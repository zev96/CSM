"""腾讯文档同步服务（评论工作流 P3）。

「同步已通过」动作：把 review_status='approved' 的评论按兼职表格的
列结构追加到共享在线表格，成功后本地标 synced + 记 sync_batches 对账。

幂等三道闸：
  1. 本地门禁 —— 只取 approved（已 synced 不会再入选）；
  2. 表格回读 —— 追加前读「链接」列，已出现该视频规范链接的行跳过
     （防「写成功但响应丢失」后重试的双写）；
  3. 对账表 —— sync_batches 记录每批写入的行区间，人工可查。

行结构（按列名映射，不假设位置）：
  序号(每批从 1 重排) | 链接(标题+规范链接) | 内容一/盖楼内容二/盖楼内容三 |
  贴图一/二/三(该层挂图时写「有图，另发」，图走手机直发) | 日期(2026.9.1)
  截图1-3 由兼职回填，不写。
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Callable

from csm_core.config import read_api_key
from csm_core.mining import storage as mining_storage
from csm_core.sync.tencent_docs import (
    TencentDocsError,
    TencentDocsMCPClient,
    TokenInvalidError,
    append_rows_csv,
    build_column_map,
    find_last_used_row,
    read_column_texts,
    read_row_texts,
    resolve_sheet,
)

from . import config_service

logger = logging.getLogger(__name__)

KEYRING_PROVIDER = "tencent_docs"
_IMG_MARKER = "有图，另发"
_MAX_TIERS = 3

# 测试注入点：替换成返回假 client 的 factory。
_client_factory: Callable[[str], TencentDocsMCPClient] | None = None


def _build_client() -> TencentDocsMCPClient:
    cfg = config_service.load()
    token = read_api_key(KEYRING_PROVIDER, cfg)
    if _client_factory is not None:
        return _client_factory(token)
    return TencentDocsMCPClient(token)


class TencentDocsDisabledError(Exception):
    """同步未启用/未配置 —— 路由映射 400，前端引导去设置页。"""


def status() -> dict[str, Any]:
    cfg = config_service.load()
    token = read_api_key(KEYRING_PROVIDER, cfg)
    return {
        "enabled": cfg.tencent_docs.enabled,
        "doc_url": cfg.tencent_docs.doc_url,
        "has_token": bool((token or "").strip()),
    }


def test_connection() -> dict[str, Any]:
    """读表头验证连接 + 列映射。成功返回映射详情，失败抛 TencentDocsError。"""
    cfg = config_service.load()
    td = cfg.tencent_docs
    if not td.doc_url.strip():
        raise TencentDocsError("请先粘贴表格链接")
    with _build_client() as client:
        target = resolve_sheet(client, td.doc_url)
        header = read_row_texts(client, target, 0)
        cmap = build_column_map(header, td.col_map)
    return {
        "ok": not cmap.missing,
        "sheet_name": target.sheet_name,
        "sheet_id": target.sheet_id,
        "row_count": target.row_count,
        "header": [h for h in header if h],
        "mapped": {k: td.col_map[k] for k in cmap.by_key},
        "missing": [td.col_map.get(k, k) for k in cmap.missing],
    }


def sync_approved(video_ids: list[int] | None = None) -> dict[str, Any]:
    """把已通过的评论批量追加到腾讯文档表格。

    Returns
    -------
    {synced_videos, synced_comments, skipped_in_doc, skipped_extra_tiers,
     row_start, row_end, batch_id}  （无待同步时 synced_videos=0 直接返回）

    Raises
    ------
    TencentDocsDisabledError  未启用
    TokenInvalidError         无/失效 token
    TencentDocsError          列缺失 / 服务端错误
    """
    cfg = config_service.load()
    td = cfg.tencent_docs
    if not td.enabled:
        raise TencentDocsDisabledError("腾讯文档同步未启用，请先在设置页配置")
    if not td.doc_url.strip():
        raise TencentDocsError("未配置表格链接，请先在设置页粘贴")

    items = mining_storage.list_approved_for_sync(video_ids)
    if not items:
        return {
            "synced_videos": 0, "synced_comments": 0,
            "skipped_in_doc": 0, "skipped_extra_tiers": 0,
            "row_start": -1, "row_end": -1, "batch_id": None,
        }

    with _build_client() as client:
        target = resolve_sheet(client, td.doc_url)
        header = read_row_texts(client, target, 0)
        cmap = build_column_map(header, td.col_map)
        # 最低要求：链接 + 内容一两列必须在（其余缺列只影响对应字段的写入）。
        required_missing = [k for k in ("url", "tier1") if cmap.col(k) is None]
        if required_missing:
            names = "、".join(td.col_map.get(k, k) for k in required_missing)
            raise TencentDocsError(f"表格里找不到必需列：{names}（检查表头或设置页的列名映射）")

        url_col = cmap.col("url")
        existing = read_column_texts(client, target, url_col)  # {row: text}
        last_used = max(existing.keys()) if existing else 0    # 表头行兜底
        existing_blob = "\n".join(existing.values())

        rows: list[list[str]] = []
        synced_video_ids: list[int] = []
        synced_comment_ids: list[int] = []
        skipped_in_doc = 0
        skipped_extra_tiers = 0
        today = datetime.now()
        date_str = f"{today.year}.{today.month}.{today.day}"
        width = max(cmap.by_key.values()) + 1

        for item in items:
            # 防双写：规范链接已出现在表格「链接」列 → 本地补标 synced，不再写。
            if item["url"] and item["url"] in existing_blob:
                skipped_in_doc += 1
                synced_comment_ids.extend(c["id"] for c in item["comments"] if c["tier"] <= _MAX_TIERS)
                continue

            row = [""] * width

            def _put(key: str, value: str) -> None:
                col = cmap.col(key)
                if col is not None:
                    row[col] = value

            _put("seq", str(len(rows) + 1))  # 每批从 1 重排（沿用表内惯例）
            _put("url", f"{item['title']} {item['url']}".strip())
            _put("date", date_str)
            for c in item["comments"]:
                if c["tier"] > _MAX_TIERS:
                    # 表格只有三层结构；更深的楼层留在 app 内（保持 approved）。
                    skipped_extra_tiers += 1
                    continue
                _put(f"tier{c['tier']}", c["text"])
                if c["image_ids"]:
                    _put(f"img{c['tier']}", _IMG_MARKER)
                synced_comment_ids.append(c["id"])
            rows.append(row)
            synced_video_ids.append(item["id"])

        row_start = last_used + 1
        row_end = row_start + len(rows) - 1
        if rows:
            append_rows_csv(client, target, row_start, rows)

    batch_id = None
    if rows:
        batch_id = mining_storage.create_sync_batch(
            target.file_id, target.sheet_id, row_start, row_end, synced_video_ids,
        )
    marked = mining_storage.mark_comments_synced(synced_comment_ids)
    logger.info(
        "[tdocs] synced %d videos (%d comments, %d skipped-in-doc) rows %d..%d",
        len(rows), marked, skipped_in_doc, row_start, row_end,
    )
    return {
        "synced_videos": len(rows),
        "synced_comments": marked,
        "skipped_in_doc": skipped_in_doc,
        "skipped_extra_tiers": skipped_extra_tiers,
        "row_start": row_start if rows else -1,
        "row_end": row_end if rows else -1,
        "batch_id": batch_id,
    }
