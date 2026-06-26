import hashlib
from pathlib import Path
import pytest
from csm_core.vault import writer


def _index_vault(root: Path) -> None:
    (root / "科普模块/吸尘器/挑选攻略").mkdir(parents=True, exist_ok=True)
    (root / "科普模块/吸尘器/吸尘器科普内容索引.md").write_text(
        "---\n产品: 吸尘器\n---\n\n# 科普索引\n\n## 挑选攻略\n\n旧内容\n", encoding="utf-8")


def _plan(root: Path):
    return writer.plan_note(
        root,
        rel_folder="科普模块/吸尘器/挑选攻略",
        filename="吸尘器-噪音选购.md",
        frontmatter={"产品": "吸尘器", "素材类型": "科普选购", "核心关键词": ["噪音"]},
        body_shape="variants",
        variants=["看噪音分贝", "看降噪结构"],
        today="2026-06-26",
    )


def test_plan_renders_full_note(tmp_path):
    _index_vault(tmp_path)
    p = _plan(tmp_path)
    assert p.rel_path == "科普模块/吸尘器/挑选攻略/吸尘器-噪音选购.md"
    assert p.conflict is False
    assert "素材类型: 科普选购" in p.full_text
    assert "① 看噪音分贝" in p.full_text and "② 看降噪结构" in p.full_text
    # 双链尾按最近祖先索引（吸尘器科普内容索引），不照 CLAUDE.md 死表
    assert "**返回上层**: [[吸尘器科普内容索引|吸尘器科普内容索引]]" in p.full_text
    assert "**返回主页**: [[关联数据库]]" in p.full_text
    assert p.index_rel == "科普模块/吸尘器/吸尘器科普内容索引.md"
    assert p.index_line == "- [[吸尘器-噪音选购]] · 科普选购 · 2026-06-26"


def test_plan_spec_table_body(tmp_path):
    (tmp_path / "产品模块/吸尘器/产品参数").mkdir(parents=True, exist_ok=True)
    p = writer.plan_note(
        tmp_path, rel_folder="产品模块/吸尘器/产品参数",
        filename="CEWEYDS19-产品参数.md",
        frontmatter={"产品": "吸尘器", "素材类型": "产品参数", "型号": "CEWEYDS19"},
        body_shape="spec_table",
        spec_rows=[{"group": "性能参数", "key": "吸力", "value": "230"},
                   {"group": "性能参数", "key": "真空度", "value": "38000"}],
        today="2026-06-26")
    assert "## 性能参数" in p.full_text
    assert "| 吸力 | 230 |" in p.full_text and "| 真空度 | 38000 |" in p.full_text


def test_plan_no_index_warns(tmp_path):
    (tmp_path / "孤立文件夹").mkdir(parents=True, exist_ok=True)
    p = writer.plan_note(
        tmp_path, rel_folder="孤立文件夹", filename="吸尘器-x.md",
        frontmatter={"产品": "吸尘器"}, body_shape="variants",
        variants=["a"], today="2026-06-26")
    assert p.index_rel is None and p.index_line is None
    assert any("无祖先索引" in w for w in p.warnings)
    assert "**返回主页**: [[关联数据库]]" in p.full_text


def test_plan_conflict_when_exists(tmp_path):
    _index_vault(tmp_path)
    (tmp_path / "科普模块/吸尘器/挑选攻略/吸尘器-噪音选购.md").write_text("x", encoding="utf-8")
    assert _plan(tmp_path).conflict is True


def test_commit_writes_file_and_registers(tmp_path):
    _index_vault(tmp_path)
    p = _plan(tmp_path)
    receipt = writer.commit_note(p, tmp_path)
    target = tmp_path / p.rel_path
    assert target.read_text(encoding="utf-8") == p.full_text
    assert receipt.content_sha == hashlib.sha256(p.full_text.encode("utf-8")).hexdigest()
    idx_text = (tmp_path / p.index_rel).read_text(encoding="utf-8")
    assert "## App 新增（待人工归入）" in idx_text
    assert "- [[吸尘器-噪音选购]] · 科普选购 · 2026-06-26" in idx_text
    assert "旧内容" in idx_text  # 人工内容未被破坏


def test_commit_idempotent_block(tmp_path):
    _index_vault(tmp_path)
    p = _plan(tmp_path)
    writer.commit_note(p, tmp_path)
    (tmp_path / p.rel_path).unlink()       # 删文件但留索引行
    writer.commit_note(p, tmp_path)        # 再写一次
    idx_text = (tmp_path / p.index_rel).read_text(encoding="utf-8")
    assert idx_text.count("- [[吸尘器-噪音选购]] ·") == 1   # 不重复登记


def test_commit_refuses_overwrite(tmp_path):
    _index_vault(tmp_path)
    p = _plan(tmp_path)
    writer.commit_note(p, tmp_path)
    with pytest.raises(FileExistsError):
        writer.commit_note(p, tmp_path)


def test_undo_deletes_when_unchanged(tmp_path):
    _index_vault(tmp_path)
    p = _plan(tmp_path)
    receipt = writer.commit_note(p, tmp_path)
    warnings = writer.undo_write(receipt, tmp_path)
    assert not (tmp_path / p.rel_path).exists()
    idx_text = (tmp_path / p.index_rel).read_text(encoding="utf-8")
    assert "吸尘器-噪音选购" not in idx_text
    assert warnings == []


def test_undo_skips_when_modified(tmp_path):
    _index_vault(tmp_path)
    p = _plan(tmp_path)
    receipt = writer.commit_note(p, tmp_path)
    (tmp_path / p.rel_path).write_text("被人工改了", encoding="utf-8")
    warnings = writer.undo_write(receipt, tmp_path)
    assert (tmp_path / p.rel_path).exists()             # 没删
    assert any("已被改动" in w for w in warnings)
