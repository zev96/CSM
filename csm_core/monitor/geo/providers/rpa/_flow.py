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
    排除 exclude_hosts（自家域名/导航）。container_sel=None 时扫整页。
    container_sel 命中多个容器时**全取**（回答常拆成多块：前言/表格/小结）。"""
    soup = BeautifulSoup(html or "", "html.parser")
    roots = soup.select(container_sel) if container_sel else [soup]
    seen: set[str] = set()
    out: list[Citation] = []
    for root in roots:
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
    """容器内全部后代文本（含链接锚文本），空白折叠；容器缺失返回 ""。
    container_sel 命中多个容器时**全部拼接**——回答常拆成多块（前言/表格/小结），
    只取首块会漏掉品牌所在的表格行 → 误判「未提及」。"""
    soup = BeautifulSoup(html or "", "html.parser")
    if not container_sel:
        return " ".join(soup.get_text(" ", strip=True).split())
    roots = soup.select(container_sel)
    if not roots:
        return ""
    joined = " ".join(r.get_text(" ", strip=True) for r in roots)
    return " ".join(joined.split())


def parse_source_items(html: str, *, item_sel: str) -> list[Citation]:
    """纯解析「源」面板的引用来源条目（元宝）。元宝信源不是 <a>，没有 URL，
    只有媒体名 + 文章标题；这里抓条目文本作 title、url 留空，按 title 去重。
    ⚠ url="" → classify 出 domain=""（信源榜按域名聚合时归「其他/空」，是元宝
    平台的固有限制，不是 bug）。"""
    soup = BeautifulSoup(html or "", "html.parser")
    out: list[Citation] = []
    seen: set[str] = set()
    for item in soup.select(item_sel):
        title = " ".join(item.get_text(" ", strip=True).split())
        if title and title not in seen:
            seen.add(title)
            out.append(Citation(url="", title=title))
    return out


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


def wait_login_ready(page: Any, *, logged_in_sel: str, logged_out_sel: str | None = None,
                     timeout_s: float = 10.0, poll_ms: int = 400,
                     settle_ms: int = 800) -> bool:
    """轮询直到登录态**可判定**再返回，避免重 SPA 加载未完就误判「未登录」。

    每轮取 page.content()：
    - logged_out_sel 命中 → 明确未登录 → False（如元宝 composer 占位「请登录」）。
    - logged_in_sel 命中（且未命中 logged_out）→ 已登录 → True。
    - 两者都没出现 → 还在加载，继续等。
    超 timeout_s 仍判不定（连 composer 都没渲染出来）→ False（按未登录处理）。

    比 detect_login 单帧快照稳：旧写法 goto 后只等 2s 就判，元宝这种重站 composer
    还没渲染 → 误报未登录（真站实测：已登录却返回 blocked）。
    """
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            html = page.content()
        except Exception:
            time.sleep(poll_ms / 1000.0)
            continue
        soup = BeautifulSoup(html or "", "html.parser")
        if logged_out_sel and soup.select_one(logged_out_sel) is not None:
            return False
        if soup.select_one(logged_in_sel) is not None:
            # composer 一出现就返回会太早（页面还没完全可交互，Kimi 这种登录后
            # 直接 submit、没有中间步骤吸收时序的最易踩）→ 稍等再返回，降低提交过早失败。
            page.wait_for_timeout(settle_ms)
            return True
        time.sleep(poll_ms / 1000.0)
    return False


def submit_query(page: Any, *, composer_sel: str, send_sel: str | None, text: str,
                 focus_ms: int = 250, key_delay_ms: int = 20, commit_ms: int = 400) -> None:
    """聚焦 composer + 真键盘逐字打字（带节流），再点 send_sel（无则按 Enter）。

    用 page.keyboard.type 而非 page.fill —— Lexical/Quill 等受控富文本编辑器
    不处理 fill 注入的值（其 onChange 不触发），会导致发送键不激活 / 提交空。

    **必须带延时**：聚焦后稍等（focus_ms）→ 逐字打（key_delay_ms）→ 提交前再等
    （commit_ms）。否则富文本（元宝 Quill 实测）来不及把输入提交进编辑器 model，
    瞬时 type+Enter 不触发发送 → 答案根本不出（真站验证：无延时 50s 0 字，带延时
    27s 出 969 字）。延时对 DeepSeek 的 textarea / Kimi 的 Lexical 无害（仅略慢）。
    """
    page.click(composer_sel)
    page.wait_for_timeout(focus_ms)
    page.keyboard.type(text, delay=key_delay_ms)
    page.wait_for_timeout(commit_ms)
    if send_sel:
        page.click(send_sel)
    else:
        page.keyboard.press("Enter")


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


def start_new_chat(page: Any, *, new_chat_sel: str, answer_sel: str,
                   timeout_s: float = 5.0, poll_ms: int = 300) -> bool:
    """点「新建对话」开一段干净会话，避免读到上一轮残留对话。

    部分站（元宝）打开即恢复上次会话 —— 不新建会把上轮答案算进「本轮」（done
    判定与抓取都污染）。这里点 icon 的**父按钮**，且用 JS 点而非 page.click：
    - 绕过 icon ``<span>`` 被同位兄弟图标拦截 pointer events（直接点会超时）；
    - 跳过隐藏副本（折叠/展开两套导航），只取首个 ``offsetParent`` 非空者。

    ``new_chat_sel`` 不在场（如 DeepSeek/Kimi 打开即新会话）→ 返回 False 跳过。
    点完轮询「回答容器」清空（旧答案消失）再返回，最多 ``timeout_s``；超时仍返回
    True（继续往下走，至多读到旧答案，由调用方容忍）。
    """
    clicked = page.evaluate(
        """(sel) => {
            const ic = [...document.querySelectorAll(sel)].find(e => e.offsetParent !== null);
            if (!ic) return false;
            (ic.closest('button') || ic.parentElement).click();
            return true;
        }""",
        new_chat_sel,
    )
    if not clicked:
        logger.info("start_new_chat: %s 不在场，跳过（视作打开即新会话）", new_chat_sel)
        return False
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            cur = len(extract_answer_text(page.content(), container_sel=answer_sel))
        except Exception:
            cur = 0
        if cur < 30:                       # 回答容器已清空 → 新会话就绪
            return True
        time.sleep(poll_ms / 1000.0)
    logger.info("start_new_chat: %ss 内视图未清空，继续（可能含旧答案）", timeout_s)
    return True


def enable_toggle_by_text(page: Any, *, text: str, active_substr: str = "selected",
                          wait_ms: int = 400) -> bool:
    """确保「文字标签的模式开关」处于开启态（如 深度思考）—— 幂等。

    找到 inner_text==text 的开关元素（DeepSeek `div.ds-toggle-button` / 元宝
    `div[class*=ThinkSelector...]` 两站文字都是「深度思考」），若其 class 已含
    active_substr（两站激活态都带 `selected`）则跳过（**避免误关**），否则点击开启。
    找不到 → False（容错，不抛）。新会话里开关一般重置为默认（深度思考=关），故
    点一次即开。
    """
    cands = page.query_selector_all(
        "div[class*='toggle'], div[class*='Selector'], div[class*='Think'], button")
    for el in cands:
        try:
            if (el.inner_text() or "").strip() != text:
                continue
            tcls = el.get_attribute("class") or ""
            if active_substr.lower() in tcls.lower():
                return True                      # 已开启，幂等跳过
            el.click()
            page.wait_for_timeout(wait_ms)
            return True
        except Exception as e:
            logger.info("enable_toggle_by_text('%s') click failed: %s", text, e)
            return False
    logger.info("enable_toggle_by_text('%s') not found", text)
    return False


def enable_tool_web_search(page: Any, *, tool_sel: str, item_text: str,
                           wait_ms: int = 600) -> bool:
    """元宝式联网搜索：点「工具」下拉 → 选「联网搜索」菜单项。失败不抛。

    新会话里默认未开，点一次即开。⚠ 若平台跨会话记忆该开关，重复点会**关掉**
    （目前靠 start_new_chat 重置规避；如线上发现没搜索，再加 active 态判断）。
    """
    try:
        page.click(tool_sel, timeout=4000)
        page.wait_for_timeout(wait_ms)
        page.click(f"li.t-dropdown__item:has-text('{item_text}')", timeout=4000)
        page.wait_for_timeout(wait_ms)
        return True
    except Exception as e:
        logger.info("enable_tool_web_search('%s') failed: %s", item_text, e)
        return False


def expand_search_toolcalls(page: Any, *, toolcall_sel: str, hint: str = "搜索",
                            max_clicks: int = 6) -> int:
    """点开 Kimi「搜索网页」toolcall，露出搜到的信源 <a>（best-effort，错误忽略）。

    Kimi 信源不稳：答案内联 <a> 有时为空，但搜索 toolcall 点开后能露出搜到的网页
    链接（含 bing 跳转壳 + 真实直链）。点开后调用方再全页抓 <a> + 过滤 bing/自家域名。
    返回点开的 toolcall 数。
    """
    clicked = 0
    try:
        tcs = page.query_selector_all(toolcall_sel)
    except Exception:
        return 0
    for tc in tcs:
        if clicked >= max_clicks:
            break
        try:
            if hint not in (tc.inner_text() or ""):
                continue
            tc.scroll_into_view_if_needed(timeout=1500)
            tc.click(timeout=2500)
            clicked += 1
            page.wait_for_timeout(900)
        except Exception:
            continue
    return clicked


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
                        answer_sel: str) -> Callable[[], bool]:
    """构造「流式是否完成」判定 closure，内置「先开始再结束」守卫。

    刚 submit 后回答还没流出来，若直接判完成会误判 → 抓空。故必须先观察到
    「回答已开始」，再判完成。
    - generating_sel（停止按钮等）：出现=开始；曾出现且现已消失=完成。
    - 无 generating_sel：测**回答容器**文本增长判「已开始」（不用整页长度——
      用户消息/UI 渲染会误触发），再由 wait_stream_done 的 idle 静默判完成。
      （Kimi 发送键完成后仍 disabled、DeepSeek/元宝 无停止键 aria，都走这条。）
    """
    started = {"v": False}
    base_len: "dict[str, int | None]" = {"v": None}

    def _done() -> bool:
        if generating_sel:
            present = page.query_selector(generating_sel) is not None
            if present:
                started["v"] = True
            return started["v"] and not present
        try:
            cur = len(extract_answer_text(page.content(), container_sel=answer_sel))
        except Exception:
            return False
        if base_len["v"] is None:
            base_len["v"] = cur
        if cur > (base_len["v"] or 0) + 30:
            started["v"] = True
        return started["v"]

    return _done
