"""跨平台共享的 User-Agent 池。

从 zhihu_question.py 抽出来，因为百度 adapter 也需要同款配色。
保留同一份池意味着改一处 UA、所有 adapter 同时生效。

只放近期 Chrome 桌面 UA —— 移动端、Edge 老版本、IE 都不在我们的爬取目标里，
反爬端见到那些反而更可疑。
"""
from __future__ import annotations

import threading


# Chrome 120-121 桌面 + 一个 Edge —— 多个 minor 版本错开签名，避免同一池
# 里两个 task 用一模一样的 UA。
UA_POOL: tuple[str, ...] = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
)


class UARotator:
    """单线程内 UA 轮换。多线程各自拿一个 rotator，互不干扰。"""

    def __init__(self) -> None:
        self._idx = 0
        self._lock = threading.Lock()

    def next(self) -> str:
        with self._lock:
            ua = UA_POOL[self._idx % len(UA_POOL)]
            self._idx += 1
            return ua
