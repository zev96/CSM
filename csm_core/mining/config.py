# csm_core/mining/config.py
"""Mining 模块运行时常量：反爬保护 + 同步到 monitor 的默认值。"""
from __future__ import annotations

# 每平台翻页硬上限（页数，不是条目）。
# 抖音风控最严，B 站最松，按经验值排序。
MAX_ATTEMPTS_PER_PLATFORM: dict[str, int] = {
    "douyin": 3,
    "kuaishou": 5,
    "bilibili": 8,
}

# 翻页之间随机延迟范围（秒）。
PAGE_DELAY_RANGE_SEC: tuple[float, float] = (2.0, 5.0)

# sync_to_monitor 的默认值。
DEFAULT_MONITOR_TOP_N: int = 5
# 每次 monitor 任务抓取的评论候选条数上限。
DEFAULT_MONITOR_SCRAPE_TOP_N: int = 150


def get_max_attempts(platform: str) -> int:
    """获取平台默认翻页上限。未知平台 fallback=kuaishou 上限（5）。"""
    return MAX_ATTEMPTS_PER_PLATFORM.get(platform, MAX_ATTEMPTS_PER_PLATFORM["kuaishou"])
