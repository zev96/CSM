"""Verify export() also writes a .md mirror into dedup_history_dir."""
from __future__ import annotations

from pathlib import Path

import frontmatter

from csm_sidecar.services import config_service, export_service


def test_markdown_export_mirrors_to_history(settings_path: Path, tmp_path: Path):
    out_dir = tmp_path / "out"
    history_dir = tmp_path / "history"
    out_dir.mkdir()
    history_dir.mkdir()
    config_service.patch({
        "out_dir": str(out_dir),
        "dedup_history_dir": str(history_dir),
    })

    body = "# 测试标题\n\n吸尘器推荐正文。"
    paths = export_service.export(
        keyword="吸尘器",
        final_text=body,
        fmt="markdown",
        template_name="导购文-基础",
    )
    assert paths["history_path"]
    mirror = Path(paths["history_path"])
    assert mirror.exists()
    assert mirror.suffix == ".md"
    post = frontmatter.loads(mirror.read_text(encoding="utf-8"))
    assert post["title"] == "测试标题"
    assert post["keyword"] == "吸尘器"
    assert post["template"] == "导购文-基础"
    assert post["source_format"] == "markdown"
    assert post["words"] > 0
    assert "exported_at" in post.metadata
    assert "吸尘器推荐正文" in post.content


def test_docx_export_also_mirrors_md(settings_path: Path, tmp_path: Path):
    out_dir = tmp_path / "out"
    history_dir = tmp_path / "history"
    out_dir.mkdir()
    history_dir.mkdir()
    config_service.patch({
        "out_dir": str(out_dir),
        "dedup_history_dir": str(history_dir),
    })

    body = "# 测试\n\n正文 docx 内容"
    paths = export_service.export(
        keyword="key",
        final_text=body,
        fmt="docx",
        template_name=None,
    )
    mirror = Path(paths["history_path"])
    assert mirror.suffix == ".md"
    post = frontmatter.loads(mirror.read_text(encoding="utf-8"))
    assert post["source_format"] == "docx"
    assert post["template"] is None


def test_mirror_filename_dedupes_on_collision(settings_path: Path, tmp_path: Path):
    out_dir = tmp_path / "out"
    history_dir = tmp_path / "history"
    out_dir.mkdir()
    history_dir.mkdir()
    config_service.patch({
        "out_dir": str(out_dir),
        "dedup_history_dir": str(history_dir),
    })

    # Pre-create a file with the same stem the exporter will pick.
    first = export_service.export(
        keyword="k", final_text="# a\n\nbody a", fmt="markdown", template_name=None
    )
    first_stem = Path(first["history_path"]).stem

    # Squat the next-export's mirror name to force the dedupe path.
    squatter = history_dir / f"{first_stem.replace('-1', '-2')}.md"
    squatter.write_text("squatter", encoding="utf-8")

    second = export_service.export(
        keyword="k", final_text="# b\n\nbody b", fmt="markdown", template_name=None
    )
    # The exporter picks the next free MMDD-N stem; if it happens to collide
    # with our squatter, the dedupe suffix path triggers and emits MMDD-N-2.
    mirror2 = Path(second["history_path"])
    assert mirror2.exists()
    assert mirror2.read_text(encoding="utf-8") != "squatter"


def test_mirror_skipped_when_history_dir_unset(settings_path: Path, tmp_path: Path):
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    config_service.patch({"out_dir": str(out_dir), "dedup_history_dir": ""})

    paths = export_service.export(
        keyword="x", final_text="# t\n\nbody", fmt="markdown", template_name=None
    )
    assert paths["history_path"] is None


def test_mirror_failure_does_not_break_export(settings_path: Path, tmp_path: Path, monkeypatch):
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    config_service.patch({
        "out_dir": str(out_dir),
        # Point history dir at a file (not a directory) — mkdir/write will fail.
        "dedup_history_dir": str(tmp_path / "blocker_file"),
    })
    (tmp_path / "blocker_file").write_text("not a dir", encoding="utf-8")

    paths = export_service.export(
        keyword="x", final_text="# t\n\nbody", fmt="markdown", template_name=None
    )
    # Primary export must still succeed.
    assert Path(paths["document"]).exists()
    assert paths["history_path"] is None
