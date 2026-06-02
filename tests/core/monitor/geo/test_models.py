from csm_core.monitor.geo.models import (
    Citation, GeoAnswer, RecommendedEntity, ClassifiedCitation, GeoExtraction, GeoCell,
)


def test_geo_answer_defaults():
    a = GeoAnswer(platform="tongyi", keyword="新能源SUV", answer_text="…")
    assert a.status == "ok"
    assert a.citations == []
    assert a.raw == {}


def test_geo_extraction_roundtrip():
    e = GeoExtraction(
        mentioned=True, target_rank=2, sentiment="pos",
        recommended=[RecommendedEntity(name="小鹏", position=2, is_target=True)],
        citations=[ClassifiedCitation(url="https://zhihu.com/x", title="t", domain="zhihu.com", source_type="知乎")],
        summary="评价正面",
    )
    assert e.recommended[0].is_target is True
    assert e.citations[0].source_type == "知乎"


def test_geo_cell_carries_everything():
    c = GeoCell(platform="kimi", keyword="新能源SUV", mentioned=False, rank=-1,
                sentiment="na", answer_text="", status="empty", raw={}, citations=[])
    assert c.rank == -1
    assert c.mentioned is False
