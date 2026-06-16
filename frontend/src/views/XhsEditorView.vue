<script setup lang="ts">
/**
 * 小红书图文笔记编辑器主视图（设计稿 §4.1 三栏）。
 *   ┌ 顶部：标题 · 草稿下拉 · 新建 · 保存状态
 *   ├ 左 PanelRail（素材，P0 占位） │ 中 NoteEditor │ 右 PhonePreview
 * 挂载即拉草稿列表；新建从空白开始（首次有内容时 store 自动建草稿）。
 */
import { onMounted, ref } from "vue";
import Icon from "@/components/ui/Icon.vue";
import PanelRail from "@/components/xhs/PanelRail.vue";
import NoteEditor from "@/components/xhs/NoteEditor.vue";
import PhonePreview from "@/components/xhs/PhonePreview.vue";
import { useXhs } from "@/stores/xhs";
import { confirmDialog } from "@/composables/useConfirm";

const xhs = useXhs();
const draftMenuOpen = ref(false);

onMounted(() => {
  void xhs.loadDrafts();
});

async function openDraft(id: string) {
  draftMenuOpen.value = false;
  if (id === xhs.draftId) return;
  // 切换前先把当前未落盘的改动 flush 一次
  await xhs.saveNow();
  await xhs.loadDraft(id);
}

async function newDraft() {
  draftMenuOpen.value = false;
  await xhs.saveNow();
  xhs.newDraft();
}

async function removeDraft(id: string, ev: Event) {
  ev.stopPropagation();
  // confirmDialog 签名：confirmDialog(message, { title?, okLabel?, cancelLabel?, kind? })
  const ok = await confirmDialog("删除后无法恢复，确认删除这篇草稿吗？", {
    title: "删除草稿",
    okLabel: "删除",
    kind: "danger",
  });
  if (!ok) return;
  await xhs.deleteDraft(id);
}

function draftLabel(d: { title: string; updated_at: string }): string {
  return d.title.trim() || "（无标题）";
}
</script>

<template>
  <div class="flex h-full flex-col" :style="{ gap: '14px' }">
    <!-- 顶部条 -->
    <div class="flex items-center" :style="{ gap: '12px' }">
      <div :style="{ fontSize: '18px', fontWeight: 700, color: 'var(--ink)' }">小红书 · 图文笔记</div>

      <!-- 草稿下拉 -->
      <div class="relative" :style="{ marginLeft: 'auto' }">
        <button
          type="button"
          class="flex items-center"
          :style="{
            gap: '6px', fontSize: '13px', padding: '7px 12px', borderRadius: '8px',
            border: '1px solid var(--line-2)', background: '#fff', color: 'var(--ink)', cursor: 'pointer',
          }"
          @click="draftMenuOpen = !draftMenuOpen"
        >
          <Icon name="doc" :size="14" />
          我的草稿（{{ xhs.drafts.length }}）
          <Icon name="arrowDown" :size="13" />
        </button>
        <div
          v-if="draftMenuOpen"
          class="absolute"
          :style="{
            top: 'calc(100% + 6px)', right: '0', width: '260px', maxHeight: '320px', overflowY: 'auto',
            background: '#fff', border: '1px solid var(--line-2)', borderRadius: '12px',
            boxShadow: '0 12px 30px -10px rgba(var(--shadow-rgb),0.25)', zIndex: 40, padding: '6px',
          }"
        >
          <div v-if="!xhs.drafts.length" :style="{ padding: '16px', textAlign: 'center', color: 'var(--ink-2)', fontSize: '13px' }">
            还没有草稿，开始写第一篇吧～
          </div>
          <button
            v-for="d in xhs.drafts"
            :key="d.id"
            type="button"
            class="flex w-full items-center"
            :style="{
              gap: '8px', padding: '8px 10px', borderRadius: '8px', cursor: 'pointer', textAlign: 'left',
              background: d.id === xhs.draftId ? 'rgba(var(--ink-rgb),0.06)' : 'transparent',
            }"
            @click="openDraft(d.id)"
          >
            <span :style="{ flex: 1, fontSize: '13px', color: 'var(--ink)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }">
              {{ draftLabel(d) }}
            </span>
            <button
              type="button"
              :style="{ cursor: 'pointer', color: 'var(--ink-2)', display: 'flex', padding: '2px' }"
              title="删除"
              @click="removeDraft(d.id, $event)"
            ><Icon name="trash" :size="14" /></button>
          </button>
        </div>
      </div>

      <button
        type="button"
        class="flex items-center"
        :style="{
          gap: '6px', fontSize: '13px', padding: '7px 14px', borderRadius: '8px',
          background: 'var(--primary)', color: '#fff', cursor: 'pointer',
        }"
        @click="newDraft"
      >
        <Icon name="plus" :size="14" /> 新建
      </button>
    </div>

    <!-- 三栏 -->
    <div class="flex min-h-0 flex-1" :style="{ gap: '14px' }">
      <!-- 左：素材面板 -->
      <div
        :style="{
          width: '320px', flexShrink: 0, background: 'var(--bg-inner)',
          border: '1px solid var(--line-2)', borderRadius: '16px', overflow: 'hidden',
        }"
      >
        <PanelRail />
      </div>
      <!-- 中：编辑器 -->
      <div
        class="min-w-0 flex-1"
        :style="{ background: 'var(--bg-inner)', border: '1px solid var(--line-2)', borderRadius: '16px', padding: '16px', overflow: 'hidden' }"
      >
        <NoteEditor />
      </div>
      <!-- 右：手机预览 -->
      <div
        :style="{
          width: '340px', flexShrink: 0, background: 'var(--bg-inner)',
          border: '1px solid var(--line-2)', borderRadius: '16px', padding: '16px', overflow: 'hidden',
        }"
      >
        <PhonePreview />
      </div>
    </div>
  </div>
</template>
