"""Slot editor dialog — edit a single Slot's full fields in a popup.

改进
----
* 槽位 ID / 显示名称：提供常用预设下拉，选择后自动填入两个字段。
* 模块路径：ComboBox 全部用索引定位，不依赖 itemData，彻底修复选择后
  下拉键名为空的问题。
* 界面文本：去除所有英文括号注释，保持全中文显示。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QStackedWidget

try:
    from qfluentwidgets import CaptionLabel
except ImportError:  # pragma: no cover
    from qfluentwidgets import BodyLabel as CaptionLabel  # type: ignore[assignment]

from qfluentwidgets import (
    MessageBoxBase, SubtitleLabel, StrongBodyLabel, BodyLabel,
    LineEdit, SpinBox, ComboBox, ScrollArea, CardWidget,
    TransparentToolButton, FluentIcon,
    InfoBar, InfoBarPosition,
)

try:
    from qfluentwidgets import CheckBox
except ImportError:  # pragma: no cover
    from PyQt6.QtWidgets import QCheckBox as CheckBox  # type: ignore[assignment]

if TYPE_CHECKING:
    from csm_core.template.schema import Slot

# ── Constants ─────────────────────────────────────────────────────────────────

_SOURCE_TYPES  = ["notes_query", "brand_fixed", "brand_pool", "test_results_aligned"]
_SOURCE_LABELS = ["笔记查询", "固定品牌", "品牌池", "测试对齐"]

# 常用槽位预设：(显示名, 英文ID, 中文显示名称)
_SLOT_PRESETS: list[tuple[str, str, str]] = [
    ("─ 从常用预设快速填入 ─", "", ""),
    ("引言",           "intro",               "引言"),
    ("科普大点",        "keypoints",            "科普大点"),
    ("自有品牌",        "brand_self",           "自有品牌"),
    ("竞争品牌",        "brand_competitors",    "竞品"),
    ("品牌测试结果",    "test_results",         "品牌测试结果"),
    ("使用场景",        "use_case",             "使用场景"),
    ("购买建议",        "buying_tips",          "购买建议"),
    ("产品参数对比",    "spec_comparison",      "产品参数对比"),
    ("用户痛点",        "pain_points",          "用户痛点"),
    ("总结",           "summary",              "总结"),
    ("行动号召",        "cta",                  "行动号召"),
]

_SKIP_DIRS = {
    ".obsidian", ".trash", ".git", "__pycache__",
    ".venv", "node_modules", ".system_generated",
}

# 模块 ComboBox 中"请选择"和"自定义"两个特殊项的索引偏移
# 结构：[0]=占位行  [1..n]=vault_dirs  [n+1]=自定义
_IDX_PLACEHOLDER = 0  # combo index for the placeholder row
# custom row index = len(vault_dirs) + 1  → computed dynamically


# ── Module-level vault helpers ─────────────────────────────────────────────────

def _scan_vault_dirs(vault_root: Path) -> list[str]:
    """Return sorted relative paths of **leaf** subdirs that directly contain .md files.

    'Leaf' means the directory contains .md files AND none of its descendant
    directories also appear in the candidate list.  This prevents parent /
    container folders (e.g. "营销资料库", "营销资料库/产品模块") from
    showing up in the picker when their children are more specific options.
    """
    candidates: list[str] = []
    try:
        for p in sorted(vault_root.rglob("*")):
            if not p.is_dir():
                continue
            try:
                rel_parts = p.relative_to(vault_root).parts
            except ValueError:
                continue
            if any(part.startswith(".") or part in _SKIP_DIRS for part in rel_parts):
                continue
            if not any(c.suffix == ".md" for c in p.iterdir() if c.is_file()):
                continue
            candidates.append("/".join(rel_parts))
            if len(candidates) >= 300:
                break
    except Exception:
        pass

    # Keep only true leaf dirs: exclude any path that is an ancestor of
    # another path in the candidate set (i.e. "path/" is a prefix of "other").
    cset = set(candidates)
    return sorted(
        d for d in candidates
        if not any(other.startswith(d + "/") for other in cset)
    )


def _scan_frontmatter(md_dir: Path) -> dict[str, list[str]]:
    """Return ``{key: sorted_unique_values}`` from YAML frontmatter of .md files."""
    seen: dict[str, set[str]] = {}
    try:
        for md in sorted(md_dir.glob("*.md"))[:200]:
            try:
                text = md.read_text(encoding="utf-8", errors="ignore")
                in_fm = started = False
                for line in text.splitlines():
                    stripped = line.strip()
                    if stripped == "---":
                        if not started:
                            started = in_fm = True
                            continue
                        break
                    if in_fm and ":" in stripped and not stripped.startswith("#"):
                        k, _, v = stripped.partition(":")
                        k, v = k.strip(), v.strip()
                        if k and v:
                            seen.setdefault(k, set()).add(v)
            except Exception:
                pass
    except Exception:
        pass
    return {k: sorted(vs) for k, vs in sorted(seen.items())}


# ── Dialog ────────────────────────────────────────────────────────────────────

class SlotEditorDialog(MessageBoxBase):
    """Popup dialog for creating or editing a single template Slot."""

    def __init__(
        self,
        slot: "Slot | None" = None,
        existing_slots: "list[tuple[str,str]] | None" = None,
        existing_slot_ids: "list[str] | None" = None,   # legacy compat
        vault_root: "Path | None" = None,
        parent=None,
    ):
        super().__init__(parent)
        # normalise to list[tuple[id, label]]
        if existing_slots is not None:
            self._existing_slots: list[tuple[str, str]] = existing_slots
        elif existing_slot_ids is not None:
            self._existing_slots = [(sid, sid) for sid in existing_slot_ids]
        else:
            self._existing_slots = []
        self._existing_ids: list[str] = [s[0] for s in self._existing_slots]
        self._editing_id: str | None = slot.id if slot else None
        self._vault_root = vault_root
        self._vault_dirs: list[str] = _scan_vault_dirs(vault_root) if vault_root else []
        self._nq_fm: dict[str, list[str]] = {}

        self.widget.setMinimumWidth(600)

        self.titleLabel = SubtitleLabel("编辑槽位" if slot else "新建槽位", self)
        self.viewLayout.addWidget(self.titleLabel)

        scroll = ScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFixedHeight(520)
        scroll.setStyleSheet(
            "QScrollArea, #scrollWidget {background: transparent; border: none;}"
        )
        inner = QWidget()
        inner.setObjectName("scrollWidget")
        scroll.setWidget(inner)

        layout = QVBoxLayout(inner)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(8)

        # ── 基本字段 ──────────────────────────────────────────────────────────
        basic = CardWidget(inner)
        bl = QVBoxLayout(basic)
        bl.setContentsMargins(16, 12, 16, 12)
        bl.setSpacing(6)
        bl.addWidget(StrongBodyLabel("基本字段"))

        # 预设下拉
        bl.addWidget(BodyLabel("常用预设（选择后自动填入 ID 和名称）"))
        self._preset_combo = ComboBox(basic)
        self._preset_combo.addItems([p[0] for p in _SLOT_PRESETS])
        bl.addWidget(self._preset_combo)
        self._preset_combo.currentIndexChanged.connect(self._on_preset_changed)

        bl.addWidget(BodyLabel("程序标识 ID（字母/数字/下划线/连字符，全局唯一）"))
        self.id_input = LineEdit(basic)
        self.id_input.setPlaceholderText("如：intro  或选择上方预设自动填入")
        bl.addWidget(self.id_input)

        bl.addWidget(BodyLabel("显示名称（文章段落标题，可用中文）"))
        self.label_input = LineEdit(basic)
        self.label_input.setPlaceholderText("如：引言-痛点共鸣")
        bl.addWidget(self.label_input)
        layout.addWidget(basic)

        # ── 数据来源 ──────────────────────────────────────────────────────────
        src = CardWidget(inner)
        sl = QVBoxLayout(src)
        sl.setContentsMargins(16, 12, 16, 12)
        sl.setSpacing(6)
        sl.addWidget(StrongBodyLabel("数据来源"))
        sl.addWidget(BodyLabel("来源类型"))
        self.source_type_combo = ComboBox(src)
        self.source_type_combo.addItems(_SOURCE_LABELS)
        sl.addWidget(self.source_type_combo)

        self.source_stack = QStackedWidget(src)
        self.source_stack.addWidget(self._build_nq_page(src))
        self.source_stack.addWidget(self._build_bf_page(src))
        self.source_stack.addWidget(self._build_bp_page(src))
        self.source_stack.addWidget(self._build_tr_page(src))
        sl.addWidget(self.source_stack)
        self.source_type_combo.currentIndexChanged.connect(self.source_stack.setCurrentIndex)
        layout.addWidget(src)

        # ── 采样设置 ──────────────────────────────────────────────────────────
        pick = CardWidget(inner)
        pl = QVBoxLayout(pick)
        pl.setContentsMargins(16, 12, 16, 12)
        pl.setSpacing(6)
        pl.addWidget(StrongBodyLabel("采样设置"))
        pl.addWidget(BodyLabel("采样模式"))
        self.pick_mode_combo = ComboBox(pick)
        self.pick_mode_combo.addItems(["固定数量", "随机范围", "用户可配置"])
        pl.addWidget(self.pick_mode_combo)

        self.pick_stack = QStackedWidget(pick)

        fw = QWidget(); fl = QHBoxLayout(fw); fl.setContentsMargins(0, 0, 0, 0)
        fl.addWidget(BodyLabel("数量："))
        self.pick_fixed = SpinBox(fw); self.pick_fixed.setRange(1, 20); self.pick_fixed.setValue(1)
        fl.addWidget(self.pick_fixed); fl.addStretch(1)
        self.pick_stack.addWidget(fw)

        rw = QWidget(); rl = QHBoxLayout(rw); rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(BodyLabel("最小："))
        self.pick_rnd_min = SpinBox(rw); self.pick_rnd_min.setRange(1, 20); self.pick_rnd_min.setValue(1)
        rl.addWidget(self.pick_rnd_min)
        rl.addWidget(BodyLabel("  最大："))
        self.pick_rnd_max = SpinBox(rw); self.pick_rnd_max.setRange(1, 20); self.pick_rnd_max.setValue(3)
        rl.addWidget(self.pick_rnd_max); rl.addStretch(1)
        self.pick_stack.addWidget(rw)

        uw = QWidget(); ul = QHBoxLayout(uw); ul.setContentsMargins(0, 0, 0, 0)
        ul.addWidget(BodyLabel("默认："))
        self.pick_uc_default = SpinBox(uw); self.pick_uc_default.setRange(1, 20); self.pick_uc_default.setValue(2)
        ul.addWidget(self.pick_uc_default)
        ul.addWidget(BodyLabel("  范围："))
        self.pick_uc_min = SpinBox(uw); self.pick_uc_min.setRange(1, 20); self.pick_uc_min.setValue(1)
        ul.addWidget(self.pick_uc_min)
        ul.addWidget(BodyLabel(" ~ "))
        self.pick_uc_max = SpinBox(uw); self.pick_uc_max.setRange(1, 20); self.pick_uc_max.setValue(5)
        ul.addWidget(self.pick_uc_max); ul.addStretch(1)
        self.pick_stack.addWidget(uw)

        pl.addWidget(self.pick_stack)
        self.pick_mode_combo.currentIndexChanged.connect(self.pick_stack.setCurrentIndex)
        pl.addWidget(BodyLabel("每篇笔记抽取的变体数量"))
        self.variants_spin = SpinBox(pick)
        self.variants_spin.setRange(1, 5); self.variants_spin.setValue(1)
        pl.addWidget(self.variants_spin)
        layout.addWidget(pick)

        # ── 约束 & 依赖 ──────────────────────────────────────────────────────
        con = CardWidget(inner)
        cl = QVBoxLayout(con)
        cl.setContentsMargins(16, 12, 16, 12)
        cl.setSpacing(6)
        cl.addWidget(StrongBodyLabel("约束 & 依赖"))
        self.unique_notes_cb = CheckBox("相同笔记不重复抽取", con)
        cl.addWidget(self.unique_notes_cb)
        cl.addWidget(BodyLabel("依赖槽位（勾选需要先运行的槽位）"))
        self._dep_checkboxes: dict[str, CheckBox] = {}  # key=slot_id
        if self._existing_slots:
            dep_container = QWidget(con)
            dep_v = QVBoxLayout(dep_container)
            dep_v.setContentsMargins(0, 0, 0, 0)
            dep_v.setSpacing(4)
            for _sid, _slabel in self._existing_slots:
                # 显示中文名称，内部 key 用 id
                _cb = CheckBox(_slabel, dep_container)
                self._dep_checkboxes[_sid] = _cb
                dep_v.addWidget(_cb)
            cl.addWidget(dep_container)
        else:
            cl.addWidget(CaptionLabel("暂无其他槽位可选", con))
        layout.addWidget(con)

        layout.addStretch(1)
        self.viewLayout.addWidget(scroll)

        self.yesButton.setText("确定")
        self.cancelButton.setText("取消")

        if slot is not None:
            self._fill_from_slot(slot)

    # ── Source page builders ──────────────────────────────────────────────────

    def _build_nq_page(self, parent: QWidget) -> QWidget:
        w = QWidget(parent)
        l = QVBoxLayout(w)
        l.setContentsMargins(0, 4, 0, 0)
        l.setSpacing(6)

        l.addWidget(BodyLabel("模块路径（从资料库目录中选择）"))
        mod_row = QHBoxLayout()
        self.nq_module_combo = ComboBox(w)
        self._fill_combo(self.nq_module_combo)
        mod_row.addWidget(self.nq_module_combo, 1)
        nq_refresh = TransparentToolButton(FluentIcon.SYNC, w)
        nq_refresh.setToolTip("刷新资料库目录列表")
        nq_refresh.clicked.connect(
            lambda: self._refresh_combo(self.nq_module_combo, self.nq_module_custom)
        )
        mod_row.addWidget(nq_refresh)
        l.addLayout(mod_row)

        self.nq_module_custom = LineEdit(w)
        self.nq_module_custom.setPlaceholderText("手动输入相对路径，如：引言模块/子目录")
        self.nq_module_custom.setVisible(False)
        l.addWidget(self.nq_module_custom)

        self.nq_module_combo.currentIndexChanged.connect(self._on_nq_module_changed)

        l.addWidget(BodyLabel("筛选条件（资料库笔记属性，留空则不筛选）"))
        self.nq_filter = LineEdit(w)
        self.nq_filter.setPlaceholderText('如：{"组件类型":"痛点共鸣"}')
        l.addWidget(self.nq_filter)

        helper_row = QHBoxLayout()
        helper_row.addWidget(CaptionLabel("快捷筛选："))
        self._nq_key_combo = ComboBox(w)
        helper_row.addWidget(self._nq_key_combo, 1)
        helper_row.addWidget(CaptionLabel(" = "))
        self._nq_val_combo = ComboBox(w)
        helper_row.addWidget(self._nq_val_combo, 1)
        apply_btn = TransparentToolButton(FluentIcon.ACCEPT_MEDIUM, w)
        apply_btn.setToolTip("写入筛选条件")
        apply_btn.clicked.connect(self._apply_nq_filter)
        helper_row.addWidget(apply_btn)
        clear_btn = TransparentToolButton(FluentIcon.DELETE, w)
        clear_btn.setToolTip("清空筛选条件")
        clear_btn.clicked.connect(lambda: self.nq_filter.clear())
        helper_row.addWidget(clear_btn)
        l.addLayout(helper_row)

        self._nq_key_combo.currentIndexChanged.connect(self._on_nq_key_changed)
        return w

    def _build_bf_page(self, parent: QWidget) -> QWidget:
        w = QWidget(parent)
        l = QVBoxLayout(w); l.setContentsMargins(0, 4, 0, 0); l.setSpacing(6)
        l.addWidget(BodyLabel("品牌名称"))
        self.bf_brand = LineEdit(w); self.bf_brand.setPlaceholderText("如：CEWEY")
        l.addWidget(self.bf_brand)
        l.addWidget(BodyLabel("产品型号"))
        self.bf_model = LineEdit(w); self.bf_model.setPlaceholderText("如：CEWEYDS18")
        l.addWidget(self.bf_model)
        return w

    def _build_bp_page(self, parent: QWidget) -> QWidget:
        w = QWidget(parent)
        l = QVBoxLayout(w); l.setContentsMargins(0, 4, 0, 0); l.setSpacing(6)
        l.addWidget(BodyLabel("排除品牌（逗号分隔）"))
        self.bp_exclude = LineEdit(w); self.bp_exclude.setPlaceholderText("如：CEWEY,戴森")
        l.addWidget(self.bp_exclude)
        return w

    def _build_tr_page(self, parent: QWidget) -> QWidget:
        w = QWidget(parent)
        l = QVBoxLayout(w); l.setContentsMargins(0, 4, 0, 0); l.setSpacing(6)
        l.addWidget(BodyLabel("跟随槽位（品牌信息来源）"))
        self.tr_follow = LineEdit(w)
        self.tr_follow.setPlaceholderText("如：brand_competitors+brand_self")
        l.addWidget(self.tr_follow)
        l.addWidget(BodyLabel("模块路径（从资料库目录中选择）"))
        tr_row = QHBoxLayout()
        self.tr_module_combo = ComboBox(w)
        self._fill_combo(self.tr_module_combo)
        tr_row.addWidget(self.tr_module_combo, 1)
        tr_refresh = TransparentToolButton(FluentIcon.SYNC, w)
        tr_refresh.setToolTip("刷新资料库目录列表")
        tr_refresh.clicked.connect(
            lambda: self._refresh_combo(self.tr_module_combo, self.tr_module_custom)
        )
        tr_row.addWidget(tr_refresh)
        l.addLayout(tr_row)
        self.tr_module_custom = LineEdit(w)
        self.tr_module_custom.setPlaceholderText("手动输入相对路径…")
        self.tr_module_custom.setVisible(False)
        l.addWidget(self.tr_module_custom)
        self.tr_module_combo.currentIndexChanged.connect(
            lambda _: self.tr_module_custom.setVisible(self._is_custom(self.tr_module_combo))
        )
        return w

    # ── Preset callback ──────────────────────────────────────────────────────

    def _on_preset_changed(self, idx: int) -> None:
        if idx <= 0 or idx >= len(_SLOT_PRESETS):
            return
        _, slot_id, label = _SLOT_PRESETS[idx]
        if slot_id:
            # 如果 ID 已存在则自动追加编号，支持多个同类型槽位
            final_id = slot_id
            n = 2
            while final_id in self._existing_ids:
                final_id = f"{slot_id}_{n}"
                n += 1
            self.id_input.setText(final_id)
        if label:
            self.label_input.setText(label)

    # ── Combo helpers (index-based, NO itemData) ──────────────────────────────

    def _fill_combo(self, combo: ComboBox) -> None:
        """Populate *combo*: [占位行] + vault_dirs + [自定义]"""
        combo.blockSignals(True)
        combo.clear()
        if self._vault_dirs:
            combo.addItem("─ 请选择资料库目录 ─")
            for d in self._vault_dirs:
                combo.addItem(d)
        else:
            combo.addItem("─ 请先在设置中配置资料库路径 ─")
        combo.addItem("── 自定义路径 ──")
        combo.blockSignals(False)

    def _custom_idx(self) -> int:
        """Index of the 'custom path' row = len(vault_dirs) + 1."""
        return len(self._vault_dirs) + 1

    def _is_custom(self, combo: ComboBox) -> bool:
        return combo.currentIndex() == self._custom_idx()

    def _get_module(self, combo: ComboBox, custom_edit: LineEdit) -> str:
        idx = combo.currentIndex()
        n = len(self._vault_dirs)
        if idx <= 0:
            return ""
        if idx > n:           # custom row
            return custom_edit.text().strip()
        return self._vault_dirs[idx - 1]  # valid dir (1-based)

    def _set_module(self, combo: ComboBox, custom_edit: LineEdit, value: str) -> None:
        if not value:
            combo.setCurrentIndex(0)
            custom_edit.setVisible(False)
            return
        try:
            i = self._vault_dirs.index(value)
            combo.setCurrentIndex(i + 1)
            custom_edit.setVisible(False)
        except ValueError:
            combo.setCurrentIndex(self._custom_idx())
            custom_edit.setText(value)
            custom_edit.setVisible(True)

    def _refresh_combo(self, combo: ComboBox, custom_edit: LineEdit) -> None:
        if self._vault_root:
            self._vault_dirs = _scan_vault_dirs(self._vault_root)
        current = self._get_module(combo, custom_edit)
        self._fill_combo(combo)
        if current:
            self._set_module(combo, custom_edit, current)

    # ── Vault callbacks ──────────────────────────────────────────────────────

    def _on_nq_module_changed(self, _: int) -> None:
        is_custom = self._is_custom(self.nq_module_combo)
        self.nq_module_custom.setVisible(is_custom)

        self._nq_fm = {}
        self._nq_key_combo.clear()
        self._nq_val_combo.clear()

        if not is_custom and self._vault_root:
            idx = self.nq_module_combo.currentIndex()
            n = len(self._vault_dirs)
            if 1 <= idx <= n:
                dir_path = self._vault_dirs[idx - 1]
                md_dir = self._vault_root / dir_path
                if md_dir.is_dir():
                    self._nq_fm = _scan_frontmatter(md_dir)
                    self._nq_key_combo.addItems(list(self._nq_fm.keys()))

    def _on_nq_key_changed(self, _: int) -> None:
        key = self._nq_key_combo.currentText()
        self._nq_val_combo.clear()
        if key in self._nq_fm:
            self._nq_val_combo.addItems(self._nq_fm[key])

    def _apply_nq_filter(self) -> None:
        key = self._nq_key_combo.currentText().strip()
        val = self._nq_val_combo.currentText().strip()
        if key and val:
            self.nq_filter.setText(json.dumps({key: val}, ensure_ascii=False))
        else:
            InfoBar.warning(
                "请先选择键和值", "选择模块路径后，快捷筛选才会显示可用的属性",
                parent=self, position=InfoBarPosition.TOP,
            )

    # ── Fill from existing slot ──────────────────────────────────────────────

    def _fill_from_slot(self, slot: "Slot") -> None:
        self.id_input.setText(slot.id)
        self.label_input.setText(slot.label)

        type_str = slot.source.type
        idx = _SOURCE_TYPES.index(type_str) if type_str in _SOURCE_TYPES else 0
        self.source_type_combo.setCurrentIndex(idx)
        self.source_stack.setCurrentIndex(idx)

        if type_str == "notes_query":
            self._set_module(self.nq_module_combo, self.nq_module_custom,
                             getattr(slot.source, "module", ""))
            filt = getattr(slot.source, "filter", {})
            if filt:
                self.nq_filter.setText(json.dumps(filt, ensure_ascii=False))
        elif type_str == "brand_fixed":
            self.bf_brand.setText(getattr(slot.source, "brand", ""))
            self.bf_model.setText(getattr(slot.source, "model", ""))
        elif type_str == "brand_pool":
            self.bp_exclude.setText(",".join(getattr(slot.source, "exclude_brands", [])))
        elif type_str == "test_results_aligned":
            self.tr_follow.setText(getattr(slot.source, "follow_slot", ""))
            self._set_module(self.tr_module_combo, self.tr_module_custom,
                             getattr(slot.source, "module", ""))

        pick = slot.pick_notes
        if isinstance(pick, int):
            self.pick_mode_combo.setCurrentIndex(0)
            self.pick_stack.setCurrentIndex(0)
            self.pick_fixed.setValue(pick)
        elif hasattr(pick, "random_between") and pick.random_between:
            self.pick_mode_combo.setCurrentIndex(1)
            self.pick_stack.setCurrentIndex(1)
            self.pick_rnd_min.setValue(pick.random_between[0])
            self.pick_rnd_max.setValue(pick.random_between[1])
        elif hasattr(pick, "user_configurable") and pick.user_configurable:
            self.pick_mode_combo.setCurrentIndex(2)
            self.pick_stack.setCurrentIndex(2)
            if pick.default is not None:
                self.pick_uc_default.setValue(pick.default)
            if pick.range:
                self.pick_uc_min.setValue(pick.range[0])
                self.pick_uc_max.setValue(pick.range[1])

        self.variants_spin.setValue(slot.pick_variants_per_note)
        self.unique_notes_cb.setChecked("unique_notes" in slot.constraints)
        for dep_id in (slot.depends_on or []):
            if dep_id in self._dep_checkboxes:
                self._dep_checkboxes[dep_id].setChecked(True)

    # ── Build dict ───────────────────────────────────────────────────────────

    def _build_slot_dict(self) -> dict:
        type_str = _SOURCE_TYPES[self.source_type_combo.currentIndex()]

        if type_str == "notes_query":
            module = self._get_module(self.nq_module_combo, self.nq_module_custom)
            raw = self.nq_filter.text().strip()
            try:
                filt = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                filt = {}
            source: dict = {"type": "notes_query", "module": module, "filter": filt}
        elif type_str == "brand_fixed":
            source = {
                "type": "brand_fixed",
                "brand": self.bf_brand.text().strip(),
                "model": self.bf_model.text().strip(),
            }
        elif type_str == "brand_pool":
            excl = [b.strip() for b in self.bp_exclude.text().split(",") if b.strip()]
            source = {"type": "brand_pool", "exclude_brands": excl}
        else:
            source = {
                "type": "test_results_aligned",
                "follow_slot": self.tr_follow.text().strip(),
                "module": self._get_module(self.tr_module_combo, self.tr_module_custom),
            }

        mode = self.pick_mode_combo.currentIndex()
        if mode == 0:
            pick_notes: object = self.pick_fixed.value()
        elif mode == 1:
            pick_notes = {"random_between": [self.pick_rnd_min.value(), self.pick_rnd_max.value()]}
        else:
            pick_notes = {
                "user_configurable": True,
                "default": self.pick_uc_default.value(),
                "range": [self.pick_uc_min.value(), self.pick_uc_max.value()],
            }

        constraints = ["unique_notes"] if self.unique_notes_cb.isChecked() else []
        depends_on = [sid for sid, cb in self._dep_checkboxes.items() if cb.isChecked()]

        return {
            "id": self.id_input.text().strip(),
            "label": self.label_input.text().strip(),
            "source": source,
            "pick_notes": pick_notes,
            "pick_variants_per_note": self.variants_spin.value(),
            "constraints": constraints,
            "depends_on": depends_on,
        }

    # ── Validation ───────────────────────────────────────────────────────────

    def validate(self) -> bool:
        from csm_core.template.schema import Slot as _Slot

        slot_id = self.id_input.text().strip()
        if not slot_id:
            InfoBar.error("验证失败", "槽位 ID 不能为空",
                          parent=self, position=InfoBarPosition.TOP)
            return False
        if slot_id != self._editing_id and slot_id in self._existing_ids:
            InfoBar.error("验证失败", f"槽位 ID「{slot_id}」已存在，请使用唯一 ID",
                          parent=self, position=InfoBarPosition.TOP)
            return False
        if not self.label_input.text().strip():
            InfoBar.error("验证失败", "显示名称不能为空",
                          parent=self, position=InfoBarPosition.TOP)
            return False
        try:
            _Slot.model_validate(self._build_slot_dict())
        except Exception as exc:
            InfoBar.error("结构校验失败", str(exc).splitlines()[0],
                          parent=self, position=InfoBarPosition.TOP)
            return False
        return True

    def get_slot(self) -> "Slot":
        """Return the validated Slot.  Call only after dialog accepted."""
        from csm_core.template.schema import Slot as _Slot
        return _Slot.model_validate(self._build_slot_dict())
