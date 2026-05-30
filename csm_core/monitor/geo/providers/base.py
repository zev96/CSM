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
    """按平台名返回 provider 单例。阶段 1 只有 tongyi / kimi。"""
    if platform == "tongyi":
        from .api_tongyi import TongyiProvider
        return TongyiProvider()
    if platform == "kimi":
        from .api_kimi import KimiProvider
        return KimiProvider()
    raise GeoProviderError(f"未知 GEO 平台: {platform}")
