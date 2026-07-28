/**
 * 成稿 tab 的版面契约：**成稿必须和初稿是同一个编辑器**。
 *
 * 用户报「成稿界面和初稿不一样、无法修改、无法下拉看全文、标题没显示」：
 * 链的 pass 预览曾是常驻在编辑器上方的条带，而它是 `min-height:auto` 的不可
 * 压缩 flex item —— 一条 pass 就是整篇正文（5000+ 字），把 `flex:1 1 0` 的成稿
 * 编辑器压成 0 高，外层编辑卡又是 `overflow-hidden`，于是既没有编辑器也没有
 * 滚动条。用户以为的「成稿」其实是那块只读的 `v-html` 诊断预览。
 * 修法：逐 pass 预览整体搬进模态，成稿列只剩「头部 + 编辑卡」，与初稿同构。
 *
 * 这里钉四条不变量：
 *   1. 两个 tab 的内容列结构一致（编辑器上方不夹任何东西）；
 *   2. 成稿编辑器可编辑，且与初稿同口径带 `# 标题` 首行；
 *   3. 逐 pass 预览只在模态里（含「重跑此 pass」），默认不占版面；
 *   4. 起新一轮清空 passes 时模态自动关闭（不留空壳）。
 */
import { mount, flushPromises } from "@vue/test-utils";
import { setActivePinia, createPinia } from "pinia";
import { describe, it, expect, vi, beforeEach, beforeAll } from "vitest";

beforeAll(() => {
  vi.stubGlobal("matchMedia", (q: string) => ({
    matches: true, media: q,
    addEventListener() {}, removeEventListener() {},
    addListener() {}, removeListener() {},
    onchange: null, dispatchEvent() { return false; },
  }));
});

let routeQuery: Record<string, any> = {};
const pushMock = vi.fn();
vi.mock("vue-router", () => ({
  useRoute: () => ({ query: routeQuery }),
  useRouter: () => ({ push: pushMock }),
}));

const postMock = vi.fn();
const getMock = vi.fn();
vi.mock("@/stores/sidecar", () => ({
  useSidecar: () => ({ client: { post: postMock, get: getMock }, ready: true, error: null, mode: "native" }),
}));
vi.mock("@/api/client", () => ({ subscribe: () => () => {} }));
vi.mock("@/composables/useNotifications", () => ({
  useNotifications: () => ({ push: vi.fn() }),
}));
vi.mock("@/composables/useSidecarReady", () => ({
  useSidecarReady: () => ({ whenReady: () => Promise.resolve(), ready: { value: true } }),
}));
vi.mock("@/composables/useToast", () => ({
  useToast: () => ({ success: vi.fn(), error: vi.fn(), warn: vi.fn(), info: vi.fn() }),
}));
vi.mock("@/composables/useFailureAlert", () => ({
  failureAlert: vi.fn().mockResolvedValue("close"),
}));
vi.mock("@/stores/config", () => ({
  useConfig: () => ({ data: { user_name: "测试" }, load: vi.fn() }),
}));
// 声明 modelValue/readonly 才能在测试里读回编辑器实际收到的正文。
vi.mock("@/components/article/TiptapEditor.vue", () => ({
  default: {
    name: "TiptapEditor",
    props: { modelValue: String, placeholder: String, readonly: Boolean, minHeight: Number },
    template: "<div class='tiptap-stub' />",
  },
}));
vi.mock("@/components/article/FactCheckPanel.vue", () => ({
  default: { name: "FactCheckPanel", template: "<div />" },
}));

import ArticleView from "@/views/ArticleView.vue";
import { useArticle, type ChainPass } from "@/stores/article";

const LONG_OUTPUT = "润色后的长正文。".repeat(400); // ~3200 字，真实 pass 的量级

function mkPass(over: Partial<ChainPass> = {}): ChainPass {
  return {
    index: 0, role: "persona", skill_id: "p", skill_name: "人设",
    output: LONG_OUTPUT, input_chars: 10, output_chars: LONG_OUTPUT.length, ...over,
  };
}

async function mountArticle(setup: (a: ReturnType<typeof useArticle>) => void = () => {}) {
  routeQuery = { keyword: "空气净化器推荐", template_id: "tpl-a" };
  const w = mount(ArticleView, { global: { stubs: { teleport: true } } });
  await flushPromises();
  setup(useArticle());
  await flushPromises();
  return w;
}

async function switchTab(w: ReturnType<typeof mount>, tab: "assembly" | "draft" | "final") {
  (w.vm as any).activeTab = tab;
  await flushPromises();
}

/**
 * 内容列（头部 + 编辑卡）的结构指纹 —— 两个 tab 必须一致。
 *
 * 三层都要看：原来的 bug 是「编辑器多了个不可压缩的 flex 兄弟」，而这种兄弟
 * 能插在三个位置 —— 内容列里（childCount 变）、编辑卡 wrapper 里（wrapChildCount
 * 变）、白卡里编辑器上方（cardChildCount / cardFirstTag 变）。只守第一层的话，
 * 后两种回归会原样复现最初的 0 高编辑器而测试照过。
 */
function paneShape(w: ReturnType<typeof mount>, pane: "draft" | "final") {
  const root = w.find(`[data-tab-pane="${pane}"]`).element as HTMLElement;
  const wrap = root.children[root.children.length - 1] as HTMLElement;
  const card = wrap.children[0] as HTMLElement;
  return {
    childCount: root.children.length,
    // 编辑卡 wrapper（内容列最后一个孩子）
    editorWrapClass: wrap.className,
    editorWrapStyle: wrap.getAttribute("style"),
    wrapChildCount: wrap.children.length,
    // 白卡本身：里面只能有编辑器
    editorCardClass: card.className,
    editorCardStyle: card.getAttribute("style"),
    cardChildCount: card.children.length,
    cardFirstClass: (card.children[0] as HTMLElement).className,
  };
}

describe("ArticleView — 成稿 = 初稿同一个编辑器", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    postMock.mockReset();
    postMock.mockResolvedValue({ data: { job_id: "j1" } });
    getMock.mockReset();
    getMock.mockImplementation((url: string) => {
      if (url === "/api/templates") return Promise.resolve({ data: { templates: [{ id: "tpl-a", name: "模板A" }] } });
      if (url === "/api/skills") return Promise.resolve({ data: { skills: [] } });
      return Promise.resolve({ data: {} });
    });
    pushMock.mockReset();
    routeQuery = {};
  });

  it("有链时，成稿内容列结构与初稿一致（编辑器上方不夹 pass 条带）", async () => {
    const w = await mountArticle((a) => {
      a.passes = [mkPass({ index: 0 }), mkPass({ index: 1, skill_id: "h", role: "humanize", skill_name: "去AI味" })];
      a.draftText = "毛坯正文";
      a.finalText = "成稿正文";
    });

    await switchTab(w, "draft");
    const draft = paneShape(w, "draft");
    await switchTab(w, "final");
    const final = paneShape(w, "final");

    // 头部 + 编辑卡，就这两块 —— pass 条带在这里出现过，正是它把编辑器挤没的
    expect(draft.childCount).toBe(2);
    // 编辑器上方/下方也不能夹东西：wrapper 里只有白卡，白卡里只有编辑器
    expect(draft.wrapChildCount).toBe(1);
    expect(draft.cardChildCount).toBe(1);
    expect(draft.cardFirstClass).toContain("tiptap-stub");
    expect(final).toEqual(draft);
  });

  it("模态打开时成稿列结构不变（pass 卡不回流进编辑区）", async () => {
    const w = await mountArticle((a) => {
      a.passes = [mkPass({ index: 0 })];
      a.finalText = "成稿正文";
    });
    await switchTab(w, "final");
    const before = paneShape(w, "final");
    await w.find("[data-passes-open]").trigger("click");
    expect(w.findAll("[data-pass-card]").length).toBe(1);
    expect(paneShape(w, "final")).toEqual(before);
  });

  it("成稿 tab 默认不渲染任何 pass 卡", async () => {
    const w = await mountArticle((a) => {
      a.passes = [mkPass({ index: 0 })];
      a.finalText = "成稿正文";
    });
    await switchTab(w, "final");
    expect(w.findAll("[data-pass-card]").length).toBe(0);
    expect(w.findAll("[data-rerun-pass]").length).toBe(0);
    // 但入口按钮在
    expect(w.find("[data-passes-open]").exists()).toBe(true);
    expect(w.find("[data-passes-open]").text()).toContain("润色过程 1 轮");
  });

  it("成稿编辑器可编辑，且正文带 # 标题首行（与初稿同口径）", async () => {
    const w = await mountArticle((a) => {
      a.passes = [mkPass({ index: 0 })];
      a.title = "养宠家庭空气净化器推荐哪款好？";
      a.finalText = "## 一、品牌分析\n正文…";
    });
    await switchTab(w, "final");
    const ed = w.findComponent({ name: "TiptapEditor" });
    expect(ed.exists()).toBe(true);
    expect(ed.props("readonly")).toBeFalsy();
    expect(ed.props("modelValue")).toBe(
      "# 养宠家庭空气净化器推荐哪款好？\n\n## 一、品牌分析\n正文…",
    );
  });

  it("点入口开模态 → 逐 pass 输出 + 「重跑此 pass」都在里面", async () => {
    const w = await mountArticle((a) => {
      a.passes = [
        mkPass({ index: 0, skill_name: "家电人设", output: "第一段输出文本" }),
        mkPass({ index: 1, role: "humanize", skill_id: "h", skill_name: "去AI味技", output: "第二段更自然" }),
      ];
      a.finalText = "成稿正文";
    });
    await switchTab(w, "final");
    await w.find("[data-passes-open]").trigger("click");

    expect(w.findAll("[data-pass-card]").length).toBe(2);
    const txt = w.text();
    expect(txt).toContain("家电人设");
    expect(txt).toContain("去AI味技");
    expect(txt).toContain("第一段输出文本");
    expect(txt).toContain("第二段更自然");

    const a = useArticle();
    const spy = vi.spyOn(a, "rerunPass").mockResolvedValue(undefined);
    const btns = w.findAll("[data-rerun-pass]");
    expect(btns.length).toBe(2);
    await btns[1].trigger("click");
    expect(spy).toHaveBeenCalledWith(1);
  });

  it("起新一轮清空 passes → 模态自动关闭，不留空壳", async () => {
    const w = await mountArticle((a) => {
      a.passes = [mkPass({ index: 0 })];
      a.finalText = "成稿正文";
    });
    await switchTab(w, "final");
    await w.find("[data-passes-open]").trigger("click");
    expect(w.findAll("[data-pass-card]").length).toBe(1);

    // finalize() / submit() 都会 passes = []
    useArticle().passes = [];
    await flushPromises();
    expect(w.findAll("[data-pass-card]").length).toBe(0);
    expect(w.find("[data-passes-open]").exists()).toBe(false);
  });

  it("重跑在飞时入口按钮变「重跑中…」—— 关掉模态也看得见", async () => {
    // Spinner + 「取消」只活在模态里，而 rerunPass 不动 article.status（右栏
    // 进度卡 / 全局取消都不亮）。入口不露出重跑态的话，关掉模态界面看着完全
    // 空闲，用户接着编辑成稿，重跑 done 一来 finalText 被整段覆盖。
    const w = await mountArticle((a) => {
      a.passes = [mkPass({ index: 0 }), mkPass({ index: 1 })];
      a.finalText = "成稿正文";
    });
    await switchTab(w, "final");
    expect(w.find("[data-passes-open]").text()).toContain("润色过程 2 轮");

    useArticle().rerunningIndex = 1;
    await flushPromises();
    expect(w.find("[data-passes-open]").text()).toContain("第 2 轮重跑中…");
  });

  it("无 passes（单 skill 旧路径）→ 无入口按钮，编辑器照常（零回归）", async () => {
    const w = await mountArticle((a) => { a.finalText = "普通成稿"; });
    await switchTab(w, "final");
    expect(w.find("[data-passes-open]").exists()).toBe(false);
    expect(w.findAll("[data-pass-card]").length).toBe(0);
    expect(w.findComponent({ name: "TiptapEditor" }).exists()).toBe(true);
    expect(paneShape(w, "final").childCount).toBe(2);
  });
});

describe("ArticleView — 导出标题的真相源", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    postMock.mockReset();
    postMock.mockResolvedValue({ data: { job_id: "j1" } });
    getMock.mockReset();
    getMock.mockImplementation((url: string) => {
      if (url === "/api/templates") return Promise.resolve({ data: { templates: [{ id: "tpl-a", name: "模板A" }] } });
      if (url === "/api/skills") return Promise.resolve({ data: { skills: [] } });
      return Promise.resolve({ data: {} });
    });
    routeQuery = {};
  });

  it("正文内嵌的 H1 压过 article.title —— 文件名和文件内容不能是两个标题", async () => {
    // 后端就是这个口径：ensure_title 在正文已有 H1 时原样返回，返回的 title
    // 取自 extract_title(body)。前端不跟上的话，用户在编辑器里直接改首行标题
    // （成稿编辑器修好之后这条路第一次可达）后导出 txt，会得到文件名 = 旧
    // article.title、正文首行 = 新 H1 —— 一次导出两个标题。
    const w = await mountArticle((a) => {
      a.title = "起飞时的旧标题";
      a.finalText = "# 我在编辑器里手改的标题\n\n正文…";
    });
    expect((w.vm as any).safeFilenameStem()).toBe("我在编辑器里手改的标题");
  });

  it("正文没有 H1 时回退 article.title（今天行为）", async () => {
    const w = await mountArticle((a) => {
      a.title = "起飞时的标题";
      a.finalText = "## 一、品牌分析\n\n正文…";
    });
    expect((w.vm as any).safeFilenameStem()).toBe("起飞时的标题");
  });

  it("文件名剥掉 Windows 非法字符，全非法时兜底 article", async () => {
    const w = await mountArticle((a) => {
      a.title = "";
      a.finalText = '# a/b:c*d?e"f<g>h|i\n\n正文';
    });
    expect((w.vm as any).safeFilenameStem()).toBe("abcdefghi");
  });
});
