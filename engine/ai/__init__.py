# -*- coding: utf-8 -*-
"""离线 AI 工作流：规则 brief 解析 / 策略检索 / 可选 LLM / narrator 模板。

诚实原则：无 LLM 时 llm_used=false，不假装 AI 工作；LLM 永不产出数字。
"""
from .brief_parser import parse_brief
from .retrieval import retrieve_strategy
from .narrator import narrate

__all__ = ["parse_brief", "retrieve_strategy", "narrate"]
