# -*- coding: utf-8 -*-
"""Agent API 冒烟：技能清单 + 分析入口 + 澄清路径。"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from server.main import app

client = TestClient(app)


def test_agent_skills():
    r = client.get("/api/agent/skills")
    assert r.status_code == 200
    body = r.json()
    assert body["load_order"] == [
        "brief-intake", "data-inventory", "data-bigdata",
        "audience-strategy", "plan-analysis", "proposal-narrative",
    ]
    assert body["validation_errors"] == []
    assert {s["stage"] for s in body["skills"]} == {
        "intake", "data_inventory", "data_bigdata", "strategy", "analysis", "narrative",
    }


def test_agent_analyze_quick():
    r = client.post("/api/agent/analyze", json={
        "brief_text": "上海乐高乐园，预算200万，暑期8周，公交+地铁，亲子家庭",
        "options": {
            "allow_defaults": True,
            "mode": "quick",
            "include_elasticity": False,
            "llm": "off",
        },
    })
    assert r.status_code == 200
    body = r.json()
    assert body["status"] in ("ready", "ready_with_assumptions")
    assert body["scenarios"][0]["id"] == "base"
    assert body["narrative"]["markdown"]
    assert r.headers.get("x-agent-status") in ("ready", "ready_with_assumptions")


def test_agent_analyze_needs_clarification():
    r = client.post("/api/agent/analyze", json={
        "brief_text": "预算200万，做个乐园提案",
        "options": {"allow_defaults": False, "llm": "off"},
    })
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "needs_clarification"
    assert body["analysis"] is None
    assert body["brief"]["questions"]
