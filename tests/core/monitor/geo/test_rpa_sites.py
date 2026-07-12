from csm_core.monitor.geo.providers.rpa.sites import SITES


def test_specs_carry_stream_timeout_and_new_chat_wait():
    # per-site 超时从 provider 硬编码收进 SiteSpec(deepseek/yuanbao 180s、kimi 120s)。
    assert SITES["deepseek"].stream_timeout_s == 180.0
    assert SITES["kimi"].stream_timeout_s == 120.0
    assert SITES["yuanbao"].stream_timeout_s == 180.0
    # 元宝新会话后需等 composer 渲染(原 provider 里的 600ms)。
    assert SITES["yuanbao"].post_new_chat_wait_ms == 600
    assert SITES["deepseek"].post_new_chat_wait_ms == 0
