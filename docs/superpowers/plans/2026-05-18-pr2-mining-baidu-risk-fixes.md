# PR 2：视频抓取治本 + 百家号风控告警 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 治本修复抖音/快手视频抓取卡登录页 + 给百家号验证码场景加 4 层风控告警 + 断点续抓 + 代理池。

**Architecture:**
1. **Risk infra**：新建 `csm_core/monitor/drivers/risk_detector.py`，提供 `detect_risk(page, response) -> RiskSignal | None`（URL/DOM/text/HTTP 4 层信号融合），baidu_keyword 和未来其他平台共用。
2. **Mining pool 化**：废弃 mining 自维护的独立 profile/cookie 注入逻辑，让 mining 走 monitor 同款 `patchright_pool`。Pool 侧统一加固反指纹（init_script + viewport randomize + UA 强制）。
3. **断点续抓**：`monitor_results.metric_json` 加 `last_resumed_keyword` 字段；任务命中风控暂停时记录已抓位置，下次"重试"从断点开始。
4. **代理池**：`<config_dir>/proxies.json` 用户自备代理列表，patchright_pool 启动时按 `rotation_strategy` 取一个 proxy，命中风控自动轮换。

**Tech Stack:** Python 3.11+ / FastAPI / Patchright（基于 Playwright fork）/ SQLite / pytest；前端 Vue 3.5 / TypeScript / Vite + vue-tsc。**前端无单元测试框架**，沿用 PR 1 同款手动 Playwright 验证。

**Spec：** [docs/superpowers/specs/2026-05-17-mining-monitor-fixes-design.md](../specs/2026-05-17-mining-monitor-fixes-design.md) §4-§5

**Branch：** `claude/bold-shannon-9a4f5d`（已基于 `f1df60f` 即 PR 1 merge 后的 main 起好）

**Worktree：** `D:\CSM\.claude\worktrees\bold-shannon-9a4f5d`

**PR 拆分可能性：** Tasks 1-4（Phase A+B：风控基础设施）跟 Tasks 5-9（Phase C+D+E+F：mining 重构 + 代理）逻辑独立，可以中途切两个 PR 上。Task 10 是收尾的前端组装，跟 5-9 一起。

---

## File Map

| 文件 | 责任 | 操作 |
|------|------|------|
| `csm_core/monitor/drivers/risk_detector.py` | 跨平台统一风控信号检测（URL/DOM/text/HTTP 4 层） | **新建** ~150 行 |
| `csm_core/monitor/drivers/incognito_session.py` | 老的 baidu URL 黑名单 | 重构成调用 risk_detector ~10 行改动 |
| `csm_core/monitor/platforms/baidu_keyword.py` | baidu adapter | 接 risk_detector + 断点续抓字段 ~50 行 |
| `csm_core/monitor/storage.py` | SQLite schema | 在 metric_json 内新增 `last_resumed_keyword` 字段（无需 ALTER TABLE，metric_json 是 JSON 列） |
| `csm_core/browser_infra/patchright_pool.py` | 共享浏览器 pool | 反指纹 init_script + viewport randomize + proxy 注入 ~80 行 |
| `csm_core/browser_infra/mining_browser.py` | 视频抓取浏览器 | 改成 patchright_pool 适配层 ~100 行重构 |
| `csm_core/mining/platforms/douyin_search.py` | 抖音搜索 | 加 DOM fallback 模式 ~40 行 |
| `csm_core/mining/platforms/kuaishou_search.py` | 快手搜索 | 加 DOM fallback 模式 ~40 行 |
| `csm_core/mining/models.py` | SearchOutcome dataclass | 加 `status: Literal["ok"\|"login_required"\|"captcha"\|"risk_control"]` 字段 ~3 行 |
| `csm_core/mining/runner.py` | mining 调度 | SSE 透传 status 字段 ~10 行 |
| `sidecar/csm_sidecar/routes/mining.py` | mining API | 新增 `GET /api/mining/credentials` ~15 行 |
| `sidecar/csm_sidecar/routes/monitor.py` | monitor API | 新增 `POST /api/monitor/tasks/{id}/resume` ~20 行 |
| `csm_core/config.py` | App config | 加 `proxies_path` 字段 ~5 行 |
| `frontend/src/components/mining/StartJobModal.vue` | 任务启动弹窗 | 加 credentials 预检 + warning ~30 行 |
| `frontend/src/views/MiningView.vue` | 视频抓取主页 | 任务卡 login_required / risk_control 徽章 ~20 行 |
| `frontend/src/components/monitor/history/BaiduRankingPage.vue` | 百度详情页 | 顶部 risk_control banner ~25 行 |
| `frontend/src/views/SettingsView.vue` | 设置页 | 新增「风控与代理」区块 ~50 行 |
| `sidecar/tests/test_risk_detector.py` | risk_detector 测试 | **新建** ~150 行 |
| `sidecar/tests/test_baidu_keyword.py` | baidu adapter 测试 | 补 risk_detector 集成 + 断点续抓 ~50 行 |
| `sidecar/tests/test_patchright_pool.py` | pool 测试 | 补 init_script + proxy 配置 ~60 行 |

---

## Test Environment Note

⚠️ **重要**：当前 Python 环境的 `csm_sidecar` editable install 指向 `D:\CSM\sidecar`（主仓库），不是这个 worktree。要让 pytest 用 worktree 的代码：

**Setup Task 0**（每个 task 开始 implementation 前跑一次）:
```bash
cd D:/CSM/.claude/worktrees/bold-shannon-9a4f5d/sidecar
# 用 PYTHONPATH 让 worktree 的 csm_sidecar 优先于 site-packages
export PYTHONPATH=$(pwd)
# 或者 PowerShell: $env:PYTHONPATH = (Get-Location).Path
pytest tests/test_health.py -v  # 烟雾测试
```

这一步只是确认 worktree 的 pytest 跑得通。每个 Task 的 test 步骤都默认在 worktree 的 `sidecar/` 目录里、带 `PYTHONPATH=.` 跑。

---

## Phase A：Risk Detection Infrastructure

### Task 1：新建 `risk_detector.py` 模块（TDD）

**Files:**
- Create: `csm_core/monitor/drivers/risk_detector.py`
- Create: `sidecar/tests/test_risk_detector.py`

**Goal:** 一个跨平台的"页面是否被风控"判定函数，融合 4 层信号。返回 `RiskSignal | None` —— None 代表正常。

---

- [ ] **Step 1: 写 failing test —— URL pattern 检测**

Create `sidecar/tests/test_risk_detector.py`:
```python
"""Tests for csm_core.monitor.drivers.risk_detector — 4 层风控信号融合。"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from csm_core.monitor.drivers.risk_detector import (
    RiskSignal,
    detect_risk_by_url,
    detect_risk_by_dom,
    detect_risk_by_text,
    detect_risk_by_http,
    detect_risk,
)


# ── Layer 1: URL pattern ──────────────────────────────────────────────────
class TestUrlLayer:
    @pytest.mark.parametrize("url", [
        "https://wappass.baidu.com/static/captcha/index.html",
        "https://passport.baidu.com/v2/?login",
        "https://baijiahao.baidu.com/safetycheck?id=123",
        "https://mbd.baidu.com/safe?token=abc",
        "https://www.baidu.com/captcha?from=serp",
    ])
    def test_known_captcha_url_patterns(self, url: str):
        sig = detect_risk_by_url(url)
        assert sig is not None
        assert sig.layer == "url"

    @pytest.mark.parametrize("url", [
        "https://www.baidu.com/s?wd=test",
        "https://baijiahao.baidu.com/s?id=12345",  # 正常文章页
        "https://www.zhihu.com/question/123",
    ])
    def test_normal_urls_pass(self, url: str):
        assert detect_risk_by_url(url) is None
```

---

- [ ] **Step 2: 运行测试确认失败**

```bash
cd D:/CSM/.claude/worktrees/bold-shannon-9a4f5d/sidecar
PYTHONPATH=. pytest tests/test_risk_detector.py -v
```

Expected: `ModuleNotFoundError: No module named 'csm_core.monitor.drivers.risk_detector'`

---

- [ ] **Step 3: 实现 `risk_detector.py` URL 层**

Create `csm_core/monitor/drivers/risk_detector.py`:
```python
"""跨平台风控信号检测。

提供 4 层信号融合：
- URL 模式（passport / captcha / wappass / safetycheck / mbd safe）
- DOM 元素（#captcha-mask / .passmod / [id^="wappass"] / .security-check / 百家号 .mod-error）
- 页面文案（"验证码" / "请完成验证" / "安全验证" / "网络异常" / "系统繁忙"）
- HTTP 状态 + 响应头（403/451/503 + BAIDUID_BFESS=deleted）

任一层命中即判定为风控。adapter 命中后 raise RiskControlException，
runner 捕获暂停任务 + 推 SSE 风控事件给前端。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

RiskLayer = Literal["url", "dom", "text", "http"]


@dataclass(frozen=True)
class RiskSignal:
    """命中的风控信号。所有 detect_risk_by_* 函数返回 RiskSignal | None。"""
    layer: RiskLayer
    detail: str  # 命中的具体特征，前端 toast 用


# ── Layer 1: URL pattern ──────────────────────────────────────────────────
# Baidu 站内所有已知验证码 / 登录墙 URL 子串。命中即风控。
_URL_PATTERNS: tuple[str, ...] = (
    "wappass.baidu.com/static/captcha",
    "passport.baidu.com/v2",
    "baijiahao.baidu.com/safetycheck",
    "mbd.baidu.com/safe",
    "baidu.com/captcha",
)


def detect_risk_by_url(url: str) -> RiskSignal | None:
    """URL 子串匹配。最便宜的一层，先跑。"""
    if not url:
        return None
    for pat in _URL_PATTERNS:
        if pat in url:
            return RiskSignal(layer="url", detail=f"URL matches {pat!r}")
    return None
```

(后续 layers 在 Step 5-9 加。)

---

- [ ] **Step 4: 运行测试确认 URL 层通过**

```bash
PYTHONPATH=. pytest tests/test_risk_detector.py::TestUrlLayer -v
```

Expected: 8 PASSED (5 captcha URLs + 3 normal URLs)

---

- [ ] **Step 5: 加 DOM 层 failing test**

在 `tests/test_risk_detector.py` 末尾追加:
```python
class TestDomLayer:
    """DOM 层基于 Patchright Page.locator() 检测。用 MagicMock 模拟 page。"""

    @pytest.mark.parametrize("selector", [
        "#captcha-mask",
        ".passmod",
        '[id^="wappass"]',
        ".security-check",
        ".mod-error",       # 百家号 fallback 错误页
    ])
    def test_dom_selector_match(self, selector: str):
        page = MagicMock()
        # locator(...).count() 返回 >0 代表命中
        locator = MagicMock()
        locator.count.return_value = 1
        # 让 page.locator(sel) 只在传入 selector 时返回命中 locator
        def fake_locator(sel: str):
            mock_loc = MagicMock()
            mock_loc.count.return_value = 1 if sel == selector else 0
            return mock_loc
        page.locator = fake_locator

        sig = detect_risk_by_dom(page)
        assert sig is not None
        assert sig.layer == "dom"
        assert selector in sig.detail

    def test_dom_no_match(self):
        page = MagicMock()
        page.locator = lambda sel: MagicMock(count=lambda: 0)
        assert detect_risk_by_dom(page) is None

    def test_dom_locator_error_swallowed(self):
        """page 还没 navigate / 被关闭等异常情况 detect 不应抛。"""
        page = MagicMock()
        page.locator = MagicMock(side_effect=RuntimeError("page closed"))
        # 任何异常都视为 "无法判定"，返回 None（不抛）
        assert detect_risk_by_dom(page) is None
```

运行：
```bash
PYTHONPATH=. pytest tests/test_risk_detector.py::TestDomLayer -v
```
Expected: FAIL with `AttributeError: ... has no attribute 'detect_risk_by_dom'`

---

- [ ] **Step 6: 实现 DOM 层**

在 `risk_detector.py` 末尾追加：
```python
# ── Layer 2: DOM element ──────────────────────────────────────────────────
_DOM_SELECTORS: tuple[str, ...] = (
    "#captcha-mask",
    ".passmod",
    '[id^="wappass"]',
    ".security-check",
    ".mod-error",
)


def detect_risk_by_dom(page: Any) -> RiskSignal | None:
    """Patchright Page 上检查典型风控 DOM 元素。任何异常都吞掉返回 None
    —— 调用方拿不到判定就该跑其他层兜底，不应该被这层 crash。"""
    try:
        for sel in _DOM_SELECTORS:
            try:
                count = page.locator(sel).count()
            except Exception:
                continue
            if count > 0:
                return RiskSignal(layer="dom", detail=f"DOM matched {sel!r}")
    except Exception:
        return None
    return None
```

运行 `PYTHONPATH=. pytest tests/test_risk_detector.py::TestDomLayer -v`，期望 5 + 1 + 1 = 7 PASSED。

---

- [ ] **Step 7: 加 Text 层 failing test**

追加：
```python
class TestTextLayer:
    @pytest.mark.parametrize("text", [
        "请完成验证后继续访问",
        "页面包含 验证码 提示",
        "网络异常，请稍后重试",
        "系统繁忙，请稍后再试",
        "为了您的账号安全 请进行 安全验证",
    ])
    def test_text_phrase_match(self, text: str):
        sig = detect_risk_by_text(text)
        assert sig is not None
        assert sig.layer == "text"

    @pytest.mark.parametrize("text", [
        "<html><body>正常文章内容</body></html>",
        "搜索结果页",
        "",
    ])
    def test_text_no_match(self, text: str):
        assert detect_risk_by_text(text) is None
```

运行 `PYTHONPATH=. pytest tests/test_risk_detector.py::TestTextLayer -v`，期望 FAIL（函数未定义）。

---

- [ ] **Step 8: 实现 Text 层**

追加到 `risk_detector.py`：
```python
# ── Layer 3: Text phrase ──────────────────────────────────────────────────
_TEXT_PHRASES: re.Pattern[str] = re.compile(
    r"(验证码|请完成验证|安全验证|网络异常|系统繁忙)"
)


def detect_risk_by_text(text: str) -> RiskSignal | None:
    """页面文案匹配。需要 page.content() 抓回 HTML 后调用。"""
    if not text:
        return None
    m = _TEXT_PHRASES.search(text)
    if m is None:
        return None
    return RiskSignal(layer="text", detail=f"text contains {m.group(0)!r}")
```

运行 `PYTHONPATH=. pytest tests/test_risk_detector.py::TestTextLayer -v`，期望 5 + 3 = 8 PASSED。

---

- [ ] **Step 9: 加 HTTP 层 failing test**

追加：
```python
class TestHttpLayer:
    @pytest.mark.parametrize("status", [403, 451, 503])
    def test_status_codes(self, status: int):
        resp = MagicMock(status=status, headers={})
        sig = detect_risk_by_http(resp)
        assert sig is not None
        assert sig.layer == "http"
        assert str(status) in sig.detail

    def test_cookie_deleted_header(self):
        resp = MagicMock(status=200, headers={"set-cookie": "BAIDUID_BFESS=deleted; Path=/"})
        sig = detect_risk_by_http(resp)
        assert sig is not None
        assert "BAIDUID_BFESS=deleted" in sig.detail

    def test_normal_response(self):
        resp = MagicMock(status=200, headers={"content-type": "text/html"})
        assert detect_risk_by_http(resp) is None

    def test_response_none(self):
        assert detect_risk_by_http(None) is None
```

运行 `PYTHONPATH=. pytest tests/test_risk_detector.py::TestHttpLayer -v`，期望 FAIL。

---

- [ ] **Step 10: 实现 HTTP 层**

追加：
```python
# ── Layer 4: HTTP status + cookie ─────────────────────────────────────────
_SUSPECT_STATUS: frozenset[int] = frozenset({403, 451, 503})


def detect_risk_by_http(response: Any) -> RiskSignal | None:
    """response: Patchright Response 或带 .status / .headers 的对象。
    None 输入直接返回 None（adapter 拿不到 response 时也别 crash）。"""
    if response is None:
        return None
    try:
        status = getattr(response, "status", None)
        headers = getattr(response, "headers", {}) or {}
    except Exception:
        return None
    if isinstance(status, int) and status in _SUSPECT_STATUS:
        return RiskSignal(layer="http", detail=f"HTTP status {status}")
    cookie_header = headers.get("set-cookie", "") if isinstance(headers, dict) else ""
    if "BAIDUID_BFESS=deleted" in cookie_header:
        return RiskSignal(layer="http", detail="cookie BAIDUID_BFESS=deleted (session invalidated)")
    return None
```

运行 `PYTHONPATH=. pytest tests/test_risk_detector.py::TestHttpLayer -v`，期望 3 + 1 + 1 + 1 = 6 PASSED。

---

- [ ] **Step 11: 加融合函数 failing test**

追加：
```python
class TestFusion:
    def test_fusion_returns_first_match(self):
        """4 层任一命中即返回该层 RiskSignal。"""
        page = MagicMock()
        page.locator = lambda sel: MagicMock(count=lambda: 0)
        page.content.return_value = "<html>正常</html>"
        page.url = "https://wappass.baidu.com/static/captcha/index"  # URL 层会命中
        resp = MagicMock(status=200, headers={})

        sig = detect_risk(page, resp)
        assert sig is not None
        assert sig.layer == "url"

    def test_fusion_no_match_returns_none(self):
        page = MagicMock()
        page.locator = lambda sel: MagicMock(count=lambda: 0)
        page.content.return_value = "<html>normal page</html>"
        page.url = "https://www.baidu.com/s?wd=test"
        resp = MagicMock(status=200, headers={})
        assert detect_risk(page, resp) is None

    def test_fusion_http_layer_when_others_miss(self):
        page = MagicMock()
        page.locator = lambda sel: MagicMock(count=lambda: 0)
        page.content.return_value = "<html>blocked</html>"
        page.url = "https://www.baidu.com/s?wd=test"
        resp = MagicMock(status=403, headers={})
        sig = detect_risk(page, resp)
        assert sig is not None
        assert sig.layer == "http"
```

运行：`PYTHONPATH=. pytest tests/test_risk_detector.py::TestFusion -v`，期望 FAIL。

---

- [ ] **Step 12: 实现融合函数**

追加：
```python
# ── Fusion ────────────────────────────────────────────────────────────────
def detect_risk(page: Any, response: Any = None) -> RiskSignal | None:
    """对 page + response 跑 4 层检测，返回第一个命中。

    顺序：url → http → dom → text（按计算成本升序，先便宜的）。
    所有内部异常都吞掉 —— 检测本身崩了不应该把抓取流程一起带崩。
    """
    # URL（最便宜）
    try:
        url = getattr(page, "url", "") or ""
        sig = detect_risk_by_url(url)
        if sig:
            return sig
    except Exception:
        pass
    # HTTP
    try:
        sig = detect_risk_by_http(response)
        if sig:
            return sig
    except Exception:
        pass
    # DOM
    sig = detect_risk_by_dom(page)
    if sig:
        return sig
    # Text（最贵 —— page.content() 要拉整页 HTML）
    try:
        text = page.content()
        sig = detect_risk_by_text(text)
        if sig:
            return sig
    except Exception:
        pass
    return None


# ── Exception type for adapter use ────────────────────────────────────────
class RiskControlException(Exception):
    """adapter 命中风控时 raise，runner 捕获后任务标 risk_control。"""

    def __init__(self, signal: RiskSignal, *, progress: int | None = None) -> None:
        super().__init__(f"risk control: layer={signal.layer} detail={signal.detail}")
        self.signal = signal
        self.progress = progress  # 已抓 N 个 keyword 的位置（用于断点续抓）
```

运行 `PYTHONPATH=. pytest tests/test_risk_detector.py -v`，期望全部 22+ tests PASSED。

---

- [ ] **Step 13: Commit Task 1**

```bash
cd D:/CSM/.claude/worktrees/bold-shannon-9a4f5d
git add csm_core/monitor/drivers/risk_detector.py sidecar/tests/test_risk_detector.py
git commit -m "$(cat <<'EOF'
feat(monitor): 新增 risk_detector 模块 + 4 层风控信号检测

URL 子串 / DOM 选择器 / 页面文案 / HTTP 状态+cookie 4 层信号融合，
任一命中即判定风控。抽到独立模块给 baidu/百家号/未来其他平台共用，
取代 incognito_session.is_baidu_captcha_url() 那套只看 URL 的薄检测。

22 个单测覆盖每层 + 融合 + 异常吞噬。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2：把 `incognito_session.py` 的 URL 黑名单迁到 risk_detector

**Files:**
- Modify: `csm_core/monitor/drivers/incognito_session.py` (line 128-145 附近)

**Goal:** 老的 `_BAIDU_CAPTCHA_DOMAINS` + `is_baidu_captcha_url()` 是 risk_detector URL 层的子集。删掉重复实现，让 `is_baidu_captcha_url` 委托给 `detect_risk_by_url`。保持调用方签名不变。

---

- [ ] **Step 1: 读现状**

```bash
sed -n '125,150p' csm_core/monitor/drivers/incognito_session.py
```

Expected: 看到 `_BAIDU_CAPTCHA_DOMAINS` 元组和 `def is_baidu_captcha_url(url: str) -> bool:` 函数。

---

- [ ] **Step 2: 现有测试是否覆盖**

```bash
grep -n "is_baidu_captcha_url" sidecar/tests/test_incognito_session.py | head -5
```

记下现有 test 数量，确保 refactor 后这些 test 仍然 pass（行为不变）。

---

- [ ] **Step 3: 把 is_baidu_captcha_url 改成 detect_risk_by_url 的薄包装**

Use Edit tool. Replace:
```python
_BAIDU_CAPTCHA_DOMAINS = (
    "wappass.baidu.com/static/captcha",
    # ... existing entries
)


def is_baidu_captcha_url(url: str) -> bool:
    if not url:
        return False
    return any(d in url for d in _BAIDU_CAPTCHA_DOMAINS)
```

With:
```python
# 老的 URL 黑名单已迁到 risk_detector._URL_PATTERNS（更全的 4 层检测的一部分）。
# is_baidu_captcha_url 保留作为向后兼容 API，新代码应该直接用 detect_risk_by_url。
from csm_core.monitor.drivers.risk_detector import detect_risk_by_url


def is_baidu_captcha_url(url: str) -> bool:
    return detect_risk_by_url(url) is not None
```

---

- [ ] **Step 4: 跑现有 incognito_session 测试确认行为不变**

```bash
PYTHONPATH=. pytest tests/test_incognito_session.py -v
```

Expected: 全部原有 test PASS（已知 PATTERNS 仍命中，且 risk_detector 涵盖的 5 个 URL 模式 ⊇ 旧的 _BAIDU_CAPTCHA_DOMAINS）。如果某条 URL 老的命中、新的不命中，把它加进 `risk_detector._URL_PATTERNS`。

---

- [ ] **Step 5: Commit Task 2**

```bash
git add csm_core/monitor/drivers/incognito_session.py
git commit -m "$(cat <<'EOF'
refactor(monitor): is_baidu_captcha_url 委托给 risk_detector.detect_risk_by_url

老的 _BAIDU_CAPTCHA_DOMAINS 元组是 risk_detector URL 层的子集，
保留独立实现属于死代码。改成薄 wrapper 保留向后兼容签名，新代码应该
直接调 detect_risk_by_url 或更全的 detect_risk()。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3：baidu_keyword.py 接入 risk_detector + 抛 RiskControlException

**Files:**
- Modify: `csm_core/monitor/platforms/baidu_keyword.py`（命中风控的地方）
- Modify: `sidecar/tests/test_baidu_keyword.py`（加集成测试）

**Goal:** baidu adapter 在每抓完一个 keyword 后跑一次 `detect_risk(page, response)`。命中即 `raise RiskControlException(signal, progress=i)`，让 runner 捕获后暂停任务 + 推 SSE。

---

- [ ] **Step 1: 找到 baidu_keyword.py 当前判定风控的地方**

```bash
grep -n "is_baidu_captcha_url\|risk_control\|captcha" csm_core/monitor/platforms/baidu_keyword.py | head -10
```

记下命中位置（应该在 SERP fetch 之后、写 result 之前）。

---

- [ ] **Step 2: 加 failing test for RiskControlException**

在 `sidecar/tests/test_baidu_keyword.py` 末尾追加：
```python
class TestRiskDetectionIntegration:
    """baidu adapter 命中风控时应 raise RiskControlException(progress=i)。"""

    def test_dom_layer_triggers_risk_exception(self, monkeypatch, tmp_path):
        """page DOM 含 #captcha-mask → adapter 抓到第 3 个关键词时抛 RiskControlException(progress=2)。"""
        from csm_core.monitor.drivers.risk_detector import RiskControlException
        from csm_core.monitor.platforms.baidu_keyword import BaiduKeywordAdapter

        # 这个 test 需要 mock 完整 page + browser 行为。看到 risk_detector 后停。
        # 具体 mock 方式：在第 3 个 keyword 的 page 上注入 #captcha-mask DOM 命中。
        # 详细 mock 留在 implementation 阶段：作为 marker test 先 skip，待 Task 3 Step 4 实装填充。
        pytest.skip("TODO: implement after Task 3 Step 4 — needs full browser mock fixture")
```

（这步只是占位，确保 test 文件可被发现。Step 4 才填具体 mock。）

---

- [ ] **Step 3: 接入 risk_detector 到 baidu_keyword adapter**

定位 baidu_keyword.py 中 SERP fetch 完成、即将提取 brand match 的那一段（grep `is_baidu_captcha_url` 找到的位置）。改成：

```python
from csm_core.monitor.drivers.risk_detector import (
    detect_risk,
    RiskControlException,
)

# ... 在 fetch_serp_for_keyword 或类似函数内，page.goto 完成后:
# 跑完整 4 层检测（不只 URL）。命中即抛 RiskControlException，
# 带上当前进度（已抓 i 个关键词），runner 捕获后写断点 + 暂停任务。
risk = detect_risk(page, response)
if risk is not None:
    raise RiskControlException(risk, progress=i)
```

（具体位置和上下文要在 implementation 时根据实际代码调整。Implementer 应保留对老的 `is_baidu_captcha_url` 的调用作为内部 fallback，但新加的 detect_risk 是主路径。）

---

- [ ] **Step 4: 填充 Step 2 占位 test 的真实 mock**

替换 Step 2 写的 skip test 为真测试。用 monkeypatch 替换 baidu adapter 内部的 `detect_risk` 函数，强制第 3 次调用返回风控信号：

```python
def test_dom_layer_triggers_risk_exception(self, monkeypatch):
    from csm_core.monitor.drivers.risk_detector import RiskSignal, RiskControlException
    from csm_core.monitor.platforms import baidu_keyword

    call_count = {"n": 0}
    def fake_detect_risk(page, response):
        call_count["n"] += 1
        if call_count["n"] >= 3:
            return RiskSignal(layer="dom", detail="DOM matched '#captcha-mask'")
        return None

    monkeypatch.setattr(baidu_keyword, "detect_risk", fake_detect_risk)
    # 调用方式根据实际 baidu_keyword adapter API 调整，
    # 这里假设有一个能注入 fake page 的 helper：
    with pytest.raises(RiskControlException) as exc_info:
        # ... drive adapter through 5 keywords; expect raise on 3rd ...
        pass
    assert exc_info.value.progress == 2
    assert exc_info.value.signal.layer == "dom"
```

运行：
```bash
PYTHONPATH=. pytest tests/test_baidu_keyword.py::TestRiskDetectionIntegration -v
```
Expected: PASS。

---

- [ ] **Step 5: Commit Task 3**

```bash
git add csm_core/monitor/platforms/baidu_keyword.py sidecar/tests/test_baidu_keyword.py
git commit -m "$(cat <<'EOF'
feat(monitor/baidu): SERP 抓取每页跑 4 层风控检测，命中抛 RiskControlException

每个关键词的 SERP page.goto 完成后调 detect_risk(page, response)，
任一层命中 → raise RiskControlException(signal, progress=i)，runner
负责捕获 + 写断点 + 暂停任务。比老的只看 URL 的判定漏检率低得多。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase B：Breakpoint Resume（Task 4）

### Task 4：断点续抓 —— 任务命中风控暂停时保存 last_resumed_keyword

**Files:**
- Modify: `csm_core/monitor/storage.py`（在 MonitorResult 写入路径上保留 last_resumed_keyword）
- Modify: `csm_core/monitor/runner.py` 或 task scheduler（捕获 RiskControlException）
- Create: `sidecar/csm_sidecar/routes/monitor.py` 新增 `POST /api/monitor/tasks/{id}/resume`
- Modify: `sidecar/tests/test_baidu_keyword.py`（断点续抓 test）

**Goal:** 任务跑到第 50/93 命中风控时 → 保留前 50 的结果 + metric_json 内记 `last_resumed_keyword=51`；用户点"重试"调 resume API → 从第 51 个 keyword 继续，前 50 不重复抓。

---

- [ ] **Step 1: 决定 last_resumed_keyword 的存储位置**

读 `csm_core/monitor/storage.py` 看 MonitorResult / monitor_results schema：

```bash
grep -n "metric_json\|monitor_results\|CREATE TABLE" csm_core/monitor/storage.py | head -10
```

确认 `metric_json` 是 TEXT 列存 JSON 序列化的 metric。`last_resumed_keyword` 可以挂在这个 JSON 里，无需 schema 迁移。

---

- [ ] **Step 2: 加 storage helper test (TDD)**

在 `sidecar/tests/test_monitor_storage.py` 加（如果文件不存在新建）：
```python
def test_set_last_resumed_keyword(tmp_path, monkeypatch):
    """append_result + set_last_resumed_keyword 让下次 query 能取到断点。"""
    from csm_core.monitor import storage
    # ... 初始化 tmp storage, insert a task ...
    # write a result with last_resumed_keyword = 51
    # read latest result, expect metric_json['last_resumed_keyword'] == 51
    pass  # full test body in implementation
```

---

- [ ] **Step 3: 实现 `set_last_resumed_keyword` storage helper**

在 `csm_core/monitor/storage.py` 加：
```python
def set_last_resumed_keyword(conn, task_id: int, position: int) -> None:
    """把"下次从第 position 个 keyword 继续抓"写到最新 MonitorResult 的
    metric_json 里。如果该 task 暂无 result，不写（resume 也无意义）。"""
    row = conn.execute(
        "SELECT id, metric_json FROM monitor_results WHERE task_id=? ORDER BY checked_at DESC LIMIT 1",
        (task_id,),
    ).fetchone()
    if row is None:
        return
    import json
    metric = json.loads(row["metric_json"] or "{}")
    metric["last_resumed_keyword"] = position
    conn.execute(
        "UPDATE monitor_results SET metric_json=? WHERE id=?",
        (json.dumps(metric, ensure_ascii=False), row["id"]),
    )
    conn.commit()


def get_last_resumed_keyword(conn, task_id: int) -> int | None:
    """读断点位置；找不到返回 None。"""
    row = conn.execute(
        "SELECT metric_json FROM monitor_results WHERE task_id=? ORDER BY checked_at DESC LIMIT 1",
        (task_id,),
    ).fetchone()
    if row is None or not row["metric_json"]:
        return None
    import json
    metric = json.loads(row["metric_json"])
    v = metric.get("last_resumed_keyword")
    return v if isinstance(v, int) else None
```

---

- [ ] **Step 4: 写断点续抓 test**

在 `sidecar/tests/test_baidu_keyword.py::TestRiskDetectionIntegration` 内加:
```python
def test_resume_from_breakpoint(self, monkeypatch):
    """命中风控抛 RiskControlException(progress=50) →
    storage 内 last_resumed_keyword=51 → resume run 从第 51 开始。"""
    from csm_core.monitor import storage
    from csm_core.monitor.drivers.risk_detector import RiskControlException, RiskSignal

    # 模拟前一次跑到第 50 个 keyword 命中风控
    conn = storage.get_conn()
    task_id = storage.create_task(conn, type="baidu_keyword", name="t",
                                  target_url="https://...", config={"search_keywords": ["kw"+str(i) for i in range(100)]})
    # 写一个含 last_resumed_keyword=51 的 monitor_result
    storage.append_result(conn, task_id=task_id, status="risk_control",
                          metric={"last_resumed_keyword": 51})
    # 校验 get_last_resumed_keyword
    assert storage.get_last_resumed_keyword(conn, task_id) == 51
    # 后面接 adapter resume run, 校验它从 keyword[51] 开始拉，前 51 不重复 ——
    # 这部分需要 mock adapter scan loop，detail 在 implementation 阶段填。
```

---

- [ ] **Step 5: 实现 resume API route**

在 `sidecar/csm_sidecar/routes/monitor.py` 末尾追加（先 grep 找到现有 monitor tasks 路由位置参考风格）：
```python
@router.post("/api/monitor/tasks/{task_id}/resume")
async def resume_task(task_id: int) -> dict:
    """从上次风控暂停的断点续抓。task 必须是 risk_control 状态 + 有
    last_resumed_keyword 记录。否则等同 run-now（从第 1 个 keyword 开始）。
    """
    # ... 复用现有 run-now 的派发逻辑，多传一个 resume_from 参数到 adapter ...
    from csm_core.monitor import storage
    conn = storage.get_conn()
    resume_from = storage.get_last_resumed_keyword(conn, task_id) or 0
    # 派发任务到 MonitorLoop / scheduler，附 resume_from
    # ... actual dispatch code depends on existing run-now route ...
    return {"task_id": task_id, "resume_from": resume_from}
```

具体派发逻辑参考现有 `/api/monitor/tasks/{id}/run-now`。

---

- [ ] **Step 6: 接 runner —— RiskControlException 捕获 → 写断点 + 推 SSE**

修改 `csm_core/monitor/runner.py` 或 `sidecar/csm_sidecar/services/monitor_loop.py`：
```python
from csm_core.monitor.drivers.risk_detector import RiskControlException
from csm_core.monitor import storage

try:
    adapter.fetch(...)
except RiskControlException as e:
    # 写断点 — adapter raise 时已经把 progress=已抓个数 带上来了。
    # 下次 resume 应从 progress+1 开始（已抓 50 个，下次从 51）。
    conn = storage.get_conn()
    storage.append_result(
        conn, task_id=task.id,
        status="risk_control",
        error_message=f"layer={e.signal.layer} detail={e.signal.detail}",
        metric={"last_resumed_keyword": (e.progress or 0) + 1},
    )
    # 推 SSE 让前端 toast + 任务卡标红
    monitor_bus.publish(MonitorEvent(
        kind="task_done",
        task_id=task.id,
        status="risk_control",
        message=f"风控拦截：{e.signal.detail}（已抓 {e.progress or 0} 个，可重试续抓）",
    ))
```

具体 monitor_bus.publish 调用看现有代码风格。

---

- [ ] **Step 7: 运行所有相关 test**

```bash
PYTHONPATH=. pytest tests/test_risk_detector.py tests/test_baidu_keyword.py tests/test_monitor_storage.py -v
```

Expected: 全部 PASS。

---

- [ ] **Step 8: Commit Task 4**

```bash
git add csm_core/monitor/storage.py csm_core/monitor/runner.py sidecar/csm_sidecar/routes/monitor.py sidecar/csm_sidecar/services/monitor_loop.py sidecar/tests/
git commit -m "$(cat <<'EOF'
feat(monitor): 断点续抓 —— 命中风控时记 last_resumed_keyword，resume API 从断点起

baidu adapter raise RiskControlException(progress=i) → runner 捕获 →
append_result(status=risk_control, metric.last_resumed_keyword=i+1) →
SSE 推前端。用户点"重试"调 POST /api/monitor/tasks/{id}/resume，
adapter 拿到 resume_from 跳过前 i 个 keyword 直接从断点继续，前面已抓的
结果不丢不重复。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase C：Mining Pool Refactor（Tasks 5-6）

### Task 5：patchright_pool 反指纹加固（init_script + viewport randomize + UA 强制）

**Files:**
- Modify: `csm_core/browser_infra/patchright_pool.py`
- Modify: `sidecar/tests/test_patchright_pool.py`（或新建）

**Goal:** Pool 启动 BrowserContext 时统一注入：
- `--disable-blink-features=AutomationControlled` launch arg
- init_script 屏蔽 `navigator.webdriver` / `window.cdc_*` / 给 `navigator.plugins` 假装数据
- viewport 在 3 档预设里随机
- `extra_http_headers` 强制带 `Accept-Language: zh-CN,zh;q=0.9,en;q=0.8` 和 `sec-ch-ua` 一致 headers
- UA 从 `ua_pool.UARotator` 强制取（之前 mining 没用）

所有走 pool 的 adapter（评论 / 百度 / mining）自动受益。

---

- [ ] **Step 1: 找到 patchright_pool launch / context 创建的位置**

```bash
grep -n "launch_persistent_context\|launched_context\|init_script\|launch_args" csm_core/browser_infra/patchright_pool.py | head -10
```

记下行号。

---

- [ ] **Step 2: 写 failing test —— UA 注入**

在 `sidecar/tests/test_patchright_pool.py` 加（文件不存在则新建）:
```python
"""Stealth 加固测试 —— pool 启动的 context 必须带正确 UA / init_script / launch_args。"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from csm_core.browser_infra import patchright_pool


class TestStealthHardening:
    def test_launch_args_include_automation_disabled(self):
        """launch_args 必须包含 --disable-blink-features=AutomationControlled。"""
        args = patchright_pool._build_launch_args()
        assert "--disable-blink-features=AutomationControlled" in args

    def test_init_script_masks_webdriver(self):
        """注入的 init_script 必须有 navigator.webdriver 屏蔽。"""
        script = patchright_pool._build_init_script()
        assert "navigator" in script and "webdriver" in script

    def test_init_script_masks_cdc(self):
        """ChromeDriver 残留变量 window.cdc_* 必须屏蔽。"""
        script = patchright_pool._build_init_script()
        assert "cdc_" in script.lower()

    def test_viewport_randomization_three_buckets(self):
        """_pick_viewport() 必须返回 3 个预设 viewport 之一。"""
        seen = set()
        for _ in range(50):
            v = patchright_pool._pick_viewport()
            seen.add((v["width"], v["height"]))
        # 50 次至少应该见过 2 档（理论上 3 档随机命中率 99%+）
        expected = {(1280, 800), (1440, 900), (1366, 768)}
        assert seen.issubset(expected)
        assert len(seen) >= 2  # 大概率见过 2 档以上

    def test_extra_headers_have_accept_language(self):
        h = patchright_pool._build_extra_headers()
        assert h.get("Accept-Language", "").startswith("zh-CN")
```

运行：
```bash
PYTHONPATH=. pytest tests/test_patchright_pool.py::TestStealthHardening -v
```
Expected: FAIL (函数未定义)。

---

- [ ] **Step 3: 实现 pool stealth helpers**

在 `csm_core/browser_infra/patchright_pool.py` 加一段新 section（在 imports 之后、launch 函数之前）:
```python
# ── Stealth hardening ──────────────────────────────────────────────────────
# 抖音/快手/百家号风控查这些信号：navigator.webdriver、window.cdc_*、
# 缺少 Accept-Language、UA 不一致。统一在 pool 这层处理，所有 adapter 共享。

_VIEWPORT_BUCKETS = (
    {"width": 1280, "height": 800},
    {"width": 1440, "height": 900},
    {"width": 1366, "height": 768},
)


def _pick_viewport() -> dict[str, int]:
    """从 3 档预设里随机一个。同账户每次启动 viewport 略变，避免 fingerprint 完全一致。"""
    import random
    return random.choice(_VIEWPORT_BUCKETS)


def _build_launch_args() -> list[str]:
    """Pool 启动 Chromium 时的统一 launch args。"""
    return [
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--disable-blink-features=AutomationControlled",
        "--disable-features=IsolateOrigins,site-per-process",
    ]


def _build_init_script() -> str:
    """每个 page navigate 前注入。屏蔽 webdriver 标记 + ChromeDriver 残留 + 给 plugins 假数据。

    注意单引号 vs 双引号要小心 —— 这段 JS 会被 Patchright 直接发给浏览器。
    """
    return r"""
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN', 'zh', 'en'] });
// 屏蔽 ChromeDriver 注入的全局变量
for (const k of Object.keys(window)) {
    if (k.startsWith('cdc_') || k.startsWith('$cdc_')) {
        try { delete window[k]; } catch (e) {}
    }
}
"""


def _build_extra_headers() -> dict[str, str]:
    """Context 默认 extra_http_headers。同步语言/区域，避免 cookies 是国内账号
    但浏览器是 en-US 这种露馅。sec-ch-ua 跟 UA 大版本一致即可。"""
    return {
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "sec-ch-ua": '"Chromium";v="120", "Not_A Brand";v="24", "Google Chrome";v="120"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
    }
```

---

- [ ] **Step 4: 让 pool 的 launch_persistent_context 调用用上这些 helper**

在 patchright_pool.py 内已有的 launch_persistent_context 调用处（找到那段，可能在 `_create_context` 或 `launched_page` 之类函数里），把 launch_args 改成调 `_build_launch_args()`，viewport 改成 `_pick_viewport()`，并在 context 创建后加：

```python
context.set_extra_http_headers(_build_extra_headers())
context.add_init_script(_build_init_script())
```

同时确保 UA 来自 `ua_pool.UARotator()` 而不是默认（grep `user_agent` 看现状）。

---

- [ ] **Step 5: 运行 stealth 测试**

```bash
PYTHONPATH=. pytest tests/test_patchright_pool.py::TestStealthHardening -v
```
Expected: 5 PASSED。

---

- [ ] **Step 6: 跑现有 pool 相关测试确认无回归**

```bash
PYTHONPATH=. pytest tests/test_browser_infra_relocation.py tests/test_patchright_pool.py -v
```
Expected: 全部 PASS（包括之前的 + 新加的 5 个）。

---

- [ ] **Step 7: Commit Task 5**

```bash
git add csm_core/browser_infra/patchright_pool.py sidecar/tests/test_patchright_pool.py
git commit -m "$(cat <<'EOF'
feat(browser_infra): patchright_pool 加 4 项反指纹加固（适用所有 adapter）

- launch_args 加 --disable-blink-features=AutomationControlled
- 每个 context add_init_script 屏蔽 navigator.webdriver / cdc_* /
  fake navigator.plugins+languages
- viewport 在 1280x800 / 1440x900 / 1366x768 三档随机
- extra_http_headers 统一带 Accept-Language=zh-CN + sec-ch-ua 一致 headers

走 pool 的所有 adapter（评论 / 百度 / 视频）自动继承。下一任务 mining_browser
切到 pool 后视频抓取也受益。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 6：mining_browser.py 改成 patchright_pool 适配层

**Files:**
- Modify: `csm_core/browser_infra/mining_browser.py`（重构核心 launched_page 函数）
- Modify: `sidecar/tests/test_browser_infra_relocation.py` 或新建 `test_mining_browser.py`

**Goal:** `mining_browser.launched_page(platform, headless)` 从「每任务 launch_persistent_context」改成「从 patchright_pool acquire page」。保留 cookie 注入（`_inject_monitor_cookies`）和进程清理（`_kill_process_tree`）作为辅助函数复用。

调用方（`csm_core/mining/runner.py` 里的 adapter dispatch）接口不变，仍然 `with launched_page(platform, ...) as page:`。

---

- [ ] **Step 1: 读 mining_browser.py 当前状态**

```bash
wc -l csm_core/browser_infra/mining_browser.py
grep -n "^def \|^class \|launched_page\|launch_persistent_context\|patchright_pool" csm_core/browser_infra/mining_browser.py
```

记下当前 `launched_page` 函数行号 + 用到的依赖。

---

- [ ] **Step 2: 写 failing test —— launched_page 走 pool**

在 `sidecar/tests/test_mining_browser.py`（新建）加：
```python
"""mining_browser.launched_page 必须走 patchright_pool（不是自己 launch_persistent_context）。"""
from unittest.mock import MagicMock, patch
import pytest

from csm_core.browser_infra import mining_browser


def test_launched_page_uses_pool_not_persistent_context(monkeypatch):
    """mining_browser.launched_page 应通过 patchright_pool 的 acquire/release API。"""
    pool_acquire_called = {"n": 0}

    def fake_acquire(*args, **kwargs):
        pool_acquire_called["n"] += 1
        return MagicMock()  # fake page

    def fake_release(page):
        pass

    monkeypatch.setattr(
        "csm_core.browser_infra.patchright_pool.acquire_page",
        fake_acquire,
        raising=False,
    )
    monkeypatch.setattr(
        "csm_core.browser_infra.patchright_pool.release_page",
        fake_release,
        raising=False,
    )

    # mining_browser 不应该自己调 launch_persistent_context
    sync_pw_called = {"n": 0}
    def fake_sync_pw():
        sync_pw_called["n"] += 1
        raise RuntimeError("should not be called — mining_browser should delegate to pool")
    monkeypatch.setattr(
        "patchright.sync_api.sync_playwright",
        fake_sync_pw,
        raising=False,
    )

    with mining_browser.launched_page("douyin", headless=False) as page:
        assert page is not None

    assert pool_acquire_called["n"] == 1
    assert sync_pw_called["n"] == 0  # 不应该直接调 sync_playwright
```

运行 `PYTHONPATH=. pytest tests/test_mining_browser.py -v`，期望 FAIL。

---

- [ ] **Step 3: 看 patchright_pool 已有的 acquire/release API**

```bash
grep -n "^def acquire\|^def release\|^def get_page\|^def launched_page\|^def borrow" csm_core/browser_infra/patchright_pool.py | head -10
```

记下 pool 暴露给外界的 API 名字 + 签名。如果没有 `acquire_page` 而是叫 `get_page` 之类，按实际 API 调整 test + implementation。

---

- [ ] **Step 4: 重构 mining_browser.launched_page**

Replace launched_page body 的核心：
```python
@contextlib.contextmanager
def launched_page(platform: str, *, headless: bool = False) -> Iterator[Any]:
    """Context-managed Patchright Page —— 走共享 patchright_pool。

    之前的"每任务独立 profile"已废弃；改成 pool 借页，跟评论/百度 adapter 共享
    浏览器栈 + stealth 配置 + cookie storage。一次登录处处可用。
    """
    from csm_core.browser_infra import patchright_pool

    page = patchright_pool.acquire_page(
        platform=platform,
        headless=headless,
    )
    try:
        # cookies 由 pool 自己注入（同一份 monitor.db），不再这里手动 inject。
        # 但保留 _inject_monitor_cookies 函数作为 fallback 调用，给 pool
        # 还没初始化 cookies 的早期阶段兜底。
        yield page
    finally:
        patchright_pool.release_page(page)
```

老的 `launch_persistent_context` 调用 + `_kill_process_tree` 全部删除（pool 自己管理生命周期）。`_inject_monitor_cookies` 作为内部 helper 保留，但不在 launched_page 中调用。

---

- [ ] **Step 5: 跑 mining_browser test**

```bash
PYTHONPATH=. pytest tests/test_mining_browser.py -v
```
Expected: PASS。

---

- [ ] **Step 6: 端到端 mining adapter 集成 test（如果有）**

```bash
PYTHONPATH=. pytest tests/test_mining_extract_*.py -v
```
Expected: 全部 PASS（如果之前 pass，pool 切换后也应 pass —— page 接口没变）。

如有 fail，多半是 `_kill_process_tree` 调用方依赖了 mining_browser 的内部状态。修复方法：把这些依赖也走 pool。

---

- [ ] **Step 7: Commit Task 6**

```bash
git add csm_core/browser_infra/mining_browser.py sidecar/tests/test_mining_browser.py
git commit -m "$(cat <<'EOF'
refactor(mining): mining_browser.launched_page 改成 patchright_pool 适配层

废弃 mining 自维护的 launch_persistent_context 路径，改走共享
patchright_pool。视频抓取自动继承 pool 的 stealth 加固 + cookie
storage + UA 轮换，跟评论/百度 adapter 完全平权。

修复了"评论抓取能跑、视频抓取卡登录页"的割裂 —— 之前两条独立浏览器栈
反指纹强度差一档 + cookies 单向注入到新 profile 缺 storage/canvas
fingerprint 导致风控认定 cookie 盗用。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase D：Mining UX（Tasks 7-8）

### Task 7：SearchOutcome.status + /api/mining/credentials + 前端预检

**Files:**
- Modify: `csm_core/mining/models.py`（SearchOutcome 加 status 字段）
- Modify: `csm_core/mining/runner.py`（透传 status）
- Modify: `sidecar/csm_sidecar/routes/mining.py`（新增 GET /api/mining/credentials）
- Modify: `frontend/src/components/mining/StartJobModal.vue`（预检 + warning UI）

**Goal:**
- 后端：SearchOutcome 加 `status: Literal["ok","login_required","captcha","risk_control"]`，runner 捕获各类异常时填对应 status，SSE 透传。
- 后端：新增 `GET /api/mining/credentials?platform=douyin` 返回 `{has_cookies: bool, last_used: timestamp | null}`。
- 前端：StartJobModal 提交前调 credentials 端点，无 cookies 阻止 + 引导跳监控中心，cookies > 7 天显黄色 warning。

---

- [ ] **Step 1: 加 SearchOutcome.status 字段**

读 `csm_core/mining/models.py`，在 `SearchOutcome` dataclass / pydantic model 加：
```python
status: Literal["ok", "login_required", "captcha", "risk_control"] = "ok"
status_detail: str | None = None  # 给前端 toast 用
```

---

- [ ] **Step 2: 加 mining runner 异常→status 映射 test**

在 `sidecar/tests/test_mining_adapter_helpers.py` 或新建 test 加：
```python
def test_runner_login_wall_sets_login_required_status():
    """adapter 跑完发现 url 仍在登录页 → SearchOutcome.status='login_required'。"""
    # ... mock adapter.search() 返回 0 条 + page.url 含 'passport.' ...
    # ... drive runner.run_job() ...
    # ... assert outcome.status == 'login_required'
    pass

def test_runner_risk_control_sets_status():
    """adapter raise RiskControlException → SearchOutcome.status='risk_control'。"""
    pass
```

（具体 mock 在 implementation 阶段填。）

---

- [ ] **Step 3: 实现 runner 异常→status 映射**

在 `csm_core/mining/runner.py` 的 search 调用处：
```python
from csm_core.monitor.drivers.risk_detector import RiskControlException

try:
    outcome = adapter.search(...)
    # 抓完 0 条 + page URL 在登录域 → login_required
    if outcome.total == 0 and _looks_like_login_wall(page):
        outcome.status = "login_required"
        outcome.status_detail = "搜索页跳转到登录页，cookies 可能过期"
except RiskControlException as e:
    outcome = SearchOutcome(
        platform=platform, total=0, items=[],
        status="risk_control",
        status_detail=f"{e.signal.layer} - {e.signal.detail}",
    )
```

`_looks_like_login_wall(page)` 是个 helper：`return any(d in page.url for d in ("passport.", "login.", "passport.douyin.com", "id.kuaishou.com"))`。

---

- [ ] **Step 4: 新增 GET /api/mining/credentials 路由**

在 `sidecar/csm_sidecar/routes/mining.py`：
```python
from csm_core.browser_infra.mining_browser import has_login_cookie

@router.get("/api/mining/credentials")
async def mining_credentials(platform: str) -> dict:
    """前端预检 cookies 是否就绪。empty cookies → 引导用户去监控中心配登录。"""
    from csm_core.monitor import storage as monitor_storage
    # has_login_cookie 已有，加 last_used 时间戳查询
    has = has_login_cookie(platform)
    last_used = None
    if has:
        conn = monitor_storage.get_conn()
        cred_type_map = {"douyin": "douyin_comment", "bilibili": "bilibili_comment", "kuaishou": "kuaishou_comment"}
        cred_type = cred_type_map.get(platform)
        if cred_type:
            row = conn.execute(
                "SELECT last_used_at FROM platform_credentials WHERE platform=? AND enabled=1 ORDER BY last_used_at DESC NULLS LAST LIMIT 1",
                (cred_type,),
            ).fetchone()
            if row and row["last_used_at"]:
                last_used = row["last_used_at"]
    return {"has_cookies": has, "last_used": last_used, "platform": platform}
```

加 test：
```python
def test_mining_credentials_endpoint(client):
    """GET /api/mining/credentials?platform=douyin 返回 has_cookies + last_used。"""
    r = client.get("/api/mining/credentials?platform=douyin")
    assert r.status_code == 200
    data = r.json()
    assert "has_cookies" in data and "last_used" in data and data["platform"] == "douyin"
```

---

- [ ] **Step 5: 前端 StartJobModal 预检**

读 `frontend/src/components/mining/StartJobModal.vue`，找到提交按钮的 click handler。在 POST `/api/mining/jobs` 之前加预检：

```ts
async function submit() {
  // 预检每个选中平台的 cookies 状态
  for (const platform of selectedPlatforms.value) {
    const r = await sidecar.client.get(`/api/mining/credentials?platform=${platform}`);
    if (!r.data.has_cookies) {
      toast.error(`未配置 ${platform} 登录凭据，请先到「监控中心 → 凭据管理」登录`);
      // 跳转到监控中心引导
      router.push({ path: "/monitor", query: { tab: "comment", subtab: platform } });
      return;
    }
    if (r.data.last_used) {
      const ageSeconds = (Date.now() - new Date(r.data.last_used).getTime()) / 1000;
      if (ageSeconds > 7 * 86400) {
        toast.warn(`${platform} cookies 已 ${Math.floor(ageSeconds / 86400)} 天未用，可能过期`);
      }
    }
  }
  // ...原有 POST 逻辑保持
}
```

---

- [ ] **Step 6: 验证后端测试通过**

```bash
PYTHONPATH=. pytest tests/test_mining_*.py -v
```
Expected: 全部 PASS。

---

- [ ] **Step 7: 前端 type-check**

```bash
cd frontend && pnpm vue-tsc -b
```
Expected: 退出 0（pre-existing errors 不变）。

---

- [ ] **Step 8: Commit Task 7**

```bash
git add csm_core/mining/ sidecar/csm_sidecar/routes/mining.py sidecar/tests/ frontend/src/components/mining/StartJobModal.vue
git commit -m "$(cat <<'EOF'
feat(mining): SearchOutcome.status + /api/mining/credentials + 前端登录预检

后端：
- SearchOutcome 加 status: ok|login_required|captcha|risk_control
- runner 异常 → status 映射：RiskControlException → risk_control，
  抓 0 条且 URL 在登录域 → login_required
- 新增 GET /api/mining/credentials?platform=X，返回 has_cookies+last_used

前端：
- StartJobModal 提交前调 credentials，无 cookies 阻止 + 引导跳监控中心，
  cookies >7 天黄色 warning

替代之前"卡登录页 5 分钟才发现"的失败链路。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 8：DOM fallback for douyin_search / kuaishou_search（Layer 5a）

**Files:**
- Modify: `csm_core/mining/platforms/douyin_search.py`
- Modify: `csm_core/mining/platforms/kuaishou_search.py`
- Modify: `sidecar/tests/test_mining_extract_*.py`（补 DOM fallback 测试）

**Goal:** XHR 拦截失败 / 拿到 0 条时自动切到 DOM 解析模式（用 `page.locator('a[href*="/video/"]')` 抽视频卡片）。speed 慢 30% 但更耐反爬。

---

- [ ] **Step 1: 在 douyin_search.py / kuaishou_search.py 加 fallback_mode 配置**

读现有 search() 函数。在末尾的 `return SearchOutcome(...)` 之前加：
```python
# 如果 XHR 路径抓 0 条，自动降级到 DOM。
if not items and getattr(self, "_allow_dom_fallback", True):
    logger.info("%s_search: XHR returned 0, falling back to DOM scrape", platform)
    items = self._scrape_dom(page, target_count, on_card)
```

加 helper 方法（douyin 版）：
```python
def _scrape_dom(self, page, target_count: int, on_card: Callable) -> list[VideoCard]:
    """DOM-fallback：直接读搜索页 video 卡片元素。"""
    items = []
    # 抖音搜索页视频卡片：a[href*="/video/"]
    locators = page.locator('a[href*="/video/"]').all()
    for loc in locators[:target_count]:
        try:
            href = loc.get_attribute("href") or ""
            # 抓 inner text 当 title（粗糙但够用）
            title = (loc.text_content() or "").strip()[:200]
            if not href:
                continue
            card = VideoCard(
                platform="douyin",
                url=href if href.startswith("http") else f"https://www.douyin.com{href}",
                aweme_id=_extract_aweme_id(href),
                title=title,
                author=None,  # DOM 路径拿不到精确作者
                play_count=None,
                like_count=None,
                cover_url=None,
            )
            items.append(card)
            on_card(card)
        except Exception:
            continue
    return items
```

kuaishou 类似，selector 改成 `a[href*="/video/"]` 或快手实际的卡片 selector（查现有 DOM 解析代码）。

---

- [ ] **Step 2: 加 fallback test**

在 `sidecar/tests/test_mining_extract_douyin.py` 加：
```python
def test_dom_fallback_kicks_in_when_xhr_empty(monkeypatch):
    """XHR 拦截返回 0 → search() 应自动调 _scrape_dom 兜底。"""
    from csm_core.mining.platforms.douyin_search import DouyinSearchAdapter

    adapter = DouyinSearchAdapter()
    # mock XHR 路径返回空
    monkeypatch.setattr(adapter, "_intercept_xhr", lambda *a, **k: [])
    # mock _scrape_dom 返回 2 个 card
    fallback_called = {"n": 0}
    def fake_dom(*a, **k):
        fallback_called["n"] += 1
        return [MagicMock(url="https://www.douyin.com/video/123"), MagicMock(url="https://www.douyin.com/video/456")]
    monkeypatch.setattr(adapter, "_scrape_dom", fake_dom)
    # mock page
    page = MagicMock()
    # drive a single search call
    outcome = adapter.search(keyword="test", target_count=10, page=page, on_card=lambda c: None, on_progress=lambda *a: None)
    assert fallback_called["n"] == 1
    assert len(outcome.items) == 2
```

```bash
PYTHONPATH=. pytest tests/test_mining_extract_douyin.py -v
```

---

- [ ] **Step 3: Commit Task 8**

```bash
git add csm_core/mining/platforms/ sidecar/tests/test_mining_extract_*.py
git commit -m "$(cat <<'EOF'
feat(mining): douyin/kuaishou XHR 失败时自动降到 DOM 解析（5a 降级）

XHR 路径返回 0 条 → 自动调 _scrape_dom 用 page.locator('a[href*="/video/"]')
抽视频 URL 兜底。慢 30% 但跨过签名 + 反指纹拦截。精确字段（播放量/点赞）
None 占位 —— 数据采集任务"有 vs 无"比"精确"重要。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase E：Proxy Pool（Task 9）

### Task 9：代理池配置 + patchright_pool proxy 注入 + Settings UI

**Files:**
- Modify: `csm_core/config.py`（加 proxies_path 字段）
- Create: `csm_core/browser_infra/proxy_pool.py`（新建：proxies.json 加载 + 轮换策略）
- Modify: `csm_core/browser_infra/patchright_pool.py`（launch 时 inject proxy）
- Modify: `frontend/src/views/SettingsView.vue`（「风控与代理」section）
- Create: `sidecar/tests/test_proxy_pool.py`

**Goal:** 用户在 `<config_dir>/proxies.json` 自备代理列表，pool 启动时按 `rotation_strategy`（默认 `on_risk_control`）取一个，命中风控后下次启动换 IP。Settings 提供文件路径配置 + 状态显示（启用/失效代理数）。

---

- [ ] **Step 1: 写 failing test —— ProxyPool 加载 + 轮换**

Create `sidecar/tests/test_proxy_pool.py`:
```python
"""ProxyPool —— proxies.json 解析 + 轮换策略。"""
import json
import tempfile
from pathlib import Path

import pytest


def test_proxypool_loads_json(tmp_path):
    from csm_core.browser_infra.proxy_pool import ProxyPool

    config = {
        "enabled": True,
        "rotation_strategy": "on_risk_control",
        "proxies": [
            {"server": "http://user:pass@1.2.3.4:8080", "tags": ["cn"]},
            {"server": "http://5.6.7.8:8080", "tags": []},
        ],
    }
    p = tmp_path / "proxies.json"
    p.write_text(json.dumps(config), encoding="utf-8")
    pool = ProxyPool(p)
    assert pool.enabled is True
    assert len(pool.available_proxies()) == 2


def test_proxypool_disabled_returns_no_proxy(tmp_path):
    from csm_core.browser_infra.proxy_pool import ProxyPool

    p = tmp_path / "proxies.json"
    p.write_text(json.dumps({"enabled": False, "proxies": []}), encoding="utf-8")
    pool = ProxyPool(p)
    assert pool.pick() is None


def test_proxypool_rotates_on_risk_control(tmp_path):
    """rotation_strategy=on_risk_control —— 调用 mark_failed 后下次 pick 换不同 server。"""
    from csm_core.browser_infra.proxy_pool import ProxyPool

    config = {
        "enabled": True,
        "rotation_strategy": "on_risk_control",
        "proxies": [
            {"server": "http://1.1.1.1:8080"},
            {"server": "http://2.2.2.2:8080"},
        ],
    }
    p = tmp_path / "proxies.json"
    p.write_text(json.dumps(config), encoding="utf-8")
    pool = ProxyPool(p)

    first = pool.pick()
    assert first is not None
    second = pool.pick()
    # 正常情况下应该复用同一个 proxy（粘性）
    assert second == first
    # 标记失败 → 下次换
    pool.mark_failed(first)
    third = pool.pick()
    assert third is not None and third != first


def test_proxypool_disables_after_3_consecutive_failures(tmp_path):
    """连续 3 次 mark_failed 同一个 proxy → 该 proxy 进 disabled 集合。"""
    from csm_core.browser_infra.proxy_pool import ProxyPool

    config = {
        "enabled": True,
        "rotation_strategy": "on_risk_control",
        "proxies": [{"server": "http://1.1.1.1:8080"}, {"server": "http://2.2.2.2:8080"}],
    }
    p = tmp_path / "proxies.json"
    p.write_text(json.dumps(config), encoding="utf-8")
    pool = ProxyPool(p)

    px = "http://1.1.1.1:8080"
    for _ in range(3):
        pool.mark_failed(px)
    available = pool.available_proxies()
    assert px not in [p["server"] for p in available]
```

运行 `PYTHONPATH=. pytest tests/test_proxy_pool.py -v`，期望 FAIL。

---

- [ ] **Step 2: 实现 ProxyPool**

Create `csm_core/browser_infra/proxy_pool.py`:
```python
"""User-supplied HTTP/SOCKS proxy pool with rotation strategies.

Config file: <config_dir>/proxies.json
{
  "enabled": true,
  "rotation_strategy": "on_risk_control" | "per_task" | "per_request" | "daily",
  "proxies": [
    {"server": "http://user:pass@1.2.3.4:8080", "tags": ["cn", "residential"]},
    {"server": "http://5.6.7.8:8080"}
  ]
}

Default rotation strategy: on_risk_control —— 粘性，命中风控才换。
"""
from __future__ import annotations

import json
import logging
import random
import threading
from pathlib import Path
from typing import Any, Literal

logger = logging.getLogger(__name__)

RotationStrategy = Literal["on_risk_control", "per_task", "per_request", "daily"]


class ProxyPool:
    def __init__(self, config_path: Path) -> None:
        self._lock = threading.Lock()
        self._path = config_path
        self._fail_counts: dict[str, int] = {}
        self._disabled: set[str] = set()
        self._current: str | None = None
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            self.enabled = False
            self._proxies: list[dict[str, Any]] = []
            self._strategy: RotationStrategy = "on_risk_control"
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning("proxy_pool: failed to parse %s: %s", self._path, e)
            self.enabled = False
            self._proxies = []
            self._strategy = "on_risk_control"
            return
        self.enabled = bool(data.get("enabled", False))
        self._strategy = data.get("rotation_strategy", "on_risk_control")
        self._proxies = list(data.get("proxies", []))

    def available_proxies(self) -> list[dict[str, Any]]:
        return [p for p in self._proxies if p["server"] not in self._disabled]

    def pick(self) -> str | None:
        """Return current proxy server URL, or None if disabled / none available."""
        if not self.enabled:
            return None
        with self._lock:
            available = self.available_proxies()
            if not available:
                return None
            if self._strategy == "on_risk_control" and self._current and self._current not in self._disabled:
                return self._current
            # else pick a new one
            choice = random.choice(available)
            self._current = choice["server"]
            return self._current

    def mark_failed(self, server: str) -> None:
        """连续 3 次失败的 proxy 进 disabled 集合，下次 pick 跳过。"""
        with self._lock:
            self._fail_counts[server] = self._fail_counts.get(server, 0) + 1
            if self._fail_counts[server] >= 3:
                self._disabled.add(server)
                logger.warning("proxy_pool: disabling %s after 3 failures", server)
            # on_risk_control: 标记失败后清掉 current 让下次重新 pick
            if self._current == server:
                self._current = None
```

运行 `PYTHONPATH=. pytest tests/test_proxy_pool.py -v`，期望 4 PASSED。

---

- [ ] **Step 3: 在 patchright_pool launch 时 inject proxy**

在 `csm_core/browser_infra/patchright_pool.py` 的 launch 函数加：
```python
def _get_proxy_arg() -> dict | None:
    """从 ProxyPool 拿 proxy 配置；None 代表不用代理。"""
    from csm_core.config import config_service
    from csm_core.browser_infra.proxy_pool import ProxyPool
    cfg = config_service.get()
    proxies_path = getattr(cfg, "proxies_path", None)
    if not proxies_path:
        return None
    pool = ProxyPool(Path(proxies_path))
    server = pool.pick()
    if not server:
        return None
    return {"server": server}


# launch_persistent_context 的调用处加:
proxy = _get_proxy_arg()
context = pw.chromium.launch_persistent_context(
    user_data_dir=user_data_dir,
    headless=headless,
    args=_build_launch_args(),
    viewport=_pick_viewport(),
    proxy=proxy,  # ← 新增
    extra_http_headers=_build_extra_headers(),
)
```

---

- [ ] **Step 4: config.py 加 proxies_path 字段**

```python
# 在 AppConfig pydantic model 加:
proxies_path: str | None = None  # 用户自备代理 JSON 路径；None 代表不用代理
```

---

- [ ] **Step 5: 前端 SettingsView 加「风控与代理」section**

读 `frontend/src/views/SettingsView.vue` 找现有 sections。在末尾追加：
```vue
<FormSection title="风控与代理" desc="抓取频繁触发验证码时启用代理池">
  <FormPathPicker
    v-model="cfg.data.proxies_path"
    label="代理池配置文件"
    desc="proxies.json 路径，留空不启用。格式见文档。"
    @update:modelValue="(v) => cfg.patch({ proxies_path: v })"
  />
  <div v-if="proxyStatus" :style="{ color: 'var(--ink-2)', fontSize: '12px' }">
    <span v-if="proxyStatus.enabled">
      已启用：{{ proxyStatus.available_count }} 个可用代理 · {{ proxyStatus.disabled_count }} 个失效
    </span>
    <span v-else>未启用代理池</span>
  </div>
</FormSection>
```

`proxyStatus` 来自一个新加的 `GET /api/proxy/status` 路由（也在这个 Task 加）：
```python
# sidecar/csm_sidecar/routes/proxy.py (new file)
@router.get("/api/proxy/status")
async def proxy_status() -> dict:
    from csm_core.config import config_service
    from csm_core.browser_infra.proxy_pool import ProxyPool
    cfg = config_service.get()
    if not cfg.proxies_path:
        return {"enabled": False, "available_count": 0, "disabled_count": 0}
    pool = ProxyPool(Path(cfg.proxies_path))
    return {
        "enabled": pool.enabled,
        "available_count": len(pool.available_proxies()),
        "disabled_count": len(pool._disabled),
    }
```

---

- [ ] **Step 6: Commit Task 9**

```bash
git add csm_core/browser_infra/proxy_pool.py csm_core/browser_infra/patchright_pool.py csm_core/config.py sidecar/csm_sidecar/routes/ sidecar/tests/test_proxy_pool.py frontend/src/views/SettingsView.vue
git commit -m "$(cat <<'EOF'
feat(infra): 用户自备代理池 —— proxies.json + on_risk_control 轮换

新建 csm_core/browser_infra/proxy_pool.py：解析 <config_dir>/proxies.json，
4 种轮换策略（默认 on_risk_control 粘性，命中风控才换）。连续 3 次失败
自动 disable。patchright_pool launch 时 inject proxy 参数。

前端 Settings 加「风控与代理」section + GET /api/proxy/status 显示
可用 / 失效代理数。代理由用户自备（HTTP/SOCKS5 URL），不内置任何
付费服务集成。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase F：Frontend Risk UX（Task 10）

### Task 10：风控 UX 收尾 —— BaiduRankingPage banner + MiningView 徽章

**Files:**
- Modify: `frontend/src/components/monitor/history/BaiduRankingPage.vue`（详情页顶部 risk_control banner）
- Modify: `frontend/src/views/MiningView.vue`（任务卡 login_required / risk_control 徽章 + "重新登录" / "重试" 按钮）

**Goal:** 把后端推上来的 status / risk_control 事件可视化在前端。用户能一眼看到"哪个任务被风控了 + 为什么 + 怎么修"。

---

- [ ] **Step 1: BaiduRankingPage 顶部 banner**

在 selectedTask 卡片顶部加：
```vue
<div
  v-if="selectedTask?.last_status === 'risk_control'"
  class="mb-3 rounded p-3 text-[12.5px]"
  :style="{ background: '#fff4eb', border: '1px solid #ff8a4c', color: '#c75216' }"
>
  ⚠ 上次抓取被风控拦截
  <div :style="{ color: 'var(--ink-3)', fontSize: '11px', marginTop: '4px' }">
    {{ selectedTask.last_error || '未知信号' }}
  </div>
  <Btn size="sm" tone="primary" @click="resumeTask" style="margin-top: 8px">
    从断点续抓
  </Btn>
</div>
```

`resumeTask` handler:
```ts
async function resumeTask() {
  if (!selectedTask.value?.id) return;
  await sidecar.client.post(`/api/monitor/tasks/${selectedTask.value.id}/resume`);
  toast.success("已派发续抓任务");
  await loadHistory();
}
```

---

- [ ] **Step 2: MiningView 任务卡状态徽章**

读 MiningView 找到任务卡渲染处。每张卡加：
```vue
<Pill v-if="job.status === 'login_required'" tone="alert">需重新登录</Pill>
<Pill v-else-if="job.status === 'risk_control'" tone="warn">已被风控</Pill>
<Pill v-else-if="job.status === 'ok'" tone="ok">正常</Pill>
```

login_required 卡上加按钮：
```vue
<Btn v-if="job.status === 'login_required'" size="sm" @click="goToLogin(job.platform)">
  重新登录
</Btn>
```

---

- [ ] **Step 3: 前端 type-check + build**

```bash
cd frontend && pnpm vue-tsc -b && pnpm build
```
Expected: 0 new errors，build 成功。

---

- [ ] **Step 4: Commit Task 10**

```bash
git add frontend/src/components/monitor/history/BaiduRankingPage.vue frontend/src/views/MiningView.vue
git commit -m "$(cat <<'EOF'
feat(monitor/mining): 前端风控 UX —— 详情页 banner + 任务卡徽章 + 重试按钮

BaiduRankingPage：last_status='risk_control' 任务在详情页顶部显橙色
banner，含信号说明 + "从断点续抓"按钮（调 POST /api/monitor/tasks/{id}/resume）。

MiningView：任务卡按 status 显徽章 ——
- login_required（红）+ "重新登录"按钮跳监控中心
- risk_control（黄）
- ok（绿）

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 11：端到端验证 + cleanup

**Files:** 无修改。

---

- [ ] **Step 1: 全量构建验证**

```bash
cd D:/CSM/.claude/worktrees/bold-shannon-9a4f5d
# 后端测试
cd sidecar && PYTHONPATH=. pytest tests/ -v 2>&1 | tail -30
# 前端构建
cd ../frontend && pnpm vue-tsc -b && pnpm build
```

期望：后端所有 tests pass；前端 vue-tsc 0 new errors，build 成功。

---

- [ ] **Step 2: 手动 dev 验证（参考 PR 1 的 setup）**

按 PR 1 流程起 sidecar + Vite，浏览器开 http://localhost:5174/。验证以下场景：

1. **未配置抖音 cookies 时启动视频抓取** → StartJobModal 阻止 + 引导跳监控中心
2. **抖音抓取正常** → 任务卡显绿色"正常"徽章
3. **百度任务命中模拟风控**（用 monkeypatch 注入 fake risk_signal）→ 详情页顶部红 banner + "从断点续抓"按钮可点
4. **Settings → 风控与代理 section** → 显示代理状态（未配置 / N 可用）

---

- [ ] **Step 3: 清理测试残留**

```bash
# 删测试任务（如果验证时建了）；删 .playwright-mcp/ 残留
rm -rf .playwright-mcp/
git status --short  # 应为干净
```

---

- [ ] **Step 4: Push branch + 开 PR**

```bash
git push -u origin claude/bold-shannon-9a4f5d
gh pr create --base main --title "feat(monitor+mining): 视频抓取治本 + 百家号风控告警 + 断点续抓 + 代理池" \
  --body "$(cat <<'EOF'
... 详细 PR body，列 10 个 commit + 测试结论 ...
EOF
)"
```

---

## Self-Review 清单

**Spec coverage:**
- ✅ Spec §4 第 1 层（前端预检 + 错误透传）→ Task 7
- ✅ Spec §4 第 2+4 层（共享 patchright_pool + stealth）→ Task 5 + Task 6
- ✅ Spec §4 第 5a 层（DOM 降级）→ Task 8
- ✅ Spec §5 一（4 层风控信号检测）→ Task 1
- ✅ Spec §5 一（断点续抓）→ Task 4
- ✅ Spec §5 二（指纹伪装，pool 侧统一）→ Task 5
- ✅ Spec §5 三（IP 代理池）→ Task 9
- ✅ Spec §5 前端 UI（任务卡状态 + risk banner）→ Task 10

**Out of spec scope（按 §8 explicit）:**
- 第 5b 可视点击降级（backlog）
- 真实"百家号 scraper"（spec 没要求独立抓取器）

**Placeholder scan:** 
- Task 3 Step 2 + Step 4 留了 implementation 阶段填具体 mock 细节的 marker（pytest.skip）—— 是合理的占位，因为 mock 上下文取决于 adapter 接口
- Task 4 Step 5 / Step 6 引用 "现有 monitor_loop / runner 风格" —— implementer 应该看上下文风格写

**Type consistency:** 
- `RiskSignal`、`RiskControlException`、`SearchOutcome.status` 名字在 Task 1/3/4/7 间一致
- `acquire_page` / `release_page` 是猜测的 pool API，Task 6 Step 3 要求 implementer 先 grep 实际 API 调整
- `last_resumed_keyword` 字段名在 Task 4 全部一致

**Ambiguity check:**
- Task 2 的"删 _BAIDU_CAPTCHA_DOMAINS 老元组"：检查现有用例引用，可能 grep 出其他文件依赖。implementer 留意。
- Task 9 的 ProxyPool `_disabled` 是 set —— 写 markdown 时用 `pool._disabled` 是内部字段。test 应该改成只测公开行为（pick / mark_failed / available_proxies）。

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-18-pr2-mining-baidu-risk-fixes.md`.

**Plan size:** 10 task + 1 verify task = 11 总，估算 ~600-700 行后端代码 + ~150 行前端 + ~300 行测试。

**Possible PR split:**
- **PR 2a**（risk infra only）: Tasks 1-4 — 后端 risk_detector + baidu 接入 + 断点续抓 + resume API
- **PR 2b**（mining + UX + proxy）: Tasks 5-10 — pool stealth + mining 重构 + DOM fallback + 前端

如果 plan 跑到 task 4 后觉得 PR 已经太大，可以 push 出 PR 2a 先 merge，然后再继续 task 5+ 作为 PR 2b。

**Two execution options:**

1. **Subagent-Driven (推荐)** — 每个 task 派 fresh subagent，task 间 spec + quality 双 review，跟 PR 1 流程一样
2. **Inline Execution** — 在本会话直接做，executing-plans 批量带 checkpoints

哪种？
