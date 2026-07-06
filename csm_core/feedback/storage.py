"""反馈学习闭环持久层 —— monitor.db v9。

挂进 ``monitor.storage`` 版本链（仿 mining/geo）：``apply_v9_migration`` 由
``monitor.storage._migrate`` 在函数体内 lazy import 调用。**顶层只 import
monitor.storage**（拿连接池），反向 import 留在 monitor 那边的函数体内，不成环。

连接经 ``monitor_storage.get_conn()``：``isolation_level=None`` 自动提交 +
``PRAGMA foreign_keys=ON``（子表 ON DELETE CASCADE 生效）+ ``sqlite3.Row``。
"""
from __future__ import annotations

import json
import sqlite3

from csm_core.feedback.model import CreationRecord, FactSnapshot, NoteUsage
from csm_core.monitor import storage as monitor_storage

# ── DDL（幂等；逐字照 spec §6.1）───────────────────────────────────────────────
_DDL_V9_FEEDBACK: list[str] = [
    """
    CREATE TABLE IF NOT EXISTS creation_records (
        id                INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id            TEXT UNIQUE NOT NULL,
        mode              TEXT NOT NULL DEFAULT 'normal',   -- normal | comparison | batch
        keyword           TEXT, template_id TEXT, title TEXT,
        angle_json        TEXT, skill_chain_json TEXT, models_json TEXT,
        contract_mode     TEXT,
        document_path     TEXT, format TEXT,
        edit_ratio        REAL,
        lint_unresolved   INTEGER DEFAULT 0,
        factcheck_blocked INTEGER DEFAULT 0,
        score             REAL, score_json TEXT,
        created_at        TEXT NOT NULL, exported_at TEXT NOT NULL
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


# ── creation_records 写 ───────────────────────────────────────────────────────
def record_creation(
    rec: CreationRecord,
    note_usage: list[NoteUsage],
    fact_snaps: list[FactSnapshot],
) -> int:
    """插一条成稿记录 + 其 note 用量 + 事实快照（单事务）。

    ``job_id`` UNIQUE。重复导出同 job → **覆盖**（先 DELETE 旧行，级联清子表，
    再插），保证「导出→改→再导出」只留最后一版、子表不累加。返回 record_id。
    """
    conn = get_conn()
    conn.execute("BEGIN")
    try:
        conn.execute("DELETE FROM creation_records WHERE job_id=?", (rec.job_id,))
        cur = conn.execute(
            """
            INSERT INTO creation_records(
                job_id, mode, keyword, template_id, title,
                angle_json, skill_chain_json, models_json, contract_mode,
                document_path, format, edit_ratio, lint_unresolved, factcheck_blocked,
                score, score_json, created_at, exported_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            RETURNING id
            """,
            (
                rec.job_id, rec.mode, rec.keyword, rec.template_id, rec.title,
                rec.angle_json, rec.skill_chain_json, rec.models_json, rec.contract_mode,
                rec.document_path, rec.format, rec.edit_ratio,
                rec.lint_unresolved, rec.factcheck_blocked,
                rec.score, rec.score_json, rec.created_at, rec.exported_at,
            ),
        )
        record_id = int(cur.fetchone()[0])
        for nu in note_usage:
            conn.execute(
                "INSERT INTO creation_note_usage(record_id, note_id, variant_index, block_id) "
                "VALUES(?,?,?,?)",
                (record_id, nu.note_id, nu.variant_index, nu.block_id),
            )
        for fs in fact_snaps:
            conn.execute(
                "INSERT INTO fact_snapshots(record_id, model, fingerprint, specs_json, created_at) "
                "VALUES(?,?,?,?,?)",
                (record_id, fs.model, fs.fingerprint, fs.specs_json, rec.exported_at),
            )
        conn.execute("COMMIT")
        return record_id
    except Exception:
        conn.execute("ROLLBACK")
        raise


# ── 排序权重（rank，默认关）───────────────────────────────────────────────────
def get_note_weights(min_samples: int, alpha: float) -> dict[str, float]:
    """按 note_id 聚合成采样权重。

    样本 = 用过该 note 且 ``edit_ratio`` 非空的**去重 record 数**（一条 record 多次
    用同 note 只算一次，杜绝变体重复灌水）。``keep_score = avg(1 - edit_ratio)``；
    ``weight = clamp(1 + alpha*(keep_score-0.5)*2, 0.5, 1.5)``；样本 < min_samples
    不入 dict（调用方视作权重 1.0）。
    """
    conn = get_conn()
    rows = conn.execute(
        """
        WITH per_note_record AS (
            SELECT DISTINCT nu.note_id AS note_id, cr.id AS record_id, cr.edit_ratio AS edit_ratio
            FROM creation_note_usage nu JOIN creation_records cr ON nu.record_id = cr.id
            WHERE cr.edit_ratio IS NOT NULL
        )
        SELECT note_id, COUNT(*) AS n, AVG(1.0 - edit_ratio) AS keep
        FROM per_note_record GROUP BY note_id HAVING COUNT(*) >= ?
        """,
        (min_samples,),
    ).fetchall()
    out: dict[str, float] = {}
    for r in rows:
        keep = r["keep"]
        w = 1.0 + alpha * (keep - 0.5) * 2.0
        out[r["note_id"]] = max(0.5, min(1.5, w))
    return out


# ── 呈现统计（/api/feedback/stats）────────────────────────────────────────────
def get_feedback_stats() -> dict:
    """两张表：notes（素材表现 top50 by uses）+ angles（角度组合 top20 by uses）。"""
    conn = get_conn()
    note_rows = conn.execute(
        """
        WITH per_note_record AS (
            SELECT DISTINCT nu.note_id AS note_id, cr.id AS record_id,
                   cr.edit_ratio AS edit_ratio, cr.score AS score
            FROM creation_note_usage nu JOIN creation_records cr ON nu.record_id = cr.id
        )
        SELECT note_id, COUNT(*) AS uses,
               AVG(edit_ratio) AS avg_edit, AVG(score) AS avg_score,
               AVG(CASE WHEN edit_ratio IS NOT NULL THEN 1.0 - edit_ratio END) AS keep
        FROM per_note_record GROUP BY note_id ORDER BY uses DESC LIMIT 50
        """
    ).fetchall()
    notes = [
        {
            "note_id": r["note_id"], "uses": r["uses"],
            "avg_edit_ratio": r["avg_edit"], "avg_score": r["avg_score"],
            "keep_score": r["keep"],
        }
        for r in note_rows
    ]

    # angles 走 Python（angle_json 是 JSON 文本，SQL 拆不动）。
    angle_rows = conn.execute(
        "SELECT angle_json, score, edit_ratio FROM creation_records "
        "WHERE angle_json IS NOT NULL AND angle_json != ''"
    ).fetchall()
    buckets: dict[tuple, dict] = {}
    for r in angle_rows:
        try:
            a = json.loads(r["angle_json"])
        except (ValueError, TypeError):
            continue
        if not isinstance(a, dict):
            continue
        audience = a.get("audience")
        sellpoints = a.get("sellpoints") or []
        if not isinstance(sellpoints, list):
            sellpoints = []
        tone = a.get("tone")
        key = (audience, tuple(sorted(str(s) for s in sellpoints)), tone)
        b = buckets.setdefault(key, {"uses": 0, "scores": [], "edits": []})
        b["uses"] += 1
        if r["score"] is not None:
            b["scores"].append(r["score"])
        if r["edit_ratio"] is not None:
            b["edits"].append(r["edit_ratio"])
    angles = [
        {
            "audience": audience, "sellpoints": list(sellpoints), "tone": tone,
            "uses": b["uses"],
            "avg_score": (sum(b["scores"]) / len(b["scores"])) if b["scores"] else None,
            "avg_edit_ratio": (sum(b["edits"]) / len(b["edits"])) if b["edits"] else None,
        }
        for (audience, sellpoints, tone), b in buckets.items()
    ]
    angles.sort(key=lambda x: x["uses"], reverse=True)
    return {"notes": notes, "angles": angles[:20]}


# ── 型号指纹基线（§7）─────────────────────────────────────────────────────────
def get_model_fingerprints() -> dict[str, tuple[str, str]]:
    """model -> (fingerprint, specs_json) 全量基线。"""
    conn = get_conn()
    rows = conn.execute(
        "SELECT model, fingerprint, specs_json FROM model_fingerprints"
    ).fetchall()
    return {r["model"]: (r["fingerprint"], r["specs_json"]) for r in rows}


def upsert_model_fingerprints(rows: list[tuple[str, str, str]], *, now: str) -> None:
    """``[(model, fingerprint, specs_json)]`` INSERT OR REPLACE，updated_at=now。"""
    conn = get_conn()
    conn.executemany(
        "INSERT OR REPLACE INTO model_fingerprints(model, fingerprint, specs_json, updated_at) "
        "VALUES(?,?,?,?)",
        [(m, fp, sj, now) for (m, fp, sj) in rows],
    )


# ── 历史关联（/api/recent 增强）───────────────────────────────────────────────
def find_creation_by_document(document_path: str) -> CreationRecord | None:
    """按 document_path 取最新一条（可能多次导出到同名 → exported_at DESC）。"""
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM creation_records WHERE document_path=? ORDER BY exported_at DESC LIMIT 1",
        (document_path,),
    ).fetchone()
    return _row_to_record(row) if row else None


def get_fact_snapshots_for_record(record_id: int) -> list[FactSnapshot]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT model, fingerprint, specs_json FROM fact_snapshots WHERE record_id=?",
        (record_id,),
    ).fetchall()
    return [
        FactSnapshot(model=r["model"], fingerprint=r["fingerprint"], specs_json=r["specs_json"])
        for r in rows
    ]


def _row_to_record(row: sqlite3.Row) -> CreationRecord:
    return CreationRecord(
        id=row["id"], job_id=row["job_id"], mode=row["mode"], keyword=row["keyword"],
        template_id=row["template_id"], title=row["title"],
        angle_json=row["angle_json"], skill_chain_json=row["skill_chain_json"],
        models_json=row["models_json"], contract_mode=row["contract_mode"],
        document_path=row["document_path"], format=row["format"],
        edit_ratio=row["edit_ratio"], lint_unresolved=row["lint_unresolved"],
        factcheck_blocked=row["factcheck_blocked"], score=row["score"],
        score_json=row["score_json"], created_at=row["created_at"], exported_at=row["exported_at"],
    )
