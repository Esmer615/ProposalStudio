# -*- coding: utf-8 -*-
"""场馆（乐园）档案加载：data/config/venues/*.json → 规范化 Skill 对象。

Agent-A 会写 data/config/venues/{venue}.json；本模块读取并校验必要字段，
缺失时回退到内置的 lego/disney/haichang 档案。

对外暴露一个 Skill 命名空间：target_population / reach_k / rings_km /
media mix bounds / level weights / POI weights / compliance / messaging。
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from . import config
from .models import PlanError

# 三个内置场馆档案（当 data/config/venues/*.json 缺失时的回退）
BUILTIN_PROFILES: Dict[str, Dict[str, Any]] = {
    "lego_shanghai": {
        "id": "lego_shanghai",
        "name": "上海乐高乐园",
        "district": "金山区",
        "coords": {"lng": 121.104, "lat": 30.880},
        "confidence": "approx",
        "target_population": 2_500_000,
        "reach_k": 260.0,
        "rings_km": [6, 20, 50],
        "metro_direct": False,
        "self_drive_share": 0.68,
        "rail_share": 0.14,
        "media_mix_bounds": {"bus": {"min": 0.4, "max": 1.0}, "metro": {"min": 0.0, "max": 0.6}},
        "level_weights": {"S": 1.30, "A++": 1.00, "A+": 0.80, "AA": 0.65},
        "poi_weights": {},
        "compliance_forbidden": ["保证入园人数", "承诺销售转化", "投资收益承诺", "校内广告"],
        "compliance_notes": ["不投校内，统一口径为“学校周边 300–500 米”。", "所有曝光数字标注估算口径。"],
        "messaging": ["亲子家庭暑期出游首选目的地", "自驾+高铁交通结构", "全国第二家乐高乐园，稀缺性吸引长三角客群"],
    },
    "disney_shanghai": {
        "id": "disney_shanghai",
        "name": "上海迪士尼度假区",
        "district": "浦东新区",
        "coords": {"lng": 121.699, "lat": 31.146},
        "confidence": "approx",
        "target_population": 2_500_000,
        "reach_k": 250.0,
        "rings_km": [6, 20, 50],
        "metro_direct": True,
        "self_drive_share": 0.35,
        "rail_share": 0.45,
        "media_mix_bounds": {"bus": {"min": 0.3, "max": 0.8}, "metro": {"min": 0.2, "max": 0.7}},
        "level_weights": {"S": 1.25, "A++": 1.00, "A+": 0.80, "AA": 0.65},
        "poi_weights": {},
        "compliance_forbidden": ["保证入园人数", "承诺销售转化", "投资收益承诺", "校内广告"],
        "compliance_notes": ["不投校内，统一口径为“学校周边 300–500 米”。", "所有曝光数字标注估算口径。"],
        "messaging": ["全球顶级主题乐园，家庭亲子与年轻成人双人群", "地铁11号线直达"],
    },
    "haichang_shanghai": {
        "id": "haichang_shanghai",
        "name": "上海海昌海洋公园",
        "district": "浦东新区",
        "coords": {"lng": 121.903, "lat": 30.894},
        "confidence": "approx",
        "target_population": 2_500_000,
        "reach_k": 255.0,
        "rings_km": [6, 20, 50],
        "metro_direct": True,
        "self_drive_share": 0.45,
        "rail_share": 0.40,
        "media_mix_bounds": {"bus": {"min": 0.4, "max": 1.0}, "metro": {"min": 0.0, "max": 0.6}},
        "level_weights": {"S": 1.25, "A++": 1.00, "A+": 0.80, "AA": 0.65},
        "poi_weights": {},
        "compliance_forbidden": ["保证入园人数", "承诺销售转化", "投资收益承诺", "校内广告"],
        "compliance_notes": ["不投校内，统一口径为“学校周边 300–500 米”。", "所有曝光数字标注估算口径。"],
        "messaging": ["海洋主题亲子乐园", "地铁16号线直达滴水湖+短驳", "科普+娱乐融合"],
    },
}


@dataclass
class Skill:
    """规范化后的场馆档案（供下游使用）。"""

    id: str
    name: str
    district: str
    coords: Dict[str, float]
    confidence: str
    target_population: int
    reach_k: float
    rings_km: List[int]
    media_mix_bounds: Dict[str, Dict[str, float]]
    level_weights: Dict[str, float]
    poi_weights: Dict[str, float]
    compliance_forbidden: List[str]
    compliance_notes: List[str]
    messaging: List[str]
    metro_direct: bool
    self_drive_share: float
    rail_share: float
    source: str = "built-in"
    extra: Dict[str, Any] = field(default_factory=dict)

    def bus_mix_bounds(self) -> tuple:
        b = self.media_mix_bounds.get("bus", {})
        return (b.get("min", 0.0), b.get("max", 1.0))

    def metro_mix_bounds(self) -> tuple:
        m = self.media_mix_bounds.get("metro", {})
        return (m.get("min", 0.0), m.get("max", 1.0))


def _venue_json_path(venue: str) -> str:
    return os.path.join(config.VENUE_DIR, f"{venue}.json")


def load_venue_profile(venue: str) -> Dict[str, Any]:
    """优先读 data/config/venues/{venue}.json；缺失则用内置档案。"""
    p = _venue_json_path(venue)
    if os.path.exists(p):
        try:
            with open(p, encoding="utf-8") as f:
                raw = json.load(f)
            return _normalize_from_file(raw, venue)
        except (json.JSONDecodeError, OSError):
            # 文件损坏 → 回退内置，但不静默：记录 source
            builtin = dict(BUILTIN_PROFILES.get(venue, {}))
            builtin["source"] = f"built-in(fallback:{os.path.basename(p)} invalid)"
            return builtin
    builtin = dict(BUILTIN_PROFILES.get(venue, {}))
    if not builtin:
        raise PlanError(
            "VALIDATION_ERROR",
            f"未知场馆：{venue}",
            field="venue",
            suggestions=list(BUILTIN_PROFILES.keys()),
        )
    builtin["source"] = "built-in"
    return builtin


def _normalize_from_file(raw: Dict[str, Any], venue: str) -> Dict[str, Any]:
    """把 Agent-A 的 venues/*.json 归一成 Skill 需要的内置字段名。"""
    out: Dict[str, Any] = {}
    out["id"] = raw.get("id", venue)
    out["name"] = raw.get("name", BUILTIN_PROFILES.get(venue, {}).get("name", venue))
    out["district"] = raw.get("district", "")

    coords = raw.get("coords") or {}
    out["coords"] = {"lng": float(coords.get("lng", 0.0)), "lat": float(coords.get("lat", 0.0))}
    confidence = coords.get("confidence") if isinstance(coords, dict) else raw.get("confidence")
    out["confidence"] = confidence or "approx"

    # target_population 可能为 {"value": null, ...} 结构
    tp = raw.get("target_population")
    if isinstance(tp, dict):
        tp_val = tp.get("value")
        out["target_population"] = int(tp_val) if tp_val is not None else 2_500_000
    else:
        out["target_population"] = int(tp or 2_500_000)

    out["reach_k"] = float(raw.get("reach_k") or 260.0)
    out["rings_km"] = [int(x) for x in (raw.get("catchment_rings_km") or raw.get("rings_km") or [6, 20, 50])]

    # media_mix_bounds: {bus:{min,max}, metro:{min,max}}
    mmb = raw.get("media_mix_bounds") or {}
    out["media_mix_bounds"] = {
        "bus": {"min": float((mmb.get("bus") or {}).get("min", 0.0)), "max": float((mmb.get("bus") or {}).get("max", 1.0))},
        "metro": {"min": float((mmb.get("metro") or {}).get("min", 0.0)), "max": float((mmb.get("metro") or {}).get("max", 1.0))},
    }

    out["level_weights"] = {k: float(v) for k, v in (raw.get("level_weights") or {"S": 1.3, "A++": 1.0, "A+": 0.8, "AA": 0.65}).items()}
    out["poi_weights"] = {k: float(v) for k, v in (raw.get("poi_type_weights") or {}).items()}
    out["compliance_forbidden"] = ["保证入园人数", "承诺销售转化", "投资收益承诺", "校内广告"]
    out["compliance_notes"] = list(raw.get("compliance_avoid_list") or [])
    out["messaging"] = list(raw.get("messaging_points") or [])

    access = raw.get("access_modes") or {}
    metro_access = access.get("metro") or {}
    out["metro_direct"] = bool(metro_access.get("direct", False)) if isinstance(metro_access, dict) else False
    sd = access.get("self_drive") or {}
    out["self_drive_share"] = float(sd.get("share", 0.5)) if isinstance(sd, dict) else float(sd or 0.5)
    hr = access.get("high_speed_rail") or access.get("metro_share") or {}
    if isinstance(hr, dict):
        out["rail_share"] = float(hr.get("share", 0.0))
    else:
        out["rail_share"] = float(hr or 0.0)

    out["source"] = f"file:{venue}.json"
    out["extra"] = {k: v for k, v in raw.items() if k not in out}
    return out


def build_skill(venue: str) -> Skill:
    """加载并校验场馆档案，返回 Skill 对象。校验失败抛 PlanError。"""
    raw = load_venue_profile(venue)
    try:
        return Skill(
            id=raw["id"],
            name=raw["name"],
            district=raw.get("district", ""),
            coords=raw.get("coords", {"lng": 0.0, "lat": 0.0}),
            confidence=raw.get("confidence", "approx"),
            target_population=int(raw.get("target_population", 2_500_000)),
            reach_k=float(raw.get("reach_k", 260.0)),
            rings_km=[int(x) for x in (raw.get("rings_km") or [6, 20, 50])],
            media_mix_bounds=raw.get("media_mix_bounds", {"bus": {"min": 0.0, "max": 1.0}, "metro": {"min": 0.0, "max": 1.0}}),
            level_weights=raw.get("level_weights", {}),
            poi_weights=raw.get("poi_weights", {}),
            compliance_forbidden=raw.get("compliance_forbidden", []),
            compliance_notes=raw.get("compliance_notes", []),
            messaging=raw.get("messaging", []),
            metro_direct=bool(raw.get("metro_direct", False)),
            self_drive_share=float(raw.get("self_drive_share", 0.5)),
            rail_share=float(raw.get("rail_share", 0.0)),
            source=raw.get("source", "built-in"),
            extra=raw.get("extra", {}),
        )
    except (KeyError, TypeError, ValueError) as e:
        raise PlanError(
            "VALIDATION_ERROR",
            f"场馆档案 {venue} 缺少必要字段或类型错误：{e}",
            field="venue",
        )


# 供服务端 /meta 使用的渠道披露口径
VENUE_PROFILE_PATHS = {v: _venue_json_path(v) for v in BUILTIN_PROFILES}


__all__ = ["Skill", "build_skill", "load_venue_profile", "BUILTIN_PROFILES"]
