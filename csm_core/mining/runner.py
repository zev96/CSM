"""Orchestrates one MiningJob: pick adapters, run each platform serially,
stream cards to storage, publish progress events.

Threading: one job runs on one worker thread (sidecar's
``mining_service`` ThreadPoolExecutor with max_workers=1). Inside the
job we DO NOT spawn additional threads — adapters block on
patchright sync API which is already greenlet-bound to this thread.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Callable

from csm_core.mining import storage as mining_storage
from csm_core.mining.comment_prefilter import count_brand_hits, fetch_video_comments
from csm_core.mining.models import (
    Platform, ProgressUpdate, SearchOutcome, VideoCard,
)
from csm_core.mining.platforms._common import SearchAdapter
from csm_core.mining.platforms.bilibili_search import BilibiliSearchAdapter
from csm_core.mining.platforms.douyin_search import DouyinSearchAdapter
from csm_core.mining.platforms.kuaishou_search import KuaishouSearchAdapter
from csm_core.monitor.tikhub.client import balance_exhausted

logger = logging.getLogger(__name__)


PUBLISH_EVERY_N_CARDS = 5
PUBLISH_EVERY_N_SECONDS = 10.0

# Brand pre-filter fallback constants — the live values come from
# AppConfig.mining_prefilter_threshold / mining_prefilter_top_n (settings.json)，
# 这里只是配置读取失败时的兜底，与 AppConfig 默认值保持一致。
# A video is marked excluded when ≥ threshold of its scraped comments
# contain at least one brand keyword（2026-08-31 拍板：前 20 条命中 1 条即排除）。
PREFILTER_THRESHOLD = 1
# How many comments to fetch per video for the brand-hit check.
PREFILTER_SCRAPE_TOP_N = 20


EventPublisher = Callable[[str, dict], None]
"""Callable injected by mining_service to publish to the event bus.
Signature: ``publish(kind, payload)`` — kind ∈ {"job.started", "job.progress",
"job.platform_done", "job.finished", "login.required"}."""


def _prefilter_params(cfg=None) -> tuple[int, int]:
    """Resolve (top_n, threshold) from AppConfig, falling back to module constants.

    每次 run 现读一次 settings.json（get_config 无缓存），用户改了设置
    下一个任务生效，不用重启 sidecar。

    cfg 可选：run() 一个任务只读一次 settings.json，与 _data_source_mode 共享
    同一次读取结果（传进来直接用，不重复 IO）；不传时（独立调用 / 测试）自己
    现读一次。
    """
    try:
        if cfg is None:
            from csm_core.config import get_config

            cfg = get_config()
        return (
            int(getattr(cfg, "mining_prefilter_top_n", PREFILTER_SCRAPE_TOP_N)),
            int(getattr(cfg, "mining_prefilter_threshold", PREFILTER_THRESHOLD)),
        )
    except Exception:
        logger.info("[runner] config read failed, using prefilter fallbacks", exc_info=True)
        return PREFILTER_SCRAPE_TOP_N, PREFILTER_THRESHOLD


def _data_source_mode(cfg=None) -> str:
    """每个任务开始时读一次settings.json（get_config 无缓存；任务内三平台同一
    数据源，不会出现同一个 job 里一个平台走本地、另一个平台走 TikHub 的情况）。
    用户改了开关下个任务生效。读不到 / 非法值 → tikhub_api（与 AppConfig 默认一致）。

    cfg 可选：run() 与 _prefilter_params 共享同一次读取结果（传进来直接用）；
    不传时（独立调用 / 测试，含 get_adapter(mode=None) 的内部调用）自己现读
    一次。
    """
    try:
        if cfg is None:
            from csm_core.config import get_config

            cfg = get_config()
        mode = str(getattr(cfg, "mining_data_source_mode", "") or "")
        return mode if mode in ("tikhub_api", "local") else "tikhub_api"
    except Exception:
        logger.info("[runner] config read failed, defaulting mining data source to tikhub_api", exc_info=True)
        return "tikhub_api"


# 只有 TikHub 路径的平台:没有浏览器采集实现。local 模式下返回占位适配器(立刻记 failed
# 并提示切到 TikHub),而不是抛 ValueError —— 抛出去会让整个 job 线程崩掉,其它平台也没结果。
_TIKHUB_ONLY_PLATFORMS = frozenset({"xiaohongshu"})


class UnsupportedLocalSearchAdapter:
    """local(浏览器)模式下没有实现的平台的占位适配器:不发任何请求,直接 failed。"""

    def __init__(self, platform: Platform) -> None:
        self.platform: Platform = platform

    def search(self, keyword, target_count, on_card, on_progress, cancel_event,
               max_attempts=None, filters=None) -> SearchOutcome:
        reason = "小红书暂不支持浏览器采集，请在「设置 › 监测 › 抓取数据源」开启 TikHub 采集"
        on_progress(ProgressUpdate(
            platform=self.platform, phase="failed", got=0, target=int(target_count), note=reason[:120],
        ))
        return SearchOutcome(platform=self.platform, status="failed", cards_emitted=0,
                             error_message=reason)


def get_adapter(platform: Platform, mode: str | None = None) -> SearchAdapter:
    """按数据源模式选适配器：tikhub_api → TikHub 付费搜索（免登录、免并发风控）；
    local → 浏览器（手动兜底）。mode=None 时现读 AppConfig.mining_data_source_mode。
    保持单参调用兼容（run() 与既有测试的 fake 都只传 platform）。"""
    if mode is None:
        mode = _data_source_mode()
    if mode == "tikhub_api":
        from csm_core.config import get_config, read_api_key
        from csm_core.mining.platforms.tikhub_search import build_tikhub_search_adapters

        adapters = build_tikhub_search_adapters(get_config, read_api_key)
        if platform in adapters:
            return adapters[platform]
        raise ValueError(f"unknown platform: {platform}")
    if platform in _TIKHUB_ONLY_PLATFORMS:
        return UnsupportedLocalSearchAdapter(platform)
    if platform == "bilibili":
        return BilibiliSearchAdapter()
    if platform == "kuaishou":
        return KuaishouSearchAdapter()
    if platform == "douyin":
        return DouyinSearchAdapter()
    raise ValueError(f"unknown platform: {platform}")


class MiningRunner:
    def __init__(self, *, publish: EventPublisher) -> None:
        self.publish = publish
        self._cancel_events: dict[int, threading.Event] = {}
        self._lock = threading.Lock()

    def register_cancel_event(self, job_id: int) -> threading.Event:
        with self._lock:
            if job_id not in self._cancel_events:
                self._cancel_events[job_id] = threading.Event()
            return self._cancel_events[job_id]

    def cancel(self, job_id: int) -> bool:
        with self._lock:
            ev = self._cancel_events.get(job_id)
        if ev:
            ev.set()
            return True
        return False

    def run(self, job_id: int) -> None:
        job = mining_storage.get_job(job_id)
        if job is None:
            logger.warning("MiningRunner.run: unknown job %d", job_id)
            return
        cancel_event = self.register_cancel_event(job_id)
        brand_keywords: list[str] = job.get("brand_keywords") or []
        filters: dict = job.get("filters") or {}
        # 一个任务只读一次 settings.json,预筛参数和数据源模式共享同一次读取
        # 结果——既省一次冗余 IO,也保证任务内所有平台看到的是同一份配置快照
        # (不会出现同一个 job 里第一个平台读到 local、第二个平台读到
        # tikhub_api 这种因为设置在任务运行期间被改动导致的"半路换源")。
        try:
            from csm_core.config import get_config

            cfg = get_config()
        except Exception:
            logger.info("[runner] config read failed for job %d, using fallbacks", job_id, exc_info=True)
            cfg = None
        prefilter_top_n, prefilter_threshold = _prefilter_params(cfg)
        mining_storage.mark_started(job_id)
        self.publish("job.started", {"job_id": job_id, "keyword": job["keyword"]})

        data_source_mode = _data_source_mode(cfg)

        # D1: TikHub 每平台单次采集有硬顶（HARD_CAP=80，见 tikhub_search.py）——
        # 用户在 UI 上选的 target_per_platform 可以到 200，但 tikhub_api 模式下
        # 适配器内部会自己把它砍到 80。如果 runner 这里继续把 200 当"满进度"的
        # 分母写进 progress，一个已经跑完、拿到 80 条的 job 在进度条上会停在
        # 80/200=40%,看起来像卡住/失败,而不是"已完成"。eff_target 就是这个
        # 任务在当前数据源模式下真正能达到的分母,job 内三平台同一数据源
        # （data_source_mode 只读一次），所以 eff_target 只需算一次。
        job_target = int(job["target_per_platform"])
        if data_source_mode == "tikhub_api":
            from csm_core.mining.platforms.tikhub_search import HARD_CAP
            eff_target = min(job_target, HARD_CAP)
        else:
            eff_target = job_target

        # L1: 任务级余额短路——进程级闩（client.balance_exhausted）每 60s 被
        # monitor 调度器重置一次,不能拿它本身当"这个任务该不该继续"的判据
        # （一个陈旧的、已经过期的 402 不该拦住全新任务；但同一个任务内,
        # platform 1 撞了 402 之后,platform 2/3 应该立刻短路,不管 60s 重置
        # 会不会在两个平台之间发生）。job_latched 是这个 job 自己的本地状态：
        # 循环开始时永远是 False（不看进场时进程闩是什么状态),只在"这个任务
        # 自己的某次 adapter.search() 调用之后发现闩被置位了"才置 True。
        job_latched = False

        for platform in job["platforms"]:
            if cancel_event.is_set():
                mining_storage.update_platform_progress(
                    job_id, platform, got=0, target=eff_target, phase="cancelled",
                )
                continue

            if job_latched:
                mining_storage.update_platform_progress(
                    job_id, platform, got=0, target=eff_target,
                    phase="failed", note="TikHub 余额不足（本任务后续平台短路，未发请求）",
                )
                self.publish("job.platform_done", {
                    "job_id": job_id, "platform": platform,
                    "status": "failed", "count": 0,
                    "error": "TikHub 余额不足（本任务短路）",
                })
                continue

            try:
                adapter = get_adapter(platform, data_source_mode)
            except Exception as e:  # noqa: BLE001 — 未知平台/构建失败只记该平台 failed,不崩整个 job
                logger.exception("get_adapter(%s, %s) failed", platform, data_source_mode)
                reason = f"平台适配器构建失败：{type(e).__name__}"
                mining_storage.update_platform_progress(
                    job_id, platform, got=0, target=eff_target, phase="failed", note=reason,
                )
                self.publish("job.platform_done", {
                    "job_id": job_id, "platform": platform,
                    "status": "failed", "count": 0, "error": reason,
                })
                continue
            emitted = [0]
            # 每张卡的发布节流状态,平台之间必须重置——否则第二个平台会带着
            # 第一个平台"已经发布过"的计数/时间戳基线起步,导致它自己的早期
            # scrolling 进度被节流阈值吞掉,一条都发不出来。
            last_pub_time = [0.0]
            last_pub_count = [0]

            def _on_card(card: VideoCard, platform=platform, emitted=emitted) -> None:
                # 先计数,再去重/入库:emitted 记录的是"适配器交给我们的卡数",
                # 与 adapter 自身的 cards_emitted / 在制 got 同一语义——不管这张
                # 卡最终有没有被去重跳过、有没有 upsert 成功都要计入,否则采集
                # 进度看起来比实际吞吐慢一大截。
                # platform / emitted 都以默认参数显式绑定各自平台的值(而不是
                # 靠闭包晚绑定引用 run() 作用域里的同名变量)——晚绑定的话,一旦
                # 某个平台的适配器把 on_card 缓存下来、在后续平台的循环体里才
                # 真正调用它,这次调用会被错误地记到"当前正在跑的平台"头上,
                # 而不是这个 on_card 本来所属的平台。
                emitted[0] += 1
                try:
                    conn = mining_storage.get_conn()
                    if mining_storage.is_video_tracked_anywhere(conn, card.platform, card.platform_video_id):
                        logger.info(
                            "[runner] skipped_dup platform=%s video_id=%s",
                            card.platform, card.platform_video_id,
                        )
                        return
                except Exception:
                    # get_conn() 本身失败(如 DB 被锁)也走这条路径:记日志、
                    # 落到下面的 upsert try(它会再拿一次 conn),而不是让异常
                    # 逃出 on_card、击穿 adapter.search()。
                    logger.exception(
                        "dedup check failed for %s/%s, falling through to upsert",
                        card.platform, card.platform_video_id,
                    )
                try:
                    mining_storage.upsert_video_and_link(card, job_id)
                except Exception as e:
                    logger.exception("upsert_video_and_link failed: %s", e)

            def _on_progress(
                pu: ProgressUpdate, platform=platform,
                last_pub_time=last_pub_time, last_pub_count=last_pub_count,
            ) -> None:
                # last_pub_time/last_pub_count 同样必须显式绑成默认参数(同
                # _on_card 那一条注释里说的晚绑定坑)——否则这个闭包存活到
                # 下一个平台的循环体时,读到的会是下一个平台新建的节流状态
                # 列表,而不是自己定义时捕获的那一份。
                mining_storage.update_platform_progress(
                    job_id, platform,
                    got=pu.got, target=pu.target, phase=pu.phase, note=pu.note,
                )
                now = time.monotonic()
                if (
                    pu.phase != "scrolling"
                    or pu.got - last_pub_count[0] >= PUBLISH_EVERY_N_CARDS
                    or now - last_pub_time[0] >= PUBLISH_EVERY_N_SECONDS
                ):
                    last_pub_count[0] = pu.got
                    last_pub_time[0] = now
                    self.publish("job.progress", {
                        "job_id": job_id, "platform": platform, "phase": pu.phase,
                        "got": pu.got, "target": pu.target, "note": pu.note,
                    })
                if pu.phase == "needs_login":
                    self.publish("login.required", {"job_id": job_id, "platform": platform})

            try:
                outcome: SearchOutcome = adapter.search(
                    keyword=job["keyword"],
                    target_count=eff_target,
                    on_card=_on_card,
                    on_progress=_on_progress,
                    cancel_event=cancel_event,
                    filters=filters,
                )
            except Exception as e:
                logger.exception("adapter %s threw — recording as failed", platform)
                mining_storage.update_platform_progress(
                    job_id, platform,
                    got=emitted[0], target=eff_target,
                    phase="failed", note=str(e)[:200],
                )
                self.publish("job.platform_done", {
                    "job_id": job_id, "platform": platform,
                    "status": "failed", "count": emitted[0], "error": str(e)[:200],
                })
                if data_source_mode == "tikhub_api" and balance_exhausted():
                    job_latched = True
                continue

            # Brand pre-filter pass — only when the search completed successfully
            # and brand keywords are configured. Runs BEFORE the final "done"
            # progress write so any transient "prefilter" phase is overwritten.
            if outcome.status == "done" and brand_keywords:
                try:
                    vids = mining_storage.videos_for_prefilter(job_id, platform)
                    for i, v in enumerate(vids):
                        if cancel_event.is_set():
                            break
                        # Transient prefilter progress — will be overwritten by
                        # the final "done" write below, keeping phase integrity.
                        mining_storage.update_platform_progress(
                            job_id, platform,
                            got=i, target=len(vids),
                            phase="prefilter", note="筛重复评论",
                        )
                        self.publish("job.progress", {
                            "job_id": job_id, "platform": platform,
                            "phase": "prefilter", "got": i, "target": len(vids),
                            "note": "筛重复评论",
                        })
                        comments = fetch_video_comments(
                            platform, v["url"], limit=prefilter_top_n,
                        )
                        if not comments:
                            # fail-open：抓不到评论 → 不排除，且不写 brand_comment_hits（保持 NULL=未检查，
                            # 区别于「检查过、0 条品牌评论」的 0）。
                            continue
                        # 快照持久化（排除与否都存）：AI 生成环节复用当
                        # 评论区语料，免二次抓取；被排除的视频 UI 可回看
                        # 命中了哪条评论。
                        try:
                            mining_storage.set_top_comments(v["id"], comments)
                        except Exception:
                            logger.exception(
                                "[runner] set_top_comments failed video=%s", v["id"],
                            )
                        texts = [c["text"] for c in comments]
                        hits = count_brand_hits(texts, brand_keywords)
                        if hits >= prefilter_threshold:
                            mining_storage.mark_brand_excluded(v["id"], hits)
                        else:
                            mining_storage.set_brand_hits(v["id"], hits)
                except Exception:
                    logger.exception(
                        "[runner] prefilter pass failed for platform=%s job=%s",
                        platform, job_id,
                    )
                # No finally needed — the "done" progress write below always
                # restores the correct phase, whether prefilter ran or not.

            # Final platform progress with outcome status.
            # For status=="done" this always writes phase="done", which
            # overwrites any transient "prefilter" phase written above.
            # R7: outcome.error_message is an adapter-internal diagnostic —
            # on the local (browser) path it's raw English text meant for
            # logs (e.g. "no SESSDATA in bilibili profile", "search GET
            # failed: <exception incl. URL+keyword>") and must never reach
            # the UI/DB; only the TikHub path's messages are user-facing
            # Chinese strings safe to persist.
            mining_storage.update_platform_progress(
                job_id, platform,
                got=outcome.cards_emitted,
                target=eff_target,
                phase=outcome.status if outcome.status != "done" else "done",
                note=(outcome.error_message or "")[:200]
                if (data_source_mode == "tikhub_api" or platform in _TIKHUB_ONLY_PLATFORMS) else "",
            )
            self.publish("job.platform_done", {
                "job_id": job_id, "platform": platform,
                "status": outcome.status, "count": outcome.cards_emitted,
                "error": outcome.error_message,
            })

            if data_source_mode == "tikhub_api" and balance_exhausted():
                job_latched = True

        try:
            summary = mining_storage.finalize_job(job_id)
            self.publish("job.finished", {"job_id": job_id, "summary": summary})
        finally:
            # Always reap the cancel Event, even if finalize_job/publish raised.
            # Previously a SQL error in finalize_job would skip this and leak
            # one threading.Event per failed job for the sidecar lifetime.
            with self._lock:
                self._cancel_events.pop(job_id, None)
