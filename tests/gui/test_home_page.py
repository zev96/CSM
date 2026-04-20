from csm_gui.config import AppConfig
from csm_gui.pages.home_page import HomePage


def test_home_page_emits_request_generate(qtbot, tmp_path):
    tpl = tmp_path / "t.json"
    tpl.write_text("{}", encoding="utf-8")
    cfg = AppConfig(
        vault_root=str(tmp_path),
        out_dir=str(tmp_path),
        default_template=str(tpl),
    )
    page = HomePage(config=cfg)
    qtbot.addWidget(page)
    page.keyword_input.setText("宠物吸尘器推荐")
    with qtbot.waitSignal(page.request_generate, timeout=1000) as sig:
        page.generate_button.click()
    payload = sig.args[0]
    assert payload["keyword"] == "宠物吸尘器推荐"
    assert payload["template_path"] == str(tpl)
    assert payload["vault_root"] == str(tmp_path)


def test_home_page_disables_generate_when_required_missing(qtbot):
    cfg = AppConfig()
    page = HomePage(config=cfg)
    qtbot.addWidget(page)
    page.keyword_input.setText("x")
    assert not page.generate_button.isEnabled()
