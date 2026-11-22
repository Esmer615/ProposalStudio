# 提案编排 API（前端对接）

> 后端编排，不改变旧接口。前端每 500ms 轮询 GET 即可，无需 SSE 也能工作。

## POST /api/proposals

请求体：

```jsonc
{
  "brief_text": "一句话需求（可空）",
  "request": {
    "industry": "乐园",
    "venue": "lego_shanghai",        // lego_shanghai | disney_shanghai | haichang_shanghai
    "budget_wan": 500,                // 100–500
    "media": ["bus", "metro"],        // 至少一项
    "start_date": "2027-07-01",       // 只选已抓月份
    "weeks": 8,                       // 2/4/6/8/12
    "customer_type": "direct",        // direct | 4a
    "locks": {"include": [], "exclude": []}
  },
  "options": {
    "data_mode": "auto",              // 兼容字段；inventory 阶段现在总是实时拉取，cached 不再跳过
    "include_elasticity": true,
    "allow_defaults": true,
    "include_routes": true,           // 默认 true：引擎后调 xinyun AI线路取方案线路几何
    "routes_force": false,            // true 时忽略 30 天缓存重新取
    "routes_max_lines": 40            // 1–60，超出按行分摊金额截断
  }
}
```

响应 `202`：

```jsonc
{"run_id": "..", "status": "queued", "events_url": "/api/proposals/{run_id}/events"}
```

## GET /api/proposals/{run_id}

轮询直到 `status` 离开 `queued|running`。`status ∈ queued|running|needs_input|done|degraded|failed`。

```jsonc
{
  "run_id": "..",
  "status": "done",            // needs_input 时留在输入页，不回跳
  "created_at": "..", "finished_at": "..",
  "inputs": {"request": {...}, "brief_text": ".."},
  "agent": {
    "brief": {...},            // slots/questions/assumptions
    "stages": [{"stage":"intake","status":"done","summary":"..","ms":2}, ...],
    "messages": [], "questions": [], "assumptions": []
  },
  "data": {
    "inventory": {"status":"done|degraded","mode":"live","forced":true,"data_version":"..","months":["2027-07"]},
    "bigdata":  {"status":"ready|degraded|skipped","reason":"MANUAL_LOGIN_REQUIRED|null","data_month":"202305"},
    "routes":   {
      "status":"ready|degraded|skipped","reason":"MANUAL_LOGIN_REQUIRED|PARTIAL_ROUTES|null",
      "summary":{"requested":23,"resolved":1,"cached":1,"fetched":0,"missing":22},
      "lines":[{"line":"1001","lineName":"1001路","lineId":9871,"points":384,"items":["bus:1001:大三侧"]}],
      "missing":[{"line":"136","reason":"MANUAL_LOGIN_REQUIRED"}],
      "geojson_url":"/api/proposals/{run_id}/routes.geojson",
      "source":"新云传媒大数据可视化平台 · AI线路（2023-05 轨迹快照）"
    }
  },
  "plan": {
    /* 完整 PlanResponse（contract 契约）；新增：
       plan.coverage.map_layers.bus_routes[] = {line,lineName,lineId,items,geometry:{type:"line",path:[[lng,lat]],points,simplified},bbox,source,data_month,confidence}
       plan.coverage.map_layers.bus[].route_ref / route_status
       plan.bus[].route_ref / route_status */
  },
  "elasticity": { /* 九档弹性，或 null 当失败/未启用 */ },
  "warnings": [".."],
  "error": null
}
```

## GET /api/proposals/{run_id}/events

非流式事件视图（可选），返回 `{run_id, status, events:[{seq,stage,status,summary,ms,data_version,warnings}]}`。

## GET /api/proposals/{run_id}/routes.geojson

方案公交线路真实几何，标准 `FeatureCollection`（每线路一个 `LineString`，WGS84；高德绘制前转 GCJ02）。
`meta` 含 `run_id/status/reason/source/data_month/disclaimer/missing[]`；无几何时 `features=[]`，不是错误。

## POST /api/routes

输入页即时地图用：不创建 run，按线路名取缓存/实时几何。

```jsonc
// 请求
{"lines": ["136", "157"], "force": false, "max_lines": 40}
// 响应 200：{status, reason, summary, lines:[{line,lineName,lineId,points,path,bbox,status}], missing[], features:[GeoJSON Feature]}
```

- `lines` 非空、最多 60；否则 422。
- 无会话且无缓存 → 200 + `status=skipped, reason=MANUAL_LOGIN_REQUIRED`，不阻塞页面。

## 固定阶段

`intake → data_inventory → data_bigdata → engine → data_routes → visualize → narrative → done`

> `data_routes` 是新增阶段（引擎之后、可视化之前）；前端时间线请容错未知阶段名。

## 语义边界

- **每次提案都会强制实时拉取红豆**：`data_inventory` 调 `hongdou-inventory/scripts/snapshot.py --overwrite --media all`，覆盖 `data/snapshots` 后 `reload_data()`；`options.data_mode` 不再跳过库存。实测 2 个月约 90 秒（每月公交+地铁各一次 API），完整提案约 2 分钟。
- 只有红豆实时快照进入 `engine` 求解；xinyun（2023-05）只作解释/可视化上下文，不改报价/库存。
- 无红豆凭证/超时 → `inventory` 降级，旧快照仍可用；目标月缺失 → `needs_input` + `DATA_UNAVAILABLE`。
- 新云无会话/验证码 → `bigdata.status=skipped`、`reason=MANUAL_LOGIN_REQUIRED`，不阻塞引擎。
- 线路几何（`data.routes` / `map_layers.bus_routes`）只用于可视化；2023-05 轨迹，不进入报价/库存/Reach/评分。无会话/线路缺失时按区县示意，不画假轨迹；缓存命中仍可出图。
- 所有输出含数据时间戳/版本/来源；日志不含凭证/token/安全码。

## 旧接口保留

`/api/agent/analyze`（快速理解，`options.allow_defaults=false` 才显示问题）、`/api/plan`、`/api/elasticity`、`/api/meta`、`/api/agent/skills`。不恢复 `/api/export`。
