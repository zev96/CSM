"""小红书 AI 助手 service（设计稿 §4.6 / P3）.

两个入口：

* :func:`generate_note` —— 输入主题/关键词，引导模型输出 JSON
  ``{title, body, topics}``；service 端解析，解析失败兜底为「整段塞正文」。
* :func:`polish_note` —— 输入正文，返回小红书风改写后的正文。

LLM client 复用 :mod:`llm_factory`（与「文章润色」/mining 同一套设置）。未配置
default provider 时 :class:`LLMConfigError` 透传给路由层包成 503。

P3 只用内置 prompt 常量；用户自定义 prompt（AppConfig.xhs_* + 设置卡）留到 P4。
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from . import config_service, llm_factory

logger = logging.getLogger(__name__)


# ── 内置 prompt（P3 固定，P4 再做可配置）────────────────────────────────────
DEFAULT_GENERATE_SYSTEM = (
    "你是小红书爆款图文笔记写手。根据用户给的主题 / 关键词，创作一篇小红书风格的图文笔记。\n"
    "要求：\n"
    "1) 标题：≤20 字，有钩子，可带 1-2 个 emoji；\n"
    "2) 正文：口语化、分点、适当 emoji 排版、有代入感，结尾自然引导互动（点赞/收藏/关注）；\n"
    "3) 话题：3-6 个，元素不带 # 前缀。\n"
    "只返回一个 JSON 对象，形如 "
    '{"title": "...", "body": "...", "topics": ["...", "..."]}，'
    "不要输出 JSON 以外的任何文字、解释或 markdown 代码块标记。"
)

DEFAULT_POLISH_SYSTEM = (
    "你是小红书文案润色助手。把用户给的正文改写成小红书爆款风格："
    "口语化、亲切、适当分点和 emoji 排版、保留原意不编造事实、结尾自然引导互动。"
    "只返回改写后的正文，不要加任何前后缀、引号、标题或解释。"
)


# ── config helpers ────────────────────────────────────────────────────────
def _resolve_system(custom: str, default: str) -> str:
    """空白自定义 → 内置默认。"""
    return custom if custom.strip() else default


# ── helpers ───────────────────────────────────────────────────────────────
def _strip_code_fence(text: str) -> str:
    """去掉模型偶尔包裹的 ```json ... ``` 代码块围栏，留出纯 JSON 给 json.loads。"""
    t = text.strip()
    if not t.startswith("```"):
        return t
    lines = t.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _loads_or_none(s: str) -> Any:
    """json.loads，失败返回 None（不抛）。"""
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        return None


def _parse_generated(text: str) -> dict[str, Any]:
    """把模型输出解析成 ``{title, body, topics}``。

    依次尝试：① 去围栏后整体解析；② 模型加了前言时，用正则抠出第一个 ``{...}``
    再解析。都失败 → 兜底：整段原文塞进 body（设计稿 §4.6）。字段缺失或类型
    不符 → 该字段取空；topics 仅保留非空字符串元素。
    """
    raw = (text or "").strip()
    data = _loads_or_none(_strip_code_fence(raw))
    if data is None:
        # 模型可能在 JSON 前加「好的，这是你的笔记：」之类前言 → 抠出第一个 {...} 再试。
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            data = _loads_or_none(m.group(0))
    if isinstance(data, dict):
        title = data.get("title")
        body = data.get("body")
        topics = data.get("topics")
        return {
            "title": title if isinstance(title, str) else "",
            "body": body if isinstance(body, str) else "",
            "topics": [t for t in topics if isinstance(t, str) and t.strip()] if isinstance(topics, list) else [],
        }
    return {"title": "", "body": raw, "topics": []}


# ── 公开 API ────────────────────────────────────────────────────────────────
def generate_note(intent: str) -> dict[str, Any]:
    """根据 intent 生成一篇笔记，返回 ``{title, body, topics}``。

    Raises
    ------
    llm_factory.LLMConfigError
        未配置 default provider / api key（路由层捕获 → 503）。
    """
    intent = (intent or "").strip()
    cfg = config_service.load()
    system = _resolve_system(cfg.xhs_generate_prompt, DEFAULT_GENERATE_SYSTEM)
    client = llm_factory.build_client()
    text = client.complete(
        system=system,
        user=f"主题 / 关键词：{intent}",
    )
    return _parse_generated(text)


def polish_note(text: str) -> str:
    """把 ``text`` 润色成小红书风正文。空输入直接返回空（不打 LLM）。

    Raises 同 :func:`generate_note`。
    """
    text = (text or "").strip()
    if not text:
        return ""
    cfg = config_service.load()
    system = _resolve_system(cfg.xhs_polish_prompt, DEFAULT_POLISH_SYSTEM)
    client = llm_factory.build_client()
    out = client.complete(system=system, user=text)
    return (out or "").strip()
