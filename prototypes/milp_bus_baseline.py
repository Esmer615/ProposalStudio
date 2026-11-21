# -*- coding: utf-8 -*-
"""原型：公交车身投放组合 MILP（真实台账 + 刊例区间中值）"""
import pandas as pd, numpy as np, time, json
from ortools.linear_solver import pywraplp

p = "docs/03-合同三份-脱敏版等9个文件/01-公交媒体台账.xlsx"
df = pd.read_excel(p, sheet_name=0, header=0)
df.columns = ["line", "company", "level", "media_type", "cap",
              "maint", "contract", "booked", "free", "renew"]
for c in ["cap", "free"]:
    df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0).astype(int)

# 刊例（万元/辆/月，区间中值）—— 07-媒体刊例价
PRICE = {"S": 6.0, "A++": 5.0, "A+": 4.0, "AA": 6.0}
# 等级权重 = 单车上刊曝光相对系数（示例，可被 PM skill 覆盖）
WEIGHT = {"S": 1.30, "A++": 1.00, "A+": 0.75, "AA": 1.10}

cand = df[df["free"] > 0].copy()
cand["price"] = cand["level"].map(PRICE).fillna(5.0)
cand["w"] = cand["level"].map(WEIGHT).fillna(1.0)
cand = cand.reset_index(drop=True)

BUDGET = 100.0        # 万元
MONTHS = 1
NIGHTS = 10           # 可用施工夜
CARS_PER_NIGHT = 25   # 单晚上刊上限

n = len(cand)
s = pywraplp.Solver.CreateSolver("CBC")
s.SetTimeLimit(8000)
x = [s.IntVar(0, int(cand.free[i]), "x%d" % i) for i in range(n)]
b = [s.BoolVar("b%d" % i) for i in range(n)]

for i in range(n):
    s.Add(x[i] <= int(cand.free[i]) * b[i])
    s.Add(x[i] >= b[i])          # 选中则至少 1 辆

s.Add(sum(cand.price[i] * x[i] * MONTHS for i in range(n)) <= BUDGET)
s.Add(sum(b) <= 45)                                              # 线路数上限
s.Add(sum(x[i] for i in range(n)) <= NIGHTS * CARS_PER_NIGHT)     # 施工产能

top = [i for i in range(n) if cand.level[i] in ("S", "A++")]
s.Add(sum(x[i] for i in top) * 2 >= sum(x[i] for i in range(n)))              # ≥50%
s.Add(sum(x[i] for i in top) * 2 <= sum(x[i] for i in range(n)) * 3)         # ≤75%

for comp, g in cand.groupby("company"):
    idx = g.index.tolist()
    s.Add(sum(x[i] for i in idx) <= 120)                          # 单公司分散

s.Maximize(sum(cand.w[i] * x[i] for i in range(n)))

t0 = time.time()
st = s.Solve()
dt = time.time() - t0

picked, tot_cars, tot_cost, tot_w = [], 0, 0.0, 0.0
for i in range(n):
    v = int(round(x[i].solution_value()))
    if v > 0:
        picked.append({"line": str(cand.line[i]), "level": cand.level[i],
                       "cars": v, "price": cand.price[i],
                       "subtotal": round(cand.price[i] * v * MONTHS, 2)})
        tot_cars += v
        tot_cost += cand.price[i] * v * MONTHS
        tot_w += cand.w[i] * v

print("status=%s obj=%.2f solve=%.0fms" % (st, s.Objective().Value(), dt * 1000))
print("lines=%d cars=%d cost=%.2f万 (budget %.0f) slack=%.2f万"
      % (len(picked), tot_cars, tot_cost, BUDGET, BUDGET - tot_cost))
lv = {}
for r in picked:
    lv[r["level"]] = lv.get(r["level"], 0) + r["cars"]
print("level mix (cars):", lv)
print("night load: %.1f cars/night (cap %d)" % (tot_cars / NIGHTS, CARS_PER_NIGHT))
print("top10:", json.dumps(sorted(picked, key=lambda r: -r["cars"])[:10], ensure_ascii=False))
print("avg price/car: %.3f 万" % (tot_cost / tot_cars))
