# 历史索引目录统一 + 段落筛选属性双下拉 + Templates/Skills 自动默认 — 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让段落筛选属性下拉零额外操作可用，把"历史索引目录"统一为成稿镜像/最近文档/查重三合一目录，Templates/Skills 在首次启动自动建好并种子内置样例。

**Architecture:**
- csm_core 暴露三个 `default_*_dir()` helper（仅路径计算）。
- sidecar lifespan 启动钩子负责：①补齐三个目录字段并 mkdir，②首次种子内置模板/Skills，③异步触发一次 vault 扫描。
- `export_service.export()` 在写完磁盘文件后，额外把正文以 .md 镜像写入历史目录。
- `aggregation_service` 数据源从 `out_dir` 切到历史目录。
- 前端：新增 `MultiValuePicker.vue` 多选下拉；`BlockEditor` 在 `/api/vault/attributes` 收 409 时自愈一次（POST scan + retry）；`SettingsView` 增加"历史索引目录"行；`RecentDocsCard / RecentHistoryView` 点击改用 `shell.open`。

**Tech Stack:** Python 3.12 / FastAPI / pydantic / python-frontmatter, Vue 3 + TypeScript + Pinia, Tauri 2 plugin-shell, pytest（sidecar）, vue-tsc（前端类型校验，无单测框架 — 前端靠 typecheck + 手工 smoke）。

**Spec:** [docs/superpowers/specs/2026-05-12-recent-history-and-vault-attrs-design.md](../specs/2026-05-12-recent-history-and-vault-attrs-design.md)

---

## File Structure

| 文件 | 角色 | 状态 |
|------|------|------|
| `csm_core/config.py` | 新增 `default_templates_dir / default_skills_dir / default_history_dir` | modify |
| `tests/csm_core/test_config_defaults.py` | csm_core 默认目录 helper 单测 | create |
| `sidecar/csm_sidecar/services/startup_dirs.py` | `ensure_default_dirs()` + `_seed_templates / _seed_skills` + `_resource_dir()` | create |
| `sidecar/tests/test_startup_dirs.py` | startup_dirs 单测 | create |
| `sidecar/csm_sidecar/lifespan.py` | lifespan 里调 `ensure_default_dirs` + 启动后台 `auto_scan_vault` 任务 | modify |
| `sidecar/csm_sidecar/services/export_service.py` | 新增 `_mirror_to_history` + `export()` 末尾调用，`export()` 接 `template_name` 形参 | modify |
| `sidecar/csm_sidecar/routes/article.py` | `ExportBody` 增加 `template_name: str \| None` | modify |
| `sidecar/tests/test_export_history_mirror.py` | mirror 写出/撞名/无配置/不可写降级测试 | create |
| `sidecar/csm_sidecar/services/aggregation_service.py` | `_resolve_history_dir` 替换 `_resolve_out_dir`，只列 `.md` | modify |
| `sidecar/tests/test_aggregation_routes.py` | 数据源切换 + 兼容旧的 `out_dir` 行为更新 | modify |
| `frontend/src/components/templates/MultiValuePicker.vue` | 多选下拉子组件，回退手填 | create |
| `frontend/src/components/templates/BlockEditor.vue` | 409 自愈 + 使用 MultiValuePicker | modify |
| `frontend/src/views/SettingsView.vue` | 「存储路径」加历史索引目录；「历史查重」降级为只读+重建 | modify |
| `frontend/src/components/home/RecentDocsCard.vue` | `openDoc` → `shell.open(path)` | modify |
| `frontend/src/views/RecentHistoryView.vue` | "打开"按钮改 `shell.open(file)`；文案改"用默认应用打开" | modify |
| `CHANGELOG.md` | 0.5.0 一行 release note | modify |

---

## Task 1: csm_core default 目录 helper

**Files:**
- Modify: `csm_core/config.py`
- Create: `tests/csm_core/test_config_defaults.py`

- [ ] **Step 1.1: 写失败测试**

Create `tests/csm_core/test_config_defaults.py`:

```python
"""default_*_dir helpers — pure path computation, no I/O."""
from __future__ import annotations

from pathlib import Path

from csm_core import config as core_config


def test_default_templates_dir_under_config_dir():
    assert core_config.default_templates_dir() == core_config.default_config_dir() / "Templates"


def test_default_skills_dir_under_config_dir():
    assert core_config.default_skills_dir() == core_config.default_config_dir() / "Skills"


def test_default_history_dir_under_config_dir():
    assert core_config.default_history_dir() == core_config.default_config_dir() / "History"


def test_helpers_return_path_objects():
    assert isinstance(core_config.default_templates_dir(), Path)
    assert isinstance(core_config.default_skills_dir(), Path)
    assert isinstance(core_config.default_history_dir(), Path)
```

- [ ] **Step 1.2: 跑测试确认失败**

```bash
cd D:/CSM/.claude/worktrees/heuristic-tesla-4d047a
python -m pytest tests/csm_core/test_config_defaults.py -v
```

Expected: AttributeError — `default_templates_dir` 等不存在。

- [ ] **Step 1.3: 加 helper**

Edit `csm_core/config.py`, in the path-helper region right after `default_config_path()`:

```python
def default_templates_dir() -> Path:
    """Per-user templates folder. Created on first sidecar startup if missing.

    Lives alongside settings.json so it survives app reinstall and stays
    writable even when the app is installed to Program Files.
    """
    return default_config_dir() / "Templates"


def default_skills_dir() -> Path:
    """Per-user Skills folder. Same rationale as default_templates_dir."""
    return default_config_dir() / "Skills"


def default_history_dir() -> Path:
    """Per-user history index folder — exports auto-mirror a .md copy here,
    and the home-screen 最近文档 list reads from this dir."""
    return default_config_dir() / "History"
```

- [ ] **Step 1.4: 跑测试**

```bash
python -m pytest tests/csm_core/test_config_defaults.py -v
```

Expected: 4 passed.

- [ ] **Step 1.5: Commit**

```bash
git add csm_core/config.py tests/csm_core/test_config_defaults.py
git commit -m "feat(config): add default_templates/skills/history_dir helpers"
```

---

## Task 2: startup_dirs 服务 — ensure_default_dirs + 种子样例

**Files:**
- Create: `sidecar/csm_sidecar/services/startup_dirs.py`
- Create: `sidecar/tests/test_startup_dirs.py`

- [ ] **Step 2.1: 写失败测试**

Create `sidecar/tests/test_startup_dirs.py`:

```python
"""Tests for ensure_default_dirs() — first-run directory bootstrap."""
from __future__ import annotations

from pathlib import Path

import pytest

from csm_sidecar.services import config_service, startup_dirs


@pytest.fixture
def cfg_path(tmp_path: Path):
    """Per-test settings.json path."""
    p = tmp_path / "settings.json"
    config_service.init(p)
    yield p
    config_service.init(None)


def test_fills_empty_fields_with_defaults(cfg_path: Path, tmp_path: Path, monkeypatch):
    user_dir = tmp_path / "user"
    monkeypatch.setattr(startup_dirs, "_default_config_dir", lambda: user_dir)
    monkeypatch.setattr(startup_dirs, "_resource_dir", lambda: tmp_path / "_no_resources_")

    startup_dirs.ensure_default_dirs()

    cfg = config_service.load()
    assert cfg.default_template == str(user_dir / "Templates")
    assert cfg.skill_dir == str(user_dir / "Skills")
    assert cfg.dedup_history_dir == str(user_dir / "History")
    assert (user_dir / "Templates").is_dir()
    assert (user_dir / "Skills").is_dir()
    assert (user_dir / "History").is_dir()


def test_does_not_overwrite_user_chosen_paths(cfg_path: Path, tmp_path: Path, monkeypatch):
    user_dir = tmp_path / "user"
    monkeypatch.setattr(startup_dirs, "_default_config_dir", lambda: user_dir)
    monkeypatch.setattr(startup_dirs, "_resource_dir", lambda: tmp_path / "_no_resources_")

    # Pre-populate user's own paths
    my_templates = tmp_path / "elsewhere" / "T"
    config_service.patch({
        "default_template": str(my_templates),
        "skill_dir": "",
        "dedup_history_dir": "",
    })

    startup_dirs.ensure_default_dirs()

    cfg = config_service.load()
    # User's choice preserved (and mkdir'd):
    assert cfg.default_template == str(my_templates)
    assert my_templates.is_dir()
    # Empty fields filled:
    assert cfg.skill_dir == str(user_dir / "Skills")
    assert cfg.dedup_history_dir == str(user_dir / "History")


def test_seeds_templates_when_user_dir_is_empty(cfg_path: Path, tmp_path: Path, monkeypatch):
    user_dir = tmp_path / "user"
    resource_dir = tmp_path / "resources"
    (resource_dir / "templates").mkdir(parents=True)
    (resource_dir / "templates" / "demo.json").write_text('{"v": 1}', encoding="utf-8")
    (resource_dir / "examples" / "skills").mkdir(parents=True)
    (resource_dir / "examples" / "skills" / "demo.md").write_text("# demo", encoding="utf-8")

    monkeypatch.setattr(startup_dirs, "_default_config_dir", lambda: user_dir)
    monkeypatch.setattr(startup_dirs, "_resource_dir", lambda: resource_dir)

    startup_dirs.ensure_default_dirs()

    assert (user_dir / "Templates" / "demo.json").is_file()
    assert (user_dir / "Skills" / "demo.md").is_file()


def test_does_not_re_seed_when_target_already_has_files(cfg_path: Path, tmp_path: Path, monkeypatch):
    user_dir = tmp_path / "user"
    (user_dir / "Templates").mkdir(parents=True)
    (user_dir / "Templates" / "user_made.json").write_text("user", encoding="utf-8")

    resource_dir = tmp_path / "resources"
    (resource_dir / "templates").mkdir(parents=True)
    (resource_dir / "templates" / "demo.json").write_text('{"v": 1}', encoding="utf-8")

    monkeypatch.setattr(startup_dirs, "_default_config_dir", lambda: user_dir)
    monkeypatch.setattr(startup_dirs, "_resource_dir", lambda: resource_dir)

    startup_dirs.ensure_default_dirs()

    # Seed must NOT copy demo.json because Templates dir is non-empty.
    assert not (user_dir / "Templates" / "demo.json").exists()
    assert (user_dir / "Templates" / "user_made.json").is_file()
```

- [ ] **Step 2.2: 跑测试确认失败**

```bash
python -m pytest sidecar/tests/test_startup_dirs.py -v
```

Expected: ModuleNotFoundError for `startup_dirs`.

- [ ] **Step 2.3: 实现 startup_dirs**

Create `sidecar/csm_sidecar/services/startup_dirs.py`:

```python
"""Startup directory bootstrap — runs once at sidecar startup.

Responsibilities:
1. Make sure ``default_template / skill_dir / dedup_history_dir`` point to
   real, writable folders. Empty fields are filled with per-user defaults
   under ``%LOCALAPPDATA%\\CSM\\CSM\\`` (see csm_core.config).
2. Seed brand-new Templates/Skills folders with the bundled samples so a
   fresh install has something to choose from. Skipped if the target dir
   already has content (won't clobber user-made templates).

Idempotent — safe to call repeatedly. Failures are logged but never raise:
the sidecar should still come up even if disk I/O is wonky.
"""
from __future__ import annotations

import logging
import shutil
import sys
from pathlib import Path

from csm_core import config as core_config

from . import config_service

logger = logging.getLogger(__name__)


# Indirection makes the two paths individually monkeypatch-able in tests
# without polluting csm_core or fiddling with sys._MEIPASS.
def _default_config_dir() -> Path:
    return core_config.default_config_dir()


def _resource_dir() -> Path:
    """Locate the bundled ``templates/`` and ``examples/`` resource roots.

    In a PyInstaller --onefile bundle these are extracted under
    ``sys._MEIPASS``. In dev (``python -m csm_sidecar.main``) they live at
    the repo root, two levels up from this file.
    """
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return Path(base)
    # csm_sidecar/services/startup_dirs.py -> sidecar/csm_sidecar/services -> sidecar -> repo
    return Path(__file__).resolve().parents[3]


def ensure_default_dirs() -> None:
    """Bootstrap user-data directories. Safe to call on every startup."""
    cfg = config_service.load()
    base = _default_config_dir()
    resource = _resource_dir()

    patches: dict[str, str] = {}

    plan = [
        ("default_template", base / "Templates", resource / "templates"),
        ("skill_dir",        base / "Skills",    resource / "examples" / "skills"),
        ("dedup_history_dir",base / "History",   None),
    ]

    for field, default_target, seed_source in plan:
        current = (getattr(cfg, field, None) or "").strip()
        target = Path(current) if current else default_target
        try:
            target.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logger.warning("ensure_default_dirs: mkdir %s failed: %s", target, e)
            continue
        if not current:
            patches[field] = str(target)
            if seed_source is not None:
                _seed_dir(seed_source, target)

    if patches:
        try:
            config_service.patch(patches)
        except Exception as e:
            logger.warning("ensure_default_dirs: persist patches failed: %s", e)


def _seed_dir(src: Path, dst: Path) -> None:
    """Copy every regular file from ``src`` into ``dst`` once.

    No-op when ``dst`` is already non-empty (user might have hand-curated
    templates we don't want to mix bundled samples into). Top-level files
    only — bundled templates/skills are flat.
    """
    if not src.is_dir():
        return
    try:
        if any(dst.iterdir()):
            return
    except OSError:
        return
    for f in src.iterdir():
        if not f.is_file():
            continue
        try:
            shutil.copy2(f, dst / f.name)
        except OSError as e:
            logger.warning("_seed_dir: copy %s -> %s failed: %s", f, dst, e)
```

- [ ] **Step 2.4: 跑测试**

```bash
python -m pytest sidecar/tests/test_startup_dirs.py -v
```

Expected: 4 passed.

- [ ] **Step 2.5: Commit**

```bash
git add sidecar/csm_sidecar/services/startup_dirs.py sidecar/tests/test_startup_dirs.py
git commit -m "feat(sidecar): startup_dirs bootstrap for templates/skills/history"
```

---

## Task 3: lifespan 调用 ensure_default_dirs + 异步 auto_scan_vault

**Files:**
- Modify: `sidecar/csm_sidecar/lifespan.py`
- Modify: `sidecar/tests/test_health.py`（确认启动钩子在测试模式跳过）

- [ ] **Step 3.1: 写失败测试**

Append to `sidecar/tests/test_startup_dirs.py`:

```python
def test_lifespan_calls_ensure_default_dirs_in_production(cfg_path: Path, tmp_path: Path, monkeypatch):
    """In non-test mode, lifespan should run ensure_default_dirs."""
    import asyncio

    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("CSM_SIDECAR_TESTING", raising=False)

    called: list[bool] = []
    monkeypatch.setattr(startup_dirs, "ensure_default_dirs", lambda: called.append(True))

    # Stub out MonitorLoop so we don't actually spin up apscheduler threads
    # for what is effectively a unit test of the lifespan glue.
    from csm_sidecar.services import monitor_lifecycle
    monkeypatch.setattr(monitor_lifecycle, "start", lambda: None)
    monkeypatch.setattr(monitor_lifecycle, "stop", lambda: None)

    from fastapi import FastAPI
    from csm_sidecar import lifespan as _lifespan

    async def run() -> None:
        async with _lifespan.lifespan(FastAPI()):
            pass

    asyncio.run(run())
    assert called == [True]


def test_lifespan_skips_dirs_in_test_mode(cfg_path: Path, monkeypatch):
    """In pytest mode, ensure_default_dirs should NOT be called to avoid
    writing to the real user config dir from test runs."""
    import asyncio

    monkeypatch.setenv("PYTEST_CURRENT_TEST", "yes")

    called: list[bool] = []
    monkeypatch.setattr(startup_dirs, "ensure_default_dirs", lambda: called.append(True))

    from fastapi import FastAPI
    from csm_sidecar import lifespan as _lifespan

    async def run() -> None:
        async with _lifespan.lifespan(FastAPI()):
            pass

    asyncio.run(run())
    assert called == []
```

- [ ] **Step 3.2: 跑测试确认失败**

```bash
python -m pytest sidecar/tests/test_startup_dirs.py::test_lifespan_calls_ensure_default_dirs_in_production -v
```

Expected: FAIL — lifespan 还没接 ensure_default_dirs。

- [ ] **Step 3.3: 改 lifespan**

Edit `sidecar/csm_sidecar/lifespan.py`, modify the `lifespan` async context to call `ensure_default_dirs` and kick off the vault scan:

```python
@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """FastAPI lifespan: token is minted before the app accepts requests.

    In production (non-pytest) we additionally:

    * Bootstrap default Templates/Skills/History directories on first run
      and seed the bundled samples.
    * Kick off a background vault scan so BlockEditor 属性下拉在用户登
      陆首屏前就准备好（fire-and-forget — 扫描失败/超时不阻塞 sidecar）。
    * Initialise the monitor sqlite db at ``<config_dir>/monitor.db``
    * Start the APScheduler-driven :class:`MonitorLoop`

    Under pytest these are skipped — fixtures opt in per test so failures
    in the monitor lifecycle don't bleed into unrelated tests."""
    if auth._TOKEN is None:
        auth.generate_token()
    started_monitor = False
    if not _is_test_run():
        try:
            from .services import startup_dirs
            startup_dirs.ensure_default_dirs()
        except Exception:
            logger.exception("ensure_default_dirs failed; continuing")
        try:
            import asyncio
            asyncio.create_task(_auto_scan_vault())
        except Exception:
            logger.exception("auto_scan_vault task scheduling failed; continuing")
        try:
            from .services import monitor_lifecycle
            monitor_lifecycle.start()
            started_monitor = True
        except Exception:
            logger.exception("MonitorLoop failed to start; continuing without it")
    try:
        yield
    finally:
        if started_monitor:
            try:
                from .services import monitor_lifecycle
                monitor_lifecycle.stop()
            except Exception:
                logger.exception("MonitorLoop shutdown raised; ignoring")


async def _auto_scan_vault() -> None:
    """Background vault scan on startup — fire-and-forget.

    Reads ``AppConfig.vault_root`` and walks the tree once so cold-start
    requests to ``/api/vault/attributes`` already see a cached index. The
    BlockEditor still has a 409 self-heal fallback so this task missing or
    crashing degrades gracefully.
    """
    try:
        from pathlib import Path
        from fastapi.concurrency import run_in_threadpool
        from .services import config_service, vault_service

        cfg = config_service.load()
        if not cfg.vault_root:
            return
        root = Path(cfg.vault_root)
        if not root.is_dir():
            return
        await run_in_threadpool(vault_service.scan, root)
        logger.info("auto vault scan completed: %s", root)
    except Exception as e:
        logger.warning("auto vault scan failed: %s", e)
```

- [ ] **Step 3.4: 跑测试**

```bash
python -m pytest sidecar/tests/test_startup_dirs.py -v
```

Expected: 6 passed.

- [ ] **Step 3.5: 跑整套 sidecar 测试确认没回归**

```bash
python -m pytest sidecar/tests/ -v
```

Expected: 所有原有测试通过（aggregation 测试此时仍假设 out_dir 数据源，将在 Task 5 调整 —— 但 Task 3 不应该破坏它，因为测试模式下 lifespan 跳过新钩子）。

- [ ] **Step 3.6: Commit**

```bash
git add sidecar/csm_sidecar/lifespan.py sidecar/tests/test_startup_dirs.py
git commit -m "feat(sidecar): wire ensure_default_dirs and auto vault scan into lifespan"
```

---

## Task 4: export_service 镜像 .md 到历史目录

**Files:**
- Modify: `sidecar/csm_sidecar/services/export_service.py`
- Modify: `sidecar/csm_sidecar/routes/article.py`
- Create: `sidecar/tests/test_export_history_mirror.py`

- [ ] **Step 4.1: 写失败测试**

Create `sidecar/tests/test_export_history_mirror.py`:

```python
"""Verify export() also writes a .md mirror into dedup_history_dir."""
from __future__ import annotations

from pathlib import Path

import frontmatter

from csm_sidecar.services import config_service, export_service


def test_markdown_export_mirrors_to_history(settings_path: Path, tmp_path: Path):
    out_dir = tmp_path / "out"
    history_dir = tmp_path / "history"
    out_dir.mkdir()
    history_dir.mkdir()
    config_service.patch({
        "out_dir": str(out_dir),
        "dedup_history_dir": str(history_dir),
    })

    body = "# 测试标题\n\n吸尘器推荐正文。"
    paths = export_service.export(
        keyword="吸尘器",
        final_text=body,
        fmt="markdown",
        template_name="导购文-基础",
    )
    assert paths["history_path"]
    mirror = Path(paths["history_path"])
    assert mirror.exists()
    assert mirror.suffix == ".md"
    post = frontmatter.loads(mirror.read_text(encoding="utf-8"))
    assert post["title"] == "测试标题"
    assert post["keyword"] == "吸尘器"
    assert post["template"] == "导购文-基础"
    assert post["source_format"] == "markdown"
    assert post["words"] > 0
    assert "exported_at" in post.metadata
    assert "吸尘器推荐正文" in post.content


def test_docx_export_also_mirrors_md(settings_path: Path, tmp_path: Path):
    out_dir = tmp_path / "out"
    history_dir = tmp_path / "history"
    out_dir.mkdir()
    history_dir.mkdir()
    config_service.patch({
        "out_dir": str(out_dir),
        "dedup_history_dir": str(history_dir),
    })

    body = "# 测试\n\n正文 docx 内容"
    paths = export_service.export(
        keyword="key",
        final_text=body,
        fmt="docx",
        template_name=None,
    )
    mirror = Path(paths["history_path"])
    assert mirror.suffix == ".md"
    post = frontmatter.loads(mirror.read_text(encoding="utf-8"))
    assert post["source_format"] == "docx"
    assert post["template"] is None


def test_mirror_filename_dedupes_on_collision(settings_path: Path, tmp_path: Path):
    out_dir = tmp_path / "out"
    history_dir = tmp_path / "history"
    out_dir.mkdir()
    history_dir.mkdir()
    config_service.patch({
        "out_dir": str(out_dir),
        "dedup_history_dir": str(history_dir),
    })

    # Pre-create a file with the same stem the exporter will pick.
    first = export_service.export(
        keyword="k", final_text="# a\n\nbody a", fmt="markdown", template_name=None
    )
    first_stem = Path(first["history_path"]).stem

    # Squat the next-export's mirror name to force the dedupe path.
    squatter = history_dir / f"{first_stem.replace('-1', '-2')}.md"
    squatter.write_text("squatter", encoding="utf-8")

    second = export_service.export(
        keyword="k", final_text="# b\n\nbody b", fmt="markdown", template_name=None
    )
    # The exporter picks the next free MMDD-N stem; if it happens to collide
    # with our squatter, the dedupe suffix path triggers and emits MMDD-N-2.
    mirror2 = Path(second["history_path"])
    assert mirror2.exists()
    assert mirror2.read_text(encoding="utf-8") != "squatter"


def test_mirror_skipped_when_history_dir_unset(settings_path: Path, tmp_path: Path):
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    config_service.patch({"out_dir": str(out_dir), "dedup_history_dir": ""})

    paths = export_service.export(
        keyword="x", final_text="# t\n\nbody", fmt="markdown", template_name=None
    )
    assert paths["history_path"] is None


def test_mirror_failure_does_not_break_export(settings_path: Path, tmp_path: Path, monkeypatch):
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    config_service.patch({
        "out_dir": str(out_dir),
        # Point history dir at a file (not a directory) — mkdir/write will fail.
        "dedup_history_dir": str(tmp_path / "blocker_file"),
    })
    (tmp_path / "blocker_file").write_text("not a dir", encoding="utf-8")

    paths = export_service.export(
        keyword="x", final_text="# t\n\nbody", fmt="markdown", template_name=None
    )
    # Primary export must still succeed.
    assert Path(paths["document"]).exists()
    assert paths["history_path"] is None
```

- [ ] **Step 4.2: 跑测试确认失败**

```bash
python -m pytest sidecar/tests/test_export_history_mirror.py -v
```

Expected: TypeError — `export()` 不接受 `template_name` 参数。

- [ ] **Step 4.3: 改 export_service 加 mirror**

Edit `sidecar/csm_sidecar/services/export_service.py`. Replace the whole file with:

```python
"""Export wrapper. Adds the optional dedup-report appendix the prototype
asks for in the export dialog (toggle '附带查重报告'), plus a .md mirror
to ``AppConfig.dedup_history_dir`` so the history index always contains
parsable markdown regardless of the user's chosen export format."""
from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import frontmatter

from csm_core.export.markdown import export_article, extract_title

from . import config_service

logger = logging.getLogger(__name__)

ExportFormat = Literal["markdown", "docx"]


def export(
    *,
    keyword: str,
    final_text: str,
    fmt: ExportFormat = "markdown",
    out_dir: str | None = None,
    include_dedup_report: bool = False,
    template_name: str | None = None,
) -> dict[str, Any]:
    """Write the article to disk and return the export descriptor.

    ``include_dedup_report`` runs a fresh dedup check and appends the
    report markdown to the article before writing. The dedup index must
    have been built (POST /api/dedup/build-index) — if not, the appendix
    is silently skipped with a warning so export still succeeds.

    Always mirrors a .md copy of ``final_text`` (without the dedup report
    appendix) to ``cfg.dedup_history_dir`` if configured. The mirror's
    frontmatter carries ``title / keyword / template / words /
    exported_at / source_format`` for downstream aggregation.
    """
    cfg = config_service.load()
    candidate = out_dir or cfg.out_dir
    if not candidate:
        raise ValueError("AppConfig.out_dir is unset and no out_dir override given")
    target_dir = Path(candidate)
    target_dir.mkdir(parents=True, exist_ok=True)

    body_for_export = final_text
    if include_dedup_report:
        try:
            from csm_core.dedup.analyzer import DedupAnalyzer  # local import: heavy
            analyzer = DedupAnalyzer()
            report = analyzer.analyze(final_text, kind="history")
            body_for_export = body_for_export + "\n\n---\n\n## 查重报告\n\n" + _format_report(report)
        except Exception:
            pass

    paths = export_article(
        out_dir=target_dir,
        keyword=keyword,
        final_text=body_for_export,
        fmt=fmt,
    )

    mirror = _mirror_to_history(
        history_dir=cfg.dedup_history_dir,
        keyword=keyword,
        final_text=final_text,            # without dedup appendix
        fmt=fmt,
        template_name=template_name,
        primary_path=paths["document"],
    )
    paths["history_path"] = str(mirror) if mirror else None
    return paths


def _mirror_to_history(
    *,
    history_dir: str,
    keyword: str,
    final_text: str,
    fmt: ExportFormat,
    template_name: str | None,
    primary_path: str,
) -> Path | None:
    """Write a .md copy of ``final_text`` into ``history_dir``. Returns
    the resulting Path on success, None on any failure (logged, never
    raises — the primary export must not fail because of mirror trouble).
    """
    if not history_dir:
        return None
    target_dir = Path(history_dir)
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        logger.warning("history dir not writable, skipping mirror: %s", e)
        return None

    stem = Path(primary_path).stem
    target = _dedupe_name(target_dir / f"{stem}.md")

    post = frontmatter.Post(
        content=final_text,
        title=extract_title(final_text) or stem,
        keyword=keyword,
        template=template_name,
        words=_count_chars(final_text),
        exported_at=datetime.now().isoformat(timespec="seconds"),
        source_format=fmt,
    )
    try:
        target.write_text(frontmatter.dumps(post), encoding="utf-8")
        return target
    except OSError as e:
        logger.warning("history mirror write failed: %s", e)
        return None


def _dedupe_name(p: Path) -> Path:
    """Suffix ``-2``, ``-3``, ... until the filename is free."""
    if not p.exists():
        return p
    i = 2
    while True:
        candidate = p.with_name(f"{p.stem}-{i}{p.suffix}")
        if not candidate.exists():
            return candidate
        i += 1


# Excluding whitespace + markdown punctuation matches what the legacy
# GUI 字数 panel showed and what aggregation_service uses.
_WS_OR_MD_PUNCT = re.compile(r"[\s\*#`>\-_]")


def _count_chars(text: str) -> int:
    return len(_WS_OR_MD_PUNCT.sub("", text or ""))


def _format_report(report: Any) -> str:
    out: list[str] = []
    out.append(f"- 全文重复率：**{getattr(report, 'duplicate_ratio', 0):.1%}**")
    out.append(f"- 全文长度：{getattr(report, 'text_length', 0)} 字")
    matches = getattr(report, "top_matches", []) or []
    if matches:
        out.append("\n### Top 命中来源\n")
        for m in matches[:3]:
            title = getattr(m, "title", "") or getattr(m, "path", "")
            ratio = getattr(m, "ratio", 0)
            out.append(f"- {title}（重叠率 {ratio:.1%}）")
    return "\n".join(out)
```

- [ ] **Step 4.4: 路由透传 template_name**

Edit `sidecar/csm_sidecar/routes/article.py`. Update `ExportBody`:

```python
class ExportBody(BaseModel):
    keyword: str = Field(min_length=1)
    final_text: str = Field(min_length=1)
    out_dir: str | None = None
    include_dedup_report: bool = False
    template_name: str | None = None
```

(No other changes needed — `body.model_dump()` already passes the field through.)

- [ ] **Step 4.5: 跑测试**

```bash
python -m pytest sidecar/tests/test_export_history_mirror.py -v
```

Expected: 5 passed.

- [ ] **Step 4.6: 跑 article 路由原有测试确认没回归**

```bash
python -m pytest sidecar/tests/test_article_routes.py -v
```

Expected: 所有原有测试通过（`template_name` 是可选字段，旧 body 仍能反序列化）。

- [ ] **Step 4.7: Commit**

```bash
git add sidecar/csm_sidecar/services/export_service.py sidecar/csm_sidecar/routes/article.py sidecar/tests/test_export_history_mirror.py
git commit -m "feat(sidecar): mirror exported article as .md to history dir"
```

---

## Task 5: aggregation_service 切换数据源到历史目录

**Files:**
- Modify: `sidecar/csm_sidecar/services/aggregation_service.py`
- Modify: `sidecar/tests/test_aggregation_routes.py`

- [ ] **Step 5.1: 改测试预期**

Edit `sidecar/tests/test_aggregation_routes.py`:

Replace **every** `out` setup（`out = tmp_path / "out"` + `client.patch("/api/config", json={"out_dir": str(out)})`）with `history` setup（`history = tmp_path / "history"` + `client.patch("/api/config", json={"dedup_history_dir": str(history)})`）。具体替换点：

- `test_recent_empty_when_out_dir_unset` → 重命名为 `test_recent_empty_when_history_unset` （行为不变，注释更新）。
- `test_recent_lists_files_newest_first` → 写入 `history / "old.md"` 和 `history / "new.md"`。
- `test_recent_drops_files_outside_window` → `history` 目录。
- `test_recent_limit_respected` → `history` 目录。
- `test_calendar_returns_zeros_when_no_files` → `dedup_history_dir`。
- `test_calendar_counts_per_day` → `history` 目录。
- `test_stats_words_returns_per_day_breakdown` → `history` 目录。
- `test_stats_words_yesterday_counts_yesterday` → `history` 目录。
- `test_stats_words_no_out_dir_returns_zeros` → 重命名 `test_stats_words_no_history_returns_zeros`。

新增一个测试确认 `.docx` 被忽略：

```python
def test_recent_only_lists_markdown(client: TestClient, tmp_path: Path):
    """History dir holds .md mirrors only — any stray .docx must be ignored."""
    history = tmp_path / "history"
    client.patch("/api/config", json={"dedup_history_dir": str(history)})
    _write_doc(history / "yes.md", title="md only")
    history.mkdir(parents=True, exist_ok=True)
    (history / "no.docx").write_bytes(b"not really a docx")
    data = client.get("/api/recent").json()
    assert data["count"] == 1
    assert data["documents"][0]["filename"] == "yes.md"
```

- [ ] **Step 5.2: 跑测试确认失败**

```bash
python -m pytest sidecar/tests/test_aggregation_routes.py -v
```

Expected: 大量 FAIL（数据源未切换，history dir 为空 → 列表空）。

- [ ] **Step 5.3: 改 aggregation_service**

Edit `sidecar/csm_sidecar/services/aggregation_service.py`. Replace `_resolve_out_dir` with `_resolve_history_dir` and switch all three public functions to call it; restrict `_iter_exported` to `.md`:

```python
# ── Helpers ────────────────────────────────────────────────────────────────
def _resolve_history_dir() -> Path | None:
    """Source-of-truth folder for 'recent docs' / calendar / words stats.

    Switched from ``out_dir`` to ``dedup_history_dir`` in 0.5.0 — the
    history dir holds .md mirrors of every export and is the only place
    the home screen needs to scan. See:
    docs/superpowers/specs/2026-05-12-recent-history-and-vault-attrs-design.md
    """
    cfg = config_service.load()
    return Path(cfg.dedup_history_dir) if cfg.dedup_history_dir else None


def _iter_exported(history_dir: Path):
    """Yield every .md under ``history_dir`` (recursive). Skips hidden files.

    History dir mirrors are .md only; we deliberately ignore .docx so a
    stray docx the user dropped in there doesn't pollute aggregations.
    """
    for p in history_dir.rglob("*.md"):
        if p.name.startswith("."):
            continue
        yield p
```

Replace **every** call site of `_resolve_out_dir()` in this file with `_resolve_history_dir()` (3 spots: `list_recent`, `calendar_for_month`, `words_for_range`). 重命名局部变量 `out_dir → history_dir`。删除旧的 `_resolve_out_dir` 函数体。

`_doc_word_count` 里的 docx 分支保留——以防历史目录里残留 docx 时 sanity check 不挂掉——但 `_iter_exported` 不会 yield 它。

- [ ] **Step 5.4: 跑测试**

```bash
python -m pytest sidecar/tests/test_aggregation_routes.py -v
```

Expected: 所有测试通过（含新增的 `test_recent_only_lists_markdown`）。

- [ ] **Step 5.5: Commit**

```bash
git add sidecar/csm_sidecar/services/aggregation_service.py sidecar/tests/test_aggregation_routes.py
git commit -m "feat(sidecar): aggregation reads from history dir, md only"
```

---

## Task 6: 整套 sidecar 测试跑通 + 检验启动钩子

**Files:**
- 无修改，只跑测试

- [ ] **Step 6.1: 跑全套 sidecar 测试**

```bash
python -m pytest sidecar/tests/ -v
```

Expected: 全部通过。如果有 vault 测试因为 lifespan 在生产路径自动扫描而 fail，回到 Task 3 检查 `_is_test_run()` 是否真的把启动钩子跳过了（应该跳过——`PYTEST_CURRENT_TEST` 是 pytest 默认设置的）。

- [ ] **Step 6.2: 跑 csm_core 测试**

```bash
python -m pytest tests/ -v
```

Expected: 全部通过。

- [ ] **Step 6.3: 不需要 commit（无文件改动）**

---

## Task 7: 前端 MultiValuePicker 多选下拉组件

**Files:**
- Create: `frontend/src/components/templates/MultiValuePicker.vue`

- [ ] **Step 7.1: 实现 MultiValuePicker**

Create `frontend/src/components/templates/MultiValuePicker.vue`:

```vue
<script setup lang="ts">
/**
 * 多选下拉 — 用于 BlockEditor 段落筛选的 value 字段。
 *
 *   - options 非空 → 渲染勾选下拉，多选行为复用 link 下拉那套 cream + dark hover；
 *   - options 空 → 回退为 free-text input（适用于 value_count > 20 的 key，或还没扫
 *     vault 时的兜底）。
 *
 * 对外契约：value 是逗号 / 中文逗号 / 顿号 分隔的字符串（与现有 commitFilters 兼容）。
 * 内部展开成数组维护勾选态。
 */
import { computed, ref } from "vue";

import Icon from "@/components/ui/Icon.vue";

const props = withDefaults(
  defineProps<{
    modelValue: string;
    options: string[];
    placeholder?: string;
    /** Force free-text mode even if options.length > 0. Used for low-cardinality but
     * still typing-friendly keys when caller wants to bypass the dropdown. */
    allowFreeText?: boolean;
  }>(),
  { placeholder: "如：引言乱象", allowFreeText: false },
);

const emit = defineEmits<{ (e: "update:modelValue", v: string): void }>();

const useDropdown = computed(() => props.options.length > 0 && !props.allowFreeText);

function parseSelected(s: string): string[] {
  return (s ?? "")
    .split(/[,，、]/)
    .map((x) => x.trim())
    .filter(Boolean);
}

const selected = computed<string[]>(() => parseSelected(props.modelValue));

function commit(arr: string[]) {
  emit("update:modelValue", arr.join(", "));
}

function toggle(v: string) {
  const set = new Set(selected.value);
  if (set.has(v)) set.delete(v);
  else set.add(v);
  commit([...set]);
}

const open = ref(false);

const buttonText = computed(() => {
  if (selected.value.length === 0) return props.placeholder;
  const joined = selected.value.join("、");
  return joined.length > 24 ? joined.slice(0, 22) + "…" : joined;
});
</script>

<template>
  <!-- Dropdown path -->
  <div v-if="useDropdown" class="relative" :style="{ minWidth: '0' }">
    <button
      type="button"
      class="flex w-full items-center justify-between gap-2 px-3 py-2 text-[12.5px]"
      :style="{
        background: 'var(--card-2)',
        border: '1px solid var(--line)',
        borderRadius: 'var(--radius-inner)',
        color: selected.length ? 'var(--ink)' : 'var(--ink-3)',
      }"
      @click="open = !open"
    >
      <span class="truncate text-left">{{ buttonText }}</span>
      <Icon name="arrowDown" :size="12" />
    </button>
    <div
      v-if="open"
      class="absolute z-10 mt-1 max-h-[240px] w-full overflow-y-auto p-1.5"
      :style="{
        background: 'var(--card-2)',
        border: '1px solid var(--line)',
        borderRadius: 'var(--radius-inner)',
        boxShadow: '0 6px 18px rgba(28,26,23,0.10)',
      }"
      @click.stop
    >
      <button
        v-for="opt in options"
        :key="opt"
        type="button"
        class="mvp-row flex w-full cursor-pointer items-center gap-2 px-2 py-1.5 text-left text-[12.5px]"
        :style="{
          borderRadius: '6px',
          background: selected.includes(opt) ? 'var(--primary-soft)' : 'transparent',
          color: selected.includes(opt) ? 'var(--primary-deep)' : 'var(--ink)',
        }"
        @click="toggle(opt)"
      >
        <span class="flex-1 truncate">{{ opt }}</span>
        <Icon
          v-if="selected.includes(opt)"
          name="check"
          :size="11"
          :style="{ color: 'var(--primary-deep)' }"
        />
      </button>
      <div class="flex justify-end pt-1">
        <button
          type="button"
          class="px-2 py-1 text-[11px]"
          :style="{ color: 'var(--ink-3)' }"
          @click="open = false"
        >
          完成
        </button>
      </div>
    </div>
  </div>

  <!-- Free-text fallback path -->
  <input
    v-else
    :value="modelValue"
    :placeholder="placeholder"
    class="bg-card-2 w-full px-3 py-2 text-[12.5px] outline-none"
    :style="{
      borderRadius: 'var(--radius-inner)',
      border: '1px solid var(--line)',
      minWidth: '0',
    }"
    @blur="(e) => emit('update:modelValue', (e.target as HTMLInputElement).value)"
  />
</template>

<style scoped>
.mvp-row:hover {
  background: var(--dark) !important;
  color: #fbf7ec !important;
}
.mvp-row:hover :deep(svg) {
  color: #fbf7ec !important;
}
</style>
```

- [ ] **Step 7.2: 类型校验**

```bash
cd frontend && npm run build
```

Expected: build 通过（组件还没被引用，但 vue-tsc 应能编译它）。

- [ ] **Step 7.3: Commit**

```bash
cd ..
git add frontend/src/components/templates/MultiValuePicker.vue
git commit -m "feat(frontend): MultiValuePicker dropdown component"
```

---

## Task 8: BlockEditor — 409 自愈 + 接入 MultiValuePicker

**Files:**
- Modify: `frontend/src/components/templates/BlockEditor.vue`

- [ ] **Step 8.1: 改 loadVaultAttrs 加自愈**

Edit `frontend/src/components/templates/BlockEditor.vue`. Replace the existing `loadVaultAttrs` (around line 211) with:

```ts
async function fetchAttrsRaw(): Promise<VaultAttribute[]> {
  const moduleScope: string | undefined = block.value?.source?.module;
  const r = await sidecar.client.get("/api/vault/attributes", {
    params: moduleScope ? { module: moduleScope } : {},
  });
  return r.data?.attributes ?? [];
}

async function loadVaultAttrs() {
  attrsLoading.value = true;
  attrsError.value = null;
  try {
    vaultAttrs.value = await fetchAttrsRaw();
  } catch (e: any) {
    if (e?.response?.status === 409) {
      // 409 = sidecar 还没有 vault 索引（lifespan 自动扫挂了 / 还没起来 /
      // 用户首次配置 vault 后还没重启）。主动触发一次 scan + retry。
      try {
        await sidecar.client.post("/api/vault/scan", {});
        vaultAttrs.value = await fetchAttrsRaw();
      } catch (inner: any) {
        const status = inner?.response?.status;
        if (status === 400) {
          attrsError.value = "尚未配置素材库 — 请在设置中指定 Vault";
        } else if (status === 404) {
          attrsError.value = "素材库目录不存在 — 请检查设置中的 Vault 路径";
        } else {
          attrsError.value = inner?.message ?? String(inner);
        }
        vaultAttrs.value = [];
      }
    } else {
      attrsError.value = e?.message ?? String(e);
      vaultAttrs.value = [];
    }
  } finally {
    attrsLoading.value = false;
  }
}
```

- [ ] **Step 8.2: 引入 MultiValuePicker + valueOptionsFor**

Right after the existing `valueHintFor` function, **add** (don't remove `valueHintFor` — it still drives the placeholder when free-text path is hit):

```ts
import MultiValuePicker from "./MultiValuePicker.vue";

const VALUE_OPTIONS_THRESHOLD = 20;

function valueOptionsFor(key: string): string[] {
  const meta = vaultAttrs.value.find((a) => a.key === key);
  if (!meta) return [];
  // 后端已经把 sample_values 截到 20；这里只是双保险确认。
  if (meta.value_count > VALUE_OPTIONS_THRESHOLD) return [];
  return meta.sample_values ?? [];
}
```

The `import` statement should sit alongside the other imports near the top of the `<script setup>` block (around line 30, with the other component imports).

- [ ] **Step 8.3: 把 value `<input>` 替换为 `<MultiValuePicker>`**

Find the value input inside the filter rows (around lines 589-599):

```vue
<input
  :value="row.value"
  :placeholder="valueHintFor(row.key)"
  class="bg-card-2 flex-[3] px-3 py-2 text-[12.5px] outline-none"
  :style="{
    borderRadius: 'var(--radius-inner)',
    border: '1px solid var(--line)',
    minWidth: '0',
  }"
  @blur="(e) => updateFilterRow(i, { value: (e.target as HTMLInputElement).value })"
/>
```

Replace with:

```vue
<div class="flex-[3]" :style="{ minWidth: '0' }">
  <MultiValuePicker
    :model-value="row.value"
    :options="valueOptionsFor(row.key)"
    :placeholder="valueHintFor(row.key)"
    @update:model-value="(v) => updateFilterRow(i, { value: v })"
  />
</div>
```

- [ ] **Step 8.4: 类型校验**

```bash
cd frontend && npm run build
```

Expected: 通过。

- [ ] **Step 8.5: 手工 smoke**

启动 dev：

```bash
cd frontend && npm run tauri:dev
```

- 在「设置 → 存储路径」选一个 vault；
- 等 sidecar 重启（dev 模式手动 kill sidecar 进程 / 重 `tauri:dev`），让 lifespan 钩子触发自动扫描；
- 打开模板编辑器 → 新建/编辑一个段落 → "筛选" key 下拉应能看到 vault 里的 frontmatter 字段；
- 选 `module=营销资料库/产品模块/吸尘器` 之类的范围 + 选 key（比如 `品牌`），value 应显示为多选下拉，能勾选品牌名。

- [ ] **Step 8.6: Commit**

```bash
cd ..
git add frontend/src/components/templates/BlockEditor.vue
git commit -m "feat(frontend): BlockEditor self-heals vault attrs on 409, value as multi-select"
```

---

## Task 9: SettingsView — 加历史索引目录，dedup section 降级

**Files:**
- Modify: `frontend/src/views/SettingsView.vue`

- [ ] **Step 9.1: 「存储路径」加历史索引目录行**

Edit `frontend/src/views/SettingsView.vue`. In the `paths` section block (the `<template v-else-if="section === 'paths'">` around line 666), 在「Skills 目录」行**之前**插入一个新 `<SettingsRow>`：

```vue
<SettingsRow
  label="历史索引目录"
  hint="成稿镜像 / 最近文档 / 查重历史 — 三合一目录，首次启动已自动建好"
>
  <PathField
    :value="get('dedup_history_dir') ?? ''"
    title="选择历史索引目录"
    @update="(v) => setField('dedup_history_dir', v)"
  />
</SettingsRow>
```

并把现在「Skills 目录」行的 `last` prop 保留（只有最后一行需要 `last`）；把"默认模板目录"和"Skills 目录"两行的 hint 改成：

- 「默认模板目录」hint：`"模板 .json 所在文件夹 — 首次启动已自动建好，可改位置"`
- 「Skills 目录」hint：`"Skill .md 目录 — 首次启动已自动建好，可改位置"`

- [ ] **Step 9.2: 「历史查重」section 降级 PathField**

In the `dedup` section block (around line 957), find:

```vue
<SettingsRow
  label="历史索引目录"
  hint="历史成稿所在文件夹 — 用于「撞稿」检测"
>
  <PathField
    :value="get('dedup_history_dir') ?? ''"
    title="选择历史索引目录"
    @update="(v) => setField('dedup_history_dir', v)"
  />
</SettingsRow>
```

Replace with：

```vue
<SettingsRow
  label="历史索引目录"
  hint="位置在「存储路径」section 修改"
>
  <span
    class="font-mono truncate text-[11px]"
    :style="{
      color: 'var(--ink-3)',
      maxWidth: '340px',
      display: 'inline-block',
    }"
    :title="get('dedup_history_dir') ?? ''"
  >
    {{ get('dedup_history_dir') || '— 未设置 —' }}
  </span>
</SettingsRow>
```

- [ ] **Step 9.3: 类型校验 + 手工核对**

```bash
cd frontend && npm run build
```

Expected: 通过。

- [ ] **Step 9.4: 手工 smoke**

```bash
npm run tauri:dev
```

- 设置 → 存储路径：看到四行（素材库 / 导出目录 / 历史索引目录 / 默认模板目录 / Skills 目录）；
- 历史索引目录默认值应是 `%LOCALAPPDATA%\CSM\CSM\History`（首次启动 lifespan 已填）；
- 切到「历史查重」section：历史索引目录变成只读地址 + 「重建」按钮仍在。

- [ ] **Step 9.5: Commit**

```bash
cd ..
git add frontend/src/views/SettingsView.vue
git commit -m "feat(frontend): SettingsView — history dir under 存储路径, dedup section read-only"
```

---

## Task 10: 最近文档点击 → shell.open

**Files:**
- Modify: `frontend/src/components/home/RecentDocsCard.vue`
- Modify: `frontend/src/views/RecentHistoryView.vue`

- [ ] **Step 10.1: 改 RecentDocsCard.openDoc**

Edit `frontend/src/components/home/RecentDocsCard.vue`. Replace the existing `openDoc` (around line 104):

```ts
async function openDoc(d: Doc) {
  // 点击 = 用系统默认应用打开 md（VS Code / Typora / Notepad）。
  // 应用内"打开历史文章"是单独的迭代（涉及 article store 改造）。
  // 兜底：没有 path 字段（不应出现 — 当前所有 docs 都来自 /api/recent）→ 跳创作区。
  if (!d.path) {
    router.push({ name: "article" });
    return;
  }
  try {
    const isTauri =
      typeof window !== "undefined" &&
      // @ts-expect-error — ambient Tauri global
      Boolean(window.__TAURI_INTERNALS__ || window.__TAURI__);
    if (!isTauri) {
      // dev 浏览器模式没有 plugin-shell — 至少把路径显出来。
      const { useToast } = await import("@/composables/useToast");
      useToast().info(`文件位置：${d.path}`);
      return;
    }
    const { open } = await import("@tauri-apps/plugin-shell");
    await open(d.path);
  } catch (e: any) {
    const { useToast } = await import("@/composables/useToast");
    useToast().error(`打开失败：${e?.message ?? e}`);
  }
}
```

- [ ] **Step 10.2: 改 RecentHistoryView.openDoc + 文案**

Edit `frontend/src/views/RecentHistoryView.vue`. Replace `openDoc` (around line 123):

```ts
async function openDoc(d: Doc) {
  try {
    const isTauri =
      typeof window !== "undefined" &&
      // @ts-expect-error — ambient Tauri global
      Boolean(window.__TAURI_INTERNALS__ || window.__TAURI__);
    if (!isTauri) {
      toast.info(`文件位置：${d.path}`);
      return;
    }
    const { open } = await import("@tauri-apps/plugin-shell");
    await open(d.path);
  } catch (e: any) {
    toast.error(`打开失败：${e?.message ?? e}`);
  }
}
```

Then find the "打开" Btn (around line 294):

```vue
<Btn variant="ghost" small @click="openDoc(d)">
  <Icon name="edit" :size="12" />
  <span>打开</span>
</Btn>
```

Replace with:

```vue
<Btn variant="ghost" small @click="openDoc(d)">
  <Icon name="edit" :size="12" />
  <span>用默认应用打开</span>
</Btn>
```

- [ ] **Step 10.3: 类型校验**

```bash
cd frontend && npm run build
```

Expected: 通过。

- [ ] **Step 10.4: 手工 smoke**

```bash
npm run tauri:dev
```

- 在创作区生成并导出一篇 md → 回到首页 → 点最近文档卡里的条目 → 系统默认 md 编辑器（如 Typora / Notepad）打开真文件；
- 进 RecentHistoryView → 点「用默认应用打开」→ 同上。

- [ ] **Step 10.5: Commit**

```bash
cd ..
git add frontend/src/components/home/RecentDocsCard.vue frontend/src/views/RecentHistoryView.vue
git commit -m "feat(frontend): recent docs click opens file with system default app"
```

---

## Task 11: CHANGELOG + 终局 smoke

**Files:**
- Modify: `CHANGELOG.md`

- [ ] **Step 11.1: 加一行 release note**

Edit `CHANGELOG.md`. 在最顶 `## Unreleased` 区域（如果没有就在文件顶部新建一个）增加：

```markdown
## Unreleased

- 段落筛选属性下拉在配置 Vault 后零额外操作即可使用；value 支持多选。
- 新增"历史索引目录"概念：导出文章会自动以 .md 镜像到该目录；最近文档 / 字数统计 / 日历改用此目录作为数据源。**旧用户首次启动后，已有 `out_dir` 下的旧导出不会出现在最近文档中——历史归零是预期行为。**
- Templates / Skills / History 三个目录在首次启动自动建好（位于 `%LOCALAPPDATA%\CSM\CSM\` 下），内置样例模板/Skills 自动种子。
- 最近文档点击改为用系统默认应用打开文件。
```

- [ ] **Step 11.2: 终局 sidecar + csm_core 测试**

```bash
python -m pytest sidecar/tests/ tests/ -v
```

Expected: 全部通过。

- [ ] **Step 11.3: 终局前端类型校验**

```bash
cd frontend && npm run build && cd ..
```

Expected: 通过。

- [ ] **Step 11.4: 终局 Tauri smoke（按 spec §测试计划的手工 smoke 清单）**

逐项跑：

- [Win11 / 已构建 release 安装包] 安装到默认位置 → 启动应用 → 设置面板检查：
  - 「存储路径」「默认模板目录」「Skills 目录」「历史索引目录」三个字段都已自动填好且目录存在；
  - `%LOCALAPPDATA%\CSM\CSM\Templates\` 内有 `daogou-changjing-renqun.json` / `daogou-kepuwuping.json` 两份样例；
  - `%LOCALAPPDATA%\CSM\CSM\Skills\` 内有 4 份样例 .md；
  - `%LOCALAPPDATA%\CSM\CSM\History\` 存在且为空。
- 设置 Vault → 重启 → 模板编辑器段落筛选 key 下拉直接可用，value 出现多选下拉。
- 创作区生成一篇 → 导出 md → 历史目录里出现镜像 .md（frontmatter 含 keyword/template/words/exported_at）；首页"最近文档"立即显示。
- 导出 docx → 历史目录里仍出现 .md（同上）；`out_dir` 仍存 docx。
- 首页"最近文档"点击 → Typora/默认编辑器打开真实文件。
- RecentHistoryView 「用默认应用打开」按钮行为同上。

- [ ] **Step 11.5: Commit**

```bash
git add CHANGELOG.md
git commit -m "docs(changelog): record history dir + vault attrs + auto-default dirs"
```

- [ ] **Step 11.6: 推送 + 开 PR**

```bash
git push -u origin claude/heuristic-tesla-4d047a
gh pr create --title "feat: 历史索引目录统一 + 段落筛选属性双下拉 + Templates/Skills 自动默认" --body "$(cat <<'EOF'
## Summary
- 统一"历史索引目录"为成稿镜像 / 最近文档 / 查重历史三合一目录
- 段落筛选属性下拉首次启动后零额外操作可用；value 支持多选
- Templates / Skills / History 三个目录在 \`%LOCALAPPDATA%\CSM\CSM\\` 下自动创建并种子样例
- 最近文档点击改为系统默认应用打开

设计稿：\`docs/superpowers/specs/2026-05-12-recent-history-and-vault-attrs-design.md\`
实施计划：\`docs/superpowers/plans/2026-05-12-recent-history-and-vault-attrs.md\`

## Test plan
- [ ] \`python -m pytest sidecar/tests/ tests/ -v\` 全过
- [ ] \`cd frontend && npm run build\` 类型校验通过
- [ ] Win11 release 安装包 → 全新用户首次启动 → 设置面板三个默认目录自动填好且 mkdir
- [ ] 设置 Vault → 重启 → 模板段落筛选 key 下拉直接可用
- [ ] 导出 md / docx → 历史目录都出现 .md 镜像（frontmatter 完整）
- [ ] 首页"最近文档"点击 → 系统默认应用打开真实文件

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```
