---
name: brief-intake
description: 接收客户提案需求，抽取场馆/预算/媒介/档期/客户类型，识别缺失、冲突与合规风险，产出待确认问题与显式假设。每次提案分析的第一个技能。
version: 1.0.0
stage: intake
order: 10
tools: []
outputs: [brief-state, questions, assumptions, compliance-flags]
references:
  - references/slot-rules.md
  - references/clarification-playbook.md
guardrails:
  - 不编造客户没说的场馆、预算、日期或媒介。
  - 必填字段缺失时先提问；只有显式 allow_defaults 才用默认值，并写入 assumptions。
  - brief 里的到园承诺、ROI、校内投放等危险表述必须标记，不能原样进入提案。
  - 解析结果必须带 source（structured/brief/inferred/default/llm）和 evidence。
---

# 接需求：从一句话 brief 到可计算请求

## 0. 你在这一步做什么

把客户的自然语言需求变成两样东西：

1. **可计算的请求**：`venue / budget_wan / media / start_date / weeks / customer_type / locks`
2. **可追问的诚实边界**：缺什么、假设了什么、客户哪些话不能原样写进提案

你**不算钱**，也不设计场景。你只负责把需求接稳。

---

## 1. 优先级（冲突时按这个顺序）

```
结构化输入 request  >  brief 明确写出的  >  从档期/季节推断的  >  默认值
```

- 结构化输入是销售在界面上明确选的，优先。
- brief 里写“乐高、200 万、公交+地铁、暑期”就是明确值，source=brief。
- “暑期”推断出 2027-07-01 / 8 周，source=inferred，必须写 assumption。
- 没说的字段才用默认值，source=default，必须写 assumption。
- LLM 只补软字段；硬字段仍以规则和引擎校验为准。

---

## 2. 必填与可选

| 槽位 | 必填 | 说明 |
|---|---|---|
| `venue` | 是 | 乐高 / 迪士尼 / 海昌；场馆决定人群、交通结构、库存池 |
| `budget_wan` | 是 | 100–500 万；超出范围必须提问或收敛并写明 |
| `media` | 是 | `bus` / `metro` / 两者；不能默认“全投” |
| `start_date` | 否 | 2027 年内；默认 2027-07-01 暑期 |
| `weeks` | 否 | 2/4/6/8/12；默认 8 周 |
| `customer_type` | 否 | `direct` / `4a`；默认直客（4A 加 15% 服务费） |
| `objective` | 否 | `balanced/reach/precision/efficiency/brand`；只影响分析视角，不是引擎参数 |
| `locks` | 否 | 只能通过结构化输入传 include/exclude 点位 id |

**只有 venue / budget / media 缺失时才阻塞。** 其他字段可以默认，但必须写 assumption。

---

## 3. 什么时候必须提问

按下面的顺序，最多问 5 个，先问阻塞项：

1. **场馆冲突/缺失**：brief 同时提乐高和迪士尼 → 必须问；没提场馆 → 必须问。
2. **预算缺失/越界**：没说预算 → 问；说 600 万 → 问是否收敛到 500 万。
3. **媒介缺失/无法识别**：只写“户外” → 问公交/地铁/组合。
4. **档期越界**：写到 2026 或 2028 → 问 2027 年内日期。
5. **周数不在档位**：说 5 周 → 问 4 周还是 6 周。
6. **客户类型不明**：只有需要区分报价时才问，默认直客。

**不要问的**：objective、audience、创意方向——这些可以由 Agent 先给分析视角，再在话术里说明。

问题必须带：`field`、`question`、`why`（为什么这个字段影响方案）、`options`、`default`、`blocking`。

---

## 4. 默认值规则（仅 allow_defaults）

- 默认场馆：乐高（`lego_shanghai`）
- 默认预算：200 万（中档，能同时看出精准与溢出的取舍）
- 默认媒介：公交 + 地铁
- 默认档期：2027-07-01 起 8 周（暑期）
- 默认客户类型：直客

**每用一个默认值，就写一条 assumption**：

```json
{"field": "weeks", "value": 8, "reason": "brief 未明确投放周数，按暑期 8 周假设", "source": "default"}
```

不允许“默认了但不说”。

---

## 5. 合规扫描（brief 阶段）

客户可能说“保证到园 50 万人”“ROI 要做到 3”“投到学校里”。这些**不能原样进入提案**。

| 危险表述 | 处理 |
|---|---|
| 保证入园/到园/客流/销量/收益 | 标记 critical；改成“提升目标人群曝光/认知”，不承诺转化 |
| ROI / 投资回报 / 转化率 | 标记 high；户外没有归因链路，改成“每万元目标曝光” |
| 投在校园/校内/校园内 | 标记 critical；改成“学校周边 300–500 米的地铁/公交点位” |
| 包入园/效果承诺/稳赚 | 标记 high；删除承诺性措辞 |

否定语境不算（“不要保证到园人数”是合规要求，不是危险承诺）。

---

## 6. 输出契约

```jsonc
{
  "status": "ready | ready_with_assumptions | needs_clarification",
  "request": { /* 可计算的 PlanRequest */ },
  "slots": {
    "venue": {"value": "lego_shanghai", "source": "brief", "confidence": "high", "evidence": "乐高"},
    "budget_wan": {"value": 200, "source": "brief", "confidence": "high", "evidence": "200万"}
  },
  "missing": ["media"],
  "questions": [
    {"id": "Q1", "field": "media", "question": "...", "why": "...", "options": [], "default": [], "blocking": true}
  ],
  "assumptions": [
    {"field": "weeks", "value": 8, "reason": "...", "source": "default"}
  ],
  "objective": "precision",
  "audience_notes": ["客户提到亲子家庭"],
  "compliance_flags": [
    {"code": "GUARANTEE_VISIT", "level": "critical", "matched": "保证到园", "guidance": "..."}
  ]
}
```

---

## 7. 自检

- [ ] venue / budget / media 都有值或都有 blocking 问题
- [ ] 每个默认值/推断值都有 assumption
- [ ] 没有把客户没说的日期、预算、场馆写死
- [ ] 预算在 100–500 万，日期在 2027 年，周数在档位内
- [ ] 危险表述都进了 compliance_flags，且给了改写建议
- [ ] 问题不超过 5 个，且按阻塞程度排序
