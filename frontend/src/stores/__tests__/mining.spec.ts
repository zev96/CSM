// frontend/src/stores/__tests__/mining.spec.ts
//
// 引流抓取任务生命周期：SSE 事件对账 / 断线快照 / 取消 409 / loadJobs 兜底。
// 回归背景：sidecar 事件体一度不带 job_id，前端所有 handler 拿 undefined 去比
// activeJob.id → 任务永远停在「抓取中」、托盘常驻「加载中」、停止按钮无效。
import { describe, it, expect, vi, beforeEach } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { flushPromises } from "@vue/test-utils";

const getMock = vi.fn();
const postMock = vi.fn();
vi.mock("@/stores/sidecar", () => ({
  useSidecar: () => ({ client: { get: getMock, post: postMock }, sseURL: (p: string) => p }),
}));
vi.mock("@/composables/useSystemNotify", () => ({
  useSystemNotify: () => ({ notify: vi.fn().mockResolvedValue(undefined) }),
}));

let sseHandlers: Record<string, (d?: any) => void> = {};
let sseOpts: { onError?: () => void } = {};
const stopSse = vi.fn();
const subscribeMock = vi.fn((_path: string, handlers: any, opts: any) => {
  sseHandlers = handlers;
  sseOpts = opts ?? {};
  return stopSse;
});
vi.mock("@/api/client", () => ({ subscribe: (...a: any[]) => subscribeMock(...(a as [string, any, any])) }));

import { useMiningStore, sumFeaturedSkipped, type MiningJob } from "@/stores/mining";
import { useNotifications } from "@/composables/useNotifications";

function job(over: Partial<MiningJob> = {}): MiningJob {
  return {
    id: 7,
    keyword: "空气净化器",
    platforms: ["douyin"],
    target_per_platform: 10,
    status: "pending",
    progress: { douyin: { got: 0, target: 10, phase: "queued" } } as MiningJob["progress"],
    error_message: "",
    created_at: "2026-09-17T00:00:00Z",
    started_at: null,
    finished_at: null,
    ...over,
  };
}

/** getMock 按 URL 路由：jobs 列表 / 单 job 快照 / videos。 */
let jobsList: MiningJob[] = [];
let jobSnapshot: MiningJob | null = null;
function routeGet(url: string) {
  if (url === "/api/mining/jobs") return Promise.resolve({ data: { count: jobsList.length, jobs: jobsList } });
  if (url.startsWith("/api/mining/jobs/")) return Promise.resolve({ data: jobSnapshot });
  if (url === "/api/mining/videos") return Promise.resolve({ data: { total: 0, videos: [] } });
  return Promise.resolve({ data: {} });
}

beforeEach(() => {
  setActivePinia(createPinia());
  localStorage.clear();
  sseHandlers = {};
  sseOpts = {};
  stopSse.mockReset();
  subscribeMock.mockClear();
  jobsList = [job()];
  jobSnapshot = null;
  getMock.mockReset().mockImplementation(routeGet);
  postMock.mockReset().mockResolvedValue({ data: { job_id: 7, job: job() } });
});

async function startJob() {
  const store = useMiningStore();
  await store.startJob("空气净化器", ["douyin"], 10);
  await flushPromises();
  return store;
}

describe("mining store — SSE 事件对账", () => {
  it("startJob 后 activeJob=running，订阅了该 job 的事件流", async () => {
    const store = await startJob();
    expect(store.hasRunningJob).toBe(true);
    expect(subscribeMock).toHaveBeenCalledWith("/api/mining/jobs/7/events", expect.anything(), expect.anything());
  });

  it("事件体不带 job_id（老 sidecar）也按订阅的 job 对账：progress / platform_done / finished 全部生效", async () => {
    const store = await startJob();
    sseHandlers["job.progress"]({ platform: "douyin", got: 3, target: 10, phase: "scrolling", note: "" });
    expect(store.activeJob!.progress.douyin.got).toBe(3);
    expect(store.jobs[0].progress.douyin.got).toBe(3);

    sseHandlers["job.platform_done"]({ platform: "douyin", status: "done", count: 10, error: "" });
    expect(store.activeJob!.progress.douyin).toMatchObject({ got: 10, phase: "done" });

    jobsList = [job({ status: "done" })];
    sseHandlers["job.finished"]({ summary: { status: "done" } });
    await flushPromises();
    expect(store.activeJob!.status).toBe("done");
    expect(store.hasRunningJob).toBe(false);
    expect(stopSse).toHaveBeenCalledTimes(1);
  });

  it("事件体带 job_id 且匹配 → 同样生效；不匹配的 job_id 不污染 activeJob", async () => {
    const store = await startJob();
    sseHandlers["job.progress"]({ job_id: 99, platform: "douyin", got: 5, target: 10, phase: "scrolling" });
    expect(store.activeJob!.progress.douyin.got).toBe(0);
    sseHandlers["job.progress"]({ job_id: 7, platform: "douyin", got: 5, target: 10, phase: "scrolling" });
    expect(store.activeJob!.progress.douyin.got).toBe(5);
  });

  it("finished 只在 running→终态 这一次推通知；取消静默", async () => {
    const store = await startJob();
    jobsList = [job({ status: "cancelled" })];
    sseHandlers["job.finished"]({ summary: { status: "cancelled" } });
    await flushPromises();
    expect(store.activeJob!.status).toBe("cancelled");
    expect(store.hasRunningJob).toBe(false);
    // 再来一次 finished（重复投递）不会再触发收尾（stopSse 只调一次）
    sseHandlers["job.finished"]({ summary: { status: "cancelled" } });
    expect(stopSse).toHaveBeenCalledTimes(1);
  });

  it("只收到 done 哨兵、没有 job.finished（runner 异常）→ 快照对账拿到终态", async () => {
    const store = await startJob();
    jobSnapshot = job({ status: "failed" });
    jobsList = [job({ status: "failed" })];
    sseHandlers.done();
    await flushPromises();
    expect(getMock).toHaveBeenCalledWith("/api/mining/jobs/7");
    expect(store.activeJob!.status).toBe("failed");
    expect(store.hasRunningJob).toBe(false);
  });

  it("EventSource 断线 onError → 快照对账；运行中不改终态，终态则收尾", async () => {
    const store = await startJob();
    jobSnapshot = job({ status: "running", progress: { douyin: { got: 4, target: 10, phase: "scrolling" } } as any });
    sseOpts.onError!();
    await flushPromises();
    expect(store.hasRunningJob).toBe(true);
    expect(store.activeJob!.progress.douyin.got).toBe(4);
    expect(stopSse).not.toHaveBeenCalled();

    jobSnapshot = job({ status: "done" });
    jobsList = [job({ status: "done" })];
    sseOpts.onError!();
    await flushPromises();
    expect(store.hasRunningJob).toBe(false);
    expect(stopSse).toHaveBeenCalledTimes(1);
  });
});

describe("mining store — 精选评论跳过数（完成通知报数）", () => {
  const doneBodies = () =>
    useNotifications().items.value.filter(n => n.category === "mining_done").map(n => n.body);
  const biliProgress = (n: number) =>
    ({ bilibili: { got: 50, target: 50, phase: "done", note: "", featured_skipped: n } }) as any;

  beforeEach(() => useNotifications().clear());

  it("sumFeaturedSkipped：跨平台求和，缺字段 / 脏值 / 空输入都当 0", () => {
    expect(sumFeaturedSkipped({
      bilibili: { got: 1, target: 1, phase: "done", featured_skipped: 3 },
      douyin: { got: 1, target: 1, phase: "done" },
      kuaishou: { got: 1, target: 1, phase: "done", featured_skipped: 2 },
    })).toBe(5);
    expect(sumFeaturedSkipped({ bilibili: { got: 0, target: 0, phase: "done", featured_skipped: -1 } })).toBe(0);
    expect(sumFeaturedSkipped({ bilibili: { got: 0, target: 0, phase: "done", featured_skipped: "x" as any } })).toBe(0);
    expect(sumFeaturedSkipped(null)).toBe(0);
    expect(sumFeaturedSkipped(undefined)).toBe(0);
  });

  it("job.finished 的 summary.progress 带 featured_skipped → 通知里报数", async () => {
    await startJob();
    jobsList = [job({ status: "done" })];
    sseHandlers["job.finished"]({ summary: { status: "done", progress: biliProgress(3) } });
    await flushPromises();
    expect(doneBodies()).toEqual(["「空气净化器」全部平台完成，已跳过 3 条开启评论精选的视频"]);
  });

  it("summary 不带 progress（老 sidecar）→ 退回 platform_done 事件攒下的计数", async () => {
    const store = await startJob();
    sseHandlers["job.platform_done"]({ platform: "douyin", status: "done", count: 10, error: "", featured_skipped: 2 });
    expect(store.activeJob!.progress.douyin.featured_skipped).toBe(2);
    expect(store.jobs[0].progress.douyin.featured_skipped).toBe(2);
    jobsList = [job({ status: "done" })];
    sseHandlers["job.finished"]({ summary: { status: "done" } });
    await flushPromises();
    expect(doneBodies()).toEqual(["「空气净化器」全部平台完成，已跳过 2 条开启评论精选的视频"]);
  });

  it("没有跳过任何视频 → 通知文案保持原样；platform_done 也不写 featured_skipped", async () => {
    const store = await startJob();
    sseHandlers["job.platform_done"]({ platform: "douyin", status: "done", count: 10, error: "", featured_skipped: 0 });
    expect("featured_skipped" in store.activeJob!.progress.douyin).toBe(false);
    jobsList = [job({ status: "done" })];
    sseHandlers["job.finished"]({ summary: { status: "done", progress: { douyin: { got: 10, target: 10, phase: "done" } } } });
    await flushPromises();
    expect(doneBodies()).toEqual(["「空气净化器」全部平台完成"]);
  });

  it("断线快照拿到终态 → 同样报数", async () => {
    await startJob();
    jobSnapshot = job({ status: "done", progress: biliProgress(4) });
    jobsList = [job({ status: "done" })];
    sseOpts.onError!();
    await flushPromises();
    expect(doneBodies()).toEqual(["「空气净化器」全部平台完成，已跳过 4 条开启评论精选的视频"]);
  });

  it("loadJobs 兜底对账拿到终态 → 同样报数", async () => {
    const store = await startJob();
    jobsList = [job({ status: "partial_done", progress: biliProgress(1) })];
    await store.loadJobs();
    await flushPromises();
    expect(doneBodies()).toEqual(["「空气净化器」部分平台未完成，已跳过 1 条开启评论精选的视频"]);
  });
});

describe("mining store — 取消", () => {
  it("cancelActive 正常 POST cancel", async () => {
    const store = await startJob();
    postMock.mockResolvedValueOnce({ data: { cancelled: true } });
    await store.cancelActive();
    expect(postMock).toHaveBeenLastCalledWith("/api/mining/jobs/7/cancel");
  });

  it("cancel 返回 409（后端已结束）→ 立刻快照对账，不再停留在「抓取中」", async () => {
    const store = await startJob();
    postMock.mockRejectedValueOnce({ response: { status: 409 } });
    jobSnapshot = job({ status: "done" });
    jobsList = [job({ status: "done" })];
    await store.cancelActive();
    await flushPromises();
    expect(store.hasRunningJob).toBe(false);
    expect(store.activeJob!.status).toBe("done");
  });

  it("cancelJob 对非活跃 job 的 409 → 刷新任务列表", async () => {
    const store = useMiningStore();
    postMock.mockRejectedValueOnce({ response: { status: 409 } });
    jobsList = [job({ id: 3, status: "done" })];
    await store.cancelJob(3);
    expect(store.jobs[0].status).toBe("done");
  });

  it("cancel 非 409 错误原样抛出", async () => {
    const store = await startJob();
    postMock.mockRejectedValueOnce({ response: { status: 500 } });
    await expect(store.cancelActive()).rejects.toBeTruthy();
    expect(store.hasRunningJob).toBe(true);
  });
});

describe("mining store — loadJobs 兜底对账", () => {
  it("activeJob 仍 running 但列表里已终态 → 采用终态并收尾", async () => {
    const store = await startJob();
    jobsList = [job({ status: "partial_done" })];
    await store.loadJobs();
    await flushPromises();
    expect(store.activeJob!.status).toBe("partial_done");
    expect(store.hasRunningJob).toBe(false);
    expect(stopSse).toHaveBeenCalled();
  });

  it("页面重开：无活跃任务、列表里有 running job → 重新订阅其事件流", async () => {
    const store = useMiningStore();
    jobsList = [job({ id: 12, status: "running" }), job({ id: 11, status: "done" })];
    await store.loadJobs();
    expect(store.activeJob?.id).toBe(12);
    expect(store.hasRunningJob).toBe(true);
    expect(subscribeMock).toHaveBeenCalledWith("/api/mining/jobs/12/events", expect.anything(), expect.anything());
  });

  it("列表里没有 running job → 不订阅、不改 activeJob", async () => {
    const store = useMiningStore();
    jobsList = [job({ id: 11, status: "done" })];
    await store.loadJobs();
    expect(store.activeJob).toBeNull();
    expect(subscribeMock).not.toHaveBeenCalled();
  });
});
