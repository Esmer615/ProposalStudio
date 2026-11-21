# -*- coding: utf-8 -*-
"""解析平台页面源码，提取查询/导出接口和表单字段。"""
from __future__ import annotations

import json
import os
import re

ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "external", "sources")
FILES = [
    "nearbyPoiLineQuery.html",
    "conditionQuery.html",
    "looseMultiQuery.html",
    "looseQuery.html",
    "comparePage.html",
    "queryPage.html",
    "busLineShowSolution.html",
    "busLineShowSolutionStation.html",
    "js_common.js.js",
]

URL_PATTERNS = [
    re.compile(r"url\s*:\s*['\"]([^'\"]+)['\"]"),
    re.compile(r"url\s*=\s*['\"]([^'\"]+)['\"]"),
    re.compile(r"action\s*=\s*['\"]([^'\"]+)['\"]"),
    re.compile(r"['\"](\/[A-Za-z][\w-]*\/[A-Za-z][\w/_-]*)['\"]"),
]

KEYWORDS = ("query", "export", "cover", "nearby", "analysis", "poi", "line", "download", "excel", "import", "save", "circle")


def main() -> int:
    for fn in FILES:
        p = os.path.join(ROOT, fn)
        if not os.path.exists(p):
            continue
        s = open(p, encoding="utf-8", errors="replace").read()
        print(f"\n===== {fn} ({len(s)} bytes) =====")
        urls = set()
        for pat in URL_PATTERNS:
            for m in pat.finditer(s):
                u = m.group(1)
                if any(k in u.lower() for k in KEYWORDS):
                    urls.add(u)
        print("URLS:", json.dumps(sorted(urls), ensure_ascii=False, indent=1)[:5000])
        lines = [l.strip() for l in s.splitlines() if re.search(r"query|cover|export|nearby|analysis|download|excel", l, re.I)]
        for l in lines[:80]:
            print("  ", l[:300])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
