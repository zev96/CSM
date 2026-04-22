from csm_gui.config import AppConfig
from csm_gui.pages.home_page import HomePage


def _seed_template(tmp_path):
    tpl = tmp_path / "t.json"
    tpl.write_text('{"id":"t","name":"t","slots":[]}', encoding="utf-8")
    return tpl


def test_home_page_emits_request_generate(qtbot, tmp_path):
    tpl = _seed_template(tmp_path)
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
    # Vault / provider are now injected from AppConfig, not form inputs.
    assert payload["vault_root"] == str(tmp_path)
    assert payload["provider"] == "anthropic"


def test_home_page_disables_generate_when_required_missing(qtbot):
    cfg = AppConfig()
    page = HomePage(config=cfg)
    qtbot.addWidget(page)
    page.single_panel.keyword_input.setText("x")
    assert not page.single_panel.generate_button.isEnabled()


def test_home_page_apply_config_reflects_new_values(qtbot, tmp_path):
    tpl_old = _seed_template(tmp_path)
    tpl_new = tmp_path / "new.json"
    tpl_new.write_text('{"id":"n","name":"n","slots":[]}', encoding="utf-8")
    cfg_old = AppConfig(
        vault_root=str(tmp_path),
        default_template=str(tpl_old),
        default_provider="mock",
    )
    page = HomePage(config=cfg_old)
    qtbot.addWidget(page)

    cfg_new = AppConfig(
        vault_root=str(tmp_path),
        default_template=str(tpl_new),
        default_provider="deepseek",
    )
    page.apply_config(cfg_new)
    p = page.single_panel.form.payload()
    assert p["template_path"] == str(tpl_new)
    assert p["vault_root"] == str(tmp_path)
    assert p["provider"] == "deepseek"


def test_home_page_apply_config_clears_when_config_cleared(qtbot, tmp_path):
    tpl = _seed_template(tmp_path)
    cfg_full = AppConfig(vault_root=str(tmp_path), default_template=str(tpl))
    page = HomePage(config=cfg_full)
    qtbot.addWidget(page)

    # Settings cleared the fields
    page.apply_config(AppConfig())
    p = page.single_panel.form.payload()
    assert p["template_path"] == ""
    assert p["vault_root"] == ""


def test_home_page_emits_request_batch(qtbot, tmp_path):
    tpl = _seed_template(tmp_path)
    cfg = AppConfig(
        default_template=str(tpl),
        vault_root=str(tmp_path),
        default_provider="mock",
    )
    home = HomePage(cfg)
    qtbot.addWidget(home)
    home.batch_panel.keyword_edit.setPlainText("kw1")
    qtbot.wait(300)
    with qtbot.waitSignal(home.request_batch, timeout=500) as sig:
        home.batch_panel.start_button.click()
    assert sig.args[0]["keywords"] == ["kw1"]


def test_home_page_has_two_tabs(qtbot):
    home = HomePage(AppConfig(default_provider="mock"))
    qtbot.addWidget(home)
    assert home.stack.count() == 2
