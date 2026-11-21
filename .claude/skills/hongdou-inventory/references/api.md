# 红豆库存 API · 连接与接口细节

> 实测环境：`https://flairmedia.com.cn:881`，`tenant-id: 1`，比赛测试账号
> 实测时间：2026-11-21
> 本 skill 只读：只调用登录 + 两个库存查询接口，不创建订单、不改媒体库。

---

## 1. OAuth2 客户端登录（推荐，脚本默认走这条）

所有对接账号共用同一个 OAuth 客户端；每个人仍用自己的平台用户名/密码取令牌。

```http
POST /admin-api/system/oauth2/token

Authorization: Basic base64(inventory-agent-test:inventory-agent-test)
tenant-id: 1
Content-Type: application/x-www-form-urlencoded
Accept: application/json

grant_type=password
username=<平台用户名>
password=<平台密码>
```

成功响应：

```json
{
  "code": 0,
  "data": {
    "access_token": "<access_token>",
    "refresh_token": "<refresh_token>",
    "expires_in": 1799
  }
}
```

- **不需要图形验证码**。
- `access_token` 是 32 位 hex 的不透明会话票据，不是 JWT。
- 有效期实测 **1799 秒（约 30 分钟）**。
- 令牌过期后请求库存接口返回：
  ```json
  {"code": 401, "msg": "账号未登录", "data": null}
  ```

### 续期

```http
POST /admin-api/system/oauth2/token
（同样的 Basic 认证 + tenant-id）

grant_type=refresh_token
refresh_token=<上次返回的 refresh_token>
```

实测：续期成功返回**新的 access_token**（旧 token 作废），`refresh_token` 保持不变，可重复使用。

### 令牌生命周期（脚本已实现）

```
get_token()
  ├─ 缓存里有令牌且剩余 >120s          → 直接用
  ├─ 缓存里有令牌但快过期              → refresh_token 续期
  ├─ 续期失败 / 没有缓存               → 用账号密码重新登录
  └─ 登录失败                          → AuthError（退出码 2）

翻页过程中某页 401 → 强制重新登录一次 → 重试同一页
重新登录后仍 401   → AuthError（退出码 3 语义）
```

### 凭证来源（按优先级）

1. 环境变量 `HONGDOU_USER` + `HONGDOU_PASS`（必须同时设置）；
2. `HONGDOU_CREDENTIALS` 指定文件的路径；
3. 项目 `scripts/.credentials`（第一行用户名，第二行密码；已 gitignore）；
4. skill 内 `scripts/.credentials`（本地兜底；skill 的 `.gitignore` 已忽略）。

允许 `#` 注释行。脚本只打印来源路径，不打印账号密码或令牌原文。

### 令牌缓存

默认：`.claude/skills/hongdou-inventory/scripts/.oauth_cache.json`（已 gitignore）。
可用 `HONGDOU_TOKEN_CACHE` 覆盖路径。缓存里记录 `base`，换环境后不会误用旧环境的令牌。

---

## 2. 库存查询接口

两个接口共用请求头：

```http
tenant-id: 1
Authorization: Bearer <access_token>
Accept: application/json
```

### 2.1 公交车媒体库存

```http
GET /admin-api/orders/media-inventory/bus/page
```

| 参数 | 必填 | 说明 | 实测行为 |
|---|---|---|---|
| `pageNo` | 是 | 页码，从 1 开始 | — |
| `pageSize` | 是 | 每页条数 | **实返条数 < pageSize** |
| `startDate` | 是 | `YYYY-MM-DD` | 影响库存占用 |
| `endDate` | 是 | `YYYY-MM-DD` | 同上 |
| `lineName` | 否 | 线路名 | **模糊匹配**：`100` → 100/1001/1002… |
| `lineLevel` | 否 | 等级编码 `1/2/3/5/6` | 服务端生效 |

### 2.2 地铁出入口库存

```http
GET /admin-api/orders/media-inventory/metro/page
```

| 参数 | 必填 | 说明 | 实测行为 |
|---|---|---|---|
| `pageNo` / `pageSize` | 是 | 分页 | 正常分页 |
| `startDate` / `endDate` | 是 | 日期 | — |
| `keyword` | 否 | 站名或出入口名 | 模糊匹配：`上海南站` → 3 条 |
| `districtname` | 否 | 区编码 | `2` → 84 条（**编码含义未确认**） |
| `lineLevel` | 否 | 等级编码 | 地铁没有 1 级 |

试过但**无效**的参数名（传了不报错，只是不生效）：
`level`、`lineType`、`mediaName`、`mediaType`、`companyName`、`operatingCompany`、`stationAttr`。

> 网页上的“媒体类型 / 行车公司 / 代理名称 / 扩展状态”筛选参数名没找到。
> 需要时用本 skill 抓回后本地过滤（`--company`、`--media-name`）。

### 2.3 响应包络

```json
{
  "code": 0,
  "msg": "success",
  "data": {
    "list": [ { "resourceType": "BUS_VEHICLE", "...": "..." } ],
    "total": 552
  }
}
```

`data` 可能是数组，也可能是 `{list|records|rows, total}`；脚本三种都兼容。

### 2.4 原始请求示例（排错用）

Bash：

```bash
TOKEN='...'
curl -k \
  -H "tenant-id: 1" \
  -H "Authorization: Bearer $TOKEN" \
  "https://flairmedia.com.cn:881/admin-api/orders/media-inventory/bus/page?pageNo=1&pageSize=20&startDate=2027-07-01&endDate=2027-07-31&lineName=100"
```

PowerShell：

```powershell
$h = @{ 'tenant-id' = '1'; Authorization = "Bearer $env:HONGDOU_TOKEN" }
Invoke-RestMethod -Headers $h -Uri (
  'https://flairmedia.com.cn:881/admin-api/orders/media-inventory/metro/page' +
  '?pageNo=1&pageSize=20&startDate=2027-07-01&endDate=2027-07-31&keyword=上海南站'
)
```

> 自签证书：直接用 curl/Invoke-RestMethod 可能报证书错误。脚本已对这个主机关闭校验；
> 手工调试时 curl 加 `-k`。生产环境应换成受信证书。

---

## 3. 翻页算法（协议坑的应对）

实测三个坑：

1. **`total` 不可信**：公交 `total=552`，实际只有 431 行。431 与资料包台账行数一致。
2. **每页实返 < `pageSize`**：
   ```
   pageSize=20   -> 19
   pageSize=100  -> 94
   pageSize=200  -> 155
   pageSize=1000 -> 431
   ```
   所以不能拿 `len(items) < pageSize` 判断结束。
3. **`resourceId` 有重复**：431 行只有 430 个不同 ID。
   抓取按 `(resourceId, lineName, mediaName)`（地铁 `(resourceId, lineName, exitName)`）去重。

脚本的终止条件：

```
本页返回 0 条 → 停止
或 连续 3 页无新增 → 停止（后端口径异常兜底）
或 到达 --max-pages / 内置 1000 页上限 → 停止并标记 truncated
```

> 公交 431 行、地铁 861 行是 2026-11-21 的实测基准，用于 sanity check，不是常量。

---

## 4. 错误与退出码

| 现象 | 含义 | 脚本退出码 |
|---|---|---|
| 缺 `HONGDOU_USER/HONGDOU_PASS` 或凭证文件不足两行 | 缺凭证 | 2 |
| HTTP 400/401/403 于登录接口 | 账密错误 / 客户端未授权 | 2 |
| 库存接口 401 或 body `code=401`，重新登录后仍失败 | 令牌失效 | 3 |
| 库存接口 `code != 0`、HTTP 400/403 | 参数/权限错误 | 4 |
| 超时、DNS、TLS、响应非 JSON | 网络错误 | 5 |
| `--max-pages` 截断 | 结果不完整（仍有 `ok:true`） | 0 |
| snapshot 单月失败 | 该月未写入 | 失败数量（上限 125） |

CLI 的错误 JSON 也是 stdout：

```json
{"ok": false, "error": "...", "error_type": "auth|token_stale|api|network|usage|interrupted"}
```

---

## 5. 为什么不用浏览器 F12 会话票据

| | F12 会话票据 | OAuth2 客户端登录 |
|---|---|---|
| 有效期 | 约 10 分钟后失效 | 1799 秒，可 refresh |
| 能否续期 | 必须重新复制 | 自动续期 |
| 适合批量 | 抓一半 401 | 支持长批任务 |
| 需要验证码 | 网页登录需要 | 不需要 |

本 skill **不走 F12**。`--token` 之类的应急入口也没有提供；如果令牌出问题，重跑 `auth.py --fresh`。
