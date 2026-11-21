#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""构建 data/geo/poi_theme_park.csv / .geojson（构建期联网，运行期离线）。

POI 面向"乐园（主题公园）亲子家庭"人群聚点。类型见 data/config/poi_types.json。
坐标通过 OSM Photon 地埋编码所得，全部标记为 approx（近似），不做精确点位拟合。
不包含任何校内投放点位（仅可覆盖学校周边，此处不收录学校本体）。
"""
from __future__ import annotations

import csv
import json
import os
import ssl
import sys
import time
import urllib.parse
import urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GEO = os.path.join(BASE, "data", "geo")

_SSL = ssl.create_default_context()
_SSL.check_hostname = False
_SSL.verify_mode = ssl.CERT_NONE

TYPE_WEIGHT = {
    "science_museum_planetarium": 1.0,
    "museum": 0.9,
    "parent_child_mall": 1.0,
    "transport_hub": 0.9,
    "children_hospital_maternity": 0.7,
    "youth_palace": 0.8,
    "aquarium_indoor_play": 1.0,
    "large_residential": 0.6,
}

# (名称, 类型, 区) —— 名称与区为公开常识信息，坐标为 Photon 近似的值
POIS = [
    # 科技馆/天文馆
    ("上海科技馆", "science_museum_planetarium", "浦东新区"),
    ("上海自然博物馆", "science_museum_planetarium", "静安区"),
    ("上海天文馆", "science_museum_planetarium", "浦东新区"),
    ("上海儿童博物馆", "science_museum_planetarium", "长宁区"),
    ("上海铁路博物馆", "science_museum_planetarium", "静安区"),
    ("上海航运博物馆", "science_museum_planetarium", "浦东新区"),
    ("上海昆虫博物馆", "science_museum_planetarium", "徐汇区"),
    ("上海消防博物馆", "science_museum_planetarium", "长宁区"),
    # 博物馆
    ("上海博物馆", "museum", "黄浦区"),
    ("上海历史博物馆", "museum", "黄浦区"),
    ("上海城市规划展示馆", "museum", "黄浦区"),
    ("上海汽车博物馆", "museum", "嘉定区"),
    ("上海电影博物馆", "museum", "徐汇区"),
    ("中华艺术宫", "museum", "浦东新区"),
    ("上海当代艺术博物馆", "museum", "黄浦区"),
    ("上海松江博物馆", "museum", "松江区"),
    ("上海青浦博物馆", "museum", "青浦区"),
    ("上海玻璃博物馆", "museum", "宝山区"),
    ("上海纺织博物馆", "museum", "普陀区"),
    ("上海中医药博物馆", "museum", "浦东新区"),
    ("上海邮政博物馆", "museum", "虹口区"),
    ("上海犹太难民纪念馆", "museum", "虹口区"),
    ("上海动漫博物馆", "museum", "浦东新区"),
    # 亲子商场
    ("环球港", "parent_child_mall", "普陀区"),
    ("大悦城", "parent_child_mall", "静安区"),
    ("虹桥天地", "parent_child_mall", "闵行区"),
    ("正大广场", "parent_child_mall", "浦东新区"),
    ("环球金融中心商场", "parent_child_mall", "浦东新区"),
    ("仲盛世界商城", "parent_child_mall", "闵行区"),
    ("LCM置地旭辉广场", "parent_child_mall", "浦东新区"),
    ("七宝万科广场", "parent_child_mall", "闵行区"),
    ("南翔印象城", "parent_child_mall", "嘉定区"),
    ("宝山万达广场", "parent_child_mall", "宝山区"),
    ("松江万达广场", "parent_child_mall", "松江区"),
    ("周浦万达广场", "parent_child_mall", "浦东新区"),
    ("世纪汇广场", "parent_child_mall", "浦东新区"),
    ("五角场万达广场", "parent_child_mall", "杨浦区"),
    ("虹口龙之梦", "parent_child_mall", "虹口区"),
    ("中山公园龙之梦", "parent_child_mall", "长宁区"),
    ("徐家汇恒隆广场", "parent_child_mall", "徐汇区"),
    ("静安大悦城", "parent_child_mall", "静安区"),
    ("世纪公园商业区", "parent_child_mall", "浦东新区"),
    # 交通枢纽
    ("虹桥火车站", "transport_hub", "闵行区"),
    ("虹桥机场T2", "transport_hub", "闵行区"),
    ("上海南站", "transport_hub", "徐汇区"),
    ("上海火车站", "transport_hub", "静安区"),
    ("浦东国际机场", "transport_hub", "浦东新区"),
    ("龙阳路交通枢纽", "transport_hub", "浦东新区"),
    ("世纪大道站", "transport_hub", "浦东新区"),
    ("人民广场站", "transport_hub", "黄浦区"),
    ("徐家汇站", "transport_hub", "徐汇区"),
    ("静安寺站", "transport_hub", "静安区"),
    ("五角场站", "transport_hub", "杨浦区"),
    ("莘庄站", "transport_hub", "闵行区"),
    ("宜山路站", "transport_hub", "徐汇区"),
    ("东方体育中心站", "transport_hub", "浦东新区"),
    # 儿童医院/妇幼
    ("上海市儿童医院", "children_hospital_maternity", "静安区"),
    ("复旦大学附属儿科医院", "children_hospital_maternity", "闵行区"),
    ("上海儿童医学中心", "children_hospital_maternity", "浦东新区"),
    ("上海市第一妇婴保健院", "children_hospital_maternity", "浦东新区"),
    ("新华医院", "children_hospital_maternity", "杨浦区"),
    ("国际和平妇幼保健院", "children_hospital_maternity", "徐汇区"),
    ("红房子妇产科医院", "children_hospital_maternity", "杨浦区"),
    ("上海市第六人民医院", "children_hospital_maternity", "徐汇区"),
    ("复旦大学附属妇产科医院", "children_hospital_maternity", "徐汇区"),
    ("上海市儿童医院普陀新院", "children_hospital_maternity", "普陀区"),
    # 少年宫
    ("上海市少年宫", "youth_palace", "静安区"),
    ("上海市青少年活动中心", "youth_palace", "静安区"),
    ("中国福利会少年宫", "youth_palace", "长宁区"),
    ("浦东新区少年宫", "youth_palace", "浦东新区"),
    ("徐汇区青少年活动中心", "youth_palace", "徐汇区"),
    ("闵行区青少年活动中心", "youth_palace", "闵行区"),
    ("宝山区少年宫", "youth_palace", "宝山区"),
    ("杨浦区少年宫", "youth_palace", "杨浦区"),
    ("虹口区青少年活动中心", "youth_palace", "虹口区"),
    ("普陀区少年宫", "youth_palace", "普陀区"),
    # 水族馆/室内乐园
    ("上海海洋水族馆", "aquarium_indoor_play", "浦东新区"),
    ("长风海洋世界", "aquarium_indoor_play", "普陀区"),
    ("上海海昌海洋公园", "aquarium_indoor_play", "浦东新区"),
    ("杜莎夫人蜡像馆", "aquarium_indoor_play", "黄浦区"),
    ("上海乐高探索中心", "aquarium_indoor_play", "普陀区"),
    ("宝燕乐园", "aquarium_indoor_play", "闵行区"),
    ("上海欢乐谷", "aquarium_indoor_play", "松江区"),
    ("锦江乐园", "aquarium_indoor_play", "徐汇区"),
    ("上海水族馆", "aquarium_indoor_play", "浦东新区"),
    ("迪士尼小镇", "aquarium_indoor_play", "浦东新区"),
    ("东方绿舟", "aquarium_indoor_play", "青浦区"),
    # 大型住宅/亲子社区
    ("联洋社区", "large_residential", "浦东新区"),
    ("碧云国际社区", "large_residential", "浦东新区"),
    ("古北社区", "large_residential", "长宁区"),
    ("大华社区", "large_residential", "宝山区"),
    ("莘庄社区", "large_residential", "闵行区"),
    ("顾村公园区域", "large_residential", "宝山区"),
    ("三林社区", "large_residential", "浦东新区"),
    ("金桥社区", "large_residential", "浦东新区"),
    ("周浦社区", "large_residential", "浦东新区"),
    ("临港新城社区", "large_residential", "浦东新区"),
    ("七宝社区", "large_residential", "闵行区"),
    ("南翔社区", "large_residential", "嘉定区"),
    ("川沙社区", "large_residential", "浦东新区"),
    ("松江新城", "large_residential", "松江区"),
    ("嘉定新城", "large_residential", "嘉定区"),
    ("青浦新城", "large_residential", "青浦区"),
]


def geocode(name: str):
    """Photon 地理编码，返回 (lng, lat) 或 None。站名+区后缀提高命中。"""
    for query in [name, name + " 上海"]:
        q = urllib.parse.quote(query)
        url = f"https://photon.komoot.io/api/?q={q}&limit=2"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "AIPlusWork-geo/1.0"})
            d = json.loads(urllib.request.urlopen(req, timeout=20).read())
            feats = d.get("features", [])
            for f in feats:
                c = f.get("geometry", {}).get("coordinates")
                if c:
                    return round(c[0], 6), round(c[1], 6)
        except Exception:
            continue
    return None


def load_district_centroids():
    out = {}
    d = json.load(open(os.path.join(GEO, "shanghai_districts.geojson"), encoding="utf-8"))
    for f in d.get("features", []):
        name = f["properties"]["name"]
        center = f["properties"].get("center") or f["properties"].get("centroid")
        if center and len(center) == 2:
            out[name] = (center[0], center[1])
    # 市中心兜底
    out["_fallback"] = (121.472644, 31.231706)
    return out


def main() -> int:
    district_centroids = load_district_centroids()
    out = []
    failed = []
    for name, ptype, district in POIS:
        coords = geocode(name)
        weight = TYPE_WEIGHT[ptype]
        if coords is None:
            coords = district_centroids.get(district) or district_centroids["_fallback"]
            failed.append(name)
        out.append({
            "id": f"poi_{len(out):03d}",
            "name": name,
            "type": ptype,
            "lng": coords[0],
            "lat": coords[1],
            "district": district,
            "source": "OSM Photon geocode (approx)" if name not in failed else "district centroid fallback",
            "confidence": "approx" if name not in failed else "low",
            "weight": weight,
            "notes": "公共信息近似坐标，非精确点位" if name not in failed else "区县质心兜底，精确度低",
        })
        time.sleep(0.3)

    # 写 CSV
    csv_path = os.path.join(GEO, "poi_theme_park.csv")
    fieldnames = ["id", "name", "type", "lng", "lat", "district", "source", "confidence", "weight", "notes"]
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(out)

    # 写 GeoJSON
    geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "id": r["id"],
                "geometry": {"type": "Point", "coordinates": [r["lng"], r["lat"]]} if r["lng"] else None,
                "properties": {k: r[k] for k in r if k not in ("lng", "lat")},
            }
            for r in out
        ],
    }
    with open(os.path.join(GEO, "poi_theme_park.geojson"), "w", encoding="utf-8") as f:
        json.dump(geojson, f, ensure_ascii=False, indent=1)

    n_ok = sum(1 for r in out if r["lng"])
    print(f"POI 总数 {len(out)}，成功编码 {n_ok}，失败 {len(failed)}")
    if failed:
        print("失败（low/空坐标）：")
        for n in failed:
            print("   -", n.encode("unicode_escape").decode())
    return 0


if __name__ == "__main__":
    sys.exit(main())
