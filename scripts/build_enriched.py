#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""富化并导出地理候选层（构建期联网需已在前面完成；此脚本纯离线）。

输入：
  - data/processed/candidates.json  （build_dataset.py 产物）
  - data/geo/metro_stations.json     （站点坐标）
  - data/geo/poi_theme_park.csv      （POI）
  - data/config/venues/*.json        （场馆坐标）

输出：
  - data/processed/candidates_enriched.json  （每个候选增加 geo 特征）
  - data/processed/candidates.geo.json      （前端地图合并层）

geo 富化（公交候选）：
  - 运营公司 -> 区域代理（COMPANY_REGION 映射），无几何则标 schematic
  - 距离场馆：公交无几何线，用公司区域代理，距离字段为 None（schematic）
geo 富化（地铁候选）：
  - 站点坐标（来自 metro_stations.json）
  - 距离场馆（Haversine）
  - POI 命中（800m 内）
  - categoryTags / stationAttr 换乘线
"""
from __future__ import annotations

import csv
import json
import math
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROC = os.path.join(BASE, "data", "processed")
GEO = os.path.join(BASE, "data", "geo")
CONFIG = os.path.join(BASE, "data", "config")
VENUES = os.path.join(CONFIG, "venues")

# 公交运营公司 -> 大致运营区域（近似，用于无几何时的区域代理）
COMPANY_REGION = {
    "巴士一公司": "杨浦/虹口",
    "巴士二公司": "徐汇/闵行",
    "巴士三公司": "普陀/长宁",
    "巴士四公司": "静安/黄浦",
    "巴士五公司": "宝山/嘉定",
    "南汇公交": "浦东/南汇",
    "金高公交": "浦东/金桥",
    "上南公交": "浦东/上南",
    "杨高公交": "浦东/杨高",
    "巴士旅游": "全市/旅游专线",
    "春秋国旅": "全市/旅游专线",
}

BUS_POI_RADIUS_M = 500
METRO_POI_RADIUS_M = 800


def haversine(lng1, lat1, lng2, lat2):
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def load_pois():
    p = os.path.join(GEO, "poi_theme_park.csv")
    if not os.path.exists(p):
        return []
    rows = list(csv.DictReader(open(p, encoding="utf-8-sig")))
    out = []
    for r in rows:
        try:
            lng = float(r["lng"]); lat = float(r["lat"])
        except (TypeError, ValueError):
            continue
        out.append({"name": r["name"], "type": r["type"], "lng": lng, "lat": lat,
                    "district": r["district"], "weights": float(r.get("weight") or 1.0)})
    return out


def load_venues():
    out = []
    if not os.path.isdir(VENUES):
        return out
    for f in sorted(os.listdir(VENUES)):
        if f.endswith(".json"):
            d = json.load(open(os.path.join(VENUES, f), encoding="utf-8"))
            c = d.get("coords") or {}
            out.append({"id": d["id"], "name": d["name"], "district": d.get("district"),
                        "lng": c.get("lng"), "lat": c.get("lat")})
    return out


def poi_hits(lng, lat, pois, radius_m):
    hits = []
    for p in pois:
        d = haversine(lng, lat, p["lng"], p["lat"])
        if d <= radius_m:
            hits.append({"name": p["name"], "type": p["type"], "distance_m": round(d)})
    return hits


def main() -> int:
    candidates = json.load(open(os.path.join(PROC, "candidates.json"), encoding="utf-8"))
    pois = load_pois()
    venues = load_venues()

    enriched = []
    for c in candidates:
        e = dict(c)
        if c["type"] == "metro":
            # 站点坐标已在 candidates 中
            lng, lat = c.get("lng"), c.get("lat")
            if lng is not None and lat is not None:
                # 距离各场馆
                e["distances_to_venues_m"] = {}
                for v in venues:
                    if v.get("lng") is not None:
                        e["distances_to_venues_m"][v["id"]] = round(haversine(lng, lat, v["lng"], v["lat"]))
                e["poi_hits_800m"] = poi_hits(lng, lat, pois, METRO_POI_RADIUS_M)
                e["schematic"] = False
            else:
                e["schematic"] = True
                e["distances_to_venues_m"] = {}
                e["poi_hits_800m"] = []
            # 换乘线 / 类别标签已在 candidates 中（stationAttr / categoryTags）
        else:
            # bus：无几何，用公司区域代理
            company = c.get("companyName") or ""
            e["region_proxy"] = COMPANY_REGION.get(company, "未知")
            e["schematic"] = True
            e["distances_to_venues_m"] = None
            e["poi_hits_500m"] = None
        enriched.append(e)

    with open(os.path.join(PROC, "candidates_enriched.json"), "w", encoding="utf-8") as f:
        json.dump(enriched, f, ensure_ascii=False, indent=1)

    # ---- 前端地图合并层 candidates.geo.json ----
    geo = {
        "type": "FeatureCollection",
        "generated_ts": None,
        "layers": {
            "venues": [],
            "pois": [],
            "metro": [],
            "bus": [],
        },
    }
    for v in venues:
        geo["layers"]["venues"].append({
            "id": v["id"], "name": v["name"], "district": v["district"],
            "lng": v.get("lng"), "lat": v.get("lat"),
            "coords": [v.get("lng"), v.get("lat")],
        })
    # POI（从 csv 读，避免重复 parse）
    for p in pois:
        geo["layers"]["pois"].append({
            "name": p["name"], "type": p["type"], "district": p["district"],
            "lng": p["lng"], "lat": p["lat"], "coord": [p["lng"], p["lat"]],
        })
    for c in candidates:
        if c["type"] == "metro":
            geo["layers"]["metro"].append({
                "business_key": c["business_key"], "lineName": c["lineName"],
                "exitName": c.get("exitName"), "level": c["level"],
                "min_free": c["min_free"],
                "stationAttr": c.get("stationAttr"), "categoryTags": c.get("categoryTags"),
                "lng": c.get("lng"), "lat": c.get("lat"),
                "coord_confidence": c.get("coord_confidence"),
            })
        else:
            geo["layers"]["bus"].append({
                "business_key": c["business_key"], "lineName": c["lineName"],
                "mediaName": c.get("mediaName"), "level": c["level"],
                "min_free": c["min_free"], "companyName": c.get("companyName"),
                "schematic": True,
                "lng": None, "lat": None,
            })
    # 计数统计
    geo["layer_counts"] = {
        "venues": len(geo["layers"]["venues"]),
        "pois": len(geo["layers"]["pois"]),
        "metro": len(geo["layers"]["metro"]),
        "bus": len(geo["layers"]["bus"]),
    }

    with open(os.path.join(PROC, "candidates.geo.json"), "w", encoding="utf-8") as f:
        json.dump(geo, f, ensure_ascii=False, indent=1)

    print(f"candidates_enriched: {len(enriched)} 条")
    print(f"candidates.geo.json 图层: {json.dumps(geo['layer_counts'], ensure_ascii=False)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
