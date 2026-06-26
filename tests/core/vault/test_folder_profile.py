from pathlib import Path
from csm_core.vault.scanner import scan_vault
from csm_core.vault import folder_profile as fp


def _write(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _variants_vault(root: Path) -> None:
    _write(root, "科普模块/吸尘器/挑选攻略/吸尘器-吸力选购.md",
           "---\n产品: 吸尘器\n素材类型: 科普选购\n核心关键词:\n  - 吸力\n---\n\n① 看吸力\n\n② 看真空度\n")
    _write(root, "科普模块/吸尘器/挑选攻略/吸尘器-续航选购.md",
           "---\n产品: 吸尘器\n素材类型: 科普选购\n核心关键词:\n  - 续航\n---\n\n① 看续航\n\n② 看电池\n")


def _spec_vault(root: Path) -> None:
    _write(root, "产品模块/吸尘器/产品参数/CEWEYDS18-产品参数.md",
           "---\n产品: 吸尘器\n素材类型: 产品参数\n品牌: CEWEY\n型号: CEWEYDS18\n---\n\n"
           "## 性能参数\n\n| 参数 | 数值 |\n|------|------|\n| 吸力 | 220 |\n")


def test_profile_variants_folder(tmp_path):
    _variants_vault(tmp_path)
    idx = scan_vault(tmp_path)
    prof = fp.profile_folder(idx, "科普模块/吸尘器/挑选攻略")
    assert prof.body_shape == "variants"
    assert prof.sample_count == 2
    assert prof.defaults.get("产品") == "吸尘器"
    assert prof.defaults.get("素材类型") == "科普选购"
    assert "核心关键词" in prof.frontmatter_keys
    assert prof.material_types == ["科普选购"]


def test_profile_spec_table_folder(tmp_path):
    _spec_vault(tmp_path)
    idx = scan_vault(tmp_path)
    prof = fp.profile_folder(idx, "产品模块/吸尘器/产品参数")
    assert prof.body_shape == "spec_table"
    assert "品牌" in prof.frontmatter_keys and "型号" in prof.frontmatter_keys


def test_list_writable_folders(tmp_path):
    _variants_vault(tmp_path)
    _spec_vault(tmp_path)
    idx = scan_vault(tmp_path)
    rels = {p.rel_folder for p in fp.list_writable_folders(idx)}
    assert "科普模块/吸尘器/挑选攻略" in rels
    assert "产品模块/吸尘器/产品参数" in rels


def test_empty_folder_profile_is_unknown(tmp_path):
    idx = scan_vault(tmp_path)
    prof = fp.profile_folder(idx, "不存在/文件夹")
    assert prof.sample_count == 0
    assert prof.body_shape == "unknown"
    assert prof.frontmatter_keys == []
