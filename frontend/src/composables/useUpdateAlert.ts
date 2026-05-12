/**
 * 「发现新版本」全局弹窗 —— 跟 useFailureAlert / useConfirm 同 pattern：
 * 单例 reactive state + Promise 命令式 API。
 *
 *   const choice = await updateAlert({ info, currentVersion });
 *   // choice: "update" | "cancel"
 *
 * 调用方（目前是 SettingsView.checkForUpdate）拿到 "update" 就去触发
 * /api/updater/download；modal 自己只负责呈现版本号、changelog、发布
 * 时间、文件大小四块信息 + 两个按钮。
 *
 * 下载流程的 SSE 进度条**不放在这个 modal 里** —— 它的责任只到"用户
 * 是否同意下载"。下载本身的进度展示走另一个 modal/toast，便于将来切换
 * 后台下载 + Notification 中心的形态。
 */
import { reactive } from "vue";

import type { UpdaterCheckResult } from "@/api/client";

type UpdateInfo = NonNullable<UpdaterCheckResult["info"]>;

interface UpdateRequest {
  info: UpdateInfo;
  currentVersion: string;
  resolve: (v: "update" | "cancel") => void;
}

interface UpdateState {
  open: boolean;
  info: UpdateInfo | null;
  currentVersion: string;
}

export const updateAlertState = reactive<UpdateState>({
  open: false,
  info: null,
  currentVersion: "",
});

const queue: UpdateRequest[] = [];
let current: UpdateRequest | null = null;

function showNext() {
  if (current || queue.length === 0) return;
  current = queue.shift()!;
  updateAlertState.info = current.info;
  updateAlertState.currentVersion = current.currentVersion;
  updateAlertState.open = true;
}

/** UpdateAvailableModal 点按钮后调，传 "update" 或 "cancel"。 */
export function resolveUpdate(value: "update" | "cancel") {
  if (!current) return;
  const c = current;
  current = null;
  updateAlertState.open = false;
  updateAlertState.info = null;
  c.resolve(value);
  Promise.resolve().then(showNext);
}

export interface UpdateAlertOptions {
  info: UpdateInfo;
  currentVersion: string;
}

export function updateAlert(
  opts: UpdateAlertOptions,
): Promise<"update" | "cancel"> {
  return new Promise<"update" | "cancel">((resolve) => {
    queue.push({
      info: opts.info,
      currentVersion: opts.currentVersion,
      resolve,
    });
    showNext();
  });
}
