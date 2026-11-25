# -*- coding: utf-8 -*-
"""数据阶段运行时：用 subprocess 调用两个数据 skill 的只读脚本。

原则：
- 只用绝对路径、shell=False、UTF-8、超时、单飞锁；
- 只解析 stdout JSON；stderr 只入摘要，不原文回传；
- 参数白名单 + 日志/异常脱敏，绝不打印 token/password/security code；
- 红豆脚本只写快照到 data/snapshots 供引擎读取；新云脚本只读，成果作为
  Agent 解释/可视化上下文，不进入报价/库存。
"""
from __future__ import annotations

import json
import math
import os
import re
import subprocess
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from engine.config import PROJECT_ROOT

_ROUTE_SOURCE = "新云传媒大数据可视化平台 · AI线路（2023-05 轨迹快照）"

# 脱敏：覆盖 token / password / 安全码 / 会话标识，替换成型别。全局单例，
# 供所有 run 复用，避免每个异常对象重建正则。
_REDACT_PATTERNS = [
    (re.compile(r"(access_token|refresh_token|token|password|pass|pwd|secret|security_code|securityCode|JSESSIONID)\s*[=:]\s*\S+", re.I), r"\1=[REDACTED]"),
    (re.compile(r"(Bearer\s+)[A-Za-z0-9._\-]+", re.I), r"\1[REDACTED]"),
    (re.compile(r"[A-Za-z0-9]{32,}"), "[REDACTED]"),
]
_REDACT_LOCK = threading.Lock()

# 单飞锁：同一时刻只允许一个数据脚本在跑，避免抓取/刷新并发破坏旧文件。
_FLIGHT_LOCK = threading.Lock()


def redact(text: Any) -> str:
    """把可能含敏感信息的文本脱敏后返回字符串。"""
    if text is None:
        return ""
    s = str(text)
    with _REDACT_LOCK:
        for pattern, repl in _REDACT_PATTERNS:
            s = pattern.sub(repl, s)
    return s


def _summarize_stderr(stderr: str, max_chars: int = 400) -> str:
    """stderr 只保留最后一段脱敏摘要，避免把进度/原文塞进结果。"""
    s = redact(stderr).strip()
    if not s:
        return ""
    if len(s) > max_chars:
        s = s[-max_chars:]
    return "\n".join(s.splitlines()[-3:])


def _clean_path(raw: Any, *, max_points: int = 600) -> Tuple[List[List[float]], bool]:
    """校验 [lng,lat] 点列；超过 max_points 时等距抽稀（保留首尾），返回 (path, simplified)。"""
    points: List[List[float]] = []
    for p in raw or []:
        if not isinstance(p, (list, tuple)) or len(p) < 2:
            continue
        try:
            lng, lat = float(p[0]), float(p[1])
        except (TypeError, ValueError):
            continue
        if not (math.isfinite(lng) and math.isfinite(lat)):
            continue
        if not (-180 <= lng <= 180 and -90 <= lat <= 90):
            continue
        points.append([lng, lat])
    if len(points) <= max_points:
        return points, False
    step = (len(points) - 1) / (max_points - 1)
    sampled = [points[int(round(i * step))] for i in range(max_points)]
    sampled[0], sampled[-1] = points[0], points[-1]
    return sampled, True


# 常见上海地标/商圈/区县坐标兜底表（GCJ02 近似；仅在离线或平台地理编码不可用时使用）
_SHANGHAI_LANDMARKS: List[Dict[str, Any]] = [
    {"name": "上海乐高乐园", "aliases": ["乐高乐园", "乐高", "枫泾"], "district": "金山区", "lng": 121.104, "lat": 30.880},
    {"name": "上海迪士尼度假区", "aliases": ["迪士尼", "迪斯尼", "川沙"], "district": "浦东新区", "lng": 121.657, "lat": 31.141},
    {"name": "上海海昌海洋公园", "aliases": ["海昌", "临港", "滴水湖"], "district": "浦东新区", "lng": 121.908, "lat": 30.910},
    {"name": "陆家嘴金融中心", "aliases": ["陆家嘴", "上海中心", "环球金融", "东方明珠", "中国平安", "平安金融", "国金中心"], "district": "浦东新区", "lng": 121.5016, "lat": 31.2397},
    {"name": "静安寺商圈", "aliases": ["静安寺", "静安嘉里", "久光", "芮欧", "南京西路"], "district": "静安区", "lng": 121.4465, "lat": 31.2238},
    {"name": "徐家汇商圈", "aliases": ["徐家汇", "港汇", "美罗城", "徐汇", "腾讯大厦", "漕河泾"], "district": "徐汇区", "lng": 121.4375, "lat": 31.1945},
    {"name": "人民广场", "aliases": ["人民广场", "南京东路", "来福士", "黄浦"], "district": "黄浦区", "lng": 121.4737, "lat": 31.2304},
    {"name": "外滩", "aliases": ["外滩", "豫园", "新天地", "淮海路", "淮海中路"], "district": "黄浦区", "lng": 121.4903, "lat": 31.2363},
    {"name": "五角场商圈", "aliases": ["五角场", "合生汇", "杨浦", "复旦", "同济"], "district": "杨浦区", "lng": 121.5145, "lat": 31.3005},
    {"name": "中山公园商圈", "aliases": ["中山公园", "龙之梦", "长宁", "虹桥开发区", "古北"], "district": "长宁区", "lng": 121.4167, "lat": 31.2185},
    {"name": "虹桥商务区", "aliases": ["虹桥", "虹桥枢纽", "国家会展中心", "闵行"], "district": "闵行区", "lng": 121.3189, "lat": 31.1943},
    {"name": "张江高科技园区", "aliases": ["张江", "张江科学城", "金桥", "世纪公园"], "district": "浦东新区", "lng": 121.5890, "lat": 31.2047},
    {"name": "前滩太古里", "aliases": ["前滩", "世博", "三林", "太古里"], "district": "浦东新区", "lng": 121.4792, "lat": 31.1520},
    {"name": "环球港", "aliases": ["环球港", "普陀", "真如", "长风"], "district": "普陀区", "lng": 121.4125, "lat": 31.2335},
    {"name": "北外滩", "aliases": ["北外滩", "虹口", "四川北路", "瑞虹"], "district": "虹口区", "lng": 121.4978, "lat": 31.2518},
    {"name": "大宁国际", "aliases": ["大宁", "彭浦", "闸北"], "district": "静安区", "lng": 121.4525, "lat": 31.2785},
    {"name": "上海天文馆", "aliases": ["天文馆"], "district": "浦东新区", "lng": 121.9225, "lat": 30.9163},
    {"name": "宝山万达", "aliases": ["宝山", "顾村", "吴淞"], "district": "宝山区", "lng": 121.4896, "lat": 31.3989},
    {"name": "松江万达", "aliases": ["松江", "佘山", "松江大学城"], "district": "松江区", "lng": 121.2278, "lat": 31.0322},
    {"name": "嘉定新城", "aliases": ["嘉定", "南翔", "安亭"], "district": "嘉定区", "lng": 121.2655, "lat": 31.3747},
    {"name": "青浦奥特莱斯", "aliases": ["青浦", "朱家角", "蟠龙天地"], "district": "青浦区", "lng": 121.1242, "lat": 31.1497},
    {"name": "奉贤南桥", "aliases": ["奉贤", "南桥"], "district": "奉贤区", "lng": 121.4741, "lat": 30.9179},
    {"name": "金山万达", "aliases": ["金山", "金山卫"], "district": "金山区", "lng": 121.3416, "lat": 30.7417},
]


def infer_shanghai_district(lng: float, lat: float, text: str = "") -> str:
    """按文本关键词或最近上海地标推断行政区。"""
    for d in (
        "浦东新区", "黄浦区", "静安区", "徐汇区", "长宁区", "普陀区",
        "虹口区", "杨浦区", "闵行区", "宝山区", "嘉定区", "金山区",
        "松江区", "青浦区", "奉贤区", "崇明区",
    ):
        if d in text or d[:-1] in text:
            return d
    best_dist = 1e9
    best_d = "黄浦区"
    for lm in _SHANGHAI_LANDMARKS:
        dist = (lm["lng"] - lng) ** 2 + (lm["lat"] - lat) ** 2
        if dist < best_dist:
            best_dist = dist
            best_d = lm["district"]
    return best_d


def fallback_geocode_shanghai(query: str) -> Dict[str, Any]:
    """离线/兜底地理编码：匹配内置上海地标与区县中心。"""
    q = (query or "").strip()
    ql = q.lower()
    for lm in _SHANGHAI_LANDMARKS:
        if lm["name"].lower() in ql or ql in lm["name"].lower():
            return {
                "ok": True, "name": q or lm["name"], "matched_name": lm["name"],
                "address": f"上海市{lm['district']}{lm['name']}",
                "district": lm["district"], "lng": lm["lng"], "lat": lm["lat"],
                "source": "本地上海地标库（离线兜底）", "cached": True,
            }
        for alias in lm["aliases"]:
            if alias.lower() in ql:
                return {
                    "ok": True, "name": q or lm["name"], "matched_name": lm["name"],
                    "address": f"上海市{lm['district']}{q}",
                    "district": lm["district"], "lng": lm["lng"], "lat": lm["lat"],
                    "source": "本地上海地标库（离线兜底）", "cached": True,
                }
    # 默认落上海市中心人民广场（保证任何自定义公司名都有合理上海坐标）
    return {
        "ok": True, "name": q or "上海市中心", "matched_name": "人民广场",
        "address": f"上海市{q}", "district": "黄浦区",
        "lng": 121.4737, "lat": 31.2304,
        "source": "上海市中心默认定位（离线兜底）", "cached": True, "approx": True,
    }


class DataSkillRuntime:
    """数据阶段的子进程运行时（只读脚本白名单 + 参数白名单 + 单飞锁）。"""

    def __init__(self) -> None:
        self._python = os.path.join(PROJECT_ROOT, ".venv", "Scripts", "python.exe")
        self._hongdou_dir = os.path.join(PROJECT_ROOT, ".claude", "skills", "hongdou-inventory", "scripts")
        self._xinyun_dir = os.path.join(PROJECT_ROOT, ".claude", "skills", "xinyun-bigdata", "scripts")
        self._node = "node"
        self._session_file = os.path.join(PROJECT_ROOT, "data", "external", "platform_storage.json")
        self._xinyun_out = os.path.join(PROJECT_ROOT, "data", "external", "platform", "queries")
        self._session_cache: Optional[Tuple[float, bool]] = None

    # ------------------------------------------------------------------ #
    # 底层 subprocess 封装
    # ------------------------------------------------------------------ #
    def _run(
        self,
        args: List[str],
        *,
        cwd: str,
        timeout_sec: int,
    ) -> Tuple[int, str, str]:
        """执行命令，返回 (returncode, stdout, stderr)。shell=False、UTF-8。"""
        env = dict(os.environ)
        env.setdefault("PYTHONIOENCODING", "utf-8")
        env.setdefault("PYTHONUTF8", "1")
        try:
            proc = subprocess.run(
                args,
                cwd=cwd,
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout_sec,
                shell=False,
                encoding="utf-8",
                errors="replace",
            )
        except subprocess.TimeoutExpired as exc:
            return -1, "", _summarize_stderr((exc.stderr or b"").decode("utf-8", "replace") if isinstance(exc.stderr, bytes) else str(exc.stderr or "")) or "timeout"
        except OSError as exc:
            return -1, "", _summarize_stderr(str(exc))
        return proc.returncode, proc.stdout or "", proc.stderr or ""

    def _parse_stdout_json(self, stdout: str) -> Optional[Dict[str, Any]]:
        """stdout 只解析 JSON；不是 JSON 则返回 None。

        先整段解析（批量脚本输出单行 JSON），再退化为从第一个 '{' 起 raw_decode，
        兼容脚本前面混有少量提示行的情况；绝不做贪婪正则截取。
        """
        if not stdout:
            return None
        text = stdout.strip()
        try:
            parsed = json.loads(text)
            return parsed if isinstance(parsed, dict) else None
        except (json.JSONDecodeError, ValueError):
            pass
        decoder = json.JSONDecoder()
        start = text.find("{")
        while start != -1:
            try:
                parsed, _end = decoder.raw_decode(text[start:])
                return parsed if isinstance(parsed, dict) else None
            except (json.JSONDecodeError, ValueError):
                start = text.find("{", start + 1)
        return None

    # ------------------------------------------------------------------ #
    # 红豆
    # ------------------------------------------------------------------ #
    def inventory_status(self) -> Dict[str, Any]:
        """红豆令牌状态（只读本地缓存，不联网）。"""
        args = [self._python, os.path.join(self._hongdou_dir, "auth.py"), "--status"]
        with _FLIGHT_LOCK:
            code, out, err = self._run(args, cwd=PROJECT_ROOT, timeout_sec=30)
        payload = self._parse_stdout_json(out) or {}
        ok = bool(payload.get("ok")) and code == 0
        return {
            "ok": ok,
            "authenticated": bool(payload.get("authenticated") or payload.get("fresh")),
            "remaining_sec": payload.get("remaining_sec"),
            "code": code,
            "summary": _summarize_stderr(err) if not ok else (payload.get("message") or ""),
        }

    def inventory_snapshot(
        self,
        months: List[str],
        *,
        overwrite: bool = False,
        media: str = "all",
    ) -> Dict[str, Any]:
        """红豆月度快照；默认跳过已存在，overwrite 仅显式 refresh 时传。"""
        # 参数白名单：月份只接受 YYYY-MM；media 只接受 bus/metro/all
        safe_months = [m for m in months if re.fullmatch(r"\d{4}-\d{2}", str(m))]
        if not safe_months:
            return {"ok": False, "error": "no_valid_months", "summary": "", "months": [], "entries": []}
        if media not in ("bus", "metro", "all"):
            media = "all"

        args = [self._python, os.path.join(self._hongdou_dir, "snapshot.py"),
                "--from-month", safe_months[0], "--to-month", safe_months[-1],
                "--media", media]
        if overwrite:
            args.append("--overwrite")

        with _FLIGHT_LOCK:
            code, out, err = self._run(args, cwd=PROJECT_ROOT, timeout_sec=180)
        payload = self._parse_stdout_json(out) or {}
        entries = payload.get("entries") or []
        failures = payload.get("failures") if "failures" in payload else (1 if not payload.get("ok") else 0)
        ok = bool(payload.get("ok")) and code == 0 and failures == 0
        return {
            "ok": ok,
            "months": safe_months,
            "entries": entries,
            "failures": failures,
            "inventory_ts": payload.get("inventory_ts"),
            "summary": _summarize_stderr(err),
        }

    def inventory_analyze(self, snapshot_path: str) -> Dict[str, Any]:
        """对目标快照做离线汇总（不联网）。"""
        path = snapshot_path
        if not os.path.isabs(path):
            path = os.path.join(PROJECT_ROOT, path)
        if not os.path.isfile(path):
            return {"ok": False, "error": "snapshot_not_found", "summary": redact(path)}
        args = [self._python, os.path.join(self._hongdou_dir, "analyze.py"),
                "--file", path, "--free-only", "--exclude-special"]
        with _FLIGHT_LOCK:
            code, out, err = self._run(args, cwd=PROJECT_ROOT, timeout_sec=60)
        payload = self._parse_stdout_json(out) or {}
        summary = payload.get("summary") or {}
        return {
            "ok": bool(payload.get("ok")) and code == 0,
            "media": payload.get("media"),
            "period": payload.get("period"),
            "summary": summary,
            "error": _summarize_stderr(err),
        }

    # ------------------------------------------------------------------ #
    # 新云（只读；无会话/验证码则跳过）
    # ------------------------------------------------------------------ #
    def _xinyun_session_available(self) -> bool:
        return os.path.isfile(self._session_file)

    def _xinyun_session_ok(self, *, force: bool = False) -> bool:
        """轻量探测会话（ai_route_batch --check，不开浏览器），缓存 60 秒。

        会话过期时直接跳过 coverage/POI 页面脚本，避免每个阶段白等 Playwright。
        """
        if not self._xinyun_session_available():
            return False
        now = time.monotonic()
        if not force and self._session_cache and (now - self._session_cache[0]) < 60:
            return self._session_cache[1]
        args = [self._node, os.path.join(self._xinyun_dir, "ai_route_batch.mjs"), "--check"]
        code, out, err = self._run(args, cwd=PROJECT_ROOT, timeout_sec=30)
        payload = self._parse_stdout_json(out) or {}
        ok = bool(payload.get("authenticated")) and code == 0
        self._session_cache = (now, ok)
        return ok

    def bigdata_session_status(self, *, force: bool = False) -> Dict[str, Any]:
        """返回新云大数据会话状态（轻量探测，不启动浏览器）。"""
        exists = self._xinyun_session_available()
        if not exists:
            return {"authenticated": False, "session_file_exists": False, "reason": "MANUAL_LOGIN_REQUIRED"}
        ok = self._xinyun_session_ok(force=force)
        return {
            "authenticated": ok,
            "session_file_exists": True,
            "reason": None if ok else "SESSION_EXPIRED",
            "data_month": "2023-05",
        }

    def _xinyun_run(self, script: str, args: List[str], *, timeout_sec: int = 120) -> Dict[str, Any]:
        """通用 xinyun 只读脚本执行；无会话返回 MANUAL_LOGIN_REQUIRED。"""
        if script not in ("coverage.mjs", "coverage_poi.mjs", "geocode.mjs", "portrait_batch.mjs"):
            return {"ok": False, "status": "skipped", "reason": "FORBIDDEN_SCRIPT", "summary": ""}
        if not self._xinyun_session_ok():
            return {"ok": False, "status": "skipped", "reason": "MANUAL_LOGIN_REQUIRED", "summary": "缺少登录会话或会话已过期：先人工运行 login.mjs 过验证码一次"}

        full = [self._node, os.path.join(self._xinyun_dir, script)] + args
        with _FLIGHT_LOCK:
            code, out, err = self._run(full, cwd=PROJECT_ROOT, timeout_sec=timeout_sec)
        parsed = self._parse_stdout_json(out)
        if code != 0:
            summary = _summarize_stderr(err)
            if "缺少登录会话" in (err or out) or "MANUAL_LOGIN" in (err or out):
                return {"ok": False, "status": "skipped", "reason": "MANUAL_LOGIN_REQUIRED", "summary": summary}
            return {"ok": False, "status": "degraded", "reason": "BIGDATA_UNAVAILABLE", "summary": summary, "parsed": parsed}
        return {"ok": True, "status": "ready", "reason": None, "stdout": redact(out), "parsed": parsed, "summary": _summarize_stderr(err)}

    def bigdata_geocode(self, address: str, *, city: str = "上海市", force: bool = False) -> Dict[str, Any]:
        """对任意上海公司/品牌/地标做地理编码（优先新云平台 /nearby/geocode + 缓存，离线兜底本地地标库）。"""
        addr = str(address or "").strip()
        if not addr:
            return {"ok": False, "error": "EMPTY_ADDRESS", "message": "地址不能为空"}
        args = ["--address", addr, "--city", city, "--out", self._xinyun_out, "--json"]
        if force:
            args.append("--force")
        r = self._xinyun_run("geocode.mjs", args, timeout_sec=60)
        parsed = r.get("parsed") if isinstance(r.get("parsed"), dict) else None
        if r.get("ok") and parsed and parsed.get("ok") and parsed.get("lng") and parsed.get("lat"):
            lng, lat = float(parsed["lng"]), float(parsed["lat"])
            district = parsed.get("district") or infer_shanghai_district(lng, lat, f"{addr} {parsed.get('address') or ''}")
            return {
                "ok": True,
                "name": addr,
                "matched_name": parsed.get("name") or addr,
                "address": parsed.get("address") or addr,
                "district": district,
                "lng": lng,
                "lat": lat,
                "source": parsed.get("source") or "新云传媒大数据可视化平台 · /nearby/geocode",
                "cached": bool(parsed.get("cached")),
            }
        return fallback_geocode_shanghai(addr)

    def bigdata_coverage(
        self,
        address: str,
        radius: int = 1500,
        *,
        lng: Optional[float] = None,
        lat: Optional[float] = None,
    ) -> Dict[str, Any]:
        args = ["--address", address, "--radius", str(radius), "--out", self._xinyun_out, "--json"]
        if lng is not None and lat is not None:
            args += ["--lng", str(lng), "--lat", str(lat)]
        r = self._xinyun_run("coverage.mjs", args)
        parsed = r.get("parsed") if isinstance(r.get("parsed"), dict) else None
        if parsed and isinstance(parsed.get("summary"), dict):
            s = parsed["summary"]
            bus_lines = list(s.get("bus_lines") or [])
            metro_stations = list(s.get("metro_stations") or [])
            raw_items = parsed.get("items") or []
            clean_items = [
                {
                    "mediaType": x.get("mediaType"),
                    "lineName": x.get("lineName"),
                    "nearestStaName": x.get("nearestStaName"),
                    "minDistance": round(float(x.get("minDistance") or 0), 1),
                    "lng": x.get("nearestStaLng") or x.get("nearestLng"),
                    "lat": x.get("nearestStaLat") or x.get("nearestLat"),
                    "lineId": x.get("lineId"),
                }
                for x in raw_items[:80]
                if isinstance(x, dict)
            ]
            r["summary"] = {
                "bus": int(s.get("bus") or len(bus_lines)),
                "metro": int(s.get("metro") or len(metro_stations)),
                "total": int(s.get("total") or len(raw_items)),
            }
            r["center"] = (parsed.get("meta") or {}).get("center")
            r["radius"] = radius
            r["bus_lines"] = bus_lines
            r["metro_stations"] = metro_stations
            r["items"] = clean_items
            r["cached"] = bool(parsed.get("cached"))
        else:
            out = r.get("stdout") or ""
            bus = metro = 0
            m = re.search(r"共\s*(\d+)\s*条（公交\s*(\d+)\s*/\s*地铁\s*(\d+)）", out)
            if m:
                bus, metro = int(m.group(2)), int(m.group(3))
            r["summary"] = {"bus": bus, "metro": metro}
            r["bus_lines"] = []
            r["metro_stations"] = []
            r["items"] = []
        r.pop("stdout", None)
        r.pop("parsed", None)
        return r

    def bigdata_poi(
        self,
        address: str,
        radius: int = 1500,
        types: str = "商场,幼儿园,写字楼,小区",
        *,
        mode: str = "detail",
        lng: Optional[float] = None,
        lat: Optional[float] = None,
    ) -> Dict[str, Any]:
        safe_mode = "detail" if mode == "detail" else "count"
        args = [
            "--address", address, "--radius", str(radius),
            "--types", types, "--mode", safe_mode, "--out", self._xinyun_out, "--json",
        ]
        if lng is not None and lat is not None:
            args += ["--lng", str(lng), "--lat", str(lat)]
        r = self._xinyun_run("coverage_poi.mjs", args)
        parsed = r.get("parsed") if isinstance(r.get("parsed"), dict) else None
        if parsed and parsed.get("ok"):
            r["summary"] = dict(parsed.get("counts") or {})
            r["total"] = int(parsed.get("total") or 0)
            r["items"] = list(parsed.get("items") or [])[:80]
            r["center"] = (parsed.get("meta") or {}).get("center")
            r["radius"] = radius
            r["types"] = (parsed.get("meta") or {}).get("types") or []
            r["cached"] = bool(parsed.get("cached"))
        else:
            out = r.get("stdout") or ""
            counts: Dict[str, int] = {}
            for line in out.splitlines():
                m = re.match(r"^\s*([^:：]+)[:：]\s*(\d+)\s*$", line.strip())
                if m:
                    counts[m.group(1).strip()] = int(m.group(2))
            r["summary"] = counts
            r["items"] = []
            r["total"] = sum(counts.values())
        r.pop("stdout", None)
        r.pop("parsed", None)
        return r

    def bigdata_portrait(
        self,
        lines: List[str],
        *,
        media: str = "公交",
        max_per_line: int = 6,
        force: bool = False,
    ) -> Dict[str, Any]:
        """批量拉取选中线路的新云 2023-05 组合画像 + 单线画像（含年龄/性别/消费/房产/终端/时段人流/PV/UV）。"""
        safe_lines: List[str] = []
        for raw in lines or []:
            s = str(raw).strip()
            if s and re.fullmatch(r"[\w一-龥()\-]{1,32}", s) and s not in safe_lines:
                safe_lines.append(s)
        safe_lines = safe_lines[:15]
        if not safe_lines:
            return {
                "ok": False, "status": "skipped", "reason": "NO_LINES",
                "aggregate": None, "per_line": {}, "matched": [], "missing": [],
                "data_month": "202305", "source": "新云传媒大数据可视化平台 · 组合查询（2023-05）",
            }
        args = [
            "--lines", ",".join(safe_lines),
            "--media", media,
            "--max-per-line", str(max(0, min(10, int(max_per_line)))),
            "--out", self._xinyun_out,
            "--json",
        ]
        if force:
            args.append("--force")
        r = self._xinyun_run("portrait_batch.mjs", args, timeout_sec=180)
        parsed = r.get("parsed") if isinstance(r.get("parsed"), dict) else None
        if parsed and parsed.get("ok"):
            return {
                "ok": True,
                "status": parsed.get("status") or "ready",
                "reason": parsed.get("reason"),
                "cached": bool(parsed.get("cached")),
                "source": parsed.get("source") or "新云传媒大数据可视化平台 · 组合查询（2023-05）",
                "data_month": parsed.get("data_month") or "202305",
                "media": media,
                "requested": parsed.get("requested") or safe_lines,
                "matched": parsed.get("matched") or [],
                "missing": parsed.get("missing") or [],
                "aggregate": parsed.get("aggregate"),
                "per_line": parsed.get("per_line") or {},
                "fetched_at": parsed.get("fetched_at"),
            }
        return {
            "ok": False,
            "status": r.get("status") or "degraded",
            "reason": r.get("reason") or "PORTRAIT_UNAVAILABLE",
            "aggregate": None,
            "per_line": {},
            "matched": [],
            "missing": safe_lines,
            "data_month": "202305",
            "source": "新云传媒大数据可视化平台 · 组合查询（2023-05）",
            "summary": r.get("summary") or "",
        }

    def bigdata_routes(
        self,
        lines: List[str],
        *,
        force: bool = False,
        max_lines: int = 40,
        max_age_days: int = 30,
    ) -> Dict[str, Any]:
        """方案公交/地铁线路的真实几何（新云 AI线路，只读）。

        一次平台会话批量取；优先复用 data/external/platform/queries 的
        ai_line_*.geojson 缓存。返回的 path 已由平台 lng/lat 交换纠正为
        GeoJSON [lng,lat]；仅用于可视化，不进入报价/库存/评分。
        """
        safe_lines: List[str] = []
        for raw in lines or []:
            s = str(raw).strip()
            # 线路名白名单：数字/字母/中文/括号/连字符，最长 32。
            if s and re.fullmatch(r"[\w一-龥()\-]{1,32}", s) and s not in safe_lines:
                safe_lines.append(s)
        try:
            limit = int(max_lines or 40)
        except (TypeError, ValueError):
            limit = 40
        try:
            ttl_days = int(max_age_days or 30)
        except (TypeError, ValueError):
            ttl_days = 30
        safe_lines = safe_lines[: max(1, min(limit, 60))]
        if not safe_lines:
            return {
                "ok": True, "status": "skipped", "reason": "NO_LINES",
                "lines": [], "missing": [],
                "summary": {"requested": 0, "resolved": 0, "cached": 0, "fetched": 0, "missing": 0},
                "data_month": "202305", "source": _ROUTE_SOURCE,
            }

        args = [
            self._node, os.path.join(self._xinyun_dir, "ai_route_batch.mjs"),
            "--lines", ",".join(safe_lines),
            "--out", self._xinyun_out,
            "--max-age-days", str(max(1, ttl_days)),
            "--max", str(len(safe_lines)),
        ]
        if force:
            args.append("--force")
        with _FLIGHT_LOCK:
            code, out, err = self._run(args, cwd=PROJECT_ROOT, timeout_sec=240)
        payload = self._parse_stdout_json(out)
        if not isinstance(payload, dict):
            status = "degraded" if code != 0 else "skipped"
            reason = "MANUAL_LOGIN_REQUIRED" if "缺少登录会话" in (err or "") else "BIGDATA_UNAVAILABLE"
            return {
                "ok": False, "status": status, "reason": reason,
                "lines": [], "missing": [{"requested": x, "reason": reason} for x in safe_lines],
                "summary": {"requested": len(safe_lines), "resolved": 0, "cached": 0, "fetched": 0, "missing": len(safe_lines)},
                "data_month": "202305", "source": _ROUTE_SOURCE,
                "error": _summarize_stderr(err),
            }

        routes: List[Dict[str, Any]] = []
        for item in payload.get("lines") or []:
            if not isinstance(item, dict):
                continue
            path, simplified = _clean_path(item.get("path"))
            if len(path) < 2:
                continue
            cleaned = {
                "requested": item.get("requested") or item.get("line"),
                "line": item.get("line") or item.get("requested"),
                "lineName": item.get("lineName"),
                "lineId": item.get("lineId"),
                "status": item.get("status") or "fetched",
                "points": len(path),
                "source_points": int(item.get("points") or len(path)),
                "simplified": simplified,
                "path": path,
                "bbox": item.get("bbox"),
                "fetched_at": item.get("fetched_at"),
            }
            if len(cleaned["path"]) >= 2:
                routes.append(cleaned)
        missing = [m for m in (payload.get("missing") or []) if isinstance(m, dict)]
        status = str(payload.get("status") or ("ready" if routes else "degraded"))
        if status not in ("ready", "degraded", "skipped"):
            status = "degraded"
        reason = payload.get("reason")
        summary = {
            "requested": len(safe_lines),
            "resolved": len(routes),
            "cached": sum(1 for r in routes if r["status"] == "cached"),
            "fetched": sum(1 for r in routes if r["status"] == "fetched"),
            "missing": len(missing),
        }
        return {
            "ok": status == "ready",
            "status": status,
            "reason": reason,
            "lines": routes,
            "missing": missing,
            "summary": summary,
            "data_month": payload.get("data_month") or "202305",
            "source": _ROUTE_SOURCE,
            "fetched_at": payload.get("fetched_at"),
            "error": _summarize_stderr(err),
        }


def default_data_runtime() -> DataSkillRuntime:
    return DataSkillRuntime()


__all__ = ["DataSkillRuntime", "default_data_runtime", "redact"]
