# 百度登录 headless 二进制修复 + 入口迁移 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 Cookie/百度登录态在 headless 下能正常读取（修掉「已登录却显示未登录」），并把百度登录入口从 Cookie 管理器迁到「百度关键词设置 · 默认 headless 开关上方」。

**Architecture:** 根因是 `headless=True` 启动让 Patchright 去找未随包的 `chrome-headless-shell.exe`。修法：所有 headless 启动显式传**完整 Chromium 的 `executable_path`**（`pw.chromium.executable_path`，已随包），绕开 headless-shell。顺带给登录轮询/状态读取加 INFO raw 日志。前端把登录卡片从 `CookieManagerModal.vue` 迁到 `SettingsView.vue` 百度区。

**Tech Stack:** Python (patchright sync API), pytest（fake-playwright monkeypatch），Vue 3 `<script setup>` + TS，vue-tsc/vite。

---

## 重要：测试命令（worktree 必读）

`csm_sidecar` 是从主仓 `D:/CSM/sidecar` editable 安装的，`csm_core` 走 cwd 解析。在 worktree 跑 pytest 必须同时把两条路径挂上，否则会测到主仓旧代码：

```bash
cd D:/CSM/.claude/worktrees/lucid-leavitt-a30b7b
PYTHONPATH="D:/CSM/.claude/worktrees/lucid-leavitt-a30b7b;D:/CSM/.claude/worktrees/lucid-leavitt-a30b7b/sidecar" python -m pytest <test> -v
```

前端验证：`cd frontend && npm run build`（= `vue-tsc -b && vite build`，node_modules 已装）。

---

## 文件结构

| 文件 | 责任 | 改动 |
|------|------|------|
| `csm_core/monitor/drivers/baidu_login.py` | 登录窗 / 状态读取 | `get_login_status` 传 executable_path；poll/status 加 INFO 日志；goto 改 domcontentloaded |
| `csm_core/monitor/drivers/baidu_browser.py` | 抓取用 persistent context | 自建分支 headless 启动传 executable_path |
| `sidecar/tests/test_baidu_login.py` | baidu_login 单测 | 新增 executable_path / 日志断言 |
| `sidecar/tests/test_baidu_browser.py` | baidu_browser 单测 | 新增 headless executable_path 断言 |
| `frontend/src/views/SettingsView.vue` | 设置页百度区 | 新增百度登录卡片（headless 开关上方）+ 登录态 state/函数 |
| `frontend/src/components/monitor/CookieManagerModal.vue` | Cookie 池管理 | 移除「百度」平台分支 + 相关 baidu 函数 |

---

## Task 1: `get_login_status` 用完整 Chromium 跑 headless

**Files:**
- Modify: `csm_core/monitor/drivers/baidu_login.py:128-133`
- Test: `sidecar/tests/test_baidu_login.py`

- [ ] **Step 1: 写失败测试**

在 `test_baidu_login.py` 末尾加（fake-playwright 记录 launch kwargs；fake chromium 暴露 `executable_path`）：

```python
class _FakeCtxForExe:
    def __init__(self, cookies): self._c = cookies; self.closed = False
    def cookies(self, url=None): return list(self._c)
    def close(self): self.closed = True

class _FakeChromiumForExe:
    executable_path = r"C:\fake\chromium\chrome.exe"
    def __init__(self, cookies):
        self.last_kwargs = {}
        self._ctx = _FakeCtxForExe(cookies)
    def launch_persistent_context(self, **kwargs):
        self.last_kwargs = kwargs
        return self._ctx

class _FakePWForExe:
    def __init__(self, cookies): self.chromium = _FakeChromiumForExe(cookies)
    def stop(self): pass

class _FakeSyncForExe:
    def __init__(self, pw): self._pw = pw
    def start(self): return self._pw


def test_get_login_status_passes_full_chromium_executable(monkeypatch, tmp_path):
    """headless 状态读取必须显式传完整 Chromium 的 executable_path，
    否则 Patchright 去找未随包的 chrome-headless-shell 启动失败。"""
    bduss = {"name": "BDUSS", "value": "x", "expires": -1}
    pw = _FakePWForExe([bduss])
    monkeypatch.setattr(
        "csm_core.monitor.drivers.baidu_login._sync_playwright",
        lambda: _FakeSyncForExe(pw),
    )
    monkeypatch.setattr(
        "csm_core.monitor.drivers.baidu_login.ensure_browsers_path", lambda: None,
    )
    from csm_core.monitor.drivers import baidu_login
    status = baidu_login.get_login_status(user_data_dir=tmp_path)

    assert pw.chromium.last_kwargs.get("executable_path") == r"C:\fake\chromium\chrome.exe"
    assert pw.chromium.last_kwargs.get("headless") is True
    assert status["logged_in"] is True
```

- [ ] **Step 2: 跑测试确认失败**

Run:
```bash
PYTHONPATH="D:/CSM/.claude/worktrees/lucid-leavitt-a30b7b;D:/CSM/.claude/worktrees/lucid-leavitt-a30b7b/sidecar" python -m pytest sidecar/tests/test_baidu_login.py::test_get_login_status_passes_full_chromium_executable -v
```
Expected: FAIL —— `last_kwargs.get("executable_path")` 为 `None`（当前代码没传）。

- [ ] **Step 3: 改实现**

`baidu_login.py` 中 `get_login_status` 的 launch 段（当前 128-133 行）改为：

```python
        pw = _sync_playwright().start()
        # headless 必须用完整 Chromium 的 executable_path —— 否则 Patchright
        # 走 headless 默认会找 chrome-headless-shell（未随包），启动直接抛
        # "Executable doesn't exist"，导致登录态读取永远失败 → UI 恒显未登录。
        context = pw.chromium.launch_persistent_context(
            user_data_dir=str(target_dir),
            headless=True,
            executable_path=pw.chromium.executable_path,
        )
```

- [ ] **Step 4: 跑测试确认通过**

Run: 同 Step 2 命令。Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add csm_core/monitor/drivers/baidu_login.py sidecar/tests/test_baidu_login.py
git commit -m "fix(baidu): get_login_status 用完整 Chromium 跑 headless，绕开缺失的 chrome-headless-shell"
```

---

## Task 2: 自建抓取 profile 的 headless 也传 executable_path

**Files:**
- Modify: `csm_core/monitor/drivers/baidu_browser.py:107-117`（自建分支 `launch_kwargs`）
- Test: `sidecar/tests/test_baidu_browser.py`

- [ ] **Step 1: 写失败测试**

`test_baidu_browser.py` 的 `FakeChromium` 加一个 `executable_path` 属性（若已有 fixture 复用之），新增：

```python
def test_self_built_headless_passes_executable_path(monkeypatch, tmp_path):
    """自建 profile + headless=True 抓取也要传完整 Chromium executable_path，
    否则同样撞 chrome-headless-shell 缺失（默认 headless 抓取会挂）。"""
    from csm_core.monitor.drivers import baidu_browser
    pw = FakePW()
    pw.chromium.executable_path = r"C:\fake\chromium\chrome.exe"  # 加到 FakeChromium
    monkeypatch.setattr(baidu_browser, "_sync_playwright", lambda: FakeSyncPW(pw))
    monkeypatch.setattr(baidu_browser, "ensure_browsers_path", lambda: None)

    with baidu_browser.baidu_browser_session(headless=True, user_data_dir=tmp_path):
        pass
    assert pw.chromium.last_kwargs.get("executable_path") == r"C:\fake\chromium\chrome.exe"
    assert pw.chromium.last_kwargs.get("headless") is True
```

> 注：`FakeChromium` 需有 `executable_path` 类属性（默认 `None`）。在 test_baidu_browser.py 的 `FakeChromium.__init__` 里加 `self.executable_path = None`，测试里覆盖。

- [ ] **Step 2: 跑测试确认失败**

Run:
```bash
PYTHONPATH="D:/CSM/.claude/worktrees/lucid-leavitt-a30b7b;D:/CSM/.claude/worktrees/lucid-leavitt-a30b7b/sidecar" python -m pytest sidecar/tests/test_baidu_browser.py::test_self_built_headless_passes_executable_path -v
```
Expected: FAIL —— `executable_path` 为 None。

- [ ] **Step 3: 改实现**

`baidu_browser.py` 自建分支（`else:` 块，107-117 行）改为：

```python
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
```

把 `pw = _sync_playwright().start()` 之后的 launch 调用改为传 executable_path（仅自建分支需要；native 分支已有自己的 chrome.exe）。即在 `context = pw.chromium.launch_persistent_context(**launch_kwargs)` 之前，对自建分支补：

```python
        # 自建 profile：headless 用完整 Chromium，避免 chrome-headless-shell 缺失。
        if not use_native_chrome:
            launch_kwargs["executable_path"] = pw.chromium.executable_path
        context = pw.chromium.launch_persistent_context(**launch_kwargs)
```

> 注意：`launch_kwargs` 在 `pw` 之前构造，executable_path 依赖 `pw.chromium`，所以这行必须放在 `pw = _sync_playwright().start()` 之后、launch 之前。

- [ ] **Step 4: 跑测试确认通过**

Run: 同 Step 2。Expected: PASS。再跑整组 `test_baidu_browser.py` 确认没回归。

- [ ] **Step 5: Commit**

```bash
git add csm_core/monitor/drivers/baidu_browser.py sidecar/tests/test_baidu_browser.py
git commit -m "fix(baidu): 自建 profile headless 抓取传完整 Chromium executable_path"
```

---

## Task 3: 登录轮询 + 状态读取加 INFO raw 日志

**Files:**
- Modify: `csm_core/monitor/drivers/baidu_login.py`（`_open_login_poll` 289-304、`get_login_status` 134-138）
- Test: `sidecar/tests/test_baidu_login.py`

**理由：** 当前 cookie 读取失败只打 DEBUG（sidecar 跑 INFO 级 → 静默）。改成 INFO 级输出 cookie 数 / 关键 cookie 命中 / 异常，让 silent failure 可观测（沿用项目「silent failure 先加 raw logging」教训）。

- [ ] **Step 1: 写测试（caplog 断言 INFO 输出）**

```python
import logging

def test_get_login_status_logs_cookie_summary(monkeypatch, tmp_path, caplog):
    pw = _FakePWForExe([{"name": "BDUSS", "value": "x", "expires": -1}])
    monkeypatch.setattr("csm_core.monitor.drivers.baidu_login._sync_playwright", lambda: _FakeSyncForExe(pw))
    monkeypatch.setattr("csm_core.monitor.drivers.baidu_login.ensure_browsers_path", lambda: None)
    from csm_core.monitor.drivers import baidu_login
    with caplog.at_level(logging.INFO, logger="csm_core.monitor.drivers.baidu_login"):
        baidu_login.get_login_status(user_data_dir=tmp_path)
    assert any("login-status" in r.message and "BDUSS" in r.message for r in caplog.records)
```

- [ ] **Step 2: 跑测试确认失败**

Run:
```bash
PYTHONPATH="D:/CSM/.claude/worktrees/lucid-leavitt-a30b7b;D:/CSM/.claude/worktrees/lucid-leavitt-a30b7b/sidecar" python -m pytest sidecar/tests/test_baidu_login.py::test_get_login_status_logs_cookie_summary -v
```
Expected: FAIL（当前无该 INFO 日志）。

- [ ] **Step 3: 改实现**

`get_login_status` 在拿到 `cookies` 后、`return _status_from_cookies(...)` 之前加：

```python
    names = [c.get("name") for c in cookies]
    logger.info(
        "baidu login-status: read %d cookies (BDUSS=%s) from %s",
        len(cookies), "yes" if "BDUSS" in names else "no", target_dir,
    )
```

`_open_login_poll` 里把 `cookies = context.cookies(...)` 的 except 从 debug 提到 info，并在命中/超时分支加 info：

```python
        try:
            cookies = context.cookies("https://www.baidu.com/")
        except Exception as e:
            logger.info("baidu login poll cookies() raised: %s", e)  # 原 debug→info
            cookies = []
        if any(c.get("name") == "BDUSS" for c in cookies):
            logger.info("baidu login poll: BDUSS detected (%d cookies)", len(cookies))
            return "success"
```

- [ ] **Step 4: 跑测试确认通过**

Run: 同 Step 2。Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add csm_core/monitor/drivers/baidu_login.py sidecar/tests/test_baidu_login.py
git commit -m "feat(baidu): 登录轮询/状态读取加 INFO raw 日志，silent failure 可观测"
```

---

## Task 4: 登录窗 goto 改 domcontentloaded（降低 30s 超时）

**Files:**
- Modify: `csm_core/monitor/drivers/baidu_login.py:261`

- [ ] **Step 1: 改实现（无新行为，纯健壮性，复用现有测试）**

`open_login_window` 里 `page.goto("https://www.baidu.com/")` 改为：

```python
            page.goto("https://www.baidu.com/", wait_until="domcontentloaded")
```

理由：默认 `wait_until="load"` 在百度慢加载时 30s 超时（日志可见）；登录轮询不依赖 goto 完成，`domcontentloaded` 更快返回、超时更少。goto 失败已被 try/except 容忍。

- [ ] **Step 2: 跑现有 baidu_login 测试确认无回归**

Run:
```bash
PYTHONPATH="D:/CSM/.claude/worktrees/lucid-leavitt-a30b7b;D:/CSM/.claude/worktrees/lucid-leavitt-a30b7b/sidecar" python -m pytest sidecar/tests/test_baidu_login.py -v
```
Expected: 全 PASS。

- [ ] **Step 3: Commit**

```bash
git add csm_core/monitor/drivers/baidu_login.py
git commit -m "fix(baidu): 登录窗 goto 用 domcontentloaded，减少 30s 加载超时"
```

---

## Task 5: 前端 —— 百度登录入口迁到 SettingsView 百度区，从 Cookie 管理器移除

**Files:**
- Modify: `frontend/src/views/SettingsView.vue`（百度关键词 section，「默认 headless」FormField 上方 ≈ 1500 行）
- Modify: `frontend/src/components/monitor/CookieManagerModal.vue`（移除 baidu 分支）

> 纯前端 UI 迁移，无新接口（复用 `POST /api/monitor/baidu/login` + `GET /api/monitor/baidu/login-status`，Task 1 修好后状态即正常）。无后端测试；用 `npm run build` 类型校验 + 手动验证。

- [ ] **Step 1: SettingsView 脚本区加登录态 state + 函数**

在 `SettingsView.vue` `<script setup>`（靠近 `confirmResetBaiduProfile` ≈ 683 行处）加：

```ts
// 百度账号登录态（从 CookieManagerModal 迁回设置页百度区）
const baiduLoginStatus = ref<{ logged_in: boolean; username: string | null }>({
  logged_in: false,
  username: null,
});
const baiduLoginBusy = ref(false);

async function refreshBaiduLoginStatus() {
  try {
    const r = await sidecar.client.get("/api/monitor/baidu/login-status");
    baiduLoginStatus.value = {
      logged_in: !!r.data?.logged_in,
      username: r.data?.username ?? null,
    };
  } catch {
    baiduLoginStatus.value = { logged_in: false, username: null };
  }
}

async function startBaiduLogin() {
  if (!(await confirmDialog(
    "会打开一个浏览器窗口，登录后 CSM 抓取任务自动用登录态访问。建议使用专用账号。",
    { title: baiduLoginStatus.value.logged_in ? "重新登录百度" : "登录百度", okLabel: "登录", kind: "info" },
  ))) return;
  baiduLoginBusy.value = true;
  try {
    const r = await sidecar.client.post("/api/monitor/baidu/login", null, { timeout: 660_000 });
    const status = r.data?.status;
    if (status === "success") toast.success("百度账号登录成功");
    else if (status === "cancelled") toast.info("登录已取消");
    else if (status === "timeout") toast.error("登录超时（窗口已关闭）");
    else toast.error(`登录失败：未知状态 ${status}`);
  } catch (e: any) {
    toast.error(`登录失败：${e.response?.data?.detail ?? e.message ?? "未知错误"}`);
  } finally {
    baiduLoginBusy.value = false;
    await refreshBaiduLoginStatus();
  }
}
```

确保 `confirmDialog` 已 import（`import { confirmDialog } from "@/composables/useConfirm";`），并在 baidu-scrape section 挂载时调用 `refreshBaiduLoginStatus()`（在该 section 的 onMounted/进入逻辑里加一次调用；若 SettingsView 用 tab 切换，放在切到百度 tab 时调）。

- [ ] **Step 2: SettingsView 模板 —— 「默认 headless」FormField 上方插入登录卡片**

在 `monitor.baidu_keyword.headless_default` 的 `FormField`（≈1503 行）**之前**插入：

```vue
              <FormField
                label="百度账号登录"
                hint="抓取任务用登录态访问百度，显著降低风控触发率。建议用专用账号。"
              >
                <div class="flex items-center gap-3">
                  <span
                    v-if="baiduLoginStatus.logged_in"
                    class="text-[12px]"
                    :style="{ color: 'var(--success, #16a34a)' }"
                  >已登录{{ baiduLoginStatus.username ? ` @${baiduLoginStatus.username}` : "" }}</span>
                  <span v-else class="text-[12px]" :style="{ color: 'var(--ink-3)' }">未登录</span>
                  <Btn variant="solid" small :disabled="baiduLoginBusy" @click="startBaiduLogin">
                    <Icon name="user" :size="12" />
                    <span>{{ baiduLoginStatus.logged_in ? "重新登录" : "登录百度" }}</span>
                  </Btn>
                </div>
              </FormField>
```

（`Btn` / `Icon` / `FormField` SettingsView 已在用，无需新 import。）

- [ ] **Step 3: CookieManagerModal 移除 baidu 分支**

`CookieManagerModal.vue` 删除：
- `PLATFORMS` 数组里 `{ value: "baidu", label: "百度" }` 这条（46-52 行）。
- 模板里 `<div v-if="platform === 'baidu'" ...>...</div>` 整块（372-408 行）。
- 脚本里 baidu 专属：`baiduLoginStatus` / `baiduLoginBusy` ref、`refreshBaiduLoginStatus`、`startBaiduLogin`（284-344 行），以及 `watch(props.open)`/`onMounted` 里的 `refreshBaiduLoginStatus()` 调用（267、278 行）。
- `loadCookies` 里 `if (platform.value === "baidu") {...}` 早返回块（191-195 行）——移除后默认 platform 不再含 baidu，无需特判。
- 把 `platform` 默认值确认仍为 `"zhihu_question"`（54 行，不变）。

- [ ] **Step 4: 类型校验 + 构建**

Run:
```bash
cd frontend && npm run build
```
Expected: exit 0（vue-tsc 无类型错误，vite 构建成功）。若 `baiduLoginStatus` 等在 CookieManagerModal 仍被模板引用会报错 —— 按报错清干净。

- [ ] **Step 5: 手动验证（需要 worktree dev）**

```bash
# 从 worktree 跑 dev（csm_core 取 worktree、含 Task1-4 修复）
cd D:/CSM/.claude/worktrees/lucid-leavitt-a30b7b ; ./scripts/dev.ps1
```
验证：设置 → 百度抓取（或百度关键词区）→「默认 headless」上方出现「百度账号登录」→ 点登录 → 登录后窗口自动关闭 → 状态显示「已登录」。Cookie 管理器平台下拉不再有「百度」。

- [ ] **Step 6: Commit**

```bash
git add frontend/src/views/SettingsView.vue frontend/src/components/monitor/CookieManagerModal.vue
git commit -m "feat(baidu): 登录入口从 Cookie 管理器迁到百度关键词设置（默认 headless 上方）"
```

---

## Self-Review 检查点（执行者跑完所有 task 后）

- [ ] 全量 baidu 相关测试通过：
```bash
PYTHONPATH="D:/CSM/.claude/worktrees/lucid-leavitt-a30b7b;D:/CSM/.claude/worktrees/lucid-leavitt-a30b7b/sidecar" python -m pytest sidecar/tests/test_baidu_login.py sidecar/tests/test_baidu_browser.py -v
```
- [ ] `cd frontend && npm run build` exit 0。
- [ ] 手动确认「登录后状态显示已登录」（核心验收）。
- [ ] `git status` 仅含本计划涉及的 6 个文件（+ 无 vite.config.*/package-lock.json 误改 —— 若 vue-tsc 改了 vite.config.* 或 npm 改了 lockfile，`git checkout --` 还原）。
