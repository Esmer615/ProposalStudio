# -*- coding: utf-8 -*-
"""解析平台业务 JS，定位查询/导出接口与参数。"""
from __future__ import annotations

import os
import re
import sys

ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "external", "sources")
TARGET = sys.argv[1] if len(sys.argv) > 1 else "js_busi_nearbyPoiLineQuery.js"
P = os.path.join(ROOT, TARGET)
s = open(P, encoding="utf-8", errors="replace").read()
lines = s.splitlines()

print(f"=== {TARGET} ({len(s)} bytes, {len(lines)} lines) ===")
# 1) URL-like strings
urls = set()
for pat in [
    r"url\s*:\s*['\"]([^'\"]+)['\"]",
    r"url\s*=\s*['\"]([^'\"]+)['\"]",
    r"['\"](\/[A-Za-z][\w-]*\/[A-Za-z][\w/_-]*)['\"]",
]:
    for m in re.finditer(pat, s):
        u = m.group(1)
        if any(k in u.lower() for k in ("query", "export", "cover", "nearby", "analysis", "poi", "line", "download", "excel", "save", "circle")):
            urls.add(u)
print("\nURLS:")
for u in sorted(urls):
    print(" ", u)

# 2) key terms with context
terms = [
    "matchCoverLine", "exportLine", "queryPoi", "exportPoi", "downloadExcel",
    "queryCover", "coverCenter", "queryBizMode", "poiRangeMode", "coverMediaType",
    "coverLineScope", "queryAddress", "queryRange", "exportToExcel", "ajax",
    "$.post", "$.get", "data:", "params",
]
print("\nTERM CONTEXTS:")
seen = set()
for i, l in enumerate(lines):
    if any(t.lower() in l.lower() for t in terms):
        start = max(0, i - 2)
        end = min(len(lines), i + 4)
        key = (start, end)
        if key in seen:
            continue
        seen.add(key)
        print(f"\n--- L{i+1} ---")
        for j in range(start, end):
            print(f"{j+1:5}: {lines[j][:500]}")
        if len(seen) > 90:
            print("... truncated ...")
            break
