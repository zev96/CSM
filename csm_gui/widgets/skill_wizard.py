"""Multi-step skill creation wizard.

Replaces the single-line "name → drop in skeleton" prompt with a 3-step
flow that bakes the user's stylistic choices into the skeleton body:

1. **基础**     name + target platform/preset
2. **风格**     tone, density, hook style, prohibitions
3. **预览**     editable preview of the generated markdown

The wizard returns ``(name, body_markdown)`` on accept; the caller is
responsible for writing the file. Keeping IO out of the wizard makes it
easy to unit-test the skeleton generator.
"""
from __future__ import annotations
from dataclasses import dataclass, field

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QStackedWidget, QFormLayout,
)
from qfluentwidgets import (
    SubtitleLabel, StrongBodyLabel, BodyLabel, CaptionLabel,
    LineEdit, ComboBox, CheckBox, TextEdit,
    PushButton, PrimaryPushButton, FluentIcon,
    MessageBoxBase, InfoBar, InfoBarPosition,
)


# ── Preset library ────────────────────────────────────────────────────────────

@dataclass
class _Preset:
    label: str
    hook: str
    density: str
    tone: str
    prohibitions: list[str] = field(default_factory=list)


_PRESETS: dict[str, _Preset] = {
    "xiaohongshu": _Preset(
        label="小红书种草",
        hook="第一句必须抛出一个共鸣痛点或反常识结论",
        density="每段 2–3 句，多用换行；emoji 不超过 2 个",
        tone="亲切口语化，第一人称分享视角",
        prohibitions=["不要使用'最'、'第一'、'100%'等绝对化用语",
                       "不要出现'点击关注''免费领'等引流话术"],
    ),
    "zhihu": _Preset(
        label="知乎深度长文",
        hook="开篇先给结论，再展开论证",
        density="段落 4–6 句，逻辑链完整",
        tone="理性、专业、克制，避免情绪化表达",
        prohibitions=["不要堆砌形容词", "禁止未经证实的数据"],
    ),
    "seo": _Preset(
        label="SEO 资讯文",
        hook="首段 80 字内自然包含核心关键词",
        density="短段为主（3 句以内）便于扫读",
        tone="中性、信息密度优先",
        prohibitions=["禁止关键词堆砌", "禁止与主题无关的扩写"],
    ),
    "blank": _Preset(
        label="空白模板",
        hook="",
        density="",
        tone="",
        prohibitions=[],
    ),
}


def build_skeleton(*, product: str, preset: _Preset, extra_prohibitions: str) -> str:
    """Compose a starter markdown body from a preset + user overrides."""
    proh = list(preset.prohibitions)
    for line in (extra_prohibitions or "").splitlines():
        s = line.strip().lstrip("-").strip()
        if s:
            proh.append(s)
    proh_block = "\n".join(f"- {p}" for p in proh) if proh else "- "

    return f"""# {preset.label or '新 Skill'}

你是一位专注于 {product or '{ product }'} 品类的内容编辑。收到毛坯文后，按下面的规则进行**润色改写**。

## 风格约束

- 开头钩子：{preset.hook}
- 段落密度：{preset.density}
- 语气：{preset.tone}
- 数字保留：必须逐字保留所有参数、价格、型号。
- 品牌/型号：必须原样保留。

## 结构约束

- 保留毛坯文的所有 H2 段落及其顺序。
- 不得新增虚构内容。

## 禁止项

{proh_block}

## 输出

直接输出润色后的完整正文 Markdown，不要加任何前言或代码块包裹。
"""


# ── Wizard dialog ─────────────────────────────────────────────────────────────

class SkillWizard(MessageBoxBase):
    """3-step skill creation wizard.

    Use ``result_name()`` and ``result_body()`` after ``exec()`` returns a
    truthy value; the wizard does not touch the filesystem itself.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.widget.setMinimumSize(560, 520)

        self._name = ""
        self._body = ""

        self._title = SubtitleLabel("新建 Skill — 1 / 3 基础", self)
        self.viewLayout.addWidget(self._title)

        self.stack = QStackedWidget(self)
        self.stack.addWidget(self._build_step1())
        self.stack.addWidget(self._build_step2())
        self.stack.addWidget(self._build_step3())
        self.viewLayout.addWidget(self.stack, 1)

        # Custom nav row replaces the default Yes/Cancel layout — we keep
        # the parent's buttonGroup but hide Yes until the final step.
        self._back_btn = PushButton(FluentIcon.LEFT_ARROW, "上一步", self)
        self._next_btn = PrimaryPushButton(FluentIcon.RIGHT_ARROW, "下一步", self)
        self._back_btn.clicked.connect(self._on_back)
        self._next_btn.clicked.connect(self._on_next)
        nav = QHBoxLayout()
        nav.addWidget(self._back_btn)
        nav.addStretch(1)
        nav.addWidget(self._next_btn)
        self.viewLayout.addLayout(nav)

        # The parent's Yes button doubles as "Create" on the final step.
        self.yesButton.setText("创建")
        self.cancelButton.setText("取消")
        self.yesButton.hide()

        self._refresh_nav()

    # ── Public API ───────────────────────────────────────────────────────
    def result_name(self) -> str:
        return self._name

    def result_body(self) -> str:
        return self._body

    # ── Step 1: name + preset ────────────────────────────────────────────
    def _build_step1(self) -> QWidget:
        w = QWidget(self)
        form = QFormLayout(w)
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(12)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self._name_input = LineEdit(w)
        self._name_input.setPlaceholderText("如：xiaohongshu-polish")
        form.addRow(BodyLabel("Skill 名称"), self._name_input)

        self._product_input = LineEdit(w)
        self._product_input.setPlaceholderText("如：宠物吸尘器、轻办公笔电")
        form.addRow(BodyLabel("适用品类"), self._product_input)

        self._preset_combo = ComboBox(w)
        for key, p in _PRESETS.items():
            self._preset_combo.addItem(p.label, userData=key)
        form.addRow(BodyLabel("起始模板"), self._preset_combo)

        hint = CaptionLabel("名称将作为文件名（.md），仅支持字母/数字/连字符。", w)
        hint.setStyleSheet("color: rgba(30,28,25,0.45)")
        form.addRow(hint)
        return w

    # ── Step 2: style overrides ──────────────────────────────────────────
    def _build_step2(self) -> QWidget:
        w = QWidget(self)
        form = QFormLayout(w)
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(12)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        form.addRow(StrongBodyLabel("微调风格（可留空，使用模板默认值）"))

        self._hook_input = LineEdit(w)
        self._hook_input.setPlaceholderText("覆盖：开头钩子要求")
        form.addRow(BodyLabel("开头钩子"), self._hook_input)

        self._density_input = LineEdit(w)
        self._density_input.setPlaceholderText("覆盖：段落密度")
        form.addRow(BodyLabel("段落密度"), self._density_input)

        self._tone_input = LineEdit(w)
        self._tone_input.setPlaceholderText("覆盖：语气")
        form.addRow(BodyLabel("语气"), self._tone_input)

        self._extra_proh = TextEdit(w)
        self._extra_proh.setPlaceholderText("每行一条额外禁止项（可选）")
        self._extra_proh.setFixedHeight(110)
        form.addRow(BodyLabel("额外禁止项"), self._extra_proh)
        return w

    # ── Step 3: preview ──────────────────────────────────────────────────
    def _build_step3(self) -> QWidget:
        w = QWidget(self)
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        lay.addWidget(StrongBodyLabel("预览（可直接编辑）"))
        self._preview = TextEdit(w)
        self._preview.setPlaceholderText("生成的 markdown 会显示在这里 …")
        lay.addWidget(self._preview, 1)
        return w

    # ── Navigation ───────────────────────────────────────────────────────
    def _on_back(self) -> None:
        i = self.stack.currentIndex()
        if i > 0:
            self.stack.setCurrentIndex(i - 1)
            self._refresh_nav()

    def _on_next(self) -> None:
        i = self.stack.currentIndex()
        if i == 0 and not self._validate_step1():
            return
        if i == 1:
            self._populate_preview()
        if i < 2:
            self.stack.setCurrentIndex(i + 1)
            self._refresh_nav()

    def _refresh_nav(self) -> None:
        i = self.stack.currentIndex()
        titles = ["新建 Skill — 1 / 3 基础",
                  "新建 Skill — 2 / 3 风格",
                  "新建 Skill — 3 / 3 预览"]
        self._title.setText(titles[i])
        self._back_btn.setEnabled(i > 0)
        is_last = (i == self.stack.count() - 1)
        self._next_btn.setVisible(not is_last)
        self.yesButton.setVisible(is_last)

    def _validate_step1(self) -> bool:
        name = self._name_input.text().strip()
        if not name:
            InfoBar.error("名称不能为空", "请填写 Skill 名称",
                          parent=self, position=InfoBarPosition.TOP)
            return False
        bad = [c for c in name if not (c.isalnum() or c in "-_")]
        if bad:
            InfoBar.error("名称包含非法字符", "仅允许字母 / 数字 / - _",
                          parent=self, position=InfoBarPosition.TOP)
            return False
        return True

    def _selected_preset(self) -> _Preset:
        key = self._preset_combo.currentData() or "blank"
        base = _PRESETS.get(key, _PRESETS["blank"])
        return _Preset(
            label=base.label,
            hook=self._hook_input.text().strip() or base.hook,
            density=self._density_input.text().strip() or base.density,
            tone=self._tone_input.text().strip() or base.tone,
            prohibitions=list(base.prohibitions),
        )

    def _populate_preview(self) -> None:
        preset = self._selected_preset()
        body = build_skeleton(
            product=self._product_input.text().strip(),
            preset=preset,
            extra_prohibitions=self._extra_proh.toPlainText(),
        )
        self._preview.setPlainText(body)

    def accept(self) -> None:  # type: ignore[override]
        # Re-validate name on final accept in case the user navigated back
        # and cleared it after passing step 1.
        if not self._validate_step1():
            self.stack.setCurrentIndex(0)
            self._refresh_nav()
            return
        self._name = self._name_input.text().strip()
        self._body = self._preview.toPlainText()
        super().accept()
