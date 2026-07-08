import json, pathlib
from csm_core.monitor.tikhub.normalize import normalize_zhihu_answers

FIX = pathlib.Path(__file__).parent / "fixtures" / "tikhub_zhihu_answers.json"

def test_unwraps_20_answers_with_content():
    raw = json.loads(FIX.read_text(encoding="utf-8"))
    answers = normalize_zhihu_answers(raw)
    assert len(answers) == 20
    assert all(a["rank"] == i + 1 for i, a in enumerate(answers))   # 连续编号
    assert all(a["content"] and len(a["content"]) > 0 for a in answers)   # 正文非空
    assert answers[0]["author"] == "你的益达"
    assert answers[0]["voteup_count"] == 112

def test_filters_non_answer_cards():
    raw = {"data": {"data": [
        {"type": "question_feed_card", "target_type": "answer",
         "target": {"content": "<p>hi</p>", "author": {"name": "u"}, "voteup_count": 5}},
        {"type": "feed_ad", "target_type": "ad", "target": {}},   # 广告卡必须被过滤
    ]}}
    answers = normalize_zhihu_answers(raw)
    assert len(answers) == 1 and answers[0]["rank"] == 1
