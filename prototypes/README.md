# Prototypes — 已跑通的原型代码

全部基于**真实数据**（431 条台账 + 真实刊例中值），在本机验证通过。

## 运行

```bash
cd prototypes
export PYTHONIOENCODING=utf-8
PY="C:/Users/20614/AppData/Local/Python/pythoncore-3.14-64/python.exe"

"$PY" test_bus_optimizer.py    # 求解器 + 9 项约束自检
"$PY" pipeline.py              # 端到端：skill -> 求解 -> 效果 -> JSON
```

> ⚠️ 这台机器的 `python` 是 Windows Store 别名桩，直接调用会静默返回 exit 49。
> 必须用上面的完整路径。

## 文件

| 文件 | 作用 |
|---|---|
| `bus_optimizer.py` | **核心求解器**。`Config` / `load_bus_ledger` / `solve` / `solve_many` |
| `effects_model.py` | 确定性 Reach/Frequency 估算 + 边际效率排序 |
| `skill_loader.py` | PM Skill 解析 + 严格 schema 校验（无 PyYAML 依赖） |
| `pipeline.py` | 端到端流水线 |
| `test_bus_optimizer.py` | 约束自检 + 可复现性测试 |
| `skills/_schema.yaml` | Skill 字段定义 |
| `skills/ban_insurance.md` | 银行保险 skill 样例（PM 照这个写） |
| `skills/beverage.md` | 食品饮料 skill 样例 |
| `out/pipeline_result.json` | 流水线输出样例 |
| `milp_bus_baseline.py` | 最早的原型（无约束，展示问题：过度集中） |
| `milp_budget_scaling.py` | 加约束后的预算缩放原型 |

## 验证结果

```
候选线路: 430  可用车辆总量: 2517

    预算        状态    线路    车辆      花费     余量     高等级     夜负荷       耗时
   100   OPTIMAL    12    18   100.0    0.0    72%     1.8     35ms
   200   OPTIMAL    12    36   200.0    0.0    75%     3.6     16ms
   500   OPTIMAL    26    91   500.0    0.0    74%     9.1     44ms

约束自检 (预算 200 万)
  [PASS] 不超预算: 200.00 <= 200
  [PASS] 线路数≥12
  [PASS] 线路数≤45
  [PASS] 施工排得下: 36 <= 250
  [PASS] 高等级占比50%-75%: 75.0%
  [PASS] 单线上限≤4辆
  [PASS] 区域全覆盖: 10/10
  [PASS] 不超库存: 0 条越界
  [PASS] 可复现（同输入同输出）
```

## 已知局限

1. **只有公交**，地铁 861 个点位必须从红豆导（资料包里没有）
2. `COMPANY_REGION` 用运营公司近似地理区域，真实版应换成线路轨迹 + POI 覆盖
3. `DAILY_RIDERS` 是按线路等级的**经验值**，真实值应从可视化平台导
4. 档期约束目前只按"空位数"静态处理，没有按具体日期查可售
5. 没有"次优解池"（OR-Tools CP-SAT 支持，CBC 不支持）

## 切换到 OR-Tools CP-SAT

当前用 `pywraplp` + CBC（部署最简单）。若要开"次优解"/更强约束表达，改 `bus_optimizer.solve()` 为
`from ortools.sat.python import cp_model`，变量/约束写法基本 1:1 对应，已在本机验证 CP-SAT 可用。
