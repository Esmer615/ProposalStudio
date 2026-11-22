# -*- coding: utf-8 -*-
"""标准库兜底服务：不依赖 FastAPI/uvicorn，路由与 JSON 契约与 server.main 一致。

用法：
    .venv\\Scripts\\python.exe server\\fallback_server.py --port 8010
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server import core  # noqa: E402

DIST = core.WEB_DIST


class Handler(BaseHTTPRequestHandler):
    server_version = "ProposalStudioFallback/1.0"

    # ------------------------------------------------------------------ #
    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Accept")

    def _json(self, payload: Dict[str, Any], status: int = 200, headers: Optional[Dict[str, str]] = None) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        for k, v in (headers or {}).items():
            self.send_header(k, str(v))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def _html(self, html: str, status: int = 200, filename: Optional[str] = None) -> None:
        body = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        if filename:
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(raw.decode("utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    # ------------------------------------------------------------------ #
    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/api/health":
            self._json(core.health())
        elif path == "/api/meta":
            self._json(core.meta())
        elif path == "/api/data/manifest":
            self._json(core.manifest())
        elif path == "/api/agent/skills":
            self._json(core.agent_skills())
        else:
            self._static(path)

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        body = self._body()
        if path == "/api/plan":
            code, payload, headers = core.plan(body)
            self._json(payload, code, headers)
        elif path == "/api/plans/batch":
            code, payload, headers = core.batch(body)
            self._json(payload, code, headers)
        elif path == "/api/elasticity":
            code, payload, headers = core.elasticity(body)
            self._json(payload, code, headers)
        elif path == "/api/agent/analyze":
            code, payload, headers = core.agent_analyze(body)
            self._json(payload, code, headers)
        else:
            self._json({"error": {"code": "NOT_FOUND", "message": path}}, 404)

    # ------------------------------------------------------------------ #
    def _static(self, path: str) -> None:
        if not DIST.exists():
            self._json({"error": {"code": "NOT_BUILT", "message": "web/dist 未构建"}}, 404)
            return
        rel = unquote(path.lstrip("/")) or "index.html"
        candidate = (DIST / rel).resolve()
        try:
            candidate.relative_to(DIST.resolve())
        except ValueError:
            self._json({"error": {"code": "FORBIDDEN", "message": "bad path"}}, 403)
            return
        if not candidate.exists() or candidate.is_dir():
            candidate = DIST / "index.html"
        if not candidate.exists():
            self._json({"error": {"code": "NOT_FOUND", "message": path}}, 404)
            return
        data = candidate.read_bytes()
        mime, _ = mimetypes.guess_type(str(candidate))
        self.send_response(200)
        self.send_header("Content-Type", (mime or "application/octet-stream") + ("; charset=utf-8" if (mime or "").startswith("text/") else ""))
        self.send_header("Content-Length", str(len(data)))
        self._cors()
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write("[fallback] " + (fmt % args) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8010)
    args = parser.parse_args()
    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"[fallback] serving on http://{args.host}:{args.port}")
    h = core.health()
    print(f"[fallback] engine_available={h['engine_available']} data_version={h['data_version']}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
