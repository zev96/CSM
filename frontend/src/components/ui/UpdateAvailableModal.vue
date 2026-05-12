<script setup lang="ts">
/**
 * 「发现新版本」弹窗 —— 同款视觉骨架（参考 FailureAlertModal / ConfirmModal）：
 *   - 圆形 icon + 标题（蓝色 sparkles 表示"好事"，跟红色失败弹窗区分）
 *   - 副标题：版本号 A → 版本号 B
 *   - 中段：元数据卡（发布时间 + 文件大小）
 *   - 主区：changelog markdown（轻量渲染：保留换行 + 列表样式 + 段落间距）
 *   - 底栏：取消（左）+ 立即更新（右，主按钮）
 *
 * sha256 缺失（manifest.json 拿不到）时禁用"立即更新"按钮，鼠标 hover
 * 提示原因 —— 这样用户看到 modal 但知道"还不能更新"，比静默 fail 友好。
 *
 * App.vue 挂一份；useUpdateAlert.ts 的 updateAlertState 驱动开合。
 */
import { computed } from "vue";

import Btn from "./Btn.vue";
import Icon from "./Icon.vue";
import {
  updateAlertState,
  resolveUpdate,
} from "@/composables/useUpdateAlert";

function onCancel() {
  resolveUpdate("cancel");
}
function onUpdate() {
  resolveUpdate("update");
}
function onBackdrop(e: MouseEvent) {
  // 点遮罩 = 取消（跟 FailureAlertModal 一致）
  if (e.currentTarget === e.target) onCancel();
}

// 文件大小格式化：byte → MB（1 位小数）。changelog 体量也不大，不做 KB 区段。
const fmtSize = computed(() => {
  const b = updateAlertState.info?.asset_size ?? 0;
  if (b <= 0) return "—";
  const mb = b / (1024 * 1024);
  return `${mb.toFixed(1)} MB`;
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

// 是否可下载：sha256 缺失（空字符串 / 长度不对）就 disable 更新按钮。
// 这种情况一般是 release 忘了附 manifest.json —— 让用户看到 modal 但
// 明确告知"暂不能更新"，比让按钮看似可点击但点了 422 要好。
const canUpdate = computed(() => {
  const sha = updateAlertState.info?.expected_sha256 ?? "";
  return sha.length === 64;
});
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
        <!-- 标题区 -->
        <div class="mb-3 flex flex-shrink-0 items-start gap-3">
          <div
            class="flex flex-shrink-0 items-center justify-center"
            :style="{
              width: '34px',
              height: '34px',
              borderRadius: '999px',
              background: 'var(--primary-soft)',
              color: 'var(--primary-deep)',
            }"
          >
            <Icon name="zap" :size="16" />
          </div>
          <div class="flex-1 pt-0.5">
            <div class="font-display text-[15px] font-semibold leading-tight">
              发现新版本
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

        <!-- 元数据卡 -->
        <div
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

        <!-- changelog 区 -->
        <!--
          GitHub release body 是 markdown。这里**不**接 markdown 渲染器
          （多 100KB 依赖换不到太多价值），用 white-space:pre-wrap 保留
          原始换行 + 简单列表符号，足够看清"做了什么改动"。等真要做
          rich markdown 再换 vue-marked / marked-vue。
        -->
        <div class="mb-1 flex-shrink-0 text-[11px] font-medium uppercase"
             :style="{ color: 'var(--ink-3)', letterSpacing: '1.2px' }">
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

        <!-- 底栏按钮 -->
        <div class="mt-5 flex flex-shrink-0 items-center justify-end gap-2">
          <!-- sha256 缺失提示 -->
          <span
            v-if="!canUpdate"
            class="mr-auto text-[11px]"
            :style="{ color: 'var(--ink-3)' }"
          >
            release 缺少 manifest.json 校验信息，暂不可下载
          </span>
          <Btn variant="ghost" small @click="onCancel">取消</Btn>
          <Btn
            variant="solid"
            small
            :disabled="!canUpdate"
            @click="onUpdate"
          >
            <Icon name="download" :size="13" />
            <span>立即更新</span>
          </Btn>
        </div>
      </div>
    </div>
  </Teleport>
</template>
