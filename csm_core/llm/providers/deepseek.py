"""DeepSeek provider (OpenAI-compatible API)."""
from __future__ import annotations
from dataclasses import dataclass
from .openai_compat import OpenAICompatClient


@dataclass
class DeepSeekClient(OpenAICompatClient):
    model: str = "deepseek-chat"
    base_url: str = "https://api.deepseek.com/v1"
