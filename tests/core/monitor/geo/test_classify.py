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


def test_registered_domain_fallback_without_tldextract(monkeypatch):
    """Release bundle may lack tldextract -> _MULTI_SUFFIX fallback must be correct."""
    import csm_core.monitor.geo.classify as classify
    monkeypatch.setattr(classify, "_EXTRACT", None)
    assert classify.registered_domain("https://zhuanlan.zhihu.com/p/123") == "zhihu.com"
    assert classify.registered_domain("https://news.people.com.cn/n1/abc") == "people.com.cn"
    assert classify.registered_domain("https://www.beijing.gov.cn/foo") == "beijing.gov.cn"
    assert classify.registered_domain("http://mp.weixin.qq.com/s/xxx") == "qq.com"
    assert classify.registered_domain("not a url") == ""


def test_canonical_splits_baidu_products():
    from csm_core.monitor.geo.classify import canonical_source
    assert canonical_source("https://baijiahao.baidu.com/s?id=1") == ("baijiahao.baidu.com", "百家号")
    assert canonical_source("https://baike.baidu.com/item/x") == ("baike.baidu.com", "百度百科")
    assert canonical_source("https://zhidao.baidu.com/q/1") == ("zhidao.baidu.com", "百度知道")
    assert canonical_source("https://mp.weixin.qq.com/s/abc") == ("mp.weixin.qq.com", "微信公众号")


def test_canonical_merges_zhihu_subdomains():
    from csm_core.monitor.geo.classify import canonical_source
    assert canonical_source("https://zhuanlan.zhihu.com/p/1") == ("zhihu.com", "知乎")
    assert canonical_source("https://www.zhihu.com/question/1") == ("zhihu.com", "知乎")


def test_authority_table():
    from csm_core.monitor.geo.classify import authority
    assert authority("权威媒体") > authority("知乎") > authority("其他")
    assert authority("未知类型") == authority("其他")


def test_classify_citations_uses_canonical():
    from csm_core.monitor.geo.classify import classify_citations
    from csm_core.monitor.geo.models import Citation
    out = classify_citations([Citation(url="https://baijiahao.baidu.com/s?id=1", title="t")])
    assert out[0].domain == "baijiahao.baidu.com"
    assert out[0].source_type == "百家号"
