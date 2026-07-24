import { mount, flushPromises } from "@vue/test-utils";
import { describe, it, expect, vi, beforeEach } from "vitest";

const getMock = vi.fn();
const postMock = vi.fn();
vi.mock("@/stores/sidecar", () => ({
  useSidecar: () => ({ client: { get: getMock, post: postMock } }),
}));

import BlockEditor from "../BlockEditor.vue";

/** 竞品池卡片模式的块。sections 非空 = 卡片模式。 */
function poolCard(sections: any[]) {
  return {
    kind: "competitor_pool",
    id: "pool_1",
    source: { type: "notes_query", module: "模板一/竞品位", filter: { 推荐位: "竞品" } },
    sections,
    pick_notes: 2,
    tier_key: "层级标签",
    heading_template: "### {tier} TOP{n}. {title}",
  };
}

function mountEditor(block: Record<string, any>) {
  return mount(BlockEditor, {
    props: { modelValue: block, index: 0, total: 1, vaultDirs: [] },
    global: { stubs: { CascadePicker: true } },
  });
}

/** 按可见文字找按钮。 */
function btn(w: any, text: string) {
  return w.findAll("button").find((b: any) => b.text().includes(text));
}

function heroCard(sections: any[]) {
  return {
    kind: "hero_brand",
    id: "hero_1",
    title: "DARZ D9",
    source: { type: "notes_query", module: "模板二/DARZD9", filter: {} },
    sections,
    heading_template: "### {tier} TOP{n}. {title}",
  };
}

/** 真实形态：模板一竞品位 7 篇，5 节全覆盖但只有部分篇写了内容。 */
const DETECTED = {
  note_count: 7,
  sections: [
    { title: "市场口碑数据", note_count: 7, with_body: 7, order: 0 },
    { title: "品牌赛道定位", note_count: 7, with_body: 7, order: 1 },
    { title: "全场景适配范围", note_count: 7, with_body: 7, order: 2 },
    // 只有一半的卡写了这节 —— 设成必需会把另一半整张剔出名册
    { title: "分维度硬核测评", note_count: 4, with_body: 4, order: 3 },
  ],
};

async function detect(w: any, data: any = DETECTED) {
  postMock.mockResolvedValueOnce({ data });
  await btn(w, "从目录识别")!.trigger("click");
  await flushPromises();
}

describe("BlockEditor — 从目录识别小节", () => {
  beforeEach(() => {
    getMock.mockReset();
    postMock.mockReset();
    getMock.mockResolvedValue({ data: { attributes: [] } });
  });

  it("按当前目录 + 筛选查小节，而不是全库", async () => {
    const w = mountEditor(poolCard([{ label: "市场口碑数据", pick_variants: 1 }]));
    await flushPromises();
    await detect(w);

    expect(postMock).toHaveBeenCalledWith("/api/vault/card_sections", {
      module: "模板一/竞品位",
      filter: { 推荐位: "竞品" },
    });
  });

  it("「有此小节」与「有内容」分两栏显示 —— 空标题的卡进不了名册", async () => {
    const w = mountEditor(poolCard([{ label: "市场口碑数据", pick_variants: 1 }]));
    await flushPromises();
    postMock.mockResolvedValueOnce({
      data: {
        note_count: 57,
        sections: [{ title: "核心定位", note_count: 57, with_body: 7, order: 0 }],
      },
    });
    await btn(w, "从目录识别")!.trigger("click");
    await flushPromises();

    expect(w.text()).toContain("57/57 篇有此小节");
    expect(w.text()).toContain("7 篇有内容");
  });

  it("识别不落库 —— 先看再导，不静默吃掉用户配好的小节", async () => {
    const w = mountEditor(poolCard([{ label: "旧小节", pick_variants: 3 }]));
    await flushPromises();
    await detect(w);

    expect(w.emitted("update:modelValue")).toBeUndefined();
  });

  it("默认只勾全覆盖的：部分覆盖的节导进来会剔掉缺它的竞品", async () => {
    const w = mountEditor(poolCard([{ label: "市场口碑数据", pick_variants: 1 }]));
    await flushPromises();
    await detect(w);
    await btn(w, "按目录替换")!.trigger("click");
    await flushPromises();

    const last = w.emitted("update:modelValue")!.at(-1)![0] as any;
    expect(last.sections.map((s: any) => s.label)).toEqual([
      "市场口碑数据", "品牌赛道定位", "全场景适配范围",
    ]);
    // required 未定义 = schema 默认 True，全仓一律按 `!== false` 读
    expect(last.sections.every((s: any) => s.required !== false)).toBe(true);
  });

  it("替换按文档序落库，不是字母序", async () => {
    const w = mountEditor(poolCard([{ label: "市场口碑数据", pick_variants: 1 }]));
    await flushPromises();
    postMock.mockResolvedValueOnce({
      data: {
        note_count: 2,
        sections: [
          { title: "核心定位", note_count: 2, with_body: 2, order: 0 },
          { title: "净化性能", note_count: 2, with_body: 2, order: 1 },
          { title: "成本与维护", note_count: 2, with_body: 2, order: 2 },
        ],
      },
    });
    await btn(w, "从目录识别")!.trigger("click");
    await flushPromises();
    await btn(w, "按目录替换")!.trigger("click");
    await flushPromises();

    const last = w.emitted("update:modelValue")!.at(-1)![0] as any;
    expect(last.sections.map((s: any) => s.label)).toEqual([
      "核心定位", "净化性能", "成本与维护",
    ]);
  });

  it("替换保留已配过小节的 必需 / 候选数 —— 只重排结构不清参数", async () => {
    const w = mountEditor(poolCard([
      { label: "市场口碑数据", h2: "", required: false, pick_variants: 3 },
    ]));
    await flushPromises();
    await detect(w);
    await btn(w, "按目录替换")!.trigger("click");
    await flushPromises();

    const last = w.emitted("update:modelValue")!.at(-1)![0] as any;
    const kept = last.sections.find((s: any) => s.label === "市场口碑数据");
    expect(kept.pick_variants).toBe(3);
  });

  // ── 对抗性审查抓到的三条 CRITICAL/MAJOR ────────────────────────────
  it("「必需」按有正文的篇数判，不按有标题的篇数 —— 否则空骨架目录必然清空名册", async () => {
    // 竞品卡几乎都是从骨架复制的：H2 早齐了、正文才刚开始填。按结构判就会
    // 给每节都设 required=true，而 build_roster 的门槛是 section_body 非空
    // → 每张卡都被判缺料 → 名册为 0 → CardRosterError，整篇生成中止。
    const w = mountEditor(poolCard([{ label: "占位", pick_variants: 1 }]));
    await flushPromises();
    await detect(w, {
      note_count: 9,
      sections: [
        { title: "已填好的节", note_count: 9, with_body: 9, order: 0 },
        { title: "空骨架节", note_count: 9, with_body: 0, order: 1 },
      ],
    });
    await btn(w, "按目录替换")!.trigger("click");
    await flushPromises();

    const last = w.emitted("update:modelValue")!.at(-1)![0] as any;
    const byLabel = Object.fromEntries(last.sections.map((s: any) => [s.label, s]));
    expect(byLabel["已填好的节"].required).toBe(true);
    expect(byLabel["空骨架节"].required).toBe(false);
  });

  it("面板直接给出入册上界 —— 全空时红字说明一张都入不了", async () => {
    const w = mountEditor(poolCard([{ label: "占位", pick_variants: 1 }]));
    await flushPromises();
    await detect(w, {
      note_count: 9,
      sections: [{ title: "空骨架节", note_count: 9, with_body: 0, order: 0 }],
    });

    expect(w.text()).toContain("一张卡都入不了册");
  });

  it("上界取必需小节里 with_body 的最小值", async () => {
    const w = mountEditor(poolCard([{ label: "占位", pick_variants: 1 }]));
    await flushPromises();
    await detect(w, {
      note_count: 6,
      sections: [
        { title: "甲", note_count: 6, with_body: 6, order: 0 },
        { title: "乙", note_count: 6, with_body: 2, order: 1 },
      ],
    });

    // 乙 with_body<总数 → 不必需；必需只有甲 → 上界 6
    expect(w.text()).toContain("最多 6 张卡入册");
  });

  // ── 复审抓到的：面板数字与真正落库的必需集合脱节 ──────────────────
  it("上界要算上「认亲带走的老小节保留的必需」——卡片模式默认就播下一个", async () => {
    // 启用卡片模式会播 {label:"市场口碑数据", required:true}，而那正是规范
    // 里的约定 H2 名、必被认亲带走。按「勾选项」算上界就会显示 9，落库却是
    // 两个必需节、真实上界 3。
    const w = mountEditor(poolCard([
      { label: "市场口碑数据", h2: "", required: true, pick_variants: 1 },
    ]));
    await flushPromises();
    await detect(w, {
      note_count: 9,
      sections: [
        { title: "市场口碑数据", note_count: 9, with_body: 3, order: 0 },
        { title: "品牌赛道定位", note_count: 9, with_body: 9, order: 1 },
      ],
    });

    expect(w.text()).toContain("最多 3 张卡入册");
    expect(w.text()).not.toContain("最多 9 张卡入册");
  });

  it("append 的上界要算上目录里根本没有的必需老小节 —— 那是必然 0", async () => {
    const w = mountEditor(poolCard([
      { label: "目录里没有的老节", h2: "", required: true, pick_variants: 1 },
    ]));
    await flushPromises();
    await detect(w, {
      note_count: 8,
      sections: [{ title: "新节", note_count: 8, with_body: 8, order: 0 }],
    });

    // 替换会把老节挤掉 → 8；追加保留老节 → 名册必然 0
    expect(w.text()).toContain("最多 8 张卡入册");
    expect(w.text()).toContain("一张卡都入不了册");
  });

  it("落库结果与面板算的是同一份方案", async () => {
    const w = mountEditor(poolCard([
      { label: "市场口碑数据", h2: "", required: true, pick_variants: 4 },
    ]));
    await flushPromises();
    await detect(w, {
      note_count: 9,
      sections: [
        { title: "市场口碑数据", note_count: 9, with_body: 3, order: 0 },
        { title: "品牌赛道定位", note_count: 9, with_body: 9, order: 1 },
      ],
    });
    await btn(w, "按目录替换")!.trigger("click");
    await flushPromises();

    const last = w.emitted("update:modelValue")!.at(-1)![0] as any;
    // 老节的 required:true 与 pick_variants:4 都原样带走（不替用户下调）
    const kept = last.sections.find((s: any) => s.label === "市场口碑数据");
    expect(kept.required).toBe(true);
    expect(kept.pick_variants).toBe(4);
    // 但后果要说出来
    expect(w.text()).toContain("其余卡会被剔出名册");
  });

  it("识别完改了目录，面板必须失效 —— 否则导入的还是旧目录的小节", async () => {
    // 截断告警本身就在劝「目录选宽了，收窄一点」，照做回来直接点替换就中招。
    const w = mountEditor(poolCard([{ label: "占位", pick_variants: 1 }]));
    await flushPromises();
    await detect(w);
    expect(btn(w, "按目录替换")).toBeDefined();

    await w.setProps({
      modelValue: {
        ...poolCard([{ label: "占位", pick_variants: 1 }]),
        source: { type: "notes_query", module: "换了的目录", filter: { 推荐位: "竞品" } },
      },
    });
    await flushPromises();

    expect(btn(w, "按目录替换")).toBeUndefined();
  });

  it("改了筛选同样失效", async () => {
    const w = mountEditor(poolCard([{ label: "占位", pick_variants: 1 }]));
    await flushPromises();
    await detect(w);

    await w.setProps({
      modelValue: {
        ...poolCard([{ label: "占位", pick_variants: 1 }]),
        source: { type: "notes_query", module: "模板一/竞品位", filter: { 推荐位: "主推" } },
      },
    });
    await flushPromises();

    expect(btn(w, "按目录替换")).toBeUndefined();
  });

  it("全覆盖的子串标题不报假警 —— 精确匹配是第一档，各自命中自己", async () => {
    const w = mountEditor(poolCard([{ label: "占位", pick_variants: 1 }]));
    await flushPromises();
    await detect(w, {
      note_count: 6,
      sections: [
        { title: "核心参数", note_count: 6, with_body: 6, order: 0 },
        { title: "核心参数对比", note_count: 6, with_body: 6, order: 1 },
      ],
    });

    expect(w.text()).not.toContain("互为子串");
  });

  it("重名跳过要说清幸存的那条绑的是哪个 ##", async () => {
    const w = mountEditor(poolCard([
      { label: "甲", h2: "乙", required: true, pick_variants: 2 },
    ]));
    await flushPromises();
    await detect(w, {
      note_count: 3,
      sections: [
        { title: "乙", note_count: 3, with_body: 3, order: 0 },
        { title: "甲", note_count: 3, with_body: 3, order: 1 },
      ],
    });
    await btn(w, "按目录替换")!.trigger("click");
    await flushPromises();

    expect(w.text()).toContain("对应的是 ## 乙");
    expect(w.text()).toContain("先给其中一个改名");
  });

  it("接口不存在时给出可行动的原因，而不是干巴巴一句 Not Found", async () => {
    // 跑着的 sidecar 比界面旧时 FastAPI 回 404 + detail 恰好是 "Not Found"。
    const w = mountEditor(poolCard([{ label: "占位", pick_variants: 1 }]));
    await flushPromises();
    postMock.mockRejectedValueOnce({
      response: { status: 404, data: { detail: "Not Found" } },
    });
    await btn(w, "从目录识别")!.trigger("click");
    await flushPromises();

    expect(w.text()).toContain("正在运行的 sidecar 比界面旧");
  });

  it("真路由自己抛的 404 不被误伤", async () => {
    const w = mountEditor(poolCard([{ label: "占位", pick_variants: 1 }]));
    await flushPromises();
    postMock.mockRejectedValueOnce({
      response: { status: 404, data: { detail: "vault root not found: D:/x" } },
    });
    await btn(w, "从目录识别")!.trigger("click");
    await flushPromises();

    expect(w.text()).toContain("vault root not found");
    expect(w.text()).not.toContain("比界面旧");
  });

  it("切块后识别面板必须消失 —— 否则会把 A 目录的小节写进 B 块", async () => {
    const w = mountEditor(poolCard([{ label: "市场口碑数据", pick_variants: 1 }]));
    await flushPromises();
    await detect(w);
    expect(btn(w, "按目录替换")).toBeDefined();

    await w.setProps({
      modelValue: {
        ...poolCard([{ label: "B块自己的节", pick_variants: 9 }]),
        id: "pool_2",
        source: { type: "notes_query", module: "模板二/竞品位", filter: {} },
      },
    });
    await flushPromises();

    expect(btn(w, "按目录替换")).toBeUndefined();
    expect(w.text()).not.toContain("市场口碑数据");
  });

  it("切到主推卡（hero_brand）时面板不渲染 —— 竞品卡形状写进 hero 会被静默吞掉", async () => {
    // HeroSection 是 extra=ignore：h2/required/pick_variants 被丢弃，
    // module/filter 被重置成空，schema 照样放行、模板照样存下去。
    const w = mountEditor(poolCard([{ label: "市场口碑数据", pick_variants: 1 }]));
    await flushPromises();
    await detect(w);

    await w.setProps({
      modelValue: heroCard([{ label: "品牌实力", module: null, filter: { 模块: "品牌实力" } }]),
    });
    await flushPromises();

    expect(btn(w, "按目录替换")).toBeUndefined();
    expect(btn(w, "只补未配置的")).toBeUndefined();
  });

  it("迟到的响应不许落到已经切走的块上", async () => {
    const w = mountEditor(poolCard([{ label: "市场口碑数据", pick_variants: 1 }]));
    await flushPromises();
    let release: (v: any) => void;
    postMock.mockReturnValueOnce(new Promise((res) => { release = res; }));
    await btn(w, "从目录识别")!.trigger("click");

    await w.setProps({ modelValue: { ...poolCard([{ label: "B", pick_variants: 1 }]), id: "pool_2" } });
    release!({ data: DETECTED });
    await flushPromises();

    expect(btn(w, "按目录替换")).toBeUndefined();
  });

  it("认亲走引擎的宽松匹配 —— 简写小节名也认得出，不会重复追加", async () => {
    // 「口碑」在生成时绑得上 `## 市场口碑数据`（find_card_section 做包含匹配）。
    // 只做精确认亲就会再补一条，成稿里同一段正文印两遍。
    const w = mountEditor(poolCard([
      { label: "口碑", h2: "", required: false, pick_variants: 5 },
    ]));
    await flushPromises();
    await detect(w);
    await btn(w, "只补未配置的")!.trigger("click");
    await flushPromises();

    const last = w.emitted("update:modelValue")!.at(-1)![0] as any;
    const labels = last.sections.map((s: any) => s.label);
    expect(labels).toContain("口碑");
    expect(labels).not.toContain("市场口碑数据");   // 不再重复补一条
    expect(last.sections.find((s: any) => s.label === "口碑").pick_variants).toBe(5);
  });

  it("替换也用宽松认亲 —— 简写小节的候选数不会被清回默认", async () => {
    const w = mountEditor(poolCard([
      { label: "口碑", h2: "", required: true, pick_variants: 5 },
    ]));
    await flushPromises();
    await detect(w);
    await btn(w, "按目录替换")!.trigger("click");
    await flushPromises();

    const last = w.emitted("update:modelValue")!.at(-1)![0] as any;
    expect(last.sections.find((s: any) => s.label === "口碑").pick_variants).toBe(5);
  });

  it("不产出重名小节 —— schema 的唯一键是 label，认亲键是 topic", async () => {
    const w = mountEditor(poolCard([
      { label: "甲", h2: "乙", required: true, pick_variants: 2 },
    ]));
    await flushPromises();
    await detect(w, {
      note_count: 3,
      sections: [
        { title: "乙", note_count: 3, with_body: 3, order: 0 },
        { title: "甲", note_count: 3, with_body: 3, order: 1 },
      ],
    });
    await btn(w, "按目录替换")!.trigger("click");
    await flushPromises();

    const last = w.emitted("update:modelValue")!.at(-1)![0] as any;
    const labels = last.sections.map((s: any) => s.label);
    expect(new Set(labels).size).toBe(labels.length);
    expect(w.text()).toContain("没有导入");         // 跳过要说出来，不能静默
  });

  it("兜底必需挑正文最全的一节，且把这个动作说出来", async () => {
    const w = mountEditor(poolCard([{ label: "占位", pick_variants: 1 }]));
    await flushPromises();
    await detect(w, {
      note_count: 10,
      sections: [
        { title: "只有1篇有正文", note_count: 10, with_body: 1, order: 0 },
        { title: "有8篇有正文", note_count: 10, with_body: 8, order: 1 },
      ],
    });
    await btn(w, "按目录替换")!.trigger("click");
    await flushPromises();

    const last = w.emitted("update:modelValue")!.at(-1)![0] as any;
    const req = last.sections.filter((s: any) => s.required !== false);
    expect(req).toHaveLength(1);
    expect(req[0].label).toBe("有8篇有正文");       // 不是文档序第一个
    expect(w.text()).toContain("设为必需");
  });

  it("互为子串的标题要报出来 —— 引擎会把它们绑到同一段正文", async () => {
    const w = mountEditor(poolCard([{ label: "占位", pick_variants: 1 }]));
    await flushPromises();
    await detect(w, {
      note_count: 6,
      sections: [
        { title: "核心参数", note_count: 3, with_body: 3, order: 0 },
        { title: "核心参数对比", note_count: 3, with_body: 3, order: 1 },
      ],
    });

    expect(w.text()).toContain("互为子串");
  });

  it("截断要明示 —— 不然「按目录替换」会删掉没列出来的小节", async () => {
    const w = mountEditor(poolCard([{ label: "占位", pick_variants: 1 }]));
    await flushPromises();
    await detect(w, {
      note_count: 80,
      truncated: true,
      sections: [{ title: "甲", note_count: 80, with_body: 80, order: 0 }],
    });

    expect(w.text()).toContain("只列出了前 50 个");
  });

  it("报错分支也有「取消」——否则面板挂上就清不掉", async () => {
    const w = mountEditor(poolCard([{ label: "市场口碑数据", pick_variants: 1 }]));
    await flushPromises();
    postMock.mockRejectedValueOnce({ response: { data: { detail: "炸了" } } });
    await btn(w, "从目录识别")!.trigger("click");
    await flushPromises();
    expect(w.text()).toContain("炸了");

    await btn(w, "取消")!.trigger("click");
    await flushPromises();
    expect(w.text()).not.toContain("炸了");
  });

  it("超时不吐英文原文", async () => {
    const w = mountEditor(poolCard([{ label: "市场口碑数据", pick_variants: 1 }]));
    await flushPromises();
    postMock.mockRejectedValueOnce({
      code: "ECONNABORTED", message: "timeout of 60000ms exceeded",
    });
    await btn(w, "从目录识别")!.trigger("click");
    await flushPromises();

    expect(w.text()).toContain("扫描超时");
  });

  it("认亲按 h2 优先（与引擎 topic() 同口径），label 改过名也认得出", async () => {
    const w = mountEditor(poolCard([
      { label: "口碑", h2: "市场口碑数据", required: true, pick_variants: 5 },
    ]));
    await flushPromises();
    await detect(w);
    await btn(w, "按目录替换")!.trigger("click");
    await flushPromises();

    const last = w.emitted("update:modelValue")!.at(-1)![0] as any;
    const kept = last.sections.find((s: any) => s.h2 === "市场口碑数据");
    expect(kept.label).toBe("口碑");         // 用户改的名字不被覆盖
    expect(kept.pick_variants).toBe(5);
  });

  it("「只补未配置的」不动已有小节，也不重复添加", async () => {
    const w = mountEditor(poolCard([
      { label: "市场口碑数据", h2: "", required: true, pick_variants: 4 },
    ]));
    await flushPromises();
    await detect(w);
    await btn(w, "只补未配置的")!.trigger("click");
    await flushPromises();

    const last = w.emitted("update:modelValue")!.at(-1)![0] as any;
    expect(last.sections.map((s: any) => s.label)).toEqual([
      "市场口碑数据", "品牌赛道定位", "全场景适配范围",
    ]);
    expect(last.sections[0].pick_variants).toBe(4);
  });

  it("全是部分覆盖时兜底一个必需 —— schema 拒收「一个必需都没有」", async () => {
    const w = mountEditor(poolCard([{ label: "占位", pick_variants: 1 }]));
    await flushPromises();
    postMock.mockResolvedValueOnce({
      data: {
        note_count: 10,
        sections: [
          { title: "甲", note_count: 4, with_body: 4, order: 0 },
          { title: "乙", note_count: 3, with_body: 3, order: 1 },
        ],
      },
    });
    await btn(w, "从目录识别")!.trigger("click");
    await flushPromises();
    await btn(w, "按目录替换")!.trigger("click");
    await flushPromises();

    const last = w.emitted("update:modelValue")!.at(-1)![0] as any;
    expect(last.sections.filter((s: any) => s.required !== false)).toHaveLength(1);
  });

  it("目录/筛选没匹配到笔记时报归因，而不是说「笔记里没有 ## 小节」", async () => {
    // 这两种空是两码事：后者会把人引去改素材，而素材根本没毛病。
    const w = mountEditor(poolCard([{ label: "市场口碑数据", pick_variants: 1 }]));
    await flushPromises();
    await detect(w, {
      note_count: 0,
      sections: [],
      hint: "该目录下有 57 篇素材，但没有一篇写了「推荐位」这个字段。",
    });

    expect(w.text()).toContain("没有一篇写了「推荐位」这个字段");
    expect(w.text()).not.toContain("没有任何 ## 小节");
  });

  it("一个 ## 都没有时给出可操作的解释，而不是一张空表", async () => {
    const w = mountEditor(poolCard([{ label: "市场口碑数据", pick_variants: 1 }]));
    await flushPromises();
    await detect(w, { note_count: 12, sections: [] });

    expect(w.text()).toContain("没有任何 ## 小节");
  });

  it("接口报错原样显示，不吞成静默失败", async () => {
    const w = mountEditor(poolCard([{ label: "市场口碑数据", pick_variants: 1 }]));
    await flushPromises();
    postMock.mockRejectedValueOnce({
      response: { data: { detail: "请先给竞品池选目录" } },
    });
    await btn(w, "从目录识别")!.trigger("click");
    await flushPromises();

    expect(w.text()).toContain("请先给竞品池选目录");
  });
});

describe("BlockEditor — 卡片模式隐藏不生效的开关", () => {
  beforeEach(() => {
    getMock.mockReset();
    postMock.mockReset();
    getMock.mockResolvedValue({ data: { attributes: [] } });
  });

  it("卡片模式不显示「子素材随机数量 / 不重复素材」——引擎根本不读", async () => {
    // sample_competitor_cards 只看 pick_notes 与每节 pick_variants；
    // sample_roster 恒不重复抽竞品，明确不看 unique_notes 开关。
    const w = mountEditor(poolCard([{ label: "市场口碑数据", pick_variants: 1 }]));
    await flushPromises();

    expect(w.text()).not.toContain("子素材随机数量");
    expect(w.text()).not.toContain("不重复素材");
  });

  it("非卡片模式照旧显示 —— legacy 对比池那两个开关是真生效的", async () => {
    const w = mountEditor({ ...poolCard([]), sections: [] });
    await flushPromises();

    expect(w.text()).toContain("子素材随机数量");
    expect(w.text()).toContain("不重复素材");
  });
});
