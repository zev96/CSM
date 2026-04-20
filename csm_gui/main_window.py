"""FluentWindow shell with three navigation items."""
from __future__ import annotations
from pathlib import Path
from qfluentwidgets import FluentWindow, FluentIcon, NavigationItemPosition
from .pages.home_page import HomePage
from .pages.article_page import ArticlePage
from .pages.settings_page import SettingsPage


class MainWindow(FluentWindow):
    def __init__(self, config_dir: Path):
        super().__init__()
        self.config_dir = Path(config_dir)
        self.resize(1280, 820)
        self.setWindowTitle("CSM — Content SEO Maker")

        self.home = HomePage(self)
        self.article = ArticlePage(self)
        self.settings = SettingsPage(self)

        self.addSubInterface(self.home, FluentIcon.HOME, "首页")
        self.addSubInterface(self.article, FluentIcon.DOCUMENT, "文章")
        self.addSubInterface(
            self.settings, FluentIcon.SETTING, "设置",
            position=NavigationItemPosition.BOTTOM,
        )
