# -*- coding: utf-8 -*-
"""红豆广告媒体管理系统 · 库存 API 共享库

提供四件事，全部只依赖 Python 标准库：

1. OAuth2 客户端密码模式登录 / refresh_token 续期 / 本地令牌缓存；
2. 公交（BUS_VEHICLE）、地铁（METRO_GATE）库存的分页抓取，
   处理接口的 total 不可信、短页、resourceId 重复等实测坑；
3. 原始 40 列 CSV 读写（utf-8-sig，与 data/snapshots 管线兼容）；
4. 档期可售汇总、等级映射、特殊状态过滤、离线分组/维度统计。

安全约定：账号密码只从环境变量或 gitignore 的凭证文件读取；
令牌只写本地缓存；本库的所有输出都不包含令牌或密码原文。
"""
from __future__ import annotations

import base64
import calendar
import csv
import hashlib
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timezone


# --------------------------------------------------------------------------- #
# 路径与常量
# --------------------------------------------------------------------------- #
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(SCRIPT_DIR)


def _find_project_root(start: str) -> str:
    """从 skill 目录向上找项目根（认 scripts/ + data/ + engine/ 三件套）。

    本项目里是 .claude/skills/hongdou-inventory -> 向上三级。
    如果 skill 被复制到别的目录，退回当前工作目录，输出落在 ./data 下。
    """
    cur = start
    for _ in range(6):
        if all(os.path.isdir(os.path.join(cur, n)) for n in ("scripts", "data", "engine")):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    return os.getcwd()


PROJECT_ROOT = _find_project_root(SKILL_DIR)

# 系统地址与共享 OAuth 客户端（组委会给所有参赛账号共用，不是个人密钥）。
# 需要指向别的环境时用环境变量覆盖。
BASE = os.environ.get("HONGDOU_BASE", "https://flairmedia.com.cn:881").rstrip("/")
TENANT_ID = os.environ.get("HONGDOU_TENANT", "1")
CLIENT_ID = os.environ.get("HONGDOU_CLIENT_ID", "inventory-agent-test")
CLIENT_SECRET = os.environ.get("HONGDOU_CLIENT_SECRET", "inventory-agent-test")

TOKEN_PATH = "/admin-api/system/oauth2/token"
MEDIA_PATHS = {
    "bus": "/admin-api/orders/media-inventory/bus/page",
    "metro": "/admin-api/orders/media-inventory/metro/page",
}
MEDIA_TYPES = {"bus": "BUS_VEHICLE", "metro": "METRO_GATE"}

# 红豆系统用自签证书，只有这个比赛环境需要跳过校验。
_SSL = ssl.create_default_context()
_SSL.check_hostname = False
_SSL.verify_mode = ssl.CERT_NONE

# 公交/地铁接口实际返回的 40 个字段，顺序与 data/snapshots/*.csv 完全一致。
CANONICAL_FIELDS = [
    "resourceType", "resourceId", "lineName", "companyName", "lineLevel",
    "mediaName", "metroNumber", "stationAttr", "exitName", "districtname",
    "businessAreaName", "categoryTags", "prompt", "greeningMetroLogo",
    "specialSituation", "amapLine", "operatingCompany", "grilleType",
    "outdoorNumber", "locationstr", "production", "mediatypename", "roadname",
    "totalhour", "unittime", "frequency", "unitmea", "totalCount",
    "contractCount", "reservationCount", "freeCount",
    "maintenanceForbiddenCount", "renewPossibleCount", "protectCount",
    "canViewKeepvehicle", "keepvehicleCount", "contractDurationMinutes",
    "reservationDurationMinutes", "freeDurationMinutes", "totalDurationMinutes",
]
assert len(CANONICAL_FIELDS) == 40, "红豆库存接口固定 40 列"

# lineLevel 编码 -> 等级名。公交已交叉验证；地铁语义未确认，只做保守映射。
LEVEL_MAPS = {
    "bus": {"1": "S", "2": "A++", "3": "A+", "5": "AA"},
    "metro": {"2": "A++", "3": "A+"},
}
LEVEL_ORDER = ["S", "A++", "A+", "AA", "unknown"]

# 方案排期必须剔除的封闭/改造状态关键词（与 scripts/build_dataset.py 一致）。
SPECIAL_BLOCK_WORDS = ("封闭", "改造", "施工", "停用", "停运")

TOTAL_FIELDS = [
    "totalCount", "contractCount", "reservationCount", "freeCount",
    "maintenanceForbiddenCount", "renewPossibleCount", "protectCount",
    "keepvehicleCount",
]

HARD_PAGE_CAP = 1000   # 防止后端分页失效导致死循环


# --------------------------------------------------------------------------- #
# 异常与退出码约定
# --------------------------------------------------------------------------- #
class HongdouError(RuntimeError):
    """所有可预期错误的基类。"""


class AuthError(HongdouError):
    """缺凭证、账密错误、无权限。CLI 退出码 2。"""


class TokenStale(HongdouError):
    """令牌失效（HTTP 401 / body code=401）。CLI 退出码 3。"""


class ApiError(HongdouError):
    """接口返回 code != 0（参数错误等）。CLI 退出码 4。"""


class NetworkError(HongdouError):
    """网络/超时/响应不是 JSON。CLI 退出码 5。"""


# --------------------------------------------------------------------------- #
# IO 小工具
# --------------------------------------------------------------------------- #
def ensure_utf8_stdio() -> None:
    """Windows 控制台默认 GBK，中文 JSON 会花；能改就改成 UTF-8。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def log_stderr(msg: str, quiet: bool = False) -> None:
    if not quiet:
        print(msg, file=sys.stderr)


def display_path(path: str) -> str:
    """项目内路径显示为相对路径，便于 agent 读取。"""
    try:
        rel = os.path.relpath(os.path.abspath(path), PROJECT_ROOT)
    except ValueError:
        return os.path.abspath(path)
    return rel if not rel.startswith("..") else os.path.abspath(path)


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def safe_tag(value: str) -> str:
    tag = re.sub(r"[^\w.-]+", "-", str(value), flags=re.UNICODE).strip("-.")
    return tag or "filtered"


# --------------------------------------------------------------------------- #
# OAuth2：登录 / 续期 / 缓存 / 凭证
# --------------------------------------------------------------------------- #
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
        """提前 120 秒判过期，避免请求边界上刚好失效。"""
        return time.time() < self.expires_at - margin


def token_cache_path() -> str:
    return os.environ.get("HONGDOU_TOKEN_CACHE") or os.path.join(SCRIPT_DIR, ".oauth_cache.json")


def load_cache() -> Token | None:
    path = token_cache_path()
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        if d.get("base") and d["base"] != BASE:
            return None
        return Token(
            access_token=str(d["access_token"]),
            refresh_token=d.get("refresh_token"),
            expires_in=int(d["expires_in"]),
            obtained_at=float(d["obtained_at"]),
        )
    except (OSError, ValueError, KeyError, TypeError):
        return None


def save_cache(tok: Token) -> None:
    path = token_cache_path()
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({
            "access_token": tok.access_token,
            "refresh_token": tok.refresh_token,
            "expires_in": tok.expires_in,
            "obtained_at": tok.obtained_at,
            "base": BASE,
        }, f)
    os.replace(tmp, path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _parse_credentials_file(path: str) -> tuple[str, str] | None:
    try:
        with open(path, encoding="utf-8-sig") as f:
            lines = [
                ln.strip() for ln in f
                if ln.strip() and not ln.lstrip().startswith("#")
            ]
    except OSError:
        return None
    if len(lines) >= 2:
        return lines[0], lines[1]
    return None


def credentials() -> tuple[str, str, str]:
    """返回 (用户名, 密码, 来源描述)。来源描述不含密码。

    优先级：
      1) HONGDOU_USER / HONGDOU_PASS（必须同时设置）
      2) HONGDOU_CREDENTIALS 指定的文件
      3) 项目 scripts/.credentials
      4) skill 内 scripts/.credentials
    文件格式：第一行用户名，第二行密码；允许 # 注释。
    """
    env_user = os.environ.get("HONGDOU_USER", "").strip()
    env_pass = os.environ.get("HONGDOU_PASS", "").strip()
    if env_user or env_pass:
        if not (env_user and env_pass):
            raise AuthError("HONGDOU_USER 与 HONGDOU_PASS 必须同时设置")
        return env_user, env_pass, "env:HONGDOU_USER/HONGDOU_PASS"

    candidates = []
    override = os.environ.get("HONGDOU_CREDENTIALS", "").strip()
    if override:
        candidates.append(override)
    candidates.append(os.path.join(PROJECT_ROOT, "scripts", ".credentials"))
    candidates.append(os.path.join(SCRIPT_DIR, ".credentials"))

    for path in candidates:
        got = _parse_credentials_file(path)
        if got:
            return got[0], got[1], f"file:{display_path(path)}"

    raise AuthError(
        "缺少红豆账号。给法（二选一）：\n"
        "  1) 环境变量: $env:HONGDOU_USER='<用户名>'; $env:HONGDOU_PASS='<密码>'\n"
        "  2) 文件:     scripts/.credentials（第一行用户名，第二行密码）\n"
        "不需要把账号写进 skill 或文档。"
    )


def _token_request(form: dict, timeout: int = 30, retries: int = 3) -> dict:
    body = urllib.parse.urlencode(form).encode()
    basic = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
    last = None
    for i in range(retries):
        req = urllib.request.Request(BASE + TOKEN_PATH, data=body, method="POST")
        req.add_header("Authorization", "Basic " + basic)
        req.add_header("tenant-id", TENANT_ID)
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        req.add_header("Accept", "application/json")
        try:
            with urllib.request.urlopen(req, context=_SSL, timeout=timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:300]
            if e.code in (400, 401, 403):
                raise AuthError(f"登录失败 HTTP {e.code}: {detail}") from None
            last = f"HTTP {e.code}: {detail}"
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as e:
            last = f"{type(e).__name__}: {e}"
        else:
            if str(payload.get("code", 0)) != "0":
                raise AuthError(
                    f"登录返回 code={payload.get('code')} msg={payload.get('msg')!r}"
                )
            data = payload.get("data") or {}
            if not data.get("access_token"):
                raise AuthError("登录返回里没有 access_token")
            return data
        if i < retries - 1:
            time.sleep(1.5 * (i + 1))
    raise NetworkError(f"登录请求失败（{last}）")


def _token_from_data(data: dict, old_refresh: str | None = None) -> Token:
    return Token(
        access_token=str(data["access_token"]),
        refresh_token=data.get("refresh_token") or old_refresh,
        expires_in=int(data.get("expires_in") or 1800),
        obtained_at=time.time(),
    )


def login(username: str, password: str) -> Token:
    data = _token_request({
        "grant_type": "password",
        "username": username,
        "password": password,
    })
    return _token_from_data(data)


def refresh(tok: Token) -> Token:
    if not tok.refresh_token:
        raise AuthError("缓存里没有 refresh_token，无法静默续期")
    data = _token_request({
        "grant_type": "refresh_token",
        "refresh_token": tok.refresh_token,
    })
    return _token_from_data(data, old_refresh=tok.refresh_token)


def get_token(force_login: bool = False, verbose: bool = True) -> Token:
    """统一入口：缓存可用就复用，过期先 refresh，失败再账密登录。"""
    if not force_login:
        cached = load_cache()
        if cached and cached.is_fresh():
            log_stderr(
                f"复用缓存令牌（剩余 {round(cached.expires_at - time.time())}s）",
                quiet=not verbose,
            )
            return cached
        if cached:
            try:
                tok = refresh(cached)
            except HongdouError as e:
                log_stderr(f"令牌续期失败（{e}），改用账号密码重新登录", quiet=not verbose)
            else:
                save_cache(tok)
                log_stderr(
                    f"令牌已用 refresh_token 续期（有效期 {tok.expires_in}s）",
                    quiet=not verbose,
                )
                return tok

    user, pwd, source = credentials()
    tok = login(user, pwd)
    save_cache(tok)
    log_stderr(
        f"OAuth2 登录成功（来源 {source}，有效期 {tok.expires_in}s）",
        quiet=not verbose,
    )
    return tok


# --------------------------------------------------------------------------- #
# 库存接口：单页请求 + 全量翻页
# --------------------------------------------------------------------------- #
def _money_key(row: dict, media: str) -> tuple:
    """抓取时按 (resourceId, 业务键) 去重；resourceId 单独不唯一。"""
    if media == "bus":
        return (row.get("resourceId"), row.get("lineName"), row.get("mediaName"))
    return (row.get("resourceId"), row.get("lineName"), row.get("exitName"))


def business_key(row: dict, media: str) -> tuple:
    """真正的业务唯一键（用于汇总去重，不含会重复的 resourceId）。"""
    if media == "bus":
        return (row.get("lineName"), row.get("mediaName"))
    return (row.get("lineName"), row.get("exitName"))


def request_page(media: str, params: dict, access_token: str,
                 timeout: int = 30, retries: int = 3) -> dict:
    """请求单页库存。401 抛 TokenStale，code!=0 抛 ApiError，网络错误重试。"""
    if media not in MEDIA_PATHS:
        raise ValueError(f"未知媒体类型：{media}")
    url = BASE + MEDIA_PATHS[media] + "?" + urllib.parse.urlencode(params)
    last = None

    for i in range(retries):
        req = urllib.request.Request(url, method="GET")
        req.add_header("tenant-id", TENANT_ID)
        req.add_header("Authorization", "Bearer " + access_token)
        req.add_header("Accept", "application/json")
        req.add_header("User-Agent", "Mozilla/5.0 (hongdou-inventory-skill/1.0)")
        try:
            with urllib.request.urlopen(req, context=_SSL, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:300]
            if e.code == 401:
                raise TokenStale(f"HTTP 401: {detail}") from None
            if e.code in (400, 403):
                raise ApiError(f"HTTP {e.code}: {detail}") from None
            last = f"HTTP {e.code}: {detail}"
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last = f"{type(e).__name__}: {e}"
        else:
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                last = f"响应不是 JSON：{raw[:200]!r}"
            else:
                if isinstance(payload, list):
                    return {"code": 0, "data": payload}
                if not isinstance(payload, dict):
                    last = f"响应结构异常：{raw[:200]!r}"
                else:
                    code = payload.get("code", 0)
                    if str(code) == "401":
                        raise TokenStale(str(payload.get("msg") or "账号未登录"))
                    if str(code) not in ("0", "None"):
                        raise ApiError(
                            f"接口返回 code={code} msg={payload.get('msg')!r}"
                        )
                    return payload
        if i < retries - 1:
            time.sleep(1.5 * (i + 1))
    raise NetworkError(f"请求失败（{last}）：{url}")


def _extract_items(payload: dict) -> tuple[list[dict], object | None]:
    data = payload.get("data")
    if isinstance(data, list):
        return data, None
    if isinstance(data, dict):
        items = data.get("list")
        if items is None:
            items = data.get("records")
        if items is None:
            items = data.get("rows")
        if not isinstance(items, list):
            items = []
        return items, data.get("total")
    return [], None


def fetch_media(media: str, start: str, end: str,
                token_provider=None,
                page_size: int = 200,
                max_pages: int | None = None,
                server_params: dict | None = None,
                delay: float = 0.15,
                timeout: int = 30,
                verbose: bool = True) -> tuple[list[dict], dict]:
    """翻页抓全量，返回 (rows, meta)。

    实测坑（2026-11-21）：
      * 接口 total 不可信（公交报 552，实际 431 行），不能当终止条件；
      * 每页实返 < pageSize（pageSize=200 只返 155），不能拿 len(items)<pageSize 判断；
      * 唯一可靠终止条件是「本页返回 0 条」，另加去重 + 连续 3 页无新增兜底；
      * resourceId 有重复，抓取按 (resourceId, lineName, mediaName/exitName) 去重。
    """
    if media not in MEDIA_PATHS:
        raise ValueError(f"未知媒体类型：{media}")
    if page_size <= 0:
        raise ValueError("--page-size 必须为正整数")
    token_provider = token_provider or get_token
    server_params = dict(server_params or {})

    token = token_provider()
    rows: list[dict] = []
    seen: set = set()
    page = 1
    pages = 0
    raw_items = 0
    stall = 0
    api_total = None
    truncated = False
    stalled = False
    relogin_done = False

    while True:
        params = dict(server_params, startDate=start, endDate=end,
                      pageNo=page, pageSize=page_size)
        try:
            payload = request_page(media, params, token.access_token, timeout=timeout)
        except TokenStale:
            if relogin_done:
                raise AuthError(f"{media} 重新登录后令牌仍失效，请检查账号权限") from None
            log_stderr(f"  {media} 令牌失效，重新登录后重试第 {page} 页", quiet=not verbose)
            token = token_provider(force_login=True)
            relogin_done = True
            continue

        items, total = _extract_items(payload)
        # 末页常常返回 total=0；保留各页里最大的非零 total 作为“接口声称值”。
        if total is not None and to_int(total) > 0:
            api_total = max(to_int(api_total or 0), to_int(total))
        raw_items += len(items)
        pages = page

        new = 0
        for item in items:
            key = _money_key(item, media)
            if key in seen:
                continue
            seen.add(key)
            rows.append(item)
            new += 1

        log_stderr(
            f"  {media} 第 {page} 页：返回 {len(items)} 条，新增 {new} 条，累计 {len(rows)}"
            + (f"（接口声称 total={total}）" if total is not None else ""),
            quiet=not verbose,
        )

        if not items:
            break
        if max_pages and page >= max_pages:
            truncated = True
            log_stderr(f"  到达 --max-pages {max_pages}，停止翻页", quiet=not verbose)
            break
        if page >= HARD_PAGE_CAP:
            truncated = True
            log_stderr(f"  到达内置页数上限 {HARD_PAGE_CAP}，停止翻页", quiet=not verbose)
            break

        if new == 0 and page > 1:
            stall += 1
            if stall >= 3:
                stalled = True
                log_stderr("  连续 3 页无新增，停止翻页（疑似后端分页失效）", quiet=not verbose)
                break
        else:
            stall = 0

        page += 1
        time.sleep(delay)

    meta = {
        "media": media,
        "pages": pages,
        "raw_items": raw_items,
        "unique_rows": len(rows),
        "api_total": api_total,
        "page_size": page_size,
        "server_params": server_params,
        "truncated": truncated,
        "stalled": stalled,
    }
    return rows, meta


# --------------------------------------------------------------------------- #
# CSV：保持管线的 40 列格式
# --------------------------------------------------------------------------- #
def flatten_row(row: dict) -> dict:
    """嵌套 dict/list（如 districtname=[2]）转 JSON 字符串，与现有管线一致。"""
    out = {}
    for key, value in row.items():
        if isinstance(value, (dict, list)):
            out[key] = json.dumps(value, ensure_ascii=False)
        else:
            out[key] = value
    return out


def csv_fields(rows: list[dict]) -> list[str]:
    fields = list(CANONICAL_FIELDS)
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    return fields


def write_csv(path: str, rows: list[dict]) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    fields = csv_fields(rows)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(flatten_row(row))


def read_csv(path: str) -> list[dict]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


# --------------------------------------------------------------------------- #
# 字段解析
# --------------------------------------------------------------------------- #
def to_int(value) -> int:
    if value is None:
        return 0
    s = str(value).strip()
    if s in ("", "None", "null", "NULL", "nan", "NaN", "NaT"):
        return 0
    try:
        return int(float(s))
    except (TypeError, ValueError):
        return 0


def level_for(media: str, line_level) -> str:
    return LEVEL_MAPS.get(media, {}).get(str(line_level).strip(), "unknown")


def is_special_blocked(row: dict) -> bool:
    text = str(row.get("specialSituation") or "")
    return any(word in text for word in SPECIAL_BLOCK_WORDS)


def district_codes(row: dict) -> list[str]:
    raw = row.get("districtname")
    if isinstance(raw, list):
        return [str(x) for x in raw]
    if raw is None or str(raw).strip() == "":
        return []
    try:
        parsed = json.loads(str(raw))
    except (TypeError, ValueError):
        parsed = [raw]
    if isinstance(parsed, list):
        return [str(x) for x in parsed]
    return [str(parsed)]


EMPTY_VALUE_STRINGS = {"", "0", "None", "null", "NULL", "nan", "NaN"}


def clean_value(value) -> str:
    """红豆接口用字符串 '0' 表示空值；汇总/分组时归一为空串，CSV 仍保留原文。"""
    text = str(value or "").strip()
    return "" if text in EMPTY_VALUE_STRINGS else text


def split_tags(value) -> list[str]:
    text = clean_value(value)
    if not text:
        return []
    return [part.strip() for part in re.split(r"[、,，;；/]+", text)
            if part.strip() and clean_value(part)]


def _contains(value, needle: str) -> bool:
    return str(needle).lower() in str(value or "").lower()


def apply_filters(rows: list[dict], media: str, *,
                  free_only: bool = False,
                  line_name: str | None = None,
                  keyword: str | None = None,
                  company: str | None = None,
                  media_name: str | None = None,
                  level: str | None = None,
                  exclude_special: bool = False,
                  district_code: str | None = None) -> list[dict]:
    """本地过滤。服务端只支持部分参数，其余在抓回后筛。"""
    out = []
    for row in rows:
        if free_only and to_int(row.get("freeCount")) <= 0:
            continue
        if line_name and not _contains(row.get("lineName"), line_name):
            continue
        if keyword:
            if media == "metro":
                if not (_contains(row.get("lineName"), keyword)
                        or _contains(row.get("exitName"), keyword)):
                    continue
            elif not _contains(row.get("lineName"), keyword):
                continue
        if company and not _contains(row.get("companyName"), company):
            continue
        if media_name and not _contains(row.get("mediaName"), media_name):
            continue
        if level:
            wanted = str(level).strip()
            row_level = level_for(media, row.get("lineLevel"))
            raw_level = str(row.get("lineLevel") or "").strip()
            if wanted.lower() not in (row_level.lower(), raw_level.lower()):
                continue
        if exclude_special and is_special_blocked(row):
            continue
        if district_code and str(district_code) not in district_codes(row):
            continue
        out.append(row)
    return out


# --------------------------------------------------------------------------- #
# 汇总
# --------------------------------------------------------------------------- #
def _top_free(rows: list[dict], media: str, limit: int = 10) -> list[dict]:
    fields = ["lineName", "exitName", "mediaName", "companyName", "lineLevel",
              "level", "freeCount", "totalCount", "contractCount",
              "reservationCount", "specialSituation", "businessAreaName",
              "categoryTags"]
    picked = sorted(
        rows,
        key=lambda r: (-to_int(r.get("freeCount")), str(r.get("lineName") or "")),
    )[:limit]
    numeric_fields = {"freeCount", "totalCount", "contractCount", "reservationCount"}
    out = []
    for row in picked:
        item = {key: row.get(key) for key in fields if clean_value(row.get(key))}
        item["level"] = level_for(media, row.get("lineLevel"))
        for key in numeric_fields:
            if key in item:
                item[key] = to_int(item[key])
        out.append(item)
    return out


def summarize(rows: list[dict], media: str, start: str, end: str,
              filters: dict | None = None,
              meta: dict | None = None) -> dict:
    """把一批库存行压成 agent 可直接引用的档期汇总。"""
    filters = filters or {}
    meta = meta or {}

    keys = {business_key(r, media) for r in rows}
    free_points = [r for r in rows if to_int(r.get("freeCount")) > 0]
    special = [r for r in rows if str(r.get("specialSituation") or "").strip()]
    blocked = [r for r in rows if is_special_blocked(r)]

    totals = {field: sum(to_int(r.get(field)) for r in rows) for field in TOTAL_FIELDS}

    by_level: dict[str, dict] = {}
    for row in rows:
        lv = level_for(media, row.get("lineLevel"))
        bucket = by_level.setdefault(lv, {"rows": 0, "free": 0, "total": 0})
        bucket["rows"] += 1
        bucket["free"] += to_int(row.get("freeCount"))
        bucket["total"] += to_int(row.get("totalCount"))
    by_level = {
        lv: by_level[lv] for lv in LEVEL_ORDER if lv in by_level
    } | {lv: by_level[lv] for lv in by_level if lv not in LEVEL_ORDER}

    summary = {
        "media": media,
        "period": {"start": start, "end": end},
        "inventory_ts": utc_now(),
        "filters": filters,
        "rows": len(rows),
        "fetched_rows": meta.get("unique_rows", len(rows)),
        "unique_business_keys": len(keys),
        "free_points": len(free_points),
        "special_points": len(special),
        "blocked_special_points": len(blocked),
        "totals": totals,
        "by_level": by_level,
        "top_free": _top_free(rows, media),
        "fetch": {
            "pages": meta.get("pages"),
            "raw_items": meta.get("raw_items"),
            "unique_rows": meta.get("unique_rows"),
            "api_total": meta.get("api_total"),
            "page_size": meta.get("page_size"),
            "server_params": meta.get("server_params") or {},
            "truncated": bool(meta.get("truncated")),
            "stalled": bool(meta.get("stalled")),
        },
        "notes": [],
    }

    if media == "bus":
        summary["distinct_lines"] = len({r.get("lineName") for r in rows})
        summary["by_company"] = _group_agg(rows, ["companyName"])
        summary["by_media_type"] = _group_agg(rows, ["mediaName"])
    else:
        summary["distinct_stations"] = len({r.get("lineName") for r in rows})
        summary["distinct_exits"] = len(keys)
        summary["by_category_tag"] = _group_agg(rows, ["categoryTags"], split=True)

    if meta.get("api_total") is not None:
        claimed = to_int(meta["api_total"])
        actual = meta.get("unique_rows")
        if actual is not None and claimed != actual:
            summary["notes"].append(
                f"接口声称 total={claimed}，实际返回 {actual} 行；"
                "不要拿 total 当库存量，翻页以本页返回 0 条为准。"
            )
        else:
            summary["notes"].append(
                f"接口 total={claimed} 与本次返回行数一致；翻页仍以本页返回 0 条为准。"
            )
    if media == "metro":
        summary["notes"].append(
            "地铁 lineLevel 语义未确认；本脚本只按 2=A++、3=A+ 映射，其余记 unknown。"
        )
        summary["notes"].append(
            "地铁 freeCount 是点位状态（通常 0/1）；free_points 比 freeCount 合计更有意义，"
            "top_free 只是明细示例，不代表点位优先级。"
        )
    zero_placeholder = sum(
        1 for r in rows
        if any(str(r.get(k) or "").strip() == "0"
               for k in ("businessAreaName", "categoryTags", "districtname"))
    )
    if zero_placeholder:
        summary["notes"].append(
            f"{zero_placeholder} 行的 businessAreaName/categoryTags/districtname 用字符串 "
            '"0" 表示空值；原始 CSV 保留 "0"，分组统计按 (空) 处理。'
        )
    if blocked:
        summary["notes"].append(
            f"{len(blocked)} 个点位命中封闭/改造/施工/停用/停运，排期方案必须剔除"
            "（可用 --exclude-special 直接过滤）。"
        )
    unknown_rows = sum(1 for r in rows if level_for(media, r.get("lineLevel")) == "unknown")
    if unknown_rows:
        summary["notes"].append(f"{unknown_rows} 行等级未知，下游需要单独确认。")
    if meta.get("truncated"):
        summary["notes"].append("本次抓取被 --max-pages 截断，结果不是全量。")
    if meta.get("stalled"):
        summary["notes"].append("后端分页疑似失效（连续无新增），结果可能不完整。")

    return summary


def _group_agg(rows: list[dict], columns: list[str], split: bool = False) -> list[dict]:
    """按若干列聚合；split=True 时按顿号/逗号拆多值（如 categoryTags）。"""
    buckets: dict[tuple, dict] = {}
    for row in rows:
        values_per_col = []
        for col in columns:
            if split:
                values_per_col.append(split_tags(row.get(col)) or ["(空)"])
            else:
                values_per_col.append([clean_value(row.get(col)) or "(空)"])

        # 单列为主（当前只用到单列）；多列时做笛卡尔积
        combos = [()]
        for values in values_per_col:
            combos = [c + (v,) for c in combos for v in values]
        for combo in combos:
            bucket = buckets.setdefault(combo, {"rows": 0, "free": 0, "total": 0,
                                                "contract": 0, "reservation": 0})
            bucket["rows"] += 1
            bucket["free"] += to_int(row.get("freeCount"))
            bucket["total"] += to_int(row.get("totalCount"))
            bucket["contract"] += to_int(row.get("contractCount"))
            bucket["reservation"] += to_int(row.get("reservationCount"))

    items = []
    for combo, agg in buckets.items():
        item = dict(zip(columns, combo))
        item.update(agg)
        items.append(item)
    items.sort(key=lambda x: (-x["free"], -x["rows"],
                              tuple(str(x.get(c) or "") for c in columns)))
    return items


# --------------------------------------------------------------------------- #
# 日期与媒体识别
# --------------------------------------------------------------------------- #
def _validate_month(month: str) -> tuple[int, int]:
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", str(month)):
        raise ValueError(f"月份格式必须是 YYYY-MM，收到：{month!r}")
    year, mon = str(month).split("-")
    return int(year), int(mon)


def month_bounds(month: str) -> tuple[str, str]:
    year, mon = _validate_month(month)
    last = calendar.monthrange(year, mon)[1]
    return f"{year:04d}-{mon:02d}-01", f"{year:04d}-{mon:02d}-{last:02d}"


def month_range(from_month: str, to_month: str) -> list[str]:
    start_y, start_m = _validate_month(from_month)
    end_y, end_m = _validate_month(to_month)
    if (end_y, end_m) < (start_y, start_m):
        raise ValueError("--to-month 不能早于 --from-month")
    out = []
    y, m = start_y, start_m
    while (y, m) <= (end_y, end_m):
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m > 12:
            y, m = y + 1, 1
        if len(out) > 240:
            raise ValueError("月份范围过大（>240 个月）")
    return out


def validate_range(start: str, end: str) -> tuple[date, date]:
    for value in (start, end):
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(value)):
            raise ValueError(f"日期格式必须是 YYYY-MM-DD，收到：{value!r}")
    try:
        start_d = date.fromisoformat(start)
        end_d = date.fromisoformat(end)
    except ValueError as e:
        raise ValueError(f"非法日期：{e}") from None
    if end_d < start_d:
        raise ValueError("--end 不能早于 --start")
    return start_d, end_d


def detect_media(rows: list[dict], path: str = "") -> str:
    counts: dict[str, int] = {}
    for row in rows:
        value = str(row.get("resourceType") or "").strip()
        if value:
            counts[value] = counts.get(value, 0) + 1
    if counts:
        top = max(counts, key=counts.get)
        for media, resource_type in MEDIA_TYPES.items():
            if top == resource_type:
                return media
    name = os.path.basename(path).lower()
    if name.startswith("bus"):
        return "bus"
    if name.startswith("metro"):
        return "metro"
    raise ValueError("无法判断媒体类型：CSV 应含 resourceType，或文件名以 bus_/metro_ 开头")


def facet_columns(media: str) -> list[str]:
    if media == "bus":
        return ["lineName", "companyName", "mediaName", "lineLevel", "level"]
    return ["lineName", "exitName", "businessAreaName", "stationAttr",
            "districtname", "categoryTags", "lineLevel", "level"]


def cell_value(row: dict, media: str, column: str):
    if column == "level":
        return level_for(media, row.get("lineLevel"))
    return row.get(column)


def build_facets(rows: list[dict], media: str, top: int = 20) -> dict:
    out = {}
    for column in facet_columns(media):
        buckets: dict[str, dict] = {}
        for row in rows:
            if column == "categoryTags":
                values = split_tags(row.get("categoryTags")) or ["(空)"]
            elif column == "districtname":
                values = [c for c in district_codes(row) if clean_value(c)] or ["(空)"]
            else:
                values = [clean_value(cell_value(row, media, column)) or "(空)"]
            for value in dict.fromkeys(values):
                bucket = buckets.setdefault(value, {"rows": 0, "free": 0})
                bucket["rows"] += 1
                bucket["free"] += to_int(row.get("freeCount"))
        items = sorted(buckets.items(), key=lambda kv: (-kv[1]["free"], -kv[1]["rows"], kv[0]))
        values = [{"value": value, **agg} for value, agg in items]
        out[column] = {
            "distinct": len(values),
            "values": values[:top] if top else values,
            "truncated": bool(top) and len(values) > top,
        }
    return out


def build_groups(rows: list[dict], media: str, columns: list[str], top: int = 20) -> dict:
    for column in columns:
        if column != "level" and column not in CANONICAL_FIELDS:
            raise ValueError(f"未知分组列：{column}")
    buckets: dict[tuple, dict] = {}
    for row in rows:
        key = tuple(clean_value(cell_value(row, media, c)) or "(空)" for c in columns)
        bucket = buckets.setdefault(key, {"rows": 0, "free": 0, "total": 0,
                                          "contract": 0, "reservation": 0})
        bucket["rows"] += 1
        bucket["free"] += to_int(row.get("freeCount"))
        bucket["total"] += to_int(row.get("totalCount"))
        bucket["contract"] += to_int(row.get("contractCount"))
        bucket["reservation"] += to_int(row.get("reservationCount"))
    items = []
    for key, agg in buckets.items():
        item = dict(zip(columns, key))
        item.update(agg)
        items.append(item)
    items.sort(key=lambda x: (-x["free"], -x["rows"],
                              tuple(str(x.get(c) or "") for c in columns)))
    return {
        "columns": columns,
        "distinct": len(items),
        "groups": items[:top] if top else items,
        "truncated": bool(top) and len(items) > top,
    }
