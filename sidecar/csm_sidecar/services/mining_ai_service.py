"""AI 速览 + AI 建议（Outreach Phase 3）.

两个入口：

* :func:`summarize_video` — 给视频生成 60-100 字摘要，写入
  ``videos.ai_summary``。``force=True`` 重新生成覆盖。
* :func:`suggest_comment` — 给 composer 用，返回一段建议草稿；不落库。

Prompt 来源：

* 用户在设置里写过 → ``AppConfig.mining_summary_prompt`` /
  ``mining_suggest_prompt``（约定：单段 = system 替换；含 ``---user---``
  分隔符 = 拆 (system, user) 两段全替换）。
* 没写 → 模块顶部 ``DEFAULT_*`` 常量（spec §4.3 那两段）。

LLM client：复用 :mod:`llm_factory`，未配置 default provider 时让
:class:`LLMConfigError` 透传给路由层包成 503。
"""
from __future__ import annotations

import logging
from typing import Any

from csm_core.mining import storage as mining_storage

from . import config_service, llm_factory

logger = logging.getLogger(__name__)


# ── Default prompts (spec §4.3) ─────────────────────────────────────────
DEFAULT_SUMMARY_PROMPT_SYSTEM = (
    "你是中文短视频内容分析助手. 对给定视频信息 (标题/平台/博主/时长/播放量), "
    "输出一段 60-100 字的中文摘要, 告诉读者「这条视频在讲什么 / 适合什么人看 / "
    "评论里可以蹭什么角度」. 直白, 口语, 不复读标题."
)
DEFAULT_SUMMARY_PROMPT_USER = (
    "平台={platform} 标题={title} 博主={author} 时长={duration} 播放={play_count}"
)
DEFAULT_SUGGEST_PROMPT_SYSTEM = (
    "你是中文小红书/抖音评论文案助手. 给定视频信息 + 用户已写的前 N-1 层评论草稿, "
    "写出第 N 层评论草稿 (≤80 字). 要求: 1) 和前面层连贯 (盖楼感); "
    "2) 口语自然不像广告; 3) 适合做种草前奏, 不直接卖."
)
DEFAULT_SUGGEST_PROMPT_USER = (
    "视频: {title} (by {author})\n"
    "已有评论:\n"
    "{previous_block}\n"
    "请写第 {tier} 层."
)

# Separator a user can put inside a custom prompt to split it into
# (system, user) two parts. If absent the whole string is treated as a
# system replacement and the default user template is kept.
_USER_SEPARATOR = "---user---"


# ── Helpers ─────────────────────────────────────────────────────────────
class _SafeDict(dict):
    """Dict subclass that returns "" for missing keys.

    Used by :func:`_render` so a typo in the user-written prompt template
    (e.g. ``{titel}``) renders as empty string instead of blowing up the
    request with a KeyError.
    """

    def __missing__(self, key: str) -> str:  # noqa: D401
        return ""


def _render(template: str, vars: dict[str, Any]) -> str:
    """Render ``template`` against ``vars`` with missing-key tolerance."""
    return template.format_map(_SafeDict(vars))


def _resolve_prompt(custom: str, default_system: str, default_user: str) -> tuple[str, str]:
    """Pick (system, user) templates from custom config or defaults.

    Resolution rules:

    * empty / whitespace-only ``custom`` → return defaults
    * ``custom`` contains ``---user---`` → split into (system, user)
    * otherwise → use ``custom`` as system, default user template stays
    """
    if not custom or not custom.strip():
        return default_system, default_user
    if _USER_SEPARATOR in custom:
        sys_part, user_part = custom.split(_USER_SEPARATOR, 1)
        return sys_part.strip("\n"), user_part.strip("\n")
    return custom, default_user


def _fetch_video(video_id: int) -> dict[str, Any]:
    """Look up the minimal video fields we need (and raise if not found).

    Direct SELECT instead of going through ``list_videos`` because the
    latter applies excluded=0 / pagination filters we don't want for the
    "look up by primary key" path.
    """
    conn = mining_storage.get_conn()
    row = conn.execute(
        "SELECT id, platform, title, author_name, duration_sec, play_count, ai_summary "
        "FROM videos WHERE id=?",
        (video_id,),
    ).fetchone()
    if row is None:
        raise LookupError(f"video not found: {video_id}")
    # row is a sqlite3.Row — supports dict-style indexing
    return {
        "id": row["id"],
        "platform": row["platform"],
        "title": row["title"] or "",
        "author": row["author_name"] or "",
        "duration": row["duration_sec"] if row["duration_sec"] is not None else "",
        "play_count": row["play_count"] if row["play_count"] is not None else "",
        "ai_summary": row["ai_summary"] if row["ai_summary"] is not None else "",
    }


# ── Public API ──────────────────────────────────────────────────────────
def summarize_video(video_id: int, force: bool = False) -> str:
    """Generate (or fetch cached) 60-100 字摘要 for one video.

    Returns the summary string. Side effect: persists the new text to
    ``videos.ai_summary`` (only when freshly generated; cache hits skip
    the write).

    Raises
    ------
    LookupError
        Video row doesn't exist.
    llm_factory.LLMConfigError
        No default provider / api key configured. Caller (route) should
        catch and translate to a 503.
    """
    video = _fetch_video(video_id)
    cached = video["ai_summary"]
    if not force and cached:
        return cached

    cfg = config_service.load()
    system_tpl, user_tpl = _resolve_prompt(
        cfg.mining_summary_prompt,
        DEFAULT_SUMMARY_PROMPT_SYSTEM,
        DEFAULT_SUMMARY_PROMPT_USER,
    )
    vars_ = {
        "platform": video["platform"],
        "title": video["title"],
        "author": video["author"],
        "duration": video["duration"],
        "play_count": video["play_count"],
    }
    rendered_system = _render(system_tpl, vars_)
    rendered_user = _render(user_tpl, vars_)

    client = llm_factory.build_client()
    text = client.complete(system=rendered_system, user=rendered_user)
    text = (text or "").strip()
    mining_storage.set_ai_summary(video_id, text)
    return text


def suggest_comment(
    video_id: int,
    tier: int,
    previous_tiers: list[str],
    tone_hint: str = "",
) -> str:
    """Return an AI-generated draft for the next comment tier.

    Does NOT persist — caller (frontend composer) decides whether to
    save it. ``previous_tiers`` is rendered into a multi-line block
    inside the user message so the model can see the prior conversation.

    Raises the same exceptions as :func:`summarize_video`.
    """
    video = _fetch_video(video_id)

    previous_block = "\n".join(
        f"第 {i + 1} 层: {t}" for i, t in enumerate(previous_tiers)
    )

    cfg = config_service.load()
    system_tpl, user_tpl = _resolve_prompt(
        cfg.mining_suggest_prompt,
        DEFAULT_SUGGEST_PROMPT_SYSTEM,
        DEFAULT_SUGGEST_PROMPT_USER,
    )
    vars_ = {
        "platform": video["platform"],
        "title": video["title"],
        "author": video["author"],
        "tier": tier,
        "previous_block": previous_block,
        "tone_hint": tone_hint or "",
    }
    rendered_system = _render(system_tpl, vars_)
    rendered_user = _render(user_tpl, vars_)

    client = llm_factory.build_client()
    text = client.complete(system=rendered_system, user=rendered_user)
    return (text or "").strip()
