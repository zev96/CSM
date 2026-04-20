from csm_gui.config import AppConfig
from csm_gui.pages.home_page import HomePage


def test_home_page_emits_request_generate(qtbot, tmp_path):
    tpl = tmp_path / "t.json"
    tpl.write_text("{}", encoding="utf-8")
    cfg = AppConfig(
        vault_root=str(tmp_path),
        out_dir=str(tmp_path),
        default_template=str(tpl),
        default_provider="anthropic",
    )
    page = HomePage(config=cfg)
    qtbot.addWidget(page)
    page.single_panel.keyword_input.setText("宠物吸尘器推荐")
    with qtbot.waitSignal(page.request_generate, timeout=1000) as sig:
        page.single_panel.generate_button.click()
    payload = sig.args[0]
    assert payload["keyword"] == "宠物吸尘器推荐"
    assert payload["template_path"] == str(tpl)
    assert payload["vault_root"] == str(tmp_path)
    assert payload["provider"] == "anthropic"


def test_home_page_disables_generate_when_required_missing(qtbot):
    cfg = AppConfig()
    page = HomePage(config=cfg)
    qtbot.addWidget(page)
    page.single_panel.keyword_input.setText("x")
    assert not page.single_panel.generate_button.isEnabled()


def test_home_page_apply_config_reflects_new_values(qtbot, tmp_path):
    tpl_old = tmp_path / "old.json"
    tpl_old.write_text("{}", encoding="utf-8")
    tpl_new = tmp_path / "new.json"
    tpl_new.write_text("{}", encoding="utf-8")
    cfg_old = AppConfig(
        vault_root=str(tmp_path / "old"),
        default_template=str(tpl_old),
        default_provider="mock",
    )
    page = HomePage(config=cfg_old)
    qtbot.addWidget(page)

    cfg_new = AppConfig(
        vault_root=str(tmp_path / "new"),
        default_template=str(tpl_new),
        default_provider="deepseek",
    )
    page.apply_config(cfg_new)
    assert page.single_panel.form.template_input.text() == str(tpl_new)
    assert page.single_panel.form.vault_input.text() == str(tmp_path / "new")
    assert page.single_panel.form.provider_combo.currentText() == "deepseek"


def test_home_page_apply_config_clears_when_config_cleared(qtbot, tmp_path):
    tpl = tmp_path / "t.json"
    tpl.write_text("{}", encoding="utf-8")
    cfg_full = AppConfig(vault_root=str(tmp_path), default_template=str(tpl))
    page = HomePage(config=cfg_full)
    qtbot.addWidget(page)

    # Settings cleared the fields
    page.apply_config(AppConfig())
    assert page.single_panel.form.template_input.text() == ""
    assert page.single_panel.form.vault_input.text() == ""


def test_home_page_emits_request_batch(qtbot, tmp_path):
    from csm_gui.pages.home_page import HomePage
    from csm_gui.config import AppConfig
    cfg = AppConfig(default_template=str(tmp_path / "t.json"),
                    vault_root=str(tmp_path), default_provider="mock")
    home = HomePage(cfg)
    qtbot.addWidget(home)
    home.batch_panel.keyword_edit.setPlainText("kw1")
    qtbot.wait(300)
    with qtbot.waitSignal(home.request_batch, timeout=500) as sig:
        home.batch_panel.start_button.click()
    assert sig.args[0]["keywords"] == ["kw1"]


def test_home_page_has_two_tabs(qtbot):
    from csm_gui.pages.home_page import HomePage
    from csm_gui.config import AppConfig
    home = HomePage(AppConfig(default_provider="mock"))
    qtbot.addWidget(home)
    assert home.stack.count() == 2
