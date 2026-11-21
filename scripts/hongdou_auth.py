# -*- coding: utf-8 -*-
"""红豆 OAuth2 登录客户端

依据 docs/红豆广告媒体管理系统-OAuth2客户端登录说明.txt：

    POST https://flairmedia.com.cn:881/admin-api/system/oauth2/token
    HTTP Basic:  inventory-agent-test / inventory-agent-test
    Headers:     tenant-id: 1
                 Content-Type: application/x-www-form-urlencoded
    Form:        grant_type=password
                 username=<平台用户名>
                 password=<平台密码>

    返回 code=0 时取 data.access_token，有效期 data.expires_in 秒。
    此流程不需要图形验证码。

相比从浏览器 F12 复制会话票据（有效期只有几分钟），
这里拿到的是标准 OAuth2 访问令牌，可以自动刷新、可长期跑批。
"""
from __future__ import annotations

import base64
import json
import os
import ssl
import sys
import time
from dataclasses import dataclass

import urllib.error
import urllib.parse
import urllib.request

BASE = "https://flairmedia.com.cn:881"
TOKEN_PATH = "/admin-api/system/oauth2/token"
TENANT_ID = "1"

CLIENT_ID = "inventory-agent-test"
CLIENT_SECRET = "inventory-agent-test"

_SSL = ssl.create_default_context()
_SSL.check_hostname = False
_SSL.verify_mode = ssl.CERT_NONE

CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".oauth_cache.json")


@dataclass
class Token:
    access_token: str
    refresh_token: str | None
    expires_in: int
    obtained_at: float

    @property
    def expires_at(self) -> float:
        return self.obtained_at + self.expires_in

    def is_fresh(self, margin: int = 120) -> bool:
        """提前 120 秒判定过期，避免边界情况下请求刚好失效"""
        return time.time() < self.expires_at - margin


def _post_form(path: str, data: dict, headers: dict) -> dict:
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(BASE + path, data=body, method="POST")
    for k, v in headers.items():
        req.add_header(k, v)
    with urllib.request.urlopen(req, context=_SSL, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def login(username: str, password: str, retries: int = 3) -> Token:
    """password 模式取令牌。不需要验证码。"""
    basic = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
    headers = {
        "Authorization": "Basic " + basic,
        "tenant-id": TENANT_ID,
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
    }
    form = {"grant_type": "password", "username": username, "password": password}

    last = None
    for i in range(retries):
        try:
            payload = _post_form(TOKEN_PATH, form, headers)
        except urllib.error.HTTPError as e:
            # 400 通常意味着账密错误或客户端未授权，重试无意义
            detail = e.read().decode("utf-8", "replace")[:300]
            if e.code in (400, 401):
                raise RuntimeError(f"登录失败 HTTP {e.code}: {detail}") from None
            last = f"HTTP {e.code}: {detail}"
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            last = f"{type(e).__name__}: {e}"
        else:
            code = payload.get("code", 0)
            data = payload.get("data") or {}
            tok = data.get("access_token")
            if code == 0 and tok:
                return Token(
                    access_token=tok,
                    refresh_token=data.get("refresh_token"),
                    expires_in=int(data.get("expires_in") or 1800),
                    obtained_at=time.time(),
                )
            raise RuntimeError(
                f"登录返回 code={code} msg={payload.get('msg')!r} data={data!r}"
            )
        if i < retries - 1:
            time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"登录请求失败：{last}")


def refresh(tok: Token) -> Token:
    """用 refresh_token 续期；失败则抛异常，由调用方决定是否重新登录"""
    if not tok.refresh_token:
        raise RuntimeError("没有 refresh_token，无法静默续期")
    basic = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
    headers = {
        "Authorization": "Basic " + basic,
        "tenant-id": TENANT_ID,
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
    }
    form = {"grant_type": "refresh_token", "refresh_token": tok.refresh_token}
    payload = _post_form(TOKEN_PATH, form, headers)
    data = payload.get("data") or {}
    if payload.get("code") != 0 or not data.get("access_token"):
        raise RuntimeError(f"续期失败 code={payload.get('code')} msg={payload.get('msg')!r}")
    return Token(
        access_token=data["access_token"],
        refresh_token=data.get("refresh_token") or tok.refresh_token,
        expires_in=int(data.get("expires_in") or 1800),
        obtained_at=time.time(),
    )


def load_cache() -> Token | None:
    if not os.path.exists(CACHE_FILE):
        return None
    try:
        with open(CACHE_FILE, encoding="utf-8") as f:
            d = json.load(f)
        return Token(d["access_token"], d.get("refresh_token"),
                     int(d["expires_in"]), float(d["obtained_at"]))
    except Exception:
        return None


def save_cache(tok: Token) -> None:
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump({
            "access_token": tok.access_token,
            "refresh_token": tok.refresh_token,
            "expires_in": tok.expires_in,
            "obtained_at": tok.obtained_at,
        }, f)


def get_credentials() -> tuple[str, str]:
    """账号来源顺序：环境变量 > scripts/.token（此处存 username:password 两行）"""
    u = os.environ.get("HONGDOU_USER", "").strip()
    p = os.environ.get("HONGDOU_PASS", "").strip()
    if u and p:
        return u, p
    if os.path.exists(CACHE_FILE.replace(".oauth_cache.json", ".credentials")):
        path = CACHE_FILE.replace(".oauth_cache.json", ".credentials")
        lines = [ln.strip() for ln in open(path, encoding="utf-8") if ln.strip()]
        if len(lines) >= 2:
            return lines[0], lines[1]
    print(
        "缺少账号。两种给法：\n"
        "  1) 环境变量:  $env:HONGDOU_USER='test16'; $env:HONGDOU_PASS='<密码>'\n"
        "  2) 文件:      scripts/.credentials  第一行用户名，第二行密码",
        file=sys.stderr,
    )
    sys.exit(2)


def get_token(force_login: bool = False) -> Token:
    """统一入口：缓存可用则复用，过期则尝试 refresh，再不行才重新登录"""
    if not force_login:
        cached = load_cache()
        if cached:
            if cached.is_fresh():
                return cached
            try:
                tok = refresh(cached)
                save_cache(tok)
                print("（令牌已用 refresh_token 续期）", file=sys.stderr)
                return tok
            except Exception:
                pass   # 落到重新登录
    user, pwd = get_credentials()
    tok = login(user, pwd)
    save_cache(tok)
    print(f"（OAuth2 登录成功，有效期 {tok.expires_in}s）", file=sys.stderr)
    return tok


if __name__ == "__main__":
    t = get_token(force_login="--fresh" in sys.argv)
    print(json.dumps({
        "access_token_len": len(t.access_token),
        "access_token_head": t.access_token[:12] + "...",
        "expires_in": t.expires_in,
        "has_refresh_token": bool(t.refresh_token),
        "remaining_sec": round(t.expires_at - time.time()),
    }, ensure_ascii=False, indent=1))