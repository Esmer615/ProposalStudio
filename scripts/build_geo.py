#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""构建 data/geo/ 下的地理资产（构建期联网，运行期离线）。

- metro_stations.json：从红豆地铁快照取 274 个去重站名，依次匹配：
  1) 公开数据集 SHMetro (YutingHan/SHMetro, MIT) —— 站名 -> 经纬度 (WGS84)
  2) OSM Photon 地理编码（仅对未命中站名，带限速）
  3) 兜底：按 businessAreaName/区县质心 (confidence=low)
- 输出包含匹配率统计与每条记录的 confidence 标记。

用法：
    PYTHONIOENCODING=utf-8 python scripts/build_geo.py
"""
from __future__ import annotations

import csv
import json
import os
import re
import ssl
import sys
import time
import urllib.parse
import urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GEO = os.path.join(BASE, "data", "geo")
SNAP = os.path.join(BASE, "data", "snapshots")

REF_FILE = os.path.join(GEO, "_shmetro_stations_by_name.json")
DISTRICT_CENTROIDS_FILE = os.path.join(GEO, "shanghai_districts.geojson")

_SSL = ssl.create_default_context()
_SSL.check_hostname = False
_SSL.verify_mode = ssl.CERT_NONE


def photon_geocode(name: str, retries: int = 2):
    """OSM Photon 地理编码，返回 [lng, lat] 或 None。"""
    q = urllib.parse.quote(name)
    url = f"https://photon.komoot.io/api/?q={q}&limit=3"
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "AIPlusWork-geo/1.0"})
            d = json.loads(urllib.request.urlopen(req, timeout=20).read())
            feats = d.get("features", [])
            for f in feats:
                p = f.get("properties", {})
                c = f.get("geometry", {}).get("coordinates")
                if not c:
                    continue
                # 取经纬度 [lng, lat]
                return [c[0], c[1]]
            return None
        except Exception:
            time.sleep(1.5)
    return None


def load_district_centroids():
    out = {}
    if not os.path.exists(DISTRICT_CENTROIDS_FILE):
        return out
    d = json.load(open(DISTRICT_CENTROIDS_FILE, encoding="utf-8"))
    for f in d.get("features", []):
        name = f["properties"]["name"]
        center = f["properties"].get("center")
        if center and len(center) == 2:
            out[name] = [center[0], center[1]]
    return out


def norm_name(s: str) -> str:
    s = (s or "").strip()
    s = s.replace("站", "")                        # 去"站"后缀
    s = re.sub(r"[\(（][^\)）]*[\)）]", "", s)      # 去括号内"原XX"
    s = s.replace("·", "").replace("•", "")
    return s


def main() -> int:
    # 取地铁快照的 274 个去重站名（选任一目标月，站名集合一致）
    metro_file = None
    for f in sorted(os.listdir(SNAP)):
        if f.startswith("metro_") and f.endswith(".csv"):
            metro_file = os.path.join(SNAP, f)
            break
    if not metro_file:
        print("未找到地铁快照 CSV", file=sys.stderr)
        return 1

    rows = list(csv.DictReader(open(metro_file, encoding="utf-8-sig")))
    stations = []
    seen = set()
    # 同时记录每个站名的 businessAreaName / districtname（用于兜底）
    station_meta = {}
    for r in rows:
        n = r["lineName"]
        if not n or n in seen:
            continue
        seen.add(n)
        stations.append(n)
        station_meta[n] = {
            "businessAreaName": r.get("businessAreaName") or "",
            "districtname": r.get("districtname") or "",
        }

    # 1) 参考数据集
    ref = json.load(open(REF_FILE, encoding="utf-8")) if os.path.exists(REF_FILE) else {}
    ref_norm = {}
    for k, v in ref.items():
        nn = norm_name(k)
        if nn not in ref_norm:
            ref_norm[nn] = (k, float(v["LNG"]), float(v["LAT"]))

    district_centroids = load_district_centroids()

    out = {}
    matched_ref = 0
    matched_photon = 0
    matched_centroid = 0
    unmatched = []

    for s in stations:
        ns = norm_name(s)
        # 1) 参考数据集
        if ns in ref_norm:
            _, lng, lat = ref_norm[ns]
            out[s] = {
                "name": s,
                "lng": lng,
                "lat": lat,
                "confidence": "medium",
                "source": "SHMetro/YutingHan (OSM, WGS84)",
            }
            matched_ref += 1
            continue
        # 2) Photon
        coords = photon_geocode(s)
        if coords:
            out[s] = {
                "name": s,
                "lng": round(coords[0], 6),
                "lat": round(coords[1], 6),
                "confidence": "approx",
                "source": "OSM Photon geocode (place-level, may be nearby not exact gate)",
            }
            matched_photon += 1
        else:
            # 3) 兜底：区县质心
            out[s] = {
                "name": s,
                "lng": None,
                "lat": None,
                "confidence": "low",
                "source": "fallback: district centroid (unresolved)",
            }
            unmatched.append(s)
        time.sleep(0.35)  # 限速

    # 兜底质心补坐标（仅对 confidence=low 记录）
    # districtname 是编码数组，无法直接映射；统一用上海全市质心近似
    shanghai_center = district_centroids.get("上海市") or district_centroids.get("黄埔区") or [121.472644, 31.231706]
    for s in unmatched:
        out[s]["district_centroid_fallback"] = shanghai_center
        matched_centroid += 1

    result = {
        "source": "SHMetro/YutingHan + OSM Photon + district centroid fallback",
        "license": "SHMetro: MIT; OSM: ODbL",
        "coordinate_system": "WGS84",
        "total_stations": len(stations),
        "matched_reference": matched_ref,
        "matched_photon": matched_photon,
        "matched_centroid_fallback": matched_centroid,
        "match_rate_exact_plus_photon": round((matched_ref + matched_photon) / len(stations), 3),
        "stations": out,
    }

    # 引擎 (engine/candidates.py load_metro_coords) 期望顶层为「站名 -> {lng,lat}」的平铺字典；
    # 因此额外写一份平铺视图到同名文件：顶层即站名，元信息收敛到 _meta。
    flat = dict(out)
    flat["_meta"] = {
        k: v for k, v in result.items() if k != "stations"
    }

    out_path = os.path.join(GEO, "metro_stations.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(flat, f, ensure_ascii=False, indent=1)
    print(f"写到 {out_path}")
    print(f"总数 {len(stations)} | 参考精确 {matched_ref} | Photon {matched_photon} | 质心兜底 {matched_centroid}")
    print(f"match_rate(excl 质心兜底) = {(matched_ref+matched_photon)/len(stations):.1%}")
    if unmatched:
        print(f"未解析（质心兜底）：{len(unmatched)}")
        for s in unmatched:
            print("   -", s.encode("unicode_escape").decode())
    return 0


if __name__ == "__main__":
    sys.exit(main())
