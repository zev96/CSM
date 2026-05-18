"""Mining module routes — jobs, videos, login flow, SSE events."""
from __future__ import annotations

import csv
import io
import logging
import sqlite3
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse, StreamingResponse
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
async def start_job(body: StartJobRequest) -> dict[str, Any]:
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
async def list_jobs(limit: int = Query(default=20, ge=1, le=200)) -> dict[str, Any]:
    items = mining_storage.list_jobs(limit=limit)
    return {"count": len(items), "jobs": items}


@router.get("/api/mining/jobs/{job_id}")
async def get_job(job_id: int) -> dict[str, Any]:
    job = mining_storage.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"job not found: {job_id}")
    return job


@router.post("/api/mining/jobs/{job_id}/cancel")
async def cancel(job_id: int) -> dict[str, Any]:
    ok = mining_service.cancel_job(job_id)
    if not ok:
        raise HTTPException(status_code=409, detail="job not running or already finished")
    return {"job_id": job_id, "cancelled": True}


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
async def export_csv(
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

    buf = io.StringIO()
    buf.write("﻿")  # BOM so Excel auto-detects UTF-8
    writer = csv.writer(buf)
    header = [
        "platform", "video_id", "url", "title", "author",
        "duration_sec", "play_count", "like_count",
        "source_keywords", "already_commented", "first_seen_at",
        "ai_summary",
    ]
    # If no comments exist for any selected video (max_tier == 0), don't
    # add comment_tier_N columns at all — keeps the old export shape for
    # callers who don't use the new feature (spec §4.5 "向后兼容").
    for tier in range(1, max_tier + 1):
        header.append(f"comment_tier_{tier}")
        header.append(f"images_tier_{tier}")
    writer.writerow(header)

    for r in rows:
        row = [
            r["platform"], r["platform_video_id"], r["url"], r["title"],
            r["author_name"], r["duration_sec"] or "",
            r["play_count"] or "", r["like_count"] or "",
            "|".join(r["source_keywords"]),
            "1" if r["already_commented"] else "0",
            r["first_seen_at"],
            r.get("ai_summary") or "",
        ]
        tiers_for_video = comments_by_video.get(int(r["id"]), {})
        for tier in range(1, max_tier + 1):
            c = tiers_for_video.get(tier)
            if c is None:
                row.append("")
                row.append("")
            else:
                row.append(c["text"])
                # Relative URLs so the export is portable; could be zipped
                # alongside an ``images/`` directory later (spec §4.5).
                row.append(",".join(f"images/{img}" for img in c["image_ids"]))
        writer.writerow(row)

    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="mining_videos.csv"'},
    )


@router.get("/api/mining/videos")
async def list_videos(
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
async def soft_delete_video(video_id: int) -> None:
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
async def login_status() -> dict[str, Any]:
    return {
        platform: {"logged_in": mining_browser.has_login_cookie(platform)}
        for platform in _login_specs
    }


@router.post("/api/mining/login/{platform}")
async def login_start(platform: Platform) -> dict[str, Any]:
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
            with mining_browser.launched_page(platform, headless=False, keep_alive=True) as page:
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
async def login_confirm(platform: Platform) -> dict[str, Any]:
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
async def get_ai_prompts() -> dict[str, Any]:
    """Return current + default prompts + the variable lists the UI hints with."""
    return _ai_prompts_payload()


@router.patch("/api/mining/ai_prompts")
async def patch_ai_prompts(body: AIPromptsPatch) -> dict[str, Any]:
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
async def list_video_comments(video_id: int) -> dict[str, Any]:
    if not _video_exists(video_id):
        raise HTTPException(status_code=404, detail=f"video not found: {video_id}")
    return {"comments": mining_storage.list_comments(video_id)}


@router.post("/api/mining/videos/{video_id}/comments", status_code=201)
async def create_video_comment(video_id: int, body: CommentCreate) -> dict[str, Any]:
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
async def patch_comment(comment_id: int, body: CommentPatch) -> dict[str, Any]:
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
async def delete_comment_route(comment_id: int) -> None:
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
async def get_comment_image(image_id: str) -> FileResponse:
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
async def ai_summary(video_id: int, body: AISummaryBody) -> dict[str, Any]:
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
async def ai_suggest_comment(video_id: int, body: AISuggestBody) -> dict[str, Any]:
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
async def bulk_mark_commented(body: BulkMarkBody) -> dict[str, Any]:
    updated = mining_storage.bulk_mark_commented(body.video_ids, body.value)
    return {"updated": updated}
