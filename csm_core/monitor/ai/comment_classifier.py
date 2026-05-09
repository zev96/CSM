"""LLM-based sentiment + brand-relevance scoring for a batch of comments.

The classifier prompts the model with a JSON-structured request: each
comment gets a sentiment bucket (``positive`` | ``neutral`` | ``negative``)
and a 0–10 relevance score against the user's keyword. Returning JSON
makes parsing deterministic — natural-language replies were too easy to
break with a single edge-case comment.

Used opportunistically by the comment-platform worker chain when the
user has flipped ``MonitorConfig.ai_classify_comments`` on. Failures
here are non-fatal: the result is still saved, the enrichment row just
stays empty.
"""
from __future__ import annotations
import json
import logging
from typing import Any

from csm_core.llm.client import LLMClient

logger = logging.getLogger(__name__)


_SYSTEM_PROMPT = (
    "你是一个评论情感与相关度分析助手。"
    "对输入的评论列表，逐条返回 JSON 数组。"
    "每个对象包含字段：index（输入序号）、sentiment（positive/neutral/negative）、"
    "relevance（0-10 整数，相对于给定关键词的相关度）、reason（不超过 30 字的简短理由）。"
    "输出必须是合法 JSON，不要包含 markdown 代码块标记。"
)


def classify(
    client: LLMClient,
    *,
    keyword: str,
    comments: list[dict[str, Any]],
    max_items: int = 30,
) -> dict[str, Any]:
    """Run the classifier on (a slice of) ``comments``.

    Returns a dict with ``items`` (per-comment annotations) and
    ``summary`` (positive/neutral/negative counts). Returns an empty
    dict on hard failure rather than raising — the caller persists the
    result regardless of whether enrichment succeeded.
    """
    if not comments:
        return {}
    sample = comments[:max_items]
    user_payload = {
        "keyword": keyword,
        "comments": [
            {"index": i, "text": (c.get("text") or "")[:200]}
            for i, c in enumerate(sample)
        ],
    }
    prompt = (
        "请分析以下评论，输出 JSON 数组。\n"
        f"输入：{json.dumps(user_payload, ensure_ascii=False)}"
    )
    try:
        raw = client.complete(system=_SYSTEM_PROMPT, user=prompt, temperature=0.2)
    except Exception:
        logger.exception("comment classifier LLM call failed")
        return {}

    items = _parse_json_array(raw)
    if not items:
        return {}

    counts = {"positive": 0, "neutral": 0, "negative": 0}
    for it in items:
        s = it.get("sentiment")
        if s in counts:
            counts[s] += 1
    return {"items": items, "summary": counts, "sample_size": len(sample)}


def _parse_json_array(text: str) -> list[dict[str, Any]]:
    """Tolerant JSON-array parser.

    LLMs occasionally wrap the array in a ```json fence even when
    instructed not to; strip those before parsing. Returns [] on any
    failure rather than raising — partial enrichment beats none.
    """
    text = (text or "").strip()
    if not text:
        return []
    # Strip ```json ... ``` fence if present.
    if text.startswith("```"):
        first_newline = text.find("\n")
        if first_newline != -1:
            text = text[first_newline + 1 :]
        if text.endswith("```"):
            text = text[: -3]
        text = text.strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Best-effort: find the first '[' and last ']' and try again.
        start = text.find("[")
        end = text.rfind("]")
        if start == -1 or end == -1 or end <= start:
            return []
        try:
            data = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return []
    if isinstance(data, list):
        return [d for d in data if isinstance(d, dict)]
    return []
