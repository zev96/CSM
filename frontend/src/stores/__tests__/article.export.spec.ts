import { setActivePinia, createPinia } from "pinia";
import { describe, it, expect, vi, beforeEach } from "vitest";

const postMock = vi.fn();
const getMock = vi.fn().mockResolvedValue({ data: {} });
vi.mock("@/stores/sidecar", () => ({
  useSidecar: () => ({ client: { post: postMock, get: getMock } }),
}));
vi.mock("@/api/client", () => ({ subscribe: () => () => {} }));
vi.mock("@/composables/useNotifications", () => ({
  useNotifications: () => ({ push: vi.fn() }),
}));

import { useArticle } from "@/stores/article";

describe("article store — 导出", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    postMock.mockReset();
    getMock.mockReset();
    getMock.mockResolvedValue({ data: {} });
  });

  it("带上标题 —— 成稿正文里没有标题，不带过来导出的文档就没有标题", async () => {
    // finalText 是纯正文（标题是单独字段，编辑器显示时才临时拼上 `# 标题`）。
    // 只发正文的话导出的 .md/.docx 通篇无标题，历史索引的标题列还会退化成
    // 第一个章节名（「一、品牌分析」）—— 用户看到的就是「润色把标题去掉了」。
    const a = useArticle();
    postMock.mockResolvedValueOnce({ data: { job_id: "j1" } });
    await a.submit({ keyword: "空气净化器", template_id: "t", seed: 1 });
    a.finalText = "## 一、品牌分析\n\n正文";
    a.title = "2026年空气净化器十大排名";
    postMock.mockReset();
    postMock.mockResolvedValue({ data: { document: "d.md", format: "markdown" } });

    await a.exportArticle({ format: "markdown" });

    expect(postMock).toHaveBeenCalledWith(
      "/api/export/markdown",
      expect.objectContaining({
        final_text: "## 一、品牌分析\n\n正文",
        title: "2026年空气净化器十大排名",
      }),
    );
  });

  it("没有标题时传 null，由后端回落到关键词", async () => {
    const a = useArticle();
    postMock.mockResolvedValueOnce({ data: { job_id: "j1" } });
    await a.submit({ keyword: "空气净化器", template_id: "t", seed: 1 });
    a.finalText = "正文";
    a.title = "";
    postMock.mockReset();
    postMock.mockResolvedValue({ data: { document: "d.md", format: "markdown" } });

    await a.exportArticle({ format: "markdown" });

    expect(postMock.mock.calls[0][1].title).toBeNull();
  });
});
