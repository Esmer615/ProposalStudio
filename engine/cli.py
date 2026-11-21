# -*- coding: utf-8 -*-
"""CLI 入口：python -m engine.cli ..."""
from __future__ import annotations

import argparse
import json
import sys

from .orchestrator import generate_plan
from .models import PlanError


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m engine.cli", description="乐园户外媒体提案引擎")
    p.add_argument("--venue", default="lego_shanghai")
    p.add_argument("--budget", type=float, default=500)
    p.add_argument("--media", default="bus,metro", help="逗号分隔：bus,metro")
    p.add_argument("--start", default="2027-07-01")
    p.add_argument("--weeks", type=int, default=8)
    p.add_argument("--customer-type", default="direct")
    p.add_argument("--out", default=None, help="输出 JSON 文件路径")
    p.add_argument("--include", default="", help="锁定 include，逗号分隔 id")
    p.add_argument("--exclude", default="", help="排除，逗号分隔 id")
    args = p.parse_args(argv)

    media = [m.strip() for m in args.media.split(",") if m.strip()]
    inc = [x.strip() for x in args.include.split(",") if x.strip()]
    exc = [x.strip() for x in args.exclude.split(",") if x.strip()]

    req = {
        "venue": args.venue,
        "budget_wan": args.budget,
        "media": media,
        "start_date": args.start,
        "weeks": args.weeks,
        "customer_type": args.customer_type,
        "locks": {"include": inc, "exclude": exc},
    }

    try:
        out = generate_plan(req, include_elasticity=True)
    except PlanError as e:
        print(json.dumps(e.to_dict(), ensure_ascii=False, indent=2), file=sys.stderr)
        return 1

    text = json.dumps(out, ensure_ascii=False, indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"已写入 {args.out}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
