#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""打印九档弹性点（用于验收/文档）。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    from engine.orchestrator import generate_elasticity

    req = {
        "industry": "乐园",
        "venue": sys.argv[1] if len(sys.argv) > 1 else "lego_shanghai",
        "budget_wan": 500,
        "media": ["bus", "metro"],
        "start_date": "2027-07-01",
        "weeks": 8,
        "customer_type": "direct",
        "locks": {"include": [], "exclude": []},
    }
    el = generate_elasticity(req)
    prev = None
    for p in el.get("points", []):
        imp = p["impressions"]
        print(
            f"{int(p['budget_wan']):>5} | imp={imp:>10} | reach={p['reach']:.4f} | "
            f"freq={p['frequency']:>6.2f} | cpm={p['cpm_yuan']:>6.2f} | "
            f"marginal={p['marginal_impressions_per_wan']:>10}"
        )
        prev = imp
    print("knee:", el.get("knee_budget_wan"), "points:", len(el.get("points", [])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
