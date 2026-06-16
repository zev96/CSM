/**
 * 小红书图文笔记编辑器 store（设计稿 §4）。
 *
 * 承载当前草稿（title/body/topics/images/cover/theme）、草稿列表、面板与
 * 预览 tab 状态。去抖自动保存：内容变化 → scheduleSave(800ms) → 首次有内容
 * 时 POST 建草稿拿 id，之后 PATCH。复制走 navigator.clipboard。
 *
 * 光标插入采用「注册式」：NoteEditor 挂载时 registerInserter(insert)，P1 的
 * 素材面板调 insertAtCursor(text) 即把内容插到正文光标处（跨组件解耦）。
 */
import { defineStore } from "pinia";

import { useSidecar } from "./sidecar";
import { useToast } from "@/composables/useToast";
import { buildFullText, countChars } from "@/utils/xhsText";

export interface XhsDraft {
  id: string;
  title: string;
  body: string;
  topics: string[];
  image_ids: string[];
  cover_index: number;
  theme_id: string | null;
  created_at: string;
  updated_at: string;
}

export type XhsPanel =
  | "template" | "theme" | "emoji" | "title" | "copy"
  | "topic" | "decoration" | "image" | "ai";

export type XhsPreviewTab = "note" | "discover";

export const TITLE_SOFT_LIMIT = 20;
export const BODY_SOFT_LIMIT = 1000;

interface XhsState {
  draftId: string | null;
  title: string;
  body: string;
  topics: string[];
  imageIds: string[];
  coverIndex: number;
  themeId: string | null;
  activePanel: XhsPanel;
  previewTab: XhsPreviewTab;
  drafts: XhsDraft[];
  saving: boolean;
}

// 去抖定时器与「正文插入器」放模块级：它们不该进 Pinia 响应式 state
// （一个是 timer handle，一个是 DOM 操作回调，都不需要触发渲染）。
let _saveTimer: ReturnType<typeof setTimeout> | null = null;
let _inserter: ((text: string) => void) | null = null;

export const useXhs = defineStore("xhs", {
  state: (): XhsState => {
    // 新建 store 实例时（含测试里的 setActivePinia + createPinia）顺带重置
    // 模块级状态，防止跨用例污染。
    _inserter = null;
    _saveTimer = null;
    return {
      draftId: null,
      title: "",
      body: "",
      topics: [],
      imageIds: [],
      coverIndex: 0,
      themeId: null,
      activePanel: "template",
      previewTab: "note",
      drafts: [],
      saving: false,
    };
  },
  getters: {
    fullText: (s): string => buildFullText(s.title, s.body, s.topics),
    titleCount: (s): number => countChars(s.title),
    bodyCount: (s): number => countChars(s.body),
    titleOver: (s): boolean => countChars(s.title) > TITLE_SOFT_LIMIT,
    bodyOver: (s): boolean => countChars(s.body) > BODY_SOFT_LIMIT,
    isEmpty: (s): boolean => s.title.trim() === "" && s.body.trim() === "",
  },
  actions: {
    async loadDrafts(): Promise<void> {
      const sidecar = useSidecar();
      try {
        const r = await sidecar.client.get("/api/xhs/drafts");
        this.drafts = r.data.drafts ?? [];
      } catch {
        this.drafts = [];
      }
    },
    async loadDraft(id: string): Promise<void> {
      const sidecar = useSidecar();
      const r = await sidecar.client.get(`/api/xhs/drafts/${id}`);
      this._apply(r.data as XhsDraft);
    },
    _apply(d: XhsDraft): void {
      this.draftId = d.id;
      this.title = d.title ?? "";
      this.body = d.body ?? "";
      this.topics = [...(d.topics ?? [])];
      this.imageIds = [...(d.image_ids ?? [])];
      this.coverIndex = d.cover_index ?? 0;
      this.themeId = d.theme_id ?? null;
    },
    newDraft(): void {
      if (_saveTimer) { clearTimeout(_saveTimer); _saveTimer = null; }
      this.draftId = null;
      this.title = "";
      this.body = "";
      this.topics = [];
      this.imageIds = [];
      this.coverIndex = 0;
      this.themeId = null;
    },
    _payload() {
      return {
        title: this.title,
        body: this.body,
        topics: this.topics,
        image_ids: this.imageIds,
        cover_index: this.coverIndex,
        theme_id: this.themeId,
      };
    },
    /** 首次有内容时建草稿拿 id；空草稿不建（避免堆积）。返回 draftId 或 null。 */
    async _ensureCreated(): Promise<string | null> {
      if (this.draftId) return this.draftId;
      if (this.isEmpty) return null;
      const sidecar = useSidecar();
      const r = await sidecar.client.post("/api/xhs/drafts", this._payload());
      this.draftId = r.data.id;
      return this.draftId;
    },
    scheduleSave(): void {
      if (_saveTimer) clearTimeout(_saveTimer);
      _saveTimer = setTimeout(() => { void this.saveNow(); }, 800);
    },
    async saveNow(): Promise<void> {
      if (_saveTimer) { clearTimeout(_saveTimer); _saveTimer = null; }
      const id = await this._ensureCreated();
      if (!id) return;
      const sidecar = useSidecar();
      this.saving = true;
      try {
        await sidecar.client.patch(`/api/xhs/drafts/${id}`, this._payload());
      } catch {
        /* 自动保存失败静默；下次编辑会再次触发。 */
      } finally {
        this.saving = false;
      }
    },
    setTitle(v: string): void {
      this.title = v;
      this.scheduleSave();
    },
    setBody(v: string): void {
      this.body = v;
      this.scheduleSave();
    },
    addTopic(tag: string): void {
      const t = tag.replace(/^#+/, "").trim();
      if (!t || this.topics.includes(t)) return;
      this.topics.push(t);
      this.scheduleSave();
    },
    removeTopic(i: number): void {
      this.topics.splice(i, 1);
      this.scheduleSave();
    },
    setActivePanel(p: XhsPanel): void {
      this.activePanel = p;
    },
    setPreviewTab(t: XhsPreviewTab): void {
      this.previewTab = t;
    },
    /** NoteEditor 挂载时注册正文光标插入器；卸载时传 null 注销。 */
    registerInserter(fn: ((text: string) => void) | null): void {
      _inserter = fn;
    },
    /** P1 素材面板插入入口：有注册器走光标插入，否则回退追加到正文末尾。 */
    insertAtCursor(text: string): void {
      if (_inserter) {
        _inserter(text);
      } else {
        this.setBody(this.body + text);
      }
    },
    async copy(kind: "title" | "body" | "full"): Promise<void> {
      const text = kind === "title" ? this.title : kind === "body" ? this.body : this.fullText;
      const toast = useToast();
      try {
        await navigator.clipboard.writeText(text);
        toast.success("已复制");
      } catch {
        toast.error("复制失败，请检查剪贴板权限");
      }
    },
    async deleteDraft(id: string): Promise<void> {
      const sidecar = useSidecar();
      await sidecar.client.delete(`/api/xhs/drafts/${id}`);
      if (this.draftId === id) this.newDraft();
      await this.loadDrafts();
    },
  },
});
