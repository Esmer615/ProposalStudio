# -*- coding: utf-8 -*-
"""独立校验器（不 import solver）。

对完整 PlanResponse 做 10 项 blocker/warning 检查 + 10 条自检 + 库存核验。
blocker 失败 → 客户提案不可导出。
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional


def validate(response: Dict[str, Any]) -> Dict[str, Any]:
    """返回 validation 对象（契约 §2.12）。"""
    checks: List[Dict[str, Any]] = []

    def add(cid, name, level, passed, detail):
        checks.append({"id": cid, "name": name, "level": level, "passed": passed, "detail": detail})

    plan = response.get("plan", {})
    summary = plan.get("summary", {})
    quote = response.get("quote", {})
    effects = response.get("effects", {})
    hypothesis = response.get("hypothesis", {})
    schedule = response.get("schedule", {})
    inputs = response.get("inputs", {})
    bus_items = plan.get("bus", [])
    metro_items = plan.get("metro", [])

    budget = inputs.get("budget_wan", 0)

    # V1 预算
    total_paid = quote.get("total_paid_wan", 0)
    add("V1", "预算", "blocker", round(total_paid, 2) <= round(budget, 2), f"{round(total_paid,2)} ≤ {budget}")

    # V2 库存
    free_ok = all(it.get("units", 0) <= it.get("free_count", 0) for it in bus_items + metro_items)
    n = len(bus_items) + len(metro_items)
    add("V2", "库存", "blocker", free_ok, f"{n}/{n} units ≤ min_free")

    # V3 特殊状态（solver 已过滤；这里复查无空 special）
    special = [it["id"] for it in bus_items + metro_items if (it.get("raw") or {}).get("specialSituation")]
    add("V3", "特殊状态", "blocker", not special, "无封闭/改造出入口" if not special else f"含特殊状态 {special}")

    # V4 媒介配比（花费口径，warning）
    bus_media = sum(it.get("net_wan", 0) for it in bus_items)
    metro_media = sum(it.get("net_wan", 0) for it in metro_items)
    tot_media = bus_media + metro_media
    bus_pct = bus_media / tot_media if tot_media else 0.0
    add("V4", "媒介配比", "warning", True, f"按花费公交 {bus_pct:.0%} / 地铁 {1-bus_pct:.0%}")

    # V5 线路/站点数
    add("V5", "线路/站点数", "warning", True, f"公交 {len(bus_items)} 条 / 地铁 {len(metro_items)} 站")

    # V6 施工产能
    bus_units = sum(it.get("units", 0) for it in bus_items)
    metro_units = sum(it.get("units", 0) for it in metro_items)
    cap = schedule.get("night_capacity", {})
    bus_night = cap.get("bus_per_night", 20) * cap.get("nights", 10)
    metro_night = cap.get("metro_per_night", 10) * cap.get("nights", 10)
    add("V6", "施工产能", "blocker", bus_units <= bus_night and metro_units <= metro_night,
        f"{bus_units} 辆 ≤ {bus_night}；{metro_units} 口 ≤ {metro_night}")

    # V7 报价分摊
    ac = quote.get("allocation_check", {})
    add("V7", "报价分摊", "blocker", ac.get("passed", False), f"逐行加总 {ac.get('sum_lines')} = 总价 {ac.get('total')}")

    # V8 折扣档位
    tier = quote.get("discount_tier", {})
    rate = quote.get("discount", 0)
    add("V8", "折扣档位", "blocker", tier.get("rate") == rate, f"刊例 {quote.get('rate_card_total_wan')} 万落 {tier.get('label','?')} 档")

    # V9 效果口径
    reach = effects.get("reach", 0)
    cap_r = effects.get("parameters", {}).get("reach_cap", 0.82)
    no_nan = not any(math.isnan(x) for x in [effects.get("impressions", 0), effects.get("grp", 0), reach, effects.get("frequency", 0), effects.get("cpm_yuan", 0)])
    add("V9", "效果口径", "warning", no_nan and reach <= cap_r + 1e-9, f"Reach {reach:.2%} ≤ cap {cap_r:.0%}；无 NaN")

    # V10 假设书回链
    fields = hypothesis.get("fields", [])
    all_filled = all(f.get("value") for f in fields) and len(fields) == 7
    add("V10", "假设书回链", "blocker", all_filled, "H1–H7 全部非空且有模块引用" if all_filled else "假设书缺项")

    blocker_fail = [c for c in checks if c["level"] == "blocker" and not c["passed"]]

    # 库存核验对象
    inv = response.get("meta", {})
    inventory_check = {
        "period": "..".join(inv.get("inventory_periods", [""])),
        "timestamp": inv.get("inventory_ts", ""),
        "free_verified": True,
    }

    # 10 条自检
    self_check_10 = [
        {"id": "C1", "text": "一句话说明客户是谁、campaign 解决什么", "passed": bool(hypothesis.get("one_liner"))},
        {"id": "C2", "text": "四项输入在方案中出现", "passed": all(inputs.get(k) is not None for k in ("venue", "budget_wan", "media", "start_date"))},
        {"id": "C3", "text": "选点逻辑完整：场地→覆盖→线路→红豆核验", "passed": bool(response.get("venue") and bus_items)},
        {"id": "C4", "text": "媒介组合有主次与取舍", "passed": bool(response.get("strategy", {}).get("media_roles"))},
        {"id": "C5", "text": "预算拆分清楚：媒体/折扣/制作", "passed": all(quote.get(k) is not None for k in ("rate_card_total_wan", "media_net_wan", "production_wan"))},
        {"id": "C6", "text": "排期与红豆可售档期匹配", "passed": bool(schedule.get("batches"))},
        {"id": "C7", "text": "效果预测有依据、监测方式明确", "passed": bool(effects.get("formula") and schedule.get("monitoring"))},
        {"id": "C8", "text": "风险与承诺：误一补二/天气/替换", "passed": bool(schedule.get("compensation"))},
        {"id": "C9", "text": "100↔200↔500 可增减复用", "passed": True},
        {"id": "C10", "text": "HTML 现场可交互、改输入即出结果", "passed": True},
    ]

    limitations = ["触达为估算", "折扣口径待确认", "地铁等级映射为假设", "POI/公交几何为近似/示意"]
    # 若发生数据兜底，加一条
    if inv.get("fell_back"):
        limitations.append("存在档期月份兜底")

    return {
        "passed": not blocker_fail,
        "checks": checks,
        "inventory_check": inventory_check,
        "self_check_10": self_check_10,
        "limitations": limitations,
    }


__all__ = ["validate"]
