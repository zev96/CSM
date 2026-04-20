from csm_gui.config import AppConfig
from csm_gui.pages.settings_page import SettingsPage


def test_settings_page_reads_config(qtbot):
    cfg = AppConfig(
        vault_root="D:/vault",
        default_provider="anthropic",
        api_keys={"anthropic": "sk-123"},
        last_seed=7,
    )
    page = SettingsPage(config=cfg, on_save=lambda c: None)
    qtbot.addWidget(page)
    assert page.provider_card.currentText() == "anthropic"
    assert page.seed_card.value() == 7
    assert page.anthropic_key_input.text() == "sk-123"
    assert page.vault_input.text() == "D:/vault"


def test_settings_page_writes_to_config_on_save(qtbot):
    saved = []
    cfg = AppConfig()
    page = SettingsPage(config=cfg, on_save=lambda c: saved.append(c))
    qtbot.addWidget(page)
    page.vault_input.setText("D:/new-vault")
    page.seed_card.setValue(42)
    page.save_button.click()
    assert len(saved) == 1
    assert saved[0].vault_root == "D:/new-vault"
    assert saved[0].last_seed == 42
