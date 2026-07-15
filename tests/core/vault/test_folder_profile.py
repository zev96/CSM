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


def _two_line_vault(root: Path) -> None:
    # 吸尘器线有笔记;空气净化器线是空骨架(真实 vault 2026-07 形态)
    _write(root, "引言模块/吸尘器/人设引入/引言-人设①.md",
           "---\n产品: 吸尘器\n素材类型: 人设引入\n核心关键词:\n  - 人设\n---\n\n① 大家好\n\n② 我是…\n")
    (root / "引言模块/空气净化器/人设引入").mkdir(parents=True, exist_ok=True)
    (root / "总结模块/空气净化器/对比总结").mkdir(parents=True, exist_ok=True)
    (root / ".obsidian/plugins").mkdir(parents=True, exist_ok=True)


def test_tree_includes_intermediate_and_empty_dirs(tmp_path):
    _two_line_vault(tmp_path)
    idx = scan_vault(tmp_path)
    rels = {p.rel_folder for p in fp.list_writable_folders(idx)}
    assert "引言模块" in rels                       # 中间层
    assert "引言模块/吸尘器" in rels
    assert "引言模块/空气净化器/人设引入" in rels    # 空文件夹
    assert not any(r.startswith(".obsidian") for r in rels)  # 隐藏目录整树排除


def test_empty_dir_borrows_sibling_line_template(tmp_path):
    _two_line_vault(tmp_path)
    idx = scan_vault(tmp_path)
    by_rel = {p.rel_folder: p for p in fp.list_writable_folders(idx)}
    prof = by_rel["引言模块/空气净化器/人设引入"]
    assert prof.template_from == "引言模块/吸尘器/人设引入"
    assert prof.sample_count == 0
    assert prof.body_shape == "variants"
    assert prof.frontmatter_keys[:3] == ["产品", "素材类型", "核心关键词"]
    assert prof.defaults["产品"] == "空气净化器"     # 产品默认值换成新产品线
    assert prof.defaults["素材类型"] == "人设引入"


def test_empty_dir_without_sibling_gets_generic_template(tmp_path):
    _two_line_vault(tmp_path)
    idx = scan_vault(tmp_path)
    by_rel = {p.rel_folder: p for p in fp.list_writable_folders(idx)}
    prof = by_rel["总结模块/空气净化器/对比总结"]     # 吸尘器线没有 对比总结
    assert prof.template_from is None
    assert prof.frontmatter_keys == ["产品", "素材类型", "核心关键词"]
    assert prof.body_shape == "variants"


def test_borrow_swap_guard_same_line_other_module(tmp_path):
    # 兄弟差异段不是产品线时(同线跨模块借),产品默认值不被错误替换
    _write(tmp_path, "科普模块/空气净化器/挑选攻略/科普①.md",
           "---\n产品: 空气净化器\n素材类型: 科普选购\n核心关键词:\n  - 选购\n---\n\n① 看CADR\n\n② 看CCM\n")
    (tmp_path / "引言模块/空气净化器/挑选攻略").mkdir(parents=True, exist_ok=True)
    idx = scan_vault(tmp_path)
    by_rel = {p.rel_folder: p for p in fp.list_writable_folders(idx)}
    prof = by_rel["引言模块/空气净化器/挑选攻略"]
    assert prof.template_from == "科普模块/空气净化器/挑选攻略"
    # 差异段是模块名(引言模块≠产品默认值)→ 不替换,保持 空气净化器
    assert prof.defaults["产品"] == "空气净化器"
