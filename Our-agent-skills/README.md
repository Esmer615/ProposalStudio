# Agent Skills：接需求 → 想策略 → 算方案 → 说人话

> 这不是三篇给人看的教程，而是 **Agent 可加载的技能包**。
> 目录结构、`SKILL.md` frontmatter、`policy.json` 和 `references/` 都由
> `agent/skills.py` 读取；`agent/runtime.py` 按 stage 逐个执行。

---

## 1. 架构：有边界的 Agent，不是自由 ReAct

```
客户 brief
   │
   ▼
┌─────────────────────────────────────────────────────────────┐
│ ProposalAgent（agent/runtime.py）                            │
│  状态机：INTAKE → STRATEGY → ANALYSIS → GUARD → NARRATIVE   │
│  · 每一步只加载一个 skill（渐进披露）                        │
│  · 工具调用全部记录到 trace                                  │
│  · LLM 只做理解/润色，不碰数字                               │
└───────────────┬─────────────────────────────────────────────┘
                │ 工具（JSON in / JSON out）
                ▼
┌─────────────────────────────────────────────────────────────┐
│ ToolRuntime（agent/tools.py）                                │
│  catalog.get / plan.generate / elasticity.generate /         │
│  compliance.scan                                             │
└───────────────┬─────────────────────────────────────────────┘
                │ 纯函数、固定 seed、单线程
                ▼
┌─────────────────────────────────────────────────────────────┐
│ engine（现有 Python 引擎）                                    │
│  PlanRequest → CP-SAT → PlanResponse                         │
│  generate_elasticity（九档预算扩展，greedy，带缓存）           │
└─────────────────────────────────────────────────────────────┘
```

**为什么不用自由 ReAct：**

- 报价/库存/曝光算错是商业事故，不能由模型决定“算什么”；
- 现场演示要求同输入同输出，模型做不到确定性复算；
- 但“接需求、判断缺什么、设计哪几个场景、怎么说”确实需要判断，
  所以用**技能驱动的有界状态机**：判断留给 Agent，算术锁在引擎。

**为什么不用 Managed Agents：** 这是本地比赛演示工具，要求离线、无 API Key 也能跑；
托管 agent 会增加网络/凭证依赖。这里的 Agent 是一个可本地运行的 Python 包。

---

## 2. 四个 skill，对应四个阶段

| 顺序 | 目录 | stage | 一句话 |
|---|---|---|---|
| ① | [`brief-intake/`](./brief-intake/SKILL.md) | `intake` | 把客户一句话变成可计算请求 + 待确认问题 + 显式假设 |
| ② | [`audience-strategy/`](./audience-strategy/SKILL.md) | `strategy` | 判断这单该跑哪些场景，解释人群/POI/交通结构 |
| ③ | [`plan-analysis/`](./plan-analysis/SKILL.md) | `analysis` | 调引擎、读真实字段、做可比分析与风险检查 |
| ④ | [`proposal-narrative/`](./proposal-narrative/SKILL.md) | `narrative` | 把结果说成人话，每个数字带口径，主动说代价 |

**加载顺序由 frontmatter 的 `order` 决定**，stage 名由 `stage` 决定。
Agent 每个阶段只把对应的 `SKILL.md` 正文放进上下文；`references/` 按需读取。

---

## 3. 一个 skill 的结构

```
brief-intake/
├─ SKILL.md          # 人/LLM 可读：目标、规则、输出、自检
├─ policy.json       # 机器可读：默认值、范围、阈值、评分权重、禁用短语
└─ references/
   ├─ slot-rules.md
   └─ clarification-playbook.md
```

### 3.1 SKILL.md frontmatter

```yaml
---
name: plan-analysis              # kebab-case，唯一
description: ...                 # 一行，给检索/路由用
version: 2.0.0
stage: analysis                  # intake | strategy | analysis | narrative
order: 30                        # 加载顺序
tools: [plan.generate, elasticity.generate]
outputs: [scenario-metrics]
references: [references/metrics-dictionary.md]
guardrails:                      # 硬约束，会进入最终 guardrails 列表
  - 预算没花完必须主动说
---
```

### 3.2 policy.json

`SKILL.md` 是给人和 LLM 的说明；`policy.json` 是给确定性代码的旋钮：

- `brief-intake/policy.json`：必填槽位、预算范围、默认值、别名、提问上限；
- `audience-strategy/policy.json`：场景预算步长、媒体替代规则、objective 排序；
- `plan-analysis/policy.json`：预算使用率阈值、评分权重、比较规则、派生指标公式；
- `proposal-narrative/policy.json`：禁用短语、必须披露项、数字格式。

改策略不用改 Python；改 `policy.json` 即可（跑 `pytest agent/tests` 验证）。

### 3.3 references/

细节表格放这里，避免把几千字一次性塞进上下文。
Agent 在需要时通过 `SkillSpec.read_reference()` 读取，路径做了越界保护。

---

## 4. 和旧版 skill 的三个关键差异

### 4.1 不再引用 `model/compute.js`

旧版三篇 skill 是给一个 JS 原型写的（`node model/compute.js`、`precision/balanced/reach/corridor`、
`metrics.targetReach`、`warnings[]`、`dataQuality.trafficSource`）。
当前项目是 Python 引擎，没有这些接口。新版全部改成：

- `engine.orchestrator.generate_plan / generate_elasticity`
- `POST /api/plan` / `/api/elasticity` / `/api/plans/batch`
- 真实字段：`plan.summary`、`effects`、`quote`、`validation.checks`、`coverage`、`schedule`

### 4.2 不再说“预算一定花满”

旧版说四个策略在 100/200/300/500 万下都花满 100%。当前 Python 引擎会保留制作费/赠媒/代理费，
库存也可能买空。实测 fixture：200 万方案落地 188.4 万（94.2%）。
新版规则：**先报使用率，<85% 必须主动说明**。

### 4.3 不再假装有四个策略

当前引擎只有一个确定性优化器。新版把“精准 vs 覆盖”定义成**分析视角**，
场景轴改为引擎真正支持的：预算下探/上探/弹性拐点/媒体组合。

---

## 5. 怎么运行

```powershell
# 查看技能清单与校验结果
.venv\Scripts\python.exe -m agent.cli --skills

# 一句话 brief
.venv\Scripts\python.exe -m agent.cli --brief "客户是上海乐高乐园，预算200万，暑期8周，公交+地铁，要覆盖亲子家庭" --allow-defaults

# 严格模式：缺字段就提问
.venv\Scripts\python.exe -m agent.cli --brief "预算200万，做个乐园提案"

# 结构化输入 + 输出 JSON/Markdown
.venv\Scripts\python.exe -m agent.cli --request-file req.json --json out.json --markdown report.md

# HTTP
POST /api/agent/analyze
GET  /api/agent/skills
```

### 可选 DeepSeek 增强（不配 Key 也能跑）

```text
# 项目根目录 .env（已 gitignore）
DEEPSEEK_API_KEY=sk-...
# 可选：DEEPSEEK_MODEL=deepseek-chat / DEEPSEEK_BASE_URL=https://api.deepseek.com
```

```powershell
.venv\Scripts\python.exe -m agent.cli --brief "..." --llm auto
```

DeepSeek 走 OpenAI-compatible HTTP，复用项目已有的 `httpx`，不需要额外 SDK。
没有 Key 时自动回退规则；LLM 润色还要通过**数字守卫**和**合规守卫**，
任一不通过就用确定性模板。

---

## 6. 设计原则（答辩可讲）

1. **AI 不做算术**：报价、库存、Reach 全部来自引擎；LLM 输出要过数字守卫。
2. **技能是数据不是代码**：Markdown + YAML + JSON，产品/策划可改。
3. **渐进披露**：每个阶段只加载一个 SKILL.md，细节按需读 references。
4. **缺失不编**：要么提问，要么写 assumption；每个字段带 source/evidence。
5. **校验独立**：engine 的 validator 不 import solver；Agent 不绕过 blocker。
6. **可比性**：不同预算不能只比 Reach；用使用率 + 每万元目标 Reach。
7. **确定性**：同输入引擎输出一致（meta 时间戳除外）；LLM 只是可选层。

---

## 7. 已知边界

- 当前没有接入可视化平台实测区域人流；Reach 是模型估算。
- 目标人群是场馆档案策划假设，不是实测去重人群。
- POI/公交几何为公开近似/区县示意。
- 折扣档位、地铁等级语义是待确认假设。
- 引擎只有一个优化器；“精准/覆盖”不是可切换的策略参数。
- 库存是 2027 月度快照，上刊前需重核。

旧版三篇 skill 已归档到 [`archive/`](./archive/)，不参与加载，仅作历史对照。
