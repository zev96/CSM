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
