from csm_core.mining.platforms._common import parse_int_count, parse_duration
from csm_core.mining.models import SearchOutcome


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


# ── SearchOutcome.status_detail field ────────────────────────────────────────

def test_search_outcome_status_detail_defaults_to_none():
    outcome = SearchOutcome(platform="douyin", status="done", cards_emitted=5)
    assert outcome.status_detail is None


def test_search_outcome_status_detail_can_be_set():
    outcome = SearchOutcome(
        platform="douyin",
        status="risk_control",
        cards_emitted=0,
        status_detail="dom: #captcha-mask",
    )
    assert outcome.status == "risk_control"
    assert outcome.status_detail == "dom: #captcha-mask"


def test_search_outcome_error_message_and_status_detail_independent():
    outcome = SearchOutcome(
        platform="bilibili",
        status="needs_login",
        cards_emitted=0,
        error_message="no cookie",
        status_detail="page redirected to login wall: https://passport.bilibili.com/login",
    )
    assert outcome.error_message == "no cookie"
    assert "passport.bilibili.com" in (outcome.status_detail or "")
