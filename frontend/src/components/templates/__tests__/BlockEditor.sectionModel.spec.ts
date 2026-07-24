import { mount, flushPromises } from "@vue/test-utils";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { defineComponent, h, ref } from "vue";

const getMock = vi.fn();
const postMock = vi.fn();
vi.mock("@/stores/sidecar", () => ({
  useSidecar: () => ({ client: { get: getMock, post: postMock } }),
}));

import BlockEditor from "../BlockEditor.vue";
import FormSelect from "@/components/forms/FormSelect.vue";
import FormInput from "@/components/forms/FormInput.vue";

/**
 * 这些用例都走「真实 v-model 回灌」—— 父组件把 emit 出来的 modelValue 重新
 * 喂回 props。BlockEditor 实例在编辑器里就是这么用的，而这条路径会把之前
 * 两个 watch 的数组字面量 getter 问题暴露出来：数组每次都是新引用，Vue 用
 * Object.is 判定恒为「变了」，于是改任何无关字段都会重跑回调（重复拉属性 +
 * 把「自定义属性」手填态重置掉）。普通 mount 不回灌 props，测不出来。
 */
const ATTRS = [
  { key: "素材类型", note_count: 8, value_count: 1, sample_values: ["产品推荐格式"] },
  {
    key: "模块", note_count: 8, value_count: 3,
    sample_values: ["品牌实力", "核心参数", "核心技术"],
  },
];

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

function mountWithVModel(initial: Record<string, any>) {
  const state = ref<any>(initial);
  const Host = defineComponent({
    setup() {
      return () =>
        h(BlockEditor, {
          modelValue: state.value,
          index: 0,
          total: 1,
          vaultDirs: [],
          "onUpdate:modelValue": (v: any) => { state.value = v; },
        });
    },
  });
  const w = mount(Host, { global: { stubs: { CascadePicker: true } } });
  return { w, state };
}

function sectionKeySelect(w: any) {
  return w
    .findAllComponents(FormSelect)
    .find((c: any) => (c.props("placeholder") ?? "").includes("筛选字段"));
}
function sectionKeyInput(w: any) {
  return w
    .findAllComponents(FormInput)
    .find((c: any) => (c.props("placeholder") ?? "") === "属性名");
}
function sectionValueSelect(w: any) {
  return w
    .findAllComponents(FormSelect)
    .find((c: any) => (c.props("placeholder") ?? "").includes("筛选值"));
}

describe("BlockEditor — 主推卡小节筛选的模型保真（v-model 回灌）", () => {
  beforeEach(() => {
    getMock.mockReset();
    postMock.mockReset();
    getMock.mockResolvedValue({ data: { attributes: ATTRS } });
  });

  it("R1：选「自定义属性…」后手填框在无关编辑后仍在", async () => {
    const { w, state } = mountWithVModel(heroCard([{ label: "品牌实力", filter: {} }]));
    await flushPromises();
    sectionKeySelect(w)!.vm.$emit("update:modelValue", "__custom__");
    await flushPromises();
    expect(sectionKeyInput(w), "切到手填后输入框应出现").toBeTruthy();

    // 改一个跟筛选毫无关系的字段：手填框不能因此被重置掉
    state.value = { ...state.value, title: "DARZ D9 Pro" };
    await flushPromises();
    expect(sectionKeyInput(w), "无关编辑后手填框应仍在").toBeTruthy();
  });

  it("R2：改无关字段不会重复拉属性", async () => {
    // 小节目录与块目录不同 → mount 时块级 + 小节级各拉一次 = 2
    const { state } = mountWithVModel(
      heroCard([{ label: "A", module: "别的目录", filter: {} }]),
    );
    await flushPromises();
    const afterMount = getMock.mock.calls.length;

    state.value = { ...state.value, title: "改个标题" };
    await flushPromises();
    expect(getMock.mock.calls.length).toBe(afterMount);
  });

  it("R3：已配置但不在样本里的值仍显示，不被藏成占位符", async () => {
    // 素材改了名 / 之前手填过 —— 值不在当前 vault 取值集合里
    const { w } = mountWithVModel(
      heroCard([{ label: "A", filter: { 模块: "已经改名的旧值" } }]),
    );
    await flushPromises();
    const vs = sectionValueSelect(w);
    expect(vs, "值应仍走下拉而不是空占位").toBeTruthy();
    const opts = vs!.props("options").map((o: any) => o.value);
    expect(opts).toContain("已经改名的旧值");
  });

  it("R4：小节目录 409 不毒化 —— 仍有 __custom__ 出口，恢复后能正常拉到", async () => {
    getMock.mockImplementation((_url: string, cfg: any) => {
      if (cfg?.params?.module === "小节目录") {
        return Promise.reject({ response: { status: 409 } });
      }
      return Promise.resolve({ data: { attributes: ATTRS } });
    });
    const { w, state } = mountWithVModel(
      heroCard([{ label: "A", module: "小节目录", filter: {} }]),
    );
    await flushPromises();
    // 409 之后：属性下拉是空的，但「自定义属性…」手填出口一定在，用户不被卡
    const optsAfter409 = sectionKeySelect(w)!.props("options").map((o: any) => o.value);
    expect(optsAfter409).toContain("__custom__");

    // 关键：没被缓存成永久空数组。旧代码把 409 结果缓存成 []（truthy），
    // `if (sectionAttrs[mod]) continue` 于是永远跳过「小节目录」——哪怕素材
    // 库修好了、模块名没变，也再也拉不到。切走再切回同一个目录来验：
    getMock.mockResolvedValue({ data: { attributes: ATTRS } });
    state.value = {
      ...state.value,
      sections: [{ ...state.value.sections[0], module: "临时别的目录" }],
    };
    await flushPromises();
    state.value = {
      ...state.value,
      sections: [{ ...state.value.sections[0], module: "小节目录" }],
    };
    await flushPromises();
    const recovered = sectionKeySelect(w)!.props("options").map((o: any) => o.value);
    expect(recovered).toContain("模块");
  });

  it("R5：关闭再开卡片模式后，没选过自定义的小节不会被卡在手填框", async () => {
    // Fix A 把 sectionCustomKeys 的重置从「每次 sections 变」收窄到「换块」，
    // 但开关卡片模式是结构性重建 sections 且 block.id 不变 —— 残留的旧下标
    // 会把一个从没选过自定义的小节错误地渲染成手填输入框，且很难退出。
    const { w } = mountWithVModel(heroCard([{ label: "A", filter: {} }]));
    await flushPromises();

    // 把当前唯一小节切成手填 → sectionCustomKeys=[0]
    sectionKeySelect(w)!.vm.$emit("update:modelValue", "__custom__");
    await flushPromises();
    expect(sectionKeyInput(w)).toBeTruthy();

    const btn = (label: string) =>
      w.findAll("button").find((b: any) => b.text().includes(label));
    await btn("关闭卡片模式")!.trigger("click");   // sections → []
    await flushPromises();
    await btn("启用卡片模式")!.trigger("click");   // sections → [1 节]
    await flushPromises();

    // 新的小节没人给它选过自定义，必须是下拉，不能是手填输入框
    expect(sectionKeyInput(w), "重开后不该残留手填态").toBeFalsy();
    expect(sectionKeySelect(w), "应回到字段下拉").toBeTruthy();
  });
});
