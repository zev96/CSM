"""OpenAI GPT provider."""
from __future__ import annotations
from dataclasses import dataclass
from .openai_compat import OpenAICompatClient


@dataclass
class OpenAIClient(OpenAICompatClient):
    model: str = "gpt-4o"
    base_url: str = "https://api.openai.com/v1"
