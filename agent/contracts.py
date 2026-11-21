# -*- coding: utf-8 -*-
"""Agent 层共享契约。

设计原则：
- Agent 只做「理解 / 设计 / 编排 / 解释」，不做算术；所有数字来自 engine。
- 输出是稳定的 JSON 结构，CLI / API / 前端共用。
- 缺字段不静默编造：要么提问，要么写出 assumption。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

AGENT_NAME = "proposal-agent"
AGENT_VERSION = "1.0.0"
SCHEMA_VERSION = "agent-analysis.v1"

STATUS_READY = "ready"
STATUS_READY_WITH_ASSUMPTIONS = "ready_with_assumptions"
STATUS_NEEDS_CLARIFICATION = "needs_clarification"
STATUS_ERROR = "error"

SOURCE_STRUCTURED = "structured"
SOURCE_BRIEF = "brief"
SOURCE_INFERRED = "inferred"
SOURCE_DEFAULT = "default"
SOURCE_LLM = "llm"

REQUIRED_SLOTS = ("venue", "budget_wan", "media")
OPTIONAL_SLOTS = ("start_date", "weeks", "customer_type", "objective")


@dataclass
class SlotValue:
    """一个槽位的值 + 来源，保证每个字段都能被追问。"""

    value: Any = None
    source: str = "missing"
    confidence: str = "low"  # high | medium | low
    evidence: str = ""

    @property
    def missing(self) -> bool:
        return self.value is None or self.value == "" or self.value == []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "value": self.value,
            "source": self.source,
            "confidence": self.confidence,
            "evidence": self.evidence,
        }


@dataclass
class BriefState:
    """intake 阶段的完整结果。"""

    raw_text: str
    request: Dict[str, Any]
    slots: Dict[str, SlotValue] = field(default_factory=dict)
    missing: List[str] = field(default_factory=list)
    questions: List[Dict[str, Any]] = field(default_factory=list)
    assumptions: List[Dict[str, Any]] = field(default_factory=list)
    objective: str = "balanced"
    audience_notes: List[str] = field(default_factory=list)
    constraints: Dict[str, Any] = field(default_factory=dict)
    compliance_flags: List[Dict[str, Any]] = field(default_factory=list)
    status: str = STATUS_READY
    summary: str = ""

    @property
    def blocking_questions(self) -> List[Dict[str, Any]]:
        return [q for q in self.questions if q.get("blocking")]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "raw_text": self.raw_text,
            "status": self.status,
            "summary": self.summary,
            "request": dict(self.request),
            "slots": {k: v.to_dict() for k, v in self.slots.items()},
            "missing": list(self.missing),
            "questions": list(self.questions),
            "assumptions": list(self.assumptions),
            "objective": self.objective,
            "audience_notes": list(self.audience_notes),
            "constraints": dict(self.constraints),
            "compliance_flags": list(self.compliance_flags),
        }


def normalize_options(raw: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """分析选项；所有阈值都可被 skill policy 覆盖，这里只做安全边界。"""
    raw = raw or {}
    allow_defaults = raw.get("allow_defaults")
    if allow_defaults is None:
        # API 默认允许补齐默认值并显式列出 assumption；CLI 默认严格提问。
        allow_defaults = bool(raw.get("defaults", False))
    mode = str(raw.get("mode") or "full").lower()
    if mode not in ("full", "quick"):
        mode = "full"
    try:
        max_scenarios = int(raw.get("max_scenarios", 4))
    except (TypeError, ValueError):
        max_scenarios = 4
    max_scenarios = max(1, min(6, max_scenarios))
    include_elasticity = raw.get("include_elasticity")
    if include_elasticity is None:
        include_elasticity = True
    return {
        "allow_defaults": bool(allow_defaults),
        "mode": mode,
        "max_scenarios": max_scenarios,
        "include_elasticity": bool(include_elasticity),
        "include_plan_artifacts": bool(raw.get("include_plan_artifacts", False)),
        "llm": str(raw.get("llm") or "auto").lower(),
        "max_questions": max(0, min(8, int(raw.get("max_questions", 5) or 5))),
    }


def error_payload(code: str, message: str, **extra: Any) -> Dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
            "recoverable": True,
            **extra,
        }
    }


def round_num(value: Any, digits: int = 2) -> Any:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return value
    if v != v or v in (float("inf"), float("-inf")):
        return 0
    return round(v, digits)


__all__ = [
    "AGENT_NAME",
    "AGENT_VERSION",
    "SCHEMA_VERSION",
    "STATUS_READY",
    "STATUS_READY_WITH_ASSUMPTIONS",
    "STATUS_NEEDS_CLARIFICATION",
    "STATUS_ERROR",
    "SOURCE_STRUCTURED",
    "SOURCE_BRIEF",
    "SOURCE_INFERRED",
    "SOURCE_DEFAULT",
    "SOURCE_LLM",
    "REQUIRED_SLOTS",
    "OPTIONAL_SLOTS",
    "SlotValue",
    "BriefState",
    "normalize_options",
    "error_payload",
    "round_num",
]
