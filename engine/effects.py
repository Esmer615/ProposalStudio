# -*- coding: utf-8 -*-
"""效果估算：确定性 Reach / Frequency / CPM / 弹性。

公式（契约 §2.7）：
    impressions = Σ units × daily_audience × view_rate × days × audience_fit × decay^(k-1)
    GRP  = impressions / target_population × 100
    Reach = reach_cap × (1 − exp(−GRP / k_eff))
    Frequency = (GRP/100) / Reach
    CPM = media_net_yuan / impressions × 1000

- 双媒体合并用单一饱和曲线；by_media 仅做归因，绝不相加成到达率。
- reach <= reach_cap；无 NaN。
- audience_fit 由 level_weights 归一（这里简化为 1.0 的等级曝光差异已并入 daily_audience）。
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

from . import config

REACH_CAP = config.REACH_CAP
VIEW_RATE_BUS = config.VIEW_RATE_BUS
VIEW_RATE_METRO = config.VIEW_RATE_METRO


def _daily_audience(kind: str, level: str) -> float:
    if kind == "bus":
        return float(config.BUS_EXPOSURE.get(level, 0.0))
    return float(config.METRO_EXPOSURE.get(level, 0.0))


def compute_effects(
    plan_items: List[Dict[str, Any]],
    target_population: float,
    reach_k: float,
    days: int,
    media_net_wan: float,
    dual_media: bool,
) -> Dict[str, Any]:
    """plan_items: 每项含 kind/level/units（免 slot 衰减按 units 排序时用 decay）。"""
    k_eff = reach_k * (config.K_EFF_DUAL_FACTOR if dual_media else 1.0)

    impressions_total = 0.0
    by_media_imp: Dict[str, float] = {"bus": 0.0, "metro": 0.0}
    by_media_cost: Dict[str, float] = {"bus": 0.0, "metro": 0.0}
    by_line: List[Dict[str, Any]] = []

    for it in plan_items:
        kind = it["kind"]
        level = it["level"]
        units = int(it.get("units", 0))
        audience = _daily_audience(kind, level)
        view_rate = VIEW_RATE_BUS if kind == "bus" else VIEW_RATE_METRO
        # audience_fit 归一：level 已通过 audience 体现，这里 audience_fit=1.0
        # slot decay：每多一个 unit 同一线路 0.72^(k-1)，简化按 units 求和
        imp = 0.0
        for k in range(units):
            imp += audience * view_rate * days * 1.0 * (config.SLOT_DECAY ** k)
        impressions_total += imp
        by_media_imp[kind] += imp
        by_media_cost[kind] += float(it.get("net_wan", 0.0))
        by_line.append({"id": it["id"], "impressions": round(imp)})

    grp = impressions_total / target_population * 100.0 if target_population else 0.0
    reach = REACH_CAP * (1.0 - math.exp(-grp / k_eff)) if grp > 0 else 0.0
    reach = min(reach, REACH_CAP)
    frequency = (grp / 100.0) / reach if reach > 1e-9 else 0.0
    cpm = (media_net_wan * 10000.0) / impressions_total * 1000.0 if impressions_total > 0 else 0.0

    by_media: List[Dict[str, Any]] = []
    total_imp = impressions_total or 1.0
    for m in ("bus", "metro"):
        if by_media_imp[m] <= 0:
            continue
        cpm_m = (by_media_cost[m] * 10000.0) / by_media_imp[m] * 1000.0 if by_media_imp[m] else 0.0
        by_media.append({
            "media": m,
            "impressions": round(by_media_imp[m]),
            "share": round(by_media_imp[m] / total_imp, 3),
            "cpm_yuan": round(cpm_m, 2),
        })
    by_media.sort(key=lambda x: ("bus", "metro").index(x["media"]))

    return {
        "impressions": round(impressions_total),
        "grp": round(grp, 1),
        "reach": round(reach, 4),
        "reach_pct": f"{reach:.1%}",
        "frequency": round(frequency, 2),
        "cpm_yuan": round(cpm, 2),
        "target_population": int(target_population),
        "parameters": {
            "reach_cap": REACH_CAP,
            "k": reach_k,
            "k_eff": round(k_eff, 2),
            "view_rate_bus": VIEW_RATE_BUS,
            "view_rate_metro": VIEW_RATE_METRO,
            "days": days,
        },
        "by_media": by_media,
        "by_line": by_line,
        "formula": "Reach = reach_cap × (1 − exp(−GRP/k_eff)); Frequency = (GRP/100)/Reach; CPM = 折后媒体费/曝光×1000",
        "disclaimer": "曝光估算，不是到园人数/销量/财务 ROI；目标人群为策划假设。",
    }


__all__ = ["compute_effects"]
