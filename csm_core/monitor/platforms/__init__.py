"""Per-platform monitor adapters. Each module exposes ``ADAPTER`` —
a singleton implementing :class:`csm_core.monitor.base.BaseMonitorAdapter`.
"""
from .zhihu_question import ADAPTER as ZHIHU
from .zhihu_search import ADAPTER as ZHIHU_SEARCH
from .bilibili_comment import ADAPTER as BILIBILI
from .douyin_comment import ADAPTER as DOUYIN
from .kuaishou_comment import ADAPTER as KUAISHOU
from .xiaohongshu_comment import ADAPTER as XIAOHONGSHU
from .baidu_keyword import ADAPTER as BAIDU
from .geo_query import ADAPTER as GEO

ALL = {
    "zhihu_question": ZHIHU,
    "zhihu_search": ZHIHU_SEARCH,
    "bilibili_comment": BILIBILI,
    "douyin_comment": DOUYIN,
    "kuaishou_comment": KUAISHOU,
    "xiaohongshu_comment": XIAOHONGSHU,   # 占位:真实抓取固定走 TikHub
    "baidu_keyword": BAIDU,
    "geo_query": GEO,
}

__all__ = ["ZHIHU", "ZHIHU_SEARCH", "BILIBILI", "DOUYIN", "KUAISHOU", "XIAOHONGSHU", "BAIDU", "GEO", "ALL"]
