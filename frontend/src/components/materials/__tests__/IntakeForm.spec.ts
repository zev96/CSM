import { setActivePinia, createPinia } from "pinia";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { mount } from "@vue/test-utils";

const getMock = vi.fn();
const postMock = vi.fn();
vi.mock("@/stores/sidecar", () => ({
  useSidecar: () => ({ client: { get: getMock, post: postMock } }),
}));
vi.mock("@/composables/useNotifications", () => ({ useNotifications: () => ({ push: vi.fn() }) }));

import IntakeForm from "@/components/materials/IntakeForm.vue";

const FOLDERS = { data: { folders: [
  { rel_folder: "科普模块/吸尘器/挑选攻略", frontmatter_keys: ["产品", "素材类型", "核心关键词"],
    defaults: { 产品: "吸尘器", 素材类型: "科普选购" }, body_shape: "variants",
    sample_count: 2, material_types: ["科普选购"] },
] } };

describe("IntakeForm", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    getMock.mockReset(); postMock.mockReset();
    getMock.mockResolvedValue(FOLDERS);
  });

  it("挂载即加载文件夹列表", async () => {
    const w = mount(IntakeForm);
    await new Promise((r) => setTimeout(r));
    expect(getMock).toHaveBeenCalledWith("/api/vault/writable-folders");
    expect(w.find('[data-folder="科普模块/吸尘器/挑选攻略"]').exists()).toBe(true);
  });

  it("选文件夹后按 defaults 预填 + body 形状为变体", async () => {
    const w = mount(IntakeForm);
    await new Promise((r) => setTimeout(r));
    await w.find('[data-folder="科普模块/吸尘器/挑选攻略"]').trigger("click");
    await w.vm.$nextTick();
    expect(w.find('[data-variant-row]').exists()).toBe(true);
    const prod = w.find('[data-fm="产品"]').element as HTMLInputElement;
    expect(prod.value).toBe("吸尘器");
  });
});
