/**
 * 「发现新版本」全局弹窗 —— 状态机版（prompt → downloading → ready / error）。
 *
 * 因为整个流程要弹**两次决策**（先问"要不要下载"，下完再问"要不要重启"），
 * 单一 Promise 不够用 —— Promise 只能 resolve 一次。这里拆成两个 awaitable：
 *
 *   ┌─ prompt 阶段 ───────────────────────────────┐
 *   │ const decision = await updateAlert(opts);   │
 *   │ // decision: "update" | "cancel"            │
 *   └─────────────────────────────────────────────┘
 *
 *   ┌─ downloading 阶段（调用方驱动）─────────────────────┐
 *   │ transitionToDownloading();                          │
 *   │ updateProgress(done, total, percent); // SSE 喂     │
 *   │ // 完成时 transitionToReady(targetPath)             │
 *   │ // 失败时 transitionToError(msg)                    │
 *   └─────────────────────────────────────────────────────┘
 *
 *   ┌─ ready / error 阶段 ──────────────────────────────────┐
 *   │ const finalChoice = await waitForFinalChoice();       │
 *   │ // "restart" | "cancel"                               │
 *   └───────────────────────────────────────────────────────┘
 *
 * 调用方拿到 "restart" 后调 Tauri install_and_restart 命令。
 */
import { reactive } from "vue";

import type { UpdaterCheckResult } from "@/api/client";

type UpdateInfo = NonNullable<UpdaterCheckResult["info"]>;

export type UpdatePhase = "prompt" | "downloading" | "ready" | "error";

/** prompt 阶段的决策。 */
export type PromptChoice = "update" | "cancel" | "skip";

/** ready / error 阶段的决策。 */
export type FinalChoice = "restart" | "cancel";

interface UpdateRequest {
  info: UpdateInfo;
  currentVersion: string;
  promptResolve: (v: PromptChoice) => void;
  finalResolve: (v: FinalChoice) => void;
}

interface UpdateState {
  open: boolean;
  phase: UpdatePhase;
  info: UpdateInfo | null;
  currentVersion: string;
  /** 已下载字节数 / 总字节数 / 百分比 —— downloading 阶段实时刷新。 */
  progress: { done: number; total: number; percent: number };
  /** 下载完成后的 zip 本地路径，install_and_restart 要用。 */
  targetPath: string;
  /** error phase 的错误文本。 */
  errorMsg: string;
}

export const updateAlertState = reactive<UpdateState>({
  open: false,
  phase: "prompt",
  info: null,
  currentVersion: "",
  progress: { done: 0, total: 0, percent: 0 },
  targetPath: "",
  errorMsg: "",
});

const queue: UpdateRequest[] = [];
let current: UpdateRequest | null = null;

function showNext() {
  if (current || queue.length === 0) return;
  current = queue.shift()!;
  updateAlertState.info = current.info;
  updateAlertState.currentVersion = current.currentVersion;
  updateAlertState.phase = "prompt";
  updateAlertState.progress = { done: 0, total: 0, percent: 0 };
  updateAlertState.targetPath = "";
  updateAlertState.errorMsg = "";
  updateAlertState.open = true;
}

/** 关闭弹窗 + 复位 state + 把当前请求清空。 */
function closeAndReset() {
  current = null;
  updateAlertState.open = false;
  updateAlertState.phase = "prompt";
  updateAlertState.info = null;
  updateAlertState.progress = { done: 0, total: 0, percent: 0 };
  updateAlertState.targetPath = "";
  updateAlertState.errorMsg = "";
  Promise.resolve().then(showNext);
}

/**
 * 解 prompt 阶段决策。Modal 在 phase=prompt 时调。
 *   - "update":  弹窗不关，调用方接管驱动后续 phase
 *   - "cancel":  关闭 + reset；finalResolve 也喂个 "cancel" 保证调用方
 *                的 awaitFinalChoice 不会永远挂着
 */
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

/**
 * 解 ready / error 阶段决策。Modal 在 phase=ready 或 phase=error 时调。
 * 也用于 downloading 阶段的"取消下载"按钮 —— 这种场景下 promptResolve
 * 已经在前面收到了 "update"，所以只需要喂 finalResolve。
 */
export function resolveFinal(value: FinalChoice) {
  if (!current) return;
  current.finalResolve(value);
  closeAndReset();
}

// ── 状态机 transition（供调用方驱动）─────────────────────────────────

export function transitionToDownloading() {
  if (!current) return;
  updateAlertState.phase = "downloading";
  updateAlertState.progress = { done: 0, total: 0, percent: 0 };
  updateAlertState.errorMsg = "";
}

export function updateProgress(done: number, total: number, percent: number) {
  if (!current) return;
  updateAlertState.progress = { done, total, percent };
}

export function transitionToReady(targetPath: string) {
  if (!current) return;
  updateAlertState.phase = "ready";
  updateAlertState.targetPath = targetPath;
  updateAlertState.progress.percent = 100;
}

export function transitionToError(msg: string) {
  if (!current) return;
  updateAlertState.phase = "error";
  updateAlertState.errorMsg = msg;
}

export interface UpdateAlertOptions {
  info: UpdateInfo;
  currentVersion: string;
}

/** 控制器：暴露 prompt + final 两个 await 点。 */
export interface UpdateAlertController {
  /** prompt 阶段决策；不 await final 也会被 "cancel" 兜底 resolve。 */
  prompt: Promise<PromptChoice>;
  /** ready / error / downloading 阶段的最终决策。 */
  final: Promise<FinalChoice>;
}

export function updateAlert(
  opts: UpdateAlertOptions,
): UpdateAlertController {
  let promptResolve!: (v: PromptChoice) => void;
  let finalResolve!: (v: FinalChoice) => void;
  const prompt = new Promise<PromptChoice>((r) => {
    promptResolve = r;
  });
  const final = new Promise<FinalChoice>((r) => {
    finalResolve = r;
  });
  queue.push({
    info: opts.info,
    currentVersion: opts.currentVersion,
    promptResolve,
    finalResolve,
  });
  showNext();
  return { prompt, final };
}
