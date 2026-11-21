# Agent 架构与技能说明

> 版本：v1.0 ｜ 日期：2026-11-22
> 代码：`agent/` ｜ 技能：`Our-agent-skills/` ｜ 引擎：`engine/`（不变）

---

## 1. 目标

让销售把「客户一句话需求」交给 Agent，得到：

1. **需求理解**：场馆/预算/媒介/档期/客户类型，缺什么、假设了什么；
2. **可行性判断**：预算能不能花出去、库存/排期/报价有没有 blocker；
3. **场景对比**：预算下探/上探/弹性拐点/媒体组合，各自的取舍；
4. **可追溯结论**：每个数字都能指到 `PlanResponse` 字段或写明派生公式；
5. **客户话术**：带口径、主动说代价、不承诺到园/ROI、不投校内。

**边界**：这是曝光覆盖分析工具，不是转化归因工具；是确定性决策工具，不是自由生成方案工具。

---

## 2. 为什么选这个架构

### 2.1 备选方案

| 架构 | 优点 | 致命问题 |
|---|---|---|
| 自由 ReAct（LLM 自己决定调什么工具） | 灵活 | 不能保证可复算；可能跳过校验；报价/库存算错是商业事故 |
| 纯函数流水线（无 Agent） | 确定、简单 | 不会接需求、不会判断缺什么、不会设计场景 |
| 多 Agent 协作（Planner/Executor/Critic） | 角色清晰 | 对这个单机工具过重；通信成本 > 收益 |
| **有界状态机 + 技能 + 工具（本方案）** | 判断留给 Agent，算术锁在引擎；可离线 | 需要维护技能/policy，但换来可控与可解释 |

### 2.2 结论

**一个有边界的「计划-执行-校验-解释」Agent**：

- 状态机决定阶段，阶段加载对应 skill；
- skill 同时提供人可读说明（`SKILL.md`）和机器可读策略（`policy.json`）；
- 工具调用确定性的 Python 引擎；
- LLM 可选，只做理解补充与话术润色，且必须通过数字守卫与合规守卫；
- 所有阶段/工具调用进入 trace，答辩可回放。

---

## 3. 状态机

```
INTAKE
  ├─ 缺必填字段且不允许默认 → CLARIFICATION（返回问题，不跑引擎）
  └─ 有可计算请求 → STRATEGY
        ↓
STRATEGY（设计场景）
  ├─ 先跑 base（客户原始请求）
  ├─ 跑 elasticity（拿 knee_budget_wan）
  └─ 按 objective 设计 1–4 个场景
        ↓
ANALYSIS（逐场景跑引擎 + 派生指标 + 风险）
        ↓
RECOMMEND（评分 + 主方案 + 替代方案）
        ↓
NARRATIVE（确定性模板 → 可选 LLM 润色 → 守卫）
        ↓
DONE（AgentAnalysis JSON + Markdown）
```

### 3.1 每一步做什么

| 阶段 | 加载 skill | 工具 | 输出 |
|---|---|---|---|
| INTAKE | `brief-intake` | `catalog.get` | `BriefState`（request/slots/questions/assumptions/compliance） |
| STRATEGY | `audience-strategy` | `plan.generate`（base）、`elasticity.generate` | `scenarios[]`（id/label/intent/request） |
| ANALYSIS | `plan-analysis` | `plan.generate`（其余场景） | 每场景 metrics/risks/score/top_picks |
| RECOMMEND | `plan-analysis` | 无 | primary/verdict/why/tradeoffs/alternatives |
| NARRATIVE | `proposal-narrative` | 可选 LLM | markdown/number_guard/llm_used |

---

## 4. 技能格式

### 4.1 目录

```
Our-agent-skills/
├─ brief-intake/
│  ├─ SKILL.md
│  ├─ policy.json
│  └─ references/
├─ audience-strategy/
├─ plan-analysis/
├─ proposal-narrative/
├─ skills-manifest.json
├─ README.md
└─ archive/            # 旧版 JS 技能，不参与加载
```

### 4.2 SKILL.md frontmatter

```yaml
---
name: plan-analysis
description: ...
version: 2.0.0
stage: analysis
order: 30
tools: [plan.generate, elasticity.generate]
outputs: [scenario-metrics, feasibility, comparison, risks]
references: [references/metrics-dictionary.md]
guardrails:
  - 预算没花完必须主动说
---
```

加载器（`agent/skills.py`）校验：

- `name` 必须 kebab-case 且唯一；
- `stage` 必须唯一；
- `order` 必须唯一（决定加载顺序）；
- `references` 必须存在；
- `policy.json` 必须是合法 JSON 对象。

### 4.3 policy.json

`SKILL.md` 是说明，`policy.json` 是确定性代码的旋钮：

| skill | policy 内容 |
|---|---|
| brief-intake | 必填槽位、预算范围、默认值、场馆/媒体别名、objective 关键词、提问上限 |
| audience-strategy | 预算步长、场景顺序、媒体替代规则、objective 标签 |
| plan-analysis | 使用率阈值、频次/饱和/产能阈值、评分权重、比较规则、派生公式 |
| proposal-narrative | 禁用短语、必须披露项、数字格式、主动披露清单 |

**改策略不用改 Python。** 改 policy 后跑 `pytest agent/tests`。

### 4.4 渐进披露

- Agent 每个阶段只把对应 `SKILL.md` 正文放进上下文；
- `references/` 按需读取（`SkillSpec.read_reference`，有路径越界保护）；
- 避免一次性把几万字塞进 prompt。

---

## 5. 工具边界

`agent/tools.py` 的 `ToolRuntime` 是唯一调用引擎的地方：

| 工具 | 底层 | 说明 |
|---|---|---|
| `catalog.get` | `engine.models` / `engine.skill_loader` / `data/processed/manifest.json` | 场馆、媒体、预算范围、档期、场馆档案、数据版本 |
| `plan.generate` | `engine.orchestrator.generate_plan` | 单方案；失败返回 `{ok:false,error}`，不抛到 Agent |
| `elasticity.generate` | `engine.orchestrator.generate_elasticity` | 九档预算扩展（greedy，带缓存） |
| `compliance.scan` | 规则 | 扫描危险承诺/校内措辞 |
| `compare` | 多次 `plan.generate` | 顺序执行，保持确定性 |

**为什么不让 LLM 直接调 HTTP**：工具参数/返回值需要类型校验、trace、错误处理；
用 Python 函数是更强的边界。

---

## 6. 输出契约（AgentAnalysis v1）

```jsonc
{
  "agent": {"name","version","mode","llm","options","skill_count","generated_at","total_ms"},
  "schema_version": "agent-analysis.v1",
  "status": "ready | ready_with_assumptions | needs_clarification | error",
  "brief": {
    "raw_text","status","summary","request",
    "slots": {"venue": {"value","source","confidence","evidence"}},
    "missing","questions","assumptions","objective","audience_notes",
    "constraints","compliance_flags"
  },
  "analysis": {
    "headline","verdict","objective","objective_label","objective_note",
    "audience","key_numbers","feasibility",
    "primary_scenario","primary_label","primary_metrics","primary_risks",
    "comparison","elasticity","data_quality","hypothesis","explanations",
    "compliance","meta","venue_profile"
  },
  "scenarios": [{"id","label","intent","use_when","role","is_base","ok","request","metrics","score","highlights","tradeoffs","risks","top_picks"}],
  "recommendation": {
    "primary_scenario","primary_label","verdict","summary",
    "why","tradeoffs",
    "alternatives":[{"scenario_id","label","score","when_to_use","tradeoff","delta_vs_primary"}],
    "next_actions","base_preferred"
  },
  "narrative": {"mode","headline","markdown","number_guard","llm_used"},
  "skills": {"manifest","runs"},
  "guardrails": [...],
  "tool_calls": [{"tool","version","ms","args","ok"}],
  "meta": {"generated_at","total_ms","data_version","inventory_ts","options","llm","engine","deterministic"},
  "artifacts": {"plans": {...}}  // 仅 include_plan_artifacts=true
}
```

### 6.1 status

| status | 含义 | HTTP |
|---|---|---|
| `ready` | 分析完成，无默认假设 | 200 |
| `ready_with_assumptions` | 分析完成，但用了默认值/推断 | 200 |
| `needs_clarification` | 缺必填字段，未跑引擎 | 200（客户端看 status） |
| `error` | 技能/引擎/未知错误 | 500 |

### 6.2 关键设计

- `brief.slots[*].source`：`structured/brief/inferred/default/llm`，每个值可追问。
- `brief.assumptions`：默认值/推断值逐条列出，不允许“默认了但不说”。
- `scenario.metrics`：只放分析需要的字段，不放完整 PlanResponse（体积控制）。
- `tool_calls`：每次引擎调用的耗时/参数摘要/错误，答辩可回放。
- `artifacts.plans`：需要完整引擎响应时显式开启。

---

## 7. LLM 使用策略

### 7.1 默认离线

- 根目录 `.env` 或环境变量没有 `DEEPSEEK_API_KEY` → `NullLLM`；
- 所有流程走确定性规则；
- 输出里 `agent.mode = "offline-rules"`，`meta.llm.available = false`，`reason` 说明原因。

### 7.2 有 Key 时

DeepSeek 走 OpenAI-compatible HTTP，复用项目已有的 `httpx`，不需要额外 SDK：

| 用途 | 模型调用 | 守卫 |
|---|---|---|
| brief 补充理解 | `POST {DEEPSEEK_BASE_URL}/chat/completions`，`response_format={"type":"json_object"}`，`temperature=0` | 只补软字段；硬字段仍走规则 + 引擎校验 |
| 话术润色 | 同一接口，普通 chat，`temperature=0.2` | 数字守卫 + 合规守卫；不通过就回退模板 |

默认模型 `deepseek-chat`；可用 `DEEPSEEK_MODEL` / `DEEPSEEK_BASE_URL` 覆盖。
`DEEPSEEK_API_KEY` 只在真正调用 LLM 时需要（放在根目录 `.env` 或环境变量）；确定性分析不需要 Key。

### 7.3 数字守卫

- 从分析 JSON 收集所有数字（含比例→百分比换算、四舍五入变体）；
- LLM 输出里的数字必须命中集合，或 ≤12 的口语数字；
- 不命中 → 拒绝 LLM 输出，回退确定性模板；
- 记录 `narrative.number_guard = {"ok": false, "unknown": [...]}`。

### 7.4 合规守卫

- 用 `proposal-narrative/policy.json` 的 `forbidden_claims` 扫描 LLM 输出；
- 否定语境跳过（“不承诺到园人数”不算违规）；
- 命中 → 回退模板。

---

## 8. 关键规则（与旧版 skill 的差异）

| 旧版 | 新版 | 原因 |
|---|---|---|
| `node model/compute.js` | `engine.orchestrator.generate_plan` | 项目是 Python 引擎 |
| `precision/balanced/reach/corridor` 四策略 | 预算/媒体/档期场景轴 | 当前引擎只有一个优化器 |
| “预算一定花满” | 先报 `utilization`，<85% 主动说明 | 引擎会留制作/赠媒/代理，库存可能买空 |
| `metrics.targetReach` | `reach_people = effects.reach × target_population` | 引擎没有该字段 |
| `warnings[]` | `validation.checks`（blocker/warning） | 引擎契约 |
| `dataQuality.trafficSource` | 明确写“当前未接平台实测人流” | 当前没有平台数据 |
| “这是最优解” | 至少两个场景 + 取舍 | 客户需求是多目标的 |

---

## 9. 测试

```powershell
# Agent 单测
.venv\Scripts\python.exe -m pytest agent/tests -q

# 服务 API（含 /api/agent/*）
.venv\Scripts\python.exe -m pytest server/tests -q

# 引擎不回归
.venv\Scripts\python.exe -m pytest engine/tests -q
```

覆盖：

- 技能加载/校验/policy；
- 富 brief 解析、缺字段提问、冲突/越界；
- 合规短语识别与否定语境；
- 场景设计（precision 会加媒体参考）；
- 数字守卫（拒绝未知数字、允许比例→百分比）；
- 端到端离线分析；
- API：技能清单、快速分析、澄清路径。

---

## 10. 扩展点

| 想加什么 | 改哪里 |
|---|---|
| 新场馆 | `data/config/venues/` + `engine.models.VENUES` + `brief-intake/policy.json` 别名 |
| 新行业 | 引擎目前只支持乐园；需要扩展 `PlanRequest.validate` 与场馆/POI 数据 |
| 新场景轴（如档期） | `audience-strategy/policy.json` + `agent/strategy.py` |
| 新指标 | `agent/analyzer.py` 的 `metrics_from_plan` + `plan-analysis/references/metrics-dictionary.md` |
| 新话术模板 | `agent/narrator.py` + `proposal-narrative/references/narrative-templates.md` |
| 换 LLM | `agent/llm.py` 实现同样的 `extract_brief/polish_narrative` 接口 |
| 前端接入 | 读 `POST /api/agent/analyze` 的 `analysis`/`scenarios`/`narrative` |

---

## 11. 已知边界

- 未接可视化平台区域人流；Reach 是模型估算。
- 目标人群是场馆档案策划假设，不是实测去重人群。
- POI/公交几何为公开近似/区县示意。
- 折扣/地铁等级语义是待确认假设。
- 当前引擎只有一个优化器；“精准/覆盖”是分析视角，不是策略参数。
- 库存是 2027 月度快照，上刊前需重核。
