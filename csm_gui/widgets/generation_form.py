"""Template picker for single + batch tabs.

Previously also surfaced vault-root and provider inputs; those were moved to
the Settings page because they're app-wide defaults and cluttered the
generate flow. The form still injects them into ``payload()`` by reading
from the AppConfig held in ``self._config``, so downstream controllers
(Article / Batch) are unchanged.
"""
from __future__ import annotations
from pathlib import Path
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QWidget, QVBoxLayout
from qfluentwidgets import BodyLabel, ComboBox
from csm_core.template.loader import list_templates
from csm_core.framework.loader import list_frameworks
from ..config import AppConfig


class GenerationForm(QWidget):
    changed = pyqtSignal()

    def __init__(self, config: AppConfig, parent=None):
        super().__init__(parent)
        self._config: AppConfig = config
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        root.addWidget(BodyLabel("模板"))
        self.template_combo = ComboBox(self)
        self.template_combo.setPlaceholderText("请选择模板（在设置页配置模板目录）")
        self.template_combo.currentIndexChanged.connect(self._on_template_changed)
        self.template_combo.currentIndexChanged.connect(lambda _i: self.changed.emit())
        root.addWidget(self.template_combo)
        self._reload_templates(config.default_template or "")

        root.addWidget(BodyLabel("框架"))
        self.framework_combo = ComboBox(self)
        self.framework_combo.setPlaceholderText("选择排版框架")
        self.framework_combo.currentIndexChanged.connect(
            lambda _i: self.changed.emit()
        )
        root.addWidget(self.framework_combo)
        self._reload_frameworks()

    def _reload_templates(self, selected_path: str) -> None:
        """Re-scan template directory and repopulate the combo.

        Directory = parent of *selected_path* when provided; otherwise
        the combo is left empty with its placeholder showing.
        """
        self.template_combo.blockSignals(True)
        self.template_combo.clear()
        target_dir: Path | None = None
        if selected_path:
            p = Path(selected_path)
            if p.parent.is_dir():
                target_dir = p.parent
        if target_dir is not None:
            for name, path in list_templates(target_dir):
                self.template_combo.addItem(name, userData=str(path))
            if selected_path:
                idx = self.template_combo.findData(str(Path(selected_path)))
                if idx >= 0:
                    self.template_combo.setCurrentIndex(idx)
        self.template_combo.blockSignals(False)
        self.changed.emit()

    def _reload_frameworks(self) -> None:
        """Re-scan `frameworks/` dir (repo-relative) and repopulate combo."""
        self.framework_combo.blockSignals(True)
        self.framework_combo.clear()
        self.framework_combo.addItem("不使用框架（纯拼接）", userData="")
        fw_dir = Path("frameworks")
        for name, path in list_frameworks(fw_dir):
            self.framework_combo.addItem(name, userData=path.stem)
        self.framework_combo.blockSignals(False)

    def refresh_frameworks(self) -> None:
        """Public: rescan after edits in the framework editor."""
        self._reload_frameworks()

    def _on_template_changed(self) -> None:
        """When a template is chosen, auto-select its default_framework if present."""
        path = self.template_combo.currentData()
        if not path:
            return
        try:
            from csm_core.template.loader import load_template
            tpl = load_template(Path(path))
        except Exception:
            return
        default = tpl.default_framework
        if not default:
            self.framework_combo.setCurrentIndex(0)
            return
        idx = self.framework_combo.findData(default)
        if idx >= 0:
            self.framework_combo.setCurrentIndex(idx)

    def refresh_templates(self) -> None:
        """Public: rescan template directory (e.g. after editing templates)."""
        self._reload_templates(self.payload()["template_path"])

    def apply_config(self, cfg: AppConfig) -> None:
        self._config = cfg
        self._reload_templates(cfg.default_template or "")
        self._reload_frameworks()

    def is_valid(self) -> bool:
        # Vault root now lives in settings; require both a template and a
        # configured vault (otherwise downstream generation would fail).
        return bool(
            self.payload()["template_path"]
            and (self._config.vault_root or "").strip()
        )

    def payload(self) -> dict:
        path = self.template_combo.currentData() or ""
        return {
            "template_path": str(path),
            "vault_root": (self._config.vault_root or "").strip(),
            "provider": self._config.default_provider,
            "framework_id": self.framework_combo.currentData() or "",
        }
