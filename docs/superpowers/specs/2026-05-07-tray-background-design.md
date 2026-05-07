# 系统托盘后台挂载

**Date:** 2026-05-07
**Status:** Approved, awaiting implementation plan

## 背景与动机

CSM 当前点击窗口右上角 × 直接退出进程，用户在创作过程中切到其他应用后，应用即被关闭。希望：

- 关闭按钮（×）默认最小化到 Windows 通知区（系统托盘），应用保留为后台运行；
- 通过托盘图标快速恢复主界面或新建文章 / 模板 / Skill；
- 关闭行为可在设置中切换为"直接退出"；
- 单实例锁：禁止用户重复双击启动多份 CSM 进程，避免 `recent_docs.json` / `settings.json` 写入竞争。

## 范围

| 项 | 在范围内 | 说明 |
|---|---|---|
| Windows 系统托盘（通知区） | ✅ | QSystemTrayIcon |
| 关闭按钮拦截行为可配置 | ✅ | "最小化到托盘" / "直接退出" 二选一 |
| 托盘菜单：显示主界面 / 新建文章 / 新建模板 / 新建 Skill / 设置 / 退出 CSM | ✅ | |
| 单实例锁 | ✅ | QLocalServer/QLocalSocket |
| 开机自启动 | ❌ | 不在本次范围 |
| Linux/macOS 兼容 | ❌ | CSM 仅 Win 分发 |

## 用户行为

### 关闭按钮（×）的两种模式

`AppConfig.close_action` 新字段（默认 `"minimize_to_tray"`）：
- `"minimize_to_tray"` → 拦截 closeEvent，主窗隐藏，托盘图标常驻
- `"quit"` → 走原退出流程，主窗 close + QApplication.quit

### 托盘图标行为

- **左键单击**：恢复主窗（等同菜单"显示主界面"）
- **左键双击**：同上（避免用户找不到入口）
- **右键单击**：弹出菜单
- **图标 tooltip**："CSM — Content Studio"

### 托盘菜单项

| 标签 | 行为 |
|---|---|
| 显示主界面 | 主窗 show + raise + activateWindow |
| 新建文章 | 主窗 show + 切到 HomePage 并光标聚焦关键词输入框 |
| 新建模板 | 主窗 show + 切到 TemplateManagerPage（保持现 sidebar 行为）|
| 新建 Skill | 主窗 show + 切到 SkillsPage 并触发"新建 Skill"向导（与 SkillsPage 现按钮等同）|
| 设置 | 主窗 show + 切到 SettingsPage |
| —— | 分隔符 |
| 退出 CSM | QApplication.quit（绕过 closeEvent 拦截） |

### 单实例语义

- 第一个 CSM 启动时绑定 `QLocalServer("CSM-singleton")`
- 第二个 CSM 启动时连接到该 server，发送 `"show"` 命令后**立即退出**
- 第一个进程收到 `"show"` 后调用"显示主界面"逻辑
- 边界：如果 server 文件残留（崩溃后），尝试连接失败回落到正常启动并清理残留

## 架构

### 文件清单

```
新增：
  csm_gui/tray/
  ├── __init__.py
  ├── icon.py              # 加载托盘图标 QIcon（复用 csm_gui/assets/csm-logo.png）
  ├── menu.py              # 构造右键菜单 QMenu，按钮 → signal
  ├── manager.py           # TrayManager：组合 QSystemTrayIcon + QMenu
  └── single_instance.py   # SingleInstance：QLocalServer/Socket 封装

修改：
  csm_gui/app.py            # 启动时挂 SingleInstance + TrayManager
  csm_gui/main_window.py    # closeEvent 拦截 + 复用 _on_home_navigate
  csm_gui/config.py         # AppConfig.close_action 新字段
  csm_gui/pages/settings_page.py  # 新增 "关闭按钮行为" 选择
```

### TrayManager 职责

- 创建 QSystemTrayIcon、注入图标、tooltip、关联 QMenu
- 暴露信号：`request_show`、`request_new_article`、`request_new_template`、`request_new_skill`、`request_settings`、`request_quit`
- 由 MainWindow 接收信号、调用相应 `switchTo` / `_on_home_navigate("...")`

### SingleInstance 职责

- 在 `app.py` 中 `QApplication` 创建后立即检测：
  ```
  if SingleInstance.try_send_show():
      sys.exit(0)
  SingleInstance.start_server()  # 失败则继续（不阻塞启动）
  ```
- Server 收到消息时发射 Qt signal，MainWindow 连接到该 signal → 调用 `_show_main_window()`

## 数据模型变更

```python
# csm_gui/config.py
@dataclass
class AppConfig:
    ...
    close_action: str = "minimize_to_tray"      # "minimize_to_tray" | "quit"
    tray_first_minimize_shown: bool = False     # 首次最小化气泡只显示一次
```

`load_config` 应对老配置文件无此字段时回退到默认值（向后兼容）。

## UI 改动

### 设置页新增项（在"通用"区块）

```
关闭按钮行为
  ◉ 最小化到托盘（推荐）
  ○ 直接退出 CSM
```

### 首次最小化的提示

第一次 `closeEvent` 触发最小化时，调用 `tray_icon.showMessage(...)` 显示气泡：
"CSM 已最小化到通知区，可在右下角找到图标。可在设置中修改此行为。"

只在第一次显示，标记位 `AppConfig.tray_first_minimize_shown = True` 持久化。

## 错误处理

| 场景 | 行为 |
|---|---|
| QSystemTrayIcon.isSystemTrayAvailable() 返回 False | 不创建托盘；`close_action` 强制为 `"quit"`；设置页该项变灰 + 提示"系统不支持托盘" |
| 单实例 server 已存在但连接失败（陈旧 socket）| 删除残留 + 重新创建 server；不阻塞启动 |
| 第二个实例连接 server 后等待响应超时（>2s）| 直接退出（视作首实例已收到，避免僵死等待）|
| 用户直接 Alt+F4 | 走 closeEvent，按 close_action 配置执行 |
| 用户在任务管理器结束进程 | 不可拦截，单实例 socket 文件残留下次启动自动清理 |

## 测试策略

### 单元测试（pytest）

- `tray/icon.py`：图标资源存在 / 缺失时的回退
- `tray/menu.py`：菜单项点击触发对应 signal（用 `pytest-qt` 的 `qtbot.mouseClick`）
- `tray/single_instance.py`：第一个 server 创建成功；第二个 try_send_show 返回 True；失败路径不抛

### 集成测试（pytest-qt）

- `MainWindow.closeEvent` 在 `close_action="minimize_to_tray"` 时调用 `hide()` 而非 `close()`
- `TrayManager.request_new_article` 信号触发后窗口可见且 HomePage 为当前页
- 单实例：spawn 第二个进程模拟，验证第一个进程收到 show 信号

### 手动验证（CSM.spec 打包后）

- 关闭后任务管理器仍能看到 CSM 进程
- 设置切到"直接退出"后再点 ×，进程正常结束
- 关闭后双击桌面快捷方式 → 主窗复原而非启新进程

## Out of Scope

- 开机自启动（注册表 / Win+R `shell:startup` 写入）— 单独立项
- 托盘图标动画（生成中转圈圈）— 后续可考虑
- 全局快捷键（Ctrl+Alt+Q 等）唤起主窗 — 后续可考虑
- 托盘图标右键的"近期文章"快速跳转 — 后续可考虑

## 实施顺序建议

1. SingleInstance 模块 + 单测
2. AppConfig.close_action 字段 + 设置页 UI
3. TrayManager 模块 + 菜单 + 单测
4. MainWindow 集成（closeEvent + 托盘信号接线）
5. 首次最小化气泡提示
6. 手动 PyInstaller 打包冒烟（核心：托盘图标在分发版能正常显示）
