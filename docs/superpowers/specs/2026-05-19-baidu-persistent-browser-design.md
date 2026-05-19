# 百度持久浏览器 profile 反爬升级 — Design

**日期**: 2026-05-19
**作者**: brainstorm session（继 `2026-05-19-baidu-monitor-hardening-design.md` 之后的第二轮）
**前置 spec**: [2026-05-19-baidu-monitor-hardening-design.md](2026-05-19-baidu-monitor-hardening-design.md)（已实现，Section 1-3 完成）

---

## 1. 背景

第一轮加固（2026-05-19）实现后实测：抓 10 个吸尘器关键词，**第 1 个 keyword 就触发 HTTP 403** 风控。Bug 2.2 的「上次抓取被百度风控拦截」banner 正确显示，但 SERP 阶段被直接 403 意味着 Section 3 加的 curl_cffi session 复用（article 阶段）压根没机会发挥。

### 1.1 根因（来自 `csm_core/monitor/drivers/incognito_session.py:46-108`）

当前 SERP 抓取走真·无痕模式：

- `pw.chromium.launch()` 每次创建临时 user_data_dir
- `browser.new_context()` 临时上下文，cookie/storage 不落盘
- 退出 `with` 块时 context → browser → playwright 全部销毁，下次冷启重来

后果：**百度看到的是「全新机器 + 0 秒 cookie baseline + 立刻连搜 10 个相同主题的关键词」**——这是教科书级的 bot 行为模式。三个核心 signal 同时命中：

| Signal | 当前行为 | 真人对照 |
|---|---|---|
| BAIDUID/BIDUPSID cookie | 每次空 | 多次访问累积、几天甚至几年 |
| Referer 链路 | 直接 hit `baidu.com/s?wd=keyword`（零 referrer） | 从首页 / 上一个 SERP 跳进 |
| 用户交互 | 0（直接 navigate） | 输入框 keystroke + 点击 search 按钮 |

第一轮做的 UA 池 + curl_cffi session reuse 解决了 article 阶段，但 SERP 阶段的 patchright 浏览器三大 signal 都没动，所以 SERP 在 keyword #0 就被拦。

### 1.2 不解决会怎样

`MonitorResult.status=risk_control` 写断点（progress=0），下次「启动监测」从 #0 继续——但 profile 还是空、还是无痕、还是直接 goto SERP，立刻又被 403，死循环。

---

## 2. 设计目标

| 编号 | 目标 | 验证 |
|---|---|---|
| G1 | SERP 阶段从「真无痕每次冷启」改成「CSM 专用持久 profile」，BAIDUID/BIDUPSID 跨任务累积 | 抓 10 个关键词，跑完 ≥ 5 个不触发风控 |
| G2 | 模拟真人搜索流程（首页 → fill → click search）替代直接 goto SERP URL | 第 1 个 keyword 触发风控的概率 < 50% |
| G3 | profile lock 安全：百度任务并发严格 = 1，多任务自动排队不冲突 | 连点 3 个百度任务，前 1 跑、后 2 排队 |
| G4 | profile 被烫坏时用户能手动重置，应用层不僵死 | UI 按钮可用 + 拒绝在 active task 时重置 |
| G5 | 不污染用户 Chrome、不影响隐私 | profile 完全在 CSM 数据目录内 |

---

## 3. 总览：5 节修法

| 节 | 主题 | 改动量 | 关键文件 |
|---|---|---|---|
| **A** | persistent_context + CSM 专用 user_data_dir | ~80 行 + 测试 | `baidu_browser.py`（rename from `incognito_session.py`） |
| **B** | 真人搜索流程（goto 主页 → fill → click） | ~50 行 + 测试 | `baidu_keyword.py:_fetch_once` |
| **C** | 百度并发限制 = 1（profile lock 硬约束） | ~10 行 | `rate_limit.py` + `apply_settings` |
| **D** | 重置 profile 的 UI 按钮 + 后端路由 | ~85 行 + 测试 | `routes/monitor.py` + `SettingsView.vue` |
| **E** | profile 健康度启动日志（ops 辅助） | ~15 行 | `baidu_browser.py:_log_profile_health` |

依赖：A 是基础，B 依赖 A（在 persistent page 里搜），C 是 A 的硬约束（profile lock），D 是 A 的逃生口，E 是 A 的诊断辅助。实现顺序 A → B → C → D → E。

---

## 4. Section A — Persistent Context（核心）

### 4.1 文件迁移

把 `csm_core/monitor/drivers/incognito_session.py` **改名为** `baidu_browser.py`。原文件名暗示「无痕」，跟新行为冲突。

### 4.2 contextmanager API 变化

```python
# csm_core/monitor/drivers/baidu_browser.py
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
    """Indirection 给单测 monkeypatch 用。"""
    from patchright.sync_api import sync_playwright
    return sync_playwright()


@dataclass
class BaiduBrowserSession:
    """一次 fetch 用的 patchright 资源句柄。

    与原 IncognitoSession 的区别：persistent context 没有独立 browser handle
    （launch_persistent_context 把 launch+new_context 融合成一个调用），所以
    只暴露 page / context / pw。
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
    - launch_persistent_context 直接返回 BrowserContext（不需要 launch().new_context()）
    - context.close() 时 cookies/localStorage/indexedDB 落盘到 user_data_dir
    - 同一时刻只能 1 个 instance 用同一 user_data_dir（OS 层 lock；并发限制
      由 rate_limit 的 platform slot semaphore=1 保证，见 Section C）

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
        # persistent context 默认通常已有 1 个 page；若是首次冷启 / 没有则新建
        page = context.pages[0] if context.pages else context.new_page()

        # 健康度日志（Section E）
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

    给「重置按钮」用（Section D 路由调用）。caller 负责确认无 active baidu
    task —— 否则会破坏正在运行的 profile 写入。
    """
    target = user_data_dir or _default_user_data_dir()
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)
        logger.info("baidu profile reset: %s", target)
```

### 4.3 调用方迁移

`csm_core/monitor/platforms/baidu_keyword.py` 现在的 import 与 `_fetch_once` 调用点：

```python
# Before (line 28):
from ..drivers.incognito_session import incognito_session

# ...

# Before (line 607):
with incognito_session(headless=headless) as session:
    page = session.page
    ...
```

改成：

```python
# After (line 28):
from ..drivers.baidu_browser import baidu_browser_session

# ...

# After (line 607):
with baidu_browser_session(headless=headless) as session:
    page = session.page
    ...
```

只有 1 处调用，迁移成本极低。

### 4.4 测试更新

`sidecar/tests/test_incognito_session.py` → 改名 `test_baidu_browser.py`，并把 fake `launch` + `new_context` 改成 fake `launch_persistent_context`。例：

```python
def test_baidu_browser_session_uses_persistent_context(monkeypatch, tmp_path):
    from csm_core.monitor.drivers import baidu_browser

    fake_pages: list[Any] = []
    fake_context = type("Ctx", (), {
        "pages": [],
        "new_page": lambda self: (fake_pages.append("p"), "p")[1],
        "close": lambda self: None,
        "cookies": lambda self, url=None: [],
    })()
    
    captured: dict[str, Any] = {}

    class FakeChromium:
        def launch_persistent_context(self, user_data_dir, **kwargs):
            captured["user_data_dir"] = user_data_dir
            captured["kwargs"] = kwargs
            return fake_context

    class FakePW:
        chromium = FakeChromium()
        def stop(self): pass

    class FakeSyncPW:
        def start(self): return FakePW()

    monkeypatch.setattr(baidu_browser, "_sync_playwright", lambda: FakeSyncPW())
    monkeypatch.setattr(baidu_browser, "ensure_browsers_path", lambda: None)

    with baidu_browser.baidu_browser_session(
        headless=True, user_data_dir=tmp_path / "profile"
    ) as sess:
        assert sess.page == "p"
        assert sess.context is fake_context

    assert captured["user_data_dir"] == str(tmp_path / "profile")
    assert "viewport" in captured["kwargs"]
    assert captured["kwargs"]["headless"] is False  # stealth: forced headed
```

---

## 5. Section B — 真人搜索流程

### 5.1 当前流程问题

`baidu_keyword.py:_fetch_once` line 651-655 当前：

```python
serp_url = "https://www.baidu.com/s?wd=" + quote(keyword)
serp_response = page.goto(serp_url, wait_until="domcontentloaded", timeout=45000)
```

→ 零 Referer + 零交互 + 直接 SERP URL = 经典 bot 模式。

### 5.2 新流程：第 1 个 keyword 走首页，后续 keyword 用顶部搜索框换词

```python
# csm_core/monitor/platforms/baidu_keyword.py

import random


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
        page.expect_navigation 拿到的 Response 对象（兼容现有 detect_risk 的入参）。
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

`_fetch_once` 主循环里替换原 `page.goto(serp_url, ...)`：

```python
# Before (line 651-665):
serp_url = "https://www.baidu.com/s?wd=" + quote(keyword)
serp_response = None
try:
    serp_response = page.goto(serp_url, wait_until="domcontentloaded", timeout=45000)
except TypeError:
    # Test FakePage 不接受 kwargs
    serp_response = page.goto(serp_url)
except Exception as e:
    logger.warning(...)
    kw_entry["fetch_error"] = f"serp navigate raised: {e!r}"
    keyword_results.append(kw_entry)
    continue

# After:
kw_entry["serp_url"] = "https://www.baidu.com/s?wd=" + quote(keyword)  # 仍记录给前端
serp_response = None
try:
    serp_response = _navigate_to_serp(page, keyword, is_first_keyword=(rel_idx == 0))
except TypeError:
    # FakePage 不接受 kwargs 时回退到直接 goto
    serp_response = page.goto("https://www.baidu.com/s?wd=" + quote(keyword))
except Exception as e:
    logger.warning(
        "baidu navigate failed (headless=%s, keyword=%r): %s",
        headless, keyword, e,
    )
    kw_entry["fetch_error"] = f"serp navigate raised: {e!r}"
    keyword_results.append(kw_entry)
    continue
```

注意 `is_first_keyword=(rel_idx == 0)`——这里 `rel_idx` 是 `_fetch_once` 主循环中相对索引（来自 `enumerate(keywords_to_fetch)`），不是绝对 `kw_idx`。即使断点续抓（`resume_from > 0`）也走第一次 = 从主页开始的路径，因为这时 page 是新 session 刚开的，状态等价于「冷启」。

### 5.3 测试

`sidecar/tests/test_baidu_keyword.py` 加：

- `test_navigate_to_serp_first_keyword_goes_home`：mock page 断言调用顺序：`goto("baidu.com")` → `wait_for_timeout` → `fill("input#kw", keyword)` → `wait_for_timeout` → `expect_navigation` ctx → `click("input#su")`。
- `test_navigate_to_serp_subsequent_keyword_skips_home`：`is_first_keyword=False` 时不调 `goto`，只调 `fill` + `click`。

---

## 6. Section C — 百度并发严格 = 1

### 6.1 为什么必须

`launch_persistent_context` 在 OS 层对 `user_data_dir` 加 lock：同时只能 1 个 Chrome instance 持有。当前 `rate_limit.py` 的 platform slot semaphore 默认允许 2 个同时持有——意味着两个百度 task 可能同时启动 Chrome 抢同一 profile，第二个会启动失败（看 patchright 怎么报）或者更糟：profile 文件被竞争写坏。

### 6.2 改动

`csm_core/browser_infra/rate_limit.py` 加 helper：

```python
def set_max_concurrent(platform: str, n: int) -> None:
    """Reconfigure the platform slot semaphore. Used by BaiduKeywordAdapter
    to force serial execution (persistent_context profile lock requires
    exclusive user_data_dir access).
    
    Idempotent — repeated calls with same n is a no-op. Different n
    creates a new semaphore (old waiters get reassigned on next acquire).
    """
    # 具体实现取决于 rate_limit.py 现有 RequestSemaphore 类结构；
    # 最简单：拿到 semaphore singleton，把 _max_value 改掉。如果当前实现
    # 内部用 threading.Semaphore（不可调），就 replace 整个 semaphore 对象。
    ...
```

`baidu_keyword.py:apply_settings` 末尾调用：

```python
# 持久 profile 不允许跨 task 并发 —— 强制 platform slot=1
rate_limit.set_max_concurrent(self.platform, 1)
```

### 6.3 用户体验

- 连点 3 个百度任务的「立刻监测」：第 1 个立刻跑，第 2、3 个**排队等**（不报错、不超时——靠现有的 slot acquire timeout=120s）
- 排队期间 frontend 的「立刻监测」按钮已经变成「监测中…」（前一轮 Bug 2.1 已修），用户不会重复点
- 如果 3+ 个挤到 slot timeout=120s 都 fail，前一轮 Bug 2.3 已经修了 toast 提示「队列繁忙」

### 6.4 测试

手动验证（自动测要 mock semaphore + ThreadPool 较重，不写自动测）：
- 启 3 个百度任务连点
- 观察前 1 个跑、后 2 个排队
- log 出现 `waiting for platform slot`

---

## 7. Section D — 重置 profile 的 UI 按钮 + 后端路由

### 7.1 后端路由

`sidecar/csm_sidecar/routes/monitor.py` 新增：

```python
@router.post("/api/monitor/baidu/reset-profile", status_code=status.HTTP_204_NO_CONTENT)
async def reset_baidu_profile() -> None:
    """Delete the persistent baidu browser profile dir. Next baidu task
    will cold-start a fresh profile.
    
    Use case: a profile that's been hit by 百度风控 multiple times has
    "burnt" cookies; rather than wait for cooldown, user can wipe and
    start fresh.
    
    Safety: refuses (409) if any baidu task is currently running — would
    corrupt the live profile mid-write.
    """
    from csm_core.monitor.drivers.baidu_browser import reset_profile
    from ..services import monitor_lifecycle

    loop = monitor_lifecycle.get()
    if loop is not None and loop.has_active_baidu_task():
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="有正在运行的百度任务，先停止再重置",
        )
    reset_profile()
```

`MonitorLoop` 需要新增 `has_active_baidu_task()` 方法：

```python
def has_active_baidu_task(self) -> bool:
    """Return True if any currently-active task is type=baidu_keyword.
    
    Used by routes/monitor.py reset-profile route to avoid corrupting
    a live persistent profile. Safe to call without holding _active_lock —
    it just reads a snapshot of the dict.
    """
    with self._active_lock:
        active_ids = list(self._active)
    if not active_ids:
        return False
    # 查 storage 看这些 active ID 里有没有 baidu_keyword 类型
    from csm_core.monitor import storage
    for tid in active_ids:
        task = storage.get_task(tid)
        if task is not None and task.type == "baidu_keyword":
            return True
    return False
```

### 7.2 前端

`frontend/src/api/client.ts` 加 API helper（如果项目有这个文件，否则在调用点直接用 `sidecar.client.post`）：

```ts
export async function resetBaiduProfile(): Promise<void> {
  await sidecar.client.post("/api/monitor/baidu/reset-profile");
}
```

`frontend/src/views/SettingsView.vue` 在百度关键词节最后加一行：

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

```ts
async function confirmResetBaiduProfile() {
  if (!confirm("确认重置百度浏览器 profile？\n下次任务会冷启重建，前几次抓取可能仍触发风控（cookie 需要慢慢累积）。")) return;
  try {
    await sidecar.client.post("/api/monitor/baidu/reset-profile");
    toast.success("百度浏览器 profile 已重置");
  } catch (e: any) {
    const detail = e.response?.data?.detail ?? e.message;
    toast.error(`重置失败：${detail}`);
  }
}
```

### 7.3 测试

`sidecar/tests/routes/test_monitor.py`（已存在）加：

- `test_reset_profile_409_when_baidu_running`：mock `loop.has_active_baidu_task` 返回 True，POST 应返 409
- `test_reset_profile_204_success_calls_reset`：mock `reset_profile`，POST 应返 204 且 `reset_profile` 被调用一次

---

## 8. Section E — Profile 健康度启动日志

### 8.1 目的

未来 debug 风控时，从 log 一眼看出 profile 状态——是空 profile、有 BAIDUID、cookie 数有多少。

### 8.2 实现

```python
# baidu_browser.py
def _log_profile_health(context: Any, user_data_dir: Path) -> None:
    """启动后打 1 行 log 标记 profile 状态。fail-soft：任何异常吞掉，
    profile health 日志失败不能阻塞 fetch。

    示例输出：
        baidu profile health: fresh=False, cookies=12, has_BAIDUID=True, path=C:/.../baidu_browser_profile
    """
    try:
        cookies = context.cookies("https://www.baidu.com/")
        has_baiduid = any(c.get("name") == "BAIDUID" for c in cookies)
        is_fresh = not (user_data_dir / "Default").exists()  # patchright 第一次启动会建这个
        logger.info(
            "baidu profile health: fresh=%s, cookies=%d, has_BAIDUID=%s, path=%s",
            is_fresh, len(cookies), has_baiduid, user_data_dir,
        )
    except Exception as e:
        logger.debug("profile health log failed (non-fatal): %s", e)
```

调用点在 Section 4.2 的 `baidu_browser_session` 里，`yield` 之前已经包含。

---

## 9. 验证策略

### 9.1 自动测试

- 后端：~6 个新 test（baidu_browser fixture / navigate_to_serp / reset-profile route）
- 全套 pytest 必过

### 9.2 实战测试（关键）

- 重启 sidecar 让 persistent_context 生效
- 新建一个百度任务，10+ 关键词
- 第一次跑：观察日志「profile health: fresh=True」+ 前几个 keyword 应该跑得过（因为已经走真人搜索流程 + 第一次 BAIDUID 会被 set 上）
- 第二次跑：观察日志「profile health: fresh=False, cookies=12+, has_BAIDUID=True」+ 风控触发率应该更低

**G1 验收**：10 个 keyword 跑完 ≥ 5 个不触发风控
**G2 验收**：第 1 个 keyword 触发风控的概率 < 50%（实测多次平均）

### 9.3 回归点

- 之前 Section 1-3（hot-reload / popover / curl_cffi session）的功能不受影响
- knowing-loop / pacing / breaker / risk_detector 全不动
- 知乎 / 抖音等其他平台用的还是 patchright_pool 老路径（这次只改百度专用的 incognito_session）

---

## 10. 改动文件清单

| 文件 | 改动 |
|---|---|
| `csm_core/monitor/drivers/incognito_session.py` → `baidu_browser.py` | 文件改名 + 重写 contextmanager 用 launch_persistent_context；新增 `reset_profile` + `_default_user_data_dir` + `_log_profile_health` |
| `csm_core/monitor/platforms/baidu_keyword.py` | (1) import `baidu_browser_session` 替代 `incognito_session`；(2) 新增 `_navigate_to_serp` + `_random_dwell_ms`；(3) `_fetch_once` 主循环改成调用 `_navigate_to_serp`；(4) `apply_settings` 末尾调用 `rate_limit.set_max_concurrent(self.platform, 1)` |
| `csm_core/browser_infra/rate_limit.py` | 新增 `set_max_concurrent(platform, n)` helper |
| `sidecar/csm_sidecar/services/monitor_loop.py` | 新增 `has_active_baidu_task()` method |
| `sidecar/csm_sidecar/routes/monitor.py` | 新增 `POST /api/monitor/baidu/reset-profile` 路由 |
| `frontend/src/views/SettingsView.vue` | 加「重置百度浏览器 profile」SettingsRow + 按钮 + confirmResetBaiduProfile handler |
| `sidecar/tests/test_incognito_session.py` → `test_baidu_browser.py` | 文件改名 + 更新 fake 为 `launch_persistent_context` 模式 |
| `sidecar/tests/test_baidu_keyword.py` | 新增 2 个 navigate_to_serp 测 |
| `sidecar/tests/routes/test_monitor.py` | 新增 2 个 reset-profile 测 |

---

## 11. YAGNI 边界

明确**不做**：

- ❌ 用户级 Chrome profile（用户已选 CSM 专用）
- ❌ Profile pool（多 profile 并发轮换）—— 单 profile 串行就够
- ❌ 自动重置 profile（用户选了手动 UI 按钮）
- ❌ 跨 task 共享 curl_cffi session —— 前一轮已经做了 per-task，此次不动
- ❌ Proxy IP 池
- ❌ 重写 risk_detector 4 层检测
- ❌ 鼠标移动模拟（Bezier 曲线等高级反爬手法）—— 先实测看 keystroke + click 是否足够
- ❌ 用 selenium-stealth 等额外库 —— patchright 自带 stealth 够用

---

## 12. 未涵盖 / 后续

如果 5 个 section 实施后实测仍触发风控，可考虑：

- 鼠标移动模拟（更细粒度真人行为）
- 多 profile rotation（profile pool）
- Proxy 池
- 用户 Chrome 二级回退选项
