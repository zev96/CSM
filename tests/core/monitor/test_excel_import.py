"""Tests for the Excel batch-import parser.

Most tests use ``parse_rows`` to avoid needing real .xlsx fixtures —
the openpyxl-specific code path is exercised in a single round-trip
test that writes the template + parses it back.
"""
from __future__ import annotations
from pathlib import Path

import pytest

from csm_core.monitor.excel_import import (
    ImportReport, parse_excel, parse_rows, write_template,
)


def _header_row() -> list:
    return ["类型", "名称", "URL", "关键词", "TopN", "调度"]


class TestSchema:
    def test_missing_required_columns_reports_error(self):
        # Header row without "URL" — parser should bail with one error
        # row pointing at row 1 and not crash on subsequent rows.
        rows = [["类型", "名称", "关键词"], ["知乎问题", "x", "ACME"]]
        report = parse_rows(rows)
        assert report.ok_count == 0
        assert report.error_count == 1
        assert report.errors[0][0] == 1
        assert "缺少必需列" in report.errors[0][1]

    def test_blank_rows_are_skipped(self):
        rows = [
            _header_row(),
            [None, None, None, None, None, None],
            ["", "", "", "", "", ""],
        ]
        report = parse_rows(rows)
        assert report.ok_count == 0
        assert report.error_count == 0


class TestZhihuRows:
    def test_chinese_label_with_full_fields(self):
        rows = [
            _header_row(),
            ["知乎问题", "知乎-A", "https://www.zhihu.com/question/123", "ACME", 5, "09:30"],
        ]
        report = parse_rows(rows)
        assert report.ok_count == 1
        t = report.tasks[0]
        assert t.type == "zhihu_question"
        assert t.name == "知乎-A"
        assert t.target_url == "https://www.zhihu.com/question/123"
        assert t.config == {"top_n": 5, "target_brand": "ACME"}
        assert t.schedule_cron == "09:30"

    def test_type_code_accepted(self):
        rows = [
            _header_row(),
            ["zhihu_question", "z", "https://www.zhihu.com/question/1", "x", "", ""],
        ]
        report = parse_rows(rows)
        assert report.ok_count == 1
        assert report.tasks[0].config["top_n"] == 10  # default

    def test_default_name_when_blank(self):
        rows = [
            _header_row(),
            ["知乎", "", "https://www.zhihu.com/question/999", "ACME", "", "manual"],
        ]
        report = parse_rows(rows)
        assert report.ok_count == 1
        # Default name embeds the URL tail so the user can tell rows apart.
        assert "999" in report.tasks[0].name


class TestCommentRows:
    def test_bilibili_writes_my_comment_text(self):
        rows = [
            _header_row(),
            ["B站评论", "b1", "https://www.bilibili.com/video/BV111", "支持博主", 20, "manual"],
        ]
        report = parse_rows(rows)
        assert report.ok_count == 1
        t = report.tasks[0]
        assert t.type == "bilibili_comment"
        assert t.config["my_comment_text"] == "支持博主"
        assert "target_brand" not in t.config

    def test_douyin_and_kuaishou_aliases(self):
        rows = [
            _header_row(),
            ["抖音评论", "d", "https://www.douyin.com/video/7300", "好用", 10, ""],
            ["快手评论", "k", "https://www.kuaishou.com/short-video/3xx", "已购", "", ""],
        ]
        report = parse_rows(rows)
        assert report.ok_count == 2
        types = {t.type for t in report.tasks}
        assert types == {"douyin_comment", "kuaishou_comment"}


class TestValidation:
    def test_unknown_type_records_error_with_excel_row_number(self):
        rows = [
            _header_row(),
            ["FaceBook", "x", "https://x", "y", 10, "manual"],
        ]
        report = parse_rows(rows)
        assert report.ok_count == 0
        # Header is row 1, first data row is row 2.
        assert report.errors[0][0] == 2
        assert "未识别的类型" in report.errors[0][1]

    def test_url_must_be_http(self):
        rows = [
            _header_row(),
            ["知乎问题", "z", "ftp://example.com/q/1", "x", 10, "manual"],
        ]
        report = parse_rows(rows)
        assert report.ok_count == 0
        assert "http" in report.errors[0][1]

    def test_blank_keyword_rejected(self):
        rows = [
            _header_row(),
            ["知乎问题", "z", "https://www.zhihu.com/question/1", "", 10, "manual"],
        ]
        report = parse_rows(rows)
        assert report.ok_count == 0
        assert "关键词" in report.errors[0][1] or "自发评论" in report.errors[0][1]

    def test_invalid_schedule_rejected(self):
        rows = [
            _header_row(),
            ["知乎问题", "z", "https://www.zhihu.com/question/1", "x", 10, "随便"],
        ]
        report = parse_rows(rows)
        assert report.ok_count == 0
        assert "调度" in report.errors[0][1]

    def test_partial_failure_keeps_good_rows(self):
        # First row good, second row bad — parser should report 1+1.
        rows = [
            _header_row(),
            ["知乎问题", "ok", "https://www.zhihu.com/question/1", "ACME", 10, "manual"],
            ["未知平台", "bad", "https://x", "y", 10, "manual"],
        ]
        report = parse_rows(rows)
        assert report.ok_count == 1
        assert report.error_count == 1


class TestTemplateRoundTrip:
    def test_write_then_parse(self, tmp_path: Path):
        # Drop a template, immediately re-parse it. Guards against the
        # template growing out of sync with the parser's expectations.
        target = tmp_path / "tpl.xlsx"
        write_template(target)
        assert target.exists()
        report = parse_excel(target)
        # The template ships with 5 sample rows — all should parse.
        assert report.ok_count == 5
        assert report.error_count == 0
