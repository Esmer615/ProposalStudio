#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""构建 data/processed/ 下的数据资产（inventory.json / candidates.json / manifest.json）。

输入：
  - data/snapshots/*.csv（2027-06..10 各月 bus/metro 快照）
  - data/*.csv（2027-01 已归档快照，不覆盖）
  - data/config/rate_card_2027.json（等级映射与刊例）
  - data/geo/metro_stations.json（站点坐标，富化用）

处理步骤：
  1. 去重：bus 按 (lineName, mediaName)；metro 按 (lineName, exitName)
  2. 等级映射：bus 1=S,2=A++,3=A+,5=AA,6=unknown(排除/标记)；metro 2=A++/3=A+ 为假设
  3. 过滤：freeCount<=0 剔除；metro specialSituation 非空（封闭/改造）剔除；未知等级标记
  4. 跨月 min_free：同一业务键在覆盖月份取 min(freeCount)，不求和
  5. 富化：地铁站点坐标、区县、商圈、类别标签；公交公司区域
  6. 输出 manifest / inventory / candidates / candidates.geo.json / candidates_enriched.json

用法：
    PYTHONIOENCODING=utf-8 python scripts/build_dataset.py
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SNAP = os.path.join(BASE, "data", "snapshots")
DATA = os.path.join(BASE, "data")
PROC = os.path.join(BASE, "data", "processed")
CONFIG = os.path.join(BASE, "data", "config")
GEO = os.path.join(BASE, "data", "geo")

BUS_LEVEL = {"1": "S", "2": "A++", "3": "A+", "5": "AA"}
METRO_LEVEL = {"2": "A++", "3": "A+"}   # 假设：地铁 2=A++/3=A+，见任务说明
LEVEL_UNKNOWN = "unknown"
LEVEL_CODE_METRO_ASSUMPTION = True  # 地铁 lineLevel 2/3 映射为假设

# 地铁 specialSituation 需要剔除的关键词
SPECIAL_BLOCKED = ["封闭", "改造", "施工", "停用", "停运"]


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def file_mtime(path: str) -> str:
    try:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(os.path.getmtime(path)))
    except OSError:
        return ""


def parse_month_from_name(fname: str):
    m = re.search(r"(\d{4}-\d{2}-\d{2})_(\d{4}-\d{2}-\d{2})", fname)
    if m:
        return m.group(1), m.group(2)
    return None, None


def list_source_files() -> list[dict]:
    out = []
    # snapshots
    for f in sorted(os.listdir(SNAP)):
        if f.endswith(".csv"):
            p = os.path.join(SNAP, f)
            media = "bus" if f.startswith("bus_") else "metro" if f.startswith("metro_") else "unknown"
            start, end = parse_month_from_name(f)
            out.append({"path": p, "media": media, "start": start, "end": end,
                        "sha256": sha256_file(p), "mtime": file_mtime(p)})
    # existing data/*.csv (2027-01 archive)
    for f in sorted(os.listdir(DATA)):
        if f.endswith(".csv") and f not in ("",):
            p = os.path.join(DATA, f)
            start, end = parse_month_from_name(f)
            if start is None:
                continue
            media = "bus" if f.startswith("bus_") else "metro" if f.startswith("metro_") else "unknown"
            # 只把 2027-01 归档当作审计回退，不重复进 snapshots
            out.append({"path": p, "media": media, "start": start, "end": end,
                        "sha256": sha256_file(p), "mtime": file_mtime(p)})
    return out


def load_csv(path: str) -> list[dict]:
    rows = list(csv.DictReader(open(path, encoding="utf-8-sig")))
    return rows


def dedupe(rows: list[dict], media: str) -> tuple[list[dict], int]:
    seen = set()
    out = []
    dup = 0
    for r in rows:
        if media == "bus":
            key = (r.get("lineName"), r.get("mediaName"))
        else:
            key = (r.get("lineName"), r.get("exitName"))
        if key in seen:
            dup += 1
            continue
        seen.add(key)
        out.append(r)
    return out, dup


def map_level(media: str, line_level) -> str:
    code = str(line_level).strip() if line_level is not None else ""
    if media == "bus":
        return BUS_LEVEL.get(code, LEVEL_UNKNOWN)
    return METRO_LEVEL.get(code, LEVEL_UNKNOWN)


def parse_district_names(districtname: str) -> list[str]:
    # districtname 形如 "[2]" 或 "[2, 11]"（编码数组，含义未确认）——保留原文并标记
    if not districtname:
        return []
    s = districtname.strip().strip("[]")
    if not s:
        return []
    return [x.strip() for x in s.split(",")]


def load_metro_coords() -> dict:
    p = os.path.join(GEO, "metro_stations.json")
    if not os.path.exists(p):
        return {}
    d = json.load(open(p, encoding="utf-8"))
    out = {}
    # 兼容两种结构：平铺字典（站名->record）或 {"stations": {...}}
    items = d.get("stations", d) if isinstance(d.get("stations"), dict) else d
    for name, v in items.items():
        if not isinstance(v, dict) or name == "_meta":
            continue
        if v.get("lng") is not None:
            out[name] = {"lng": v["lng"], "lat": v["lat"], "confidence": v.get("confidence")}
    return out


def build_inventory() -> tuple[list[dict], dict]:
    """逐月读快照，输出去重/过滤后的 inventory 记录，并返回过滤统计。"""
    files = [f for f in list_source_files() if f["start"] is not None]
    # 仅 2027-06..10 的 snapshots + 2027-01 归档，全部纳入
    inventory = []
    stats = {"files": 0, "raw_rows": 0, "dup_rows": 0, "filter_free": 0,
             "filter_special": 0, "unknown_level": 0, "kept_rows": 0}

    metro_coords = load_metro_coords()

    for f in files:
        media = f["media"]
        if media not in ("bus", "metro"):
            continue
        rows = load_csv(f["path"])
        stats["files"] += 1
        stats["raw_rows"] += len(rows)
        rows, dup = dedupe(rows, media)
        stats["dup_rows"] += dup

        start, end = f["start"], f["end"]
        month = start[:7]  # YYYY-MM

        for r in rows:
            # 等级
            level = map_level(media, r.get("lineLevel"))
            free = int(r.get("freeCount") or 0)

            # 过滤 free<=0
            if free <= 0:
                stats["filter_free"] += 1
                continue

            # 地铁 specialSituation 过滤
            special = (r.get("specialSituation") or "").strip()
            if media == "metro" and special and any(k in special for k in SPECIAL_BLOCKED):
                stats["filter_special"] += 1
                continue

            if level == LEVEL_UNKNOWN:
                stats["unknown_level"] += 1

            if media == "bus":
                business_key = r.get("lineName") or ""
                exit_name = None
                media_name = r.get("mediaName") or ""
            else:
                business_key = f"{r.get('lineName')}|{r.get('exitName')}"
                exit_name = r.get("exitName") or ""
                media_name = None

            rec = {
                "month": month,
                "type": media,
                "business_key": business_key,
                "lineName": r.get("lineName") or "",
                "exitName": exit_name,
                "mediaName": media_name,
                "level": level,
                "level_code": str(r.get("lineLevel") or ""),
                "free": free,
                "totalCount": int(r.get("totalCount") or 0),
                "contractCount": int(r.get("contractCount") or 0),
                "reservationCount": int(r.get("reservationCount") or 0),
                "source_file": os.path.basename(f["path"]),
            }

            if media == "bus":
                rec["companyName"] = r.get("companyName") or ""
            else:
                rec["stationAttr"] = r.get("stationAttr") or ""
                rec["businessAreaName"] = r.get("businessAreaName") or ""
                rec["categoryTags"] = r.get("categoryTags") or ""
                rec["districtname_raw"] = r.get("districtname") or ""
                rec["district"] = None  # 编码含义未确认，置空并标记
                special_nonempty = special if special and not any(k in special for k in SPECIAL_BLOCKED) else ""
                rec["specialSituation"] = special_nonempty
                # 坐标富化
                coord = metro_coords.get(r.get("lineName"))
                if coord:
                    rec["lng"] = coord["lng"]
                    rec["lat"] = coord["lat"]
                    rec["coord_confidence"] = coord["confidence"]
                else:
                    rec["lng"] = None
                    rec["lat"] = None
                    rec["coord_confidence"] = "low"

            inventory.append(rec)
            stats["kept_rows"] += 1

    return inventory, stats


def build_candidates(inventory: list[dict]) -> list[dict]:
    """按业务键聚合，跨月取 min_free（不求和）。"""
    by_key = {}
    for r in inventory:
        k = r["business_key"]
        if k not in by_key:
            by_key[k] = {
                "business_key": k,
                "type": r["type"],
                "lineName": r["lineName"],
                "exitName": r.get("exitName"),
                "mediaName": r.get("mediaName"),
                "level": r["level"],
                "level_code": r["level_code"],
                "months": [],
                "min_free": None,
            }
        c = by_key[k]
        c["months"].append(r["month"])
        if c["min_free"] is None or r["free"] < c["min_free"]:
            c["min_free"] = r["free"]

    candidates = []
    for k, c in by_key.items():
        # 保留富化字段（取第一条有坐标的）
        ref = next((r for r in inventory if r["business_key"] == k), {})
        c["district"] = ref.get("district")
        c["districtname_raw"] = ref.get("districtname_raw")
        c["businessAreaName"] = ref.get("businessAreaName")
        c["categoryTags"] = ref.get("categoryTags")
        c["stationAttr"] = ref.get("stationAttr")
        c["companyName"] = ref.get("companyName")
        c["lng"] = ref.get("lng")
        c["lat"] = ref.get("lat")
        c["coord_confidence"] = ref.get("coord_confidence")
        c["totalCount"] = ref.get("totalCount")
        c["contractCount"] = ref.get("contractCount")
        c["reservationCount"] = ref.get("reservationCount")
        c["months"] = sorted(set(c["months"]))
        c["specialSituation"] = ref.get("specialSituation", "")
        candidates.append(c)

    return candidates


def build_manifest(inventory: list[dict], stats: dict, candidates: list[dict]) -> dict:
    files = list_source_files()
    # 计算 data_version：manifest 主体内容 + 配置文件的 sha256
    config_files = [
        os.path.join(CONFIG, "rate_card_2027.json"),
        os.path.join(CONFIG, "schedule_rules.json"),
        os.path.join(CONFIG, "poi_types.json"),
        os.path.join(CONFIG, "venues", "lego_shanghai.json"),
        os.path.join(CONFIG, "venues", "disney_shanghai.json"),
        os.path.join(CONFIG, "venues", "haichang_shanghai.json"),
        os.path.join(BASE, "scripts", "build_dataset.py"),
    ]
    content = {
        "files": [{"path": os.path.basename(f["path"]), "sha256": f["sha256"],
                   "media": f["media"], "start": f["start"], "end": f["end"]} for f in files],
        "stats": stats,
        "candidate_count": len(candidates),
        "config_sha": {os.path.basename(p): sha256_file(p) if os.path.exists(p) else "missing"
                       for p in config_files},
    }
    payload = json.dumps(content, sort_keys=True, ensure_ascii=False)
    data_version = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]

    # 每月行数/free 汇总
    monthly = {}
    for r in inventory:
        m = r["month"]
        if m not in monthly:
            monthly[m] = {"bus": {"rows": 0, "free": 0}, "metro": {"rows": 0, "free": 0}}
        monthly[m][r["type"]]["rows"] += 1
        monthly[m][r["type"]]["free"] += r["free"]

    manifest = {
        "data_version": data_version,
        "inventory_period": "2027-06/2027-07/2027-08/2027-09/2027-10（+2027-01 审计回退）",
        "inventory_ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source_system": "红豆广告媒体管理系统（比赛专用账号）",
        "api_paths": {
            "bus": "/admin-api/orders/media-inventory/bus/page",
            "metro": "/admin-api/orders/media-inventory/metro/page",
        },
        "assumptions": [
            "地铁 lineLevel 2=A++/3=A+ 为假设（源文档未给出地铁等级语义）",
            "地铁 districtname 为编码数组，含义未确认，未映射为区名",
            "跨月方案可用量取覆盖月份 min(freeCount)，不求和",
            "公交线路线形为示意图（schematic），未匹配真实轨迹",
        ],
        "files": content["files"],
        "stats": stats,
        "monthly": monthly,
        "config_sha": content["config_sha"],
    }
    return manifest


def main() -> int:
    os.makedirs(PROC, exist_ok=True)

    inventory, stats = build_inventory()
    candidates = build_candidates(inventory)

    manifest = build_manifest(inventory, stats, candidates)

    # 写 inventory.json
    with open(os.path.join(PROC, "inventory.json"), "w", encoding="utf-8") as f:
        json.dump(inventory, f, ensure_ascii=False, indent=1)

    # 写 candidates.json
    with open(os.path.join(PROC, "candidates.json"), "w", encoding="utf-8") as f:
        json.dump(candidates, f, ensure_ascii=False, indent=1)

    # 写 manifest.json
    with open(os.path.join(PROC, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)

    print(f"inventory records: {len(inventory)}")
    print(f"candidates records: {len(candidates)}")
    print(f"data_version: {manifest['data_version']}")
    print(f"stats: {json.dumps(stats, ensure_ascii=False)}")
    print("monthly:")
    for m, v in sorted(manifest["monthly"].items()):
        print(f"  {m}: bus {v['bus']['rows']}rows/{v['bus']['free']}free, metro {v['metro']['rows']}rows/{v['metro']['free']}free")
    return 0


if __name__ == "__main__":
    sys.exit(main())
