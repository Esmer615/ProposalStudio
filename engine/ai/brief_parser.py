# -*- coding: utf-8 -*-
"""离线规则 brief 解析：从中文自然语言提取 venue/budget/media/dates。

纯规则，确定性；解析失败回退到默认请求。
"""
from __future__ import annotations

import re
from typing import Any, Dict, Optional

_VENUE_KEYWORDS = {
    "lego_shanghai": ["乐高", "lego", "LEGOLAND"],
    "disney_shanghai": ["迪士尼", "disney"],
    "haichang_shanghai": ["海昌", "海洋公园"],
}
_MEDIA_KEYWORDS = {
    "bus": ["公交", "车身", "巴士"],
    "metro": ["地铁", "轨道", "出入口"],
}


def parse_brief(text: Optional[str]) -> Dict[str, Any]:
    """返回规范化字段字典（可与 PlanRequest.from_dict 合并）。"""
    out: Dict[str, Any] = {}
    if not text:
        return out

    # venue
    for venue, kws in _VENUE_KEYWORDS.items():
        if any(k.lower() in text.lower() for k in kws):
            out["venue"] = venue
            break

    # budget（万）
    m = re.search(r"(\d+(?:\.\d+)?)\s*万", text)
    if m:
        out["budget_wan"] = float(m.group(1))

    # media
    media = []
    for med, kws in _MEDIA_KEYWORDS.items():
        if any(k in text for k in kws):
            media.append(med)
    if media:
        out["media"] = media

    # dates（YYYY-MM-DD）
    m = re.search(r"(\d{4}-\d{2}-\d{2})", text)
    if m:
        out["start_date"] = m.group(1)

    # weeks
    m = re.search(r"(\d+)\s*周", text)
    if m:
        out["weeks"] = int(m.group(1))

    return out


def brief_summary(text: Optional[str]) -> str:
    """生成 brief 解析摘要（用于 workflow.stages/brief.summary）。"""
    d = parse_brief(text)
    if not d:
        return "无 brief，使用默认参数"
    parts = []
    if "venue" in d:
        parts.append(d["venue"])
    if "budget_wan" in d:
        parts.append(f"{d['budget_wan']}万")
    if "media" in d:
        parts.append("+".join(d["media"]))
    return "识别 " + "/".join(parts) if parts else "brief 非结构化"


__all__ = ["parse_brief", "brief_summary"]
