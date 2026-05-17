import { defineStore } from "pinia"
import { ref, computed } from "vue"

export type Platform = "douyin" | "bilibili" | "kuaishou"
export type CommentedFilter = "0" | "1" | "all"

export interface PlatformProgress {
  got: number
  target: number
  phase: string
  note?: string
}

export interface MiningJob {
  id: number
  keyword: string
  platforms: Platform[]
  target_per_platform: number
  status: string
  progress: Record<Platform, PlatformProgress>
  error_message: string
  created_at: string
  started_at: string | null
  finished_at: string | null
}

export interface Video {
  id: number
  platform: Platform
  platform_video_id: string
  url: string
  title: string
  author_name: string
  author_id: string
  cover_url: string
  duration_sec: number | null
  play_count: number | null
  like_count: number | null
  published_at: string | null
  excluded: boolean
  already_commented: boolean
  commented_source: string | null
  commented_at: string | null
  first_seen_at: string
  source_keywords: string[]
}

const API = "/api/mining"

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(API + path, init)
  if (!r.ok) throw new Error(`${r.status}: ${await r.text()}`)
  return r.json()
}

export const useMiningStore = defineStore("mining", () => {
  const activeJob = ref<MiningJob | null>(null)
  const videos = ref<Video[]>([])
  const total = ref(0)
  const loading = ref(false)
  const filters = ref({
    keyword: null as string | null,
    platform: null as Platform | null,
    commented: "0" as CommentedFilter,
    q: "",
  })
  const loginStatus = ref<Record<Platform, boolean>>({
    douyin: false, bilibili: false, kuaishou: false,
  })

  const hasRunningJob = computed(
    () => activeJob.value !== null
      && ["pending", "running"].includes(activeJob.value.status)
  )

  let eventSource: EventSource | null = null

  async function startJob(keyword: string, platforms: Platform[], target: number): Promise<number> {
    const r = await apiFetch<{ job_id: number; job: MiningJob }>("/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ keyword, platforms, target_per_platform: target }),
    })
    activeJob.value = r.job
    subscribe(r.job_id)
    return r.job_id
  }

  function subscribe(jobId: number) {
    if (eventSource) eventSource.close()
    eventSource = new EventSource(`${API}/jobs/${jobId}/events`)
    eventSource.addEventListener("job.progress", (e: MessageEvent) => {
      const d = JSON.parse(e.data)
      if (activeJob.value && activeJob.value.id === d.job_id) {
        activeJob.value.progress[d.platform as Platform] = {
          got: d.got, target: d.target, phase: d.phase, note: d.note,
        }
      }
    })
    eventSource.addEventListener("job.platform_done", (e: MessageEvent) => {
      const d = JSON.parse(e.data)
      if (activeJob.value && activeJob.value.id === d.job_id) {
        activeJob.value.progress[d.platform as Platform] = {
          ...(activeJob.value.progress[d.platform as Platform] || { target: 50 }),
          got: d.count,
          phase: d.status === "done" ? "done" : d.status,
          note: d.error || "",
        }
      }
    })
    eventSource.addEventListener("job.finished", (e: MessageEvent) => {
      const d = JSON.parse(e.data)
      if (activeJob.value && activeJob.value.id === d.job_id) {
        activeJob.value.status = d.summary.status
        activeJob.value.finished_at = new Date().toISOString()
      }
      eventSource?.close()
      eventSource = null
      refreshVideos()
    })
    eventSource.addEventListener("login.required", (e: MessageEvent) => {
      const d = JSON.parse(e.data)
      loginStatus.value[d.platform as Platform] = false
    })
    eventSource.addEventListener("done", () => {
      eventSource?.close()
      eventSource = null
    })
  }

  async function cancelActive() {
    if (activeJob.value === null) return
    await fetch(`${API}/jobs/${activeJob.value.id}/cancel`, { method: "POST" })
  }

  async function refreshVideos(offset = 0, limit = 50) {
    loading.value = true
    try {
      const params = new URLSearchParams()
      if (filters.value.keyword) params.set("keyword", filters.value.keyword)
      if (filters.value.platform) params.set("platform", filters.value.platform)
      params.set("commented", filters.value.commented)
      if (filters.value.q) params.set("q", filters.value.q)
      params.set("offset", String(offset))
      params.set("limit", String(limit))
      const r = await apiFetch<{ total: number; videos: Video[] }>(`/videos?${params}`)
      total.value = r.total
      if (offset === 0) videos.value = r.videos
      else videos.value.push(...r.videos)
    } finally {
      loading.value = false
    }
  }

  async function refreshLoginStatus() {
    const r = await apiFetch<Record<Platform, { logged_in: boolean }>>("/login/status")
    for (const p of ["douyin", "bilibili", "kuaishou"] as Platform[]) {
      loginStatus.value[p] = r[p]?.logged_in ?? false
    }
  }

  async function startLogin(platform: Platform) {
    await fetch(`${API}/login/${platform}`, { method: "POST" })
  }

  async function confirmLogin(platform: Platform): Promise<boolean> {
    const r = await apiFetch<{ logged_in: boolean }>(`/login/${platform}/confirm`, { method: "POST" })
    loginStatus.value[platform] = r.logged_in
    return r.logged_in
  }

  async function deleteVideo(id: number) {
    await fetch(`${API}/videos/${id}`, { method: "DELETE" })
    videos.value = videos.value.filter(v => v.id !== id)
    total.value = Math.max(0, total.value - 1)
  }

  return {
    activeJob, videos, total, loading, filters, loginStatus,
    hasRunningJob,
    startJob, cancelActive, refreshVideos,
    refreshLoginStatus, startLogin, confirmLogin,
    deleteVideo,
  }
})
