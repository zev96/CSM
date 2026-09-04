"""表格高层操作：URL 解析、表头列映射、找末行、CSV 追加、区间读取。

行列约定与 sheet-mcp 一致：全部 0-based。

工具名【不带前缀】—— 真服务 tools/list 确认为 ``get_sheet_info`` /
``get_cell_data`` / ``set_range_value_by_csv`` / ``set_cell_style``（sheet
精细编辑引擎的原生名）。曾误加 ``sheet.`` 前缀导致 “tool not found”
（官方龙虾 skill 的 mcporter 里 ``sheet-mcp.<tool>`` 是「服务名.工具名」，
CLI 惯例，不是工具真名——照抄成前缀就错了）。别再加回前缀。
"""
from __future__ import annotations

import io
import csv as _csv
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, urlparse

from .client import TencentDocsMCPClient
from .errors import TencentDocsError

logger = logging.getLogger(__name__)

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
    info = client.call_tool("get_sheet_info", {"file_id": file_id})
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
    data = client.call_tool("get_cell_data", {
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
        data = client.call_tool("get_cell_data", {
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
    client.call_tool("set_range_value_by_csv", {
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
    client.call_tool("set_cell_style", {
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
    # 可选列（非 url/tier1）配置了但表头里没找到——不阻断同步，仅用于
    # 「测试连接」的告警展示（例如漏配了 贴图二 列）。
    optional_missing: list[str] = field(default_factory=list)
    # 表头断层：评论层里夹在已发现的最深层之内、但自己缺列的层号
    # （如只有 评论A/评论C → tier_gaps=[2]）。同样只用于展示告警。
    tier_gaps: list[int] = field(default_factory=list)

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


# ── 表头惯例自动发现（2026-09-01 用户拍板的列命名）──────────────────────
# 评论A / 评论B / … → tier1 / tier2 / …；评论A的图片 / 评论A图片 → img1 / …
# 层数由表头实际有几列决定（不再硬顶 3 层）。链接列容忍 链接/视频链接/文章链接。
# 字母上限收窄到 A–E（对齐生成端 5 层评论上限）：占位符文案「评论X」或罗马
# 数字「评论Ⅰ」不是惯例里的具体字母，绝不能被误判成 tier24 / tier9 这种
# 不存在的深层列（那样会让真正该判「无此列」的评论被错误放行去写别处）。
_TIER_RE = re.compile(r"^评论([A-Ea-e])$")
_IMG_RE = re.compile(r"^评论([A-Ea-e])的?图片$")
_ALIASES: dict[str, tuple[str, ...]] = {
    "url": ("链接", "视频链接", "文章链接"),
    "seq": ("序号",),
    "date": ("日期", "任务日期"),
}
_REQUIRED_KEYS = ("url", "tier1")


def _letter_to_tier(ch: str) -> int:
    return ord(ch.upper()) - ord("A") + 1


def max_tier(cmap: ColumnMap) -> int:
    """表头里最深的评论层（tierN 的最大 N）；没有 → 0。"""
    return max(
        (int(k[4:]) for k in cmap.by_key if k.startswith("tier") and k[4:].isdigit()),
        default=0,
    )


def _normalize_header_cell(h: str | None) -> str:
    """NFKC 规整（全角字母/数字 → 半角，如 评论Ａ → 评论A）再去空白。"""
    return _WS_RE.sub("", unicodedata.normalize("NFKC", h or ""))


def build_column_map_auto(header: list[str], col_names: dict[str, str]) -> ColumnMap:
    """先按配置列名精确匹配（`build_column_map`），再按表头惯例自动发现补齐。

    发现规则（NFKC 规整、去空白、字母不分大小写）：``评论X`` → ``tierN``、
    ``评论X的图片`` / ``评论X图片`` → ``imgN``（X=A→1、B→2…），
    ``链接/视频链接/文章链接`` → ``url``，``序号`` → ``seq``，
    ``日期/任务日期`` → ``date``。精确匹配优先（不覆盖）。别名之间按
    ``_ALIASES`` 里 tuple 的顺序定优先级（不是表头出现顺序）——同一个 key
    的多个别名都出现在表头时选优先级最高的那个，并 warn 一下选了哪个。
    ``missing`` 只报必需列（url、tier1）——可选列缺失记进 ``optional_missing``，
    表头断层记进 ``tier_gaps``，两者都不算错，只用于「测试连接」展示告警。
    """
    cmap = build_column_map(header, col_names)
    normalized_header = [_normalize_header_cell(h) for h in header]

    for i, name in enumerate(normalized_header):
        if not name:
            continue
        m = _TIER_RE.match(name)
        if m:
            cmap.by_key.setdefault(f"tier{_letter_to_tier(m.group(1))}", i)
            continue
        m = _IMG_RE.match(name)
        if m:
            cmap.by_key.setdefault(f"img{_letter_to_tier(m.group(1))}", i)

    for key, names in _ALIASES.items():
        if key in cmap.by_key:
            continue
        matched = [i for i, name in enumerate(normalized_header) if name in names]
        if not matched:
            continue
        chosen: int | None = None
        for alias_name in names:  # tuple 顺序 = 优先级
            for i in matched:
                if normalized_header[i] == alias_name:
                    chosen = i
                    break
            if chosen is not None:
                break
        assert chosen is not None  # matched 非空必能命中某个 alias_name
        cmap.by_key[key] = chosen
        if len(matched) > 1:
            seen_names = "、".join(dict.fromkeys(normalized_header[i] for i in matched))
            logger.warning(
                "[tdocs] 表头里 %s 的别名出现了不止一个（%s），按优先级选用第 %d 列",
                key, seen_names, chosen,
            )

    cmap.missing = [k for k in _REQUIRED_KEYS if k not in cmap.by_key]
    cmap.optional_missing = [
        k for k in col_names if k not in cmap.by_key and k not in _REQUIRED_KEYS
    ]
    cmap.tier_gaps = [
        n for n in range(1, max_tier(cmap) + 1) if f"tier{n}" not in cmap.by_key
    ]
    return cmap
