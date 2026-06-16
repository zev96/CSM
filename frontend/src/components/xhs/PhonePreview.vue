<script setup lang="ts">
/**
 * 手机预览（设计稿 §4.3）—— 纯 computed 渲染，不做 DOM 转图（导出=复制文案）。
 * 笔记页 / 发现页两 tab。P0 封面用占位块；真实图在 P2 接。
 */
import { computed } from "vue";
import { useXhs } from "@/stores/xhs";
import { useConfig } from "@/stores/config";

const xhs = useXhs();
const cfg = useConfig();

const nickname = computed<string>(() => String(cfg.data?.user_name ?? "") || "我的小红书");
const avatarLetter = computed<string>(() => (nickname.value || "我").slice(0, 1).toUpperCase());

// 正文按行渲染（white-space: pre-wrap 保留换行与缩进 + emoji）。
const displayTitle = computed(() => xhs.title || "添加标题更吸睛～");
const displayBody = computed(() => xhs.body || "正文还没写哦，左侧素材点一点，右侧实时预览～");
const tags = computed(() => xhs.topics.filter((t) => t.trim()));
</script>

<template>
  <div class="flex h-full flex-col" :style="{ gap: '10px' }">
    <!-- tab 切换 -->
    <div class="flex items-center justify-center" :style="{ gap: '6px' }">
      <button
        v-for="t in (['note', 'discover'] as const)"
        :key="t"
        type="button"
        :style="{
          fontSize: '12px',
          padding: '4px 12px',
          borderRadius: '999px',
          border: '1px solid var(--line-2)',
          cursor: 'pointer',
          background: xhs.previewTab === t ? 'var(--primary)' : 'transparent',
          color: xhs.previewTab === t ? '#fff' : 'var(--ink-2)',
        }"
        @click="xhs.setPreviewTab(t)"
      >
        {{ t === 'note' ? '笔记页' : '发现页' }}
      </button>
    </div>

    <!-- 手机外框 -->
    <div
      class="min-h-0 flex-1 overflow-y-auto"
      :style="{
        margin: '0 auto',
        width: '300px',
        maxWidth: '100%',
        borderRadius: '28px',
        border: '8px solid var(--dark)',
        background: '#fff',
        boxShadow: '0 12px 30px -10px rgba(var(--shadow-rgb),0.25)',
      }"
    >
      <!-- ── 笔记页 ── -->
      <div v-if="xhs.previewTab === 'note'" :style="{ paddingBottom: '12px' }">
        <!-- 封面（P0 占位） -->
        <div
          :style="{
            width: '100%',
            aspectRatio: '3 / 4',
            background: 'linear-gradient(135deg, #ffe3d3, #ffd0b5)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: 'var(--primary)',
            fontSize: '13px',
            borderRadius: '20px 20px 0 0',
          }"
        >
          封面图（P2 上传）
        </div>
        <div :style="{ padding: '12px 14px' }">
          <!-- 作者条 -->
          <div class="flex items-center" :style="{ gap: '8px', marginBottom: '8px' }">
            <div
              :style="{
                width: '28px', height: '28px', borderRadius: '999px',
                background: 'var(--dark)', color: 'var(--primary)',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                fontSize: '12px', fontWeight: 700,
              }"
            >{{ avatarLetter }}</div>
            <span :style="{ fontSize: '13px', color: 'var(--ink)', flex: 1 }">{{ nickname }}</span>
            <span :style="{ fontSize: '12px', color: '#fff', background: '#ff2e4d', padding: '3px 12px', borderRadius: '999px' }">关注</span>
          </div>
          <!-- 标题 -->
          <div
            :style="{
              fontSize: '16px', fontWeight: 700, lineHeight: 1.4, marginBottom: '6px',
              color: xhs.title ? 'var(--ink)' : '#bbb', whiteSpace: 'pre-wrap', wordBreak: 'break-word',
            }"
          >{{ displayTitle }}</div>
          <!-- 正文 -->
          <div
            :style="{
              fontSize: '14px', lineHeight: 1.7,
              color: xhs.body ? 'var(--ink)' : '#bbb',
              whiteSpace: 'pre-wrap', wordBreak: 'break-word',
            }"
          >{{ displayBody }}</div>
          <!-- 话题 -->
          <div v-if="tags.length" :style="{ marginTop: '8px', display: 'flex', flexWrap: 'wrap', gap: '4px 8px' }">
            <span v-for="(t, i) in tags" :key="i" :style="{ fontSize: '14px', color: '#3a6fb0' }">#{{ t }}</span>
          </div>
          <!-- 假互动栏 -->
          <div class="flex items-center" :style="{ gap: '16px', marginTop: '12px', color: 'var(--ink-2)', fontSize: '12px' }">
            <span>♡ 1.2k</span><span>☆ 328</span><span>💬 56</span>
          </div>
        </div>
      </div>

      <!-- ── 发现页 ── -->
      <div v-else :style="{ padding: '12px' }">
        <div
          :style="{
            borderRadius: '12px', overflow: 'hidden', width: '60%',
            border: '1px solid var(--line-2)',
          }"
        >
          <div
            :style="{
              width: '100%', aspectRatio: '3 / 4',
              background: 'linear-gradient(135deg, #ffe3d3, #ffd0b5)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              color: 'var(--primary)', fontSize: '11px',
            }"
          >封面</div>
          <div :style="{ padding: '8px' }">
            <div
              :style="{
                fontSize: '12px', lineHeight: 1.4, fontWeight: 600,
                color: xhs.title ? 'var(--ink)' : '#bbb',
                display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical',
                overflow: 'hidden',
              }"
            >{{ displayTitle }}</div>
            <div class="flex items-center" :style="{ gap: '6px', marginTop: '6px' }">
              <div
                :style="{
                  width: '16px', height: '16px', borderRadius: '999px',
                  background: 'var(--dark)', color: 'var(--primary)',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  fontSize: '9px', fontWeight: 700,
                }"
              >{{ avatarLetter }}</div>
              <span :style="{ fontSize: '11px', color: 'var(--ink-2)', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }">{{ nickname }}</span>
              <span :style="{ fontSize: '11px', color: 'var(--ink-2)' }">♡ 1.2k</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
