from csm_gui.main_window import MainWindow


def test_main_window_has_three_nav_items(qtbot, tmp_path):
    win = MainWindow(config_dir=tmp_path)
    qtbot.addWidget(win)

    assert win.stackedWidget.count() == 3
    names = {win.stackedWidget.widget(i).objectName() for i in range(win.stackedWidget.count())}
    assert names == {"HomePage", "ArticlePage", "SettingsPage"}
