from csm_core.scoring.ai_flavor import ai_flavor_parts

HUMAN = (
    "上周把家里那台老吸尘器换掉了。原因说来好笑：猫毛缠进滚刷，拆了半小时。\n\n"
    "新机器用了十天，地毯上的猫毛一遍过。楼下邻居问我是不是换了保洁阿姨。\n\n"
    "要说缺点也有，尘杯小了点，倒得勤。但对我这种懒人，能少拆一次刷头就是胜利。"
)

AI_HEAVY = (
    "首先，吸力是选购吸尘器的核心指标。其次，续航能力同样值得关注。最后，噪音水平不容忽视。\n\n"
    "总的来说，这款产品表现出色。值得一提的是，它不是简单的清洁工具，而是智能家居的入口。"
    "不仅性能强劲，更在细节处体现匠心。众所周知，除螨需要强吸力。\n\n"
    "总之，综合来看这是一款值得推荐的产品。"
)


def _points(parts, key):
    return next((p.points for p in parts if p.key == key), 0.0)


def test_clean_human_text_low_deduction():
    parts = ai_flavor_parts(HUMAN)
    assert sum(p.points for p in parts) <= 6.0


def test_ai_heavy_text_flags_signals():
    parts = ai_flavor_parts(AI_HEAVY)
    assert _points(parts, "ai_triplet") >= 8.0          # 首先…其次…最后
    assert _points(parts, "ai_connectives") > 0
    assert _points(parts, "ai_parallel") > 0            # 不是…而是 / 不仅…更
    assert _points(parts, "ai_summary") >= 4.0          # 段首「总之」


def test_triplet_capped():
    text = ("首先A。其次B。最后C。" * 5)
    assert _points(ai_flavor_parts(text), "ai_triplet") <= 16.0


def test_connectives_capped():
    text = "首先，" * 200 + "结束。"
    assert _points(ai_flavor_parts(text), "ai_connectives") <= 15.0


def test_extra_words_extend():
    base = ai_flavor_parts("这款产品赋能千家万户。")
    extended = ai_flavor_parts("这款产品赋能千家万户。", extra_words=["赋能"])
    assert _points(extended, "ai_connectives") > _points(base, "ai_connectives")


def test_monotony_uniform_sentences():
    text = "。".join("这是一句长度基本一样的句子啊" for _ in range(12)) + "。"
    assert _points(ai_flavor_parts(text), "monotony") > 0


def test_empty_text_no_parts():
    assert ai_flavor_parts("") == []
