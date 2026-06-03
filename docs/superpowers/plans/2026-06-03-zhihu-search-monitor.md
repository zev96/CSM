# 知乎搜索排名监控 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在监测中心新增 `zhihu_search` 任务类型——用知乎官方搜索 API 对每个关键词取前 10 结果，在标题/摘要/作者匹配品牌词，记录 1-based 排名。

**Architecture:** 复用现有 `csm_core/monitor/` 平台 adapter 范式（`fetch(task) -> MonitorResult`）。`monitor_loop` / 存储 / 路由全部泛型已覆盖，后端只加 3 处（TaskType 字面量 + 新 adapter + 注册）。官方 API 是干净的 `GET + Bearer`，用 `httpx`，无爬虫/cookie/验证码。前端加一个 Tab + 表单分支 + 结果模块 + 设置页凭证框。

**Tech Stack:** Python（httpx, pydantic）· pytest · Vue 3 + TypeScript · vue-tsc · 知乎开放平台 API

**Spec:** `docs/superpowers/specs/2026-06-03-zhihu-search-monitor-design.md`

---

## File Structure

**后端（PR #1）**
- `csm_core/monitor/base.py` — Modify: `TaskType` Literal 加 `"zhihu_search"`
- `csm_core/monitor/platforms/zhihu_search.py` — Create: `zhihu_search_api()` + `match_brand()` + `ZhihuSearchAdapter` + `ADAPTER`
- `csm_core/monitor/platforms/__init__.py` — Modify: import + 注册进 `ALL`
- `tests/core/monitor/test_zhihu_search.py` — Create: 单测
- `scripts/manual_test_zhihu_search.py` — Create: 手动联调脚本
- `CHANGELOG.md` — Modify: 加条目

**前端（PR #2）**
- `frontend/src/utils/monitor-types.ts` — Modify: `ZhihuSearchTaskConfig` 接口
- `frontend/src/components/monitor/AddTaskModal.vue` — Modify: 类型/表单/校验/提交分支
- `frontend/src/components/monitor/ZhihuSearchModule.vue` — Create: 结果模块
- `frontend/src/views/MonitorView.vue` — Modify: 加 `zhihu_search` Tab
- `frontend/src/views/SettingsView.vue` — Modify: 知乎 Access Secret 区块

**可选全文匹配（PR #3，用户「可行再加」）**
- `csm_core/monitor/platforms/zhihu_content.py` — Create: 共享正文抓取 helper
- 以上 adapter / 表单 / 模块的全文分支

---

# PR #1 — 后端 + 单测

## Task 1: TaskType 加 `zhihu_search`

**Files:**
- Modify: `csm_core/monitor/base.py:44-51`
- Test: `tests/core/monitor/test_zhihu_search.py`

- [ ] **Step 1: Write the failing test**

创建 `tests/core/monitor/test_zhihu_search.py`：

```python
"""Tests for the zhihu_search monitor adapter (官方搜索 API · 品牌词命中排名)."""
from __future__ import annotations

from csm_core.monitor.base import MonitorTask


def test_zhihu_search_is_valid_task_type():
    """MonitorTask 接受 type='zhihu_search'（Literal 已扩展）。"""
    t = MonitorTask(type="zhihu_search", name="测试", target_url="https://x")
    assert t.type == "zhihu_search"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/core/monitor/test_zhihu_search.py::test_zhihu_search_is_valid_task_type -v`
Expected: FAIL — pydantic `ValidationError`（`zhihu_search` 不在 Literal 里）

- [ ] **Step 3: Add the literal**

`csm_core/monitor/base.py`，把 `TaskType` 改成：

```python
TaskType = Literal[
    "zhihu_question",
    "zhihu_search",
    "bilibili_comment",
    "douyin_comment",
    "kuaishou_comment",
    "baidu_keyword",
    "geo_query",
]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/core/monitor/test_zhihu_search.py::test_zhihu_search_is_valid_task_type -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add csm_core/monitor/base.py tests/core/monitor/test_zhihu_search.py
git commit -m "feat(monitor): add zhihu_search to TaskType"
```

---

## Task 2: `zhihu_search_api()` 请求 + 解析（mock httpx）

**Files:**
- Create: `csm_core/monitor/platforms/zhihu_search.py`
- Test: `tests/core/monitor/test_zhihu_search.py`

- [ ] **Step 1: Write the failing tests**

把以下追加到 `tests/core/monitor/test_zhihu_search.py`（顶部 import 处加 `from csm_core.monitor.platforms import zhihu_search as zs`）：

```python
class _FakeResp:
    def __init__(self, status_code: int, payload=None, raise_json=False):
        self.status_code = status_code
        self._payload = payload
        self._raise_json = raise_json

    def json(self):
        if self._raise_json:
            raise ValueError("not json")
        return self._payload


_OK_PAYLOAD = {
    "Code": 0,
    "Message": "success",
    "Data": {
        "HasMore": False,
        "SearchHashId": "hash123",
        "Items": [
            {
                "Title": "RAG 评测方法综述",
                "ContentType": "Article",
                "ContentID": "111",
                "ContentText": "本文介绍主流 RAG 评测框架…",
                "Url": "https://zhuanlan.zhihu.com/p/111?utm_x=1",
                "CommentCount": 15,
                "VoteUpCount": 128,
                "AuthorName": "张三",
                "AuthorityLevel": "2",
                "EditTime": 1710000000,
                "RankingScore": 0.98,
            }
        ],
    },
}


def test_api_ok_parses_items(monkeypatch):
    monkeypatch.setattr(zs.httpx, "get", lambda *a, **k: _FakeResp(200, _OK_PAYLOAD))
    out = zs.zhihu_search_api("rag", 10, "secret")
    assert out["ok"] is True
    assert out["code"] == 0
    assert out["search_hash_id"] == "hash123"
    assert len(out["items"]) == 1
    assert out["items"][0]["Title"] == "RAG 评测方法综述"


def test_api_30001_marked_not_ok(monkeypatch):
    payload = {"Code": 30001, "Message": "rate limited", "Data": {}}
    monkeypatch.setattr(zs.httpx, "get", lambda *a, **k: _FakeResp(200, payload))
    out = zs.zhihu_search_api("rag", 10, "secret")
    assert out["ok"] is False
    assert out["code"] == 30001
    assert out["items"] == []


def test_api_empty_reason_passthrough(monkeypatch):
    payload = {"Code": 0, "Message": "ok", "Data": {"Items": [], "EmptyReason": "无结果"}}
    monkeypatch.setattr(zs.httpx, "get", lambda *a, **k: _FakeResp(200, payload))
    out = zs.zhihu_search_api("rag", 10, "secret")
    assert out["ok"] is True
    assert out["empty_reason"] == "无结果"
    assert out["items"] == []


def test_api_http_500_is_error(monkeypatch):
    monkeypatch.setattr(zs.httpx, "get", lambda *a, **k: _FakeResp(500, None))
    out = zs.zhihu_search_api("rag", 10, "secret")
    assert out["ok"] is False
    assert out["http_status"] == 500
    assert out["error"]


def test_api_non_json_is_error(monkeypatch):
    monkeypatch.setattr(zs.httpx, "get", lambda *a, **k: _FakeResp(200, None, raise_json=True))
    out = zs.zhihu_search_api("rag", 10, "secret")
    assert out["ok"] is False
    assert "non-JSON" in out["error"]


def test_api_transport_exception_is_error(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("conn reset")
    monkeypatch.setattr(zs.httpx, "get", boom)
    out = zs.zhihu_search_api("rag", 10, "secret")
    assert out["ok"] is False
    assert "conn reset" in out["error"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/core/monitor/test_zhihu_search.py -k api -v`
Expected: FAIL — `ModuleNotFoundError` / `AttributeError`（`zhihu_search` 模块不存在）

- [ ] **Step 3: Create the module with `zhihu_search_api`**

创建 `csm_core/monitor/platforms/zhihu_search.py`：

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/core/monitor/test_zhihu_search.py -k api -v`
Expected: PASS（6 个 api 测试全绿）

- [ ] **Step 5: Commit**

```bash
git add csm_core/monitor/platforms/zhihu_search.py tests/core/monitor/test_zhihu_search.py
git commit -m "feat(monitor): zhihu_search_api request+parse with tests"
```

---

## Task 3: 品牌匹配 + 排名（纯函数 `match_brand` / `_match_item` / `_rank_results`）

**Files:**
- Modify: `csm_core/monitor/platforms/zhihu_search.py`
- Test: `tests/core/monitor/test_zhihu_search.py`

- [ ] **Step 1: Write the failing tests**

追加到 `tests/core/monitor/test_zhihu_search.py`：

```python
def _item(title="", text="", author=""):
    return {"Title": title, "ContentText": text, "AuthorName": author,
            "ContentType": "Article", "ContentID": "x", "Url": "https://z/x",
            "VoteUpCount": 0, "CommentCount": 0, "AuthorityLevel": "0",
            "EditTime": 0, "RankingScore": 0.0}


def test_match_brand_case_insensitive_and_order():
    assert zs.match_brand("I love Claude Code", ["claude"]) == "claude"
    assert zs.match_brand("无关", ["claude"]) is None
    # 顺序代表优先级：主品牌排前
    assert zs.match_brand("anthropic claude", ["claude", "anthropic"]) == "claude"


def test_match_item_field_precedence():
    # 标题命中优先
    assert zs.ZhihuSearchAdapter._match_item(_item(title="戴森评测"), ["戴森"]) == ("戴森", "title")
    # 标题没有 → 摘要
    assert zs.ZhihuSearchAdapter._match_item(_item(text="我用戴森"), ["戴森"]) == ("戴森", "excerpt")
    # 都没有 → 作者
    assert zs.ZhihuSearchAdapter._match_item(_item(author="戴森官方"), ["戴森"]) == ("戴森", "author")
    # 全无 → (None, None)
    assert zs.ZhihuSearchAdapter._match_item(_item(title="小米"), ["戴森"]) == (None, None)


def test_rank_results_first_rank_and_count():
    items = [
        _item(title="小米吸尘器"),       # 1
        _item(text="戴森 V12 真香"),      # 2 ✓
        _item(author="添可"),            # 3
        _item(title="戴森对比小米"),      # 4 ✓
    ]
    first, count, snap = zs.ZhihuSearchAdapter._rank_results(items, ["戴森"], 10)
    assert first == 2
    assert count == 2
    assert len(snap) == 4
    assert snap[1]["matches_brand"] is True
    assert snap[1]["matched_field"] == "excerpt"
    assert snap[0]["matches_brand"] is False
    # 摘要截断 160
    assert len(snap[0]["excerpt"]) <= 160


def test_rank_results_no_match_returns_minus_one():
    items = [_item(title="小米"), _item(title="添可")]
    first, count, snap = zs.ZhihuSearchAdapter._rank_results(items, ["戴森"], 10)
    assert first == -1
    assert count == 0
    assert len(snap) == 2


def test_rank_results_respects_count_cap():
    items = [_item(title="无关")] * 9 + [_item(title="戴森")]  # 命中在第 10
    first, count, snap = zs.ZhihuSearchAdapter._rank_results(items, ["戴森"], 5)
    assert first == -1  # 只看前 5
    assert len(snap) == 5
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/core/monitor/test_zhihu_search.py -k "match or rank" -v`
Expected: FAIL — `AttributeError`（`match_brand` / `ZhihuSearchAdapter` 未定义）

- [ ] **Step 3: Add matcher functions + class skeleton**

在 `csm_core/monitor/platforms/zhihu_search.py` 的 `zhihu_search_api` 之后追加：

```python
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
                "excerpt": str(raw.get("ContentText") or "")[:160],
            })
        first_rank = matched_ranks[0] if matched_ranks else -1
        return first_rank, len(matched_ranks), snapshot
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/core/monitor/test_zhihu_search.py -k "match or rank" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add csm_core/monitor/platforms/zhihu_search.py tests/core/monitor/test_zhihu_search.py
git commit -m "feat(monitor): zhihu_search brand matcher + ranker with tests"
```

---

## Task 4: `fetch()` 编排 + 注册 adapter

**Files:**
- Modify: `csm_core/monitor/platforms/zhihu_search.py`
- Modify: `csm_core/monitor/platforms/__init__.py`
- Test: `tests/core/monitor/test_zhihu_search.py`

- [ ] **Step 1: Write the failing tests**

追加到 `tests/core/monitor/test_zhihu_search.py`：

```python
def _task(**cfg):
    return MonitorTask(type="zhihu_search", name="t", target_url="https://z",
                       id=1, config=cfg)


def _patch_secret(monkeypatch, value="secret"):
    monkeypatch.setattr(zs, "read_api_key", lambda provider: value)


def test_fetch_missing_config_fails(monkeypatch):
    _patch_secret(monkeypatch)
    r = zs.ADAPTER.fetch(_task(search_keywords=[], target_brand=""))
    assert r.status == "failed"


def test_fetch_missing_secret_errors(monkeypatch):
    _patch_secret(monkeypatch, value="")
    r = zs.ADAPTER.fetch(_task(search_keywords=["rag"], target_brand="戴森"))
    assert r.status == "error"
    assert "Access Secret" in r.error_message


def test_fetch_ok_aggregates_best_rank(monkeypatch):
    _patch_secret(monkeypatch)

    def fake_api(query, count, secret, **k):
        # kw "a" → 命中在 rank 2；kw "b" → 命中在 rank 1
        if query == "a":
            return {"ok": True, "code": 0, "items": [_item(title="无"), _item(title="戴森")],
                    "empty_reason": None, "search_hash_id": "h", "message": "", "http_status": 200, "error": None}
        return {"ok": True, "code": 0, "items": [_item(title="戴森王")],
                "empty_reason": None, "search_hash_id": "h", "message": "", "http_status": 200, "error": None}

    monkeypatch.setattr(zs, "zhihu_search_api", fake_api)
    r = zs.ADAPTER.fetch(_task(search_keywords=["a", "b"], target_brand="戴森"))
    assert r.status == "ok"
    assert r.rank == 1  # best across keywords
    assert r.metric["matched_keywords"] == 2
    assert r.metric["total_keywords"] == 2
    assert len(r.metric["keywords"]) == 2


def test_fetch_20001_aborts_with_error(monkeypatch):
    _patch_secret(monkeypatch)
    calls = {"n": 0}

    def fake_api(query, count, secret, **k):
        calls["n"] += 1
        return {"ok": False, "code": 20001, "items": [], "empty_reason": None,
                "search_hash_id": None, "message": "", "http_status": 200, "error": None}

    monkeypatch.setattr(zs, "zhihu_search_api", fake_api)
    r = zs.ADAPTER.fetch(_task(search_keywords=["a", "b", "c"], target_brand="戴森"))
    assert r.status == "error"
    assert "20001" in r.error_message
    assert calls["n"] == 1  # 第一次 20001 即中止，不再打后两个关键词


def test_fetch_all_30001_is_risk_control(monkeypatch):
    _patch_secret(monkeypatch)
    monkeypatch.setattr(zs, "zhihu_search_api", lambda *a, **k: {
        "ok": False, "code": 30001, "items": [], "empty_reason": None,
        "search_hash_id": None, "message": "", "http_status": 200, "error": None})
    r = zs.ADAPTER.fetch(_task(search_keywords=["a"], target_brand="戴森"))
    assert r.status == "risk_control"


def test_adapter_registered():
    from csm_core.monitor.platforms import ALL
    assert "zhihu_search" in ALL
    assert ALL["zhihu_search"].platform == "zhihu_search"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/core/monitor/test_zhihu_search.py -k "fetch or registered" -v`
Expected: FAIL — `AttributeError: ... 'ADAPTER'` / `'fetch'`，registry 测试 KeyError

- [ ] **Step 3: Implement `fetch()` + `ADAPTER` singleton**

在 `csm_core/monitor/platforms/zhihu_search.py` 的 `ZhihuSearchAdapter` 类里（`_rank_results` 之后）加 `fetch`，并在文件末尾加单例：

```python
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
        count = max(1, min(10, int(cfg.get("count") or 10)))

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
```

- [ ] **Step 4: Register in `__init__.py`**

`csm_core/monitor/platforms/__init__.py` 改成：

```python
"""Per-platform monitor adapters. Each module exposes ``ADAPTER`` —
a singleton implementing :class:`csm_core.monitor.base.BaseMonitorAdapter`.
"""
from .zhihu_question import ADAPTER as ZHIHU
from .zhihu_search import ADAPTER as ZHIHU_SEARCH
from .bilibili_comment import ADAPTER as BILIBILI
from .douyin_comment import ADAPTER as DOUYIN
from .kuaishou_comment import ADAPTER as KUAISHOU
from .baidu_keyword import ADAPTER as BAIDU
from .geo_query import ADAPTER as GEO

ALL = {
    "zhihu_question": ZHIHU,
    "zhihu_search": ZHIHU_SEARCH,
    "bilibili_comment": BILIBILI,
    "douyin_comment": DOUYIN,
    "kuaishou_comment": KUAISHOU,
    "baidu_keyword": BAIDU,
    "geo_query": GEO,
}

__all__ = ["ZHIHU", "ZHIHU_SEARCH", "BILIBILI", "DOUYIN", "KUAISHOU", "BAIDU", "GEO", "ALL"]
```

- [ ] **Step 5: Run the full test file**

Run: `python -m pytest tests/core/monitor/test_zhihu_search.py -v`
Expected: PASS（全部，约 18 个）

- [ ] **Step 6: Commit**

```bash
git add csm_core/monitor/platforms/zhihu_search.py csm_core/monitor/platforms/__init__.py tests/core/monitor/test_zhihu_search.py
git commit -m "feat(monitor): zhihu_search fetch orchestration + register adapter"
```

---

## Task 5: 手动联调脚本 + CHANGELOG

**Files:**
- Create: `scripts/manual_test_zhihu_search.py`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Create the manual test script**

创建 `scripts/manual_test_zhihu_search.py`：

```python
"""手动联调 zhihu_search adapter。

用法（PowerShell）：
    $env:ZHIHU_SECRET="<你的 Access Secret>"
    python scripts/manual_test_zhihu_search.py 扫地机器人 戴森

参数：argv[1]=关键词（可多个用引号）、最后一个=目标品牌词。
不走 keyring，直接读环境变量 ZHIHU_SECRET，方便快速验证。
"""
from __future__ import annotations

import json
import os
import sys

from csm_core.monitor.base import MonitorTask
from csm_core.monitor.platforms import zhihu_search as zs


def main() -> None:
    secret = os.environ.get("ZHIHU_SECRET", "")
    if not secret:
        print("请先设置环境变量 ZHIHU_SECRET", file=sys.stderr)
        sys.exit(1)
    if len(sys.argv) < 3:
        print("用法: python scripts/manual_test_zhihu_search.py <关键词...> <品牌词>", file=sys.stderr)
        sys.exit(1)
    *keywords, brand = sys.argv[1:]

    # monkeypatch read_api_key 直接返回环境变量里的 secret
    zs.read_api_key = lambda provider: secret  # type: ignore[assignment]

    task = MonitorTask(
        type="zhihu_search", name="manual", target_url="https://z", id=0,
        config={"search_keywords": keywords, "target_brand": brand, "count": 10},
    )
    result = zs.ADAPTER.fetch(task)
    print(f"status={result.status} rank={result.rank}")
    print(json.dumps(result.metric, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Add CHANGELOG entry**

打开 `CHANGELOG.md`，在最上方的版本/`[Unreleased]` 区块的「新增 / Added」下加一条（沿用文件现有的标题层级与中文措辞风格）：

```markdown
- 监测中心新增「知乎搜索排名」监控：用知乎官方搜索 API 对关键词取前 10 结果，追踪目标品牌词命中位置。需在设置页填写知乎开放平台 Access Secret。
```

- [ ] **Step 3: Run the full backend test suite (regression check)**

Run: `python -m pytest tests/core/monitor/ -v`
Expected: PASS（新文件 + 既有 monitor 测试都不破）

- [ ] **Step 4: Commit**

```bash
git add scripts/manual_test_zhihu_search.py CHANGELOG.md
git commit -m "chore(monitor): zhihu_search manual test script + CHANGELOG"
```

> **PR #1 收尾：** push 分支 + `gh pr create`，标题「feat(monitor): 知乎搜索排名监控后端」。

---

# PR #2 — 前端 + 端到端

## Task 6: `monitor-types.ts` 加配置接口

**Files:**
- Modify: `frontend/src/utils/monitor-types.ts`

- [ ] **Step 1: Add the interface**

在 `frontend/src/utils/monitor-types.ts` 末尾（`scheduleLabel` 函数之前的某处，与其它 `*TaskConfig` 接口并列）加：

```ts
/**
 * zhihu_search 任务的 ``config`` 形状（对齐 csm_core.monitor.platforms.zhihu_search
 * adapter 读取的键）：多关键词 + 单品牌词 + 可选别名 + 固定 count。
 * ``match_full_text`` 为 PR #3 的可选全文匹配开关（默认 false）。
 */
export interface ZhihuSearchTaskConfig {
  search_keywords: string[];
  target_brand: string;
  brand_aliases: string[];
  count: number;
  match_full_text?: boolean;
}
```

- [ ] **Step 2: Typecheck**

Run: `cd frontend && npm run build`
Expected: PASS（vue-tsc 无报错）

- [ ] **Step 3: Commit**

```bash
git add frontend/src/utils/monitor-types.ts
git commit -m "feat(monitor-ui): ZhihuSearchTaskConfig type"
```

---

## Task 7: AddTaskModal 加 `zhihu_search` 分支

**Files:**
- Modify: `frontend/src/components/monitor/AddTaskModal.vue`

> 关键陷阱：`isComment` 当前定义为「不是 zhihu_question / baidu_keyword / geo_query」。新增 `zhihu_search` **必须**也排除，否则会被误当评论任务。

- [ ] **Step 1: Extend the TaskType union + TYPES list**

`AddTaskModal.vue` script 顶部：

```ts
type TaskType = "zhihu_question" | "zhihu_search" | "bilibili_comment" | "douyin_comment" | "kuaishou_comment" | "baidu_keyword" | "geo_query";
```

`TYPES` 数组加一项（放在 zhihu_question 之后）：

```ts
const TYPES = [
  { value: "zhihu_question", label: "知乎问题（排名监测）" },
  { value: "zhihu_search", label: "知乎搜索排名" },
  { value: "bilibili_comment", label: "B 站评论留存" },
  { value: "douyin_comment", label: "抖音评论留存" },
  { value: "kuaishou_comment", label: "快手评论留存" },
  { value: "baidu_keyword", label: "百度关键词排名" },
  { value: "geo_query", label: "AI 卡位监控（GEO）" },
] as const;
```

- [ ] **Step 2: Add refs + computed (and FIX isComment)**

在 GEO refs 之后加知乎搜索 refs：

```ts
// 知乎搜索（zhihu_search）—— 关键词 list + 单品牌词 + 别名
const zsKeywordsRaw = ref(""); // newline-separated
const zsTargetBrand = ref("");
const zsAliasesText = ref(""); // comma-separated
```

把 `isComment` 改成排除 zhihu_search，并加 `isZhihuSearch`：

```ts
const isGeo = computed(() => type.value === "geo_query");
const isZhihuSearch = computed(() => type.value === "zhihu_search");
const isComment = computed(() =>
  type.value !== "zhihu_question" &&
  type.value !== "zhihu_search" &&
  type.value !== "baidu_keyword" &&
  type.value !== "geo_query"
);
const isBaidu = computed(() => type.value === "baidu_keyword");
const isEdit = computed(() => !!props.editingTask);
```

- [ ] **Step 3: Reset in close() + hydrate in hydrateFromTask()**

`close()` 里（GEO 重置附近）加：

```ts
  zsKeywordsRaw.value = "";
  zsTargetBrand.value = "";
  zsAliasesText.value = "";
```

`hydrateFromTask()` 里（GEO hydration 之后）加：

```ts
  // 知乎搜索 hydration
  const zsKeywords: string[] = Array.isArray(cfg.search_keywords) ? cfg.search_keywords : [];
  // 注意：baidu 也用 search_keywords，这里只在 type==zhihu_search 时用到，互不干扰
  zsKeywordsRaw.value = zsKeywords.join("\n");
  zsTargetBrand.value = String(cfg.target_brand ?? "");
  const zsAliases: string[] = Array.isArray(cfg.brand_aliases) ? cfg.brand_aliases : [];
  zsAliasesText.value = zsAliases.join("，");
```

- [ ] **Step 4: validate() + submit() branches**

`validate()` 在 `isGeo` 分支之后、`isBaidu` 之前插入：

```ts
  } else if (isZhihuSearch.value) {
    const keywords = zsKeywordsRaw.value.split(/\r?\n/).map((s) => s.trim()).filter(Boolean);
    if (keywords.length === 0) return "搜索关键词至少填一个";
    if (!zsTargetBrand.value.trim()) return "目标品牌词不能为空";
```

`submit()` 里组 config，在 `isGeo` 分支之后、`isBaidu` 之前插入：

```ts
    } else if (isZhihuSearch.value) {
      const keywords = zsKeywordsRaw.value.split(/\r?\n/).map((s) => s.trim()).filter(Boolean);
      config = {
        search_keywords: keywords,
        target_brand: zsTargetBrand.value.trim(),
        brand_aliases: zsAliasesText.value.split(/[，,]/).map((s) => s.trim()).filter(Boolean),
        count: 10,
      };
      // target_url 由第一个关键词派生 —— 后端要求非空；点开是真实知乎搜索页
      computedTargetUrl = "https://www.zhihu.com/search?type=content&q=" + encodeURIComponent(keywords[0]);
```

- [ ] **Step 5: Template — fields block + guard existing fields**

在 GEO 的 `<template v-if="isGeo">…</template>` 之后插入知乎搜索字段块：

```html
          <!-- 知乎搜索排名：关键词 / 品牌词 / 别名 -->
          <template v-if="isZhihuSearch">
            <FormField label="搜索关键词" hint="一行一个，每个关键词单独搜一次（每次消耗 1 次知乎 API 配额，每天 1000）">
              <textarea
                v-model="zsKeywordsRaw"
                rows="4"
                placeholder="如：&#10;扫地机器人推荐&#10;宠物吸尘器"
                class="bg-card-2 focus:bg-card-white outline-none transition-colors"
                :style="{
                  width: '100%', resize: 'vertical', padding: '6px 10px',
                  fontSize: '12.5px', fontFamily: 'inherit', border: '1px solid var(--line)',
                  borderRadius: 'var(--radius-inner)', color: 'var(--ink)', boxSizing: 'border-box',
                }"
              />
            </FormField>
            <FormField label="目标品牌词" hint="命中前 10 结果的标题/摘要/作者就算「我」">
              <FormInput v-model="zsTargetBrand" placeholder="如：示例品牌" debounce="live" />
            </FormField>
            <FormField label="品牌别名" hint="逗号分隔；命中任一别名都算命中（可留空）">
              <FormInput v-model="zsAliasesText" placeholder="如：ExampleBrand，EB" debounce="live" />
            </FormField>
          </template>
```

把三个「通用」字段的 `v-if` 都加上 `&& !isZhihuSearch`：

1. 目标 URL 字段（约 line 444）：`v-if="!isBaidu && !isGeo && !isZhihuSearch"`
2. 目标品牌关键词字段（约 line 665）：`v-if="!isComment && !isBaidu && !isGeo && !isZhihuSearch"`
3. Top-N 字段（约 line 677）：`v-if="!isBaidu && !isGeo && !isZhihuSearch"`

同时 `validate()` 顶部的「目标 URL 不能为空」判断也要放行 zhihu_search（约 line 270）：

```ts
  if (!isBaidu.value && !isGeo.value && !isZhihuSearch.value && !targetUrl.value.trim()) return "目标 URL 不能为空";
```

- [ ] **Step 6: Typecheck**

Run: `cd frontend && npm run build`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/monitor/AddTaskModal.vue
git commit -m "feat(monitor-ui): AddTaskModal zhihu_search branch"
```

---

## Task 8: ZhihuSearchModule.vue（结果模块）

**Files:**
- Create: `frontend/src/components/monitor/ZhihuSearchModule.vue`

> 先 Read `frontend/src/components/monitor/ZhihuMonitorModule.vue` 与 `geo/GeoTaskModule.vue`，对齐它们的列表/详情视觉与 `useSidecar().client` 用法。下面是**完整可运行的最小版**（只依赖已验证的原语：`useSidecar`、`subscribe`、`AddTaskModal`、原生 div + tailwind），落地后按 sibling 调整样式细节。

- [ ] **Step 1: Create the component**

创建 `frontend/src/components/monitor/ZhihuSearchModule.vue`：

```vue
<script setup lang="ts">
/**
 * 知乎搜索排名监控模块 —— 拉 zhihu_search 任务、跑、展示最新结果的前 10
 * 命中情况。数据形状对齐 csm_core/monitor/platforms/zhihu_search.py 的 metric。
 */
import { ref, onMounted, onUnmounted, computed } from "vue";
import { useSidecar } from "@/stores/sidecar";
import { subscribe } from "@/api/client";
import { useToast } from "@/composables/useToast";
import AddTaskModal from "./AddTaskModal.vue";

interface ResultItem {
  rank: number;
  title: string;
  content_type: string;
  url: string;
  voteup_count: number;
  author_name: string;
  matches_brand: boolean;
  matched_brand: string | null;
  matched_field: string | null;
  excerpt: string;
}
interface KeywordResult {
  keyword: string;
  results: ResultItem[];
  matched_count: number;
  first_rank: number;
  result_count: number;
  empty_reason: string | null;
  api_code: number | null;
  fetch_error: string | null;
}
interface Task {
  id: number;
  type: string;
  name: string;
  target_url: string;
  enabled: boolean;
  schedule_cron: string;
  last_check_at: string | null;
  last_status: string | null;
  config?: Record<string, any>;
}

const sidecar = useSidecar();
const toast = useToast();

const tasks = ref<Task[]>([]);
const selectedId = ref<number | null>(null);
const latestMetric = ref<Record<string, any> | null>(null);
const latestStatus = ref<string | null>(null);
const running = ref<Set<number>>(new Set());
const showModal = ref(false);
const editingTask = ref<Task | null>(null);

const selected = computed(() => tasks.value.find((t) => t.id === selectedId.value) || null);
const keywordResults = computed<KeywordResult[]>(() => latestMetric.value?.keywords ?? []);

async function loadTasks() {
  // GET /api/monitor/tasks → { count, tasks: [...] }（已核对 routes/monitor.py:41-48）
  const r = await sidecar.client.get("/api/monitor/tasks", { params: { type: "zhihu_search" } });
  tasks.value = r.data.tasks ?? [];
  if (selectedId.value === null && tasks.value.length) {
    selectTask(tasks.value[0].id);
  }
}

async function loadLatest(taskId: number) {
  // GET /api/monitor/results → { task_id, count, results: [...] }，行含 .metric / .status
  // （已核对 routes/monitor.py:175-183 + services/monitor_service.py:result_to_dict）
  const r = await sidecar.client.get("/api/monitor/results", { params: { task_id: taskId, limit: 1 } });
  const rows = r.data.results ?? [];
  if (rows.length) {
    latestMetric.value = rows[0].metric ?? null;
    latestStatus.value = rows[0].status ?? null;
  } else {
    latestMetric.value = null;
    latestStatus.value = null;
  }
}

async function selectTask(id: number) {
  selectedId.value = id;
  await loadLatest(id);
}

async function runNow(id: number) {
  running.value = new Set(running.value).add(id);
  try {
    await sidecar.client.post(`/api/monitor/tasks/${id}/run-now`, {});
  } catch (e: any) {
    toast.error(`触发失败：${e?.response?.data?.detail ?? e?.message ?? e}`);
    const s = new Set(running.value); s.delete(id); running.value = s;
  }
}

async function removeTask(id: number) {
  if (!confirm("确认删除这个知乎搜索监控任务？")) return;
  await sidecar.client.delete(`/api/monitor/tasks/${id}`);
  if (selectedId.value === id) { selectedId.value = null; latestMetric.value = null; }
  await loadTasks();
}

function openAdd() { editingTask.value = null; showModal.value = true; }
function openEdit(t: Task) { editingTask.value = t; showModal.value = true; }

async function onTaskSaved() {
  showModal.value = false;
  await loadTasks();
  if (selectedId.value !== null) await loadLatest(selectedId.value);
}

let stopSSE: (() => void) | null = null;
onMounted(async () => {
  await loadTasks();
  stopSSE = subscribe("/api/monitor/events", {
    finished: async (d: any) => {
      const s = new Set(running.value); s.delete(d?.task_id); running.value = s;
      await loadTasks();
      if (d?.task_id === selectedId.value) await loadLatest(selectedId.value);
    },
    failed: async (d: any) => {
      const s = new Set(running.value); s.delete(d?.task_id); running.value = s;
      await loadTasks();
    },
  });
});
onUnmounted(() => { if (stopSSE) stopSSE(); });
</script>

<template>
  <div class="flex gap-4">
    <!-- 左：任务列表 -->
    <div class="w-[240px] shrink-0 flex flex-col gap-2">
      <button class="text-[12.5px] px-3 py-2 rounded bg-[var(--ink)] text-white" @click="openAdd">
        + 新增知乎搜索监控
      </button>
      <div
        v-for="t in tasks" :key="t.id"
        class="px-3 py-2 rounded cursor-pointer text-[12.5px] border"
        :style="{
          background: t.id === selectedId ? 'var(--card-2)' : 'transparent',
          borderColor: 'var(--line)',
        }"
        @click="selectTask(t.id)"
      >
        <div class="font-medium truncate">{{ t.name }}</div>
        <div class="text-[11px] text-[var(--ink-3)]">
          {{ t.last_status ?? "未运行" }} · {{ t.schedule_cron }}
        </div>
      </div>
      <div v-if="!tasks.length" class="text-[12px] text-[var(--ink-3)] px-1">
        还没有知乎搜索监控任务。
      </div>
    </div>

    <!-- 右：详情 -->
    <div class="flex-1 min-w-0">
      <div v-if="!selected" class="text-[13px] text-[var(--ink-3)] p-6">
        从左侧选择或新建一个任务。
      </div>
      <div v-else class="flex flex-col gap-3">
        <div class="flex items-center gap-2">
          <div class="text-[14px] font-medium">{{ selected.name }}</div>
          <a :href="selected.target_url" target="_blank" class="text-[11.5px] text-[var(--primary-deep)] hover:underline">知乎搜索页 ↗</a>
          <div class="ml-auto flex gap-2">
            <button class="text-[12px] px-2 py-1 rounded bg-[var(--card-2)]" :disabled="running.has(selected.id)" @click="runNow(selected.id)">
              {{ running.has(selected.id) ? "运行中…" : "立即执行" }}
            </button>
            <button class="text-[12px] px-2 py-1 rounded bg-[var(--card-2)]" @click="openEdit(selected)">编辑</button>
            <button class="text-[12px] px-2 py-1 rounded bg-[var(--card-2)]" @click="removeTask(selected.id)">删除</button>
          </div>
        </div>

        <div v-if="latestStatus === 'error'" class="text-[12px] text-red-600">
          鉴权失败：检查设置页的知乎 Access Secret，或系统时钟是否准确。
        </div>
        <div v-if="latestStatus === 'risk_control'" class="text-[12px] text-amber-600">
          被知乎频率/配额限制（30001），稍后重试。
        </div>
        <div v-if="!latestMetric" class="text-[12px] text-[var(--ink-3)]">还没有结果，点「立即执行」。</div>

        <!-- 每个关键词一张卡 -->
        <div v-for="kw in keywordResults" :key="kw.keyword" class="border rounded p-3" :style="{ borderColor: 'var(--line)' }">
          <div class="flex items-center gap-2 mb-2">
            <span class="text-[13px] font-medium">{{ kw.keyword }}</span>
            <span v-if="kw.first_rank > 0" class="text-[11px] px-1.5 py-0.5 rounded bg-green-100 text-green-700">
              首位命中 #{{ kw.first_rank }} · 共 {{ kw.matched_count }} 条
            </span>
            <span v-else class="text-[11px] px-1.5 py-0.5 rounded bg-[var(--card-2)] text-[var(--ink-3)]">前 10 无命中</span>
            <span v-if="kw.fetch_error" class="text-[11px] text-red-600">{{ kw.fetch_error }}</span>
            <span v-else-if="kw.empty_reason" class="text-[11px] text-[var(--ink-3)]">知乎无结果：{{ kw.empty_reason }}</span>
          </div>
          <table class="w-full text-[12px]">
            <thead class="text-[var(--ink-3)]">
              <tr><th class="text-left w-8">#</th><th class="text-left">标题</th><th class="text-left w-16">类型</th><th class="text-left w-20">作者</th><th class="text-right w-14">赞同</th></tr>
            </thead>
            <tbody>
              <tr
                v-for="r in kw.results" :key="r.rank"
                :style="{ background: r.matches_brand ? 'rgba(34,197,94,0.08)' : 'transparent' }"
              >
                <td>{{ r.rank }}</td>
                <td class="truncate max-w-[320px]">
                  <a :href="r.url" target="_blank" class="hover:underline">{{ r.title }}</a>
                  <span v-if="r.matches_brand" class="ml-1 text-[10px] px-1 rounded bg-green-200 text-green-800">命中:{{ r.matched_brand }}({{ r.matched_field }})</span>
                </td>
                <td>{{ r.content_type }}</td>
                <td class="truncate max-w-[80px]">{{ r.author_name }}</td>
                <td class="text-right">{{ r.voteup_count }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <AddTaskModal
      v-model:open="showModal"
      :default-type="'zhihu_search' as any"
      :editing-task="editingTask as any"
      @created="onTaskSaved"
      @updated="onTaskSaved"
    />
  </div>
</template>
```

- [ ] **Step 2: Typecheck**

Run: `cd frontend && npm run build`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/monitor/ZhihuSearchModule.vue
git commit -m "feat(monitor-ui): ZhihuSearchModule results panel"
```

---

## Task 9: MonitorView 加「知乎搜索」Tab

**Files:**
- Modify: `frontend/src/views/MonitorView.vue`

- [ ] **Step 1: Import the module + extend Tab type**

`MonitorView.vue` script 顶部 import 区加：

```ts
import ZhihuSearchModule from "@/components/monitor/ZhihuSearchModule.vue";
```

`Tab` 类型（约 line 70）改成：

```ts
type Tab = "zhihu" | "zhihu_search" | "comment" | "baidu" | "geo";
```

`tabFromQuery()`（约 line 72-77）放行新值：

```ts
function tabFromQuery(): Tab {
  const q = route.query.tab;
  if (q === "zhihu" || q === "zhihu_search" || q === "comment" || q === "baidu" || q === "geo") return q;
  return "zhihu";
}
```

`currentTaskType`（约 line 99-102）加分支：

```ts
  if (activeTab.value === "zhihu") return "zhihu_question";
  if (activeTab.value === "zhihu_search") return "zhihu_search";
  if (activeTab.value === "baidu") return "baidu_keyword";
  return PLATFORM_TYPE[commentSubtab.value];
```

- [ ] **Step 2: Add the tab pill + mount the module in template**

Read 模板里现有 tab 胶囊（搜 `activeTab = 'zhihu'` 或 `geo` 的按钮）与模块挂载（搜 `<GeoTaskModule` / `<ZhihuMonitorModule`），照同款加：

胶囊（在「知乎」按钮之后）：

```html
<button
  class="..."
  :style="{ /* 复制相邻胶囊的高亮 style 表达式，把判断改成 activeTab === 'zhihu_search' */ }"
  @click="activeTab = 'zhihu_search'"
>知乎搜索</button>
```

模块挂载（与 GeoTaskModule 同级）：

```html
<ZhihuSearchModule v-else-if="activeTab === 'zhihu_search'" />
```

> 注意 v-if/v-else-if 链：把这一行放进现有的 `<ZhihuMonitorModule v-if=… /> … <GeoTaskModule v-else-if=… />` 链里，保持只挂载一个。

- [ ] **Step 3: Typecheck + run**

Run: `cd frontend && npm run build`
Expected: PASS

手动：`npm run tauri:dev`，监测中心应出现「知乎搜索」Tab，点进去能开新增弹窗。

- [ ] **Step 4: Commit**

```bash
git add frontend/src/views/MonitorView.vue
git commit -m "feat(monitor-ui): zhihu_search tab in MonitorView"
```

---

## Task 10: SettingsView 加知乎 Access Secret 区块

**Files:**
- Modify: `frontend/src/views/SettingsView.vue`

> 不放进 LLM `PROVIDERS` 数组（那带 model/baseURL/test）。用独立的最小 keyring 区块，只做保存 + 已配置状态，**无测试按钮**。

- [ ] **Step 1: Add state + handlers in `<script setup>`**

在 provider 相关 helpers 附近（如 `saveProviderKey` 之后）加：

```ts
// ── 知乎开放平台 Access Secret（非 LLM，独立于 PROVIDERS）─────────
const zhihuSecretDraft = ref("");
const zhihuHasKey = ref(false);

async function refreshZhihuKey() {
  try {
    const s = await keyringStatus("zhihu");
    zhihuHasKey.value = Boolean(s.has_key);
    zhihuSecretDraft.value = zhihuHasKey.value ? API_KEY_MASK : "";
  } catch {
    zhihuHasKey.value = false;
  }
}
function onZhihuFocus() { if (zhihuSecretDraft.value === API_KEY_MASK) zhihuSecretDraft.value = ""; }
function onZhihuBlur() { if (!zhihuSecretDraft.value.trim() && zhihuHasKey.value) zhihuSecretDraft.value = API_KEY_MASK; }
async function saveZhihuSecret() {
  const raw = zhihuSecretDraft.value.trim();
  if (!raw || raw === API_KEY_MASK) { toast.warn("请先粘贴知乎 Access Secret"); return; }
  try {
    await keyringSet("zhihu", raw);
    zhihuHasKey.value = true;
    zhihuSecretDraft.value = API_KEY_MASK;
    toast.success("知乎 Access Secret 已保存");
  } catch (e: any) {
    toast.error(`保存失败：${e?.message ?? e}`);
  }
}
```

在已有的 `onMounted` / `refreshKeyringStatus()` 调用旁补一次 `refreshZhihuKey()`（搜组件挂载时调 `refreshKeyringStatus`，在其后加 `refreshZhihuKey();`）。

- [ ] **Step 2: Add the settings card in `<template>`**

在 LLM providers 卡片之后插入一个小卡（class 沿用相邻 section 的容器样式）：

```html
<section class="...同级 section 容器 class...">
  <div class="text-[13px] font-medium mb-1">知乎开放平台</div>
  <div class="text-[12px] text-[var(--ink-3)] mb-2">
    监测中心「知乎搜索排名」用的官方 API 凭证。到
    <a href="https://developer.zhihu.com/" target="_blank" class="text-[var(--primary-deep)] hover:underline">知乎数据开放平台</a>
    个人中心获取 Access Secret。
  </div>
  <div class="flex items-center gap-2">
    <input
      v-model="zhihuSecretDraft"
      type="password"
      placeholder="粘贴 Access Secret"
      class="flex-1 px-2 py-1 text-[12.5px] rounded border"
      :style="{ borderColor: 'var(--line)', background: 'var(--card-2)' }"
      @focus="onZhihuFocus"
      @blur="onZhihuBlur"
    />
    <span class="text-[11px]" :style="{ color: zhihuHasKey ? 'var(--ok, #16a34a)' : 'var(--ink-3)' }">
      {{ zhihuHasKey ? "已配置" : "未配置" }}
    </span>
    <button class="text-[12px] px-3 py-1 rounded bg-[var(--ink)] text-white" @click="saveZhihuSecret">保存</button>
  </div>
</section>
```

确认 `keyringSet` / `keyringStatus` 已在文件顶部 import（LLM provider 已用，应已 import；若无则补 `import { keyringSet, keyringStatus } from "@/api/client";`）。

- [ ] **Step 3: Typecheck**

Run: `cd frontend && npm run build`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add frontend/src/views/SettingsView.vue
git commit -m "feat(settings): zhihu Access Secret keyring field"
```

---

## Task 11: 端到端验收（手动）

**Files:** 无（手动验证）

- [ ] **Step 1: Build + run**

```bash
cd frontend && npm run build && cd .. && npm run tauri:dev
```

- [ ] **Step 2: 走查清单**

- [ ] 设置页填知乎 Access Secret → 保存 → 状态变「已配置」
- [ ] 监测中心「知乎搜索」Tab → 新增任务（2 个关键词 + 一个品牌词）→ 保存
- [ ] 选中任务 → 立即执行 → 出现每关键词前 10 列表，命中行高亮 + rank 徽章
- [ ] 不填 Access Secret 时执行 → 详情区提示「鉴权失败 / 请配置」
- [ ] 改调度为「每天 09:00」→ 列表显示调度

- [ ] **Step 3: Commit any fixups, then open PR**

```bash
git add -A && git commit -m "fix(monitor-ui): zhihu_search e2e polish"  # 若有
```

> **PR #2 收尾：** push + `gh pr create`，标题「feat(monitor): 知乎搜索排名监控前端」。

---

# PR #3 —（可选）全文级匹配

> 用户：「先这样做，可行再加全文匹配」。PR #1/#2 上线后再评估是否做。默认关，opt-in，best-effort。详见 spec §5.4。

## Task 12: `zhihu_content.fetch_text` 共享 helper

**Files:**
- Create: `csm_core/monitor/platforms/zhihu_content.py`
- Test: `tests/core/monitor/test_zhihu_content.py`

- [ ] **Step 1: Write the failing test**

创建 `tests/core/monitor/test_zhihu_content.py`：

```python
from __future__ import annotations
from csm_core.monitor.platforms import zhihu_content as zc


class _FakeResp:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
    def json(self):
        return self._payload


def test_fetch_text_article_strips_tags(monkeypatch):
    monkeypatch.setattr(zc, "_cc_get", lambda url, **k: _FakeResp(200, {"content": "<p>戴森 V12 实测</p>"}))
    txt = zc.fetch_text("Article", "111", cookie_store=None)
    assert "戴森 V12 实测" in txt
    assert "<p>" not in txt


def test_fetch_text_unsupported_type_returns_none():
    assert zc.fetch_text("Question", "1", cookie_store=None) is None


def test_fetch_text_http_error_returns_none(monkeypatch):
    monkeypatch.setattr(zc, "_cc_get", lambda url, **k: _FakeResp(403, {}))
    assert zc.fetch_text("Answer", "9", cookie_store=None) is None
```

- [ ] **Step 2: Run to verify fail**

Run: `python -m pytest tests/core/monitor/test_zhihu_content.py -v`
Expected: FAIL — module missing

- [ ] **Step 3: Implement**

创建 `csm_core/monitor/platforms/zhihu_content.py`：

```python
"""可选全文匹配用的知乎正文抓取 helper（best-effort）。

只支持 Article / Answer（其它类型返回 None 回退摘要）。curl_cffi
impersonate chrome120 + 复用 zhihu_question 的 Cookie 池。任意失败 → None。
"""
from __future__ import annotations
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

_ENDPOINTS = {
    "Article": "https://www.zhihu.com/api/v4/articles/{cid}?include=content",
    "Answer": "https://www.zhihu.com/api/v4/answers/{cid}?include=content",
}


def _cc_get(url: str, **kwargs: Any) -> Any:
    """curl_cffi GET（indirection 便于单测 monkeypatch）。"""
    from curl_cffi import requests as cc_requests
    return cc_requests.get(url, impersonate="chrome120", timeout=15, **kwargs)


def _strip_tags(html: str) -> str:
    return re.sub(r"<[^>]+>", "", html or "").strip()


def fetch_text(content_type: str, content_id: str, *, cookie_store: Any = None) -> str | None:
    """抓一条知乎内容正文纯文本。失败 / 不支持的类型 → None。"""
    tmpl = _ENDPOINTS.get(content_type)
    if not tmpl or not content_id:
        return None
    cookies = {}
    if cookie_store is not None:
        cred = cookie_store.pick()
        if cred and cred.cookies_text:
            for piece in cred.cookies_text.split(";"):
                if "=" in piece:
                    k, _, v = piece.partition("=")
                    cookies[k.strip()] = v.strip()
    try:
        resp = _cc_get(tmpl.format(cid=content_id), cookies=cookies)
    except Exception as e:
        logger.info("zhihu_content fetch raised: %s", e)
        return None
    if resp.status_code != 200:
        return None
    try:
        content = (resp.json() or {}).get("content") or ""
    except Exception:
        return None
    text = _strip_tags(content)
    return text or None
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/core/monitor/test_zhihu_content.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add csm_core/monitor/platforms/zhihu_content.py tests/core/monitor/test_zhihu_content.py
git commit -m "feat(monitor): zhihu_content best-effort fulltext fetch helper"
```

---

## Task 13: adapter 接入 `match_full_text` + 前端开关

**Files:**
- Modify: `csm_core/monitor/platforms/zhihu_search.py`
- Modify: `frontend/src/components/monitor/AddTaskModal.vue`
- Modify: `frontend/src/components/monitor/ZhihuSearchModule.vue`
- Test: `tests/core/monitor/test_zhihu_search.py`

- [ ] **Step 1: Write the failing tests**

追加到 `tests/core/monitor/test_zhihu_search.py`：

```python
def test_fulltext_match_when_excerpt_misses(monkeypatch):
    _patch_secret(monkeypatch)
    # 标题/摘要/作者都不含品牌，但正文含
    monkeypatch.setattr(zs, "zhihu_search_api", lambda *a, **k: {
        "ok": True, "code": 0, "items": [_item(title="无关标题", text="无关摘要", author="路人")],
        "empty_reason": None, "search_hash_id": "h", "message": "", "http_status": 200, "error": None})
    monkeypatch.setattr(zs, "_fulltext_fetch", lambda ct, cid: "正文里有 戴森 V12")
    r = zs.ADAPTER.fetch(_task(search_keywords=["a"], target_brand="戴森", match_full_text=True))
    res0 = r.metric["keywords"][0]["results"][0]
    assert res0["matches_brand"] is True
    assert res0["matched_field"] == "fulltext"
    assert res0["fulltext_status"] == "matched"


def test_fulltext_disabled_never_fetches(monkeypatch):
    _patch_secret(monkeypatch)
    monkeypatch.setattr(zs, "zhihu_search_api", lambda *a, **k: {
        "ok": True, "code": 0, "items": [_item(title="无关")],
        "empty_reason": None, "search_hash_id": "h", "message": "", "http_status": 200, "error": None})
    def boom(ct, cid):
        raise AssertionError("must not fetch when disabled")
    monkeypatch.setattr(zs, "_fulltext_fetch", boom)
    r = zs.ADAPTER.fetch(_task(search_keywords=["a"], target_brand="戴森", match_full_text=False))
    assert r.metric["keywords"][0]["results"][0]["fulltext_status"] == "disabled"
```

- [ ] **Step 2: Run to verify fail**

Run: `python -m pytest tests/core/monitor/test_zhihu_search.py -k fulltext -v`
Expected: FAIL

- [ ] **Step 3: Wire full-text into the adapter**

在 `zhihu_search.py` 顶部 import 后加一个惰性包装（开关关闭时不 import zhihu_content、不碰 cookie）：

```python
def _fulltext_fetch(content_type: str, content_id: str) -> str | None:
    """惰性调用 zhihu_content（仅 match_full_text=True 时走到）。"""
    from .zhihu_content import fetch_text
    from ..drivers.cookie_store import CookieStore
    return fetch_text(content_type, content_id, cookie_store=CookieStore("zhihu_question"))
```

把 `_rank_results` 改为支持全文回查：新增参数 `match_full_text=False`，每条 item 在标题/摘要/作者未命中时回查全文。改写 `_rank_results`：

```python
    @classmethod
    def _rank_results(
        cls, items, brands, count, *, match_full_text: bool = False,
    ):
        snapshot = []
        matched_ranks = []
        for i, raw in enumerate(items[:count], start=1):
            matched_brand, matched_field = cls._match_item(raw, brands)
            fulltext_status = "disabled" if not match_full_text else "skipped"
            if matched_brand is None and match_full_text:
                ctype = str(raw.get("ContentType") or "")
                cid = str(raw.get("ContentID") or "")
                try:
                    text = _fulltext_fetch(ctype, cid)
                except Exception:
                    text = None
                if text is None:
                    fulltext_status = "fetch_failed"
                else:
                    hit = match_brand(text, brands)
                    if hit:
                        matched_brand, matched_field = hit, "fulltext"
                        fulltext_status = "matched"
                    else:
                        fulltext_status = "fetched_no_match"
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
                "fulltext_status": fulltext_status,
                "excerpt": str(raw.get("ContentText") or "")[:160],
            })
        first_rank = matched_ranks[0] if matched_ranks else -1
        return first_rank, len(matched_ranks), snapshot
```

在 `fetch()` 里读开关并传入（`count = ...` 行附近加 `match_full_text = bool(cfg.get("match_full_text"))`；调用处 `self._rank_results(resp["items"], brands, count, match_full_text=match_full_text)`）。

> 既有非全文测试仍应通过：`match_full_text` 默认 False，`fulltext_status="disabled"`，`_match_item` 行为不变。`test_rank_results_*` 的断言不查 `fulltext_status`，不受影响。

- [ ] **Step 4: Run backend tests**

Run: `python -m pytest tests/core/monitor/test_zhihu_search.py -v`
Expected: PASS（含 fulltext 两项 + 既有全绿）

- [ ] **Step 5: Frontend toggle**

`AddTaskModal.vue`：加 `const zsMatchFullText = ref(false);`，`close()` 重置 `zsMatchFullText.value = false;`，`hydrateFromTask` 加 `zsMatchFullText.value = Boolean(cfg.match_full_text);`，submit 的 zhihu_search config 加 `match_full_text: zsMatchFullText.value,`，模板知乎搜索块末尾加：

```html
            <FormField label="全文级匹配" hint="开启后对前 10 结果逐条抓正文再匹配（更全但更慢，需在 Cookie 管理配置知乎 Cookie）" inline>
              <FormToggle v-model="zsMatchFullText" />
            </FormField>
```

`ZhihuSearchModule.vue` 的 `ResultItem` 接口加 `fulltext_status?: string;`，命中徽章在 `matched_field === 'fulltext'` 时显示「(正文)」。

- [ ] **Step 6: Typecheck + commit**

Run: `cd frontend && npm run build`
Expected: PASS

```bash
git add csm_core/monitor/platforms/zhihu_search.py tests/core/monitor/test_zhihu_search.py frontend/src/components/monitor/AddTaskModal.vue frontend/src/components/monitor/ZhihuSearchModule.vue
git commit -m "feat(monitor): optional zhihu_search full-text matching (opt-in)"
```

> **PR #3 收尾：** push + `gh pr create`，标题「feat(monitor): 知乎搜索可选全文匹配」。

---

## Self-Review Notes（plan 作者自查）

**Spec coverage:**
- §1/§2 品牌词命中语义 → Task 3/4 ✓
- §3 API 字段 → Task 2（解析）+ Task 3（snapshot 字段）✓
- §4.1 后端 3 处 → Task 1（base）+ Task 4（adapter+注册）✓
- §5.2 config（search_keywords/target_brand/brand_aliases/count）→ Task 4 + Task 7 ✓
- §5.3 metric + rank 语义 → Task 4 ✓
- §6 Access Secret keyring → Task 10 ✓
- §7 前端表单/模块/Tab → Task 7/8/9 ✓
- §5.4 全文匹配 → Task 12/13 ✓
- 30001/20001 处理 → Task 4 tests ✓

**Type consistency:** `zhihu_search_api` 返回的 dict 键（ok/code/items/empty_reason/search_hash_id/http_status/error）在 Task 2 定义、Task 4 fetch 消费一致；`_rank_results` 返回 (first_rank, matched_count, snapshot) 三元组在 Task 3 定义、Task 4 调用一致；snapshot item 键与 ZhihuSearchModule 的 `ResultItem` 接口一致（rank/title/content_type/url/voteup_count/author_name/matches_brand/matched_brand/matched_field/excerpt）。

**已核对的契约（无需再查）：**
- `GET /api/monitor/tasks` → `{count, tasks:[...]}`；`GET /api/monitor/results` → `{task_id, count, results:[...]}`，行含 `.metric` / `.status`（`routes/monitor.py` + `monitor_service.result_to_dict`）。Task 8 已按此写。
- SSE `/api/monitor/events` 的 `event:` 名 = MonitorEvent.kind（`started/finished/failed/progress/...`）；Task 8 的 `finished`/`failed` handler 正确（`routes/monitor.py:342-354`）。
- `POST /api/monitor/tasks/{id}/run-now` 返回 `{task_id, queued, keyword}`；`POST /api/monitor/tasks` 返回创建后的 task dict（含 `id`，AddTaskModal 已用 `r.data.id`）。

**Known follow-ups（执行时照搬 sibling，非阻塞）：**
- Task 9 的 tab 胶囊 inline `:style` 高亮表达式照搬相邻胶囊（MonitorView 用 inline :style）——执行者 Read 后对齐。
- Task 10 的 `<section>` 容器 class 照搬相邻 settings section。
