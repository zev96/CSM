"""腾讯文档 Sheet MCP 客户端（移植自官方「龙虾」skill 的调用方式）。

Skill 包（cdn.addon.tencentsuite.com/static/tencent-docs.zip）里的表格
操作走 MCP over Streamable HTTP：

    endpoint  https://docs.qq.com/api/v6/sheet/mcp
    鉴权      Authorization: <TENCENT_DOCS_TOKEN>（原样直传，无 Bearer 前缀，
              与 skill 的 mcporter 配置 ``--header "Authorization=$Token"`` 一致）
    协议      JSON-RPC 2.0（initialize → notifications/initialized → tools/call）

响应可能是纯 JSON，也可能是 SSE 帧（Streamable HTTP 规范允许两种），
``_parse_response`` 两者都收。工具结果优先取 ``structuredContent``，
否则解析 ``content[0].text`` 里的 JSON 文本。

架构对照 TikHub 集成（monitor/tikhub/client.py）：token 走 keyring、
日志脱敏、不自动重试、错误映射成用户可读中文（errors.py）。
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any

import httpx

from .errors import TencentDocsError, TokenInvalidError, map_error

logger = logging.getLogger(__name__)

SHEET_MCP_URL = "https://docs.qq.com/api/v6/sheet/mcp"

_PROTOCOL_VERSION = "2025-03-26"
_CLIENT_INFO = {"name": "csm-sidecar", "version": "1.0"}


def _redact(token: str) -> str:
    if not token:
        return "<empty>"
    return token[:4] + "…" + token[-4:] if len(token) > 8 else "<short>"


class TencentDocsMCPClient:
    """薄封装：一次会话（initialize 一回）+ 若干 tools/call。

    transport 参数仅供测试注入（httpx.MockTransport）。
    """

    def __init__(
        self,
        token: str,
        *,
        base_url: str = SHEET_MCP_URL,
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not (token or "").strip():
            raise TokenInvalidError("未配置腾讯文档 Token，请在设置页粘贴")
        self._token = token.strip()
        self._base_url = base_url
        self._session_id: str | None = None
        self._initialized = False
        self._http = httpx.Client(
            timeout=timeout,
            transport=transport,
            headers={
                "Authorization": self._token,
                "Content-Type": "application/json",
                # Streamable HTTP 规范要求两种都接受；服务端选其一返回。
                "Accept": "application/json, text/event-stream",
            },
        )

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "TencentDocsMCPClient":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # ── JSON-RPC plumbing ────────────────────────────────────────────────
    def _post(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        headers: dict[str, str] = {}
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        try:
            resp = self._http.post(self._base_url, json=payload, headers=headers)
        except httpx.HTTPError as e:
            raise TencentDocsError(f"腾讯文档服务网络错误：{e}") from e

        sid = resp.headers.get("Mcp-Session-Id") or resp.headers.get("mcp-session-id")
        if sid:
            self._session_id = sid

        if resp.status_code in (401, 403):
            raise TokenInvalidError()
        if resp.status_code >= 400:
            raise TencentDocsError(
                f"腾讯文档服务 HTTP {resp.status_code}：{resp.text[:200]}"
            )
        # 202/204 = 通知类请求被接受，无 body。
        if resp.status_code in (202, 204) or not resp.content:
            return None
        return self._parse_response(resp)

    @staticmethod
    def _parse_response(resp: httpx.Response) -> dict[str, Any]:
        ctype = resp.headers.get("content-type", "")
        text = resp.text
        if "text/event-stream" in ctype:
            # SSE 帧：取最后一个 data: 行里的 JSON-RPC message（服务端可能
            # 先发进度事件，response 在最后）。
            last: dict[str, Any] | None = None
            for line in text.splitlines():
                line = line.strip()
                if not line.startswith("data:"):
                    continue
                chunk = line[len("data:"):].strip()
                if not chunk:
                    continue
                try:
                    msg = json.loads(chunk)
                except ValueError:
                    continue
                if isinstance(msg, dict) and ("result" in msg or "error" in msg):
                    last = msg
            if last is None:
                raise TencentDocsError("腾讯文档服务返回的事件流中没有结果帧")
            return last
        try:
            body = json.loads(text)
        except ValueError as e:
            raise TencentDocsError(f"腾讯文档服务返回非 JSON：{text[:200]}") from e
        if not isinstance(body, dict):
            raise TencentDocsError(f"腾讯文档服务返回异常结构：{text[:200]}")
        return body

    def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        msg = self._post({
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": "initialize",
            "params": {
                "protocolVersion": _PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": _CLIENT_INFO,
            },
        })
        if msg is not None and "error" in msg:
            err = msg["error"] or {}
            raise map_error(str(err.get("message") or err))
        # initialized 通知：规范要求；服务端不认时忽略失败（stateless 实现常见）。
        try:
            self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        except TencentDocsError:
            logger.debug("initialized notification rejected; continuing (stateless server?)")
        self._initialized = True

    # ── Public API ───────────────────────────────────────────────────────
    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """调一个表格工具（不带前缀，如 ``get_sheet_info``），返回结构化结果
        dict（成功空结果 = {}）。工具名由 tools/list 确认，见 sheet.py 顶注。"""
        self._ensure_initialized()
        msg = self._post({
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        })
        if msg is None:
            raise TencentDocsError(f"{name} 无响应")
        if "error" in msg:
            err = msg["error"] or {}
            raise map_error(str(err.get("message") or err))
        result = msg.get("result") or {}

        if result.get("isError"):
            raise map_error(_content_text(result))

        structured = result.get("structuredContent")
        if isinstance(structured, dict):
            return structured
        text = _content_text(result)
        if text:
            try:
                parsed = json.loads(text)
                if isinstance(parsed, dict):
                    return parsed
            except ValueError:
                pass
        return {}

    def list_tools(self) -> list[str]:
        """枚举服务端注册的工具名（MCP ``tools/list``）—— 纯诊断用。

        现网 ``sheet-mcp`` 实为「智能表格（smartsheet.*）」服务，与本模块
        假设的经典表格 ``sheet.*`` 单元格工具不是一套；「测试连接」用它把
        服务端真实工具清单摊给用户，据实定方案（见设计文档 §5.1 待验证项）。
        分页游标 ``nextCursor`` 存在则续拉（工具数很少，10 页硬上限兜底）。
        """
        self._ensure_initialized()
        names: list[str] = []
        cursor: str | None = None
        for _ in range(10):
            params: dict[str, Any] = {"cursor": cursor} if cursor else {}
            msg = self._post({
                "jsonrpc": "2.0",
                "id": str(uuid.uuid4()),
                "method": "tools/list",
                "params": params,
            })
            if msg is None:
                break
            if "error" in msg:
                err = msg["error"] or {}
                raise map_error(str(err.get("message") or err))
            result = msg.get("result") or {}
            for tool in result.get("tools") or []:
                if isinstance(tool, dict) and tool.get("name"):
                    names.append(str(tool["name"]))
            cursor = result.get("nextCursor")
            if not cursor:
                break
        return names

    def __repr__(self) -> str:  # 日志里绝不能露 token
        return f"TencentDocsMCPClient(token={_redact(self._token)})"


def _content_text(result: dict[str, Any]) -> str:
    """拼接 MCP tool result 的 content[] 文本块。"""
    parts: list[str] = []
    for item in result.get("content") or []:
        if isinstance(item, dict) and item.get("type") == "text":
            parts.append(str(item.get("text") or ""))
    return "\n".join(parts).strip()
