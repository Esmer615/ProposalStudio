# -*- coding: utf-8 -*-
"""端到端流水线演示：skill 加载 -> 求解 -> 效果估算 -> 方案 JSON

这条链路里没有任何一步由 LLM 计算数字。
LLM 的职责边界（未来接入时）只有一条：把 PM 的自然语言诉求翻译成 skill 字段，
且翻译结果必须通过 skill_loader 的 schema 校验才能进入流水线。
"""
from __future__ import annotations

import json
import os
import sys

from bus_optimizer import load_bus_ledger
from effects_model import marginal_efficiency
from skill_loader import SkillError, load_skill, skill_to_config
from bus_optimizer import solve

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.join(HERE, "skills")


def run(skill_path: str, budgets=(100, 200, 500)) -> dict:
    skill = load_skill(skill_path)
    cand = load_bus_ledger()

    out = {
        "skill": {k: v for k, v in skill.items() if not k.startswith("_")},
        "source": skill["_source"],
        "budget_variants": [],
    }

    for b in budgets:
        cfg, eff = skill_to_config(skill, budget=b)
        plan = solve(cand, cfg)
        if plan["status"] not in ("OPTIMAL", "FEASIBLE"):
            out["budget_variants"].append({"budget": b, "status": plan["status"]})
            continue

        from effects_model import estimate
        metrics = estimate(plan["plan"], eff)
        out["budget_variants"].append({
            "budget": b,
            "status": plan["status"],
            "line_count": plan["line_count"],
            "car_count": plan["car_count"],
            "cost": plan["cost"],
            "slack": plan["slack"],
            "high_share": plan["high_share"],
            "night_load": plan["night_load"],
            "solve_ms": plan["solve_ms"],
            "reach_pct": metrics["reach_pct"],
            "grp": metrics["grp"],
            "frequency": metrics["frequency"],
            "cpm_yuan": metrics["cpm_yuan"],
            "impressions": metrics["impressions"],
            "level_mix": plan["level_mix"],
            "region_mix": plan["region_mix"],
            "trim_priority": [m["line"] for m in marginal_efficiency(plan["plan"])[:5]],
            "plan": plan["plan"],
        })
    return out


if __name__ == "__main__":
    try:
        result = run(os.path.join(SKILL_DIR, "ban_insurance.md"))
    except SkillError as e:
        print("Skill 校验失败：", e, file=sys.stderr)
        sys.exit(2)

    print(f"skill = {result['skill']['industry']}  ({result['source']})")
    print(f"目标人群 {result['skill']['target_population']:,}  reach_k={result['skill']['reach_k']}")
    print(f"合规禁词 {result['skill']['compliance_forbidden']}\n")

    for v in result["budget_variants"]:
        print(f"[{v['budget']}万] 车{v['car_count']} 线{v['line_count']} 花费{v['cost']:.1f}万 "
              f"到达{v['reach_pct']} 频次{v['frequency']} CPM {v['cpm_yuan']}元 "
              f"求解{v['solve_ms']}ms 高等级{v['high_share']:.0%}")
        print(f"        等级配比 {v['level_mix']}  先砍: {v['trim_priority']}")

    os.makedirs(os.path.join(HERE, "out"), exist_ok=True)
    with open(os.path.join(HERE, "out", "pipeline_result.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    print("\n已写入 prototypes/out/pipeline_result.json")