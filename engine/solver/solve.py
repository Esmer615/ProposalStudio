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

# 三种确定性优化策略参数（在同一 CP-SAT 凹边际递减模型上求解差异化组合）
STRATEGY_PROFILES: Dict[str, Dict[str, Any]] = {
    "balanced": {
        "w_exp": 0.55,
        "w_qual": 0.45,
        "w_div_line": 120,
        "w_div_dist": 180,
        "bus_max_units": 3,
        "metro_max_units": 2,
        "bus_high_lo": config.BUS_HIGH_SHARE_LO,
        "bus_mix_delta": 0.0,
        "metro_mix_delta": 0.0,
        "zone_boost": 1.0,
        "xinyun_bonus": 160,
    },
    "max_reach": {
        "w_exp": 0.74,
        "w_qual": 0.18,
        "w_div_line": 280,
        "w_div_dist": 360,
        "bus_max_units": 2,
        "metro_max_units": 1,
        "bus_high_lo": 0.25,
        "bus_mix_delta": 0.12,
        "metro_mix_delta": -0.12,
        "zone_boost": 0.85,
        "xinyun_bonus": 90,
    },
    "precision": {
        "w_exp": 0.24,
        "w_qual": 0.76,
        "w_div_line": 50,
        "w_div_dist": 80,
        "bus_max_units": 4,
        "metro_max_units": 2,
        "bus_high_lo": 0.52,
        "bus_mix_delta": -0.10,
        "metro_mix_delta": 0.12,
        "zone_boost": 1.45,
        "xinyun_bonus": 340,
    },
}


def _strategy_profile(mode: str) -> Dict[str, Any]:
    return STRATEGY_PROFILES.get(str(mode or "balanced").lower(), STRATEGY_PROFILES["balanced"])


def _adjust_mix_bounds(bounds: Tuple[float, float], delta: float) -> Tuple[float, float]:
    lo, hi = bounds
    if delta == 0.0:
        return (lo, hi)
    new_lo = max(0.0, min(0.85, lo + delta))
    new_hi = max(new_lo + 0.10, min(1.0, hi + delta))
    return (round(new_lo, 2), round(new_hi, 2))


def _slot_marginal_value(item: Dict[str, Any], slot_k: int, prof: Dict[str, Any]) -> int:
    """计算单个点位第 slot_k 个新增投放单元的边际目标分（精确建模 SLOT_DECAY 边际递减）。

    将「有效日均曝光」与「空间/POI/廊道综合质量分」归一化到同一 [0, 1000] 尺度，
    彻底解决旧版线性模型中 exposure*100 淹没 score 且忽略同线重复递减的问题。
    """
    view_rate = config.VIEW_RATE_BUS if item["kind"] == "bus" else config.VIEW_RATE_METRO
    raw_exp = float(item.get("exposure") or 0.0) * view_rate
    # 归一化曝光分（以地铁 A++ 有效日曝光 45,000 为基准 1000 分）
    exp_norm = min(1000.0, (raw_exp / 45000.0) * 1000.0)
    # 综合质量分（0..1000），在 precision 策略下强化空间亲和与 POI 浓度
    base_score = float(item.get("score") or 50.0) * 10.0
    sb = item.get("score_breakdown") or {}
    zone_val = float(sb.get("zone") or 0.5) * 1000.0
    qual_norm = min(1000.0, base_score * 0.65 + zone_val * 0.35 * prof["zone_boost"])
    decay = config.SLOT_DECAY ** slot_k
    val = (prof["w_exp"] * exp_norm + prof["w_qual"] * qual_norm) * decay
    # 若该线路/站点被新云大数据实测命中（目标地点周边），首车/首口加策略亲和分
    if slot_k == 0 and item.get("xinyun_matched"):
        val += prof["xinyun_bonus"]
    return max(1, int(round(val)))


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
    strategy_mode: str = "balanced",
) -> Dict[str, Any]:
    agency_factor = config.AGENCY_FEE_RATE if customer_type == "4a" else 0.0
    _validate_locks(locks, bus_items, metro_items)

    excl = set(locks.get("exclude", []))
    bus_items = [it for it in bus_items if it["id"] not in excl]
    metro_items = [it for it in metro_items if it["id"] not in excl]

    result = _solve_cpsat(bus_items, metro_items, budget_wan, months, discount, agency_factor, locks, nights,
                          skill_bus_mix, skill_metro_mix, prod_bus, prod_metro, strategy_mode=strategy_mode)
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
# CP-SAT（凹边际递减槽位建模 + 多策略目标）
# --------------------------------------------------------------------------- #
def _solve_cpsat(bus_items, metro_items, budget_wan, months, discount, agency_factor, locks, nights,
                 skill_bus_mix, skill_metro_mix, prod_bus=DEFAULT_PROD_BUS, prod_metro=DEFAULT_PROD_METRO,
                 strategy_mode: str = "balanced"):
    try:
        from ortools.sat.python import cp_model
    except Exception:
        return None

    prof = _strategy_profile(strategy_mode)
    eff_bus_mix = _adjust_mix_bounds(skill_bus_mix, prof["bus_mix_delta"])
    eff_metro_mix = _adjust_mix_bounds(skill_metro_mix, prof["metro_mix_delta"])

    budget_int = int(round(budget_wan * SCALE))
    nb = len(bus_items)
    nm = len(metro_items)

    lock_include = set(locks.get("include", []))
    lock_bus = set(lid for lid in lock_include if any(it["id"] == lid for it in bus_items))
    lock_metro = set(lid for lid in lock_include if any(it["id"] == lid for it in metro_items))

    # 地铁按“站点”聚合（每个候选是一个出入口；最小/最大站点数 = 去重线路数）
    metro_station_ids = sorted({it.get("line_name") or it["id"] for it in metro_items})

    # 逐级松弛顺序（文档化，绝不放松预算/库存）：
    #   relax=0 全约束（含策略化配比与单线上限）
    #   relax=1 放松媒体配比下限（media_mix_min）——最先松，因地铁单价高、额小难凑
    #   relax=2 再松等级配比下限（level_share_lo）与策略单线紧上限
    #   relax=3 最后松线路/站点数下限 + 单公司上限（line_count_min/company_cap）
    for relax in range(4):
        m = cp_model.CpModel()

        bus_cost = [_build_cost_unit(it, months, discount, agency_factor, prod_bus, prod_metro) for it in bus_items]
        metro_cost = [_build_cost_unit(it, months, discount, agency_factor, prod_bus, prod_metro) for it in metro_items]

        max_bus_u = prof["bus_max_units"] if relax < 2 else config.BUS_MAX_UNITS_PER_LINE
        max_metro_u = prof["metro_max_units"] if relax < 2 else config.METRO_MAX_UNITS_PER_EXIT
        bus_ub = [max(0, min(int(it["free_count"]), max_bus_u)) for it in bus_items]
        metro_ub = [max(0, min(int(it["free_count"]), max_metro_u)) for it in metro_items]
        # 锁定项至少 1 且可分配
        bus_ub = [max(u, 1) if bus_items[i]["id"] in lock_bus and bus_items[i]["free_count"] >= 1 else u for i, u in enumerate(bus_ub)]
        metro_ub = [max(u, 1) if metro_items[i]["id"] in lock_metro and metro_items[i]["free_count"] >= 1 else u for i, u in enumerate(metro_ub)]

        bx = [m.NewIntVar(0, bus_ub[i], f"bx{i}") for i in range(nb)]
        bb = [m.NewBoolVar(f"bb{i}") for i in range(nb)]
        mx = [m.NewIntVar(0, metro_ub[i], f"mx{i}") for i in range(nm)]
        mb = [m.NewBoolVar(f"mb{i}") for i in range(nm)]

        # 凹边际递减槽位二元变量：s[i][k] 表示第 k+1 个投放单元是否启用，满足 s[k] >= s[k+1]
        b_slots: List[List[Any]] = []
        for i in range(nb):
            if bus_ub[i] > 0:
                slots = [m.NewBoolVar(f"bs_{i}_{k}") for k in range(bus_ub[i])]
                for k in range(len(slots) - 1):
                    m.Add(slots[k] >= slots[k + 1])
                m.Add(bx[i] == sum(slots))
                m.Add(bb[i] == slots[0])
                b_slots.append(slots)
            else:
                m.Add(bx[i] == 0)
                m.Add(bb[i] == 0)
                b_slots.append([])

        m_slots: List[List[Any]] = []
        for i in range(nm):
            if metro_ub[i] > 0:
                slots = [m.NewBoolVar(f"ms_{i}_{k}") for k in range(metro_ub[i])]
                for k in range(len(slots) - 1):
                    m.Add(slots[k] >= slots[k + 1])
                m.Add(mx[i] == sum(slots))
                m.Add(mb[i] == slots[0])
                m_slots.append(slots)
            else:
                m.Add(mx[i] == 0)
                m.Add(mb[i] == 0)
                m_slots.append([])

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
        metro_station_bool: List[Any] = []
        for sid in metro_station_ids:
            member_idx = [i for i in range(nm) if (metro_items[i].get("line_name") or metro_items[i]["id"]) == sid]
            if not member_idx:
                continue
            sb = m.NewBoolVar(f"mst_{sid[:8]}")
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

        # 媒体配比（按折后媒体净额口径）
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
            bmin, bmax = eff_bus_mix if relax == 0 else skill_bus_mix
            mmin, mmax = eff_metro_mix if relax == 0 else skill_metro_mix
            m.Add(bus_net * 100 <= int(round(bmax * 100)) * total_net)
            if relax < 1 and bmin > 0:
                m.Add(bus_net * 100 >= int(round(bmin * 100)) * total_net)
            m.Add(metro_net * 100 <= int(round(mmax * 100)) * total_net)
            if relax < 1 and mmin > 0:
                m.Add(metro_net * 100 >= int(round(mmin * 100)) * total_net)

        # 等级配比（relax>=2 松下限，relax>=3 跳过）
        MIN_UNITS_FOR_SHARE = 3
        if relax < 3:
            hi_bus = config.BUS_HIGH_SHARE_HI
            top_bus = [i for i in range(nb) if bus_items[i]["level"] in ("S", "A++")]
            top_metro = [i for i in range(nm) if metro_items[i]["level"] == "A++"]
            if top_bus and nb > 0:
                top_units = sum(bx[i] for i in top_bus)
                m.Add(top_units * 100 <= int(round(hi_bus * 100)) * bus_units_sum)
                if relax < 2:
                    en = m.NewBoolVar("bus_share_en")
                    m.Add(bus_units_sum >= MIN_UNITS_FOR_SHARE).OnlyEnforceIf(en)
                    m.Add(bus_units_sum <= MIN_UNITS_FOR_SHARE - 1).OnlyEnforceIf(en.Not())
                    lo_bus = int(round(prof["bus_high_lo"] * 100))
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

        # 目标函数：精确凹边际递减槽位收益 + 线路多样性 + 区域覆盖多样性
        obj_terms = []
        for i in range(nb):
            for k, slot_var in enumerate(b_slots[i]):
                obj_terms.append(_slot_marginal_value(bus_items[i], k, prof) * slot_var)
            obj_terms.append(prof["w_div_line"] * bb[i])
        for i in range(nm):
            for k, slot_var in enumerate(m_slots[i]):
                obj_terms.append(_slot_marginal_value(metro_items[i], k, prof) * slot_var)
            obj_terms.append(prof["w_div_line"] * mb[i])

        # 区域覆盖 z[d]（软加分，鼓励跨区覆盖）
        districts: Dict[str, List[Tuple[str, int]]] = {}
        for i in range(nb):
            districts.setdefault(bus_items[i]["district"], []).append(("b", i))
        for i in range(nm):
            districts.setdefault(metro_items[i]["district"], []).append(("m", i))
        for idx_d, (_d, members) in enumerate(districts.items()):
            if not members:
                continue
            zd = m.NewBoolVar(f"z_{idx_d}")
            exprs = [bb[i] if kind == "b" else mb[i] for kind, i in members]
            m.Add(zd <= sum(exprs))
            obj_terms.append(prof["w_div_dist"] * zd)

        m.Maximize(sum(obj_terms))

        # 确定性 warm-start
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
                "strategy_mode": strategy_mode,
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
