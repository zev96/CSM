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
  评论A的图片/… (该层挂图 → 图片本体直接插进该格) | 日期(2026年9月1日)
  截图列由兼职回填，不写。层数 = 表头里 评论X 列的数量（不再硬顶 3 层）。

贴图列（评论楼层的图片）：
  - ``tencent_docs.sync_images`` 开 + 服务端 tools/list 有 ``insert_image`` → 该层每张
    挂图按 base64 插进对应贴图格（一格多图时叠放在同一格，兼职可拖开）；
  - 工具缺席 / 开关关 → 该格写「有图，另发」标记（旧行为，图走手机直发）；
  - 单张插入失败（网络 / 文件缺失 / 超大）→ 计 images_failed；该格一张都没成功时
    补写标记，绝不让一条有图评论在表格里"看起来没图"。
  - 表头没有该层贴图列 → 图片无处可放，计 images_dropped（正文保持干净）。
"""
from __future__ import annotations

import base64
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

from csm_core.config import SheetColumnOverride, TencentDocsConfig, read_api_key
from csm_core.mining import storage as mining_storage
from csm_core.sync.tencent_docs import (
    INSERT_IMAGE_TOOL,
    ROLE_KEYS,
    ColumnMap,
    SheetTarget,
    TencentDocsError,
    TencentDocsMCPClient,
    TokenInvalidError,
    append_rows_csv,
    apply_column_overrides,
    build_column_map_auto,
    describe_columns,
    insert_image,
    list_sheets,
    max_tier,
    paint_row_background,
    parse_doc_url,
    pick_fallback_sheet,
    pick_sheet_by_name,
    read_column_texts,
    read_row_texts,
    write_cell_text,
)

from . import config_service, mining_images_service

logger = logging.getLogger(__name__)

KEYRING_PROVIDER = "tencent_docs"
_IMG_MARKER = "有图，另发"
# 必需列缺失时给用户看的名字（同时列出旧惯例与新惯例）
_REQUIRED_LABELS = {
    "url": "链接（或 视频链接 / 文章链接）",
    "tier1": "评论A（或 内容一）",
}
_PLATFORM_ORDER = ("douyin", "bilibili", "kuaishou", "xiaohongshu")
_PLATFORM_LABEL = {"douyin": "抖音", "bilibili": "B站", "kuaishou": "快手", "xiaohongshu": "小红书"}
# 单张插图上限：本地上传本就封顶 5MB，这里再留一点余量给 base64 膨胀（×4/3）+ JSON-RPC
# 信封；超过直接按"插入失败"计数并回落标记，省一次注定超限的请求。
_MAX_INSERT_IMAGE_BYTES = 4 * 1024 * 1024

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


def _override_key(file_id: str, sheet_id: str) -> str:
    return f"{file_id}:{sheet_id}"


def _column_map_for(
    td: TencentDocsConfig, file_id: str, sheet_id: str, header: list[str],
) -> ColumnMap:
    """自动识别 + 该子表的手动映射覆盖（快照校验不过 → 作废，override_stale 置位）。"""
    cmap = build_column_map_auto(header, td.col_map)
    ov = td.sheet_col_overrides.get(_override_key(file_id, sheet_id))
    if ov is not None and ov.mapping:
        apply_column_overrides(cmap, header, td.col_map, dict(ov.mapping), ov.header or None)
    return cmap


def _sheet_report(
    td: TencentDocsConfig, file_id: str, target: SheetTarget,
    header: list[str], cmap: ColumnMap,
) -> dict[str, Any]:
    """「识别表头」/「测试连接」共用的单子表报告。"""
    return {
        "sheet_id": target.sheet_id,
        "sheet_name": target.sheet_name,
        "header": header,
        "columns": describe_columns(header, cmap),
        "mapping": dict(cmap.by_key),
        "missing": [_REQUIRED_LABELS.get(k, k) for k in cmap.missing],
        "optional_missing": [td.col_map.get(k, k) for k in cmap.optional_missing],
        "tier_gaps": cmap.tier_gaps,
        "tiers_detected": max_tier(cmap),
        # 有评论层列但没有对应贴图列的层号——同步时该层挂图无处可放（images_dropped）。
        "image_cols_missing": [
            n for n in range(1, max_tier(cmap) + 1)
            if cmap.col(f"tier{n}") is not None and cmap.col(f"img{n}") is None
        ],
        "has_override": _override_key(file_id, target.sheet_id) in td.sheet_col_overrides,
        "override_stale": cmap.override_stale,
    }


def _load_sheet_state(
    client: TencentDocsMCPClient, target: SheetTarget, td: TencentDocsConfig, file_id: str,
) -> _SheetState:
    header = read_row_texts(client, target, 0)
    cmap = _column_map_for(td, file_id, target.sheet_id, header)
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


def _image_b64(image_id: str) -> str | None:
    """本地图片 → base64 文本；缺文件 / 读失败 / 超大 → None（调用方计 images_failed）。"""
    path = mining_images_service.get_image_path(image_id)
    if path is None:
        logger.info("[tdocs] image %s not found on disk", image_id)
        return None
    try:
        data = path.read_bytes()
    except OSError:
        logger.info("[tdocs] image %s unreadable", image_id, exc_info=True)
        return None
    if not data or len(data) > _MAX_INSERT_IMAGE_BYTES:
        logger.info("[tdocs] image %s skipped: %d bytes", image_id, len(data))
        return None
    return base64.b64encode(data).decode("ascii")


def _insert_images(
    client: TencentDocsMCPClient,
    target: SheetTarget,
    row_start: int,
    pending: list[tuple[int, int, list[str]]],
) -> tuple[int, int]:
    """把 pending [(行偏移, 贴图列, image_ids)] 逐张插进表格。返回 (成功张数, 失败张数)。

    单张失败（文件缺失 / 超大 / 服务端拒绝）只计数、继续下一张；某一格一张都没成功时
    补写「有图，另发」标记（补写本身也 fail-open）。token 失效原样上抛——继续插只会
    张张失败，且本次同步不应被标 synced。
    """
    inserted = failed = 0
    for offset, col, image_ids in pending:
        row = row_start + offset
        ok_any = False
        for image_id in image_ids:
            b64 = _image_b64(image_id)
            if b64 is None:
                failed += 1
                continue
            try:
                insert_image(client, target, row, col, b64)
            except TokenInvalidError:
                raise
            except TencentDocsError:
                logger.info("[tdocs] insert_image failed row=%d col=%d image=%s",
                            row, col, image_id, exc_info=True)
                failed += 1
                continue
            inserted += 1
            ok_any = True
        if not ok_any:
            try:
                write_cell_text(client, target, row, col, _IMG_MARKER)
            except TencentDocsError:
                logger.info("[tdocs] marker fallback failed row=%d col=%d", row, col, exc_info=True)
    return inserted, failed


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
                        header, _column_map_for(td, file_id, target.sheet_id, header),
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
                    "matched_by_name": named is not None,
                    **_sheet_report(td, file_id, target, header, cmap),
                })
        except TokenInvalidError:
            raise
        except TencentDocsError as e:
            _augment_with_tools(e, available_tools)
            raise

    ok = all(not p["missing"] for p in per_platform)
    return {
        "ok": ok,
        "sheets": per_platform,
        # 贴图直传能力：服务端有 insert_image 工具才能把评论图片插进表格，否则同步时
        # 只写「有图，另发」标记。前端据此提示。
        "insert_image_supported": INSERT_IMAGE_TOOL in available_tools,
        "sync_images": bool(td.sync_images),
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


def inspect(doc_url: str | None = None) -> dict[str, Any]:
    """「识别表头」：读表格里**每一张**子表的首行，按列名识别评论 / 图片 / 链接 / 序号 /
    日期列（叠加该子表已保存的手动映射），并标出每个平台会写进哪张子表。

    ``doc_url`` 传了就用它（粘贴链接后先识别再保存），否则用设置里的链接。
    返回给设置页逐列确认；确认后的映射用 ``save_mapping`` 存起来，同步时按它写。
    """
    cfg = config_service.load()
    td = cfg.tencent_docs
    url = (doc_url or td.doc_url or "").strip()
    if not url:
        raise TencentDocsError("请先粘贴表格链接")
    with _build_client() as client:
        available_tools = _discover_tools(client)
        try:
            file_id, url_tab = parse_doc_url(url)
            sheets = list_sheets(client, file_id)
            fallback = pick_fallback_sheet(sheets, url_tab)
            # 平台 → 子表路由（与同步同口径：同名子表优先，否则兜底子表）
            routed: dict[str, list[str]] = {s.sheet_id: [] for s in sheets}
            matched_by_name: dict[str, bool] = {}
            for platform in _PLATFORM_ORDER:
                named = pick_sheet_by_name(sheets, td.sheet_map.get(platform, ""))
                target = named or fallback
                routed[target.sheet_id].append(platform)
                matched_by_name[platform] = named is not None
            reports: list[dict[str, Any]] = []
            for target in sheets:
                header = read_row_texts(client, target, 0)
                cmap = _column_map_for(td, file_id, target.sheet_id, header)
                rep = _sheet_report(td, file_id, target, header, cmap)
                rep["platforms"] = routed[target.sheet_id]
                rep["platform_labels"] = [_PLATFORM_LABEL[p] for p in routed[target.sheet_id]]
                rep["is_fallback"] = target.sheet_id == fallback.sheet_id
                reports.append(rep)
        except TokenInvalidError:
            raise
        except TencentDocsError as e:
            _augment_with_tools(e, available_tools)
            raise
    # 只对"会被写入"的子表要求必需列齐全；纯闲置的子表缺列不算错。
    ok = all(not r["missing"] for r in reports if r["platforms"])
    return {
        "ok": ok,
        "doc_url": url,
        "file_id": file_id,
        "url_tab": url_tab,
        "sheets": reports,
        "matched_by_name": matched_by_name,
        "insert_image_supported": INSERT_IMAGE_TOOL in available_tools,
        "sync_images": bool(td.sync_images),
        "available_tools": available_tools,
    }


def save_mapping(
    file_id: str, sheet_id: str, mapping: dict[str, int | None], header: list[str],
) -> dict[str, Any]:
    """保存一张子表的手动列映射（整份替换）。角色名 / 列号非法直接拒绝。"""
    clean: dict[str, int | None] = {}
    for role, col in (mapping or {}).items():
        if role not in ROLE_KEYS:
            raise ValueError(f"未知角色：{role}")
        if col is None:
            clean[role] = None
            continue
        if isinstance(col, bool) or not isinstance(col, int) or col < 0:
            raise ValueError(f"列号非法：{role}={col!r}")
        if header and col >= len(header):
            raise ValueError(f"列号超出表头范围：{role}={col}")
        clean[role] = col
    dup: dict[int, list[str]] = {}
    for role, col in clean.items():
        if col is not None:
            dup.setdefault(col, []).append(role)
    clash = [roles for roles in dup.values() if len(roles) > 1]
    if clash:
        raise ValueError("同一列不能同时指定成两个角色：" + "、".join("/".join(r) for r in clash))
    cfg = config_service.load()
    cfg.tencent_docs.sheet_col_overrides[_override_key(file_id, sheet_id)] = SheetColumnOverride(
        mapping=clean, header=[str(h or "") for h in header],
    )
    config_service.save(cfg)
    return {"ok": True, "key": _override_key(file_id, sheet_id), "mapping": clean}


def clear_mapping(file_id: str, sheet_id: str) -> dict[str, Any]:
    """删掉该子表的手动映射，回到纯自动识别。"""
    cfg = config_service.load()
    removed = cfg.tencent_docs.sheet_col_overrides.pop(_override_key(file_id, sheet_id), None) is not None
    if removed:
        config_service.save(cfg)
    return {"ok": True, "removed": removed}


def sync_approved(video_ids: list[int] | None = None) -> dict[str, Any]:
    """把已通过的评论按平台路由批量追加到腾讯文档表格。

    Returns
    -------
    {synced_videos, synced_comments, skipped_in_doc, skipped_extra_tiers,
     images_inserted, images_failed, images_unsupported, images_dropped,
     mapping_stale: [sheet_name…]（保存过手动映射但表头已变、本次退回自动识别的子表）,
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
            "skipped_in_doc": 0, "skipped_extra_tiers": 0, "images_dropped": 0,
            "images_inserted": 0, "images_failed": 0, "images_unsupported": 0,
            "mapping_stale": [],
            "batches": [], "batch_id": None,
        }

    by_platform: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        by_platform.setdefault(item["platform"], []).append(item)

    synced_comment_ids: list[int] = []
    skipped_in_doc = 0
    skipped_extra_tiers = 0
    images_dropped = 0
    images_inserted = 0
    images_failed = 0
    images_unsupported = 0
    batches: list[dict[str, Any]] = []
    date_str = _date_str()

    with _build_client() as client:
        # 贴图直传：开关开 + 服务端确有 insert_image 工具。tools/list 探测失败按不支持
        # 处理（回落标记），不让一次诊断请求失败拖垮整批同步。
        use_image_tool = bool(td.sync_images) and INSERT_IMAGE_TOOL in _discover_tools(client)
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
                state = _load_sheet_state(client, target, td, file_id)
                states[target.sheet_id] = state
            cmap = state.cmap
            width = max(cmap.by_key.values()) + 1

            rows: list[list[str]] = []
            block_video_ids: list[int] = []
            block_comment_ids: list[int] = []
            # (行偏移, 贴图列, image_ids)：CSV 写完后逐张插图（行号 = row_start + 偏移）。
            pending_images: list[tuple[int, int, list[str]]] = []
            for item in plat_items:
                # 防双写：该子表「链接」列已出现规范链接 → 本地补标 synced，不写。
                if item["url"] and item["url"] in state.existing_blob:
                    skipped_in_doc += 1
                    synced_comment_ids.extend(
                        c["id"] for c in item["comments"]
                        if cmap.col(f"tier{c['tier']}") is not None
                    )
                    # 超出表头层数的评论在这条分支里也留在 app 内（不标
                    # synced）——同样要计进 skipped_extra_tiers，不然「这批
                    # 还剩几层没进表格」的统计在去重路径上会悄悄漏掉。
                    skipped_extra_tiers += sum(
                        1 for c in item["comments"]
                        if cmap.col(f"tier{c['tier']}") is None
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
                        if img_col is None:
                            # 该层没有贴图列：绝不把内部指示语（「有图，另发」）
                            # 混进评论正文——兼职是原样复制评论文本去发布的，
                            # 混进去的指示语会被公开贴出去。正文保持干净，
                            # 只计数，缺列本身在「测试连接」的
                            # image_cols_missing 里提前提示用户去补配。
                            images_dropped += 1
                        elif use_image_tool:
                            # 图片本体插进贴图格（CSV 写完后再插；格子先留空）。
                            pending_images.append((len(rows), img_col, list(c["image_ids"])))
                        else:
                            row[img_col] = _IMG_MARKER
                            images_unsupported += len(c["image_ids"])
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
            if pending_images:
                ins, fail = _insert_images(client, target, row_start, pending_images)
                images_inserted += ins
                images_failed += fail
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

    mapping_stale = [s.target.sheet_name for s in states.values() if s.cmap.override_stale]
    if mapping_stale:
        logger.warning("[tdocs] manual column mapping stale (header changed) on sheets: %s", mapping_stale)
    batch_row_ids: list[int] = []
    for b in batches:
        batch_row_ids.append(mining_storage.create_sync_batch(
            file_id, b.pop("_sheet_id"), b["row_start"], b["row_end"], b.pop("_video_ids"),
        ))
    marked = mining_storage.mark_comments_synced(synced_comment_ids)
    total_videos = sum(b["videos"] for b in batches)
    logger.info(
        "[tdocs] synced %d videos (%d comments) across %d sheet blocks; %d skipped-in-doc; "
        "images inserted=%d failed=%d unsupported=%d dropped=%d",
        total_videos, marked, len(batches), skipped_in_doc,
        images_inserted, images_failed, images_unsupported, images_dropped,
    )
    return {
        "synced_videos": total_videos,
        "synced_comments": marked,
        "skipped_in_doc": skipped_in_doc,
        "skipped_extra_tiers": skipped_extra_tiers,
        "images_dropped": images_dropped,
        "images_inserted": images_inserted,
        "images_failed": images_failed,
        "images_unsupported": images_unsupported,
        "mapping_stale": mapping_stale,
        "batches": batches,
        "batch_id": batch_row_ids[0] if batch_row_ids else None,
    }
