<script setup lang="ts">
/**
 * 「发现新版本」弹窗 —— 状态机式（prompt → downloading → ready / error）。
 *
 * 4 个 phase 共用同一个外壳，主区内容（changelog / 进度条 / 完成提示 /
 * 错误信息）切换；底栏按钮也跟 phase 变。
 *
 *   prompt      标题 + 元数据卡 + changelog + [取消][立即更新]
 *   downloading 标题 + 元数据卡 + 进度条     + [取消下载]
 *   ready       标题 + 元数据卡 + 完成提示   + [稍后][立即重启]
 *   error       红色标题 + 错误信息          + [关闭]
 *
 * sha256 缺失时（manifest.json 拿不到）prompt 阶段禁用「立即更新」按钮，
 * 鼠标 hover 提示原因。downloading / ready / error 阶段 ESC + 点遮罩
 * 都不再关闭弹窗 —— 这几个阶段都是任务态，让用户走显式按钮决策。
 *
 * App.vue 挂一份；useUpdateAlert.ts 的 updateAlertState 驱动开合 + phase。
 */
import { computed } from "vue";

import Btn from "./Btn.vue";
import Icon from "./Icon.vue";
import ProgressBar from "./ProgressBar.vue";
import {
  updateAlertState,
  resolvePrompt,
  resolveFinal,
} from "@/composables/useUpdateAlert";

function onPromptCancel() {
  resolvePrompt("cancel");
}
function onPromptUpdate() {
  resolvePrompt("update");
}
function onDownloadCancel() {
  // downloading 阶段「取消下载」—— 通过 finalResolve("cancel") 通知调用方
  // 中止 SSE。注意调用方还要主动断开 EventSource，这里只关弹窗。
  resolveFinal("cancel");
}
function onReadyLater() {
  resolveFinal("cancel");
}
function onReadyRestart() {
  resolveFinal("restart");
}
function onErrorClose() {
  resolveFinal("cancel");
}

// 只有 prompt 阶段点遮罩关弹窗。downloading / ready / error 是任务态，
// 用户必须显式选按钮 —— 防止下载到一半被「随手点黑边」中断。
function onBackdrop(e: MouseEvent) {
  if (e.currentTarget !== e.target) return;
  if (updateAlertState.phase === "prompt") onPromptCancel();
}

// 文件大小格式化：byte → MB（1 位小数）。
function fmtMB(bytes: number): string {
  if (bytes <= 0) return "0 MB";
  const mb = bytes / (1024 * 1024);
  return `${mb.toFixed(1)} MB`;
}

const fmtSize = computed(() => {
  const b = updateAlertState.info?.asset_size ?? 0;
  if (b <= 0) return "—";
  return fmtMB(b);
});

// 发布时间格式化：ISO → "YYYY-MM-DD"。time zone 不显示 —— release 跨区
// 用户一般只看日期。
const fmtPublished = computed(() => {
  const s = updateAlertState.info?.published_at ?? "";
  if (!s) return "—";
  try {
    const d = new Date(s);
    if (isNaN(d.getTime())) return s;
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, "0");
    const day = String(d.getDate()).padStart(2, "0");
    return `${y}-${m}-${day}`;
  } catch {
    return s;
  }
});

// prompt 阶段：sha256 缺失就 disable「立即更新」。
const canUpdate = computed(() => {
  const sha = updateAlertState.info?.expected_sha256 ?? "";
  return sha.length === 64;
});

// downloading 阶段：进度比例（0-1，给 ProgressBar 用）。
// 起手就给 0（不是 null = indeterminate）—— 不然 ProgressBar 在 indeterminate
// 模式是"全宽 + shimmer"，第一条 SSE 进度（比如 5%）到达后，width 会从
// 100% 过渡到 5%，看起来就是"闪 100% 再缩回"。
const progressRatio = computed(() => {
  const p = updateAlertState.progress.percent;
  return Math.max(0, Math.min(1, p / 100));
});

const fmtDone = computed(() => fmtMB(updateAlertState.progress.done));
const fmtTotal = computed(() => fmtMB(updateAlertState.progress.total));
</script>

<template>
  <Teleport to="body">
    <div
      v-if="updateAlertState.open && updateAlertState.info"
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/30"
      @click="onBackdrop"
    >
      <div
        class="anim-up bg-bg-inner flex flex-col p-6"
        :style="{
          width: '520px',
          maxWidth: '92vw',
          maxHeight: '85vh',
          borderRadius: 'var(--radius-card)',
          boxShadow: '0 16px 48px rgba(0,0,0,0.18)',
        }"
        @click.stop
      >
        <!-- 标题区 ─ 颜色随 phase 切（error 红、其他蓝）─ -->
        <div class="mb-3 flex flex-shrink-0 items-start gap-3">
          <div
            class="flex flex-shrink-0 items-center justify-center"
            :style="{
              width: '34px',
              height: '34px',
              borderRadius: '999px',
              background:
                updateAlertState.phase === 'error'
                  ? 'rgba(220, 76, 60, 0.12)'
                  : 'var(--primary-soft)',
              color:
                updateAlertState.phase === 'error'
                  ? 'var(--red)'
                  : 'var(--primary-deep)',
            }"
          >
            <Icon
              :name="
                updateAlertState.phase === 'error'
                  ? 'warn'
                  : updateAlertState.phase === 'ready'
                  ? 'check'
                  : 'zap'
              "
              :size="16"
            />
          </div>
          <div class="flex-1 pt-0.5">
            <div class="font-display text-[15px] font-semibold leading-tight">
              {{
                updateAlertState.phase === "error"
                  ? "更新失败"
                  : updateAlertState.phase === "ready"
                  ? "下载完成"
                  : updateAlertState.phase === "downloading"
                  ? "正在下载更新"
                  : "发现新版本"
              }}
            </div>
            <div
              class="mt-1.5 text-[12.5px] leading-relaxed"
              :style="{ color: 'var(--ink-2)' }"
            >
              <span :style="{ color: 'var(--ink-3)' }">
                当前 v{{ updateAlertState.currentVersion }}
              </span>
              <Icon
                name="arrowRight"
                :size="11"
                class="mx-1 inline-block align-middle"
                :style="{ color: 'var(--ink-4)' }"
              />
              <span class="font-semibold">
                v{{ updateAlertState.info.version }}
              </span>
            </div>
          </div>
        </div>

        <!-- 元数据卡（error 阶段不显示） -->
        <div
          v-if="updateAlertState.phase !== 'error'"
          class="mb-3 flex flex-shrink-0 items-center gap-4 px-3 py-2 text-[11.5px]"
          :style="{
            background: 'var(--card-2)',
            border: '1px solid var(--line)',
            borderRadius: 'var(--radius-inner)',
            color: 'var(--ink-3)',
          }"
        >
          <span class="inline-flex items-center gap-1.5">
            <Icon name="calendar" :size="12" />
            <span>发布于 {{ fmtPublished }}</span>
          </span>
          <span :style="{ color: 'var(--ink-4)' }">·</span>
          <span class="inline-flex items-center gap-1.5">
            <Icon name="download" :size="12" />
            <span>{{ fmtSize }}</span>
          </span>
        </div>

        <!-- 主区：按 phase 切 ─────────────────────────────────────── -->

        <!-- prompt: changelog -->
        <template v-if="updateAlertState.phase === 'prompt'">
          <div
            class="mb-1 flex-shrink-0 text-[11px] font-medium uppercase"
            :style="{ color: 'var(--ink-3)', letterSpacing: '1.2px' }"
          >
            更新内容
          </div>
          <div
            class="min-h-0 flex-1 overflow-y-auto"
            :style="{
              background: 'var(--card)',
              border: '1px solid var(--line)',
              borderRadius: 'var(--radius-inner)',
              padding: '10px 14px',
            }"
          >
            <div
              class="text-[12.5px] leading-relaxed"
              :style="{
                color: 'var(--ink-2)',
                whiteSpace: 'pre-wrap',
                wordBreak: 'break-word',
              }"
            >
              {{ updateAlertState.info.changelog || "(release 未附说明)" }}
            </div>
          </div>
        </template>

        <!-- downloading: 进度条 -->
        <template v-else-if="updateAlertState.phase === 'downloading'">
          <div class="flex flex-shrink-0 flex-col gap-3 py-4">
            <ProgressBar :value="progressRatio" :height="8" tone="primary" />
            <div class="flex items-center justify-between text-[12px]">
              <span :style="{ color: 'var(--ink-2)' }">
                {{ fmtDone }} / {{ fmtTotal }}
              </span>
              <span
                class="font-semibold tabular-nums"
                :style="{ color: 'var(--primary-deep)' }"
              >
                {{ updateAlertState.progress.percent.toFixed(1) }}%
              </span>
            </div>
            <div class="text-[11.5px]" :style="{ color: 'var(--ink-3)' }">
              下载完成后可直接重启应用完成安装，更新过程几秒内完成。
            </div>
          </div>
        </template>

        <!-- ready: 完成提示 -->
        <template v-else-if="updateAlertState.phase === 'ready'">
          <div
            class="flex flex-shrink-0 flex-col gap-3 px-3 py-4"
            :style="{
              background: 'var(--card)',
              border: '1px solid var(--line)',
              borderRadius: 'var(--radius-inner)',
            }"
          >
            <div class="flex items-center gap-2">
              <Icon
                name="check"
                :size="16"
                :style="{ color: 'var(--green)' }"
              />
              <span class="text-[13px] font-medium">更新包已下载完成</span>
            </div>
            <div
              class="text-[12px] leading-relaxed"
              :style="{ color: 'var(--ink-3)' }"
            >
              点击「立即重启」会关闭当前应用，由独立的 updater
              替换安装目录后自动重新启动；过程几秒内完成。
              <br />
              <span :style="{ color: 'var(--ink-4)' }">
                提示：请先保存正在编辑的内容。
              </span>
            </div>
          </div>
        </template>

        <!-- error: 错误信息 -->
        <template v-else-if="updateAlertState.phase === 'error'">
          <div
            class="flex flex-shrink-0 flex-col gap-2 px-3 py-3"
            :style="{
              background: 'rgba(220, 76, 60, 0.08)',
              border: '1px solid rgba(220, 76, 60, 0.4)',
              borderRadius: 'var(--radius-inner)',
              color: 'var(--red)',
            }"
          >
            <div class="text-[12.5px] font-medium">更新流程中出错</div>
            <div
              class="text-[12px] leading-relaxed"
              :style="{
                color: 'var(--ink-2)',
                whiteSpace: 'pre-wrap',
                wordBreak: 'break-word',
              }"
            >
              {{ updateAlertState.errorMsg || "未知错误" }}
            </div>
          </div>
        </template>

        <!-- 底栏：按 phase 切按钮 ─────────────────────────────────── -->
        <div class="mt-5 flex flex-shrink-0 items-center justify-end gap-2">
          <!-- prompt: sha256 缺失提示 -->
          <span
            v-if="updateAlertState.phase === 'prompt' && !canUpdate"
            class="mr-auto text-[11px]"
            :style="{ color: 'var(--ink-3)' }"
          >
            release 缺少 manifest.json 校验信息，暂不可下载
          </span>

          <template v-if="updateAlertState.phase === 'prompt'">
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

          <template v-else-if="updateAlertState.phase === 'downloading'">
            <Btn variant="ghost" small @click="onDownloadCancel">取消下载</Btn>
          </template>

          <template v-else-if="updateAlertState.phase === 'ready'">
            <Btn variant="ghost" small @click="onReadyLater">稍后</Btn>
            <Btn variant="solid" small @click="onReadyRestart">
              <Icon name="refresh" :size="13" />
              <span>立即重启</span>
            </Btn>
          </template>

          <template v-else-if="updateAlertState.phase === 'error'">
            <Btn variant="ghost" small @click="onErrorClose">关闭</Btn>
          </template>
        </div>
      </div>
    </div>
  </Teleport>
</template>
