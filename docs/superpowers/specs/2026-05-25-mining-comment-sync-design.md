# 引流视频抓取 → 监测中心 同步联动 设计文档

**日期**：2026-05-25
**范围**：1 个改造（mining 采集时全局查重 + 反爬保护）+ 1 个新增（mining 任务同步到 monitor 的手动按钮 + 后端服务）
**预计 PR 拆分**：1 个 PR（前后端一起，因为前端按钮依赖后端 API）

---

## 1. 背景

当前 mining 模块（引流视频抓取）和 monitor 模块（评论排名监测）在数据库层共享 `monitor.db`，但**业务流程脱节**：

1. **缺采集端查重**：mining adapter 抓视频时只在 `videos` 表内查重（`UNIQUE(platform, platform_video_id)`），不查 `monitor_tasks`。已经在监测中心追踪过的视频会被重复抓取入库，但兼职没新内容可操作。
2. **缺业务联动**：用户在 mining 给每条视频起草了 tier=1 评论（`video_comments` 表），兼职拿草稿去发评论，但 mining 这边无法**一键把"视频 URL + 草稿评论"批量灌进 monitor**。当前必须在监测中心手动 Excel/逐条录入，工作量大且容易抄错。

本次目标：把 mining 已经产出的（视频 + 第一层评论草稿）转成 monitor 任务，让兼职发完评论后直接启动监测。

---

## 2. 目标 / 非目标

### 目标

1. mining 采集时跨 `videos` + `monitor_tasks` 全局查重，已存在的视频静默跳过，不入 `videos` 表。
2. adapter 翻页凑齐 `target_per_platform` 配额，但带反爬保护（硬上限 + 随机延迟）。
3. mining 任务列表行的三点菜单新增"同步监测中心"按钮，仅当该 job 的所有视频都被标记 `already_commented=1` 时可点击。
4. 弹窗收集 monitor 元数据（任务名前缀 / 理想排名 / 计划），后台自动批量创建 `monitor_tasks`，`enabled=false` 等待兼职手动启动。
5. 同步过程对单条失败/重复/无草稿等情况有明确的反馈和跳过策略，不中断整批。

### 非目标（YAGNI）

- 不做 monitor → mining 的反向联动（task 删除/修改不影响 mining）。
- 不做 mining job 完成的自动 trigger 同步（必须用户手动点）。
- 不做同步弹窗内的视频明细预览 / 反选（一次同步整 job 全部可同步视频）。
- 不做 monitor_tasks 的 schedule_cron 自定义（默认手动 = `null`）。
- 不做跨 mining job 的合并同步。
- 不做 video_comments 的 AI 重新建议入口。
- 不做 monitor_tasks 命名模板自定义（命名规则固定：`{弹窗任务名前缀} - {video.title[:30]}`，前缀默认 = mining job 名，用户可改）。

---

## 3. 总览：1 个改造 + 1 个新增

```
┌────────────────────────────────────────────────────────────────────┐
│ 改造 ①：mining adapter 采集时全局查重                              │
│                                                                    │
│   adapter 抓到 VideoCard                                          │
│     ↓                                                              │
│   storage.is_video_tracked_in_monitor_or_videos(platform, vid)    │
│     ├── 已在 videos 表 OR monitor_tasks 表 → 静默跳过             │
│     │     → runner 计数 skipped_duplicates++                       │
│     │     → adapter 翻下一页                                       │
│     │     → 受 MAX_ATTEMPTS_PER_PLATFORM 硬上限保护                │
│     │     → 每页之间 2-5s 随机延迟                                 │
│     │                                                              │
│     └── 都不存在 → upsert_video_and_link() 正常入库                │
│           → collected++                                            │
│                                                                    │
│   退出条件：collected == target_per_platform                       │
│            OR attempt > max_attempts                               │
│            OR adapter 自然 EOF                                     │
└────────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────────┐
│ 新增 ②：mining 任务"同步监测中心"动作                              │
│                                                                    │
│ 前端                                                                │
│   MiningView 三点菜单：                                            │
│     [导出 CSV] [删除任务] [同步监测中心 ← 新]                      │
│   按钮可点击条件 = mining_jobs.status ∈ {done, partial_done}       │
│                    AND total_videos > 0                            │
│                    AND count(already_commented=1) == total_videos  │
│                                                                    │
│   点击 → SyncToMonitorModal：                                      │
│     ┌──────────────────────────────┐                              │
│     │ 任务名前缀：[mining job 名]   │                              │
│     │ 理想排名：  [5]               │                              │
│     │ 计划：     [手动 ▾]           │                              │
│     │              [取消] [同步]    │                              │
│     └──────────────────────────────┘                              │
│                                                                    │
│ 后端 POST /api/mining/jobs/{job_id}/sync_to_monitor               │
│   for each video in job (JOIN video_source_keywords):              │
│     ├── 已在 monitor_tasks（按 video_id 正则匹配）→ skipped_dup++  │
│     ├── 无 tier=1 video_comments OR text='' → skipped_no_draft++  │
│     └── 创建 monitor_tasks(                                        │
│           type=f"{video.platform}_comment",                        │
│           name=f"{prefix} - {video.title[:30]}",                   │
│           target_url=video.url,                                    │
│           config={my_comment_text: text, top_n: 用户输入,          │
│                   scrape_top_n: 150},                              │
│           schedule_cron=None,                                      │
│           enabled=False                                            │
│         ) → created++                                              │
│   return {created, skipped_dup, skipped_no_draft, errors[]}        │
│                                                                    │
│   前端 toast：                                                      │
│     "已同步 X 条到监测中心；跳过 Y 条（已存在）+ Z 条（无草稿）"   │
└────────────────────────────────────────────────────────────────────┘
```

### 关键设计原则

- **手动触发，不自动**：避免 mining job 完成事件挂监听器；用户手动点 = 二次确认，符合"兼职业务流"。
- **enabled=false 默认**：所有新建的 monitor_tasks 都关掉，等兼职发完评论手动启动。
- **复用 monitor 现有代码**：不改 monitor 的 schema/路由/UI，纯单向写入 `monitor_tasks`。
- **平台自动分配**：`monitor_tasks.type = f"{video.platform}_comment"`，无需新增映射表。

---

## 4. 详细设计

### 4.1 改造点：mining 采集时全局查重 + 反爬保护

#### 查重 SQL

`monitor_tasks` 没有 `platform_video_id` 列（现状是从 `target_url` 用正则提取，见 `_check_already_commented()` line 589-621）。本设计**复用现有正则**，不动 schema。

拆成两个独立函数，组合调用更清晰、复用性更高：

```python
# csm_core/mining/storage.py

def is_video_in_videos_table(
    conn: sqlite3.Connection,
    platform: str,
    platform_video_id: str,
) -> bool:
    """videos 表精确 UNIQUE 查询，O(1)。"""
    row = conn.execute(
        "SELECT 1 FROM videos WHERE platform=? AND platform_video_id=? LIMIT 1",
        (platform, platform_video_id),
    ).fetchone()
    return row is not None


def is_video_in_monitor_tasks(
    conn: sqlite3.Connection,
    platform: str,
    platform_video_id: str,
) -> bool:
    """monitor_tasks 反查：LIKE + 正则精确匹配。

    monitor_tasks 没有独立的 platform_video_id 列，所以这里走两步：
      1. LIKE 加速过滤（带 idx_monitor_tasks_target_url 索引）
      2. 用 _extract_platform_video_id() 正则二次确认避免误判
    """
    type_map = {
        "douyin": "douyin_comment",
        "kuaishou": "kuaishou_comment",
        "bilibili": "bilibili_comment",
    }
    task_type = type_map.get(platform)
    if not task_type:
        return False  # 未知平台不查 monitor

    candidates = conn.execute(
        "SELECT target_url FROM monitor_tasks WHERE type=? AND target_url LIKE ?",
        (task_type, f"%{platform_video_id}%"),
    ).fetchall()

    for (target_url,) in candidates:
        extracted = _extract_platform_video_id(target_url, platform)
        if extracted == platform_video_id:
            return True
    return False


def is_video_tracked_anywhere(
    conn: sqlite3.Connection,
    platform: str,
    platform_video_id: str,
) -> bool:
    """采集时用：videos OR monitor_tasks 任一存在即跳过。"""
    return (
        is_video_in_videos_table(conn, platform, platform_video_id)
        or is_video_in_monitor_tasks(conn, platform, platform_video_id)
    )
```

使用场景：

- **采集阶段** runner 调 `is_video_tracked_anywhere()`
- **同步阶段** sync_to_monitor 调 `is_video_in_monitor_tasks()`（video 一定在 videos 表里，所以不需要再查 videos）

新增索引：放在 `csm_core/mining/storage.py` 的 `_DDL_V5_MINING`（即下一个新 phase）中，配合 `apply_v5_migration()` 函数（参照 v4 migration 命名规约 line 119）：

```sql
CREATE INDEX IF NOT EXISTS idx_monitor_tasks_target_url
  ON monitor_tasks(type, target_url);
```

#### Runner 改造

```python
# csm_core/mining/runner.py（伪码）

from .config import MAX_ATTEMPTS_PER_PLATFORM, PAGE_DELAY_RANGE_SEC
import random
import asyncio

async def _collect_for_platform(
    platform: str,
    adapter: BaseAdapter,
    target: int,
    job_id: int,
) -> CollectStats:
    collected = 0
    skipped_dup = 0
    attempts = 0
    max_attempts = MAX_ATTEMPTS_PER_PLATFORM.get(platform, 5)

    page_size = adapter.page_size  # adapter 已有这个属性
    max_items = max_attempts * page_size

    async for video_card in adapter.iter_videos():
        attempts += 1
        if is_video_tracked_anywhere(
            conn, platform, video_card.platform_video_id
        ):
            skipped_dup += 1
        else:
            upsert_video_and_link(conn, video_card, job_id, ...)
            collected += 1

        if collected >= target:
            break
        if attempts >= max_items:
            logger.info(
                "[%s] hit max_attempts=%d (collected=%d/%d, skipped_dup=%d)",
                platform, max_attempts, collected, target, skipped_dup,
            )
            break

        # 用 attempts % page_size == 0 判断"刚消费完一页"
        # 比 adapter.just_paginated（不存在的属性）可靠，不依赖 adapter 内部状态
        if attempts > 0 and attempts % page_size == 0:
            await asyncio.sleep(random.uniform(*PAGE_DELAY_RANGE_SEC))

    update_job_progress(conn, job_id, {
        "collected": collected,
        "skipped_duplicates": skipped_dup,
        "max_attempts_hit": attempts >= max_items,
    })
    return CollectStats(collected, skipped_dup, attempts)
```

#### 配置常量

新增 `csm_core/mining/config.py`（或扩展现有）：

```python
# 每平台翻页硬上限（页数，不是条目）
MAX_ATTEMPTS_PER_PLATFORM: dict[str, int] = {
    "douyin": 3,
    "kuaishou": 5,
    "bilibili": 8,
}

# 翻页之间随机延迟范围（秒）
PAGE_DELAY_RANGE_SEC: tuple[float, float] = (2.0, 5.0)

# 同步到 monitor 时的默认值
DEFAULT_MONITOR_TOP_N: int = 5
DEFAULT_MONITOR_SCRAPE_TOP_N: int = 150
```

#### 兜底降级

`is_video_tracked_in_monitor_or_videos()` 异常时（DB 锁 / I/O 失败）记 warn log 但**不中断**，让 `upsert_video_and_link()` 走 SQL UNIQUE 兜底（已有的 `INSERT OR IGNORE`）。

### 4.2 新增点：同步到监测中心

#### 后端服务模块

新建 `csm_core/mining/sync_to_monitor.py`：

```python
"""mining → monitor 单向同步。

输入：mining_job_id + 同步参数（任务名前缀、top_n、schedule_cron）
输出：SyncResult{created, skipped_dup, skipped_no_draft, errors}

约束：
- 只同步该 job 的 videos
- 每条 video 取 tier=1 的 video_comments；text 为空也算"无草稿"
- 跳过已在 monitor_tasks 出现的 (platform, video_id)
- 单条失败不中断整批，收集到 errors[]
- 新创 monitor_tasks 一律 enabled=False
"""

@dataclass
class SyncParams:
    task_name_prefix: str
    top_n: int = 5
    scrape_top_n: int = 150
    schedule_cron: str | None = None  # None = 手动

@dataclass
class SyncResult:
    created: int
    skipped_dup: int
    skipped_no_draft: int
    errors: list[dict]  # [{video_id, reason}, ...]

def run(
    conn: sqlite3.Connection,
    job_id: int,
    params: SyncParams,
) -> SyncResult:
    rows = conn.execute("""
        SELECT v.id, v.platform, v.platform_video_id, v.url, v.title,
               vc.text AS comment_text
        FROM videos v
        JOIN video_source_keywords vsk ON vsk.video_id = v.id
        LEFT JOIN video_comments vc
          ON vc.video_id = v.id AND vc.tier = 1
        WHERE vsk.job_id = ?
    """, (job_id,)).fetchall()

    result = SyncResult(0, 0, 0, [])
    for row in rows:
        try:
            # 同步时只需查 monitor_tasks（video 必在 videos 表里，跳过那层冗余检查）
            if is_video_in_monitor_tasks(
                conn, row["platform"], row["platform_video_id"]
            ):
                result.skipped_dup += 1
                continue

            comment_text = (row["comment_text"] or "").strip()
            if not comment_text:
                result.skipped_no_draft += 1
                continue

            _create_monitor_task(
                conn,
                task_type=f"{row['platform']}_comment",
                name=f"{params.task_name_prefix} - {row['title'][:30]}",
                target_url=row["url"],
                config={
                    "my_comment_text": comment_text,
                    "top_n": params.top_n,
                    "scrape_top_n": params.scrape_top_n,
                },
                schedule_cron=params.schedule_cron,
                enabled=False,
            )
            result.created += 1
        except Exception as e:
            logger.exception("sync video_id=%s failed", row["id"])
            result.errors.append({"video_id": row["id"], "reason": str(e)})

    logger.info(
        "[sync_to_monitor] job_id=%d created=%d skipped_dup=%d "
        "skipped_no_draft=%d errors=%d",
        job_id, result.created, result.skipped_dup,
        result.skipped_no_draft, len(result.errors),
    )
    return result
```

#### HTTP 端点

新增 `sidecar/csm_sidecar/routes/mining.py`：

```python
class SyncToMonitorRequest(BaseModel):
    task_name_prefix: str = Field(min_length=1, max_length=100)
    top_n: int = Field(ge=1, le=50, default=5)
    schedule_cron: str | None = None  # None = 手动

class SyncToMonitorResponse(BaseModel):
    created: int
    skipped_dup: int
    skipped_no_draft: int
    errors: list[dict]

@router.post(
    "/api/mining/jobs/{job_id}/sync_to_monitor",
    response_model=SyncToMonitorResponse,
)
async def sync_to_monitor(job_id: int, req: SyncToMonitorRequest):
    job = mining_storage.get_job(conn, job_id)
    if not job:
        raise HTTPException(404, "job_not_found")

    if job["status"] not in ("done", "partial_done"):
        raise HTTPException(
            409,
            detail={"error": "job_not_ready", "reason": "status_not_done"},
        )

    stats = mining_storage.get_video_stats(conn, job_id)
    if stats["total"] == 0 or stats["already_commented"] != stats["total"]:
        raise HTTPException(
            409,
            detail={
                "error": "job_not_ready",
                "reason": "not_all_commented",
                "total": stats["total"],
                "already_commented": stats["already_commented"],
            },
        )

    result = sync_to_monitor.run(
        conn, job_id,
        SyncParams(
            task_name_prefix=req.task_name_prefix,
            top_n=req.top_n,
            schedule_cron=req.schedule_cron,
        ),
    )
    return SyncToMonitorResponse(
        created=result.created,
        skipped_dup=result.skipped_dup,
        skipped_no_draft=result.skipped_no_draft,
        errors=result.errors,
    )
```

#### 前端组件

新建 `frontend/src/components/mining/SyncToMonitorModal.vue`：

- Props: `jobId: number`, `defaultName: string`（mining job 名）
- Form fields:
  - 任务名前缀（默认 = defaultName，min 1 max 100）
  - 理想排名 top_n（默认 5、min 1 max 50）
  - 计划：本期**只显示"手动"一个选项**（下拉禁用或纯文字标签），对应后端 `schedule_cron=null`。未来扩展时再加其它选项。
- 按钮：取消 / 同步
- 点同步 → call `store.syncToMonitor(jobId, params)` → 成功 toast + emit close

修改 `frontend/src/views/MiningView.vue`：

- 三点菜单加 menuitem "同步监测中心"，条件 disabled + tooltip：
  - 用现有 `videoStats` computed（line 433-436）判断
  - disabled tooltip 文案：
    - status 不是 done/partial_done：「请先等待采集完成」
    - total=0：「该任务无可同步视频」
    - 未全标：「还有 X 条视频未标记已评论」
- 点击 → 打开 `SyncToMonitorModal`

修改 `frontend/src/stores/mining.ts`：

```typescript
async syncToMonitor(
  jobId: number,
  params: { task_name_prefix: string; top_n: number; schedule_cron: string | null }
): Promise<{ created: number; skipped_dup: number; skipped_no_draft: number; errors: any[] }> {
  const { data } = await api.post(
    `/api/mining/jobs/${jobId}/sync_to_monitor`,
    params
  );
  return data;
}
```

#### Toast 文案模板

```
成功（created > 0）：
  "已同步 {created} 条到监测中心
   （跳过 {skipped_dup} 条已存在，{skipped_no_draft} 条无评论草稿）"

全部 dup：
  "无新增。{skipped_dup} 条视频均已在监测中心"

有 errors：
  "同步完成：成功 {created} / 失败 {errors.length}。点击查看详情"
  （点开展示 errors 列表）
```

---

## 5. 改动文件清单

| # | 文件 | 类型 | 备注 |
|---|------|------|------|
| 1 | `csm_core/mining/storage.py` | 改 | 加 `is_video_tracked_in_monitor_or_videos()`；DDL 加 `idx_monitor_tasks_target_url` |
| 2 | `csm_core/mining/runner.py` | 改 | 凑额度循环 + 翻页随机延迟 + skipped_duplicates 计数 |
| 3 | `csm_core/mining/sync_to_monitor.py` | **新** | 同步主逻辑 |
| 4 | `csm_core/mining/config.py` | 改/新 | `MAX_ATTEMPTS_PER_PLATFORM`, `PAGE_DELAY_RANGE_SEC`, `DEFAULT_MONITOR_TOP_N`, `DEFAULT_MONITOR_SCRAPE_TOP_N` |
| 5 | `sidecar/csm_sidecar/routes/mining.py` | 改 | 新端点 `POST /api/mining/jobs/{job_id}/sync_to_monitor` |
| 6 | `frontend/src/components/mining/SyncToMonitorModal.vue` | **新** | 弹窗组件 |
| 7 | `frontend/src/views/MiningView.vue` | 改 | 三点菜单加项 + disabled 逻辑 |
| 8 | `frontend/src/stores/mining.ts` | 改 | `syncToMonitor()` 方法 |
| 9 | `csm_sidecar/tests/test_collect_dedup.py` | **新** | 采集查重 + 凑额度 单元测试 |
| 10 | `csm_sidecar/tests/test_sync_to_monitor.py` | **新** | 同步逻辑单元测试 |
| 11 | `csm_sidecar/tests/test_sync_to_monitor_api.py` | **新** | HTTP API 测试 |
| 12 | `csm_sidecar.spec` / `csm_sidecar_onefile.spec` | 检查 | 如果新模块有非 .py 数据文件确保 `collect_data_files("csm_core")` 兜底（v0.5.6 教训） |
| 13 | `CHANGELOG.md` | 改 | 加 entry（release.yml 会卡 extract_changelog） |

---

## 6. 数据库变更

**不动现有 schema 列**。仅新增 1 个索引：

```sql
CREATE INDEX IF NOT EXISTS idx_monitor_tasks_target_url
  ON monitor_tasks(type, target_url);
```

加在 `csm_core/mining/storage.py` 的下一个 phase migration `_DDL_V5_MINING` + `apply_v5_migration()`（参照 v4 命名规约 line 100-128）。注意索引建在 `monitor_tasks` 表上，但 migration 函数挂在 mining 模块，跟改造责任绑定。

**不引入 platform_video_id 列**到 monitor_tasks：复用现有 `_extract_platform_video_id()` 正则。如果未来 video 量上万、查重热点变性能瓶颈，再考虑加列 + 反填 migration。

---

## 7. 状态机 / 边界条件

### 同步按钮可点击逻辑

```
按钮可点击 ⇔ 同时满足：
  1. mining_jobs.status ∈ {"done", "partial_done"}
  2. total_videos > 0
  3. count(videos.already_commented=1) == total_videos
```

| 状态 | 按钮 | tooltip |
|---|---|---|
| pending/running | disabled | 请先等待采集完成 |
| done/partial_done + total=0 | disabled | 该任务无可同步视频 |
| done/partial_done + 部分已评论 | disabled | 还有 X 条视频未标记已评论 |
| done/partial_done + 全部已评论 | enabled | — |
| failed/cancelled/interrupted | disabled | 请先等待采集完成 |

### 边界处理表

| 边界 | 处理 |
|---|---|
| video 标 already_commented=1 但 tier=1 草稿为空（含 `text=''`） | 跳过 + `skipped_no_draft++` |
| 同 mining job 重复点同步 | 第 2 次：全 skipped_dup，created=0，toast 提示 |
| 同步中用户关闭弹窗 / 切页 | 后端继续跑（POST 不依赖前端连接） |
| 2 个 mining job 含同一 video | 第 1 个建 task；第 2 个 skipped_dup |
| 采集 dup 检查 SQL 异常 | warn log + UPSERT 兜底，不中断 |
| 同步单条 monitor_tasks 创建失败 | 加入 errors[]，继续下一条 |
| job 未完成强行 POST 同步 API | 后端二次校验，返回 409 |
| video 被删除但 monitor_tasks 已建 | LEFT JOIN 自然不返回，无悬空 |

---

## 8. 错误处理

### HTTP 错误码

| 端点 | 码 | 含义 |
|---|---|---|
| `POST /api/mining/jobs/{job_id}/sync_to_monitor` | 404 | job_id 不存在 |
| | 409 | job 未到可同步状态（含 `detail.reason` 区分） |
| | 422 | 请求体校验失败（top_n 非正整数等） |
| | 200 | 完成（无论 created 是否 = 0） |

### 前端处理

- 200 → toast + 关闭弹窗
- 409 → 弹窗内红字显示原因（理论上 UI 已 disable，到这里是并发，提示用户刷新）
- 5xx → toast「同步失败：{message}」+ 不关闭弹窗供重试

### 日志

`sync_to_monitor.run()` 完成时**必须**输出 raw log（参考 v0.5.8 silent failure 教训）：

```
[sync_to_monitor] job_id=42 created=18 skipped_dup=3 skipped_no_draft=2 errors=0
```

errors 非空时另起一行打 detail。

---

## 9. 测试策略

### 单元测试

| 文件 | 用例 |
|---|---|
| `test_collect_dedup.py` | ① video 已在 videos 表 → skip<br>② video 已在 monitor_tasks（正则提取 video_id 命中）→ skip<br>③ 都不存在 → 正常 upsert<br>④ adapter 翻页到 max_attempts 退出（fake adapter 全返回 dup）<br>⑤ adapter 自然 EOF 提前退出<br>⑥ dup 检查 SQL 异常 → 兜底走 UNIQUE 不中断 |
| `test_sync_to_monitor.py` | ① 5 video 都有 tier=1 草稿 → created=5<br>② 2 video 没 tier=1 草稿 → skipped_no_draft=2<br>③ 3 video 已在 monitor_tasks → skipped_dup=3<br>④ 混合（5 创/2 dup/3 无草稿）<br>⑤ video_comments.text='' 视为无草稿<br>⑥ 单条 monitor_tasks 创建失败不中断，errors[] 长度=1<br>⑦ 平台映射正确（douyin/kuaishou/bilibili → 对应 type） |
| `test_sync_to_monitor_api.py` | ① job 不存在 → 404<br>② job 未完成 → 409<br>③ top_n=0 → 422<br>④ 正常 → 200 + body 字段齐全 |

### 集成测试

- 跑真实 SQLite 内存库（不 mock storage）
- 端到端：模拟 mining job 完成 → POST sync API → 检查 monitor_tasks 表实际行数和字段值

### 手动验收

1. **dev 模式**：
   - 跑抖音 mining 抓 5 条 → 起草 5 条 tier=1 评论 → 全部标记已评论
   - 三点菜单出现"同步监测中心"且可点击；填任务名、top_n=5、计划=手动 → 点同步
   - 监测中心出现 5 条新 task，type=douyin_comment、enabled=false、my_comment_text 正确
   - 切到监测中心手动启用 1 条 → 跑一次 → 排名结果正常

2. **重复同步**：同 job 再点 → toast 跳过 5 条；monitor_tasks 不出现重复

3. **跨 job 重复**：跑同关键词第 2 次 mining → progress 提示「跳过 5 条重复」；videos 新增 0 条

4. **反爬保护**：mock adapter 持续返回 dup → 验证抖音翻 3 页就停 + UI 提示

5. **未完成强行同步**：未全部标记已评论时按钮 disabled；如果手动 curl POST → 409

6. **release 包验收**：全新 Win 机器装 NSIS → 重复 1-5

---

## 10. 实施顺序

```
Phase 1: 后端基础（独立可测，Phase 1 & 2 可并行）
  1.1 config.py 常量
  1.2 storage.is_video_tracked_in_monitor_or_videos() + 索引迁移
  1.3 test_collect_dedup.py（TDD）
  1.4 runner.py 改造：翻页凑额度 + 随机延迟

Phase 2: 同步逻辑
  2.1 sync_to_monitor.py + 单元测试
  2.2 routes/mining.py 新端点 + API 测试
  2.3 集成测试

Phase 3: 前端
  3.1 SyncToMonitorModal.vue 表单组件
  3.2 MiningView 三点菜单 + disabled 逻辑
  3.3 stores/mining.ts: syncToMonitor()
  3.4 toast / 错误处理 UX

Phase 4: 验收 + release
  4.1 dev 手工验收 6 条用例
  4.2 PR + code review
  4.3 版本号 5 处 bump（release.py + frontend/package.json + lockfile + CHANGELOG + Cargo.toml）
  4.4 NSIS 全新机器验收
  4.5 release tag
```

---

## 11. 上线 checklist

参考 v0.5.1 ~ v0.5.8 教训：

- [ ] CHANGELOG.md 加 entry（release.yml 会卡 extract_changelog）
- [ ] 版本号 5 处都改：release.py / CHANGELOG.md / frontend/package.json / frontend/package-lock.json / Cargo.toml
- [ ] `sync_to_monitor.run()` 输出 raw log（避免 silent failure）
- [ ] 不依赖 `input()`（windowed build 限制）
- [ ] 新增数据文件（如有）走 `collect_data_files` 兜底
- [ ] dev 机和全新 Win 机器都跑过 NSIS

---

## 12. 风险与缓解

| 风险 | 缓解 |
|---|---|
| 凑额度翻页触发反爬软封 cookie | MAX_ATTEMPTS_PER_PLATFORM 硬上限 + 2-5s 随机延迟 |
| LIKE 扫 monitor_tasks 性能差 | 加 `idx_monitor_tasks_target_url(type, target_url)` 索引 |
| 正则 `_extract_platform_video_id()` 误判 | 复用现有函数（已经在 production），有 bug 是历史 bug 不是新增 |
| 同步过程中 sidecar crash | 已写入的 monitor_tasks 保留；用户重试只会 skipped_dup，幂等 |
| 同步耗时长 user 误以为卡死 | toast 起 "正在同步..." spinner；后端 < 1s/条 估算 100 条 < 2 分钟 |
| video 数量极大（>1000）一次同步爆内存 | rows 用 fetchall() 一次取——本期视频量预期 < 200 不构成问题；未来分批 |

---

## 13. 未来扩展（不在本期范围）

- 同步弹窗内的视频明细预览 + 反选
- monitor → mining 反向联动（task 删了通知 mining）
- 跨 mining job 的合并同步
- 评论文案的 per-video AI 重写入口（在弹窗内）
- monitor_tasks 命名模板自定义
- 同步动作的撤销 / 批量删除最近同步过的 monitor_tasks
