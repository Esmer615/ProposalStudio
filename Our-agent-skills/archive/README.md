# 归档：v1 技能（不参与加载）

这里的三个 Markdown 是上一版技能，写给一个 **JS 原型**：

- `model/compute.js`
- `precision / balanced / reach / corridor` 四个策略参数
- `metrics.targetReach` / `metrics.efficiency` / `metrics.utilization`
- `warnings[]` / `dataQuality.trafficSource`

当前项目是 Python 引擎，没有这些接口；因此新版把内容迁移并校正到
`../brief-intake/`、`../audience-strategy/`、`../plan-analysis/`、`../proposal-narrative/`。

**保留原因：**

- 人群/POI 的商业逻辑、合规措辞、话术样例仍然有价值；
- 方便对照“旧说法哪里不适用于当前引擎”（例如“预算一定花满”“四个策略”）。

**不要：**

- 不要把这几个文件当 Agent 的 skill 加载；
- 不要在新提案里引用旧版的具体数字（如“科技馆 22 个点位、40–50 万买满”），
  库存/候选池已经变了。用当前引擎的 `elasticity` 与 `plan.summary` 重新验证。

`agent/skills.py` 会跳过 `archive/`。
