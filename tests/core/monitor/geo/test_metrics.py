# tests/core/monitor/geo/test_metrics.py
from csm_core.monitor.geo.models import GeoCell
from csm_core.monitor.geo import metrics


def _cell(plat, kw, mentioned, rank, sentiment="na"):
    return GeoCell(platform=plat, keyword=kw, mentioned=mentioned, rank=rank, sentiment=sentiment)


def test_share_of_chat_and_bands():
    cells = [_cell("tongyi", "k1", True, 1, "pos"),
             _cell("tongyi", "k2", False, -1),
             _cell("kimi", "k1", False, -1),
             _cell("kimi", "k2", False, -1)]
    agg = metrics.aggregate(cells)
    assert agg["total"] == 4
    assert agg["mentioned"] == 1
    assert agg["soc"] == 0.25
    assert agg["status_band"] == "weak"     # 0.25 -> weak (0.2-0.5 band)
    # 25% -> weak (20%~50%)
    assert metrics.band(0.25) == "weak"
    assert metrics.band(0.1) == "hidden"
    assert metrics.band(0.8) == "strong"


def test_first_rank_rate_denominator_is_total():
    cells = [_cell("tongyi", "k1", True, 1), _cell("tongyi", "k2", True, 3),
             _cell("kimi", "k1", True, 1), _cell("kimi", "k2", False, -1)]
    agg = metrics.aggregate(cells)
    assert agg["first_rank_rate"] == 0.5          # 2 rank==1 / 4 total
    assert agg["first_rank_rate_mentioned"] == 2 / 3  # 2 / 3 mentioned


def test_sentiment_score_mean_over_mentioned():
    cells = [_cell("tongyi", "k1", True, 1, "pos"),
             _cell("tongyi", "k2", True, 2, "neg"),
             _cell("kimi", "k1", True, 1, "neu"),
             _cell("kimi", "k2", False, -1, "na")]
    agg = metrics.aggregate(cells)
    assert agg["sentiment_score"] == 0.0          # (1 + -1 + 0)/3
    assert agg["sentiment_dist"] == {"pos": 1, "neu": 1, "neg": 1}


def test_by_platform_breakdown():
    cells = [_cell("tongyi", "k1", True, 1), _cell("kimi", "k1", False, -1)]
    agg = metrics.aggregate(cells)
    assert agg["by_platform"]["tongyi"]["soc"] == 1.0
    assert agg["by_platform"]["kimi"]["soc"] == 0.0


def test_representative_rank_is_median_of_mentioned():
    cells = [_cell("t", "k1", True, 1), _cell("t", "k2", True, 3), _cell("t", "k3", True, 5),
             _cell("t", "k4", False, -1)]
    assert metrics.representative_rank(cells) == 3
    assert metrics.representative_rank([_cell("t", "k", False, -1)]) == -1
