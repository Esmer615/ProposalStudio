#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""全组合矩阵检查：场馆 × 预算 × 媒体 × 档期。

用法：
    .venv\\Scripts\\python.exe scripts/matrix_check.py --budgets 100,200,500 --media bus,metro,both
"""
from __future__ import annotations

import argparse
import itertools
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--venues", default="lego_shanghai,disney_shanghai,haichang_shanghai")
    ap.add_argument("--budgets", default="100,200,500")
    ap.add_argument("--media", default="bus,metro,both")
    ap.add_argument("--dates", default="2027-07-01")
    ap.add_argument("--weeks", type=int, default=8)
    ap.add_argument("--customer-type", default="direct")
    args = ap.parse_args()

    try:
        from engine.orchestrator import generate_plan
    except Exception as exc:
        print(f"[FAIL] cannot import engine.orchestrator: {type(exc).__name__}: {exc}")
        return 2

    venues = [x.strip() for x in args.venues.split(",") if x.strip()]
    budgets = [float(x) for x in args.budgets.split(",") if x.strip()]
    media_sets = []
    for m in args.media.split(","):
        m = m.strip()
        if m == "both":
            media_sets.append(["bus", "metro"])
        elif m:
            media_sets.append([m])
    dates = [x.strip() for x in args.dates.split(",") if x.strip()]

    rows = []
    failures = 0
    for venue, budget, media, start in itertools.product(venues, budgets, media_sets, dates):
        req = {
            "industry": "乐园",
            "venue": venue,
            "budget_wan": budget,
            "media": media,
            "start_date": start,
            "weeks": args.weeks,
            "customer_type": args.customer_type,
            "locks": {"include": [], "exclude": []},
        }
        try:
            resp = generate_plan(req)
            plan = resp.get("plan", {})
            eff = resp.get("effects", {})
            quote = resp.get("quote", {})
            val = resp.get("validation", {})
            units = (plan.get("summary") or {}).get("bus_units", 0) + (plan.get("summary") or {}).get("metro_units", 0)
            reach = eff.get("reach", 0.0)
            total = quote.get("total_paid_wan", 0.0)
            ok = True
            reasons = []
            if not val.get("passed", False):
                ok = False
                reasons.append("validator")
            if not math.isfinite(float(reach)):
                ok = False
                reasons.append("NaN reach")
            if float(total) > float(budget) + 1e-6:
                ok = False
                reasons.append("over budget")
            if not (plan.get("bus") or plan.get("metro")):
                ok = False
                reasons.append("empty plan")
            if not ok:
                failures += 1
            rows.append((venue, int(budget), "+".join(media), start, units, round(float(total), 2), f"{float(reach):.1%}", "OK" if ok else "FAIL:" + ",".join(reasons), resp.get("meta", {}).get("solve_ms")))
        except Exception as exc:
            failures += 1
            rows.append((venue, int(budget), "+".join(media), start, "-", "-", "-", f"EXC:{type(exc).__name__}:{exc}", "-"))

    print(f"{'venue':<18} {'budget':>6} {'media':<11} {'start':<12} {'units':>5} {'paid':>8} {'reach':>7} {'status':<20} {'ms':>5}")
    for r in rows:
        print(f"{r[0]:<18} {r[1]:>6} {r[2]:<11} {r[3]:<12} {str(r[4]):>5} {str(r[5]):>8} {str(r[6]):>7} {str(r[7]):<20} {str(r[8]):>5}")
    print(f"\n[{'PASS' if failures == 0 else 'FAIL'}] {len(rows) - failures}/{len(rows)} combinations OK")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
