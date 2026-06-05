# Stream C — GEO/百度 RPA 浏览器移屏外 + 验证码上浮 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use `- [ ]`.
> **Commits:** Chinese `feat:` + trailer `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.
> **Tests:** these are **csm_core** modules. `python -m pytest <path> -v` from repo root (csm_core resolves to worktree, no override). EXCEPTION: `sidecar/tests/test_baidu_browser.py` lives under sidecar/ but imports only `csm_core` — it runs WITHOUT override too; but if a test you touch imports `csm_sidecar`, use `$env:PYTHONPATH="D:\CSM\.claude\worktrees\elastic-moore-fa05f4\sidecar"` in the same command. Verify the import path if unsure.

**Goal:** GEO RPA（DeepSeek/Kimi/元宝）和百度 RPA 浏览器在**采集运行时**移到屏幕外、不抢视觉；验证码/登录需人工时把窗口**上浮**到可见区，处理完移回屏外。GEO 的 `open_login`（用户主动登录）保持有头可见不变。

**⚠️ 关键背景（必读）：** 之前 `--window-position=-32000,-32000` 在本仓库**试过被回退**——屏外窗口被 Chromium 当「遮挡」暂停重绘，元素 `boundingClientRect` 报 **0×0**，搞坏 patchright fill/click（见 `sidecar/tests/test_baidu_browser.py:104-109` 的反向断言）。本方案的关键差异是**加反遮挡 flags**（`--disable-features=CalculateNativeWinOcclusion` 等）让屏外窗口继续渲染+可交互。**用户需真机验证 GEO 能提问+出答案；若仍坏 → 回退 GEO 为 headless。**

**Architecture:** 新建共享 `browser_infra/window_util.py`：`offscreen_args(hidden)`（移屏外+反遮挡 flags）+ `surface_window(page)`/`hide_window(page)`（CDP `Browser.getWindowForTarget`+`setWindowBounds`，失败回退不崩）。GEO 路径：`mining_browser.launched_page` 加 `hidden_window` 参数（**默认 False，不动 mining**），GEO 的 `rpa_page` 显式传 `hidden_window=True`。百度：`baidu_browser_session` 加 `hidden_window`（**仅在有头时**追加 offscreen args），并在 `baidu_keyword._try_human_solve` 验证码等待时 `surface_window`→`finally: hide_window`。CDP 用法本仓库零先例，属真机待验证项。

**Tech Stack:** Python (csm_core.browser_infra / monitor.drivers / monitor.platforms) + pytest（monkeypatch 假浏览器，不真起浏览器）。

---

## File Structure

| 文件 | 责任 | 改动 |
|---|---|---|
| `csm_core/browser_infra/window_util.py` | 新建 | `offscreen_args()` + `surface_window()`/`hide_window()` (CDP) |
| `csm_core/browser_infra/mining_browser.py` | GEO/mining launch | `launched_page` 加 `hidden_window=False` 参数 + 追加 offscreen_args |
| `csm_core/monitor/geo/providers/rpa/_session.py` | GEO RPA 入口 | `rpa_page` 传 `hidden_window=True` |
| `csm_core/monitor/drivers/baidu_browser.py` | 百度 launch | `baidu_browser_session` 加 `hidden_window=True`，有头时追加 offscreen_args（两模式）|
| `csm_core/monitor/platforms/baidu_keyword.py` | 百度验证码 | `_try_human_solve`（+ 文章页验证码路径）surface→finally hide |
| `tests/core/browser_infra/test_window_util.py` | 新建 | offscreen_args + surface/hide(CDP fake) |
| `tests/core/browser_infra/test_mining_browser_offscreen.py` | 新建 | launched_page args（monkeypatch）|
| `sidecar/tests/test_baidu_browser.py` | 既有 | **翻转** :108 负断言 → 有头+hidden 时断言存在 |

---

## Task 1: `window_util.py` — offscreen_args + surface/hide

**Files:** Create `csm_core/browser_infra/window_util.py`; Test `tests/core/browser_infra/test_window_util.py`

- [ ] **Step 1: 失败测试** — 新建 `tests/core/browser_infra/test_window_util.py`：
```python
from csm_core.browser_infra import window_util


def test_offscreen_args_when_hidden():
    args = window_util.offscreen_args(True)
    assert "--window-position=-32000,-32000" in args
    assert "--disable-features=CalculateNativeWinOcclusion" in args
    assert "--disable-backgrounding-occluded-windows" in args
    assert "--disable-renderer-backgrounding" in args


def test_offscreen_args_empty_when_not_hidden():
    assert window_util.offscreen_args(False) == []


class _FakeCDP:
    def __init__(self): self.sent = []
    def send(self, method, params=None):
        self.sent.append((method, params or {}))
        if method == "Browser.getWindowForTarget":
            return {"windowId": 7}
        return {}


class _FakeCtx:
    def __init__(self, cdp): self._cdp = cdp
    def new_cdp_session(self, page): return self._cdp


class _FakePage:
    def __init__(self, cdp): self.context = _FakeCtx(cdp); self._front = 0
    def bring_to_front(self): self._front += 1


def test_surface_window_moves_onscreen():
    cdp = _FakeCDP(); page = _FakePage(cdp)
    window_util.surface_window(page)
    methods = [m for m, _ in cdp.sent]
    assert "Browser.getWindowForTarget" in methods
    setb = next(p for m, p in cdp.sent if m == "Browser.setWindowBounds")
    assert setb["windowId"] == 7
    assert setb["bounds"]["left"] >= 0 and setb["bounds"]["top"] >= 0  # 可见区
    assert page._front == 1


def test_hide_window_moves_offscreen():
    cdp = _FakeCDP(); page = _FakePage(cdp)
    window_util.hide_window(page)
    setb = next(p for m, p in cdp.sent if m == "Browser.setWindowBounds")
    assert setb["bounds"]["left"] < -1000 and setb["bounds"]["top"] < -1000


def test_surface_window_swallows_cdp_error():
    class Boom:
        context = type("C", (), {"new_cdp_session": lambda self, p: (_ for _ in ()).throw(RuntimeError("no cdp"))})()
    window_util.surface_window(Boom())  # 不抛
```

- [ ] **Step 2: 跑失败** `python -m pytest tests/core/browser_infra/test_window_util.py -v` → ImportError.

- [ ] **Step 3: 实现** `csm_core/browser_infra/window_util.py`：
```python
"""RPA 浏览器「移屏外 + 运行时上浮」工具。

移屏外（采集时不抢视觉）：offscreen_args() 给 launch_persistent_context 的
args 追加 --window-position 到屏外 + 反遮挡 flags。反遮挡 flags 是关键 ——
否则 Chromium 把屏外窗口当遮挡暂停重绘，元素 boundingClientRect 报 0×0、
fill/click 失效（本仓库之前因此回退过纯 --window-position 方案）。

上浮（验证码/登录需人工时）：surface_window() 用 CDP Browser.setWindowBounds
把窗口移回可见区并 bring_to_front；hide_window() 移回屏外。CDP 失败不崩
（多屏/驱动差异时回退为「窗口留在原位」，记 warning）。
"""
from __future__ import annotations
import logging
from typing import Any

logger = logging.getLogger(__name__)

_OFFSCREEN = "-32000,-32000"
_OCCLUSION_FLAGS = [
    f"--window-position={_OFFSCREEN}",
    "--disable-features=CalculateNativeWinOcclusion",
    "--disable-backgrounding-occluded-windows",
    "--disable-renderer-backgrounding",
]


def offscreen_args(hidden: bool) -> list[str]:
    """hidden=True → 移屏外+反遮挡 flags；False → 空（不改变窗口位置）。"""
    return list(_OCCLUSION_FLAGS) if hidden else []


def _window_id(page: Any) -> tuple[Any, int]:
    cdp = page.context.new_cdp_session(page)
    wid = cdp.send("Browser.getWindowForTarget")["windowId"]
    return cdp, wid


def surface_window(page: Any) -> None:
    """把窗口移回可见区 + 置前（验证码/登录人工处理用）。CDP 失败不崩。"""
    try:
        cdp, wid = _window_id(page)
        cdp.send("Browser.setWindowBounds", {
            "windowId": wid,
            "bounds": {"left": 80, "top": 80, "width": 1100, "height": 800, "windowState": "normal"},
        })
    except Exception:
        logger.warning("surface_window 失败（CDP 不可用）；窗口可能仍在屏外", exc_info=True)
    try:
        page.bring_to_front()
    except Exception:
        pass


def hide_window(page: Any) -> None:
    """把窗口移回屏外。CDP 失败不崩。"""
    try:
        cdp, wid = _window_id(page)
        cdp.send("Browser.setWindowBounds", {
            "windowId": wid, "bounds": {"left": -32000, "top": -32000},
        })
    except Exception:
        logger.warning("hide_window 失败（CDP 不可用）", exc_info=True)
```

- [ ] **Step 4: 跑通过** `python -m pytest tests/core/browser_infra/test_window_util.py -v` → PASS. （若 `tests/core/browser_infra/` 无 `__init__.py`/conftest 导致 collection 问题，照该目录既有测试结构补；先 `ls tests/core/browser_infra/`。）

- [ ] **Step 5: 提交** `git add csm_core/browser_infra/window_util.py tests/core/browser_infra/test_window_util.py` → `feat(browser): window_util 移屏外 flags + CDP 上浮/隐藏`

---

## Task 2: GEO RPA — launched_page 移屏外

**Files:** Modify `csm_core/browser_infra/mining_browser.py`, `csm_core/monitor/geo/providers/rpa/_session.py`; Test `tests/core/browser_infra/test_mining_browser_offscreen.py`

**说明:** `launched_page` 被 GEO RPA 和 mining 搜索共用。**默认 `hidden_window=False` 不动 mining**；GEO 的 `rpa_page` 显式传 True。

- [ ] **Step 1: 失败测试** — 新建 `tests/core/browser_infra/test_mining_browser_offscreen.py`，monkeypatch 假浏览器记录 launch args（参考 `sidecar/tests/test_baidu_browser.py` 的 FakeSyncPW 风格 —— 先读它）。断言：`launched_page(platform, hidden_window=True)` 的 launch args 含 `--window-position=-32000,-32000`；`hidden_window=False`（默认）不含。需 monkeypatch `mining_browser` 里启动 playwright 的 seam（读 `launched_page` 找到它启动 pw 的调用，monkeypatch 成假的 `launch_persistent_context` 记录 kwargs["args"]）。

- [ ] **Step 2: 跑失败** → AssertionError / TypeError（hidden_window 未知参数）。

- [ ] **Step 3: 实现** — `mining_browser.py`：
  - import `from csm_core.browser_infra.window_util import offscreen_args`。
  - `launched_page` 签名加 `hidden_window: bool = False`：
    ```python
    def launched_page(platform: str, *, headless: bool = False, hidden_window: bool = False) -> Iterator[Any]:
    ```
  - `launch_args` 追加：在现有 `launch_args = ["--no-sandbox", "--disable-dev-shm-usage", "--window-size=1000,700"]` 之后加 `launch_args += offscreen_args(hidden_window)`。
  - `_session.py` `rpa_page`：把 `launched_page(f"geo_{platform}", headless=headless)` 改成 `launched_page(f"geo_{platform}", headless=headless, hidden_window=True)`。

- [ ] **Step 4: 跑通过** `python -m pytest tests/core/browser_infra/test_mining_browser_offscreen.py -v` → PASS.
- [ ] **Step 5: 提交** `git add csm_core/browser_infra/mining_browser.py csm_core/monitor/geo/providers/rpa/_session.py tests/core/browser_infra/test_mining_browser_offscreen.py` → `feat(geo): GEO RPA 浏览器采集时移屏外（mining 不变）`

---

## Task 3: 百度 launch 移屏外（两模式，有头时）

**Files:** Modify `csm_core/monitor/drivers/baidu_browser.py`; Test `sidecar/tests/test_baidu_browser.py`

- [ ] **Step 1: 改测试（翻转负断言 + 加正断言）** — `sidecar/tests/test_baidu_browser.py`：
  - 把 `:108` 的 `assert "--window-position=-32000,-32000" not in args` 改为：默认（`hidden_window` 未传或为 True）有头 self-built 模式 **应包含** `--window-position=-32000,-32000` + 反遮挡 flags。更新该处注释（移屏外 + 反遮挡 flags 现已重新启用、配 occlusion-disable 修了 0×0）。
  - native 模式（lines 205-211 附近）同样断言有头时含 offscreen flags。
  - 加一个 `hidden_window=False` 的用例断言**不含** offscreen flags。
  - 加一个 headless self-built（`headless=True`）用例断言**不含** offscreen flags（无头无窗口、无需移屏外）。

- [ ] **Step 2: 跑失败**（先确认是否需 override：该测试只 import csm_core 则不需要）`python -m pytest sidecar/tests/test_baidu_browser.py -v` → 失败（断言反了 / hidden_window 未知）。

- [ ] **Step 3: 实现** — `baidu_browser.py`：
  - import `from csm_core.browser_infra.window_util import offscreen_args`。
  - `baidu_browser_session` 签名加 `hidden_window: bool = True`。
  - 计算 `effective_headless`：native 恒 False；self-built = 入参 `headless`。**有头时**（`not effective_headless`）给两个分支的 `args` 追加 `offscreen_args(hidden_window)`：
    - native 分支 `args=[...]` 之后 `launch_kwargs["args"] += offscreen_args(hidden_window)`（native 恒有头）。
    - self-built 分支：`if not headless: launch_kwargs["args"] += offscreen_args(hidden_window)`（headless 时不加）。
  - （`baidu_keyword.py` 调 `baidu_browser_session` 处默认 `hidden_window=True` 即可，无需显式传；如要可配置，从 task config 读，本任务不强制。）

- [ ] **Step 4: 跑通过** `python -m pytest sidecar/tests/test_baidu_browser.py -v` → PASS.
- [ ] **Step 5: 提交** `git add csm_core/monitor/drivers/baidu_browser.py sidecar/tests/test_baidu_browser.py` → `feat(baidu): 百度 RPA 浏览器有头时移屏外（含反遮挡 flags）`

---

## Task 4: 百度验证码时上浮窗口

**Files:** Modify `csm_core/monitor/platforms/baidu_keyword.py`; Test（baidu_keyword 既有测试文件，grep `_try_human_solve`/`test_baidu_keyword`）

- [ ] **Step 1: 失败测试** — 在 baidu_keyword 测试里加：构造一个假 page（带 `.url` 序列：先在风控域、后离开）+ 假 CDP（记录 setWindowBounds），调 `_try_human_solve(page=..., keyword=..., kw_idx=0, timeout_s=..., poll_interval_s=0)`，断言期间调用了 `surface_window`（窗口移回可见区），结束（solved 或 timeout）后调用了 `hide_window`（移回屏外）。可 monkeypatch `baidu_keyword.surface_window`/`hide_window` 为记录用的 spy，断言调用序列 surface→…→hide。

- [ ] **Step 2: 跑失败** → surface/hide 未被调用。

- [ ] **Step 3: 实现** — `baidu_keyword.py`：
  - import `from csm_core.browser_infra.window_util import surface_window, hide_window`。
  - `_try_human_solve`：在函数体开头（notify 之后）`surface_window(page)`；把 `while` 等待循环包进 `try: ... finally: hide_window(page)`，保证 solved 和 timeout 两条出口都把窗口移回屏外。
  - （可选，若时间允许）文章页验证码路径（lines 504-543）同款 surface/finally hide。本任务核心是 SERP 级 `_try_human_solve`。

- [ ] **Step 4: 跑通过** `python -m pytest <baidu_keyword test> -v` → PASS（含既有用例）。
- [ ] **Step 5: 提交** `git add csm_core/monitor/platforms/baidu_keyword.py <test>` → `feat(baidu): 验证码人工解时窗口上浮、解完移回屏外`

---

## Self-Review

**Spec coverage（spec §Stream C）:** ④ GEO 移屏外 → Task 1+2 ✓；⑤ 百度移屏外不抢视觉 → Task 1+3 ✓；验证码/登录上浮 → Task 1+4（百度）✓；GEO open_login 保持可见 → 不改（设计明确）✓；反遮挡 flags 修 0×0 → Task 1 ✓（**真机验证项**）。

**确认点（真机/执行）:** (a) **patchright `context.new_cdp_session(page)` + `Browser.setWindowBounds` 真能用**（本仓库零先例 —— surface/hide 真机验证）；(b) **移屏外 + 反遮挡 flags 后 GEO fill/click 不再 0×0**（用户真机跑 GEO 任务验证，坏则回退 GEO headless）；(c) `tests/core/browser_infra/` 目录/collection 结构；(d) baidu_keyword 测试文件位置 + 是否需 override。

**范围安全:** `launched_page` 默认 `hidden_window=False` —— **mining 搜索不受影响**，只 GEO 显式开。百度仅**有头**时移屏外（headless 模式不动）。CDP 失败全部 try/except 回退不崩。

**顺序:** Task 1（helper）→ 2（GEO）→ 3（百度 launch）→ 4（百度验证码）。每步测试。
