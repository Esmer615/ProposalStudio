#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""最小 manifest 兜底：扫描红豆快照，生成 data/processed/manifest.json。

用于 Agent-A 的完整 build_dataset 尚未就绪时，让 server/meta 与页面显示
data_version / inventory_periods。完整版 manifest 可由 Agent-A 覆盖。
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
SNAP = DATA / "snapshots"
OUT = DATA / "processed"
CONFIG = DATA / "config"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _sum_col(rows: List[Dict[str, str]], col: str) -> int:
    total = 0
    for r in rows:
        try:
            total += int(float(r.get(col) or 0))
        except (TypeError, ValueError):
            pass
    return total


def main() -> int:
    import csv

    files = sorted(list(SNAP.glob("*.csv")) + list(DATA.glob("*_2027-*.csv")))
    seen = set()
    records = []
    periods = set()
    bus_rows = metro_rows = 0
    for p in files:
        key = p.name
        if key in seen:
            continue
        seen.add(key)
        with p.open(encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
        kind = "bus" if p.name.startswith("bus_") else "metro" if p.name.startswith("metro_") else "unknown"
        if kind == "unknown":
            continue
        period = p.name.split("_")[1] + ".." + p.name.split("_")[2].replace(".csv", "")
        periods.add(period)
        free = _sum_col(rows, "freeCount")
        special = sum(1 for r in rows if (r.get("specialSituation") or "").strip())
        records.append({
            "file": str(p.relative_to(ROOT)).replace("\\", "/"),
            "kind": kind,
            "period": period,
            "rows": len(rows),
            "freeCount_sum": free,
            "contractCount_sum": _sum_col(rows, "contractCount"),
            "reservationCount_sum": _sum_col(rows, "reservationCount"),
            "specialSituation_count": special,
            "sha256": _sha256(p),
            "mtime": datetime.fromtimestamp(p.stat().st_mtime).astimezone().isoformat(timespec="seconds"),
        })
        if kind == "bus":
            bus_rows += len(rows)
        else:
            metro_rows += len(rows)

    h = hashlib.sha256()
    for r in sorted(records, key=lambda x: x["file"]):
        h.update((r["file"] + r["sha256"]).encode("utf-8"))
    for p in sorted(CONFIG.rglob("*.json")):
        h.update(p.read_bytes())
    data_version = h.hexdigest()[:12]

    OUT.mkdir(parents=True, exist_ok=True)
    manifest = {
        "version": 1,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source": "红豆广告媒体管理系统（比赛专用账号，只读 API）",
        "api": [
            "/admin-api/orders/media-inventory/bus/page",
            "/admin-api/orders/media-inventory/metro/page",
        ],
        "data_version": data_version,
        "periods": sorted(periods),
        "inventory_periods": sorted(periods),
        "files": records,
        "totals": {
            "bus_rows": bus_rows,
            "metro_rows": metro_rows,
            "files": len(records),
            "freeCount_sum": sum(r["freeCount_sum"] for r in records),
        },
        "notes": [
            "月度快照为查询区间聚合，不是逐日库存；跨月投放取 min_free。",
            "静态台账 free=2517 为 2026-11-13 快照，不可当作当前库存。",
            "地铁 specialSituation 非空的封闭/改造口必须剔除。",
            "本文件为 Lead 最小兜底；Agent-A 的完整 build_dataset 可覆盖。",
        ],
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[OK] data/processed/manifest.json data_version={data_version} files={len(records)} periods={sorted(periods)}")
    print(f"     bus_rows={bus_rows} metro_rows={metro_rows}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
