# Stream D-B — GEO 数据中心分析页 + 规范信源/权重 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development (or executing-plans). Steps use `- [ ]`.
> **Commits:** Chinese `feat:` + trailer `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.
> **Tests:**
> - **csm_core tests (Tasks 1–2: classify + leaderboard) run WITHOUT override** — `python -m pytest tests/core/monitor/geo/<f> -v` from repo root (csm_core resolves to worktree).
> - frontend type-check: `cd frontend; npx vue-tsc --noEmit` (node_modules installed; NOT `vue-tsc -b`; restore any emitted vite.config.js/tsbuildinfo via `git checkout --`; never stage node_modules/package-lock.json/vite.config.js).

**Goal:** 新增「GEO」数据中心分析页（按品牌：选一个 geo_query 任务 → 该品牌的关键词×AI平台矩阵 + 高权重信源榜 + KPI/趋势），并实现规范信源聚合（*.zhihu.com 合并、百度系/微信按产品拆）+ 权重 = 被引频次 × 覆盖平台数 × 信源类型权威度。

**Architecture:** 后端 `classify.py` 加 canonical host 拆分（百度系/微信，写入时生效）+ authority 权重表；`citation_leaderboard` 加 `weight` 字段并按权重排序（被引/覆盖平台/source_type 已在手）。前端复用 80% 现有 GEO 组件：新 `useGeoAnalytics`（基于 `useGeoKeywordDetail`，但一次 `/latest-cells` 取全部关键词、`/citations` 不传 keyword=全量带权重信源榜）、fork `GeoRankHeatmap`→`GeoKeywordMatrix`（行=关键词，列=平台，格=品牌在该格状态，复用 `cellStatus`）、reuse `GeoSourceList`（加 weight 条）/`GeoTrend`/`GeoHero`；装配成 `GeoAnalyticsPage.vue`，挂进 `DataCenterView` 第 5 个 tab。

**Tech Stack:** Python (csm_core.monitor.geo) + pytest；Vue 3 `<script setup>` + axios。

**⚠️ 已知约束（写进设计）：百度系拆分只对「新跑的数据」生效** —— `geo_citations` 只存合并后的注册域名（`record_run` 写 `cit.domain`），老行已是 `baidu.com`。拆分逻辑在 classify/写入层，需重跑任务才体现。`*.zhihu.com`→知乎 合并读侧就生效。

---

## File Structure

| 文件 | 责任 | 改动 |
|---|---|---|
| `csm_core/monitor/geo/classify.py` | 域名规整+分类 | + `_CANONICAL_HOST`/`_AUTHORITY`/`authority()`/`canonical_source()`；`classify_citations` 改用 canonical |
| `csm_core/monitor/geo/storage.py` | 聚合查询 | `citation_leaderboard` 加 `weight` + 按权重排序 |
| `tests/core/monitor/geo/test_classify.py` | 既有 | + canonical/authority 测试 |
| `tests/core/monitor/geo/test_storage.py` | 既有 | + weight 排序测试 |
| `frontend/src/components/monitor/geo/geoDetail.ts` | 数据层 | `BoardRow` 加 `weight`；+ `useGeoAnalytics` composable |
| `frontend/src/components/monitor/geo/GeoKeywordMatrix.vue` | 新组件 | fork GeoRankHeatmap（关键词×平台）|
| `frontend/src/components/monitor/geo/GeoSourceList.vue` | 信源榜 | bar 用 weight；显示 weight |
| `frontend/src/components/monitor/geo/GeoAnalyticsPage.vue` | 新页 | 装配（任务选择器+KPI+矩阵+信源榜+趋势+点格下钻）|
| `frontend/src/views/DataCenterView.vue` | 数据中心壳 | + GEO tab |

---

## Task 1: classify.py — 规范信源拆分 + 权威度表

**Files:** Modify `csm_core/monitor/geo/classify.py`; Test `tests/core/monitor/geo/test_classify.py`

- [ ] **Step 1: 失败测试** — 追加到 `test_classify.py`：
```python
def test_canonical_splits_baidu_products():
    from csm_core.monitor.geo.classify import canonical_source
    assert canonical_source("https://baijiahao.baidu.com/s?id=1") == ("baijiahao.baidu.com", "百家号")
    assert canonical_source("https://baike.baidu.com/item/x") == ("baike.baidu.com", "百度百科")
    assert canonical_source("https://zhidao.baidu.com/q/1") == ("zhidao.baidu.com", "百度知道")
    assert canonical_source("https://mp.weixin.qq.com/s/abc") == ("mp.weixin.qq.com", "微信公众号")

def test_canonical_merges_zhihu_subdomains():
    from csm_core.monitor.geo.classify import canonical_source
    assert canonical_source("https://zhuanlan.zhihu.com/p/1") == ("zhihu.com", "知乎")
    assert canonical_source("https://www.zhihu.com/question/1") == ("zhihu.com", "知乎")

def test_authority_table():
    from csm_core.monitor.geo.classify import authority
    assert authority("权威媒体") > authority("知乎") > authority("其他")
    assert authority("未知类型") == authority("其他")

def test_classify_citations_uses_canonical():
    from csm_core.monitor.geo.classify import classify_citations
    from csm_core.monitor.geo.models import Citation
    out = classify_citations([Citation(url="https://baijiahao.baidu.com/s?id=1", title="t")])
    assert out[0].domain == "baijiahao.baidu.com"
    assert out[0].source_type == "百家号"
```

- [ ] **Step 2: 跑失败** `python -m pytest tests/core/monitor/geo/test_classify.py -k "canonical or authority" -v` → ImportError/AssertionError.

- [ ] **Step 3: 实现** — 在 `classify.py` `_RULES` 之后加：
```python
# host 级拆分：一个主域名下的多个独立内容平台，注册域名会合并掉它们，
# 所以在「完整 host」层识别后拆开（百度系/微信）。⚠️ 写入时生效：
# geo_citations 存的是这里产出的 domain，老数据是合并态，需重跑才体现。
_CANONICAL_HOST: dict[str, tuple[str, str]] = {
    "baijiahao.baidu.com": ("baijiahao.baidu.com", "百家号"),
    "baike.baidu.com": ("baike.baidu.com", "百度百科"),
    "zhidao.baidu.com": ("zhidao.baidu.com", "百度知道"),
    "tieba.baidu.com": ("tieba.baidu.com", "贴吧"),
    "mp.weixin.qq.com": ("mp.weixin.qq.com", "微信公众号"),
}

# source_type → 权威度基数（高权重信源排序用）。未知类型回退「其他」。
_AUTHORITY: dict[str, float] = {
    "权威媒体": 1.0, "百度百科": 0.9, "知乎": 0.8,
    "百家号": 0.6, "微信公众号": 0.6, "小红书": 0.6,
    "百度知道": 0.5, "电商": 0.4, "贴吧": 0.3, "其他": 0.2,
}


def authority(source_type: str) -> float:
    return _AUTHORITY.get(source_type, _AUTHORITY["其他"])


def _host(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower().strip(".")
    except Exception:
        return ""


def canonical_source(url: str) -> tuple[str, str]:
    """(canonical domain, source_type)。先查 host 级拆分表（百度系/微信），
    否则注册域名 + 规则分类（*.zhihu.com 在 registered_domain 合并）。"""
    host = _host(url)
    if host in _CANONICAL_HOST:
        return _CANONICAL_HOST[host]
    dom = registered_domain(url)
    return dom, classify_source(dom)
```
并把 `classify_citations` 改成用 canonical：
```python
def classify_citations(cits: list[Citation]) -> list[ClassifiedCitation]:
    out: list[ClassifiedCitation] = []
    for c in cits:
        dom, st = canonical_source(c.url)
        out.append(ClassifiedCitation(url=c.url, title=c.title, domain=dom, source_type=st))
    return out
```

- [ ] **Step 4: 跑通过** `python -m pytest tests/core/monitor/geo/test_classify.py -v` → PASS（含既有用例；既有 `classify_source`/`registered_domain` 行为不变）。

- [ ] **Step 5: 提交** `git add csm_core/monitor/geo/classify.py tests/core/monitor/geo/test_classify.py` → `feat(geo): 规范信源 canonical_source（百度系/微信拆分、知乎合并）+ authority 权重表`

---

## Task 2: citation_leaderboard — 加 weight + 按权重排序

**Files:** Modify `csm_core/monitor/geo/storage.py`; Test `tests/core/monitor/geo/test_storage.py`

- [ ] **Step 1: 失败测试** — 追加（用既有 `_seed_run`/`fresh_db` fixture 风格）：seed 一个任务，cells 含多个信源（如 zhihu×2平台、一个权威媒体×1平台），调 `citation_leaderboard(tid, days=3650)`，断言每行有 `weight` 字段，且排序按 `weight` 降序（不是 count）。例如构造「count 低但 authority 高、覆盖平台多」的源排到前面来验证权重生效。具体断言：
```python
def test_citation_leaderboard_has_weight_and_sorts_by_it(fresh_db):
    # 用 _seed_run 的扩展：构造两个源，让 weight 排序 != count 排序
    ...
    board = geo_storage.citation_leaderboard(tid, days=3650)
    assert all("weight" in b for b in board)
    # weight = count * len(platforms) * authority(source_type)，降序
    weights = [b["weight"] for b in board]
    assert weights == sorted(weights, reverse=True)
```
（参考 `test_storage.py` 现有 `_seed_run`；可再加一个权威媒体源让 authority 区分开。）

- [ ] **Step 2: 跑失败** `python -m pytest tests/core/monitor/geo/test_storage.py -k weight -v` → KeyError 'weight'.

- [ ] **Step 3: 实现** — `storage.py` 顶部加 `from .classify import authority`；把 `citation_leaderboard` 的 `out`/`out.sort` 改为：
```python
    out = [{
        "domain": e["domain"], "source_type": e["source_type"], "count": e["count"],
        "platforms": sorted(e["_plats"]), "keywords": sorted(e["_kws"]),
        "weight": round(e["count"] * len(e["_plats"]) * authority(e["source_type"]), 2),
    } for e in agg.values()]
    out.sort(key=lambda e: (-e["weight"], -e["count"], e["domain"]))
    return out
```
（`weight` 加进每行；排序主键改 weight 降序，count、domain 做 tie-break。其余不变。`geo_export` 路由读 `b["count"]`/`b["platforms"]` 不受影响；可选：导出多加一列 weight —— 本任务不强制。）

- [ ] **Step 4: 跑通过** `python -m pytest tests/core/monitor/geo/test_storage.py -v` → PASS（含既有 `test_citation_leaderboard_ranks_by_freq` —— 注意：若既有测试硬断言纯频次排序，weight 排序在单源/同 authority 下仍等价；若它因排序变化失败，更新该断言为 weight 语义并保留 count 断言）。

- [ ] **Step 5: 提交** `git add csm_core/monitor/geo/storage.py tests/core/monitor/geo/test_storage.py` → `feat(geo): 信源榜 weight=被引×覆盖平台×权威度 + 按权重排序`

---

## Task 3: useGeoAnalytics composable + BoardRow.weight

**Files:** Modify `frontend/src/components/monitor/geo/geoDetail.ts`

新增一个跨关键词的 composable（基于 `useGeoKeywordDetail`），供 GeoAnalyticsPage 用。复用其 `cellToPlatform`/`orderPlatforms`/`PlatformVM`/`HistoryPoint` 等。

- [ ] **Step 1: BoardRow 加 weight** —— `interface BoardRow` 加 `weight: number;`。

- [ ] **Step 2: 新增 `useGeoAnalytics`**（放在 `useGeoKeywordDetail` 之后）。它接收 `taskId: Ref<number|null>` + `brandTerms: Ref<string[]>` + `configuredKeywords: Ref<string[]>`（任务 config.keywords，用于矩阵行顺序/补空）+ `configuredPlatforms: Ref<string[]>`（列顺序/补空），返回：
```typescript
interface GeoAnalytics {
  keywords: string[];                                  // 矩阵行（config.keywords 优先，落到有数据的）
  platformIds: string[];                               // 矩阵列（orderPlatforms 后的平台 id）
  matrix: Record<string, Record<string, PlatformVM>>;  // matrix[keyword][platformId] = cell VM
  metric: TopMetric | null;                            // 顶层聚合 KPI（soc/sentiment_score/mentioned/...）
  history: HistoryPoint[];                             // 顶层 soc 趋势（最近 7 天）
  board: BoardRow[];                                   // 全关键词带权重信源榜（已按 weight 排）
  lastRunIso: string | null;
}
```
实现要点（镜像 `useGeoKeywordDetail` 的 Promise.all + race guard，差异如下）：
- `/latest-cells`：一次取全部，**不按关键词过滤**；按 `c.keyword` 分组，对每个 cell 跑 `cellToPlatform(c, brandTerms)`；`platformIds = orderPlatforms(所有出现过的平台 VM).map(p=>p.id)` 去重；`keywords = configuredKeywords 优先，回退到 cells 里出现的关键词集合`；`matrix[kw][platformId] = 该 cell 的 PlatformVM`。
- `/api/monitor/results?task_id&limit=8`：`metric = results[0].metric`（**顶层**聚合，不是 by_keyword —— 顶层有 soc/sentiment_score/mentioned/ok_total/total，见 `csm_core/monitor/geo/metrics.aggregate`）；`history` 同 `useGeoKeywordDetail` 但用顶层 `m.soc`/`m.first_rank_rate`（不取 by_keyword）。`TopMetric` 用一个本地 interface（soc, sentiment_score, mentioned, ok_total, total, status_band 可选）。
- `/citations`：**不传 keyword**（=全量）；`board = lb.map(r => ({ domain:r.domain, type:r.source_type, count:r.count, platforms: r.platforms?.length ?? 0, weight: r.weight ?? 0 }))`（后端已按 weight 排序；前端保序）。
- watch `[taskId, brandTerms, configuredKeywords, configuredPlatforms]` immediate 重拉；`loading`/`error` 同款。

- [ ] **Step 3: 类型检查** `cd frontend; npx vue-tsc --noEmit` → 无新错误。
- [ ] **Step 4: 提交** `git add frontend/src/components/monitor/geo/geoDetail.ts` → `feat(geo-ui): useGeoAnalytics 跨关键词数据层 + BoardRow.weight`

---

## Task 4: GeoKeywordMatrix + GeoSourceList weight + GeoAnalyticsPage + 数据中心 GEO tab

**Files:** Create `GeoKeywordMatrix.vue`, `GeoAnalyticsPage.vue`; Modify `GeoSourceList.vue`, `DataCenterView.vue`

- [ ] **Step 1: GeoKeywordMatrix.vue（fork GeoRankHeatmap）** —— 复制 `GeoRankHeatmap.vue`，改：
  - props: `{ keywords: string[]; platformIds: string[]; matrix: Record<string, Record<string, PlatformVM>> }`。
  - import `cellStatus` + `platformShort` from geoDetail。
  - 表头列：`v-for p in platformIds` → `platformShort(p)`。
  - 行：`v-for kw in keywords`，行首格显示 `kw`（截断+title）。
  - 单元格：`const vm = matrix[kw]?.[p]`；显示 `vm ? cellStatus(vm).short : '·'`，颜色 `vm ? cellStatus(vm).color : 'var(--ink-4)'`，空格淡边框（仿原 `·` 样式）。
  - `@click` 单元格 → `emit('cell', { keyword: kw, platformId: p })`（仅当 vm 存在）。
  - `cols = computed(() => \`120px repeat(${platformIds.length}, 1fr)\`)`（行首给关键词更宽）。
  - 删掉原 `competitors`/`rankOf`/`cellStyleOf`（用 cellStatus 替代）。
  - emits: `defineEmits<{ cell: [payload: { keyword: string; platformId: string }] }>()`。

- [ ] **Step 2: GeoSourceList 显示 weight** —— `GeoSourceList.vue`：
  - `maxCount` 旁加 `const maxWeight = computed(() => Math.max(1, ...props.board.map((b) => b.weight)));`
  - 进度条宽度 `b.count / maxCount` 改 `b.weight / maxWeight`。
  - 右侧「N 次引用」上方/下方加一行权重：`<div :style="...">权重 {{ b.weight }}</div>`（小字，复用既有样式风格）。
  - `BoardRow` 已在 Task 3 加 `weight`，type 不再报错。

- [ ] **Step 3: GeoAnalyticsPage.vue（新页，装配）** —— 新建 `frontend/src/components/monitor/geo/GeoAnalyticsPage.vue`：
  - `<script setup>`：
    - load geo 任务：`GET /api/monitor/tasks?type=geo_query` → `tasks`（仿 GeoTaskModule.loadTasks）。`selectedTaskId = ref<number|null>`，onMounted 后默认选第一个。
    - `selectedTask` computed；`brandTermsOf`/`keywordsOf`/`platformsOf`（仿 GeoTaskModule lines 75-108，用 config.brand/keywords/brand_aliases/platforms）。
    - `const { keywords, platformIds, matrix, metric, history, board, loading } = useGeoAnalytics(selectedTaskId, selectedBrandTerms, selectedKeywords, selectedPlatforms)` —— 注意 useGeoAnalytics 返回的是一个 reactive 对象/refs，按 Task 3 的返回结构解构（若返回单个 `analytics: Ref<GeoAnalytics|null>`，则模板读 `analytics.keywords` 等；实现时二选一并保持一致）。
    - `selectedCell = ref<PlatformVM|null>(null)`；`onCell({keyword,platformId})` → `selectedCell.value = matrix[keyword]?.[platformId] ?? null`（点格下钻）。
  - `<template>`（复用现有卡片骨架/样式变量）：
    - 顶部：品牌选择器（`<select>` 或 FormSelect 绑 selectedTaskId，options = tasks 的 brand/name）。
    - KPI 行：监测关键词数(`keywords.length`) / 平均曝光率(`metric.soc` → %) / 平均情感(`metric.sentiment_score`) / 高权重信源数(`board.length`)。可用简单卡片或复用 `GeoHero`（GeoHero 需要 KeywordMetric 形状，metric 顶层字段大体兼容；不兼容就用简单 KPI 卡）。
    - `GeoKeywordMatrix :keywords :platform-ids :matrix @cell="onCell"`。
    - 点格后：`<GeoPlatformBlock v-if="selectedCell" :platform="selectedCell" :brand="brand" :brand-terms="brandTerms" />`（复用，展示该格回答原文+引用信源）。
    - `GeoSourceList :board :total="platformIds.length" :task-id="selectedTaskId" keyword=""`（信源榜；keyword 传空=全量）。
    - `GeoTrend :history`（趋势）。
  - 空态：无 geo 任务 → 提示去监测中心建。

- [ ] **Step 4: DataCenterView 加 GEO tab** —— `frontend/src/views/DataCenterView.vue`：
  - type `HistorySubtab` 加 `"geo"`。
  - `HISTORY_TABS` 末尾加 `{ k: "geo", l: "GEO" }`。
  - import `GeoAnalyticsPage`。
  - 加 handler `goToGeoTask({taskId})` → `router.push({ name:"monitor", query:{ tab:"geo", task: payload.taskId } })`（若 GeoAnalyticsPage 不 emit navigate 可省，但为一致性保留并在模板绑定 `@navigate` 若页面有）。
  - 模板：`<GeoAnalyticsPage v-else-if="historySubtab === 'geo'" />`（GeoAnalyticsPage 自带任务选择，不需要 navigate；如实现了 cell→navigate 则绑定）。

- [ ] **Step 5: 类型检查** `cd frontend; npx vue-tsc --noEmit` → 无新错误。
- [ ] **Step 6: dev 手测（建议）** —— 数据中心第 5 tab「GEO」加载，选品牌 → 矩阵渲染、点格出回答原文+信源、信源榜按权重排、趋势显示。
- [ ] **Step 7: 提交** `git add frontend/src/components/monitor/geo/GeoKeywordMatrix.vue frontend/src/components/monitor/geo/GeoAnalyticsPage.vue frontend/src/components/monitor/geo/GeoSourceList.vue frontend/src/views/DataCenterView.vue` → `feat(geo-ui): GEO 数据中心分析页（关键词×平台矩阵 + 高权重信源榜）+ 数据中心 GEO tab`

---

## Self-Review

**Spec coverage（spec §D3/D4）:** GEO 数据中心页（KPI+矩阵+信源榜+趋势，按品牌选择器）→ Task 3+4 ✓；矩阵=名次+颜色（cellStatus）✓；点格下钻回答原文+引用信源（GeoPlatformBlock）✓；高权重信源 weight=被引×覆盖平台×权威度 → Task 1+2 ✓；规范信源（知乎合并/百度系拆分）→ Task 1 ✓（**写入时生效，需重跑**，已在设计标注）。

**Placeholder/确认点:** 后端给完整代码。前端 Task 3/4 给精确结构+复用点，执行者读 `geoDetail.ts`/`GeoRankHeatmap.vue`/`GeoTaskModule.vue` 源码落实。确认点：(a) GeoHero 的 props 是否与顶层 metric 兼容（不兼容退化为简单 KPI 卡）；(b) `/api/monitor/results` 顶层 metric 是否含 soc/sentiment_score（读 `metrics.aggregate` 确认 —— 摸底显示顶层有 soc/sentiment_score/mentioned/ok_total/total）；(c) useGeoAnalytics 返回形态（解构 refs vs 单 analytics ref）实现时定一种、模板对齐。

**一致性:** `BoardRow.weight`（Task 3）↔ 后端 leaderboard `weight`（Task 2）↔ GeoSourceList 读 `b.weight`（Task 4）一致；matrix[kw][pid]=PlatformVM ↔ GeoKeywordMatrix props ↔ cellStatus 输入一致。

**顺序:** Task 1 → 2（后端，独立 csm_core 测试，无 override）→ 3（数据层）→ 4（组件+页+tab）。
