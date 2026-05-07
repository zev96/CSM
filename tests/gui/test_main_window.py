from csm_gui.main_window import MainWindow
from PyQt6.QtGui import QCloseEvent


def _make_close_event() -> QCloseEvent:
    return QCloseEvent()


def test_close_event_minimize_to_tray_hides_window(qtbot, tmp_path):
    """close_action='minimize_to_tray' should hide() the window instead of closing."""
    win = MainWindow(config_dir=tmp_path)
    qtbot.addWidget(win)
    win.config.close_action = "minimize_to_tray"
    win.show()
    qtbot.waitExposed(win)
    assert win.isVisible()

    ev = _make_close_event()
    win.closeEvent(ev)
    qtbot.wait(100)
    assert not win.isVisible()
    assert not ev.isAccepted()


def test_close_event_quit_mode_accepts(qtbot, tmp_path):
    win = MainWindow(config_dir=tmp_path)
    qtbot.addWidget(win)
    win.config.close_action = "quit"
    ev = _make_close_event()
    win.closeEvent(ev)
    assert ev.isAccepted()


def test_show_main_window_brings_to_front(qtbot, tmp_path):
    win = MainWindow(config_dir=tmp_path)
    qtbot.addWidget(win)
    win.hide()
    win._show_main_window()
    qtbot.wait(50)
    assert win.isVisible()


def test_tray_new_article_focuses_keyword_input(qtbot, tmp_path):
    """When tray menu emits new_article_requested, MainWindow switches to home."""
    win = MainWindow(config_dir=tmp_path)
    qtbot.addWidget(win)
    win.show()
    qtbot.waitExposed(win)

    win._on_tray_new_article()
    qtbot.wait(50)
    assert win.stackedWidget.currentWidget() is win.home


def test_main_window_has_nav_items(qtbot, tmp_path):
    win = MainWindow(config_dir=tmp_path)
    qtbot.addWidget(win)

    names = {win.stackedWidget.widget(i).objectName() for i in range(win.stackedWidget.count())}
    assert {"HomePage", "ArticlePage", "SettingsPage", "BatchResultPage", "TemplateManagerPage"}.issubset(names)


def test_main_window_loads_config(qtbot, tmp_path):
    from csm_gui.config import AppConfig, save_config
    cfg = AppConfig(default_provider="deepseek", last_seed=99)
    save_config(cfg, tmp_path / "settings.json")
    win = MainWindow(config_dir=tmp_path)
    qtbot.addWidget(win)
    assert win.config.default_provider == "deepseek"
    assert win.config.last_seed == 99


def test_export_action_writes_files(qtbot, tmp_path):
    from pathlib import Path
    from csm_core.pipeline import GenerateResult
    from csm_core.assembler.plan import AssemblyPlan, BlockResult, PickedVariant
    from csm_core.template.loader import load_template
    from csm_gui.config import AppConfig, save_config

    template_path = Path(__file__).parent.parent.parent / "templates" / "daogou-changjing-renqun.json"
    cfg = AppConfig(out_dir=str(tmp_path), default_template=str(template_path))
    save_config(cfg, tmp_path / "settings.json")
    win = MainWindow(config_dir=tmp_path)
    qtbot.addWidget(win)

    plan = AssemblyPlan(
        keyword="测试关键词", template_id="t", seed=0,
        results=[BlockResult(block_id="s", kind="paragraph", picks=[
            PickedVariant(note_id="n", variant_index=0, text="hello"),
        ])],
    )
    win.article_controller._current_template = load_template(template_path)
    win.article_controller._current_result = GenerateResult(
        markdown_path="", assembly_json_path="",
        plan=plan, final_text="# exported",
    )
    win._on_export()
    written = list(tmp_path.iterdir())
    assert any(p.suffix == ".md" for p in written)
    assert any(p.name.endswith(".assembly.json") for p in written)


def _capture_infobar(monkeypatch, method: str):
    shown = []

    def fake(*args, **kwargs):
        shown.append((args, kwargs))
        from types import SimpleNamespace
        return SimpleNamespace(show=lambda: None, addWidget=lambda w: None)

    monkeypatch.setattr(f"qfluentwidgets.InfoBar.{method}", staticmethod(fake))
    return shown


def test_generate_failed_shows_error_infobar(qtbot, tmp_path, monkeypatch):
    from csm_gui.config import AppConfig, save_config
    cfg = AppConfig(out_dir=str(tmp_path))
    save_config(cfg, tmp_path / "settings.json")
    win = MainWindow(config_dir=tmp_path)
    qtbot.addWidget(win)
    shown = _capture_infobar(monkeypatch, "error")
    win._on_generate_failed("RuntimeError: bad\ntraceback line")
    assert len(shown) == 1
    args, kwargs = shown[0]
    content = kwargs.get("content") or (args[1] if len(args) > 1 else "")
    assert "RuntimeError" in content
    assert "traceback" not in content  # only first line surfaced


def test_empty_pool_routes_to_warning(qtbot, tmp_path, monkeypatch):
    from csm_gui.config import AppConfig, save_config
    cfg = AppConfig(out_dir=str(tmp_path))
    save_config(cfg, tmp_path / "settings.json")
    win = MainWindow(config_dir=tmp_path)
    qtbot.addWidget(win)
    warnings = _capture_infobar(monkeypatch, "warning")
    errors = _capture_infobar(monkeypatch, "error")
    win._on_generate_failed("EmptyPoolError: slot 'x': empty pool")
    assert len(warnings) == 1
    assert len(errors) == 0


def test_show_plan_warnings_emits_when_present(qtbot, tmp_path, monkeypatch):
    from csm_core.assembler.plan import AssemblyPlan
    from csm_gui.config import AppConfig, save_config
    cfg = AppConfig(out_dir=str(tmp_path))
    save_config(cfg, tmp_path / "settings.json")
    win = MainWindow(config_dir=tmp_path)
    qtbot.addWidget(win)
    shown = []

    def fake_warning(*args, **kwargs):
        shown.append((args, kwargs))
        from types import SimpleNamespace
        return SimpleNamespace(show=lambda: None)

    monkeypatch.setattr("qfluentwidgets.InfoBar.warning", staticmethod(fake_warning))
    plan = AssemblyPlan(
        keyword="k", template_id="t", seed=0,
        warnings=["缺数据: slot_a", "缺数据: slot_b"],
    )
    win._show_plan_warnings_list(plan.warnings)
    assert len(shown) == 1
    assert "缺数据" in shown[0][1]["content"]


def test_show_plan_warnings_silent_when_empty(qtbot, tmp_path, monkeypatch):
    from csm_core.assembler.plan import AssemblyPlan
    from csm_gui.config import AppConfig, save_config
    cfg = AppConfig(out_dir=str(tmp_path))
    save_config(cfg, tmp_path / "settings.json")
    win = MainWindow(config_dir=tmp_path)
    qtbot.addWidget(win)
    shown = []
    monkeypatch.setattr(
        "qfluentwidgets.InfoBar.warning",
        staticmethod(lambda *a, **kw: shown.append(1)),
    )
    plan = AssemblyPlan(keyword="k", template_id="t", seed=0)
    win._show_plan_warnings_list([])
    assert shown == []


def test_export_without_result_is_noop(qtbot, tmp_path, monkeypatch):
    from csm_gui.config import AppConfig, save_config
    cfg = AppConfig(out_dir=str(tmp_path))
    save_config(cfg, tmp_path / "settings.json")
    win = MainWindow(config_dir=tmp_path)
    qtbot.addWidget(win)
    errors = _capture_infobar(monkeypatch, "error")
    successes = _capture_infobar(monkeypatch, "success")
    # Nothing to export — should not raise, should not write files, no toasts.
    win._on_export()
    assert list(tmp_path.iterdir()) == [tmp_path / "settings.json"]
    assert errors == []
    assert successes == []


def test_main_window_has_batch_controller(qtbot, tmp_path):
    from csm_gui.config import AppConfig, save_config
    save_config(AppConfig(out_dir=str(tmp_path)), tmp_path / "settings.json")
    win = MainWindow(config_dir=tmp_path)
    qtbot.addWidget(win)
    assert hasattr(win, "batch_controller")
    assert hasattr(win, "batch_result_page")


def test_busy_during_batch_disables_single_generate(qtbot, tmp_path):
    from csm_gui.config import AppConfig, save_config
    save_config(AppConfig(out_dir=str(tmp_path)), tmp_path / "settings.json")
    win = MainWindow(config_dir=tmp_path)
    qtbot.addWidget(win)
    win.batch_controller.busy_changed.emit(True)
    assert win.home.single_panel.generate_button.isEnabled() is False
    assert win.home.batch_panel.start_button.isEnabled() is False
    win.batch_controller.busy_changed.emit(False)


def test_batch_completed_shows_success_infobar(qtbot, tmp_path, monkeypatch):
    from csm_gui.config import AppConfig, save_config
    from csm_core.batch.report import BatchReport, BatchItem
    save_config(AppConfig(out_dir=str(tmp_path)), tmp_path / "settings.json")
    win = MainWindow(config_dir=tmp_path)
    qtbot.addWidget(win)
    shown = _capture_infobar(monkeypatch, "success")
    report = BatchReport(
        batch_id="b", batch_dir=str(tmp_path), started_at="", finished_at="",
        template_path="t", vault_root="v", seed=0, total=1,
        items=[BatchItem(index=1, keyword="k", status="success")],
    )
    win.batch_controller.batch_completed.emit(report)
    assert len(shown) == 1


def test_batch_completed_with_failures_shows_warning(qtbot, tmp_path, monkeypatch):
    from csm_gui.config import AppConfig, save_config
    from csm_core.batch.report import BatchReport, BatchItem
    save_config(AppConfig(out_dir=str(tmp_path)), tmp_path / "settings.json")
    win = MainWindow(config_dir=tmp_path)
    qtbot.addWidget(win)
    shown = _capture_infobar(monkeypatch, "warning")
    report = BatchReport(
        batch_id="b", batch_dir=str(tmp_path), started_at="", finished_at="",
        template_path="t", vault_root="v", seed=0, total=2,
        items=[
            BatchItem(index=1, keyword="k1", status="success"),
            BatchItem(index=2, keyword="k2", status="failed", error_type="X", error_message="y"),
        ],
    )
    win.batch_controller.batch_completed.emit(report)
    assert len(shown) == 1


def test_app_does_not_quit_when_hidden_to_tray(qtbot, tmp_path, qapp):
    """Once setQuitOnLastWindowClosed(False) is set, hiding the window must not exit the app."""
    from csm_gui.main_window import MainWindow
    qapp.setQuitOnLastWindowClosed(False)
    win = MainWindow(config_dir=tmp_path)
    qtbot.addWidget(win)
    win.show()
    qtbot.waitExposed(win)
    win.hide()
    qtbot.wait(100)
    # If qapp had quit, this assert would never run — the test runner would die.
    assert not win.isVisible()
    qapp.setQuitOnLastWindowClosed(True)  # restore for next test


def test_main_window_has_dedup_analyzer(qtbot, tmp_path):
    from csm_gui.main_window import MainWindow
    from csm_core.dedup.analyzer import DedupAnalyzer
    win = MainWindow(config_dir=tmp_path)
    qtbot.addWidget(win)
    assert isinstance(win.dedup_analyzer, DedupAnalyzer)


def test_main_window_polished_triggers_dedup_when_enabled(qtbot, tmp_path, monkeypatch):
    """When dedup_enabled=True, _on_polished should kick off two analyses."""
    from csm_gui.main_window import MainWindow
    win = MainWindow(config_dir=tmp_path)
    qtbot.addWidget(win)
    win.config.dedup_enabled = True

    triggered = []
    monkeypatch.setattr(win, "_kick_dedup_analysis",
                        lambda text, kind: triggered.append((text[:5], kind)))

    win._on_polished("已经润色完成的文章内容文字" * 10)
    kinds = sorted([k for _, k in triggered])
    assert "history" in kinds
    assert "vault" in kinds


def test_main_window_polished_does_nothing_when_dedup_disabled(qtbot, tmp_path, monkeypatch):
    from csm_gui.main_window import MainWindow
    win = MainWindow(config_dir=tmp_path)
    qtbot.addWidget(win)
    win.config.dedup_enabled = False

    triggered = []
    monkeypatch.setattr(win, "_kick_dedup_analysis",
                        lambda text, kind: triggered.append(kind))

    win._on_polished("内容" * 100)
    assert triggered == []


def test_main_window_check_update_button_dispatches(qtbot, tmp_path, monkeypatch):
    """Settings page emits check_update_requested → MainWindow starts a worker."""
    from csm_gui.main_window import MainWindow
    win = MainWindow(config_dir=tmp_path)
    qtbot.addWidget(win)

    started = []
    monkeypatch.setattr(win, "_start_update_check_manual",
                        lambda: started.append(True))
    win.settings.check_update_requested.emit()
    assert started == [True]


def test_main_window_handles_update_check_no_update(qtbot, tmp_path):
    """When CheckResult has no update, no dialog should be shown."""
    from csm_gui.main_window import MainWindow
    from csm_core.updater_client.checker import CheckResult
    win = MainWindow(config_dir=tmp_path)
    qtbot.addWidget(win)
    # Should not crash; explicit no-update path
    win._on_update_check_done(CheckResult(False, None, None), is_manual=False)


def test_main_window_dispatch_update_check_skips_when_no_repo(qtbot, tmp_path):
    """If update_repo is empty, manual check shows a warning (no worker started)."""
    from csm_gui.main_window import MainWindow
    win = MainWindow(config_dir=tmp_path)
    qtbot.addWidget(win)
    win.config.update_repo = ""  # explicitly empty
    n_workers_before = len(win._update_workers)
    win._dispatch_update_check(is_manual=True)
    # No worker should be started
    assert len(win._update_workers) == n_workers_before
