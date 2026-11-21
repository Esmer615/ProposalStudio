---
name: xinyun-bigdata
description: 使用新云传媒大数据可视化平台（flairmedia.com.cn:38880）的五个子模块获取数据：组合查询（某条公交/地铁线路的人群画像）、媒体覆盖查询（中心+半径周边线路/站点）、条件查询（2023-05 人群/区域筛选）、地址查询（地址/坐标+半径的媒体与 POI 计数）、AI线路（线路几何 GeoJSON / 站点坐标）。Use when the user asks for 大数据平台、组合查询、区域人流属性/区域人群画像、媒体覆盖分析、条件查询、定制查询/地址查询、AI线路. Requires a manual captcha login once.
---

# 新云大数据平台 Skill（五子模块）

> 平台：`https://flairmedia.com.cn:38880`（比赛测试账号）
> 数据月份：**只有 2023-05**（`dataMonth=202305`）；2023-07 返回空。
> 原则：人工过验证码一次 → 保存会话 → **按需查指定线路/中心** → 输出小结果（JSON/Excel/GeoJSON）。
> **不要全量拉取 2023-05 的网格/标签**。

---

## 0. 首次登录（只需一次人工验证码）

```powershell
cd D:\Cacimodo\Projects\AIPlusWork
node .claude\skills\xinyun-bigdata\scripts\login.mjs
```

- 会打开可见 Chrome，自动填 `scripts/.credentials` 里的账号密码，停在验证码输入框。
- 你输入验证码并点登录；脚本保存会话到 `data/external/platform_storage.json`（本地、gitignore）。
- **不绕过验证码、不用第三方打码**；会话过期时重跑本命令。

---

## 1. 子模块索引

| 菜单/页面 | 子模块 | 详细文档 | 选项发现（实时） | 查询脚本 | 一句话 |
|---|---|---|---|---|---|
| 组合查询 `/comparePage` | 组合查询 | [modules/compare.md](modules/compare.md) | `scripts/compare_options.mjs` | `scripts/compare.mjs` | 按一级/二级/三级标签查指定线路，取年龄/性别/房产/消费/手机/时段人流，可导出 Excel |
| 媒体覆盖分析 `/nearbyPoiLineQuery` | 媒体覆盖查询 | [modules/coverage.md](modules/coverage.md) | `scripts/coverage_options.mjs` | `scripts/coverage.mjs`（覆盖媒体）<br>`scripts/coverage_poi.mjs`（周边点位） | 中心+半径→周边公交线路/地铁站；或 POI 数量/明细 CSV（平台导出格式） |
| 条件查询 `/conditionQuery` | 条件查询 | [modules/condition.md](modules/condition.md) | `scripts/condition_options.mjs` | `scripts/condition.mjs` | 2023-05 人群/区域筛选→命中媒体→平台导出 Excel（建议小范围） |
| 定制查询 `/looseMultiQuery` | 地址查询 | [modules/address.md](modules/address.md) | `scripts/address_options.mjs` | `scripts/address.mjs` | 地址/坐标+半径→命中媒体→导出 Excel |
| AI线路 `/busLineShowSolution`、AI线路-站点 `/busLineShowSolutionStation` | AI线路 | [modules/ai-route.md](modules/ai-route.md) | `scripts/ai_route_options.mjs` | `scripts/ai_route.mjs`（只读）<br>`scripts/ai_share.mjs`（分享/导出） | 线路树/线路几何 GeoJSON；分享百度地图 HTML + 导出 xls |

> `scripts/query.mjs` 是组合查询的兼容别名，实际执行 `compare.mjs`。

## 1.1 每个模块的交互链路（固定顺序）

```
0. 选项发现（实时）   *_options.mjs      → 拿一级/二级/三级标签、条件项、半径、POI 类型、线路树
1. 选值              （agent 从输出里选） → 传给查询脚本的参数
2. 查询              *_mjs              → 调平台接口，返回 JSON/摘要/导出文件
3. 输出/导出         同脚本 --export → Excel / JSON / GeoJSON
```

- **不预拉全量选项**；`*_options.mjs` 每次都向平台实时查，输出只打印当前需要的选项/匹配项。
- 条件查询只导出 Excel（不落 grids/labels）；地址/覆盖/AI 输出小 JSON/GeoJSON；组合查询可 `--export` 生成 Excel。
- 每个模块 MD 的 **第 0 节** 都有“选项发现”的实测命令与输出。

## 1.2 查询后的数据获取与可视化

| 模块 | 数据文件 | 平台导出/分享 | 可视化 |
|---|---|---|---|
| 组合查询 | `compare_<ids>_<date>.json`（8 指标原始值） | `--export` → `.xls`（`/exportIndicatorData`→`/downloadExcel`） | 平台右侧人群画像/人流属性（ECharts）；无分享链接 |
| 媒体覆盖 | `coverage_<中心>_<半径>.json` + `.csv` | 平台“导出分析结果” | 覆盖结果 CSV；点位地图在平台页面直接查看，不导出截图 |
| 周边点位 | `coverage_poi_<中心>_<半径>_<count|detail>.csv`（平台“导出点位”同格式） | 平台“导出点位”（前端 CSV，无服务端接口） | 直接打开 CSV；平台页面直接查看，不导出截图 |
| 条件查询 | `大数据洞察_条件查询_<condition>_<date>.xls`（命中媒体的汇总指标） | 脚本内建导出：`/exportIndicatorData`→`/downloadExcel`（与组合查询同一链路） | 直接打开 Excel；平台页面可看网格图；不导出截图 |
| 地址查询 | `大数据洞察_地址查询_<中心>_<半径>_<日期>.xls`（命中媒体的汇总指标） | 脚本内建导出：`/exportIndicatorData`→`/downloadExcel`（与组合查询同一链路） | 直接打开 Excel；平台页面可看地图/属性，不导出截图 |
| AI线路 | `ai_line_<id>.geojson` | **`ai_share.mjs`：保存→授权→分享链接 + 导出 xls** | 官方百度地图 HTML，**外部无登录可看** |

> AI线路分享是唯一官方“可分享可视化”链路，已实现并验证；其他模块平台没有分享按钮，用 CSV/JSON/平台导出，**不做截图导出**（避免把平台界面信息带到本地）。

---

## 2. 快速开始（每个模块一个已验证示例）

### 2.1 组合查询：公交 01路/1001/1002

```powershell
# 0) 发现选项
node .claude\skills\xinyun-bigdata\scripts\compare_options.mjs --first
node .claude\skills\xinyun-bigdata\scripts\compare_options.mjs --first 公交
node .claude\skills\xinyun-bigdata\scripts\compare_options.mjs --first 公交 --keyword 1001

# 1) 查询 + 导出
node .claude\skills\xinyun-bigdata\scripts\compare.mjs `
  --media 公交 --labels "01路,1001,1002" --date 202305 --export
```

已实测：`01路=6382`、`1001=6000`、`1002=6001`；20岁以下 0.84%；男性 53.96%/女性 46.04%；房产 23/64/9/4%；手机 Top OPPO/三星；输出 JSON + 34KB Excel。
详见 [modules/compare.md](modules/compare.md)。

### 2.2 媒体覆盖查询：乐高 1000m

```powershell
# 0) 发现选项（模式/半径/POI 类型）
node .claude\skills\xinyun-bigdata\scripts\coverage_options.mjs

# 1a) 覆盖媒体：中心+半径→线路/站点
node .claude\skills\xinyun-bigdata\scripts\coverage.mjs --address "上海乐高乐园" --radius 1000

# 1b) 周边点位：POI 数量/明细
node .claude\skills\xinyun-bigdata\scripts\coverage_poi.mjs --address "上海乐高乐园" --radius 1000 --types "商场,幼儿园" --mode count
node .claude\skills\xinyun-bigdata\scripts\coverage_poi.mjs --address "上海乐高乐园" --radius 1000 --types "商场" --mode detail
```

已实测：平台 geocode 中心 1000m 内 **2 条公交 / 0 地铁**（1675路 384m、枫泾七路 997m）；周边点位 商场 1 / 幼儿园 0，CSV 与平台“导出点位”同格式。
详见 [modules/coverage.md](modules/coverage.md)。

### 2.3 条件查询：徐家汇商圈 + 20岁以下 / 1万以下（小范围）

```powershell
# 0) 发现条件项（17=徐家汇商圈；53–56=20岁以下的收入档）
node .claude\skills\xinyun-bigdata\scripts\condition_options.mjs --type 人群属性 --subtype 年龄属性

# 1) 小范围查询并导出 Excel（默认就是 17,53）
node .claude\skills\xinyun-bigdata\scripts\condition.mjs --condition "17,53"
```

已实测：查询约 **3 秒**，命中 **11 个媒体**，导出 `大数据洞察_条件查询_17_53_202305.xls`（41,984 字节；导出另需数秒）。
脚本只把命中的媒体用于导出，**不保存 grids/labels**。
详见 [modules/condition.md](modules/condition.md)。

### 2.4 地址查询：乐高 1000m

```powershell
# 0) 发现选项（范围/红豆线路/POI 类型）
node .claude\skills\xinyun-bigdata\scripts\address_options.mjs

# 1) 地址查询并导出 Excel
node .claude\skills\xinyun-bigdata\scripts\address.mjs --address "上海乐高乐园" --radius 1000
```

已实测：乐高 1000m 命中 1 个媒体；导出 `大数据洞察_地址查询_上海乐高乐园_1000_202305.xls`（32,768 字节）。
脚本只保存 `.xls`，不保存 labels/sop JSON/CSV。
详见 [modules/address.md](modules/address.md)。

### 2.5 AI线路：1001路几何

```powershell
# 0) 发现线路树/搜索节点
node .claude\skills\xinyun-bigdata\scripts\ai_route_options.mjs --tree line
node .claude\skills\xinyun-bigdata\scripts\ai_route_options.mjs --tree line --search 1001

# 1) 读取线路几何（只读）
node .claude\skills\xinyun-bigdata\scripts\ai_route.mjs --line 1001

# 2) 分享/导出（写操作：创建历史方案 + 授权外部访问 1 个月；用户明确要求分享时用）
node .claude\skills\xinyun-bigdata\scripts\ai_share.mjs --line 1001 --remark "skill share test"
# → SHARE_URL: https://flairmedia.com.cn:38880/busLineShow?webId=<id>
# → 外部无登录已验证可打开；同时导出 xls（不做截图）
```

已实测：匹配 `1001路`（lineId=9871），输出 GeoJSON 线形；`--station 人民广场` 可读站点坐标。
详见 [modules/ai-route.md](modules/ai-route.md)。

---

## 3. 平台接口速查

| 能力 | 接口 |
|---|---|
| 标签解析 | `POST /label/queryThirdLabel`（`firstLabel`，`secondLabel` 空=全部） |
| 组合查询指标 | `POST /bbf8e41e454b47126290905525c69f7`（`queryType=1, indicatorType, dataMonth=202305, labelIds, gridIds=, extOptions`） |
| 导出 Excel | 先加载 `/infoPage`，`POST /exportIndicatorData` → `GET /downloadExcel` |
| 地理编码 | `POST /nearby/geocode`（JSON `{address, city:"上海市"}`） |
| 媒体覆盖 | `POST /baseInfoLine/matchCoverLines`（JSON `{radius, mediaTypes, lineScope, centers}`） |
| 条件查询 | `POST /label/queryLabelByQueryCondition`（`queryCondition, dataMonth`）；取命中媒体后走 `POST /exportIndicatorData` → `GET /downloadExcel`（与组合查询同一导出链路） |
| 地址查询 | `POST /label/queryLabelByBorder`（`numStr, border, dataMonth, isHD`）；取命中媒体后走 `POST /exportIndicatorData` → `GET /downloadExcel`（与组合查询同一导出链路） |
| 周边点位导出 | 前端 CSV（`exportPoiResult()` → `downloadCsv`）；无服务端接口 |
| AI线路树 | `GET /baseInfoLine/getTreeLine`、`GET /baseInfoLine/getTreeLine?type=station` |
| 线路几何 | `GET /baseInfoLine/getLineJson?linePath=...` |

> 混淆接口若平台改版，请检查 `/js/busi/info/infoPage.js` 的 `getData` 并更新 `scripts/lib.mjs` 的 `DATA_URL`。

---

## 4. 安全与数据约束

- 只使用比赛发放的测试账号，只读；不批量拉全量网格/标签。
- 不绕过验证码、不用第三方打码；人工登录一次。
- 账号密码只在 `scripts/.credentials`（gitignore）；不打印、不写入 skill、不提交。
- 会话文件 `data/external/platform_storage.json` 只在本地；过期重登。
- 平台数据只有 **2023-05**；覆盖分析接口无日期参数，按当前轨迹快照解释，不要与 2023-05 人群数据混口径。
- AI线路只读；不要自动调用 `/baseInfoWeb/saveWeb`（会创建平台方案）。

---

## 5. 工具调研结论（GitHub / 插件市场）

- 最贴合的是 **Playwright / Playwright MCP / Chrome DevTools MCP** 这类真实浏览器会话工具；本 skill 在 `scripts/package.json` 里独立安装 Playwright（不依赖 `web/node_modules`），人工登录后复用 `JSESSIONID`。
- 通用 Chrome 抓取插件（Web Scraper / Instant Data Scraper / Data Miner）只能抓表格/DOM，抓不到右侧 ECharts 图表和平台 XHR JSON；不作为主方案。
- 安装：在 `.claude/skills/xinyun-bigdata/scripts` 执行 `npm install`（已装 Playwright 1.65.1）；浏览器优先系统 Chrome，其次 Edge，最后内置 Chromium。若希望在对话里实时点页面，可另装 Playwright MCP（`npx @playwright/mcp@latest`）。

---

## 6. 排错

| 现象 | 处理 |
|---|---|
| 400 “plain HTTP request sent to HTTPS port” | nginx 误跳 http；脚本已自动改回 https |
| 401/跳登录 | 会话过期，重跑 `login.mjs` |
| 标签找不到 | 用完整 `thirdLabel`/`ext1`（如 `01路`、`1001`）；脚本会列候选 |
| 导出失败（405/网络错误） | 先加载 `/infoPage`；`lib.mjs::exportIndicators` 已处理；条件查询请用小范围，避免超大 gridIds |
| 条件查询全量太慢/失败 | 用商圈/行政区 + 人群条件缩小范围（例：`--condition "17,53"`） |
| 条件查询 2023-07 为空 | 平台只有 2023-05 |
| 数据全 0/空 | 该线路在 2023-05 无数据，或选错标签/站 |
| 浏览器打不开 | `lib.mjs` 会依次尝试 Chrome → Edge → 内置 Chromium；都失败时在 `scripts` 目录执行 `npx playwright install chromium` |

---

## 7. 文件

```
.claude/skills/xinyun-bigdata/
├─ SKILL.md
├─ modules/
│  ├─ compare.md
│  ├─ coverage.md
│  ├─ condition.md
│  ├─ address.md
│  └─ ai-route.md
└─ scripts/
   ├─ lib.mjs                 # 会话/HTTP/标签/指标/导出/几何/地理编码/POI类型
   ├─ login.mjs               # 人工验证码登录
   ├─ compare_options.mjs     # 组合查询：一/二/三级标签实时发现
   ├─ compare.mjs             # 组合查询（query.mjs 为兼容别名）
   ├─ coverage_options.mjs    # 覆盖：模式/半径/POI类型实时发现
   ├─ coverage.mjs            # 覆盖媒体
   ├─ coverage_poi.mjs        # 周边点位（count/detail；平台格式 CSV）
   ├─ condition_options.mjs   # 条件项实时发现
   ├─ condition.mjs           # 条件查询（小范围命中媒体→导出 Excel）
   ├─ address_options.mjs     # 地址查询选项（范围/isHD/POI类型）
   ├─ address.mjs             # 地址查询（命中媒体→导出 Excel）
   ├─ ai_route_options.mjs    # 线路/站点树发现
   ├─ ai_route.mjs            # AI线路/AI线路-站点（只读几何）
   └─ ai_share.mjs            # AI线路：保存→授权→分享链接+导出（写操作）
```
