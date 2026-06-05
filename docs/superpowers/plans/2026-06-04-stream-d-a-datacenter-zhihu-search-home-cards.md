# Stream D-A — 数据中心改名 + 知乎搜索分析页 + 首页 2 卡 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`).
>
> **Commits:** repo convention (Chinese `feat:`) + trailer `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.
>
> **Test commands (worktree gotchas):**
> - csm_core tests: `python -m pytest <path>` from repo root (csm_core resolves to worktree).
> - **sidecar tests REQUIRE the override** (else they import the main-repo copy): PowerShell `$env:PYTHONPATH="D:\CSM\.claude\worktrees\elastic-moore-fa05f4\sidecar"; python -m pytest <path> -v` — set it in the SAME command as pytest. Verify `csm_sidecar.__file__` prints a worktree path.
> - frontend type-check: `cd frontend; npx vue-tsc --noEmit` (node_modules already installed; do NOT use `vue-tsc -b` — it emits vite.config.js. If anything is emitted, `git checkout -- vite.config.js *.tsbuildinfo`). Never stage node_modules / package-lock.json / vite.config.js.

**Goal:** 数据中心「知乎排名」改名「知乎问题」并新增「知乎搜索」分析子页（含后端聚合端点），首页新增「知乎搜索」「GEO」两张卡片（6 卡 3×2）。

**Architecture:** 后端镜像现有 `history_service.get_baidu_keyword_history`（按 task×keyword 展开），但读 zhihu_search 的字段名（`matched_count`/`first_rank`，非 baidu 的 `default_*`），新增 `get_zhihu_search_history` + 路由；`get_summary` 扩展 `zhihu_search`/`geo_query` 两块给首页卡。前端：`DataCenterView` 改名+加 tab；新建 `ZhihuSearchAnalyticsPage.vue`（镜像 `ZhihuRankingPage.vue` 版式，列表绑定 keyword 行）；新建 `ZhihuSearchCard.vue`/`GeoCard.vue`（复用 `KeywordTrendCard`，镜像 `ZhihuCard.vue`）；`HomeView` 4→6 卡。**GEO 数据中心 tab + 页留到 Plan D-B**（本计划只加 GEO 首页卡，它点击跳已存在的 monitor geo tab）。

**Tech Stack:** Python (csm_sidecar) + pytest；Vue 3 `<script setup>` + Pinia + axios。

---

## File Structure

| 文件 | 责任 | 改动 |
|---|---|---|
| `sidecar/csm_sidecar/services/history_service.py` | 历史聚合查询 | + `get_zhihu_search_history()` |
| `sidecar/csm_sidecar/routes/monitor.py` | 路由 | + `GET /api/monitor/history/zhihu-search` |
| `sidecar/csm_sidecar/services/monitor_service.py` | summary | `PLATFORM_TYPES` 加 `zhihu_search`；`get_summary` 加 `zhihu_search`/`geo_query` 分支 |
| `frontend/src/views/DataCenterView.vue` | 数据中心壳 | 改名 + 知乎搜索 tab + handler + import |
| `frontend/src/components/monitor/history/ZhihuSearchAnalyticsPage.vue` | 新分析页 | 新建（镜像 ZhihuRankingPage）|
| `frontend/src/components/home/ZhihuSearchCard.vue` | 首页卡 | 新建（镜像 ZhihuCard）|
| `frontend/src/components/home/GeoCard.vue` | 首页卡 | 新建（复用 KeywordTrendCard）|
| `frontend/src/views/HomeView.vue` | 首页网格 | 4→6 卡，`lg:grid-cols-4`→`lg:grid-cols-3` |
| `sidecar/tests/test_history_routes.py` | 既有 | + zhihu-search 端点测试 |
| `sidecar/tests/test_monitor_summary*.py` | summary 测试 | + zhihu_search/geo 分支断言（位置见 Task 2）|

---

## Task 1: 后端 `/api/monitor/history/zhihu-search` 端点

**Files:**
- Modify: `sidecar/csm_sidecar/services/history_service.py` (add `get_zhihu_search_history`)
- Modify: `sidecar/csm_sidecar/routes/monitor.py` (add route, mirror `get_zhihu_ranking_history` route at lines 323–329)
- Test: `sidecar/tests/test_history_routes.py`

**背景:** zhihu_search 结果 metric 形如 `{ "keywords": [ {keyword, matched_count, first_rank, result_count, results, ...}, ... ], "search_keywords": [...], ... }`（见 `csm_core/monitor/platforms/zhihu_search.py` 的 metric 构造）。每行 = (task, keyword)。镜像 `get_baidu_keyword_history`（history_service.py:315–475）但字段名用 `matched_count`/`first_rank`。复用现有 `_parse_range`、`_classify_zhihu_change`、`_find_keyword_entry`、`_baidu_daily_series`。

- [ ] **Step 1: 写失败测试**

先读 `sidecar/tests/test_history_routes.py` 看现有 zhihu-ranking / baidu-keyword 端点测试怎么 seed monitor.db + 调用（mirror 它的 fixture）。然后追加一个测试，按同样的 fixture 方式：建一个 `zhihu_search` 任务（config `{"search_keywords": ["扫地机器人哪个好","自清洁扫地机"], "target_brand": "石头"}`）+ 一条 `ok` result，metric =
```python
{
    "keywords": [
        {"keyword": "扫地机器人哪个好", "matched_count": 3, "first_rank": 2, "result_count": 10, "results": [{"rank": 2, "matches_brand": True}]},
        {"keyword": "自清洁扫地机", "matched_count": 0, "first_rank": -1, "result_count": 8, "results": []},
    ],
    "search_keywords": ["扫地机器人哪个好", "自清洁扫地机"],
}
```
调用 `GET /api/monitor/history/zhihu-search?range=7d`，断言：
```python
assert resp.status_code == 200
body = resp.json()
assert body["range"] == "7d"
assert body["kpis"]["monitored_keywords"] == 2
kws = {k["search_keyword"]: k for k in body["keywords"]}
assert kws["扫地机器人哪个好"]["matched_count"] == 3
assert kws["扫地机器人哪个好"]["best_rank"] == 2
assert kws["自清洁扫地机"]["matched_count"] == 0
assert kws["自清洁扫地机"]["best_rank"] == -1
```
并加一个 `range` 非法值返回 400 的断言（mirror 现有端点测试）。

- [ ] **Step 2: 跑测试确认失败**

Run (override): `$env:PYTHONPATH="D:\CSM\.claude\worktrees\elastic-moore-fa05f4\sidecar"; python -m pytest sidecar/tests/test_history_routes.py -k zhihu_search -v`
Expected: FAIL — 404（路由不存在）。

- [ ] **Step 3: 实现 service 函数**

在 `history_service.py` 末尾（`get_baidu_keyword_history` 之后、`_find_keyword_entry` 附近）加：

```python
def get_zhihu_search_history(range_str: str) -> dict[str, Any]:
    """知乎搜索 KPI + 每日趋势 + (task×keyword) 关键词列表。

    镜像 get_baidu_keyword_history，但读 zhihu_search 的字段名
    (matched_count / first_rank)。每行 = 一个 (task, search_keyword)。
    """
    range_days = _parse_range(range_str)
    now = datetime.now()
    conn = storage.get_conn()
    rows = conn.execute(
        """
        SELECT r.task_id, r.checked_at, r.status, r.rank, r.metric_json,
               t.id AS t_id, t.name AS task_name, t.config_json
        FROM monitor_results r
        JOIN monitor_tasks t ON t.id = r.task_id
        WHERE t.type = 'zhihu_search'
          AND t.enabled = 1
          AND r.status = 'ok'
        ORDER BY r.task_id ASC, r.checked_at DESC
        """,
    ).fetchall()
    all_tasks = conn.execute(
        "SELECT id, name, config_json FROM monitor_tasks "
        "WHERE type='zhihu_search' AND enabled=1",
    ).fetchall()

    per_task: dict[int, list[dict]] = defaultdict(list)
    for row in rows:
        m = json.loads(row["metric_json"] or "{}")
        checked = storage._parse_iso(row["checked_at"])  # noqa: SLF001
        if not checked:
            continue
        per_task[row["task_id"]].append({
            "checked_at": checked,
            "metric": m,
            "task_name": row["task_name"],
        })

    keyword_rows = []
    for t in all_tasks:
        cfg = json.loads(t["config_json"] or "{}")
        results = per_task.get(t["id"], [])
        curr_result = results[0] if results else None
        prev_result = results[1] if len(results) > 1 else None
        curr_m = curr_result["metric"] if curr_result else {}
        prev_m = prev_result["metric"] if prev_result else {}

        search_keywords = list(cfg.get("search_keywords") or [])
        if not search_keywords and curr_m.get("search_keywords"):
            search_keywords = list(curr_m["search_keywords"])
        target_brand = cfg.get("target_brand", "")

        for kw in search_keywords:
            curr_kw = _find_keyword_entry(curr_m, kw)
            prev_kw = _find_keyword_entry(prev_m, kw)
            curr_matched = int((curr_kw or {}).get("matched_count") or 0) if curr_kw else 0
            curr_best = int((curr_kw or {}).get("first_rank") or -1) if curr_kw else -1
            prev_matched = (int(prev_kw.get("matched_count") or 0)) if prev_kw else None
            prev_best = (int(prev_kw.get("first_rank") or -1)) if prev_kw else None

            _curr = {"matched_count": curr_matched, "best_rank": curr_best, "top_n": 10} if curr_kw else None
            _prev = {"matched_count": (prev_matched or 0), "best_rank": (prev_best or -1), "top_n": 10} if prev_kw else None
            kind, _ = _classify_zhihu_change(_curr, _prev)

            results_list = (curr_kw or {}).get("results") or []
            matched_ranks = [r["rank"] for r in results_list if r.get("matches_brand")]

            keyword_rows.append({
                "task_id": t["id"],
                "task_name": t["name"],
                "search_keyword": kw,
                "target_brand": target_brand,
                "matched_count": curr_matched,
                "matched_count_prev": prev_matched,
                "top_n": 10,
                "matched_ranks": matched_ranks,
                "best_rank": curr_best,
                "best_rank_prev": prev_best,
                "change_kind": kind,
                "checked_at": (curr_result["checked_at"].isoformat() if curr_result else None),
            })

    monitored_keywords = len(keyword_rows)
    hit_count_total = sum(k["matched_count"] for k in keyword_rows)
    topn_total = monitored_keywords * 10
    avg_match_rate_today = (hit_count_total / topn_total) if topn_total else 0.0
    hit_count_prev = sum((k["matched_count_prev"] or 0) for k in keyword_rows if k["matched_count_prev"] is not None)
    topn_prev_total = sum(10 for k in keyword_rows if k["matched_count_prev"] is not None)
    avg_match_rate_prev = (hit_count_prev / topn_prev_total) if topn_prev_total else 0.0
    changed_down = sum(1 for k in keyword_rows if k["change_kind"] in ("down", "dropped"))
    changed_up = sum(1 for k in keyword_rows if k["change_kind"] in ("up", "new"))
    brands_covered = len({
        json.loads(t["config_json"] or "{}").get("target_brand", "")
        for t in all_tasks if json.loads(t["config_json"] or "{}").get("target_brand")
    })
    daily_series = _baidu_daily_series(per_task, all_tasks, range_days=range_days, now=now)

    return {
        "range": range_str,
        "kpis": {
            "monitored_keywords": monitored_keywords,
            "brands_covered": brands_covered,
            "avg_match_rate_today": avg_match_rate_today,
            "avg_match_rate_prev": avg_match_rate_prev,
            "hit_count_total": hit_count_total,
            "topn_total": topn_total,
            "changed_keywords": changed_down + changed_up,
            "changed_up": changed_up,
            "changed_down": changed_down,
        },
        "daily_series": daily_series,
        "keywords": keyword_rows,
    }
```

**⚠️ 实现确认:** `_find_keyword_entry(metric, kw)` 按 `entry.get("keyword")==kw` 查（history_service.py:478–484）。先确认 zhihu_search 的 `metric["keywords"][i]` 真有 `keyword` 字段（读 `csm_core/monitor/platforms/zhihu_search.py` entry 构造，约 line 290）。若没有、而是按 `search_keywords` 顺序对齐，则改用按位置取（`curr_m["keywords"][idx]`）。同时确认 `_baidu_daily_series` 读的字段（若它依赖 baidu 的 `default_*`，则需为 zhihu_search 写一个 `_zhihu_search_daily_series` 变体或传入字段名参数 —— 读它的实现确定）。

- [ ] **Step 4: 加路由**

在 `routes/monitor.py` 紧挨现有 zhihu-ranking 路由（约 323–329）后加：
```python
@router.get("/api/monitor/history/zhihu-search")
def get_zhihu_search_history(range_str: str = Query("7d", alias="range")) -> dict[str, Any]:
    _require_storage()
    try:
        return history_service.get_zhihu_search_history(range_str=range_str)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
```

- [ ] **Step 5: 跑测试确认通过**

Run (override): `$env:PYTHONPATH="D:\CSM\.claude\worktrees\elastic-moore-fa05f4\sidecar"; python -m pytest sidecar/tests/test_history_routes.py -v`
Expected: PASS（新增用例 + 既有用例）。

- [ ] **Step 6: 提交**
```bash
git add sidecar/csm_sidecar/services/history_service.py sidecar/csm_sidecar/routes/monitor.py sidecar/tests/test_history_routes.py
git commit -m "feat(monitor): 知乎搜索数据中心聚合端点 /api/monitor/history/zhihu-search"
```

---

## Task 2: 扩展 `/api/monitor/summary` 给首页知乎搜索 + GEO 卡

**Files:**
- Modify: `sidecar/csm_sidecar/services/monitor_service.py` (`PLATFORM_TYPES` + `get_summary` lines 159–220)
- Test: `sidecar/tests/` —— 先 Glob `sidecar/tests/*summary*` / grep `get_summary` 找现有 summary 测试文件；没有就新建 `sidecar/tests/test_monitor_summary_cards.py`。

- [ ] **Step 1: 写失败测试**

Seed 一个 `zhihu_search` 任务 + 一条 result（metric `{"total_matches": 5, "best_first_rank": 2, "matched_keywords": 2}`）和一个 `geo_query` 任务 + result（metric `{"soc": 0.58, "sentiment_score": 0.3, "mentioned": 4}`）。调 `monitor_service.get_summary()`，断言：
```python
s = get_summary()
zs = s["platforms"]["zhihu_search"]
assert zs["task_count"] == 1
assert zs["tasks"][0]["latest"] is not None
assert "series" in zs["tasks"][0]
geo = s["platforms"]["geo_query"]["tasks"][0]
assert geo["kpi_snapshot"]["soc"] == 0.58
assert "series" in geo
```

- [ ] **Step 2: 跑失败** (override) `... pytest sidecar/tests/test_monitor_summary_cards.py -v` → FAIL（`KeyError: 'zhihu_search'`，PLATFORM_TYPES 不含它）。

- [ ] **Step 3: 实现**

(a) 找到 `PLATFORM_TYPES` 定义（monitor_service.py，grep `PLATFORM_TYPES =`），把 `"zhihu_search"` 加进去（保持 `geo_query` 已在内）。

(b) 在 `get_summary` 的 `if ttype == "zhihu_question":` 分支后，新增两个 `elif`（放在 `else:` 之前）:
```python
            elif ttype == "zhihu_search":
                recent = storage.list_results(t.id, limit=7)
                latest = recent[0] if recent else None
                prev = recent[1] if len(recent) > 1 else None
                entry["latest"] = result_to_dict(latest) if latest else None
                entry["prev"] = result_to_dict(prev) if prev else None
                entry["series"] = [
                    {
                        "checked_at": r.checked_at.isoformat() if r.checked_at else None,
                        "matched": int((r.metric or {}).get("total_matches") or 0),
                    }
                    for r in reversed(recent)
                ]
            elif ttype == "geo_query":
                recent = storage.list_results(t.id, limit=7)
                latest = recent[0] if recent else None
                entry["latest"] = result_to_dict(latest) if latest else None
                entry["series"] = [
                    {
                        "checked_at": r.checked_at.isoformat() if r.checked_at else None,
                        "soc": float((r.metric or {}).get("soc") or 0.0),
                    }
                    for r in reversed(recent)
                ]
                m0 = (latest.metric or {}) if latest else {}
                entry["kpi_snapshot"] = {
                    "soc": float(m0.get("soc") or 0.0),
                    "sentiment": float(m0.get("sentiment_score") or 0.0),
                    "mentioned": int(m0.get("mentioned") or 0),
                }
```

- [ ] **Step 4: 跑通过** (override) → PASS.

- [ ] **Step 5: 提交**
```bash
git add sidecar/csm_sidecar/services/monitor_service.py sidecar/tests/test_monitor_summary_cards.py
git commit -m "feat(monitor): summary 增加 zhihu_search / geo 摘要（首页卡用）"
```

---

## Task 3: DataCenterView 改名 + 知乎搜索 tab

**Files:** Modify `frontend/src/views/DataCenterView.vue`

- [ ] **Step 1: 改名 + 类型 + tab 数组**

(a) line 21 类型加 `zhihu_search`：
```typescript
type HistorySubtab = "retention" | "zhihu" | "baidu" | "zhihu_search";
```
(b) lines 30–34 `HISTORY_TABS`：把 `{ k: "zhihu", l: "知乎排名" }` 的 label 改 `"知乎问题"`，并插入知乎搜索（放在知乎问题后）：
```typescript
const HISTORY_TABS: Array<{ k: HistorySubtab; l: string }> = [
  { k: "zhihu", l: "知乎问题" },
  { k: "zhihu_search", l: "知乎搜索" },
  { k: "retention", l: "平台评论" },
  { k: "baidu", l: "百度排名" },
];
```

- [ ] **Step 2: import + handler + render**

(a) import（line 19 附近）：`import ZhihuSearchAnalyticsPage from "@/components/monitor/history/ZhihuSearchAnalyticsPage.vue";`
(b) 在 `goToZhihuTask` 后加：
```typescript
function goToZhihuSearchTask(payload: { taskId: number }) {
  router.push({ name: "monitor", query: { tab: "zhihu_search", task: payload.taskId } });
}
```
(c) 在模板 ZhihuRankingPage 渲染块后加：
```vue
        <ZhihuSearchAnalyticsPage
          v-else-if="historySubtab === 'zhihu_search'"
          @navigate="goToZhihuSearchTask"
        />
```

- [ ] **Step 3: 类型检查**（先做完 Task 4 再 typecheck，因为引用了新组件；或先建空壳。建议顺序 Task 4 → Task 3 Step 3）

Run: `cd frontend; npx vue-tsc --noEmit` → 无新错误。

- [ ] **Step 4: 提交**
```bash
git add frontend/src/views/DataCenterView.vue
git commit -m "feat(monitor-ui): 数据中心 知乎排名→知乎问题 + 新增知乎搜索子页"
```

---

## Task 4: ZhihuSearchAnalyticsPage.vue（镜像 ZhihuRankingPage）

**Files:** Create `frontend/src/components/monitor/history/ZhihuSearchAnalyticsPage.vue`

**做法:** 复制 `frontend/src/components/monitor/history/ZhihuRankingPage.vue` 全文为新文件，然后按下表改（结构/版式/range picker/KPI 卡/图表/列表滚动全部保留不动）：

- [ ] **Step 1: 复制并改 script**

- 顶部注释改成「知乎搜索页」，端点 `zhihu-search`。
- `interface Question` → `interface KeywordRow`，字段改成 endpoint 返回的：`task_id, search_keyword, target_brand, matched_count, matched_count_prev, top_n, matched_ranks, best_rank, best_rank_prev, change_kind, checked_at`。
- `interface Kpis` 改成端点的 KPI 字段：`monitored_keywords, brands_covered, avg_match_rate_today, avg_match_rate_prev, hit_count_total, topn_total, changed_keywords, changed_up, changed_down`。
- `interface ZhihuResponse` → `ZhihuSearchResponse { range; kpis: Kpis; daily_series: DailyPoint[]; keywords: KeywordRow[] }`。`DailyPoint` 改 `avg_match_rate` 字段名（与 `_baidu_daily_series` 输出一致 —— 读它确认字段名，可能是 `avg_share`/`avg_match_rate`；据此绑定）。
- `load()` 的 URL 改 `"/api/monitor/history/zhihu-search"`。
- `filtered` / `chartLabels` / `chartSeries` 改读 `data.value.keywords` / `daily_series`，chart 第一条 series 数据用 `avg_match_rate`（或日序列实际字段）。
- `rankChangeText(q)` 参数类型改 `KeywordRow`，逻辑不变（读 best_rank/best_rank_prev/change_kind）。

- [ ] **Step 2: 改 template 文案/绑定**

- KPI 1 标题「监测问题数」→「监测关键词数」，`data.kpis.monitored_questions`→`monitored_keywords`。
- KPI 2「品牌占有率（平均）」可保留语义为「平均命中率」，`avg_share_today`→`avg_match_rate_today`、`avg_share_prev`→`avg_match_rate_prev`。
- KPI 3「排名异动问题」→「异动关键词」，`changed_questions`→`changed_keywords`。
- 列表列头「关键词 / 卡位 / 排名 / 状态」保留；行里 `q.title`→`q.search_keyword`，`q.matched_count`（命中数）、`q.best_rank`（首位排名）绑定不变。
- `v-for="q in filtered" :key="q.task_id"` —— 注意 (task×keyword) 行 task_id 可能重复，改 `:key="`${q.task_id}-${q.search_keyword}`"`。
- 点击 `emit('navigate', { taskId: q.task_id })` 不变。

- [ ] **Step 3: 类型检查** `cd frontend; npx vue-tsc --noEmit` → 无新错误（连同 Task 3 的引用）。

- [ ] **Step 4: 提交**
```bash
git add frontend/src/components/monitor/history/ZhihuSearchAnalyticsPage.vue
git commit -m "feat(monitor-ui): 知乎搜索数据中心分析页（镜像知乎问题）"
```

---

## Task 5: 首页 ZhihuSearchCard + GeoCard + 6 卡网格

**Files:**
- Create `frontend/src/components/home/ZhihuSearchCard.vue`, `frontend/src/components/home/GeoCard.vue`
- Modify `frontend/src/views/HomeView.vue`

- [ ] **Step 1: ZhihuSearchCard（镜像 ZhihuCard）**

复制 `frontend/src/components/home/ZhihuCard.vue` → `ZhihuSearchCard.vue`，改：
- 数据源 line 149：`r.data.platforms?.zhihu_search?.tasks ?? []`。
- `matchedCount(snap)`：读 `snap.metric?.total_matches`（zhihu_search 没有 matched_count，用 total_matches）。
- `rowSeries`：series 点字段是 `matched`（见 Task 2 zhihu_search series），改 `t.series.map(p => p.matched)`；`SeriesPoint` 接口字段 `matched_count`→`matched`。
- `category="知乎搜索"`，`goDetail`/`onItemClick` 的 `tab: "zhihu"`→`"zhihu_search"`，`empty-title="暂无知乎搜索任务"`。

- [ ] **Step 2: GeoCard（复用 KeywordTrendCard，按 soc）**

复制 `ZhihuCard.vue` → `GeoCard.vue`，改：
- 数据源：`r.data.platforms?.geo_query?.tasks ?? []`。
- `MonitorTaskRow` 加可选 `kpi_snapshot?: { soc: number; sentiment: number; mentioned: number }`，`SeriesPoint` 字段 `{ checked_at; soc: number }`。
- severity/badge 按 soc delta：`socOf(snap) = Number(snap.metric?.soc ?? 0)`；delta = latest.soc - prev.soc；up/down/flat。badge 文本显示百分比变化（`Math.round(|delta|*100)`）。
- `rowSeries`：`t.series.map(p => Math.round(p.soc * 100))`；`yMax: 100`。
- `category="GEO · AI 卡位"`，`onItemClick`/`goDetail` 用 `tab: "geo"`（monitor 已有 geo tab），`empty-title="暂无 GEO 任务"`。

- [ ] **Step 3: HomeView 6 卡 3×2**

`frontend/src/views/HomeView.vue`：
- import 两个新卡。
- 网格 class（line ~69）`lg:grid-cols-4` → `lg:grid-cols-3`。
- 卡列表（lines 72–76）加 `<ZhihuSearchCard />` `<GeoCard />`（共 6）。

- [ ] **Step 4: 类型检查** `cd frontend; npx vue-tsc --noEmit` → 无新错误。

- [ ] **Step 5: dev 手测（可选，建议）**

起 dev（worktree：`$env:PYTHONPATH=<worktree>/sidecar`，`run_in_background`）；首页应显示 6 卡 3×2，知乎搜索/GEO 卡渲染（空态也行）；数据中心 5 子 tab 切换、知乎排名显示为「知乎问题」、「知乎搜索」页加载。

- [ ] **Step 6: 提交**
```bash
git add frontend/src/components/home/ZhihuSearchCard.vue frontend/src/components/home/GeoCard.vue frontend/src/views/HomeView.vue
git commit -m "feat(home): 首页新增知乎搜索 + GEO 卡片（6 卡 3×2）"
```

---

## Self-Review

**Spec coverage（对照 spec §D1/D2/D5）:**
- 数据中心改名知乎排名→知乎问题 → Task 3 ✓
- 新增知乎搜索数据中心页 → Task 1（端点）+ Task 4（页）✓
- 首页新增知乎搜索 + GEO 卡（6 卡 3×2）→ Task 2（summary）+ Task 5 ✓
- GEO 数据中心 tab/页 → **不在本计划**（Plan D-B），本计划只加 GEO 首页卡（点击跳已存在的 monitor geo tab）。这是有意拆分。

**Placeholder scan:** 后端给了完整代码；前端用「复制 X + 指定改动」（执行者可读源文件），每处改动已具体列出，非占位。两处「实现确认」（zhihu_search keyword 字段名 / `_baidu_daily_series` 字段）已显式标注 —— 执行者读对应文件确认后据实绑定。

**Type/契约一致性:** 端点返回 `keywords[]` 字段名（search_keyword/matched_count/best_rank/change_kind）↔ Task 4 页 interface 一致；summary 的 series 字段（zhihu_search=`matched`、geo=`soc`）↔ Task 5 卡读取一致；`kpi_snapshot.soc` ↔ GeoCard 读取一致。

**风险/执行注意:**
- (task×keyword) 行 `:key` 必须带 keyword，否则 Vue 复用错行。
- `_baidu_daily_series` 若强依赖 baidu 的 `default_*` 字段，zhihu_search 复用会算错 → 读其实现，必要时写 `_zhihu_search_daily_series`。
- summary 加 `zhihu_search` 到 PLATFORM_TYPES 后，其他读 summary 的地方（评论卡等）不受影响（只是多一个 key）。
- 顺序建议：Task 1 → 2（后端，可独立测）→ Task 4（建页）→ Task 3（接 tab）→ Task 5（卡）。每步 typecheck/pytest。
