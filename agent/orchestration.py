# -*- coding: utf-8 -*-
"""提案编排：ProposalRunner + 运行存储。

固定阶段：intake → data_inventory → data_bigdata → engine → visualize → narrative → done。
- intake 复用 agent.intake.resolve_brief（结构化优先、allow_defaults 显式；blocking 缺字段 → needs_input）。
- 数据阶段调 DataSkillRuntime；红豆成功后 reload_data + reload_geo；失败/跳过显式降级。
- engine 阶段生成确定性方案（可选弹性），失败不阻塞。
- 结果持久化到 data/runs/<run_id>.json + 进程内字典 + 锁。
"""
from __future__ import annotations

import copy
import json
import os
import re
import threading
import time
import uuid
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from engine.config import PROJECT_ROOT
from .contracts import (
    STATUS_NEEDS_CLARIFICATION,
    STATUS_READY,
    normalize_options,
)
from .data_skills import DataSkillRuntime, default_data_runtime, redact, _ROUTE_SOURCE
from .intake import resolve_brief
from .skills import load_default_registry
from .tools import ToolRuntime

RUNS_DIR = os.path.join(PROJECT_ROOT, "data", "runs")

STAGES = ["intake", "data_inventory", "data_bigdata", "engine", "data_routes", "visualize", "narrative", "done"]

# 进程内运行存储：run_id -> result dict
_RUNS: Dict[str, Dict[str, Any]] = {}
_RUNS_LOCK = threading.Lock()


def _now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00")


def _read_snapshot_months(request: Dict[str, Any]) -> List[str]:
    """从请求 start_date/weeks 推断覆盖的自然月份；缺省 2027-07/08。"""
    start = str(request.get("start_date") or "2027-07-01")
    weeks = int(request.get("weeks") or 8)
    try:
        from datetime import date, timedelta
        d0 = date.fromisoformat(start[:10])
    except ValueError:
        d0 = date(2027, 7, 1)
    end = d0 + timedelta(days=weeks * 7)
    months: List[str] = []
    y, m = d0.year, d0.month
    while (y, m) <= (end.year, end.month):
        months.append(f"{y:04d}-{m:02d}")
        m += 1
        if m > 12:
            m = 1
            y += 1
    if not months:
        months = ["2027-07", "2027-08"]
    return months


def _norm_line(value: Any) -> str:
    """线路匹配键：去掉尾部“路”和空白（红豆 `136` ≈ 平台 `136路`）。"""
    return re.sub(r"路$", "", str(value or "").strip()).replace(" ", "")


def _lines_from_plan(plan_resp: Optional[Dict[str, Any]]) -> Tuple[List[str], Dict[str, List[str]]]:
    """从 PlanResponse 提取公交线路（按行分摊金额降序）与本线路的点位 id。"""
    plan = (plan_resp or {}).get("plan") or {}
    weights: Dict[str, float] = {}
    items: Dict[str, List[str]] = {}
    for item in plan.get("bus") or []:
        if not isinstance(item, dict) or item.get("status") == "replaced":
            continue
        line = _norm_line(item.get("line"))
        if not line:
            # 兼容只有展示名的情况：`136路 · 大三侧` / `136路 大三侧`
            name = str(item.get("name") or "")
            line = _norm_line(re.split(r"[·\s]", name, maxsplit=1)[0])
        if not line:
            continue
        weights[line] = weights.get(line, 0.0) + float(item.get("total_wan") or 0)
        item_id = item.get("id")
        if item_id:
            items.setdefault(line, []).append(str(item_id))
    ordered = sorted(weights, key=lambda line: (-weights[line], line))
    return ordered, items


_METRO_STATION_LINES: Optional[Dict[str, List[int]]] = None


def _metro_station_lines() -> Dict[str, List[int]]:
    """本地上海地铁站名 -> 线路号（只用于把方案地铁点位映射到平台线路名）。"""
    global _METRO_STATION_LINES
    if _METRO_STATION_LINES is not None:
        return _METRO_STATION_LINES
    result: Dict[str, List[int]] = {}
    path = os.path.join(PROJECT_ROOT, "data", "geo", "_shmetro_stations_by_name.json")
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        for name, entry in raw.items():
            if not isinstance(entry, dict):
                continue
            try:
                no = int(entry.get("LINE_NO"))
            except (TypeError, ValueError):
                continue
            result.setdefault(str(name), []).append(no)
    except (OSError, ValueError, json.JSONDecodeError):
        result = {}
    _METRO_STATION_LINES = result
    return result


def _metro_line_label(no: int) -> str:
    return f"地铁{int(no)}号线"


def _metro_lines_from_plan(plan_resp: Optional[Dict[str, Any]]) -> Tuple[List[str], Dict[str, List[str]]]:
    """从 PlanResponse 提取方案地铁线路（按点位金额降序）与每个线路的点位 id。

    平台 AI线路 的地铁节点名为“地铁N号线”（部分带分支后缀，如 11 号线）。
    线路号来源：点位 evidence/reasons 中的 L01/L09/L11、显式 line 字段、本地站名表 LINE_NO。
    """
    plan = (plan_resp or {}).get("plan") or {}
    station_lines = _metro_station_lines()
    weights: Dict[str, float] = {}
    items: Dict[str, List[str]] = {}
    for item in plan.get("metro") or []:
        if not isinstance(item, dict) or item.get("status") == "replaced":
            continue
        numbers: Set[int] = set()
        raw_line = str(item.get("line") or "")
        for m in re.findall(r"\d{1,2}", raw_line):
            numbers.add(int(m))
        blob = json.dumps(item, ensure_ascii=False)
        # 不能依赖尾随 \b：`L11换乘` 的 11 后是中文，仍是 \w，\b 不成立。
        for m in re.findall(r"(?<![A-Za-z0-9])L(\d{1,2})(?!\d)", blob, flags=re.I):
            numbers.add(int(m))
        for m in re.findall(r"(?:地铁)?\s*(\d{1,2})\s*号线", blob):
            numbers.add(int(m))
        station = str(item.get("station") or "")
        for no in station_lines.get(station, []):
            numbers.add(int(no))
        item_id = item.get("id")
        if not numbers or not item_id:
            continue
        for no in sorted(numbers):
            label = _metro_line_label(no)
            weights[label] = weights.get(label, 0.0) + float(item.get("total_wan") or 0)
            items.setdefault(label, []).append(str(item_id))
    ordered = sorted(weights, key=lambda line: (-weights[line], line))
    return ordered, items


def _unresolved_route_status(reason: Any) -> str:
    if str(reason or "") in ("MANUAL_LOGIN_REQUIRED", "NO_LINES", "CACHED_ONLY", "BIGDATA_UNAVAILABLE"):
        return "unavailable"
    return "missing"


def _enrich_routes(
    plan_resp: Optional[Dict[str, Any]],
    routes_payload: Optional[Dict[str, Any]],
    run_id: str,
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """把真实线路几何注入 PlanResponse 的深拷贝，绝不修改引擎缓存对象。

    - `coverage.map_layers.bus_routes[]`：每条线路一条 Feature-like 记录（前端画 Polyline 用）
    - `coverage.map_layers.bus[].route_ref/route_status`：点位到线路的引用
    - `plan.bus[].route_ref/route_status`：表格/抽屉联动
    - 返回 `(enriched_plan, routes_summary)`；`routes_summary` 不含坐标，避免与地图层重复。
    """
    if not plan_resp or not isinstance(routes_payload, dict):
        return plan_resp, None

    lines, items_by_line = _lines_from_plan(plan_resp)
    metro_lines, metro_items_by_line = _metro_lines_from_plan(plan_resp)
    route_by_key: Dict[str, Dict[str, Any]] = {}
    for route in routes_payload.get("lines") or []:
        key = _norm_line(route.get("line")) or _norm_line(route.get("lineName"))
        if key:
            route_by_key[key] = route
    missing_by_key: Dict[str, Dict[str, Any]] = {}
    for miss in routes_payload.get("missing") or []:
        key = _norm_line(miss.get("requested"))
        if key:
            missing_by_key[key] = miss

    enriched = copy.deepcopy(plan_resp)
    coverage = enriched.setdefault("coverage", {}) if isinstance(enriched, dict) else {}
    map_layers = coverage.setdefault("map_layers", {}) if isinstance(coverage, dict) else {}

    def make_route(line: str, route: Dict[str, Any], items: List[str], media: str) -> Dict[str, Any]:
        return {
            "line": line,
            "lineName": route.get("lineName") or line,
            "lineId": route.get("lineId"),
            "items": items,
            "media": media,
            "geometry": {
                "type": "line",
                "path": route.get("path"),
                "points": route.get("points"),
                "simplified": bool(route.get("simplified")),
            },
            "bbox": route.get("bbox"),
            "source": routes_payload.get("source") or _ROUTE_SOURCE,
            "data_month": routes_payload.get("data_month") or "202305",
            "confidence": "approx",
            "fetched_at": route.get("fetched_at") or routes_payload.get("fetched_at"),
        }

    bus_routes: List[Dict[str, Any]] = []
    for line in lines:
        route = route_by_key.get(line)
        if not route or not route.get("path"):
            continue
        bus_routes.append(make_route(line, route, items_by_line.get(line, []), "bus"))

    metro_routes: List[Dict[str, Any]] = []
    for line in metro_lines:
        route = route_by_key.get(line)
        if not route or not route.get("path"):
            continue
        metro_routes.append(make_route(line, route, metro_items_by_line.get(line, []), "metro"))

    all_routes = bus_routes + metro_routes
    route_meta = {
        "source": routes_payload.get("source") or _ROUTE_SOURCE,
        "data_month": routes_payload.get("data_month") or "202305",
        "status": routes_payload.get("status"),
        "reason": routes_payload.get("reason"),
        "fetched_at": routes_payload.get("fetched_at"),
        "note": "平台 2023-05 轨迹快照；几何经 WGS84→GCJ02 后用于可视化，不参与报价/库存/评分。",
    }
    if isinstance(map_layers, dict):
        map_layers["bus_routes"] = bus_routes
        map_layers["bus_routes_meta"] = dict(route_meta)
        map_layers["metro_routes"] = metro_routes
        map_layers["metro_routes_meta"] = dict(route_meta)
    if all_routes and isinstance(coverage, dict):
        route_source = "新云传媒大数据可视化平台 · AI线路（2023-05 轨迹快照，仅可视化）"
        sources = coverage.get("sources")
        if isinstance(sources, list) and route_source not in sources:
            sources.append(route_source)
        note = " 公交/地铁真实线路为 2023-05 轨迹快照，仅用于可视化。"
        if note.strip() not in str(coverage.get("disclaimer") or ""):
            coverage["disclaimer"] = str(coverage.get("disclaimer") or "").rstrip() + note

    item_status: Dict[str, Tuple[str, str]] = {}  # bus item_id -> (line, route_status)
    for route in bus_routes:
        for item_id in route.get("items") or []:
            item_status[str(item_id)] = (route["line"], "ready")
    for line in lines:
        if line in route_by_key:
            continue
        miss = missing_by_key.get(line) or {}
        state = _unresolved_route_status(miss.get("reason") or routes_payload.get("reason"))
        for item_id in items_by_line.get(line, []):
            item_status.setdefault(str(item_id), (line, state))

    if isinstance(map_layers, dict):
        for entry in map_layers.get("bus") or []:
            if not isinstance(entry, dict):
                continue
            entry_id = str(entry.get("id") or "")
            state_line = item_status.get(entry_id)
            if state_line:
                entry["route_ref"], entry["route_status"] = state_line
            else:
                fallback = entry_id.split(":")[1] if entry_id.startswith("bus:") and entry_id.count(":") >= 2 else ""
                entry["route_ref"] = _norm_line(fallback) or None
                entry["route_status"] = "unavailable"

    plan_block = enriched.get("plan") or {}
    for item in plan_block.get("bus") or []:
        if not isinstance(item, dict):
            continue
        line = _norm_line(item.get("line"))
        state = item_status.get(str(item.get("id")), (line, "unavailable"))[1] if item.get("id") else "unavailable"
        item["route_ref"] = line or None
        item["route_status"] = state

    # 地铁点位可能属于多条线路（换乘站）；route_ref 用“/”列出，任一线路有几何即 ready。
    refs_by_item: Dict[str, List[str]] = {}
    for line, ids in metro_items_by_line.items():
        for item_id in ids:
            refs_by_item.setdefault(str(item_id), []).append(line)
    ready_metro_lines = {r["line"] for r in metro_routes}
    for item in plan_block.get("metro") or []:
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("id") or "")
        refs = sorted(set(refs_by_item.get(item_id, [])))
        if not refs:
            continue
        item["route_ref"] = "/".join(refs)
        item["route_status"] = "ready" if any(line in ready_metro_lines for line in refs) else "unavailable"

    summary = routes_payload.get("summary") or {}
    routes_summary = {
        "status": routes_payload.get("status"),
        "reason": routes_payload.get("reason"),
        "source": routes_payload.get("source") or _ROUTE_SOURCE,
        "data_month": routes_payload.get("data_month") or "202305",
        "fetched_at": routes_payload.get("fetched_at"),
        "summary": {
            "requested": int(summary.get("requested") or (len(lines) + len(metro_lines))),
            "resolved": len(all_routes),
            "cached": int(summary.get("cached") or 0),
            "fetched": int(summary.get("fetched") or 0),
            "missing": len(missing_by_key),
        },
        "lines": [
            {
                "line": r["line"],
                "lineName": r.get("lineName"),
                "lineId": r.get("lineId"),
                "media": r.get("media"),
                "points": (r.get("geometry") or {}).get("points"),
                "items": r.get("items") or [],
            }
            for r in all_routes
        ],
        "missing": [
            {
                "line": m.get("requested"),
                "reason": m.get("reason"),
                "media": "metro" if str(m.get("requested") or "").startswith("地铁") else "bus",
            }
            for m in (routes_payload.get("missing") or [])
            if isinstance(m, dict)
        ],
        "geojson_url": f"/api/proposals/{run_id}/routes.geojson",
        "note": "仅用于可视化；不参与报价/库存/评分。平台数据只有 2023-05，线路为近似轨迹。",
    }
    return enriched, routes_summary


class ProposalRunner:
    """一次提案的完整编排：数据 → 引擎 → 结果。"""

    def __init__(self, data_runtime: Optional[DataSkillRuntime] = None) -> None:
        self.data = data_runtime or default_data_runtime()
        self.registry = load_default_registry()
        self.tools = ToolRuntime()

    # ------------------------------------------------------------------ #
    def run(
        self,
        payload: Dict[str, Any],
        run_id: str,
        on_stage: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> Dict[str, Any]:
        started_at = _now_iso()
        warnings: List[str] = []
        stages: List[Dict[str, Any]] = []

        raw_text = payload.get("brief_text") or payload.get("brief") or payload.get("customer_brief") or ""
        structured = payload.get("request") or payload.get("plan_request") or {}
        options_raw = payload.get("options") or {}
        options = normalize_options(options_raw)
        include_elasticity = bool(options_raw.get("include_elasticity", True))

        def notify(entry: Dict[str, Any]) -> None:
            if not on_stage:
                return
            try:
                on_stage(entry)
            except Exception:
                pass

        def mark(name: str, status: str = "active") -> None:
            notify({"stage": name, "status": status, "summary": ""})

        def stage(name: str, status: str, summary: str = "", extra: Optional[Dict[str, Any]] = None) -> None:
            entry = {"stage": name, "status": status, "summary": summary, **(extra or {})}
            stages.append(entry)
            notify(entry)

        # ---- 1. intake ---------------------------------------------------
        mark("intake")
        t0 = time.perf_counter()
        catalog = self.tools.catalog()
        narrative_policy = self.registry.policy("narrative")
        intake_policy = self.registry.policy("intake")
        brief = resolve_brief(
            raw_text, structured, catalog, options,
            llm=None,  # 结构化优先；本编排不用 LLM
            compliance_policy=narrative_policy,
            intake_policy=intake_policy,
        )
        stage("intake", "needs_input" if brief.status == STATUS_NEEDS_CLARIFICATION else "done",
              summary=brief.summary, extra={"ms": int((time.perf_counter() - t0) * 1000)})

        if brief.status == STATUS_NEEDS_CLARIFICATION and brief.blocking_questions:
            return self._assemble(
                run_id=run_id, started_at=started_at, status="needs_input",
                request=brief.request, brief=brief.to_dict(),
                stages=stages, warnings=list(warnings), plan=None,
                data={"inventory": None, "bigdata": None, "routes": None}, elasticity=None,
            )

        request = brief.request

        # ---- 2. data_inventory ------------------------------------------
        # 强制实时拉取：忽略 data_mode=cached，始终调用 hongdou-inventory
        # snapshot.py --overwrite，用红豆接口的新数据覆盖 data/snapshots。
        data_inventory: Optional[Dict[str, Any]] = None
        mark("data_inventory")
        t0 = time.perf_counter()
        months = _read_snapshot_months(request)
        snap = self.data.inventory_snapshot(months, overwrite=True, media="all")
        status = "done" if snap.get("ok") else "degraded"
        if not snap.get("ok"):
            warnings.append("红豆实时拉取未完全成功（forced live pull）")
        stage("data_inventory", status,
              summary=f"红豆实时拉取 {','.join(months)}（--overwrite）" if snap.get("ok") else "红豆实时拉取失败",
              extra={"ms": int((time.perf_counter() - t0) * 1000)})
        data_inventory = {
            "status": status,
            "mode": "live",
            "forced": True,
            "months": months,
            "snapshot": snap,
            "data_version": None,  # 下面重载后回填
        }

        # 拉取后必须清引擎缓存 + POI 缓存，保证读到的就是刚写入的快照。
        try:
            from engine.orchestrator import reload_data
            from engine.candidates import reload_geo
            reload_data()
            reload_geo()
        except Exception as exc:  # pragma: no cover
            warnings.append(f"reload_data/reload_geo 失败：{redact(exc)}")

        # 回填 data_version（用引擎 catalog 里的当前版本）
        try:
            catalog2 = self.tools.catalog()
            dv = (catalog2.get("inventory") or {}).get("data_version")
            if data_inventory is not None:
                data_inventory["data_version"] = dv
        except Exception:
            pass

        # ---- 3. data_bigdata --------------------------------------------
        data_bigdata: Optional[Dict[str, Any]] = None
        mark("data_bigdata")
        t0 = time.perf_counter()
        venue_name = (catalog.get("venue_profiles") or {}).get(request.get("venue"), {}).get("name") \
            or {"lego_shanghai": "上海乐高乐园", "disney_shanghai": "上海迪士尼度假区", "haichang_shanghai": "上海海昌海洋公园"}.get(request.get("venue"), str(request.get("venue")))
        cov = self.data.bigdata_coverage(venue_name, radius=1000)
        poi = self.data.bigdata_poi(venue_name, radius=1000, types="商场,幼儿园")
        cov_status = cov.get("status") or ("ready" if cov.get("ok") else "degraded")
        poi_status = poi.get("status") or ("ready" if poi.get("ok") else "degraded")
        overall_bi = "ready" if cov_status == "ready" and poi_status == "ready" else (
            "skipped" if cov_status == "skipped" and poi_status == "skipped" else "degraded"
        )
        if cov_status == "skipped" or poi_status == "skipped":
            warnings.append("新云数据跳过：MANUAL_LOGIN_REQUIRED（需人工验证码登录一次），不阻塞引擎")
        elif overall_bi == "degraded":
            warnings.append("新云 2023-05 补充数据部分不可用（degraded）")
        stage("data_bigdata", overall_bi,
              summary=f"coverage={cov.get('summary')} poi={poi.get('summary')}", extra={"ms": int((time.perf_counter() - t0) * 1000)})
        data_bigdata = {
            "status": overall_bi,
            "reason": cov.get("reason") or poi.get("reason"),
            "coverage": cov,
            "poi": poi,
            "data_month": "202305",
        }

        # ---- 4. engine ---------------------------------------------------
        mark("engine")
        t0 = time.perf_counter()
        plan_resp: Optional[Dict[str, Any]] = None
        engine_status = "done"
        try:
            from engine.orchestrator import generate_plan, generate_elasticity
            plan_resp = generate_plan(request, include_elasticity=False)
        except Exception as exc:
            engine_status = "failed"
            plan_resp = None
            err = self._engine_error(exc)
            warnings.append(f"引擎失败：{redact(err.get('message') or exc)}")

        elasticity: Optional[Dict[str, Any]] = None
        if engine_status == "done" and include_elasticity:
            try:
                from engine.orchestrator import generate_elasticity
                elasticity = generate_elasticity(request)
            except Exception as exc:  # 弹性失败不阻塞
                warnings.append(f"弹性计算失败（不阻塞）：{redact(exc)}")
                elasticity = None
        stage("engine", engine_status,
              summary="生成完整 PlanResponse" if plan_resp else "引擎失败", extra={"ms": int((time.perf_counter() - t0) * 1000)})

        # ---- 5. data_routes ---------------------------------------------
        # 方案线路只有引擎跑完才知道；由 Agent 调 xinyun AI线路 取真实几何。
        routes_payload: Optional[Dict[str, Any]] = None
        routes_data: Optional[Dict[str, Any]] = None
        if plan_resp and options.get("include_routes", True):
            mark("data_routes")
            t0 = time.perf_counter()
            bus_lines, _bus_items = _lines_from_plan(plan_resp)
            metro_lines, _metro_items = _metro_lines_from_plan(plan_resp)
            route_lines = bus_lines + metro_lines
            routes_payload = self.data.bigdata_routes(
                route_lines,
                force=bool(options.get("routes_force")),
                max_lines=int(options.get("routes_max_lines") or 40),
            )
            plan_resp, routes_data = _enrich_routes(plan_resp, routes_payload, run_id)
            summary = routes_payload.get("summary") or {}
            resolved = int(summary.get("resolved") or 0)
            requested = int(summary.get("requested") or len(route_lines))
            route_status = str(routes_payload.get("status") or "degraded")
            stage("data_routes", route_status,
                  summary=(f"方案线路 {len(bus_lines)} 条公交 + {len(metro_lines)} 条地铁，"
                           f"真实几何 {resolved}/{requested} 条"),
                  extra={"ms": int((time.perf_counter() - t0) * 1000)})
            if route_status != "ready" and requested:
                warnings.append(
                    f"线路真实几何 {resolved}/{requested} 条（{routes_payload.get('reason') or route_status}），缺失线路按区县示意"
                )
        else:
            stage("data_routes", "skipped", summary="include_routes=false 或引擎未生成方案")

        # ---- 6. visualize ------------------------------------------------
        mark("visualize")
        route_resolved = len(((routes_data or {}).get("lines")) or [])
        route_requested = int((((routes_data or {}).get("summary")) or {}).get("requested") or 0)
        stage("visualize", "done" if plan_resp else "skipped",
              summary=(f"地图图层已注入 {route_resolved}/{route_requested} 条真实线路（map_layers.bus_routes + metro_routes）"
                       if plan_resp else "地图/图表图层由前端基于计划渲染"))

        # ---- 7. narrative ------------------------------------------------
        mark("narrative")
        stage("narrative", "done" if plan_resp else "skipped",
              summary="话术与口径由确定性 narrative 组装")

        status = "done" if plan_resp else "degraded"
        if engine_status == "failed":
            status = "failed"
        elif warnings:
            status = "degraded"

        mark("done")
        stage("done", status, summary=f"最终状态 {status}")

        result = self._assemble(
            run_id=run_id, started_at=started_at, status=status,
            request=request, brief=brief.to_dict(), stages=stages, warnings=warnings,
            plan=plan_resp,
            data={"inventory": data_inventory, "bigdata": data_bigdata, "routes": routes_data},
            elasticity=elasticity, error=(None if plan_resp else self._engine_error(None) if engine_status == "failed" else None),
        )
        return result

    # ------------------------------------------------------------------ #
    def _engine_error(self, exc: Any) -> Dict[str, Any]:
        if exc is None:
            return {"code": "ENGINE_FAILED", "message": "引擎未生成方案"}
        to_dict = getattr(exc, "to_dict", None)
        if callable(to_dict):
            try:
                return (to_dict().get("error") or {"code": "ENGINE_ERROR", "message": str(exc)})
            except Exception:
                pass
        return {"code": getattr(exc, "code", "ENGINE_ERROR"), "message": redact(getattr(exc, "message", str(exc)))}

    def _assemble(
        self,
        *,
        run_id: str,
        started_at: str,
        status: str,
        request: Dict[str, Any],
        brief: Dict[str, Any],
        stages: List[Dict[str, Any]],
        warnings: List[str],
        plan: Optional[Dict[str, Any]],
        data: Dict[str, Any],
        elasticity: Optional[Dict[str, Any]],
        error: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        finished_at = _now_iso()
        return {
            "run_id": run_id,
            "status": status,
            "created_at": started_at,
            "finished_at": finished_at,
            "inputs": {"request": request, "brief_text": brief.get("raw_text", "")},
            "agent": {
                "brief": brief,
                "stages": stages,
                "messages": [],
                "questions": brief.get("questions", []),
                "assumptions": brief.get("assumptions", []),
            },
            "data": data,
            "plan": plan,
            "elasticity": elasticity,
            "warnings": warnings,
            "error": error,
        }


# --------------------------------------------------------------------------- #
# 运行存储
# --------------------------------------------------------------------------- #
def _run_path(run_id: str) -> str:
    return os.path.join(RUNS_DIR, f"{run_id}.json")


def persist_run(result: Dict[str, Any]) -> None:
    os.makedirs(RUNS_DIR, exist_ok=True)
    path = _run_path(result["run_id"])
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, allow_nan=False, default=str)
    os.replace(tmp, path)


def _safe_file_run_id(name: str) -> Optional[str]:
    return name[:-5] if name.endswith(".json") else None


def get_run(run_id: str) -> Optional[Dict[str, Any]]:
    with _RUNS_LOCK:
        if run_id in _RUNS:
            return _RUNS[run_id]
    path = _run_path(run_id)
    if os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            with _RUNS_LOCK:
                _RUNS[run_id] = data
            return data
        except (OSError, json.JSONDecodeError):
            return None
    return None


def submit_run(payload: Dict[str, Any]) -> str:
    """创建运行（queued），返回 run_id；执行由调用方在后台线程触发。"""
    run_id = uuid.uuid4().hex[:12]
    result = {
        "run_id": run_id,
        "status": "queued",
        "created_at": _now_iso(),
        "finished_at": None,
        "inputs": payload,
        "agent": None,
        "data": None,
        "plan": None,
        "elasticity": None,
        "warnings": [],
        "error": None,
    }
    with _RUNS_LOCK:
        _RUNS[run_id] = result
    persist_run(result)
    return run_id


def execute_run(run_id: str, payload: Dict[str, Any], data_runtime: Optional[DataSkillRuntime] = None) -> None:
    """后台执行：把 queued 更新为最终结果并落盘。

    阶段完成/开始时通过 on_stage 增量写回 _RUNS，前端轮询即可看到气泡图进度；
    最终结果仍以 runner.run 的完整 result 覆盖。
    """
    def on_stage(entry: Dict[str, Any]) -> None:
        with _RUNS_LOCK:
            rec = _RUNS.get(run_id)
            if rec is None:
                return
            rec["status"] = "running"
            agent = rec.get("agent")
            if not isinstance(agent, dict):
                agent = {"brief": None, "stages": [], "messages": [], "questions": [], "assumptions": []}
                rec["agent"] = agent
            stages = agent.setdefault("stages", [])
            stages.append({
                "stage": entry.get("stage"),
                "status": entry.get("status"),
                "summary": entry.get("summary") or "",
                "ms": entry.get("ms"),
            })
            snapshot = copy.deepcopy(rec)
        try:
            persist_run(snapshot)
        except Exception:
            pass

    try:
        with _RUNS_LOCK:
            rec = _RUNS.get(run_id)
            if rec is not None:
                rec["status"] = "running"
                if not isinstance(rec.get("agent"), dict):
                    rec["agent"] = {"brief": None, "stages": [], "messages": [], "questions": [], "assumptions": []}
                rec["agent"].setdefault("stages", [])
        runner = ProposalRunner(data_runtime)
        result = runner.run(payload, run_id, on_stage=on_stage)
    except Exception as exc:  # pragma: no cover
        result = {
            "run_id": run_id,
            "status": "failed",
            "created_at": (get_run(run_id) or {}).get("created_at") or _now_iso(),
            "finished_at": _now_iso(),
            "inputs": payload,
            "agent": None,
            "data": None,
            "plan": None,
            "elasticity": None,
            "warnings": [],
            "error": {"code": "RUNNER_ERROR", "message": redact(exc)},
        }
    # 每次 run 完成即生成本地交付 PDF（销售提案 + 对应客户类型合同）；其余模板点击时按需懒生成。
    if isinstance(result, dict) and result.get("plan"):
        try:
            from server.proposal_pdf import generate_run_pdfs
            generate_run_pdfs(result)
        except Exception as exc:
            result.setdefault("warnings", []).append(f"PDF 生成失败：{redact(exc)}")
    with _RUNS_LOCK:
        _RUNS[run_id] = result
    persist_run(result)


__all__ = [
    "ProposalRunner", "STAGES", "RUNS_DIR",
    "submit_run", "get_run", "execute_run", "persist_run",
    "default_data_runtime",
]
