// frontend/src/stores/__tests__/taskTray.spec.ts
import { describe, it, expect, vi, beforeEach } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { flushPromises } from "@vue/test-utils";
import { nextTick } from "vue";

const getMock = vi.fn();
const postMock = vi.fn();
vi.mock("@/stores/sidecar", () => ({
  useSidecar: () => ({ client: { get: getMock, post: postMock }, sseURL: (p: string) => p }),
}));
vi.mock("@/composables/useSidecarReady", () => ({
  useSidecarReady: () => ({ whenReady: () => Promise.resolve() }),
}));
vi.mock("@/composables/useSystemNotify", () => ({
  useSystemNotify: () => ({ notify: vi.fn().mockResolvedValue(undefined) }),
}));
vi.mock("@/api/client", () => ({ subscribe: vi.fn(() => () => {}) }));

import { useTaskTray } from "@/stores/taskTray";
import { useMonitorStatus } from "@/stores/monitorStatus";
import { useBatch } from "@/stores/batch";
import { useArticle } from "@/stores/article";

beforeEach(() => {
  setActivePinia(createPinia());
  localStorage.clear();
  getMock.mockReset().mockResolvedValue({
    data: {
      tasks: [
        { id: 11, name: "扫地机器人怎么选", type: "zhihu_question" },
        { id: 12, name: "吸尘器推荐", type: "zhihu_question" },
        { id: 31, name: "宠物吸尘器", type: "baidu_keyword" },
      ],
    },
  });
  postMock.mockReset().mockResolvedValue({ data: { cancelled: true } });
});

describe("taskTray — 监测聚合", () => {
  it("running 任务按显示组聚合成卡，count=底层任务数", async () => {
    const monitor = useMonitorStatus();
    const tray = useTaskTray();
    monitor.markRunning(11);
    monitor.markRunning(12);
    monitor.markRunning(31);
    await flushPromises(); // 元数据懒加载落地
    await nextTick();

    expect(tray.runningTasks.length).toBe(2);
    const zhihu = tray.runningTasks.find((t) => t.title.includes("知乎问题监测"))!;
    expect(zhihu.title).toBe("知乎问题监测 · 2 个任务");
    expect(zhihu.subtitle).toContain("扫地机器人怎么选");
    expect(zhihu.count).toBe(2);
    expect(zhihu.memberIds).toEqual([11, 12]);
    expect(tray.runningCount).toBe(3);
  });

  it("组内进度 Σcurrent/Σtotal；全组无进度 → null（不确定态）", async () => {
    const monitor = useMonitorStatus();
    const tray = useTaskTray();
    monitor.markRunning(11);
    monitor.markRunning(12);
    monitor.markRunning(31);
    await flushPromises();
    monitor.setProgress(11, 3, 10);
    monitor.setProgress(12, 1, 10);
    await nextTick();

    const zhihu = tray.runningTasks.find((t) => t.title.includes("知乎问题监测"))!;
    expect(zhihu.progress).toBeCloseTo(0.2);
    const baidu = tray.runningTasks.find((t) => t.title.includes("百度排名监测"))!;
    expect(baidu.progress).toBeNull();
  });

  it("waiting_chrome phase → state=waiting + 排队文案；captcha 优先级更高", async () => {
    const monitor = useMonitorStatus();
    const tray = useTaskTray();
    monitor.markRunning(31);
    await flushPromises();
    monitor._dispatchSse("waiting_chrome_close", { task_id: 31 });
    await nextTick();
    let baidu = tray.runningTasks.find((t) => t.title.includes("百度排名监测"))!;
    expect(baidu.state).toBe("waiting");
    expect(baidu.subtitle).toContain("等待浏览器空闲");

    monitor._dispatchSse("needs_captcha", { task_id: 31, keyword: "kw" });
    await nextTick();
    baidu = tray.runningTasks.find((t) => t.title.includes("百度排名监测"))!;
    expect(baidu.state).toBe("captcha");
  });

  it("元数据缓存未命中 → 标题退化为「监测任务」、子标题「任务 #id」", async () => {
    getMock.mockResolvedValue({ data: { tasks: [] } });
    const monitor = useMonitorStatus();
    const tray = useTaskTray();
    monitor.markRunning(99);
    await flushPromises();
    await nextTick();
    expect(tray.runningTasks[0].title).toBe("监测任务");
    expect(tray.runningTasks[0].subtitle).toContain("任务 #99");
  });
});

describe("taskTray — 幽灵完成条目回归", () => {
  it("batch 提交中间态（running 但 jobId 未返回）不产生卡片与最近完成", async () => {
    const batch = useBatch();
    const tray = useTaskTray();
    batch.$patch({ status: "running", jobId: null, total: 0 });
    await nextTick();
    expect(tray.runningTasks.find((t) => t.kind === "batch")).toBeUndefined();
    batch.$patch({ jobId: "u1", total: 5 });
    await nextTick();
    expect(tray.runningTasks.find((t) => t.kind === "batch")).toBeTruthy();
    expect(tray.recentFinished.length).toBe(0);
  });

  it("article 提交中间态同样不产生幽灵条目", async () => {
    const article = useArticle();
    const tray = useTaskTray();
    article.$patch({ status: "running", jobId: null, title: "kw" });
    await nextTick();
    expect(tray.runningTasks.find((t) => t.kind === "article")).toBeUndefined();
    article.$patch({ jobId: "g1", currentStage: "扫描资料库", stageIndex: 0 });
    await nextTick();
    expect(tray.runningTasks.find((t) => t.kind === "article")).toBeTruthy();
    expect(tray.recentFinished.length).toBe(0);
  });
});
