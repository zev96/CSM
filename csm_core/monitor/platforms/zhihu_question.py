"""Zhihu question rank monitor.

Strategy: a two-track fetch. The fast path uses ``curl_cffi`` against
Zhihu's public answers feed (``/api/v4/questions/{id}/answers``) — that
endpoint serves JSON without login for most public questions, and the
``impersonate="chrome120"`` flag in curl_cffi forges the TLS handshake
fingerprint Zhihu's CDN uses to weed out plain ``requests`` traffic.
When the fast path returns 4xx / risk-control HTML, we fall back to
``DrissionPage`` rendering the question page in a real Chromium and
scraping the DOM. The fallback is slow (5–10s per call) but resilient
to most cookie-only blocks.

The rank we report is 1-based: 1 = the user's brand keyword appears in
the top answer, ``-1`` = not found within the configured ``top_n``.
``metric`` carries the snapshot of the inspected answers so the UI can
render an at-a-glance Top-N preview without re-fetching.
"""
from __future__ import annotations
import logging
import re
import threading
import time
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

from ..base import BaseMonitorAdapter, MonitorResult, MonitorTask, maybe_cancel
from ..rate_limit import get_pacer, get_breaker
from ..drivers import browser_driver
from ..drivers.cookie_store import CookieStore, DEFAULT_COOLDOWN_SECONDS
from ..drivers.ua_pool import UA_POOL as _UA_POOL

logger = logging.getLogger(__name__)


_QUESTION_ID_RE = re.compile(r"/question/(\d+)")
_API_TEMPLATE = "https://www.zhihu.com/api/v4/questions/{qid}/answers"


def _extract_question_id(url: str) -> str | None:
    m = _QUESTION_ID_RE.search(url)
    return m.group(1) if m else None


class ZhihuQuestionAdapter:
    """Implements :class:`BaseMonitorAdapter` for Zhihu question rank."""

    platform: str = "zhihu_question"

    def __init__(self) -> None:
        # CookieStore is rebuilt by ``apply_settings`` whenever the user
        # toggles multi-account mode or changes the rotation N. Default
        # construction matches the legacy behavior so tests + isolated
        # callers don't have to wire settings up.
        self._cookies = CookieStore(self.platform)
        self._ua_idx = 0
        self._pacer = get_pacer(self.platform)
        self._breaker = get_breaker(self.platform)
        # Engine name, mutated by ``apply_settings``. Default = patchright
        # so a sidecar that never loads settings still picks the recommended
        # engine; previously this hardcoded DrissionPage at the import level.
        self._engine: str = "patchright"

    def apply_settings(
        self,
        *,
        engine: str = "patchright",
        rotation_enabled: bool = False,
        tasks_per_account: int = 2,
        cooldown_seconds: int = DEFAULT_COOLDOWN_SECONDS,
    ) -> None:
        """Re-bind the adapter to current user settings.

        Called from ``monitor_lifecycle.start`` (and again on settings
        save). Rebuilding the CookieStore is cheap — it's just an object
        with two counters; the underlying DB rows are unchanged.

        Why not read settings inline on every fetch: the adapter is a
        module-level singleton shared by all in-flight tasks, and reading
        settings from disk per fetch would either need a cache or eat
        the JSON parse cost. Push the settings in on save → adapter
        reads its own fields → zero per-fetch overhead.
        """
        self._engine = engine if engine in ("patchright", "drission") else "patchright"
        self._cookies = CookieStore(
            self.platform,
            rotation_enabled=rotation_enabled,
            tasks_per_account=tasks_per_account,
            cooldown_seconds=cooldown_seconds,
        )

    # ── Public API ──────────────────────────────────────────────────────────
    def fetch(
        self,
        task: MonitorTask,
        cancel_token: threading.Event | None = None,
        **_kwargs,
    ) -> MonitorResult:
        # **_kwargs swallows monitor_loop's progress_cb / resume_from —
        # zhihu doesn't need them, but accepting unknown kwargs avoids the
        # TypeError fallback chain on every call. cancel_token is the
        # only one we actually honor (cooperative mid-fetch cancel).
        if not self._breaker.allow():
            return MonitorResult(
                task_id=task.id or 0,
                checked_at=datetime.utcnow(),
                status="risk_control",
                rank=-1,
                error_message="circuit breaker open for zhihu_question",
            )

        qid = _extract_question_id(task.target_url)
        if not qid:
            return MonitorResult(
                task_id=task.id or 0,
                checked_at=datetime.utcnow(),
                status="failed",
                rank=-1,
                error_message=f"could not parse question id from {task.target_url}",
            )

        target_brand = (task.config.get("target_brand") or "").strip()
        # Top-N 上限 40：超过这个数答案 noise 多、抓取慢，UI 也展示不下；
        # 下限 1。用户在 UI 上设了 50/100 这里 silent clamp，不报错。
        raw_top_n = int(task.config.get("top_n") or 10)
        top_n = max(1, min(40, raw_top_n))
        if not target_brand:
            return MonitorResult(
                task_id=task.id or 0,
                checked_at=datetime.utcnow(),
                status="failed",
                rank=-1,
                error_message="task.config.target_brand is required",
            )

        # Cancel check #1 —— 用户在 pacer wait 之前就点了停止，立刻退出。
        maybe_cancel(cancel_token)

        # Honor the configured request spacing before issuing any HTTP.
        self._pacer.wait()

        # Cancel check #2 —— pacer 可能 sleep 了 N 秒（rate limit），用户期间
        # 点停止应该立刻生效，不发 fast 请求。
        maybe_cancel(cancel_token)

        # Fast path → fallback chain. On both success and final failure
        # we update the breaker so it can decide whether to open.
        answers, source = self._fetch_fast(qid)
        if answers is None:
            # Cancel check #3 —— 这是最有价值的取消点：browser fallback 启动
            # Playwright/DrissionPage 要 5-10s，cookies 解析 + 页面渲染都是
            # 阻塞操作，触发后中途没法退。在这里 short-circuit 才有意义。
            maybe_cancel(cancel_token)
            # browser fallback 现在按 top_n 滚动到加载够；早期版本固定切 20。
            answers, source = self._fetch_browser(task.target_url, qid, top_n=top_n)
        if answers is None:
            self._breaker.record_failure()
            return MonitorResult(
                task_id=task.id or 0,
                checked_at=datetime.utcnow(),
                status="failed",
                rank=-1,
                error_message="both fast and browser fetch failed",
                metric={"source": source},
            )

        self._breaker.record_success()
        first_rank, matched_ranks, snapshot = self._rank_brand(
            answers, target_brand, top_n,
        )
        visit_count = self._fetch_visit_count(qid)
        return MonitorResult(
            task_id=task.id or 0,
            checked_at=datetime.utcnow(),
            status="ok",
            # `rank` 保留首条命中位置，给 sparkline + 旧 UI 兼容
            rank=first_rank,
            metric={
                "source": source,
                "target_brand": target_brand,
                "top_n": top_n,
                # 命中数 + 全部位置：用户在 UI 上主要看这个
                "matched_count": len(matched_ranks),
                "matched_ranks": matched_ranks,
                "answers": snapshot,
                "question_id": qid,
                "question_visit_count": visit_count,
            },
        )

    # ── Fast path: curl_cffi ───────────────────────────────────────────────
    def _fetch_fast(self, qid: str) -> tuple[list[dict[str, Any]] | None, str]:
        try:
            from curl_cffi import requests as cc_requests
        except ImportError:
            logger.warning("curl_cffi not available; skipping fast path")
            return None, "curl_cffi_missing"

        cred = self._cookies.pick()
        ua = cred.user_agent if cred and cred.user_agent else self._next_ua()
        headers = {
            "User-Agent": ua,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Referer": f"https://www.zhihu.com/question/{qid}",
            "x-requested-with": "fetch",
        }
        cookies = self._parse_cookies(cred.cookies_text) if cred else {}

        # ``include`` whitelist trimmed to fields we actually display —
        # matches what the official web client requests, so the API is
        # less likely to flag the request as scripted.
        params = {
            "include": (
                "data[*].is_normal,suggest_edit,comment_count,collapsed_counts,"
                "reviewing_comments_count,can_comment,content,voteup_count,"
                "reshipment_settings,comment_permission,created_time,updated_time,"
                "review_info,question,excerpt,is_labeled,paid_info,relationship.is_authorized,"
                "is_author,voting,is_thanked,is_nothelp,is_recognized;"
                "data[*].author.badge[?(type=best_answerer)].topics;"
                "data[*].author.member.role,member.url_token,member.id,member.name,"
                "member.avatar_url,member.headline,member.gender,member.user_type"
            ),
            "limit": "20",
            "offset": "0",
            "platform": "desktop",
            "sort_by": "default",
        }
        url = _API_TEMPLATE.format(qid=qid)
        try:
            resp = cc_requests.get(
                url,
                headers=headers,
                cookies=cookies,
                params=params,
                impersonate="chrome120",
                timeout=20,
            )
        except Exception as e:
            logger.info("zhihu fast path raised: %s", e)
            if cred:
                self._cookies.mark_failed(cred)
            return None, "curl_cffi_exception"

        if resp.status_code != 200:
            logger.info("zhihu fast path HTTP %s", resp.status_code)
            if cred:
                self._cookies.mark_failed(cred)
            return None, f"curl_cffi_http_{resp.status_code}"

        try:
            payload = resp.json()
        except Exception:
            logger.info("zhihu fast path returned non-JSON (likely risk-control HTML)")
            if cred:
                self._cookies.mark_failed(cred)
            return None, "curl_cffi_non_json"

        data = payload.get("data") if isinstance(payload, dict) else None
        if not data:
            return None, "curl_cffi_empty_data"

        if cred:
            self._cookies.mark_ok(cred)
        # Map to the simplified shape we use downstream so the rest of
        # the adapter doesn't care which source produced the answers.
        answers: list[dict[str, Any]] = []
        for item in data:
            try:
                author = (item.get("author") or {}).get("name", "")
                # 保留完整答案文本 —— zhihu 答案常 2k-30k 字，目标品牌词
                # 可能出现在任意位置。匹配用全文（_rank_brand 里做 in 查找），
                # UI 展示的 200 字预览在 _rank_brand 里另外截。500 字硬截会
                # 漏掉 80% 内容里的命中（实测见日志）。
                content = self._strip_tags(item.get("content") or item.get("excerpt") or "")
                answers.append({
                    "author": author,
                    "content": content,
                    "voteup_count": int(item.get("voteup_count") or 0),
                    "comment_count": int(item.get("comment_count") or 0),
                    "url": item.get("url") or "",
                    "created_time": item.get("created_time"),
                })
            except Exception:
                continue
        return answers, "curl_cffi"

    # ── 问题浏览量（best-effort，无 cookie）────────────────────────────────
    def _fetch_visit_count(self, qid: str) -> int | None:
        """拉问题「被浏览」数。走 /api/v4/questions/{qid}?include=visit_count。

        不取 cookie（公开元数据 + 避免动轮换计数器）。任何失败返回 None，
        UI 端显示 "—"。加 INFO raw 日志便于排查 silent failure。
        """
        try:
            from curl_cffi import requests as cc_requests
        except ImportError:
            return None
        headers = {
            "User-Agent": self._next_ua(),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Referer": f"https://www.zhihu.com/question/{qid}",
            "x-requested-with": "fetch",
        }
        url = f"https://www.zhihu.com/api/v4/questions/{qid}"
        try:
            resp = cc_requests.get(
                url, headers=headers, params={"include": "visit_count"},
                impersonate="chrome120", timeout=15,
            )
        except Exception as e:
            logger.info("zhihu visit_count fetch raised: %s", e)
            return None
        if resp.status_code != 200:
            logger.info("zhihu visit_count HTTP %s (qid=%s)", resp.status_code, qid)
            return None
        try:
            payload = resp.json()
        except Exception:
            logger.info("zhihu visit_count non-JSON (qid=%s)", qid)
            return None
        vc = payload.get("visit_count") if isinstance(payload, dict) else None
        vc_int = int(vc) if isinstance(vc, (int, float)) else None
        logger.info("zhihu visit_count qid=%s -> %s", qid, vc_int)
        return vc_int

    # ── Fallback: real browser (Patchright by default, Drission fallback) ────
    def _fetch_browser(
        self, url: str, qid: str, top_n: int = 20,
    ) -> tuple[list[dict[str, Any]] | None, str]:
        """Render question page in a real Chromium and scrape AnswerItem cards.

        Engine is chosen via ``self._engine`` ("patchright" | "drission")
        — see ``browser_driver`` for the abstraction. Adapter logic is
        identical regardless of engine; only the JS calls and selector
        queries go through ``driver.evaluate_js`` / ``driver.query_count``.

        知乎问题页是**懒加载**：初始 HTML 通常只渲染 5-10 条答案，剩下的
        要下滑触发 lazy mount。所以这里不能简单 `query_count >= top_n`
        切完事 —— 必须 scroll 到底 → 等新卡 → 重复，直到至少有
        ``top_n`` 张 card 或卷动了 N 次还没增加。

        Args:
            top_n: 目标答案数（来自 task.config.top_n，已经在 fetch() clamp 到 1-40）。
        """
        try:
            driver = browser_driver.get_driver(self._engine)
        except RuntimeError as e:
            logger.warning(
                "zhihu browser fallback unavailable (engine=%s): %s",
                self._engine, e,
            )
            return None, f"browser_unavailable_{self._engine}"

        # 注入 cookie —— browser 的 user-data-dir 跨进程持久化，上次跑
        # 留下的 cookie（甚至跑出 /unhuman 时存的"游客"cookie）会干扰
        # 这次注入。流程：
        #   1. 先 navigate 到 zhihu 空白页（建立域上下文，DrissionPage 必需）
        #   2. clear 掉 zhihu 域所有旧 cookie（防止跟新 cookie 冲突）
        #   3. 只注一次 .zhihu.com（Playwright 不归一化前缀点，注两次
        #      会变成两套；DrissionPage 也只需要一个）
        #   4. 回读 cookie 列表，日志里确认 z_c0 等关键字真的进去了
        # 旧版本同时注 ".zhihu.com" 和 "zhihu.com" 是为了兼容 DrissionPage
        # 不同小版本对前缀点的处理差异 —— 实测 Patchright 下会变成两套
        # 不同的 cookie 同时发送，zhihu 后端拒识别 → 永远登录页。
        cred = self._cookies.pick()
        if cred and cred.cookies_text:
            try:
                parsed_keys = [
                    p.split("=", 1)[0].strip()
                    for p in cred.cookies_text.split(";")
                    if "=" in p
                ]
                # Patchright: 跳过前置 navigate —— Playwright 不需要先有域上
                # 下文也能 add_cookies。原本的 navigate("https://www.zhihu.com/")
                # 等于用空 cookie 状态打一次 zhihu 首页，zhihu 会回一堆游客
                # cookie 还顺带在反爬端登记一次"新会话"。直接 inject 然后
                # navigate 到目标 question URL，第一次 HTTP 请求就带着我们
                # 的 z_c0 等关键 cookie。
                # DrissionPage: 仍需前置 navigate（set.cookies 要求域上下文）。
                if self._engine == "drission":
                    driver.navigate("https://www.zhihu.com/")
                # 清掉 user-data-dir 里上次跑剩的 zhihu cookie（关键修复，
                # 否则跟新 cookie 同名/同域 → Playwright 不 dedup，发请求
                # 时 Cookie header 里会出现两份 z_c0 server 端拒识别）。
                driver.clear_cookies("zhihu")
                driver.inject_cookies(".zhihu.com", cred.cookies_text)
                landed_names = driver.read_cookie_names("zhihu")
                critical = ["z_c0", "q_c1", "d_c0", "_zap"]
                missing_critical = [k for k in critical if k not in landed_names]
                # 算出"输入里有 / 落地里没"的那些 —— Playwright 偶尔会因为
                # cookie value 含未 escape 的特殊字符（如 `;` `,`）静默 drop。
                # 把丢的那条记到日志，反推是 value 问题还是 attrs 问题。
                input_set = set(parsed_keys)
                landed_set = set(landed_names)
                dropped = sorted(input_set - landed_set)
                logger.info(
                    "zhihu browser cookie injected: engine=%s label=%r "
                    "input=%d landed=%d (z_c0_in_input=%s, z_c0_landed=%s, "
                    "missing_critical=%s, dropped_by_browser=%s)",
                    self._engine,
                    cred.label,
                    len(parsed_keys),
                    len(landed_names),
                    "yes" if "z_c0" in parsed_keys else "MISSING_FROM_INPUT",
                    "yes" if "z_c0" in landed_names else "DROPPED_BY_BROWSER",
                    missing_critical or "none",
                    dropped or "none",
                )
            except Exception as e:
                logger.warning("zhihu browser cookie inject failed: %s", e)
        else:
            logger.warning(
                "zhihu browser fallback has no cookie; will likely hit login redirect. "
                "Add a Cookie via Cookie Manager."
            )

        try:
            driver.navigate(url)
            landed = driver.current_url()
            if "signin" in landed or "login" in landed:
                logger.warning(
                    "zhihu browser landed on login page (%s) — cookie likely "
                    "expired or invalid; will likely abort with 0 cards",
                    landed,
                )
                # 立即把当前 cred 标失败并冷却 —— 下一个 task 切下一条 cookie。
                if cred:
                    self._cookies.mark_failed(cred)
            elif "unhuman" in landed or "/account/unhuman" in landed:
                logger.warning(
                    "zhihu hit anti-bot wall (%s) — re-grab cookie or wait "
                    "and retry. Sometimes triggers even with valid cookies.",
                    landed,
                )
                if cred:
                    self._cookies.mark_failed(cred)
            # 注 CSS 缩短每条答案高度 + 隐藏图片占位 + 隐藏侧边栏。
            # 答案默认每条占 800-1500px 高，把每条压到 200px 上限 → 滚 2-3
            # 次就到底，触发懒加载快得多。CSS 只影响 viewport 渲染，不影响
            # DOM 节点（querySelector 仍然找得到 .AnswerItem 和子选择器）。
            driver.evaluate_js("""
                const css = `
                    .AnswerItem { max-height: 200px !important; overflow: hidden !important; }
                    .AnswerItem .RichContent { max-height: 100px !important; overflow: hidden !important; }
                    img, picture, video, figure { display: none !important; }
                    .Question-sideColumn, .Question-main .QuestionRichText,
                    .css-1qyytj7, .HotQuestions, .Pc-card { display: none !important; }
                `;
                const s = document.createElement('style');
                s.textContent = css;
                document.head.appendChild(s);
            """)

            # 等首批 card 渲染（冷缓存 5-10s，热路径秒级）
            driver.wait_for_any(".AnswerItem", timeout_s=15.0)

            # 滚动加载策略（按用户实测）：
            #   1. scroll 到 body 底
            #   2. 往上回弹一点（-200px）—— 知乎的 IntersectionObserver 监听
            #      底部 sentinel；停在精确底部时 observer 可能因为 "出 viewport"
            #      没触发，回弹一点让 sentinel 重新进入 viewport
            #   3. 等 2s 让新 card mount
            # 每轮 ≈ 2.5s。max_rounds=20 够拉 top_n=40 的极端情况。
            prev_count = 0
            stagnant_rounds = 0
            max_rounds = 20
            for round_i in range(max_rounds):
                cur_count = driver.query_count(".AnswerItem")
                if cur_count >= top_n:
                    break
                if cur_count == prev_count and round_i > 0:
                    stagnant_rounds += 1
                    if stagnant_rounds >= 3:
                        break
                else:
                    stagnant_rounds = 0
                prev_count = cur_count
                driver.evaluate_js("""
                    window.scrollTo(0, document.body.scrollHeight);
                    setTimeout(() => window.scrollBy(0, -200), 300);
                """)
                time.sleep(2.0)

            all_count = driver.query_count(".AnswerItem")
            logger.info(
                "zhihu browser fetch: engine=%s rendered %d cards total, "
                "taking top %d (landed url=%s)",
                self._engine, all_count, min(all_count, top_n),
                landed[:120] if landed else "?",
            )
        except Exception as e:
            logger.warning("zhihu browser fetch raised: %s", e)
            return None, "browser_exception"

        if all_count == 0:
            logger.warning(
                "zhihu browser fetch: 0 AnswerItem cards — likely login wall "
                "or anti-bot. Last landed URL: %s",
                landed[:200] if landed else "?",
            )
            return None, "browser_no_cards"

        # 用一次 JS 调用批量抽全 cards 的内容 —— 关键是用 `textContent` 而
        # 不是 `innerText`：
        #   - innerText 只给可见文本，zhihu 的"阅读全文"折叠 + 我们注的
        #     `overflow:hidden` 都会让 innerText 漏掉后半段
        #   - textContent 直接读 DOM 文本，无视 CSS / display:none
        # 还能少 N 次跨语言 round trip。
        raw = driver.evaluate_js(
            """
            const limit = args[0];
            const cards = Array.from(document.querySelectorAll('.AnswerItem')).slice(0, limit);
            return cards.map(card => {
                const authorEl = card.querySelector('.AuthorInfo-name');
                const contentEl = card.querySelector('.RichContent-inner')
                               || card.querySelector('.RichContent');
                const voteEl = card.querySelector('.VoteButton--up');
                return {
                    author: authorEl ? authorEl.textContent.trim() : '',
                    content: contentEl ? contentEl.textContent.trim() : '',
                    voteup_text: voteEl ? voteEl.textContent.trim() : '0',
                };
            });
            """,
            top_n,
        )

        answers: list[dict[str, Any]] = []
        for item in raw or []:
            try:
                # 不截断 content：_rank_brand 用全文匹配品牌词，UI 预览
                # 200 字在 _rank_brand 里另外截。详见 fast path 里的同款注释。
                answers.append({
                    "author": str(item.get("author") or ""),
                    "content": str(item.get("content") or ""),
                    "voteup_count": _parse_count(str(item.get("voteup_text") or "0")),
                    "comment_count": 0,
                    "url": "",
                    "created_time": None,
                })
            except Exception:
                continue

        # 浏览器拿到结果，给当前 cookie 记一次成功（轮换计数器在 pick() 里
        # 已经 +1，这里只更新 last_used_at + 清 fail_count）。
        if answers and cred:
            self._cookies.mark_ok(cred)
        return (answers if answers else None), f"browser_{self._engine}"

    # ── Helpers ────────────────────────────────────────────────────────────
    def _next_ua(self) -> str:
        ua = _UA_POOL[self._ua_idx % len(_UA_POOL)]
        self._ua_idx += 1
        return ua

    @staticmethod
    def _parse_cookies(text: str) -> dict[str, str]:
        out: dict[str, str] = {}
        for piece in (text or "").split(";"):
            piece = piece.strip()
            if not piece or "=" not in piece:
                continue
            k, _, v = piece.partition("=")
            out[k.strip()] = v.strip()
        return out

    @staticmethod
    def _strip_tags(html: str) -> str:
        # Lightweight tag stripper — we only need a preview snippet, not
        # faithful Markdown. Avoids pulling bs4 into the hot path.
        return re.sub(r"<[^>]+>", "", html or "").strip()

    @staticmethod
    def _rank_brand(
        answers: list[dict[str, Any]],
        brand: str,
        top_n: int,
    ) -> tuple[int, list[int], list[dict[str, Any]]]:
        """Return (first_rank, all_matched_ranks, top-N snapshot).

        - ``first_rank``: 首个命中的 1-based 位置；全部未命中 → -1。保留这
          个字段是为了 sparkline 的"首条排名走势"和向后兼容旧 result 行。
        - ``all_matched_ranks``: 所有命中位置（1-based）。`len(...)` 就是
          用户最关心的"前 N 条里有几条是我"。
        - ``snapshot``: 前 N 个答案的元数据；每条带 ``matches_brand`` 旗，
          前端在详情列表里据此高亮自家答案。
        """
        brand_lc = brand.lower()
        matched_ranks: list[int] = []
        snapshot: list[dict[str, Any]] = []
        for i, ans in enumerate(answers[:top_n], start=1):
            content = (ans.get("content") or "").lower()
            author = (ans.get("author") or "").lower()
            hit = brand_lc in content or brand_lc in author
            snapshot.append({
                "rank": i,
                "author": ans.get("author", ""),
                "content_preview": (ans.get("content") or "")[:200],
                "voteup_count": ans.get("voteup_count", 0),
                "matches_brand": hit,
            })
            if hit:
                matched_ranks.append(i)
        first_rank = matched_ranks[0] if matched_ranks else -1
        return first_rank, matched_ranks, snapshot


def _parse_count(text: str) -> int:
    """Zhihu shows '1.2 万' / '12.3K' on the rendered page; normalize."""
    if not text:
        return 0
    text = text.replace(",", "").strip()
    try:
        if "万" in text:
            return int(float(text.replace("万", "").strip()) * 10000)
        if "k" in text.lower():
            return int(float(text.lower().replace("k", "").strip()) * 1000)
        m = re.search(r"\d+", text)
        return int(m.group()) if m else 0
    except (ValueError, AttributeError):
        return 0


# Module-level singleton — imported by csm_core/monitor/platforms/__init__.py
ADAPTER = ZhihuQuestionAdapter()
