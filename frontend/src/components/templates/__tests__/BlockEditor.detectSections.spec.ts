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

  it("切到主推卡（hero_brand）时旧结果必须清掉 —— 竞品卡形状写进 hero 会被静默吞掉", async () => {
    // 主推卡现在也有自己的识别（走 /note_sections），但**这一次的竞品结果**
    // 不能留在面板上：HeroSection 是 extra=ignore，h2/required/pick_variants
    // 会被丢弃、module/filter 重置成空，schema 照样放行、模板照样存下去。
    // 失效靠 detectScopeKey 里的 kind。
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


/**
 * 主推卡的识别是**另一套**：一个小节 = 一整篇笔记，靠 frontmatter 字段区分
 * （`模块: 参考价格`），正文里根本没有 H2。缺了它的代价就是这次要修的病：
 * 小节名手敲、筛选值另配，对不上时第一节空池报错，而没配筛选的小节会静默
 * 命中整个目录随机抽。
 */
const HERO_DETECTED = {
  field: "模块",
  field_candidates: ["模块", "模块序号"],
  note_count: 4,
  values: [
    { value: "标题行", note_count: 1, with_body: 1, order: 0 },
    { value: "参考价格", note_count: 1, with_body: 1, order: 1 },
    { value: "除醛技术", note_count: 1, with_body: 1, order: 2 },
    { value: "外观颜值", note_count: 1, with_body: 0, order: 3 },
  ],
};

async function detectHero(w: any, data: any = HERO_DETECTED) {
  postMock.mockResolvedValueOnce({ data });
  await btn(w, "从目录识别")!.trigger("click");
  await flushPromises();
}

function lastSections(w: any): any[] {
  const ev = w.emitted("update:modelValue")!;
  return ev[ev.length - 1][0].sections;
}

describe("BlockEditor — 主推卡从目录识别", () => {
  beforeEach(() => {
    getMock.mockReset();
    postMock.mockReset();
    getMock.mockResolvedValue({ data: { attributes: [] } });
  });

  it("走 /note_sections，并把当前小节用的筛选字段回传", async () => {
    // 不回传的话后端自己推断，`模块` 和 `模块序号` 都能一篇一值，
    // 换个字段用户就看不懂了。
    const w = mountEditor(heroCard([
      { label: "品牌实力", module: null, filter: { 模块: "品牌实力" } },
    ]));
    await flushPromises();
    await detectHero(w);

    expect(postMock).toHaveBeenCalledWith("/api/vault/note_sections", {
      module: "模板二/DARZD9",
      filter: {},
      field: "模块",
    });
  });

  it("没配过筛选时 field 传 null，由后端推断", async () => {
    const w = mountEditor(heroCard([{ label: "空节", module: null, filter: {} }]));
    await flushPromises();
    await detectHero(w);

    expect(postMock).toHaveBeenCalledWith(
      "/api/vault/note_sections",
      expect.objectContaining({ field: null }),
    );
  });

  it("落库写成 filter={字段: 取值}，顺序按识别结果", async () => {
    const w = mountEditor(heroCard([{ label: "空节", module: null, filter: {} }]));
    await flushPromises();
    await detectHero(w);
    await btn(w, "按目录替换")!.trigger("click");

    const secs = lastSections(w);
    expect(secs.map((s: any) => s.label)).toEqual(["标题行", "参考价格", "除醛技术"]);
    expect(secs[1]).toMatchObject({
      label: "参考价格", module: null, filter: { 模块: "参考价格" },
      pick_notes: 1, pick_variants_per_note: 1,
    });
  });

  it("认亲后**改写** filter —— 从别的模板复制来的旧筛选值必须被纠正", async () => {
    // 这就是模板四的真实坏法：label 是「参考价格」，filter 却还是从模板二
    // 复制来的 {模块: 品牌实力}，而模板四目录里压根没有「品牌实力」。
    // 认亲时原样带走 filter 等于把病一起带走，识别按钮点了也白点。
    const w = mountEditor(heroCard([
      { label: "参考价格", module: null, filter: { 模块: "品牌实力" }, pick_notes: 2 },
    ]));
    await flushPromises();
    await detectHero(w);
    await btn(w, "按目录替换")!.trigger("click");

    const hit = lastSections(w).find((s: any) => s.label === "参考价格");
    expect(hit.filter).toEqual({ 模块: "参考价格" });
    // 用户调过的候选数是他的显式选择，替换的是「有哪些节」不是推倒重来
    expect(hit.pick_notes).toBe(2);
  });

  it("默认不勾没正文的取值 —— 抽出来是空段", async () => {
    const w = mountEditor(heroCard([{ label: "空节", module: null, filter: {} }]));
    await flushPromises();
    await detectHero(w);
    await btn(w, "按目录替换")!.trigger("click");

    expect(lastSections(w).map((s: any) => s.label)).not.toContain("外观颜值");
  });

  it("取消勾选后不导入（`标题行` 这类不该当正文小节的靠用户取消）", async () => {
    const w = mountEditor(heroCard([{ label: "空节", module: null, filter: {} }]));
    await flushPromises();
    await detectHero(w);
    const boxes = w.findAll("input[type=checkbox]");
    const labels = w.findAll("label");
    const i = labels.findIndex((l: any) => l.text().includes("标题行"));
    await labels[i].find("input").setValue(false);
    await btn(w, "按目录替换")!.trigger("click");

    expect(lastSections(w).map((s: any) => s.label)).toEqual(["参考价格", "除醛技术"]);
    expect(boxes.length).toBeGreaterThan(0);
  });

  it("追加模式：对不上任何取值的老小节要明说会报空池", async () => {
    const w = mountEditor(heroCard([
      { label: "品牌实力", module: null, filter: { 模块: "品牌实力" } },
    ]));
    await flushPromises();
    await detectHero(w);
    await btn(w, "只补未配置的")!.trigger("click");
    await flushPromises();

    expect(w.text()).toContain("这个目录里没有这个取值");
    // 老小节留在原位，新取值追加在后面
    expect(lastSections(w).map((s: any) => s.label))
      .toEqual(["品牌实力", "标题行", "参考价格", "除醛技术"]);
  });

  it("不显示竞品池那套「N/M 篇有此小节」—— 主推卡一个取值就一篇", async () => {
    const w = mountEditor(heroCard([{ label: "空节", module: null, filter: {} }]));
    await flushPromises();
    await detectHero(w);

    expect(w.text()).not.toContain("篇有此小节");
    expect(w.text()).toContain("按「模块」拆成小节");
    expect(w.text()).toContain("3 节");          // 勾了 3 个（外观颜值没正文）
    expect(w.text()).not.toContain("张卡入册");
  });

  it("没有任何字段能分开笔记时说清是分组字段的问题，不说「没写 ## 小节」", async () => {
    const w = mountEditor(heroCard([{ label: "空节", module: null, filter: {} }]));
    await flushPromises();
    await detectHero(w, { field: "", field_candidates: [], note_count: 3, values: [] });

    expect(w.text()).toContain("没有哪个 frontmatter 字段能把它们分开");
    expect(w.text()).not.toContain("## 小节");
  });

  it("目录没选时按钮禁用，提示说的是主推卡不是竞品池", async () => {
    const w = mountEditor({
      ...heroCard([{ label: "空节", module: null, filter: {} }]),
      source: { type: "notes_query", module: "", filter: {} },
    });
    await flushPromises();
    const b = btn(w, "从目录识别")!;
    expect(b.attributes("disabled")).toBeDefined();
    expect(b.attributes("title")).toContain("主推卡");
  });
});


describe("BlockEditor — 主推卡识别的四个陷阱（对抗性审查发现）", () => {
  beforeEach(() => {
    getMock.mockReset();
    postMock.mockReset();
    getMock.mockResolvedValue({ data: { attributes: [] } });
  });

  it("认亲先按小节名、后按筛选值 —— 反了会把标签和内容绑错并丢掉一整节", async () => {
    // 反着来的失败形态：{label:"选购建议", filter:{模块:"参考价格"}} 被取值
    // 「参考价格」先按 filter 认走并固化，真正的「选购建议」再生成一条同名
    // 小节、被去重丢掉 —— 成稿里「选购建议」印的是参考价格的正文。
    const w = mountEditor(heroCard([
      { label: "选购建议", module: null, filter: { 模块: "参考价格" } },
      { label: "除醛技术", module: null, filter: {} },
    ]));
    await flushPromises();
    await detectHero(w, {
      field: "模块", field_candidates: ["模块"], note_count: 4,
      values: [
        { value: "标题行", note_count: 1, with_body: 1, order: 0 },
        { value: "参考价格", note_count: 1, with_body: 1, order: 1 },
        { value: "除醛技术", note_count: 1, with_body: 1, order: 2 },
        { value: "选购建议", note_count: 1, with_body: 1, order: 3 },
      ],
    });
    // 现有小节都对得上 → 默认只勾它们；把另外两个也勾上，测最狠的情况
    for (const t of ["标题行", "参考价格"]) {
      const l = w.findAll("label").find((x: any) => x.text().includes(t));
      if (l && !l.find("input").element.checked) await l.find("input").setValue(true);
    }
    await btn(w, "按目录替换")!.trigger("click");

    const secs = lastSections(w);
    const byLabel = Object.fromEntries(secs.map((x: any) => [x.label, x.filter]));
    expect(byLabel["选购建议"]).toEqual({ 模块: "选购建议" });
    expect(byLabel["参考价格"]).toEqual({ 模块: "参考价格" });
    expect(secs.length).toBe(4);
  });

  it("认亲时目录也归零 —— 老小节自带的目录会让引擎去 B 目录查 A 目录的取值", async () => {
    const w = mountEditor(heroCard([
      { label: "参考价格", module: "另一个目录/别的产品", filter: {} },
    ]));
    await flushPromises();
    await detectHero(w);
    await btn(w, "按目录替换")!.trigger("click");
    await flushPromises();

    const hit = lastSections(w).find((x: any) => x.label === "参考价格");
    expect(hit.module).toBeNull();
    expect(w.text()).toContain("原来单独指定了目录");
  });

  it("filter 是合并不是整体替换 —— 别把用户额外加的约束无声抹掉", async () => {
    const w = mountEditor(heroCard([
      { label: "参考价格", module: null, filter: { 模块: "品牌实力", 推荐位: "主推" } },
    ]));
    await flushPromises();
    await detectHero(w);
    await btn(w, "按目录替换")!.trigger("click");

    const hit = lastSections(w).find((x: any) => x.label === "参考价格");
    expect(hit.filter).toEqual({ 模块: "参考价格", 推荐位: "主推" });
  });

  it("不按 label 去重 —— 空小节名是主推卡文档支持的写法（续段），删了是丢数据", async () => {
    // schema 的 label 唯一性校验只加在 competitor_pool 上；HeroSection 的
    // label 留空 = 只输出正文不输出小节标题。照搬竞品那套会把所有续段合并。
    const w = mountEditor(heroCard([
      { label: "分维度硬核测评", module: null, filter: { 模块: "除醛" } },
      { label: "", module: null, filter: { 模块: "消毒" } },
      { label: "", module: null, filter: { 模块: "过敏原" } },
      { label: "", module: null, filter: { 模块: "体验" } },
    ]));
    await flushPromises();
    await detectHero(w);
    await btn(w, "只补未配置的")!.trigger("click");

    const secs = lastSections(w);
    expect(secs.filter((x: any) => x.label === "").length).toBe(3);
    expect(secs.length).toBeGreaterThanOrEqual(4);
  });

  it("在已配好的块上识别，默认只勾对得上的 —— 不能用修复按钮把能跑的版本改坏", async () => {
    // 用户 5 个目录里每个都躺着一篇 `模块: 标题行`（有正文）。默认全勾的话，
    // 在本来正常的版本上点一下就会多出 `**标题行** ：… TOP1. DARZ D9`。
    const w = mountEditor(heroCard([
      { label: "参考价格", module: null, filter: { 模块: "参考价格" } },
      { label: "除醛技术", module: null, filter: { 模块: "除醛技术" } },
    ]));
    await flushPromises();
    await detectHero(w);
    // 面板在点「按目录替换」后就收起来了，提示要在收起之前断言
    expect(w.text()).toContain("个取值没勾");
    await btn(w, "按目录替换")!.trigger("click");

    expect(lastSections(w).map((x: any) => x.label)).toEqual(["参考价格", "除醛技术"]);
  });

  it("没配过的块（刚开卡片模式）仍然默认全勾有正文的，不然点了等于没点", async () => {
    const w = mountEditor(heroCard([{ label: "市场口碑数据", module: null, filter: {} }]));
    await flushPromises();
    await detectHero(w);
    await btn(w, "按目录替换")!.trigger("click");

    expect(lastSections(w).map((x: any) => x.label))
      .toEqual(["标题行", "参考价格", "除醛技术"]);
  });

  it("后端换掉了分不开笔记的字段时要说清楚", async () => {
    const w = mountEditor(heroCard([{ label: "x", module: null, filter: { 素材类型: "产品推荐格式" } }]));
    await flushPromises();
    await detectHero(w, { ...HERO_DETECTED, field_rejected: "素材类型" });

    expect(w.text()).toContain("素材类型");
    expect(w.text()).toContain("已改用");
  });

  it("字段拆不出小节时列出这个目录能用的字段，不说「没有字段能分开」", async () => {
    const w = mountEditor(heroCard([{ label: "x", module: null, filter: {} }]));
    await flushPromises();
    await detectHero(w, {
      field: "核心关键词", field_candidates: ["模块", "模块序号"],
      note_count: 11, values: [],
    });

    expect(w.text()).toContain("模块");
    expect(w.text()).not.toContain("没有哪个 frontmatter 字段能把它们分开");
  });

  it("同 id 不同 kind 切换也要清掉旧结果（detectScopeKey 里的 kind 真被用上）", async () => {
    // 原来那条用例是 pool_1 → hero_1，id 本身就变了，把 kind 从 key 里删掉
    // 照样绿 —— 守不住回归。这里把 id 钉死，只换 kind。
    const w = mountEditor({ ...poolCard([{ label: "市场口碑数据", pick_variants: 1 }]), id: "same" });
    await flushPromises();
    await detect(w);
    expect(btn(w, "按目录替换")).toBeDefined();

    await w.setProps({
      modelValue: { ...heroCard([{ label: "品牌实力", module: null, filter: {} }]), id: "same" },
    });
    await flushPromises();

    expect(btn(w, "按目录替换")).toBeUndefined();
  });
});
