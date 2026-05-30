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
