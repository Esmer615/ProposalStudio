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


# 行业档案库（覆盖赛题五大行业 + 通用商业，供自定义公司/地标动态构建 Skill）
INDUSTRY_PROFILES: Dict[str, Dict[str, Any]] = {
    "乐园": {
        "target_population": 2_500_000,
        "reach_k": 260.0,
        "rings_km": [6, 20, 50],
        "media_mix_bounds": {"bus": {"min": 0.35, "max": 0.85}, "metro": {"min": 0.15, "max": 0.65}},
        "poi_types": "商场,景点,幼儿园,小学,小区",
        "business_goal": "把“知道该目的地”转化为“排进假期出游计划”，提升客群到访与品牌心智。",
        "campaign_goal": "以家庭亲子认知 + 出游考虑为核心，兼顾年轻客群打卡；不以直接销售转化为主 KPI。",
        "audience_primary": "上海及周边 4–12 岁孩子的家庭（决策人 30–45 岁）",
        "audience_secondary": "18–30 岁年轻打卡客群、长三角高铁周末游客",
        "persona": "关注交通便利、体验口碑与周末/假期出游性价比的家庭决策人",
        "activity_area": "大型居住社区、亲子商场、科技馆/博物馆、交通枢纽与学校周边 300–500 米",
        "creative": ["家庭一日游场景视觉", "核心地标与品牌识别", "强调交通接驳与错峰规划"],
        "compliance_notes": ["不投校内，统一口径为“学校周边 300–500 米”。", "曝光/Reach 均为模型估算，不承诺入园人数。"],
    },
    "银行保险": {
        "target_population": 3_200_000,
        "reach_k": 290.0,
        "rings_km": [3, 8, 20],
        "media_mix_bounds": {"bus": {"min": 0.25, "max": 0.70}, "metro": {"min": 0.30, "max": 0.75}},
        "poi_types": "写字楼,商场,小区,产业园",
        "business_goal": "强化品牌信任与高端专业形象，拉动核心商务圈及中产社区客群的产品认知与咨询意愿。",
        "campaign_goal": "聚焦金融/商务通勤高频触达与中产家庭品牌信任建设，严守金融广告合规口径。",
        "audience_primary": "28–55 岁上海中高端白领、企业主及家庭财富管理决策人",
        "audience_secondary": "陆家嘴/静安/徐家汇等核心 CBD 通勤人群与有房中产家庭",
        "persona": "注重机构信誉、稳健保障与长期服务口碑的金融服务客群",
        "activity_area": "核心 CBD 写字楼群、轨交换乘枢纽、中高端住宅区与精品商业综合体",
        "creative": ["简洁信任背书与品牌标识", "贴近通勤/家庭保障场景", "严守合规，不做收益率/收益承诺"],
        "compliance_notes": ["严禁承诺投资收益率或保本收益。", "所有触达与曝光指标均标注模型估算口径。"],
    },
    "食品饮料": {
        "target_population": 4_500_000,
        "reach_k": 310.0,
        "rings_km": [3, 10, 25],
        "media_mix_bounds": {"bus": {"min": 0.45, "max": 0.90}, "metro": {"min": 0.10, "max": 0.55}},
        "poi_types": "商场,超市,全家便利店,小区,写字楼",
        "business_goal": "快速打透旺季大众声量与即时饮用/购买联想，带动商超、便利店与商圈终端动销。",
        "campaign_goal": "追求全城高广度 Reach 与高频视觉记忆，覆盖通勤、午间及社区生活动线。",
        "audience_primary": "18–45 岁上海城市大众消费者、年轻上班族与家庭采购决策人",
        "audience_secondary": "高频出入便利店/商超/商圈的年轻流动客群",
        "persona": "偏好清爽直观视觉、易受高频户外曝光触发即时购买的快消受众",
        "activity_area": "主干道公交走廊、核心商圈商场、便利店/商超密集区与大型通勤地铁口",
        "creative": ["大视觉产品主图 + 强食欲/冰爽感画面", "一句话记忆点", "联动周边商超/便利店消费场景"],
        "compliance_notes": ["遵循食品广告规范，不做医疗或夸大功效宣传。", "所有曝光/CPM 指标标注模型估算口径。"],
    },
    "保健品": {
        "target_population": 2_800_000,
        "reach_k": 270.0,
        "rings_km": [3, 10, 25],
        "media_mix_bounds": {"bus": {"min": 0.45, "max": 0.85}, "metro": {"min": 0.15, "max": 0.55}},
        "poi_types": "小区,医院,商场,超市",
        "business_goal": "建立科学健康品牌心智，精准触达注重养生与家庭健康的成熟客群及送礼人群。",
        "campaign_goal": "兼顾成熟社区公交慢行渗透与核心商圈地铁高频曝光，严格遵守保健食品广告法。",
        "audience_primary": "35–65 岁注重健康管理的中产家庭及银发活力人群",
        "audience_secondary": "25–45 岁有长辈孝心礼赠或自身亚健康调理需求的白领",
        "persona": "高度关注成分权威、品牌背书与日常持续养护的家庭健康决策人",
        "activity_area": "成熟大型居住社区、综合医院/商圈周边、主干公交线路与生活枢纽地铁口",
        "creative": ["温和可信赖的健康生活场景", "突出蓝帽/权威背书", "严禁涉及疾病治疗功效宣称"],
        "compliance_notes": ["严格遵守保健食品广告规范，明示“保健食品不是药物”。", "不承诺具体销量或转化率。"],
    },
    "私立医院": {
        "target_population": 2_200_000,
        "reach_k": 240.0,
        "rings_km": [3, 8, 18],
        "media_mix_bounds": {"bus": {"min": 0.35, "max": 0.80}, "metro": {"min": 0.20, "max": 0.65}},
        "poi_types": "小区,医院,口腔医院,写字楼,商场",
        "business_goal": "提升院区所在核心辐射圈的知名度和专业信任度，吸引周边中高端家庭与白领优先考虑。",
        "campaign_goal": "以院区 3–8km 核心生活圈高浓度覆盖为主，辅以关键换乘枢纽建立专业医疗品牌形象。",
        "audience_primary": "院区周边 3–8km 内 25–55 岁中高端家庭与白领人群",
        "audience_secondary": "有口腔/妇儿/眼科/高端体检等品质医疗需求的城市中产",
        "persona": "重视就诊体验、医生资质与交通便利性的品质医疗客群",
        "activity_area": "院区周边社区主干道、临近轨交出入口、核心商务写字楼与中高端商业体",
        "creative": ["专业洁净的医疗环境与专家团队背书", "清晰院区区位与交通指引", "严格遵守医疗广告审查规范"],
        "compliance_notes": ["严格遵守《医疗广告管理办法》，不得保证治愈率或疗效。", "所有覆盖与曝光数据标注模型估算口径。"],
    },
}


def get_industry_profile(industry: str) -> Dict[str, Any]:
    ind = str(industry or "乐园").strip()
    if ind in INDUSTRY_PROFILES:
        return INDUSTRY_PROFILES[ind]
    # 模糊归类
    if any(k in ind for k in ("银行", "保险", "金融", "证券", "基金", "理财")):
        return INDUSTRY_PROFILES["银行保险"]
    if any(k in ind for k in ("食品", "饮料", "快消", "饮用水", "茶饮", "乳品", "餐饮")):
        return INDUSTRY_PROFILES["食品饮料"]
    if any(k in ind for k in ("保健", "营养", "养生", "大健康")):
        return INDUSTRY_PROFILES["保健品"]
    if any(k in ind for k in ("医院", "口腔", "医美", "眼科", "体检", "诊所", "医疗")):
        return INDUSTRY_PROFILES["私立医院"]
    if any(k in ind for k in ("乐园", "文旅", "景区", "公园", "度假")):
        return INDUSTRY_PROFILES["乐园"]
    return {
        "target_population": 3_000_000,
        "reach_k": 275.0,
        "rings_km": [3, 8, 20],
        "media_mix_bounds": {"bus": {"min": 0.30, "max": 0.80}, "metro": {"min": 0.20, "max": 0.70}},
        "poi_types": "商场,写字楼,小区",
        "business_goal": "扩大目标商圈与全城核心动线的品牌能见度，提升潜在客群的到店/咨询意愿。",
        "campaign_goal": "平衡目标地点核心辐射圈高浓度曝光与全城高客流干线广度覆盖。",
        "audience_primary": "22–50 岁上海核心城区通勤白领与品质生活家庭",
        "audience_secondary": "目标地标 3–8km 辐射圈内的常驻及流动商业客群",
        "persona": "高频活跃于主城区商圈、写字楼与轨交枢纽的城市主流消费人群",
        "activity_area": "目标地标核心辐射圈、轨交换乘枢纽、核心商圈与主干公交走廊",
        "creative": ["高对比度品牌主视觉 + 清晰核心卖点", "强化地标方位/活动节点提示", "简洁易记的户外大字排版"],
        "compliance_notes": ["不投校内，学校周边统一按 300–500 米合规口径。", "所有曝光、Reach、CPM 均标注模型估算口径。"],
    }


def build_custom_skill(custom_venue: Dict[str, Any], industry: str = "其他") -> Skill:
    """为任意全国客户公司/品牌/地标动态构建 Skill 对象。
    若客户公司位于上海之外（如贵阳、北京、深圳等），保留真实公司地址信息用于展示，
    同时在上海投放优化中使用上海市中心作为全域辐射锚点，确保三套上海户外方案求解稳定。
    """
    prof = get_industry_profile(industry)
    coords = custom_venue.get("coords") or {}
    raw_lng = float(coords.get("lng", custom_venue.get("lng", 121.4737)))
    raw_lat = float(coords.get("lat", custom_venue.get("lat", 31.2304)))
    in_shanghai = (120.8 <= raw_lng <= 122.2) and (30.65 <= raw_lat <= 31.9)
    lng = raw_lng if in_shanghai else 121.4737
    lat = raw_lat if in_shanghai else 31.2304
    raw_district = str(custom_venue.get("district") or "").strip()
    district = (raw_district or "黄浦区") if in_shanghai else "黄浦区"
    # 判断是否中心城区（中心城区默认地铁直达高，远郊自驾占比高）
    core_districts = ("黄浦区", "静安区", "徐汇区", "长宁区", "普陀区", "虹口区", "杨浦区", "浦东新区", "闵行区")
    is_core = any(d in district for d in core_districts)
    rings = [int(x) for x in (custom_venue.get("rings_km") or prof["rings_km"])]
    return Skill(
        id=str(custom_venue.get("id") or "custom"),
        name=str(custom_venue.get("name") or "自定义品牌地点"),
        district=district,
        coords={"lng": lng, "lat": lat},
        confidence="geocoded",
        target_population=int(prof["target_population"]),
        reach_k=float(prof["reach_k"]),
        rings_km=rings,
        media_mix_bounds=dict(prof["media_mix_bounds"]),
        level_weights={"S": 1.30, "A++": 1.05, "A+": 0.80, "AA": 0.65},
        poi_weights={},
        compliance_forbidden=["承诺绝对销量", "保证投资收益", "夸大医疗疗效", "校内广告"],
        compliance_notes=list(prof["compliance_notes"]),
        messaging=list(prof["creative"]),
        metro_direct=is_core,
        self_drive_share=0.28 if is_core else 0.58,
        rail_share=0.52 if is_core else 0.22,
        source=f"custom-geocoded:{industry}",
        extra={
            "industry": industry,
            "industry_profile": prof,
            "address": custom_venue.get("address") or custom_venue.get("name"),
            "company_city": custom_venue.get("city") or ("上海市" if in_shanghai else ""),
            "company_coords": {"lng": raw_lng, "lat": raw_lat},
            "is_national_client": not in_shanghai,
        },
    )


def build_skill(venue: str, custom_venue: Optional[Dict[str, Any]] = None, industry: str = "乐园") -> Skill:
    """加载并校验场馆档案，返回 Skill 对象。支持预设场馆及任意自定义公司/地标。"""
    if isinstance(custom_venue, dict) and custom_venue.get("name"):
        return build_custom_skill(custom_venue, industry=industry)
    raw = load_venue_profile(venue)
    prof = get_industry_profile(industry)
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
            extra={**(raw.get("extra") or {}), "industry": industry, "industry_profile": prof},
        )
    except (KeyError, TypeError, ValueError) as e:
        raise PlanError(
            "VALIDATION_ERROR",
            f"场馆档案 {venue} 缺少必要字段或类型错误：{e}",
            field="venue",
        )


# 供服务端 /meta 使用的渠道披露口径
VENUE_PROFILE_PATHS = {v: _venue_json_path(v) for v in BUILTIN_PROFILES}


__all__ = [
    "Skill",
    "build_skill",
    "build_custom_skill",
    "get_industry_profile",
    "INDUSTRY_PROFILES",
    "load_venue_profile",
    "BUILTIN_PROFILES",
]
