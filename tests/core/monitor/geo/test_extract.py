from csm_core.monitor.geo.models import GeoAnswer, Citation
from csm_core.monitor.geo.extract import extract


class FakeClient:
    def __init__(self, payload: str):
        self._payload = payload
        self.last_user = ""

    def complete(self, *, system: str, user: str, temperature=None) -> str:
        self.last_user = user
        return self._payload


def test_extract_parses_llm_json():
    payload = '''{"mentioned": true, "target_rank": 2, "sentiment": "pos",
      "recommended": [{"name":"比亚迪","position":1},{"name":"小鹏","position":2}],
      "summary": "小鹏智驾被正面推荐"}'''
    ans = GeoAnswer(platform="tongyi", keyword="新能SUV",
                    answer_text="推荐比亚迪、小鹏……",
                    citations=[Citation(url="https://zhuanlan.zhihu.com/p/1", title="知乎文")])
    ext = extract(ans, brand="小鹏", aliases=["XPeng"], client=FakeClient(payload))
    assert ext.mentioned is True
    assert ext.target_rank == 2
    assert ext.recommended[1].is_target is True          # 「小鹏」被标 target
    assert ext.recommended[0].is_target is False
    # 信源来自 answer，分类已补
    assert ext.citations[0].domain == "zhihu.com"
    assert ext.citations[0].source_type == "知乎"


def test_extract_bad_json_falls_back():
    ans = GeoAnswer(platform="kimi", keyword="k", answer_text="小鹏不错")
    ext = extract(ans, brand="小鹏", aliases=[], client=FakeClient("这不是JSON"))
    assert ext.target_rank == -1
    assert ext.summary.startswith("[抽取失败")
    assert ext.mentioned is True  # heuristic: 小鹏 appears in text


def test_extract_retry_succeeds_on_second_attempt():
    """First call returns bad JSON, the strict-retry call returns good JSON -> parsed, not degraded."""
    payloads = ["not json at all",
                '{"mentioned": true, "target_rank": 1, "sentiment": "pos", "recommended": [], "summary": "ok"}']
    class TwoShot:
        def __init__(self): self.calls = 0
        def complete(self, *, system, user, temperature=None):
            p = payloads[self.calls]; self.calls += 1; return p
    c = TwoShot()
    ans = GeoAnswer(platform="tongyi", keyword="k", answer_text="小鹏不错")
    ext = extract(ans, brand="小鹏", aliases=[], client=c)
    assert c.calls == 2
    assert ext.target_rank == 1
    assert not ext.summary.startswith("[抽取失败")


def test_extract_llm_exception_degrades():
    """An LLM call that raises (network/timeout) degrades to the heuristic, not a crash."""
    class Boom:
        def complete(self, *, system, user, temperature=None):
            raise RuntimeError("network down")
    ans = GeoAnswer(platform="tongyi", keyword="k", answer_text="小鹏不错")
    ext = extract(ans, brand="小鹏", aliases=[], client=Boom())
    assert ext.target_rank == -1
    assert ext.mentioned is True            # heuristic: 小鹏 appears in text
    assert ext.summary.startswith("[抽取失败")


def test_extract_empty_answer_short_circuits():
    ans = GeoAnswer(platform="kimi", keyword="k", answer_text="", status="empty")
    called = {"n": 0}

    class Counting(FakeClient):
        def complete(self, **kw):
            called["n"] += 1
            return "{}"

    ext = extract(ans, brand="小鹏", aliases=[], client=Counting("{}"))
    assert ext.mentioned is False
    assert called["n"] == 0           # 空答案不调 LLM
