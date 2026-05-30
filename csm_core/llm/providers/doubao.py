"""Doubao (Volcengine Ark) provider via the OpenAI-compatible endpoint.

注意：Ark 的 ``model`` 字段通常是用户在方舟控制台创建的推理接入点 ID
(ep-xxxxxxxx) 或模型名，需用户在设置页「模型名」里按自己的接入点填。
"""
from __future__ import annotations
from dataclasses import dataclass
from .openai_compat import OpenAICompatClient


@dataclass
class DoubaoClient(OpenAICompatClient):
    model: str = "doubao-pro-32k"
    base_url: str = "https://ark.cn-beijing.volces.com/api/v3"
