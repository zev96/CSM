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

- 100 词/天能流畅跑完，单轮耗时 < 20 分钟
- 单轮触发风控次数稳态 ≤ 2 次
- 偶发风控时浏览器已在用户面前，解题流程 ≤ 30 秒
- 用户首次启用 ≤ 10 秒（不养号、不复制文件）
- 不改用户日常 Chrome 启动方式

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
6. 100 词预计 8-15 分钟（基于：SERP pacing 5-8s × 100 + 每词解 5-10 篇文章 × article pacing 3-6s，真 profile 后估计 0-2 次风控、每次解题 30 秒）
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

## 兼容性 / 兜底

- `baidu_use_native_chrome=False`（默认）→ 行为完全不变，所有现有用户零感知
- 软着陆验证码独立于 native mode：即使关 native，自建 profile 模式下命中风控也走软着陆（弹 headed 临时窗口让用户解），不再硬停
- 当前自建 `baidu_browser_profile` 不删，保留作 fallback + 测试路径
- 配置迁移：现有用户升级后，`baidu_use_native_chrome` 默认 `False`，无需主动操作；首次进设置页能看到新开关

## 测试策略

### 单元

- `chrome_preflight.is_chrome_running`：mock `psutil.process_iter` 模拟有/无 chrome.exe 进程
- `chrome_preflight.wait_for_chrome_closed`：mock + 模拟 1s/3s 后关闭、超时三种场景
- `baidu_browser_session(use_native_chrome=True)`：mock `pw.chromium.launch_persistent_context`，断言 kwargs 包含正确的 `channel="chrome"` / `executable_path` / `--profile-directory`
- 配置探测：mock 注册表读取、文件系统、Preferences JSON 解析

### 集成

- mock Patchright + 注入假 SERP HTML → 跑 fetch with `use_native_chrome=True` → 断言走 native 分支、其他逻辑不变
- mock 风控触发 → 验证 `_try_human_solve` 调用、超时 fallback 正常

### 手动

- 真机实测：用户日常电脑装好 native mode → 跑 100 词 → 记录耗时、风控触发次数、人工解题次数
- 故意制造风控：连续抓 5-10 个高频热词不间隔 → 验证软着陆体验顺畅
- Chrome 关闭检测：跑监控期间手动开 Chrome 看 CSM 是否抢、关 Chrome 看是否自动开跑

## 工期估算

| 阶段 | 工作量 |
|---|---|
| 配置 + 自动探测 + UI | 1 天 |
| `chrome_preflight.py` 新文件 + 单元测试 | 1 天 |
| `baidu_browser.py` native mode + 单元测试 | 1 天 |
| `baidu_keyword.py` fetch hook + 集成测试 | 1 天 |
| 软着陆验证码集成 | 1-2 天 |
| 通知集成（Tauri 通知 API 接入 sidecar）| 0.5 天 |
| 手动测试 + 调优 | 1-2 天 |
| **合计** | **6-8 个工作日** |

## 不做的事（显式排除）

- ❌ CDP attach（影刀那套）—— stealth 失效
- ❌ 多账号 cookie 池 —— 单 profile 够用
- ❌ IP 代理池 —— 同上
- ❌ 复制 profile 副本（方案 B''）—— 用户已明确选 D
- ❌ 改用户 Chrome 启动方式（加 debug 端口等）—— 完全不动用户日常 Chrome
- ❌ 自动启动用户 Chrome（让 CSM 帮你重开 Chrome）—— 不替用户做 OS 级操作
- ❌ 跨 OS（Mac / Linux）—— 当前只针对 Windows，跨平台后续单独 spec

## 风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| Chrome 新版破坏 channel="chrome" 兼容 | native mode 启动失败 | fallback 到自建 profile + 警告日志 |
| 用户日常 profile 被爬虫"污染"（百度搜索 history 写入）| 用户日常浏览能看到 CSM 跑过的搜索记录 | 已在文档说明、用户选 D 即接受此 trade-off |
| psutil 在某些 Windows 环境检测 chrome.exe 失败 | wait_for_chrome_closed 永远等不到 | 加超时 + UI 显示错误提示 |
| 用户多 profile 选错 | 用错号、cookie 不对 | UI 下拉框显示 profile 账号名，明确标注"建议选你平时用得最多的" |
