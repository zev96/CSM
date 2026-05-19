# Baidu Monitor Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 3 independent issues in baidu keyword monitoring — default-excluded-domains hot-reload (Bug 3), AddTaskModal default-list popover (Bug 2), and UA pool + curl_cffi Session reuse to dramatically reduce risk control trips (Bug 1).

**Architecture:** All 3 sections are isolated and can be implemented in any order. Section 1 abstracts `_apply_runtime_settings` from `monitor_lifecycle.start()` so PATCH /api/config can hot-reload adapter settings. Section 2 adds a read-only popover modal in AddTaskModal that pulls from the existing `useConfig` Pinia store. Section 3 adds per-task `curl_cffi.Session` reuse with rotating Chrome-sub-version UA headers (impersonate=chrome120 stays fixed for TLS fingerprint stability), modelled after the existing bilibili_comment pattern.

**Tech Stack:** Python 3.11 + FastAPI + curl_cffi (already vendored), Vue 3 + Pinia + Vue Router, pytest.

**Reference spec:** [docs/superpowers/specs/2026-05-19-baidu-monitor-hardening-design.md](../specs/2026-05-19-baidu-monitor-hardening-design.md)

---

## File Structure

| File | Status | Responsibility |
|---|---|---|
| `sidecar/csm_sidecar/services/monitor_lifecycle.py` | Modify | Extract `_apply_runtime_settings(cfg)`; add `reconfigure(cfg)` |
| `sidecar/csm_sidecar/routes/config.py` | Modify | `patch_config` calls `reconfigure` when monitor.* changes |
| `sidecar/tests/routes/test_config.py` | Create | 3 patch_config tests covering hot-reload |
| `sidecar/tests/routes/__init__.py` | Create | (empty, makes routes/ a test package) |
| `csm_core/monitor/platforms/baidu_keyword.py` | Modify | `_UA_POOL` + `_get_session` / `_drop_session` helpers + session param threading |
| `sidecar/tests/test_baidu_keyword.py` | Modify | 5 new tests: session cache, warmup failure, UA rotation, drop on risk, session propagation |
| `frontend/src/components/monitor/AddTaskModal.vue` | Modify | Add "view default list" button + popover modal + computed + router push |
| `frontend/src/views/SettingsView.vue` | Modify | Add `id="baidu-default-excludes"` anchor on default_excluded_domains FormField |

---

## Section 1 — Bug 3: Settings Hot-Reload

### Task 1: Refactor `_apply_runtime_settings` from `start()`

**Goal:** Pure refactor — extract the adapter-configure logic from `start()` into a reusable function. No external behavior change.

**Files:**
- Modify: `sidecar/csm_sidecar/services/monitor_lifecycle.py`

- [ ] **Step 1: Look at current `start()` to remember the layout**

Run: `Read sidecar/csm_sidecar/services/monitor_lifecycle.py` (or `cat sidecar/csm_sidecar/services/monitor_lifecycle.py`)

The current `start()` (lines 27-79) inlines all `apply_settings` / `browser_driver.configure` calls. We're going to extract lines 47-71 into a private `_apply_runtime_settings(cfg)` function.

- [ ] **Step 2: Add `AppConfig` import**

In `sidecar/csm_sidecar/services/monitor_lifecycle.py`, change the import line:

```python
from csm_core.monitor import storage
from csm_core.monitor.drivers import browser_driver
from csm_core.monitor.platforms.baidu_keyword import ADAPTER as BAIDU_ADAPTER
from csm_core.monitor.platforms.zhihu_question import ADAPTER as ZHIHU_ADAPTER

from . import config_service
from .monitor_loop import MonitorLoop
from ..monitor_bus import monitor_bus
```

…to add `AppConfig`:

```python
from csm_core.config import AppConfig
from csm_core.monitor import storage
from csm_core.monitor.drivers import browser_driver
from csm_core.monitor.platforms.baidu_keyword import ADAPTER as BAIDU_ADAPTER
from csm_core.monitor.platforms.zhihu_question import ADAPTER as ZHIHU_ADAPTER

from . import config_service
from .monitor_loop import MonitorLoop
from ..monitor_bus import monitor_bus
```

- [ ] **Step 3: Add `_apply_runtime_settings` function**

In `sidecar/csm_sidecar/services/monitor_lifecycle.py`, insert this function BEFORE `def start(...)`:

```python
def _apply_runtime_settings(cfg: AppConfig) -> None:
    """Push runtime-mutable monitor settings into the live adapters.

    Called from start() (first boot) and reconfigure() (every PATCH that
    touches monitor.*). NEVER raises — invalid config logs & old values
    stay in place, so PATCH /api/config still returns 200 with whatever
    the user wrote, and we don't surprise them with stale runtime state
    after a partial failure.

    Each adapter gets its own try/except so a failure in one (e.g. the
    browser driver can't find chrome.exe at the new path) doesn't stop
    the others from picking up the new pacing / exclude-domain values.
    """
    mcfg = cfg.monitor
    try:
        browser_driver.configure(mcfg.browser_engine, mcfg.chrome_path or "")
    except Exception as e:
        logger.exception("browser_driver.configure failed: %s", e)
    try:
        ZHIHU_ADAPTER.apply_settings(
            engine=mcfg.browser_engine,
            rotation_enabled=mcfg.multi_account_rotation,
            tasks_per_account=mcfg.tasks_per_account,
            cooldown_seconds=mcfg.cookie_cooldown_minutes * 60,
        )
    except Exception as e:
        logger.exception("ZHIHU_ADAPTER.apply_settings failed: %s", e)
    try:
        bcfg = mcfg.baidu_keyword
        BAIDU_ADAPTER.apply_settings(
            headless_default=bcfg.headless_default,
            captcha_visible_timeout_s=bcfg.captcha_visible_timeout_s,
            captcha_max_promotions=bcfg.captcha_max_promotions,
            serp_pacing_seconds=bcfg.serp_pacing_seconds,
            article_pacing_seconds=bcfg.article_pacing_seconds,
            baijiahao_pacing_seconds=bcfg.baijiahao_pacing_seconds,
            breaker_failures=bcfg.breaker_failures,
            breaker_cooldown_seconds=bcfg.breaker_cooldown_seconds,
            default_excluded_domains=bcfg.default_excluded_domains,
        )
    except Exception as e:
        logger.exception("BAIDU_ADAPTER.apply_settings failed: %s", e)
```

- [ ] **Step 4: Update `start()` to call `_apply_runtime_settings`**

In `sidecar/csm_sidecar/services/monitor_lifecycle.py`, replace the existing `start()` body (the part from `cfg = config_service.load()` through the `BAIDU_ADAPTER.apply_settings(...)` call) with:

```python
def start(*, db_path: Path | None = None) -> MonitorLoop:
    """Idempotently start the loop. Initialises monitor.db on first call.

    ``db_path`` defaults to ``<config_dir>/monitor.db`` matching the
    legacy GUI shell. Passing an explicit path is for tests that want to
    co-locate the DB with their tmp settings.
    """
    global _loop
    if _loop is not None and _loop.is_running():
        return _loop

    if not storage_initialized():
        target = Path(db_path) if db_path else _default_db_path()
        storage.init_db(target)
        logger.info("monitor storage initialised at %s", target)

    cfg = config_service.load()
    _apply_runtime_settings(cfg)
    _loop = MonitorLoop(
        event_sink=monitor_bus.publish,
        alert_top_n=cfg.monitor.alert_top_n,
        cooldown_hours=cfg.monitor.alert_cooldown_hours,
        # tick_seconds left at default 60 — APScheduler handles drift.
    )
    _loop.start()
    return _loop
```

- [ ] **Step 5: Run existing monitor_lifecycle tests to verify refactor didn't break anything**

Run from `D:\CSM\.claude\worktrees\hopeful-elion-cff72a`:

```
cd sidecar && python -m pytest tests/ -k "lifecycle or monitor" -x
```

Expected: all existing tests pass. If any test was importing the inline apply_settings call, fix the import (none should — those calls weren't directly testable).

- [ ] **Step 6: Commit**

```
git add sidecar/csm_sidecar/services/monitor_lifecycle.py
git commit -m "$(cat <<'EOF'
refactor(monitor): extract _apply_runtime_settings from start()

Pure refactor — pull adapter.apply_settings + browser_driver.configure
out of monitor_lifecycle.start() into a private function so reconfigure()
(next commit) can share the same code path. Each adapter gets its own
try/except so a single broken setting doesn't poison the others.

No behavior change at this point.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Add `reconfigure(cfg)` function

**Goal:** Public API entry point for hot-reload. Idempotent + no-op when loop is down.

**Files:**
- Modify: `sidecar/csm_sidecar/services/monitor_lifecycle.py`

- [ ] **Step 1: Add `reconfigure` function**

In `sidecar/csm_sidecar/services/monitor_lifecycle.py`, insert AFTER `stop()` (around line 90, before `def get()`):

```python
def reconfigure(cfg: AppConfig | None = None) -> None:
    """Re-push monitor settings into adapters without restarting the loop.

    Called from PATCH /api/config when ``monitor.*`` fields change so the
    user doesn't need to restart sidecar after editing default exclude
    domains / pacing / breaker thresholds / etc.

    No-op if start() hasn't been called yet — lifespan order ensures
    start() runs before HTTP routes accept requests, but defensive.

    ``cfg=None`` re-reads the latest from config_service (the usual path).
    Passing an explicit cfg is for tests that want to skip the disk read.
    """
    if _loop is None:
        return
    _apply_runtime_settings(cfg or config_service.load())
```

- [ ] **Step 2: Verify the file still parses**

Run from `D:\CSM\.claude\worktrees\hopeful-elion-cff72a`:

```
cd sidecar && python -c "from csm_sidecar.services import monitor_lifecycle; print(monitor_lifecycle.reconfigure)"
```

Expected output: `<function reconfigure at 0x...>`

- [ ] **Step 3: Commit**

```
git add sidecar/csm_sidecar/services/monitor_lifecycle.py
git commit -m "$(cat <<'EOF'
feat(monitor): add reconfigure() for runtime settings hot-reload

Public API entry point so routes/config.py can push monitor.* changes
into the live adapters without bouncing the whole sidecar process.
Idempotent — calling reconfigure when the loop is down is a no-op (safe
during boot before start() runs).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: PATCH /api/config triggers reconfigure

**Goal:** Wire the route handler. The handler imports `monitor_lifecycle` lazily inside the function to avoid a circular import at module load.

**Files:**
- Modify: `sidecar/csm_sidecar/routes/config.py`

- [ ] **Step 1: Replace `patch_config` handler**

In `sidecar/csm_sidecar/routes/config.py`, replace the `patch_config` function (currently lines 27-43) with:

```python
@router.patch("/api/config", response_model=AppConfig)
async def patch_config(updates: dict[str, Any]) -> AppConfig:
    """Apply a partial update. Nested dicts (e.g. monitor) are deep-merged.

    Body shape: any subset of AppConfig's JSON form. Examples::

        {"vault_root": "/path/to/vault"}
        {"monitor": {"alert_top_n": 7}}
        {"default_provider": "anthropic", "default_model": {"anthropic": "claude-opus-4-7"}}

    When ``monitor.*`` fields change, the live adapters are reconfigured
    so users don't need to restart sidecar after editing default exclude
    domains / pacing / breaker thresholds. reconfigure() is idempotent
    and swallows internal exceptions, so PATCH still returns 200 even if
    an adapter rejected the new value.
    """
    try:
        new_cfg = config_service.patch(updates)
    except ValueError as e:  # pydantic ValidationError subclasses ValueError
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        ) from e

    # Hot-reload adapter settings only when monitor.* actually changed.
    # Lazy import: routes are imported during app boot before
    # monitor_lifecycle is fully ready; module-level import would create
    # a circular dep with config_service.
    if "monitor" in updates:
        from ..services import monitor_lifecycle
        monitor_lifecycle.reconfigure(new_cfg)

    return new_cfg
```

- [ ] **Step 2: Verify the file still imports**

Run from `D:\CSM\.claude\worktrees\hopeful-elion-cff72a`:

```
cd sidecar && python -c "from csm_sidecar.routes import config; print(config.patch_config)"
```

Expected output: `<function patch_config at 0x...>`

- [ ] **Step 3: Commit**

```
git add sidecar/csm_sidecar/routes/config.py
git commit -m "$(cat <<'EOF'
feat(config): hot-reload adapter settings on PATCH /api/config

When PATCH body touches monitor.*, call monitor_lifecycle.reconfigure
to push new settings into live adapters. Closes the gap where users
edited default_excluded_domains / pacing in SettingsView but had to
restart sidecar before the change took effect.

Lazy import of monitor_lifecycle inside the handler avoids a circular
dep with config_service at module load time.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Tests — patch_config hot-reload behavior

**Goal:** End-to-end tests that prove the route triggers reconfigure and the adapter sees the new value.

**Files:**
- Create: `sidecar/tests/routes/__init__.py` (empty)
- Create: `sidecar/tests/routes/test_config.py`

- [ ] **Step 1: Create routes test package**

Run from `D:\CSM\.claude\worktrees\hopeful-elion-cff72a`:

```
mkdir -p sidecar/tests/routes
```

Then create `sidecar/tests/routes/__init__.py` as an empty file (write a file with no content). This makes `routes` a discoverable test package.

- [ ] **Step 2: Write the failing tests**

Create `sidecar/tests/routes/test_config.py` with this content:

```python
"""Tests for PATCH /api/config hot-reload behavior.

Verifies that monitor.* changes trigger monitor_lifecycle.reconfigure(),
and that non-monitor changes don't (avoid wasting cycles).
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from csm_core.config import AppConfig
from csm_core.monitor.platforms.baidu_keyword import ADAPTER as BAIDU_ADAPTER
from csm_sidecar.app import create_app
from csm_sidecar.services import config_service, monitor_lifecycle


@pytest.fixture
def client(tmp_path, monkeypatch):
    """TestClient with an isolated config path under tmp_path."""
    # Point config_service at a tmp file so PATCH writes don't touch
    # the real user config. config_service caches the resolved path
    # via lru_cache-equivalent module state, so monkeypatch get_path.
    cfg_path = tmp_path / "settings.json"
    monkeypatch.setattr(config_service, "get_path", lambda: cfg_path)
    # Force re-load of in-memory cached config (if any).
    if hasattr(config_service, "_cache"):
        monkeypatch.setattr(config_service, "_cache", None, raising=False)
    app = create_app()
    # Bypass token auth for tests; the dependency is RequireToken which
    # reads CSM_SIDECAR_TOKEN env, but the simplest workaround is to set
    # one and pass the header in the test client.
    monkeypatch.setenv("CSM_SIDECAR_TOKEN", "test-token")
    return TestClient(app, headers={"X-CSM-Token": "test-token"})


def test_patch_monitor_calls_reconfigure(client):
    """PATCH with monitor.* should call monitor_lifecycle.reconfigure."""
    with patch.object(monitor_lifecycle, "reconfigure") as mock_recfg:
        resp = client.patch(
            "/api/config",
            json={"monitor": {"baidu_keyword": {"default_excluded_domains": ["a.com"]}}},
        )
    assert resp.status_code == 200
    assert mock_recfg.call_count == 1
    # reconfigure receives the new AppConfig with the patch already applied
    (call_cfg,) = mock_recfg.call_args.args
    assert isinstance(call_cfg, AppConfig)
    assert "a.com" in call_cfg.monitor.baidu_keyword.default_excluded_domains


def test_patch_non_monitor_skips_reconfigure(client):
    """PATCH touching only non-monitor fields should NOT call reconfigure."""
    with patch.object(monitor_lifecycle, "reconfigure") as mock_recfg:
        resp = client.patch("/api/config", json={"vault_root": str(client)})
    assert resp.status_code == 200
    assert mock_recfg.call_count == 0


def test_patch_default_excluded_domains_visible_to_adapter(client):
    """End-to-end: PATCH the domain list, observe BAIDU_ADAPTER updated.

    This is the user-visible fix for Bug 3: edit in SettingsView →
    adapter's internal state changes WITHOUT a sidecar restart.
    """
    # Force monitor_lifecycle into the "loop running" state so
    # reconfigure() doesn't short-circuit on `_loop is None`.
    fake_loop = object()  # any non-None placeholder; reconfigure only
                          # checks `_loop is None`, doesn't touch attrs
    monitor_lifecycle._loop = fake_loop  # noqa: SLF001
    try:
        resp = client.patch(
            "/api/config",
            json={"monitor": {"baidu_keyword": {
                "default_excluded_domains": ["bug3-test.example"],
            }}},
        )
        assert resp.status_code == 200
        # Adapter should have picked up the new value
        assert "bug3-test.example" in BAIDU_ADAPTER._default_excluded_domains  # noqa: SLF001
    finally:
        monitor_lifecycle._loop = None  # noqa: SLF001 — reset for other tests
```

- [ ] **Step 3: Run the new tests to verify they pass**

Run from `D:\CSM\.claude\worktrees\hopeful-elion-cff72a`:

```
cd sidecar && python -m pytest tests/routes/test_config.py -v
```

Expected: all 3 tests pass.

If `create_app` is not in `csm_sidecar.app` (different module name), find it with `grep -rn "def create_app" sidecar/` and adjust the import. Same for `X-CSM-Token` header — search `RequireToken` definition to find the actual header name.

- [ ] **Step 4: Run full sidecar suite to check no regressions**

Run from `D:\CSM\.claude\worktrees\hopeful-elion-cff72a`:

```
cd sidecar && python -m pytest tests/ -x
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```
git add sidecar/tests/routes/__init__.py sidecar/tests/routes/test_config.py
git commit -m "$(cat <<'EOF'
test(config): cover patch_config hot-reload behavior

Three tests:
- monitor.* patch calls reconfigure with the new AppConfig
- non-monitor patch (vault_root etc.) skips reconfigure
- end-to-end: PATCH default_excluded_domains → BAIDU_ADAPTER picks up
  the new value without sidecar restart (the user-visible Bug 3 fix)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Section 2 — Bug 2: AddTaskModal Default-List Popover

### Task 5: Add anchor id to SettingsView's default_excluded_domains FormField

**Goal:** Give the router-push hash a target to scroll to.

**Files:**
- Modify: `frontend/src/views/SettingsView.vue`

- [ ] **Step 1: Find the default_excluded_domains FormField**

Run from `D:\CSM\.claude\worktrees\hopeful-elion-cff72a`:

```
grep -n "default_excluded_domains" frontend/src/views/SettingsView.vue
```

Note the line of the `<FormField` that wraps the textarea (the textarea binds `setField("monitor.baidu_keyword.default_excluded_domains", ...)`).

- [ ] **Step 2: Wrap the FormField with an anchor div**

In `frontend/src/views/SettingsView.vue`, find the `<FormField` for default_excluded_domains and wrap it (or add `id` to it). If the existing FormField looks like:

```vue
<FormField
  label="默认排除域名"
  hint="..."
>
  <textarea ... />
</FormField>
```

Wrap it in a div with the anchor id:

```vue
<div id="baidu-default-excludes">
  <FormField
    label="默认排除域名"
    hint="..."
  >
    <textarea ... />
  </FormField>
</div>
```

This guarantees `router.push({ hash: "#baidu-default-excludes" })` scrolls to the right place without depending on whether `FormField` propagates `id`.

- [ ] **Step 3: Verify typecheck**

Run from `D:\CSM\.claude\worktrees\hopeful-elion-cff72a`:

```
cd frontend && npm run typecheck
```

Expected: no new errors beyond pre-existing ones.

- [ ] **Step 4: Commit**

```
git add frontend/src/views/SettingsView.vue
git commit -m "$(cat <<'EOF'
feat(settings): add scroll anchor for baidu default-excludes section

Wraps the default_excluded_domains FormField with id="baidu-default-excludes"
so the AddTaskModal popover (next commit) can deep-link to it via
router.push({ hash: ... }).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: AddTaskModal — script setup state + computed + router

**Goal:** Wire the data flow: pull default list from `useConfig` store, add reactive popover state, define the navigate function.

**Files:**
- Modify: `frontend/src/components/monitor/AddTaskModal.vue`

- [ ] **Step 1: Find existing script setup imports**

Run from `D:\CSM\.claude\worktrees\hopeful-elion-cff72a`:

```
grep -n "^import\|^const\|^function" frontend/src/components/monitor/AddTaskModal.vue | head -30
```

Note where `import { ref, ... } from "vue"` is, and how the file currently emits / closes the modal (look for `emit("close"`).

- [ ] **Step 2: Add imports**

In `frontend/src/components/monitor/AddTaskModal.vue`'s `<script setup>` block, add these imports near the top (with the other Vue imports):

```ts
import { computed, ref } from "vue";
import { useRouter } from "vue-router";

import { useConfig } from "@/stores/config";
```

(If `computed`/`ref` are already imported from "vue", just add them to the existing import statement — don't duplicate.)

- [ ] **Step 3: Add state + computed + handler in `<script setup>`**

In `frontend/src/components/monitor/AddTaskModal.vue`'s `<script setup>` block, add these AFTER the existing ref declarations (somewhere near `baiduUseDefaultExcludes`, ~line 85):

```ts
// Popover that shows the current global default_excluded_domains
// (read-only, with a button to jump to the Settings section for editing).
// Data is pulled live from useConfig — the store is hydrated at app boot,
// but onMounted in this component is a defensive fallback if a user opens
// the modal before the config has loaded.
const cfgStore = useConfig();
const router = useRouter();
const showDefaultDomainsPopover = ref(false);
const defaultExcludeDomains = computed<string[]>(
  () => cfgStore.data?.monitor?.baidu_keyword?.default_excluded_domains ?? []
);

function goToSettingsExcludeDomains() {
  showDefaultDomainsPopover.value = false;
  emit("close");  // close AddTaskModal first so the Settings view is visible
  router.push({ name: "settings", hash: "#baidu-default-excludes" });
}
```

Note: if the component uses a different emit name to close (e.g. `update:open` or `cancel`), use that name. Check the existing close button to find the right emit.

- [ ] **Step 4: Add onMounted fallback for store hydration**

In `frontend/src/components/monitor/AddTaskModal.vue`'s `<script setup>` block, if there's already an `onMounted` block, add to it; otherwise add:

```ts
import { onMounted } from "vue";

onMounted(async () => {
  // If the config store wasn't hydrated yet (rare race in cold start),
  // load it now so the popover's count badge shows the right number.
  if (!cfgStore.data) {
    try {
      await cfgStore.load();
    } catch {
      // Non-fatal: popover will show "(空)" — the user can still proceed
      // with the rest of the form. Logging handled by the store itself.
    }
  }
});
```

(If onMounted is already imported, skip the import line. If `onMounted` already exists in the file with other side-effects, just add the body inside it.)

- [ ] **Step 5: Verify typecheck**

Run from `D:\CSM\.claude\worktrees\hopeful-elion-cff72a`:

```
cd frontend && npm run typecheck
```

Expected: no new errors. If you get `Property 'data' does not exist on type ...` — the store's state type may need `.data` to be exposed differently; check `frontend/src/stores/config.ts` and adjust the field name accordingly.

- [ ] **Step 6: Commit**

```
git add frontend/src/components/monitor/AddTaskModal.vue
git commit -m "$(cat <<'EOF'
feat(monitor): wire AddTaskModal to useConfig for default-list display

Adds script-level state for the upcoming popover that shows the current
monitor.baidu_keyword.default_excluded_domains. Pulls from the existing
useConfig Pinia store; onMounted fallback re-loads if the store wasn't
hydrated yet (defensive — boot path usually loads first).

Template hookup comes next; this commit is the data wiring only.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: AddTaskModal — template button + popover modal

**Goal:** UI surface — the button next to the toggle and the modal-in-modal popover.

**Files:**
- Modify: `frontend/src/components/monitor/AddTaskModal.vue`

- [ ] **Step 1: Replace the `baiduUseDefaultExcludes` FormField**

In `frontend/src/components/monitor/AddTaskModal.vue`, find the FormField that contains `<FormToggle v-model="baiduUseDefaultExcludes" />` (around line 439-445) and replace it with:

```vue
<FormField
  label="启用默认电商/B2B 黑名单"
  hint="默认过滤 jd / 1688 / taobao / pinduoduo 等采购与电商站点（这些命中目标品牌也不是软文）。如果你确实要监测这些站，关掉。"
  inline
>
  <div class="flex items-center gap-2">
    <FormToggle v-model="baiduUseDefaultExcludes" />
    <button
      type="button"
      class="text-[11px] text-[var(--ink-2)] hover:text-[var(--primary-deep)] underline-offset-2 hover:underline"
      @click="showDefaultDomainsPopover = true"
    >
      查看名单（{{ defaultExcludeDomains.length }}）
    </button>
  </div>
</FormField>
```

- [ ] **Step 2: Add popover modal markup**

In `frontend/src/components/monitor/AddTaskModal.vue`, find the outermost `<template>` root and add this popover markup at the very bottom of the template (so it's a sibling of the main modal content, with higher z-index):

```vue
<!-- 默认排除域名展示弹层（modal-in-modal） -->
<div
  v-if="showDefaultDomainsPopover"
  class="fixed inset-0 z-[60] flex items-center justify-center bg-black/30"
  @click.self="showDefaultDomainsPopover = false"
>
  <div class="w-[400px] max-h-[60vh] flex flex-col rounded-lg bg-[var(--card)] p-4 shadow-xl">
    <div class="flex items-center justify-between mb-3">
      <div class="text-[13px] font-medium">默认排除域名（{{ defaultExcludeDomains.length }}）</div>
      <button
        type="button"
        class="text-[16px] leading-none"
        @click="showDefaultDomainsPopover = false"
      >×</button>
    </div>

    <div class="flex-1 overflow-auto text-[12px] font-mono space-y-1">
      <div v-if="defaultExcludeDomains.length === 0" class="text-[var(--ink-3)]">
        （空 —— 去应用设置里添加）
      </div>
      <div v-for="d in defaultExcludeDomains" :key="d">{{ d }}</div>
    </div>

    <div class="mt-3 pt-3 border-t border-[var(--line)] flex justify-between items-center">
      <button
        type="button"
        class="text-[11.5px] text-[var(--primary-deep)] hover:underline"
        @click="goToSettingsExcludeDomains"
      >
        去应用设置编辑 →
      </button>
      <button
        type="button"
        class="text-[11.5px] px-3 py-1 rounded bg-[var(--card-2)]"
        @click="showDefaultDomainsPopover = false"
      >
        关闭
      </button>
    </div>
  </div>
</div>
```

- [ ] **Step 3: Append a merge note to the "自定义排除域名" hint**

In `frontend/src/components/monitor/AddTaskModal.vue`, find the `<FormField label="自定义排除域名"` (around line 447-449) and change its `hint` from:

```
hint="一行一个；自家品牌官网 / 其他非软文站点写这里。可写 cewey.com 或 https://www.cewey.com/，会按 host 后缀匹配（cewey.com 同时命中 www.cewey.com / shop.cewey.com）。"
```

…to:

```
hint="一行一个；自家品牌官网 / 其他非软文站点写这里。可写 cewey.com 或 https://www.cewey.com/，会按 host 后缀匹配（cewey.com 同时命中 www.cewey.com / shop.cewey.com）。会和上方"默认黑名单"合并去重。"
```

- [ ] **Step 4: Verify typecheck + build**

Run from `D:\CSM\.claude\worktrees\hopeful-elion-cff72a`:

```
cd frontend && npm run typecheck
```

Expected: no new errors.

Optionally smoke-test the build:

```
cd frontend && npm run build
```

Expected: succeeds without errors (warnings about pre-existing issues are OK).

- [ ] **Step 5: Manual smoke test (if dev server is running)**

If `scripts/dev.ps1` is running, open the app → 监测 → 新建任务 → 百度类型 → 展开 SERP 抓取设置 → confirm:
- "查看名单（N）" button appears next to "启用默认电商/B2B 黑名单" toggle
- Clicking it shows a popover with the current list
- "去应用设置编辑 →" closes both modals and navigates to SettingsView scrolled to `#baidu-default-excludes`

(Manual; no automated browser test.)

- [ ] **Step 6: Commit**

```
git add frontend/src/components/monitor/AddTaskModal.vue
git commit -m "$(cat <<'EOF'
feat(monitor): add view-default-list popover in AddTaskModal

Next to the "启用默认电商/B2B 黑名单" toggle, add a small button that
shows the current global default_excluded_domains in a modal-in-modal
popover (read-only). Includes a "去应用设置编辑" link that navigates to
SettingsView scrolled to the right section.

Closes the UX gap where users couldn't see what domains were already
in the global list without leaving the new-task flow.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Section 3 — Bug 1: UA Pool + Session Reuse

### Task 8: Add `_UA_POOL` + `_next_ua` + init session state

**Goal:** Module-level UA pool + per-instance index + per-task session map. Pure addition; no existing behavior changes yet.

**Files:**
- Modify: `csm_core/monitor/platforms/baidu_keyword.py`

- [ ] **Step 1: Add threading import + UA pool constant**

In `csm_core/monitor/platforms/baidu_keyword.py`, find the existing imports block (top of file, line ~17-23) and add `threading`:

```python
from __future__ import annotations

import logging
import threading
from datetime import datetime
from typing import Any, Callable
from urllib.parse import urlparse, quote
```

Then, after the existing `_XPATH_*` constants (around line 56-58) and before `def parse_serp`, add:

```python
# Chrome 子版本 UA 轮换池。curl_cffi 的 impersonate="chrome120" 在
# _get_session 里保持不变（控制 TLS/H2 fingerprint，跨大版本切换会
# 让 TLS 与 UA header 矛盾更可疑），只换 User-Agent header 在 Chrome
# 119-122 之间轮转。
_UA_POOL: tuple[str, ...] = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
)
```

- [ ] **Step 2: Extend `BaiduKeywordAdapter.__init__`**

In `csm_core/monitor/platforms/baidu_keyword.py`, find `def __init__(self) -> None:` (line 359) and replace its body with:

```python
def __init__(self) -> None:
    # 真实字段在 apply_settings 里被覆盖。
    self._headless_default = True
    self._captcha_timeout_s = 90
    # 默认排除域名（B2B / 电商）。apply_settings 会用 config 里的值
    # 覆盖；空 list 表示「不应用全局黑名单」（用户在设置页清空时）。
    self._default_excluded_domains: tuple[str, ...] = ()
    # UA 轮换游标 + per-task curl_cffi.Session 池。Session 内含 cookie jar，
    # per-task 复用让 BAIDUID / BIDUPSID baseline cookie 不被频繁丢弃 →
    # 大幅降低百度风控触发率（参考 bilibili_comment 同款模式）。
    self._ua_idx = 0
    self._http_sessions: dict[int, Any] = {}
    self._http_sessions_lock = threading.Lock()
```

- [ ] **Step 3: Add `_next_ua` method**

In `csm_core/monitor/platforms/baidu_keyword.py`, after `__init__` and BEFORE `apply_settings`, add:

```python
def _next_ua(self) -> str:
    """Round-robin pick from _UA_POOL. Called only by _get_session
    so each Session gets a stable UA for its lifetime — switching UA
    mid-session would itself be a bot signal."""
    ua = _UA_POOL[self._ua_idx % len(_UA_POOL)]
    self._ua_idx += 1
    return ua
```

- [ ] **Step 4: Verify file still parses**

Run from `D:\CSM\.claude\worktrees\hopeful-elion-cff72a`:

```
python -c "from csm_core.monitor.platforms.baidu_keyword import BaiduKeywordAdapter, _UA_POOL; print(len(_UA_POOL)); a = BaiduKeywordAdapter(); print(a._next_ua())"
```

Expected output:
```
4
Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36
```

- [ ] **Step 5: Commit**

```
git add csm_core/monitor/platforms/baidu_keyword.py
git commit -m "$(cat <<'EOF'
feat(monitor): add UA pool + session state to BaiduKeywordAdapter

Adds the module-level _UA_POOL (4 Chrome sub-version UAs), per-adapter
_ua_idx round-robin cursor, and per-task _http_sessions dict guarded by
_http_sessions_lock. No callers yet — wiring comes in the next commits.

Modelled after the bilibili_comment pattern: keep curl_cffi
impersonate="chrome120" constant (TLS fingerprint), rotate only the
User-Agent header.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 9: Add `_get_session` + `_drop_session` helpers (TDD)

**Goal:** Per-task Session factory + cleanup. Test-first so we catch warmup-failure-not-fatal semantics up front.

**Files:**
- Modify: `csm_core/monitor/platforms/baidu_keyword.py`
- Modify: `sidecar/tests/test_baidu_keyword.py`

- [ ] **Step 1: Write failing tests**

Find the end of `sidecar/tests/test_baidu_keyword.py` (you should already know the file from prior work). Append:

```python
# ── _get_session / _drop_session / _next_ua ────────────────────────────


def test_next_ua_rotates_through_pool():
    """连续调用应该至少覆盖 3 个不同 UA (pool 有 4 条 + Mac 1 条)."""
    from csm_core.monitor.platforms import baidu_keyword

    adapter = baidu_keyword.BaiduKeywordAdapter()
    seen = {adapter._next_ua() for _ in range(8)}
    assert len(seen) >= 3, f"expected >=3 distinct UAs across 8 rotations, got {seen}"


def test_get_session_caches_per_task(monkeypatch):
    """同一 task_id 调两次 _get_session 返回同一对象；不同 task_id 返回不同对象."""
    from csm_core.monitor.platforms import baidu_keyword

    # Avoid real curl_cffi calls. Build a fake Session class that records
    # warmup GETs and exposes a .close().
    created: list[Any] = []

    class FakeSession:
        def __init__(self, *a, **kw):
            self.headers = {}
            self.closed = False
            created.append(self)

        def get(self, url, **kwargs):
            return type("R", (), {"status_code": 200})()

        def close(self):
            self.closed = True

    fake_cc = type("M", (), {"Session": FakeSession})()
    monkeypatch.setattr(
        "curl_cffi.requests", fake_cc, raising=False,
    )
    # Replace the module-attribute import path used by _get_session
    import sys
    sys.modules["curl_cffi.requests"] = fake_cc

    adapter = baidu_keyword.BaiduKeywordAdapter()
    s1 = adapter._get_session(42)
    s2 = adapter._get_session(42)
    s3 = adapter._get_session(43)
    assert s1 is s2, "same task_id should get cached session"
    assert s1 is not s3, "different task_id should get different session"
    assert len(created) == 2


def test_get_session_warmup_failure_not_fatal(monkeypatch, caplog):
    """warm-up GET baidu.com 抛异常时 _get_session 仍正常返回 session."""
    from csm_core.monitor.platforms import baidu_keyword

    class FakeSession:
        def __init__(self, *a, **kw):
            self.headers = {}

        def get(self, url, **kwargs):
            raise RuntimeError("simulated network failure")

        def close(self):
            pass

    fake_cc = type("M", (), {"Session": FakeSession})()
    import sys
    sys.modules["curl_cffi.requests"] = fake_cc

    adapter = baidu_keyword.BaiduKeywordAdapter()
    with caplog.at_level("INFO", logger="csm_core.monitor.platforms.baidu_keyword"):
        sess = adapter._get_session(99)
    assert sess is not None
    assert "warmup failed" in caplog.text.lower()


def test_drop_session_removes_and_closes(monkeypatch):
    """_drop_session 应该从 dict 里移除并调 close。重复调用 idempotent."""
    from csm_core.monitor.platforms import baidu_keyword

    class FakeSession:
        def __init__(self, *a, **kw):
            self.headers = {}
            self.closed = False

        def get(self, url, **kwargs):
            return type("R", (), {"status_code": 200})()

        def close(self):
            self.closed = True

    fake_cc = type("M", (), {"Session": FakeSession})()
    import sys
    sys.modules["curl_cffi.requests"] = fake_cc

    adapter = baidu_keyword.BaiduKeywordAdapter()
    sess = adapter._get_session(7)
    assert 7 in adapter._http_sessions
    adapter._drop_session(7)
    assert 7 not in adapter._http_sessions
    assert sess.closed is True
    # Idempotent: second call is no-op, doesn't raise
    adapter._drop_session(7)
```

- [ ] **Step 2: Run tests to see them fail**

Run from `D:\CSM\.claude\worktrees\hopeful-elion-cff72a`:

```
cd sidecar && python -m pytest tests/test_baidu_keyword.py::test_next_ua_rotates_through_pool tests/test_baidu_keyword.py::test_get_session_caches_per_task tests/test_baidu_keyword.py::test_get_session_warmup_failure_not_fatal tests/test_baidu_keyword.py::test_drop_session_removes_and_closes -v
```

Expected: `test_next_ua_rotates_through_pool` PASSES (already implemented in Task 8). The other 3 FAIL with `AttributeError: 'BaiduKeywordAdapter' object has no attribute '_get_session'`.

- [ ] **Step 3: Implement `_get_session` and `_drop_session`**

In `csm_core/monitor/platforms/baidu_keyword.py`, AFTER `_next_ua` method, add:

```python
def _get_session(self, task_id: int) -> Any:
    """Get-or-create curl_cffi.Session for this task. First call warm-ups
    by GET https://www.baidu.com/ to seed BAIDUID/BIDUPSID baseline cookies.

    Thread safety: BAIDU_ADAPTER is a module singleton and the ThreadPool
    in monitor_loop runs multiple tasks concurrently. The lock guards the
    dict only — the Session itself is used single-threaded inside one
    task's _fetch_once → _check_block path, so per-session calls don't
    need synchronization.

    Warm-up failure is non-fatal: subsequent real requests will build
    cookies naturally; warm-up only reduces the "naked cookie" risk on
    the first article fetch.
    """
    with self._http_sessions_lock:
        sess = self._http_sessions.get(task_id)
        if sess is not None:
            return sess
        from curl_cffi import requests as cc_requests
        sess = cc_requests.Session(impersonate="chrome120")
        sess.headers.update({
            "User-Agent": self._next_ua(),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1",
        })
        try:
            sess.get("https://www.baidu.com/", timeout=8)
        except Exception as e:
            logger.info("baidu session warmup failed (task=%d): %s", task_id, e)
        self._http_sessions[task_id] = sess
        return sess


def _drop_session(self, task_id: int) -> None:
    """Drop and close the per-task Session. Called from fetch()'s finally
    block so every task gets a fresh session next time — long-lived
    sessions accumulate request-count signals that baidu uses to flag
    bots. Idempotent: dropping an absent task_id is a no-op."""
    with self._http_sessions_lock:
        sess = self._http_sessions.pop(task_id, None)
    if sess is not None:
        try:
            sess.close()
        except Exception:
            pass
```

- [ ] **Step 4: Run tests to verify they pass**

Run from `D:\CSM\.claude\worktrees\hopeful-elion-cff72a`:

```
cd sidecar && python -m pytest tests/test_baidu_keyword.py::test_next_ua_rotates_through_pool tests/test_baidu_keyword.py::test_get_session_caches_per_task tests/test_baidu_keyword.py::test_get_session_warmup_failure_not_fatal tests/test_baidu_keyword.py::test_drop_session_removes_and_closes -v
```

Expected: all 4 PASS.

- [ ] **Step 5: Commit**

```
git add csm_core/monitor/platforms/baidu_keyword.py sidecar/tests/test_baidu_keyword.py
git commit -m "$(cat <<'EOF'
feat(monitor): add _get_session/_drop_session for per-task cookie reuse

Per-task curl_cffi.Session with warmup GET to baidu.com to seed
BAIDUID/BIDUPSID baseline cookies. Drop on task end so long-lived
session request counts don't accumulate.

Thread safety: dict-level lock; Session itself used single-threaded
within one task. Warm-up failure is non-fatal (logged then continue).

Tests cover: UA pool rotation, per-task caching, warmup failure
tolerance, drop-and-close idempotency.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 10: Thread session through `_cc_get`

**Goal:** Make `_cc_get` accept an optional `session` kwarg. Backwards-compatible — existing callers that don't pass it get the old stateless behavior.

**Files:**
- Modify: `csm_core/monitor/platforms/baidu_keyword.py`

- [ ] **Step 1: Replace `_cc_get`**

In `csm_core/monitor/platforms/baidu_keyword.py`, find `def _cc_get(url: str, **kwargs: Any) -> Any:` (line 125) and replace with:

```python
def _cc_get(url: str, *, session: Any = None, **kwargs: Any) -> Any:
    """HTTP GET via curl_cffi.

    ``session=None`` (legacy) → stateless single-request curl_cffi.requests.get
    ``session=<Session>``      → session.get keeping cookie jar / connection pool

    Indirection retained for single-test monkeypatching. Session-mode
    drops any ``impersonate=`` kwarg since the Session was already
    constructed with one.
    """
    if session is not None:
        kwargs.pop("impersonate", None)
        return session.get(url, **kwargs)
    from curl_cffi import requests as cc_requests
    return cc_requests.get(url, **kwargs)
```

- [ ] **Step 2: Verify existing tests still pass**

Run from `D:\CSM\.claude\worktrees\hopeful-elion-cff72a`:

```
cd sidecar && python -m pytest tests/test_baidu_keyword.py -x
```

Expected: ALL tests pass (including the 4 from Task 9). The signature change is backwards-compatible because `session` is keyword-only with default `None`.

- [ ] **Step 3: Commit**

```
git add csm_core/monitor/platforms/baidu_keyword.py
git commit -m "$(cat <<'EOF'
feat(monitor): _cc_get accepts optional session for cookie reuse

Backwards-compatible — session=None keeps the old stateless path.
With session passed, _cc_get delegates to session.get so BAIDUID/
BIDUPSID cookies persist across SERP / link / article requests
within one task.

Drops impersonate kwarg in session-mode since the Session was
already constructed with impersonate="chrome120".

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 11: Thread session through `resolve_baidu_link` + `fetch_article_http`

**Goal:** Module-level helpers accept the session and pass it down to `_cc_get`. Backwards-compatible.

**Files:**
- Modify: `csm_core/monitor/platforms/baidu_keyword.py`

- [ ] **Step 1: Update `resolve_baidu_link`**

In `csm_core/monitor/platforms/baidu_keyword.py`, find `def resolve_baidu_link(url: str) -> str:` (line 130) and replace with:

```python
def resolve_baidu_link(url: str, *, session: Any = None) -> str:
    """如果是 baidu.com/link?url=... 跳转，跟随 redirect 拿真实 URL。

    非百度跳转 URL 直接返回。任何异常 → 返回原 URL（adapter 自然把它当
    抓取失败 source）。

    ``session`` —— 可选 curl_cffi.Session 复用 cookie / connection pool。
    None 时走 stateless 旧路径（保留给单测 monkeypatch _cc_get 用）。
    """
    if not url or "baidu.com/link?" not in url:
        return url
    try:
        resp = _cc_get(
            url,
            session=session,
            impersonate="chrome120",
            allow_redirects=True,
            timeout=10,
        )
        return getattr(resp, "url", None) or url
    except Exception as e:
        logger.info("resolve_baidu_link(%s) raised: %s", url[:60], e)
        return url
```

- [ ] **Step 2: Update `fetch_article_http`**

In `csm_core/monitor/platforms/baidu_keyword.py`, find `def fetch_article_http(url: str) -> dict[str, Any]:` (line 156) and replace its signature + the two `_cc_get` calls. The full function (preserving the existing risk-detection logic and return-dict structure) becomes:

```python
def fetch_article_http(url: str, *, session: Any = None) -> dict[str, Any]:
    """用 curl_cffi + readability 抓单篇文章，返回纯文本正文。

    ``session`` —— 可选 curl_cffi.Session 复用 cookie / connection pool。
    None 时走 stateless 旧路径（保留给单测 monkeypatch _cc_get 用）。

    Returns:
        dict 含:
            content: str — 提取出的正文（失败时为 ""）
            source: "http"
            fetch_error: str | None — 失败原因
            needs_browser_fallback: bool — adapter 据此判断是否升级到浏览器
    """
    try:
        resp = _cc_get(
            url,
            session=session,
            impersonate="chrome120",
            allow_redirects=True,
            timeout=15,
        )
    except Exception as e:
        return {
            "content": "",
            "source": "http",
            "fetch_error": f"http request raised: {e!r}",
            "needs_browser_fallback": True,
        }

    if resp.status_code >= 400:
        return {
            "content": "",
            "source": "http",
            "fetch_error": f"http {resp.status_code}",
            "needs_browser_fallback": True,
        }

    ctype = (resp.headers.get("content-type") or "").lower()
    if "text/html" not in ctype and "application/xhtml" not in ctype:
        return {
            "content": "",
            "source": "http",
            "fetch_error": f"unexpected content-type: {ctype}",
            "needs_browser_fallback": True,
        }

    raw = getattr(resp, "text", "") or ""

    # Article-level 风控检测（与 fetch_article_browser 的 detect_risk 对齐，
    # 但跳过 DOM 层 —— 我们没有 page，只有 raw HTML + Response）。
    final_url = getattr(resp, "url", url) or url
    risk = (
        detect_risk_by_url(final_url)
        or detect_risk_by_http(resp)
        or detect_risk_by_text(raw)
    )
    if risk is not None:
        return {
            "content": "",
            "source": "http",
            "fetch_error": f"百度风控：layer={risk.layer} {risk.detail}",
            "needs_browser_fallback": False,
        }

    content = _extract_readable_text(raw)
    if len(content) < _HTTP_MIN_CONTENT_CHARS:
        return {
            "content": content,
            "source": "http",
            "fetch_error": f"readable content too short ({len(content)} chars)",
            "needs_browser_fallback": True,
        }

    return {
        "content": content,
        "source": "http",
        "fetch_error": None,
        "needs_browser_fallback": False,
    }
```

- [ ] **Step 3: Verify existing tests still pass**

Run from `D:\CSM\.claude\worktrees\hopeful-elion-cff72a`:

```
cd sidecar && python -m pytest tests/test_baidu_keyword.py -x
```

Expected: ALL tests pass — these are backwards-compatible signature extensions.

- [ ] **Step 4: Commit**

```
git add csm_core/monitor/platforms/baidu_keyword.py
git commit -m "$(cat <<'EOF'
feat(monitor): thread session through resolve_baidu_link/fetch_article_http

Module-level helpers now accept optional session= kwarg that flows
into _cc_get. Backwards-compatible — default None preserves the
stateless behavior used by existing tests.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 12: Thread session through `_check_block`

**Goal:** Pass the session into the article-iteration loop.

**Files:**
- Modify: `csm_core/monitor/platforms/baidu_keyword.py`

- [ ] **Step 1: Update `_check_block` signature + propagate session**

In `csm_core/monitor/platforms/baidu_keyword.py`, find `def _check_block(` (line 740). Change its signature from:

```python
def _check_block(
    self,
    page: Any,
    links: list[dict[str, str]],
    brands: list[str],
    *,
    block: str,
    exclude_set: set[str] | None = None,
) -> list[dict[str, Any]]:
```

…to:

```python
def _check_block(
    self,
    page: Any,
    links: list[dict[str, str]],
    brands: list[str],
    *,
    block: str,
    exclude_set: set[str] | None = None,
    session: Any = None,
) -> list[dict[str, Any]]:
```

Then INSIDE the function body, find the line that says:

```python
href = resolve_baidu_link(link["href"])
```

…and change to:

```python
href = resolve_baidu_link(link["href"], session=session)
```

Then find the line that says:

```python
attempt = fetch_article_http(href)
```

…and change to:

```python
attempt = fetch_article_http(href, session=session)
```

(The `fetch_article_browser` call stays as-is — it uses the patchright page, not curl_cffi.)

- [ ] **Step 2: Verify existing tests still pass**

Run from `D:\CSM\.claude\worktrees\hopeful-elion-cff72a`:

```
cd sidecar && python -m pytest tests/test_baidu_keyword.py -x
```

Expected: ALL tests pass — `session=None` default means existing callers see no change.

- [ ] **Step 3: Commit**

```
git add csm_core/monitor/platforms/baidu_keyword.py
git commit -m "$(cat <<'EOF'
feat(monitor): thread session through _check_block

Article iteration loop now passes session to resolve_baidu_link
and fetch_article_http. Browser-fallback path stays untouched
(patchright Page, not curl_cffi).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 13: Thread session through `_fetch_once` + `_fetch_with_promotion`

**Goal:** Propagate session from the public `fetch` entry down to `_check_block`.

**Files:**
- Modify: `csm_core/monitor/platforms/baidu_keyword.py`

- [ ] **Step 1: Update `_fetch_with_promotion` signature**

In `csm_core/monitor/platforms/baidu_keyword.py`, find `def _fetch_with_promotion(` (line 522). Change the signature from:

```python
def _fetch_with_promotion(
    self,
    task: MonitorTask,
    keywords: list[str],
    brand: str,
    headless: bool,
    progress_cb: "Callable[[int, int], None] | None" = None,
    cancel_token: Any = None,
    *,
    resume_from: int = 0,
) -> MonitorResult:
```

…to:

```python
def _fetch_with_promotion(
    self,
    task: MonitorTask,
    keywords: list[str],
    brand: str,
    headless: bool,
    progress_cb: "Callable[[int, int], None] | None" = None,
    cancel_token: Any = None,
    *,
    resume_from: int = 0,
    session: Any = None,
) -> MonitorResult:
```

Then INSIDE its body, find the call to `self._fetch_once(...)` and add `session=session`:

```python
result = self._fetch_once(
    task, keywords, brand, headless, progress_cb, cancel_token,
    resume_from=resume_from,
    session=session,
)
```

- [ ] **Step 2: Update `_fetch_once` signature**

In `csm_core/monitor/platforms/baidu_keyword.py`, find `def _fetch_once(` (line 563). Change the signature similarly to add `session: Any = None` after `resume_from`:

```python
def _fetch_once(
    self,
    task: MonitorTask,
    keywords: list[str],
    brand: str,
    headless: bool,
    progress_cb: "Callable[[int, int], None] | None" = None,
    cancel_token: Any = None,
    *,
    resume_from: int = 0,
    session: Any = None,
) -> MonitorResult:
```

Then INSIDE the body, find the two `self._check_block(...)` calls and add `session=session` to each. They currently look like:

```python
default_results = self._check_block(
    page, parsed["default_links"], [brand], block="default",
    exclude_set=exclude_set,
)
news_results = self._check_block(
    page, parsed["news_links"], [brand], block="news",
    exclude_set=exclude_set,
)
```

Change both to add `session=session`:

```python
default_results = self._check_block(
    page, parsed["default_links"], [brand], block="default",
    exclude_set=exclude_set,
    session=session,
)
news_results = self._check_block(
    page, parsed["news_links"], [brand], block="news",
    exclude_set=exclude_set,
    session=session,
)
```

- [ ] **Step 3: Verify existing tests still pass**

Run from `D:\CSM\.claude\worktrees\hopeful-elion-cff72a`:

```
cd sidecar && python -m pytest tests/test_baidu_keyword.py -x
```

Expected: ALL pass.

- [ ] **Step 4: Commit**

```
git add csm_core/monitor/platforms/baidu_keyword.py
git commit -m "$(cat <<'EOF'
feat(monitor): thread session through _fetch_once / _fetch_with_promotion

Pipes the optional session= kwarg from fetch() entry down through
the promotion wrapper into _check_block, where article fetches
actually use it. All defaults to None for backwards compatibility.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 14: Wire session lifecycle into `fetch()` entry (TDD)

**Goal:** Top-level `fetch(task)` calls `_get_session(task.id)` once, passes it down, and `_drop_session` in finally. This is the moment Bug 1 becomes effective end-to-end.

**Files:**
- Modify: `csm_core/monitor/platforms/baidu_keyword.py`
- Modify: `sidecar/tests/test_baidu_keyword.py`

- [ ] **Step 1: Write the failing tests**

Append to `sidecar/tests/test_baidu_keyword.py`:

```python
# ── fetch() session lifecycle ──────────────────────────────────────────


def test_fetch_drops_session_on_normal_return(monkeypatch):
    """正常完成时 fetch() 在 finally 里释放 session（_http_sessions 不留残)."""
    from csm_core.monitor.platforms import baidu_keyword
    from csm_core.monitor.base import MonitorTask, MonitorResult
    from datetime import datetime

    adapter = baidu_keyword.BaiduKeywordAdapter()
    adapter.apply_settings(default_excluded_domains=())

    # Short-circuit fetch's heavy path: return a MonitorResult immediately
    # from _fetch_with_promotion. We're only verifying the session-cleanup
    # contract here, not the full SERP pipeline.
    captured: dict[str, Any] = {}

    def fake_promotion(self, task, keywords, brand, headless, progress_cb, cancel_token,
                       *, resume_from, session):
        captured["session"] = session
        captured["task_id"] = task.id
        return MonitorResult(
            task_id=task.id or 0,
            checked_at=datetime.utcnow(),
            status="ok", rank=1, metric={},
        )

    monkeypatch.setattr(
        baidu_keyword.BaiduKeywordAdapter,
        "_fetch_with_promotion",
        fake_promotion,
    )
    # Bypass curl_cffi by stubbing _get_session to a sentinel
    sentinel = object()
    monkeypatch.setattr(
        baidu_keyword.BaiduKeywordAdapter,
        "_get_session",
        lambda self, tid: sentinel,
    )
    drops: list[int] = []
    monkeypatch.setattr(
        baidu_keyword.BaiduKeywordAdapter,
        "_drop_session",
        lambda self, tid: drops.append(tid),
    )

    task = MonitorTask(
        id=101, type="baidu_keyword", name="t",
        target_url="https://www.baidu.com/s?wd=x",
        config={"search_keywords": ["x"], "target_brand": "y"},
    )
    result = adapter.fetch(task)
    assert result.status == "ok"
    assert captured["session"] is sentinel
    assert drops == [101]


def test_fetch_drops_session_on_risk_control(monkeypatch):
    """RiskControlException 时 session 也被 drop (脏 cookie 不能复用)."""
    from csm_core.monitor.platforms import baidu_keyword
    from csm_core.monitor.base import MonitorTask
    from csm_core.monitor.drivers.risk_detector import (
        RiskControlException, RiskSignal,
    )

    adapter = baidu_keyword.BaiduKeywordAdapter()
    adapter.apply_settings(default_excluded_domains=())

    def fake_promotion(self, task, keywords, brand, headless, progress_cb, cancel_token,
                       *, resume_from, session):
        raise RiskControlException(
            RiskSignal(layer="url", detail="wappass triggered"), progress=2,
        )

    monkeypatch.setattr(
        baidu_keyword.BaiduKeywordAdapter,
        "_fetch_with_promotion",
        fake_promotion,
    )
    monkeypatch.setattr(
        baidu_keyword.BaiduKeywordAdapter,
        "_get_session",
        lambda self, tid: object(),
    )
    drops: list[int] = []
    monkeypatch.setattr(
        baidu_keyword.BaiduKeywordAdapter,
        "_drop_session",
        lambda self, tid: drops.append(tid),
    )

    task = MonitorTask(
        id=202, type="baidu_keyword", name="t",
        target_url="https://www.baidu.com/s?wd=x",
        config={"search_keywords": ["x"], "target_brand": "y"},
    )
    import pytest
    with pytest.raises(RiskControlException):
        adapter.fetch(task)
    assert drops == [202], "session should be dropped even when RiskControlException propagates"
```

- [ ] **Step 2: Run the new tests to see them fail**

Run from `D:\CSM\.claude\worktrees\hopeful-elion-cff72a`:

```
cd sidecar && python -m pytest tests/test_baidu_keyword.py::test_fetch_drops_session_on_normal_return tests/test_baidu_keyword.py::test_fetch_drops_session_on_risk_control -v
```

Expected: both FAIL. Likely failure mode: `TypeError: _fetch_with_promotion() got an unexpected keyword argument 'session'` (because fetch doesn't yet pass session) OR `assert drops == [101]` fails because finally doesn't drop yet.

- [ ] **Step 3: Update `fetch()` to manage session lifecycle**

In `csm_core/monitor/platforms/baidu_keyword.py`, find `def fetch(` (line 457). Replace the existing body — the current body ends with:

```python
return self._fetch_with_promotion(
    task, keywords, brand, headless, progress_cb, cancel_token,
    resume_from=resume_from,
)
```

…wrap that call in try/finally and pass session. The full updated method becomes:

```python
def fetch(
    self,
    task: MonitorTask,
    *,
    progress_cb: "Callable[[int, int], None] | None" = None,
    cancel_token: Any = None,
    resume_from: int = 0,
) -> MonitorResult:
    """Run one round of SERP scraping for all configured keywords.

    ``progress_cb(current, total)`` is called after each keyword
    completes so the UI can render a "N / M" progress bar live.
    ``current`` starts at 1 (after first keyword done) and ends at
    ``total``; the loop publishes (0, total) once up front so the bar
    shows the total count immediately on start.

    ``cancel_token`` is a duck-typed object exposing ``is_set() -> bool``
    (we accept ``threading.Event`` from the sidecar; ``None`` skips
    cancellation entirely so unit tests don't need to fake it).

    ``resume_from`` — 0-based index of the first keyword to scrape.

    Session lifecycle: a per-task curl_cffi.Session is created up-front
    (warm-up GET baidu.com seeds BAIDUID baseline cookies), threaded
    through _fetch_with_promotion → _fetch_once → _check_block →
    fetch_article_http / resolve_baidu_link, and ALWAYS dropped in
    finally — both on normal completion (don't accumulate request-count
    signal that bots get flagged for) and on RiskControlException
    (dirty cookies that already triggered captcha must not be reused).
    ``_drop_session`` is idempotent (uses dict.pop with default).
    """
    breaker = rate_limit.get_breaker(self.platform)
    if not breaker.allow():
        return MonitorResult(
            task_id=task.id or 0,
            checked_at=datetime.utcnow(),
            status="risk_control",
            rank=-1,
            error_message="circuit breaker open for baidu_keyword",
        )

    cfg = task.config or {}
    keywords_raw = cfg.get("search_keywords") or []
    keywords = [k.strip() for k in keywords_raw if k and k.strip()]
    brand = (cfg.get("target_brand") or "").strip()

    if not keywords or not brand:
        return MonitorResult(
            task_id=task.id or 0,
            checked_at=datetime.utcnow(),
            status="failed",
            rank=-1,
            error_message="config.search_keywords (non-empty list) + target_brand required",
        )

    headless = bool(cfg.get("headless", self._headless_default))
    rate_limit.get_pacer(self.platform).wait()

    # Clamp resume_from to valid range so callers don't need to guard.
    resume_from = max(0, min(int(resume_from), len(keywords)))

    session = self._get_session(task.id or 0)
    try:
        return self._fetch_with_promotion(
            task, keywords, brand, headless, progress_cb, cancel_token,
            resume_from=resume_from,
            session=session,
        )
    finally:
        # Drop on every exit path (normal return / RiskControlException /
        # any other adapter exception). Idempotent so even if something
        # downstream already called _drop_session, this is safe.
        self._drop_session(task.id or 0)
```

- [ ] **Step 4: Run the new tests to verify they pass**

Run from `D:\CSM\.claude\worktrees\hopeful-elion-cff72a`:

```
cd sidecar && python -m pytest tests/test_baidu_keyword.py::test_fetch_drops_session_on_normal_return tests/test_baidu_keyword.py::test_fetch_drops_session_on_risk_control -v
```

Expected: both PASS.

- [ ] **Step 5: Run the full suite — no regressions**

Run from `D:\CSM\.claude\worktrees\hopeful-elion-cff72a`:

```
cd sidecar && python -m pytest tests/ -x
```

Expected: ALL pass.

- [ ] **Step 6: Commit**

```
git add csm_core/monitor/platforms/baidu_keyword.py sidecar/tests/test_baidu_keyword.py
git commit -m "$(cat <<'EOF'
feat(monitor): wire session lifecycle into baidu fetch() entry

fetch() now creates a per-task curl_cffi.Session up-front (warm-up
GET baidu.com to seed BAIDUID baseline cookies), threads it through
the full call chain, and unconditionally drops it in finally — both
on normal return AND when RiskControlException propagates (dirty
cookies that already triggered captcha must not be reused for the
next task).

Tests cover both lifecycle paths.

Closes the main reduction in baidu risk-control trip rate. Combined
with the Chrome sub-version UA rotation (Task 8), should drop the
"10 keywords → captcha" failure rate from ~60% to ~20%.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 15: Final regression sweep + typecheck

**Goal:** One last full-stack pass to confirm nothing slipped.

- [ ] **Step 1: Backend full suite**

Run from `D:\CSM\.claude\worktrees\hopeful-elion-cff72a`:

```
cd sidecar && python -m pytest tests/ -v
```

Expected: every test passes (the existing suite plus the new ~7 tests added in Tasks 4, 9, 14).

- [ ] **Step 2: Frontend typecheck**

Run from `D:\CSM\.claude\worktrees\hopeful-elion-cff72a`:

```
cd frontend && npm run typecheck
```

Expected: clean (or no NEW errors beyond pre-existing ones from prior work; document any pre-existing in a comment if asked).

- [ ] **Step 3: Frontend build smoke**

Run from `D:\CSM\.claude\worktrees\hopeful-elion-cff72a`:

```
cd frontend && npm run build
```

Expected: build succeeds.

- [ ] **Step 4: If everything's green, this is the last commit**

Nothing to commit at this point if Tasks 1-14 each committed cleanly. Skip this step.

If pytest / typecheck flagged anything not caught earlier, fix in a final commit:

```
git add <files>
git commit -m "fix(monitor): address regression caught in final sweep

<short description>

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
"
```

---

## Implementation Notes

### Test conventions

- All new pytest tests live next to existing baidu_keyword tests in `sidecar/tests/test_baidu_keyword.py` and route tests in `sidecar/tests/routes/test_config.py`.
- Use `monkeypatch` for swapping module-level symbols (`_cc_get`, `cc_requests.Session`, adapter methods) — this is the project's existing pattern.
- Avoid real network in unit tests; use the FakeSession pattern shown in Task 9.

### curl_cffi Session lifecycle

- Sessions are constructed lazily in `_get_session` so first-call cost is paid once per task.
- Drop on EVERY exit path (the `finally` block in `fetch()`) — long-lived sessions accumulate request-count signal that baidu uses to flag bots. Per-task lifecycle is the "real user, short session" approximation.
- The lock guards the DICT only, not the Session itself. Within one task, the Session is used by exactly one thread (the worker thread running that task in monitor_loop's executor).

### Why impersonate=chrome120 stays constant

- `impersonate` controls TLS fingerprint (JA3) and HTTP/2 settings, not the User-Agent header.
- Cross-major-version impersonate switches (chrome120 → firefox133) make the TLS-vs-UA combo MORE suspicious, not less.
- Best practice is "stable TLS fingerprint, rotating UA header within the same browser family".

### Why per-task session, not per-request session?

- Cookies persist across same-task article fetches → looks like a human browsing a SERP and clicking through results.
- Cookies don't persist across tasks → no single cookie accumulates a suspicious request count over many SERPs.
- This is the bilibili_comment battle-tested pattern (see `csm_core/monitor/platforms/bilibili_comment.py` lines 60-66 for reference).

### Why per-task session, not adapter-singleton session?

- Singleton session accumulates request signal until baidu flags it; you'd need extra logic to detect and rotate.
- Per-task is simpler: drop on task end, no rotation logic needed.

### Hot-reload not covered by reconfigure

- `MonitorLoop.__init__` reads `alert_top_n` and `alert_cooldown_hours` once. Changes to these still require sidecar restart. This is acceptable — alert thresholds aren't high-frequency edits.
- The spec section 4.5 explicitly accepts this trade-off. Future work could push these into a setter on MonitorLoop.

### Lazy import in patch_config (Task 3)

- `monitor_lifecycle` imports `config_service` at module load. If `routes/config.py` imports `monitor_lifecycle` at module load, you get a circular dep that may resolve in different orders during boot.
- Lazy import inside the handler runs after the boot dance has settled — guaranteed safe.

### Spec-coverage cross-check

| Spec section | Plan task(s) |
|---|---|
| §4.2 `_apply_runtime_settings` | Task 1 |
| §4.2 `start()` updated | Task 1 (step 4) |
| §4.2 `reconfigure(cfg)` | Task 2 |
| §4.3 `patch_config` calls reconfigure | Task 3 |
| §4.4 reconfigure tests (3 cases) | Task 4 |
| §5.2.1 button next to toggle | Task 7 (step 1) |
| §5.2.2 script setup state | Task 6 |
| §5.2.3 popover modal | Task 7 (step 2) |
| §5.2.4 hint text | Task 7 (step 3) |
| §5.3 SettingsView anchor | Task 5 |
| §6.2.1 `_UA_POOL` | Task 8 (step 1) |
| §6.2.2 init session state | Task 8 (step 2) |
| §6.2.3 `_get_session` / `_drop_session` | Task 9 |
| §6.2.4 `_cc_get` session= | Task 10 |
| §6.2.5 helpers thread session | Task 11 |
| §6.2.6 `fetch` try/finally drop | Tasks 12, 13, 14 |
| §6.3 5 new tests | Tasks 9 (4 tests) + 14 (2 tests) — covers ua rotation, per-task cache, warmup tolerance, drop idempotency, drop on risk |
