"""LLM summarization of Zhihu Top-N answers, written to the user's Vault.

When ``MonitorConfig.ai_summarize_zhihu`` is on, every successful Zhihu
task run ends with a call to :func:`summarize_to_vault`. The summary is
markdown — front-matter + a ranked list of competitor takeaways —
intended to feed back into the existing CSM SEO pipeline as raw
material. The path is returned so the caller can persist it into the
``ai_enrichments.vault_note_path`` column.

The note path lives under ``<vault>/_monitor_intel/{date}_{question_id}.md``
which keeps the auto-generated notes out of the user's hand-curated
top-level structure.
"""
from __future__ import annotations
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from csm_core.llm.client import LLMClient

logger = logging.getLogger(__name__)


_SYSTEM_PROMPT = (
    "你是一个 SEO 内容研究员。给定一个知乎问题及其 Top-N 回答列表，"
    "输出 200-400 字的中文总结。包含：1) 主流观点的 3-5 条要点；"
    "2) 各回答之间的核心分歧；3) 当前回答整体未充分覆盖的角度（用于反向选题）。"
    "使用 Markdown 列表格式。不要复述具体作者名。"
)


def summarize_to_vault(
    client: LLMClient,
    *,
    vault_root: Path,
    task_name: str,
    target_brand: str,
    question_id: str,
    answers: list[dict[str, Any]],
) -> str | None:
    """Summarize ``answers`` and write a markdown note into the vault.

    Returns the relative path the note was saved to (relative to
    ``vault_root``), or None if the summarization or write failed.
    """
    if not answers:
        return None
    try:
        body = _build_user_prompt(task_name, target_brand, answers)
        summary = client.complete(system=_SYSTEM_PROMPT, user=body, temperature=0.4)
    except Exception:
        logger.exception("answer summarizer LLM call failed")
        return None
    if not summary or not summary.strip():
        return None

    intel_dir = vault_root / "_monitor_intel"
    try:
        intel_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        logger.exception("failed to mkdir %s", intel_dir)
        return None

    today = datetime.now().strftime("%Y-%m-%d")
    fname = f"{today}_zhihu_{question_id}.md"
    target = intel_dir / fname
    try:
        target.write_text(_render_note(task_name, target_brand, summary, answers), encoding="utf-8")
    except OSError:
        logger.exception("failed to write %s", target)
        return None
    rel = target.relative_to(vault_root).as_posix()
    return rel


def _build_user_prompt(task_name: str, brand: str, answers: list[dict[str, Any]]) -> str:
    lines = [
        f"问题：{task_name}",
        f"目标品牌词：{brand}",
        "",
        "Top 回答列表：",
    ]
    for ans in answers[:10]:
        rank = ans.get("rank", "?")
        votes = ans.get("voteup_count", 0)
        snippet = (ans.get("content_preview") or "").strip().replace("\n", " ")[:300]
        lines.append(f"#{rank} 赞{votes}：{snippet}")
    return "\n".join(lines)


def _render_note(task_name: str, brand: str, summary: str, answers: list[dict[str, Any]]) -> str:
    """Compose the saved markdown — front matter + summary + raw refs."""
    today = datetime.now().strftime("%Y-%m-%d %H:%M")
    front = (
        "---\n"
        f"title: \"知乎竞品摘要 · {task_name}\"\n"
        "type: monitor_intel\n"
        f"brand: \"{brand}\"\n"
        f"generated_at: \"{today}\"\n"
        "---\n\n"
    )
    body = f"# {task_name}\n\n## LLM 摘要\n\n{summary.strip()}\n\n## 原始回答（Top {len(answers)})\n\n"
    refs = []
    for ans in answers:
        rank = ans.get("rank", "?")
        votes = ans.get("voteup_count", 0)
        author = ans.get("author") or ""
        snippet = (ans.get("content_preview") or "").strip().replace("\n", " ")[:200]
        refs.append(f"- #{rank} · {author} · 赞 {votes}\n  > {snippet}")
    return front + body + "\n".join(refs) + "\n"
