"""geo_query adapter —— 批量关键词 × 多 AI 平台 fan-out 卡位监控。

fetch() 对 keywords × platforms 做笛卡尔积，逐 cell：provider 采集 →
LLM 抽取 → 信源分类 → 累积 GeoCell。cell 级错误隔离（单 cell 失败记
status 继续）。结束后聚合四大 KPI 写 MonitorResult.metric，明细落
geo_cells/geo_citations。复用 baidu 的 progress_cb / maybe_cancel /
resume_from 约定。

**持久化约定**：fetch() 像 baidu_keyword 一样**只返回** MonitorResult，
由 monitor_loop._run_one 调 save_result 持久化一次。adapter 自己**不**调
save_result —— 否则会与 loop 双写 monitor_results（一行被 geo_cells 引用、
一行带 alert 标志成孤儿，共享 checked_at 时下钻/latest 取行不确定）。
geo 明细则用 adapter 盖的同一个 ``checked_at`` 关联（record_run），不靠
monitor_results.id 外键。

全失败保护：若所有 cell 都失败，返回 status="failed"（而非 ok+rank=-1），
避免 notify 误报"排名跌出 Top-N"。

签名约定对齐 baidu_keyword.fetch —— progress_cb / cancel_token /
resume_from 都是 keyword-only（``*`` 之后），与 monitor_loop 的分发方式
一致。
"""
from __future__ import annotations
import logging
import threading
from datetime import datetime
from typing import Any, Callable

from ..base import MonitorTask, MonitorResult, maybe_cancel
from ..geo.models import GeoCell
from ..geo.providers.base import get_provider
from ..geo.extract import extract, build_extract_client
from ..geo import metrics
from ..geo import storage as geo_storage

logger = logging.getLogger(__name__)


class GeoQueryAdapter:
    platform = "geo_query"

    def fetch(
        self,
        task: MonitorTask,
        *,
        progress_cb: "Callable[[int, int], None] | None" = None,
        cancel_token: "threading.Event | None" = None,
        resume_from: int = 0,
    ) -> MonitorResult:
        cfg = task.config or {}
        brand = str(cfg.get("brand", "")).strip()
        aliases = list(cfg.get("brand_aliases", []) or [])
        keywords = [k for k in (cfg.get("keywords") or []) if str(k).strip()]
        platforms = list(cfg.get("platforms") or [])
        web_search = bool(cfg.get("web_search", True))
        extract_provider = str(cfg.get("extract_provider") or "mock")

        if not brand or not keywords or not platforms:
            return MonitorResult(task_id=task.id or 0, checked_at=datetime.utcnow(),
                                 status="failed", rank=-1,
                                 error_message="geo_query 配置缺 brand/keywords/platforms")

        cells_plan = [(kw, plat) for kw in keywords for plat in platforms]
        total = len(cells_plan)

        # 抽取 client 建一次（失败 → 整体失败，因为每个 cell 都要用）
        try:
            client = build_extract_client(extract_provider)
        except Exception as e:
            return MonitorResult(task_id=task.id or 0, checked_at=datetime.utcnow(),
                                 status="failed", rank=-1, error_message=f"抽取 client: {e}")

        # Clamp resume_from to valid range so callers don't need to guard.
        resume_from = max(0, min(int(resume_from), total))

        # Emit an initial progress event up-front (mirror baidu) so the UI
        # shows the total immediately instead of an empty bar until the
        # first cell finishes. Wrapped — a flaky sink must never kill fetch.
        if progress_cb is not None:
            try:
                progress_cb(resume_from, total)
            except Exception:
                logger.exception("[geo] progress_cb(resume_from,N) raised; ignoring")

        cells: list[GeoCell] = []
        for i, (kw, plat) in enumerate(cells_plan):
            if i < resume_from:
                continue
            maybe_cancel(cancel_token)
            cell = self._run_cell(kw, plat, brand, aliases, web_search, client)
            cells.append(cell)
            if progress_cb is not None:
                try:
                    progress_cb(i + 1, total)
                except Exception:
                    logger.exception("[geo] progress_cb(%s,%s) raised; ignoring", i + 1, total)

        agg = metrics.aggregate(cells)
        # I2：把"够不到平台"和"曝光低"区分开 —— error_cells 让仪表盘知道
        # 是采集失败还是真没提及（现由 metrics._block 算出：total-ok_total，
        # cell 只会是 ok/error/blocked，无 empty，等价旧的 error+blocked 计数）。
        # I3：续抓标记，让 UI 知道这次只跑了断点之后。
        agg["partial_resume"] = resume_from > 0
        rank = metrics.representative_rank(cells)

        # checked_at 算一次，同时盖在 MonitorResult 和这批 cell 上 —— 这是
        # geo 表与本次运行的关联键（不靠 monitor_results.id 外键）。
        checked_at = datetime.utcnow()

        # I1：全失败 → status=failed，避免误报"排名跌出 Top-N"告警。
        # （notify.should_alert 在 status != "ok" 时直接 return False —— 已核实。）
        # 即便整体失败也照样 record_run 这批 cell，数据不丢。
        ok_cells = sum(1 for c in cells if c.status == "ok")
        if cells and ok_cells == 0:
            first_err = next(
                (c.raw.get("error") for c in cells if c.status in ("error", "blocked")),
                "全部平台采集失败",
            )
            result = MonitorResult(
                task_id=task.id or 0, checked_at=checked_at,
                status="failed", rank=-1, metric=agg,
                error_message=f"geo_query 全部 cell 失败：{first_err}",
            )
        else:
            result = MonitorResult(
                task_id=task.id or 0, checked_at=checked_at,
                status="ok", rank=rank, metric=agg,
            )

        # 明细落 geo_cells/geo_citations，用同一个 checked_at 关联。
        # adapter 不再 save_result —— monitor_loop._run_one 持久化 result（一次）。
        geo_storage.record_run(task.id or 0, checked_at, cells)
        return result

    def _run_cell(
        self,
        keyword: str,
        platform: str,
        brand: str,
        aliases: list[str],
        web_search: bool,
        client: Any,
    ) -> GeoCell:
        try:
            provider = get_provider(platform)
            answer = provider.query(keyword, web_search=web_search)
            if answer.status in ("error", "blocked"):
                return GeoCell(platform=platform, keyword=keyword, status=answer.status,
                               answer_text="", raw={"error": answer.error})
            ext = extract(answer, brand=brand, aliases=aliases, client=client)
            return GeoCell(
                platform=platform, keyword=keyword,
                mentioned=ext.mentioned, rank=ext.target_rank, sentiment=ext.sentiment,
                answer_text=answer.answer_text, status="ok", raw=answer.raw,
                citations=ext.citations, recommended=ext.recommended, summary=ext.summary)
        except Exception as e:                       # cell 级隔离
            # logger.exception 抓 traceback（漏检 debug 用）；raw 存 repr(e)
            # 保留异常类型（不止 message），下钻时能区分 TimeoutError vs ValueError。
            logger.exception("[geo] cell 失败 kw=%s plat=%s", keyword, platform)
            return GeoCell(platform=platform, keyword=keyword, status="error",
                           raw={"error": repr(e)})


ADAPTER = GeoQueryAdapter()
