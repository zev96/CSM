<template>
  <div class="modal-backdrop" @click.self="$emit('close')">
    <div class="modal">
      <h2>平台登录状态</h2>
      <p>登录后 cookie 会保存在本地 profile，下次抓取自动复用。</p>
      <ul>
        <li v-for="p in platforms" :key="p">
          <strong>{{ label(p) }}</strong>
          <span class="status" :data-ok="loginStatus[p]">
            {{ loginStatus[p] ? "已登录" : "未登录" }}
          </span>
          <button v-if="!openFor || openFor === p" @click="onLogin(p)" :disabled="openFor === p">
            {{ openFor === p ? "已打开浏览器…" : "登录 / 重新登录" }}
          </button>
          <button
            v-if="openFor === p" class="primary"
            @click="onConfirm(p)"
          >我登好了</button>
        </li>
      </ul>
      <footer>
        <button @click="$emit('close')">关闭</button>
      </footer>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from "vue"
import type { Platform } from "../../stores/mining"

defineProps<{ loginStatus: Record<Platform, boolean> }>()
const emit = defineEmits<{
  close: []
  login: [platform: Platform]
  confirm: [platform: Platform]
}>()

const platforms: Platform[] = ["douyin", "bilibili", "kuaishou"]
const openFor = ref<Platform | null>(null)

function label(p: Platform) {
  return { douyin: "抖音", bilibili: "B站", kuaishou: "快手" }[p]
}
async function onLogin(p: Platform) {
  openFor.value = p
  emit("login", p)
}
async function onConfirm(p: Platform) {
  emit("confirm", p)
  openFor.value = null
}
</script>

<style scoped>
.modal-backdrop { position: fixed; inset: 0; background: rgba(0,0,0,0.4); display: flex; align-items: center; justify-content: center; z-index: 100; }
.modal { background: white; padding: 24px; border-radius: 8px; min-width: 420px; display: flex; flex-direction: column; gap: 12px; }
ul { list-style: none; padding: 0; }
li { display: grid; grid-template-columns: 80px 80px 1fr auto; gap: 12px; align-items: center; padding: 8px 0; border-bottom: 1px solid #eee; }
.status[data-ok="true"] { color: #155724; }
.status[data-ok="false"] { color: #d9534f; }
.primary { background: #2d6cdf; color: white; padding: 4px 10px; border-radius: 4px; border: 0; }
footer { display: flex; justify-content: flex-end; }
</style>
