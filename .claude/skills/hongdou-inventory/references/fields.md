# 红豆库存字段字典与口径

> 来源：`docs/红豆库存API-字段说明.md`（实测 2026-11-21）
> CSV 固定 40 列，列顺序与 `data/snapshots/*.csv` 一致，编码 UTF-8 with BOM（`utf-8-sig`）。

---

## 1. 40 列清单

```
resourceType, resourceId, lineName, companyName, lineLevel, mediaName,
metroNumber, stationAttr, exitName, districtname, businessAreaName,
categoryTags, prompt, greeningMetroLogo, specialSituation, amapLine,
operatingCompany, grilleType, outdoorNumber, locationstr, production,
mediatypename, roadname, totalhour, unittime, frequency, unitmea,
totalCount, contractCount, reservationCount, freeCount,
maintenanceForbiddenCount, renewPossibleCount, protectCount,
canViewKeepvehicle, keepvehicleCount, contractDurationMinutes,
reservationDurationMinutes, freeDurationMinutes, totalDurationMinutes
```

`districtname` 这类数组字段在 CSV 里写成 JSON 字符串，例如 `"[2]"`。

---

## 2. 核心字段（两个接口共用）

| 字段 | 类型 | 含义 | 备注 |
|---|---|---|---|
| `resourceType` | string | `BUS_VEHICLE` / `METRO_GATE` | 判断媒体的可靠依据 |
| `resourceId` | int | 资源 ID | **会重复，不能当主键** |
| `lineName` | string | 公交=线路名；地铁=**站名** | |
| `lineLevel` | string | 等级编码（字符串） | 见第 4 节 |
| `totalCount` | int | 总资源数 | 公交是车辆数 |
| `contractCount` | int | 合同占用 | |
| `reservationCount` | int | 预定占用 | |
| `freeCount` | int | **可售空位** | 方案里说的“空车数”就是它 |
| `maintenanceForbiddenCount` | int | 保养影响容量 | **不是全 0**：2027-01 公交合计 223、地铁 0（旧文档有误） |
| `renewPossibleCount` | int | 可能续约数 | 实测全 0 |
| `protectCount` | int | 优先保护数 | 实测全 0 |
| `canViewKeepvehicle` | bool | 是否可查看保留车 | 实测全 false |
| `keepvehicleCount` | int | 保留车数 | 实测全 0 |

四个 `*DurationMinutes`（contract / reservation / free / total）实测**全部为 null**，暂不使用。

---

## 3. 公交 / 地铁专属字段

### 3.1 公交（BUS_VEHICLE）

| 字段 | 有值 | 含义 | 示例 |
|---|---|---|---|
| `companyName` | ✅ | 行车公司 | 南汇、金高、上南、杨高、巴士一~五、巴士旅游、春秋国旅 |
| `mediaName` | ✅ | 媒体类型 | `车身三侧` / `大三侧` / `全色车` |

其余 `metroNumber` / `stationAttr` / `exitName` / `districtname` / `businessAreaName` /
`categoryTags` 等公交行全部为 null。

### 3.2 地铁（METRO_GATE）

| 字段 | 有值 | 含义 | 示例 |
|---|---|---|---|
| `lineName` | ✅ | 站名 | `上海南站` |
| `exitName` | ✅ | 出入口 | `1号口`、`10号口` |
| `metroNumber` | ✅ | 点位编号 | `SHDT-0014` |
| `stationAttr` | ✅ | 换乘线路 | `L01/L03/L15换乘` |
| `districtname` | ✅ | 区编码数组 | `[2]`（**编码→区名未确认**） |
| `businessAreaName` | ✅ | 商圈名 | `上海南站`、`徐汇日月光中心` |
| `categoryTags` | ✅ | 场景标签 | `商业、办公`、`住宅、办公`、`六大商圈` |
| `specialSituation` | ⚠️ 少量 | 特殊状态 | `封闭改造`、`扶梯改造，封闭至2026.10.31` |

`categoryTags` 可直接用于“商圈型/住宅型/办公型”分组。
`specialSituation` 命中封闭/改造等状态的点位**必须从方案里剔除**。
2027-01 实测有 **9 个点位**命中关键词（旧文档写 6 个，以实际查询为准）。

> **`"0"` 占位符**：接口用字符串 `"0"` 表示空值，常见于 `businessAreaName`、
> `categoryTags`、`districtname`。原始 CSV 保留 `"0"`；本 skill 的分组/维度统计
> 会把它归一成 `(空)`，避免把 `"0"` 当成有效商圈或标签。

---

## 4. 等级映射（lineLevel）

### 公交（已与静态台账交叉验证）

| `lineLevel` | 等级 |
|---|---|
| `"1"` | S |
| `"2"` | A++ |
| `"3"` | A+ |
| `"5"` | AA |
| `"6"` | 未知（台账里找不到对应） |
| 其他/空 | unknown |

### 地铁（语义未确认）

| `lineLevel` | 本 skill 映射 |
|---|---|
| `"2"` | A++ |
| `"3"` | A+ |
| 其他/空 | unknown |

> 地铁等级不能直接套公交的 S/A++/A+ 语义；回答时要注明“口径待确认”。
> `engine/config.py` 的映射与本 skill 一致。

---

## 5. 唯一键

| 媒体 | 抓取去重键 | 业务唯一键（汇总用） |
|---|---|---|
| 公交 | `(resourceId, lineName, mediaName)` | `(lineName, mediaName)` |
| 地铁 | `(resourceId, lineName, exitName)` | `(lineName, exitName)` |

`resourceId` 单独不唯一（431 行只有 430 个不同 ID），**不要拿它当主键**。

---

## 6. 特殊状态过滤

`specialSituation` 非空且包含以下关键词的地铁点位，排期方案要剔除：

```
封闭  改造  施工  停用  停运
```

与 `scripts/build_dataset.py` 的关键词表一致。`fetch.py --exclude-special` 和
`analyze.py --exclude-special` 会按这张表过滤；默认不过滤，但在汇总里报告数量。

---

## 7. 汇总 JSON 字段（fetch.py / analyze.py 输出）

```jsonc
{
  "media": "bus",
  "period": {"start": "2027-07-01", "end": "2027-07-31"},
  "inventory_ts": "2027-01-01T00:00:00Z",
  "filters": {
    "server": {"lineName": "100"},
    "local": {"free_only": true}
  },
  "rows": 11,                       // 本地筛选后的行数
  "fetched_rows": 11,               // 接口去重后的行数
  "unfiltered_rows": 11,            // fetch.py 额外给出
  "unique_business_keys": 11,       // (lineName, mediaName) 去重
  "free_points": 9,                 // freeCount > 0 的行数
  "special_points": 0,              // specialSituation 非空的行数
  "blocked_special_points": 0,      // 命中封闭/改造关键词的行数
  "totals": {
    "totalCount": 88,
    "contractCount": 20,
    "reservationCount": 12,
    "freeCount": 44
  },
  "by_level": {
    "A++": {"rows": 5, "free": 20, "total": 40}
  },
  "top_free": [
    {"lineName": "100", "mediaName": "车身三侧", "level": "A++",
     "freeCount": 8, "totalCount": 8, "contractCount": 0, "reservationCount": 0}
  ],
  "distinct_lines": 3,              // 公交
  "distinct_stations": 1,           // 地铁
  "distinct_exits": 3,              // 地铁
  "by_company": [{"companyName": "巴士一公司", "rows": 3, "free": 12, ...}],
  "by_media_type": [{"mediaName": "车身三侧", "rows": 5, "free": 20, ...}],
  "by_category_tag": [{"categoryTags": "商业", "rows": 2, "free": 2, ...}],
  "fetch": {
    "pages": 2, "raw_items": 20, "unique_rows": 11,
    "api_total": 552, "page_size": 200,
    "truncated": false, "stalled": false
  },
  "notes": ["接口声称 total=552，实测以返回行为准；不要拿 total 当库存量。"]
}
```

### 派生指标口径

| 指标 | 公式 | 说明 |
|---|---|---|
| `free_total` | `sum(freeCount)` | 可售空位总量；公交是空车辆数 |
| `free_points` | `count(freeCount > 0)` | 有空位的资源行数 |
| `occupied` | `contractCount + reservationCount` | 合同 + 预定；不一定等于 `total - free` |
| `premium_share` | `(S+A+++A+) 行数 / 总行数` | 库存等级占比，**不是人群浓度** |
| `by_level` | 按 lineLevel 映射分组 | 地铁等级语义待确认 |

> 地铁每条记录的 `freeCount` 基本是 0/1 点位状态，`top_free` 在大量并列时没有排序意义；
> 看 `free_points` 和 `by_category_tag`，不要拿 `top_free` 当前几名做优先推荐。

### 过滤参数语义

| 参数 | 端 | 语义 |
|---|---|---|
| `--line-name` | 服务端（公交） | `lineName` 模糊匹配 |
| `--keyword` | 服务端（地铁） | 站名或出入口模糊匹配 |
| `--line-level` | 服务端（两者） | 原始等级编码精确匹配 |
| `--district-code` | 服务端+本地（地铁） | `districtname` 数组包含该编码 |
| `--company` | 本地（公交） | `companyName` 子串匹配 |
| `--media-name` | 本地（公交） | `mediaName` 子串匹配 |
| `--level` | 本地（两者） | 等级名（S/A++/A+/AA/unknown）或原始编码 |
| `--free-only` | 本地（两者） | `freeCount > 0` |
| `--exclude-special` | 本地（地铁） | 剔除命中封闭/改造关键词的点位 |

---

## 8. 没有的字段（不要编）

| 缺的东西 | 可能来源 |
|---|---|
| 地铁等级 `"2"/"3"` 的真实含义 | 问组委会或前端下拉框 |
| `districtname` 编码 → 区名 | 同上 |
| 线路走向 / 站点坐标 | 大数据平台 AI 线路（`xinyun-bigdata` skill） |
| 线路日均客流 | 大数据平台媒体查询（月份必须选 2023 年） |
| 媒体类型筛选参数名 | 前端 JS / Network；本 skill 用本地过滤替代 |
