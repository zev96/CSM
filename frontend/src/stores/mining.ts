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
import { useStaleGuard } from "@/composables/useStaleGuard"
import { useNotifications } from "@/composables/useNotifications"

export type Platform = "douyin" | "bilibili" | "kuaishou" | "xiaohongshu"
export type CommentedFilter = "0" | "1" | "all"

// ── 搜索筛选（按平台分组，与后端 SearchFilters 模型一一对应）──────────
// 值全用平台原生参数格式；UI 只展示各平台真实支持的档位。
export interface DouyinFilters {
  /** 0=不限 1=一天内 7=一周内 182=半年内（抖音只有档位，无任意区间） */
  publish_time: "0" | "1" | "7" | "182"
  /** 0=综合 1=最多点赞 2=最新发布 */
  sort_type: "0" | "1" | "2"
  /** 含 "note" 时走综合搜索并本地过滤图文 */
  content_types: ("video" | "note")[]
}

export interface BilibiliFilters {
  /** totalrank=综合 click=最多点击 pubdate=最新发布 dm=最多弹幕 stow=最多收藏 */
  order: "totalrank" | "click" | "pubdate" | "dm" | "stow"
  /** YYYY-MM-DD，B 站原生支持任意日期区间 */
  time_begin: string | null
  time_end: string | null
}

export interface KuaishouFilters {
  /** 快手无服务端时间参数 —— 抓取后按发布时间本地过滤（产出速率会降低） */
  time_begin: string | null
  time_end: string | null
}

export interface XiaohongshuFilters {
  /** general=综合 time_descending=最新 popularity_descending=最多点赞
   *  comment_descending=最多评论 collect_descending=最多收藏（TikHub 服务端排序） */
  sort_type: "general" | "time_descending" | "popularity_descending" | "comment_descending" | "collect_descending"
  /** all=不限 video=视频笔记 image=图文笔记 */
  note_type: "all" | "video" | "image"
  /** 与抖音同形的档位：0=不限 1=一天内 7=一周内 182=半年内 */
  time_filter: "0" | "1" | "7" | "182"
}

export interface SearchFilters {
  douyin: DouyinFilters
  bilibili: BilibiliFilters
  kuaishou: KuaishouFilters
  xiaohongshu: XiaohongshuFilters
}

export function defaultSearchFilters(): SearchFilters {
  return {
    douyin: { publish_time: "0", sort_type: "0", content_types: ["video"] },
    bilibili: { order: "totalrank", time_begin: null, time_end: null },
    kuaishou: { time_begin: null, time_end: null },
    xiaohongshu: { sort_type: "general", note_type: "all", time_filter: "0" },
  }
}

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
  /** 该 job 通过 video_source_keywords 关联的视频数（list_jobs SQL 聚合）。
   *  TaskListItem 状态派生：> 0 时根据 commented_count 区分 进行中 / 已完成。 */
  video_count?: number
  /** 该 job 关联视频中 already_commented=1 的数量。
   *  = video_count → 用户已完成评论 → 显示「已完成」
   *  < video_count → 用户还有视频未评论 → 显示「进行中」 */
  commented_count?: number
  /** v13：任务创建时的搜索筛选条件（按平台分组）。老任务为空对象。 */
  filters?: Partial<SearchFilters>
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
  /** v13：品牌预筛抓到的前 N 条热评快照（生成语料 + 命中证据）。
   *  null = 未检查（无品牌词任务 / 抓取失败 fail-open）。 */
  top_comments?: { text: string; likes: number | null; author: string }[] | null
  /** v14：该视频下 review_status='pending' 的评论数（审核队列徽标）。 */
  pending_review_count?: number
}

export interface Comment {
  id: number
  video_id?: number
  tier: number
  text: string
  image_ids: string[]
  /** Server-computed: absolute-relative paths like "/api/mining/images/{id}". */
  image_urls: string[]
  status: "draft" | "assigned" | "done"
  source: "manual" | "ai_suggested"
  /** v14 审核状态机：'' = 旧数据/人工（不进审核队列）；pending 仅批量
   *  AI 生成写入；approved 人审通过；synced/executed 留给腾讯文档链路。 */
  review_status: "" | "pending" | "approved" | "synced" | "executed"
  /** 生成时用的模板 id（软引用，模板删了留痕）。 */
  template_id?: number | null
  /** 确定性 AI 味评分（≥3 审核视图标黄）。 */
  ai_flavor_score?: number | null
  reviewed_at?: string | null
  synced_at?: string | null
  created_at: string
  updated_at: string
}

/** 批量 AI 生成的进行中状态（SSE 驱动）。null = 没有批次。 */
export interface GenBatchState {
  active: boolean
  batchId: number
  done: number
  total: number
  generated: number
  failed: number
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

export interface SyncToMonitorRequest {
  task_name_prefix: string
  top_n: number
  schedule_cron?: string | null
}

export interface SyncToMonitorResult {
  created: number
  skipped_dup: number
  skipped_no_draft: number
  errors: Record<string, unknown>[]
}

/** POST /api/mining/sync_to_docs 的返回（P3 腾讯文档同步）。 */
export interface SyncToDocsResult {
  synced_videos: number
  synced_comments: number
  /** 表格「链接」列已有该视频 → 跳过写入、本地补标 synced（防双写）。 */
  skipped_in_doc: number
  /** 超出目标子表实际评论列层数（上限 5，以表头「评论X」列数为准）的楼层数（留在 app 内，保持 approved）。 */
  skipped_extra_tiers: number
  /** 挂图因该层表头无「评论X的图片」列而未写入/未标注的条数。 */
  images_dropped: number
  /** 直接插进表格贴图格的图片张数（insert_image）。 */
  images_inserted: number
  /** 插图失败（文件缺失 / 超大 / 服务端拒绝）的张数——该格已回落写「有图，另发」。 */
  images_failed: number
  /** 服务端无 insert_image 工具或已关闭直传 → 只写「有图，另发」标记的图片张数。 */
  images_unsupported: number
  /** 保存过手动列映射、但表头已变化（列挪位 / 改名）→ 本次退回自动识别的子表名。 */
  mapping_stale: string[]
  /** 每个平台写入了哪张子表的哪个行区间（0-based）。 */
  batches: {
    platform: Platform
    sheet_name: string
    row_start: number
    row_end: number
    videos: number
  }[]
  batch_id: number | null
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
  const bell = useNotifications()
  const videos = ref<Video[]>([])
  const total = ref(0)
  const loading = ref(false)
  // jobs 列表(左栏渲染用)+ 当前选中的 job(右栏视频列表过滤)。
  // currentJobId === null 表示"全部任务"(右栏聚合所有 job 的视频)。
  const jobs = ref<MiningJob[]>([])
  const currentJobId = ref<number | null>(null)
  const filters = ref({
    keyword: null as string | null,
    platform: null as Platform | null,
    // 默认 'all' 这样 commented + uncommented 都取回来,UI 状态 pivot
    // (待评论/已评论/全部)在客户端 reduce,counts 才能算准 — 否则
    // 已评论 永远是 0 因为已评论的根本不会被 fetch。
    commented: "all" as CommentedFilter,
    q: "",
    job_id: null as number | null,
  })
  const loginStatus = ref<Record<Platform, boolean>>({
    douyin: false, bilibili: false, kuaishou: false,
    // 小红书没有浏览器采集路径，永远 false（只在 TikHub 模式可选）。
    xiaohongshu: false,
  })

  // Phase 2/3 — keyed by video_id. Sorted by tier asc as returned by API.
  const commentsByVideo = ref<Record<number, Comment[]>>({})
  // Spinner state for AI summary buttons in VideoCard.
  const aiSummaryLoading = ref<Record<number, boolean>>({})
  // Spinner state for "发布第 N 层" in CommentComposer.
  const commentSavingByVideo = ref<Record<number, boolean>>({})

  // sync-to-monitor state
  const syncingJobId = ref<number | null>(null)
  const syncResult = ref<SyncToMonitorResult | null>(null)
  const syncError = ref<string | null>(null)

  const hasRunningJob = computed(
    () => activeJob.value !== null
      && ["pending", "running"].includes(activeJob.value.status)
  )

  // SSE teardown function from `subscribe()`. Null when no stream is open.
  let stopSse: (() => void) | null = null

  async function startJob(
    keyword: string,
    platforms: Platform[],
    target: number,
    brandKeywords: string[] = [],
    filters: SearchFilters = defaultSearchFilters(),
  ): Promise<number> {
    const resp = await api().post<{ job_id: number; job: MiningJob }>(
      "/api/mining/jobs",
      {
        keyword,
        platforms,
        target_per_platform: target,
        brand_keywords: brandKeywords,
        filters,
      },
    )
    activeJob.value = resp.data.job
    subscribeToJob(resp.data.job_id)
    // Left-column task list must show the new task immediately. Don't await
    // — fire-and-forget; the SSE handlers will keep mirroring once it lands.
    loadJobs().catch(() => { /* non-fatal, list refreshes again on finish */ })
    return resp.data.job_id
  }

  /** Patch one job inside jobs[] in place (reactive-safe). */
  function _patchJobInList(jobId: number, patch: (j: MiningJob) => MiningJob) {
    const idx = jobs.value.findIndex(j => j.id === jobId)
    if (idx !== -1) jobs.value[idx] = patch(jobs.value[idx])
  }

  const RUNNING_STATUSES = ["pending", "running"]
  const isRunningStatus = (s: unknown) => RUNNING_STATUSES.includes(String(s ?? ""))

  /**
   * 活跃任务「running → 终态」的统一收尾：推通知（取消静默）、关流、刷视频列表
   * 和任务列表。三条路径（SSE job.finished / 断线快照 / loadJobs 对账）都走
   * 这里；调用方负责只在真正发生状态转换时调用（wasRunning 判定），所以
   * 不会重复推通知。
   */
  function _settleFinished(status: string, keyword: string) {
    if (stopSse) { stopSse(); stopSse = null }
    if (status !== "cancelled") {
      // 用户主动取消不推「完成」通知 —— 与 monitor/article 的取消静默一致
      const ok = status === "done" || status === "completed"
      bell.push("引流任务完成", {
        body: `「${keyword}」${ok ? "全部平台完成" : "部分平台未完成"}`,
        tone: ok ? "success" : "warn",
        category: "mining_done",
      })
    }
    refreshVideos()
    // Refresh the full jobs list to pick up any post-run server-side
    // mutations (e.g. partial_done note updates) we may have missed.
    loadJobs().catch(() => { /* non-fatal */ })
  }

  function subscribeToJob(jobId: number) {
    if (stopSse) { stopSse(); stopSse = null }
    // 一条事件流只属于一个 job。事件体里的 job_id 由 sidecar 的 SSE 路由补入
    // （EventBus 层因参数名撞车会把它剥掉）；老版本 sidecar 没有这个字段时
    // 退回本闭包的 jobId —— 之前所有 handler 都拿 undefined 去比 activeJob.id，
    // 进度 / 完成 / 取消全部失配，任务永远停在「抓取中」。
    const jid = (d: any): number => (typeof d?.job_id === "number" ? d.job_id : jobId)
    const isActive = (d: any) => activeJob.value !== null && activeJob.value.id === jid(d)
    stopSse = subscribe(`/api/mining/jobs/${jobId}/events`, {
      "job.progress": (d: any) => {
        if (isActive(d)) {
          activeJob.value!.progress[d.platform as Platform] = {
            got: d.got, target: d.target, phase: d.phase, note: d.note,
          }
        }
        // Mirror into jobs[] so the left-column progress bar animates live.
        _patchJobInList(jid(d), j => ({
          ...j,
          progress: {
            ...j.progress,
            [d.platform]: { got: d.got, target: d.target, phase: d.phase, note: d.note },
          },
        }))
      },
      "job.platform_done": (d: any) => {
        if (isActive(d)) {
          activeJob.value!.progress[d.platform as Platform] = {
            ...(activeJob.value!.progress[d.platform as Platform] || { target: 50 }),
            got: d.count,
            phase: d.status === "done" ? "done" : d.status,
            note: d.error || "",
          }
        }
        _patchJobInList(jid(d), j => ({
          ...j,
          progress: {
            ...j.progress,
            [d.platform]: {
              ...(j.progress[d.platform as Platform] || { target: 50 }),
              got: d.count,
              phase: d.status === "done" ? "done" : d.status,
              note: d.error || "",
            },
          },
        }))
      },
      "job.finished": (d: any) => {
        const id = jid(d)
        const st = String(d.summary?.status ?? "")
        const wasRunning = isActive(d) && isRunningStatus(activeJob.value!.status)
        if (isActive(d)) {
          activeJob.value!.status = st
          activeJob.value!.finished_at = new Date().toISOString()
        }
        _patchJobInList(id, j => ({
          ...j,
          status: st,
          finished_at: new Date().toISOString(),
        }))
        const kw = activeJob.value && activeJob.value.id === id
          ? activeJob.value.keyword
          : (jobs.value.find(j => j.id === id)?.keyword ?? "")
        if (wasRunning) {
          _settleFinished(st, kw)
        } else if (stopSse) {
          stopSse(); stopSse = null
        }
      },
      "login.required": (d: any) => {
        loginStatus.value[d.platform as Platform] = false
      },
      done: () => {
        if (stopSse) { stopSse(); stopSse = null }
        // 只收到 done 哨兵、没收到 job.finished（runner 线程异常、finalize 落库
        // 失败等）→ 拉快照对账，否则 activeJob 永远停在 running。
        if (hasRunningJob.value) void _refreshActiveJobSnapshot()
      },
    }, {
      onError: () => { void _refreshActiveJobSnapshot() },
    })
  }

  /**
   * SSE 断线 / 服务端事件缺失时的快照对账：拉一次 GET /api/mining/jobs/{id}
   * （routes/mining.py get_job 直接返回 job dict），把错过的 progress/status
   * 补回来。事件队列断线即被 sidecar 回收、错过的 job.finished 不会重放 ——
   * 终态经快照得知时，这里是恢复路径之一，要补齐 finished handler 的收尾。
   * 单飞：EventSource 重连风暴下不会叠加发请求。
   */
  let snapshotInFlight = false
  async function _refreshActiveJobSnapshot() {
    const job = activeJob.value
    if (!job || snapshotInFlight) return
    snapshotInFlight = true
    try {
      const resp = await api().get<MiningJob>(`/api/mining/jobs/${job.id}`)
      const fresh = resp.data
      if (!fresh || typeof fresh.id !== "number") return
      if (!activeJob.value || activeJob.value.id !== fresh.id) return // 期间换了任务
      const wasRunning = isRunningStatus(activeJob.value.status)
      activeJob.value = fresh
      // get_job 不带 list_jobs 才有的聚合列（video_count/commented_count）——
      // 整体替换会把真实计数清零；保留列表里的旧值。
      _patchJobInList(fresh.id, j => ({
        ...fresh,
        video_count: j.video_count,
        commented_count: j.commented_count,
      }))
      if (wasRunning && !isRunningStatus(fresh.status)) {
        _settleFinished(fresh.status, fresh.keyword)
      }
    } catch {
      /* 瞬时网络问题 —— EventSource 自己会重连，下次事件兜底 */
    } finally {
      snapshotInFlight = false
    }
  }

  /**
   * 取消任意 job（POST /api/mining/jobs/{id}/cancel）。后端 409 表示任务已经
   * 结束或根本不在跑 —— 此时前端状态已经落后，立刻对账拉快照 / 刷列表，别让
   * 「抓取中」+ 停止按钮继续骗人。
   */
  async function cancelJob(jobId: number): Promise<void> {
    try {
      await api().post(`/api/mining/jobs/${jobId}/cancel`)
    } catch (e: any) {
      if (e?.response?.status !== 409) throw e
      if (activeJob.value?.id === jobId) await _refreshActiveJobSnapshot()
      else await loadJobs().catch(() => { /* non-fatal */ })
    }
  }

  async function cancelActive() {
    if (activeJob.value === null) return
    await cancelJob(activeJob.value.id)
  }

  // Limit bumped from 50 to 500 (max allowed by backend Query le=500 in
  // sidecar/csm_sidecar/routes/mining.py:233) so the status pills in
  // MiningView (待评论 / 已评论 / 全部) reflect the full set — they're
  // computed client-side from store.videos. If accumulated mining_videos
  // ever exceeds 500 we should add a /api/mining/videos/stats endpoint
  // and stop relying on the loaded list for counts.
  //
  // Stale guard: MiningView wires ``@input="store.refreshVideos()"`` so
  // every keystroke in the search box fires a fresh request. Without a
  // guard, two responses can resolve in arrival-time order — the older
  // one would overwrite ``videos.value`` and ``total.value`` with stale
  // data plus drop the spinner while the newer call is still in flight.
  const videosLoadGuard = useStaleGuard()

  async function refreshVideos(offset = 0, limit = 500) {
    const my = videosLoadGuard.issue()
    loading.value = true
    try {
      const params: Record<string, string | number> = {
        commented: filters.value.commented,
        offset, limit,
      }
      if (filters.value.keyword) params.keyword = filters.value.keyword
      if (filters.value.platform) params.platform = filters.value.platform
      if (filters.value.q) params.q = filters.value.q
      if (filters.value.job_id !== null) params.job_id = filters.value.job_id
      const resp = await api().get<{ total: number; videos: Video[] }>(
        "/api/mining/videos",
        { params },
      )
      if (videosLoadGuard.isStale(my)) return
      total.value = resp.data.total
      if (offset === 0) videos.value = resp.data.videos
      else videos.value.push(...resp.data.videos)
    } finally {
      // Only the latest in-flight call owns the spinner.
      if (!videosLoadGuard.isStale(my)) {
        loading.value = false
      }
    }
  }

  async function refreshLoginStatus() {
    const resp = await api().get<Record<Platform, { logged_in: boolean }>>(
      "/api/mining/login/status",
    )
    for (const p of ["douyin", "bilibili", "kuaishou", "xiaohongshu"] as Platform[]) {
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

  /** Loop-delete; backend has no bulk endpoint and N is small here (<=500). */
  async function bulkDeleteVideos(ids: number[]): Promise<number> {
    let deleted = 0
    for (const id of ids) {
      try {
        await api().delete(`/api/mining/videos/${id}`)
        deleted += 1
      } catch {
        // Skip individual failures (404 if another tab already removed it).
      }
    }
    const idSet = new Set(ids)
    videos.value = videos.value.filter(v => !idSet.has(v.id))
    total.value = Math.max(0, total.value - deleted)
    return deleted
  }

  /**
   * Fetch the recent jobs list for the left-column task panel.
   *
   * 顺手做两件对账（都是兜底，正常路径由 SSE 驱动）：
   *   1. activeJob 还标着 running、列表里它已是终态 → 采用终态并收尾。
   *   2. 前端没有活跃任务（页面刷新 / 重开后），但列表里有 running/pending 的
   *      job（sidecar 单 worker，最多一个）→ 重新挂上 SSE，托盘和进度条恢复。
   */
  async function loadJobs(limit = 50) {
    const resp = await api().get<{ count: number; jobs: MiningJob[] }>(
      "/api/mining/jobs",
      { params: { limit } },
    )
    jobs.value = resp.data.jobs
    const aj = activeJob.value
    if (aj && isRunningStatus(aj.status)) {
      const fresh = jobs.value.find(j => j.id === aj.id)
      if (fresh && !isRunningStatus(fresh.status)) {
        activeJob.value = fresh
        _settleFinished(fresh.status, fresh.keyword)
      }
    } else if (!hasRunningJob.value) {
      const running = jobs.value.find(j => isRunningStatus(j.status))
      if (running) {
        activeJob.value = running
        subscribeToJob(running.id)
      }
    }
  }

  /**
   * Switch the right column to a specific job's videos (or "all" when id
   * is null). Triggers a refresh under the new filter.
   */
  async function selectJob(id: number | null) {
    currentJobId.value = id
    filters.value.job_id = id
    await refreshVideos()
  }

  /**
   * 删除整条任务：DELETE /api/mining/jobs/{id}。
   *
   * 后端如果还没接这个路由，会回 404/405 —— 直接 throw 出去让 caller
   * 弹 toast 提示"暂未支持，等后端补"。成功的话本地 jobs[] 跟着移除，
   * 若当前选中的就是被删的，currentJobId 复位为 null + 清 videos。
   */
  async function deleteJob(jobId: number): Promise<void> {
    await api().delete(`/api/mining/jobs/${jobId}`)
    jobs.value = jobs.value.filter(j => j.id !== jobId)
    if (currentJobId.value === jobId) {
      currentJobId.value = null
      filters.value.job_id = null
      videos.value = []
      total.value = 0
    }
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

  // ── 批量 AI 生成 + 审核（P2）──────────────────────────────────────────
  const genState = ref<GenBatchState | null>(null)
  let stopGenSse: (() => void) | null = null

  function _teardownGenSse() {
    if (stopGenSse) { stopGenSse(); stopGenSse = null }
  }

  async function generateBatch(
    videoIds: number[],
    tiersPerVideo: number,
    toneHint = "",
    templateIds: number[] = [],
  ): Promise<number> {
    try {
      const resp = await api().post<{ batch_id: number; total: number }>(
        "/api/mining/generate_batch",
        {
          video_ids: videoIds,
          tiers_per_video: tiersPerVideo,
          tone_hint: toneHint,
          template_ids: templateIds,
        },
      )
      genState.value = {
        active: true, batchId: resp.data.batch_id,
        done: 0, total: resp.data.total, generated: 0, failed: 0,
      }
      _subscribeToGenBatch(resp.data.batch_id)
      return resp.data.batch_id
    } catch (err) {
      _wrapLLMError(err)
    }
  }

  function _subscribeToGenBatch(batchId: number) {
    _teardownGenSse()
    stopGenSse = subscribe(`/api/mining/generate_batch/${batchId}/events`, {
      "generation.progress": (d: any) => {
        if (genState.value?.batchId !== batchId) return
        genState.value = { ...genState.value, done: d.done, total: d.total }
        // 边生成边刷新对应视频的评论楼，右栏能实时看到新草稿。
        if (d.video_id) loadComments(d.video_id).catch(() => {})
      },
      "generation.finished": (d: any) => {
        if (genState.value?.batchId === batchId) {
          genState.value = {
            ...genState.value, active: false,
            generated: d.generated ?? 0, failed: d.failed ?? 0,
          }
        }
        // pending_review_count 变了 → 刷新视频列表（审核 tab 徽标）。
        refreshVideos().catch(() => {})
      },
      done: () => {
        _teardownGenSse()
        if (genState.value?.batchId === batchId && genState.value.active) {
          genState.value = { ...genState.value, active: false }
        }
      },
    })
  }

  async function cancelGeneration(): Promise<void> {
    const id = genState.value?.batchId
    if (id == null) return
    await api().post(`/api/mining/generate_batch/${id}/cancel`)
  }

  function _patchVideoPending(videoId: number, delta: number) {
    const v = videos.value.find(x => x.id === videoId)
    if (v) {
      v.pending_review_count = Math.max(0, (v.pending_review_count ?? 0) + delta)
    }
  }

  async function approveComment(commentId: number, videoId: number): Promise<Comment> {
    const resp = await api().patch<Comment>(
      `/api/mining/comments/${commentId}/review`,
      { action: "approve" },
    )
    const list = commentsByVideo.value[videoId]
    if (list) {
      commentsByVideo.value[videoId] = list.map(c => (c.id === resp.data.id ? resp.data : c))
    }
    _patchVideoPending(videoId, -1)
    return resp.data
  }

  async function reviewBulk(videoIds: number[]): Promise<number> {
    const resp = await api().post<{ approved: number }>(
      "/api/mining/comments/review_bulk",
      { video_ids: videoIds },
    )
    for (const id of videoIds) {
      if (commentsByVideo.value[id]) loadComments(id).catch(() => {})
    }
    await refreshVideos()
    return resp.data.approved
  }

  // ── 腾讯文档同步（P3）────────────────────────────────────────────────
  const syncingToDocs = ref(false)

  async function syncToDocs(videoIds?: number[]): Promise<SyncToDocsResult> {
    syncingToDocs.value = true
    try {
      const resp = await api().post<SyncToDocsResult>(
        "/api/mining/sync_to_docs",
        { video_ids: videoIds ?? null },
      )
      // approved → synced 后 pending/approved 统计变了，刷新列表 + 已加载的评论楼。
      await refreshVideos()
      for (const idStr of Object.keys(commentsByVideo.value)) {
        loadComments(Number(idStr)).catch(() => {})
      }
      return resp.data
    } finally {
      syncingToDocs.value = false
    }
  }

  async function syncToMonitor(
    jobId: number,
    req: SyncToMonitorRequest,
  ): Promise<SyncToMonitorResult> {
    syncingJobId.value = jobId
    syncResult.value = null
    syncError.value = null
    try {
      const resp = await api().post<SyncToMonitorResult>(
        `/api/mining/jobs/${jobId}/sync_to_monitor`,
        req,
      )
      syncResult.value = resp.data
      return resp.data
    } catch (e: any) {
      const detail = e?.response?.data?.detail ?? e?.message ?? String(e)
      syncError.value = String(detail)
      throw e
    } finally {
      syncingJobId.value = null
    }
  }

  return {
    activeJob, videos, total, loading, filters, loginStatus,
    jobs, currentJobId,
    commentsByVideo, aiSummaryLoading, commentSavingByVideo,
    syncingJobId, syncResult, syncError,
    hasRunningJob,
    startJob, cancelActive, cancelJob, refreshVideos,
    refreshLoginStatus, startLogin, confirmLogin,
    deleteVideo, bulkDeleteVideos, loadJobs, selectJob, exportUrl, deleteJob,
    loadComments, createComment, updateComment, deleteComment,
    uploadImage, summarize, suggestComment, bulkMarkCommented,
    syncToMonitor,
    genState, generateBatch, cancelGeneration, approveComment, reviewBulk,
    syncingToDocs, syncToDocs,
  }
})
