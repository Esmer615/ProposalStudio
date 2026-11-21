---
name: hongdou-inventory
description: 红豆广告媒体管理系统（flairmedia.com.cn:881）只读库存数据获取：OAuth2 密码模式登录/续期、公交与地铁库存按档期分页抓取、线路/站点/等级筛选、CSV/JSON 快照、档期可售汇总与离线分析。Use when the user asks for 红豆、红豆库存、媒体库存、公交库存、地铁库存、可售空位、档期库存、库存快照、库存校验、media-inventory、OAuth2/accessToken. Read-only; credentials come from HONGDOU_USER/HONGDOU_PASS or a gitignored file.
---

# 红豆库存数据获取（HongDou Inventory）

> 系统：红豆广告媒体管理系统 `https://flairmedia.com.cn:881`
> 范围：**只读**库存查询（公交 `BUS_VEHICLE` / 地铁 `METRO_GATE`）；不创建订单、不改媒体库。
> 连接方式：OAuth2 客户端密码模式（不是浏览器 F12 会话票据）。
> 依赖：Python 3.10+ 标准库，无需 `pip install`。

---

## 0. 凭证（先看这条）

账号密码按优先级读取，**不要写进 skill、文档或 Git**：

1. 环境变量 `HONGDOU_USER` + `HONGDOU_PASS`；
2. `HONGDOU_CREDENTIALS` 指向的文件；
3. 项目 `scripts/.credentials`（第一行用户名，第二行密码，已 gitignore）；
4. skill 内 `scripts/.credentials`（本地兜底，skill 的 `.gitignore` 已忽略）。

令牌缓存在 `scripts/.oauth_cache.json`（已 gitignore），默认 30 分钟有效，可自动 refresh。
脚本只输出令牌长度和剩余时间，**永远不打印令牌或密码原文**。

---

## 1. 快速开始

以下命令都在项目根目录执行；用项目虚拟环境 `.venv\Scripts\python.exe`（本机 `python` 是 Store 别名桩，别直接用）。

```powershell
$env:PYTHONIOENCODING = 'utf-8'   # 可选；脚本也会自己切 UTF-8
$SK = ".claude\skills\hongdou-inventory\scripts"

# 0) 检查/获取令牌（先跑这个；失败会给出明确退出码）
.venv\Scripts\python.exe $SK\auth.py               # 确保有可用令牌
.venv\Scripts\python.exe $SK\auth.py --status      # 可选：只看本地缓存，不联网

# 1) 按档期抓公交 + 地铁（默认写 data/hongdou/，并打印汇总 JSON）
.venv\Scripts\python.exe $SK\fetch.py --start 2027-07-01 --end 2027-07-31

# 2) 单条线路 / 单个站点
.venv\Scripts\python.exe $SK\fetch.py --start 2027-07-01 --end 2027-07-31 --media bus --line-name 100
.venv\Scripts\python.exe $SK\fetch.py --start 2027-07-01 --end 2027-07-31 --media metro --keyword 上海南站

# 3) 只要可售；地铁剔除封闭/改造点位
.venv\Scripts\python.exe $SK\fetch.py --start 2027-01-01 --end 2027-01-31 --media metro --free-only --exclude-special

# 4) 批量月度快照 → data/snapshots（供引擎；默认跳过已存在的文件）
.venv\Scripts\python.exe $SK\snapshot.py --from-month 2027-01 --to-month 2027-10

# 5) 离线分析已抓 CSV（不联网、不重复打接口）
.venv\Scripts\python.exe $SK\analyze.py --file data\hongdou\bus_2027-07-01_2027-07-31.csv --free-only --group-by companyName
.venv\Scripts\python.exe $SK\analyze.py --file data\snapshots\metro_2027-01-01_2027-01-31.csv --facets --top 10
```

`fetch.py` / `snapshot.py` / `analyze.py` 的 **stdout 都是 JSON**，进度写 stderr，方便 agent 解析。

---

## 2. 脚本索引

| 脚本 | 作用 | 联网 | 主要输出 |
|---|---|---|---|
| `auth.py` | 检查缓存 / 登录 / refresh；不打印令牌 | 是 | JSON 令牌状态 |
| `fetch.py` | ad-hoc 档期抓取，可按线路/站点/等级/公司筛选 | 是 | `data/hongdou/*.csv` + 汇总 JSON |
| `snapshot.py` | 批量月度全量快照，写入引擎读取目录 | 是 | `data/snapshots/{bus,metro}_YYYY-MM-01_YYYY-MM-last.csv` |
| `analyze.py` | 离线汇总、分组、维度发现 | 否 | 汇总/分组/维度 JSON |
| `hongdou_lib.py` | 共享库（OAuth2、分页、CSV、汇总） | — | — |

---

## 3. 连接方式（OAuth2）

```http
POST https://flairmedia.com.cn:881/admin-api/system/oauth2/token

Authorization: Basic base64(inventory-agent-test:inventory-agent-test)
tenant-id: 1
Content-Type: application/x-www-form-urlencoded

grant_type=password
username=<平台用户名>
password=<平台密码>
```

- 成功返回 `code=0`，取 `data.access_token`；有效期实测 **1799 秒**。
- 令牌是 32 位 hex 的不透明票据，不是 JWT。
- 过期用 `grant_type=refresh_token` 静默续期（返回新 access_token，refresh_token 不变）。
- **不需要图形验证码**；不要用浏览器 F12 复制的会话票据（约 10 分钟就失效）。
- 翻页中途 401：脚本自动重新登录一次并重试当前页。

细节和 curl/PowerShell 原始请求见 [references/api.md](references/api.md)。

---

## 4. 库存接口与抓取规则

```http
GET /admin-api/orders/media-inventory/bus/page
GET /admin-api/orders/media-inventory/metro/page

tenant-id: 1
Authorization: Bearer <access_token>
```

| 参数 | 公交 | 地铁 | 说明 |
|---|---|---|---|
| `startDate` / `endDate` | ✅ | ✅ | 必填，`YYYY-MM-DD`；**日期真实影响库存** |
| `lineName` | ✅ | — | 线路名，服务端**模糊匹配**（`100` 会带出 1001/1002） |
| `keyword` | — | ✅ | 站名或出入口，模糊匹配 |
| `lineLevel` | ✅ | ✅ | 等级编码（公交 1/2/3/5/6；地铁 2/3） |
| `districtname` | — | ✅ | 区编码（含义未确认） |

实测坑（脚本已处理）：

1. **`total` 不可信**：公交报 552，实际 431 行；
2. **每页实返 < `pageSize`**（200 → 155），不能用 `len(items) < pageSize` 判断结束；
3. **`resourceId` 有重复**：431 行只有 430 个不同 ID，不能当主键；
4. 终止条件只认**本页返回 0 条**，另加“连续 3 页无新增”兜底。

字段字典与等级映射见 [references/fields.md](references/fields.md)。

---

## 5. 输出约定

### CSV

- 固定 40 列，列顺序与 `data/snapshots/*.csv` 完全一致；
- 编码 `utf-8-sig`（带 BOM），嵌套字段（如 `districtname=[2]`）写成 JSON 字符串；
- `fetch.py` 默认 `data/hongdou/`，有筛选时文件名带 `_filtered`（可用 `--tag` 自定义）；
  同一目录多次筛选抓取请用 `--tag` 区分，否则 `_filtered` 会互相覆盖；
- `snapshot.py` 默认 `data/snapshots/`，文件名 `{media}_{YYYY-MM-01}_{YYYY-MM-last}.csv`。

### 汇总 JSON（关键字段）

```jsonc
{
  "ok": true,
  "period": {"start": "2027-07-01", "end": "2027-07-31"},
  "results": {
    "bus": {
      "rows": 334,
      "fetched_rows": 431,
      "free_points": 280,
      "totals": {"totalCount": 2525, "contractCount": 758,
                 "reservationCount": 404, "freeCount": 1470},
      "by_level": {"S": {"rows": 47, "free": 300, "total": 400}},
      "top_free": [{"lineName": "100", "freeCount": 2, "level": "A++"}],
      "fetch": {"pages": 3, "api_total": 552, "truncated": false},
      "notes": ["接口声称 total=552，实测以返回行为准；不要拿 total 当库存量。"],
      "file": "data/hongdou/bus_2027-07-01_2027-07-31.csv"
    }
  },
  "inventory_ts": "2026-11-21T13:00:00Z"
}
```

> 上面的数字是形状示例；真实数字以本次查询返回为准。

---

## 6. 数据质量红线（引用数字前必读）

1. **静态台账不能当库存**：台账写公交空位 2,517/2,525，真实 2027-01 档期只有 1,237。任何库存数字都必须来自按目标档期的 API 查询。
2. **必须带档期和时间戳**：“红豆库存 API，档期 X~Y，查询于 Z；可售 freeCount=N；上刊前需重核”。
3. **接口 `total` 不是库存量**：公交 552 vs 实际 431 行；用 `rows` / `fetched_rows`。
4. **`resourceId` 不是主键**：业务键是公交 `(lineName, mediaName)`、地铁 `(lineName, exitName)`。
5. **地铁等级语义未确认**：只保守映射 `2=A++`、`3=A+`；回答要注明“口径待确认”。
6. **封闭/改造点位必须剔除**：`specialSituation` 命中 `封闭/改造/施工/停用/停运` 的地铁点位不能进方案；用 `--exclude-special` 或在分析时说明。
7. **地铁 `freeCount` 是点位状态**：合计 ≈ 有空位的出入口点位数，不是“743 个站”。
8. **公交和地铁不要相加**：媒体口径不同（车辆 vs 出入口）。
9. **不要编没有的字段**：线路几何/客流/区县映射不在红豆库存 API 里；线路几何用 `xinyun-bigdata` skill。
10. **只读**：不要尝试创建订单、修改媒体库或调整库存。

完整口径、实测基准和引用模板见 [references/data-quality.md](references/data-quality.md)。

---

## 7. 与项目管线衔接

```powershell
# 1) 抓月度快照（只写全量原始 40 列，不预过滤）
.venv\Scripts\python.exe $SK\snapshot.py --from-month 2027-01 --to-month 2027-10

# 2) 重建处理后数据（过滤 free<=0 / 封闭点位、等级映射、跨月 min_free）
.venv\Scripts\python.exe scripts\build_dataset.py

# 3) 对账
.venv\Scripts\python.exe scripts\validate_dataset.py
```

- `snapshot.py` 默认**跳过已存在的月份**（幂等重跑）；要拉最新数据加 `--overwrite`。
- `engine/data_loader.py` 从文件名解析月份；文件名必须是 `{media}_{YYYY-MM-01}_{YYYY-MM-last}.csv`。
- 跨月库存取 **min**，不是相加；任一月 `freeCount<=0` 或被封闭，整个业务键不可用。
- **不要**把 `fetch.py` 的筛选结果放进 `data/snapshots/`，否则引擎会误以为这是当月全量库存。
- `snapshot.py` 写的 `hongdou_fetch_manifest.json` 只是抓取审计，不会被管线当输入。

---

## 8. 排错

| 现象 | 处理 |
|---|---|
| `auth.py --status` 退出码 1 | 本地无缓存或已过期；运行 `auth.py`（或直接跑 `fetch.py`，会自动登录） |
| 退出码 2 / “缺少红豆账号” | 设置 `HONGDOU_USER`/`HONGDOU_PASS`，或检查 `scripts/.credentials` 是否两行 |
| 登录 HTTP 400 | 账密错误或 OAuth 客户端未授权；不要重试到封号 |
| 库存接口 401 / `账号未登录` | 令牌过期；直接重跑 `fetch.py`（会自动重新登录）或 `auth.py --fresh` |
| 退出码 4 / `code!=0` | 参数不合法（日期格式、lineLevel 等）；先去掉筛选再试 |
| 退出码 5 / 超时 | 网络问题；脚本已重试 3 次。`snapshot.py` 会跳过失败月份继续 |
| 结果行数比预期少 | 看汇总里的 `fetch.truncated` / `fetch.stalled` / `notes`；可能被 `--max-pages` 截断 |
| 某线路 0 行 | 线路名是模糊匹配；先不加筛选抓全量，用 `analyze.py --facets` 看真实名称 |
| 中文乱码 | 设 `$env:PYTHONIOENCODING='utf-8'`；或把 `--summary-out` 写成文件再读 |
| 证书错误（自己写 HTTP 客户端时） | 该站点是自签证书；curl 加 `-k`，Python `verify=False`（仅比赛环境） |

---

## 9. 安全

- 只使用比赛发放的测试账号；只读。
- 账号密码只在环境变量或 gitignore 的凭证文件里；不写入文档、skill、日志、导出 HTML。
- 令牌缓存 `scripts/.oauth_cache.json` 已 gitignore；不要提交。
- 脚本输出只含令牌长度/剩余时间，不含令牌原文。
- 共享 OAuth 客户端 `inventory-agent-test` 是组委会给所有参赛者的，不是个人密钥；
  生产环境应换成正式客户端凭证。
- 抓取有 0.15–0.2 秒限速，不要改成并发轰炸生产系统。

---

## 10. 文件

```
.claude/skills/hongdou-inventory/
├─ SKILL.md
├─ references/
│  ├─ api.md            # OAuth2 流程、库存接口、翻页算法、退出码
│  ├─ fields.md         # 40 列字段字典、等级映射、唯一键、汇总口径
│  └─ data-quality.md   # 实测基准、静态台账差异、引用模板、管线衔接
└─ scripts/
   ├─ hongdou_lib.py    # OAuth2 / 分页 / CSV / 汇总 共享库
   ├─ auth.py           # 令牌检查与获取
   ├─ fetch.py          # ad-hoc 档期抓取 + 汇总
   ├─ snapshot.py       # 批量月度快照（供引擎）
   ├─ analyze.py        # 离线分析
   └─ .gitignore        # 凭证/令牌缓存
```
