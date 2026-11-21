# 指标字典（plan-analysis 参考）

## 1. 直接来自引擎

| 指标 | 字段 | 含义 | 口径 |
|---|---|---|---|
| 预算 | `inputs.budget_wan` | 客户预算（万元） | 含制作/代理的约束上限 |
| 实际落地 | `quote.total_paid_wan` | 媒体净价 + 制作费 + 代理费 | 万元 |
| 媒体净价 | `quote.media_net_wan` | 折后媒体费 | 万元 |
| 制作费 | `quote.production_wan` | 公交 0.75 万/辆、地铁 0.03 万/口（假设） | 万元 |
| 代理费 | `quote.agency_fee_wan` | 4A 15%，直客 0 | 万元 |
| 赠媒 | `quote.gift_wan` | 折后媒体费 5% 等值点位 | 万元 |
| 剩余 | `quote.budget_slack_wan` | 预算 - 实际落地 | 万元 |
| 折扣 | `quote.discount` | 全单落档 0.88/0.83/0.78/0.73/0.68 | 比例 |
| 刊例总额 | `quote.rate_card_total_wan` | 折前刊例 | 万元 |
| 总曝光 | `effects.impressions` | 人次（模型估算） | 非目标人群曝光 |
| GRP | `effects.grp` | 总曝光 / 目标人群 × 100 | 模型估算 |
| 到达率 | `effects.reach` | 0–1（模型估算） | 单条饱和曲线 |
| 到达率文本 | `effects.reach_pct` | 如 "80.3%" | 直接引用 |
| 频次 | `effects.frequency` | GRP/100 / Reach | 模型估算 |
| CPM | `effects.cpm_yuan` | 媒体净价 / 总曝光 × 1000 | 混合口径 |
| 目标人群 | `effects.target_population` | 场馆档案策划假设 | 不是实测 |
| 到达上限 | `effects.parameters.reach_cap` | 通常 0.82 | 物理上限 |
| 公交车辆 | `plan.summary.bus_units` | 实际采购车数 | 红豆可售 |
| 公交线路 | `plan.summary.bus_lines` | 选中线路数 | — |
| 地铁口 | `plan.summary.metro_units` | 实际采购口数 | 红豆可售 |
| 地铁站 | `plan.summary.metro_stations` | 选中站点数 | — |
| POI 命中 | `plan.summary.poi_hits` | 唯一 POI 数 | 公开近似 |
| 媒体花费占比 | `plan.summary.media_mix` | 公交/地铁花费占比 | — |
| 媒体曝光占比 | `effects.by_media[].share` | 公交/地铁曝光占比 | 只做归因，不用于相加 reach |
| 等级结构 | `plan.summary.level_mix` | S/A++/A+/AA 的车/口数 | — |
| 区县结构 | `plan.summary.district_mix` | 各区县车/口数 | 公交为区县示意 |
| 施工夜数 | `schedule.night_capacity.nights` | 实际用到的夜数 | 上限 10 |
| 夜间产能 | `schedule.night_capacity` | 公交 20/晚、地铁 10/晚 | — |
| 雨备 | `schedule.night_capacity.rain_buffer_nights` | 2 个雨备夜 | — |

## 2. 派生指标（必须写公式）

```python
utilization = quote.total_paid_wan / inputs.budget_wan
reach_people = effects.reach * effects.target_population
impressions_per_wan = effects.impressions / quote.total_paid_wan
reach_people_per_wan = reach_people / quote.total_paid_wan
premium_share = (S + A++ + A+) units / total units
saturation = effects.reach / effects.parameters.reach_cap
```

## 3. 不存在的指标（禁止自造）

| 旧字段/说法 | 为什么不能用 | 替代 |
|---|---|---|
| `metrics.targetReach` | 引擎没有目标人群曝光字段 | `reach_people`（派生） |
| `metrics.targetShare` | 引擎没有人群浓度字段 | `poi_hits` + `poi_types` |
| `metrics.efficiency` | 引擎没有预计算 | `reach_people_per_wan`（派生） |
| `metrics.utilization` | 引擎在 `quote` 里 | `total_paid_wan / budget_wan` |
| `warnings[]` | 引擎用 `validation.checks` | 读 `level`/`passed` |
| `dataQuality.trafficSource` | 当前没有平台人流 | 明确写“未接入” |
| `planId` / `strategy.key` | 当前没有策略参数 | `scenario.id` / `strategy.one_liner` |

## 4. 数值阅读顺序

1. `validation.passed`：不过就别往下推荐。
2. `utilization`：钱花出去了吗。
3. `effects.reach` / `frequency` / `cpm_yuan`：效果与代价。
4. `plan.summary.poi_hits` / `level_mix` / `district_mix`：买到了什么。
5. `quote`：价格结构对不对。
6. `schedule.night_capacity`：能不能落地。
