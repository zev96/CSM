<script setup lang="ts">
/**
 * 小红书图文笔记编辑器主视图（设计稿 §4.1 三栏）。
 *   ┌ 顶部：标题 · 草稿下拉 · 保存状态
 *   ├ 左 PanelRail（素材，P0 占位） │ 中 NoteEditor │ 右 PhonePreview
 * 挂载即拉草稿列表；新草稿在首次有内容时由 store 自动创建。
 */
import { nextTick, onMounted, onUnmounted, ref } from "vue";
import Icon from "@/components/ui/Icon.vue";
import PanelRail from "@/components/xhs/PanelRail.vue";
import NoteEditor from "@/components/xhs/NoteEditor.vue";
import PhonePreview from "@/components/xhs/PhonePreview.vue";
import { useXhs } from "@/stores/xhs";
import { confirmDialog } from "@/composables/useConfirm";

const xhs = useXhs();
const draftMenuOpen = ref(false);
const draftWrap = ref<HTMLElement | null>(null);

// 点击下拉之外关闭菜单。toggle 按钮本身在 draftWrap 内，所以「点按钮打开」
// 的那次 click 冒泡到 document 时 contains() 为真、不会把刚开的菜单自关。
function onDocClick(e: MouseEvent) {
  if (!draftMenuOpen.value) return;
  if (draftWrap.value && !draftWrap.value.contains(e.target as Node)) {
    draftMenuOpen.value = false;
  }
}

onMounted(() => {
  void xhs.loadDrafts();
  document.addEventListener("click", onDocClick);
});
onUnmounted(() => document.removeEventListener("click", onDocClick));

async function openDraft(id: string) {
  draftMenuOpen.value = false;
  if (id === xhs.draftId) return;
  // 切换前先把当前未落盘的改动 flush 一次
  await xhs.saveNow();
  await xhs.loadDraft(id);
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

// ── 行内重命名 ────────────────────────────────────────────────────────────────
const renamingId = ref<string | null>(null);
const renameText = ref("");
// v-for 内的 ref 会收集为数组；v-if 保证同一时刻至多一个输入框在 DOM 中，取 [0] 即可
const renameInputRef = ref<HTMLInputElement[]>([]);

function startRename(id: string, current: string, ev: Event) {
  ev.stopPropagation();
  renamingId.value = id;
  renameText.value = current;
  nextTick(() => renameInputRef.value[0]?.focus());
}

async function commitRename(id: string, ev?: Event) {
  ev?.stopPropagation();
  // 防止 Enter 提交后 DOM 移除触发 blur 再次调用（双提交）
  if (renamingId.value !== id) return;
  const t = renameText.value.trim();
  renamingId.value = null;
  if (t) await xhs.renameDraft(id, t);
}

// ── 复制副本 ──────────────────────────────────────────────────────────────────
async function duplicate(id: string, ev: Event) {
  ev.stopPropagation();
  await xhs.duplicateDraft(id);
}

function draftLabel(d: { title: string; updated_at: string }): string {
  return d.title.trim() || "（无标题）";
}
</script>

<template>
  <div class="flex h-full flex-col" :style="{ gap: '14px' }">
    <!-- 顶部条 -->
    <div class="flex items-center" :style="{ gap: '12px', flexShrink: 0 }">
      <div class="text-[11px] uppercase" :style="{ letterSpacing: '1.5px', color: 'var(--ink-3)' }">图文编辑器</div>

      <!-- 草稿下拉 -->
      <div ref="draftWrap" class="relative" :style="{ marginLeft: 'auto' }">
        <button
          type="button"
          class="flex items-center"
          :style="{
            gap: '6px', fontSize: '13px', padding: '7px 12px', borderRadius: '8px',
            border: '1px solid var(--line-2)', background: 'var(--card-white)', color: 'var(--ink)', cursor: 'pointer',
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
            background: 'var(--card-white)', border: '1px solid var(--line-2)', borderRadius: '12px',
            boxShadow: '0 12px 30px -10px rgba(var(--shadow-rgb),0.25)', zIndex: 40, padding: '6px',
          }"
        >
          <div v-if="!xhs.drafts.length" :style="{ padding: '16px', textAlign: 'center', color: 'var(--ink-2)', fontSize: '13px' }">
            还没有草稿，开始写第一篇吧～
          </div>
          <div
            v-for="d in xhs.drafts"
            :key="d.id"
            role="button"
            tabindex="0"
            class="flex w-full items-center"
            :style="{
              gap: '8px', padding: '8px 10px', borderRadius: '8px', cursor: 'pointer', textAlign: 'left',
              background: d.id === xhs.draftId ? 'rgba(var(--ink-rgb),0.06)' : 'transparent',
            }"
            @click="openDraft(d.id)"
            @keydown.enter.prevent="openDraft(d.id)"
          >
            <!-- 行内重命名输入框（激活时替换标签文本） -->
            <input
              v-if="renamingId === d.id"
              ref="renameInputRef"
              v-model="renameText"
              :style="{
                flex: 1, fontSize: '13px', color: 'var(--ink)',
                border: '1px solid var(--primary)', borderRadius: '4px',
                padding: '1px 5px', outline: 'none', background: 'var(--card-white)',
                minWidth: 0,
              }"
              @keydown.enter.prevent="commitRename(d.id, $event)"
              @keydown.esc.prevent="renamingId = null"
              @blur="commitRename(d.id)"
              @click.stop
            />
            <span
              v-else
              :style="{ flex: 1, fontSize: '13px', color: 'var(--ink)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }"
            >
              {{ draftLabel(d) }}
            </span>
            <!-- 重命名按钮 -->
            <button
              type="button"
              :style="{ cursor: 'pointer', color: 'var(--ink-2)', display: 'flex', padding: '2px' }"
              title="重命名"
              @click="startRename(d.id, d.title, $event)"
            ><Icon name="edit" :size="14" /></button>
            <!-- 复制副本按钮 -->
            <button
              type="button"
              :style="{ cursor: 'pointer', color: 'var(--ink-2)', display: 'flex', padding: '2px' }"
              title="复制副本"
              @click="duplicate(d.id, $event)"
            ><Icon name="copy" :size="14" /></button>
            <!-- 删除按钮 -->
            <button
              type="button"
              :style="{ cursor: 'pointer', color: 'var(--ink-2)', display: 'flex', padding: '2px' }"
              title="删除"
              @click="removeDraft(d.id, $event)"
            ><Icon name="trash" :size="14" /></button>
          </div>
        </div>
      </div>
    </div>

    <!-- 三栏 -->
    <div class="flex min-h-0 flex-1" :style="{ gap: '14px' }">
      <!-- 左：素材面板 -->
      <div
        :style="{
          width: '320px', flexShrink: 0, background: 'var(--card)',
          border: '1px solid var(--line-2)', borderRadius: '16px', overflow: 'hidden',
        }"
      >
        <PanelRail />
      </div>
      <!-- 中：编辑器（弹性 1.4，比右栏略宽，随窗口缩放收窄） -->
      <div
        class="min-w-0"
        :style="{ flex: '1.4 1 0', background: 'var(--card)', border: '1px solid var(--line-2)', borderRadius: '16px', padding: '16px', overflow: 'hidden' }"
      >
        <NoteEditor />
      </div>
      <!-- 右：手机预览（弹性 1，比原来更宽，手机随之变大贴边） -->
      <div
        class="min-w-0"
        :style="{
          flex: '1 1 0', minWidth: '300px', background: 'var(--card)',
          border: '1px solid var(--line-2)', borderRadius: '16px', padding: '16px', overflow: 'hidden',
        }"
      >
        <PhonePreview />
      </div>
    </div>
  </div>
</template>
