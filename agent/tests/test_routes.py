# -*- coding: utf-8 -*-
"""方案线路几何：编排注入、缓存隔离、GeoJSON 端点与按需取数接口。"""
from __future__ import annotations

import copy
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from agent.data_skills import _clean_path
from agent.orchestration import (
    ProposalRunner,
    _enrich_routes,
    _lines_from_plan,
    _metro_lines_from_plan,
    persist_run,
)
from server import core


def _plan():
    return {
        "plan": {
            "bus": [
                {"id": "bus:17:大三侧", "line": "17", "status": "paid", "total_wan": 8.0},
                {"id": "bus:136:大三侧", "line": "136", "status": "paid", "total_wan": 10.0},
            ],
            "metro": [],
            "summary": {},
        },
        "coverage": {
            "map_layers": {
                "bus": [
                    {"id": "bus:136:大三侧", "geometry": None, "schematic_district": "长宁-普陀", "selected": True},
                    {"id": "bus:17:大三侧", "geometry": None, "schematic_district": "徐汇-闵行", "selected": True},
                ],
                "metro": [],
                "poi": [],
            },
            "poi_hits": [],
        },
        "meta": {"data_version": "test-dv"},
    }


def _routes_payload():
    return {
        "ok": False,
        "status": "degraded",
        "reason": "PARTIAL_ROUTES",
        "source": "新云传媒大数据可视化平台 · AI线路",
        "data_month": "202305",
        "fetched_at": "2026-11-22T00:00:00+08:00",
        "summary": {"requested": 2, "resolved": 1, "cached": 1, "fetched": 0, "missing": 1},
        "lines": [
            {
                "requested": "136",
                "line": "136",
                "lineName": "136路",
                "lineId": 9900,
                "status": "cached",
                "points": 2,
                "source_points": 2,
                "simplified": False,
                "path": [[121.40, 31.20], [121.41, 31.21]],
                "bbox": [121.40, 31.20, 121.41, 31.21],
                "fetched_at": "2026-11-22T00:00:00+08:00",
            }
        ],
        "missing": [{"requested": "17", "reason": "NOT_FOUND"}],
    }


def test_lines_from_plan_sorted_by_spend_and_normalized():
    lines, items = _lines_from_plan(_plan())
    assert lines == ["136", "17"]
    assert items["136"] == ["bus:136:大三侧"]
    assert _lines_from_plan(None) == ([], {})


def _metro_plan():
    return {
        "plan": {
            "bus": [],
            "metro": [
                {
                    "id": "metro:人民广场:2号口",
                    "station": "人民广场",
                    "line": None,
                    "status": "paid",
                    "total_wan": 40.0,
                    "reasons": ["L01/L09/L11换乘"],
                    "evidence": [{"type": "transfer", "text": "L01/L09/L11换乘"}],
                },
                {
                    "id": "metro:徐家汇:1号口",
                    "station": "徐家汇",
                    "line": None,
                    "status": "paid",
                    "total_wan": 30.0,
                    "reasons": ["L01/L09/L11换乘"],
                    "evidence": [],
                },
            ],
            "summary": {},
        },
        "coverage": {"map_layers": {"bus": [], "metro": [], "poi": []}, "poi_hits": []},
        "meta": {"data_version": "test-dv"},
    }


def _metro_payload():
    def line(name, line_id, name_platform=None):
        return {
            "requested": name,
            "line": name,
            "lineName": name_platform or name,
            "lineId": line_id,
            "status": "fetched",
            "points": 2,
            "path": [[121.47, 31.23], [121.48, 31.24]],
            "bbox": [121.47, 31.23, 121.48, 31.24],
            "fetched_at": "2026-11-22T00:00:00+08:00",
        }

    return {
        "ok": True,
        "status": "ready",
        "reason": None,
        "source": "新云传媒大数据可视化平台 · AI线路",
        "data_month": "202305",
        "fetched_at": "2026-11-22T00:00:00+08:00",
        "summary": {"requested": 3, "resolved": 3, "cached": 0, "fetched": 3, "missing": 0},
        "lines": [
            line("地铁1号线", 11288),
            line("地铁9号线", 11297),
            line("地铁11号线", 11299, "地铁11号线(嘉定北)"),
        ],
        "missing": [],
    }


def test_metro_lines_from_plan_uses_evidence_and_station_lines():
    lines, items = _metro_lines_from_plan(_metro_plan())
    assert {"地铁1号线", "地铁9号线", "地铁11号线"} <= set(lines)
    assert "metro:人民广场:2号口" in items["地铁1号线"]
    assert "metro:徐家汇:1号口" in items["地铁11号线"]
    assert _metro_lines_from_plan(None) == ([], {})


def test_enrich_routes_adds_metro_routes():
    enriched, summary = _enrich_routes(_metro_plan(), _metro_payload(), "test-metro")

    layers = enriched["coverage"]["map_layers"]
    assert layers["bus_routes"] == []
    assert len(layers["metro_routes"]) == 3
    assert all(r["media"] == "metro" for r in layers["metro_routes"])
    by_line = {r["line"]: r for r in layers["metro_routes"]}
    assert by_line["地铁11号线"]["lineName"] == "地铁11号线(嘉定北)"
    assert by_line["地铁11号线"]["items"] == ["metro:人民广场:2号口", "metro:徐家汇:1号口"]
    assert by_line["地铁1号线"]["geometry"]["path"] == [[121.47, 31.23], [121.48, 31.24]]
    assert layers["metro_routes_meta"]["status"] == "ready"

    metro_items = {m["id"]: m for m in enriched["plan"]["metro"]}
    assert metro_items["metro:人民广场:2号口"]["route_status"] == "ready"
    assert "地铁1号线" in metro_items["metro:人民广场:2号口"]["route_ref"]

    assert summary["summary"]["resolved"] == 3
    assert summary["lines"] and all(item["media"] == "metro" for item in summary["lines"])
    assert summary["geojson_url"] == "/api/proposals/test-metro/routes.geojson"


def test_clean_path_validates_and_simplifies():
    path, simplified = _clean_path([[121.4, 31.2], ["x", 0], [121.5, 31.3], [999, 0]])
    assert path == [[121.4, 31.2], [121.5, 31.3]]
    assert simplified is False

    many = [[121.0 + i * 0.0001, 31.0] for i in range(1200)]
    sampled, simplified = _clean_path(many, max_points=100)
    assert simplified is True
    assert len(sampled) == 100
    assert sampled[0] == many[0] and sampled[-1] == many[-1]


def test_enrich_routes_does_not_mutate_engine_response():
    original = _plan()
    before = copy.deepcopy(original)
    enriched, summary = _enrich_routes(original, _routes_payload(), "test-run")

    assert original == before  # engine cache object untouched
    assert "bus_routes" not in original["coverage"]["map_layers"]
    assert "route_ref" not in original["plan"]["bus"][0]

    layers = enriched["coverage"]["map_layers"]
    assert len(layers["bus_routes"]) == 1
    route = layers["bus_routes"][0]
    assert route["line"] == "136"
    assert route["lineName"] == "136路"
    assert route["geometry"]["type"] == "line"
    assert route["geometry"]["path"] == [[121.40, 31.20], [121.41, 31.21]]
    assert route["items"] == ["bus:136:大三侧"]

    by_id = {b["id"]: b for b in layers["bus"]}
    assert by_id["bus:136:大三侧"]["route_ref"] == "136"
    assert by_id["bus:136:大三侧"]["route_status"] == "ready"
    assert by_id["bus:17:大三侧"]["route_ref"] == "17"
    assert by_id["bus:17:大三侧"]["route_status"] == "missing"

    plan_items = {b["id"]: b for b in enriched["plan"]["bus"]}
    assert plan_items["bus:136:大三侧"]["route_status"] == "ready"
    assert plan_items["bus:17:大三侧"]["route_status"] == "missing"

    assert summary["geojson_url"] == "/api/proposals/test-run/routes.geojson"
    assert summary["summary"] == {"requested": 2, "resolved": 1, "cached": 1, "fetched": 0, "missing": 1}


class _FakeRuntime:
    def __init__(self):
        self.snapshot_calls = []

    def inventory_snapshot(self, months, *, overwrite=False, media="all"):
        self.snapshot_calls.append({"months": list(months), "overwrite": overwrite, "media": media})
        return {"ok": True, "entries": []}

    def bigdata_coverage(self, *a, **k):
        return {"ok": True, "status": "ready", "reason": None, "summary": {"bus": 2, "metro": 0}}

    def bigdata_poi(self, *a, **k):
        return {"ok": True, "status": "ready", "reason": None, "summary": {"商场": 1}}

    def bigdata_routes(self, lines, **k):
        assert lines == ["136", "17"]
        return _routes_payload()


def test_runner_adds_data_routes_stage(monkeypatch):
    import engine.orchestrator as orch

    monkeypatch.setattr(orch, "generate_plan", lambda request, include_elasticity=False: copy.deepcopy(_plan()))

    payload = {
        "brief_text": "上海乐高乐园，预算500万，暑期8周，公交+地铁，直客",
        "request": {
            "industry": "乐园", "venue": "lego_shanghai", "budget_wan": 500,
            "media": ["bus", "metro"], "start_date": "2027-07-01", "weeks": 8,
            "customer_type": "direct", "locks": {"include": [], "exclude": []},
        },
        "options": {
            "data_mode": "cached", "include_elasticity": False,
            "allow_defaults": True, "include_routes": True,
        },
    }
    runtime = _FakeRuntime()
    result = ProposalRunner(data_runtime=runtime).run(payload, run_id="test-routes-stage")
    assert runtime.snapshot_calls[0]["overwrite"] is True  # 强制实时拉取，忽略 data_mode=cached
    assert runtime.snapshot_calls[0]["media"] == "all"
    stages = [s["stage"] for s in result["agent"]["stages"]]
    assert "data_routes" in stages
    assert stages.index("engine") < stages.index("data_routes") < stages.index("visualize")
    assert result["data"]["routes"]["summary"]["resolved"] == 1
    assert result["plan"]["coverage"]["map_layers"]["bus_routes"][0]["line"] == "136"
    assert result["status"] == "degraded"  # 17 缺几何，显式降级


def test_proposal_routes_geojson_endpoint():
    run_id = "test-routes-geojson"
    result = {
        "run_id": run_id,
        "status": "degraded",
        "created_at": "2026-11-22T00:00:00+08:00",
        "finished_at": "2026-11-22T00:00:01+08:00",
        "inputs": {"request": {"venue": "lego_shanghai"}},
        "agent": None,
        "plan": {
            "meta": {"data_version": "test-dv"},
            "coverage": {
                "map_layers": {
                    "bus_routes": [
                        {
                            "line": "136",
                            "lineName": "136路",
                            "lineId": 9900,
                            "items": ["bus:136:大三侧"],
                            "geometry": {"type": "line", "path": [[121.4, 31.2], [121.41, 31.21]], "points": 2},
                            "source": "新云传媒大数据可视化平台 · AI线路",
                            "data_month": "202305",
                            "confidence": "approx",
                        }
                    ]
                }
            },
        },
        "data": {"routes": {"status": "degraded", "reason": "PARTIAL_ROUTES", "missing": [{"line": "17", "reason": "NOT_FOUND"}]}},
        "elasticity": None, "warnings": [], "error": None,
    }
    path = os.path.join(core.ROOT, "data", "runs", f"{run_id}.json")
    try:
        persist_run(result)
        code, payload, _headers = core.proposal_routes(run_id)
        assert code == 200
        assert payload["type"] == "FeatureCollection"
        assert len(payload["features"]) == 1
        feature = payload["features"][0]
        assert feature["properties"]["line"] == "136"
        assert feature["geometry"]["coordinates"] == [[121.4, 31.2], [121.41, 31.21]]
        assert payload["meta"]["run_id"] == run_id
        assert "2023-05" in payload["meta"]["disclaimer"]
        assert payload["meta"]["missing"][0]["line"] == "17"
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def test_api_proposal_routes_registered():
    from fastapi.testclient import TestClient
    from server.main import app

    client = TestClient(app)
    run_id = "test-routes-api"
    result = {
        "run_id": run_id,
        "status": "degraded",
        "created_at": "2026-11-22T00:00:00+08:00",
        "finished_at": "2026-11-22T00:00:01+08:00",
        "inputs": {"request": {"venue": "lego_shanghai"}},
        "agent": None,
        "plan": {
            "meta": {"data_version": "test-dv"},
            "coverage": {"map_layers": {"bus_routes": [{
                "line": "136", "lineName": "136路", "lineId": 9900,
                "items": ["bus:136:大三侧"],
                "geometry": {"type": "line", "path": [[121.4, 31.2], [121.41, 31.21]], "points": 2},
                "source": "新云传媒大数据可视化平台 · AI线路", "data_month": "202305",
            }]}},
        },
        "data": {"routes": {"status": "ready", "summary": {"requested": 1, "resolved": 1}, "missing": []}},
        "elasticity": None, "warnings": [], "error": None,
    }
    path = os.path.join(core.ROOT, "data", "runs", f"{run_id}.json")
    try:
        persist_run(result)
        r = client.get(f"/api/proposals/{run_id}/routes.geojson")
        assert r.status_code == 200
        body = r.json()
        assert body["type"] == "FeatureCollection"
        assert body["features"][0]["properties"]["line"] == "136"
        assert body["features"][0]["geometry"]["coordinates"][0] == [121.4, 31.2]
    finally:
        try:
            os.remove(path)
        except OSError:
            pass

    missing = client.get("/api/proposals/no-such-run/routes.geojson")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "RUN_NOT_FOUND"


def test_routes_lookup_validation_and_success(monkeypatch):
    code, payload, _ = core.routes_lookup({"lines": []})
    assert code == 422
    assert payload["error"]["code"] == "VALIDATION_ERROR"

    import agent.data_skills as ds

    class _Runtime:
        def bigdata_routes(self, lines, **k):
            assert lines == ["136"]
            return _routes_payload()

    monkeypatch.setattr(ds, "default_data_runtime", lambda: _Runtime())
    code, payload, _ = core.routes_lookup({"lines": ["136"]})
    assert code == 200
    assert payload["type"] == "FeatureCollection"
    assert payload["status"] == "degraded"
    assert payload["features"][0]["properties"]["line"] == "136"
    assert payload["note"]


def test_proposal_routes_geojson_merges_bus_and_metro():
    run_id = "test-routes-metro-geojson"
    result = {
        "run_id": run_id,
        "status": "done",
        "created_at": "2026-11-22T00:00:00+08:00",
        "finished_at": "2026-11-22T00:00:01+08:00",
        "inputs": {"request": {"venue": "lego_shanghai"}},
        "agent": None,
        "plan": {
            "meta": {"data_version": "test-dv"},
            "coverage": {
                "map_layers": {
                    "bus_routes": [{
                        "line": "136", "lineName": "136路", "lineId": 9900, "media": "bus",
                        "items": ["bus:136:大三侧"],
                        "geometry": {"type": "line", "path": [[121.4, 31.2], [121.41, 31.21]], "points": 2},
                    }],
                    "metro_routes": [{
                        "line": "地铁1号线", "lineName": "地铁1号线", "lineId": 11288, "media": "metro",
                        "items": ["metro:人民广场:2号口"],
                        "geometry": {"type": "line", "path": [[121.43, 31.23], [121.44, 31.24]], "points": 2},
                    }],
                }
            },
        },
        "data": {"routes": {"status": "ready", "reason": None, "missing": []}},
        "elasticity": None, "warnings": [], "error": None,
    }
    path = os.path.join(core.ROOT, "data", "runs", f"{run_id}.json")
    try:
        persist_run(result)
        code, payload, _ = core.proposal_routes(run_id)
        assert code == 200
        assert len(payload["features"]) == 2
        assert {f["properties"]["media"] for f in payload["features"]} == {"bus", "metro"}
        metro = next(f for f in payload["features"] if f["properties"]["media"] == "metro")
        assert metro["properties"]["line"] == "地铁1号线"
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
