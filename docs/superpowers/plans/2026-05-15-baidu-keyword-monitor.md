# 百度关键词排名监控 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在监控中心增加 `baidu_keyword` 监控类型 —— 操控本地 patchright（默认 headless、命中验证码升级可见）打开百度搜索，用指定 XPath 抓「默认搜索」「最新资讯」两个区块的文章链接，逐篇打开判断是否含目标品牌词，分区块输出排名、自家/竞品标记，纳入现有历史 + 趋势 + Excel 导出。

**Architecture:** 平台 adapter（`BaiduKeywordAdapter`）实现 `BaseMonitorAdapter.fetch`，挂进现有 `monitor_loop`，沿用 `MonitorTask`/`MonitorResult`/`metric_json` 的存储模式。浏览器层不复用 `patchright_pool`（持久 user-data-dir 与无痕语义冲突），而是新增独立的 `incognito_session` 模块走 per-fetch 临时 `BrowserContext`。HTTP-first 抓正文用 `curl_cffi` + `readability-lxml`，识别失败 fallback 同 incognito 浏览器同 tab。前端新增 `BaiduRankingPage`、`AddTaskModal` 百度分支、`SettingsView` 百度面板、SSE captcha Toast。

**Tech Stack:** Python 3.11 / FastAPI sidecar / patchright (Playwright stealth fork) / curl_cffi / readability-lxml / pytest · Vue 3 / Pinia / Tauri 2 / TypeScript / xlsx / Chart.js

**对 spec 的规划期细化（明确记录，避免后续 review 困惑）：**

1. **不扩展 `browser_driver.py` / `patchright_pool.py`**：现有 pool 的线程局部持久 context + 节点 PID + idle reaper 设计是为知乎那类「长会话 + cookie 持续注入」量身做的。百度任务每次 fetch 独立无痕 context，跟那套模型语义冲突。改成单独一个 `csm_core/monitor/drivers/incognito_session.py` 模块，提供 `incognito_session(headless: bool)` ContextManager，自管 `sync_playwright().start()` + `chromium.launch()`（非 persistent）+ `new_context()` + 销毁。Zhihu 路径完全不动。
2. **`EventKind` Literal 扩展**：在 `sidecar/csm_sidecar/services/monitor_loop.py` 现有 `EventKind = Literal[...]` 上加三个值 `"captcha_required" | "captcha_resolved" | "captcha_timeout"`，复用 `MonitorEvent` / `MonitorBus.publish` 通道，不另开 SSE 流。
3. **`RequestPacer` 用 `delay_min`/`delay_max`，不是单个 `min_interval`**：spec 中写 `serp_pacing_seconds=5` 是简化表达；实际配置成 `delay_min=5, delay_max=10`（与现有 pacer API 一致，让节奏看着像真人）。Settings 字段保留 `serp_pacing_seconds`，加载时映射成 `delay_min=N, delay_max=N*2`。

---

## File Structure

### 新建

- `csm_core/monitor/drivers/ua_pool.py` — 从 `zhihu_question.py` 抽出的共享 UA 池，多平台引用
- `csm_core/monitor/drivers/incognito_session.py` — patchright 临时无痕 context 管理器
- `csm_core/monitor/platforms/baidu_keyword.py` — `BaiduKeywordAdapter` 实现
- `sidecar/tests/test_baidu_keyword.py` — adapter 单元测试
- `sidecar/tests/test_incognito_session.py` — incognito context manager 单元测试
- `sidecar/tests/fixtures/baidu/serp_default_only.html` — 真实百度 SERP（无最新资讯）
- `sidecar/tests/fixtures/baidu/serp_with_news.html` — 真实百度 SERP（含最新资讯）
- `sidecar/tests/fixtures/baidu/captcha_urls.txt` — 真实百度验证码 URL 样本
- `scripts/manual_test_baidu.py` — 独立调试脚本（脱离 monitor_loop）
- `frontend/src/components/monitor/history/BaiduRankingPage.vue` — 百度历史详情页

### 修改

- `csm_core/monitor/base.py:15-20` — `TaskType` Literal 加 `"baidu_keyword"`
- `csm_core/monitor/platforms/__init__.py` — 注册 BAIDU adapter
- `csm_core/monitor/platforms/zhihu_question.py:36-41` — UA 池迁移到 ua_pool（保留 import 别名）
- `csm_core/monitor/excel_import.py:40-80` — `_TYPE_LABEL_MAP` / `TEMPLATE_HEADERS` / `_row_to_task` 适配百度
- `sidecar/csm_sidecar/services/monitor_loop.py:46` — `EventKind` Literal 加 captcha 三值
- `sidecar/csm_sidecar/services/monitor_lifecycle.py` — `BAIDU_ADAPTER.apply_settings()` 挂接
- `sidecar/csm_sidecar/services/config_service.py` — Pydantic config 加 `monitor.baidu_keyword.*` 字段
- `sidecar/pyproject.toml:6-16` — 加 `readability-lxml`、`curl_cffi`、`patchright` 依赖（若尚未列出）
- `frontend/src/components/monitor/AddTaskModal.vue` — 百度 task 类型分支
- `frontend/src/components/monitor/BatchImportTaskModal.vue` — 百度 Excel 模板（依赖后端模板已更新）
- `frontend/src/components/monitor/CookieManagerModal.vue` — 隐藏 `baidu_keyword` 选项
- `frontend/src/views/MonitorView.vue` — 百度历史 tab 路由
- `frontend/src/views/SettingsView.vue` — 「百度关键词」设置折叠面板
- `frontend/src/App.vue` 或 monitor store — SSE captcha 事件 → Toast

---

# PR #1 — 后端 + 单测

每个任务体量约 5–15 分钟。所有后端任务跑同一条 git 分支 `claude/brave-elbakyan-0d5933`，每完成一个任务提交一次。

## Task 1: 在 `TaskType` Literal 加 `baidu_keyword`

**Files:**
- Modify: `csm_core/monitor/base.py:15-20`
- Test: `sidecar/tests/test_monitor_routes.py`（已有；加一个用例）

- [ ] **Step 1: 写失败测试**

在 `sidecar/tests/test_monitor_routes.py` 末尾追加：

```python
def test_create_baidu_keyword_task(client, monitor_db):
    body = {
        "type": "baidu_keyword",
        "name": "百度-Claude教程",
        "target_url": "search:Claude Code 教程",
        "config": {
            "search_keyword": "Claude Code 教程",
            "target_brands": ["Claude", "Anthropic"],
            "headless": True,
        },
        "schedule_cron": "manual",
        "enabled": True,
    }
    resp = client.post("/api/monitor/tasks", json=body)
    assert resp.status_code == 201, resp.text
    assert resp.json()["type"] == "baidu_keyword"
    assert resp.json()["config"]["target_brands"] == ["Claude", "Anthropic"]
```

- [ ] **Step 2: 跑测试验证失败**

```bash
cd sidecar
python -m pytest tests/test_monitor_routes.py::test_create_baidu_keyword_task -v
```

Expected: 422 Validation Error（`baidu_keyword` 不在当前 Literal）。

- [ ] **Step 3: 修改 base.py**

打开 `csm_core/monitor/base.py`，把：

```python
TaskType = Literal[
    "zhihu_question",
    "bilibili_comment",
    "douyin_comment",
    "kuaishou_comment",
]
```

改成：

```python
TaskType = Literal[
    "zhihu_question",
    "bilibili_comment",
    "douyin_comment",
    "kuaishou_comment",
    "baidu_keyword",
]
```

- [ ] **Step 4: 跑测试验证通过**

```bash
cd sidecar
python -m pytest tests/test_monitor_routes.py::test_create_baidu_keyword_task -v
```

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add csm_core/monitor/base.py sidecar/tests/test_monitor_routes.py
git commit -m "feat(monitor): TaskType 加 baidu_keyword

CRUD 路由层泛型已经覆盖，这一步只扩 Literal 解锁创建。
adapter 实现见后续任务。"
```

---

## Task 2: 抽取共享 UA 池 `ua_pool.py`

**Files:**
- Create: `csm_core/monitor/drivers/ua_pool.py`
- Modify: `csm_core/monitor/platforms/zhihu_question.py:36-41`
- Test: `sidecar/tests/test_ua_pool.py`（新）

- [ ] **Step 1: 写失败测试**

新建 `sidecar/tests/test_ua_pool.py`：

```python
"""UA pool 抽取的回归测试。"""
from csm_core.monitor.drivers import ua_pool


def test_pool_returns_strings():
    assert len(ua_pool.UA_POOL) >= 4
    for ua in ua_pool.UA_POOL:
        assert ua.startswith("Mozilla/5.0")
        assert "Chrome/" in ua


def test_next_ua_rotates():
    rotator = ua_pool.UARotator()
    first = rotator.next()
    second = rotator.next()
    # 第二次跟第一次不同（除非池只有 1 个，但断言池 ≥ 4）
    assert first != second
    # 转一圈回到起点
    pool_size = len(ua_pool.UA_POOL)
    for _ in range(pool_size - 2):
        rotator.next()
    assert rotator.next() == first
```

- [ ] **Step 2: 跑测试验证失败**

```bash
cd sidecar
python -m pytest tests/test_ua_pool.py -v
```

Expected: FAIL `ModuleNotFoundError`。

- [ ] **Step 3: 创建 ua_pool.py**

新建 `csm_core/monitor/drivers/ua_pool.py`：

```python
"""跨平台共享的 User-Agent 池。

从 zhihu_question.py 抽出来，因为百度 adapter 也需要同款配色。
保留同一份池意味着改一处 UA、所有 adapter 同时生效。

只放近期 Chrome 桌面 UA —— 移动端、Edge 老版本、IE 都不在我们的爬取目标里，
反爬端见到那些反而更可疑。
"""
from __future__ import annotations

import threading


# Chrome 120-121 桌面 + 一个 Edge —— 多个 minor 版本错开签名，避免同一池
# 里两个 task 用一模一样的 UA。
UA_POOL: tuple[str, ...] = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
)


class UARotator:
    """单线程内 UA 轮换。多线程各自拿一个 rotator，互不干扰。"""

    def __init__(self) -> None:
        self._idx = 0
        self._lock = threading.Lock()

    def next(self) -> str:
        with self._lock:
            ua = UA_POOL[self._idx % len(UA_POOL)]
            self._idx += 1
            return ua
```

- [ ] **Step 4: 跑测试验证通过**

```bash
cd sidecar
python -m pytest tests/test_ua_pool.py -v
```

Expected: PASS。

- [ ] **Step 5: 迁移 zhihu_question.py**

`csm_core/monitor/platforms/zhihu_question.py`，删除：

```python
_UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ... Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ... Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) ... Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ... Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
]
```

新增 import：

```python
from ..drivers.ua_pool import UA_POOL as _UA_POOL
```

`_next_ua` 方法保持原样（仍用 `self._ua_idx` + 模 `len(_UA_POOL)`）。

- [ ] **Step 6: 跑知乎相关测试验证未回归**

```bash
cd sidecar
python -m pytest tests/ -k "zhihu or monitor" -v
```

Expected: 全部 PASS（未触发任何 zhihu 测试的失败）。

- [ ] **Step 7: 提交**

```bash
git add csm_core/monitor/drivers/ua_pool.py csm_core/monitor/platforms/zhihu_question.py sidecar/tests/test_ua_pool.py
git commit -m "refactor(monitor): UA 池抽到 drivers/ua_pool.py

下个任务百度 adapter 直接 import 同一份池，
避免两份 UA 列表漂移。"
```

---

## Task 3: `incognito_session` ContextManager

**Files:**
- Create: `csm_core/monitor/drivers/incognito_session.py`
- Test: `sidecar/tests/test_incognito_session.py`

这一步只做「能 start / close」的最薄壳，验证码检测在下一个任务加。

- [ ] **Step 1: 写失败测试**

新建 `sidecar/tests/test_incognito_session.py`：

```python
"""incognito_session 上下文管理器的单元测试。

不真启动 Chromium —— mock `sync_playwright` 的关键调用链，
验证 lifecycle 正确（start → launch → new_context → close 全打到）。
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from csm_core.monitor.drivers import incognito_session


@pytest.fixture
def mock_playwright(monkeypatch):
    """让 sync_playwright() 返回我们能 spy 的对象树。"""
    pw_handle = MagicMock(name="pw_handle")
    context = MagicMock(name="context")
    browser = MagicMock(name="browser")
    page = MagicMock(name="page")

    browser.new_context.return_value = context
    context.new_page.return_value = page
    pw_handle.chromium.launch.return_value = browser

    pw_starter = MagicMock(name="pw_starter")
    pw_starter.start.return_value = pw_handle

    fake_sync = MagicMock(return_value=pw_starter)
    monkeypatch.setattr(incognito_session, "_sync_playwright", fake_sync)
    return {
        "sync": fake_sync,
        "pw_handle": pw_handle,
        "browser": browser,
        "context": context,
        "page": page,
    }


def test_session_yields_page(mock_playwright):
    with incognito_session.incognito_session(headless=True) as sess:
        assert sess.page is mock_playwright["page"]
        assert sess.context is mock_playwright["context"]


def test_session_passes_headless_flag(mock_playwright):
    with incognito_session.incognito_session(headless=False):
        pass
    launch_call = mock_playwright["pw_handle"].chromium.launch.call_args
    assert launch_call.kwargs.get("headless") is False


def test_session_uses_incognito_context_not_persistent(mock_playwright):
    """关键反爬不变量：必须用 browser.new_context()，绝不能用
    launch_persistent_context（持久 user-data-dir 会跨任务带前次痕迹）。"""
    with incognito_session.incognito_session(headless=True):
        pass
    # launch 被调一次（开 browser）
    assert mock_playwright["pw_handle"].chromium.launch.called
    # launch_persistent_context 绝不能被调
    assert not mock_playwright["pw_handle"].chromium.launch_persistent_context.called
    # new_context 被调一次（开无痕 context）
    assert mock_playwright["browser"].new_context.called


def test_session_closes_in_lifo_order(mock_playwright):
    """正常退出：context.close → browser.close → pw.stop。"""
    with incognito_session.incognito_session(headless=True):
        pass
    mock_playwright["context"].close.assert_called_once()
    mock_playwright["browser"].close.assert_called_once()
    mock_playwright["pw_handle"].stop.assert_called_once()


def test_session_closes_on_exception(mock_playwright):
    """异常路径也要关掉，否则 Chromium 进程会泄漏。"""
    class Boom(Exception):
        pass

    with pytest.raises(Boom):
        with incognito_session.incognito_session(headless=True):
            raise Boom()

    mock_playwright["context"].close.assert_called_once()
    mock_playwright["browser"].close.assert_called_once()
    mock_playwright["pw_handle"].stop.assert_called_once()
```

- [ ] **Step 2: 跑测试验证失败**

```bash
cd sidecar
python -m pytest tests/test_incognito_session.py -v
```

Expected: FAIL `ModuleNotFoundError: csm_core.monitor.drivers.incognito_session`。

- [ ] **Step 3: 实现 incognito_session.py**

新建 `csm_core/monitor/drivers/incognito_session.py`：

```python
"""百度 adapter 专用：per-fetch 无痕 BrowserContext。

为什么不复用 patchright_pool：那个池是为知乎设计的 `launch_persistent_context`
（持久 user-data-dir + 线程局部 Page + idle reaper）。百度任务每次 fetch
独立无痕、不带前次 cookie，跟那套 lifecycle 完全相反。

这里走 `browser.launch()` + `browser.new_context()`，离开 with 块后
context → browser → playwright 全部销毁，下次冷启重来。代价 2–4s 冷启，
换无前次指纹累积。

线程模型：每次调用都在调用者线程内启动 sync_playwright 并在同线程关闭。
不跨线程共享 handle —— monitor_loop 的 ThreadPoolExecutor 每个 task 在
单线程内完整跑完 fetch，没有 cross-thread 风险。
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator

from .patchright_pool import ensure_browsers_path

logger = logging.getLogger(__name__)


# Indirection 是为了让单元测试能 monkeypatch 一个 fake `sync_playwright`，
# 避开真启动 Chromium。
def _sync_playwright() -> Any:
    from patchright.sync_api import sync_playwright
    return sync_playwright()


@dataclass
class IncognitoSession:
    """一次 fetch 用的 patchright 资源句柄。

    Caller 只用到 `page` 和 `context`；其他句柄由 ContextManager 自己关。
    """
    page: Any
    context: Any
    browser: Any
    pw: Any


@contextmanager
def incognito_session(*, headless: bool) -> Iterator[IncognitoSession]:
    """启动一次无痕 patchright 会话。退出时 LIFO 全部销毁。

    Args:
        headless: True → 后台跑；False → 弹可见窗口（验证码升级用）。

    Yields:
        IncognitoSession，含 `.page`/`.context` 给 adapter 用。

    Raises:
        RuntimeError: patchright 未安装、Chromium 启动失败。
    """
    # 与 patchright_pool 共用 PLAYWRIGHT_BROWSERS_PATH 检测，确保 onefile 打包后
    # 也能找到 Chromium。
    ensure_browsers_path()

    pw = None
    browser = None
    context = None
    try:
        pw = _sync_playwright().start()
        # 真正的「无痕」: launch() 默认每次新建临时 profile dir，并在 close()
        # 时删除。比 launch_persistent_context 简单得多。
        browser = pw.chromium.launch(
            headless=headless,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--window-size=1366,768",
            ],
        )
        # new_context 真正给我们一个无痕上下文 —— cookie/storage 不会落盘。
        context = browser.new_context(
            viewport={"width": 1366, "height": 768},
            # 不传 user_agent —— patchright Chromium 自带的 UA 跟它的 Client Hints
            # 是一致的；自己设会让 navigator.userAgent 与 userAgentData 错版本。
        )
        page = context.new_page()
        yield IncognitoSession(page=page, context=context, browser=browser, pw=pw)
    finally:
        # LIFO 关闭。每一层都包 try/except —— 一层炸了不能挡住下一层。
        if context is not None:
            try:
                context.close()
            except Exception as e:
                logger.debug("incognito context.close raised: %s", e)
        if browser is not None:
            try:
                browser.close()
            except Exception as e:
                logger.debug("incognito browser.close raised: %s", e)
        if pw is not None:
            try:
                pw.stop()
            except Exception as e:
                logger.debug("incognito pw.stop raised: %s", e)
```

- [ ] **Step 4: 跑测试验证通过**

```bash
cd sidecar
python -m pytest tests/test_incognito_session.py -v
```

Expected: 5 PASS。

- [ ] **Step 5: 提交**

```bash
git add csm_core/monitor/drivers/incognito_session.py sidecar/tests/test_incognito_session.py
git commit -m "feat(monitor): 加 incognito_session 上下文管理器

百度 adapter 用，每次 fetch 拿一个临时无痕 BrowserContext，
退出 with 块自动销毁。不动 patchright_pool。"
```

---

## Task 4: 验证码 URL / DOM 检测

**Files:**
- Modify: `csm_core/monitor/drivers/incognito_session.py`（加 `is_baidu_captcha_url` 函数）
- Modify: `sidecar/tests/test_incognito_session.py`（加用例）

- [ ] **Step 1: 写失败测试**

在 `sidecar/tests/test_incognito_session.py` 末尾追加：

```python
def test_is_baidu_captcha_url_detects_wappass():
    assert incognito_session.is_baidu_captcha_url(
        "https://wappass.baidu.com/static/captcha/tuxing.html?ak=xxx"
    )


def test_is_baidu_captcha_url_detects_passport():
    assert incognito_session.is_baidu_captcha_url(
        "https://passport.baidu.com/?login&u=https://www.baidu.com/s?wd=test"
    )


def test_is_baidu_captcha_url_detects_verify():
    assert incognito_session.is_baidu_captcha_url(
        "https://verify.baidu.com/v2/index.html"
    )


def test_is_baidu_captcha_url_clean_baidu_url_not_captcha():
    assert not incognito_session.is_baidu_captcha_url(
        "https://www.baidu.com/s?wd=test"
    )
    assert not incognito_session.is_baidu_captcha_url("")
    assert not incognito_session.is_baidu_captcha_url("https://example.com")
```

- [ ] **Step 2: 跑测试验证失败**

```bash
cd sidecar
python -m pytest tests/test_incognito_session.py::test_is_baidu_captcha_url_detects_wappass -v
```

Expected: FAIL `AttributeError: module ... has no attribute 'is_baidu_captcha_url'`。

- [ ] **Step 3: 实现函数**

`csm_core/monitor/drivers/incognito_session.py` 文件末尾追加：

```python
# 百度验证码落地页固定走这几个域；URL 子串匹配比 DOM 检测便宜很多，
# 优先用 URL。DOM 兜底另外做（adapter 调 page.locator 检测）。
_BAIDU_CAPTCHA_URL_MARKERS = (
    "wappass.baidu.com/static/captcha",
    "passport.baidu.com",
    "verify.baidu.com",
)


def is_baidu_captcha_url(url: str) -> bool:
    """True iff 落地 URL 看起来是百度的反爬验证码页。

    在 `page.goto` 之后立刻调一次 —— 命中说明已被百度拦下，要么走
    headless→可见升级，要么把当前 task 标 risk_control。
    """
    if not url:
        return False
    return any(marker in url for marker in _BAIDU_CAPTCHA_URL_MARKERS)
```

- [ ] **Step 4: 跑测试验证通过**

```bash
cd sidecar
python -m pytest tests/test_incognito_session.py -v
```

Expected: 9 PASS。

- [ ] **Step 5: 提交**

```bash
git add csm_core/monitor/drivers/incognito_session.py sidecar/tests/test_incognito_session.py
git commit -m "feat(monitor): 加 is_baidu_captcha_url 验证码 URL 检测

URL 子串匹配，比 DOM 检测便宜；adapter 在 page.goto 后立调一次。"
```

---

## Task 5: 保存 SERP fixture 文件

**Files:**
- Create: `sidecar/tests/fixtures/baidu/serp_default_only.html`
- Create: `sidecar/tests/fixtures/baidu/serp_with_news.html`
- Create: `sidecar/tests/fixtures/baidu/captcha_urls.txt`

这一步不写测试，只把 fixture 数据落地，让后面的 SERP 解析测试有素材吃。

- [ ] **Step 1: 在浏览器里手动捞两份真实 SERP HTML**

打开百度搜：
- 一个**冷门关键词**（如 `"Claude Code Tauri sidecar"`），SERP 没有「最新资讯」区块 → 另存为 `sidecar/tests/fixtures/baidu/serp_default_only.html`
- 一个**热点关键词**（如 `"AI 编程工具"` 或当天的热点新闻词），SERP 含「最新资讯」三篇 → 另存为 `sidecar/tests/fixtures/baidu/serp_with_news.html`

**脱敏要求**：
- 用编辑器全文搜替换掉 cookie 串、`<script>` 块里的用户 ID、`logid` 等带个人特征字段（用 `XXX` 占位）
- 不要包含「百度账号」相关 cookie 痕迹（无痕模式跑应该没有，但 fixture 是手动捞的，可能有）

- [ ] **Step 2: 校验 fixture 解析得出**

打开任一一份 HTML，用浏览器 DevTools 跑用户给的 XPath（在 Console 里）：

```javascript
// 默认搜索区块
$x("//div[contains(@class, 'c-container') and contains(@class, 'result') and contains(@class, 'xpath-log') and contains(@class, 'new-pmd') and not(@tpl='sp_purc_pc') and not(@tpl='news-realtime') and not(@tpl='short_video') and not(.//span[contains(@class, 'cosc-title-slot')])]//h3/a").length
```

`serp_default_only.html` 应返回 ≥ 8（百度首页一般 9-10 条，部分可能被排除）。`serp_with_news.html` 类似。

```javascript
// 最新资讯区块
$x("//div[contains(@class, 'cos-space')]/div[contains(@class, 'cos-row')]//h3//a").length
```

`serp_default_only.html` 应返回 0。`serp_with_news.html` 应返回 ≈ 3。

- [ ] **Step 3: 把验证码 URL 样本落地**

新建 `sidecar/tests/fixtures/baidu/captcha_urls.txt`，一行一个：

```
https://wappass.baidu.com/static/captcha/tuxing.html?ak=xxx&backurl=https%3A%2F%2Fwww.baidu.com%2Fs%3Fwd%3Dtest
https://passport.baidu.com/?login&u=https%3A%2F%2Fwww.baidu.com%2F
https://verify.baidu.com/v2/index.html?token=xxx
```

(这一步是文档化样本，方便未来对照 —— Task 4 的单测里已经包含相同 URL 字符串。)

- [ ] **Step 4: 提交**

```bash
git add sidecar/tests/fixtures/baidu/
git commit -m "test(monitor): 加百度 SERP / 验证码 URL fixtures

脱敏过的真实 SERP HTML 两份（含/不含最新资讯），
留给 SERP 解析单测吃。捞自 2026-05 当时的百度页面。"
```

---

## Task 6: `lxml` 解析 SERP 的纯函数 + 测试

**Files:**
- Create: `csm_core/monitor/platforms/baidu_keyword.py`（模块占位 + 解析函数）
- Test: `sidecar/tests/test_baidu_keyword.py`

这一步只实现 SERP 解析函数 `parse_serp(html: str) -> dict`，不动浏览器、不动 adapter 类。后续任务再往上面加。

- [ ] **Step 1: 写失败测试**

新建 `sidecar/tests/test_baidu_keyword.py`：

```python
"""百度 keyword adapter 单元测试。

不真开 Chromium、不真发 HTTP。所有外部交互都 mock。
SERP 解析逻辑用真实保存的 fixture 验证。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from csm_core.monitor.platforms import baidu_keyword


FIXTURES = Path(__file__).parent / "fixtures" / "baidu"


def _load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


# ── SERP 解析 ─────────────────────────────────────────────────────────────
def test_parse_serp_default_only_no_news():
    html = _load("serp_default_only.html")
    parsed = baidu_keyword.parse_serp(html)
    assert parsed["news_present"] is False
    assert parsed["news_links"] == []
    assert len(parsed["default_links"]) >= 8
    # 每个 link 是 dict，包含 title + href
    for link in parsed["default_links"]:
        assert "title" in link
        assert "href" in link
        assert link["href"].startswith("http")


def test_parse_serp_with_news_extracts_both_blocks():
    html = _load("serp_with_news.html")
    parsed = baidu_keyword.parse_serp(html)
    assert parsed["news_present"] is True
    assert 1 <= len(parsed["news_links"]) <= 5
    assert len(parsed["default_links"]) >= 5
    # 两个 list 严格分开，不重复
    default_hrefs = {l["href"] for l in parsed["default_links"]}
    news_hrefs = {l["href"] for l in parsed["news_links"]}
    assert default_hrefs.isdisjoint(news_hrefs)


def test_parse_serp_empty_html_returns_empty():
    parsed = baidu_keyword.parse_serp("")
    assert parsed["default_links"] == []
    assert parsed["news_links"] == []
    assert parsed["news_present"] is False
```

- [ ] **Step 2: 跑测试验证失败**

```bash
cd sidecar
python -m pytest tests/test_baidu_keyword.py -v
```

Expected: FAIL `ImportError: cannot import name 'baidu_keyword'`。

- [ ] **Step 3: 实现 baidu_keyword.py 解析层**

新建 `csm_core/monitor/platforms/baidu_keyword.py`：

```python
"""百度关键词排名监控 adapter。

策略：
1. 用 patchright incognito 打开 baidu.com/s?wd=keyword（默认 headless）
2. 用 spec 给的 XPath 抓「默认搜索」「最新资讯」两个区块的 h3//a href
3. 解 baidu.com/link?url=... 跳转拿真实 URL
4. 对每条 URL：curl_cffi + readability 抓正文，识别失败 fallback 浏览器
5. 大小写不敏感匹配任一 target_brand → matches_brand=True

引擎硬绑 patchright（无痕需 BrowserContext API，drission 不支持）。
"""
from __future__ import annotations

import logging
from typing import Any

from lxml import html as lxml_html

logger = logging.getLogger(__name__)


# 用户提供的两条 XPath（spec 第 1 节末尾）。完整 contains/not 链
# 跟用户原文一致，仅去掉首尾空白 —— XPath 引擎对空白不挑，但单行更易读。
_XPATH_DEFAULT = (
    "//div[contains(@class, 'c-container') "
    "and contains(@class, 'result') "
    "and contains(@class, 'xpath-log') "
    "and contains(@class, 'new-pmd') "
    "and not(@tpl='sp_purc_pc') "
    "and not(@tpl='news-realtime') "
    "and not(@tpl='short_video') "
    "and not(.//span[contains(@class, 'cosc-title-slot')])"
    "]//h3/a"
)

_XPATH_NEWS = (
    "//div[contains(@class, 'cos-space')]"
    "/div[contains(@class, 'cos-row')]"
    "//h3//a"
)


def parse_serp(html: str) -> dict[str, Any]:
    """从一段 SERP HTML 抽取两组 (title, href) 链接。

    纯函数：不发请求、不解 redirect、不判断品牌词 —— 只把 DOM 翻成 list。
    """
    if not html or not html.strip():
        return {"default_links": [], "news_links": [], "news_present": False}

    try:
        doc = lxml_html.fromstring(html)
    except Exception as e:
        logger.warning("baidu parse_serp: lxml fromstring raised: %s", e)
        return {"default_links": [], "news_links": [], "news_present": False}

    default_links = _extract_a_tags(doc, _XPATH_DEFAULT)
    news_links = _extract_a_tags(doc, _XPATH_NEWS)
    return {
        "default_links": default_links,
        "news_links": news_links,
        "news_present": bool(news_links),
    }


def _extract_a_tags(doc: Any, xpath: str) -> list[dict[str, str]]:
    """跑一条 XPath 抓所有 <a>，返回 [{title, href}]。"""
    try:
        nodes = doc.xpath(xpath)
    except Exception as e:
        logger.warning("baidu xpath %r raised: %s", xpath, e)
        return []
    out: list[dict[str, str]] = []
    for a in nodes:
        href = (a.get("href") or "").strip()
        if not href:
            continue
        # 标题文本：百度 h3 里通常有 <em> 高亮，textcontent 直接拿到纯文本
        title = (a.text_content() or "").strip()
        out.append({"title": title, "href": href})
    return out
```

需要在 sidecar 的依赖里有 `lxml`。`readability-lxml` 会拉 `lxml` 作为依赖（下面 Task 14 加），但保险起见也写到测试 imports 路径。本机如果 `pip list | grep lxml` 没有就 `pip install lxml`（PyInstaller 打包阶段 readability 会拽进来）。

- [ ] **Step 4: 跑测试验证通过**

```bash
cd sidecar
python -m pytest tests/test_baidu_keyword.py -v
```

Expected: 3 PASS。

- [ ] **Step 5: 注册占位 adapter**

`csm_core/monitor/platforms/baidu_keyword.py` 文件末尾追加：

```python
class BaiduKeywordAdapter:
    """`BaseMonitorAdapter` 实现。完整 fetch 在后续任务里逐步加上。"""

    platform: str = "baidu_keyword"

    def __init__(self) -> None:
        # 真实字段在 apply_settings 里被覆盖。
        self._headless_default = True
        self._captcha_timeout_s = 90
        self._captcha_max_promotions = 1

    def apply_settings(
        self,
        *,
        headless_default: bool = True,
        captcha_visible_timeout_s: int = 90,
        captcha_max_promotions: int = 1,
        serp_pacing_seconds: int = 5,
        breaker_failures: int = 3,
        breaker_cooldown_seconds: int = 600,
    ) -> None:
        """挂接 settings.monitor.baidu_keyword.*。lifecycle 启动 + 设置页保存时各调一次。"""
        from ..rate_limit import get_pacer, get_breaker

        self._headless_default = headless_default
        self._captcha_timeout_s = captcha_visible_timeout_s
        self._captcha_max_promotions = captcha_max_promotions

        pacer = get_pacer(self.platform)
        # 把 spec 的 serp_pacing_seconds 映射成 pacer 的 (min, max) jitter 窗口。
        pacer.configure(
            delay_min=float(serp_pacing_seconds),
            delay_max=float(serp_pacing_seconds * 2),
        )
        breaker = get_breaker(self.platform)
        breaker.failure_threshold = breaker_failures
        breaker.cool_off_seconds = float(breaker_cooldown_seconds)

    def fetch(self, task):  # noqa: ANN001 — full annotation in later task
        """先返回失败结果，完整实现见后续任务。"""
        from datetime import datetime
        from ..base import MonitorResult
        return MonitorResult(
            task_id=task.id or 0,
            checked_at=datetime.utcnow(),
            status="failed",
            rank=-1,
            error_message="baidu_keyword adapter not yet implemented",
        )


# Module-level singleton —— 跟其他平台一致。
ADAPTER = BaiduKeywordAdapter()
```

注册到 `csm_core/monitor/platforms/__init__.py`：

```python
"""Per-platform monitor adapters."""
from .zhihu_question import ADAPTER as ZHIHU
from .bilibili_comment import ADAPTER as BILIBILI
from .douyin_comment import ADAPTER as DOUYIN
from .kuaishou_comment import ADAPTER as KUAISHOU
from .baidu_keyword import ADAPTER as BAIDU

ALL = {
    "zhihu_question": ZHIHU,
    "bilibili_comment": BILIBILI,
    "douyin_comment": DOUYIN,
    "kuaishou_comment": KUAISHOU,
    "baidu_keyword": BAIDU,
}

__all__ = ["ZHIHU", "BILIBILI", "DOUYIN", "KUAISHOU", "BAIDU", "ALL"]
```

- [ ] **Step 6: 再跑一次确认 import 链路无回归**

```bash
cd sidecar
python -m pytest tests/ -v -x
```

Expected: 全部 PASS（Task 1 那条 baidu_keyword 创建测试也连带过了）。

- [ ] **Step 7: 提交**

```bash
git add csm_core/monitor/platforms/baidu_keyword.py csm_core/monitor/platforms/__init__.py sidecar/tests/test_baidu_keyword.py
git commit -m "feat(monitor): 加 baidu_keyword adapter 占位 + SERP 解析

只实现 parse_serp 纯函数 + adapter 占位类。
fetch() 暂返回 failed，下一步加品牌匹配 / HTTP 抓正文 / 浏览器编排。"
```

---

## Task 7: 品牌词大小写不敏感匹配函数

**Files:**
- Modify: `csm_core/monitor/platforms/baidu_keyword.py`
- Modify: `sidecar/tests/test_baidu_keyword.py`

- [ ] **Step 1: 写失败测试**

`sidecar/tests/test_baidu_keyword.py` 追加：

```python
# ── 品牌词匹配 ───────────────────────────────────────────────────────────
def test_match_brand_case_insensitive_hit():
    matched = baidu_keyword.match_brand(
        "I love claude code today",
        ["Claude", "Anthropic"],
    )
    assert matched == "Claude"


def test_match_brand_returns_first_in_brand_order():
    """命中多个时，按 brands 列表里的顺序取第一个。"""
    matched = baidu_keyword.match_brand(
        "anthropic 出了一个叫 claude 的产品",
        ["Claude", "Anthropic"],  # Claude 在前
    )
    assert matched == "Claude"


def test_match_brand_no_match_returns_none():
    assert baidu_keyword.match_brand("text without brand", ["Claude"]) is None


def test_match_brand_empty_inputs():
    assert baidu_keyword.match_brand("", ["Claude"]) is None
    assert baidu_keyword.match_brand("text", []) is None
    assert baidu_keyword.match_brand("", []) is None
```

- [ ] **Step 2: 跑测试验证失败**

```bash
cd sidecar
python -m pytest tests/test_baidu_keyword.py::test_match_brand_case_insensitive_hit -v
```

Expected: FAIL `AttributeError: module ... has no attribute 'match_brand'`。

- [ ] **Step 3: 实现 match_brand**

`csm_core/monitor/platforms/baidu_keyword.py` 在 `parse_serp` 后追加：

```python
def match_brand(content: str, brands: list[str]) -> str | None:
    """大小写不敏感找首个出现的目标品牌词。

    "首个" 的含义是 brands 列表里的顺序，不是 content 中位置 ——
    用户排品牌词顺序代表优先级（主品牌排前面）。

    Args:
        content: 待检测正文（不限长度，但建议先 readability 提过）
        brands: 目标品牌词列表，至少非空才有意义

    Returns:
        命中的品牌词原文（保留 brands 列表里的大小写），无命中 → None
    """
    if not content or not brands:
        return None
    content_lc = content.lower()
    for brand in brands:
        if brand and brand.lower() in content_lc:
            return brand
    return None
```

- [ ] **Step 4: 跑测试验证通过**

```bash
cd sidecar
python -m pytest tests/test_baidu_keyword.py -v
```

Expected: 7 PASS（前 3 个 SERP + 新加 4 个 match_brand）。

- [ ] **Step 5: 提交**

```bash
git add csm_core/monitor/platforms/baidu_keyword.py sidecar/tests/test_baidu_keyword.py
git commit -m "feat(monitor): 加 match_brand 大小写不敏感品牌词匹配"
```

---

## Task 8: 百度跳转链接 redirect 解析

**Files:**
- Modify: `csm_core/monitor/platforms/baidu_keyword.py`
- Modify: `sidecar/tests/test_baidu_keyword.py`

百度 SERP `href` 多半是 `https://www.baidu.com/link?url=xxx`，需要 HEAD/GET 跟随重定向拿真实 URL。

- [ ] **Step 1: 写失败测试**

`sidecar/tests/test_baidu_keyword.py` 追加：

```python
# ── 百度跳转解析 ─────────────────────────────────────────────────────────
def test_resolve_baidu_link_already_real_url():
    """非百度跳转 URL 原样返回。"""
    real = "https://zhuanlan.zhihu.com/p/123456"
    assert baidu_keyword.resolve_baidu_link(real) == real


def test_resolve_baidu_link_follows_302(monkeypatch):
    """baidu.com/link?url=... 跟随 302 到真实站点。"""
    fake_real = "https://www.example.com/article"

    class FakeResp:
        url = fake_real
        status_code = 200

    def fake_get(url, **kwargs):
        # 验证调用方传了 allow_redirects=True
        assert kwargs.get("allow_redirects") is True
        return FakeResp()

    import csm_core.monitor.platforms.baidu_keyword as bk
    monkeypatch.setattr(bk, "_cc_get", fake_get)

    resolved = baidu_keyword.resolve_baidu_link(
        "https://www.baidu.com/link?url=encoded_blob_xxx"
    )
    assert resolved == fake_real


def test_resolve_baidu_link_returns_original_on_error(monkeypatch):
    """解失败 → 退回原始 URL，让上游决定怎么处理。"""
    def fake_get(url, **kwargs):
        raise RuntimeError("network down")

    import csm_core.monitor.platforms.baidu_keyword as bk
    monkeypatch.setattr(bk, "_cc_get", fake_get)

    original = "https://www.baidu.com/link?url=blob"
    assert baidu_keyword.resolve_baidu_link(original) == original
```

- [ ] **Step 2: 跑测试验证失败**

```bash
cd sidecar
python -m pytest tests/test_baidu_keyword.py::test_resolve_baidu_link_already_real_url -v
```

Expected: FAIL（函数不存在）。

- [ ] **Step 3: 实现 resolve_baidu_link**

`csm_core/monitor/platforms/baidu_keyword.py` 追加：

```python
from typing import Any as _Any  # 在文件顶部已有，避免重复 import


# Indirection 给单测 monkeypatch 用。真实调用走 curl_cffi。
def _cc_get(url: str, **kwargs: _Any) -> _Any:
    from curl_cffi import requests as cc_requests
    return cc_requests.get(url, **kwargs)


def resolve_baidu_link(url: str) -> str:
    """如果是 baidu.com/link?url=... 跳转，跟随 redirect 拿真实 URL。

    非百度跳转 URL 直接返回。任何异常 → 返回原 URL（adapter 自然把它当
    抓取失败 source）。
    """
    if not url or "baidu.com/link?" not in url:
        return url
    try:
        resp = _cc_get(
            url,
            impersonate="chrome120",
            allow_redirects=True,
            timeout=10,
        )
        return getattr(resp, "url", None) or url
    except Exception as e:
        logger.info("resolve_baidu_link(%s) raised: %s", url[:60], e)
        return url
```

- [ ] **Step 4: 跑测试验证通过**

```bash
cd sidecar
python -m pytest tests/test_baidu_keyword.py -v
```

Expected: 10 PASS。

- [ ] **Step 5: 提交**

```bash
git add csm_core/monitor/platforms/baidu_keyword.py sidecar/tests/test_baidu_keyword.py
git commit -m "feat(monitor): 加 resolve_baidu_link 跳转解析

baidu.com/link?url=... → 真实站点。跟随 302，解失败退回原 URL。"
```

---

## Task 9: HTTP-first 抓正文 + 降级条件判断

**Files:**
- Modify: `csm_core/monitor/platforms/baidu_keyword.py`
- Modify: `sidecar/tests/test_baidu_keyword.py`
- Modify: `sidecar/pyproject.toml`（加 readability-lxml）

- [ ] **Step 1: 加依赖**

打开 `sidecar/pyproject.toml`，在 `dependencies` 列表里加：

```toml
dependencies = [
    "fastapi>=0.110",
    "uvicorn[standard]>=0.27",
    "sse-starlette>=2.0",
    "keyring>=24.0",
    "apscheduler>=3.10",
    "pydantic>=2.6",
    "readability-lxml>=0.8.1",  # baidu 抓正文用
    "lxml>=4.9",                # readability 依赖；显式列出便于 PyInstaller 打包
    "curl-cffi>=0.7",           # 已在用，显式列以便 sidecar 单独可装
]
```

装一下：

```bash
cd sidecar
pip install -e .
```

`pip list | findstr readability` 看到 `readability-lxml` 即可。

- [ ] **Step 2: 写失败测试**

`sidecar/tests/test_baidu_keyword.py` 追加：

```python
# ── HTTP-first 抓正文 ────────────────────────────────────────────────────
class _FakeResp:
    def __init__(self, *, text: str, status_code: int = 200,
                 headers: dict | None = None):
        self.text = text
        self.status_code = status_code
        self.headers = headers or {"content-type": "text/html; charset=utf-8"}


def test_fetch_article_http_success(monkeypatch):
    """正常 HTML，readability 提到正文 ≥ 200 字 → source=http, 拿到 preview。"""
    long_content = (
        "<html><body><article>"
        + ("我用 Claude Code 写了一个 Tauri 应用。" * 20)
        + "</article></body></html>"
    )

    monkeypatch.setattr(
        baidu_keyword, "_cc_get",
        lambda url, **kw: _FakeResp(text=long_content),
    )
    result = baidu_keyword.fetch_article_http("https://example.com/post")
    assert result["source"] == "http"
    assert result["fetch_error"] is None
    assert "Claude Code" in result["content"]
    assert len(result["content"]) >= 200


def test_fetch_article_http_status_too_high_triggers_fallback(monkeypatch):
    monkeypatch.setattr(
        baidu_keyword, "_cc_get",
        lambda url, **kw: _FakeResp(text="", status_code=403),
    )
    result = baidu_keyword.fetch_article_http("https://example.com/forbidden")
    assert result["source"] == "http"
    assert result["needs_browser_fallback"] is True
    assert "403" in (result["fetch_error"] or "")


def test_fetch_article_http_non_html_triggers_fallback(monkeypatch):
    monkeypatch.setattr(
        baidu_keyword, "_cc_get",
        lambda url, **kw: _FakeResp(
            text="{}",
            headers={"content-type": "application/json"},
        ),
    )
    result = baidu_keyword.fetch_article_http("https://example.com/api")
    assert result["needs_browser_fallback"] is True
    assert "content-type" in (result["fetch_error"] or "").lower()


def test_fetch_article_http_too_short_triggers_fallback(monkeypatch):
    """readability 提出来正文 < 200 字 → 视为 SPA 壳，要求浏览器 fallback。"""
    short = "<html><body><div>请打开 APP 查看</div></body></html>"
    monkeypatch.setattr(
        baidu_keyword, "_cc_get",
        lambda url, **kw: _FakeResp(text=short),
    )
    result = baidu_keyword.fetch_article_http("https://example.com/spa")
    assert result["needs_browser_fallback"] is True


def test_fetch_article_http_network_exception_triggers_fallback(monkeypatch):
    def boom(url, **kw):
        raise RuntimeError("dns nxdomain")

    monkeypatch.setattr(baidu_keyword, "_cc_get", boom)
    result = baidu_keyword.fetch_article_http("https://offline.example/")
    assert result["needs_browser_fallback"] is True
    assert "nxdomain" in (result["fetch_error"] or "").lower()
```

- [ ] **Step 3: 跑测试验证失败**

```bash
cd sidecar
python -m pytest tests/test_baidu_keyword.py -k fetch_article -v
```

Expected: FAIL（函数不存在）。

- [ ] **Step 4: 实现 fetch_article_http**

`csm_core/monitor/platforms/baidu_keyword.py` 追加：

```python
# 决定是否升级浏览器的最短正文阈值。少于这个字数说明 readability
# 没真正提到内容（典型 SPA「请用 APP 打开」壳页），交给浏览器 fallback。
_HTTP_MIN_CONTENT_CHARS = 200


def fetch_article_http(url: str) -> dict[str, Any]:
    """用 curl_cffi + readability 抓单篇文章，返回纯文本正文。

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


def _extract_readable_text(raw_html: str) -> str:
    """readability-lxml 提正文。失败返回空串。"""
    if not raw_html.strip():
        return ""
    try:
        from readability import Document
    except ImportError:
        logger.warning("readability-lxml not installed; falling back to lxml text_content")
        try:
            doc = lxml_html.fromstring(raw_html)
            return (doc.text_content() or "").strip()
        except Exception:
            return ""
    try:
        doc = Document(raw_html)
        summary_html = doc.summary(html_partial=True)
        text = lxml_html.fromstring(summary_html).text_content() if summary_html else ""
        return (text or "").strip()
    except Exception as e:
        logger.info("readability summary raised: %s", e)
        return ""
```

- [ ] **Step 5: 跑测试验证通过**

```bash
cd sidecar
python -m pytest tests/test_baidu_keyword.py -v
```

Expected: 15 PASS。

- [ ] **Step 6: 提交**

```bash
git add sidecar/pyproject.toml csm_core/monitor/platforms/baidu_keyword.py sidecar/tests/test_baidu_keyword.py
git commit -m "feat(monitor): HTTP-first 抓正文 + readability 降级判断

curl_cffi + readability-lxml 抓 → 5 类失败条件触发浏览器 fallback：
  status≥400 / 非 text/html / readable 正文 < 200 字 / 网络异常 / SPA marker
显式 sidecar 依赖加 readability-lxml / lxml / curl-cffi。"
```

---

## Task 10: 浏览器 fallback 抓正文

**Files:**
- Modify: `csm_core/monitor/platforms/baidu_keyword.py`
- Modify: `sidecar/tests/test_baidu_keyword.py`

- [ ] **Step 1: 写失败测试**

`sidecar/tests/test_baidu_keyword.py` 追加：

```python
# ── 浏览器 fallback ─────────────────────────────────────────────────────
def test_fetch_article_browser_success():
    """给一个 fake page，验证 fallback 抽到 content 并标 source=browser。"""
    long_text = "  这里是浏览器 fallback 抓到的正文：" + ("Claude " * 30)

    class FakePage:
        def goto(self, url, **kw):
            pass

        def content(self):
            return f"<html><body><article>{long_text}</article></body></html>"

    result = baidu_keyword.fetch_article_browser(
        FakePage(), "https://spa.example/post"
    )
    assert result["source"] == "browser"
    assert result["fetch_error"] is None
    assert "Claude" in result["content"]


def test_fetch_article_browser_navigation_exception():
    class FakePage:
        def goto(self, url, **kw):
            raise RuntimeError("navigation timeout")

        def content(self):
            return ""

    result = baidu_keyword.fetch_article_browser(
        FakePage(), "https://timeout.example/"
    )
    assert result["source"] == "browser"
    assert "navigation timeout" in (result["fetch_error"] or "")
```

- [ ] **Step 2: 跑测试验证失败**

```bash
cd sidecar
python -m pytest tests/test_baidu_keyword.py::test_fetch_article_browser_success -v
```

Expected: FAIL。

- [ ] **Step 3: 实现 fetch_article_browser**

`csm_core/monitor/platforms/baidu_keyword.py` 追加：

```python
def fetch_article_browser(page: Any, url: str) -> dict[str, Any]:
    """浏览器 fallback：用已有的 patchright Page 打开 URL，读 HTML 提正文。

    跟 HTTP-first 函数返回结构一致，方便上游统一处理。

    复用同一个 incognito context 的 Page —— SERP 抓完后，循环里
    每条 URL 在同 page 上 goto 切走（不开新 tab，避免句柄爆炸）。
    """
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=20000)
    except TypeError:
        # FakePage 不接受关键字参数：测试场景
        try:
            page.goto(url)
        except Exception as e:
            return {
                "content": "",
                "source": "browser",
                "fetch_error": f"page.goto raised: {e!r}",
                "needs_browser_fallback": False,
            }
    except Exception as e:
        return {
            "content": "",
            "source": "browser",
            "fetch_error": f"page.goto raised: {e!r}",
            "needs_browser_fallback": False,
        }

    try:
        raw = page.content() or ""
    except Exception as e:
        return {
            "content": "",
            "source": "browser",
            "fetch_error": f"page.content raised: {e!r}",
            "needs_browser_fallback": False,
        }

    text = _extract_readable_text(raw)
    return {
        "content": text,
        "source": "browser",
        "fetch_error": None if text else "browser content empty after readability",
        "needs_browser_fallback": False,
    }
```

- [ ] **Step 4: 跑测试验证通过**

```bash
cd sidecar
python -m pytest tests/test_baidu_keyword.py -v
```

Expected: 17 PASS。

- [ ] **Step 5: 提交**

```bash
git add csm_core/monitor/platforms/baidu_keyword.py sidecar/tests/test_baidu_keyword.py
git commit -m "feat(monitor): 浏览器 fallback 抓正文

同一个 patchright Page goto 走 SPA，content() + readability 提文。
跟 HTTP-first 返回结构对齐，上游可统一处理。"
```

---

## Task 11: 编排 `fetch()` —— mock 全链路

**Files:**
- Modify: `csm_core/monitor/platforms/baidu_keyword.py`
- Modify: `sidecar/tests/test_baidu_keyword.py`

把所有片段拼成完整 `fetch(task) → MonitorResult`，但浏览器层全部 mock 掉。验证码升级 + 真浏览器留到手动测。

- [ ] **Step 1: 写失败测试**

`sidecar/tests/test_baidu_keyword.py` 追加：

```python
# ── 完整 fetch 编排 ──────────────────────────────────────────────────────
from csm_core.monitor.base import MonitorTask


class FakeSession:
    """假装 IncognitoSession，只暴露 page。"""

    def __init__(self, *, serp_html: str, page_contents: dict[str, str],
                 captcha_url: str | None = None):
        self._serp_html = serp_html
        self._page_contents = page_contents
        self._captcha_url = captcha_url
        self._current_url = ""
        # adapter 通过 .page.goto / .page.content 读取
        self.page = self  # type: ignore[assignment]
        self.context = None
        self.browser = None
        self.pw = None

    # adapter 当 page 调用的方法
    def goto(self, url, **kw):
        if self._captcha_url and "baidu.com/s?" in url:
            self._current_url = self._captcha_url
        else:
            self._current_url = url

    @property
    def url(self):
        return self._current_url

    def content(self):
        if "baidu.com/s?" in self._current_url:
            return self._serp_html
        return self._page_contents.get(self._current_url, "")


@pytest.fixture
def patch_session(monkeypatch):
    """工厂 fixture：调用方传入 fake session，adapter 走 mock 路径。"""
    holder: dict = {"session": None}

    from contextlib import contextmanager

    @contextmanager
    def fake_ctx(*, headless: bool):
        holder["last_headless"] = headless
        yield holder["session"]

    monkeypatch.setattr(
        baidu_keyword, "incognito_session", fake_ctx
    )
    return holder


def test_fetch_happy_path_default_only(monkeypatch, patch_session):
    """没有最新资讯，10 条结果里第 1 条是自家、其余竞品。"""
    serp = _load("serp_default_only.html")
    # 用真实 SERP 抓出来的 hrefs 给每条配一段正文
    parsed = baidu_keyword.parse_serp(serp)
    default_links = parsed["default_links"]
    page_contents = {}
    for i, link in enumerate(default_links):
        # 解掉百度跳转后 fake_get 默认走 mock_resolve（见下）
        url = link["href"]
        page_contents[url] = (
            "<html><body><article>"
            + (f"这是关于 Claude 的文章 {i}。" if i == 0
               else f"这是别的竞品的文章 {i}。 ")
            * 30
            + "</article></body></html>"
        )

    patch_session["session"] = FakeSession(
        serp_html=serp, page_contents=page_contents,
    )
    # resolve_baidu_link → 原样返回（mock）
    monkeypatch.setattr(baidu_keyword, "resolve_baidu_link", lambda u: u)
    # 走 HTTP-first 直接命中（不绕浏览器）
    def fake_cc_get(url, **kw):
        return _FakeResp(text=page_contents.get(url, ""))
    monkeypatch.setattr(baidu_keyword, "_cc_get", fake_cc_get)

    task = MonitorTask(
        id=1,
        type="baidu_keyword",
        name="t",
        target_url="https://www.baidu.com/s?wd=test",
        config={"search_keyword": "test", "target_brands": ["Claude"]},
    )

    result = baidu_keyword.ADAPTER.fetch(task)
    assert result.status == "ok"
    assert result.metric["news_present"] is False
    assert len(result.metric["default_results"]) >= 8
    assert result.metric["default_results"][0]["matches_brand"] is True
    assert result.metric["default_results"][0]["matched_brand"] == "Claude"
    assert result.rank == 1  # 首条命中
    assert result.metric["default_first_rank"] == 1
    assert result.metric["default_matched_count"] >= 1
    assert result.metric["captcha_hit"] is False


def test_fetch_captcha_returns_risk_control(monkeypatch, patch_session):
    """SERP 落地到验证码 URL，单 task 不升级（max_promotions=0 用 monkey）→
    立即返回 risk_control。"""
    serp = _load("serp_default_only.html")
    patch_session["session"] = FakeSession(
        serp_html=serp,
        page_contents={},
        captcha_url="https://wappass.baidu.com/static/captcha/tuxing.html?x=y",
    )

    # 把 max_promotions 暂时设成 0，避免单测里真跑升级流程
    baidu_keyword.ADAPTER._captcha_max_promotions = 0

    task = MonitorTask(
        id=2,
        type="baidu_keyword",
        name="t",
        target_url="https://www.baidu.com/s?wd=test",
        config={"search_keyword": "test", "target_brands": ["Claude"]},
    )
    result = baidu_keyword.ADAPTER.fetch(task)
    assert result.status == "risk_control"
    assert result.metric["captcha_hit"] is True

    # 还原
    baidu_keyword.ADAPTER._captcha_max_promotions = 1


def test_fetch_breaker_open_returns_risk_control(monkeypatch):
    """熔断打开时跳过所有 IO 直接 risk_control。"""
    from csm_core.monitor.rate_limit import get_breaker
    breaker = get_breaker("baidu_keyword")
    # 强制打开
    breaker.failure_threshold = 1
    breaker.cool_off_seconds = 999.0
    breaker.record_failure()
    assert breaker.allow() is False

    task = MonitorTask(
        id=3,
        type="baidu_keyword",
        name="t",
        target_url="https://www.baidu.com/s?wd=test",
        config={"search_keyword": "test", "target_brands": ["x"]},
    )
    result = baidu_keyword.ADAPTER.fetch(task)
    assert result.status == "risk_control"
    assert "circuit breaker" in result.error_message.lower()

    # 还原
    breaker.record_success()
```

- [ ] **Step 2: 跑测试验证失败**

```bash
cd sidecar
python -m pytest tests/test_baidu_keyword.py::test_fetch_happy_path_default_only -v
```

Expected: FAIL（fetch 还是只返回 stub）。

- [ ] **Step 3: 实现完整 fetch()**

`csm_core/monitor/platforms/baidu_keyword.py` 顶部 import 区加：

```python
from datetime import datetime
from urllib.parse import urlparse, quote
from .. import rate_limit
from ..base import BaseMonitorAdapter, MonitorResult, MonitorTask
from ..drivers.incognito_session import incognito_session, is_baidu_captcha_url
```

替换占位 `fetch`：

```python
    def fetch(self, task: MonitorTask) -> MonitorResult:
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
        keyword = (cfg.get("search_keyword") or "").strip()
        brands = [b.strip() for b in (cfg.get("target_brands") or []) if b and b.strip()]
        if not keyword or not brands:
            return MonitorResult(
                task_id=task.id or 0,
                checked_at=datetime.utcnow(),
                status="failed",
                rank=-1,
                error_message="config.search_keyword + target_brands required",
            )

        headless = bool(cfg.get("headless", self._headless_default))
        rate_limit.get_pacer(self.platform).wait()

        return self._fetch_with_promotion(task, keyword, brands, headless)

    def _fetch_with_promotion(
        self,
        task: MonitorTask,
        keyword: str,
        brands: list[str],
        headless: bool,
    ) -> MonitorResult:
        """跑一次 SERP；命中验证码且还有升级机会 → headless=False 再跑一次。"""
        breaker = rate_limit.get_breaker(self.platform)
        promotions_left = self._captcha_max_promotions
        last_attempt_headless = headless
        captcha_hit_overall = False

        while True:
            try:
                result = self._fetch_once(task, keyword, brands, last_attempt_headless)
            except Exception as e:
                logger.exception("baidu fetch raised: %s", e)
                breaker.record_failure()
                return MonitorResult(
                    task_id=task.id or 0,
                    checked_at=datetime.utcnow(),
                    status="failed",
                    rank=-1,
                    error_message=f"adapter exception: {e!r}",
                )

            captcha_hit_overall = captcha_hit_overall or result.metric.get("captcha_hit", False)
            if result.status == "risk_control" and result.metric.get("captcha_hit"):
                if promotions_left > 0 and last_attempt_headless:
                    logger.info(
                        "baidu captcha hit; promoting to visible (%d promotions left)",
                        promotions_left,
                    )
                    promotions_left -= 1
                    last_attempt_headless = False
                    continue
                # 用尽升级机会，或者本来就在 visible 还命中
                result.metric["captcha_hit"] = True
                breaker.record_failure()
                return result

            if result.status == "ok":
                breaker.record_success()
            else:
                breaker.record_failure()
            # 把 captcha_hit_overall 写回去，前端用得到
            result.metric["captcha_hit"] = captcha_hit_overall
            return result

    def _fetch_once(
        self,
        task: MonitorTask,
        keyword: str,
        brands: list[str],
        headless: bool,
    ) -> MonitorResult:
        """一次完整 SERP→解 link→抓正文→打分。"""
        serp_url = "https://www.baidu.com/s?wd=" + quote(keyword)
        now = datetime.utcnow()
        empty_metric = {
            "search_keyword": keyword,
            "target_brands": brands,
            "serp_url": serp_url,
            "default_results": [],
            "news_results": [],
            "default_matched_count": 0,
            "default_first_rank": -1,
            "news_first_rank": -1,
            "news_present": False,
            "engine": "patchright",
            "headless": headless,
            "captcha_hit": False,
        }

        with incognito_session(headless=headless) as session:
            page = session.page
            try:
                page.goto(serp_url, wait_until="domcontentloaded", timeout=20000)
            except TypeError:
                # Test FakePage 不接受 kwargs
                page.goto(serp_url)
            except Exception as e:
                empty_metric["captcha_hit"] = False
                return MonitorResult(
                    task_id=task.id or 0,
                    checked_at=now,
                    status="failed",
                    rank=-1,
                    metric=empty_metric,
                    error_message=f"serp navigate raised: {e!r}",
                )

            landed_url = getattr(page, "url", "") or ""
            if is_baidu_captcha_url(landed_url):
                empty_metric["captcha_hit"] = True
                return MonitorResult(
                    task_id=task.id or 0,
                    checked_at=now,
                    status="risk_control",
                    rank=-1,
                    metric=empty_metric,
                    error_message=f"baidu captcha at {landed_url[:120]}",
                )

            try:
                serp_html = page.content() or ""
            except Exception as e:
                return MonitorResult(
                    task_id=task.id or 0,
                    checked_at=now,
                    status="failed",
                    rank=-1,
                    metric=empty_metric,
                    error_message=f"serp page.content raised: {e!r}",
                )

            parsed = parse_serp(serp_html)
            empty_metric["news_present"] = parsed["news_present"]

            # 抓默认搜索 + 最新资讯两组
            default_results = self._check_block(
                page, parsed["default_links"], brands, block="default",
            )
            news_results = self._check_block(
                page, parsed["news_links"], brands, block="news",
            )

            empty_metric["default_results"] = default_results
            empty_metric["news_results"] = news_results
            matched = [r for r in default_results if r.get("matches_brand")]
            empty_metric["default_matched_count"] = len(matched)
            empty_metric["default_first_rank"] = matched[0]["rank"] if matched else -1
            news_matched = [r for r in news_results if r.get("matches_brand")]
            empty_metric["news_first_rank"] = news_matched[0]["rank"] if news_matched else -1

        first_rank = empty_metric["default_first_rank"]
        return MonitorResult(
            task_id=task.id or 0,
            checked_at=now,
            status="ok",
            rank=first_rank,
            metric=empty_metric,
        )

    def _check_block(
        self,
        page: Any,
        links: list[dict[str, str]],
        brands: list[str],
        *,
        block: str,
    ) -> list[dict[str, Any]]:
        """对一组链接逐条抓正文 + 判命中。返回 1-based rank 的 dict 列表。"""
        out: list[dict[str, Any]] = []
        for i, link in enumerate(links, start=1):
            href = resolve_baidu_link(link["href"])
            host = urlparse(href).netloc or "baidu.com"

            attempt = fetch_article_http(href)
            if attempt.get("needs_browser_fallback"):
                attempt = fetch_article_browser(page, href)

            content = attempt.get("content") or ""
            matched_brand = match_brand(content, brands)
            out.append({
                "rank": i,
                "title": link.get("title", ""),
                "url": href,
                "host": host,
                "matches_brand": matched_brand is not None,
                "matched_brand": matched_brand,
                "source": attempt.get("source") or "http",
                "content_preview": content[:160],
                "fetch_error": attempt.get("fetch_error"),
            })
        return out
```

需要在文件顶部加 `from typing import Any`（如果还没）。

- [ ] **Step 4: 跑测试验证通过**

```bash
cd sidecar
python -m pytest tests/test_baidu_keyword.py -v
```

Expected: 20 PASS。

- [ ] **Step 5: 提交**

```bash
git add csm_core/monitor/platforms/baidu_keyword.py sidecar/tests/test_baidu_keyword.py
git commit -m "feat(monitor): 完整 fetch() 编排 + 验证码升级流程

熔断 → pacer → incognito session → SERP → 两组解析 → 逐链抓正文 → 打分。
命中验证码且还有升级机会 → 切 headless=False 重跑一次。"
```

---

## Task 12: SSE captcha 事件类型扩展

**Files:**
- Modify: `sidecar/csm_sidecar/services/monitor_loop.py:46`
- Test: `sidecar/tests/test_monitor_bus.py`（加一个用例）

百度 adapter 升级可见时通过 `monitor_bus.publish` 推一条 `captcha_required` 事件。`MonitorEvent.kind` 是 Literal，需要扩展。

- [ ] **Step 1: 写失败测试**

`sidecar/tests/test_monitor_bus.py` 末尾追加（如果该文件不存在的话，新建）：

```python
def test_monitor_event_kind_includes_captcha_states():
    """captcha 三个状态在 EventKind Literal 里。"""
    from typing import get_args
    from csm_sidecar.services.monitor_loop import EventKind

    args = set(get_args(EventKind))
    assert "captcha_required" in args
    assert "captcha_resolved" in args
    assert "captcha_timeout" in args
```

- [ ] **Step 2: 跑测试验证失败**

```bash
cd sidecar
python -m pytest tests/test_monitor_bus.py::test_monitor_event_kind_includes_captcha_states -v
```

Expected: FAIL。

- [ ] **Step 3: 扩展 EventKind**

`sidecar/csm_sidecar/services/monitor_loop.py:46`：

```python
EventKind = Literal["started", "finished", "alert", "failed", "tick"]
```

改成：

```python
EventKind = Literal[
    "started", "finished", "alert", "failed", "tick",
    "captcha_required", "captcha_resolved", "captcha_timeout",
]
```

- [ ] **Step 4: 跑测试验证通过**

```bash
cd sidecar
python -m pytest tests/test_monitor_bus.py -v
```

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add sidecar/csm_sidecar/services/monitor_loop.py sidecar/tests/test_monitor_bus.py
git commit -m "feat(sidecar): EventKind 加 captcha_required/resolved/timeout

复用 MonitorEvent + monitor_bus.publish 通道，
百度 adapter 升级可见时通过它推前端弹 Toast。"
```

---

## Task 13: monitor_lifecycle 挂接百度 settings

**Files:**
- Modify: `sidecar/csm_sidecar/services/monitor_lifecycle.py:50-56`
- Modify: `sidecar/csm_sidecar/services/config_service.py`（Pydantic 加字段）
- Test: 暂不加单测（lifecycle 测试基础设施较重；下面 Task 14 跑全套确认未回归）

- [ ] **Step 1: config_service 加百度字段**

打开 `sidecar/csm_sidecar/services/config_service.py`，找到 `class MonitorConfig` 或类似定义，加：

```python
class BaiduKeywordConfig(BaseModel):
    """settings.monitor.baidu_keyword.*"""
    headless_default: bool = True
    captcha_visible_timeout_s: int = 90
    captcha_max_promotions: int = 1
    serp_pacing_seconds: int = 5
    breaker_failures: int = 3
    breaker_cooldown_seconds: int = 600


class MonitorConfig(BaseModel):
    # ... existing fields ...
    baidu_keyword: BaiduKeywordConfig = Field(default_factory=BaiduKeywordConfig)
```

（如果现有 MonitorConfig 不是 BaseModel 而是 dataclass，按现有风格加 `baidu_keyword: BaiduKeywordConfig = field(default_factory=BaiduKeywordConfig)`。先 grep 验证：）

```bash
grep -n "class MonitorConfig" sidecar/csm_sidecar/services/config_service.py
```

按真实风格调整上述代码片段。

- [ ] **Step 2: monitor_lifecycle.start() 调 BAIDU.apply_settings**

`sidecar/csm_sidecar/services/monitor_lifecycle.py`，import 段加：

```python
from csm_core.monitor.platforms.baidu_keyword import ADAPTER as BAIDU_ADAPTER
```

`start()` 函数里，找到 `ZHIHU_ADAPTER.apply_settings(...)` 那段，紧接其后加：

```python
    bcfg = mcfg.baidu_keyword
    BAIDU_ADAPTER.apply_settings(
        headless_default=bcfg.headless_default,
        captcha_visible_timeout_s=bcfg.captcha_visible_timeout_s,
        captcha_max_promotions=bcfg.captcha_max_promotions,
        serp_pacing_seconds=bcfg.serp_pacing_seconds,
        breaker_failures=bcfg.breaker_failures,
        breaker_cooldown_seconds=bcfg.breaker_cooldown_seconds,
    )
```

- [ ] **Step 3: 跑全套 sidecar 测试确认未回归**

```bash
cd sidecar
python -m pytest tests/ -v
```

Expected: 全部 PASS。

- [ ] **Step 4: 提交**

```bash
git add sidecar/csm_sidecar/services/config_service.py sidecar/csm_sidecar/services/monitor_lifecycle.py
git commit -m "feat(sidecar): monitor_lifecycle 挂接百度 settings

启动时把 settings.monitor.baidu_keyword.* 灌进 BAIDU_ADAPTER。
设置页保存通道（如果项目里有自动 reload）会复用现有机制。"
```

---

## Task 14: Excel 批量导入支持百度

**Files:**
- Modify: `csm_core/monitor/excel_import.py:40-80`
- Modify: 现有 Excel 测试（如 `sidecar/tests/test_excel_import.py`）

- [ ] **Step 1: 写失败测试**

如果存在 `sidecar/tests/test_excel_import.py` 就追加，否则新建：

```python
"""Excel 批量导入百度 keyword 的回归测试。"""
from csm_core.monitor.excel_import import parse_rows


def test_excel_import_baidu_keyword_row():
    rows = [
        ["类型", "名称", "URL", "关键词", "TopN", "调度"],
        # 百度的 URL 留空（会自动从关键词派生），目标品牌词放在「关键词」列里用 | 分隔
        ["百度关键词", "百度-Claude教程",
         "search:Claude Code 教程", "Claude|Anthropic", 10, "09:00"],
    ]
    report = parse_rows(rows)
    assert report.error_count == 0, report.errors
    assert report.ok_count == 1
    task = report.tasks[0]
    assert task.type == "baidu_keyword"
    assert task.config["search_keyword"] == "Claude Code 教程"
    assert task.config["target_brands"] == ["Claude", "Anthropic"]
    assert task.target_url.startswith("https://www.baidu.com/s?wd=")
    assert task.schedule_cron == "09:00"


def test_excel_import_baidu_label_aliases():
    rows = [
        ["类型", "名称", "URL", "关键词", "TopN", "调度"],
        ["baidu_keyword", "t1", "search:test", "BrandA", 10, "manual"],
        ["baidu", "t2", "search:other", "BrandB", 10, "manual"],
    ]
    report = parse_rows(rows)
    assert report.ok_count == 2, report.errors
    assert all(t.type == "baidu_keyword" for t in report.tasks)
```

- [ ] **Step 2: 跑测试验证失败**

```bash
cd sidecar
python -m pytest tests/test_excel_import.py -v
```

Expected: FAIL（类型不识别 / config 字段不对）。

- [ ] **Step 3: 改 excel_import.py**

`csm_core/monitor/excel_import.py:40-58` 的 `_TYPE_LABEL_MAP` 末尾加：

```python
    "百度关键词": "baidu_keyword",
    "百度": "baidu_keyword",
    "baidu": "baidu_keyword",
    "baidu_keyword": "baidu_keyword",
```

`_row_to_task` 函数（`csm_core/monitor/excel_import.py:209` 附近）末尾，找到这一段：

```python
    config: dict[str, object] = {"top_n": top_n}
    if ttype == "zhihu_question":
        config["target_brand"] = str(keyword_raw).strip()
    else:
        config["my_comment_text"] = str(keyword_raw).strip()
```

改成：

```python
    config: dict[str, object] = {"top_n": top_n}
    if ttype == "zhihu_question":
        config["target_brand"] = str(keyword_raw).strip()
    elif ttype == "baidu_keyword":
        # 百度：「关键词」列里实际放的是「搜索关键词:目标品牌词|品牌词|...」格式
        # 或允许把搜索词放 URL 列、品牌词放关键词列。
        # 为简化体验，约定：
        #   - URL 列填 "search:实际搜索词"
        #   - 关键词列填 "BrandA|BrandB|..."
        # adapter 内部 fetch 时从 config.search_keyword 拼真实 URL，
        # 表里的 target_url 只是占位。
        url_text = str(url_raw).strip()
        if url_text.startswith("search:"):
            search_keyword = url_text[len("search:"):].strip()
        else:
            search_keyword = url_text  # 容错：直接当关键词
        if not search_keyword:
            raise ValueError("百度任务的搜索关键词为空")
        brands_raw = str(keyword_raw).strip()
        brands = [b.strip() for b in brands_raw.split("|") if b.strip()]
        if not brands:
            raise ValueError("百度任务的目标品牌词为空")
        from urllib.parse import quote as _quote
        # 派生 target_url —— 跟 adapter 内部规范一致
        return MonitorTask(
            type=ttype,
            name=name,
            target_url=f"https://www.baidu.com/s?wd={_quote(search_keyword)}",
            config={"search_keyword": search_keyword, "target_brands": brands},
            schedule_cron=schedule,
            enabled=True,
        )
    else:
        config["my_comment_text"] = str(keyword_raw).strip()
```

(注意：百度分支提前 `return`，因为它的 config 结构跟其他平台不同。)

另外 `csm_core/monitor/excel_import.py:73-80` 的 `TEMPLATE_SAMPLES` 加百度样例：

```python
TEMPLATE_SAMPLES = [
    ["知乎问题", "知乎-某品牌词监测", "https://www.zhihu.com/question/123456", "ACME", 10, "09:00"],
    ["B站评论", "B站-某视频评论留存", "https://www.bilibili.com/video/BV1xxxxx", "你这个测评太真实了", 20, "manual"],
    ["抖音评论", "抖音-某视频评论留存", "https://www.douyin.com/video/7300000000000000000", "支持博主", 10, "manual"],
    ["快手评论", "快手-某视频评论留存", "https://www.kuaishou.com/short-video/3xxxxxxxx", "已加购物车", 10, "manual"],
    ["百度关键词", "百度-Claude教程", "search:Claude Code 教程", "Claude|Anthropic", 10, "09:00"],
]
```

- [ ] **Step 4: 跑测试验证通过**

```bash
cd sidecar
python -m pytest tests/test_excel_import.py -v
```

Expected: 2 PASS（加全套确认不回归：`pytest tests/ -v`）。

- [ ] **Step 5: 提交**

```bash
git add csm_core/monitor/excel_import.py sidecar/tests/test_excel_import.py
git commit -m "feat(monitor): Excel 批量导入支持 baidu_keyword

URL 列填「search:关键词」，关键词列用「|」分隔多个目标品牌词。
派生 target_url = https://www.baidu.com/s?wd=...
模板样例新增百度行。"
```

---

## Task 15: 手动验证脚本

**Files:**
- Create: `scripts/manual_test_baidu.py`

跑一次真的 Chromium，把 metric JSON 吐到 stdout。**不是自动化测试** —— 是 release 前必跑的烟雾测试入口。

- [ ] **Step 1: 创建脚本**

新建 `scripts/manual_test_baidu.py`：

```python
"""手动跑一次百度 keyword 任务，不进 monitor_loop，结果打 stdout。

用法：
    cd <repo-root>
    python scripts/manual_test_baidu.py "Claude Code 教程" "Claude,Anthropic"

可选环境变量：
    BAIDU_HEADLESS=0    # 默认 1
"""
from __future__ import annotations

import json
import os
import sys

# 让脚本能 import 项目内的 csm_core
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from csm_core.monitor.base import MonitorTask
from csm_core.monitor.platforms.baidu_keyword import ADAPTER


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__, file=sys.stderr)
        return 2
    keyword = argv[1]
    brands = [b.strip() for b in argv[2].split(",") if b.strip()]
    headless = os.environ.get("BAIDU_HEADLESS", "1") == "1"

    ADAPTER.apply_settings(
        headless_default=headless,
        captcha_visible_timeout_s=90,
        captcha_max_promotions=1,
        serp_pacing_seconds=5,
        breaker_failures=3,
        breaker_cooldown_seconds=600,
    )

    task = MonitorTask(
        id=999,
        type="baidu_keyword",
        name=f"manual-{keyword}",
        target_url=f"https://www.baidu.com/s?wd={keyword}",
        config={"search_keyword": keyword, "target_brands": brands},
    )

    print(f">> headless={headless} keyword={keyword!r} brands={brands}")
    result = ADAPTER.fetch(task)
    print(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0 if result.status == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
```

- [ ] **Step 2: 烟雾测试**

```bash
# 默认 headless 跑一次冷门关键词（应该不会触发验证码）
python scripts/manual_test_baidu.py "csm sidecar tauri claude" "Claude"
```

预期：stdout 输出一份完整 metric JSON，至少 5 条 `default_results`，`status="ok"`。

如果命中验证码：
```bash
BAIDU_HEADLESS=0 python scripts/manual_test_baidu.py "csm sidecar tauri claude" "Claude"
```

应该弹出 Chromium 窗口让你手动过验证（90s 内）。

- [ ] **Step 3: 提交**

```bash
git add scripts/manual_test_baidu.py
git commit -m "test(monitor): 加 manual_test_baidu.py 烟雾测试入口

release 前必跑：真启 Chromium、真访百度、吐 metric JSON。
单测覆盖不到真浏览器与真反爬，靠这个补。"
```

---

## Task 16: PR #1 收尾 —— 自检 + 推分支

- [ ] **Step 1: 全套单测最后跑一遍**

```bash
cd sidecar
python -m pytest tests/ -v
```

Expected: 全部 PASS。

- [ ] **Step 2: lint / typecheck（如项目有 mypy/ruff 配置）**

```bash
cd sidecar
# 如有 ruff 配置
ruff check csm_sidecar/ ../csm_core/monitor/
# 如有 mypy 配置
mypy csm_sidecar/services/monitor_lifecycle.py ../csm_core/monitor/platforms/baidu_keyword.py
```

修掉任何 import 顺序 / 未使用 / 类型问题。

- [ ] **Step 3: 推分支 + 开 PR**

记忆里 `feedback_merge_flow_pr.md` 的硬约束：用户说 commit/merge → 走 PR 流程。

```bash
git push -u origin claude/brave-elbakyan-0d5933
gh pr create --title "feat(monitor): 百度关键词排名 - 后端 + 单测 (PR 1/2)" --body "$(cat <<'EOF'
## Summary
- 新增 `baidu_keyword` 监控类型：完整 platform adapter + SERP 解析 + HTTP-first 抓正文 + 浏览器 fallback
- 新增 `csm_core/monitor/drivers/incognito_session.py`：per-fetch 无痕 BrowserContext，验证码 URL 检测
- 新增 `csm_core/monitor/drivers/ua_pool.py`：从 zhihu_question 抽出的共享 UA 池
- 扩展 `EventKind` Literal 加 captcha_required/resolved/timeout
- `monitor_lifecycle` 挂接 `BAIDU_ADAPTER.apply_settings` + `MonitorConfig.baidu_keyword`
- Excel 批量导入新增百度模板行 + URL 列「search:关键词」+ 关键词列「BrandA|BrandB」语义
- 新增 readability-lxml / lxml / curl-cffi 显式依赖

## Test plan
- [x] `pytest sidecar/tests/ -v` 全过（含 SERP 解析、品牌词匹配、跳转解析、HTTP/浏览器 fallback、完整 fetch 编排）
- [x] `python scripts/manual_test_baidu.py "csm sidecar tauri claude" "Claude"` 真启 Chromium 跑通
- [ ] Settings 模型字段 `monitor.baidu_keyword.*` 在前端 PR (#2) 落地后端到端验证

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 4: 等用户审 PR / 合并**

PR 合并前 **不要** 开始 PR #2 的前端任务（前端 import 后端 EventKind / Excel 模板路径，否则会冲突）。

---

# PR #2 — 前端 + 端到端

前端任务以 Vue 组件 + 集成手测为主，单元测试空间有限。每个任务以「修改 + 浏览器/Tauri dev 跑一遍」为完成标志。

## Task 17: AddTaskModal 百度分支

**Files:**
- Modify: `frontend/src/components/monitor/AddTaskModal.vue`

- [ ] **Step 1: 读现状**

```bash
grep -n "zhihu_question\|TaskType\|baidu" frontend/src/components/monitor/AddTaskModal.vue
```

定位 task 类型选择器、配置字段表单的位置。

- [ ] **Step 2: 加 baidu_keyword 选项 + 表单**

在类型下拉选项里加：

```vue
<option value="baidu_keyword">百度关键词排名</option>
```

紧接其它平台的 v-if 分支，加：

```vue
<template v-else-if="form.type === 'baidu_keyword'">
  <FormField label="搜索关键词" required>
    <FormInput v-model="form.config.search_keyword"
               placeholder="百度搜索关键词（如：Claude Code 教程）" />
  </FormField>

  <FormField label="目标品牌词" required hint="一行一个，命中任一即标「自家」">
    <textarea v-model="targetBrandsText"
              rows="4"
              class="w-full rounded border border-gray-300 px-3 py-2"
              placeholder="Claude&#10;Anthropic&#10;..." />
  </FormField>

  <FormField label="调度">
    <ScheduleInput v-model="form.schedule_cron" />
  </FormField>

  <details class="mt-3">
    <summary class="cursor-pointer text-sm text-gray-600">高级</summary>
    <FormField label="强制可见浏览器" hint="勾选 = 不走 headless，浏览器窗口可见。仅当 settings 全局默认 headless 时有意义。">
      <FormToggle v-model="form.config.headless"
                  :true-value="false" :false-value="true" />
    </FormField>
  </details>
</template>
```

`<script setup>` 块加 `targetBrandsText` 计算属性：

```ts
const targetBrandsText = computed({
  get: () => (form.value.config.target_brands || []).join('\n'),
  set: (v: string) => {
    form.value.config.target_brands = v
      .split('\n')
      .map(s => s.trim())
      .filter(Boolean)
  },
})
```

提交前确保 `form.config` 在 type=`baidu_keyword` 时默认 `{search_keyword: "", target_brands: [], headless: true}`（在 watch type 变化时重置；不然换类型残留旧字段会让后端 422）。

- [ ] **Step 3: dev 跑一遍**

```bash
cd frontend
pnpm tauri:dev
```

监控中心 → 新建任务 → 类型选「百度关键词排名」→ 填关键词「test」+ 品牌词「Claude」→ 保存 → 列表里看到新任务，配置正确。

- [ ] **Step 4: 提交**

```bash
git add frontend/src/components/monitor/AddTaskModal.vue
git commit -m "feat(frontend): AddTaskModal 加 baidu_keyword 表单分支

搜索关键词单行 + 目标品牌词多行 + 高级里可强制可见浏览器。"
```

---

## Task 18: BatchImportTaskModal 百度模板支持

**Files:**
- Modify: `frontend/src/components/monitor/BatchImportTaskModal.vue`

后端 Excel 解析层（Task 14）已经支持 `百度关键词` 行。前端这步只需要让模板下载链接吐出新模板。

- [ ] **Step 1: 验证模板生成路径**

```bash
grep -n "write_template\|TEMPLATE_HEADERS\|监测任务批量导入" sidecar/csm_sidecar/routes/monitor.py
```

确认存在 `GET /api/monitor/batch/template` 之类端点。如果没有就跳过，UI 上的「下载模板」按钮直接调后端文件读返回——具体接入方式按现有同款代码风格走。

- [ ] **Step 2: 前端不动 / 验证**

`BatchImportTaskModal.vue` 中模板按钮通常调用统一的下载接口，无需改前端代码 —— 后端模板里已经加了百度样例（Task 14），下载得到的 xlsx 第 6 行就是百度示例。

实际跑一下：
```bash
pnpm tauri:dev
```
监控中心 → 批量导入 → 下载模板 → 打开 xlsx → 第 6 行可见「百度关键词」示例。

填一行真实数据 → 上传 → 列表里看到新建的百度 task。

- [ ] **Step 3: 如果前端实际需要改，加新的 typing**

如果 `BatchImportTaskModal.vue` 里硬编码了任务类型枚举（如 `validTypes = ['zhihu_question', ...]`），把 `'baidu_keyword'` 加进去。

```bash
grep -n "TaskType\|validTypes\|'zhihu_question'" frontend/src/components/monitor/BatchImportTaskModal.vue
```

- [ ] **Step 4: 提交（如有修改）**

```bash
git add frontend/src/components/monitor/BatchImportTaskModal.vue
git commit -m "feat(frontend): BatchImportTaskModal 接入百度批量导入

模板示例由后端 TEMPLATE_SAMPLES 提供；
前端枚举/校验如有硬编码也补上 baidu_keyword。"
```

如果没修改：跳过这个 commit。

---

## Task 19: BaiduRankingPage.vue 历史页

**Files:**
- Create: `frontend/src/components/monitor/history/BaiduRankingPage.vue`
- 参考样本: `frontend/src/components/monitor/history/ZhihuRankingPage.vue`

- [ ] **Step 1: 先读 ZhihuRankingPage 的结构**

```bash
wc -l frontend/src/components/monitor/history/ZhihuRankingPage.vue
```

> 50 行的话整文件读一遍：

```bash
head -200 frontend/src/components/monitor/history/ZhihuRankingPage.vue
```

抓住骨架（左侧 task 列表、右侧详情、趋势图、当前结果、Excel 导出按钮）。

- [ ] **Step 2: 实现 BaiduRankingPage.vue**

新建 `frontend/src/components/monitor/history/BaiduRankingPage.vue`：

```vue
<template>
  <div class="flex h-full">
    <!-- 左：任务列表 -->
    <aside class="w-72 border-r overflow-y-auto">
      <div v-for="t in tasks" :key="t.id"
           class="cursor-pointer p-3 hover:bg-gray-50"
           :class="t.id === selectedId ? 'bg-blue-50' : ''"
           @click="selectedId = t.id">
        <div class="font-medium text-sm truncate">{{ t.name }}</div>
        <div class="text-xs text-gray-500 truncate">{{ t.config?.search_keyword }}</div>
        <div class="text-xs mt-1">
          <span v-if="t.last_status === 'ok'" class="text-green-600">正常</span>
          <span v-else-if="t.last_status === 'risk_control'" class="text-yellow-600">熔断/验证码</span>
          <span v-else-if="t.last_status === 'failed'" class="text-red-600">失败</span>
          <span v-else class="text-gray-400">未跑</span>
        </div>
      </div>
    </aside>

    <!-- 右：详情 -->
    <main class="flex-1 overflow-y-auto p-4" v-if="selected">
      <header class="flex items-center justify-between mb-3">
        <div>
          <h2 class="text-lg font-semibold">{{ selected.name }}</h2>
          <a class="text-xs text-blue-600 underline"
             :href="serpUrl" target="_blank">{{ serpUrl }}</a>
        </div>
        <div class="flex gap-2">
          <Btn @click="runNow">立即执行</Btn>
          <Btn @click="exportExcel" :disabled="!latestMetric">导出 Excel</Btn>
        </div>
      </header>

      <!-- 状态徽章 -->
      <div class="text-xs text-gray-500 mb-4">
        上次检查 {{ formatDate(selected.last_check_at) }}
        · headless={{ latestMetric?.headless ? '是' : '否' }}
        · captcha {{ latestMetric?.captcha_hit ? '已命中' : '未命中' }}
      </div>

      <!-- 趋势 -->
      <Card title="近 30 天趋势" class="mb-4">
        <LineChart :data="trendData" />
      </Card>

      <!-- 默认搜索结果 -->
      <Card title="当前结果 · 默认搜索" class="mb-4">
        <table class="w-full text-sm">
          <thead><tr>
            <th class="text-left p-2 w-12">排名</th>
            <th class="text-left p-2">标题</th>
            <th class="text-left p-2 w-32">域名</th>
            <th class="text-left p-2 w-24">自家?</th>
          </tr></thead>
          <tbody>
            <tr v-for="row in latestMetric?.default_results || []" :key="row.rank"
                :class="rowClass(row)">
              <td class="p-2">{{ row.rank }}</td>
              <td class="p-2">
                <a :href="row.url" target="_blank" class="hover:underline">{{ row.title || '(无标题)' }}</a>
                <details v-if="row.content_preview" class="mt-1">
                  <summary class="text-xs text-gray-400 cursor-pointer">查看摘要</summary>
                  <div class="text-xs text-gray-600 mt-1">{{ row.content_preview }}…</div>
                </details>
              </td>
              <td class="p-2 text-gray-500">{{ row.host }}</td>
              <td class="p-2">
                <Pill v-if="row.fetch_error" tone="gray">抓取失败</Pill>
                <Pill v-else-if="row.matches_brand" tone="green">命中: {{ row.matched_brand }}</Pill>
                <Pill v-else tone="default">{{ row.host }}</Pill>
              </td>
            </tr>
          </tbody>
        </table>
      </Card>

      <!-- 最新资讯结果 -->
      <Card v-if="latestMetric?.news_present" title="当前结果 · 最新资讯" class="mb-4">
        <table class="w-full text-sm">
          <thead><tr>
            <th class="text-left p-2 w-12">排名</th>
            <th class="text-left p-2">标题</th>
            <th class="text-left p-2 w-32">域名</th>
            <th class="text-left p-2 w-24">自家?</th>
          </tr></thead>
          <tbody>
            <tr v-for="row in latestMetric.news_results || []" :key="row.rank"
                :class="rowClass(row)">
              <td class="p-2">{{ row.rank }}</td>
              <td class="p-2">
                <a :href="row.url" target="_blank" class="hover:underline">{{ row.title || '(无标题)' }}</a>
              </td>
              <td class="p-2 text-gray-500">{{ row.host }}</td>
              <td class="p-2">
                <Pill v-if="row.matches_brand" tone="green">命中: {{ row.matched_brand }}</Pill>
                <Pill v-else tone="default">{{ row.host }}</Pill>
              </td>
            </tr>
          </tbody>
        </table>
      </Card>
    </main>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import * as XLSX from 'xlsx'
import { invoke } from '@tauri-apps/api/core'

import Btn from '@/components/ui/Btn.vue'
import Card from '@/components/ui/Card.vue'
import Pill from '@/components/ui/Pill.vue'
import LineChart from './LineChart.vue'

import { useToast } from '@/composables/useToast'  // 路径按现有项目调整

interface BaiduResultRow {
  rank: number
  title: string
  url: string
  host: string
  matches_brand: boolean
  matched_brand: string | null
  source: 'http' | 'browser'
  content_preview: string
  fetch_error: string | null
}
interface BaiduMetric {
  search_keyword: string
  target_brands: string[]
  serp_url: string
  default_results: BaiduResultRow[]
  news_results: BaiduResultRow[]
  default_matched_count: number
  default_first_rank: number
  news_first_rank: number
  news_present: boolean
  engine: string
  headless: boolean
  captcha_hit: boolean
}
interface MonitorTask {
  id: number
  name: string
  type: string
  config?: { search_keyword?: string; target_brands?: string[] }
  last_check_at?: string
  last_status?: string
}
interface MonitorResult {
  task_id: number
  checked_at: string
  status: string
  rank: number
  metric: BaiduMetric
  error_message: string
}

const tasks = ref<MonitorTask[]>([])
const selectedId = ref<number | null>(null)
const history = ref<MonitorResult[]>([])
const toast = useToast()

const selected = computed(() => tasks.value.find(t => t.id === selectedId.value) || null)
const latestMetric = computed<BaiduMetric | null>(
  () => history.value[0]?.metric || null
)
const serpUrl = computed(() => latestMetric.value?.serp_url
  || (selected.value?.config?.search_keyword
      ? `https://www.baidu.com/s?wd=${encodeURIComponent(selected.value.config.search_keyword)}`
      : ''))

const trendData = computed(() => {
  // 取近 30 天每天的 default_first_rank + default_matched_count
  const rows = history.value.slice(0, 30).reverse()
  return {
    labels: rows.map(r => r.checked_at.slice(5, 10)),
    datasets: [
      { label: '首条排名', data: rows.map(r => r.metric.default_first_rank > 0 ? r.metric.default_first_rank : null), yAxisID: 'rank' },
      { label: '自家命中数', data: rows.map(r => r.metric.default_matched_count), yAxisID: 'count' },
    ],
  }
})

function rowClass(row: BaiduResultRow) {
  if (row.fetch_error) return 'bg-gray-50'
  if (row.matches_brand) return 'bg-green-50'
  return ''
}

function formatDate(s: string | undefined) {
  if (!s) return '从未'
  return new Date(s).toLocaleString()
}

async function loadTasks() {
  const r = await fetch('/api/monitor/tasks?type=baidu_keyword')
  const j = await r.json()
  tasks.value = j.tasks
  if (!selectedId.value && tasks.value.length > 0) {
    selectedId.value = tasks.value[0].id
  }
}

async function loadHistory(taskId: number) {
  const r = await fetch(`/api/monitor/tasks/${taskId}/results?limit=30`)
  const j = await r.json()
  history.value = j.results || []
}

async function runNow() {
  if (!selected.value) return
  await fetch(`/api/monitor/tasks/${selected.value.id}/run-now`, { method: 'POST' })
  toast.info('已派发，结果会通过 SSE 流推回')
}

function exportExcel() {
  if (!latestMetric.value || !selected.value) return
  const wb = XLSX.utils.book_new()
  const headerRow = [
    '排名', '区块', '标题', '链接', '域名', '是否自家', '命中品牌', '抓取来源', '抓取错误',
  ]
  const sheet1 = [headerRow]
  for (const r of latestMetric.value.default_results || []) {
    sheet1.push([
      r.rank, '默认搜索', r.title, r.url, r.host,
      r.matches_brand ? '是' : '否',
      r.matched_brand || '',
      r.source, r.fetch_error || '',
    ])
  }
  XLSX.utils.book_append_sheet(wb, XLSX.utils.aoa_to_sheet(sheet1), '默认搜索')

  if (latestMetric.value.news_present) {
    const sheet2 = [headerRow]
    for (const r of latestMetric.value.news_results || []) {
      sheet2.push([
        r.rank, '最新资讯', r.title, r.url, r.host,
        r.matches_brand ? '是' : '否',
        r.matched_brand || '',
        r.source, r.fetch_error || '',
      ])
    }
    XLSX.utils.book_append_sheet(wb, XLSX.utils.aoa_to_sheet(sheet2), '最新资讯')
  }

  XLSX.writeFile(wb, `baidu_ranking_${selected.value.name}_${Date.now()}.xlsx`)
}

watch(selectedId, (id) => {
  if (id != null) loadHistory(id)
})

onMounted(async () => {
  await loadTasks()
})
</script>
```

注意：

- `useToast`、`Btn`/`Card`/`Pill`/`LineChart` 的 import 路径**按项目现有组件路径修正**。最稳妥的方式是看 `ZhihuRankingPage.vue` 同款 import 抄。
- API 调用如果项目里走的是 axios + 鉴权拦截器，把 `fetch(...)` 换成项目的 client。
- `useToast` 如果不存在，就用 ToastContainer 暴露的全局事件方式（按现有 `ToastContainer.vue` 接口）。

- [ ] **Step 3: dev 跑一遍**

```bash
pnpm tauri:dev
```

打开监控中心 → 切到「百度关键词」tab（下个 Task 加路由）→ 列表里能看到 Task 17 创建的那个任务 → 点「立即执行」→ 等几十秒 → 看到默认搜索结果表 → 「导出 Excel」下载并打开。

如果还没接路由，直接 import 这个页面到 MonitorView 临时挂载验证。

- [ ] **Step 4: 提交**

```bash
git add frontend/src/components/monitor/history/BaiduRankingPage.vue
git commit -m "feat(frontend): BaiduRankingPage 历史详情页

仿 ZhihuRankingPage 双栏。30 天趋势 + 默认搜索 + 最新资讯
两块独立 + 行底色区分 + 摘要折叠 + Excel 导出 (Sheet1/Sheet2)。"
```

---

## Task 20: MonitorView 接入百度历史 tab

**Files:**
- Modify: `frontend/src/views/MonitorView.vue`

- [ ] **Step 1: 找到 tab 切换代码**

```bash
grep -n "ZhihuRankingPage\|RetentionPage\|历史\|history" frontend/src/views/MonitorView.vue
```

定位 history tab 的渲染分支。

- [ ] **Step 2: 加百度 tab**

按现有 tab 模式加一个，比如：

```vue
<!-- tab 头 -->
<button @click="historyTab = 'baidu'"
        :class="historyTab === 'baidu' ? 'active-tab-class' : ''">
  百度关键词
</button>

<!-- tab 内容 -->
<BaiduRankingPage v-else-if="historyTab === 'baidu'" />
```

`<script setup>` 加 import：

```ts
import BaiduRankingPage from '@/components/monitor/history/BaiduRankingPage.vue'
```

(用现有项目代码风格 —— v-if/v-else-if 链 / 路由 view / 动态 component 都行。)

- [ ] **Step 3: dev 验证**

```bash
pnpm tauri:dev
```

监控中心 → 历史 tab → 切到「百度关键词」→ 能看到 Task 19 那个组件正常加载。

- [ ] **Step 4: 提交**

```bash
git add frontend/src/views/MonitorView.vue
git commit -m "feat(frontend): MonitorView 历史 tab 加百度关键词"
```

---

## Task 21: SettingsView 百度设置面板

**Files:**
- Modify: `frontend/src/views/SettingsView.vue`

- [ ] **Step 1: 找到现有 monitor 设置块**

```bash
grep -n "monitor\|cookie_cooldown\|zhihu\|rotation" frontend/src/views/SettingsView.vue
```

- [ ] **Step 2: 加百度设置折叠面板**

紧接知乎设置块后加：

```vue
<details class="border-t pt-3 mt-3">
  <summary class="cursor-pointer font-medium">百度关键词</summary>
  <div class="mt-3 space-y-3">
    <FormField label="默认 headless" hint="勾选则后台跑浏览器；命中验证码会自动升级可见窗口。">
      <FormToggle v-model="settings.monitor.baidu_keyword.headless_default" />
    </FormField>

    <FormField label="验证码等待时长（秒）">
      <FormInput type="number" min="30" max="300"
                 v-model.number="settings.monitor.baidu_keyword.captcha_visible_timeout_s" />
    </FormField>

    <FormField label="单任务最多升级次数">
      <FormInput type="number" min="0" max="3"
                 v-model.number="settings.monitor.baidu_keyword.captcha_max_promotions" />
    </FormField>

    <FormField label="SERP 节流（秒）" hint="跨任务 SERP 最小间隔；实际抖动取 [N, 2N]。">
      <FormInput type="number" min="1" max="60"
                 v-model.number="settings.monitor.baidu_keyword.serp_pacing_seconds" />
    </FormField>

    <FormField label="熔断失败阈值">
      <FormInput type="number" min="1" max="10"
                 v-model.number="settings.monitor.baidu_keyword.breaker_failures" />
    </FormField>

    <FormField label="熔断恢复时长（秒）">
      <FormInput type="number" min="60" max="3600"
                 v-model.number="settings.monitor.baidu_keyword.breaker_cooldown_seconds" />
    </FormField>
  </div>
</details>
```

- [ ] **Step 3: dev 验证**

```bash
pnpm tauri:dev
```

设置 → 监控 → 百度关键词折叠面板能展开 → 改一个字段 → 保存 → 重启 sidecar → 字段被持久化（看 `settings.json`）。

- [ ] **Step 4: 提交**

```bash
git add frontend/src/views/SettingsView.vue
git commit -m "feat(frontend): SettingsView 加百度关键词设置折叠面板

6 个字段：headless 默认 / 验证码超时 / 升级次数 / SERP 节流 / 熔断阈值 / 熔断恢复"
```

---

## Task 22: CookieManagerModal 隐藏百度选项

**Files:**
- Modify: `frontend/src/components/monitor/CookieManagerModal.vue`

百度任务无痕模式跑，cookie pool 对它无意义。下拉里隐掉避免误导。

- [ ] **Step 1: 找下拉选项**

```bash
grep -n "platform\|zhihu_question\|bilibili" frontend/src/components/monitor/CookieManagerModal.vue
```

- [ ] **Step 2: 排除 baidu_keyword**

如果选项是硬编码数组：直接不加 baidu_keyword（默认就不会出现）。
如果选项是从 TaskType 列表自动派生：加一个过滤：

```ts
const COOKIE_PLATFORMS = ['zhihu_question', 'bilibili_comment', 'douyin_comment', 'kuaishou_comment'] as const
// 或:
const cookiePlatforms = computed(() =>
  allPlatforms.value.filter(p => p !== 'baidu_keyword')
)
```

- [ ] **Step 3: dev 验证**

```bash
pnpm tauri:dev
```

监控中心 → cookie 管理弹窗 → platform 下拉里**没有**「百度关键词」。

- [ ] **Step 4: 提交（如有改动）**

```bash
git add frontend/src/components/monitor/CookieManagerModal.vue
git commit -m "fix(frontend): CookieManagerModal 排除 baidu_keyword

百度任务走无痕，不依赖 cookie 池；下拉里出现会误导用户。"
```

---

## Task 23: SSE captcha Toast

**Files:**
- Modify: 项目里订阅 `monitor_bus` SSE 的全局位置（通常是 `App.vue` 或专门的 monitor store）

`grep -n "monitor_bus\|/api/monitor/events\|EventSource" frontend/src/` 找出现有 SSE 订阅入口。

- [ ] **Step 1: 现有订阅函数加 captcha 分支**

定位 SSE 事件分发逻辑（一般是 switch/if 链按 `kind`）。加：

```ts
if (event.kind === 'captcha_required') {
  toast.warn(`百度要求验证码 — 浏览器已弹出，请在 ${event.timeout_s || 90} 秒内完成验证`, {
    duration: 90000,
  })
} else if (event.kind === 'captcha_resolved') {
  toast.success('已通过验证码，继续抓取')
} else if (event.kind === 'captcha_timeout') {
  toast.error('验证码等待超时，任务已标记为失败')
}
```

Toast 调用按现有 `ToastContainer.vue` 暴露的 API。

- [ ] **Step 2: 适配 monitor_loop publish 路径**

Captcha 事件需要 monitor_loop 真正 publish。回到后端：

- 修改 `csm_sidecar/services/monitor_loop.py`：在 task 派发循环里，监听 adapter fetch 结果 `metric.captcha_hit` 字段。如果当前结果 `metric.headless` 是 `False`（说明已升级），不再推 `captcha_required`。

但更简洁的做法是 adapter 在升级前直接调 `monitor_bus.publish(MonitorEvent(kind="captcha_required", ...))`。这意味着 adapter 需要拿到 bus 引用 —— 通过 `apply_settings` 注入：

`baidu_keyword.py` 加：

```python
class BaiduKeywordAdapter:
    def __init__(self) -> None:
        ...
        self._event_sink: Any = None

    def apply_settings(
        self,
        ...,
        event_sink: Any = None,
    ) -> None:
        ...
        if event_sink is not None:
            self._event_sink = event_sink
```

`monitor_lifecycle.start()` 改为：

```python
    BAIDU_ADAPTER.apply_settings(
        ...,
        event_sink=monitor_bus.publish,
    )
```

`_fetch_with_promotion` 升级处加：

```python
if promotions_left > 0 and last_attempt_headless:
    if self._event_sink:
        from sidecar.csm_sidecar.services.monitor_loop import MonitorEvent
        self._event_sink(MonitorEvent(
            kind="captcha_required",
            task_id=task.id or 0,
            at=datetime.utcnow(),
        ))
    promotions_left -= 1
    last_attempt_headless = False
    continue
```

(写死的 import 路径不漂亮但能跑；项目里如果 MonitorEvent 已经在 csm_core 共享层就更好。)

- [ ] **Step 3: dev 验证**

```bash
pnpm tauri:dev
```

跑一个百度任务（用容易触发验证码的高频关键词，或手动 mock：临时改 `baidu_keyword.py` 让 `is_baidu_captcha_url` 总返回 True）→ Toast 出现「百度要求验证码」。

- [ ] **Step 4: 提交**

```bash
git add csm_core/monitor/platforms/baidu_keyword.py \
        sidecar/csm_sidecar/services/monitor_lifecycle.py \
        frontend/src/<sse 文件> \
        frontend/src/App.vue
git commit -m "feat: SSE captcha 事件链路打通

adapter 升级前 publish captcha_required；
前端 Toast 提示用户 90s 内过验证。"
```

---

## Task 24: PR #2 收尾 + release 实跑

- [ ] **Step 1: 跑 `tauri:build --release`**

```bash
cd frontend
pnpm tauri:build
```

预期产出 `frontend/src-tauri/target/release/bundle/nsis/<name>-setup.exe`。

- [ ] **Step 2: 卸载旧版 + 安装新版**

按 memory 里 `feedback_csm_release_pipeline_lessons.md` 第 7 条：install dir ≠ data dir。先用控制面板卸载现有 v0.4.6 → 安装新构建。

- [ ] **Step 3: release 实跑清单**

按 spec §8.3 全过一遍：

- [ ] 创建 baidu_keyword 任务 → 立即执行 → 历史页看到结果
- [ ] 批量导入 Excel 5 行 → 5 个百度任务建出来
- [ ] 跑完导出 Excel，链接可点、Sheet1/Sheet2 列对齐
- [ ] 验证 patchright onefile 不爆 0xc0000409
- [ ] `PLAYWRIGHT_BROWSERS_PATH` 在 `%LOCALAPPDATA%\ms-playwright` 工作正常
- [ ] readability-lxml 在 onefile 下能 import（手动测一个常规 article URL，sidecar 日志里看是否走 `source=http`）
- [ ] 故意触发验证码（同关键词连跑 20 次或手动 mock），Toast 出现 + 可见窗口弹出 + 90s 过验证 → 继续抓

- [ ] **Step 4: 三处版本号一起 bump**

按 memory `feedback_csm_release_pipeline_lessons.md` 第 6 条：

```bash
grep -n "0.4.6" frontend/package.json frontend/src-tauri/Cargo.toml frontend/src-tauri/tauri.conf.json
```

三处一致改成 `0.4.7`（或 `0.5.0`，按 release 习惯）。

- [ ] **Step 5: 推 PR #2 + 等用户合 + 发版**

```bash
git push
gh pr create --title "feat(monitor): 百度关键词排名 - 前端 + 端到端 (PR 2/2)" --body "$(cat <<'EOF'
## Summary
- 监控中心新增「百度关键词」task 类型表单（AddTaskModal）
- 新增 `BaiduRankingPage` 历史详情页（30 天趋势 + 默认搜索/最新资讯独立表 + Excel 导出）
- `MonitorView` 历史 tab 加百度入口
- `SettingsView` 加百度设置面板（headless、验证码超时、节流、熔断）
- `CookieManagerModal` 排除 baidu_keyword
- SSE captcha 事件 → 前端 Toast；adapter 通过 event_sink 推送
- 三处版本号 bump → v0.4.7

## Test plan
- [x] dev 跑通完整工作流：建任务 → 立即执行 → 历史页结果 → 导出 Excel
- [x] release 实跑全过（见上方清单）

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

合并后用 `release.py` 走现有发版流程。

---

# Self-Review Checklist

After implementing all tasks, verify:

- [ ] **Spec coverage** — 每节 spec 都能在 plan task 里找到对应实现：
  - §3 架构 → Task 2/3/6
  - §4 数据模型 → Task 1/6/11
  - §5 浏览器层 → Task 3/4/9/10/11
  - §6 前端 UI → Task 17/19/20
  - §7 设置 → Task 13/21
  - §7.3 SSE 事件 → Task 12/23
  - §7.4 打包 → Task 9/24
  - §8 测试 → Task 6-11/15/24
  - §9 上线节奏 → Task 16/24

- [ ] **依赖一致性** — `readability-lxml` 在 Task 9 加入 pyproject.toml 后，Task 11 的 fetch_article_http 才能 import 成功。运行顺序不能颠倒。

- [ ] **类型一致** —
  - `EventKind` 在 Task 12 扩展后，Task 23 的 captcha publish 才能通过 mypy
  - `MonitorTask.config` 的 `target_brands: list[str]` 在 Task 1 测试 + Task 11 实现 + Task 14 Excel 解析 + Task 17 前端表单四处保持同一形状
  - `MonitorResult.metric` 字段名（`default_results`/`news_results`/`default_first_rank`/...）在 Task 11 adapter + Task 19 前端组件 + Task 24 Excel 导出三处对齐

- [ ] **PR 边界** — PR #1 backend 测试自洽（不依赖前端任何文件）；PR #2 前端依赖 PR #1 已 merge（EventKind / Excel 模板格式）。
