#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""离线分析已抓取的红豆库存 CSV（不联网）。

用于：
  * 对已有快照做可售汇总（不用重复打接口）；
  * 按线路/公司/媒体类型/等级/商圈标签分组；
  * 维度发现：看看有哪些线路、公司、站点、商圈标签。

用法：
    python analyze.py --file data/hongdou/bus_2027-07-01_2027-07-31.csv
    python analyze.py --file ... --free-only --group-by companyName
    python analyze.py --file ... --facets --top 15
    python analyze.py --file data/snapshots/metro_2027-01-01_2027-01-31.csv \
        --exclude-special --group-by categoryTags --free-only
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

import hongdou_lib as hd


def _json_print(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _fail(code: int, message: str, error_type: str) -> int:
    _json_print({"ok": False, "error": message, "error_type": error_type})
    print(message, file=sys.stderr)
    return code


def _period_from_name(path: str) -> tuple[str, str]:
    match = re.search(r"(\d{4}-\d{2}-\d{2})_(\d{4}-\d{2}-\d{2})", os.path.basename(path))
    return (match.group(1), match.group(2)) if match else ("", "")


def main() -> int:
    hd.ensure_utf8_stdio()
    parser = argparse.ArgumentParser(
        description="离线分析红豆库存 CSV（汇总/分组/维度发现；不联网）",
    )
    parser.add_argument("--file", required=True, help="库存 CSV 路径")
    parser.add_argument("--free-only", action="store_true", help="只看 freeCount > 0")
    parser.add_argument("--line-name", help="线路名/站名，模糊过滤")
    parser.add_argument("--keyword", help="站名或出入口，模糊过滤（地铁）")
    parser.add_argument("--company", help="公交行车公司，模糊过滤")
    parser.add_argument("--media-name", help="公交媒体类型，模糊过滤")
    parser.add_argument("--level", help="等级名或原始编码（S/A++/A+/AA/1/2/3/5）")
    parser.add_argument("--exclude-special", action="store_true",
                        help="剔除封闭/改造/施工/停用/停运的地铁点位")
    parser.add_argument("--district-code", help="地铁区编码（精确匹配 districtname 数组元素）")
    parser.add_argument("--group-by", help="分组列，逗号分隔，如 companyName 或 lineName,mediaName")
    parser.add_argument("--facets", action="store_true",
                        help="输出维度发现（线路/公司/媒体类型/等级/商圈标签等）")
    parser.add_argument("--top", type=int, default=20,
                        help="分组/维度每项最多返回多少条（默认 20；0=全部）")
    parser.add_argument("--json-out", help="把结果另存为 JSON 文件")
    args = parser.parse_args()

    if args.top < 0:
        return _fail(2, "--top 不能为负", "usage")
    if not os.path.isfile(args.file):
        return _fail(2, f"文件不存在：{args.file}", "usage")

    try:
        raw_rows = hd.read_csv(args.file)
    except (OSError, UnicodeError) as e:
        return _fail(2, f"读取 CSV 失败：{e}", "usage")
    if not raw_rows:
        return _fail(2, f"CSV 没有数据行：{args.file}", "empty")

    try:
        media = hd.detect_media(raw_rows, args.file)
    except ValueError as e:
        return _fail(2, str(e), "usage")

    filters = {
        k: v for k, v in {
            "free_only": args.free_only,
            "line_name": args.line_name,
            "keyword": args.keyword,
            "company": args.company,
            "media_name": args.media_name,
            "level": args.level,
            "exclude_special": args.exclude_special,
            "district_code": args.district_code,
        }.items() if v not in (None, False)
    }

    rows = hd.apply_filters(
        raw_rows, media,
        free_only=args.free_only,
        line_name=args.line_name,
        keyword=args.keyword,
        company=args.company,
        media_name=args.media_name,
        level=args.level,
        exclude_special=args.exclude_special,
        district_code=args.district_code,
    )

    start, end = _period_from_name(args.file)
    summary = hd.summarize(rows, media, start, end, filters=filters)
    summary["fetched_rows"] = len(raw_rows)   # 离线口径：CSV 全量行数
    summary["source_rows"] = len(raw_rows)
    summary["filtered_out"] = len(raw_rows) - len(rows)
    if not rows:
        summary["notes"].append("筛选后 0 行；放宽 --free-only/--level 等条件再试。")

    result = {
        "ok": True,
        "file": hd.display_path(args.file),
        "media": media,
        "period": {"start": start, "end": end},
        "filters": filters,
        "summary": summary,
    }

    if args.group_by:
        columns = [c.strip() for c in args.group_by.split(",") if c.strip()]
        if not columns:
            return _fail(2, "--group-by 不能为空", "usage")
        try:
            result["group_by"] = hd.build_groups(rows, media, columns, top=args.top)
        except ValueError as e:
            return _fail(2, str(e), "usage")

    if args.facets:
        result["facets"] = hd.build_facets(rows, media, top=args.top)

    if args.json_out:
        os.makedirs(os.path.dirname(os.path.abspath(args.json_out)), exist_ok=True)
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"写入 {hd.display_path(args.json_out)}", file=sys.stderr)

    _json_print(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
