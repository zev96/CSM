import pytest
from pathlib import Path
from csm_core.vault.brand_registry import build_brand_registry, BrandRegistry


def test_registry_lists_brands(mini_vault_path: Path):
    registry = build_brand_registry(mini_vault_path)
    assert isinstance(registry, BrandRegistry)
    assert set(registry.brands()) == {"CEWEY", "戴森", "小狗"}


def test_registry_models_for_brand(mini_vault_path: Path):
    registry = build_brand_registry(mini_vault_path)
    assert registry.models("戴森") == ["戴森V15"]
    assert registry.models("CEWEY") == ["CEWEYDS18"]


def test_registry_all_models(mini_vault_path: Path):
    registry = build_brand_registry(mini_vault_path)
    models = set(registry.all_models())
    assert models == {"CEWEYDS18", "戴森V15", "小狗T12"}


def test_registry_brand_of(mini_vault_path: Path):
    registry = build_brand_registry(mini_vault_path)
    assert registry.brand_of("戴森V15") == "戴森"
    assert registry.brand_of("不存在") is None


def test_registry_competitors_of(mini_vault_path: Path):
    registry = build_brand_registry(mini_vault_path)
    competitors = registry.competitors_of("CEWEY")
    assert set(competitors) == {"戴森V15", "小狗T12"}


def test_registry_folds_brand_alias_to_canonical(tmp_path: Path):
    # 笔记写的是别名「米家」，registry 应归一到 canonical「小米」
    d = tmp_path / "营销资料库/产品模块/吸尘器/产品参数"
    d.mkdir(parents=True)
    (d / "米家3C-产品参数.md").write_text(
        "---\n产品: 吸尘器\n品牌: 米家\n型号: 米家3C\n素材类型: 产品参数\n核心关键词: [x]\n---\n体\n",
        encoding="utf-8",
    )
    reg = build_brand_registry(tmp_path)
    assert reg.brands() == ["小米"]
    assert reg.brand_of("米家3C") == "小米"


def test_registry_falls_back_to_filename_when_no_frontmatter(tmp_path: Path):
    # 真实库形态：产品参数笔记无 品牌/型号 frontmatter，仅靠文件名
    d = tmp_path / "营销资料库/产品模块/吸尘器/产品参数"
    d.mkdir(parents=True)
    for stem in ("CEWEYDS18-产品参数", "戴森V12-产品参数", "米家3C-产品参数"):
        (d / f"{stem}.md").write_text(
            "---\n产品: 吸尘器\n素材类型: 产品参数\n核心关键词: [x]\n---\n体\n",
            encoding="utf-8",
        )
    reg = build_brand_registry(tmp_path)
    assert set(reg.brands()) == {"CEWEY", "戴森", "小米"}
    assert set(reg.all_models()) == {"CEWEYDS18", "戴森V12", "米家3C"}
    assert reg.brand_of("米家3C") == "小米"


_REAL_VAULT = Path(r"D:\家电组共享\DATA\营销资料库")


@pytest.mark.integration
@pytest.mark.skipif(not _REAL_VAULT.exists(), reason="真实 vault 不在本机")
def test_real_vault_registry_has_33_models():
    reg = build_brand_registry(_REAL_VAULT)
    assert len(reg.all_models()) == 33
    assert "CEWEY" in reg.brands()
    assert "小米" in reg.brands()  # 米家* 应归一到 小米，不出现「米家」品牌
    assert "米家" not in reg.brands()
    assert {"米家3C", "米家2显尘版", "米家3基站版"}.issubset(set(reg.models("小米")))
