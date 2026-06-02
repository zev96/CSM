"""Kimi (Moonshot) provider via the OpenAI-compatible endpoint."""
from __future__ import annotations
from dataclasses import dataclass
from .openai_compat import OpenAICompatClient


@dataclass
class KimiClient(OpenAICompatClient):
    model: str = "kimi-k2.6"
    base_url: str = "https://api.moonshot.cn/v1"
