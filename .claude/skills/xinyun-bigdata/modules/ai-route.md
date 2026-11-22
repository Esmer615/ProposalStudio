# 子模块 5：AI线路 / AI线路-站点

> 页面：`https://flairmedia.com.cn:38880/busLineShowSolution`（AI线路）
> 页面：`https://flairmedia.com.cn:38880/busLineShowSolutionStation`（AI线路-站点）
> 脚本：`scripts/ai_route.mjs`
> 用途：读取线路树与线路几何（GeoJSON），可替换“区县示意”的真实线形。
> **只读**：不调用 `/baseInfoWeb/saveWeb`，不创建/修改平台方案。

## 0. 先实时发现选项（线路/站点树）

```powershell
# 线路树顶层分组
node .claude\skills\xinyun-bigdata\scripts\ai_route_options.mjs --tree line
# → 12 个分组（新云-最新1225 / 新云-都市观光 / 新高度 / 水陆通 / DG-0520 / …）

# 搜索线路
node .claude\skills\xinyun-bigdata\scripts\ai_route_options.mjs --tree line --search 1001
# → 1001路  lineId=9871  linePath=D:\SOP\media-res\JSON\1001路

# 搜索站点（AI线路-站点）
node .claude\skills\xinyun-bigdata\scripts\ai_route_options.mjs --tree station --search 人民广场
```

> 选项来自 `/baseInfoLine/getTreeLine`（线路）或 `?type=station`（站点）实时树；不预拉全量节点。

## UI 路径

1. 顶部菜单 **AI线路**。
2. 搜索线路（如 `1001`），勾选线路。
3. 页面会画出线路；如需保存/生成在线 HTML，平台有 **保存** 按钮（本 skill 不自动点击，避免写入）。
4. **AI线路-站点**：同样的树，但节点是站点（`staName` / `staLocaltion`）。

## 脚本

```powershell
cd D:\Cacimodo\Projects\AIPlusWork

# 线路几何
node .claude\skills\xinyun-bigdata\scripts\ai_route.mjs --line 1001

# 站点坐标（可选）
node .claude\skills\xinyun-bigdata\scripts\ai_route.mjs --station 人民广场
```

参数：

| 参数 | 说明 |
|---|---|
| `--line` | 线路名，如 `1001`（自动匹配 `1001路`） |
| `--station` | 站名，如 `人民广场` |
| `--out` | 输出目录；默认 `data/external/platform/queries` |

## 接口

```http
GET /baseInfoLine/getTreeLine
→ {"code":..,"data":[ {name:"S",children:[{lineId:9871,lineName:"1001路",linePath:"D:\\SOP\\media-res\\JSON\\1001路",...}]}]}

GET /baseInfoLine/getLineJson?linePath=<encodeURIComponent(linePath)>
→ {"code":0,"data":"{\"path\":[{\"lng\":31.11,\"lat\":121.58},...]}"}

GET /baseInfoLine/getTreeLine?type=station
→ 站点树（staName / staLocaltion）
```

- **坐标交换**：`getLineJson` 返回的 `path` 点实际是 `{lng:<latitude>, lat:<longitude>}`（平台 JS 用 `new BMap.Point(mobile[i].lat, mobile[i].lng)`）；脚本已纠正为 GeoJSON 的 `[lng, lat]`。
- `linePath` 是平台服务器路径；URL 编码后传给 `getLineJson`。

## 已验证示例

`--line 1001`：

```
线路: 1001路 (lineId=9871)
几何点: 384
bbox: lng 121.577691..121.593946 / lat 31.112367..31.129428
GeoJSON: data/external/platform/queries/ai_line_9871.geojson
```

输出 GeoJSON `FeatureCollection`，可用于替换网站地图上的区县示意线。

## 分享链接 + 导出 + 可视化（重点）

平台历史记录里的“授权访问/复制链接”就是官方百度地图 HTML。脚本 `ai_share.mjs` 已实现：

```powershell
node .claude\skills\xinyun-bigdata\scripts\ai_share.mjs --line 1001 --remark "skill share test"
```

实测输出：

```
SAVE 200 {"msg":"数据保存成功！...","code":200,"data":{"id":"1321666885934125056","showName":"test16_2026_11_21_235326","state":"1",...}}
WEB_ID: 1321666885934125056
AUTH 200 {"msg":"授权保存成功！...","code":200,"data":"1321666888366821376"}
SHARE_URL: https://flairmedia.com.cn:38880/busLineShow?webId=1321666885934125056
EXPORT: ...\ai_line_detail_1321666885934125056.xls (4608 bytes)
```

- 分享链接格式：线路 `busLineShow?webId=<id>`；站点 `busLineShowStation?webId=<id>`（历史记录按 `_station` 名称自动选）。
- **外部无登录已验证可打开**（标题“skill share test（自定义线路预览）”，百度地图 canvas 正常，1001 可见）。
- 导出：`GET /baseInfoWeb/exportWebLineDetail?webId=<id>`，得到线路明细 xls。
- **不做截图**：可视化直接使用平台分享链接（官方百度地图 HTML），不把平台界面截图带到本地。
- **写操作说明**：`ai_share.mjs` 会在平台创建一条历史方案并授权外部访问（默认一个月）；只在用户明确要求“分享/复制链接”时运行。只读查询请用 `ai_route.mjs`。

## 批量取方案线路（ai_route_batch.mjs）

提案项目的 Agent 用这个脚本：引擎选出公交/地铁线路后，一次会话批量取几何，带缓存与会话探测。

### 地铁线路

- 线路树 `--tree line` 明确包含「地铁线路」分组（25 个节点：地铁1–19号线，及 5/10/11 等分支），AI线路支持地铁几何。
- 批量取地铁：`--lines "地铁1号线,地铁11号线"`；脚本对 `地铁N号线` 做前缀匹配带分支的节点（如 `地铁11号线(嘉定北)` / `(花桥)`），同名多分支取 `lineId` 最小的一条；缓存按前缀复用。
- 实测 2026-11-22：`地铁1号线` 210 点、`地铁11号线(嘉定北)` 472 点，`status=ready`。
- `AI线路-站点` 只给站坐标，不提供线路几何；地铁线形请用线路树。

```powershell
# 只探测会话（不启动浏览器；apiRequest 共享 storageState）
node .claude\skills\xinyun-bigdata\scripts\ai_route_batch.mjs --check
# → {"ok":true,"authenticated":true,"http_status":200,...}
# 过期：{"ok":false,"authenticated":false,"http_status":302,"reason":"MANUAL_LOGIN_REQUIRED","location":"http://…/login"}

# 批量取线路；stdout 是单行 JSON，可重复 --out
node .claude\skills\xinyun-bigdata\scripts\ai_route_batch.mjs `
  --lines "136,157,17" --out data\external\platform\queries

# 强制刷新 / 只用缓存（无会话演示）
node .claude\skills\xinyun-bigdata\scripts\ai_route_batch.mjs --lines "136,157" --force
node .claude\skills\xinyun-bigdata\scripts\ai_route_batch.mjs --lines "136,157" --cached-only
```

参数：

| 参数 | 说明 |
|---|---|
| `--lines` | 逗号分隔线路名（`136` 或 `136路` 都可，内部去掉尾部“路”）；默认最多 60 条 |
| `--out` | 缓存目录；默认 `data/external/platform/queries` |
| `--max-age-days` | 缓存 TTL，默认 30 天 |
| `--force` | 忽略缓存重新取 |
| `--cached-only` | 不联网，只返回缓存；缺的写入 `missing[]` |
| `--check` | 只探测会话，不读线路、不写文件 |

输出：

```json
{
  "ok": false,
  "status": "degraded",
  "reason": "PARTIAL_ROUTES",
  "data_month": "202305",
  "summary": {"requested": 2, "resolved": 1, "cached": 0, "fetched": 1, "missing": 1},
  "lines": [{"requested": "136", "line": "136", "lineName": "136路", "lineId": 9900,
             "status": "fetched", "points": 384,
             "path": [[121.57, 31.11], ...], "bbox": [121.5, 31.1, 121.6, 31.2],
             "fetched_at": "2026-11-22T…Z"}],
  "missing": [{"requested": "404", "reason": "NOT_FOUND", "suggestions": []}]
}
```

- **纯 JSON stdout**（进度/错误只写 stderr）；`path` 已由平台 `{lng:纬度, lat:经度}` 交换为 `[lng,lat]`。
- 全部缓存命中时不启动浏览器；缺少 `STATE` 或会话过期但有缓存时，仍返回缓存 + `missing[]`。
- 会话探测与批量取数都走 `context.request`/`apiRequest`，不加载页面，避开 nginx 的 https→http 302 导致的 400。
- `status`：`ready`（全部命中）/ `degraded`（部分）/ `skipped`（无会话且无缓存）。
- 只读；不创建平台方案、不调用 `ai_share.mjs`。

## 注意

- 只读；不要把 `/baseInfoWeb/saveWeb` 写进自动化（会创建平台方案）。
- 线路树较大（约 342KB），脚本只取匹配节点。
- `AI线路-站点` 的站坐标来自 `staLocaltion`（`lng,lat` 字符串），没有线路几何。
- Playwright ≥1.65 不允许 `route.continue({url})` 跨协议：`lib.mjs` 已改为“导航 302 Location 重写 + 子资源 http→https 代理”，不要在脚本里再写旧的 route hack。
- 会话过期时，Agent 会先 `--check` 再决定是否跑 coverage/POI 页面脚本，避免每阶段白等浏览器。
