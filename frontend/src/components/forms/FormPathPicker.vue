<script setup lang="ts">
import { usePathPicker } from "@/composables/usePathPicker";

import Btn from "@/components/ui/Btn.vue";
import FormInput from "./FormInput.vue";

const props = withDefaults(
  defineProps<{
    modelValue: string | null | undefined;
    placeholder?: string;
    /** Ask for a directory instead of a single file. */
    directory?: boolean;
    /** When file-mode, the file extensions accepted (no dots). */
    extensions?: string[];
    disabled?: boolean;
  }>(),
  { directory: true },
);

const emit = defineEmits<{
  (e: "update:modelValue", v: string | null): void;
  (e: "commit", v: string | null): void;
}>();

const picker = usePathPicker();

async function browse() {
  const picked = await picker.pick({
    title: props.directory ? "选择目录" : "选择文件",
    defaultPath: props.modelValue ?? undefined,
    directory: props.directory,
    extensions: props.extensions,
  });
  if (picked) {
    emit("update:modelValue", picked);
    emit("commit", picked);
  }
}
</script>

<template>
  <div class="flex items-center gap-2">
    <FormInput
      :model-value="modelValue ?? ''"
      :placeholder="placeholder ?? '尚未选择'"
      :disabled="disabled"
      @update:model-value="(v) => $emit('update:modelValue', (v as string) || null)"
      @commit="(v) => $emit('commit', (v as string) || null)"
    />
    <Btn variant="ghost" small :disabled="disabled" @click="browse">选择…</Btn>
  </div>
</template>
