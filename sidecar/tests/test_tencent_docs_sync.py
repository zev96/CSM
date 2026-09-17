"""P3 腾讯文档同步测试：URL 解析、列映射、MCP 客户端、同步服务全流程。

MCP 服务端全程假实现（httpx.MockTransport / FakeSheetClient），不打网络。
"""
from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from csm_core.mining import storage as ms
from csm_core.monitor import storage as monitor_storage
from csm_core.sync.tencent_docs import (
    TencentDocsError,
    TencentDocsMCPClient,
    TokenInvalidError,
    build_column_map,
    parse_doc_url,
)
from csm_core.sync.tencent_docs.sheet import (
    SheetTarget,
    append_rows_csv,
    find_last_used_row,
    max_tier,
    read_row_texts,
    resolve_sheet,
)
from csm_sidecar.services import config_service, tencent_docs_service as tds


# ── parse_doc_url ──────────────────────────────────────────────────────

def test_parse_doc_url_with_tab():
    fid, tab = parse_doc_url("https://docs.qq.com/sheet/DWHhYWkxjSkJvT0N?tab=BB08J2")
    assert fid == "DWHhYWkxjSkJvT0N"
    assert tab == "BB08J2"


def test_parse_doc_url_without_tab():
    fid, tab = parse_doc_url("https://docs.qq.com/sheet/DAbCdEf123")
    assert fid == "DAbCdEf123"
    assert tab is None


def test_parse_doc_url_invalid():
    with pytest.raises(TencentDocsError):
        parse_doc_url("https://docs.qq.com/doc/DAbc")  # word 文档不是表格
    with pytest.raises(TencentDocsError):
        parse_doc_url("")


# ── build_column_map ───────────────────────────────────────────────────

_USER_HEADER = ["序号", "链接", "内容一", "贴图一", "盖楼内容二", "贴图二",
                "盖楼内容三", "贴图三", "日期", "截图1", "截图2", "截图3"]
_COL_NAMES = {
    "seq": "序号", "url": "链接",
    "tier1": "内容一", "img1": "贴图一",
    "tier2": "盖楼内容二", "img2": "贴图二",
    "tier3": "盖楼内容三", "img3": "贴图三",
    "date": "日期",
}


def test_build_column_map_full_hit():
    cmap = build_column_map(_USER_HEADER, _COL_NAMES)
    assert cmap.missing == []
    assert cmap.col("seq") == 0
    assert cmap.col("url") == 1
    assert cmap.col("tier3") == 6
    assert cmap.col("date") == 8


def test_build_column_map_position_independent():
    """调整列顺序不影响映射 —— 只认列名。"""
    header = ["日期", "链接", "序号", "内容一"]
    cmap = build_column_map(header, {"seq": "序号", "url": "链接", "tier1": "内容一", "date": "日期"})
    assert cmap.col("date") == 0
    assert cmap.col("seq") == 2


def test_build_column_map_whitespace_tolerant_and_missing():
    header = [" 序号 ", "链接"]
    cmap = build_column_map(header, {"seq": "序号", "url": "链接", "tier1": "内容一"})
    assert cmap.col("seq") == 0
    assert cmap.missing == ["tier1"]


from csm_core.sync.tencent_docs import build_column_map_auto


def test_column_map_auto_detects_comment_letters_dynamic_tiers():
    header = ["视频链接", "评论A", "评论A的图片", "评论B", "评论C", "评论D", "评论D的图片"]
    cmap = build_column_map_auto(header, _COL_NAMES)
    assert cmap.col("url") == 0                 # 别名：视频链接
    assert cmap.col("tier1") == 1 and cmap.col("img1") == 2
    assert cmap.col("tier2") == 3 and cmap.col("tier3") == 4
    assert cmap.col("tier4") == 5 and cmap.col("img4") == 6     # 层数由表头决定，不硬顶 3
    assert cmap.missing == []


def test_column_map_auto_tolerates_whitespace_and_lowercase():
    header = ["链接", "评论 a", "评论a图片"]
    cmap = build_column_map_auto(header, _COL_NAMES)
    assert cmap.col("tier1") == 1 and cmap.col("img1") == 2


def test_column_map_auto_legacy_header_still_exact_matches():
    cmap = build_column_map_auto(_USER_HEADER, _COL_NAMES)
    assert cmap.col("tier1") == 2 and cmap.col("img1") == 3 and cmap.col("tier3") == 6
    assert cmap.missing == []


def test_column_map_auto_missing_reports_only_required():
    cmap = build_column_map_auto(["发布类型", "平台", "文章标题"], _COL_NAMES)
    assert cmap.missing == ["url", "tier1"]
    cmap2 = build_column_map_auto(["文章链接"], _COL_NAMES)
    assert cmap2.col("url") == 0 and cmap2.missing == ["tier1"]


def test_column_map_auto_exact_match_wins_over_convention():
    """配置列名精确匹配（内容一）优先于表头惯例发现（评论A），不被后者覆盖。"""
    cmap = build_column_map_auto(["链接", "内容一", "评论A"], _COL_NAMES)
    assert cmap.col("tier1") == 1


def test_column_map_auto_alias_priority_prefers_higher_priority_name():
    """url 的别名 (链接, 视频链接, 文章链接) 按 tuple 顺序定优先级，不是按
    表头出现顺序——「链接」排第一，即使「视频链接」在表头里更靠前也不选它。

    col_names 里不配 "url" 精确匹配目标，逼着走纯别名解析路径（否则
    build_column_map 的精确匹配会先一步命中，测不出别名优先级排序本身）。"""
    cmap = build_column_map_auto(["视频链接", "链接"], {"tier1": "内容一"})
    assert cmap.col("url") == 1


def test_column_map_auto_nfkc_normalizes_fullwidth_letters():
    """全角字母 评论Ａ 经 NFKC 规整后等价于半角 评论A，命中 tier1。"""
    cmap = build_column_map_auto(["链接", "评论Ａ"], _COL_NAMES)
    assert cmap.col("tier1") == 1


def test_column_map_auto_reports_optional_missing_and_tier_gaps():
    """T2：可选列缺失 (optional_missing) 与表头断层 (tier_gaps) 都要能报出来
    （不阻断，只用于「测试连接」告警展示）。"""
    legacy_header_no_tier2 = ["序号", "链接", "内容一", "贴图一", "盖楼内容三", "贴图三", "日期"]
    cmap = build_column_map_auto(legacy_header_no_tier2, _COL_NAMES)
    assert cmap.missing == []
    assert "tier2" in cmap.optional_missing and "img2" in cmap.optional_missing

    gap_cmap = build_column_map_auto(["链接", "评论A", "评论C"], _COL_NAMES)
    assert gap_cmap.tier_gaps == [2]

    full_cmap = build_column_map_auto(_USER_HEADER, _COL_NAMES)
    assert full_cmap.optional_missing == []
    assert full_cmap.tier_gaps == []


def test_column_map_auto_ignores_letters_beyond_e():
    """R6：评论字母上限收窄到 A-E（对齐生成端 5 层评论上限）。超出范围的
    字母（含占位符文案「评论X」）不会被当成 tier 列，不会把 max_tier
    误撑到 24 这种不存在的深层。"""
    header = ["链接", "评论A", "评论B", "评论X"]
    cmap = build_column_map_auto(header, _COL_NAMES)
    assert max_tier(cmap) == 2
    assert cmap.tier_gaps == []


# ── MCP client（httpx.MockTransport）──────────────────────────────────

def _jsonrpc_result(result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": "1", "result": result}


def _mk_client(handler) -> TencentDocsMCPClient:
    return TencentDocsMCPClient("tok-123", transport=httpx.MockTransport(handler))


def test_client_rejects_empty_token():
    with pytest.raises(TokenInvalidError):
        TencentDocsMCPClient("  ")


def test_client_call_tool_json_path():
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "tok-123"  # 原样直传，无 Bearer
        payload = json.loads(request.content or b"{}") if request.content else {}
        seen.append(payload)
        method = payload.get("method")
        if method == "initialize":
            return httpx.Response(200, json=_jsonrpc_result({"serverInfo": {}}),
                                  headers={"Mcp-Session-Id": "sess-1"})
        if method == "notifications/initialized":
            return httpx.Response(202)
        assert request.headers.get("Mcp-Session-Id") == "sess-1"
        return httpx.Response(200, json=_jsonrpc_result({
            "content": [{"type": "text", "text": '{"sheets": [{"sheet_id": "S1"}]}'}],
        }))

    with _mk_client(handler) as client:
        out = client.call_tool("get_sheet_info", {"file_id": "D1"})
    assert out == {"sheets": [{"sheet_id": "S1"}]}
    assert [p.get("method") for p in seen] == [
        "initialize", "notifications/initialized", "tools/call",
    ]


def test_client_call_tool_sse_and_structured():
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content or b"{}") if request.content else {}
        if payload.get("method") != "tools/call":
            return httpx.Response(202)
        body = (
            "event: message\n"
            'data: {"jsonrpc":"2.0","method":"notifications/progress","params":{}}\n\n'
            "event: message\n"
            'data: {"jsonrpc":"2.0","id":"1","result":{"structuredContent":{"ok":1}}}\n\n'
        )
        return httpx.Response(200, content=body,
                              headers={"Content-Type": "text/event-stream"})

    with _mk_client(handler) as client:
        out = client.call_tool("get_cell_data", {})
    assert out == {"ok": 1}


def test_client_maps_token_error():
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content or b"{}") if request.content else {}
        if payload.get("method") != "tools/call":
            return httpx.Response(202)
        return httpx.Response(200, json=_jsonrpc_result({
            "isError": True,
            "content": [{"type": "text", "text": "error 400006: token invalid"}],
        }))

    with _mk_client(handler) as client:
        with pytest.raises(TokenInvalidError):
            client.call_tool("get_sheet_info", {})


def test_client_http_401_maps_token_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="unauthorized")

    with _mk_client(handler) as client:
        with pytest.raises(TokenInvalidError):
            client.call_tool("get_sheet_info", {})


def test_client_list_tools_enumerates_names():
    """tools/list 诊断：initialize 后枚举服务端注册的工具名。"""
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content or b"{}") if request.content else {}
        method = payload.get("method")
        if method == "initialize":
            return httpx.Response(200, json=_jsonrpc_result({"serverInfo": {}}),
                                  headers={"Mcp-Session-Id": "s"})
        if method == "notifications/initialized":
            return httpx.Response(202)
        if method == "tools/list":
            return httpx.Response(200, json=_jsonrpc_result({"tools": [
                {"name": "smartsheet.list_tables", "description": "列出工作表"},
                {"name": "smartsheet.add_records"},
                {"bad": "no name → 跳过"},
            ]}))
        raise AssertionError(f"unexpected method {method}")

    with _mk_client(handler) as client:
        assert client.list_tools() == ["smartsheet.list_tables", "smartsheet.add_records"]


def test_client_list_tools_follows_cursor():
    """tools/list 分页：nextCursor 存在时续拉，直到无游标。"""
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content or b"{}") if request.content else {}
        method = payload.get("method")
        if method == "initialize":
            return httpx.Response(200, json=_jsonrpc_result({}),
                                  headers={"Mcp-Session-Id": "s"})
        if method == "notifications/initialized":
            return httpx.Response(202)
        if method == "tools/list":
            cursor = (payload.get("params") or {}).get("cursor")
            if not cursor:
                return httpx.Response(200, json=_jsonrpc_result({
                    "tools": [{"name": "a"}], "nextCursor": "c2"}))
            return httpx.Response(200, json=_jsonrpc_result({"tools": [{"name": "b"}]}))
        raise AssertionError(f"unexpected method {method}")

    with _mk_client(handler) as client:
        assert client.list_tools() == ["a", "b"]


def test_client_list_tools_sanitizes_and_caps():
    """I5：list_tools 清单会原样拼进错误文案给用户看——服务端名字不可信,
    需要去控制字符、单条截断、总数封顶。"""
    tools = [{"name": f"tool{i}"} for i in range(298)]
    tools.append({"name": "evil\nFAKE"})
    tools.append({"name": "x" * 500})

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content or b"{}") if request.content else {}
        method = payload.get("method")
        if method == "initialize":
            return httpx.Response(200, json=_jsonrpc_result({}),
                                  headers={"Mcp-Session-Id": "s"})
        if method == "notifications/initialized":
            return httpx.Response(202)
        if method == "tools/list":
            return httpx.Response(200, json=_jsonrpc_result({"tools": tools}))
        raise AssertionError(f"unexpected method {method}")

    with _mk_client(handler) as client:
        names = client.list_tools()
    assert len(names) <= 200
    assert all("\n" not in n for n in names)
    assert all(len(n) <= 80 for n in names)


def test_client_redacts_token_from_http_error_text():
    """S3：网关拒绝消息常回显 token——绝不能原样落进 reason（会展示给用户/写进日志）。"""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="denied for token tok-123 by gateway")

    with _mk_client(handler) as client:
        with pytest.raises(TencentDocsError) as ei:
            client.call_tool("get_sheet_info", {})
    assert "tok-123" not in ei.value.reason
    assert "***" in ei.value.reason


def test_client_redacts_token_from_tool_error_text():
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content or b"{}") if request.content else {}
        if payload.get("method") != "tools/call":
            return httpx.Response(202)
        return httpx.Response(200, json=_jsonrpc_result({
            "isError": True,
            "content": [{"type": "text", "text": "internal error for tok-123, retry"}],
        }))

    with _mk_client(handler) as client:
        with pytest.raises(TencentDocsError) as ei:
            client.call_tool("get_sheet_info", {})
    assert "tok-123" not in ei.value.reason
    assert "***" in ei.value.reason


# ── Sheet helpers（假 client）──────────────────────────────────────────

class FakeSheetClient:
    """内存表格（可多子表）：rows_of(sheet_id)[r][c] = str。记录 CSV/样式/插图调用。"""

    # 默认不含 insert_image（旧服务形态）；插图用例把它加进 tools。
    DEFAULT_TOOLS = ["get_sheet_info", "get_cell_data", "set_range_value_by_csv"]

    def __init__(self, rows: list[list[str]] | None = None, *, sheets: list[dict] | None = None):
        self.sheets = sheets or [
            {"sheet_id": "BB08J2", "sheet_name": "工作表1", "sheet_type": "worksheet",
             "row_count": 200, "col_count": 20},
        ]
        first_id = self.sheets[0]["sheet_id"]
        self.rows_by_sheet: dict[str, list[list[str]]] = {first_id: rows if rows is not None else []}
        self.csv_writes: list[dict] = []
        self.style_calls: list[dict] = []
        self.image_calls: list[dict] = []
        self.tools = list(self.DEFAULT_TOOLS)
        self.fail_insert = False

    @property
    def rows(self) -> list[list[str]]:
        """第一张子表的行（单表用例的便捷别名）。"""
        return self.rows_by_sheet[self.sheets[0]["sheet_id"]]

    def rows_of(self, sheet_id: str) -> list[list[str]]:
        return self.rows_by_sheet.setdefault(sheet_id, [])

    def list_tools(self) -> list[str]:
        return list(self.tools)

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass

    def call_tool(self, name, arguments):
        if name == "get_sheet_info":
            return {"sheets": self.sheets}
        if name == "set_cell_style":
            self.style_calls.append(arguments)
            return {}
        if name == "insert_image":
            if self.fail_insert:
                raise TencentDocsError("腾讯文档服务报错：image too large")
            self.image_calls.append(arguments)
            return {}
        rows = self.rows_of(arguments["sheet_id"])
        if name == "get_cell_data":
            cells = []
            for r in range(arguments["start_row"], arguments["end_row"] + 1):
                if r >= len(rows):
                    break
                for c in range(arguments["start_col"], arguments["end_col"] + 1):
                    if c < len(rows[r]) and rows[r][c]:
                        cells.append({"row": r, "col": c,
                                      "value_type": "STRING",
                                      "string_value": rows[r][c]})
            return {"cells": cells}
        if name == "set_range_value_by_csv":
            self.csv_writes.append(arguments)
            # 回放进内存表格，方便断言后续读
            import csv as _csv
            import io
            parsed = list(_csv.reader(io.StringIO(arguments["csv_data"])))
            r0, c0 = arguments["start_row"], arguments["start_col"]
            for dr, row in enumerate(parsed):
                while len(rows) <= r0 + dr:
                    rows.append([])
                target = rows[r0 + dr]
                for dc, val in enumerate(row):
                    while len(target) <= c0 + dc:
                        target.append("")
                    if val:
                        target[c0 + dc] = val
            return {}
        raise AssertionError(f"unexpected tool {name}")


def test_resolve_sheet_prefers_tab():
    fake = FakeSheetClient([], sheets=[
        {"sheet_id": "AAA", "sheet_name": "one", "sheet_type": "worksheet", "row_count": 10, "col_count": 5},
        {"sheet_id": "BBB", "sheet_name": "two", "sheet_type": "worksheet", "row_count": 10, "col_count": 5},
    ])
    t = resolve_sheet(fake, "https://docs.qq.com/sheet/D123?tab=BBB")
    assert t.sheet_id == "BBB"
    t2 = resolve_sheet(fake, "https://docs.qq.com/sheet/D123")
    assert t2.sheet_id == "AAA"


def test_read_row_and_last_used_row():
    fake = FakeSheetClient([
        _USER_HEADER,
        ["1", "链接A", "评论"],
        [],
        ["", "链接B"],
    ])
    t = resolve_sheet(fake, "https://docs.qq.com/sheet/D123?tab=BB08J2")
    assert read_row_texts(fake, t, 0)[:3] == ["序号", "链接", "内容一"]
    assert find_last_used_row(fake, t, probe_col=1) == 3   # 链接列最后非空在 row 3
    # 表头行也算「已用」（docstring 约定）→ 有表头的列最少返回 0
    assert find_last_used_row(fake, t, probe_col=6) == 0
    assert find_last_used_row(fake, t, probe_col=15) == -1  # 表头外的全空列


def test_append_rows_csv_quotes_properly():
    fake = FakeSheetClient([_USER_HEADER])
    t = resolve_sheet(fake, "https://docs.qq.com/sheet/D123?tab=BB08J2")
    append_rows_csv(fake, t, 1, [["1", '标题,带逗号 "引号" https://x', "评论\n换行"]])
    csv_data = fake.csv_writes[0]["csv_data"]
    assert '"标题,带逗号 ""引号"" https://x"' in csv_data
    # 回放后单元格内容还原
    assert fake.rows[1][1] == '标题,带逗号 "引号" https://x'
    assert fake.rows[1][2] == "评论\n换行"


# ── v15 迁移 ────────────────────────────────────────────────────────────

def test_v15_sync_batches_table(monitor_db: Path):
    conn = ms.get_conn()
    cols = {r[1] for r in conn.execute("PRAGMA table_info(sync_batches)").fetchall()}
    assert {"doc_id", "sheet_id", "row_start", "row_end", "video_ids_json"} <= cols
    ms.apply_v15_migration(conn)  # 幂等


# ── 同步服务全流程 ──────────────────────────────────────────────────────

def _seed_video_with_comments(video_id: int, url: str, tiers: list[str], *, images_on: set[int] = frozenset()):
    conn = monitor_storage.get_conn()
    conn.execute(
        "INSERT INTO videos(id, platform, platform_video_id, url, title) VALUES(?,?,?,?,?)",
        (video_id, "douyin", f"dy{video_id}", url, f"标题{video_id}"),
    )
    for i, text in enumerate(tiers, start=1):
        cid = ms.upsert_ai_comment(video_id, i, text)
        if i in images_on:
            ms.update_comment(cid, image_ids=["img-x"])
        ms.approve_comment(cid)


@pytest.fixture
def tdocs_env(monitor_db: Path, settings_path: Path, monkeypatch):
    """启用同步 + 假 token + 假表格。返回 FakeSheetClient 以便断言。"""
    config_service.patch({"tencent_docs": {
        "enabled": True,
        "doc_url": "https://docs.qq.com/sheet/D123?tab=BB08J2",
    }})
    monkeypatch.setattr(tds, "read_api_key", lambda p, c=None: "tok-abc")
    fake = FakeSheetClient([list(_USER_HEADER)])
    monkeypatch.setattr(tds, "_client_factory", lambda token: fake)
    yield fake
    monkeypatch.setattr(tds, "_client_factory", None)


def test_sync_approved_writes_rows_and_marks_synced(tdocs_env: FakeSheetClient):
    _seed_video_with_comments(1, "https://www.douyin.com/video/111",
                              ["一楼", "二楼"], images_on={1})
    _seed_video_with_comments(2, "https://www.douyin.com/video/222", ["只有一楼"])

    result = tds.sync_approved()

    assert result["synced_videos"] == 2
    assert result["synced_comments"] == 3
    assert result["batch_id"] is not None
    assert len(result["batches"]) == 1
    block = result["batches"][0]
    assert block["platform"] == "douyin"
    # 表内只有表头（无数据行）→ 不留分隔行，直接从 row 1 开始
    assert block["row_start"] == 1
    assert block["row_end"] == 2
    assert tdocs_env.style_calls == []

    # 行内容：列位置按表头映射
    row1 = tdocs_env.rows[1]
    assert row1[0] == "1"                                  # 序号从 1 重排
    assert row1[1] == "标题1 https://www.douyin.com/video/111"
    assert row1[2] == "一楼"
    assert row1[3] == "有图，另发"                          # tier1 挂图 → 贴图一标记
    assert row1[4] == "二楼"
    assert "月" in row1[8]                                  # 日期（2026年9月1日 格式）
    row2 = tdocs_env.rows[2]
    assert row2[0] == "2"
    assert row2[2] == "只有一楼"

    # 本地状态：approved → synced
    for vid in (1, 2):
        assert all(c["review_status"] == "synced" for c in ms.list_comments(vid))

    # 对账表
    conn = ms.get_conn()
    batch = conn.execute("SELECT * FROM sync_batches").fetchone()
    assert batch["doc_id"] == "D123"
    assert batch["row_start"] == 1 and batch["row_end"] == 2


_CONVENTION_HEADER = ["视频链接", "评论A", "评论A的图片", "评论B", "评论C", "评论D"]


def test_sync_convention_header_writes_four_tiers(monitor_db, settings_path, monkeypatch):
    """用户表头惯例：视频链接 + 评论A..D（无 序号/日期）→ 四层全写入，不再截到 3 层。"""
    config_service.patch({"tencent_docs": {
        "enabled": True,
        "doc_url": "https://docs.qq.com/sheet/D123?tab=BB08J2",
    }})
    monkeypatch.setattr(tds, "read_api_key", lambda p, c=None: "tok")
    fake = FakeSheetClient([list(_CONVENTION_HEADER)])
    monkeypatch.setattr(tds, "_client_factory", lambda token: fake)
    _seed_video_with_comments(1, "https://www.douyin.com/video/111",
                              ["一楼", "二楼", "三楼", "四楼"], images_on={1})

    result = tds.sync_approved()
    assert result["synced_videos"] == 1
    assert result["synced_comments"] == 4
    assert result["skipped_extra_tiers"] == 0
    row = fake.rows[1]
    assert row[0] == "标题1 https://www.douyin.com/video/111"   # 视频链接（别名）
    assert row[1] == "一楼" and row[2] == "有图，另发"
    assert row[3] == "二楼" and row[4] == "三楼" and row[5] == "四楼"
    monkeypatch.setattr(tds, "_client_factory", None)


def test_sync_skips_tiers_deeper_than_header(monitor_db, settings_path, monkeypatch):
    config_service.patch({"tencent_docs": {
        "enabled": True,
        "doc_url": "https://docs.qq.com/sheet/D123?tab=BB08J2",
    }})
    monkeypatch.setattr(tds, "read_api_key", lambda p, c=None: "tok")
    fake = FakeSheetClient([["链接", "评论A", "评论B"]])
    monkeypatch.setattr(tds, "_client_factory", lambda token: fake)
    _seed_video_with_comments(1, "https://www.douyin.com/video/111", ["一楼", "二楼", "三楼"])

    result = tds.sync_approved()
    assert result["skipped_extra_tiers"] == 1          # 第 3 层没列，留在 app 内
    assert result["synced_comments"] == 2
    monkeypatch.setattr(tds, "_client_factory", None)


def test_sync_gap_header_skips_missing_middle_tier(monitor_db, settings_path, monkeypatch):
    """T1：表头断层（评论A/评论C 之间没有评论B）不能再用「表头最大层号」判断
    某一层能不能写——按该层的列是否真实存在决定。断层的那层留在 app 内
    （保持 approved，不假标 synced），已有列的层照常写、照常标 synced。"""
    config_service.patch({"tencent_docs": {
        "enabled": True,
        "doc_url": "https://docs.qq.com/sheet/D123?tab=BB08J2",
    }})
    monkeypatch.setattr(tds, "read_api_key", lambda p, c=None: "tok")
    fake = FakeSheetClient([["链接", "评论A", "评论C"]])
    monkeypatch.setattr(tds, "_client_factory", lambda token: fake)
    _seed_video_with_comments(1, "https://www.douyin.com/video/111", ["一楼", "二楼", "三楼"])

    result = tds.sync_approved()
    assert result["synced_comments"] == 2
    assert result["skipped_extra_tiers"] == 1
    row = fake.rows[1]
    assert row[1] == "一楼"     # tier1 → 评论A 列
    assert row[2] == "三楼"     # tier3 → 评论C 列
    assert "二楼" not in row    # tier2 没有列，没有被误写进任何位置

    comments_by_tier = {c["tier"]: c for c in ms.list_comments(1)}
    assert comments_by_tier[1]["review_status"] == "synced"
    assert comments_by_tier[2]["review_status"] == "approved"   # 断层层：留在 app 内
    assert comments_by_tier[3]["review_status"] == "synced"
    monkeypatch.setattr(tds, "_client_factory", None)


def test_sync_literal_comment_x_header_is_harmless(monitor_db, settings_path, monkeypatch):
    """R6：字母上限收窄到 A-E 后，表头里字面出现的「评论X」（占位符文案，
    不是惯例里具体的字母）根本不会被解析成任何 tier 列——tier2 仍然没有
    列可写，照常留在 app 内（不被误标 synced），tiers_detected 不受影响。"""
    config_service.patch({"tencent_docs": {
        "enabled": True,
        "doc_url": "https://docs.qq.com/sheet/D123?tab=BB08J2",
    }})
    monkeypatch.setattr(tds, "read_api_key", lambda p, c=None: "tok")
    fake = FakeSheetClient([["链接", "评论A", "评论X"]])
    monkeypatch.setattr(tds, "_client_factory", lambda token: fake)
    _seed_video_with_comments(1, "https://www.douyin.com/video/111", ["一楼", "二楼"])

    result = tds.sync_approved()
    assert result["skipped_extra_tiers"] == 1
    row = fake.rows[1]
    assert row[1] == "一楼"

    tier2 = next(c for c in ms.list_comments(1) if c["tier"] == 2)
    assert tier2["review_status"] == "approved"    # 没有列可写，没有被假标 synced
    monkeypatch.setattr(tds, "_client_factory", None)


def test_sync_drops_image_marker_when_tier_has_no_image_column(monitor_db, settings_path, monkeypatch):
    """R4：兼职是原样复制评论正文去公开发布的——「有图，另发」这种内部指示语
    绝不能混进正文（会被公开贴出去）。某层有图但表头没有对应的「评论X的
    图片」列时，正文保持干净，只计数 images_dropped；有图片列的层照常走列。"""
    config_service.patch({"tencent_docs": {
        "enabled": True,
        "doc_url": "https://docs.qq.com/sheet/D123?tab=BB08J2",
    }})
    monkeypatch.setattr(tds, "read_api_key", lambda p, c=None: "tok")
    fake = FakeSheetClient([["链接", "评论A", "评论A的图片", "评论B"]])
    monkeypatch.setattr(tds, "_client_factory", lambda token: fake)
    _seed_video_with_comments(1, "https://www.douyin.com/video/111",
                              ["一楼", "二楼"], images_on={1, 2})

    result = tds.sync_approved()
    assert result["images_dropped"] == 1
    row = fake.rows[1]
    assert row[2] == "有图，另发"      # tier1 有图片列 → 走列
    assert row[3] == "二楼"            # tier2 没有图片列 → 干净正文，不混入指示语
    monkeypatch.setattr(tds, "_client_factory", None)


def test_test_connection_reports_tiers_detected(monitor_db, settings_path, monkeypatch):
    config_service.patch({"tencent_docs": {
        "enabled": True,
        "doc_url": "https://docs.qq.com/sheet/D123?tab=BB08J2",
    }})
    monkeypatch.setattr(tds, "read_api_key", lambda p, c=None: "tok")
    fake = FakeSheetClient([list(_CONVENTION_HEADER)])
    monkeypatch.setattr(tds, "_client_factory", lambda token: fake)
    out = tds.test_connection()
    assert out["ok"] is True and out["missing"] == []
    assert all(p["tiers_detected"] == 4 for p in out["sheets"])
    monkeypatch.setattr(tds, "_client_factory", None)


def test_test_connection_missing_required_uses_friendly_labels(monitor_db, settings_path, monkeypatch):
    config_service.patch({"tencent_docs": {
        "enabled": True,
        "doc_url": "https://docs.qq.com/sheet/D123?tab=BB08J2",
    }})
    monkeypatch.setattr(tds, "read_api_key", lambda p, c=None: "tok")
    fake = FakeSheetClient([["发布类型", "平台", "文章标题"]])
    monkeypatch.setattr(tds, "_client_factory", lambda token: fake)
    out = tds.test_connection()
    assert out["ok"] is False
    assert any("视频链接" in m for m in out["missing"])
    assert any("评论A" in m for m in out["missing"])
    monkeypatch.setattr(tds, "_client_factory", None)


def test_test_connection_reports_optional_missing_columns(monitor_db, settings_path, monkeypatch):
    """T2：可选列（非 url/tier1）配置了但表头里没有 → optional_missing 报出来，
    但不算错（ok 仍为 True，missing 仍为空）。"""
    config_service.patch({"tencent_docs": {
        "enabled": True,
        "doc_url": "https://docs.qq.com/sheet/D123?tab=BB08J2",
    }})
    monkeypatch.setattr(tds, "read_api_key", lambda p, c=None: "tok")
    legacy_header_no_tier2 = ["序号", "链接", "内容一", "贴图一", "盖楼内容三", "贴图三", "日期"]
    fake = FakeSheetClient([legacy_header_no_tier2])
    monkeypatch.setattr(tds, "_client_factory", lambda token: fake)
    out = tds.test_connection()
    assert out["ok"] is True
    assert out["missing"] == []
    assert "盖楼内容二" in out["optional_missing"]
    assert "贴图二" in out["optional_missing"]
    monkeypatch.setattr(tds, "_client_factory", None)


def test_test_connection_reports_tier_gaps(monitor_db, settings_path, monkeypatch):
    """T2：表头断层（评论A/评论C 之间缺评论B）要能报出 tier_gaps，供前端提醒。"""
    config_service.patch({"tencent_docs": {
        "enabled": True,
        "doc_url": "https://docs.qq.com/sheet/D123?tab=BB08J2",
    }})
    monkeypatch.setattr(tds, "read_api_key", lambda p, c=None: "tok")
    fake = FakeSheetClient([["链接", "评论A", "评论C"]])
    monkeypatch.setattr(tds, "_client_factory", lambda token: fake)
    out = tds.test_connection()
    assert all(p["tier_gaps"] == [2] for p in out["sheets"])
    monkeypatch.setattr(tds, "_client_factory", None)


def test_test_connection_reports_image_cols_missing(monitor_db, settings_path, monkeypatch):
    """R4：贴图列缺失的层号要在「测试连接」里报出来，让用户提前配好列，
    而不是等到同步时才发现图片信息被静默丢弃。"""
    config_service.patch({"tencent_docs": {
        "enabled": True,
        "doc_url": "https://docs.qq.com/sheet/D123?tab=BB08J2",
    }})
    monkeypatch.setattr(tds, "read_api_key", lambda p, c=None: "tok")
    fake = FakeSheetClient([["链接", "评论A", "评论A的图片", "评论B", "评论C"]])
    monkeypatch.setattr(tds, "_client_factory", lambda token: fake)
    out = tds.test_connection()
    assert all(p["image_cols_missing"] == [2, 3] for p in out["sheets"])
    monkeypatch.setattr(tds, "_client_factory", None)


def test_test_connection_full_header_no_optional_missing_no_gaps(tdocs_env: FakeSheetClient):
    """T2 反面：表头齐全（_USER_HEADER）时 optional_missing / tier_gaps 都该是空。"""
    out = tds.test_connection()
    assert all(p["optional_missing"] == [] for p in out["sheets"])
    assert all(p["tier_gaps"] == [] for p in out["sheets"])
    assert out["optional_missing"] == []


def test_sync_approved_dedups_by_url_column(tdocs_env: FakeSheetClient):
    """表格里已有该视频链接 → 跳过写入、本地补标 synced（防双写）。"""
    tdocs_env.rows.append(["1", "旧行 https://www.douyin.com/video/111", "旧评论"])
    _seed_video_with_comments(1, "https://www.douyin.com/video/111", ["一楼"])

    result = tds.sync_approved()
    assert result["synced_videos"] == 0
    assert result["skipped_in_doc"] == 1
    assert result["synced_comments"] == 1   # 本地仍标 synced
    assert all(c["review_status"] == "synced" for c in ms.list_comments(1))
    assert len(tdocs_env.rows) == 2         # 没有新行


def test_sync_dedup_skip_counts_skipped_extra_tiers(monitor_db, settings_path, monkeypatch):
    """R5：去重分支（该视频链接已在文档里）也要统计超出表头层数的评论——
    这些层留在 app 内（保持 approved），不能被 skipped_extra_tiers 漏计,
    否则「这批还剩几层没进表格」的统计在去重路径上会悄悄失真。"""
    config_service.patch({"tencent_docs": {
        "enabled": True,
        "doc_url": "https://docs.qq.com/sheet/D123?tab=BB08J2",
    }})
    monkeypatch.setattr(tds, "read_api_key", lambda p, c=None: "tok")
    fake = FakeSheetClient([
        ["链接", "评论A", "评论B", "评论C"],
        ["旧行 https://www.douyin.com/video/111", "旧评论"],
    ])
    monkeypatch.setattr(tds, "_client_factory", lambda token: fake)
    _seed_video_with_comments(1, "https://www.douyin.com/video/111",
                              ["一楼", "二楼", "三楼", "四楼", "五楼"])

    result = tds.sync_approved()
    assert result["skipped_in_doc"] == 1
    assert result["skipped_extra_tiers"] == 2
    assert result["synced_comments"] == 3

    comments_by_tier = {c["tier"]: c for c in ms.list_comments(1)}
    assert comments_by_tier[1]["review_status"] == "synced"
    assert comments_by_tier[3]["review_status"] == "synced"
    assert comments_by_tier[4]["review_status"] == "approved"
    assert comments_by_tier[5]["review_status"] == "approved"
    monkeypatch.setattr(tds, "_client_factory", None)


def test_sync_approved_leaves_separator_row_after_existing_rows(tdocs_env: FakeSheetClient):
    """表里已有数据行 → 新批次前留一行空分隔行并涂橙（对齐用户表内惯例）。"""
    tdocs_env.rows.append(["1", "既有行 https://old/1", "x"])
    tdocs_env.rows.append(["2", "既有行 https://old/2", "y"])
    _seed_video_with_comments(1, "https://www.douyin.com/video/111", ["一楼"])

    result = tds.sync_approved()
    block = result["batches"][0]
    # last_used=2 → 分隔行占 row 3，数据从 row 4 起
    assert block["row_start"] == 4
    assert tdocs_env.rows[4][2] == "一楼"
    assert len(tdocs_env.style_calls) == 1
    style = tdocs_env.style_calls[0]
    assert style["start_row"] == 3 and style["end_row"] == 3
    assert style["format"]["bg_color"] == "FFFFC000"       # 橙色分隔行
    # 分隔行本身没有文本内容
    assert len(tdocs_env.rows) <= 5 or not any(tdocs_env.rows[3])


def test_sync_approved_reuses_trailing_separator_row(tdocs_env: FakeSheetClient):
    """上一批留下的橙色空分隔行（无文本）—— 新分隔行恰好落在同一行复用，
    不会出现两行连续空行。"""
    tdocs_env.rows.append(["1", "既有行 https://old/1", "x"])
    tdocs_env.rows.append([])   # 用户表尾的橙色分隔行（只有底色，无文本）
    _seed_video_with_comments(1, "https://www.douyin.com/video/111", ["一楼"])

    result = tds.sync_approved()
    block = result["batches"][0]
    # 「链接」列最后非空在 row 1 → 分隔行 = row 2（正是既有空行），数据 row 3
    assert block["row_start"] == 3
    assert tdocs_env.style_calls[0]["start_row"] == 2


def test_sync_approved_noop_when_nothing_approved(tdocs_env: FakeSheetClient):
    result = tds.sync_approved()
    assert result["synced_videos"] == 0
    assert result["batch_id"] is None
    assert result["batches"] == []
    assert tdocs_env.csv_writes == []


def test_sync_routes_platforms_to_named_sheets(monitor_db, settings_path, monkeypatch):
    """多子表（抖音/B站/快手 tab）→ 按平台名路由，各写各的子表。"""
    config_service.patch({"tencent_docs": {
        "enabled": True,
        "doc_url": "https://docs.qq.com/sheet/D123?tab=DYTAB",
    }})
    monkeypatch.setattr(tds, "read_api_key", lambda p, c=None: "tok")
    fake = FakeSheetClient(sheets=[
        {"sheet_id": "DYTAB", "sheet_name": "抖音", "sheet_type": "worksheet", "row_count": 200, "col_count": 20},
        {"sheet_id": "BLTAB", "sheet_name": "B站", "sheet_type": "worksheet", "row_count": 200, "col_count": 20},
        {"sheet_id": "KSTAB", "sheet_name": "快手", "sheet_type": "worksheet", "row_count": 200, "col_count": 20},
    ])
    for sid in ("DYTAB", "BLTAB", "KSTAB"):
        fake.rows_of(sid).append(list(_USER_HEADER))
    monkeypatch.setattr(tds, "_client_factory", lambda token: fake)

    conn = monitor_storage.get_conn()
    conn.execute(
        "INSERT INTO videos(id, platform, platform_video_id, url, title) VALUES(1,'douyin','d1','https://www.douyin.com/video/1','抖音视频')")
    conn.execute(
        "INSERT INTO videos(id, platform, platform_video_id, url, title) VALUES(2,'bilibili','b1','https://www.bilibili.com/video/BV1','B站视频')")
    for vid in (1, 2):
        cid = ms.upsert_ai_comment(vid, 1, f"评论{vid}")
        ms.approve_comment(cid)

    result = tds.sync_approved()
    assert result["synced_videos"] == 2
    by_platform = {b["platform"]: b for b in result["batches"]}
    assert by_platform["douyin"]["sheet_name"] == "抖音"
    assert by_platform["bilibili"]["sheet_name"] == "B站"
    assert fake.rows_of("DYTAB")[1][2] == "评论1"
    assert fake.rows_of("BLTAB")[1][2] == "评论2"
    assert fake.rows_of("KSTAB") == [list(_USER_HEADER)]   # 快手无内容不动
    # 序号在各自子表内都从 1 起
    assert fake.rows_of("DYTAB")[1][0] == "1"
    assert fake.rows_of("BLTAB")[1][0] == "1"
    monkeypatch.setattr(tds, "_client_factory", None)


def test_sync_approved_requires_enabled(monitor_db: Path, settings_path: Path, monkeypatch):
    monkeypatch.setattr(tds, "read_api_key", lambda p, c=None: "tok")
    with pytest.raises(tds.TencentDocsDisabledError):
        tds.sync_approved()


def test_sync_approved_missing_required_column(monitor_db, settings_path, monkeypatch):
    config_service.patch({"tencent_docs": {
        "enabled": True,
        "doc_url": "https://docs.qq.com/sheet/D123?tab=BB08J2",
    }})
    monkeypatch.setattr(tds, "read_api_key", lambda p, c=None: "tok")
    fake = FakeSheetClient([["随便", "别的表头"]])
    monkeypatch.setattr(tds, "_client_factory", lambda token: fake)
    _seed_video_with_comments(1, "https://www.douyin.com/video/111", ["一楼"])
    with pytest.raises(TencentDocsError, match="找不到必需列"):
        tds.sync_approved()
    monkeypatch.setattr(tds, "_client_factory", None)


def test_test_connection_reports_mapping(tdocs_env: FakeSheetClient):
    out = tds.test_connection()
    assert out["ok"] is True
    assert out["sheet_name"] == "工作表1"
    assert out["missing"] == []
    assert "链接" in out["header"]
    # 诊断字段：无论成败都带上服务端真实工具清单（tools/list）
    assert out["available_tools"] == [
        "get_sheet_info", "get_cell_data", "set_range_value_by_csv",
    ]
    # 平台路由报告：单表用例三个平台都回落到兜底子表（非按名命中）
    assert [p["platform"] for p in out["sheets"]] == ["douyin", "bilibili", "kuaishou", "xiaohongshu"]
    assert all(p["sheet_name"] == "工作表1" for p in out["sheets"])
    assert all(p["matched_by_name"] is False for p in out["sheets"])


class _ToolNotFoundClient:
    """模拟真服务：sheet.* 一律 tool not found，但 tools/list 能列出真实工具。"""

    tools = ["smartsheet.list_tables", "smartsheet.list_records", "smartsheet.add_records"]

    def list_tools(self):
        return list(self.tools)

    def call_tool(self, name, arguments):
        raise TencentDocsError(
            f"腾讯文档服务报错：tool not found: {name}, trace_id:deadbeef")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass

    def close(self):
        pass


def test_test_connection_surfaces_available_tools_on_tool_not_found(
    monitor_db, settings_path, monkeypatch,
):
    """sheet.get_sheet_info 不存在时，错误里挂上 tools/list 真实清单（诊断）。"""
    config_service.patch({"tencent_docs": {
        "enabled": True,
        "doc_url": "https://docs.qq.com/sheet/D123?tab=BB08J2",
    }})
    monkeypatch.setattr(tds, "read_api_key", lambda p, c=None: "tok")
    monkeypatch.setattr(tds, "_client_factory", lambda token: _ToolNotFoundClient())
    with pytest.raises(TencentDocsError) as ei:
        tds.test_connection()
    reason = ei.value.reason
    assert "tool not found" in reason
    assert "smartsheet.list_tables" in reason           # 诊断清单已挂上
    assert "smartsheet.add_records" in reason
    monkeypatch.setattr(tds, "_client_factory", None)


def test_test_connection_reports_named_sheets(monitor_db, settings_path, monkeypatch):
    config_service.patch({"tencent_docs": {
        "enabled": True,
        "doc_url": "https://docs.qq.com/sheet/D123",
    }})
    monkeypatch.setattr(tds, "read_api_key", lambda p, c=None: "tok")
    fake = FakeSheetClient(sheets=[
        {"sheet_id": "DYTAB", "sheet_name": "抖音", "sheet_type": "worksheet", "row_count": 200, "col_count": 20},
        {"sheet_id": "BLTAB", "sheet_name": "B 站", "sheet_type": "worksheet", "row_count": 200, "col_count": 20},
    ])
    fake.rows_of("DYTAB").append(list(_USER_HEADER))
    fake.rows_of("BLTAB").append(list(_USER_HEADER))
    monkeypatch.setattr(tds, "_client_factory", lambda token: fake)

    out = tds.test_connection()
    by_platform = {p["platform"]: p for p in out["sheets"]}
    assert by_platform["douyin"]["matched_by_name"] is True
    # 「B 站」带空格也按去空白匹配命中「B站」
    assert by_platform["bilibili"]["matched_by_name"] is True
    assert by_platform["bilibili"]["sheet_name"] == "B 站"
    # 快手没有同名子表 → 回落第一张
    assert by_platform["kuaishou"]["matched_by_name"] is False
    assert by_platform["kuaishou"]["sheet_name"] == "抖音"
    monkeypatch.setattr(tds, "_client_factory", None)


# ── 路由 ────────────────────────────────────────────────────────────────

def test_status_route(client, monitor_db, monkeypatch):
    monkeypatch.setattr(tds, "read_api_key", lambda p, c=None: "")
    r = client.get("/api/mining/tencent_docs/status")
    assert r.status_code == 200
    body = r.json()
    assert body["enabled"] is False
    assert body["has_token"] is False


def test_sync_route_disabled_returns_code(client, monitor_db, monkeypatch):
    monkeypatch.setattr(tds, "read_api_key", lambda p, c=None: "tok")
    r = client.post("/api/mining/sync_to_docs", json={})
    assert r.status_code == 400
    assert r.json()["code"] == "tencent_docs_disabled"


# ── 评论楼层图片直接插进表格（insert_image）────────────────────────────────

_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


@pytest.fixture
def fake_images(tmp_path: Path, monkeypatch):
    """img-x / img-y 落成真实文件；其余 image_id 视为缺失。"""
    files = {}
    for iid in ("img-x", "img-y"):
        p = tmp_path / f"{iid}.png"
        p.write_bytes(_PNG)
        files[iid] = p
    monkeypatch.setattr(tds.mining_images_service, "get_image_path", lambda iid: files.get(iid))
    return files


def test_sync_inserts_images_into_image_column(tdocs_env: FakeSheetClient, fake_images):
    import base64
    tdocs_env.tools.append("insert_image")
    _seed_video_with_comments(1, "https://www.douyin.com/video/111", ["一楼", "二楼"], images_on={1})

    result = tds.sync_approved()

    assert result["images_inserted"] == 1
    assert result["images_failed"] == 0 and result["images_unsupported"] == 0
    assert tdocs_env.image_calls == [{
        "file_id": "D123", "sheet_id": "BB08J2",
        "row_index": 1, "col_index": 3,                      # 第一条数据行 × 「贴图一」列
        "content": base64.b64encode(_PNG).decode("ascii"),
    }]
    assert tdocs_env.rows[1][3] == ""                         # 有图本体就不写文字标记
    assert tdocs_env.rows[1][2] == "一楼"
    assert all(c["review_status"] == "synced" for c in ms.list_comments(1))


def test_sync_inserts_every_image_of_a_tier_into_same_cell(tdocs_env: FakeSheetClient, fake_images):
    tdocs_env.tools.append("insert_image")
    conn = monitor_storage.get_conn()
    conn.execute("INSERT INTO videos(id, platform, platform_video_id, url, title) VALUES(1,'douyin','d1','https://www.douyin.com/video/1','t')")
    cid = ms.upsert_ai_comment(1, 1, "一楼")
    ms.update_comment(cid, image_ids=["img-x", "img-y"])
    ms.approve_comment(cid)

    result = tds.sync_approved()
    assert result["images_inserted"] == 2
    assert [(c["row_index"], c["col_index"]) for c in tdocs_env.image_calls] == [(1, 3), (1, 3)]


def test_sync_falls_back_to_marker_when_tool_missing(tdocs_env: FakeSheetClient, fake_images):
    """服务端没有 insert_image → 旧行为：贴图列写「有图，另发」。"""
    _seed_video_with_comments(1, "https://www.douyin.com/video/111", ["一楼"], images_on={1})
    result = tds.sync_approved()
    assert result["images_unsupported"] == 1 and result["images_inserted"] == 0
    assert tdocs_env.image_calls == []
    assert tdocs_env.rows[1][3] == "有图，另发"


def test_sync_respects_sync_images_switch(tdocs_env: FakeSheetClient, fake_images):
    tdocs_env.tools.append("insert_image")
    config_service.patch({"tencent_docs": {"sync_images": False}})
    _seed_video_with_comments(1, "https://www.douyin.com/video/111", ["一楼"], images_on={1})
    result = tds.sync_approved()
    assert result["images_unsupported"] == 1 and tdocs_env.image_calls == []
    assert tdocs_env.rows[1][3] == "有图，另发"


def test_sync_insert_failure_counts_and_writes_marker(tdocs_env: FakeSheetClient, fake_images):
    """单张插入失败：计 images_failed，该格补写标记，评论仍标 synced（文本已写入表格）。"""
    tdocs_env.tools.append("insert_image")
    tdocs_env.fail_insert = True
    _seed_video_with_comments(1, "https://www.douyin.com/video/111", ["一楼"], images_on={1})
    result = tds.sync_approved()
    assert result["images_failed"] == 1 and result["images_inserted"] == 0
    assert tdocs_env.rows[1][3] == "有图，另发"
    assert all(c["review_status"] == "synced" for c in ms.list_comments(1))


def test_sync_missing_image_file_counts_failed(tdocs_env: FakeSheetClient, fake_images):
    tdocs_env.tools.append("insert_image")
    conn = monitor_storage.get_conn()
    conn.execute("INSERT INTO videos(id, platform, platform_video_id, url, title) VALUES(1,'douyin','d1','https://www.douyin.com/video/1','t')")
    cid = ms.upsert_ai_comment(1, 1, "一楼")
    ms.update_comment(cid, image_ids=["img-gone"])
    ms.approve_comment(cid)
    result = tds.sync_approved()
    assert result["images_failed"] == 1 and tdocs_env.image_calls == []
    assert tdocs_env.rows[1][3] == "有图，另发"


def test_sync_image_without_column_still_dropped(tdocs_env: FakeSheetClient, fake_images, monkeypatch):
    """表头没有该层贴图列 → 图无处可放：images_dropped，不插图、不写标记、正文干净。"""
    fake = FakeSheetClient([["链接", "评论A", "评论B"]])
    fake.tools.append("insert_image")
    monkeypatch.setattr(tds, "_client_factory", lambda token: fake)
    _seed_video_with_comments(1, "https://www.douyin.com/video/111", ["一楼", "二楼"], images_on={2})
    result = tds.sync_approved()
    assert result["images_dropped"] == 1 and result["images_inserted"] == 0
    assert fake.image_calls == [] and fake.rows[1][2] == "二楼"


def test_test_connection_reports_insert_image_support(tdocs_env: FakeSheetClient):
    out = tds.test_connection()
    assert out["insert_image_supported"] is False and out["sync_images"] is True
    tdocs_env.tools.append("insert_image")
    assert tds.test_connection()["insert_image_supported"] is True
    # 四平台都出现在路由报告里（小红书 tab 默认名「小红书」）
    assert [p["platform"] for p in out["sheets"]] == ["douyin", "bilibili", "kuaishou", "xiaohongshu"]
    assert out["sheets"][-1]["platform_label"] == "小红书"


def test_sync_routes_xiaohongshu_to_its_named_sheet(monitor_db, settings_path, monkeypatch):
    config_service.patch({"tencent_docs": {
        "enabled": True,
        "doc_url": "https://docs.qq.com/sheet/D123?tab=DYTAB",
    }})
    monkeypatch.setattr(tds, "read_api_key", lambda p, c=None: "tok")
    fake = FakeSheetClient(sheets=[
        {"sheet_id": "DYTAB", "sheet_name": "抖音", "sheet_type": "worksheet", "row_count": 200, "col_count": 20},
        {"sheet_id": "XHSTAB", "sheet_name": "小红书", "sheet_type": "worksheet", "row_count": 200, "col_count": 20},
    ])
    for sid in ("DYTAB", "XHSTAB"):
        fake.rows_of(sid).append(list(_USER_HEADER))
    monkeypatch.setattr(tds, "_client_factory", lambda token: fake)
    conn = monitor_storage.get_conn()
    conn.execute(
        "INSERT INTO videos(id, platform, platform_video_id, url, title) VALUES(1,'xiaohongshu','64f1c2a3000000001e03ab12','https://www.xiaohongshu.com/explore/64f1c2a3000000001e03ab12','笔记')")
    cid = ms.upsert_ai_comment(1, 1, "小红书评论")
    ms.approve_comment(cid)

    result = tds.sync_approved()
    assert result["synced_videos"] == 1
    assert result["batches"][0]["platform"] == "xiaohongshu"
    assert result["batches"][0]["sheet_name"] == "小红书"
    assert fake.rows_of("XHSTAB")[1][2] == "小红书评论"
    assert fake.rows_of("DYTAB") == [list(_USER_HEADER)]
    monkeypatch.setattr(tds, "_client_factory", None)


# ── 表头识别（放宽惯例）+ 手动列映射 ─────────────────────────────────────

from csm_core.sync.tencent_docs import (  # noqa: E402
    apply_column_overrides, classify_header, col_letter, describe_columns,
)


@pytest.mark.parametrize("header,role", [
    ("评论A", "tier1"), ("评论 b", "tier2"), ("评论1", "tier1"), ("评论三", "tier3"),
    ("一楼", "tier1"), ("2楼评论", "tier2"), ("第三层评论", "tier3"), ("楼层4", "tier4"),
    ("内容一", "tier1"), ("盖楼内容二", "tier2"), ("主评", "tier1"), ("评论A（必填）", "tier1"),
    ("评论A的图片", "img1"), ("评论2图片", "img2"), ("一楼图片", "img1"), ("贴图三", "img3"),
    ("图片1", "img1"), ("第2层图片", "img2"), ("配图五", "img5"), ("评论①", "tier1"),
    ("截图1", None), ("评论返图", None), ("执行状态", None), ("备注", None),
    ("评论X", None), ("评论6", None), ("评论Ⅰ", None), ("", None), (None, None),
    ("链接", "url"), ("视频链接", "url"), ("笔记链接", "url"), ("抖音链接", "url"), ("URL", "url"),
    ("序号", "seq"), ("编号", "seq"), ("日期", "date"), ("任务日期", "date"),
])
def test_classify_header_conventions(header, role):
    assert classify_header(header) == role


def test_column_map_auto_non_adjacent_columns_and_three_tiers():
    """评论列与图片列不相邻、只有 3 层、夹着日期和截图列 —— 按名字全部对上。"""
    header = ["序号", "链接", "评论1", "评论2", "评论3", "日期", "图片1", "图片2", "图片3", "截图1", "截图2"]
    cmap = build_column_map_auto(header, {})
    assert cmap.col("tier1") == 2 and cmap.col("tier3") == 4
    assert cmap.col("img1") == 6 and cmap.col("img3") == 8
    assert cmap.col("seq") == 0 and cmap.col("url") == 1 and cmap.col("date") == 5
    assert max_tier(cmap) == 3 and cmap.tier_gaps == [] and cmap.missing == []
    assert all(cmap.source[k] == "auto" for k in cmap.by_key)
    assert not {9, 10} & set(cmap.by_key.values())          # 截图列不是任何角色


def test_column_map_auto_mixed_conventions_and_first_wins():
    header = ["笔记链接", "一楼", "一楼图片", "二楼", "二楼图片", "三楼", "评论1"]
    cmap = build_column_map_auto(header, {})
    assert cmap.col("url") == 0
    assert cmap.col("tier1") == 1 and cmap.col("tier2") == 3 and cmap.col("tier3") == 5
    assert cmap.col("img1") == 2 and cmap.col("img2") == 4
    # 「评论1」也是 tier1，但靠前的「一楼」已占位 → 取靠前
    assert 6 not in cmap.by_key.values()


def test_apply_column_overrides_moves_roles_and_ignores():
    header = ["链接", "评论A", "备注", "评论B", "评论A的图片"]
    cmap = build_column_map_auto(header, {})
    assert cmap.col("tier2") == 3 and cmap.col("img1") == 4
    apply_column_overrides(cmap, header, {}, {"tier2": 2, "img1": None, "img2": 4}, header)
    assert cmap.col("tier2") == 2 and cmap.source["tier2"] == "override"
    assert cmap.col("img1") is None                       # 显式忽略
    assert cmap.col("img2") == 4 and cmap.col("tier1") == 1
    assert cmap.override_stale is False and cmap.tier_gaps == [] and cmap.missing == []


def test_apply_column_overrides_displaces_conflicting_auto_role():
    header = ["链接", "评论A", "评论B"]
    cmap = build_column_map_auto(header, {})
    apply_column_overrides(cmap, header, {}, {"img1": 2}, header)   # 把「评论B」列改成第 1 层图片
    assert cmap.col("img1") == 2 and cmap.col("tier2") is None and max_tier(cmap) == 1


def test_apply_column_overrides_stale_when_header_changed():
    saved = ["链接", "评论A", "评论B"]
    now = ["链接", "评论B", "评论A"]                      # 两列互换
    cmap = build_column_map_auto(now, {})
    apply_column_overrides(cmap, now, {}, {"tier1": 1}, saved)
    assert cmap.override_stale is True and cmap.col("tier1") == 2   # 沿用自动识别
    cmap2 = build_column_map_auto(now, {})
    apply_column_overrides(cmap2, now, {}, {"tier1": 9}, now)       # 列号越界
    assert cmap2.override_stale is True


def test_describe_columns_and_letters():
    assert col_letter(0) == "A" and col_letter(25) == "Z" and col_letter(26) == "AA"
    header = ["链接", "评论A", ""]
    cols = describe_columns(header, build_column_map_auto(header, {}))
    assert cols[0] == {"col": 0, "letter": "A", "header": "链接", "role": "url",
                       "role_label": "链接", "source": "auto"}
    assert cols[1]["role_label"] == "第 1 层评论"
    assert cols[2]["role"] is None and cols[2]["header"] == "" and cols[2]["source"] is None


def _sheet(sid, name):
    return {"sheet_id": sid, "sheet_name": name, "sheet_type": "worksheet", "row_count": 200, "col_count": 20}


def test_inspect_reports_every_sheet_with_columns_and_routing(monitor_db, settings_path, monkeypatch):
    config_service.patch({"tencent_docs": {
        "enabled": True, "doc_url": "https://docs.qq.com/sheet/D123?tab=DYTAB",
    }})
    monkeypatch.setattr(tds, "read_api_key", lambda p, c=None: "tok")
    fake = FakeSheetClient(sheets=[_sheet("DYTAB", "抖音"), _sheet("XHSTAB", "小红书"), _sheet("MISC", "说明")])
    fake.rows_of("DYTAB").append(["序号", "链接", "评论1", "评论2", "评论3", "日期", "图片1", "图片2", "图片3", "截图1"])
    fake.rows_of("XHSTAB").append(["笔记链接", "一楼", "一楼图片", "二楼"])
    fake.rows_of("MISC").append(["随便", "写点啥"])
    monkeypatch.setattr(tds, "_client_factory", lambda token: fake)

    out = tds.inspect()
    assert out["ok"] is True and out["file_id"] == "D123" and out["doc_url"].startswith("https://docs.qq.com/sheet/D123")
    by = {s["sheet_name"]: s for s in out["sheets"]}
    # 抖音：同名命中；B站 / 快手没有同名子表 → 兜底到 URL tab（也是这张）
    assert by["抖音"]["platforms"] == ["douyin", "bilibili", "kuaishou"] and by["抖音"]["is_fallback"] is True
    assert by["小红书"]["platforms"] == ["xiaohongshu"]
    assert by["说明"]["platforms"] == [] and by["说明"]["missing"]        # 闲置子表缺列不算错
    dy = by["抖音"]
    assert dy["tiers_detected"] == 3 and dy["mapping"]["img3"] == 8 and dy["image_cols_missing"] == []
    assert [c["role"] for c in dy["columns"]][:3] == ["seq", "url", "tier1"]
    assert dy["columns"][9]["role"] is None and dy["columns"][9]["letter"] == "J"
    assert dy["has_override"] is False and dy["override_stale"] is False
    xhs = by["小红书"]
    assert xhs["mapping"] == {"url": 0, "tier1": 1, "img1": 2, "tier2": 3}
    assert xhs["image_cols_missing"] == [2]
    assert out["matched_by_name"] == {"douyin": True, "bilibili": False, "kuaishou": False, "xiaohongshu": True}
    monkeypatch.setattr(tds, "_client_factory", None)


def test_inspect_accepts_explicit_url_without_saving_it(monitor_db, settings_path, monkeypatch):
    config_service.patch({"tencent_docs": {"enabled": True, "doc_url": ""}})
    monkeypatch.setattr(tds, "read_api_key", lambda p, c=None: "tok")
    fake = FakeSheetClient([list(_USER_HEADER)])
    monkeypatch.setattr(tds, "_client_factory", lambda token: fake)
    out = tds.inspect("https://docs.qq.com/sheet/DNEW?tab=BB08J2")
    assert out["file_id"] == "DNEW" and out["ok"] is True
    assert config_service.load().tencent_docs.doc_url == ""      # 只识别，不改配置
    with pytest.raises(TencentDocsError, match="粘贴表格链接"):
        tds.inspect()
    monkeypatch.setattr(tds, "_client_factory", None)


def test_save_mapping_then_sync_and_inspect_use_it(monitor_db, settings_path, monkeypatch):
    """自动识别认不出「楼中楼 / 补充 / 配图」→ 用户手动指定 → 同步按指定列写，识别面板标 override。"""
    config_service.patch({"tencent_docs": {
        "enabled": True, "doc_url": "https://docs.qq.com/sheet/D123?tab=BB08J2",
    }})
    monkeypatch.setattr(tds, "read_api_key", lambda p, c=None: "tok")
    header = ["链接", "主评", "楼中楼", "补充", "配图"]
    fake = FakeSheetClient([list(header)])
    monkeypatch.setattr(tds, "_client_factory", lambda token: fake)

    before = tds.inspect()["sheets"][0]
    assert before["tiers_detected"] == 1 and before["mapping"] == {"url": 0, "tier1": 1}

    saved = tds.save_mapping("D123", "BB08J2", {"tier2": 2, "tier3": 3, "img1": 4}, header)
    assert saved["ok"] is True
    ov = config_service.load().tencent_docs.sheet_col_overrides["D123:BB08J2"]
    assert ov.mapping == {"tier2": 2, "tier3": 3, "img1": 4} and ov.header == header

    after = tds.inspect()["sheets"][0]
    assert after["has_override"] is True and after["override_stale"] is False
    assert after["tiers_detected"] == 3 and after["mapping"]["img1"] == 4
    assert after["columns"][2]["source"] == "override" and after["columns"][1]["source"] == "auto"

    _seed_video_with_comments(1, "https://www.douyin.com/video/111", ["一楼", "二楼", "三楼"], images_on={1})
    result = tds.sync_approved()
    assert result["synced_comments"] == 3 and result["skipped_extra_tiers"] == 0
    assert result["mapping_stale"] == []
    row = fake.rows[1]
    assert row[1] == "一楼" and row[2] == "二楼" and row[3] == "三楼"
    assert row[4] == "有图，另发"                              # 图走 img1 → 「配图」列（无 insert_image 工具）

    assert tds.clear_mapping("D123", "BB08J2")["removed"] is True
    assert tds.inspect()["sheets"][0]["has_override"] is False
    assert tds.clear_mapping("D123", "BB08J2")["removed"] is False
    monkeypatch.setattr(tds, "_client_factory", None)


def test_sync_reports_stale_mapping_when_header_moved(monitor_db, settings_path, monkeypatch):
    config_service.patch({"tencent_docs": {
        "enabled": True, "doc_url": "https://docs.qq.com/sheet/D123?tab=BB08J2",
    }})
    monkeypatch.setattr(tds, "read_api_key", lambda p, c=None: "tok")
    tds.save_mapping("D123", "BB08J2", {"tier2": 2}, ["链接", "主评", "楼中楼"])
    fake = FakeSheetClient([["链接", "主评", "备注", "楼中楼"]])     # 用户后来插了一列
    monkeypatch.setattr(tds, "_client_factory", lambda token: fake)
    _seed_video_with_comments(1, "https://www.douyin.com/video/111", ["一楼", "二楼"])

    result = tds.sync_approved()
    assert result["mapping_stale"] == ["工作表1"]
    assert result["skipped_extra_tiers"] == 1                  # 退回自动识别：楼中楼认不出 → 第 2 层留在 app
    assert fake.rows[1][1] == "一楼" and "二楼" not in fake.rows[1]
    assert tds.inspect()["sheets"][0]["override_stale"] is True
    monkeypatch.setattr(tds, "_client_factory", None)


def test_save_mapping_rejects_bad_input(monitor_db, settings_path):
    with pytest.raises(ValueError, match="未知角色"):
        tds.save_mapping("D1", "S1", {"tier9": 0}, ["a"])
    with pytest.raises(ValueError, match="同一列"):
        tds.save_mapping("D1", "S1", {"tier1": 0, "img1": 0}, ["a"])
    with pytest.raises(ValueError, match="超出"):
        tds.save_mapping("D1", "S1", {"tier1": 3}, ["a", "b"])
    with pytest.raises(ValueError, match="非法"):
        tds.save_mapping("D1", "S1", {"tier1": True}, ["a"])
    assert config_service.load().tencent_docs.sheet_col_overrides == {}


def test_inspect_and_mapping_routes(client, monitor_db, monkeypatch):
    monkeypatch.setattr(tds, "read_api_key", lambda p, c=None: "tok")
    fake = FakeSheetClient([list(_USER_HEADER)])
    monkeypatch.setattr(tds, "_client_factory", lambda token: fake)

    r = client.post("/api/mining/tencent_docs/inspect", json={"doc_url": "https://docs.qq.com/sheet/D9?tab=BB08J2"})
    assert r.status_code == 200
    body = r.json()
    assert body["file_id"] == "D9" and body["sheets"][0]["tiers_detected"] == 3
    assert body["sheets"][0]["columns"][3]["role"] == "img1"

    bad = client.put("/api/mining/tencent_docs/mapping", json={
        "file_id": "D9", "sheet_id": "BB08J2", "mapping": {"nope": 1}, "header": _USER_HEADER,
    })
    assert bad.status_code == 400 and "未知角色" in bad.json()["detail"]

    ok = client.put("/api/mining/tencent_docs/mapping", json={
        "file_id": "D9", "sheet_id": "BB08J2", "mapping": {"img2": None, "tier2": 4}, "header": _USER_HEADER,
    })
    assert ok.status_code == 200 and ok.json()["mapping"] == {"img2": None, "tier2": 4}
    again = client.post("/api/mining/tencent_docs/inspect", json={"doc_url": "https://docs.qq.com/sheet/D9?tab=BB08J2"}).json()
    assert again["sheets"][0]["has_override"] is True and "img2" not in again["sheets"][0]["mapping"]

    gone = client.delete("/api/mining/tencent_docs/mapping/D9/BB08J2")
    assert gone.status_code == 200 and gone.json()["removed"] is True
    monkeypatch.setattr(tds, "_client_factory", None)
