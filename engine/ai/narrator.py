# -*- coding: utf-8 -*-
"""narrator 模板：把求解结果转成一段话（不产生数字，只引用已有数字）。"""
from __future__ import annotations

from typing import Any, Dict, List


def narrate(response: Dict[str, Any]) -> List[str]:
    """返回 workflow.stages.narrate 的摘要片段。"""
    plan = response.get("plan", {})
    summary = plan.get("summary", {})
    effects = response.get("effects", {})
    out = [
        f"共选 {len(plan.get('bus', []))} 条公交线路、{len(plan.get('metro', []))} 个地铁口；"
        f"目标人群曝光预计 {effects.get('impressions', 0):,} 人次，Reach {effects.get('reach_pct', '0%')}。",
    ]
    return out


__all__ = ["narrate"]
