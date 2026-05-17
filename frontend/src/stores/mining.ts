/**
 * Mining store — Pinia + SSE subscription for video mining jobs.
 *
 * Uses the shared sidecar bridge (``useSidecar().client`` + the ``subscribe``
 * helper from ``@/api/client``) instead of bare ``fetch``. Bare fetch would
 * use relative URLs that hit Vite's dev server (returning index.html) and
 * skip the Bearer-token header that the sidecar requires.
 *
 * Phase 2/3 (outreach 评论楼 + AI):
 *   - ``commentsByVideo`` caches the comment list keyed by video_id; UI
 *     pulls from here so components can render the latest state without
 *     re-fetching on every interaction.
 *   - ``aiSummaryLoading`` / ``commentSavingByVideo`` are spinner flags
 *     used by VideoCard / CommentComposer to disable buttons during
 *     in-flight RPCs.
 *   - AI routes return 503 with ``code === "llm_not_configured"`` when
 *     the user hasn't picked a default provider yet. We unwrap that into
 *     ``LLMNotConfiguredError`` so callers can show the "去设置" action
 *     toast without inspecting axios internals.
 */
import { defineStore } from "pinia"
import { ref, computed } from "vue"
import type { AxiosError } from "axios"

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
  ai_summary?: string | null
}

export interface Comment {
  id: number
  tier: number
  text: string
  image_ids: string[]
  /** Server-computed: absolute-relative paths like "/api/mining/images/{id}". */
  image_urls: string[]
  status: "draft" | "assigned" | "done"
  source: "manual" | "ai_suggested"
  created_at: string
  updated_at: string
}

export interface CreateCommentPayload {
  tier: number
  text: string
  image_ids: string[]
  source: "manual" | "ai_suggested"
}

export interface UpdateCommentPayload {
  text?: string
  image_ids?: string[]
  status?: Comment["status"]
}

/**
 * Thrown when the sidecar returns 503 + code="llm_not_configured" from
 * the AI routes. Callers (composer / video card) catch this to show
 * a "去设置" toast instead of a generic error.
 */
export class LLMNotConfiguredError extends Error {
  constructor(message: string = "请先在设置中配置 AI 服务") {
    super(message)
    this.name = "LLMNotConfiguredError"
  }
}

function _wrapLLMError(err: unknown): never {
  const axErr = err as AxiosError<{ code?: string; detail?: string; msg?: string }>
  const resp = axErr?.response
  if (resp?.status === 503 && resp.data?.code === "llm_not_configured") {
    throw new LLMNotConfiguredError(resp.data.detail || resp.data.msg)
  }
  throw err
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

  // Phase 2/3 — keyed by video_id. Sorted by tier asc as returned by API.
  const commentsByVideo = ref<Record<number, Comment[]>>({})
  // Spinner state for AI summary buttons in VideoCard.
  const aiSummaryLoading = ref<Record<number, boolean>>({})
  // Spinner state for "发布第 N 层" in CommentComposer.
  const commentSavingByVideo = ref<Record<number, boolean>>({})

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

  // ── Phase 2: comment CRUD ──────────────────────────────────────────────
  async function loadComments(videoId: number): Promise<Comment[]> {
    const resp = await api().get<{ comments: Comment[] }>(
      `/api/mining/videos/${videoId}/comments`,
    )
    const list = resp.data.comments ?? []
    commentsByVideo.value[videoId] = list
    return list
  }

  async function createComment(
    videoId: number,
    payload: CreateCommentPayload,
  ): Promise<Comment> {
    commentSavingByVideo.value[videoId] = true
    try {
      const resp = await api().post<Comment>(
        `/api/mining/videos/${videoId}/comments`,
        payload,
      )
      const created = resp.data
      const list = commentsByVideo.value[videoId] ?? []
      const next = [...list, created].sort((a, b) => a.tier - b.tier)
      commentsByVideo.value[videoId] = next
      return created
    } finally {
      commentSavingByVideo.value[videoId] = false
    }
  }

  async function updateComment(
    commentId: number,
    payload: UpdateCommentPayload,
  ): Promise<Comment> {
    const resp = await api().patch<Comment>(
      `/api/mining/comments/${commentId}`,
      payload,
    )
    const updated = resp.data
    // Find which video this belongs to and replace in-place.
    for (const [vidKey, list] of Object.entries(commentsByVideo.value)) {
      const idx = list.findIndex(c => c.id === commentId)
      if (idx !== -1) {
        const vid = Number(vidKey)
        const next = list.slice()
        next[idx] = updated
        commentsByVideo.value[vid] = next.sort((a, b) => a.tier - b.tier)
        break
      }
    }
    return updated
  }

  async function deleteComment(commentId: number): Promise<void> {
    await api().delete(`/api/mining/comments/${commentId}`)
    for (const [vidKey, list] of Object.entries(commentsByVideo.value)) {
      const idx = list.findIndex(c => c.id === commentId)
      if (idx !== -1) {
        const vid = Number(vidKey)
        commentsByVideo.value[vid] = list.filter(c => c.id !== commentId)
        break
      }
    }
  }

  /**
   * Upload an image for a comment. Returns the server's image_id + URL
   * which the composer then passes back in ``createComment.image_ids``.
   */
  async function uploadImage(
    videoId: number,
    file: File,
  ): Promise<{ image_id: string; url: string; size: number }> {
    const form = new FormData()
    form.append("video_id", String(videoId))
    form.append("file", file)
    const resp = await api().post<{ image_id: string; url: string; size: number }>(
      "/api/mining/comments/images",
      form,
      { headers: { "Content-Type": "multipart/form-data" } },
    )
    return resp.data
  }

  // ── Phase 3: AI summary + suggest ──────────────────────────────────────
  async function summarize(videoId: number, force = false): Promise<string> {
    aiSummaryLoading.value[videoId] = true
    try {
      const resp = await api().post<{ summary: string }>(
        `/api/mining/videos/${videoId}/ai_summary`,
        { force },
      )
      const summary = resp.data.summary
      const idx = videos.value.findIndex(v => v.id === videoId)
      if (idx !== -1) {
        // Replace the entry so reactivity picks up the change cleanly
        // (mutating .ai_summary directly works too, but a new object is
        // safer when other watchers compare by reference).
        videos.value[idx] = { ...videos.value[idx], ai_summary: summary }
      }
      return summary
    } catch (e) {
      _wrapLLMError(e)
    } finally {
      aiSummaryLoading.value[videoId] = false
    }
  }

  async function suggestComment(
    videoId: number,
    tier: number,
    previous_tiers: string[],
  ): Promise<string> {
    try {
      const resp = await api().post<{ suggestion: string }>(
        `/api/mining/videos/${videoId}/ai_suggest_comment`,
        { tier, previous_tiers },
      )
      return resp.data.suggestion
    } catch (e) {
      _wrapLLMError(e)
    }
  }

  /**
   * Toggle ``videos.already_commented`` for a batch. On success we
   * refresh the list so the visible cards drop out of "待评论".
   */
  async function bulkMarkCommented(ids: number[], value: boolean): Promise<number> {
    const resp = await api().patch<{ updated: number }>(
      "/api/mining/videos/bulk_mark_commented",
      { video_ids: ids, value },
    )
    await refreshVideos()
    return resp.data.updated
  }

  return {
    activeJob, videos, total, loading, filters, loginStatus,
    commentsByVideo, aiSummaryLoading, commentSavingByVideo,
    hasRunningJob,
    startJob, cancelActive, refreshVideos,
    refreshLoginStatus, startLogin, confirmLogin,
    deleteVideo, exportUrl,
    loadComments, createComment, updateComment, deleteComment,
    uploadImage, summarize, suggestComment, bulkMarkCommented,
  }
})
