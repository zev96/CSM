from csm_gui.main_window import MainWindow


def test_main_window_has_three_nav_items(qtbot, tmp_path):
    win = MainWindow(config_dir=tmp_path)
    qtbot.addWidget(win)

    assert win.stackedWidget.count() == 3
    names = {win.stackedWidget.widget(i).objectName() for i in range(win.stackedWidget.count())}
    assert names == {"HomePage", "ArticlePage", "SettingsPage"}


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
    from csm_core.assembler.plan import AssemblyPlan, SlotAssignment, PickedVariant
    from csm_core.template.loader import load_template
    from csm_gui.config import AppConfig, save_config

    template_path = Path(__file__).parent.parent.parent / "templates" / "daogou-changjing-renqun.json"
    cfg = AppConfig(out_dir=str(tmp_path), default_template=str(template_path))
    save_config(cfg, tmp_path / "settings.json")
    win = MainWindow(config_dir=tmp_path)
    qtbot.addWidget(win)

    plan = AssemblyPlan(
        keyword="测试关键词", template_id="t", seed=0,
        slots=[SlotAssignment(slot_id="s", picks=[
            PickedVariant(note_id="n", variant_index=0, text="hello"),
        ])],
    )
    win.article._template = load_template(template_path)
    win.article.current_result = GenerateResult(
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
        keyword="k", template_id="t", seed=0, slots=[],
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
    plan = AssemblyPlan(keyword="k", template_id="t", seed=0, slots=[])
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
