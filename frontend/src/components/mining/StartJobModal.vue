<template>
  <div class="modal-backdrop" @click.self="$emit('close')">
    <div class="modal">
      <h2>新建抓取任务</h2>
      <label>关键词 <input v-model="keyword" autofocus /></label>
      <fieldset>
        <legend>平台</legend>
        <label v-for="p in allPlatforms" :key="p">
          <input type="checkbox" :value="p" v-model="platforms" />
          {{ label(p) }}
          <span v-if="!loginStatus[p]" class="warn">未登录</span>
        </label>
      </fieldset>
      <label>
        每平台抓取数量：{{ target }}
        <input type="range" min="10" max="200" step="10" v-model.number="target" />
      </label>
      <footer>
        <button @click="$emit('close')">取消</button>
        <button
          class="primary"
          :disabled="!keyword.trim() || platforms.length === 0"
          @click="onSubmit"
        >开始抓取</button>
      </footer>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from "vue"
import type { Platform } from "../../stores/mining"

const props = defineProps<{ loginStatus: Record<Platform, boolean> }>()
const emit = defineEmits<{
  close: []
  submit: [payload: { keyword: string; platforms: Platform[]; target: number }]
}>()

const keyword = ref("")
const platforms = ref<Platform[]>(
  (Object.keys(props.loginStatus) as Platform[]).filter(p => props.loginStatus[p])
)
const target = ref(50)
const allPlatforms: Platform[] = ["douyin", "bilibili", "kuaishou"]

function label(p: Platform) {
  return { douyin: "抖音", bilibili: "B站", kuaishou: "快手" }[p]
}

function onSubmit() {
  emit("submit", { keyword: keyword.value.trim(), platforms: platforms.value, target: target.value })
}
</script>

<style scoped>
.modal-backdrop {
  position: fixed; inset: 0; background: rgba(0,0,0,0.4);
  display: flex; align-items: center; justify-content: center; z-index: 100;
}
.modal { background: white; padding: 24px; border-radius: 8px; min-width: 360px; display: flex; flex-direction: column; gap: 12px; }
label { display: flex; flex-direction: column; gap: 4px; }
fieldset { border: 1px solid #ddd; padding: 8px; border-radius: 4px; }
fieldset label { flex-direction: row; gap: 6px; align-items: center; }
.warn { color: #d9534f; font-size: 12px; }
footer { display: flex; justify-content: flex-end; gap: 8px; }
.primary { background: #2d6cdf; color: white; padding: 6px 16px; border-radius: 4px; border: 0; }
.primary[disabled] { opacity: 0.4; }
</style>
