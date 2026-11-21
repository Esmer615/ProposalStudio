# 乐园 AI 提案工作台 · Proposal Studio

> INTERCITY HACK 湖州场 · AI+办公赛道 · 命题方：上海新云传媒
> 选题：**乐园（主题公园）** ｜ 主推：**上海乐高乐园**（迪士尼/海昌可切换）
> 一句话：给户外媒体销售一个「改一个滑杆，当天出提案」的本地工作台——真实红豆库存、可解释选点、可交互地图、可追溯报价。

---

## 这个项目解决什么

销售做一份户外投放提案，现实是：人工查红豆库存 → 凭经验定线路/折扣 → 手工拼 PPT，一套流程好几天。客户当天要方案，单子就被竞对拿走。

本项目把「查库存—定组合—算报价—出方案」压成一个本地可跑的确定性工具：

- 输入：乐园场馆（乐高/迪士尼/海昌）、预算 100–500 万、公交/地铁、2027 档期、直客/4A。
- 输出：完整的可交互 HTML 提案（客户模式）+ 内部工作台（地图/表格/排期/报价/校验）+ 静态单文件导出。
- 现场：评委改预算/换场馆/换媒体，250ms 防抖后重新求解，地图与方案联动。

**边界**：这是曝光覆盖工具，不是转化归因工具；是确定性决策工具，不是生成式文案工具；是本地销售工作台，不是运营后台。

---

## 目录结构

```
AIPlusWork/
├─ engine/                  # 乐园优化引擎（Python）
│  ├─ models.py             # 冻结的请求/错误模型（Lead）
│  ├─ data_loader.py        # 红豆库存加载/去重/过滤/min_free
│  ├─ candidates.py         # 候选富化：价格/曝光/场馆亲和/POI/圈层
│  ├─ solver/               # CP-SAT 主模型 + HiGHS/贪心兜底
│  ├─ finance.py            # 折扣不动点 + 报价 + 逐行分摊
│  ├─ effects.py            # Reach/Frequency/CPM/九档弹性
│  ├─ schedule.py           # 夜间施工批次/雨备/监测 SLA/误一补二
│  ├─ validator.py          # 独立校验（不 import solver）
│  ├─ explanations.py       # 假设书七要素/选点理由/反事实
│  ├─ ai/                   # 离线 brief 解析/策略检索/narrator（可选 LLM）
│  └─ orchestrator.py       # 唯一入口 generate_plan()
├─ agent/                   # 需求分析 Agent（技能驱动 + 工具调用 + 可选 DeepSeek）
│  ├─ runtime.py            # 有界状态机：intake → strategy → analysis → narrative
│  ├─ intake.py             # brief → 可计算请求 + 问题 + 假设
│  ├─ strategy.py           # 场景设计：预算下探/上探/拐点/媒体组合
│  ├─ tools.py              # plan/elasticity/catalog/compliance 工具
│  ├─ analyzer.py           # 指标派生/风险/评分/推荐
│  ├─ narrator.py           # 确定性话术 + 数字守卫 + 合规守卫
│  ├─ llm.py                # 可选 DeepSeek 适配器（无 Key 自动回退）
│  ├─ skills.py             # 技能加载器（SKILL.md + policy.json + references）
│  └─ cli.py                # 命令行入口
├─ Our-agent-skills/        # Agent 技能包（4 个 stage + policy + references）
├─ server/                  # 本地 API（FastAPI + 标准库兜底）
├─ web/                     # React + Vite + Tailwind + ECharts 工作台
│  ├─ src/fixtures/         # 冻结的 PlanResponse fixture
│  └─ public/geo/           # 本地上海区县 GeoJSON（无在线瓦片）
├─ data/
│  ├─ snapshots/            # 红豆 2027 月度库存 CSV（只读快照）
│  ├─ processed/            # manifest / candidates / candidates.geo
│  ├─ config/               # 场馆档案/刊例/折扣/排期规则
│  └─ geo/                  # POI/站点坐标/区县（构建期缓存）
├─ docs/                    # 赛题资料 + 契约 + 任务拆分 + 说明书
│  ├─ 任务拆分.md            # 执行清单（先拆分后执行）
│  ├─ 契约-v1.md             # 前后端/引擎唯一契约
│  ├─ 模型说明书.md          # 输入/输出/中间流程/公式/局限
│  ├─ campaign假设书.md      # 七要素一页纸
│  └─ 一页纸说明.md          # 团队/AI/数据/局限
├─ scripts/                 # 红豆抓取/数据构建/审计/确定性/矩阵
├─ .claude/skills/          # Claude Code 技能（hongdou-inventory 红豆库存、xinyun-bigdata 大数据平台）
├─ prototypes/              # 早期原型（保留作对比）
├─ start.ps1                # 生产模式：API + web/dist，端口 8010
├─ start-dev.ps1            # 开发模式：API(8010) + Vite(5173)
└─ test.ps1                 # 引擎测试 + 前端类型检查/构建 + API smoke
```

---

## 环境

- Windows 11 + PowerShell
- Python **3.14.6**：`C:/Users/20614/AppData/Local/Python/pythoncore-3.14-64/python.exe`
  > ⚠️ 本机 `python` 是 Windows Store 别名桩，直接调用会静默失败；请用完整路径或下方 `.venv`。
- Node 24 / npm 11 / pnpm
- 已装 Python 依赖：`ortools`、`scipy`、`pandas`、`numpy`、`fastapi`、`uvicorn`、`pydantic`、`PyYAML`、`pytest`、`httpx`

## 安装

```powershell
# 1) Python venv + 依赖
uv venv .venv --python "C:/Users/20614/AppData/Local/Python/pythoncore-3.14-64/python.exe"
uv pip install --python .venv\Scripts\python.exe -r requirements.txt

# 2) 前端
pnpm --dir web install
pnpm --dir web build          # 生产模式静态文件 web/dist
# 可选：pnpm --dir web export  # 单文件提案导出 web/dist-export/index.html（build:export 为别名）
# 注入真实方案：.venv\Scripts\python.exe scripts\build_export.py
```

## 运行

### 生产模式（推荐演示）

```powershell
.\start.ps1
```

- 本地 API + 静态站点：<http://127.0.0.1:8010>
- 端口 8000 被本机系统进程占用，项目统一使用 **8010**。

### 开发模式

```powershell
.\start-dev.ps1
```

- API：<http://127.0.0.1:8010>
- 前端：<http://127.0.0.1:5173>（Vite 代理 `/api` → 8010）

### 手动启动

```powershell
.venv\Scripts\python.exe -m uvicorn server.main:app --host 127.0.0.1 --port 8010
# 无 FastAPI 时：
.venv\Scripts\python.exe server\fallback_server.py --port 8010
```

## 测试

```powershell
.\test.ps1
# 或单独：
.venv\Scripts\python.exe -m pytest engine/tests server/tests -q
.venv\Scripts\python.exe scripts\check_determinism.py --runs 3
.venv\Scripts\python.exe scripts\matrix_check.py --budgets 100,200,500 --media bus,metro,both
pnpm --dir web typecheck
pnpm --dir web build
pnpm --dir web exec playwright test
```

## 验收状态（2026-11-21）

| 项 | 结果 |
|---|---|
| 引擎 + 服务单测 | 37 passed |
| 三场馆 × 三预算 × 三媒体 | 27/27 组合 OK |
| 确定性 | 3/3 次完全一致（除 meta 时间） |
| 前端构建/类型 | 通过（dist ~1.56MB JS / 500KB gzip） |
| Playwright fixture E2E | 5/5 passed |
| Live E2E（8010 真实引擎） | 换场馆/滑杆 200/弹性 9 行/地图抽屉/锁定/客户提案，console error 0 |
| 单文件导出 | 9/9 档 feasible；3.42MB；`file://` 断网可切档；无凭证/外部 CDN |
| 数据 | manifest `f786985a2947`；6,972 库存记录；1,256 候选；POI 103；地铁坐标 275 |

> 详细结果与已知问题见 `docs/测试报告.md`；模型口径见 `docs/模型说明书.md`。

## 数据更新（红豆只读快照）

```powershell
# 凭证：scripts/.credentials（已 gitignore）或环境变量 HONGDOU_USER/HONGDOU_PASS
$env:PYTHONIOENCODING='utf-8'
.venv\Scripts\python.exe scripts\fetch_hongdou.py --start 2027-07-01 --end 2027-07-31 --out data\snapshots
.venv\Scripts\python.exe scripts\fetch_hongdou.py --start 2027-08-01 --end 2027-08-31 --out data\snapshots
.venv\Scripts\python.exe scripts\build_dataset.py
.venv\Scripts\python.exe scripts\validate_dataset.py
```

> 库存以红豆 API 快照为准；静态台账 `free=2517` 是 2026-11 快照，不可当作当前库存。页面会显示 `inventory_ts` 与 `inventory_periods`。

> 也可以直接用 Claude Code 技能包 `.claude/skills/hongdou-inventory/`：`SKILL.md` 记录 OAuth2/库存接口与数据口径，`scripts/auth.py|fetch.py|snapshot.py|analyze.py` 供 agent 调用；`fetch.py` 默认写 `data/hongdou/`，`snapshot.py` 默认写 `data/snapshots/`。

---

## API 摘要

| 方法/路径 | 作用 |
|---|---|
| `GET /api/health` | 引擎/数据/求解器状态 |
| `GET /api/meta` | 场馆/媒体/日期/费率/默认请求/manifest |
| `POST /api/plan` | 单方案 PlanResponse |
| `POST /api/plans/batch` | 100/200/500 对比 |
| `POST /api/elasticity` | 九档预算弹性 |
| `POST /api/export` | 单文件 HTML 提案 |
| `GET /api/data/manifest` | 数据审计 |
| `POST /api/agent/analyze` | Agent 需求分析（brief → 场景 → 结论 + 话术） |
| `GET /api/agent/skills` | Agent 技能清单与校验结果 |

详细字段见 `docs/契约-v1.md`。

---

## Agent 需求分析（新增）

把「客户一句话 brief」变成「可计算请求 + 场景对比 + 可追溯结论 + 提案话术」。

```
brief
  ↓
① brief-intake      接需求：抽槽位、提问、假设、合规扫描
  ↓
② audience-strategy 想策略：预算下探/上探/拐点/媒体组合（当前引擎没有四个策略参数）
  ↓
③ plan-analysis     算方案：调 generate_plan / generate_elasticity，读真实字段做比较
  ↓
④ proposal-narrative 说人话：每个数字带口径，主动说预算使用率与代价
  ↓
AgentAnalysis JSON + Markdown 提案
```

- **AI 不做算术**：报价/库存/Reach 全部来自 `engine`；LLM 输出要过数字守卫。
- **技能是数据**：`Our-agent-skills/*/SKILL.md` + `policy.json` + `references/`。
- **缺失不编**：必填字段缺失时提问；允许默认值时必须逐条列 assumption。
- **可选 DeepSeek**：根目录 `.env` 或环境变量没有 `DEEPSEEK_API_KEY` 时自动回退规则；默认模型 `deepseek-chat`。

```powershell
# 一句话 brief（允许默认值，列出假设）
.venv\Scripts\python.exe -m agent.cli --brief "客户是上海乐高乐园，预算200万，暑期8周，公交+地铁，要覆盖亲子家庭" --allow-defaults

# 严格模式：缺字段就提问
.venv\Scripts\python.exe -m agent.cli --brief "预算200万，做个乐园提案"

# 技能清单 / 校验
.venv\Scripts\python.exe -m agent.cli --skills
```

> DeepSeek 是可选增强：在根目录 `.env` 设置 `DEEPSEEK_API_KEY`（或设环境变量）后自动启用（默认模型 `deepseek-chat`）；
> 不设置则完全走规则，不影响分析结果。架构详见 `docs/Agent架构与技能说明.md`。

Agent 架构与技能格式详见 `docs/Agent架构与技能说明.md`；技能包说明见 `Our-agent-skills/README.md`。

---

## 模型与口径（详见 `docs/模型说明书.md`）

- **组合优化**：OR-Tools CP-SAT；公交整数车辆、地铁 0/1 出入口；预算/库存/媒介配比/等级/线路数/施工产能/锁定排除/区域覆盖。
- **确定性**：单线程、固定 seed、整数缩放；同输入必同输出（meta 时间除外）。
- **折扣**：按全单刊例总额落档 88/83/78/73/68%，最多 5 轮不动点；赠媒 5%；4A 15%。
- **效果**：`Reach = cap × (1 − exp(−GRP/k_eff))`；公交+地铁合并用单一饱和曲线，**不把两者到达率相加**。
- **排期**：夜间 23:00–05:00；公交 20 辆/晚、地铁 10 口/晚；2 个雨备夜；误一补二；监测 SLA。
- **降级**：CP-SAT → HiGHS → 确定性贪心；库存与预算约束绝不放松。

## 比赛要求对应

| 赛题要求 | 本实现 |
|---|---|
| 基于红豆真实可售库存 | 2027 月度快照；页面显示校验时间戳/档期；过滤封闭口/未知等级 |
| 大数据可视化平台 | 区县/POI/场馆圈/地铁点/公交线地图（本地 GeoJSON，离线可用）；后续可接可视化平台导出 |
| 给定行业+预算产出可交互 HTML | 本地工作台 + 客户提案模式 + 静态单文件导出 |
| 100–500 万可伸缩 | 单一引擎连续预算；九档弹性；100/200/500 对比 |
| 评委现场改输入当场出结果 | 250ms 防抖重解；换场馆/媒体/档期/锁定全联动；不白屏 |
| Campaign 假设书 | `docs/campaign假设书.md`；七要素 H1–H7；方案逐项回链 |
| 一页纸说明 | `docs/一页纸说明.md` |

## 已知局限

- 曝光/Reach/Frequency/CPM 为估算，不是实测；目标人群为策划假设。
- 折扣门槛、地铁等级语义为待确认假设；页面与说明书标注。
- POI（103 个）与地铁/公交几何为公开近似/区县示意；不用于测量级结论；POI 目标 112+，已知差 9 个。
- 九档弹性为同一优化器的 deterministic greedy 扩展估值，主方案为 CP-SAT；两者共享库存/配比/预算规则，数值可能不同。
- 库存是快照，档期占用会变化；演示前需核对。
- 不做转化归因；不承诺到园人数/销量/收益。
- 端口 8000 被本机系统进程占用，项目统一使用 8010。

## 第三方与许可

- UI 模板：shadcn-admin (MIT) — 见 `web/THIRD_PARTY_LICENSES.md`
- 图表/地图：Apache ECharts (Apache-2.0)
- 求解器：Google OR-Tools (Apache-2.0)
- 地图数据：如使用 OSM，遵循 © OpenStreetMap contributors / ODbL；页面标注来源与近似声明。
- 单文件导出：vite-plugin-singlefile (MIT)

## 文档索引

- `docs/任务拆分.md` — 执行清单与验收矩阵
- `docs/契约-v1.md` — 请求/响应/错误/图表字段
- `docs/模型说明书.md` — 模型输入/输出/流程/公式/局限
- `docs/campaign假设书.md` — 七要素一页纸
- `docs/一页纸说明.md` — 团队/AI/数据/局限
- `docs/PRD.md` — PM 原始 PRD（设计意图）
- `docs/模型选型与Agent工作流方案.md` — 选型调研
