# -*- coding: utf-8 -*-
"""候选富化：价格 / 曝光代理 / 场馆亲和 / POI 命中 / 区县权重 / 廊道加成 / 槽位衰减。

产出每个候选的 score / score_breakdown / reasons / evidence / alternatives。
乐高无地铁直达：采用 6/20/50km 圈 + 家庭客源枢纽，不做硬 6km 过滤。
绝不编造坐标；缺失地理时标 schematic / low confidence。
"""
from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from . import config
from .finance import RateCard, unit_price
from .data_loader import Candidate
from .skill_loader import Skill

# 距离（km）到 zone 权重（按场馆 rings_km 命中若干环的近似）
# 无真实坐标时 fallback 到 operating-company region / district 代理
RADIUS_BUS_KM = 0.5
RADIUS_METRO_KM = 0.8

_POI_CACHE: Optional[List[Dict[str, Any]]] = None
_METRO_COORD_CACHE: Optional[Dict[str, Dict[str, Any]]] = None
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


def load_pois(force: bool = False) -> List[Dict[str, Any]]:
    """读取本地 POI 层（构建期缓存，运行时不联网）。

    优先 data/geo/poi_theme_park.geojson，回退 poi_fallback.geojson。
    返回 [{id,name,type,lng,lat,district,weight,source,confidence}]
    """
    global _POI_CACHE
    if _POI_CACHE is not None and not force:
        return _POI_CACHE
    out: List[Dict[str, Any]] = []
    for name in ("poi_theme_park.geojson", "poi_fallback.geojson"):
        p = os.path.join(config.GEO_DIR, name)
        if not os.path.exists(p):
            continue
        try:
            with open(p, encoding="utf-8") as f:
                geo = json.load(f)
            for feat in geo.get("features", []):
                props = feat.get("properties") or {}
                geom = feat.get("geometry") or {}
                coord = geom.get("coordinates") or []
                if len(coord) < 2:
                    continue
                typ = props.get("type") or "attraction"
                out.append({
                    "id": props.get("id") or f"poi:{len(out)+1}",
                    "name": props.get("name") or "POI",
                    "type": typ,
                    "lng": float(coord[0]),
                    "lat": float(coord[1]),
                    "district": props.get("district") or "",
                    "weight": float(props.get("weight") or TYPE_WEIGHT.get(typ, 0.6)),
                    "source": props.get("source") or "公开信息近似",
                    "confidence": props.get("confidence") or "approx",
                })
            if out:
                break
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            out = []
            continue
    _POI_CACHE = out
    return out


def load_metro_coords(force: bool = False) -> Dict[str, Dict[str, Any]]:
    """地铁站坐标：优先 data/geo/metro_stations.json，回退构建期公开站点数据。"""
    global _METRO_COORD_CACHE
    if _METRO_COORD_CACHE is not None and not force:
        return _METRO_COORD_CACHE
    out: Dict[str, Dict[str, Any]] = {}
    p1 = os.path.join(config.GEO_DIR, "metro_stations.json")
    p2 = os.path.join(config.GEO_DIR, "_shmetro_stations_by_name.json")
    for p in (p1, p2):
        if not os.path.exists(p):
            continue
        try:
            with open(p, encoding="utf-8") as f:
                raw = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(raw, dict):
            continue
        for name, v in raw.items():
            if not isinstance(v, dict):
                continue
            lng = v.get("lng", v.get("LNG"))
            lat = v.get("lat", v.get("LAT"))
            try:
                lng_f, lat_f = float(lng), float(lat)
            except (TypeError, ValueError):
                continue
            out[str(name)] = {
                "lng": lng_f, "lat": lat_f,
                "confidence": v.get("confidence") or ("approx" if p == p1 else "approx"),
                "source": v.get("source") or ("公开站点数据" if p == p2 else "构建期缓存"),
            }
        if out:
            break
    _METRO_COORD_CACHE = out
    return out


def reload_geo() -> None:
    global _POI_CACHE, _METRO_COORD_CACHE
    _POI_CACHE = None
    _METRO_COORD_CACHE = None


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    h = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng / 2) ** 2
    )
    return 2 * r * math.asin(math.sqrt(h))


def _station_coords(cand: Candidate) -> Optional[Dict[str, float]]:
    if cand.kind != "metro":
        return None
    c = load_metro_coords().get(cand.line_name)
    if not c:
        return None
    return {"lng": float(c["lng"]), "lat": float(c["lat"])}


def _station_geo(cand: Candidate) -> Optional[Dict[str, Any]]:
    """地铁站坐标 + 置信度/来源（来自 metro_stations.json，绝不编造）。"""
    if cand.kind != "metro":
        return None
    c = load_metro_coords().get(cand.line_name)
    if not c:
        return None
    try:
        lng, lat = float(c["lng"]), float(c["lat"])
    except (KeyError, TypeError, ValueError):
        return None
    return {
        "coords": {"lng": lng, "lat": lat},
        "confidence": c.get("confidence") or "approx",
        "source": c.get("source") or "",
    }


def _exposure_proxy(kind: str, level: str) -> float:
    if kind == "bus":
        return float(config.BUS_EXPOSURE.get(level, 0.0))
    return float(config.METRO_EXPOSURE.get(level, 0.0))


def _level_weight(skill: Skill, level: str) -> float:
    return float(skill.level_weights.get(level, 1.0))


def _zone_score(skill: Skill, cand: Candidate) -> float:
    """场馆亲和 / 区域权重：无真实距离时用区县 / 运营公司代理。"""
    # 乐高（金山）与市中心距离远；这里用启发式：区县越接近金山/浦东枢纽权重越高。
    # 简化：区内与场馆同区 -> 高；否则中等。真实版应接 geo。
    district = cand.district or ""
    venue_district = skill.district or ""
    if district and venue_district and district == venue_district:
        return 0.95
    # 家庭客源核心区（市中心 + 浦东）
    core = ("黄浦区", "静安区", "徐汇区", "浦东新区", "长宁区", "虹口区", "杨浦区", "普陀区", "闵行区")
    if any(c in district for c in core):
        return 0.70
    return 0.45


def _poi_score(cand: Candidate, skill: Skill, pois: List[Dict[str, Any]]) -> Tuple[float, int, List[Dict[str, Any]]]:
    """POI 命中：地铁 800m 真实距离；公交无坐标时用区县代理。

    返回 (score, hits, poi_evidence)；无数据 → (0.0, 0, [])，不影响稳定性。
    """
    # 若 Candidate.raw 已带 poi_hits（来自 candidates_enriched），直接使用
    raw_hits = cand.raw.get("poi_hits") if isinstance(cand.raw, dict) else None
    if raw_hits:
        n = len(raw_hits) if isinstance(raw_hits, list) else int(raw_hits or 0)
        return (min(1.0, 0.3 + 0.2 * n), n, [])
    if not pois:
        return (0.0, 0, [])

    coords = _station_coords(cand)
    if coords:
        hits: List[Tuple[Dict[str, Any], float]] = []
        for p in pois:
            try:
                d = _haversine_km(coords["lat"], coords["lng"], float(p["lat"]), float(p["lng"]))
            except (KeyError, TypeError, ValueError):
                continue
            if d <= RADIUS_METRO_KM:
                hits.append((p, d))
        hits.sort(key=lambda x: x[1])
        n = len(hits)
        if not n:
            return (0.0, 0, [])
        weight_sum = sum(float(p.get("weight", 0.6)) for p, _ in hits)
        score = min(1.0, weight_sum / 3.0)
        evidence = []
        for p, d in hits[:5]:
            evidence.append({
                "id": p.get("id"),
                "name": p.get("name"),
                "type": p.get("type"),
                "lng": p.get("lng"),
                "lat": p.get("lat"),
                "weight": p.get("weight"),
                "distance_m": round(d * 1000),
                "source": p.get("source"),
            })
        return (score, n, evidence)

    # 地铁无坐标：不能拿“整个区”的 POI 冒充满意 800m；坐标缺失即视为低置信度，
    # POI 维度置 0，避免远郊站被区县代理误加权（地图上也不会伪造位置）。
    if cand.kind == "metro":
        return (0.0, 0, [])

    # 公交无坐标：区县代理（明确标注 schematic）；兼容 “杨浦-浦东” 这类复合区域名
    import re
    parts = [x for x in re.split(r"[-/、]", cand.district or "") if x]
    hit_pois = [
        p for p in pois
        if p.get("district") and any(part in str(p["district"]) for part in parts)
    ]
    n = len(hit_pois)
    if not n:
        return (0.0, 0, [])
    score = min(0.65, 0.15 + 0.05 * min(n, 10))
    return (score, n, hit_pois[:3])


def _corridor_score(cand: Candidate) -> float:
    """廊道 / 换乘加成：地铁换乘站 stationAttr 含多线 -> 加分。"""
    if cand.kind == "metro" and cand.station_attr:
        # 统计换乘线路数（Lxx 数量）
        import re
        lines = re.findall(r"L\d{2}", cand.station_attr)
        return min(1.0, 0.6 + 0.1 * len(lines))
    # 公交：知名走廊（17/71/911 等）通过 reason 隐式体现，这里中性
    return 0.7


def _cost_efficiency(kind: str, level: str, rc: RateCard) -> float:
    """千人成本反向归一（缺客流时让位其他维度）。"""
    exp = _exposure_proxy(kind, level)
    price = unit_price(rc, kind, level)
    if not exp or not price:
        return 0.5
    cpm = price * 10000.0 / exp * 1000.0  # 元/千曝光
    # 越低越好；归一化到 0..1（CPM 0 → 1, CPM 200 → 0.2）
    return max(0.0, min(1.0, 1.0 - (cpm - 10.0) / 200.0))


def enrich(
    cands: List[Candidate],
    skill: Skill,
    rc: RateCard,
    pois: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """把 Candidate 富化成带评分/理由/证据的 dict 列表（solver 与解释层共用）。"""
    pois = pois if pois is not None else load_pois()
    out: List[Dict[str, Any]] = []
    for c in cands:
        exp = _exposure_proxy(c.kind, c.level)
        lv_w = _level_weight(skill, c.level)
        zone = _zone_score(skill, c)
        poi_s, poi_n, poi_ev = _poi_score(c, skill, pois)
        corridor = _corridor_score(c)
        ceff = _cost_efficiency(c.kind, c.level, rc)

        # 综合评分（PRD §6 加权参照，乐园行业 audienceW=0.5 已并入 poi 维度）
        score = round((
            0.34 * zone
            + 0.10 * min(1.0, (lv_w - 0.65) / 0.65)  # 等级权重归一
            + 0.28 * corridor
            + 0.15 * ceff
            + 0.13 * poi_s
        ) * 100.0, 1)

        reasons: List[str] = []
        evidence: List[Dict[str, Any]] = []
        # 曝光理由
        if exp:
            reasons.append(f"{c.level} 级，日均曝光按 {int(exp):,} 人次估算，曝光效率{'高' if exp >= 48000 else '中'}")
        # 区县理由
        reasons.append(f"覆盖 {c.district or '未知区县'}" + ("（场馆同区，亲和度高）" if zone >= 0.9 else ""))
        # 库存证据
        evidence.append({"type": "inventory", "text": f"红豆 min_free={c.free_count}", "source": "红豆 API"})
        if c.kind == "metro" and c.station_attr:
            reasons.append(f"{c.station_attr} 换乘，家庭出行拦截强")
            evidence.append({"type": "transfer", "text": c.station_attr, "source": "红豆 stationAttr"})
        if poi_n:
            names = "、".join(str(p.get("name")) for p in poi_ev[:3] if p.get("name"))
            reasons.append(f"周边命中 {poi_n} 个亲子/家庭 POI" + (f"（{names}）" if names else ""))
            evidence.append({
                "type": "poi",
                "text": f"周边 800m/区县代理命中 {poi_n} 个 POI" + (f"：{names}" if names else ""),
                "source": "POI 近似库（构建期缓存）",
            })

        # geo：地铁有站点坐标 → point（带来源置信度）；公交无真实轨迹数据 → schematic。
        # 若日后数据组提供公交线路几何，此处改为 geo={"type":"lines", "coords": [...]}。
        if c.kind == "metro":
            sg = _station_geo(c)
        else:
            sg = None
        if c.kind == "metro" and sg:
            geo = {"type": "point", "coords": sg["coords"], "confidence": sg["confidence"]}
            if sg.get("source"):
                geo["source"] = sg["source"]
        else:
            geo = {"type": "schematic", "district": c.district or "", "confidence": "low"}

        out.append({
            "id": c.id,
            "kind": c.kind,
            "name": c.line_name,
            "line": c.line_name if c.kind == "bus" else None,
            "station": c.line_name if c.kind == "metro" else None,
            "exit": c.exit_name,
            "company": c.company,
            "district": c.district,
            "level": c.level,
            "media_type": c.media_type,
            "free_count": c.free_count,
            "unit_price_wan": unit_price(rc, c.kind, c.level),
            "exposure": exp,
            "score": score,
            "score_breakdown": {
                "exposure": round(min(1.0, exp / 90000.0), 2),
                "audience_fit": round(min(1.0, (lv_w - 0.65) / 0.65), 2),
                "poi": round(poi_s, 2),
                "zone": round(zone, 2),
                "corridor": round(corridor, 2),
                "cost_efficiency": round(ceff, 2),
            },
            "reasons": reasons,
            "evidence": evidence,
            "alternatives": [],
            "geo": geo,
            "poi_hits": poi_ev,
            "poi_count": poi_n,
            "raw": c.raw,
        })
    return out


def prefilter(enriched: List[Dict[str, Any]], kind: str) -> List[Dict[str, Any]]:
    """性能保护：只保留 top N 高分候选，但保留等级多样性（否则配比约束不可行）。"""
    sub = [e for e in enriched if e["kind"] == kind]
    cap = config.PREFILTER_BUS if kind == "bus" else config.PREFILTER_METRO

    # 排除 bus AA（曝光 0，契约明确 AA 不进曝光主线）
    if kind == "bus":
        sub = [e for e in sub if e["level"] != "AA"]

    sub.sort(key=lambda e: (-e["score"], e["id"]))

    # 等级配额：确保每个等级至少保留若干候选，防止高等级独占挤掉低等级
    if kind == "metro":
        levels = ("A++", "A+")
    else:
        levels = ("S", "A++", "A+")

    picked: List[Dict[str, Any]] = []
    seen = set()
    # 先按等级分层各取一部分
    per_level = max(1, cap // len(levels))
    for lv in levels:
        pool = [e for e in sub if e["level"] == lv]
        for e in pool[:per_level]:
            if e["id"] not in seen and len(picked) < cap:
                picked.append(e)
                seen.add(e["id"])
    # 剩余名额按分数填满
    for e in sub:
        if len(picked) >= cap:
            break
        if e["id"] not in seen:
            picked.append(e)
            seen.add(e["id"])

    picked.sort(key=lambda e: (-e["score"], e["id"]))
    return picked


__all__ = ["enrich", "prefilter", "load_pois", "load_metro_coords", "reload_geo"]
