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


def _format_month_ym(val: Any) -> str:
    """将 '202305' 或 '2023-05-01' 统一格式化为 'YYYY-MM'。"""
    s = str(val or "").strip()
    m = re.match(r"^(\d{4})-?(\d{2})", s)
    return f"{m.group(1)}-{m.group(2)}" if m else s


def _format_month_range(months: Optional[List[str]]) -> str:
    """将月份列表格式化为诚实的档期范围（如 ['2027-01', '2027-02'] -> '2027-01 至 2027-02'）。"""
    clean = sorted({_format_month_ym(x) for x in (months or []) if _format_month_ym(x)})
    if not clean:
        return "—"
    if len(clean) == 1:
        return clean[0]
    return f"{clean[0]} 至 {clean[-1]}"


def _translate_data_reason(reason: Any, data_month: str = "2023-05") -> str:
    """将内部英文错误码转译为清晰诚实的中文原因。"""
    code = str(reason or "").strip()
    mapping = {
        "NOT_FOUND": f"新云 {data_month} 平台库查无此线",
        "MANUAL_LOGIN_REQUIRED": "新云会话未登录或已过期",
        "SESSION_EXPIRED": "新云会话已过期",
        "BIGDATA_UNAVAILABLE": "新云接口拉取失败",
        "BATCH_UNAVAILABLE": "新云批量轨迹接口超时或失败",
        "PORTRAIT_UNAVAILABLE": "新云人群画像接口拉取失败",
        "PARTIAL_ROUTES": f"部分线路在新云 {data_month} 平台查无轨迹",
        "NO_LINES": "当前方案无可查线路",
        "EMPTY_PATH": "平台返回轨迹坐标为空",
    }
    return mapping.get(code, code or "外部数据源返回异常")


def _route_retry_candidates(line: str) -> List[str]:
    """针对缺失的分支/高峰/区间线路，生成用于 Agent 自动重试的主线候选名。"""
    raw = str(line or "").strip()
    if not raw:
        return []
    candidates: List[str] = []

    def add(v: str) -> None:
        v = v.strip()
        if v and v != raw and v not in candidates:
            candidates.append(v)

    # 1. 剥离分支/高峰/区间后缀（如 866-高峰线 -> 866 / 866路；71路区间 -> 71路 / 71）
    stripped = re.sub(
        r"[-—_/\s]*(?:高峰线|高峰|早高峰|晚高峰|区间线?|短驳线?|定班线?|快线|慢线|B线|A线|支线|专线)$",
        "",
        raw,
    ).strip()
    if stripped and stripped != raw:
        base = re.sub(r"路$", "", stripped).strip()
        if base:
            if base.isdigit():
                add(f"{base}路")
                add(base)
            else:
                add(stripped)
                add(base)
                if not stripped.endswith("路") and not stripped.endswith("线"):
                    add(f"{base}路")

    # 2. 如果含连字符且上面未命中，取连字符前的主干名
    if "-" in raw:
        head = raw.split("-", 1)[0].strip()
        if head and head != raw:
            add(f"{head}路" if head.isdigit() else head)
            add(head)

    # 3. 纯数字或普通公交切换“路”后缀
    if not raw.startswith("地铁"):
        if raw.endswith("路"):
            add(raw[:-1])
        elif raw.isdigit():
            add(f"{raw}路")

    return candidates


def _retry_missing_routes(
    routes_payload: Dict[str, Any],
    fetch_fn: Callable[..., Dict[str, Any]],
    *,
    max_rounds: int = 2,
) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
    """Agent 自动重试缺失线路：先直接重拉瞬态失败线路，并尝试主线别名兜底（如 866-高峰线 -> 866路）。"""
    if not isinstance(routes_payload, dict):
        return routes_payload, None
    initial_missing = [m for m in (routes_payload.get("missing") or []) if isinstance(m, dict)]
    if not initial_missing:
        return routes_payload, None
    top_reason = str(routes_payload.get("reason") or "")
    if top_reason in ("MANUAL_LOGIN_REQUIRED", "NO_LINES"):
        return routes_payload, None

    lines = list(routes_payload.get("lines") or [])
    pending = list(initial_missing)
    recovered: List[Dict[str, str]] = []
    attempts = 0

    def _index_resolved(resp: Optional[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        idx: Dict[str, Dict[str, Any]] = {}
        for item in ((resp or {}).get("lines") or []):
            if not isinstance(item, dict) or not item.get("path"):
                continue
            for k in (item.get("requested"), item.get("line"), item.get("lineName")):
                nk = _norm_line(k)
                if nk:
                    idx[nk] = item
                raw_k = str(k or "").strip()
                if raw_k:
                    idx[raw_k] = item
        return idx

    # Round 1: 对瞬态失败原名重拉 + 对 NOT_FOUND 尝试主线别名
    query_terms: List[str] = []
    cand_map: Dict[str, List[str]] = {}
    for m in pending:
        orig = str(m.get("requested") or m.get("line") or "").strip()
        if not orig:
            continue
        m_reason = str(m.get("reason") or top_reason)
        cands: List[str] = []
        if m_reason != "NOT_FOUND":
            cands.append(orig)
        for alias in _route_retry_candidates(orig):
            if alias not in cands:
                cands.append(alias)
        if not cands:
            cands.append(orig)
        cand_map[orig] = cands
        for q in cands:
            if q not in query_terms:
                query_terms.append(q)

    if query_terms:
        attempts += 1
        retry_resp = fetch_fn(query_terms, force=True, max_lines=max(len(query_terms), 20))
        idx = _index_resolved(retry_resp)
        still_pending: List[Dict[str, Any]] = []
        for m in pending:
            orig = str(m.get("requested") or m.get("line") or "").strip()
            matched_item: Optional[Dict[str, Any]] = None
            matched_via = orig
            for q in cand_map.get(orig, [orig]):
                hit = idx.get(q) or idx.get(_norm_line(q))
                if hit:
                    matched_item = hit
                    matched_via = q
                    break
            if matched_item is not None:
                cloned = copy.deepcopy(matched_item)
                cloned["requested"] = orig
                cloned["line"] = orig
                if _norm_line(matched_via) != _norm_line(orig):
                    base_name = matched_item.get("lineName") or matched_via
                    cloned["alias_matched"] = matched_via
                    cloned["lineName"] = f"{orig}（复用主线 {base_name}）"
                lines.append(cloned)
                recovered.append({"line": orig, "via": matched_via})
            else:
                still_pending.append(m)
        pending = still_pending

    # Round 2: 若仍有非 NOT_FOUND 的瞬态失败线路，再补拉 1 次
    if pending and attempts < max_rounds:
        transient = [
            m for m in pending
            if str(m.get("reason") or top_reason) not in ("NOT_FOUND", "MANUAL_LOGIN_REQUIRED")
        ]
        transient_terms = [
            str(m.get("requested") or m.get("line") or "").strip()
            for m in transient
            if str(m.get("requested") or m.get("line") or "").strip()
        ]
        if transient_terms:
            attempts += 1
            retry_resp2 = fetch_fn(transient_terms, force=True, max_lines=max(len(transient_terms), 20))
            idx2 = _index_resolved(retry_resp2)
            still_pending2: List[Dict[str, Any]] = []
            for m in pending:
                orig = str(m.get("requested") or m.get("line") or "").strip()
                hit = idx2.get(orig) or idx2.get(_norm_line(orig))
                if hit:
                    cloned = copy.deepcopy(hit)
                    cloned["requested"] = orig
                    cloned["line"] = orig
                    lines.append(cloned)
                    recovered.append({"line": orig, "via": orig})
                else:
                    still_pending2.append(m)
            pending = still_pending2

    updated = dict(routes_payload)
    updated["lines"] = lines
    updated["missing"] = pending
    prev_summary = dict(routes_payload.get("summary") or {})
    requested_cnt = int(prev_summary.get("requested") or (len(lines) + len(pending)))
    updated["summary"] = {
        "requested": requested_cnt,
        "resolved": len(lines),
        "cached": int(prev_summary.get("cached") or 0),
        "fetched": int(prev_summary.get("fetched") or 0) + len(recovered),
        "missing": len(pending),
    }
    if not pending:
        updated["status"] = "ready"
        updated["reason"] = None
    elif len(lines) > 0:
        updated["status"] = "partial"

    retry_info = {
        "module": "新云线路轨迹",
        "attempts": attempts,
        "initial_missing": len(initial_missing),
        "recovered_count": len(recovered),
        "recovered": recovered,
        "remaining_missing": [str(m.get("requested") or m.get("line") or "").strip() for m in pending],
    }
    return updated, retry_info


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
        # 若首次拉取失败，Agent 自动补拉重试 1 次。
        acquired_items: List[str] = []
        failure_items: List[Dict[str, Any]] = []
        retry_log: List[Dict[str, Any]] = []

        data_inventory: Optional[Dict[str, Any]] = None
        mark("data_inventory")
        t0 = time.perf_counter()
        months = _read_snapshot_months(request)
        period_label = _format_month_range(months)
        inv_attempts = 1
        snap = self.data.inventory_snapshot(months, overwrite=True, media="all")
        if not snap.get("ok"):
            inv_attempts = 2
            stage("data_inventory", "running",
                  summary=f"红豆 {period_label} 首次拉取异常，Agent 正在第 2 次重试...")
            snap = self.data.inventory_snapshot(months, overwrite=True, media="all")
            retry_log.append({
                "module": "红豆实时库存",
                "attempts": inv_attempts,
                "recovered": bool(snap.get("ok")),
                "months": months,
            })

        inv_ok = bool(snap.get("ok"))
        inv_status = "done" if inv_ok else "partial"
        if inv_ok:
            acquired_items.append(f"红豆实时库存（{period_label} 档期，公交+地铁）")
        else:
            inv_err = str(snap.get("summary") or snap.get("error") or "接口返回失败").strip()
            detail = f"红豆实时库存（{period_label}）重试 {inv_attempts} 次后仍拉取失败：{inv_err}，已回退本地快照"
            failure_items.append({"module": "红豆实时库存", "lines": [], "reason": inv_err, "detail": detail})
            warnings.append(detail)

        stage("data_inventory", inv_status,
              summary=(f"红豆实时库存已获取 {period_label}" + (f"（第 {inv_attempts} 次重试成功）" if inv_attempts > 1 else ""))
              if inv_ok else f"红豆 {period_label} 重试 {inv_attempts} 次失败，已回退本地快照",
              extra={"ms": int((time.perf_counter() - t0) * 1000), "attempts": inv_attempts})
        data_inventory = {
            "status": inv_status,
            "mode": "live" if inv_ok else "snapshot_fallback",
            "forced": True,
            "months": months,
            "period_label": period_label,
            "attempts": inv_attempts,
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
        custom_venue = request.get("custom_venue") if isinstance(request.get("custom_venue"), dict) else None
        if custom_venue and custom_venue.get("name"):
            venue_name = str(custom_venue["name"])
            c_coords = custom_venue.get("coords") or {}
            raw_lng = float(c_coords["lng"]) if c_coords.get("lng") is not None else None
            raw_lat = float(c_coords["lat"]) if c_coords.get("lat") is not None else None
            # 新云大数据平台覆盖上海区域；外省客户公司自动改用上海全域锚点查询周边覆盖与 POI
            if raw_lng is not None and raw_lat is not None and (120.8 <= raw_lng <= 122.2 and 30.65 <= raw_lat <= 31.9):
                t_lng, t_lat = raw_lng, raw_lat
                bigdata_query_addr = venue_name
            else:
                t_lng, t_lat = 121.4737, 31.2304
                bigdata_query_addr = "上海人民广场"
        else:
            v_prof = (catalog.get("venue_profiles") or {}).get(request.get("venue"), {}) or {}
            venue_name = v_prof.get("name") \
                or {"lego_shanghai": "上海乐高乐园", "disney_shanghai": "上海迪士尼度假区", "haichang_shanghai": "上海海昌海洋公园"}.get(request.get("venue"), str(request.get("venue")))
            v_coords = v_prof.get("coords") or {}
            t_lng = float(v_coords["lng"]) if v_coords.get("lng") is not None else None
            t_lat = float(v_coords["lat"]) if v_coords.get("lat") is not None else None
            bigdata_query_addr = venue_name

        try:
            from engine.skill_loader import get_industry_profile
            poi_types = get_industry_profile(str(request.get("industry") or "乐园")).get("poi_types") or "商场,写字楼,小区"
        except Exception:
            poi_types = "商场,写字楼,小区"

        bd_month_raw = "202305"
        bd_month_label = _format_month_ym(bd_month_raw)

        cov_attempts = 1
        cov = self.data.bigdata_coverage(bigdata_query_addr, radius=1500, lng=t_lng, lat=t_lat)
        cov_status = cov.get("status") or ("ready" if cov.get("ok") else "failed")
        if cov_status != "ready" and cov.get("reason") != "MANUAL_LOGIN_REQUIRED":
            cov_attempts = 2
            stage("data_bigdata", "running", summary=f"新云 {bd_month_label} 周边覆盖首次获取失败，Agent 正在重试...")
            cov = self.data.bigdata_coverage(bigdata_query_addr, radius=1500, lng=t_lng, lat=t_lat)
            cov_status = cov.get("status") or ("ready" if cov.get("ok") else "failed")
            retry_log.append({"module": "新云周边覆盖", "attempts": cov_attempts, "recovered": cov_status == "ready"})

        poi_attempts = 1
        poi = self.data.bigdata_poi(bigdata_query_addr, radius=1500, types=poi_types, mode="detail", lng=t_lng, lat=t_lat)
        poi_status = poi.get("status") or ("ready" if poi.get("ok") else "failed")
        if poi_status != "ready" and poi.get("reason") != "MANUAL_LOGIN_REQUIRED":
            poi_attempts = 2
            stage("data_bigdata", "running", summary=f"新云 {bd_month_label} 周边 POI 首次获取失败，Agent 正在重试...")
            poi = self.data.bigdata_poi(bigdata_query_addr, radius=1500, types=poi_types, mode="detail", lng=t_lng, lat=t_lat)
            poi_status = poi.get("status") or ("ready" if poi.get("ok") else "failed")
            retry_log.append({"module": "新云周边 POI", "attempts": poi_attempts, "recovered": poi_status == "ready"})

        overall_bi = "ready" if cov_status == "ready" and poi_status == "ready" else (
            "skipped" if cov_status == "skipped" and poi_status == "skipped" else "partial"
        )
        cov_bus = int((cov.get("summary") or {}).get("bus") or 0)
        cov_metro = int((cov.get("summary") or {}).get("metro") or 0)
        poi_total = int(poi.get("total") or 0)

        if cov_status == "ready" and poi_status == "ready":
            acquired_items.append(
                f"新云 {bd_month_label} 周边覆盖（公交 {cov_bus} 条/地铁 {cov_metro} 条）与 POI（{poi_total} 个）"
            )
        else:
            if cov_status == "ready":
                acquired_items.append(f"新云 {bd_month_label} 周边覆盖（公交 {cov_bus} 条/地铁 {cov_metro} 条）")
            if poi_status == "ready":
                acquired_items.append(f"新云 {bd_month_label} 周边 POI（{poi_total} 个）")
            if cov_status == "skipped" and poi_status == "skipped":
                detail = f"新云 {bd_month_label} 周边覆盖与 POI 未获取：新云会话未登录或已过期"
                failure_items.append({"module": "新云周边覆盖与POI", "lines": [], "reason": "MANUAL_LOGIN_REQUIRED", "detail": detail})
                warnings.append(detail)
            else:
                if cov_status != "ready":
                    r_zh = _translate_data_reason(cov.get("reason"), bd_month_label)
                    detail = f"新云 {bd_month_label} 周边覆盖重试 {cov_attempts} 次仍失败：{r_zh}"
                    failure_items.append({"module": "新云周边覆盖", "lines": [], "reason": cov.get("reason"), "detail": detail})
                    warnings.append(detail)
                if poi_status != "ready":
                    r_zh = _translate_data_reason(poi.get("reason"), bd_month_label)
                    detail = f"新云 {bd_month_label} 周边 POI 重试 {poi_attempts} 次仍失败：{r_zh}"
                    failure_items.append({"module": "新云周边POI", "lines": [], "reason": poi.get("reason"), "detail": detail})
                    warnings.append(detail)

        stage("data_bigdata", overall_bi,
              summary=f"新云 {bd_month_label} 周边覆盖 公交 {cov_bus} 条 / 地铁 {cov_metro} 条 · POI {poi_total} 个",
              extra={"ms": int((time.perf_counter() - t0) * 1000)})
        data_bigdata = {
            "status": overall_bi,
            "reason": cov.get("reason") or poi.get("reason"),
            "target_name": venue_name,
            "radius": 1500,
            "coverage": cov,
            "poi": poi,
            "data_month": bd_month_raw,
        }

        # ---- 4. engine（一次求解 3 套差异化确定性方案） -------------------
        mark("engine")
        t0 = time.perf_counter()
        plan_resp: Optional[Dict[str, Any]] = None
        variants_bundle: Optional[Dict[str, Any]] = None
        engine_status = "done"
        preferred_mode = str(request.get("strategy_mode") or "balanced")
        try:
            from engine.orchestrator import generate_plan_variants, generate_elasticity
            variants_bundle = generate_plan_variants(request, bigdata_context=data_bigdata)
            v_plans = variants_bundle.get("plans") or {}
            active_mode = preferred_mode if preferred_mode in v_plans else variants_bundle.get("default_mode", "balanced")
            variants_bundle["selected_mode"] = active_mode
            plan_resp = v_plans.get(active_mode)
        except Exception as exc:
            engine_status = "failed"
            plan_resp = None
            variants_bundle = None
            err = self._engine_error(exc)
            warnings.append(f"引擎失败：{redact(err.get('message') or exc)}")

        elasticity: Optional[Dict[str, Any]] = None
        if engine_status == "done" and include_elasticity:
            try:
                from engine.orchestrator import generate_elasticity
                elasticity = generate_elasticity(request, bigdata_context=data_bigdata)
            except Exception as exc:  # 弹性失败不阻塞
                warnings.append(f"弹性计算失败（不阻塞）：{redact(exc)}")
                elasticity = None
        stage("engine", engine_status,
              summary=f"CP-SAT 凹边际递减模型已生成 {len((variants_bundle or {}).get('plans') or {})} 套策略方案" if plan_resp else "引擎失败",
              extra={"ms": int((time.perf_counter() - t0) * 1000)})

        # ---- 5. data_routes + data_portrait（真实线路几何 + 新云 2023-05 受众画像与时段人流）
        routes_payload: Optional[Dict[str, Any]] = None
        routes_data: Optional[Dict[str, Any]] = None
        portrait_data: Optional[Dict[str, Any]] = None
        if plan_resp and options.get("include_routes", True):
            mark("data_routes")
            t0 = time.perf_counter()
            all_variant_plans = list(((variants_bundle or {}).get("plans") or {}).values()) or [plan_resp]
            union_bus: List[str] = []
            union_metro: List[str] = []
            for vp in all_variant_plans:
                bl, _ = _lines_from_plan(vp)
                ml, _ = _metro_lines_from_plan(vp)
                for x in bl:
                    if x not in union_bus:
                        union_bus.append(x)
                for x in ml:
                    if x not in union_metro:
                        union_metro.append(x)
            route_lines = union_bus + union_metro
            routes_payload = self.data.bigdata_routes(
                route_lines,
                force=bool(options.get("routes_force")),
                max_lines=int(options.get("routes_max_lines") or 50),
            )
            # 若存在缺失线路（且非未登录），Agent 自动补拉重试（含高峰线/区间线主线别名补查）
            if isinstance(routes_payload, dict) and (routes_payload.get("missing") or []) and routes_payload.get("reason") not in ("MANUAL_LOGIN_REQUIRED", "NO_LINES"):
                miss_cnt_0 = len(routes_payload.get("missing") or [])
                stage("data_routes", "running",
                      summary=f"检测到 {miss_cnt_0} 条线路轨迹缺失，Agent 正在自动补拉重试...")
                routes_payload, r_retry = _retry_missing_routes(routes_payload, self.data.bigdata_routes, max_rounds=2)
                if r_retry:
                    retry_log.append(r_retry)

            # 同步把真实线路几何 + 新云实测 POI 注入所有 3 套策略方案
            bigdata_poi_items = (poi.get("items") or []) if isinstance(poi, dict) else []
            if variants_bundle and isinstance(variants_bundle.get("plans"), dict):
                for mode_key, vp in list(variants_bundle["plans"].items()):
                    vp_enriched, vp_rs = _enrich_routes(vp, routes_payload, run_id)
                    if bigdata_poi_items:
                        mlayers = (vp_enriched.setdefault("coverage", {})).setdefault("map_layers", {})
                        mlayers["bigdata_poi"] = bigdata_poi_items
                    variants_bundle["plans"][mode_key] = vp_enriched
                    if mode_key == variants_bundle.get("selected_mode"):
                        plan_resp = vp_enriched
                        routes_data = vp_rs
            else:
                plan_resp, routes_data = _enrich_routes(plan_resp, routes_payload, run_id)
                if bigdata_poi_items:
                    ((plan_resp.setdefault("coverage", {})).setdefault("map_layers", {}))["bigdata_poi"] = bigdata_poi_items

            # 拉取方案核心公交线路的 2023-05 真实人群画像与时段人流密度（失败自动重试 1 次）
            top_portrait_lines = [
                (ln if ln.endswith("路") else f"{ln}路")
                for ln in union_bus[:10]
            ]
            if top_portrait_lines:
                portrait_data = self.data.bigdata_portrait(top_portrait_lines, media="公交", max_per_line=6)
                if not (portrait_data or {}).get("ok") and (portrait_data or {}).get("reason") not in ("MANUAL_LOGIN_REQUIRED", "NO_LINES"):
                    stage("data_routes", "running", summary="新云人群画像首次获取失败，Agent 正在自动重试...")
                    portrait_data = self.data.bigdata_portrait(top_portrait_lines, media="公交", max_per_line=6, force=True)
                    retry_log.append({
                        "module": "新云人群画像",
                        "attempts": 2,
                        "recovered": bool((portrait_data or {}).get("ok")),
                    })
                per_line_map = (portrait_data or {}).get("per_line") or {}
                # 注入到每套方案对应公交条目上，供点击地图/表格抽屉查看详细实测数据
                if per_line_map:
                    norm_pl = {}
                    for k, v in per_line_map.items():
                        nk = _norm_line(k)
                        if nk:
                            norm_pl[nk] = v
                    target_plans = list(((variants_bundle or {}).get("plans") or {}).values()) or [plan_resp]
                    for vp in target_plans:
                        for item in ((vp.get("plan") or {}).get("bus") or []):
                            nk = _norm_line(item.get("line"))
                            if nk and nk in norm_pl:
                                item["xinyun_portrait"] = norm_pl[nk]

            summary = routes_payload.get("summary") or {}
            resolved = int(summary.get("resolved") or 0)
            requested = int(summary.get("requested") or len(route_lines))
            route_month = _format_month_ym(routes_payload.get("data_month") or "202305")
            still_missing = [m for m in (routes_payload.get("missing") or []) if isinstance(m, dict)]
            p_matched = len((portrait_data or {}).get("matched") or [])

            if resolved > 0:
                acquired_items.append(f"新云 {route_month} 线路真实轨迹（{resolved}/{requested} 条）")
            if still_missing:
                miss_names = [str(m.get("requested") or m.get("line") or "").strip() for m in still_missing]
                miss_names = [x for x in miss_names if x]
                first_reason = still_missing[0].get("reason") or routes_payload.get("reason")
                r_zh = _translate_data_reason(first_reason, route_month)
                shown = "、".join(miss_names[:6]) + (f" 等 {len(miss_names)} 条" if len(miss_names) > 6 else "")
                detail = f"未获取到轨迹（{len(miss_names)} 条）：{shown}（{r_zh}，重试后仍无数据，已按区县示意）"
                failure_items.append({
                    "module": "新云线路轨迹",
                    "lines": miss_names,
                    "reason": str(first_reason or ""),
                    "detail": detail,
                })
                warnings.append(detail)

            if top_portrait_lines:
                if p_matched > 0:
                    p_month = _format_month_ym((portrait_data or {}).get("data_month") or "202305")
                    acquired_items.append(f"新云 {p_month} 人群画像（{p_matched}/{len(top_portrait_lines)} 条核心线路）")
                else:
                    p_reason = (portrait_data or {}).get("reason") or "PORTRAIT_UNAVAILABLE"
                    p_month = _format_month_ym((portrait_data or {}).get("data_month") or "202305")
                    detail = f"新云 {p_month} 人群画像未获取：{_translate_data_reason(p_reason, p_month)}"
                    failure_items.append({"module": "新云人群画像", "lines": [], "reason": str(p_reason), "detail": detail})
                    warnings.append(detail)

            effective_route_status = "ready" if not still_missing else ("partial" if resolved > 0 else "skipped")
            stage("data_routes", effective_route_status,
                  summary=(f"三套方案合并线路 {len(union_bus)} 条公交 + {len(union_metro)} 条地铁，"
                           f"真实轨迹 {resolved}/{requested} 条；新云画像 {p_matched} 条"),
                  extra={"ms": int((time.perf_counter() - t0) * 1000)})
        else:
            stage("data_routes", "skipped", summary="include_routes=false 或引擎未生成方案")

        # ---- 6. visualize ------------------------------------------------
        mark("visualize")
        route_resolved = len(((routes_data or {}).get("lines")) or [])
        route_requested = int((((routes_data or {}).get("summary")) or {}).get("requested") or 0)
        stage("visualize", "done" if plan_resp else "skipped",
              summary=(f"地图图层已注入 {route_resolved}/{route_requested} 条真实线路 + 人流密度热力与受众画像数据"
                       if plan_resp else "地图/图表图层由前端基于计划渲染"))

        # ---- 7. narrative ------------------------------------------------
        mark("narrative")
        stage("narrative", "done" if plan_resp else "skipped",
              summary="话术与三套策略对比口径由确定性 narrative 组装")

        # 方案成功生成后状态一律为 done（不再标为“降级”），具体已获取/未获取明细通过 data.report 透明呈现
        if engine_status == "failed" or not plan_resp:
            status = "failed"
        else:
            status = "done"

        data_report = {
            "acquired": acquired_items,
            "failures": failure_items,
            "retries": retry_log,
            "all_ok": len(failure_items) == 0,
        }

        mark("done")
        stage("done", status, summary=f"已完成 · 已获取 {len(acquired_items)} 项数据" + (f"，{len(failure_items)} 项缺失已明细说明" if failure_items else ""))

        result = self._assemble(
            run_id=run_id, started_at=started_at, status=status,
            request=request, brief=brief.to_dict(), stages=stages, warnings=warnings,
            plan=plan_resp,
            variants=variants_bundle,
            data={
                "inventory": data_inventory,
                "bigdata": data_bigdata,
                "routes": routes_data,
                "portrait": portrait_data,
                "report": data_report,
            },
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
        variants: Optional[Dict[str, Any]] = None,
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
            "variants": variants,
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
