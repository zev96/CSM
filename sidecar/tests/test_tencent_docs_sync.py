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
        out = client.call_tool("sheet.get_sheet_info", {"file_id": "D1"})
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
        out = client.call_tool("sheet.get_cell_data", {})
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
            client.call_tool("sheet.get_sheet_info", {})


def test_client_http_401_maps_token_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="unauthorized")

    with _mk_client(handler) as client:
        with pytest.raises(TokenInvalidError):
            client.call_tool("sheet.get_sheet_info", {})


# ── Sheet helpers（假 client）──────────────────────────────────────────

class FakeSheetClient:
    """内存表格：rows[r][c] = str。记录 append 调用。"""

    def __init__(self, rows: list[list[str]], *, sheets: list[dict] | None = None):
        self.rows = rows
        self.sheets = sheets or [
            {"sheet_id": "BB08J2", "sheet_name": "工作表1", "sheet_type": "worksheet",
             "row_count": max(200, len(rows)), "col_count": 20},
        ]
        self.csv_writes: list[dict] = []

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass

    def call_tool(self, name, arguments):
        if name == "sheet.get_sheet_info":
            return {"sheets": self.sheets}
        if name == "sheet.get_cell_data":
            cells = []
            for r in range(arguments["start_row"], arguments["end_row"] + 1):
                if r >= len(self.rows):
                    break
                for c in range(arguments["start_col"], arguments["end_col"] + 1):
                    if c < len(self.rows[r]) and self.rows[r][c]:
                        cells.append({"row": r, "col": c,
                                      "value_type": "STRING",
                                      "string_value": self.rows[r][c]})
            return {"cells": cells}
        if name == "sheet.set_range_value_by_csv":
            self.csv_writes.append(arguments)
            # 回放进内存表格，方便断言后续读
            import csv as _csv
            import io
            parsed = list(_csv.reader(io.StringIO(arguments["csv_data"])))
            r0, c0 = arguments["start_row"], arguments["start_col"]
            for dr, row in enumerate(parsed):
                while len(self.rows) <= r0 + dr:
                    self.rows.append([])
                target = self.rows[r0 + dr]
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
    assert result["row_start"] == 1          # 表头在 row 0
    assert result["row_end"] == 2
    assert result["batch_id"] is not None

    # 行内容：列位置按表头映射
    row1 = tdocs_env.rows[1]
    assert row1[0] == "1"                                  # 序号从 1 重排
    assert row1[1] == "标题1 https://www.douyin.com/video/111"
    assert row1[2] == "一楼"
    assert row1[3] == "有图，另发"                          # tier1 挂图 → 贴图一标记
    assert row1[4] == "二楼"
    assert row1[8]                                          # 日期非空（2026.9.1 格式）
    assert "." in row1[8]
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


def test_sync_approved_appends_after_existing_rows(tdocs_env: FakeSheetClient):
    tdocs_env.rows.append(["1", "既有行 https://old/1", "x"])
    tdocs_env.rows.append(["2", "既有行 https://old/2", "y"])
    _seed_video_with_comments(1, "https://www.douyin.com/video/111", ["一楼"])

    result = tds.sync_approved()
    assert result["row_start"] == 3
    assert tdocs_env.rows[3][2] == "一楼"


def test_sync_approved_noop_when_nothing_approved(tdocs_env: FakeSheetClient):
    result = tds.sync_approved()
    assert result["synced_videos"] == 0
    assert result["batch_id"] is None
    assert tdocs_env.csv_writes == []


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
