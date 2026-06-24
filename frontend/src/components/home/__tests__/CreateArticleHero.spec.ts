import { mount, flushPromises } from "@vue/test-utils";
import { setActivePinia, createPinia } from "pinia";
import { describe, it, expect, vi, beforeEach } from "vitest";

const pushMock = vi.fn();
vi.mock("vue-router", () => ({
  useRouter: () => ({ push: pushMock }),
}));

vi.mock("@/stores/config", () => ({
  useConfig: () => ({ data: { user_name: "测试" } }),
}));

const getMock = vi.fn();
vi.mock("@/stores/sidecar", () => ({
  useSidecar: () => ({ client: { get: getMock } }),
}));

vi.mock("@/composables/useSidecarReady", () => ({
  useSidecarReady: () => ({ whenReady: () => Promise.resolve() }),
}));

// AnglePicker pulls taxonomy via the article store — stub the heavy child so
// the Hero spec stays focused on takeoff() query assembly.
vi.mock("@/components/article/AnglePicker.vue", () => ({
  default: { name: "AnglePicker", template: "<div class='angle-picker-stub' />" },
}));

import CreateArticleHero from "@/components/home/CreateArticleHero.vue";

const TEMPLATES = { templates: [{ id: "tpl-a", name: "模板A" }, { id: "tpl-b", name: "模板B" }] };
const SKILLS = { skills: [{ id: "sk-a", name: "风格A" }] };

function setupSidecar() {
  getMock.mockImplementation((url: string) => {
    if (url === "/api/templates") return Promise.resolve({ data: TEMPLATES });
    if (url === "/api/skills") return Promise.resolve({ data: SKILLS });
    return Promise.resolve({ data: {} });
  });
}

describe("CreateArticleHero — 角度 chip + query", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    pushMock.mockReset();
    getMock.mockReset();
    setupSidecar();
  });

  it("渲染「角度」chip（与 模板/风格 平级）", async () => {
    const w = mount(CreateArticleHero, { global: { stubs: { teleport: true } } });
    await flushPromises();
    expect(w.text()).toContain("角度");
  });

  it("无角度选择时 takeoff query 不带 audience/sellpoints/tone/title", async () => {
    const w = mount(CreateArticleHero, { global: { stubs: { teleport: true } } });
    await flushPromises();
    (w.vm as any).keyword = "无线吸尘器";
    (w.vm as any).takeoff();
    expect(pushMock).toHaveBeenCalledTimes(1);
    const query = pushMock.mock.calls[0][0].query;
    expect(query.keyword).toBe("无线吸尘器");
    expect(query.audience).toBeUndefined();
    expect(query.sellpoints).toBeUndefined();
    expect(query.tone).toBeUndefined();
    expect(query.title).toBeUndefined();
  });

  it("选了角度后 takeoff query 含扁平 audience/sellpoints(逗号)/tone/title", async () => {
    const w = mount(CreateArticleHero, { global: { stubs: { teleport: true } } });
    await flushPromises();
    (w.vm as any).keyword = "无线吸尘器";
    (w.vm as any).angle = { audience: "铲屎官", sellpoints: ["防缠绕技术", "续航时间"], tone: "口语" };
    (w.vm as any).title = "我的标题";
    (w.vm as any).takeoff();
    const query = pushMock.mock.calls[0][0].query;
    expect(query.audience).toBe("铲屎官");
    expect(query.sellpoints).toBe("防缠绕技术,续航时间");
    expect(query.tone).toBe("口语");
    expect(query.title).toBe("我的标题");
  });

  it("角度部分为空（仅卖点）时只带非空 facet", async () => {
    const w = mount(CreateArticleHero, { global: { stubs: { teleport: true } } });
    await flushPromises();
    (w.vm as any).keyword = "k";
    (w.vm as any).angle = { audience: null, sellpoints: ["防缠绕技术"], tone: null };
    (w.vm as any).takeoff();
    const query = pushMock.mock.calls[0][0].query;
    expect(query.sellpoints).toBe("防缠绕技术");
    expect(query.audience).toBeUndefined();
    expect(query.tone).toBeUndefined();
    expect(query.title).toBeUndefined();
  });

  it("pick-template 更新选中模板（进入 query）", async () => {
    const w = mount(CreateArticleHero, { global: { stubs: { teleport: true } } });
    await flushPromises();
    (w.vm as any).keyword = "k";
    (w.vm as any).onPickTemplate("tpl-b");
    (w.vm as any).takeoff();
    const query = pushMock.mock.calls[0][0].query;
    expect(query.template_id).toBe("tpl-b");
  });
});
