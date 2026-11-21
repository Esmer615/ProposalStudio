# -*- coding: utf-8 -*-
"""结果分析：把多个引擎方案变成可比较、可解释、可追问的结论。

所有数字都从 PlanResponse 读取或做明确标注的算术派生（例如
reach_people = reach × target_population）。不做转化归因，不把公交与地铁
的 reach 相加（引擎本身就是单条饱和曲线）。
"""
from __future__ import annotations

from collections import Counter
from typing import Any, Dict, Iterable, List, Optional

from .contracts import BriefState, round_num
from .strategy import objective_label

LEVEL_ORDER = {"S": 0, "A++": 1, "A+": 2, "AA": 3, "unknown": 4}
MEDIA_LABEL = {"bus": "公交", "metro": "地铁"}


# --------------------------------------------------------------------------- #
# 单方案指标
# --------------------------------------------------------------------------- #
def metrics_from_plan(response: Dict[str, Any], catalog: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    inputs = response.get("inputs") or {}
    summary = (response.get("plan") or {}).get("summary") or {}
    quote = response.get("quote") or {}
    effects = response.get("effects") or {}
    validation = response.get("validation") or {}
    coverage = response.get("coverage") or {}
    schedule = response.get("schedule") or {}
    meta = response.get("meta") or {}
    strategy = response.get("strategy") or {}

    budget = _as_float(inputs.get("budget_wan"))
    total_paid = _as_float(quote.get("total_paid_wan"))
    media_net = _as_float(quote.get("media_net_wan"))
    impressions = _as_float(effects.get("impressions"))
    reach_pct = _as_float(effects.get("reach"))
    target_pop = _as_float(effects.get("target_population"))
    reach_people = round(reach_pct * target_pop)
    frequency = _as_float(effects.get("frequency"))
    cpm = _as_float(effects.get("cpm_yuan"))

    utilization = total_paid / budget if budget else 0.0
    media_net_utilization = media_net / budget if budget else 0.0
    impressions_per_wan = impressions / total_paid if total_paid else 0.0
    reach_people_per_wan = reach_people / total_paid if total_paid else 0.0

    poi_hits_list = coverage.get("poi_hits") or []
    poi_hits = int(summary.get("poi_hits") or len(poi_hits_list))
    poi_types = Counter(str(p.get("type")) for p in poi_hits_list if p.get("type"))
    poi_type_labels = Counter({t: n for t, n in poi_types.items()})

    level_mix = {str(k): int(v) for k, v in (summary.get("level_mix") or {}).items()}
    total_units = sum(level_mix.values())
    premium_units = sum(v for k, v in level_mix.items() if k in ("S", "A++", "A+"))
    premium_share = premium_units / total_units if total_units else 0.0

    district_mix = {str(k): int(v) for k, v in (summary.get("district_mix") or {}).items()}
    top_districts = sorted(district_mix.items(), key=lambda kv: (-kv[1], kv[0]))[:5]

    checks = validation.get("checks") or []
    blockers = [c for c in checks if c.get("level") == "blocker" and not c.get("passed")]
    warnings = [c for c in checks if c.get("level") == "warning" and not c.get("passed")]

    profile = ((catalog or {}).get("venue_profiles") or {}).get(inputs.get("venue")) or {}
    venue_source = profile.get("source") or "venue profile"
    venue_notes = profile.get("compliance_notes") or []

    data_quality = {
        "inventory": {
            "source": "红豆广告媒体管理系统快照",
            "data_version": meta.get("data_version"),
            "timestamp": meta.get("inventory_ts"),
            "periods": meta.get("inventory_periods"),
            "note": "库存为只读快照，上刊前需重新核对占用。",
        },
        "reach": {
            "source": "模型估算",
            "method": effects.get("formula"),
            "parameters": effects.get("parameters"),
            "disclaimer": effects.get("disclaimer"),
        },
        "poi": {
            "source": "公开近似 POI 库（构建期缓存）",
            "confidence": "approx",
            "note": "POI 坐标/类型为公开信息推算，不用于测量级结论。",
        },
        "venue_profile": {
            "source": venue_source,
            "confidence": "策划假设" if profile else "unknown",
            "notes": venue_notes,
        },
        "discount": {
            "source": "刊例落档假设",
            "tier": quote.get("discount_tier"),
            "notes": quote.get("notes") or [],
        },
        "traffic_platform": {
            "source": "未接入",
            "note": "当前构建没有可视化平台实测区域人流，所有 Reach/曝光均为模型估算。",
        },
    }

    schedule_summary = {
        "go_live": schedule.get("go_live"),
        "take_down": schedule.get("take_down"),
        "total_days": schedule.get("total_days"),
        "batches": len(schedule.get("batches") or []),
        "night_capacity": schedule.get("night_capacity"),
        "monitoring": [m.get("name") for m in (schedule.get("monitoring") or [])],
        "compensation": schedule.get("compensation"),
        "risks": schedule.get("risks") or [],
    }

    return {
        "budget_wan": round_num(budget, 2),
        "total_paid_wan": round_num(total_paid, 2),
        "media_net_wan": round_num(media_net, 2),
        "budget_slack_wan": round_num(max(0.0, budget - total_paid), 2),
        "utilization": round_num(utilization, 4),
        "media_net_utilization": round_num(media_net_utilization, 4),
        "absorption_status": _absorption_status(utilization),
        "impressions": int(impressions),
        "impressions_per_wan": round_num(impressions_per_wan, 1),
        "reach_pct": round_num(reach_pct, 4),
        "reach_pct_label": f"{reach_pct:.1%}",
        "reach_people": int(reach_people),
        "reach_people_per_wan": round_num(reach_people_per_wan, 1),
        "frequency": round_num(frequency, 2),
        "cpm_yuan": round_num(cpm, 2),
        "target_population": int(target_pop),
        "target_population_source": "venue profile（策划假设，非实测去重）",
        "target_population_profile_value": profile.get("target_population"),
        "grp": round_num(effects.get("grp"), 1),
        "reach_cap": (effects.get("parameters") or {}).get("reach_cap"),
        "saturation": round_num((reach_pct / (effects.get("parameters") or {}).get("reach_cap", 0.82)) if reach_pct else 0, 3),
        "media_mix_cost": summary.get("media_mix") or {},
        "media_mix_impressions": {m.get("media"): m.get("share") for m in (effects.get("by_media") or [])},
        "bus_units": int(summary.get("bus_units") or 0),
        "bus_lines": int(summary.get("bus_lines") or 0),
        "metro_units": int(summary.get("metro_units") or 0),
        "metro_stations": int(summary.get("metro_stations") or 0),
        "item_count": len((response.get("plan") or {}).get("bus") or []) + len((response.get("plan") or {}).get("metro") or []),
        "poi_hits": poi_hits,
        "poi_types": dict(poi_type_labels),
        "level_mix": level_mix,
        "premium_share": round_num(premium_share, 3),
        "district_mix": district_mix,
        "top_districts": [{"district": d, "units": n} for d, n in top_districts],
        "gross_wan": round_num(quote.get("rate_card_total_wan"), 2),
        "discount": round_num(quote.get("discount"), 3),
        "discount_label": (quote.get("discount_tier") or {}).get("label"),
        "discount_converged": bool(quote.get("discount_converged", True)),
        "production_wan": round_num(quote.get("production_wan"), 2),
        "agency_fee_wan": round_num(quote.get("agency_fee_wan"), 2),
        "gift_wan": round_num(quote.get("gift_wan"), 2),
        "allocation_passed": bool((quote.get("allocation_check") or {}).get("passed")),
        "validation": {
            "passed": bool(validation.get("passed")),
            "blockers": blockers,
            "warnings": warnings,
            "checks": checks,
            "limitations": validation.get("limitations") or [],
            "inventory_check": validation.get("inventory_check") or {},
        },
        "schedule": schedule_summary,
        "strategy": {
            "one_liner": strategy.get("one_liner"),
            "audience": strategy.get("audience"),
            "media_roles": strategy.get("media_roles"),
            "mix_rationale": strategy.get("mix_rationale"),
            "compliance": strategy.get("compliance"),
            "avoid": strategy.get("avoid"),
        },
        "data_quality": data_quality,
        "meta": {
            "data_version": meta.get("data_version"),
            "solver": meta.get("solver"),
            "status": meta.get("status"),
            "solve_ms": meta.get("solve_ms"),
            "total_ms": meta.get("total_ms"),
            "cache_hit": meta.get("cache_hit"),
            "inventory_ts": meta.get("inventory_ts"),
            "fallback_chain": meta.get("fallback_chain") or [],
        },
    }


def _absorption_status(utilization: float) -> str:
    if utilization >= 0.85:
        return "absorbed"
    if utilization >= 0.70:
        return "partial"
    return "underused"


def _as_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


# --------------------------------------------------------------------------- #
# 风险
# --------------------------------------------------------------------------- #
def build_risks(
    metrics: Dict[str, Any],
    brief: BriefState,
    policy: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    policy = policy or {}
    thresholds = policy.get("thresholds") or {}
    absorption_floor = float(thresholds.get("absorption_floor", 0.85))
    reach_low = float(thresholds.get("reach_low", 0.45))
    frequency_high = float(thresholds.get("frequency_high", 20))
    saturation_high = float(thresholds.get("saturation_high", 0.95))
    capacity_high = float(thresholds.get("capacity_high", 0.80))

    risks: List[Dict[str, Any]] = []
    val = metrics.get("validation") or {}

    for check in val.get("blockers") or []:
        risks.append({
            "code": check.get("id") or "BLOCKER",
            "level": "critical",
            "message": f"独立校验未通过：{check.get('name')} — {check.get('detail')}",
            "evidence": check,
            "action": "先修复该 blocker，再谈推荐；客户提案不应导出。",
        })

    utilization = float(metrics.get("utilization") or 0)
    if utilization < absorption_floor:
        risks.append({
            "code": "BUDGET_UNDERUSED",
            "level": "high",
            "message": f"预算使用率 {utilization:.1%}，低于 {absorption_floor:.0%}；实际落地 {metrics.get('total_paid_wan')} 万，剩余 {metrics.get('budget_slack_wan')} 万。",
            "evidence": {
                "utilization": utilization,
                "total_paid_wan": metrics.get("total_paid_wan"),
                "budget_slack_wan": metrics.get("budget_slack_wan"),
            },
            "action": "不要假装花满；给出两个选择：放宽媒介/点位约束，或降低预算并说明理由。",
        })

    reach_pct = float(metrics.get("reach_pct") or 0)
    if reach_pct < reach_low:
        risks.append({
            "code": "REACH_LOW",
            "level": "medium",
            "message": f"目标人群 Reach 仅 {reach_pct:.1%}（模型估算，目标人群 {metrics.get('target_population'):,}）。",
            "evidence": {"reach_pct": reach_pct, "target_population": metrics.get("target_population")},
            "action": "说明这是估算口径；若客户要覆盖，考虑加预算或扩媒体组合。",
        })

    frequency = float(metrics.get("frequency") or 0)
    if frequency > frequency_high:
        risks.append({
            "code": "FREQUENCY_HIGH",
            "level": "medium" if frequency < frequency_high * 1.5 else "high",
            "message": f"平均频次 {frequency:.1f} 次，边际触达可能转向重复曝光。",
            "evidence": {"frequency": frequency},
            "action": "用预算弹性说明“再加钱主要买频次”；必要时把增量预算换媒体/换点位。",
        })

    saturation = float(metrics.get("saturation") or 0)
    if saturation >= saturation_high:
        risks.append({
            "code": "REACH_SATURATED",
            "level": "medium",
            "message": f"Reach 已达模型上限的 {saturation:.0%}，继续加预算的到达增量有限。",
            "evidence": {"saturation": saturation, "reach_cap": metrics.get("reach_cap")},
            "action": "把增量预算用于新客群/新档期，而不是继续堆同一批点位。",
        })

    cap = (metrics.get("schedule") or {}).get("night_capacity") or {}
    total_days = (metrics.get("schedule") or {}).get("total_days") or 0
    if cap and total_days:
        bus_per_night = int(cap.get("bus_per_night") or 0) * int(cap.get("nights") or 1)
        metro_per_night = int(cap.get("metro_per_night") or 0) * int(cap.get("nights") or 1)
        bus_used = metrics.get("bus_units") or 0
        metro_used = metrics.get("metro_units") or 0
        bus_util = bus_used / bus_per_night if bus_per_night else 0
        metro_util = metro_used / metro_per_night if metro_per_night else 0
        if max(bus_util, metro_util) > capacity_high:
            risks.append({
                "code": "SCHEDULE_CAPACITY",
                "level": "medium",
                "message": f"施工产能已用 {max(bus_util, metro_util):.0%}（公交 {bus_used}/{bus_per_night} 辆，地铁 {metro_used}/{metro_per_night} 口）。",
                "evidence": {"bus_utilization": round_num(bus_util, 3), "metro_utilization": round_num(metro_util, 3)},
                "action": "把长尾点位延后 1–2 周上刊，或预留雨备夜。",
            })

    if metrics.get("poi_hits", 0) < 5:
        risks.append({
            "code": "POI_LOW",
            "level": "medium",
            "message": f"仅命中 {metrics.get('poi_hits')} 个家庭/亲子 POI，人群相关性可能不足。",
            "evidence": {"poi_hits": metrics.get("poi_hits")},
            "action": "检查场馆档案的 POI 权重与候选库存；不要用通用点位冒充亲子点位。",
        })

    if metrics.get("discount_converged") is False:
        risks.append({
            "code": "DISCOUNT_NOT_CONVERGED",
            "level": "high",
            "message": "折扣不动点未收敛，报价可能不是全单落档的稳定解。",
            "evidence": {"discount": metrics.get("discount"), "discount_label": metrics.get("discount_label")},
            "action": "以保守折扣档为准；导出前复核报价分摊。",
        })

    if not metrics.get("allocation_passed"):
        risks.append({
            "code": "ALLOCATION_MISMATCH",
            "level": "critical",
            "message": "逐行分摊加总与总报价不一致。",
            "evidence": metrics.get("validation", {}).get("checks"),
            "action": "阻止导出；先修报价分摊。",
        })

    # 媒体配比与策略目标的偏差
    roles = (metrics.get("strategy") or {}).get("media_roles") or []
    cost_mix = metrics.get("media_mix_cost") or {}
    bus_cost = float(cost_mix.get("bus_pct") or 0)
    for role in roles:
        target = float(role.get("share_target") or 0)
        if target <= 0:
            continue
        actual = bus_cost if role.get("media") == "bus" else 1 - bus_cost
        if abs(actual - target) > 0.15:
            risks.append({
                "code": "MEDIA_MIX_DEVIATION",
                "level": "low",
                "message": f"{MEDIA_LABEL.get(role.get('media'), role.get('media'))}实际花费占比 {actual:.0%}，策略目标 {target:.0%}，偏差超过 15 个百分点。",
                "evidence": {"media": role.get("media"), "target": target, "actual": round_num(actual, 3)},
                "action": "在话术里解释是库存/单价约束导致，而不是策略本意。",
            })

    # brief 里的违规承诺
    for flag in brief.compliance_flags or []:
        risks.append({
            "code": flag.get("code") or "COMPLIANCE_PHRASE",
            "level": flag.get("level") or "high",
            "message": f"客户 brief 出现需要改写的表述（{flag.get('code')}），不能原样写进提案。",
            "evidence": flag,
            "action": flag.get("guidance") or "改用合规口径：不承诺到园/ROI/销量，不投校内。",
        })

    # 估算口径必须主动披露
    risks.append({
        "code": "ESTIMATE_DISCLOSURE",
        "level": "low",
        "message": "曝光/Reach/频次/CPM 为模型估算；POI 坐标为公开近似；当前未接平台实测人流。",
        "evidence": {"data_quality": metrics.get("data_quality", {}).get("traffic_platform")},
        "action": "每个数字带口径；主动说明三条局限，不承诺到园人数或财务 ROI。",
    })

    order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    risks.sort(key=lambda r: (order.get(str(r.get("level")), 9), str(r.get("code"))))
    return risks


# --------------------------------------------------------------------------- #
# 场景对比 / 评分
# --------------------------------------------------------------------------- #
def score_scenarios(
    scenarios: List[Dict[str, Any]],
    objective: str,
    policy: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    policy = policy or {}
    absorption_floor = float((policy.get("thresholds") or {}).get("absorption_floor", 0.85))
    valid = [s for s in scenarios if s.get("ok") and s.get("metrics")]
    if not valid:
        return scenarios

    max_reach = max((s["metrics"].get("reach_people") or 0) for s in valid) or 1
    max_eff = max((s["metrics"].get("reach_people_per_wan") or 0) for s in valid) or 1
    max_poi = max((s["metrics"].get("poi_hits") or 0) for s in valid) or 1
    max_premium = max((s["metrics"].get("premium_share") or 0) for s in valid) or 1

    weights_by_objective = {
        "reach": {"reach": 0.60, "efficiency": 0.15, "absorption": 0.15, "poi": 0.10},
        "precision": {"reach": 0.20, "efficiency": 0.15, "absorption": 0.20, "poi": 0.45},
        "efficiency": {"reach": 0.15, "efficiency": 0.55, "absorption": 0.25, "poi": 0.05},
        "brand": {"reach": 0.50, "efficiency": 0.10, "absorption": 0.20, "poi": 0.20},
        "balanced": {"reach": 0.30, "efficiency": 0.25, "absorption": 0.25, "poi": 0.20},
    }
    weights = dict(weights_by_objective.get(objective, weights_by_objective["balanced"]))
    weights.update(policy.get("score_weights", {}).get(objective, {}))

    for s in scenarios:
        if not s.get("ok") or not s.get("metrics"):
            s["score"] = {"total": 0.0, "breakdown": {}, "rank": None, "feasible": False}
            continue
        m = s["metrics"]
        breakdown = {
            "reach": (m.get("reach_people") or 0) / max_reach,
            "efficiency": (m.get("reach_people_per_wan") or 0) / max_eff,
            "poi": (m.get("poi_hits") or 0) / max_poi,
            "premium": (m.get("premium_share") or 0) / max_premium,
            "absorption": min(1.0, (m.get("utilization") or 0) / 0.95),
        }
        precision_score = 0.6 * breakdown["poi"] + 0.4 * breakdown["premium"]
        components = {
            "reach": breakdown["reach"],
            "efficiency": breakdown["efficiency"],
            "poi": precision_score,
            "absorption": breakdown["absorption"],
        }
        total = sum(weights[k] * components[k] for k in weights)
        if (m.get("utilization") or 0) < absorption_floor:
            total *= 0.75
        if (m.get("frequency") or 0) > 25:
            total *= 0.90
        if not (m.get("validation") or {}).get("passed"):
            total = 0.0
        s["score"] = {
            "total": round_num(total * 100, 1),
            "breakdown": {k: round_num(v, 3) for k, v in components.items()},
            "raw": {k: round_num(v, 4) for k, v in breakdown.items()},
            "rank": None,
            "feasible": bool((m.get("validation") or {}).get("passed")),
        }

    ranked = sorted(
        [s for s in scenarios if s.get("score", {}).get("feasible")],
        key=lambda s: (-float(s["score"]["total"]), str(s.get("id"))),
    )
    for idx, s in enumerate(ranked, start=1):
        s["score"]["rank"] = idx
    return scenarios


def recommend(
    scenarios: List[Dict[str, Any]],
    brief: BriefState,
    policy: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    policy = policy or {}
    absorption_floor = float((policy.get("thresholds") or {}).get("absorption_floor", 0.85))
    feasible = [s for s in scenarios if s.get("score", {}).get("feasible")]
    if not feasible:
        return {
            "primary_scenario": None,
            "verdict": "not_recommended",
            "summary": "所有场景都未通过独立校验，不能给客户提案。",
            "why": [],
            "tradeoffs": [],
            "alternatives": [],
            "next_actions": ["检查输入/库存/约束", "查看 validation.blockers"],
        }

    ranked = sorted(feasible, key=lambda s: (-float(s["score"]["total"]), str(s.get("id"))))
    top = ranked[0]
    base = next((s for s in feasible if s.get("is_base")), None)

    # 场景是对客户原始需求的敏感性分析，不是替客户改预算。
    # 只要基准方案可执行且预算基本花出去，默认推荐基准；只有基准明显不可行
    # （预算使用率 <85%）时，才把更合适的下探/媒体参考升为主推荐。
    if base is None:
        primary = top
    else:
        base_util = float((base.get("metrics") or {}).get("utilization") or 0)
        if base_util >= absorption_floor:
            primary = base
        else:
            better = [
                s for s in ranked
                if s is not base
                and float((s.get("metrics") or {}).get("utilization") or 0) >= absorption_floor
            ]
            primary = better[0] if better else base

    m = primary.get("metrics") or {}
    verdict = "recommend"
    if not (m.get("validation") or {}).get("passed"):
        verdict = "not_recommended"
    elif (m.get("utilization") or 0) < absorption_floor:
        verdict = "recommend_with_caveats"
    elif (primary.get("risks") or []):
        high = [r for r in primary["risks"] if r.get("level") in ("critical", "high")]
        if high:
            verdict = "recommend_with_caveats"

    summary = (
        f"建议以「{primary.get('label')}」推进：预算 {_fmt_wan(m.get('budget_wan'))}，"
        f"实际落地 {_fmt_wan(m.get('total_paid_wan'))}（使用率 {_fmt_pct(m.get('utilization'))}），"
        f"总曝光 {_fmt_int(m.get('impressions'))} 人次，目标人群 Reach {m.get('reach_pct_label')}（模型估算），"
        f"频次 {m.get('frequency')}，混合 CPM {m.get('cpm_yuan')} 元。"
    )

    why: List[str] = []
    if (m.get("utilization") or 0) >= absorption_floor:
        why.append(f"预算使用率 {_fmt_pct(m.get('utilization'))}，钱基本花出去了。")
    else:
        why.append(f"预算使用率仅 {_fmt_pct(m.get('utilization'))}，必须主动说明未花完的部分。")
    why.append(f"目标人群 Reach {m.get('reach_pct_label')}，目标人群口径 {_fmt_int(m.get('target_population'))}（策划假设，非实测去重）。")
    why.append(f"命中 {m.get('poi_hits')} 个亲子/家庭 POI，公交 {m.get('bus_units')} 辆 / 地铁 {m.get('metro_units')} 口。")
    if primary.get("is_base"):
        why.append("客户原始输入即可执行；不替你改预算或媒体组合，其他场景作为取舍参考。")

    higher_scored = [
        s for s in ranked
        if s is not primary and float((s.get("score") or {}).get("total") or 0) > float((primary.get("score") or {}).get("total") or 0)
    ]
    if higher_scored:
        why.append(
            "部分敏感性场景在评分上更高，但评分是按 objective 视角的相对排序，"
            "不等于应替客户改预算/改媒体；它们作为取舍列出，不替代原始需求。"
        )

    alternatives = []
    for s in ranked:
        if s is primary:
            continue
        sm = s.get("metrics") or {}
        tradeoffs = s.get("tradeoffs") or []
        alternatives.append({
            "scenario_id": s.get("id"),
            "label": s.get("label"),
            "score": (s.get("score") or {}).get("total"),
            "when_to_use": s.get("use_when") or s.get("intent") or "",
            "tradeoff": str(tradeoffs[0]) if tradeoffs else "",
            "delta_vs_primary": {
                "budget_wan": round_num((sm.get("budget_wan") or 0) - (m.get("budget_wan") or 0), 2),
                "reach_people": int((sm.get("reach_people") or 0) - (m.get("reach_people") or 0)),
                "utilization": round_num((sm.get("utilization") or 0) - (m.get("utilization") or 0), 4),
            },
        })

    next_actions = [
        "确认 brief 中标注为 assumption 的字段（预算/档期/媒介/客户类型）。",
        "上刊前重新核对红豆库存占用；快照不是实时库存。",
        "如涉及学校/儿童场景，统一表述为“学校周边 300–500 米”，不投校内。",
        "所有曝光/Reach 数字带“模型估算”口径，不承诺到园人数或 ROI。",
    ]
    if (m.get("utilization") or 0) < absorption_floor:
        next_actions.insert(0, "先处理预算未花完：放宽媒体/点位约束，或降低预算并说明。")

    return {
        "primary_scenario": primary.get("id"),
        "primary_label": primary.get("label"),
        "verdict": verdict,
        "summary": summary,
        "why": why,
        "tradeoffs": primary.get("tradeoffs") or [],
        "alternatives": alternatives,
        "next_actions": next_actions,
        "base_preferred": bool(primary.get("is_base")),
    }


# --------------------------------------------------------------------------- #
# 跨场景比较
# --------------------------------------------------------------------------- #
def cross_scenario_notes(scenarios: List[Dict[str, Any]]) -> None:
    """给每个场景补“相对 base”的取舍说明（原地修改）。"""
    base = next((s for s in scenarios if s.get("is_base") and s.get("ok")), None)
    if not base:
        return
    bm = base.get("metrics") or {}
    for s in scenarios:
        if not s.get("ok") or s is base:
            continue
        m = s.get("metrics") or {}
        notes: List[str] = []
        paid_delta = (m.get("total_paid_wan") or 0) - (bm.get("total_paid_wan") or 0)
        reach_delta = (m.get("reach_people") or 0) - (bm.get("reach_people") or 0)
        if abs(paid_delta) >= 1:
            direction = "多花" if paid_delta > 0 else "少花"
            notes.append(
                f"相对基准{direction} {_fmt_wan(abs(paid_delta))}，目标 Reach "
                f"{'增加' if reach_delta >= 0 else '减少'} {_fmt_int(abs(reach_delta))} 人（模型估算）。"
            )
            if abs(paid_delta) > 0 and reach_delta:
                marginal = reach_delta / paid_delta
                notes.append(f"边际约 {marginal:,.0f} 人目标 Reach / 万元（派生值，跨预算比较用）。")
        if s.get("id", "").startswith("media_"):
            notes.append(
                f"媒体曝光占比：公交 {_fmt_pct((m.get('media_mix_impressions') or {}).get('bus', 0))} / "
                f"地铁 {_fmt_pct((m.get('media_mix_impressions') or {}).get('metro', 0))}。"
            )
            base_reach = bm.get("reach_people") or 0
            alt_reach = m.get("reach_people") or 0
            base_cpm = bm.get("cpm_yuan") or 0
            alt_cpm = m.get("cpm_yuan") or 0
            if (base_reach and alt_reach > base_reach * 1.02) or (base_cpm and alt_cpm < base_cpm * 0.9):
                base.setdefault("tradeoffs", [])
                base["tradeoffs"].append(
                    f"{s.get('label')}的 Reach {_fmt_pct(m.get('reach_pct'))} / CPM {alt_cpm} 元优于基准"
                    f"（{_fmt_pct(bm.get('reach_pct'))} / {base_cpm} 元）；组合中另一媒体的价值要用枢纽/场景解释，不能用 Reach 证明。"
                )
                base["tradeoffs"] = _dedupe(base["tradeoffs"])
        base_poi = bm.get("poi_hits") or 0
        if (m.get("poi_hits") or 0) != base_poi:
            notes.append(f"POI 命中 {m.get('poi_hits')} 个，基准为 {base_poi} 个。")
        s["tradeoffs"] = _dedupe((s.get("tradeoffs") or []) + notes)


def _dedupe(items: Iterable[str]) -> List[str]:
    out: List[str] = []
    for item in items:
        if item and item not in out:
            out.append(item)
    return out


# --------------------------------------------------------------------------- #
# 弹性
# --------------------------------------------------------------------------- #
def summarize_elasticity(
    elasticity: Optional[Dict[str, Any]],
    budget_wan: float,
    reach_cap: float = 0.82,
) -> Dict[str, Any]:
    if not isinstance(elasticity, dict) or not elasticity.get("points"):
        return {
            "available": False,
            "note": "未计算预算弹性；分析结论不包含“再加钱值不值”的判断。",
        }
    points = list(elasticity.get("points") or [])
    current = None
    for p in points:
        if abs(float(p.get("budget_wan") or 0) - budget_wan) < 1e-6:
            current = p
            break
    if current is None and points:
        current = min(points, key=lambda p: abs(float(p.get("budget_wan") or 0) - budget_wan))
    knee = elasticity.get("knee_budget_wan")
    current_reach = float((current or {}).get("reach") or 0)
    saturation = current_reach / reach_cap if reach_cap else 0
    interpretation = ""
    if knee is not None:
        if budget_wan < float(knee):
            interpretation = f"当前预算 {budget_wan:g} 万低于弹性拐点 {float(knee):g} 万；到拐点前，加预算仍能显著提升 Reach。"
        elif abs(budget_wan - float(knee)) < 1e-6:
            interpretation = f"当前预算正好在弹性拐点 {float(knee):g} 万；继续加钱主要买频次，而不是新增到达。"
        else:
            interpretation = f"当前预算 {budget_wan:g} 万已超过弹性拐点 {float(knee):g} 万；继续加钱的 Reach 增量有限。"
    if saturation >= 0.95:
        interpretation += f" 当前 Reach 已达模型上限的 {saturation:.0%}。"
    return {
        "available": True,
        "unit": elasticity.get("unit") or "万元",
        "knee_budget_wan": knee,
        "current_budget_wan": budget_wan,
        "current_point": current,
        "reach_cap": reach_cap,
        "saturation": round_num(saturation, 3),
        "marginal_impressions_per_wan": (current or {}).get("marginal_impressions_per_wan"),
        "interpretation": interpretation.strip(),
        "points": points,
        "note": elasticity.get("note") or "弹性曲线为同一引擎的确定性预算扩展估值；主方案仍以 CP-SAT 结果为准。",
    }


# --------------------------------------------------------------------------- #
# 主方案摘要 / 对比表
# --------------------------------------------------------------------------- #
def comparison_rows(scenarios: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows = []
    for s in scenarios:
        if not s.get("ok"):
            rows.append({
                "scenario_id": s.get("id"),
                "label": s.get("label"),
                "status": "failed",
                "error": (s.get("error") or {}).get("message"),
            })
            continue
        m = s.get("metrics") or {}
        rows.append({
            "scenario_id": s.get("id"),
            "label": s.get("label"),
            "role": s.get("role"),
            "budget_wan": m.get("budget_wan"),
            "total_paid_wan": m.get("total_paid_wan"),
            "utilization": m.get("utilization"),
            "budget_slack_wan": m.get("budget_slack_wan"),
            "impressions": m.get("impressions"),
            "reach_pct": m.get("reach_pct"),
            "reach_people": m.get("reach_people"),
            "frequency": m.get("frequency"),
            "cpm_yuan": m.get("cpm_yuan"),
            "poi_hits": m.get("poi_hits"),
            "bus_units": m.get("bus_units"),
            "metro_units": m.get("metro_units"),
            "score": (s.get("score") or {}).get("total"),
            "rank": (s.get("score") or {}).get("rank"),
            "validation_passed": (m.get("validation") or {}).get("passed"),
        })
    return rows


def top_picks(response: Dict[str, Any], limit: int = 8) -> List[Dict[str, Any]]:
    plan = response.get("plan") or {}
    items = list(plan.get("bus") or []) + list(plan.get("metro") or [])
    items.sort(key=lambda it: (-float(it.get("score") or 0), str(it.get("id"))))
    out = []
    for it in items[:limit]:
        out.append({
            "id": it.get("id"),
            "name": it.get("name"),
            "kind": it.get("kind"),
            "level": it.get("level"),
            "units": it.get("units"),
            "net_wan": it.get("net_wan"),
            "score": it.get("score"),
            "poi_count": it.get("poi_count"),
            "reasons": (it.get("reasons") or [])[:2],
        })
    return out


def build_scenario_record(
    scenario: Dict[str, Any],
    result: Dict[str, Any],
    catalog: Dict[str, Any],
    brief: BriefState,
    risk_policy: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    record: Dict[str, Any] = {
        "id": scenario.get("id"),
        "label": scenario.get("label"),
        "intent": scenario.get("intent"),
        "use_when": scenario.get("use_when", ""),
        "role": scenario.get("role"),
        "is_base": bool(scenario.get("is_base")),
        "request": scenario.get("request"),
        "ok": bool(result.get("ok")),
        "duration_ms": None,
    }
    if not result.get("ok"):
        record["error"] = result.get("error")
        return record
    response = result.get("plan") or {}
    metrics = metrics_from_plan(response, catalog)
    record.update({
        "metrics": metrics,
        "risks": build_risks(metrics, brief, risk_policy),
        "top_picks": top_picks(response, 8 if scenario.get("is_base") else 4),
        "highlights": _highlights(metrics),
        "tradeoffs": _tradeoffs(metrics),
        "hypothesis": response.get("hypothesis"),
        "explanations": _compact_explanations(response.get("explanations")),
    })
    return record


def _highlights(m: Dict[str, Any]) -> List[str]:
    out = [
        f"预算落地 {_fmt_wan(m.get('total_paid_wan'))} / {_fmt_wan(m.get('budget_wan'))}（{_fmt_pct(m.get('utilization'))}）。",
        f"总曝光 {_fmt_int(m.get('impressions'))} 人次；目标 Reach {m.get('reach_pct_label')}；频次 {m.get('frequency')}。",
        f"公交 {m.get('bus_units')} 辆 / {m.get('bus_lines')} 条线；地铁 {m.get('metro_units')} 口 / {m.get('metro_stations')} 站。",
        f"命中 {m.get('poi_hits')} 个亲子/家庭 POI。",
    ]
    return out


def _tradeoffs(m: Dict[str, Any]) -> List[str]:
    out: List[str] = []
    if (m.get("budget_slack_wan") or 0) >= 1:
        out.append(f"剩余 {_fmt_wan(m.get('budget_slack_wan'))}未花完。")
    imp_mix = m.get("media_mix_impressions") or {}
    if len(imp_mix) > 1:
        out.append(
            f"曝光占比公交 {_fmt_pct(imp_mix.get('bus', 0))} / 地铁 {_fmt_pct(imp_mix.get('metro', 0))}；"
            "地铁单价高，买到的是枢纽拦截而不是广度。"
        )
    if (m.get("frequency") or 0) > 20:
        out.append(f"频次 {m.get('frequency')} 偏高，继续加钱可能主要买重复曝光。")
    if (m.get("poi_hits") or 0) < 10:
        out.append(f"POI 命中 {m.get('poi_hits')} 个，覆盖面偏窄。")
    return _dedupe(out)


def _compact_explanations(expl: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    expl = expl or {}
    return {
        "why_selected": (expl.get("why_selected") or [])[:5],
        "why_not": (expl.get("why_not") or [])[:3],
        "trim_priority": (expl.get("trim_priority") or [])[:3],
        "counterfactuals": expl.get("counterfactuals") or {},
        "hypothesis_links": expl.get("hypothesis_links") or {},
    }


# --------------------------------------------------------------------------- #
# 格式化（narrative 共用）
# --------------------------------------------------------------------------- #
def _fmt_wan(v: Any) -> str:
    try:
        return f"{float(v):.1f} 万"
    except (TypeError, ValueError):
        return "—"


def _fmt_pct(v: Any) -> str:
    try:
        return f"{float(v):.1%}"
    except (TypeError, ValueError):
        return "—"


def _fmt_int(v: Any) -> str:
    try:
        return f"{int(round(float(v))):,}"
    except (TypeError, ValueError):
        return "—"


def format_comparison_rows(rows: List[Dict[str, Any]]) -> str:
    lines = [
        "| 方案 | 预算 | 实际落地 | 使用率 | 总曝光 | 目标 Reach | 频次 | CPM | POI | 评分 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in rows:
        if r.get("status") == "failed":
            lines.append(f"| {r.get('label')} | — | — | — | — | — | — | — | — | 失败 |")
            continue
        lines.append(
            f"| {r.get('label')} | {_fmt_wan(r.get('budget_wan'))} | {_fmt_wan(r.get('total_paid_wan'))} | "
            f"{_fmt_pct(r.get('utilization'))} | {_fmt_int(r.get('impressions'))} | "
            f"{_fmt_pct(r.get('reach_pct'))} | {r.get('frequency')} | {r.get('cpm_yuan')} | "
            f"{r.get('poi_hits')} | {r.get('score')} |"
        )
    return "\n".join(lines)


__all__ = [
    "metrics_from_plan",
    "build_risks",
    "score_scenarios",
    "recommend",
    "cross_scenario_notes",
    "summarize_elasticity",
    "comparison_rows",
    "top_picks",
    "build_scenario_record",
    "format_comparison_rows",
    "objective_label",
]
