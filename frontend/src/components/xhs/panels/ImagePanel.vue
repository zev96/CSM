<script setup lang="ts">
/**
 * 图片面板（设计稿 §5「图片」/ P2）。上传 / 缩略图 / 拖拽排序 / 设封面 / 删除。
 * 上传走 store.uploadImage（强制建草稿 → multipart POST → 推 imageIds）；
 * 缩略图 src = sseURL("/api/xhs/images/{id}")；排序用原生 HTML5 拖拽。
 */
import { ref } from "vue";
import Icon from "@/components/ui/Icon.vue";
import { useXhs } from "@/stores/xhs";
import { useSidecar } from "@/stores/sidecar";
import { useToast } from "@/composables/useToast";

const xhs = useXhs();
const sidecar = useSidecar();
const toast = useToast();

const fileInput = ref<HTMLInputElement | null>(null);
const uploading = ref(false);
const dragIndex = ref<number | null>(null);

function thumbUrl(id: string): string {
  return sidecar.sseURL(`/api/xhs/images/${id}`);
}

function openPicker() {
  fileInput.value?.click();
}

async function onFilesPicked(e: Event) {
  const input = e.target as HTMLInputElement;
  const files = Array.from(input.files ?? []);
  if (!files.length) return;
  uploading.value = true;
  try {
    for (const f of files) {
      try {
        await xhs.uploadImage(f);
      } catch {
        toast.error(`「${f.name}」上传失败（仅支持 5MB 内的 jpg/png/webp）`);
      }
    }
  } finally {
    uploading.value = false;
    input.value = ""; // 允许重选同一文件
  }
}

function onDragStart(i: number) {
  dragIndex.value = i;
}
function onDrop(i: number) {
  if (dragIndex.value !== null && dragIndex.value !== i) {
    xhs.reorderImages(dragIndex.value, i);
  }
  dragIndex.value = null;
}
function onDragEnd() {
  dragIndex.value = null;
}
</script>

<template>
  <div class="flex h-full flex-col" :style="{ gap: '12px' }">
    <!-- 上传 -->
    <button type="button" class="xhs-upload-btn" :disabled="uploading" @click="openPicker">
      <Icon name="upload" :size="15" />
      {{ uploading ? '上传中…' : '上传图片' }}
    </button>
    <input
      ref="fileInput"
      type="file"
      accept="image/jpeg,image/png,image/webp"
      multiple
      :style="{ display: 'none' }"
      @change="onFilesPicked"
    />
    <div :style="{ fontSize: '11px', color: 'var(--ink-2)', flexShrink: 0 }">
      支持 jpg / png / webp，单张 ≤ 5MB；拖动缩略图可排序，第一张或设为封面的那张是笔记封面。
    </div>

    <!-- 空态 -->
    <div
      v-if="!xhs.imageIds.length"
      class="flex flex-col items-center justify-center"
      :style="{
        flex: 1, gap: '8px', color: 'var(--ink-2)', fontSize: '13px', textAlign: 'center',
        border: '1px dashed var(--line-2)', borderRadius: '12px', padding: '28px 16px',
      }"
    >
      <Icon name="image" :size="26" />
      <div>还没有图片，点上方「上传图片」添加</div>
    </div>

    <!-- 缩略图网格 -->
    <div
      v-else
      class="min-h-0 flex-1 overflow-y-auto"
      :style="{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '8px', alignContent: 'flex-start' }"
    >
      <div
        v-for="(id, i) in xhs.imageIds"
        :key="id"
        class="xhs-thumb"
        draggable="true"
        :style="{
          position: 'relative', aspectRatio: '1 / 1', borderRadius: '10px', overflow: 'hidden',
          border: i === xhs.coverIndex ? '2px solid var(--primary)' : '1px solid var(--line-2)',
          opacity: dragIndex === i ? 0.4 : 1, cursor: 'grab',
        }"
        @dragstart="onDragStart(i)"
        @dragover.prevent
        @drop="onDrop(i)"
        @dragend="onDragEnd"
      >
        <img
          class="xhs-thumb-img"
          :src="thumbUrl(id)"
          :style="{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }"
          draggable="false"
        />
        <!-- 封面角标 -->
        <span
          v-if="i === xhs.coverIndex"
          :style="{
            position: 'absolute', top: '4px', left: '4px', fontSize: '10px', color: '#fff',
            background: 'var(--primary)', borderRadius: '6px', padding: '1px 6px',
          }"
        >封面</span>
        <!-- 删除 -->
        <button
          type="button"
          class="xhs-thumb-del"
          title="删除"
          :style="{
            position: 'absolute', top: '4px', right: '4px', width: '20px', height: '20px',
            borderRadius: '999px', background: 'rgba(0,0,0,0.5)', color: '#fff', cursor: 'pointer',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }"
          @click="xhs.removeImage(i)"
        ><Icon name="x" :size="12" /></button>
        <!-- 设为封面（当前已是封面时隐藏但保留 DOM，使 findAll 下标一致） -->
        <button
          type="button"
          class="xhs-thumb-cover"
          :style="{
            position: 'absolute', bottom: '0', left: '0', right: '0', fontSize: '10px',
            background: 'rgba(0,0,0,0.45)', color: '#fff', cursor: 'pointer', padding: '2px 0',
            border: 'none',
            display: i !== xhs.coverIndex ? 'block' : 'none',
          }"
          @click="xhs.setCover(i)"
        >设为封面</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.xhs-upload-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  flex-shrink: 0;
  font-size: 13px;
  padding: 9px 14px;
  border-radius: 10px;
  border: 1px solid var(--primary);
  background: var(--primary);
  color: #fff;
  cursor: pointer;
  transition: filter 0.15s;
}
.xhs-upload-btn:hover {
  filter: brightness(0.97);
}
.xhs-upload-btn:disabled {
  opacity: 0.6;
  cursor: default;
}
</style>
