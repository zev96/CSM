import { mount, flushPromises } from "@vue/test-utils";
import { describe, it, expect, vi, beforeEach } from "vitest";

// ── hoisted spy refs so vi.mock factories can reference them ────────────
const { postMock, getMock, pushMock } = vi.hoisted(() => ({
  postMock: vi.fn(),
  getMock: vi.fn(),
  pushMock: vi.fn(),
}));

vi.mock("vue-router", () => ({
  useRoute: () => ({ params: { id: "new" } }),
  useRouter: () => ({ push: pushMock }),
}));
vi.mock("@/stores/sidecar", () => ({
  useSidecar: () => ({ client: { post: postMock, get: getMock } }),
}));
vi.mock("@/composables/useToast", () => ({
  useToast: () => ({ success: vi.fn(), error: vi.fn(), warn: vi.fn() }),
}));

import SkillEditView from "@/views/SkillEditView.vue";

describe("SkillEditView role", () => {
  beforeEach(() => {
    postMock.mockReset();
    getMock.mockReset();
    pushMock.mockReset();
  });

  it("创建时 payload 带 role（默认 persona）", async () => {
    postMock.mockResolvedValueOnce({
      data: { id: "x", name: "x", role: "persona" },
    });
    const w = mount(SkillEditView);

    // 名称非空 —— save 会校验
    const name = w.find("input");
    await name.setValue("测试人设");

    // create 模式下保存按钮文案 = 「创建」
    const saveBtn = w.findAll("button").find((b) => b.text().includes("创建"));
    expect(saveBtn).toBeTruthy();
    await saveBtn!.trigger("click");
    await flushPromises();

    expect(postMock).toHaveBeenCalledWith(
      "/api/skills",
      expect.objectContaining({ role: "persona" }),
    );

    w.unmount();
  });
});
