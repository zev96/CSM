# 首页工作台按「图一」重做 — 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 CSM 桌面端首页改成「图一」bento 版式 —— 3 张大数字卡(异动数)+ 高权重信源榜 + GEO 半圆仪表盘 + 评论留存卡 + 最近文档，每张接最近 7 天真实指标。

**Architecture:** 后端在既有 `history_service` / `geo` 存储层上加 3 个聚合(changed_prev、GEO 汇总曝光、全局信源榜)，全部纯查询无 schema 变更；前端新建 3 个卡片组件 + 重做留存卡 + 重排 `HomeView`，复用既有 `card-frosted`/`Sparkline`/`Icon`/`useSidecar` 原子。运行中的桌面端走 vite HMR 实时验收。

**Tech Stack:** FastAPI + SQLite(csm_core.monitor.storage) / pytest；Vue 3 `<script setup>` + Pinia + axios / vitest + vue-tsc。

**工作目录与命令前缀（每个测试步骤都按此跑）：**
- 仓库根：`D:\CSM\.claude\worktrees\elastic-moore-fa05f4`，分支 `feat/home-dashboard-redesign`
- 后端测试必须用 worktree 代码（csm_sidecar editable 装在主仓）：
  `$env:PYTHONPATH="D:/CSM/.claude/worktrees/elastic-moore-fa05f4;D:/CSM/.claude/worktrees/elastic-moore-fa05f4/sidecar"; python -m pytest <file> -v`
- 前端：在 `frontend/` 下 `npm run test:unit -- <file>`；类型检查 `npx vue-tsc --noEmit`（**别用 `-b`**，它会 emit vite.config.js 触发 vite restart）
- 提交：只 `git add <具体文件>`，**绝不 `git add -A`**（`frontend/src-tauri/tauri.conf.json` 有 dev-only 改动不能进）。trailer：`Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`

---

## Task 1: 后端 — 全局高权重信源榜

**Files:**
- Modify: `csm_core/monitor/geo/storage.py:130-162`（`citation_leaderboard` 让 `task_id` 可空 = 全局）
- Modify: `sidecar/csm_sidecar/services/__init__`? 否 — 直接在 route 调 storage（与现有 `geo_citations` 同风格）
- Modify: `sidecar/csm_sidecar/routes/monitor.py`（在 `geo_citations` 后加全局榜路由）
- Test: `sidecar/tests/test_geo_leaderboard_global.py`（新建）

- [ ] **Step 1: 写失败测试**

```python
# sidecar/tests/test_geo_leaderboard_global.py
"""全局高权重信源榜：跨所有 geo 任务聚合 + 排名周对比。"""
from __future__ import annotations
from datetime import datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient
from csm_core.monitor.geo import storage as geo_storage
from csm_core.monitor.geo.models import GeoCell, Citation


def _cell(task_id, kw, domains, *, mentioned=True, status="ok"):
    return GeoCell(
        platform="tongyi", keyword=kw, mentioned=mentioned, rank=1,
        sentiment="pos", answer_text="x", status=status, raw={},
        recommended=[], summary="",
        citations=[Citation(url=f"https://{d}/a", title="t", domain=d,
                            source_type="新闻网站") for d in domains],
    )


def test_global_leaderboard_aggregates_across_tasks(client: TestClient, monitor_db: Path):
    now = datetime.now()
    geo_storage.record_run(101, now, [_cell(101, "扫地机", ["smzdm.com", "zhihu.com"])])
    geo_storage.record_run(202, now, [_cell(202, "吸尘器", ["smzdm.com"])])
    board = geo_storage.citation_leaderboard(task_id=None, days=7)
    domains = [b["domain"] for b in board]
    assert "smzdm.com" in domains and "zhihu.com" in domains
    smzdm = next(b for b in board if b["domain"] == "smzdm.com")
    assert smzdm["count"] == 2  # 跨 101 + 202


def test_global_leaderboard_endpoint_with_rank_delta(client: TestClient, monitor_db: Path):
    now = datetime.now()
    # 本周：smzdm 2 次、zhihu 1 次 → smzdm rank1, zhihu rank2
    geo_storage.record_run(1, now, [_cell(1, "k", ["smzdm.com", "smzdm.com", "zhihu.com"][:1])])
    geo_storage.record_run(1, now, [_cell(1, "k", ["smzdm.com"])])
    geo_storage.record_run(1, now, [_cell(1, "k", ["zhihu.com"])])
    r = client.get("/api/monitor/geo/citations/leaderboard", params={"days": 7, "limit": 8})
    assert r.status_code == 200, r.text
    board = r.json()["leaderboard"]
    assert board[0]["rank"] == 1
    assert "rank_delta" in board[0]  # 上一窗口无数据 → 新进，rank_delta 约定见实现
```

- [ ] **Step 2: 跑测试确认失败**

Run: `...PYTHONPATH...; python -m pytest sidecar/tests/test_geo_leaderboard_global.py -v`
Expected: FAIL（`citation_leaderboard` 不接受 `task_id=None`；endpoint 404）

- [ ] **Step 3: 改 storage —— `task_id` 可空**

`csm_core/monitor/geo/storage.py`，把 `citation_leaderboard` 签名与 WHERE 改成：

```python
def citation_leaderboard(
    task_id: int | None, days: int = 30, platform: str | None = None, keyword: str | None = None,
) -> list[dict[str, Any]]:
    """域名频次降序。task_id=None 时跨全部任务聚合（首页全局信源榜）。"""
    conn = monitor_storage.get_conn()
    sql = ["SELECT domain, source_type, platform, keyword",
           "FROM geo_citations",
           "WHERE checked_at >= datetime('now', ?)"]
    args: list[Any] = [f"-{int(days)} days"]
    if task_id is not None:
        sql.append("AND task_id=?"); args.append(task_id)
    if platform:
        sql.append("AND platform=?"); args.append(platform)
    if keyword:
        sql.append("AND keyword=?"); args.append(keyword)
    rows = conn.execute("\n".join(sql), args).fetchall()
    # ... agg 块原样不变 ...
```

（agg / out / sort 块保持不变。注意现有调用方 `geo_citations` route 与 `geo_export` 传的是具体 `task_id`，行为不变。）

- [ ] **Step 4: 加全局榜 route + 排名周对比**

`sidecar/csm_sidecar/routes/monitor.py`，在 `geo_citations`（约 :684）之后加：

```python
@router.get("/api/monitor/geo/citations/leaderboard")
def geo_citations_leaderboard(
    days: int = Query(default=7, ge=1, le=90),
    limit: int = Query(default=8, ge=1, le=50),
) -> dict[str, Any]:
    """全局高权重信源榜：跨所有 geo 任务近 days 天聚合，带排名较上一窗口的变化。"""
    _require_storage()
    from csm_core.monitor.geo import storage as geo_storage

    curr = geo_storage.citation_leaderboard(task_id=None, days=days)
    prev = geo_storage.citation_leaderboard(task_id=None, days=days * 2)
    # prev 取「days..2*days」窗口排名：用 2*days 榜的排名近似上一窗口位置
    prev_rank = {b["domain"]: i + 1 for i, b in enumerate(prev)}
    out = []
    for i, b in enumerate(curr[:limit]):
        rank = i + 1
        rp = prev_rank.get(b["domain"])
        out.append({
            "domain": b["domain"], "source_type": b["source_type"],
            "count": b["count"], "weight": b["weight"],
            "rank": rank,
            "rank_prev": rp,                      # None = 新进
            "rank_delta": (rp - rank) if rp is not None else None,  # +上升 / -下降 / None 新进
        })
    return {"days": days, "leaderboard": out}
```

- [ ] **Step 5: 跑测试确认通过**

Run: `...PYTHONPATH...; python -m pytest sidecar/tests/test_geo_leaderboard_global.py -v`
Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add csm_core/monitor/geo/storage.py sidecar/csm_sidecar/routes/monitor.py sidecar/tests/test_geo_leaderboard_global.py
git commit -m "feat(geo): 全局高权重信源榜端点（跨任务聚合 + 排名周对比）"
```

---

## Task 2: 后端 — GEO 汇总曝光率端点

**Files:**
- Modify: `csm_core/monitor/geo/storage.py`（加 `exposure_window(days_from, days_to)` 聚合）
- Modify: `sidecar/csm_sidecar/services/history_service.py`（加 `get_geo_exposure_summary`）
- Modify: `sidecar/csm_sidecar/routes/monitor.py`（加 route）
- Test: `sidecar/tests/test_geo_exposure_summary.py`（新建）

- [ ] **Step 1: 写失败测试**

```python
# sidecar/tests/test_geo_exposure_summary.py
from __future__ import annotations
from datetime import datetime, timedelta
from pathlib import Path
from fastapi.testclient import TestClient
from csm_core.monitor.geo import storage as geo_storage
from csm_core.monitor.geo.models import GeoCell


def _cell(kw, *, mentioned, status="ok"):
    return GeoCell(platform="tongyi", keyword=kw, mentioned=mentioned, rank=1 if mentioned else -1,
                   sentiment="pos" if mentioned else "na", answer_text="", status=status,
                   raw={}, recommended=[], summary="", citations=[])


def test_geo_exposure_summary_global_soc(client: TestClient, monitor_db: Path):
    now = datetime.now()
    # 4 个 ok cell，2 个 mentioned → soc 0.5
    geo_storage.record_run(1, now, [_cell("a", mentioned=True), _cell("b", mentioned=True),
                                    _cell("c", mentioned=False), _cell("d", mentioned=False)])
    r = client.get("/api/monitor/geo/summary", params={"range": "7d"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["soc"] == 0.5
    assert body["ok_cells"] == 4 and body["mentioned"] == 2
    assert body["band"] in ("hidden", "weak", "strong")


def test_geo_exposure_summary_empty(client: TestClient, monitor_db: Path):
    r = client.get("/api/monitor/geo/summary", params={"range": "7d"})
    assert r.status_code == 200
    b = r.json()
    assert b["soc"] == 0.0 and b["ok_cells"] == 0 and b["delta"] == 0.0
```

- [ ] **Step 2: 跑测试确认失败**

Run: `...PYTHONPATH...; python -m pytest sidecar/tests/test_geo_exposure_summary.py -v`
Expected: FAIL（endpoint 404）

- [ ] **Step 3: storage 聚合函数**

`csm_core/monitor/geo/storage.py` 末尾加：

```python
def exposure_window(days: int, offset_days: int = 0) -> tuple[int, int]:
    """返回 [now-(offset+days) .. now-offset) 窗口内 (mentioned, ok_total)。

    offset=0 → 最近 days 天；offset=days → 上一个 days 天（周对比用）。
    口径同 metrics._block：分母是 status='ok' 的 cell 数。
    """
    conn = monitor_storage.get_conn()
    row = conn.execute(
        """
        SELECT
          COUNT(*) FILTER (WHERE status='ok') AS ok_total,
          COALESCE(SUM(CASE WHEN status='ok' AND mentioned=1 THEN 1 ELSE 0 END), 0) AS mentioned
        FROM geo_cells
        WHERE checked_at >= datetime('now', ?) AND checked_at < datetime('now', ?)
        """,
        (f"-{int(days) + int(offset_days)} days", f"-{int(offset_days)} days"),
    ).fetchone()
    return int(row["mentioned"] or 0), int(row["ok_total"] or 0)
```

> 注：`FILTER (WHERE ...)` 需 SQLite ≥ 3.30（Python 3.14 自带 sqlite 满足）。若担心兼容可改 `SUM(CASE WHEN status='ok' THEN 1 ELSE 0 END)`。

- [ ] **Step 4: service 函数**

`sidecar/csm_sidecar/services/history_service.py` 加（复用 `_parse_range` + `geo.metrics.band`）：

```python
def get_geo_exposure_summary(range_str: str) -> dict[str, Any]:
    """全部 geo 任务近 range 天的全局曝光率 soc = Σmentioned/Σok_cells + 较上一窗口 delta。"""
    range_days = _parse_range(range_str)
    from csm_core.monitor.geo import storage as geo_storage
    from csm_core.monitor.geo.metrics import band
    m_cur, ok_cur = geo_storage.exposure_window(range_days, offset_days=0)
    m_prev, ok_prev = geo_storage.exposure_window(range_days, offset_days=range_days)
    soc = (m_cur / ok_cur) if ok_cur else 0.0
    soc_prev = (m_prev / ok_prev) if ok_prev else 0.0
    return {
        "range": range_str,
        "soc": round(soc, 4),
        "soc_prev": round(soc_prev, 4),
        "delta": round(soc - soc_prev, 4),
        "band": band(soc),                    # hidden / weak / strong（复用既有阈值 0.2/0.5）
        "mentioned": m_cur,
        "ok_cells": ok_cur,
    }
```

- [ ] **Step 5: route**

`sidecar/csm_sidecar/routes/monitor.py`，紧跟 zhihu-search history route 之后（约 :348）：

```python
@router.get("/api/monitor/geo/summary")
def get_geo_exposure_summary(range_str: str = Query("7d", alias="range")) -> dict[str, Any]:
    _require_storage()
    try:
        return history_service.get_geo_exposure_summary(range_str=range_str)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
```

> 路由顺序注意：必须放在 `/api/monitor/geo/{task_id}/citations` **之前**或用静态前缀区分 —— `summary` 不是数字，不会被 `{task_id}` 吞，但为稳妥放在 geo 段开头。

- [ ] **Step 6: 跑测试确认通过**

Run: `...PYTHONPATH...; python -m pytest sidecar/tests/test_geo_exposure_summary.py -v`
Expected: PASS

- [ ] **Step 7: 提交**

```bash
git add csm_core/monitor/geo/storage.py sidecar/csm_sidecar/services/history_service.py sidecar/csm_sidecar/routes/monitor.py sidecar/tests/test_geo_exposure_summary.py
git commit -m "feat(geo): GEO 汇总曝光率端点（全局 soc + 较上周 delta + band）"
```

---

## Task 3: 后端 — 3 个 ranking 端点补 `changed_prev`

**Files:**
- Modify: `sidecar/csm_sidecar/services/history_service.py`（`get_baidu_keyword_history` / `get_zhihu_ranking_history` / `get_zhihu_search_history` 的 kpis 各加 `changed_prev`）
- Test: `sidecar/tests/test_history_changed_prev.py`（新建）

**口径：** `changed_prev` = 把每个 task 的「截止 (now - range_days) 之前」最近两条结果做同样 `_classify_zhihu_change`，统计 up/down/new/dropped 的条目数。即「上一个窗口末的 changed 数」，供大数字卡算 ↑/↓ vs 上周。

- [ ] **Step 1: 写失败测试（以 zhihu_ranking 为例 + baidu）**

```python
# sidecar/tests/test_history_changed_prev.py
from __future__ import annotations
from datetime import datetime, timedelta
from pathlib import Path
from fastapi.testclient import TestClient
from csm_core.monitor import storage
from csm_core.monitor.base import MonitorResult
from csm_sidecar.services import history_service


def _seed_zhihu_q(client, brand="石头"):
    body = {"type": "zhihu_question", "name": "知乎问题-X",
            "target_url": "https://zhihu.com/q/1",
            "config": {"top_n": 10, "target_brand": brand},
            "schedule_cron": "manual", "enabled": True}
    return client.post("/api/monitor/tasks", json=body).json()["id"]


def _res(tid, at, mc):
    storage.save_result(MonitorResult(task_id=tid, checked_at=at, status="ok",
        rank=1, metric={"matched_count": mc, "matched_ranks": [1] * mc, "top_n": 10},
        error_message=""))


def test_zhihu_ranking_changed_prev_present(client: TestClient, monitor_db: Path):
    tid = _seed_zhihu_q(client)
    now = datetime.now()
    # 两条都在上一窗口（≥7天前）：一升一持平
    _res(tid, now - timedelta(days=9), 2)
    _res(tid, now - timedelta(days=8), 4)   # up vs 前一条 → changed_prev 计 1
    # 本窗口再来一条
    _res(tid, now, 4)
    out = history_service.get_zhihu_ranking_history("7d")
    assert "changed_prev" in out["kpis"]
    assert out["kpis"]["changed_prev"] == 1


def test_baidu_changed_prev_present(client: TestClient, monitor_db: Path):
    out = history_service.get_baidu_keyword_history("7d")
    assert "changed_prev" in out["kpis"]   # 空库也得有字段，值 0
    assert out["kpis"]["changed_prev"] == 0
```

- [ ] **Step 2: 跑测试确认失败**

Run: `...PYTHONPATH...; python -m pytest sidecar/tests/test_history_changed_prev.py -v`
Expected: FAIL（KeyError: 'changed_prev'）

- [ ] **Step 3: 加 helper + 接入 zhihu_ranking**

`history_service.py` 加 helper：

```python
def _changed_prev_count(per_task: dict[int, list[dict]], range_days: int, now: datetime,
                        score_of) -> int:
    """每个 task 取「checked_at < now-range_days」最近两条，做 curr/prev 分类，
    统计 up/down/new/dropped 的 task 数。score_of(entry)->(matched_count, best_rank, top_n)。"""
    cutoff = now - timedelta(days=range_days)
    changed = 0
    for results in per_task.values():
        older = [r for r in results if r["checked_at"] < cutoff]  # results 已 DESC
        if not older:
            continue
        curr = score_of(older[0])
        prev = score_of(older[1]) if len(older) > 1 else None
        kind, _ = _classify_zhihu_change(curr, prev)
        if kind in ("up", "down", "new", "dropped"):
            changed += 1
    return changed
```

`get_zhihu_ranking_history`：`per_task` 的 entry 已含 `matched_count`/`best_rank`/`top_n`，在 `return` 前算：

```python
    changed_prev = _changed_prev_count(
        per_task, range_days, now,
        score_of=lambda e: {"matched_count": e["matched_count"],
                            "best_rank": e["best_rank"], "top_n": e["top_n"]},
    )
```
并在 kpis dict 加 `"changed_prev": changed_prev,`。

- [ ] **Step 4: 接入 baidu + zhihu_search（per-keyword）**

baidu/zhihu_search 的 `per_task` entry 存的是整条 run 的 `metric`，需把「每关键词」展开。最简单：对这两个函数，`changed_prev` 用**任务级**近似 —— 拿每 task 老窗口最近两条 run，对其 metric 里**全部关键词**做分类计数。在 `get_baidu_keyword_history` return 前：

```python
    cutoff = now - timedelta(days=range_days)
    changed_prev = 0
    for tid, results in per_task.items():
        older = [r for r in results if r["checked_at"] < cutoff]
        if not older:
            continue
        cm = older[0]["metric"]; pm = older[1]["metric"] if len(older) > 1 else {}
        for kw in task_keywords_for(all_tasks, tid):   # 见下
            ck = _find_keyword_entry(cm, kw); pk = _find_keyword_entry(pm, kw)
            if ck is None:
                continue
            _c = {"matched_count": ck.get("default_matched_count", 0),
                  "best_rank": ck.get("default_first_rank", -1), "top_n": 10}
            _p = ({"matched_count": pk.get("default_matched_count", 0),
                   "best_rank": pk.get("default_first_rank", -1), "top_n": 10} if pk else None)
            kind, _ = _classify_zhihu_change(_c, _p)
            if kind in ("up", "down", "new", "dropped"):
                changed_prev += 1
```
其中辅助：
```python
def task_keywords_for(all_tasks, tid: int) -> list[str]:
    for t in all_tasks:
        if t["id"] == tid:
            return list(json.loads(t["config_json"] or "{}").get("search_keywords") or [])
    return []
```
kpis 加 `"changed_prev": changed_prev`。zhihu_search 同理但字段名用 `matched_count`/`first_rank`（与该函数现有 per-keyword 读法一致）。

- [ ] **Step 5: 跑测试确认通过**

Run: `...PYTHONPATH...; python -m pytest sidecar/tests/test_history_changed_prev.py -v`
Expected: PASS

- [ ] **Step 6: 跑既有 history 测试防回归**

Run: `...PYTHONPATH...; python -m pytest sidecar/tests/test_monitor_routes.py sidecar/tests/test_monitor_summary_cards.py -v`
Expected: PASS（未改既有字段，只加 `changed_prev`）

- [ ] **Step 7: 提交**

```bash
git add sidecar/csm_sidecar/services/history_service.py sidecar/tests/test_history_changed_prev.py
git commit -m "feat(monitor): 3 个 ranking 端点补 changed_prev（大数字卡较上周徽章）"
```

---

## Task 4: 前端 — `StatCard` + 3 张数字卡

**Files:**
- Create: `frontend/src/components/home/StatCard.vue`
- Create: `frontend/src/components/home/cards/BaiduStatCard.vue`、`ZhihuQuestionStatCard.vue`、`ZhihuSearchStatCard.vue`（薄包：取数 + 跳转）
- Test: `frontend/src/components/home/__tests__/StatCard.spec.ts`

> 现有 `BaiduSeoCard.vue` / `ZhihuCard.vue` / `ZhihuSearchCard.vue`（列表版）暂留文件不删，只是 HomeView 不再引用（Task 8）。新卡放 `cards/` 子目录避免命名冲突。

- [ ] **Step 1: StatCard 展示组件（纯 props）**

```vue
<!-- frontend/src/components/home/StatCard.vue -->
<script setup lang="ts">
import Icon from "@/components/ui/Icon.vue";
defineProps<{
  category: string;          // "百度 SEO"
  value: number;             // changed_keywords
  delta: number | null;      // value - changed_prev；null = 无对比
  loaded?: boolean;
  emptyHint?: string;
}>();
const emit = defineEmits<{ detail: [] }>();
function pillStyle(d: number) {
  if (d > 0) return { background: "#dde7d2", color: "#4d6b2f" };
  if (d < 0) return { background: "#f3d3cd", color: "#a3382a" };
  return { background: "rgba(28,26,23,0.06)", color: "var(--ink-2)" };
}
</script>
<template>
  <section class="card-frosted relative flex h-full flex-col overflow-hidden" :style="{ padding: '16px' }">
    <div class="flex flex-shrink-0 items-center justify-between">
      <div class="text-[12px]" :style="{ color: 'var(--ink-3)' }">{{ category }}</div>
      <button type="button" class="trend-detail inline-flex h-6 w-6 items-center justify-center rounded-full"
        title="详情" @click="emit('detail')"><Icon name="arrowRight" :size="11" /></button>
    </div>
    <div class="mt-auto flex items-end justify-between">
      <div class="font-display font-bold" :style="{ fontSize: '40px', lineHeight: 1, letterSpacing: '-1px', color: 'var(--ink)' }">
        {{ value }}
      </div>
      <span v-if="delta !== null"
        class="mb-1 inline-flex h-5 items-center gap-0.5 rounded-full px-2 text-[10.5px] font-medium"
        :style="pillStyle(delta)">
        <Icon v-if="delta > 0" name="arrowUp" :size="9" />
        <Icon v-else-if="delta < 0" name="arrowDown" :size="9" />
        {{ Math.abs(delta) }}
      </span>
    </div>
    <div class="mt-1 text-[10.5px]" :style="{ color: 'var(--ink-3)' }">近 7 天异动</div>
  </section>
</template>
<style scoped>
.trend-detail { background: rgba(28,26,23,0.04); color: var(--ink-2); border: 1px solid rgba(28,26,23,0.06); transition: background-color .12s ease; }
.trend-detail:hover { background: rgba(28,26,23,0.08); }
</style>
```

- [ ] **Step 2: 写 vitest（渲染 + 涨跌色）**

```ts
// frontend/src/components/home/__tests__/StatCard.spec.ts
import { mount } from "@vue/test-utils";
import { describe, it, expect } from "vitest";
import StatCard from "@/components/home/StatCard.vue";

describe("StatCard", () => {
  it("shows value and up pill (green) when delta>0", () => {
    const w = mount(StatCard, { props: { category: "百度 SEO", value: 5, delta: 2, loaded: true } });
    expect(w.text()).toContain("5");
    expect(w.text()).toContain("2");
    expect(w.html()).toContain("#dde7d2"); // green bg
  });
  it("hides pill when delta is null", () => {
    const w = mount(StatCard, { props: { category: "x", value: 0, delta: null, loaded: true } });
    expect(w.findAll("span").some(s => s.text().match(/\d/))).toBe(false);
  });
});
```

- [ ] **Step 3: 跑测试**

Run（在 `frontend/`）: `npm run test:unit -- StatCard`
Expected: PASS

- [ ] **Step 4: 3 张薄包卡（取数 + 跳转）**

`frontend/src/components/home/cards/BaiduStatCard.vue`（其余两张同构，改 endpoint / category / tab / kpis 字段名）：

```vue
<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import StatCard from "@/components/home/StatCard.vue";
import { useSidecar } from "@/stores/sidecar";
import { useSidecarReady } from "@/composables/useSidecarReady";
const sidecar = useSidecar(); const router = useRouter(); const { whenReady } = useSidecarReady();
const value = ref(0); const delta = ref<number | null>(null); const loaded = ref(false);
onMounted(async () => {
  try {
    await whenReady();
    const r = await sidecar.client.get("/api/monitor/history/baidu-keyword", { params: { range: "7d" } });
    const k = r.data.kpis ?? {};
    value.value = k.changed_keywords ?? 0;
    delta.value = typeof k.changed_prev === "number" ? (k.changed_keywords - k.changed_prev) : null;
  } catch { /* 静默空态 */ } finally { loaded.value = true; }
});
</script>
<template>
  <StatCard category="百度 SEO" :value="value" :delta="delta" :loaded="loaded"
    @detail="router.push({ name: 'monitor', query: { tab: 'baidu' } })" />
</template>
```

- 知乎问题：endpoint `/api/monitor/history/zhihu-ranking`，kpis 字段 `changed_questions`，category "知乎问题"，tab `zhihu`。
- 知乎搜索：endpoint `/api/monitor/history/zhihu-search`，kpis 字段 `changed_keywords`，category "知乎搜索"，tab `zhihu_search`。

- [ ] **Step 5: 提交**

```bash
git add frontend/src/components/home/StatCard.vue frontend/src/components/home/cards/ frontend/src/components/home/__tests__/StatCard.spec.ts
git commit -m "feat(home): StatCard 大数字卡 + 百度/知乎问题/知乎搜索 三张数字卡"
```

---

## Task 5: 前端 — `GaugeCard`（GEO 半圆仪表盘）

**Files:**
- Create: `frontend/src/components/home/GaugeCard.vue`（含 SVG 半圆 + 取数）
- Test: `frontend/src/components/home/__tests__/GaugeCard.spec.ts`

- [ ] **Step 1: GaugeCard（SVG 半圆 0–100）**

```vue
<!-- frontend/src/components/home/GaugeCard.vue -->
<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import Icon from "@/components/ui/Icon.vue";
import { useSidecar } from "@/stores/sidecar";
import { useSidecarReady } from "@/composables/useSidecarReady";
const sidecar = useSidecar(); const router = useRouter(); const { whenReady } = useSidecarReady();
const soc = ref(0); const delta = ref(0); const band = ref<"hidden"|"weak"|"strong">("hidden"); const loaded = ref(false);
const pct = computed(() => Math.round(soc.value * 100));
const deltaPct = computed(() => Math.round(delta.value * 100));
const BAND_LABEL = { hidden: "低曝光", weak: "中等曝光", strong: "高曝光" } as const;
// 半圆：半径 80，180°→0° 映射 0→100。描边弧长 = π*r。
const R = 80; const ARC = Math.PI * R;
const dash = computed(() => `${(pct.value / 100) * ARC} ${ARC}`);
const arcColor = computed(() => pct.value >= 50 ? "var(--green)" : pct.value >= 20 ? "#e8a04a" : "var(--red)");
onMounted(async () => {
  try {
    await whenReady();
    const r = await sidecar.client.get("/api/monitor/geo/summary", { params: { range: "7d" } });
    soc.value = r.data.soc ?? 0; delta.value = r.data.delta ?? 0; band.value = r.data.band ?? "hidden";
  } catch { /* 静默 */ } finally { loaded.value = true; }
});
</script>
<template>
  <section class="card-frosted relative flex h-full flex-col overflow-hidden" :style="{ padding: '16px' }">
    <div class="flex flex-shrink-0 items-center justify-between">
      <div class="text-[12px]" :style="{ color: 'var(--ink-3)' }">GEO</div>
      <button type="button" class="trend-detail inline-flex h-6 w-6 items-center justify-center rounded-full"
        title="详情" @click="router.push({ name: 'monitor', query: { tab: 'geo' } })"><Icon name="arrowRight" :size="11" /></button>
    </div>
    <div class="flex min-h-0 flex-1 flex-col items-center justify-center">
      <svg :viewBox="`0 0 ${R*2+20} ${R+30}`" :style="{ width: '100%', maxWidth: '220px' }">
        <path :d="`M 10 ${R+10} A ${R} ${R} 0 0 1 ${R*2+10} ${R+10}`" fill="none"
          stroke="rgba(28,26,23,0.08)" :stroke-width="12" stroke-linecap="round" />
        <path :d="`M 10 ${R+10} A ${R} ${R} 0 0 1 ${R*2+10} ${R+10}`" fill="none"
          :stroke="arcColor" :stroke-width="12" stroke-linecap="round"
          :stroke-dasharray="dash" :style="{ transition: 'stroke-dasharray .6s ease' }" />
        <text :x="R+10" :y="R+2" text-anchor="middle" class="font-display font-bold"
          :style="{ fontSize: '34px', fill: 'var(--ink)' }">{{ pct }}</text>
        <text :x="R+10" :y="R+22" text-anchor="middle" :style="{ fontSize: '11px', fill: arcColor }">{{ BAND_LABEL[band] }}</text>
      </svg>
      <span class="mt-1 inline-flex h-5 items-center gap-0.5 rounded-full px-2 text-[10.5px] font-medium"
        :style="deltaPct > 0 ? { background:'#dde7d2', color:'#4d6b2f' } : deltaPct < 0 ? { background:'#f3d3cd', color:'#a3382a' } : { background:'rgba(28,26,23,0.06)', color:'var(--ink-2)' }">
        <Icon v-if="deltaPct>0" name="arrowUp" :size="9" /><Icon v-else-if="deltaPct<0" name="arrowDown" :size="9" />
        {{ Math.abs(deltaPct) }}% 较上周
      </span>
    </div>
  </section>
</template>
<style scoped>
.trend-detail { background: rgba(28,26,23,0.04); color: var(--ink-2); border: 1px solid rgba(28,26,23,0.06); }
.trend-detail:hover { background: rgba(28,26,23,0.08); }
</style>
```

- [ ] **Step 2: vitest（mock client，断言 pct 渲染）**

```ts
// frontend/src/components/home/__tests__/GaugeCard.spec.ts
import { mount, flushPromises } from "@vue/test-utils";
import { describe, it, expect, vi } from "vitest";
vi.mock("@/stores/sidecar", () => ({ useSidecar: () => ({ client: { get: vi.fn().mockResolvedValue({ data: { soc: 0.6, delta: 0.08, band: "strong" } }) } }) }));
vi.mock("@/composables/useSidecarReady", () => ({ useSidecarReady: () => ({ whenReady: () => Promise.resolve() }) }));
vi.mock("vue-router", () => ({ useRouter: () => ({ push: vi.fn() }) }));
import GaugeCard from "@/components/home/GaugeCard.vue";

describe("GaugeCard", () => {
  it("renders soc as 0-100 + band label", async () => {
    const w = mount(GaugeCard);
    await flushPromises();
    expect(w.text()).toContain("60");
    expect(w.text()).toContain("高曝光");
    expect(w.text()).toContain("8%");
  });
});
```

- [ ] **Step 3: 跑测试**

Run（`frontend/`）: `npm run test:unit -- GaugeCard`
Expected: PASS

- [ ] **Step 4: 提交**

```bash
git add frontend/src/components/home/GaugeCard.vue frontend/src/components/home/__tests__/GaugeCard.spec.ts
git commit -m "feat(home): GEO 半圆仪表盘卡（全局曝光率 + 较上周）"
```

---

## Task 6: 前端 — `SourceLeaderboardCard`（高权重信源榜）

**Files:**
- Create: `frontend/src/components/home/SourceLeaderboardCard.vue`
- Test: `frontend/src/components/home/__tests__/SourceLeaderboardCard.spec.ts`

- [ ] **Step 1: 组件**

```vue
<!-- frontend/src/components/home/SourceLeaderboardCard.vue -->
<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import Icon from "@/components/ui/Icon.vue";
import { useSidecar } from "@/stores/sidecar";
import { useSidecarReady } from "@/composables/useSidecarReady";
interface Row { domain: string; source_type: string; rank: number; rank_delta: number | null; }
const sidecar = useSidecar(); const router = useRouter(); const { whenReady } = useSidecarReady();
const rows = ref<Row[]>([]); const loaded = ref(false);
onMounted(async () => {
  try {
    await whenReady();
    const r = await sidecar.client.get("/api/monitor/geo/citations/leaderboard", { params: { days: 7, limit: 8 } });
    rows.value = r.data.leaderboard ?? [];
  } catch { /* 静默 */ } finally { loaded.value = true; }
});
function deltaStyle(d: number | null) {
  if (d === null) return { background: "var(--yellow-soft)", color: "#7a5400" }; // 新进
  if (d > 0) return { background: "#dde7d2", color: "#4d6b2f" };
  if (d < 0) return { background: "#f3d3cd", color: "#a3382a" };
  return { background: "rgba(28,26,23,0.06)", color: "var(--ink-2)" };
}
function deltaText(d: number | null) { return d === null ? "新" : d === 0 ? "—" : String(Math.abs(d)); }
</script>
<template>
  <section class="card-frosted relative flex h-full flex-col overflow-hidden" :style="{ padding: '16px' }">
    <div class="flex flex-shrink-0 items-center justify-between">
      <div class="text-[12px]" :style="{ color: 'var(--ink-3)' }">高权重信源</div>
      <button type="button" class="trend-detail inline-flex h-6 w-6 items-center justify-center rounded-full"
        title="详情" @click="router.push({ name: 'monitor', query: { tab: 'geo' } })"><Icon name="arrowRight" :size="11" /></button>
    </div>
    <div v-if="loaded && rows.length === 0" class="flex min-h-0 flex-1 items-center justify-center text-center text-[12px]" :style="{ color: 'var(--ink-3)' }">
      暂无信源数据<br /><span class="text-[11px]">跑 GEO 监测后自动统计</span>
    </div>
    <div v-else class="mt-2 flex min-h-0 flex-1 flex-col gap-1 overflow-y-auto">
      <div v-for="r in rows" :key="r.domain" class="flex items-center gap-2 rounded-[10px] px-2 py-1.5">
        <span class="font-mono w-4 flex-shrink-0 text-[12px] tabular-nums" :style="{ color: 'var(--ink-3)' }">{{ r.rank }}</span>
        <div class="min-w-0 flex-1">
          <div class="truncate text-[12px]" :style="{ color: 'var(--ink)' }">{{ r.domain }}</div>
          <div class="truncate text-[10px]" :style="{ color: 'var(--ink-3)' }">{{ r.source_type }}</div>
        </div>
        <span class="inline-flex h-5 flex-shrink-0 items-center gap-0.5 rounded-full px-2 text-[10.5px] font-medium" :style="deltaStyle(r.rank_delta)">
          <Icon v-if="r.rank_delta !== null && r.rank_delta > 0" name="arrowUp" :size="9" />
          <Icon v-else-if="r.rank_delta !== null && r.rank_delta < 0" name="arrowDown" :size="9" />
          {{ deltaText(r.rank_delta) }}
        </span>
      </div>
    </div>
  </section>
</template>
<style scoped>
.trend-detail { background: rgba(28,26,23,0.04); color: var(--ink-2); border: 1px solid rgba(28,26,23,0.06); }
.trend-detail:hover { background: rgba(28,26,23,0.08); }
</style>
```

- [ ] **Step 2: vitest**

```ts
// frontend/src/components/home/__tests__/SourceLeaderboardCard.spec.ts
import { mount, flushPromises } from "@vue/test-utils";
import { describe, it, expect, vi } from "vitest";
vi.mock("@/stores/sidecar", () => ({ useSidecar: () => ({ client: { get: vi.fn().mockResolvedValue({ data: { leaderboard: [
  { domain: "smzdm.com", source_type: "什么值得买", rank: 1, rank_delta: 3 },
  { domain: "zhihu.com", source_type: "知乎", rank: 2, rank_delta: null },
] } }) } }) }));
vi.mock("@/composables/useSidecarReady", () => ({ useSidecarReady: () => ({ whenReady: () => Promise.resolve() }) }));
vi.mock("vue-router", () => ({ useRouter: () => ({ push: vi.fn() }) }));
import SourceLeaderboardCard from "@/components/home/SourceLeaderboardCard.vue";

describe("SourceLeaderboardCard", () => {
  it("renders ranked domains with delta / 新", async () => {
    const w = mount(SourceLeaderboardCard);
    await flushPromises();
    expect(w.text()).toContain("smzdm.com");
    expect(w.text()).toContain("zhihu.com");
    expect(w.text()).toContain("新"); // rank_delta null
  });
});
```

- [ ] **Step 3: 跑测试**

Run（`frontend/`）: `npm run test:unit -- SourceLeaderboardCard`
Expected: PASS

- [ ] **Step 4: 提交**

```bash
git add frontend/src/components/home/SourceLeaderboardCard.vue frontend/src/components/home/__tests__/SourceLeaderboardCard.spec.ts
git commit -m "feat(home): 高权重信源榜卡（全局 top-N + 排名周对比）"
```

---

## Task 7: 前端 — 重做 `CommentRetentionCard`（改用专用 7 天端点）

**Files:**
- Modify: `frontend/src/components/home/CommentRetentionCard.vue`（整体重写 script + template）
- Test: `frontend/src/components/home/__tests__/CommentRetentionCard.spec.ts`（新建）

**数据：** 改用 `GET /api/monitor/history/comment-retention?range=7d` → `platforms[ptype] = { label, rate_today, rate_prev, daily_series[] }`。大% = 各平台 `current_retained` / `current_total` 聚合；徽章 = 聚合 rate_today vs 聚合 rate_prev；平台 tab 切换显示单平台 rate + 其 daily_series 折线。

- [ ] **Step 1: 重写组件**

```vue
<!-- frontend/src/components/home/CommentRetentionCard.vue -->
<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import Icon from "@/components/ui/Icon.vue";
import Sparkline from "@/components/ui/Sparkline.vue";
import { useSidecar } from "@/stores/sidecar";
import { useSidecarReady } from "@/composables/useSidecarReady";
interface PlatformData { label: string; current_retained: number; current_total: number;
  rate_today: number; rate_prev: number; daily_series: { date: string; rate: number }[]; }
const sidecar = useSidecar(); const router = useRouter(); const { whenReady } = useSidecarReady();
const platforms = ref<Record<string, PlatformData>>({}); const loaded = ref(false);
const ORDER = [["bilibili_comment","B 站"],["kuaishou_comment","快手"],["douyin_comment","抖音"]] as const;
const activeKey = ref<string | null>(null); // null = 聚合
const available = computed(() => ORDER.filter(([k]) => platforms.value[k]));
const aggRate = computed(() => {
  let ret = 0, tot = 0;
  for (const [k] of available.value) { const p = platforms.value[k]; ret += p.current_retained; tot += p.current_total; }
  return tot ? ret / tot : 0;
});
const aggPrev = computed(() => {  // 各平台 rate_prev 按今日 total 加权
  let s = 0, tot = 0;
  for (const [k] of available.value) { const p = platforms.value[k]; s += p.rate_prev * p.current_total; tot += p.current_total; }
  return tot ? s / tot : 0;
});
const shownRate = computed(() => activeKey.value ? (platforms.value[activeKey.value]?.rate_today ?? 0) : aggRate.value);
const shownPrev = computed(() => activeKey.value ? (platforms.value[activeKey.value]?.rate_prev ?? 0) : aggPrev.value);
const deltaPct = computed(() => Math.round((shownRate.value - shownPrev.value) * 100));
const series = computed<number[]>(() => {
  if (activeKey.value) return (platforms.value[activeKey.value]?.daily_series ?? []).map(d => Math.round(d.rate * 100));
  // 聚合折线：按平台 total 不易加权，简单取 B站 优先 or 第一个有数据平台
  const first = available.value[0]?.[0];
  return first ? (platforms.value[first].daily_series ?? []).map(d => Math.round(d.rate * 100)) : [];
});
const sparkColor = computed(() => { const p = Math.round(shownRate.value*100); return p>=80?"var(--green)":p>=50?"#e8a04a":"var(--red)"; });
onMounted(async () => {
  try { await whenReady();
    const r = await sidecar.client.get("/api/monitor/history/comment-retention", { params: { range: "7d" } });
    platforms.value = r.data.platforms ?? {};
  } catch { /* 静默 */ } finally { loaded.value = true; }
});
</script>
<template>
  <section class="card-frosted relative flex h-full flex-col overflow-hidden" :style="{ padding: '16px' }">
    <div class="flex flex-shrink-0 items-center justify-between">
      <div class="text-[12px]" :style="{ color: 'var(--ink-3)' }">评论留存率</div>
      <button type="button" class="trend-detail inline-flex h-6 w-6 items-center justify-center rounded-full"
        title="详情" @click="router.push({ name: 'monitor', query: { tab: 'comment' } })"><Icon name="arrowRight" :size="11" /></button>
    </div>
    <div class="mt-2 flex flex-shrink-0 items-baseline gap-2">
      <div class="font-display font-bold" :style="{ fontSize: '40px', lineHeight: 1, letterSpacing: '-1px', color: 'var(--ink)' }">
        {{ available.length ? Math.round(shownRate * 100) + "%" : "—" }}
      </div>
      <span v-if="available.length" class="inline-flex h-5 items-center gap-0.5 rounded-full px-2 text-[10.5px] font-medium"
        :style="deltaPct>0?{background:'#dde7d2',color:'#4d6b2f'}:deltaPct<0?{background:'#f3d3cd',color:'#a3382a'}:{background:'rgba(28,26,23,0.06)',color:'var(--ink-2)'}">
        <Icon v-if="deltaPct>0" name="arrowUp" :size="9" /><Icon v-else-if="deltaPct<0" name="arrowDown" :size="9" />{{ Math.abs(deltaPct) }}%
      </span>
    </div>
    <div class="mb-2 flex-shrink-0">
      <Sparkline :points="series" :height="48" :stroke="sparkColor" :show-last="true" :y-min="0" :y-max="100" fluid />
    </div>
    <!-- 平台 tab -->
    <div class="mt-auto flex flex-shrink-0 gap-1">
      <button type="button" class="rounded-full px-2.5 py-1 text-[11px]"
        :style="activeKey===null?{background:'var(--ink)',color:'#fff'}:{background:'var(--card-2)',color:'var(--ink-2)'}"
        @click="activeKey = null">全部</button>
      <button v-for="[k,label] in available" :key="k" type="button" class="rounded-full px-2.5 py-1 text-[11px]"
        :style="activeKey===k?{background:'var(--ink)',color:'#fff'}:{background:'var(--card-2)',color:'var(--ink-2)'}"
        @click="activeKey = k">{{ label }}</button>
    </div>
  </section>
</template>
<style scoped>
.trend-detail { background: rgba(28,26,23,0.04); color: var(--ink-2); border: 1px solid rgba(28,26,23,0.06); }
.trend-detail:hover { background: rgba(28,26,23,0.08); }
</style>
```

- [ ] **Step 2: vitest**

```ts
// frontend/src/components/home/__tests__/CommentRetentionCard.spec.ts
import { mount, flushPromises } from "@vue/test-utils";
import { describe, it, expect, vi } from "vitest";
vi.mock("@/stores/sidecar", () => ({ useSidecar: () => ({ client: { get: vi.fn().mockResolvedValue({ data: { platforms: {
  bilibili_comment: { label: "B 站", current_retained: 8, current_total: 14, rate_today: 8/14, rate_prev: 0.7, daily_series: [{date:"d",rate:0.7},{date:"d2",rate:0.57}] },
} } }) } }) }));
vi.mock("@/composables/useSidecarReady", () => ({ useSidecarReady: () => ({ whenReady: () => Promise.resolve() }) }));
vi.mock("vue-router", () => ({ useRouter: () => ({ push: vi.fn() }) }));
import CommentRetentionCard from "@/components/home/CommentRetentionCard.vue";

describe("CommentRetentionCard", () => {
  it("aggregates retention % and shows platform tab", async () => {
    const w = mount(CommentRetentionCard);
    await flushPromises();
    expect(w.text()).toContain("57%"); // 8/14
    expect(w.text()).toContain("B 站");
  });
});
```

- [ ] **Step 3: 跑测试**

Run（`frontend/`）: `npm run test:unit -- CommentRetentionCard`
Expected: PASS

- [ ] **Step 4: 提交**

```bash
git add frontend/src/components/home/CommentRetentionCard.vue frontend/src/components/home/__tests__/CommentRetentionCard.spec.ts
git commit -m "feat(home): 评论留存卡改用专用 7 天端点 + 平台 tab + 折线"
```

---

## Task 8: 前端 — HomeView bento 布局 + 移除视频抓取卡

**Files:**
- Modify: `frontend/src/views/HomeView.vue`（重排网格 + 换卡引用）
- Test: 无单测（布局靠 HMR 真机验收）；vue-tsc 兜类型

- [ ] **Step 1: 改 HomeView 引用 + 网格**

把 `<script setup>` 的 import 改为新卡，模板 Row2/Row3 换成 bento `grid`（4 列；右列 `row-span-2` 给信源榜，最近文档置右下）：

```vue
<script setup lang="ts">
import { onMounted } from "vue";
import CreateArticleHero from "@/components/home/CreateArticleHero.vue";
import BaiduStatCard from "@/components/home/cards/BaiduStatCard.vue";
import ZhihuQuestionStatCard from "@/components/home/cards/ZhihuQuestionStatCard.vue";
import ZhihuSearchStatCard from "@/components/home/cards/ZhihuSearchStatCard.vue";
import SourceLeaderboardCard from "@/components/home/SourceLeaderboardCard.vue";
import CommentRetentionCard from "@/components/home/CommentRetentionCard.vue";
import GaugeCard from "@/components/home/GaugeCard.vue";
import RecentDocsCard from "@/components/home/RecentDocsCard.vue";
import { useConfig } from "@/stores/config";
import { useSidecarReady } from "@/composables/useSidecarReady";
const cfg = useConfig(); const { whenReady } = useSidecarReady();
onMounted(async () => { try { await whenReady(); if (!cfg.data) await cfg.load(); } catch { /* toasted */ } });
</script>

<template>
  <div class="flex h-full flex-col">
    <div class="flex-shrink-0"><CreateArticleHero /></div>
    <div class="flex-shrink-0" :style="{ height: '25px' }"></div>
    <!-- bento：4 列 × 2 行；右列信源榜跨 2 行，最近文档右下 -->
    <div class="grid min-h-0 flex-1 grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 lg:grid-rows-2"
         :style="{ gap: '16px' }">
      <BaiduStatCard class="lg:col-start-1 lg:row-start-1" />
      <ZhihuQuestionStatCard class="lg:col-start-2 lg:row-start-1" />
      <ZhihuSearchStatCard class="lg:col-start-3 lg:row-start-1" />
      <SourceLeaderboardCard class="lg:col-start-4 lg:row-start-1 lg:row-span-2" />
      <CommentRetentionCard class="lg:col-start-1 lg:col-span-2 lg:row-start-2" />
      <GaugeCard class="lg:col-start-3 lg:row-start-2" />
    </div>
    <div class="flex-shrink-0" :style="{ height: '16px' }"></div>
    <div :style="{ flex: '120 1 120px', minHeight: '110px' }"><RecentDocsCard /></div>
  </div>
</template>
```

> 注：精确 col/row span 与最近文档放右下 vs 独立 Row3 在 HMR 里对图一微调（图一最近文档在信源榜下方右列；若 bento 内放不下就保留独立 Row3，如上）。`VideoMiningCard.vue` 文件保留不删，仅不再引用。

- [ ] **Step 2: 类型检查**

Run（`frontend/`）: `npx vue-tsc --noEmit`
Expected: 0 errors。若它意外 emit 了 `vite.config.js` / `*.d.ts`，`git checkout -- vite.config.js` 还原。

- [ ] **Step 3: HMR 真机核对**

运行中的桌面端会自动热更首页。核对：3 数字卡 + 信源榜 + 留存 + GEO 仪表 + 最近文档版式贴近图一；无「视频抓取」卡；空数据卡显示空态不报错。截图对照图一，必要时回 Step 1 调 span/gap。

- [ ] **Step 4: 提交**

```bash
git add frontend/src/views/HomeView.vue
git commit -m "feat(home): 首页改 bento 版式（图一）+ 移除视频抓取卡"
```

---

## Task 9: 全量验证 + PR

- [ ] **Step 1: 后端全测**

Run: `...PYTHONPATH...; python -m pytest sidecar/tests/ -q`
Expected: 全 PASS（新增 3 文件 + 既有不回归）

- [ ] **Step 2: 前端单测 + 类型**

Run（`frontend/`）: `npm run test:unit` 然后 `npx vue-tsc --noEmit`
Expected: 全 PASS / 0 errors（emit 出的 vite.config.js / *.d.ts 用 `git checkout --` 还原）

- [ ] **Step 3: 确认 dev-only 文件不在 diff**

Run: `git diff origin/main --name-only`
Expected: 不含 `frontend/src-tauri/tauri.conf.json`、不含 `frontend/src-tauri/Cargo.toml`。若有，`git restore --staged` + 确保未提交。

- [ ] **Step 4: 推分支 + 开 PR**（用户说发 PR 时才做）

```bash
git push -u origin feat/home-dashboard-redesign
gh pr create --title "feat(home): 首页工作台按图一重做（7 天真实指标）" --body "<总结 + 🤖 Generated with [Claude Code](https://claude.com/claude-code)>"
```
返回 PR URL，停在网页 merge。

---

## 自查（writing-plans self-review）

- **Spec 覆盖**：①百度/知乎/知乎搜索数字卡→Task4(+Task3 changed_prev)；②高权重信源→Task1+Task6；③GEO 仪表→Task2+Task5；④评论留存→Task7；⑤最近文档→沿用(Task8 仅布局)；移除视频抓取→Task8。全覆盖。
- **类型一致**：后端 kpis 加 `changed_prev`（Task3）↔ 前端读 `changed_prev`（Task4 Step4）一致；GEO summary 字段 `soc/delta/band`（Task2）↔ GaugeCard 读同名（Task5）一致；leaderboard `rank/rank_delta`（Task1）↔ SourceLeaderboardCard 读同名（Task6）一致；retention `rate_today/rate_prev/daily_series`（既有）↔ Task7 读同名一致。
- **占位扫描**：无 TBD/TODO；各步均有可跑命令与代码。Task8 的精确 span 明确交给 HMR 微调（非占位，是有意的真机调参）。
