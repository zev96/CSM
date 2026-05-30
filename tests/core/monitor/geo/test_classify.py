# tests/core/monitor/geo/test_classify.py
from csm_core.monitor.geo.models import Citation
from csm_core.monitor.geo.classify import registered_domain, classify_source, classify_citations


def test_registered_domain_strips_subdomain():
    assert registered_domain("https://zhuanlan.zhihu.com/p/123") == "zhihu.com"
    assert registered_domain("https://www.xiaohongshu.com/explore/abc") == "xiaohongshu.com"
    assert registered_domain("http://mp.weixin.qq.com/s/xxx") == "qq.com"
    assert registered_domain("not a url") == ""


def test_classify_source_rule_table():
    assert classify_source("zhihu.com") == "知乎"
    assert classify_source("xiaohongshu.com") == "小红书"
    assert classify_source("people.com.cn") == "权威媒体"
    assert classify_source("gov.cn") == "权威媒体"
    assert classify_source("jd.com") == "电商"
    assert classify_source("randomblog.net") == "其他"


def test_classify_citations_fills_domain_and_type():
    out = classify_citations([Citation(url="https://zhuanlan.zhihu.com/p/1", title="t")])
    assert out[0].domain == "zhihu.com"
    assert out[0].source_type == "知乎"
    assert out[0].title == "t"
