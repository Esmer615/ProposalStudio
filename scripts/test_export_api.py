#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""验证 FastAPI /api/export：返回注入真实 9 档方案的 HTML。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402
from server.main import app  # noqa: E402

REQ = {
    "industry": "乐园",
    "venue": "lego_shanghai",
    "budget_wan": 500,
    "media": ["bus", "metro"],
    "start_date": "2027-07-01",
    "weeks": 8,
    "customer_type": "direct",
    "locks": {"include": [], "exclude": []},
}


def main() -> int:
    client = TestClient(app)
    r = client.post("/api/export", json=REQ)
    print("status:", r.status_code, "bytes:", len(r.content))
    if r.status_code != 200:
        print(r.text[:1000])
        return 1
    html = r.text
    print("has_window_payload:", "window.__PLAN_DATA__" in html)
    print("has_payload_mode:", '"mode": "static-export"' in html or '"mode":"static-export"' in html)
    print("has_tiers:", '"tiers"' in html)
    print("has_token_left:", "__PLAN_PAYLOAD__" in html)
    out = ROOT / "web" / "dist-export" / "api-export.html"
    out.write_text(html, encoding="utf-8")
    print("written:", out, f"({out.stat().st_size/1024/1024:.2f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
