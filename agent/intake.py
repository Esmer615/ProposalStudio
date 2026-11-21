# -*- coding: utf-8 -*-
"""Brief 接收：把客户自然语言需求解析成可计算请求 + 待确认问题 + 显式假设。

原则：
- 规则优先，LLM 只做补充理解，且不能覆盖规则已经确认的硬字段；
- 缺字段不编：要么提问，要么写进 assumptions；
- 任何解析结果都带 source / evidence，方便销售和评委追问。
"""
from __future__ import annotations

import datetime as _dt
import re
import unicodedata
from typing import Any, Dict, List, Optional, Tuple

from .contracts import (
    BriefState,
    REQUIRED_SLOTS,
    SOURCE_BRIEF,
    SOURCE_DEFAULT,
    SOURCE_INFERRED,
    SOURCE_LLM,
    SOURCE_STRUCTURED,
    STATUS_NEEDS_CLARIFICATION,
    STATUS_READY,
    STATUS_READY_WITH_ASSUMPTIONS,
    SlotValue,
)

VENUE_KEYWORDS: Dict[str, List[str]] = {
    "lego_shanghai": ["乐高", "legoland", "lego"],
    "disney_shanghai": ["迪士尼", "disney"],
    "haichang_shanghai": ["海昌", "海洋公园", "ocean park"],
}
MEDIA_KEYWORDS: Dict[str, List[str]] = {
    "bus": ["公交", "巴士", "车身", "公交车身"],
    "metro": ["地铁", "轨交", "轨道交通", "地铁口", "出入口"],
}
_ALL_MEDIA_PHRASES = ("全媒体", "公交+地铁", "公交和地铁", "公交车+地铁", "公交、地铁", "bus+metro")

_CN_DIGITS = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
               "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_CN_UNITS = {"十": 10, "百": 100, "千": 1000, "万": 10000, "亿": 100000000}

_OBJECTIVE_KEYWORDS = {
    "efficiency": ["效率", "性价比", "最值", "划算", "预算有限", "花得值", "投产比"],
    "precision": ["精准", "目标人群", "核心人群", "亲子家庭", "家长", "触达", "浓度"],
    "reach": ["曝光", "覆盖", "广度", "全城", "声量", "看到", "到达"],
    "brand": ["品牌", "知名度", "心智", "认知", "形象"],
}

_AUDIENCE_KEYWORDS = [
    "亲子", "家庭", "孩子", "儿童", "家长", "幼儿园", "小学", "中学生",
    "年轻人", "白领", "情侣", "游客", "长三角",
    "20岁", "<20", "20岁以下", "低龄",
]

_DEFAULT_BUDGET_WAN = 200.0


def normalize_text(text: str) -> str:
    """全角转半角，统一空白；保留中文。"""
    return unicodedata.normalize("NFKC", text or "").replace("　", " ").strip()


def _slot(value: Any, source: str, confidence: str, evidence: str = "") -> SlotValue:
    return SlotValue(value=value, source=source, confidence=confidence, evidence=evidence)


# --------------------------------------------------------------------------- #
# 数字 / 日期
# --------------------------------------------------------------------------- #
def cn_to_number(text: str) -> Optional[float]:
    """中文数字解析，覆盖预算常见写法（一百五十万 / 两百万 / 三百五十）。"""
    if not text:
        return None
    total = 0
    section = 0
    number = 0
    for ch in text:
        if ch in _CN_DIGITS:
            number = _CN_DIGITS[ch]
        elif ch in _CN_UNITS:
            unit = _CN_UNITS[ch]
            if unit >= 10000:
                section = (section + number) * unit
                total += section
                section = 0
                number = 0
            else:
                if number == 0:
                    number = 1
                section += number * unit
                number = 0
        else:
            return None
    return float(total + section + number)


def _budget_candidates(text: str) -> List[Tuple[float, str]]:
    out: List[Tuple[float, str]] = []

    # 1) 阿拉伯数字 + 万/万元/w/W/元
    for m in re.finditer(r"(?P<num>\d+(?:\.\d+)?)\s*(?P<unit>万元|万|w|W|元)", text):
        num = float(m.group("num"))
        unit = m.group("unit")
        if unit == "元":
            if num >= 100000:
                out.append((num / 10000.0, m.group(0)))
        else:
            out.append((num, m.group(0)))

    # 2) 中文数字 + 万/万元（或中文数字中自带万）
    for m in re.finditer(r"(?P<cn>[零〇一二两三四五六七八九十百千万亿]+)\s*(?P<unit>万元|万)?", text):
        cn = m.group("cn")
        if not any(ch in _CN_UNITS for ch in cn):
            # 纯个位数/十位数没有业务含义（如“三家”），跳过
            continue
        val = cn_to_number(cn)
        if val is None:
            continue
        if "万" in cn or "亿" in cn:
            val = val / 10000.0
        elif m.group("unit") in ("万", "万元"):
            pass
        else:
            continue
        if val >= 1:
            out.append((val, m.group(0)))

    # 去重，保留首次出现顺序
    seen = set()
    unique: List[Tuple[float, str]] = []
    for value, evidence in out:
        key = round(value, 4)
        if key in seen:
            continue
        seen.add(key)
        unique.append((value, evidence))
    return unique


def _extract_budget(text: str) -> Tuple[Optional[SlotValue], List[float]]:
    candidates = _budget_candidates(text)
    if not candidates:
        return None, []
    # 优先取带“预算”上下文的数字
    context = None
    for value, evidence in candidates:
        idx = text.find(evidence)
        window = text[max(0, idx - 14): idx]
        if any(k in window for k in ("预算", "费用", "媒体", "总预算", "投放")):
            context = (value, evidence)
            break
    value, evidence = context or candidates[0]
    conflicts = [v for v, _ in candidates if abs(v - value) > 0.01]
    confidence = "high" if context and not conflicts else ("medium" if not conflicts else "low")
    return _slot(round(value, 2), SOURCE_BRIEF, confidence, evidence), conflicts


def _extract_venue(
    text: str,
    valid_ids: List[str],
    aliases: Optional[Dict[str, List[str]]] = None,
) -> Tuple[Optional[SlotValue], List[str]]:
    matches: List[Tuple[str, str]] = []
    lower = text.lower()
    for vid, keywords in (aliases or VENUE_KEYWORDS).items():
        if vid not in valid_ids:
            continue
        for kw in keywords:
            if kw.lower() in lower:
                matches.append((vid, kw))
                break
    ids = list(dict.fromkeys(m for m, _ in matches))
    if len(ids) == 1:
        evidence = next(kw for vid, kw in matches if vid == ids[0])
        return _slot(ids[0], SOURCE_BRIEF, "high", evidence), []
    if len(ids) > 1:
        return None, ids
    return None, []


def _extract_media(
    text: str,
    aliases: Optional[Dict[str, List[str]]] = None,
) -> Optional[SlotValue]:
    if any(p in text for p in _ALL_MEDIA_PHRASES):
        return _slot(["bus", "metro"], SOURCE_BRIEF, "high", "全媒体/公交+地铁")
    found = []
    evidence = []
    lower = text.lower()
    for mid, keywords in (aliases or MEDIA_KEYWORDS).items():
        for kw in keywords:
            if kw.lower() in lower:
                found.append(mid)
                evidence.append(kw)
                break
    if not found:
        return None
    return _slot(found, SOURCE_BRIEF, "high" if len(found) == 2 else "medium", "/".join(evidence))


def _safe_date(year: int, month: int, day: int) -> Optional[str]:
    try:
        return _dt.date(year, month, day).isoformat()
    except ValueError:
        return None


def _extract_start_date(text: str) -> Optional[SlotValue]:
    # 完整日期
    m = re.search(r"(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})日?", text)
    if m:
        iso = _safe_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if iso:
            return _slot(iso, SOURCE_BRIEF, "high", m.group(0))

    # 年 + 月
    m = re.search(r"(20\d{2})年(\d{1,2})月", text)
    if m:
        iso = _safe_date(int(m.group(1)), int(m.group(2)), 1)
        if iso:
            return _slot(iso, SOURCE_BRIEF, "medium", m.group(0))

    # 月 + 日 / 月（默认 2027）
    m = re.search(r"(\d{1,2})月(\d{1,2})日", text)
    if m:
        iso = _safe_date(2027, int(m.group(1)), int(m.group(2)))
        if iso:
            return _slot(iso, SOURCE_INFERRED, "medium", m.group(0) + "（年份按 2027）")
    m = re.search(r"(\d{1,2})月份?", text)
    if m:
        iso = _safe_date(2027, int(m.group(1)), 1)
        if iso:
            return _slot(iso, SOURCE_INFERRED, "low", m.group(0) + "（年份/日期按 2027-01 推断）")

    season_map = {
        "暑期": ("2027-07-01", "暑期默认 7 月 1 日开始"),
        "暑假": ("2027-07-01", "暑假默认 7 月 1 日开始"),
        "国庆": ("2027-10-01", "国庆默认 10 月 1 日开始"),
        "五一": ("2027-05-01", "五一默认 5 月 1 日开始"),
        "寒假": ("2027-01-15", "寒假默认 1 月 15 日开始"),
        "元旦": ("2027-01-01", "元旦默认 1 月 1 日开始"),
    }
    for key, (iso, note) in season_map.items():
        if key in text:
            return _slot(iso, SOURCE_INFERRED, "medium", note)
    return None


def _nearest_weeks(value: int, allowed: List[int]) -> int:
    return min(allowed, key=lambda x: (abs(x - value), x))


def _extract_weeks(text: str) -> Optional[SlotValue]:
    m = re.search(r"(\d+(?:\.\d+)?)\s*周", text)
    if m:
        return _slot(int(round(float(m.group(1)))), SOURCE_BRIEF, "high", m.group(0))
    m = re.search(r"(\d+)\s*个?\s*星期", text)
    if m:
        return _slot(int(m.group(1)), SOURCE_BRIEF, "high", m.group(0))
    m = re.search(r"(\d+)\s*个月", text)
    if m:
        return _slot(int(m.group(1)) * 4, SOURCE_BRIEF, "medium", m.group(0) + "（按 4 周/月折算）")
    m = re.search(r"([一二两三四五六七八九十]+)\s*个月", text)
    if m:
        n = cn_to_number(m.group(1))
        if n:
            return _slot(int(n) * 4, SOURCE_BRIEF, "medium", m.group(0) + "（按 4 周/月折算）")
    if "暑期" in text or "暑假" in text:
        return _slot(8, SOURCE_INFERRED, "medium", "暑期按 8 周假设")
    return None


def _extract_customer_type(text: str) -> Optional[SlotValue]:
    lower = text.lower()
    if "4a" in lower or "代理" in text or "agency" in lower:
        return _slot("4a", SOURCE_BRIEF, "high", "4A/代理")
    if "直客" in text or "direct" in lower:
        return _slot("direct", SOURCE_BRIEF, "high", "直客")
    return None


def _extract_objective(text: str, keywords: Optional[Dict[str, List[str]]] = None) -> SlotValue:
    scores: Dict[str, int] = {}
    evidence: Dict[str, List[str]] = {}
    for key, kws in (keywords or _OBJECTIVE_KEYWORDS).items():
        hits = [kw for kw in kws if kw in text]
        if hits:
            scores[key] = len(hits)
            evidence[key] = hits
    if not scores:
        return _slot("balanced", SOURCE_DEFAULT, "low", "未明确目标，按均衡分析")
    ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
    top_key, top_score = ranked[0]
    if len(ranked) > 1 and ranked[1][1] == top_score:
        return _slot("balanced", SOURCE_INFERRED, "low", "同时提到多种目标，按均衡分析")
    return _slot(top_key, SOURCE_BRIEF, "high", "/".join(evidence.get(top_key, [])))


def _audience_notes(text: str) -> List[str]:
    """只回人群关键词与短片段，不要整句 brief。"""
    notes: List[str] = []
    hits = [kw for kw in _AUDIENCE_KEYWORDS if kw in text]
    if hits:
        notes.append("人群关键词：" + "、".join(dict.fromkeys(hits)))
    for sentence in re.split(r"[。；;，,\n]", text):
        matched = [kw for kw in _AUDIENCE_KEYWORDS if kw in sentence]
        if not matched:
            continue
        snippet = sentence.strip()[:48]
        if snippet and snippet not in notes:
            notes.append(snippet)
        if len(notes) >= 3:
            break
    return notes


def _request_from_structured(structured: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for key in ("venue", "budget_wan", "media", "start_date", "weeks", "customer_type", "industry", "locks"):
        if key in structured and structured[key] is not None:
            out[key] = structured[key]
    return out


# --------------------------------------------------------------------------- #
# 合规扫描（brief 阶段）
# --------------------------------------------------------------------------- #
def _is_negated(text: str, index: int) -> bool:
    window = text[max(0, index - 16): index]
    return any(word in window for word in ("不", "无需", "不要", "不能", "禁止", "别", "避免", "不得"))


def detect_compliance_flags(text: str, policy: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rules = (policy or {}).get("forbidden_claims") or []
    flags: List[Dict[str, Any]] = []
    seen_codes = set()
    for rule in rules:
        if isinstance(rule, str):
            rule = {"match": rule, "guidance": ""}
        needle = str(rule.get("match") or "").strip()
        if not needle:
            continue
        start = 0
        while True:
            idx = text.find(needle, start)
            if idx < 0:
                break
            start = idx + len(needle)
            if _is_negated(text, idx):
                continue
            code = str(rule.get("code") or "COMPLIANCE_PHRASE")
            if code in seen_codes:
                continue
            seen_codes.add(code)
            flags.append({
                "code": code,
                "level": str(rule.get("level") or "high"),
                "matched": needle,
                "location": "brief",
                "guidance": str(rule.get("guidance") or ""),
            })
    return flags


# --------------------------------------------------------------------------- #
# 主入口
# --------------------------------------------------------------------------- #
def resolve_brief(
    raw_text: Optional[str],
    structured: Optional[Dict[str, Any]],
    catalog: Dict[str, Any],
    options: Dict[str, Any],
    *,
    llm: Any = None,
    compliance_policy: Optional[Dict[str, Any]] = None,
    intake_policy: Optional[Dict[str, Any]] = None,
) -> BriefState:
    """解析 + 合并 + 校验，返回 BriefState。

    intake_policy 来自 brief-intake/policy.json：默认值、范围、别名、提问上限。
    """
    ip = dict(intake_policy or {})
    structured = dict(structured or {})
    raw_text = normalize_text(raw_text or str(structured.get("brief_text") or ""))
    valid_venues = [v["id"] for v in catalog.get("venues", [])]
    allowed_weeks = [int(x) for x in (ip.get("allowed_weeks") or catalog.get("allowed_weeks", [2, 4, 6, 8, 12]))]
    defaults = {**dict(catalog.get("defaults") or {}), **(ip.get("defaults") or {})}
    max_questions = int(options.get("max_questions") or ip.get("max_questions", 5))
    budget_range = {**(catalog.get("budget_range") or {}), **(ip.get("budget_range_wan") or {})}
    default_budget = float(ip.get("default_budget_wan", _DEFAULT_BUDGET_WAN))
    objective_keywords = ip.get("objective_keywords") or None
    venue_aliases = ip.get("venue_aliases") or None
    media_aliases = ip.get("media_aliases") or None

    slots: Dict[str, SlotValue] = {}
    questions: List[Dict[str, Any]] = []
    assumptions: List[Dict[str, Any]] = []
    conflicts: Dict[str, Any] = {}

    # ---- 规则解析 ----------------------------------------------------------
    parsed: Dict[str, SlotValue] = {}
    venue_slot, venue_conflicts = _extract_venue(raw_text, valid_venues, venue_aliases)
    if venue_conflicts:
        conflicts["venue"] = venue_conflicts
    elif venue_slot:
        parsed["venue"] = venue_slot

    budget_slot, budget_conflicts = _extract_budget(raw_text)
    if budget_slot:
        parsed["budget_wan"] = budget_slot
    if budget_conflicts:
        conflicts["budget_wan"] = budget_conflicts

    media_slot = _extract_media(raw_text, media_aliases)
    if media_slot:
        parsed["media"] = media_slot

    date_slot = _extract_start_date(raw_text)
    if date_slot:
        parsed["start_date"] = date_slot

    weeks_slot = _extract_weeks(raw_text)
    if weeks_slot:
        parsed["weeks"] = weeks_slot

    customer_slot = _extract_customer_type(raw_text)
    if customer_slot:
        parsed["customer_type"] = customer_slot

    objective_slot = _extract_objective(raw_text, objective_keywords)
    parsed["objective"] = objective_slot

    # ---- 可选 LLM 补充：只补规则缺失的软字段 -------------------------------
    llm_audience_notes: List[str] = []
    llm_constraints: List[str] = []
    llm_status: List[str] = []
    if llm is not None and getattr(llm, "available", False):
        try:
            enriched = llm.extract_brief(raw_text, _brief_json_schema(), _intake_prompt())
        except Exception as exc:  # pragma: no cover - 外部服务异常
            enriched = None
            llm_status.append(f"LLM 解析失败，已回退规则：{type(exc).__name__}")
        if isinstance(enriched, dict):
            if "objective" not in parsed or parsed.get("objective", SlotValue()).source != SOURCE_BRIEF:
                obj = str(enriched.get("objective") or "")
                if obj in ("balanced", "reach", "precision", "efficiency", "brand"):
                    parsed["objective"] = _slot(obj, SOURCE_LLM, "low", "LLM 语义解析")
            for note in (enriched.get("audience_notes") or []):
                note = str(note).strip()
                if note and note not in llm_audience_notes:
                    llm_audience_notes.append(note)
            for item in (enriched.get("constraints") or []):
                item = str(item).strip()
                if item and item not in llm_constraints:
                    llm_constraints.append(item)
            if llm.last_error:
                llm_status.append(str(llm.last_error))
            # 硬字段只在规则完全缺失时接受，且仍会走引擎校验
            for key, value in (enriched.get("hard_fields") or {}).items():
                if key not in ("venue", "budget_wan", "media", "start_date", "weeks", "customer_type"):
                    continue
                if key in parsed:
                    continue
                if key == "venue":
                    if value not in valid_venues:
                        continue
                elif key == "budget_wan":
                    try:
                        value = float(str(value).replace("万", "").strip())
                    except (TypeError, ValueError):
                        continue
                elif key == "weeks":
                    try:
                        value = int(value)
                    except (TypeError, ValueError):
                        continue
                elif key == "media":
                    value = [str(x).strip().lower() for x in (value if isinstance(value, list) else [value])]
                elif key == "customer_type":
                    value = str(value).strip().lower()
                    if value not in ("direct", "4a"):
                        continue
                parsed[key] = _slot(value, SOURCE_LLM, "low", "LLM 语义解析，待校验")

    # ---- 结构化请求优先 ----------------------------------------------------
    structured_values = _request_from_structured(structured)
    for key, value in structured_values.items():
        if key == "industry" or key == "locks":
            continue
        if key == "media":
            value = [str(x).strip().lower() for x in (value if isinstance(value, list) else [value])]
        if key == "customer_type":
            value = str(value).strip().lower()
        confidence = "high"
        slots[key] = _slot(value, SOURCE_STRUCTURED, confidence, "显式结构化输入")
    structured_objective = str(structured.get("objective") or "").strip().lower()
    if structured_objective in ("balanced", "reach", "precision", "efficiency", "brand"):
        slots["objective"] = _slot(structured_objective, SOURCE_STRUCTURED, "high", "显式结构化输入")
    for key, slot in parsed.items():
        if key not in slots:
            slots[key] = slot

    # ---- 补默认值 / 校验 ---------------------------------------------------
    def add_question(field: str, question: str, why: str, options_list: List[Any],
                     default: Any, blocking: bool) -> None:
        if len(questions) >= max_questions:
            return
        questions.append({
            "id": f"Q{len(questions) + 1}",
            "field": field,
            "question": question,
            "why": why,
            "options": options_list,
            "default": default,
            "blocking": blocking,
        })

    def add_assumption(field: str, value: Any, reason: str, source: str = SOURCE_DEFAULT) -> None:
        assumptions.append({"field": field, "value": value, "reason": reason, "source": source})

    allow_defaults = bool(options.get("allow_defaults"))

    # venue
    venue = slots.get("venue")
    venue_conflict_asked = False
    if "venue" in conflicts:
        add_question(
            "venue",
            f"brief 同时提到多个场馆（{' / '.join(conflicts['venue'])}），这次以哪个为准？",
            "场馆决定人群、交通结构和可售库存池，不能同时成立。",
            [{"value": v, "label": next((x["name"] for x in catalog["venues"] if x["id"] == v), v)} for v in conflicts["venue"]],
            conflicts["venue"][0],
            True,
        )
        venue_conflict_asked = True
        slots.pop("venue", None)
        venue = None
    if venue is None or venue.missing:
        if venue_conflict_asked:
            pass
        elif allow_defaults:
            venue = _slot(defaults.get("venue", "lego_shanghai"), SOURCE_DEFAULT, "low", "未指定场馆，按默认乐高")
            slots["venue"] = venue
            add_assumption("venue", venue.value, "brief 未明确场馆，按默认乐高乐园分析", SOURCE_DEFAULT)
        else:
            add_question(
                "venue",
                "这次投放的是哪个乐园？",
                "场馆决定目标人群、交通结构（是否地铁直达）和可用库存。",
                [{"value": v["id"], "label": v["name"]} for v in catalog.get("venues", [])],
                "lego_shanghai",
                True,
            )
    elif venue.value not in valid_venues:
        add_question(
            "venue",
            f"暂不支持场馆「{venue.value}」，请从现有场馆中选择。",
            "当前引擎只覆盖上海三个乐园，不能拿别的场地套库存。",
            [{"value": v["id"], "label": v["name"]} for v in catalog.get("venues", [])],
            "lego_shanghai",
            True,
        )

    # budget
    budget = slots.get("budget_wan")
    bmin = float(budget_range.get("min_wan", 100))
    bmax = float(budget_range.get("max_wan", 500))
    if budget is None or budget.missing:
        if allow_defaults:
            budget = _slot(default_budget, SOURCE_DEFAULT, "low", f"未指定预算，按 {default_budget:g} 万分析")
            slots["budget_wan"] = budget
            add_assumption("budget_wan", budget.value, "brief 未明确预算，按 200 万中档分析", SOURCE_DEFAULT)
        else:
            add_question(
                "budget_wan",
                f"可用媒体预算是多少（{bmin:.0f}–{bmax:.0f} 万）？",
                "预算决定能买多少库存，也决定是否需要向下溢出到更广的点位。",
                [{"value": x, "label": f"{x} 万"} for x in (100, 200, 300, 500)],
                200,
                True,
            )
    else:
        try:
            bval = float(budget.value)
        except (TypeError, ValueError):
            bval = None
        if bval is None or bval < bmin or bval > bmax:
            if allow_defaults:
                clamped = min(bmax, max(bmin, round(bval or default_budget, 0)))
                slots["budget_wan"] = _slot(clamped, SOURCE_DEFAULT, "low", f"预算 {budget.value} 超出范围，已收敛到 {clamped} 万")
                add_assumption("budget_wan", clamped, f"预算 {budget.value} 超出 {bmin:.0f}–{bmax:.0f} 万，按最近边界 {clamped} 万分析", SOURCE_DEFAULT)
            else:
                add_question(
                    "budget_wan",
                    f"预算 {budget.value} 万超出当前引擎范围（{bmin:.0f}–{bmax:.0f} 万），请确认预算。",
                    "引擎按 100–500 万建模，超范围结果不可比。",
                    [{"value": x, "label": f"{x} 万"} for x in (100, 200, 300, 500)],
                    min(bmax, max(bmin, bval or default_budget)),
                    True,
                )

    # media
    media = slots.get("media")
    valid_media = {m["id"] for m in catalog.get("media", [])}
    if media is None or media.missing:
        if allow_defaults:
            media = _slot(["bus", "metro"], SOURCE_DEFAULT, "low", "未指定媒体，按公交+地铁分析")
            slots["media"] = media
            add_assumption("media", media.value, "brief 未明确媒介，按公交+地铁组合分析", SOURCE_DEFAULT)
        else:
            add_question(
                "media",
                "媒介范围：只投公交车身、只投地铁出入口，还是两者组合？",
                "公交和地铁的单价、库存与人群场景不同，需要确认后才能算。",
                [
                    {"value": ["bus", "metro"], "label": "公交+地铁"},
                    {"value": ["bus"], "label": "只投公交"},
                    {"value": ["metro"], "label": "只投地铁"},
                ],
                ["bus", "metro"],
                True,
            )
    else:
        vals = [str(x) for x in (media.value if isinstance(media.value, list) else [media.value])]
        bad = [x for x in vals if x not in valid_media]
        if bad or not vals:
            if allow_defaults:
                slots["media"] = _slot(["bus", "metro"], SOURCE_DEFAULT, "low", f"媒介 {vals} 非法，按公交+地铁分析")
                add_assumption("media", ["bus", "metro"], f"媒介 {vals} 不在可选范围，按公交+地铁分析", SOURCE_DEFAULT)
            else:
                add_question(
                    "media",
                    f"无法识别媒介「{', '.join(bad or vals)}」，请选择公交/地铁。",
                    "引擎只支持公交车身与地铁出入口两类。",
                    [{"value": ["bus", "metro"], "label": "公交+地铁"}, {"value": ["bus"], "label": "只投公交"}, {"value": ["metro"], "label": "只投地铁"}],
                    ["bus", "metro"],
                    True,
                )

    # start_date
    start = slots.get("start_date")
    if start is None or start.missing:
        start = _slot(defaults.get("start_date", "2027-07-01"), SOURCE_DEFAULT, "medium", "未指定档期，按 2027 暑期起算")
        slots["start_date"] = start
        add_assumption("start_date", start.value, "brief 未明确开始日期，按 2027-07-01 暑期档假设", SOURCE_DEFAULT)
    else:
        try:
            d = _dt.date.fromisoformat(str(start.value))
            if d.year != 2027:
                if allow_defaults:
                    start = _slot("2027-07-01", SOURCE_DEFAULT, "low", f"年份 {d.year} 超出赛题范围，按 2027-07-01")
                    slots["start_date"] = start
                    add_assumption("start_date", start.value, f"日期 {start.value} 不在 2027 年，按 2027-07-01 分析", SOURCE_DEFAULT)
                else:
                    add_question(
                        "start_date",
                        f"档期 {start.value} 不在 2027 年内，请确认 2027 年的投放日期。",
                        "当前库存快照与赛题档期限定在 2027 年。",
                        [{"value": "2027-07-01", "label": "2027-07-01 暑期"}],
                        "2027-07-01",
                        True,
                    )
        except (ValueError, TypeError):
            if allow_defaults:
                slots["start_date"] = _slot("2027-07-01", SOURCE_DEFAULT, "low", "日期非法，按 2027-07-01")
                add_assumption("start_date", "2027-07-01", f"无法解析日期 {start.value}，按 2027-07-01 分析", SOURCE_DEFAULT)
            else:
                add_question(
                    "start_date",
                    "开始日期无法识别，请给出 2027 年内的日期（YYYY-MM-DD）。",
                    "档期决定红豆库存的可用月份。",
                    [{"value": "2027-07-01", "label": "2027-07-01 暑期"}],
                    "2027-07-01",
                    True,
                )

    # weeks
    weeks = slots.get("weeks")
    if weeks is None or weeks.missing:
        weeks = _slot(defaults.get("weeks", 8), SOURCE_DEFAULT, "medium", "未指定周数，按 8 周暑期档")
        slots["weeks"] = weeks
        add_assumption("weeks", weeks.value, "brief 未明确投放周数，按 8 周假设", SOURCE_DEFAULT)
    else:
        try:
            wval = int(weeks.value)
        except (TypeError, ValueError):
            wval = None
        if wval not in allowed_weeks:
            if allow_defaults:
                nearest = _nearest_weeks(wval or 8, allowed_weeks)
                slots["weeks"] = _slot(nearest, SOURCE_DEFAULT, "low", f"周数 {weeks.value} 不在可选范围，收敛到 {nearest}")
                add_assumption("weeks", nearest, f"周数 {weeks.value} 不在 {allowed_weeks}，按最近档 {nearest} 周分析", SOURCE_DEFAULT)
            else:
                add_question(
                    "weeks",
                    f"投放周数 {weeks.value} 不在可选档位，请选择 {allowed_weeks} 之一。",
                    "排期与施工产能按固定周数档位建模。",
                    [{"value": x, "label": f"{x} 周"} for x in allowed_weeks],
                    _nearest_weeks(wval or 8, allowed_weeks),
                    True,
                )

    # customer_type
    customer = slots.get("customer_type")
    if customer is None or customer.missing:
        customer = _slot(defaults.get("customer_type", "direct"), SOURCE_DEFAULT, "medium", "未说明客户类型，按直客")
        slots["customer_type"] = customer
        add_assumption("customer_type", customer.value, "brief 未说明直客/4A，按直客分析（不含 15% 代理费）", SOURCE_DEFAULT)
    elif str(customer.value) not in ("direct", "4a"):
        if allow_defaults:
            slots["customer_type"] = _slot("direct", SOURCE_DEFAULT, "low", f"客户类型 {customer.value} 非法，按直客")
            add_assumption("customer_type", "direct", f"客户类型 {customer.value} 无法识别，按直客分析", SOURCE_DEFAULT)
        else:
            add_question(
                "customer_type",
                "这单是直客还是 4A 代理？",
                "4A 代理会加 15% 服务费，影响报价与预算约束。",
                [{"value": "direct", "label": "直客"}, {"value": "4a", "label": "4A 代理"}],
                "direct",
                False,
            )

    # objective 不入引擎，只影响分析视角
    objective = slots.get("objective") or objective_slot
    slots["objective"] = objective

    # ---- 构造引擎请求 ------------------------------------------------------
    request: Dict[str, Any] = {
        "industry": "乐园",
        "venue": (slots.get("venue").value if slots.get("venue") else defaults.get("venue", "lego_shanghai")),
        "budget_wan": (float(slots["budget_wan"].value) if slots.get("budget_wan") and not slots["budget_wan"].missing else default_budget),
        "media": (list(slots["media"].value) if slots.get("media") and not slots["media"].missing else ["bus", "metro"]),
        "start_date": (str(slots["start_date"].value) if slots.get("start_date") and not slots["start_date"].missing else "2027-07-01"),
        "weeks": (int(slots["weeks"].value) if slots.get("weeks") and not slots["weeks"].missing else 8),
        "customer_type": (str(slots["customer_type"].value) if slots.get("customer_type") and not slots["customer_type"].missing else "direct"),
        "locks": structured.get("locks") or {"include": [], "exclude": []},
    }
    if structured.get("brief_text") and not raw_text:
        request["brief_text"] = str(structured["brief_text"])

    # 结构化 locks 校验
    locks = request.get("locks") or {}
    if not isinstance(locks, dict):
        request["locks"] = {"include": [], "exclude": []}
        add_assumption("locks", request["locks"], "locks 格式非法，已重置为空锁定", SOURCE_DEFAULT)
    else:
        request["locks"] = {
            "include": [str(x) for x in (locks.get("include") or [])],
            "exclude": [str(x) for x in (locks.get("exclude") or [])],
        }

    # ---- 推断值也必须有 assumption ----------------------------------------
    existing_assumptions = {(a.get("field"), str(a.get("value"))) for a in assumptions}
    for field in ("venue", "budget_wan", "media", "start_date", "weeks", "customer_type"):
        slot = slots.get(field)
        if slot and slot.source == SOURCE_INFERRED:
            key = (field, str(slot.value))
            if key not in existing_assumptions:
                add_assumption(field, slot.value, slot.evidence or "brief 推断", SOURCE_INFERRED)
                existing_assumptions.add(key)

    # ---- 合规扫描 ----------------------------------------------------------
    compliance_flags = detect_compliance_flags(raw_text, compliance_policy)
    if compliance_flags:
        add_assumption(
            "compliance",
            "brief 含需改写措辞",
            "已按合规口径改写：不投校内、不承诺到园/ROI；见 compliance_flags",
            "policy",
        )

    # ---- 状态 --------------------------------------------------------------
    missing = [f for f in REQUIRED_SLOTS if f not in slots or slots[f].missing]
    blocking = [q for q in questions if q.get("blocking")]
    if blocking:
        status = STATUS_NEEDS_CLARIFICATION
    elif assumptions:
        status = STATUS_READY_WITH_ASSUMPTIONS
    else:
        status = STATUS_READY

    summary = _brief_summary(request, slots, objective.value if objective else "balanced", status)
    audience_notes = _audience_notes(raw_text)
    for note in llm_audience_notes:
        if not any(note in existing or existing in note for existing in audience_notes):
            audience_notes.append(note)
    return BriefState(
        raw_text=raw_text,
        request=request,
        slots=slots,
        missing=missing,
        questions=questions,
        assumptions=assumptions,
        objective=str(objective.value if objective else "balanced"),
        audience_notes=audience_notes,
        constraints={
            "locks": request["locks"],
            "compliance_flags": compliance_flags,
            "llm_notes": llm_constraints,
            "llm_status": llm_status,
        },
        compliance_flags=compliance_flags,
        status=status,
        summary=summary,
    )


def _brief_summary(request: Dict[str, Any], slots: Dict[str, SlotValue], objective: str, status: str) -> str:
    venue = request.get("venue")
    media = "+".join({"bus": "公交", "metro": "地铁"}.get(m, m) for m in request.get("media", []))
    return (
        f"{venue} / {request.get('budget_wan')} 万 / {media} / "
        f"{request.get('start_date')} 起 {request.get('weeks')} 周 / 目标：{objective} / 状态：{status}"
    )


def _intake_prompt() -> str:
    return (
        "你是户外媒体提案的需求解析器。只从客户原文抽取字段，不补造、不计算。\n"
        "硬字段：venue(id: lego_shanghai|disney_shanghai|haichang_shanghai), budget_wan(万元), "
        "media(数组，id: bus|metro), start_date(YYYY-MM-DD), weeks(2|4|6|8|12), customer_type(direct|4a)。\n"
        "软字段：objective(balanced|reach|precision|efficiency|brand), audience_notes, constraints。\n"
        "规则：客户没明确说的硬字段就省略；不要把“乐高”当客户类型；"
        "media 用 id 不要用中文；不确定就省略。不要输出解释，只输出 JSON。"
    )


def _brief_json_schema() -> Dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "hard_fields": {
                "type": "object",
                "properties": {
                    "venue": {
                        "type": "string",
                        "enum": ["lego_shanghai", "disney_shanghai", "haichang_shanghai"],
                    },
                    "budget_wan": {"type": "number"},
                    "media": {
                        "type": "array",
                        "items": {"type": "string", "enum": ["bus", "metro"]},
                    },
                    "start_date": {"type": "string"},
                    "weeks": {"type": "integer", "enum": [2, 4, 6, 8, 12]},
                    "customer_type": {"type": "string", "enum": ["direct", "4a"]},
                },
                "additionalProperties": False,
            },
            "objective": {"type": "string", "enum": ["balanced", "reach", "precision", "efficiency", "brand"]},
            "audience_notes": {"type": "array", "items": {"type": "string"}},
            "constraints": {"type": "array", "items": {"type": "string"}},
        },
        "additionalProperties": False,
    }


def request_signature(request: Dict[str, Any]) -> str:
    """场景去重用的稳定签名。"""
    media = ",".join(sorted(str(x) for x in (request.get("media") or [])))
    locks = request.get("locks") or {}
    inc = ",".join(sorted(str(x) for x in (locks.get("include") or [])))
    exc = ",".join(sorted(str(x) for x in (locks.get("exclude") or [])))
    return "|".join([
        str(request.get("venue")),
        f"{float(request.get('budget_wan') or 0):.2f}",
        media,
        str(request.get("start_date")),
        str(request.get("weeks")),
        str(request.get("customer_type")),
        inc,
        exc,
    ])


__all__ = [
    "resolve_brief",
    "detect_compliance_flags",
    "normalize_text",
    "cn_to_number",
    "request_signature",
]
