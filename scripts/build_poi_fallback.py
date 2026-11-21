#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""POI 兜底生成器：红豆地铁站 categoryTags + 公开站点坐标 + 精选亲子地标。

不依赖外网；输出 data/geo/poi_fallback.geojson / .csv。
用于 Agent-A 的 POI 尚未就绪时的兜底；不覆盖 poi_theme_park.geojson。
"""
from __future__ import annotations

import csv
import json
import math
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
GEO = ROOT / "data" / "geo"
SNAP = ROOT / "data" / "snapshots"

DISTRICT = {
    "[1]": "黄浦区", "[2]": "徐汇区", "[3]": "长宁区", "[4]": "静安区",
    "[5]": "普陀区", "[6]": "虹口区", "[7]": "杨浦区", "[8]": "闵行区",
    "[9]": "宝山区", "[10]": "嘉定区", "[11]": "浦东新区", "[12]": "金山区",
    "[13]": "松江区", "[14]": "青浦区", "[15]": "奉贤区", "[16]": "崇明区",
    "[17]": "浦东新区", "[18]": "浦东新区", "[19]": "浦东新区", "[20]": "浦东新区",
    "[21]": "闵行区", "[22]": "宝山区",
}

# 类型权重（与 venue profile 的 poi_type_weights 对齐）
TYPE_WEIGHT = {
    "parent_child_mall": 1.0,
    "large_residential": 0.6,
    "transport_hub": 0.9,
    "science_museum_planetarium": 1.0,
    "museum": 0.9,
    "aquarium_indoor_play": 1.0,
    "youth_palace": 0.8,
    "children_hospital_maternity": 0.7,
    "attraction": 1.0,
    "destination": 1.0,
}

# 精选亲子地标（公开近似坐标，WGS84；仅用于规划，不用于测量）
CURATED: List[Dict[str, Any]] = [
    ("上海科技馆", "science_museum_planetarium", 121.544, 31.221, "浦东新区"),
    ("上海自然博物馆", "science_museum_planetarium", 121.461, 31.236, "静安区"),
    ("上海天文馆", "science_museum_planetarium", 121.929, 30.912, "浦东新区"),
    ("上海博物馆", "museum", 121.476, 31.228, "黄浦区"),
    ("上海海洋水族馆", "aquarium_indoor_play", 121.509, 31.240, "浦东新区"),
    ("上海野生动物园", "attraction", 121.834, 31.056, "浦东新区"),
    ("上海迪士尼度假区", "destination", 121.657, 31.144, "浦东新区"),
    ("上海乐高乐园度假区", "destination", 121.104, 30.880, "金山区"),
    ("上海海昌海洋公园", "destination", 121.903, 30.894, "浦东新区"),
    ("上海欢乐谷", "attraction", 121.216, 31.097, "松江区"),
    ("东方明珠", "attraction", 121.499, 31.239, "浦东新区"),
    ("上海中心", "attraction", 121.505, 31.233, "浦东新区"),
    ("金茂大厦", "attraction", 121.505, 31.235, "浦东新区"),
    ("环球金融中心", "attraction", 121.506, 31.234, "浦东新区"),
    ("正大广场", "parent_child_mall", 121.501, 31.238, "浦东新区"),
    ("国金中心", "parent_child_mall", 121.505, 31.238, "浦东新区"),
    ("港汇恒隆广场", "parent_child_mall", 121.437, 31.195, "徐汇区"),
    ("美罗城", "parent_child_mall", 121.437, 31.194, "徐汇区"),
    ("静安嘉里中心", "parent_child_mall", 121.445, 31.224, "静安区"),
    ("久光百货", "parent_child_mall", 121.445, 31.223, "静安区"),
    ("环球港", "parent_child_mall", 121.412, 31.236, "普陀区"),
    ("中山公园龙之梦", "parent_child_mall", 121.419, 31.220, "长宁区"),
    ("五角场万达", "parent_child_mall", 121.514, 31.303, "杨浦区"),
    ("合生汇", "parent_child_mall", 121.515, 31.306, "杨浦区"),
    ("大宁国际", "parent_child_mall", 121.455, 31.276, "静安区"),
    ("虹桥天地", "parent_child_mall", 121.318, 31.197, "闵行区"),
    ("前滩太古里", "parent_child_mall", 121.480, 31.150, "浦东新区"),
    ("上海南站", "transport_hub", 121.429, 31.154, "徐汇区"),
    ("虹桥火车站", "transport_hub", 121.327, 31.200, "闵行区"),
    ("人民广场", "transport_hub", 121.475, 31.232, "黄浦区"),
    ("陆家嘴", "transport_hub", 121.506, 31.239, "浦东新区"),
    ("徐家汇", "transport_hub", 121.437, 31.195, "徐汇区"),
    ("静安寺", "transport_hub", 121.445, 31.223, "静安区"),
    ("上海动物园", "attraction", 121.364, 31.195, "长宁区"),
    ("上海植物园", "attraction", 121.450, 31.150, "徐汇区"),
    ("共青森林公园", "attraction", 121.550, 31.320, "杨浦区"),
    ("世纪公园", "attraction", 121.550, 31.220, "浦东新区"),
    ("顾村公园", "attraction", 121.390, 31.340, "宝山区"),
    ("召稼楼古镇", "attraction", 121.550, 31.050, "闵行区"),
    ("新场古镇", "attraction", 121.650, 31.030, "浦东新区"),
    ("七宝老街", "attraction", 121.350, 31.150, "闵行区"),
    ("南翔古镇", "attraction", 121.310, 31.300, "嘉定区"),
    ("朱家角古镇", "attraction", 121.050, 31.100, "青浦区"),
    ("上海影视乐园", "attraction", 121.290, 31.000, "松江区"),
    ("辰山植物园", "attraction", 121.180, 31.080, "松江区"),
    ("广富林文化遗址", "museum", 121.200, 31.050, "松江区"),
    ("上海玻璃博物馆", "museum", 121.490, 31.330, "宝山区"),
    ("上海汽车博物馆", "museum", 121.170, 31.320, "嘉定区"),
    ("上海儿童博物馆", "museum", 121.420, 31.200, "长宁区"),
    ("上海马戏城", "attraction", 121.460, 31.280, "静安区"),
    ("梅赛德斯奔驰文化中心", "attraction", 121.490, 31.190, "浦东新区"),
    ("东方体育中心", "attraction", 121.480, 31.160, "浦东新区"),
    ("复旦大学附属儿科医院", "children_hospital_maternity", 121.399, 31.162, "闵行区"),
    ("上海儿童医学中心", "children_hospital_maternity", 121.527, 31.207, "浦东新区"),
    ("上海市儿童医院", "children_hospital_maternity", 121.443, 31.230, "静安区"),
    ("国际和平妇幼保健院", "children_hospital_maternity", 121.443, 31.190, "徐汇区"),
    ("中福会少年宫", "youth_palace", 121.455, 31.230, "静安区"),
    ("上海市青少年活动中心", "youth_palace", 121.455, 31.240, "静安区"),
]


def _load_stations() -> Dict[str, Dict[str, Any]]:
    p = GEO / "_shmetro_stations_by_name.json"
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def _load_metro_tags() -> Dict[str, Dict[str, str]]:
    files = sorted(SNAP.glob("metro_2027-07-*.csv")) or sorted(SNAP.glob("metro_*.csv"))
    if not files:
        return {}
    out: Dict[str, Dict[str, str]] = {}
    with files[0].open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            name = (row.get("lineName") or "").strip()
            if not name:
                continue
            out.setdefault(name, {
                "business": (row.get("businessAreaName") or "").strip(),
                "tags": (row.get("categoryTags") or "").strip(),
                "district": DISTRICT.get((row.get("districtname") or "").strip(), "浦东新区"),
            })
    return out


def _type_from_tags(tags: str) -> str | None:
    if "交通枢纽" in tags:
        return "transport_hub"
    if "商业" in tags:
        return "parent_child_mall"
    if "住宅" in tags:
        return "large_residential"
    if "会展" in tags or "文化" in tags:
        return "museum"
    if "办公" in tags:
        return None
    return None


def _haversine_km(a: Dict[str, float], b: Dict[str, float]) -> float:
    r = 6371.0
    dlat = math.radians(b["lat"] - a["lat"])
    dlng = math.radians(b["lng"] - a["lng"])
    la1, la2 = math.radians(a["lat"]), math.radians(b["lat"])
    h = math.sin(dlat / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin(dlng / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def main() -> int:
    stations = _load_stations()
    tags = _load_metro_tags()
    pois: List[Dict[str, Any]] = []
    seen = set()

    def add(name: str, typ: str, lng: float, lat: float, district: str, source: str, confidence: str = "approx") -> None:
        key = (round(lng, 3), round(lat, 3), typ)
        if key in seen:
            return
        seen.add(key)
        pois.append({
            "id": f"poi:{len(pois)+1:04d}",
            "name": name,
            "type": typ,
            "lng": round(lng, 6),
            "lat": round(lat, 6),
            "district": district,
            "weight": TYPE_WEIGHT.get(typ, 0.6),
            "source": source,
            "confidence": confidence,
        })

    # 1) 精选亲子地标
    for name, typ, lng, lat, district in CURATED:
        add(name, typ, lng, lat, district, "公开信息近似坐标")

    # 2) 红豆地铁站 + categoryTags（提供的数据）
    for station, meta in sorted(tags.items()):
        s = stations.get(station)
        if not s:
            continue
        typ = _type_from_tags(meta.get("tags", ""))
        if not typ:
            continue
        try:
            lng, lat = float(s["LNG"]), float(s["LAT"])
        except Exception:
            continue
        label = meta.get("business") or station
        add(label, typ, lng, lat, meta.get("district") or "浦东新区", "红豆 categoryTags + 公开站点坐标", "approx")

    # 3) 若不足 112，用剩余地铁站补足为 large_residential（低权重，来源明确）
    if len(pois) < 112:
        for station, s in sorted(stations.items()):
            if len(pois) >= 112:
                break
            try:
                lng, lat = float(s["LNG"]), float(s["LAT"])
            except Exception:
                continue
            meta = tags.get(station, {})
            add(meta.get("business") or station, "large_residential", lng, lat,
                meta.get("district") or "浦东新区", "公开站点坐标（社区代理）", "low")

    # GeoJSON
    geo = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {k: v for k, v in p.items() if k not in ("lng", "lat")},
                "geometry": {"type": "Point", "coordinates": [p["lng"], p["lat"]]},
            }
            for p in pois
        ],
        "metadata": {
            "source": "红豆地铁 categoryTags + 公开站点/地标近似坐标",
            "count": len(pois),
            "note": "仅用于规划近似，不用于测量级结论；不投校内。",
        },
    }
    GEO.mkdir(parents=True, exist_ok=True)
    (GEO / "poi_fallback.geojson").write_text(json.dumps(geo, ensure_ascii=False, indent=1), encoding="utf-8")
    with (GEO / "poi_fallback.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["id", "name", "type", "lng", "lat", "district", "weight", "source", "confidence"])
        writer.writeheader()
        writer.writerows(pois)

    from collections import Counter
    print(f"[OK] POI fallback: {len(pois)} -> data/geo/poi_fallback.geojson")
    print("types:", dict(Counter(p["type"] for p in pois)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
