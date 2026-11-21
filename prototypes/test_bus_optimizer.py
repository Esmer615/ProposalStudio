# -*- coding: utf-8 -*-
"""验证 bus_optimizer：三个预算 + 可复现性 + 约束自检"""
import json
import sys

from bus_optimizer import Config, load_bus_ledger, solve, solve_many

cand = load_bus_ledger()
print(f"候选线路: {len(cand)}  可用车辆总量: {cand['free'].sum()}\n")

rows = solve_many(cand, budgets=(100, 200, 500))
print(f"{'预算':>6} {'状态':>9} {'线路':>5} {'车辆':>5} {'花费':>7} {'余量':>6} "
      f"{'高等级':>7} {'夜负荷':>7} {'耗时':>8}")
for r in rows:
    if r["status"] not in ("OPTIMAL", "FEASIBLE"):
        print(f"{r.get('budget', 0):>6} {r['status']:>9}  {r.get('msg','')}")
        continue
    print(f"{r['budget']:>6.0f} {r['status']:>9} {r['line_count']:>5} {r['car_count']:>5} "
          f"{r['cost']:>7.1f} {r['slack']:>6.1f} {r['high_share']:>6.0%} "
          f"{r['night_load']:>7.1f} {r['solve_ms']:>6}ms")

# ---- 约束自检 ----
print("\n--- 约束自检 (预算 200 万) ---")
r = solve(cand, Config(budget=200))
checks = [
    ("不超预算", r["cost"] <= 200 + 1e-6, f"{r['cost']:.2f} <= 200"),
    ("线路数≥12", r["line_count"] >= 12, str(r["line_count"])),
    ("线路数≤45", r["line_count"] <= 45, str(r["line_count"])),
    ("施工排得下", r["car_count"] <= 10 * 25, f"{r['car_count']} <= 250"),
    ("高等级占比50%-75%", 0.50 - 1e-6 <= r["high_share"] <= 0.75 + 1e-6, f"{r['high_share']:.1%}"),
    ("单线上限≤4辆", all(p["cars"] <= 4 for p in r["plan"]),
     str(max(p["cars"] for p in r["plan"]))),
    ("区域全覆盖", len(r["region_mix"]) == cand["region"].nunique(),
     f"{len(r['region_mix'])}/{cand['region'].nunique()}"),
]
ok = True
for name, passed, detail in checks:
    print(f"  [{'PASS' if passed else 'FAIL'}] {name}: {detail}")
    ok &= passed

# ---- 库存自检：不能超过台账空位数 ----
free_map = dict(zip(cand["line"].astype(str), cand["free"]))
bad = [p for p in r["plan"] if p["cars"] > free_map.get(p["line"], 0)]
print(f"  [{'PASS' if not bad else 'FAIL'}] 不超库存: {len(bad)} 条越界")
ok &= not bad

# ---- 可复现性：同输入跑两次应完全一致 ----
a = solve(cand, Config(budget=200))
b = solve(cand, Config(budget=200))
same = [(p["line"], p["cars"]) for p in a["plan"]] == [(p["line"], p["cars"]) for p in b["plan"]]
print(f"  [{'PASS' if same else 'FAIL'}] 可复现（同输入同输出）")
ok &= same

print("\n总判定:", "全部通过 ✅" if ok else "有失败项 ❌")

print("\n--- 100 万方案明细（前 15 条）---")
print(json.dumps(rows[0]["plan"][:15], ensure_ascii=False, indent=1))
sys.exit(0 if ok else 1)