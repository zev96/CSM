import { defineStore } from "pinia";
import { computed, ref } from "vue";
import { useSidecar } from "@/stores/sidecar";

export interface Coverage {
  has_specs?: boolean;
  has_tests?: boolean;
  script_dimensions?: number;
  empty_spec_fields?: string[];
  [k: string]: unknown;
}
export interface BrandModelRow {
  model: string;       // full-stem，如 CEWEYDS18
  brand: string;
  role: string;        // 主推 | 竞品
  product_line: string; // 吸尘器 | 空气净化器 | 未分类…
  coverage: Coverage;
}
export interface SpecValue {
  field: string; raw: string; numbers: number[]; unit: string;
  is_approx: boolean; is_placeholder: boolean;
  section: string;               // 所属 H2 小节名(后端 v2 起下发)
}
export interface ModelDetail {
  brand: string; model: string; model_full: string; category: string; role: string;
  specs: Record<string, SpecValue>;
  certs: string[];
  scripts: Record<string, string[]>;
  endorsements: string[];
  intro: string[];
  tests: Record<string, string>;
  coverage: Coverage;
  inject_preview: string;
}

export interface FolderProfile {
  rel_folder: string;
  frontmatter_keys: string[];
  defaults: Record<string, string>;
  body_shape: "variants" | "spec_table" | "unknown";
  sample_count: number;
  material_types: string[];
}
export interface NotePlan {
  rel_folder: string; filename: string; rel_path: string;
  frontmatter: Record<string, unknown>; body: string; backlink_tail: string;
  full_text: string; index_rel: string | null; index_line: string | null;
  conflict: boolean; warnings: string[];
}
export interface WriteReceipt {
  created_rel: string; content_sha: string;
  index_rel: string | null; index_line: string | null;
}
export interface NotePayload {
  rel_folder: string; filename: string;
  frontmatter: Record<string, unknown>; body_shape: string;
  variants?: string[]; spec_rows?: { group: string; key: string; value: string }[];
}
export interface AtomDraft {
  text: string;
  rel_folder: string | null;
  material_type: string;
  product: string;
  keyword: string;
  filename: string;
  confidence: "high" | "med" | "low";
  warnings: string[];
}

function errMsg(e: any): string {
  return e?.response?.data?.detail ?? e?.message ?? String(e);
}

export const useMaterials = defineStore("materials", () => {
  const models = ref<BrandModelRow[]>([]);
  const lineFilter = ref<string>("全部");   // 品牌型号页产品线筛选(汇总栏联动)
  /** 筛选后的型号池;陈旧筛选值(产品线已消失)自愈按「全部」,防列表死锁空态。 */
  const lineModels = computed(() => {
    if (lineFilter.value === "全部") return models.value;
    const pool = models.value.filter((r) => (r.product_line || "未分类") === lineFilter.value);
    return pool.length ? pool : models.value;
  });
  const loading = ref(false);
  const error = ref<string | null>(null);
  const selectedModel = ref<string | null>(null);
  const detail = ref<ModelDetail | null>(null);
  const detailLoading = ref(false);
  const writableFolders = ref<FolderProfile[]>([]);
  const foldersLoading = ref(false);
  const currentPlan = ref<NotePlan | null>(null);
  const lastReceipt = ref<WriteReceipt | null>(null);
  const intakeError = ref<string | null>(null);
  const chunkProgress = ref<{ current: number; total: number } | null>(null);
  const lastAtomizeTruncated = ref<{ dropped: number } | null>(null);
  const chunkCancelled = ref(false);

  const CHUNK_THRESHOLD = 8000;

  function cancelAtomize(): void {
    chunkCancelled.value = true;
  }

  function atomKey(a: AtomDraft): string {
    return `${a.rel_folder ?? ""}|${a.text.replace(/[\s\p{P}]/gu, "").slice(0, 80)}`;
  }

  async function list(): Promise<void> {
    loading.value = true; error.value = null;
    try {
      const r = await useSidecar().client.get("/api/brand-memory");
      models.value = r.data.models ?? [];
    } catch (e: any) {
      error.value = errMsg(e); models.value = [];
    } finally { loading.value = false; }
  }

  async function select(model: string): Promise<void> {
    selectedModel.value = model;
    detail.value = null; detailLoading.value = true; error.value = null;
    try {
      const r = await useSidecar().client.get(
        `/api/brand-memory/${encodeURIComponent(model)}`);
      detail.value = r.data;
    } catch (e: any) {
      error.value = errMsg(e);
    } finally { detailLoading.value = false; }
  }

  async function loadFolders(): Promise<void> {
    foldersLoading.value = true; intakeError.value = null;
    try {
      const r = await useSidecar().client.get("/api/vault/writable-folders");
      writableFolders.value = r.data.folders ?? [];
    } catch (e: any) {
      intakeError.value = errMsg(e); writableFolders.value = [];
    } finally { foldersLoading.value = false; }
  }

  async function planNote(payload: NotePayload): Promise<void> {
    intakeError.value = null;
    try {
      const r = await useSidecar().client.post("/api/vault/plan", payload);
      currentPlan.value = r.data;
    } catch (e: any) {
      intakeError.value = errMsg(e); currentPlan.value = null;
    }
  }

  async function commitNote(payload: NotePayload): Promise<boolean> {
    intakeError.value = null;
    try {
      const r = await useSidecar().client.post("/api/vault/commit", payload);
      lastReceipt.value = r.data;
      return true;
    } catch (e: any) {
      intakeError.value = errMsg(e);
      return false;
    }
  }

  async function undoLast(): Promise<void> {
    if (!lastReceipt.value) return;
    try {
      await useSidecar().client.post("/api/vault/undo", lastReceipt.value);
    } catch (e: any) {
      intakeError.value = errMsg(e);
    } finally {
      lastReceipt.value = null;
    }
  }

  async function atomizeText(text: string): Promise<AtomDraft[]> {
    intakeError.value = null;
    lastAtomizeTruncated.value = null;
    if (text.length <= CHUNK_THRESHOLD) {
      try {
        const r = await useSidecar().client.post("/api/vault/atomize", { text });
        return r.data.atoms ?? [];
      } catch (e: any) {
        intakeError.value = errMsg(e);
        return [];
      }
    }
    // 长文：先切块再逐块拆条（进度可见、块间可取消、跨块去重）
    chunkCancelled.value = false;
    let chunks: string[] = [];
    try {
      const r = await useSidecar().client.post("/api/vault/atomize/split", { text });
      chunks = r.data.chunks ?? [];
      if (r.data.truncated) {
        lastAtomizeTruncated.value = { dropped: r.data.dropped_chars ?? 0 };
      }
    } catch (e: any) {
      intakeError.value = errMsg(e);
      chunkProgress.value = null;   // 防御：任何早退都不留残留进度态
      return [];
    }
    const seen = new Set<string>();
    const merged: AtomDraft[] = [];
    chunkProgress.value = { current: 0, total: chunks.length };
    try {
      for (let i = 0; i < chunks.length; i++) {
        if (chunkCancelled.value) break;
        chunkProgress.value = { current: i + 1, total: chunks.length };
        try {
          const r = await useSidecar().client.post("/api/vault/atomize", { text: chunks[i] });
          for (const a of (r.data.atoms ?? []) as AtomDraft[]) {
            const k = atomKey(a);
            if (seen.has(k)) continue;
            seen.add(k);
            merged.push(a);
          }
        } catch (e: any) {
          intakeError.value = errMsg(e);      // 中断但保留已拆的块
          break;
        }
      }
    } finally {
      chunkProgress.value = null;
    }
    return merged;
  }

  async function commitAtom(payload: NotePayload): Promise<WriteReceipt | null> {
    intakeError.value = null;
    try {
      const r = await useSidecar().client.post("/api/vault/commit", payload);
      return r.data;
    } catch (e: any) {
      intakeError.value = errMsg(e); return null;
    }
  }

  async function undoAtom(receipt: WriteReceipt): Promise<void> {
    intakeError.value = null;
    try {
      await useSidecar().client.post("/api/vault/undo", receipt);
    } catch (e: any) {
      intakeError.value = errMsg(e);
    }
  }

  return {
    models, lineFilter, lineModels, loading, error, selectedModel, detail, detailLoading, list, select,
    writableFolders, foldersLoading, currentPlan, lastReceipt, intakeError,
    loadFolders, planNote, commitNote, undoLast,
    atomizeText, commitAtom, undoAtom,
    chunkProgress, lastAtomizeTruncated, cancelAtomize,
  };
});
