"""Sidecar entry point.

Run directly to spawn the service the way Tauri will:

    python -m csm_sidecar.main

Or import ``app`` for ``uvicorn csm_sidecar.main:app --reload`` during
development. The ``__main__`` path is what PyInstaller will package.
"""
from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import auth, heartbeat, lifespan as _lifespan, logging_setup
from .routes import aggregation as aggregation_routes
from .routes import angle as angle_routes
from .routes import article as article_routes
from .routes import assembler as assembler_routes
from .routes import batch as batch_routes
from .routes import brand_memory as brand_memory_routes
from .routes import chain as chain_routes
from .routes import config as config_routes
from .routes import dedup as dedup_routes
from .routes import generate as generate_routes
from .routes import mining as mining_routes
from .routes import monitor as monitor_routes
from .routes import skills as skills_routes
from .routes import system as system_routes
from .routes import templates as templates_routes
from .routes import updater as updater_routes
from .routes import vault as vault_routes
from .routes import vault_writer as vault_writer_routes
from .routes import vault_atomize as vault_atomize_routes
from .routes import xhs as xhs_routes

logger = logging.getLogger(__name__)

app = FastAPI(
    title="CSM Sidecar",
    version="0.0.1",
    lifespan=_lifespan.lifespan,
)

# CORS — Tauri WebView loads from ``http://localhost:5173`` in dev and
# ``tauri://localhost`` (or ``https://tauri.localhost`` on Windows) once
# packaged. The sidecar binds to ``127.0.0.1:<random>``, which the browser
# treats as a different origin from ``localhost`` even though both resolve
# to the loopback interface. Without these allow-list entries the
# preflight OPTIONS gets a 405 + no ``Access-Control-Allow-*`` headers,
# the browser refuses the real request, and axios surfaces it as a
# generic "Network Error". The token check still gates every route — CORS
# only governs whether the browser is willing to deliver the response, not
# whether the server trusts the caller.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "tauri://localhost",
        # 历史：Tauri 2 Windows 默认 https://tauri.localhost，但混合
        # 内容（HTTPS → HTTP sidecar）会被 WebView2 拦截。我们改成
        # dangerousUseHttpScheme:true (tauri.conf.json) 让前端走
        # http://tauri.localhost，跟 sidecar 同协议，preflight + 实际
        # 请求都不再被 mixed-content 阻断。
        "http://tauri.localhost",
        "https://tauri.localhost",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Heartbeat tracker — refreshes ``last_activity`` on every request so the
# watchdog (started in run()) knows the UI is still alive.
app.middleware("http")(heartbeat.heartbeat_middleware)

app.include_router(system_routes.router)
app.include_router(config_routes.router)
app.include_router(vault_routes.router)
app.include_router(vault_writer_routes.router)
app.include_router(vault_atomize_routes.router)
app.include_router(skills_routes.router)
app.include_router(brand_memory_routes.router)
app.include_router(templates_routes.router)
app.include_router(generate_routes.router)
app.include_router(chain_routes.router)
app.include_router(article_routes.router)
app.include_router(batch_routes.router)
app.include_router(monitor_routes.router)
app.include_router(mining_routes.router)
app.include_router(dedup_routes.router)
app.include_router(updater_routes.router)
app.include_router(aggregation_routes.router)
app.include_router(assembler_routes.router)
app.include_router(angle_routes.router)
app.include_router(xhs_routes.router)


def run() -> None:
    """PyInstaller / `python -m` entry point.

    Picks a free loopback port, prints the handshake JSON to stdout, then
    hands control to uvicorn. Tauri captures the first stdout line and
    discards the rest (uvicorn writes its own access logs to stderr by
    default in our config).

    Production-only setup also lands here:
    - File logging to ``<config_dir>/logs/sidecar.log`` (rotating)
    - Heartbeat watchdog (idle self-shutdown)
    """
    import uvicorn

    log_file = logging_setup.setup(log_dir=logging_setup.default_log_dir())
    if log_file:
        logger.info("logging to %s", log_file)

    heartbeat.start_watchdog()

    port = _lifespan.pick_free_port()
    # Token is minted in the lifespan handler so it's tied to the same
    # FastAPI instance that handles the first request, but we need it on
    # stdout *before* uvicorn binds the socket — otherwise Tauri waits
    # forever. Mint here and have lifespan reuse the existing value.
    token = auth.generate_token()
    _lifespan.emit_handshake(port, token)

    uvicorn.run(
        app,
        host="127.0.0.1",
        port=port,
        log_level="info",
        access_log=False,  # too chatty for desktop sidecar; rely on app logs
    )


if __name__ == "__main__":
    run()
