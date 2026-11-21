# -*- coding: utf-8 -*-
"""解析 app.min.js / common.js 的接口与 showLabel/导出逻辑。"""
from __future__ import annotations

import os
import re

ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "external", "sources")
FILES = ["res_busi-load_app.min.js", "js_common.js.js"]

KEYWORDS = ["showLabel", "export", "downloadExcel", "infoPage", "infoFrame", "queryLabel", "labelId", "area", "crowd", "people", "flow", "query"]


def main() -> None:
    for fn in FILES:
        p = os.path.join(ROOT, fn)
        if not os.path.exists(p):
            continue
        s = open(p, encoding="utf-8", errors="replace").read()
        print(f"\n===== {fn} ({len(s)} bytes) =====")
        urls = sorted(set(re.findall(r"['\"](/[A-Za-z][\w/.-]*)['\"]", s)))
        print("URLS:")
        for u in urls:
            if any(k in u.lower() for k in ("label", "info", "query", "export", "download", "base", "line", "area", "flow", "crowd")):
                print("  ", u)
        for kw in KEYWORDS:
            idxs = [m.start() for m in re.finditer(re.escape(kw), s, re.I)]
            if not idxs:
                continue
            print(f"\n--- {kw} ({len(idxs)}) ---")
            for i in idxs[:4]:
                print(s[max(0, i - 350):i + 700].replace("\n", " ")[:1100])


if __name__ == "__main__":
    main()
