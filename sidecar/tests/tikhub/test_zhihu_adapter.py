import json, pathlib
from unittest.mock import MagicMock
from csm_core.monitor.base import MonitorTask
from csm_core.monitor.tikhub.zhihu_adapter import ZhihuQuestionApiAdapter

FIX = pathlib.Path(__file__).parent / "fixtures" / "tikhub_zhihu_answers.json"

def _task(top_n=10):
    return MonitorTask(type="zhihu_question", name="t",
                       target_url="https://www.zhihu.com/question/23640683",
                       config={"target_brand": "你的益达", "top_n": top_n})

def test_top_n_le_20_single_page_and_matches():
    raw = json.loads(FIX.read_text(encoding="utf-8"))
    client = MagicMock(); client.get.return_value = raw
    a = ZhihuQuestionApiAdapter(client_factory=lambda: client)
    r = a.fetch(_task(top_n=10))
    assert r.status == "ok"
    assert r.rank == 1                       # "你的益达" 命中(作者名),首位
    assert client.get.call_count == 1        # top_n<=20 单页
    assert r.metric["source"] == "tikhub"
    assert r.metric["matched_count"] >= 1

def test_bad_url_fails_gracefully():
    a = ZhihuQuestionApiAdapter(client_factory=lambda: MagicMock())
    t = MonitorTask(type="zhihu_question", name="t", target_url="https://bad/x",
                    config={"target_brand": "x", "top_n": 5})
    r = a.fetch(t)
    assert r.status == "failed"
