# 百度抓取反风控（方案 D）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 CSM 百度抓取加"挂载用户日常 Chrome profile"模式（native mode），配上软着陆验证码 + 系统通知，让 100 词监控能流畅跑、触发风控时不丢进度。

**Architecture:** 后端在现有 Patchright 抓取链路上加 native mode 分支：跑前轮询等 Chrome 关闭、用 `channel="chrome"` + 用户 user_data_dir 启动真 Chrome、命中风控时不停掉而是把窗口拉到中央等用户解题。前端新增 Settings tab 配置 + waiting_chrome_close 倒计时 banner + Tauri 系统通知。

**Tech Stack:** Python 3 / FastAPI / Patchright / psutil / Pydantic v2 / Vue 3 / TypeScript / Tauri 2 / @tauri-apps/plugin-notification

**Spec:** [docs/superpowers/specs/2026-05-24-baidu-anti-risk-design.md](docs/superpowers/specs/2026-05-24-baidu-anti-risk-design.md)

---

## 文件结构总览

### 后端
| 操作 | 路径 | 责任 |
|---|---|---|
| 修改 | `csm_core/config.py` | 加 4 个 native mode 字段 |
| **新建** | `csm_core/monitor/drivers/chrome_detect.py` | 探测 Chrome 安装、user_data_dir、profile 列表 |
| **新建** | `csm_core/monitor/drivers/chrome_preflight.py` | 检测 Chrome 进程 + 轮询等待关闭 |
| 修改 | `csm_core/monitor/drivers/baidu_browser.py` | `baidu_browser_session()` 加 native mode 分支 |
| 修改 | `csm_core/monitor/platforms/baidu_keyword.py` | fetch 入口加 preflight + 透传 native session args + 软着陆 |
| 修改 | `sidecar/csm_sidecar/routes/monitor.py` | 5 个新 API 路由 |
| 修改 | `sidecar/csm_sidecar/services/monitor_loop.py` | EventKind + MonitorEvent 扩展 |
| 修改 | `sidecar/csm_sidecar/monitor_bus.py` | `event_to_dict` 序列化新字段 |

### 后端测试
| 操作 | 路径 |
|---|---|
| **新建** | `sidecar/tests/test_chrome_detect.py` |
| **新建** | `sidecar/tests/test_chrome_preflight.py` |
| 修改 | `sidecar/tests/test_baidu_browser.py` (加 native mode 用例) |
| 修改 | `sidecar/tests/test_baidu_keyword.py` (加 preflight + 软着陆用例) |
| 修改 | `sidecar/tests/test_monitor_routes.py` (加 5 个新 API 测试) |
| 修改 | `sidecar/tests/test_monitor_bus.py` (新 EventKind 序列化测试) |

### 前端
| 操作 | 路径 | 责任 |
|---|---|---|
| 修改 | `frontend/package.json` | 加 `@tauri-apps/plugin-notification` |
| 修改 | `frontend/src-tauri/Cargo.toml` | 加 `tauri-plugin-notification` Rust 端 |
| 修改 | `frontend/src-tauri/src/lib.rs` | 注册插件 |
| 修改 | `frontend/src-tauri/capabilities/default.json` | 加通知权限 |
| **新建** | `frontend/src/composables/useSystemNotify.ts` | 系统通知封装 |
| **新建** | `frontend/src/components/settings/BaiduScrapeSettings.vue` | Settings 新 tab 组件 |
| 修改 | `frontend/src/components/settings/SettingsModal.vue`（或现有 Settings 入口）| 接入新 tab |
| 修改 | `frontend/src/components/monitor/history/BaiduRankingPage.vue` | 加 waiting_chrome_close banner |
| 修改 | `frontend/src/stores/monitorStatus.ts` | 处理 3 个新事件 |

---

## Task 1: 扩展 BaiduKeywordConfig schema

**Files:**
- Modify: `csm_core/config.py:23-50`
- Test: `sidecar/tests/test_config_routes.py` (现有)

- [ ] **Step 1: 看现有 BaiduKeywordConfig 全貌**

Run: `Read csm_core/config.py 1-90`
确认 BaiduKeywordConfig 类的字段顺序和缩进风格。

- [ ] **Step 2: 写失败测试 — native mode 字段 round-trip**

在 `sidecar/tests/test_config_routes.py` 末尾追加：

```python
def test_baidu_keyword_config_native_mode_fields_round_trip(client):
    """新加的 4 个 native mode 字段能 GET/PATCH 正确 round-trip。"""
    resp = client.get("/api/config")
    assert resp.status_code == 200
    cfg = resp.json()
    bk = cfg["monitor"]["baidu_keyword"]
    # 默认值断言
    assert bk["use_native_chrome"] is False
    assert bk["chrome_executable_path"] is None
    assert bk["chrome_user_data_dir"] is None
    assert bk["chrome_profile_name"] == "Default"

    # PATCH 后能读到
    patch = {
        "monitor": {
            "baidu_keyword": {
                "use_native_chrome": True,
                "chrome_executable_path": "C:/test/chrome.exe",
                "chrome_user_data_dir": "C:/test/User Data",
                "chrome_profile_name": "Profile 1",
            }
        }
    }
    resp = client.patch("/api/config", json=patch)
    assert resp.status_code == 200
    bk2 = resp.json()["monitor"]["baidu_keyword"]
    assert bk2["use_native_chrome"] is True
    assert bk2["chrome_executable_path"] == "C:/test/chrome.exe"
    assert bk2["chrome_user_data_dir"] == "C:/test/User Data"
    assert bk2["chrome_profile_name"] == "Profile 1"
```

- [ ] **Step 3: 运行测试确认失败**

Run: `cd D:/CSM/.claude/worktrees/tender-brahmagupta-f4a634 && pytest sidecar/tests/test_config_routes.py::test_baidu_keyword_config_native_mode_fields_round_trip -v`
Expected: FAIL — `KeyError: 'use_native_chrome'`

- [ ] **Step 4: 修改 BaiduKeywordConfig 加 4 个字段**

在 `csm_core/config.py` 的 BaiduKeywordConfig 类里、`baijiahao_pacing_seconds` 字段之后插入：

```python
    # ── Native Chrome 模式 (方案 D) ──────────────────────────────
    # 启用后：跑监控时挂载用户日常 Chrome profile（用 channel="chrome" +
    # 用户的 user_data_dir）。需要跑前先关掉 Chrome（OS profile lock）。
    # 详见 docs/superpowers/specs/2026-05-24-baidu-anti-risk-design.md
    use_native_chrome: bool = False
    # 自动探测时为 None，UI 启用 native mode 时调 /api/monitor/baidu/detect-chrome
    chrome_executable_path: str | None = None
    chrome_user_data_dir: str | None = None
    # 多 profile 用户选哪个（"Default" / "Profile 1" / "Profile 2"...）
    chrome_profile_name: str = "Default"
```

- [ ] **Step 5: 运行测试确认通过**

Run: `cd D:/CSM/.claude/worktrees/tender-brahmagupta-f4a634 && pytest sidecar/tests/test_config_routes.py::test_baidu_keyword_config_native_mode_fields_round_trip -v`
Expected: PASS

- [ ] **Step 6: 跑全套 config 测试确保没破坏现有行为**

Run: `cd D:/CSM/.claude/worktrees/tender-brahmagupta-f4a634 && pytest sidecar/tests/test_config_routes.py -v`
Expected: ALL PASS

- [ ] **Step 7: Commit**

```bash
git -C D:/CSM/.claude/worktrees/tender-brahmagupta-f4a634 add csm_core/config.py sidecar/tests/test_config_routes.py
git -C D:/CSM/.claude/worktrees/tender-brahmagupta-f4a634 commit -m "feat(monitor): add baidu native chrome mode config fields

引入 use_native_chrome / chrome_executable_path / chrome_user_data_dir /
chrome_profile_name 四个字段。默认 False = 行为不变。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: chrome_detect.py — Chrome 安装 / profile 列表探测

**Files:**
- Create: `csm_core/monitor/drivers/chrome_detect.py`
- Create: `sidecar/tests/test_chrome_detect.py`

- [ ] **Step 1: 写失败测试 — find_chrome_executable**

新建 `sidecar/tests/test_chrome_detect.py`：

```python
"""chrome_detect.py 单元测试 —— mock 注册表 / 文件系统 / Preferences JSON。"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from csm_core.monitor.drivers import chrome_detect


# ── find_chrome_executable ───────────────────────────────────────
class TestFindChromeExecutable:
    def test_returns_registry_path_when_present(self, monkeypatch):
        """注册表查到 → 直接返回，不查文件系统。"""
        fake_path = r"C:\Custom\Chrome\chrome.exe"
        monkeypatch.setattr(chrome_detect, "_read_registry_chrome_path", lambda: fake_path)
        # 文件系统探测应该不被调用 —— 用 monkeypatch 抛异常验证
        monkeypatch.setattr(
            chrome_detect, "_find_default_install_path",
            lambda: pytest.fail("不应回退到文件系统探测"),
        )
        assert chrome_detect.find_chrome_executable() == fake_path

    def test_falls_back_to_default_path_when_no_registry(self, monkeypatch, tmp_path):
        """注册表无 → 找默认安装路径。"""
        monkeypatch.setattr(chrome_detect, "_read_registry_chrome_path", lambda: None)
        fake_default = tmp_path / "chrome.exe"
        fake_default.touch()
        monkeypatch.setattr(chrome_detect, "_find_default_install_path", lambda: str(fake_default))
        assert chrome_detect.find_chrome_executable() == str(fake_default)

    def test_returns_none_when_both_fail(self, monkeypatch):
        """注册表 + 默认路径都没 → None。"""
        monkeypatch.setattr(chrome_detect, "_read_registry_chrome_path", lambda: None)
        monkeypatch.setattr(chrome_detect, "_find_default_install_path", lambda: None)
        assert chrome_detect.find_chrome_executable() is None


# ── find_user_data_dir ───────────────────────────────────────────
class TestFindUserDataDir:
    def test_returns_localappdata_default(self, monkeypatch, tmp_path):
        fake_local = tmp_path / "AppData" / "Local"
        chrome_data = fake_local / "Google" / "Chrome" / "User Data"
        chrome_data.mkdir(parents=True)
        monkeypatch.setenv("LOCALAPPDATA", str(fake_local))
        assert chrome_detect.find_user_data_dir() == str(chrome_data)

    def test_returns_none_when_dir_missing(self, monkeypatch, tmp_path):
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))  # 不创建 Google/Chrome
        assert chrome_detect.find_user_data_dir() is None


# ── list_profiles ────────────────────────────────────────────────
class TestListProfiles:
    def test_lists_default_and_numbered_profiles_with_account_emails(self, tmp_path):
        """枚举 Default / Profile 1 / Profile 2，从 Preferences JSON 读账号 email。"""
        # 准备测试数据
        for name, email in [("Default", "user1@gmail.com"), ("Profile 1", "user2@gmail.com")]:
            p = tmp_path / name
            p.mkdir()
            (p / "Preferences").write_text(
                '{"account_info":[{"email":"' + email + '"}]}',
                encoding="utf-8",
            )
        # 无 Preferences 的 profile —— 仍列出但 email=None
        (tmp_path / "Profile 2").mkdir()

        result = chrome_detect.list_profiles(str(tmp_path))
        names = {p["name"] for p in result}
        assert names == {"Default", "Profile 1", "Profile 2"}
        by_name = {p["name"]: p for p in result}
        assert by_name["Default"]["account_email"] == "user1@gmail.com"
        assert by_name["Profile 1"]["account_email"] == "user2@gmail.com"
        assert by_name["Profile 2"]["account_email"] is None

    def test_returns_empty_when_dir_missing(self):
        assert chrome_detect.list_profiles("/nonexistent/path") == []

    def test_ignores_non_profile_directories(self, tmp_path):
        """User Data 下有 Crashpad、ShaderCache 等非 profile 目录，要跳过。"""
        (tmp_path / "Default").mkdir()
        (tmp_path / "Crashpad").mkdir()
        (tmp_path / "ShaderCache").mkdir()
        names = {p["name"] for p in chrome_detect.list_profiles(str(tmp_path))}
        assert names == {"Default"}
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd D:/CSM/.claude/worktrees/tender-brahmagupta-f4a634 && pytest sidecar/tests/test_chrome_detect.py -v`
Expected: FAIL — ModuleNotFoundError: chrome_detect

- [ ] **Step 3: 创建 chrome_detect.py 实现**

新建 `csm_core/monitor/drivers/chrome_detect.py`：

```python
"""探测用户系统中 Chrome 的安装路径、user_data_dir、profile 列表。

服务于 baidu_keyword.py 的 native mode：跑监控前需要知道用户 Chrome 在哪、
用哪个 profile。所有探测都是 best-effort —— 失败时返回 None，UI 端会让用户
手动填路径。
"""
from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_PROFILE_DIR_RE = re.compile(r"^(Default|Profile \d+)$")


# ── Chrome executable ────────────────────────────────────────────
def find_chrome_executable() -> str | None:
    """探测 chrome.exe 绝对路径。失败返回 None。

    顺序：注册表 → 默认安装路径（HKLM Program Files / Program Files (x86)）
    """
    p = _read_registry_chrome_path()
    if p:
        return p
    return _find_default_install_path()


def _read_registry_chrome_path() -> str | None:
    """读注册表 HKLM\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\App Paths\\chrome.exe
    的 (Default) 值。Windows-only；其他平台直接返回 None。
    """
    if os.name != "nt":
        return None
    try:
        import winreg  # type: ignore[import-not-found]
    except ImportError:
        return None
    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe",
        ) as key:
            value, _ = winreg.QueryValueEx(key, "")
            if value and os.path.exists(value):
                return value
    except (OSError, FileNotFoundError):
        return None
    return None


def _find_default_install_path() -> str | None:
    """fallback 到默认安装路径。"""
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return None


# ── User Data directory ──────────────────────────────────────────
def find_user_data_dir() -> str | None:
    """探测 Chrome User Data 目录绝对路径。默认 %LOCALAPPDATA%\\Google\\Chrome\\User Data。"""
    local_appdata = os.environ.get("LOCALAPPDATA")
    if not local_appdata:
        return None
    p = Path(local_appdata) / "Google" / "Chrome" / "User Data"
    if p.is_dir():
        return str(p)
    return None


# ── Profile 列表 ──────────────────────────────────────────────────
def list_profiles(user_data_dir: str) -> list[dict[str, Any]]:
    """扫 user_data_dir 下所有 profile 子目录，读各自 Preferences JSON 拿账号 email。

    Returns:
        list of {"name": str, "account_email": str | None}
        无 Preferences 或 JSON 无 account_info → email=None。
        非 profile 目录（Crashpad / ShaderCache / etc）会被过滤。
    """
    base = Path(user_data_dir)
    if not base.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for entry in sorted(base.iterdir()):
        if not entry.is_dir():
            continue
        if not _PROFILE_DIR_RE.match(entry.name):
            continue
        email = _read_account_email(entry / "Preferences")
        out.append({"name": entry.name, "account_email": email})
    return out


def _read_account_email(preferences_path: Path) -> str | None:
    """从 Preferences JSON 读第一个 account_info[0].email。失败返回 None。"""
    try:
        raw = preferences_path.read_text(encoding="utf-8")
        data = json.loads(raw)
        accounts = data.get("account_info") or []
        if accounts and isinstance(accounts, list):
            email = accounts[0].get("email")
            if email and isinstance(email, str):
                return email
    except (OSError, json.JSONDecodeError, KeyError):
        return None
    return None
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd D:/CSM/.claude/worktrees/tender-brahmagupta-f4a634 && pytest sidecar/tests/test_chrome_detect.py -v`
Expected: ALL PASS（10 个测试用例都过）

- [ ] **Step 5: Commit**

```bash
git -C D:/CSM/.claude/worktrees/tender-brahmagupta-f4a634 add csm_core/monitor/drivers/chrome_detect.py sidecar/tests/test_chrome_detect.py
git -C D:/CSM/.claude/worktrees/tender-brahmagupta-f4a634 commit -m "feat(monitor): add chrome_detect for native mode setup

探测 Chrome.exe（注册表 + 默认路径 fallback）、user_data_dir、
profile 列表（含账号 email）。Best-effort，失败返回 None。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: chrome_preflight.py — Chrome 进程检测 + 轮询等待关闭

**Files:**
- Create: `csm_core/monitor/drivers/chrome_preflight.py`
- Create: `sidecar/tests/test_chrome_preflight.py`

- [ ] **Step 1: 写失败测试**

新建 `sidecar/tests/test_chrome_preflight.py`：

```python
"""chrome_preflight.py 单元测试 —— mock psutil 模拟 Chrome 进程状态。"""
from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from csm_core.monitor.drivers import chrome_preflight


class TestIsChromeRunning:
    def test_returns_true_when_chrome_exe_running(self, monkeypatch):
        fake_proc = MagicMock()
        fake_proc.info = {"name": "chrome.exe"}
        monkeypatch.setattr(chrome_preflight, "_iter_processes", lambda: [fake_proc])
        assert chrome_preflight.is_chrome_running() is True

    def test_returns_false_when_only_other_processes(self, monkeypatch):
        fake_proc = MagicMock()
        fake_proc.info = {"name": "firefox.exe"}
        monkeypatch.setattr(chrome_preflight, "_iter_processes", lambda: [fake_proc])
        assert chrome_preflight.is_chrome_running() is False

    def test_case_insensitive_name_match(self, monkeypatch):
        fake_proc = MagicMock()
        fake_proc.info = {"name": "Chrome.exe"}  # 大写
        monkeypatch.setattr(chrome_preflight, "_iter_processes", lambda: [fake_proc])
        assert chrome_preflight.is_chrome_running() is True

    def test_skips_processes_raising_access_denied(self, monkeypatch):
        import psutil
        bad_proc = MagicMock()
        type(bad_proc).info = property(lambda self: (_ for _ in ()).throw(psutil.AccessDenied()))
        good_proc = MagicMock()
        good_proc.info = {"name": "chrome.exe"}
        monkeypatch.setattr(chrome_preflight, "_iter_processes", lambda: [bad_proc, good_proc])
        assert chrome_preflight.is_chrome_running() is True


class TestWaitForChromeClosed:
    def test_returns_immediately_when_chrome_not_running(self, monkeypatch):
        monkeypatch.setattr(chrome_preflight, "is_chrome_running", lambda: False)
        notify_calls: list = []
        monkeypatch.setattr(chrome_preflight, "_notify", lambda **kw: notify_calls.append(kw))
        # 不超时 + 不调通知
        chrome_preflight.wait_for_chrome_closed(timeout_s=5, poll_interval_s=0.01)
        assert notify_calls == []  # 没必要发通知

    def test_polls_and_returns_when_chrome_closes_mid_wait(self, monkeypatch):
        """前 2 次 poll 在跑、第 3 次关闭。"""
        state = {"calls": 0}

        def fake_is_running():
            state["calls"] += 1
            return state["calls"] <= 2

        monkeypatch.setattr(chrome_preflight, "is_chrome_running", fake_is_running)
        monkeypatch.setattr(chrome_preflight, "_notify", lambda **kw: None)

        chrome_preflight.wait_for_chrome_closed(timeout_s=5, poll_interval_s=0.01)
        assert state["calls"] >= 3  # 至少 poll 了 3 次

    def test_raises_after_timeout(self, monkeypatch):
        """一直在跑 → 超时 raise。"""
        monkeypatch.setattr(chrome_preflight, "is_chrome_running", lambda: True)
        monkeypatch.setattr(chrome_preflight, "_notify", lambda **kw: None)

        with pytest.raises(chrome_preflight.ChromeStillRunningError) as exc:
            chrome_preflight.wait_for_chrome_closed(timeout_s=0.05, poll_interval_s=0.01)
        assert "超时" in str(exc.value) or "timeout" in str(exc.value).lower()

    def test_emits_notification_on_first_running_detection(self, monkeypatch):
        """第一次检测到在跑 → 发通知，之后不重复发。"""
        state = {"calls": 0}
        def fake_is_running():
            state["calls"] += 1
            return state["calls"] <= 3

        notify_calls: list = []
        monkeypatch.setattr(chrome_preflight, "is_chrome_running", fake_is_running)
        monkeypatch.setattr(chrome_preflight, "_notify", lambda **kw: notify_calls.append(kw))

        chrome_preflight.wait_for_chrome_closed(timeout_s=5, poll_interval_s=0.01)
        assert len(notify_calls) == 1  # 只发一次通知
        assert "关闭 Chrome" in notify_calls[0].get("body", "")
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd D:/CSM/.claude/worktrees/tender-brahmagupta-f4a634 && pytest sidecar/tests/test_chrome_preflight.py -v`
Expected: FAIL — ModuleNotFoundError

- [ ] **Step 3: 创建 chrome_preflight.py**

新建 `csm_core/monitor/drivers/chrome_preflight.py`：

```python
"""跑 baidu_keyword native mode 前的 Chrome 进程状态预检。

策略：detect → 发通知 → 轮询等关闭 → 关掉后立刻返回 / 超时 raise。
"""
from __future__ import annotations

import logging
import time
from typing import Any, Callable, Iterable

import psutil

logger = logging.getLogger(__name__)


class ChromeStillRunningError(RuntimeError):
    """等待 Chrome 关闭超时。"""


def is_chrome_running() -> bool:
    """检测系统是否有 chrome.exe 进程在跑。

    psutil 偶尔在子进程切换时抛 NoSuchProcess / AccessDenied，吞掉继续遍历。
    """
    for proc in _iter_processes():
        try:
            name = (proc.info.get("name") or "").lower()
            if name == "chrome.exe":
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return False


def _iter_processes() -> Iterable[psutil.Process]:
    """Indirection 给测试 monkeypatch。"""
    return psutil.process_iter(["name"])


def wait_for_chrome_closed(
    timeout_s: int = 120,
    poll_interval_s: float = 1.0,
    *,
    task_id: int | None = None,
    event_publisher: "Callable[[dict[str, Any]], None] | None" = None,
) -> None:
    """轮询等待 Chrome 关闭。第一次检测到在跑就发通知，关掉立即返回。

    Args:
        timeout_s: 超时秒数。
        poll_interval_s: 轮询间隔。
        task_id: 关联的监控任务 ID（用于 SSE 事件）。None = 不发事件。
        event_publisher: SSE 事件发布回调（DI 模式，避免 csm_core ↔ sidecar 循环
            依赖）。签名：fn({"kind": str, "task_id": int, "remaining_s": int}) -> None。
            None = 不发事件。

    Raises:
        ChromeStillRunningError: 超时仍有 chrome.exe 进程。
    """
    def _maybe_publish(payload: dict[str, Any]) -> None:
        if event_publisher is not None and task_id is not None:
            try:
                event_publisher(payload)
            except Exception:
                logger.exception("event_publisher raised; preflight continues")

    if not is_chrome_running():
        _maybe_publish({"kind": "chrome_closed", "task_id": task_id})
        return

    _notify(
        title="CSM 百度监控",
        body="请关闭 Chrome 浏览器以开始监控（自动检测中）",
    )

    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        remaining = int(deadline - time.monotonic())
        _maybe_publish({
            "kind": "waiting_chrome_close",
            "task_id": task_id,
            "remaining_s": remaining,
        })
        time.sleep(poll_interval_s)
        if not is_chrome_running():
            logger.info("chrome closed, proceeding with native mode")
            _maybe_publish({"kind": "chrome_closed", "task_id": task_id})
            return

    raise ChromeStillRunningError(
        f"等待 Chrome 关闭超时（{timeout_s}s），请手动关闭后重试"
    )


def _notify(*, title: str, body: str) -> None:
    """通知发送 indirection —— 测试可 monkeypatch，prod 由 sidecar 注入。

    本模块不直接依赖 sidecar 通知层，避免 csm_core ↔ sidecar 循环 import。
    sidecar 启动时会调 ``set_notifier(callable)`` 注入真正的实现。
    """
    impl = _notify_impl
    if impl is None:
        logger.warning("notifier not configured; skip: title=%s body=%s", title, body)
        return
    try:
        impl(title=title, body=body)
    except Exception:
        logger.exception("notifier raised; preflight continues")


_notify_impl = None


def set_notifier(fn) -> None:
    """Sidecar lifespan 启动时调用，注入真正的通知发送实现。"""
    global _notify_impl
    _notify_impl = fn
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd D:/CSM/.claude/worktrees/tender-brahmagupta-f4a634 && pytest sidecar/tests/test_chrome_preflight.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git -C D:/CSM/.claude/worktrees/tender-brahmagupta-f4a634 add csm_core/monitor/drivers/chrome_preflight.py sidecar/tests/test_chrome_preflight.py
git -C D:/CSM/.claude/worktrees/tender-brahmagupta-f4a634 commit -m "feat(monitor): add chrome_preflight for native mode wait-loop

是否在跑 + 轮询等待关闭（带超时 + 通知 indirection）。
通知 impl 用注入模式避免 csm_core ↔ sidecar 循环依赖。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: baidu_browser.py — 加 native mode 分支

**Files:**
- Modify: `csm_core/monitor/drivers/baidu_browser.py:49-126`
- Modify: `sidecar/tests/test_baidu_browser.py`

- [ ] **Step 1: 写失败测试 — native mode 启动参数正确**

在 `sidecar/tests/test_baidu_browser.py` 末尾追加：

```python
def test_baidu_browser_session_native_mode_uses_chrome_channel(monkeypatch, tmp_path):
    """use_native_chrome=True 时：launch_persistent_context 拿到 channel='chrome'
    + executable_path + --profile-directory，且 headless 被强制改成 False。
    """
    from csm_core.monitor.drivers import baidu_browser

    captured: dict[str, Any] = {}
    fake_context = MagicMock()
    fake_context.pages = [MagicMock()]
    fake_context.cookies.return_value = []
    fake_chromium = MagicMock()
    fake_chromium.launch_persistent_context = lambda **kw: (captured.update(kw), fake_context)[1]
    fake_pw = MagicMock()
    fake_pw.chromium = fake_chromium

    monkeypatch.setattr(baidu_browser, "_sync_playwright", lambda: MagicMock(start=lambda: fake_pw))
    monkeypatch.setattr(baidu_browser, "ensure_browsers_path", lambda: None)

    with baidu_browser.baidu_browser_session(
        headless=True,  # 应该被强制覆盖为 False
        user_data_dir=tmp_path,
        use_native_chrome=True,
        chrome_executable_path="C:/test/chrome.exe",
        chrome_profile_name="Profile 1",
    ):
        pass

    assert captured.get("channel") == "chrome"
    assert captured.get("executable_path") == "C:/test/chrome.exe"
    assert captured.get("headless") is False  # native 强制 False
    args = captured.get("args") or []
    assert "--profile-directory=Profile 1" in args
    # native mode 不加 --blink-settings=imagesEnabled=false
    assert "--blink-settings=imagesEnabled=false" not in args


def test_baidu_browser_session_self_built_mode_unchanged(monkeypatch, tmp_path):
    """use_native_chrome=False（默认）：保持原行为，不带 channel / executable_path。"""
    from csm_core.monitor.drivers import baidu_browser

    captured: dict[str, Any] = {}
    fake_context = MagicMock()
    fake_context.pages = [MagicMock()]
    fake_context.cookies.return_value = []
    fake_chromium = MagicMock()
    fake_chromium.launch_persistent_context = lambda **kw: (captured.update(kw), fake_context)[1]
    fake_pw = MagicMock()
    fake_pw.chromium = fake_chromium

    monkeypatch.setattr(baidu_browser, "_sync_playwright", lambda: MagicMock(start=lambda: fake_pw))
    monkeypatch.setattr(baidu_browser, "ensure_browsers_path", lambda: None)

    with baidu_browser.baidu_browser_session(
        headless=True,
        user_data_dir=tmp_path,
    ):
        pass

    assert "channel" not in captured
    assert "executable_path" not in captured
    assert captured.get("headless") is True
    args = captured.get("args") or []
    assert "--blink-settings=imagesEnabled=false" in args  # 自建保留
```

（先确认 test 文件顶部已 import `MagicMock` 和 `Any`，没有就加）

- [ ] **Step 2: 运行测试确认失败**

Run: `cd D:/CSM/.claude/worktrees/tender-brahmagupta-f4a634 && pytest sidecar/tests/test_baidu_browser.py::test_baidu_browser_session_native_mode_uses_chrome_channel sidecar/tests/test_baidu_browser.py::test_baidu_browser_session_self_built_mode_unchanged -v`
Expected: FAIL — `TypeError: baidu_browser_session() got an unexpected keyword argument 'use_native_chrome'`

- [ ] **Step 3: 修改 baidu_browser_session 加 native mode 分支**

替换 `csm_core/monitor/drivers/baidu_browser.py` 的 `baidu_browser_session` 函数（49-126 行整体）为：

```python
@contextmanager
def baidu_browser_session(
    *,
    headless: bool,
    user_data_dir: Path | None = None,
    use_native_chrome: bool = False,
    chrome_executable_path: str | None = None,
    chrome_profile_name: str = "Default",
) -> Iterator[BaiduBrowserSession]:
    """启动百度抓取专用的持久 BrowserContext。

    两种模式：
    - **自建 profile**（默认，向后兼容）：用 CSM 自有 user_data_dir + Patchright 自带
      Chromium。可真 headless。
    - **native Chrome**（``use_native_chrome=True``）：用 channel="chrome" +
      用户的 Chrome.exe + 用户日常 user_data_dir。``headless`` 入参被忽略
      （Chrome stable 不支持 headless persistent context，会启动失败）。

    Args:
        headless: 自建模式下生效；native 模式被强制覆盖为 False。
        user_data_dir: 自建模式 → 默认 ``<config_dir>/baidu_browser_profile``；
                       native 模式 → 必须是用户 Chrome User Data 目录绝对路径。
        use_native_chrome: True = 走 native 分支。
        chrome_executable_path: native 模式必填，用户 Chrome.exe 绝对路径。
        chrome_profile_name: native 模式选哪个 profile（"Default" / "Profile 1"...）。

    Yields:
        BaiduBrowserSession。

    Raises:
        RuntimeError: patchright 未安装、Chromium / Chrome 启动失败。
        ValueError: native 模式但缺 user_data_dir / chrome_executable_path。
    """
    ensure_browsers_path()

    if use_native_chrome:
        if user_data_dir is None:
            raise ValueError("native mode requires user_data_dir")
        if not chrome_executable_path:
            raise ValueError("native mode requires chrome_executable_path")
        target_dir = Path(user_data_dir)
        if headless:
            logger.debug("native mode 忽略 headless=True（Chrome stable 不支持）")
        launch_kwargs: dict[str, Any] = dict(
            user_data_dir=str(target_dir),
            headless=False,
            executable_path=chrome_executable_path,
            channel="chrome",
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                f"--profile-directory={chrome_profile_name}",
            ],
            viewport={"width": 1366, "height": 768},
        )
    else:
        target_dir = user_data_dir or _default_user_data_dir()
        target_dir.mkdir(parents=True, exist_ok=True)
        launch_kwargs = dict(
            user_data_dir=str(target_dir),
            headless=headless,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--window-size=1366,768",
                "--blink-settings=imagesEnabled=false",
            ],
            viewport={"width": 1366, "height": 768},
        )

    pw = None
    context = None
    try:
        pw = _sync_playwright().start()
        context = pw.chromium.launch_persistent_context(**launch_kwargs)
        page = context.pages[0] if context.pages else context.new_page()
        _log_profile_health(context, target_dir)
        yield BaiduBrowserSession(page=page, context=context, pw=pw)
    finally:
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
```

- [ ] **Step 4: 运行新测试 + 全套现有测试**

Run: `cd D:/CSM/.claude/worktrees/tender-brahmagupta-f4a634 && pytest sidecar/tests/test_baidu_browser.py -v`
Expected: ALL PASS（含新 2 个 + 现有用例）

- [ ] **Step 5: Commit**

```bash
git -C D:/CSM/.claude/worktrees/tender-brahmagupta-f4a634 add csm_core/monitor/drivers/baidu_browser.py sidecar/tests/test_baidu_browser.py
git -C D:/CSM/.claude/worktrees/tender-brahmagupta-f4a634 commit -m "feat(monitor): add native chrome branch to baidu_browser_session

use_native_chrome=True 时用 channel='chrome' + 用户 Chrome.exe +
用户 user_data_dir 启动，headless 入参被忽略。默认 False = 行为不变。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: baidu_keyword.py — fetch hook（preflight + native session args）

**Files:**
- Modify: `csm_core/monitor/platforms/baidu_keyword.py:573-770` (fetch 入口附近)
- Modify: `sidecar/tests/test_baidu_keyword.py`

- [ ] **Step 1: 看现有 fetch() 入口和 session 启动位置**

Run: `Read csm_core/monitor/platforms/baidu_keyword.py 573-770`
锁定要插入 preflight 调用的位置（启动 `baidu_browser_session` context manager 之前）。

- [ ] **Step 2: 写失败测试 — native mode 启用时调 preflight**

在 `sidecar/tests/test_baidu_keyword.py` 末尾追加：

```python
def test_fetch_calls_chrome_preflight_when_native_mode_enabled(monkeypatch):
    """use_native_chrome=True → fetch() 入口调 wait_for_chrome_closed。"""
    from csm_core.monitor.platforms import baidu_keyword
    from csm_core.monitor.base import MonitorTask, TaskType

    preflight_called: list[bool] = []
    def fake_preflight(timeout_s=120, poll_interval_s=1.0):
        preflight_called.append(True)
        # mock 立即返回（chrome 不在跑）
        return None

    monkeypatch.setattr(
        "csm_core.monitor.drivers.chrome_preflight.wait_for_chrome_closed",
        fake_preflight,
    )
    # mock config 返回 use_native=True
    fake_cfg = MagicMock()
    fake_cfg.monitor.baidu_keyword.use_native_chrome = True
    fake_cfg.monitor.baidu_keyword.chrome_executable_path = "C:/x/chrome.exe"
    fake_cfg.monitor.baidu_keyword.chrome_user_data_dir = "C:/x/User Data"
    fake_cfg.monitor.baidu_keyword.chrome_profile_name = "Default"
    monkeypatch.setattr("csm_core.config.get_config", lambda: fake_cfg)

    # mock baidu_browser_session 不实际启浏览器
    fake_session = MagicMock()
    fake_session.page = MagicMock()
    fake_session.context = MagicMock()
    fake_session.context.cookies.return_value = [{"name": "BDUSS", "value": "x"}]
    from contextlib import contextmanager
    @contextmanager
    def fake_session_cm(**kwargs):
        # 断言 native 参数被透传
        assert kwargs.get("use_native_chrome") is True
        assert kwargs.get("chrome_executable_path") == "C:/x/chrome.exe"
        assert kwargs.get("chrome_profile_name") == "Default"
        yield fake_session
    monkeypatch.setattr(
        "csm_core.monitor.platforms.baidu_keyword.baidu_browser_session",
        fake_session_cm,
    )

    task = MonitorTask(
        id=1, type=TaskType.baidu_keyword, name="t", target_url="https://baidu.com",
        config={"search_keywords": [], "target_brand": "x"},  # 空 keywords 短路返回
    )
    adapter = baidu_keyword.BaiduKeywordAdapter()
    # 短路：空 keywords 应该早 return，但 preflight 已经跑过
    adapter.fetch(task)
    assert preflight_called == [True]


def test_fetch_skips_preflight_when_native_mode_disabled(monkeypatch):
    """默认 use_native_chrome=False → 不调 preflight。"""
    from csm_core.monitor.platforms import baidu_keyword
    from csm_core.monitor.base import MonitorTask, TaskType

    preflight_called: list[bool] = []
    monkeypatch.setattr(
        "csm_core.monitor.drivers.chrome_preflight.wait_for_chrome_closed",
        lambda **kw: preflight_called.append(True),
    )
    fake_cfg = MagicMock()
    fake_cfg.monitor.baidu_keyword.use_native_chrome = False
    monkeypatch.setattr("csm_core.config.get_config", lambda: fake_cfg)

    task = MonitorTask(
        id=1, type=TaskType.baidu_keyword, name="t", target_url="https://baidu.com",
        config={"search_keywords": [], "target_brand": "x"},
    )
    adapter = baidu_keyword.BaiduKeywordAdapter()
    adapter.fetch(task)
    assert preflight_called == []


def test_fetch_returns_error_when_chrome_close_times_out(monkeypatch):
    """preflight raise ChromeStillRunningError → 返回 status=error 结果，不进 session。"""
    from csm_core.monitor.platforms import baidu_keyword
    from csm_core.monitor.drivers.chrome_preflight import ChromeStillRunningError
    from csm_core.monitor.base import MonitorTask, TaskType

    def fake_preflight(**kw):
        raise ChromeStillRunningError("等待 Chrome 关闭超时")

    monkeypatch.setattr(
        "csm_core.monitor.drivers.chrome_preflight.wait_for_chrome_closed",
        fake_preflight,
    )
    fake_cfg = MagicMock()
    fake_cfg.monitor.baidu_keyword.use_native_chrome = True
    fake_cfg.monitor.baidu_keyword.chrome_executable_path = "C:/x/chrome.exe"
    fake_cfg.monitor.baidu_keyword.chrome_user_data_dir = "C:/x/User Data"
    fake_cfg.monitor.baidu_keyword.chrome_profile_name = "Default"
    monkeypatch.setattr("csm_core.config.get_config", lambda: fake_cfg)

    session_called: list[bool] = []
    monkeypatch.setattr(
        "csm_core.monitor.platforms.baidu_keyword.baidu_browser_session",
        lambda **kw: session_called.append(True),
    )

    task = MonitorTask(
        id=1, type=TaskType.baidu_keyword, name="t", target_url="https://baidu.com",
        config={"search_keywords": ["x"], "target_brand": "y"},
    )
    adapter = baidu_keyword.BaiduKeywordAdapter()
    result = adapter.fetch(task)
    assert result.status == "error"
    assert "等待 Chrome 关闭超时" in (result.error_message or "")
    assert session_called == []  # 没启 session
```

（test 文件顶部需 `from unittest.mock import MagicMock`，没就加）

- [ ] **Step 3: 运行测试确认失败**

Run: `cd D:/CSM/.claude/worktrees/tender-brahmagupta-f4a634 && pytest sidecar/tests/test_baidu_keyword.py -k "chrome_preflight or native" -v`
Expected: FAIL（功能没实现）

- [ ] **Step 4: 修改 fetch() 入口加 preflight + 透传 native 参数**

在 `csm_core/monitor/platforms/baidu_keyword.py` 顶部导入区加：

```python
from ..drivers import chrome_preflight
from csm_core import config as csm_config
```

修改 fetch() 函数（找到现有 `with baidu_browser_session(headless=headless) as bsession:` 这一行附近，约 761 行），在它**之前**插入 preflight，并把 session args 改成透传：

```python
        # ── Native mode preflight ────────────────────────────────
        # use_native_chrome=True → 跑前等用户关 Chrome（OS profile lock）。
        # 超时返回 error，不进 session。
        cfg = csm_config.get_config()
        baidu_cfg = cfg.monitor.baidu_keyword
        use_native = bool(baidu_cfg.use_native_chrome)

        if use_native:
            try:
                chrome_preflight.wait_for_chrome_closed(timeout_s=120)
            except chrome_preflight.ChromeStillRunningError as e:
                return MonitorResult(
                    task_id=task.id or 0,
                    checked_at=datetime.utcnow(),
                    status="error",
                    rank=-1,
                    error_message=str(e),
                )

        session_kwargs: dict[str, Any] = {}
        if use_native:
            session_kwargs.update(
                use_native_chrome=True,
                user_data_dir=Path(baidu_cfg.chrome_user_data_dir or ""),
                chrome_executable_path=baidu_cfg.chrome_executable_path,
                chrome_profile_name=baidu_cfg.chrome_profile_name,
            )
        # native 强制 headless=False（baidu_browser_session 内部也会忽略）
        effective_headless = False if use_native else headless

        with baidu_browser_session(headless=effective_headless, **session_kwargs) as bsession:
            # ... 现有 fetch 逻辑全部保留 ...
```

注意：把现有的 `with baidu_browser_session(headless=headless) as bsession:` 替换成上面这块，但**所有 with 块内的现有逻辑保持不变**。

- [ ] **Step 5: 运行 native 相关测试 + 全套 baidu_keyword 测试**

Run: `cd D:/CSM/.claude/worktrees/tender-brahmagupta-f4a634 && pytest sidecar/tests/test_baidu_keyword.py -v`
Expected: ALL PASS（含新 3 个 + 现有所有用例）

- [ ] **Step 6: Commit**

```bash
git -C D:/CSM/.claude/worktrees/tender-brahmagupta-f4a634 add csm_core/monitor/platforms/baidu_keyword.py sidecar/tests/test_baidu_keyword.py
git -C D:/CSM/.claude/worktrees/tender-brahmagupta-f4a634 commit -m "feat(monitor): wire chrome_preflight + native session args into baidu fetch

native mode 启用时：① fetch 入口调 wait_for_chrome_closed ② 透传 native
参数给 baidu_browser_session ③ 超时返回 status=error。默认 False = 不变。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: 软着陆验证码 `_try_human_solve`

**Files:**
- Modify: `csm_core/monitor/platforms/baidu_keyword.py` (新增函数 + 主循环 hook)
- Modify: `sidecar/tests/test_baidu_keyword.py`

- [ ] **Step 1: 写失败测试 — _try_human_solve 等到 URL 离开风控域名后返回 True**

在 `sidecar/tests/test_baidu_keyword.py` 追加：

```python
def test_try_human_solve_returns_true_when_url_leaves_risk_domain(monkeypatch):
    """page.url 从 wappass.baidu.com 切回 www.baidu.com/s → 返回 True。"""
    from csm_core.monitor.platforms import baidu_keyword

    state = {"polls": 0}
    fake_page = MagicMock()
    def url_property(self):
        state["polls"] += 1
        # 前 3 次还在 wappass，第 4 次跳回 baidu/s
        if state["polls"] <= 3:
            return "https://wappass.baidu.com/static/captcha/tuxing.html"
        return "https://www.baidu.com/s?wd=test"
    type(fake_page).url = property(url_property)
    fake_page.query_selector.return_value = None  # 没有 captcha DOM

    monkeypatch.setattr(baidu_keyword, "_notify", lambda **kw: None)

    result = baidu_keyword._try_human_solve(
        page=fake_page, keyword="test", kw_idx=5, timeout_s=5, poll_interval_s=0.01,
    )
    assert result is True
    assert state["polls"] >= 4


def test_try_human_solve_returns_false_on_timeout(monkeypatch):
    """超时仍在 wappass → 返回 False（caller 走原 raise 路径）。"""
    from csm_core.monitor.platforms import baidu_keyword

    fake_page = MagicMock()
    type(fake_page).url = property(lambda self: "https://wappass.baidu.com/captcha")
    fake_page.query_selector.return_value = MagicMock()  # passmod DOM 还在

    monkeypatch.setattr(baidu_keyword, "_notify", lambda **kw: None)

    result = baidu_keyword._try_human_solve(
        page=fake_page, keyword="test", kw_idx=5, timeout_s=0.05, poll_interval_s=0.01,
    )
    assert result is False


def test_try_human_solve_emits_notification_with_keyword(monkeypatch):
    """触发时发系统通知带关键词。"""
    from csm_core.monitor.platforms import baidu_keyword

    fake_page = MagicMock()
    type(fake_page).url = property(lambda self: "https://www.baidu.com/s?wd=already_solved")
    fake_page.query_selector.return_value = None

    captured: list = []
    monkeypatch.setattr(baidu_keyword, "_notify", lambda **kw: captured.append(kw))

    baidu_keyword._try_human_solve(
        page=fake_page, keyword="testkw", kw_idx=3, timeout_s=1, poll_interval_s=0.01,
    )
    assert len(captured) == 1
    assert "testkw" in captured[0].get("body", "")
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd D:/CSM/.claude/worktrees/tender-brahmagupta-f4a634 && pytest sidecar/tests/test_baidu_keyword.py -k "try_human_solve" -v`
Expected: FAIL — `AttributeError: module 'baidu_keyword' has no attribute '_try_human_solve'`

- [ ] **Step 3: 在 baidu_keyword.py 加 _try_human_solve 函数 + _notify**

在 `csm_core/monitor/platforms/baidu_keyword.py` 文件靠近 _navigate_to_serp 函数附近加：

```python
# ── 软着陆验证码 ────────────────────────────────────────────────
_RISK_URL_PATTERNS = ("wappass", "verify.baidu", "safetycheck", "passport.baidu")
_RISK_DOM_SELECTORS = (".passmod", "#captcha-mask", ".security-check")
_notify_impl: Any = None


def _notify(*, title: str, body: str) -> None:
    """通知发送 indirection —— sidecar 注入实现。csm_core 不直接依赖 sidecar。"""
    if _notify_impl is None:
        logger.warning("notifier not configured; skip: title=%s body=%s", title, body)
        return
    try:
        _notify_impl(title=title, body=body)
    except Exception:
        logger.exception("notifier raised; continue")


def set_notifier(fn: Any) -> None:
    """Sidecar 启动时注入。"""
    global _notify_impl
    _notify_impl = fn


def _try_human_solve(
    *,
    page: Any,
    keyword: str,
    kw_idx: int,
    timeout_s: int = 300,
    poll_interval_s: float = 1.0,
    task_id: int | None = None,
    event_publisher: Any = None,
) -> bool:
    """命中风控时弹通知 + 轮询等用户解题。

    Args:
        page, keyword, kw_idx: 当前 SERP 上下文。
        timeout_s, poll_interval_s: 超时和轮询。
        task_id: 关联监控任务 ID（用于 SSE）。
        event_publisher: 同 chrome_preflight，DI 注入。
            签名：fn({"kind": str, "task_id": int, "keyword": str, "kw_idx": int}) -> None。

    Returns:
        True  — 用户解完，URL 离开风控域名 + DOM 验证码元素消失。caller retry 当前 kw。
        False — 超时仍在风控页。caller 走原 raise RiskControlException 路径。
    """
    _notify(
        title="CSM 百度监控",
        body=f"需要人工解验证码（关键词：{keyword}），点击浏览器窗口完成",
    )
    if event_publisher is not None and task_id is not None:
        try:
            event_publisher({
                "kind": "needs_captcha",
                "task_id": task_id,
                "keyword": keyword,
                "kw_idx": kw_idx,
            })
        except Exception:
            logger.exception("event_publisher raised; continue")

    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        time.sleep(poll_interval_s)
        try:
            cur_url = page.url or ""
        except Exception:
            cur_url = ""
        in_risk = any(p in cur_url for p in _RISK_URL_PATTERNS)
        if in_risk:
            continue
        # URL 已离开风控域名 → 再检 DOM 验证码元素是否消失
        any_captcha_dom = False
        for sel in _RISK_DOM_SELECTORS:
            try:
                if page.query_selector(sel) is not None:
                    any_captcha_dom = True
                    break
            except Exception:
                continue
        if not any_captcha_dom:
            logger.info("human solve detected; resuming keyword #%d (%s)", kw_idx, keyword)
            return True

    logger.warning("human solve timeout for keyword #%d (%s)", kw_idx, keyword)
    return False
```

确认 `import time` 已经在文件顶部，没有就加。

- [ ] **Step 4: 在主循环 hook 软着陆 —— 命中 detect_risk 时先 _try_human_solve**

找到 `csm_core/monitor/platforms/baidu_keyword.py` 中：

```python
                risk = detect_risk(page, serp_response)
                if risk is not None:
                    raise RiskControlException(risk, progress=kw_idx)
```

替换为：

```python
                risk = detect_risk(page, serp_response)
                if risk is not None:
                    # 软着陆：弹通知给用户解，解完 retry 当前 kw；失败 fallback 到 raise
                    solved = _try_human_solve(
                        page=page, keyword=keyword, kw_idx=kw_idx,
                    )
                    if solved:
                        # 重新 navigate + 重新 detect_risk，本轮 kw 重跑
                        try:
                            serp_response = _navigate_to_serp(page, keyword)
                        except Exception as e:
                            kw_entry["fetch_error"] = f"serp navigate after solve raised: {e!r}"
                            keyword_results.append(kw_entry)
                            continue
                        risk2 = detect_risk(page, serp_response)
                        if risk2 is not None:
                            raise RiskControlException(risk2, progress=kw_idx)
                        # 解完 + 重导成功 → 继续往下走正常 SERP 解析流程
                    else:
                        raise RiskControlException(risk, progress=kw_idx)
```

- [ ] **Step 5: 运行新测试 + 全套**

Run: `cd D:/CSM/.claude/worktrees/tender-brahmagupta-f4a634 && pytest sidecar/tests/test_baidu_keyword.py -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git -C D:/CSM/.claude/worktrees/tender-brahmagupta-f4a634 add csm_core/monitor/platforms/baidu_keyword.py sidecar/tests/test_baidu_keyword.py
git -C D:/CSM/.claude/worktrees/tender-brahmagupta-f4a634 commit -m "feat(monitor): add _try_human_solve soft-landing for baidu captcha

命中风控时弹通知 + 轮询等用户在浏览器里解，解完 retry 当前关键词；
超时 fallback 到原 raise RiskControlException 路径（断点续抓兜底）。
通知 impl 用注入模式。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: 5 个新 API 路由（detect-chrome / list-profiles / test-native / native-config GET&POST）

**Files:**
- Modify: `sidecar/csm_sidecar/routes/monitor.py` (末尾追加 native mode routes)
- Modify: `sidecar/tests/test_monitor_routes.py`

- [ ] **Step 1: 写失败测试 — 5 个 API**

在 `sidecar/tests/test_monitor_routes.py` 末尾追加：

```python
class TestBaiduNativeModeRoutes:
    def test_detect_chrome_returns_paths_when_present(self, client, monkeypatch):
        monkeypatch.setattr(
            "csm_core.monitor.drivers.chrome_detect.find_chrome_executable",
            lambda: "C:/Chrome/chrome.exe",
        )
        monkeypatch.setattr(
            "csm_core.monitor.drivers.chrome_detect.find_user_data_dir",
            lambda: "C:/User Data",
        )
        resp = client.post("/api/monitor/baidu/detect-chrome")
        assert resp.status_code == 200
        data = resp.json()
        assert data["executable_path"] == "C:/Chrome/chrome.exe"
        assert data["user_data_dir"] == "C:/User Data"

    def test_detect_chrome_returns_none_when_missing(self, client, monkeypatch):
        monkeypatch.setattr(
            "csm_core.monitor.drivers.chrome_detect.find_chrome_executable",
            lambda: None,
        )
        monkeypatch.setattr(
            "csm_core.monitor.drivers.chrome_detect.find_user_data_dir",
            lambda: None,
        )
        resp = client.post("/api/monitor/baidu/detect-chrome")
        assert resp.status_code == 200
        data = resp.json()
        assert data["executable_path"] is None
        assert data["user_data_dir"] is None

    def test_list_profiles_returns_array(self, client, monkeypatch):
        monkeypatch.setattr(
            "csm_core.monitor.drivers.chrome_detect.list_profiles",
            lambda path: [
                {"name": "Default", "account_email": "a@gmail.com"},
                {"name": "Profile 1", "account_email": None},
            ],
        )
        resp = client.post(
            "/api/monitor/baidu/list-profiles",
            json={"user_data_dir": "C:/User Data"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["profiles"][0]["name"] == "Default"
        assert data["profiles"][0]["account_email"] == "a@gmail.com"
        assert len(data["profiles"]) == 2

    def test_list_profiles_400_on_empty_path(self, client):
        resp = client.post("/api/monitor/baidu/list-profiles", json={"user_data_dir": ""})
        assert resp.status_code == 400

    def test_test_native_success(self, client, monkeypatch):
        """mock baidu_browser_session 不抛 → 返回 {"ok": True}。"""
        from contextlib import contextmanager
        @contextmanager
        def fake_session(**kw):
            assert kw["use_native_chrome"] is True
            yield MagicMock()
        monkeypatch.setattr(
            "csm_sidecar.routes.monitor.baidu_browser_session", fake_session,
        )
        resp = client.post(
            "/api/monitor/baidu/test-native",
            json={
                "chrome_executable_path": "C:/Chrome/chrome.exe",
                "chrome_user_data_dir": "C:/User Data",
                "chrome_profile_name": "Default",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_test_native_failure_returns_error_details(self, client, monkeypatch):
        from contextlib import contextmanager
        @contextmanager
        def fake_session(**kw):
            raise RuntimeError("chrome.exe not found")
            yield  # pragma: no cover
        monkeypatch.setattr(
            "csm_sidecar.routes.monitor.baidu_browser_session", fake_session,
        )
        resp = client.post(
            "/api/monitor/baidu/test-native",
            json={
                "chrome_executable_path": "C:/bad/chrome.exe",
                "chrome_user_data_dir": "C:/User Data",
                "chrome_profile_name": "Default",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is False
        assert "chrome.exe not found" in body["error"]

    def test_native_config_get_returns_current_settings(self, client):
        resp = client.get("/api/monitor/baidu/native-config")
        assert resp.status_code == 200
        data = resp.json()
        assert "use_native_chrome" in data
        assert "chrome_executable_path" in data
        assert "chrome_user_data_dir" in data
        assert "chrome_profile_name" in data

    def test_native_config_post_persists(self, client):
        resp = client.post(
            "/api/monitor/baidu/native-config",
            json={
                "use_native_chrome": True,
                "chrome_executable_path": "C:/x/chrome.exe",
                "chrome_user_data_dir": "C:/x/User Data",
                "chrome_profile_name": "Profile 1",
            },
        )
        assert resp.status_code == 200
        # round-trip
        resp2 = client.get("/api/monitor/baidu/native-config")
        data = resp2.json()
        assert data["use_native_chrome"] is True
        assert data["chrome_executable_path"] == "C:/x/chrome.exe"
        assert data["chrome_profile_name"] == "Profile 1"
```

- [ ] **Step 2: 运行确认失败**

Run: `cd D:/CSM/.claude/worktrees/tender-brahmagupta-f4a634 && pytest sidecar/tests/test_monitor_routes.py::TestBaiduNativeModeRoutes -v`
Expected: FAIL（路由不存在 404）

- [ ] **Step 3: 在 routes/monitor.py 加 5 个新路由**

在 `sidecar/csm_sidecar/routes/monitor.py` 末尾追加：

```python
# ── Baidu native mode (方案 D) ────────────────────────────────────
from csm_core.monitor.drivers import chrome_detect
from csm_core.monitor.drivers.baidu_browser import baidu_browser_session
from pathlib import Path as _Path
from csm_core import config as _csm_config


class ListProfilesBody(BaseModel):
    user_data_dir: str = Field(min_length=1)


class TestNativeBody(BaseModel):
    chrome_executable_path: str = Field(min_length=1)
    chrome_user_data_dir: str = Field(min_length=1)
    chrome_profile_name: str = Field(default="Default")


class NativeConfigBody(BaseModel):
    use_native_chrome: bool
    chrome_executable_path: str | None = None
    chrome_user_data_dir: str | None = None
    chrome_profile_name: str = "Default"


@router.post("/api/monitor/baidu/detect-chrome")
def baidu_detect_chrome() -> dict[str, Any]:
    """探测 Chrome 安装路径 + User Data 默认位置。"""
    return {
        "executable_path": chrome_detect.find_chrome_executable(),
        "user_data_dir": chrome_detect.find_user_data_dir(),
    }


@router.post("/api/monitor/baidu/list-profiles")
def baidu_list_profiles(body: ListProfilesBody) -> dict[str, Any]:
    """枚举给定 user_data_dir 下所有 profile + 账号 email。"""
    return {"profiles": chrome_detect.list_profiles(body.user_data_dir)}


@router.post("/api/monitor/baidu/test-native")
def baidu_test_native(body: TestNativeBody) -> dict[str, Any]:
    """试启动 Chrome 验证配置可用。成功 close 后返回 ok=True。"""
    try:
        with baidu_browser_session(
            headless=False,  # native 模式下被忽略
            user_data_dir=_Path(body.chrome_user_data_dir),
            use_native_chrome=True,
            chrome_executable_path=body.chrome_executable_path,
            chrome_profile_name=body.chrome_profile_name,
        ):
            pass  # 启动成功立即关
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.get("/api/monitor/baidu/native-config")
def baidu_get_native_config() -> dict[str, Any]:
    """读当前 native mode 配置。"""
    cfg = _csm_config.get_config()
    bk = cfg.monitor.baidu_keyword
    return {
        "use_native_chrome": bk.use_native_chrome,
        "chrome_executable_path": bk.chrome_executable_path,
        "chrome_user_data_dir": bk.chrome_user_data_dir,
        "chrome_profile_name": bk.chrome_profile_name,
    }


@router.post("/api/monitor/baidu/native-config")
def baidu_set_native_config(body: NativeConfigBody) -> dict[str, Any]:
    """保存 native mode 配置（merge 到全局 BaiduKeywordConfig）。"""
    cfg = _csm_config.get_config()
    bk = cfg.monitor.baidu_keyword
    bk.use_native_chrome = body.use_native_chrome
    bk.chrome_executable_path = body.chrome_executable_path
    bk.chrome_user_data_dir = body.chrome_user_data_dir
    bk.chrome_profile_name = body.chrome_profile_name
    _csm_config.save_config(cfg)
    return {"ok": True}
```

如果 `_csm_config.save_config` 不存在，先 Grep 一下确认正确的持久化函数名（可能是 `set_config` / `write` 等）。

- [ ] **Step 4: 运行测试确认通过**

Run: `cd D:/CSM/.claude/worktrees/tender-brahmagupta-f4a634 && pytest sidecar/tests/test_monitor_routes.py::TestBaiduNativeModeRoutes -v`
Expected: ALL PASS（8 个用例）

- [ ] **Step 5: 跑全套 monitor_routes 测试确保没破坏现有路由**

Run: `cd D:/CSM/.claude/worktrees/tender-brahmagupta-f4a634 && pytest sidecar/tests/test_monitor_routes.py -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git -C D:/CSM/.claude/worktrees/tender-brahmagupta-f4a634 add sidecar/csm_sidecar/routes/monitor.py sidecar/tests/test_monitor_routes.py
git -C D:/CSM/.claude/worktrees/tender-brahmagupta-f4a634 commit -m "feat(api): add 5 baidu native mode routes

POST /detect-chrome, /list-profiles, /test-native;
GET+POST /native-config — 给前端 Settings 新 tab 配置 native mode。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: 扩展 MonitorEvent + EventKind（3 个新事件）+ event_to_dict 序列化

**Files:**
- Modify: `sidecar/csm_sidecar/services/monitor_loop.py:56-75` (EventKind + MonitorEvent)
- Modify: `sidecar/csm_sidecar/monitor_bus.py:83-108` (event_to_dict)
- Modify: `sidecar/tests/test_monitor_bus.py`

- [ ] **Step 1: 写失败测试 — 新 EventKind + 字段序列化**

在 `sidecar/tests/test_monitor_bus.py` 末尾追加：

```python
def test_event_to_dict_waiting_chrome_close_carries_remaining_s():
    from datetime import datetime
    from csm_sidecar.services.monitor_loop import MonitorEvent
    from csm_sidecar.monitor_bus import event_to_dict

    evt = MonitorEvent(
        kind="waiting_chrome_close",
        task_id=42,
        at=datetime(2026, 1, 1, 12, 0, 0),
        remaining_s=87,
    )
    out = event_to_dict(evt)
    assert out["kind"] == "waiting_chrome_close"
    assert out["task_id"] == 42
    assert out["remaining_s"] == 87


def test_event_to_dict_chrome_closed_minimal():
    from datetime import datetime
    from csm_sidecar.services.monitor_loop import MonitorEvent
    from csm_sidecar.monitor_bus import event_to_dict

    evt = MonitorEvent(
        kind="chrome_closed", task_id=42, at=datetime(2026, 1, 1, 12, 0, 0),
    )
    out = event_to_dict(evt)
    assert out["kind"] == "chrome_closed"
    assert out["task_id"] == 42
    # 不带 remaining_s / keyword 等额外字段


def test_event_to_dict_needs_captcha_carries_keyword_and_idx():
    from datetime import datetime
    from csm_sidecar.services.monitor_loop import MonitorEvent
    from csm_sidecar.monitor_bus import event_to_dict

    evt = MonitorEvent(
        kind="needs_captcha",
        task_id=42,
        at=datetime(2026, 1, 1, 12, 0, 0),
        keyword="iphone 15",
        kw_idx=5,
    )
    out = event_to_dict(evt)
    assert out["kind"] == "needs_captcha"
    assert out["keyword"] == "iphone 15"
    assert out["kw_idx"] == 5
```

- [ ] **Step 2: 运行确认失败**

Run: `cd D:/CSM/.claude/worktrees/tender-brahmagupta-f4a634 && pytest sidecar/tests/test_monitor_bus.py -k "waiting_chrome or chrome_closed or needs_captcha" -v`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'remaining_s'`

- [ ] **Step 3: 扩展 EventKind + MonitorEvent dataclass**

在 `sidecar/csm_sidecar/services/monitor_loop.py:56-61` 把 EventKind 改成：

```python
EventKind = Literal[
    "started", "finished", "alert", "failed", "tick",
    "captcha_required", "captcha_resolved", "captcha_timeout",
    "progress",
    "risk_control",
    # Native mode 方案 D：跑前等关 Chrome / Chrome 已关 / 命中风控需人工解
    "waiting_chrome_close", "chrome_closed", "needs_captcha",
]
```

在 `MonitorEvent` dataclass（约 64-75 行）末尾加：

```python
    # Native mode 方案 D 专用字段（默认 None，保持向后兼容）
    remaining_s: int | None = None  # waiting_chrome_close 倒计时
    keyword: str | None = None      # needs_captcha 的关键词文本
    kw_idx: int | None = None       # needs_captcha 的关键词索引 (0-based)
```

- [ ] **Step 4: 扩展 event_to_dict 序列化新字段**

在 `sidecar/csm_sidecar/monitor_bus.py` 的 `event_to_dict` 函数（83-108 行）的 return 之前加：

```python
    if event.remaining_s is not None:
        out["remaining_s"] = event.remaining_s
    if event.keyword is not None:
        out["keyword"] = event.keyword
    if event.kw_idx is not None:
        out["kw_idx"] = event.kw_idx
```

- [ ] **Step 5: 运行新测试 + 全套 bus 测试**

Run: `cd D:/CSM/.claude/worktrees/tender-brahmagupta-f4a634 && pytest sidecar/tests/test_monitor_bus.py -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git -C D:/CSM/.claude/worktrees/tender-brahmagupta-f4a634 add sidecar/csm_sidecar/services/monitor_loop.py sidecar/csm_sidecar/monitor_bus.py sidecar/tests/test_monitor_bus.py
git -C D:/CSM/.claude/worktrees/tender-brahmagupta-f4a634 commit -m "feat(events): add waiting_chrome_close / chrome_closed / needs_captcha events

3 个新 EventKind 给 native mode 用：等关 Chrome 倒计时、Chrome 已关、
命中验证码需人工解。MonitorEvent 加 remaining_s / keyword / kw_idx 三个
optional 字段。event_to_dict 序列化时 None 不输出（向后兼容）。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 9: 装 @tauri-apps/plugin-notification 依赖

**Files:**
- Modify: `frontend/package.json`
- Modify: `frontend/src-tauri/Cargo.toml`
- Modify: `frontend/src-tauri/src/lib.rs`
- Modify: `frontend/src-tauri/capabilities/default.json`（或同等 capabilities 文件）

- [ ] **Step 1: 装 npm 包**

```bash
cd D:/CSM/frontend && npm install @tauri-apps/plugin-notification@^2.0.0
```

（用 npm 不是 pnpm，参考 memory 中 `feedback_csm_frontend_npm_lockfile.md`）

- [ ] **Step 2: 在 Cargo.toml 加 Rust 端依赖**

打开 `frontend/src-tauri/Cargo.toml`，在 `[dependencies]` section 加：

```toml
tauri-plugin-notification = "2"
```

- [ ] **Step 3: 在 src-tauri/src/lib.rs 注册插件**

打开 `frontend/src-tauri/src/lib.rs`，在 `tauri::Builder::default()` chain 里找 `.plugin(...)` 调用集中处，加：

```rust
.plugin(tauri_plugin_notification::init())
```

如果没有别的 plugin 调用，加在 `.invoke_handler(...)` 之前。

- [ ] **Step 4: 在 capabilities 加权限**

打开 `frontend/src-tauri/capabilities/default.json`（如果不叫这个名字，先 ls 该目录确认），在 `permissions` 数组里加：

```json
"notification:default"
```

- [ ] **Step 5: cargo check 编译验证**

```bash
cd D:/CSM/frontend/src-tauri && cargo check
```

Expected: 编译通过，无 error。

- [ ] **Step 6: Commit**

```bash
git -C D:/CSM/.claude/worktrees/tender-brahmagupta-f4a634 add frontend/package.json frontend/package-lock.json frontend/src-tauri/Cargo.toml frontend/src-tauri/Cargo.lock frontend/src-tauri/src/lib.rs frontend/src-tauri/capabilities/
git -C D:/CSM/.claude/worktrees/tender-brahmagupta-f4a634 commit -m "feat(tauri): add @tauri-apps/plugin-notification

给 native mode 软着陆验证码 / 跑完 / 等 Chrome 关闭 发系统通知用。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 10: useSystemNotify composable

**Files:**
- Create: `frontend/src/composables/useSystemNotify.ts`
- Create: `frontend/src/composables/__tests__/useSystemNotify.test.ts`

- [ ] **Step 1: 看现有 composables 目录结构 + 测试约定**

Run: `ls D:/CSM/frontend/src/composables/__tests__/ 2>/dev/null || ls D:/CSM/frontend/src/composables/`
确认现有测试文件命名风格（`.test.ts` / `.spec.ts` / 同级文件 / `__tests__/` 子目录）。

- [ ] **Step 2: 写失败测试**

新建 `frontend/src/composables/__tests__/useSystemNotify.test.ts`（或按现有约定的路径）：

```typescript
import { describe, it, expect, vi, beforeEach } from "vitest"
import { useSystemNotify } from "../useSystemNotify"

vi.mock("@tauri-apps/plugin-notification", () => ({
  isPermissionGranted: vi.fn(),
  requestPermission: vi.fn(),
  sendNotification: vi.fn(),
}))

import * as notif from "@tauri-apps/plugin-notification"

describe("useSystemNotify", () => {
  beforeEach(() => {
    vi.resetAllMocks()
  })

  it("sends notification when permission already granted", async () => {
    vi.mocked(notif.isPermissionGranted).mockResolvedValue(true)
    const { notify } = useSystemNotify()
    await notify("Title", "Body")
    expect(notif.sendNotification).toHaveBeenCalledWith({ title: "Title", body: "Body" })
    expect(notif.requestPermission).not.toHaveBeenCalled()
  })

  it("requests permission then sends when not granted", async () => {
    vi.mocked(notif.isPermissionGranted).mockResolvedValue(false)
    vi.mocked(notif.requestPermission).mockResolvedValue("granted")
    const { notify } = useSystemNotify()
    await notify("T", "B")
    expect(notif.requestPermission).toHaveBeenCalled()
    expect(notif.sendNotification).toHaveBeenCalledWith({ title: "T", body: "B" })
  })

  it("silently skips when permission denied", async () => {
    vi.mocked(notif.isPermissionGranted).mockResolvedValue(false)
    vi.mocked(notif.requestPermission).mockResolvedValue("denied")
    const { notify } = useSystemNotify()
    await notify("T", "B")
    expect(notif.sendNotification).not.toHaveBeenCalled()
  })
})
```

- [ ] **Step 3: 运行测试确认失败**

Run: `cd D:/CSM/frontend && npm run test:unit -- useSystemNotify`
Expected: FAIL — 文件不存在

（如果 `npm run test:unit` 命令不存在，先看 package.json 的 scripts 找正确命令名，例如 `npm run test` / `vitest run`）

- [ ] **Step 4: 创建 useSystemNotify.ts**

新建 `frontend/src/composables/useSystemNotify.ts`：

```typescript
import {
  isPermissionGranted,
  requestPermission,
  sendNotification,
} from "@tauri-apps/plugin-notification"

/**
 * Tauri 系统通知封装。
 *
 * native mode（方案 D）用：
 *   - 等关 Chrome
 *   - 监控完成
 *   - 需要人工解验证码
 *
 * 调用方传 title + body，本封装处理权限请求 + 静默 fallback（权限拒绝时不抛）。
 */
export function useSystemNotify() {
  async function notify(title: string, body: string): Promise<void> {
    let granted = await isPermissionGranted()
    if (!granted) {
      const result = await requestPermission()
      granted = result === "granted"
    }
    if (granted) {
      await sendNotification({ title, body })
    }
  }
  return { notify }
}
```

- [ ] **Step 5: 运行测试确认通过**

Run: `cd D:/CSM/frontend && npm run test:unit -- useSystemNotify`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git -C D:/CSM/.claude/worktrees/tender-brahmagupta-f4a634 add frontend/src/composables/useSystemNotify.ts frontend/src/composables/__tests__/useSystemNotify.test.ts
git -C D:/CSM/.claude/worktrees/tender-brahmagupta-f4a634 commit -m "feat(frontend): add useSystemNotify composable

Wrap @tauri-apps/plugin-notification with permission handling +
silent fallback when denied. 给 native mode 3 类通知用。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 11: Settings 新增"百度抓取" tab

**Files:**
- Create: `frontend/src/components/settings/BaiduScrapeSettings.vue`
- Modify: 现有 Settings 入口（先 grep 找到，可能在 `frontend/src/components/settings/` 或 `frontend/src/views/`）

- [ ] **Step 1: 找现有 Settings 容器**

Run: `Grep "SettingsModal\|SettingsView\|TabsView\|SettingTab" --glob "**/*.vue" --path D:/CSM/frontend/src`
确认现有 Settings 用的 tab 容器组件路径。如果没有 tab 结构，定位最合适的 section 插入点。

- [ ] **Step 2: 创建 BaiduScrapeSettings.vue 组件**

新建 `frontend/src/components/settings/BaiduScrapeSettings.vue`：

```vue
<script setup lang="ts">
import { ref, onMounted, watch } from "vue"
import FormField from "@/components/ui/FormField.vue"
import FormInput from "@/components/ui/FormInput.vue"
import FormToggle from "@/components/ui/FormToggle.vue"

interface NativeConfig {
  use_native_chrome: boolean
  chrome_executable_path: string | null
  chrome_user_data_dir: string | null
  chrome_profile_name: string
}

interface ProfileInfo {
  name: string
  account_email: string | null
}

const config = ref<NativeConfig>({
  use_native_chrome: false,
  chrome_executable_path: null,
  chrome_user_data_dir: null,
  chrome_profile_name: "Default",
})
const profiles = ref<ProfileInfo[]>([])
const testResult = ref<{ ok: boolean; error?: string } | null>(null)
const loading = ref(false)
const errorMsg = ref("")

async function loadConfig() {
  const resp = await fetch("/api/monitor/baidu/native-config")
  if (resp.ok) config.value = await resp.json()
}

async function detectChrome() {
  loading.value = true
  errorMsg.value = ""
  try {
    const resp = await fetch("/api/monitor/baidu/detect-chrome", { method: "POST" })
    const data = await resp.json()
    config.value.chrome_executable_path = data.executable_path
    config.value.chrome_user_data_dir = data.user_data_dir
    if (data.user_data_dir) await loadProfiles()
    if (!data.executable_path) {
      errorMsg.value = "未检测到 Chrome 安装，请手动填写路径或先安装 Chrome"
    }
  } finally {
    loading.value = false
  }
}

async function loadProfiles() {
  if (!config.value.chrome_user_data_dir) {
    profiles.value = []
    return
  }
  const resp = await fetch("/api/monitor/baidu/list-profiles", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_data_dir: config.value.chrome_user_data_dir }),
  })
  if (resp.ok) {
    profiles.value = (await resp.json()).profiles
  }
}

async function testStartup() {
  loading.value = true
  testResult.value = null
  try {
    const resp = await fetch("/api/monitor/baidu/test-native", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        chrome_executable_path: config.value.chrome_executable_path,
        chrome_user_data_dir: config.value.chrome_user_data_dir,
        chrome_profile_name: config.value.chrome_profile_name,
      }),
    })
    testResult.value = await resp.json()
  } catch (e) {
    testResult.value = { ok: false, error: String(e) }
  } finally {
    loading.value = false
  }
}

async function saveConfig() {
  loading.value = true
  errorMsg.value = ""
  try {
    const resp = await fetch("/api/monitor/baidu/native-config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(config.value),
    })
    if (!resp.ok) {
      errorMsg.value = `保存失败：${await resp.text()}`
    }
  } finally {
    loading.value = false
  }
}

watch(() => config.value.chrome_user_data_dir, () => loadProfiles())

onMounted(() => {
  loadConfig()
})
</script>

<template>
  <section class="baidu-scrape-settings">
    <h2>百度抓取模式</h2>

    <FormField label="启用日常 Chrome profile 模式">
      <FormToggle v-model="config.use_native_chrome" />
      <p class="hint">
        启用后跑监控时会借用你的真实 Chrome profile 降低风控触发率。
        跑前需要先关闭 Chrome 浏览器（OS 限制）。
      </p>
    </FormField>

    <div v-if="config.use_native_chrome" class="native-config">
      <FormField label="Chrome 可执行文件路径">
        <FormInput v-model="config.chrome_executable_path" placeholder="C:\Program Files\Google\Chrome\Application\chrome.exe" />
        <button type="button" @click="detectChrome" :disabled="loading">🔍 自动探测</button>
      </FormField>

      <FormField label="Chrome User Data 目录">
        <FormInput v-model="config.chrome_user_data_dir" placeholder="%LOCALAPPDATA%\Google\Chrome\User Data" />
      </FormField>

      <FormField label="使用 Profile">
        <select v-model="config.chrome_profile_name">
          <option v-for="p in profiles" :key="p.name" :value="p.name">
            {{ p.name }}{{ p.account_email ? ` (${p.account_email})` : '' }}
          </option>
        </select>
      </FormField>

      <div class="actions">
        <button type="button" @click="testStartup" :disabled="loading || !config.chrome_executable_path || !config.chrome_user_data_dir">
          🧪 测试启动
        </button>
        <button type="button" @click="saveConfig" :disabled="loading">💾 保存</button>
      </div>

      <div v-if="testResult" class="test-result" :class="{ ok: testResult.ok, err: !testResult.ok }">
        <template v-if="testResult.ok">✓ 配置可用</template>
        <template v-else>
          ✗ 启动失败：{{ testResult.error }}
          <button type="button" @click="navigator.clipboard.writeText(testResult.error || '')">复制错误</button>
        </template>
      </div>

      <div v-if="errorMsg" class="error-banner">{{ errorMsg }}</div>
    </div>
  </section>
</template>

<style scoped>
.baidu-scrape-settings { display: flex; flex-direction: column; gap: 1rem; padding: 1rem; }
.hint { font-size: 0.85rem; color: var(--text-secondary); margin-top: 0.25rem; }
.native-config { display: flex; flex-direction: column; gap: 0.75rem; padding-left: 1rem; border-left: 2px solid var(--line); }
.actions { display: flex; gap: 0.5rem; }
.test-result.ok { color: var(--success); }
.test-result.err { color: var(--danger); }
.error-banner { padding: 0.5rem; background: var(--danger-bg); color: var(--danger); border-radius: var(--radius-inner); }
</style>
```

（如果 `@/components/ui/FormField.vue` 等组件路径不对，按 Step 1 找到的实际路径调整 import）

- [ ] **Step 3: 在 Settings 容器接入新 tab**

按 Step 1 找到的 Settings 容器结构：

- **如果是 tab 结构**：找到 tabs 数组定义，加新项 `{ id: 'baidu-scrape', label: '百度抓取', component: BaiduScrapeSettings }`
- **如果是平铺 section**：在合适位置 import + 渲染 `<BaiduScrapeSettings />`

具体路径在 Step 1 探查到后确定。

- [ ] **Step 4: 启 dev server 手动验证 UI 加载**

```bash
cd D:/CSM/frontend && npm run dev
```

打开 Settings → "百度抓取" tab → 检查：
1. Toggle 默认 OFF
2. 打开 Toggle 后看到 3 个输入字段 + Profile 下拉框
3. 点"自动探测" → 字段被 fill
4. 点"测试启动" → 应该返回 ok=true 或者明确错误

- [ ] **Step 5: Commit**

按 Step 3 实际修改的 Settings 容器文件路径填入 git add（不要留占位文本）：

```bash
git -C D:/CSM/.claude/worktrees/tender-brahmagupta-f4a634 add frontend/src/components/settings/BaiduScrapeSettings.vue
# + Step 3 改的 Settings 容器文件（具体路径以 Step 1 grep 结果为准），例如：
# git -C D:/CSM/.claude/worktrees/tender-brahmagupta-f4a634 add frontend/src/components/settings/SettingsModal.vue
git -C D:/CSM/.claude/worktrees/tender-brahmagupta-f4a634 commit -m "feat(frontend): add Baidu native mode settings tab

复用 FormField/FormToggle/FormInput 自建组件。包含自动探测、profile 选择、
测试启动、保存配置。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 12: BaiduRankingPage 加 waiting_chrome_close banner + 监控完成通知

**Files:**
- Modify: `frontend/src/components/monitor/history/BaiduRankingPage.vue:1220-1308`
- Modify: `frontend/src/stores/monitorStatus.ts`（处理 3 个新事件）

- [ ] **Step 1: 看现有进度条 + 事件处理**

Run: `Read frontend/src/components/monitor/history/BaiduRankingPage.vue 1200-1310` 和 `Read frontend/src/stores/monitorStatus.ts`
确认现有状态机和 SSE 事件 dispatch 路径。

- [ ] **Step 2: 扩展 monitorStatus.ts 处理 3 个新事件**

在 `frontend/src/stores/monitorStatus.ts` 的 SSE 事件分发逻辑中（找现有 switch / if-else on `event.kind`）加：

```typescript
case "waiting_chrome_close":
  // 把 task 状态切到 waiting_chrome_close + 记 remaining_s 用于倒计时
  store.taskStates[event.task_id] = {
    ...store.taskStates[event.task_id],
    status: "waiting_chrome_close",
    waiting_remaining_s: event.remaining_s ?? 120,
  }
  notify("CSM 百度监控", "请关闭 Chrome 浏览器以开始监控（自动检测中）")
  break

case "chrome_closed":
  // Chrome 已关，回到 running 让现有进度条接管
  store.taskStates[event.task_id] = {
    ...store.taskStates[event.task_id],
    status: "running",
    waiting_remaining_s: null,
  }
  break

case "needs_captcha":
  notify("CSM 百度监控", `需要人工解验证码（关键词：${event.keyword}），点击浏览器窗口`)
  break

case "finished":
  // native mode 跑完通知（如果是 native，文案不同）
  // 检查 task config 看是不是 native，简化处理：所有 finished 都发系统通知
  notify("CSM 百度监控", `监控完成，已抓 ${event.progress_total ?? '?'} 词`)
  break
```

`notify` 来自 `useSystemNotify`：在文件顶部 import 并初始化一次：

```typescript
import { useSystemNotify } from "@/composables/useSystemNotify"
const { notify } = useSystemNotify()
```

- [ ] **Step 3: 在 BaiduRankingPage.vue 加 waiting_chrome_close banner**

在 BaiduRankingPage.vue 的进度条区域（约 1220 行附近）加新状态分支：

```vue
<div v-if="task.status === 'waiting_chrome_close'" class="waiting-chrome-banner">
  ⏳ 任务 #{{ task.id }} 正在等待 Chrome 关闭<br>
  <small>请关闭 Chrome 浏览器以继续监控。剩余等待 {{ formatRemaining(task.waiting_remaining_s) }}</small>
  <button @click="cancelTask(task.id)" class="cancel-btn">取消任务</button>
</div>
```

加 helper：

```typescript
function formatRemaining(s: number | null | undefined): string {
  if (!s) return "--"
  const mm = Math.floor(s / 60)
  const ss = s % 60
  return `${mm}:${ss.toString().padStart(2, "0")}`
}
```

`waiting_remaining_s` 需要每秒倒计时 ── 加 `setInterval` 自动 -1：

```typescript
let countdownTimer: number | undefined
onMounted(() => {
  countdownTimer = window.setInterval(() => {
    for (const tid in store.taskStates) {
      const s = store.taskStates[tid]
      if (s.status === "waiting_chrome_close" && (s.waiting_remaining_s ?? 0) > 0) {
        s.waiting_remaining_s = (s.waiting_remaining_s ?? 0) - 1
      }
    }
  }, 1000)
})
onUnmounted(() => clearInterval(countdownTimer))
```

加样式：

```css
.waiting-chrome-banner {
  padding: 0.75rem;
  background: var(--warning-bg, #fff8e1);
  color: var(--warning, #f57c00);
  border-radius: var(--radius-inner);
  margin: 0.5rem 0;
}
.cancel-btn {
  margin-top: 0.5rem;
  padding: 0.25rem 0.75rem;
  background: var(--danger);
  color: white;
  border: none;
  border-radius: var(--radius-inner);
  cursor: pointer;
}
```

- [ ] **Step 4: 启 dev server + 手动验证**

```bash
cd D:/CSM/frontend && npm run dev
```

不容易 e2e 直接触发 native mode + waiting，所以做组件 visual 验证：
1. 临时在 monitorStatus 里手动 set `status: "waiting_chrome_close"` + `waiting_remaining_s: 90` → 看到 banner 显示倒计时
2. 验证完恢复正常

- [ ] **Step 5: Commit**

```bash
git -C D:/CSM/.claude/worktrees/tender-brahmagupta-f4a634 add frontend/src/components/monitor/history/BaiduRankingPage.vue frontend/src/stores/monitorStatus.ts
git -C D:/CSM/.claude/worktrees/tender-brahmagupta-f4a634 commit -m "feat(frontend): handle native mode events + waiting-chrome banner

3 个新事件接入 monitorStatus + 倒计时 banner + 系统通知触发
（等关 Chrome / 监控完成 / 需要人工解验证码）。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

注意：commit 时 add 的具体文件以本 Task 实际修改的为准，不要在路径里留任何占位文本。Step 1 找到的 Settings 容器修改如果跨文件，全部一起 add。

---

## Task 13: Sidecar lifespan 注入 event_publisher

**Files:**
- Modify: `sidecar/csm_sidecar/lifespan.py`（或同等启动 hook）
- Modify: `csm_core/monitor/platforms/baidu_keyword.py`（BAIDU_ADAPTER 需要 set_event_publisher 方法 + 在 fetch / _try_human_solve 调用处把 publisher 传下去）

注：Task 3 的 `wait_for_chrome_closed` 和 Task 6 的 `_try_human_solve` 已经在 signature 里支持
`event_publisher` 参数，本 Task 只负责"在 BAIDU_ADAPTER 上加注入入口 + 在 lifespan 启动时注入实现"。

- [ ] **Step 1: 找现有 sidecar 启动 hook + BAIDU_ADAPTER 模块单例**

Run: `Grep "lifespan\|startup\|on_startup" --path D:/CSM/sidecar/csm_sidecar`
找到 FastAPI lifespan 入口（通常是 `@asynccontextmanager async def lifespan(app)`）。

Run: `Grep "BAIDU_ADAPTER\|baidu_adapter\s*=" --path D:/CSM/csm_core/monitor/platforms/baidu_keyword.py`
找到 module-level singleton 实际名字。下面假设叫 `BAIDU_ADAPTER`，按实际替换。

- [ ] **Step 2: 在 BaiduKeywordAdapter 加 set_event_publisher + 内部字段**

在 `csm_core/monitor/platforms/baidu_keyword.py` 的 `BaiduKeywordAdapter.__init__` 末尾加：

```python
        self._event_publisher: Any = None
```

加 setter 方法：

```python
    def set_event_publisher(self, fn: Any) -> None:
        """Sidecar lifespan 启动时注入，给 native mode chrome_preflight +
        软着陆验证码 发 SSE 事件用。"""
        self._event_publisher = fn
```

- [ ] **Step 3: 修改 Task 5 加的 preflight 调用 + Task 6 加的 _try_human_solve 调用，传 publisher**

把 Task 5 加的 preflight 块：

```python
        if use_native:
            try:
                chrome_preflight.wait_for_chrome_closed(timeout_s=120)
            except chrome_preflight.ChromeStillRunningError as e:
                ...
```

改成：

```python
        if use_native:
            try:
                chrome_preflight.wait_for_chrome_closed(
                    timeout_s=120,
                    task_id=task.id or 0,
                    event_publisher=self._event_publisher,
                )
            except chrome_preflight.ChromeStillRunningError as e:
                ...
```

把 Task 6 主循环 hook 里的 `_try_human_solve(page=page, keyword=keyword, kw_idx=kw_idx)` 改成：

```python
                    solved = _try_human_solve(
                        page=page, keyword=keyword, kw_idx=kw_idx,
                        task_id=task.id,
                        event_publisher=self._event_publisher,
                    )
```

- [ ] **Step 4: 在 lifespan 启动段注入 publisher**

在 sidecar lifespan 启动段（Step 1 找到的位置）加：

```python
from csm_core.monitor.platforms import baidu_keyword as bk_module
from csm_sidecar.monitor_bus import monitor_bus
from csm_sidecar.services.monitor_loop import MonitorEvent
from datetime import datetime
from typing import Any


def _publish_native_event(payload: dict[str, Any]) -> None:
    """从 csm_core 收到 dict 形态事件 → 包成 MonitorEvent → publish 到 monitor_bus。"""
    evt = MonitorEvent(
        kind=payload["kind"],
        task_id=payload.get("task_id", 0),
        at=datetime.utcnow(),
        remaining_s=payload.get("remaining_s"),
        keyword=payload.get("keyword"),
        kw_idx=payload.get("kw_idx"),
    )
    monitor_bus.publish(evt)


bk_module.BAIDU_ADAPTER.set_event_publisher(_publish_native_event)
```

（按 Step 1 找到的实际 singleton 名字替换 `BAIDU_ADAPTER`）

- [ ] **Step 5: 跑全套后端测试确保没破坏现有行为**

Run: `cd D:/CSM/.claude/worktrees/tender-brahmagupta-f4a634 && pytest sidecar/tests/ -v -x`
Expected: ALL PASS

如果 Task 5/6 的测试因 publisher 参数变化失败，是因为 publisher=None 时默认不应抛 —— 测试本身不需要改（功能层面 publisher 是 optional）。

- [ ] **Step 6: 集成测试 — fetch() 触发 preflight 时 monitor_bus 收到 waiting_chrome_close 事件**

新增测试在 `sidecar/tests/test_baidu_keyword.py`：

```python
def test_fetch_publishes_waiting_chrome_close_event(monkeypatch):
    """native mode + Chrome 在跑 → 应该 publish waiting_chrome_close 到 monitor_bus。"""
    from csm_sidecar.monitor_bus import monitor_bus
    from csm_sidecar.services.monitor_loop import MonitorEvent
    from csm_core.monitor.drivers import chrome_preflight
    from csm_core.monitor.platforms import baidu_keyword
    from csm_core.monitor.base import MonitorTask, TaskType
    from datetime import datetime
    from typing import Any

    # 安装 publisher（模拟 lifespan）
    published: list[MonitorEvent] = []
    def fake_publisher(payload: dict[str, Any]) -> None:
        published.append(MonitorEvent(
            kind=payload["kind"],
            task_id=payload.get("task_id", 0),
            at=datetime.utcnow(),
            remaining_s=payload.get("remaining_s"),
            keyword=payload.get("keyword"),
            kw_idx=payload.get("kw_idx"),
        ))

    adapter = baidu_keyword.BaiduKeywordAdapter()
    adapter.set_event_publisher(fake_publisher)

    # mock Chrome 前 2 次在跑、第 3 次关闭
    state = {"calls": 0}
    def fake_is_running():
        state["calls"] += 1
        return state["calls"] <= 2
    monkeypatch.setattr(chrome_preflight, "is_chrome_running", fake_is_running)
    monkeypatch.setattr(chrome_preflight, "_notify", lambda **kw: None)

    fake_cfg = MagicMock()
    fake_cfg.monitor.baidu_keyword.use_native_chrome = True
    fake_cfg.monitor.baidu_keyword.chrome_executable_path = "C:/x/chrome.exe"
    fake_cfg.monitor.baidu_keyword.chrome_user_data_dir = "C:/x/User Data"
    fake_cfg.monitor.baidu_keyword.chrome_profile_name = "Default"
    monkeypatch.setattr("csm_core.config.get_config", lambda: fake_cfg)

    from contextlib import contextmanager
    @contextmanager
    def fake_session(**kw):
        sess = MagicMock()
        sess.page = MagicMock()
        sess.context = MagicMock()
        sess.context.cookies.return_value = [{"name": "BDUSS", "value": "x"}]
        yield sess
    monkeypatch.setattr(baidu_keyword, "baidu_browser_session", fake_session)

    task = MonitorTask(
        id=99, type=TaskType.baidu_keyword, name="t", target_url="https://baidu.com",
        config={"search_keywords": [], "target_brand": "x"},
    )
    adapter.fetch(task)

    kinds = [e.kind for e in published]
    assert "waiting_chrome_close" in kinds
    assert "chrome_closed" in kinds
    # task_id 正确
    assert all(e.task_id == 99 for e in published if e.task_id)
```

- [ ] **Step 7: 跑新集成测试**

Run: `cd D:/CSM/.claude/worktrees/tender-brahmagupta-f4a634 && pytest sidecar/tests/test_baidu_keyword.py::test_fetch_publishes_waiting_chrome_close_event -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git -C D:/CSM/.claude/worktrees/tender-brahmagupta-f4a634 add csm_core/monitor/platforms/baidu_keyword.py sidecar/csm_sidecar/lifespan.py sidecar/tests/test_baidu_keyword.py
git -C D:/CSM/.claude/worktrees/tender-brahmagupta-f4a634 commit -m "feat(monitor): wire native mode events through monitor_bus

BaiduKeywordAdapter 加 set_event_publisher；sidecar lifespan 启动时注入
把 dict 形态事件包成 MonitorEvent publish 到 monitor_bus。集成测试覆盖
fetch → preflight → waiting_chrome_close + chrome_closed 事件链。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 14: 真机手动测试 + 验证清单

**Files:**
- 无代码改动，纯手动测试

- [ ] **Step 1: 在主仓 git pull 最新代码 + worktree merge**

```bash
git -C D:/CSM/.claude/worktrees/tender-brahmagupta-f4a634 checkout main
git -C D:/CSM/.claude/worktrees/tender-brahmagupta-f4a634 pull --ff-only
git -C D:/CSM/.claude/worktrees/tender-brahmagupta-f4a634 fetch origin
```

按照 memory `reference_csm_dev_worktree_setup.md` 重启 sidecar editable install。

- [ ] **Step 2: 启动 CSM dev 模式**

```bash
cd D:/CSM/.claude/worktrees/tender-brahmagupta-f4a634/frontend && ./dev.ps1
```

或用 memory `reference_csm_worktree_tauri_coldstart.md` 的 cold-start 优化。

- [ ] **Step 3: 手动测试 checklist —— Settings 配置流**

按顺序操作并对照预期：

| 操作 | 预期 |
|---|---|
| 打开 Settings → "百度抓取" tab | 看到 toggle (OFF) + 描述 |
| 打开 toggle | 展开 3 个输入字段 + Profile 下拉框 + 测试/保存按钮 |
| 点 "自动探测" | 3 个字段被 fill；Profile 下拉显示账号 email |
| 改 Profile 下拉到别的 profile | 字段更新 |
| 点 "测试启动"（Chrome 是开的）| 失败：profile lock 错误，明确报错信息 |
| 关闭 Chrome → 再点 "测试启动" | ✓ 配置可用 |
| 点 "保存" | 静默成功，刷新页面验证字段被持久化 |

- [ ] **Step 4: 手动测试 —— 跑监控流**

| 操作 | 预期 |
|---|---|
| 创建一个 5 词的百度任务 → 启动监控 | 因 toggle 已 ON，Chrome 又是关的 → 直接进 running，跑完 5 词 |
| 开 Chrome → 再启动监控 | 看到 waiting_chrome_close banner + 倒计时 + 系统通知 "请关闭 Chrome" |
| 关 Chrome | 1 秒内 banner 消失，进入 running |
| 跑完 | 系统通知 "监控完成，已抓 N 词" |

- [ ] **Step 5: 手动测试 —— 软着陆验证码**

| 操作 | 预期 |
|---|---|
| 设置 SERP pacing 到 1s（强制触发风控）| 配置生效 |
| 启动监控连续跑 20 词 | 中间某次必触发风控 |
| 触发后浏览器窗口已在前台显示验证码 + 系统通知 "需要人工解验证码（关键词：xxx）" | 通知到达 |
| 手动在浏览器解验证码 | 解完 1-2 秒内 CSM 继续跑 |
| 进度不丢，从中断的 kw 继续 | ✓ |

- [ ] **Step 6: 真实容量测试 —— 100 词**

| 操作 | 预期 |
|---|---|
| 准备 100 个真实关键词的任务 | 配置就绪 |
| 默认 pacing 启动监控 | 100 词跑完，记录耗时 |
| 期望 60-150 分钟、触发 0-3 次 | 记录实际数字 |

- [ ] **Step 7: 把真实数据写到 spec 验证 section**

把 Step 6 的实际耗时 + 触发率追加到 `docs/superpowers/specs/2026-05-24-baidu-anti-risk-design.md` 的"性能与风控预期" section 末尾"实测数据"小节：

```markdown
### 实测数据（首轮）

- 实施日期：2026-MM-DD
- 关键词数：100
- 配置：默认 pacing（SERP 5-10s + 文章 3-6s）
- 实际耗时：MM 分钟
- 触发风控次数：N
- 人工解题平均耗时：S 秒
- 结论：[符合预期 / 偏差及原因]
```

- [ ] **Step 8: 最终 commit**

```bash
git -C D:/CSM/.claude/worktrees/tender-brahmagupta-f4a634 add docs/superpowers/specs/2026-05-24-baidu-anti-risk-design.md
git -C D:/CSM/.claude/worktrees/tender-brahmagupta-f4a634 commit -m "docs(monitor): record native mode first-week real-world data

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## 完成标志

- [ ] 所有 14 个 Task 的 step 都打勾完成
- [ ] `pytest sidecar/tests/` 全过
- [ ] `npm run test:unit`（前端）全过
- [ ] 手动 checklist Step 3-6 全部预期符合
- [ ] 实测数据已记录到 spec
- [ ] 创建 PR 准备 review

```bash
git -C D:/CSM/.claude/worktrees/tender-brahmagupta-f4a634 push -u origin claude/tender-brahmagupta-f4a634
cd D:/CSM/.claude/worktrees/tender-brahmagupta-f4a634 && gh pr create --title "feat(monitor): baidu native chrome mode (方案 D)" --body "$(cat <<'EOF'
## Summary
- 给百度抓取加 native mode：挂载用户日常 Chrome profile（无养号、无复制副本）
- 跑前轮询等关 Chrome，软着陆验证码（解完继续不丢进度），系统通知（等关 Chrome / 跑完 / 需解验证）
- 5 个新 API + 3 个新 SSE 事件 + Settings 新 tab + waiting_chrome_close banner

## Spec
docs/superpowers/specs/2026-05-24-baidu-anti-risk-design.md

## Test plan
- [x] 后端单元测试全过（chrome_detect / chrome_preflight / baidu_browser native / baidu_keyword preflight + 软着陆）
- [x] 后端集成测试全过（5 API + 3 新 SSE 事件）
- [x] 前端单元测试全过（useSystemNotify）
- [x] 手动 100 词实测（数据记录到 spec）

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```
