/**
 * 小红书自定义素材 store（设计稿 §3.4）。kind ∈ template|copy|title|topic，
 * 与起步 JSON 合并显示、标「我的」分组。setup-store 写法（仿 templates.ts），
 * 与承载草稿的 options-store useXhs 解耦。
 */
import { defineStore } from "pinia";
import { ref, computed } from "vue";
import { useSidecar } from "@/stores/sidecar";

export type XhsAssetKind = "template" | "copy" | "title" | "topic";

export interface XhsCustomAsset {
  id: string;
  kind: XhsAssetKind;
  // payload 形状随 kind 变（template:{name,title,body,topics} / copy:{text} / title:{text} / topic:{text}）
  payload: Record<string, any>;
  created_at: string;
}

export const useXhsAssets = defineStore("xhsAssets", () => {
  const api = () => useSidecar().client;

  const assets = ref<XhsCustomAsset[]>([]);
  const loaded = ref(false);

  const templates = computed(() => assets.value.filter((a) => a.kind === "template"));
  const copies = computed(() => assets.value.filter((a) => a.kind === "copy"));
  const titles = computed(() => assets.value.filter((a) => a.kind === "title"));
  const topics = computed(() => assets.value.filter((a) => a.kind === "topic"));

  async function reload(): Promise<void> {
    const r = await api().get("/api/xhs/custom-assets");
    assets.value = r.data.assets ?? [];
    loaded.value = true;
  }

  /** 首次加载（已加载则跳过）。面板挂载时调用。 */
  async function ensureLoaded(): Promise<void> {
    if (loaded.value) return;
    await reload();
  }

  async function create(kind: XhsAssetKind, payload: Record<string, any>): Promise<XhsCustomAsset> {
    const r = await api().post("/api/xhs/custom-assets", { kind, payload });
    const asset = r.data.asset as XhsCustomAsset;
    assets.value.unshift(asset); // 后端按 created_at DESC，新的在前
    return asset;
  }

  async function remove(id: string): Promise<void> {
    await api().delete(`/api/xhs/custom-assets/${id}`);
    assets.value = assets.value.filter((a) => a.id !== id);
  }

  return { assets, loaded, templates, copies, titles, topics, ensureLoaded, reload, create, remove };
});
