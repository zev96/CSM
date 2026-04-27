"""Alibaba Qwen provider via DashScope's OpenAI-compatible endpoint.

DashScope exposes a Chat Completions mirror at ``/compatible-mode/v1`` —
we use that so the same client class works across providers.
"""
from __future__ import annotations
from dataclasses import dataclass
from .openai_compat import OpenAICompatClient


@dataclass
class QwenClient(OpenAICompatClient):
    model: str = "qwen-max"
    base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
