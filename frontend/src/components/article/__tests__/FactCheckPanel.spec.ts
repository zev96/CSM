import { mount, flushPromises } from "@vue/test-utils";
import { describe, it, expect, vi, beforeEach } from "vitest";

const resolveMock = vi.fn();
const state: any = {
  finalText: "电机 15万转。通过 CCC 认证。",
  factcheck: {
    blocked: true,
    violations: [
      { kind: "number", value: "15万转", number: 150000, sentence: "电机 15万转。", suggestion: "改用参数表数值" },
      { kind: "cert", value: "CCC", number: null, sentence: "通过 CCC 认证。", suggestion: "删除或换实际认证" },
    ],
  },
  resolveFactcheck: resolveMock,
};
vi.mock("@/stores/article", () => ({ useArticle: () => state }));
vi.mock("@/composables/useToast", () => ({ useToast: () => ({ success: vi.fn(), error: vi.fn(), warn: vi.fn() }) }));

import FactCheckPanel from "@/components/article/FactCheckPanel.vue";

// Dialog 内部用 <Teleport to="body">，而 @vue/test-utils 的 findAll 不会
// 穿进 teleport 目标（只有 text()/html() 会序列化它）。stub teleport 让
// Dialog 内容就地渲染，这样才能 findAll 到 footer 按钮 / 放行 checkbox。
const mountOpts = { props: { open: true }, global: { stubs: { teleport: true } } } as const;

describe("FactCheckPanel", () => {
  beforeEach(() => resolveMock.mockReset());

  it("渲染所有违规项 + 句子", () => {
    const w = mount(FactCheckPanel, mountOpts);
    expect(w.text()).toContain("15万转");
    expect(w.text()).toContain("CCC");
    expect(w.text()).toContain("电机 15万转。");
  });

  it("勾选放行后『重新核对并导出』回传归一 number + cert 名", async () => {
    resolveMock.mockResolvedValueOnce({ ok: true });
    const w = mount(FactCheckPanel, mountOpts);
    // 勾两个放行 checkbox
    const boxes = w.findAll("input[type='checkbox']");
    for (const b of boxes) await b.setValue(true);
    const btn = w.findAll("button").find((b) => b.text().includes("重新核对并导出"));
    await btn!.trigger("click");
    await flushPromises();
    expect(resolveMock).toHaveBeenCalledWith(state.finalText, [150000], ["CCC"]);
  });
});
