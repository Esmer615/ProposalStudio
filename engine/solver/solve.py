# -*- coding: utf-8 -*-
"""求解入口：CP-SAT 主模型 → HiGHS 兜底 → 贪心最后手段。

确定性保证：CP-SAT num_search_workers=1 + random_seed=42 + 固定时间窗。
不可行时按顺序松弛：等级配比 → 媒体配比 → 线路/站点最少数量 → 建议加预算/改锁；
绝不放宽预算或库存。

返回结构：
{
  "status": "OPTIMAL"|"FEASIBLE"|"INFEASIBLE",
  "solver": "CP-SAT"|"HiGHS"|"Greedy",
  "fallback_chain": [...],
  "bus": {item_id: units}, "metro": {item_id: units},
  "objective": float, "solve_ms": int, "relaxed": [...]
}
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple

from .. import config
from ..models import PlanError

SCALE = 10000  # 钱放大倍数（0.0001 万 = 1 单位，覆盖 4 位小数）
# 制作费默认（刊例口径，覆盖 rate_card 未提供时；正确值应从 finance.load_rate_card() 传入）
DEFAULT_PROD_BUS = 0.75
DEFAULT_PROD_METRO = 0.03


def _build_cost_unit(item: Dict[str, Any], months: int, discount: float, agency_factor: float,
                     prod_bus: float = DEFAULT_PROD_BUS, prod_metro: float = DEFAULT_PROD_METRO) -> int:
    """单 unit 总成本（含制作 + 4A），放大 SCALE 的整数（万元）。

    制作费来自刊例（finance.load_rate_card），不由 config 复刻。
    """
    up = item["unit_price_wan"]
    prod = prod_bus if item["kind"] == "bus" else prod_metro
    cost = up * months * discount * (1.0 + agency_factor) + prod
    return int(round(cost * SCALE))


def _add_greedy_hint(m, bus_items, metro_items, budget_wan, months, discount, agency_factor,
                     lock_bus, lock_metro, nights, bx, bb, mx, mb, bus_ub, metro_ub,
                     prod_bus=DEFAULT_PROD_BUS, prod_metro=DEFAULT_PROD_METRO):
    """给 CP-SAT 一个确定性贪心 warm-start，保证超时 incumbent 稳定。"""
    nb = len(bus_items)
    nm = len(metro_items)
    budget_left = budget_wan
    bus_units = [0] * nb
    metro_units = [0] * nm

    def _cu(it):
        return _build_cost_unit(it, months, discount, agency_factor, prod_bus, prod_metro)

    # 锁定优先
    for i in range(nb):
        if bus_items[i]["id"] in lock_bus:
            bus_units[i] = 1
            budget_left -= _cu(bus_items[i]) / SCALE
    for i in range(nm):
        if metro_items[i]["id"] in lock_metro:
            metro_units[i] = 1
            budget_left -= _cu(metro_items[i]) / SCALE

    def ratio(kind, it):
        c = _cu(it) / SCALE
        return it["score"] / c if c > 0 else 0.0

    order = []
    for i in range(nb):
        if bus_items[i]["id"] not in lock_bus:
            order.append(("b", i, ratio("bus", bus_items[i])))
    for i in range(nm):
        if metro_items[i]["id"] not in lock_metro:
            order.append(("m", i, ratio("metro", metro_items[i])))
    order.sort(key=lambda x: (-x[2], x[1]))

    for kind, i, _r in order:
        if kind == "b":
            c1 = _cu(bus_items[i]) / SCALE
            cap = nights * config.BUS_PER_NIGHT - sum(bus_units)
            u = 0
            while u < bus_ub[i] and u < cap and budget_left >= c1 * (u + 1):
                u += 1
            bus_units[i] = u
            budget_left -= c1 * u
        else:
            c1 = _cu(metro_items[i]) / SCALE
            cap = nights * config.METRO_PER_NIGHT - sum(metro_units)
            u = 0
            while u < metro_ub[i] and u < cap and budget_left >= c1 * (u + 1):
                u += 1
            metro_units[i] = u
            budget_left -= c1 * u

    for i in range(nb):
        m.AddHint(bx[i], bus_units[i])
        m.AddHint(bb[i], 1 if bus_units[i] > 0 else 0)
    for i in range(nm):
        m.AddHint(mx[i], metro_units[i])
        m.AddHint(mb[i], 1 if metro_units[i] > 0 else 0)


def _objective_value(bus_items, metro_items, bus_units, metro_units) -> float:
    obj = 0.0
    for it in bus_items:
        obj += it["score"] * bus_units.get(it["id"], 0)
    for it in metro_items:
        obj += it["score"] * metro_units.get(it["id"], 0)
    return round(obj, 2)


def _validate_locks(locks: Dict[str, List[str]], bus_items, metro_items) -> None:
    """锁定/排除校验：未知 ID、free<=0、include+exclude 冲突 → LOCK_CONFLICT。

    在求解前一次性校验，绝不静默忽略未知 ID（契约 §3）。
    """
    include = locks.get("include", []) or []
    exclude = locks.get("exclude", []) or []
    inc = set(include)
    exc = set(exclude)

    # include + exclude 冲突
    clash = inc & exc
    if clash:
        raise PlanError(
            "LOCK_CONFLICT",
            f"锁定项同时出现在 include 与 exclude：{sorted(clash)[:5]}",
            field="locks",
            suggestions=["从 include 或 exclude 中移除冲突项"],
            recoverable=False,
        )

    # 建立已知 ID 索引（bus/metro 全量候选，含 free_count）
    known: Dict[str, Dict[str, Any]] = {}
    for it in list(bus_items) + list(metro_items):
        known[it["id"]] = it

    unknown = [lid for lid in inc if lid not in known]
    if unknown:
        raise PlanError(
            "LOCK_CONFLICT",
            f"未找到锁定点位的候选：{sorted(unknown)[:5]}",
            field="locks.include",
            suggestions=[
                "核对点位 ID（是否来自候选清单）",
                "改用相邻出入口 / 同站其它口",
                "清除不存在的锁定项",
            ],
            recoverable=False,
        )

    zero = [lid for lid in inc if lid in known and int(known[lid].get("free_count", 0)) <= 0]
    if zero:
        raise PlanError(
            "LOCK_CONFLICT",
            f"锁定点位当前无可售库存（free<=0）：{sorted(zero)[:5]}",
            field="locks.include",
            suggestions=["改用相邻出入口 / 同站其它口", "选择其它档期", "清除该锁定项"],
            recoverable=False,
        )

    unknown_ex = [lid for lid in exc if lid not in known]
    if unknown_ex:
        # 排除未知 ID 无害（本就不在候选中），仅不报错；但记录为宽松处理
        pass


def solve(
    bus_items: List[Dict[str, Any]],
    metro_items: List[Dict[str, Any]],
    budget_wan: float,
    months: int,
    discount: float,
    customer_type: str,
    locks: Dict[str, List[str]],
    skill_bus_mix: Tuple[float, float],
    skill_metro_mix: Tuple[float, float],
    nights: int = config.BUS_INSTALL_NIGHTS,
    prod_bus: float = DEFAULT_PROD_BUS,
    prod_metro: float = DEFAULT_PROD_METRO,
) -> Dict[str, Any]:
    agency_factor = config.AGENCY_FEE_RATE if customer_type == "4a" else 0.0
    _validate_locks(locks, bus_items, metro_items)

    excl = set(locks.get("exclude", []))
    bus_items = [it for it in bus_items if it["id"] not in excl]
    metro_items = [it for it in metro_items if it["id"] not in excl]

    result = _solve_cpsat(bus_items, metro_items, budget_wan, months, discount, agency_factor, locks, nights,
                          skill_bus_mix, skill_metro_mix, prod_bus, prod_metro)
    if result is not None:
        return result

    try:
        hs = _solve_highs(bus_items, metro_items, budget_wan, months, discount, agency_factor, locks, nights,
                          prod_bus, prod_metro)
        if hs is not None:
            hs["fallback_chain"] = ["CP-SAT(failed)"]
            return hs
    except Exception:
        pass

    gr = _solve_greedy(bus_items, metro_items, budget_wan, months, discount, agency_factor, locks, nights,
                       prod_bus, prod_metro)
    gr["fallback_chain"] = ["CP-SAT(failed)", "HiGHS(failed)"]
    return gr


# --------------------------------------------------------------------------- #
# CP-SAT
# --------------------------------------------------------------------------- #
def _solve_cpsat(bus_items, metro_items, budget_wan, months, discount, agency_factor, locks, nights,
                 skill_bus_mix, skill_metro_mix, prod_bus=DEFAULT_PROD_BUS, prod_metro=DEFAULT_PROD_METRO):
    try:
        from ortools.sat.python import cp_model
    except Exception:
        return None

    budget_int = int(round(budget_wan * SCALE))
    nb = len(bus_items)
    nm = len(metro_items)

    lock_include = set(locks.get("include", []))
    lock_bus = set(lid for lid in lock_include if any(it["id"] == lid for it in bus_items))
    lock_metro = set(lid for lid in lock_include if any(it["id"] == lid for it in metro_items))

    # 地铁按“站点”聚合（每个候选是一个出入口；最小/最大站点数 = 去重线路数）
    metro_station_ids = sorted({it.get("line_name") or it["id"] for it in metro_items})

    # 逐级松弛顺序（文档化，绝不放松预算/库存）：
    #   relax=0 全约束
    #   relax=1 放松媒体配比下限（media_mix_min）——最先松，因地铁单价高、额小难凑
    #   relax=2 再松等级配比下限（level_share_lo）
    #   relax=3 最后松线路/站点数下限 + 单公司上限（line_count_min/company_cap）
    for relax in range(4):
        m = cp_model.CpModel()

        bus_cost = [_build_cost_unit(it, months, discount, agency_factor, prod_bus, prod_metro) for it in bus_items]
        metro_cost = [_build_cost_unit(it, months, discount, agency_factor, prod_bus, prod_metro) for it in metro_items]
        # 目标权重：以曝光（日均客流代理）为主，保证“预算↑ 曝光不降”的单调性；
        # 再叠加综合评分（含 POI/区县/廊道）作为二级偏好。
        bus_score = [int(round(it.get("exposure", it["score"]) * 100 + it["score"])) for it in bus_items]
        metro_score = [int(round(it.get("exposure", it["score"]) * 100 + it["score"])) for it in metro_items]
        bus_ub = [max(0, min(int(it["free_count"]), config.BUS_MAX_UNITS_PER_LINE)) for it in bus_items]
        metro_ub = [max(0, min(int(it["free_count"]), config.METRO_MAX_UNITS_PER_EXIT)) for it in metro_items]
        # 锁定项至少 1 且可分配
        bus_ub = [max(u, 1) if bus_items[i]["id"] in lock_bus and bus_items[i]["free_count"] >= 1 else u for i, u in enumerate(bus_ub)]
        metro_ub = [max(u, 1) if metro_items[i]["id"] in lock_metro and metro_items[i]["free_count"] >= 1 else u for i, u in enumerate(metro_ub)]

        bx = [m.NewIntVar(0, bus_ub[i], f"bx{i}") for i in range(nb)]
        bb = [m.NewBoolVar(f"bb{i}") for i in range(nb)]
        mx = [m.NewIntVar(0, metro_ub[i], f"mx{i}") for i in range(nm)]
        mb = [m.NewBoolVar(f"mb{i}") for i in range(nm)]

        for i in range(nb):
            if bus_ub[i] > 0:
                m.Add(bx[i] <= bus_ub[i] * bb[i])
                m.Add(bx[i] >= bb[i])
            else:
                m.Add(bx[i] == 0)
                m.Add(bb[i] == 0)
        for i in range(nm):
            if metro_ub[i] > 0:
                m.Add(mx[i] <= metro_ub[i] * mb[i])
                m.Add(mx[i] >= mb[i])
            else:
                m.Add(mx[i] == 0)
                m.Add(mb[i] == 0)

        # 预算（硬，绝不放松）
        m.Add(
            sum(bus_cost[i] * bx[i] for i in range(nb))
            + sum(metro_cost[i] * mx[i] for i in range(nm))
            <= budget_int
        )

        bus_units_sum = sum(bx)
        metro_units_sum = sum(mx)
        bus_lines_sum = sum(bb)

        # 地铁站点数 = 去重线路（每个被选中出入口的线路）计数，非出入口数。
        # 每个站点 s 的“被选”指示器 = OR(该站所有出入口的 mb)。
        metro_station_bool: List[Any] = []
        for sid in metro_station_ids:
            member_idx = [i for i in range(nm) if (metro_items[i].get("line_name") or metro_items[i]["id"]) == sid]
            if not member_idx:
                continue
            sb = m.NewBoolVar(f"ms_{sid[:8]}")
            m.Add(sb <= sum(mb[i] for i in member_idx))
            m.Add(sum(mb[i] for i in member_idx) <= len(member_idx) * sb)
            metro_station_bool.append(sb)
        metro_stations_sum = sum(metro_station_bool)

        # 线路/站点数量（relax>=3 松弛下限；上界始终保留）
        if nb > 0:
            lo_lines = config.BUS_MIN_LINES
            m.Add(bus_lines_sum <= config.BUS_MAX_LINES)
            if relax < 3 and len(bus_items) >= lo_lines and lo_lines > 0:
                m.Add(bus_lines_sum >= lo_lines)
        if nm > 0:
            lo_st = config.METRO_MIN_STATIONS
            m.Add(metro_stations_sum <= config.METRO_MAX_STATIONS)
            if relax < 3 and len(metro_station_bool) >= lo_st and lo_st > 0:
                m.Add(metro_stations_sum >= lo_st)

        # 媒体配比（按折后媒体净额口径 net = 单价 × units × months × discount）。
        # 整数缩放系数 100000（万元 × 1e5），避免 1000 缩放溢出。
        # relax>=1 时放松“下限”约束（media_mix_min），上界始终保留。
        MP = 100000
        if bus_items and metro_items:
            bus_net = sum(
                int(round(bus_items[i]["unit_price_wan"] * months * discount * MP)) * bx[i]
                for i in range(nb)
            )
            metro_net = sum(
                int(round(metro_items[i]["unit_price_wan"] * months * discount * MP)) * mx[i]
                for i in range(nm)
            )
            total_net = bus_net + metro_net
            bmin, bmax = skill_bus_mix
            mmin, mmax = skill_metro_mix
            # bus 上下界（bus 为主媒体）
            m.Add(bus_net * 100 <= int(round(bmax * 100)) * total_net)
            if relax < 1 and bmin > 0:
                m.Add(bus_net * 100 >= int(round(bmin * 100)) * total_net)
            # metro 上下界
            m.Add(metro_net * 100 <= int(round(mmax * 100)) * total_net)
            if relax < 1 and mmin > 0:
                m.Add(metro_net * 100 >= int(round(mmin * 100)) * total_net)

        # 等级配比（relax>=2 松下限，relax>=3 跳过）
        # 阈值：units 太小时下限约束无意义（契约：units 太小则禁用）
        MIN_UNITS_FOR_SHARE = 3
        if relax < 3:
            hi_bus = config.BUS_HIGH_SHARE_HI
            top_bus = [i for i in range(nb) if bus_items[i]["level"] in ("S", "A++")]
            top_metro = [i for i in range(nm) if metro_items[i]["level"] == "A++"]
            if top_bus and nb > 0:
                top_units = sum(bx[i] for i in top_bus)
                m.Add(top_units * 100 <= int(round(hi_bus * 100)) * bus_units_sum)
                if relax < 2:
                    # 下界在总 units >= threshold 时绑定；用布尔指示器
                    en = m.NewBoolVar("bus_share_en")
                    m.Add(bus_units_sum >= MIN_UNITS_FOR_SHARE).OnlyEnforceIf(en)
                    m.Add(bus_units_sum <= MIN_UNITS_FOR_SHARE - 1).OnlyEnforceIf(en.Not())
                    lo_bus = int(round(config.BUS_HIGH_SHARE_LO * 100))
                    m.Add(top_units * 100 >= lo_bus * bus_units_sum).OnlyEnforceIf(en)
            if top_metro and nm > 0:
                top_units = sum(mx[i] for i in top_metro)
                m.Add(top_units * 100 <= int(round(config.METRO_HIGH_SHARE_HI * 100)) * metro_units_sum)
                if relax < 2:
                    en_m = m.NewBoolVar("metro_share_hi_en")
                    m.Add(metro_units_sum >= MIN_UNITS_FOR_SHARE).OnlyEnforceIf(en_m)
                    m.Add(metro_units_sum <= MIN_UNITS_FOR_SHARE - 1).OnlyEnforceIf(en_m.Not())
                    lo_metro = int(round(config.METRO_HIGH_SHARE_LO * 100))
                    m.Add(top_units * 100 >= lo_metro * metro_units_sum).OnlyEnforceIf(en_m)

        # 单公司上限（bus）
        company_groups: Dict[str, List[int]] = {}
        for i in range(nb):
            company_groups.setdefault(bus_items[i].get("company") or "其他", []).append(i)
        if relax < 3:
            for idx in company_groups.values():
                m.Add(sum(bx[i] for i in idx) <= config.BUS_COMPANY_CAP)

        # 施工产能（硬）
        m.Add(bus_units_sum <= nights * config.BUS_PER_NIGHT)
        m.Add(metro_units_sum <= nights * config.METRO_PER_NIGHT)

        # 锁定 include
        for i in range(nb):
            if bus_items[i]["id"] in lock_bus:
                m.Add(bb[i] == 1)
                m.Add(bx[i] >= 1)
        for i in range(nm):
            if metro_items[i]["id"] in lock_metro:
                m.Add(mb[i] == 1)
                m.Add(mx[i] >= 1)

        # 媒体配比（软：目标不惩罚，仅作为约束在 relax==0 时按花费比例上下限）
        # 目标函数
        obj_terms = []
        for i in range(nb):
            obj_terms.append(bus_score[i] * bx[i])
            obj_terms.append(10 * bb[i])  # 覆盖 tie-break
        for i in range(nm):
            obj_terms.append(metro_score[i] * mx[i])
            obj_terms.append(10 * mb[i])

        # 区域覆盖 z[d]（软加分，鼓励分散）
        districts = {}
        for i in range(nb):
            districts.setdefault(bus_items[i]["district"], []).append(("b", i))
        for i in range(nm):
            districts.setdefault(metro_items[i]["district"], []).append(("m", i))
        for d, members in districts.items():
            if not members:
                continue
            zd = m.NewBoolVar(f"z")
            exprs = []
            for kind, i in members:
                exprs.append(bb[i] if kind == "b" else mb[i])
            m.Add(zd <= sum(exprs))
            obj_terms.append(50 * zd)

        m.Maximize(sum(obj_terms))

        # 确定性 warm-start：用贪心解作为 hint，保证超时时的 incumbent 稳定可复现
        _add_greedy_hint(m, bus_items, metro_items, budget_wan, months, discount, agency_factor,
                         lock_bus, lock_metro, nights, bx, bb, mx, mb, bus_ub, metro_ub,
                         prod_bus, prod_metro)

        solver = cp_model.CpSolver()
        solver.parameters.num_search_workers = config.CP_SAT_WORKERS
        solver.parameters.random_seed = config.CP_SAT_SEED
        solver.parameters.max_time_in_seconds = config.CP_SAT_TIME_LIMIT_MS / 1000.0

        t0 = time.time()
        status = solver.Solve(m)
        solve_ms = round((time.time() - t0) * 1000)

        if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            bus_units = {}
            metro_units = {}
            for i in range(nb):
                v = int(solver.Value(bx[i]))
                if v > 0:
                    bus_units[bus_items[i]["id"]] = v
            for i in range(nm):
                v = int(solver.Value(mx[i]))
                if v > 0:
                    metro_units[metro_items[i]["id"]] = v
            relaxed_tags = []
            if relax >= 1:
                relaxed_tags.append("media_mix_min")
            if relax >= 2:
                relaxed_tags.append("level_share_lo")
            if relax >= 3:
                relaxed_tags.append("line_count_min")
                relaxed_tags.append("company_cap")
            return {
                "status": "OPTIMAL" if status == cp_model.OPTIMAL else "FEASIBLE",
                "solver": "CP-SAT",
                "fallback_chain": [],
                "bus": bus_units,
                "metro": metro_units,
                "objective": _objective_value(bus_items, metro_items, bus_units, metro_units),
                "solve_ms": solve_ms,
                "relaxed": relaxed_tags,
            }
        # 不可行 → 下一级
    return None


# --------------------------------------------------------------------------- #
# HiGHS（scipy milp）兜底
# --------------------------------------------------------------------------- #
def _solve_highs(bus_items, metro_items, budget_wan, months, discount, agency_factor, locks, nights,
                 prod_bus=DEFAULT_PROD_BUS, prod_metro=DEFAULT_PROD_METRO):
    try:
        import numpy as np
        from scipy.optimize import milp, LinearConstraint, Bounds
    except Exception:
        return None

    nb = len(bus_items)
    nm = len(metro_items)
    n = nb + nm
    if n == 0:
        return None

    c = np.array([-it["score"] for it in bus_items] + [-it["score"] for it in metro_items], dtype=float)
    ub_list = [min(int(it["free_count"]), config.BUS_MAX_UNITS_PER_LINE) for it in bus_items] + \
              [min(int(it["free_count"]), config.METRO_MAX_UNITS_PER_EXIT) for it in metro_items]
    bounds = Bounds(np.zeros(n), np.array(ub_list, dtype=float))

    cost_row = [_build_cost_unit(it, months, discount, agency_factor, prod_bus, prod_metro) / SCALE for it in bus_items + metro_items]
    constraints = [LinearConstraint(np.array([cost_row]), -np.inf, budget_wan)]

    cap_bus = np.zeros(n); cap_bus[:nb] = 1.0
    constraints.append(LinearConstraint([cap_bus], -np.inf, nights * config.BUS_PER_NIGHT))
    cap_metro = np.zeros(n); cap_metro[nb:] = 1.0
    constraints.append(LinearConstraint([cap_metro], -np.inf, nights * config.METRO_PER_NIGHT))

    t0 = time.time()
    res = milp(c=c, integrality=np.ones(n), bounds=bounds, constraints=constraints)
    solve_ms = round((time.time() - t0) * 1000)

    if res.success and res.x is not None:
        bus_units = {bus_items[i]["id"]: int(round(res.x[i])) for i in range(nb) if int(round(res.x[i])) > 0}
        metro_units = {metro_items[i]["id"]: int(round(res.x[nb + i])) for i in range(nm) if int(round(res.x[nb + i])) > 0}
        return {
            "status": "FEASIBLE", "solver": "HiGHS", "fallback_chain": [],
            "bus": bus_units, "metro": metro_units,
            "objective": _objective_value(bus_items, metro_items, bus_units, metro_units),
            "solve_ms": solve_ms, "relaxed": [],
        }
    return None


# --------------------------------------------------------------------------- #
# 贪心（最后手段）
# --------------------------------------------------------------------------- #
def _solve_greedy(bus_items, metro_items, budget_wan, months, discount, agency_factor, locks, nights,
                  prod_bus=DEFAULT_PROD_BUS, prod_metro=DEFAULT_PROD_METRO):
    budget_left = budget_wan
    bus_units: Dict[str, int] = {}
    metro_units: Dict[str, int] = {}
    bus_count = 0
    metro_count = 0
    lock_include = set(locks.get("include", []))

    def _cu(it):
        return _build_cost_unit(it, months, discount, agency_factor, prod_bus, prod_metro) / SCALE

    all_items = [("bus", it) for it in bus_items] + [("metro", it) for it in metro_items]

    # 锁定优先
    for kind, it in all_items:
        if it["id"] in lock_include:
            c1 = _cu(it)
            if budget_left >= c1 and it["free_count"] >= 1:
                if kind == "bus":
                    bus_units[it["id"]] = 1; bus_count += 1
                else:
                    metro_units[it["id"]] = 1; metro_count += 1
                budget_left -= c1

    # 按 score / 成本效率
    def ratio(it):
        c1 = _cu(it)
        return it["score"] / c1 if c1 > 0 else 0.0

    remaining = [(k, it) for k, it in all_items if it["id"] not in lock_include]
    remaining.sort(key=lambda x: (-ratio(x[1]), x[1]["id"]))

    for kind, it in remaining:
        if kind == "bus" and bus_count >= config.BUS_MAX_LINES:
            continue
        if kind == "metro" and metro_count >= config.METRO_MAX_STATIONS:
            continue
        ub = min(int(it["free_count"]), config.BUS_MAX_UNITS_PER_LINE if kind == "bus" else config.METRO_MAX_UNITS_PER_EXIT)
        c1 = _cu(it)
        cap = (nights * config.BUS_PER_NIGHT - sum(bus_units.values())) if kind == "bus" else (nights * config.METRO_PER_NIGHT - sum(metro_units.values()))
        units = 0
        while units < ub and units < cap and budget_left >= c1 * (units + 1):
            units += 1
        if units > 0:
            if kind == "bus":
                bus_units[it["id"]] = units; bus_count += 1
            else:
                metro_units[it["id"]] = units; metro_count += 1
            budget_left -= c1 * units

    return {
        "status": "FEASIBLE" if (bus_units or metro_units) else "INFEASIBLE",
        "solver": "Greedy", "fallback_chain": [],
        "bus": bus_units, "metro": metro_units,
        "objective": _objective_value(bus_items, metro_items, bus_units, metro_units),
        "solve_ms": 0, "relaxed": [],
    }


__all__ = ["solve", "SCALE"]
