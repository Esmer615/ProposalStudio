# 乐园行业户外媒体提案引擎（Track B）

确定性主题公园提案引擎，唯一入口 `engine/orchestrator.generate_plan()`，
返回与 `docs/契约-v1.md` 完全一致的 `PlanResponse`。

## 运行

```bash
# Python 必须是完整路径（这台机器的 `python` 别名是坏的）
PY=C:/Users/20614/AppData/Local/Python/pythoncore-3.14-64/python.exe

# CLI
$PY -m engine.cli --venue lego_shanghai --budget 500 --media bus,metro --start 2027-07-01 --weeks 8 --customer-type direct --out out.json

# 九档弹性
$PY -m pytest engine/tests/test_engine.py -q
```

## 模块

| 文件 | 职责 |
|---|---|
| `models.py` | Lead 冻结的 `PlanRequest`/`PlanError`（不改） |
| `config.py` | 集中配置：等级映射/曝光代理/折扣/排期/求解参数 |
| `skill_loader.py` | 场馆档案加载（`data/config/venues/*.json`，缺则内置回退） |
| `data_loader.py` | 红豆快照 CSV → 候选；去重/过滤/跨月 min_free/日期覆盖 |
| `candidates.py` | 候选富化（价格/曝光/POI 命中/区县/廊道/评分） |
| `finance.py` | 刊例价+折扣档位+全单折扣不动点+行分摊 |
| `effects.py` | Reach/Frequency/CPM（饱和曲线，双媒体归因不相加） |
| `solver/solve.py` | CP-SAT 主模型 → HiGHS 兜底 → 贪心；确定性 |
| `schedule.py` | 阶段/批次/夜装产能/雨备/监测 SLA/误一补二 |
| `validator.py` | 独立校验（不 import solver），10 blocker/warning |
| `explanations.py` | 假设书七要素/策略/逐点理由/反事实/回链 |
| `ai/` | 离线规则 brief 解析/策略检索/narrator（无 LLM 不假装） |
| `orchestrator.py` | 唯一 `generate_plan()` + LRU 缓存 + `generate_elasticity()` |
| `cli.py` | `python -m engine.cli` |

## 关键假设（答辩可摊开）

- 地铁 `lineLevel` 2=A++ / 3=A+ 为**显式假设**（`config.METRO_LEVEL_MAP`）。
- 公交 `lineLevel` 1=S / 2=A++ / 3=A+ / 5=AA（AA 不进曝光主线）。
- 曝光代理为线路等级经验值（bus S 5.8万/A++ 4.8万/A+ 3.8万；metro A++ 9万/A+ 5.5万 人次/天）。
- 折扣档（88/83/78/73/68%）阈值以契约为准（0/200/350/500/700 万），折扣率来自 `rate_card_2027.json`。
- 乐高无地铁直达：采用 6/20/50km 圈 + 家庭客源枢纽，不做硬 6km 过滤。
- 地铁口坐标/POI 坐标为公开近似，缺失时标 `confidence: low / schematic`。

## 确定性

CP-SAT `num_search_workers=1` + `random_seed=42` + 固定时间窗 + 贪心 warm-start hint。
弹性曲线用确定性贪心（单调于预算）。同输入重复调用，除 `meta.generated_at/request_id/solve_ms/total_ms/cache_hit` 外完全一致。

## 已知局限

- 求解在 100 万预算下 bus 仅约 5–9 辆（公交车身按刊例价，反直觉但真实）。
- CP-SAT 在 600ms 时间窗内多数返回 FEASIBLE（非 OPTIMAL），但结果确定性、预算/库存均满足。
- POI/站点坐标依赖 `data/geo`（数据组维护）；缺失时退化为区县示意。
