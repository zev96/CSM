"""表格高层操作：URL 解析、表头列映射、找末行、CSV 追加、区间读取。

行列约定与 sheet-mcp 一致：全部 0-based。

工具名【不带前缀】—— 真服务 tools/list 确认为 ``get_sheet_info`` /
``get_cell_data`` / ``set_range_value_by_csv`` / ``set_cell_style`` /
``insert_image``（sheet 精细编辑引擎的原生名）。曾误加 ``sheet.`` 前缀导致 “tool not found”
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
    # 每个角色的来源："auto"（配置列名精确匹配 / 表头惯例识别）或 "override"
    # （用户在设置页手动指定）。给「识别表头」面板展示用。
    source: dict[str, str] = field(default_factory=dict)
    # 用户保存过手动映射，但表头已经和保存时不一样（列挪位 / 改名 / 删列）——
    # 整份覆盖作废、沿用自动识别；同步结果里报出来让用户重新确认。
    override_stale: bool = False

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


# ── 表头惯例自动发现（2026-09-01 用户拍板的列命名，2026-09-17 放宽）─────────
# 只认列名、不认位置：评论列与图片列不相邻、顺序打乱、中间夹其它列都不影响。
# 层号写法兼容 字母 A–E / 数字 1–5 / 中文 一–五 / 圈号 ①–⑤：
#   评论A · 评论1 · 一楼 · 1楼评论 · 第一层评论 · 楼层1 · 内容一 · 盖楼内容二 → tierN
#   评论A的图片 · 评论1图片 · 一楼图片 · 贴图一 · 图片1 · 第1层图片 · 配图2   → imgN
# 层数由表头实际有几列决定（只有 3 层就只写 3 层）。层号上限 5（对齐生成端）：
# 占位符「评论X」/ 罗马数字「评论Ⅰ」不是具体层号，绝不能误判成不存在的深层列。
# 「截图1-3 / 评论返图 / 执行状态」是兼职回填列，明确排除，不参与识别。
ROLE_TIER_MAX = 5
ROLE_KEYS: frozenset[str] = frozenset(
    {"seq", "url", "date"}
    | {f"tier{n}" for n in range(1, ROLE_TIER_MAX + 1)}
    | {f"img{n}" for n in range(1, ROLE_TIER_MAX + 1)}
)
_NUM_MAP: dict[str, int] = {
    **{c: i + 1 for i, c in enumerate("ABCDE")},
    **{str(i): i for i in range(1, ROLE_TIER_MAX + 1)},
    **{c: i + 1 for i, c in enumerate("一二三四五")},
    **{c: i + 1 for i, c in enumerate("①②③④⑤")},
}
_NUM_CLASS = "A-Ea-e1-5一二三四五①-⑤"
_BRACKET_RE = re.compile(r"[（(【\[][^）)】\]]*[）)】\]]")      # 去掉「评论A（必填）」的括注
_TRAIL_PUNCT_RE = re.compile(r"[：:，,。．.]+$")
# 兼职回填列 / 与评论无关的列：绝不能被识别成任何角色。
_EXCLUDE_RE = re.compile(r"截图|返图|执行|回填|状态|备注")
_IMG_RES = (
    # 评论A的图片 · 评论1图片 · 一楼图片 · 层2配图 · A图片
    re.compile(rf"^(?:评论|楼层|层)?([{_NUM_CLASS}])(?:楼|层)?(?:评论)?的?(?:图片|配图|贴图|图)$"),
    # 贴图一 · 图片1 · 评论图片2 · 评论配图A
    re.compile(rf"^(?:评论|楼层)?(?:图片|配图|贴图|图)([{_NUM_CLASS}])$"),
    # 第1层图片 · 第一楼评论的图片
    re.compile(rf"^第([{_NUM_CLASS}])(?:层|楼)(?:评论)?的?(?:图片|配图|贴图|图)$"),
)
_TIER_RES = (
    re.compile(rf"^评论([{_NUM_CLASS}])$"),                                        # 评论A · 评论1 · 评论一
    re.compile(rf"^([{_NUM_CLASS}])(?:楼|层)(?:评论|内容|文案)?$"),                   # 一楼 · 1楼评论 · 二层内容
    re.compile(rf"^第([{_NUM_CLASS}])(?:层|楼)(?:评论|内容|文案)?$"),                 # 第1层评论 · 第二楼
    re.compile(rf"^(?:盖楼内容|评论内容|评论文案|楼层|文案|盖楼|内容|层)([{_NUM_CLASS}])$"),  # 盖楼内容二 · 内容一 · 楼层1
)
_TIER1_WORDS = frozenset({"评论", "主评", "主评论", "首评", "一级评论", "主楼", "评论内容", "评论文案"})
_ALIASES: dict[str, tuple[str, ...]] = {
    "url": ("链接", "视频链接", "文章链接", "笔记链接", "作品链接", "视频地址", "地址", "url", "URL"),
    "seq": ("序号", "编号"),
    "date": ("日期", "任务日期"),
}
_REQUIRED_KEYS = ("url", "tier1")


def _letter_to_tier(ch: str) -> int:
    return ord(ch.upper()) - ord("A") + 1


def _num(ch: str) -> int | None:
    return _NUM_MAP.get(ch.upper())


def _clean_header(h: str | None) -> str:
    """识别用的规整：NFKC → 去括注 → 去空白 → 去尾部标点。"""
    s = unicodedata.normalize("NFKC", h or "")
    s = _BRACKET_RE.sub("", s)
    s = _WS_RE.sub("", s)
    return _TRAIL_PUNCT_RE.sub("", s)


def classify_header(name: str | None) -> str | None:
    """单个表头文本 → 角色（tierN / imgN / url / seq / date）；认不出 → None。

    评论 / 图片按上面的惯例正则；url / seq / date 按别名全等（大小写不敏感）。
    「截图」「返图」等兼职回填列一律 None。
    """
    s = _clean_header(name)
    if not s or _EXCLUDE_RE.search(s):
        return None
    for rx in _IMG_RES:
        m = rx.match(s)
        if m:
            n = _num(m.group(1))
            return f"img{n}" if n else None
    for rx in _TIER_RES:
        m = rx.match(s)
        if m:
            n = _num(m.group(1))
            return f"tier{n}" if n else None
    if s in _TIER1_WORDS:
        return "tier1"
    low = s.lower()
    for key, names in _ALIASES.items():
        if any(low == n.lower() for n in names):
            return key
    if s.endswith(("链接", "地址")):
        return "url"
    return None


def col_letter(i: int) -> str:
    """0-based 列号 → Excel 列字母（0→A … 26→AA）。"""
    out = ""
    i += 1
    while i > 0:
        i, r = divmod(i - 1, 26)
        out = chr(ord("A") + r) + out
    return out


def role_label(role: str) -> str:
    if role == "url":
        return "链接"
    if role == "seq":
        return "序号"
    if role == "date":
        return "日期"
    if role.startswith("tier"):
        return f"第 {role[4:]} 层评论"
    if role.startswith("img"):
        return f"第 {role[3:]} 层图片"
    return role


def max_tier(cmap: ColumnMap) -> int:
    """表头里最深的评论层（tierN 的最大 N）；没有 → 0。"""
    return max(
        (int(k[4:]) for k in cmap.by_key if k.startswith("tier") and k[4:].isdigit()),
        default=0,
    )


def _normalize_header_cell(h: str | None) -> str:
    """NFKC 规整（全角字母/数字 → 半角，如 评论Ａ → 评论A）再去空白。"""
    return _WS_RE.sub("", unicodedata.normalize("NFKC", h or ""))


def _finalize_column_map(cmap: ColumnMap, col_names: dict[str, str]) -> ColumnMap:
    """重算 missing / optional_missing / tier_gaps（自动识别与人工覆盖后都要跑一遍）。"""
    cmap.missing = [k for k in _REQUIRED_KEYS if k not in cmap.by_key]
    cmap.optional_missing = [
        k for k in col_names if k not in cmap.by_key and k not in _REQUIRED_KEYS
    ]
    cmap.tier_gaps = [
        n for n in range(1, max_tier(cmap) + 1) if f"tier{n}" not in cmap.by_key
    ]
    return cmap


def build_column_map_auto(header: list[str], col_names: dict[str, str]) -> ColumnMap:
    """先按配置列名精确匹配（`build_column_map`），再按表头惯例自动发现补齐。

    发现规则见 ``classify_header``：评论 / 图片列按层号惯例（字母 / 数字 / 中文数字），
    ``链接/视频链接/…`` → ``url``，``序号`` → ``seq``，``日期/任务日期`` → ``date``。
    只认列名不认位置——评论列与图片列不相邻、顺序打乱都无所谓。精确匹配优先
    （不覆盖）；同一角色出现多列时取最靠前的一列。别名之间按 ``_ALIASES`` 里
    tuple 的顺序定优先级（不是表头出现顺序）——同一个 key 的多个别名都出现在
    表头时选优先级最高的那个，并 warn 一下选了哪个。
    ``missing`` 只报必需列（url、tier1）——可选列缺失记进 ``optional_missing``，
    表头断层记进 ``tier_gaps``，两者都不算错，只用于「识别表头」展示告警。
    """
    cmap = build_column_map(header, col_names)
    normalized_header = [_normalize_header_cell(h) for h in header]
    used_cols = set(cmap.by_key.values())

    for i, raw in enumerate(header):
        if i in used_cols:
            continue
        role = classify_header(raw)
        if role and (role.startswith("tier") or role.startswith("img")):
            cmap.by_key.setdefault(role, i)

    for key, names in _ALIASES.items():
        if key in cmap.by_key:
            continue
        lowered = [n.lower() for n in names]
        matched = [i for i, name in enumerate(normalized_header) if name.lower() in lowered]
        if not matched:
            continue
        chosen: int | None = None
        for alias_name in lowered:  # tuple 顺序 = 优先级
            for i in matched:
                if normalized_header[i].lower() == alias_name:
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

    # 链接列兜底：别名都没命中时，任何以「链接 / 地址」结尾的列（如「抖音链接」）
    # 都当链接列——它是必需列，宁可宽一点。
    if "url" not in cmap.by_key:
        used = set(cmap.by_key.values())
        for i, raw in enumerate(header):
            if i not in used and classify_header(raw) == "url":
                cmap.by_key["url"] = i
                break

    cmap.source = {k: "auto" for k in cmap.by_key}
    return _finalize_column_map(cmap, col_names)


def apply_column_overrides(
    cmap: ColumnMap,
    header: list[str],
    col_names: dict[str, str],
    mapping: dict[str, int | None],
    saved_header: list[str] | None = None,
) -> ColumnMap:
    """用户在设置页手动指定的列映射覆盖自动识别（就地修改并返回 cmap）。

    ``mapping``：{role: 列号 | None}，None = 该角色忽略（即使自动识别到了也不写）。
    ``saved_header``：保存映射时的表头快照。给了就逐列校验——任一被指定的列当前
    表头文本与快照不同（列挪位 / 改名 / 删列）→ 整份覆盖作废，``override_stale``
    置位并沿用自动识别；宁可退回自动识别，也不能把评论写进已经不是那一列的格子。
    指定列上原来自动识别到的其它角色让位（一列只能是一个角色）。
    """
    if not mapping:
        return cmap
    cur = [_normalize_header_cell(h) for h in header]
    saved = [_normalize_header_cell(h) for h in saved_header] if saved_header is not None else None
    for role, col in mapping.items():
        if role not in ROLE_KEYS or col is None:
            continue
        if not isinstance(col, int) or col < 0 or col >= len(cur):
            cmap.override_stale = True
            return cmap
        if saved is not None and (col >= len(saved) or cur[col] != saved[col]):
            cmap.override_stale = True
            return cmap
    for role, col in mapping.items():
        if role not in ROLE_KEYS:
            continue
        cmap.by_key.pop(role, None)
        cmap.source.pop(role, None)
        if col is None:
            continue
        for other, c in list(cmap.by_key.items()):
            if c == col:
                del cmap.by_key[other]
                cmap.source.pop(other, None)
        cmap.by_key[role] = col
        cmap.source[role] = "override"
    return _finalize_column_map(cmap, col_names)


def describe_columns(header: list[str], cmap: ColumnMap) -> list[dict[str, Any]]:
    """给「识别表头」面板：逐列 {col, letter, header, role, role_label, source}。"""
    by_col = {c: k for k, c in cmap.by_key.items()}
    out: list[dict[str, Any]] = []
    for i, h in enumerate(header):
        role = by_col.get(i)
        out.append({
            "col": i,
            "letter": col_letter(i),
            "header": (h or "").strip(),
            "role": role,
            "role_label": role_label(role) if role else "",
            "source": cmap.source.get(role) if role else None,
        })
    return out


# ── 插图 ────────────────────────────────────────────────────────────────
# 工具名与参数来自官方 sheetagent 桥接层对 insert_image 的转发（{file_id, sheet_id,
# row_index, col_index, content}，content = 去掉 data: 前缀的 base64 图片本体；
# 另有 image_id 可复用已上传图片，本流程不用）。
INSERT_IMAGE_TOOL = "insert_image"


def insert_image(
    client: TencentDocsMCPClient,
    target: SheetTarget,
    row: int,
    col: int,
    content_b64: str,
) -> None:
    """把一张图片插到 (row, col) 单元格（0-based）。调用方自行 fail-open：单张失败
    回落写文字标记，不阻塞整批同步。"""
    if content_b64.startswith("data:"):
        content_b64 = content_b64.split(",", 1)[-1]
    client.call_tool(INSERT_IMAGE_TOOL, {
        "file_id": target.file_id,
        "sheet_id": target.sheet_id,
        "row_index": int(row),
        "col_index": int(col),
        "content": content_b64,
    })


def write_cell_text(
    client: TencentDocsMCPClient, target: SheetTarget, row: int, col: int, text: str,
) -> None:
    """单格写文本 —— 复用 CSV 批量接口，起点即目标格（插图失败回落标记用）。"""
    append_rows_csv(client, target, row, [[text]], start_col=col)
