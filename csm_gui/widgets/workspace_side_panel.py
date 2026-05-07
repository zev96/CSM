"""Right-hand side panel for the article workspace.

Simplified layout:

  top body card (white)
    当前 Skill          → dropdown ComboBox
    微调                → pill groups for 语气 / 长度
    润色                → primary button (triggers AI polish on the 初稿 tab)
  bottom footer (transparent)
    整篇重新生成 · 导出

A hidden ``ControlsPanel`` still owns the polish skill/provider wiring so
``main_window`` signals keep working unchanged.
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel,
)
from qfluentwidgets import (
    StrongBodyLabel, PushButton, PrimaryPushButton, FluentIcon, ComboBox,
    ScrollArea,
)

from .controls_panel import ControlsPanel


# ── Design tokens ───────────────────────────────────────────────────────────
_INK    = "#1e1c19"
_INK_2  = "rgba(30,28,25,0.62)"
_INK_3  = "rgba(30,28,25,0.38)"
_INK_5  = "rgba(30,28,25,0.08)"
_ACCENT        = "#2f6f5e"
_ACCENT_SOFTER = "#ecf2ee"


def _section_eyebrow(text: str, parent=None) -> QLabel:
    lbl = QLabel(text, parent)
    lbl.setStyleSheet(
        f"color: {_INK_3}; font-size: 11px; letter-spacing: 0.6px;"
        "font-weight: 600; background: transparent;"
    )
    return lbl


class WorkspaceSidePanel(QWidget):
    """Right-hand panel. Preserves the old ControlsPanel signal surface."""

    polish_requested    = pyqtSignal(object)   # (skill_path: Path | None)
    export_requested    = pyqtSignal()
    rerun_all_requested = pyqtSignal()
    clear_all_requested = pyqtSignal()
    skill_library_requested = pyqtSignal()  # kept for back-compat (unused now)

    def __init__(
        self,
        skill_dir: Path | None = None,
        provider_default: str = "",
        preferred_skill: str | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.setObjectName("WorkspaceSidePanel")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet("#WorkspaceSidePanel { background: transparent; }")
        self.setMinimumWidth(300)

        self._skill_dir: Path | None = Path(skill_dir) if skill_dir else None
        self._preferred_skill: str | None = preferred_skill

        # Hidden ControlsPanel still drives provider/skill bookkeeping.
        self._controls = ControlsPanel(
            skill_dir=skill_dir, provider_default=provider_default,
            preferred_skill=preferred_skill, parent=self,
        )
        self._controls.hide()
        self._controls.polish_requested.connect(self.polish_requested.emit)
        self._controls.export_requested.connect(self.export_requested.emit)
        self._controls.rerun_all_requested.connect(self.rerun_all_requested.emit)
        self._controls.clear_all_requested.connect(self.clear_all_requested.emit)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 4, 18, 14)
        root.setSpacing(12)

        # ── Body (transparent, matches main bg) ──────────────────────────
        body_card = QFrame(self); body_card.setObjectName("SideBodyCard")
        body_card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        body_card.setStyleSheet("#SideBodyCard { background: transparent; border: none; }")
        scroll = ScrollArea(body_card)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet(
            "ScrollArea, QScrollArea, QScrollArea > QWidget > QWidget "
            "{ background: transparent; border: none; }"
        )
        inner = QWidget(); inner.setStyleSheet("background: transparent;")
        b_lay = QVBoxLayout(inner)
        b_lay.setContentsMargins(0, 12, 0, 12); b_lay.setSpacing(14)

        # Skill dropdown
        b_lay.addWidget(_section_eyebrow("当前 Skill", inner))
        self._skill_combo = ComboBox(inner)
        self._skill_combo.setFixedHeight(34)
        self._skill_combo.currentTextChanged.connect(self._on_skill_changed)
        b_lay.addWidget(self._skill_combo)

        # Polish action
        self.polish_btn = PrimaryPushButton(FluentIcon.EDIT, "润色", inner)
        self.polish_btn.setFixedHeight(32)
        self.polish_btn.clicked.connect(self._on_polish_clicked)
        b_lay.addSpacing(4)
        b_lay.addWidget(self.polish_btn)

        b_lay.addStretch(1)
        scroll.setWidget(inner)
        card_lay = QVBoxLayout(body_card); card_lay.setContentsMargins(0, 0, 0, 0)
        card_lay.addWidget(scroll)
        root.addWidget(body_card, 1)

        # ── Footer (transparent bg, single row) ──────────────────────────
        foot = QWidget(self); foot.setStyleSheet("background: transparent;")
        flay = QHBoxLayout(foot); flay.setContentsMargins(0, 0, 0, 0); flay.setSpacing(6)
        self.clear_btn = PushButton(FluentIcon.DELETE, "清空", foot)
        self.clear_btn.setFixedHeight(30)
        self.clear_btn.clicked.connect(self.clear_all_requested.emit)
        flay.addWidget(self.clear_btn, 1)
        self.rerun_btn = PrimaryPushButton(FluentIcon.SYNC, "重新随机", foot)
        self.rerun_btn.setFixedHeight(30)
        self.rerun_btn.clicked.connect(self.rerun_all_requested.emit)
        flay.addWidget(self.rerun_btn, 1)
        self.export_btn = PushButton(FluentIcon.DOWNLOAD, "导出文章", foot)
        self.export_btn.setObjectName("exportButton")
        self.export_btn.setFixedHeight(30)
        self.export_btn.clicked.connect(self.export_requested.emit)
        flay.addWidget(self.export_btn, 1)
        root.addWidget(foot)

        self._refresh_skill_list()

    # ── Skill combo ─────────────────────────────────────────────────────
    def _refresh_skill_list(self) -> None:
        self._skill_combo.blockSignals(True)
        self._skill_combo.clear()
        self._skill_combo.addItem("无")
        if self._skill_dir and self._skill_dir.is_dir():
            for p in sorted(self._skill_dir.glob("*.md")):
                self._skill_combo.addItem(p.stem)
        target = self._preferred_skill or "无"
        idx = self._skill_combo.findText(target)
        self._skill_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self._skill_combo.blockSignals(False)
        # Sync to hidden controls
        self._controls.set_preferred_skill(
            None if target == "无" else target
        )

    def _on_skill_changed(self, name: str) -> None:
        self._preferred_skill = None if name == "无" else name
        self._controls.set_preferred_skill(self._preferred_skill)

    def _on_polish_clicked(self) -> None:
        name = self._skill_combo.currentText()
        if name and name != "无" and self._skill_dir:
            skill_path: Path | None = self._skill_dir / f"{name}.md"
        else:
            skill_path = None
        self.polish_requested.emit(skill_path)

    # ── Public API — mirrors the old ControlsPanel ───────────────────────
    def set_skill_dir(self, skill_dir: Path | None,
                      preferred_skill: str | None = None) -> None:
        self._skill_dir = Path(skill_dir) if skill_dir else None
        self._controls.set_skill_dir(skill_dir, preferred_skill)
        if preferred_skill is not None:
            self._preferred_skill = preferred_skill
        self._refresh_skill_list()

    def refresh_skills(self) -> None:
        """Re-scan the skill directory and update the dropdown.

        Called when the article workspace becomes visible so newly
        created / renamed / deleted skills from the Skill 库 page show up
        without requiring a settings save round-trip.
        """
        self._refresh_skill_list()

    def set_preferred_skill(self, name: str | None) -> None:
        self._preferred_skill = name
        self._controls.set_preferred_skill(name)
        target = name or "无"
        idx = self._skill_combo.findText(target)
        if idx >= 0:
            self._skill_combo.blockSignals(True)
            self._skill_combo.setCurrentIndex(idx)
            self._skill_combo.blockSignals(False)

    def set_provider_default(self, name: str) -> None:
        self._controls.set_provider_default(name)

    # Back-compat for tests that poked the old combo directly.
    @property
    def skill_combo(self):
        return self._skill_combo
