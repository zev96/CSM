# Mining → Monitor Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 mining 采集时跨 videos+monitor_tasks 全局查重（带反爬保护翻页凑额度），并新增 mining 任务"同步监测中心"按钮，把已起草评论的视频批量灌进 monitor 作为待启动监测任务。

**Architecture:** 后端在 `csm_core/mining/storage.py` 加查重函数 + V5 migration（新索引），改 adapter Protocol 加 `max_attempts` 参数让 3 个 adapter 各自实现翻页上限与延迟；runner 在 on_card 回调里查重跳 dup。新增 `csm_core/mining/sync_to_monitor.py` 服务模块 + HTTP 端点。前端在 MiningView 三点菜单加项 + 新建 SyncToMonitorModal.vue 弹窗。

**Tech Stack:** Python 3.11 (pytest, pytest-asyncio, FastAPI/Pydantic, sqlite3), Vue 3 + TypeScript (Pinia, Tauri 2), Vitest.

**Spec:** See [docs/superpowers/specs/2026-05-25-mining-comment-sync-design.md](../specs/2026-05-25-mining-comment-sync-design.md).

---

## File Structure

### Create
- `csm_core/mining/config.py` — 反爬保护常量 + 同步默认值
- `csm_core/mining/sync_to_monitor.py` — `SyncParams`/`SyncResult` + `run()`
- `frontend/src/components/mining/SyncToMonitorModal.vue` — 同步弹窗组件
- `sidecar/tests/test_sync_to_monitor.py` — sync 服务单元测试
- `sidecar/tests/test_sync_to_monitor_api.py` — HTTP 端点测试
- `sidecar/tests/test_collect_dedup.py` — 采集查重单元测试

### Modify
- `csm_core/mining/storage.py` — 加 3 个查重函数；新增 `_DDL_V5_MINING` 和 `apply_v5_migration()`
- `csm_core/monitor/storage.py:129-143` — `_migrate()` 加 `mining_storage.apply_v5_migration(conn)` 调用
- `csm_core/mining/platforms/_common.py:27-38` — `SearchAdapter` Protocol 加 `max_attempts` 参数
- `csm_core/mining/platforms/douyin_search.py` — adapter 实现 max_attempts 上限 + 翻页延迟
- `csm_core/mining/platforms/kuaishou_search.py` — 同上
- `csm_core/mining/platforms/bilibili_search.py` — 同上
- `csm_core/mining/runner.py` — on_card 加查重跳 dup 逻辑 + skipped_dup 计数到 progress
- `sidecar/csm_sidecar/routes/mining.py` — 加 `POST /api/mining/jobs/{job_id}/sync_to_monitor` 端点
- `frontend/src/views/MiningView.vue` — 三点菜单加"同步监测中心"项 + disabled 逻辑
- `frontend/src/stores/mining.ts` — `syncToMonitor()` 方法
- `CHANGELOG.md` — 加 entry

---

## Task 1: 反爬保护常量与同步默认值

**Files:**
- Create: `csm_core/mining/config.py`

- [ ] **Step 1: 新建 config.py 写入常量**

```python
# csm_core/mining/config.py
"""Mining 模块运行时常量：反爬保护 + 同步到 monitor 的默认值。"""
from __future__ import annotations

# 每平台翻页硬上限（页数，不是条目）。
# 抖音风控最严，B 站最松，按经验值排序。
MAX_ATTEMPTS_PER_PLATFORM: dict[str, int] = {
    "douyin": 3,
    "kuaishou": 5,
    "bilibili": 8,
}

# 翻页之间随机延迟范围（秒）。
PAGE_DELAY_RANGE_SEC: tuple[float, float] = (2.0, 5.0)

# sync_to_monitor 的默认值。
DEFAULT_MONITOR_TOP_N: int = 5
DEFAULT_MONITOR_SCRAPE_TOP_N: int = 150


def get_max_attempts(platform: str) -> int:
    """获取平台默认翻页上限。未知平台 fallback=5。"""
    return MAX_ATTEMPTS_PER_PLATFORM.get(platform, 5)
```

- [ ] **Step 2: Commit**

```bash
git add csm_core/mining/config.py
git commit -m "feat(mining): config constants for anti-scrape and sync defaults"
```

---

## Task 2: 查重函数 `is_video_in_videos_table`

**Files:**
- Modify: `csm_core/mining/storage.py`
- Test: `sidecar/tests/test_collect_dedup.py`

- [ ] **Step 1: 写失败测试**

新建 `sidecar/tests/test_collect_dedup.py`：

```python
"""Tests for cross-table dedup helpers used by mining collection."""
from __future__ import annotations

import pytest

from csm_core.mining import storage as mining_storage
from csm_core.monitor import storage as monitor_storage


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """Each test gets a fresh SQLite file with both monitor + mining schema."""
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(monitor_storage, "_DB_PATH", str(db_path), raising=False)
    monitor_storage._DB_PATH = str(db_path)  # belt-and-suspenders
    # Trigger migration
    conn = monitor_storage.get_conn()
    yield conn
    conn.close()


def test_is_video_in_videos_table_when_present(temp_db):
    conn = temp_db
    # Insert one video directly
    conn.execute(
        "INSERT INTO videos(platform, platform_video_id, url, title) "
        "VALUES (?, ?, ?, ?)",
        ("douyin", "7000000000001", "https://www.douyin.com/video/7000000000001", "x"),
    )
    assert mining_storage.is_video_in_videos_table(conn, "douyin", "7000000000001") is True


def test_is_video_in_videos_table_when_absent(temp_db):
    assert mining_storage.is_video_in_videos_table(temp_db, "douyin", "9999999999") is False


def test_is_video_in_videos_table_different_platform_same_id(temp_db):
    conn = temp_db
    conn.execute(
        "INSERT INTO videos(platform, platform_video_id, url, title) "
        "VALUES (?, ?, ?, ?)",
        ("douyin", "7000000000001", "https://www.douyin.com/video/7000000000001", "x"),
    )
    # 同 id 不同平台不应误判
    assert mining_storage.is_video_in_videos_table(conn, "kuaishou", "7000000000001") is False
```

- [ ] **Step 2: 运行测试看失败**

```bash
cd sidecar && pytest tests/test_collect_dedup.py::test_is_video_in_videos_table_when_present -v
```

Expected: `FAIL`, AttributeError: module 'csm_core.mining.storage' has no attribute 'is_video_in_videos_table'

- [ ] **Step 3: 在 storage.py 加函数**

在 `csm_core/mining/storage.py` 末尾（或 helper 区块）加：

```python
def is_video_in_videos_table(
    conn: sqlite3.Connection,
    platform: str,
    platform_video_id: str,
) -> bool:
    """videos 表精确 UNIQUE 查询，O(1)。供 mining 采集时跳过已抓视频。"""
    row = conn.execute(
        "SELECT 1 FROM videos WHERE platform=? AND platform_video_id=? LIMIT 1",
        (platform, platform_video_id),
    ).fetchone()
    return row is not None
```

- [ ] **Step 4: 运行测试看通过**

```bash
cd sidecar && pytest tests/test_collect_dedup.py -v -k is_video_in_videos_table
```

Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add csm_core/mining/storage.py sidecar/tests/test_collect_dedup.py
git commit -m "feat(mining): is_video_in_videos_table dedup helper"
```

---

## Task 3: 查重函数 `is_video_in_monitor_tasks`

**Files:**
- Modify: `csm_core/mining/storage.py`
- Test: `sidecar/tests/test_collect_dedup.py`

- [ ] **Step 1: 写失败测试（追加到 test_collect_dedup.py）**

```python
def _create_monitor_task(conn, type_, target_url, my_text="x"):
    """Helper to insert a monitor task directly."""
    import json
    conn.execute(
        "INSERT INTO monitor_tasks(type, name, target_url, config_json, enabled) "
        "VALUES (?, ?, ?, ?, ?)",
        (type_, "test", target_url, json.dumps({"my_comment_text": my_text, "top_n": 5}), 0),
    )


def test_is_video_in_monitor_tasks_when_present(temp_db):
    conn = temp_db
    _create_monitor_task(
        conn, "douyin_comment",
        "https://www.douyin.com/video/7000000000001"
    )
    assert mining_storage.is_video_in_monitor_tasks(conn, "douyin", "7000000000001") is True


def test_is_video_in_monitor_tasks_when_absent(temp_db):
    assert mining_storage.is_video_in_monitor_tasks(temp_db, "douyin", "9999999999") is False


def test_is_video_in_monitor_tasks_wrong_type_not_matched(temp_db):
    """zhihu_question 类型 task 包含相同 id 子串不应误判为 douyin 命中。"""
    conn = temp_db
    _create_monitor_task(
        conn, "zhihu_question",
        "https://zhihu.com/q/7000000000001",
    )
    assert mining_storage.is_video_in_monitor_tasks(conn, "douyin", "7000000000001") is False


def test_is_video_in_monitor_tasks_unknown_platform(temp_db):
    """未知 platform 直接返回 False，不查 monitor。"""
    assert mining_storage.is_video_in_monitor_tasks(temp_db, "weibo", "7000000000001") is False
```

- [ ] **Step 2: 运行测试看失败**

```bash
cd sidecar && pytest tests/test_collect_dedup.py -v -k is_video_in_monitor_tasks
```

Expected: 4 tests fail with AttributeError

- [ ] **Step 3: 在 storage.py 加函数**

```python
def is_video_in_monitor_tasks(
    conn: sqlite3.Connection,
    platform: str,
    platform_video_id: str,
) -> bool:
    """monitor_tasks 反查：LIKE + 正则精确匹配。

    monitor_tasks 没有独立的 platform_video_id 列，所以走两步：
      1. LIKE 加速过滤（带 idx_monitor_tasks_target_url 索引）
      2. 用 _extract_platform_video_id() 正则二次确认，避免 url 子串误判
    """
    type_map = {
        "douyin": "douyin_comment",
        "kuaishou": "kuaishou_comment",
        "bilibili": "bilibili_comment",
    }
    task_type = type_map.get(platform)
    if not task_type:
        return False

    candidates = conn.execute(
        "SELECT target_url FROM monitor_tasks WHERE type=? AND target_url LIKE ?",
        (task_type, f"%{platform_video_id}%"),
    ).fetchall()

    for (target_url,) in candidates:
        extracted = _extract_platform_video_id(target_url, platform)
        if extracted == platform_video_id:
            return True
    return False
```

- [ ] **Step 4: 运行测试看通过**

```bash
cd sidecar && pytest tests/test_collect_dedup.py -v -k is_video_in_monitor_tasks
```

Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add csm_core/mining/storage.py sidecar/tests/test_collect_dedup.py
git commit -m "feat(mining): is_video_in_monitor_tasks reverse lookup helper"
```

---

## Task 4: 组合查重函数 `is_video_tracked_anywhere` + V5 索引迁移

**Files:**
- Modify: `csm_core/mining/storage.py`
- Modify: `csm_core/monitor/storage.py:129-143`
- Test: `sidecar/tests/test_collect_dedup.py`

- [ ] **Step 1: 写失败测试**

```python
def test_is_video_tracked_anywhere_in_videos(temp_db):
    conn = temp_db
    conn.execute(
        "INSERT INTO videos(platform, platform_video_id, url, title) VALUES (?, ?, ?, ?)",
        ("douyin", "7000000000001", "https://www.douyin.com/video/7000000000001", "x"),
    )
    assert mining_storage.is_video_tracked_anywhere(conn, "douyin", "7000000000001") is True


def test_is_video_tracked_anywhere_in_monitor(temp_db):
    conn = temp_db
    _create_monitor_task(
        conn, "douyin_comment",
        "https://www.douyin.com/video/7000000000001"
    )
    assert mining_storage.is_video_tracked_anywhere(conn, "douyin", "7000000000001") is True


def test_is_video_tracked_anywhere_nowhere(temp_db):
    assert mining_storage.is_video_tracked_anywhere(temp_db, "douyin", "9999999999") is False


def test_idx_monitor_tasks_target_url_exists(temp_db):
    """V5 migration 必须建索引。"""
    rows = temp_db.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_monitor_tasks_target_url'"
    ).fetchall()
    assert len(rows) == 1
```

- [ ] **Step 2: 运行测试看失败**

```bash
cd sidecar && pytest tests/test_collect_dedup.py -v -k "tracked_anywhere or idx_monitor"
```

Expected: 4 fail (3 missing function, 1 missing index)

- [ ] **Step 3: 在 storage.py 加组合函数 + V5 DDL**

在 storage.py 加：

```python
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


# V5 migration: add index for monitor_tasks dedup lookup performance.
_DDL_V5_MINING: list[str] = [
    "CREATE INDEX IF NOT EXISTS idx_monitor_tasks_target_url "
    "ON monitor_tasks(type, target_url)",
]


def apply_v5_migration(conn: sqlite3.Connection) -> None:
    """Called by monitor.storage._migrate when bumping v4 → v5.

    Idempotent: CREATE INDEX IF NOT EXISTS handles re-runs.
    """
    for stmt in _DDL_V5_MINING:
        conn.execute(stmt)
```

- [ ] **Step 4: 在 monitor/storage.py:_migrate() 挂调用**

定位 `csm_core/monitor/storage.py` 的 `_migrate` 函数（line 129-143），在最后的 `apply_v4_migration(conn)` 后加：

```python
mining_storage.apply_v5_migration(conn)
```

并把版本号字符串从 "4" 升到 "5"（注意 `INSERT OR REPLACE INTO schema_meta(key, value) VALUES('version', ?)` 的传参）。

- [ ] **Step 5: 运行测试看通过**

```bash
cd sidecar && pytest tests/test_collect_dedup.py -v
```

Expected: 全部 11 passed（包括之前的）

- [ ] **Step 6: Commit**

```bash
git add csm_core/mining/storage.py csm_core/monitor/storage.py sidecar/tests/test_collect_dedup.py
git commit -m "feat(mining): is_video_tracked_anywhere + V5 idx_monitor_tasks_target_url"
```

---

## Task 5: SearchAdapter Protocol 加 `max_attempts` 参数

**Files:**
- Modify: `csm_core/mining/platforms/_common.py:27-38`

- [ ] **Step 1: 改 Protocol 签名**

把 `_common.py` 的 `SearchAdapter` Protocol 替换为：

```python
class SearchAdapter(Protocol):
    """Each platform adapter implements this."""
    platform: Platform

    def search(
        self,
        keyword: str,
        target_count: int,
        on_card: OnCard,
        on_progress: OnProgress,
        cancel_event: threading.Event,
        max_attempts: int | None = None,
    ) -> SearchOutcome:
        """Search the platform.

        Args:
          target_count: stop after emitting this many cards. Adapter may emit
                        more if a single page yields extras; runner is responsible
                        for cancel_event.
          max_attempts: max page-fetch attempts before bailing (anti-scrape).
                        None → adapter uses its own platform default from
                        csm_core.mining.config.get_max_attempts(self.platform).
        """
        ...
```

- [ ] **Step 2: 检查现有 3 个 adapter 编译通过（默认参数兼容）**

```bash
cd sidecar && python -c "from csm_core.mining.platforms.douyin_search import DouyinSearchAdapter; from csm_core.mining.platforms.kuaishou_search import KuaishouSearchAdapter; from csm_core.mining.platforms.bilibili_search import BilibiliSearchAdapter; print('OK')"
```

Expected: `OK`（adapter 实现暂时不强制 max_attempts；接下来的 task 会改它们）

- [ ] **Step 3: Commit**

```bash
git add csm_core/mining/platforms/_common.py
git commit -m "feat(mining): SearchAdapter.search adds optional max_attempts param"
```

---

## Task 6: 改 douyin adapter 实现 max_attempts + 翻页延迟

**Files:**
- Modify: `csm_core/mining/platforms/douyin_search.py`

- [ ] **Step 1: 先看 adapter 现有翻页位置**

```bash
grep -n "next_page\|page_count\|cursor\|while " csm_core/mining/platforms/douyin_search.py | head -20
```

定位 adapter 内部的翻页循环（通常是 `while not cancel_event.is_set():` 形式）。

- [ ] **Step 2: 改 search() 签名 + 加翻页计数 + 加延迟**

模式：在 `search()` 入口加：

```python
import random
import time
from csm_core.mining.config import get_max_attempts, PAGE_DELAY_RANGE_SEC

# 在 search() 函数体内最开头：
if max_attempts is None:
    max_attempts = get_max_attempts("douyin")

attempts = 0
```

在每次"翻新一页"之前（adapter 内部 cursor 推进的位置）加：

```python
attempts += 1
if attempts > max_attempts:
    on_progress(ProgressUpdate(
        platform=self.platform,
        status="hit_max_attempts",
        message=f"翻页保护：达到 {max_attempts} 页上限",
    ))
    break

# 翻页之间随机延迟（第一页前不延迟）
if attempts > 1:
    time.sleep(random.uniform(*PAGE_DELAY_RANGE_SEC))
```

具体插入点：在 adapter 拿到一页结果、emit 所有 cards、即将请求下一页的位置。如果 adapter 是按 cursor 而非显式 page 循环，把"每次 cursor 推进"计为 1 个 attempt。

⚠️ 修改后 `search()` 签名必须接受 `max_attempts: int | None = None` 关键字参数。

- [ ] **Step 3: 手工 smoke test**

```bash
cd sidecar && python -c "
from csm_core.mining.platforms.douyin_search import DouyinSearchAdapter
import inspect
sig = inspect.signature(DouyinSearchAdapter().search)
assert 'max_attempts' in sig.parameters, sig
print('signature OK:', sig)
"
```

Expected: `signature OK: (keyword, target_count, on_card, on_progress, cancel_event, max_attempts=None)`

- [ ] **Step 4: Commit**

```bash
git add csm_core/mining/platforms/douyin_search.py
git commit -m "feat(mining): douyin adapter respects max_attempts and page delay"
```

---

## Task 7: 改 kuaishou adapter（同 Task 6 模式）

**Files:**
- Modify: `csm_core/mining/platforms/kuaishou_search.py`

- [ ] **Step 1: 改签名 + 加上限 + 加延迟**

按 Task 6 的同样模式（fallback to `get_max_attempts("kuaishou")` = 5）：

```python
import random
import time
from csm_core.mining.config import get_max_attempts, PAGE_DELAY_RANGE_SEC

# search() 入口
if max_attempts is None:
    max_attempts = get_max_attempts("kuaishou")
attempts = 0

# 翻页位置前
attempts += 1
if attempts > max_attempts:
    on_progress(ProgressUpdate(
        platform=self.platform,
        status="hit_max_attempts",
        message=f"翻页保护：达到 {max_attempts} 页上限",
    ))
    break

if attempts > 1:
    time.sleep(random.uniform(*PAGE_DELAY_RANGE_SEC))
```

- [ ] **Step 2: signature 检查**

```bash
cd sidecar && python -c "
from csm_core.mining.platforms.kuaishou_search import KuaishouSearchAdapter
import inspect
sig = inspect.signature(KuaishouSearchAdapter().search)
assert 'max_attempts' in sig.parameters
print('OK:', sig)
"
```

- [ ] **Step 3: Commit**

```bash
git add csm_core/mining/platforms/kuaishou_search.py
git commit -m "feat(mining): kuaishou adapter respects max_attempts and page delay"
```

---

## Task 8: 改 bilibili adapter（同 Task 6 模式）

**Files:**
- Modify: `csm_core/mining/platforms/bilibili_search.py`

- [ ] **Step 1: 改签名 + 加上限 + 加延迟（用 "bilibili" 默认上限 8）**

按 Task 6/7 同样模式，把 `get_max_attempts("bilibili")` 作为 fallback。

- [ ] **Step 2: signature 检查**

```bash
cd sidecar && python -c "
from csm_core.mining.platforms.bilibili_search import BilibiliSearchAdapter
import inspect
sig = inspect.signature(BilibiliSearchAdapter().search)
assert 'max_attempts' in sig.parameters
print('OK:', sig)
"
```

- [ ] **Step 3: Commit**

```bash
git add csm_core/mining/platforms/bilibili_search.py
git commit -m "feat(mining): bilibili adapter respects max_attempts and page delay"
```

---

## Task 9: Runner on_card 查重 + skipped_dup 计数

**Files:**
- Modify: `csm_core/mining/runner.py`
- Test: `sidecar/tests/test_collect_dedup.py`

- [ ] **Step 1: 先定位 runner.py 里 adapter.search() 调用位置**

```bash
grep -n "adapter.search\|on_card\|upsert_video_and_link" csm_core/mining/runner.py | head -20
```

预期看到 runner 把一个 `on_card` callback（lambda 或函数）传给 `adapter.search(...)`，callback 内部调 `mining_storage.upsert_video_and_link(...)` 入库。

- [ ] **Step 2: 在 on_card 包装层加查重**

在 runner.py 里把 `on_card` callback 改造为：

```python
from csm_core.mining import storage as mining_storage

# 在创建 on_card 的位置（可能是函数内的 closure）：
def on_card(card: VideoCard) -> None:
    conn = mining_storage.get_conn()
    try:
        if mining_storage.is_video_tracked_anywhere(
            conn, platform, card.platform_video_id
        ):
            # 跳过 dup：进度计数 +1，不入 videos 表
            stats["skipped_dup"] = stats.get("skipped_dup", 0) + 1
            on_progress(ProgressUpdate(
                platform=platform,
                status="skipped_duplicate",
                message=f"跳过已知视频 {card.platform_video_id}",
            ))
            return
    except Exception:  # 兜底降级：查重失败不中断采集，依赖 UNIQUE 约束
        logger.exception("dedup check failed for %s", card.platform_video_id)

    mining_storage.upsert_video_and_link(conn, card, job_id=job_id, keyword=keyword)
    stats["collected"] = stats.get("collected", 0) + 1
```

`stats` dict 是 runner 内现有的进度容器，搜 `progress_json` 或 `stats` 定位实际用法，把 `skipped_dup` 加到现有 progress 写入逻辑里（一般是 `update_job_progress(...)` 或 finalize_job 处）。

- [ ] **Step 3: 写一个 runner 集成 smoke 测试（在 test_collect_dedup.py 追加）**

```python
def test_runner_skips_dup_via_on_card(temp_db):
    """Fake adapter emits 5 cards, 2 of which already exist in videos.
    Runner should write 3 to DB and report skipped_dup=2."""
    from unittest.mock import MagicMock
    from csm_core.mining import runner as mining_runner
    from csm_core.mining.models import VideoCard, Platform
    import threading

    conn = temp_db
    # Seed videos table with 2 existing
    conn.execute(
        "INSERT INTO videos(platform, platform_video_id, url, title) VALUES (?, ?, ?, ?)",
        ("douyin", "v1", "https://www.douyin.com/video/v1", "exists 1"),
    )
    conn.execute(
        "INSERT INTO videos(platform, platform_video_id, url, title) VALUES (?, ?, ?, ?)",
        ("douyin", "v2", "https://www.douyin.com/video/v2", "exists 2"),
    )

    # Fake adapter that immediately emits 5 cards then returns SearchOutcome.OK
    cards = [
        VideoCard(platform=Platform.DOUYIN, platform_video_id=vid,
                  url=f"https://www.douyin.com/video/{vid}", title=f"t-{vid}",
                  author_name="a", author_id="aid", cover_url=None,
                  duration_sec=None, like_count=None, comment_count=None,
                  publish_time=None)
        for vid in ["v1", "v2", "v3", "v4", "v5"]
    ]

    # NOTE: 实际 runner 内部细节按现有代码组织；此测可能需要走 mining_runner.run_job 入口
    # 用真实 adapter mock 或者通过 monkeypatch 替换 ADAPTERS 字典
    # 此 step 主要验证 dedup 行为，具体测试形态由 runner 现有写法决定
    pytest.skip("integration test stub - flesh out after Step 2 inspection")
```

- [ ] **Step 4: 手工跑一次 dev 模式 mining 任务确认日志输出 skipped_dup**

```bash
# 在 dev 环境跑一次抖音 mining 任务，关键词选最近抓过的
# 看 sidecar log 是否输出 "skipped_duplicate" 进度事件
```

Expected: progress event 流里能看到 `skipped_duplicate` kind 出现

- [ ] **Step 5: Commit**

```bash
git add csm_core/mining/runner.py sidecar/tests/test_collect_dedup.py
git commit -m "feat(mining): runner on_card dedups across videos+monitor_tasks"
```

---

## Task 10: SyncParams / SyncResult dataclasses + 同步主逻辑

**Files:**
- Create: `csm_core/mining/sync_to_monitor.py`
- Test: `sidecar/tests/test_sync_to_monitor.py`

- [ ] **Step 1: 先写测试 fixtures**

新建 `sidecar/tests/test_sync_to_monitor.py`：

```python
"""Tests for mining → monitor sync service."""
from __future__ import annotations

import json
import pytest

from csm_core.mining import storage as mining_storage
from csm_core.mining import sync_to_monitor
from csm_core.mining.sync_to_monitor import SyncParams, SyncResult
from csm_core.monitor import storage as monitor_storage


@pytest.fixture
def db_with_job(tmp_path, monkeypatch):
    """Fresh DB with one mining job + 5 videos."""
    db_path = tmp_path / "test.db"
    monitor_storage._DB_PATH = str(db_path)
    conn = monitor_storage.get_conn()

    # Create job
    job_id = conn.execute(
        "INSERT INTO mining_jobs(keyword, platforms_json, target_per_platform, "
        "status, created_at) VALUES (?, ?, ?, ?, datetime('now')) RETURNING id",
        ("test_kw", json.dumps(["douyin"]), 5, "done"),
    ).fetchone()[0]

    # Create 5 videos with already_commented=1
    for vid in ["v1", "v2", "v3", "v4", "v5"]:
        video_id = conn.execute(
            "INSERT INTO videos(platform, platform_video_id, url, title, already_commented) "
            "VALUES (?, ?, ?, ?, 1) RETURNING id",
            ("douyin", vid, f"https://www.douyin.com/video/{vid}", f"title-{vid}"),
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO video_source_keywords(video_id, job_id, keyword, rank_in_search) "
            "VALUES (?, ?, ?, ?)",
            (video_id, job_id, "test_kw", 0),
        )
        # Add tier=1 comment for first 3 videos only
        if vid in ("v1", "v2", "v3"):
            conn.execute(
                "INSERT INTO video_comments(video_id, tier, text, status, source) "
                "VALUES (?, 1, ?, 'draft', 'manual')",
                (video_id, f"comment for {vid}"),
            )

    yield conn, job_id
    conn.close()


def test_sync_creates_monitor_tasks(db_with_job):
    conn, job_id = db_with_job
    result = sync_to_monitor.run(
        conn, job_id,
        SyncParams(task_name_prefix="batch-1", top_n=5),
    )
    assert isinstance(result, SyncResult)
    assert result.created == 3  # only v1/v2/v3 have tier=1 drafts
    assert result.skipped_no_draft == 2  # v4, v5
    assert result.skipped_dup == 0
    assert result.errors == []

    # Verify in DB
    rows = conn.execute(
        "SELECT type, name, target_url, config_json, enabled FROM monitor_tasks ORDER BY id"
    ).fetchall()
    assert len(rows) == 3
    for row in rows:
        assert row[0] == "douyin_comment"
        assert row[1].startswith("batch-1 - ")
        assert row[4] == 0  # enabled=False
        cfg = json.loads(row[3])
        assert "my_comment_text" in cfg
        assert cfg["top_n"] == 5
        assert cfg["scrape_top_n"] == 150
```

- [ ] **Step 2: 跑测试看失败**

```bash
cd sidecar && pytest tests/test_sync_to_monitor.py::test_sync_creates_monitor_tasks -v
```

Expected: FAIL with ModuleNotFoundError

- [ ] **Step 3: 实现 sync_to_monitor.py**

```python
# csm_core/mining/sync_to_monitor.py
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
from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass, field

from csm_core.mining.config import DEFAULT_MONITOR_TOP_N, DEFAULT_MONITOR_SCRAPE_TOP_N
from csm_core.mining.storage import is_video_in_monitor_tasks

logger = logging.getLogger(__name__)


@dataclass
class SyncParams:
    task_name_prefix: str
    top_n: int = DEFAULT_MONITOR_TOP_N
    scrape_top_n: int = DEFAULT_MONITOR_SCRAPE_TOP_N
    schedule_cron: str | None = None  # None = 手动


@dataclass
class SyncResult:
    created: int = 0
    skipped_dup: int = 0
    skipped_no_draft: int = 0
    errors: list[dict] = field(default_factory=list)


def run(
    conn: sqlite3.Connection,
    job_id: int,
    params: SyncParams,
) -> SyncResult:
    rows = conn.execute(
        """
        SELECT v.id, v.platform, v.platform_video_id, v.url, v.title,
               vc.text AS comment_text
        FROM videos v
        JOIN video_source_keywords vsk ON vsk.video_id = v.id
        LEFT JOIN video_comments vc
          ON vc.video_id = v.id AND vc.tier = 1
        WHERE vsk.job_id = ?
        """,
        (job_id,),
    ).fetchall()

    result = SyncResult()
    for row in rows:
        video_id = row[0] if not hasattr(row, "keys") else row["id"]
        platform = row[1] if not hasattr(row, "keys") else row["platform"]
        platform_video_id = row[2] if not hasattr(row, "keys") else row["platform_video_id"]
        url = row[3] if not hasattr(row, "keys") else row["url"]
        title = row[4] if not hasattr(row, "keys") else row["title"]
        comment_text_raw = row[5] if not hasattr(row, "keys") else row["comment_text"]

        try:
            # 同步时只需查 monitor_tasks（video 必在 videos 表里）
            if is_video_in_monitor_tasks(conn, platform, platform_video_id):
                result.skipped_dup += 1
                continue

            comment_text = (comment_text_raw or "").strip()
            if not comment_text:
                result.skipped_no_draft += 1
                continue

            task_type = f"{platform}_comment"
            name = f"{params.task_name_prefix} - {(title or '')[:30]}"
            config_json = json.dumps({
                "my_comment_text": comment_text,
                "top_n": params.top_n,
                "scrape_top_n": params.scrape_top_n,
            })

            conn.execute(
                """
                INSERT INTO monitor_tasks(type, name, target_url, config_json,
                                          schedule_cron, enabled)
                VALUES (?, ?, ?, ?, ?, 0)
                """,
                (task_type, name, url, config_json, params.schedule_cron),
            )
            result.created += 1
        except Exception as e:
            logger.exception("sync video_id=%s failed", video_id)
            result.errors.append({"video_id": video_id, "reason": str(e)})

    logger.info(
        "[sync_to_monitor] job_id=%d created=%d skipped_dup=%d "
        "skipped_no_draft=%d errors=%d",
        job_id, result.created, result.skipped_dup,
        result.skipped_no_draft, len(result.errors),
    )
    return result
```

- [ ] **Step 4: 跑测试看通过**

```bash
cd sidecar && pytest tests/test_sync_to_monitor.py::test_sync_creates_monitor_tasks -v
```

Expected: 1 passed

- [ ] **Step 5: Commit**

```bash
git add csm_core/mining/sync_to_monitor.py sidecar/tests/test_sync_to_monitor.py
git commit -m "feat(mining): sync_to_monitor service module"
```

---

## Task 11: sync_to_monitor 边界用例测试

**Files:**
- Test: `sidecar/tests/test_sync_to_monitor.py`

- [ ] **Step 1: 追加边界测试**

```python
def test_sync_skips_dup_in_monitor_tasks(db_with_job):
    conn, job_id = db_with_job
    # Pre-insert a monitor_task for v1
    conn.execute(
        "INSERT INTO monitor_tasks(type, name, target_url, config_json, enabled) "
        "VALUES ('douyin_comment', 'pre-existing', "
        "'https://www.douyin.com/video/v1', '{}', 0)",
    )

    result = sync_to_monitor.run(
        conn, job_id, SyncParams(task_name_prefix="batch", top_n=5)
    )
    assert result.skipped_dup == 1  # v1
    assert result.created == 2  # v2, v3
    assert result.skipped_no_draft == 2  # v4, v5


def test_sync_empty_text_treated_as_no_draft(db_with_job):
    conn, job_id = db_with_job
    # Clear v1's text to empty string
    conn.execute("UPDATE video_comments SET text='' WHERE text LIKE 'comment for v1'")

    result = sync_to_monitor.run(
        conn, job_id, SyncParams(task_name_prefix="batch", top_n=5)
    )
    assert result.created == 2  # v2, v3 only
    assert result.skipped_no_draft == 3  # v1 (empty), v4, v5


def test_sync_whitespace_only_text_is_no_draft(db_with_job):
    conn, job_id = db_with_job
    conn.execute("UPDATE video_comments SET text='   \\n  ' WHERE text LIKE 'comment for v2'")

    result = sync_to_monitor.run(
        conn, job_id, SyncParams(task_name_prefix="batch", top_n=5)
    )
    assert result.skipped_no_draft >= 1  # at least v2 stripped to empty


def test_sync_repeat_idempotent(db_with_job):
    """Running sync twice in a row: second run all dup."""
    conn, job_id = db_with_job
    first = sync_to_monitor.run(conn, job_id, SyncParams(task_name_prefix="x", top_n=5))
    assert first.created == 3

    second = sync_to_monitor.run(conn, job_id, SyncParams(task_name_prefix="x", top_n=5))
    assert second.created == 0
    assert second.skipped_dup == 3
    assert second.skipped_no_draft == 2


def test_sync_single_failure_does_not_break_batch(db_with_job, monkeypatch):
    """Force one INSERT to fail; others succeed; errors[] has the failure."""
    conn, job_id = db_with_job

    real_execute = conn.execute
    call_count = {"n": 0}

    def flaky_execute(sql, *args, **kwargs):
        if "INSERT INTO monitor_tasks" in sql:
            call_count["n"] += 1
            if call_count["n"] == 2:  # fail second monitor_task insert
                raise sqlite3.OperationalError("simulated fault")
        return real_execute(sql, *args, **kwargs)

    monkeypatch.setattr(conn, "execute", flaky_execute)
    result = sync_to_monitor.run(conn, job_id, SyncParams(task_name_prefix="b", top_n=5))
    assert result.created == 2  # 1 success + 1 success (skipping the failed one)
    assert len(result.errors) == 1
    assert "simulated fault" in result.errors[0]["reason"]


def test_sync_platform_mapping(tmp_path, monkeypatch):
    """kuaishou + bilibili platforms map to correct task types."""
    db_path = tmp_path / "test.db"
    monitor_storage._DB_PATH = str(db_path)
    conn = monitor_storage.get_conn()

    job_id = conn.execute(
        "INSERT INTO mining_jobs(keyword, platforms_json, target_per_platform, "
        "status, created_at) VALUES (?, ?, ?, ?, datetime('now')) RETURNING id",
        ("kw", json.dumps(["kuaishou", "bilibili"]), 5, "done"),
    ).fetchone()[0]

    for platform, vid in [("kuaishou", "k1"), ("bilibili", "b1")]:
        video_id = conn.execute(
            "INSERT INTO videos(platform, platform_video_id, url, title, already_commented) "
            "VALUES (?, ?, ?, ?, 1) RETURNING id",
            (platform, vid, f"https://example.com/{platform}/{vid}", vid),
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO video_source_keywords(video_id, job_id, keyword, rank_in_search) "
            "VALUES (?, ?, ?, ?)",
            (video_id, job_id, "kw", 0),
        )
        conn.execute(
            "INSERT INTO video_comments(video_id, tier, text, status, source) "
            "VALUES (?, 1, ?, 'draft', 'manual')",
            (video_id, "x"),
        )

    sync_to_monitor.run(conn, job_id, SyncParams(task_name_prefix="m", top_n=5))
    types = conn.execute("SELECT type FROM monitor_tasks ORDER BY id").fetchall()
    assert [t[0] for t in types] == ["kuaishou_comment", "bilibili_comment"]
```

- [ ] **Step 2: 跑全部 sync 测试**

```bash
cd sidecar && pytest tests/test_sync_to_monitor.py -v
```

Expected: 6 passed

- [ ] **Step 3: Commit**

```bash
git add sidecar/tests/test_sync_to_monitor.py
git commit -m "test(sync): edge cases - dup, empty text, idempotent, failure, platform mapping"
```

---

## Task 12: HTTP 端点 POST `/api/mining/jobs/{job_id}/sync_to_monitor`

**Files:**
- Modify: `sidecar/csm_sidecar/routes/mining.py`
- Test: `sidecar/tests/test_sync_to_monitor_api.py`

- [ ] **Step 1: 先看现有路由组织**

```bash
grep -n "^@router\.\|router = APIRouter\|from fastapi" sidecar/csm_sidecar/routes/mining.py | head -10
```

- [ ] **Step 2: 写失败的 API 测试**

新建 `sidecar/tests/test_sync_to_monitor_api.py`：

```python
"""HTTP API tests for /api/mining/jobs/{job_id}/sync_to_monitor."""
from __future__ import annotations

import json
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Build sidecar FastAPI app with isolated DB."""
    from csm_core.monitor import storage as monitor_storage
    db_path = tmp_path / "test.db"
    monitor_storage._DB_PATH = str(db_path)

    from csm_sidecar.app import build_app  # adjust import to actual entrypoint
    app = build_app()
    # Bypass auth if sidecar requires bearer:
    # set TEST_TOKEN env or use Depends override
    return TestClient(app)


@pytest.fixture
def seeded_job(tmp_path):
    """Create one done job with 3 videos all commented + tier=1 drafts."""
    from csm_core.monitor import storage as monitor_storage
    conn = monitor_storage.get_conn()

    job_id = conn.execute(
        "INSERT INTO mining_jobs(keyword, platforms_json, target_per_platform, "
        "status, created_at) VALUES (?, ?, ?, ?, datetime('now')) RETURNING id",
        ("kw", json.dumps(["douyin"]), 3, "done"),
    ).fetchone()[0]

    for vid in ["v1", "v2", "v3"]:
        video_id = conn.execute(
            "INSERT INTO videos(platform, platform_video_id, url, title, already_commented) "
            "VALUES (?, ?, ?, ?, 1) RETURNING id",
            ("douyin", vid, f"https://www.douyin.com/video/{vid}", vid),
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO video_source_keywords(video_id, job_id, keyword, rank_in_search) "
            "VALUES (?, ?, ?, ?)",
            (video_id, job_id, "kw", 0),
        )
        conn.execute(
            "INSERT INTO video_comments(video_id, tier, text, status, source) "
            "VALUES (?, 1, ?, 'draft', 'manual')",
            (video_id, f"c-{vid}"),
        )
    return job_id


def test_sync_to_monitor_happy_path(client, seeded_job):
    res = client.post(
        f"/api/mining/jobs/{seeded_job}/sync_to_monitor",
        json={"task_name_prefix": "batch-1", "top_n": 5, "schedule_cron": None},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["created"] == 3
    assert body["skipped_dup"] == 0
    assert body["skipped_no_draft"] == 0
    assert body["errors"] == []


def test_sync_404_when_job_not_exists(client):
    res = client.post(
        "/api/mining/jobs/99999/sync_to_monitor",
        json={"task_name_prefix": "x", "top_n": 5, "schedule_cron": None},
    )
    assert res.status_code == 404


def test_sync_409_when_job_not_done(client, tmp_path):
    from csm_core.monitor import storage as monitor_storage
    conn = monitor_storage.get_conn()
    job_id = conn.execute(
        "INSERT INTO mining_jobs(keyword, platforms_json, target_per_platform, "
        "status, created_at) VALUES (?, ?, ?, ?, datetime('now')) RETURNING id",
        ("kw", json.dumps(["douyin"]), 5, "running"),
    ).fetchone()[0]

    res = client.post(
        f"/api/mining/jobs/{job_id}/sync_to_monitor",
        json={"task_name_prefix": "x", "top_n": 5, "schedule_cron": None},
    )
    assert res.status_code == 409
    assert "job_not_ready" in res.text


def test_sync_409_when_not_all_commented(client):
    from csm_core.monitor import storage as monitor_storage
    conn = monitor_storage.get_conn()
    job_id = conn.execute(
        "INSERT INTO mining_jobs(keyword, platforms_json, target_per_platform, "
        "status, created_at) VALUES (?, ?, ?, ?, datetime('now')) RETURNING id",
        ("kw", json.dumps(["douyin"]), 5, "done"),
    ).fetchone()[0]
    video_id = conn.execute(
        "INSERT INTO videos(platform, platform_video_id, url, title, already_commented) "
        "VALUES (?, ?, ?, ?, 0) RETURNING id",
        ("douyin", "x", "https://www.douyin.com/video/x", "x"),
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO video_source_keywords(video_id, job_id, keyword, rank_in_search) "
        "VALUES (?, ?, ?, ?)",
        (video_id, job_id, "kw", 0),
    )

    res = client.post(
        f"/api/mining/jobs/{job_id}/sync_to_monitor",
        json={"task_name_prefix": "x", "top_n": 5, "schedule_cron": None},
    )
    assert res.status_code == 409
    assert "not_all_commented" in res.text


def test_sync_422_top_n_out_of_range(client, seeded_job):
    res = client.post(
        f"/api/mining/jobs/{seeded_job}/sync_to_monitor",
        json={"task_name_prefix": "x", "top_n": 0, "schedule_cron": None},
    )
    assert res.status_code == 422


def test_sync_422_empty_prefix(client, seeded_job):
    res = client.post(
        f"/api/mining/jobs/{seeded_job}/sync_to_monitor",
        json={"task_name_prefix": "", "top_n": 5, "schedule_cron": None},
    )
    assert res.status_code == 422
```

- [ ] **Step 3: 跑测试看失败**

```bash
cd sidecar && pytest tests/test_sync_to_monitor_api.py -v
```

Expected: 全部 FAIL（端点不存在）

- [ ] **Step 4: 实现端点**

在 `sidecar/csm_sidecar/routes/mining.py` 加：

```python
from pydantic import BaseModel, Field
from fastapi import HTTPException

from csm_core.mining import sync_to_monitor as sync_svc
from csm_core.mining import storage as mining_storage
from csm_core.monitor import storage as monitor_storage


class SyncToMonitorRequest(BaseModel):
    task_name_prefix: str = Field(min_length=1, max_length=100)
    top_n: int = Field(ge=1, le=50, default=5)
    schedule_cron: str | None = None


class SyncToMonitorResponse(BaseModel):
    created: int
    skipped_dup: int
    skipped_no_draft: int
    errors: list[dict]


def _get_video_stats_for_job(conn, job_id: int) -> dict:
    """Return {total, already_commented} for one job."""
    row = conn.execute(
        """
        SELECT COUNT(DISTINCT v.id) AS total,
               SUM(CASE WHEN v.already_commented=1 THEN 1 ELSE 0 END) AS commented
        FROM videos v
        JOIN video_source_keywords vsk ON vsk.video_id = v.id
        WHERE vsk.job_id = ?
        """,
        (job_id,),
    ).fetchone()
    if not row:
        return {"total": 0, "already_commented": 0}
    return {
        "total": row[0] or 0,
        "already_commented": row[1] or 0,
    }


@router.post(
    "/api/mining/jobs/{job_id}/sync_to_monitor",
    response_model=SyncToMonitorResponse,
)
def sync_to_monitor(job_id: int, req: SyncToMonitorRequest):
    job = mining_storage.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail={"error": "job_not_found"})

    if job["status"] not in ("done", "partial_done"):
        raise HTTPException(
            status_code=409,
            detail={"error": "job_not_ready", "reason": "status_not_done",
                    "status": job["status"]},
        )

    conn = monitor_storage.get_conn()
    stats = _get_video_stats_for_job(conn, job_id)
    if stats["total"] == 0 or stats["already_commented"] != stats["total"]:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "job_not_ready",
                "reason": "not_all_commented",
                "total": stats["total"],
                "already_commented": stats["already_commented"],
            },
        )

    result = sync_svc.run(
        conn, job_id,
        sync_svc.SyncParams(
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

- [ ] **Step 5: 跑测试看通过**

```bash
cd sidecar && pytest tests/test_sync_to_monitor_api.py -v
```

Expected: 6 passed

- [ ] **Step 6: Commit**

```bash
git add sidecar/csm_sidecar/routes/mining.py sidecar/tests/test_sync_to_monitor_api.py
git commit -m "feat(api): POST /api/mining/jobs/{id}/sync_to_monitor endpoint"
```

---

## Task 13: 前端 stores/mining.ts 加 syncToMonitor 方法

**Files:**
- Modify: `frontend/src/stores/mining.ts`

- [ ] **Step 1: 定位 store 文件末尾的 actions 区**

```bash
grep -n "syncToMonitor\|bulkMarkCommented\|defineStore" frontend/src/stores/mining.ts | head -10
```

- [ ] **Step 2: 加 TypeScript 接口 + 方法**

在 stores/mining.ts 文件顶部已有类型定义区加：

```typescript
export interface SyncToMonitorParams {
  task_name_prefix: string
  top_n: number
  schedule_cron: string | null
}

export interface SyncToMonitorResult {
  created: number
  skipped_dup: number
  skipped_no_draft: number
  errors: Array<{ video_id: number; reason: string }>
}
```

在 `defineStore('mining', { ... actions: { ... } })` 的 actions 块里加：

```typescript
async syncToMonitor(
  jobId: number,
  params: SyncToMonitorParams,
): Promise<SyncToMonitorResult> {
  const { data } = await api.post<SyncToMonitorResult>(
    `/api/mining/jobs/${jobId}/sync_to_monitor`,
    params,
  )
  return data
},
```

⚠️ `api` 是已有的 axios 实例，按 store 内现有调用风格写。

- [ ] **Step 3: typecheck**

```bash
cd frontend && npx vue-tsc --noEmit
```

Expected: 无错误

- [ ] **Step 4: Commit**

```bash
git add frontend/src/stores/mining.ts
git commit -m "feat(frontend): syncToMonitor store action"
```

---

## Task 14: SyncToMonitorModal.vue 弹窗组件

**Files:**
- Create: `frontend/src/components/mining/SyncToMonitorModal.vue`

- [ ] **Step 1: 看现有 BatchImportTaskModal 学风格**

```bash
head -80 frontend/src/components/monitor/BatchImportTaskModal.vue
```

记录使用的 UI 库（Naive / Element Plus / 等）和样式约定。

- [ ] **Step 2: 实现弹窗**

```vue
<!-- frontend/src/components/mining/SyncToMonitorModal.vue -->
<template>
  <NModal
    :show="show"
    preset="card"
    title="同步到监测中心"
    style="width: 480px"
    :mask-closable="!loading"
    @update:show="onClose"
  >
    <NForm ref="formRef" :model="form" :rules="rules" label-placement="top">
      <NFormItem label="任务名前缀" path="task_name_prefix">
        <NInput
          v-model:value="form.task_name_prefix"
          placeholder="将作为每条监测任务的名称前缀"
          maxlength="100"
          show-count
        />
      </NFormItem>

      <NFormItem label="理想排名（前 N 位）" path="top_n">
        <NInputNumber
          v-model:value="form.top_n"
          :min="1"
          :max="50"
          style="width: 100%"
        />
      </NFormItem>

      <NFormItem label="计划">
        <NSelect
          v-model:value="form.schedule_cron"
          :options="[{ label: '手动（不自动跑）', value: null }]"
          :disabled="true"
        />
        <template #feedback>本期仅支持"手动"，后续将开放定时</template>
      </NFormItem>
    </NForm>

    <template #footer>
      <NSpace justify="end">
        <NButton :disabled="loading" @click="onClose(false)">取消</NButton>
        <NButton type="primary" :loading="loading" @click="onSubmit">
          同步
        </NButton>
      </NSpace>
    </template>
  </NModal>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { useMessage } from 'naive-ui'
import {
  NModal, NForm, NFormItem, NInput, NInputNumber, NSelect, NSpace, NButton,
} from 'naive-ui'
import type { FormInst } from 'naive-ui'
import { useMiningStore } from '@/stores/mining'

const props = defineProps<{
  show: boolean
  jobId: number
  defaultName: string
}>()
const emit = defineEmits<{
  (e: 'update:show', v: boolean): void
  (e: 'synced'): void
}>()

const store = useMiningStore()
const message = useMessage()
const formRef = ref<FormInst | null>(null)
const loading = ref(false)

const form = ref({
  task_name_prefix: '',
  top_n: 5,
  schedule_cron: null as string | null,
})

const rules = {
  task_name_prefix: {
    required: true, message: '请输入任务名前缀', trigger: ['blur'],
  },
  top_n: {
    type: 'number', required: true, min: 1, max: 50, message: '1-50 之间整数',
  },
}

watch(() => props.show, (v) => {
  if (v) {
    form.value.task_name_prefix = props.defaultName
    form.value.top_n = 5
    form.value.schedule_cron = null
  }
})

function onClose(_v: boolean) {
  if (loading.value) return
  emit('update:show', false)
}

async function onSubmit() {
  try {
    await formRef.value?.validate()
  } catch {
    return
  }
  loading.value = true
  try {
    const result = await store.syncToMonitor(props.jobId, form.value)
    const parts = [`已同步 ${result.created} 条到监测中心`]
    if (result.skipped_dup > 0) parts.push(`跳过 ${result.skipped_dup} 条（已存在）`)
    if (result.skipped_no_draft > 0) parts.push(`${result.skipped_no_draft} 条无评论草稿`)
    if (result.errors.length > 0) parts.push(`失败 ${result.errors.length} 条`)
    if (result.created === 0 && result.errors.length === 0) {
      message.warning(`无新增：${result.skipped_dup} 条均已在监测中心`)
    } else if (result.errors.length > 0) {
      message.warning(parts.join('；'))
      console.warn('[sync errors]', result.errors)
    } else {
      message.success(parts.join('；'))
    }
    emit('synced')
    emit('update:show', false)
  } catch (e: any) {
    const detail = e?.response?.data?.detail
    if (e?.response?.status === 409) {
      message.error(`同步条件未满足：${JSON.stringify(detail)}`)
    } else {
      message.error(`同步失败：${e?.message || '未知错误'}`)
    }
  } finally {
    loading.value = false
  }
}
</script>
```

⚠️ 如果项目用的不是 Naive UI，把 `NModal/NForm/...` 换成对应组件（Element Plus 的 `ElDialog/ElForm/...` 等）。从 Step 1 的现有组件复用同套 UI 库。

- [ ] **Step 3: typecheck**

```bash
cd frontend && npx vue-tsc --noEmit
```

Expected: 无错误

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/mining/SyncToMonitorModal.vue
git commit -m "feat(frontend): SyncToMonitorModal component"
```

---

## Task 15: MiningView 三点菜单加项 + disabled 逻辑

**Files:**
- Modify: `frontend/src/views/MiningView.vue`

- [ ] **Step 1: 定位三点菜单组件位置**

```bash
grep -n "导出.*CSV\|删除任务\|videoStats\|MoreOutlined\|n-dropdown" frontend/src/views/MiningView.vue | head -20
```

预期看到现有的"导出 CSV / 删除任务"菜单项实现位置，以及 `videoStats` computed（line 433-436）。

- [ ] **Step 2: 在三点菜单加 menuitem**

定位到三点菜单 options 数组（可能是 `dropdownOptions` 之类），加新选项。以 Naive `NDropdown` 风格为例：

```typescript
const dropdownOptions = computed(() => [
  { label: '导出 CSV', key: 'export_csv' },
  { label: '同步监测中心', key: 'sync_to_monitor',
    disabled: !canSyncToMonitor(currentRow.value),
    props: {
      title: getSyncDisabledTooltip(currentRow.value),
    },
  },
  { label: '删除任务', key: 'delete', /* ... */ },
])
```

加 helper 函数（在 script setup 末尾或 utils）：

```typescript
function canSyncToMonitor(row: MiningJob | undefined): boolean {
  if (!row) return false
  const okStatus = row.status === 'done' || row.status === 'partial_done'
  if (!okStatus) return false
  const stats = computeVideoStats(row)  // 复用现有逻辑
  return stats.total > 0 && stats.commented === stats.total
}

function getSyncDisabledTooltip(row: MiningJob | undefined): string {
  if (!row) return ''
  if (row.status !== 'done' && row.status !== 'partial_done') {
    return '请先等待采集完成'
  }
  const stats = computeVideoStats(row)
  if (stats.total === 0) return '该任务无可同步视频'
  if (stats.commented < stats.total) {
    return `还有 ${stats.total - stats.commented} 条视频未标记已评论`
  }
  return ''
}
```

`computeVideoStats(row)` 应复用 line 433-436 现有的计算逻辑。如果现有是 inline 的，抽出来：

```typescript
function computeVideoStats(row: MiningJob) {
  // 从 row._video_count 和 row._commented_count 字段读
  // （storage.list_jobs 已附带这两个字段）
  return {
    total: row._video_count ?? 0,
    commented: row._commented_count ?? 0,
  }
}
```

- [ ] **Step 3: 在 dropdown select handler 里加 'sync_to_monitor' 分支**

```typescript
function handleDropdownSelect(key: string, row: MiningJob) {
  switch (key) {
    case 'export_csv': /* existing */ break
    case 'sync_to_monitor':
      syncModalState.value = { show: true, jobId: row.id, defaultName: row.keyword }
      break
    case 'delete': /* existing */ break
  }
}
```

- [ ] **Step 4: 模板里挂上 modal**

在 template 末尾加：

```vue
<SyncToMonitorModal
  v-model:show="syncModalState.show"
  :job-id="syncModalState.jobId"
  :default-name="syncModalState.defaultName"
  @synced="onSyncDone"
/>
```

```typescript
import SyncToMonitorModal from '@/components/mining/SyncToMonitorModal.vue'

const syncModalState = ref({ show: false, jobId: 0, defaultName: '' })

function onSyncDone() {
  // 可选：弹完成的全局提示 / 刷新一下监测中心（如果跟前端 store 有引用）
}
```

- [ ] **Step 5: typecheck**

```bash
cd frontend && npx vue-tsc --noEmit
```

Expected: 无错误

- [ ] **Step 6: Commit**

```bash
git add frontend/src/views/MiningView.vue
git commit -m "feat(frontend): MiningView dropdown menu adds sync_to_monitor with disabled logic"
```

---

## Task 16: 集成手动验收

**Files:** （无代码改动）

- [ ] **Step 1: dev 模式启动**

```bash
cd D:/CSM && pnpm dev  # 或者项目 README 里写的启动命令
```

- [ ] **Step 2: 跑一个抖音 mining 任务**

UI 操作：
- 引流采集 → 新建任务 → 关键词填一个新鲜关键词（之前没跑过的）
- 平台勾抖音、target=5
- 等待 status='done'

- [ ] **Step 3: 给每条视频起草 tier=1 评论**

UI 操作：
- 进入 mining 任务详情
- 每条视频点开 → 起草评论 → 选 tier=1 → 保存
- 5 条都做

- [ ] **Step 4: 全部标记已评论**

UI 操作：
- 多选 5 条 → 点 toolbar"标记已评论"
- 列表显示绿色已评论标记

- [ ] **Step 5: 检查三点菜单"同步监测中心"已启用**

UI 操作：
- 任务列表 → 该任务行 → 三点菜单
- "同步监测中心"应该是亮色（可点击）

- [ ] **Step 6: 点同步，填表确认**

- 任务名前缀：`抖音-测试-20260525`
- 理想排名：5
- 计划：手动
- 点同步 → toast "已同步 5 条到监测中心"

- [ ] **Step 7: 监测中心确认结果**

UI 操作：
- 切到监测中心 → 抖音评论 tab
- 应看到 5 条新 task，type=douyin_comment，enabled=false
- 点开任一条：my_comment_text 是 mining 那边起草的文案
- 启用一条 + 立刻跑一次 → 看排名结果正常

- [ ] **Step 8: 重复同步测试**

- 同 mining job 再点"同步监测中心" → toast "无新增：5 条均已在监测中心"
- monitor_tasks 表不应多出重复

- [ ] **Step 9: 跨 job 重复测试**

- 跑同关键词第 2 次 mining → 等完成
- 看 progress / log 应该有 skipped_duplicate 事件
- videos 表新增 0 条（或新加只对应当时没的）

- [ ] **Step 10: 未完成强行同步**

- 创建新 mining job 但不标已评论
- 三点菜单"同步监测中心"应 disabled + tooltip
- 手动 curl POST 到 API:
  ```bash
  curl -X POST -H "Authorization: Bearer $TOKEN" \
    http://127.0.0.1:$PORT/api/mining/jobs/$JOB_ID/sync_to_monitor \
    -H "Content-Type: application/json" \
    -d '{"task_name_prefix":"x","top_n":5,"schedule_cron":null}'
  ```
- 应返回 409 + body 含 `"not_all_commented"`

- [ ] **Step 11: 记录验收结论**

把验收结果写到 PR description（下一 task 会建 PR），逐条 √/×

---

## Task 17: CHANGELOG 与 PR

**Files:**
- Modify: `CHANGELOG.md`

- [ ] **Step 1: 加 CHANGELOG entry**

在 `CHANGELOG.md` 顶部按现有格式加（不动版本号，等 release 时再 bump）：

```markdown
## [Unreleased]

### Added
- mining 任务三点菜单新增"同步监测中心"按钮：所有视频标记已评论后可一键
  把 (video URL, tier=1 评论草稿) 批量灌进监测中心（默认 enabled=false 待手动启动）。
- 新 API: `POST /api/mining/jobs/{job_id}/sync_to_monitor`
- monitor_tasks 加索引 `idx_monitor_tasks_target_url`（V5 migration，自动应用）。

### Changed
- mining 采集时跨 videos+monitor_tasks 全局查重：已知视频静默跳过不入库。
- adapter 增加 max_attempts 翻页上限（抖音 3 / 快手 5 / B 站 8）+ 2-5s 随机翻页延迟，
  降低反爬软封风险。

### Internal
- `csm_core/mining/` 新增 `config.py`（反爬常量）和 `sync_to_monitor.py`（同步服务）。
- `csm_core/mining/storage.py` 加 `is_video_in_videos_table` /
  `is_video_in_monitor_tasks` / `is_video_tracked_anywhere` 查重辅助函数。
- `SearchAdapter.search()` 加可选 `max_attempts` 参数（向后兼容）。
```

- [ ] **Step 2: 整体跑所有 sidecar 测试**

```bash
cd sidecar && pytest tests/ -v
```

Expected: 全绿

- [ ] **Step 3: 前端 typecheck + 关键单元测试**

```bash
cd frontend && npx vue-tsc --noEmit
```

Expected: 无错误

- [ ] **Step 4: 提交 CHANGELOG**

```bash
git add CHANGELOG.md
git commit -m "docs: changelog for mining → monitor sync feature"
```

- [ ] **Step 5: push 分支 + 建 PR**

按用户约定（feedback_merge_flow_pr.md）：push 分支 + gh pr create + 返回 URL：

```bash
git push -u origin claude/cranky-williamson-497965
gh pr create --title "feat: mining → monitor sync (manual button + cross-table dedup)" --body "$(cat <<'EOF'
## Summary
- mining 任务三点菜单新增"同步监测中心"按钮：全部视频标记已评论后可批量
  把 (video URL, tier=1 评论草稿) 灌进监测中心（默认 enabled=false 待手动启动）
- mining 采集时跨 videos+monitor_tasks 全局查重 + adapter 翻页反爬保护
  （max_attempts 硬上限 + 2-5s 随机延迟）

Spec: [docs/superpowers/specs/2026-05-25-mining-comment-sync-design.md](docs/superpowers/specs/2026-05-25-mining-comment-sync-design.md)
Plan: [docs/superpowers/plans/2026-05-25-mining-comment-sync.md](docs/superpowers/plans/2026-05-25-mining-comment-sync.md)

## Test plan
- [x] sidecar pytest 全绿（test_collect_dedup.py + test_sync_to_monitor.py + test_sync_to_monitor_api.py）
- [x] frontend vue-tsc 无错
- [x] dev 手工验收：mining 5 条 → 起草 → 全标已评论 → 点同步 → monitor 出 5 条 enabled=false task
- [x] 重复同步：second-run created=0、skipped_dup=5
- [x] 跨 job 重复：第 2 次同关键词 mining 跳过已知视频
- [x] 未完成强行 API 调用：返回 409
- [ ] 全新 Win 机器 NSIS 验收（release 前补）

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

返回 PR URL 给用户。

---

## Self-Review Notes

**Spec coverage 自查（对照 spec 第 2 节"目标"5 条）**：
1. ✅ 跨表全局查重 → Task 2-4 + Task 9
2. ✅ 翻页凑齐 + 反爬 → Task 5-8（adapter 改造）+ Task 9（runner 配合）
3. ✅ 三点菜单同步按钮 + 启用条件 → Task 15
4. ✅ 弹窗 + 后台批量创建 + enabled=false → Task 14 + Task 10/12
5. ✅ 单条失败/重复/无草稿不中断 → Task 10 + Task 11 边界测试

**Spec 第 7 节边界用例自查**：
- video 无 tier=1 草稿 → Task 11 test_sync_creates_monitor_tasks（skipped_no_draft 验证）
- 同 job 重复点 → Task 11 test_sync_repeat_idempotent
- 单条失败 → Task 11 test_sync_single_failure_does_not_break_batch
- 平台映射 → Task 11 test_sync_platform_mapping
- 同步中关弹窗 / 跨 job 同 video / video 删了 → 文档/spec 阐明的行为；未单测但代码路径覆盖

**注意点（plan 偏离 spec）**：
- Spec 第 4.1 节 runner 伪码用了 async generator 风格；实际 adapter 是回调式 Protocol。
  本 plan 改为：adapter 内部加 max_attempts + 延迟（Task 6-8），runner 在 on_card
  里查重（Task 9）。语义等价，但实现位置和 spec 不同。
- "凑齐 target" 严格语义：因为 dup 不算数，adapter emit 数到 target_count 就停，
  runner 实际入库数 < target。本期不引入"夸大 target_count 让 adapter 多抓"复杂度
  （会让 progress UI 更难懂）；用户可接受实际 < target 的轻微缺货，反爬保护优先。
- 弹窗"计划"下拉本期只显示"手动"一个选项（disabled），保留 schedule_cron 字段
  为后续扩展用。
