# -*- coding: utf-8 -*-
"""全国客户公司调研与投放策略顾问 Agent：
- 支持全国任意客户公司/品牌输入（不限上海，如贵州老干妈、华为、比亚迪、字节跳动、中国平安、上海乐高乐园等）；
- 接入 DeepSeek LLM 自主识别企业全称、推断所属行业/细分赛道、梳理核心客群与户外广告投放策略；
- 两阶段高德全国地图定位闭环：
  1) Phase 1（lookup_done=False）：Agent 识别客户公司全称并生成精准全国高德检索词（search_queries），
     由前端高德地图 PlaceSearch 全国检索真实公司地址与经纬度；
  2) Phase 2（lookup_done=True）：Agent 核实真实高德地址，输出结构化「客户档案与广告策略确认卡」（company_profile），
     同步定位高德地图与表单参数，并在对话中返回给用户确认或调整。
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple

from engine.models import INDUSTRIES, STRATEGY_MODES, VENUES
from .data_skills import DataSkillRuntime, default_data_runtime, fallback_geocode_shanghai
from .intake import (
    _extract_budget,
    _extract_customer_type,
    _extract_media,
    _extract_start_date,
    _extract_venue,
    _extract_weeks,
    normalize_text,
)
from .llm import DeepSeekLLM, _parse_json, build_llm

_INDUSTRY_KEYWORDS: List[Tuple[str, List[str]]] = [
    ("银行保险", [
        "银行", "保险", "平安", "招行", "招商银行", "建行", "工行", "农行", "中行",
        "友邦", "太保", "太平洋保险", "人保", "国寿", "理财", "基金", "证券", "金融", "信托",
    ]),
    ("食品饮料", [
        "饮用水", "矿泉水", "饮料", "食品", "奶茶", "咖啡", "可乐", "牛奶", "乳业", "啤酒", "白酒", "零食",
        "农夫山泉", "元气森林", "瑞幸", "星巴克", "百岁山", "快消", "老干妈", "辣椒酱", "调味", "酱油",
        "海天", "伊利", "蒙牛", "康师傅", "统一", "旺旺", "霸王茶姬", "喜茶", "蜜雪冰城", "餐饮", "火锅",
        "海底捞", "茅台", "五粮液", "青岛啤酒", "娃哈哈", "东鹏", "卫龙", "三只松鼠", "良品铺子",
    ]),
    ("保健品", [
        "保健品", "保健", "营养", "维生素", "益生菌", "养生", "燕窝", "汤臣倍健",
        "蛋白粉", "大健康", "阿胶", "钙片", "东阿阿胶", "斯维诗", "swisse",
    ]),
    ("私立医院", [
        "医院", "口腔", "牙科", "眼科", "医美", "体检", "诊所", "妇儿",
        "和睦家", "美年", "爱尔", "瑞尔", "齿科", "医疗", "康复", "通策",
    ]),
    ("乐园", [
        "乐园", "迪士尼", "乐高", "海昌", "欢乐谷", "天文馆", "野生动物园",
        "主题公园", "景区", "文旅", "度假区", "海洋公园", "长隆", "方特", "环球影城",
    ]),
]

_INDUSTRY_DEFAULT_PROFILE: Dict[str, Dict[str, Any]] = {
    "食品饮料": {
        "industry_detail": "快消食品 / 饮料调味品",
        "core_business": "面向大众消费市场的快消食品饮料品牌，重视高频曝光与商超/餐饮渠道转化",
        "target_audience": "全年龄段家庭消费者、年轻上班族及商超日常采购人群",
        "ad_strategy_mode": "max_reach",
        "ad_strategy_label": "全域广度 · 高频国民曝光",
        "ad_strategy_reason": "推荐公交车身全城流动高频曝光叠加地铁换乘枢纽触达，快速放大品牌大众声量并拉动终端商超动销。",
        "recommended_media": ["bus", "metro"],
    },
    "银行保险": {
        "industry_detail": "银行 / 保险 / 综合金融服务",
        "core_business": "面向城市白领、家庭资产配置及企业主的综合金融与保障服务机构",
        "target_audience": "25–55 岁高净值商务人士、核心商圈白领及中产家庭决策者",
        "ad_strategy_mode": "precision",
        "ad_strategy_label": "核心商圈与商务干线精准聚焦",
        "ad_strategy_reason": "优先锁定 CBD 写字楼、高端社区及核心轨交枢纽周边高价值点位，以高质感大画幅强化品牌信任背书。",
        "recommended_media": ["bus", "metro"],
    },
    "保健品": {
        "industry_detail": "营养健康 / 膳食补充剂",
        "core_business": "聚焦家庭健康管理与细分营养补充的大健康消费品牌",
        "target_audience": "注重养生保健的中青年白领、银发群体及家庭健康采购者",
        "ad_strategy_mode": "balanced",
        "ad_strategy_label": "均衡首选 · 社区与通勤双覆盖",
        "ad_strategy_reason": "结合社区干线公交与主力地铁通勤出入口，在早晚高峰建立持续健康心智，兼顾覆盖广度与单次触达效率。",
        "recommended_media": ["bus", "metro"],
    },
    "私立医院": {
        "industry_detail": "专科医疗 / 口腔眼科体检服务",
        "core_business": "提供高品质诊疗、口腔/眼科或健康体检服务的专业医疗机构",
        "target_audience": "中高端城市家庭、白领及周边 3–8km 高潜力就诊人群",
        "ad_strategy_mode": "precision",
        "ad_strategy_label": "高浓聚焦 · 周边与精准客群触达",
        "ad_strategy_reason": "围绕核心客群居住与办公圈层密集投放，突出专业资质与便捷到院引导，降低获客成本。",
        "recommended_media": ["metro", "bus"],
    },
    "乐园": {
        "industry_detail": "主题乐园 / 文旅目的地",
        "core_business": "面向亲子家庭与年轻潮流客群的沉浸式文旅娱乐目的地",
        "target_audience": "亲子家庭客群、周末短途出游人群及年轻社交打卡群体",
        "ad_strategy_mode": "balanced",
        "ad_strategy_label": "均衡首选 · 亲子社区与交通枢纽联动",
        "ad_strategy_reason": "以大画幅公交车身打造强视觉记忆，联动地铁换乘大站与亲子商圈出入口，高效拉动周末及节假日购票转化。",
        "recommended_media": ["bus", "metro"],
    },
    "其他": {
        "industry_detail": "综合商业 / 科技制造与服务品牌",
        "core_business": "具备全国或区域影响力的商业品牌，计划通过上海核心户外媒体提升品牌知名度",
        "target_audience": "城市主流消费人群、商务通勤白领及核心商圈活跃客群",
        "ad_strategy_mode": "balanced",
        "ad_strategy_label": "均衡首选 · 全城主干与地标兼顾",
        "ad_strategy_reason": "推荐公交车身与地铁出入口组合投放，在主干商圈建立品牌高度的同时保证全城稳定触达频次。",
        "recommended_media": ["bus", "metro"],
    },
}

_STRATEGY_KEYWORDS: List[Tuple[str, List[str]]] = [
    ("max_reach", ["广度", "全城", "覆盖", "曝光最大", "铺开", "声量", "性价比", "低cpm", "cpm低"]),
    ("precision", ["聚焦", "精准", "周边", "地标", "核心圈", "高浓度", "高频", "门店周边", "公司周边", "高端"]),
    ("balanced", ["均衡", "平衡", "兼顾", "推荐", "综合"]),
]

# 注意：严禁把“位置”“行业”这类属性词误当成企业名前缀！
_BRACKET_COMPANY = re.compile(r"「([^「」]{2,36})」")
_PLACE_PATTERNS = [
    re.compile(r"(?:客户公司是|客户是|公司叫|公司是|企业叫|企业是|品牌叫|品牌是|我们是|我是|查询|调研|查找|定位到|定位|换成|改到)\s*[：:]?\s*「?([A-Za-z0-9\u4e00-\u9fa5（）()·\-]{2,30})」?"),
    re.compile(r"^([A-Za-z0-9\u4e00-\u9fa5（）()·\-]{2,28}(?:有限责任公司|股份有限公司|有限公司|企业|公司|集团|总部|银行|保险|医院|诊所|乐园|公园|科技|食品|饮料|汽车|药业))$"),
]

_STOP_PLACES = {
    "上海", "上海市", "公交", "地铁", "全媒体", "公交车身", "地铁出入口", "直客", "代理", "4a", "4a代理",
    "方案", "三套方案", "广告", "预算", "暑期", "国庆", "五一", "今年", "明年", "均衡", "均衡首选",
    "广度", "全域广度", "聚焦", "地标聚焦", "公司", "品牌", "客户", "企业", "行业", "所属行业", "和所属行业",
    "你好", "您好", "确认", "确认无误", "好的", "可以", "没问题", "信息", "地址", "位置", "策略", "广告策略",
}


def _extract_industry(text: str) -> Optional[str]:
    low = text.lower()
    for ind, kws in _INDUSTRY_KEYWORDS:
        if any(kw.lower() in low for kw in kws):
            return ind
    return None


def _extract_strategy(text: str) -> Optional[str]:
    low = text.lower()
    for mode, kws in _STRATEGY_KEYWORDS:
        if any(kw.lower() in low for kw in kws):
            return mode
    return None


def _clean_company_name(raw: str) -> str:
    cand = (raw or "").strip(" ，。！？；、\"'“”‘’「」【】")
    cand = re.split(
        r"(?:这家|这间|这个|的(?:地址|位置|行业|信息|预算|公司)|预算|投|想|准备|需要|做|，|,|。|；|;|\d+万|\d+周|直客|4[aA]|代理|公交|地铁)",
        cand,
    )[0].strip()
    if len(cand) > 3 and cand.endswith("企业"):
        cand = cand[:-2].strip()
    return cand


def _extract_company_rule(text: str, enterprise_hint: Optional[str] = None) -> Optional[str]:
    if enterprise_hint and enterprise_hint.strip():
        return _clean_company_name(enterprise_hint)

    bm = _BRACKET_COMPANY.search(text)
    if bm:
        cand = _clean_company_name(bm.group(1))
        if len(cand) >= 2 and cand.lower() not in _STOP_PLACES:
            return cand

    for pat in _PLACE_PATTERNS:
        m = pat.search(text)
        if not m:
            continue
        cand = _clean_company_name(m.group(1))
        if len(cand) >= 2 and cand.lower() not in _STOP_PLACES and not re.fullmatch(r"\d+", cand):
            return cand

    # 极简输入（如直接发“贵州老干妈”“比亚迪”“胖东来”）
    stripped = text.strip(" ，。！？；、")
    if (
        2 <= len(stripped) <= 22
        and not re.search(r"(?:预算|\d+万|\d+周|直客|4[aA]|代理|公交|地铁|档期|\d{4}[.\-/]\d{1,2}|生成|均衡|广度|聚焦|你好|您好|谢谢|确认|好的|可以|换|改)", stripped)
        and stripped.lower() not in _STOP_PLACES
    ):
        cand = _clean_company_name(stripped)
        if len(cand) >= 2 and cand.lower() not in _STOP_PLACES:
            return cand
    return None


def _sanitize_candidates(raw_list: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """清洗全国高德 PlaceSearch 传来的候选公司地址列表。"""
    cleaned: List[Dict[str, Any]] = []
    seen = set()
    for item in raw_list or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("matched_name") or "").strip()
        try:
            lng = float(item.get("lng"))
            lat = float(item.get("lat"))
        except (TypeError, ValueError):
            continue
        if not name or not (-180 <= lng <= 180 and -90 <= lat <= 90):
            continue
        key = (name, round(lng, 4), round(lat, 4))
        if key in seen:
            continue
        seen.add(key)
        province = str(item.get("province") or item.get("pname") or "").strip()
        city = str(item.get("city") or item.get("cityname") or "").strip()
        district = str(item.get("district") or item.get("adname") or "").strip()
        address = str(item.get("address") or "").strip()
        is_shanghai = ("上海" in (province + city + address)) or (120.8 <= lng <= 122.2 and 30.65 <= lat <= 31.9)
        if is_shanghai and not city:
            city = "上海市"
        full_addr = address
        if full_addr and city and city not in full_addr:
            prefix = f"{province}{city}" if province and province != city and province not in city else city
            full_addr = f"{prefix}{district if district and district not in full_addr else ''}{full_addr}"
        elif not full_addr:
            prefix = f"{province}{city}" if province and province != city else (city or province)
            full_addr = f"{prefix}{district}{name}"
        cleaned.append({
            "name": name,
            "province": province,
            "city": city,
            "district": district,
            "address": full_addr,
            "lng": round(lng, 6),
            "lat": round(lat, 6),
            "is_shanghai": is_shanghai,
            "type": str(item.get("type") or "").strip(),
            "source": str(item.get("source") or "高德地图全国检索"),
        })
    return cleaned[:8]


def _make_custom_venue(cand: Dict[str, Any], display_name: Optional[str] = None) -> Dict[str, Any]:
    cand_name = str(cand.get("name") or "").strip()
    raw_disp = str(display_name or "").strip()
    final_name = raw_disp if raw_disp and len(raw_disp) >= len(cand_name) else (cand_name or raw_disp or "客户公司")
    return {
        "id": "custom",
        "name": final_name,
        "matched_name": cand_name or final_name,
        "province": cand.get("province") or "",
        "city": cand.get("city") or ("上海市" if cand.get("is_shanghai", False) else ""),
        "district": cand.get("district") or "",
        "address": cand.get("address") or cand_name or "",
        "coords": {"lng": float(cand["lng"]), "lat": float(cand["lat"])},
        "rings_km": [3, 8, 20],
        "is_shanghai": bool(cand.get("is_shanghai", False)),
        "source": cand.get("source") or "高德地图定位",
    }


def _build_rule_company_profile(
    company_name: str,
    industry: str,
    chosen: Optional[Dict[str, Any]] = None,
    strategy_override: Optional[str] = None,
) -> Dict[str, Any]:
    ind = industry if industry in INDUSTRIES else "其他"
    base = _INDUSTRY_DEFAULT_PROFILE.get(ind, _INDUSTRY_DEFAULT_PROFILE["其他"])
    strat_mode = strategy_override if strategy_override in STRATEGY_MODES else base["ad_strategy_mode"]
    strat_label = STRATEGY_MODES[strat_mode]["short"] if strategy_override in STRATEGY_MODES else base["ad_strategy_label"]
    return {
        "company_name": company_name or (chosen.get("name") if chosen else "待确认客户公司"),
        "address": (chosen.get("address") if chosen else "") or "待核实公司地址",
        "city": (chosen.get("city") if chosen else "") or "",
        "district": (chosen.get("district") if chosen else "") or "",
        "industry": ind,
        "industry_detail": base["industry_detail"],
        "core_business": base["core_business"],
        "target_audience": base["target_audience"],
        "ad_strategy_mode": strat_mode,
        "ad_strategy_label": strat_label,
        "ad_strategy_reason": base["ad_strategy_reason"],
        "recommended_media": list(base["recommended_media"]),
    }


def _call_llm_agent(
    message: str,
    draft: Dict[str, Any],
    history: List[Dict[str, str]],
    candidates: List[Dict[str, Any]],
    lookup_done: bool,
    enterprise_hint: Optional[str] = None,
    *,
    llm_mode: str = "auto",
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """调用 DeepSeek LLM 调研全国客户公司信息、核实高德地址并生成广告策略确认建议。"""
    llm = build_llm(llm_mode)
    if not getattr(llm, "available", False):
        return None, getattr(llm, "reason", "LLM 未启用")
    if isinstance(llm, DeepSeekLLM):
        llm.timeout = 22.0

    system_prompt = """你是「新云媒介提案台」的资深 AI 客户调研与户外广告策略顾问 Agent。

产品核心业务流程（请严格遵循）：
1. 用户输入的是【客户公司/品牌名称】，这家客户公司可以位于【全国各地】（例如：贵州老干妈在贵州省贵阳市、华为在深圳市、比亚迪在深圳市、字节跳动在北京市、胖东来在河南许昌、上海乐高乐园在上海金山区、中国平安在深圳或上海）。
2. 工作台右侧的高德地图用于【精准定位该客户公司的真实地址】（全国范围，绝对不要强行把外地公司定到上海人民广场，也不要因为公司在外省就拒绝定位！）。
3. 当用户提到一家客户公司时，你的任务是：
   - 识别并核实该客户公司的规范全称（如「贵州老干妈」→「贵阳南明老干妈风味食品有限责任公司」；如用户输入不准确或有简称/错别字，主动纠偏并在回复中说明）。
   - 如果 `lookup_done` 为 false（尚未查高德地图），且本轮提及了新客户公司（且不是页面预设三大乐园）：
     设置 `need_map_search: true`，并给出 1~3 个最适合高德地图【全国检索】的精准关键词 `search_queries`（优先填企业官方全称或“城市+企业名”，例如 ["贵阳南明老干妈风味食品有限责任公司", "老干妈总部", "贵州老干妈"]）。
   - 如果 `lookup_done` 为 true，请审核传入的全国高德地图真实候选点 `place_candidates`：
     a) 优先选择最匹配该客户公司【总部/主办公地址】的真实候选（不要选无关的小餐馆/便利店），设置 `selected_candidate_index`，并将 `location_status` 设为：
        - `"located"`：已找到准确匹配的公司地址（会在高德地图直接定位标出，并在聊天中展示客户调研卡片请用户确认）；
        - `"needs_confirm"`：存在多个同名公司/主要分支需要用户挑一个，或高德只找到近似地址；
        - `"not_found"`：`place_candidates` 为空或全部与客户公司无关，诚实告知用户高德未找到精确地址并请用户核实公司全称或补充所在城市/地址。
4. 自主整理客户公司信息与广告策略（写入 `company_profile` 对象，供前端渲染成清晰卡片请用户确认）：
   - `company_name`：核实后的客户公司全称
   - `industry`：必须归类到 6 选 1：["乐园", "银行保险", "食品饮料", "保健品", "私立医院", "其他"]
   - `industry_detail`：细分赛道（如“辣椒调味品 / 快消食品”）
   - `core_business`：一句话概括主营业务与品牌特点
   - `target_audience`：一句话概括核心目标受众
   - `ad_strategy_mode`：推荐户外投放策略，3 选 1：`"balanced"`（均衡首选）| `"max_reach"`（全域广度）| `"precision"`（核心地标聚焦）
   - `ad_strategy_label`：策略标题（如“全域广度 · 高频国民曝光”）
   - `ad_strategy_reason`：1~2 句针对该客户公司的户外公交/地铁广告策略建议（严禁编造具体报价、点位数、CPM 或曝光数字！）
   - `recommended_media`：推荐媒介数组，如 `["bus", "metro"]`、`["bus"]` 或 `["metro"]`
5. 多轮确认：
   - 调研出客户公司地址、行业与广告策略后，在 `reply` 中用简洁自然的中文向用户汇报并请用户确认（例如：“已为您定位到客户公司地址，并自动匹配了所属行业与广告策略建议，请确认以上信息是否准确，或告诉我需要调整的预算/档期/策略。”）。
   - 当用户明确回复「确认」「没问题」「可以」或确认了全部关键参数时，设置 `user_confirmed: true`。
   - 同时提取用户本轮提到的 `budget_wan`（10~5000）、`weeks`（2~52）、`start_date`（YYYY-MM-01）、`media`、`customer_type`（direct/4a）、`strategy_mode`。未提及则为 null。

必须严格输出单个 JSON 对象（不要 Markdown 代码块，不要多余解释）：
{
  "enterprise_query": "本轮识别的客户公司原词，无则 null",
  "canonical_enterprise": "核实后的客户公司规范全称，无则 null",
  "need_map_search": false,
  "search_queries": [],
  "location_status": "located | confirmed | needs_confirm | not_found | unchanged",
  "selected_candidate_index": null,
  "user_confirmed": false,
  "company_profile": {
    "company_name": "",
    "industry": "食品饮料",
    "industry_detail": "",
    "core_business": "",
    "target_audience": "",
    "ad_strategy_mode": "balanced",
    "ad_strategy_label": "",
    "ad_strategy_reason": "",
    "recommended_media": ["bus", "metro"]
  },
  "industry": null,
  "budget_wan": null,
  "weeks": null,
  "start_date": null,
  "media": null,
  "customer_type": null,
  "strategy_mode": null,
  "reply": "给用户的自然、简洁中文回复（不超过 140 字，不要用 ** 星号）",
  "suggestions": [
    {"label": "按钮文案", "send_text": "点击后发送给Agent的话", "action": "optional: generate | pick_candidate | confirm_profile", "candidate_index": 0}
  ]
}"""

    compact_draft = {
        "venue": draft.get("venue"),
        "custom_venue": draft.get("custom_venue"),
        "venue_confirmed": bool(draft.get("venue_confirmed")),
        "company_profile": draft.get("company_profile"),
        "industry": draft.get("industry"),
        "budget_wan": draft.get("budget_wan"),
        "weeks": draft.get("weeks"),
        "start_date": draft.get("start_date"),
        "media": draft.get("media"),
        "customer_type": draft.get("customer_type"),
        "strategy_mode": draft.get("strategy_mode"),
    }
    compact_cands = [
        {
            "index": i,
            "name": c["name"],
            "province": c.get("province", ""),
            "city": c["city"],
            "district": c["district"],
            "address": c["address"],
            "type": c.get("type", ""),
        }
        for i, c in enumerate(candidates)
    ]

    messages: List[Dict[str, str]] = [{"role": "system", "content": system_prompt}]
    for h in (history or [])[-8:]:
        role = h.get("role")
        content = str(h.get("content") or "").strip()
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content[:500]})

    user_payload = {
        "user_message": message,
        "enterprise_hint_from_input_box": enterprise_hint,
        "current_draft": compact_draft,
        "lookup_done": lookup_done,
        "place_candidates": compact_cands,
    }
    messages.append({"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)})

    raw = llm._chat(
        messages,
        max_tokens=1100,
        temperature=0.15,
        response_format={"type": "json_object"},
    )
    if not raw:
        return None, getattr(llm, "last_error", "LLM 返回为空")
    parsed = _parse_json(raw)
    if not isinstance(parsed, dict):
        return None, "LLM JSON 解析失败"
    return parsed, None


def consult_turn(
    message: str,
    draft: Optional[Dict[str, Any]] = None,
    history: Optional[List[Dict[str, str]]] = None,
    *,
    place_candidates: Optional[List[Dict[str, Any]]] = None,
    lookup_done: bool = False,
    enterprise_hint: Optional[str] = None,
    llm_mode: str = "auto",
    data_runtime: Optional[DataSkillRuntime] = None,
) -> Dict[str, Any]:
    """处理一轮用户与 Agent 的交互：调研全国客户公司、定位高德地址、输出行业与广告策略供用户确认。"""
    text = normalize_text(message or "")
    state = dict(draft or {})
    updates: List[str] = []
    geocoded: Optional[Dict[str, Any]] = None
    _ = data_runtime or default_data_runtime()
    candidates = _sanitize_candidates(place_candidates)

    # 0) 确定性规则提取硬参数（配合 LLM 兜底与补漏）
    venue_slot, _ = _extract_venue(text, list(VENUES.keys()))
    rule_industry = _extract_industry(f"{enterprise_hint or ''} {text}")
    budget_slot, _ = _extract_budget(text)
    media_slot = _extract_media(text)
    date_slot = _extract_start_date(text)
    weeks_slot = _extract_weeks(text)
    cust_slot = _extract_customer_type(text)
    rule_strategy = _extract_strategy(text)
    rule_company = _extract_company_rule(text, enterprise_hint=enterprise_hint)

    preset_hit_id: Optional[str] = None
    if venue_slot and venue_slot.value in VENUES and not enterprise_hint:
        preset_hit_id = str(venue_slot.value)

    # 若本地上海预设地标精确命中且用户明确提了上海地标，可作为补充候选，但仍允许全国高德检索
    if not candidates and not preset_hit_id and rule_company:
        local_hit = fallback_geocode_shanghai(rule_company, allow_default_center=False)
        if local_hit.get("ok") and local_hit.get("verified"):
            candidates = _sanitize_candidates([local_hit])

    # 1) 调用 DeepSeek LLM Agent 进行客户公司调研与定位决策
    llm_res, llm_error = _call_llm_agent(
        text,
        state,
        history or [],
        candidates,
        lookup_done or bool(preset_hit_id),
        enterprise_hint=enterprise_hint,
        llm_mode=llm_mode,
    )
    agent_mode = "llm" if llm_res else "rule"

    # Phase 1：需要前端用高德地图【全国检索】客户公司真实地址
    if not lookup_done and not preset_hit_id:
        if llm_res and llm_res.get("need_map_search"):
            raw_queries = llm_res.get("search_queries") or []
            queries = [str(q).strip() for q in raw_queries if str(q).strip()][:3]
            ent_q = str(
                llm_res.get("canonical_enterprise")
                or llm_res.get("enterprise_query")
                or rule_company
                or ""
            ).strip()
            if ent_q and ent_q not in queries:
                queries.insert(0, ent_q)
            if queries:
                return {
                    "ok": True,
                    "need_place_lookup": True,
                    "search_queries": queries[:3],
                    "pending_enterprise": ent_q or queries[0],
                    "reply": "",
                    "draft": state,
                    "updates": [],
                    "geocoded": None,
                    "company_profile": None,
                    "candidates": [],
                    "suggestions": [],
                    "ready_to_run": False,
                    "location_status": "searching",
                    "agent_mode": "llm",
                    "llm_error": None,
                }
        elif not llm_res and rule_company and not candidates:
            return {
                "ok": True,
                "need_place_lookup": True,
                "search_queries": [rule_company, f"{rule_company} 总部"],
                "pending_enterprise": rule_company,
                "reply": "",
                "draft": state,
                "updates": [],
                "geocoded": None,
                "company_profile": None,
                "candidates": [],
                "suggestions": [],
                "ready_to_run": False,
                "location_status": "searching",
                "agent_mode": "rule",
                "llm_error": llm_error,
            }

    # 2) 解析并同步位置、行业、策略与客户档案
    location_status = "unchanged"
    chosen_cand: Optional[Dict[str, Any]] = None
    enterprise_name = str(
        (llm_res or {}).get("canonical_enterprise")
        or (llm_res or {}).get("enterprise_query")
        or rule_company
        or ((state.get("custom_venue") or {}).get("name") if isinstance(state.get("custom_venue"), dict) else "")
        or ""
    ).strip()

    user_explicit_confirm = bool(
        (llm_res or {}).get("user_confirmed")
        or re.search(r"(?:确认无误|确认信息|确认定位|确认策略|信息准确|就按这个|没问题)", text)
    )

    if preset_hit_id:
        vinfo = VENUES[preset_hit_id]
        state["venue"] = preset_hit_id
        state.pop("custom_venue", None)
        state["venue_confirmed"] = True
        state["industry"] = state.get("industry") or "乐园"
        location_status = "confirmed"
        enterprise_name = vinfo["name"]
        updates.append(f"客户目标已定位「{vinfo['name']}」")
    elif llm_res:
        loc_st = str(llm_res.get("location_status") or "unchanged").strip()
        if loc_st in ("located", "confirmed", "needs_confirm", "not_found", "unchanged"):
            location_status = loc_st
        sel_idx = llm_res.get("selected_candidate_index")
        if isinstance(sel_idx, int) and 0 <= sel_idx < len(candidates):
            chosen_cand = candidates[sel_idx]
        elif candidates and location_status in ("located", "confirmed", "needs_confirm"):
            chosen_cand = candidates[0]

        if chosen_cand:
            cv = _make_custom_venue(chosen_cand, display_name=enterprise_name or chosen_cand["name"])
            state["venue"] = "custom"
            state["custom_venue"] = cv
            state["venue_confirmed"] = (location_status == "confirmed") or user_explicit_confirm
            geocoded = chosen_cand
            loc_area = f"{chosen_cand.get('city') or ''}{chosen_cand.get('district') or ''}" or "全国"
            updates.append(f"已定位「{cv['name']}」（{loc_area}）")
        elif location_status == "not_found":
            state["venue_confirmed"] = False
            if enterprise_name:
                state["pending_enterprise"] = enterprise_name
        elif user_explicit_confirm and (state.get("custom_venue") or state.get("venue") in VENUES):
            state["venue_confirmed"] = True
            location_status = "confirmed"
    else:
        # 规则模式处理全国高德候选点
        if candidates:
            chosen_cand = candidates[0]
            cv = _make_custom_venue(chosen_cand, display_name=enterprise_name or chosen_cand["name"])
            state["venue"] = "custom"
            state["custom_venue"] = cv
            location_status = "confirmed" if user_explicit_confirm else ("located" if len(candidates) == 1 else "needs_confirm")
            state["venue_confirmed"] = user_explicit_confirm or (len(candidates) == 1)
            geocoded = chosen_cand
            loc_area = f"{chosen_cand.get('city') or ''}{chosen_cand.get('district') or ''}" or "全国"
            updates.append(f"已定位「{cv['name']}」（{loc_area}）")
        elif lookup_done and rule_company:
            location_status = "not_found"
            state["pending_enterprise"] = rule_company
            state["venue_confirmed"] = False
        elif user_explicit_confirm and (state.get("custom_venue") or state.get("venue") in VENUES):
            state["venue_confirmed"] = True
            location_status = "confirmed"

    # 构造结构化「客户公司档案与广告策略」(company_profile)
    raw_prof = (llm_res or {}).get("company_profile") if isinstance((llm_res or {}).get("company_profile"), dict) else None
    llm_ind = (llm_res or {}).get("industry") or (raw_prof.get("industry") if raw_prof else None)
    ind = llm_ind if llm_ind in INDUSTRIES else (rule_industry or state.get("industry") or "其他")
    if ind in INDUSTRIES and (llm_ind in INDUSTRIES or rule_industry):
        if ind != state.get("industry"):
            updates.append(f"所属行业「{ind}」")
        state["industry"] = ind

    # 预算（支持 10–5000 万）
    llm_budget = (llm_res or {}).get("budget_wan")
    b_raw = llm_budget if isinstance(llm_budget, (int, float)) and llm_budget >= 10 else (budget_slot.value if budget_slot and budget_slot.value is not None else None)
    if b_raw is not None:
        bval = max(10.0, min(5000.0, float(b_raw)))
        state["budget_wan"] = int(round(bval))
        updates.append(f"预算 {state['budget_wan']} 万")

    # 策略倾向（用户明确提出 > LLM 推荐 > 行业默认）
    llm_strat = (llm_res or {}).get("strategy_mode") or (raw_prof.get("ad_strategy_mode") if raw_prof else None)
    strat_val = rule_strategy or (llm_strat if llm_strat in STRATEGY_MODES else None)
    if strat_val:
        if strat_val != state.get("strategy_mode"):
            updates.append(f"策略「{STRATEGY_MODES[strat_val]['short']}」")
        state["strategy_mode"] = strat_val

    # 媒介
    llm_media = (llm_res or {}).get("media")
    valid_llm_media = [m for m in llm_media if m in ("bus", "metro")] if isinstance(llm_media, list) else []
    media_val = valid_llm_media or (list(media_slot.value) if media_slot and media_slot.value else [])
    if media_val:
        state["media"] = media_val
        lbl = " + ".join("公交车身" if m == "bus" else "地铁出入口" for m in state["media"])
        updates.append(f"媒介 {lbl}")

    # 档期 / 周数 / 客户类型
    llm_date = (llm_res or {}).get("start_date")
    if isinstance(llm_date, str) and re.match(r"^\d{4}-\d{2}", llm_date):
        state["start_date"] = llm_date[:7] + "-01"
        updates.append(f"起始档期 {state['start_date'][:7].replace('-', '.')}")
    elif date_slot and date_slot.value:
        state["start_date"] = str(date_slot.value)
        updates.append(f"起始档期 {state['start_date'][:7].replace('-', '.')}")

    llm_weeks = (llm_res or {}).get("weeks")
    w_raw = llm_weeks if isinstance(llm_weeks, (int, float)) and llm_weeks >= 2 else (weeks_slot.value if weeks_slot and weeks_slot.value else None)
    if w_raw is not None:
        wval = max(2, min(52, int(round(float(w_raw)))))
        state["weeks"] = wval
        updates.append(f"投放 {wval} 周")

    llm_cust = (llm_res or {}).get("customer_type")
    cust_val = llm_cust if llm_cust in ("direct", "4a") else (str(cust_slot.value) if cust_slot and cust_slot.value else None)
    if cust_val:
        state["customer_type"] = cust_val
        updates.append("签约模式 4A 代理" if cust_val == "4a" else "签约模式直客")

    # 组装完整的 company_profile（只要本轮调研/更新了企业，或之前已有档案）
    company_profile: Optional[Dict[str, Any]] = None
    cv_now = state.get("custom_venue") if isinstance(state.get("custom_venue"), dict) else None
    should_emit_profile = bool(
        chosen_cand
        or preset_hit_id
        or raw_prof
        or (enterprise_name and location_status in ("located", "confirmed", "needs_confirm"))
    )
    if should_emit_profile:
        fallback_prof = _build_rule_company_profile(
            enterprise_name or (cv_now.get("name") if cv_now else ""),
            state.get("industry") or ind,
            chosen=chosen_cand or (
                {
                    "name": cv_now.get("name"),
                    "address": cv_now.get("address"),
                    "city": cv_now.get("city"),
                    "district": cv_now.get("district"),
                }
                if cv_now else None
            ),
            strategy_override=state.get("strategy_mode"),
        )
        if raw_prof:
            rec_media = [m for m in (raw_prof.get("recommended_media") or []) if m in ("bus", "metro")]
            p_strat = raw_prof.get("ad_strategy_mode")
            company_profile = {
                "company_name": str(raw_prof.get("company_name") or fallback_prof["company_name"]).strip(),
                "address": (chosen_cand.get("address") if chosen_cand else "") or (cv_now.get("address") if cv_now else "") or fallback_prof["address"],
                "city": (chosen_cand.get("city") if chosen_cand else "") or (cv_now.get("city") if cv_now else ""),
                "district": (chosen_cand.get("district") if chosen_cand else "") or (cv_now.get("district") if cv_now else ""),
                "industry": state.get("industry") or fallback_prof["industry"],
                "industry_detail": str(raw_prof.get("industry_detail") or fallback_prof["industry_detail"]).strip(),
                "core_business": str(raw_prof.get("core_business") or fallback_prof["core_business"]).strip(),
                "target_audience": str(raw_prof.get("target_audience") or fallback_prof["target_audience"]).strip(),
                "ad_strategy_mode": p_strat if p_strat in STRATEGY_MODES else fallback_prof["ad_strategy_mode"],
                "ad_strategy_label": str(raw_prof.get("ad_strategy_label") or fallback_prof["ad_strategy_label"]).strip(),
                "ad_strategy_reason": str(raw_prof.get("ad_strategy_reason") or fallback_prof["ad_strategy_reason"]).strip(),
                "recommended_media": rec_media or fallback_prof["recommended_media"],
            }
        else:
            company_profile = fallback_prof
        state["company_profile"] = company_profile
        # 若用户尚未主动指定策略，则采用 Agent 推荐策略
        if not state.get("strategy_mode") and company_profile.get("ad_strategy_mode") in STRATEGY_MODES:
            state["strategy_mode"] = company_profile["ad_strategy_mode"]

    # 合并 brief_text
    if text:
        prev_brief = str(state.get("brief_text") or "").strip()
        if text not in prev_brief:
            state["brief_text"] = f"{prev_brief}；{text}".strip("；") if prev_brief else text

    # 3) 构造操作筹码（支持确认企业与策略、切换其他高德候选地址、调整策略、一键生成）
    has_located_company = bool(cv_now or (state.get("venue") in VENUES))
    ready_to_run = has_located_company and location_status != "not_found" and bool(state.get("budget_wan"))

    suggestions: List[Dict[str, Any]] = []
    if location_status == "not_found":
        suggestions = [
            {"label": "补充企业全称与所在城市", "send_text": "我们公司的全称是："},
            {"label": "试试：贵州老干妈", "send_text": "我们是贵州老干妈，预算350万"},
            {"label": "试试：陆家嘴中国平安", "send_text": "我们是陆家嘴中国平安，预算300万"},
        ]
    else:
        if user_explicit_confirm and ready_to_run:
            suggestions.append({"label": "立即启动 Agent 生成三套方案 →", "action": "generate"})
        elif ready_to_run:
            suggestions.append({"label": "确认企业信息与策略，生成三套方案 →", "action": "generate"})
            suggestions.append({"label": "确认信息无误（继续聊细节）", "send_text": "以上客户公司地址、行业与广告策略确认无误"})

        # 如果高德还查到了其他真实候选分支地址，提供一键切换地址按钮
        if len(candidates) > 1:
            for alt in candidates[1:3]:
                area_tag = alt.get("city") or alt.get("district") or ""
                suggestions.append({
                    "label": f"改定位：{alt['name']}{'（' + area_tag + '）' if area_tag else ''}",
                    "action": "pick_place",
                    "place": alt,
                    "send_text": f"改定位到：{alt['name']}（{alt['address']}）",
                })

        # 补充来自 LLM 的合理微调建议（过滤与“确认”重复的按钮）
        for s in (llm_res or {}).get("suggestions") or []:
            if len(suggestions) >= 4:
                break
            if not isinstance(s, dict):
                continue
            label = str(s.get("label") or "").strip()
            if not label or any(x["label"] == label for x in suggestions):
                continue
            if "确认" in label and any("确认" in x["label"] for x in suggestions):
                continue
            action = s.get("action")
            if action == "pick_candidate":
                cidx = s.get("candidate_index")
                if isinstance(cidx, int) and 0 <= cidx < len(candidates):
                    c = candidates[cidx]
                    suggestions.append({
                        "label": label,
                        "action": "pick_place",
                        "place": c,
                        "send_text": str(s.get("send_text") or f"改定位到：{c['name']}"),
                    })
                    continue
            if action == "generate":
                continue
            suggestions.append({
                "label": label,
                "action": None,
                "send_text": str(s.get("send_text") or label),
            })

        if len(suggestions) < 3 and ready_to_run:
            cur_strat = state.get("strategy_mode") or "balanced"
            alt_strat = ("改用精准聚焦策略", "策略调整为精准聚焦") if cur_strat != "precision" else ("改用全域广度策略", "策略调整为全域广度")
            suggestions.append({"label": alt_strat[0], "send_text": alt_strat[1]})

    # 4) 回复文案
    reply = str((llm_res or {}).get("reply") or "").replace("**", "").strip()
    if not reply:
        if location_status == "not_found":
            reply = (
                f"我在高德地图全国范围暂未检索到「{enterprise_name or text}」的准确位置，可能是企业简称、别称或有错别字。\n"
                "请补充一下客户公司的规范全称或所在城市，我会立即重新调研并在地图上为您精准标出。"
            )
        elif company_profile:
            upd_str = ("（已同步：" + " · ".join(updates) + "）") if updates else ""
            if user_explicit_confirm:
                reply = f"已确认「{company_profile['company_name']}」的客户档案、公司地址与投放策略{upd_str}。点击下方按钮即可启动 Agent 生成三套方案。"
            else:
                reply = (
                    f"已为您完成「{company_profile['company_name']}」的客户调研与全国高德地址定位，并自动匹配了所属行业与广告策略建议{upd_str}。\n"
                    "请核对上方卡片中的公司地址、所属行业及投放策略是否准确；如需更换分公司地址或调整预算/策略，可直接告诉我。"
                )
        else:
            upd_prefix = ("已为您更新：" + " · ".join(updates) + "。") if updates else "收到您的补充说明。"
            reply = f"{upd_prefix}请确认当前客户信息与投放参数无误，确认后可一键启动 Agent 生成三套方案。"

    return {
        "ok": True,
        "need_place_lookup": False,
        "search_queries": [],
        "pending_enterprise": enterprise_name if location_status == "not_found" else "",
        "location_status": location_status,
        "reply": reply,
        "draft": state,
        "updates": updates,
        "geocoded": geocoded,
        "company_profile": company_profile,
        "candidates": candidates[:5],
        "suggestions": suggestions[:4],
        "ready_to_run": ready_to_run,
        "agent_mode": agent_mode,
        "llm_error": llm_error,
    }


__all__ = ["consult_turn"]
