"""表格高层操作：URL 解析、表头列映射、找末行、CSV 追加、区间读取。

行列约定与 sheet-mcp 一致：全部 0-based。
"""
from __future__ import annotations

import io
import csv as _csv
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, urlparse

from .client import TencentDocsMCPClient
from .errors import TencentDocsError

# https://docs.qq.com/sheet/DWHhY...?tab=BB08J2 → (file_id, tab)
_SHEET_PATH_RE = re.compile(r"/sheet/([A-Za-z0-9]+)")


def parse_doc_url(url: str) -> tuple[str, str | None]:
    """从在线表格链接解析 (file_id, tab_sheet_id)。

    file_id = 路径 /sheet/ 后的段；tab 查询参数即子表 sheet_id（docs.qq.com
    的 tab= 与 get_sheet_info 返回的 sheet_id 同值）。解析不出 → 抛错。
    """
    u = (url or "").strip()
    m = _SHEET_PATH_RE.search(u)
    if not m:
        raise TencentDocsError(
            "无法从链接解析表格 ID —— 需要形如 https://docs.qq.com/sheet/xxxx 的在线表格链接"
        )
    file_id = m.group(1)
    tab = None
    try:
        qs = parse_qs(urlparse(u).query)
        tab_vals = qs.get("tab") or []
        if tab_vals:
            tab = tab_vals[0]
    except ValueError:
        pass
    return file_id, tab


@dataclass
class SheetTarget:
    file_id: str
    sheet_id: str
    sheet_name: str = ""
    row_count: int = 0
    col_count: int = 0


def list_sheets(client: TencentDocsMCPClient, file_id: str) -> list[SheetTarget]:
    """文档下全部子表。空 → 抛错（无权限/坏链接的统一出口）。"""
    info = client.call_tool("sheet.get_sheet_info", {"file_id": file_id})
    raw = [s for s in (info.get("sheets") or []) if isinstance(s, dict)]
    if not raw:
        raise TencentDocsError("表格里没有任何子表（或无访问权限）")
    return [
        SheetTarget(
            file_id=file_id,
            sheet_id=str(s.get("sheet_id") or ""),
            sheet_name=str(s.get("sheet_name") or ""),
            row_count=int(s.get("row_count") or 0),
            col_count=int(s.get("col_count") or 0),
        )
        for s in raw
    ]


_WS_RE = re.compile(r"\s+")


def pick_sheet_by_name(sheets: list[SheetTarget], name: str | None) -> SheetTarget | None:
    """按子表名匹配（去空白全等：「B站」==「B 站」）。找不到返回 None。"""
    want = _WS_RE.sub("", name or "")
    if not want:
        return None
    for s in sheets:
        if _WS_RE.sub("", s.sheet_name) == want:
            return s
    return None


def pick_fallback_sheet(sheets: list[SheetTarget], tab: str | None) -> SheetTarget:
    """兜底子表：URL 的 tab 命中就用它，否则第一张。"""
    if tab:
        for s in sheets:
            if s.sheet_id == tab:
                return s
    return sheets[0]


def resolve_sheet(client: TencentDocsMCPClient, doc_url: str) -> SheetTarget:
    """URL → 具体子表。tab 参数命中就用它；否则取第一张。"""
    file_id, tab = parse_doc_url(doc_url)
    return pick_fallback_sheet(list_sheets(client, file_id), tab)


# ── 读 ──────────────────────────────────────────────────────────────────

def read_row_texts(
    client: TencentDocsMCPClient, target: SheetTarget, row: int,
) -> list[str]:
    """读一整行的文本值（按列序，空单元格为 ""）。表头解析用。"""
    end_col = max(0, min(target.col_count - 1, 199))
    data = client.call_tool("sheet.get_cell_data", {
        "file_id": target.file_id,
        "sheet_id": target.sheet_id,
        "start_row": row, "start_col": 0,
        "end_row": row, "end_col": end_col,
        "return_csv": False,
    })
    out = [""] * (end_col + 1)
    for c in data.get("cells") or []:
        col = int(c.get("col") or 0)
        if 0 <= col <= end_col:
            out[col] = _cell_text(c)
    return out


def read_column_texts(
    client: TencentDocsMCPClient, target: SheetTarget, col: int,
    *, start_row: int = 0, end_row: int | None = None,
) -> dict[int, str]:
    """读某一列的非空文本 {row: text}。单次请求 ≤20000 格，按 10000 行分片。"""
    last = target.row_count - 1 if end_row is None else end_row
    out: dict[int, str] = {}
    row = start_row
    while row <= last:
        chunk_end = min(last, row + 9999)
        data = client.call_tool("sheet.get_cell_data", {
            "file_id": target.file_id,
            "sheet_id": target.sheet_id,
            "start_row": row, "start_col": col,
            "end_row": chunk_end, "end_col": col,
            "return_csv": False,
        })
        for c in data.get("cells") or []:
            text = _cell_text(c)
            if text:
                out[int(c.get("row") or 0)] = text
        row = chunk_end + 1
    return out


def find_last_used_row(
    client: TencentDocsMCPClient, target: SheetTarget, probe_col: int,
) -> int:
    """以某列（通常是「链接」列）非空为准的最后一行；全空返回 -1。

    表头行也算「已用」—— 追加起点 = 返回值 + 1 天然落在表头之下。
    """
    texts = read_column_texts(client, target, probe_col)
    return max(texts.keys()) if texts else -1


def _cell_text(cell: dict[str, Any]) -> str:
    vt = cell.get("value_type")
    if vt == "NUMBER":
        num = cell.get("number_value")
        if num is None:
            return ""
        # 整数别带 .0（序号列读回来要和写入的对上）
        return str(int(num)) if float(num).is_integer() else str(num)
    if vt == "BOOL":
        return "true" if cell.get("bool_value") else "false"
    return str(cell.get("string_value") or "").strip()


# ── 写 ──────────────────────────────────────────────────────────────────

def append_rows_csv(
    client: TencentDocsMCPClient,
    target: SheetTarget,
    start_row: int,
    rows: list[list[str]],
    *,
    start_col: int = 0,
) -> None:
    """把 rows 以 CSV 批量写到 start_row 起的区域（set_range_value_by_csv）。

    标准 CSV 引号转义交给 csv 模块；服务端会自动做类型识别（纯数字 →
    NUMBER），序号列写数字没问题。空字段服务端跳过、不覆盖已有内容。
    """
    if not rows:
        return
    buf = io.StringIO()
    writer = _csv.writer(buf, lineterminator="\n")
    for r in rows:
        writer.writerow(["" if v is None else str(v) for v in r])
    client.call_tool("sheet.set_range_value_by_csv", {
        "file_id": target.file_id,
        "sheet_id": target.sheet_id,
        "start_row": start_row,
        "start_col": start_col,
        "csv_data": buf.getvalue(),
    })


# 批间分隔行的橙色底（ARGB）—— 对齐用户表格里手工维护的分隔行样式。
SEPARATOR_BG_ARGB = "FFFFC000"


def paint_row_background(
    client: TencentDocsMCPClient,
    target: SheetTarget,
    row: int,
    width: int,
    *,
    bg_argb: str = SEPARATOR_BG_ARGB,
) -> None:
    """给一行前 width 列上背景色（分隔行用）。调用方自行 fail-open。"""
    client.call_tool("sheet.set_cell_style", {
        "file_id": target.file_id,
        "sheet_id": target.sheet_id,
        "start_row": row, "start_col": 0,
        "end_row": row, "end_col": max(0, width - 1),
        "format": {"bg_color": bg_argb},
    })


# ── 列映射 ──────────────────────────────────────────────────────────────

@dataclass
class ColumnMap:
    """表头列名 → 列号。缺列记进 missing，由「测试连接」报给用户。"""
    by_key: dict[str, int] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)

    def col(self, key: str) -> int | None:
        return self.by_key.get(key)


def build_column_map(header: list[str], col_names: dict[str, str]) -> ColumnMap:
    """按配置的列名在表头行里定位列号 —— 只认列名，不假设列的位置。

    匹配口径：去空白全等（「盖楼内容二」==「盖楼内容二 」）。
    """
    normalized = {i: (h or "").strip() for i, h in enumerate(header)}
    cmap = ColumnMap()
    for key, name in col_names.items():
        want = (name or "").strip()
        if not want:
            cmap.missing.append(key)
            continue
        found = None
        for i, h in normalized.items():
            if h == want:
                found = i
                break
        if found is None:
            cmap.missing.append(key)
        else:
            cmap.by_key[key] = found
    return cmap
