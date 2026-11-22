# 方案线路真实几何 · Agent 取数与可视化契约

> 日期：2026-11-22 ｜ 范围：后端 / Agent / 数据 skill；前端改动由前端 agent 负责。
> 一句话：引擎选出公交线路后，Agent 调 `xinyun-bigdata` 的 **AI线路** 批量取 GeoJSON，注入 `PlanResponse` 地图层，并提供 GeoJSON 端点给高德地图画 Polyline。

---

## 1. 工作流（ProposalRunner 固定顺序）

```
brief
  ↓
intake              需求解析（结构化优先）
  ↓
data_inventory      红豆快照（2027 库存）
  ↓
data_bigdata        新云补充：场馆周边覆盖 / POI（2023-05，可选）
  ↓
engine              CP-SAT 生成 PlanResponse（plan.bus[].line 是线路名，如 136）
  ↓
data_routes         ★ 新增：按方案线路名调 xinyun AI线路 批量取真实几何
  ↓
visualize           把几何注入 map_layers.bus_routes[]，输出 GeoJSON 端点
  ↓
narrative → done
```

- 取数只在**引擎成功**后发生；失败/无会话不阻塞方案，显式标记 `skipped/degraded`。
- 新云数据只有 **2023-05 轨迹快照**；线路几何只用于地图可视化，**不进入报价、库存、Reach/评分**。
- Agent 只用只读脚本；不调用 `/baseInfoWeb/saveWeb`、不调用 `ai_share.mjs`。

## 2. Agent 调用链

```
agent/orchestration.py::ProposalRunner
  └─ agent/data_skills.py::DataSkillRuntime.bigdata_routes(lines)
       └─ node .claude/skills/xinyun-bigdata/scripts/ai_route_batch.mjs
            --lines "136,157,17" --out data/external/platform/queries
```

- `lines` 来自 `PlanResponse.plan.bus[].line`，去重后按行分摊金额排序，默认最多 40 条（可配 `routes_max_lines`，上限 60）。
- 缓存：`data/external/platform/queries/ai_line_<lineId>.geojson`（与 `ai_route.mjs` 共用），默认 30 天 TTL；**全部命中时不启动浏览器**。
- 会话过期：`ai_route_batch.mjs --check` 通过 `apiRequest` 探测 `/baseInfoLine/getTreeLine`，返回 302→`/login` 时标记 `MANUAL_LOGIN_REQUIRED`；后端据此跳过 coverage/POI 页面脚本，避免白等 Playwright。
- 手动登录一次：`node .claude/skills/xinyun-bigdata/scripts/login.mjs`（人工过验证码）。未登录时仍可用已有缓存出图。

## 3. 运行结果字段（`GET /api/proposals/{run_id}`）

### 3.1 `data.routes`（摘要，无坐标）

```json
{
  "data": {
    "routes": {
      "status": "degraded",
      "reason": "MANUAL_LOGIN_REQUIRED",
      "source": "新云传媒大数据可视化平台 · AI线路（2023-05 轨迹快照）",
      "data_month": "202305",
      "fetched_at": "2026-11-22T01:20:00.000Z",
      "summary": { "requested": 23, "resolved": 1, "cached": 1, "fetched": 0, "missing": 22 },
      "lines": [{ "line": "1001", "lineName": "1001路", "lineId": 9871, "points": 384, "items": ["bus:1001:大三侧"] }],
      "missing": [{ "line": "136", "reason": "MANUAL_LOGIN_REQUIRED" }],
      "geojson_url": "/api/proposals/<run_id>/routes.geojson",
      "note": "仅用于可视化；不参与报价/库存/评分。平台数据只有 2023-05，线路为近似轨迹。"
    }
  }
}
```

`status`：`ready`（全部命中）/ `degraded`（部分命中或部分失败）/ `skipped`（无会话且无缓存）。
`missing[].reason`：`MANUAL_LOGIN_REQUIRED` / `NOT_FOUND` / `EMPTY_GEOMETRY` / `CACHED_ONLY` 等。

### 3.2 `plan.coverage.map_layers.bus_routes[]`（坐标在这里）

```json
{
  "line": "136",
  "lineName": "136路",
  "lineId": 9900,
  "items": ["bus:136:大三侧"],
  "geometry": {
    "type": "line",
    "path": [[121.40, 31.20], [121.41, 31.21]],
    "points": 2,
    "simplified": false
  },
  "bbox": [121.40, 31.20, 121.41, 31.21],
  "source": "新云传媒大数据可视化平台 · AI线路（2023-05 轨迹快照）",
  "data_month": "202305",
  "confidence": "approx",
  "fetched_at": "2026-11-22T01:20:00.000Z"
}
```

- **坐标系**：平台原始字段 `{lng:<纬度>, lat:<经度>}` 已在脚本内交换为 GeoJSON `[经度, 纬度]`（WGS84 近似）；高德绘制前仍需 `wgsToGcj`。
- `path.points` 超过 600 时等距抽稀，`simplified=true`（保留首尾；只影响展示）。
- `map_layers.bus_routes` 缺失/为空：前端应按区县示意，不画假轨迹。
- 同层还提供：
  - `map_layers.bus_routes_meta`：`{source, data_month, status, reason, fetched_at, note}`
  - `map_layers.bus[].route_ref`：线路名（如 `136`）
  - `map_layers.bus[].route_status`：`ready` / `missing` / `unavailable`
  - `plan.bus[].route_ref` / `plan.bus[].route_status`：表格/抽屉联动

## 4. API

### 4.1 `GET /api/proposals/{run_id}/routes.geojson`

返回合并后的标准 GeoJSON `FeatureCollection`，每个线路一个 `LineString`；如 `run` 未完成或没有几何，返回空 `features` 并在 `meta` 里给出 `status/reason/missing`。

```json
{
  "type": "FeatureCollection",
  "features": [{
    "type": "Feature",
    "properties": { "line": "136", "lineName": "136路", "lineId": 9900, "items": ["bus:136:大三侧"], "points": 2, "source": "...", "data_month": "202305", "confidence": "approx" },
    "geometry": { "type": "LineString", "coordinates": [[121.40, 31.20], [121.41, 31.21]] }
  }],
  "meta": { "run_id": "...", "status": "ready", "source": "...", "data_month": "202305", "disclaimer": "平台只有 2023-05 轨迹快照…", "missing": [] }
}
```

### 4.2 `POST /api/routes`

给输入页 `/api/plan` 的即时地图用：不创建 run，按线路名取缓存/平台几何。

```http
POST /api/routes
{"lines":["136","157"],"force":false,"max_lines":40}
```

- 返回 `lines[]`（含 `path`）与 `features[]`（GeoJSON）；`status` 语义同上。
- 只读；无会话且无缓存 → `status=skipped`, `reason=MANUAL_LOGIN_REQUIRED`，HTTP 200。
- 参数校验：`lines` 非空、最多 60 条；否则 422。

## 5. 前端接入（高德，media 页建议改法）

> 后端本轮**没有修改 `web/`**。以下为前端 agent 的最小接入建议；页面读取的 `plan` 是 `run.plan`（PlanResponse），因此路径是 `plan.coverage.map_layers.bus_routes`。

```ts
// media.astro drawMap() 内，地铁 marker 之后
const routes = (PLAN.coverage?.map_layers?.bus_routes || []) as any[];
const routeLines: any[] = [];
for (const r of routes) {
  const path = (r.geometry?.path || []).map(([lng, lat]: number[]) => wgsToGcj(lng, lat));
  if (path.length < 2) continue;
  const line = new AMap.Polyline({
    path,
    strokeColor: '#2e5b44',
    strokeWeight: 4,
    strokeOpacity: 0.85,
    lineJoin: 'round',
    lineCap: 'round',
    zIndex: 120,
    cursor: 'pointer',
  });
  line.on('click', () => openRouteDrawer(r)); // 可选：线路名/点位/来源/2023-05
  map.add(line);
  routeLines.push(line);
}
// fitView 时把 routeLines 的 path 一起纳入
```

- 图层开关：在“图层与筛选”加一个 `data-layer="routes"` 复选框；关闭时 `map.remove(routeLines)`。
- 静态兜底（`StaticMap`）：可只画入选地铁点/场馆；线路缺失时不要伪造。
- 数据口径标签：`新云 AI线路 · 2023-05 · 近似轨迹`；`route_status !== 'ready'` 的线路在表格/抽屉显示“区县示意”。
- 若希望输入页预览也显示线路：方案生成后用 `/api/plan` 的 `plan.bus[].line` 去重，调 `POST /api/routes`；结果里的 `features` 直接画。

## 6. 状态与降级（必须显式）

| 场景 | `data.routes.status` | 页面建议 |
|---|---|---|
| 会话有效，全部命中 | `ready` | 画真实线路 |
| 部分线路平台不存在/几何为空 | `degraded` + `missing[]` | 命中画线，缺失按区县示意 |
| 无会话（验证码未过）且无缓存 | `skipped` + `MANUAL_LOGIN_REQUIRED` | 显示“补充线路需人工登录一次”，不阻塞方案 |
| 全部命中缓存 | `ready`（`summary.cached`） | 正常画线；标注 2023-05 |
| 引擎失败 | 无 `data_routes` 阶段 | 不生成结果页 |

## 7. 验证

```powershell
# Python 单测 + mock 平台集成（不需要真实会话）
.venv\Scripts\python.exe -m pytest agent/tests/test_routes.py agent/tests/test_xinyun_routes_script.py -q

# 会话探测（不会开浏览器）
node .claude\skills\xinyun-bigdata\scripts\ai_route_batch.mjs --check

# 真实批量取线路（需先人工 login.mjs 过验证码）
node .claude\skills\xinyun-bigdata\scripts\ai_route_batch.mjs --lines "136,157,17"
```

## 8. 已知限制

- 平台数据只有 **2023-05**；线路轨迹为当时快照，不能证明 2027 实际走向。
- 几何是公开/平台近似，不用于测量级结论；报价/库存/Reach 与几何无关。
- 平台线路树可能缺少红豆中的线路（如新开/区间线）；缺失必须按区县示意展示。
- 会话需要人工验证码，不绕过、不自动打码；`ai_share.mjs` 是写操作，自动流程禁用。

## 9. 地铁线路（2026-11-22 补齐）

平台线路树确实包含 **「地铁线路」分组（25 个节点：地铁1–19号线及 5/10/11 等分支）**，AI线路支持地铁几何，无需另做一套地铁图。

- `ai_route_batch.mjs` 现在支持地铁线路名：`--lines "地铁1号线,地铁11号线"`。地铁线路按前缀匹配带分支的节点（如 `地铁11号线(嘉定北)` / `(花桥)`）；同名多分支当前稳定取 `lineId` 最小的一条（11 号线取嘉定北），缓存同样按前缀复用。
- 编排从 `plan.metro[]` 解析线路号：`evidence/reasons` 里的 `L01/L09/L11`、显式 `line` 字段、本地 `data/geo/_shmetro_stations_by_name.json` 的 `LINE_NO`；写入 `coverage.map_layers.metro_routes[]`（字段同 `bus_routes`，并带 `media:"metro"`；`items` 是选中地铁口 id），同时写 `metro_routes_meta`。
- `data.routes.lines[]` 每条带 `media:"bus|metro"`，`missing[]` 也带 media；`GET /api/proposals/{run_id}/routes.geojson` 合并公交+地铁 FeatureCollection。
- 前端 `media.astro` 已支持：公交实线 `#2e5b44`、地铁虚线 `#a8794a`，选点圆点、悬停线路名、点击抽屉、图层开关；缺失几何仍按区县示意。
- 验证 run **`c20c490c4492`**：32 条公交 + 6 条地铁（1/2/8/9/11/18），38/38 ready，`/result/media.html?run=c20c490c4492`。
- 边界：平台只有 2023-05 快照；11 号线分支取嘉定北；线路几何不进入报价/库存/Reach/评分。
