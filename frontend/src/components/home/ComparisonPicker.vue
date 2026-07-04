<script setup lang="ts">
/**
 * 横评型号多选弹层 —— 从品牌记忆（useMaterials().list()）拉型号，按
 * role（主推 / 竞品）分组成 chip，多选 2–4 个回填 v-model 的 string[]。
 *
 * 数据源：GET /api/brand-memory → materials.models: BrandModelRow[]，
 * row.role 是中文串「主推」/「竞品」；多选 value = row.model（full-stem），
 * 展示 = row.brand + " " + row.model。
 */
import { computed, onMounted } from "vue";
import { useMaterials } from "@/stores/materials";
import Btn from "@/components/ui/Btn.vue";
import Icon from "@/components/ui/Icon.vue";

const props = defineProps<{ modelValue: string[]; open: boolean }>();
const emit = defineEmits<{
  (e: "update:modelValue", v: string[]): void;
  (e: "update:open", v: boolean): void;
}>();

const materials = useMaterials();
onMounted(() => { void materials.list(); });

const own = computed(() => materials.models.filter((m) => m.role === "主推"));
const competitor = computed(() => materials.models.filter((m) => m.role !== "主推"));
const MAX = 4;

function toggle(model: string) {
  const cur = [...props.modelValue];
  const i = cur.indexOf(model);
  if (i >= 0) cur.splice(i, 1);
  else if (cur.length < MAX) cur.push(model);
  emit("update:modelValue", cur);
}
function isSel(model: string) { return props.modelValue.includes(model); }
function close() { emit("update:open", false); }
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="fixed inset-0 z-50 flex items-center justify-center"
         :style="{ background: 'rgba(0,0,0,0.28)' }" @click.self="close">
      <div class="anim-up" :style="{ width: '440px', maxHeight: '70vh', overflowY: 'auto',
           background: 'var(--card)', borderRadius: '16px', padding: '20px' }">
        <div class="flex items-center justify-between" :style="{ marginBottom: '12px' }">
          <span class="font-medium">选择对比型号（2–4 个）</span>
          <button type="button" @click="close"><Icon name="x" :size="16" /></button>
        </div>
        <div v-if="own.length" :style="{ marginBottom: '10px' }">
          <div class="text-[11px]" :style="{ color: 'var(--ink-3)', marginBottom: '6px' }">主推</div>
          <div class="flex flex-wrap gap-2">
            <button v-for="m in own" :key="m.model" type="button"
                    class="qc-model-chip" :data-sel="isSel(m.model)"
                    :style="{ padding: '5px 10px', borderRadius: '8px', fontSize: '12px',
                      border: '1px solid var(--line)',
                      background: isSel(m.model) ? 'var(--primary-soft)' : 'var(--frosted-bg)' }"
                    @click="toggle(m.model)">{{ m.brand }} {{ m.model }}</button>
          </div>
        </div>
        <div v-if="competitor.length">
          <div class="text-[11px]" :style="{ color: 'var(--ink-3)', marginBottom: '6px' }">竞品</div>
          <div class="flex flex-wrap gap-2">
            <button v-for="m in competitor" :key="m.model" type="button"
                    class="qc-model-chip" :data-sel="isSel(m.model)"
                    :style="{ padding: '5px 10px', borderRadius: '8px', fontSize: '12px',
                      border: '1px solid var(--line)',
                      background: isSel(m.model) ? 'var(--primary-soft)' : 'var(--frosted-bg)' }"
                    @click="toggle(m.model)">{{ m.brand }} {{ m.model }}</button>
          </div>
        </div>
        <div class="flex justify-end" :style="{ marginTop: '16px' }">
          <Btn variant="dark" :disabled="modelValue.length < 2" @click="close">
            完成（{{ modelValue.length }}）
          </Btn>
        </div>
      </div>
    </div>
  </Teleport>
</template>
