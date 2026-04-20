from csm_gui.widgets.generation_form import GenerationForm
from csm_gui.config import AppConfig


def test_generation_form_reads_config_defaults(qtbot, tmp_path):
    cfg = AppConfig(default_template=str(tmp_path / "t.json"),
                    vault_root=str(tmp_path), default_provider="deepseek")
    form = GenerationForm(cfg)
    qtbot.addWidget(form)
    assert form.template_input.text() == str(tmp_path / "t.json")
    assert form.vault_input.text() == str(tmp_path)
    assert form.provider_combo.currentText() == "deepseek"


def test_generation_form_apply_config_updates_fields(qtbot, tmp_path):
    form = GenerationForm(AppConfig())
    qtbot.addWidget(form)
    new = AppConfig(default_template=str(tmp_path / "x.json"),
                    vault_root=str(tmp_path), default_provider="anthropic")
    form.apply_config(new)
    assert form.template_input.text() == str(tmp_path / "x.json")
    assert form.provider_combo.currentText() == "anthropic"


def test_generation_form_is_valid(qtbot, tmp_path):
    cfg = AppConfig(default_template=str(tmp_path / "t.json"),
                    vault_root=str(tmp_path), default_provider="mock")
    form = GenerationForm(cfg)
    qtbot.addWidget(form)
    assert form.is_valid() is True
    form.vault_input.setText("")
    assert form.is_valid() is False


def test_generation_form_payload(qtbot, tmp_path):
    cfg = AppConfig(default_template="t.json", vault_root=str(tmp_path),
                    default_provider="mock")
    form = GenerationForm(cfg)
    qtbot.addWidget(form)
    p = form.payload()
    assert p == {
        "template_path": "t.json",
        "vault_root": str(tmp_path),
        "provider": "mock",
    }
