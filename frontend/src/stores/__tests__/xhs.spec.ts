import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { createPinia, setActivePinia } from "pinia";

const getMock = vi.fn();
const postMock = vi.fn();
const patchMock = vi.fn();
const deleteMock = vi.fn();
vi.mock("@/stores/sidecar", () => ({
  useSidecar: () => ({
    client: { get: getMock, post: postMock, patch: patchMock, delete: deleteMock },
    sseURL: (p: string) => p,
  }),
}));

import { useXhs, _resetXhsModuleState } from "@/stores/xhs";

beforeEach(() => {
  setActivePinia(createPinia());
  _resetXhsModuleState();
  getMock.mockReset();
  postMock.mockReset();
  patchMock.mockReset();
  deleteMock.mockReset();
  // 全程用 fake timers：scheduleSave 的模块级 _saveTimer 不会在用例间
  // 乱触发；afterEach 清掉所有挂起定时器，杜绝跨用例污染。
  vi.useFakeTimers();
});

afterEach(() => {
  vi.clearAllTimers();
  vi.useRealTimers();
});

describe("useXhs — getters", () => {
  it("fullText 组装标题/正文/话题", () => {
    const x = useXhs();
    x.$patch({ title: "T", body: "B", topics: ["a"] });
    expect(x.fullText).toBe("T\n\nB\n\n#a");
  });
  it("字数与超限标志", () => {
    const x = useXhs();
    x.$patch({ title: "x".repeat(21) });
    expect(x.titleCount).toBe(21);
    expect(x.titleOver).toBe(true);
    expect(x.bodyOver).toBe(false);
  });
  it("isEmpty 看标题与正文是否都空白", () => {
    const x = useXhs();
    expect(x.isEmpty).toBe(true);
    x.$patch({ body: "  " });
    expect(x.isEmpty).toBe(true);
    x.$patch({ body: "字" });
    expect(x.isEmpty).toBe(false);
  });
});

describe("useXhs — 自动保存 _ensureCreated", () => {
  it("空草稿 saveNow 不发请求", async () => {
    const x = useXhs();
    await x.saveNow();
    expect(postMock).not.toHaveBeenCalled();
    expect(patchMock).not.toHaveBeenCalled();
  });

  it("首次有内容 → POST 建草稿一次；再 saveNow → 只 PATCH", async () => {
    postMock.mockResolvedValue({ data: { id: "d1", title: "T", body: "", topics: [], image_ids: [], cover_index: 0, theme_id: null } });
    patchMock.mockResolvedValue({ data: {} });
    const x = useXhs();
    x.$patch({ title: "T" });

    await x.saveNow();
    expect(postMock).toHaveBeenCalledTimes(1);
    expect(x.draftId).toBe("d1");
    expect(patchMock).toHaveBeenCalledTimes(1); // saveNow 在 _ensureCreated(POST) 后继续走一次 PATCH
    expect(patchMock).toHaveBeenCalledWith("/api/xhs/drafts/d1", expect.objectContaining({ title: "T" }));

    await x.saveNow();
    expect(postMock).toHaveBeenCalledTimes(1); // 不再建第二次
    expect(patchMock).toHaveBeenCalledTimes(2);
  });

  it("scheduleSave 去抖：800ms 后触发一次 saveNow", async () => {
    // fake timers 已在 beforeEach 全局开启
    postMock.mockResolvedValue({ data: { id: "d1" } });
    patchMock.mockResolvedValue({ data: {} });
    const x = useXhs();
    x.setTitle("a");
    x.setTitle("ab");
    x.setTitle("abc"); // 连续输入只应触发一次
    expect(postMock).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(800);
    expect(postMock).toHaveBeenCalledTimes(1);
  });

  it("并发 saveNow 只建一次草稿（in-flight 去重）", async () => {
    let resolvePost!: (v: unknown) => void;
    postMock.mockReturnValue(new Promise((res) => { resolvePost = res; }));
    patchMock.mockResolvedValue({ data: {} });
    const x = useXhs();
    x.$patch({ title: "T" });
    const p1 = x.saveNow();
    const p2 = x.saveNow();   // 与 p1 并发：应复用同一个 in-flight POST
    resolvePost({ data: { id: "d1" } });
    await Promise.all([p1, p2]);
    expect(postMock).toHaveBeenCalledTimes(1); // 只建一次
    expect(x.draftId).toBe("d1");
  });
});

describe("useXhs — 话题", () => {
  it("addTopic 去前导 # + 去重 + 丢空", () => {
    const x = useXhs();
    x.addTopic("#考证");
    x.addTopic("考证"); // 重复
    x.addTopic("   ");  // 空
    x.addTopic("干货");
    expect(x.topics).toEqual(["考证", "干货"]);
  });
  it("removeTopic 按下标删除", () => {
    const x = useXhs();
    x.$patch({ topics: ["a", "b", "c"] });
    x.removeTopic(1);
    expect(x.topics).toEqual(["a", "c"]);
  });
});

describe("useXhs — 光标插入入口", () => {
  it("注册 inserter 后 insertAtCursor 委托给它", () => {
    const x = useXhs();
    const fn = vi.fn();
    x.registerInserter(fn);
    x.insertAtCursor("💛");
    expect(fn).toHaveBeenCalledWith("💛");
  });
  it("未注册 inserter 时回退为追加到正文末尾", () => {
    const x = useXhs();
    x.$patch({ body: "abc" });
    x.insertAtCursor("!");
    expect(x.body).toBe("abc!");
  });
});

describe("useXhs — 复制", () => {
  it("copy('full') 写入剪贴板全文", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { clipboard: { writeText } });
    const x = useXhs();
    x.$patch({ title: "T", body: "B", topics: ["a"] });
    await x.copy("full");
    expect(writeText).toHaveBeenCalledWith("T\n\nB\n\n#a");
    vi.unstubAllGlobals();
  });
});
