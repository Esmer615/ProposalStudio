#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""从已注入的静态导出 HTML 中提取九档预算点，供文档/验收使用。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "web" / "dist-export" / "index.html"
MARKER = "window.__PLAN_DATA__ = "


def main() -> int:
    if not HTML.exists():
        print(f"[FAIL] not found: {HTML}")
        return 2
    s = HTML.read_text(encoding="utf-8", errors="replace")
    i = s.find(MARKER)
    if i < 0:
        print("[FAIL] payload marker not found")
        return 2
    rest = s[i + len(MARKER):]
    payload, _ = json.JSONDecoder().raw_decode(rest)
    print("mode:", payload.get("mode"), "default:", payload.get("default_budget_wan"))
    plans = payload.get("plans") or {}
    prev = None
    rows = []
    for b in payload.get("tiers") or []:
        key = str(int(b)) if float(b).is_integer() else str(b)
        pl = plans.get(key)
        if not pl or "effects" not in pl:
            print(f"{b:>5} | NO FEASIBLE PLAN")
            continue
        e = pl["effects"]
        imp = e["impressions"]
        marginal = round((imp - prev) / 50.0) if prev is not None else 0
        row = {
            "budget": b,
            "impressions": imp,
            "reach": round(e["reach"], 4),
            "frequency": round(e["frequency"], 2),
            "cpm": round(e["cpm_yuan"], 2),
            "marginal_per_wan": marginal,
        }
        rows.append(row)
        prev = imp
        print(f"{int(b):>5} | imp={imp:>10} | reach={e['reach']:.4f} | freq={e['frequency']:>6.2f} | cpm={e['cpm_yuan']:>6.2f} | marginal={marginal:>10}")
    if len(rows) >= 2:
        # knee: first budget where marginal drops below 85% of previous marginal
        knee = rows[0]["budget"]
        prev_m = None
        for r in rows:
            m = r["marginal_per_wan"]
            if prev_m and prev_m > 0 and m < prev_m * 0.85:
                knee = r["budget"]
                break
            prev_m = m
        print("knee~", knee)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
