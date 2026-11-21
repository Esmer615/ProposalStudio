# 子模块 4：地址查询

> 页面：`https://flairmedia.com.cn:38880/looseMultiQuery`（顶部菜单「定制查询」）
> 脚本：`scripts/address.mjs`
> 用途：地址/坐标 + 半径 → 命中媒体 → 导出平台 Excel。
> **只导出文件**：不保存 labels/sop JSON/CSV，只保存 `.xls`。

## 0. 先实时发现选项

```powershell
node .claude\skills\xinyun-bigdata\scripts\address_options.mjs
```

实测输出：

```
查询方式: 地址查询 / POI查询（页面顶部单选）
查询时间: 2023-05（固定）
查询范围 queryRange: 100 / 200 / 500 / 1000 / 1500 / 2000 / 2500 米
红豆线路 isHD: 0(否) / 1(是)
POI 类型（/basekeyword/query）: 25 个（商场/景点/幼儿园/小学/中学/大学/医院/…）
```

> 查询范围、isHD 是页面 select 实时读取；POI 类型来自 `/basekeyword/query` 实时接口。
> 本脚本走 **地址查询** 分支（地址/坐标 + 半径）；页面上的“POI 查询”分支当前未脚本化，走 UI。

## 脚本

```powershell
cd D:\Cacimodo\Projects\AIPlusWork

# 小范围示例：乐高 1000m
node .claude\skills\xinyun-bigdata\scripts\address.mjs `
  --address "上海乐高乐园" `
  --radius 1000
```

参数：

| 参数 | 默认 | 说明 |
|---|---|---|
| `--address` | — | 地址/地标；走 `/nearby/geocode` |
| `--lng` / `--lat` | — | 直接给坐标（与地址二选一） |
| `--radius` | `1000` | 米；脚本生成 36 点圆形边界 |
| `--date` | `202305` | 只支持 2023-05 |
| `--name` | `大数据洞察_地址查询_<中心>_<半径>_<日期>` | 导出文件名（不含 `.xls`） |
| `--out` | `data/external/platform/queries` | 输出目录 |

## 接口

```http
POST /nearby/geocode                 # 地址 → 坐标
Content-Type: application/json
{"address":"上海乐高乐园","city":"上海市"}
→ {"code":0,"data":{"lng":121.1078,"lat":30.8931,...}}

POST /label/queryLabelByBorder
numStr=0
&border=<"lng lat,lng lat,...">       # 闭合圆形边界
&dataMonth=202305
&isHD=0
→ {"numStr":"0","grids":[...],"labels":[...],"sopExtendData":[...]}
```

脚本只用 `labels[].id` 作为导出参数；`grids`/`sopExtendData` 不保存、不输出。

```http
POST /exportIndicatorData
queryType=1
&indicatorType=coverPeoples,visitorsFlowrate,regionAttribute,crowdAge,crowdGender,crowdHouse,crowdIndividualConsumption,crowdPhone,crowdExtInfo
&dataMonth=202305
&labelIds=<命中媒体 id，逗号分隔>
&gridIds=
&extOptions={"gridType":"500","underground":"0"}
&fileName=大数据洞察_地址查询_上海乐高乐园_1000_202305
→ {"code":"0000","data":"<filePath>"}

GET /downloadExcel?filePath=<filePath>&excelType=1&fileName=<fileName>.xls
→ .xls
```

> 这与组合查询/条件查询是同一条导出链路；地址查询用命中的媒体标签（`labelIds`）导出汇总指标。
> 平台右侧 `/infoPage` 的“导出”按钮走同一条链路。

## 已验证示例

`--address "上海乐高乐园" --radius 1000`：

```
地理编码: 上海乐高乐园 -> 121.1078 30.8931
中心: 上海乐高乐园 (121.1078, 30.8931) 半径 1000m
命中媒体: 1
EXPORT: ...\大数据洞察_地址查询_上海乐高乐园_1000_202305.xls (32768 bytes)
```

文件为 Excel（`application/vnd.ms-excel`）。

## 数据获取与可视化

| 内容 | 方式 |
|---|---|
| 导出文件 | `大数据洞察_地址查询_<中心>_<半径>_<日期>.xls`（命中媒体的汇总指标） |
| 平台导出 | 右侧 `/infoPage` 的“导出”；脚本复用 `/exportIndicatorData` → `/downloadExcel` |
| 可视化 | 直接打开 Excel；平台页面可看地图/属性；**不导出截图** |
| 本地保存 | 只保存 `.xls`；不保存 labels/sop JSON/CSV |

## 注意

- 地址查询的 `labels` 是边界内的媒体标签；对乐高 1000m 只返回 1 条（郊区媒体稀疏），而覆盖分析的 2 条公交是“线路轨迹经过半径”，两者口径不同。
- 只有 2023-05 数据；`--date` 固定为 202305。
- 不导出截图；结果就是 Excel。
