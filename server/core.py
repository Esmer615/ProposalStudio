# -*- coding: utf-8 -*-
"""API 业务核心：FastAPI 与标准库兜底服务共用。

不在这里做任何优化计算；所有数字来自 engine.orchestrator.generate_plan()。
"""
from __future__ import annotations

import json
import platform
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
CONFIG_DIR = DATA_DIR / "config"
PROCESSED_DIR = DATA_DIR / "processed"
WEB_DIST = ROOT / "web" / "dist"
WEB_EXPORT = ROOT / "web" / "dist-export"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# --------------------------------------------------------------------------- #
# 基础工具
# --------------------------------------------------------------------------- #
def _read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def _cfg(name: str) -> Optional[Dict[str, Any]]:
    return _read_json(CONFIG_DIR / name)


def _manifest() -> Dict[str, Any]:
    return _read_json(PROCESSED_DIR / "manifest.json", {}) or {}


def _data_version() -> str:
    m = _manifest()
    return str(m.get("data_version") or m.get("version") or "unavailable")


def _inventory_periods() -> List[str]:
    m = _manifest()
    # Agent-A 的完整 manifest 用 files[{start,end}] 记录月份
    files = m.get("files") or []
    derived = sorted({
        f"{f.get('start')}..{f.get('end')}"
        for f in files
        if isinstance(f, dict) and f.get("start") and f.get("end")
    })
    if derived:
        return derived
    periods = m.get("periods") or m.get("inventory_periods") or []
    if isinstance(periods, list):
        return [str(p) for p in periods]
    return []


def _inventory_ts() -> Optional[str]:
    m = _manifest()
    return m.get("fetched_at") or m.get("inventory_ts") or m.get("generated_at")


def _load_engine():
    """延迟导入，避免引擎未就绪时整个服务起不来。"""
    try:
        from engine.orchestrator import generate_plan  # type: ignore

        return generate_plan, None
    except Exception as exc:  # pragma: no cover - 引擎未就绪时的保护
        return None, f"{type(exc).__name__}: {exc}"


def _load_request_cls():
    try:
        from engine.models import PlanRequest, PlanError  # type: ignore

        return PlanRequest, PlanError
    except Exception:
        return None, None


def _default_request() -> Dict[str, Any]:
    try:
        from engine.models import PlanRequest  # type: ignore

        return PlanRequest().to_dict()
    except Exception:
        return {
            "industry": "乐园",
            "venue": "lego_shanghai",
            "budget_wan": 500,
            "media": ["bus", "metro"],
            "start_date": "2027-07-01",
            "weeks": 8,
            "customer_type": "direct",
            "locks": {"include": [], "exclude": []},
        }


def _venue_options() -> List[Dict[str, Any]]:
    venues_dir = CONFIG_DIR / "venues"
    out: List[Dict[str, Any]] = []
    if venues_dir.exists():
        for p in sorted(venues_dir.glob("*.json")):
            v = _read_json(p, {}) or {}
            if v.get("id"):
                out.append(
                    {
                        "id": v.get("id"),
                        "name": v.get("name"),
                        "district": v.get("district"),
                        "access": v.get("access") or v.get("access_modes"),
                        "coords": v.get("coords"),
                        "rings_km": v.get("rings_km") or v.get("catchment_rings_km"),
                        "target_population": v.get("target_population"),
                        "reach_k": v.get("reach_k"),
                        "media_mix_bounds": v.get("media_mix_bounds"),
                    }
                )
    if out:
        return out
    return [
        {"id": "lego_shanghai", "name": "上海乐高乐园", "district": "金山区"},
        {"id": "disney_shanghai", "name": "上海迪士尼度假区", "district": "浦东新区"},
        {"id": "haichang_shanghai", "name": "上海海昌海洋公园", "district": "浦东新区"},
    ]


def _date_options() -> List[Dict[str, Any]]:
    periods = _inventory_periods()
    if periods:
        # manifest 可能存 "2027-07-01..2027-07-31"
        starts: List[str] = []
        for p in periods:
            s = str(p).split("..")[0].split("~")[0].strip()
            if s and s not in starts:
                starts.append(s)
        if starts:
            return [{"value": s, "label": s[:7] + " 快照"} for s in sorted(starts)]
    return [
        {"value": "2027-07-01", "label": "2027 暑期（7–8 月）"},
        {"value": "2027-06-01", "label": "2027 端午/初夏（6 月）"},
        {"value": "2027-09-01", "label": "2027 开学季（9 月）"},
        {"value": "2027-10-01", "label": "2027 国庆（10 月）"},
    ]


# --------------------------------------------------------------------------- #
# 端点业务
# --------------------------------------------------------------------------- #
def health() -> Dict[str, Any]:
    gen, err = _load_engine()
    return {
        "status": "ok" if gen else "degraded",
        "engine_available": gen is not None,
        "engine_error": err,
        "python": platform.python_version(),
        "solver": "CP-SAT",
        "data_version": _data_version(),
        "inventory_periods": _inventory_periods(),
        "inventory_ts": _inventory_ts(),
        "manifest_ready": bool(_manifest()),
    }


def _discount_tiers(rate: Dict[str, Any]) -> List[Dict[str, Any]]:
    """把 rate_card_2027.json 的 discount_tiers 归一成契约 DiscountTier[]。"""
    raw = None
    if isinstance(rate, dict):
        raw = rate.get("discount_tiers")
    if not isinstance(raw, list) or not raw:
        cfg = _cfg("discount_tiers.json") or _cfg("discounts.json") or {}
        raw = cfg.get("tiers") if isinstance(cfg, dict) else None
    out: List[Dict[str, Any]] = []
    if isinstance(raw, list):
        parsed = []
        for t in raw:
            if not isinstance(t, dict):
                continue
            rate_value = t.get("rate", t.get("discount"))
            if rate_value is None:
                continue
            parsed.append(
                {
                    "label": t.get("label") or f"{int(float(rate_value) * 100)}%",
                    "min_gross_wan": float(t.get("min_gross_wan", t.get("threshold_wan", 0)) or 0),
                    "max_gross_wan": t.get("max_gross_wan"),
                    "rate": float(rate_value),
                }
            )
        parsed.sort(key=lambda x: x["min_gross_wan"])
        for i, t in enumerate(parsed):
            if t["max_gross_wan"] is None and i + 1 < len(parsed):
                t["max_gross_wan"] = parsed[i + 1]["min_gross_wan"] - 1
            out.append(t)
    if not out:
        out = [
            {"label": "88%", "min_gross_wan": 0, "max_gross_wan": 99, "rate": 0.88},
            {"label": "83%", "min_gross_wan": 100, "max_gross_wan": 199, "rate": 0.83},
            {"label": "78%", "min_gross_wan": 200, "max_gross_wan": 299, "rate": 0.78},
            {"label": "73%", "min_gross_wan": 300, "max_gross_wan": 399, "rate": 0.73},
            {"label": "68%", "min_gross_wan": 400, "max_gross_wan": None, "rate": 0.68},
        ]
    return out


def meta() -> Dict[str, Any]:
    rate = _cfg("rate_card_2027.json") or {}
    schedule = _cfg("schedule_rules.json") or {}
    date_opts = _date_options()
    return {
        "industry": "乐园",
        "venues": _venue_options(),
        "media": [
            {"id": "bus", "name": "公交车身"},
            {"id": "metro", "name": "地铁出入口"},
        ],
        # 前端 MetaResponse 约定 dates 为 string[]；label 另给 date_options
        "dates": [d["value"] for d in date_opts],
        "date_options": date_opts,
        "budget_range": {"min": 100, "max": 500, "default": 500, "step": 10},
        "weeks_options": [2, 4, 6, 8, 12],
        "customer_types": [
            {"id": "direct", "label": "直客"},
            {"id": "4a", "label": "4A 代理"},
        ],
        "default_request": _default_request(),
        "rate_card": rate,
        "discount_tiers": _discount_tiers(rate),
        "schedule_rules": schedule,
        "manifest": _manifest(),
        "data_ready": bool(_manifest()),
    }


def _map_exception(exc: Exception) -> Tuple[int, Dict[str, Any]]:
    PlanRequest, PlanError = _load_request_cls()
    if PlanError and isinstance(exc, PlanError):
        mapping = {
            "VALIDATION_ERROR": 422,
            "DATA_UNAVAILABLE": 422,
            "INFEASIBLE": 409,
            "LOCK_CONFLICT": 409,
            "INTERNAL": 500,
        }
        return mapping.get(exc.code, 400), exc.to_dict()
    return 500, {
        "error": {
            "code": "INTERNAL",
            "message": f"{type(exc).__name__}: {exc}",
            "suggestions": [],
            "recoverable": True,
        }
    }


def plan(body: Optional[Dict[str, Any]]) -> Tuple[int, Dict[str, Any], Dict[str, str]]:
    t0 = time.perf_counter()
    PlanRequest, _ = _load_request_cls()
    if PlanRequest is None:
        return 503, {"error": {"code": "ENGINE_UNAVAILABLE", "message": "engine.models 未就绪", "suggestions": [], "recoverable": True}}, {}
    try:
        req = PlanRequest.from_dict(body or {})
    except Exception as exc:
        code, payload = _map_exception(exc)
        return code, payload, {}

    gen, err = _load_engine()
    if gen is None:
        return 503, {
            "error": {
                "code": "ENGINE_UNAVAILABLE",
                "message": "求解引擎尚未就绪，请稍后重试",
                "suggestions": ["检查 engine/orchestrator.py 是否存在", "运行 engine 测试"],
                "recoverable": True,
                "detail": err,
            }
        }, {}

    try:
        # 单方案默认不算九档弹性，保证滑杆/现场改输入响应；
        # 兼容旧签名（不支持 include_elasticity 时回退）。
        try:
            resp = gen(req.to_dict(), include_elasticity=False)
        except TypeError:
            resp = gen(req.to_dict())
    except Exception as exc:
        code, payload = _map_exception(exc)
        return code, payload, {}

    elapsed = int((time.perf_counter() - t0) * 1000)
    headers = {
        "X-Data-Version": str((resp.get("meta") or {}).get("data_version") or _data_version()),
        "X-Solve-Ms": str((resp.get("meta") or {}).get("solve_ms") or elapsed),
        "X-Cache": "1" if (resp.get("meta") or {}).get("cache_hit") else "0",
    }
    return 200, resp, headers


def batch(body: Optional[Dict[str, Any]]) -> Tuple[int, Dict[str, Any], Dict[str, str]]:
    """支持两种调用：
    - {"requests": [PlanRequest, ...]}（前端批量对比）
    - {"venue":..., "budgets":[100,200,500], ...}（同一基础请求改预算）
    """
    body = dict(body or {})
    requests = body.pop("requests", None)
    if isinstance(requests, list) and requests:
        plans: List[Dict[str, Any]] = []
        for req in requests:
            if not isinstance(req, dict):
                continue
            code, payload, _ = plan(req)
            if code != 200:
                return code, payload, {}
            plans.append(payload)
        return 200, {"plans": plans}, {}

    budgets = body.pop("budgets", None) or [100, 200, 500]
    plans = []
    for b in budgets:
        req = dict(body)
        req["budget_wan"] = b
        code, payload, _ = plan(req)
        if code != 200:
            return code, payload, {}
        plans.append(payload)
    return 200, {"plans": plans}, {}


def elasticity(body: Optional[Dict[str, Any]]) -> Tuple[int, Dict[str, Any], Dict[str, str]]:
    """九档弹性：优先调用 generate_elasticity（同引擎、缓存），否则回退单方案里的 elasticity。"""
    try:
        from engine.orchestrator import generate_elasticity  # type: ignore

        PlanRequest, _ = _load_request_cls()
        if PlanRequest is None:
            raise RuntimeError("engine.models 未就绪")
        req = PlanRequest.from_dict(body or {})
        el = generate_elasticity(req.to_dict())
        return 200, el, {"X-Data-Version": _data_version()}
    except Exception:
        code, payload, headers = plan(body)
        if code != 200:
            return code, payload, headers
        return 200, payload.get("elasticity", {}), headers


def manifest() -> Dict[str, Any]:
    return {
        "manifest": _manifest(),
        "data_version": _data_version(),
        "inventory_periods": _inventory_periods(),
        "inventory_ts": _inventory_ts(),
    }


def agent_analyze(body: Optional[Dict[str, Any]]) -> Tuple[int, Dict[str, Any], Dict[str, str]]:
    """Agent 需求分析入口。

    默认 allow_defaults=True：API 调用方通常只想快速拿分析；缺字段会以
    assumptions 显式列出。CLI 默认严格提问。
    """
    try:
        from agent.runtime import ProposalAgent  # type: ignore
    except Exception as exc:
        return 503, {
            "error": {
                "code": "AGENT_UNAVAILABLE",
                "message": f"Agent 未就绪：{type(exc).__name__}: {exc}",
                "suggestions": ["检查 agent/ 目录与 Our-agent-skills/"],
                "recoverable": True,
            }
        }, {}

    payload = dict(body or {})
    opts = dict(payload.get("options") or {})
    opts.setdefault("allow_defaults", True)
    payload["options"] = opts

    try:
        result = ProposalAgent().run(payload)
    except Exception as exc:  # pragma: no cover - 顶层保护
        return 500, {
            "error": {
                "code": "AGENT_ERROR",
                "message": f"{type(exc).__name__}: {exc}",
                "suggestions": ["用 /api/agent/skills 检查技能", "设置 AGENT_DEBUG=1 查看细节"],
                "recoverable": True,
            }
        }, {}

    status = str(result.get("status") or "")
    code = 500 if status == "error" else 200
    headers = {
        "X-Agent-Status": status,
        "X-Data-Version": str((result.get("meta") or {}).get("data_version") or _data_version()),
    }
    return code, result, headers


def agent_skills() -> Dict[str, Any]:
    """技能清单 + 校验结果，供前端/答辩展示。"""
    try:
        from agent.skills import load_default_registry  # type: ignore

        reg = load_default_registry()
        manifest = reg.manifest()
        return {
            "root": manifest.get("root"),
            "load_order": manifest.get("load_order") or [],
            "stages": manifest.get("stages") or [],
            "skills": reg.summaries(),
            "validation_errors": manifest.get("validation_errors") or [],
        }
    except Exception as exc:
        return {
            "error": {
                "code": "SKILL_UNAVAILABLE",
                "message": f"{type(exc).__name__}: {exc}",
            }
        }


def export_html(body: Optional[Dict[str, Any]]) -> Tuple[int, str, str]:
    """单文件提案导出。需要 web/dist-export/index.html 存在（vite.export 构建）。

    载荷 = 当前方案 + 100–500 万预算档位（默认步长 50），前端静态模式可切换。
    """
    index = WEB_EXPORT / "index.html"
    if not index.exists():
        index = WEB_EXPORT / "export.html"
    if not index.exists():
        return 501, "", ""
    try:
        from server.export_payload import build_export_payload

        payload = build_export_payload(body, step=50)
    except Exception:
        return 500, "", ""
    html = index.read_text(encoding="utf-8", errors="replace")
    safe = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    if "__PLAN_PAYLOAD__" in html:
        html = html.replace("__PLAN_PAYLOAD__", safe)
    else:
        # 兜底：不碰属性名，在 head 里注入（新模板应使用 __PLAN_PAYLOAD__）
        html = html.replace(
            "</head>",
            f"<script>window.__PLAN_DATA__ = {safe};</script></head>",
        )
    return 200, html, "export.html"


__all__ = [
    "health", "meta", "plan", "batch", "elasticity", "manifest",
    "agent_analyze", "agent_skills", "export_html", "ROOT", "WEB_DIST",
]
