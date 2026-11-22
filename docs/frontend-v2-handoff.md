# 前端 v2 交接与执行清单（上下文压缩版）

> 日期：2026-11-22 ｜ 范围：只重做前端，不改业务代码；桌面端；不打印任何密钥/凭证。
> 本轮目标：主页 + 用户输入页（可视化 + Agent 交流）+ 多个结果页；两个数据 skill 进入 Agent 体系并自动取数；同一批数据经确定性引擎估价，再用高德 SDK 可视化。

## 0. 已核实的现状（不要盲信旧说明）

- Astro 多页：`web/src/pages/` 现有 index/product/map/cases/collaboration/about/privacy/terms/credits 共 9 页；`web/astro.config.mjs` 为 `build.format:"file"`，链接必须写 `*.html`（如 `/input.html`、`/result/overview.html`），不要写 `/input`。
- Agent 运行时存在：`agent/runtime.py::ProposalAgent.run`（intake → base plan → elasticity → scenarios → recommend → narrative）；`agent/skills.py::SkillRegistry` 只加载 `Our-agent-skills/`，要求每个 skill 有 `SKILL.md`、`policy.json`、唯一 `stage`/`order`；当前 `/api/agent/skills` 只有 4 个 stage skill。
- 两个数据 skill 真实路径：`.claude/skills/hongdou-inventory/`、`.claude/skills/xinyun-bigdata/`。它们没有 `stage/order/policy.json`，因此**当前不会被 ProposalAgent 加载**；只能被 Claude Code 直接调用。
- 服务端已有 `/api/health`、`/api/meta`、`/api/plan`、`/api/plans/batch`、`/api/elasticity`、`/api/agent/analyze`、`/api/agent/skills`；`/api/export` 只存在于 README/契约文字，`server/main.py` 未注册，不要依赖。
- 前端目前只调用 `/api/plan` 和静态 fixture；没有 Agent 交流，也没有把 Agent/技能结果带到结果页。
- 现有花哨与裁切证据：`web/src/components/Nav.astro`、`Footer.astro`、`product.astro` 多处重复“生成投放方案”；`.taste-skill/gate.json` 已记录 `action-repeat`（nav+hero）、`fade-cut`（“44 / 44”被渐隐）、`section-air`、`card-layout` 等；`product.astro` 的 `rows = ...slice(0,8)` 但文案写“前 12 条”；`web/src/styles/site.css` 多处 `height:420px/500px + overflow:hidden`（`.ps-map-window__body`、`#network .ps-map-card`、`#features .panel`），容易裁切。

## A. 目标信息架构（1 主页 + 1 输入页 + 4 结果页）

| URL | 源文件 | 内容块（从上到下） | 业务依据 |
|---|---|---|---|
| `/index.html` | `web/src/pages/index.astro` | 极简页头；H1「乐园投放提案工作台」；一句真实能力（红豆库存→确定性引擎→高德地图）；唯一主按钮「生成投放方案」；三步说明（输入→Agent 取数→四页方案）；一行数据口径；可选“最近一次方案”文字链接。无照片、无滚动动效、无统计条、无 FAQ。 | PRD §2.1/§8；一页纸说明 §2 |
| `/input.html` | `web/src/pages/input.astro`（新） | 双栏：左侧表单（场馆/预算/媒体/档期/周数/客户类型 + 高级锁定）+ Agent 对话（消息、槽位、假设、问题 chips、合规提示）；右侧高德预览（场馆+圈层+地铁口+POI，可选 xinyun 周边覆盖）+ 数据状态（红豆快照时间戳/数据版本、xinyun 会话/2023-05、缓存）；底部唯一主按钮「生成方案」+ 阶段时间线。 | PRD §4.0–4.4；契约 §1–§2；演示脚本 0:30–2:15 |
| `/result/overview.html` | `web/src/pages/result/overview.astro`（新） | 运行状态条（run_id、data_version、inventory_ts、solver、degraded 标记）；H1（场馆+预算+档期）；4 个 KPI；H1–H7 假设书；一句话策略/人群/交通/媒介角色；媒体配比小条形图 + 小地图；四个结果页 tabs；口径与局限摘要。 | PRD §4.1；campaign 假设书 H1–H7；契约 §2.3–§2.6；模型说明书 §3；演示脚本 0:30–1:30 |
| `/result/media.html` | `web/src/pages/result/media.astro`（新） | 全屏高德地图（场馆/圈层/入选地铁口/POI 命中/区县边界；公交只按区县示意）；图层与等级筛选；公交/地铁点位表（分页，默认 20 行）；点击抽屉（可售、评分分解、理由、证据、替代项）；POI 命中与区县配比。 | PRD §4.2–4.4；campaign H4/H6；契约 §2.6/§2.11/§2.13；数据审计 §3–§5；演示脚本 1:30–2:15、3:00–3:45 |
| `/result/economics.html` | `web/src/pages/result/economics.astro`（新） | 报价瀑布（刊例→折扣→折后媒体费→制作→4A→总价）；逐行分摊核对；赠媒；预算使用率/余量；排期 Gantt + 批次表 + 夜间产能/雨备/监测 SLA/误一补二。 | PRD §4.5–4.6；campaign H5；契约 §2.8–§2.10；模型说明书 §5.5/§5.7/§5.8；演示脚本 2:15–3:45 |
| `/result/effects.html` | `web/src/pages/result/effects.astro`（新） | 效果 KPI（曝光/GRP/Reach/Frequency/CPM）+ 分媒体归因；弹性双轴图 + 九档表；validator 的 blocker/warning/10 条自检；已知局限；数据版本/快照时间戳/来源；Agent+数据阶段时间线；折叠的“数据来源与许可”。 | PRD §4.7–4.9；campaign H7 与预算弹性；契约 §2.7/§2.8/§2.12/§2.14；模型说明书 §5.6/§6/§10；一页纸说明 §3–4；数据审计 |

**必须删除/停用的页面与装饰：**
- 删除页面：`web/src/pages/product.astro`、`map.astro`、`cases.astro`、`collaboration.astro`、`about.astro`、`privacy.astro`、`terms.astro`、`credits.astro`。旧的 `/product.html#demo`、`/map.html`、`/cases.html` 链接全部改到 `/input.html` 或对应结果页；不保留跳转壳页。
- 导航：`Nav.astro` 删除五栏 mega menu、图片卡片、右侧“生成投放方案”按钮；只留 logo、主页、输入页/最近方案；结果页用 `ResultTabs`（Overview/Media/Economics/Effects）并保留 `?run=`。
- 页脚：`Footer.astro` 删除大 CTA、四列链接、隐私/条款/图片来源链接；只留一行数据来源、估算声明、当前 run 的 `data_version`/`inventory_ts`。
- 资源/装饰：停止引用 `web/public/assets/moments/**`、`backgrounds/**`、`motion/**`、`diagrams/**`、`web/public/assets/img/photo-*.webp` 营销照片；`Base.astro` 删除 `moments` prop、背景/动效/layout/diagram 脚本与 Google Fonts 外链；保留必要基础 CSS、图标与 `StaticMap.astro`（仅无 Key/加载失败兜底）。
- 代码：`web/src/scripts/demo.ts`、`map.ts` 被新 `input.ts`、`result.ts`、`amap.ts` 取代；`web/src/data/fixtures/*.json` 只保留“无服务端演示兜底”，不再作为页面营销内容来源。

## B. Agent + 两个数据 skill 的接入方案

### B.1 两个 skill 的真实能力与依赖

| skill | 脚本与认证 | 输出/写盘 | 自动调用限制 |
|---|---|---|---|
| `hongdou-inventory` | `.claude/skills/hongdou-inventory/scripts/{auth,fetch,snapshot,analyze}.py`、`hongdou_lib.py`；OAuth2 密码模式，token 实测 1799 秒，缓存 `.oauth_cache.json` 可 refresh；**无验证码**；凭证来自 `HONGDOU_USER/HONGDOU_PASS` 或 `scripts/.credentials`。 | `fetch.py`→`data/hongdou/*.csv`；`snapshot.py`→`data/snapshots/{bus,metro}_YYYY-MM-01_YYYY-MM-last.csv`；stdout JSON，进度 stderr；只读。 | 可按目标月份自动抓；无凭证/401 时降级；不要把 `fetch.py` 的筛选结果放进 `data/snapshots`。 |
| `xinyun-bigdata` | `.claude/skills/xinyun-bigdata/scripts/*.mjs`；Playwright 已装；首次 `login.mjs` 打开可见 Chrome，**人工输入验证码一次**，会话存 `data/external/platform_storage.json`；平台数据只有 `202305`，覆盖接口无日期参数。 | 组合/覆盖/地址/条件→JSON/XLS/CSV；AI 线路→GeoJSON；`ai_share.mjs` 会创建平台方案并授权分享（写操作）。 | 仅当会话有效时自动调用只读脚本；验证码不可绕过；自动流程禁用 `ai_share`、禁用全量网格/大规模条件查询；2023-05 只能作为补充，不可混入 2027 库存/报价。 |

### B.2 注册进 Agent 体系（适配层，不复制脚本）

- 在 `Our-agent-skills/` 新增两个薄适配 skill（脚本仍指向 `.claude/skills/...`，避免双份实现）：
  - `Our-agent-skills/data-inventory/SKILL.md`：`name: data-inventory`、`stage: data_inventory`、`order: 15`、`tools: [inventory.status, inventory.snapshot, inventory.analyze]`、`outputs: [inventory-summary, data-version, warnings]`；`policy.json` 放可抓月份白名单、TTL、超时、凭证名、`allow_overwrite`、失败策略。
  - `Our-agent-skills/data-bigdata/SKILL.md`：`name: data-bigdata`、`stage: data_bigdata`、`order: 16`、`tools: [bigdata.coverage, bigdata.poi, bigdata.routes]`、`outputs: [coverage-context, poi-context, route-geometry, warnings]`；`policy.json` 放只读命令白名单（含 `ai_route_batch.mjs`）、`data_month:"202305"`、手动登录标记、`allow_share:false`、半径/POI 类型/线路条数白名单、缓存 TTL。`compare` 本轮未接入。
  - 同步 `Our-agent-skills/skills-manifest.json`；`SkillRegistry` 会自动发现，`/api/agent/skills` 会列出 6 个 skill。两个新 `stage` 不冲突现有 4 个 stage。
- 新增 `agent/data_skills.py::DataSkillRuntime`：用 `subprocess.run`（绝对路径、`shell=False`、UTF-8、超时、单飞锁）调用上述脚本；只解析 stdout JSON，stderr 只入日志摘要；对 token/password/security code 做脱敏；参数白名单；禁用 `ai_share` 等写操作，只保留查询脚本自身的本地文件输出。
- 新增 `agent/orchestration.py::ProposalRunner`（或扩展 `ProposalAgent.run`）：固定顺序 `INTAKE → DATA(INVENTORY) → DATA(BIGDATA) → STRATEGY/ANALYSIS → VISUALIZE → NARRATIVE → DONE`；数据阶段通过 `event_sink` 发事件，不改变现有 `/api/agent/analyze` 的同步返回契约。
- 现有 `agent/runtime.py` 的 base plan 在数据阶段之后执行；`ToolRuntime` 仍只调用 `engine.orchestrator.generate_plan/ generate_elasticity`，数据脚本不得直接算价格/库存。

### B.3 编排 API（新增，旧接口保留）

```
POST /api/proposals
{"brief_text":"...","request":{"industry":"乐园","venue":"lego_shanghai","budget_wan":500,
 "media":["bus","metro"],"start_date":"2027-07-01","weeks":8,"customer_type":"direct",
 "locks":{"include":[],"exclude":[]}},
 "options":{"data_mode":"auto","include_elasticity":true,"include_plan_artifacts":true,
            "auto_refresh_hours":24,"allow_defaults":true}}
→ 202 {"run_id":"...","status":"queued","events_url":"/api/proposals/{id}/events"}
```
- `GET /api/proposals/{run_id}` → `{run_id,status,created_at,inputs,brief,agent,data,plan,stages,warnings}`；`status ∈ queued|running|needs_input|done|degraded|failed`；`plan` 为完整 `PlanResponse`；`data` 只含摘要/路径/时间戳/脱敏状态，绝不含 token。
- `GET /api/proposals/{run_id}/events` SSE：`{"seq","stage","status","at","ms","summary","data_version","warnings"}`；阶段为 `intake,data_inventory,data_bigdata,engine,data_routes,visualize,narrative,done`；前端断线可退化为 500ms 轮询。
- 旧接口：`/api/agent/analyze` 用于“快速理解需求”（输入页要显式传 `options.allow_defaults=false` 才显示问题；`server/core.py::agent_analyze` 在未传该键时默认 true）；`/api/plan` 保留给引擎单跑/调试；`/api/elasticity` 保留给结果页按需刷新。

### B.4 失败与降级（必须显式，不伪造）

| 场景 | 行为 | 页面表现 |
|---|---|---|
| 无红豆凭证/401 | `data_inventory: degraded`；缓存快照完整则继续算；目标月缺失则 `needs_input` + `DATA_UNAVAILABLE`，不静默换月 | 右上“库存未刷新·使用缓存快照”+ 时间戳；缺月显示可执行建议 |
| 红豆抓取超时/部分页 | 退避重试 1 次；失败则保留旧文件（原子写临时文件再改名），不把半份 CSV 当完整库存 | `degraded`，`X-Data-Version` 不变；建议重试 |
| xinyun 无会话/验证码未过 | `data_bigdata: skipped`，`reason=MANUAL_LOGIN_REQUIRED`；不阻塞引擎 | 显示“补充图层需人工登录一次”说明，不弹自动登录、不绕过 |
| xinyun 超时/2023-05 为空 | `data_bigdata: degraded`；地图只用本地图层 | 标注“2023-05 补充数据不可用” |
| 引擎 `INFEASIBLE/LOCK_CONFLICT` | 返回 409，不生成结果页 | 显示错误契约的 suggestions，保留输入页 |
| skill 校验失败/子进程异常 | 500 + `request_id`；不返回半成品 | 修正 `agent/skills.py` 清单；可重试 |
| 数据刷新与求解并发 | 单飞锁；刷新期间旧 run 仍可读；完成后统一 `data_version` 失效缓存 | 状态条显示“数据刷新中”，不白屏 |

### B.5 数据进入引擎与重载（重要事实）

- 红豆 `snapshot.py` 写 `data/snapshots/*.csv`；`engine/data_loader.py::load_inventory` **直接扫描这些 CSV**（不是读 `data/processed/*.json`），按月去重、取 `min_free`、过滤封闭/未知等级，并用源文件内容算 `data_version`。
- 刷新后必须：`engine.orchestrator.reload_data()` 清方案缓存；当前实现**未清 `_ELASTICITY_CACHE`**，v2 需扩展 `reload_data()` 同时清它；再调 `engine.candidates.reload_geo()` 清 POI/地铁坐标缓存。`engine/data_loader.reload_data()` 是 no-op，不要依赖。
- `scripts/build_dataset.py` / `scripts/build_enriched.py` 生成 `data/processed` 审计资产（注意：`build_dataset.py` 本身不写 `candidates_enriched.json`，由 `build_enriched.py` 写；引擎运行时不读这些 JSON）。`scripts/validate_dataset.py` 做对账；`scripts/build_web_data.py` 生成前端 fixture/地图资产。它们不等于“让引擎生效”；真正生效的是 snapshot + 清缓存。
- 确定性：同一请求 + 同一 `data_version`，除 `meta.generated_at/request_id/solve_ms/total_ms/cache_hit` 外必须一致；缓存键含 `data_version`；九档弹性按场馆/媒体/档期缓存，刷新后也要清。
- **边界**：只有红豆库存/配置进入求解器；xinyun 返回的人群画像/覆盖/AI 线路是 Agent 解释与可视化上下文，不能直接改 2027 报价/库存数字。若要把 xinyun 数据用于评分，属于模型改造+重标定，本轮明确不做。

## C. 前端数据流与可视化

- 输入页默认值：`GET /api/meta`（`venues/date_options/budget_range/default_request/discount_tiers/manifest`）；字段校验按 `docs/契约-v1.md §1`：预算 100–500、媒体至少 1 项、日期只选已抓月份、周数 2/4/6/8/12、客户类型 direct/4a。
- Agent 交流：用户可写一句话 brief；点“理解需求”调 `POST /api/agent/analyze`（`options.allow_defaults:false` 优先，缺字段返回 `questions`），渲染 `brief.slots/assumptions/questions/compliance_flags`；点击问题 chip 回填表单。不做开放式多轮自治聊天；把对话文本累积为最终 `brief_text`。
- 生成：唯一主按钮调 `POST /api/proposals`（同步返回 202 也可以，推荐 SSE）；`needs_input` 留在输入页；`done/degraded` 把 `run_id` 写入 `localStorage.lastRunId` 后跳 `/result/overview.html?run=<id>`；失败按错误契约展示，不跳转。
- 持久化（最稳妥）：服务端 `data/runs/<run_id>.json` + 内存 LRU；结果页 URL 只带 `run_id`；`localStorage` 只存表单草稿和 `lastRunId`，不存整份 PlanResponse（体积/过期/一致性）。服务重启后从磁盘读；文件不存在显示空态并链回 `/input.html`。
- 结果页读取：统一 `web/src/scripts/result.ts`，从 `location.search` 取 `run`，`GET /api/proposals/{id}`，按 `data-result-view` 渲染；四个 tabs 共用同一 run，不能各自再调 `/api/plan`，否则“同一批数据”不成立。
- 高德：共享 `web/src/scripts/amap.ts`，Key/security code 只从 `web/.env` 构建注入，不写日志。输入页图层：场馆+圈层、全部地铁口（背景）、POI、可选 xinyun 周边覆盖；结果 overview 小地图、media 全屏地图：场馆/圈层、入选地铁口、POI 命中、区县边界、选中点抽屉；公交只做区县/清单示意，绝不画假轨迹。无 Key/加载失败保留 `StaticMap.astro` 静态兜底并标注来源。
- 图表：overview 媒体配比条形；economics 报价瀑布 + Gantt；effects 双轴弹性 + 九档表 + 校验矩阵。所有数字直接来自 run payload，前端不算钱/库存。

## D. 桌面端验收与 taste 审查清单

### D.1 命令（在 `D:\Cacimodo\Projects\AIPlusWork\web` 下执行）

```powershell
$TASTE = "C:\Users\20614\.claude\skills\design-taste-frontend"
pnpm --dir web build
# 六个页面：index / input / result/overview / result/media / result/economics / result/effects
node "$TASTE\scripts\copy-lint.mjs" dist/index.html --kind software
node "$TASTE\scripts\consistency.mjs" dist/index.html --widths 1440,1280 --rhythm-widths 1440,1280 --profile .taste-skill/chrome-v2 --page software --category "户外媒体 AI 提案工作台" --primary "生成投放方案"
node "$TASTE\assets\layout\check.mjs" --url dist/index.html --root dist --profile .taste-skill/chrome-v2 --sizes 1440x900,1280x800 --shots shots/v2
node "$TASTE\scripts\shoot.mjs" --url dist/index.html --w 1440 --out shots/v2/1440-index.png --profile .taste-skill/chrome-v2
node "$TASTE\scripts\perf.mjs" dist/index.html --profile .taste-skill/chrome-v2
node "$TASTE\scripts\gate.mjs" --start dist/index.html --root dist --new --kind software --category "户外媒体 AI 提案工作台" --primary "生成投放方案"
node "$TASTE\scripts\gate.mjs" dist/index.html --root dist
```
- 对六个页面逐页跑 `copy-lint`、`consistency`、`check`、`shoot`、`perf`；`gate` 至少覆盖 index + input + overview + media（其余页面用 consistency 兜底）。`gate` 会强制检查 1440/390/320：本项目不做手机端，**1440 必须零 FAIL**；390/320 的纯移动问题记录为范围豁免，不为手机重做布局。
- taste 优化在结构完成后再跑一轮；只允许 CJK 36 字压力测试类 waiver（`.taste-skill/waivers.json` 写理由）；裁切、`action-repeat`、`overflow-x`、重复按钮一律不得豁免。

### D.2 1440 验收清单

- 语法/构建：`pnpm --dir web build` 成功；所有 `.astro`/`.ts` import 存在；`/api` 代理在 dev 可用。
- 裁切：1440×900 与 1280×800 全页截图；`document.documentElement.scrollWidth <= clientWidth`；任何含文字/数字的卡片不得 `height + overflow:hidden`；表格默认 20 行/页，超出显示“共 N 条”+ 分页；不再出现“前 12 条实际 8 条”这类文案；不使用渐隐盖住最后一行。
- 重复按钮：同屏同 label 只出现 1 次（taste `action-repeat` 为零）；导航不放主 CTA，页脚不放主 CTA；输入页只有底部一个「生成方案」；结果页用 tabs 导航，另只保留一个“修改输入”次要链接；“刷新数据”作为文字操作并二次确认。
- 链接：所有内部链接指向已构建的 `*.html`；`?run=` 在四个结果 tabs 间保留；无 `/product.html`、`/map.html`、`/cases.html`、`/collaboration.html`、`/about.html` 残留；无死锚点 `#demo`；无外部 Google Fonts/图片 CDN。
- 控制台：应用 `console.error` = 0；`/data/*`、`/assets/*` 无 404；AMap 无 Key/失败时只出现预期 warning 且静态兜底可见；网络请求中无 token/密码/security code 出现在前端日志。
- 密度：每屏最多 4 个 KPI；正文 16px、行高 ≥1.6；地图高度 ≥560px；左右栏间距一致；长中文标签换行不省略关键数字；详情用抽屉/折叠，不压缩进固定高度。
- 性能：暖请求方案 <350ms（冷启动按模型说明书 ~1.7s）；滑杆/切换保留旧结果，显示“重算中”；图片/地图资源懒加载；`perf.mjs` 无 FAIL。

## E. 需要用户确认/提供的项，以及明确不做

**需要确认/提供：**
1. 确认页面删减：是否同意删除 product/map/cases/collaboration/about/privacy/terms/credits；来源/许可/局限是否只放结果页折叠块与页脚一行。
2. 高德：`web/.env` 已有 Key；确认演示环境可联网、Key 配额足够；是否需要更换为企业 Key。文档/日志不输出 Key 字节。
3. 红豆：确认 `scripts/.credentials` 或环境变量可用；确认允许 `snapshot.py` 抓取/覆盖哪些月份（建议只 2027-06..10；默认 2027-07/08）；确认演示前是否强制刷新。
4. 新云：确认演示前可人工完成一次 `login.mjs` 验证码登录；确认 2023-05 数据只作补充；确认禁用 `ai_share` 等写操作。
5. 交互：Agent 交流是否接受“结构化表单 + 一句话 brief + 问题 chips”的有界方式（当前 runtime 不支持开放式多轮）；若要多轮自由聊天，需新增会话记忆与安全边界。
6. 结果页：确认 4 个结果页划分（Overview/Media/Economics/Effects）及默认场景（乐高 500 万 / 2027-07-01 / 8 周 / 直客）。
7. 数据：确认“红豆库存进入 engine；xinyun 只做策略/可视化上下文”的边界；若要求 xinyun 参与评分，需单独立项重标定。

**明确不做：**
- 不做手机端/平板专属布局；390/320 只记录为范围豁免。
- 不做产品/地图/案例/协作/关于/隐私/条款/来源独立页；不做营销大图、3D、滚动编排、渐变网格、装饰性动效。
- 不做单文件离线导出（`/api/export` 已移除）；不恢复旧 `dist-export`。
- 不绕过验证码、不自动分享 xinyun AI 线路、不批量拉平台全量网格/标签。
- 不让 LLM 产出预算/库存/报价/曝光数字；不把 2023-05 数据混入 2027 库存或报价；任何缺失/降级必须显式标注。

## F. 并行接入：方案线路真实几何（2026-11-22 后端会话，供前端 agent）

> 后端已完成，**未修改 web/**；契约与可直接粘贴的 AMap 片段见 `docs/route-geometry-api.md`，协作留言见 `.agents/notes/2026-11-22-routes-visualization.md`。

- **红豆阶段改为强制实时拉取**：`ProposalRunner` 每次都调 `snapshot.py --overwrite --media all` 覆盖 `data/snapshots` 后 `reload_data()`；`options.data_mode=cached` 不再跳过库存。实测 2 个月（公交+地铁各一次 API）约 90 秒，完整提案约 2 分钟，不是 bug。
- `run.plan.coverage.map_layers.bus_routes[]`：`{line, lineName, lineId, items[], geometry:{type:"line", path:[[lng,lat],...], points, simplified}, source, data_month:"202305", confidence:"approx"}`。
- `map_layers.bus[].route_ref / route_status`、`plan.bus[].route_ref / route_status`；`run.data.routes` 是摘要。
- 新端点：`GET /api/proposals/{run_id}/routes.geojson`；`POST /api/routes {"lines":[...]}`（给输入页即时地图）。
- 时间线新增阶段 `data_routes`（engine 之后、visualize 之前），未知阶段请容错。
- `media.astro` 的 `drawMap()` 按 `bus_routes` 画 `AMap.Polyline`，坐标先 `wgsToGcj`；缺失线路不画假轨迹；加“公交线路”图层开关。
- 新云已人工登录成功；**最新线上 API run：`497884c2163a`**（重启后的 8010；请求故意传 `data_mode=cached`；红豆 4 份快照全 `ok`；23/23 条公交线路 ready；`status=done`，115 秒）；`/result/media.html?run=497884c2163a`。
- 另一个强制拉取样本：`98769e60eafa`（32/32 条；实时库存变化会让线路数在 23/32 之间变化，前端不要写死）；改造前样本：`1ce41e83348c`；降级样本：`cc9eb1e4a9c0`。
- 新端点 `GET /api/proposals/{run_id}/routes.geojson` 与 `POST /api/routes` 需要重启 8010 加载新代码；结果页现有 fixture 没有 `bus_routes` 时应保持旧行为。

## G. 前端收尾记录（2026-11-22，桌面端）

> 用户确认：只做电脑端 1440/1280；390/320 不处理。

**已完成**
- 输入页：移除 `main > section` 的 100vh 营销节奏（原标题下约 800px 空白、表单/地图被推到第二屏）；主按钮移到首屏标题区（全页唯一），阶段时间线放左栏；表单/地图按 12 列共享分栏；地图 640px，AMap `complete` 前显示 StaticMap 兜底（文案「加载中 · 静态预览」）；覆盖月份、数据版本、库存时间、页脚版本从 `/api/meta.manifest` 回填；Agent 初始交流气泡；AMap logo/iframe 补 `alt`/`aria-label`/`title`，隐藏 iframe 移出 Tab 序；移除 Scale 与带文字的场馆 marker。
- 结果页：每页唯一 H1（overview 动态「场馆 · 预算 · 档期」；media/economics/effects 用页名）；effects 从 `run.elasticity` 取九档数据（图 + 表恢复）；media 按折后金额排序、POI 全列；overview 媒体配比可读；局限编号化；degraded 状态中文化；页脚由 Base 统一渲染并在结果加载后回填版本。
- 首页：示例数字与当前默认 run 对齐（32 条/39 辆、7,463.8 万、36.4、63.05 元），标注示例快照；页脚版本从 manifest 回填；字体改为系统可加载栈；补齐 og/twitter 分享元数据。
- 媒体线路图层：`media.astro` 读取 `run.plan.coverage.map_layers.bus_routes` + `metro_routes`，同时兼容通用 `routes`；WGS84→GCJ02 后画 `AMap.Polyline`（公交实线 `#2e5b44`，地铁虚线 `#a8794a`）。每条线路中点加一个方案选点圆点；悬停显示线路名/选点数，点击线路或圆点打开抽屉（线路、媒介、几何点数、方案选点、来源、2023-05、用途）。`data-layer="routes"` 开关；缺失/空几何不画假轨迹；fitView 用地铁点 + 线路 path 点，保持上海视角。面板显示「公交 N / 地铁 M 条有几何」；若后端未返回地铁几何则显式显示「地铁线路几何未返回（其余按区县示意）」。
- 联调：`c20c490c4492` 为 32 条公交 + 6 条地铁（1/2/8/9/11/18），38/38 条真实几何；`1ce41e83348c` 为 23 条公交；`cc9eb1e4a9c0` 为 1 条 + 缺失提示的降级样本。

**验证**
- `pytest engine/tests server/tests agent/tests`：**71 passed**（新增地铁线路映射/注入和公交+地铁 GeoJSON 合并测试）。
- `pnpm --dir web build`：6 页构建通过。
- 桌面截图：`web/shots/v2/final-*.png`、`web/shots/v2/final-metro-media-1440.png`、输入页 `web/shots/v2/final3-input-*.png`。
- `GATE: OPEN 1`：输入页 `hero-fold`（应用工作台需约 1.7 屏滚动）；5 条 waiver（AMap shader/webgl、工作台 hero、工具页脚、无装饰动效）+ 9 WARN 已记录；390/320 按用户指示不修。

**地铁线路后端已补齐（2026-11-22）**
- 平台线路树含「地铁线路」分组（25 个节点）；`ai_route_batch.mjs` 支持 `--lines "地铁1号线,地铁11号线"`，按前缀匹配 11 号线等分支（取 lineId 最小，当前嘉定北）。
- 编排从 `plan.metro[]` 的 `L01/L09/L11`、显式 line、本地站名表 LINE_NO 解析线路号，写入 `map_layers.metro_routes[]`（media="metro"，items=选中地铁口 id）；`data.routes.lines[].media` 与 `/routes.geojson` 均合并公交+地铁。
- 验证：`c20c490c4492` 的 6 条地铁几何全部返回（1/2/8/9/11/18）；`/result/media.html?run=c20c490c4492` 显示公交实线 + 地铁虚线 + 双图例。
- 边界：平台只有 2023-05 快照；11 号线取嘉定北分支；线路几何不参与报价/库存/Reach/评分。


## H. 模板化提案 PDF（2026-11-22）

- 来源：`docs/03-合同三份-脱敏版等9个文件` 的历史销售提案样本（FLAIR MEDIA 结构）+ 三份合同（直客/4A框架/4A订单）的签约要点。
- 生成器：`server/proposal_pdf.py`，A4 HTML 模板经本机 Chrome 打印；含封面、目录、项目理解、媒介地图+线路表、排期、报价、效果、合同要点、数据声明。
- 本地生成：`.venv\Scripts\python.exe -m server.proposal_pdf <run_id>`；缓存 `data/exports/proposals/<run_id>.pdf`，并复制到 `web/public/proposals`、`web/dist/proposals`。
- Overview 概览新增「下载提案 PDF」，链接 `/proposals/<run_id>.pdf`；当前 `c20c490c4492` 已生成（10 页 / 606 KB）。
- 新 run 懒生成路由 `GET /proposals/{run_id}.pdf` 已在 `server/main.py` 注册；重启 8010 后生效。未重启时先跑 CLI，静态文件链接同样可用。
- 合同路径：直客《户外媒体发布合同（直客）》；4A《4A 框架合同 + 4A 订单》。PDF 为提案阶段要点模板，正式条款以签署合同为准。
