# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the CSM sidecar.

Built into ``--onedir`` mode (faster cold start than --onefile and avoids
the temp-extract step that historically tripped antivirus on Windows).
The whole produced folder ships as Tauri's `externalBin` / `resources`
entry — see frontend/src-tauri/tauri.conf.json.

Per the migration plan + memory's PyQt6/PyInstaller rules:
  * UPX is OFF — produced binaries broke under UPX historically.
  * No PyQt6 hidden imports (sidecar is Qt-free).
  * Bundle every csm_core.llm.providers.* — make_client() resolves them
    by string and PyInstaller's static analyzer can't see those imports.
  * curl_cffi / DrissionPage / anthropic / datasketch each ship native
    sub-modules that need ``collect_submodules`` / ``collect_data_files``
    to be picked up cleanly.

Build (from the worktree root):

    pyinstaller sidecar/csm-sidecar.spec --noconfirm --distpath frontend/src-tauri/binaries
"""
from __future__ import annotations

from PyInstaller.utils.hooks import collect_data_files, collect_submodules


# ── Data files ─────────────────────────────────────────────────────────────
# anthropic ships its tokenizer + JSON schemas as package data.
# curl_cffi ships compiled .pyd / .dll under its package root.
# DrissionPage has chrome-driver shims and webdriver helpers.
datas: list[tuple[str, str]] = []
datas += collect_data_files("anthropic")
datas += collect_data_files("curl_cffi")
datas += collect_data_files("DrissionPage", include_py_files=False)
datas += collect_data_files("frontmatter")
# CSM Skill / template defaults shipped with the app (read-only).
datas += [("../templates", "templates"), ("../examples", "examples")]


# ── Hidden imports ─────────────────────────────────────────────────────────
hiddenimports: list[str] = [
    # csm_core core packages — direct imports above only catch the ones
    # actually referenced by sidecar code; PyInstaller still needs the
    # full set because some submodules are imported lazily inside
    # csm_core itself (assembler reroll, vault scanner edge cases, etc.).
    "csm_core",
    "csm_core.config",
    "csm_core.assembler",
    "csm_core.assembler.constraints",
    "csm_core.assembler.plan",
    "csm_core.assembler.render",
    "csm_core.assembler.reroll",
    "csm_core.assembler.sampler",
    "csm_core.batch",
    "csm_core.batch.runner",
    "csm_core.batch.report",
    "csm_core.dedup",
    "csm_core.dedup.shingles",
    "csm_core.dedup.corpus",
    "csm_core.dedup.index",
    "csm_core.dedup.analyzer",
    "csm_core.dedup.report",
    "csm_core.export",
    "csm_core.export.markdown",
    "csm_core.keyword",
    "csm_core.keyword.extractor",
    "csm_core.llm",
    "csm_core.llm.client",
    "csm_core.llm.prompts",
    # LLM providers are conditionally imported inside make_client();
    # list them so PyInstaller bundles every provider.
    "csm_core.llm.providers.mock",
    "csm_core.llm.providers.anthropic",
    "csm_core.llm.providers.openai",
    "csm_core.llm.providers.openai_compat",
    "csm_core.llm.providers.deepseek",
    "csm_core.llm.providers.gemini",
    "csm_core.llm.providers.qwen",
    # Monitor module
    "csm_core.monitor",
    "csm_core.monitor.base",
    "csm_core.monitor.scheduler",
    "csm_core.monitor.storage",
    "csm_core.monitor.notify",
    "csm_core.monitor.rate_limit",
    "csm_core.monitor.text_match",
    "csm_core.monitor.excel_import",
    # Platform adapters — same import-by-string pattern via platforms.ALL
    "csm_core.monitor.platforms",
    "csm_core.monitor.platforms.zhihu_question",
    "csm_core.monitor.platforms.bilibili_comment",
    "csm_core.monitor.platforms.douyin_comment",
    "csm_core.monitor.platforms.kuaishou_comment",
    # Drivers (cookie store + http session)
    "csm_core.monitor.drivers",
    "csm_core.monitor.drivers.cookie_store",
    "csm_core.monitor.drivers.http",
    "csm_core.monitor.drivers.browser",
    # Template + vault
    "csm_core.template",
    "csm_core.template.loader",
    "csm_core.template.schema",
    "csm_core.title",
    "csm_core.title.generator",
    "csm_core.vault",
    "csm_core.vault.scanner",
    "csm_core.vault.note_parser",
    "csm_core.vault.brand_registry",
    # Updater client
    "csm_core.updater_client",
    "csm_core.updater_client.checker",
    "csm_core.updater_client.downloader",
    "csm_core.updater_client.github_client",
    "csm_core.updater_client.manifest",
    # Sidecar package itself + every route + service.
    "csm_sidecar",
    "csm_sidecar.auth",
    "csm_sidecar.event_bus",
    "csm_sidecar.heartbeat",
    "csm_sidecar.lifespan",
    "csm_sidecar.logging_setup",
    "csm_sidecar.monitor_bus",
    # Routes are wired via include_router in main.py; PyInstaller sees
    # them via that import chain, but we list them too as defense.
    "csm_sidecar.routes",
    "csm_sidecar.routes.aggregation",
    "csm_sidecar.routes.article",
    "csm_sidecar.routes.batch",
    "csm_sidecar.routes.config",
    "csm_sidecar.routes.dedup",
    "csm_sidecar.routes.generate",
    "csm_sidecar.routes.monitor",
    "csm_sidecar.routes.skills",
    "csm_sidecar.routes.system",
    "csm_sidecar.routes.templates",
    "csm_sidecar.routes.updater",
    "csm_sidecar.routes.vault",
    "csm_sidecar.services",
    "csm_sidecar.services.aggregation_service",
    "csm_sidecar.services.batch_service",
    "csm_sidecar.services.config_service",
    "csm_sidecar.services.dedup_service",
    "csm_sidecar.services.export_service",
    "csm_sidecar.services.generate_service",
    "csm_sidecar.services.keyword_service",
    "csm_sidecar.services.llm_factory",
    "csm_sidecar.services.monitor_lifecycle",
    "csm_sidecar.services.monitor_loop",
    "csm_sidecar.services.monitor_service",
    "csm_sidecar.services.polish_service",
    "csm_sidecar.services.skills_service",
    "csm_sidecar.services.templates_service",
    "csm_sidecar.services.title_service",
    "csm_sidecar.services.updater_service",
    "csm_sidecar.services.vault_service",
    # Third-party — SDKs that resolve lazily.
    "anthropic",
    "frontmatter",
    "httpx",
    "tenacity",
    "pydantic",
    "click",
    "datasketch",
    "datasketch.minhash",
    "datasketch.lsh",
    "curl_cffi",
    "curl_cffi.requests",
    "DrissionPage",
    "fastapi",
    "uvicorn",
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    "sse_starlette",
    "starlette",
    "apscheduler",
    "apscheduler.schedulers.background",
    "apscheduler.triggers.interval",
    "keyring",
    "keyring.backends",
]
hiddenimports += collect_submodules("anthropic")
hiddenimports += collect_submodules("datasketch")
hiddenimports += collect_submodules("curl_cffi")
hiddenimports += collect_submodules("DrissionPage")
hiddenimports += collect_submodules("uvicorn")


# ── PyInstaller graph ──────────────────────────────────────────────────────
a = Analysis(
    ["csm_sidecar/__main__.py"],
    pathex=[".", ".."],  # so csm_core (one level up) is importable
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Sidecar is Qt-free; exclude every GUI lib so the bundle stays small.
        "tkinter",
        "PyQt5",
        "PyQt6",
        "PySide2",
        "PySide6",
        "qfluentwidgets",
        # Test machinery — never needed at runtime.
        "pytest",
        "_pytest",
        "pytest_asyncio",
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="csm-sidecar",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,           # ★ memory: UPX broke produced binaries — keep OFF.
    console=True,        # ★ Tauri reads stdout for the handshake JSON.
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="csm-sidecar",
)
