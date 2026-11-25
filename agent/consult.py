# -*- coding: utf-8 -*-
"""交互式需求顾问 Agent：支持多轮自然语言沟通、公司/地标定位与细节确认。

原则：
- 不编造价格/库存/曝光数字；只帮助用户澄清品牌/公司地点、行业、预算、档期、媒介、客户类型与投放目标；
- 规则抽取优先，若配置了 DEEPSEEK_API_KEY 则润色回复语气；无 Key 时确定性顾问话术同样完整自然；
- 当用户提到任意上海公司/品牌/商圈/地标时，调用 xinyun-bigdata /nearby/geocode（或本地地标库兜底）解析坐标，
  实时同步到前端地图与表单。
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from engine.models import INDUSTRIES, STRATEGY_MODES, VENUES
from .data_skills import DataSkillRuntime, default_data_runtime
from .intake import (
    _extract_budget,
    _extract_customer_type,
    _extract_media,
    _extract_start_date,
    _extract_venue,
    _extract_weeks,
    normalize_text,
)
from .llm import build_llm

_INDUSTRY_KEYWORDS: List[Tuple[str, List[str]]] = [
    ("银行保险", ["银行", "保险", "平安", "招行", "招商银行", "建行", "工行", "农行", "中行", "友邦", "太保", "太平洋保险", "理财", "基金", "证券", "金融"]),
    ("食品饮料", ["饮用水", "矿泉水", "饮料", "食品", "奶茶", "咖啡", "可乐", "牛奶", "乳业", "啤酒", "零食", "农夫山泉", "元气森林", "瑞幸", "星巴克", "百岁山", "快消"]),
    ("保健品", ["保健品", "保健", "营养", "维生素", "益生菌", "养生", "燕窝", "汤臣倍健", "蛋白粉", "大健康"]),
    ("私立医院", ["医院", "口腔", "牙科", "眼科", "医美", "体检", "诊所", "妇儿", "和睦家", "美年", "爱尔", "瑞尔"]),
    ("乐园", ["乐园", "迪士尼", "乐高", "海昌", "欢乐谷", "天文馆", "野生动物园", "主题公园", "景区", "文旅"]),
]

_STRATEGY_KEYWORDS: List[Tuple[str, List[str]]] = [
    ("max_reach", ["广度", "全城", "覆盖", "曝光最大", "铺开", "声量", "性价比", "低cpm", "cpm低"]),
    ("precision", ["聚焦", "精准", "周边", "地标", "核心圈", "高浓度", "高频", "门店周边", "公司周边", "高端"]),
    ("balanced", ["均衡", "平衡", "兼顾", "推荐", "综合"]),
]

_PLACE_PATTERNS = [
    re.compile(r"(?:地点|地址|位置|位于|在|围绕|公司叫|品牌叫|客户是|我们是|投放)\s*[：:是为]?\s*「?([A-Za-z0-9\u4e00-\u9fa5（）()·\-]{2,24})」?"),
    re.compile(r"上海([A-Za-z0-9\u4e00-\u9fa5]{2,18}(?:大厦|中心|广场|商圈|医院|公园|乐园|金融|科技园|园区|产业园|大学|门店|总部|寺|路|城|馆))"),
]

_STOP_PLACES = {
    "上海", "上海市", "公交", "地铁", "全媒体", "公交车身", "地铁出入口", "直客", "代理", "方案", "广告",
    "预算", "暑期", "国庆", "五一", "今年", "明年", "均衡", "广度", "聚焦", "公司", "品牌", "客户",
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


def _extract_custom_place(text: str) -> Optional[str]:
    # 先匹配常见知名上海地标/商圈/企业词
    known_phrases = [
        "陆家嘴中国平安", "中国平安金融中心", "平安金融中心", "上海中心大厦", "环球金融中心",
        "陆家嘴", "静安寺", "静安嘉里中心", "南京西路", "徐家汇", "港汇恒隆", "美罗城",
        "人民广场", "南京东路", "外滩", "新天地", "淮海路", "五角场", "合生汇",
        "中山公园", "虹桥商务区", "虹桥枢纽", "国家会展中心", "张江科学城", "张江高科技园区", "张江",
        "前滩太古里", "前滩", "环球港", "北外滩", "大宁国际", "上海天文馆", "漕河泾",
        "腾讯大厦", "阿里巴巴", "哔哩哔哩", "和睦家医院", "瑞尔齿科", "宝山万达", "松江万达", "嘉定新城",
    ]
    for p in known_phrases:
        if p in text:
            return p
    for pat in _PLACE_PATTERNS:
        m = pat.search(text)
        if not m:
            continue
        cand = m.group(1).strip(" ，。！？；、")
        # 截断后面跟的预算/时间/媒介词
        cand = re.split(r"(?:预算|投|想|准备|需要|做|在|的|，|,|。|；|;|\d+万|\d+周)", cand)[0].strip()
        if len(cand) >= 2 and cand not in _STOP_PLACES and not re.fullmatch(r"\d+", cand):
            return cand
    return None


def consult_turn(
    message: str,
    draft: Optional[Dict[str, Any]] = None,
    history: Optional[List[Dict[str, str]]] = None,
    *,
    data_runtime: Optional[DataSkillRuntime] = None,
) -> Dict[str, Any]:
    """处理一轮用户与 Agent 的交互对话，更新结构化需求草稿并给出下一步澄清建议。"""
    text = normalize_text(message or "")
    state = dict(draft or {})
    updates: List[str] = []
    geocoded: Optional[Dict[str, Any]] = None
    runtime = data_runtime or default_data_runtime()

    # 1) 识别预设场馆或自定义公司/地点
    venue_slot, _ = _extract_venue(text, list(VENUES.keys()))
    if venue_slot and venue_slot.value in VENUES:
        vid = str(venue_slot.value)
        state["venue"] = vid
        state.pop("custom_venue", None)
        state["industry"] = state.get("industry") or "乐园"
        updates.append(f"目标地点已设为「{VENUES[vid]['name']}」")
    else:
        custom_place = _extract_custom_place(text)
        if custom_place:
            geo = runtime.bigdata_geocode(custom_place)
            if geo.get("ok") and geo.get("lng") and geo.get("lat"):
                geocoded = geo
                state["venue"] = "custom"
                state["custom_venue"] = {
                    "id": "custom",
                    "name": custom_place,
                    "district": geo.get("district") or "",
                    "address": geo.get("address") or custom_place,
                    "coords": {"lng": float(geo["lng"]), "lat": float(geo["lat"])},
                    "rings_km": [3, 8, 20],
                }
                updates.append(f"已定位自定义地点「{custom_place}」（{geo.get('district') or '上海市'}）")

    # 2) 行业
    ind = _extract_industry(text)
    if ind:
        state["industry"] = ind
        updates.append(f"行业已识别为「{ind}」")

    # 3) 预算
    budget_slot, _ = _extract_budget(text)
    if budget_slot and budget_slot.value is not None:
        bval = max(100.0, min(500.0, float(budget_slot.value)))
        state["budget_wan"] = round(bval, 0)
        updates.append(f"预算 {int(state['budget_wan'])} 万")

    # 4) 媒介
    media_slot = _extract_media(text)
    if media_slot and media_slot.value:
        state["media"] = list(media_slot.value)
        lbl = " + ".join("公交车身" if m == "bus" else "地铁出入口" for m in state["media"])
        updates.append(f"媒介 {lbl}")

    # 5) 档期 / 周数
    date_slot = _extract_start_date(text)
    if date_slot and date_slot.value:
        state["start_date"] = str(date_slot.value)
        updates.append(f"起始档期 {state['start_date']}")

    weeks_slot = _extract_weeks(text)
    if weeks_slot and weeks_slot.value:
        allowed = [2, 4, 6, 8, 12]
        nearest = min(allowed, key=lambda x: abs(x - int(weeks_slot.value)))
        state["weeks"] = nearest
        updates.append(f"投放 {nearest} 周")

    # 6) 客户类型
    cust_slot = _extract_customer_type(text)
    if cust_slot and cust_slot.value:
        state["customer_type"] = str(cust_slot.value)
        updates.append("签约模式 4A 代理" if state["customer_type"] == "4a" else "签约模式直客")

    # 7) 优先策略倾向
    strat = _extract_strategy(text)
    if strat:
        state["strategy_mode"] = strat
        updates.append(f"优先策略「{STRATEGY_MODES[strat]['short']}」")

    # 合并 brief_text
    if text:
        prev_brief = str(state.get("brief_text") or "").strip()
        if text not in prev_brief:
            state["brief_text"] = f"{prev_brief}；{text}".strip("；") if prev_brief else text

    # 8) 诊断待确认项，形成有深度的下一步提问与快捷回复筹码
    missing_prompts: List[str] = []
    suggestions: List[Dict[str, Any]] = []

    has_place = bool(state.get("custom_venue") or (state.get("venue") in VENUES))
    if not has_place:
        missing_prompts.append("请问本次投放的目标公司、品牌门店或上海核心地标是哪里？（例如：陆家嘴中国平安、静安寺商圈、上海乐高乐园）")
        suggestions.extend([
            {"label": "陆家嘴 · 中国平安（银行保险）", "send_text": "我们是陆家嘴中国平安，银行保险行业"},
            {"label": "静安寺商圈（食品饮料）", "send_text": "目标在静安寺商圈，食品饮料品牌推广"},
            {"label": "上海乐高乐园（主题乐园）", "send_text": "上海乐高乐园暑期亲子投放"},
        ])
    elif not state.get("industry"):
        missing_prompts.append("请问贵司所属行业是哪一类？不同行业会匹配不同的 POI 权重、受众人群口径与广告合规提示。")
        for ind_name in INDUSTRIES[:5]:
            suggestions.append({"label": ind_name, "send_text": f"行业是{ind_name}"})

    if not state.get("budget_wan"):
        missing_prompts.append("媒体总预算大约在什么区间（100–500 万）？")
        if len(suggestions) < 4:
            suggestions.extend([
                {"label": "预算 200 万", "send_text": "预算 200 万，投 8 周"},
                {"label": "预算 350 万", "send_text": "预算 350 万，投 8 周"},
                {"label": "预算 500 万", "send_text": "预算 500 万，投 8 周"},
            ])

    if not state.get("strategy_mode") and has_place:
        missing_prompts.append("本次投放更看重「全域广度降 CPM」、「核心地标周边高浓聚焦」，还是「均衡首选」？（系统会同步生成三套方案供您对比切换）")
        if len(suggestions) < 5:
            suggestions.extend([
                {"label": "均衡首选（推荐）", "send_text": "优先看均衡首选方案，直客签约"},
                {"label": "全域广度 · 低 CPM", "send_text": "优先看全域广度覆盖，追求最低 CPM"},
                {"label": "核心地标高浓聚焦", "send_text": "优先聚焦目标地标周边核心商圈"},
            ])

    if not state.get("customer_type") and has_place and len(suggestions) < 5:
        suggestions.append({"label": "4A 代理签约（含15%服务费）", "send_text": "按 4A 代理模式报价并匹配 4A 合同"})

    ready_to_run = has_place and bool(state.get("budget_wan"))
    place_label = (
        (state.get("custom_venue") or {}).get("name")
        or (VENUES.get(str(state.get("venue") or "")) or {}).get("name")
        or "目标地点"
    )

    if updates:
        lead = "已为您更新：" + " · ".join(updates) + "。"
    else:
        lead = f"收到您的补充说明（当前目标：{place_label}）。"

    if missing_prompts:
        reply = f"{lead}\n为让 CP-SAT 求解与新云大数据覆盖更贴合业务，还想跟您确认：{missing_prompts[0]}"
    else:
        b = int(state.get("budget_wan") or 300)
        w = int(state.get("weeks") or 8)
        m_lbl = " + ".join("公交车身" if m == "bus" else "地铁出入口" for m in (state.get("media") or ["bus", "metro"]))
        c_lbl = "4A 代理" if state.get("customer_type") == "4a" else "直客"
        reply = (
            f"{lead}\n核心参数已齐备：**{place_label}**（{state.get('industry') or '综合商业'}） · "
            f"**{b} 万** · **{w} 周** · **{m_lbl}** · **{c_lbl}**。\n"
            "点击下方按钮即可启动 Agent：实时拉取红豆库存 + 新云周边覆盖/人群画像/线路轨迹，并一次生成「均衡首选 / 全域广度 / 地标聚焦」三套方案供您对比决策。"
        )
        suggestions = [
            {"label": "确认并立即生成三套方案 →", "action": "generate"},
            {"label": "改用 4A 代理报价" if state.get("customer_type") != "4a" else "改用直客报价",
             "send_text": "改成 4A 代理模式" if state.get("customer_type") != "4a" else "改成直客模式"},
            {"label": "只投公交车身", "send_text": "媒介改成只投公交车身"},
        ]

    # 可选 LLM 润色（若配置了 DEEPSEEK_API_KEY 且文本简短，润色语气但不改动数字/状态）
    llm = build_llm("auto")
    if getattr(llm, "available", False) and text:
        try:
            prompt = (
                "你是上海新云传媒的资深户外媒介策略顾问。请把下面的顾问回复润色为更自然、专业、简洁的中文（不超过 110 字），"
                "严格保留原有地名、行业、预算和追问重点，不要编造任何新的报价、库存或曝光数字。"
            )
            polished = llm._chat(
                [
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": f"用户说：{text}\n待润色回复：{reply}"},
                ],
                max_tokens=220,
                temperature=0.3,
            )
            if polished and len(polished.strip()) >= 12:
                reply = polished.strip()
        except Exception:
            pass

    return {
        "ok": True,
        "reply": reply,
        "draft": state,
        "updates": updates,
        "geocoded": geocoded,
        "suggestions": suggestions[:4],
        "ready_to_run": ready_to_run,
    }


__all__ = ["consult_turn"]
