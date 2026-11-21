# -*- coding: utf-8 -*-
"""FastAPI 本地服务：127.0.0.1:8010。

运行：
    .venv\\Scripts\\python.exe -m uvicorn server.main:app --host 127.0.0.1 --port 8010
或：
    .\\start.ps1
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from server import core

ROOT = core.ROOT
DIST = core.WEB_DIST

app = FastAPI(
    title="乐园 AI 提案工作台 API",
    version="1.0.0",
    description="上海新云传媒 · INTERCITY HACK · 本地演示服务",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "http://127.0.0.1:8010",
        "http://localhost:8010",
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _json(payload: Dict[str, Any], status: int = 200, headers: Optional[Dict[str, str]] = None) -> JSONResponse:
    return JSONResponse(content=payload, status_code=status, headers=headers or {})


@app.get("/api/health")
def api_health() -> JSONResponse:
    return _json(core.health())


@app.get("/api/meta")
def api_meta() -> JSONResponse:
    return _json(core.meta())


@app.get("/api/data/manifest")
def api_manifest() -> JSONResponse:
    return _json(core.manifest())


@app.post("/api/plan")
async def api_plan(request: Request) -> JSONResponse:
    try:
        body = await request.json()
    except Exception:
        body = {}
    code, payload, headers = core.plan(body if isinstance(body, dict) else {})
    return _json(payload, code, headers)


@app.post("/api/plans/batch")
async def api_batch(request: Request) -> JSONResponse:
    try:
        body = await request.json()
    except Exception:
        body = {}
    code, payload, headers = core.batch(body if isinstance(body, dict) else {})
    return _json(payload, code, headers)


@app.post("/api/elasticity")
async def api_elasticity(request: Request) -> JSONResponse:
    try:
        body = await request.json()
    except Exception:
        body = {}
    code, payload, headers = core.elasticity(body if isinstance(body, dict) else {})
    return _json(payload, code, headers)


@app.get("/api/agent/skills")
def api_agent_skills() -> JSONResponse:
    return _json(core.agent_skills())


@app.post("/api/agent/analyze")
async def api_agent_analyze(request: Request) -> JSONResponse:
    try:
        body = await request.json()
    except Exception:
        body = {}
    code, payload, headers = core.agent_analyze(body if isinstance(body, dict) else {})
    return _json(payload, code, headers)


@app.post("/api/export")
async def api_export(request: Request) -> Response:
    try:
        body = await request.json()
    except Exception:
        body = {}
    code, html, filename = core.export_html(body if isinstance(body, dict) else {})
    if code != 200:
        return _json(
            {
                "error": {
                    "code": "EXPORT_UNAVAILABLE",
                    "message": "静态导出尚未构建；请先运行 pnpm --dir web export",
                    "suggestions": ["pnpm --dir web export", "检查 web/dist-export/index.html"],
                    "recoverable": True,
                }
            },
            code,
        )
    return HTMLResponse(
        content=html,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# --------------------------------------------------------------------------- #
# 静态站点（生产模式）：只有在 web/dist 存在时挂载
# --------------------------------------------------------------------------- #
if DIST.exists():
    assets = DIST / "assets"
    if assets.exists():
        app.mount("/assets", StaticFiles(directory=str(assets)), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str) -> Response:
        # API 路径不会走到这里（上面已注册）
        candidate = DIST / full_path
        if full_path and candidate.exists() and candidate.is_file():
            return Response(content=candidate.read_bytes(), media_type=_guess_media(candidate))
        index = DIST / "index.html"
        if index.exists():
            return HTMLResponse(index.read_text(encoding="utf-8", errors="replace"))
        return _json({"error": {"code": "NOT_BUILT", "message": "web/dist 未构建"}}, 404)


def _guess_media(path: Path) -> str:
    ext = path.suffix.lower()
    return {
        ".js": "text/javascript",
        ".mjs": "text/javascript",
        ".css": "text/css",
        ".json": "application/json",
        ".geojson": "application/geo+json",
        ".svg": "image/svg+xml",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".woff2": "font/woff2",
        ".html": "text/html; charset=utf-8",
    }.get(ext, "application/octet-stream")


@app.on_event("startup")
def _startup() -> None:
    h = core.health()
    print("[server] 乐园 AI 提案工作台 API")
    print(f"[server] engine_available={h['engine_available']} data_version={h['data_version']}")
    print(f"[server] inventory_periods={h['inventory_periods']}")
    if not h["engine_available"]:
        print(f"[server] engine_error={h['engine_error']}")
        return

    # 启动预热默认场景（后台线程，不阻塞健康检查）：100/200/500 + 九档弹性缓存
    def _warm() -> None:
        try:
            from engine.orchestrator import generate_elasticity, generate_plan

            base = core._default_request()  # noqa: SLF001 - 本地演示
            for b in (500, 200, 100):
                req = dict(base)
                req["budget_wan"] = b
                generate_plan(req)
            generate_elasticity(base)
            print("[server] prewarm done (100/200/500 + elasticity)")
        except Exception as exc:  # pragma: no cover
            print(f"[server] prewarm skipped: {type(exc).__name__}: {exc}")

    import threading

    threading.Thread(target=_warm, name="prewarm", daemon=True).start()
