# -*- coding: utf-8 -*-
"""Agent 可调用的确定性工具。

工具是 Agent 与引擎之间唯一的边界：
- 输入/输出都是 JSON 可序列化；
- 所有数字来自 engine；
- 每次调用记录耗时与参数摘要，供 trace 复盘。
"""
from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, Iterable, List, Optional, Tuple

from engine.config import PROCESSED_DIR
from engine.models import (
    ALLOWED_WEEKS,
    BUDGET_MAX_WAN,
    BUDGET_MIN_WAN,
    CUSTOMER_TYPES,
    DEFAULT_START_DATE,
    DEFAULT_WEEKS,
    MEDIA_LABELS,
    VENUES,
)

TOOL_VERSION = "1.0.0"


def _read_json(path: str, default: Any) -> Any:
    try:
        with open(path, encoding="utf-8-sig") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return default


class ToolRuntime:
    """工具注册表 + 调用记录。线程内使用，不适合跨请求共享。"""

    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []
        self._catalog: Optional[Dict[str, Any]] = None

    # ------------------------------------------------------------------ #
    # 元数据
    # ------------------------------------------------------------------ #
    def catalog(self) -> Dict[str, Any]:
        """场馆/媒体/档期/政策摘要：Agent 设计场景时需要，不含库存明细。"""
        if self._catalog is not None:
            return self._catalog

        from engine.skill_loader import BUILTIN_PROFILES, build_skill

        manifest = _read_json(os.path.join(PROCESSED_DIR, "manifest.json"), {}) or {}
        periods = sorted({
            f"{f.get('start')}..{f.get('end')}"
            for f in (manifest.get("files") or [])
            if isinstance(f, dict) and f.get("start") and f.get("end")
        })

        profiles: Dict[str, Any] = {}
        for venue_id in VENUES:
            try:
                skill = build_skill(venue_id)
                profiles[venue_id] = {
                    "id": skill.id,
                    "name": skill.name,
                    "district": skill.district,
                    "metro_direct": skill.metro_direct,
                    "self_drive_share": skill.self_drive_share,
                    "rail_share": skill.rail_share,
                    "target_population": skill.target_population,
                    "reach_k": skill.reach_k,
                    "media_mix_bounds": skill.media_mix_bounds,
                    "compliance_notes": skill.compliance_notes,
                    "source": skill.source,
                }
            except Exception as exc:  # pragma: no cover - 数据损坏时的保护
                profiles[venue_id] = {
                    "id": venue_id,
                    "name": VENUES[venue_id]["name"],
                    "error": f"{type(exc).__name__}: {exc}",
                }

        self._catalog = {
            "industry": "乐园",
            "venues": [
                {
                    "id": vid,
                    "name": VENUES[vid]["name"],
                    "district": VENUES[vid]["district"],
                    "short": VENUES[vid]["short"],
                }
                for vid in VENUES
            ],
            "media": [{"id": k, "label": v} for k, v in MEDIA_LABELS.items()],
            "budget_range": {"min_wan": BUDGET_MIN_WAN, "max_wan": BUDGET_MAX_WAN},
            "allowed_weeks": list(ALLOWED_WEEKS),
            "customer_types": [{"id": k, "label": v} for k, v in CUSTOMER_TYPES.items()],
            "defaults": {
                "venue": "lego_shanghai",
                "budget_wan": 200,
                "media": ["bus", "metro"],
                "start_date": DEFAULT_START_DATE,
                "weeks": DEFAULT_WEEKS,
                "customer_type": "direct",
            },
            "venue_profiles": profiles,
            "inventory": {
                "data_version": str(manifest.get("data_version") or "unavailable"),
                "periods": periods,
                "timestamp": manifest.get("inventory_ts") or manifest.get("fetched_at"),
                "source_system": manifest.get("source_system"),
                "assumptions": manifest.get("assumptions") or [],
            },
            "builtin_venues": list(BUILTIN_PROFILES.keys()),
        }
        return self._catalog

    # ------------------------------------------------------------------ #
    # 工具：单方案 / 弹性 / 批量
    # ------------------------------------------------------------------ #
    def run_plan(self, request: Dict[str, Any]) -> Dict[str, Any]:
        t0 = time.perf_counter()
        args = {
            "venue": request.get("venue"),
            "budget_wan": request.get("budget_wan"),
            "media": request.get("media"),
            "start_date": request.get("start_date"),
            "weeks": request.get("weeks"),
            "customer_type": request.get("customer_type"),
        }
        try:
            from engine.models import PlanRequest
            from engine.orchestrator import generate_plan

            req = PlanRequest.from_dict(request)
            resp = generate_plan(req, include_elasticity=False)
            result = {"ok": True, "request": req.to_dict(), "plan": resp}
        except Exception as exc:
            result = {
                "ok": False,
                "request": dict(request),
                "error": self._error_from_exception(exc),
            }
        self._record("plan.generate", args, result, t0)
        return result

    def run_elasticity(self, request: Dict[str, Any]) -> Dict[str, Any]:
        t0 = time.perf_counter()
        args = {
            "venue": request.get("venue"),
            "budget_wan": request.get("budget_wan"),
            "media": request.get("media"),
            "start_date": request.get("start_date"),
            "weeks": request.get("weeks"),
            "customer_type": request.get("customer_type"),
        }
        try:
            from engine.models import PlanRequest
            from engine.orchestrator import generate_elasticity

            req = PlanRequest.from_dict(request)
            data = generate_elasticity(req)
            result = {"ok": True, "elasticity": data}
        except Exception as exc:
            result = {"ok": False, "error": self._error_from_exception(exc)}
        self._record("elasticity.generate", args, result, t0)
        return result

    def compare(self, requests: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """顺序执行，保持确定性；引擎内部有缓存。"""
        return [self.run_plan(r) for r in requests]

    # ------------------------------------------------------------------ #
    # 工具：合规扫描
    # ------------------------------------------------------------------ #
    def compliance_scan(
        self,
        text: str,
        *,
        policy: Optional[Dict[str, Any]] = None,
        location: str = "brief",
    ) -> List[Dict[str, Any]]:
        """扫描客户 brief 中的危险承诺/合规雷区；否定句不计入。"""
        t0 = time.perf_counter()
        policy = policy or {}
        rules = policy.get("forbidden_claims") or []
        flags: List[Dict[str, Any]] = []
        for rule in rules:
            if isinstance(rule, str):
                rule = {"match": rule, "guidance": ""}
            needle = str(rule.get("match") or "").strip()
            if not needle:
                continue
            start = 0
            while True:
                idx = text.find(needle, start)
                if idx < 0:
                    break
                start = idx + len(needle)
                if _is_negated(text, idx):
                    continue
                flags.append({
                    "code": str(rule.get("code") or "COMPLIANCE_PHRASE"),
                    "level": str(rule.get("level") or "high"),
                    "matched": needle,
                    "location": location,
                    "guidance": str(rule.get("guidance") or ""),
                })
        self._record("compliance.scan", {"location": location, "rules": len(rules)}, {"flags": flags}, t0)
        return flags

    # ------------------------------------------------------------------ #
    @staticmethod
    def _error_from_exception(exc: Exception) -> Dict[str, Any]:
        to_dict = getattr(exc, "to_dict", None)
        if callable(to_dict):
            try:
                return to_dict().get("error", {"code": "ENGINE_ERROR", "message": str(exc)})
            except Exception:
                pass
        return {
            "code": getattr(exc, "code", "ENGINE_ERROR"),
            "message": getattr(exc, "message", f"{type(exc).__name__}: {exc}"),
            "recoverable": True,
        }

    def _record(self, name: str, args: Dict[str, Any], result: Dict[str, Any], t0: float) -> None:
        self.calls.append({
            "tool": name,
            "version": TOOL_VERSION,
            "ms": int((time.perf_counter() - t0) * 1000),
            "args": args,
            "ok": bool(result.get("ok", True)),
            **({"error": result.get("error")} if result.get("error") else {}),
        })


def _is_negated(text: str, index: int) -> bool:
    """粗略判断命中的危险短语是否处于否定语境（"不要保证入园"）。"""
    window = text[max(0, index - 16): index]
    return any(word in window for word in ("不", "无需", "不要", "不能", "禁止", "别", "避免", "不得"))


__all__ = ["ToolRuntime", "TOOL_VERSION"]
