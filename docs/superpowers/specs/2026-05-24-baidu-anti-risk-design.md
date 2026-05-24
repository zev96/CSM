# 百度抓取反风控：直接挂载日常 Chrome profile（方案 D）

**Date:** 2026-05-24
**Status:** Draft (brainstorm 完成，待 review)
**Owner:** zev96

## Background

### 问题陈述

CSM 百度关键词排名监控当前在用户日常使用中遇到强风控：跑 3-5 个关键词后就跳验证码，断点续抓机制虽然能保住进度，但用户体验差且无法支撑"一天 100 词流畅监控"的目标。

### 当前架构（已实现的反爬手段）

CSM 当前 SERP 抓取流程（[csm_core/monitor/platforms/baidu_keyword.py:372-373](csm_core/monitor/platforms/baidu_keyword.py)）：

```python
serp_url = "https://www.baidu.com/s?wd=" + quote(keyword)
return page.goto(serp_url, wait_until="domcontentloaded", timeout=30000)
```

- 已经在用 Patchright stealth fork（不是 requests）
- 持久 BrowserContext，cookie 跨任务累积到 `<config_dir>/baidu_browser_profile/`
- UA 轮换（4 条 Chrome 119-122）、TLS chrome120 指纹、SERP pacing 5-10s jitter、串行 concurrency=1
- 风控检测 5 层：URL / HTTP / DOM / 文案 / 登录态
- 命中风控 → raise RiskControlException → 写断点 → 等用户在 UI 点恢复

### 此前已实测且回滚的方案

git log 显示 2025 年实现过"模拟真人"方案并回滚（[baidu_keyword.py:366-371](csm_core/monitor/platforms/baidu_keyword.py)）：

```
f469ddb  add _navigate_to_serp + _random_dwell_ms helpers          ← 引入"三段式"
9950f82  pass force=True to fill/click in _navigate_to_serp        ← 调试填框
34c224c  submit via keyboard.press(Enter) instead of click input#su ← 调试提交
ff42662  longer dwell + simulated mouse movement for stealth       ← 加"人类动作"
ea98475  refactor: simplify _navigate_to_serp to direct page.goto  ← 全部回滚
```

回滚注释明确：**"三段式 home/fill/Enter 的时间 pattern 反而是 bot 信号。带登录态（BDUSS）的直接 goto 看起来像真实用户从书签或外链进 SERP，是 baidu organic 流量的主要形态。"**

结论：动作模拟不是有效路径。真正的瓶颈在 profile 真实度 + IP 速率阈值。

### 用户硬需求

1. 一天监控 ~100 个关键词
2. 流畅跑、不要频繁弹验证码
3. 可以接受跑监控时不使用浏览器
4. 偏好像影刀那样"用真实浏览器跑"
5. 在岗时间跑，能响应通知

### 为什么不走 CDP attach（影刀那套）

影刀通过 CDP 附着到用户日常 Chrome，关键代价：

- 用户 Chrome 启动必须加 `--remote-debugging-port=9222`，要改快捷方式
- Chrome 顶部挂"使用不受支持的命令行标志"黄色警告条
- **Patchright stealth patch 是 launch 时注入的，CDP attach 模式下 stealth 大部分失效** —— 用真 profile 换来 stealth 失效，得不偿失
- 隐私边界：CSM 进程能读 Chrome 所有 cookie

用户接受"跑监控时不用浏览器"后，CDP attach 的唯一优势（不关 Chrome）就没必要了，可以走更干净的 `launch_persistent_context + 真 user_data_dir` 路径。

## Goals

- 100 词/天能流畅跑完，单轮耗时目标 **60-90 分钟**（基于"文章 pacing 降到 1-2s + SERP pacing 不变"）
- 单轮触发风控次数稳态 ≤ 2 次
- 偶发风控时浏览器已在用户面前，解题流程 ≤ 30 秒
- 用户首次启用 ≤ 10 秒（不养号、不复制文件，配置面板自动探测）
- 不改用户日常 Chrome 启动方式
- 关键事件（等关 Chrome / 完成 / 需验证）通过系统通知推送，CSM 在后台也能收到
- 不破坏现有用户的零感知升级（`baidu_use_native_chrome=False` 默认行为不变）

## Non-goals

- ❌ CDP attach 模式
- ❌ 多账号 cookie 池
- ❌ IP 代理池
- ❌ 复制 profile 副本到 CSM 专用目录
- ❌ 调用影刀 / 任何外部 RPA 进程
- ❌ 删除当前自建 `baidu_browser_profile`（保留作 fallback）

## 架构

### 改动点 1：配置层 — `csm_core/config.py`

新增 4 个字段：

```python
# 总开关。False = 沿用现有自建 profile 模式（向后兼容）
baidu_use_native_chrome: bool = False

# 用户 Chrome 安装路径。None = 启用时自动探测
baidu_chrome_executable_path: str | None = None

# 用户 Chrome User Data 目录。None = 启用时自动探测
baidu_chrome_user_data_dir: str | None = None

# 多 profile 用户选哪个。"Default" / "Profile 1" / "Profile 2"...
baidu_chrome_profile_name: str = "Default"
```

### 改动点 2：浏览器层 — `csm_core/monitor/drivers/baidu_browser.py`

`baidu_browser_session()` 增加 native mode 分支：

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
    ensure_browsers_path()

    if use_native_chrome:
        # native mode：用户日常 Chrome.exe + 日常 user_data_dir
        # 注意：headless 入参在 native mode 下被忽略，Chrome stable 不支持 headless
        # persistent context（启动会失败）。固定 headless=False、窗口可见。
        if headless:
            logger.debug("native mode 忽略 headless=True（Chrome stable 不支持）")
        target_dir = Path(user_data_dir)  # 必须是用户 Chrome 的 User Data 目录
        launch_kwargs = dict(
            user_data_dir=str(target_dir),
            headless=False,                          # 强制 False
            executable_path=chrome_executable_path,  # 显式指定 Chrome.exe
            channel="chrome",                        # 让 Patchright 走 Chrome 而非自带 Chromium
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                f"--profile-directory={chrome_profile_name}",
                # 不加 --blink-settings=imagesEnabled=false（日常 Chrome 显示图片是常态）
            ],
            viewport={"width": 1366, "height": 768},
        )
    else:
        # 现有自建 profile 模式（不变，向后兼容）
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

    pw = _sync_playwright().start()
    try:
        context = pw.chromium.launch_persistent_context(**launch_kwargs)
        page = context.pages[0] if context.pages else context.new_page()
        _log_profile_health(context, target_dir)
        yield BaiduBrowserSession(page=page, context=context, pw=pw)
    finally:
        # LIFO 关闭
        ...
```

### 改动点 3：预检层（新文件）— `csm_core/monitor/drivers/chrome_preflight.py`

```python
"""跑 native mode 前的 Chrome 进程状态检查。

策略：发系统通知请求关闭 Chrome → 每 1s 轮询一次 → 用户关掉就立刻返回 → 超时 raise。
"""
import time
import psutil
import logging
from csm_sidecar.notifications import notify  # Tauri 通知封装

logger = logging.getLogger(__name__)

class ChromeStillRunningError(RuntimeError):
    pass

def is_chrome_running() -> bool:
    """检测系统是否有 chrome.exe 进程在跑。"""
    for proc in psutil.process_iter(["name"]):
        try:
            name = (proc.info.get("name") or "").lower()
            if name == "chrome.exe":
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return False

def wait_for_chrome_closed(timeout_s: int = 120, poll_interval_s: float = 1.0) -> None:
    """轮询等待 Chrome 关闭。第一次检测到在跑就发通知，关闭后立即返回。

    Raises:
        ChromeStillRunningError: 超时仍有 chrome.exe 进程。
    """
    if not is_chrome_running():
        return  # 已关闭，直接放行

    notify(
        title="CSM 百度监控",
        body="请关闭 Chrome 浏览器以开始监控（自动检测中）",
    )

    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        time.sleep(poll_interval_s)
        if not is_chrome_running():
            logger.info("chrome closed, proceeding with native mode")
            return

    raise ChromeStillRunningError(
        f"等待 Chrome 关闭超时（{timeout_s}s），请手动关闭后重试"
    )
```

### 改动点 4：主循环 hook — `csm_core/monitor/platforms/baidu_keyword.py`

`fetch()` 入口处理 native mode：

```python
def fetch(self, task, *, progress_cb=None, cancel_token=None, resume_from=0):
    cfg_global = config.get_config()  # 全局 config
    use_native = cfg_global.baidu_use_native_chrome

    if use_native:
        try:
            chrome_preflight.wait_for_chrome_closed(timeout_s=120)
        except ChromeStillRunningError as e:
            return MonitorResult(
                task_id=task.id or 0,
                checked_at=datetime.utcnow(),
                status="error",
                rank=-1,
                error_message=str(e),
            )

    # 把 native 参数透传给 baidu_browser_session
    session_kwargs = {}
    if use_native:
        session_kwargs.update(
            use_native_chrome=True,
            user_data_dir=Path(cfg_global.baidu_chrome_user_data_dir),
            chrome_executable_path=cfg_global.baidu_chrome_executable_path,
            chrome_profile_name=cfg_global.baidu_chrome_profile_name,
        )

    # native mode 传 headless=False（虽然 native 内部也会忽略，但显式传 False 更清楚）
    # 自建 profile 模式保持 headless=True 不变
    headless_arg = False if use_native else True

    try:
        with baidu_browser_session(headless=headless_arg, **session_kwargs) as session:
            # ... 现有 fetch 逻辑全部保留（_fetch_with_promotion / _fetch_once /
            # SERP 解析 / 文章抓取 / 风控检测 / 断点写入 / progress_cb 等）
            ...
    finally:
        if use_native:
            notify(
                title="CSM 百度监控",
                body=f"监控完成，已抓 {completed_count} 词，可以重新打开 Chrome",
            )
```

软着陆验证码（命中风控时不立即停、而是把窗口拉到中央等用户解）作为兜底也加上，详见下方"用户操作流程"。

## 用户操作流程

### 首次启用配置（一次性，~10 秒）

1. 打开 CSM → 设置 → 百度抓取
2. 打开"日常 Chrome profile 模式"开关
3. CSM 自动探测：
   - **executable**：查注册表 `HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe` → fallback 到 `C:\Program Files\Google\Chrome\Application\chrome.exe` 和 `C:\Program Files (x86)\Google\Chrome\Application\chrome.exe`
   - **user_data_dir**：默认 `%LOCALAPPDATA%\Google\Chrome\User Data`
   - **profile 列表**：扫该目录下 `Default` / `Profile 1` / `Profile 2`...，读各自 `Preferences` JSON 里的账号名展示给用户
4. UI 显示探测结果 + profile 下拉框，用户确认默认选项或手动选别的 → 保存
5. 探测失败 → UI 弹路径选择器让用户手动填

### 日常跑监控

1. 用户在 CSM 点"开始监控"
2. **Chrome 已关**：直接进入 fetch
3. **Chrome 在跑**：
   - 系统通知 "请关闭 Chrome 浏览器以开始监控（自动检测中）"
   - CSM 后台每 1s 轮询 `is_chrome_running()`
   - UI 进度条显示 "等待 Chrome 关闭（剩余 N 秒）"
   - 用户关掉 → CSM 在 1 秒内启动 fetch
   - 120 秒后仍未关 → 写错误日志、UI 显示超时
4. fetch 启动：Patchright 用 channel="chrome" 拉起真 Chrome.exe，加载日常 user_data_dir
5. 浏览器窗口可见（用户已确认偏好"看窗口跑"），用户可以实时看到 SERP 翻页
6. 100 词预计耗时（基于代码实测节奏，**不是承诺**）：
   - **默认 pacing 不动**：130-170 分钟（2-3 小时）
   - **文章 pacing 降到 1-2s**：60-90 分钟（1-1.5 小时）
   - **激进提速**：30-45 分钟（风控风险显著上升，不推荐起步用）
   - 触发风控时每次人工解题约 30 秒，预期 0-3 次/轮（详见下方"性能与风控预期"section）
7. fetch 完成：系统通知 "百度监控完成，已抓 N 词，可重新打开 Chrome"

### 偶发风控（每周可能 0-2 次）

1. 风控 5 层任一命中 → 不立即 raise RiskControlException
2. 调用 `_try_human_solve(session, page, keyword)`：
   - 浏览器窗口已经在用户面前（窗口可见模式）
   - 系统通知 "需要人工验证（关键词 #N）"
   - 等待 URL 离开 wappass / verify.baidu / safetycheck 域名（最多 300s）
   - URL 回到正常 SERP → 检测 DOM 中 `.passmod` / `#captcha-mask` 已消失 → return True
   - 主循环 retry 当前关键词、继续后续
3. 超时未解 / 用户明确取消 → fall back 到现有 `raise RiskControlException(progress=kw_idx)` 流程 → 写断点 → UI 显示恢复按钮

### 异常分支

- **用户没装 Chrome**：配置阶段 UI 阻止启用，提示"未检测到 Chrome 安装"+ 安装链接
- **Patchright 启动真 Chrome 失败**（版本不匹配 / 路径无效 / profile 锁等罕见情况）：
  - 实现层面用 try/except 包住 `launch_persistent_context`
  - 捕获到异常 → 写错误日志 → **本次 fetch 直接报错**（不自动 fallback，因为静默 fallback 会让用户以为自己在用日常 profile、其实用的自建空 profile）
  - UI 显示明确错误 + "切回自建 profile 模式" 按钮，让用户主动决定
- **用户 Chrome profile 加了 Windows Hello 解锁 password manager**：第一次启动可能弹系统凭据框，记 known limitation 到文档（不算 bug）
- **用户 100 词跑到一半 Chrome 被自己手动开了**：CSM 不监控这种情况（profile lock 已经由 OS 强制，Chrome 会自己开不起来或冲突；这种边角不优化）

## UI 设计

### 总原则

- **全局/机器级配置 vs 任务级配置**：native mode 的 4 个新字段都是机器级（一台电脑只有一组 Chrome 安装），不放进 per-task 的 [AddTaskModal.vue](frontend/src/components/monitor/AddTaskModal.vue)，而是新增"全局百度抓取设置"区
- **沿用现有组件**：FormField / FormInput / FormToggle（[frontend/src/components/ui/](frontend/src/components/ui/)）—— 不引新组件库
- **避免大改 IA**：只往现有页面增量加 section，不重排导航 / 不重做布局（参考已知约束：CSM UI 即将做 B+C 大改，本次只做最小必要 UI 补丁）

### 1. 新增"全局百度抓取设置"区

**位置**：**复用现有"设置"侧栏 / 模态，新增一个 tab**（用户决定）。具体落点：实施前 explore 一下当前"设置"页的结构（[frontend/src/stores/config.ts](frontend/src/stores/config.ts) 相关组件），找到现有 tab 容器、加一个"百度抓取"tab，把下方所有字段塞进去。

如果当前 Settings 用的是单页平铺（不是 tab 结构），就在合适的 section 之间插入新 section，标题"百度抓取设置"。

**字段布局**（自上而下）：

```
┌─ ⚙ 抓取模式（默认折叠）──────────────────────────────────┐
│                                                          │
│  [Toggle] 启用日常 Chrome profile 模式                    │
│           ──────────────                                  │
│           说明：跑监控时会借用你的真实 Chrome profile，    │
│           大幅降低风控触发。需要在跑监控时关闭 Chrome。    │
│                                                          │
│  ↓ 开关 ON 后展开：                                       │
│                                                          │
│  Chrome 可执行文件路径                                    │
│  [输入框：C:\Program Files\Google\Chrome\Application\chrome.exe]  [🔍 自动探测] [📁 选择文件]│
│                                                          │
│  Chrome User Data 目录                                    │
│  [输入框：%LOCALAPPDATA%\Google\Chrome\User Data]  [🔍 自动探测] [📁 选择目录]│
│                                                          │
│  使用 Profile                                             │
│  [下拉框：Default（fh13430366543@gmail.com）▾]            │
│   └ 选项例：                                              │
│     ├ Default（fh13430366543@gmail.com）                  │
│     ├ Profile 1（另一个邮箱）                              │
│     └ Profile 2（未登录）                                  │
│                                                          │
│  [🧪 测试启动]    [💾 保存]                                │
│                                                          │
│  ▸ 状态：✓ 配置可用 / ⚠ 路径无效 / ✗ Chrome 未安装         │
└──────────────────────────────────────────────────────────┘
```

**字段交互**：

- **启用 toggle**：默认 OFF（向后兼容）。OFF 时下面 4 个字段灰显折叠
- **自动探测**按钮：调后端新 API `POST /api/monitor/baidu/detect-chrome`，返回探测到的 executable + user_data_dir + profile 列表，前端 fill 字段
- **选择文件 / 选择目录**：调 Tauri `@tauri-apps/plugin-dialog` 的 `open()`，让用户挑路径
- **Profile 下拉框**：依赖 user_data_dir，user_data_dir 改变后自动重新加载（调 `POST /api/monitor/baidu/list-profiles`，返回 `{name, account_email}[]`）
- **测试启动**按钮：调 `POST /api/monitor/baidu/test-native`，后端尝试用配置参数启动一次 Chrome 再关掉，前端展示结果（最多 30s timeout）
- **未装 Chrome / 配置无效**时：保存按钮灰显 + 红字说明

### 2. 任务级配置（AddTaskModal）—— **不动**

[AddTaskModal.vue:430-493](frontend/src/components/monitor/AddTaskModal.vue) 的"百度高级设置"折叠区**完全不改**。
单任务的 `headless / exclude_domains / use_default_excludes` 等都保留。

### 3. 监控运行时 UI 扩展

在 [BaiduRankingPage.vue:1220-1251](frontend/src/components/monitor/history/BaiduRankingPage.vue) 现有进度条状态机里加 1 个新状态：

**新状态：`waiting_chrome_close`**

```
┌─ 任务 #X 正在等待 Chrome 关闭 ──────────────────┐
│                                                 │
│  ⏳ 请关闭 Chrome 浏览器以继续监控               │
│  剩余等待时间：1:47                              │
│                                                 │
│  [取消任务]                                      │
└─────────────────────────────────────────────────┘
```

- 后端 sidecar 通过 SSE 推 `{status: "waiting_chrome_close", remaining_s: 107}` → [monitorStatus.ts](frontend/src/stores/monitorStatus.ts) 接收 → BaiduRankingPage 显示
- 用户关 Chrome → 后端 1s 内检测到 → 状态变 `running` + 现有进度条接管
- 倒计时归零 → 状态变 `error` + 错误文案"Chrome 关闭超时"

**现有状态文案微调**（仅 native mode 启用时）：
- 完成 → "已抓 N 词，可以重新打开 Chrome"
- 验证码 → "需要人工解验证码（点击通知或浏览器窗口）"

### 4. 系统通知集成（新增依赖）

**新增依赖**：`@tauri-apps/plugin-notification` v2.x（package.json + src-tauri/Cargo.toml + src-tauri/capabilities）

**新增前端封装**：`frontend/src/composables/useSystemNotify.ts`

```typescript
import { sendNotification, isPermissionGranted, requestPermission } from "@tauri-apps/plugin-notification"

export function useSystemNotify() {
  async function notify(title: string, body: string) {
    let granted = await isPermissionGranted()
    if (!granted) granted = (await requestPermission()) === "granted"
    if (granted) await sendNotification({ title, body })
  }
  return { notify }
}
```

**触发场景**（在 sidecar 通过 SSE event 推到前端 → 前端调 useSystemNotify）：

| 事件 | title | body |
|---|---|---|
| 等待 Chrome 关闭 | "CSM 百度监控" | "请关闭 Chrome 浏览器以开始监控（自动检测中）" |
| 监控完成 | "CSM 百度监控" | "已抓 N 词，可以重新打开 Chrome" |
| 需要人工验证 | "CSM 百度监控" | "需要人工解验证码（关键词：xxx），点击此处" |
| 失败（Chrome 未关）| "CSM 百度监控" | "等待 Chrome 关闭超时" |

**保留现有内存通知**（[useNotifications.ts](frontend/src/composables/useNotifications.ts)）：所有这些事件**同时**写入内存通知日志，用户事后能在 NotificationDropdown 里翻历史。

### 5. 错误兜底 UI

| 错误场景 | UI 表现 |
|---|---|
| 探测 Chrome 失败（未装）| 设置页保存按钮灰显 + "未检测到 Chrome 安装，请安装 Chrome 后重试 [下载链接]" |
| 路径手动填写无效 | 输入框红边 + "路径不存在，请重新选择" |
| 测试启动失败 | 测试按钮下方红色 banner + 完整错误信息（不截断）+ "复制错误" 按钮 |
| 跑监控时启动 Chrome 失败 | 任务状态变 `error` + 错误详情可点开 + 显示 "切回自建 profile 模式（这次运行）" 按钮 |
| Chrome 关闭超时 | 任务状态变 `error` + 文案 "等待 Chrome 关闭超时（120s），请关闭后手动重试" + "重试" 按钮 |

### 6. 不做的 UI 改动（显式排除）

- ❌ 不重做 [BaiduRankingPage.vue](frontend/src/components/monitor/history/BaiduRankingPage.vue) 整体布局 / IA
- ❌ 不引入 Element-Plus / Naive-UI / Ant Design Vue 等第三方组件库
- ❌ 不做"账号管理 / 多 profile 切换" 高级页（用户选 D 即接受单 profile，多 profile 是后续需求）
- ❌ 不做 onboarding 引导 wizard（首次启用 toggle 时只给 inline 说明即可）

### 7. 后端新 API（配合 UI）

| Method | Path | 用途 |
|---|---|---|
| GET | `/api/monitor/baidu/native-config` | 读当前 native mode 配置 |
| POST | `/api/monitor/baidu/native-config` | 保存 native mode 配置 |
| POST | `/api/monitor/baidu/detect-chrome` | 自动探测 Chrome 安装 + user_data_dir |
| POST | `/api/monitor/baidu/list-profiles` | 列出 user_data_dir 下所有 profile + 账号名 |
| POST | `/api/monitor/baidu/test-native` | 试启动 Chrome 验证配置可用 |

SSE 现有 `/api/monitor/stream` 增加事件类型：
- `waiting_chrome_close` (payload: `{task_id, remaining_s}`)
- `chrome_closed` (payload: `{task_id}`)
- `needs_captcha` (payload: `{task_id, keyword, kw_idx}`)

---

## 兼容性 / 兜底

- `baidu_use_native_chrome=False`（默认）→ 行为完全不变，所有现有用户零感知
- 软着陆验证码独立于 native mode：即使关 native，自建 profile 模式下命中风控也走软着陆（弹 headed 临时窗口让用户解），不再硬停
- 当前自建 `baidu_browser_profile` 不删，保留作 fallback + 测试路径
- 配置迁移：现有用户升级后，`baidu_use_native_chrome` 默认 `False`，无需主动操作；首次进设置页能看到新开关

## 测试策略

### 后端单元

- `chrome_preflight.is_chrome_running`：mock `psutil.process_iter` 模拟有/无 chrome.exe 进程
- `chrome_preflight.wait_for_chrome_closed`：mock + 模拟 1s/3s 后关闭、超时三种场景
- `baidu_browser_session(use_native_chrome=True)`：mock `pw.chromium.launch_persistent_context`，断言 kwargs 包含正确的 `channel="chrome"` / `executable_path` / `--profile-directory`
- 配置探测：mock 注册表读取、文件系统、Preferences JSON 解析
- 新 API 路由单元：`detect-chrome` / `list-profiles` / `test-native` / `native-config` GET/POST

### 后端集成

- mock Patchright + 注入假 SERP HTML → 跑 fetch with `use_native_chrome=True` → 断言走 native 分支、其他逻辑不变
- mock 风控触发 → 验证 `_try_human_solve` 调用、超时 fallback 正常
- SSE 事件推送：mock fetch 流程触发 `waiting_chrome_close` / `chrome_closed` / `needs_captcha` 事件 → 断言 SSE stream 收到

### 前端单元

- `useSystemNotify` composable：mock `@tauri-apps/plugin-notification`，验证权限请求 + sendNotification 调用
- 新增设置页组件：mock API → 验证字段渲染、自动探测按钮触发、profile 下拉框联动 user_data_dir 变化
- `BaiduRankingPage` 新状态：mock SSE 推 `waiting_chrome_close` → 断言 UI 显示倒计时 banner

### 手动

- 真机实测：用户日常电脑装好 native mode → 跑 100 词 → 记录耗时、风控触发次数、人工解题次数
- 故意制造风控：连续抓 5-10 个高频热词不间隔 → 验证软着陆体验顺畅
- Chrome 关闭检测：跑监控期间手动开 Chrome 看 CSM 是否抢、关 Chrome 看是否自动开跑
- 通知体验：CSM 最小化时跑监控 → 验证系统通知能弹出 + 点击能拉回窗口
- 多 profile 用户：装两个 Chrome profile、各自登不同百度账号 → 验证下拉框正确显示账号名 + 切换 profile 跑监控行为正确

## 工期估算

### 后端

| 阶段 | 工作量 |
|---|---|
| 配置 schema + 自动探测逻辑（chrome_path / user_data_dir / profile 列表）| 1 天 |
| `chrome_preflight.py` 新文件 + 单元测试 | 1 天 |
| `baidu_browser.py` native mode + 单元测试 | 1 天 |
| `baidu_keyword.py` fetch hook + 集成测试 | 1 天 |
| 软着陆验证码集成（`_try_human_solve` 函数 + 集成测试）| 1-2 天 |
| 5 个新 API 路由（detect-chrome / list-profiles / test-native / native-config GET/POST）+ 测试 | 1 天 |
| SSE 事件推送扩展（3 个新事件类型）+ 测试 | 0.5 天 |

**后端合计：6.5-7.5 天**

### 前端

| 阶段 | 工作量 |
|---|---|
| 新增依赖 `@tauri-apps/plugin-notification`（package.json + Cargo.toml + capabilities）| 0.5 天 |
| `useSystemNotify` composable + 单元测试 | 0.5 天 |
| 新增"全局百度抓取设置"区组件（沿用 FormField/FormInput/FormToggle）| 1.5-2 天 |
| 自动探测按钮 + 文件/目录选择对话框接入 | 0.5 天 |
| `BaiduRankingPage` 新状态 `waiting_chrome_close` 倒计时 banner | 0.5 天 |
| 错误兜底 UI（5 种错误场景的 inline 提示 / banner）| 0.5 天 |
| 前端单元 + 手动测试 | 1 天 |

**前端合计：5-5.5 天**

### 联调 / 手动测试

| 阶段 | 工作量 |
|---|---|
| 前后端 SSE / API 联调 | 1 天 |
| 真机实测 + 修磨（100 词、多 profile、故意触发风控等场景） | 1-2 天 |

**联调合计：2-3 天**

### **总计：13-16 个工作日**（约 3 周）

## 不做的事（显式排除）

- ❌ CDP attach（影刀那套）—— stealth 失效
- ❌ 多账号 cookie 池 —— 单 profile 够用
- ❌ IP 代理池 —— 同上
- ❌ 复制 profile 副本（方案 B''）—— 用户已明确选 D
- ❌ 改用户 Chrome 启动方式（加 debug 端口等）—— 完全不动用户日常 Chrome
- ❌ 自动启动用户 Chrome（让 CSM 帮你重开 Chrome）—— 不替用户做 OS 级操作
- ❌ 跨 OS（Mac / Linux）—— 当前只针对 Windows，跨平台后续单独 spec

## 性能与风控预期（关键 ── 实施前必读）

### 速度估算（基于真实代码）

单关键词成本组成（串行）：
- SERP pacing 5-10s（除第一个）
- SERP 浏览器加载 2-5s
- 默认搜索 ~10 条结果 × (resolve_baidu_link 1-2s + fetch_article_http 2-5s + article_pacing 3-6s) = 60-130s
- 最新资讯块（如果有）10-40s
- **单关键词合计：~50-150s（中位 ~80-100s）**

100 词预期总耗时：

| 配置 | 时长 | 风控触发风险 |
|---|---|---|
| 默认 pacing（SERP 5-10s + 文章 3-6s）| 130-170 分钟（2-3 小时）| 低 |
| 文章 pacing 降到 1-2s（推荐起步）| 60-90 分钟（1-1.5 小时）| 低-中 |
| SERP 2-3s + 文章并行 | 30-45 分钟 | 高 |

**关键洞察**：百度风控只看 SERP + `baidu.com/link?url=`，文章本身在第三方网站，文章 pacing 对百度风控影响极小。所以文章 pacing 可以激进降低，对百度风控几乎没影响。

### 风控触发率改善评估

方案 D 在 6 个风控维度上的实际改善：

| 维度 | 当前 | 方案 D | 改善幅度 |
|---|---|---|---|
| Cookie / Profile 真实度 | ~30%（CSM 自建空 profile）| ~95%（用户日常真 profile）| **大幅改善 ⭐** |
| UA 真实度 | 已轮换 | 已轮换 | 无变化 |
| TLS 指纹 | chrome120 | chrome120 | 无变化 |
| **IP 段** | 用户家 / 公司 IP | **同一个 IP** | **无变化** |
| SERP 节奏 | 5-10s | 5-10s（除非主动调）| 无变化 |
| 行为模式（直接 goto）| 同 | 同 | 无变化 |

**结论**：方案 D 本质上只在"profile 真实度"这一个维度大幅改善。其他维度不变。

### 预期触发率（最佳估计，非承诺）

- 当前现状：每 3-5 词触发一次 → 平均 4 词/触发
- 方案 D 第一周：估计 20-50 词/触发
- 方案 D 稳态：估计 50-100 词/触发（解过几次验证码后 cookie 进一步洗白）
- **100 词跑一轮：预期 0-3 次触发，但可能更多**

### 不能承诺"零触发"的根本原因

1. **IP 维度完全没动**。百度风控对 IP 速率有独立阈值，profile 救不了
2. **百度风控算法是黑盒**。阈值随关键词热度、时段、当前对方策略变化
3. **用户 IP 段的"声誉"未知**。如果此 IP 之前跑过别的 RPA 被标记，效果会打折
4. **影刀能跑顺的真相**：用户描述"时间长一点"=影刀本身节奏比 CSM 慢，不是"魔法"

### 如果"零触发"是硬需求，需要的额外投入

| 方案 | 效果 | 成本 |
|---|---|---|
| SERP pacing 30s+ | 大幅降触发率 | 100 词光 SERP 等就 ~50 分钟 |
| 多账号 cookie 池（3-5 号轮换）| 单号速率减半-1/5 | 养 3-5 个百度号 |
| IP 代理池 | 分散 IP 维度信号 | 月付 ¥100-500 |
| 时段拆分（早 50 + 晚 50）| 避开风控高峰 | 接受半天才能跑完 |

**这些方案 D 都不包含**。方案 D 上线后建议先跑 3-5 天收集真实触发率数据，再决定要不要加。

### 验证方案 D 假设的方式

实施完成后**第一周**重点监控：
- 100 词单轮的实际耗时
- 单轮触发风控的次数
- 触发时间分布（是均匀触发还是连续触发）
- 人工解题后能继续跑多少词

如果实际数据明显偏离预期（比如每 10 词就触发一次），说明 IP 段问题大，需要立即加 IP 代理或多账号。

## 风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| Chrome 新版破坏 channel="chrome" 兼容 | native mode 启动失败 | fallback 到自建 profile + 警告日志 |
| 用户日常 profile 被爬虫"污染"（百度搜索 history 写入）| 用户日常浏览能看到 CSM 跑过的搜索记录 | 已在文档说明、用户选 D 即接受此 trade-off |
| psutil 在某些 Windows 环境检测 chrome.exe 失败 | wait_for_chrome_closed 永远等不到 | 加超时 + UI 显示错误提示 |
| 用户多 profile 选错 | 用错号、cookie 不对 | UI 下拉框显示 profile 账号名，明确标注"建议选你平时用得最多的" |
