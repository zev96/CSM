import json
from pathlib import Path
from csm_core.assembler.plan import AssemblyPlan, BlockResult, PickedVariant
from csm_core.export.markdown import export_article


def _sample_plan() -> AssemblyPlan:
    return AssemblyPlan(
        keyword="宠物吸尘器推荐",
        template_id="daogou-changjing-renqun",
        seed=42,
        results=[BlockResult(
            block_id="intro",
            kind="paragraph",
            picks=[PickedVariant(note_id="n", variant_index=0, text="引言内容")],
        )],
    )


def test_export_writes_md_and_assembly_json(tmp_path: Path):
    paths = export_article(
        out_dir=tmp_path,
        keyword="宠物吸尘器推荐",
        final_text="# 标题\n\n正文内容",
        plan=_sample_plan(),
        prompt_snapshot={"system": "sys", "user": "usr", "provider": "mock"},
    )
    md_path = Path(paths["markdown"])
    json_path = Path(paths["assembly_json"])
    assert md_path.exists()
    assert md_path.read_text(encoding="utf-8") == "# 标题\n\n正文内容"
    assert json_path.exists()
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data["plan"]["keyword"] == "宠物吸尘器推荐"
    assert data["prompt_snapshot"]["provider"] == "mock"


def test_export_sanitizes_filename(tmp_path: Path):
    paths = export_article(
        out_dir=tmp_path,
        keyword="带/特殊\\字符:的?关键词",
        final_text="x",
        plan=_sample_plan(),
        prompt_snapshot={},
    )
    md_path = Path(paths["markdown"])
    assert md_path.exists()
    for ch in ("/", "\\", ":", "?"):
        assert ch not in md_path.name


def test_export_raises_when_out_dir_missing(tmp_path: Path):
    nonexistent = tmp_path / "does_not_exist"
    import pytest
    with pytest.raises(FileNotFoundError):
        export_article(
            out_dir=nonexistent,
            keyword="k", final_text="t",
            plan=_sample_plan(), prompt_snapshot={},
        )
