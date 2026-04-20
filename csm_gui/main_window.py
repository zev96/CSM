"""FluentWindow shell with three navigation items."""
from __future__ import annotations
from pathlib import Path
from qfluentwidgets import FluentWindow, FluentIcon, NavigationItemPosition
from .config import AppConfig, load_config, save_config as _save_config
from .pages.home_page import HomePage
from .pages.article_page import ArticlePage
from .pages.settings_page import SettingsPage
from .controllers.article_controller import ArticleController


class MainWindow(FluentWindow):
    """FluentWindow shell.

    Config mutation contract: pages that need current config should read
    ``self.window().config`` (or receive config via constructor and re-read
    on user action). There is currently NO ``configChanged`` signal — when
    SettingsPage fires ``_on_settings_save``, MainWindow rebinds
    ``self.config`` but does not notify other pages. Revisit if Task B3+
    requires live observation.
    """

    def __init__(self, config_dir: Path):
        super().__init__()
        self.config_dir = Path(config_dir)
        self._config_path = self.config_dir / "settings.json"
        self.config: AppConfig = load_config(self._config_path)
        self._current_result = None
        self.resize(1280, 820)
        self.setWindowTitle("CSM — Content SEO Maker")

        self.article_controller = ArticleController(self.config, parent=self)
        self.article_controller.generated.connect(self._on_generated)
        self.article_controller.generate_failed.connect(self._on_generate_failed)
        self.article_controller.plan_warnings.connect(self._show_plan_warnings_list)
        self.article_controller.reroll_completed.connect(self._on_reroll_completed)
        self.article_controller.polished.connect(self._on_polished)
        self.article_controller.polish_failed.connect(self._on_generate_failed)
        self.article_controller.exported.connect(self._on_exported)
        self.article_controller.export_failed.connect(self._on_export_failed)

        self.home = HomePage(config=self.config, parent=self)
        self.home.request_generate.connect(self._on_request_generate)
        self.article = ArticlePage(
            skill_dir=Path(self.config.skill_dir) if self.config.skill_dir else None,
            default_provider=self.config.default_provider,
            parent=self,
        )
        self.article.reroll_slot_requested.connect(self._on_reroll_slot)
        self.article.controls.polish_requested.connect(self._on_polish)
        self.article.controls.export_requested.connect(self._on_export)
        self.settings = SettingsPage(config=self.config, on_save=self._on_settings_save)

        self.addSubInterface(self.home, FluentIcon.HOME, "首页")
        self.addSubInterface(self.article, FluentIcon.DOCUMENT, "文章")
        self.addSubInterface(
            self.settings, FluentIcon.SETTING, "设置",
            position=NavigationItemPosition.BOTTOM,
        )

    def save_config(self) -> None:
        _save_config(self.config, self._config_path)

    def _on_settings_save(self, new_cfg: AppConfig) -> None:
        self.config = new_cfg
        self.save_config()
        self.home.apply_config(new_cfg)
        self.article.apply_config(new_cfg)

    def _on_request_generate(self, payload: dict) -> None:
        ok = self.article_controller.request_generate(payload)
        if not ok:
            from qfluentwidgets import InfoBar, InfoBarPosition
            if not self.config.out_dir:
                InfoBar.error(
                    "缺少输出目录", "请先在设置页配置输出目录",
                    parent=self, position=InfoBarPosition.TOP,
                )
            else:
                InfoBar.warning(
                    "正在生成", "请等待当前任务完成",
                    parent=self, position=InfoBarPosition.TOP,
                )

    def _on_generated(self, result) -> None:
        from csm_core.assembler.render import compose_draft
        draft = compose_draft(result.plan)
        self.article.load_result(
            self.article_controller.current_template,
            result.plan, draft, result.final_text,
        )
        self.switchTo(self.article)

    def _show_plan_warnings_list(self, warnings: list) -> None:
        if not warnings:
            return
        from qfluentwidgets import InfoBar, InfoBarPosition
        InfoBar.warning(
            title="注意",
            content="\n".join(warnings[:3]),
            parent=self,
            position=InfoBarPosition.TOP,
            duration=6000,
        )

    def _on_reroll_slot(self, slot_id: str) -> None:
        self.article_controller.reroll_slot(
            slot_id,
            user_config={
                "brand_competitors": int(self.article.controls.brand_count_input.value())
            },
        )

    def _on_reroll_completed(self, new_plan) -> None:
        from csm_core.assembler.render import compose_draft
        self.article.update_plan(
            self.article_controller.current_template,
            new_plan,
            compose_draft(new_plan),
        )

    def _on_polish(self, provider: str, skill_path) -> None:
        self.article_controller.polish(provider, skill_path)

    def _on_polished(self, text: str) -> None:
        self.article.markdown_view.set_polished(text)

    def _on_export(self) -> None:
        self.article_controller.export()

    def _on_exported(self, paths: dict) -> None:
        from qfluentwidgets import InfoBar, InfoBarPosition, PushButton
        import os
        out_dir = Path(self.config.out_dir)
        bar = InfoBar.success(
            title="导出成功", content=paths["markdown"],
            parent=self, position=InfoBarPosition.TOP, duration=5000,
        )
        open_btn = PushButton("打开文件夹", bar)
        open_btn.clicked.connect(lambda: os.startfile(str(out_dir)))
        bar.addWidget(open_btn)
        bar.show()

    def _on_export_failed(self, msg: str) -> None:
        from qfluentwidgets import InfoBar, InfoBarPosition
        first_line = msg.splitlines()[0] if msg else "未知错误"
        if first_line.startswith("OutputDirectoryMissing"):
            InfoBar.error(
                "缺少输出目录", "请先在设置页配置输出目录",
                parent=self, position=InfoBarPosition.TOP, duration=5000,
            )
            return
        InfoBar.error(
            "导出失败", first_line,
            parent=self, position=InfoBarPosition.TOP, duration=5000,
        )

    def _on_generate_failed(self, msg: str) -> None:
        from qfluentwidgets import InfoBar, InfoBarPosition
        first_line = msg.splitlines()[0] if msg else "未知错误"
        # EmptyPoolError (vault too small for the template) is a data issue,
        # not a system error — surface as warning, not red.
        if "EmptyPoolError" in first_line:
            InfoBar.warning(
                "素材不足", first_line,
                parent=self, position=InfoBarPosition.TOP, duration=6000,
            )
            return
        InfoBar.error(
            "生成失败", first_line,
            parent=self, position=InfoBarPosition.TOP, duration=5000,
        )
