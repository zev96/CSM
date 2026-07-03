import { mount } from "@vue/test-utils";
import { setActivePinia, createPinia } from "pinia";
import { describe, it, expect, vi, beforeEach } from "vitest";

const post = vi.fn().mockResolvedValue({ data: { atoms: [] } });
const get = vi.fn().mockResolvedValue({ data: { folders: [] } });
vi.mock("@/stores/sidecar", () => ({ useSidecar: () => ({ client: { post, get } }) }));

import AtomizePanel from "@/components/materials/AtomizePanel.vue";
import { useMaterials } from "@/stores/materials";

describe("AtomizePanel 分块 UI", () => {
  beforeEach(() => setActivePinia(createPinia()));

  it("chunkProgress 时显示进度并出现取消按钮", async () => {
    const w = mount(AtomizePanel, { global: { stubs: { teleport: true } } });
    const m = useMaterials();
    m.chunkProgress = { current: 2, total: 4 };
    await w.vm.$nextTick();
    expect(w.text()).toContain("分块 2/4");
    expect(w.find("[data-atomize-cancel]").exists()).toBe(true);
  });

  it("点取消调 cancelAtomize", async () => {
    const w = mount(AtomizePanel, { global: { stubs: { teleport: true } } });
    const m = useMaterials();
    m.chunkProgress = { current: 1, total: 3 };
    const spy = vi.spyOn(m, "cancelAtomize");
    await w.vm.$nextTick();
    await w.find("[data-atomize-cancel]").trigger("click");
    expect(spy).toHaveBeenCalled();
  });
});
