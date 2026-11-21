# 子模块 3：条件查询

> 页面：`https://flairmedia.com.cn:38880/conditionQuery`
> 脚本：`scripts/condition.mjs`
> 用途：按 2023-05 的人群/区域条件筛选，把命中的媒体导出为平台 Excel。
> **只导出文件**：查询返回的 grids/labels 只在内存里用于取媒体 ID，不落本地、不保存 grids。

## 0. 先实时发现选项（不要预拉全量）

```powershell
# 全部条件分组概览
node .claude\skills\xinyun-bigdata\scripts\condition_options.mjs

# 年龄属性的选项（20岁以下/20~30/… 及其 1万以下…）
node .claude\skills\xinyun-bigdata\scripts\condition_options.mjs --type 人群属性 --subtype 年龄属性

# 商圈（示例：徐家汇 = 17）
node .claude\skills\xinyun-bigdata\scripts\condition_options.mjs --type 商圈
```

实测（`--type 人群属性 --subtype 年龄属性`，共 20 条）：

```
id=53  人群属性/年龄属性/20岁以下  name=1万以下   conditionId=1  dataItem=val10  min=0 max=10000
id=54  人群属性/年龄属性/20岁以下  name=1~5万     conditionId=2  dataItem=val10  min=10000 max=50000
id=55  人群属性/年龄属性/20岁以下  name=5~10万    conditionId=3  dataItem=val10  min=50000 max=100000
id=56  人群属性/年龄属性/20岁以下  name=10万以上  conditionId=4  dataItem=val10  min=100000 max=99999999
```

> UI 的“年龄属性”是多个 select：`20岁以下` / `20~30岁` / …；每个 select 的选项是 `1万以下/1~5万/5~10万/10万以上`，对应 request 值 `id=53/54/55/56`。
> 其他 firstType/secondType/thirdType 同样用 options 脚本实时查看；不要手写未知条件。

## UI 路径

1. 顶部菜单 **条件查询**。
2. **查询时间**：`2023-05`。
3. 选筛选条件：
   - 行政区 / 街道镇 / 商圈
   - 区域属性：地理属性（内环内/中环…）、POI 属性（学校/会展/小区/景点）
   - 人群属性：月日均人次、月日均人数、年龄属性、性别、房产、消费
4. 点 **查询**，左侧地图显示网格，右侧 `/infoPage` 显示所选区域汇总值。
5. 点右侧 **导出** 下载 Excel（脚本复用同一条 `/exportIndicatorData` 链路）。

> 条件查询页自身左上的 `poiExportButton` 是注释状态；实际可用的是右侧 infoPage 的“导出”。

## 脚本

```powershell
cd D:\Cacimodo\Projects\AIPlusWork

# 小范围示例：徐家汇商圈(17) + 20岁以下/1万以下(53)
node .claude\skills\xinyun-bigdata\scripts\condition.mjs --condition "17,53"
```

参数：

| 参数 | 默认 | 说明 |
|---|---|---|
| `--condition` | `17,53` | 条件 id 或 UI 生成的 queryCondition；多个 id 用逗号连接 |
| `--date` | `202305` | 只支持 2023-05 |
| `--name` | `大数据洞察_条件查询_<condition>_<date>` | 导出文件名（不含 `.xls`） |
| `--out` | `data/external/platform/queries` | 输出目录 |

> 建议限定小范围（商圈/行政区/街道镇）验证；全上海条件会返回数万网格，导出慢且可能被网关拒绝。
> 默认 `17,53` 实测查询约 **3 秒**、命中 **11 个媒体**（导出另需数秒）。

## 接口

```http
POST /label/queryLabelByQueryCondition
queryCondition=17,53&dataMonth=202305
→ {"grids":[...],"labels":[...]}
```

脚本只用 `labels[].id` 作为导出参数；`grids` 不保存、不输出。

```http
POST /exportIndicatorData
queryType=1
&indicatorType=coverPeoples,visitorsFlowrate,regionAttribute,crowdAge,crowdGender,crowdHouse,crowdIndividualConsumption,crowdPhone,crowdExtInfo
&dataMonth=202305
&labelIds=<命中媒体 id，逗号分隔>
&gridIds=
&extOptions={"gridType":"500","underground":"0"}
&fileName=大数据洞察_条件查询_17_53_202305
→ {"code":"0000","data":"<filePath>"}

GET /downloadExcel?filePath=<filePath>&excelType=1&fileName=<fileName>.xls
→ .xls
```

> 这与组合查询 `compare.mjs --export` 是同一条导出链路；条件查询用命中的媒体标签（`labelIds`）导出汇总指标。
> 平台右侧 infoPage 的“导出”按钮是另一种模式：`queryType=2 + gridIds`（全部网格）。脚本采用 media 标签模式，避免超大 gridIds 被网关拒绝。

## 已验证示例

```powershell
node .claude\skills\xinyun-bigdata\scripts\condition.mjs
```

```
条件: 徐家汇商圈 + 20岁以下 / 1万以下 (condition=17,53, date=202305)
命中媒体: 11
EXPORT: ...\大数据洞察_条件查询_17_53_202305.xls (41984 bytes)
```

文件为 OLE Excel（`d0 cf 11 e0` 头）；查询约 3 秒，导出另需数秒。

## 数据获取与可视化

| 内容 | 方式 |
|---|---|
| 导出文件 | `大数据洞察_条件查询_<condition>_<date>.xls`（命中媒体的汇总指标） |
| 平台导出 | 右侧 `/infoPage` 的“导出”；脚本复用 `/exportIndicatorData` |
| 可视化 | 直接打开 Excel；平台页面可查看网格图；**不导出截图** |
| 本地保存 | 只保存 `.xls`；不保存 grids/labels JSON |

## 注意

- 平台只有 2023-05；2023-07 返回空。
- 条件 ID 是平台口径；先跑 `condition_options.mjs`。示例 `17`=徐家汇商圈、`53`=20岁以下/1万以下（实测）。
- 多个条件用逗号连接（如 `17,53`）；不要默认跑全上海。
- 导出的是**命中媒体的汇总指标**，不是网格 crowdDensity；需要网格图请在平台页面查看。
- 不导出截图。
