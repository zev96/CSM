from csm_core.config import AppConfig, BrandMemoryConfig, load_config, save_config


def test_brand_memory_defaults_off():
    cfg = AppConfig()
    assert cfg.brand_memory.inject is False
    assert cfg.brand_memory.factcheck is False
    assert cfg.brand_memory.own_brands == ["CEWEY"]
    assert cfg.brand_memory.inject_variant_cap == 3
    assert cfg.brand_memory.inject_endorsement_cap == 5


def test_brand_memory_roundtrip(tmp_path):
    p = tmp_path / "settings.json"
    save_config(AppConfig(brand_memory=BrandMemoryConfig(
        inject=True, factcheck=True, own_brands=["CEWEY", "希喂"])), p)
    loaded = load_config(p)
    assert loaded.brand_memory.inject is True
    assert loaded.brand_memory.factcheck is True
    assert loaded.brand_memory.own_brands == ["CEWEY", "希喂"]


def test_legacy_settings_without_brand_memory_defaults(tmp_path):
    p = tmp_path / "s.json"
    p.write_text('{"vault_root": "x"}', encoding="utf-8")
    assert load_config(p).brand_memory.inject is False
