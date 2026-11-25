# -*- coding: utf-8 -*-
"""解释层：假设书七要素 / 策略一句话 / 逐点理由 / 反事实 / 回链。

所有文本只使用 JSON 中真实存在的数字；不编造数值。
"""
from __future__ import annotations

from typing import Any, Dict, List

from .skill_loader import Skill, get_industry_profile


def build_hypothesis(request, skill: Skill) -> Dict[str, Any]:
    venue_name = request.venue_name
    industry = str(getattr(request, "industry", "乐园") or "乐园")
    prof = (skill.extra or {}).get("industry_profile") or get_industry_profile(industry)
    budget = int(request.budget_wan)
    weeks = request.weeks
    start = request.start_date
    end = request.end_date
    metro_direct = "轨交覆盖便利" if skill.metro_direct else "无地铁直达、需自驾/高铁/公交接驳"
    media_labels = [
        "公交车身" if m == "bus" else "地铁出入口"
        for m in (getattr(request, "media", None) or ["bus", "metro"])
    ]
    media_str = " + ".join(media_labels)

    fields = [
        {"id": "H1", "label": "客户与品牌", "value": f"{venue_name}（{industry}行业，{skill.district or '上海市'}核心定位目标）。"},
        {"id": "H2", "label": "生意目标", "value": prof["business_goal"]},
        {"id": "H3", "label": "Campaign 目标", "value": prof["campaign_goal"]},
        {"id": "H4", "label": "目标人群", "value": f"{prof['audience_primary']}；补充 {prof['audience_secondary']}。"},
        {"id": "H5", "label": "时间与预算", "value": f"{start} 至 {end}（{weeks} 周），媒体预算 {budget} 万元（含制作）。"},
        {"id": "H6", "label": "媒体范围", "value": f"{media_str}组合：公交承担干线社区广度渗透，地铁承担交通枢纽与核心商圈定点拦截。"},
        {"id": "H7", "label": "成功衡量", "value": "目标人群有效曝光、Reach/Frequency、CPM、POI 与周边实测线路覆盖数、红豆可售核验率；以监测照片与月度报告为准。"},
    ]

    one_liner = (
        f"围绕「{venue_name}（{skill.district}）」构建公交车身广度渗透 + 地铁出入口枢纽拦截组合，"
        f"以边际递减优化与区位浓度加权为核心，用 {budget} 万预算在 {weeks} 周内实现高价值触达。"
    )
    assumptions = [
        f"{venue_name} {metro_direct}，自驾/轨交结构为策划假设，用于媒介角色分工。",
        f"目标人群 {skill.target_population:,} 为{industry}行业策划口径，不是实测去重人群。",
        "曝光、Reach、Frequency、CPM 均为模型估算，不承诺直接销量或到店/入园人数。",
    ]
    return {"fields": fields, "one_liner": one_liner, "assumptions": assumptions}


def build_strategy(request, skill: Skill) -> Dict[str, Any]:
    industry = str(getattr(request, "industry", "乐园") or "乐园")
    prof = (skill.extra or {}).get("industry_profile") or get_industry_profile(industry)
    return {
        "one_liner": f"针对{industry}客群动线，以公交做全城广度、地铁做枢纽拦截、新云覆盖与 POI 做空间浓度加权，支撑多策略组合取舍。",
        "audience": {
            "primary": prof["audience_primary"],
            "secondary": prof["audience_secondary"],
            "persona": prof["persona"],
            "activity_area": prof["activity_area"],
        },
        "transport": {
            "self_drive_share": skill.self_drive_share,
            "rail_share": skill.rail_share,
            "metro_access": ("无地铁直达，需地铁+公交/接驳" if not skill.metro_direct else "轨交覆盖便利，适合地铁枢纽联动"),
            "note": "地铁点位重点买核心换乘枢纽与目标辐射圈商圈，公交承接社区与主干走廊。",
        },
        "media_roles": [
            {"media": "bus", "role": "城市主干走廊与生活社区广度渗透", "share_target": 0.5},
            {"media": "metro", "role": "核心轨交枢纽与目标商圈定点拦截", "share_target": 0.5},
        ],
        "mix_rationale": "公交车身单价友好且覆盖面广，承担城市渗透任务；地铁出入口单价更高，换来核心枢纽高频拦截，体现“广度 vs 聚焦”的主动取舍。",
        "compliance": {
            "forbidden": list(skill.compliance_forbidden or ["保证转化人数", "承诺销售转化", "投资收益承诺", "校内广告"]),
            "notes": list(prof.get("compliance_notes") or ["不投校内，统一口径为“学校周边 300–500 米”。", "所有曝光数字标注估算口径。"]),
        },
        "creative": list(prof.get("creative") or ["高辨识度品牌主视觉", "结合目标商圈地标场景", "清晰行动引导"]),
        "avoid": [
            "只按低价排序选点位，忽略目标辐射圈匹配度",
            "把地铁 Reach 与公交 Reach 直接相加",
            "忽略单线多车边际递减效应导致过度扎堆",
            "用静态台账冒充红豆实时档期可售库存",
        ],
    }


def build_venue(request, skill: Skill) -> Dict[str, Any]:
    return {
        "id": skill.id,
        "name": skill.name,
        "district": skill.district,
        "coords": skill.coords,
        "confidence": skill.confidence,
        "rings_km": skill.rings_km,
        "access": {
            "self_drive_share": skill.self_drive_share,
            "rail_share": skill.rail_share,
            "metro_access": ("无地铁直达" if not skill.metro_direct else "地铁直达"),
            "note": "公交/地铁用于城市家庭客源拦截与接驳。",
        },
        "target_population": skill.target_population,
        "reach_k": skill.reach_k,
        "source": "公开信息 + 赛题资料，坐标近似",
    }


def build_explanations(plan_items: List[Dict[str, Any]], skill: Skill, request) -> Dict[str, Any]:
    """why_selected / why_not / trim_priority / counterfactuals / hypothesis_links。"""
    paid = [it for it in plan_items if it.get("status") != "gift"]
    why_selected = []
    for it in paid[:6]:
        reasons = it.get("reasons", [])
        first = reasons[0] if reasons else "选中该点位"
        refs = ["H4", "H6"] + (["H7"] if it.get("kind") == "metro" else [])
        why_selected.append({"item_id": it["id"], "reason": first, "hypothesis_refs": refs})

    why_not = [
        {"item": "竞品目的地站点", "reason": "家庭客群重叠但意图冲突；不买竞品门口。"},
        {"item": "远郊低等级公交线路", "reason": "单价低但家庭 POI 浓度低，曝光价值不足以抵消制作与执行成本。"},
        {"item": "纯高价地铁口全铺", "reason": "地铁单价远高于公交，全铺会牺牲公交广度与预算弹性。"},
    ]

    # trim_priority：边际效率最低（score/花费 低）先砍
    def eff_score(it):
        tot = it.get("total_wan", 0) or 1
        return it.get("score", 0) / tot
    trimmed = sorted(paid, key=eff_score)[:3]
    trim_priority = [
        {"item_id": it["id"], "reason": "边际曝光/万元较低，砍预算先砍它", "cost_wan": round(it.get("total_wan", 0), 2)}
        for it in trimmed
    ]

    counterfactuals = {
        "budget_100": "砍预算时保留高分公交 + 少量高价枢纽，放弃铺底线路与低效地铁口。",
        "venue_switch": "换场地后地铁直达权重上升，公交占比相应下调。",
        "inventory_conflict": "目标点位被占时按“同站其他口→相邻枢纽→同区县替代”顺序替换，保持预算与配比不变。",
    }
    hypothesis_links = {
        "H1": ["venue", "strategy.audience"],
        "H2": ["effects", "plan.summary"],
        "H3": ["strategy.media_roles", "effects"],
        "H4": ["coverage.poi_hits", "plan.bus", "plan.metro"],
        "H5": ["inputs", "quote", "schedule"],
        "H6": ["plan.summary.media_mix", "coverage"],
        "H7": ["validation.inventory_check", "schedule.monitoring", "effects"],
    }
    return {
        "why_selected": why_selected,
        "why_not": why_not,
        "trim_priority": trim_priority,
        "counterfactuals": counterfactuals,
        "hypothesis_links": hypothesis_links,
    }


__all__ = ["build_hypothesis", "build_strategy", "build_venue", "build_explanations"]
