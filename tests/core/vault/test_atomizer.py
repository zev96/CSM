from csm_core.vault import atomizer as A
from csm_core.vault.folder_profile import FolderProfile


def _folders():
    return [
        FolderProfile(rel_folder="科普模块/吸尘器/挑选攻略",
                      frontmatter_keys=["产品", "素材类型", "核心关键词"],
                      defaults={"产品": "吸尘器"}, body_shape="variants",
                      sample_count=2, material_types=["科普选购", "引言痛点"]),
        FolderProfile(rel_folder="产品模块/吸尘器/产品参数",
                      frontmatter_keys=["品牌", "型号"], defaults={},
                      body_shape="spec_table", sample_count=1, material_types=["产品参数"]),
    ]


def test_build_menu_excludes_spec_table_and_lists_types():
    menu = A.build_menu(_folders())
    assert "科普模块/吸尘器/挑选攻略" in menu
    assert "科普选购" in menu and "引言痛点" in menu
    assert "产品模块/吸尘器/产品参数" not in menu     # spec_table 不进菜单


def test_safe_filename_spaces_and_seps():
    assert A._safe_filename("吸力 选购", "kw") == "吸力-选购.md"
    assert A._safe_filename("a/b\\c", "kw") == "a-b-c.md"


def test_safe_filename_empty_uses_fallback():
    assert A._safe_filename("", "吸力") == "吸力.md"
    assert A._safe_filename("   ", "") == "素材.md"


def test_safe_filename_keeps_md_suffix():
    assert A._safe_filename("吸力选购.md", "kw") == "吸力选购.md"


import json as _json


def test_parse_atoms_valid_array():
    raw = _json.dumps([
        {"正文": "看吸力", "建议文件夹": "科普模块/吸尘器/挑选攻略", "素材类型": "科普选购",
         "产品": "通用", "核心关键词": "吸力", "建议文件名": "吸力选购", "置信度": "high"},
        {"正文": "看噪音", "建议文件夹": "科普模块/吸尘器/挑选攻略", "素材类型": "科普选购",
         "产品": "希喂", "核心关键词": "噪音", "建议文件名": "噪音", "置信度": "med"},
    ], ensure_ascii=False)
    atoms = A.parse_atoms(raw, _folders())
    assert len(atoms) == 2
    assert atoms[0].text == "看吸力"
    assert atoms[0].rel_folder == "科普模块/吸尘器/挑选攻略"
    assert atoms[0].filename == "吸力选购.md"
    assert atoms[0].confidence == "high"
    assert atoms[1].product == "希喂"


def test_parse_atoms_strips_code_fence():
    raw = "```json\n" + _json.dumps([{"正文": "x", "置信度": "low"}], ensure_ascii=False) + "\n```"
    atoms = A.parse_atoms(raw, _folders())
    assert len(atoms) == 1 and atoms[0].text == "x"


def test_parse_atoms_extracts_array_with_preamble():
    raw = "好的，拆好了：\n" + _json.dumps([{"正文": "y", "置信度": "high"}], ensure_ascii=False)
    atoms = A.parse_atoms(raw, _folders())
    assert len(atoms) == 1 and atoms[0].text == "y"


def test_parse_atoms_non_array_returns_empty():
    assert A.parse_atoms('{"正文": "x"}', _folders()) == []
    assert A.parse_atoms("根本不是 JSON", _folders()) == []


def test_parse_atoms_offmenu_folder_blanked_with_warning():
    raw = _json.dumps([{"正文": "z", "建议文件夹": "不存在/文件夹", "置信度": "med"}], ensure_ascii=False)
    atoms = A.parse_atoms(raw, _folders())
    assert atoms[0].rel_folder is None
    assert any("不在素材库" in w for w in atoms[0].warnings)


def test_parse_atoms_invalid_confidence_defaults_low():
    raw = _json.dumps([{"正文": "z", "置信度": "拿不准"}], ensure_ascii=False)
    assert A.parse_atoms(raw, _folders())[0].confidence == "low"


def test_parse_atoms_empty_text_skipped():
    raw = _json.dumps([{"正文": "   ", "置信度": "high"}, {"正文": "ok", "置信度": "high"}], ensure_ascii=False)
    atoms = A.parse_atoms(raw, _folders())
    assert len(atoms) == 1 and atoms[0].text == "ok"


def test_parse_atoms_filename_from_keyword_when_missing():
    raw = _json.dumps([{"正文": "z", "核心关键词": "续航", "置信度": "high"}], ensure_ascii=False)
    assert A.parse_atoms(raw, _folders())[0].filename == "续航.md"


def test_parse_atoms_filename_from_text_when_no_keyword():
    long = "这是一段足够长的中文正文用来测试文件名回退逻辑"
    raw = _json.dumps([{"正文": long, "置信度": "high"}], ensure_ascii=False)
    atoms = A.parse_atoms(raw, _folders())
    assert atoms[0].filename == long[:12] + ".md"
