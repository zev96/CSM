from csm_core.lint.rules import build_rules
from csm_core.lint.scanner import scan, autofix, build_report

R = build_rules(None)

# U+201C/U+201D — the curly-quote chars that QUOTE_CHARS targets
LQUOTE = "“"
RQUOTE = "”"


def cats(text):
    return [h.category for h in scan(text, R)]


def test_hits_each_category():
    assert "absolute" in cats("这是最佳之选")
    assert "traffic" in cats("加微信领取福利")
    assert "meta_speak" in cats("这其实是软文")
    assert "emoji" in cats("好用😀")
    assert "dash" in cats("高效——安静")
    assert "quote" in cats("所谓" + LQUOTE + "静音" + RQUOTE)


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


def test_autofix_mechanical_only():
    t = "好用😀高效——安静，所谓" + LQUOTE + "静音" + RQUOTE + "模式，业内最佳"
    fixed = autofix(t, R)
    assert "😀" not in fixed
    assert "——" not in fixed and "，安静" in fixed   # —— → ，
    assert LQUOTE not in fixed and RQUOTE not in fixed and "静音模式" in fixed
    assert "最佳" in fixed                            # 判断类不动


def test_autofix_idempotent():
    t = "a😀b——c" + LQUOTE + "最强" + RQUOTE
    assert autofix(autofix(t, R), R) == autofix(t, R)


def test_autofix_collapses_commas():
    # —— 在句末不产生 。，；多个 —— 不堆叠逗号
    assert autofix("结束。——开始", R) == "结束。开始"
    assert autofix("a————b", R) == "a，b"


def test_build_report_shape():
    rep = build_report("最佳😀", R)
    assert any(h.category == "absolute" for h in rep.hits)
    assert "😀" not in rep.fixed_text and "最佳" in rep.fixed_text
