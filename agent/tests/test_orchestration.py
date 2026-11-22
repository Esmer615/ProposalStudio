# -*- coding: utf-8 -*-
"""编排层测试：fake 数据运行时避免网络；覆盖强制实时拉取 / PlanResponse / needs_input / 持久化 / 6 skill 校验。"""
from __future__ import annotations

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from agent.orchestration import ProposalRunner, get_run, persist_run, submit_run
from agent.skills import load_default_registry


class _FakeDataRuntime:
    """记录红豆调用参数；不发网络。"""

    def __init__(self) -> None:
        self.snapshot_calls = []

    def inventory_snapshot(self, months, *, overwrite=False, media="all"):
        self.snapshot_calls.append({"months": list(months), "overwrite": overwrite, "media": media})
        return {
            "ok": True,
            "months": list(months),
            "entries": [{"month": months[0] if months else "2027-07", "media": "bus", "status": "ok", "rows": 10}],
            "failures": 0,
            "inventory_ts": "2026-11-22T00:00:00Z",
        }

    def bigdata_coverage(self, *a, **k):
        return {"ok": True, "status": "ready", "reason": None, "summary": {"bus": 0, "metro": 0}}

    def bigdata_poi(self, *a, **k):
        return {"ok": True, "status": "ready", "reason": None, "summary": {}}

    def bigdata_routes(self, lines, **k):
        return {
            "ok": True, "status": "ready", "reason": None,
            "source": "test-routes", "data_month": "202305",
            "summary": {"requested": len(lines), "resolved": 0, "cached": 0, "fetched": 0, "missing": 0},
            "lines": [], "missing": [],
        }


def _payload(**overrides):
    base = {
        "brief_text": "上海乐高乐园，预算500万，暑期8周，公交+地铁，直客",
        "request": {
            "industry": "乐园",
            "venue": "lego_shanghai",
            "budget_wan": 500,
            "media": ["bus", "metro"],
            "start_date": "2027-07-01",
            "weeks": 8,
            "customer_type": "direct",
            "locks": {"include": [], "exclude": []},
        },
        # data_mode=cached 仍然传入，用于证明它不会跳过实时拉取。
        "options": {"data_mode": "cached", "include_elasticity": False, "allow_defaults": True},
    }
    base.update(overrides)
    return base


def test_six_skills_validate():
    reg = load_default_registry()
    assert reg.validate() == []
    assert len(reg.ordered()) == 6
    stages = {s.stage for s in reg.ordered()}
    assert "data_inventory" in stages
    assert "data_bigdata" in stages


def test_forced_live_pull_produces_plan_response():
    runtime = _FakeDataRuntime()
    runner = ProposalRunner(data_runtime=runtime)
    result = runner.run(_payload(), run_id="test-live-0001")
    assert result["status"] in ("done", "degraded")
    assert result["plan"] is not None
    assert result["plan"].get("plan") is not None
    # data_mode=cached 被忽略：每次都必须 --overwrite、拉全部媒体
    assert runtime.snapshot_calls
    assert runtime.snapshot_calls[0]["overwrite"] is True
    assert runtime.snapshot_calls[0]["media"] == "all"
    inventory = result["data"]["inventory"]
    assert inventory["mode"] == "live"
    assert inventory["forced"] is True
    # 阶段固定
    assert [s["stage"] for s in result["agent"]["stages"]][:1] == ["intake"]
    assert any(s["stage"] == "data_inventory" and "实时拉取" in (s.get("summary") or "")
               for s in result["agent"]["stages"])


def test_needs_input_when_blocking_missing():
    runner = ProposalRunner()
    result = runner.run({
        "brief_text": "预算200万，做个乐园提案",
        "request": {},
        "options": {"data_mode": "cached", "allow_defaults": False},
    }, run_id="test-needs-0002")
    assert result["status"] == "needs_input"
    assert result["plan"] is None
    assert result["agent"]["questions"]


def test_run_persistence_and_get():
    run_id = "test-persist-0003"
    result = {
        "run_id": run_id,
        "status": "done",
        "created_at": "2026-11-22T00:00:00+08:00",
        "finished_at": "2026-11-22T00:00:01+08:00",
        "inputs": {}, "agent": None, "data": None, "plan": {"ok": True},
        "elasticity": None, "warnings": [], "error": None,
    }
    persist_run(result)
    got = get_run(run_id)
    assert got is not None
    assert got["run_id"] == run_id
    assert got["plan"]["ok"] is True


def test_submit_run_creates_queued():
    run_id = submit_run(_payload())
    assert run_id
    got = get_run(run_id)
    assert got["status"] == "queued"


def test_get_unknown_run_returns_none():
    assert get_run("does-not-exist") is None
