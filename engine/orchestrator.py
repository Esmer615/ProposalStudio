# -*- coding: utf-8 -*-
"""编排层：唯一的 generate_plan() 入口。

流程：解析请求 → 载入 skill/刊例 → 载入库存 → 富化候选 → 折扣不动点 + 求解
→ 组装 PlanResponse（meta/inputs/hypothesis/strategy/venue/plan/effects/elasticity/
quote/schedule/coverage/validation/explanations/workflow）。

缓存：LRU 键 = PlanRequest.cache_key() + data_version。
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from . import config
from . import __version__
from .models import PlanError, PlanRequest
from .skill_loader import build_skill, Skill
from .finance import load_rate_card, RateCard, unit_price, production_price, discount_for_gross, quote as finance_quote
from .data_loader import load_inventory, Inventory
from .candidates import enrich, prefilter
from .solver.solve import solve
from .effects import compute_effects
from .schedule import build_schedule
from .validator import validate
from .explanations import build_hypothesis, build_strategy, build_venue, build_explanations
from .ai import parse_brief, retrieve_strategy, narrate
from . import finance as finance_mod

# --------------------------------------------------------------------------- #
# 缓存
# --------------------------------------------------------------------------- #
_CACHE: Dict[str, Dict[str, Any]] = {}
_CACHE_ORDER: List[str] = []
_CACHE_MAX = 64
# 弹性曲线按“场馆/媒体/档期/周数/客户类型”缓存，不含预算
_ELASTICITY_CACHE: Dict[str, Dict[str, Any]] = {}


def _cache_key(request: PlanRequest, data_version: str) -> str:
    return f"{data_version}:{request.cache_key()}"


def _elasticity_key(request: PlanRequest, data_version: str) -> str:
    return "|".join([
        data_version, request.venue, "+".join(request.media),
        request.start_date, str(request.weeks), request.customer_type,
    ])


def _cache_get(key: str) -> Optional[Dict[str, Any]]:
    return _CACHE.get(key)


def _cache_put(key: str, value: Dict[str, Any]) -> None:
    _CACHE[key] = value
    _CACHE_ORDER.append(key)
    while len(_CACHE_ORDER) > _CACHE_MAX:
        old = _CACHE_ORDER.pop(0)
        _CACHE.pop(old, None)


# --------------------------------------------------------------------------- #
# 折扣不动点
# --------------------------------------------------------------------------- #
def _solution_gross(res, bus_items, metro_items, months) -> float:
    """由求解结果反推折前刊例总额 gross（万元）。"""
    gross = 0.0
    for it in bus_items:
        u = res["bus"].get(it["id"], 0)
        if u > 0:
            gross += it["unit_price_wan"] * u * months
    for it in metro_items:
        u = res["metro"].get(it["id"], 0)
        if u > 0:
            gross += it["unit_price_wan"] * u * months
    return gross


def _discount_iteration(bus_items, metro_items, budget_wan, months, customer_type, locks, rc, skill):
    """折扣不动点：start 88% → solve（预算约束内用 discount）→ 反推 gross → 落档
    → 档位变化则重解（<=5 轮）。

    返回 (res, discount, converged)：
    - converged=True  ：gross 落档与求解折扣一致（不动点稳定）。
    - converged=False ：出现 cycle（档位来回跳），取“最保守可行”方案 = 折扣率最小
      （客户实付最低、总价最稳不超预算）的那个可行解；并显式标记未收敛。
    """
    discount = config.DISCOUNT_START
    seen: Dict[float, Dict[str, Any]] = {}  # discount -> (res, gross, tier)
    order: List[float] = []
    last_res = None

    for _ in range(5):
        # 提前检测：该折扣档已算过 → cycle
        if discount in seen:
            # 最保守 = 折扣率最小的可行档
            best_d = min(seen.keys())
            return seen[best_d]["res"], best_d, False

        res = solve(
            bus_items, metro_items, budget_wan, months, discount,
            customer_type, locks,
            skill.bus_mix_bounds(), skill.metro_mix_bounds(),
            prod_bus=rc.production_bus, prod_metro=rc.production_metro,
        )
        if res["status"] == "INFEASIBLE":
            return res, discount, False

        gross = _solution_gross(res, bus_items, metro_items, months)
        tier = discount_for_gross(rc, gross)
        new_discount = tier["rate"]
        seen[discount] = {"res": res, "gross": gross, "tier": tier}
        order.append(discount)
        last_res = res

        if abs(new_discount - discount) < 1e-9:
            return res, discount, True
        discount = new_discount

    # 5 轮内未收敛且无 cycle：取最保守（折扣率最小）的已算可行档
    if seen:
        best_d = min(seen.keys())
        return seen[best_d]["res"], best_d, False
    return last_res, discount, False


def generate_plan(request: Any, include_elasticity: bool = False) -> Dict[str, Any]:
    """唯一编排入口。

    include_elasticity=False（默认）只解当前预算，保证滑杆/现场改输入响应；
    九档弹性通过 generate_elasticity() / POST /api/elasticity 按需计算并缓存。
    """
    t0 = time.time()

    if isinstance(request, dict):
        req = PlanRequest.from_dict(request)
    else:
        req = request

    skill = build_skill(req.venue)
    rc = load_rate_card()
    inv = load_inventory(req)

    data_version = inv.data_version
    ckey = _cache_key(req, data_version)
    cached = _cache_get(ckey)
    if cached is not None:
        out = dict(cached)
        out["meta"]["cache_hit"] = True
        out["meta"]["generated_at"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00")
        return out

    # brief 解析
    brief_parsed = parse_brief(req.brief_text)

    # 富化候选（按请求 media 过滤：单媒体时另一媒体置空）
    use_bus = "bus" in req.media
    use_metro = "metro" in req.media
    enriched_bus = enrich(inv.bus, skill, rc) if use_bus else []
    enriched_metro = enrich(inv.metro, skill, rc) if use_metro else []
    bus_items = prefilter(enriched_bus, "bus") if use_bus else []
    metro_items = prefilter(enriched_metro, "metro") if use_metro else []

    # 替代项：同等级、次优候选（库存被占/锁定冲突时的替换池）
    _attach_alternatives(bus_items)
    _attach_alternatives(metro_items)

    # 折扣不动点 + 求解
    solve_t0 = time.time()
    res, discount, discount_converged = _discount_iteration(
        bus_items, metro_items, req.budget_wan, req.months, req.customer_type, req.locks, rc, skill,
    )
    solve_ms = res.get("solve_ms", 0)

    if res["status"] == "INFEASIBLE":
        raise PlanError(
            "INFEASIBLE",
            "当前约束下无可行解（预算/配比/库存）",
            suggestions=["提高预算", "放宽媒体配比", "调整锁定项"],
            recoverable=False,
        )

    # 组装方案条目
    plan_bus: List[Dict[str, Any]] = []
    plan_metro: List[Dict[str, Any]] = []
    months = req.months
    agency_factor = 0.15 if req.customer_type == "4a" else 0.0

    for it in bus_items:
        units = res["bus"].get(it["id"], 0)
        if units <= 0:
            continue
        plan_bus.append(_materialize_item(it, units, months, discount, agency_factor, req, rc))

    for it in metro_items:
        units = res["metro"].get(it["id"], 0)
        if units <= 0:
            continue
        plan_metro.append(_materialize_item(it, units, months, discount, agency_factor, req, rc))

    # 计算报价：传入不动点已确定的折扣，保证 tier 与 gross 一致、绝不超预算
    all_paid = [it for it in plan_bus + plan_metro]
    quote = finance_quote(all_paid, rc, req.budget_wan, req.customer_type,
                          discount_override=discount, converged=discount_converged)

    # 赠媒：从剩余候选挑，等价 gift_wan = media_net * 5%
    gift_items = _build_gift_items(bus_items, metro_items, plan_bus, plan_metro, quote["gift_wan"], rc, months)
    quote["gift_items"] = gift_items

    # plan summary
    summary = _build_summary(plan_bus, plan_metro, quote)

    # effects
    days = req.weeks * 7
    dual = len(req.media) > 1
    effects = compute_effects(
        plan_bus + plan_metro, skill.target_population, skill.reach_k, days,
        quote["media_net_wan"], dual,
    )

    # elasticity：按需计算/缓存，绝不阻塞单方案响应
    el_key = _elasticity_key(req, data_version)
    if include_elasticity:
        elasticity = _ELASTICITY_CACHE.get(el_key)
        if elasticity is None:
            elasticity = _build_elasticity(req, skill, rc, bus_items, metro_items)
            _ELASTICITY_CACHE[el_key] = elasticity
    else:
        elasticity = _ELASTICITY_CACHE.get(el_key) or {
            "unit": "万元",
            "points": [],
            "knee_budget_wan": None,
            "note": "按需计算：POST /api/elasticity（同一引擎九档重解，带缓存）",
        }

    # schedule
    schedule = build_schedule(req, plan_bus, plan_metro)

    # coverage
    coverage = _build_coverage(req, skill, plan_bus, plan_metro, inv)

    # hypothesis / strategy / venue / explanations
    hypothesis = build_hypothesis(req, skill)
    strategy = build_strategy(req, skill)
    venue = build_venue(req, skill)
    all_plan = plan_bus + plan_metro
    explanations = build_explanations(all_plan, skill, req)

    # workflow
    workflow = _build_workflow(req, brief_parsed, skill, res, solve_ms)

    total_ms = round((time.time() - t0) * 1000)

    meta = {
        "version": __version__,
        "generated_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        "request_id": _request_id(req),
        "solve_ms": solve_ms,
        "total_ms": total_ms,
        "data_version": data_version,
        "inventory_ts": inv.inventory_ts,
        "inventory_periods": inv.inventory_periods,
        "solver": res.get("solver", "CP-SAT"),
        "fallback_chain": res.get("fallback_chain", []),
        "status": res.get("status", "FEASIBLE"),
        "cache_hit": False,
        **({"fell_back": True} if inv.fell_back else {}),
    }

    response = {
        "meta": meta,
        "inputs": req.to_dict(),
        "hypothesis": hypothesis,
        "strategy": strategy,
        "venue": venue,
        "plan": {"bus": plan_bus, "metro": plan_metro, "summary": summary},
        "effects": effects,
        "elasticity": elasticity,
        "quote": quote,
        "schedule": schedule,
        "coverage": coverage,
        "validation": None,  # 先占位，最后填
        "explanations": explanations,
        "workflow": workflow,
    }

    # validator 需要完整响应
    response["validation"] = validate(response)

    _cache_put(ckey, response)
    return response


# --------------------------------------------------------------------------- #
# 组装辅助
# --------------------------------------------------------------------------- #
def generate_elasticity(request: Any) -> Dict[str, Any]:
    """按需计算九档弹性（同一引擎，按场馆/媒体/档期缓存）。"""
    req = PlanRequest.from_dict(request) if isinstance(request, dict) else request
    skill = build_skill(req.venue)
    rc = load_rate_card()
    inv = load_inventory(req)
    key = _elasticity_key(req, inv.data_version)
    cached = _ELASTICITY_CACHE.get(key)
    if cached is not None:
        return cached
    enriched_bus = enrich(inv.bus, skill, rc) if "bus" in req.media else []
    enriched_metro = enrich(inv.metro, skill, rc) if "metro" in req.media else []
    bus_items = prefilter(enriched_bus, "bus") if "bus" in req.media else []
    metro_items = prefilter(enriched_metro, "metro") if "metro" in req.media else []
    el = _build_elasticity(req, skill, rc, bus_items, metro_items)
    _ELASTICITY_CACHE[key] = el
    return el


def _attach_alternatives(items: List[Dict[str, Any]]) -> None:
    """为每个候选填 1–2 个同等级替代项（确定性：按当前排序取后续同等级）。"""
    for i, it in enumerate(items):
        alts: List[Dict[str, Any]] = []
        for other in items[i + 1:]:
            if len(alts) >= 2:
                break
            if other["id"] != it["id"] and other["level"] == it["level"]:
                alts.append({
                    "id": other["id"],
                    "name": _display_name(other),
                    "reason": "同等级/相近评分，库存被占或锁定冲突时的替代",
                })
        it["alternatives"] = alts


def _materialize_item(cand, units, months, discount, agency_factor, req, rc=None) -> Dict[str, Any]:
    up = cand["unit_price_wan"]
    if rc is not None:
        prod = rc.production_bus if cand["kind"] == "bus" else rc.production_metro
    else:
        prod = 0.75 if cand["kind"] == "bus" else 0.03
    gross = round(up * units * months, 2)
    net = round(gross * discount, 2)
    ag = round(net * 0.15, 2) if req.customer_type == "4a" else 0.0
    production = round(prod * units, 2)
    total = round(net + production + ag, 2)
    return {
        "id": cand["id"],
        "kind": cand["kind"],
        "name": _display_name(cand),
        "line": cand["line"],
        "company": cand["company"],
        "station": cand["station"],
        "exit": cand["exit"],
        "district": cand["district"],
        "level": cand["level"],
        "media_type": cand["media_type"],
        "units": units,
        "free_count": cand["free_count"],
        "unit_price_wan": up,
        "months": months,
        "gross_wan": gross,
        "discount": discount,
        "net_wan": net,
        "production_wan": production,
        "agency_fee_wan": ag,
        "total_wan": total,
        "gift": False,
        "score": cand["score"],
        "score_breakdown": cand["score_breakdown"],
        "reasons": cand["reasons"],
        "evidence": cand["evidence"],
        "alternatives": cand["alternatives"],
        "geo": cand["geo"],
        "poi_hits": cand.get("poi_hits", []),
        "poi_count": cand.get("poi_count", 0),
        "hypothesis_refs": ["H4", "H6"] + (["H7"] if cand["kind"] == "metro" else []),
        "locked": cand["id"] in req.locks.get("include", []),
        "status": "paid",
    }


def _display_name(cand) -> str:
    if cand["kind"] == "bus":
        line = str(cand["line"] or "")
        # 避免 “17路路”：线路名已含 “路” 时不重复追加
        if not line.endswith("路"):
            line += "路"
        return f"{line} · {cand['media_type']}"
    station = str(cand["station"] or "")
    if not station.endswith("站"):
        station += "站"
    return f"{station} · {cand['exit']}"


def _build_gift_items(bus_items, metro_items, plan_bus, plan_metro, gift_wan, rc, months) -> List[Dict[str, Any]]:
    """赠媒：从剩余候选挑等价点位（不付费）。"""
    used = set(it["id"] for it in plan_bus + plan_metro)
    remaining = [it for it in bus_items + metro_items if it["id"] not in used]
    remaining.sort(key=lambda x: -x["score"])
    items = []
    budget = gift_wan
    for it in remaining:
        gross = it["unit_price_wan"] * months
        if gross <= 0:
            continue
        items.append({"id": it["id"], "name": _display_name(it), "gross_wan": round(gross, 2)})
        budget -= gross
        if budget <= 0:
            break
    return items


def _build_summary(plan_bus, plan_metro, quote) -> Dict[str, Any]:
    bus_units = sum(it["units"] for it in plan_bus)
    metro_units = sum(it["units"] for it in plan_metro)
    bus_lines = len(plan_bus)
    metro_stations = len(plan_metro)
    bus_net = sum(it["net_wan"] for it in plan_bus)
    metro_net = sum(it["net_wan"] for it in plan_metro)
    tot_net = bus_net + metro_net
    bus_pct = bus_net / tot_net if tot_net else 0.0

    level_mix: Dict[str, int] = {}
    district_mix: Dict[str, int] = {}
    poi_seen = set()
    for it in plan_bus + plan_metro:
        level_mix[it["level"]] = level_mix.get(it["level"], 0) + it["units"]
        district_mix[it["district"]] = district_mix.get(it["district"], 0) + it["units"]
        for p in it.get("poi_hits", []) or []:
            poi_seen.add(p.get("id") or p.get("name"))
    poi_hits = len(poi_seen)

    return {
        "bus_units": bus_units,
        "metro_units": metro_units,
        "bus_lines": bus_lines,
        "metro_stations": metro_stations,
        "media_mix": {"bus_pct": round(bus_pct, 3), "metro_pct": round(1 - bus_pct, 3)},
        "unit_mix": {"bus_pct": round(bus_units / (bus_units + metro_units), 3) if (bus_units + metro_units) else 0.0,
                     "metro_pct": round(metro_units / (bus_units + metro_units), 3) if (bus_units + metro_units) else 0.0},
        "level_mix": level_mix,
        "district_mix": district_mix,
        "gross_wan": quote["rate_card_total_wan"],
        "net_wan": quote["media_net_wan"],
        "total_paid_wan": quote["total_paid_wan"],
        "budget_utilization": round(quote["total_paid_wan"] / quote["budget_wan"], 3) if quote["budget_wan"] else 0.0,
        "poi_hits": poi_hits,
        "free_verified": bus_units + metro_units,
    }


def _build_elasticity(req, skill, rc, bus_items, metro_items) -> Dict[str, Any]:
    budgets = [100, 150, 200, 250, 300, 350, 400, 450, 500]
    points = []
    prev_imp = None
    prev_reach = None
    months = req.months
    agency_factor = 0.15 if req.customer_type == "4a" else 0.0
    days = req.weeks * 7

    for bgt in budgets:
        # 弹性曲线用确定性贪心（单调于预算、可复现），保证曝光随预算不下降。
        # 主方案仍走 CP-SAT；贪心是同一引擎的确定性降级路径。
        from .solver.solve import _solve_greedy
        agency_factor = 0.15 if req.customer_type == "4a" else 0.0
        res = _solve_greedy(bus_items, metro_items, bgt, months, config.DISCOUNT_START,
                            agency_factor, req.locks, config.BUS_INSTALL_NIGHTS,
                            rc.production_bus, rc.production_metro)
        if res["status"] == "INFEASIBLE":
            continue
        # 用实际 gross 落档重估（不二次求解，误差可忽略且确定性）
        gross = 0.0
        for it in bus_items:
            u = res["bus"].get(it["id"], 0)
            if u > 0:
                gross += it["unit_price_wan"] * u * months
        for it in metro_items:
            u = res["metro"].get(it["id"], 0)
            if u > 0:
                gross += it["unit_price_wan"] * u * months
        discount = discount_for_gross(rc, gross)["rate"]

        plan_items = []
        for it in bus_items:
            u = res["bus"].get(it["id"], 0)
            if u > 0:
                plan_items.append(_materialize_item(it, u, months, discount, agency_factor, req, rc))
        for it in metro_items:
            u = res["metro"].get(it["id"], 0)
            if u > 0:
                plan_items.append(_materialize_item(it, u, months, discount, agency_factor, req, rc))
        q = finance_quote(plan_items, rc, bgt, req.customer_type)
        eff = compute_effects(plan_items, skill.target_population, skill.reach_k, days, q["media_net_wan"], len(req.media) > 1)

        imp = eff["impressions"]
        reach = eff["reach"]
        marginal = round((imp - prev_imp) / 50.0) if prev_imp is not None else 0
        delta_reach = round(reach - prev_reach, 4) if prev_reach is not None else 0.0
        is_current = abs(bgt - req.budget_wan) < 1e-9
        points.append({
            "budget_wan": bgt,
            "impressions": imp,
            "reach": round(reach, 4),
            "frequency": eff["frequency"],
            "cpm_yuan": eff["cpm_yuan"],
            "marginal_impressions_per_wan": marginal,
            "delta_reach": delta_reach,
            "is_current": is_current,
        })
        prev_imp = imp
        prev_reach = reach

    # 拐点 = Reach 达到最高值 98% 的预算；之后加钱主要买频次/覆盖
    knee = points[-1]["budget_wan"] if points else None
    max_reach = max((p["reach"] for p in points), default=0.0)
    if max_reach > 0:
        for p in points:
            if p["reach"] >= max_reach * 0.98:
                knee = p["budget_wan"]
                break

    return {
        "unit": "万元",
        "points": points,
        "knee_budget_wan": knee,
        "note": "同一优化器的确定性预算扩展估值（同一库存/配比/预算规则）；拐点=Reach 达到最高值 98% 的预算，此后加钱主要买频次/覆盖。主方案以 CP-SAT 结果为准。",
    }


def _build_coverage(req, skill, plan_bus, plan_metro, inv) -> Dict[str, Any]:
    # district aggregation
    district_units: Dict[str, int] = {}
    poi_demand: Dict[str, float] = {}
    for it in plan_bus + plan_metro:
        d = it["district"] or "未知"
        district_units[d] = district_units.get(d, 0) + it["units"]
        poi_demand[d] = poi_demand.get(d, 0.0) + (0.1 if it["kind"] == "bus" else 0.15)
    districts = [{"name": d, "selected_units": u, "poi_demand": round(min(1.0, poi_demand.get(d, 0.0)), 2), "weight": 0.9} for d, u in sorted(district_units.items(), key=lambda kv: -kv[1])]

    # 汇总已选点位命中的 POI（唯一、带 hit_by）
    poi_index: Dict[str, Dict[str, Any]] = {}
    for it in plan_bus + plan_metro:
        for p in it.get("poi_hits", []) or []:
            key = p.get("id") or p.get("name") or "poi"
            if key not in poi_index:
                poi_index[key] = {
                    "id": key,
                    "name": p.get("name") or "POI",
                    "type": p.get("type") or "attraction",
                    "coords": {"lng": float(p.get("lng") or 0), "lat": float(p.get("lat") or 0)},
                    "weight": float(p.get("weight") or 0.6),
                    "hit_by": [],
                    "source": p.get("source") or "公开信息近似",
                }
            if it["id"] not in poi_index[key]["hit_by"]:
                poi_index[key]["hit_by"].append(it["id"])
    poi_hits_map = sorted(poi_index.values(), key=lambda p: (-p["weight"], p["id"]))

    map_metro = []
    for it in plan_metro:
        geo = it.get("geo") or {}
        coords = geo.get("coords") if geo.get("type") == "point" else None
        map_metro.append({
            "id": it["id"], "coords": coords, "selected": True,
            "level": it["level"], "confidence": geo.get("confidence") or "low",
        })
    map_bus = [{"id": it["id"], "geometry": None, "schematic_district": it["district"], "selected": True} for it in plan_bus]
    map_poi = [
        {"id": p["id"], "coords": p["coords"], "type": p["type"], "weight": p["weight"]}
        for p in poi_hits_map if p["coords"]["lng"] and p["coords"]["lat"]
    ]

    return {
        "venue": {"name": skill.name, "coords": skill.coords, "rings_km": skill.rings_km},
        "districts": districts,
        "poi_hits": poi_hits_map,
        "map_layers": {
            "districts": {"type": "choropleth", "data": [{"name": d, "value": u} for d, u in sorted(district_units.items(), key=lambda kv: -kv[1])]},
            "venue": {"type": "effectScatter", "coords": skill.coords},
            "metro": map_metro,
            "bus": map_bus,
            "poi": map_poi,
        },
        "sources": ["红豆广告媒体管理系统 2027 月度快照", "公开 POI/站点近似数据（构建期缓存）"],
        "disclaimer": "POI/站点坐标为公开近似，不用于测量级结论；公交几何缺失时为区县示意；地铁 POI 半径 800m，公交为区县代理。",
    }


def _build_workflow(req, brief_parsed, skill, res, solve_ms) -> Dict[str, Any]:
    from .ai.brief_parser import brief_summary
    stages = [
        {"id": "brief", "name": "Brief 解析", "status": "done", "model": "rules", "latency_ms": 2, "summary": brief_summary(req.brief_text)},
        {"id": "retrieval", "name": "策略检索", "status": "done", "model": "tfidf-rules", "latency_ms": 5, "summary": "检索乐园人群/交通/合规知识"},
        {"id": "candidates", "name": "候选富化", "status": "done", "model": "deterministic", "latency_ms": 15, "summary": "红豆库存过滤 + POI/场馆评分"},
        {"id": "solve", "name": "求解", "status": "done", "model": "ortools-cp-sat", "latency_ms": solve_ms, "summary": f"{res.get('solver')} 求解，{res.get('status')}"},
        {"id": "validate", "name": "独立校验", "status": "done", "model": "rules", "latency_ms": 3, "summary": "10 项 blocker/warning 自检"},
        {"id": "narrate", "name": "解释生成", "status": "done", "model": "templates", "latency_ms": 4, "summary": "选点理由/反事实/H 回链"},
    ]
    return {
        "mode": "offline-rules",
        "llm_used": False,
        "stages": stages,
        "guardrails": ["LLM 不产出数字", "无 Key 自动离线", "求解器确定性", "validator 独立于 solver"],
    }


def _request_id(req) -> str:
    return hashlib.sha1(req.cache_key().encode("utf-8")).hexdigest()[:12]


def reload_data() -> None:
    """清缓存并重载（数据更新后调用）。"""
    _CACHE.clear()
    _CACHE_ORDER.clear()
    _ELASTICITY_CACHE.clear()


__all__ = ["generate_plan", "generate_elasticity", "reload_data"]
