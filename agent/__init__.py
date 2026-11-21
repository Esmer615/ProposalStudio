# -*- coding: utf-8 -*-
"""提案分析 Agent：接收客户需求，设计分析场景，调用确定性引擎，输出可追溯结论。

架构（见 Our-agent-skills/README.md）：
    intake -> strategy -> tools -> analysis -> guard -> narrative

对外入口：
    from agent import ProposalAgent
    result = ProposalAgent().run({"brief_text": "..."})
"""
from __future__ import annotations

from .contracts import AGENT_NAME, AGENT_VERSION
from .runtime import ProposalAgent, analyze_brief

__all__ = ["AGENT_NAME", "AGENT_VERSION", "ProposalAgent", "analyze_brief"]
