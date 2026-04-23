from pathlib import Path
from csm_gui.widgets.batch_panel import BatchPanel
from csm_gui.config import AppConfig


def test_batch_panel_keyword_count(qtbot):
    p = BatchPanel(AppConfig(default_provider="mock"))
    qtbot.addWidget(p)
    p.keyword_edit.setPlainText("a\nb\n\na\nc")
    qtbot.wait(300)
    assert p.unique_keywords() == ["a", "b", "c"]
    assert "3" in p.count_label.text()


def test_batch_panel_start_disabled_when_empty(qtbot, tmp_path):
    tpl = tmp_path / "t.json"
    tpl.write_text("{}", encoding="utf-8")
    cfg = AppConfig(default_template=str(tpl),
                    vault_root=str(tmp_path), default_provider="mock")
    p = BatchPanel(cfg)
    qtbot.addWidget(p)
    assert p.start_button.isEnabled() is False
    p.keyword_edit.setPlainText("a")
    qtbot.wait(300)
    assert p.start_button.isEnabled() is True
    p.keyword_edit.setPlainText("")
    qtbot.wait(300)
    assert p.start_button.isEnabled() is False


def test_batch_panel_import_txt_replaces(qtbot, tmp_path, monkeypatch):
    cfg = AppConfig(default_provider="mock")
    p = BatchPanel(cfg)
    qtbot.addWidget(p)
    p.keyword_edit.setPlainText("existing")

    f = tmp_path / "kw.txt"
    f.write_text("new1\nnew2\n", encoding="utf-8")
    monkeypatch.setattr(
        "csm_gui.widgets.batch_panel.QFileDialog.getOpenFileName",
        staticmethod(lambda *a, **kw: (str(f), "")),
    )
    p._on_import_clicked()
    assert p.keyword_edit.toPlainText().splitlines() == ["new1", "new2"]


def test_batch_panel_import_csv_first_column(qtbot, tmp_path, monkeypatch):
    cfg = AppConfig(default_provider="mock")
    p = BatchPanel(cfg)
    qtbot.addWidget(p)
    f = tmp_path / "kw.csv"
    f.write_text("kw1,extra\nkw2,ignore\n", encoding="utf-8")
    monkeypatch.setattr(
        "csm_gui.widgets.batch_panel.QFileDialog.getOpenFileName",
        staticmethod(lambda *a, **kw: (str(f), "")),
    )
    p._on_import_clicked()
    assert p.keyword_edit.toPlainText().splitlines() == ["kw1", "kw2"]


def test_batch_panel_emits_request_batch(qtbot, tmp_path):
    tpl = tmp_path / "t.json"
    tpl.write_text("{}", encoding="utf-8")
    cfg = AppConfig(default_template=str(tpl),
                    vault_root=str(tmp_path), default_provider="mock")
    p = BatchPanel(cfg)
    qtbot.addWidget(p)
    p.keyword_edit.setPlainText("kw1\nkw2")
    qtbot.wait(300)
    with qtbot.waitSignal(p.request_batch, timeout=500) as sig:
        p.start_button.click()
    payload = sig.args[0]
    assert payload["keywords"] == ["kw1", "kw2"]
    assert payload["template_path"] == str(tpl)
    assert payload["provider"] == "mock"
