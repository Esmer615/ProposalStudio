# -*- coding: utf-8 -*-
"""ai_route_batch.mjs 的本地 mock 平台集成测试（不需要真实平台会话）。

覆盖：线路树匹配、平台 lng/lat 交换、GeoJSON 落盘、缺失线路、缓存复用、
会话过期（302→/login）时显式 MANUAL_LOGIN_REQUIRED。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

NODE = shutil.which("node")
SCRIPTS = os.path.join(ROOT, ".claude", "skills", "xinyun-bigdata", "scripts")
SCRIPT = os.path.join(SCRIPTS, "ai_route_batch.mjs")
PLAYWRIGHT = os.path.join(SCRIPTS, "node_modules", "playwright")

pytestmark = pytest.mark.skipif(
    not NODE or not os.path.isfile(SCRIPT) or not os.path.isdir(PLAYWRIGHT),
    reason="需要 node 与 xinyun-bigdata/scripts/node_modules/playwright",
)

TREE = {
    "code": 0,
    "data": [
        {
            "name": "新云-测试",
            "children": [
                {"lineId": 9871, "lineName": "1001路", "linePath": "D:\\SOP\\1001路"},
                {"lineId": 9900, "lineName": "136路", "linePath": "D:\\SOP\\136路"},
            ],
        }
    ],
}
# 平台字段交换：lng 存纬度、lat 存经度。
GEO = {
    "D:\\SOP\\1001路": [[31.112367, 121.577691], [31.129428, 121.593946]],
    "D:\\SOP\\136路": [[31.20, 121.40], [31.21, 121.41]],
}


def _serve(mode="ok"):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _json(self, payload, status=200):
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if mode == "login":
                self.send_response(302)
                self.send_header("Location", "http://flairmedia.com.cn:38880/login")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            u = urlparse(self.path)
            if u.path == "/baseInfoLine/getTreeLine":
                return self._json(TREE)
            if u.path == "/baseInfoLine/getLineJson":
                line_path = parse_qs(u.query).get("linePath", [""])[0]
                pts = GEO.get(line_path)
                if pts is None:
                    return self._json({"code": 404, "data": None}, 404)
                # 平台字段交换：lng 字段存纬度、lat 字段存经度。
                inner = {"path": [{"lng": lat, "lat": lng} for lat, lng in pts]}
                return self._json({"code": 0, "data": json.dumps(inner)})
            return self._json({"code": 404}, 404)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    return server, thread, base


def _run(lines, out_dir, state_file, base):
    env = os.environ.copy()
    env["XINYUN_BASE"] = base
    env["XINYUN_STATE"] = state_file
    env.setdefault("PYTHONIOENCODING", "utf-8")
    proc = subprocess.run(
        [NODE, SCRIPT, "--lines", lines, "--out", out_dir],
        cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_batch_fetch_missing_and_cache(tmp_path):
    state = tmp_path / "state.json"
    state.write_text('{"cookies":[],"origins":[]}', encoding="utf-8")
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    server, thread, base = _serve()
    try:
        result = _run("1001,136,404", str(out_dir), str(state), base)
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert result["status"] == "degraded"
    assert result["reason"] == "PARTIAL_ROUTES"
    assert result["summary"]["resolved"] == 2
    assert result["summary"]["missing"] == 1
    by_line = {x["requested"]: x for x in result["lines"]}
    assert by_line["1001"]["points"] == 2
    # 平台 lng/lat 已交换为 [经度, 纬度]
    assert by_line["1001"]["path"][0] == [121.577691, 31.112367]
    assert result["missing"][0]["requested"] == "404"

    files = sorted(os.listdir(out_dir))
    assert "ai_line_9871.geojson" in files
    assert "ai_line_9900.geojson" in files
    geo = json.loads((out_dir / "ai_line_9871.geojson").read_text(encoding="utf-8"))
    assert geo["features"][0]["geometry"]["coordinates"] == [[121.577691, 31.112367], [121.593946, 31.129428]]

    # 平台已关闭：完全缓存命中不应再需要会话/网络。
    cached = _run("1001,136", str(out_dir), str(state), base)
    assert cached["status"] == "ready"
    assert cached["cache_only"] is True
    assert cached["summary"]["cached"] == 2
    assert all(x["status"] == "cached" for x in cached["lines"])


def test_batch_manual_login_when_session_expired(tmp_path):
    state = tmp_path / "state.json"
    state.write_text('{"cookies":[],"origins":[]}', encoding="utf-8")
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    server, thread, base = _serve(mode="login")
    try:
        result = _run("136", str(out_dir), str(state), base)
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert result["status"] == "skipped"
    assert result["reason"] == "MANUAL_LOGIN_REQUIRED"
    assert result["lines"] == []
    assert result["missing"][0]["reason"] == "MANUAL_LOGIN_REQUIRED"
