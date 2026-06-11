<script setup lang="ts">
/**
 * 状态预览 — 设计期工具，集中展示空态 / 加载 / 错误 / 进度卡片。
 * 不接 sidecar，不写状态，仅 UI。
 */
import { ref } from "vue";

import Btn from "@/components/ui/Btn.vue";
import Card from "@/components/ui/Card.vue";
import Pill from "@/components/ui/Pill.vue";
import ProgressBar from "@/components/ui/ProgressBar.vue";
import Spinner from "@/components/ui/Spinner.vue";
import Icon from "@/components/ui/Icon.vue";
import { useToast } from "@/composables/useToast";

const STATES = [
  "empty-docs",
  "empty-monitor",
  "loading-index",
  "polishing",
  "error-api",
  "offline",
] as const;
type State = (typeof STATES)[number];

const active = ref<State>("empty-docs");
const toast = useToast();
</script>

<template>
  <div class="flex flex-col gap-d">
    <Card>
      <div class="flex items-center justify-between">
        <div>
          <div class="font-display text-[18px] font-semibold">状态预览</div>
          <div class="mt-1 text-[12.5px] text-ink-3">
            设计期工具集 — 验证空态 / 加载 / 错误等卡片视觉。
          </div>
        </div>
        <div class="flex items-center gap-2">
          <Pill tone="ok">ok</Pill>
          <Pill tone="warn">warn</Pill>
          <Pill tone="alert">alert</Pill>
          <Pill tone="primary">primary</Pill>
          <Pill>info</Pill>
        </div>
      </div>

      <div class="mt-4 flex flex-wrap gap-1.5">
        <button
          v-for="s in STATES"
          :key="s"
          type="button"
          class="text-[11.5px]"
          :style="{
            padding: '6px 10px',
            borderRadius: '999px',
            background: active === s ? 'var(--primary)' : 'var(--card-2)',
            color: active === s ? '#fff' : 'var(--ink-2)',
            border: '1px solid var(--line)',
          }"
          @click="active = s"
        >
          {{ s }}
        </button>
      </div>
    </Card>

    <Card v-if="active === 'empty-docs'">
      <div class="flex flex-col items-center gap-3 py-10 text-center">
        <Icon name="fileText" :size="36" />
        <div class="font-display text-[16px] font-semibold">还没有文档</div>
        <div class="max-w-sm text-[12.5px] text-ink-3">
          在「创作区」输入关键词，起飞一篇文章 — 写完后会自动落到 out_dir。
        </div>
        <Btn variant="solid" small>新建文章</Btn>
      </div>
    </Card>

    <Card v-else-if="active === 'empty-monitor'">
      <div class="flex flex-col items-center gap-3 py-10 text-center">
        <Icon name="radar" :size="36" />
        <div class="font-display text-[16px] font-semibold">还没有监测任务</div>
        <div class="max-w-sm text-[12.5px] text-ink-3">
          添加知乎问题或 B/抖/快评论，CSM 会按设定的频率自动检查排名变化。
        </div>
        <Btn variant="solid" small>添加任务</Btn>
      </div>
    </Card>

    <Card v-else-if="active === 'loading-index'">
      <div class="flex items-center gap-4">
        <Spinner :size="28" />
        <div class="min-w-0 flex-1">
          <div class="font-display text-[14.5px] font-semibold">正在重建查重索引</div>
          <div class="text-[12px] text-ink-3">已扫描 142 / 234 篇</div>
          <ProgressBar class="mt-2" :value="142 / 234" />
        </div>
      </div>
    </Card>

    <Card v-else-if="active === 'polishing'">
      <div
        class="relative overflow-hidden p-6"
        :style="{ background: 'var(--dark)', color: 'var(--card)', borderRadius: 'var(--radius-card)' }"
      >
        <div class="font-display text-[16px] font-semibold">正在使用「克制理性」润色</div>
        <div class="mt-1 text-[12px] opacity-70">
          段 5/8 · 1640/2400 字 · 预计 28 秒
        </div>
        <ProgressBar class="mt-3" :value="0.62" tone="primary" />
      </div>
    </Card>

    <Card v-else-if="active === 'error-api'">
      <div class="flex items-start gap-3">
        <span
          class="inline-flex shrink-0 items-center justify-center"
          :style="{
            width: '32px',
            height: '32px',
            borderRadius: '50%',
            background: 'var(--red)',
            color: '#fff',
          }"
        >
          <Icon name="alert" :size="16" />
        </span>
        <div class="min-w-0 flex-1">
          <div class="font-display text-[14px] font-semibold text-red">
            LLM 调用超时
          </div>
          <div class="mt-1 text-[12px] text-ink-3">
            ConnectionTimeout: anthropic-api unreachable. 检查网络或切换 provider。
          </div>
          <div class="mt-2 flex gap-2">
            <Btn variant="solid" small>重试</Btn>
            <Btn variant="ghost" small>切到 Mock</Btn>
          </div>
        </div>
      </div>
    </Card>

    <Card v-else-if="active === 'offline'">
      <div class="flex flex-col items-center gap-2 py-10 text-center">
        <Icon name="alert" :size="32" />
        <div class="font-display text-[15px] font-semibold">离线模式</div>
        <div class="max-w-sm text-[12px] text-ink-3">
          无法连接 sidecar — 请确认 Python 进程已启动。
        </div>
      </div>
    </Card>

    <Card>
      <div class="font-display text-[14px] font-semibold mb-2">Toast 测试</div>
      <div class="flex flex-wrap gap-2">
        <Btn variant="ghost" small @click="toast.info('普通提示信息')">info</Btn>
        <Btn variant="ghost" small @click="toast.success('保存成功')">success</Btn>
        <Btn variant="ghost" small @click="toast.warn('磁盘空间不足')">warn</Btn>
        <Btn variant="ghost" small @click="toast.error('请求失败：404')">error</Btn>
      </div>
    </Card>
  </div>
</template>
