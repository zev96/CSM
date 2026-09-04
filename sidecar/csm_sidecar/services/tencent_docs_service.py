"""腾讯文档同步服务（评论工作流 P3）。

「同步已通过」动作：把 review_status='approved' 的评论按兼职表格的
列结构追加到共享在线表格，成功后本地标 synced + 记 sync_batches 对账。

平台路由：表格按平台分子表（抖音/B站/快手 各一张 tab）——同步时按
``TencentDocsConfig.sheet_map`` 的子表名匹配（去空白），把每个平台的
视频写到自己的子表；找不到同名子表回落到 URL tab / 第一张子表。

批次分隔：沿用用户表内惯例 —— 每批数据前留一行空分隔行并涂橙色底
（子表里已有数据行时才留；上一批留下的空分隔行会被复用，不会连着
出现两行）。涂色失败不阻塞同步（fail-open）。

幂等三道闸：
  1. 本地门禁 —— 只取 approved（已 synced 不会再入选）；
  2. 表格回读 —— 追加前读该子表「链接」列，已出现该视频规范链接的跳过
     （防「写成功但响应丢失」后重试的双写）；
  3. 对账表 —— sync_batches 记录每批写入的子表与行区间。

行结构（按列名映射，不假设位置；配置列名精确匹配优先，其余按
``评论A/评论B/…``「评论X的图片」表头惯例自动发现，见
``build_column_map_auto``）：
  序号(每批每平台从 1 重排) | 链接(标题+规范链接) | 评论A/评论B/… |
  评论A的图片/… (该层挂图时写「有图，另发」) | 日期(2026年9月1日)
  截图列由兼职回填，不写。层数 = 表头里 评论X 列的数量（不再硬顶 3 层）。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

from csm_core.config import read_api_key
from csm_core.mining import storage as mining_storage
from csm_core.sync.tencent_docs import (
    ColumnMap,
    SheetTarget,
    TencentDocsError,
    TencentDocsMCPClient,
    TokenInvalidError,
    append_rows_csv,
    build_column_map_auto,
    list_sheets,
    max_tier,
    paint_row_background,
    parse_doc_url,
    pick_fallback_sheet,
    pick_sheet_by_name,
    read_column_texts,
    read_row_texts,
)

from . import config_service

logger = logging.getLogger(__name__)

KEYRING_PROVIDER = "tencent_docs"
_IMG_MARKER = "有图，另发"
# 必需列缺失时给用户看的名字（同时列出旧惯例与新惯例）
_REQUIRED_LABELS = {
    "url": "链接（或 视频链接 / 文章链接）",
    "tier1": "评论A（或 内容一）",
}
_PLATFORM_ORDER = ("douyin", "bilibili", "kuaishou")
_PLATFORM_LABEL = {"douyin": "抖音", "bilibili": "B站", "kuaishou": "快手"}

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


def _date_str() -> str:
    today = datetime.now()
    return f"{today.year}年{today.month}月{today.day}日"


@dataclass
class _SheetState:
    """一张子表在本次同步中的累积状态（多平台可能共用兜底子表）。"""
    target: SheetTarget
    cmap: ColumnMap
    header: list[str]
    existing_blob: str          # 「链接」列已有文本拼串（防双写比对）
    next_row: int               # 下一次写入的行号（0-based）
    batches: list[dict[str, Any]] = field(default_factory=list)


def _load_sheet_state(
    client: TencentDocsMCPClient, target: SheetTarget, col_names: dict[str, str],
) -> _SheetState:
    header = read_row_texts(client, target, 0)
    cmap = build_column_map_auto(header, col_names)
    if cmap.missing:
        names = "、".join(_REQUIRED_LABELS.get(k, k) for k in cmap.missing)
        raise TencentDocsError(f"子表「{target.sheet_name}」里找不到必需列：{names}")
    existing = read_column_texts(client, target, cmap.col("url"))
    last_used = max(existing.keys()) if existing else 0  # 表头行兜底
    return _SheetState(
        target=target,
        cmap=cmap,
        header=header,
        existing_blob="\n".join(existing.values()),
        next_row=last_used + 1,
    )


def _discover_tools(client: TencentDocsMCPClient) -> list[str]:
    """best-effort 枚举服务端工具（tools/list）。token 失效照抛，其余吞掉。"""
    try:
        return client.list_tools()
    except TokenInvalidError:
        raise
    except TencentDocsError:
        logger.info("[tdocs] tools/list 诊断探测失败，忽略", exc_info=True)
        return []


def _augment_with_tools(e: TencentDocsError, tools: list[str]) -> TencentDocsError:
    """把 tools/list 清单挂到错误 reason 上（诊断），保留原异常子类型。"""
    if tools:
        e.reason = (
            f"{e.reason}\n\n【诊断】服务端实际暴露的 MCP 工具（tools/list）：\n"
            f"{'、'.join(tools)}"
        )
        e.args = (e.reason,)
    return e


def test_connection() -> dict[str, Any]:
    """读表头验证连接 + 平台子表路由 + 列映射。失败抛 TencentDocsError。

    诊断：先用 MCP ``tools/list`` 枚举服务端真实工具；若后续 ``sheet.*`` 调用
    因「tool not found」失败，把真实工具清单挂到错误里，便于据实定方案。
    """
    cfg = config_service.load()
    td = cfg.tencent_docs
    if not td.doc_url.strip():
        raise TencentDocsError("请先粘贴表格链接")
    with _build_client() as client:
        available_tools = _discover_tools(client)
        try:
            file_id, url_tab = parse_doc_url(td.doc_url)
            sheets = list_sheets(client, file_id)
            fallback = pick_fallback_sheet(sheets, url_tab)

            header_cache: dict[str, tuple[list[str], ColumnMap]] = {}

            def _check(target: SheetTarget) -> tuple[list[str], ColumnMap]:
                if target.sheet_id not in header_cache:
                    header = read_row_texts(client, target, 0)
                    header_cache[target.sheet_id] = (
                        header, build_column_map_auto(header, td.col_map),
                    )
                return header_cache[target.sheet_id]

            per_platform: list[dict[str, Any]] = []
            for platform in _PLATFORM_ORDER:
                wanted = td.sheet_map.get(platform, "")
                named = pick_sheet_by_name(sheets, wanted)
                target = named or fallback
                header, cmap = _check(target)
                per_platform.append({
                    "platform": platform,
                    "platform_label": _PLATFORM_LABEL[platform],
                    "sheet_name": target.sheet_name,
                    "matched_by_name": named is not None,
                    "missing": [_REQUIRED_LABELS.get(k, k) for k in cmap.missing],
                    "optional_missing": [td.col_map.get(k, k) for k in cmap.optional_missing],
                    "tier_gaps": cmap.tier_gaps,
                    "tiers_detected": max_tier(cmap),
                })
        except TokenInvalidError:
            raise
        except TencentDocsError as e:
            raise _augment_with_tools(e, available_tools) from e

    ok = all(not p["missing"] for p in per_platform)
    return {
        "ok": ok,
        "sheets": per_platform,
        "all_sheet_names": [s.sheet_name for s in sheets],
        # 兼容字段（旧 UI/测试）：取第一个平台的结果
        "sheet_name": per_platform[0]["sheet_name"],
        "header": [h for h in header_cache[fallback.sheet_id][0] if h]
        if fallback.sheet_id in header_cache else [],
        "missing": sorted({m for p in per_platform for m in p["missing"]}),
        "optional_missing": sorted({m for p in per_platform for m in p["optional_missing"]}),
        # 诊断字段：服务端 tools/list 真实工具清单（据实定方案用）
        "available_tools": available_tools,
    }


def sync_approved(video_ids: list[int] | None = None) -> dict[str, Any]:
    """把已通过的评论按平台路由批量追加到腾讯文档表格。

    Returns
    -------
    {synced_videos, synced_comments, skipped_in_doc, skipped_extra_tiers,
     batches: [{platform, sheet_name, row_start, row_end, videos}], batch_id}

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
            "skipped_in_doc": 0, "skipped_extra_tiers": 0, "images_inlined": 0,
            "batches": [], "batch_id": None,
        }

    by_platform: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        by_platform.setdefault(item["platform"], []).append(item)

    synced_comment_ids: list[int] = []
    skipped_in_doc = 0
    skipped_extra_tiers = 0
    images_inlined = 0
    batches: list[dict[str, Any]] = []
    date_str = _date_str()

    with _build_client() as client:
        file_id, url_tab = parse_doc_url(td.doc_url)
        sheets = list_sheets(client, file_id)
        fallback = pick_fallback_sheet(sheets, url_tab)
        states: dict[str, _SheetState] = {}

        for platform in _PLATFORM_ORDER:
            plat_items = by_platform.get(platform)
            if not plat_items:
                continue
            target = pick_sheet_by_name(sheets, td.sheet_map.get(platform, "")) or fallback
            state = states.get(target.sheet_id)
            if state is None:
                state = _load_sheet_state(client, target, td.col_map)
                states[target.sheet_id] = state
            cmap = state.cmap
            width = max(cmap.by_key.values()) + 1

            rows: list[list[str]] = []
            block_video_ids: list[int] = []
            block_comment_ids: list[int] = []
            for item in plat_items:
                # 防双写：该子表「链接」列已出现规范链接 → 本地补标 synced，不写。
                if item["url"] and item["url"] in state.existing_blob:
                    skipped_in_doc += 1
                    synced_comment_ids.extend(
                        c["id"] for c in item["comments"]
                        if cmap.col(f"tier{c['tier']}") is not None
                    )
                    continue

                row = [""] * width

                def _put(key: str, value: str) -> None:
                    col = cmap.col(key)
                    if col is not None:
                        row[col] = value

                _put("seq", str(len(rows) + 1))  # 每批每平台从 1 重排
                _put("url", f"{item['title']} {item['url']}".strip())
                _put("date", date_str)
                for c in item["comments"]:
                    col = cmap.col(f"tier{c['tier']}")
                    if col is None:
                        # 表头没有这一层的「评论X」列（超出层数或表头断层）；
                        # 留在 app 内（保持 approved），不按「最大层号」误判可写。
                        skipped_extra_tiers += 1
                        continue
                    row[col] = c["text"]
                    if c["image_ids"]:
                        img_col = cmap.col(f"img{c['tier']}")
                        if img_col is not None:
                            row[img_col] = _IMG_MARKER
                        else:
                            # 该层没有贴图列：标记并入正文，不让「有图」信息静默消失。
                            row[col] = f"{c['text']}（{_IMG_MARKER}）"
                            images_inlined += 1
                    block_comment_ids.append(c["id"])
                rows.append(row)
                block_video_ids.append(item["id"])

            if not rows:
                continue

            # 批间分隔行：子表里已有数据行（next_row > 1，即表头之外有内容）
            # 时留一行空行并涂橙。上一批若已留过空分隔行（只有底色没文本，
            # 「链接」列读不到）——本行恰好落在它上面，等于复用，不会双空行。
            separator_row: int | None = None
            if state.next_row > 1:
                separator_row = state.next_row
                state.next_row += 1

            row_start = state.next_row
            row_end = row_start + len(rows) - 1
            append_rows_csv(client, target, row_start, rows)
            if separator_row is not None:
                try:
                    paint_row_background(client, target, separator_row, width)
                except TencentDocsError:
                    logger.info("[tdocs] separator styling failed; continuing", exc_info=True)
            state.next_row = row_end + 1
            # 本次已写的链接也进比对串，防同一次同步里跨平台/重复视频再写。
            state.existing_blob += "\n" + "\n".join(
                r[cmap.col("url")] for r in rows if cmap.col("url") is not None
            )

            synced_comment_ids.extend(block_comment_ids)
            batches.append({
                "platform": platform,
                "sheet_name": target.sheet_name,
                "row_start": row_start,
                "row_end": row_end,
                "videos": len(rows),
                "_sheet_id": target.sheet_id,
                "_video_ids": block_video_ids,
            })

    batch_row_ids: list[int] = []
    for b in batches:
        batch_row_ids.append(mining_storage.create_sync_batch(
            file_id, b.pop("_sheet_id"), b["row_start"], b["row_end"], b.pop("_video_ids"),
        ))
    marked = mining_storage.mark_comments_synced(synced_comment_ids)
    total_videos = sum(b["videos"] for b in batches)
    logger.info(
        "[tdocs] synced %d videos (%d comments) across %d sheet blocks; %d skipped-in-doc",
        total_videos, marked, len(batches), skipped_in_doc,
    )
    return {
        "synced_videos": total_videos,
        "synced_comments": marked,
        "skipped_in_doc": skipped_in_doc,
        "skipped_extra_tiers": skipped_extra_tiers,
        "images_inlined": images_inlined,
        "batches": batches,
        "batch_id": batch_row_ids[0] if batch_row_ids else None,
    }
