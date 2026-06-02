from csm_core.monitor.geo.alerts import evaluate_geo_alerts


def test_hidden_alert_when_soc_below_20():
    cur = {"soc": 0.1, "first_rank_rate": 0.0, "by_platform": {}}
    alerts = evaluate_geo_alerts(cur, None)
    assert any(a["kind"] == "hidden" for a in alerts)


def test_no_hidden_when_soc_ok():
    cur = {"soc": 0.6, "first_rank_rate": 0.3, "by_platform": {}}
    assert evaluate_geo_alerts(cur, None) == []


def test_first_rank_drop_alert():
    prev = {"soc": 0.6, "first_rank_rate": 0.5, "by_platform": {}}
    cur = {"soc": 0.6, "first_rank_rate": 0.2, "by_platform": {}}  # 0.5->0.2 跌 0.3
    alerts = evaluate_geo_alerts(cur, prev)
    assert any(a["kind"] == "first_drop" for a in alerts)


def test_platform_dropped_alert():
    prev = {"soc": 0.6, "first_rank_rate": 0.4, "by_platform": {"tongyi": {"mentioned": 2}, "kimi": {"mentioned": 1}}}
    cur = {"soc": 0.4, "first_rank_rate": 0.2, "by_platform": {"tongyi": {"mentioned": 2}, "kimi": {"mentioned": 0}}}
    alerts = evaluate_geo_alerts(cur, prev)
    assert any(a["kind"] == "platform_dropped" and "kimi" in a["detail"] for a in alerts)
