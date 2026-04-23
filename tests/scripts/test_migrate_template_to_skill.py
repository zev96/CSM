"""Tests for one-shot template→skill migration."""
from __future__ import annotations
import json
from pathlib import Path
import pytest
from scripts.migrate_template_to_skill import migrate_file, migrate_directory


def _write_legacy_template(dir_: Path, tid: str, sys_prompt: str, seo: dict) -> Path:
    p = dir_ / f"{tid}.json"
    p.write_text(json.dumps({
        "id": tid, "name": tid, "product": "吸尘器",
        "version": 1,
        "system_prompt_default": sys_prompt,
        "seo_defaults": seo,
        "blocks": [{"kind": "literal", "id": "lit", "text": "hi"}],
    }, ensure_ascii=False), encoding="utf-8")
    return p


def test_migrate_file_writes_skill_and_rewrites_json(tmp_path):
    tpl_dir = tmp_path / "templates"; tpl_dir.mkdir()
    skill_dir = tmp_path / "skills"; skill_dir.mkdir()

    tpl = _write_legacy_template(
        tpl_dir, "tpl-a",
        sys_prompt="你是家电编辑。",
        seo={
            "target_word_count": [1500, 2000],
            "keyword_density": [5, 8],
            "tone": "小红书笔记体",
            "force_h2": True,
            "long_tail_keywords": ["家用吸尘器推荐", "宠物吸尘器对比"],
        },
    )

    result = migrate_file(tpl, skill_dir)
    assert result is not None
    skill_path = skill_dir / "tpl-a-migrated.md"
    assert skill_path.is_file()

    content = skill_path.read_text(encoding="utf-8")
    assert "你是家电编辑。" in content
    assert "1500-2000" in content
    assert "5-8" in content
    assert "小红书笔记体" in content
    assert "家用吸尘器推荐" in content
    assert "必须使用 H2" in content

    rewritten = json.loads(tpl.read_text(encoding="utf-8"))
    assert rewritten["default_skill_id"] == "tpl-a-migrated"
    assert "version" not in rewritten
    assert "system_prompt_default" not in rewritten
    assert "seo_defaults" not in rewritten

    backup = tpl.with_suffix(tpl.suffix + ".bak")
    assert backup.is_file()
    assert "system_prompt_default" in json.loads(backup.read_text(encoding="utf-8"))


def test_migrate_file_is_idempotent(tmp_path):
    tpl_dir = tmp_path / "t"; tpl_dir.mkdir()
    skill_dir = tmp_path / "s"; skill_dir.mkdir()
    tpl = _write_legacy_template(tpl_dir, "x", "s", {
        "target_word_count": [100, 200], "keyword_density": [1, 2],
        "tone": "t", "force_h2": False, "long_tail_keywords": [],
    })

    migrate_file(tpl, skill_dir)
    second = migrate_file(tpl, skill_dir)
    assert second is None


def test_migrate_directory_migrates_all_and_skips_non_json(tmp_path):
    tpl_dir = tmp_path / "t"; tpl_dir.mkdir()
    skill_dir = tmp_path / "s"; skill_dir.mkdir()
    _write_legacy_template(tpl_dir, "a", "A", {
        "target_word_count": [1, 2], "keyword_density": [1, 2],
        "tone": "t", "force_h2": True, "long_tail_keywords": [],
    })
    _write_legacy_template(tpl_dir, "b", "B", {
        "target_word_count": [1, 2], "keyword_density": [1, 2],
        "tone": "t", "force_h2": True, "long_tail_keywords": [],
    })
    (tpl_dir / "README.txt").write_text("not a template", encoding="utf-8")

    results = migrate_directory(tpl_dir, skill_dir)
    assert len(results) == 2
    assert (skill_dir / "a-migrated.md").is_file()
    assert (skill_dir / "b-migrated.md").is_file()


def test_migrate_file_noop_when_no_legacy_fields(tmp_path):
    tpl_dir = tmp_path / "t"; tpl_dir.mkdir()
    skill_dir = tmp_path / "s"; skill_dir.mkdir()
    p = tpl_dir / "clean.json"
    p.write_text(json.dumps({
        "id": "clean", "name": "c", "product": "p",
        "default_skill_id": "some-skill",
        "blocks": [{"kind": "literal", "id": "lit", "text": "hi"}],
    }, ensure_ascii=False), encoding="utf-8")

    assert migrate_file(p, skill_dir) is None
