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


def test_export_without_result_is_noop(qtbot, tmp_path):
    from csm_gui.config import AppConfig, save_config
    cfg = AppConfig(out_dir=str(tmp_path))
    save_config(cfg, tmp_path / "settings.json")
    win = MainWindow(config_dir=tmp_path)
    qtbot.addWidget(win)
    # Nothing to export — should not raise, should not write files.
    win._on_export()
    assert list(tmp_path.iterdir()) == [tmp_path / "settings.json"]
