from csm_core.monitor.tikhub.client import paginate
from csm_core.monitor.tikhub.errors import TikHubError
import pytest

def test_stops_at_target():
    pages = [(["a","b"], "c1", True), (["c","d"], "c2", True), (["e"], None, False)]
    it = iter(pages); calls = []
    def page_fn(cursor): calls.append(cursor); return next(it)
    items = paginate(page_fn, target=3, max_pages=10)
    assert items == ["a","b","c"]        # 达 target=3 即停,不抓第 3 页
    assert len(calls) == 2

def test_stops_when_no_more():
    pages = [(["a"], "c1", True), (["b"], None, False)]
    it = iter(pages)
    items = paginate(lambda c: next(it), target=100, max_pages=10)
    assert items == ["a","b"]            # API 报尽即停,不足 target 也停

def test_page_failure_raises_not_partial():
    def page_fn(cursor):
        if cursor is None: return (["a"], "c1", True)
        raise TikHubError("第2页挂了")
    with pytest.raises(TikHubError):
        paginate(page_fn, target=100, max_pages=10)   # 绝不返残缺 ["a"]

def test_max_pages_fuse_raises():
    def page_fn(cursor): return (["x"], "next", True)   # 永远 has_more
    with pytest.raises(TikHubError):
        paginate(page_fn, target=1000, max_pages=3)

def test_stop_predicate_short_circuits():
    # 命中即停:has_more 永远为真,但 stop_predicate 在累积列表含 "MINE" 时返回 True → 立刻停。
    pages = iter([(["a", "b"], "c1", True), (["MINE"], "c2", True), (["z"], "c3", True)])
    calls = []
    def page_fn(cursor): calls.append(cursor); return next(pages)
    items = paginate(page_fn, target=1000, max_pages=10,
                     stop_predicate=lambda acc: any(x == "MINE" for x in acc))
    assert items == ["a", "b", "MINE"]     # 第 2 页拿到 MINE 即停
    assert len(calls) == 2                  # 不翻第 3 页

def test_stop_predicate_none_is_backward_compatible():
    pages = iter([(["a"], "c1", True), (["b"], None, False)])
    items = paginate(lambda c: next(pages), target=100, max_pages=10, stop_predicate=None)
    assert items == ["a", "b"]
