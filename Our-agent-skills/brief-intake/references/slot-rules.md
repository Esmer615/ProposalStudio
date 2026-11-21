# 槽位抽取规则（brief-intake 参考）

> 这张表是 `agent/intake.py` 的行为说明；改规则时两边要同步。

## 1. 优先级

```
structured request > brief 明确值 > 季节/上下文推断 > 默认值
```

- structured：销售在界面明确选的字段，source=`structured`。
- brief：文本里能指到原词的，source=`brief`。
- inferred：从“暑期/国庆/寒假”等推出来的，source=`inferred`，必须写 assumption。
- default：完全没说才用，source=`default`，必须写 assumption。
- llm：只补软字段；硬字段仍要经过规则和引擎校验。

## 2. 场馆

| id | 别名 |
|---|---|
| `lego_shanghai` | 乐高、乐高乐园、LEGOLAND、lego |
| `disney_shanghai` | 迪士尼、迪士尼乐园、Disney |
| `haichang_shanghai` | 海昌、海洋公园、海昌海洋公园、Ocean Park |

- 命中多个 → 冲突，必须提问。
- 命中一个 → source=brief，confidence=high。
- 没命中 → 缺失；allow_defaults 时用乐高，否则提问。

## 3. 预算

识别优先级：

1. 带“预算/费用/媒体/总预算”上下文的数字（最高置信度）
2. `数字 + 万/万元/w/W/元`
3. 中文数字 + 万：一百五十万、两百万、三百五十万
4. `数字元` ≥ 100000 → 除以 10000

规则：

- 单位统一为万元。
- 多个不同数字 → conflicts，confidence=low；如果无法判断，按上下文取第一个。
- <100 或 >500 → 越界：allow_defaults 时收敛到最近边界并写 assumption；否则提问。
- 不要从“8 周”“3 个点位”里误抽预算。

## 4. 媒介

| id | 别名 |
|---|---|
| `bus` | 公交、公交车、公交车身、巴士、车身 |
| `metro` | 地铁、轨道交通、轨交、地铁口、出入口、站点 |

- “全媒体 / 公交+地铁 / 公交和地铁” → `["bus","metro"]`。
- 命中一个 → 单媒体。
- 没命中 → 缺失；allow_defaults 时用两者。
- 非法值 → 提问或收敛。

## 5. 档期

| 写法 | 结果 | source |
|---|---|---|
| `2027-07-01` / `2027/7/1` / `2027年7月1日` | 精确日期 | brief |
| `2027年7月` | 2027-07-01 | brief/medium |
| `7月1日` / `7月` | 2027 年对应日期 | inferred |
| 暑期/暑假 | 2027-07-01 | inferred |
| 国庆 | 2027-10-01 | inferred |
| 五一 | 2027-05-01 | inferred |
| 寒假 | 2027-01-15 | inferred |
| 元旦 | 2027-01-01 | inferred |

- 只接受 2027 年；年份不符 → 提问或收敛并写 assumption。
- 日期非法（2 月 30 日）→ 提问/收敛。

## 6. 周数

| 写法 | 结果 |
|---|---|
| `8 周` | 8 |
| `8 个星期` | 8 |
| `2 个月` / `两个月` | 8（按 4 周/月） |
| 暑期且未写周数 | 8（inferred） |

- 可选档位：`[2, 4, 6, 8, 12]`。
- 不在档位 → 提问；allow_defaults 时取最近档并写 assumption。

## 7. 客户类型

| 写法 | 结果 |
|---|---|
| 4A / 代理 / agency | `4a` |
| 直客 / direct | `direct` |
| 未说明 | `direct`（assumption） |

影响：4A 加 15% 服务费，直客不加。

## 8. 分析视角（objective）

不是引擎参数，只影响场景选择与评分权重。

| objective | 触发词 |
|---|---|
| `efficiency` | 效率、性价比、最值、划算、预算有限、花得值、投产比 |
| `precision` | 精准、目标人群、核心人群、亲子家庭、家长、触达、浓度 |
| `reach` | 曝光、覆盖、广度、全城、声量、看到、到达 |
| `brand` | 品牌、知名度、心智、认知、形象 |
| `balanced` | 未明确，或同时提到多个冲突目标 |

## 9. 合规扫描

见 `proposal-narrative/policy.json` 的 `forbidden_claims`。否定语境跳过。
