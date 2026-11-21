#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""导出 HTML 脱敏/离线扫描：不得含凭证、token、外部 http(s) 资源。

用法：
    .venv\\Scripts\\python.exe scripts/verify_export.py web/dist-export/index.html
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

FORBIDDEN = [
    (re.compile(r"xin1234", re.I), "明文密码"),
    (re.compile(r"flairmedia", re.I), "红豆/可视化平台域名"),
    (re.compile(r"access_token|refresh_token|Bearer\s+[A-Za-z0-9]", re.I), "token"),
    (re.compile(r"scripts[\\/]\.credentials|\.oauth_cache\.json", re.I), "凭证文件"),
    (re.compile(r"HONGDOU_USER|HONGDOU_PASS", re.I), "凭证环境变量"),
]
EXTERNAL = re.compile(r"""(?:src|href)\s*=\s*["']https?://|url\(\s*["']?https?://""", re.I)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    args = ap.parse_args()
    p = Path(args.path)
    if not p.exists():
        print(f"[FAIL] not found: {p}")
        return 2
    html = p.read_text(encoding="utf-8", errors="replace")
    problems = []
    for rx, label in FORBIDDEN:
        if rx.search(html):
            problems.append(f"forbidden: {label}")
    if EXTERNAL.search(html):
        problems.append("external http(s) resource reference")
    # 常见 CDN 域名
    for cdn in ("cdn.jsdelivr.net", "unpkg.com", "cdnjs.cloudflare.com", "fonts.googleapis.com"):
        if cdn in html:
            problems.append(f"CDN: {cdn}")
    if problems:
        print("[FAIL] export contains:")
        for x in problems:
            print("  -", x)
        return 1
    size_mb = p.stat().st_size / 1024 / 1024
    print(f"[PASS] export clean: {p} ({size_mb:.2f} MB); no credentials/external CDN detected")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
