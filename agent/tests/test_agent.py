# -*- coding: utf-8 -*-
"""Agent 层测试：技能加载 / 需求解析 / 场景设计 / 数字守卫 / 端到端离线分析。"""
from __future__ import annotations

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from agent.contracts import STATUS_NEEDS_CLARIFICATION, normalize_options
from agent.intake import detect_compliance_flags, resolve_brief
from agent.llm import NullLLM
from agent.narrator import guard_numbers
from agent.runtime import ProposalAgent
from agent.skills import load_default_registry
from agent.strategy import ScenarioPlanner
from agent.tools import ToolRuntime


@pytest.fixture(scope="module")
def catalog():
    return ToolRuntime().catalog()


@pytest.fixture(scope="module")
def registry():
    return load_default_registry()


def test_skills_load_and_validate(registry):
    assert registry.validate() == []
    names = [s.name for s in registry.ordered()]
    assert names == [
        "brief-intake", "data-inventory", "data-bigdata",
        "audience-strategy", "plan-analysis", "proposal-narrative",
    ]
    assert registry.policy("analysis")["thresholds"]["absorption_floor"] == 0.85
    assert registry.policy("narrative")["forbidden_claims"]


def test_intake_rich_brief(catalog, registry):
    brief = resolve_brief(
        "客户是上海乐高乐园，预算200万，暑期8周，公交+地铁，要覆盖亲子家庭，希望提升曝光",
        {},
        catalog,
        normalize_options({}),
        compliance_policy=registry.policy("narrative"),
        intake_policy=registry.policy("intake"),
    )
    assert brief.request["venue"] == "lego_shanghai"
    assert brief.request["budget_wan"] == 200
    assert brief.request["media"] == ["bus", "metro"]
    assert brief.request["start_date"] == "2027-07-01"
    assert brief.request["weeks"] == 8
    assert brief.objective == "reach"
    assert brief.status in ("ready", "ready_with_assumptions")


def test_intake_missing_required_asks(catalog, registry):
    brief = resolve_brief(
        "预算200万，做个乐园提案",
        {},
        catalog,
        normalize_options({}),
        compliance_policy=registry.policy("narrative"),
        intake_policy=registry.policy("intake"),
    )
    assert brief.status == STATUS_NEEDS_CLARIFICATION
    fields = {q["field"] for q in brief.questions if q.get("blocking")}
    assert "venue" in fields
    assert "media" in fields


def test_intake_compliance_flags(registry):
    flags = detect_compliance_flags(
        "保证到园50万人，投在学校里，ROI要做到3",
        registry.policy("narrative"),
    )
    codes = {f["code"] for f in flags}
    assert "GUARANTEE_VISIT" in codes
    assert "IN_SCHOOL" in codes
    assert "ROI_PROMISE" in codes


def test_intake_negated_compliance_not_flagged(registry):
    flags = detect_compliance_flags(
        "不承诺到园人数，不投校内，不给 ROI",
        registry.policy("narrative"),
    )
    assert flags == []


def test_scenario_planner_precision_includes_media_reference(catalog, registry):
    brief = resolve_brief(
        "乐高，预算200万，公交+地铁，要精准触达亲子家庭",
        {},
        catalog,
        normalize_options({"allow_defaults": True}),
        compliance_policy=registry.policy("narrative"),
        intake_policy=registry.policy("intake"),
    )
    planner = ScenarioPlanner(registry.policy("strategy"))
    scenarios = planner.design(brief, catalog, normalize_options({"max_scenarios": 3}), None)
    ids = [s["id"] for s in scenarios]
    assert ids[0] == "base"
    assert any(i.startswith("media_") for i in ids)


def test_number_guard_rejects_unknown_number():
    payload = {"budget_wan": 200, "reach_pct": 0.803, "narrative": "模型估算"}
    ok, unknown = guard_numbers("预算 200 万，目标 Reach 80.3%，ROI 12.5%", payload)
    assert ok is False
    assert "12.5" in unknown


def test_number_guard_allows_known_numbers():
    payload = {"budget_wan": 200, "reach_pct": 0.803, "impressions": 27003200}
    ok, unknown = guard_numbers(
        "预算 200 万，总曝光 27,003,200 人次，目标 Reach 80.3%，折扣 88/83/78/73/68%（模型估算）",
        payload,
    )
    assert ok is True
    assert unknown == []


def test_agent_run_offline():
    result = ProposalAgent(llm=NullLLM("test")).run({
        "brief_text": "客户是上海乐高乐园，预算200万，暑期8周，公交+地铁，要覆盖亲子家庭，希望提升曝光",
        "options": {
            "allow_defaults": True,
            "max_scenarios": 2,
            "include_elasticity": False,
            "llm": "off",
        },
    })
    assert result["status"] in ("ready", "ready_with_assumptions")
    assert result["schema_version"] == "agent-analysis.v1"
    assert result["scenarios"], "至少应有基准方案"
    base = result["scenarios"][0]
    assert base["id"] == "base" and base["ok"] is True
    assert base["metrics"]["budget_wan"] == 200
    assert base["metrics"]["validation"]["passed"] is True
    assert result["recommendation"]["primary_scenario"] == "base"
    assert "模型估算" in result["narrative"]["markdown"]
    assert result["narrative"]["llm_used"] is False
    assert any(c["tool"] == "plan.generate" for c in result["tool_calls"])
    assert result["meta"]["data_version"]


def test_agent_clarification_without_defaults():
    result = ProposalAgent(llm=NullLLM("test")).run({
        "brief_text": "预算200万，做个乐园提案",
        "options": {"allow_defaults": False, "llm": "off"},
    })
    assert result["status"] == STATUS_NEEDS_CLARIFICATION
    assert result["analysis"] is None
    assert result["scenarios"] == []
    assert "需要补充信息" in result["narrative"]["markdown"]
