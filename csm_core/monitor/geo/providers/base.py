"""GeoProvider 协议 + 平台 → provider 注册表。"""
from __future__ import annotations
import threading
from typing import Protocol, runtime_checkable

from ..models import GeoAnswer


class GeoProviderError(RuntimeError):
    pass


@runtime_checkable
class GeoProvider(Protocol):
    platform: str
    mode: str  # "api" | "rpa"

    def query(self, keyword: str, *, web_search: bool,
              cancel_token: "threading.Event | None" = None) -> GeoAnswer: ...


def get_provider(platform: str) -> GeoProvider:
    """返回 provider 实例（每次新建，provider 无状态）。API：tongyi / doubao；RPA：deepseek / kimi / yuanbao。"""
    if platform == "tongyi":
        try:
            from .api_tongyi import TongyiProvider
        except ImportError as e:
            raise GeoProviderError(f"tongyi provider 未就绪: {e}") from e
        return TongyiProvider()
    if platform == "kimi":
        # 阶段 3：Kimi 改走 RPA（API 版 annotations 恒 0 拿不到信源）；
        # api_kimi 模块保留供其单测直接 import，但 get_provider 不再走它。
        try:
            from .rpa.kimi import KimiProvider
        except ImportError as e:
            raise GeoProviderError(f"kimi(rpa) provider 未就绪: {e}") from e
        return KimiProvider()
    if platform == "doubao":
        try:
            from .api_doubao import DoubaoProvider
        except ImportError as e:
            raise GeoProviderError(f"doubao provider 未就绪: {e}") from e
        return DoubaoProvider()
    if platform == "deepseek":
        try:
            from .rpa.deepseek import DeepSeekProvider
        except ImportError as e:
            raise GeoProviderError(f"deepseek provider 未就绪: {e}") from e
        return DeepSeekProvider()
    raise GeoProviderError(f"未知 GEO 平台: {platform}")
