"""Per-platform monitor adapters. Each module exposes ``ADAPTER`` —
a singleton implementing :class:`csm_core.monitor.base.BaseMonitorAdapter`.
"""
from .zhihu_question import ADAPTER as ZHIHU
from .bilibili_comment import ADAPTER as BILIBILI
from .douyin_comment import ADAPTER as DOUYIN
from .kuaishou_comment import ADAPTER as KUAISHOU

ALL = {
    "zhihu_question": ZHIHU,
    "bilibili_comment": BILIBILI,
    "douyin_comment": DOUYIN,
    "kuaishou_comment": KUAISHOU,
}

__all__ = ["ZHIHU", "BILIBILI", "DOUYIN", "KUAISHOU", "ALL"]
