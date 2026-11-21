"""Build the data assets the Astro frontend imports.

Writes:
  web/src/data/fixtures/plan-<venue>-<budget>.json   real engine PlanResponse
  web/src/data/fixtures/elasticity-lego.json         real nine-step elasticity
  web/src/data/map/metro.json                        metro exits (WGS84, cleaned)
  web/src/data/map/poi.json                          POIs (WGS84, cleaned)
  web/src/data/map/venues.json                       venue profiles
  web/public/data/shanghai_districts.geojson         district boundaries (as-is, DataV)
  web/src/data/map/meta.json                         counts + data version

Run: .venv\\Scripts\\python.exe scripts\\build_web_data.py
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
WEB = ROOT / "web"
DATA = WEB / "src" / "data"
FIXTURES = DATA / "fixtures"
MAP = DATA / "map"
PUBLIC_DATA = WEB / "public" / "data"

BBOX = (120.80, 30.60, 122.30, 31.90)  # Shanghai incl. Chongming


def _write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {path.relative_to(ROOT)} ({path.stat().st_size:,} B)")


def _in_bbox(lng: float, lat: float) -> bool:
    return BBOX[0] <= lng <= BBOX[2] and BBOX[1] <= lat <= BBOX[3]


def build_plans() -> None:
    from engine.orchestrator import generate_elasticity, generate_plan

    base = {
        "industry": "乐园",
        "media": ["bus", "metro"],
        "start_date": "2027-07-01",
        "weeks": 8,
        "customer_type": "direct",
        "locks": {"include": [], "exclude": []},
        "brief_text": None,
    }
    combos = [
        ("lego", "lego_shanghai", 500),
        ("lego", "lego_shanghai", 200),
        ("lego", "lego_shanghai", 100),
        ("disney", "disney_shanghai", 500),
        ("haichang", "haichang_shanghai", 500),
    ]
    for label, venue, budget in combos:
        payload = {**base, "venue": venue, "budget_wan": budget}
        plan = generate_plan(payload)
        _write_json(FIXTURES / f"plan-{label}-{budget}.json", plan)
        print("  ", label, budget, "kpi:", plan["effects"]["impressions"], plan["effects"]["reach_pct"])

    elast = generate_elasticity({**base, "venue": "lego_shanghai", "budget_wan": 500})
    _write_json(FIXTURES / "elasticity-lego.json", elast)


def build_map() -> None:
    cand_path = ROOT / "data" / "processed" / "candidates.geo.json"
    raw = json.loads(cand_path.read_text(encoding="utf-8"))
    layers = raw["layers"]

    metro = []
    dropped = 0
    for m in layers.get("metro", []):
        lng, lat = m.get("lng"), m.get("lat")
        if not lng or not lat or not _in_bbox(lng, lat):
            dropped += 1
            continue
        metro.append({
            "id": m.get("id"),
            "name": m.get("name") or m.get("exitName"),
            "station": m.get("station") or m.get("stationName"),
            "exit": m.get("exit") or m.get("exitName"),
            "line": m.get("line") or m.get("lineName"),
            "level": m.get("level"),
            "district": m.get("district"),
            "lng": round(float(lng), 6),
            "lat": round(float(lat), 6),
            "confidence": m.get("coord_confidence") or m.get("confidence"),
        })

    pois = []
    seen = set()
    for p in layers.get("pois", []):
        lng, lat = p.get("lng"), p.get("lat")
        if not lng or not lat:
            coord = p.get("coord") or []
            if len(coord) >= 2:
                lng, lat = coord[0], coord[1]
        if not lng or not lat or not _in_bbox(lng, lat):
            continue
        key = (p.get("name"), round(float(lng), 4), round(float(lat), 4))
        if key in seen:
            continue
        seen.add(key)
        pois.append({
            "id": p.get("id"),
            "name": p.get("name"),
            "type": p.get("type"),
            "district": p.get("district"),
            "weight": p.get("weight"),
            "lng": round(float(lng), 6),
            "lat": round(float(lat), 6),
            "source": "theme-park",
        })

    fallback_path = ROOT / "data" / "geo" / "poi_fallback.geojson"
    if fallback_path.exists():
        fb = json.loads(fallback_path.read_text(encoding="utf-8"))
        for f in fb.get("features", []):
            lng, lat = f["geometry"]["coordinates"][:2]
            if not _in_bbox(lng, lat):
                continue
            props = f.get("properties", {})
            key = (props.get("name"), round(float(lng), 4), round(float(lat), 4))
            if key in seen:
                continue
            seen.add(key)
            pois.append({
                "id": props.get("id"),
                "name": props.get("name"),
                "type": props.get("type"),
                "district": props.get("district"),
                "weight": props.get("weight"),
                "lng": round(float(lng), 6),
                "lat": round(float(lat), 6),
                "source": "fallback",
            })

    venues = []
    venues_dir = ROOT / "data" / "config" / "venues"
    for path in sorted(venues_dir.glob("*.json")):
        v = json.loads(path.read_text(encoding="utf-8"))
        coords = v.get("coords") or {}
        venues.append({
            "id": v.get("id"),
            "name": v.get("name"),
            "en_name": v.get("en_name"),
            "district": v.get("district"),
            "coords": {"lng": coords.get("lng"), "lat": coords.get("lat")},
            "rings_km": v.get("catchment_rings_km") or v.get("rings_km"),
            "access": v.get("access_modes"),
            "target_population": v.get("target_population"),
            "reach_k": v.get("reach_k"),
        })

    _write_json(MAP / "metro.json", metro)
    _write_json(MAP / "poi.json", pois)
    _write_json(MAP / "venues.json", venues)

    districts_src = ROOT / "data" / "geo" / "shanghai_districts.geojson"
    PUBLIC_DATA.mkdir(parents=True, exist_ok=True)
    (PUBLIC_DATA / "shanghai_districts.geojson").write_text(
        districts_src.read_text(encoding="utf-8"), encoding="utf-8"
    )
    print(f"wrote {PUBLIC_DATA.relative_to(ROOT)}/shanghai_districts.geojson")

    manifest_path = ROOT / "data" / "processed" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    _write_json(MAP / "meta.json", {
        "data_version": manifest.get("data_version"),
        "inventory_ts": manifest.get("inventory_ts"),
        "inventory_periods": manifest.get("inventory_periods"),
        "metro_points": len(metro),
        "metro_dropped": dropped,
        "poi_points": len(pois),
        "districts": 16,
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "coord_note": "地铁、POI、场馆为 WGS84，前端转换为 GCJ-02；区县边界沿用 DataV 口径。",
    })


if __name__ == "__main__":
    os.makedirs(FIXTURES, exist_ok=True)
    build_plans()
    build_map()
    print("done")
