<script setup lang="ts">
/**
 * Composer for the "盖楼" tier draft inside a VideoCard.
 *
 * Three modes (driven by props):
 *   1. empty       — 0 floors so far. Placeholder "在这里写第一条评论…",
 *                    button "发布第 1 层", textarea starts at 2 rows.
 *   2. continue    — N floors so far. Placeholder "+ 继续盖一层评论…",
 *                    button "盖第 N+1 层", textarea starts at 1 row,
 *                    auto-grows on focus.
 *   3. editing     — Parent set ``editingComment``. Orange top banner,
 *                    text + image_ids preloaded, button "保存修改".
 *
 * Owns three pieces of local state:
 *   - ``text``: the textarea body, autosizes via scrollHeight.
 *   - ``images``: thumbnails of already-uploaded images. The composer
 *     uploads each picked file immediately so the user sees progress
 *     and can cancel one without re-uploading the rest. Each item's
 *     ``image_id`` is what the backend wants in the final POST.
 *   - busy flags for the three async operations.
 *
 * In editing mode, ``images`` is rehydrated from the comment being
 * edited: the server returns ``image_urls`` (absolute paths) alongside
 * ``image_ids``, so we pair them up. File names aren't preserved by the
 * server, so the rehydrated chips show "(已有图片)" as the tooltip.
 *
 * Source-tracking nuance: if the user pressed "AI 续写" *and* the
 * textarea text still matches whatever the suggest call returned, we
 * label the saved comment ``source = "ai_suggested"``. The moment the
 * user types over the suggestion, we revert to "manual". Editing
 * existing comments doesn't change source.
 *
 * TODO(phase-4): swap the 图片 button's native file picker for an
 * inline "素材库" popover that surfaces re-usable image assets — the
 * user explicitly asked for this in the spec but it's out of scope
 * for the current redesign iteration.
 */
import { computed, nextTick, ref, useTemplateRef, watch } from "vue";
import { useRouter } from "vue-router";

import TemplateChipsRow from "@/components/mining/TemplateChipsRow.vue";
import TemplateDrawer from "@/components/mining/TemplateDrawer.vue";
import Icon from "@/components/ui/Icon.vue";
import { useToast } from "@/composables/useToast";
import { useStaleGuard } from "@/composables/useStaleGuard";
import { useMiningStore, LLMNotConfiguredError, type Comment } from "@/stores/mining";
import { useSidecar } from "@/stores/sidecar";
import { useTemplatesStore, type Template } from "@/stores/templates";

const props = defineProps<{
  videoId: number;
  /** N+1 for the next floor to publish (e.g. 1 when there are 0 floors). */
  nextTier: number;
  previousTiers: string[];
  /** True iff at least one floor exists so 完成 is meaningful. */
  canComplete?: boolean;
  /** Parent is mid-bulkMarkCommented call; show "处理中…" + freeze. */
  completeBusy?: boolean;
  /** When non-null, composer is in EDIT mode for that comment. */
  editingComment: Comment | null;
}>();

const emit = defineEmits<{
  (e: "saved"): void;
  (e: "cancel-edit"): void;
  (e: "complete"): void;
}>();

const store = useMiningStore();
const toast = useToast();
const router = useRouter();
const sidecar = useSidecar();
const templatesStore = useTemplatesStore();

const MAX_IMAGES = 9;

// Template library state — drawer toggle + pending pick for replace/append confirm.
const drawerOpen = ref(false);
const pendingPick = ref<Template | null>(null);
const showPickConfirm = ref(false);

function resolveUrl(u: string): string {
  if (!u) return "";
  if (u.startsWith("http://") || u.startsWith("https://")) return u;
  return sidecar.sseURL(u);
}

const text = ref("");
const images = ref<{ image_id: string; url: string; name: string }[]>([]);
const isUploading = ref(false);
const isSuggesting = ref(false);
const isSaving = ref(false);
const lastSuggestion = ref<string | null>(null);

const fileInputRef = useTemplateRef<HTMLInputElement>("fileInputRef");
const textareaRef = useTemplateRef<HTMLTextAreaElement>("textareaRef");

const isEditing = computed(() => props.editingComment !== null);
const mode = computed<"empty" | "continue" | "editing">(() => {
  if (isEditing.value) return "editing";
  if (props.previousTiers.length === 0) return "empty";
  return "continue";
});

const placeholder = computed(() => {
  if (mode.value === "editing")
    return `正在编辑第 ${props.editingComment!.tier} 层…`;
  if (mode.value === "empty")
    return "在这里写第一条评论…";
  return "+ 继续盖一层评论…";
});

const publishLabel = computed(() => {
  if (mode.value === "editing") return "保存修改";
  if (mode.value === "empty") return `发布第 ${props.nextTier} 层`;
  return `盖第 ${props.nextTier} 层`;
});

const canSave = computed(() =>
  !isSaving.value
  && (text.value.trim().length > 0 || images.value.length > 0),
);

const canPickMoreImages = computed(() => images.value.length < MAX_IMAGES);

/**
 * Auto-grow the textarea. The floor (minimum height) depends on mode —
 * empty starts at 2 rows of room, continue starts at 1 row but expands
 * once the user types. Editing mode just respects content height.
 */
function autosize(el: HTMLTextAreaElement | null) {
  if (!el) return;
  el.style.height = "auto";
  const floor = mode.value === "empty" ? 48 : 32;
  const next = Math.max(floor, Math.min(180, el.scrollHeight));
  el.style.height = next + "px";
}

// Re-hydrate composer when entering/leaving edit mode.
watch(() => props.editingComment, async (next, prev) => {
  if (next && next !== prev) {
    text.value = next.text || "";
    // Pair image_ids ↔ image_urls returned by the server.
    images.value = (next.image_ids || []).map((id, i) => ({
      image_id: id,
      url: next.image_urls?.[i] ?? "",
      name: "(已有图片)",
    }));
    lastSuggestion.value = null;
    await nextTick();
    autosize(textareaRef.value);
    textareaRef.value?.focus();
  } else if (!next && prev) {
    // Left edit mode → clear so the next floor starts fresh.
    text.value = "";
    images.value = [];
    lastSuggestion.value = null;
    await nextTick();
    autosize(textareaRef.value);
  }
}, { immediate: true });

function onInput(ev: Event) {
  text.value = (ev.target as HTMLTextAreaElement).value;
  autosize(ev.target as HTMLTextAreaElement);
}

function onFocus(ev: FocusEvent) {
  // continue mode starts visually compact (1 row); on focus we grow to
  // give the user breathing room without making them click in twice.
  autosize(ev.target as HTMLTextAreaElement);
}

function pickImages() {
  if (!canPickMoreImages.value) return;
  fileInputRef.value?.click();
}

async function onFilesPicked(ev: Event) {
  const inp = ev.target as HTMLInputElement;
  const list = inp.files;
  if (!list || list.length === 0) return;
  isUploading.value = true;
  try {
    for (let i = 0; i < list.length; i++) {
      const f = list.item(i);
      if (!f) continue;
      // Enforce the 9-image cap client-side. Server also caps but this
      // gives instant feedback instead of a 422 mid-upload.
      if (images.value.length >= MAX_IMAGES) {
        toast.warn(`最多 ${MAX_IMAGES} 张图片`);
        break;
      }
      try {
        const r = await store.uploadImage(props.videoId, f);
        images.value.push({ image_id: r.image_id, url: r.url, name: f.name });
      } catch (e: any) {
        const status = e?.response?.status as number | undefined;
        const detail = e?.response?.data?.detail as string | undefined;
        if (status === 413) {
          toast.error(`图片 ${f.name} 太大（上限 5MB）`);
        } else if (status === 415) {
          toast.error(`图片 ${f.name} 格式不支持（仅 JPG/PNG/WebP）`);
        } else {
          toast.error(`图片 ${f.name} 上传失败${detail ? "：" + detail : ""}`);
        }
      }
    }
  } finally {
    isUploading.value = false;
    inp.value = "";
  }
}

function removeImage(idx: number) {
  images.value.splice(idx, 1);
}

// Guards anything async that wants to write text.value. ``onSuggest``
// issues a token before awaiting the LLM; ``handlePick`` and
// ``confirmPick`` issue (without checking) so any in-flight suggestion
// is invalidated the moment the user picks a template instead — the
// late-arriving suggestion no longer clobbers the template they chose.
const textWriteGuard = useStaleGuard();

async function onSuggest() {
  if (isSuggesting.value) return;
  const my = textWriteGuard.issue();
  isSuggesting.value = true;
  try {
    // In edit mode, we still let the user 续写 — the suggestion will
    // overwrite the textarea content, so we treat the post-save source
    // as ai_suggested if they didn't change it again afterwards.
    const tierForSuggest = isEditing.value
      ? props.editingComment!.tier
      : props.nextTier;
    const suggestion = await store.suggestComment(
      props.videoId,
      tierForSuggest,
      props.previousTiers,
    );
    if (textWriteGuard.isStale(my)) return;
    text.value = suggestion;
    lastSuggestion.value = suggestion;
    await nextTick();
    autosize(textareaRef.value);
    textareaRef.value?.focus();
  } catch (e) {
    if (textWriteGuard.isStale(my)) return;
    if (e instanceof LLMNotConfiguredError) {
      toast.error(e.message || "请先在设置中配置 AI 服务", {
        actionLabel: "去设置",
        onAction: () => { router.push("/settings"); },
      });
    } else {
      const detail = (e as any)?.response?.data?.detail as string | undefined;
      toast.error("AI 续写失败" + (detail ? "：" + detail : ""));
    }
  } finally {
    isSuggesting.value = false;
  }
}

async function onPublish() {
  if (!canSave.value) return;
  isSaving.value = true;
  try {
    if (isEditing.value) {
      await store.updateComment(props.editingComment!.id, {
        text: text.value,
        image_ids: images.value.map(i => i.image_id),
      });
      toast.success("已保存修改");
      emit("cancel-edit");
      emit("saved");
    } else {
      const source: "manual" | "ai_suggested" =
        lastSuggestion.value !== null && text.value === lastSuggestion.value
          ? "ai_suggested"
          : "manual";
      await store.createComment(props.videoId, {
        tier: props.nextTier,
        text: text.value,
        image_ids: images.value.map(i => i.image_id),
        source,
      });
      // Clean slate for the next tier — but keep composer visible &
      // focused so 盖楼 stays a flow rather than a series of clicks.
      text.value = "";
      images.value = [];
      lastSuggestion.value = null;
      await nextTick();
      autosize(textareaRef.value);
      textareaRef.value?.focus();
      emit("saved");
    }
  } catch (e: any) {
    const status = e?.response?.status as number | undefined;
    if (status === 409) {
      toast.error("评论楼层有冲突，请刷新后重试");
      emit("saved");
    } else {
      const detail = e?.response?.data?.detail as string | undefined;
      toast.error("保存失败" + (detail ? "：" + detail : ""));
    }
  } finally {
    isSaving.value = false;
  }
}

function onCancelEdit() {
  // Decision: discard any in-progress text rather than try to preserve.
  // Keeps the mental model simple: edit-cancel = "back out, nothing
  // changed".
  emit("cancel-edit");
}

// ── Template library: pick / replace / append flow ─────────────────
//
// Empty textarea → direct fill (no confirm dialog needed).
// Non-empty textarea → stash pending pick + show 3-button popover
//   (替换 / 追加 / 取消) so the user doesn't lose what they typed.
// useTemplate() server-bumps use_count + last_used_at so chip ranking
// updates on next mount of TemplateChipsRow.
async function handlePick(tpl: Template) {
  // Invalidate any pending onSuggest — the user is choosing a template
  // instead, and a late-arriving suggestion would overwrite their pick.
  textWriteGuard.issue();
  if (text.value.trim().length === 0) {
    text.value = await templatesStore.useTemplate(tpl.id);
    await nextTick();
    autosize(textareaRef.value);
    textareaRef.value?.focus();
  } else {
    pendingPick.value = tpl;
    showPickConfirm.value = true;
  }
}

async function confirmPick(action: "replace" | "append") {
  if (!pendingPick.value) return;
  textWriteGuard.issue();
  const filledText = await templatesStore.useTemplate(pendingPick.value.id);
  if (action === "replace") {
    text.value = filledText;
  } else {
    text.value = text.value.trim() + "\n" + filledText;
  }
  showPickConfirm.value = false;
  pendingPick.value = null;
  await nextTick();
  autosize(textareaRef.value);
  textareaRef.value?.focus();
}

function cancelPick() {
  showPickConfirm.value = false;
  pendingPick.value = null;
}

function onTextareaKeydown(e: KeyboardEvent) {
  // Ctrl+/ or Cmd+/ opens the template drawer. Doesn't fire if user is
  // mid-IME composition (browser handles that automatically).
  if ((e.ctrlKey || e.metaKey) && e.key === "/") {
    drawerOpen.value = true;
    e.preventDefault();
  }
}
</script>

<template>
  <div
    class="flex flex-col relative"
    :style="{
      background: 'var(--card-white)',
      border: '1.5px solid ' + (isEditing ? 'var(--primary)' : 'var(--line-2)'),
      borderRadius: '12px',
      padding: '0',
      overflow: 'hidden',
    }"
  >
    <!-- 编辑模式横幅 -->
    <div
      v-if="isEditing"
      class="flex items-center"
      :style="{
        background: 'var(--primary)',
        color: '#fff',
        padding: '5px 10px',
        fontSize: '11px',
        fontWeight: 600,
        gap: '6px',
      }"
    >
      <Icon name="edit" :size="11"/>
      <span>正在编辑第 {{ editingComment?.tier }} 层</span>
      <button
        type="button"
        class="ml-auto inline-flex items-center gap-1 transition hover:bg-[rgba(255,255,255,0.15)]"
        :style="{
          height: '20px',
          padding: '0 8px',
          borderRadius: '999px',
          fontSize: '10.5px',
          background: 'rgba(255,255,255,0.15)',
          color: '#fff',
          cursor: 'pointer',
        }"
        @click="onCancelEdit"
      >
        <Icon name="x" :size="10"/>
        <span>取消</span>
      </button>
    </div>

    <!-- 模板 chips（onMounted 拉取 top-N，picked 后命中 handlePick） -->
    <div :style="{ padding: '7px 9px 0' }">
      <TemplateChipsRow
        @pick="handlePick"
        @open-drawer="drawerOpen = true"
      />
    </div>

    <!-- textarea -->
    <textarea
      ref="textareaRef"
      :value="text"
      @input="onInput"
      @focus="onFocus"
      @keydown="onTextareaKeydown"
      :placeholder="placeholder"
      :rows="mode === 'empty' ? 2 : 1"
      class="w-full bg-transparent outline-none resize-none"
      :style="{
        padding: '9px 11px 4px',
        fontSize: '12.5px',
        lineHeight: 1.55,
        color: 'var(--ink)',
        fontFamily: 'inherit',
        minHeight: mode === 'empty' ? '48px' : '32px',
        // Global `:focus-visible { outline: 2px solid var(--primary) }`
        // (style.css:188) shows an orange ring when the textarea is
        // focused. The composer's outer container already telegraphs
        // edit / publish state with its own color cues, so the ring on
        // the textarea is visual noise. Suppress for textarea only —
        // keyboard nav on toolbar buttons keeps the global affordance.
        outline: 'none',
      }"
    />

    <!-- 已选图片预览 -->
    <div
      v-if="images.length"
      class="flex flex-wrap items-center"
      :style="{ padding: '2px 8px 6px', gap: '6px' }"
    >
      <div
        v-for="(img, i) in images"
        :key="img.image_id"
        class="relative"
        :style="{
          width: '50px',
          height: '50px',
          borderRadius: '8px',
          overflow: 'hidden',
          border: '1px solid var(--line-2)',
          background: 'var(--card-2)',
        }"
        :title="img.name"
      >
        <img
          v-if="img.url"
          :src="resolveUrl(img.url)"
          :alt="img.name"
          :style="{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }"
        />
        <button
          type="button"
          class="absolute inline-flex items-center justify-center"
          :style="{
            top: '-4px', right: '-4px',
            width: '16px', height: '16px',
            borderRadius: '999px',
            background: 'var(--dark)', color: '#fff',
            border: '1px solid var(--card)',
            cursor: 'pointer',
          }"
          title="移除"
          @click="removeImage(i)"
        ><Icon name="x" :size="9"/></button>
      </div>
    </div>

    <!-- 工具栏 -->
    <div
      class="flex items-center"
      :style="{ padding: '5px 6px 5px 8px', gap: '6px' }"
    >
      <!--
        图片 + AI 续写 按用户要求只保留 icon，文字下线 —— 鼠标 hover
        title 属性给完整说明。图片数量徽章 N/9 保留（点开前要知道还能
        加几张）；上传中 / 生成中走 Spinner 才在 icon 处可视化状态。
      -->
      <button
        type="button"
        class="inline-flex items-center gap-1 transition"
        :disabled="isUploading || !canPickMoreImages"
        :style="{
          height: '28px',
          width: images.length > 0 ? 'auto' : '28px',
          padding: images.length > 0 ? '0 9px' : '0',
          justifyContent: 'center',
          borderRadius: '999px',
          fontSize: '11px',
          background: 'var(--card-2)',
          color: (isUploading || !canPickMoreImages) ? 'var(--ink-4)' : 'var(--ink-2)',
          border: '1px solid var(--line)',
          cursor: isUploading ? 'wait' : (canPickMoreImages ? 'pointer' : 'not-allowed'),
        }"
        :title="isUploading ? '上传中…' : (canPickMoreImages ? '上传图片（JPG/PNG/WebP）' : `已达上限 ${MAX_IMAGES} 张`)"
        @click="pickImages"
      >
        <Icon name="image" :size="13"/>
        <span
          v-if="images.length > 0"
          :style="{
            fontSize: '10px',
            color: images.length >= MAX_IMAGES ? 'var(--red)' : 'var(--ink-3)',
          }"
        >{{ images.length }}/{{ MAX_IMAGES }}</span>
      </button>
      <button
        type="button"
        class="inline-flex items-center justify-center transition"
        :disabled="isSuggesting"
        :style="{
          height: '28px',
          width: '28px',
          padding: '0',
          borderRadius: '999px',
          background: 'rgba(245,192,66,0.18)',
          color: isSuggesting ? 'var(--ink-4)' : '#7a5400',
          border: '1px solid rgba(245,192,66,0.36)',
          cursor: isSuggesting ? 'wait' : 'pointer',
        }"
        :title="isSuggesting ? 'AI 续写中…' : '让 AI 续写下一层评论'"
        @click="onSuggest"
      >
        <Icon name="wand" :size="13"/>
      </button>
      <div class="flex-1"/>
      <button
        type="button"
        class="inline-flex items-center gap-1.5 transition"
        :disabled="!canSave"
        :style="{
          height: '28px',
          padding: '0 14px',
          borderRadius: '999px',
          fontSize: '11.5px',
          fontWeight: 600,
          background: canSave ? 'var(--primary)' : 'var(--card-2)',
          color: canSave ? '#fff' : 'var(--ink-4)',
          border: '1px solid ' + (canSave ? 'var(--primary)' : 'var(--line)'),
          cursor: canSave ? 'pointer' : 'not-allowed',
        }"
        :title="canSave ? publishLabel : '请先写一些内容或加张图'"
        @click="onPublish"
      >
        <Icon :name="isEditing ? 'check' : 'play'" :size="11"/>
        <span>{{ isSaving ? "保存中…" : publishLabel }}</span>
      </button>
      <button
        v-if="!isEditing"
        type="button"
        class="inline-flex items-center gap-1.5 transition"
        :disabled="!canComplete || completeBusy"
        :style="{
          height: '28px',
          padding: '0 14px',
          borderRadius: '999px',
          fontSize: '11.5px',
          fontWeight: 600,
          background: canComplete ? 'var(--dark)' : 'var(--card-2)',
          color: canComplete ? '#fff' : 'var(--ink-4)',
          border: '1px solid ' + (canComplete ? 'var(--dark)' : 'var(--line)'),
          cursor: (!canComplete || completeBusy) ? 'not-allowed' : 'pointer',
        }"
        :title="canComplete ? '标记这条已搞定' : '至少写一层评论才能完成'"
        @click="emit('complete')"
      >
        <Icon name="check" :size="11"/>
        <span>{{ completeBusy ? "处理中…" : "完成" }}</span>
      </button>
    </div>

    <!-- Hidden multi-select picker. TODO(phase-4): replace with 素材库. -->
    <input
      ref="fileInputRef"
      type="file"
      accept="image/jpeg,image/png,image/webp,image/jpg"
      multiple
      style="display: none"
      @change="onFilesPicked"
    />

    <!-- 替换/追加确认 popover — only when textarea has content -->
    <div
      v-if="showPickConfirm"
      class="pick-confirm-overlay"
      @click.self="cancelPick"
    >
      <div class="pick-confirm-card">
        <div class="confirm-title">输入框已有内容</div>
        <div class="confirm-preview">{{ pendingPick?.text }}</div>
        <div class="confirm-actions">
          <button @click="confirmPick('replace')">替换</button>
          <button @click="confirmPick('append')">追加</button>
          <button @click="cancelPick">取消</button>
        </div>
      </div>
    </div>

    <!-- 模板抽屉（T11 实装；当前 stub 只满足导入） -->
    <TemplateDrawer
      v-if="drawerOpen"
      @close="drawerOpen = false"
      @pick="async (tpl: Template) => { drawerOpen = false; await handlePick(tpl) }"
    />
  </div>
</template>

<style scoped>
/* Replace/append confirm popover — only renders when textarea has content
 * and user clicks a chip. Click-on-overlay or 取消 button dismisses. */
.pick-confirm-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.3);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
}
.pick-confirm-card {
  background: var(--card, #fff);
  border-radius: 10px;
  padding: 18px 20px;
  min-width: 320px;
  max-width: 480px;
  box-shadow: 0 12px 32px rgba(0, 0, 0, 0.18);
}
.confirm-title {
  font-weight: 600;
  margin-bottom: 8px;
  color: var(--ink, #2a2017);
}
.confirm-preview {
  background: var(--card-2, #fff5dc);
  padding: 10px;
  border-radius: 6px;
  font-size: 12px;
  color: var(--ink, #2a2017);
  margin-bottom: 14px;
  max-height: 120px;
  overflow-y: auto;
  white-space: pre-wrap;
}
.confirm-actions {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
}
.confirm-actions button {
  padding: 6px 14px;
  border-radius: 6px;
  border: 1px solid var(--line, #d4c8a8);
  background: var(--card, #fff);
  cursor: pointer;
  font-size: 12px;
  font-family: inherit;
}
.confirm-actions button:first-child {
  background: var(--ink, #2a2017);
  color: #fff;
  border-color: var(--ink, #2a2017);
}
</style>
