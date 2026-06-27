import { defineStore } from "pinia";
import { ref } from "vue";
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
  coverage: Coverage;
}
export interface SpecValue {
  field: string; raw: string; numbers: number[]; unit: string;
  is_approx: boolean; is_placeholder: boolean;
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
    try {
      const r = await useSidecar().client.post("/api/vault/atomize", { text });
      return r.data.atoms ?? [];
    } catch (e: any) {
      intakeError.value = errMsg(e); return [];
    }
  }

  async function commitAtom(payload: NotePayload): Promise<WriteReceipt | null> {
    try {
      const r = await useSidecar().client.post("/api/vault/commit", payload);
      return r.data;
    } catch (e: any) {
      intakeError.value = errMsg(e); return null;
    }
  }

  async function undoAtom(receipt: WriteReceipt): Promise<void> {
    try {
      await useSidecar().client.post("/api/vault/undo", receipt);
    } catch (e: any) {
      intakeError.value = errMsg(e);
    }
  }

  return {
    models, loading, error, selectedModel, detail, detailLoading, list, select,
    writableFolders, foldersLoading, currentPlan, lastReceipt, intakeError,
    loadFolders, planNote, commitNote, undoLast,
    atomizeText, commitAtom, undoAtom,
  };
});
