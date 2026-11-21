#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""按档期抓取红豆公交/地铁库存，输出 CSV + 汇总 JSON。

这是 ad-hoc 查询入口：默认落在 data/hongdou/，不会影响引擎读取的
data/snapshots/。要更新管线快照，请用 snapshot.py。

用法：
    python fetch.py --start 2027-07-01 --end 2027-07-31
    python fetch.py --start 2027-07-01 --end 2027-07-31 --media bus --line-name 100
    python fetch.py --start 2027-07-01 --end 2027-07-31 --media metro --keyword 上海南站
    python fetch.py ... --free-only --exclude-special
    python fetch.py ... --media bus --json-out data/hongdou/100路.json

stdout 始终是 JSON 汇总；进度写 stderr。

退出码：0 成功；2 用法/缺凭证；3 令牌失效；4 接口 code!=0；5 网络错误。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import hongdou_lib as hd


def _json_print(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _fail(code: int, message: str, error_type: str) -> int:
    _json_print({"ok": False, "error": message, "error_type": error_type})
    print(message, file=sys.stderr)
    return code


def _local_filters(args) -> dict:
    raw = {
        "free_only": args.free_only,
        "company": args.company,
        "media_name": args.media_name,
        "level": args.level,
        "exclude_special": args.exclude_special,
    }
    return {k: v for k, v in raw.items() if v not in (None, False)}


def _server_params(media: str, args) -> dict:
    params = {}
    if media == "bus":
        if args.line_name:
            params["lineName"] = args.line_name
    else:
        if args.keyword:
            params["keyword"] = args.keyword
        if args.district_code:
            params["districtname"] = args.district_code
    if args.line_level:
        params["lineLevel"] = args.line_level
    return params


def _validate_args(args) -> None:
    hd.validate_range(args.start, args.end)
    if args.page_size <= 0:
        raise ValueError("--page-size 必须为正整数")
    if args.max_pages is not None and args.max_pages <= 0:
        raise ValueError("--max-pages 必须为正整数")

    bus_only = {
        "--line-name": args.line_name,
        "--company": args.company,
        "--media-name": args.media_name,
    }
    metro_only = {
        "--keyword": args.keyword,
        "--district-code": args.district_code,
    }
    for name, value in bus_only.items():
        if value and args.media != "bus":
            raise ValueError(f"{name} 只适用于 --media bus（当前 --media {args.media}）")
    for name, value in metro_only.items():
        if value and args.media != "metro":
            raise ValueError(f"{name} 只适用于 --media metro（当前 --media {args.media}）")
    if args.exclude_special and args.media == "bus":
        raise ValueError("--exclude-special 只适用于地铁（公交 specialSituation 为空）")
    if args.json_out and args.media == "all":
        raise ValueError("--json-out 需要配合 --media bus 或 --media metro（一次一个文件）")


def _write_json(path: str, payload: dict) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def main() -> int:
    hd.ensure_utf8_stdio()
    parser = argparse.ArgumentParser(
        description="红豆库存 ad-hoc 抓取（公交/地铁，按档期；只读）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例：\n"
            "  python fetch.py --start 2027-07-01 --end 2027-07-31\n"
            "  python fetch.py --start 2027-07-01 --end 2027-07-31 --media bus --line-name 100\n"
            "  python fetch.py --start 2027-07-01 --end 2027-07-31 --media metro --keyword 上海南站\n"
        ),
    )
    parser.add_argument("--start", required=True, help="开始日期 YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="结束日期 YYYY-MM-DD")
    parser.add_argument("--media", choices=("bus", "metro", "all"), default="all",
                        help="媒体类型（默认 all）")
    parser.add_argument("--line-name", help="公交线路名，服务端模糊匹配（仅 --media bus）")
    parser.add_argument("--keyword", help="地铁站名/出入口，服务端模糊匹配（仅 --media metro）")
    parser.add_argument("--line-level", help="线路等级编码，如 1/2/3/5/6（公交/地铁都支持）")
    parser.add_argument("--district-code", help="地铁区编码（编码含义未确认，仅 --media metro）")
    parser.add_argument("--company", help="公交行车公司，抓回后本地模糊过滤")
    parser.add_argument("--media-name", help="公交媒体类型（车身三侧/大三侧/全色车），本地过滤")
    parser.add_argument("--level", help="等级名或原始编码（S/A++/A+/AA/1/2/3/5），本地过滤")
    parser.add_argument("--free-only", action="store_true", help="只要 freeCount > 0 的行")
    parser.add_argument("--exclude-special", action="store_true",
                        help="剔除封闭/改造/施工/停用/停运的地铁点位")
    parser.add_argument("--out", default=os.path.join(hd.PROJECT_ROOT, "data", "hongdou"),
                        help="输出目录（默认 data/hongdou）")
    parser.add_argument("--tag", help="文件名后缀标签；有筛选时默认 filtered")
    parser.add_argument("--page-size", type=int, default=200, help="每页条数（默认 200）")
    parser.add_argument("--max-pages", type=int, help="最多翻几页（调试用；会截断结果）")
    parser.add_argument("--no-csv", action="store_true", help="不写 CSV，只输出汇总")
    parser.add_argument("--json-out", help="把筛选后的原始行写成 JSON（需单媒体）")
    parser.add_argument("--summary-out", help="把完整汇总 JSON 另存到文件")
    parser.add_argument("--quiet", action="store_true", help="不打印翻页进度")
    args = parser.parse_args()

    try:
        _validate_args(args)
    except ValueError as e:
        return _fail(2, str(e), "usage")

    media_list = ["bus", "metro"] if args.media == "all" else [args.media]
    local = _local_filters(args)
    started = time.time()

    results = {}
    written_files = {}

    try:
        for media in media_list:
            server = _server_params(media, args)
            filters = {}
            if server:
                filters["server"] = server
            if local:
                filters["local"] = local

            hd.log_stderr(
                f"抓取 {media}：{args.start} ~ {args.end}"
                + (f"，服务端筛选 {server}" if server else ""),
                quiet=args.quiet,
            )

            rows, meta = hd.fetch_media(
                media, args.start, args.end,
                page_size=args.page_size,
                max_pages=args.max_pages,
                server_params=server,
                verbose=not args.quiet,
            )
            unfiltered_rows = len(rows)
            rows = hd.apply_filters(
                rows, media,
                free_only=args.free_only,
                line_name=args.line_name,
                keyword=args.keyword,
                company=args.company,
                media_name=args.media_name,
                level=args.level,
                exclude_special=args.exclude_special,
                district_code=args.district_code,
            )

            summary = hd.summarize(
                rows, media, args.start, args.end, filters=filters, meta=meta,
            )
            summary["unfiltered_rows"] = unfiltered_rows
            if not rows:
                summary["notes"].append(
                    f"抓回 {unfiltered_rows} 行，本地筛选后为 0 行；可放宽 --free-only/--level 等条件。"
                )

            csv_path = None
            if not args.no_csv:
                has_filters = bool(server) or bool(local)
                suffix = ""
                if args.tag:
                    suffix = "_" + hd.safe_tag(args.tag)
                elif has_filters:
                    suffix = "_filtered"
                csv_path = os.path.join(
                    args.out, f"{media}_{args.start}_{args.end}{suffix}.csv")
                hd.write_csv(csv_path, rows)
                written_files[media] = hd.display_path(csv_path)
                hd.log_stderr(
                    f"  写入 {hd.display_path(csv_path)}（{len(rows)} 行）",
                    quiet=args.quiet,
                )
            summary["file"] = hd.display_path(csv_path) if csv_path else None
            results[media] = summary

            if args.json_out:
                payload = {
                    "ok": True,
                    "media": media,
                    "period": {"start": args.start, "end": args.end},
                    "filters": filters,
                    "fetch": summary["fetch"],
                    "rows": rows,
                }
                _write_json(args.json_out, payload)
                hd.log_stderr(f"  写入 {hd.display_path(args.json_out)}", quiet=args.quiet)

    except hd.AuthError as e:
        return _fail(2, str(e), "auth")
    except hd.TokenStale as e:
        return _fail(3, str(e), "token_stale")
    except hd.ApiError as e:
        return _fail(4, str(e), "api")
    except hd.NetworkError as e:
        return _fail(5, str(e), "network")
    except KeyboardInterrupt:
        return _fail(130, "已中断", "interrupted")

    output = {
        "ok": True,
        "base": hd.BASE,
        "period": {"start": args.start, "end": args.end},
        "media": args.media,
        "filters": {
            "server": {m: _server_params(m, args) for m in media_list},
            "local": local,
        },
        "results": results,
        "files": written_files,
        "inventory_ts": hd.utc_now(),
        "elapsed_sec": round(time.time() - started, 2),
        "notes": [
            "库存是实时查询结果，回答时必须带档期 + 查询时间戳。",
            "接口 total 不可作为翻页终止条件；以 results.<media>.rows / fetched_rows 为准。",
        ],
    }

    if args.summary_out:
        _write_json(args.summary_out, output)
        hd.log_stderr(f"写入 {hd.display_path(args.summary_out)}", quiet=args.quiet)

    _json_print(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
