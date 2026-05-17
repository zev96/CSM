<template>
  <div class="mining-view">
    <header class="mining-header">
      <h1>引流 · 视频抓取</h1>
      <div class="actions">
        <button @click="showStart = true" :disabled="store.hasRunningJob">+ 新任务</button>
        <button @click="showLogin = true">⚙ 平台登录</button>
        <a :href="exportUrl" download="mining_videos.csv">⏬ 导出 CSV</a>
      </div>
    </header>

    <section v-if="store.activeJob" class="active-job">
      <JobProgressCard :job="store.activeJob" @cancel="store.cancelActive" />
    </section>

    <section class="filters">
      <div class="seg">
        <button
          v-for="opt in commentedOpts" :key="opt.value"
          :class="{ active: store.filters.commented === opt.value }"
          @click="setCommented(opt.value)"
        >{{ opt.label }}</button>
      </div>
      <select v-model="store.filters.platform" @change="onFilterChange">
        <option :value="null">全部平台</option>
        <option value="douyin">抖音</option>
        <option value="bilibili">B 站</option>
        <option value="kuaishou">快手</option>
      </select>
      <input v-model="store.filters.q" placeholder="搜标题或作者" @input="onSearchInput" />
    </section>

    <VideoTable
      :videos="store.videos" :total="store.total" :loading="store.loading"
      @delete="store.deleteVideo"
    />

    <StartJobModal
      v-if="showStart" :login-status="store.loginStatus"
      @close="showStart = false"
      @submit="onStartSubmit"
    />
    <PlatformLoginPanel
      v-if="showLogin" :login-status="store.loginStatus"
      @close="onLoginPanelClose"
      @login="onLogin" @confirm="onConfirmLogin"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, computed } from "vue"
import { useMiningStore, type Platform, type CommentedFilter } from "../stores/mining"
import JobProgressCard from "../components/mining/JobProgressCard.vue"
import VideoTable from "../components/mining/VideoTable.vue"
import StartJobModal from "../components/mining/StartJobModal.vue"
import PlatformLoginPanel from "../components/mining/PlatformLoginPanel.vue"

const store = useMiningStore()
const showStart = ref(false)
const showLogin = ref(false)

const commentedOpts: { value: CommentedFilter; label: string }[] = [
  { value: "0", label: "未评论" },
  { value: "1", label: "已评论" },
  { value: "all", label: "全部" },
]

const exportUrl = computed(() => {
  const p = new URLSearchParams()
  if (store.filters.keyword) p.set("keyword", store.filters.keyword)
  if (store.filters.platform) p.set("platform", store.filters.platform)
  p.set("commented", store.filters.commented)
  if (store.filters.q) p.set("q", store.filters.q)
  return `/api/mining/videos/export.csv?${p}`
})

function setCommented(v: CommentedFilter) {
  store.filters.commented = v
  store.refreshVideos()
}
function onFilterChange() { store.refreshVideos() }

let searchDebounce: number | null = null
function onSearchInput() {
  if (searchDebounce) clearTimeout(searchDebounce)
  searchDebounce = window.setTimeout(() => store.refreshVideos(), 300)
}

async function onStartSubmit(payload: { keyword: string; platforms: Platform[]; target: number }) {
  showStart.value = false
  await store.startJob(payload.keyword, payload.platforms, payload.target)
}

async function onLogin(p: Platform) { await store.startLogin(p) }
async function onConfirmLogin(p: Platform) { await store.confirmLogin(p) }
function onLoginPanelClose() { showLogin.value = false; store.refreshLoginStatus() }

onMounted(async () => {
  await store.refreshLoginStatus()
  await store.refreshVideos()
})
</script>

<style scoped>
.mining-view { display: flex; flex-direction: column; height: 100%; padding: 16px; gap: 16px; }
.mining-header { display: flex; justify-content: space-between; align-items: center; }
.actions { display: flex; gap: 8px; }
.actions a { padding: 6px 12px; border: 1px solid #ddd; border-radius: 6px; text-decoration: none; color: inherit; }
.active-job { padding: 12px; border: 1px solid #ffd; background: #fffef0; border-radius: 8px; }
.filters { display: flex; gap: 8px; align-items: center; }
.seg button { padding: 6px 12px; border: 1px solid #ddd; background: white; }
.seg button.active { background: #2d6cdf; color: white; border-color: #2d6cdf; }
.seg button:first-child { border-radius: 6px 0 0 6px; }
.seg button:last-child { border-radius: 0 6px 6px 0; }
</style>
