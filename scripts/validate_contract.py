#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""契约形状校验：引擎输出必须覆盖 fixture 的字段/类型（允许新增字段）。

用法：
    .venv\\Scripts\\python.exe scripts/validate_contract.py
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FIXTURE = ROOT / "web" / "src" / "fixtures" / "plan.fixture.json"
NULLABLE = {None}


def _type_name(x: Any) -> str:
    if x is None:
        return "null"
    if isinstance(x, bool):
        return "bool"
    if isinstance(x, (int, float)):
        return "number"
    if isinstance(x, str):
        return "string"
    if isinstance(x, list):
        return "array"
    if isinstance(x, dict):
        return "object"
    return type(x).__name__


def _compare(expected: Any, actual: Any, path: str, errors: list[str], warnings: list[str]) -> None:
    # 动态字典：区县/等级配比的 key 随方案变化，不要求与 fixture 完全同 key
    if path.endswith(".district_mix") or path.endswith(".level_mix"):
        if not isinstance(actual, dict):
            errors.append(f"{path}: expected object")
            return
        bad = [k for k, v in actual.items() if not isinstance(v, (int, float))]
        if bad:
            errors.append(f"{path}: non-numeric values {bad[:5]}")
        return
    # 懒加载弹性：/api/plan 默认 points=[]，不要求 knee 是数字
    if path == "$.elasticity" and isinstance(actual, dict) and not actual.get("points"):
        warnings.append("$.elasticity.points: empty (lazy; /api/elasticity computes it)")
        return
    # 最高档（68%）没有上限，允许 null
    if path == "$.quote.discount_tier.max_gross_wan" and actual is None:
        return

    et = _type_name(expected)
    at = _type_name(actual)
    if et == "null":
        return
    if et != at:
        # 允许 fixture 的 int 与实际 float（/反之）
        if et == "number" and at == "number":
            pass
        else:
            errors.append(f"{path}: type {at} != expected {et}")
            return
    if et == "object":
        for k, v in expected.items():
            if k not in actual:
                errors.append(f"{path}.{k}: missing")
            else:
                _compare(v, actual[k], f"{path}.{k}", errors, warnings)
    elif et == "array":
        if not expected:
            return
        if not actual:
            warnings.append(f"{path}: empty array (fixture has sample)")
            return
        _compare(expected[0], actual[0], f"{path}[0]", errors, warnings)
        # 如果数组元素是对象，检查所有实际元素都有关键字段
        if isinstance(expected[0], dict):
            keys = set(expected[0].keys())
            for i, item in enumerate(actual[:20]):
                if isinstance(item, dict):
                    missing = keys - set(item.keys())
                    if missing:
                        errors.append(f"{path}[{i}]: missing keys {sorted(missing)}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--venue", default="lego_shanghai")
    ap.add_argument("--budget", type=float, default=500)
    ap.add_argument("--media", default="bus,metro")
    ap.add_argument("--start", default="2027-07-01")
    ap.add_argument("--weeks", type=int, default=8)
    ap.add_argument("--customer-type", default="direct")
    ap.add_argument("--response", help="直接校验一个 PlanResponse JSON 文件，不调用引擎")
    args = ap.parse_args()

    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    if args.response:
        resp = json.loads(Path(args.response).read_text(encoding="utf-8"))
    else:
        try:
            from engine.orchestrator import generate_plan
        except Exception as exc:
            print(f"[FAIL] cannot import engine.orchestrator: {type(exc).__name__}: {exc}")
            return 2
        resp = generate_plan(
            {
                "industry": "乐园",
                "venue": args.venue,
                "budget_wan": args.budget,
                "media": [m.strip() for m in args.media.split(",") if m.strip()],
                "start_date": args.start,
                "weeks": args.weeks,
                "customer_type": args.customer_type,
                "locks": {"include": [], "exclude": []},
            }
        )

    errors: list[str] = []
    warnings: list[str] = []
    _compare(fixture, resp, "$", errors, warnings)
    # 业务不变量
    try:
        if float(resp["quote"]["total_paid_wan"]) > float(resp["quote"]["budget_wan"]) + 1e-6:
            errors.append("$.quote: total_paid_wan > budget_wan")
        if not resp["quote"]["allocation_check"].get("passed"):
            errors.append("$.quote.allocation_check.passed is false")
        if not resp["validation"].get("passed"):
            errors.append("$.validation.passed is false (blocker)")
        if abs(float(resp["plan"]["summary"]["total_paid_wan"]) - float(resp["quote"]["total_paid_wan"])) > 1.0:
            errors.append("$.plan.summary.total_paid_wan != quote.total_paid_wan")
    except Exception as exc:
        errors.append(f"business invariant check failed: {type(exc).__name__}: {exc}")

    if warnings:
        print("[WARN]")
        for w in warnings[:20]:
            print("  -", w)
    if errors:
        print(f"[FAIL] {len(errors)} contract issue(s):")
        for e in errors[:50]:
            print("  -", e)
        return 1
    print("[PASS] PlanResponse matches fixture contract shape and business invariants")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
