/**
 * Mining store — Pinia + SSE subscription for video mining jobs.
 *
 * Uses the shared sidecar bridge (``useSidecar().client`` + the ``subscribe``
 * helper from ``@/api/client``) instead of bare ``fetch``. Bare fetch would
 * use relative URLs that hit Vite's dev server (returning index.html) and
 * skip the Bearer-token header that the sidecar requires.
 */
import { defineStore } from "pinia"
import { ref, computed } from "vue"

import { subscribe } from "@/api/client"
import { useSidecar } from "@/stores/sidecar"

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

function api() {
  return useSidecar().client
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

  // SSE teardown function from `subscribe()`. Null when no stream is open.
  let stopSse: (() => void) | null = null

  async function startJob(keyword: string, platforms: Platform[], target: number): Promise<number> {
    const resp = await api().post<{ job_id: number; job: MiningJob }>(
      "/api/mining/jobs",
      { keyword, platforms, target_per_platform: target },
    )
    activeJob.value = resp.data.job
    subscribeToJob(resp.data.job_id)
    return resp.data.job_id
  }

  function subscribeToJob(jobId: number) {
    if (stopSse) { stopSse(); stopSse = null }
    stopSse = subscribe(`/api/mining/jobs/${jobId}/events`, {
      "job.progress": (d: any) => {
        if (activeJob.value && activeJob.value.id === d.job_id) {
          activeJob.value.progress[d.platform as Platform] = {
            got: d.got, target: d.target, phase: d.phase, note: d.note,
          }
        }
      },
      "job.platform_done": (d: any) => {
        if (activeJob.value && activeJob.value.id === d.job_id) {
          activeJob.value.progress[d.platform as Platform] = {
            ...(activeJob.value.progress[d.platform as Platform] || { target: 50 }),
            got: d.count,
            phase: d.status === "done" ? "done" : d.status,
            note: d.error || "",
          }
        }
      },
      "job.finished": (d: any) => {
        if (activeJob.value && activeJob.value.id === d.job_id) {
          activeJob.value.status = d.summary.status
          activeJob.value.finished_at = new Date().toISOString()
        }
        if (stopSse) { stopSse(); stopSse = null }
        refreshVideos()
      },
      "login.required": (d: any) => {
        loginStatus.value[d.platform as Platform] = false
      },
      done: () => {
        if (stopSse) { stopSse(); stopSse = null }
      },
    })
  }

  async function cancelActive() {
    if (activeJob.value === null) return
    try {
      await api().post(`/api/mining/jobs/${activeJob.value.id}/cancel`)
    } catch (e: any) {
      // 409 = already finished. Silently swallow; UI will catch up on next refresh.
      if (e?.response?.status !== 409) throw e
    }
  }

  async function refreshVideos(offset = 0, limit = 50) {
    loading.value = true
    try {
      const params: Record<string, string | number> = {
        commented: filters.value.commented,
        offset, limit,
      }
      if (filters.value.keyword) params.keyword = filters.value.keyword
      if (filters.value.platform) params.platform = filters.value.platform
      if (filters.value.q) params.q = filters.value.q
      const resp = await api().get<{ total: number; videos: Video[] }>(
        "/api/mining/videos",
        { params },
      )
      total.value = resp.data.total
      if (offset === 0) videos.value = resp.data.videos
      else videos.value.push(...resp.data.videos)
    } finally {
      loading.value = false
    }
  }

  async function refreshLoginStatus() {
    const resp = await api().get<Record<Platform, { logged_in: boolean }>>(
      "/api/mining/login/status",
    )
    for (const p of ["douyin", "bilibili", "kuaishou"] as Platform[]) {
      loginStatus.value[p] = resp.data[p]?.logged_in ?? false
    }
  }

  async function startLogin(platform: Platform) {
    await api().post(`/api/mining/login/${platform}`)
  }

  async function confirmLogin(platform: Platform): Promise<boolean> {
    const resp = await api().post<{ logged_in: boolean }>(
      `/api/mining/login/${platform}/confirm`,
    )
    loginStatus.value[platform] = resp.data.logged_in
    return resp.data.logged_in
  }

  async function deleteVideo(id: number) {
    await api().delete(`/api/mining/videos/${id}`)
    videos.value = videos.value.filter(v => v.id !== id)
    total.value = Math.max(0, total.value - 1)
  }

  /** Absolute CSV-export URL including baseURL + token query string. */
  function exportUrl(): string {
    const params = new URLSearchParams()
    params.set("commented", filters.value.commented)
    if (filters.value.keyword) params.set("keyword", filters.value.keyword)
    if (filters.value.platform) params.set("platform", filters.value.platform)
    if (filters.value.q) params.set("q", filters.value.q)
    return useSidecar().sseURL(`/api/mining/videos/export.csv?${params.toString()}`)
  }

  return {
    activeJob, videos, total, loading, filters, loginStatus,
    hasRunningJob,
    startJob, cancelActive, refreshVideos,
    refreshLoginStatus, startLogin, confirmLogin,
    deleteVideo, exportUrl,
  }
})
