import json
from pathlib import Path
import pytest
from csm_core.framework.loader import load_framework, save_framework, list_frameworks
from csm_core.framework.schema import Framework, ParagraphBlock


def _write(path: Path, data: dict):
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_load_framework_round_trips(tmp_path):
    fw = Framework(
        id="fx", name="n", variables=["keyword"],
        blocks=[ParagraphBlock(kind="paragraph", slot="s1")],
    )
    path = tmp_path / "fx.json"
    save_framework(fw, path)
    loaded = load_framework(path)
    assert loaded.id == "fx"
    assert loaded.blocks[0].slot == "s1"


def test_load_framework_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_framework(tmp_path / "nope.json")


def test_list_frameworks_sorted_by_name(tmp_path):
    _write(tmp_path / "a.json", {"id": "a", "name": "Zebra", "variables": [],
                                  "blocks": [{"kind": "paragraph", "slot": "s1"}]})
    _write(tmp_path / "b.json", {"id": "b", "name": "Apple", "variables": [],
                                  "blocks": [{"kind": "paragraph", "slot": "s1"}]})
    out = list_frameworks(tmp_path)
    assert [name for name, _ in out] == ["Apple", "Zebra"]


def test_list_frameworks_skips_hidden_and_trash(tmp_path):
    (tmp_path / ".trash").mkdir()
    _write(tmp_path / ".trash" / "x.json", {"id": "x", "name": "Hidden",
                                             "variables": [],
                                             "blocks": [{"kind": "paragraph", "slot": "s"}]})
    _write(tmp_path / ".hidden.json", {"id": "h", "name": "Hidden2",
                                        "variables": [],
                                        "blocks": [{"kind": "paragraph", "slot": "s"}]})
    _write(tmp_path / "ok.json", {"id": "ok", "name": "OK",
                                   "variables": [],
                                   "blocks": [{"kind": "paragraph", "slot": "s"}]})
    out = list_frameworks(tmp_path)
    assert [name for name, _ in out] == ["OK"]


def test_list_frameworks_missing_dir(tmp_path):
    assert list_frameworks(tmp_path / "does-not-exist") == []


def test_list_frameworks_falls_back_to_stem_on_parse_error(tmp_path):
    (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")
    out = list_frameworks(tmp_path)
    assert out == [("broken", tmp_path / "broken.json")]
