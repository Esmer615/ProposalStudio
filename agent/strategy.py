# -*- coding: utf-8 -*-
"""场景设计：Agent 的「想」这一步。

注意：当前引擎（engine/orchestrator.py）只有一个确定性优化器，没有
precision/balanced/reach/corridor 四个策略参数。因此 Agent 不假装切换策略，
而是沿引擎真正支持的轴做场景对比：

    预算 / 媒体组合 / 档期 / 周数 / 客户类型 / 锁定

「精准 vs 覆盖」是分析视角，不是引擎参数；它通过 objective 影响场景选择与
评分权重，并在话术里显式说明。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .contracts import BriefState
from .intake import request_signature

DEFAULT_LABELS = {
    "base": "基准方案",
    "budget_down": "预算下探",
    "budget_up": "预算上探",
    "knee": "弹性拐点",
    "media_bus": "公交-only 参考",
    "media_metro": "地铁-only 参考",
    "media_both": "公交+地铁 参考",
}

OBJECTIVE_LABELS = {
    "balanced": "均衡",
    "reach": "覆盖/曝光",
    "precision": "精准触达",
    "efficiency": "预算效率",
    "brand": "品牌认知",
}


class ScenarioPlanner:
    def __init__(self, policy: Optional[Dict[str, Any]] = None) -> None:
        self.policy = dict(policy or {})

    def design(
        self,
        brief: BriefState,
        catalog: Dict[str, Any],
        options: Dict[str, Any],
        elasticity: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        base = dict(brief.request)
        budget = float(base.get("budget_wan") or 200)
        media = [str(x) for x in (base.get("media") or [])]
        objective = brief.objective or "balanced"
        max_scenarios = int(options.get("max_scenarios", 4))
        if options.get("mode") == "quick":
            max_scenarios = 1

        budget_range = catalog.get("budget_range", {})
        floor = float(self.policy.get("budget_floor_wan", budget_range.get("min_wan", 100)))
        ceiling = float(self.policy.get("budget_ceiling_wan", budget_range.get("max_wan", 500)))
        step = float(self.policy.get("budget_step_wan", 100))
        labels = {**DEFAULT_LABELS, **(self.policy.get("labels") or {})}

        scenarios: List[Dict[str, Any]] = [{
            "id": "base",
            "label": labels["base"],
            "intent": "客户原始需求对应的方案，作为所有对比的基准。",
            "use_when": "客户原始预算与媒体组合不变时。",
            "role": "primary",
            "is_base": True,
            "request": dict(base),
        }]

        def add(
            sid: str,
            label: str,
            intent: str,
            request: Dict[str, Any],
            role: str = "sensitivity",
            use_when: str = "",
        ) -> None:
            req = dict(base)
            req.update(request)
            sig = request_signature(req)
            if sig == request_signature(base):
                return
            if any(request_signature(s["request"]) == sig for s in scenarios):
                return
            scenarios.append({
                "id": sid,
                "label": label,
                "intent": intent,
                "use_when": use_when,
                "role": role,
                "is_base": False,
                "request": req,
            })

        scenario_rules = self.policy.get("scenario_rules") or {}

        # ---- 媒体替代（先算出来，按 objective 决定先后） -------------------
        media_args: Optional[Dict[str, Any]] = None
        if len(media) > 1:
            alt = self._media_alternative(base.get("venue"), objective, catalog)
            if alt:
                media_args = {
                    "sid": f"media_{alt}",
                    "label": labels.get(f"media_{alt}", f"{alt}-only 参考"),
                    "intent": "只保留一种媒体，检验组合是否真的比单投更值。",
                    "use_when": (
                        "客户要更低的 CPM / 更广的社区覆盖时。"
                        if alt == "bus" else "客户要枢纽/地铁动线定点拦截时。"
                    ),
                    "request": {"media": [alt]},
                    "role": "reference",
                }
        elif len(media) == 1:
            other = [m for m in ("bus", "metro") if m not in media]
            if other:
                media_args = {
                    "sid": "media_both",
                    "label": labels["media_both"],
                    "intent": "补上另一种媒体，检验组合是否有额外增益。",
                    "use_when": "客户愿意增加媒体组合换覆盖时。",
                    "request": {"media": ["bus", "metro"]},
                    "role": "reference",
                }
        early_for = set(scenario_rules.get("media_early_for") or ["precision", "brand"])
        early_media = media_args is not None and objective in early_for
        if early_media:
            add(
                media_args["sid"], media_args["label"], media_args["intent"],
                media_args["request"], role="reference", use_when=media_args["use_when"],
            )

        # ---- 预算轴 --------------------------------------------------------
        down = max(floor, budget - step)
        up = min(ceiling, budget + step)
        knee = _knee_budget(elasticity)

        budget_plan: List[tuple] = []
        order = (scenario_rules.get("objective_order") or {}).get(
            objective,
            ["budget_down", "budget_up", "knee"],
        )
        intents = {
            "budget_down": "少花一档预算，看覆盖与效率的取舍；回答“这单必须花满吗”。",
            "budget_up": "多花一档预算，检查覆盖增量与边际效率。",
            "knee": "预算弹性拐点：判断“再加钱值不值”。",
        }
        use_when_map = {
            "budget_down": "客户砍预算，或想确认最低可行预算时。",
            "budget_up": "客户要更大覆盖/曝光，且预算可加时。",
            "knee": "客户问“再加钱值不值”时。",
        }
        available = {
            "budget_down": down if down < budget else None,
            "budget_up": up if up > budget else None,
            "knee": knee if (knee and floor <= knee <= ceiling and abs(knee - budget) > 1e-9) else None,
        }
        for key in order:
            bgt = available.get(key)
            if bgt is None:
                continue
            budget_plan.append((key, labels.get(key, key), intents.get(key, ""), bgt, use_when_map.get(key, "")))

        for sid, label, intent, bgt, use_when in budget_plan:
            add(sid, label, intent, {"budget_wan": float(bgt)}, use_when=use_when)

        # ---- 媒体轴（precision/brand 已提前加过） -------------------------
        if media_args is not None and not early_media:
            add(
                media_args["sid"], media_args["label"], media_args["intent"],
                media_args["request"], role=media_args["role"], use_when=media_args["use_when"],
            )

        # ---- 截断：base 永远保留 ------------------------------------------
        if len(scenarios) > max_scenarios:
            scenarios = [scenarios[0]] + scenarios[1:max_scenarios]
        return scenarios

    def _media_alternative(self, venue: str, objective: str, catalog: Dict[str, Any]) -> Optional[str]:
        profile = (catalog.get("venue_profiles") or {}).get(venue) or {}
        metro_direct = bool(profile.get("metro_direct"))
        default_alt = str(self.policy.get("media_alternative_default", "bus"))
        if not metro_direct:
            # 无地铁直达的乐园，地铁只能做家庭出发枢纽；单投地铁通常不如公交广度稳。
            return "bus"
        if objective in ("precision", "brand"):
            return "metro"
        return default_alt

    def describe(self, scenarios: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return [
            {
                "id": s["id"],
                "label": s["label"],
                "intent": s["intent"],
                "use_when": s.get("use_when", ""),
                "role": s["role"],
                "request": dict(s["request"]),
            }
            for s in scenarios
        ]


def _knee_budget(elasticity: Optional[Dict[str, Any]]) -> Optional[float]:
    if not isinstance(elasticity, dict):
        return None
    try:
        knee = elasticity.get("knee_budget_wan")
        return float(knee) if knee is not None else None
    except (TypeError, ValueError):
        return None


def objective_label(objective: str, policy: Optional[Dict[str, Any]] = None) -> str:
    labels = {**OBJECTIVE_LABELS, **((policy or {}).get("objective_labels") or {})}
    return labels.get(objective, objective)


__all__ = ["ScenarioPlanner", "objective_label", "OBJECTIVE_LABELS"]
