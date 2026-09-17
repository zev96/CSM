import { describe, it, expect } from "vitest";
import { mount } from "@vue/test-utils";
import StartJobModal from "../StartJobModal.vue";

// Dialog 内部用 <Teleport to="body">，@vue/test-utils 的 find 不会穿进
// teleport 目标 —— stub teleport 让内容就地渲染，方便断言滑条 / 文案。
const mountOpts = (props: Record<string, unknown>) => ({
  props: { open: true, loginStatus: { bilibili: true, douyin: true, kuaishou: true, xiaohongshu: false }, ...props },
  global: { stubs: { teleport: true } },
});

describe("StartJobModal — TikHub 模式采集上限钳制", () => {
  it("TikHub 模式：滑条 max 钳到 80，提示文案可见", () => {
    const w = mount(StartJobModal, mountOpts({ tikhubMode: true }));
    const input = w.find('input[type="range"]');
    expect(input.attributes("max")).toBe("80");
    expect(w.text()).toContain("TikHub 模式：单平台每次最多 80 条");
  });

  it("本地浏览器模式：滑条 max 仍为 200，不显示 TikHub 提示", () => {
    const w = mount(StartJobModal, mountOpts({ tikhubMode: false }));
    const input = w.find('input[type="range"]');
    expect(input.attributes("max")).toBe("200");
    expect(w.text()).not.toContain("TikHub 模式：单平台每次最多");
  });

  it("已经拖到 200 后切到 TikHub 模式，cap 自动回落到 80，估算数字同步更新", async () => {
    const w = mount(StartJobModal, mountOpts({ tikhubMode: false }));
    const input = w.find('input[type="range"]');
    await input.setValue("200");
    // 本地模式、三平台默认全选：200 × 3 = 600。
    expect(w.text()).toContain("预计抓取");
    expect(w.text()).toContain("600");

    await w.setProps({ tikhubMode: true });
    // watch(capMax) 把 cap 从 200 钳回 80。
    expect(w.find('input[type="range"]').attributes("max")).toBe("80");
    // 估算不能再撒谎：三平台 × 80 = 240，不能停留在旧的 600。
    expect(w.text()).toContain("240");
    expect(w.text()).not.toContain("600");
  });
});
