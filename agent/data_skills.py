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

    def _xinyun_run(self, script: str, args: List[str]) -> Dict[str, Any]:
        """通用 xinyun 只读脚本执行；无会话返回 MANUAL_LOGIN_REQUIRED。"""
        if script not in ("coverage.mjs", "coverage_poi.mjs"):
            return {"ok": False, "status": "skipped", "reason": "FORBIDDEN_SCRIPT", "summary": ""}
        if not self._xinyun_session_ok():
            return {"ok": False, "status": "skipped", "reason": "MANUAL_LOGIN_REQUIRED", "summary": "缺少登录会话或会话已过期：先人工运行 login.mjs 过验证码一次"}

        full = [self._node, os.path.join(self._xinyun_dir, script)] + args
        with _FLIGHT_LOCK:
            code, out, err = self._run(full, cwd=PROJECT_ROOT, timeout_sec=120)
        # 脚本主要用人类可读 stdout，不是 JSON；这里解析关键摘要
        if code != 0:
            summary = _summarize_stderr(err)
            if "缺少登录会话" in (err or out) or "MANUAL_LOGIN" in (err or out):
                return {"ok": False, "status": "skipped", "reason": "MANUAL_LOGIN_REQUIRED", "summary": summary}
            return {"ok": False, "status": "degraded", "reason": "BIGDATA_UNAVAILABLE", "summary": summary}
        return {"ok": True, "status": "ready", "reason": None, "stdout": redact(out), "summary": _summarize_stderr(err)}

    def bigdata_coverage(self, address: str, radius: int = 1000) -> Dict[str, Any]:
        r = self._xinyun_run("coverage.mjs", ["--address", address, "--radius", str(radius)])
        # 从 stdout 提取公交/地铁计数
        out = r.get("stdout") or ""
        bus = metro = 0
        m = re.search(r"共\s*(\d+)\s*条（公交\s*(\d+)\s*/\s*地铁\s*(\d+)）", out)
        if m:
            bus, metro = int(m.group(2)), int(m.group(3))
        r["summary"] = {"bus": bus, "metro": metro}
        r.pop("stdout", None)
        return r

    def bigdata_poi(self, address: str, radius: int = 1000, types: str = "商场,幼儿园") -> Dict[str, Any]:
        r = self._xinyun_run("coverage_poi.mjs", [
            "--address", address, "--radius", str(radius),
            "--types", types, "--mode", "count",
        ])
        out = r.get("stdout") or ""
        counts: Dict[str, int] = {}
        for line in out.splitlines():
            m = re.match(r"^\s*([^:：]+)[:：]\s*(\d+)\s*$", line.strip())
            if m:
                counts[m.group(1).strip()] = int(m.group(2))
        r["summary"] = counts
        r.pop("stdout", None)
        return r

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
