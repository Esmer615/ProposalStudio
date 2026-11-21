# 红豆数据获取 · 首选方案：OAuth2 客户端登录

> 结论：**OAuth2 稳定、可自动续期、可长期跑批。后续一律用这个，不要再用浏览器 F12 扒会话票据。**

---

## 一、两种取令牌方式对比（实测）

| | 浏览器 F12 会话票据 | **OAuth2 客户端登录** |
|---|---|---|
| 来源 | 登录网页后 Local Storage / Network 头 | `POST /admin-api/system/oauth2/token` |
| 形态 | 32 位 hex 会话 ID | 32 位 hex `access_token` + `refresh_token` |
| 有效期 | **约 10 分钟后失效** | **1799 秒（30 分钟）** |
| 能否续期 | ❌ 必须重新 F12 复制 | ✅ `grant_type=refresh_token` 静默续期 |
| 需要验证码 | 网页登录需要 | **不需要** |
| 适合批量跑 | ❌ 抓一半就 401 | ✅ |
| 实测结论 | 抓完一轮后再请求 → `{"code":401,"msg":"账号未登录"}` | 连续跑多个档期、多次翻页全部成功 |

---

## 二、接口

```http
POST https://flairmedia.com.cn:881/admin-api/system/oauth2/token
HTTP Basic:  inventory-agent-test / inventory-agent-test
Headers:
  tenant-id: 1
  Content-Type: application/x-www-form-urlencoded

Form:
  grant_type=password
  username=<平台用户名>
  password=<平台密码>
```

成功返回：

```json
{
  "code": 0,
  "data": {
    "access_token": "58a45a26b245...",
    "refresh_token": "1685f8d6d5cd...",
    "expires_in": 1799
  }
}
```

续期：

```http
POST /admin-api/system/oauth2/token
（同样的 Basic 认证 + tenant-id）
Form:
  grant_type=refresh_token
  refresh_token=<上一步拿到的 refresh_token>
```

> 实测：续期成功，返回**新的 access_token**（旧 token 作废），
> `refresh_token` 保持不变（可重复使用）。
> 所以只需在 `.credentials` 里存用户名密码，令牌完全自动化管理，不用人手干预。

调用库存接口时：

```http
GET /admin-api/orders/media-inventory/bus/page?...
tenant-id: 1
Authorization: Bearer <access_token>
```

---

## 三、实现

| 文件 | 作用 |
|---|---|
| `scripts/hongdou_auth.py` | OAuth2 登录 / 续期 / 令牌缓存 |
| `scripts/fetch_hongdou.py` | 库存抓取（自动调用上面那个） |
| `scripts/.credentials` | 两行：用户名、密码（**已 gitignore**） |
| `scripts/.oauth_cache.json` | 令牌缓存（自动生成，**已 gitignore**） |

令牌生命周期管理逻辑：

```
get_token()
  ├─ 缓存里有令牌且未过期（留 120 秒余量）→ 直接用
  ├─ 缓存里有令牌但快过期 → 用 refresh_token 续期
  ├─ 续期失败 / 没有缓存 → 用 .credentials 里的账号密码重新登录
  └─ 都失败 → 退出码 2，明确报错
```

抓取过程中若某页返回 401（或 body 里 `code=401`），会自动重新登录一次然后继续，
不会中断整批任务。

---

## 四、怎么用

```powershell
$PY = "C:/Users/20614/AppData/Local/Python/pythoncore-3.14-64/python.exe"

# 1) 首次：把账号写进 scripts/.credentials（两行：用户名、密码）
#    或临时用环境变量
$env:HONGDOU_USER = "test16"
$env:HONGDOU_PASS = "<密码>"

# 2) 验证登录
& $PY scripts/hongdou_auth.py

# 3) 抓数据（默认走 OAuth2，无需任何 token 参数）
& $PY scripts/fetch_hongdou.py --start 2027-01-01 --end 2027-12-31
```

不再需要 `--token`。`--token` 仍然保留，但只在应急时用（会自动回退到 OAuth2）。

---

## 五、实测数据：日期参数是真实生效的（这是核心价值）

同一个接口，只改 `startDate`/`endDate`，库存完全不同：

### 公交 431 条的可售空位总量

| 档期 | 可售空位 |
|---|---|
| 今天 2026-11-21 | **888** |
| 2027-01 | **1237** |
| 2027-07 | **1470** |
| 2027-12 | **2128** |

### 地铁 861 个点位的可售空位总量

| 档期 | 可售空位 | 合同占用 |
|---|---|---|
| 今天 2026-11-21 | **334** | 527 |
| 2027-01 | **743** | 96 |
| 2027-07 | **845** | 14 |

### 单条线路（100 路）的跨档期变化

| 档期 | 总 | 合同 | 预定 | 空 |
|---|---|---|---|---|
| 2027-01 | 8 | 1 | 5 | 2 |
| 2027-07 | 8 | 1 | 5 | 2 |
| 2026-11-21 | 8 | 7 | 0 | **1** |

> 结论：**档期越远，库存越空**（还没被卖出去）。
> 这直接决定了方案设计：2027 年的方案可售空间远大于"今天"的视角，
> 如果只看静态台账（写死空位 2517）会严重误判。

---

## 六、踩过的坑（已在代码里处理）

| 坑 | 现象 | 处理 |
|---|---|---|
| `total` 不可信 | 公交报 552，实际 431 | 不拿 total 当终止条件，只认"本页返回 0 条" |
| 每页实返 < pageSize | pageSize=200 只返 155/139/137 | 同上，不做 `<pageSize` 判断 |
| `resourceId` 重复 | 431 条只有 430 个 ID | 按 `(resourceId, lineName, mediaName)` 去重 |
| 会话票据短命 | 约 10 分钟后 401 | **改用 OAuth2（本文方案）** |
| 自签证书 | `SSL: CERTIFICATE_VERIFY_FAILED` | 脚本内关掉校验（仅比赛内网） |

---

## 七、安全说明

- `scripts/.credentials`、`scripts/.oauth_cache.json` 都在 `.gitignore` 里
- 令牌**不落日志**：脚本只打印长度/前 12 位
- OAuth 客户端 ID/Secret 是组委会给所有参赛者共用的，不是个人密钥
- 生产环境应该换成正式的客户端凭证，别把 `inventory-agent-test` 带出去

---

## 八、下一步

数据已经有了（`data/` 下两份 CSV），接下来把 `prototypes/bus_optimizer.py`
的数据源从静态 xlsx 换成这两份 CSV，然后按**真实档期可售**重跑三档预算方案。
