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
import { useMiningStore } from "@/stores/mining";
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

describe("taskTray — 引流/批量/单篇卡片", () => {
  it("mining activeJob → 卡片：平台分项 subtitle + Σgot/Σtarget", async () => {
    const mining = useMiningStore();
    const tray = useTaskTray();
    mining.activeJob = {
      id: 3,
      keyword: "宠物吸尘器",
      platforms: ["kuaishou", "douyin"],
      target_per_platform: 50,
      status: "running",
      progress: {
        kuaishou: { got: 31, target: 50, phase: "fetching" },
        douyin: { got: 50, target: 50, phase: "done" },
      } as any,
      error_message: "",
      created_at: "",
      started_at: null,
      finished_at: null,
    };
    await nextTick();
    const card = tray.runningTasks.find((t) => t.kind === "mining")!;
    expect(card.title).toContain("宠物吸尘器");
    expect(card.subtitle).toContain("快手 31/50");
    expect(card.subtitle).toContain("抖音已完成");
    expect(card.progress).toBeCloseTo(81 / 100);
    expect(card.cancellable).toBe(true);
  });

  it("batch running → 第 i/N 篇 subtitle + progress getter", async () => {
    const batch = useBatch();
    const tray = useTaskTray();
    batch.$patch({
      status: "running",
      jobId: "u1",
      total: 5,
      items: [
        { index: 1, keyword: "a", status: "success", duration_seconds: 1, document: null, error_type: null, error_message: null },
        { index: 2, keyword: "b", status: "success", duration_seconds: 1, document: null, error_type: null, error_message: null },
        { index: 3, keyword: "c", status: "running", duration_seconds: 0, document: null, error_type: null, error_message: null },
        { index: 4, keyword: "d", status: "queued", duration_seconds: 0, document: null, error_type: null, error_message: null },
        { index: 5, keyword: "e", status: "queued", duration_seconds: 0, document: null, error_type: null, error_message: null },
      ],
    });
    await nextTick();
    const card = tray.runningTasks.find((t) => t.kind === "batch")!;
    expect(card.title).toBe("批量生成 · 5 篇");
    expect(card.subtitle).toContain("第 3/5 篇");
    expect(card.subtitle).toContain("c");
    expect(card.progress).toBeCloseTo(0.4);
  });

  it("article running → 阶段 subtitle，PR1 不可取消", async () => {
    const article = useArticle();
    const tray = useTaskTray();
    article.$patch({
      status: "running",
      jobId: "g1",
      title: "无线吸尘器",
      currentStage: "调用 LLM",
      stageIndex: 4,
    });
    await nextTick();
    const card = tray.runningTasks.find((t) => t.kind === "article")!;
    expect(card.title).toContain("无线吸尘器");
    expect(card.subtitle).toBe("调用 LLM（5/6）");
    expect(card.progress).toBeCloseTo(5 / 6);
    expect(card.cancellable).toBe(false);
  });

  it("runningCount = 监测底层任务数 + 其余卡各 1", async () => {
    const monitor = useMonitorStatus();
    const article = useArticle();
    const tray = useTaskTray();
    monitor.markRunning(11);
    monitor.markRunning(12);
    article.$patch({ status: "running", jobId: "g1", title: "kw", currentStage: "导出", stageIndex: 5 });
    await flushPromises();
    await nextTick();
    expect(tray.runningCount).toBe(3);
  });
});

describe("taskTray — 取消分发 + 最近完成", () => {
  it("监测组卡取消 → 对组内每个 id POST cancel", async () => {
    const monitor = useMonitorStatus();
    const tray = useTaskTray();
    monitor.markRunning(11);
    monitor.markRunning(12);
    await flushPromises();
    await nextTick();
    const zhihu = tray.runningTasks.find((t) => t.kind === "monitor")!;
    await tray.cancelTask(zhihu);
    expect(postMock).toHaveBeenCalledWith("/api/monitor/tasks/11/cancel");
    expect(postMock).toHaveBeenCalledWith("/api/monitor/tasks/12/cancel");
  });

  it("mining 取消 → POST /api/mining/jobs/{id}/cancel", async () => {
    const mining = useMiningStore();
    const tray = useTaskTray();
    mining.activeJob = {
      id: 3, keyword: "k", platforms: ["douyin"], target_per_platform: 50,
      status: "running", progress: {} as any, error_message: "",
      created_at: "", started_at: null, finished_at: null,
    };
    await nextTick();
    await tray.cancelTask(tray.runningTasks.find((t) => t.kind === "mining")!);
    expect(postMock).toHaveBeenCalledWith("/api/mining/jobs/3/cancel");
  });

  it("任务从 running 消失 → 进最近完成区（mining completed → done）并可清空", async () => {
    const mining = useMiningStore();
    const tray = useTaskTray();
    mining.activeJob = {
      id: 3, keyword: "k", platforms: ["douyin"], target_per_platform: 50,
      status: "running", progress: {} as any, error_message: "",
      created_at: "", started_at: null, finished_at: null,
    };
    await nextTick();
    expect(tray.runningTasks.length).toBe(1);

    mining.activeJob = { ...mining.activeJob!, status: "completed" };
    await nextTick();
    expect(tray.runningTasks.length).toBe(0);
    expect(tray.recentFinished.length).toBe(1);
    expect(tray.recentFinished[0].outcome).toBe("done");
    expect(tray.recentFinished[0].title).toContain("k");

    tray.clearFinished();
    expect(tray.recentFinished.length).toBe(0);
  });

  it("batch error → 最近完成 outcome=failed", async () => {
    const batch = useBatch();
    const tray = useTaskTray();
    batch.$patch({ status: "running", jobId: "u1", total: 1, items: [] });
    await nextTick();
    batch.$patch({ status: "error", error: "boom" });
    await nextTick();
    expect(tray.recentFinished[0]?.outcome).toBe("failed");
  });

  it("meta 缓存补齐导致组卡改名 → 不产生幽灵完成", async () => {
    getMock.mockResolvedValueOnce({ data: { tasks: [] } }); // 首拉为空 → fallback 组名
    const monitor = useMonitorStatus();
    const tray = useTaskTray();
    monitor.markRunning(11);
    await flushPromises();
    await nextTick();
    expect(tray.runningTasks[0].title).toBe("监测任务");

    getMock.mockResolvedValue({
      data: { tasks: [{ id: 11, name: "扫地机器人怎么选", type: "zhihu_question" }] },
    });
    await tray.ensureMonitorMeta(true);
    await nextTick();
    expect(tray.runningTasks[0].title).toContain("知乎问题监测");
    expect(tray.recentFinished.length).toBe(0); // 改名 ≠ 完成
  });

  it("取消请求失败 → cancellingKeys 回滚，✕ 可重试", async () => {
    const mining = useMiningStore();
    const tray = useTaskTray();
    mining.activeJob = {
      id: 3, keyword: "k", platforms: ["douyin"], target_per_platform: 50,
      status: "running", progress: {} as any, error_message: "",
      created_at: "", started_at: null, finished_at: null,
    };
    await nextTick();
    const card = tray.runningTasks.find((t) => t.kind === "mining")!;
    postMock.mockRejectedValueOnce(
      Object.assign(new Error("boom"), { response: { status: 500 } }),
    );
    await expect(tray.cancelTask(card)).rejects.toThrow();
    expect(tray.cancellingKeys.has(card.key)).toBe(false);
  });
});
