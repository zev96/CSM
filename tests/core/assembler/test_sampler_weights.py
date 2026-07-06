"""note_weights 加权采样 —— 零回归（None/{} 逐字节同今天）+ 加权偏置 + 确定性。

用 ParagraphBlock（constraints 默认 []，走非唯一分支=加权分支）；NumberedList
默认 unique_notes 是唯一分支，v1 不加权。
"""
from pathlib import Path

from csm_core.assembler.sampler import sample_block
from csm_core.template.schema import NotesQuerySource, ParagraphBlock
from csm_core.vault.brand_registry import build_brand_registry
from csm_core.vault.scanner import scan_vault


def _write(vault: Path, rel: str, fm: dict, body: str) -> None:
    p = vault / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    fms = "\n".join(f"{k}: {v}" for k, v in fm.items())
    p.write_text(f"---\n{fms}\n---\n{body}\n", encoding="utf-8")


def _seed_pool(tmp_path: Path):
    for i in range(4):
        _write(tmp_path, f"L/{i}.md", {"产品": "吸尘器"}, f"条目{i}")
    return scan_vault(tmp_path), build_brand_registry(tmp_path)


def _blk(n: int) -> ParagraphBlock:
    return ParagraphBlock(
        id="s1", label="L", source=NotesQuerySource(module="L"),
        pick_notes=n, pick_variants_per_note=1,
    )


def test_note_weights_none_is_zero_regression(tmp_path):
    idx, reg = _seed_pool(tmp_path)
    base = [p.note_id for p in sample_block(_blk(20), idx, reg, seed=7, user_config={}).picks]
    none = [p.note_id for p in sample_block(
        _blk(20), idx, reg, seed=7, user_config={}, note_weights=None).picks]
    empty = [p.note_id for p in sample_block(
        _blk(20), idx, reg, seed=7, user_config={}, note_weights={}).picks]
    assert base == none   # 显式 None 与不传一致
    assert base == empty  # 空 dict 也走零回归分支（不触发 rng.choices）


def test_note_weights_bias_favored(tmp_path):
    idx, reg = _seed_pool(tmp_path)
    uniform = sample_block(_blk(80), idx, reg, seed=3, user_config={})
    favored = sorted({p.note_id for p in uniform.picks})[0]
    weighted = sample_block(
        _blk(80), idx, reg, seed=3, user_config={}, note_weights={favored: 5.0})
    ids = [p.note_id for p in weighted.picks]
    # 4 note、favored 权重 5 其余 1 → 期望占比 ~5/8=62.5%；宽松断言 >40%（均匀仅 25%）。
    assert ids.count(favored) > len(ids) * 0.4


def test_note_weights_deterministic(tmp_path):
    idx, reg = _seed_pool(tmp_path)
    # note.id 是 stem（"0"），不是 "L/0.md" —— 用真键才真正走非均匀加权路径（对抗审查 D1）。
    w = {"0": 2.0}
    r1 = [p.note_id for p in sample_block(
        _blk(30), idx, reg, seed=9, user_config={}, note_weights=w).picks]
    r2 = [p.note_id for p in sample_block(
        _blk(30), idx, reg, seed=9, user_config={}, note_weights=w).picks]
    assert r1 == r2  # 同 seed 同权重 → 完全一致（可复现）
