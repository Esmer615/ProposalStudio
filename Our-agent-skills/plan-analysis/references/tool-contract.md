# 工具契约（plan-analysis 参考）

## Agent 内部工具

实现在 `agent/tools.py` 的 `ToolRuntime`：

```python
runtime.catalog() -> dict
runtime.run_plan(request: dict) -> {"ok": bool, "request": dict, "plan": PlanResponse} | {"ok": False, "error": {...}}
runtime.run_elasticity(request: dict) -> {"ok": bool, "elasticity": dict} | {"ok": False, "error": {...}}
runtime.compare(requests: list[dict]) -> list[dict]
runtime.compliance_scan(text, policy=..., location=...) -> list[flag]
```

`run_plan` 内部调用 `engine.orchestrator.generate_plan(PlanRequest, include_elasticity=False)`。
`run_elasticity` 调用 `engine.orchestrator.generate_elasticity(PlanRequest)`。

## HTTP

| 路径 | 方法 | 说明 |
|---|---|---|
| `/api/meta` | GET | 场馆/媒体/预算/档期/费率 |
| `/api/health` | GET | 引擎/数据状态 |
| `/api/plan` | POST | 单方案 |
| `/api/elasticity` | POST | 九档弹性 |
| `/api/plans/batch` | POST | 批量：`{"budgets":[100,200,500], ...}` 或 `{"requests":[...]}` |
| `/api/agent/analyze` | POST | Agent 分析入口（本文件所在架构新增） |
| `/api/agent/skills` | GET | 技能清单 |

## PlanRequest

```jsonc
{
  "industry": "乐园",           // 当前只支持乐园
  "venue": "lego_shanghai",     // lego_shanghai | disney_shanghai | haichang_shanghai
  "budget_wan": 200,            // 100–500
  "media": ["bus", "metro"],    // bus | metro
  "start_date": "2027-07-01",   // 2027 年内
  "weeks": 8,                   // 2 | 4 | 6 | 8 | 12
  "customer_type": "direct",    // direct | 4a
  "locks": {"include": [], "exclude": []},
  "brief_text": "可选，规则解析用"
}
```

## PlanResponse 关键字段

完整契约见 `docs/契约-v1.md`。这里只列分析必读：

```jsonc
{
  "meta": {"data_version", "inventory_ts", "inventory_periods", "solver", "status", "solve_ms", "cache_hit"},
  "inputs": {"industry","venue","venue_name","budget_wan","media","start_date","end_date","weeks","months","customer_type","locks"},
  "plan": {
    "bus": [...],
    "metro": [...],
    "summary": {
      "bus_units","bus_lines","metro_units","metro_stations",
      "media_mix":{"bus_pct","metro_pct"},
      "unit_mix", "level_mix", "district_mix", "poi_hits",
      "gross_wan", "net_wan", "total_paid_wan", "budget_utilization"
    }
  },
  "effects": {
    "impressions","grp","reach","reach_pct","frequency","cpm_yuan","target_population",
    "parameters":{"reach_cap","k","k_eff","view_rate_bus","view_rate_metro","days"},
    "by_media":[{"media","impressions","share","cpm_yuan"}],
    "by_line":[{"id","impressions"}],
    "formula","disclaimer"
  },
  "quote": {
    "rate_card_total_wan","discount_tier":{"label","min_gross_wan","max_gross_wan","rate"},
    "discount","discount_converged","media_net_wan","production_wan","agency_fee_wan",
    "gift_wan","gift_items","total_paid_wan","budget_wan","budget_slack_wan",
    "customer_type","allocation_check":{"sum_lines","total","diff","passed"},"tiers","notes"
  },
  "validation": {
    "passed","checks":[{"id","name","level","passed","detail"}],
    "inventory_check":{"period","timestamp","free_verified"},
    "self_check_10":[...],"limitations":[...]
  },
  "schedule": {"go_live","take_down","total_days","phases","batches","night_capacity","monitoring","compensation","risks"},
  "coverage": {"venue","districts":[...],"poi_hits":[...],"sources","disclaimer"},
  "strategy": {"one_liner","audience","transport","media_roles","mix_rationale","compliance","creative","avoid"},
  "hypothesis": {"fields":[{"id","label","value"}],"one_liner","assumptions"},
  "explanations": {"why_selected","why_not","trim_priority","counterfactuals","hypothesis_links"},
  "workflow": {"mode","llm_used","stages","guardrails"}
}
```

## ElasticityResponse

```jsonc
{
  "unit": "万元",
  "points": [
    {"budget_wan","impressions","reach","frequency","cpm_yuan",
     "marginal_impressions_per_wan","delta_reach","is_current"}
  ],
  "knee_budget_wan": 200,
  "note": "同一优化器的确定性预算扩展估值（greedy）；主方案以 CP-SAT 结果为准。"
}
```
