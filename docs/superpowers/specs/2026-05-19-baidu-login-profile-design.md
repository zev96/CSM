# 百度登录态 + 简化 SERP 导航 — Design

## 背景

CSM v0.4.x 的 baidu_keyword 监测被百度风控持续拦截。最近一周以 stealth 思路（持久 profile + 模拟人输入 + 鼠标抖动 + 长 dwell）加固后，real-world 测试仍在 keyword #0 即触发 `layer=text detail=text contains '安全验证'`。日志确认 baidu 主页正常加载 (`has_input#kw=1, title='百度一下，你就知道'`) 但 5 秒内 SERP 响应直接被风控替换。

复盘根因：

1. 三段式流程（home → 等 3-6s → 模拟鼠标 → fill input#kw force=True → 等 0.8-1.5s → keyboard.press(Enter)）的时间窗口太稳定，rhythm 反而是 bot 特征。真实用户不会每次都"先停 5 秒再填字"。
2. 匿名访问下 baidu 风控信任分极低，新建 BAIDUID 几个请求即触发。
3. 现有 stealth 加固只动了浏览器层指纹（patchright stealth fork），没有动**账号层身份**。

参考的开源方案 `HuChundong/baidu-ai-search` 解决的是 baidu **AI 搜索**产品（chat 风格）的抓取，不是普通 SERP，"复制按钮 + 读剪贴板"手法不适用；docker browserless 跟 CSM 桌面 app 边界冲突。其中**移动端 UA 模拟**有一定参考价值，但作为登录态方案的 fallback 收益不足以匹配复杂度，本期不做。

用户已确认两个核心决策：

- 登录方式：CSM 嵌入登录 webview（patchright headed 窗口）
- 登录态过期：暂停任务 + UI 起红点提醒重登（复用现有 risk_control 暂停机制）

## 目标

让 baidu_keyword 任务在带登录态的 persistent profile 下稳定跑完 10 keyword × 1 task，不再被"安全验证"挡住。同时回归更简单、更接近"原架构"的 SERP 导航路径。

## 非目标

- 不实现 mobile UA / 移动端 SERP URL
- 不实现 proxy 池 / IP 轮换
- 不引入 Docker browserless
- 不使用用户主浏览器（Chrome/Edge）的 profile —— 文件锁冲突 + 隐私边界
- 不支持多账号轮换（一个 persistent profile 一个登录账号即可，需要换号走 reset profile 路径）

## 架构总览

四层：

```
Layer 1 — 简化 SERP 导航（删除三段式，回 page.goto(serp_url)）
Layer 2 — 登录 webview + persistent profile
Layer 3 — 登录态检测与暂停（复用 RiskControlException 机制）
Layer 4 — 保留：persistent profile / reset / article 双路 / 百家号节流
```

模块边界：

```
csm_core/monitor/
├── drivers/
│   ├── baidu_browser.py        # 不变。persistent context contextmanager
│   ├── baidu_login.py          # 新。open_login_window + get_login_status + detect_login_required
│   ├── patchright_pool.py      # 不变。ensure_browsers_path
│   └── risk_detector.py        # 不变。4 层风控
├── platforms/
│   └── baidu_keyword.py        # 改。_navigate_to_serp 简化 + _fetch_once 内加登录态前置 check
└── ...

sidecar/csm_sidecar/routes/
└── monitor.py                  # 加 POST /api/monitor/baidu/login + GET /api/monitor/baidu/login-status

frontend/src/views/
└── SettingsView.vue            # 加百度账号 SettingsRow
```

## Layer 1: 简化 SERP 导航

**改动文件**：`csm_core/monitor/platforms/baidu_keyword.py`

**当前** `_navigate_to_serp(page, keyword, *, is_first_keyword)`（约 75 行）：
- `is_first_keyword=True`：`page.goto("https://www.baidu.com/")` → diagnostic log → `wait_for_timeout(3000-6000ms)` → `_simulate_user_browsing(page)` → `page.fill("input#kw", keyword, force=True)` → `wait_for_timeout(800-1500ms)` → `page.keyboard.press("Enter")` with `expect_navigation`
- `is_first_keyword=False`：跳过 home / dwell / mouse 段，复用搜索框

**简化后**：

```python
def _navigate_to_serp(page: Any, keyword: str) -> Any:
    """直接 goto SERP url。返回 navigation response 供 detect_risk 用。

    回归原架构 —— 三段式 home/fill/Enter 的时间 pattern 反而是 bot 信号。
    带登录态的直接 goto 看起来像真实用户从书签或外链进 SERP，是 baidu
    organic 流量的主要形态。
    """
    serp_url = "https://www.baidu.com/s?wd=" + quote(keyword)
    return page.goto(serp_url, wait_until="domcontentloaded", timeout=30000)
```

**同步删除**：

- 函数参数 `is_first_keyword`
- helper `_simulate_user_browsing(page)`
- `_random_dwell_ms` 的长 dwell 分支（3000-6000ms）。短 dwell（800-1500ms）也删掉 —— SERP 间节流统一交给 `rate_limit.get_pacer("baidu_keyword")`，不再需要 helper 抖动。
- `_fetch_once` 里 `is_first_keyword=(rel_idx == 0)` 的参数传递
- 测试文件 `test_baidu_keyword.py` 里 navigate-related 的 FakeKeyboard / FakeMouse 测试样例

**测试改写**：

`test_baidu_keyword.py` 的 `_navigate_to_serp` 测试组改为：
- 断言 `page.goto` 被调用 1 次
- 第 1 参数 URL 含 `wd=` 加 quote(keyword)
- `wait_until="domcontentloaded"` 显式传入
- 返回值即 page.goto 的 response

## Layer 2: 登录 webview + persistent profile

**新文件**：`csm_core/monitor/drivers/baidu_login.py`

### Public API

```python
def open_login_window(
    user_data_dir: Path | None = None,
    *,
    timeout_s: int = 600,
) -> dict[str, Any]:
    """开一个可见 patchright headed 窗口让用户登录百度。

    流程：
    1. launch_persistent_context(headless=False) 在 baidu profile 上开窗
    2. page.goto("https://www.baidu.com/")，让用户点右上"登录"
    3. 每 3 秒 poll context.cookies("https://www.baidu.com/")，检测 BDUSS 是否出现
    4. 同时监听 BrowserContext "close" 事件（用户手动关窗）
    5. BDUSS 命中 → 等 2 秒让所有登录 cookie 落盘 → context.close()
    6. 用户关窗 → 立即返回 cancelled
    7. timeout_s 达到 → 关窗 + 返回 timeout

    BDUSS 命中后可选地调 baidu passport /api/?logininfo 拿 username，失败不阻塞。
    success 时把 {"username": str | None, "logged_in_at": iso8601} 写到
    user_data_dir / ".csm_login_meta.json"，供 get_login_status 后续读取。

    Returns:
        {"status": "success" | "cancelled" | "timeout", "username": str | None}

    Raises:
        RuntimeError: persistent profile 已被 active baidu task 锁住
                      （caller 在 sidecar route 里先 has_active_baidu_task 409 兜底）。
    """


def get_login_status(user_data_dir: Path | None = None) -> dict[str, Any]:
    """读 persistent profile 看登录态。不弹窗。

    实现：launch_persistent_context(headless=True) 短时启动一次，读
    cookies("https://www.baidu.com/")，立刻关。开销 ~2s，settings 页打开
    时调一次能接受。

    BDUSS 不在 → logged_in=False。
    BDUSS 在但 expires < now → logged_in=False（cookie 已过期）。
    BDUSS 在且未过期 → logged_in=True，username 从 user_data_dir / ".csm_login_meta.json"
        读取（open_login_window 成功时同步写入；passport API 拉 username 失败
        时缓存文件没有 username 字段，前端降级显示"已登录"）。

    Returns:
        {"logged_in": bool, "username": str | None, "expires_at": str | None}
    """


def detect_login_required(response: Any, page: Any) -> bool:
    """SERP 响应是否提示需要登录（'登录后体验更佳' / 跳转到 wappass）。

    Layer 3 的 SERP 后置兜底用。主入口检查走 fetch 开头的 BDUSS check；
    这个用于 cookie 看着是登录态但 server-side session 失效的边界情况。

    判定规则：
    - response.url 含 'wappass.baidu.com' / 'passport.baidu.com' → True
    - page.content 里含「请登录」类文案 → True
    - 否则 False
    """
```

### Sidecar 路由

`sidecar/csm_sidecar/routes/monitor.py` 加：

```
POST /api/monitor/baidu/login
  - 前置：has_active_baidu_task() → 409 + {"detail": "请先停止运行中的百度任务"}
  - 调 baidu_login.open_login_window()
  - 返回 {"status": "success"|"cancelled"|"timeout", "username": str|None}
  - 5xx 仅在 RuntimeError（profile lock 等）时返回

GET /api/monitor/baidu/login-status
  - 调 baidu_login.get_login_status()
  - 返回 {"logged_in": bool, "username": str|None, "expires_at": str|None}
  - 失败（profile 损坏等）也降级返回 logged_in=False, 不抛 5xx
```

### 前端 UI

`frontend/src/views/SettingsView.vue` 在"重置百度浏览器 profile"按钮旁加新行 SettingsRow：

- 状态字段（onMounted + 显式刷新按钮触发 GET login-status）：
  - 未登录：灰字"未登录" + 蓝色"登录百度"按钮
  - 已登录：绿字"已登录 @{username}"（无 username 时显示"已登录"）+ 灰边"重新登录"按钮 + 过期提示（如剩余 <7 天）
  - 过期：红字"登录已过期，请重新登录" + 红边"重新登录"按钮
- 点击按钮：
  - 用 `confirm()` 对话框二次确认（避免误点中断任务）
  - 调 POST /api/monitor/baidu/login，等响应（webview 可能开 30s-10min）
  - 接收响应：success → toast 绿色"登录成功"+ 刷新状态；cancelled → toast 灰色"已取消"；timeout → toast 红色"登录超时，请重试"
  - 409 错误：toast 红色"请先停止运行中的百度任务"

### 用户提示

登录 webview 顶部建议用 `page.add_init_script` 注入一个 banner：

```html
<div style="background:#FEF3C7; padding:8px; text-align:center; font-size:12px;">
  ⚠️ 建议使用专用百度账号。CSM 抓取触发风控时该账号可能受限。
</div>
```

非阻塞建议，落地优先级：MVP 后做（spec 标记为 follow-up）。

### 测试

`sidecar/tests/test_baidu_login.py`（新）：

- `test_open_login_window_success`：FakeContext.cookies 第 1 次空 → 第 2 次返回 [{"name": "BDUSS", ...}] → 断言 status="success" + context.close 被调
- `test_open_login_window_cancelled`：FakeContext 触发 close 事件 → 断言 status="cancelled"
- `test_open_login_window_timeout`：FakeContext.cookies 始终空 + timeout_s=1 → 断言 status="timeout"
- `test_get_login_status_logged_in`：FakeContext.cookies 返回 BDUSS 含 future expires → 断言 logged_in=True
- `test_get_login_status_not_logged_in`：cookies 空 → logged_in=False
- `test_get_login_status_expired`：cookies BDUSS expires < now → logged_in=False
- `test_detect_login_required_wappass`：fake response.url 含 wappass → True
- `test_detect_login_required_normal_serp`：fake response.url 是 SERP → False

`sidecar/tests/test_monitor_routes.py`（加）：

- `test_baidu_login_409_when_task_active`：monkeypatch has_active_baidu_task → True，POST → 409
- `test_baidu_login_success`：monkeypatch open_login_window → success，POST → 200 + 透传
- `test_baidu_login_status`：monkeypatch get_login_status，GET → 透传

**前端无单测框架**（package.json 没装 vitest / jest），所以 SettingsView 改动只跑 `vue-tsc` 类型检查 + 手动 verify：登录按钮点击 → POST → toast 反馈；状态行 onMounted → GET → 渲染对应文案。验证计划章节有具体步骤。

## Layer 3: 登录态检测与暂停

`BaiduKeywordAdapter.fetch()` 公共签名 / 编排逻辑不变（仍是 `fetch → _fetch_with_promotion → _fetch_once`）。登录态检测加在 `_fetch_once` 内的 `with baidu_browser_session(...)` 块进入后、keyword 循环开始前 —— 复用主 session 的 context 读 cookie，避免单独再开一个 short-lived context 的 2s 启动开销。

具体在 `_fetch_once` 里插入：

```python
with baidu_browser_session(headless=headless) as session:
    page = session.page

    # 登录态前置 check：未登录直接 raise risk_control（layer="auth"），
    # runner 暂停任务 + 写断点，UI 起红点提醒重登。
    # 用主 session 的 context 读 cookie，无额外启动开销。
    cookies = session.context.cookies("https://www.baidu.com/")
    has_bduss = any(c.get("name") == "BDUSS" for c in cookies)
    if not has_bduss:
        raise RiskControlException(
            signal=RiskSignal(layer="auth", detail="百度账号未登录或已过期"),
            progress=resume_from,
        )

    # 现有 keyword 循环 ...
    for rel_idx, keyword in enumerate(keywords_to_fetch):
        ...
        response = _navigate_to_serp(page, keyword)
        # 已有的 4 层 detect_risk(page, response) 不变
        # 新增 SERP 后置兜底：cookie 看着是登录态但 server session 失效
        if detect_login_required(response, page):
            raise RiskControlException(
                signal=RiskSignal(layer="auth", detail="登录态失效，被重定向到登录页"),
                progress=kw_idx,
            )
        ...
```

### 风控类型扩展

`RiskSignal.layer` 现有取值：`"url"` / `"http"` / `"dom"` / `"text"`。新增 `"auth"`。`risk_detector.py` 不需要改（auth 不走 detect_risk 路径，是 adapter 自己 raise）。

### 前端 UI 改动

`BaiduRankingPage.vue` Level 2 顶部的 risk_control 提示条已有逻辑（参考 baidu-monitor-hardening-design.md Bug 2.2 修复）。layer="auth" 时文案改：

```vue
<div v-if="latestResult?.status === 'risk_control' && latestResult.metric?.captcha_signal_layer === 'auth'">
  百度账号未登录或已过期，请到「设置 → 百度账号」重新登录后从断点继续抓取。
  <button @click="goSettings">前往设置</button>
</div>
```

monitorStatus store 的 `failed` SSE handler 已经分诊跳过 "风控拦截"，无需改动。

### 测试

`csm_core/tests/monitor/test_baidu_keyword.py`（加）：

- `test_fetch_raises_when_not_logged_in`：mock `baidu_browser_session` yield 一个 context.cookies 返回 [] → 断言 raise RiskControlException(layer="auth"), progress=resume_from
- `test_fetch_proceeds_when_logged_in`：mock 返回 [{"name": "BDUSS", ...}] → 断言 进入 SERP 循环
- `test_fetch_raises_when_serp_redirects_to_login`：mock SERP response.url 含 wappass → 断言 raise(layer="auth")
- `test_fetch_resume_progress_preserved`：未登录 raise 时 progress 等于传入的 resume_from（已抓的不重复）

BaiduRankingPage 改动同样无 JS 单测，靠 `vue-tsc` 类型检查 + 手动 verify：构造一条 status="risk_control" + metric.captcha_signal_layer="auth" 的历史记录，断言 Level 2 顶部显示「百度账号未登录或已过期」文案 + 「前往设置」按钮。

## Layer 4: 保留 / 清理

**保留不动**：

- `csm_core/monitor/drivers/baidu_browser.py` 整个 `baidu_browser_session` contextmanager
- `_default_user_data_dir` / `reset_profile` / `_log_profile_health`
- 设置页 "重置百度浏览器 profile" 按钮（用户切账号 / profile 损坏时用）
- `has_active_baidu_task` + reset/login 互斥 409
- `_BAIJIAHAO_PACER_KEY` / `_ARTICLE_PACER_KEY` 节流逻辑
- 断点 + resume 机制（last_resumed_keyword）
- article 双路抓：HTTP-first (curl_cffi + readability) + browser fallback
- 4 层 risk_detector（url / http / dom / text）

**百家号节流可选微调**：`_BAIJIAHAO_PACER_KEY` 间隔从 5-10s 改 8-15s。登录态下可能不需要，先观察一轮再决定。spec 不强制做。

## 风险与开放点

1. **登录窗口 entry URL**：spec 倾向 `https://www.baidu.com/`，让用户点右上"登录"按钮（更自然，符合真人路径）。备选 `https://passport.baidu.com/v2/?login` 直达登录页（少一步但 URL fingerprint 更明显是"自动化进登录页"）。MVP 用 www.baidu.com，实现时如果发现 baidu 主页对未登录的 patchright 不友好，再回头评。
2. **patchright 进程与 Tauri 主窗口的焦点关系**：patchright 是独立 Chromium 进程，跟 Tauri WebView 不冲突。Win 11 上窗口弹出可能需要 `page.bring_to_front()` 抢前台。实现时验证。
3. **BDUSS 过期不立刻被百度撤销**：server-side session 可能先于 cookie expires_at 失效。Layer 3 的 SERP 后置 `detect_login_required(response, page)` 兜底覆盖这种情况。
4. **多账号场景**：本期不支持。用户想换账号 → 设置页"重置百度浏览器 profile"（删 profile）→ 重新登录。后续若需要多账号轮换，再设计 profile 切换 UI。
5. **username 获取的可靠性**：baidu passport `/api/?logininfo` 接口非公开 API，可能改 schema。`open_login_window` 拿不到 username 不阻塞 success 判定（status="success", username=None）。前端 fallback 显示"已登录"。
6. **登录窗口超时默认值**：spec 给 600s（10 分钟）。扫码登录 + 真人输入用户名密码 + 短信验证一般 ≤2min，给充裕余量。实现时可以暴露成 sidecar 配置项。
7. **登录 banner 提示专用账号**：spec 标 follow-up，MVP 不阻塞。建议二期补 `page.add_init_script` 注入。
8. **diagnostics log 保留还是删**：当前 `_navigate_to_serp` 里的 `baidu home loaded: ...` log 在简化后无意义（不再 goto home）。`baidu fill failed: ...` log 也随 fill 删除一起去掉。整个 diagnostic 块清理。

## 验证计划

**单测**（后端）：
- `sidecar/tests/test_baidu_login.py`（新，8 个 case）
- `sidecar/tests/test_monitor_routes.py`（加 3 个 case）
- `csm_core/tests/monitor/test_baidu_keyword.py`（加 4 个 case，改写 navigate 组）

**前端**：无 JS 单测框架。靠 `vue-tsc` 类型检查 + 手动验证（步骤见"真实跑"段）。

**集成**：
- `cd sidecar && python -m pytest tests/test_baidu_login.py tests/test_monitor_routes.py -x`
- `cd csm_core && python -m pytest tests/monitor/test_baidu_keyword.py -x`
- `cd frontend && npm run build`（含 vue-tsc 类型检查）

**真实跑**（Tauri dev）：
1. 启动应用，进设置 → 百度账号 → 点"登录百度"
2. webview 弹出 baidu 主页 → 点右上"登录" → 扫码或账密
3. 登录成功 → webview 自动关 → 设置页显示"已登录 @用户名"
4. 跑一个 0519-4 baidu_keyword 任务（10 keyword × 真扫地机品牌词）
5. 断言：日志看不到 "风控拦截：layer=text"，10 keyword 完整跑完，default_results 有内容，content_preview 有真实文章正文
6. 如果还是触发风控 → cookie 看着是登录态但 server session 已失效 → 检查日志是否有 layer="auth"（SERP 后置兜底命中）
7. 设置页强制删除 profile → 重新跑任务 → 应当立即触发 layer="auth" risk_control，UI 起红点

**回归测试**：
- 评论 / 知乎 / 抖音 / 小红书 / 微信 等其他 platform adapter 不受影响（baidu_login 改动隔离在 baidu_keyword 调用链）
- AddTaskModal 单个新增 baidu_keyword 任务 / BatchImportTaskModal 批量导入仍工作（仅 fetch 路径变了，task 创建不变）
- reset profile 按钮仍能用（用户切账号场景）

## 实施顺序建议

writing-plans 阶段细化。粗顺序：

1. Layer 1 简化 SERP 导航 + 测试改写（独立可上）
2. Layer 2 baidu_login.py + 测试（独立可上）
3. Layer 2 sidecar 路由 + 测试
4. Layer 2 SettingsView UI + 测试
5. Layer 3 fetch 入口加 BDUSS check + 测试
6. Layer 3 SERP 后置 detect_login_required + 测试
7. Layer 3 BaiduRankingPage UI 文案 + 测试
8. Layer 4 清理（删 _simulate_user_browsing / 长 dwell / diagnostic log / is_first_keyword 参数）
9. 最终 regression sweep + 真实环境测一轮 baidu_keyword task
