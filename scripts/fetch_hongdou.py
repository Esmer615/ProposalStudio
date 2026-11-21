#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""红豆广告媒体管理系统 —— 库存快照抓取

依据 docs/红豆广告媒体管理系统-库存API接入说明(1).txt：

    公交车媒体库存 (GET)
      /admin-api/orders/media-inventory/bus/page
        ?pageNo=1&pageSize=20&startDate=2026-11-21&endDate=2026-11-21&lineName=100

    地铁出入口库存 (GET)
      /admin-api/orders/media-inventory/metro/page
        ?pageNo=1&pageSize=20&startDate=2026-11-21&endDate=2026-11-21
        &keyword=上海南站        # 可选

    共享请求头
      tenant-id: 1
      Authorization: Bearer <accessToken>

accessToken 从哪来
------------------
用你自己的账号在红豆网页端登录后拿到的令牌，不是另发的密钥。
两种取法（任选其一）：

  A. 浏览器 DevTools（最省事）
     1) Chrome 打开 https://flairmedia.com.cn:881/index 正常登录
     2) F12 -> Application/应用 -> Local Storage -> https://flairmedia.com.cn:881
     3) 找 key 为 ACCESS_TOKEN（可能是 accessToken / access_token）的那一条，
        复制它的 value。注意这个系统的 value 常常是带引号的 JSON 字符串，
        形如 "eyJhbGciOiJIUzI1NiJ9.xxxxx.yyyyy"，**引号和 Bearer 前缀都不要**
     4) 有效期通常几小时，过期就重新登一次再复制

  B. DevTools Network（A 找不到时用）
     1) 登录后在页面里点一下「媒体管理 -> 媒体库」触发任意请求
     2) F12 -> Network -> 点任意一个 admin-api 请求
     3) 看 Request Headers 里的 Authorization: Bearer eyJ...
     4) 把 Bearer 后面那串复制出来

用法
----
    # 1) 放到环境变量（推荐，避免写进命令历史）
    PowerShell:  $env:HONGDOU_TOKEN = "eyJ..."
    Bash:        export HONGDOU_TOKEN="eyJ..."

    # 2) 跑全量快照（2027 全年可售）
    python fetch_hongdou.py --start 2027-01-01 --end 2027-12-31 --out ../data/

    # 3) 只探一张表，确认 token 有效
    python fetch_hongdou.py --start 2027-07-01 --end 2027-07-31 --only bus --pages 1

退出码
------
    0  成功
    2  缺 token
    3  token 无效 / 过期（HTTP 401）
    4  接口返回 code != 0

实测注意事项（2026-11-21）
--------------------------
  * accessToken 是**登录后的会话票据**，不是 JWT（实测是 32 位 hex，如
    726fa5c831f146e1886af7eacb4314fe），从 DevTools 的 Authorization 头取。
  * 接口 total 不可信：bus 报 552，实际 431 条。
  * 每页实返 < pageSize，不能拿 pageSize 判断结束，只能靠"本页返回 0 条"。
  * 详细字段说明见 docs/红豆库存API-字段说明.md
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://flairmedia.com.cn:881"
BUS_PATH = "/admin-api/orders/media-inventory/bus/page"
METRO_PATH = "/admin-api/orders/media-inventory/metro/page"
TENANT_ID = "1"

# 这个系统用自签证书，需要跳过校验（仅比赛环境内网使用）
_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE


TOKEN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".token")

# 让同目录的 hongdou_auth 可被导入
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


class TokenStale(RuntimeError):
    """令牌失效（HTTP 401 或 body 里 code=401）。"""


def make_token_provider(manual_token: str | None):
    """返回一个无参可调用对象，调用即得可用令牌。

    优先级：
      1) --token 参数 / HONGDOU_TOKEN / scripts/.token  —— 手工会话票据，过期就没了
      2) OAuth2 密码模式（hongdou_auth）                  —— 默认走这条，可自动续期

    手工会话票据实测只有几分钟寿命（约 10 分钟后返回 401 账号未登录），
    所以默认走 OAuth2；只有显式给了手工 token 才用老的。
    """
    manual = (manual_token or os.environ.get("HONGDOU_TOKEN", "")).strip()
    if not manual and os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, encoding="utf-8") as f:
            manual = f.read().strip()
    if manual.lower().startswith("bearer "):
        manual = manual[7:].strip()

    import hongdou_auth

    def oauth_provider(force_login: bool = False):
        return hongdou_auth.get_token(force_login=force_login)

    if manual:
        print("（检测到手工令牌：寿命短，失效后自动回退 OAuth2）", file=sys.stderr)

        class _Manual:
            access_token = manual

        def provider(force_login: bool = False):
            if force_login:
                return oauth_provider(force_login=True)
            return _Manual()

        return provider

    return oauth_provider


def request_page(path: str, params: dict, token: str, retries: int = 3) -> dict:
    """单页请求。token 无效时抛 TokenStale，由上层决定是否重新登录。"""
    url = BASE + path + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, method="GET")
    req.add_header("tenant-id", TENANT_ID)
    req.add_header("Authorization", "Bearer " + token)
    req.add_header("Accept", "application/json")
    req.add_header("User-Agent", "Mozilla/5.0 (hongdou-snapshot/1.0)")

    last = None
    for i in range(retries):
        try:
            with urllib.request.urlopen(req, context=_SSL_CTX, timeout=30) as resp:
                payload = json.loads(resp.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            if e.code == 401:
                raise TokenStale("HTTP 401")
            last = f"HTTP {e.code}"
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            last = f"{type(e).__name__}: {e}"
        else:
            # 有些情况下接口返回 200 但 body 里 code=401
            if payload.get("code") == 401:
                raise TokenStale(str(payload.get("msg")))
            return payload
        if i < retries - 1:
            time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"请求失败（{last}）：{url}")


def fetch_all(path: str, base_params: dict, get_token, page_size: int,
              max_pages: int | None = None, label: str = "",
              total_hint: int | None = None) -> list[dict]:
    """翻页抓全量，按 (resourceId, lineName, mediaName) 去重，令牌过期自动重登。

    实测坑（2026-11-21）：
      1) 接口的 total 不可信 —— 公交 total=552，实际只有 431 条（431 是真实线路数，
         552 可能是"线路×媒体类型"的另一口径）。所以不能拿 total 当终止条件。
      2) 每页实际返回条数 < pageSize（pageSize=200 时返 155/139/137），
         所以也不能用 len(items) < page_size 判断结束。
      3) 终止条件只能是：本页返回 0 条。同时用去重后的条数做双保险。

    参数 get_token 是个无参可调用对象，返回带 .access_token 的令牌对象；
    令牌失效时调用方可通过 get_token(force_login=True) 拿新的。
    """
    rows: list[dict] = []
    seen: set = set()
    page = 1
    stall = 0
    token = get_token()
    relogin_done = False

    while True:
        params = dict(base_params, pageNo=page, pageSize=page_size)
        try:
            payload = request_page(path, params, token.access_token)
        except TokenStale:
            if relogin_done:
                print(f"重新登录后仍然失效（{label}），请检查账号权限。", file=sys.stderr)
                sys.exit(3)
            print(f"令牌失效，自动重新登录后继续（{label} 第 {page} 页）", file=sys.stderr)
            token = get_token(force_login=True)
            relogin_done = True
            continue     # 同一页重试一次

        code = payload.get("code", 0)
        if code != 0:
            print(f"接口返回 code={code} msg={payload.get('msg')!r}（{label} 第 {page} 页）", file=sys.stderr)
            sys.exit(4)

        data = payload.get("data")
        if isinstance(data, list):
            items, total = data, None
        elif isinstance(data, dict):
            items = data.get("list") or data.get("records") or data.get("rows") or []
            total = data.get("total")
        else:
            items, total = [], None

        new = 0
        for it in items:
            key = (it.get("resourceId"), it.get("lineName"), it.get("mediaName"))
            if key in seen:
                continue
            seen.add(key)
            rows.append(it)
            new += 1

        print(f"  {label} 第 {page} 页: 返回 {len(items)} 条，新增 {new} 条"
              + (f"，累计 {len(rows)}（接口声称 {total}）" if total is not None else
                 f"，累计 {len(rows)}"),
              file=sys.stderr)

        if not items:
            break
        if max_pages and page >= max_pages:
            print(f"  到达 --pages 上限 {max_pages}，停止翻页", file=sys.stderr)
            break
        if total_hint and len(rows) >= total_hint:
            break
        # 连续 3 页没有新增 => 后端在重复返回同一批，停止
        if new == 0 and page > 1:
            stall += 1
            if stall >= 3:
                print("  连续多页无新增数据，停止翻页（疑似后端分页失效）", file=sys.stderr)
                break
        else:
            stall = 0
        page += 1
        time.sleep(0.15)   # 轻微限速，避免给生产系统压力
    return rows


def flatten(rows: list[dict]) -> list[dict]:
    """把嵌套的 dict/list 字段压平，方便丢进 CSV / pandas"""
    out = []
    for r in rows:
        flat = {}
        for k, v in r.items():
            if isinstance(v, (dict, list)):
                flat[k] = json.dumps(v, ensure_ascii=False)
            else:
                flat[k] = v
        out.append(flat)
    return out


def write_csv(path: str, rows: list[dict]) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    if not rows:
        print(f"  (无数据，跳过 {path})", file=sys.stderr)
        return
    cols = list(rows[0].keys())
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"  -> {path} ({len(rows)} 行, {len(cols)} 列)", file=sys.stderr)


def main() -> int:
    ap = argparse.ArgumentParser(description="红豆库存 API 快照")
    ap.add_argument("--token", help="手工会话票据（可选；默认走 OAuth2 自动登录）")
    ap.add_argument("--user", help="平台用户名（默认从 scripts/.credentials 读）")
    ap.add_argument("--password", help="平台密码（默认从 scripts/.credentials 读）")
    ap.add_argument("--start", required=True, help="开始日期 YYYY-MM-DD")
    ap.add_argument("--end", required=True, help="结束日期 YYYY-MM-DD")
    ap.add_argument("--line-name", default=None, help="公交线路名，如 100；不填即全部")
    ap.add_argument("--keyword", default=None, help="地铁站名/出入口，如 上海南站；不填即全部")
    ap.add_argument("--page-size", type=int, default=200)
    ap.add_argument("--pages", type=int, default=None, help="最多翻几页（调试用）")
    ap.add_argument("--only", choices=("bus", "metro"), default=None)
    ap.add_argument("--out", default="../data", help="输出目录")
    args = ap.parse_args()

    if args.user and args.password:
        os.environ["HONGDOU_USER"] = args.user
        os.environ["HONGDOU_PASS"] = args.password

    provider = make_token_provider(args.token)
    print(f"时间范围 {args.start} ~ {args.end}", file=sys.stderr)

    summary = {}

    if args.only in (None, "bus"):
        print("抓取：公交车媒体库存", file=sys.stderr)
        p = {"startDate": args.start, "endDate": args.end}
        if args.line_name:
            p["lineName"] = args.line_name
        rows = fetch_all(BUS_PATH, p, provider, args.page_size, args.pages, "bus")
        rows = flatten(rows)
        write_csv(os.path.join(args.out, f"bus_{args.start}_{args.end}.csv"), rows)
        summary["bus"] = len(rows)

    if args.only in (None, "metro"):
        print("抓取：地铁出入口库存", file=sys.stderr)
        p = {"startDate": args.start, "endDate": args.end}
        if args.keyword:
            p["keyword"] = args.keyword
        rows = fetch_all(METRO_PATH, p, provider, args.page_size, args.pages, "metro")
        rows = flatten(rows)
        write_csv(os.path.join(args.out, f"metro_{args.start}_{args.end}.csv"), rows)
        summary["metro"] = len(rows)

    print("\n完成：" + json.dumps(summary, ensure_ascii=False), file=sys.stderr)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        sys.exit(5)