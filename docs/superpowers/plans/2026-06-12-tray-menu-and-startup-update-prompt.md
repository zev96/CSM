# 托盘菜单清理（⑥）+ 启动更新弹窗（⑦）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ⑥ 精简系统托盘右键菜单（移除 "Content SEO Maker" 标题项 + 两个从未真正绑定的快捷键提示）；⑦ 应用启动时静默检查更新，有新版本自动弹出已有的 `UpdateAvailableModal`，并新增「跳过此版本」选项。

**Architecture:** ⑦ 的检查→下载→SSE→重启完整闭环目前**写死在** `SettingsView.checkForUpdate`（手动按钮触发）。本计划把它**抽取**成共享编排层 `useUpdateFlow.ts`（`runUpdateCheck({ silent })`），供 SettingsView（手动，silent=false，有 toast 反馈、忽略 skip）和 App.vue（启动，silent=true，无更新/失败静默、尊重 skip）共用。「跳过此版本」= 在 prompt 阶段加一个按钮 → `PromptChoice` 增加 `"skip"` → 编排层把该版本号写入 `localStorage` → 启动静默检查时若 latest 版本 == 已跳过版本则不弹（手动检查无视 skip）。⑥ 是 `tray.rs` 的纯删除/简化。

**Tech Stack:** Vue 3 `<script setup>`, Vitest（jsdom 提供 localStorage）, vue-tsc, Tauri 2（Rust, `tauri::menu`）。

---

## File Structure

| 文件 | 责任 | 动作 |
|---|---|---|
| `frontend/src-tauri/src/tray.rs` | 系统托盘菜单 | 改（⑥：删 header + 快捷键） |
| `frontend/src/composables/useUpdateFlow.ts` | 更新编排层（runUpdateCheck）+ skip 持久化纯函数 | **新建** |
| `frontend/src/composables/__tests__/useUpdateFlow.spec.ts` | skip 纯函数 + shouldAutoPrompt 单测 | **新建** |
| `frontend/src/composables/useUpdateAlert.ts` | 弹窗状态机 | 改（`PromptChoice` 加 `"skip"`） |
| `frontend/src/components/ui/UpdateAvailableModal.vue` | 弹窗 UI | 改（prompt 加「跳过此版本」按钮） |
| `frontend/src/views/SettingsView.vue` | 设置页（手动检查更新） | 改（`checkForUpdate` 瘦身为调 `runUpdateCheck`） |
| `frontend/src/App.vue` | 应用外壳 | 改（onMounted 启动静默检查） |

---

## Task 1: ⑥ 精简托盘菜单（tray.rs）

**Files:**
- Modify: `frontend/src-tauri/src/tray.rs`

当前菜单 = `[header("Content SEO Maker", disabled), sep1, show("显示主窗口", Ctrl+Shift+C), sep2, quit("退出 CSM", Ctrl+Q)]`。文件注释自承 accelerator「not wired yet」、纯提示。目标菜单 = `[show("显示主窗口"), sep, quit("退出 CSM")]`，无快捷键提示、无标题项。

- [ ] **Step 1: 删除 header MenuItem 定义**

删除这一段（约 line 26-35，含其上方注释）：
```rust
    // Disabled brand header — gives the menu a "title" so the user knows
    // which app this menu belongs to. `enabled=false` greys it out so it's
    // not click-able and reads as a label.
    let header = MenuItem::with_id(
        app,
        "header",
        "Content SEO Maker",
        false,
        None::<&str>,
    )?;
```

- [ ] **Step 2: 移除两个快捷键提示（accelerator → None）**

`show_item`（约 line 40-46）：把 `Some("Ctrl+Shift+C")` 改成 `None::<&str>`，并把注释收敛为一句。结果：
```rust
    // Show / hide the main window.
    let show_item = MenuItem::with_id(
        app,
        "show",
        "显示主窗口",
        true,
        None::<&str>,
    )?;
```

`quit_item`（约 line 51-57）：把 `Some("Ctrl+Q")` 改成 `None::<&str>`，注释收敛：
```rust
    // Quit — the only real way to shut the app down (window X minimises to tray).
    let quit_item = MenuItem::with_id(
        app,
        "quit",
        "退出 CSM",
        true,
        None::<&str>,
    )?;
```

- [ ] **Step 3: 收敛 separators 到一个，并从菜单移除 header**

把两个 separator 定义（约 line 59-60）合并为一个：
```rust
    let sep = PredefinedMenuItem::separator(app)?;
```
把菜单组装（约 line 62-65）改为：
```rust
    let menu = Menu::with_items(
        app,
        &[&show_item, &sep, &quit_item],
    )?;
```

- [ ] **Step 4: 清理 on_menu_event 的 header 分支**

删除 `on_menu_event` 里的 `"header"` 注释分支（约 line 86-88）——保留末尾的 `_ => {}` 兜底：
```rust
            _ => {}
```
（即删掉 `// "header" is disabled ...` 那两行注释，`_ => {}` 留着。）

- [ ] **Step 5: 更新文件头注释**

把文件头 doc 注释里描述菜单的部分（约 line 5、line 11-20 的 "Menu styling note"）更新为不再提 brand header / accelerator hints。具体：
- line 5 `Right-click the icon → context menu with: 显示主窗口 / 退出` 保持即可（已准确）。
- "Menu styling note" 段落里删掉 "a disabled brand header" 和 "accelerator hints" 的措辞，改为描述当前的极简菜单（显示主窗口 / 分隔符 / 退出）。

- [ ] **Step 6: 验证编译（best-effort）**

Run: `cd frontend/src-tauri && cargo check`
Expected: 编译通过、0 error（仅可能有无关 warning）。
注意：worktree 首次 `cargo check` 会编译 Tauri 依赖，可能较慢（数分钟）。若环境无法在合理时间内完成，至少确认改动是纯删除 + `Some(...)→None::<&str>`（无新符号、无类型变化），并在报告中说明 cargo check 未跑完、依赖 CI/release build 兜底。

- [ ] **Step 7: Commit**

```bash
git add frontend/src-tauri/src/tray.rs
git commit -m "feat(tauri): 精简托盘菜单 —— 移除 Content SEO Maker 标题项 + 两个未绑定的快捷键提示" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: ⑦核心 —— useUpdateFlow 编排层 + skip 持久化 + PromptChoice "skip"

**Files:**
- Modify: `frontend/src/composables/useUpdateAlert.ts`
- Create: `frontend/src/composables/useUpdateFlow.ts`
- Test: `frontend/src/composables/__tests__/useUpdateFlow.spec.ts`

- [ ] **Step 1: useUpdateAlert.ts —— PromptChoice 增加 "skip"**

把（约 line 35）：
```ts
export type PromptChoice = "update" | "cancel";
```
改为：
```ts
export type PromptChoice = "update" | "cancel" | "skip";
```

并更新 `resolvePrompt`（约 line 103-114）以处理 `"skip"`（与 cancel 一样关闭弹窗，但把 `"skip"` 透传给 `await ctrl.prompt`，持久化交给 useUpdateFlow）：
```ts
export function resolvePrompt(value: PromptChoice) {
  if (!current) return;
  const c = current;
  if (value === "update") {
    c.promptResolve("update");
    return;
  }
  // cancel / skip：都关闭弹窗 + 双 resolve（finalResolve 兜底，避免 awaitFinalChoice 永挂）。
  // "skip" 的版本持久化由调用方（useUpdateFlow）在拿到 prompt 结果后处理。
  c.promptResolve(value);
  c.finalResolve("cancel");
  closeAndReset();
}
```

- [ ] **Step 2: 写 useUpdateFlow 的失败测试（skip 纯函数 + shouldAutoPrompt）**

Create `frontend/src/composables/__tests__/useUpdateFlow.spec.ts`:
```ts
import { describe, it, expect, beforeEach } from "vitest";
import {
  getSkippedVersion,
  markVersionSkipped,
  shouldAutoPrompt,
} from "../useUpdateFlow";

beforeEach(() => {
  localStorage.clear();
});

describe("skip-version persistence", () => {
  it("returns empty string when nothing skipped", () => {
    expect(getSkippedVersion()).toBe("");
  });
  it("persists then reads back a skipped version", () => {
    markVersionSkipped("1.2.3");
    expect(getSkippedVersion()).toBe("1.2.3");
  });
  it("overwrites a previously skipped version", () => {
    markVersionSkipped("1.2.3");
    markVersionSkipped("1.3.0");
    expect(getSkippedVersion()).toBe("1.3.0");
  });
});

describe("shouldAutoPrompt", () => {
  it("prompts when latest differs from skipped", () => {
    expect(shouldAutoPrompt("1.2.4", "1.2.3")).toBe(true);
  });
  it("suppresses when latest equals skipped", () => {
    expect(shouldAutoPrompt("1.2.3", "1.2.3")).toBe(false);
  });
  it("prompts when nothing is skipped", () => {
    expect(shouldAutoPrompt("1.2.3", "")).toBe(true);
  });
});
```

- [ ] **Step 3: 运行测试确认失败**

Run: `cd frontend && npx vitest run src/composables/__tests__/useUpdateFlow.spec.ts`
Expected: FAIL — "Failed to resolve import ../useUpdateFlow"。

- [ ] **Step 4: 写 useUpdateFlow.ts**

Create `frontend/src/composables/useUpdateFlow.ts`. 这是把 `SettingsView.checkForUpdate` 的完整闭环抽取出来并参数化 `silent` + 加 skip gate。逐行对照保留了原有的微妙行为（尤其 `downloadedPath` 本地捕获的注释）。
```ts
/**
 * 更新检查编排层 —— check → prompt → download(SSE) → ready → install_and_restart
 * 的完整闭环，供「设置页手动检查」和「启动静默检查」共用。
 *
 *   - silent=false（设置页手动）：无更新 / 出错都 toast 反馈；忽略「跳过此版本」。
 *   - silent=true （启动自动）  ：无更新 / 检查出错 静默；尊重「跳过此版本」。
 *
 * 「跳过此版本」：prompt 阶段用户点「跳过此版本」→ resolvePrompt("skip")
 * → 这里把该版本号写入 localStorage；下次**静默**检查若 latest==skipped 则不弹。
 * 用户在设置页**手动**检查时无视 skip（主动要看就让他看）。
 */
import { useToast } from "./useToast";

const SKIP_KEY = "csm.update.skip.v1";

/** 读「已跳过的版本号」；无 / 读失败 → 空串。 */
export function getSkippedVersion(): string {
  try {
    return localStorage.getItem(SKIP_KEY) ?? "";
  } catch {
    return "";
  }
}

/** 记录「跳过此版本」。 */
export function markVersionSkipped(version: string): void {
  try {
    localStorage.setItem(SKIP_KEY, version);
  } catch {
    /* private mode — 跳过持久化失败就当没跳过，下次仍会弹，可接受 */
  }
}

/** 自动检查时是否应该弹窗：仅当 latest 版本不等于已跳过的版本。 */
export function shouldAutoPrompt(latestVersion: string, skippedVersion: string): boolean {
  return latestVersion !== skippedVersion;
}

export async function runUpdateCheck(opts: { silent?: boolean } = {}): Promise<void> {
  const silent = opts.silent ?? false;
  const toast = useToast();
  try {
    const { updaterCheck, updaterDownload, subscribe } = await import("@/api/client");
    const {
      updateAlert,
      transitionToDownloading,
      updateProgress,
      transitionToReady,
      transitionToError,
    } = await import("./useUpdateAlert");

    let r;
    try {
      r = await updaterCheck();
    } catch (e: any) {
      if (!silent) {
        toast.error(`检查更新失败：${e?.response?.data?.detail ?? e?.message ?? e}`);
      }
      return;
    }
    if (r.error) {
      if (!silent) toast.warn(`更新检查未完成：${r.error}`);
      return;
    }
    if (!r.has_update || !r.info) {
      if (!silent) toast.info(`已是最新版本（${r.current_version}）`);
      return;
    }
    // 启动静默检查尊重「跳过此版本」；手动检查无视 skip。
    if (silent && !shouldAutoPrompt(r.info.version, getSkippedVersion())) {
      return;
    }

    const ctrl = updateAlert({
      info: r.info,
      currentVersion: r.current_version,
    });
    const decision = await ctrl.prompt;
    if (decision === "skip") {
      markVersionSkipped(r.info.version);
      return;
    }
    if (decision !== "update") return;

    // ── 触发下载 ──────────────────────────────────────────────
    let job: { job_id: string; stream_url: string };
    try {
      job = await updaterDownload(r.info.zip_url, r.info.expected_sha256);
    } catch (e: any) {
      transitionToError(
        `启动下载失败：${e?.response?.data?.detail ?? e?.message ?? e}`,
      );
      await ctrl.final;
      return;
    }

    transitionToDownloading();

    // ⚠ downloadedPath 必须**本地捕获**：resolveFinal("restart") 会同步
    // closeAndReset() 清空 updateAlertState.targetPath，等下面 await ctrl.final
    // 醒来时 state 已空。本地变量不受 reset 影响。
    let resolved = false; // 防止 done + cancel 抢双 finalResolve
    let downloadedPath = "";
    const stop = subscribe(job.stream_url, {
      progress: (d: any) => {
        if (resolved) return;
        updateProgress(d.done ?? 0, d.total ?? 0, d.percent ?? 0);
      },
      done: (d: any) => {
        if (resolved) return;
        resolved = true;
        downloadedPath = d.target ?? "";
        transitionToReady(downloadedPath);
        stop();
      },
      error: (d: any) => {
        if (resolved) return;
        resolved = true;
        transitionToError(d.error ?? "下载失败（未知原因）");
        stop();
      },
    });

    const finalChoice = await ctrl.final;
    stop(); // 兜底：取消下载时 SSE 还没收到终止事件，主动断开

    if (finalChoice === "restart") {
      // 用户已主动走到这一步 —— 安装阶段的反馈不受 silent 抑制。
      try {
        const { invoke } = await import("@tauri-apps/api/core");
        await invoke("install_and_restart", { zipPath: downloadedPath });
        toast.info("正在准备安装更新…");
      } catch (e: any) {
        const msg = String(e?.message ?? e ?? "");
        if (msg.includes("updater_not_found")) {
          toast.warn(
            "dev 环境下没有 updater.exe，无法测试安装重启流程。请打 release 包验证。",
          );
        } else {
          toast.error(`启动安装失败：${msg}`);
        }
      }
    }
  } catch (e: any) {
    if (!silent) {
      toast.error(`检查更新失败：${e?.response?.data?.detail ?? e?.message ?? e}`);
    }
  }
}
```

- [ ] **Step 5: 运行测试确认通过**

Run: `cd frontend && npx vitest run src/composables/__tests__/useUpdateFlow.spec.ts`
Expected: PASS（6 个测试）。

- [ ] **Step 6: 类型检查**

Run: `cd frontend && npx vue-tsc -b`
Expected: 0 error。（若 emit 了 `vite.config.js`/`*.d.ts` 杂散产物，`git checkout -- frontend/vite.config.js` 还原。）

- [ ] **Step 7: Commit**

```bash
git add frontend/src/composables/useUpdateFlow.ts frontend/src/composables/__tests__/useUpdateFlow.spec.ts frontend/src/composables/useUpdateAlert.ts
git commit -m "feat(frontend): 抽取 useUpdateFlow 编排层（silent + 跳过此版本），PromptChoice 加 skip" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: ⑦接线 —— Modal 跳过按钮 + SettingsView 瘦身 + App.vue 启动检查

**Files:**
- Modify: `frontend/src/components/ui/UpdateAvailableModal.vue`
- Modify: `frontend/src/views/SettingsView.vue`
- Modify: `frontend/src/App.vue`

- [ ] **Step 1: UpdateAvailableModal —— prompt 阶段加「跳过此版本」按钮**

在 `<script setup>` 里加一个 handler（在 `onPromptUpdate` 附近，约 line 35-37 后）：
```ts
function onPromptSkip() {
  resolvePrompt("skip");
}
```

把 footer 里 prompt 阶段的按钮组（约 line 316-327）改为（在最左加「跳过此版本」ghost 按钮）：
```vue
      <template v-if="updateAlertState.phase === 'prompt'">
        <Btn variant="ghost" small @click="onPromptSkip">跳过此版本</Btn>
        <Btn variant="ghost" small @click="onPromptCancel">取消</Btn>
        <Btn
          variant="solid"
          small
          :disabled="!canUpdate"
          @click="onPromptUpdate"
        >
          <Icon name="download" :size="13" />
          <span>立即更新</span>
        </Btn>
      </template>
```

- [ ] **Step 2: SettingsView —— checkForUpdate 瘦身为调 runUpdateCheck**

把 `checkForUpdate` 整个函数体（约 line 579-685，从 `async function checkForUpdate()` 到其闭合 `}`）替换为：
```ts
async function checkForUpdate() {
  if (updaterChecking.value) return;
  updaterChecking.value = true;
  try {
    const { runUpdateCheck } = await import("@/composables/useUpdateFlow");
    await runUpdateCheck({ silent: false });
  } finally {
    updaterChecking.value = false;
  }
}
```
保留上方 `const updaterChecking = ref(false);`（约 line 578）——按钮 `:disabled="updaterChecking"` 仍用它。可一并精简上方那段描述旧闭环的长注释（约 line 569-577）为一句「检查更新：委托 useUpdateFlow.runUpdateCheck（手动模式，有 toast 反馈）」。

检查该文件是否还残留对 `updaterCheck`/`updaterDownload`/`subscribe`/`updateAlert`/`transitionTo*`/`updateProgress` 的 import 或用法——这些原本就是函数内 `await import(...)` 动态引入的（不是顶层 import），随函数体删除即可消失。删除后用 `rg` 确认 SettingsView 不再引用它们（见 Step 4）。

- [ ] **Step 3: App.vue —— onMounted 末尾启动静默检查**

在 `onMounted` 内、`configReady.value = true;`（约 line 128）之后、`onMounted` 闭合 `});`（约 line 129）之前，插入：
```ts
  // 启动后静默检查更新：有新版本自动弹 UpdateAvailableModal；已「跳过」的版本不弹。
  // fire-and-forget —— 不阻塞 UI；检查失败静默（仅设置页手动检查才提示）。
  import("./composables/useUpdateFlow")
    .then(({ runUpdateCheck }) => runUpdateCheck({ silent: true }))
    .catch(() => {});
```

- [ ] **Step 4: 验证**

Run: `cd frontend && rg -n "updaterDownload|transitionToDownloading|updateAlert\(" src/views/SettingsView.vue`
Expected: 无匹配（旧闭环逻辑已随函数体移除）。

Run: `cd frontend && npx vue-tsc -b`
Expected: 0 error。（必要时 `git checkout -- frontend/vite.config.js`。）

Run: `cd frontend && npx vitest run`
Expected: 全部通过（基线 + useUpdateFlow 的 6 个新测试）。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/ui/UpdateAvailableModal.vue frontend/src/views/SettingsView.vue frontend/src/App.vue
git commit -m "feat(frontend): 启动静默检查更新 + 弹窗「跳过此版本」；SettingsView 手动检查改走 useUpdateFlow" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: 收尾验证 + push + PR

- [ ] **Step 1: 全量验证**

Run: `cd frontend && npx vue-tsc -b && npx vitest run`
Expected: 0 type error；测试全过。跑完若有 `vite.config.js`/`*.d.ts` 杂散产物则还原。

- [ ] **Step 2: 确认 lockfile 干净**

Run: `git status --porcelain frontend/package-lock.json`
Expected: 无输出。

- [ ] **Step 3: push + 开 PR**

```bash
git push -u origin claude/tray-update-prompt
gh pr create --base main --title "feat: 托盘菜单精简（⑥）+ 启动更新弹窗与跳过此版本（⑦）" --body "见 docs/superpowers/plans/2026-06-12-tray-menu-and-startup-update-prompt.md。⑥ tray.rs 删标题+快捷键提示；⑦ 抽取 useUpdateFlow 供启动静默检查 + 设置手动检查共用，新增「跳过此版本」。" --base main
```
返回 PR URL，停在 pending 等网页 merge。

- [ ] **Step 4: 用户验证（无法自动化的部分）**

- ⑥：release 包里右键托盘图标，确认菜单只有「显示主窗口 / 退出 CSM」、无快捷键文字、无标题项。
- ⑦：dev 或 release 启动应用，若有新版本应自动弹窗；点「跳过此版本」后重启应用应不再自动弹该版本；设置页手动「检查更新」仍应弹（无视 skip）。dev 环境 install 阶段会提示「没有 updater.exe」属正常。

---

## Self-Review

**1. Spec coverage:**
- ⑥ 删除快捷键（Ctrl+Shift+C / Ctrl+Q）→ Task 1 Step 2 ✓
- ⑥ 删除 "Content SEO Maker" 标题 → Task 1 Step 1+3 ✓
- ⑦ 启动时检测新版本弹窗 → Task 2（runUpdateCheck silent）+ Task 3 Step 3（App.vue 接线）✓
- ⑦ 「跳过此版本」 → Task 2（PromptChoice skip + 持久化）+ Task 3 Step 1（按钮）✓
- DRY：手动 + 启动共用 runUpdateCheck，不重复闭环 ✓

**2. Placeholder scan:** 无 TBD/"类似上文"；每步给了完整代码或精确 before→after。✓

**3. Type consistency:** `PromptChoice` 加 `"skip"`（Task 2 Step 1）→ `runUpdateCheck` 内 `decision === "skip"`（Task 2 Step 4）→ Modal `resolvePrompt("skip")`（Task 3 Step 1）一致。`runUpdateCheck({ silent })` 签名在定义（Task 2）、SettingsView 调用（Task 3 Step 2）、App.vue 调用（Task 3 Step 3）一致。`getSkippedVersion`/`markVersionSkipped`/`shouldAutoPrompt` 在定义、测试、runUpdateCheck 使用处签名一致。✓

**4. 行为保真:** runUpdateCheck 逐行搬运 checkForUpdate（含 `downloadedPath` 本地捕获、`resolved` 双 resolve 防护、SSE stop 兜底、dev updater_not_found 分支），仅新增 `silent` gate（只作用于「检查阶段」的 toast 与 skip 判断，不影响用户交互后的下载/安装反馈）+ skip 判断。SettingsView 行为不变（手动 silent=false 等价原逻辑）。
