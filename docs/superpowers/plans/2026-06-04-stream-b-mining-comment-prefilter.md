# Stream B — 引流评论视频 ≤3 种草预筛 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use `- [ ]`.
> **Commits:** Chinese `feat:` + trailer `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.
> **Tests:** mining storage/runner tests live in `sidecar/tests/` but import `csm_core` → run WITHOUT override from repo root: `python -m pytest sidecar/tests/test_mining_runner.py -v`. If a test imports `csm_sidecar` (e.g. the route test), use `$env:PYTHONPATH="D:\CSM\.claude\worktrees\elastic-moore-fa05f4\sidecar"` in the same command.

**Goal:** 引流挖掘视频时，对每个候选视频抓第一页评论，数含**目标品牌词**的评论数；**≥3 条 → 标 `excluded`（已种草满 3，避免重复评论）+ 记原因 + 命中数**；<3 条照常入库。品牌词来自引流任务新增的 `brand_keywords` 字段。

**Architecture:** 数据层加 3 列（`videos.brand_comment_hits` / `videos.exclude_reason` / `mining_jobs.brand_keywords_json`）经 V7 迁移（**必须接进 `csm_core/monitor/storage._migrate`**）+ 一个 `mark_brand_excluded` setter。`brand_keywords` 从 `StartJobRequest` → `submit_job` → `create_job` → `_row_to_job_dict`（runner 读 dict）。抓评论**复用监控侧适配器**：用合成 `MonitorTask` 调 `ADAPTER.fetch()` 读 `result.metric["hot_comments"]`（小 `scrape_top_n` 控延迟）。预筛在 runner 每平台 search 完成后的**独立 pass**（option B）跑，发 `prefilter` phase；**fail-open**：抓评论失败/空 → 不排除。

**⚠️ 可靠性边界（写进设计、告知用户）:** 抓评论用 `CookieStore("<platform>_comment")` 的 cookie ——
- 用户必须用过**评论监控**（任务①）才有这些 cookie；只用引流不用评论监控 → cookie 空 → 抓评论失败 → fail-open（预筛不动）。
- **抖音 X-Bogus 是 stub、可靠性差**（即便有 cookie 也常空/验证码）；快手要 cookie；B站公开视频热评常可匿名拿到。
- 所以预筛**对 B站/快手相对可用、抖音弱**，且**只对有评论 cookie 的用户生效**。fail-open 保证「抓不到 ≠ 误排除」。

**Tech Stack:** Python (csm_core.mining + monitor.storage + monitor.platforms) + pytest（monkeypatch 抓评论，不真起网络）。前端 `prefilter` phase + 排除原因展示列为**可选后续**（见 Task 5），核心是后端。

---

## File Structure

| 文件 | 改动 |
|---|---|
| `csm_core/mining/storage.py` | V7 迁移（3 列）+ `mark_brand_excluded` + `_row_to_video_dict`/`_row_to_job_dict` 加新列 + `create_job` 接 brand_keywords |
| `csm_core/monitor/storage.py` | `_migrate` 接 `apply_v7_migration` + bump schema 版本（**关键**）|
| `csm_core/mining/models.py` | `MiningJob`/`StartJobRequest` 加 `brand_keywords`；`PlatformPhase` 加 `"prefilter"` |
| `sidecar/csm_sidecar/services/mining_service.py` | `submit_job` 加 `brand_keywords` 参数 → `create_job` |
| `sidecar/csm_sidecar/routes/mining*.py` | POST 路由把 `req.brand_keywords` 透传 `submit_job` |
| `csm_core/mining/comment_prefilter.py` | 新建：`fetch_video_comment_texts` + `count_brand_hits` |
| `csm_core/mining/runner.py` | 每平台 search 后跑预筛 pass（fail-open + prefilter phase）|
| tests | mining storage/runner/prefilter 单测 |

---

## Task 1: 数据层 — V7 迁移 + setter + brand_keywords 列

**Files:** Modify `csm_core/mining/storage.py`, `csm_core/monitor/storage.py`; Test `sidecar/tests/test_mining_storage.py`（或既有 mining storage 测试，grep）

- [ ] **Step 1: 读迁移机制** — 读 `csm_core/mining/storage.py` 的 `apply_v6_migration` + 该文件顶部 docstring（说明 `apply_vN_migration` 由 `monitor/storage._migrate` 调用）；读 `csm_core/monitor/storage.py` 的 `_migrate`（找 schema 版本常量 + `apply_v6_migration` 的调用处）。**两处都要改**才能让 V7 真跑。

- [ ] **Step 2: 失败测试** — 新建/追加 mining storage 测试：init 一个全新 monitor.db（既有 `db`/`fresh_db` fixture），断言 `videos` 表有 `brand_comment_hits`/`exclude_reason` 列、`mining_jobs` 有 `brand_keywords_json` 列（`PRAGMA table_info`）；`mark_brand_excluded(video_id, hits=4)` 后该行 `excluded=1, exclude_reason='brand_seeded', brand_comment_hits=4`（直接查 `videos`，因为 `list_videos` 过滤 excluded=0）；`create_job(..., brand_keywords=["石头","roborock"])` 后 `get_job(jid)["brand_keywords"] == ["石头","roborock"]`。

- [ ] **Step 3: 实现 mining/storage.py**
  - 加 `_DDL_V7_*`（若需索引，可省）+ `def apply_v7_migration(conn)`：PRAGMA-guard（仿 `apply_v4_migration`）`ALTER TABLE videos ADD COLUMN brand_comment_hits INTEGER`、`ALTER TABLE videos ADD COLUMN exclude_reason TEXT`、`ALTER TABLE mining_jobs ADD COLUMN brand_keywords_json TEXT NOT NULL DEFAULT '[]'`。
  - `mark_brand_excluded`：
    ```python
    def mark_brand_excluded(video_id: int, hits: int) -> bool:
        conn = get_conn()
        cur = conn.execute(
            "UPDATE videos SET excluded=1, exclude_reason='brand_seeded', brand_comment_hits=? WHERE id=?",
            (int(hits), video_id),
        )
        return cur.rowcount > 0
    ```
  - （可选记非排除命中数）`set_brand_hits(video_id, hits)`：`UPDATE videos SET brand_comment_hits=? WHERE id=?`（<3 时记数不排除）。
  - `create_job` 加 `brand_keywords: list[str] | None = None` 参数，INSERT 多写 `brand_keywords_json`（`json.dumps(brand_keywords or [])`）—— 注意同步改 INSERT 的列名+占位符+values。
  - `_row_to_job_dict` 返回加 `"brand_keywords": json.loads(row["brand_keywords_json"]) if "brand_keywords_json" in row.keys() and row["brand_keywords_json"] else []`（容错读，仿 ai_summary try/except）。
  - `_row_to_video_dict` 加 `brand_comment_hits` / `exclude_reason`（容错读）。

- [ ] **Step 4: 实现 monitor/storage.py `_migrate`** — bump schema 版本常量 +6→+7（按既有写法），加 `mining_storage.apply_v7_migration(conn)` 调用（仿 v6 那行；注意 import 来源）。

- [ ] **Step 5: 跑通过** `python -m pytest sidecar/tests/test_mining_storage.py -v`（+ 既有 mining storage 测试全绿，确认迁移没破坏老 db）。
- [ ] **Step 6: 提交** → `feat(mining): V7 迁移 brand_comment_hits/exclude_reason/brand_keywords + mark_brand_excluded`

---

## Task 2: brand_keywords 贯通（model → service → route → create_job）

**Files:** Modify `csm_core/mining/models.py`, `sidecar/csm_sidecar/services/mining_service.py`, `sidecar/csm_sidecar/routes/mining*.py`; Test（路由/service 测试，需 override 跑 sidecar）

- [ ] **Step 1: 失败测试** — 找 mining 路由测试（grep `StartJobRequest`/`/api/mining/jobs` POST）。加用例：POST 带 `brand_keywords: ["石头"]` → 落库后 `get_job` 的 brand_keywords == ["石头"]。（或 service 级：`submit_job(..., brand_keywords=["石头"])` → get_job 验证。）

- [ ] **Step 2: 实现**
  - `models.py`：`StartJobRequest` 加 `brand_keywords: list[str] = Field(default_factory=list)`；`MiningJob` 加 `brand_keywords: list[str] = Field(default_factory=list)`；`PlatformPhase` Literal 加 `"prefilter"`。
  - `mining_service.submit_job` 签名加 `brand_keywords: list[str] | None = None`，传给 `mining_storage.create_job(keyword, platforms, target_per_platform, brand_keywords=brand_keywords)`。
  - mining POST 路由：调用 `submit_job` 处加 `brand_keywords=req.brand_keywords`。

- [ ] **Step 3-4: 跑通过 + 提交** → `feat(mining): 引流任务支持 brand_keywords（提交→落库→runner 可读）`

---

## Task 3: 抓评论复用 helper + 品牌命中计数

**Files:** Create `csm_core/mining/comment_prefilter.py`; Test `sidecar/tests/test_comment_prefilter.py`

- [ ] **Step 1: 失败测试** — monkeypatch 各平台 `ADAPTER.fetch` 返回带 `metric["hot_comments"]` 的假 result，断言 `fetch_video_comment_texts("bilibili", url, limit=30)` 返回 `[c["text"]...]`；抓取失败（fetch 抛/返回 failed/空）→ 返回 `[]`（fail-open 由调用方处理，helper 只返回空）。`count_brand_hits(["买了石头很好","凑数","roborock yyds"], ["石头","roborock"]) == 2`；空 brand → 0。

- [ ] **Step 2: 实现** `csm_core/mining/comment_prefilter.py`：
```python
"""引流预筛：复用监控评论适配器抓单视频评论 + 数品牌词命中。"""
from __future__ import annotations
import logging
from typing import Any

logger = logging.getLogger(__name__)

# mining platform → monitor comment 适配器 type（与 storage._PLATFORM_TO_MONITOR_TYPE 一致）
_PLATFORM_COMMENT_TYPE = {
    "douyin": "douyin_comment",
    "bilibili": "bilibili_comment",
    "kuaishou": "kuaishou_comment",
}


def count_brand_hits(texts: list[str], brands: list[str]) -> int:
    bl = [b.lower() for b in brands if b and b.strip()]
    if not bl:
        return 0
    return sum(1 for t in texts if any(b in (t or "").lower() for b in bl))


def fetch_video_comment_texts(platform: str, video_url: str, limit: int = 30) -> list[str]:
    """抓该视频前 ~limit 条评论文本。复用监控评论适配器（curl_cffi + *_comment cookie）。
    任何失败/空 → 返回 []（调用方据此 fail-open，不排除）。cookie 来自评论监控命名空间。"""
    ctype = _PLATFORM_COMMENT_TYPE.get(platform)
    if ctype is None:
        return []
    try:
        from csm_core.monitor.platforms import ALL as _MONITOR_ADAPTERS  # platform type → ADAPTER
        from csm_core.monitor.base import MonitorTask
        adapter = _MONITOR_ADAPTERS.get(ctype)
        if adapter is None:
            return []
        task = MonitorTask(
            type=ctype, name="prefilter", target_url=video_url,
            # my_comment_text 必填非空（build_match_result 要求）；预筛只数评论，用占位
            config={"my_comment_text": " ", "scrape_top_n": int(limit)},
        )
        result = adapter.fetch(task)
        if getattr(result, "status", "") not in ("ok",):
            return []
        hots = (result.metric or {}).get("hot_comments") or []
        return [str(c.get("text") or "") for c in hots]
    except Exception:
        logger.info("[prefilter] fetch comments failed platform=%s url=%s", platform, video_url[:80], exc_info=True)
        return []
```
（确认 `csm_core/monitor/platforms/__init__.py` 的 `ALL` dict 形如 `{type: ADAPTER}`，含 `*_comment` —— 读它确认 key/对象；若适配器不在 `ALL` 则直接 import 各 `ADAPTER`。）

- [ ] **Step 3-4: 跑通过 + 提交** → `feat(mining): 抓单视频评论 helper（复用监控适配器）+ 品牌命中计数`

---

## Task 4: runner 预筛 pass（核心集成）

**Files:** Modify `csm_core/mining/runner.py`; Test `sidecar/tests/test_mining_runner.py`

- [ ] **Step 1: 失败测试** — 仿 `test_mining_runner.py`：建 job 带 `brand_keywords=["石头"]`，FakeAdapter emit 几个 VideoCard；monkeypatch `runner` 引入的 `fetch_video_comment_texts` 让某视频返回 ≥3 条含「石头」、另一个返回 0/1 条。run → 直接查 `videos` 断言：满 3 的视频 `excluded=1, exclude_reason='brand_seeded', brand_comment_hits>=3`；<3 的 `excluded=0`。再加一例 brand_keywords 为空 → 不预筛（全 excluded=0）。

- [ ] **Step 2: 实现** `runner.py`：
  - import `from csm_core.mining.comment_prefilter import fetch_video_comment_texts, count_brand_hits`。
  - 读 `brand_keywords = job.get("brand_keywords") or []`（run 开头）。
  - 在每平台 search 成功后（L156 之后、`job.platform_done` 之前）插入预筛 pass：**仅当 `brand_keywords` 非空**。查该 job 该平台**本次新入库、未排除**的视频（用 `mining_storage` 现有查询 —— 读 storage 找按 job_id+platform 列 not-excluded 视频的方式；没有就加一个 `list_job_platform_videos(job_id, platform)` 简单查询）。对每个视频：
    ```python
    texts = fetch_video_comment_texts(platform, v["url"], limit=PREFILTER_SCRAPE_TOP_N)  # e.g. 30
    if not texts:
        continue  # fail-open：抓不到不排除
    hits = count_brand_hits(texts, brand_keywords)
    if hits >= PREFILTER_THRESHOLD:  # 3
        mining_storage.mark_brand_excluded(v["id"], hits)
    else:
        mining_storage.set_brand_hits(v["id"], hits)  # 记数不排除（可选）
    ```
    期间发 `prefilter` phase：`update_platform_progress(job_id, platform, got=i, target=len(vids), phase="prefilter", note="筛评论")` + `self.publish("job.progress", {...,"phase":"prefilter",...})`（仿 L122-125）。**结束后把 platform phase 恢复 `done`**（否则 `finalize_job` 把非-done 当失败 —— 见 recon §5），即预筛 pass 跑完再发最终 `done` 进度 + `job.platform_done`。
  - 常量 `PREFILTER_THRESHOLD = 3`、`PREFILTER_SCRAPE_TOP_N = 30`。
  - 整个 pass 包 try/except（单视频抓取失败不影响其他、不影响平台 done）。

- [ ] **Step 3: 跑通过** `python -m pytest sidecar/tests/test_mining_runner.py -v`（+ 既有 runner 测试全绿 —— 确认无 brand_keywords 时行为不变）。
- [ ] **Step 4: 提交** → `feat(mining): 引流预筛 —— 每视频评论含品牌词 ≥3 标排除（fail-open）`

---

## Task 5（可选/后续）: 前端预筛可见性

**Files:** `frontend/src/stores/mining.ts`（phase 类型加 `prefilter`）、mining 视频列表/卡片组件。

- [ ] phase 文案：`prefilter` → 「筛重复评论中」。
- [ ] 排除视频可见+可恢复：若现有 mining UI 有「已排除」视图/筛选，让预筛排除的视频在那显示 `exclude_reason='brand_seeded'`（文案「已种草满 3」）+ `brand_comment_hits` + 恢复按钮（调既有恢复/`excluded=0` 接口）。若现有 UI 无「已排除」视图，本任务记为后续，不阻塞核心。

**说明:** 核心避免重复评论的价值在后端排除（excluded 视频从默认列表消失）。本任务是「让用户看到为何排除 + 恢复」，按现有 UI 能力决定是补丁还是后续。

---

## Self-Review

**Spec coverage（任务⑥ + spec §Stream B）:** brand_keywords 字段 → Task 2 ✓；抓每视频评论数品牌词 → Task 3 ✓；≥3 标 excluded+原因+命中数 → Task 1（setter/列）+ Task 4（集成）✓；<3 照常入库 → Task 4（不排除、记数）✓；复用监控抓评论内核 → Task 3 ✓；fail-open → Task 3（空）+ Task 4（空跳过）✓；UI 可见可恢复 → Task 5（按现有 UI 能力，可后续）。

**最高风险/确认点:** (a) **V7 迁移必须接进 `monitor/storage._migrate` + bump 版本**（漏了列不会建）—— Task 1 Step 1/4 强调；(b) cookie 源边界（评论 cookie 命名空间，抖音 X-Bogus 弱）—— 设计已标，fail-open 兜底；(c) `monitor.platforms.ALL` 的形状（type→ADAPTER）—— Task 3 确认；(d) runner 查「本平台本次未排除视频」的方式 —— Task 4 读 storage 确认或加简单查询；(e) prefilter phase 后必须恢复 `done` 否则 finalize 当失败。

**顺序:** Task 1（迁移/列/setter）→ 2（brand_keywords 贯通）→ 3（helper）→ 4（runner 集成）→ 5（前端，可选）。每步测试。
