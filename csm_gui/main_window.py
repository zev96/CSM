"""FluentWindow shell with three navigation items."""
from __future__ import annotations
from pathlib import Path
from qfluentwidgets import FluentWindow, FluentIcon, NavigationItemPosition
from .config import AppConfig, load_config, save_config as _save_config
from .pages.home_page import HomePage
from .pages.article_page import ArticlePage
from .pages.settings_page import SettingsPage
from .pages.template_manager_page import TemplateManagerPage
from .pages.skills_page import SkillsPage
from .controllers.article_controller import ArticleController
from .controllers.batch_controller import BatchController
from .pages.batch_result_page import BatchResultPage


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
        # Intentionally leave window title empty and hide the title-bar
        # icon / title label — the FluentWindow's left nav carries the
        # app's identity so the top-bar chrome stays quiet.
        self.setWindowTitle("")
        self.titleBar.iconLabel.hide()
        self.titleBar.titleLabel.hide()

        self.article_controller = ArticleController(self.config, parent=self)
        self.article_controller.generated.connect(self._on_generated)
        self.article_controller.generate_failed.connect(self._on_generate_failed)
        self.article_controller.plan_warnings.connect(self._show_plan_warnings_list)
        self.article_controller.polished.connect(self._on_polished)
        self.article_controller.polish_failed.connect(self._on_polish_failed)
        self.article_controller.exported.connect(self._on_exported)
        self.article_controller.export_failed.connect(self._on_export_failed)
        self.article_controller.reroll_completed.connect(self._on_reroll_completed)
        self.article_controller.reroll_failed.connect(self._on_reroll_failed)

        self.home = HomePage(config=self.config, parent=self)
        self.home.request_generate.connect(self._on_request_generate)

        self.batch_controller = BatchController(self.config, parent=self)
        self.batch_controller.batch_started.connect(self._on_batch_started)
        self.batch_controller.batch_progress.connect(self._on_batch_progress)
        self.batch_controller.item_finished.connect(self._on_batch_item_finished)
        self.batch_controller.batch_completed.connect(self._on_batch_completed)
        self.batch_controller.batch_cancelled.connect(self._on_batch_cancelled)
        self.batch_controller.batch_failed.connect(self._on_generate_failed)

        self.batch_result_page = BatchResultPage(self)
        self.batch_result_page.cancel_requested.connect(self.batch_controller.cancel)
        self.batch_result_page.return_requested.connect(lambda: self.switchTo(self.home))
        self.stackedWidget.addWidget(self.batch_result_page)

        self.article_controller.busy_changed.connect(self._on_any_busy)
        self.batch_controller.busy_changed.connect(self._on_any_busy)

        self.home.request_batch.connect(self._on_request_batch)
        self.article = ArticlePage(
            skill_dir=Path(self.config.skill_dir) if self.config.skill_dir else None,
            default_provider=self.config.default_provider,
            parent=self,
        )
        self.article.controls.polish_requested.connect(self._on_polish)
        self.article.controls.export_requested.connect(self._on_export)
        self.article.controls.rerun_all_requested.connect(self._on_rerun_all)
        self.article.controls.clear_all_requested.connect(self._on_clear_all)
        self.article.pick_list_panel.reroll_requested.connect(self._on_reroll_requested)
        # Modal spinner shown while polish runs. Owned by the window so we
        # can dismiss it from any of the polish completion / failure slots.
        self._polish_busy_dialog = None
        self.template_manager = TemplateManagerPage(config=self.config, parent=self)
        self.skills = SkillsPage(config=self.config, parent=self)
        self.settings = SettingsPage(config=self.config, on_save=self._on_settings_save)

        self.addSubInterface(self.home, FluentIcon.HOME, "首页")
        self.addSubInterface(self.article, FluentIcon.DOCUMENT, "文章")
        self.addSubInterface(self.template_manager, FluentIcon.LIBRARY, "模板")
        self.addSubInterface(self.skills, FluentIcon.DICTIONARY, "Skills")
        self.addSubInterface(
            self.settings, FluentIcon.SETTING, "设置",
            position=NavigationItemPosition.BOTTOM,
        )

        # ``self.stackedWidget.addWidget(self.batch_result_page)`` above made
        # that page index 0, so FluentWindow would land there on startup.
        # Force the home page to be the initial view.
        self.switchTo(self.home)

    def save_config(self) -> None:
        _save_config(self.config, self._config_path)

    def _on_settings_save(self, new_cfg: AppConfig) -> None:
        self.config = new_cfg
        self.save_config()
        self.home.apply_config(new_cfg)
        self.article.apply_config(new_cfg)
        self.template_manager.apply_config(new_cfg)
        self.skills.apply_config(new_cfg)
        self.batch_controller.apply_config(new_cfg)

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

    def _on_polish_failed(self, msg: str) -> None:
        self._dismiss_polish_busy()
        self._on_generate_failed(msg)

    def _on_clear_all(self) -> None:
        ok = self.article_controller.clear()
        if not ok:
            from qfluentwidgets import InfoBar, InfoBarPosition
            InfoBar.warning(
                "无法清空", "请等待当前任务完成",
                parent=self, position=InfoBarPosition.TOP,
            )
            return
        self.article.clear()

    def _on_rerun_all(self) -> None:
        ok = self.article_controller.rerun_all()
        if not ok:
            from qfluentwidgets import InfoBar, InfoBarPosition
            InfoBar.warning(
                "无法重新随机", "请先生成一篇文章，或等待当前任务完成",
                parent=self, position=InfoBarPosition.TOP,
            )

    def _on_reroll_requested(self, block_id: str, pick_index: int) -> None:
        self.article.pick_list_panel.set_busy(True)
        ok = self.article_controller.reroll_pick(block_id, pick_index)
        if not ok:
            # Controller refused (no article / busy / missing vault handled via signal).
            self.article.pick_list_panel.set_busy(False)

    def _on_reroll_completed(self, new_plan) -> None:
        from csm_core.assembler.render import compose_draft
        draft = compose_draft(new_plan)
        self.article.update_plan(
            self.article_controller.current_template, new_plan, draft,
        )
        self.article.pick_list_panel.set_busy(False)

    def _on_reroll_failed(self, msg: str) -> None:
        self.article.pick_list_panel.set_busy(False)
        from qfluentwidgets import InfoBar, InfoBarPosition
        InfoBar.warning(
            title="重抽失败", content=msg, parent=self,
            position=InfoBarPosition.TOP, duration=4000,
        )

    def _on_polish(self, skill_path) -> None:
        # Provider is read from config (the workspace no longer has a picker).
        # Pass the current (possibly user-edited) draft text so manual
        # tweaks made in the 初稿 tab are what the LLM polishes.
        self._show_polish_busy()
        self.article_controller.polish(
            self.config.default_provider, skill_path,
            draft_override=self.article.markdown_view.get_draft_text(),
        )

    def _show_polish_busy(self) -> None:
        from .widgets.busy_dialog import BusyDialog
        if self._polish_busy_dialog is not None:
            return
        dlg = BusyDialog(
            title="正在润色",
            message="AI 正在打磨成文，请稍候…",
            parent=self,
        )
        self._polish_busy_dialog = dlg
        dlg.show()

    def _dismiss_polish_busy(self) -> None:
        dlg = self._polish_busy_dialog
        if dlg is None:
            return
        self._polish_busy_dialog = None
        dlg.dismiss()
        dlg.deleteLater()

    def _on_polished(self, text: str) -> None:
        self._dismiss_polish_busy()
        # ``set_polished`` auto-flips the pivot to 成文, fulfilling the
        # "polish done → jump to result tab" behaviour.
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
        if first_line.startswith("NotPolished"):
            InfoBar.warning(
                "尚未润色", "请先点击「润色」生成成文再导出",
                parent=self, position=InfoBarPosition.TOP, duration=5000,
            )
            return
        InfoBar.error(
            "导出失败", first_line,
            parent=self, position=InfoBarPosition.TOP, duration=5000,
        )

    def _on_request_batch(self, payload: dict) -> None:
        if self.article_controller.is_busy():
            from qfluentwidgets import InfoBar, InfoBarPosition
            InfoBar.warning("正在生成", "请先完成当前单篇任务",
                            parent=self, position=InfoBarPosition.TOP)
            return
        ok = self.batch_controller.start_batch(payload)
        if not ok:
            from qfluentwidgets import InfoBar, InfoBarPosition
            InfoBar.error("批量启动失败", "检查输出目录/关键词/资料库路径",
                          parent=self, position=InfoBarPosition.TOP, duration=5000)
            return
        from csm_core.batch.report import BatchReport
        cleaned = []
        seen = set()
        for k in payload["keywords"]:
            k = k.strip()
            if k and k not in seen:
                seen.add(k); cleaned.append(k)
        initial = BatchReport(
            batch_id="pending", batch_dir="",
            started_at="", finished_at=None,
            template_path=payload["template_path"],
            vault_root=payload["vault_root"],
            seed=int(payload.get("seed", self.config.last_seed)),
            total=len(cleaned),
        )
        self.batch_result_page.on_batch_started(initial)
        self.switchTo(self.batch_result_page)

    def _on_batch_progress(self, done, total, keyword):
        self.batch_result_page.on_batch_progress(done, total, keyword)

    def _on_batch_item_finished(self, item):
        self.batch_result_page.on_item_finished(item)

    def _on_batch_started(self, report):
        self.batch_result_page.on_batch_started(report)

    def _on_batch_completed(self, report):
        self.batch_result_page.on_batch_completed(report)
        from qfluentwidgets import InfoBar, InfoBarPosition
        success = sum(1 for i in report.items if i.status == "success")
        failed = sum(1 for i in report.items if i.status == "failed")
        if failed == 0:
            InfoBar.success(
                "批量完成", f"{report.total} 个关键词全部成功",
                parent=self, position=InfoBarPosition.TOP, duration=5000,
            )
        else:
            InfoBar.warning(
                "批量完成（部分失败）", f"成功 {success} / 失败 {failed}",
                parent=self, position=InfoBarPosition.TOP, duration=6000,
            )

    def _on_batch_cancelled(self, report):
        self.batch_result_page.on_batch_cancelled(report)
        from qfluentwidgets import InfoBar, InfoBarPosition
        done = len(report.items)
        InfoBar.info(
            "批量已取消", f"已完成 {done} / {report.total}",
            parent=self, position=InfoBarPosition.TOP, duration=5000,
        )

    def _on_any_busy(self, busy: bool) -> None:
        any_busy = busy or self.article_controller.is_busy() or self.batch_controller.is_busy()
        self.home.set_busy(any_busy)

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
