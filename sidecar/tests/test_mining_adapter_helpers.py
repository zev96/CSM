from csm_core.mining.platforms._common import parse_int_count, parse_duration


def test_parse_int_count_chinese_wan():
    assert parse_int_count("1.2万") == 12_000
    assert parse_int_count("12万") == 120_000


def test_parse_int_count_yi():
    assert parse_int_count("1.5亿") == 150_000_000


def test_parse_int_count_english_k():
    assert parse_int_count("3.4k") == 3_400
    assert parse_int_count("2M") == 2_000_000


def test_parse_int_count_commas():
    assert parse_int_count("12,345") == 12_345


def test_parse_int_count_empty_and_garbage():
    assert parse_int_count("") is None
    assert parse_int_count("--") is None
    assert parse_int_count(None) is None  # type: ignore[arg-type]


def test_parse_duration_mmss():
    assert parse_duration("1:23") == 83


def test_parse_duration_hhmmss():
    assert parse_duration("01:02:03") == 3723


def test_parse_duration_empty():
    assert parse_duration("") is None
    assert parse_duration("abc") is None
