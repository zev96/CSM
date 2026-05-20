/**
 * Templates store — Pinia for comment template library.
 *
 * Pulls top-N chips for CommentComposer, full list for drawer + settings.
 * /use endpoint bumps use_count + last_used_at server-side so chips
 * re-rank correctly on next list().
 */
import { defineStore } from "pinia"
import { ref } from "vue"
import { useSidecar } from "@/stores/sidecar"

export interface Template {
  id: number
  text: string
  tags: string[]
  source_platform: string | null
  source_comment_id: number | null
  starred: boolean
  hidden: boolean
  use_count: number
  first_seen_at: string
  last_used_at: string
}

export interface ListTemplateParams {
  search?: string
  tags?: string[]
  platform?: string
  starred?: boolean
  hidden?: "0" | "1" | "all"
  limit?: number
  offset?: number
}

export interface CreateTemplatePayload {
  text: string
  tags?: string[]
  source_platform?: string | null
}

export interface UpdateTemplatePayload {
  text?: string
  tags?: string[]
  starred?: boolean
  hidden?: boolean
}

export class TemplateDuplicateError extends Error {
  kind = "duplicate" as const
  constructor(public existingId: number) {
    super(`template already exists (id=${existingId})`)
    this.name = "TemplateDuplicateError"
  }
}

function api() {
  return useSidecar().client
}

export const useTemplatesStore = defineStore("templates", () => {
  const items = ref<Template[]>([])
  const total = ref(0)
  const allTags = ref<string[]>([])
  const loading = ref(false)

  async function list(params: ListTemplateParams = {}): Promise<void> {
    loading.value = true
    try {
      const resp = await api().get<{ items: Template[]; total: number }>(
        "/api/mining/templates",
        {
          params: {
            search: params.search,
            tags: params.tags?.length ? params.tags.join(",") : undefined,
            platform: params.platform,
            starred: params.starred,
            hidden: params.hidden ?? "0",
            limit: params.limit ?? 50,
            offset: params.offset ?? 0,
          },
        },
      )
      items.value = resp.data.items
      total.value = resp.data.total
    } finally {
      loading.value = false
    }
  }

  async function listTopChips(limit = 5): Promise<Template[]> {
    const resp = await api().get<{ items: Template[]; total: number }>(
      "/api/mining/templates",
      { params: { limit, offset: 0, hidden: "0" } },
    )
    return resp.data.items
  }

  async function loadAllTags(): Promise<void> {
    const resp = await api().get<{ tags: string[] }>("/api/mining/templates/tags")
    allTags.value = resp.data.tags
  }

  async function useTemplate(id: number): Promise<string> {
    const resp = await api().post<{ text: string }>(`/api/mining/templates/${id}/use`)
    return resp.data.text
  }

  async function create(payload: CreateTemplatePayload): Promise<Template> {
    try {
      const resp = await api().post<{ template: Template }>("/api/mining/templates", payload)
      return resp.data.template
    } catch (err: any) {
      if (err?.response?.status === 409 && err.response.data?.detail === "duplicate") {
        throw new TemplateDuplicateError(err.response.data.existing_id)
      }
      throw err
    }
  }

  async function update(id: number, payload: UpdateTemplatePayload): Promise<Template> {
    try {
      const resp = await api().patch<{ template: Template }>(`/api/mining/templates/${id}`, payload)
      // Update local cache if id is in items
      const idx = items.value.findIndex(t => t.id === id)
      if (idx >= 0) items.value[idx] = resp.data.template
      return resp.data.template
    } catch (err: any) {
      if (err?.response?.status === 409 && err.response.data?.detail === "duplicate") {
        throw new TemplateDuplicateError(err.response.data.existing_id)
      }
      throw err
    }
  }

  async function remove(id: number): Promise<void> {
    await api().delete(`/api/mining/templates/${id}`)
    items.value = items.value.filter(t => t.id !== id)
  }

  async function bulkImport(payload: {
    texts: string[]
    tags?: string[]
    source_platform?: string | null
  }): Promise<{ created: number; skipped_duplicates: number }> {
    const resp = await api().post<{ created: number; skipped_duplicates: number }>(
      "/api/mining/templates/bulk-import",
      payload,
    )
    return resp.data
  }

  async function exportAll(): Promise<Template[]> {
    // Fetch all templates including hidden, page through 500-at-a-time.
    const all: Template[] = []
    let offset = 0
    const limit = 500
    while (true) {
      const resp = await api().get<{ items: Template[]; total: number }>(
        "/api/mining/templates",
        { params: { hidden: "all", limit, offset } },
      )
      all.push(...resp.data.items)
      if (all.length >= resp.data.total) break
      offset += limit
    }
    return all
  }

  return {
    items, total, allTags, loading,
    list, listTopChips, loadAllTags,
    useTemplate, create, update, remove,
    bulkImport, exportAll,
  }
})
