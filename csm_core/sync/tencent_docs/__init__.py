"""腾讯文档同步（评论工作流 P3）。

移植官方「龙虾」腾讯文档 skill 的 sheet-mcp 调用：单 token（keyring
provider="tencent_docs"）直连 https://docs.qq.com/api/v6/sheet/mcp。
"""
from .client import SHEET_MCP_URL, TencentDocsMCPClient
from .errors import TencentDocsError, TokenInvalidError, VipRequiredError
from .sheet import (
    ColumnMap,
    SheetTarget,
    append_rows_csv,
    build_column_map,
    find_last_used_row,
    parse_doc_url,
    read_column_texts,
    read_row_texts,
    resolve_sheet,
)

__all__ = [
    "SHEET_MCP_URL",
    "TencentDocsMCPClient",
    "TencentDocsError",
    "TokenInvalidError",
    "VipRequiredError",
    "ColumnMap",
    "SheetTarget",
    "append_rows_csv",
    "build_column_map",
    "find_last_used_row",
    "parse_doc_url",
    "read_column_texts",
    "read_row_texts",
    "resolve_sheet",
]
