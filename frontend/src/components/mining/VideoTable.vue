<template>
  <div class="video-table">
    <p v-if="loading">加载中…</p>
    <p v-else-if="!videos.length">没有视频。换个筛选或起个新任务。</p>
    <article v-for="v in videos" :key="v.id" class="video-row">
      <img :src="v.cover_url || ''" alt="" class="cover" loading="lazy" />
      <div class="body">
        <header>
          <strong>{{ v.title || "(无标题)" }}</strong>
          <span class="plat" :data-platform="v.platform">{{ platformLabel(v.platform) }}</span>
          <span
            v-if="v.already_commented"
            class="commented-badge"
            :title="commentedTooltip(v)"
          >已评论</span>
        </header>
        <footer>
          <span>{{ v.author_name }}</span>
          <span v-if="v.play_count !== null">▶ {{ fmt(v.play_count) }}</span>
          <span v-if="v.like_count !== null">👍 {{ fmt(v.like_count) }}</span>
          <span v-if="v.duration_sec">⏱ {{ fmtDur(v.duration_sec) }}</span>
          <span class="kw" v-for="k in v.source_keywords" :key="k">#{{ k }}</span>
        </footer>
      </div>
      <div class="actions">
        <button disabled title="第二期上线">写评论计划</button>
        <a :href="v.url" target="_blank" rel="noopener">打开</a>
        <button @click="$emit('delete', v.id)">剔除</button>
      </div>
    </article>
  </div>
</template>

<script setup lang="ts">
import type { Video, Platform } from "../../stores/mining"

defineProps<{ videos: Video[]; total: number; loading: boolean }>()
defineEmits<{ delete: [id: number] }>()

function platformLabel(p: Platform) {
  return { douyin: "抖音", bilibili: "B站", kuaishou: "快手" }[p]
}
function fmt(n: number): string {
  if (n >= 10000) return (n / 10000).toFixed(1) + "万"
  if (n >= 1000) return (n / 1000).toFixed(1) + "k"
  return String(n)
}
function fmtDur(s: number): string {
  const m = Math.floor(s / 60), ss = s % 60
  return `${m}:${String(ss).padStart(2, "0")}`
}
function commentedTooltip(v: Video): string {
  const src = v.commented_source === "monitor_task" ? "评论监控任务" : v.commented_source
  return `来自${src}${v.commented_at ? "，最近检查 " + v.commented_at.slice(0, 10) : ""}`
}
</script>

<style scoped>
.video-row { display: grid; grid-template-columns: 120px 1fr 200px; gap: 12px; padding: 12px; border-bottom: 1px solid #eee; }
.cover { width: 120px; height: 80px; object-fit: cover; background: #ddd; border-radius: 4px; }
.body { display: flex; flex-direction: column; gap: 4px; }
header { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.plat { font-size: 11px; padding: 2px 6px; border-radius: 3px; background: #f0f0f0; }
.plat[data-platform="douyin"] { background: #000; color: white; }
.plat[data-platform="bilibili"] { background: #00a1d6; color: white; }
.plat[data-platform="kuaishou"] { background: #ff6633; color: white; }
.commented-badge {
  font-size: 11px; padding: 2px 6px; border-radius: 3px;
  background: #d4edda; color: #155724; cursor: help;
}
footer { display: flex; gap: 8px; color: #666; font-size: 13px; flex-wrap: wrap; }
.kw { color: #2d6cdf; }
.actions { display: flex; flex-direction: column; gap: 6px; align-items: stretch; }
.actions button[disabled] { opacity: 0.4; cursor: not-allowed; }
</style>
