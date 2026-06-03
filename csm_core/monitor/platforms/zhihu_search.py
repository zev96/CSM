"""知乎搜索排名监控 adapter（官方开放平台 API）。

与 baidu_keyword 同语义（关键词 → 品牌词在前 N 的排名），但走知乎官方
搜索 API（GET /api/v1/content/zhihu_search，Bearer 鉴权），返回结构化
JSON，无需爬虫 / cookie / 验证码 / 风控 / 正文抽取。每个关键词 = 一次
API 调用（每天 1000 配额）。匹配字段：Title + ContentText(摘要) +
AuthorName，大小写不敏感。
"""
from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any

import httpx

from ..base import BaseMonitorAdapter, MonitorResult, MonitorTask, maybe_cancel
from ..rate_limit import get_pacer, get_breaker
from csm_core.config import read_api_key

logger = logging.getLogger(__name__)

ZHIHU_SEARCH_URL = "https://developer.zhihu.com/api/v1/content/zhihu_search"

_MAX_COUNT = 10        # 知乎搜索 API 上限：Count 最大 10、无分页
_EXCERPT_CHARS = 160   # UI 预览摘要截断长度


def _api_error(msg: str, *, http_status: int | None = None) -> dict[str, Any]:
    return {
        "ok": False,
        "code": None,
        "message": "",
        "items": [],
        "empty_reason": None,
        "search_hash_id": None,
        "http_status": http_status,
        "error": msg,
    }


def zhihu_search_api(
    query: str,
    count: int,
    secret: str,
    *,
    timeout: float = 20.0,
) -> dict[str, Any]:
    """发一次知乎搜索 API 请求。纯函数，便于 mock httpx 单测。

    Returns 归一化 dict：ok / code / message / items / empty_reason /
    search_hash_id / http_status / error。
    """
    headers = {
        "Authorization": f"Bearer {secret}",
        "X-Request-Timestamp": str(int(time.time())),
        "Content-Type": "application/json",
    }
    params = {"Query": query, "Count": count}
    try:
        resp = httpx.get(ZHIHU_SEARCH_URL, headers=headers, params=params, timeout=timeout)
    except Exception as e:
        return _api_error(f"request raised: {e!r}")

    if resp.status_code >= 400:
        return _api_error(f"http {resp.status_code}", http_status=resp.status_code)

    try:
        payload = resp.json()
    except Exception:
        return _api_error("non-JSON response", http_status=resp.status_code)

    code = payload.get("Code")
    data = payload.get("Data") or {}
    items = data.get("Items") or []
    return {
        "ok": code == 0,
        "code": code,
        "message": str(payload.get("Message") or ""),
        "items": items if isinstance(items, list) else [],
        "empty_reason": data.get("EmptyReason"),
        "search_hash_id": data.get("SearchHashId"),
        "http_status": resp.status_code,
        "error": None,
    }


def match_brand(text: str, brands: list[str]) -> str | None:
    """大小写不敏感找首个出现的品牌词（brands 顺序代表优先级）。"""
    if not text or not brands:
        return None
    text_lc = text.lower()
    for brand in brands:
        if brand and brand.lower() in text_lc:
            return brand
    return None


class ZhihuSearchAdapter:
    """BaseMonitorAdapter 实现。关键词 → 知乎官方搜索 API → 品牌词命中排名。"""

    platform: str = "zhihu_search"

    def __init__(self) -> None:
        self._pacer = get_pacer(self.platform)
        self._breaker = get_breaker(self.platform)

    @staticmethod
    def _match_item(raw: dict[str, Any], brands: list[str]) -> tuple[str | None, str | None]:
        """Return (matched_brand, matched_field) for one item, or (None, None).

        字段优先级：title > excerpt(ContentText) > author。
        """
        for field_name, value in (
            ("title", raw.get("Title")),
            ("excerpt", raw.get("ContentText")),
            ("author", raw.get("AuthorName")),
        ):
            hit = match_brand(str(value or ""), brands)
            if hit:
                return hit, field_name
        return None, None

    @classmethod
    def _rank_results(
        cls, items: list[dict[str, Any]], brands: list[str], count: int,
    ) -> tuple[int, int, list[dict[str, Any]]]:
        """Return (first_rank, matched_count, snapshot[]). rank 1-based，-1=无命中。"""
        snapshot: list[dict[str, Any]] = []
        matched_ranks: list[int] = []
        for i, raw in enumerate(items[:count], start=1):
            matched_brand, matched_field = cls._match_item(raw, brands)
            hit = matched_brand is not None
            if hit:
                matched_ranks.append(i)
            snapshot.append({
                "rank": i,
                "title": str(raw.get("Title") or ""),
                "content_type": str(raw.get("ContentType") or ""),
                "content_id": str(raw.get("ContentID") or ""),
                "url": str(raw.get("Url") or ""),
                "voteup_count": int(raw.get("VoteUpCount") or 0),
                "comment_count": int(raw.get("CommentCount") or 0),
                "author_name": str(raw.get("AuthorName") or ""),
                "authority_level": str(raw.get("AuthorityLevel") or ""),
                "ranking_score": float(raw.get("RankingScore") or 0.0),
                "edit_time": raw.get("EditTime"),
                "matches_brand": hit,
                "matched_brand": matched_brand,
                "matched_field": matched_field,
                "excerpt": str(raw.get("ContentText") or "")[:_EXCERPT_CHARS],
            })
        first_rank = matched_ranks[0] if matched_ranks else -1
        return first_rank, len(matched_ranks), snapshot

    def fetch(
        self,
        task: MonitorTask,
        *,
        progress_cb=None,
        cancel_token=None,
        resume_from: int = 0,
    ) -> MonitorResult:
        """一次检查：逐关键词调官方 API，匹配品牌词，聚合 MonitorResult。

        永不 raise —— 异常包成 status='failed'。``progress_cb(i, N)`` 驱动
        UI 进度条；``cancel_token`` 在关键词之间检查；``resume_from`` 接受
        但本 adapter 不需要（API 快、无断点续传），保留以兼容调度签名。
        """
        if not self._breaker.allow():
            return MonitorResult(
                task_id=task.id or 0, checked_at=datetime.utcnow(),
                status="risk_control", rank=-1,
                error_message="circuit breaker open for zhihu_search",
            )

        cfg = task.config or {}
        keywords = [k.strip() for k in (cfg.get("search_keywords") or []) if k and k.strip()]
        brand = (cfg.get("target_brand") or "").strip()
        aliases = [a.strip() for a in (cfg.get("brand_aliases") or []) if a and a.strip()]
        count = max(1, min(_MAX_COUNT, int(cfg.get("count") or _MAX_COUNT)))

        if not keywords or not brand:
            return MonitorResult(
                task_id=task.id or 0, checked_at=datetime.utcnow(),
                status="failed", rank=-1,
                error_message="config.search_keywords (non-empty) + target_brand required",
            )

        secret = read_api_key("zhihu")
        if not secret:
            return MonitorResult(
                task_id=task.id or 0, checked_at=datetime.utcnow(),
                status="error", rank=-1,
                error_message="未配置知乎 Access Secret，请到设置页填写",
            )

        brands = [brand, *aliases]
        now = datetime.utcnow()
        maybe_cancel(cancel_token)
        if progress_cb is not None:
            try:
                progress_cb(0, len(keywords))
            except Exception:
                logger.exception("progress_cb(0,N) raised; ignoring")

        keyword_results: list[dict[str, Any]] = []
        auth_failed = False

        for idx, kw in enumerate(keywords):
            maybe_cancel(cancel_token)
            if idx > 0:
                self._pacer.wait()
            resp = zhihu_search_api(kw, count, secret)
            entry: dict[str, Any] = {
                "keyword": kw,
                "search_hash_id": resp.get("search_hash_id"),
                "results": [],
                "matched_count": 0,
                "first_rank": -1,
                "result_count": 0,
                "empty_reason": resp.get("empty_reason"),
                "api_code": resp.get("code"),
                "fetch_error": None,
            }
            if resp["ok"]:
                first_rank, matched_count, snapshot = self._rank_results(
                    resp["items"], brands, count,
                )
                entry.update(results=snapshot, matched_count=matched_count,
                             first_rank=first_rank, result_count=len(snapshot))
            elif resp.get("code") == 20001:
                auth_failed = True
                entry["fetch_error"] = "鉴权失败（20001）：Access Secret 错误或系统时钟偏差过大"
                keyword_results.append(entry)
                break
            elif resp.get("code") == 30001:
                entry["fetch_error"] = "频率/配额限制（30001）"
            else:
                entry["fetch_error"] = resp.get("error") or f"api code={resp.get('code')}"
            keyword_results.append(entry)
            logger.info(
                "[zhihu_search] kw=%r code=%s results=%d matched=%d first_rank=%d%s",
                kw, resp.get("code"), entry["result_count"], entry["matched_count"],
                entry["first_rank"],
                f" err={entry['fetch_error']!r}" if entry["fetch_error"] else "",
            )
            if progress_cb is not None:
                try:
                    progress_cb(idx + 1, len(keywords))
                except Exception:
                    logger.exception("progress_cb(%s,N) raised; ignoring", idx + 1)

        first_ranks = [e["first_rank"] for e in keyword_results if e["first_rank"] > 0]
        best_first_rank = min(first_ranks) if first_ranks else -1
        metric: dict[str, Any] = {
            "source": "zhihu_openapi",
            "target_brand": brand,
            "brand_aliases": aliases,
            "search_keywords": keywords,
            "count": count,
            "keywords": keyword_results,
            "total_keywords": len(keywords),
            "matched_keywords": sum(1 for e in keyword_results if e["matched_count"] > 0),
            "total_matches": sum(e["matched_count"] for e in keyword_results),
            "best_first_rank": best_first_rank,
        }

        # 熔断 + 状态：一次 fetch 记一次（对齐 baidu_keyword）。
        #
        # 设计取舍（刻意为之，勿改行为）：30001 频率/配额限制 *计入* 熔断器。
        # 这与 baidu_keyword 的风控处理相反 —— baidu 的 RiskControlException
        # 是用户可操作的验证码/登录墙（见 baidu_keyword.py「不计入熔断器」），
        # 让 runner 写断点 + 暂停任务，故意排除在熔断器之外，因为自动退避帮不上
        # 忙；而知乎是官方 API 的限流，自动退避恰好对症：一旦每天 1000 配额或
        # 每秒速率耗尽，后续每次调用都返回 30001，让连续全 30001 的轮次触发熔断
        # 即可停止在冷却期内继续锤一个已被限流的端点。任一关键词成功（any_ok）
        # 即重置失败窗口，因为它证明凭证 / API 本身是健康的。
        any_ok = any(e.get("api_code") == 0 for e in keyword_results)
        if any_ok and not auth_failed:
            self._breaker.record_success()
        else:
            self._breaker.record_failure()

        if auth_failed:
            status = "error"
            err = "鉴权失败（20001）：检查 Access Secret 或系统时钟"
        elif keyword_results and all(e.get("api_code") == 30001 for e in keyword_results):
            status = "risk_control"
            err = "全部关键词被频率/配额限制（30001）"
        elif not any_ok:
            status = "failed"
            err = "所有关键词请求失败"
        else:
            status = "ok"
            err = ""

        return MonitorResult(
            task_id=task.id or 0, checked_at=now, status=status,
            rank=best_first_rank, metric=metric, error_message=err,
        )


ADAPTER = ZhihuSearchAdapter()
