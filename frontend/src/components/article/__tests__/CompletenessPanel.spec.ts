import { mount } from "@vue/test-utils";
import { setActivePinia, createPinia } from "pinia";
import { describe, it, expect, vi, beforeEach } from "vitest";
import CompletenessPanel from "@/components/article/CompletenessPanel.vue";
import { useArticle, type MissingFact } from "@/stores/article";

vi.mock("@/stores/sidecar", () => ({ useSidecar: () => ({ client: { post: vi.fn(), get: vi.fn() } }) }));

const MISS: MissingFact = { kind: "number", token: "250AW", value: 250, sentence: "吸力 250AW。" };

describe("CompletenessPanel", () => {
  beforeEach(() => setActivePinia(createPinia()));

  it("渲染缺失项", () => {
    const a = useArticle();
    a.completeness = { checked: true, missing: [MISS] };
    const w = mount(CompletenessPanel, {
      props: { open: true }, global: { stubs: { teleport: true } } });
    expect(w.findAll("[data-missing-fact]")).toHaveLength(1);
    expect(w.text()).toContain("250AW");
  });
});
