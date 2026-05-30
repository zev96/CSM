"""geo_query adapter —— 批量关键词 × 多 AI 平台 fan-out 卡位监控。

fetch() 对 keywords × platforms 做笛卡尔积，逐 cell：provider 采集 →
LLM 抽取 → 信源分类 → 累积 GeoCell。cell 级错误隔离（单 cell 失败记
status 继续）。结束后聚合四大 KPI 写 MonitorResult.metric，明细落
geo_cells/geo_citations。复用 baidu 的 progress_cb / maybe_cancel /
resume_from 约定。

签名约定对齐 baidu_keyword.fetch —— progress_cb / cancel_token /
resume_from 都是 keyword-only（``*`` 之后），与 monitor_loop 的分发方式
一致。
"""
from __future__ import annotations
import logging
import threading
from datetime import datetime
from typing import Callable

from ..base import MonitorTask, MonitorResult, maybe_cancel
from ..geo.models import GeoCell
from ..geo.providers.base import get_provider
from ..geo.extract import extract, build_extract_client
from ..geo import metrics
from ..geo import storage as geo_storage
from .. import storage

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

        cells: list[GeoCell] = []
        for i, (kw, plat) in enumerate(cells_plan):
            if i < resume_from:
                continue
            maybe_cancel(cancel_token)
            cell = self._run_cell(kw, plat, brand, aliases, web_search, client)
            cells.append(cell)
            if progress_cb:
                progress_cb(i + 1, total)

        agg = metrics.aggregate(cells)
        rank = metrics.representative_rank(cells)
        checked_at = datetime.utcnow()
        result = MonitorResult(task_id=task.id or 0, checked_at=checked_at,
                               status="ok", rank=rank, metric=agg)
        # 落库：先存 result 拿 result_id，再 record_run 明细
        result_id = storage.save_result(result)
        geo_storage.record_run(result_id, task.id or 0, cells)
        return result

    def _run_cell(self, keyword, platform, brand, aliases, web_search, client) -> GeoCell:
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
                citations=ext.citations)
        except Exception as e:                       # cell 级隔离
            logger.warning("[geo] cell 失败 kw=%s plat=%s: %s", keyword, platform, e)
            return GeoCell(platform=platform, keyword=keyword, status="error",
                           raw={"error": str(e)})


ADAPTER = GeoQueryAdapter()
