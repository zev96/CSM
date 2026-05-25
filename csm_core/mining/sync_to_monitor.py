# csm_core/mining/sync_to_monitor.py
"""mining → monitor 单向同步。

输入：mining_job_id + 同步参数（任务名前缀、top_n、schedule_cron）
输出：SyncResult{created, skipped_dup, skipped_no_draft, errors}

约束：
- 只同步该 job 的 videos
- 每条 video 取 tier=1 的 video_comments；text 为空也算"无草稿"
- 跳过已在 monitor_tasks 出现的 (platform, video_id)
- 单条失败不中断整批，收集到 errors[]
- 新创 monitor_tasks 一律 enabled=False
"""
from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass, field

from csm_core.mining.config import DEFAULT_MONITOR_SCRAPE_TOP_N, DEFAULT_MONITOR_TOP_N
from csm_core.mining.storage import is_video_in_monitor_tasks

logger = logging.getLogger(__name__)


@dataclass
class SyncParams:
    task_name_prefix: str
    top_n: int = DEFAULT_MONITOR_TOP_N
    scrape_top_n: int = DEFAULT_MONITOR_SCRAPE_TOP_N
    schedule_cron: str | None = None  # None = 手动


@dataclass
class SyncResult:
    created: int = 0
    skipped_dup: int = 0
    skipped_no_draft: int = 0
    errors: list[dict] = field(default_factory=list)


def run(
    conn: sqlite3.Connection,
    job_id: int,
    params: SyncParams,
) -> SyncResult:
    rows = conn.execute(
        """
        SELECT v.id, v.platform, v.platform_video_id, v.url, v.title,
               vc.text AS comment_text
        FROM videos v
        JOIN video_source_keywords vsk ON vsk.video_id = v.id
        LEFT JOIN video_comments vc
          ON vc.video_id = v.id AND vc.tier = 1
        WHERE vsk.job_id = ?
        GROUP BY v.id
        """,
        (job_id,),
    ).fetchall()

    result = SyncResult()
    for row in rows:
        video_id = row[0]
        platform = row[1]
        platform_video_id = row[2]
        url = row[3]
        title = row[4]
        comment_text_raw = row[5]

        try:
            # 同步时只需查 monitor_tasks（video 必在 videos 表里）
            if is_video_in_monitor_tasks(conn, platform, platform_video_id):
                result.skipped_dup += 1
                continue

            comment_text = (comment_text_raw or "").strip()
            if not comment_text:
                result.skipped_no_draft += 1
                continue

            task_type = f"{platform}_comment"
            name = f"{params.task_name_prefix} - {(title or '')[:30]}"
            config_json = json.dumps({
                "my_comment_text": comment_text,
                "top_n": params.top_n,
                "scrape_top_n": params.scrape_top_n,
            })

            schedule_cron = params.schedule_cron if params.schedule_cron is not None else "manual"
            conn.execute(
                """
                INSERT INTO monitor_tasks(type, name, target_url, config_json,
                                          schedule_cron, enabled)
                VALUES (?, ?, ?, ?, ?, 0)
                """,
                (task_type, name, url, config_json, schedule_cron),
            )
            result.created += 1
        except Exception as e:
            logger.exception("sync video_id=%s failed", video_id)
            result.errors.append({"video_id": video_id, "reason": str(e)})

    logger.info(
        "[sync_to_monitor] job_id=%d created=%d skipped_dup=%d "
        "skipped_no_draft=%d errors=%d",
        job_id, result.created, result.skipped_dup,
        result.skipped_no_draft, len(result.errors),
    )
    return result
