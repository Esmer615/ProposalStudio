# To 前端 agent：方案线路真实几何已接入（后端）

> 2026-11-22 ｜ 发起：后端/Agent 会话 ｜ 不修改 `web/`，避免和你并行冲突。
> 详细契约：`docs/route-geometry-api.md`

## 已完成的接口

1. `POST /api/proposals` 跑完后，`run.plan.coverage.map_layers` 新增：
   - `bus_routes[]`：`{line, lineName, lineId, items[], geometry:{type:"line", path:[[lng,lat],...], points, simplified}, bbox, source, data_month:"202305", confidence:"approx"}`
   - `bus_routes_meta`：`{status, reason, source, data_month, fetched_at, note}`
   - `map_layers.bus[].route_ref` / `route_status`（`ready|missing|unavailable`）
   - `plan.bus[].route_ref` / `route_status`
2. `run.data.routes`：摘要（`status, reason, summary, lines[], missing[], geojson_url`），无坐标。
3. `GET /api/proposals/{run_id}/routes.geojson`：合并 `FeatureCollection`，可直接 `fetch().json()`。
4. `POST /api/routes`：`{"lines":["136","157"]}` → 不建 run 的缓存/实时取数，适合输入页 `/api/plan` 后画线。
5. 时间线新增阶段 `data_routes`（在 `engine` 与 `visualize` 之间）；未知阶段请容错渲染。

## 请前端做的（建议最小改动）

- `web/src/pages/result/media.astro`：在 `drawMap()` 里按 `PLAN.coverage.map_layers.bus_routes` 画 `AMap.Polyline`；
  坐标先 `wgsToGcj(lng,lat)`；加“公交线路”图层开关；缺失线路不画假轨迹。
- 可选：`overview` 小地图也画（同一字段）；`media` 表格/抽屉显示 `route_status`。
- 状态条可加 `run.data.routes.status`（`ready/degraded/skipped`）；`skipped` 时提示“补充线路需人工登录一次”。
- 文档第 5 节有可直接粘的 TS 片段。

## 当前测试状态（重要）

- **工作流已改为强制实时拉取**：`ProposalRunner` 每次都调 `hongdou-inventory snapshot.py --overwrite --media all`，忽略 `data_mode=cached`；随后 xinyun 覆盖/POI 实时查，方案线路几何走 AI线路（30 天缓存）。
- 人工验证码登录已完成，会话有效。
- **最新线上 API run：`497884c2163a`**（重启后的 8010；请求里故意传 `data_mode=cached`；红豆 4 份快照全部 `ok`；23/23 条公交线路 ready；`status=done`，耗时 115 秒）。
  - 访问：`/result/media.html?run=497884c2163a`。
- 另一个强制拉取样本：`98769e60eafa`（同一套新代码，32/32 条 BUS 线路；说明实时库存变化会让线路数变化，前端不要写死 32/23）。
- 上一个样本：`1ce41e83348c`（23/23 条 ready，强制拉取改造前）。
- 降级样本：`cc9eb1e4a9c0`（仅 1001 有几何），用于测试 `missing/unavailable` 展示。
- 时间成本：强制拉取 2 个月（公交+地铁各一次 API）约 90 秒；完整提案约 2 分钟。`data_mode=cached` 不再省这一步。
- 后端测试：`pytest agent/tests engine/tests server/tests -q`（68 passed）。
- 8010 需要重启才能加载“强制拉取”新代码；重启后会立即对下一次 `/api/proposals` 生效。

## 冲突边界

- 后端只改了：`agent/{data_skills,orchestration,contracts}.py`、`server/{core,main}.py`、`.claude/skills/xinyun-bigdata/scripts/{lib.mjs,ai_route_batch.mjs}`、测试与文档。
- **没有改** `web/`、`web/dist`、fixtures、`data/runs` 的既有文件。
- 需要重启 8010 的 API 进程才能看到新字段（当前运行的是旧代码）；前端 dev 热更新不受影响。
