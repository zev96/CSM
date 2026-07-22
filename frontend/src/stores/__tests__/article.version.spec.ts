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

async function seed(a: ReturnType<typeof useArticle>, choices: Record<string, string> | null) {
  postMock.mockResolvedValueOnce({ data: { job_id: "j1" } });
  await a.submit({ keyword: "空气净化器", template_id: "t", seed: 3 });
  a.plan = choices ? ({ version_choices: choices } as any) : null;
  postMock.mockReset();
  postMock.mockResolvedValue({ data: { job_id: "j2" } });
}

describe("article store — 结构版本", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    postMock.mockReset();
    getMock.mockReset();
    getMock.mockResolvedValue({ data: {} });
  });

  it("「重新随机」锁住当前版本，只换素材", async () => {
    // 2 个版本下不锁的话，点一次重随有一半概率整篇换结构。
    const a = useArticle();
    await seed(a, { rec_ver: "版本1·口碑权威型" });
    await a.rerun();
    expect(postMock).toHaveBeenCalledWith(
      "/api/generate",
      expect.objectContaining({
        seed: 4,
        version_overrides: { rec_ver: "版本1·口碑权威型" },
      }),
    );
  });

  it("显式换版本时传新版本", async () => {
    const a = useArticle();
    await seed(a, { rec_ver: "版本1" });
    await a.rerunWithVersion("rec_ver", "版本2");
    expect(postMock).toHaveBeenCalledWith(
      "/api/generate",
      expect.objectContaining({ version_overrides: { rec_ver: "版本2" } }),
    );
  });

  it("传 null 放开锁，让种子重新抽", async () => {
    const a = useArticle();
    await seed(a, { rec_ver: "版本1" });
    await a.rerun(null);
    const body = postMock.mock.calls[0][1];
    expect(body.version_overrides).toBeUndefined();
    expect(body.seed).toBe(4);
  });

  it("没有版本组的模板不带 version_overrides（零回归）", async () => {
    const a = useArticle();
    await seed(a, null);
    await a.rerun();
    const body = postMock.mock.calls[0][1];
    expect(body.version_overrides).toBeUndefined();
  });
});
