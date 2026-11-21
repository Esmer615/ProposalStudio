# -*- coding: utf-8 -*-
"""本地 API 冒烟测试：契约字段、错误码、批量、弹性。

引擎未就绪时，涉及求解的用例 skip（便于前端/服务并行开发）。
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from server.main import app

client = TestClient(app)

DEFAULT_REQ = {
    "industry": "乐园",
    "venue": "lego_shanghai",
    "budget_wan": 500,
    "media": ["bus", "metro"],
    "start_date": "2027-07-01",
    "weeks": 8,
    "customer_type": "direct",
    "locks": {"include": [], "exclude": []},
}


def _health() -> dict:
    return client.get("/api/health").json()


def _engine_ready() -> bool:
    return bool(_health().get("engine_available"))


def test_health() -> None:
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert "engine_available" in body
    assert "data_version" in body


def test_meta() -> None:
    r = client.get("/api/meta")
    assert r.status_code == 200
    body = r.json()
    assert body["industry"] == "乐园"
    assert len(body["venues"]) >= 3
    assert {m["id"] for m in body["media"]} == {"bus", "metro"}
    assert body["budget_range"]["min"] == 100


def test_manifest() -> None:
    r = client.get("/api/data/manifest")
    assert r.status_code == 200
    assert "manifest" in r.json()


def test_invalid_budget() -> None:
    req = dict(DEFAULT_REQ)
    req["budget_wan"] = 50
    r = client.post("/api/plan", json=req)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"


def test_invalid_venue() -> None:
    req = dict(DEFAULT_REQ)
    req["venue"] = "not_a_venue"
    r = client.post("/api/plan", json=req)
    assert r.status_code == 422


@pytest.mark.skipif(not _engine_ready(), reason="engine/orchestrator not ready")
def test_plan_default() -> None:
    r = client.post("/api/plan", json=DEFAULT_REQ)
    assert r.status_code == 200, r.text
    body = r.json()
    for key in (
        "meta", "inputs", "hypothesis", "strategy", "venue", "plan",
        "effects", "elasticity", "quote", "schedule", "coverage",
        "validation", "explanations", "workflow",
    ):
        assert key in body, f"missing {key}"
    assert body["meta"]["data_version"]
    assert body["validation"]["checks"]
    assert body["plan"]["bus"] or body["plan"]["metro"]
    assert body["effects"]["reach"] <= body["effects"]["parameters"]["reach_cap"] + 1e-9


@pytest.mark.skipif(not _engine_ready(), reason="engine/orchestrator not ready")
def test_plan_invalid_date() -> None:
    req = dict(DEFAULT_REQ)
    req["start_date"] = "2026-07-01"
    r = client.post("/api/plan", json=req)
    assert r.status_code == 422


@pytest.mark.skipif(not _engine_ready(), reason="engine/orchestrator not ready")
def test_batch_requests() -> None:
    reqs = []
    for b in (100, 200, 500):
        req = dict(DEFAULT_REQ)
        req["budget_wan"] = b
        reqs.append(req)
    r = client.post("/api/plans/batch", json={"requests": reqs})
    assert r.status_code == 200, r.text
    assert len(r.json()["plans"]) == 3


@pytest.mark.skipif(not _engine_ready(), reason="engine/orchestrator not ready")
def test_batch_budgets() -> None:
    req = dict(DEFAULT_REQ)
    req["budgets"] = [100, 200]
    r = client.post("/api/plans/batch", json=req)
    assert r.status_code == 200, r.text
    assert len(r.json()["plans"]) == 2


@pytest.mark.skipif(not _engine_ready(), reason="engine/orchestrator not ready")
def test_elasticity() -> None:
    r = client.post("/api/elasticity", json=DEFAULT_REQ)
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body.get("points", [])) >= 3
    assert "knee_budget_wan" in body
