#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""批量抓取红豆月度库存快照，写到引擎读取的 data/snapshots/。

文件名与 scripts/fetch_hongdou.py 一致：
    bus_YYYY-MM-01_YYYY-MM-lastday.csv
    metro_YYYY-MM-01_YYYY-MM-lastday.csv
engine/data_loader.py 和 scripts/build_dataset.py 按这个命名识别月份。

行为：
  * 默认跳过已存在的文件；需要重抓加 --overwrite。
  * 单月/单媒体失败不阻塞其他月份；返回失败数（0=全部成功）。
  * 额外写 hongdou_fetch_manifest.json（抓取审计，不会被数据管线当成输入）。

用法：
    python snapshot.py --from-month 2027-01 --to-month 2027-10
    python snapshot.py --from-month 2027-06 --to-month 2027-10 --media bus --overwrite
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone

import hongdou_lib as hd


def _json_print(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _file_mtime(path: str) -> str:
    return datetime.fromtimestamp(os.path.getmtime(path), timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ")


def _write_manifest(path: str, payload: dict) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def main() -> int:
    hd.ensure_utf8_stdio()
    parser = argparse.ArgumentParser(
        description="批量抓取红豆月度库存快照（写入 data/snapshots，供引擎使用）",
    )
    parser.add_argument("--from-month", required=True, help="起始月份 YYYY-MM")
    parser.add_argument("--to-month", required=True, help="结束月份 YYYY-MM（含）")
    parser.add_argument("--media", choices=("bus", "metro", "all"), default="all")
    parser.add_argument("--out", default=os.path.join(hd.PROJECT_ROOT, "data", "snapshots"),
                        help="输出目录（默认 data/snapshots）")
    parser.add_argument("--page-size", type=int, default=200)
    parser.add_argument("--delay", type=float, default=0.2,
                        help="每次请求后的等待秒数（默认 0.2）")
    parser.add_argument("--overwrite", action="store_true",
                        help="已存在同名 CSV 也重新抓取（默认跳过）")
    parser.add_argument("--quiet", action="store_true", help="不打印进度")
    args = parser.parse_args()

    try:
        months = hd.month_range(args.from_month, args.to_month)
        if args.page_size <= 0:
            raise ValueError("--page-size 必须为正整数")
        if args.delay < 0:
            raise ValueError("--delay 不能为负")
    except ValueError as e:
        _json_print({"ok": False, "error": str(e), "error_type": "usage"})
        print(str(e), file=sys.stderr)
        return 2

    media_list = ["bus", "metro"] if args.media == "all" else [args.media]
    os.makedirs(args.out, exist_ok=True)
    entries: list[dict] = []
    failures = 0
    started = time.time()

    try:
        for month in months:
            start, end = hd.month_bounds(month)
            hd.log_stderr(f"\n===== {month}：{start} ~ {end} =====", quiet=args.quiet)
            for media in media_list:
                filename = f"{media}_{start}_{end}.csv"
                path = os.path.join(args.out, filename)
                base = {"month": month, "start": start, "end": end,
                        "media": media, "file": hd.display_path(path)}

                if os.path.exists(path) and not args.overwrite:
                    try:
                        rows = hd.read_csv(path)
                    except OSError as e:
                        failures += 1
                        entries.append({**base, "status": "failed",
                                        "error": f"读取已有文件失败：{e}"})
                        hd.log_stderr(f"  [FAIL] {media} 读取已有文件失败：{e}",
                                      quiet=args.quiet)
                        continue
                    entries.append({
                        **base,
                        "status": "skipped",
                        "rows": len(rows),
                        "free_total": sum(hd.to_int(r.get("freeCount")) for r in rows),
                        "sha256": hd.sha256_file(path),
                        "file_mtime": _file_mtime(path),
                    })
                    hd.log_stderr(
                        f"  [SKIP] {media} 已存在 {filename}（{len(rows)} 行）；"
                        "需要重抓加 --overwrite",
                        quiet=args.quiet,
                    )
                    continue

                hd.log_stderr(f"  [FETCH] {media} -> {filename}", quiet=args.quiet)
                try:
                    rows, meta = hd.fetch_media(
                        media, start, end,
                        page_size=args.page_size,
                        delay=args.delay,
                        verbose=not args.quiet,
                    )
                except hd.ApiError as e:
                    failures += 1
                    entries.append({**base, "status": "failed", "error_type": "api",
                                    "error": str(e)})
                    hd.log_stderr(f"  [FAIL] {media} {month} 接口错误：{e}", quiet=args.quiet)
                    continue
                except hd.NetworkError as e:
                    failures += 1
                    entries.append({**base, "status": "failed", "error_type": "network",
                                    "error": str(e)})
                    hd.log_stderr(f"  [FAIL] {media} {month} 网络错误：{e}", quiet=args.quiet)
                    continue

                if not rows:
                    failures += 1
                    entries.append({**base, "status": "empty",
                                    "error": "接口返回 0 行；未写文件，避免污染引擎快照",
                                    "fetch": meta})
                    hd.log_stderr(f"  [EMPTY] {media} {month} 返回 0 行，未写文件",
                                  quiet=args.quiet)
                    continue

                hd.write_csv(path, rows)
                entry = {
                    **base,
                    "status": "ok",
                    "rows": len(rows),
                    "free_total": sum(hd.to_int(r.get("freeCount")) for r in rows),
                    "sha256": hd.sha256_file(path),
                    "fetch": meta,
                }
                entries.append(entry)
                hd.log_stderr(
                    f"  [OK] {media} {filename}（{len(rows)} 行，"
                    f"free={entry['free_total']}）",
                    quiet=args.quiet,
                )

    except hd.AuthError as e:
        _json_print({"ok": False, "error": str(e), "error_type": "auth",
                     "entries": entries})
        print(str(e), file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        _json_print({"ok": False, "error": "已中断", "error_type": "interrupted",
                     "entries": entries})
        return 130

    manifest_path = os.path.join(args.out, "hongdou_fetch_manifest.json")
    manifest = {
        "generated_at": hd.utc_now(),
        "base": hd.BASE,
        "out": hd.display_path(args.out),
        "months": months,
        "media": media_list,
        "overwrite": args.overwrite,
        "failures": failures,
        "entries": entries,
        "note": "抓取审计文件；项目数据管线 manifest 由 scripts/build_dataset.py 生成。",
    }
    _write_manifest(manifest_path, manifest)

    output = {
        "ok": failures == 0,
        "out": hd.display_path(args.out),
        "months": months,
        "media": media_list,
        "entries": entries,
        "failures": failures,
        "manifest": hd.display_path(manifest_path),
        "inventory_ts": hd.utc_now(),
        "elapsed_sec": round(time.time() - started, 2),
    }
    _json_print(output)

    if failures:
        print(f"完成，但有 {failures} 个失败/空结果；详见 {manifest_path}",
              file=sys.stderr)
    else:
        print(f"完成，全部成功；清单 {manifest_path}", file=sys.stderr)
    return min(failures, 125)


if __name__ == "__main__":
    sys.exit(main())
