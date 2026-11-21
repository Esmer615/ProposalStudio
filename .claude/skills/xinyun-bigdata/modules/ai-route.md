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

## 注意

- 只读；不要把 `/baseInfoWeb/saveWeb` 写进自动化（会创建平台方案）。
- 线路树较大（约 342KB），脚本只取匹配节点。
- `AI线路-站点` 的站坐标来自 `staLocaltion`（`lng,lat` 字符串），没有线路几何。
