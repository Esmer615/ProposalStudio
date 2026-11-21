#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""确定性检查：同一请求连续 N 次，除 meta 时间/耗时/缓存外必须完全一致。

用法：
    .venv\\Scripts\\python.exe scripts/check_determinism.py --runs 5
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

VOLATILE_META = {"generated_at", "request_id", "solve_ms", "total_ms", "cache_hit"}


def _strip_volatile(resp: dict) -> dict:
    out = json.loads(json.dumps(resp, ensure_ascii=False))
    meta = out.get("meta") or {}
    for k in VOLATILE_META:
        meta.pop(k, None)
    out["meta"] = meta
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=5)
    ap.add_argument("--venue", default="lego_shanghai")
    ap.add_argument("--budget", type=float, default=500)
    ap.add_argument("--media", default="bus,metro")
    ap.add_argument("--start", default="2027-07-01")
    ap.add_argument("--weeks", type=int, default=8)
    ap.add_argument("--customer-type", default="direct")
    args = ap.parse_args()

    try:
        from engine.orchestrator import generate_plan
    except Exception as exc:
        print(f"[FAIL] cannot import engine.orchestrator: {type(exc).__name__}: {exc}")
        return 2

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

    base = None
    for i in range(args.runs):
        resp = generate_plan(req)
        clean = _strip_volatile(resp)
        if base is None:
            base = clean
            print(f"[run {i+1}] PLAN id/units: {len(resp.get('plan', {}).get('bus', []))} bus / {len(resp.get('plan', {}).get('metro', []))} metro; solve_ms={resp.get('meta', {}).get('solve_ms')}")
            continue
        if clean != base:
            print(f"[FAIL] run {i+1} differs from run 1")
            # 显示第一个差异路径
            def diff(a, b, path=""):
                if type(a) is not type(b):
                    return f"{path}: type {type(a).__name__} != {type(b).__name__}"
                if isinstance(a, dict):
                    for k in sorted(set(a) | set(b)):
                        if k not in a or k not in b:
                            return f"{path}/{k}: missing"
                        d = diff(a[k], b[k], f"{path}/{k}")
                        if d:
                            return d
                elif isinstance(a, list):
                    if len(a) != len(b):
                        return f"{path}: len {len(a)} != {len(b)}"
                    for j, (x, y) in enumerate(zip(a, b)):
                        d = diff(x, y, f"{path}[{j}]")
                        if d:
                            return d
                elif a != b:
                    return f"{path}: {a!r} != {b!r}"
                return None

            print("  first diff:", diff(base, clean))
            return 1
        print(f"[run {i+1}] identical (meta volatile stripped)")

    print(f"[PASS] {args.runs} runs deterministic")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
