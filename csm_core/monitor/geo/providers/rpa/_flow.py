"""RPA 交互原语 + 纯 HTML 解析（站点无关，选择器作参数传入）。

DOM 读取拆「纯函数（吃 HTML 串，bs4，CI fixture 可测）+ 薄 page 包装」。
⚠ 传给纯函数的选择器（container_sel/logged_in_sel/logged_out_sel）必须是
合法 CSS（bs4 .select），不能用 Playwright :has-text 伪类。
"""
from __future__ import annotations
import logging
import time
from typing import Any, Callable
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from csm_core.monitor.base import maybe_cancel
from csm_core.monitor.geo.models import Citation

logger = logging.getLogger(__name__)


# ── 纯解析（吃 HTML 串）─────────────────────────────────────────────
def extract_citations(html: str, *, container_sel: str | None = None,
                      exclude_hosts: tuple[str, ...] = ()) -> list[Citation]:
    """抽外链引用：容器内所有 http(s) <a>，title=锚文本，按 url 去重，
    排除 exclude_hosts（自家域名/导航）。container_sel=None 时扫整页。"""
    soup = BeautifulSoup(html or "", "html.parser")
    root = soup.select_one(container_sel) if container_sel else soup
    if root is None:
        return []
    seen: set[str] = set()
    out: list[Citation] = []
    for a in root.select("a[href]"):
        href = (a.get("href") or "").strip()
        if not href.lower().startswith(("http://", "https://")):
            continue
        host = (urlparse(href).hostname or "").lower()
        if any(host == h or host.endswith("." + h) for h in exclude_hosts):
            continue
        if href in seen:
            continue
        seen.add(href)
        title = " ".join(a.get_text(" ", strip=True).split())
        out.append(Citation(url=href, title=title))
    return out


def extract_answer_text(html: str, *, container_sel: str | None = None) -> str:
    """容器内全部后代文本（含链接锚文本），空白折叠；容器缺失返回 ""。"""
    soup = BeautifulSoup(html or "", "html.parser")
    root = soup.select_one(container_sel) if container_sel else soup
    if root is None:
        return ""
    return " ".join(root.get_text(" ", strip=True).split())


def is_logged_in_html(html: str, *, logged_in_sel: str,
                      logged_out_sel: str | None = None) -> bool:
    """logged_in_sel 命中（如 composer 存在）且 logged_out_sel（若给）不命中 → True。"""
    soup = BeautifulSoup(html or "", "html.parser")
    if soup.select_one(logged_in_sel) is None:
        return False
    if logged_out_sel and soup.select_one(logged_out_sel) is not None:
        return False
    return True


# ── page 包装（薄）─────────────────────────────────────────────────
def detect_login(page: Any, *, logged_in_sel: str,
                 logged_out_sel: str | None = None) -> bool:
    try:
        html = page.content()
    except Exception as e:
        logger.warning("detect_login page.content() raised: %s", e)
        return False
    return is_logged_in_html(html, logged_in_sel=logged_in_sel, logged_out_sel=logged_out_sel)


def submit_query(page: Any, *, composer_sel: str, send_sel: str | None, text: str) -> None:
    page.fill(composer_sel, text)
    if send_sel:
        page.click(send_sel)
    else:
        page.press(composer_sel, "Enter")


def ensure_web_toggle(page: Any, *, toggle_sel: str, want_on: bool = True,
                      on_attr: str = "aria-pressed", on_value: str = "true") -> None:
    """开/关联网开关。toggle 不存在 → 忽略（部分站默认联网/无显式开关）。"""
    el = page.query_selector(toggle_sel)
    if el is None:
        logger.info("ensure_web_toggle: %s not found (treat as default-on)", toggle_sel)
        return
    cur_on = (el.get_attribute(on_attr) or "").lower() == on_value.lower()
    if cur_on != want_on:
        el.click()


def wait_stream_done(page: Any, *, done_predicate: Callable[[], bool],
                     idle_ms: int = 1500, timeout_s: float = 90.0,
                     poll_ms: int = 500,
                     cancel_token: "Any | None" = None) -> None:
    """轮询直到 done_predicate() 为真且 page.content() 长度静默 idle_ms。
    超 timeout_s 抛 TimeoutError；每轮 maybe_cancel(cancel_token)（取消即抛）。"""
    deadline = time.monotonic() + timeout_s
    stable_since: float | None = None
    last_len = -1
    while True:
        maybe_cancel(cancel_token)
        if time.monotonic() > deadline:
            raise TimeoutError(f"wait_stream_done exceeded {timeout_s}s")
        try:
            done = bool(done_predicate())
        except Exception as e:
            logger.debug("done_predicate raised: %s", e)
            done = False
        try:
            cur_len = len(page.content())
        except Exception:
            cur_len = last_len
        quiet = cur_len == last_len
        last_len = cur_len
        if done and quiet:
            if stable_since is None:
                stable_since = time.monotonic()
            elif (time.monotonic() - stable_since) * 1000 >= idle_ms:
                return
        else:
            stable_since = None
        time.sleep(poll_ms / 1000.0)


def make_done_predicate(page: Any, *, generating_sel: str | None,
                        send_sel: str | None) -> Callable[[], bool]:
    """构造「流式是否完成」判定 closure，内置「先开始再结束」守卫。

    刚 submit 后，生成指示器（generating_sel，如停止按钮）还没渲染 / send 还没被
    禁用，若此刻直接判完成会误判 → 抓到空回答。故必须先观察到「生成已开始」，
    再以其消失判完成。
    - generating_sel：出现=开始；曾出现且现已消失=完成。
    - 无 generating_sel：退化为 send 按钮——禁用=开始；曾禁用且现可点=完成。
    - 都没有：恒 True（无完成信号，靠 wait_stream_done 的 idle 静默兜底）。
    """
    started = {"v": False}

    def _done() -> bool:
        if generating_sel:
            present = page.query_selector(generating_sel) is not None
            if present:
                started["v"] = True
            return started["v"] and not present
        if send_sel:
            el = page.query_selector(send_sel)
            enabled = el is not None and el.is_enabled()
            if not enabled:
                started["v"] = True
            return started["v"] and enabled
        return True

    return _done
