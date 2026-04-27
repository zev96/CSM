"""Google Gemini provider via the OpenAI-compatible endpoint.

Google publishes a Chat Completions facade at
``https://generativelanguage.googleapis.com/v1beta/openai`` so the
shared OpenAI-compat client works without bringing in the
``google-generativeai`` SDK.
"""
from __future__ import annotations
from dataclasses import dataclass
from .openai_compat import OpenAICompatClient


@dataclass
class GeminiClient(OpenAICompatClient):
    model: str = "gemini-2.5-pro"
    base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai"
