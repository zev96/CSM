from csm_core.factcheck.extract import (
    extract_number_mentions, extract_certs, split_sentences,
)


def test_only_unit_bearing_numbers_extracted():
    vals = [v for v, _ in extract_number_mentions("推荐3款，吸力250AW，第1名，2024年")]
    assert 250.0 in vals
    assert 3.0 not in vals      # 「3款」是计数词，不抽
    assert 1.0 not in vals      # 「第1名」不抽
    assert 2024.0 not in vals   # 「2024年」不抽


def test_wan_expanded_and_percent_and_compound_unit():
    vals = {v for v, _ in extract_number_mentions("12万转电机，效率约60%，气流1700L/min")}
    assert vals == {120000.0, 60.0, 1700.0}


def test_unit_longest_match_AW_not_W():
    mentions = extract_number_mentions("250AW")
    assert mentions == [(250.0, "250AW")]


def test_raw_token_preserved_for_review():
    mentions = extract_number_mentions("噪音70dB")
    assert mentions[0][1] == "70dB"


def test_extract_certs_word_boundaried_and_deduped():
    certs = extract_certs("通过 CE、FCC 认证，国家3C认证，再拿 CE")
    assert certs == ["CE", "FCC", "3C"]      # 去重 + 保序
    assert extract_certs("CELLULAR 的 CELL") == []   # 不在词内误命中 CE


def test_split_sentences():
    assert split_sentences("一句。两句！三句\n四句") == ["一句", "两句", "三句", "四句"]
