# 百度验证码 UX 优化设计

> 状态：设计已确认（2026-06-15），待写实现计划。方案 A（有头+屏外常驻）。

## 背景与问题
百度排名监控用 patchright 真 Chromium 采集。触发图形验证码（百度安全验证 / 滑块）时：
- 浏览器默认**无头模式**（`baidu_keyword.py` adapter `_headless_default = True`），根本没有可见窗口；
- 即使有头也停在屏外（`--window-position=-32000,-32000`）；
- 用户只看到任务栏闪烁（弱提醒），不知道要操作，采集卡住直到 300s 超时。

现状其实**已有「软着陆」机制** `_try_human_solve()`（detect_risk → surface_window → 轮询等解），但被三点削弱：
1. 无头模式下 `surface_window` 移的是不存在的窗口；
2. `_notify` 是 log-only（`lifespan.py`），没有真正的系统通知；
3. `bring_to_front()` 在 Windows 抢不到前台焦点（系统限制后台程序抢焦点），只剩任务栏闪。

## 目标
百度触发验证码时：浏览器自动弹到**屏幕中央**可操作 + **三管齐下强通知**确保用户注意到 → 用户解完自动继续采集。

## 方案（A：有头+屏外常驻）

### 1. 浏览器常驻模式：无头 → 有头+屏外
- 百度 `headless_default` 改 `False`；屏外参数（`offscreen_args`：`-32000,-32000` + 关 occlusion）在有头时已自动生效。
- 平时窗口在屏外不打扰；验证码时移入屏。
- 副作用（正向）：有头真窗口反爬指纹更干净，可能降低验证码触发频率。
- 资源：百度串行单实例（concurrency=1），多一个屏外 Chromium 进程，可控。
- 注意：兼容 bundled Chromium（headless→headed offscreen）与 native Chrome（已 headed）两种 profile 模式。

### 2. 验证码窗口呈现（增强 `window_util.surface_window`）
- 移到**屏幕中央**（当前硬编码 `(80,80,1100,800)` → 居中坐标）。
- 尽力置顶 + 抢焦点：`bring_to_front()` + OS 级尝试（Windows `SetWindowPos` HWND_TOPMOST / `SetForegroundWindow`，best-effort、失败不致命）。
- 用户解完 → `hide_window` 移回屏外 + 取消置顶。
- 因 Windows 抢焦点限制不可靠，**强通知（§3）作为引导兜底**：即使浏览器没自动到最前，用户也能从通知/任务栏点开它。

### 3. 强通知 · 三管齐下（通用层，所有 `needs_captcha` 受益）
验证码检测时，除 surface_window 外同时：
- **系统桌面通知**：从 log-only 接到真正的 Tauri 通知（路径：sidecar 已发 `needs_captcha` SSE → 前端订阅 → 前端调 Tauri notification plugin；确认/补全前端对 `needs_captcha` 的系统通知处理）。文案「百度需要人工验证，浏览器已弹出，请完成验证」。
- **app 内醒目提醒**：前端收 `needs_captcha` SSE → 顶部/中央 banner 或 modal（非 toast），引导「浏览器已弹出，请去解验证码」。
- **任务栏闪烁 + app 抢焦点**：新增 Tauri command `request_user_attention`（Rust 侧 `Window::request_user_attention`），前端收 `needs_captcha` 时调用，让 CSM 图标在任务栏闪 + 尝试前置 app 窗口。

### 4. 解验证流程（复用现有）
- 轮询 300s（`poll_interval` 1s）检测验证页消失（URL 离开风险域 + DOM 验证元素消失）→ 自动重试该关键词。
- 超时 → `RiskControlException(progress=kw_idx)` → 任务暂停、记断点，可 `resume_from` 续跑（现有机制）。

### 5. 范围
- **有头+屏外 + 窗口居中**：仅百度（用户报的、验证码最频繁；其它平台浏览器机制不同，知乎走 curl_cffi 快通道，风险高，不在本次）。
- **通知三层**：通用——任何平台发 `needs_captcha` SSE 都触发系统通知 + app 提醒 + 任务栏闪。

## 架构 / 涉及文件
| 层 | 文件 | 改动 |
|---|---|---|
| 采集 | `csm_core/monitor/platforms/baidu_keyword.py` | `_headless_default` → False；确认 `_try_human_solve` 调 surface_window |
| 窗口 | `csm_core/browser_infra/window_util.py` | `surface_window` 居中坐标 + best-effort 置顶/抢焦点 |
| sidecar | `sidecar/csm_sidecar/lifespan.py` | `_notify` / 通知通道（按未知 1 结论决定是否真接） |
| 前端 | `frontend/src/...`（SSE handler + 新 banner/modal 组件） | `needs_captcha` → 系统通知 + app 提醒 + 调 request_user_attention |
| Tauri | `frontend/src-tauri/src/` | 新 command `request_user_attention` |

## 数据流
```
百度采集 → detect_risk 命中验证码
  → surface_window(居中 + 尽力置顶)
  → 发 needs_captcha SSE（已有）
       → 前端：系统通知 + app banner/modal + request_user_attention(任务栏闪)
  → 用户切到浏览器解验证码
  → 轮询检测验证页消失 → hide_window(回屏外) → 继续采集该关键词
  （超时 300s → RiskControlException → 暂停可 resume）
```

## 错误处理
- 通知任一环失败 best-effort（不致命，日志记录）。
- 置顶/抢焦点失败 → 通知引导兜底。
- 超时 → 现有 resume 机制。

## 测试
- 单元：`window_util` 居中坐标计算（给定屏幕尺寸 → 窗口居中 bounds）；detect_risk 现有测试不动。
- 真机（不可自动化）：百度跑到验证码 → 确认浏览器居中弹出 + 三通知触发 + 解完自动继续。QA 清单交用户。

## 关键实现未知（writing-plans / 实现时细化）
1. **系统通知通道**：确认前端是否已处理 `needs_captcha` SSE 的系统通知（`useSystemNotify`），还是要补；`_notify`（csm_core/sidecar）是否需要真接通道，还是系统通知全走「前端 SSE → Tauri notification plugin」路径（很可能后者，`_notify` log-only 可保留）。
2. **request_user_attention**：Tauri 2 `Window::request_user_attention(Some(UserAttentionType::Critical))` Rust command + 前端 invoke。
3. **OS 级置顶**：Windows `SetWindowPos`/`SetForegroundWindow` 经 pywin32/ctypes，非 Windows 降级跳过。
4. **居中坐标**：屏幕尺寸获取方式（CDP `Browser.getWindowBounds` / 固定假设居中 / 多屏处理）。
