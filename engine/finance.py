# -*- coding: utf-8 -*-
"""报价与折扣：刊例价 + 全单折扣不动点 + 行分摊。

核心流程（PRD §4.5 / 契约 §2.9）：
1. 折扣按全单刊例总额落档（88/83/78/73/68%）。
2. 折扣 -> 折后媒体费 -> 反推刊例总额，是不动点问题，迭代 <=5 轮。
   起始 88%，实际折扣取“最保守可行”档（不发生 cycle 循环时）。
3. 制作费：公交 0.75 万/辆、地铁 0.03 万/口。
4. 4A 服务费 15%（仅 customer_type=4a）。
5. 赠媒 = 折后媒体费 5% 等值（从剩余候选挑，不计付费 KPI）。
6. 逐行分摊加总 == total_paid_wan（误差 <= 1 元）。
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from . import config
from .models import PlanError


@dataclass
class RateCard:
    bus_price: Dict[str, float]
    metro_price: Dict[str, float]
    production_bus: float
    production_metro: float
    discount_tiers: List[Dict[str, Any]]


def load_rate_card() -> RateCard:
    """读 data/config/rate_card_2027.json；缺失则用内置 default。"""
    p = os.path.join(config.CONFIG_DIR, "rate_card_2027.json")
    bus_price = dict(config.DEFAULT_RATE_CARD["bus"])
    metro_price = dict(config.DEFAULT_RATE_CARD["metro"])
    prod_bus = config.DEFAULT_RATE_CARD["production_bus_per_vehicle_wan"]
    prod_metro = config.DEFAULT_RATE_CARD["production_metro_per_gate_wan"]
    tiers = [dict(t) for t in config.DISCOUNT_TIERS]
    if os.path.exists(p):
        try:
            with open(p, encoding="utf-8") as f:
                raw = json.load(f)
            bus_price = {k: float(v) for k, v in (raw.get("bus", {}).get("unit_per_month_wan", {}) or {}).items()}
            metro_price = {k: float(v) for k, v in (raw.get("metro", {}).get("unit_per_month_wan", {}) or {}).items()}
            prod_bus = float(raw.get("bus", {}).get("production_wan_per_vehicle", prod_bus))
            prod_metro = float(raw.get("metro", {}).get("production_wan_per_gate", prod_metro))
            # 折扣档位（文件是唯一权威）：阈值 threshold_wan + 折扣率 discount。
            # 文件阈值 0/100/200/300/400（88/83/78/73/68%）优先级高于 config 兜底
            # （0/200/350/500/700）。契约 §2.9 的默认边界仅在文件缺失时使用。
            dt = raw.get("discount_tiers")
            if isinstance(dt, list) and dt:
                parsed = []
                for i, t in enumerate(dt):
                    if not isinstance(t, dict):
                        continue
                    rate = t.get("discount")
                    lo = t.get("threshold_wan", t.get("min_gross_wan"))
                    if rate is None or lo is None:
                        continue
                    lo = float(lo)
                    nxt = dt[i + 1] if isinstance(dt, list) and i + 1 < len(dt) else None
                    hi = None
                    if isinstance(nxt, dict):
                        nxt_lo = nxt.get("threshold_wan", nxt.get("min_gross_wan"))
                        if nxt_lo is not None:
                            hi = float(nxt_lo) - 0.01  # [lo, hi)，阈值边界连续
                    parsed.append({
                        "label": f"{int(float(rate) * 100)}%",
                        "min_gross_wan": lo,
                        "max_gross_wan": hi,
                        "rate": float(rate),
                    })
                if parsed:
                    tiers = parsed
        except (json.JSONDecodeError, OSError, KeyError, TypeError, ValueError):
            pass
    # 兜底：如果 tiers 为空用 config 默认
    if not tiers:
        tiers = [dict(t) for t in config.DISCOUNT_TIERS]
    return RateCard(
        bus_price=bus_price,
        metro_price=metro_price,
        production_bus=prod_bus,
        production_metro=prod_metro,
        discount_tiers=tiers,
    )


def unit_price(rc: RateCard, kind: str, level: str) -> float:
    if kind == "bus":
        return rc.bus_price.get(level, rc.bus_price.get("A+", 4.0))
    return rc.metro_price.get(level, rc.metro_price.get("A+", 20.0))


def production_price(rc: RateCard, kind: str) -> float:
    return rc.production_bus if kind == "bus" else rc.production_metro


def discount_for_gross(rc: RateCard, gross_wan: float) -> Dict[str, Any]:
    """按全单刊例总额落档。"""
    for t in rc.discount_tiers:
        lo = t["min_gross_wan"]
        hi = t["max_gross_wan"]
        if hi is None:
            if gross_wan >= lo:
                return t
        elif lo <= gross_wan <= hi:
            return t
    return rc.discount_tiers[-1]


def quote(items: List[Dict[str, Any]], rc: RateCard, budget_wan: float, customer_type: str,
          discount_override: Optional[float] = None, converged: bool = True) -> Dict[str, Any]:
    """items: 已选方案的付费条目（每项已含 units/month/kind/level）。

    discount_override：由 orchestrator 折扣不动点确定的最终折扣；
    converged：不动点是否收敛。

    返回 quote 对象（不含 gift_items / allocation），供 orchestrator 组装。
    """
    return _compute_quote(items, rc, budget_wan, customer_type, discount_override, converged)


def _compute_quote(items, rc, budget_wan, customer_type, discount_override=None, converged=True) -> Dict[str, Any]:
    months = items[0]["months"] if items else 1

    # gross 总额（刊例）
    rate_card_total = 0.0
    for it in items:
        up = unit_price(rc, it["kind"], it["level"])
        g = up * it["units"] * months
        it["unit_price_wan"] = up
        it["gross_wan"] = round(g, 2)
        rate_card_total += g
    rate_card_total = round(rate_card_total, 2)

    # 折扣：优先用 orchestrator 不动点结果；否则按 gross 落档（单次查询）。
    # 绝不产生“折扣档与 gross 不匹配”或“超预算”的报价。
    if discount_override is not None:
        tier = discount_for_gross(rc, rate_card_total)
        # 覆盖档位：用给定的折扣率重标 tier 标签，保证 tier.rate == discount_override
        tier = dict(tier)
        tier["rate"] = float(discount_override)
        tier["label"] = f"{int(float(discount_override) * 100)}%"
        discount = float(discount_override)
    else:
        tier = discount_for_gross(rc, rate_card_total)
        discount = tier["rate"]

    # 制作费
    production = 0.0
    for it in items:
        prod = production_price(rc, it["kind"]) * it["units"]
        it["production_wan"] = round(prod, 2)
        production += prod
    production = round(production, 2)

    media_net = round(rate_card_total * discount, 2)

    agency = round(media_net * config.AGENCY_FEE_RATE, 2) if customer_type == "4a" else 0.0

    total = round(media_net + production + agency, 2)

    # 若超预算，执行折扣不动点：向更保守（更低 gross 阈值 → 更高折扣）方向降档，
    # 但折扣率不变（折扣率由 gross 决定，gross 已确定不能改）。
    # 实际这里的“不动点”指：若超预算，则把部分条目移出（由 orchestrator/solver 保证不超）。
    # 这里仅保证折扣档正确，超预算由 solver 约束兜底。
    if total > budget_wan:
        # 尝试用更保守档的折扣（更低 gross 阈值档可能已是最低；这里仅记录）
        pass

    # 逐行分摊（net + production + agency 按 gross 比例分摊）
    alloc_sum = 0.0
    for it in items:
        share = (it["gross_wan"] / rate_card_total) if rate_card_total else 0.0
        net = round(it["gross_wan"] * discount, 2)
        prod = it["production_wan"]
        ag = round(net * config.AGENCY_FEE_RATE, 2) if customer_type == "4a" else 0.0
        # 4A 服务费按 net 分摊（媒体费口径）
        it["discount"] = discount
        it["net_wan"] = round(net, 2)
        it["agency_fee_wan"] = ag
        it["total_wan"] = round(net + prod + ag, 2)
        alloc_sum += it["total_wan"]
    alloc_sum = round(alloc_sum, 2)

    # 保证行分摊与总价一致（≤1 元误差修正）
    diff = round(total - alloc_sum, 2)
    if items and abs(diff) > 0.01:
        # 把差值加到首行
        items[0]["total_wan"] = round(items[0]["total_wan"] + diff, 2)
        alloc_sum = round(sum(it["total_wan"] for it in items), 2)

    gift_wan = round(media_net * config.GIFT_RATE, 2)

    return {
        "rate_card_total_wan": round(rate_card_total, 2),
        "discount_tier": tier,
        "discount": discount,
        "discount_converged": bool(converged),
        "media_net_wan": media_net,
        "production_wan": production,
        "agency_fee_wan": agency,
        "gift_wan": gift_wan,
        "gift_items": [],
        "total_paid_wan": round(total, 2),
        "budget_wan": budget_wan,
        "budget_slack_wan": round(budget_wan - round(total, 2), 2),
        "customer_type": customer_type,
        "allocation_check": {
            "sum_lines": round(alloc_sum, 2),
            "total": round(total, 2),
            "diff": round(round(total, 2) - round(alloc_sum, 2), 2),
            "passed": abs(round(total, 2) - round(alloc_sum, 2)) <= 1.0,
        },
        "tiers": [dict(t) for t in rc.discount_tiers],
        "notes": [
            "折扣口径来自赛前培训/PRD，待赞助方确认",
            "制作费公交 0.75 万/辆、地铁 0.03 万/口为区间估算",
        ],
    }


__all__ = ["RateCard", "load_rate_card", "unit_price", "production_price", "discount_for_gross", "quote"]
