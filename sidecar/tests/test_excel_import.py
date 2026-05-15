"""Excel 批量导入百度 keyword 的回归测试。"""
from csm_core.monitor.excel_import import parse_rows


def test_excel_import_baidu_keyword_row():
    rows = [
        ["类型", "名称", "URL", "关键词", "TopN", "调度"],
        # 百度的 URL 留空（会自动从关键词派生），目标品牌词放在「关键词」列里用 | 分隔
        ["百度关键词", "百度-Claude教程",
         "search:Claude Code 教程", "Claude|Anthropic", 10, "09:00"],
    ]
    report = parse_rows(rows)
    assert report.error_count == 0, report.errors
    assert report.ok_count == 1
    task = report.tasks[0]
    assert task.type == "baidu_keyword"
    assert task.config["search_keyword"] == "Claude Code 教程"
    assert task.config["target_brands"] == ["Claude", "Anthropic"]
    assert task.target_url.startswith("https://www.baidu.com/s?wd=")
    assert task.schedule_cron == "09:00"


def test_excel_import_baidu_label_aliases():
    rows = [
        ["类型", "名称", "URL", "关键词", "TopN", "调度"],
        ["baidu_keyword", "t1", "search:test", "BrandA", 10, "manual"],
        ["baidu", "t2", "search:other", "BrandB", 10, "manual"],
    ]
    report = parse_rows(rows)
    assert report.ok_count == 2, report.errors
    assert all(t.type == "baidu_keyword" for t in report.tasks)
