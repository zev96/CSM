# 百度验证码 UX 优化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development（或 executing-plans）。Steps use `- [ ]`.

**Goal:** 百度采集触发图形验证码时，浏览器自动可见（有头+屏外 → 验证码时移屏幕中央）+ 三管齐下强通知（系统通知 + app toast + 任务栏闪），用户解完自动继续采集。

**Architecture:** 复用现有软着陆机制（`_try_human_solve` + `surface_window` + `needs_captcha` SSE + `useSystemNotify`）。核心修复百度 headless（无头 → 有头屏外）让 `surface_window` 生效；三处增强：窗口居中、Tauri 任务栏闪、app 内 toast。

**Tech Stack:** Python（csm_core / patchright CDP）, Vue 3（Pinia store）, Rust（Tauri 2 command）, pytest, vue-tsc。

**调研结论（功能 ~95% 已有）：** 前端 `needs_captcha` handler（`monitorStatus.ts:276`）已发真系统通知（`useSystemNotify` → Tauri notification plugin）；`surface_window` CDP 移窗 + `bring_to_front` 已在；`detect_risk` 5 层检测已在；`_try_human_solve` 软着陆 + 300s 轮询 + RiskControlException 断点 resume 已在。**仅缺**：①百度恒无头（surface_window 无窗口可移）②窗口非居中 ③无任务栏闪 ④无 app 内提醒。

**环境（跑 Python 测试）：** worktree 用主仓 venv + cwd 覆盖到 worktree 代码：
`cd D:/CSM/.claude/worktrees/focused-varahamihira-60097d && D:/CSM/.venv/Scripts/python.exe -m pytest <path> -v`

---

## File Structure
- `csm_core/monitor/platforms/baidu_keyword.py` — 百度恒有头+屏外（headless 修复，Task 1）
- `csm_core/browser_infra/window_util.py` — `surface_window` 居中 + `_center_bounds` 纯函数（Task 2）
- `tests/core/browser_infra/test_window_util.py` — `_center_bounds` TDD（文件已存在，追加）
- `frontend/src-tauri/src/lib.rs` — 新 `request_window_attention` command（Task 3）
- `frontend/src/stores/monitorStatus.ts` — `needs_captcha` handler 加 toast + invoke 任务栏闪（Task 3）

---

## Task 1: 百度恒有头 + 屏外（核心修复）

**Files:** Modify `csm_core/monitor/platforms/baidu_keyword.py`

无头时 `surface_window` 没有窗口可移 → 验证码永远看不到。改成恒有头（屏外参数 `offscreen_args` 在有头时自动生效，平时窗口在 -32000 不打扰）。

- [ ] **Step 1 — 改 `_headless_default`**
`baidu_keyword.py:709`：`self._headless_default = True` → `self._headless_default = False`

- [ ] **Step 2 — 强制 `effective_headless = False`**
`baidu_keyword.py:981-982`，把：
```python
        headless = bool(cfg.get("headless", self._headless_default))
        effective_headless = False if use_native else headless
```
改成：
```python
        # 百度恒有头 + 屏外：验证码必须可见可操作（无头无窗口无法解）。屏外参数
        # offscreen_args 在有头时自动生效，平时窗口停在 -32000 不打扰；有头真窗口
        # 反爬指纹也更干净，可能降低验证码触发。native 模式本就强制有头。
        effective_headless = False
```

- [ ] **Step 3 — 验证无悬空 headless 引用**
Run: `grep -n "effective_headless\|cfg.get(\"headless\")\|_headless_default" csm_core/monitor/platforms/baidu_keyword.py`
Expected: `effective_headless` 恒 False；无引用已删的 `headless` 局部变量（若 grep 出残留引用，改回该处用 `effective_headless`）。`_headless_default = False` 仅作语义默认。

- [ ] **Step 4 — Commit**
```bash
git add csm_core/monitor/platforms/baidu_keyword.py
git commit -m "fix(monitor): 百度恒有头+屏外 —— 无头模式下 surface_window 无窗口可移，验证码看不到"
```

**验证（真机 QA，无法自动化）：** 百度跑监控 → 平时无窗口打扰（屏外）；触发验证码时窗口出现（居中见 Task 2）。

---

## Task 2: 验证码窗口移屏幕中央（TDD 纯函数 + surface_window）

**Files:** Modify `csm_core/browser_infra/window_util.py`; Test `tests/core/browser_infra/test_window_util.py`

`surface_window` 当前固定 `(80,80)`。改成屏幕居中。提取 `_center_bounds` 纯函数做 TDD（CDP 调用部分无法单元测，靠真机）。

- [ ] **Step 1 — 写失败测试**（追加到 `tests/core/browser_infra/test_window_util.py`）
```python
from csm_core.browser_infra.window_util import _center_bounds


def test_center_bounds_centers_window():
    left, top = _center_bounds(screen_w=1920, screen_h=1080, win_w=1100, win_h=800)
    assert left == (1920 - 1100) // 2  # 410
    assert top == (1080 - 800) // 2    # 140


def test_center_bounds_clamps_when_window_larger_than_screen():
    # 窗口比屏幕大 → 不出现负坐标
    left, top = _center_bounds(screen_w=800, screen_h=600, win_w=1100, win_h=800)
    assert left == 0
    assert top == 0
```

- [ ] **Step 2 — 跑测试确认 fail**
Run: `cd D:/CSM/.claude/worktrees/focused-varahamihira-60097d && D:/CSM/.venv/Scripts/python.exe -m pytest tests/core/browser_infra/test_window_util.py -k center_bounds -v`
Expected: FAIL（`_center_bounds` 不存在，ImportError）。

- [ ] **Step 3 — 实现 `_center_bounds`**（window_util.py 加，放在 `surface_window` 之前）
```python
def _center_bounds(screen_w: int, screen_h: int, win_w: int, win_h: int) -> tuple[int, int]:
    """屏幕居中的窗口左上角坐标；窗口比屏大时 clamp 到 0，不出负坐标。"""
    left = max(0, (screen_w - win_w) // 2)
    top = max(0, (screen_h - win_h) // 2)
    return left, top
```

- [ ] **Step 4 — 跑测试确认 pass**
Run: 同 Step 2
Expected: PASS（2 passed）。

- [ ] **Step 5 — surface_window 改用居中**（替换现有 `surface_window` 里固定 `(80,80,1100,800)` 的 bounds 计算；保留原 try/except 容错 + `logger.warning` + `page.bring_to_front()`）
```python
def surface_window(page: Any) -> None:
    """把（屏外的）浏览器窗口移到屏幕中央并尽力前置，供用户解验证码。"""
    win_w, win_h = 1100, 800
    try:
        screen = page.evaluate("({w: screen.availWidth, h: screen.availHeight})")
        left, top = _center_bounds(int(screen["w"]), int(screen["h"]), win_w, win_h)
    except Exception:
        left, top = 80, 80  # 取屏幕尺寸失败 → 退回固定左上角
    try:
        cdp, wid = _window_id(page)
        cdp.send(
            "Browser.setWindowBounds",
            {"windowId": wid, "bounds": {"left": left, "top": top, "width": win_w, "height": win_h, "windowState": "normal"}},
        )
        page.bring_to_front()
    except Exception as e:  # noqa: BLE001
        logger.warning("surface_window failed: %s", e)
```

- [ ] **Step 6 — 跑全 window_util 测试 + commit**
Run: `cd D:/CSM/.claude/worktrees/focused-varahamihira-60097d && D:/CSM/.venv/Scripts/python.exe -m pytest tests/core/browser_infra/test_window_util.py -v`
Expected: 全 PASS。
```bash
git add csm_core/browser_infra/window_util.py tests/core/browser_infra/test_window_util.py
git commit -m "feat(monitor): 验证码窗口移屏幕中央（_center_bounds TDD + surface_window page.evaluate 取屏幕尺寸，失败回退 80,80）"
```

---

## Task 3: 任务栏闪烁 + app 内提醒（Tauri command + needs_captcha handler）

**Files:** Modify `frontend/src-tauri/src/lib.rs`; Modify `frontend/src/stores/monitorStatus.ts`

现有 `needs_captcha` handler 已发系统通知。增强两点：app 内 toast（你在看 app 时）+ 任务栏闪（你在别处时）。

- [ ] **Step 1 — Rust command**（lib.rs，参考现有 `sidecar::get_sidecar` / `updater::install_and_restart` 模式）
先确认主窗口 label：`grep -n "label\|WebviewWindow\|get_webview_window" frontend/src-tauri/src/*.rs frontend/src-tauri/tauri.conf.json`（Tauri 2 默认主窗口 label 常为 `"main"`；以实际为准）。
加 command：
```rust
#[tauri::command]
fn request_window_attention(app: tauri::AppHandle) -> Result<(), String> {
    use tauri::{Manager, window::UserAttentionType};
    let win = app
        .get_webview_window("main")
        .ok_or_else(|| "main window not found".to_string())?;
    win.request_user_attention(Some(UserAttentionType::Critical))
        .map_err(|e| e.to_string())?;
    let _ = win.set_focus(); // best-effort 前置；Windows 抢焦点受限时退化为任务栏闪
    Ok(())
}
```
注册（lib.rs:53-56 的 `invoke_handler`）：
```rust
        .invoke_handler(tauri::generate_handler![
            sidecar::get_sidecar,
            updater::install_and_restart,
            request_window_attention,
        ])
```

- [ ] **Step 2 — 前端 needs_captcha handler 增强**（`monitorStatus.ts:276-282`）
```typescript
      needs_captcha: (d: any) => {
        if (typeof d.task_id === "number" && d.task_id > 0) _setPhase(d.task_id, "captcha");
        const kw = typeof d.keyword === "string" ? d.keyword : "";
        // ① 系统通知（已有）
        void _notify?.("CSM 百度监控", `需要人工解验证码（关键词：${kw}），浏览器已弹出`);
        // ② app 内醒目提醒（toast 已在 store init）
        toast.warn(`需要人工解验证码（${kw}）—— 浏览器已弹到屏幕中央，请去操作`, { ttl: 10000 });
        // ③ 任务栏闪 + 尽力前置 app（best-effort，非 Tauri 环境静默跳过）
        void import("@tauri-apps/api/core")
          .then(({ invoke }) => invoke("request_window_attention"))
          .catch(() => {});
      },
```
（确认 `toast.warn` 签名支持 `{ ttl }` —— 见 `useToast.ts`；若不支持改成 `toast.warn(msg)`。）

- [ ] **Step 3 — 前端类型检查**
Run: `cd frontend && npx vue-tsc -b`（跑完 `git checkout -- vite.config.js` 还原 if emitted）
Expected: 0 errors。（Rust 编译在 Task 4 / 真机 tauri build 验证。）

- [ ] **Step 4 — Commit**
```bash
git add frontend/src-tauri/src/lib.rs frontend/src/stores/monitorStatus.ts
git commit -m "feat(monitor): 验证码 needs_captcha 增强 —— 任务栏闪(request_user_attention) + app 内 toast 提醒"
```

---

## Task 4: 收尾验证 + PR

- [ ] **Step 1 — 全量验证**
- Python：`cd <worktree> && D:/CSM/.venv/Scripts/python.exe -m pytest tests/core/browser_infra/ -v`（window_util 全绿）
- 前端：`cd frontend && npx vue-tsc -b`（0）+ `npx vitest run`（136 passed）；还原杂散产物（vite.config.js）。
- `git status` 确认无杂散 untracked（勿提交 run-test-desktop.bat 等本地启动器）。
- [ ] **Step 2 — commit plan**（`docs/superpowers/plans/2026-06-15-baidu-captcha-ux.md`）+ spec 已提交。
- [ ] **Step 3 — final review**（origin/main..HEAD）：百度 `effective_headless` 恒 False 无悬空变量、`_center_bounds` 正确 + surface_window 有 fallback、Tauri command 已注册且 window label 正确、needs_captcha handler 三通知齐全、无回归。
- [ ] **Step 4 — push + PR**
```bash
git push -u origin claude/baidu-captcha-ux
gh pr create --base main --title "feat(monitor): 百度验证码 UX —— 有头屏外 + 窗口居中 + 三管齐下通知" --body "见 docs/superpowers/plans/2026-06-15-baidu-captcha-ux.md。复用现有软着陆机制，核心修复百度无头（→ 有头屏外）让 surface_window 生效，增强窗口居中 + 任务栏闪 + app toast。"
```
返回 URL 停 pending。
- [ ] **Step 5 — 真机 QA（关键，无法自动化）**：
  - 百度跑监控 → 平时**无窗口打扰**（屏外有头）
  - 触发验证码 → 浏览器**居中弹出** + **系统通知** + **app toast** + **任务栏闪烁**
  - 解完验证码 → **自动继续**采集该关键词
  - 超时 300s → 任务暂停可 resume（现有）

---

## Self-Review
- **Spec 覆盖**：①有头屏外=Task1 ②窗口居中=Task2 ③系统通知=已有(确认) ④app提醒=Task3 ⑤任务栏闪=Task3 ⑥解验证流程=复用现有。✓
- **范围**：headed+居中聚焦百度（Task1/2）；通知层（toast+任务栏闪）通用于所有 needs_captcha（Task3 在 store handler，与平台无关）。✓
- **可测性**：仅 `_center_bounds` 可 TDD（Task2）；headless/CDP/Rust/Tauri/浏览器均靠真机 QA（已诚实标注 Step 5）。
- **4 个原 spec 未知已解**：①系统通知=前端 SSE→useSystemNotify 路径已有（无需动后端 _notify）②request_user_attention=Tauri command（Task3）③OS 置顶=不做（patchright 不暴露 HWND，任务栏闪走 Tauri 足够）④居中=page.evaluate screen size（Task2）。
- **风险**：百度恒有头多一个屏外 Chromium 进程（串行单实例，可控）；Windows 抢焦点受限 → 任务栏闪 + 通知兜底。
