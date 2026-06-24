import { setActivePinia, createPinia } from "pinia";
import { describe, it, expect, vi, beforeEach } from "vitest";

const postMock = vi.fn();
const getMock = vi.fn().mockResolvedValue({ data: {} });
vi.mock("@/stores/sidecar", () => ({
  useSidecar: () => ({ client: { post: postMock, get: getMock } }),
}));
vi.mock("@/api/client", () => ({
  subscribe: () => () => {},
}));
vi.mock("@/composables/useNotifications", () => ({
  useNotifications: () => ({ push: vi.fn() }),
}));

import { useArticle } from "@/stores/article";
import type { Angle } from "@/stores/article";

describe("article store — angle / title", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    postMock.mockReset();
    getMock.mockReset();
    getMock.mockResolvedValue({ data: {} });
  });

  it("submit POSTs title + angle in the body", async () => {
    postMock.mockResolvedValueOnce({ data: { job_id: "j1" } });
    const a = useArticle();
    const angle: Angle = {
      audience: "铲屎官",
      sellpoints: ["防缠绕技术", "续航时间"],
      tone: "口语",
    };
    await a.submit({
      keyword: "无线吸尘器",
      template_id: "t",
      title: "无线吸尘器哪款好用？实测分享",
      angle,
    });
    expect(postMock).toHaveBeenCalledWith("/api/generate", expect.objectContaining({
      keyword: "无线吸尘器",
      template_id: "t",
      title: "无线吸尘器哪款好用？实测分享",
      angle,
    }));
  });

  it("lastRequest retains angle + title", async () => {
    postMock.mockResolvedValueOnce({ data: { job_id: "j2" } });
    const a = useArticle();
    const angle: Angle = { audience: "宝妈", sellpoints: ["绿光显尘"], tone: null };
    await a.submit({ keyword: "k", template_id: "t", title: "标题X", angle });
    expect(a.lastRequest?.title).toBe("标题X");
    expect(a.lastRequest?.angle).toEqual(angle);
  });

  it("rerun keeps angle + title (seed bumped)", async () => {
    postMock.mockResolvedValueOnce({ data: { job_id: "j3" } });
    const a = useArticle();
    const angle: Angle = { audience: "老年人", sellpoints: [], tone: "专业" };
    await a.submit({ keyword: "k", template_id: "t", seed: 2, title: "标题Y", angle });
    postMock.mockResolvedValueOnce({ data: { job_id: "j4" } });
    await a.rerun();
    const lastCall = postMock.mock.calls[postMock.mock.calls.length - 1];
    expect(lastCall[0]).toBe("/api/generate");
    expect(lastCall[1]).toMatchObject({ title: "标题Y", angle, seed: 3 });
  });

  it("omits title/angle when not provided (today's behaviour)", async () => {
    postMock.mockResolvedValueOnce({ data: { job_id: "j5" } });
    const a = useArticle();
    await a.submit({ keyword: "k", template_id: "t" });
    const body = postMock.mock.calls[0][1];
    expect(body.title).toBeUndefined();
    expect(body.angle).toBeUndefined();
  });

  it("fetchAngleTaxonomy GETs once and caches", async () => {
    const taxonomy = {
      tones: [{ key: "口语", hint: "h" }],
      dimensions: [{ key: "防缠绕技术", label: "防缠绕" }],
      audiences: ["铲屎官"],
      presets: [{ name: "p", template_id: null, audience: null, sellpoints: [], tone: null }],
    };
    getMock.mockResolvedValue({ data: taxonomy });
    const a = useArticle();
    await a.fetchAngleTaxonomy();
    await a.fetchAngleTaxonomy();
    const taxCalls = getMock.mock.calls.filter((c) => c[0] === "/api/angle/taxonomy");
    expect(taxCalls).toHaveLength(1);
    expect(a.angleTaxonomy).toEqual(taxonomy);
  });
});
