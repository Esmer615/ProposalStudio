# -*- coding: utf-8 -*-
"""Agent 编排：一个有边界的「计划-执行-校验-解释」状态机。

为什么不是自由 ReAct：
- 报价/库存/曝光必须可复算，不能让模型决定算什么；
- 现场演示要求同样输入得到同样结果；
- 但“接需求、判断缺什么、设计哪几个场景、怎么说”确实需要判断，
  所以用技能驱动的有界状态机，把判断留在 Agent，把算术锁在引擎。
"""
from __future__ import annotations

import os
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from .analyzer import (
    build_scenario_record,
    comparison_rows,
    cross_scenario_notes,
    recommend,
    score_scenarios,
    summarize_elasticity,
)
from .contracts import (
    AGENT_NAME,
    AGENT_VERSION,
    SCHEMA_VERSION,
    STATUS_ERROR,
    STATUS_NEEDS_CLARIFICATION,
    STATUS_READY,
    BriefState,
    error_payload,
    normalize_options,
)
from .intake import resolve_brief
from .llm import NullLLM, build_llm
from .narrator import build_narrative
from .skills import SkillRegistry, load_default_registry
from .strategy import ScenarioPlanner, objective_label
from .tools import ToolRuntime

SKILL_STAGES = ("intake", "strategy", "analysis", "narrative")


class ProposalAgent:
    def __init__(
        self,
        skills_root: Optional[str] = None,
        llm: Any = None,
        tools: Optional[ToolRuntime] = None,
    ) -> None:
        self.registry = SkillRegistry(skills_root) if skills_root else load_default_registry()
        self.llm = llm if llm is not None else build_llm(os.environ.get("AGENT_LLM", "auto"))
        self.tools = tools or ToolRuntime()

    # ------------------------------------------------------------------ #
    def run(self, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        t0 = time.perf_counter()
        payload = dict(payload or {})
        options = normalize_options(payload.get("options") or payload.get("agent_options"))
        active_llm = self.llm if options.get("llm") != "off" else NullLLM("LLM 已关闭")

        raw_text, structured = _split_input(payload)
        skill_runs: List[Dict[str, Any]] = []
        started_at = datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00")

        try:
            skills = self.registry.ordered()
            skill_errors = self.registry.validate()
            skill_run = {
                "skills": [{"name": s.name, "stage": s.stage, "version": s.version, "sha256": s.sha256} for s in skills],
                "validation_errors": skill_errors,
            }
            if skill_errors:
                return self._error_result(
                    "技能校验失败：" + "；".join(skill_errors),
                    started_at,
                    t0,
                    code="SKILL_VALIDATION_ERROR",
                    skill_runs=[{"stage": "skills", "status": "failed", "ms": 0, "summary": "；".join(skill_errors)}],
                )
        except Exception as exc:
            return self._error_result(
                f"技能加载失败：{type(exc).__name__}: {exc}",
                started_at,
                t0,
                code="SKILL_LOAD_ERROR",
                skill_runs=skill_runs,
            )

        try:
            catalog = self.tools.catalog()
            narrative_policy = self.registry.policy("narrative")
            analysis_policy = self.registry.policy("analysis")
            strategy_policy = self.registry.policy("strategy")
            intake_policy = self.registry.policy("intake")

            # ---- 1. 接需求 -------------------------------------------------
            ts = time.perf_counter()
            brief = resolve_brief(
                raw_text,
                structured,
                catalog,
                options,
                llm=active_llm,
                compliance_policy=narrative_policy,
                intake_policy=intake_policy,
            )
            skill_runs.append(self._skill_run("intake", ts, status=brief.status, summary=brief.summary))

            if brief.status == STATUS_NEEDS_CLARIFICATION:
                result = self._clarification_result(
                    brief, options, catalog, skill_runs, active_llm, narrative_policy, started_at, t0,
                )
                return result

            # ---- 2. 基准方案 -----------------------------------------------
            ts = time.perf_counter()
            base_result = self.tools.run_plan(brief.request)
            if not base_result.get("ok"):
                result = self._engine_error_result(
                    brief, base_result, options, catalog, skill_runs, active_llm,
                    narrative_policy, started_at, t0,
                )
                return result
            skill_runs.append(self._skill_run("strategy", ts, status="done", summary="生成基准方案"))

            # ---- 3. 预算弹性（用于场景设计 & 拐点判断） --------------------
            elasticity_result: Dict[str, Any] = {"ok": False, "error": {"message": "未计算"}}
            if options.get("include_elasticity"):
                ts = time.perf_counter()
                elasticity_result = self.tools.run_elasticity(brief.request)
                skill_runs.append(self._skill_run(
                    "analysis", ts,
                    status="done" if elasticity_result.get("ok") else "degraded",
                    summary="预算弹性" if elasticity_result.get("ok") else "弹性计算失败，继续单方案分析",
                ))
                if not elasticity_result.get("ok"):
                    elasticity_result = {"ok": False, "error": elasticity_result.get("error")}

            elasticity_data = elasticity_result.get("elasticity") if elasticity_result.get("ok") else None

            # ---- 4. 设计并执行对比场景 -------------------------------------
            ts = time.perf_counter()
            planner = ScenarioPlanner(strategy_policy)
            planned = planner.design(brief, catalog, options, elasticity_data)
            skill_runs.append(self._skill_run(
                "strategy", ts, status="done",
                summary=f"设计 {len(planned)} 个场景：" + "、".join(s["label"] for s in planned),
            ))

            records: List[Dict[str, Any]] = []
            raw_plans: Dict[str, Any] = {}
            for scenario in planned:
                ts = time.perf_counter()
                if scenario.get("is_base"):
                    result = base_result
                else:
                    result = self.tools.run_plan(scenario["request"])
                record = build_scenario_record(
                    scenario, result, catalog, brief,
                    risk_policy=analysis_policy,
                )
                record["duration_ms"] = int((time.perf_counter() - ts) * 1000)
                records.append(record)
                if result.get("ok"):
                    raw_plans[scenario["id"]] = result.get("plan")

            # ---- 5. 比较 / 评分 / 推荐 ------------------------------------
            ts = time.perf_counter()
            cross_scenario_notes(records)
            score_scenarios(records, brief.objective, analysis_policy)
            recommendation = recommend(records, brief, analysis_policy)
            base_metrics = next((r.get("metrics") for r in records if r.get("is_base") and r.get("ok")), None) or {}
            elasticity_summary = summarize_elasticity(
                elasticity_data,
                float(brief.request.get("budget_wan") or 0),
                float((base_metrics.get("reach_cap") or 0.82)),
            )
            comparison = comparison_rows(records)
            skill_runs.append(self._skill_run(
                "analysis", ts, status="done",
                summary=f"比较 {len(records)} 个场景；primary={recommendation.get('primary_scenario')}",
            ))

            primary = next((r for r in records if r.get("id") == recommendation.get("primary_scenario")), None)
            if primary is None:
                primary = next((r for r in records if r.get("ok")), records[0] if records else None)
            if primary is None or not primary.get("ok"):
                return self._error_result(
                    "所有场景均未成功生成方案。",
                    started_at, t0, code="NO_FEASIBLE_SCENARIO", skill_runs=skill_runs,
                )

            analysis = _assemble_analysis(
                brief=brief,
                records=records,
                primary=primary,
                recommendation=recommendation,
                comparison=comparison,
                elasticity=elasticity_summary,
                objective_policy=strategy_policy,
                analysis_policy=analysis_policy,
                catalog=catalog,
            )

            # ---- 6. 话术 + 守卫 -------------------------------------------
            ts = time.perf_counter()
            narrative_payload = {
                "status": brief.status,
                "headline": analysis.get("headline"),
                "meta": analysis.get("meta"),
                "primary": primary,
                "recommendation": recommendation,
                "comparison": comparison,
                "elasticity": elasticity_summary,
                "objective_label": analysis.get("objective_label"),
            }
            narrative = build_narrative(
                narrative_payload,
                brief=brief,
                llm=active_llm,
                policy=narrative_policy,
            )
            skill_runs.append(self._skill_run(
                "narrative", ts, status="done",
                summary=f"话术模式={narrative.get('mode')}；数字守卫={'通过' if narrative.get('number_guard', {}).get('ok') else '拒绝'}",
            ))

            total_ms = int((time.perf_counter() - t0) * 1000)
            result: Dict[str, Any] = {
                "agent": _agent_meta(active_llm, options, skills, total_ms, started_at),
                "schema_version": SCHEMA_VERSION,
                "status": brief.status if brief.status != STATUS_NEEDS_CLARIFICATION else STATUS_READY,
                "brief": brief.to_dict(),
                "analysis": analysis,
                "scenarios": _compact_scenarios(records),
                "recommendation": recommendation,
                "narrative": narrative,
                "skills": {
                    "manifest": skill_run,
                    "runs": skill_runs,
                },
                "guardrails": _guardrails(skills),
                "tool_calls": list(self.tools.calls),
                "meta": _result_meta(
                    catalog, total_ms, started_at, options, active_llm,
                    engine_meta=(analysis.get("meta") or {}),
                ),
            }
            if options.get("include_plan_artifacts"):
                result["artifacts"] = {"plans": raw_plans}
            return result
        except Exception as exc:  # pragma: no cover - 顶层保护，避免 API 500
            return self._error_result(
                f"{type(exc).__name__}: {exc}",
                started_at,
                t0,
                code="AGENT_ERROR",
                skill_runs=skill_runs,
                debug=os.environ.get("AGENT_DEBUG") == "1",
            )

    # ------------------------------------------------------------------ #
    def _clarification_result(
        self,
        brief: BriefState,
        options: Dict[str, Any],
        catalog: Dict[str, Any],
        skill_runs: List[Dict[str, Any]],
        llm: Any,
        narrative_policy: Dict[str, Any],
        started_at: str,
        t0: float,
    ) -> Dict[str, Any]:
        narrative = build_narrative(
            {"status": STATUS_NEEDS_CLARIFICATION, "headline": "需要补充信息后才能分析"},
            brief=brief,
            llm=None,
            policy=narrative_policy,
        )
        skill_runs.append(self._skill_run("narrative", time.perf_counter(), status="done", summary="输出澄清问题"))
        total_ms = int((time.perf_counter() - t0) * 1000)
        return {
            "agent": _agent_meta(llm, options, self.registry.ordered(), total_ms, started_at),
            "schema_version": SCHEMA_VERSION,
            "status": STATUS_NEEDS_CLARIFICATION,
            "brief": brief.to_dict(),
            "analysis": None,
            "scenarios": [],
            "recommendation": None,
            "narrative": narrative,
            "skills": {"manifest": {"skills": [s.to_dict() for s in self.registry.ordered()]}, "runs": skill_runs},
            "guardrails": _guardrails(self.registry.ordered()),
            "tool_calls": list(self.tools.calls),
            "meta": _result_meta(catalog, total_ms, started_at, options, llm),
        }

    def _engine_error_result(
        self,
        brief: BriefState,
        base_result: Dict[str, Any],
        options: Dict[str, Any],
        catalog: Dict[str, Any],
        skill_runs: List[Dict[str, Any]],
        llm: Any,
        narrative_policy: Dict[str, Any],
        started_at: str,
        t0: float,
    ) -> Dict[str, Any]:
        err = base_result.get("error") or {}
        suggestions = err.get("suggestions") or ["检查预算/媒介/档期", "尝试放宽锁定条件", "更换场馆或媒体组合"]
        brief.questions = [{
            "id": "Q1",
            "field": err.get("field") or "request",
            "question": f"引擎无法生成方案：{err.get('message') or '未知错误'}。请调整输入。",
            "why": "报价与库存约束必须由引擎确认，Agent 不会绕过。",
            "options": suggestions,
            "default": None,
            "blocking": True,
        }]
        skill_runs.append(self._skill_run("analysis", time.perf_counter(), status="failed", summary=str(err.get("code"))))
        total_ms = int((time.perf_counter() - t0) * 1000)
        narrative = build_narrative(
            {"status": STATUS_NEEDS_CLARIFICATION, "headline": "引擎无法生成方案"},
            brief=brief,
            llm=None,
            policy=narrative_policy,
        )
        return {
            "agent": _agent_meta(llm, options, self.registry.ordered(), total_ms, started_at),
            "schema_version": SCHEMA_VERSION,
            "status": STATUS_ERROR,
            "brief": brief.to_dict(),
            "analysis": None,
            "scenarios": [],
            "recommendation": None,
            "error": err or error_payload("ENGINE_ERROR", "引擎无法生成方案"),
            "narrative": narrative,
            "skills": {"manifest": {"skills": [s.to_dict() for s in self.registry.ordered()]}, "runs": skill_runs},
            "guardrails": _guardrails(self.registry.ordered()),
            "tool_calls": list(self.tools.calls),
            "meta": _result_meta(catalog, total_ms, started_at, options, llm),
        }

    def _error_result(
        self,
        message: str,
        started_at: str,
        t0: float,
        *,
        code: str,
        skill_runs: Optional[List[Dict[str, Any]]] = None,
        debug: bool = False,
    ) -> Dict[str, Any]:
        total_ms = int((time.perf_counter() - t0) * 1000)
        return {
            "agent": {
                "name": AGENT_NAME,
                "version": AGENT_VERSION,
                "mode": "offline-rules",
            },
            "schema_version": SCHEMA_VERSION,
            "status": STATUS_ERROR,
            "brief": None,
            "analysis": None,
            "scenarios": [],
            "recommendation": None,
            "error": error_payload(code, message),
            "narrative": {
                "mode": "rules",
                "headline": "Agent 执行失败",
                "markdown": f"# Agent 执行失败\n\n{message}\n",
                "number_guard": {"ok": True, "unknown": []},
                "llm_used": False,
            },
            "skills": {"manifest": {}, "runs": skill_runs or []},
            "guardrails": [],
            "tool_calls": list(self.tools.calls),
            "meta": {"generated_at": started_at, "total_ms": total_ms},
            **({"debug": {"error": message}} if debug else {}),
        }

    @staticmethod
    def _skill_run(stage: str, t0: float, *, status: str, summary: str) -> Dict[str, Any]:
        return {
            "stage": stage,
            "status": status,
            "ms": int((time.perf_counter() - t0) * 1000),
            "summary": summary,
        }


# --------------------------------------------------------------------------- #
# 辅助
# --------------------------------------------------------------------------- #
def _split_input(payload: Dict[str, Any]):
    raw_text = payload.get("brief_text") or payload.get("brief") or payload.get("customer_brief") or ""
    structured = payload.get("request") or payload.get("plan_request") or {}
    if not structured:
        # 允许直接把 PlanRequest 字段放在顶层
        structured = {k: payload[k] for k in (
            "venue", "budget_wan", "media", "start_date", "weeks",
            "customer_type", "industry", "locks", "brief_text", "objective",
        ) if k in payload}
    return str(raw_text or ""), dict(structured or {})


def _assemble_analysis(
    *,
    brief: BriefState,
    records: List[Dict[str, Any]],
    primary: Dict[str, Any],
    recommendation: Dict[str, Any],
    comparison: List[Dict[str, Any]],
    elasticity: Dict[str, Any],
    objective_policy: Dict[str, Any],
    analysis_policy: Dict[str, Any],
    catalog: Dict[str, Any],
) -> Dict[str, Any]:
    m = primary.get("metrics") or {}
    val = m.get("validation") or {}
    profile = ((catalog.get("venue_profiles") or {}).get(brief.request.get("venue")) or {})
    absorption_floor = float(((analysis_policy or {}).get("thresholds") or {}).get("absorption_floor", 0.85))
    headline = (
        f"{_venue_name(brief.request.get('venue'))} · {m.get('budget_wan')} 万 · "
        f"{brief.request.get('weeks')} 周：建议「{recommendation.get('primary_label') or primary.get('label')}」；"
        f"预算使用率 {_pct(m.get('utilization'))}，目标 Reach {m.get('reach_pct_label')}（模型估算）"
    )
    feasibility = {
        "status": "ok" if val.get("passed") and m.get("utilization", 0) >= absorption_floor else
                  ("partial" if val.get("passed") else "blocked"),
        "validation_passed": bool(val.get("passed")),
        "blockers": val.get("blockers") or [],
        "warnings": val.get("warnings") or [],
        "absorption": m.get("absorption_status"),
        "absorption_floor": absorption_floor,
        "utilization": m.get("utilization"),
        "budget_slack_wan": m.get("budget_slack_wan"),
    }
    audience = {
        "definition": "场馆档案目标人群口径（策划假设，非实测去重）",
        "target_population": m.get("target_population"),
        "reach_people": m.get("reach_people"),
        "reach_pct": m.get("reach_pct"),
        "notes": brief.audience_notes,
        "strategy": (m.get("strategy") or {}).get("audience"),
        "age_band_note": "当前未接可视化平台实测人流；年龄细分不可用，提案不声称更细粒度。",
    }
    key_numbers = {
        "budget_wan": m.get("budget_wan"),
        "total_paid_wan": m.get("total_paid_wan"),
        "utilization": m.get("utilization"),
        "budget_slack_wan": m.get("budget_slack_wan"),
        "impressions": m.get("impressions"),
        "reach_pct": m.get("reach_pct"),
        "reach_people": m.get("reach_people"),
        "frequency": m.get("frequency"),
        "cpm_yuan": m.get("cpm_yuan"),
        "poi_hits": m.get("poi_hits"),
        "bus_units": m.get("bus_units"),
        "metro_units": m.get("metro_units"),
        "media_mix_cost": m.get("media_mix_cost"),
        "discount_label": m.get("discount_label"),
        "gift_wan": m.get("gift_wan"),
    }
    return {
        "headline": headline,
        "verdict": recommendation.get("verdict"),
        "objective": brief.objective,
        "objective_label": objective_label(brief.objective, objective_policy),
        "objective_note": "当前引擎只有一个确定性优化器；“精准/覆盖”是分析视角，不是引擎策略参数。",
        "audience": audience,
        "key_numbers": key_numbers,
        "feasibility": feasibility,
        "primary_scenario": primary.get("id"),
        "primary_label": primary.get("label"),
        "primary_metrics": m,
        "primary_risks": primary.get("risks") or [],
        "comparison": comparison,
        "elasticity": elasticity,
        "data_quality": m.get("data_quality"),
        "hypothesis": primary.get("hypothesis"),
        "explanations": primary.get("explanations"),
        "compliance": {
            "brief_flags": brief.compliance_flags,
            "venue_notes": profile.get("compliance_notes") or [],
            "required_phrasing": "学校周边 300–500 米；不投校内。",
        },
        "meta": m.get("meta"),
        "venue_profile": {
            "metro_direct": profile.get("metro_direct"),
            "self_drive_share": profile.get("self_drive_share"),
            "target_population": profile.get("target_population"),
            "source": profile.get("source"),
        },
    }


def _compact_scenarios(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for r in records:
        if not r.get("ok"):
            out.append({
                "id": r.get("id"),
                "label": r.get("label"),
                "intent": r.get("intent"),
                "use_when": r.get("use_when"),
                "role": r.get("role"),
                "is_base": r.get("is_base"),
                "ok": False,
                "error": r.get("error"),
            })
            continue
        m = r.get("metrics") or {}
        out.append({
            "id": r.get("id"),
            "label": r.get("label"),
            "intent": r.get("intent"),
            "use_when": r.get("use_when"),
            "role": r.get("role"),
            "is_base": r.get("is_base"),
            "ok": True,
            "duration_ms": r.get("duration_ms"),
            "request": r.get("request"),
            "metrics": {
                "budget_wan": m.get("budget_wan"),
                "total_paid_wan": m.get("total_paid_wan"),
                "utilization": m.get("utilization"),
                "budget_slack_wan": m.get("budget_slack_wan"),
                "absorption_status": m.get("absorption_status"),
                "impressions": m.get("impressions"),
                "reach_pct": m.get("reach_pct"),
                "reach_pct_label": m.get("reach_pct_label"),
                "reach_people": m.get("reach_people"),
                "frequency": m.get("frequency"),
                "cpm_yuan": m.get("cpm_yuan"),
                "poi_hits": m.get("poi_hits"),
                "bus_units": m.get("bus_units"),
                "metro_units": m.get("metro_units"),
                "media_mix_impressions": m.get("media_mix_impressions"),
                "media_mix_cost": m.get("media_mix_cost"),
                "discount_label": m.get("discount_label"),
                "validation": {
                    "passed": (m.get("validation") or {}).get("passed"),
                    "blockers": (m.get("validation") or {}).get("blockers"),
                    "warnings": (m.get("validation") or {}).get("warnings"),
                },
                "data_quality": m.get("data_quality"),
            },
            "score": r.get("score"),
            "highlights": r.get("highlights"),
            "tradeoffs": r.get("tradeoffs"),
            "risks": r.get("risks"),
            "top_picks": r.get("top_picks"),
        })
    return out


def _agent_meta(llm: Any, options: Dict[str, Any], skills: List[Any], total_ms: int, started_at: str) -> Dict[str, Any]:
    describe = llm.describe() if hasattr(llm, "describe") else {"available": False}
    return {
        "name": AGENT_NAME,
        "version": AGENT_VERSION,
        "mode": "llm-assisted" if describe.get("available") else "offline-rules",
        "llm": describe,
        "options": dict(options),
        "skill_count": len(skills),
        "generated_at": started_at,
        "total_ms": total_ms,
    }


def _result_meta(
    catalog: Dict[str, Any],
    total_ms: int,
    started_at: str,
    options: Dict[str, Any],
    llm: Any,
    *,
    engine_meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """优先用引擎本次响应里的数据版本，避免 manifest 与库存哈希两套版本号打架。"""
    inv = catalog.get("inventory") or {}
    em = engine_meta or {}
    return {
        "generated_at": started_at,
        "total_ms": total_ms,
        "data_version": em.get("data_version") or inv.get("data_version"),
        "inventory_periods": em.get("inventory_periods") or inv.get("periods"),
        "inventory_ts": em.get("inventory_ts") or inv.get("timestamp"),
        "options": dict(options),
        "llm": llm.describe() if hasattr(llm, "describe") else {"available": False},
        "engine": "engine.orchestrator.generate_plan",
        "deterministic": True,
    }


def _guardrails(skills: List[Any]) -> List[str]:
    base = [
        "LLM 不产出数字；所有数字来自 engine 或明确的派生公式。",
        "validator 独立于 solver；blocker 失败不得导出客户提案。",
        "预算未花完必须主动说明，不得假装花满。",
        "不承诺到园人数/销量/财务 ROI；不投校内。",
        "所有曝光/Reach/频次/CPM 标注“模型估算”口径。",
        "同输入引擎输出确定（meta 时间戳除外）。",
    ]
    for skill in skills:
        for g in skill.guardrails or []:
            if g not in base:
                base.append(g)
    return base


def _venue_name(venue: Any) -> str:
    from engine.models import VENUES
    return (VENUES.get(str(venue)) or {}).get("name", str(venue))


def _pct(v: Any) -> str:
    try:
        return f"{float(v):.1%}"
    except (TypeError, ValueError):
        return "—"


def analyze_brief(brief_text: str, **options: Any) -> Dict[str, Any]:
    """一行调用：给客户 brief，拿完整分析。"""
    return ProposalAgent().run({"brief_text": brief_text, "options": options})


__all__ = ["ProposalAgent", "analyze_brief", "SKILL_STAGES"]
