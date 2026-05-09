"""Modal dialog for creating / editing a monitor task.

The same dialog handles both flows — pass an existing :class:`MonitorTask`
to ``__init__`` for edit, or omit it for create. Field set adapts to the
selected task type so the user only sees what's relevant:

- ``zhihu_question``: target URL + 品牌词 + Top-N
- ``*_comment``: target URL + 自发评论文本 + Top-N + 相似度阈值

Schedule is the same shape across types: ``manual`` or daily ``HH:MM``.
"""
from __future__ import annotations
from typing import Any

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFormLayout, QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel, ComboBox, LineEdit, MessageBoxBase, SpinBox, DoubleSpinBox,
    StrongBodyLabel, SubtitleLabel, SwitchButton, TimeEdit,
)
from PyQt6.QtCore import QTime

from csm_core.monitor.base import MonitorTask, TaskType


_TYPE_LABELS: list[tuple[TaskType, str]] = [
    ("zhihu_question", "知乎问题排名"),
    ("bilibili_comment", "B 站评论留存"),
    ("douyin_comment", "抖音评论留存"),
    ("kuaishou_comment", "快手评论留存"),
]


class MonitorTaskDialog(MessageBoxBase):
    """Create / edit dialog for a single :class:`MonitorTask`."""

    def __init__(self, parent: QWidget | None = None, task: MonitorTask | None = None):
        super().__init__(parent)
        self._editing = task
        # MessageBoxBase exposes ``widget`` (the inner panel) and
        # ``viewLayout`` (the body slot). It does NOT expose a
        # ``titleLabel`` attribute in this qfluentwidgets version, so
        # the title is rendered via a SubtitleLabel inserted at the
        # top of viewLayout — same pattern as AccountDialog.
        self.widget.setMinimumWidth(460)
        self.viewLayout.addWidget(
            SubtitleLabel("编辑监测任务" if task else "新建监测任务", self)
        )

        # Containing widget for the dialog body fields.
        body = QWidget(self)
        form = QFormLayout(body)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setSpacing(12)

        # ── Common fields ──────────────────────────────────────────────
        self.type_combo = ComboBox(self)
        for value, label in _TYPE_LABELS:
            self.type_combo.addItem(label, userData=value)
        if task:
            for i in range(self.type_combo.count()):
                if self.type_combo.itemData(i) == task.type:
                    self.type_combo.setCurrentIndex(i)
                    break
            # Editing: type can't change (it would invalidate target_url
            # uniqueness across types).
            self.type_combo.setDisabled(True)
        form.addRow(BodyLabel("类型"), self.type_combo)

        self.name_edit = LineEdit(self)
        self.name_edit.setPlaceholderText("任务名称（用于列表标识）")
        if task:
            self.name_edit.setText(task.name)
        form.addRow(BodyLabel("名称"), self.name_edit)

        self.url_edit = LineEdit(self)
        self.url_edit.setPlaceholderText("https://...")
        if task:
            self.url_edit.setText(task.target_url)
        form.addRow(BodyLabel("目标 URL"), self.url_edit)

        # ── Type-specific fields ───────────────────────────────────────
        # Zhihu fields
        self.brand_edit = LineEdit(self)
        self.brand_edit.setPlaceholderText("需要监测排名的品牌词")
        if task and task.type == "zhihu_question":
            self.brand_edit.setText(str(task.config.get("target_brand", "")))
        self._brand_row = (BodyLabel("品牌词"), self.brand_edit)
        form.addRow(*self._brand_row)

        # Comment fields
        self.my_comment_edit = LineEdit(self)
        self.my_comment_edit.setPlaceholderText("自发评论文本（用于匹配热评列表）")
        if task and task.type.endswith("_comment"):
            self.my_comment_edit.setText(str(task.config.get("my_comment_text", "")))
        self._my_comment_row = (BodyLabel("自发评论"), self.my_comment_edit)
        form.addRow(*self._my_comment_row)

        self.threshold_spin = DoubleSpinBox(self)
        self.threshold_spin.setRange(0.5, 1.0)
        self.threshold_spin.setSingleStep(0.05)
        self.threshold_spin.setValue(float(task.config.get("threshold", 0.85)) if task else 0.85)
        self._threshold_row = (BodyLabel("相似度阈值"), self.threshold_spin)
        form.addRow(*self._threshold_row)

        # Common: Top-N
        self.top_n_spin = SpinBox(self)
        self.top_n_spin.setRange(1, 50)
        self.top_n_spin.setValue(int(task.config.get("top_n", 10)) if task else 10)
        form.addRow(BodyLabel("检测 Top-N"), self.top_n_spin)

        # Schedule
        sched_box = QWidget(self)
        sched_layout = QHBoxLayout(sched_box)
        sched_layout.setContentsMargins(0, 0, 0, 0)
        sched_layout.setSpacing(8)
        self.schedule_switch = SwitchButton(self)
        self.schedule_switch.setOnText("每日定时")
        self.schedule_switch.setOffText("仅手动")
        self.time_edit = TimeEdit(self)
        self.time_edit.setDisplayFormat("HH:mm")
        if task and task.schedule_cron and task.schedule_cron != "manual":
            try:
                hh, mm = task.schedule_cron.split(":", 1)
                self.time_edit.setTime(QTime(int(hh), int(mm)))
            except (ValueError, IndexError):
                self.time_edit.setTime(QTime(9, 0))
            self.schedule_switch.setChecked(True)
        else:
            self.time_edit.setTime(QTime(9, 0))
            self.schedule_switch.setChecked(False)
        self.time_edit.setEnabled(self.schedule_switch.isChecked())
        self.schedule_switch.checkedChanged.connect(self.time_edit.setEnabled)
        sched_layout.addWidget(self.schedule_switch)
        sched_layout.addWidget(self.time_edit)
        sched_layout.addStretch(1)
        form.addRow(BodyLabel("调度"), sched_box)

        self.enabled_switch = SwitchButton(self)
        self.enabled_switch.setOnText("启用")
        self.enabled_switch.setOffText("禁用")
        self.enabled_switch.setChecked(task.enabled if task else True)
        form.addRow(BodyLabel("状态"), self.enabled_switch)

        self.viewLayout.addWidget(body)

        # Wire the type-combo to show/hide the relevant rows.
        self.type_combo.currentIndexChanged.connect(self._refresh_visibility)
        self._refresh_visibility()

        self.yesButton.setText("保存")
        self.cancelButton.setText("取消")

    # ── Public API ─────────────────────────────────────────────────────────
    def to_task(self) -> MonitorTask:
        """Build a :class:`MonitorTask` from the current form state.

        Caller is responsible for persisting it via storage.create_task /
        update_task and for showing an error InfoBar on validation
        failure (we raise ``ValueError`` for empty required fields so
        the caller can surface a meaningful message).
        """
        ttype: TaskType = self.type_combo.currentData() or "zhihu_question"
        name = self.name_edit.text().strip()
        url = self.url_edit.text().strip()
        if not name:
            raise ValueError("请填写任务名称")
        if not url:
            raise ValueError("请填写目标 URL")
        if not url.startswith("http"):
            raise ValueError("URL 需以 http(s) 开头")

        config: dict[str, Any] = {"top_n": int(self.top_n_spin.value())}
        if ttype == "zhihu_question":
            brand = self.brand_edit.text().strip()
            if not brand:
                raise ValueError("请填写要监测的品牌词")
            config["target_brand"] = brand
        else:
            my_comment = self.my_comment_edit.text().strip()
            if not my_comment:
                raise ValueError("请填写自发评论文本")
            config["my_comment_text"] = my_comment
            config["threshold"] = float(self.threshold_spin.value())

        if self.schedule_switch.isChecked():
            t = self.time_edit.time()
            schedule = f"{t.hour():02d}:{t.minute():02d}"
        else:
            schedule = "manual"

        task = MonitorTask(
            id=self._editing.id if self._editing else None,
            type=ttype,
            name=name,
            target_url=url,
            config=config,
            schedule_cron=schedule,
            enabled=self.enabled_switch.isChecked(),
        )
        return task

    # ── Internal ───────────────────────────────────────────────────────────
    def _refresh_visibility(self) -> None:
        ttype = self.type_combo.currentData()
        is_zhihu = ttype == "zhihu_question"
        # Toggle row visibility by hiding both the label and the field —
        # otherwise QFormLayout leaves a stripe of label whitespace.
        for label, widget in (self._brand_row,):
            label.setVisible(is_zhihu)
            widget.setVisible(is_zhihu)
        for label, widget in (self._my_comment_row, self._threshold_row):
            label.setVisible(not is_zhihu)
            widget.setVisible(not is_zhihu)
