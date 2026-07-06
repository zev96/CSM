"""反馈闭环轻量数据类 —— 纯搬运（storage 行 <-> 服务层），不做校验。"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class NoteUsage:
    """一条成稿用到的某个素材变体（note 用量）。"""
    note_id: str
    variant_index: int | None = None
    block_id: str | None = None


@dataclass
class FactSnapshot:
    """成稿导出时某型号的事实指纹快照（供 §7 过期判定）。"""
    model: str
    fingerprint: str
    specs_json: str


@dataclass
class CreationRecord:
    """一条成稿导出记录（creation_records 行）。``id`` 读回时填，插入时忽略。"""
    job_id: str
    mode: str
    keyword: str | None
    template_id: str | None
    title: str | None
    angle_json: str | None
    skill_chain_json: str | None
    models_json: str | None
    contract_mode: str | None
    document_path: str | None
    format: str | None
    edit_ratio: float | None
    lint_unresolved: int
    factcheck_blocked: int
    score: float | None
    score_json: str | None
    created_at: str
    exported_at: str
    id: int | None = None
