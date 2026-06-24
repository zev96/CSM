from csm_core.factcheck import check_facts


def test_out_of_whitelist_number_flagged():
    r = check_facts("吸力高达250AW。", allowed_numbers={220.0}, allowed_certs=set())
    assert r.ok is False
    assert len(r.violations) == 1
    v = r.violations[0]
    assert v.kind == "number" and v.value == "250AW"
    assert v.sentence == "吸力高达250AW"


def test_faithful_numbers_not_flagged():
    text = "吸力220AW，约60%除螨率，12万转电机，1700L/min。"
    r = check_facts(
        text, allowed_numbers={220.0, 60.0, 120000.0, 1700.0}, allowed_certs=set(),
    )
    assert r.ok is True and r.violations == []


def test_bare_counts_never_flagged_even_if_absent():
    r = check_facts("推荐3款，综合第1名。", allowed_numbers=set(), allowed_certs=set())
    assert r.ok is True


def test_fabricated_cert_flagged_known_cert_passes():
    r = check_facts(
        "通过 CE 与 CCC 认证。", allowed_numbers=set(), allowed_certs={"CE"},
    )
    assert r.ok is False
    assert [v.value for v in r.violations] == ["CCC"]


def test_multiple_violations_across_sentences():
    r = check_facts(
        "吸力300AW。噪音55dB。", allowed_numbers={220.0}, allowed_certs=set(),
    )
    assert {v.value for v in r.violations} == {"300AW", "55dB"}
