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


# ── Sheet helpers（假 client）──────────────────────────────────────────

class FakeSheetClient:
    """内存表格（可多子表）：rows_of(sheet_id)[r][c] = str。记录 CSV/样式调用。"""

    def __init__(self, rows: list[list[str]] | None = None, *, sheets: list[dict] | None = None):
        self.sheets = sheets or [
            {"sheet_id": "BB08J2", "sheet_name": "工作表1", "sheet_type": "worksheet",
             "row_count": 200, "col_count": 20},
        ]
        first_id = self.sheets[0]["sheet_id"]
        self.rows_by_sheet: dict[str, list[list[str]]] = {first_id: rows if rows is not None else []}
        self.csv_writes: list[dict] = []
        self.style_calls: list[dict] = []

    @property
    def rows(self) -> list[list[str]]:
        """第一张子表的行（单表用例的便捷别名）。"""
        return self.rows_by_sheet[self.sheets[0]["sheet_id"]]

    def rows_of(self, sheet_id: str) -> list[list[str]]:
        return self.rows_by_sheet.setdefault(sheet_id, [])

    def list_tools(self) -> list[str]:
        return ["get_sheet_info", "get_cell_data", "set_range_value_by_csv"]

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
    assert [p["platform"] for p in out["sheets"]] == ["douyin", "bilibili", "kuaishou"]
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
