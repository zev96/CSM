"""FluentWindow shell with three navigation items."""
from __future__ import annotations
from pathlib import Path
from qfluentwidgets import FluentWindow, FluentIcon, NavigationItemPosition
from .config import AppConfig, load_config, save_config as _save_config
from .pages.home_page import HomePage
from .pages.article_page import ArticlePage
from .pages.settings_page import SettingsPage
from .workers.polish_worker import PolishWorker
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
        self._polish_worker: PolishWorker | None = None
        self._vault_cache: tuple[Path, object, object] | None = None
        self.resize(1280, 820)
        self.setWindowTitle("CSM — Content SEO Maker")

        self.article_controller = ArticleController(self.config, parent=self)
        self.article_controller.generated.connect(self._on_generated)
        self.article_controller.generate_failed.connect(self._on_generate_failed)
        self.article_controller.plan_warnings.connect(self._show_plan_warnings_list)

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

    def _get_vault(self, vault_root):
        if self._vault_cache is None or self._vault_cache[0] != vault_root:
            from csm_core.vault.scanner import scan_vault
            from csm_core.vault.brand_registry import build_brand_registry
            self._vault_cache = (vault_root, scan_vault(vault_root), build_brand_registry(vault_root))
        return self._vault_cache[1], self._vault_cache[2]

    def _on_settings_save(self, new_cfg: AppConfig) -> None:
        self.config = new_cfg
        self.save_config()
        self.home.apply_config(new_cfg)
        self.article.apply_config(new_cfg)
        self._vault_cache = None

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
        self._current_result = result
        self.article.load_result(
            self.article_controller._current_template,
            result,
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
        from .workers.reroll import reroll_slot
        if not self.article.current_result or not self.article._template:
            return
        if not self.config.vault_root:
            return
        index, registry = self._get_vault(Path(self.config.vault_root))
        self.article._reroll_counter += 1
        new_plan = reroll_slot(
            slot_id=slot_id, template=self.article._template,
            index=index, registry=registry,
            current_plan=self.article.current_result.plan,
            counter=self.article._reroll_counter,
            user_config={
                "brand_competitors": int(self.article.controls.brand_count_input.value())
            },
        )
        self.article.current_result.plan = new_plan
        self.article.slot_list.load(self.article._template, new_plan)
        self.article.markdown_view.set_draft(self.article._compose_draft(new_plan))

    def _on_polish(self, provider: str, skill_path) -> None:
        if not self.article.current_result or not self.article._template:
            return
        if self._polish_worker is not None and self._polish_worker.isRunning():
            from qfluentwidgets import InfoBar, InfoBarPosition
            InfoBar.warning(
                "正在润色", "请等待当前润色任务完成",
                parent=self, position=InfoBarPosition.TOP,
            )
            return
        from csm_core.llm.prompts import build_prompt, PromptInputs
        from .llm_factory import build_client

        template = self.article._template
        plan = self.article.current_result.plan
        draft = self.article._compose_draft(plan)

        skill_text: str | None = None
        if skill_path:
            try:
                skill_text = Path(skill_path).read_text(encoding="utf-8")
            except OSError as exc:
                from qfluentwidgets import InfoBar, InfoBarPosition
                InfoBar.error(
                    "读取 skill 失败", str(exc),
                    parent=self, position=InfoBarPosition.TOP,
                )
                return

        system, user = build_prompt(PromptInputs(
            template_system_prompt=template.system_prompt_default,
            user_skill_prompt=skill_text,
            seo=template.seo_defaults,
            keyword=plan.keyword,
            draft=draft,
        ))
        client = build_client(self.config, provider)
        self._polish_worker = PolishWorker(client=client, system=system, user=user, parent=self)
        self._polish_worker.finished.connect(self._on_polished)
        self._polish_worker.failed.connect(self._on_generate_failed)
        self._polish_worker.start()

    def _on_polished(self, text: str) -> None:
        if self.article.current_result is not None:
            self.article.current_result.final_text = text
        self.article.markdown_view.set_polished(text)

    def _on_export(self) -> None:
        from csm_core.export.markdown import export_article
        from qfluentwidgets import InfoBar, InfoBarPosition, PushButton
        import os
        res = self.article.current_result
        if not res:
            return
        if not self.config.out_dir:
            InfoBar.error(
                "缺少输出目录", "请先在设置页配置输出目录",
                parent=self, position=InfoBarPosition.TOP, duration=5000,
            )
            return
        out_dir = Path(self.config.out_dir)
        try:
            paths = export_article(
                out_dir=out_dir,
                keyword=res.plan.keyword,
                final_text=res.final_text,
                plan=res.plan,
                prompt_snapshot={},
            )
        except Exception as exc:  # noqa: BLE001 — UI boundary, surface all errors as toast
            InfoBar.error(
                "导出失败", f"{type(exc).__name__}: {exc}",
                parent=self, position=InfoBarPosition.TOP, duration=5000,
            )
            return
        bar = InfoBar.success(
            title="导出成功", content=paths["markdown"],
            parent=self, position=InfoBarPosition.TOP, duration=5000,
        )
        open_btn = PushButton("打开文件夹", bar)
        open_btn.clicked.connect(lambda: os.startfile(str(out_dir)))
        bar.addWidget(open_btn)
        bar.show()

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
