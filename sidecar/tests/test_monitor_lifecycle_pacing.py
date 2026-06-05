"""锁定：_apply_runtime_settings 把 MonitorConfig 的 pacing/concurrency
推进评论平台的全局 pacer + semaphore（之前只配了 baidu/zhihu）。"""
from __future__ import annotations

import csm_core.browser_infra.rate_limit as rate_limit
from csm_core.config import AppConfig
from csm_core.monitor.rate_limit import get_pacer
from csm_sidecar.services import monitor_lifecycle


def test_apply_runtime_settings_configures_comment_pacing_and_concurrency():
    cfg = AppConfig()
    cfg.monitor.request_delay_min = 2.0
    cfg.monitor.request_delay_max = 4.0
    cfg.monitor.concurrency_per_platform = 3

    monitor_lifecycle._apply_runtime_settings(cfg)

    for platform in ("bilibili_comment", "douyin_comment", "kuaishou_comment"):
        pacer = get_pacer(platform)
        assert pacer.delay_min == 2.0, platform
        assert pacer.delay_max == 4.0, platform
        assert rate_limit._max_concurrent[platform] == 3, platform
