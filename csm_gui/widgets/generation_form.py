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
        self.template_combo.currentIndexChanged.connect(lambda _i: self.changed.emit())
        root.addWidget(self.template_combo)
        self._reload_templates(config.default_template or "")

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

    def refresh_templates(self) -> None:
        """Public: rescan template directory (e.g. after editing templates)."""
        self._reload_templates(self.payload()["template_path"])

    def apply_config(self, cfg: AppConfig) -> None:
        self._config = cfg
        self._reload_templates(cfg.default_template or "")

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
        }
