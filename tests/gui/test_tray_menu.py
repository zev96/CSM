"""TrayMenu: 6 actions, each emits its dedicated signal."""
from csm_gui.tray.menu import TrayMenu


def _action(menu, text):
    return next(a for a in menu.actions() if a.text() == text)


def test_tray_menu_has_six_actions(qtbot):
    menu = TrayMenu()
    qtbot.addWidget(menu)
    labels = [a.text() for a in menu.actions() if not a.isSeparator()]
    assert labels == ["显示主界面", "新建文章", "新建模板", "新建 Skill", "设置", "退出 CSM"]


def test_show_action_emits_signal(qtbot):
    menu = TrayMenu()
    qtbot.addWidget(menu)
    with qtbot.waitSignal(menu.show_requested, timeout=1000):
        _action(menu, "显示主界面").trigger()


def test_new_article_emits_signal(qtbot):
    menu = TrayMenu()
    qtbot.addWidget(menu)
    with qtbot.waitSignal(menu.new_article_requested, timeout=1000):
        _action(menu, "新建文章").trigger()


def test_new_template_emits_signal(qtbot):
    menu = TrayMenu()
    qtbot.addWidget(menu)
    with qtbot.waitSignal(menu.new_template_requested, timeout=1000):
        _action(menu, "新建模板").trigger()


def test_new_skill_emits_signal(qtbot):
    menu = TrayMenu()
    qtbot.addWidget(menu)
    with qtbot.waitSignal(menu.new_skill_requested, timeout=1000):
        _action(menu, "新建 Skill").trigger()


def test_settings_emits_signal(qtbot):
    menu = TrayMenu()
    qtbot.addWidget(menu)
    with qtbot.waitSignal(menu.settings_requested, timeout=1000):
        _action(menu, "设置").trigger()


def test_quit_emits_signal(qtbot):
    menu = TrayMenu()
    qtbot.addWidget(menu)
    with qtbot.waitSignal(menu.quit_requested, timeout=1000):
        _action(menu, "退出 CSM").trigger()
