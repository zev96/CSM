from csm_core.config import MonitorConfig


def test_data_source_mode_defaults_local():
    c = MonitorConfig()
    assert c.data_source_mode == "local"
    assert c.tikhub_base_url == "https://api.tikhub.dev"
    assert c.tikhub_video_endpoint == "app"
    assert c.tikhub_zhihu_limit == 20


def test_data_source_mode_accepts_api():
    c = MonitorConfig(data_source_mode="tikhub_api")
    assert c.data_source_mode == "tikhub_api"


def test_mining_data_source_mode_defaults_to_tikhub():
    from csm_core.config import AppConfig
    assert AppConfig().mining_data_source_mode == "tikhub_api"


def test_mining_data_source_mode_accepts_local_only():
    import pytest
    from pydantic import ValidationError
    from csm_core.config import AppConfig
    assert AppConfig(mining_data_source_mode="local").mining_data_source_mode == "local"
    with pytest.raises(ValidationError):
        AppConfig(mining_data_source_mode="browser")
