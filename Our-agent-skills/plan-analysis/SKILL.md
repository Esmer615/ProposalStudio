---
name: plan-analysis
description: 调用确定性引擎生成方案与预算弹性，读取真实字段做可行性、预算使用率、覆盖/频次/CPM、库存与校验分析，并做同预算可比的多场景对比。
version: 2.0.0
stage: analysis
order: 30
tools: [plan.generate, elasticity.generate, catalog.get, compliance.scan]
outputs: [scenario-metrics, feasibility, comparison, risks]
references:
  - references/tool-contract.md
  - references/metrics-dictionary.md
  - references/warning-playbook.md
guardrails:
  - 所有数字来自 engine 的 PlanResponse；派生指标必须写公式。
  - 预算没花完必须主动说；不得用“预算一定花满”的旧说法。
  - 不把公交与地铁的 reach 相加；引擎本身就是单条饱和曲线。
  - 不同预算的场景不能只比 Reach 绝对值，必须同时看使用率与每万元目标 Reach。
  - 数据口径必须区分红豆库存、POI 估算、模型曝光估算、折扣假设。
---

# 算方案：调用引擎，读真实字段，做可比分析

## 0. 你的角色

你不直接“算”出方案。你的动作是：

1. 把场景请求交给**确定性引擎**；
2. 读引擎返回的真实字段；
3. 检查可行性、预算使用率、库存、排期、报价；
4. 做**同预算可比**的横向比较；
5. 把风险和口径交给下游话术。

---

## 1. 工具契约（当前 Python 引擎）

### 1.1 Agent 内部工具

| 工具 | 作用 | 关键参数 |
|---|---|---|
| `catalog.get` | 场馆/媒体/预算范围/档期/场馆档案/数据版本 | 无 |
| `plan.generate` | 单方案，返回完整 PlanResponse | `venue, budget_wan, media, start_date, weeks, customer_type, locks` |
| `elasticity.generate` | 九档预算弹性（greedy 扩展估值，带缓存） | 同上 |
| `compliance.scan` | 扫描危险承诺/校内措辞 | `text, policy, location` |

### 1.2 HTTP（前端/外部调用）

```http
POST /api/plan          # 单方案
POST /api/elasticity    # 九档弹性
POST /api/plans/batch   # 多方案（budgets=[100,200,500] 或 requests=[...]）
```

### 1.3 输入

```jsonc
{
  "venue": "lego_shanghai",     // lego_shanghai | disney_shanghai | haichang_shanghai
  "budget_wan": 200,            // 100–500
  "media": ["bus", "metro"],    // bus | metro
  "start_date": "2027-07-01",   // 2027 年内
  "weeks": 8,                   // 2 | 4 | 6 | 8 | 12
  "customer_type": "direct",    // direct | 4a
  "locks": {"include": [], "exclude": []}
}
```

### 1.4 输出字段（真实，不要自造）

```jsonc
{
  "meta": {"data_version", "inventory_ts", "solver", "status", "solve_ms", "cache_hit"},
  "inputs": {"venue", "budget_wan", "media", "start_date", "end_date", "weeks", "months", "customer_type"},
  "plan": {
    "bus": [{"id","name","level","units","free_count","net_wan","total_wan","score","poi_hits","reasons"}],
    "metro": [/* 同上 */],
    "summary": {
      "bus_units","bus_lines","metro_units","metro_stations",
      "media_mix":{"bus_pct","metro_pct"},
      "level_mix","district_mix","poi_hits",
      "gross_wan","net_wan","total_paid_wan","budget_utilization"
    }
  },
  "effects": {
    "impressions","grp","reach","reach_pct","frequency","cpm_yuan",
    "target_population","parameters":{"reach_cap","k","k_eff","days"},
    "by_media":[{"media","impressions","share","cpm_yuan"}],
    "formula","disclaimer"
  },
  "quote": {
    "rate_card_total_wan","discount","discount_tier","discount_converged",
    "media_net_wan","production_wan","agency_fee_wan","gift_wan",
    "total_paid_wan","budget_slack_wan","allocation_check","tiers","notes"
  },
  "validation": {
    "passed","checks":[{"id","name","level","passed","detail"}],
    "inventory_check","limitations"
  },
  "schedule": {"go_live","take_down","total_days","batches","night_capacity","monitoring","compensation","risks"},
  "coverage": {"venue","districts","poi_hits":[{"id","name","type","weight","hit_by","source"}]},
  "strategy": {"one_liner","audience","media_roles","mix_rationale","compliance","avoid"},
  "hypothesis": {"fields":[...],"one_liner","assumptions"},
  "explanations": {"why_selected","why_not","trim_priority","counterfactuals","hypothesis_links"}
}
```

**没有的字段**（旧 skill 里的）：`metrics.targetReach`、`metrics.efficiency`、`metrics.utilization`、
`warnings[]`、`dataQuality.trafficSource`、`planId`、`strategy.key`。
不要引用这些；用上面的真实字段做派生。

---

## 2. 派生指标（写清公式）

| 指标 | 公式 | 用途 |
|---|---|---|
| `utilization` | `quote.total_paid_wan / inputs.budget_wan` | 预算使用率；<85% 必须说明 |
| `reach_people` | `effects.reach × effects.target_population` | 目标人群到达人数（模型估算） |
| `impressions_per_wan` | `effects.impressions / quote.total_paid_wan` | 每万元实际花费买到的总曝光 |
| `reach_people_per_wan` | `reach_people / quote.total_paid_wan` | 每万元目标 Reach，用于跨预算比较 |
| `premium_share` | `(S + A++ + A+) units / 总 units` | 高等级库存占比（不是人群浓度） |
| `saturation` | `effects.reach / effects.parameters.reach_cap` | 距模型到达上限还有多少空间 |

**注意**：`effects.reach` 是到达率（0–1），不是人数；`effects.impressions` 是总曝光人次，
不是目标人群曝光。两者不能混用。

---

## 3. 标准工作流

```
1. 接 intake 的 request
2. plan.generate 生成基准方案
3. elasticity.generate 拿九档与 knee_budget_wan
4. 按 strategy 设计场景，逐个 plan.generate
5. 每个场景检查：
   - validation.passed（blocker）
   - utilization 是否 ≥85%
   - effects.reach / frequency / cpm 是否合理
   - schedule.night_capacity 是否够
   - quote.allocation_check 是否为 true
6. 横向比较（同预算/不同预算分开）
7. 输出 metrics + comparison + risks
```

---

## 4. 必须检查的五件事

### 4.1 预算花满了没有

看 `utilization = quote.total_paid_wan / inputs.budget_wan`。

- ≥85%：可以说“基本花满”。
- 70–85%：**必须主动说**“部分未花完”，并给选择：放宽约束 / 降预算 / 换档期。
- <70%：方案不能直接推荐；大概率是供给或约束卡住。

**不要再说“预算一定会花满”**。当前引擎会留制作费/赠媒/代理费，且库存可能买空；
fixture 里 200 万方案实际落地 188.4 万（94.2%），这就是正常情况。

### 4.2 独立校验过了没有

`validation.passed` 是所有 blocker 的与。看 `validation.checks` 里 `level=blocker` 且 `passed=false` 的项。
**blocker 失败 → 客户提案不可导出。**

常见 blocker：V1 预算、V2 库存、V3 特殊状态、V6 施工产能、V7 报价分摊、V8 折扣档位、V10 假设书回链。

### 4.3 Reach/频次/CPM 是不是可信

- `effects.reach` 不能超过 `effects.parameters.reach_cap`（通常 0.82）。
- 双媒体时 `k_eff = k × 1.10`，公交和地铁合并用**一条**饱和曲线，不能相加。
- 频次 >20 时提醒“继续加钱主要买重复曝光”。
- CPM 是混合口径：`媒体净价 / 总曝光 × 1000`；地铁 CPM 通常远高于公交，不要用一个总 CPM 掩盖结构差异。

### 4.4 排期排得下吗

看 `schedule.night_capacity`：公交 20 辆/晚、地铁 10 口/晚、总夜数、2 个雨备夜。
`bus_units` / `metro_units` 接近上限时，长尾点位要延后上刊。

### 4.5 报价对不对

- 折扣按**全单刊例总额**落档：88/83/78/73/68%。
- 4A 加 15% 服务费；直客不加。
- 赠媒是折后媒体费的 5%。
- `quote.allocation_check.passed` 必须为 true，逐行加总 == 总价。

---

## 5. 横向比较规则

1. **同一笔预算**：可以直接比 Reach/曝光/频次/POI。
2. **不同预算**：先比 `utilization`，再比 `reach_people_per_wan`；不要只报 Reach 绝对值。
3. 只比较 `validation.passed=true` 的场景；失败的场景单独列为“不可行”。
4. 至少保留两个场景 + 各自适用条件，不给单一“最优解”。
5. 评分只是相对排序，必须在话术里说明权重来自 objective，不是客户价值本身。

---

## 6. 数据质量口径

| 层 | 当前来源 | 必须怎么说 |
|---|---|---|
| 库存 | 红豆 2027 月度快照 | “红豆快照，数据版本 X；上刊前需重核占用” |
| POI/人群 | 公开近似 POI 库 | “公开近似，不用于测量级结论” |
| 曝光/Reach | 引擎饱和曲线模型 | “模型估算，不是实测” |
| 平台人流 | **未接入** | “当前没有平台实测区域人流” |
| 折扣 | 全单落档假设 | “档位口径待赞助方确认” |
| 场馆档案 | `data/config/venues/*.json` | “自驾/高铁/人群为策划假设” |

---

## 7. 输出契约

```jsonc
{
  "scenarios": [
    {
      "id": "base",
      "request": {...},
      "ok": true,
      "metrics": {
        "budget_wan", "total_paid_wan", "utilization", "budget_slack_wan",
        "impressions", "reach_pct", "reach_people", "frequency", "cpm_yuan",
        "poi_hits", "bus_units", "metro_units", "discount_label",
        "validation": {"passed": true, "blockers": [], "warnings": []}
      },
      "risks": [{"code","level","message","action","evidence"}],
      "score": {"total", "breakdown", "rank", "feasible"}
    }
  ],
  "comparison": [...],
  "elasticity": {"knee_budget_wan", "current_point", "interpretation"},
  "recommendation": {"primary_scenario", "verdict", "why", "tradeoffs", "alternatives"}
}
```

---

## 8. 自检

- [ ] 每个数字都能指到 PlanResponse 的字段或写明派生公式
- [ ] 预算没花完的场景，我主动说了
- [ ] 我没有把公交和地铁的 reach 相加
- [ ] 不同预算的对比，我用了使用率和每万元 Reach
- [ ] 只推荐了通过 blocker 校验的场景
- [ ] 我给了至少两个场景 + 各自适用条件
- [ ] 数据口径四层都标了：库存/POI/曝光/折扣
