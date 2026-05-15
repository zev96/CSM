"""UA pool 抽取的回归测试。"""
from csm_core.monitor.drivers import ua_pool


def test_pool_returns_strings():
    assert len(ua_pool.UA_POOL) >= 4
    for ua in ua_pool.UA_POOL:
        assert ua.startswith("Mozilla/5.0")
        assert "Chrome/" in ua


def test_next_ua_rotates():
    rotator = ua_pool.UARotator()
    first = rotator.next()
    second = rotator.next()
    # 第二次跟第一次不同（除非池只有 1 个，但断言池 ≥ 4）
    assert first != second
    # 转一圈回到起点
    pool_size = len(ua_pool.UA_POOL)
    for _ in range(pool_size - 2):
        rotator.next()
    assert rotator.next() == first
