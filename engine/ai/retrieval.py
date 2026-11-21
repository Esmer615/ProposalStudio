# -*- coding: utf-8 -*-
"""TF-IDF / 关键词策略检索：在场馆 profile + 知识片段里检索相关策略片段。

确定性、无 LLM；返回命中的知识片段列表，供假设书/策略引用。
"""
from __future__ import annotations

from typing import Any, Dict, List

from ..skill_loader import Skill


def retrieve_strategy(skill: Skill, brief_text: str) -> List[str]:
    """返回检索到的策略片段（简化为关键词命中 skill 字段）。"""
    snippets: List[str] = []
    text = (brief_text or "") + " " + skill.name + " " + skill.district
    # 人群/交通/目的简单关键词映射
    if any(k in text for k in ("亲子", "家庭", "孩子")):
        snippets.append("目标人群聚焦亲子家庭（4–12 岁），决策人为 30–45 岁家长。")
    if any(k in text for k in ("自驾", "高铁", "地铁")):
        snippets.append("交通结构：自驾/高铁/地铁接驳，媒介需覆盖交通枢纽与家庭客源。")
    if any(k in text for k in ("暑期", "旺季", "节假")):
        snippets.append("主档期 2027 暑期 7–8 月，节假日高峰，前置上刊。")
    snippets.extend(skill.messaging[:2])
    return snippets


__all__ = ["retrieve_strategy"]
