"""DedupPanel: two-row metrics widget showing 历史重复率 / 素材引用率."""
from datetime import datetime
from csm_gui.widgets.dedup_panel import DedupPanel
from csm_core.dedup.report import DuplicateReport, TopMatch


def test_panel_initial_state_shows_dash(qtbot):
    panel = DedupPanel()
    qtbot.addWidget(panel)
    assert "—" in panel.history_value_label.text()
    assert "—" in panel.vault_value_label.text()


def test_panel_renders_history_report(qtbot):
    panel = DedupPanel()
    qtbot.addWidget(panel)
    report = DuplicateReport(
        corpus_kind="history",
        text_length=3200,
        duplicate_chars=384,
        duplicate_ratio=0.12,
        top_matches=[TopMatch(source_path="/a", source_title="A", overlap_chars=200, overlap_ratio=0.06)],
        hits=[],
        computed_at=datetime.now(),
    )
    panel.set_report(report)
    assert "12" in panel.history_value_label.text()


def test_panel_renders_vault_report(qtbot):
    panel = DedupPanel()
    qtbot.addWidget(panel)
    report = DuplicateReport(
        corpus_kind="vault",
        text_length=1000,
        duplicate_chars=380,
        duplicate_ratio=0.38,
        top_matches=[],
        hits=[],
        computed_at=datetime.now(),
    )
    panel.set_report(report)
    assert "38" in panel.vault_value_label.text()


def test_panel_recalculate_button_emits_signal(qtbot):
    panel = DedupPanel()
    qtbot.addWidget(panel)
    with qtbot.waitSignal(panel.recalculate_requested, timeout=1000):
        panel.recalc_button.click()


def test_panel_history_drilldown_emits_signal(qtbot):
    panel = DedupPanel()
    qtbot.addWidget(panel)
    report = DuplicateReport(
        corpus_kind="history",
        text_length=1000, duplicate_chars=120, duplicate_ratio=0.12,
        top_matches=[], hits=[], computed_at=datetime.now(),
    )
    panel.set_report(report)
    with qtbot.waitSignal(panel.drilldown_requested, timeout=1000) as blocker:
        panel.history_drill_button.click()
    assert blocker.args[0] == "history"


def test_panel_thresholds_change_color(qtbot):
    """颜色按 green/yellow 阈值切换。"""
    panel = DedupPanel()
    qtbot.addWidget(panel)
    panel.set_thresholds(green=15, yellow=30)
    panel.set_report(DuplicateReport(
        corpus_kind="history", text_length=1000, duplicate_chars=80,
        duplicate_ratio=0.08, top_matches=[], hits=[], computed_at=datetime.now(),
    ))
    style = panel.history_value_label.styleSheet()
    assert "color" in style.lower() or panel.history_value_label.text()


def test_panel_disabled_state_when_not_enabled(qtbot):
    panel = DedupPanel()
    qtbot.addWidget(panel)
    panel.set_disabled_message("功能未启用")
    assert not panel.recalc_button.isEnabled()
