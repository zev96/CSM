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

import type { AxiosError } from "axios";
import { useSidecar } from "./sidecar";
import { useToast } from "@/composables/useToast";
import { buildFullText, countChars } from "@/utils/xhsText";
import { findTheme, type XhsTheme } from "@/data/xhs/assets";
import { orderedMarker, nextOrderedNumber } from "@/utils/xhsTheme";

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
// 光标上下文探针：NoteEditor 注册，返回光标前文本，用于有序列表按块计数。
let _cursorProbe: (() => { before: string }) | null = null;
// 建草稿请求去重：in-flight 的 POST promise，避免并发 saveNow 重复建草稿。
let _creating: Promise<string | null> | null = null;

/**
 * @internal 仅供单测 beforeEach 调用：重置模块级可变状态（去抖定时器 +
 * 正文插入器 + 建草稿 in-flight 去重）。生产代码不应调用 —— 这些单例的
 * 生命周期分别由 scheduleSave/saveNow 和 NoteEditor 的 mount/unmount 管理。
 */
export function _resetXhsModuleState(): void {
  if (_saveTimer) clearTimeout(_saveTimer);
  _saveTimer = null;
  _inserter = null;
  _cursorProbe = null;
  _creating = null;
}

/**
 * 503 + code="llm_not_configured" 时抛出。AiPanel 据此弹「去设置」toast，
 * 而非通用报错。与 mining store 的同名类各自独立（xhs 模块自洽，不耦合 mining）。
 */
export class LLMNotConfiguredError extends Error {
  constructor(message = "请先在设置中配置 AI 服务") {
    super(message);
    this.name = "LLMNotConfiguredError";
  }
}

/** 把 sidecar AI 路由的 503 llm_not_configured 解包成 LLMNotConfiguredError，其余原样抛。 */
function _wrapLLMError(err: unknown): never {
  const ax = err as AxiosError<{ code?: string; detail?: string }>;
  const resp = ax?.response;
  if (resp?.status === 503 && resp.data?.code === "llm_not_configured") {
    throw new LLMNotConfiguredError(resp.data.detail || undefined);
  }
  throw err;
}

export const useXhs = defineStore("xhs", {
  state: (): XhsState => ({
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
  }),
  getters: {
    fullText: (s): string => buildFullText(s.title, s.body),
    titleCount: (s): number => countChars(s.title),
    bodyCount: (s): number => countChars(s.body),
    titleOver: (s): boolean => countChars(s.title) > TITLE_SOFT_LIMIT,
    bodyOver: (s): boolean => countChars(s.body) > BODY_SOFT_LIMIT,
    isEmpty: (s): boolean =>
      s.title.trim() === "" && s.body.trim() === "" && s.imageIds.length === 0,
    /** 当前激活的排版主题对象（无则 null）。 */
    activeTheme: (s): XhsTheme | null => findTheme(s.themeId),
    /** 工具条快捷符号按钮：激活主题 → 小标题/无序/有序/分割线（无主题时空）。
     *  「有序」的 symbol 仅作按钮提示（该样式第 1 个序号字形），点击实际走
     *  insertOrdered 按正文已有序号推算下一个。用 function 形式以便 this 访问 activeTheme。 */
    themeToolbar(): { key: string; label: string; symbol: string }[] {
      const t = this.activeTheme;
      if (!t) return [];
      return [
        { key: "heading", label: "小标题", symbol: t.heading },
        { key: "bullet", label: "无序", symbol: t.bullet },
        { key: "ordered", label: "有序", symbol: orderedMarker(1, t.ordered) },
        { key: "divider", label: "分割线", symbol: t.divider },
      ];
    },
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
      this.topics = []; // 话题现以 #标签 文本形式存在于正文；旧草稿 topic 数组忽略
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
    /** 模板载入：覆盖标题/正文，模板话题以 #话题 形式拼到正文末尾。 */
    applyTemplate(tpl: { title: string; body: string; topics: string[] }): void {
      this.title = tpl.title;
      this.body = tpl.body;
      this.topics = [];
      for (const t of tpl.topics) this.addTopic(t);
      this.scheduleSave();
    },
    /** 应用排版主题：设激活主题 id，工具条随即出现该主题快捷符号。 */
    applyTheme(themeId: string): void {
      this.themeId = themeId;
      this.scheduleSave();
    },
    /** 工具条「有序」：按激活主题 ordered 样式，在光标处插入「下一个序号 + 空格」。
     *  下一个序号按光标前当前列表块（空行分块）计数，跨块各自从 1 起。无激活主题时不动。 */
    insertOrdered(): void {
      const t = this.activeTheme;
      if (!t) return;
      const before = _cursorProbe ? _cursorProbe().before : this.body;
      const n = nextOrderedNumber(before, t.ordered);
      this.insertAtCursor(orderedMarker(n, t.ordered) + " ");
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
    /** 首次有内容时建草稿拿 id；空草稿不建（避免堆积）。返回 draftId 或 null。
     *  force=true 时无视 isEmpty 强制建（上传图片场景：上传动作本身即内容）。
     *  用 _creating 去重：并发调用复用同一个 in-flight POST，防止建出孤儿草稿。 */
    async _ensureCreated(force = false): Promise<string | null> {
      if (this.draftId) return this.draftId;
      if (!force && this.isEmpty) return null;
      if (_creating) return _creating;
      _creating = (async () => {
        try {
          const sidecar = useSidecar();
          const r = await sidecar.client.post("/api/xhs/drafts", this._payload());
          this.draftId = r.data.id;
          return this.draftId;
        } finally {
          _creating = null;
        }
      })();
      return _creating;
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
    /** 点击/输入话题：在正文末尾追加「#话题」（已存在则跳过）。话题现以 #标签 文本形式存在于正文。 */
    addTopic(tag: string): void {
      const t = tag.replace(/^#+/, "").trim();
      if (!t) return;
      const esc = t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      if (new RegExp("#" + esc + "(?=\\s|$)").test(this.body)) return; // 去重：已有同名 #话题
      const sep = this.body.length === 0 || /\s$/.test(this.body) ? "" : " ";
      this.setBody(this.body + sep + "#" + t);
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
    /** NoteEditor 挂载时注册光标上下文探针（取光标前文本）；卸载传 null。 */
    registerCursorProbe(fn: (() => { before: string }) | null): void {
      _cursorProbe = fn;
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
    /** 上传一张图片：强制确保草稿存在 → multipart POST → 把 image_id 推进 imageIds → 去抖保存。
     *  失败（如 400 超限/非图）向上抛，由调用方（ImagePanel）toast。 */
    async uploadImage(file: File): Promise<void> {
      const id = await this._ensureCreated(true);
      if (!id) return;
      const sidecar = useSidecar();
      const form = new FormData();
      form.append("file", file);
      const r = await sidecar.client.post(`/api/xhs/drafts/${id}/images`, form, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      this.imageIds.push(r.data.image_id);
      this.scheduleSave();
    },
    /** 删第 i 张图。封面下标随之修正：删封面前的图→左移；删的就是封面或越界→夹回合法范围。
     *  文件删除由后端 PATCH diff（image_ids 变化）负责。 */
    removeImage(i: number): void {
      if (i < 0 || i >= this.imageIds.length) return;
      const removedWasCover = i === this.coverIndex;
      this.imageIds.splice(i, 1);
      if (this.imageIds.length === 0) {
        this.coverIndex = 0;
      } else if (removedWasCover) {
        this.coverIndex = Math.min(this.coverIndex, this.imageIds.length - 1);
      } else if (i < this.coverIndex) {
        this.coverIndex -= 1;
      }
      this.scheduleSave();
    },
    /** 设第 i 张为封面。 */
    setCover(i: number): void {
      if (i < 0 || i >= this.imageIds.length) return;
      this.coverIndex = i;
      this.scheduleSave();
    },
    /** 把第 from 张移到 to 位；封面下标跟随原封面图。 */
    reorderImages(from: number, to: number): void {
      const n = this.imageIds.length;
      if (from === to || from < 0 || from >= n || to < 0 || to >= n) return;
      const coverId = this.imageIds[this.coverIndex];
      const [moved] = this.imageIds.splice(from, 1);
      this.imageIds.splice(to, 0, moved);
      const newCover = this.imageIds.indexOf(coverId);
      if (newCover >= 0) this.coverIndex = newCover;
      this.scheduleSave();
    },
    async deleteDraft(id: string): Promise<void> {
      const sidecar = useSidecar();
      await sidecar.client.delete(`/api/xhs/drafts/${id}`);
      if (this.draftId === id) this.newDraft();
      await this.loadDrafts();
    },
    /** 重命名草稿（仅改标题）。当前打开的就是它则同步本地标题。 */
    async renameDraft(id: string, title: string): Promise<void> {
      const sidecar = useSidecar();
      await sidecar.client.patch(`/api/xhs/drafts/${id}`, { title });
      if (this.draftId === id) this.title = title;
      await this.loadDrafts();
    },
    /** 复制副本：后端建副本（含图片拷贝），刷新列表。返回新 id。 */
    async duplicateDraft(id: string): Promise<string | null> {
      const sidecar = useSidecar();
      const r = await sidecar.client.post(`/api/xhs/drafts/${id}/duplicate`);
      await this.loadDrafts();
      return r.data?.id ?? null;
    },
    /** AI 生成整篇：返回 {title, body, topics}（调用方决定是否覆盖填入）。
     *  503 未配置 LLM → 抛 LLMNotConfiguredError（AiPanel 弹「去设置」）。 */
    async generateNote(intent: string): Promise<{ title: string; body: string; topics: string[] }> {
      const sidecar = useSidecar();
      try {
        const r = await sidecar.client.post("/api/xhs/ai/generate", { intent });
        return {
          title: typeof r.data?.title === "string" ? r.data.title : "",
          body: typeof r.data?.body === "string" ? r.data.body : "",
          topics: Array.isArray(r.data?.topics) ? r.data.topics : [],
        };
      } catch (e) {
        _wrapLLMError(e);
      }
    },
    /** AI 润色当前正文：返回润色后文本（不直接写回，调用方决定）。 */
    async polishBody(): Promise<string> {
      const sidecar = useSidecar();
      try {
        const r = await sidecar.client.post("/api/xhs/ai/polish", { text: this.body });
        return typeof r.data?.body === "string" ? r.data.body : "";
      } catch (e) {
        _wrapLLMError(e);
      }
    },
  },
});
