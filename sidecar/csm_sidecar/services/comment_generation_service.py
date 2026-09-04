"""批量评论生成（评论工作流 P2）。

「模板 × 视频分析 → 个性化改写」：对勾选的每条视频，取一条评论模板 +
A 档上下文（元数据 / 预筛存下的前 20 条热评 / AI 速览缓存），让 LLM 改写
成贴合该视频的评论；tier≥2 生成盖楼跟评。产出经 ``ai_flavor_parts``
确定性检查，超阈值自动带违规项重写一次，最终以 review_status='pending'
落库进人工审核队列。

线程模型仿 :mod:`mining_service`：单 worker executor + 全局忙碌位 +
event_bus SSE（队列 key = ``mining-gen-{batch_id}``）。与抓取 executor
互相独立，SQLite WAL 下并行安全。

Prompt 约定同 :mod:`mining_ai_service`：用户自定义存
``AppConfig.mining_rewrite_prompt``，单段 = 替换 system，含 ``---user---``
= 拆 (system, user) 两段。
"""
from __future__ import annotations

import itertools
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, Future
from typing import Any

from csm_core.mining import storage as mining_storage
from csm_core.scoring.ai_flavor import ai_flavor_parts

from . import config_service, llm_factory
from .mining_ai_service import _render, _resolve_prompt
from ..event_bus import bus as event_bus

logger = logging.getLogger(__name__)


# ── Default prompts（spec §3.2 改写规则 7 条）────────────────────────────
DEFAULT_REWRITE_PROMPT_SYSTEM = (
    "你是中文短视频评论改写助手。给定一条「评论模板」和目标视频的信息"
    "（标题/博主/评论区热评样本），把模板改写成一条像真实观众写的评论。规则：\n"
    "1) 保留模板的核心卖点与品牌词，其余全部重写，禁止逐句同义替换；\n"
    "2) 至少引用视频具体元素 1 处（标题里的场景 / 评论区正在聊的点），"
    "让评论像看过这条视频的人写的；\n"
    "3) 模仿评论区热评样本的语言风格（口语程度、emoji 密度、句子长短）；\n"
    "4) 长度与模板相当（±30%）；\n"
    "5) 禁用套话连接词：首先/其次/再者/综上所述/总而言之/值得一提的是/"
    "不难发现/与此同时/一方面…另一方面/不是…而是/不仅…更；\n"
    "6) 不得虚构模板里没有的可证伪细节（使用时长/价格/售后经历）；\n"
    "7) 写第 N 层（N≥2）盖楼跟评时：必须与前几层形成对话感"
    "（补充/追问/附和），不能是独立评论换个位置。\n"
    "只输出评论正文，不要解释、不要加引号。"
)
DEFAULT_REWRITE_PROMPT_USER = (
    "平台={platform} 标题={title} 博主={author} 播放={play_count}\n"
    "视频速览: {summary}\n"
    "评论区热评样本:\n{comments_block}\n"
    "评论模板:\n{template_text}\n"
    "已写楼层:\n{previous_block}\n"
    "写第 {tier} 层。语气提示: {tone_hint}"
)

# ai_flavor 各信号 points 之和 ≥ 该值 → 自动带违规项重写一次；重写后仍
# 超标则保留低分版本，前端按 score 标黄。短评论里一个套话连接词 = 3 分，
# 所以 3.0 ≈「出现任何一个明确 AI 痕迹就重写」。
REWRITE_FLAVOR_THRESHOLD = 3.0

# 热评样本注入上限（条数 / 单条截断），控 prompt 体积。
_COMMENTS_BLOCK_MAX = 10
_COMMENT_TEXT_CAP = 120

_MAX_TIERS = 5  # 评论A–E；腾讯文档实际写入层数由表头「评论X」列数决定（tencent_docs_service）


# ── Batch runner state（仿 mining_service 单 worker + 忙碌位）───────────
_executor: ThreadPoolExecutor | None = None
_active_batch_id: int | None = None
_active_lock = threading.Lock()
_batch_counter = itertools.count(1)
_cancel_events: dict[int, threading.Event] = {}


def init() -> None:
    """Called from sidecar lifespan. Idempotent."""
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="gen-worker")


def shutdown() -> None:
    global _executor
    if _executor is not None:
        _executor.shutdown(wait=False, cancel_futures=True)
        _executor = None


def active_batch_id() -> int | None:
    with _active_lock:
        return _active_batch_id


def cancel_batch(batch_id: int) -> bool:
    ev = _cancel_events.get(batch_id)
    if ev is None:
        return False
    ev.set()
    return True


def event_queue_id(batch_id: int) -> str:
    return f"mining-gen-{batch_id}"


def submit_batch(
    video_ids: list[int],
    tiers_per_video: int = 1,
    template_ids: list[int] | None = None,
    tone_hint: str = "",
) -> int:
    """Queue one generation batch. Returns batch_id.

    Raises
    ------
    RuntimeError("generation busy ...")  已有批次在跑 → 路由映射 409。
    ValueError                            模板不可用（显式 id 不存在 / 模板库空）。
    llm_factory.LLMConfigError            LLM 未配置 → 路由映射 503。
    """
    global _active_batch_id
    if _executor is None:
        raise RuntimeError("comment_generation_service not initialized")
    tiers = max(1, min(int(tiers_per_video), _MAX_TIERS))
    # 提交时就把 client / 模板池备好：配置错误要在 HTTP 请求里立刻 503/400，
    # 而不是批次开跑后才在 SSE 里报。
    client = llm_factory.build_client()
    templates = _resolve_templates(template_ids)

    with _active_lock:
        if _active_batch_id is not None:
            raise RuntimeError(f"generation busy on batch {_active_batch_id}")
        batch_id = next(_batch_counter)
        _active_batch_id = batch_id
    _cancel_events[batch_id] = threading.Event()
    event_bus.create_job(event_queue_id(batch_id))
    fut = _executor.submit(
        _run_batch, batch_id, list(video_ids), tiers, templates, tone_hint, client,
    )
    fut.add_done_callback(lambda f: _on_done(batch_id, f))
    return batch_id


def _on_done(batch_id: int, _future: Future) -> None:
    global _active_batch_id
    with _active_lock:
        if _active_batch_id == batch_id:
            _active_batch_id = None
    _cancel_events.pop(batch_id, None)
    event_bus.finish(event_queue_id(batch_id))


def _resolve_templates(template_ids: list[int] | None) -> list[dict[str, Any]]:
    """显式 id 列表 → 逐个取；空 → 模板库可见模板 Top 50（星标/最近优先）。"""
    if template_ids:
        out: list[dict[str, Any]] = []
        for tid in template_ids:
            tpl = mining_storage.get_template(int(tid))
            if tpl is None:
                raise ValueError(f"template not found: {tid}")
            out.append(tpl)
        return out
    items = mining_storage.list_templates(hidden="0", limit=50)["items"]
    if not items:
        raise ValueError("模板库为空：请先在模板库里添加至少一条评论模板")
    return items


# ── Batch worker ────────────────────────────────────────────────────────
def _run_batch(
    batch_id: int,
    video_ids: list[int],
    tiers: int,
    templates: list[dict[str, Any]],
    tone_hint: str,
    client: Any,
) -> None:
    qid = event_queue_id(batch_id)
    cancel = _cancel_events[batch_id]
    cfg = config_service.load()
    system_tpl, user_tpl = _resolve_prompt(
        cfg.mining_rewrite_prompt,
        DEFAULT_REWRITE_PROMPT_SYSTEM,
        DEFAULT_REWRITE_PROMPT_USER,
    )
    extra_words = list(getattr(getattr(cfg, "scoring", None), "extra_ai_words", []) or [])

    total = len(video_ids)
    generated = 0
    skipped = 0
    failed = 0
    tpl_cursor = 0

    for i, vid in enumerate(video_ids):
        if cancel.is_set():
            break
        ok_tiers = 0
        error = ""
        try:
            video = _fetch_video_context(vid)
            if video is None or video["excluded"]:
                skipped += 1
                error = "视频不存在或已排除"
            else:
                previous: list[str] = _existing_tier_texts(vid, tiers)
                for tier in range(1, tiers + 1):
                    if cancel.is_set():
                        break
                    tpl = templates[tpl_cursor % len(templates)]
                    tpl_cursor += 1
                    try:
                        text, score = _generate_one(
                            client, system_tpl, user_tpl, video, tpl["text"],
                            tier, previous, tone_hint, extra_words,
                        )
                        mining_storage.upsert_ai_comment(
                            vid, tier, text,
                            template_id=tpl["id"], ai_flavor_score=score,
                        )
                        # 覆盖 previous 里同层旧文本，保证后续层引用的是新稿。
                        if len(previous) >= tier:
                            previous[tier - 1] = text
                        else:
                            previous.append(text)
                        ok_tiers += 1
                        generated += 1
                    except mining_storage.TierOccupiedError:
                        # 人工写的 / 已通过的楼层 → 不动，跳过该层。
                        skipped += 1
        except llm_factory.LLMConfigError:
            # 配置在批次中途被清掉 —— 无法继续，整批终止。
            failed += total - i
            error = "llm_not_configured"
            event_bus.publish(qid, "generation.progress", done=i, total=total,
                              video_id=vid, ok_tiers=0, error=error)
            break
        except Exception as e:  # 单视频失败不阻塞整批
            logger.exception("[gen] video %d failed: %s", vid, e)
            failed += 1
            error = str(e)[:200]

        event_bus.publish(
            qid, "generation.progress",
            done=i + 1, total=total, video_id=vid,
            ok_tiers=ok_tiers, error=error,
        )

    event_bus.publish(
        qid, "generation.finished",
        total=total, generated=generated, skipped=skipped, failed=failed,
        cancelled=cancel.is_set(),
    )


def _fetch_video_context(video_id: int) -> dict[str, Any] | None:
    """A 档上下文：元数据 + top_comments 快照 + ai_summary 缓存。"""
    conn = mining_storage.get_conn()
    row = conn.execute(
        "SELECT id, platform, title, author_name, play_count, excluded, "
        "ai_summary, top_comments_json FROM videos WHERE id=?",
        (video_id,),
    ).fetchone()
    if row is None:
        return None
    import json as _json
    try:
        top_comments = _json.loads(row["top_comments_json"]) if row["top_comments_json"] else []
    except ValueError:
        top_comments = []
    return {
        "id": row["id"],
        "platform": row["platform"],
        "title": row["title"] or "",
        "author": row["author_name"] or "",
        "play_count": row["play_count"] if row["play_count"] is not None else "",
        "excluded": bool(row["excluded"]),
        "summary": row["ai_summary"] or "",
        "top_comments": top_comments,
    }


def _existing_tier_texts(video_id: int, up_to: int) -> list[str]:
    """已有楼层文本（tier 升序，截到 up_to），给盖楼 prompt 当上文。"""
    comments = mining_storage.list_comments(video_id)
    by_tier = {c["tier"]: c["text"] for c in comments}
    out: list[str] = []
    for t in range(1, up_to + 1):
        if t in by_tier:
            out.append(by_tier[t])
        else:
            break
    return out


def _comments_block(top_comments: list[dict[str, Any]]) -> str:
    if not top_comments:
        return "（无样本）"
    lines = []
    for c in top_comments[:_COMMENTS_BLOCK_MAX]:
        text = str(c.get("text") or "")[:_COMMENT_TEXT_CAP]
        likes = c.get("likes")
        lines.append(f"- {text}" + (f"（赞{likes}）" if likes else ""))
    return "\n".join(lines)


def flavor_score(text: str, extra_words: list[str] | None = None) -> float:
    """确定性 AI 味总分 = 各信号 points 之和。"""
    return round(sum(p.points for p in ai_flavor_parts(text, extra_words=extra_words)), 1)


def _generate_one(
    client: Any,
    system_tpl: str,
    user_tpl: str,
    video: dict[str, Any],
    template_text: str,
    tier: int,
    previous: list[str],
    tone_hint: str,
    extra_words: list[str],
) -> tuple[str, float]:
    """单条生成 + AI 味检查 + 超阈值自动重写一次。返回 (text, score)。"""
    previous_block = "\n".join(
        f"第 {i + 1} 层: {t}" for i, t in enumerate(previous[: tier - 1])
    ) or "（无）"
    vars_ = {
        "platform": video["platform"],
        "title": video["title"],
        "author": video["author"],
        "play_count": video["play_count"],
        "summary": video["summary"],
        "comments_block": _comments_block(video["top_comments"]),
        "template_text": template_text,
        "tier": tier,
        "previous_block": previous_block,
        "tone_hint": tone_hint or "自然口语",
    }
    rendered_system = _render(system_tpl, vars_)
    rendered_user = _render(user_tpl, vars_)

    text = (client.complete(system=rendered_system, user=rendered_user) or "").strip()
    score = flavor_score(text, extra_words)
    if score < REWRITE_FLAVOR_THRESHOLD:
        return text, score

    # 带着具体违规项重写一次；仍超标则保留分低的版本（审核视图标黄）。
    parts = ai_flavor_parts(text, extra_words=extra_words)
    details = "；".join(f"{p.label}: {p.detail}" for p in parts)
    retry_user = (
        rendered_user
        + f"\n\n上一版评论：{text}\n检查发现 AI 痕迹（{details}）。"
        "请重写这条评论消除这些痕迹，其余要求不变。"
    )
    text2 = (client.complete(system=rendered_system, user=retry_user) or "").strip()
    score2 = flavor_score(text2, extra_words)
    if text2 and score2 < score:
        return text2, score2
    return text, score
