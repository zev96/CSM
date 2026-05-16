"""Excel 批量导入百度 keyword 的回归测试。

新语义：
- URL 列：search:<kw1>|<kw2>|...（pipe 分隔多关键词，search: 前缀）
- 关键词列：<single brand>（单品牌词，无 pipe）
"""
from csm_core.monitor.excel_import import parse_rows


def test_excel_import_baidu_keyword_row():
    rows = [
        ["类型", "名称", "URL", "关键词", "TopN", "调度"],
        # URL 列：多关键词用 pipe 分隔；关键词列：单品牌词
        ["百度关键词", "百度-Claude教程",
         "search:Claude Code 教程|Claude API 使用", "Claude", 10, "09:00"],
    ]
    report = parse_rows(rows)
    assert report.error_count == 0, report.errors
    assert report.ok_count == 1
    task = report.tasks[0]
    assert task.type == "baidu_keyword"
    assert task.config["search_keywords"] == ["Claude Code 教程", "Claude API 使用"]
    assert task.config["target_brand"] == "Claude"
    assert task.target_url.startswith("https://www.baidu.com/s?wd=")
    assert task.schedule_cron == "09:00"


def test_excel_import_baidu_label_aliases():
    rows = [
        ["类型", "名称", "URL", "关键词", "TopN", "调度"],
        ["baidu_keyword", "t1", "search:test1|test2", "BrandA", 10, "manual"],
        ["baidu", "t2", "search:other", "BrandB", 10, "manual"],
    ]
    report = parse_rows(rows)
    assert report.ok_count == 2, report.errors
    assert all(t.type == "baidu_keyword" for t in report.tasks)
    t1 = report.tasks[0]
    assert t1.config["search_keywords"] == ["test1", "test2"]
    assert t1.config["target_brand"] == "BrandA"
    t2 = report.tasks[1]
    assert t2.config["search_keywords"] == ["other"]
    assert t2.config["target_brand"] == "BrandB"
