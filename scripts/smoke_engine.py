#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""引擎冒烟：默认场景跑通并打印关键结果。

用法：
    .venv\\Scripts\\python.exe scripts/smoke_engine.py [--venue lego_shanghai] [--budget 500]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--venue", default="lego_shanghai")
    ap.add_argument("--budget", type=float, default=500)
    ap.add_argument("--media", default="bus,metro")
    ap.add_argument("--start", default="2027-07-01")
    ap.add_argument("--weeks", type=int, default=8)
    ap.add_argument("--customer-type", default="direct")
    ap.add_argument("--dump", default="")
    args = ap.parse_args()

    from engine.orchestrator import generate_plan

    req = {
        "industry": "乐园",
        "venue": args.venue,
        "budget_wan": args.budget,
        "media": [m.strip() for m in args.media.split(",") if m.strip()],
        "start_date": args.start,
        "weeks": args.weeks,
        "customer_type": args.customer_type,
        "locks": {"include": [], "exclude": []},
    }
    t = time.time()
    resp = generate_plan(req)
    elapsed = round((time.time() - t) * 1000)
    if args.dump:
        Path(args.dump).write_text(json.dumps(resp, ensure_ascii=False, indent=1), encoding="utf-8")

    plan = resp.get("plan", {})
    quote = resp.get("quote", {})
    eff = resp.get("effects", {})
    val = resp.get("validation", {})
    meta = resp.get("meta", {})
    print("elapsed_ms:", elapsed)
    print("keys:", sorted(resp.keys()))
    print("meta:", json.dumps({k: meta.get(k) for k in ("status", "solver", "fallback_chain", "data_version", "inventory_ts", "inventory_periods", "solve_ms")}, ensure_ascii=False))
    print("plan:", len(plan.get("bus", [])), "bus /", len(plan.get("metro", [])), "metro")
    print("summary:", json.dumps(plan.get("summary", {}), ensure_ascii=False))
    print("quote:", json.dumps({k: quote.get(k) for k in ("rate_card_total_wan", "discount", "media_net_wan", "production_wan", "agency_fee_wan", "total_paid_wan", "budget_slack_wan")}, ensure_ascii=False))
    print("effects:", json.dumps({k: eff.get(k) for k in ("impressions", "grp", "reach", "frequency", "cpm_yuan")}, ensure_ascii=False))
    print("validation_passed:", val.get("passed"))
    failed = [c for c in val.get("checks", []) if not c.get("passed")]
    if failed:
        print("validation_failed:", json.dumps(failed, ensure_ascii=False))
    print("elasticity_points:", len(resp.get("elasticity", {}).get("points", [])))
    print("schedule_batches:", len(resp.get("schedule", {}).get("batches", [])))
    if args.dump:
        print("dumped:", args.dump)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
