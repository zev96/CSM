from csm_gui.main_window import MainWindow


def test_main_window_has_three_nav_items(qtbot, qapp, tmp_path):
    win = MainWindow(config_dir=tmp_path)
    qtbot.addWidget(win)
    # qfluentwidgets 1.11.x exposes nav items via navigationInterface.panel.items
    items = win.navigationInterface.panel.items
    assert len(items) >= 3
