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
    assert cfg.last_seed == 0
    assert cfg.default_model == {}


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


def test_save_config_creates_parent_dirs(tmp_path: Path):
    target = tmp_path / "nested" / "deep" / "settings.json"
    save_config(AppConfig(), target)
    assert target.exists()


def test_load_type_error_returns_defaults(tmp_path: Path):
    p = tmp_path / "bad.json"
    p.write_text('{"last_seed": "not-an-int"}', encoding="utf-8")
    cfg = load_config(p)
    assert cfg == AppConfig()


def test_appconfig_default_close_action():
    from csm_gui.config import AppConfig
    cfg = AppConfig()
    assert cfg.close_action == "minimize_to_tray"
    assert cfg.tray_first_minimize_shown is False


def test_appconfig_close_action_validates_literal():
    from csm_gui.config import AppConfig
    from pydantic import ValidationError
    import pytest
    with pytest.raises(ValidationError):
        AppConfig(close_action="invalid_value")


def test_appconfig_loads_old_settings_without_close_action(tmp_path):
    """老 settings.json 没有 close_action 时回退到默认值（向后兼容）。"""
    from csm_gui.config import AppConfig, load_config
    p = tmp_path / "settings.json"
    p.write_text('{"vault_root":"/tmp"}', encoding="utf-8")
    cfg = load_config(p)
    assert cfg.close_action == "minimize_to_tray"
    assert cfg.tray_first_minimize_shown is False
