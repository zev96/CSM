# tests/core/monitor/geo/test_metrics.py
from csm_core.monitor.geo.models import GeoCell
from csm_core.monitor.geo import metrics


def _cell(plat, kw, mentioned, rank, sentiment="na", status="ok"):
    return GeoCell(platform=plat, keyword=kw, mentioned=mentioned, rank=rank,
                   sentiment=sentiment, status=status)


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


def test_first_rank_rate_denominator_is_ok_total():
    # 全 ok cell → ok_total == total，分母不变，比率与旧口径一致。
    cells = [_cell("tongyi", "k1", True, 1), _cell("tongyi", "k2", True, 3),
             _cell("kimi", "k1", True, 1), _cell("kimi", "k2", False, -1)]
    agg = metrics.aggregate(cells)
    assert agg["ok_total"] == 4
    assert agg["first_rank_rate"] == 0.5          # 2 rank==1 / 4 ok
    assert agg["first_rank_rate_mentioned"] == 2 / 3  # 2 / 3 mentioned


def test_failed_cell_excluded_from_soc_and_first_rank_denominators():
    # 采集失败的 cell（status=error）是「没问到」不是「问了没提及」，
    # 不该把 SoC / 首推率拉低 —— 分母只数 ok cell。
    cells = [_cell("tongyi", "k1", True, 1, "pos"),
             _cell("kimi", "k1", False, -1, status="error")]
    agg = metrics.aggregate(cells)
    assert agg["total"] == 2
    assert agg["ok_total"] == 1
    assert agg["error_cells"] == 1
    assert agg["mentioned"] == 1
    assert agg["soc"] == 1.0                       # 1 提及 / 1 有效（NOT 0.5）
    assert agg["status_band"] == "strong"          # soc=1.0
    assert agg["first_rank_rate"] == 1.0           # 1 rank==1 / 1 有效（分母 ok_total）
    assert agg["first_rank_rate_mentioned"] == 1.0


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


def test_sentiment_na_excluded_from_score_and_dist():
    """A mentioned cell with sentiment='na' (extraction couldn't classify) must NOT
    be averaged as neutral, and score/dist must agree on the population."""
    cells = [_cell("t", "k1", True, 1, "pos"), _cell("t", "k2", True, 2, "na")]
    agg = metrics.aggregate(cells)
    assert agg["sentiment_score"] == 1.0           # only 'pos' counts; 'na' excluded
    assert agg["sentiment_dist"] == {"pos": 1, "neu": 0, "neg": 0}
    assert sum(agg["sentiment_dist"].values()) == 1  # dist population == classified mentions


def test_representative_rank_is_median_of_mentioned():
    cells = [_cell("t", "k1", True, 1), _cell("t", "k2", True, 3), _cell("t", "k3", True, 5),
             _cell("t", "k4", False, -1)]
    assert metrics.representative_rank(cells) == 3
    assert metrics.representative_rank([_cell("t", "k", False, -1)]) == -1


def test_completeness_measured_over_expected():
    # 完整度(§4.7):实际测到(≥1 ok cell)平台数 / 请求平台数。附加信号,不动分母。
    cells = [_cell("tongyi", "k1", True, 1),                       # tongyi 有 ok
             _cell("tongyi", "k2", False, -1),
             _cell("kimi", "k1", False, -1, status="blocked"),     # kimi 全 blocked = 没测到
             _cell("kimi", "k2", False, -1, status="blocked")]
    agg = metrics.aggregate(cells)
    assert agg["platforms_expected"] == 2            # 默认从 cells 推(tongyi/kimi)
    assert agg["platforms_measured"] == 1            # 只 tongyi 有 ok cell
    assert agg["completeness"] == 0.5


def test_completeness_expected_override_and_no_denominator_change():
    # fetch 以「请求平台数」为 expected(口径以请求为准);且完整度不改 SoC 分母。
    cells = [_cell("tongyi", "k1", True, 1)]
    agg = metrics.aggregate(cells, platforms_expected=5)
    assert agg["platforms_expected"] == 5
    assert agg["platforms_measured"] == 1
    assert agg["completeness"] == 0.2
    assert agg["soc"] == 1.0                          # SoC 仍按 ok_total,不被完整度污染
    assert agg["ok_total"] == 1


def test_completeness_empty_cells():
    agg = metrics.aggregate([])
    assert agg["platforms_expected"] == 0
    assert agg["platforms_measured"] == 0
    assert agg["completeness"] == 0.0
