# Stream A — 监控「平台评论」进度条 + 提速 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Commits:** follow repo convention (Chinese `feat:`/`fix:` subject) and end every commit message with the trailer `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.

**Goal:** 让监控「平台评论」(bilibili/douyin/kuaishou_comment) 在抓取时真正推送进度事件、前端显示进度条，并把抓取条数与请求节流做成可调（默认保守防软封）。

**Architecture:** 进度 SSE 管线已存在（`monitor_loop._run_one` 已把 `progress_cb` 传给适配器、已发 `MonitorEvent(kind="progress")`）；三个评论适配器目前用 `**_kwargs` 吞掉 `progress_cb` 从不调用 —— 本流让它们在翻页循环里调用 `progress_cb(已抓评论数, 目标条数)`，并把抓取上限改为读 `task.config.scrape_top_n`（默认 150）。提速「可调档」靠把 sidecar 启动时缺失的 `configure_pacing`/`configure_concurrency` 接线补上，让既有 `MonitorConfig.request_delay_min/max` + `concurrency_per_platform` 对评论平台真正生效。前端给 `CommentMonitorModule.vue` 加 `ProgressBar`（读 `monitorStatus.progressOf`，镜像 `ZhihuSearchModule`）。

**Tech Stack:** Python (csm_core 适配器 + csm_sidecar)、pytest、Vue 3 `<script setup>` + Pinia (`monitorStatus`)。

---

## File Structure

| 文件 | 责任 | 改动 |
|---|---|---|
| `csm_core/monitor/platforms/_comment_common.py` | 三评论适配器共享：结果构造 + 进度上报 helper | 加 `ProgressCb` 类型 + `report_progress()` |
| `csm_core/monitor/platforms/bilibili_comment.py` | B 站评论抓取 | `fetch`/`_fetch_comments_by_mode` 接 `progress_cb` + 用 `scrape_top_n` 当 limit |
| `csm_core/monitor/platforms/douyin_comment.py` | 抖音评论抓取 | 同上（`_fetch_comments`）|
| `csm_core/monitor/platforms/kuaishou_comment.py` | 快手评论抓取 | 同上（`_fetch_comments`）|
| `sidecar/csm_sidecar/services/monitor_lifecycle.py` | 启动/重配时把设置推进适配器 | `_apply_runtime_settings` 补评论平台的 pacing/concurrency 接线 |
| `frontend/src/components/monitor/CommentMonitorModule.vue` | 平台评论 UI（L1 批次/L2 视频/L3 详情）| L2 视频行 + L3 详情加 `ProgressBar` |
| `tests/core/monitor/test_comment_progress.py` | 新增：进度 + scrape_top_n 单测 | 新建 |
| `tests/core/monitor/test_comment_common.py` | 既有 | 加 `report_progress` 单测 |
| `sidecar/tests/test_monitor_lifecycle_pacing.py` | 新增：pacing 接线单测 | 新建 |

---

## Task 1: `report_progress` helper + `ProgressCb` 类型

**Files:**
- Modify: `csm_core/monitor/platforms/_comment_common.py`
- Test: `tests/core/monitor/test_comment_common.py`

- [ ] **Step 1: 写失败测试**

追加到 `tests/core/monitor/test_comment_common.py` 末尾：

```python
def test_report_progress_noop_when_cb_none():
    from csm_core.monitor.platforms._comment_common import report_progress
    # None cb 不应抛错
    report_progress(None, 3, 10)


def test_report_progress_forwards_current_total():
    from csm_core.monitor.platforms._comment_common import report_progress
    calls = []
    report_progress(lambda c, t: calls.append((c, t)), 5, 150)
    assert calls == [(5, 150)]


def test_report_progress_swallows_cb_exception():
    from csm_core.monitor.platforms._comment_common import report_progress

    def boom(c, t):
        raise RuntimeError("sink down")

    # 上报失败绝不能打断抓取
    report_progress(boom, 1, 2)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/core/monitor/test_comment_common.py -k report_progress -v`
Expected: FAIL — `ImportError: cannot import name 'report_progress'`

- [ ] **Step 3: 实现 helper**

在 `csm_core/monitor/platforms/_comment_common.py` 顶部 import 区（`from typing import Any` 那行）改为带 `Callable`，并在 `DEFAULT_SCRAPE_TOP_N = 150` 之后加：

```python
from typing import Any, Callable

# 进度回调签名：progress_cb(已抓条数, 目标条数)。monitor_loop._run_one
# 注入的 _progress_cb 就是这个形状（它内部已 try/except 发 SSE 事件）。
ProgressCb = Callable[[int, int], None]


def report_progress(progress_cb: "ProgressCb | None", current: int, total: int) -> None:
    """安全调用进度回调：None 直接跳过；回调抛错只记 debug 不上抛。

    抓取主流程绝不能因为「发个进度事件失败」而中断 —— SSE 队列满 / 客户端
    断开都可能让 cb 抛错。"""
    if progress_cb is None:
        return
    try:
        progress_cb(int(current), int(total))
    except Exception:
        logger.debug("progress_cb raised; ignoring", exc_info=True)
```

（注意：`logger` 在该文件已定义；`Any` 原 import 行替换为 `Any, Callable`。）

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/core/monitor/test_comment_common.py -k report_progress -v`
Expected: PASS (3 passed)

- [ ] **Step 5: 提交**

```bash
git add csm_core/monitor/platforms/_comment_common.py tests/core/monitor/test_comment_common.py
git commit -m "feat(monitor): 评论适配器进度上报 helper report_progress"
```

---

## Task 2: Bilibili 适配器接进度 + scrape_top_n 抓取上限

**Files:**
- Modify: `csm_core/monitor/platforms/bilibili_comment.py`
- Test: `tests/core/monitor/test_comment_progress.py` (新建)

- [ ] **Step 1: 写失败测试**

新建 `tests/core/monitor/test_comment_progress.py`：

```python
"""三评论适配器的翻页进度上报 + scrape_top_n 抓取上限。

锁定行为：适配器每抓完一页应调用 progress_cb(已抓数, 目标数)，序列单调
不减；fetch() 把 task.config.scrape_top_n 当抓取上限传给翻页函数。
"""
from __future__ import annotations

from unittest.mock import MagicMock

from csm_core.monitor.platforms.bilibili_comment import BilibiliCommentAdapter


def _bili_page(replies, *, is_end, next_cursor=0):
    resp = MagicMock()
    resp.status_code = 200
    resp.text = "{}"
    resp.json.return_value = {
        "code": 0,
        "data": {
            "replies": [
                {"content": {"message": m}, "member": {"uname": "u"}, "like": 1}
                for m in replies
            ],
            "cursor": {"is_end": is_end, "next": next_cursor},
        },
    }
    return resp


def _bili_adapter():
    a = BilibiliCommentAdapter()
    a._pacer.wait = lambda: None
    return a


def test_bilibili_fetch_reports_progress_per_page():
    sess = MagicMock()
    sess.get.side_effect = [
        _bili_page(["a", "b"], is_end=False, next_cursor=10),
        _bili_page(["c"], is_end=True),
    ]
    calls = []
    a = _bili_adapter()
    comments, ok, err = a._fetch_comments_by_mode(
        sess, "123", mode=2, limit=150,
        progress_cb=lambda c, t: calls.append((c, t)),
    )
    assert ok is True
    assert [c["text"] for c in comments] == ["a", "b", "c"]
    # 每页一次，current 单调递增，total 恒为 limit
    assert calls == [(2, 150), (3, 150)]


def test_bilibili_fetch_uses_scrape_top_n_as_limit(monkeypatch):
    """fetch() 应把 task.config.scrape_top_n 当抓取上限。"""
    from csm_core.monitor.base import MonitorTask

    a = _bili_adapter()
    captured = {}

    def fake_fetch_mode(session, aid, mode, limit, cancel_token=None, progress_cb=None):
        captured["limit"] = limit
        return [], True, None

    monkeypatch.setattr(a, "_resolve_aid", lambda *x, **k: "999")
    monkeypatch.setattr(a, "_fetch_comments_by_mode", fake_fetch_mode)
    # curl_cffi import + cookie pick 走真实路径但不发请求（fake_fetch_mode 截胡）
    task = MonitorTask(
        id=1, type="bilibili_comment", name="t",
        target_url="https://www.bilibili.com/video/BV1xx",
        config={"my_comment_text": "hi", "scrape_top_n": 40},
    )
    a.fetch(task, progress_cb=None)
    assert captured["limit"] == 40
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/core/monitor/test_comment_progress.py -k bilibili -v`
Expected: FAIL — `TypeError: _fetch_comments_by_mode() got an unexpected keyword argument 'progress_cb'`

- [ ] **Step 3: 实现**

在 `bilibili_comment.py`：

(a) import 行加 helper + 默认值（第 23 行）：

```python
from ._comment_common import (
    build_match_result, fail_result, risk_control_result,
    DEFAULT_SCRAPE_TOP_N, ProgressCb, report_progress,
)
```

(b) `fetch` 签名加 `progress_cb`（第 46-51 行）：

```python
    def fetch(
        self,
        task: MonitorTask,
        cancel_token: threading.Event | None = None,
        progress_cb: "ProgressCb | None" = None,
        **_kwargs,
    ) -> MonitorResult:
```

(c) 抓取调用处（第 105-107 行）改成读 scrape_top_n 当 limit + 传 progress_cb：

```python
        scrape_top_n = int(task.config.get("scrape_top_n") or DEFAULT_SCRAPE_TOP_N)
        hot, ok, err = self._fetch_comments_by_mode(
            session, aid, mode=3, limit=scrape_top_n,
            cancel_token=cancel_token, progress_cb=progress_cb,
        )
```

(d) `_fetch_comments_by_mode` 签名加 `progress_cb`（第 140-147 行）：

```python
    def _fetch_comments_by_mode(
        self,
        session: Any,
        aid: str,
        mode: int,
        limit: int,
        cancel_token: threading.Event | None = None,
        progress_cb: "ProgressCb | None" = None,
    ) -> tuple[list[dict[str, Any]], bool, str | None]:
```

(e) 在该函数翻页循环里、`cursor = body.get("cursor") or {}` 之前（约第 202 行，`for reply in ...` 块之后）加一行进度上报：

```python
            for reply in body.get("replies") or []:
                if not self._append_comment(all_comments, reply, limit):
                    break

            report_progress(progress_cb, len(all_comments), limit)

            cursor = body.get("cursor") or {}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/core/monitor/test_comment_progress.py -k bilibili -v`
Expected: PASS (2 passed)

- [ ] **Step 5: 跑既有 B 站测试防回归**

Run: `python -m pytest tests/core/monitor -k bilibili -v`
Expected: PASS（既有用例不受影响）

- [ ] **Step 6: 提交**

```bash
git add csm_core/monitor/platforms/bilibili_comment.py tests/core/monitor/test_comment_progress.py
git commit -m "feat(monitor): B站评论适配器翻页进度上报 + scrape_top_n 抓取上限"
```

---

## Task 3: Douyin 适配器接进度 + scrape_top_n

**Files:**
- Modify: `csm_core/monitor/platforms/douyin_comment.py`
- Test: `tests/core/monitor/test_comment_progress.py`

- [ ] **Step 1: 写失败测试**

追加到 `tests/core/monitor/test_comment_progress.py`：

```python
from csm_core.monitor.platforms.douyin_comment import DouyinCommentAdapter


def _douyin_page(texts, *, has_more, cursor=0):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "comments": [
            {"text": t, "user": {"nickname": "n"}, "digg_count": 1} for t in texts
        ],
        "has_more": has_more,
        "cursor": cursor,
    }
    return resp


def _douyin_adapter():
    a = DouyinCommentAdapter()
    a._pacer.wait = lambda: None
    return a


def test_douyin_fetch_reports_progress_per_page():
    sess = MagicMock()
    sess.get.side_effect = [
        _douyin_page(["a", "b"], has_more=1, cursor=20),
        _douyin_page(["c"], has_more=0),
    ]
    calls = []
    a = _douyin_adapter()
    comments, ok, err = a._fetch_comments(
        sess, "7xxx", limit=150,
        progress_cb=lambda c, t: calls.append((c, t)),
    )
    assert ok is True
    assert [c["text"] for c in comments] == ["a", "b", "c"]
    assert calls == [(2, 150), (3, 150)]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/core/monitor/test_comment_progress.py -k douyin -v`
Expected: FAIL — `TypeError: _fetch_comments() got an unexpected keyword argument 'progress_cb'`

- [ ] **Step 3: 实现**

在 `douyin_comment.py`：

(a) import（第 30 行）：

```python
from ._comment_common import (
    build_match_result, fail_result, risk_control_result,
    DEFAULT_SCRAPE_TOP_N, ProgressCb, report_progress,
)
```

(b) `fetch` 签名加 `progress_cb`（第 56-61 行）：

```python
    def fetch(
        self,
        task: MonitorTask,
        cancel_token: threading.Event | None = None,
        progress_cb: "ProgressCb | None" = None,
        **_kwargs,
    ) -> MonitorResult:
```

(c) 抓取调用处（第 97-100 行）：

```python
        self._pacer.wait()
        scrape_top_n = int(task.config.get("scrape_top_n") or DEFAULT_SCRAPE_TOP_N)
        comments, ok, err = self._fetch_comments(
            session, aweme_id, limit=scrape_top_n,
            cancel_token=cancel_token, progress_cb=progress_cb,
        )
```

(d) `_fetch_comments` 签名（第 142-148 行）：

```python
    def _fetch_comments(
        self,
        session: Any,
        aweme_id: str,
        limit: int,
        cancel_token: threading.Event | None = None,
        progress_cb: "ProgressCb | None" = None,
    ) -> tuple[list[dict[str, Any]], bool, str | None]:
```

(e) 在 append 块之后、`if data.get("has_more") != 1:` 之前（约第 202-203 行）加：

```python
            for c in data.get("comments") or []:
                if len(all_comments) >= limit:
                    break
                text = c.get("text") or ""
                if not text:
                    continue
                all_comments.append({
                    "rank": len(all_comments) + 1,
                    "text": text,
                    "author": (c.get("user") or {}).get("nickname", ""),
                    "likes": int(c.get("digg_count") or 0),
                })

            report_progress(progress_cb, len(all_comments), limit)

            if data.get("has_more") != 1:
                break
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/core/monitor/test_comment_progress.py -k douyin -v`
Expected: PASS (1 passed)

- [ ] **Step 5: 提交**

```bash
git add csm_core/monitor/platforms/douyin_comment.py tests/core/monitor/test_comment_progress.py
git commit -m "feat(monitor): 抖音评论适配器翻页进度上报 + scrape_top_n 抓取上限"
```

---

## Task 4: Kuaishou 适配器接进度 + scrape_top_n

**Files:**
- Modify: `csm_core/monitor/platforms/kuaishou_comment.py`
- Test: `tests/core/monitor/test_comment_progress.py`

- [ ] **Step 1: 写失败测试**

追加到 `tests/core/monitor/test_comment_progress.py`（复用快手 GraphQL 响应形状）：

```python
from csm_core.monitor.platforms.kuaishou_comment import KuaishouCommentAdapter


def _ks_page(texts, *, pcursor_v2):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "data": {
            "visionCommentList": {
                "rootCommentsV2": [
                    {"commentId": f"c{i}", "content": t, "authorName": "a", "likedCount": 0}
                    for i, t in enumerate(texts)
                ],
                "rootComments": [],
                "pcursorV2": pcursor_v2,
                "pcursor": "no_more",
            }
        }
    }
    return resp


def _ks_adapter():
    a = KuaishouCommentAdapter()
    a._pacer.wait = lambda: None
    return a


def test_kuaishou_fetch_reports_progress_per_page():
    sess = MagicMock()
    sess.post.side_effect = [
        _ks_page(["a", "b"], pcursor_v2="next"),
        _ks_page(["c"], pcursor_v2="no_more"),
    ]
    calls = []
    a = _ks_adapter()
    comments, ok, err = a._fetch_comments(
        sess, "photo1", limit=150,
        progress_cb=lambda c, t: calls.append((c, t)),
    )
    assert ok is True
    assert [c["text"] for c in comments] == ["a", "b", "c"]
    assert calls == [(2, 150), (3, 150)]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/core/monitor/test_comment_progress.py -k kuaishou -v`
Expected: FAIL — `TypeError: _fetch_comments() got an unexpected keyword argument 'progress_cb'`

- [ ] **Step 3: 实现**

在 `kuaishou_comment.py`：

(a) import（第 24 行）：

```python
from ._comment_common import (
    build_match_result, fail_result, risk_control_result,
    DEFAULT_SCRAPE_TOP_N, ProgressCb, report_progress,
)
```

(b) `fetch` 签名加 `progress_cb`（第 99-104 行）：

```python
    def fetch(
        self,
        task: MonitorTask,
        cancel_token: threading.Event | None = None,
        progress_cb: "ProgressCb | None" = None,
        **_kwargs,
    ) -> MonitorResult:
```

(c) 抓取调用处（第 142-145 行）：

```python
        self._pacer.wait()
        scrape_top_n = int(task.config.get("scrape_top_n") or DEFAULT_SCRAPE_TOP_N)
        comments, ok, err = self._fetch_comments(
            session, photo_id, limit=scrape_top_n,
            cancel_token=cancel_token, progress_cb=progress_cb,
        )
```

(d) `_fetch_comments` 签名（第 207-213 行）：

```python
    def _fetch_comments(
        self,
        session: Any,
        photo_id: str,
        limit: int,
        cancel_token: threading.Event | None = None,
        progress_cb: "ProgressCb | None" = None,
    ) -> tuple[list[dict[str, Any]], bool, str | None]:
```

(e) 在 `for c in roots:` append 块之后、`new_pcursor = ...` 之前（约第 266-267 行）加：

```python
            for c in roots:
                if len(all_comments) >= limit:
                    break
                text = c.get("content") or ""
                if not text:
                    continue
                all_comments.append({
                    "rank": len(all_comments) + 1,
                    "text": text,
                    "author": c.get("authorName") or "",
                    "likes": int(c.get("likedCount") or 0),
                })

            report_progress(progress_cb, len(all_comments), limit)

            new_pcursor = (
                vision.get("pcursorV2") if roots_v2 else vision.get("pcursor")
            ) or ""
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/core/monitor/test_comment_progress.py -v`
Expected: PASS（B 站 / 抖音 / 快手全部 progress 用例通过）

- [ ] **Step 5: 跑既有快手测试防回归**

Run: `python -m pytest tests/core/monitor/test_kuaishou_comment.py -v`
Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add csm_core/monitor/platforms/kuaishou_comment.py tests/core/monitor/test_comment_progress.py
git commit -m "feat(monitor): 快手评论适配器翻页进度上报 + scrape_top_n 抓取上限"
```

---

## Task 5: 接通评论平台的 pacing / concurrency 可调档

**Files:**
- Modify: `sidecar/csm_sidecar/services/monitor_lifecycle.py:28-69` (`_apply_runtime_settings`)
- Test: `sidecar/tests/test_monitor_lifecycle_pacing.py` (新建)

**背景:** 旧 PyQt 栈 `monitor_controller.py` 会 `configure_pacing`/`configure_concurrency`，但 sidecar 的 `_apply_runtime_settings` 只配了 browser/zhihu/baidu —— 评论平台的 `RequestPacer` 一直用默认 5–15s、并发 2，`MonitorConfig.request_delay_min/max` + `concurrency_per_platform` 对评论平台等于失效。补上接线＝用户在设置里改这几个值就能调速（默认不变＝保守）。

- [ ] **Step 1: 写失败测试**

新建 `sidecar/tests/test_monitor_lifecycle_pacing.py`：

```python
"""锁定：_apply_runtime_settings 把 MonitorConfig 的 pacing/concurrency
推进评论平台的全局 pacer（之前只配了 baidu/zhihu）。"""
from __future__ import annotations

from csm_core.config import AppConfig
from csm_core.monitor.rate_limit import get_pacer
from csm_sidecar.services import monitor_lifecycle


def test_apply_runtime_settings_configures_comment_pacing():
    cfg = AppConfig()
    cfg.monitor.request_delay_min = 2.0
    cfg.monitor.request_delay_max = 4.0

    monitor_lifecycle._apply_runtime_settings(cfg)

    for platform in ("bilibili_comment", "douyin_comment", "kuaishou_comment"):
        pacer = get_pacer(platform)
        assert pacer.delay_min == 2.0, platform
        assert pacer.delay_max == 4.0, platform
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest sidecar/tests/test_monitor_lifecycle_pacing.py -v`
Expected: FAIL — `assert 5.0 == 2.0`（默认值未被覆盖）

- [ ] **Step 3: 实现**

在 `monitor_lifecycle.py` 顶部 import 区加：

```python
from csm_core.monitor.rate_limit import configure_pacing, configure_concurrency
```

并在 `_apply_runtime_settings` 末尾（`BAIDU_ADAPTER.apply_settings` 的 try/except 之后）加：

```python
    # 评论平台（bilibili/douyin/kuaishou_comment）没有 apply_settings —— 它们
    # 用全局 pacer/semaphore。这里把 MonitorConfig 的节流/并发推进去，
    # 让设置页的「请求间隔」「每平台并发」对评论平台真正生效（默认 5-15s /
    # 并发 2 保持不变，防软封）。
    for platform in ("bilibili_comment", "douyin_comment", "kuaishou_comment"):
        try:
            configure_pacing(platform, mcfg.request_delay_min, mcfg.request_delay_max)
            configure_concurrency(platform, mcfg.concurrency_per_platform)
        except Exception:
            logger.exception("comment platform pacing/concurrency config failed: %s", platform)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest sidecar/tests/test_monitor_lifecycle_pacing.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add sidecar/csm_sidecar/services/monitor_lifecycle.py sidecar/tests/test_monitor_lifecycle_pacing.py
git commit -m "feat(monitor): 接通评论平台 pacing/concurrency 可调档（默认保守）"
```

---

## Task 6: 前端 CommentMonitorModule 加抓取进度条

**Files:**
- Modify: `frontend/src/components/monitor/CommentMonitorModule.vue`

**说明:** 该模块目前无任何进度条，只有 `batchRunState()` 文案与 L3 spinner。镜像 `ZhihuSearchModule` 直接读 `monitorStatus` store，在 L2 视频行（每行＝一个 task）和 L3 详情显示进度条。前端可视组件无单测 harness，用 dev 实跑验证。

- [ ] **Step 1: script 里引入 store + ProgressBar**

`CommentMonitorModule.vue` `<script setup>` import 区加：

```ts
import ProgressBar from "@/components/ui/ProgressBar.vue";
import { useMonitorStatus } from "@/stores/monitorStatus";
```

在 `const toast = useToast();` 之后加：

```ts
const monitorStatus = useMonitorStatus();

// 单个 task（视频）当前抓取进度比例：running 且有 progress 时返回 0-1，
// 否则 null（ProgressBar 收到 null 走 indeterminate shimmer）。
function videoProgressValue(videoId: string): number | null {
  const taskId = realTaskIdFromVideoId(videoId);
  if (taskId == null) return null;
  const p = monitorStatus.progressOf(taskId);
  if (!p || !p.total) return null;
  return Math.max(0, Math.min(1, p.current / p.total));
}
function isVideoRunning(videoId: string): boolean {
  const taskId = realTaskIdFromVideoId(videoId);
  return taskId != null ? monitorStatus.isRunning(taskId) : false;
}
```

- [ ] **Step 2: L2 视频行加进度条**

在 L2 视频行（约第 1006-1017 行那个 `<div class="min-w-0">` 标题块）里，`postedAt` 那行 `<div>` 之后、闭合 `</div>` 之前，插入：

```html
                  <ProgressBar
                    v-if="isVideoRunning(v.id)"
                    :value="videoProgressValue(v.id)"
                    :height="3"
                    tone="primary"
                    :style="{ marginTop: '6px' }"
                  />
```

- [ ] **Step 3: L3 详情「立刻监测」按钮旁显示已扫描进度**

在 L3 操作按钮区（约第 1206-1213 行）的 `<span>{{ runningTaskIds[...] ? "监测中…" : "立刻监测" }}</span>` 文案中，把进度数字带上。将该 `<button>` 内的 `<span>` 替换为：

```html
                <span>{{
                  runningTaskIds[realTaskIdFromVideoId(selectedVideo.id) || 0]
                    ? (monitorStatus.progressOf(realTaskIdFromVideoId(selectedVideo.id) || 0)
                        ? `监测中 ${monitorStatus.progressOf(realTaskIdFromVideoId(selectedVideo.id) || 0)!.current}/${monitorStatus.progressOf(realTaskIdFromVideoId(selectedVideo.id) || 0)!.total}`
                        : "监测中…")
                    : "立刻监测"
                }}</span>
```

并在该 `<button>` 之后插入一条细进度条：

```html
              <ProgressBar
                v-if="realTaskIdFromVideoId(selectedVideo.id) && runningTaskIds[realTaskIdFromVideoId(selectedVideo.id) || 0]"
                :value="videoProgressValue(selectedVideo.id)"
                :height="4"
                tone="primary"
                :style="{ alignSelf: 'center', flex: 1, minWidth: '80px' }"
              />
```

- [ ] **Step 4: 类型检查**

Run: `cd frontend && npx vue-tsc --noEmit -p tsconfig.json`
Expected: 无新增类型错误（若 `vue-tsc -b` 产生 `vite.config.js`/`.d.ts` emit，用 `git checkout -- vite.config.js *.tsbuildinfo` 还原）

- [ ] **Step 5: dev 实跑验证（手测）**

按 `reference_csm_dev_worktree_setup` 起 dev（worktree 用 `$env:PYTHONPATH=<worktree>/sidecar` 覆盖，dev 服务用 `run_in_background`）。
- 监控中心 → 平台评论 → 选一个批次「立刻监测」→ 进 L2 视频列表
- Expected: 正在抓的视频行下方出现细进度条并随抓取推进；L3 详情按钮显示「监测中 N/150」并有进度条；抓完进度条消失、显示结果。

- [ ] **Step 6: 提交**

```bash
git add frontend/src/components/monitor/CommentMonitorModule.vue
git commit -m "feat(monitor-ui): 平台评论 L2/L3 抓取进度条（读 monitorStatus）"
```

---

## Self-Review

**1. Spec coverage（对照 spec §2 Stream A）:**
- 进度条不显示 → Task 1-4（适配器调用 progress_cb）+ Task 6（前端显示）✓
- 进度语义 = 已扫描评论数 / scrape_top_n → Task 2-4 `report_progress(progress_cb, len(all_comments), limit)`，limit=scrape_top_n ✓
- 提速可调档 + 保守默认 → Task 2-4（scrape_top_n 做抓取上限，默认 150）+ Task 5（pacing/concurrency 接线，默认 5-15s/2）✓
- 进度 cb 抛错不中断抓取 → Task 1 `report_progress` try/except ✓
- 配置边界保护 → `RequestPacer.configure` 已校验 `delay_max>=delay_min>=0`；`scrape_top_n` 用 `int(... or DEFAULT)` 兜底；`configure_concurrency` 已校验 `>=1`。✓（无需额外任务）

**2. Placeholder scan:** 无 TBD/TODO；每个代码步给了完整代码与 before/after 锚点。✓

**3. Type consistency:** `ProgressCb`/`report_progress` 在 Task 1 定义，Task 2-4 import 一致；`progress_cb` 关键字与 `monitor_loop._run_one` 现有调用 `adapter.fetch(task, progress_cb=_progress_cb, cancel_token=..., resume_from=...)` 匹配（`resume_from` 仍由 `**_kwargs` 吞）。`videoProgressValue`/`isVideoRunning` 在 Task 6 Step 1 定义、Step 2-3 使用一致。`progressOf` 返回 `{current,total}|null` 与 store 定义一致。✓

**4. 风险点（执行时留意）:**
- 行号是基于当前快照的锚点，执行时以「函数名 + 相邻代码」定位，不要死认行号。
- Task 6 Step 3 的内联三元较繁，若 vue-tsc 报错可抽成 `computed` 或小函数 `detailRunLabel()`，行为不变。
