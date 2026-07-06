# PR-D 实现计划：反馈学习闭环（§6）+ 事实更新传导（§7）

Phase 4+ 的最后一块。承接已合并的 PR-A（#149 增量索引）、PR-B（#152 契约+评分）、PR-C（#153 横评）。
分支 `claude/phase4-feedback-facts`，base = main（已含 PR-A/B/C + finalize 修复 #154）。

设计源：`docs/superpowers/specs/2026-07-01-phase4-plus-design.md` §6-§7、§10.6-10.7 验收、§11 纪律。

---

## 概要（第一性原理）

**根本需求**：让「导出即产生一条可学习的成稿记录」，并让「vault 参数变更能反向标记过期文章」。两件事共用一套持久层（monitor.db v9），但方向相反：
- §6 反馈：成稿导出 → 落 `creation_records`（+ note 用量 + 事实快照）→ 聚合成 note/角度统计 → 可选反哺采样权重。
- §7 传导：vault 型号指纹 vs `model_fingerprints` 基线 → 变更 → 通知 + 历史页「参数已变更」徽章 → 一键重生成。

**三条不可动摇的红线**（贯穿全 PR）：
1. **fail-open 采集**：`record_export` 全程 try/except 吞异常 + log，**任何失败都不得影响导出本身**。反馈是副作用，不是主流程。
2. **零回归采样**：`assemble_plan(note_weights=None)` 必须与今天**逐字节一致**（RNG 消耗序列不变）——这是保守分支字节红线的同构要求。加权只在显式传权重时生效。
3. **测试全 tmp DB + config 隔离**：迁移/服务测试一律 `init_db(tmp_path/"monitor.db")` + monkeypatch `config_service`；共享盘红线，任何测试禁写 `D:\家电组共享\DATA`。

**默认姿态**（用户 2026-07-01 拍板）：`record` 默认开（静默采集）、`rank` 默认关（不改采样，零行为变化）。所以合并即上线的只有「采集 + 传导检测」，排序是 opt-in。

---

## 三个集成确认点（实现者动手前先核对真实 API，别照抄我的猜测）

计划里这三处我给了方向但**必须以代码为准**，Unit 实现者第一步先确认，审查者重点盯：

- **CP-1（Unit A 采样池元素类型）**：`csm_core/assembler/sampler.py` `_sample_notes_source` 里 `pool` 的元素类型，取 `note_id` 的字段名。加权 lookup `note_weights.get(<note_id>, 1.0)` 依赖它。确认 `pool[i]` 是 `ParsedNote`（`.id`）还是别的。
- **CP-2（Unit B finalize 指纹来源）**：`finalize_draft` 内解析出的注入 scope 是 `ModelScope` 还是 `BrandModelMemory`？`spec_fingerprint` 需要 `.specs`(dict[str,SpecValue]) + `.certs`(list[str])。若 scope 不带 certs，改从底层 memory 取，或让 `spec_fingerprint` 接受鸭子类型。**不重解析**（spec §6.2「无漂移」）。
- **CP-3（Unit B 全量型号枚举）**：`fact_service.detect_changes` 要遍历所有型号做 `resolve_memory(brand, model, category, index, own_brands=…)`——`category` 从哪来？registry 只给 brand→model。确认 index/registry 是否能枚举 `(brand, model, category)` 三元组（很可能从 `index.notes` 的型号笔记直接拿 category），否则 detect 无法调 resolve_memory。这是 §7 全局检测的地基，先打通再写。

---

## File Structure

**Unit A — csm_core 纯逻辑（持久层 + 指纹 + 加权采样）**
- `csm_core/feedback/__init__.py`（新）
- `csm_core/feedback/storage.py`（新）— v9 迁移四表 + `apply_v9_migration` + CRUD/聚合
- `csm_core/feedback/model.py`（新）— `CreationRecord` / `NoteUsage` / `FactSnapshot` / `NoteStat` / `AngleStat` 轻量 dataclass
- `csm_core/brand_memory/fingerprint.py`（新）— `spec_fingerprint` + `diff_canonical`
- `csm_core/monitor/storage.py`（改）— `_SCHEMA_VERSION 8→9` + `_migrate` 挂 v9
- `csm_core/assembler/sampler.py`（改）— `_sample_notes_source` 加可选 `note_weights`
- `csm_core/assembler/*.py`（改）— `assemble_plan` 透传 `note_weights`（CP-1 定位链路）
- 测试：`tests/core/feedback/test_storage.py`、`test_weights.py`、`tests/core/brand_memory/test_fingerprint.py`、`tests/core/assembler/test_sampler_weights.py`

**Unit B — sidecar 接线（服务 + 钩子 + 路由）**
- `csm_core/config.py`（改）— `FeedbackConfig` + 挂 `AppConfig.feedback`
- `sidecar/csm_sidecar/services/feedback_service.py`（新）— stash/record_export/weights/stats
- `sidecar/csm_sidecar/services/fact_service.py`（新）— detect_changes/drain/diff
- `sidecar/csm_sidecar/services/generate_service.py`（改）— submit/submit_comparison stash、finalize stash_scopes、rank 权重穿透
- `sidecar/csm_sidecar/services/assembler_service.py`（改，若需）— 权重传参
- `sidecar/csm_sidecar/routes/article.py`（改）— `ExportBody` 加字段 + 采集钩子
- `sidecar/csm_sidecar/routes/generate.py`（改）— `resolve_factcheck` 采集钩子
- `sidecar/csm_sidecar/routes/feedback.py`（新）— `/api/feedback/stats`、`/api/facts/changes`、`/api/facts/diff`
- `sidecar/csm_sidecar/services/aggregation_service.py`（改）— `/api/recent` 每行增强
- lifespan + `/api/vault/scan`（改，定位后）— 扫描后触发 detect_changes
- 测试：`sidecar/tests/test_feedback_service.py`、`test_fact_service.py`、`test_feedback_routes.py`、`test_recent_stale.py`（全 tmp DB + config 隔离）

**Unit C — 前端**
- `frontend/src/stores/article.ts`（改）— `exportArticle` 带 `job_id`(+score)
- `frontend/src/stores/config.ts` 或类型（改）— `feedback` 配置
- `frontend/src/api/client.ts`（改）— `listRecent` 类型扩 + `feedbackStats`/`factsChanges`/`factsDiff`
- `frontend/src/components/settings/FeedbackCard.vue`（新）
- `frontend/src/views/MaterialsView.vue`（改）— 新 tab「使用反馈」
- `frontend/src/components/materials/FeedbackStatsPanel.vue`（新）
- `frontend/src/views/RecentHistoryView.vue`（改）— 徽章 + 重生成
- App 启动序列（改，定位后）— 拉 facts/changes → 通知
- 测试：store/panel/badge 最小集 + `vue-tsc -b`

---

# Unit A — csm_core 纯逻辑

## Task A1：feedback/storage.py — v9 迁移四表 + 注册

**新模块** `csm_core/feedback/storage.py`。DDL 逐字照 spec §6.1（`IF NOT EXISTS` 幂等）：

```python
"""反馈学习闭环持久层 —— monitor.db v9。挂进 monitor.storage 版本链（仿 mining/geo）。"""
from __future__ import annotations
import sqlite3
from csm_core.monitor import storage as monitor_storage

_DDL_V9_FEEDBACK: list[str] = [
    """
    CREATE TABLE IF NOT EXISTS creation_records (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id           TEXT UNIQUE NOT NULL,
        mode             TEXT NOT NULL DEFAULT 'normal',   -- normal | comparison | batch
        keyword          TEXT, template_id TEXT, title TEXT,
        angle_json       TEXT, skill_chain_json TEXT, models_json TEXT,
        contract_mode    TEXT,
        document_path    TEXT, format TEXT,
        edit_ratio       REAL,
        lint_unresolved  INTEGER DEFAULT 0,
        factcheck_blocked INTEGER DEFAULT 0,
        score            REAL, score_json TEXT,
        created_at       TEXT NOT NULL, exported_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_creation_doc ON creation_records(document_path)",
    """
    CREATE TABLE IF NOT EXISTS creation_note_usage (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        record_id     INTEGER NOT NULL REFERENCES creation_records(id) ON DELETE CASCADE,
        note_id       TEXT NOT NULL, variant_index INTEGER, block_id TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_note_usage_note ON creation_note_usage(note_id)",
    "CREATE INDEX IF NOT EXISTS idx_note_usage_record ON creation_note_usage(record_id)",
    """
    CREATE TABLE IF NOT EXISTS fact_snapshots (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        record_id   INTEGER NOT NULL REFERENCES creation_records(id) ON DELETE CASCADE,
        model       TEXT NOT NULL, fingerprint TEXT NOT NULL, specs_json TEXT NOT NULL,
        created_at  TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_fact_snap_model ON fact_snapshots(model, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_fact_snap_record ON fact_snapshots(record_id)",
    """
    CREATE TABLE IF NOT EXISTS model_fingerprints (
        model       TEXT PRIMARY KEY, fingerprint TEXT NOT NULL,
        specs_json  TEXT NOT NULL, updated_at TEXT NOT NULL
    )
    """,
]

def apply_v9_migration(conn: sqlite3.Connection) -> None:
    """Called by monitor.storage._migrate when bumping v8 -> v9. Idempotent."""
    for stmt in _DDL_V9_FEEDBACK:
        conn.execute(stmt)

def get_conn() -> sqlite3.Connection:
    """Thin alias — feedback shares monitor's connection pool."""
    return monitor_storage.get_conn()
```

**注册**（`csm_core/monitor/storage.py`）：
- 第 27 行 `_SCHEMA_VERSION = 8` → `9`。
- `_migrate()`（约 129-156）在 v8 之后、`INSERT OR REPLACE schema_meta` 之前加：
```python
    # v9: 反馈学习闭环四表（creation_records / note_usage / fact_snapshots /
    #     model_fingerprints）。lazy import 同 v3-v8。
    from csm_core.feedback import storage as feedback_storage
    feedback_storage.apply_v9_migration(conn)
```

**⚠️ 循环 import 警惕**：`feedback/storage.py` 顶层 `import monitor.storage`，而 `monitor.storage._migrate` **函数体内**（非顶层）lazy import `feedback.storage`——与 mining/geo 现状一致，不成环。别把 feedback 的 import 提到 monitor.storage 顶层。

**测试** `tests/core/feedback/test_storage.py`（`fresh_db` 装置照 `tests/core/monitor/test_storage.py:17-31` 重置 `_db_path/_initialized/_local`）：
- `test_v9_tables_exist`：init 后 `sqlite_master` 含四表。
- `test_v9_schema_version`：`schema_meta` version == '9'。
- `test_v9_idempotent`：连开两次 `init_db`（重置 guard 后）不抛、表仍在。
- `test_fk_cascade`：删 creation_records 一行，其 note_usage/fact_snapshots 级联删（需 `PRAGMA foreign_keys=ON`——**确认 monitor get_conn 是否开 FK**；若没开，CASCADE 不生效，测试改为手动删或在 storage 写入时开 FK。记录到备注）。

## Task A2：feedback/model.py + storage CRUD/聚合

**model.py** 轻量 dataclass（不用 pydantic，纯搬运）：
```python
@dataclass
class NoteUsage:
    note_id: str
    variant_index: int | None = None
    block_id: str | None = None

@dataclass
class FactSnapshot:
    model: str
    fingerprint: str
    specs_json: str

@dataclass
class CreationRecord:
    job_id: str
    mode: str
    keyword: str | None; template_id: str | None; title: str | None
    angle_json: str | None; skill_chain_json: str | None; models_json: str | None
    contract_mode: str | None
    document_path: str | None; format: str | None
    edit_ratio: float | None
    lint_unresolved: int; factcheck_blocked: int
    score: float | None; score_json: str | None
    created_at: str; exported_at: str
```

**storage CRUD**（都走 `get_conn()`，写操作用事务；**确认现有写者的 commit 姿态**——monitor 是 autocommit 还是 `with conn:`？照抄 mining `record_*` 的提交方式）：

```python
def record_creation(rec: CreationRecord, note_usage: list[NoteUsage],
                    fact_snaps: list[FactSnapshot]) -> int:
    """插一条成稿记录 + 其 note 用量 + 事实快照（一个事务）。job_id 冲突用
    INSERT OR REPLACE？——不。job_id UNIQUE，重复导出同 job 应更新而非累加：
    先 DELETE 旧行（级联清子表）再插，保证幂等重导不留脏子行。返回 record_id。"""
```
- 语义定夺：**重复导出同 job_id → 覆盖**（DELETE 旧 record 触发级联 → 重插）。这样用户「导出→改→再导出」只留最后一版，edit_ratio 反映最终改动。写测试钉这个幂等。

```python
def get_note_weights(min_samples: int, alpha: float) -> dict[str, float]:
    """按 note_id 聚合成排序权重。样本 = 用过该 note 且 edit_ratio 非空的
    **去重 record 数**（一条 record 多次用同 note 只算一次，避免变体重复灌水）。
    keep_score = avg(1 - edit_ratio) over 这些 record；
    weight = clamp(1 + alpha*(keep_score-0.5)*2, 0.5, 1.5)；样本<min_samples 不入 dict。"""
```
SQL（先去重到 (note_id, record_id, edit_ratio) 再聚合，杜绝双计）：
```sql
WITH per_note_record AS (
  SELECT DISTINCT nu.note_id AS note_id, cr.id AS record_id, cr.edit_ratio AS edit_ratio
  FROM creation_note_usage nu JOIN creation_records cr ON nu.record_id = cr.id
  WHERE cr.edit_ratio IS NOT NULL
)
SELECT note_id, COUNT(*) AS n, AVG(1.0 - edit_ratio) AS keep
FROM per_note_record GROUP BY note_id HAVING COUNT(*) >= :min_samples
```
Python 侧 clamp。

```python
def get_feedback_stats() -> dict:
    """/api/feedback/stats 数据源。
    notes: 同上聚合但不设门槛，top50 按 uses 降序，带 uses/avg_edit_ratio/avg_score/keep_score。
    angles: 遍历 creation_records.angle_json（JSON 解析：audience/sellpoints/tone），
            按 (audience, tuple(sorted sellpoints), tone) 聚合 uses/avg_score/avg_edit_ratio，top20。"""
```
- angles 聚合走 Python（angle_json 是 JSON 文本，SQL 拆不动）：`SELECT angle_json, score, edit_ratio FROM creation_records WHERE angle_json IS NOT NULL` → 分组。

```python
def get_model_fingerprints() -> dict[str, tuple[str, str]]:
    """model -> (fingerprint, specs_json) 全量基线。"""

def upsert_model_fingerprints(rows: list[tuple[str, str, str]], *, now: str) -> None:
    """[(model, fingerprint, specs_json)] INSERT OR REPLACE + updated_at=now。"""

def find_creation_by_document(document_path: str) -> CreationRecord | None:
    """按 document_path 取最新一条（可能多条→exported_at DESC LIMIT 1）。"""

def get_fact_snapshots_for_record(record_id: int) -> list[FactSnapshot]:
    ...
```

**测试** `test_storage.py` 续 + `test_weights.py`：
- `record_creation` 往返：插 record + 2 note_usage + 2 fact_snap → 读回字段全等；重复同 job_id 覆盖（子表不累加）。
- `get_note_weights`：造 6 条 record 用 noteX（edit_ratio 0.0）→ keep=1.0 → weight=clamp(1+0.5*0.5*2)=1.5；用 noteY 4 条 → 样本<5 不入 dict；同 record 内 noteZ 出现两次只算 1 样本（凑不够门槛）。钳位上下界各一例。
- `get_feedback_stats`：notes/angles 形状 + top 截断 + 空库返回空表不抛。
- 基线 upsert/读、find_by_document（多条取最新）。

## Task A3：brand_memory/fingerprint.py

**新** `csm_core/brand_memory/fingerprint.py`：
```python
"""型号参数指纹 —— 只对『会传导的事实』（参数 specs + 认证 certs）建线，
scripts/tests/endorsements/intro 变化不算事实变更（§7.1）。"""
from __future__ import annotations
import hashlib, json
from csm_core.brand_memory.model import BrandModelMemory

def spec_fingerprint(memory: BrandModelMemory) -> tuple[str, str]:
    """返回 (sha256hex, canonical_specs_json)。
    canonical = {"specs": sorted [[field, raw]] 非占位对, "certs": sorted list}。"""
    specs = sorted([sv.field, sv.raw] for sv in memory.specs.values() if not sv.is_placeholder)
    certs = sorted(memory.certs)
    canonical = json.dumps({"specs": specs, "certs": certs},
                           ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return digest, canonical

def diff_canonical(old_json: str, new_json: str) -> list[dict]:
    """[{field, old, new}]：specs 逐字段增/删/改 + certs 作为 field='认证'（old/new = 逗号串）。
    old_json 空/坏 → 视作全新（首建，调用方自行决定是否报）。"""
```
- diff 细节：parse 两侧 `{"specs": [[f,r],...], "certs": [...]}` → specs 转 dict{f:r} 对比（新增 old=None、删除 new=None、改则都在），certs 变化聚成一条 `{field:"认证", old:"A,B", new:"A,C"}`。

**测试** `tests/core/brand_memory/test_fingerprint.py`：
- 占位不参与：同型号，只有 `is_placeholder` 的 spec 值变 → 指纹不变。
- 顺序无关：specs 插入顺序不同 → 指纹相同（sorted）。
- certs 参与：加一个 cert → 指纹变。
- scripts/tests/endorsements 不参与：改 scripts → 指纹不变。
- 稳定性：同输入两次 → 同 hex。
- `diff_canonical`：改一个参数 raw → 一条 {field, old, new}；加 cert → 一条 field=认证；old 空 → 全新。

## Task A4：sampler note_weights（rank 特性，默认关，零回归）

**改** `csm_core/assembler/sampler.py` `_sample_notes_source`（约 97-100）。**CP-1 先确认 pool 元素取 note_id 的字段**。

```python
def _sample_notes_source(..., note_weights: dict[str, float] | None = None):
    if "unique_notes" in constraints:
        actual = min(requested, len(pool))
        chosen = rng.sample(pool, actual)      # 唯一分支 v1 不加权（无放回加权复杂，留边界）
    else:
        actual = requested
        if note_weights is None:
            chosen = [rng.choice(pool) for _ in range(requested)]   # ← 今天行为，逐字节不动
        else:
            w = [note_weights.get(_note_id(n), 1.0) for n in pool]
            chosen = rng.choices(pool, weights=w, k=requested)      # ← 仅显式权重时
```
- **零回归铁律**：`note_weights is None` 走原 `rng.choice` 循环，**RNG 消耗序列与今天完全一致**。绝不能「统一改成 rng.choices」——那会变 RNG 序列、破坏同种子复现。
- `_note_id(n)`：CP-1 确认的字段（大概率 `n.id`）。
- `note_weights` 透传链：`_sample_notes_source` ← `sample_block` ← `assemble_plan`（新增可选参 `note_weights=None`，一路默认 None）。CP-1 里把这条链的每一跳都补上默认参。

**测试** `tests/core/assembler/test_sampler_weights.py`：
- **零回归快照**：固定 vault + seed，`assemble_plan(note_weights=None)` 的 picks 序列 == `assemble_plan()`（不传）== 一份钉死快照（改动前先录基线值）。
- 加权确定性：同 seed 同权重两次 → picks 完全一致。
- 加权偏置：给 noteA 权重 1.5、其余 0.5，大 requested（如 50 次非唯一采样）→ noteA 命中占比显著高于均匀（统计断言留足容差，别脆）。
- 唯一分支不受权重影响（传权重 == 不传，结果同）。

**Unit A 两段对抗审查**：正确性（get_note_weights 去重/钳位、fingerprint canonical、迁移幂等）+ 边界回归（sampler 零回归字节一致、FK 级联、循环 import、空库/占位/坏 JSON）。指令「设法证伪」。

---

# Unit B — sidecar 接线

## Task B1：FeedbackConfig

**改** `csm_core/config.py`（仿 `ContractConfig` 第 167-172）：
```python
class FeedbackConfig(BaseModel):
    """settings.feedback.* —— 反馈学习（record 默认开、rank 默认关）。"""
    record: bool = True
    rank: bool = False
    min_samples: int = Field(default=5, ge=1)
    alpha: float = Field(default=0.5, ge=0.0, le=2.0)
```
`AppConfig` 加 `feedback: FeedbackConfig = Field(default_factory=FeedbackConfig)`。
**测试**：默认值 + patch 深合并（`config_service.patch({"feedback":{"rank":True}})` 不动 record）。

## Task B2：feedback_service — stash + record_export（fail-open 核心）

**新** `sidecar/csm_sidecar/services/feedback_service.py`。两个 LRU（仿 comparison_cache MAX=50）：

```python
_request_cache: OrderedDict[str, dict] = OrderedDict()   # job_id -> 请求快照
_scopes_cache: OrderedDict[str, list[FactSnapshot]] = OrderedDict()  # job_id -> 事实快照
_lock = threading.Lock()
MAX = 50

def stash_request(job_id: str, snapshot: dict) -> None: ...   # submit/submit_comparison 调
def stash_scopes(job_id: str, snaps: list[FactSnapshot]) -> None: ...  # finalize 调
def reset_for_test() -> None: ...   # 清两 cache（测试隔离）
```

`snapshot` 归一化字段（normal 与 comparison 共用一个形状）：
`{mode, keyword, template_id, title, angle_json, skill_chain_json, models_json, contract_mode}`。
- normal（GenerateRequest）：mode='normal'、models_json=None、angle_json=json(angle)、skill_chain_json=json(skill_chain)。
- comparison（ComparisonRequest）：mode='comparison'、models_json=json(models)、template_id='__comparison__'、angle_json=json(tone-only angle 或 None)。

**record_export（fail-open）**：
```python
def record_export(job_id: str | None, *, document_path: str, fmt: str,
                  final_text: str, score: float | None, score_json: str | None,
                  lint_unresolved: int, factcheck_blocked: int) -> None:
    """导出成功后采集一条 creation_record。全程 try/except 吞 —— 绝不影响导出。"""
    try:
        cfg = config_service.load()
        if not cfg.feedback.record:
            return
        if not job_id:
            return                      # 纯前端 clientDownload / 无 job → 不采集（v1 边界）
        snap = _request_cache.get(job_id)
        if snap is None:
            return                      # 请求快照丢了（LRU 淘汰/重启）→ 放弃这条（宁缺）
        note_usage = _extract_note_usage(job_id)     # 走 assembler_service.get_plan；横评/miss → []
        edit_ratio = _compute_edit_ratio(job_id, final_text)  # chain 缓存 vs 导出；miss → None
        fact_snaps = _scopes_cache.get(job_id, [])
        now = _utcnow_iso()
        rec = CreationRecord(job_id=job_id, mode=snap["mode"], ...=snap[...],
                             document_path=document_path, format=fmt,
                             edit_ratio=edit_ratio, lint_unresolved=lint_unresolved,
                             factcheck_blocked=factcheck_blocked,
                             score=score, score_json=score_json,
                             created_at=now, exported_at=now)
        feedback_storage.record_creation(rec, note_usage, fact_snaps)
    except Exception:
        logger.exception("record_export failed for job %s (swallowed)", job_id)
```

`_extract_note_usage(job_id)`：`entry = assembler_service.get_plan(job_id)`；None → `[]`。递归走 `entry.plan.results`（含 `BlockResult.children`），每个 `BlockResult` 的 `picks: list[PickedVariant]` → `NoteUsage(note_id=p.note_id, variant_index=p.variant_index, block_id=block.block_id)`。

`_compute_edit_ratio(job_id, export_final)`：`state = chain_service.get_state(job_id)`；无 state 或无 `final_text` → None；否则 `1 - difflib.SequenceMatcher(None, state.final_text, export_final).ratio()`。**注意**：横评/常规都走 chain，chain 缓存都有；缓存淘汰才 None。

```python
def get_note_weights() -> dict[str, float]:
    cfg = config_service.load()
    if not cfg.feedback.rank:
        return {}
    return feedback_storage.get_note_weights(cfg.feedback.min_samples, cfg.feedback.alpha)

def get_feedback_stats() -> dict:
    return feedback_storage.get_feedback_stats()
```

**测试** `test_feedback_service.py`（tmp DB + config 隔离 + `reset_for_test`）：
- stash→record 全链命中：stash_request + stash_scopes + 预置 plan/chain state → record_export → DB 一行 + note_usage/fact_snap 落库、edit_ratio 正确。
- **fail-open**：monkeypatch `feedback_storage.record_creation` 抛 → record_export **不抛**、导出不受影响、日志有 exception。
- job_id=None / 快照 miss / plan miss / chain miss → 分别静默跳过或字段 None，不抛。
- `record=False` → 不落库。
- `get_note_weights`：rank=False → {}；rank=True → 透传 storage。

## Task B3：fact_service — 全局检测

**新** `sidecar/csm_sidecar/services/fact_service.py`。**CP-3 先确认型号+category 枚举方式**。

```python
_pending: list[dict] = []       # ModelChange 队列（session 级）
_lock = threading.Lock()

def detect_changes(index, registry) -> list[dict]:
    """逐型号 resolve_memory → spec_fingerprint → 对基线。首建不报、变更收集并更新基线。"""
    baseline = feedback_storage.get_model_fingerprints()   # model -> (fp, specs_json)
    changes, new_rows = [], []
    for (brand, model, category) in _enumerate_models(index, registry):   # CP-3
        try:
            mem = resolve_memory(brand, model, category, index, own_brands=_own_brands(cfg))
        except Exception:
            continue                       # 该型号解析失败 → 跳过（不因单型号崩全局）
        fp, canonical = spec_fingerprint(mem)
        old = baseline.get(model)
        if old is None:
            new_rows.append((model, fp, canonical))        # 首建基线，不报变更
        elif old[0] != fp:
            changes.append({"model": model,
                            "changed": diff_canonical(old[1], canonical),
                            "detected_at": _utcnow_iso()})
            new_rows.append((model, fp, canonical))         # 更新基线
    if new_rows:
        feedback_storage.upsert_model_fingerprints(new_rows, now=_utcnow_iso())
    if changes:
        with _lock:
            _pending.extend(changes)
    return changes

def drain_changes() -> list[dict]:
    with _lock:
        out = list(_pending); _pending.clear(); return out

def diff_for_model(model, index, registry) -> list[dict]:
    """按需取某型号当前 vs 基线的字段 diff（GET /api/facts/diff）。"""
```

**触发时机**（§7.2）：
- lifespan 启动扫完成后调一次 `detect_changes`（**首次建线不报**，正是要的）。
- `POST /api/vault/scan`（重建索引）成功后调，并把返回值直接塞进响应（前端即时拿）。
- **定位** lifespan 与 vault/scan 路由（Unit B 实现者先 grep `vault/scan`、`lifespan`、`build_brand_registry` 的调用点）。

**测试** `test_fact_service.py`（tmp DB，合成 index/registry；**禁真实库**）：
- 首建不报：空基线 + 两型号 → 返回 []、基线落 2 行。
- 变更报 diff：改一型号参数 → 返回 1 条含 changed、基线更新。
- 未变不报：二次调同 index → []。
- registry 缺型号/解析失败 → 跳过不崩。
- drain 清队列（两次 drain 第二次空）。

## Task B4：generate_service 钩子

**改** `generate_service.py`：
- `submit`（161）：`bus.create_job()` 后 `feedback_service.stash_request(job_id, _snapshot_normal(req))`。
- `submit_comparison`（PR-C）：同样 `stash_request(job_id, _snapshot_comparison(req))`。
- **finalize stash_scopes**（CP-2）：`finalize_draft` 内注入 scope 解析处，把 `(model, spec_fingerprint(mem))` 收集后 `feedback_service.stash_scopes(job_id, snaps)`。normal 与 comparison **两条 finalize 路径都要覆盖**——finalize_draft 是两者共用尾段（PR-C 旁路设计），在共用段挂一次即可，但 comparison 的 scopes 来自 bypass 参、normal 来自内部 resolve，确认两种都能拿到 memory（CP-2）。
  - 实现建议：给 `finalize_draft` 加可选 `on_scopes: Callable[[list], None] | None = None`，在它解析出 scope memory 后回调；`_finalize_job` 两处传 `on_scopes=lambda snaps: feedback_service.stash_scopes(job_id, snaps)`。**不改注入 prompt 字节**（回调只读，旁路）。
- **rank 权重穿透**：`_run_job`（及批量 `_run_batch` 若有）里 `assemble_plan(...)` 调用点，加 `note_weights=feedback_service.get_note_weights()`（rank=False 时返回 {} → 视作 None 语义：**{} 也要走零回归分支**！所以 `assemble_plan` 内 `if not note_weights:` 当 None 处理，别让空 dict 触发 rng.choices）。
  - ⚠️ 定夺：`get_note_weights()` rank 关时返回 `{}`；`assemble_plan`/`_sample_notes_source` 必须把「None 或空 dict」都当今天行为。A4 的判断改成 `if not note_weights:`（None 与 {} 同）。

**测试**：submit/submit_comparison 后 `_request_cache` 有对应快照；finalize 后 `_scopes_cache` 有快照；rank=False 时采样与今天一致（沿用 A4 零回归断言，服务层再钉一遍）。

## Task B5：路由采集钩子 + 新端点

**改** `routes/article.py`（`ExportBody` 第 55、路由 63-71）：
```python
class ExportBody(BaseModel):
    keyword: str
    final_text: str = Field(min_length=1)
    include_dedup_report: bool = False
    template_name: str | None = None
    job_id: str | None = None            # 新：采集关联
    score: float | None = None           # 新：质检卡已算
    score_json: str | None = None        # 新
    lint_unresolved: int = 0             # 新
```
路由体导出成功后：
```python
    result = export_service.export(fmt=fmt, keyword=..., final_text=..., ...)  # 原逻辑不动
    feedback_service.record_export(body.job_id, document_path=result["document"],
        fmt=result["format"], final_text=body.final_text, score=body.score,
        score_json=body.score_json, lint_unresolved=body.lint_unresolved,
        factcheck_blocked=0)             # 正常导出未被 factcheck 拦
    return result
```
（record_export 自身 fail-open，路由无需再包 try。）

**改** `routes/generate.py` `resolve_factcheck`（94-110）：`resolve_and_export` 返回 ok 后 `record_export(job_id, ..., factcheck_blocked=1)`（这条稿曾被 factcheck 拦、用户放行）。final_text 用 `body.final_text`；document/format 从 resolve 返回取。

**新** `routes/feedback.py`：
```python
@router.get("/api/feedback/stats")
def feedback_stats() -> dict: return feedback_service.get_feedback_stats()

@router.get("/api/facts/changes")
def facts_changes() -> dict: return {"changes": fact_service.drain_changes()}

@router.get("/api/facts/diff")
def facts_diff(model: str = Query(...)) -> dict:
    index = vault_service.get(Path(config_service.load().vault_root))
    registry = build_brand_registry(Path(config_service.load().vault_root))
    return {"model": model, "changed": fact_service.diff_for_model(model, index, registry)}
```
在 app include_router 处挂上（定位 routes 注册中心）。

**测试** `test_feedback_routes.py`：/stats 空/有数据形状；/facts/changes drain；/facts/diff 型号 diff；export 路由带 job_id → DB 落一行（tmp DB + config record=True）。

## Task B6：/api/recent 每行增强（§7.3）

**改** `aggregation_service.list_recent`（26-50）：每个 doc 追加：
```python
rec = feedback_storage.find_creation_by_document(str(f))
stale_models = []
if rec is not None:
    baseline = feedback_storage.get_model_fingerprints()
    for snap in feedback_storage.get_fact_snapshots_for_record(rec.id):
        cur = baseline.get(snap.model)
        if cur is not None and cur[0] != snap.fingerprint:
            stale_models.append(snap.model)
item["facts_stale"] = bool(stale_models)
item["stale_models"] = stale_models
item["record"] = {"keyword":..., "template_id":..., "angle_json":..., "skill_chain_json":...,
                  "mode":..., "models_json":..., "contract_mode":...} if rec else None
```
- **形状兼容**：新字段是**追加**，旧前端不读不受影响（`test_recent_stale` 钉旧字段仍在）。
- 无 creation_record 的旧文章：`facts_stale=False`、`record=None`（§7.3 边界：不标）。
- **性能**：list_recent 默认 limit 30，每行 2-3 次索引查询，量小可接受；baseline 每行重取可提到循环外取一次（实现者优化）。

**测试** `test_recent_stale.py`（tmp DB）：有 record + 某快照指纹 != 当前基线 → facts_stale=True + stale_models；无 record → False + record=None；旧字段（path/title/format...）仍在。

**Unit B 三段对抗审查**：正确性（record_export 全链字段、edit_ratio、note 提取递归 children、detect 首建/更新）+ 边界回归（横评/normal 两 finalize 都 stash、{} 权重零回归、/recent 形状兼容、LRU 淘汰、job_id=None）+ 安全 fail-open（record_export 任意子步抛都不影响导出、detect 单型号崩不塌全局、config 隔离、无共享盘写、无循环 import）。

---

# Unit C — 前端

## Task C1：exportArticle 带 job_id + score

**改** `frontend/src/stores/article.ts` `exportArticle`（654-669）POST body 加：
```ts
    job_id: this.lastJobId ?? null,
    score: this.score ?? null,            // PR-B 若已存 score 到 store，带上；无则 null
    score_json: this.scoreJson ?? null,
    lint_unresolved: this.lintUnresolved ?? 0,
```
- **确认** PR-B 后 store 有无 `score`/`scoreJson`/`lintUnresolved`（质检卡算过）；没有就先只带 job_id，score 留 null（后端容忍）。别硬造字段。

## Task C2：config 类型 + FeedbackCard 设置卡

- config store/类型加 `feedback: {record, rank, min_samples, alpha}`。
- **新** `components/settings/FeedbackCard.vue`（仿 `ContractCard.vue` 1-51）：record/rank 两开关 + min_samples 数字（1-20）。onMounted 读 `cfg.data.feedback`，改动 `cfg.patch({feedback:{...}})`，toast「已保存」。挂进设置页（定位 ContractCard 挂载处，同排加）。
- 文案：record「记录导出用于学习（默认开）」、rank「用反馈微调素材采样（默认关，同种子仍可复现）」、min_samples「最小样本数」。

## Task C3：MaterialsView 反馈 tab + FeedbackStatsPanel

- **改** `MaterialsView.vue`（tab ref 10、按钮 32-41）：tab 联合类型加 `"feedback"`，加按钮「使用反馈」，v-if 块渲染 `<FeedbackStatsPanel>`。
- **新** `components/materials/FeedbackStatsPanel.vue`：onMounted `GET /api/feedback/stats` → 两张简表：
  - 素材表现：note_id / uses / avg_edit_ratio / avg_score / keep_score（keep_score 高=改得少=好用）。
  - 角度组合表现：audience+sellpoints+tone / uses / avg_score / avg_edit_ratio。
  - 空态：「导出文章后这里会积累使用统计」。
- 只读展示，无交互门禁，不涉 PR#148 proceed 教训。

## Task C4：RecentHistoryView 过期徽章 + 重新生成

- **改** `api/client.ts` `listRecent`（42-55）返回类型加 `facts_stale?: boolean; stale_models?: string[]; record?: {...} | null`；加 `feedbackStats()`、`factsChanges()`、`factsDiff(model)`。
- **改** `RecentHistoryView.vue`（Doc interface 37-45、行模板 271-298）：
  - Doc 加 `facts_stale?/stale_models?/record?`。
  - stale 行：warn Pill「参数已变更」；hover 触发 `factsDiff(model)` 列出变更字段（懒取，缓存）。
  - 「重新生成」按钮（仅 stale 且 record 非空）：按 `record.mode` 拼 router query 跳创作流——
    - normal：`{keyword, template_id, title, angle(解 angle_json), skill_chain(解 skill_chain_json), contract: contract_mode}`（Hero 同款 query，对齐 CreateArticleHero 读的 key）。
    - comparison：`{mode:"comparison", models(解 models_json → "A,B,C"), keyword, title, skill_chain, tone, contract}`（对齐 PR-C ArticleView init 读的 query key）。
  - **确认** Hero/ArticleView 实际读的 query key 名（PR-B/PR-C 定的），别拼错键。

## Task C5：启动拉 facts/changes → 通知 + 型号 pill

- App 启动 sidecar 就绪后拉一次 `factsChanges()`；`POST /api/vault/scan` 响应也直接带 changes。
- 有变更 → `useNotifications().push("N 个型号参数已更新", {tone:"info", category:"system"})`。
- 变更型号集存进一个轻量 store（session 级）；MaterialsView 型号列表行：若型号 ∈ 变更集 → 小 Pill「参数已更新」。
- **定位** App 启动序列（sidecar handshake / 就绪回调处）与型号列表渲染组件。

**测试**：FeedbackCard patch、FeedbackStatsPanel 空/有数据、RecentHistoryView stale 徽章 render + 重生成 query 组装（normal & comparison 两种）、client 类型。`vue-tsc -b` 0。

**Unit C 两段对抗审查**：正确性（query key 对齐 Hero/ArticleView、stale 判定、patch 深合并）+ 边界（无 record 不显钮、空态、score 字段缺失容忍、vue-tsc union fixture 显式标注 CSM#144）。

---

# 收尾

1. **全量回归**（三端，对基线零新增失败）：
   - `pytest tests/`（csm_core）+ **显式** `pytest sidecar/tests/`（sidecar 不在默认 testpaths，CI 也没 pytest job，必须手跑——见记忆 reference_csm_sidecar_tests_excluded_from_ci）。
   - 前端 `npm run test`（vitest）+ `npx vue-tsc -b`。
   - worktree 双 PYTHONPATH 覆盖：`$env:PYTHONPATH="<worktree>/sidecar;<worktree>"` 让测试吃 worktree 代码而非主仓 editable（记忆 reference_csm_dev_worktree_setup）。
2. **多 Agent 对抗性终审**（3 视角，指令「证伪」）：跨层契约（前端 query key ↔ 后端字段 ↔ DB 列全对齐）/ 正确性（迁移+聚合+指纹+detect）/ 安全（fail-open 真吞、无共享盘写、config 隔离、循环 import、rank 零回归）。
3. **开 PR** base=main（走 PR 流程，push + gh pr create + 返回 URL，停 pending 等网页 merge）。commit 尾 `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`。PR 正文中文。
4. 更新记忆 `project_csm_creation_studio_upgrade.md`：Phase 4+ 全收官。

---

# 备注（实现者纪律，沿用历轮）

- **三个 CP 先确认再动手**（CP-1 采样池 note_id 字段 / CP-2 finalize 指纹 scope 来源 / CP-3 全量型号+category 枚举）。照抄我的猜测会翻车。
- **fail-open 是安全红线**：record_export 及其所有子步一律吞异常 + log，导出主流程绝不受影响。审查者拿「让子步抛异常」证伪。
- **零回归是字节红线**：`assemble_plan` note_weights 为 None **或 {}** 时，采样 RNG 序列与今天逐字节一致。先录基线快照再改。
- **config 隔离铁律**：sidecar 测试一律 monkeypatch `config_service`（init tmp settings.json）；native 开发机会读真实 settings（记忆 feedback_csm_baidu_fetch_test_config_isolation）。
- **共享盘红线**：任何测试禁写 `D:\家电组共享\DATA`；DB 测试全 `init_db(tmp_path)`；真实库只读回归用 `@skipif`。
- **迁移测试用 tmp_path init_db**，`fresh_db` 装置重置 `_db_path/_initialized/_local`（照 tests/core/monitor/test_storage.py）。
- **FK 级联**确认 get_conn 是否 `PRAGMA foreign_keys=ON`；没开则 CASCADE 不生效，记到实现说明。
- **循环 import**：feedback.storage 顶层 import monitor.storage OK；monitor.storage 只能在 `_migrate` 函数体内 lazy import feedback.storage。
- **vue-tsc 必跑**；字面量 union fixture 显式标注（CSM#144）。
