# -*- coding: utf-8 -*-
"""静态单文件提案的数据载荷：当前方案 + 预算档位方案。

前端导出构建在 web/dist-export/index.html 中保留字面量 `__PLAN_DATA__`；
Lead/构建脚本把本函数返回的 JSON 注入进去，形成可离线切换预算档的单文件。

载荷约定（与前端约定）：
{
  "mode": "static-export",
  "generated_at": "...",
  "default_budget_wan": 500,
  "tiers": [100, 150, ..., 500],
  "plans": { "100": PlanResponse, "150": PlanResponse, ... }
}
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.models import PlanError, PlanRequest  # noqa: E402


def _generate(body: Dict[str, Any]) -> Dict[str, Any]:
    from engine.orchestrator import generate_plan  # delayed import

    return generate_plan(body)


def build_export_payload(
    body: Optional[Dict[str, Any]],
    *,
    step: int = 50,
    budgets: Optional[List[float]] = None,
) -> Dict[str, Any]:
    body = dict(body or {})
    req = PlanRequest.from_dict(body)
    base_budget = float(req.budget_wan)

    if budgets is None:
        budgets = [float(b) for b in range(100, 501, max(10, int(step)))]
        if base_budget not in budgets:
            budgets.append(base_budget)
        budgets = sorted(set(b for b in budgets if 100 <= b <= 500))

    plans: Dict[str, Any] = {}
    for b in budgets:
        req_b = dict(req.to_dict())
        req_b["budget_wan"] = b
        try:
            plans[str(int(b)) if float(b).is_integer() else str(b)] = _generate(req_b)
        except PlanError as exc:
            # 某一档不可行不应阻断导出；记录错误，前端显示该档不可用
            plans[str(int(b)) if float(b).is_integer() else str(b)] = {
                "error": exc.to_dict()["error"],
                "inputs": req_b,
            }

    default_plan = plans.get(str(int(base_budget)) if base_budget.is_integer() else str(base_budget))
    if not default_plan or "error" in default_plan:
        # 当前预算不可行则用最高可行档兜底
        for b in reversed(budgets):
            p = plans.get(str(int(b)) if float(b).is_integer() else str(b))
            if p and "error" not in p:
                default_plan = p
                base_budget = b
                break

    return {
        "mode": "static-export",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "default_budget_wan": base_budget,
        "tiers": budgets,
        "plans": plans,
        "data_version": (default_plan or {}).get("meta", {}).get("data_version", ""),
        "inventory_ts": (default_plan or {}).get("meta", {}).get("inventory_ts", ""),
    }


__all__ = ["build_export_payload"]
