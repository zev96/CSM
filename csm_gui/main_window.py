"""FluentWindow shell with three navigation items."""
from __future__ import annotations
from pathlib import Path
from qfluentwidgets import FluentWindow, FluentIcon, NavigationItemPosition
from .config import AppConfig, load_config, save_config as _save_config
from .pages.home_page import HomePage
from .pages.article_page import ArticlePage
from .pages.settings_page import SettingsPage


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
        self._worker = None
        self._last_template_path: Path | None = None
        self._vault_cache: tuple[Path, object, object] | None = None
        self.resize(1280, 820)
        self.setWindowTitle("CSM — Content SEO Maker")

        self.home = HomePage(config=self.config, parent=self)
        self.home.request_generate.connect(self._on_request_generate)
        self.article = ArticlePage(
            skill_dir=Path(self.config.skill_dir) if self.config.skill_dir else None,
            default_provider=self.config.default_provider,
            parent=self,
        )
        self.article.reroll_slot_requested.connect(self._on_reroll_slot)
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
        if not self.config.out_dir:
            from qfluentwidgets import InfoBar, InfoBarPosition
            InfoBar.error(
                "缺少输出目录", "请先在设置页配置输出目录",
                parent=self, position=InfoBarPosition.TOP,
            )
            return
        if self._worker is not None and self._worker.isRunning():
            from qfluentwidgets import InfoBar, InfoBarPosition
            InfoBar.warning(
                "正在生成", "请等待当前任务完成",
                parent=self, position=InfoBarPosition.TOP,
            )
            return
        from csm_core.pipeline import GenerateRequest
        from .workers.generate_worker import GenerateWorker
        from .llm_factory import build_client
        client = build_client(self.config, payload["provider"])
        self._last_template_path = Path(payload["template_path"])
        req = GenerateRequest(
            keyword=payload["keyword"],
            vault_root=Path(payload["vault_root"]),
            template_path=self._last_template_path,
            out_dir=Path(self.config.out_dir),
            llm_client=client,
            seed=self.config.last_seed,
        )
        self._worker = GenerateWorker(req, self)
        self._worker.finished.connect(self._on_generated)
        self._worker.failed.connect(self._on_generate_failed)
        self._worker.start()

    def _on_generated(self, result) -> None:
        from csm_core.template.loader import load_template
        self._current_result = result
        template = load_template(self._last_template_path)
        self.article.load_result(template, result)
        self.switchTo(self.article)

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
        draft = "\n\n".join(
            "\n\n".join(p.text for p in s.picks) for s in new_plan.slots if s.picks
        )
        self.article.markdown_view.set_draft(draft)

    def _on_generate_failed(self, msg: str) -> None:
        from qfluentwidgets import InfoBar, InfoBarPosition
        first_line = msg.splitlines()[0] if msg else "未知错误"
        InfoBar.error(
            "生成失败", first_line,
            parent=self, position=InfoBarPosition.TOP, duration=5000,
        )
