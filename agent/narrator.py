# -*- coding: utf-8 -*-
"""提案话术：把分析结果说成人话，同时守住数字与合规口径。

默认走确定性模板；配置了 DeepSeek 时可以做语言润色，但必须通过：
1) 数字守卫：不得引入分析结果里不存在的数字；
2) 合规守卫：不得出现到园承诺/ROI/校内投放等危险表述。
任一不通过 → 回退模板，不拿客户提案冒险。
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from .contracts import BriefState, STATUS_NEEDS_CLARIFICATION
from .intake import detect_compliance_flags

_LEVEL_LABEL = {"critical": "严重", "high": "高", "medium": "中", "low": "提示"}
_VENUE_NAMES = {
    "lego_shanghai": "上海乐高乐园",
    "disney_shanghai": "上海迪士尼度假区",
    "haichang_shanghai": "上海海昌海洋公园",
}
_MEDIA_LABEL = {"bus": "公交车身", "metro": "地铁出入口"}
_STATIC_ALLOWED_NUMBERS = {
    # 赛题/业务常量（话术中允许出现，不代表具体方案数值）
    100, 150, 200, 250, 300, 350, 400, 450, 500,
    2, 4, 5, 6, 8, 10, 12, 15, 20, 23, 85, 2027, 2026,
    # 折扣档位（88/83/78/73/68%）
    88, 83, 78, 73, 68,
}
_COMMA_IN_NUMBER = re.compile(r"(?<=\d),(?=\d)")


def build_narrative(
    payload: Dict[str, Any],
    *,
    brief: BriefState,
    llm: Any = None,
    policy: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    status = payload.get("status")
    if status == STATUS_NEEDS_CLARIFICATION:
        md = _clarification_markdown(brief)
        return {
            "mode": "rules",
            "headline": "需要补充信息后才能分析",
            "markdown": md,
            "number_guard": {"ok": True, "unknown": []},
            "llm_used": False,
        }

    md = _render_rules(payload, brief)
    result = {
        "mode": "rules",
        "headline": payload.get("headline") or "方案分析",
        "markdown": md,
        "number_guard": {"ok": True, "unknown": []},
        "llm_used": False,
    }

    if llm is None or not getattr(llm, "available", False):
        return result

    try:
        polished = llm.polish_narrative(md, payload, _narrative_prompt(policy))
    except Exception as exc:  # pragma: no cover - 外部服务异常
        result["llm_error"] = f"{type(exc).__name__}: {exc}"
        return result

    if not isinstance(polished, str) or len(polished.strip()) < 200:
        result["llm_error"] = "LLM 输出为空或过短，已回退模板"
        return result

    ok_numbers, unknown = guard_numbers(polished, payload)
    flags = detect_compliance_flags(polished, policy)
    if not ok_numbers:
        result["number_guard"] = {"ok": False, "unknown": unknown}
        result["llm_error"] = "LLM 输出引入了未知数字，已回退模板"
        return result
    if flags:
        result["number_guard"] = {"ok": True, "unknown": []}
        result["llm_error"] = f"LLM 输出触发合规用语 {[f.get('matched') for f in flags]}，已回退模板"
        return result

    result.update({
        "mode": "llm",
        "markdown": polished.strip() + "\n",
        "number_guard": {"ok": True, "unknown": []},
        "llm_used": True,
    })
    return result


# --------------------------------------------------------------------------- #
# 确定性模板
# --------------------------------------------------------------------------- #
def _render_rules(payload: Dict[str, Any], brief: BriefState) -> str:
    primary = payload.get("primary") or {}
    m = primary.get("metrics") or {}
    rec = payload.get("recommendation") or {}
    comparison = payload.get("comparison") or []
    elasticity = payload.get("elasticity") or {}
    risks = primary.get("risks") or []
    request = brief.request
    venue_name = _VENUE_NAMES.get(str(request.get("venue")), str(request.get("venue")))
    media = " + ".join(_MEDIA_LABEL.get(x, x) for x in (request.get("media") or []))
    objective = payload.get("objective_label") or brief.objective

    lines: List[str] = []
    lines.append(f"# 提案分析 · {venue_name} · {_fmt_wan(request.get('budget_wan'))} · {request.get('weeks')} 周")
    lines.append("")
    lines.append(
        f"> 数据版本 {payload.get('meta', {}).get('data_version', '—')} · "
        f"引擎 {payload.get('meta', {}).get('solver', '—')} · "
        "曝光/Reach/频次/CPM 为模型估算，POI 为公开近似，不承诺到园人数或财务 ROI。"
    )
    lines.append("")

    lines.append("## 结论")
    lines.append(rec.get("summary") or "（无可用结论）")
    lines.append("")
    verdict_label = {
        "recommend": "可推荐",
        "recommend_with_caveats": "有保留地推荐",
        "not_recommended": "不建议直接提案",
    }.get(rec.get("verdict"), rec.get("verdict") or "—")
    lines.append(f"- 结论：**{verdict_label}**；主方案「{rec.get('primary_label') or primary.get('label')}」。")
    if primary.get("score"):
        lines.append(f"- 综合评分：{primary['score'].get('total')} / 100（按「{objective}」视角加权，仅用于方案间对比）。")
    if rec.get("why"):
        lines.append("- 判断依据：")
        for w in rec.get("why") or []:
            lines.append(f"  - {w}")
    lines.append("")

    lines.append("## 需求理解")
    lines.append(f"- 场馆：{venue_name}（{request.get('venue')}）。")
    lines.append(f"- 预算：{_fmt_wan(request.get('budget_wan'))}；媒介：{media}；档期：{request.get('start_date')} 起 {request.get('weeks')} 周。")
    lines.append(f"- 客户类型：{'4A 代理' if request.get('customer_type') == '4a' else '直客'}；分析视角：{objective}。")
    if brief.audience_notes:
        lines.append(f"- 客户提到的人群/场景：{'；'.join(brief.audience_notes[:3])}。")
    if brief.assumptions:
        lines.append("- 本次分析的显式假设：")
        for a in brief.assumptions:
            lines.append(f"  - {a.get('field')} = {a.get('value')}：{a.get('reason')}")
    if brief.compliance_flags:
        lines.append("- 合规提示：brief 中有需要改写的表述；提案统一用“学校周边 300–500 米”，不投校内。")
    lines.append("")

    lines.append("## 场景对比")
    if comparison:
        lines.append(_comparison_table(comparison))
        lines.append("")
        lines.append("> 注意：不同预算的场景不能只看 Reach 绝对值，必须同时看预算使用率与每万元目标 Reach。评分只用于同一目标视角下的相对比较。")
    else:
        lines.append("（无可用场景）")
    lines.append("")

    lines.append("## 主方案解读")
    if m:
        lines.append(f"- 预算：{_fmt_wan(m.get('budget_wan'))}；实际落地 {_fmt_wan(m.get('total_paid_wan'))}（使用率 {_fmt_pct(m.get('utilization'))}，剩余 {_fmt_wan(m.get('budget_slack_wan'))}）。")
        lines.append(f"- 效果：总曝光 {_fmt_int(m.get('impressions'))} 人次；目标人群 Reach {m.get('reach_pct_label')}（目标人群 {_fmt_int(m.get('target_population'))}，策划假设）；频次 {m.get('frequency')}；混合 CPM {m.get('cpm_yuan')} 元。")
        lines.append(f"- 规模：公交 {m.get('bus_units')} 辆 / {m.get('bus_lines')} 条线；地铁 {m.get('metro_units')} 口 / {m.get('metro_stations')} 站；命中 {m.get('poi_hits')} 个亲子/家庭 POI。")
        lines.append(f"- 报价：刊例 {_fmt_wan(m.get('gross_wan'))}，落 {m.get('discount_label') or '—'} 档；媒体净价 {_fmt_wan(m.get('media_net_wan'))}；制作费 {_fmt_wan(m.get('production_wan'))}；代理费 {_fmt_wan(m.get('agency_fee_wan'))}；赠媒 {_fmt_wan(m.get('gift_wan'))}。")
        sched = m.get("schedule") or {}
        if sched:
            lines.append(f"- 排期：{sched.get('go_live')} 上刊，{sched.get('take_down')} 下刊；{sched.get('total_days')} 天；夜间施工 {sched.get('batches')} 批；含雨备与监测 SLA。")
        val = m.get("validation") or {}
        lines.append(f"- 独立校验：{'通过' if val.get('passed') else '未通过'}（{len(val.get('blockers') or [])} 个 blocker / {len(val.get('warnings') or [])} 个 warning）。")
        picks = primary.get("top_picks") or []
        if picks:
            lines.append("- 代表点位（按评分）：")
            for p in picks[:5]:
                reasons = "；".join(p.get("reasons") or [])
                lines.append(f"  - {p.get('name')}（{p.get('kind')} / {p.get('level')} / {p.get('units')} 单位 / 折后 {_fmt_wan(p.get('net_wan'))}）：{reasons}")
        strategy = m.get("strategy") or {}
        if strategy.get("mix_rationale"):
            lines.append(f"- 组合逻辑：{strategy.get('mix_rationale')}")
        for t in primary.get("tradeoffs") or []:
            lines.append(f"- 取舍：{t}")
    else:
        lines.append("（主方案无可用指标）")
    lines.append("")

    alternatives = rec.get("alternatives") or []
    if alternatives:
        lines.append("## 备选与取舍")
        for a in alternatives:
            delta = a.get("delta_vs_primary") or {}
            bits = []
            if abs(float(delta.get("budget_wan") or 0)) >= 1:
                bits.append(f"预算 {float(delta.get('budget_wan')):+.0f} 万")
            if delta.get("reach_people"):
                bits.append(f"目标 Reach {int(delta.get('reach_people')):+,} 人")
            delta_text = "；".join(bits) if bits else "预算不变"
            when = str(a.get("when_to_use") or "").rstrip("。")
            tradeoff = str(a.get("tradeoff") or "").rstrip("。")
            parts = [f"- **{a.get('label')}**（评分 {a.get('score')}）"]
            if when:
                parts.append(f"适用：{when}")
            if tradeoff:
                parts.append(f"代价：{tradeoff}")
            parts.append(f"相对主方案：{delta_text}（模型估算）")
            lines.append("；".join(parts) + "。")
        lines.append("")

    lines.append("## 预算弹性")
    if elasticity.get("available"):
        lines.append(f"- 当前预算 {elasticity.get('current_budget_wan')} 万；弹性拐点 {elasticity.get('knee_budget_wan')} 万。")
        lines.append(f"- {elasticity.get('interpretation')}")
        cur = elasticity.get("current_point") or {}
        if cur:
            lines.append(f"- 当前档位：总曝光 {_fmt_int(cur.get('impressions'))} 人次；Reach {_fmt_pct(cur.get('reach'))}；边际每万元曝光 {_fmt_int(cur.get('marginal_impressions_per_wan'))}。")
        lines.append(f"- 口径：{elasticity.get('note')}")
    else:
        lines.append("- 本次未计算预算弹性。")
    lines.append("")

    lines.append("## 风险与口径")
    if risks:
        for r in risks:
            lines.append(f"- [{_LEVEL_LABEL.get(r.get('level'), r.get('level'))}] {r.get('message')} → {r.get('action')}")
    else:
        lines.append("- 未发现额外风险；仍需主动披露估算口径。")
    lines.append("")

    lines.append("## 建议与下一步")
    for action in rec.get("next_actions") or []:
        lines.append(f"- {action}")
    lines.append("")

    lines.append("## 数据来源")
    dq = m.get("data_quality") or {}
    inv = dq.get("inventory") or {}
    lines.append(f"- 库存：{inv.get('source') or '红豆快照'}（数据版本 {inv.get('data_version') or '—'}，时间 {inv.get('timestamp') or '—'}）。")
    lines.append("- 人群/POI：公开近似 POI 库；目标人群为场馆档案策划假设，不是实测去重人群。")
    lines.append("- 曝光/Reach/频次/CPM：引擎确定性与饱和曲线模型估算；当前未接可视化平台实测人流。")
    lines.append("- 折扣：按全单刊例总额落档（88/83/78/73/68%），档位口径待赞助方最终确认。")
    lines.append("- 学校相关：只覆盖学校周边 300–500 米的地铁/公交点位，不投校内。")
    lines.append("")
    return "\n".join(lines)


def _comparison_table(rows: List[Dict[str, Any]]) -> str:
    lines = [
        "| 方案 | 预算 | 实际落地 | 使用率 | 总曝光 | 目标 Reach | 频次 | CPM | POI | 评分 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in rows:
        if r.get("status") == "failed":
            lines.append(f"| {r.get('label')} | — | — | — | — | — | — | — | — | 失败 |")
            continue
        lines.append(
            f"| {r.get('label')} | {_fmt_wan(r.get('budget_wan'))} | {_fmt_wan(r.get('total_paid_wan'))} | "
            f"{_fmt_pct(r.get('utilization'))} | {_fmt_int(r.get('impressions'))} | "
            f"{_fmt_pct(r.get('reach_pct'))} | {r.get('frequency')} | {r.get('cpm_yuan')} | "
            f"{r.get('poi_hits')} | {r.get('score')} |"
        )
    return "\n".join(lines)


def _clarification_markdown(brief: BriefState) -> str:
    lines = ["# 需要补充信息", ""]
    lines.append("当前 brief 缺少关键字段，先不跑方案，避免用默认值编出一个看起来完整的结论。")
    lines.append("")
    for q in brief.questions:
        mark = "必须确认" if q.get("blocking") else "建议确认"
        lines.append(f"- **{q.get('question')}**（{mark}）")
        lines.append(f"  - 原因：{q.get('why')}")
        if q.get("options"):
            opts = "；".join(str(o.get("label") if isinstance(o, dict) else o) for o in q.get("options") or [])
            lines.append(f"  - 可选：{opts}")
    lines.append("")
    if brief.assumptions:
        lines.append("已做出的假设：")
        for a in brief.assumptions:
            lines.append(f"- {a.get('field')} = {a.get('value')}：{a.get('reason')}")
    lines.append("")
    lines.append("补齐后重新运行；或显式允许默认值，Agent 会把所有假设逐条列出。")
    lines.append("")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# 数字 / 合规守卫
# --------------------------------------------------------------------------- #
def guard_numbers(text: str, payload: Dict[str, Any]) -> Tuple[bool, List[str]]:
    allowed = set(_STATIC_ALLOWED_NUMBERS)
    _collect_numbers(payload, allowed)
    unknown: List[str] = []
    clean_text = _COMMA_IN_NUMBER.sub("", text)
    for raw in re.findall(r"(?<![\w.-])\d+(?:\.\d+)?(?![\w.-])", clean_text):
        try:
            num = float(raw)
        except ValueError:
            continue
        if num <= 12:
            continue
        if _num_in_set(num, allowed):
            continue
        unknown.append(raw)
    return (not unknown), sorted(set(unknown))


def _num_in_set(num: float, allowed: set) -> bool:
    for a in allowed:
        try:
            if abs(float(a) - num) <= 0.051:
                return True
        except (TypeError, ValueError):
            continue
    return False


def _collect_numbers(obj: Any, out: set) -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(k, str):
                for raw in re.findall(r"\d+(?:\.\d+)?", k):
                    _add_number(out, float(raw))
            _collect_numbers(v, out)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _collect_numbers(v, out)
    elif isinstance(obj, (int, float)) and not isinstance(obj, bool):
        _add_number(out, float(obj))
    elif isinstance(obj, str):
        clean = _COMMA_IN_NUMBER.sub("", obj)
        for raw in re.findall(r"\d+(?:\.\d+)?", clean):
            try:
                _add_number(out, float(raw))
            except ValueError:
                pass


def _add_number(out: set, num: float) -> None:
    out.add(num)
    for digits in (0, 1, 2):
        out.add(round(num, digits))
    # 比例（0–1）在话术里通常写成百分比，允许 0.803 ↔ 80.3
    if 0 <= num <= 1:
        pct = num * 100
        out.add(pct)
        for digits in (0, 1, 2):
            out.add(round(pct, digits))


def _narrative_prompt(policy: Optional[Dict[str, Any]]) -> str:
    forbidden = (policy or {}).get("forbidden_claims") or []
    forbidden_text = "；".join(
        f"{r.get('match')} → {r.get('guidance')}" if isinstance(r, dict) else str(r)
        for r in forbidden
    )
    return (
        "你是户外媒体提案的资深策划。请在给定分析结果的基础上改写提案话术。"
        "硬性要求：只使用输入中出现的数字，不新增任何数字；不承诺到园人数、销量、ROI；"
        "不投校内，统一说“学校周边 300–500 米”；每个曝光/Reach 数字必须带“模型估算”口径；"
        "主动说明预算使用率与未花完金额；至少保留两个方案的权衡，不给单一“最优解”。"
        "输出 Markdown，保留原有章节结构。"
        + (f" 禁用/改写：{forbidden_text}。" if forbidden_text else "")
    )


# --------------------------------------------------------------------------- #
def _fmt_wan(v: Any) -> str:
    try:
        return f"{float(v):.1f} 万"
    except (TypeError, ValueError):
        return "—"


def _fmt_pct(v: Any) -> str:
    try:
        return f"{float(v):.1%}"
    except (TypeError, ValueError):
        return "—"


def _fmt_int(v: Any) -> str:
    try:
        return f"{int(round(float(v))):,}"
    except (TypeError, ValueError):
        return "—"


__all__ = ["build_narrative", "guard_numbers"]
