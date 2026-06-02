def test_geo_query_in_tasktype_literal():
    from csm_core.monitor.base import TaskType
    import typing
    assert "geo_query" in typing.get_args(TaskType)


def test_geo_query_in_adapter_registry():
    from csm_core.monitor.platforms import ALL
    assert "geo_query" in ALL
    assert ALL["geo_query"].platform == "geo_query"


def test_geo_adapter_has_fetch():
    from csm_core.monitor.platforms import ALL
    assert hasattr(ALL["geo_query"], "fetch")
