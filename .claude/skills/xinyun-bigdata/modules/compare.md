# 子模块 1：组合查询

> 页面：`https://flairmedia.com.cn:38880/comparePage`
> 脚本：`scripts/compare.mjs`（`scripts/query.mjs` 为兼容别名）
> 查询时间：固定 **2023-05**；平台没有 2023-07 数据。

## 0. 先实时发现选项（不要预拉全量）

```powershell
# 一级标签
node .claude\skills\xinyun-bigdata\scripts\compare_options.mjs --first
# → 公交 / 户外 / 地铁出入口 / 上海地铁 / 观光车

# 二级标签（一级=公交）
node .claude\skills\xinyun-bigdata\scripts\compare_options.mjs --first 公交
# → A+ / A++ / AA / S / 其他；二级“全部”= 留空

# 三级标签搜索（一级=公交，二级留空=全部）
node .claude\skills\xinyun-bigdata\scripts\compare_options.mjs --first 公交 --keyword 1001
# → 共 1549，匹配 1：A+-1001  id=6000  车身三侧  ext1=1001路
```

> 选项全部通过 `/label/queryFirstLabel`、`/querySecondLabel`、`/queryThirdLabel` **实时查询**，不落全量。
> `--keyword 1001` 只匹配 1001；要看 1002 用 `--keyword 1002`，要看整组用 `--keyword 100`。

## UI 路径

1. 顶部菜单点 **组合查询**（`/comparePage`）。
2. **查询时间**：`2023-05`。
3. **一级标签**：`公交`（或 `地铁出入口` / `上海地铁` / `户外` / `观光车`）。
4. **二级标签**：`全部`（实际是**留空**；公交可选 `A+` / `A++` / `AA` / `其他`）。
5. **三级标签**：多选线路/站点，逗号分隔，例如 `01路,1001,1002`。
6. 勾选 **添加比较**，点击 **查询**。
7. 右侧出现 **已选择媒体** 和 **区域人流属性 / 区域人群画像**；点右侧 **导出** 下载 Excel。

## 脚本

```powershell
cd D:\Cacimodo\Projects\AIPlusWork
node .claude\skills\xinyun-bigdata\scripts\compare.mjs `
  --media 公交 `
  --labels "01路,1001,1002" `
  --date 202305 `
  --export
```

参数：

| 参数 | 默认 | 说明 |
|---|---|---|
| `--media` | `公交` | 一级标签；公交/地铁出入口/上海地铁/户外/观光车 |
| `--labels` | 必填 | 三级标签，逗号分隔；`01路,1001,1002` |
| `--date` | `202305` | 只支持 2023-05 |
| `--out` | `data/external/platform/queries` | 输出目录 |
| `--export` | 无 | 额外导出 Excel（`/exportIndicatorData` → `/downloadExcel`） |

## 接口

```http
POST /label/queryThirdLabel        # 标签解析
firstLabel=公交&secondLabel=       # 二级“全部”= 空

POST /bbf8e41e454b47126290905525c69f7   # 指标数据
queryType=1&indicatorType=crowdAge&dataMonth=202305
&labelIds=6382,6000,6001&gridIds=
&extOptions={"gridType":"500","underground":"0"}
```

- 指标：`visitorsFlowrateAndcrowdSpeed`、`circleCross`、`regionAttribute`、`crowdAge`、`crowdGender`、`crowdHouse`、`crowdConsumption`、`crowdPhoneNew`。
- 标签 ID 动态解析；2026-11-21 时 `01路=6382`、`1001=6000`、`1002=6001`。

## 数据获取与可视化

| 内容 | 方式 |
|---|---|
| 原始指标 | `compare_<ids>_<date>.json`（8 个 indicator 的原始 `data`） |
| 表格导出 | `--export` → `大数据洞察_<ids>_<date>.xls`（平台 `/exportIndicatorData` → `/downloadExcel`） |
| 可视化 | 平台右侧“区域人流属性/区域人群画像”图表直接查看；skill 输出可喂给项目网站 ECharts；**不导出截图** |

> 组合查询没有“分享链接”；需要分享可视化时，用 AI线路 `ai_share.mjs` 生成百度地图 HTML，或用 Excel/JSON 给客户。

## 字段

- `crowdAge.age1` = 20岁以下，`age2` = 20–30，`age3` = 30–40，`age4` = 40–50，`age5` = 50以上（%）。
- `crowdGender.male/female`（%）。
- `crowdHouse.zero/one/two/more`（0–1 小数；脚本 summary 输出 `house_pct`）。
- `crowdPhoneNew[].phone_name/num`（计数）。
- `visitorsFlowrateAndcrowdSpeed[].time1..time4/type`（原始时段值）。
- `crowdConsumption.*`：原始字段，UI 图表映射未完全公开，先保留原值。

## 已验证示例

`--media 公交 --labels "01路,1001,1002" --date 202305 --export`：

```
公交-其他-01路 id=6382
公交-A+-1001 id=6000
公交-A+-1002 id=6001
20岁以下 0.84%
男性 53.96% / 女性 46.04%
房产 无房23 / 一套64 / 二套9 / 多套4
手机 Top OPPO:11 / 三星:11 / VIVO:8 / 小米:8 / 苹果:8
时段人流 67 点（非零 7，最大 2316970）
JSON + 34KB Excel 已生成
```

输出：

```
data/external/platform/queries/compare_<ids>_202305.json
data/external/platform/queries/大数据洞察_<ids>_202305.xls
```

> **口径说明**：不同标签集合的聚合值不同。只查 `1001,1002` 时当前返回 20岁以下 1.1%、男性 68.28%、房产 23/65/9/4%；你提供的示例图中房产 25/70.65/4.35% 可能对应不同查询时点或勾选状态。脚本输出以平台接口实时返回为准，不做二次加工。
