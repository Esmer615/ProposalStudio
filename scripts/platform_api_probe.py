# -*- coding: utf-8 -*-
"""用已保存的平台会话直接调用覆盖分析接口，验证响应结构。只读。"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict

import httpx

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "data" / "external" / "platform_storage.json"
OUT = ROOT / "data" / "external" / "platform"
OUT.mkdir(parents=True, exist_ok=True)
BASE = "https://flairmedia.com.cn:38880"


def load_cookies() -> Dict[str, str]:
    state = json.loads(STATE.read_text(encoding="utf-8"))
    cookies = {}
    for c in state.get("cookies") or []:
        name = c.get("name")
        val = c.get("value")
        if name and val is not None:
            cookies[name] = val
    return cookies


def main() -> int:
    cookies = load_cookies()
    print("cookies loaded:", ", ".join(sorted(cookies.keys())) or "(none)")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
        "Referer": BASE + "/nearbyPoiLineQuery",
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "application/json, text/javascript, */*; q=0.01",
    }
    payload = {
        "radius": 1000,
        "mediaTypes": ["bus", "metro"],
        "lineScope": "all",
        "centers": [
            {
                "name": "上海乐高乐园",
                "address": "上海市金山区枫泾镇",
                "lng": 121.104,
                "lat": 30.880,
            }
        ],
    }
    with httpx.Client(verify=False, timeout=60, follow_redirects=True, headers=headers, cookies=cookies) as c:
        r = c.post(BASE + "/baseInfoLine/matchCoverLines", json=payload)
        print("status:", r.status_code, "ct:", r.headers.get("content-type"))
        text = r.text
        out = OUT / "match_lego_1000.json"
        out.write_text(text, encoding="utf-8")
        print("saved:", out, "bytes:", len(text))
        try:
            data = r.json()
        except Exception:
            print("not json:", text[:500])
            return 1
        print("top keys:", list(data.keys()) if isinstance(data, dict) else type(data).__name__)
        print("code:", data.get("code") if isinstance(data, dict) else None, "msg:", data.get("msg") if isinstance(data, dict) else None)
        items = data.get("data") if isinstance(data, dict) else None
        print("items:", len(items) if isinstance(items, list) else type(items).__name__)
        if isinstance(items, list) and items:
            print("item keys:", list(items[0].keys()))
            print(json.dumps(items[0], ensure_ascii=False, indent=1)[:3000])
            print("last item:", json.dumps(items[-1], ensure_ascii=False, indent=1)[:1000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
