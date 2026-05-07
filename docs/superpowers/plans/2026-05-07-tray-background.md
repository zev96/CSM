# 系统托盘后台挂载 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 CSM 关闭按钮（×）默认行为改成"最小化到 Windows 系统托盘"，同时加单实例锁，避免多开。

**Architecture:** 新增 `csm_gui/tray/` 模块封装托盘 UI 与单实例 socket。`MainWindow.closeEvent` 拦截后按 `AppConfig.close_action` 决定隐藏或退出；托盘菜单的 6 个操作通过 Qt signals 上抛到 MainWindow 复用现有导航逻辑。设置页加一个 close_action 选择器。

**Tech Stack:** PyQt6 (`QSystemTrayIcon`, `QMenu`, `QLocalServer`, `QLocalSocket`), qfluentwidgets, pydantic v2 (AppConfig), pytest-qt

**Spec:** [docs/superpowers/specs/2026-05-07-tray-background-design.md](../specs/2026-05-07-tray-background-design.md)

---

## File Structure

**Create:**
- `csm_gui/tray/__init__.py`
- `csm_gui/tray/icon.py` — `load_tray_icon() -> QIcon`
- `csm_gui/tray/menu.py` — `TrayMenu(QMenu)` 暴露 6 个 signal
- `csm_gui/tray/manager.py` — `TrayManager(QObject)` 组合 QSystemTrayIcon + TrayMenu
- `csm_gui/tray/single_instance.py` — `SingleInstance(QObject)` QLocalServer 封装
- `tests/gui/test_tray_icon.py`
- `tests/gui/test_tray_menu.py`
- `tests/gui/test_tray_manager.py`
- `tests/gui/test_single_instance.py`

**Modify:**
- `csm_gui/config.py` — AppConfig 加 `close_action`, `tray_first_minimize_shown`
- `csm_gui/app.py` — 启动加 SingleInstance + TrayManager，window.show() 之前
- `csm_gui/main_window.py` — closeEvent 拦截、托盘 signal 接线、_show_main_window 方法
- `csm_gui/pages/settings_page.py` — 关闭按钮行为选择器
- `tests/gui/test_config.py` — 新字段测试
- `tests/gui/test_main_window.py` — closeEvent 行为测试
- `tests/gui/test_settings_page.py` — close_action UI 测试

**Test layout:** 与现有项目一致——pytest 用 `qtbot` fixture（pytest-qt 自带，无需 import）。

---

## Task 1: AppConfig 加 close_action 与 tray_first_minimize_shown 字段

**Files:**
- Modify: `csm_gui/config.py`
- Modify: `tests/gui/test_config.py`

- [ ] **Step 1: 写失败测试 — 字段默认值**

打开 `tests/gui/test_config.py`，追加：

```python
def test_appconfig_default_close_action():
    from csm_gui.config import AppConfig
    cfg = AppConfig()
    assert cfg.close_action == "minimize_to_tray"
    assert cfg.tray_first_minimize_shown is False


def test_appconfig_close_action_validates_literal():
    from csm_gui.config import AppConfig
    from pydantic import ValidationError
    import pytest
    with pytest.raises(ValidationError):
        AppConfig(close_action="invalid_value")


def test_appconfig_loads_old_settings_without_close_action(tmp_path):
    """老 settings.json 没有 close_action 时回退到默认值（向后兼容）。"""
    from csm_gui.config import AppConfig, load_config
    p = tmp_path / "settings.json"
    p.write_text('{"vault_root":"/tmp"}', encoding="utf-8")
    cfg = load_config(p)
    assert cfg.close_action == "minimize_to_tray"
    assert cfg.tray_first_minimize_shown is False
```

- [ ] **Step 2: 跑测试确认失败**

```bash
pytest tests/gui/test_config.py::test_appconfig_default_close_action -v
```

预期：`AttributeError` 或 `ValidationError` — 字段不存在。

- [ ] **Step 3: 在 AppConfig 加字段**

修改 `csm_gui/config.py`：

```python
# 文件顶部 Provider 定义下方加 CloseAction 类型别名
CloseAction = Literal["minimize_to_tray", "quit"]


class AppConfig(BaseModel):
    # ... 既有字段保持不变 ...
    export_format: Literal["markdown", "docx"] = "markdown"
    
    # 新增字段
    close_action: CloseAction = "minimize_to_tray"
    tray_first_minimize_shown: bool = False
```

- [ ] **Step 4: 跑测试确认通过**

```bash
pytest tests/gui/test_config.py -v
```

预期：所有 3 个新测试 PASS，旧测试不应回归。

- [ ] **Step 5: 提交**

```bash
git add csm_gui/config.py tests/gui/test_config.py
git commit -m "feat(config): add close_action and tray_first_minimize_shown fields"
```

---

## Task 2: 单实例锁 SingleInstance 模块

**Files:**
- Create: `csm_gui/tray/__init__.py`
- Create: `csm_gui/tray/single_instance.py`
- Create: `tests/gui/test_single_instance.py`

- [ ] **Step 1: 创建空 `__init__.py`**

```bash
mkdir -p csm_gui/tray
```

写文件 `csm_gui/tray/__init__.py`：

```python
"""System tray + single-instance components."""
```

- [ ] **Step 2: 写失败测试 — 第一个实例 try_acquire 成功，第二个返回 False**

写文件 `tests/gui/test_single_instance.py`：

```python
"""SingleInstance: only the first process binds the local server."""
from __future__ import annotations
from csm_gui.tray.single_instance import SingleInstance


def test_first_instance_acquires(qtbot):
    inst = SingleInstance(server_name="csm-test-singleton-1")
    qtbot.addWidget(inst)  # not strictly necessary for QObject, but qtbot needs *something* — use a dummy QObject host
    assert inst.try_acquire() is True
    inst.release()


def test_second_instance_detects_running(qtbot):
    a = SingleInstance(server_name="csm-test-singleton-2")
    b = SingleInstance(server_name="csm-test-singleton-2")
    assert a.try_acquire() is True
    assert b.try_acquire() is False  # 第二个失败
    a.release()


def test_show_signal_emitted_on_second_launch(qtbot):
    """第二个实例发 'show' 命令后第一个的 show_requested signal 应触发。"""
    a = SingleInstance(server_name="csm-test-singleton-3")
    b = SingleInstance(server_name="csm-test-singleton-3")
    assert a.try_acquire() is True
    assert b.try_acquire() is False

    with qtbot.waitSignal(a.show_requested, timeout=2000):
        b.send_show()

    a.release()


def test_stale_socket_cleaned_up(qtbot, tmp_path, monkeypatch):
    """如果有陈旧 socket 残留，第一个实例应能清理后正常 acquire。"""
    # 模拟陈旧 server：先创建一个不响应的 server，再创建第二个尝试 acquire
    import os
    a = SingleInstance(server_name="csm-test-singleton-4")
    assert a.try_acquire() is True
    # 不调 release，模拟崩溃
    del a

    # 第二次启动应能清理并成功
    b = SingleInstance(server_name="csm-test-singleton-4")
    assert b.try_acquire() is True
    b.release()
```

注意：`qtbot.addWidget` 只接受 QWidget，QObject 不需要它注册。简化第一个测试：

```python
def test_first_instance_acquires():
    from csm_gui.tray.single_instance import SingleInstance
    inst = SingleInstance(server_name="csm-test-singleton-1")
    assert inst.try_acquire() is True
    inst.release()
```

把所有 `qtbot.addWidget(inst)` 删掉（QObject 不需要）。

- [ ] **Step 3: 跑测试确认失败**

```bash
pytest tests/gui/test_single_instance.py -v
```

预期：`ModuleNotFoundError: No module named 'csm_gui.tray.single_instance'`。

- [ ] **Step 4: 实现 SingleInstance**

写文件 `csm_gui/tray/single_instance.py`：

```python
"""Single-instance lock via QLocalServer/Socket.

Usage in app.py:
    inst = SingleInstance("csm-app-singleton")
    if not inst.try_acquire():
        inst.send_show()
        sys.exit(0)
    # main process keeps `inst` alive; connect inst.show_requested to MainWindow.
"""
from __future__ import annotations
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtNetwork import QLocalServer, QLocalSocket

_SHOW_MSG = b"show\n"
_TIMEOUT_MS = 2000


class SingleInstance(QObject):
    """Bind a named local socket; second instance detects and notifies first.

    The chosen ``server_name`` must be unique to the app + user — Windows
    pipe names live in a shared namespace within a logon session.
    """

    show_requested = pyqtSignal()

    def __init__(self, server_name: str = "csm-app-singleton",
                 parent: QObject | None = None):
        super().__init__(parent)
        self._name = server_name
        self._server: QLocalServer | None = None
        self._acquired = False

    def try_acquire(self) -> bool:
        """Attempt to bind the server. Return True iff this is the first process.

        If a stale socket file remains from a crashed prior process,
        ``QLocalServer.removeServer`` clears it and we try again.
        """
        # Quick probe: try to connect as client. If a real server answers,
        # this process is NOT first.
        probe = QLocalSocket()
        probe.connectToServer(self._name)
        if probe.waitForConnected(_TIMEOUT_MS):
            probe.disconnectFromServer()
            return False
        probe.abort()

        # No server answering — clean any stale name then bind.
        QLocalServer.removeServer(self._name)
        self._server = QLocalServer(self)
        if not self._server.listen(self._name):
            self._server = None
            return False
        self._server.newConnection.connect(self._on_new_connection)
        self._acquired = True
        return True

    def _on_new_connection(self) -> None:
        assert self._server is not None
        sock = self._server.nextPendingConnection()
        if sock is None:
            return
        if sock.waitForReadyRead(_TIMEOUT_MS):
            data = bytes(sock.readAll())
            if data.strip() == b"show":
                self.show_requested.emit()
        sock.disconnectFromServer()
        sock.deleteLater()

    def send_show(self) -> bool:
        """Send a 'show' command to an existing instance. Return True on success."""
        sock = QLocalSocket()
        sock.connectToServer(self._name)
        if not sock.waitForConnected(_TIMEOUT_MS):
            return False
        sock.write(_SHOW_MSG)
        ok = sock.waitForBytesWritten(_TIMEOUT_MS)
        sock.disconnectFromServer()
        return ok

    def release(self) -> None:
        """Close the server. Safe to call multiple times."""
        if self._server is not None:
            self._server.close()
            self._server = None
        self._acquired = False

    def __del__(self):
        try:
            self.release()
        except Exception:
            pass
```

- [ ] **Step 5: 跑测试确认通过**

```bash
pytest tests/gui/test_single_instance.py -v
```

预期：所有 4 个测试 PASS。

如有失败：检查 `QLocalServer` 是否需要在 windows 下用 `setSocketOptions(QLocalServer.SocketOption.UserAccessOption)` —— 默认即可，不需要。

- [ ] **Step 6: 提交**

```bash
git add csm_gui/tray/__init__.py csm_gui/tray/single_instance.py tests/gui/test_single_instance.py
git commit -m "feat(tray): single-instance lock via QLocalServer"
```

---

## Task 3: 托盘图标加载器

**Files:**
- Create: `csm_gui/tray/icon.py`
- Create: `tests/gui/test_tray_icon.py`

- [ ] **Step 1: 写失败测试**

写文件 `tests/gui/test_tray_icon.py`：

```python
"""Tray icon loader: prefer bundled logo, fall back to a Fluent icon."""
from PyQt6.QtGui import QIcon
from csm_gui.tray.icon import load_tray_icon


def test_load_tray_icon_returns_qicon(qtbot):
    icon = load_tray_icon()
    assert isinstance(icon, QIcon)
    assert not icon.isNull()


def test_load_tray_icon_uses_bundled_logo_when_present(tmp_path, monkeypatch):
    """If assets/csm-logo.png exists, the icon should be loadable."""
    # The real assets path may or may not exist depending on dev setup.
    # We just verify load_tray_icon never crashes — see test_load_tray_icon_returns_qicon.
    icon = load_tray_icon()
    assert not icon.isNull()
```

- [ ] **Step 2: 跑测试确认失败**

```bash
pytest tests/gui/test_tray_icon.py -v
```

预期：`ModuleNotFoundError`。

- [ ] **Step 3: 实现**

写文件 `csm_gui/tray/icon.py`：

```python
"""Tray icon loader.

Prefers ``csm_gui/assets/csm-logo.png`` if shipped with the build;
falls back to qfluentwidgets' FluentIcon.HOME so the tray works even
before the asset is bundled.
"""
from __future__ import annotations
from pathlib import Path
from PyQt6.QtGui import QIcon


def load_tray_icon() -> QIcon:
    """Return a non-null QIcon suitable for QSystemTrayIcon.

    The icon should be at least 16×16; both ``.png`` and the FluentIcon
    fallback satisfy this.
    """
    logo = Path(__file__).resolve().parent.parent / "assets" / "csm-logo.png"
    if logo.exists():
        ic = QIcon(str(logo))
        if not ic.isNull():
            return ic

    # Fallback: qfluentwidgets ships icons as resource paths usable by QIcon.
    try:
        from qfluentwidgets import FluentIcon
        return FluentIcon.HOME.icon()
    except Exception:
        # Absolute last resort: the Qt standard icon. Still non-null.
        from PyQt6.QtWidgets import QApplication, QStyle
        app = QApplication.instance()
        if app is not None:
            return app.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)
        return QIcon()
```

- [ ] **Step 4: 跑测试确认通过**

```bash
pytest tests/gui/test_tray_icon.py -v
```

预期：2 PASS。

- [ ] **Step 5: 提交**

```bash
git add csm_gui/tray/icon.py tests/gui/test_tray_icon.py
git commit -m "feat(tray): icon loader with bundled-logo + Fluent fallback"
```

---

## Task 4: 托盘右键菜单 TrayMenu

**Files:**
- Create: `csm_gui/tray/menu.py`
- Create: `tests/gui/test_tray_menu.py`

- [ ] **Step 1: 写失败测试**

写文件 `tests/gui/test_tray_menu.py`：

```python
"""TrayMenu: 6 actions, each emits its dedicated signal."""
from csm_gui.tray.menu import TrayMenu


def test_tray_menu_has_six_actions(qtbot):
    menu = TrayMenu()
    qtbot.addWidget(menu)
    labels = [a.text() for a in menu.actions() if not a.isSeparator()]
    assert labels == ["显示主界面", "新建文章", "新建模板", "新建 Skill", "设置", "退出 CSM"]


def test_show_action_emits_signal(qtbot):
    menu = TrayMenu()
    qtbot.addWidget(menu)
    with qtbot.waitSignal(menu.show_requested, timeout=1000):
        menu.actions()[0].trigger()


def test_new_article_emits_signal(qtbot):
    menu = TrayMenu()
    qtbot.addWidget(menu)
    with qtbot.waitSignal(menu.new_article_requested, timeout=1000):
        menu.actions()[1].trigger()


def test_new_template_emits_signal(qtbot):
    menu = TrayMenu()
    qtbot.addWidget(menu)
    with qtbot.waitSignal(menu.new_template_requested, timeout=1000):
        menu.actions()[2].trigger()


def test_new_skill_emits_signal(qtbot):
    menu = TrayMenu()
    qtbot.addWidget(menu)
    with qtbot.waitSignal(menu.new_skill_requested, timeout=1000):
        menu.actions()[3].trigger()


def test_settings_emits_signal(qtbot):
    menu = TrayMenu()
    qtbot.addWidget(menu)
    with qtbot.waitSignal(menu.settings_requested, timeout=1000):
        menu.actions()[4].trigger()


def test_quit_emits_signal(qtbot):
    menu = TrayMenu()
    qtbot.addWidget(menu)
    # 退出 CSM 是第 6 个（index 5），但要跳过分隔符。检查通过 text 而不是 index。
    quit_action = next(a for a in menu.actions() if a.text() == "退出 CSM")
    with qtbot.waitSignal(menu.quit_requested, timeout=1000):
        quit_action.trigger()
```

注意：`menu.actions()[0]` 这种 index 写法会因为分隔符位置漂移失败。**改用 text 查找**：

```python
def _action(menu, text):
    return next(a for a in menu.actions() if a.text() == text)


def test_show_action_emits_signal(qtbot):
    menu = TrayMenu()
    qtbot.addWidget(menu)
    with qtbot.waitSignal(menu.show_requested, timeout=1000):
        _action(menu, "显示主界面").trigger()
```

把所有 `menu.actions()[N]` 改成 `_action(menu, "标签")`。

- [ ] **Step 2: 跑测试确认失败**

```bash
pytest tests/gui/test_tray_menu.py -v
```

预期：`ModuleNotFoundError`。

- [ ] **Step 3: 实现**

写文件 `csm_gui/tray/menu.py`：

```python
"""Tray right-click menu.

Six actions, each fires its own pyqtSignal so the parent can route
them without inspecting QAction identity.
"""
from __future__ import annotations
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QMenu, QWidget


class TrayMenu(QMenu):
    show_requested = pyqtSignal()
    new_article_requested = pyqtSignal()
    new_template_requested = pyqtSignal()
    new_skill_requested = pyqtSignal()
    settings_requested = pyqtSignal()
    quit_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)

        self._add("显示主界面", self.show_requested)
        self._add("新建文章", self.new_article_requested)
        self._add("新建模板", self.new_template_requested)
        self._add("新建 Skill", self.new_skill_requested)
        self._add("设置", self.settings_requested)
        self.addSeparator()
        self._add("退出 CSM", self.quit_requested)

    def _add(self, label: str, signal) -> QAction:
        act = QAction(label, self)
        act.triggered.connect(signal.emit)
        self.addAction(act)
        return act
```

- [ ] **Step 4: 跑测试确认通过**

```bash
pytest tests/gui/test_tray_menu.py -v
```

预期：7 PASS。

- [ ] **Step 5: 提交**

```bash
git add csm_gui/tray/menu.py tests/gui/test_tray_menu.py
git commit -m "feat(tray): right-click menu with six action signals"
```

---

## Task 5: TrayManager 组合 QSystemTrayIcon + TrayMenu

**Files:**
- Create: `csm_gui/tray/manager.py`
- Create: `tests/gui/test_tray_manager.py`

- [ ] **Step 1: 写失败测试**

写文件 `tests/gui/test_tray_manager.py`：

```python
"""TrayManager wires the QSystemTrayIcon + TrayMenu and re-exposes signals."""
from PyQt6.QtWidgets import QSystemTrayIcon
from csm_gui.tray.manager import TrayManager


def test_manager_creates_when_tray_available(qtbot):
    if not QSystemTrayIcon.isSystemTrayAvailable():
        import pytest
        pytest.skip("system tray not available in this environment")
    mgr = TrayManager()
    assert mgr.is_available() is True
    assert mgr.tray_icon is not None


def test_manager_tooltip(qtbot):
    if not QSystemTrayIcon.isSystemTrayAvailable():
        import pytest
        pytest.skip("system tray not available in this environment")
    mgr = TrayManager()
    assert mgr.tray_icon.toolTip() == "CSM — Content Studio"


def test_manager_double_click_emits_show(qtbot):
    """Double-click on the tray icon should emit show_requested."""
    if not QSystemTrayIcon.isSystemTrayAvailable():
        import pytest
        pytest.skip("system tray not available in this environment")
    mgr = TrayManager()
    with qtbot.waitSignal(mgr.show_requested, timeout=1000):
        mgr._on_activated(QSystemTrayIcon.ActivationReason.DoubleClick)


def test_manager_left_click_emits_show(qtbot):
    if not QSystemTrayIcon.isSystemTrayAvailable():
        import pytest
        pytest.skip("system tray not available in this environment")
    mgr = TrayManager()
    with qtbot.waitSignal(mgr.show_requested, timeout=1000):
        mgr._on_activated(QSystemTrayIcon.ActivationReason.Trigger)


def test_manager_right_click_does_not_emit_show(qtbot):
    """Right-click shows the context menu, not the main window."""
    if not QSystemTrayIcon.isSystemTrayAvailable():
        import pytest
        pytest.skip("system tray not available in this environment")
    mgr = TrayManager()
    received = []
    mgr.show_requested.connect(lambda: received.append(True))
    mgr._on_activated(QSystemTrayIcon.ActivationReason.Context)
    qtbot.wait(100)
    assert received == []


def test_manager_relays_menu_signals(qtbot):
    if not QSystemTrayIcon.isSystemTrayAvailable():
        import pytest
        pytest.skip("system tray not available in this environment")
    mgr = TrayManager()
    with qtbot.waitSignal(mgr.new_article_requested, timeout=1000):
        mgr._menu.new_article_requested.emit()


def test_show_message_first_minimize(qtbot):
    """show_first_minimize_bubble triggers a tray notification."""
    if not QSystemTrayIcon.isSystemTrayAvailable():
        import pytest
        pytest.skip("system tray not available in this environment")
    mgr = TrayManager()
    # Should not raise. Visually verifying the bubble is out of scope here.
    mgr.show_first_minimize_bubble()
```

- [ ] **Step 2: 跑测试确认失败**

```bash
pytest tests/gui/test_tray_manager.py -v
```

预期：`ModuleNotFoundError`。

- [ ] **Step 3: 实现**

写文件 `csm_gui/tray/manager.py`：

```python
"""TrayManager: owns QSystemTrayIcon, hooks up menu, exposes uniform signals.

Lifetime: created in app.py and held by MainWindow. Single instance per
process. Calling ``show()`` is what makes the icon visible — no tray
appears until the manager is told to.
"""
from __future__ import annotations
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QSystemTrayIcon
from .icon import load_tray_icon
from .menu import TrayMenu

_TOOLTIP = "CSM — Content Studio"
_FIRST_MINIMIZE_TITLE = "CSM 已最小化到托盘"
_FIRST_MINIMIZE_MSG = (
    "CSM 在后台运行。可在右下角托盘图标双击恢复主界面，"
    "或在设置中改回直接退出。"
)


class TrayManager(QObject):
    """Combines QSystemTrayIcon + TrayMenu, re-exposes the menu's signals.

    Right-click shows the menu. Left/double click emits ``show_requested``.
    """

    show_requested = pyqtSignal()
    new_article_requested = pyqtSignal()
    new_template_requested = pyqtSignal()
    new_skill_requested = pyqtSignal()
    settings_requested = pyqtSignal()
    quit_requested = pyqtSignal()

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._available = QSystemTrayIcon.isSystemTrayAvailable()
        self._menu = TrayMenu()
        self.tray_icon: QSystemTrayIcon | None = None
        if self._available:
            self.tray_icon = QSystemTrayIcon(load_tray_icon(), self)
            self.tray_icon.setToolTip(_TOOLTIP)
            self.tray_icon.setContextMenu(self._menu)
            self.tray_icon.activated.connect(self._on_activated)
        self._wire_menu()

    def _wire_menu(self) -> None:
        self._menu.show_requested.connect(self.show_requested.emit)
        self._menu.new_article_requested.connect(self.new_article_requested.emit)
        self._menu.new_template_requested.connect(self.new_template_requested.emit)
        self._menu.new_skill_requested.connect(self.new_skill_requested.emit)
        self._menu.settings_requested.connect(self.settings_requested.emit)
        self._menu.quit_requested.connect(self.quit_requested.emit)

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        # Trigger == single left click (Win + Linux). DoubleClick == double left click.
        # Context == right click → Qt automatically shows the contextMenu.
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.show_requested.emit()

    def is_available(self) -> bool:
        return self._available

    def show(self) -> None:
        if self.tray_icon is not None:
            self.tray_icon.show()

    def hide(self) -> None:
        if self.tray_icon is not None:
            self.tray_icon.hide()

    def show_first_minimize_bubble(self) -> None:
        if self.tray_icon is None:
            return
        # 5000ms → 5s, the OS may shorten this on its own.
        self.tray_icon.showMessage(
            _FIRST_MINIMIZE_TITLE, _FIRST_MINIMIZE_MSG,
            QSystemTrayIcon.MessageIcon.Information, 5000,
        )
```

- [ ] **Step 4: 跑测试确认通过**

```bash
pytest tests/gui/test_tray_manager.py -v
```

预期：7 PASS（如 CI 环境无系统托盘则 SKIP）。

- [ ] **Step 5: 提交**

```bash
git add csm_gui/tray/manager.py tests/gui/test_tray_manager.py
git commit -m "feat(tray): TrayManager combining icon + menu with unified signals"
```

---

## Task 6: 设置页加 close_action 选择器

**Files:**
- Modify: `csm_gui/pages/settings_page.py`
- Modify: `tests/gui/test_settings_page.py`

- [ ] **Step 1: 看现有 settings_page 结构（不修改）**

```bash
head -100 csm_gui/pages/settings_page.py
```

记下：现有 layout 是什么；如何拿到 AppConfig；how on_save 接受变更。需要在某个区块（推荐"通用"或类似）追加一个"关闭按钮行为"行。

- [ ] **Step 2: 写失败测试**

打开 `tests/gui/test_settings_page.py`，追加：

```python
def test_settings_page_has_close_action_selector(qtbot):
    from csm_gui.config import AppConfig
    from csm_gui.pages.settings_page import SettingsPage
    cfg = AppConfig()
    saved = []
    page = SettingsPage(config=cfg, on_save=lambda c: saved.append(c))
    qtbot.addWidget(page)
    # 必须存在 close_action_combo 控件
    assert hasattr(page, "close_action_combo")


def test_settings_page_close_action_default_minimize(qtbot):
    from csm_gui.config import AppConfig
    from csm_gui.pages.settings_page import SettingsPage
    cfg = AppConfig(close_action="minimize_to_tray")
    page = SettingsPage(config=cfg, on_save=lambda c: None)
    qtbot.addWidget(page)
    # 当前选中应为 "最小化到托盘"
    assert page.close_action_combo.currentData() == "minimize_to_tray"


def test_settings_page_close_action_save_quit(qtbot):
    from csm_gui.config import AppConfig
    from csm_gui.pages.settings_page import SettingsPage
    cfg = AppConfig()
    saved: list[AppConfig] = []
    page = SettingsPage(config=cfg, on_save=lambda c: saved.append(c))
    qtbot.addWidget(page)
    # 找到下拉项的 index
    idx = page.close_action_combo.findData("quit")
    assert idx >= 0
    page.close_action_combo.setCurrentIndex(idx)
    page._on_save()  # 触发保存（实际方法名可能不同——按 settings_page 里现有命名）
    assert saved
    assert saved[-1].close_action == "quit"
```

注意：`_on_save` 的实际方法名要看 settings_page.py 里现有的保存按钮处理函数；如果是 `_save_clicked` 或类似的名字，**改测试调对应方法**。

- [ ] **Step 3: 跑测试确认失败**

```bash
pytest tests/gui/test_settings_page.py -k close_action -v
```

预期：`AttributeError: 'SettingsPage' object has no attribute 'close_action_combo'`。

- [ ] **Step 4: 实现 — 在 settings_page.py 添加 ComboBox**

在 `SettingsPage.__init__` 中找到一个合适的位置（推荐"通用设置"区块），追加：

```python
from qfluentwidgets import ComboBox  # 如果还没导入

# ...

# 关闭按钮行为
self.close_action_combo = ComboBox(self)
self.close_action_combo.addItem("最小化到托盘（推荐）", userData="minimize_to_tray")
self.close_action_combo.addItem("直接退出 CSM", userData="quit")
# 应用当前 cfg
idx = self.close_action_combo.findData(self._config.close_action)
self.close_action_combo.setCurrentIndex(max(0, idx))

# 把它放到布局里 —— 用现有的 form 行模式（参考其他配置项的添加方式）
# 例如：
#   row.addWidget(BodyLabel("关闭按钮行为"))
#   row.addWidget(self.close_action_combo)
```

并在保存逻辑（`_on_save` / `_save_clicked` / 类似方法）里追加：

```python
new_cfg = self._config.model_copy(update={
    # ... 现有字段
    "close_action": self.close_action_combo.currentData(),
})
```

如果 SettingsPage 是一行一行收集字段的模式，照猫画虎；如果它通过 model_dump + 局部 update 重建 cfg，加一行更新即可。

**如果系统托盘不可用（headless / 远程桌面），把控件置灰**：

```python
from PyQt6.QtWidgets import QSystemTrayIcon
if not QSystemTrayIcon.isSystemTrayAvailable():
    self.close_action_combo.setEnabled(False)
    self.close_action_combo.setToolTip("当前系统不支持托盘，已强制使用 \"直接退出\"")
    # 同时强制选中 quit
    idx = self.close_action_combo.findData("quit")
    self.close_action_combo.setCurrentIndex(idx)
```

- [ ] **Step 5: 跑测试确认通过**

```bash
pytest tests/gui/test_settings_page.py -k close_action -v
```

预期：3 PASS。

- [ ] **Step 6: 跑全部 settings_page 测试避免回归**

```bash
pytest tests/gui/test_settings_page.py -v
```

预期：原有测试全部 PASS。

- [ ] **Step 7: 提交**

```bash
git add csm_gui/pages/settings_page.py tests/gui/test_settings_page.py
git commit -m "feat(settings): close-button behavior selector"
```

---

## Task 7: MainWindow 拦截 closeEvent + 接托盘信号

**Files:**
- Modify: `csm_gui/main_window.py`
- Modify: `tests/gui/test_main_window.py`

- [ ] **Step 1: 写失败测试 — closeEvent 在 minimize_to_tray 模式下应隐藏窗口而非关闭**

在 `tests/gui/test_main_window.py` 追加：

```python
from PyQt6.QtCore import QEvent
from PyQt6.QtGui import QCloseEvent


def _make_close_event() -> QCloseEvent:
    return QCloseEvent()


def test_close_event_minimize_to_tray_hides_window(qtbot, tmp_path):
    """close_action='minimize_to_tray' should hide() the window instead of closing."""
    from csm_gui.main_window import MainWindow
    win = MainWindow(config_dir=tmp_path)
    qtbot.addWidget(win)
    win.config.close_action = "minimize_to_tray"
    win.show()
    qtbot.waitExposed(win)
    assert win.isVisible()

    ev = _make_close_event()
    win.closeEvent(ev)
    qtbot.wait(100)
    assert not win.isVisible()  # 已隐藏
    assert not ev.isAccepted()  # 关闭被拦截


def test_close_event_quit_mode_accepts(qtbot, tmp_path):
    from csm_gui.main_window import MainWindow
    win = MainWindow(config_dir=tmp_path)
    qtbot.addWidget(win)
    win.config.close_action = "quit"
    ev = _make_close_event()
    win.closeEvent(ev)
    assert ev.isAccepted()


def test_show_main_window_brings_to_front(qtbot, tmp_path):
    from csm_gui.main_window import MainWindow
    win = MainWindow(config_dir=tmp_path)
    qtbot.addWidget(win)
    win.hide()
    win._show_main_window()
    qtbot.wait(50)
    assert win.isVisible()


def test_tray_new_article_focuses_keyword_input(qtbot, tmp_path):
    """When tray menu emits new_article_requested, MainWindow switches to home + focuses keyword input."""
    from csm_gui.main_window import MainWindow
    win = MainWindow(config_dir=tmp_path)
    qtbot.addWidget(win)
    win.show()
    qtbot.waitExposed(win)

    win._on_tray_new_article()
    qtbot.wait(50)
    # current page should be home
    assert win.stackedWidget.currentWidget() is win.home
    # focus on keyword input — pytest-qt may not reliably set focus headless,
    # so we just verify the method ran and switched page.
```

- [ ] **Step 2: 跑测试确认失败**

```bash
pytest tests/gui/test_main_window.py -k "close_event or tray or show_main" -v
```

预期：`AttributeError` —— `closeEvent` 没拦截、`_show_main_window` 不存在。

- [ ] **Step 3: 实现 — 在 MainWindow 加 closeEvent + _show_main_window + 托盘信号槽**

修改 `csm_gui/main_window.py`：

a) **import 段**追加：

```python
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QCloseEvent
from PyQt6.QtWidgets import QApplication
from .tray.manager import TrayManager
```

b) **`__init__` 末尾**（在 `self.switchTo(self.home)` **之后**）追加：

```python
# Tray manager — owned by the window. app.py's start sequence shows it.
# (Visible/invisible is controlled later by MainWindow.start_tray_lifecycle.)
self.tray = TrayManager(self)
self.tray.show_requested.connect(self._show_main_window)
self.tray.new_article_requested.connect(self._on_tray_new_article)
self.tray.new_template_requested.connect(self._on_tray_new_template)
self.tray.new_skill_requested.connect(self._on_tray_new_skill)
self.tray.settings_requested.connect(self._on_tray_settings)
self.tray.quit_requested.connect(self._on_tray_quit)
if self.tray.is_available() and self.config.close_action == "minimize_to_tray":
    self.tray.show()
```

c) **加 closeEvent override**（放在 _on_settings_save 附近）：

```python
def closeEvent(self, event: QCloseEvent) -> None:
    """Intercept × per AppConfig.close_action."""
    if self.config.close_action == "minimize_to_tray" and self.tray.is_available():
        event.ignore()
        self.hide()
        if not self.config.tray_first_minimize_shown:
            self.tray.show_first_minimize_bubble()
            self.config.tray_first_minimize_shown = True
            self.save_config()
        return
    # fall through: normal quit
    event.accept()
    super().closeEvent(event)
```

d) **加托盘动作槽函数**（紧贴 closeEvent 之后）：

```python
def _show_main_window(self) -> None:
    """Restore the main window from tray. Idempotent."""
    self.show()
    self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized)
    self.raise_()
    self.activateWindow()

def _on_tray_new_article(self) -> None:
    self._show_main_window()
    self.switchTo(self.home)
    try:
        self.home.keyword_input.setFocus()
    except AttributeError:
        pass

def _on_tray_new_template(self) -> None:
    self._show_main_window()
    self.switchTo(self.template_manager)
    # Trigger the existing "新建模板" button's handler.
    try:
        self.template_manager.list_panel._on_new()
    except AttributeError:
        pass

def _on_tray_new_skill(self) -> None:
    self._show_main_window()
    self.switchTo(self.skills)
    try:
        self.skills.new_btn.click()
    except AttributeError:
        pass

def _on_tray_settings(self) -> None:
    self._show_main_window()
    self.switchTo(self.settings)

def _on_tray_quit(self) -> None:
    """Bypass closeEvent — true exit."""
    self.tray.hide()
    QApplication.instance().quit()
```

e) **响应设置页改动** — 在现有 `_on_settings_save` 末尾追加：

```python
def _on_settings_save(self, new_cfg: AppConfig) -> None:
    # ... 既有 propagation 不变 ...
    # 同步托盘可见性（用户可能切换了 close_action）
    if self.tray.is_available():
        if new_cfg.close_action == "minimize_to_tray":
            self.tray.show()
        else:
            self.tray.hide()
```

- [ ] **Step 4: 跑测试确认通过**

```bash
pytest tests/gui/test_main_window.py -k "close_event or tray or show_main" -v
```

预期：4 PASS。

- [ ] **Step 5: 跑全部 main_window 测试避免回归**

```bash
pytest tests/gui/test_main_window.py -v
```

预期：旧测试全部 PASS。

- [ ] **Step 6: 提交**

```bash
git add csm_gui/main_window.py tests/gui/test_main_window.py
git commit -m "feat(window): intercept closeEvent and wire tray actions"
```

---

## Task 8: app.py 集成 — 单实例 + 托盘 lifecycle

**Files:**
- Modify: `csm_gui/app.py`

- [ ] **Step 1: 看现有 app.py（确认基线）**

文件目前结构：

```python
def run() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    apply_theme()
    win = MainWindow(config_dir=_default_config_dir())
    win.show()
    return app.exec()
```

- [ ] **Step 2: 改造 run() 加单实例锁 + setQuitOnLastWindowClosed(False)**

修改 `csm_gui/app.py`：

```python
"""Create a configured QApplication and return it plus the main window."""
from __future__ import annotations
import sys
from pathlib import Path
from PyQt6.QtCore import QStandardPaths
from PyQt6.QtWidgets import QApplication
from .theme import apply_theme
from .main_window import MainWindow
from .tray.single_instance import SingleInstance


def _default_config_dir() -> Path:
    loc = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppConfigLocation)
    d = Path(loc) / "CSM" if loc else Path.home() / ".csm"
    d.mkdir(parents=True, exist_ok=True)
    return d


def run() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    # Critical: prevent Qt from quitting when MainWindow is hidden to tray.
    # Without this, hide() == quit() because no other top-level windows exist.
    app.setQuitOnLastWindowClosed(False)

    apply_theme()

    # Single-instance lock. If another CSM is already running, ask it to show
    # itself and exit cleanly here.
    instance = SingleInstance("csm-app-singleton")
    if not instance.try_acquire():
        instance.send_show()
        return 0

    win = MainWindow(config_dir=_default_config_dir())
    # Route the singleton's "show" message to the window's restore method.
    instance.show_requested.connect(win._show_main_window)

    win.show()
    return app.exec()
```

- [ ] **Step 3: 集成测试 — 校验 setQuitOnLastWindowClosed 已生效**

打开 `tests/gui/test_main_window.py` 追加：

```python
def test_app_does_not_quit_when_hidden_to_tray(qtbot, tmp_path, qapp):
    """Once setQuitOnLastWindowClosed(False) is set, hiding the window must not exit the app."""
    from csm_gui.main_window import MainWindow
    qapp.setQuitOnLastWindowClosed(False)
    win = MainWindow(config_dir=tmp_path)
    qtbot.addWidget(win)
    win.show()
    qtbot.waitExposed(win)
    win.hide()
    qtbot.wait(100)
    # If qapp had quit, this assert would never run — the test runner would die.
    assert not win.isVisible()
    # restore for next test
    qapp.setQuitOnLastWindowClosed(True)
```

- [ ] **Step 4: 跑测试**

```bash
pytest tests/gui/test_main_window.py -v
```

预期：通过。

- [ ] **Step 5: 提交**

```bash
git add csm_gui/app.py tests/gui/test_main_window.py
git commit -m "feat(app): single-instance + tray lifecycle in run()"
```

---

## Task 9: 手动 PyInstaller 冒烟（不进 CI）

**Files:**
- 验证 `CSM.spec`（不一定要修改，但要确认 csm_gui/tray 被打入）

- [ ] **Step 1: 检查 CSM.spec 的 hiddenimports / pathex**

```bash
cat CSM.spec | grep -E "hiddenimports|pathex|csm_gui"
```

确认 `csm_gui` 整包通过 `Analysis(...)` 的 module 自动发现机制纳入。`csm_gui.tray` 是新子包，正常情况下 PyInstaller 会自动跟进。如果 spec 用了显式 `hiddenimports` 列表，**追加** `'csm_gui.tray', 'csm_gui.tray.manager', 'csm_gui.tray.single_instance', 'csm_gui.tray.icon', 'csm_gui.tray.menu'`。

- [ ] **Step 2: PyInstaller 打包**

```bash
pyinstaller CSM.spec
```

确认 `dist/CSM/CSM.exe` 生成。如果出错，看 console 报缺什么模块，按报错补 hiddenimports。

- [ ] **Step 3: 启动 dist/CSM/CSM.exe，做以下 5 项手动验证**

1. **托盘图标显示**：启动后右下角通知区出现 CSM 图标，鼠标悬停 tooltip 显示 "CSM — Content Studio"。
2. **关闭最小化**：点窗口右上角 ×，窗口消失但任务管理器中 CSM.exe 进程仍在；首次最小化应弹气泡提示。
3. **托盘恢复**：双击托盘图标，主窗回来；右键菜单 6 项齐全。
4. **托盘动作**：右键 → 新建文章 → 主窗显示 + Home 页 + 关键词输入框聚焦。其他 3 个新建/设置同理。
5. **托盘退出**：右键 → 退出 CSM → 进程结束。
6. **单实例**：再次双击桌面快捷方式 → 不应启新进程；已有窗口被前置（被托盘恢复）。
7. **设置切换 quit 模式**：进入设置 → 关闭按钮行为改为"直接退出" → 保存 → 点 × → 进程结束。

- [ ] **Step 4: 异常路径**

8. **无系统托盘环境**（不易模拟，**可跳过此条**，但代码已防御）：理论上 `is_available()` 返回 False 时托盘不显示，close_action 强制退出。

- [ ] **Step 5: 提交（如有 spec 改动）**

```bash
git add CSM.spec
git commit -m "build(spec): explicit hidden imports for csm_gui.tray (if needed)"
```

如果 spec 没改，跳过提交。

---

## Task 10: CHANGELOG 与文档（可选）

**Files:**
- Modify: `README.md`（如有"功能列表"段）

- [ ] **Step 1: README 加一行**

如果 README.md 有"主要功能"或类似段落，追加：

```markdown
- 关闭按钮默认最小化到系统托盘（可在设置中切换）
- 托盘菜单快速创建文章 / 模板 / Skill，进入设置
- 单实例锁：避免重复启动多份 CSM 进程导致配置冲突
```

- [ ] **Step 2: 提交**

```bash
git add README.md
git commit -m "docs(readme): mention tray + single-instance behavior"
```

---

## Self-Review Checklist

完成所有 Task 后：

- [ ] 全量测试 `pytest tests/` 全部 PASS
- [ ] PyInstaller 打包成功，dist/CSM/CSM.exe 能启动
- [ ] 手动 7 项验证全部通过
- [ ] 旧用户的 settings.json（无 close_action 字段）启动应用不报错，行为为默认值
- [ ] 关闭后任务管理器仍能看到 CSM.exe 进程
- [ ] git log 中应有 8–10 个独立 commit（每 Task 至少 1 个）

---

## 风险点 / 易错处

1. **`app.setQuitOnLastWindowClosed(False)` 必须在 MainWindow 创建前设置**——否则一旦窗口隐藏，QApplication 立即 quit，托盘形同虚设。
2. **托盘图标不显示**：CI 测试要 `if not QSystemTrayIcon.isSystemTrayAvailable(): pytest.skip(...)`，否则 headless 环境会失败。
3. **QLocalServer 命名冲突**：`csm-app-singleton` 在多用户机器上独立（Win 是 logon-session-namespace），不需要附加 username。
4. **closeEvent 在 quit 模式仍要 `super().closeEvent(event)`**——FluentWindow 父类可能有清理逻辑。
5. **托盘菜单的 "新建模板/Skill" 调用 `_on_new()` 是访问私有方法**——若现有面板将来改名，托盘会失败但有 try/except 兜底。**接受这个耦合**（YAGNI），未来如果改名再公开 API。
