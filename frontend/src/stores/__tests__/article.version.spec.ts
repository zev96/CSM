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

  it("rerun() 无参 = 锁当前版本只换素材（「只换文字·锁结构」入口用它）", async () => {
    // store 原语：无参锁当前版本。注意 UI 主按钮「全部重采」现在显式传 null
    // 走自由重抽（见 article.version 的 rerun(null) 用例）；这条只钉原语本身。
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
  it("先锁版本再「换个版本」时能真正解锁（不被 lastRequest 里的旧锁带回去）", async () => {
    // rerun() 会把锁写进 lastRequest；rerun(null) 如果只是「不再添加」，
    // 展开 lastRequest 时旧锁会原样带出去 —— 换版本按钮就永久失效了。
    const a = useArticle();
    await seed(a, { rec_ver: "版本1" });
    await a.rerun();                       // 第一次：锁上版本1
    expect(postMock.mock.calls[0][1].version_overrides).toEqual({ rec_ver: "版本1" });
    a.plan = { version_choices: { rec_ver: "版本1" } } as any;
    await a.rerun(null);                   // 第二次：显式解锁
    expect(postMock.mock.calls[1][1].version_overrides).toBeUndefined();
  });
});
