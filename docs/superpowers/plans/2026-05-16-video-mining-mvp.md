# Video Mining MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a new `MiningView` to CSM that takes a keyword, drives Patchright headed browsers against 抖音/B站/快手 search pages, scrapes ≈50 videos per platform into a deduped SQLite store, and reverse-looks-up `monitor_tasks` so already-commented videos are marked.

**Architecture:** Extract shared browser primitives (`cookie_store`, `ua_pool`, `rate_limit`, `patchright_pool`, `interactive_login`) from `csm_core/monitor/` up to a new `csm_core/browser_infra/` package via re-export shims. Add a new `csm_core/mining/` package with three search adapters that share a `SearchAdapter` Protocol and a `MiningRunner` orchestrator running platforms serially. Mining persists into 3 new SQLite tables in the existing monitor DB (`mining_jobs`, `videos`, `video_source_keywords`). Sidecar exposes `/api/mining/*` routes with SSE progress events on the existing `event_bus`. Vue 3 frontend adds `MiningView` + Pinia `mining` store.

**Tech Stack:** Python 3.11, Patchright (Playwright fork), FastAPI, SQLite 3 (stdlib), pytest, Vue 3, Pinia, Tauri 2.

**Spec reference:** `docs/superpowers/specs/2026-05-16-video-mining-mvp-design.md`

---

## Phase 1 — Browser infra extraction (5 file moves + relocation test)

These tasks are mechanical: move file, add re-export shim, run tests. Goal is zero behavior change. Existing monitor adapters keep importing from `csm_core.monitor.drivers.*` and `csm_core.monitor.rate_limit` via the shims.

### Task 1: Create `csm_core/browser_infra/` package and move `cookie_store.py`

**Files:**
- Create: `csm_core/browser_infra/__init__.py`
- Create: `csm_core/browser_infra/cookie_store.py` (moved from monitor/drivers)
- Modify: `csm_core/monitor/drivers/cookie_store.py` (becomes re-export shim)

- [ ] **Step 1: Create the package directory and `__init__.py`**

Create `csm_core/browser_infra/__init__.py` with content:
```python
"""Shared browser-automation primitives used by both monitor and mining.

Originally lived under ``csm_core/monitor/drivers/``; promoted to a
top-level package when the mining module was added so it could be
imported without pulling in monitor-specific code.

Re-export shims remain under ``csm_core/monitor/drivers/`` and
``csm_core/monitor/`` so existing imports continue to work unchanged.
"""
```

- [ ] **Step 2: Move `cookie_store.py` contents to `csm_core/browser_infra/cookie_store.py`**

Open `csm_core/monitor/drivers/cookie_store.py`, copy its entire content into a new file at `csm_core/browser_infra/cookie_store.py`. Do not change any code.

- [ ] **Step 3: Replace old file with re-export shim**

Replace the contents of `csm_core/monitor/drivers/cookie_store.py` with:
```python
"""Re-export shim. Real implementation lives in csm_core.browser_infra.cookie_store.

Kept here so existing imports like ``from csm_core.monitor.drivers.cookie_store
import CookieStore`` continue to work after the v0.5 browser_infra extraction.
"""
from csm_core.browser_infra.cookie_store import *  # noqa: F401,F403
from csm_core.browser_infra.cookie_store import CookieStore  # noqa: F401  # explicit re-export
```

- [ ] **Step 4: Run all existing monitor tests to verify no break**

Run: `pytest sidecar/tests/ -x -q`
Expected: all existing tests pass.

- [ ] **Step 5: Commit**

```bash
git add csm_core/browser_infra/__init__.py csm_core/browser_infra/cookie_store.py csm_core/monitor/drivers/cookie_store.py
git commit -m "refactor(browser-infra): move cookie_store from monitor.drivers up to top-level"
```

---

### Task 2: Move `ua_pool.py`

**Files:**
- Create: `csm_core/browser_infra/ua_pool.py`
- Modify: `csm_core/monitor/drivers/ua_pool.py` (becomes shim)

- [ ] **Step 1: Move content**

Copy entire content of `csm_core/monitor/drivers/ua_pool.py` into `csm_core/browser_infra/ua_pool.py` without changes.

- [ ] **Step 2: Replace original with shim**

Replace `csm_core/monitor/drivers/ua_pool.py` with:
```python
"""Re-export shim. Real implementation in csm_core.browser_infra.ua_pool."""
from csm_core.browser_infra.ua_pool import *  # noqa: F401,F403
```

- [ ] **Step 3: Run tests**

Run: `pytest sidecar/tests/test_ua_pool.py -x -q`
Expected: pass.

- [ ] **Step 4: Commit**

```bash
git add csm_core/browser_infra/ua_pool.py csm_core/monitor/drivers/ua_pool.py
git commit -m "refactor(browser-infra): move ua_pool to top-level"
```

---

### Task 3: Move `rate_limit.py`

**Files:**
- Create: `csm_core/browser_infra/rate_limit.py`
- Modify: `csm_core/monitor/rate_limit.py` (becomes shim)

- [ ] **Step 1: Move content**

Copy entire content of `csm_core/monitor/rate_limit.py` into `csm_core/browser_infra/rate_limit.py` unchanged.

- [ ] **Step 2: Replace original with shim**

Replace `csm_core/monitor/rate_limit.py` with:
```python
"""Re-export shim. Real implementation in csm_core.browser_infra.rate_limit."""
from csm_core.browser_infra.rate_limit import *  # noqa: F401,F403
from csm_core.browser_infra.rate_limit import (  # noqa: F401
    RequestPacer, CircuitBreaker, slot,
    get_pacer, get_breaker, configure_pacing, configure_concurrency,
    acquire_slot, release_slot,
)
```

- [ ] **Step 3: Run tests**

Run: `pytest sidecar/tests/ -x -q -k "monitor"`
Expected: pass.

- [ ] **Step 4: Commit**

```bash
git add csm_core/browser_infra/rate_limit.py csm_core/monitor/rate_limit.py
git commit -m "refactor(browser-infra): move rate_limit to top-level"
```

---

### Task 4: Move `patchright_pool.py`

**Files:**
- Create: `csm_core/browser_infra/patchright_pool.py`
- Modify: `csm_core/monitor/drivers/patchright_pool.py` (becomes shim)

- [ ] **Step 1: Move content**

Copy entire content of `csm_core/monitor/drivers/patchright_pool.py` into `csm_core/browser_infra/patchright_pool.py` unchanged.

- [ ] **Step 2: Replace original with shim**

Replace `csm_core/monitor/drivers/patchright_pool.py` with:
```python
"""Re-export shim. Real implementation in csm_core.browser_infra.patchright_pool."""
from csm_core.browser_infra.patchright_pool import *  # noqa: F401,F403
from csm_core.browser_infra.patchright_pool import (  # noqa: F401
    ensure_browsers_path, configure, get_page, shutdown,
    set_cookies_for_domain, clear_cookies_for_domain, read_cookie_names,
    IDLE_SHUTDOWN_SECONDS,
)
```

- [ ] **Step 3: Run tests**

Run: `pytest sidecar/tests/ -x -q`
Expected: pass.

- [ ] **Step 4: Commit**

```bash
git add csm_core/browser_infra/patchright_pool.py csm_core/monitor/drivers/patchright_pool.py
git commit -m "refactor(browser-infra): move patchright_pool to top-level"
```

---

### Task 5: Move `interactive_login.py`

**Files:**
- Create: `csm_core/browser_infra/interactive_login.py`
- Modify: `csm_core/monitor/drivers/interactive_login.py` (becomes shim)

- [ ] **Step 1: Move content**

Copy entire content of `csm_core/monitor/drivers/interactive_login.py` into `csm_core/browser_infra/interactive_login.py`.

**Important:** the original file imports `from .. import storage` (relative import to monitor.storage). After the move, that breaks because `..` resolves differently. Change the import in the new file at `csm_core/browser_infra/interactive_login.py` to:

```python
from csm_core.monitor import storage  # absolute — interactive login still writes to monitor cookie table
```

- [ ] **Step 2: Replace original with shim**

Replace `csm_core/monitor/drivers/interactive_login.py` with:
```python
"""Re-export shim. Real implementation in csm_core.browser_infra.interactive_login."""
from csm_core.browser_infra.interactive_login import *  # noqa: F401,F403
```

- [ ] **Step 3: Run tests**

Run: `pytest sidecar/tests/ -x -q`
Expected: pass.

- [ ] **Step 4: Commit**

```bash
git add csm_core/browser_infra/interactive_login.py csm_core/monitor/drivers/interactive_login.py
git commit -m "refactor(browser-infra): move interactive_login to top-level"
```

---

### Task 6: Relocation regression test

**Files:**
- Create: `sidecar/tests/test_browser_infra_relocation.py`

- [ ] **Step 1: Write the test**

Create `sidecar/tests/test_browser_infra_relocation.py`:
```python
"""Regression test: monitor.drivers and monitor.rate_limit re-export shims work.

After moving browser primitives up to csm_core/browser_infra/, every old
import path must still resolve to the same object as the new path.
A single failure here means an outside caller (or the bundled exe) breaks.
"""
import importlib


def _assert_same_object(old_path: str, new_path: str, attr: str) -> None:
    old_mod = importlib.import_module(old_path)
    new_mod = importlib.import_module(new_path)
    assert getattr(old_mod, attr) is getattr(new_mod, attr), (
        f"{old_path}.{attr} is not {new_path}.{attr} — shim re-export broken"
    )


def test_cookie_store_reexport():
    _assert_same_object(
        "csm_core.monitor.drivers.cookie_store",
        "csm_core.browser_infra.cookie_store",
        "CookieStore",
    )


def test_ua_pool_reexport_module_loads():
    # ua_pool has functions, not a single class — just verify both modules
    # have the same set of public attributes.
    old = importlib.import_module("csm_core.monitor.drivers.ua_pool")
    new = importlib.import_module("csm_core.browser_infra.ua_pool")
    old_public = {a for a in dir(old) if not a.startswith("_")}
    new_public = {a for a in dir(new) if not a.startswith("_")}
    # Old shim should export at least what new module exports.
    missing = new_public - old_public
    # Allow extras (re-export `*` may pull module-level names) but no missing.
    assert not missing, f"missing on shim: {missing}"


def test_rate_limit_reexport():
    for sym in ("RequestPacer", "CircuitBreaker", "get_pacer", "get_breaker"):
        _assert_same_object(
            "csm_core.monitor.rate_limit",
            "csm_core.browser_infra.rate_limit",
            sym,
        )


def test_patchright_pool_reexport():
    for sym in ("ensure_browsers_path", "get_page", "shutdown"):
        _assert_same_object(
            "csm_core.monitor.drivers.patchright_pool",
            "csm_core.browser_infra.patchright_pool",
            sym,
        )


def test_interactive_login_reexport_loads():
    # Just verify importing the shim doesn't ImportError.
    importlib.import_module("csm_core.monitor.drivers.interactive_login")
    importlib.import_module("csm_core.browser_infra.interactive_login")
```

- [ ] **Step 2: Run the test**

Run: `pytest sidecar/tests/test_browser_infra_relocation.py -v`
Expected: 5 tests pass.

- [ ] **Step 3: Commit**

```bash
git add sidecar/tests/test_browser_infra_relocation.py
git commit -m "test(browser-infra): assert monitor re-export shims still resolve"
```

---

## Phase 2 — Mining data layer

### Task 7: Mining storage — schema migration v2 → v3

**Files:**
- Create: `csm_core/mining/__init__.py`
- Create: `csm_core/mining/storage.py`
- Modify: `csm_core/monitor/storage.py` (bump `_SCHEMA_VERSION` to 3, extend `_migrate`)

The mining module shares the monitor SQLite DB. To keep migrations centralized, the v3 migration lives in `monitor/storage.py` but the table-creation SQL is contributed by `mining/storage.py` via a hook.

- [ ] **Step 1: Create `csm_core/mining/__init__.py`**

Empty marker file:
```python
"""Video mining module — keyword search across 抖音/B站/快手, dedup, store."""
```

- [ ] **Step 2: Write `csm_core/mining/storage.py` skeleton with DDL constants**

Create `csm_core/mining/storage.py`:
```python
"""SQLite storage layer for the mining module.

Shares the monitor DB file (same ``init_db`` path). The 3 mining tables
are added in schema v3 — see ``_DDL_V3_MINING`` below; the actual
``ALTER`` / ``CREATE`` is run by ``csm_core.monitor.storage._migrate``
which knows the current version. Splitting the DDL list out here keeps
mining-specific concerns out of monitor/storage.py while still using
the same migration runner.

Connection model: re-uses ``monitor.storage.get_conn()`` — there is one
sqlite3.Connection per thread, WAL + foreign_keys on. Mining inserts
are autocommit (each ``on_card`` callback writes one row triple), no
explicit transactions needed; the runner already throttles cards to
≤1/200ms so WAL doesn't thrash.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Any, Iterable

from csm_core.monitor import storage as monitor_storage


# ── Schema v3 additions ─────────────────────────────────────────────────
_DDL_V3_MINING: list[str] = [
    """
    CREATE TABLE IF NOT EXISTS mining_jobs (
        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
        keyword             TEXT NOT NULL,
        platforms_json      TEXT NOT NULL,
        target_per_platform INTEGER NOT NULL DEFAULT 50,
        status              TEXT NOT NULL,
        progress_json       TEXT NOT NULL DEFAULT '{}',
        error_message       TEXT NOT NULL DEFAULT '',
        created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        started_at          TEXT,
        finished_at         TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_mining_jobs_keyword ON mining_jobs(keyword)",
    "CREATE INDEX IF NOT EXISTS idx_mining_jobs_created ON mining_jobs(created_at DESC)",
    """
    CREATE TABLE IF NOT EXISTS videos (
        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
        platform            TEXT NOT NULL,
        platform_video_id   TEXT NOT NULL,
        url                 TEXT NOT NULL,
        title               TEXT NOT NULL DEFAULT '',
        author_name         TEXT NOT NULL DEFAULT '',
        author_id           TEXT NOT NULL DEFAULT '',
        cover_url           TEXT NOT NULL DEFAULT '',
        duration_sec        INTEGER,
        play_count          INTEGER,
        like_count          INTEGER,
        published_at        TEXT,
        raw_json            TEXT NOT NULL DEFAULT '{}',
        excluded            INTEGER NOT NULL DEFAULT 0,
        already_commented   INTEGER NOT NULL DEFAULT 0,
        commented_source    TEXT,
        commented_at        TEXT,
        first_seen_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        UNIQUE(platform, platform_video_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_videos_platform ON videos(platform)",
    "CREATE INDEX IF NOT EXISTS idx_videos_first_seen ON videos(first_seen_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_videos_already_commented ON videos(already_commented, platform)",
    """
    CREATE TABLE IF NOT EXISTS video_source_keywords (
        video_id        INTEGER NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
        keyword         TEXT NOT NULL,
        job_id          INTEGER NOT NULL REFERENCES mining_jobs(id) ON DELETE CASCADE,
        rank_in_search  INTEGER NOT NULL,
        found_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        PRIMARY KEY (video_id, keyword, job_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_vsk_keyword ON video_source_keywords(keyword)",
    "CREATE INDEX IF NOT EXISTS idx_vsk_job ON video_source_keywords(job_id)",
]


def apply_v3_migration(conn: sqlite3.Connection) -> None:
    """Called by monitor.storage._migrate when bumping v2 → v3.

    Idempotent (all statements use IF NOT EXISTS).
    """
    for stmt in _DDL_V3_MINING:
        conn.execute(stmt)


def get_conn() -> sqlite3.Connection:
    """Thin alias — mining shares monitor's connection pool."""
    return monitor_storage.get_conn()
```

- [ ] **Step 3: Modify `csm_core/monitor/storage.py` to bump version and call mining migration**

In `csm_core/monitor/storage.py`:

Change line 27 from `_SCHEMA_VERSION = 2` to:
```python
_SCHEMA_VERSION = 3
```

Replace the `_migrate` function (around lines 129-141) with:
```python
def _migrate(conn: sqlite3.Connection) -> None:
    for stmt in _DDL_V1:
        conn.execute(stmt)
    # v2: 加 cooldown_until 给多账号轮换用 (see commit history for full why).
    _ensure_column(conn, "platform_credentials", "cooldown_until", "INTEGER NOT NULL DEFAULT 0")
    # v3: 视频引流抓取 (mining) 三表。Migration lives in csm_core/mining/storage.py
    # to keep mining-specific DDL out of this file. Import is lazy to avoid
    # making mining a hard dep of monitor at import time.
    from csm_core.mining import storage as mining_storage
    mining_storage.apply_v3_migration(conn)
    conn.execute(
        "INSERT OR REPLACE INTO schema_meta(key, value) VALUES('version', ?)",
        (str(_SCHEMA_VERSION),),
    )
```

- [ ] **Step 4: Write a smoke test for schema migration**

Create `sidecar/tests/test_mining_schema.py`:
```python
"""Verify v3 schema migration adds all mining tables on a fresh DB."""
import sqlite3
from pathlib import Path

import pytest

from csm_core.monitor import storage as monitor_storage


@pytest.fixture
def fresh_db(tmp_path: Path, monkeypatch):
    """Reset monitor_storage state and point it at a tmp_path DB."""
    # Reset module-level globals so init_db re-runs.
    monkeypatch.setattr(monitor_storage, "_initialized", False)
    monkeypatch.setattr(monitor_storage, "_db_path", None)
    db = tmp_path / "monitor.db"
    monitor_storage.init_db(db)
    yield db
    monkeypatch.setattr(monitor_storage, "_initialized", False)
    monkeypatch.setattr(monitor_storage, "_db_path", None)


def test_v3_creates_mining_tables(fresh_db: Path):
    conn = sqlite3.connect(str(fresh_db))
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    table_names = {r[0] for r in rows}
    assert "mining_jobs" in table_names
    assert "videos" in table_names
    assert "video_source_keywords" in table_names


def test_v3_videos_has_already_commented_columns(fresh_db: Path):
    conn = sqlite3.connect(str(fresh_db))
    cols = {row[1] for row in conn.execute("PRAGMA table_info(videos)").fetchall()}
    assert {"already_commented", "commented_source", "commented_at"} <= cols


def test_v3_videos_unique_platform_video_id(fresh_db: Path):
    conn = sqlite3.connect(str(fresh_db))
    conn.execute(
        "INSERT INTO videos(platform, platform_video_id, url) VALUES('douyin','x','u')"
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO videos(platform, platform_video_id, url) VALUES('douyin','x','u2')"
        )


def test_v3_schema_version_recorded(fresh_db: Path):
    conn = sqlite3.connect(str(fresh_db))
    row = conn.execute(
        "SELECT value FROM schema_meta WHERE key='version'"
    ).fetchone()
    assert row[0] == "3"
```

- [ ] **Step 5: Run the schema test**

Run: `pytest sidecar/tests/test_mining_schema.py -v`
Expected: 4 tests pass.

- [ ] **Step 6: Run all sidecar tests to confirm no regression**

Run: `pytest sidecar/tests/ -x -q`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add csm_core/mining/__init__.py csm_core/mining/storage.py csm_core/monitor/storage.py sidecar/tests/test_mining_schema.py
git commit -m "feat(mining): schema v3 migration with mining_jobs/videos/video_source_keywords tables"
```

---

### Task 8: Mining pydantic models

**Files:**
- Create: `csm_core/mining/models.py`

- [ ] **Step 1: Write `csm_core/mining/models.py`**

```python
"""Pydantic / dataclass models for the mining module.

VideoCard is the adapter→runner DTO (mutable dataclass — easier to fill in
incrementally as we parse a search result card). MiningJob / Video /
SourceKeyword are pydantic models used at API boundaries.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


Platform = Literal["douyin", "bilibili", "kuaishou"]

MiningStatus = Literal[
    "pending", "running", "done", "partial_done",
    "failed", "cancelled", "interrupted",
]

PlatformPhase = Literal[
    "queued", "launching", "logging_in",
    "scrolling", "done", "failed",
    "needs_login", "risk_control", "cancelled",
]


@dataclass
class VideoCard:
    """One scraped search-result entry, before it lands in SQLite."""
    platform: Platform
    platform_video_id: str
    url: str
    title: str = ""
    author_name: str = ""
    author_id: str = ""
    cover_url: str = ""
    duration_sec: int | None = None
    play_count: int | None = None
    like_count: int | None = None
    published_at: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)
    rank_in_search: int = 0  # 1-based, filled by adapter


@dataclass
class ProgressUpdate:
    platform: Platform
    phase: PlatformPhase
    got: int = 0
    target: int = 0
    note: str = ""


@dataclass
class SearchOutcome:
    platform: Platform
    status: Literal["done", "failed", "needs_login", "risk_control", "cancelled"]
    cards_emitted: int
    error_message: str = ""


class MiningJob(BaseModel):
    id: int | None = None
    keyword: str
    platforms: list[Platform] = Field(default_factory=lambda: ["douyin", "bilibili", "kuaishou"])
    target_per_platform: int = 50
    status: MiningStatus = "pending"
    progress: dict[str, dict[str, Any]] = Field(default_factory=dict)
    error_message: str = ""
    created_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class Video(BaseModel):
    id: int
    platform: Platform
    platform_video_id: str
    url: str
    title: str = ""
    author_name: str = ""
    author_id: str = ""
    cover_url: str = ""
    duration_sec: int | None = None
    play_count: int | None = None
    like_count: int | None = None
    published_at: str | None = None
    excluded: bool = False
    already_commented: bool = False
    commented_source: str | None = None
    commented_at: str | None = None
    first_seen_at: datetime
    source_keywords: list[str] = Field(default_factory=list)  # joined from video_source_keywords


class StartJobRequest(BaseModel):
    keyword: str = Field(min_length=1, max_length=80)
    platforms: list[Platform] = Field(default_factory=lambda: ["douyin", "bilibili", "kuaishou"])
    target_per_platform: int = Field(default=50, ge=10, le=200)
```

- [ ] **Step 2: Smoke-import test**

Add to `sidecar/tests/test_mining_schema.py`:
```python


def test_models_import_and_validate():
    from csm_core.mining.models import StartJobRequest, VideoCard
    req = StartJobRequest(keyword="扫地机器人")
    assert req.target_per_platform == 50
    card = VideoCard(platform="douyin", platform_video_id="x", url="u")
    assert card.rank_in_search == 0
```

- [ ] **Step 3: Run test**

Run: `pytest sidecar/tests/test_mining_schema.py::test_models_import_and_validate -v`
Expected: pass.

- [ ] **Step 4: Commit**

```bash
git add csm_core/mining/models.py sidecar/tests/test_mining_schema.py
git commit -m "feat(mining): pydantic models for job/video/card DTOs"
```

---

### Task 9: Mining storage CRUD — `upsert_video_and_link` + job lifecycle

**Files:**
- Modify: `csm_core/mining/storage.py`

- [ ] **Step 1: Append CRUD functions to `csm_core/mining/storage.py`**

Append the following below the existing content of `csm_core/mining/storage.py`:

```python


# ── Job CRUD ──────────────────────────────────────────────────────────
def create_job(keyword: str, platforms: list[str], target_per_platform: int) -> int:
    conn = get_conn()
    cur = conn.execute(
        """
        INSERT INTO mining_jobs(keyword, platforms_json, target_per_platform, status, progress_json)
        VALUES(?, ?, ?, 'pending', ?)
        RETURNING id
        """,
        (
            keyword,
            json.dumps(platforms, ensure_ascii=False),
            target_per_platform,
            json.dumps({p: {"got": 0, "target": target_per_platform, "phase": "queued"} for p in platforms}, ensure_ascii=False),
        ),
    )
    return int(cur.fetchone()[0])


def mark_started(job_id: int) -> None:
    conn = get_conn()
    conn.execute(
        "UPDATE mining_jobs SET status='running', started_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
        (job_id,),
    )


def update_platform_progress(job_id: int, platform: str, *, got: int, target: int, phase: str, note: str = "") -> None:
    conn = get_conn()
    row = conn.execute("SELECT progress_json FROM mining_jobs WHERE id=?", (job_id,)).fetchone()
    if row is None:
        return
    progress: dict[str, Any] = json.loads(row["progress_json"]) if row["progress_json"] else {}
    progress[platform] = {"got": got, "target": target, "phase": phase, "note": note}
    conn.execute(
        "UPDATE mining_jobs SET progress_json=? WHERE id=?",
        (json.dumps(progress, ensure_ascii=False), job_id),
    )


def finalize_job(job_id: int) -> dict[str, Any]:
    """Compute the overall job status from per-platform phases."""
    conn = get_conn()
    row = conn.execute("SELECT progress_json FROM mining_jobs WHERE id=?", (job_id,)).fetchone()
    if row is None:
        return {}
    progress: dict[str, Any] = json.loads(row["progress_json"]) if row["progress_json"] else {}
    phases = [p["phase"] for p in progress.values()]
    successes = sum(1 for ph in phases if ph == "done")
    failures = len(phases) - successes
    if successes == len(phases) and len(phases) > 0:
        status = "done"
    elif successes == 0:
        status = "failed"
    else:
        status = "partial_done"
    conn.execute(
        "UPDATE mining_jobs SET status=?, finished_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
        (status, job_id),
    )
    return {"status": status, "successes": successes, "failures": failures, "progress": progress}


def cancel_job_if_running(job_id: int) -> bool:
    """Flip status to cancelled only if still running/pending. Caller wakes the runner separately."""
    conn = get_conn()
    cur = conn.execute(
        """
        UPDATE mining_jobs SET status='cancelled', finished_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')
        WHERE id=? AND status IN ('pending', 'running')
        """,
        (job_id,),
    )
    return cur.rowcount > 0


def mark_interrupted_jobs() -> int:
    """At sidecar startup, flip orphaned status=running rows to interrupted."""
    conn = get_conn()
    cur = conn.execute(
        "UPDATE mining_jobs SET status='interrupted', finished_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE status='running'"
    )
    return cur.rowcount


def get_job(job_id: int) -> dict[str, Any] | None:
    conn = get_conn()
    row = conn.execute("SELECT * FROM mining_jobs WHERE id=?", (job_id,)).fetchone()
    return _row_to_job_dict(row) if row else None


def list_jobs(limit: int = 20) -> list[dict[str, Any]]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM mining_jobs ORDER BY created_at DESC LIMIT ?", (limit,)
    ).fetchall()
    return [_row_to_job_dict(r) for r in rows]


def _row_to_job_dict(row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "keyword": row["keyword"],
        "platforms": json.loads(row["platforms_json"]),
        "target_per_platform": row["target_per_platform"],
        "status": row["status"],
        "progress": json.loads(row["progress_json"]) if row["progress_json"] else {},
        "error_message": row["error_message"],
        "created_at": row["created_at"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
    }


# ── Video upsert ──────────────────────────────────────────────────────
def upsert_video_and_link(card, job_id: int) -> int:
    """Insert (or skip duplicate) a video row, run the already_commented
    check on first insert, and always add the source-keyword link.

    Returns the videos.id (existing or freshly inserted).

    Why a single function and not two: the call site (``runner.on_card``)
    needs both writes to happen atomically with respect to the rest of
    the pipeline — if we split, a crash between them could leave a
    video row without its keyword link, which would make the dedup-on-
    rerun behavior silently wrong.
    """
    conn = get_conn()
    # Step 1: try insert; ON CONFLICT keep existing row but return id.
    cur = conn.execute(
        """
        INSERT INTO videos(platform, platform_video_id, url, title, author_name, author_id,
                           cover_url, duration_sec, play_count, like_count, published_at, raw_json)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(platform, platform_video_id) DO NOTHING
        RETURNING id
        """,
        (
            card.platform, card.platform_video_id, card.url, card.title,
            card.author_name, card.author_id, card.cover_url,
            card.duration_sec, card.play_count, card.like_count, card.published_at,
            json.dumps(card.raw, ensure_ascii=False, default=str),
        ),
    )
    row = cur.fetchone()
    is_new = row is not None
    if is_new:
        video_id = int(row[0])
        # Run reverse-lookup ONLY on first insert. Cheap (≤ 1 sqlite query
        # per platform per card) and ensures the already_commented flag
        # is in place before the UI ever sees the row.
        _check_already_commented(conn, video_id, card.platform, card.platform_video_id)
    else:
        # Existing row — fetch its id.
        idrow = conn.execute(
            "SELECT id FROM videos WHERE platform=? AND platform_video_id=?",
            (card.platform, card.platform_video_id),
        ).fetchone()
        video_id = int(idrow["id"])
    # Step 2: link this hit to the keyword + job. Composite PK swallows
    # the "same video, same keyword, same job" case (only happens on
    # retries — rank stays the first rank we observed).
    keyword = _job_keyword(conn, job_id)
    conn.execute(
        """
        INSERT INTO video_source_keywords(video_id, keyword, job_id, rank_in_search)
        VALUES(?,?,?,?)
        ON CONFLICT DO NOTHING
        """,
        (video_id, keyword, job_id, card.rank_in_search),
    )
    return video_id


def _job_keyword(conn, job_id: int) -> str:
    row = conn.execute("SELECT keyword FROM mining_jobs WHERE id=?", (job_id,)).fetchone()
    return row["keyword"] if row else ""


# ── already_commented reverse lookup ──────────────────────────────────
# Each platform's *_comment task targets a video URL; we extract the
# platform_video_id from that URL using the same regex set the monitor
# adapters use. Kept in-module to avoid pulling adapter code into mining.
import re as _re

_VIDEO_ID_PATTERNS: dict[str, list[_re.Pattern[str]]] = {
    "douyin": [
        _re.compile(r"/video/(\d+)"),
        _re.compile(r"/note/(\d+)"),
        _re.compile(r"modal_id=(\d+)"),
        _re.compile(r"aweme_id=(\d+)"),
    ],
    "bilibili": [
        _re.compile(r"/video/(BV[A-Za-z0-9]+)"),
        _re.compile(r"bvid=(BV[A-Za-z0-9]+)"),
        # av-IDs can co-exist; we treat the BV form as the canonical platform_video_id.
        _re.compile(r"/video/av(\d+)"),
    ],
    "kuaishou": [
        _re.compile(r"/short-video/([0-9a-zA-Z]+)"),
        _re.compile(r"photoId=([0-9a-zA-Z]+)"),
        _re.compile(r"/profile/[^/]+/photo/([0-9a-zA-Z]+)"),
    ],
}


def extract_platform_video_id(platform: str, url: str) -> str | None:
    """Public helper, used by adapters AND by the reverse-lookup below."""
    for pat in _VIDEO_ID_PATTERNS.get(platform, []):
        m = pat.search(url or "")
        if m:
            return m.group(1)
    return None


_PLATFORM_TO_MONITOR_TYPE = {
    "douyin": "douyin_comment",
    "bilibili": "bilibili_comment",
    "kuaishou": "kuaishou_comment",
}


def _check_already_commented(conn, video_id: int, platform: str, platform_video_id: str) -> None:
    """Look at monitor_tasks rows for type=<platform>_comment; if any
    target_url resolves to the same platform_video_id, mark the new
    video row already_commented=1.

    Why scan all rows of that type instead of an index lookup: monitor
    target_urls are stored verbatim (short links, modal_id forms, etc.)
    — no normalized column to JOIN on. The rowset is small (the user's
    own comment task list, hundreds at most), so a linear scan with
    regex extraction on each row is fine. If this ever crosses 10k rows
    we can add a generated column ``platform_video_id_norm`` and an
    index; YAGNI for v1.
    """
    monitor_type = _PLATFORM_TO_MONITOR_TYPE.get(platform)
    if monitor_type is None:
        return
    rows = conn.execute(
        "SELECT id, target_url, last_check_at FROM monitor_tasks WHERE type=?",
        (monitor_type,),
    ).fetchall()
    for r in rows:
        pid = extract_platform_video_id(platform, r["target_url"])
        if pid == platform_video_id:
            conn.execute(
                """
                UPDATE videos SET already_commented=1,
                                  commented_source='monitor_task',
                                  commented_at=?
                WHERE id=?
                """,
                (r["last_check_at"], video_id),
            )
            return


# ── Video reads ───────────────────────────────────────────────────────
def list_videos(
    *,
    keyword: str | None = None,
    platform: str | None = None,
    commented: str = "0",   # "0" | "1" | "all"
    q: str | None = None,
    job_id: int | None = None,
    offset: int = 0,
    limit: int = 50,
) -> tuple[list[dict[str, Any]], int]:
    """Returns (rows, total). Each row is a dict with source_keywords aggregated."""
    conn = get_conn()
    where = ["v.excluded=0"]
    args: list[Any] = []
    if platform:
        where.append("v.platform=?")
        args.append(platform)
    if commented == "0":
        where.append("v.already_commented=0")
    elif commented == "1":
        where.append("v.already_commented=1")
    # "all" → no filter
    if keyword:
        where.append(
            "EXISTS (SELECT 1 FROM video_source_keywords vsk "
            "WHERE vsk.video_id=v.id AND vsk.keyword=?)"
        )
        args.append(keyword)
    if job_id is not None:
        where.append(
            "EXISTS (SELECT 1 FROM video_source_keywords vsk "
            "WHERE vsk.video_id=v.id AND vsk.job_id=?)"
        )
        args.append(job_id)
    if q:
        where.append("(v.title LIKE ? OR v.author_name LIKE ?)")
        args.extend([f"%{q}%", f"%{q}%"])

    where_sql = " AND ".join(where)
    total = int(conn.execute(
        f"SELECT COUNT(*) FROM videos v WHERE {where_sql}", args,
    ).fetchone()[0])
    rows = conn.execute(
        f"""
        SELECT v.*, GROUP_CONCAT(DISTINCT vsk.keyword) AS source_keywords
        FROM videos v
        LEFT JOIN video_source_keywords vsk ON vsk.video_id = v.id
        WHERE {where_sql}
        GROUP BY v.id
        ORDER BY v.first_seen_at DESC
        LIMIT ? OFFSET ?
        """,
        args + [limit, offset],
    ).fetchall()
    return [_row_to_video_dict(r) for r in rows], total


def _row_to_video_dict(row) -> dict[str, Any]:
    keys_csv = row["source_keywords"] or ""
    return {
        "id": row["id"],
        "platform": row["platform"],
        "platform_video_id": row["platform_video_id"],
        "url": row["url"],
        "title": row["title"],
        "author_name": row["author_name"],
        "author_id": row["author_id"],
        "cover_url": row["cover_url"],
        "duration_sec": row["duration_sec"],
        "play_count": row["play_count"],
        "like_count": row["like_count"],
        "published_at": row["published_at"],
        "excluded": bool(row["excluded"]),
        "already_commented": bool(row["already_commented"]),
        "commented_source": row["commented_source"],
        "commented_at": row["commented_at"],
        "first_seen_at": row["first_seen_at"],
        "source_keywords": [k for k in keys_csv.split(",") if k],
    }


def soft_delete_video(video_id: int) -> bool:
    conn = get_conn()
    cur = conn.execute("UPDATE videos SET excluded=1 WHERE id=?", (video_id,))
    return cur.rowcount > 0
```

- [ ] **Step 2: Write CRUD tests**

Create `sidecar/tests/test_mining_storage.py`:
```python
"""Direct unit tests for csm_core/mining/storage.py."""
from pathlib import Path

import pytest

from csm_core.mining import storage as ms
from csm_core.mining.models import VideoCard
from csm_core.monitor import storage as monitor_storage


@pytest.fixture
def db(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(monitor_storage, "_initialized", False)
    monkeypatch.setattr(monitor_storage, "_db_path", None)
    if hasattr(monitor_storage._local, "conn"):
        delattr(monitor_storage._local, "conn")
    monitor_storage.init_db(tmp_path / "monitor.db")
    yield
    monkeypatch.setattr(monitor_storage, "_initialized", False)
    monkeypatch.setattr(monitor_storage, "_db_path", None)


def _make_card(rank: int = 1, *, platform="douyin", vid="111") -> VideoCard:
    return VideoCard(
        platform=platform,
        platform_video_id=vid,
        url=f"https://example.com/video/{vid}",
        title=f"video {vid}",
        author_name="作者A",
        cover_url="http://x/cover.jpg",
        like_count=10,
        rank_in_search=rank,
    )


def test_create_job_returns_id(db):
    jid = ms.create_job("扫地机器人", ["douyin", "bilibili"], 50)
    assert jid > 0
    job = ms.get_job(jid)
    assert job["keyword"] == "扫地机器人"
    assert job["platforms"] == ["douyin", "bilibili"]
    assert job["status"] == "pending"


def test_upsert_video_inserts_and_links(db):
    jid = ms.create_job("k1", ["douyin"], 50)
    vid_id = ms.upsert_video_and_link(_make_card(rank=3), jid)
    assert vid_id > 0
    rows, total = ms.list_videos(commented="all")
    assert total == 1
    assert rows[0]["source_keywords"] == ["k1"]


def test_upsert_video_dedups_on_second_call(db):
    j1 = ms.create_job("k1", ["douyin"], 50)
    j2 = ms.create_job("k2", ["douyin"], 50)
    id1 = ms.upsert_video_and_link(_make_card(), j1)
    id2 = ms.upsert_video_and_link(_make_card(), j2)
    assert id1 == id2  # same row
    rows, total = ms.list_videos(commented="all")
    assert total == 1  # single videos row
    assert set(rows[0]["source_keywords"]) == {"k1", "k2"}  # both keywords attached


def test_already_commented_marks_when_monitor_task_exists(db):
    # Pre-insert a monitor_task pointing at the same video.
    conn = monitor_storage.get_conn()
    conn.execute(
        """
        INSERT INTO monitor_tasks(type, name, target_url, config_json, schedule_cron, last_check_at)
        VALUES('douyin_comment', 'my_comment', 'https://www.douyin.com/video/111', '{}', 'manual', '2026-05-10T00:00:00Z')
        """
    )
    jid = ms.create_job("k1", ["douyin"], 50)
    vid_id = ms.upsert_video_and_link(_make_card(vid="111"), jid)
    rows, _ = ms.list_videos(commented="1")
    assert len(rows) == 1
    assert rows[0]["id"] == vid_id
    assert rows[0]["already_commented"] is True
    assert rows[0]["commented_source"] == "monitor_task"


def test_already_commented_does_not_mark_unrelated(db):
    conn = monitor_storage.get_conn()
    conn.execute(
        """
        INSERT INTO monitor_tasks(type, name, target_url, config_json, schedule_cron)
        VALUES('douyin_comment', 'other', 'https://www.douyin.com/video/999', '{}', 'manual')
        """
    )
    jid = ms.create_job("k1", ["douyin"], 50)
    ms.upsert_video_and_link(_make_card(vid="111"), jid)
    rows, _ = ms.list_videos(commented="0")
    assert len(rows) == 1
    assert rows[0]["already_commented"] is False


def test_already_commented_uses_short_url_pattern(db):
    """modal_id form must also match the same platform_video_id."""
    conn = monitor_storage.get_conn()
    conn.execute(
        """
        INSERT INTO monitor_tasks(type, name, target_url, config_json, schedule_cron)
        VALUES('douyin_comment', 'modal', 'https://www.douyin.com/discover?modal_id=111', '{}', 'manual')
        """
    )
    jid = ms.create_job("k1", ["douyin"], 50)
    ms.upsert_video_and_link(_make_card(vid="111"), jid)
    rows, _ = ms.list_videos(commented="1")
    assert len(rows) == 1


def test_list_videos_filter_by_commented(db):
    conn = monitor_storage.get_conn()
    conn.execute(
        "INSERT INTO monitor_tasks(type, name, target_url, config_json, schedule_cron) "
        "VALUES('douyin_comment','m','https://www.douyin.com/video/111','{}','manual')"
    )
    jid = ms.create_job("k", ["douyin"], 50)
    ms.upsert_video_and_link(_make_card(vid="111"), jid)
    ms.upsert_video_and_link(_make_card(vid="222"), jid)
    uncommented, _ = ms.list_videos(commented="0")
    commented, _ = ms.list_videos(commented="1")
    all_videos, _ = ms.list_videos(commented="all")
    assert len(uncommented) == 1
    assert len(commented) == 1
    assert len(all_videos) == 2


def test_soft_delete_excludes_from_list(db):
    jid = ms.create_job("k", ["douyin"], 50)
    vid_id = ms.upsert_video_and_link(_make_card(), jid)
    assert ms.soft_delete_video(vid_id) is True
    rows, total = ms.list_videos(commented="all")
    assert total == 0


def test_finalize_job_done_when_all_platforms_done(db):
    jid = ms.create_job("k", ["douyin", "bilibili"], 50)
    ms.update_platform_progress(jid, "douyin", got=50, target=50, phase="done")
    ms.update_platform_progress(jid, "bilibili", got=50, target=50, phase="done")
    summary = ms.finalize_job(jid)
    assert summary["status"] == "done"


def test_finalize_job_partial_when_mixed(db):
    jid = ms.create_job("k", ["douyin", "bilibili"], 50)
    ms.update_platform_progress(jid, "douyin", got=0, target=50, phase="needs_login")
    ms.update_platform_progress(jid, "bilibili", got=50, target=50, phase="done")
    summary = ms.finalize_job(jid)
    assert summary["status"] == "partial_done"


def test_cancel_running_job_flips_status(db):
    jid = ms.create_job("k", ["douyin"], 50)
    ms.mark_started(jid)
    assert ms.cancel_job_if_running(jid) is True
    assert ms.get_job(jid)["status"] == "cancelled"


def test_extract_platform_video_id_handles_short_forms():
    assert ms.extract_platform_video_id("douyin", "https://www.douyin.com/video/7123") == "7123"
    assert ms.extract_platform_video_id("douyin", "https://www.douyin.com/?modal_id=7123") == "7123"
    assert ms.extract_platform_video_id("bilibili", "https://b23.tv/video/BV1ab2cd3ef4") == "BV1ab2cd3ef4"
    assert ms.extract_platform_video_id("kuaishou", "https://www.kuaishou.com/short-video/aZ9Q1xY") == "aZ9Q1xY"
    assert ms.extract_platform_video_id("douyin", "https://example.com") is None
```

- [ ] **Step 3: Run tests**

Run: `pytest sidecar/tests/test_mining_storage.py -v`
Expected: 12 tests pass.

- [ ] **Step 4: Commit**

```bash
git add csm_core/mining/storage.py sidecar/tests/test_mining_storage.py
git commit -m "feat(mining): storage CRUD + already_commented reverse-lookup"
```

---

## Phase 3 — Mining backend (browser launcher + adapters + runner + routes)

### Task 10: Persistent-profile browser launcher

**Files:**
- Create: `csm_core/browser_infra/mining_browser.py`

The existing `patchright_pool` uses tempfile per launch (correct for monitor's many-short-tasks pattern). Mining needs a **stable** profile per platform so cookies persist across launches. New file is purpose-built for this.

- [ ] **Step 1: Write `csm_core/browser_infra/mining_browser.py`**

```python
"""Persistent-profile Patchright launcher for the mining module.

Differs from ``patchright_pool``:

- One profile **per platform**, stable across launches → cookies survive.
- Caller drives the lifecycle (open → search → close); no thread-local
  caching, no idle reaper. Mining tasks are 5-10 min batches, not
  many-shot tasks like monitor, so the pool model doesn't help.
- Headed by default — see spec section 2 (browser mode lock).

Shares two helpers with ``patchright_pool``: ``ensure_browsers_path()``
and ``_kill_process_tree()``. We import them by string to avoid coupling
mining to monitor's pool wholesale.
"""
from __future__ import annotations

import contextlib
import logging
import threading
import time
from pathlib import Path
from typing import Any, Iterator

from csm_core.browser_infra.patchright_pool import (
    ensure_browsers_path,
    _kill_process_tree,
)

logger = logging.getLogger(__name__)


_PROFILE_ROOT_DEFAULT = "browser_profiles"
_profile_root: Path | None = None


def configure_profile_root(path: Path) -> None:
    """Tell the launcher where to put per-platform user_data_dirs.

    Typically called once at sidecar startup with ``<config_dir>/browser_profiles``.
    """
    global _profile_root
    _profile_root = Path(path)
    _profile_root.mkdir(parents=True, exist_ok=True)


def _profile_dir_for(platform: str) -> Path:
    if _profile_root is None:
        raise RuntimeError(
            "mining_browser profile root not configured — call configure_profile_root(...) first"
        )
    p = _profile_root / platform
    p.mkdir(parents=True, exist_ok=True)
    return p


@contextlib.contextmanager
def launched_page(platform: str, *, headless: bool = False) -> Iterator[Any]:
    """Context-managed Patchright Page for one mining batch.

    On exit: OS-kills the Chromium tree (cross-thread-safe path, same
    technique as patchright_pool's reaper). Profile cookies are persisted
    by Chromium before the kill cascade because launch_persistent_context
    flushes on context.close() — but cross-thread close raises, so we
    do a best-effort close-then-kill: graceful close runs on the owning
    thread, then we kill to guarantee teardown.
    """
    try:
        from patchright.sync_api import sync_playwright
    except ImportError as e:
        raise RuntimeError(
            "patchright not installed; run `pip install patchright` and "
            "`patchright install chromium`"
        ) from e

    ensure_browsers_path()
    user_data_dir = str(_profile_dir_for(platform))

    pw = sync_playwright().start()
    node_pid = 0
    try:
        try:
            node_pid = pw._impl_obj._connection._transport._proc.pid
        except Exception:
            logger.warning(
                "mining_browser[%s]: cannot read node pid — graceful kill only", platform
            )

        launch_args = [
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--window-size=1000,700",
        ]
        context = pw.chromium.launch_persistent_context(
            user_data_dir=user_data_dir,
            headless=headless,
            args=launch_args,
            viewport={"width": 1000, "height": 700},
        )
        pages = context.pages
        page = pages[0] if pages else context.new_page()
        logger.info(
            "mining_browser[%s] launched (profile=%s, node_pid=%d)",
            platform, user_data_dir, node_pid,
        )
        try:
            yield page
        finally:
            try:
                context.close()
            except Exception as e:
                logger.debug("mining_browser[%s] context.close raised: %s", platform, e)
    finally:
        try:
            pw.stop()
        except Exception as e:
            logger.debug("mining_browser[%s] pw.stop raised: %s", platform, e)
        if node_pid:
            _kill_process_tree(node_pid, label=f"mining-browser[{platform}]")


def has_login_cookie(platform: str) -> bool:
    """Best-effort: does the persistent profile have a key login cookie?

    Reads the SQLite cookie store directly because spinning a Chromium
    just to check this would be wasteful. The file may not exist yet
    (fresh profile) or may be locked (browser running) — both → False.
    """
    profile = _profile_dir_for(platform)
    cookies_db = profile / "Default" / "Cookies"
    if not cookies_db.exists():
        return False
    key_cookie = {
        "douyin": "sessionid",
        "bilibili": "SESSDATA",
        "kuaishou": "kuaishou.web.cp.api_st",
    }.get(platform)
    if not key_cookie:
        return False
    try:
        import sqlite3
        conn = sqlite3.connect(f"file:{cookies_db}?mode=ro", uri=True, timeout=0.2)
        try:
            row = conn.execute(
                "SELECT 1 FROM cookies WHERE name=? LIMIT 1", (key_cookie,)
            ).fetchone()
            return row is not None
        finally:
            conn.close()
    except sqlite3.OperationalError:
        # locked = Chromium running with this profile → assume valid
        return True
    except Exception as e:
        logger.debug("has_login_cookie[%s] read failed: %s", platform, e)
        return False
```

- [ ] **Step 2: Smoke test (import only — no live browser launch in CI)**

Add to `sidecar/tests/test_mining_storage.py`:
```python


def test_mining_browser_import_only():
    from csm_core.browser_infra import mining_browser
    assert callable(mining_browser.launched_page)
    assert callable(mining_browser.has_login_cookie)
```

- [ ] **Step 3: Run test**

Run: `pytest sidecar/tests/test_mining_storage.py::test_mining_browser_import_only -v`
Expected: pass.

- [ ] **Step 4: Commit**

```bash
git add csm_core/browser_infra/mining_browser.py sidecar/tests/test_mining_storage.py
git commit -m "feat(browser-infra): persistent-profile launcher for mining"
```

---

### Task 11: Adapter Protocol + base helpers

**Files:**
- Create: `csm_core/mining/platforms/__init__.py`
- Create: `csm_core/mining/platforms/_common.py`

- [ ] **Step 1: Write `__init__.py`**

```python
"""Search adapters for each video platform."""
```

- [ ] **Step 2: Write `_common.py`**

```python
"""Shared Protocol, helpers, and exceptions for mining platform adapters."""
from __future__ import annotations

import logging
import threading
from typing import Callable, Protocol

from csm_core.mining.models import (
    Platform, ProgressUpdate, SearchOutcome, VideoCard,
)

logger = logging.getLogger(__name__)


class RiskControlError(Exception):
    """Adapter saw a captcha/login wall mid-scrape."""


class NeedsLoginError(Exception):
    """Adapter found no valid login cookie at launch."""


OnCard = Callable[[VideoCard], None]
OnProgress = Callable[[ProgressUpdate], None]


class SearchAdapter(Protocol):
    """Each platform adapter implements this."""
    platform: Platform

    def search(
        self,
        keyword: str,
        target_count: int,
        on_card: OnCard,
        on_progress: OnProgress,
        cancel_event: threading.Event,
    ) -> SearchOutcome: ...


def parse_int_count(text: str) -> int | None:
    """Parse '1.2万' / '3.4k' / '5,678' / '' into int. Returns None on empty/invalid."""
    if not text:
        return None
    t = text.strip().replace(",", "").replace(" ", "")
    if not t:
        return None
    try:
        if t.endswith(("万", "w", "W")):
            return int(float(t[:-1]) * 10_000)
        if t.endswith(("亿",)):
            return int(float(t[:-1]) * 100_000_000)
        if t.endswith(("k", "K")):
            return int(float(t[:-1]) * 1_000)
        if t.endswith(("m", "M")):
            return int(float(t[:-1]) * 1_000_000)
        return int(float(t))
    except (ValueError, TypeError):
        return None


def parse_duration(text: str) -> int | None:
    """Parse '1:23' / '01:02:03' into seconds. Returns None on parse failure."""
    if not text:
        return None
    parts = text.strip().split(":")
    try:
        nums = [int(p) for p in parts]
    except ValueError:
        return None
    if len(nums) == 2:
        return nums[0] * 60 + nums[1]
    if len(nums) == 3:
        return nums[0] * 3600 + nums[1] * 60 + nums[2]
    return None
```

- [ ] **Step 3: Test the helpers**

Create `sidecar/tests/test_mining_adapter_helpers.py`:
```python
from csm_core.mining.platforms._common import parse_int_count, parse_duration


def test_parse_int_count_chinese_wan():
    assert parse_int_count("1.2万") == 12_000
    assert parse_int_count("12万") == 120_000


def test_parse_int_count_yi():
    assert parse_int_count("1.5亿") == 150_000_000


def test_parse_int_count_english_k():
    assert parse_int_count("3.4k") == 3_400
    assert parse_int_count("2M") == 2_000_000


def test_parse_int_count_commas():
    assert parse_int_count("12,345") == 12_345


def test_parse_int_count_empty_and_garbage():
    assert parse_int_count("") is None
    assert parse_int_count("--") is None
    assert parse_int_count(None) is None  # type: ignore[arg-type]


def test_parse_duration_mmss():
    assert parse_duration("1:23") == 83


def test_parse_duration_hhmmss():
    assert parse_duration("01:02:03") == 3723


def test_parse_duration_empty():
    assert parse_duration("") is None
    assert parse_duration("abc") is None
```

- [ ] **Step 4: Run tests**

Run: `pytest sidecar/tests/test_mining_adapter_helpers.py -v`
Expected: 8 tests pass.

- [ ] **Step 5: Commit**

```bash
git add csm_core/mining/platforms/__init__.py csm_core/mining/platforms/_common.py sidecar/tests/test_mining_adapter_helpers.py
git commit -m "feat(mining): adapter Protocol + count/duration parse helpers"
```

---

### Task 12: B 站 search adapter

B 站 is implemented first because it's the most reliable platform and gives the runner a working end-to-end before we tackle the harder ones. The adapter intercepts the `/x/web-interface/wbi/search/type` XHR response (richer than DOM scraping) and only falls back to DOM if the XHR shape changes.

**Files:**
- Create: `csm_core/mining/platforms/bilibili_search.py`
- Create: `sidecar/tests/fixtures/mining/bilibili/search_response.json`
- Create: `sidecar/tests/test_mining_extract_bilibili.py`

- [ ] **Step 1: Capture a fixture from a real search**

Save a JSON sample (you can capture this live during dev, or use the synthetic one below for the initial commit) to `sidecar/tests/fixtures/mining/bilibili/search_response.json`:
```json
{
  "code": 0,
  "data": {
    "result": [
      {
        "type": "video",
        "bvid": "BV1abc23defg",
        "aid": 1234567890,
        "title": "扫地机器人选购指南",
        "author": "测评UP主",
        "mid": 88888888,
        "pic": "//i0.hdslb.com/bfs/archive/abc.jpg",
        "duration": "10:23",
        "play": 12345,
        "like": 678,
        "pubdate": 1715000000,
        "description": "本期测评 ..."
      },
      {
        "type": "video",
        "bvid": "BV2bcd34efgh",
        "aid": 1234567891,
        "title": "扫地机器人对比",
        "author": "家电小白",
        "mid": 77777777,
        "pic": "//i0.hdslb.com/bfs/archive/def.jpg",
        "duration": "5:01",
        "play": 50000,
        "like": 1200,
        "pubdate": 1715100000,
        "description": "..."
      }
    ]
  }
}
```

- [ ] **Step 2: Write the adapter**

`csm_core/mining/platforms/bilibili_search.py`:
```python
"""B 站 search adapter — intercepts the wbi search XHR, falls back to DOM.

Why XHR-first: B 站's React app renders cards lazily, and DOM selectors
break every ~6 months when the search page is rebuilt. The
``/x/web-interface/wbi/search/type`` response is a stable contract — we
just route it from the browser into our card stream.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any
from urllib.parse import quote

from csm_core.browser_infra import mining_browser
from csm_core.mining.models import (
    Platform, ProgressUpdate, SearchOutcome, VideoCard,
)
from csm_core.mining.platforms._common import (
    NeedsLoginError, OnCard, OnProgress, parse_duration, parse_int_count,
)

logger = logging.getLogger(__name__)


class BilibiliSearchAdapter:
    platform: Platform = "bilibili"

    def search(
        self,
        keyword: str,
        target_count: int,
        on_card: OnCard,
        on_progress: OnProgress,
        cancel_event: threading.Event,
    ) -> SearchOutcome:
        if not mining_browser.has_login_cookie("bilibili"):
            on_progress(ProgressUpdate(platform=self.platform, phase="needs_login", got=0, target=target_count))
            return SearchOutcome(platform=self.platform, status="needs_login", cards_emitted=0,
                                 error_message="no SESSDATA in profile")

        on_progress(ProgressUpdate(platform=self.platform, phase="launching", got=0, target=target_count))
        emitted = 0
        seen_bvids: set[str] = set()

        with mining_browser.launched_page("bilibili") as page:
            on_progress(ProgressUpdate(platform=self.platform, phase="scrolling", got=0, target=target_count))

            def _handle_response(response: Any) -> None:
                nonlocal emitted
                if cancel_event.is_set():
                    return
                if "/web-interface/wbi/search/type" not in response.url and \
                   "/web-interface/search/type" not in response.url:
                    return
                try:
                    body = response.json()
                except Exception:
                    return
                cards = self._extract_cards(body)
                for c in cards:
                    if cancel_event.is_set() or emitted >= target_count:
                        return
                    if c.platform_video_id in seen_bvids:
                        continue
                    seen_bvids.add(c.platform_video_id)
                    emitted += 1
                    c.rank_in_search = emitted
                    on_card(c)
                on_progress(ProgressUpdate(
                    platform=self.platform, phase="scrolling",
                    got=emitted, target=target_count,
                ))

            page.on("response", _handle_response)
            url = f"https://search.bilibili.com/all?keyword={quote(keyword)}"
            page.goto(url, wait_until="domcontentloaded", timeout=30_000)

            # Paginate by clicking "下一页" or by URL ?page=N — URL is more reliable.
            for page_num in range(1, 11):  # cap at 10 pages = ~200 results
                if cancel_event.is_set() or emitted >= target_count:
                    break
                page.goto(
                    f"{url}&page={page_num}",
                    wait_until="domcontentloaded",
                    timeout=30_000,
                )
                # Give the XHR a chance to fire before the next page.
                for _ in range(20):
                    if cancel_event.is_set() or emitted >= target_count:
                        break
                    time.sleep(0.5)
                    if emitted >= target_count:
                        break

        if cancel_event.is_set():
            return SearchOutcome(platform=self.platform, status="cancelled", cards_emitted=emitted)
        on_progress(ProgressUpdate(platform=self.platform, phase="done", got=emitted, target=target_count))
        return SearchOutcome(platform=self.platform, status="done", cards_emitted=emitted)

    def _extract_cards(self, body: dict[str, Any]) -> list[VideoCard]:
        """Parse a single wbi search response into VideoCards."""
        if not isinstance(body, dict):
            return []
        if body.get("code") != 0:
            return []
        result = body.get("data", {}).get("result", [])
        cards: list[VideoCard] = []
        for item in result:
            if not isinstance(item, dict) or item.get("type") != "video":
                continue
            bvid = item.get("bvid")
            if not bvid:
                continue
            cards.append(VideoCard(
                platform="bilibili",
                platform_video_id=bvid,
                url=f"https://www.bilibili.com/video/{bvid}",
                title=_strip_em(item.get("title", "")),
                author_name=item.get("author", ""),
                author_id=str(item.get("mid", "")) or "",
                cover_url=_normalize_url(item.get("pic", "")),
                duration_sec=parse_duration(item.get("duration", "")),
                play_count=item.get("play") if isinstance(item.get("play"), int) else parse_int_count(str(item.get("play", ""))),
                like_count=item.get("like") if isinstance(item.get("like"), int) else parse_int_count(str(item.get("like", ""))),
                published_at=_pubdate_to_iso(item.get("pubdate")),
                raw=item,
            ))
        return cards


def _strip_em(text: str) -> str:
    """Search API wraps keyword hits in <em class="keyword">…</em>. Strip."""
    if not text:
        return ""
    # Cheap regex strip — no DOM parser needed.
    import re
    return re.sub(r"</?em[^>]*>", "", text)


def _normalize_url(u: str) -> str:
    if u.startswith("//"):
        return "https:" + u
    return u or ""


def _pubdate_to_iso(ts) -> str | None:
    if not isinstance(ts, (int, float)):
        return None
    try:
        from datetime import datetime, timezone
        return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return None
```

- [ ] **Step 3: Write extraction-only test (no live browser)**

Create `sidecar/tests/test_mining_extract_bilibili.py`:
```python
import json
from pathlib import Path

from csm_core.mining.platforms.bilibili_search import BilibiliSearchAdapter


FIXTURE = Path(__file__).parent / "fixtures" / "mining" / "bilibili" / "search_response.json"


def test_extract_cards_basic():
    adapter = BilibiliSearchAdapter()
    body = json.loads(FIXTURE.read_text(encoding="utf-8"))
    cards = adapter._extract_cards(body)
    assert len(cards) == 2
    c1 = cards[0]
    assert c1.platform == "bilibili"
    assert c1.platform_video_id == "BV1abc23defg"
    assert c1.url == "https://www.bilibili.com/video/BV1abc23defg"
    assert c1.title == "扫地机器人选购指南"
    assert c1.author_name == "测评UP主"
    assert c1.author_id == "88888888"
    assert c1.duration_sec == 623   # 10:23
    assert c1.play_count == 12345
    assert c1.cover_url.startswith("https://")


def test_extract_handles_em_tags():
    adapter = BilibiliSearchAdapter()
    cards = adapter._extract_cards({
        "code": 0,
        "data": {"result": [{
            "type": "video", "bvid": "BVa", "title": "<em class=\"keyword\">扫地</em>机器人",
            "author": "x", "mid": 1, "pic": "//x", "duration": "0:30",
            "play": 1, "like": 1, "pubdate": 0,
        }]},
    })
    assert cards[0].title == "扫地机器人"


def test_extract_skips_non_video_results():
    adapter = BilibiliSearchAdapter()
    cards = adapter._extract_cards({
        "code": 0,
        "data": {"result": [
            {"type": "bili_user", "mid": 1},
            {"type": "video", "bvid": "BVa", "title": "x", "author": "a", "mid": 1,
             "pic": "//x", "duration": "0:10", "play": 1, "like": 1, "pubdate": 0},
        ]},
    })
    assert len(cards) == 1
    assert cards[0].platform_video_id == "BVa"


def test_extract_returns_empty_on_error_code():
    adapter = BilibiliSearchAdapter()
    cards = adapter._extract_cards({"code": -101, "data": None})
    assert cards == []
```

- [ ] **Step 4: Run extraction tests**

Run: `pytest sidecar/tests/test_mining_extract_bilibili.py -v`
Expected: 4 tests pass.

- [ ] **Step 5: Commit**

```bash
git add csm_core/mining/platforms/bilibili_search.py sidecar/tests/fixtures/mining/bilibili/search_response.json sidecar/tests/test_mining_extract_bilibili.py
git commit -m "feat(mining): B站 search adapter — XHR intercept + extraction"
```

---

### Task 13: 快手 search adapter

Kuaishou web search renders cards in the DOM and via XHR; we extract from DOM because the XHR endpoint requires a fresh client signature on every call.

**Files:**
- Create: `csm_core/mining/platforms/kuaishou_search.py`
- Create: `sidecar/tests/fixtures/mining/kuaishou/search_dom.html`
- Create: `sidecar/tests/test_mining_extract_kuaishou.py`

- [ ] **Step 1: Save a fixture DOM**

Save to `sidecar/tests/fixtures/mining/kuaishou/search_dom.html`:
```html
<!DOCTYPE html>
<html><body>
<div class="search-result-content">
  <a class="search-result-item" href="/short-video/3xabc123" data-photo-id="3xabc123">
    <img class="photo-cover" src="https://cover.kuaishou.com/aaa.jpg" />
    <div class="photo-title">扫地机器人 推荐</div>
    <div class="author-name">家电达人</div>
    <div class="photo-play-count">12.3万</div>
    <div class="photo-like-count">3,456</div>
    <div class="photo-duration">1:23</div>
  </a>
  <a class="search-result-item" href="/short-video/3xdef456" data-photo-id="3xdef456">
    <img class="photo-cover" src="https://cover.kuaishou.com/bbb.jpg" />
    <div class="photo-title">扫地机器人 测评</div>
    <div class="author-name">小李</div>
    <div class="photo-play-count">5000</div>
    <div class="photo-like-count">200</div>
    <div class="photo-duration">0:45</div>
  </a>
</div>
</body></html>
```

- [ ] **Step 2: Write the adapter**

`csm_core/mining/platforms/kuaishou_search.py`:
```python
"""快手 search adapter — DOM scrape with infinite scroll."""
from __future__ import annotations

import logging
import threading
import time
from typing import Any
from urllib.parse import quote

from csm_core.browser_infra import mining_browser
from csm_core.mining.models import (
    Platform, ProgressUpdate, SearchOutcome, VideoCard,
)
from csm_core.mining.platforms._common import (
    OnCard, OnProgress, RiskControlError,
    parse_duration, parse_int_count,
)

logger = logging.getLogger(__name__)


class KuaishouSearchAdapter:
    platform: Platform = "kuaishou"

    def search(
        self,
        keyword: str,
        target_count: int,
        on_card: OnCard,
        on_progress: OnProgress,
        cancel_event: threading.Event,
    ) -> SearchOutcome:
        if not mining_browser.has_login_cookie("kuaishou"):
            on_progress(ProgressUpdate(platform=self.platform, phase="needs_login", got=0, target=target_count))
            return SearchOutcome(platform=self.platform, status="needs_login", cards_emitted=0)

        on_progress(ProgressUpdate(platform=self.platform, phase="launching", got=0, target=target_count))
        emitted = 0
        seen: set[str] = set()

        with mining_browser.launched_page("kuaishou") as page:
            url = f"https://www.kuaishou.com/search/video?searchKey={quote(keyword)}"
            page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            on_progress(ProgressUpdate(platform=self.platform, phase="scrolling", got=0, target=target_count))

            stagnant_scrolls = 0
            for _ in range(50):  # safety cap on scrolls
                if cancel_event.is_set() or emitted >= target_count:
                    break

                if _looks_like_captcha(page):
                    return SearchOutcome(
                        platform=self.platform, status="risk_control",
                        cards_emitted=emitted, error_message="captcha intercepted",
                    )

                html = page.content()
                new_cards = self._extract_from_dom(html, exclude_ids=seen)
                if new_cards:
                    stagnant_scrolls = 0
                    for c in new_cards:
                        if emitted >= target_count:
                            break
                        seen.add(c.platform_video_id)
                        emitted += 1
                        c.rank_in_search = emitted
                        on_card(c)
                    on_progress(ProgressUpdate(
                        platform=self.platform, phase="scrolling",
                        got=emitted, target=target_count,
                    ))
                else:
                    stagnant_scrolls += 1
                    if stagnant_scrolls >= 3:
                        break  # end of results

                page.evaluate("window.scrollBy(0, window.innerHeight * 2)")
                time.sleep(1.5)

        if cancel_event.is_set():
            return SearchOutcome(platform=self.platform, status="cancelled", cards_emitted=emitted)
        on_progress(ProgressUpdate(platform=self.platform, phase="done", got=emitted, target=target_count))
        return SearchOutcome(platform=self.platform, status="done", cards_emitted=emitted)

    def _extract_from_dom(self, html: str, *, exclude_ids: set[str]) -> list[VideoCard]:
        """Parse Kuaishou search DOM into cards. Uses lxml for speed."""
        try:
            from lxml import html as lxml_html
        except ImportError:
            # Fallback to BeautifulSoup if lxml missing — slower but tolerable.
            return self._extract_via_bs4(html, exclude_ids)

        tree = lxml_html.fromstring(html)
        cards: list[VideoCard] = []
        for item in tree.cssselect("a.search-result-item"):
            pid = item.get("data-photo-id") or _href_to_photo_id(item.get("href", ""))
            if not pid or pid in exclude_ids:
                continue
            title = _first_text(item.cssselect(".photo-title"))
            author = _first_text(item.cssselect(".author-name"))
            play_txt = _first_text(item.cssselect(".photo-play-count"))
            like_txt = _first_text(item.cssselect(".photo-like-count"))
            dur_txt = _first_text(item.cssselect(".photo-duration"))
            cover = _first_attr(item.cssselect("img.photo-cover"), "src")
            cards.append(VideoCard(
                platform="kuaishou",
                platform_video_id=pid,
                url=f"https://www.kuaishou.com/short-video/{pid}",
                title=title,
                author_name=author,
                cover_url=cover,
                duration_sec=parse_duration(dur_txt),
                play_count=parse_int_count(play_txt),
                like_count=parse_int_count(like_txt),
                raw={"title": title, "author": author, "play_txt": play_txt, "like_txt": like_txt},
            ))
        return cards

    def _extract_via_bs4(self, html: str, exclude_ids: set[str]) -> list[VideoCard]:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        cards: list[VideoCard] = []
        for item in soup.select("a.search-result-item"):
            pid = item.get("data-photo-id") or _href_to_photo_id(item.get("href", ""))
            if not pid or pid in exclude_ids:
                continue
            def _t(sel: str) -> str:
                el = item.select_one(sel)
                return (el.get_text(strip=True) if el else "")
            def _attr(sel: str, key: str) -> str:
                el = item.select_one(sel)
                return (el.get(key, "") if el else "")
            cards.append(VideoCard(
                platform="kuaishou",
                platform_video_id=pid,
                url=f"https://www.kuaishou.com/short-video/{pid}",
                title=_t(".photo-title"),
                author_name=_t(".author-name"),
                cover_url=_attr("img.photo-cover", "src"),
                duration_sec=parse_duration(_t(".photo-duration")),
                play_count=parse_int_count(_t(".photo-play-count")),
                like_count=parse_int_count(_t(".photo-like-count")),
                raw={},
            ))
        return cards


def _first_text(els: list[Any]) -> str:
    if not els:
        return ""
    return (els[0].text_content() or "").strip()


def _first_attr(els: list[Any], attr: str) -> str:
    if not els:
        return ""
    return els[0].get(attr, "") or ""


def _href_to_photo_id(href: str) -> str:
    if not href:
        return ""
    import re
    m = re.search(r"/short-video/([0-9a-zA-Z]+)", href)
    return m.group(1) if m else ""


def _looks_like_captcha(page: Any) -> bool:
    try:
        url = page.url or ""
    except Exception:
        return False
    return "/captcha" in url or "verify" in url.lower()
```

- [ ] **Step 3: Write extraction test**

Create `sidecar/tests/test_mining_extract_kuaishou.py`:
```python
from pathlib import Path

from csm_core.mining.platforms.kuaishou_search import KuaishouSearchAdapter


FIXTURE = Path(__file__).parent / "fixtures" / "mining" / "kuaishou" / "search_dom.html"


def test_extract_two_cards_from_fixture():
    adapter = KuaishouSearchAdapter()
    html = FIXTURE.read_text(encoding="utf-8")
    cards = adapter._extract_from_dom(html, exclude_ids=set())
    assert len(cards) == 2
    c1 = cards[0]
    assert c1.platform == "kuaishou"
    assert c1.platform_video_id == "3xabc123"
    assert c1.url == "https://www.kuaishou.com/short-video/3xabc123"
    assert c1.title == "扫地机器人 推荐"
    assert c1.author_name == "家电达人"
    assert c1.play_count == 123_000   # 12.3万
    assert c1.like_count == 3_456
    assert c1.duration_sec == 83      # 1:23


def test_extract_respects_exclude_ids():
    adapter = KuaishouSearchAdapter()
    html = FIXTURE.read_text(encoding="utf-8")
    cards = adapter._extract_from_dom(html, exclude_ids={"3xabc123"})
    assert len(cards) == 1
    assert cards[0].platform_video_id == "3xdef456"
```

- [ ] **Step 4: Run extraction tests**

Run: `pytest sidecar/tests/test_mining_extract_kuaishou.py -v`
Expected: 2 tests pass.

- [ ] **Step 5: Commit**

```bash
git add csm_core/mining/platforms/kuaishou_search.py sidecar/tests/fixtures/mining/kuaishou/search_dom.html sidecar/tests/test_mining_extract_kuaishou.py
git commit -m "feat(mining): 快手 search adapter — DOM scroll extract"
```

---

### Task 14: 抖音 search adapter

Douyin is the hardest. Strategy: navigate to search URL, intercept `/aweme/v1/web/general/search/single/` XHR (the same one their React app calls), parse JSON. If XHR doesn't fire (likely on first load due to X-Bogus reissue), fall back to scrolling and re-trying.

**Files:**
- Create: `csm_core/mining/platforms/douyin_search.py`
- Create: `sidecar/tests/fixtures/mining/douyin/search_response.json`
- Create: `sidecar/tests/test_mining_extract_douyin.py`

- [ ] **Step 1: Save fixture**

Save to `sidecar/tests/fixtures/mining/douyin/search_response.json`:
```json
{
  "status_code": 0,
  "data": [
    {
      "type": 1,
      "aweme_info": {
        "aweme_id": "7300000000000000001",
        "desc": "扫地机器人推荐",
        "share_url": "https://www.douyin.com/video/7300000000000000001",
        "author": {"uid": "123", "nickname": "测评博主", "short_id": "abc"},
        "video": {
          "cover": {"url_list": ["https://p3.douyinpic.com/aaa.jpg"]},
          "duration": 60000
        },
        "statistics": {
          "digg_count": 1234,
          "play_count": 5678,
          "share_count": 90,
          "comment_count": 22
        },
        "create_time": 1715000000
      }
    },
    {
      "type": 1,
      "aweme_info": {
        "aweme_id": "7300000000000000002",
        "desc": "扫地机器人评测",
        "share_url": "https://www.douyin.com/video/7300000000000000002",
        "author": {"uid": "456", "nickname": "家电党", "short_id": "def"},
        "video": {
          "cover": {"url_list": ["https://p3.douyinpic.com/bbb.jpg"]},
          "duration": 45000
        },
        "statistics": {"digg_count": 88, "play_count": 999, "share_count": 1, "comment_count": 0},
        "create_time": 1715100000
      }
    }
  ]
}
```

- [ ] **Step 2: Write the adapter**

`csm_core/mining/platforms/douyin_search.py`:
```python
"""抖音 search adapter — XHR intercept on /aweme/v1/web/general/search/single/.

Highest-risk platform: X-Bogus signature, strict login enforcement,
captcha on first load when fingerprint looks fresh. Strategy:

1. Verify login cookie (sessionid) exists in profile.
2. Navigate search URL; let the React app issue its own (signed) XHR.
3. Listen on page.on('response') for the search endpoint; parse JSON.
4. Scroll to trigger more pages; cap at N scrolls / target_count.
5. Detect captcha/login walls and bail with needs_login or risk_control.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any
from urllib.parse import quote

from csm_core.browser_infra import mining_browser
from csm_core.mining.models import (
    Platform, ProgressUpdate, SearchOutcome, VideoCard,
)
from csm_core.mining.platforms._common import OnCard, OnProgress

logger = logging.getLogger(__name__)


class DouyinSearchAdapter:
    platform: Platform = "douyin"

    def search(
        self,
        keyword: str,
        target_count: int,
        on_card: OnCard,
        on_progress: OnProgress,
        cancel_event: threading.Event,
    ) -> SearchOutcome:
        if not mining_browser.has_login_cookie("douyin"):
            on_progress(ProgressUpdate(platform=self.platform, phase="needs_login", got=0, target=target_count))
            return SearchOutcome(
                platform=self.platform, status="needs_login", cards_emitted=0,
                error_message="no sessionid in douyin profile",
            )

        on_progress(ProgressUpdate(platform=self.platform, phase="launching", got=0, target=target_count))
        emitted = 0
        seen: set[str] = set()
        risk_detected = False

        with mining_browser.launched_page("douyin") as page:
            on_progress(ProgressUpdate(platform=self.platform, phase="scrolling", got=0, target=target_count))

            def _on_response(response: Any) -> None:
                nonlocal emitted, risk_detected
                if cancel_event.is_set() or emitted >= target_count:
                    return
                if "/aweme/v1/web/general/search/single" not in response.url:
                    return
                try:
                    body = response.json()
                except Exception:
                    return
                if body.get("status_code") not in (0, None):
                    return
                for c in self._extract_cards(body):
                    if emitted >= target_count:
                        return
                    if c.platform_video_id in seen:
                        continue
                    seen.add(c.platform_video_id)
                    emitted += 1
                    c.rank_in_search = emitted
                    on_card(c)
                on_progress(ProgressUpdate(
                    platform=self.platform, phase="scrolling",
                    got=emitted, target=target_count,
                ))

            page.on("response", _on_response)
            url = f"https://www.douyin.com/search/{quote(keyword)}?type=video"
            page.goto(url, wait_until="domcontentloaded", timeout=30_000)

            for _ in range(30):
                if cancel_event.is_set() or emitted >= target_count:
                    break
                if _is_captcha_or_login(page):
                    risk_detected = True
                    break
                page.evaluate("window.scrollBy(0, window.innerHeight * 2)")
                time.sleep(2.0)

        if risk_detected:
            return SearchOutcome(
                platform=self.platform, status="risk_control",
                cards_emitted=emitted, error_message="captcha/login wall",
            )
        if cancel_event.is_set():
            return SearchOutcome(platform=self.platform, status="cancelled", cards_emitted=emitted)
        on_progress(ProgressUpdate(platform=self.platform, phase="done", got=emitted, target=target_count))
        return SearchOutcome(platform=self.platform, status="done", cards_emitted=emitted)

    def _extract_cards(self, body: dict[str, Any]) -> list[VideoCard]:
        if not isinstance(body, dict):
            return []
        cards: list[VideoCard] = []
        for item in body.get("data") or []:
            if not isinstance(item, dict):
                continue
            info = item.get("aweme_info") or {}
            aweme_id = info.get("aweme_id")
            if not aweme_id:
                continue
            author = info.get("author") or {}
            stats = info.get("statistics") or {}
            video = info.get("video") or {}
            cover_list = (video.get("cover") or {}).get("url_list") or []
            duration_ms = video.get("duration") or 0
            cards.append(VideoCard(
                platform="douyin",
                platform_video_id=str(aweme_id),
                url=info.get("share_url") or f"https://www.douyin.com/video/{aweme_id}",
                title=info.get("desc", "") or "",
                author_name=author.get("nickname", "") or "",
                author_id=str(author.get("uid", "")) or "",
                cover_url=cover_list[0] if cover_list else "",
                duration_sec=int(duration_ms / 1000) if duration_ms else None,
                play_count=stats.get("play_count"),
                like_count=stats.get("digg_count"),
                published_at=_ts_to_iso(info.get("create_time")),
                raw=info,
            ))
        return cards


def _ts_to_iso(ts) -> str | None:
    if not isinstance(ts, (int, float)) or ts <= 0:
        return None
    try:
        from datetime import datetime, timezone
        return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return None


def _is_captcha_or_login(page: Any) -> bool:
    try:
        url = page.url or ""
    except Exception:
        return False
    if "captcha" in url.lower() or "verify" in url.lower():
        return True
    if url.startswith("https://www.douyin.com/passport/"):
        return True
    return False
```

- [ ] **Step 3: Write extraction test**

`sidecar/tests/test_mining_extract_douyin.py`:
```python
import json
from pathlib import Path

from csm_core.mining.platforms.douyin_search import DouyinSearchAdapter


FIXTURE = Path(__file__).parent / "fixtures" / "mining" / "douyin" / "search_response.json"


def test_extract_two_cards_from_fixture():
    adapter = DouyinSearchAdapter()
    body = json.loads(FIXTURE.read_text(encoding="utf-8"))
    cards = adapter._extract_cards(body)
    assert len(cards) == 2
    c1 = cards[0]
    assert c1.platform == "douyin"
    assert c1.platform_video_id == "7300000000000000001"
    assert c1.url == "https://www.douyin.com/video/7300000000000000001"
    assert c1.title == "扫地机器人推荐"
    assert c1.author_name == "测评博主"
    assert c1.author_id == "123"
    assert c1.like_count == 1234     # digg_count
    assert c1.play_count == 5678
    assert c1.duration_sec == 60     # 60000ms → 60s
    assert c1.cover_url.startswith("https://")


def test_extract_handles_missing_fields():
    adapter = DouyinSearchAdapter()
    cards = adapter._extract_cards({
        "status_code": 0,
        "data": [{"type": 1, "aweme_info": {"aweme_id": "x"}}],
    })
    assert len(cards) == 1
    assert cards[0].platform_video_id == "x"
    assert cards[0].title == ""
    assert cards[0].duration_sec is None


def test_extract_returns_empty_on_failure_status():
    adapter = DouyinSearchAdapter()
    cards = adapter._extract_cards({"status_code": 8, "data": []})
    # Adapter is forgiving on status when data is empty anyway.
    assert cards == []
```

- [ ] **Step 4: Run extraction tests**

Run: `pytest sidecar/tests/test_mining_extract_douyin.py -v`
Expected: 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add csm_core/mining/platforms/douyin_search.py sidecar/tests/fixtures/mining/douyin/search_response.json sidecar/tests/test_mining_extract_douyin.py
git commit -m "feat(mining): 抖音 search adapter — XHR intercept + captcha bail"
```

---

### Task 15: MiningRunner — orchestrator

**Files:**
- Create: `csm_core/mining/runner.py`

- [ ] **Step 1: Write `csm_core/mining/runner.py`**

```python
"""Orchestrates one MiningJob: pick adapters, run each platform serially,
stream cards to storage, publish progress events.

Threading: one job runs on one worker thread (sidecar's
``mining_service`` ThreadPoolExecutor with max_workers=1). Inside the
job we DO NOT spawn additional threads — adapters block on
patchright sync API which is already greenlet-bound to this thread.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Callable

from csm_core.mining import storage as mining_storage
from csm_core.mining.models import (
    Platform, ProgressUpdate, SearchOutcome, VideoCard,
)
from csm_core.mining.platforms._common import SearchAdapter
from csm_core.mining.platforms.bilibili_search import BilibiliSearchAdapter
from csm_core.mining.platforms.douyin_search import DouyinSearchAdapter
from csm_core.mining.platforms.kuaishou_search import KuaishouSearchAdapter

logger = logging.getLogger(__name__)


PUBLISH_EVERY_N_CARDS = 5
PUBLISH_EVERY_N_SECONDS = 10.0


EventPublisher = Callable[[str, dict], None]
"""Callable injected by mining_service to publish to the event bus.
Signature: ``publish(kind, payload)`` — kind ∈ {"job.started", "job.progress",
"job.platform_done", "job.finished", "login.required"}."""


def get_adapter(platform: Platform) -> SearchAdapter:
    if platform == "bilibili":
        return BilibiliSearchAdapter()
    if platform == "kuaishou":
        return KuaishouSearchAdapter()
    if platform == "douyin":
        return DouyinSearchAdapter()
    raise ValueError(f"unknown platform: {platform}")


class MiningRunner:
    def __init__(self, *, publish: EventPublisher) -> None:
        self.publish = publish
        self._cancel_events: dict[int, threading.Event] = {}
        self._lock = threading.Lock()

    def register_cancel_event(self, job_id: int) -> threading.Event:
        ev = threading.Event()
        with self._lock:
            self._cancel_events[job_id] = ev
        return ev

    def cancel(self, job_id: int) -> bool:
        with self._lock:
            ev = self._cancel_events.get(job_id)
        if ev:
            ev.set()
            return True
        return False

    def run(self, job_id: int) -> None:
        job = mining_storage.get_job(job_id)
        if job is None:
            logger.warning("MiningRunner.run: unknown job %d", job_id)
            return
        cancel_event = self.register_cancel_event(job_id)
        mining_storage.mark_started(job_id)
        self.publish("job.started", {"job_id": job_id, "keyword": job["keyword"]})

        # Per-card publisher state, reset between platforms.
        last_pub_time = [0.0]
        last_pub_count = [0]

        for platform in job["platforms"]:
            if cancel_event.is_set():
                mining_storage.update_platform_progress(
                    job_id, platform, got=0, target=job["target_per_platform"], phase="cancelled",
                )
                continue

            adapter = get_adapter(platform)

            def _on_card(card: VideoCard, platform=platform) -> None:
                try:
                    mining_storage.upsert_video_and_link(card, job_id)
                except Exception as e:
                    logger.exception("upsert_video_and_link failed: %s", e)

            def _on_progress(pu: ProgressUpdate, platform=platform) -> None:
                mining_storage.update_platform_progress(
                    job_id, platform,
                    got=pu.got, target=pu.target, phase=pu.phase, note=pu.note,
                )
                now = time.monotonic()
                if (
                    pu.phase != "scrolling"
                    or pu.got - last_pub_count[0] >= PUBLISH_EVERY_N_CARDS
                    or now - last_pub_time[0] >= PUBLISH_EVERY_N_SECONDS
                ):
                    last_pub_count[0] = pu.got
                    last_pub_time[0] = now
                    self.publish("job.progress", {
                        "job_id": job_id, "platform": platform, "phase": pu.phase,
                        "got": pu.got, "target": pu.target, "note": pu.note,
                    })
                if pu.phase == "needs_login":
                    self.publish("login.required", {"job_id": job_id, "platform": platform})

            try:
                outcome: SearchOutcome = adapter.search(
                    keyword=job["keyword"],
                    target_count=job["target_per_platform"],
                    on_card=_on_card,
                    on_progress=_on_progress,
                    cancel_event=cancel_event,
                )
            except Exception as e:
                logger.exception("adapter %s threw — recording as failed", platform)
                mining_storage.update_platform_progress(
                    job_id, platform,
                    got=0, target=job["target_per_platform"],
                    phase="failed", note=str(e)[:200],
                )
                self.publish("job.platform_done", {
                    "job_id": job_id, "platform": platform,
                    "status": "failed", "count": 0, "error": str(e)[:200],
                })
                continue

            # Final platform progress with outcome status.
            mining_storage.update_platform_progress(
                job_id, platform,
                got=outcome.cards_emitted,
                target=job["target_per_platform"],
                phase=outcome.status if outcome.status != "done" else "done",
            )
            self.publish("job.platform_done", {
                "job_id": job_id, "platform": platform,
                "status": outcome.status, "count": outcome.cards_emitted,
                "error": outcome.error_message,
            })

        summary = mining_storage.finalize_job(job_id)
        self.publish("job.finished", {"job_id": job_id, "summary": summary})

        with self._lock:
            self._cancel_events.pop(job_id, None)
```

- [ ] **Step 2: Write an integration test using a fake adapter**

Create `sidecar/tests/test_mining_runner.py`:
```python
"""Runner integration test with a fake adapter — no real browser."""
import threading
from pathlib import Path

import pytest

from csm_core.mining import storage as ms
from csm_core.mining.models import (
    ProgressUpdate, SearchOutcome, VideoCard,
)
from csm_core.mining.runner import MiningRunner
from csm_core.monitor import storage as monitor_storage


@pytest.fixture
def db(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(monitor_storage, "_initialized", False)
    monkeypatch.setattr(monitor_storage, "_db_path", None)
    if hasattr(monitor_storage._local, "conn"):
        delattr(monitor_storage._local, "conn")
    monitor_storage.init_db(tmp_path / "monitor.db")
    yield


class FakeAdapter:
    def __init__(self, platform, cards, status="done"):
        self.platform = platform
        self.cards = cards
        self.status = status

    def search(self, keyword, target_count, on_card, on_progress, cancel_event):
        on_progress(ProgressUpdate(platform=self.platform, phase="launching", got=0, target=target_count))
        for c in self.cards:
            if cancel_event.is_set():
                return SearchOutcome(platform=self.platform, status="cancelled", cards_emitted=0)
            on_card(c)
        on_progress(ProgressUpdate(platform=self.platform, phase="done", got=len(self.cards), target=target_count))
        return SearchOutcome(platform=self.platform, status=self.status, cards_emitted=len(self.cards))


def test_runner_two_platforms_done(db, monkeypatch):
    events: list[tuple] = []

    def publish(kind, payload):
        events.append((kind, payload))

    runner = MiningRunner(publish=publish)
    fake_b = FakeAdapter("bilibili", [
        VideoCard(platform="bilibili", platform_video_id="B1", url="u1", title="t1"),
        VideoCard(platform="bilibili", platform_video_id="B2", url="u2", title="t2"),
    ])
    fake_k = FakeAdapter("kuaishou", [
        VideoCard(platform="kuaishou", platform_video_id="K1", url="u3", title="t3"),
    ])

    def fake_get_adapter(platform):
        return {"bilibili": fake_b, "kuaishou": fake_k}[platform]

    monkeypatch.setattr("csm_core.mining.runner.get_adapter", fake_get_adapter)

    jid = ms.create_job("k", ["bilibili", "kuaishou"], 50)
    runner.run(jid)

    job = ms.get_job(jid)
    assert job["status"] == "done"
    rows, total = ms.list_videos(commented="all")
    assert total == 3
    kinds = [e[0] for e in events]
    assert "job.started" in kinds
    assert "job.finished" in kinds
    # platform_done events for both platforms
    plat_done = [e for e in events if e[0] == "job.platform_done"]
    assert len(plat_done) == 2


def test_runner_partial_when_one_needs_login(db, monkeypatch):
    events = []
    def publish(kind, payload):
        events.append((kind, payload))

    runner = MiningRunner(publish=publish)
    good = FakeAdapter("bilibili", [
        VideoCard(platform="bilibili", platform_video_id="B1", url="u1"),
    ])
    bad = FakeAdapter("douyin", [], status="needs_login")

    def fake_get_adapter(platform):
        return {"bilibili": good, "douyin": bad}[platform]

    monkeypatch.setattr("csm_core.mining.runner.get_adapter", fake_get_adapter)

    jid = ms.create_job("k", ["bilibili", "douyin"], 50)
    runner.run(jid)
    job = ms.get_job(jid)
    assert job["status"] == "partial_done"
    rows, total = ms.list_videos(commented="all")
    assert total == 1  # bilibili's one card persisted


def test_runner_cancel_mid_job(db, monkeypatch):
    events = []
    def publish(kind, payload):
        events.append((kind, payload))

    runner = MiningRunner(publish=publish)

    # Adapter that yields 5 cards but checks cancel between each.
    class SlowAdapter:
        platform = "bilibili"
        def search(self, keyword, target_count, on_card, on_progress, cancel_event):
            emitted = 0
            for i in range(5):
                if cancel_event.is_set():
                    return SearchOutcome(platform=self.platform, status="cancelled", cards_emitted=emitted)
                on_card(VideoCard(platform="bilibili", platform_video_id=f"B{i}", url="u"))
                emitted += 1
            on_progress(ProgressUpdate(platform=self.platform, phase="done", got=emitted, target=target_count))
            return SearchOutcome(platform=self.platform, status="done", cards_emitted=emitted)

    monkeypatch.setattr("csm_core.mining.runner.get_adapter", lambda p: SlowAdapter())
    jid = ms.create_job("k", ["bilibili"], 50)
    cancel_event = runner.register_cancel_event(jid)
    cancel_event.set()  # cancel before run
    runner.run(jid)
    rows, total = ms.list_videos(commented="all")
    assert total == 0  # nothing emitted
```

- [ ] **Step 3: Run runner tests**

Run: `pytest sidecar/tests/test_mining_runner.py -v`
Expected: 3 tests pass.

- [ ] **Step 4: Commit**

```bash
git add csm_core/mining/runner.py sidecar/tests/test_mining_runner.py
git commit -m "feat(mining): MiningRunner orchestrator + integration tests"
```

---

### Task 16: Sidecar service layer

**Files:**
- Create: `sidecar/csm_sidecar/services/mining_service.py`

- [ ] **Step 1: Write the service**

`sidecar/csm_sidecar/services/mining_service.py`:
```python
"""Mining service — submits jobs to a single-worker pool, owns the runner."""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, Future
from threading import Lock
from typing import Any

from csm_core.mining import storage as mining_storage
from csm_core.mining.runner import MiningRunner

from ..event_bus import bus as event_bus

logger = logging.getLogger(__name__)


_executor: ThreadPoolExecutor | None = None
_runner: MiningRunner | None = None
_active_job_id: int | None = None
_active_lock = Lock()


def init() -> None:
    """Called from sidecar lifespan. Idempotent."""
    global _executor, _runner
    if _executor is not None:
        return
    _executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mining-worker")
    _runner = MiningRunner(publish=_publish_to_bus)
    # Sweep orphaned running jobs from a previous run.
    interrupted = mining_storage.mark_interrupted_jobs()
    if interrupted:
        logger.info("mining: marked %d orphaned jobs as interrupted", interrupted)


def shutdown() -> None:
    global _executor
    if _executor is not None:
        _executor.shutdown(wait=False, cancel_futures=True)
        _executor = None


def is_busy() -> bool:
    with _active_lock:
        return _active_job_id is not None


def active_job_id() -> int | None:
    with _active_lock:
        return _active_job_id


def submit_job(keyword: str, platforms: list[str], target_per_platform: int) -> int:
    if _executor is None or _runner is None:
        raise RuntimeError("mining_service not initialized")
    with _active_lock:
        if _active_job_id is not None:
            raise RuntimeError(f"mining busy on job {_active_job_id}")
    job_id = mining_storage.create_job(keyword, platforms, target_per_platform)
    event_bus.create_job(_event_job_id(job_id))
    fut = _executor.submit(_run_with_guard, job_id)
    fut.add_done_callback(lambda f: _on_done(job_id, f))
    return job_id


def cancel_job(job_id: int) -> bool:
    if _runner is None:
        return False
    flipped_storage = mining_storage.cancel_job_if_running(job_id)
    runner_acked = _runner.cancel(job_id)
    return flipped_storage or runner_acked


def _run_with_guard(job_id: int) -> None:
    global _active_job_id
    with _active_lock:
        _active_job_id = job_id
    try:
        assert _runner is not None
        _runner.run(job_id)
    except Exception as e:
        logger.exception("mining job %d crashed: %s", job_id, e)
        mining_storage.finalize_job(job_id)
    finally:
        with _active_lock:
            _active_job_id = None


def _on_done(job_id: int, _future: Future) -> None:
    event_bus.finish(_event_job_id(job_id))


def _publish_to_bus(kind: str, payload: dict[str, Any]) -> None:
    job_id = payload.get("job_id")
    if job_id is None:
        return
    event_bus.publish(_event_job_id(job_id), kind, **payload)


def _event_job_id(job_id: int) -> str:
    """One bus queue per mining job, keyed by 'mining-<id>'."""
    return f"mining-{job_id}"
```

- [ ] **Step 2: Test the service (using monkeypatched runner)**

Create `sidecar/tests/test_mining_service.py`:
```python
"""mining_service tests using a fake runner."""
import time
from pathlib import Path

import pytest

from csm_core.mining import storage as ms
from csm_core.monitor import storage as monitor_storage
from csm_sidecar.services import mining_service


@pytest.fixture(autouse=True)
def fresh_db(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(monitor_storage, "_initialized", False)
    monkeypatch.setattr(monitor_storage, "_db_path", None)
    if hasattr(monitor_storage._local, "conn"):
        delattr(monitor_storage._local, "conn")
    monitor_storage.init_db(tmp_path / "monitor.db")
    # Reset service singletons.
    mining_service._executor = None
    mining_service._runner = None
    mining_service._active_job_id = None
    yield
    mining_service.shutdown()


def test_init_idempotent():
    mining_service.init()
    mining_service.init()
    assert not mining_service.is_busy()


def test_submit_runs_and_completes(monkeypatch):
    class StubRunner:
        def __init__(self, *a, **kw): pass
        def run(self, job_id):
            ms.update_platform_progress(job_id, "bilibili", got=1, target=1, phase="done")
        def register_cancel_event(self, job_id):
            import threading
            return threading.Event()
        def cancel(self, job_id): return False

    monkeypatch.setattr(mining_service, "MiningRunner", StubRunner)
    mining_service.init()
    jid = mining_service.submit_job("k", ["bilibili"], 1)
    # Wait up to 2s for the executor to flush.
    for _ in range(20):
        if not mining_service.is_busy():
            break
        time.sleep(0.1)
    assert not mining_service.is_busy()
    assert ms.get_job(jid)["status"] in {"done", "partial_done", "failed"}


def test_submit_rejects_when_busy(monkeypatch):
    import threading

    block = threading.Event()
    class BlockingRunner:
        def __init__(self, *a, **kw): pass
        def run(self, job_id):
            block.wait(timeout=2.0)
            ms.finalize_job(job_id)
        def register_cancel_event(self, job_id):
            return threading.Event()
        def cancel(self, job_id): return False

    monkeypatch.setattr(mining_service, "MiningRunner", BlockingRunner)
    mining_service.init()
    jid1 = mining_service.submit_job("k1", ["bilibili"], 1)
    # Loop until the worker enters run().
    for _ in range(20):
        if mining_service.is_busy():
            break
        time.sleep(0.05)
    with pytest.raises(RuntimeError, match="busy"):
        mining_service.submit_job("k2", ["bilibili"], 1)
    block.set()
    for _ in range(40):
        if not mining_service.is_busy():
            break
        time.sleep(0.05)


def test_cancel_when_no_active_job_returns_false():
    mining_service.init()
    assert mining_service.cancel_job(999) is False
```

- [ ] **Step 3: Run service tests**

Run: `pytest sidecar/tests/test_mining_service.py -v`
Expected: 4 tests pass.

- [ ] **Step 4: Commit**

```bash
git add sidecar/csm_sidecar/services/mining_service.py sidecar/tests/test_mining_service.py
git commit -m "feat(mining): sidecar service layer with single-worker executor"
```

---

### Task 17: Sidecar routes

**Files:**
- Create: `sidecar/csm_sidecar/routes/mining.py`
- Modify: `sidecar/csm_sidecar/main.py` (register router + lifespan hook)

- [ ] **Step 1: Read current main.py to find router registration site**

Open `sidecar/csm_sidecar/main.py` (or `app.py` if that's where routers are wired). Look for existing `app.include_router(monitor.router)` and lifespan startup calls — we need to add similar entries.

- [ ] **Step 2: Write `routes/mining.py`**

```python
"""Mining module routes — jobs, videos, login flow, SSE events."""
from __future__ import annotations

import csv
import io
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from csm_core.browser_infra import mining_browser
from csm_core.mining import storage as mining_storage
from csm_core.mining.models import Platform, StartJobRequest

from ..auth import RequireToken
from ..event_bus import bus as event_bus
from ..services import mining_service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["mining"], dependencies=[RequireToken])


# ── Jobs ─────────────────────────────────────────────────────────────
@router.post("/api/mining/jobs", status_code=201)
async def start_job(body: StartJobRequest) -> dict[str, Any]:
    try:
        job_id = mining_service.submit_job(
            keyword=body.keyword,
            platforms=body.platforms,
            target_per_platform=body.target_per_platform,
        )
    except RuntimeError as e:
        if "busy" in str(e):
            raise HTTPException(status_code=409, detail=str(e))
        raise HTTPException(status_code=500, detail=str(e))
    job = mining_storage.get_job(job_id)
    return {"job_id": job_id, "status": "pending", "job": job}


@router.get("/api/mining/jobs")
async def list_jobs(limit: int = Query(default=20, ge=1, le=200)) -> dict[str, Any]:
    items = mining_storage.list_jobs(limit=limit)
    return {"count": len(items), "jobs": items}


@router.get("/api/mining/jobs/{job_id}")
async def get_job(job_id: int) -> dict[str, Any]:
    job = mining_storage.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"job not found: {job_id}")
    return job


@router.post("/api/mining/jobs/{job_id}/cancel")
async def cancel(job_id: int) -> dict[str, Any]:
    ok = mining_service.cancel_job(job_id)
    if not ok:
        raise HTTPException(status_code=409, detail="job not running or already finished")
    return {"job_id": job_id, "cancelled": True}


@router.get("/api/mining/jobs/{job_id}/events")
async def stream_events(job_id: int):
    """SSE stream of mining.* events for one job."""
    queue_key = f"mining-{job_id}"

    async def event_gen():
        async for event in event_bus.stream(queue_key):
            yield {"event": event.get("kind", "message"), "data": _json(event)}

    return EventSourceResponse(event_gen())


def _json(obj: Any) -> str:
    import json as _j
    return _j.dumps(obj, ensure_ascii=False, default=str)


# ── Videos ───────────────────────────────────────────────────────────
@router.get("/api/mining/videos")
async def list_videos(
    keyword: str | None = Query(default=None),
    platform: Platform | None = Query(default=None),
    commented: str = Query(default="0", pattern="^(0|1|all)$"),
    q: str | None = Query(default=None),
    job_id: int | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=500),
) -> dict[str, Any]:
    rows, total = mining_storage.list_videos(
        keyword=keyword, platform=platform, commented=commented,
        q=q, job_id=job_id, offset=offset, limit=limit,
    )
    return {"total": total, "offset": offset, "limit": limit, "videos": rows}


@router.delete("/api/mining/videos/{video_id}", status_code=204)
async def soft_delete_video(video_id: int) -> None:
    if not mining_storage.soft_delete_video(video_id):
        raise HTTPException(status_code=404, detail="video not found")


@router.get("/api/mining/videos/export.csv")
async def export_csv(
    keyword: str | None = Query(default=None),
    platform: Platform | None = Query(default=None),
    commented: str = Query(default="0", pattern="^(0|1|all)$"),
    q: str | None = Query(default=None),
):
    rows, _ = mining_storage.list_videos(
        keyword=keyword, platform=platform, commented=commented,
        q=q, offset=0, limit=10_000,
    )
    buf = io.StringIO()
    buf.write("﻿")  # BOM so Excel auto-detects UTF-8
    writer = csv.writer(buf)
    writer.writerow([
        "platform", "video_id", "url", "title", "author",
        "duration_sec", "play_count", "like_count",
        "source_keywords", "already_commented", "first_seen_at",
    ])
    for r in rows:
        writer.writerow([
            r["platform"], r["platform_video_id"], r["url"], r["title"],
            r["author_name"], r["duration_sec"] or "",
            r["play_count"] or "", r["like_count"] or "",
            "|".join(r["source_keywords"]),
            "1" if r["already_commented"] else "0",
            r["first_seen_at"],
        ])
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="mining_videos.csv"'},
    )


# ── Login ────────────────────────────────────────────────────────────
class LoginStartBody(BaseModel):
    platform: Platform


_login_specs = {
    "douyin": ("https://www.douyin.com/", "sessionid"),
    "bilibili": ("https://www.bilibili.com/", "SESSDATA"),
    "kuaishou": ("https://www.kuaishou.com/", "kuaishou.web.cp.api_st"),
}


@router.get("/api/mining/login/status")
async def login_status() -> dict[str, Any]:
    return {
        platform: {"logged_in": mining_browser.has_login_cookie(platform)}
        for platform in _login_specs
    }


@router.post("/api/mining/login/{platform}")
async def login_start(platform: Platform) -> dict[str, Any]:
    """Launch a headed Patchright window pointing at the platform homepage.

    User logs in manually; cookies persist in the platform's user_data_dir.
    Returns immediately — the browser stays open and is closed when the
    user calls /confirm.

    Implementation note: we hold the launcher context-manager open in a
    background thread; calling /confirm signals it to close. To keep this
    plan implementation-complete without growing a whole login lifecycle
    object, this endpoint launches and *waits*; FastAPI dispatches sync
    endpoints on a threadpool worker so blocking is fine. User must call
    /confirm within 10 minutes or we time out.
    """
    import threading
    state = _login_state
    with state.lock:
        if state.active_platform is not None:
            raise HTTPException(status_code=409, detail=f"login already active for {state.active_platform}")
        state.active_platform = platform
        state.confirm_event = threading.Event()

    def _runner():
        try:
            url, cookie_name = _login_specs[platform]
            with mining_browser.launched_page(platform, headless=False) as page:
                page.goto(url, wait_until="domcontentloaded", timeout=30_000)
                logger.info("login flow opened for %s — waiting up to 10 min for /confirm", platform)
                state.confirm_event.wait(timeout=600)
        except Exception as e:
            logger.exception("login flow for %s crashed: %s", platform, e)
        finally:
            with state.lock:
                state.active_platform = None
                state.confirm_event = None

    threading.Thread(target=_runner, name=f"mining-login-{platform}", daemon=True).start()
    return {"platform": platform, "browser_opened": True}


@router.post("/api/mining/login/{platform}/confirm")
async def login_confirm(platform: Platform) -> dict[str, Any]:
    state = _login_state
    with state.lock:
        if state.active_platform != platform or state.confirm_event is None:
            raise HTTPException(status_code=409, detail="no active login flow")
        state.confirm_event.set()
    # Brief moment for the browser to flush + close + the runner thread to clear state.
    import time
    for _ in range(20):
        with state.lock:
            if state.active_platform is None:
                break
        time.sleep(0.1)
    logged_in = mining_browser.has_login_cookie(platform)
    return {"platform": platform, "logged_in": logged_in}


class _LoginState:
    def __init__(self) -> None:
        import threading
        self.lock = threading.Lock()
        self.active_platform: Platform | None = None
        self.confirm_event: threading.Event | None = None


_login_state = _LoginState()
```

- [ ] **Step 3: Register router and wire lifespan in `main.py`**

Locate the section that wires monitor routes in `sidecar/csm_sidecar/main.py`. After `app.include_router(monitor.router)` add:

```python
from .routes import mining
app.include_router(mining.router)
```

In the lifespan startup, after `monitor_lifecycle.startup(...)`-style calls, add:

```python
from .services import mining_service
mining_service.init()

# Configure mining browser profile root.
from csm_core import config as core_config
from csm_core.browser_infra import mining_browser as _mb
_mb.configure_profile_root(core_config.default_config_dir() / "browser_profiles")
```

In the lifespan shutdown branch (mirror to monitor's shutdown), add:

```python
mining_service.shutdown()
```

- [ ] **Step 4: Write route tests using FastAPI TestClient**

Create `sidecar/tests/test_mining_routes.py`:
```python
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Reset monitor + mining state per test.
from csm_core.mining import storage as ms
from csm_core.monitor import storage as monitor_storage


@pytest.fixture
def client(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(monitor_storage, "_initialized", False)
    monkeypatch.setattr(monitor_storage, "_db_path", None)
    if hasattr(monitor_storage._local, "conn"):
        delattr(monitor_storage._local, "conn")
    monitor_storage.init_db(tmp_path / "monitor.db")
    # Disable auth for tests.
    monkeypatch.setenv("CSM_DISABLE_AUTH", "1")

    from csm_sidecar.main import app
    from csm_sidecar.services import mining_service
    mining_service._executor = None
    mining_service._runner = None
    mining_service._active_job_id = None
    mining_service.init()
    with TestClient(app) as c:
        yield c
    mining_service.shutdown()


def test_list_videos_empty(client):
    r = client.get("/api/mining/videos")
    assert r.status_code == 200
    assert r.json()["total"] == 0


def test_start_job_rejects_invalid_target(client):
    r = client.post("/api/mining/jobs", json={"keyword": "k", "target_per_platform": 5})
    assert r.status_code == 422  # below ge=10


def test_start_job_rejects_empty_keyword(client):
    r = client.post("/api/mining/jobs", json={"keyword": ""})
    assert r.status_code == 422


def test_cancel_unknown_job_returns_409(client):
    r = client.post("/api/mining/jobs/9999/cancel")
    assert r.status_code == 409


def test_videos_commented_query_three_values(client):
    # Insert a video manually, marked already_commented.
    conn = monitor_storage.get_conn()
    conn.execute(
        "INSERT INTO videos(platform, platform_video_id, url, already_commented) "
        "VALUES('douyin','x','u',1)"
    )
    conn.execute(
        "INSERT INTO videos(platform, platform_video_id, url) "
        "VALUES('douyin','y','u2')"
    )
    r0 = client.get("/api/mining/videos?commented=0")
    r1 = client.get("/api/mining/videos?commented=1")
    rall = client.get("/api/mining/videos?commented=all")
    assert r0.json()["total"] == 1
    assert r1.json()["total"] == 1
    assert rall.json()["total"] == 2


def test_export_csv_returns_attachment(client):
    r = client.get("/api/mining/videos/export.csv")
    assert r.status_code == 200
    assert "text/csv" in r.headers["content-type"]
    assert r.text.startswith("﻿")  # BOM
    assert "platform,video_id,url" in r.text


def test_login_status_returns_three_platforms(client, tmp_path, monkeypatch):
    from csm_core.browser_infra import mining_browser
    mining_browser.configure_profile_root(tmp_path / "profiles")
    r = client.get("/api/mining/login/status")
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) == {"douyin", "bilibili", "kuaishou"}
    for p, info in body.items():
        assert info["logged_in"] is False  # fresh profiles


def test_soft_delete_nonexistent_returns_404(client):
    r = client.delete("/api/mining/videos/9999")
    assert r.status_code == 404
```

- [ ] **Step 5: Verify `CSM_DISABLE_AUTH` exists or use real token**

Search `sidecar/csm_sidecar/auth.py` for `CSM_DISABLE_AUTH` or a similar test-mode hook. If none exists, swap the env var line for whatever the project already provides (e.g. monkeypatching `RequireToken`'s dependency to a no-op). Other monitor tests already exist (e.g. `test_monitor_routes.py`) — mirror their setup pattern.

- [ ] **Step 6: Run route tests**

Run: `pytest sidecar/tests/test_mining_routes.py -v`
Expected: 8 tests pass.

- [ ] **Step 7: Smoke-run the full test suite to catch wiring regressions**

Run: `pytest sidecar/tests/ -x -q`
Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add sidecar/csm_sidecar/routes/mining.py sidecar/csm_sidecar/main.py sidecar/tests/test_mining_routes.py
git commit -m "feat(mining): FastAPI routes for jobs/videos/login + SSE"
```

---

## Phase 4 — Frontend

### Task 18: Pinia store

**Files:**
- Create: `frontend/src/stores/mining.ts`

- [ ] **Step 1: Write the store**

```typescript
import { defineStore } from "pinia"
import { ref, computed } from "vue"

export type Platform = "douyin" | "bilibili" | "kuaishou"
export type CommentedFilter = "0" | "1" | "all"

export interface PlatformProgress {
  got: number
  target: number
  phase: string
  note?: string
}

export interface MiningJob {
  id: number
  keyword: string
  platforms: Platform[]
  target_per_platform: number
  status: string
  progress: Record<Platform, PlatformProgress>
  error_message: string
  created_at: string
  started_at: string | null
  finished_at: string | null
}

export interface Video {
  id: number
  platform: Platform
  platform_video_id: string
  url: string
  title: string
  author_name: string
  author_id: string
  cover_url: string
  duration_sec: number | null
  play_count: number | null
  like_count: number | null
  published_at: string | null
  excluded: boolean
  already_commented: boolean
  commented_source: string | null
  commented_at: string | null
  first_seen_at: string
  source_keywords: string[]
}

const API = "/api/mining"

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(API + path, init)
  if (!r.ok) throw new Error(`${r.status}: ${await r.text()}`)
  return r.json()
}

export const useMiningStore = defineStore("mining", () => {
  const activeJob = ref<MiningJob | null>(null)
  const videos = ref<Video[]>([])
  const total = ref(0)
  const loading = ref(false)
  const filters = ref({
    keyword: null as string | null,
    platform: null as Platform | null,
    commented: "0" as CommentedFilter,
    q: "",
  })
  const loginStatus = ref<Record<Platform, boolean>>({
    douyin: false, bilibili: false, kuaishou: false,
  })

  const hasRunningJob = computed(
    () => activeJob.value !== null
      && ["pending", "running"].includes(activeJob.value.status)
  )

  let eventSource: EventSource | null = null

  async function startJob(keyword: string, platforms: Platform[], target: number): Promise<number> {
    const r = await apiFetch<{ job_id: number; job: MiningJob }>("/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ keyword, platforms, target_per_platform: target }),
    })
    activeJob.value = r.job
    subscribe(r.job_id)
    return r.job_id
  }

  function subscribe(jobId: number) {
    if (eventSource) eventSource.close()
    eventSource = new EventSource(`${API}/jobs/${jobId}/events`)
    eventSource.addEventListener("job.progress", (e: MessageEvent) => {
      const d = JSON.parse(e.data)
      if (activeJob.value && activeJob.value.id === d.job_id) {
        activeJob.value.progress[d.platform as Platform] = {
          got: d.got, target: d.target, phase: d.phase, note: d.note,
        }
      }
    })
    eventSource.addEventListener("job.platform_done", (e: MessageEvent) => {
      const d = JSON.parse(e.data)
      if (activeJob.value && activeJob.value.id === d.job_id) {
        activeJob.value.progress[d.platform as Platform] = {
          ...(activeJob.value.progress[d.platform as Platform] || { target: 50 }),
          got: d.count,
          phase: d.status === "done" ? "done" : d.status,
          note: d.error || "",
        }
      }
    })
    eventSource.addEventListener("job.finished", (e: MessageEvent) => {
      const d = JSON.parse(e.data)
      if (activeJob.value && activeJob.value.id === d.job_id) {
        activeJob.value.status = d.summary.status
        activeJob.value.finished_at = new Date().toISOString()
      }
      eventSource?.close()
      eventSource = null
      refreshVideos()
    })
    eventSource.addEventListener("login.required", (e: MessageEvent) => {
      const d = JSON.parse(e.data)
      loginStatus.value[d.platform as Platform] = false
    })
    eventSource.addEventListener("done", () => {
      eventSource?.close()
      eventSource = null
    })
  }

  async function cancelActive() {
    if (activeJob.value === null) return
    await fetch(`${API}/jobs/${activeJob.value.id}/cancel`, { method: "POST" })
  }

  async function refreshVideos(offset = 0, limit = 50) {
    loading.value = true
    try {
      const params = new URLSearchParams()
      if (filters.value.keyword) params.set("keyword", filters.value.keyword)
      if (filters.value.platform) params.set("platform", filters.value.platform)
      params.set("commented", filters.value.commented)
      if (filters.value.q) params.set("q", filters.value.q)
      params.set("offset", String(offset))
      params.set("limit", String(limit))
      const r = await apiFetch<{ total: number; videos: Video[] }>(`/videos?${params}`)
      total.value = r.total
      if (offset === 0) videos.value = r.videos
      else videos.value.push(...r.videos)
    } finally {
      loading.value = false
    }
  }

  async function refreshLoginStatus() {
    const r = await apiFetch<Record<Platform, { logged_in: boolean }>>("/login/status")
    for (const p of ["douyin", "bilibili", "kuaishou"] as Platform[]) {
      loginStatus.value[p] = r[p]?.logged_in ?? false
    }
  }

  async function startLogin(platform: Platform) {
    await fetch(`${API}/login/${platform}`, { method: "POST" })
  }

  async function confirmLogin(platform: Platform): Promise<boolean> {
    const r = await apiFetch<{ logged_in: boolean }>(`/login/${platform}/confirm`, { method: "POST" })
    loginStatus.value[platform] = r.logged_in
    return r.logged_in
  }

  async function deleteVideo(id: number) {
    await fetch(`${API}/videos/${id}`, { method: "DELETE" })
    videos.value = videos.value.filter(v => v.id !== id)
    total.value = Math.max(0, total.value - 1)
  }

  return {
    activeJob, videos, total, loading, filters, loginStatus,
    hasRunningJob,
    startJob, cancelActive, refreshVideos,
    refreshLoginStatus, startLogin, confirmLogin,
    deleteVideo,
  }
})
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/stores/mining.ts
git commit -m "feat(mining-fe): Pinia store with SSE subscription"
```

---

### Task 19: `MiningView.vue` main shell

**Files:**
- Create: `frontend/src/views/MiningView.vue`
- Create: `frontend/src/components/mining/JobProgressCard.vue`
- Create: `frontend/src/components/mining/VideoTable.vue`
- Create: `frontend/src/components/mining/StartJobModal.vue`
- Create: `frontend/src/components/mining/PlatformLoginPanel.vue`

The 5 files together implement the view + its 4 child components. Each file is reasonably small and focused.

- [ ] **Step 1: Write `MiningView.vue`**

```vue
<template>
  <div class="mining-view">
    <header class="mining-header">
      <h1>引流 · 视频抓取</h1>
      <div class="actions">
        <button @click="showStart = true" :disabled="store.hasRunningJob">+ 新任务</button>
        <button @click="showLogin = true">⚙ 平台登录</button>
        <a :href="exportUrl" download="mining_videos.csv">⏬ 导出 CSV</a>
      </div>
    </header>

    <section v-if="store.activeJob" class="active-job">
      <JobProgressCard :job="store.activeJob" @cancel="store.cancelActive" />
    </section>

    <section class="filters">
      <div class="seg">
        <button
          v-for="opt in commentedOpts" :key="opt.value"
          :class="{ active: store.filters.commented === opt.value }"
          @click="setCommented(opt.value)"
        >{{ opt.label }}</button>
      </div>
      <select v-model="store.filters.platform" @change="onFilterChange">
        <option :value="null">全部平台</option>
        <option value="douyin">抖音</option>
        <option value="bilibili">B 站</option>
        <option value="kuaishou">快手</option>
      </select>
      <input v-model="store.filters.q" placeholder="搜标题或作者" @input="onSearchInput" />
    </section>

    <VideoTable
      :videos="store.videos" :total="store.total" :loading="store.loading"
      @delete="store.deleteVideo"
    />

    <StartJobModal
      v-if="showStart" :login-status="store.loginStatus"
      @close="showStart = false"
      @submit="onStartSubmit"
    />
    <PlatformLoginPanel
      v-if="showLogin" :login-status="store.loginStatus"
      @close="onLoginPanelClose"
      @login="onLogin" @confirm="onConfirmLogin"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, computed } from "vue"
import { useMiningStore, type Platform, type CommentedFilter } from "../stores/mining"
import JobProgressCard from "../components/mining/JobProgressCard.vue"
import VideoTable from "../components/mining/VideoTable.vue"
import StartJobModal from "../components/mining/StartJobModal.vue"
import PlatformLoginPanel from "../components/mining/PlatformLoginPanel.vue"

const store = useMiningStore()
const showStart = ref(false)
const showLogin = ref(false)

const commentedOpts: { value: CommentedFilter; label: string }[] = [
  { value: "0", label: "未评论" },
  { value: "1", label: "已评论" },
  { value: "all", label: "全部" },
]

const exportUrl = computed(() => {
  const p = new URLSearchParams()
  if (store.filters.keyword) p.set("keyword", store.filters.keyword)
  if (store.filters.platform) p.set("platform", store.filters.platform)
  p.set("commented", store.filters.commented)
  if (store.filters.q) p.set("q", store.filters.q)
  return `/api/mining/videos/export.csv?${p}`
})

function setCommented(v: CommentedFilter) {
  store.filters.commented = v
  store.refreshVideos()
}
function onFilterChange() { store.refreshVideos() }

let searchDebounce: number | null = null
function onSearchInput() {
  if (searchDebounce) clearTimeout(searchDebounce)
  searchDebounce = window.setTimeout(() => store.refreshVideos(), 300)
}

async function onStartSubmit(payload: { keyword: string; platforms: Platform[]; target: number }) {
  showStart.value = false
  await store.startJob(payload.keyword, payload.platforms, payload.target)
}

async function onLogin(p: Platform) { await store.startLogin(p) }
async function onConfirmLogin(p: Platform) { await store.confirmLogin(p) }
function onLoginPanelClose() { showLogin.value = false; store.refreshLoginStatus() }

onMounted(async () => {
  await store.refreshLoginStatus()
  await store.refreshVideos()
})
</script>

<style scoped>
.mining-view { display: flex; flex-direction: column; height: 100%; padding: 16px; gap: 16px; }
.mining-header { display: flex; justify-content: space-between; align-items: center; }
.actions { display: flex; gap: 8px; }
.actions a { padding: 6px 12px; border: 1px solid #ddd; border-radius: 6px; text-decoration: none; color: inherit; }
.active-job { padding: 12px; border: 1px solid #ffd; background: #fffef0; border-radius: 8px; }
.filters { display: flex; gap: 8px; align-items: center; }
.seg button { padding: 6px 12px; border: 1px solid #ddd; background: white; }
.seg button.active { background: #2d6cdf; color: white; border-color: #2d6cdf; }
.seg button:first-child { border-radius: 6px 0 0 6px; }
.seg button:last-child { border-radius: 0 6px 6px 0; }
</style>
```

- [ ] **Step 2: Write `JobProgressCard.vue`**

```vue
<template>
  <div class="card">
    <header>
      <strong>{{ job.keyword }}</strong>
      <span class="status" :data-status="job.status">{{ statusLabel }}</span>
      <button class="cancel" v-if="canCancel" @click="$emit('cancel')">取消</button>
    </header>
    <ul>
      <li v-for="p in job.platforms" :key="p">
        <span class="plat">{{ platformLabel(p) }}</span>
        <progress :value="progressOf(p).got" :max="progressOf(p).target"></progress>
        <span class="counts">{{ progressOf(p).got }} / {{ progressOf(p).target }}</span>
        <span class="phase" :data-phase="progressOf(p).phase">{{ phaseLabel(progressOf(p).phase) }}</span>
      </li>
    </ul>
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue"
import type { MiningJob, Platform, PlatformProgress } from "../../stores/mining"

const props = defineProps<{ job: MiningJob }>()
defineEmits<{ cancel: [] }>()

const canCancel = computed(() => ["pending", "running"].includes(props.job.status))
const statusLabel = computed(() => {
  return {
    pending: "排队中", running: "运行中", done: "完成",
    partial_done: "部分完成", failed: "失败",
    cancelled: "已取消", interrupted: "中断",
  }[props.job.status] || props.job.status
})

function progressOf(p: Platform): PlatformProgress {
  return props.job.progress[p] || { got: 0, target: props.job.target_per_platform, phase: "queued" }
}
function platformLabel(p: Platform) {
  return { douyin: "抖音", bilibili: "B站", kuaishou: "快手" }[p]
}
function phaseLabel(phase: string) {
  return {
    queued: "排队", launching: "启动浏览器", scrolling: "滚动加载",
    done: "✓", failed: "失败", needs_login: "需登录",
    risk_control: "风控", cancelled: "已取消",
  }[phase] || phase
}
</script>

<style scoped>
.card { display: flex; flex-direction: column; gap: 8px; }
header { display: flex; gap: 12px; align-items: center; }
.status { padding: 2px 8px; border-radius: 4px; background: #eee; font-size: 12px; }
.status[data-status="done"] { background: #d4edda; }
.status[data-status="failed"] { background: #f8d7da; }
.status[data-status="partial_done"] { background: #fff3cd; }
.cancel { margin-left: auto; }
ul { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 4px; }
li { display: grid; grid-template-columns: 60px 1fr 80px 100px; gap: 12px; align-items: center; }
.phase[data-phase="needs_login"] { color: #d9534f; }
.phase[data-phase="risk_control"] { color: #d9534f; }
</style>
```

- [ ] **Step 3: Write `VideoTable.vue`**

```vue
<template>
  <div class="video-table">
    <p v-if="loading">加载中…</p>
    <p v-else-if="!videos.length">没有视频。换个筛选或起个新任务。</p>
    <article v-for="v in videos" :key="v.id" class="video-row">
      <img :src="v.cover_url || ''" alt="" class="cover" loading="lazy" />
      <div class="body">
        <header>
          <strong>{{ v.title || "(无标题)" }}</strong>
          <span class="plat" :data-platform="v.platform">{{ platformLabel(v.platform) }}</span>
          <span
            v-if="v.already_commented"
            class="commented-badge"
            :title="commentedTooltip(v)"
          >已评论</span>
        </header>
        <footer>
          <span>{{ v.author_name }}</span>
          <span v-if="v.play_count !== null">▶ {{ fmt(v.play_count) }}</span>
          <span v-if="v.like_count !== null">👍 {{ fmt(v.like_count) }}</span>
          <span v-if="v.duration_sec">⏱ {{ fmtDur(v.duration_sec) }}</span>
          <span class="kw" v-for="k in v.source_keywords" :key="k">#{{ k }}</span>
        </footer>
      </div>
      <div class="actions">
        <button disabled title="第二期上线">写评论计划</button>
        <a :href="v.url" target="_blank" rel="noopener">打开</a>
        <button @click="$emit('delete', v.id)">剔除</button>
      </div>
    </article>
  </div>
</template>

<script setup lang="ts">
import type { Video, Platform } from "../../stores/mining"

defineProps<{ videos: Video[]; total: number; loading: boolean }>()
defineEmits<{ delete: [id: number] }>()

function platformLabel(p: Platform) {
  return { douyin: "抖音", bilibili: "B站", kuaishou: "快手" }[p]
}
function fmt(n: number): string {
  if (n >= 10000) return (n / 10000).toFixed(1) + "万"
  if (n >= 1000) return (n / 1000).toFixed(1) + "k"
  return String(n)
}
function fmtDur(s: number): string {
  const m = Math.floor(s / 60), ss = s % 60
  return `${m}:${String(ss).padStart(2, "0")}`
}
function commentedTooltip(v: Video): string {
  const src = v.commented_source === "monitor_task" ? "评论监控任务" : v.commented_source
  return `来自${src}${v.commented_at ? "，最近检查 " + v.commented_at.slice(0, 10) : ""}`
}
</script>

<style scoped>
.video-row { display: grid; grid-template-columns: 120px 1fr 200px; gap: 12px; padding: 12px; border-bottom: 1px solid #eee; }
.cover { width: 120px; height: 80px; object-fit: cover; background: #ddd; border-radius: 4px; }
.body { display: flex; flex-direction: column; gap: 4px; }
header { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.plat { font-size: 11px; padding: 2px 6px; border-radius: 3px; background: #f0f0f0; }
.plat[data-platform="douyin"] { background: #000; color: white; }
.plat[data-platform="bilibili"] { background: #00a1d6; color: white; }
.plat[data-platform="kuaishou"] { background: #ff6633; color: white; }
.commented-badge {
  font-size: 11px; padding: 2px 6px; border-radius: 3px;
  background: #d4edda; color: #155724; cursor: help;
}
footer { display: flex; gap: 8px; color: #666; font-size: 13px; flex-wrap: wrap; }
.kw { color: #2d6cdf; }
.actions { display: flex; flex-direction: column; gap: 6px; align-items: stretch; }
.actions button[disabled] { opacity: 0.4; cursor: not-allowed; }
</style>
```

- [ ] **Step 4: Write `StartJobModal.vue`**

```vue
<template>
  <div class="modal-backdrop" @click.self="$emit('close')">
    <div class="modal">
      <h2>新建抓取任务</h2>
      <label>关键词 <input v-model="keyword" autofocus /></label>
      <fieldset>
        <legend>平台</legend>
        <label v-for="p in allPlatforms" :key="p">
          <input type="checkbox" :value="p" v-model="platforms" />
          {{ label(p) }}
          <span v-if="!loginStatus[p]" class="warn">未登录</span>
        </label>
      </fieldset>
      <label>
        每平台抓取数量：{{ target }}
        <input type="range" min="10" max="200" step="10" v-model.number="target" />
      </label>
      <footer>
        <button @click="$emit('close')">取消</button>
        <button
          class="primary"
          :disabled="!keyword.trim() || platforms.length === 0"
          @click="onSubmit"
        >开始抓取</button>
      </footer>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from "vue"
import type { Platform } from "../../stores/mining"

const props = defineProps<{ loginStatus: Record<Platform, boolean> }>()
const emit = defineEmits<{
  close: []
  submit: [payload: { keyword: string; platforms: Platform[]; target: number }]
}>()

const keyword = ref("")
const platforms = ref<Platform[]>(
  (Object.keys(props.loginStatus) as Platform[]).filter(p => props.loginStatus[p])
)
const target = ref(50)
const allPlatforms: Platform[] = ["douyin", "bilibili", "kuaishou"]

function label(p: Platform) {
  return { douyin: "抖音", bilibili: "B站", kuaishou: "快手" }[p]
}

function onSubmit() {
  emit("submit", { keyword: keyword.value.trim(), platforms: platforms.value, target: target.value })
}
</script>

<style scoped>
.modal-backdrop {
  position: fixed; inset: 0; background: rgba(0,0,0,0.4);
  display: flex; align-items: center; justify-content: center; z-index: 100;
}
.modal { background: white; padding: 24px; border-radius: 8px; min-width: 360px; display: flex; flex-direction: column; gap: 12px; }
label { display: flex; flex-direction: column; gap: 4px; }
fieldset { border: 1px solid #ddd; padding: 8px; border-radius: 4px; }
fieldset label { flex-direction: row; gap: 6px; align-items: center; }
.warn { color: #d9534f; font-size: 12px; }
footer { display: flex; justify-content: flex-end; gap: 8px; }
.primary { background: #2d6cdf; color: white; padding: 6px 16px; border-radius: 4px; border: 0; }
.primary[disabled] { opacity: 0.4; }
</style>
```

- [ ] **Step 5: Write `PlatformLoginPanel.vue`**

```vue
<template>
  <div class="modal-backdrop" @click.self="$emit('close')">
    <div class="modal">
      <h2>平台登录状态</h2>
      <p>登录后 cookie 会保存在本地 profile，下次抓取自动复用。</p>
      <ul>
        <li v-for="p in platforms" :key="p">
          <strong>{{ label(p) }}</strong>
          <span class="status" :data-ok="loginStatus[p]">
            {{ loginStatus[p] ? "已登录" : "未登录" }}
          </span>
          <button v-if="!openFor || openFor === p" @click="onLogin(p)" :disabled="openFor === p">
            {{ openFor === p ? "已打开浏览器…" : "登录 / 重新登录" }}
          </button>
          <button
            v-if="openFor === p" class="primary"
            @click="onConfirm(p)"
          >我登好了</button>
        </li>
      </ul>
      <footer>
        <button @click="$emit('close')">关闭</button>
      </footer>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from "vue"
import type { Platform } from "../../stores/mining"

defineProps<{ loginStatus: Record<Platform, boolean> }>()
const emit = defineEmits<{
  close: []
  login: [platform: Platform]
  confirm: [platform: Platform]
}>()

const platforms: Platform[] = ["douyin", "bilibili", "kuaishou"]
const openFor = ref<Platform | null>(null)

function label(p: Platform) {
  return { douyin: "抖音", bilibili: "B站", kuaishou: "快手" }[p]
}
async function onLogin(p: Platform) {
  openFor.value = p
  emit("login", p)
}
async function onConfirm(p: Platform) {
  emit("confirm", p)
  openFor.value = null
}
</script>

<style scoped>
.modal-backdrop { position: fixed; inset: 0; background: rgba(0,0,0,0.4); display: flex; align-items: center; justify-content: center; z-index: 100; }
.modal { background: white; padding: 24px; border-radius: 8px; min-width: 420px; display: flex; flex-direction: column; gap: 12px; }
ul { list-style: none; padding: 0; }
li { display: grid; grid-template-columns: 80px 80px 1fr auto; gap: 12px; align-items: center; padding: 8px 0; border-bottom: 1px solid #eee; }
.status[data-ok="true"] { color: #155724; }
.status[data-ok="false"] { color: #d9534f; }
.primary { background: #2d6cdf; color: white; padding: 4px 10px; border-radius: 4px; border: 0; }
footer { display: flex; justify-content: flex-end; }
</style>
```

- [ ] **Step 6: Commit**

```bash
git add frontend/src/views/MiningView.vue frontend/src/components/mining/
git commit -m "feat(mining-fe): MiningView + JobProgressCard/VideoTable/StartJobModal/PlatformLoginPanel"
```

---

### Task 20: LeftNav integration + router

**Files:**
- Modify: `frontend/src/components/LeftNav.vue`
- Modify: `frontend/src/router/index.ts` (or wherever routes are defined)

- [ ] **Step 1: Locate the router file**

Run: `grep -r "createRouter" frontend/src/ -l`
Note the path it returns (likely `frontend/src/router/index.ts` or similar).

- [ ] **Step 2: Add a route for `/mining`**

Open the router file and add an entry alongside existing routes:
```typescript
{
  path: "/mining",
  name: "mining",
  component: () => import("../views/MiningView.vue"),
},
```

- [ ] **Step 3: Add a LeftNav entry**

Read `frontend/src/components/LeftNav.vue` to find the existing nav-item pattern (likely an array of items each with `{ to, icon, label }`). Add a new entry between `monitor` and `templates`:
```typescript
{ to: "/mining", icon: "search", label: "引流" }
```

If LeftNav uses inline JSX/template rather than an array, add the equivalent `<router-link to="/mining">引流</router-link>` matching the existing pattern.

- [ ] **Step 4: Sanity-build the frontend**

Run: `pnpm --filter frontend build`
Expected: build succeeds (no TypeScript errors).

If errors mention missing types for `EventSource` in TypeScript strict mode, add `"DOM"` and `"DOM.Iterable"` to `frontend/tsconfig.json`'s `compilerOptions.lib` if not already there.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/LeftNav.vue frontend/src/router/
git commit -m "feat(mining-fe): wire MiningView into LeftNav + router"
```

---

### Task 21: End-to-end smoke test

**Files:**
- Create: `docs/superpowers/plans/2026-05-16-video-mining-mvp-smoke.md`

This is a manual checklist, not an automated test. Smoke testing requires real browser interaction + real platform sessions which CI cannot do.

- [ ] **Step 1: Write the smoke runbook**

Create `docs/superpowers/plans/2026-05-16-video-mining-mvp-smoke.md`:
```markdown
# Video Mining MVP — Smoke Test Runbook

Run after the v0.5 build is installed. All steps performed manually in the app.

## Setup

1. Start the CSM desktop app.
2. Open Settings → confirm `default_config_dir` exists; verify `<config_dir>/browser_profiles/` was created on first sidecar startup.

## A. Login flow (each platform once)

For each `<platform>` in {bilibili, douyin, kuaishou}:

1. Navigate LeftNav → 引流.
2. Click "⚙ 平台登录"; confirm 3 rows visible; all show "未登录" initially.
3. Click "登录 / 重新登录" for `<platform>`.
4. A headed Patchright Chromium window opens at the platform homepage.
5. Sign in normally (QR scan / username+password).
6. Click "我登好了" in CSM.
7. Verify the row updates to "已登录".

## B. First mining job

1. With at least bilibili logged in, click "+ 新任务".
2. Keyword: "扫地机器人"; platforms: bilibili only; target: 50.
3. Submit → modal closes, JobProgressCard appears at top.
4. Watch the bilibili progress bar tick up over 1-3 minutes.
5. When "job.finished" arrives, status badge flips to "完成".
6. Verify video table populates with ≥30 unique bilibili videos.
7. Click a row's "打开" → opens in default browser.
8. Filter "未评论" should equal the full count (nothing pre-existing in monitor_tasks).

## C. Already-commented marker

1. In monitor view, create a `bilibili_comment` task targeting one of the BV-ids you saw in B.
2. Return to 引流, click "+ 新任务" with the SAME keyword.
3. Submit; let it finish.
4. With filter "未评论": the previously-monitored video should NOT appear.
5. Switch filter to "已评论": that one row appears with the green "已评论" badge; tooltip says "来自评论监控任务...".

## D. Multi-platform run + partial failure

1. Delete the douyin profile folder (forces needs_login).
2. Run a mining job with all 3 platforms checked.
3. Verify:
   - bilibili + kuaishou complete normally.
   - douyin row shows "需登录" phase.
   - Overall job status: "部分完成".

## E. Cancel mid-job

1. Start a fresh job, any keyword.
2. Click "取消" within the first minute.
3. Verify status flips to "已取消", already-emitted videos remain visible.

## F. Export

1. With table populated, click "⏬ 导出 CSV".
2. Open in Excel, confirm Chinese text renders correctly (BOM works).
3. Confirm "already_commented" column reflects the filter.

## G. Sidecar restart safety

1. Start a job, immediately kill the sidecar process (Task Manager).
2. Restart the app.
3. Verify that the previous job's status is "interrupted" (not "running").
```

- [ ] **Step 2: Commit**

```bash
git add docs/superpowers/plans/2026-05-16-video-mining-mvp-smoke.md
git commit -m "docs(mining): manual smoke test runbook"
```

---

## Phase 5 — Final integration verification

### Task 22: Full test suite + import audit

- [ ] **Step 1: Run all sidecar tests one final time**

Run: `pytest sidecar/tests/ -v`
Expected: every test passes. If anything mining-related is RED, fix before declaring done.

- [ ] **Step 2: Verify no monitor regression by grepping for old import paths**

Run: `grep -r "from csm_core.monitor.drivers.cookie_store" csm_core/ sidecar/ --include='*.py'`
Expected: only `csm_core/monitor/drivers/cookie_store.py` (the shim itself) appears. No business code should still import the old path — but it's not a bug if they do (shims still work). The audit is informational.

- [ ] **Step 3: Verify the build still produces a sidecar exe**

Run: `pnpm --filter frontend build` then verify the sidecar PyInstaller spec still includes the new paths. Open `CSM.spec` and confirm that `hiddenimports` (if used) doesn't need to be patched for `csm_core.mining.*`. Most likely the implicit collection picks them up since they're under `csm_core/`. If you see an `ImportError: csm_core.mining` from a built exe, add to the spec:
```python
hiddenimports.extend(["csm_core.mining", "csm_core.mining.storage", "csm_core.mining.runner"])
```

- [ ] **Step 4: Bump version in 4 places (per MEMORY.md)**

Per the repo's CSM v0.4.x lessons (MEMORY.md `feedback_csm_release_pipeline_lessons.md`), version bumps must touch:
- `csm_gui/_version.py`
- `frontend/src-tauri/tauri.conf.json`
- `frontend/package.json`
- `sidecar/csm_sidecar/__init__.py`

Bump to `0.5.0` (minor — new feature surface).

- [ ] **Step 5: Add CHANGELOG entry**

Open `CHANGELOG.md`, add at top:
```markdown
## v0.5.0 (2026-XX-XX)

### Added
- 视频引流抓取（mining）：关键词 → 抖音/B站/快手 搜索抓视频列表 → 全局去重落库
- 反查 monitor_tasks，自动标记 already_commented 的视频
- 平台登录 UI（首次手动登录、cookie 持久化）

### Changed
- 共享浏览器基建从 monitor/drivers/ 上提到 browser_infra/ 顶层包；monitor 包内保留 re-export 薄层
```

- [ ] **Step 6: Final commit**

```bash
git add csm_gui/_version.py frontend/src-tauri/tauri.conf.json frontend/package.json sidecar/csm_sidecar/__init__.py CHANGELOG.md
git commit -m "release: v0.5.0 视频引流抓取 MVP"
```

- [ ] **Step 7: Run the manual smoke runbook**

Follow `docs/superpowers/plans/2026-05-16-video-mining-mvp-smoke.md` end to end. Any failures block release.

---

## Done criteria

Every checkbox above is ticked AND:

- All `pytest sidecar/tests/` pass.
- Frontend `pnpm build` succeeds.
- Manual smoke runbook (A–G) all pass on a clean install.
- A test run of "扫地机器人" with at least 2 platforms logged in produces ≥80 videos, deduped, with rank ordering visible.
- Hitting the same keyword twice produces only `video_source_keywords` deltas, no `videos` duplicates.
- A pre-existing `monitor_tasks` row with type `*_comment` and matching target_url causes the corresponding mining video to be marked `already_commented=1`.
