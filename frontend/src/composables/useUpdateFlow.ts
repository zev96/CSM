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
import type { UpdaterCheckResult } from "@/api/client";
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

    let r: UpdaterCheckResult;
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
    // 即使 silent 也留 console 痕迹，方便排查（如动态 import 失败这种静默不弹的场景）。
    console.error("[useUpdateFlow] 更新检查未预期出错:", e);
    if (!silent) {
      toast.error(`检查更新失败：${e?.response?.data?.detail ?? e?.message ?? e}`);
    }
  }
}
