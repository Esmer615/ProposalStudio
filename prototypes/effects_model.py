# -*- coding: utf-8 -*-
"""效果估算：确定性 Reach / Frequency 模型（不让 LLM 算数）

行业依据
--------
户外媒体测算通行做法（OOH 到达率建模）：
  1) 每辆车 = 一个"接触机会"载体，日曝光 = 日均客流 × 可视率
  2) 把全部投放折算成 GRP（总接触人次 / 目标人群）
  3) GRP → 到达率用饱和函数（指数/负二项近似）：
        Reach = 1 - exp(-GRP / a)
     或等价的  Reach = 1 - (1 + GRP/a)^(-a)   （Beta-Binomial 近似）
  4) 频次 = GRP / Reach

为什么用饱和函数而不是线性叠加：
  同一批人会被多条线路重复触达，线性相加会系统性高估到达率。

参数 a 的含义：a 越大，达到同样到达率需要的 GRP 越多（人群越分散/流动性越低）。
  a 由行业 skill 提供，默认 2.5。
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

# 单车日均客流（人次）——线路等级经验值
# 真实实现应替换为可视化平台"区域人流/媒体查询"导出的线路级数据
DAILY_RIDERS = {"S": 58000, "A++": 48000, "A+": 38000, "AA": 40000, "unknown": 35000}

# 车身上刊可视率：车身三面长期暴露，取行业常用的 0.55-0.65 中值
VIEW_RATE = 0.60


@dataclass
class ReachConfig:
    """效果模型参数（PM skill 可覆写）"""

    days: int = 30                      # 投放天数
    view_rate: float = VIEW_RATE        # 可视率
    target_population: float = 8_000_000  # 上海目标人群基数（默认全上海常住）
    reach_cap: float = 0.85             # 物理媒体到达率上限（再高的数字不可信）
    k: float = 250.0                    # 饱和常数：达到 cap 一半所需 GRP 的量级


def estimate(plan: list, cfg: Optional[ReachConfig] = None) -> dict:
    """输入 solve() 返回的 plan，输出可写进 HTML 的确定性指标"""
    cfg = cfg or ReachConfig()
    if not plan:
        return {"grp": 0.0, "reach": 0.0, "frequency": 0.0, "impressions": 0}

    impressions = 0.0
    by_line = []
    for p in plan:
        riders = DAILY_RIDERS.get(p["level"], DAILY_RIDERS["unknown"])
        imp = riders * cfg.view_rate * cfg.days * p["cars"]
        impressions += imp
        by_line.append({
            "line": p["line"],
            "level": p["level"],
            "cars": p["cars"],
            "daily_riders": riders,
            "impressions": round(imp),
        })

    grp = impressions / cfg.target_population * 100.0
    # 饱和曲线：Reach 随 GRP 增长但被 reach_cap 封顶，不会出现 100% 这种不可信数字
    reach = cfg.reach_cap * (1.0 - math.exp(-grp / cfg.k))
    frequency = (grp / 100.0) / reach if reach > 1e-9 else 0.0

    cost_yuan = sum(p["subtotal"] for p in plan) * 10000.0   # 万元 -> 元
    cpm = cost_yuan / impressions * 1000.0 if impressions else 0.0

    return {
        "impressions": round(impressions),
        "grp": round(grp, 1),
        "reach": round(reach, 4),
        "reach_pct": f"{reach:.1%}",
        "frequency": round(frequency, 2),
        "cpm_yuan": round(cpm, 2),
        "target_population": cfg.target_population,
        "parameters": {"reach_cap": cfg.reach_cap, "k": cfg.k,
                       "view_rate": cfg.view_rate, "days": cfg.days},
        "formula": "Reach = reach_cap * (1 - exp(-GRP/k)); Frequency = (GRP/100)/Reach",
        "by_line": sorted(by_line, key=lambda r: -r["impressions"]),
    }


def marginal_efficiency(plan: list, cfg: Optional[ReachConfig] = None) -> list:
    """每条线路的千次曝光成本，用于回答"砍预算先砍谁"

    注意：若只按等级定价与估算客流，同等级线路的千次曝光成本会完全相同。
    要真正区分优先级，必须引入"是否命中目标人群"（门店/地标覆盖度），
    这是 metrics 层的职责，见 docs/模型选型与Agent工作流方案.md 第五节。
    """
    cfg = cfg or ReachConfig()
    rows = []
    for p in plan:
        riders = DAILY_RIDERS.get(p["level"], DAILY_RIDERS["unknown"])
        imp = riders * cfg.view_rate * cfg.days * p["cars"]
        cost_yuan = p["subtotal"] * 10000.0
        rows.append({
            "line": p["line"],
            "level": p["level"],
            "cars": p["cars"],
            "cost_wan": round(p["subtotal"], 2),
            "impressions": round(imp),
            "cost_per_1k_impressions": round(cost_yuan / imp * 1000.0, 2) if imp else None,
        })
    return sorted(rows, key=lambda r: -(r["cost_per_1k_impressions"] or 0))


__all__ = ["ReachConfig", "estimate", "marginal_efficiency", "DAILY_RIDERS"]