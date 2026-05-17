<script setup lang="ts">
/**
 * Composer for the "发布第 N 层" tier draft inside a VideoCard.
 *
 * Owns three pieces of local state:
 *   - ``text``: the textarea body, autosizes via line-count.
 *   - ``images``: thumbnails of already-uploaded images. The composer
 *     uploads each picked file immediately so the user sees progress
 *     and can cancel one without re-uploading the rest. Each item's
 *     ``image_id`` is what the backend wants in the final POST.
 *   - busy flags for the three async operations.
 *
 * The composer never touches ``commentsByVideo`` directly — after a
 * successful publish it emits ``saved``, and the parent (VideoCard) is
 * responsible for re-fetching or trusting the store update. This keeps
 * the composer reusable in contexts where comments aren't kept in the
 * store (e.g. an isolated drawer in the future).
 *
 * Source-tracking nuance: if the user pressed "AI 建议" *and* the
 * textarea text still matches whatever the suggest call returned, we
 * label the saved comment ``source = "ai_suggested"`` so the backend
 * can later compute AI-adoption stats. The moment the user types over
 * the suggestion, we revert to "manual" — pressing AI again resets it.
 */
import { computed, nextTick, ref, useTemplateRef } from "vue";
import { useRouter } from "vue-router";

import Icon from "@/components/ui/Icon.vue";
import { useToast } from "@/composables/useToast";
import { useMiningStore, LLMNotConfiguredError } from "@/stores/mining";
import { useSidecar } from "@/stores/sidecar";

const props = defineProps<{
  videoId: number;
  nextTier: number;
  previousTiers: string[];
}>();

const emit = defineEmits<{
  (e: "saved"): void;
}>();

const store = useMiningStore();
const toast = useToast();
const router = useRouter();
const sidecar = useSidecar();

/**
 * Image URLs returned by the upload API are relative paths
 * ("/api/mining/images/{id}"). Resolve them through ``sseURL`` so they
 * include the sidecar baseURL + auth token query string — otherwise
 * the WebView hits Vite's dev server / sandbox origin and the thumb
 * stays broken.
 */
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

// Tracks the last AI-suggested string the composer pasted in. If the
// current ``text`` value still matches, we tag the saved comment as
// ``ai_suggested``; once the user edits it diverges, we drop back to
// manual.
const lastSuggestion = ref<string | null>(null);

const fileInputRef = useTemplateRef<HTMLInputElement>("fileInputRef");
const textareaRef = useTemplateRef<HTMLTextAreaElement>("textareaRef");

const canSave = computed(() =>
  !isSaving.value
  && (text.value.trim().length > 0 || images.value.length > 0),
);

// Auto-grow the textarea up to a sane cap. We measure scrollHeight on
// each input and write back to style.height, avoiding a 3rd-party lib.
function autosize(el: HTMLTextAreaElement | null) {
  if (!el) return;
  el.style.height = "auto";
  // 56px floor matches the disabled placeholder composer for visual
  // continuity; 180px cap so a runaway paste doesn't push the card off
  // screen — past that, the textarea scrolls internally.
  const next = Math.max(56, Math.min(180, el.scrollHeight));
  el.style.height = next + "px";
}

function onInput(ev: Event) {
  text.value = (ev.target as HTMLTextAreaElement).value;
  autosize(ev.target as HTMLTextAreaElement);
}

function pickImages() {
  fileInputRef.value?.click();
}

async function onFilesPicked(ev: Event) {
  const inp = ev.target as HTMLInputElement;
  const list = inp.files;
  if (!list || list.length === 0) return;
  isUploading.value = true;
  try {
    // Sequential upload — small N (typically 1-3), the backend writes
    // synchronously to disk, and a Promise.all would obscure per-file
    // failures.
    for (let i = 0; i < list.length; i++) {
      const f = list.item(i);
      if (!f) continue;
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
    // Reset the file input so picking the same file twice in a row
    // still fires `change`.
    inp.value = "";
  }
}

function removeImage(idx: number) {
  images.value.splice(idx, 1);
}

async function onSuggest() {
  if (isSuggesting.value) return;
  isSuggesting.value = true;
  try {
    const suggestion = await store.suggestComment(
      props.videoId,
      props.nextTier,
      props.previousTiers,
    );
    text.value = suggestion;
    lastSuggestion.value = suggestion;
    await nextTick();
    autosize(textareaRef.value);
    // Move focus into the textarea so the user can polish immediately.
    textareaRef.value?.focus();
  } catch (e) {
    if (e instanceof LLMNotConfiguredError) {
      toast.error(e.message || "请先在设置中配置 AI 服务", {
        actionLabel: "去设置",
        onAction: () => { router.push("/settings"); },
      });
    } else {
      const detail = (e as any)?.response?.data?.detail as string | undefined;
      toast.error("AI 建议生成失败" + (detail ? "：" + detail : ""));
    }
  } finally {
    isSuggesting.value = false;
  }
}

async function onPublish() {
  if (!canSave.value) return;
  isSaving.value = true;
  try {
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
    // Clean slate for the next tier.
    text.value = "";
    images.value = [];
    lastSuggestion.value = null;
    await nextTick();
    autosize(textareaRef.value);
    emit("saved");
  } catch (e: any) {
    const status = e?.response?.status as number | undefined;
    if (status === 409) {
      // Two tabs raced — parent should re-fetch which surfaces the
      // winning tier and bumps our nextTier.
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

</script>

<template>
  <div
    class="flex flex-col relative"
    :style="{
      background: 'var(--card-white)',
      border: '1.5px solid var(--line-2)',
      borderRadius: '12px',
      padding: '2px',
    }"
  >
    <!-- textarea -->
    <textarea
      ref="textareaRef"
      :value="text"
      @input="onInput"
      :placeholder="`写第 ${nextTier} 层评论…（可附图片）`"
      rows="2"
      class="w-full bg-transparent outline-none resize-none"
      :style="{
        padding: '9px 11px 4px',
        fontSize: '12.5px',
        lineHeight: 1.55,
        color: 'var(--ink)',
        fontFamily: 'inherit',
        minHeight: '56px',
      }"
    />

    <!-- 已选图片预览 -->
    <div
      v-if="images.length"
      class="flex flex-wrap items-center gap-1.5"
      :style="{ padding: '4px 8px 6px' }"
    >
      <div
        v-for="(img, i) in images"
        :key="img.image_id"
        class="relative"
        :style="{
          width: '44px',
          height: '44px',
          borderRadius: '8px',
          overflow: 'hidden',
          border: '1px solid var(--line-2)',
          background: 'var(--card-2)',
        }"
        :title="img.name"
      >
        <img
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
      class="flex items-center gap-1.5"
      :style="{ padding: '5px 6px 5px 8px' }"
    >
      <button
        type="button"
        class="inline-flex items-center gap-1 transition"
        :disabled="isUploading"
        :style="{
          height: '26px',
          padding: '0 9px',
          borderRadius: '999px',
          fontSize: '11px',
          background: 'var(--card-2)',
          color: isUploading ? 'var(--ink-4)' : 'var(--ink-2)',
          border: '1px solid var(--line)',
          cursor: isUploading ? 'wait' : 'pointer',
        }"
        @click="pickImages"
      >
        <Icon name="image" :size="11"/>
        <span>{{ isUploading ? "上传中…" : "图片" }}</span>
      </button>
      <button
        type="button"
        class="inline-flex items-center gap-1 transition"
        :disabled="isSuggesting"
        :style="{
          height: '26px',
          padding: '0 9px',
          borderRadius: '999px',
          fontSize: '11px',
          background: 'rgba(245,192,66,0.18)',
          color: isSuggesting ? 'var(--ink-4)' : '#7a5400',
          border: '1px solid rgba(245,192,66,0.36)',
          cursor: isSuggesting ? 'wait' : 'pointer',
        }"
        @click="onSuggest"
      >
        <Icon name="wand" :size="11"/>
        <span>{{ isSuggesting ? "生成中…" : "AI 建议" }}</span>
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
        :title="canSave ? '发布草稿' : '请先写一些内容或加张图'"
        @click="onPublish"
      >
        <Icon name="play" :size="11"/>
        <span>{{ isSaving ? "保存中…" : `发布第 ${nextTier} 层` }}</span>
      </button>
    </div>

    <!-- Hidden multi-select picker -->
    <input
      ref="fileInputRef"
      type="file"
      accept="image/jpeg,image/png,image/webp,image/jpg"
      multiple
      style="display: none"
      @change="onFilesPicked"
    />
  </div>
</template>
