"""Kimi (Moonshot) provider via the OpenAI-compatible endpoint."""
from __future__ import annotations
from dataclasses import dataclass
from .openai_compat import OpenAICompatClient


@dataclass
class KimiClient(OpenAICompatClient):
    model: str = "moonshot-v1-8k"
    base_url: str = "https://api.moonshot.cn/v1"
