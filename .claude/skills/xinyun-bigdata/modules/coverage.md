# 子模块 2：媒体覆盖查询

> 页面：`https://flairmedia.com.cn:38880/nearbyPoiLineQuery`（顶部菜单「媒体覆盖分析」）
> 脚本：`scripts/coverage.mjs`
> 用途：输入中心点/地址 + 半径 → 查周边公交线路、地铁站及最近距离。

## 0. 先实时发现选项（不要预拉全量）

```powershell
node .claude\skills\xinyun-bigdata\scripts\coverage_options.mjs
```

实测输出：

```
查询内容 queryBizMode: poi=周边点位 / line=覆盖媒体
检索范围 poiRangeMode: circle=圆形 / region=行政区 / polygon=多边形
覆盖媒体中心来源 coverCenterSource: poi=已查询点位 / manual=手动输入
媒体类型 coverMediaType: bus / metro
线路范围 coverLineScope: self=仅新云媒体 / all=全部
周边点位搜索半径 queryRange: 300 / 500 / 1000 / 1500 / 2000 / 3000 / 5000
覆盖半径 lineMatchRange: 50 / 100 / 200 / 300 / 500 / 1000 / 1500 / 2000
POI 类型（/basekeyword/query）: 25 个（商场/景点/幼儿园/小学/中学/大学/医院/…）
```

## UI 路径

1. 顶部菜单 **媒体覆盖分析**。
2. 查询内容选 **覆盖媒体**。
3. 检索范围选 **圆形**。
4. **中心地点 / 坐标**：输入地址或坐标（支持多个）。
5. **搜索半径**：如 1000 米。
6. 媒体类型勾选 **公交** / **地铁**。
7. 点 **分析覆盖媒体**；右侧列出覆盖媒体；可点 **导出分析结果**。

## 脚本

```powershell
cd D:\Cacimodo\Projects\AIPlusWork
node .claude\skills\xinyun-bigdata\scripts\coverage.mjs `
  --address "上海乐高乐园" `
  --radius 1000
```

参数：

| 参数 | 默认 | 说明 |
|---|---|---|
| `--address` | — | 地址/地标；脚本用 `/nearby/geocode` 解析 |
| `--lng` / `--lat` | — | 也可直接给坐标（与 `--address` 二选一） |
| `--name` | 地址/自定义 | 输出中心名称 |
| `--radius` | `1000` | 米 |
| `--media` | `bus,metro` | 媒体类型 |
| `--out` | `data/external/platform/queries` | 输出目录 |

## 接口

```http
POST /nearby/geocode                 # 仅当给的是地址
Content-Type: application/json
{"address":"上海乐高乐园","city":"上海市"}
→ {"code":0,"data":{"lng":121.1078,"lat":30.8931,...}}

POST /baseInfoLine/matchCoverLines
Content-Type: application/json
{
  "radius": 1000,
  "mediaTypes": ["bus","metro"],
  "lineScope": "all",
  "centers": [{"name":"上海乐高乐园","address":"上海乐高乐园","lng":121.1078,"lat":30.8931}]
}
→ {"code":0,"data":[{lineId,lineName,mediaType,nearestLng,nearestLat,minDistance,linePath,...,nearestStaName}]}
```

- 地铁项有 `nearestStaName`（最近站名）、`nearestStaDistance`；公交项只有 `lineName` / `minDistance`。
- `linePath` 是平台服务器路径；本模块只返回覆盖清单，不下载轨迹（AI线路模块可读 geometry）。

## 已验证示例

`--address "上海乐高乐园" --radius 1000`：

```
地理编码: 上海乐高乐园 -> 121.1078 30.8931
覆盖结果: 共 2 条（公交 2 / 地铁 0）
公交线路: 1675路, 枫泾七路
  bus 1675路 距离 384m
  bus 枫泾七路 距离 997m
```

> 中心坐标来自平台 `/nearby/geocode`。用 `--lng 121.104 --lat 30.88`（我们数据里的近似坐标）会得到另一组线路（约 6 条，含朱泾5路/枫戚快线）。覆盖结果依赖中心点；以实际输入为准。

输出：

```
data/external/platform/queries/coverage_上海乐高乐园_1000.json
```

## 同一页面的另一分支：周边点位

“查询内容”选 **周边点位** 时，用 `coverage_poi.mjs`（实时 POI 类型来自 `/basekeyword/query`）：

```powershell
# 只统计数量
node .claude\skills\xinyun-bigdata\scripts\coverage_poi.mjs `
  --address "上海乐高乐园" --radius 1000 --types "商场,幼儿园" --mode count
# 实测：商场 1 / 幼儿园 0

# 点位明细
node .claude\skills\xinyun-bigdata\scripts\coverage_poi.mjs `
  --address "上海乐高乐园" --radius 1000 --types "商场" --mode detail
# 实测：商场 | 爱琴海·缤纷里AEGEAN BINGO | 金山区枫泾镇乐纷路268号 | 608m
```

- 接口：`POST /nearby/count` 或 `POST /nearby/detail`
- 请求：`{searchMode:"circle", keywords:["商场","幼儿园"], radius:1000, maxPage:1, centers:[{name,address,lng,lat}]}`
- `--types` 必须是 `/basekeyword/query` 返回的 `keyName`（商场/景点/幼儿园/小学/中学/大学/医院/…）。
- 明细模式最多 `maxPage` 页（默认 1；原 UI 上限 10 页≈200 条）。
- 输出 CSV 与平台“导出点位”按钮同列：
  - count：`检索模式,中心点名称,中心点经度,中心点纬度,行政区,搜索半径,点位类型,检索数量`
  - detail：`检索模式,类型,名称,主体名称,合并数量,地址,距离中心点,中心点,行政区,经度,纬度`
- 不再保存 JSON/坐标串；CSV 已含经纬度。

## 数据获取与可视化

| 内容 | 方式 |
|---|---|
| 覆盖媒体数据 | `coverage_<中心>_<半径>.json` + `.csv`（mediaType/lineName/nearestStaName/lng/lat/minDistance/lineId/linePath） |
| 周边点位数据 | `coverage_poi_<中心>_<半径>_<count|detail>.csv`（平台“导出点位”同格式；含经纬度） |
| 平台导出 | 覆盖结果点 **导出分析结果**；点位结果点 **导出点位**（前端 CSV，无服务端接口） |
| 可视化 | 平台页面直接查看（百度地图）；**本 skill 不导出截图**，数据用 CSV |

```powershell
node .claude\skills\xinyun-bigdata\scripts\coverage_poi.mjs `
  --address "上海乐高乐园" --radius 1000 --types "商场" --mode detail
```

覆盖媒体（line）输出 JSON/CSV；周边点位 count/detail 输出与平台“导出点位”同格式的 CSV。平台页面上的地图结果由使用者直接查看，不通过截图搬运。

## 注意

- 该接口**没有日期参数**，是按系统线路轨迹与当前媒体库计算的覆盖；页面没有 2023-05 月份口径。不要把它的“覆盖”与条件查询的 2023-05 人群数据混为一个口径。
- 公交没有真实线形时，本模块只给覆盖线路和最近距离；地图线形请用 AI线路模块的 `/getLineJson`。
- 周边点位查询是 **Baidu POI 检索**，不是 2023-05 人群画像；不要混用。
