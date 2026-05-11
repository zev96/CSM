<script setup lang="ts">
import { useRouter } from "vue-router";

import Card from "@/components/ui/Card.vue";
import Icon from "@/components/ui/Icon.vue";

const router = useRouter();

const ACTIONS = [
  { name: "edit",     label: "粘贴洗稿",  hint: "贴进来一段，整篇润色",  to: "article" },
  { name: "library",  label: "模板库",    hint: "复用已有写作框架",      to: "templates" },
  { name: "radar",    label: "监测中心",  hint: "排名 / 评论留存看板",   to: "monitor" },
  { name: "wand",     label: "Skills",    hint: "调风格，挑笔触",       to: "templates" },
] as const;
</script>

<template>
  <Card>
    <div class="grid grid-cols-2 gap-2 sm:grid-cols-4">
      <button
        v-for="a in ACTIONS"
        :key="a.label"
        type="button"
        class="flex flex-col items-start gap-2 bg-card-2 p-3 text-left transition hover:bg-card-white"
        :style="{ borderRadius: 'var(--radius-inner)', border: '1px solid var(--line)' }"
        @click="router.push({ name: a.to })"
      >
        <span
          class="inline-flex items-center justify-center"
          :style="{
            width: '32px',
            height: '32px',
            borderRadius: '10px',
            background: 'var(--primary-soft)',
            color: 'var(--primary-deep)',
          }"
        >
          <Icon :name="a.name" :size="16" />
        </span>
        <div>
          <div class="text-[13px] font-semibold">{{ a.label }}</div>
          <div class="mt-0.5 text-[11.5px] text-ink-3">{{ a.hint }}</div>
        </div>
      </button>
    </div>
  </Card>
</template>
