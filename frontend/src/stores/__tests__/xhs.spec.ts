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

import { useXhs, _resetXhsModuleState, LLMNotConfiguredError } from "@/stores/xhs";
import { THEMES } from "@/data/xhs/assets";
import { orderedMarker } from "@/utils/xhsTheme";

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
  it("fullText 组装标题/正文（话题已内嵌正文）", () => {
    const x = useXhs();
    x.$patch({ title: "T", body: "B #a" });
    expect(x.fullText).toBe("T\n\nB #a");
  });
  it("字数与超限标志", () => {
    const x = useXhs();
    x.$patch({ title: "x".repeat(21) });
    expect(x.titleCount).toBe(21);
    expect(x.titleOver).toBe(true);
    expect(x.bodyOver).toBe(false);
  });
  it("isEmpty 看标题/正文/图片是否都为空", () => {
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

describe("useXhs — 话题（内嵌正文）", () => {
  it("addTopic 把 #话题 追加到正文末尾", () => {
    const x = useXhs();
    x.$patch({ body: "正文" });
    x.addTopic("穿搭");
    expect(x.body).toBe("正文 #穿搭");
  });
  it("addTopic 去前导 # 后追加", () => {
    const x = useXhs();
    x.$patch({ body: "" });
    x.addTopic("#通勤");
    expect(x.body).toBe("#通勤");
  });
  it("addTopic 去重：同名 #话题 已存在则跳过", () => {
    const x = useXhs();
    x.$patch({ body: "正文 #穿搭" });
    x.addTopic("穿搭");
    expect(x.body).toBe("正文 #穿搭"); // 不重复追加
  });
  it("addTopic 丢空", () => {
    const x = useXhs();
    x.$patch({ body: "正文" });
    x.addTopic("   ");
    expect(x.body).toBe("正文"); // 无变化
  });
  it("addTopic 正文末尾已有空格时不重复加空格", () => {
    const x = useXhs();
    x.$patch({ body: "正文 " });
    x.addTopic("干货");
    expect(x.body).toBe("正文 #干货");
  });
  it("topics 数组始终为空（话题入正文，不入数组）", () => {
    const x = useXhs();
    x.addTopic("穿搭");
    expect(x.topics).toEqual([]);
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
  it("copy('full') 写入剪贴板全文（话题已内嵌正文）", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { clipboard: { writeText } });
    const x = useXhs();
    x.$patch({ title: "T", body: "B #a" });
    await x.copy("full");
    expect(writeText).toHaveBeenCalledWith("T\n\nB #a");
    vi.unstubAllGlobals();
  });
});

describe("useXhs — 模板载入", () => {
  it("applyTemplate 覆盖标题/正文，模板话题拼入正文末尾，topics 数组为空", async () => {
    postMock.mockResolvedValue({ data: { id: "d1" } });
    patchMock.mockResolvedValue({ data: {} });
    const x = useXhs();
    x.$patch({ title: "旧", body: "旧正文", topics: ["旧"] });
    x.applyTemplate({ title: "新标题", body: "新正文\n第二行", topics: ["a", "b"] });
    expect(x.title).toBe("新标题");
    expect(x.body).toBe("新正文\n第二行 #a #b"); // 话题内嵌正文
    expect(x.topics).toEqual([]); // 数组始终空
    // 触发了去抖保存：800ms 后建草稿
    await vi.advanceTimersByTimeAsync(800);
    expect(postMock).toHaveBeenCalledTimes(1);
  });
});

describe("useXhs — 排版主题", () => {
  it("默认无激活主题，activeTheme=null、themeToolbar 为空", () => {
    const x = useXhs();
    expect(x.activeTheme).toBeNull();
    expect(x.themeToolbar).toEqual([]);
  });

  it("applyTheme 设激活主题，activeTheme 解析出主题对象", () => {
    const x = useXhs();
    const t = THEMES[0];
    x.applyTheme(t.id);
    expect(x.themeId).toBe(t.id);
    expect(x.activeTheme?.id).toBe(t.id);
  });

  it("themeToolbar 由激活主题映射出 小标题/无序/有序/分割线 四个按钮", () => {
    const x = useXhs();
    const t = THEMES[0];
    x.applyTheme(t.id);
    const tb = x.themeToolbar;
    expect(tb.map((b) => b.key)).toEqual(["heading", "bullet", "ordered", "divider"]);
    expect(tb.find((b) => b.key === "heading")?.symbol).toBe(t.heading);
    expect(tb.find((b) => b.key === "bullet")?.symbol).toBe(t.bullet);
    expect(tb.find((b) => b.key === "divider")?.symbol).toBe(t.divider);
  });

  it("applyTheme 触发去抖保存", async () => {
    postMock.mockResolvedValue({ data: { id: "d1" } });
    patchMock.mockResolvedValue({ data: {} });
    const x = useXhs();
    x.$patch({ title: "有内容" }); // 非空才会真的建草稿
    x.applyTheme(THEMES[0].id);
    await vi.advanceTimersByTimeAsync(800);
    expect(postMock).toHaveBeenCalledTimes(1);
  });

  it("themeToolbar 的「有序」symbol = 该主题样式的第 1 个序号字形", () => {
    const x = useXhs();
    const t = THEMES.find((th) => th.ordered === "circle") ?? THEMES[0];
    x.applyTheme(t.id);
    const ordered = x.themeToolbar.find((b) => b.key === "ordered");
    expect(ordered?.label).toBe("有序");
    expect(ordered?.symbol).toBe(orderedMarker(1, t.ordered));
  });

  it("insertOrdered 按正文已有序号数插入下一个序号", () => {
    const x = useXhs();
    const t = THEMES.find((th) => th.ordered === "emoji") ?? THEMES[0];
    x.applyTheme(t.id);
    x.setBody("1️⃣ 第一条\n"); // 已有 1 个 emoji 序号
    // 本测试未注册光标插入器 → insertAtCursor 回退「追加正文末」，故可直接断言 x.body
    x.insertOrdered();          // 应插入第 2 个 → "2️⃣ "
    expect(x.body).toContain("2️⃣ ");
  });

  it("无激活主题时 insertOrdered 不动正文", () => {
    const x = useXhs();
    x.setBody("原样");
    x.insertOrdered();
    expect(x.body).toBe("原样");
  });
});

describe("useXhs — 图片", () => {
  it("isEmpty 也看图片：有图即非空", () => {
    const x = useXhs();
    expect(x.isEmpty).toBe(true);
    x.$patch({ imageIds: ["a"] });
    expect(x.isEmpty).toBe(false);
  });

  it("uploadImage：空草稿也强制建 draft，再 POST 图片，把 id 推进 imageIds", async () => {
    postMock.mockResolvedValueOnce({ data: { id: "d1" } });            // _ensureCreated(force) 建草稿
    postMock.mockResolvedValueOnce({ data: { image_id: "img1", url: "/api/xhs/images/img1", size: 9 } }); // 上传
    patchMock.mockResolvedValue({ data: {} });
    const x = useXhs();
    const file = new File([new Uint8Array([1, 2, 3])], "a.png", { type: "image/png" });
    await x.uploadImage(file);
    expect(postMock).toHaveBeenCalledTimes(2);
    expect(x.draftId).toBe("d1");
    expect(postMock.mock.calls[1][0]).toBe("/api/xhs/drafts/d1/images");
    expect(x.imageIds).toEqual(["img1"]);
  });

  it("setCover 设封面下标", () => {
    const x = useXhs();
    x.$patch({ imageIds: ["a", "b", "c"] });
    x.setCover(2);
    expect(x.coverIndex).toBe(2);
  });

  it("removeImage：删封面前的图，封面下标左移保持指向同一张", () => {
    const x = useXhs();
    x.$patch({ imageIds: ["a", "b", "c"], coverIndex: 2 }); // 封面是 c
    x.removeImage(0); // 删 a
    expect(x.imageIds).toEqual(["b", "c"]);
    expect(x.coverIndex).toBe(1); // 仍指向 c
  });

  it("removeImage：删的就是封面，封面回退且不越界", () => {
    const x = useXhs();
    x.$patch({ imageIds: ["a", "b"], coverIndex: 1 });
    x.removeImage(1); // 删封面 b
    expect(x.imageIds).toEqual(["a"]);
    expect(x.coverIndex).toBe(0);
  });

  it("removeImage：删到空，封面归 0", () => {
    const x = useXhs();
    x.$patch({ imageIds: ["a"], coverIndex: 0 });
    x.removeImage(0);
    expect(x.imageIds).toEqual([]);
    expect(x.coverIndex).toBe(0);
  });

  it("removeImage：删封面后面的图，封面下标不变", () => {
    const x = useXhs();
    x.$patch({ imageIds: ["a", "b", "c"], coverIndex: 0 }); // 封面是 a
    x.removeImage(2); // 删 c（在封面之后）
    expect(x.imageIds).toEqual(["a", "b"]);
    expect(x.coverIndex).toBe(0); // 封面仍指向 a，不受影响
  });

  it("reorderImages：移动后封面跟随原图", () => {
    const x = useXhs();
    x.$patch({ imageIds: ["a", "b", "c"], coverIndex: 0 }); // 封面 a
    x.reorderImages(0, 2); // a 移到末尾 → [b, c, a]
    expect(x.imageIds).toEqual(["b", "c", "a"]);
    expect(x.coverIndex).toBe(2); // 封面仍是 a
  });
});

describe("isEmpty（话题入正文后）", () => {
  it("标题/正文/图全空时 isEmpty 为 true", () => {
    const s = useXhs();
    s.$patch({ title: "  ", body: "", imageIds: [] });
    expect(s.isEmpty).toBe(true);
  });

  it("正文含 #话题 文本时 isEmpty 为 false", () => {
    const s = useXhs();
    s.$patch({ title: "", body: "#穿搭", imageIds: [] });
    expect(s.isEmpty).toBe(false);
  });
});

describe("insertOrdered 按光标前列表块计数（P4）", () => {
  it("有探针时按当前块算下一个序号", () => {
    const s = useXhs();
    s.applyTheme("warm_yellow"); // 任一存在的主题；取其 ordered 样式
    const style = s.activeTheme!.ordered;
    const inserted: string[] = [];
    s.registerInserter((t) => inserted.push(t));
    // 当前块已有 2 个序号 → 期望插入第 3 个
    const before = `${orderedMarker(1, style)} a\n${orderedMarker(2, style)} b\n`;
    s.registerCursorProbe(() => ({ before }));
    s.insertOrdered();
    expect(inserted[0]).toBe(orderedMarker(3, style) + " ");
  });

  it("空行后是新块 → 从 1 起", () => {
    const s = useXhs();
    s.applyTheme("warm_yellow");
    const style = s.activeTheme!.ordered;
    const inserted: string[] = [];
    s.registerInserter((t) => inserted.push(t));
    s.registerCursorProbe(() => ({ before: `${orderedMarker(1, style)} a\n\n` }));
    s.insertOrdered();
    expect(inserted[0]).toBe(orderedMarker(1, style) + " ");
  });

  it("无探针时回退按整段正文尾块计数", () => {
    const s = useXhs();
    s.applyTheme("warm_yellow");
    const style = s.activeTheme!.ordered;
    s.$patch({ body: `${orderedMarker(1, style)} a\n` });
    const inserted: string[] = [];
    s.registerInserter((t) => inserted.push(t));
    s.registerCursorProbe(null);
    s.insertOrdered();
    expect(inserted[0]).toBe(orderedMarker(2, style) + " ");
  });
});

describe("useXhs — AI actions", () => {
  it("generateNote 返回后端 {title, body, topics}", async () => {
    const x = useXhs();
    postMock.mockResolvedValueOnce({ data: { title: "T", body: "B", topics: ["a", "b"] } });
    const out = await x.generateNote("主题");
    expect(out).toEqual({ title: "T", body: "B", topics: ["a", "b"] });
    expect(postMock).toHaveBeenCalledWith("/api/xhs/ai/generate", { intent: "主题" });
  });

  it("generateNote 缺字段时各自取空", async () => {
    const x = useXhs();
    postMock.mockResolvedValueOnce({ data: { title: "只有标题" } });
    const out = await x.generateNote("主题");
    expect(out).toEqual({ title: "只有标题", body: "", topics: [] });
  });

  it("503 llm_not_configured → 抛 LLMNotConfiguredError", async () => {
    const x = useXhs();
    postMock.mockRejectedValueOnce({
      response: { status: 503, data: { code: "llm_not_configured", detail: "去配置" } },
    });
    await expect(x.generateNote("主题")).rejects.toBeInstanceOf(LLMNotConfiguredError);
  });

  it("polishBody 把当前正文 POST 给 /polish 并返回 body", async () => {
    const x = useXhs();
    x.setBody("朴素正文");
    postMock.mockResolvedValueOnce({ data: { body: "润色后" } });
    const out = await x.polishBody();
    expect(out).toBe("润色后");
    expect(postMock).toHaveBeenCalledWith("/api/xhs/ai/polish", { text: "朴素正文" });
  });

  it("polishBody 非 503 错误原样抛出（不包成 LLMNotConfiguredError）", async () => {
    const x = useXhs();
    x.setBody("正文");
    postMock.mockRejectedValueOnce({ response: { status: 502, data: { code: "llm_error" } } });
    await expect(x.polishBody()).rejects.not.toBeInstanceOf(LLMNotConfiguredError);
  });
});

describe("草稿 重命名 / 复制副本（P4）", () => {
  it("renameDraft PATCH 标题并刷新列表；当前草稿同步标题", async () => {
    getMock.mockResolvedValue({ data: { drafts: [] } });
    patchMock.mockResolvedValue({ data: {} });
    const s = useXhs();
    s.$patch({ draftId: "d1", title: "旧" });
    await s.renameDraft("d1", "新标题");
    expect(patchMock).toHaveBeenCalledWith("/api/xhs/drafts/d1", { title: "新标题" });
    expect(s.title).toBe("新标题");   // 当前草稿 id === "d1" → 同步本地标题
    expect(getMock).toHaveBeenCalledWith("/api/xhs/drafts"); // loadDrafts 触发
  });

  it("renameDraft 当前打开的不是被改名的草稿，不同步本地标题", async () => {
    getMock.mockResolvedValue({ data: { drafts: [] } });
    patchMock.mockResolvedValue({ data: {} });
    const s = useXhs();
    s.$patch({ draftId: "d2", title: "我自己的标题" });
    await s.renameDraft("d1", "另一篇的新标题");
    expect(s.title).toBe("我自己的标题"); // 不影响当前草稿
  });

  it("duplicateDraft POST /duplicate 并刷新列表，返回新 id", async () => {
    getMock.mockResolvedValue({ data: { drafts: [] } });
    postMock.mockResolvedValue({ data: { id: "d2" } });
    const s = useXhs();
    const newId = await s.duplicateDraft("d1");
    expect(postMock).toHaveBeenCalledWith("/api/xhs/drafts/d1/duplicate");
    expect(getMock).toHaveBeenCalledWith("/api/xhs/drafts"); // loadDrafts 触发
    expect(newId).toBe("d2");
  });

  it("duplicateDraft 后端不返回 id 时返回 null", async () => {
    getMock.mockResolvedValue({ data: { drafts: [] } });
    postMock.mockResolvedValue({ data: {} });
    const s = useXhs();
    const newId = await s.duplicateDraft("d1");
    expect(newId).toBeNull();
  });
});
