#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把真实引擎的预算档位方案注入单文件导出 HTML。

前置：pnpm --dir web export 生成 web/dist-export/index.html，且含 __PLAN_DATA__ 占位符。
用法：
    .venv\\Scripts\\python.exe scripts/build_export.py --venue lego_shanghai --budget 500
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.export_payload import build_export_payload  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--venue", default="lego_shanghai")
    ap.add_argument("--budget", type=float, default=500)
    ap.add_argument("--media", default="bus,metro")
    ap.add_argument("--start", default="2027-07-01")
    ap.add_argument("--weeks", type=int, default=8)
    ap.add_argument("--customer-type", default="direct")
    ap.add_argument("--step", type=int, default=50)
    default_html = ROOT / "web" / "dist-export" / "index.html"
    if not default_html.exists():
        default_html = ROOT / "web" / "dist-export" / "export.html"
    ap.add_argument("--html", default=str(default_html))
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    html_path = Path(args.html)
    if not html_path.exists():
        print(f"[FAIL] export html not found: {html_path}")
        print("       run: pnpm --dir web export")
        return 2
    html = html_path.read_text(encoding="utf-8", errors="replace")
    if "__PLAN_PAYLOAD__" not in html and "__PLAN_DATA__" not in html:
        print("[FAIL] payload placeholder not found; frontend export build must keep __PLAN_PAYLOAD__")
        return 2

    payload = build_export_payload(
        {
            "industry": "乐园",
            "venue": args.venue,
            "budget_wan": args.budget,
            "media": [m.strip() for m in args.media.split(",") if m.strip()],
            "start_date": args.start,
            "weeks": args.weeks,
            "customer_type": args.customer_type,
            "locks": {"include": [], "exclude": []},
        },
        step=args.step,
    )
    encoded = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    if "__PLAN_PAYLOAD__" in html:
        out_html = html.replace("__PLAN_PAYLOAD__", encoded)
    else:
        # 兼容旧模板：只注入 head script，不替换属性名
        out_html = html.replace(
            "</head>",
            f"<script>window.__PLAN_DATA__ = {encoded};</script></head>",
        )
    out_path = Path(args.out) if args.out else html_path
    out_path.write_text(out_html, encoding="utf-8")
    size_mb = out_path.stat().st_size / 1024 / 1024
    ok_tiers = sum(1 for p in payload["plans"].values() if "error" not in p)
    print(f"[OK] {out_path} ({size_mb:.2f} MB); tiers={len(payload['tiers'])}, feasible={ok_tiers}, default={payload['default_budget_wan']}万")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
