# Migration: PyQt6 → Tauri + Vue 3 + Python Sidecar

This folder holds the working artefacts for the v0.4 architecture
migration. The authoritative plan lives at
`C:\Users\EDY\.claude\plans\python-seo-sharded-sparrow.md`; the files
here are the executable / reviewable outputs.

## Stage A — sidecar + alignment

| File | Purpose | Status |
|---|---|---|
| `feature-ui-mapping.md` | Cross-table of `csm_core/` capabilities × CSM-RE1 V1 screens. Source of truth for what each Vue view needs and what `csm_core` can supply. | **A2 — to fill** |
| `api-contract.openapi.yaml` | Sidecar HTTP/SSE contract derived from the mapping. Generated/maintained alongside `sidecar/`. | A3 — to draft |

## Stage B/C — sidecar 接线 + 前端迁移

前端（Tauri 2 + Vue 3）与 Python sidecar 已成为唯一在用的栈；老 PyQt6 客户端在 Stage D 移除。

## Stage D — 移除 PyQt6 老栈 ✅（2026-06-13）

`csm_gui/`（PyQt6 桌面壳，v0.3.0）连同其专属测试 `tests/gui/`、PyInstaller
spec `CSM.spec`、启动入口 `main.py` 已删除。`pyproject.toml` 的 `gui` 可选依赖
（PyQt6 / PyQt6-Fluent-Widgets）、`csm-gui` 入口、`pytest-qt` 一并移除，包版本
来源由 `csm_gui._version` 改为 `csm_core.__version__`。

发布管线（`release.yml` / `release.py` / `build_sidecar.py`）此前已与老栈解耦
——CI 跑 `pip install -e .`（不含 `[gui]`），构建 sidecar + updater + Tauri NSIS
——故本次删除不影响发布。
