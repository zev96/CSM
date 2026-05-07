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


def test_settings_page_provider_roundtrip(qtbot):
    saved = []
    cfg = AppConfig()
    page = SettingsPage(config=cfg, on_save=lambda c: saved.append(c))
    qtbot.addWidget(page)
    idx = page.provider_card.findText("deepseek")
    assert idx >= 0
    page.provider_card.setCurrentIndex(idx)
    page.save_button.click()
    assert saved[0].default_provider == "deepseek"
    assert saved[0].api_keys == {}  # empty inputs were filtered out


def test_settings_page_has_close_action_selector(qtbot):
    from csm_gui.config import AppConfig
    from csm_gui.pages.settings_page import SettingsPage
    cfg = AppConfig()
    saved = []
    page = SettingsPage(config=cfg, on_save=lambda c: saved.append(c))
    qtbot.addWidget(page)
    # 必须存在 close_action_combo 控件
    assert hasattr(page, "close_action_combo")


def test_settings_page_close_action_default_minimize(qtbot):
    from csm_gui.config import AppConfig
    from csm_gui.pages.settings_page import SettingsPage
    cfg = AppConfig(close_action="minimize_to_tray")
    page = SettingsPage(config=cfg, on_save=lambda c: None)
    qtbot.addWidget(page)
    # 当前选中应为 "最小化到托盘"
    assert page.close_action_combo.currentData() == "minimize_to_tray"


def test_settings_page_close_action_save_quit(qtbot):
    from csm_gui.config import AppConfig
    from csm_gui.pages.settings_page import SettingsPage
    cfg = AppConfig()
    saved: list[AppConfig] = []
    page = SettingsPage(config=cfg, on_save=lambda c: saved.append(c))
    qtbot.addWidget(page)
    # 找到下拉项的 index
    idx = page.close_action_combo.findData("quit")
    assert idx >= 0
    page.close_action_combo.setCurrentIndex(idx)
    # _save is the actual save method name (not _on_save which is the callback)
    page._save()
    assert saved
    assert saved[-1].close_action == "quit"


def test_settings_page_has_dedup_section(qtbot):
    from csm_gui.config import AppConfig
    from csm_gui.pages.settings_page import SettingsPage
    cfg = AppConfig()
    page = SettingsPage(config=cfg, on_save=lambda c: None)
    qtbot.addWidget(page)
    assert hasattr(page, "dedup_enabled_switch")
    assert hasattr(page, "dedup_history_dir_edit")
    assert hasattr(page, "dedup_rebuild_history_button")
    assert hasattr(page, "dedup_rebuild_vault_button")
    assert hasattr(page, "dedup_threshold_green_spin")
    assert hasattr(page, "dedup_threshold_yellow_spin")


def test_settings_page_dedup_save_persists_fields(qtbot, tmp_path):
    from csm_gui.config import AppConfig
    from csm_gui.pages.settings_page import SettingsPage
    cfg = AppConfig()
    saved: list[AppConfig] = []
    page = SettingsPage(config=cfg, on_save=lambda c: saved.append(c))
    qtbot.addWidget(page)
    page.dedup_enabled_switch.setChecked(True)
    page.dedup_history_dir_edit.setText(str(tmp_path))
    page.dedup_threshold_green_spin.setValue(20)
    page.dedup_threshold_yellow_spin.setValue(40)
    page._save()
    assert saved
    assert saved[-1].dedup_enabled is True
    assert saved[-1].dedup_history_dir == str(tmp_path)
    assert saved[-1].dedup_threshold_green == 20
    assert saved[-1].dedup_threshold_yellow == 40


def test_settings_page_dedup_rebuild_history_emits_signal(qtbot, tmp_path):
    from csm_gui.config import AppConfig
    from csm_gui.pages.settings_page import SettingsPage
    cfg = AppConfig(dedup_history_dir=str(tmp_path))
    page = SettingsPage(config=cfg, on_save=lambda c: None)
    qtbot.addWidget(page)
    with qtbot.waitSignal(page.dedup_rebuild_requested, timeout=1000) as blocker:
        page.dedup_rebuild_history_button.click()
    assert blocker.args[0] == "history"
