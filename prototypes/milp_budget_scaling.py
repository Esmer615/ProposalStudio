# -*- coding: utf-8 -*-
"""原型2：加入覆盖/分散约束 + 边际成本优先的预算缩放开关系数"""
import pandas as pd, numpy as np, time, json
from ortools.linear_solver import pywraplp

p = "docs/03-合同三份-脱敏版等9个文件/01-公交媒体台账.xlsx"
df = pd.read_excel(p, sheet_name=0, header=0)
df.columns = ["line", "company", "level", "media_type", "cap",
              "maint", "contract", "booked", "free", "renew"]
for c in ["cap", "free"]:
    df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0).astype(int)

PRICE = {"S": 6.0, "A++": 5.0, "A+": 4.0, "AA": 6.0}
WEIGHT = {"S": 1.30, "A++": 1.00, "A+": 0.75, "AA": 1.10}

cand = df[df["free"] > 0].copy()
cand["price"] = cand["level"].map(PRICE).fillna(5.0)
cand["w"] = cand["level"].map(WEIGHT).fillna(1.0)
cand = cand.reset_index(drop=True)
n = len(cand)

# 运营公司 ≈ 地理区域代理（一~五公司/杨高/上南/南汇/金高）
COMPANY_REGION = {
    "巴士一公司": "杨浦-虹口", "巴士二公司": "黄浦-静安", "巴士三公司": "长宁-普陀",
    "巴士四公司": "徐汇-闵行", "巴士五公司": "宝山-闸北", "杨高公交": "杨浦-浦东",
    "上南公交": "浦东-上南", "南汇公交": "浦东-南汇", "金高公交": "浦东-金桥",
    "春秋国旅": "观光", "巴士旅游": "观光",
}
cand["region"] = cand["company"].map(COMPANY_REGION).fillna("其他")

def solve(budget, min_lines=12, max_per_line=4, n_nights=10, cars_per_night=25,
          high_share_lo=0.50, high_share_hi=0.75):
    s = pywraplp.Solver.CreateSolver("CBC")
    s.SetTimeLimit(15000)
    x = [s.IntVar(0, int(min(cand.free[i], max_per_line)), "x%d" % i) for i in range(n)]
    b = [s.BoolVar("b%d" % i) for i in range(n)]
    for i in range(n):
        s.Add(x[i] <= int(min(cand.free[i], max_per_line)) * b[i])
        s.Add(x[i] >= b[i])
    s.Add(sum(cand.price[i] * x[i] for i in range(n)) <= budget)
    s.Add(sum(b) >= min_lines)
    s.Add(sum(b) <= 45)
    s.Add(sum(x[i] for i in range(n)) <= n_nights * cars_per_night)
    top = [i for i in range(n) if cand.level[i] in ("S", "A++")]
    tot = sum(x[i] for i in range(n))
    s.Add(sum(x[i] for i in top) * 100 >= int(high_share_lo * 100) * tot)
    s.Add(sum(x[i] for i in top) * 100 <= int(high_share_hi * 100) * tot)
    # 区域覆盖：每个有候选线路的区域至少 1 条线
    regions = cand.region.unique().tolist()
    for rg in regions:
        idx = cand.index[cand.region == rg].tolist()
        if not idx:
            continue
        s.Add(sum(b[i] for i in idx) >= 1)
    s.Maximize(sum(cand.w[i] * x[i] for i in range(n)))
    t0 = time.time(); st = s.Solve(); dt = time.time() - t0
    picked, cars, cost = [], 0, 0.0
    for i in range(n):
        v = int(round(x[i].solution_value()))
        if v > 0:
            picked.append((str(cand.line[i]), cand.level[i], v, cand.price[i], cand.region[i]))
            cars += v; cost += cand.price[i] * v
    return st, s.Objective().Value(), dt, picked, cars, cost

print("budget | status | obj  | lines | cars | cost  | slack | ms")
for B in (100, 200, 500):
    st, obj, dt, picked, cars, cost = solve(B)
    print("%6d | %6d | %5.2f | %5d | %4d | %5.1f | %5.1f | %.0f"
          % (B, st, obj, len(picked), cars, cost, B - cost, dt * 1000))

st, obj, dt, picked, cars, cost = solve(100)
lv = {}
for r in picked:
    lv[r[1]] = lv.get(r[1], 0) + r[2]
rg = {}
for r in picked:
    rg[r[4]] = rg.get(r[4], 0) + r[2]
print("\n[100万] level mix:", lv)
print("[100万] region mix:", rg)
print("[100万] lines:", json.dumps(
    sorted([{"line": r[0], "lv": r[1], "cars": r[2], "region": r[4]} for r in picked],
           key=lambda d: -d["cars"])[:15], ensure_ascii=False))