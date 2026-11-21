#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""检查/获取红豆 OAuth2 令牌。

用法：
    python auth.py                 # 确保有可用令牌（缓存 -> refresh -> 登录）
    python auth.py --fresh         # 忽略缓存，强制重新登录
    python auth.py --status        # 只读本地缓存，不发网络请求

输出是 JSON（stdout），永远不打印 access_token / refresh_token 原文。
退出码：0 有可用令牌；1 status 下无可用缓存；2 缺凭证/账密错误；
        3 令牌失效；4 接口错误；5 网络错误。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone

import hongdou_lib as hd


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _print(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def main() -> int:
    hd.ensure_utf8_stdio()
    parser = argparse.ArgumentParser(
        description="红豆广告媒体管理系统 OAuth2 令牌检查/获取（只读，不打印令牌原文）",
    )
    parser.add_argument("--status", action="store_true",
                        help="只检查本地缓存，不发网络请求")
    parser.add_argument("--fresh", action="store_true",
                        help="忽略缓存，强制用账号密码重新登录")
    parser.add_argument("--quiet", action="store_true", help="不打印过程信息")
    args = parser.parse_args()

    try:
        if args.status:
            tok = hd.load_cache()
            if not tok:
                _print({
                    "ok": False,
                    "authenticated": False,
                    "cached": False,
                    "cache_path": hd.display_path(hd.token_cache_path()),
                    "message": "无令牌缓存；运行 auth.py 获取令牌",
                })
                return 1
            fresh = tok.is_fresh()
            _print({
                "ok": fresh,
                "authenticated": fresh,
                "cached": True,
                "fresh": fresh,
                "remaining_sec": round(tok.expires_at - time.time()),
                "expires_at": _iso(tok.expires_at),
                "has_refresh_token": bool(tok.refresh_token),
                "access_token_len": len(tok.access_token),
                "cache_path": hd.display_path(hd.token_cache_path()),
                "base": hd.BASE,
            })
            return 0 if fresh else 1

        tok = hd.get_token(force_login=args.fresh, verbose=not args.quiet)
        try:
            _, _, source = hd.credentials()
        except hd.AuthError:
            source = "(缓存令牌；未读取凭证)"
        _print({
            "ok": True,
            "authenticated": True,
            "remaining_sec": round(tok.expires_at - time.time()),
            "expires_at": _iso(tok.expires_at),
            "expires_in": tok.expires_in,
            "has_refresh_token": bool(tok.refresh_token),
            "access_token_len": len(tok.access_token),
            "credential_source": source,
            "cache_path": hd.display_path(hd.token_cache_path()),
            "tenant_id": hd.TENANT_ID,
            "base": hd.BASE,
        })
        return 0

    except hd.AuthError as e:
        _print({"ok": False, "error": str(e), "error_type": "auth"})
        print(str(e), file=sys.stderr)
        return 2
    except hd.TokenStale as e:
        _print({"ok": False, "error": str(e), "error_type": "token_stale"})
        print(str(e), file=sys.stderr)
        return 3
    except hd.ApiError as e:
        _print({"ok": False, "error": str(e), "error_type": "api"})
        print(str(e), file=sys.stderr)
        return 4
    except hd.NetworkError as e:
        _print({"ok": False, "error": str(e), "error_type": "network"})
        print(str(e), file=sys.stderr)
        return 5
    except KeyboardInterrupt:
        _print({"ok": False, "error": "已中断", "error_type": "interrupted"})
        return 130


if __name__ == "__main__":
    sys.exit(main())
