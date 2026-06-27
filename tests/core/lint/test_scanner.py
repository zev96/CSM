from csm_core.lint.rules import build_rules
from csm_core.lint.scanner import scan

R = build_rules(None)


def cats(text):
    return [h.category for h in scan(text, R)]


def test_hits_each_category():
    assert "absolute" in cats("这是最佳之选")
    assert "traffic" in cats("加微信领取福利")
    assert "meta_speak" in cats("这其实是软文")
    assert "emoji" in cats("好用😀")
    assert "dash" in cats("高效——安静")
    assert "quote" in cats("所谓“静音”")


def test_absolute_no_false_positive():
    # 温度/序数词不该误报
    assert scan("最近更新了固件", R) == []
    assert scan("最后一步是清洁", R) == []
    assert scan("最初的设计", R) == []


def test_offsets_and_sentence():
    text = "前言。这款是最佳选择！下一句"
    hits = scan(text, R)
    h = next(h for h in hits if h.text == "最佳")
    assert text[h.start:h.end] == "最佳"
    assert h.sentence == "这款是最佳选择"   # 句子边界内、去标点


def test_dedup_longest_wins():
    # "100%安全" 与子串 "100%" 都在词表 → 只留最长
    hits = [h for h in scan("本机100%安全", R) if h.category == "absolute"]
    assert len(hits) == 1 and hits[0].text == "100%安全"


def test_sorted_by_start():
    hits = scan("😀开头最佳结尾加微信", R)
    starts = [h.start for h in hits]
    assert starts == sorted(starts)


def test_empty_text():
    assert scan("", R) == []
    assert scan("普通干净的一段文字。", R) == []
