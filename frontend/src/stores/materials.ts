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

  return { models, loading, error, selectedModel, detail, detailLoading, list, select };
});
