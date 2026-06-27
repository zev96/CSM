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
