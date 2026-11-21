# 红豆库存 API · 实测字段说明

> 实测时间：2026-11-21
> 实测环境：`https://flairmedia.com.cn:881`，tenant-id=1，账号 test16
> 抓取脚本：`scripts/fetch_hongdou.py`，结果存 `data/`

---

## 一、抓取结果总览

| 接口 | 接口声称 | 实际拿到 | 说明 |
|---|---|---|---|
| 公交 `BUS_VEHICLE` | 552 | **431 条** | 431 与资料包台账行数一致 |
| 地铁 `METRO_GATE` | 861 | **861 条** | 861 = 274 个站 × 各出入口 |

**公交 431 条库存汇总（档期 2027-01-01 ~ 2027-01-31）**

| 指标 | 数量 |
|---|---|
| 总车数 | 2525 |
| 合同占用 | 758 |
| 预定占用 | 404 |
| **可售空位** | **1237** |

> ⚠️ 这条最重要：资料包里那份静态台账写的是**空位 2517/2525**（几乎全可售），
> 而真实档期查询只有 **1237** —— 差了一倍。
> **静态台账不能当库存用**，答辩时如果只引用台账数字，评委一查系统就对不上。

**地铁 861 条库存汇总**

| 指标 | 数量 |
|---|---|
| 总点位 | 861 |
| 合同占用 | 96 |
| 预定占用 | 22 |
| **可售空位** | **743**（空位 > 0 的点位有 743 个） |

---

## 二、接口与请求格式

```http
GET /admin-api/orders/media-inventory/bus/page
GET /admin-api/orders/media-inventory/metro/page

tenant-id: 1
Authorization: Bearer <accessToken>
Accept: application/json
```

### 公交参数

| 参数 | 必填 | 说明 | 实测行为 |
|---|---|---|---|
| `pageNo` | 是 | 页码，从 1 开始 | — |
| `pageSize` | 是 | 每页条数 | **实返条数 < pageSize**，见下方坑 |
| `startDate` | 是 | `YYYY-MM-DD` | 影响结果（见第四节） |
| `endDate` | 是 | 同上 | — |
| `lineName` | 否 | 线路名 | **模糊匹配**：`100` → 11 条（100/1001/1002…）；`1001` → 1 条；`浦东1` → 25 条 |
| `lineLevel` | 否 | 线路等级编码 | `1`/`2`/`3`/`5`/`6`，见第三节 |

### 地铁参数

| 参数 | 必填 | 说明 | 实测行为 |
|---|---|---|---|
| `pageNo` / `pageSize` | 是 | 分页 | 正常分页 |
| `startDate` / `endDate` | 是 | 日期 | — |
| `keyword` | 否 | 站名或出入口名 | 模糊匹配：`上海南站` → 3 条；`徐家汇` → 4 条 |
| `districtname` | 否 | 区编码 | `2` → 84 条（**编码含义未确认**） |
| `lineLevel` | 否 | 等级编码 | `1` → 0 条（地铁没有 1 级） |

> 试过但**无效**的参数名（传了不报错，就是不生效）：
> `level`、`lineType`、`mediaName`、`mediaType`、`companyName`、`operatingCompany`、`stationAttr`
>
> 网页上那几个筛选框（媒体类型、行车公司、代理名称、扩展状态）对应的参数名**没找到**。
> 需要时从 `assets/index-*.js` 里翻，或在前端筛完再导出。

---

## 三、字段字典（40 个字段，实际有值的只有一半）

### 3.1 两个接口共用的库存字段（核心，必用）

| 字段 | 类型 | 含义 | 对应静态台账列 |
|---|---|---|---|
| `resourceType` | string | `BUS_VEHICLE` / `METRO_GATE` | — |
| `resourceId` | int | 媒体资源 ID（**注意：有重复，见坑 3**） | — |
| `lineName` | string | 公交=线路名；地铁=**站名** | 线路 |
| `lineLevel` | string | 等级编码（字符串！） | 线路等级 |
| `totalCount` | int | 总资源数 | 总车辆数（可售） |
| `contractCount` | int | 合同占用 | 合同车数 |
| `reservationCount` | int | 预定占用 | 预定车数 |
| `freeCount` | int | **可售空位 ← 这就是"空车数"** | 空位数 |
| `maintenanceForbiddenCount` | int | 保养影响容量（2027-01 公交合计 223，地铁 0；**不是全 0**） | 保养影响容量 |
| `renewPossibleCount` | int | 可能续约数（全库为 0） | 可能续约数 |
| `protectCount` | int | 优先保护数（全库为 0） | — |
| `canViewKeepvehicle` | bool | 是否可查看保留车（全 false） | — |
| `keepvehicleCount` | int | 保留车数（全 0） | — |

**四个 duration 字段**（`contractDurationMinutes` / `reservationDurationMinutes` /
`freeDurationMinutes` / `totalDurationMinutes`）—— 实测**全部为 null**，
可能是"按分钟统计的占用时长"，当前数据未填充。暂时不用。

### 3.2 公交专属字段

| 字段 | 有值？ | 含义 |
|---|---|---|
| `companyName` | ✅ | 行车公司（南汇/金高/上南/杨高/巴士一~五/巴士旅游/春秋国旅） |
| `mediaName` | ✅ | 媒体类型：`车身三侧`(334) / `大三侧`(95) / `全色车`(2) |

其余 `metroNumber` / `stationAttr` / `exitName` / `districtname` / `businessAreaName` /
`categoryTags` / `prompt` / `amapLine` / `operatingCompany` / `locationstr` /
`production` / `mediatypename` / `roadname` / `totalhour` / `unittime` /
`frequency` / `unitmea` / `grilleType` / `outdoorNumber` / `greeningMetroLogo` —— **全部为 null**。

### 3.3 地铁专属字段（信息比公交丰富得多）

| 字段 | 有值？ | 含义 | 示例 |
|---|---|---|---|
| `lineName` | ✅ | **站名** | `上海南站` |
| `exitName` | ✅ | 出入口 | `1号口`、`10号口` |
| `metroNumber` | ✅ | 点位编号 | `SHDT-0014` |
| `stationAttr` | ✅ | **换乘线路** | `L01/L03/L15换乘` |
| `districtname` | ✅ | **区编码数组** | `[2]`、`[11]`（**编码含义未确认**） |
| `businessAreaName` | ✅ | 商圈名 | `上海南站`、`徐汇日月光中心、光大会展中心` |
| `categoryTags` | ✅ | **场景标签** | `商业、办公`、`住宅、办公`、`六大商圈`、`商圈` |
| `specialSituation` | ⚠️ 少量 | **特殊状态** | `封闭改造`、`扶梯改造，封闭至2026.10.31` |

> `categoryTags` 特别有用：可以直接用来做"商圈型/住宅型/办公型"分类，
> 这是做覆盖分析时的天然分组，比从公交的"运营公司"猜区域靠谱得多。
>
> `specialSituation` 很关键：2027-01 实测有 9 个点位命中封闭/改造等状态，**必须从方案里剔除**，
> 否则会做出一个"投了但装不上"的方案。

---

## 四、三个必须知道的坑

### 坑 1：`total` 字段不可信

```
公交: total=552，实际翻页只能拿到 431 条
```

431 和资料包台账行数完全一致，所以 431 才是真实行数。
552 可能是另一种统计口径（比如"线路 × 媒体类型"的组合数）。

**结论**：不能拿 `total` 当翻页终止条件。

### 坑 2：每页实返条数 < pageSize

```
pageSize=20   -> 实返 19
pageSize=100  -> 实返 94
pageSize=200  -> 实返 155
pageSize=552  -> 实返 431
pageSize=1000 -> 实返 431
```

后端似乎在 `pageNo × pageSize` 上做了奇怪的截断。

**结论**：不能拿 `len(items) < pageSize` 判断结束，唯一可靠的终止条件是**本页返回 0 条**。
脚本已按此实现，并加了"按 `(resourceId, lineName, mediaName)` 去重"和
"连续 3 页无新增则停"两道保险。

### 坑 3：`resourceId` 有重复

431 条里只有 430 个不同的 `resourceId`。所以 **`resourceId` 不能当主键**，
真正的唯一键是 `(lineName, mediaName)`（公交）或 `(lineName, exitName)`（地铁）。

### 坑 4：accessToken 不是 JWT

实测拿到的 token 是 **32 位 hex**（`726fa5c831f146e1886af7eacb4314fe`），
不是常见的三段式 JWT。而且**有效期很短**——我抓完一轮后（约 10 分钟）
再请求就返回：

```json
{"code": 401, "msg": "账号未登录", "data": null}
```

**结论**：
- token 是会话票据，不是签名 JWT
- 过期后必须重新从浏览器 F12 复制
- 脚本遇到 `code=401` 只打印一次"重新登录"提示，不会反复重试骚扰服务器

---

## 五、`lineLevel` 编码 → 等级名 的对照表（已交叉验证）

我用 API 数据与资料包静态台账的 `线路等级` 列做了一次全量交叉比对：

| API `lineLevel` | 实际等级 | 条数 |
|---|---|---|
| `"1"` | **S** | 48 |
| `"2"` | **A++** | 200 |
| `"3"` | **A+** | 181 |
| `"5"` | **AA** | 2 |
| `"6"` | 未知（7 条） | 7 |

> 注意 `"6"` 这 7 条在静态台账里找不到对应，需要单独确认。
> 地铁只有 `"2"`(502) 和 `"3"`(354)，另有 5 条为空 —— 说明地铁的等级口径和公交不同，
> **不能直接套用公交的 S/A++/A+ 语义**。

---

## 六、日期参数的实际影响

`startDate`/`endDate` 确实影响库存（这是这个 API 最大的价值）：

```
线路 100 在 2027-01：总 8 车，合同 1，预定 5，空 2
线路 100 在 2026-11-21（今天）：总 8 车，合同 7，预定 0，空 1
```

同一辆车在不同档期的占用状态完全不同 —— 正是赛题要求的"库存按日期查询"。

> 建议：方案排期前必须按目标月份的**首尾日**查一次，把 `freeCount` 写进方案，
> 并在 HTML 上标注"库存校验时间戳 + 校验档期"。这是行业专业度的加分项。

---

## 七、数据怎么用

### 直接可用

```python
import pandas as pd
b = pd.read_csv("data/bus_2027-01-01_2027-01-31.csv")
m = pd.read_csv("data/metro_2027-01-01_2027-01-31.csv")

# 只要可售的
b_free = b[b.freeCount > 0]
m_free = m[m.freeCount > 0].query("specialSituation.isna()", engine="python")

# 等级映射
LEVEL = {"1": "S", "2": "A++", "3": "A+", "5": "AA"}
b["level"] = b.lineLevel.astype(str).map(LEVEL)

# 地铁商圈分组
m["scene"] = m.categoryTags.fillna("").str.split("、")
```

### 接到优化器

`prototypes/bus_optimizer.py` 的 `load_bus_ledger()` 目前读的是静态 xlsx。
换成读这个 CSV 只需改列名映射：

```python
COL_MAP = {
    "lineName": "line", "companyName": "company", "lineLevel": "level_code",
    "mediaName": "media_type", "totalCount": "cap",
    "maintenanceForbiddenCount": "maint", "contractCount": "contract",
    "reservationCount": "booked", "freeCount": "free",
    "renewPossibleCount": "renew",
}
# 并加一步 level_code -> level 的映射
```

---

## 八、还没拿到的

| 缺的东西 | 可能来源 |
|---|---|
| 地铁等级 `"2"`/`"3"` 的真实含义 | 需要问组委会，或在前端筛选框里看下拉选项 |
| `districtname` 编码 → 区名 | 同上 |
| 线路走向 / 站点坐标 | 可视化平台「AI 线路」画线后拿 HTML 里的坐标 |
| 线路日均客流 | 可视化平台「媒体查询」，**月份必须选 2023 年** |
| 媒体类型筛选参数名 | 从前端 JS 或 Network 抓 |

---

## 九、复现命令

```powershell
$PY = "C:/Users/20614/AppData/Local/Python/pythoncore-3.14-64/python.exe"

# 探一页
& $PY scripts/fetch_hongdou.py --start 2027-01-01 --end 2027-01-31 --only bus --pages 1

# 全量
& $PY scripts/fetch_hongdou.py --start 2027-01-01 --end 2027-01-31 --out ./data
```

输出：

```
data/bus_2027-01-01_2027-01-31.csv     431 行 × 40 列
data/metro_2027-01-01_2027-01-31.csv   861 行 × 40 列
```