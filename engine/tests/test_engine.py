# -*- coding: utf-8 -*-
"""引擎单元测试 + 集成测试。"""
from __future__ import annotations

import json
import math
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from engine.orchestrator import generate_plan, generate_elasticity
from engine.models import PlanRequest, PlanError
from engine.finance import load_rate_card, quote
from engine.data_loader import load_inventory
from engine.skill_loader import build_skill


def _req(**kw):
    base = {"venue": "lego_shanghai", "budget_wan": 500, "media": ["bus", "metro"],
            "start_date": "2027-07-01", "weeks": 8, "customer_type": "direct"}
    base.update(kw)
    return base


# --------------------------------------------------------------------------- #
# 报价分摊
# --------------------------------------------------------------------------- #
def test_quote_allocation_sums_to_total():
    rc = load_rate_card()
    items = [
        {"kind": "bus", "level": "S", "units": 4, "months": 2},
        {"kind": "metro", "level": "A++", "units": 2, "months": 2},
    ]
    q = quote(items, rc, 500, "direct")
    ac = q["allocation_check"]
    assert ac["passed"] is True
    assert abs(ac["sum_lines"] - ac["total"]) <= 1.0
    assert q["total_paid_wan"] <= 500


def test_quote_discount_tier():
    rc = load_rate_card()
    # 文件阈值 0/100/200/300/400：gross 300 落 73% 档（300-399），gross 400 落 68% 档
    items_300 = [{"kind": "bus", "level": "S", "units": 25, "months": 2}]  # gross 300
    q300 = quote(items_300, rc, 800, "direct")
    assert q300["discount_tier"]["rate"] == 0.73  # 300-399 -> 73%
    items_400 = [{"kind": "bus", "level": "S", "units": 50, "months": 2}]  # gross 600
    q600 = quote(items_400, rc, 800, "direct")
    assert q600["discount_tier"]["rate"] == 0.68  # >=400 -> 68%


def test_agency_fee_only_4a():
    rc = load_rate_card()
    items = [{"kind": "bus", "level": "S", "units": 10, "months": 2}]
    qd = quote(items, rc, 200, "direct")
    qa = quote(items, rc, 300, "4a")
    assert qd["agency_fee_wan"] == 0.0
    assert qa["agency_fee_wan"] > 0.0


# --------------------------------------------------------------------------- #
# 库存 / 约束
# --------------------------------------------------------------------------- #
def test_budget_respected():
    d = generate_plan(_req(budget_wan=500))
    assert d["quote"]["total_paid_wan"] <= 500
    assert d["validation"]["passed"]


def test_inventory_not_exceeded():
    d = generate_plan(_req(budget_wan=500))
    for it in d["plan"]["bus"] + d["plan"]["metro"]:
        assert it["units"] <= it["free_count"]


def test_single_media_bus_only():
    d = generate_plan(_req(media=["bus"], budget_wan=500))
    assert d["plan"]["summary"]["metro_units"] == 0
    assert d["plan"]["summary"]["bus_units"] > 0


def test_single_media_metro_only():
    d = generate_plan(_req(media=["metro"], budget_wan=300))
    assert d["plan"]["summary"]["bus_units"] == 0
    assert d["plan"]["summary"]["metro_units"] > 0


# --------------------------------------------------------------------------- #
# 确定性：同输入 5 次一致（除 meta）
# --------------------------------------------------------------------------- #
def test_determinism():
    req = _req(budget_wan=500, media=["bus", "metro"])
    plans = [generate_plan(req) for _ in range(5)]
    base = json.dumps(plans[0], ensure_ascii=False, sort_keys=True)
    # 排除 meta 里会变的字段
    sigs = []
    for p in plans:
        q = json.loads(json.dumps(p))
        for k in ("generated_at", "request_id", "solve_ms", "total_ms", "cache_hit"):
            q["meta"].pop(k, None)
        sigs.append(json.dumps(q, ensure_ascii=False, sort_keys=True))
    assert all(s == sigs[0] for s in sigs)


# --------------------------------------------------------------------------- #
# 三场馆 × 三预算矩阵
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("venue", ["lego_shanghai", "disney_shanghai", "haichang_shanghai"])
@pytest.mark.parametrize("budget", [100, 200, 500])
def test_matrix_feasible(venue, budget):
    d = generate_plan(_req(venue=venue, budget_wan=budget))
    assert d["meta"]["status"] in ("OPTIMAL", "FEASIBLE")
    assert d["validation"]["passed"]
    assert round(d["quote"]["total_paid_wan"], 2) <= budget


def test_schedule_batches_before_golive_and_units_sum():
    """排期：所有批次日期 < go-live；批次 units 总和 == 付费 units；阶段不重叠。"""
    from datetime import date as _date
    d = generate_plan(_req(budget_wan=500))
    sched = d["schedule"]
    go_live = _date.fromisoformat(sched["go_live"])
    batches = sched["batches"]
    # 批次全部在 go-live 前
    for b in batches:
        assert _date.fromisoformat(b["date"]) < go_live, f"批次 {b['id']} 越过上刊日"
    # units 总和 == 付费 units
    batch_units = sum(b["units"] for b in batches)
    paid_units = d["plan"]["summary"]["bus_units"] + d["plan"]["summary"]["metro_units"]
    assert batch_units == paid_units
    # 阶段 P1-P4 严格不重叠（顺序倒推）
    ph = {p["id"]: (_date.fromisoformat(p["start"]), _date.fromisoformat(p["end"])) for p in sched["phases"]}
    for a, b in (("P1", "P2"), ("P2", "P3"), ("P3", "P4")):
        assert ph[a][1] < ph[b][0], f"{a} 与 {b} 重叠"


def test_effects_no_nan_and_reach_capped():
    req = _req(budget_wan=500)
    d = generate_plan(req, include_elasticity=True)
    e = d["effects"]
    for k in ("impressions", "grp", "reach", "frequency", "cpm_yuan"):
        assert not math.isnan(e[k])
    assert e["reach"] <= e["parameters"]["reach_cap"] + 1e-9


def test_elasticity_has_9_points():
    d = generate_elasticity(_req(budget_wan=500))
    assert len(d["points"]) == 9
    imps = [p["impressions"] for p in d["points"]]
    assert all(imps[i] <= imps[i + 1] for i in range(len(imps) - 1))


def test_lock_include_respected():
    d = generate_plan(_req(budget_wan=500))
    first_bus = d["plan"]["bus"][0]["id"] if d["plan"]["bus"] else None
    if first_bus:
        d2 = generate_plan(_req(budget_wan=500, locks={"include": [first_bus], "exclude": []}))
        ids = [it["id"] for it in d2["plan"]["bus"] + d2["plan"]["metro"]]
        assert first_bus in ids


def test_lock_conflict_unknown_id():
    """未知 include ID 必须 raise LOCK_CONFLICT，不静默忽略。"""
    with pytest.raises(PlanError) as ei:
        generate_plan(_req(budget_wan=500, locks={"include": ["bus:99999:不存在"], "exclude": []}))
    assert ei.value.code == "LOCK_CONFLICT"


def test_lock_conflict_include_exclude():
    """include 与 exclude 冲突必须 raise。"""
    d = generate_plan(_req(budget_wan=500))
    first_bus = d["plan"]["bus"][0]["id"]
    with pytest.raises(PlanError) as ei:
        generate_plan(_req(budget_wan=500, locks={"include": [first_bus], "exclude": [first_bus]}))
    assert ei.value.code == "LOCK_CONFLICT"


def test_data_unavailable_raises():
    req = PlanRequest.from_dict(_req(start_date="2027-12-01"))
    with pytest.raises(PlanError) as ei:
        load_inventory(req, allow_fallback=False)
    assert ei.value.code == "DATA_UNAVAILABLE"


def _write_snapshot(tmp_path, month, kind, rows, header_extra=()):
    """写一个月的合成快照 CSV，返回路径。"""
    import csv as _csv
    cols = ["lineName", "lineLevel", "freeCount", "specialSituation"]
    if kind == "bus":
        cols = ["lineName", "mediaName", "lineLevel", "freeCount", "specialSituation", "companyName"]
    else:
        cols = ["lineName", "exitName", "lineLevel", "freeCount", "specialSituation"]
    cols = list(cols) + list(header_extra)
    fn = f"{kind}_{month}-01_{month}-28.csv"
    p = tmp_path / fn
    with open(p, "w", encoding="utf-8", newline="") as f:
        w = _csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in cols})
    return p


def _patch_snapshot_dir(monkeypatch, d):
    import engine.config as cfg
    monkeypatch.setattr(cfg, "SNAPSHOT_DIR", str(d))
    monkeypatch.setattr(cfg, "DATA_DIR", str(d))
    from engine import data_loader
    # 清掉模块级缓存（DATA_DIR 变动后）
    monkeypatch.setattr(data_loader, "config", cfg)


def test_cross_month_min_free_excludes_zero_month(tmp_path, monkeypatch):
    """跨月活动：某月 free=0 或 special 非空 => 整键剔除，不取另一月正值。"""
    p_06 = _write_snapshot(tmp_path, "2027-06", "bus", [
        {"lineName": "100", "mediaName": "大三侧", "lineLevel": "1", "freeCount": "10", "specialSituation": ""},
        {"lineName": "200", "mediaName": "大三侧", "lineLevel": "2", "freeCount": "5", "specialSituation": ""},
    ])
    # 7 月：line 100 free=0（整键应剔除）；line 200 special 非空（整键应剔除）；line 300 正常
    p_07 = _write_snapshot(tmp_path, "2027-07", "bus", [
        {"lineName": "100", "mediaName": "大三侧", "lineLevel": "1", "freeCount": "0", "specialSituation": ""},
        {"lineName": "200", "mediaName": "大三侧", "lineLevel": "2", "freeCount": "8", "specialSituation": "整修"},
        {"lineName": "300", "mediaName": "大三侧", "lineLevel": "1", "freeCount": "6", "specialSituation": ""},
        {"lineName": "300", "mediaName": "大三侧", "lineLevel": "1", "freeCount": "6", "specialSituation": ""},
    ])
    # 地铁仅覆盖 7 月（请求只要求 bus，缺 metro 不应失败）
    _write_snapshot(tmp_path, "2027-07", "metro", [
        {"lineName": "人民广场", "exitName": "1号口", "lineLevel": "2", "freeCount": "3", "specialSituation": ""},
    ])
    _patch_snapshot_dir(monkeypatch, tmp_path)

    req = PlanRequest.from_dict(_req(start_date="2027-06-01", weeks=8, media=["bus"]))
    inv = load_inventory(req, allow_fallback=False)

    ids = {c.id for c in inv.bus}
    # line 100（7 月 free=0）被整键剔除
    assert "bus:100:大三侧" not in ids
    # line 200（7 月 special 非空）被整键剔除
    assert "bus:200:大三侧" not in ids
    # line 300（两月均正常）保留
    assert "bus:300:大三侧" in ids


def test_cross_month_min_free_min_not_sum(tmp_path, monkeypatch):
    """跨月取 min free，绝不求和。"""
    _write_snapshot(tmp_path, "2027-06", "bus", [
        {"lineName": "911", "mediaName": "大三侧", "lineLevel": "1", "freeCount": "12", "specialSituation": ""},
    ])
    _write_snapshot(tmp_path, "2027-07", "bus", [
        {"lineName": "911", "mediaName": "大三侧", "lineLevel": "1", "freeCount": "3", "specialSituation": ""},
    ])
    _write_snapshot(tmp_path, "2027-07", "metro", [
        {"lineName": "人民广场", "exitName": "1号口", "lineLevel": "2", "freeCount": "3", "specialSituation": ""},
    ])
    _patch_snapshot_dir(monkeypatch, tmp_path)

    req = PlanRequest.from_dict(_req(start_date="2027-06-01", weeks=8, media=["bus"]))
    inv = load_inventory(req, allow_fallback=False)
    cand = next(c for c in inv.bus if c.line_name == "911")
    assert cand.free_count == 3  # min(12,3)，不是 15


def test_bus_only_does_not_require_metro_snapshot(tmp_path, monkeypatch):
    """bus-only 请求不因缺 metro 快照而失败。"""
    _write_snapshot(tmp_path, "2027-07", "bus", [
        {"lineName": "911", "mediaName": "大三侧", "lineLevel": "1", "freeCount": "12", "specialSituation": ""},
    ])
    _patch_snapshot_dir(monkeypatch, tmp_path)

    req = PlanRequest.from_dict(_req(start_date="2027-07-01", weeks=4, media=["bus"]))
    # 不抛 DATA_UNAVAILABLE
    inv = load_inventory(req, allow_fallback=False)
    assert len(inv.bus) >= 1
