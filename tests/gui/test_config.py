from pathlib import Path
from csm_gui.config import AppConfig, load_config, save_config


def test_appconfig_defaults():
    cfg = AppConfig()
    assert cfg.vault_root is None
    assert cfg.out_dir is None
    assert cfg.default_provider == "mock"
    assert cfg.api_keys == {}
    assert cfg.default_template is None
    assert cfg.skill_dir is None


def test_save_and_load_roundtrip(tmp_path: Path):
    cfg = AppConfig(
        vault_root=str(tmp_path / "vault"),
        out_dir=str(tmp_path / "out"),
        default_provider="anthropic",
        api_keys={"anthropic": "sk-test"},
        default_template=str(tmp_path / "t.json"),
        last_seed=42,
    )
    save_config(cfg, tmp_path / "settings.json")
    loaded = load_config(tmp_path / "settings.json")
    assert loaded == cfg


def test_load_nonexistent_returns_defaults(tmp_path: Path):
    cfg = load_config(tmp_path / "missing.json")
    assert cfg == AppConfig()


def test_load_malformed_returns_defaults(tmp_path: Path):
    p = tmp_path / "bad.json"
    p.write_text("{not json", encoding="utf-8")
    cfg = load_config(p)
    assert cfg == AppConfig()
