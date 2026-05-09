"""Monitor center — top-level page with three sub-tabs.

Layout (top → bottom):

1. Alert strip — stacks any active :class:`RankAlertCard` widgets so
   the user sees rank-fell-out warnings the moment they open the page.
2. Pivot toolbar — switches between "知乎问题" / "评论留存" / "历史报告".
3. Action toolbar — new task / run now / start-stop scheduling / export.
4. Task table — name / type / schedule / last check / current rank /
   status. Rows are clickable; selection drives the detail panel.
5. Detail panel — Top-N snapshot for the selected task.

Style discipline
----------------
- No emoji anywhere; status uses FluentIcon glyphs.
- Buttons & cards come from qfluentwidgets only — no raw QPushButton /
  QFrame.
- Layout & spacing mirror the existing pages (article_page / home_page).
"""
from __future__ import annotations
import logging
from typing import Any

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QFileDialog, QHBoxLayout, QHeaderView, QSizePolicy, QStackedWidget,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)
from qfluentwidgets import (
    BodyLabel, CardWidget, ComboBox, FluentIcon, IconWidget, InfoBar,
    InfoBarPosition, MessageBox, Pivot, PrimaryPushButton, PushButton,
    StrongBodyLabel, SubtitleLabel, TextEdit, TransparentToolButton,
)

from csm_core.monitor import excel_import, storage
from csm_core.monitor.base import MonitorResult, MonitorTask
from csm_gui.controllers.monitor_controller import MonitorController
from csm_gui.widgets.monitor_task_dialog import MonitorTaskDialog
from csm_gui.widgets.rank_alert_card import RankAlertCard

logger = logging.getLogger(__name__)


_TYPE_DISPLAY = {
    "zhihu_question": "知乎问题",
    "bilibili_comment": "B 站评论",
    "douyin_comment": "抖音评论",
    "kuaishou_comment": "快手评论",
}


class MonitorPage(QWidget):
    """Main monitor page; owned by MainWindow."""

    # Page-out signal: forwarded by MainWindow to navigate to ArticlePage
    # and prefill the keyword + competitor snippet payload.
    generate_requested = pyqtSignal(dict)

    def __init__(self, controller: MonitorController, parent=None):
        super().__init__(parent)
        self.setObjectName("MonitorPage")
        self._controller = controller
        self._tasks: dict[int, MonitorTask] = {}
        self._latest: dict[int, MonitorResult] = {}
        self._alert_cards: dict[int, RankAlertCard] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(16)

        # Page title.
        title = SubtitleLabel("监测中心", self)
        root.addWidget(title)

        # Alert strip — stacks active alerts vertically. Hidden when
        # empty so it doesn't take up space on a quiet day.
        self._alert_host = QWidget(self)
        self._alert_layout = QVBoxLayout(self._alert_host)
        self._alert_layout.setContentsMargins(0, 0, 0, 0)
        self._alert_layout.setSpacing(8)
        self._alert_host.setVisible(False)
        root.addWidget(self._alert_host)

        # Tab pivot.
        self._pivot = Pivot(self)
        self._pivot.addItem(routeKey="all", text="全部")
        self._pivot.addItem(routeKey="zhihu_question", text="知乎问题")
        self._pivot.addItem(routeKey="comments", text="评论留存")
        self._pivot.setCurrentItem("all")
        self._pivot.currentItemChanged.connect(self._on_pivot_changed)
        root.addWidget(self._pivot)

        # Action toolbar.
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        self._new_btn = PrimaryPushButton(FluentIcon.ADD, "新建任务", self)
        self._new_btn.clicked.connect(self._on_new_task)
        toolbar.addWidget(self._new_btn)

        # Batch-import flow: pick an .xlsx → bulk-create tasks. The
        # template button drops a sample file so the user knows the
        # column layout without consulting docs.
        self._import_btn = PushButton(FluentIcon.DOWNLOAD, "批量导入 Excel", self)
        self._import_btn.clicked.connect(self._on_batch_import)
        toolbar.addWidget(self._import_btn)

        self._template_btn = PushButton(FluentIcon.SAVE_AS, "下载模板", self)
        self._template_btn.clicked.connect(self._on_download_template)
        toolbar.addWidget(self._template_btn)

        self._edit_btn = PushButton(FluentIcon.EDIT, "编辑", self)
        self._edit_btn.clicked.connect(self._on_edit_task)
        self._edit_btn.setEnabled(False)
        toolbar.addWidget(self._edit_btn)

        self._delete_btn = PushButton(FluentIcon.DELETE, "删除", self)
        self._delete_btn.clicked.connect(self._on_delete_task)
        self._delete_btn.setEnabled(False)
        toolbar.addWidget(self._delete_btn)

        self._run_btn = PushButton(FluentIcon.PLAY_SOLID, "立即检测", self)
        self._run_btn.clicked.connect(self._on_run_now)
        self._run_btn.setEnabled(False)
        toolbar.addWidget(self._run_btn)

        toolbar.addStretch(1)

        self._schedule_btn = PushButton(FluentIcon.PLAY, "启动调度", self)
        self._schedule_btn.clicked.connect(self._on_toggle_schedule)
        toolbar.addWidget(self._schedule_btn)

        root.addLayout(toolbar)

        # Task table.
        self._table = QTableWidget(self)
        self._table.setColumnCount(6)
        self._table.setHorizontalHeaderLabels([
            "名称", "类型", "调度", "上次检测", "当前排名", "状态",
        ])
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        h = self._table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        self._table.itemSelectionChanged.connect(self._on_selection_changed)
        self._table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        root.addWidget(self._table, 1)

        # Detail panel — Top-N snapshot of the selected task.
        detail = CardWidget(self)
        d_layout = QVBoxLayout(detail)
        d_layout.setContentsMargins(20, 16, 20, 16)
        d_layout.setSpacing(8)
        self._detail_title = StrongBodyLabel("选中任务后这里显示 Top-N 快照", detail)
        d_layout.addWidget(self._detail_title)
        self._detail_text = TextEdit(detail)
        self._detail_text.setReadOnly(True)
        self._detail_text.setMinimumHeight(160)
        d_layout.addWidget(self._detail_text)
        root.addWidget(detail)

        # Wire controller signals.
        controller.task_started.connect(self._on_task_started)
        controller.task_finished.connect(self._on_task_finished)
        controller.task_failed.connect(self._on_task_failed)
        controller.task_alert.connect(self._on_task_alert)
        controller.scheduling_changed.connect(self._on_scheduling_changed)

        self._on_scheduling_changed(controller.is_scheduling())
        self.refresh()

    # ── Public API ─────────────────────────────────────────────────────────
    def refresh(self) -> None:
        """Reload tasks + latest results from storage and repaint."""
        try:
            tasks = storage.list_tasks()
        except Exception:
            logger.exception("monitor refresh: list_tasks failed")
            return
        self._tasks = {t.id: t for t in tasks if t.id is not None}
        self._latest.clear()
        for tid in self._tasks:
            r = storage.latest_result(tid)
            if r is not None:
                self._latest[tid] = r
        self._repaint_table()

    # ── Toolbar handlers ───────────────────────────────────────────────────
    def _on_new_task(self) -> None:
        dlg = MonitorTaskDialog(self)
        if not dlg.exec():
            return
        try:
            task = dlg.to_task()
        except ValueError as e:
            self._error(str(e))
            return
        try:
            storage.create_task(task)
        except Exception as e:
            self._error(f"保存失败：{e}")
            return
        self._info("已创建任务")
        self.refresh()

    def _on_batch_import(self) -> None:
        """Pick an .xlsx, bulk-create tasks via storage.create_task.

        We persist *all* parsable rows even when some rows have errors —
        the InfoBar surfaces error counts so the user can fix the rejected
        rows in their spreadsheet and re-import. ``create_task`` is upsert
        on (type, target_url), so re-importing a fixed file does the
        right thing automatically.
        """
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择批量导入 Excel",
            "",
            "Excel 文件 (*.xlsx *.xlsm)",
        )
        if not path:
            return
        try:
            report = excel_import.parse_excel(path)
        except Exception as e:
            logger.exception("excel parse failed")
            self._error(f"读取 Excel 失败：{e}")
            return

        saved = 0
        for task in report.tasks:
            try:
                storage.create_task(task)
                saved += 1
            except Exception as e:
                report.errors.append((0, f"保存任务「{task.name}」失败：{e}"))
        self.refresh()

        if saved and not report.errors:
            self._info(f"已导入 {saved} 个任务")
            return
        # Mixed / failure path: show a MessageBox with the per-row errors
        # so the user can copy them out, fix the file, and re-import.
        if report.errors:
            err_lines = [f"第 {row} 行：{msg}" for row, msg in report.errors[:20]]
            extra = (
                f"\n... 还有 {len(report.errors) - 20} 条错误未列出"
                if len(report.errors) > 20 else ""
            )
            head = (
                f"已导入 {saved} 个任务，{len(report.errors)} 行失败：\n\n"
                if saved else f"导入失败，共 {len(report.errors)} 行错误：\n\n"
            )
            box = MessageBox("批量导入结果", head + "\n".join(err_lines) + extra, self.window())
            box.cancelButton.hide()
            box.yesButton.setText("我知道了")
            box.exec()
        elif saved == 0:
            self._info("文件中没有可导入的任务")

    def _on_download_template(self) -> None:
        """Drop a sample .xlsx the user can edit and re-import."""
        path, _ = QFileDialog.getSaveFileName(
            self,
            "保存模板",
            "monitor_tasks_template.xlsx",
            "Excel 文件 (*.xlsx)",
        )
        if not path:
            return
        try:
            excel_import.write_template(path)
        except Exception as e:
            logger.exception("excel template write failed")
            self._error(f"模板生成失败：{e}")
            return
        self._info(f"模板已保存到：{path}")

    def _on_edit_task(self) -> None:
        task = self._selected_task()
        if not task:
            return
        dlg = MonitorTaskDialog(self, task=task)
        if not dlg.exec():
            return
        try:
            updated = dlg.to_task()
        except ValueError as e:
            self._error(str(e))
            return
        try:
            storage.update_task(updated)
        except Exception as e:
            self._error(f"保存失败：{e}")
            return
        self._info("已更新任务")
        self.refresh()

    def _on_delete_task(self) -> None:
        task = self._selected_task()
        if not task or task.id is None:
            return
        # MessageBox with title + body; FluentIcon glyph appears via the
        # qfluentwidgets default — no emoji or unicode warning sign.
        box = MessageBox("删除任务", f"确认删除任务「{task.name}」？历史结果将一并清除。", self.window())
        if not box.exec():
            return
        try:
            storage.delete_task(task.id)
        except Exception as e:
            self._error(f"删除失败：{e}")
            return
        self._info("已删除")
        self.refresh()

    def _on_run_now(self) -> None:
        task = self._selected_task()
        if not task or task.id is None:
            return
        if not self._controller.run_now(task.id):
            self._info("该任务正在执行")
            return
        self._info(f"已启动检测：{task.name}")

    def _on_toggle_schedule(self) -> None:
        if self._controller.is_scheduling():
            self._controller.stop_scheduling()
        else:
            self._controller.start_scheduling()

    # ── Controller signal handlers ─────────────────────────────────────────
    def _on_task_started(self, task_id: int) -> None:
        # Update only the status cell to avoid blowing away the
        # selection. Cheap because the table is small.
        row = self._row_for(task_id)
        if row >= 0:
            self._set_status_cell(row, "运行中", FluentIcon.SYNC)

    def _on_task_finished(self, result: MonitorResult) -> None:
        self._latest[result.task_id] = result
        # Reload the task to pick up updated last_check_at / last_status.
        t = storage.get_task(result.task_id)
        if t and t.id is not None:
            self._tasks[t.id] = t
        self._repaint_table()
        # If the selected row finished, refresh the detail panel.
        sel = self._selected_task()
        if sel and sel.id == result.task_id:
            self._update_detail(result)

    def _on_task_failed(self, task_id: int, message: str) -> None:
        row = self._row_for(task_id)
        if row >= 0:
            self._set_status_cell(row, "失败", FluentIcon.CANCEL)
        self._error(f"任务执行失败：{message[:120]}")

    def _on_task_alert(self, task_id: int, result: MonitorResult) -> None:
        # Stack a new alert card above the table. The card carries the
        # prefill payload that the "生成对标内容" button will hand back
        # to MainWindow via ``generate_requested``.
        if task_id in self._alert_cards:
            return
        task = self._tasks.get(task_id)
        if task is None:
            return
        rank_text = self._format_alert_text(task, result)
        prefill = self._build_prefill(task, result)
        card = RankAlertCard(task_id, task.name, rank_text, prefill, self)
        card.generate_requested.connect(self._on_alert_generate)
        card.dismissed.connect(self._on_alert_dismissed)
        self._alert_layout.addWidget(card)
        self._alert_cards[task_id] = card
        self._alert_host.setVisible(True)

    def _on_alert_generate(self, task_id: int, prefill: dict[str, Any]) -> None:
        # Bubble up to MainWindow so it can navigate to ArticlePage.
        self.generate_requested.emit(prefill)
        self._on_alert_dismissed(task_id)

    def _on_alert_dismissed(self, task_id: int) -> None:
        card = self._alert_cards.pop(task_id, None)
        if card is not None:
            card.deleteLater()
        if not self._alert_cards:
            self._alert_host.setVisible(False)

    def _on_scheduling_changed(self, active: bool) -> None:
        if active:
            self._schedule_btn.setIcon(FluentIcon.PAUSE)
            self._schedule_btn.setText("停止调度")
        else:
            self._schedule_btn.setIcon(FluentIcon.PLAY)
            self._schedule_btn.setText("启动调度")

    # ── Table plumbing ─────────────────────────────────────────────────────
    def _repaint_table(self) -> None:
        active_pivot = self._pivot.currentRouteKey() or "all"
        rows = []
        for tid, task in sorted(self._tasks.items()):
            if active_pivot == "zhihu_question" and task.type != "zhihu_question":
                continue
            if active_pivot == "comments" and not task.type.endswith("_comment"):
                continue
            rows.append(task)
        self._table.setRowCount(len(rows))
        for r, task in enumerate(rows):
            self._set_cell(r, 0, task.name)
            self._set_cell(r, 1, _TYPE_DISPLAY.get(task.type, task.type))
            self._set_cell(r, 2, task.schedule_cron)
            self._set_cell(r, 3, _format_time(task.last_check_at))
            latest = self._latest.get(task.id) if task.id else None
            if latest is None:
                rank_str = "—"
            elif latest.rank == -1:
                rank_str = "未上榜"
            else:
                rank_str = f"#{latest.rank}"
            self._set_cell(r, 4, rank_str)
            status, icon = self._status_for(task, latest)
            self._set_status_cell(r, status, icon)
            # Stash the task id on column 0 for selection lookup.
            item = self._table.item(r, 0)
            if item:
                item.setData(Qt.ItemDataRole.UserRole, task.id)

    def _set_cell(self, row: int, col: int, text: str) -> None:
        item = QTableWidgetItem(text)
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self._table.setItem(row, col, item)

    def _set_status_cell(self, row: int, text: str, icon: FluentIcon) -> None:
        host = QWidget()
        layout = QHBoxLayout(host)
        layout.setContentsMargins(8, 0, 8, 0)
        layout.setSpacing(6)
        ic = IconWidget(icon, host)
        ic.setFixedSize(14, 14)
        layout.addWidget(ic)
        layout.addWidget(BodyLabel(text, host))
        layout.addStretch(1)
        self._table.setCellWidget(row, 5, host)

    def _row_for(self, task_id: int) -> int:
        for r in range(self._table.rowCount()):
            item = self._table.item(r, 0)
            if item and item.data(Qt.ItemDataRole.UserRole) == task_id:
                return r
        return -1

    def _selected_task(self) -> MonitorTask | None:
        idxs = self._table.selectionModel().selectedRows()
        if not idxs:
            return None
        item = self._table.item(idxs[0].row(), 0)
        if item is None:
            return None
        tid = item.data(Qt.ItemDataRole.UserRole)
        return self._tasks.get(tid) if tid else None

    def _on_selection_changed(self) -> None:
        task = self._selected_task()
        has = task is not None
        self._edit_btn.setEnabled(has)
        self._delete_btn.setEnabled(has)
        self._run_btn.setEnabled(has)
        if not has:
            self._detail_title.setText("选中任务后这里显示 Top-N 快照")
            self._detail_text.clear()
            return
        latest = self._latest.get(task.id) if task and task.id else None
        if latest is None:
            self._detail_title.setText(f"{task.name} — 暂无检测记录")
            self._detail_text.clear()
        else:
            self._update_detail(latest)

    def _on_pivot_changed(self, _: str) -> None:
        self._repaint_table()

    # ── Detail panel rendering ─────────────────────────────────────────────
    def _update_detail(self, result: MonitorResult) -> None:
        task = self._tasks.get(result.task_id)
        title = task.name if task else f"任务 #{result.task_id}"
        self._detail_title.setText(f"{title} — 最近一次快照")
        m = result.metric or {}
        lines: list[str] = []
        if task and task.type == "zhihu_question":
            lines.append(f"目标品牌词：{m.get('target_brand', '')}")
            lines.append(f"检测范围：Top {m.get('top_n', 10)}")
            lines.append("")
            for ans in m.get("answers", []):
                hit = "★" if ans.get("matches_brand") else "  "
                preview = (ans.get("content_preview") or "").replace("\n", " ")
                lines.append(
                    f"{hit} #{ans.get('rank')} {ans.get('author', '')} · 赞{ans.get('voteup_count', 0)}"
                )
                if preview:
                    lines.append(f"     {preview}")
        else:
            lines.append(f"自发评论：{m.get('my_comment_text', '')}")
            lines.append(
                f"匹配：{'是' if m.get('matched') else '否'}"
                f"，相似度 {m.get('similarity', 0):.2f}"
                f"，热评 Top {m.get('top_n', 10)}"
            )
            if m.get("matched_text"):
                lines.append(f"匹配评论：{m['matched_text']}")
            lines.append("")
            for c in m.get("hot_comments", []):
                lines.append(
                    f"#{c.get('rank')} {c.get('author', '')} · 赞{c.get('likes', 0)}"
                )
                lines.append(f"     {(c.get('text') or '').strip()[:200]}")
        self._detail_text.setPlainText("\n".join(lines))

    # ── Misc helpers ───────────────────────────────────────────────────────
    @staticmethod
    def _status_for(task: MonitorTask, latest: MonitorResult | None) -> tuple[str, FluentIcon]:
        if latest is None:
            return ("未运行", FluentIcon.INFO)
        if latest.status == "ok":
            return ("正常", FluentIcon.ACCEPT)
        if latest.status == "risk_control":
            return ("风控暂停", FluentIcon.IOT)
        if latest.status == "failed":
            return ("失败", FluentIcon.CANCEL)
        return (latest.status, FluentIcon.INFO)

    @staticmethod
    def _format_alert_text(task: MonitorTask, result: MonitorResult) -> str:
        m = result.metric or {}
        if task.type == "zhihu_question":
            top_n = m.get("top_n", 10)
            if result.rank == -1:
                return f"品牌词「{m.get('target_brand', '')}」未出现在 Top {top_n} 回答中。"
            return f"品牌词「{m.get('target_brand', '')}」当前排名 #{result.rank}（已跌出 Top {top_n}）。"
        if result.rank == -1:
            return f"自发评论已脱离热评 Top {m.get('top_n', 10)}。"
        return f"自发评论排名 #{result.rank}，已跌出 Top {m.get('top_n', 10)} 阈值。"

    @staticmethod
    def _build_prefill(task: MonitorTask, result: MonitorResult) -> dict[str, Any]:
        """Construct the keyword + competitor-snippet payload that the
        ArticlePage prefill receives."""
        m = result.metric or {}
        if task.type == "zhihu_question":
            keyword = m.get("target_brand", "") or task.name
            competitor_snippets = []
            for ans in m.get("answers", []):
                snippet = ans.get("content_preview") or ""
                if snippet:
                    competitor_snippets.append({
                        "rank": ans.get("rank"),
                        "author": ans.get("author"),
                        "snippet": snippet,
                    })
            return {
                "source": "monitor",
                "task_id": task.id,
                "keyword": keyword,
                "competitor_snippets": competitor_snippets,
                "context_note": (
                    f"知乎问题「{task.name}」中品牌词当前排名："
                    f"{'未上榜' if result.rank == -1 else f'#{result.rank}'}"
                ),
            }
        # Comment-platform alert: less interesting for prefill, but still
        # surface the matched text + hot list as context.
        return {
            "source": "monitor",
            "task_id": task.id,
            "keyword": m.get("my_comment_text", "") or task.name,
            "competitor_snippets": [
                {"rank": c.get("rank"), "author": c.get("author"), "snippet": c.get("text")}
                for c in m.get("hot_comments", [])
            ],
            "context_note": f"{_TYPE_DISPLAY.get(task.type, task.type)}「{task.name}」评论留存预警",
        }

    def _info(self, message: str) -> None:
        InfoBar.success(
            "提示", message, duration=2000,
            position=InfoBarPosition.TOP, parent=self.window(),
        )

    def _error(self, message: str) -> None:
        InfoBar.error(
            "错误", message, duration=4000,
            position=InfoBarPosition.TOP, parent=self.window(),
        )


def _format_time(dt) -> str:
    if not dt:
        return "—"
    try:
        return dt.strftime("%m-%d %H:%M")
    except Exception:
        return str(dt)
