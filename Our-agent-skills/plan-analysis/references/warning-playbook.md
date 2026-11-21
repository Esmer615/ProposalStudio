# 校验与警告处理（plan-analysis 参考）

当前引擎没有 `warnings[]` 数组；用 `validation.checks`。每条 check：

```jsonc
{"id":"V1","name":"预算","level":"blocker","passed":true,"detail":"188.4 ≤ 200.0"}
```

## 10 项校验

| id | 名称 | level | 失败时怎么办 |
|---|---|---|---|
| V1 | 预算 | blocker | 报价超预算，不能导出；降预算或改组合 |
| V2 | 库存 | blocker | 采购量超过红豆可售；换点位/降量 |
| V3 | 特殊状态 | blocker | 含封闭/改造出入口；从计划中剔除 |
| V4 | 媒介配比 | warning | 配比偏离场馆档案目标；在话术里解释是库存/单价约束 |
| V5 | 线路/站点数 | warning | 线路/站点过少或过多；检查施工与分散度 |
| V6 | 施工产能 | blocker | 夜间装不下；延后长尾点位或分档上刊 |
| V7 | 报价分摊 | blocker | 逐行加总 ≠ 总价；阻止导出 |
| V8 | 折扣档位 | blocker | 折扣与刊例总额不匹配；复核报价 |
| V9 | 效果口径 | warning | Reach 超上限或 NaN；检查参数 |
| V10 | 假设书回链 | blocker | H1–H7 缺失；补假设书 |

`validation.passed` = 所有 blocker 都通过。

## 其他必须处理的情况

### 预算使用率低

不是 validation 失败，但商业上不能忽略：

```python
utilization = quote.total_paid_wan / inputs.budget_wan
```

- <0.85：主动说“未花完”，给三个选择：放宽约束 / 降预算 / 换档期。
- <0.70：不能直接推荐，先解释原因（供给买空 or 约束卡住）。

### 频次过高

`effects.frequency > 20`：说明加钱主要买重复曝光。
用 `elasticity.knee_budget_wan` 和边际曝光支撑这个判断。

### 施工产能接近上限

`bus_units / (bus_per_night × nights)` 或 `metro_units / (metro_per_night × nights) > 0.8`：
长尾点位延后 1–2 周，保留 2 个雨备夜。

### 折扣未收敛

`quote.discount_converged == false`：报价不是稳定解；以保守档为准，导出前复核。

### POI 命中过少

`plan.summary.poi_hits < 5`：人群相关性可能不足；检查场馆 POI 权重与候选库存，
不要用通用点位冒充亲子点位。

### 数据质量

- `coverage.sources` / `coverage.disclaimer`：POI 与几何来源。
- `effects.disclaimer`：曝光不是到园。
- `validation.limitations`：已知局限。
- `meta.data_version` / `inventory_ts`：库存快照版本与时间。

这些不是“警告”，但必须在话术里主动披露。
