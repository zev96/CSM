# 平台评论 L1：批量「立刻监测」按钮

## 背景

`MonitorView.vue` 平台评论 tab 的 L1（任务汇总）行只有「编辑批次」
（铅笔）和「删除批次」（垃圾桶）两个动作。要触发某批次下 N 个视频
任务重跑，用户得先点任务名进 L2 视频列表，再对每一个视频单独点
「立刻监测」。N=5 的批次就要点 5 次 + N 次切换，是个明显的高频痛点。

需求：在 L1 行加一个**批量立刻监测**按钮，一键派发该批次下所有子
任务，复用现有 SSE 状态机做实时反馈与自动刷新。

## 范围

- 仅评论 tab（B 站 / 抖音 / 快手 共享）
- 知乎 tab L1 行已经是单任务、自带「立刻监测」，不在本次改动
- 不引入新的后端接口、不改并发策略
- 不引入新的 modal / 弹层

## 设计

### 按钮放置

L1 行 status 列（rightmost 列），顺序：

```
<状态 pill>  <批量立刻监测 按钮>  <编辑> <删除>
                  ↑ 新增
```

样式复用 L2 video list 的「立刻监测」按钮：小号药丸状（`padding: 4px
10px / radius: 999px`），文字色 `--primary-deep`，背景透明。

### 文案状态机

按现有 `runningTaskIds[]` 字典推断：

```ts
const child = tasks.filter(t => parseBatchName(t.name) === batchName)
const runningCount = child.filter(t => runningTaskIds[t.id]).length
const total = child.length

label = runningCount === 0 ? '立刻监测'
      : runningCount === total ? '监测中…'
      : `监测中 ${total - runningCount}/${total}`   // "已完成数 / 总数"
disabled = runningCount > 0
```

`监测中 3/5` 读作「5 个里跑完 3 个」——progress 而非 still-running 计数，
跑完一个就自增，符合用户期望。

### 派发流程

```ts
async function runBatch(batchName: string) {
  const child = tasks.value.filter(t => parseBatchName(t.name) === batchName)
  if (!child.length) return
  child.forEach(t => markRunning(t.id))   // 乐观标记，按钮立刻切到 disabled
  const results = await Promise.allSettled(
    child.map(t => sidecar.client.post(`/api/monitor/tasks/${t.id}/run-now`))
  )
  const fails = results.filter(r => r.status === 'rejected')
  if (fails.length === 0) {
    toast.info(`已派发 ${child.length} 个任务`)
  } else if (fails.length === child.length) {
    child.forEach(t => clearRunning(t.id))   // 全失败：清掉 spinner
    toast.error(`派发失败：${fails.length}/${child.length}`)
  } else {
    results.forEach((r, i) => {
      if (r.status === 'rejected') clearRunning(child[i].id)
    })
    toast.warn(`派发 ${child.length - fails.length}/${child.length}，${fails.length} 失败`)
  }
}
```

派发成功后 **不**主动 reload 全列 snapshot —— SSE bus 的 `finished`
handler 已经会对每个子任务 `_fetchSnapshotPair`，L1 行的留存 / 变化
是 computed 自 snapshot，会跟着自动刷。

### 并发与风控

后端 `monitor_loop.run_task_now` 把请求扔进 ThreadPoolExecutor，每平台
有 `rate_limit.py` 的 Semaphore（默认 max_in_flight=2），再叠每任务的
`pacer`。前端一次性 fire 5 个 POST 对后端就是 5 个 future 排队，超过
信号量数量的会阻塞——**不会**形成对快手 / B 站 GraphQL 的冲击。

数据库写也安全：每 worker 线程在 `storage` 用 `threading.local`
sqlite 连接，不冲突。

## 验证

- 单元测：mock `sidecar.client.post`，验证 `runBatch` 派发的 task_id
  集合等于 batch 的 child task ids，且失败/成功分支 toast 文案正确
- 手动：dev 启动 → 平台评论 → 快手 → 0514 批次 → 点批量立刻监测 →
  按钮变「监测中 0/5」→ SSE 推进时数字递增 → 全跑完按钮回到「立刻
  监测」、留存列同步更新
- 不破坏既有：L2 单任务「立刻监测」、L3 单视频「立刻监测」、编辑
  批次、删除批次都保留行为不变

## 不动的（YAGNI）

- 不加进度 modal / 不展开 L1 行 / 不加「取消运行中」按钮
- 不修改后端 `/run-now` 接口签名（保持单任务粒度，前端组合）
- 不动 `rate_limit.py` 的并发数（默认值是验证过的）
