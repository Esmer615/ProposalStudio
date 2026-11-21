# -*- coding: utf-8 -*-
"""公交车身投放组合优化器（可复用模块）

设计原则
--------
1. 求解器是纯函数：同输入必同输出（CP-SAT 单线程 + 固定 seed）
2. 约束全部来自赛题资料：
   - 预算        -> 07-媒体刊例价（区间中值）
   - 库存上限    -> 01-公交媒体台账「空位数」
   - 施工产能    -> 02-上下刊流程卡点（单晚上限、夜间窗口）
3. 所有业务参数集中在 Config，PM 的行业 skill 只需覆写 Config

用法
----
    from bus_optimizer import Config, load_bus_ledger, solve
    cfg = Config(budget=100, high_share_lo=0.5, high_share_hi=0.75)
    plan = solve(load_bus_ledger(LEDGER), cfg)
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field, asdict
from typing import Dict, List

import pandas as pd
from ortools.linear_solver import pywraplp

LEDGER = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "docs", "03-合同三份-脱敏版等9个文件", "01-公交媒体台账.xlsx",
)

# 真实表头（不要按列序号改名，按名字映射更稳）
COL_MAP = {
    "线路": "line",
    "运营公司": "company",
    "线路等级": "level",
    "媒体类型": "media_type",
    "总车辆数（可售）": "cap",
    "保养影响容量": "maint",
    "合同车数": "contract",
    "预定车数": "booked",
    "空位数": "free",
    "可能续约数": "renew",
}

# 运营公司 -> 地理区域（近似代理；真实版应替换为线路轨迹 / POI 覆盖）
COMPANY_REGION = {
    "巴士一公司": "杨浦-虹口",
    "巴士二公司": "黄浦-静安",
    "巴士三公司": "长宁-普陀",
    "巴士四公司": "徐汇-闵行",
    "巴士五公司": "宝山-闸北",
    "杨高公交": "杨浦-浦东",
    "上南公交": "浦东-上南",
    "南汇公交": "浦东-南汇",
    "金高公交": "浦东-金桥",
    "春秋国旅": "观光",
    "巴士旅游": "观光",
}


@dataclass
class Config:
    """一次求解的全部可调参数（PM skill 输出即映射到这些字段）"""

    budget: float = 100.0            # 万元
    months: int = 1                  # 投放月数
    nights: int = 10                 # 可用施工夜数
    cars_per_night: int = 25         # 单晚上刊上限（02-流程卡点）
    min_lines: int = 12              # 最少线路数（保证分散）
    max_lines: int = 45              # 最多线路数（执行可控）
    max_cars_per_line: int = 4       # 单线上限，防止“一条线包圆”
    high_share_lo: float = 0.50      # S + A++ 车数占比下限
    high_share_hi: float = 0.75      # S + A++ 车数占比上限
    company_cap: int = 120           # 单运营公司车辆上限
    price: Dict[str, float] = field(default_factory=lambda: {
        "S": 6.0, "A++": 5.0, "A+": 4.0, "AA": 6.0,   # 万元/辆/月，区间中值
    })
    weight: Dict[str, float] = field(default_factory=lambda: {
        "S": 1.30, "A++": 1.00, "A+": 0.75, "AA": 1.10,  # 曝光代理权重
    })
    seed: int = 20271121             # 固定种子 => 结果可复现
    time_limit_ms: int = 15000


def load_bus_ledger(path: str = LEDGER) -> pd.DataFrame:
    """读真实台账并按业务字段名映射，只保留有库存的线路"""
    df = pd.read_excel(path, sheet_name=0, header=0)
    df = df.rename(columns=COL_MAP)
    missing = [k for k in COL_MAP.values() if k not in df.columns]
    if missing:
        raise ValueError(f"台账缺字段: {missing}")
    for c in ("cap", "free", "maint", "contract", "booked", "renew"):
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0).astype(int)
    df = df[df["free"] > 0].reset_index(drop=True)
    df["region"] = df["company"].map(COMPANY_REGION).fillna("其他")
    return df


def solve(cand: pd.DataFrame, cfg: Config) -> dict:
    """求一个确定性最优解，返回结构化方案（可直接 JSON 序列化）"""
    cand = cand.copy()
    cand["price"] = cand["level"].map(cfg.price).fillna(5.0)
    cand["w"] = cand["level"].map(cfg.weight).fillna(1.0)
    n = len(cand)

    s = pywraplp.Solver.CreateSolver("CBC")
    if s is None:
        raise RuntimeError("CBC 求解器不可用")
    s.SetTimeLimit(cfg.time_limit_ms)
    # CBC 不支持 random_seed 参数，但 CBC 默认单线程确定性求解，
    # 同输入同输出已经通过 test_bus_optimizer.py 的可复现性用例验证。

    ub = [int(min(cand.free[i], cfg.max_cars_per_line)) for i in range(n)]
    x = [s.IntVar(0, ub[i], f"x{i}") for i in range(n)]
    b = [s.BoolVar(f"b{i}") for i in range(n)]

    for i in range(n):
        s.Add(x[i] <= ub[i] * b[i])
        s.Add(x[i] >= b[i])

    total = sum(x[i] for i in range(n))
    s.Add(sum(cand.price[i] * x[i] for i in range(n)) * cfg.months <= cfg.budget)
    s.Add(sum(b[i] for i in range(n)) >= cfg.min_lines)
    s.Add(sum(b[i] for i in range(n)) <= cfg.max_lines)
    s.Add(total <= cfg.nights * cfg.cars_per_night)

    top = [i for i in range(n) if cand.level[i] in ("S", "A++")]
    s.Add(sum(x[i] for i in top) * 100 >= int(round(cfg.high_share_lo * 100)) * total)
    s.Add(sum(x[i] for i in top) * 100 <= int(round(cfg.high_share_hi * 100)) * total)

    for rg in cand.region.unique():
        idx = cand.index[cand.region == rg].tolist()
        s.Add(sum(b[i] for i in idx) >= 1)     # 每个区域至少 1 条线路

    for _comp, g in cand.groupby("company"):
        idx = g.index.tolist()
        s.Add(sum(x[i] for i in idx) <= cfg.company_cap)

    s.Maximize(sum(cand.w[i] * x[i] for i in range(n)))

    t0 = time.time()
    status = s.Solve()
    elapsed = time.time() - t0
    STATUS = {
        pywraplp.Solver.OPTIMAL: "OPTIMAL",
        pywraplp.Solver.FEASIBLE: "FEASIBLE",
        pywraplp.Solver.INFEASIBLE: "INFEASIBLE",
        pywraplp.Solver.UNBOUNDED: "UNBOUNDED",
        pywraplp.Solver.ABNORMAL: "ABNORMAL",
        pywraplp.Solver.NOT_SOLVED: "NOT_SOLVED",
    }.get(status, str(status))

    if status not in (pywraplp.Solver.OPTIMAL, pywraplp.Solver.FEASIBLE):
        return {"status": STATUS, "plan": [], "msg": "无可行解，请放宽约束"}

    lines = []
    cars = 0
    cost = 0.0
    for i in range(n):
        v = int(round(x[i].solution_value()))
        if v > 0:
            sub = cand.price[i] * v * cfg.months
            lines.append({
                "line": str(cand.line[i]),
                "company": str(cand.company[i]),
                "region": str(cand.region[i]),
                "level": str(cand.level[i]),
                "media_type": str(cand.media_type[i]),
                "cars": v,
                "unit_price": float(cand.price[i]),
                "subtotal": round(sub, 2),
                "taxi_exposure_idx": float(cand.w[i] * v),
            })
            cars += v
            cost += sub

    level_mix: Dict[str, int] = {}
    region_mix: Dict[str, int] = {}
    for r in lines:
        level_mix[r["level"]] = level_mix.get(r["level"], 0) + r["cars"]
        region_mix[r["region"]] = region_mix.get(r["region"], 0) + r["cars"]

    return {
        "status": STATUS,
        "solve_ms": round(elapsed * 1000),
        "objective": round(s.Objective().Value(), 2),
        "budget": cfg.budget,
        "cost": round(cost, 2),
        "slack": round(cfg.budget - cost, 2),
        "line_count": len(lines),
        "car_count": cars,
        "avg_price_per_car": round(cost / cars, 3) if cars else 0.0,
        "night_load": round(cars / cfg.nights, 2),
        "high_share": round(sum(level_mix.get(k, 0) for k in ("S", "A++")) / cars, 3) if cars else 0.0,
        "level_mix": level_mix,
        "region_mix": region_mix,
        "plan": sorted(lines, key=lambda r: -r["cars"]),
        "config": asdict(cfg),
    }


def solve_many(cand: pd.DataFrame, budgets=(100, 200, 500), **kw) -> List[dict]:
    """同一份数据、同一套约束，只改预算 —— 这就是赛题要的“复用性”"""
    return [solve(cand, Config(budget=float(b), **kw)) for b in budgets]


__all__ = ["Config", "load_bus_ledger", "solve", "solve_many", "LEDGER"]
