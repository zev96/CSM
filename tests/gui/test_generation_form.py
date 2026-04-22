from csm_gui.widgets.generation_form import GenerationForm
from csm_gui.config import AppConfig


def _write_templates(tmp_path):
    """Seed a template directory so the combo has entries to pick from."""
    tpl = tmp_path / "t.json"
    tpl.write_text('{"id":"t","name":"t","slots":[]}', encoding="utf-8")
    return tpl


def test_generation_form_reads_config_defaults(qtbot, tmp_path):
    tpl = _write_templates(tmp_path)
    cfg = AppConfig(
        default_template=str(tpl),
        vault_root=str(tmp_path),
        default_provider="deepseek",
    )
    form = GenerationForm(cfg)
    qtbot.addWidget(form)
    # Vault / provider inputs were removed — payload pulls from config.
    assert form.payload()["vault_root"] == str(tmp_path)
    assert form.payload()["provider"] == "deepseek"
    assert form.payload()["template_path"] == str(tpl)


def test_generation_form_apply_config_updates_fields(qtbot, tmp_path):
    form = GenerationForm(AppConfig())
    qtbot.addWidget(form)
    tpl = _write_templates(tmp_path)
    new = AppConfig(
        default_template=str(tpl),
        vault_root=str(tmp_path),
        default_provider="anthropic",
    )
    form.apply_config(new)
    p = form.payload()
    assert p["template_path"] == str(tpl)
    assert p["vault_root"] == str(tmp_path)
    assert p["provider"] == "anthropic"


def test_generation_form_is_valid(qtbot, tmp_path):
    tpl = _write_templates(tmp_path)
    cfg = AppConfig(
        default_template=str(tpl),
        vault_root=str(tmp_path),
        default_provider="mock",
    )
    form = GenerationForm(cfg)
    qtbot.addWidget(form)
    assert form.is_valid() is True
    # Clearing vault (via settings) invalidates the form.
    form.apply_config(AppConfig(default_template=str(tpl), vault_root=""))
    assert form.is_valid() is False


def test_generation_form_payload(qtbot, tmp_path):
    tpl = _write_templates(tmp_path)
    cfg = AppConfig(
        default_template=str(tpl),
        vault_root=str(tmp_path),
        default_provider="mock",
    )
    form = GenerationForm(cfg)
    qtbot.addWidget(form)
    p = form.payload()
    assert p == {
        "template_path": str(tpl),
        "vault_root": str(tmp_path),
        "provider": "mock",
    }
