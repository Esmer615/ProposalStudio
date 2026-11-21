# -*- coding: utf-8 -*-
"""解释层：假设书七要素 / 策略一句话 / 逐点理由 / 反事实 / 回链。

所有文本只使用 JSON 中真实存在的数字；不编造数值。
"""
from __future__ import annotations

from typing import Any, Dict, List

from .skill_loader import Skill


def build_hypothesis(request, skill: Skill) -> Dict[str, Any]:
    venue_name = request.venue_name
    budget = int(request.budget_wan)
    weeks = request.weeks
    start = request.start_date
    end = request.end_date
    metro_direct = "有地铁直达" if skill.metro_direct else "无地铁直达、需自驾/高铁/接驳"

    fields = [
        {"id": "H1", "label": "客户与品牌", "value": f"{venue_name}（主题乐园，{skill.district}，2027 暑期亲子出游头部目的地）。"},
        {"id": "H2", "label": "生意目标", "value": "把“知道该乐园”转化为“排进暑期一日游计划”，提升暑期入园与家庭客群到访。"},
        {"id": "H3", "label": "Campaign 目标", "value": "以家庭亲子认知 + 暑期出游考虑为核心，兼顾年轻客群打卡；不以直接销售转化为主 KPI。"},
        {"id": "H4", "label": "目标人群", "value": f"上海及周边 4–12 岁孩子的家庭（决策人 30–45 岁）；补充 18–30 岁年轻打卡客群。"},
        {"id": "H5", "label": "时间与预算", "value": f"{start} 至 {end}（{weeks} 周，暑期档），媒体预算 {budget} 万元（含制作）。"},
        {"id": "H6", "label": "媒体范围", "value": "公交车身 + 地铁出入口组合：公交做家庭社区广度，地铁做交通枢纽与亲子商圈拦截。"},
        {"id": "H7", "label": "成功衡量", "value": "目标人群有效曝光、Reach/Frequency、CPM、POI 覆盖数、红豆可售核验率；以监测照片与月度报告为准。"},
    ]

    one_liner = f"用公交车身把{venue_name}带进全城家庭的暑期清单，用地铁出入口在交通枢纽与亲子商圈做定点拦截；预算优先买“家庭浓度”，不买单纯低价点位。"
    assumptions = [
        f"{venue_name} {metro_direct}，自驾占比为策划假设，用于媒介角色分工。",
        f"目标人群 {skill.target_population:,} 为上海及周边亲子家庭策划口径，不是实测去重人群。",
        "曝光、Reach、Frequency、CPM 均为模型估算，不承诺入园人数或销售转化。",
    ]
    return {"fields": fields, "one_liner": one_liner, "assumptions": assumptions}


def build_strategy(request, skill: Skill) -> Dict[str, Any]:
    return {
        "one_liner": "公交做广度、地铁做枢纽、POI 做家庭浓度加权；用可解释的选点理由支撑组合。",
        "audience": {
            "primary": "4–12 岁孩子的上海家庭，30–45 岁决策人",
            "secondary": "18–30 岁年轻打卡客群、长三角高铁亲子游客",
            "persona": "周末/暑期带孩子出游的家长，关注交通便利、排队时间与性价比",
            "activity_area": "大型居住区、亲子商场、科技馆/博物馆、交通枢纽、儿童医院周边",
        },
        "transport": {
            "self_drive_share": skill.self_drive_share,
            "rail_share": skill.rail_share,
            "metro_access": ("无地铁直达，需地铁+公交/接驳" if not skill.metro_direct else "地铁直达，公共交通便利"),
            "note": "地铁点位重点买“家庭出发枢纽”和“亲子商圈”。",
        },
        "media_roles": [
            {"media": "bus", "role": "城市广度与家庭社区渗透", "share_target": 0.5},
            {"media": "metro", "role": "交通枢纽/亲子商圈定点拦截", "share_target": 0.5},
        ],
        "mix_rationale": "公交车身承担“把目的地带进社区”的广度任务；地铁出入口单价高，换来交通枢纽的家庭出发拦截，是“广度 vs 枢纽”的主动取舍。",
        "compliance": {
            "forbidden": ["保证入园人数", "承诺销售转化", "投资收益承诺", "校内广告"],
            "notes": ["不投校内，统一口径为“学校周边 300–500 米”。", "所有曝光数字标注估算口径。"],
        },
        "creative": [
            "暑期亲子一日游场景：从家出发到乐园的一天",
            "主题角色 + 城市地标",
            "强调“提前规划、错峰入园、交通接驳”",
        ],
        "avoid": [
            "只按价格排序选点位",
            "把地铁 reach 与公交 reach 相加",
            "用静态台账 free 冒充暑期库存",
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
