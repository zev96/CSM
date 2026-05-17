<template>
  <div class="card">
    <header>
      <strong>{{ job.keyword }}</strong>
      <span class="status" :data-status="job.status">{{ statusLabel }}</span>
      <button class="cancel" v-if="canCancel" @click="$emit('cancel')">取消</button>
    </header>
    <ul>
      <li v-for="p in job.platforms" :key="p">
        <span class="plat">{{ platformLabel(p) }}</span>
        <progress :value="progressOf(p).got" :max="progressOf(p).target"></progress>
        <span class="counts">{{ progressOf(p).got }} / {{ progressOf(p).target }}</span>
        <span class="phase" :data-phase="progressOf(p).phase">{{ phaseLabel(progressOf(p).phase) }}</span>
      </li>
    </ul>
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue"
import type { MiningJob, Platform, PlatformProgress } from "../../stores/mining"

const props = defineProps<{ job: MiningJob }>()
defineEmits<{ cancel: [] }>()

const canCancel = computed(() => ["pending", "running"].includes(props.job.status))
const statusLabel = computed(() => {
  return {
    pending: "排队中", running: "运行中", done: "完成",
    partial_done: "部分完成", failed: "失败",
    cancelled: "已取消", interrupted: "中断",
  }[props.job.status] || props.job.status
})

function progressOf(p: Platform): PlatformProgress {
  return props.job.progress[p] || { got: 0, target: props.job.target_per_platform, phase: "queued" }
}
function platformLabel(p: Platform) {
  return { douyin: "抖音", bilibili: "B站", kuaishou: "快手" }[p]
}
function phaseLabel(phase: string) {
  return {
    queued: "排队", launching: "启动浏览器", scrolling: "滚动加载",
    done: "✓", failed: "失败", needs_login: "需登录",
    risk_control: "风控", cancelled: "已取消",
  }[phase] || phase
}
</script>

<style scoped>
.card { display: flex; flex-direction: column; gap: 8px; }
header { display: flex; gap: 12px; align-items: center; }
.status { padding: 2px 8px; border-radius: 4px; background: #eee; font-size: 12px; }
.status[data-status="done"] { background: #d4edda; }
.status[data-status="failed"] { background: #f8d7da; }
.status[data-status="partial_done"] { background: #fff3cd; }
.cancel { margin-left: auto; }
ul { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 4px; }
li { display: grid; grid-template-columns: 60px 1fr 80px 100px; gap: 12px; align-items: center; }
.phase[data-phase="needs_login"] { color: #d9534f; }
.phase[data-phase="risk_control"] { color: #d9534f; }
</style>
