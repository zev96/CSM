# Baidu Persistent Browser Profile Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the per-fetch "real incognito" patchright session with a CSM-owned persistent `launch_persistent_context` profile, add simulated real-user search flow (home → fill → click), enforce baidu concurrency=1, and add a profile-reset UI escape hatch — to drop the keyword-#0 risk-control trip rate observed in real testing.

**Architecture:** Section A migrates `incognito_session.py` → `baidu_browser.py` with `launch_persistent_context` pointing at `<config_dir>/baidu_browser_profile`. Section B replaces `page.goto(serp_url)` in `_fetch_once` with `_navigate_to_serp(page, kw, is_first_keyword)` which simulates real-user input. Section C uses the existing `rate_limit.configure_concurrency` to force baidu serial. Section D adds a Settings reset button + POST route. Section E adds startup profile-health log.

**Tech Stack:** Python 3.11 + patchright (Chromium stealth fork) + FastAPI sidecar + Vue 3 frontend + pytest.

**Reference spec:** [docs/superpowers/specs/2026-05-19-baidu-persistent-browser-design.md](../specs/2026-05-19-baidu-persistent-browser-design.md)

---

## File Structure

| File | Status | Responsibility |
|---|---|---|
| `csm_core/monitor/drivers/incognito_session.py` | **Rename → `baidu_browser.py`** | Persistent BrowserContext lifecycle, profile path resolution, profile reset, health log |
| `csm_core/monitor/platforms/baidu_keyword.py` | Modify | Use new `baidu_browser_session` import; add `_random_dwell_ms` + `_navigate_to_serp`; replace `page.goto(serp_url)` in `_fetch_once`; call `rate_limit.configure_concurrency` in `apply_settings` |
| `sidecar/csm_sidecar/services/monitor_loop.py` | Modify | Add `has_active_baidu_task() -> bool` method using existing `get_active_task_ids()` + `storage.get_task` |
| `sidecar/csm_sidecar/routes/monitor.py` | Modify | Add `POST /api/monitor/baidu/reset-profile` route |
| `frontend/src/views/SettingsView.vue` | Modify | Add reset SettingsRow + `confirmResetBaiduProfile` handler |
| `sidecar/tests/test_incognito_session.py` | **Rename → `test_baidu_browser.py`** | Update fakes from `launch + new_context` to `launch_persistent_context` |
| `sidecar/tests/test_baidu_keyword.py` | Modify | Add 2 tests for `_navigate_to_serp` first/subsequent paths |
| `sidecar/tests/routes/test_monitor.py` | Create or Modify | Add 2 tests for `reset_profile` route (409 / 204) |

`csm_core/browser_infra/rate_limit.py` — **no changes needed**. It already exposes `configure_concurrency(platform, max_in_flight)` (line 39); the spec's "set_max_concurrent" is just naming. We use the existing function.

---

## Section A — Persistent Context

### Task 1: Create `baidu_browser.py` (rename + rewrite)

**Files:**
- Rename: `csm_core/monitor/drivers/incognito_session.py` → `csm_core/monitor/drivers/baidu_browser.py`
- Rename: `sidecar/tests/test_incognito_session.py` → `sidecar/tests/test_baidu_browser.py`

This task only handles the file move and the new contextmanager body. Updating the caller in `baidu_keyword.py` is Task 3.

- [ ] **Step 1: Rename source and test files via git**

From `D:\CSM\.claude\worktrees\hopeful-elion-cff72a`:

```bash
git mv csm_core/monitor/drivers/incognito_session.py csm_core/monitor/drivers/baidu_browser.py
git mv sidecar/tests/test_incognito_session.py sidecar/tests/test_baidu_browser.py
```

If the test file doesn't exist, skip its rename; we'll create it in Task 2.

- [ ] **Step 2: Replace `baidu_browser.py` content**

Overwrite `csm_core/monitor/drivers/baidu_browser.py` with:

```python
"""百度 adapter 专用：持久 BrowserContext（CSM 自有 profile）。

替代原 incognito_session 的"真无痕每次冷启"模式。改用 patchright 的
launch_persistent_context + 我们自己的 user_data_dir，让 BAIDUID /
BIDUPSID cookie 跨 task 累积 —— 这是把百度风控从「keyword #0 就 403」
拉回去的核心。

profile lock：同一时刻只能一个 instance 持有同一 user_data_dir。由
rate_limit.configure_concurrency(baidu_keyword, 1) 强制百度任务串行
保证。

线程模型：每次调用都在调用者线程内启动 sync_playwright 并在同线程关闭。
不跨线程共享 handle —— monitor_loop 的 ThreadPoolExecutor 每个 task 在
单线程内完整跑完 fetch，没有 cross-thread 风险。
"""
from __future__ import annotations

import logging
import shutil
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from .patchright_pool import ensure_browsers_path

logger = logging.getLogger(__name__)


def _sync_playwright() -> Any:
    """Indirection 给单测 monkeypatch 用，避开真启 Chromium。"""
    from patchright.sync_api import sync_playwright
    return sync_playwright()


@dataclass
class BaiduBrowserSession:
    """一次 fetch 用的 patchright 资源句柄。

    与原 IncognitoSession 的区别：persistent context 没有独立 browser
    handle（launch_persistent_context 把 launch+new_context 融合成一个
    调用），所以只暴露 page / context / pw。
    """
    page: Any
    context: Any
    pw: Any


@contextmanager
def baidu_browser_session(
    *, headless: bool, user_data_dir: Path | None = None
) -> Iterator[BaiduBrowserSession]:
    """启动百度抓取专用的持久 BrowserContext。

    与原 incognito_session 的核心区别：
    - launch_persistent_context 直接返回 BrowserContext（不需要 launch +
      new_context 两步）
    - context.close() 时 cookies / localStorage / indexedDB 落盘到
      user_data_dir，不删
    - 同一时刻只能 1 个 instance 用同一 user_data_dir（OS 层 lock；并发
      限制由 rate_limit.configure_concurrency 保证）

    Args:
        headless: True → 后台跑；False → 弹可见窗口（验证码升级用）。
                  注：patchright stealth fork 不能真正 honor headless=True，
                  所以始终 headed + 推屏外（沿用原 incognito_session 的策略）。
        user_data_dir: 默认 <config_dir>/baidu_browser_profile。

    Yields:
        BaiduBrowserSession，含 .page / .context / .pw 给 adapter 用。

    Raises:
        RuntimeError: patchright 未安装、Chromium 启动失败。
    """
    ensure_browsers_path()
    target_dir = user_data_dir or _default_user_data_dir()
    target_dir.mkdir(parents=True, exist_ok=True)

    pw = None
    context = None
    try:
        pw = _sync_playwright().start()

        # ── Launch flags（沿用原 incognito_session 的策略） ────────────
        launch_args: list[str] = [
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--window-size=1366,768",
            "--blink-settings=imagesEnabled=false",
        ]
        effective_headless = headless
        if headless:
            # 始终以 headed 启动（stealth 才能工作），位置推到屏外。
            launch_args.extend([
                "--window-position=-32000,-32000",
                "--start-minimized",
            ])
            effective_headless = False

        context = pw.chromium.launch_persistent_context(
            user_data_dir=str(target_dir),
            headless=effective_headless,
            args=launch_args,
            viewport={"width": 1366, "height": 768},
        )
        # persistent context 通常已有 default page；若是首次冷启 / 没有则新建
        page = context.pages[0] if context.pages else context.new_page()

        # 健康度日志 —— 失败不阻塞 fetch（Section E）
        _log_profile_health(context, target_dir)

        yield BaiduBrowserSession(page=page, context=context, pw=pw)
    finally:
        # LIFO 关闭。context.close() 时 cookies 自动落盘 user_data_dir。
        if context is not None:
            try:
                context.close()
            except Exception as e:
                logger.debug("baidu context.close raised: %s", e)
        if pw is not None:
            try:
                pw.stop()
            except Exception as e:
                logger.debug("baidu pw.stop raised: %s", e)


def _default_user_data_dir() -> Path:
    """<config_dir>/baidu_browser_profile —— 跟 monitor.db 同目录。"""
    from csm_sidecar.services import config_service
    return config_service.get_path().parent / "baidu_browser_profile"


def reset_profile(user_data_dir: Path | None = None) -> None:
    """删整个 profile 目录。下次 baidu_browser_session 启动会冷建。

    给「重置按钮」用（routes/monitor.py 路由调用）。caller 负责确认无 active
    baidu task —— 否则会破坏正在运行的 profile 写入。
    """
    target = user_data_dir or _default_user_data_dir()
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)
        logger.info("baidu profile reset: %s", target)


def _log_profile_health(context: Any, user_data_dir: Path) -> None:
    """启动后打 1 行 log 标记 profile 状态。fail-soft：任何异常吞掉，
    profile health 日志失败不能阻塞 fetch。

    示例输出：
        baidu profile health: fresh=False, cookies=12, has_BAIDUID=True, path=C:/.../baidu_browser_profile
    """
    try:
        cookies = context.cookies("https://www.baidu.com/")
        has_baiduid = any(c.get("name") == "BAIDUID" for c in cookies)
        # patchright 第一次启动后会建 Default 子目录写 cookie；不存在 = fresh
        is_fresh = not (user_data_dir / "Default").exists()
        logger.info(
            "baidu profile health: fresh=%s, cookies=%d, has_BAIDUID=%s, path=%s",
            is_fresh, len(cookies), has_baiduid, user_data_dir,
        )
    except Exception as e:
        logger.debug("profile health log failed (non-fatal): %s", e)
```

- [ ] **Step 3: Verify file imports cleanly**

From `D:\CSM\.claude\worktrees\hopeful-elion-cff72a`:

```bash
python -c "from csm_core.monitor.drivers.baidu_browser import baidu_browser_session, reset_profile; print(baidu_browser_session, reset_profile)"
```

Expected: prints `<function baidu_browser_session at 0x...> <function reset_profile at 0x...>`

- [ ] **Step 4: Commit (without caller update yet)**

```bash
git add csm_core/monitor/drivers/baidu_browser.py
git rm csm_core/monitor/drivers/incognito_session.py 2>/dev/null || true
git commit -m "$(cat <<'EOF'
refactor(monitor): rename incognito_session.py -> baidu_browser.py + persistent_context

Replaces the per-fetch "real incognito" model (launch + new_context with
temp user_data_dir) with persistent_context pointed at CSM's own
user_data_dir (<config_dir>/baidu_browser_profile). Cookies / localStorage /
indexedDB persist across tasks so BAIDUID + BIDUPSID baseline accumulates.

Caller in baidu_keyword.py still imports the old path — wired in next
commit. Tests rewritten next commit too.

profile lock: only one instance can hold the user_data_dir at a time.
rate_limit.configure_concurrency(baidu_keyword, 1) (Section C) enforces
serial baidu task execution to honor that lock.

Also includes reset_profile() helper for Section D's UI escape hatch and
_log_profile_health() for Section E ops diagnosis.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

Note: if `git rm` says the file is already gone (because `git mv` already removed it in Step 1), that's fine — the `|| true` handles it.

---

### Task 2: Rewrite test file for new API

**Files:**
- Modify: `sidecar/tests/test_baidu_browser.py`

If Task 1's rename moved an existing test file, this task rewrites it. If no existing test file, this task creates it from scratch.

- [ ] **Step 1: Inspect what tests exist**

```bash
ls sidecar/tests/test_baidu_browser.py 2>/dev/null && cat sidecar/tests/test_baidu_browser.py | head -30
```

If the file exists and has tests using `incognito_session` / `pw.chromium.launch().new_context()`, these tests are now broken and need rewriting. If the file doesn't exist, skip Step 2 and go to Step 3.

- [ ] **Step 2: If file exists, snapshot what it tested**

Read the existing file fully. Note the test function names — the new tests should cover the same scenarios but with `launch_persistent_context` semantics.

- [ ] **Step 3: Write new test file**

Overwrite `sidecar/tests/test_baidu_browser.py` with:

```python
"""Tests for baidu_browser.baidu_browser_session — persistent BrowserContext
contextmanager that replaces the old incognito_session.

These tests use monkey-patched fake playwright handles to avoid real
Chromium startup. The fakes mirror only the surface baidu_browser_session
actually uses.
"""
from __future__ import annotations

from typing import Any
from pathlib import Path

import pytest


# ── Fakes ──────────────────────────────────────────────────────────────


class FakeContext:
    """Stand-in for patchright BrowserContext returned by
    launch_persistent_context. Records calls for assertions."""

    def __init__(self):
        self.pages: list[Any] = []
        self.close_called = False
        self._cookies_returned: list[dict[str, Any]] = []

    def new_page(self):
        page = object()
        self.pages.append(page)
        return page

    def close(self):
        self.close_called = True

    def cookies(self, url=None):
        return list(self._cookies_returned)


class FakeChromium:
    def __init__(self):
        self.last_user_data_dir: str | None = None
        self.last_kwargs: dict[str, Any] = {}
        self.context = FakeContext()

    def launch_persistent_context(self, user_data_dir, **kwargs):
        self.last_user_data_dir = user_data_dir
        self.last_kwargs = kwargs
        return self.context


class FakePW:
    def __init__(self):
        self.chromium = FakeChromium()
        self.stop_called = False

    def stop(self):
        self.stop_called = True


class FakeSyncPW:
    def __init__(self, pw: FakePW):
        self._pw = pw

    def start(self):
        return self._pw


@pytest.fixture
def fake_pw(monkeypatch):
    """Provide a FakePW, wire baidu_browser to use it."""
    from csm_core.monitor.drivers import baidu_browser

    pw = FakePW()
    monkeypatch.setattr(baidu_browser, "_sync_playwright", lambda: FakeSyncPW(pw))
    monkeypatch.setattr(baidu_browser, "ensure_browsers_path", lambda: None)
    return pw


# ── Tests ──────────────────────────────────────────────────────────────


def test_baidu_browser_session_uses_persistent_context(fake_pw, tmp_path):
    """Confirms launch_persistent_context is called with our user_data_dir
    + the stealth-required args (headed, viewport, image-disabled blink flag)."""
    from csm_core.monitor.drivers import baidu_browser

    user_dir = tmp_path / "profile"
    with baidu_browser.baidu_browser_session(headless=True, user_data_dir=user_dir) as sess:
        assert sess.page is not None
        assert sess.context is fake_pw.chromium.context

    chromium = fake_pw.chromium
    assert chromium.last_user_data_dir == str(user_dir)
    # headless=True is downgraded to headed because stealth needs headed
    assert chromium.last_kwargs["headless"] is False
    # viewport is propagated
    assert chromium.last_kwargs["viewport"] == {"width": 1366, "height": 768}
    # launch flags include the off-screen + minimized + image-disabled stealth tricks
    args = chromium.last_kwargs["args"]
    assert "--window-position=-32000,-32000" in args
    assert "--start-minimized" in args
    assert "--blink-settings=imagesEnabled=false" in args


def test_baidu_browser_session_closes_on_exit(fake_pw, tmp_path):
    """Verifies context.close + pw.stop run in the finally clause."""
    from csm_core.monitor.drivers import baidu_browser

    with baidu_browser.baidu_browser_session(headless=True, user_data_dir=tmp_path / "p"):
        pass

    assert fake_pw.chromium.context.close_called is True
    assert fake_pw.stop_called is True


def test_baidu_browser_session_creates_dir_if_missing(fake_pw, tmp_path):
    """user_data_dir is auto-created on first use (mkdir -p)."""
    from csm_core.monitor.drivers import baidu_browser

    target = tmp_path / "not_yet_created" / "profile"
    assert not target.exists()

    with baidu_browser.baidu_browser_session(headless=True, user_data_dir=target):
        pass

    assert target.exists()


def test_reset_profile_removes_dir(tmp_path):
    """reset_profile deletes the entire user_data_dir."""
    from csm_core.monitor.drivers import baidu_browser

    profile = tmp_path / "profile"
    profile.mkdir()
    (profile / "Default").mkdir()
    (profile / "Default" / "Cookies").write_text("fake cookie data")

    baidu_browser.reset_profile(user_data_dir=profile)

    assert not profile.exists()


def test_reset_profile_idempotent_on_missing_dir(tmp_path):
    """reset_profile is safe when called on a non-existent dir."""
    from csm_core.monitor.drivers import baidu_browser

    target = tmp_path / "does_not_exist"
    # Must not raise
    baidu_browser.reset_profile(user_data_dir=target)
    assert not target.exists()


def test_log_profile_health_fail_soft(fake_pw, tmp_path, caplog):
    """If context.cookies raises, baidu_browser_session still works.
    The log is non-fatal."""
    from csm_core.monitor.drivers import baidu_browser

    # Make cookies() raise so _log_profile_health hits the except branch
    def boom(url=None):
        raise RuntimeError("simulated cookie-jar error")
    fake_pw.chromium.context.cookies = boom

    # Should NOT raise
    with caplog.at_level("DEBUG", logger="csm_core.monitor.drivers.baidu_browser"):
        with baidu_browser.baidu_browser_session(headless=True, user_data_dir=tmp_path / "p"):
            pass

    assert "profile health log failed" in caplog.text
```

- [ ] **Step 4: Run the new tests**

```bash
cd sidecar && python -m pytest tests/test_baidu_browser.py -v
```

Expected: all 6 tests PASS.

If any fail because the `BaiduBrowserSession` field names or function signatures differ from what Task 1 wrote, fix the test to match Task 1's actual code — the implementation in Task 1 is canonical.

- [ ] **Step 5: Commit**

```bash
git add sidecar/tests/test_baidu_browser.py
git rm sidecar/tests/test_incognito_session.py 2>/dev/null || true
git commit -m "$(cat <<'EOF'
test(monitor): rewrite incognito_session tests for persistent_context

Replaces the launch + new_context fakes with launch_persistent_context
fakes. Six tests cover: stealth args propagation, close-on-exit,
auto-mkdir of user_data_dir, reset_profile happy path + idempotency,
fail-soft health log.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Update `baidu_keyword.py` caller to use new module

**Files:**
- Modify: `csm_core/monitor/platforms/baidu_keyword.py` lines 28 (import) and ~607 (call site)

- [ ] **Step 1: Update import**

In `csm_core/monitor/platforms/baidu_keyword.py`, find the existing import:

```python
from ..drivers.incognito_session import incognito_session
```

Change to:

```python
from ..drivers.baidu_browser import baidu_browser_session
```

- [ ] **Step 2: Update call site in `_fetch_once`**

Find the line:

```python
with incognito_session(headless=headless) as session:
```

Change to:

```python
with baidu_browser_session(headless=headless) as session:
```

The `session.page` access on the next line stays the same — `BaiduBrowserSession` and the old `IncognitoSession` both expose `page`.

- [ ] **Step 3: Verify file still imports**

```bash
python -c "from csm_core.monitor.platforms.baidu_keyword import BaiduKeywordAdapter; print(BaiduKeywordAdapter)"
```

Expected: prints `<class 'csm_core.monitor.platforms.baidu_keyword.BaiduKeywordAdapter'>`

- [ ] **Step 4: Run baidu_keyword tests + new baidu_browser tests**

```bash
cd sidecar && python -m pytest tests/test_baidu_keyword.py tests/test_baidu_browser.py -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add csm_core/monitor/platforms/baidu_keyword.py
git commit -m "$(cat <<'EOF'
feat(monitor): point baidu_keyword adapter at baidu_browser_session

Two-line swap: import + call site in _fetch_once. The new
baidu_browser_session yields a BaiduBrowserSession with .page exposed
just like the old IncognitoSession, so the adapter body is unchanged
beyond the with-statement.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Section B — Real-User Search Flow

### Task 4: Add `_random_dwell_ms` + `_navigate_to_serp` (TDD)

**Files:**
- Modify: `csm_core/monitor/platforms/baidu_keyword.py` (add module-level helpers)
- Modify: `sidecar/tests/test_baidu_keyword.py` (append 2 new tests)

- [ ] **Step 1: Write failing tests first**

Append to `sidecar/tests/test_baidu_keyword.py`:

```python
# ── _navigate_to_serp / _random_dwell_ms ───────────────────────────────


def test_navigate_to_serp_first_keyword_goes_home(monkeypatch):
    """First keyword: goto baidu.com home → fill kw → click su.

    Verifies the full real-user simulation flow runs for is_first_keyword=True.
    """
    from csm_core.monitor.platforms import baidu_keyword

    calls: list[tuple[str, Any]] = []

    class FakeNavInfo:
        @property
        def value(self):
            return "fake-response"

    class FakeNavCtx:
        def __enter__(self):
            return FakeNavInfo()
        def __exit__(self, *a):
            return False

    class FakePage:
        def goto(self, url, **kwargs):
            calls.append(("goto", url))
        def wait_for_timeout(self, ms):
            calls.append(("wait_for_timeout", ms))
        def fill(self, selector, value):
            calls.append(("fill", (selector, value)))
        def click(self, selector):
            calls.append(("click", selector))
        def expect_navigation(self, **kwargs):
            calls.append(("expect_navigation", kwargs))
            return FakeNavCtx()

    response = baidu_keyword._navigate_to_serp(
        FakePage(), keyword="吸尘器", is_first_keyword=True,
    )

    assert response == "fake-response"
    # Required ordering: home goto comes FIRST
    op_names = [c[0] for c in calls]
    assert op_names[0] == "goto"
    assert "baidu.com" in calls[0][1]
    # Then a wait (dwell)
    assert "wait_for_timeout" in op_names[:3]
    # Then fill with the keyword
    fill_call = next(c for c in calls if c[0] == "fill")
    assert fill_call[1] == ("input#kw", "吸尘器")
    # Then expect_navigation wrapping click on input#su
    assert ("click", "input#su") in calls
    assert ("expect_navigation",) in [(c[0],) for c in calls]


def test_navigate_to_serp_subsequent_keyword_skips_home(monkeypatch):
    """is_first_keyword=False: do NOT goto home; just fill + click in the
    existing SERP page's top searchbox."""
    from csm_core.monitor.platforms import baidu_keyword

    calls: list[tuple[str, Any]] = []

    class FakeNavInfo:
        @property
        def value(self):
            return "fake-response"

    class FakeNavCtx:
        def __enter__(self):
            return FakeNavInfo()
        def __exit__(self, *a):
            return False

    class FakePage:
        def goto(self, url, **kwargs):
            calls.append(("goto", url))
        def wait_for_timeout(self, ms):
            calls.append(("wait_for_timeout", ms))
        def fill(self, selector, value):
            calls.append(("fill", (selector, value)))
        def click(self, selector):
            calls.append(("click", selector))
        def expect_navigation(self, **kwargs):
            calls.append(("expect_navigation", kwargs))
            return FakeNavCtx()

    baidu_keyword._navigate_to_serp(
        FakePage(), keyword="洗碗机", is_first_keyword=False,
    )

    # NO goto should happen — we reuse the existing SERP's top searchbox
    goto_calls = [c for c in calls if c[0] == "goto"]
    assert goto_calls == [], f"expected no goto, got {goto_calls}"

    fill_call = next(c for c in calls if c[0] == "fill")
    assert fill_call[1] == ("input#kw", "洗碗机")
    assert ("click", "input#su") in calls
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd sidecar && python -m pytest tests/test_baidu_keyword.py::test_navigate_to_serp_first_keyword_goes_home tests/test_baidu_keyword.py::test_navigate_to_serp_subsequent_keyword_skips_home -v
```

Expected: both FAIL with `AttributeError: module 'csm_core.monitor.platforms.baidu_keyword' has no attribute '_navigate_to_serp'`.

- [ ] **Step 3: Implement `_random_dwell_ms` + `_navigate_to_serp`**

In `csm_core/monitor/platforms/baidu_keyword.py`, find the existing `import random` (top of file). If `random` is not yet imported, add:

```python
import random
```

near the other stdlib imports (alongside `logging`).

Then, AFTER the existing module-level helpers (`resolve_baidu_link`, `fetch_article_http`, `fetch_article_browser`) and BEFORE `class BaiduKeywordAdapter`, add:

```python
def _random_dwell_ms(*, short: bool = False) -> int:
    """模拟真人 dwell time。
    
    short=True 用于打字与点击之间（输入完到点搜索按钮，200-500ms）；
    否则用于看页面停留（800-2000ms）。
    """
    if short:
        return random.randint(200, 500)
    return random.randint(800, 2000)


def _navigate_to_serp(page: Any, keyword: str, *, is_first_keyword: bool) -> Any:
    """模拟真人搜索路径。
    
    第 1 个 keyword：完整走「goto baidu.com 首页 → wait → fill input → click search」
    后续 keyword：直接复用当前 SERP 页面的顶部搜索框（fill + click），保留
        Referer: https://www.baidu.com/s?wd=上一个词 的自然链路。
    
    Returns:
        page.expect_navigation 拿到的 Response 对象（兼容现有 detect_risk
        的入参）。
    """
    if is_first_keyword:
        # 从主页开始 —— 让 BAIDUID 被 set + Referer 自然形成
        page.goto("https://www.baidu.com/", wait_until="domcontentloaded", timeout=30000)
        # 真人会停留几百毫秒看页面
        page.wait_for_timeout(_random_dwell_ms())
    
    # 找搜索框 + 输入 keyword
    # patchright stealth 会模拟真实 keystroke 事件序列
    page.fill("input#kw", keyword)
    page.wait_for_timeout(_random_dwell_ms(short=True))
    
    # 用 expect_navigation 同步等 click 后的页面切换
    # patchright 会发真实 mousedown/mouseup/click 事件序列
    with page.expect_navigation(wait_until="domcontentloaded", timeout=45000) as nav_info:
        page.click("input#su")
    return nav_info.value
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd sidecar && python -m pytest tests/test_baidu_keyword.py::test_navigate_to_serp_first_keyword_goes_home tests/test_baidu_keyword.py::test_navigate_to_serp_subsequent_keyword_skips_home -v
```

Expected: both PASS.

- [ ] **Step 5: Run full baidu_keyword suite to verify no regressions**

```bash
cd sidecar && python -m pytest tests/test_baidu_keyword.py -x
```

Expected: all pass (new 2 tests + existing 34+).

- [ ] **Step 6: Commit**

```bash
git add csm_core/monitor/platforms/baidu_keyword.py sidecar/tests/test_baidu_keyword.py
git commit -m "$(cat <<'EOF'
feat(monitor): add _navigate_to_serp + _random_dwell_ms helpers

Two module-level helpers that simulate real-user search behavior:

- _random_dwell_ms: returns 800-2000ms (long dwell, "user looking at
  page") or 200-500ms (short, "typing-to-clicking gap")
- _navigate_to_serp: when is_first_keyword=True, goto baidu.com home
  then fill input#kw + click input#su via expect_navigation; when False,
  reuse the current SERP page's top searchbox (preserves natural
  Referer chain across keywords)

No callers yet — wiring into _fetch_once comes in the next commit.

Tests cover both first-keyword and subsequent-keyword paths.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: Replace `page.goto(serp_url)` in `_fetch_once` with `_navigate_to_serp`

**Files:**
- Modify: `csm_core/monitor/platforms/baidu_keyword.py` (the `_fetch_once` loop body around line 636-665)

- [ ] **Step 1: Find current goto block**

In `csm_core/monitor/platforms/baidu_keyword.py`, locate the part of `_fetch_once` (inside the `for rel_idx, keyword in enumerate(keywords_to_fetch):` loop) where:

```python
serp_url = "https://www.baidu.com/s?wd=" + quote(keyword)
kw_entry: dict[str, Any] = {
    "keyword": keyword,
    "serp_url": serp_url,
    ...
}

# Navigate to SERP. 45s timeout — baidu 偶尔冷启慢，20s 不够。
serp_response = None
try:
    serp_response = page.goto(serp_url, wait_until="domcontentloaded", timeout=45000)
except TypeError:
    # Test FakePage 不接受 kwargs
    serp_response = page.goto(serp_url)
except Exception as e:
    logger.warning(
        "baidu navigate failed (headless=%s, keyword=%r): %s",
        headless, keyword, e,
    )
    kw_entry["fetch_error"] = f"serp navigate raised: {e!r}"
    keyword_results.append(kw_entry)
    # 注意：page.goto 失败时不调 detect_risk —— 页面没加载，4 层信号都没意义。
    # 此 keyword 会以 fetch_error 状态记录，runner 会跳到下一个。
    continue
```

- [ ] **Step 2: Replace the navigate block**

Replace **only** the `serp_response = None / try / except / continue` block (keep `kw_entry` dict construction unchanged, keep the `keyword_results.append(kw_entry); continue` path on exception). The new block becomes:

```python
# Real-user simulation: rel_idx == 0 means first keyword in this session,
# which is also the cold-start state (page just got opened by
# baidu_browser_session). On subsequent keywords we reuse the SERP's
# top searchbox to preserve the natural Referer chain.
serp_response = None
try:
    serp_response = _navigate_to_serp(
        page, keyword, is_first_keyword=(rel_idx == 0),
    )
except TypeError:
    # FakePage (in older tests) may not implement fill / expect_navigation;
    # fall back to direct goto so unrelated tests still work.
    try:
        serp_response = page.goto(serp_url, wait_until="domcontentloaded", timeout=45000)
    except TypeError:
        serp_response = page.goto(serp_url)
except Exception as e:
    logger.warning(
        "baidu navigate failed (headless=%s, keyword=%r): %s",
        headless, keyword, e,
    )
    kw_entry["fetch_error"] = f"serp navigate raised: {e!r}"
    keyword_results.append(kw_entry)
    # 注意：_navigate_to_serp 失败时不调 detect_risk —— 页面没加载，
    # 4 层信号都没意义。此 keyword 以 fetch_error 状态记录，runner 跳到下一个。
    continue
```

The TypeError fallback handles FakePage objects in existing tests that don't implement `expect_navigation` / `fill`. New tests use proper fakes.

- [ ] **Step 3: Run full baidu_keyword suite**

```bash
cd sidecar && python -m pytest tests/test_baidu_keyword.py -v
```

Expected: all PASS (existing 34+ tests + the 2 new ones from Task 4).

If some existing tests fail because their FakePage doesn't have `fill` / `expect_navigation`, the TypeError fallback should catch them — but if not, find the test and either (a) extend its FakePage with these methods or (b) verify the TypeError fallback is being hit correctly. Per the implementation, `TypeError` catches `AttributeError`-like calls on duck-typed fakes; if a fake uses `MagicMock`, it may behave differently — adapt the fallback if needed.

- [ ] **Step 4: Commit**

```bash
git add csm_core/monitor/platforms/baidu_keyword.py
git commit -m "$(cat <<'EOF'
feat(monitor): use _navigate_to_serp in _fetch_once main loop

Replaces direct page.goto(serp_url) with real-user simulation:
first keyword goes home → fill → click; subsequent keywords reuse
the SERP top searchbox. TypeError fallback to old goto path keeps
existing FakePage-based tests working.

Together with Section A's persistent profile, this addresses the
"keyword #0 trip on first SERP" symptom observed in real testing.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Section C — Force Baidu Concurrency = 1

### Task 6: Call `rate_limit.configure_concurrency` in `apply_settings`

**Files:**
- Modify: `csm_core/monitor/platforms/baidu_keyword.py:apply_settings`

- [ ] **Step 1: Add the call**

In `csm_core/monitor/platforms/baidu_keyword.py`, find `def apply_settings(...)`. At the end of the function body (after the existing `breaker = get_breaker(self.platform)` block), append:

```python
        # persistent_context profile lock requires exclusive user_data_dir
        # access — force baidu task serial execution. The semaphore is
        # global per platform; calling this on every apply_settings is
        # idempotent (rate_limit.configure_concurrency replaces the
        # semaphore object).
        from .. import rate_limit
        rate_limit.configure_concurrency(self.platform, 1)
```

Note: there's already a local import `from ..rate_limit import get_pacer, get_breaker` inside `apply_settings`. The same `from .. import rate_limit` line is harmless because Python caches modules — but to be DRY, you can instead change the existing import line to also pull in `configure_concurrency`:

```python
        from ..rate_limit import get_pacer, get_breaker, configure_concurrency
        ...
        configure_concurrency(self.platform, 1)
```

Pick whichever style matches the file's existing convention.

- [ ] **Step 2: Add a test verifying baidu gets concurrency=1**

Append to `sidecar/tests/test_baidu_keyword.py`:

```python
def test_apply_settings_forces_baidu_concurrency_to_one():
    """persistent_context profile lock requires serial baidu execution.
    apply_settings should reconfigure rate_limit accordingly."""
    from csm_core.monitor.platforms import baidu_keyword
    from csm_core.browser_infra import rate_limit

    # Clean slate — clear any prior configuration for this platform
    with rate_limit._sem_lock:
        rate_limit._sems.pop(baidu_keyword.BaiduKeywordAdapter.platform, None)
        rate_limit._max_concurrent.pop(baidu_keyword.BaiduKeywordAdapter.platform, None)

    adapter = baidu_keyword.BaiduKeywordAdapter()
    adapter.apply_settings(default_excluded_domains=())

    assert rate_limit._max_concurrent[baidu_keyword.BaiduKeywordAdapter.platform] == 1
```

- [ ] **Step 3: Run the new test + full sidecar suite**

```bash
cd sidecar && python -m pytest tests/test_baidu_keyword.py::test_apply_settings_forces_baidu_concurrency_to_one tests/test_baidu_keyword.py -v
```

Expected: new test PASSES + no regressions.

- [ ] **Step 4: Commit**

```bash
git add csm_core/monitor/platforms/baidu_keyword.py sidecar/tests/test_baidu_keyword.py
git commit -m "$(cat <<'EOF'
feat(monitor): force baidu concurrency=1 in apply_settings

persistent_context profile lock requires exclusive user_data_dir
access — only one Chrome instance can hold the profile at a time.
apply_settings now calls rate_limit.configure_concurrency to enforce
serial execution. Without this, two parallel baidu tasks would race
on the user_data_dir lock and the second would fail to launch (or
worse, corrupt the profile).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Section D — Reset Profile UI

### Task 7: Add `has_active_baidu_task` method on `MonitorLoop`

**Files:**
- Modify: `sidecar/csm_sidecar/services/monitor_loop.py`

- [ ] **Step 1: Find existing `get_active_task_ids` method**

In `sidecar/csm_sidecar/services/monitor_loop.py`, find `def get_active_task_ids(self) -> list[int]:` (around line 198). Note that it acquires `self._active_lock` and reads `self._active_task_ids`.

- [ ] **Step 2: Add `has_active_baidu_task` after `get_active_task_ids`**

Insert immediately after `get_active_task_ids`'s method body:

```python
    def has_active_baidu_task(self) -> bool:
        """Return True if any currently-active task is type=baidu_keyword.
        
        Used by routes/monitor.py reset-profile route to avoid corrupting
        a live persistent profile mid-write. Safe to call without callers
        holding _active_lock — we take a snapshot then resolve types via
        storage.
        """
        active_ids = self.get_active_task_ids()
        if not active_ids:
            return False
        from csm_core.monitor import storage
        for tid in active_ids:
            try:
                task = storage.get_task(tid)
            except Exception:
                continue
            if task is not None and task.type == "baidu_keyword":
                return True
        return False
```

- [ ] **Step 3: Verify the file still imports**

```bash
python -c "from csm_sidecar.services.monitor_loop import MonitorLoop; print(MonitorLoop.has_active_baidu_task)"
```

Expected: prints `<function MonitorLoop.has_active_baidu_task at 0x...>`

- [ ] **Step 4: Commit**

```bash
git add sidecar/csm_sidecar/services/monitor_loop.py
git commit -m "$(cat <<'EOF'
feat(monitor): add MonitorLoop.has_active_baidu_task helper

Returns True iff any active task is type=baidu_keyword. Used by the
upcoming POST /api/monitor/baidu/reset-profile route to refuse with
409 when a baidu task is running — wiping the user_data_dir mid-write
would corrupt the live profile.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 8: Add `POST /api/monitor/baidu/reset-profile` route + tests

**Files:**
- Modify: `sidecar/csm_sidecar/routes/monitor.py`
- Modify: `sidecar/tests/routes/test_monitor.py` (or create if doesn't exist)

- [ ] **Step 1: Find the existing imports in monitor.py**

In `sidecar/csm_sidecar/routes/monitor.py`, find the imports near the top. Note where `status` from fastapi and `HTTPException` are imported, and where the `router` is defined.

- [ ] **Step 2: Add the reset route**

Add this route at a sensible spot in `sidecar/csm_sidecar/routes/monitor.py` (after task CRUD routes; near other manual-action POST routes if they exist):

```python
@router.post("/api/monitor/baidu/reset-profile", status_code=status.HTTP_204_NO_CONTENT)
async def reset_baidu_profile() -> None:
    """Delete the persistent baidu browser profile dir.

    Use case: profile has been hit by 百度风控 multiple times and cookies
    are "burnt"; rather than wait for cooldown, user wipes and starts fresh.

    Safety: refuses (409) if any baidu task is currently running — would
    corrupt the live profile mid-write.
    """
    from csm_core.monitor.drivers.baidu_browser import reset_profile
    from ..services import monitor_lifecycle

    loop = monitor_lifecycle.get()
    if loop is not None and loop.has_active_baidu_task():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="有正在运行的百度任务，先停止再重置",
        )
    reset_profile()
```

If `HTTPException` and `status` aren't already imported in monitor.py, add them:

```python
from fastapi import APIRouter, HTTPException, status
```

- [ ] **Step 3: Add route tests**

If `sidecar/tests/routes/test_monitor.py` doesn't exist, create it. Otherwise append. Add:

```python
def test_reset_baidu_profile_409_when_baidu_task_running(client):
    """If a baidu task is active, reset should refuse with 409."""
    from unittest.mock import patch
    from csm_sidecar.services import monitor_lifecycle

    fake_loop = type("L", (), {"has_active_baidu_task": lambda self: True})()
    monitor_lifecycle._loop = fake_loop  # noqa: SLF001
    try:
        with patch(
            "csm_core.monitor.drivers.baidu_browser.reset_profile"
        ) as mock_reset:
            resp = client.post("/api/monitor/baidu/reset-profile")
        assert resp.status_code == 409
        assert "百度任务" in resp.json().get("detail", "")
        mock_reset.assert_not_called()
    finally:
        monitor_lifecycle._loop = None  # noqa: SLF001


def test_reset_baidu_profile_204_when_no_baidu_task(client):
    """No active baidu task → reset_profile is called and returns 204."""
    from unittest.mock import patch
    from csm_sidecar.services import monitor_lifecycle

    fake_loop = type("L", (), {"has_active_baidu_task": lambda self: False})()
    monitor_lifecycle._loop = fake_loop  # noqa: SLF001
    try:
        with patch(
            "csm_core.monitor.drivers.baidu_browser.reset_profile"
        ) as mock_reset:
            resp = client.post("/api/monitor/baidu/reset-profile")
        assert resp.status_code == 204
        mock_reset.assert_called_once()
    finally:
        monitor_lifecycle._loop = None  # noqa: SLF001
```

These tests use the same `client` fixture pattern as the existing `sidecar/tests/routes/test_config.py` (created in the previous plan). If that fixture is at a project-level conftest or in this file's conftest, it's already available; otherwise copy the fixture from `test_config.py`.

- [ ] **Step 4: Run the new tests**

```bash
cd sidecar && python -m pytest tests/routes/test_monitor.py::test_reset_baidu_profile_409_when_baidu_task_running tests/routes/test_monitor.py::test_reset_baidu_profile_204_when_no_baidu_task -v
```

Expected: both PASS.

- [ ] **Step 5: Run the full sidecar suite for regressions**

```bash
cd sidecar && python -m pytest tests/ -x
```

Expected: all pass (pre-existing 3 failures + 3 errors OK as before).

- [ ] **Step 6: Commit**

```bash
git add sidecar/csm_sidecar/routes/monitor.py sidecar/tests/routes/test_monitor.py
git commit -m "$(cat <<'EOF'
feat(monitor): POST /api/monitor/baidu/reset-profile route

Allows the user to manually wipe the persistent baidu browser profile
when cookies are burnt (repeated risk control). Refuses with 409 if a
baidu task is currently running. Returns 204 on success.

Two tests cover both branches.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 9: Add UI reset button + handler in SettingsView

**Files:**
- Modify: `frontend/src/views/SettingsView.vue`

- [ ] **Step 1: Locate the baidu_keyword section**

Find the section in `frontend/src/views/SettingsView.vue` that contains the `default_excluded_domains` SettingsRow (the one wrapped with `<div id="baidu-default-excludes">` from the previous plan). The reset row goes AFTER that as a new sibling SettingsRow.

- [ ] **Step 2: Add the reset SettingsRow**

After the closing `</div>` of `<div id="baidu-default-excludes">`, add:

```vue
<SettingsRow
  label="重置百度浏览器 profile"
  hint="如果连续触发百度风控、cookie 已经烫坏，点这里清空浏览器数据从头来。期间不能有运行中的百度任务。"
  last
>
  <Btn variant="danger" small @click="confirmResetBaiduProfile">
    <Icon name="trash" :size="12" />
    <span>重置</span>
  </Btn>
</SettingsRow>
```

If the existing `default-excludes` SettingsRow has `last` on it, REMOVE the `last` attribute from that one (since it's no longer the last row in the section) and keep `last` on the new reset row only.

- [ ] **Step 3: Add the handler in `<script setup>`**

In `frontend/src/views/SettingsView.vue`'s `<script setup>` section, find where other handlers like `excludeDomainsModalOpen` are declared. Add:

```ts
async function confirmResetBaiduProfile() {
  if (!confirm("确认重置百度浏览器 profile？\n下次任务会冷启重建，前几次抓取可能仍触发风控（cookie 需要慢慢累积）。")) {
    return;
  }
  try {
    await sidecar.client.post("/api/monitor/baidu/reset-profile");
    toast.success("百度浏览器 profile 已重置");
  } catch (e: any) {
    const detail = e.response?.data?.detail ?? e.message ?? "未知错误";
    toast.error(`重置失败：${detail}`);
  }
}
```

Required imports / refs that should already exist in this file:
- `sidecar` (from `@/api/sidecar` or similar — check what other POST calls in this file use)
- `toast` (from `@/composables/useToast` or similar)

If these aren't yet imported, check how `excludeDomainsModalOpen` callers handle their POST — copy that pattern.

`Icon` and `Btn` components: search the file for existing `<Btn` and `<Icon name="trash"` usage. If the `trash` icon name doesn't exist in the project's icon set, pick a similar one (`delete` / `x` / `rotate-ccw` are common alternatives — grep `<Icon name=` to see what's available).

- [ ] **Step 4: Verify typecheck + build**

```bash
cd frontend && npm run typecheck
```

Expected: only the previously known errors (no new ones). The MonitorView.vue:3287 error was fixed in commit `20b46b9`, so typecheck should be CLEAN now.

```bash
cd frontend && npm run build
```

Expected: build succeeds.

- [ ] **Step 5: (Optional) Manual smoke test**

If `scripts/dev.ps1` is running: open the app → Settings → 监测 → 百度关键词. You should see a "重置百度浏览器 profile" row at the bottom with a danger-styled button. Clicking it should show the browser confirm dialog. Approving with no active baidu task → toast "百度浏览器 profile 已重置".

- [ ] **Step 6: Commit**

```bash
git add frontend/src/views/SettingsView.vue
git commit -m "$(cat <<'EOF'
feat(settings): add reset baidu browser profile button

New SettingsRow under 百度关键词 section with a danger-styled "重置"
button. Click → browser confirm → POST /api/monitor/baidu/reset-profile.
Toast success on 204, error toast on 409 (active baidu task) or other
failures.

The escape hatch for when persistent profile cookies get burnt by
repeated risk control. After reset, the next task cold-starts the
profile from scratch.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Section E — Profile Health Log

The `_log_profile_health` function is already included in Task 1's `baidu_browser.py` content, and Task 1's contextmanager already calls it before `yield`. Task 2's test `test_log_profile_health_fail_soft` already covers fail-soft behavior.

**No separate task needed.** Section E is fully covered by Tasks 1 + 2.

---

## Task 10: Final regression sweep

After all section commits are in.

- [ ] **Step 1: Backend full suite**

```bash
cd sidecar && python -m pytest tests/ -v
```

Expected: same baseline (pre-existing failures OK). All new tests pass.

- [ ] **Step 2: Frontend typecheck**

```bash
cd frontend && npm run typecheck
```

Expected: clean (zero errors).

- [ ] **Step 3: Frontend build**

```bash
cd frontend && npm run build
```

Expected: succeeds with no new errors.

- [ ] **Step 4: If anything new failed**

If a regression appears, dispatch a fix subagent or fix inline. Final commit message: `fix(monitor): address regression caught in persistent-browser final sweep`.

- [ ] **Step 5: If all green, no commit needed**

This task is a verification gate. No code changes if nothing broke.

---

## Spec-Coverage Cross-Check

| Spec section | Plan task(s) |
|---|---|
| §4.1 file rename | Task 1 (Step 1: git mv) |
| §4.2 contextmanager body | Task 1 (Step 2) |
| §4.3 caller migration | Task 3 |
| §4.4 test update | Task 2 |
| §5.1 _navigate_to_serp helpers | Task 4 |
| §5.2 _fetch_once replacement | Task 5 |
| §5.3 navigate tests | Task 4 (TDD step 1) |
| §6.1-2 force concurrency=1 | Task 6 |
| §6.3-4 concurrency UX / manual test | Manual (Task 10 step 5) |
| §7.1 reset_profile route | Task 8 |
| §7.2 SettingsView reset UI | Task 9 |
| §7.3 reset route tests | Task 8 |
| §8 health log | Task 1 (function included), Task 2 (test) |
| §9 verification | Task 10 |
| §11 YAGNI items | (negative — verified by not implementing them) |

All spec sections are covered. The `set_max_concurrent` name in the spec actually maps to the existing `rate_limit.configure_concurrency` function — no new helper needed (the plan uses the existing function directly).

---

## Implementation Notes

### Test isolation reminder

If a test mutates `monitor_lifecycle._loop` directly (as in Tasks 8's route tests), always reset it in a `try/finally`. The previous plan's `tests/routes/test_config.py` showed the pattern.

### profile lock cross-test pollution

Tests that exercise `rate_limit.configure_concurrency` could pollute later tests' semaphore state. Task 6's test clears `_sems` and `_max_concurrent` for `baidu_keyword` before running — follow that pattern if adding more rate_limit tests.

### git mv vs separate add/rm

When renaming the incognito → baidu_browser files, prefer `git mv` over delete+add — git correctly detects the rename and shows it in `git log --follow` history.

### MonitorTask.type field reference

In Task 7's `has_active_baidu_task`, we access `task.type == "baidu_keyword"`. The field name on `MonitorTask` is `type` (verified in existing usage like `baidu_keyword.py:497`). If the storage returns a dict instead of a model, use `task["type"] == "baidu_keyword"` — adapt to whatever `storage.get_task` actually returns (check `csm_core/monitor/storage.py:get_task` if unsure).

### confirm() dialog in Tauri / Vue

`window.confirm` works in Tauri webview. If the project prefers a custom modal dialog over the native browser confirm, search the codebase for `useConfirm` or `<ConfirmDialog` — match the existing pattern. The plan uses native `confirm()` for simplicity; switching to a custom dialog is a Section-D nit, not a spec violation.
