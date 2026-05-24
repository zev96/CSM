"""Mining module routes — jobs, videos, login flow, SSE events."""
from __future__ import annotations

import csv
import io
import logging
import sqlite3
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from csm_core.browser_infra import mining_browser
from csm_core.mining import storage as mining_storage
from csm_core.mining.models import Platform, StartJobRequest

from ..auth import RequireToken
from ..event_bus import bus as event_bus
from ..services import config_service, mining_ai_service, mining_images_service, mining_service
from ..services.llm_factory import LLMConfigError
from ..services.mining_ai_service import (
    DEFAULT_SUGGEST_PROMPT_SYSTEM,
    DEFAULT_SUGGEST_PROMPT_USER,
    DEFAULT_SUMMARY_PROMPT_SYSTEM,
    DEFAULT_SUMMARY_PROMPT_USER,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["mining"], dependencies=[RequireToken])


# ── Jobs ─────────────────────────────────────────────────────────────
@router.post("/api/mining/jobs", status_code=201)
def start_job(body: StartJobRequest) -> dict[str, Any]:
    try:
        job_id = mining_service.submit_job(
            keyword=body.keyword,
            platforms=body.platforms,
            target_per_platform=body.target_per_platform,
        )
    except RuntimeError as e:
        if "busy" in str(e):
            raise HTTPException(status_code=409, detail=str(e))
        raise HTTPException(status_code=500, detail=str(e))
    job = mining_storage.get_job(job_id)
    return {"job_id": job_id, "status": "pending", "job": job}


@router.get("/api/mining/jobs")
def list_jobs(limit: int = Query(default=20, ge=1, le=200)) -> dict[str, Any]:
    items = mining_storage.list_jobs(limit=limit)
    return {"count": len(items), "jobs": items}


@router.get("/api/mining/jobs/{job_id}")
def get_job(job_id: int) -> dict[str, Any]:
    job = mining_storage.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"job not found: {job_id}")
    return job


@router.post("/api/mining/jobs/{job_id}/cancel")
def cancel(job_id: int) -> dict[str, Any]:
    ok = mining_service.cancel_job(job_id)
    if not ok:
        raise HTTPException(status_code=409, detail="job not running or already finished")
    return {"job_id": job_id, "cancelled": True}


@router.delete("/api/mining/jobs/{job_id}")
def delete_job_route(job_id: int) -> dict[str, Any]:
    """Hard-delete a mining job + cascade-clean orphan videos.

    409 if the job is currently running — UX wise the caller should hit
    /cancel first and wait for the SSE finalize, otherwise we'd be
    deleting DB rows underneath a still-writing executor (data race +
    risk that the finalize step re-inserts video_source_keywords for a
    job_id that no longer exists, which would FK-fail loudly).

    404 if the job doesn't exist (already deleted in another tab).
    """
    if mining_service.active_job_id() == job_id:
        raise HTTPException(
            status_code=409,
            detail="job is running — cancel and wait for it to finish before deleting",
        )
    if mining_storage.get_job(job_id) is None:
        raise HTTPException(status_code=404, detail=f"job not found: {job_id}")
    result = mining_storage.delete_job(job_id)
    return {"job_id": job_id, "deleted": True, **result}


@router.get("/api/mining/jobs/{job_id}/events")
async def stream_events(job_id: int):
    """SSE stream of mining.* events for one job."""
    queue_key = f"mining-{job_id}"

    async def event_gen():
        async for event in event_bus.stream(queue_key):
            yield {"event": event.get("kind", "message"), "data": _json(event)}

    return EventSourceResponse(event_gen())


def _json(obj: Any) -> str:
    import json as _j
    return _j.dumps(obj, ensure_ascii=False, default=str)


# ── Videos ───────────────────────────────────────────────────────────
def _parse_ids_param(ids: str | None) -> list[int] | None:
    """Parse a ``?ids=1,2,3`` query string into a list of ints.

    Empty / None → ``None`` (caller falls back to filter-based listing).
    Non-numeric tokens are silently skipped — the export is a convenience
    endpoint, not a transactional API, so we don't 400 on a malformed
    URL the user pasted by hand.
    """
    if not ids:
        return None
    out: list[int] = []
    for tok in ids.split(","):
        tok = tok.strip()
        if not tok:
            continue
        try:
            out.append(int(tok))
        except ValueError:
            continue
    return out or None


def _fetch_comments_by_video(video_ids: list[int]) -> tuple[dict[int, dict[int, dict]], int]:
    """One round-trip: fetch all comments for the given videos.

    Returns (comments_by_video, max_tier) where comments_by_video is
    ``{video_id: {tier: {"text": str, "image_ids": list[str]}}}`` and
    max_tier is 0 if no comments exist for any of the videos.
    """
    if not video_ids:
        return {}, 0
    import json as _json

    conn = mining_storage.get_conn()
    placeholders = ",".join("?" * len(video_ids))
    rows = conn.execute(
        f"SELECT video_id, tier, text, image_ids_json FROM video_comments "
        f"WHERE video_id IN ({placeholders}) ORDER BY video_id, tier",
        list(video_ids),
    ).fetchall()
    by_video: dict[int, dict[int, dict]] = {}
    max_tier = 0
    for r in rows:
        vid = int(r["video_id"])
        tier = int(r["tier"])
        if tier > max_tier:
            max_tier = tier
        try:
            image_ids = _json.loads(r["image_ids_json"]) if r["image_ids_json"] else []
        except (ValueError, TypeError):
            image_ids = []
        by_video.setdefault(vid, {})[tier] = {
            "text": r["text"] or "",
            "image_ids": image_ids,
        }
    return by_video, max_tier


@router.get("/api/mining/videos/export.csv")
def export_csv(
    keyword: str | None = Query(default=None),
    platform: Platform | None = Query(default=None),
    commented: str = Query(default="0", pattern="^(0|1|all)$"),
    q: str | None = Query(default=None),
    ids: str | None = Query(default=None),
):
    selected_ids = _parse_ids_param(ids)
    if selected_ids is not None:
        # Explicit id list overrides the filter params. We still go through
        # list_videos for the source_keywords aggregation, then filter
        # down — small N so an in-Python filter is fine.
        rows, _ = mining_storage.list_videos(
            commented="all", offset=0, limit=10_000,
        )
        wanted = set(selected_ids)
        rows = [r for r in rows if r["id"] in wanted]
    else:
        rows, _ = mining_storage.list_videos(
            keyword=keyword, platform=platform, commented=commented,
            q=q, offset=0, limit=10_000,
        )

    # Single-query comment fetch keyed by the exported video ids only.
    video_ids = [int(r["id"]) for r in rows]
    comments_by_video, max_tier = _fetch_comments_by_video(video_ids)

    # ─────────────────────────────────────────────────────────────────────
    # CSV format —— 按用户「给兼职人填返图」需求改造（2026-05 重排）：
    #   序号 | 平台 | 视频链接
    #   | 第1层评论内容 | 评论图片 | 评论返图
    #   | 第2层评论内容 | 评论图片 | 评论返图
    #   | ...（按 max_tier 展开 N 组三连列）
    #
    # 字段约定：
    #   - 序号：纯顺序号，从 1 开始
    #   - 平台：中文显示（B 站 / 抖音 / 快手 / 知乎），方便兼职人识别
    #   - 视频链接：r["url"]，直接复制到浏览器就能打开（短链 douyin/v.kuaishou
    #     在入库时已展开成 long form）
    #   - 第N层评论内容：tier=N 的 c["text"]，没有就空串
    #   - 评论图片：tier=N 的 image_ids，转成「images/{id}」相对路径（跟旧
    #     版一致；目前 image_ids 是 db 内 image_id 字符串）
    #   - 评论返图：永远空 —— 兼职人填完照片后手动补这一列
    #
    # 旧版的 video_id / title / author / duration / play / like / source_keywords
    # / already_commented / first_seen_at / ai_summary 全部下线（用户场景里
    # 这些字段对兼职人没用，反而让 CSV 变宽难读）。
    # ─────────────────────────────────────────────────────────────────────
    PLATFORM_LABEL_CN = {
        "bilibili": "B 站",
        "douyin": "抖音",
        "kuaishou": "快手",
        "zhihu": "知乎",
    }

    buf = io.StringIO()
    buf.write("﻿")  # BOM so Excel auto-detects UTF-8
    writer = csv.writer(buf)
    header: list[str] = ["序号", "平台", "视频链接"]
    for tier in range(1, max_tier + 1):
        header.append(f"第{tier}层评论内容")
        header.append("评论图片")
        header.append("评论返图")
    writer.writerow(header)

    for seq, r in enumerate(rows, start=1):
        platform_cn = PLATFORM_LABEL_CN.get(r["platform"], r["platform"])
        row: list[str | int] = [seq, platform_cn, r["url"]]
        tiers_for_video = comments_by_video.get(int(r["id"]), {})
        for tier in range(1, max_tier + 1):
            c = tiers_for_video.get(tier)
            if c is None:
                row.append("")          # 第N层评论内容
                row.append("")          # 评论图片
                row.append("")          # 评论返图
            else:
                row.append(c["text"])
                row.append(",".join(f"images/{img}" for img in c["image_ids"]))
                row.append("")          # 评论返图永远空——给兼职人手填
        writer.writerow(row)

    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="mining_videos.csv"'},
    )


@router.get("/api/mining/videos")
def list_videos(
    keyword: str | None = Query(default=None),
    platform: Platform | None = Query(default=None),
    commented: str = Query(default="0", pattern="^(0|1|all)$"),
    q: str | None = Query(default=None),
    job_id: int | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=500),
) -> dict[str, Any]:
    rows, total = mining_storage.list_videos(
        keyword=keyword, platform=platform, commented=commented,
        q=q, job_id=job_id, offset=offset, limit=limit,
    )
    return {"total": total, "offset": offset, "limit": limit, "videos": rows}


@router.delete("/api/mining/videos/{video_id}", status_code=204)
def soft_delete_video(video_id: int) -> None:
    if not mining_storage.soft_delete_video(video_id):
        raise HTTPException(status_code=404, detail="video not found")


# ── Login ────────────────────────────────────────────────────────────
class LoginStartBody(BaseModel):
    platform: Platform


_login_specs = {
    "douyin": ("https://www.douyin.com/", "sessionid"),
    "bilibili": ("https://www.bilibili.com/", "SESSDATA"),
    "kuaishou": ("https://www.kuaishou.com/", "kuaishou.web.cp.api_st"),
}


@router.get("/api/mining/login/status")
def login_status() -> dict[str, Any]:
    return {
        platform: {"logged_in": mining_browser.has_login_cookie(platform)}
        for platform in _login_specs
    }


@router.post("/api/mining/login/{platform}")
def login_start(platform: Platform) -> dict[str, Any]:
    """Launch a headed Patchright window pointing at the platform homepage.

    User logs in manually; cookies persist in the platform's user_data_dir.
    Returns immediately — the browser stays open and is closed when the
    user calls /confirm.

    Idempotency: clicking "登录" twice for the same platform is a normal
    user mistake (window minimized, user thinks it's not there). Instead
    of 409-ing them into a wall, we just report "already open" and they
    can find their existing window. 409 is only raised when ANOTHER
    platform's login is in progress (that's a real conflict — patchright
    serializes one Chromium at a time).
    """
    import threading
    state = _login_state
    with state.lock:
        if state.active_platform == platform:
            # Same-platform retry: window is still open from a previous click.
            return {"platform": platform, "browser_opened": True, "reused": True}
        if state.active_platform is not None:
            raise HTTPException(
                status_code=409,
                detail=f"login already active for {state.active_platform}; finish or call /confirm first",
            )
        state.active_platform = platform
        state.confirm_event = threading.Event()

    def _runner():
        try:
            url, cookie_name = _login_specs[platform]
            with mining_browser.launched_page(platform, headless=False) as page:
                page.goto(url, wait_until="domcontentloaded", timeout=30_000)
                logger.info("login flow opened for %s — waiting up to 10 min for /confirm", platform)
                state.confirm_event.wait(timeout=600)
        except Exception as e:
            logger.exception("login flow for %s crashed: %s", platform, e)
        finally:
            with state.lock:
                state.active_platform = None
                state.confirm_event = None

    threading.Thread(target=_runner, name=f"mining-login-{platform}", daemon=True).start()
    return {"platform": platform, "browser_opened": True, "reused": False}


@router.post("/api/mining/login/{platform}/confirm")
def login_confirm(platform: Platform) -> dict[str, Any]:
    state = _login_state
    with state.lock:
        if state.active_platform != platform or state.confirm_event is None:
            raise HTTPException(status_code=409, detail="no active login flow")
        state.confirm_event.set()
    import time
    for _ in range(20):
        with state.lock:
            if state.active_platform is None:
                break
        time.sleep(0.1)
    logged_in = mining_browser.has_login_cookie(platform)
    return {"platform": platform, "logged_in": logged_in}


class _LoginState:
    def __init__(self) -> None:
        import threading
        self.lock = threading.Lock()
        self.active_platform: Platform | None = None
        self.confirm_event: threading.Event | None = None


_login_state = _LoginState()


# ── AI Prompts config (Phase 3, T3b) ─────────────────────────────────
# Single source of truth: DEFAULT_* constants come from mining_ai_service.
# settings page hits these two routes; mining_ai_service reads the same
# config_service.load() values so they stay in lock-step automatically.

_PROMPT_VARS = {
    "summary": ["platform", "title", "author", "duration", "play_count"],
    "suggest": ["platform", "title", "author", "tier", "previous_block", "tone_hint"],
}


def _ai_prompts_payload() -> dict[str, Any]:
    cfg = config_service.load()
    return {
        "summary": {
            "current": cfg.mining_summary_prompt,
            "default": DEFAULT_SUMMARY_PROMPT_SYSTEM + "\n---user---\n" + DEFAULT_SUMMARY_PROMPT_USER,
        },
        "suggest": {
            "current": cfg.mining_suggest_prompt,
            "default": DEFAULT_SUGGEST_PROMPT_SYSTEM + "\n---user---\n" + DEFAULT_SUGGEST_PROMPT_USER,
        },
        "vars": _PROMPT_VARS,
    }


class AIPromptsPatch(BaseModel):
    """PATCH body for /api/mining/ai_prompts. 空字符串 = 回默认。"""

    summary: str | None = None
    suggest: str | None = None


@router.get("/api/mining/ai_prompts")
def get_ai_prompts() -> dict[str, Any]:
    """Return current + default prompts + the variable lists the UI hints with."""
    return _ai_prompts_payload()


@router.patch("/api/mining/ai_prompts")
def patch_ai_prompts(body: AIPromptsPatch) -> dict[str, Any]:
    """Update mining_summary_prompt / mining_suggest_prompt.

    Either field may be omitted (no change). Empty string is allowed and
    means "clear back to built-in default". No fields → 400.
    """
    updates: dict[str, Any] = {}
    if body.summary is not None:
        updates["mining_summary_prompt"] = body.summary
    if body.suggest is not None:
        updates["mining_suggest_prompt"] = body.suggest
    if not updates:
        raise HTTPException(status_code=400, detail="no fields provided")
    config_service.patch(updates)
    return _ai_prompts_payload()


# ── Comment CRUD (Phase 2 T5) ────────────────────────────────────────
def _video_exists(video_id: int) -> bool:
    conn = mining_storage.get_conn()
    return conn.execute("SELECT 1 FROM videos WHERE id=?", (video_id,)).fetchone() is not None


class CommentCreate(BaseModel):
    """POST body for /api/mining/videos/{id}/comments."""

    tier: int = Field(..., ge=1)
    text: str = ""
    image_ids: list[str] = Field(default_factory=list)
    source: str = "manual"


class CommentPatch(BaseModel):
    """PATCH body for /api/mining/comments/{cid}. All fields optional."""

    text: str | None = None
    image_ids: list[str] | None = None
    status: str | None = None


@router.get("/api/mining/videos/{video_id}/comments")
def list_video_comments(video_id: int) -> dict[str, Any]:
    if not _video_exists(video_id):
        raise HTTPException(status_code=404, detail=f"video not found: {video_id}")
    return {"comments": mining_storage.list_comments(video_id)}


@router.post("/api/mining/videos/{video_id}/comments", status_code=201)
def create_video_comment(video_id: int, body: CommentCreate) -> dict[str, Any]:
    if not _video_exists(video_id):
        raise HTTPException(status_code=404, detail=f"video not found: {video_id}")
    try:
        comment_id = mining_storage.create_comment(
            video_id=video_id,
            tier=body.tier,
            text=body.text,
            image_ids=body.image_ids,
            source=body.source,
        )
    except sqlite3.IntegrityError:
        raise HTTPException(
            status_code=409,
            detail=f"tier {body.tier} already exists for video {video_id}",
        )
    return mining_storage.get_comment(comment_id) or {}


@router.patch("/api/mining/comments/{comment_id}")
def patch_comment(comment_id: int, body: CommentPatch) -> dict[str, Any]:
    existing = mining_storage.get_comment(comment_id)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"comment not found: {comment_id}")
    # Diff image_ids BEFORE writing so we can clean up the orphaned files
    # off-DB regardless of what update_comment ends up doing.
    removed: list[str] = []
    if body.image_ids is not None:
        old_set = set(existing["image_ids"])
        new_set = set(body.image_ids)
        removed = sorted(old_set - new_set)
    updated = mining_storage.update_comment(
        comment_id,
        text=body.text,
        image_ids=body.image_ids,
        status=body.status,
    )
    if updated is None:  # racy delete between get + update
        raise HTTPException(status_code=404, detail=f"comment not found: {comment_id}")
    if removed:
        mining_images_service.delete_images(removed)
    return updated


@router.delete("/api/mining/comments/{comment_id}", status_code=204)
def delete_comment_route(comment_id: int) -> None:
    existing = mining_storage.get_comment(comment_id)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"comment not found: {comment_id}")
    image_ids = list(existing["image_ids"])
    if not mining_storage.delete_comment(comment_id):
        raise HTTPException(status_code=404, detail=f"comment not found: {comment_id}")
    if image_ids:
        mining_images_service.delete_images(image_ids)


# ── Image upload + serve (Phase 2 T5) ────────────────────────────────
@router.post("/api/mining/comments/images", status_code=201)
async def upload_comment_image(
    video_id: int = Form(...),
    file: UploadFile = File(...),
) -> dict[str, Any]:
    """Multipart upload. Bytes are sniffed for magic-bytes — the declared
    Content-Type / filename are NOT trusted (spec §6.2)."""
    if not _video_exists(video_id):
        raise HTTPException(status_code=404, detail=f"video not found: {video_id}")
    content = await file.read()
    try:
        image_id = mining_images_service.save_image(video_id, content)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {
        "image_id": image_id,
        "url": f"/api/mining/images/{image_id}",
        "size": len(content),
    }


# NOTE: this route is auth-gated like every other API route (RequireToken
# accepts either Bearer header OR ?token=<token> on GET — see auth.py).
# Frontend <img :src="..."> needs to append ?token=... from the sidecar
# store; alternatively the axios client can fetch and produce a blob URL.
_EXT_TO_MEDIA_TYPE = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}


@router.get("/api/mining/images/{image_id}")
def get_comment_image(image_id: str) -> FileResponse:
    path = mining_images_service.get_image_path(image_id)
    if path is None:
        raise HTTPException(status_code=404, detail=f"image not found: {image_id}")
    media_type = _EXT_TO_MEDIA_TYPE.get(path.suffix.lower(), "application/octet-stream")
    return FileResponse(str(path), media_type=media_type)


# ── AI inference (Phase 3 T5) ────────────────────────────────────────
class AISummaryBody(BaseModel):
    force: bool = False


class AISuggestBody(BaseModel):
    tier: int = Field(..., ge=1)
    previous_tiers: list[str] = Field(default_factory=list)
    tone_hint: str = ""


def _llm_http_error(e: Exception) -> HTTPException:
    """Map LLMConfigError → 503; anything else from the LLM client → 502."""
    if isinstance(e, LLMConfigError):
        return HTTPException(
            status_code=503,
            detail={"code": "llm_not_configured", "detail": str(e)},
        )
    return HTTPException(
        status_code=502,
        detail={"code": "llm_error", "detail": str(e) or e.__class__.__name__},
    )


@router.post("/api/mining/videos/{video_id}/ai_summary")
def ai_summary(video_id: int, body: AISummaryBody) -> dict[str, Any]:
    try:
        text = mining_ai_service.summarize_video(video_id, force=body.force)
    except LookupError:
        raise HTTPException(status_code=404, detail=f"video not found: {video_id}")
    except LLMConfigError as e:
        raise _llm_http_error(e)
    except Exception as e:  # noqa: BLE001 — LLM client can raise anything
        logger.exception("ai_summary failed for video %s", video_id)
        raise _llm_http_error(e)
    return {"summary": text}


@router.post("/api/mining/videos/{video_id}/ai_suggest_comment")
def ai_suggest_comment(video_id: int, body: AISuggestBody) -> dict[str, Any]:
    try:
        text = mining_ai_service.suggest_comment(
            video_id,
            tier=body.tier,
            previous_tiers=body.previous_tiers,
            tone_hint=body.tone_hint,
        )
    except LookupError:
        raise HTTPException(status_code=404, detail=f"video not found: {video_id}")
    except LLMConfigError as e:
        raise _llm_http_error(e)
    except Exception as e:  # noqa: BLE001
        logger.exception("ai_suggest_comment failed for video %s", video_id)
        raise _llm_http_error(e)
    return {"suggestion": text}


# ── Bulk mark commented (Phase 2 T5) ─────────────────────────────────
class BulkMarkBody(BaseModel):
    video_ids: list[int] = Field(default_factory=list)
    value: bool


@router.patch("/api/mining/videos/bulk_mark_commented")
def bulk_mark_commented(body: BulkMarkBody) -> dict[str, Any]:
    updated = mining_storage.bulk_mark_commented(body.video_ids, body.value)
    return {"updated": updated}


# ── Comment templates (v5) ─────────────────────────────────────────────


class TemplateListResponse(BaseModel):
    items: list[dict[str, Any]]
    total: int


@router.get("/api/mining/templates", response_model=TemplateListResponse)
def list_templates(
    search: str | None = None,
    tags: str | None = Query(default=None, description="CSV of tag names, intersection"),
    platform: str | None = None,
    starred: bool | None = None,
    hidden: str = Query(default="0", pattern="^(0|1|all)$"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    # Filter out empty strings — `?tags=,A,` should be treated as `["A"]`,
    # not `["", "A", ""]` which would silently match zero templates.
    tag_list = [t for t in (s.strip() for s in tags.split(",")) if t] if tags else None
    return mining_storage.list_templates(
        search=search,
        tags=tag_list,
        platform=platform,
        starred=starred,
        hidden=hidden,
        limit=limit,
        offset=offset,
    )


@router.get("/api/mining/templates/tags")
def list_template_tags() -> dict[str, list[str]]:
    return {"tags": mining_storage.list_used_tags()}


class CreateTemplateBody(BaseModel):
    text: str = Field(..., min_length=1)
    tags: list[str] = Field(default_factory=list)
    source_platform: str | None = None


class UpdateTemplateBody(BaseModel):
    text: str | None = None
    tags: list[str] | None = None
    starred: bool | None = None
    hidden: bool | None = None


_MAX_TEXT_LEN = 2000
_MAX_TAGS = 10
_MAX_TAG_LEN = 12
_MAX_BULK = 500


def _validate_template_input(text: str | None, tags: list[str] | None) -> None:
    if text is not None and len(text) > _MAX_TEXT_LEN:
        raise HTTPException(status_code=400, detail="text_too_long")
    if tags is not None:
        if len(tags) > _MAX_TAGS:
            raise HTTPException(status_code=400, detail="too_many_tags")
        for t in tags:
            if len(t) > _MAX_TAG_LEN:
                raise HTTPException(status_code=400, detail="tag_too_long")


def _fetch_template_dict(template_id: int) -> dict[str, Any] | None:
    """Fetch a single template row + convert to API dict."""
    from csm_core.monitor.storage import get_conn
    r = get_conn().execute(
        "SELECT * FROM comment_templates WHERE id=?", (template_id,),
    ).fetchone()
    return mining_storage._row_to_template_dict(r) if r else None


@router.post("/api/mining/templates", status_code=201)
def create_template(body: CreateTemplateBody):
    _validate_template_input(body.text, body.tags)
    try:
        tid = mining_storage.create_template(
            text=body.text, tags=body.tags, source_platform=body.source_platform,
        )
    except mining_storage.TemplateDuplicateError as e:
        # Use JSONResponse (not HTTPException) so the 409 body is flat —
        # tests expect {"detail": "duplicate", "existing_id": N}, not
        # {"detail": {"detail": "duplicate", "existing_id": N}}.
        return JSONResponse(
            status_code=409,
            content={"detail": "duplicate", "existing_id": e.existing_id},
        )
    return {"template": _fetch_template_dict(tid)}


@router.patch("/api/mining/templates/{template_id}")
def patch_template(template_id: int, body: UpdateTemplateBody):
    _validate_template_input(body.text, body.tags)
    try:
        tpl = mining_storage.update_template(
            template_id,
            text=body.text, tags=body.tags,
            starred=body.starred, hidden=body.hidden,
        )
    except mining_storage.TemplateDuplicateError as e:
        return JSONResponse(
            status_code=409,
            content={"detail": "duplicate", "existing_id": e.existing_id},
        )
    if tpl is None:
        raise HTTPException(status_code=404, detail="template not found")
    return {"template": tpl}


@router.delete("/api/mining/templates/{template_id}")
def delete_template(template_id: int) -> dict[str, Any]:
    ok = mining_storage.delete_template(template_id)
    if not ok:
        raise HTTPException(status_code=404, detail="template not found")
    return {"ok": True}


@router.post("/api/mining/templates/{template_id}/use")
def use_template(template_id: int) -> dict[str, Any]:
    text = mining_storage.bump_template_use(template_id)
    if text is None:
        raise HTTPException(status_code=404, detail="template not found")
    return {"text": text}


class BulkImportBody(BaseModel):
    texts: list[str] = Field(..., min_length=1)
    tags: list[str] = Field(default_factory=list)
    source_platform: str | None = None


@router.post("/api/mining/templates/bulk-import")
def bulk_import_templates(body: BulkImportBody) -> dict[str, int]:
    if len(body.texts) > _MAX_BULK:
        raise HTTPException(status_code=400, detail="max_batch_exceeded")
    _validate_template_input(text=None, tags=body.tags)
    # text-level length check on each item
    for t in body.texts:
        if len(t) > _MAX_TEXT_LEN:
            raise HTTPException(status_code=400, detail="text_too_long")
    return mining_storage.bulk_import_templates(
        texts=body.texts, tags=body.tags, source_platform=body.source_platform,
    )
