"""Monitor module routes — tasks, results, cookies, summary, reports, events."""
from __future__ import annotations

import json
import os
from typing import Any, AsyncIterator

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from csm_core.monitor import storage
from csm_core.monitor.base import MonitorTask, TaskType

from ..auth import RequireToken
from ..monitor_bus import monitor_bus
from ..services import history_service, monitor_lifecycle, monitor_service

router = APIRouter(tags=["monitor"], dependencies=[RequireToken])


def _require_storage() -> None:
    if not monitor_service.storage_initialized():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="monitor storage not initialised — call POST /api/monitor/init or start the sidecar in production mode",
        )


# ── Task CRUD ──────────────────────────────────────────────────────────────
class TaskBody(BaseModel):
    """POST/PATCH body. ``id`` is server-assigned on create."""
    type: TaskType
    name: str = Field(min_length=1)
    target_url: str = Field(min_length=1)
    config: dict[str, Any] = Field(default_factory=dict)
    schedule_cron: str = "manual"
    enabled: bool = True


@router.get("/api/monitor/tasks")
def list_tasks(
    type: TaskType | None = Query(default=None),
    enabled_only: bool = Query(default=False),
) -> dict[str, Any]:
    _require_storage()
    items = monitor_service.list_tasks(type=type, enabled_only=enabled_only)
    return {"count": len(items), "tasks": items}


@router.get("/api/monitor/tasks/{task_id}")
def get_task(task_id: int) -> dict[str, Any]:
    _require_storage()
    t = monitor_service.get_task(task_id)
    if t is None:
        raise HTTPException(status_code=404, detail=f"task not found: {task_id}")
    return t


@router.post("/api/monitor/tasks", status_code=201)
def create_task(body: TaskBody) -> dict[str, Any]:
    _require_storage()
    task = MonitorTask(**body.model_dump())
    new_id = monitor_service.create_task(task)
    return monitor_service.get_task(new_id) or {"id": new_id}


@router.patch("/api/monitor/tasks/{task_id}")
def update_task(task_id: int, body: TaskBody) -> dict[str, Any]:
    _require_storage()
    if monitor_service.get_task(task_id) is None:
        raise HTTPException(status_code=404, detail=f"task not found: {task_id}")
    task = MonitorTask(id=task_id, **body.model_dump())
    monitor_service.update_task(task)
    return monitor_service.get_task(task_id) or {}


@router.delete("/api/monitor/tasks/{task_id}", status_code=204)
def delete_task(task_id: int) -> None:
    _require_storage()
    if monitor_service.get_task(task_id) is None:
        raise HTTPException(status_code=404, detail=f"task not found: {task_id}")
    monitor_service.delete_task(task_id)


@router.post("/api/monitor/tasks/{task_id}/run-now")
def run_now(
    task_id: int,
    keyword: str | None = Query(default=None),
) -> dict[str, Any]:
    """Force one dispatch off-schedule. Returns immediately — watch
    /api/monitor/events for the result.

    ``keyword`` (optional) — currently only honored by ``baidu_keyword``
    tasks: when present, the adapter only scrapes that single keyword's
    SERP, and the loop merges the partial result with the previous
    snapshot so other keywords' data is preserved. Sent by the Level 2
    «启动监测» button to avoid spinning a browser per keyword.
    """
    _require_storage()
    loop = monitor_lifecycle.get()
    if loop is None or not loop.is_running():
        raise HTTPException(
            status_code=503,
            detail="MonitorLoop not running — start the sidecar in production mode",
        )
    if monitor_service.get_task(task_id) is None:
        raise HTTPException(status_code=404, detail=f"task not found: {task_id}")
    loop.run_task_now(task_id, keyword_override=keyword)
    return {"task_id": task_id, "queued": True, "keyword": keyword}


@router.post("/api/monitor/tasks/{task_id}/resume")
def resume_task(task_id: int) -> dict[str, Any]:
    """Resume a risk_control'd task from its last_resumed_keyword breakpoint.

    Reads the latest result's ``metric.last_resumed_keyword`` and dispatches
    via the same run-now path with ``resume_from`` set accordingly. If the
    task has no breakpoint (no prior risk_control result with the key), falls
    through to a normal full-scan starting at keyword 0.

    Returns immediately — watch ``/api/monitor/events`` for the result.
    """
    _require_storage()
    loop = monitor_lifecycle.get()
    if loop is None or not loop.is_running():
        raise HTTPException(
            status_code=503,
            detail="MonitorLoop not running — start the sidecar in production mode",
        )
    if monitor_service.get_task(task_id) is None:
        raise HTTPException(status_code=404, detail=f"task not found: {task_id}")

    resume_from = storage.get_last_resumed_keyword(task_id) or 0
    loop.run_task_now(task_id, resume_from=resume_from)
    return {"task_id": task_id, "resume_from": resume_from, "queued": True}


@router.get("/api/monitor/running")
def list_running() -> dict[str, Any]:
    """Truth source for "which tasks are currently being fetched".

    Frontend hydrates ``runningTaskIds`` from this when a page mounts
    after the user navigated away (SSE `started` events fired while the
    component was unmounted are lost, so the local Set goes stale).
    Sidecar restart returns empty (any in-flight tasks died with the
    process) — that's the correct semantics.
    """
    loop = monitor_lifecycle.get()
    if loop is None or not loop.is_running():
        return {"running_task_ids": []}
    return {"running_task_ids": loop.get_active_task_ids()}


@router.post("/api/monitor/tasks/{task_id}/cancel")
def cancel_task(task_id: int) -> dict[str, Any]:
    """Cooperative cancel: signal the running worker to bail at its next
    checkpoint. Baidu adapter checks between keywords; other adapters
    are single-shot fetches that can't easily be interrupted (the
    cancel flag will still mark them so they won't reschedule mid-run).

    Returns ``{cancelled: true}`` if the signal was delivered (task was
    running), else ``{cancelled: false}``. Either way 200 — the UI just
    treats the result as advisory and waits for the next SSE event.
    """
    _require_storage()
    loop = monitor_lifecycle.get()
    if loop is None or not loop.is_running():
        return {"task_id": task_id, "cancelled": False}
    delivered = loop.cancel_task(task_id)
    return {"task_id": task_id, "cancelled": delivered}


# ── Results ────────────────────────────────────────────────────────────────
@router.get("/api/monitor/results")
def list_results(
    task_id: int = Query(...),
    limit: int = Query(default=30, ge=1, le=500),
) -> dict[str, Any]:
    """Historical results — feeds the sparkline (D in A2 alignment table)."""
    _require_storage()
    rows = monitor_service.list_results(task_id, limit=limit)
    return {"task_id": task_id, "count": len(rows), "results": rows}


# ── Cookies ────────────────────────────────────────────────────────────────
class CookieBody(BaseModel):
    cookies_text: str = Field(min_length=1)
    label: str = ""
    user_agent: str = ""


@router.get("/api/monitor/cookies")
def list_cookies(
    platform: str = Query(...),
    enabled_only: bool = Query(default=False),
) -> dict[str, Any]:
    _require_storage()
    rows = monitor_service.list_cookies(platform, enabled_only=enabled_only)
    return {"platform": platform, "count": len(rows), "cookies": rows}


@router.post("/api/monitor/cookies/{platform}", status_code=201)
def add_cookie(platform: str, body: CookieBody) -> dict[str, Any]:
    _require_storage()
    cred_id = monitor_service.add_cookie(platform=platform, **body.model_dump())
    return {"id": cred_id, "platform": platform, "label": body.label}


@router.delete("/api/monitor/cookies/{cred_id}", status_code=204)
def delete_cookie(cred_id: int) -> None:
    _require_storage()
    monitor_service.delete_cookie(cred_id)


# ── Interactive cookie capture ─────────────────────────────────────────────
class CookieLoginBody(BaseModel):
    """Body for ``POST /api/monitor/cookies/{platform}/login``.

    Triggers an interactive Patchright window that the user logs into
    manually. Cookies harvested from that window are saved as a new
    pool entry — fingerprint-consistent with the scraping path that
    will later reuse them.
    """
    label: str = ""
    timeout_s: float = Field(default=300.0, ge=10, le=900)


@router.post("/api/monitor/cookies/{platform}/login", status_code=201)
def login_capture(platform: str, body: CookieLoginBody) -> dict[str, Any]:
    """Open a Patchright window, wait for user login, save cookies.

    Why ``def`` not ``async def``: this endpoint blocks for up to
    ``timeout_s`` seconds while the user logs in. Declaring it sync
    makes FastAPI run it in its threadpool, which keeps the asyncio
    event loop free to handle other requests (SSE feeds, the monitor
    tick scheduler, etc.) while this one waits. An ``async def`` that
    called the sync ``capture_cookies_via_login`` directly would pin
    the event loop for 5 minutes — every other request would hang.

    Errors:
        400 — unknown platform name.
        503 — Patchright not installed / Chromium binary missing.
        200 with success=False — user gave up (window closed or
            timeout). Distinct from infrastructure failure: the UI
            shows "登录超时" rather than "系统错误".
    """
    import logging as _logging
    _route_log = _logging.getLogger(__name__)
    _route_log.info(
        "interactive login request: platform=%s label=%r timeout=%.0fs",
        platform, body.label, body.timeout_s,
    )
    _require_storage()
    try:
        from csm_core.monitor.drivers import interactive_login
    except Exception as e:
        # An ImportError here means the bundled sidecar is missing the
        # interactive_login module or one of its transitive deps
        # (typically patchright when the spec didn't include it). Without
        # this branch the route would 500 with no detail and the frontend
        # would show "Network Error" — surface the cause instead.
        _route_log.exception("interactive login: import failed")
        raise HTTPException(
            status_code=503,
            detail=f"interactive login unavailable: {e!r}",
        ) from e

    try:
        result = interactive_login.capture_cookies_via_login(
            platform=platform,
            label=body.label,
            timeout_s=body.timeout_s,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except RuntimeError as e:
        # Patchright missing / Chromium not installed. Status 503 =
        # "service-side dependency unavailable" — the UI tells the
        # user to install Chromium rather than retry.
        _route_log.warning("interactive login: runtime error: %s", e)
        raise HTTPException(status_code=503, detail=str(e)) from e
    except Exception as e:
        # Catch-all: anything else (FileNotFoundError from pw.start(),
        # PermissionError on user_data_dir, Playwright launch timeout,
        # cookie serialization failure, …) used to bubble up as a bare
        # 500 with no body — axios then shows "Network Error" which is
        # actively misleading. Funnel into a 500 with the exception repr
        # so the UI toast tells the user what actually broke.
        _route_log.exception("interactive login: unexpected failure")
        raise HTTPException(
            status_code=500,
            detail=f"login_capture crashed: {type(e).__name__}: {e}",
        ) from e

    return {
        "success": result.success,
        "id": result.cred_id,
        "platform": platform,
        "label": body.label,
        "cookie_count": result.cookie_count,
        "cookies_preview": result.cookies_preview,
        "error": result.error,
    }


# ── Summary + history aggregations ────────────────────────────────────────
@router.get("/api/monitor/summary")
def get_summary() -> dict[str, Any]:
    _require_storage()
    return monitor_service.get_summary()


@router.get("/api/monitor/history/comment-retention")
def get_comment_retention_history(range_str: str = Query("7d", alias="range")) -> dict[str, Any]:
    _require_storage()
    try:
        return history_service.get_comment_retention_history(range_str=range_str)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/api/monitor/history/zhihu-ranking")
def get_zhihu_ranking_history(range_str: str = Query("7d", alias="range")) -> dict[str, Any]:
    _require_storage()
    try:
        return history_service.get_zhihu_ranking_history(range_str=range_str)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/api/monitor/history/baidu-keyword")
def get_baidu_keyword_history(range_str: str = Query("7d", alias="range")) -> dict[str, Any]:
    _require_storage()
    try:
        return history_service.get_baidu_keyword_history(range_str=range_str)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


# ── Live event stream ──────────────────────────────────────────────────────
@router.get("/api/monitor/events")
async def stream_events():
    """SSE broadcast of every MonitorLoop event. Multiple clients OK."""
    async def _gen() -> AsyncIterator[dict]:
        async for event in monitor_bus.subscribe():
            yield {
                "event": event["kind"],
                "data": json.dumps(
                    {k: v for k, v in event.items() if k != "kind"},
                    ensure_ascii=False,
                ),
            }
    return EventSourceResponse(_gen())


# ── Baidu browser profile management ──────────────────────────────────────
@router.post("/api/monitor/baidu/reset-profile", status_code=status.HTTP_204_NO_CONTENT)
def reset_baidu_profile() -> None:
    """Delete the persistent baidu browser profile dir.

    Use case: profile has been hit by 百度风控 multiple times and cookies
    are "burnt"; rather than wait for cooldown, user wipes and starts fresh.

    Safety: refuses (409) if any baidu task is currently running — would
    corrupt the live profile mid-write.
    """
    from csm_core.monitor.drivers.baidu_browser import reset_profile
    from ..services import monitor_lifecycle

    loop = monitor_lifecycle.get()
    if loop is not None and loop.has_active_baidu_task():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="有正在运行的百度任务，先停止再重置",
        )
    reset_profile()


@router.post("/api/monitor/baidu/login")
async def baidu_login_open() -> dict[str, Any]:
    """Open a visible patchright window so the user can log in to Baidu.
    Persistent cookies land in the same profile dir that fetch tasks use.

    Refuses (409) if a baidu task is running — they share the same
    user_data_dir lock.

    Runs the (sync) playwright call in a thread so FastAPI's asyncio loop
    isn't blocked. patchright's sync API explicitly refuses to run inside
    an asyncio event loop, so a direct call from this `async def` handler
    raises "It looks like you are using Playwright Sync API inside the
    asyncio loop." — to_thread sidesteps that.
    """
    import asyncio
    from csm_core.monitor.drivers.baidu_login import open_login_window
    from ..services import monitor_lifecycle

    loop = monitor_lifecycle.get()
    if loop is not None and loop.has_active_baidu_task():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="有正在运行的百度任务，先停止再登录",
        )
    return await asyncio.to_thread(open_login_window)


@router.get("/api/monitor/baidu/login-status")
async def baidu_login_status() -> dict[str, Any]:
    """Read-only login state probe used by the settings page.

    Briefly launches a headless persistent context (~2s) to read cookies.
    Failures degrade to {logged_in: False} rather than 5xx — settings UI
    shouldn't blow up if the profile is corrupt.

    Same to_thread reasoning as baidu_login_open — sync patchright cannot
    run in the asyncio loop.
    """
    import asyncio
    from csm_core.monitor.drivers.baidu_login import get_login_status

    try:
        return await asyncio.to_thread(get_login_status)
    except Exception as e:
        # Soft fallback so the UI keeps functioning
        import logging
        logging.getLogger(__name__).warning("baidu login-status read failed: %s", e)
        return {"logged_in": False, "username": None, "expires_at": None}


# ── GEO RPA 登录（DeepSeek/Kimi/元宝 真浏览器持久档登录态）─────────────
_GEO_RPA_PLATFORMS = {"deepseek", "kimi", "yuanbao"}


@router.post("/api/monitor/geo/rpa/{platform}/login")
async def geo_rpa_login_open(platform: str) -> dict[str, Any]:
    """开有头窗让用户登录某 RPA 平台。持久档落 browser_profiles/geo_<platform>/。
    sync patchright 不能在 asyncio loop 里跑 → to_thread。"""
    import asyncio
    if platform not in _GEO_RPA_PLATFORMS:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"未知 RPA 平台: {platform}")
    from csm_core.monitor.geo.providers.rpa import _session
    return await asyncio.to_thread(_session.open_login, platform)


@router.get("/api/monitor/geo/rpa/{platform}/login-status")
async def geo_rpa_login_status(platform: str) -> dict[str, Any]:
    """无头快查登录态。失败降级 {logged_in: False}，不 5xx。"""
    import asyncio
    if platform not in _GEO_RPA_PLATFORMS:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"未知 RPA 平台: {platform}")
    from csm_core.monitor.geo.providers.rpa import _session
    try:
        return await asyncio.to_thread(_session.login_status, platform)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("geo rpa login-status[%s] failed: %s", platform, e)
        return {"logged_in": False}


# ── Baidu native mode (方案 D) ────────────────────────────────────
from csm_core.monitor.drivers import chrome_detect
from csm_core.monitor.drivers.baidu_browser import baidu_browser_session
from pathlib import Path as _Path

# 用 config_service.load() 而不是 csm_core.config.get_config()，跟
# baidu_keyword.fetch() 保持一致（这样测试 fixture config_service.init(tmp_path)
# 注入的 config 能生效）。
from csm_sidecar.services import config_service as _cfg_svc


class ListProfilesBody(BaseModel):
    user_data_dir: str = Field(min_length=1)


class CopyProfileBody(BaseModel):
    source_user_data_dir: str = Field(min_length=1)
    source_profile_name: str = Field(default="Default")


class TestNativeBody(BaseModel):
    chrome_executable_path: str = Field(min_length=1)
    chrome_profile_copy_path: str = Field(min_length=1)


class NativeConfigBody(BaseModel):
    use_native_chrome: bool
    chrome_executable_path: str | None = None
    chrome_user_data_dir: str | None = None
    chrome_profile_name: str = "Default"


@router.post("/api/monitor/baidu/detect-chrome")
def baidu_detect_chrome() -> dict[str, Any]:
    """探测 Chrome 安装路径 + User Data 默认位置。"""
    return {
        "executable_path": chrome_detect.find_chrome_executable(),
        "user_data_dir": chrome_detect.find_user_data_dir(),
    }


@router.post("/api/monitor/baidu/list-profiles")
def baidu_list_profiles(body: ListProfilesBody) -> dict[str, Any]:
    """枚举给定 user_data_dir 下所有 profile + 账号 email。"""
    return {"profiles": chrome_detect.list_profiles(body.user_data_dir)}


@router.post("/api/monitor/baidu/copy-profile")
def baidu_copy_profile(body: CopyProfileBody) -> dict[str, Any]:
    """一键复制 Chrome profile 到 CSM 专用目录（B' 方案）。

    副本路径独立于 Chrome 默认目录，绕过 Chrome 91+ DevTools 安全限制。
    返回包含 copy_path 给前端展示 + 更新 config。
    """
    from csm_core import config as _core_config

    target = _core_config.default_config_dir() / "baidu_chrome_profile_copy"
    try:
        meta = chrome_detect.copy_profile_to(
            source_user_data_dir=body.source_user_data_dir,
            source_profile_name=body.source_profile_name,
            target_path=str(target),
        )
    except FileNotFoundError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"复制失败: {e}"}

    # 更新 config
    cfg = _cfg_svc.load()
    bk = cfg.monitor.baidu_keyword
    bk.chrome_profile_copy_path = str(target)
    bk.chrome_profile_copy_imported_at = meta["imported_at"]
    # 源信息记下来给 re-import 用
    bk.chrome_user_data_dir = body.source_user_data_dir
    bk.chrome_profile_name = body.source_profile_name
    # 顺手探测并持久化 chrome.exe 路径 —— 否则它一直为空（默认 None），用户走完
    # 复制流程后点"登录副本"/正式跑监控会直接撞"缺 Chrome 可执行文件路径"。
    # 仅在尚未设置时探测，不覆盖用户手填的路径。
    if not bk.chrome_executable_path:
        detected_exe = chrome_detect.find_chrome_executable()
        if detected_exe:
            bk.chrome_executable_path = detected_exe
    _cfg_svc.save(cfg)

    return {
        "ok": True,
        "copy_path": str(target),
        "imported_at": meta["imported_at"],
        "size_mb": meta["size_mb"],
        "elapsed_s": meta["elapsed_s"],
    }


@router.post("/api/monitor/baidu/test-native")
def baidu_test_native(body: TestNativeBody) -> dict[str, Any]:
    """试启动 Chrome 验证副本可用。成功 close 后返回 ok=True。

    Preflight check 已经不需要 ── 副本路径独立于 Chrome 默认目录，
    可以跟用户日常 Chrome 共存。
    """
    try:
        with baidu_browser_session(
            headless=False,
            user_data_dir=_Path(body.chrome_profile_copy_path),
            use_native_chrome=True,
            chrome_executable_path=body.chrome_executable_path,
            chrome_profile_name="Default",  # 副本内固定叫 Default
        ):
            pass  # 启动成功立即关
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.get("/api/monitor/baidu/native-config")
def baidu_get_native_config() -> dict[str, Any]:
    """读当前 native mode 配置。"""
    cfg = _cfg_svc.load()
    bk = cfg.monitor.baidu_keyword
    return {
        "use_native_chrome": bk.use_native_chrome,
        "chrome_executable_path": bk.chrome_executable_path,
        "chrome_user_data_dir": bk.chrome_user_data_dir,
        "chrome_profile_name": bk.chrome_profile_name,
        "chrome_profile_copy_path": bk.chrome_profile_copy_path,
        "chrome_profile_copy_imported_at": bk.chrome_profile_copy_imported_at,
        "chrome_profile_copy_last_logged_in_at": bk.chrome_profile_copy_last_logged_in_at,
    }


@router.post("/api/monitor/baidu/native-config")
def baidu_set_native_config(body: NativeConfigBody) -> dict[str, Any]:
    """保存 native mode 配置（merge 到全局 BaiduKeywordConfig）。"""
    cfg = _cfg_svc.load()
    bk = cfg.monitor.baidu_keyword
    bk.use_native_chrome = body.use_native_chrome
    bk.chrome_executable_path = body.chrome_executable_path
    bk.chrome_user_data_dir = body.chrome_user_data_dir
    bk.chrome_profile_name = body.chrome_profile_name
    _cfg_svc.save(cfg)
    return {"ok": True}


# 启动副本 Chrome 让用户登录百度（B' 必须 ── DPAPI 复制不了 cookies）
@router.post("/api/monitor/baidu/launch-login-window")
def baidu_launch_login_window() -> dict[str, Any]:
    """Spawn detached headed Chrome 副本 + 打开 baidu.com 让用户登录。

    用户在副本里登录后关闭浏览器 → Chrome 把 BDUSS 写入副本 Cookies（用副本
    Local State master key 加密）→ 后续 fetch 用副本能正常解密。

    本 API 不等待用户登录完成（subprocess 启动后立即返回）；后台线程监听
    进程退出，进程退出时更新 chrome_profile_copy_last_logged_in_at config。
    """
    import subprocess
    import threading
    from datetime import datetime

    cfg = _cfg_svc.load()
    bk = cfg.monitor.baidu_keyword
    if not bk.chrome_profile_copy_path:
        return {"ok": False, "error": "还未导入 Chrome profile 副本，请先点'复制 Chrome profile'"}
    if not bk.chrome_executable_path:
        return {"ok": False, "error": "缺 Chrome 可执行文件路径"}

    # Spawn 副本 Chrome detached（独立进程，CSM sidecar 退出不影响它）
    try:
        proc = subprocess.Popen(
            [
                bk.chrome_executable_path,
                f"--user-data-dir={bk.chrome_profile_copy_path}",
                "--profile-directory=Default",
                "https://www.baidu.com",
            ],
            # detached：sidecar 退出不杀子 process
            creationflags=subprocess.DETACHED_PROCESS if os.name == "nt" else 0,
        )
    except Exception as e:
        return {"ok": False, "error": f"启动 Chrome 副本失败: {e}"}

    # 后台监听进程退出 → 更新 last_logged_in_at
    def _watch_login_window(pid: int) -> None:
        try:
            proc.wait()  # 阻塞直到 Chrome 完全退出
        except Exception:
            return
        # Chrome 退出 = 用户关了登录窗 = BDUSS 已经持久化到副本 Cookies
        cfg2 = _cfg_svc.load()
        bk2 = cfg2.monitor.baidu_keyword
        bk2.chrome_profile_copy_last_logged_in_at = datetime.utcnow().isoformat()
        _cfg_svc.save(cfg2)
        # 也通过 monitor_bus publish 一个事件给前端
        from csm_sidecar.monitor_bus import monitor_bus
        from csm_sidecar.services.monitor_loop import MonitorEvent
        monitor_bus.publish(MonitorEvent(
            kind="needs_captcha",  # reuse 现有 event kind 让前端弹通知
            task_id=0,
            at=datetime.utcnow(),
            keyword="副本登录态已保存",
            kw_idx=0,
        ))

    threading.Thread(target=_watch_login_window, args=(proc.pid,), daemon=True).start()

    return {"ok": True, "pid": proc.pid}


# ── GEO 卡位监控只读聚合端点 ───────────────────────────────────────────
# auth：router 级 ``dependencies=[RequireToken]`` 已覆盖这两个 GET，跟本文件
# 其它路由一致（不在 handler 签名里重复声明）。KPI 汇总走现有
# /api/monitor/results（metric_json 已含 KPI 块），阶段 1 不单列 kpi 端点；
# 导出 Excel 推迟到阶段 2。geo_storage 懒加载（与其它 handler 同风格）。
@router.get("/api/monitor/geo/{task_id}/citations")
def geo_citations(
    task_id: int,
    days: int = Query(default=30),
    platform: str | None = Query(default=None),
    keyword: str | None = Query(default=None),
) -> dict[str, Any]:
    """信源榜：按注册域名频次降序聚合该任务近 ``days`` 天的全部 citation。"""
    _require_storage()
    from csm_core.monitor.geo import storage as geo_storage

    return {
        "leaderboard": geo_storage.citation_leaderboard(
            task_id, days=days, platform=platform, keyword=keyword
        )
    }


@router.get("/api/monitor/geo/{task_id}/export")
def geo_export(task_id: int, days: int = Query(default=30, ge=1, le=3650)):
    """信源榜 Excel 导出：近 ``days`` 天全部 citation 聚合为 xlsx 文件下载。"""
    _require_storage()
    import io
    from openpyxl import Workbook
    from fastapi.responses import StreamingResponse
    from csm_core.monitor.geo import storage as geo_storage

    board = geo_storage.citation_leaderboard(task_id, days=days)
    wb = Workbook()
    ws = wb.active
    ws.title = "信源榜"
    ws.append(["排名", "域名", "类型", "引用次数", "覆盖平台数", "命中关键词"])
    for i, b in enumerate(board, start=1):
        ws.append([i, b["domain"], b["source_type"], b["count"],
                   len(b["platforms"]), " / ".join(b["keywords"])])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="geo_citations_{task_id}.xlsx"'},
    )


@router.get("/api/monitor/geo/{task_id}/cells")
def geo_cells(task_id: int, checked_at: str = Query(...)) -> dict[str, Any]:
    """下钻：某次运行的全部 cell（原文 + 信源）。

    运行按 ``(task_id, checked_at)`` 关联 —— ``checked_at`` 是该次运行
    MonitorResult.checked_at 的存库 ISO 串（前端从 /api/monitor/results
    拿到后回传）。geo 表不外键 monitor_results.id（adapter 不自存 result，
    避免与 monitor_loop 的 save_result 双写）。
    """
    _require_storage()
    from csm_core.monitor.geo import storage as geo_storage

    return {"cells": geo_storage.cells_for_run(task_id, checked_at)}


@router.get("/api/monitor/geo/{task_id}/latest-cells")
def geo_latest_cells(task_id: int) -> dict[str, Any]:
    """下钻：该任务**最近一次**运行的全部 cell（原文 + 信源 + 推荐顺序）。

    不需要 ``checked_at`` 入参 —— L2 卡位仪表盘直接拿最新一跑。后端用
    ``max(checked_at)`` 解析最近运行，规避 ``/api/monitor/results`` 回传的
    checked_at 缺尾 ``Z``、与 geo_cells 存库串（带 ``Z``）不相等导致
    /cells 精确匹配返回 0 条的坑（geo_cells 不外键 monitor_results.id）。
    """
    _require_storage()
    from csm_core.monitor.geo import storage as geo_storage

    return {"cells": geo_storage.cells_for_latest_run(task_id)}
