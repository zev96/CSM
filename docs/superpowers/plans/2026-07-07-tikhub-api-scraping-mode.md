# TikHub 付费 API 抓取模式 —— 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: 用 superpowers:subagent-driven-development(推荐)或 superpowers:executing-plans 逐任务执行。步骤用 `- [ ]` 复选框跟踪。

**Goal:** 在监测模块加一个全局开关,把知乎问题 + 抖音/B站/快手评论的抓取从本地浏览器切换到 TikHub 付费 API,不动现有本地适配器、零回归。

**Architecture:** 旁路 API 适配器 + 模式感知分派。新增 `csm_core/monitor/tikhub/` 包(HTTP client + normalizer + 适配器);`API_ADAPTERS` 并行注册表;`monitor_loop._run_one` 按 `data_source_mode` 选适配器。取数后复用现有 `build_match_result`(评论)与 `_rank_brand`(知乎)做匹配。

**Tech Stack:** Python(pydantic、curl_cffi/httpx 已在用)、FastAPI(config 路由)、Vue3(SettingsView)、keyring、pytest、PyInstaller。

**设计文档:** `docs/superpowers/specs/2026-07-06-tikhub-api-scraping-mode-design.md`(权威;本计划实现它)。

---

## 测试环境前言(每个后端任务都适用)

- **worktree 跑测试**:主仓 `D:/CSM` checkout 在别的分支,editable 装的 csm_core/csm_sidecar 指向主仓。要测**本 worktree** 代码,必须覆盖 PYTHONPATH:
  ```powershell
  $env:PYTHONPATH="D:\CSM\.claude\worktrees\objective-moore-ecce71;D:\CSM\.claude\worktrees\objective-moore-ecce71\sidecar"
  ```
- **sidecar 测试不进默认 CI**(root `testpaths=["tests"]` 只收 root `tests/`)。新测试放 `sidecar/tests/tikhub/`,**必须显式**跑:
  ```powershell
  python -m pytest sidecar/tests/tikhub/ -v
  ```
  执行前先 `grep -r "def test_" sidecar/tests | head` 确认现有 monitor 测试约定,新测试与之co-locate。
- **不 mock 真实 HTTP 打 TikHub**(会计费)。所有 client 测试用 mock transport;真实响应只在 Phase 0 探针里抓一次落 fixture。

---

## 文件结构

**新建:**
- `csm_core/monitor/tikhub/__init__.py` — 导出 `API_ADAPTERS`
- `csm_core/monitor/tikhub/client.py` — `TikHubClient`:鉴权/BaseURL/单次 GET/错误映射/日志 redact/进程级 402 余额闩/`paginate()`
- `csm_core/monitor/tikhub/errors.py` — `TikHubError`、`TikHubBalanceExhausted`、错误码→中文
- `csm_core/monitor/tikhub/normalize.py` — `normalize_zhihu_answers`、`normalize_douyin/kuaishou/bilibili_comments`
- `csm_core/monitor/tikhub/zhihu_adapter.py` — `ZhihuQuestionApiAdapter`
- `csm_core/monitor/tikhub/comment_adapter.py` — 通用 `CommentApiAdapter` + 3 个 `PlatformSpec`
- `sidecar/scripts/tikhub_probe.py` — Phase 0 探针
- `sidecar/tests/tikhub/` — 全部单测 + fixtures

**修改:**
- `csm_core/config.py` — `MonitorConfig` 新增字段
- `csm_core/monitor/platforms/__init__.py` — 导出 `API_ADAPTERS`(从 tikhub 包)
- `sidecar/csm_sidecar/services/monitor_loop.py` — `_run_one` 分派 + mode 持有 + API 模式跳过 `slot()` + 402 闩短路
- `sidecar/csm_sidecar/services/monitor_lifecycle.py` — `reconfigure()` 注入 mode + API 模式不推本地 pacing
- `frontend/src/views/SettingsView.vue` — 监测 section「抓取数据源」
- `csm-sidecar.spec` / `sidecar/pyproject.toml` / `build_sidecar.py` — keyring 加固

---

## Phase 0 — 探针与 fixtures(先钉死字段路径,de-risk)

### Task 0.1:TikHub 探针脚本

**Files:** Create `sidecar/scripts/tikhub_probe.py`

- [ ] **Step 1: 写探针脚本**(读 env `TIKHUB_API_KEY`,打 4 端点,存 raw JSON)

```python
"""一次性探针:抓 TikHub 真实响应落 fixture,供 normalizer 测试用。
用法(用户本机):  set TIKHUB_API_KEY=xxx  &&  python sidecar/scripts/tikhub_probe.py \
    --douyin <抖音视频URL或aweme_id> --kuaishou <...> --bilibili <BV...> --zhihu <question_id>
不计入自动化,手动跑。每端点 1 次 = $0.001。"""
import os, sys, json, argparse, pathlib
import httpx

BASE = os.environ.get("TIKHUB_BASE_URL", "https://api.tikhub.dev")
KEY = os.environ.get("TIKHUB_API_KEY")
OUT = pathlib.Path(__file__).resolve().parents[1] / "tests" / "tikhub" / "fixtures"

def _get(path, params):
    r = httpx.get(f"{BASE}{path}", params=params,
                  headers={"Authorization": f"Bearer {KEY}"}, timeout=30)
    print(f"[{r.status_code}] {path} -> {len(r.content)} bytes")
    r.raise_for_status()
    return r.json()

def main():
    if not KEY:
        sys.exit("set TIKHUB_API_KEY first")
    ap = argparse.ArgumentParser()
    for p in ("douyin", "kuaishou", "bilibili", "zhihu"):
        ap.add_argument(f"--{p}")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    jobs = []
    if a.douyin:
        jobs.append(("douyin_comments", "/api/v1/douyin/app/v3/fetch_video_comments",
                     {"aweme_id": a.douyin, "count": 20, "cursor": 0}))
    if a.kuaishou:
        jobs.append(("kuaishou_comments", "/api/v1/kuaishou/app/fetch_video_comment",
                     {"photo_id": a.kuaishou}))
    if a.bilibili:
        jobs.append(("bilibili_comments", "/api/v1/bilibili/app/fetch_video_comments",
                     {"bv_id": a.bilibili, "mode": 3, "next_offset": 1}))
    if a.zhihu:
        jobs.append(("zhihu_answers", "/api/v1/zhihu/web/fetch_question_answers",
                     {"question_id": a.zhihu, "limit": 20}))
    for name, path, params in jobs:
        data = _get(path, params)
        (OUT / f"tikhub_{name}.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  saved fixtures/tikhub_{name}.json")

if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 落知乎 fixture**(已有真实样本)

```bash
mkdir -p sidecar/tests/tikhub/fixtures
cp "C:/Users/EDY/Downloads/response.json" sidecar/tests/tikhub/fixtures/tikhub_zhihu_answers.json
```

- [ ] **Step 3: (用户手动)跑评论探针** —— 用户设 `TIKHUB_API_KEY` + 各给一条视频(抖音/快手/B站,B站选一条**有 UP 置顶评论**的),生成 3 个评论 fixture。**此步产出的 JSON 是 Task 4-5 normalizer 的字段来源。**

- [ ] **Step 4: Commit**

```bash
git add sidecar/scripts/tikhub_probe.py sidecar/tests/tikhub/fixtures/
git commit -m "chore(tikhub): 探针脚本 + 知乎响应 fixture"
```

> 若用户暂时不便跑评论探针:Task 5(评论 normalizer)先按设计 §8.2 候选字段路径写 + 标 `@pytest.mark.skip("待 fixture")`,拿到 fixture 再解除并校正。

---

## Phase 1 — 配置 + TikHub client 基座

### Task 1:MonitorConfig 新增字段

**Files:** Modify `csm_core/config.py`(`MonitorConfig`);Test `sidecar/tests/tikhub/test_config_fields.py`

- [ ] **Step 1: 写失败测试**

```python
from csm_core.config import MonitorConfig

def test_data_source_mode_defaults_local():
    c = MonitorConfig()
    assert c.data_source_mode == "local"
    assert c.tikhub_base_url == "https://api.tikhub.dev"
    assert c.tikhub_video_endpoint == "app"
    assert c.tikhub_zhihu_limit == 20

def test_data_source_mode_accepts_api():
    c = MonitorConfig(data_source_mode="tikhub_api")
    assert c.data_source_mode == "tikhub_api"
```

- [ ] **Step 2: 跑测试确认失败** — `python -m pytest sidecar/tests/tikhub/test_config_fields.py -v` → FAIL(字段不存在)
- [ ] **Step 3: 加字段**(在 `MonitorConfig` 内,紧挨 `browser_engine`)

```python
    data_source_mode: Literal["local", "tikhub_api"] = "local"
    tikhub_base_url: str = "https://api.tikhub.dev"
    tikhub_video_endpoint: Literal["app", "web"] = "app"
    tikhub_zhihu_limit: int = 20
```

- [ ] **Step 4: 跑测试确认通过** — 同上 → PASS
- [ ] **Step 5: Commit** — `git commit -am "feat(config): TikHub 数据源模式字段"`

### Task 2:TikHubClient — 鉴权/GET/错误映射/redact

**Files:** Create `csm_core/monitor/tikhub/errors.py`、`client.py`;Test `sidecar/tests/tikhub/test_client.py`

- [ ] **Step 1: 写失败测试**(用假 transport,不打真网)

```python
import pytest, httpx
from csm_core.monitor.tikhub.client import TikHubClient
from csm_core.monitor.tikhub.errors import TikHubError, TikHubBalanceExhausted

def _client(handler):
    transport = httpx.MockTransport(handler)
    return TikHubClient(base_url="https://api.tikhub.dev", api_key="k",
                        _transport=transport)

def test_get_ok_returns_data():
    c = _client(lambda req: httpx.Response(200, json={"code": 200, "data": {"x": 1}}))
    assert c.get("/p", {}) == {"code": 200, "data": {"x": 1}}

def test_402_raises_balance_exhausted():
    c = _client(lambda req: httpx.Response(402, json={"code": 402, "message": "no balance"}))
    with pytest.raises(TikHubBalanceExhausted):
        c.get("/p", {})

def test_429_maps_to_chinese_reason():
    c = _client(lambda req: httpx.Response(429, json={"code": 429}))
    with pytest.raises(TikHubError) as e:
        c.get("/p", {})
    assert "限流" in str(e.value.reason)

def test_auth_header_present():
    seen = {}
    def h(req):
        seen["auth"] = req.headers.get("authorization")
        return httpx.Response(200, json={"code": 200, "data": {}})
    _client(h).get("/p", {})
    assert seen["auth"] == "Bearer k"
```

- [ ] **Step 2: 跑测试确认失败** — `python -m pytest sidecar/tests/tikhub/test_client.py -v` → FAIL(模块不存在)
- [ ] **Step 3: 实现 errors.py + client.py**

```python
# errors.py
class TikHubError(Exception):
    def __init__(self, reason: str, code: int | None = None):
        self.reason = reason; self.code = code
        super().__init__(reason)

class TikHubBalanceExhausted(TikHubError):
    pass

def map_error(status: int, code: int | None) -> TikHubError:
    if status == 402:
        return TikHubBalanceExhausted("TikHub 余额不足", code)
    if status == 429:
        return TikHubError("TikHub 限流", code)
    if status in (401, 403):
        return TikHubError("TikHub 鉴权失败或 Key 无效", code)
    return TikHubError(f"TikHub API 错误(HTTP {status})", code)
```

```python
# client.py
import logging, threading, httpx
from .errors import TikHubError, TikHubBalanceExhausted, map_error

logger = logging.getLogger(__name__)
_balance_lock = threading.Lock()
_balance_exhausted = False   # 进程级、跨平台 402 闩

def balance_exhausted() -> bool:
    with _balance_lock:
        return _balance_exhausted

def reset_balance_latch() -> None:
    global _balance_exhausted
    with _balance_lock:
        _balance_exhausted = False

def _trip_balance_latch() -> None:
    global _balance_exhausted
    with _balance_lock:
        _balance_exhausted = True

class TikHubClient:
    def __init__(self, base_url: str, api_key: str, *, timeout: float = 30.0,
                 _transport=None):
        self._base = base_url.rstrip("/")
        self._key = api_key
        self._http = httpx.Client(timeout=timeout, transport=_transport)

    def get(self, path: str, params: dict) -> dict:
        # 日志绝不带 Authorization / key
        logger.info("[tikhub] GET %s params=%s", path, {k: v for k, v in params.items()})
        try:
            r = self._http.get(self._base + path, params=params,
                               headers={"Authorization": f"Bearer {self._key}"})
        except httpx.HTTPError as e:
            raise TikHubError("网络错误") from e
        if r.status_code != 200:
            err = map_error(r.status_code, None)
            if isinstance(err, TikHubBalanceExhausted):
                _trip_balance_latch()
            logger.warning("[tikhub] %s http=%d first200=%s", path, r.status_code, r.text[:200])
            raise err
        return r.json()
```

- [ ] **Step 4: 跑测试确认通过** → PASS
- [ ] **Step 5: Commit** — `git add ... && git commit -m "feat(tikhub): client 基座 + 错误映射 + 402 余额闩"`

### Task 3:自适应翻页 `paginate()`

**Files:** Modify `client.py`;Test `sidecar/tests/tikhub/test_paginate.py`

- [ ] **Step 1: 写失败测试**

```python
from csm_core.monitor.tikhub.client import paginate
from csm_core.monitor.tikhub.errors import TikHubError
import pytest

def test_stops_at_target():
    pages = [(["a","b"], "c1", True), (["c","d"], "c2", True), (["e"], None, False)]
    it = iter(pages); calls = []
    def page_fn(cursor): calls.append(cursor); return next(it)
    items = paginate(page_fn, target=3, max_pages=10)
    assert items == ["a","b","c"]        # 达 target=3 即停,不抓第 3 页
    assert len(calls) == 2

def test_stops_when_no_more():
    pages = [(["a"], "c1", True), (["b"], None, False)]
    it = iter(pages)
    items = paginate(lambda c: next(it), target=100, max_pages=10)
    assert items == ["a","b"]            # API 报尽即停,不足 target 也停

def test_page_failure_raises_not_partial():
    def page_fn(cursor):
        if cursor is None: return (["a"], "c1", True)
        raise TikHubError("第2页挂了")
    with pytest.raises(TikHubError):
        paginate(page_fn, target=100, max_pages=10)   # 绝不返残缺 ["a"]

def test_max_pages_fuse_raises():
    def page_fn(cursor): return (["x"], "next", True)   # 永远 has_more
    with pytest.raises(TikHubError):
        paginate(page_fn, target=1000, max_pages=3)
```

- [ ] **Step 2: 跑测试确认失败** → FAIL
- [ ] **Step 3: 实现 paginate**(加到 client.py)

```python
def paginate(page_fn, target: int, max_pages: int, cancel_token=None):
    """page_fn(cursor) -> (items, next_cursor, has_more)。
    正常停:达 target / has_more=False / 空页。
    异常停:page_fn 抛异常(向上传播,绝不返残缺)/ 超 max_pages。"""
    out, cursor, pages = [], None, 0
    while len(out) < target:
        if cancel_token is not None and cancel_token.is_set():
            break
        if pages >= max_pages:
            raise TikHubError(f"翻页超过 {max_pages} 页仍未终止(疑似异常)")
        items, cursor, has_more = page_fn(cursor)   # 抛异常 = 整体失败
        pages += 1
        if not items:
            break
        out.extend(items)
        if not has_more or cursor is None:
            break
    return out[:target]
```

- [ ] **Step 4: 跑测试确认通过** → PASS
- [ ] **Step 5: Commit** — `git commit -am "feat(tikhub): 自适应翻页(页失败=整体失败 + max_pages 硬闸)"`

---

## Phase 2 — Normalizers

### Task 4:知乎 normalizer(拆 feed 信封,已由 fixture 钉死)

**Files:** Create `normalize.py`(`normalize_zhihu_answers`);Test `sidecar/tests/tikhub/test_normalize_zhihu.py`

- [ ] **Step 1: 写失败测试**(用真实 fixture)

```python
import json, pathlib
from csm_core.monitor.tikhub.normalize import normalize_zhihu_answers

FIX = pathlib.Path(__file__).parent / "fixtures" / "tikhub_zhihu_answers.json"

def test_unwraps_20_answers_with_content():
    raw = json.loads(FIX.read_text(encoding="utf-8"))
    answers = normalize_zhihu_answers(raw)
    assert len(answers) == 20
    assert all(a["rank"] == i + 1 for i, a in enumerate(answers))   # 连续编号
    assert all(a["content"] and len(a["content"]) > 0 for a in answers)   # 正文非空
    assert answers[0]["author"] == "你的益达"
    assert answers[0]["voteup_count"] == 112

def test_filters_non_answer_cards():
    raw = {"data": {"data": [
        {"type": "question_feed_card", "target_type": "answer",
         "target": {"content": "<p>hi</p>", "author": {"name": "u"}, "voteup_count": 5}},
        {"type": "feed_ad", "target_type": "ad", "target": {}},   # 广告卡必须被过滤
    ]}}
    answers = normalize_zhihu_answers(raw)
    assert len(answers) == 1 and answers[0]["rank"] == 1
```

- [ ] **Step 2: 跑测试确认失败** → FAIL
- [ ] **Step 3: 实现**(复用本地 `_strip_tags`,不另写)

```python
# normalize.py
from csm_core.monitor.platforms.zhihu_question import ZhihuQuestionAdapter

_strip = ZhihuQuestionAdapter._strip_tags   # 与本地逐字节一致

def normalize_zhihu_answers(raw: dict) -> list[dict]:
    cards = (raw.get("data") or {}).get("data") or []
    out = []
    for card in cards:
        if card.get("type") != "question_feed_card": continue
        if card.get("target_type") != "answer": continue
        t = card.get("target")
        if not isinstance(t, dict): continue
        out.append({
            "rank": len(out) + 1,                       # 过滤后连续编号
            "author": ((t.get("author") or {}).get("name")),
            "content": t.get("content") or "",          # 原始 HTML;匹配前由调用方 _strip
            "voteup_count": t.get("voteup_count"),
            "comment_count": t.get("comment_count"),
            "url": t.get("url"),
        })
    return out
```

- [ ] **Step 4: 跑测试确认通过** → PASS
- [ ] **Step 5: Commit** — `git commit -am "feat(tikhub): 知乎 feed 信封 normalizer(过滤广告卡+连续编号)"`

### Task 5:评论 normalizer(3 平台 → `{text,author,likes,rank}`)

**Files:** Modify `normalize.py`;Test `sidecar/tests/tikhub/test_normalize_comments.py`

> 字段路径以 Phase 0 探针 fixture 为准。下方按设计 §8.2 候选路径写;拿到 fixture 后**用真实数据校正并断言**。B站必须复刻「置顶(upper.top)→rank1 + 文本去重」。

- [ ] **Step 1: 写失败测试**(抖音示例 + B站置顶/去重)

```python
from csm_core.monitor.tikhub.normalize import (
    normalize_douyin_comments, normalize_bilibili_comments)

def test_douyin_maps_fields_and_ranks():
    raw = {"data": {"comments": [
        {"text": "好用", "user": {"nickname": "A"}, "digg_count": 9},
        {"text": "一般", "user": {"nickname": "B"}, "digg_count": 3},
    ]}}
    out = normalize_douyin_comments(raw)
    assert out == [
        {"rank": 1, "text": "好用", "author": "A", "likes": 9},
        {"rank": 2, "text": "一般", "author": "B", "likes": 3},
    ]

def test_bilibili_pins_top_first_and_dedups():
    raw = {"data": {"upper": {"top": {"content": {"message": "置顶"},
                                      "member": {"uname": "UP"}, "like": 50}},
                    "hots": [
                        {"content": {"message": "置顶"}, "member": {"uname": "UP"}, "like": 50},  # 与置顶重复
                        {"content": {"message": "热评"}, "member": {"uname": "C"}, "like": 8}]}}
    out = normalize_bilibili_comments(raw, first_page=True)
    assert out[0] == {"rank": 1, "text": "置顶", "author": "UP", "likes": 50}
    assert [c["text"] for c in out] == ["置顶", "热评"]   # 去重后置顶只出现一次
```

- [ ] **Step 2: 跑测试确认失败** → FAIL
- [ ] **Step 3: 实现三平台 normalizer**(抖音/快手取 comments 数组按序编号;B站首屏 top→hots→replies + 按 text 去重)

```python
def _rank(items):
    return [{**it, "rank": i + 1} for i, it in enumerate(items)]

def normalize_douyin_comments(raw: dict) -> list[dict]:
    cs = (raw.get("data") or {}).get("comments") or []
    return _rank([{"text": c.get("text") or "",
                   "author": (c.get("user") or {}).get("nickname"),
                   "likes": c.get("digg_count")} for c in cs])

def normalize_kuaishou_comments(raw: dict) -> list[dict]:
    d = raw.get("data") or {}
    cs = d.get("comments") or d.get("rootComments") or []   # 探针后校正键名
    return _rank([{"text": c.get("content") or "",
                   "author": c.get("authorName") or c.get("author_name"),
                   "likes": c.get("likedCount") or c.get("liked_count")} for c in cs])

def normalize_bilibili_comments(raw: dict, first_page: bool = False) -> list[dict]:
    d = raw.get("data") or {}
    rows, seen = [], set()
    def push(node):
        if not node: return
        text = ((node.get("content") or {}).get("message")) or ""
        if text in seen: return
        seen.add(text)
        rows.append({"text": text, "author": (node.get("member") or {}).get("uname"),
                     "likes": node.get("like")})
    if first_page:
        push((d.get("upper") or {}).get("top"))     # 置顶 → 第一
        for h in d.get("hots") or []: push(h)
    for r in d.get("replies") or []: push(r)
    return _rank(rows)
```

- [ ] **Step 4: 跑测试确认通过** → PASS
- [ ] **Step 5: Commit** — `git commit -am "feat(tikhub): 三平台评论 normalizer(B站置顶+去重)"`

---

## Phase 3 — API 适配器

### Task 6:知乎问题 API 适配器

**Files:** Create `zhihu_adapter.py`;Test `sidecar/tests/tikhub/test_zhihu_adapter.py`

- [ ] **Step 1: 写失败测试**(mock client,断言 rank 复用 `_rank_brand`、top_n>20 翻页)

```python
from unittest.mock import MagicMock
from csm_core.monitor.base import MonitorTask
from csm_core.monitor.tikhub.zhihu_adapter import ZhihuQuestionApiAdapter

def _task(top_n=10):
    return MonitorTask(type="zhihu_question", name="t",
                       target_url="https://www.zhihu.com/question/23640683",
                       config={"target_brand": "你的益达", "top_n": top_n})

def test_top_n_le_20_single_page_and_matches(monkeypatch):
    import json, pathlib
    raw = json.loads((pathlib.Path(__file__).parent/"fixtures"/"tikhub_zhihu_answers.json").read_text("utf-8"))
    client = MagicMock(); client.get.return_value = raw
    a = ZhihuQuestionApiAdapter(client_factory=lambda cfg: client)
    r = a.fetch(_task(top_n=10))
    assert r.status == "ok"
    assert r.rank == 1                       # "你的益达" 是第 1 条
    assert client.get.call_count == 1        # top_n≤20 单页
    assert r.metric["source"] == "tikhub"
```

- [ ] **Step 2: 跑测试确认失败** → FAIL
- [ ] **Step 3: 实现**(提取 qid、paginate 到 `min(40, top_n)`、normalize、复用 `_rank_brand`)

```python
import re
from csm_core.monitor.base import MonitorTask, MonitorResult
from csm_core.monitor.platforms.zhihu_question import ZhihuQuestionAdapter
from .normalize import normalize_zhihu_answers
from .client import paginate
from .errors import TikHubError

_QID = re.compile(r"/question/(\d+)")

class ZhihuQuestionApiAdapter:
    platform = "zhihu_question"
    def __init__(self, client_factory): self._cf = client_factory
    def fetch(self, task, cancel_token=None, progress_cb=None, **_) -> MonitorResult:
        m = _QID.search(task.target_url or "")
        if not m:
            return MonitorResult(task_id=task.id, status="failed",
                                 metric={"error": "无法从 URL 解析 question_id"})
        qid = m.group(1)
        brand = (task.config.get("target_brand") or "").strip()
        top_n = max(1, min(40, int(task.config.get("top_n") or 10)))
        client = self._cf(task.config)   # 由分派层注入 base_url/key/limit
        try:
            def page_fn(cursor):
                params = {"question_id": qid, "limit": 20}
                if cursor: params["cursor"] = cursor
                raw = client.get("/api/v1/zhihu/web/fetch_question_answers", params)
                ans = normalize_zhihu_answers(raw)
                nxt = ((raw.get("data") or {}).get("paging") or {})
                has_more = not nxt.get("is_end", True)
                return ans, (nxt.get("next") if has_more else None), has_more
            answers = paginate(page_fn, target=top_n, max_pages=3)
        except TikHubError as e:
            return MonitorResult(task_id=task.id, status="failed", metric={"error": e.reason})
        for i, a in enumerate(answers): a["rank"] = i + 1
        rank = ZhihuQuestionAdapter._rank_brand(answers, brand, top_n)   # 复用,口径一致
        return MonitorResult(task_id=task.id, status="ok", rank=rank,
                             metric={"source": "tikhub", "target_brand": brand,
                                     "answers": answers, "scanned_full": True})
```

> 注:`_rank_brand` 的确切签名以 `zhihu_question.py:597` 为准;若它取 `task.config`(含别名)而非 `target_brand` 串,按其真实签名传参 —— **务必复用它,不要重写匹配逻辑**。

- [ ] **Step 4: 跑测试确认通过** → PASS
- [ ] **Step 5: Commit** — `git commit -am "feat(tikhub): 知乎问题 API 适配器(复用 _rank_brand)"`

### Task 7:通用评论 API 适配器 + 3 平台 spec

**Files:** Create `comment_adapter.py`;Test `sidecar/tests/tikhub/test_comment_adapter.py`

- [ ] **Step 1: 写失败测试**(抖音:扫描 ≤50=最多3页护栏;页失败=整体 failed)

```python
from unittest.mock import MagicMock
from csm_core.monitor.base import MonitorTask
from csm_core.monitor.tikhub.comment_adapter import CommentApiAdapter, DOUYIN_SPEC

def _task():
    return MonitorTask(type="douyin_comment", name="t",
                       target_url="https://www.douyin.com/video/7abcdefg",
                       config={"my_comment_text": "沙发", "top_n": 5})

def test_douyin_scans_at_most_3_pages():
    client = MagicMock()
    # 每页 20 条 has_more=True → 若不设 50 上限会无限翻
    client.get.return_value = {"data": {"comments": [{"text": f"c{i}", "user": {"nickname": "u"},
                              "digg_count": 0} for i in range(20)], "has_more": True, "cursor": 1}}
    a = CommentApiAdapter(DOUYIN_SPEC, client_factory=lambda cfg: client,
                          id_extractor=lambda s, u: ("7abcdefg", ""))
    r = a.fetch(_task())
    assert client.get.call_count <= 3               # 50÷20 → 3 页封顶
    assert r.metric["scanned_full"] is True
```

- [ ] **Step 2: 跑测试确认失败** → FAIL
- [ ] **Step 3: 实现通用适配器 + spec**(复用现有 `_extract_video_id` 与 `build_match_result`)

```python
from dataclasses import dataclass
from typing import Callable
from csm_core.monitor.base import MonitorResult
from csm_core.monitor.platforms._comment_common import build_match_result
from csm_core.monitor.platforms.douyin_comment import DouyinCommentAdapter
from csm_core.monitor.platforms.kuaishou_comment import KuaishouCommentAdapter
from csm_core.monitor.platforms.bilibili_comment import BilibiliCommentAdapter
from . import normalize
from .client import paginate
from .errors import TikHubError

@dataclass
class PlatformSpec:
    platform: str
    endpoint: str
    default_depth: int
    depth_cap: int
    build_params: Callable          # (vid, id_type, cursor) -> dict
    parse_page: Callable            # (raw, first_page) -> (items, next_cursor, has_more)

def _dy_params(vid, id_type, cursor):
    p = {"aweme_id": vid, "count": 20}
    if cursor: p["cursor"] = cursor
    return p
def _dy_page(raw, first):
    d = raw.get("data") or {}
    return (normalize.normalize_douyin_comments(raw),
            d.get("cursor"), bool(d.get("has_more")))

DOUYIN_SPEC = PlatformSpec("douyin_comment", "/api/v1/douyin/app/v3/fetch_video_comments",
                           50, 50, _dy_params, _dy_page)
# KUAISHOU_SPEC / BILIBILI_SPEC 同构:endpoint/params/parse_page 按 §4.1/§8.2 填(B站 parse 传 first_page)

class CommentApiAdapter:
    def __init__(self, spec, client_factory, id_extractor):
        self.spec = spec; self.platform = spec.platform
        self._cf = client_factory; self._extract = id_extractor
    def fetch(self, task, cancel_token=None, progress_cb=None, **_) -> MonitorResult:
        client = self._cf(task.config)
        vid, id_type = self._extract(client_session_or_none(client), task.target_url)
        if not vid:
            return MonitorResult(task_id=task.id, status="failed",
                                 metric={"error": "无法解析视频 ID"})
        depth = min(int(task.config.get("scrape_top_n") or self.spec.default_depth),
                    self.spec.depth_cap)
        first = {"v": True}
        def page_fn(cursor):
            raw = client.get(self.spec.endpoint, self.spec.build_params(vid, id_type, cursor))
            items, nxt, more = self.spec.parse_page(raw, first["v"]); first["v"] = False
            return items, nxt, more
        try:
            comments = paginate(page_fn, target=depth, max_pages=(depth // 20) + 2,
                                cancel_token=cancel_token)
        except TikHubError as e:
            return MonitorResult(task_id=task.id, status="failed", metric={"error": e.reason})
        match = build_match_result(task, comments)   # 复用现有匹配
        return MonitorResult(task_id=task.id, status="ok", rank=match["rank"],
                             metric={**match["metric"], "source": "tikhub", "scanned_full": True})
```

> `id_extractor` 直接传现有静态方法:`DouyinCommentAdapter._extract_video_id` 等(纯 HTTP/正则,含短链)。`client_session_or_none` 提供一个可跟随重定向的 httpx session 给短链展开(可用 client 内部的 `_http`)。B站 spec 用 `bv_id` + `mode=3`,省掉 aid 转换。

- [ ] **Step 4: 跑测试确认通过** → PASS
- [ ] **Step 5: Commit** — `git commit -am "feat(tikhub): 通用评论适配器 + 抖音 spec(深度护栏)"`

### Task 8:补齐快手/B站 spec + 各自适配器测试

**Files:** Modify `comment_adapter.py`;Test 同上文件新增用例

- [ ] **Step 1-2: 写失败测试**:快手 `photo_id`(eID)可用、B站首屏置顶→rank1(用 Task 5 的 fixture/构造)。
- [ ] **Step 3: 填 `KUAISHOU_SPEC`、`BILIBILI_SPEC`**(endpoint/params/parse_page 按 §4.1;快手 pcursor 结束判 `no_more`;B站 `next_offset`+`is_end`,parse 传 first_page 以复刻置顶)。
- [ ] **Step 4: 跑测试确认通过**
- [ ] **Step 5: Commit** — `git commit -am "feat(tikhub): 快手/B站评论 spec"`

---

## Phase 4 — 注册表 + 分派 + 注入 + 限速旁路

### Task 9:API_ADAPTERS 注册 + 分派 + mode 注入

**Files:** Create `tikhub/__init__.py`;Modify `platforms/__init__.py`、`monitor_loop.py`、`monitor_lifecycle.py`;Test `sidecar/tests/tikhub/test_dispatch.py`

- [ ] **Step 1: 写失败测试**(mode=tikhub_api 时 4 类路由 API;baidu 回落本地)

```python
def test_api_mode_routes_to_api_adapter(make_loop):
    loop = make_loop(mode="tikhub_api")
    assert loop._select_adapter("douyin_comment").__class__.__name__ == "CommentApiAdapter"
    assert loop._select_adapter("baidu_keyword").__class__.__name__ != "CommentApiAdapter"  # 回落本地

def test_local_mode_routes_to_local(make_loop):
    loop = make_loop(mode="local")
    assert loop._select_adapter("douyin_comment") is loop._adapters["douyin_comment"]
```

- [ ] **Step 2-3:** 实现
  - `tikhub/__init__.py`:构造 `API_ADAPTERS = {"zhihu_question": ZhihuQuestionApiAdapter(cf), "douyin_comment": CommentApiAdapter(DOUYIN_SPEC, cf, DouyinCommentAdapter._extract_video_id), ...}`,`cf`=client_factory 从 config 造 `TikHubClient`(读 keyring key + base_url)。
  - `platforms/__init__.py`:`from csm_core.monitor.tikhub import API_ADAPTERS`。
  - `monitor_loop.py`:`MonitorLoop.__init__` 存 `self._data_source_mode="local"` + `self._api_adapters`;抽 `_select_adapter(type)`(§5.4 伪码);`_run_one` 改调 `_select_adapter`。
  - `monitor_lifecycle.py`:`reconfigure()` 调 `loop.set_data_source_mode(cfg.monitor.data_source_mode)`。
- [ ] **Step 4: 跑测试确认通过**
- [ ] **Step 5: Commit** — `git commit -am "feat(tikhub): 模式感知分派 + mode 注入链"`

### Task 10:API 模式绕过本地 pacing/slot + 402 短路

**Files:** Modify `monitor_loop.py`、`monitor_lifecycle.py`;Test `sidecar/tests/tikhub/test_pacing_bypass.py`

- [ ] **Step 1: 写失败测试**

```python
def test_api_mode_skips_slot(make_loop, monkeypatch):
    loop = make_loop(mode="tikhub_api")
    entered = []
    monkeypatch.setattr(loop, "_slot", lambda *a, **k: entered.append(a) or _nullctx())
    loop._run_one(_douyin_task())
    assert entered == []          # API 模式不进 platform 信号量

def test_balance_latch_short_circuits_remaining(make_loop):
    from csm_core.monitor.tikhub.client import _trip_balance_latch, reset_balance_latch
    reset_balance_latch(); _trip_balance_latch()
    loop = make_loop(mode="tikhub_api")
    r = loop._run_one(_douyin_task())
    assert r.status == "failed" and "余额" in r.metric["error"]   # 不发请求,直接短路
```

- [ ] **Step 2-3:** 实现
  - `_run_one`:`if self._data_source_mode=="tikhub_api"`:先 `if balance_exhausted(): return failed("TikHub 余额不足,本轮跳过")`;且**不进 `slot()`**(本地反爬信号量);正常走 API 适配器。
  - `monitor_lifecycle._apply_runtime_settings`:`if cfg.monitor.data_source_mode=="tikhub_api"`:**不**给评论平台 `configure_pacing(5~15s)`(或设 0);并发可设高(如 8)。
  - 本轮结束若 `balance_exhausted()`:聚合**一条**"TikHub 余额不足"通知(而非每任务一条),并 `reset_balance_latch()` 供下轮重试。
- [ ] **Step 4: 跑测试确认通过**
- [ ] **Step 5: Commit** — `git commit -am "feat(tikhub): API 模式绕过本地限速 + 402 短路聚合通知"`

---

## Phase 5 — 前端 UI(设计 §6.3)

### Task 11:监测 section「抓取数据源」

**Files:** Modify `frontend/src/views/SettingsView.vue`(监测 section 最顶,line ~1394 之后、Cookie 池之前);复用 `keyringSet/keyringStatus`

- [ ] **Step 1: 加子标题 + 主开关**(照 `browser_engine` autosave 范式)

```vue
<div class="mb-3 mt-5 font-display text-[13px] font-semibold" :style="{ color: 'var(--ink)' }">抓取数据源</div>
<SettingsRow label="付费 API 抓取(TikHub)" hint="开 = 知乎问题 + 抖音/B站/快手评论走 TikHub 付费 API;关 = 本地浏览器抓取">
  <FormToggle
    :model-value="(get('monitor.data_source_mode') ?? 'local') === 'tikhub_api'"
    @update:model-value="(v) => setField('monitor.data_source_mode', v ? 'tikhub_api' : 'local')"
  />
</SettingsRow>
```

- [ ] **Step 2: 开关 ON 条件展开**(`v-if data_source_mode==='tikhub_api'`):API Key(复用 zhihuSecret 那套 input+已配置+保存,`keyringSet("tikhub", raw)`)、接口区域(FormSelect 绑 `monitor.tikhub_base_url`)、成本提示行。新增 `tikhubSecretDraft`/`tikhubHasKey`/`saveTikhubSecret`(照 `zhihuSecret*` 复制)。
- [ ] **Step 3: 本地专属行灰化**:给「浏览器引擎/多账号轮换/每账号任务数/Cookie 冷却」外层加 `:style="{ opacity: get('monitor.data_source_mode')==='tikhub_api' ? 0.5 : 1 }"` + hint 追加「(仅本地模式生效)」。
- [ ] **Step 4: 手动验证**:`npm run dev`(worktree cold-start 见记忆);切换开关→展开/灰化正常;保存 key→keyringStatus 变「已配置」;刷新后 `data_source_mode` 持久。⚠️ 前端无自动化测试,截图核对(可用 Playwright 注入)。
- [ ] **Step 5: Commit** — `git commit -am "feat(settings): 抓取数据源开关 + TikHub key/base_url/成本提示"`

---

## Phase 6 — 打包加固 + 真机验证(设计 §13 R6/R7)

### Task 12:keyring 打包加固

**Files:** Modify `csm-sidecar.spec`、`sidecar/pyproject.toml`、`build_sidecar.py`

- [ ] **Step 1:** spec 里显式 `datas += copy_metadata('keyring')`;`hiddenimports += ['win32ctypes.core', 'win32ctypes.core.ctypes', 'keyring.backends.Windows']`。
- [ ] **Step 2:** `pyproject.toml` deps 加 `pywin32-ctypes>=0.2.0; sys_platform=='win32'`。
- [ ] **Step 3:** `build_sidecar.py` 打包后加 smoke test:子进程跑一次 `keyring.set/get/delete` round-trip,失败即 `sys.exit(1)`(fail 构建)。
- [ ] **Step 4:** 本地重打 sidecar,确认 smoke test 绿。
- [ ] **Step 5: Commit** — `git commit -am "build(tikhub): keyring 打包显式声明 + 打包后 smoke test"`

### Task 13:真机 sanity 验证(手动,收尾)

- [ ] 用户在打包/dev 版:配 TikHub key → 开 API 开关 → 各平台建 1 个任务跑一次,确认:知乎命中排名正确;评论**留存判定**可靠(自己评论找得到、rank 合理);402/无 key 时报中文失败不刷屏。
- [ ] 若评论字段有偏差,回 Task 5 用真实 fixture 校正 normalizer。

---

## 自查(spec 覆盖 / 占位 / 类型一致)

**Spec 覆盖:** §5 架构=Task 2/3/6/7/8/9;§6.1 config=Task 1;§6.3 UI=Task 11;§7 数据流=Task 6/7;§8 normalizer=Task 4/5;§9 错误/402/redact/不重试=Task 2/3/10;§10 测试=各 Task 内联;§11 深度上限=Task 7 spec `depth_cap`;§12 探针=Task 0;§13 R3 scanned_full=Task 6/7、R6 keyring=Task 12、R7 redact=Task 2。**全覆盖。**

**占位扫描:** 评论 normalizer 字段路径依赖 Phase 0 fixture —— 已标注"探针后校正",非 TODO 占位;`KUAISHOU_SPEC`/`BILIBILI_SPEC` 在 Task 8 给出填写依据(§4.1)。`_rank_brand` 签名以源码为准并注明"必须复用不重写"。

**类型一致:** `TikHubClient.get`、`paginate(page_fn,target,max_pages,cancel_token)`、`normalize_*`(返回 `{rank,text,author,likes}` / `{rank,author,content,...}`)、`build_match_result(task,comments)->{rank,metric}`、`MonitorResult(task_id,status,rank,metric)` 全计划一致。

**风险留存:** 评论端点真实字段/顺序需 Phase 0 探针坐实(设计 §12);未跑探针前 Task 5/8 用真实 fixture 前不 merge。
