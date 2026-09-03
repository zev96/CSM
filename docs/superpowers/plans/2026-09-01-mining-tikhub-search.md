# 采集改走 TikHub 付费搜索 + 腾讯文档「评论X」列惯例 —— 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 采集模块「关键词 → 找视频」这一步默认改走 TikHub 付费搜索（免登录、免并发风控），浏览器采集保留为手动兜底；同时让腾讯文档同步按用户表头惯例（`评论A / 评论A的图片 / 评论B / 评论C / 评论D…`）自动对列、层数由表头决定。

**Architecture:** 新增 `csm_core/mining/platforms/tikhub_normalize.py`（纯函数：三平台 TikHub 响应 → `VideoCard` + 翻页请求构造）和 `tikhub_search.py`（一个通用 `TikHubSearchAdapter` + 三个 `SearchSpec`，实现现有 `SearchAdapter` Protocol，带每页重试 / 硬顶 80 / 翻页硬闸 / 402 余额闩）。`runner.get_adapter(platform, mode)` 按 `AppConfig.mining_data_source_mode` 分派；拿到 `VideoCard` 后走**完全不变**的 `on_card` 管线（去重 / 入库 / 品牌预筛）。`TikHubClient` 加 `post()`（抖音搜索只收 POST）。腾讯文档侧新增 `build_column_map_auto()` 按表头发现 `评论X` 列，`sync_approved` 层数改为动态。

**Tech Stack:** Python 3.12 / httpx / pydantic（sidecar）；Vue 3 + TS（frontend）；pytest（`sidecar/tests/`，**不在默认 CI 里，必须显式跑**）。

**Spec:** `docs/superpowers/specs/2026-09-01-mining-tikhub-search-design.md`

**运行测试的固定前缀（worktree 里必须用 PYTHONPATH 覆盖主仓 editable 安装）：**

```bash
cd "D:/CSM/.claude/worktrees/affectionate-heisenberg-9bbcf4"
WT="D:/CSM/.claude/worktrees/affectionate-heisenberg-9bbcf4"
PYTHONPATH="$WT;$WT/sidecar" /d/CSM/.venv/Scripts/python.exe -m pytest <目标> -q
```

下文所有 `pytest …` 命令都省略这个前缀，实际执行时必须带上。

---

## Task 0（已完成，仅供上下文）

以下已在工作树里，**不要重做**：

- 腾讯文档 `sheet.` 前缀 bug 已修（`csm_core/sync/tencent_docs/sheet.py` 五处 `call_tool` 改为不带前缀的 `get_sheet_info / get_cell_data / set_range_value_by_csv / set_cell_style`），并在 `test_connection` 加了 `tools/list` 诊断；`sidecar/tests/test_tencent_docs_sync.py` 30 条全绿。
- 三平台 TikHub 搜索**真实响应**已落 fixture（用真 token 抓、按结构截断，保留全部翻页/包装字段）：
  - `sidecar/tests/tikhub/fixtures/tikhub_search_douyin.json` — `data.business_data` 4 项（type `1,1,1,66668`），首条 `aweme_id=7454425478926060809`、作者 `秋叶`、`digg_count=3936`、`create_time=1735635697`、`video.duration=142710`
  - `sidecar/tests/tikhub/fixtures/tikhub_search_bilibili.json` — `data.data.result` 3 项，`page=1 pagesize=20 numPages=50`，首条 `bvid=BV1w8Mr6VEfW`、作者 `科技先疯队`、`play=173047`、`like=5297`、`pubdate=1785893300`、`duration="11:28"`
  - `sidecar/tests/tikhub/fixtures/tikhub_search_kuaishou.json` — `data.mixFeeds` 4 项（itemType `5,5,5,28`），`data.pcursor="1"`、`data.recoPcursor="no_more"`，首条 `photo_id=5226427428337552341`、`user_name="恭喜的AI 科技"`、`view_count=141046`、`like_count=832`、`duration=64500`（ms）、`timestamp=1640603519820`（ms）

## 文件结构

**新建**
- `csm_core/mining/platforms/tikhub_normalize.py` — 纯函数：请求构造（首页 / 下一页）+ 响应归一化（三平台）
- `csm_core/mining/platforms/tikhub_search.py` — `SearchSpec` + `TikHubSearchAdapter` + 三个 spec + `build_tikhub_search_adapters()`
- `sidecar/tests/tikhub/test_search_normalize.py` — fixture 驱动的归一化测试
- `sidecar/tests/tikhub/test_search_adapter.py` — 适配器行为测试（MockTransport）
- `sidecar/tests/tikhub/test_search_dispatch.py` — runner 按 mode 分派

**修改**
- `csm_core/monitor/tikhub/client.py` — 抽 `_parse()`，新增 `post()`
- `csm_core/config.py` — `AppConfig.mining_data_source_mode`
- `csm_core/mining/runner.py` — `get_adapter(platform, mode)` + `run()` 读 mode
- `frontend/src/components/mining/PlatformPickerCard.vue` — `tikhubMode` prop
- `frontend/src/components/mining/StartJobModal.vue` — `tikhubMode` prop + 默认全选
- `frontend/src/views/MiningView.vue` — 从 config store 算 `tikhubMode` 传下去
- `frontend/src/views/SettingsView.vue` — 采集数据源开关
- `csm_core/sync/tencent_docs/sheet.py` — `build_column_map_auto()`
- `sidecar/csm_sidecar/services/tencent_docs_service.py` — 用 auto 映射、层数动态
- `sidecar/csm_sidecar/services/comment_generation_service.py`、`sidecar/csm_sidecar/routes/mining.py`、`frontend/src/components/mining/GenerateBatchModal.vue` — 生成层数上限 3 → 5
- `sidecar/tests/tikhub/test_client.py`、`sidecar/tests/test_tencent_docs_sync.py` — 追加测试
- `CHANGELOG.md`

---

### Task 1: `TikHubClient.post()`（抖音搜索只收 POST）

**Files:**
- Modify: `csm_core/monitor/tikhub/client.py:88-125`
- Test: `sidecar/tests/tikhub/test_client.py`

- [ ] **Step 1: 写失败测试（追加到 `sidecar/tests/tikhub/test_client.py` 末尾）**

```python
def test_post_sends_json_body_and_auth():
    seen = {}

    def h(req):
        seen["auth"] = req.headers.get("authorization")
        seen["ct"] = req.headers.get("content-type")
        seen["body"] = req.read()
        seen["method"] = req.method
        return httpx.Response(200, json={"code": 200, "data": {"ok": 1}})

    out = _client(h).post("/api/v1/douyin/search/fetch_video_search_v2", {"keyword": "x", "cursor": 0})
    assert out["data"] == {"ok": 1}
    assert seen["method"] == "POST"
    assert seen["auth"] == "Bearer k"
    assert "application/json" in seen["ct"]
    assert b'"keyword": "x"' in seen["body"] or b'"keyword":"x"' in seen["body"]


def test_post_402_trips_latch():
    c = _client(lambda req: httpx.Response(402, json={"code": 402}))
    with pytest.raises(TikHubBalanceExhausted):
        c.post("/p", {})
    assert balance_exhausted() is True


def test_post_body_code_non_200_raises():
    c = _client(lambda req: httpx.Response(200, json={"code": 500, "message": "boom"}))
    with pytest.raises(TikHubError):
        c.post("/p", {})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest sidecar/tests/tikhub/test_client.py -q -k post`
Expected: 3 FAILED —— `AttributeError: 'TikHubClient' object has no attribute 'post'`

- [ ] **Step 3: 实现 —— 抽 `_parse()`，`get()` 复用，新增 `post()`**

把 `client.py` 里 `def get(...)` 整个方法替换为：

```python
    def _parse(self, r: httpx.Response, path: str) -> dict:
        """HTTP 状态 → JSON → 业务 code 三层校验(get/post 共用)。"""
        # 1) HTTP 层错误
        if r.status_code != 200:
            self._fail(r.status_code, r.status_code, path, r.text)

        # 2) 解析 JSON —— 非法 JSON 统一成 TikHubError,别让 JSONDecodeError 击穿上层
        try:
            data = r.json()
        except ValueError as e:
            logger.warning(
                "[tikhub] %s http=200 非法JSON first200=%s", path, self._redact(r.text)[:200]
            )
            raise TikHubError("TikHub 响应不是合法 JSON") from e

        # 3) 业务层错误:HTTP 200 但 body.code != 200(聚合 API 常见做法)
        biz_code = data.get("code") if isinstance(data, dict) else None
        if isinstance(biz_code, int) and biz_code != 200:
            self._fail(biz_code, 200, path, r.text)

        return data

    def get(self, path: str, params: dict) -> dict:
        """对 TikHub API 发起一次鉴权 GET,返回解析后的 JSON 响应体(整个 wrapper)。

        触发 TikHubError 的情形:HTTP 非 200 / 响应体 code != 200 / 非法 JSON / 网络错误。
        402(HTTP 或 body code)会额外触发进程级余额闩。
        """
        if not path.startswith("/"):
            path = "/" + path
        # 日志绝不带 Authorization / key —— 只记录路径与参数。
        logger.info("[tikhub] GET %s params=%s", path, dict(params))
        try:
            r = self._http.get(
                self._base + path,
                params=params,
                headers={"Authorization": f"Bearer {self._key}"},
            )
        except httpx.HTTPError as e:
            raise TikHubError("网络错误") from e
        return self._parse(r, path)

    def post(self, path: str, json_body: dict) -> dict:
        """对 TikHub API 发起一次鉴权 POST(JSON body),错误语义与 get() 完全一致。

        抖音搜索系列端点(/api/v1/douyin/search/*)只收 POST。日志只记 body 的
        key 列表(keyword 可能含用户敏感词,不记值)。
        """
        if not path.startswith("/"):
            path = "/" + path
        logger.info("[tikhub] POST %s body_keys=%s", path, sorted(json_body))
        try:
            r = self._http.post(
                self._base + path,
                json=json_body,
                headers={"Authorization": f"Bearer {self._key}"},
            )
        except httpx.HTTPError as e:
            raise TikHubError("网络错误") from e
        return self._parse(r, path)
```

- [ ] **Step 4: 跑全部 client 测试确认通过（含旧的 get 测试零回归）**

Run: `pytest sidecar/tests/tikhub/test_client.py -q`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add csm_core/monitor/tikhub/client.py sidecar/tests/tikhub/test_client.py
git commit -m "feat(tikhub): client 增加 post()（抖音搜索只收 POST），get/post 共用 _parse 三层校验"
```

---

### Task 2: 配置项 `mining_data_source_mode`

**Files:**
- Modify: `csm_core/config.py:310-311`（`mining_prefilter_threshold` 之后）
- Test: `sidecar/tests/tikhub/test_config_fields.py`

- [ ] **Step 1: 写失败测试（追加到 `sidecar/tests/tikhub/test_config_fields.py` 末尾）**

```python
def test_mining_data_source_mode_defaults_to_tikhub():
    from csm_core.config import AppConfig
    assert AppConfig().mining_data_source_mode == "tikhub_api"


def test_mining_data_source_mode_accepts_local_only():
    import pytest
    from pydantic import ValidationError
    from csm_core.config import AppConfig
    assert AppConfig(mining_data_source_mode="local").mining_data_source_mode == "local"
    with pytest.raises(ValidationError):
        AppConfig(mining_data_source_mode="browser")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest sidecar/tests/tikhub/test_config_fields.py -q -k mining_data_source`
Expected: FAIL —— `AttributeError` / `ValidationError`（字段不存在）

- [ ] **Step 3: 实现 —— 在 `mining_prefilter_threshold` 那行之后插入**

```python
    # ── Mining 采集数据源（2026-09-01 拍板：默认走 TikHub 付费搜索）────────
    # tikhub_api = 三平台关键词搜索走 TikHub（免登录、免并发风控，$0.01/次）；
    # local      = 本地浏览器采集（手动兜底：TikHub 宕机 / 额度耗尽时切回）。
    # 复用 monitor.tikhub_base_url + keyring provider="tikhub"，不单独配。
    mining_data_source_mode: Literal["tikhub_api", "local"] = "tikhub_api"
```

（`Literal` 已在文件顶部 import，`MonitorConfig.data_source_mode` 同款写法。）

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest sidecar/tests/tikhub/test_config_fields.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add csm_core/config.py sidecar/tests/tikhub/test_config_fields.py
git commit -m "feat(mining): AppConfig.mining_data_source_mode（默认 tikhub_api）"
```

---

### Task 3: 归一化 —— 抖音（复用浏览器 `_extract_cards`）

**Files:**
- Create: `csm_core/mining/platforms/tikhub_normalize.py`
- Test: `sidecar/tests/tikhub/test_search_normalize.py`

- [ ] **Step 1: 写失败测试（新建文件）**

```python
"""TikHub 关键词搜索响应 → VideoCard 归一化（真实 fixture，2026-09-01 实测抓取）。"""
import json
import pathlib

from csm_core.mining.platforms import tikhub_normalize as N

FIX = pathlib.Path(__file__).parent / "fixtures"


def _load(name: str) -> dict:
    return json.loads((FIX / name).read_text(encoding="utf-8"))


# ── 抖音 ────────────────────────────────────────────────────────────────

def test_douyin_first_body_pushes_filters_down():
    body = N.douyin_first_body("空气净化器", {
        "publish_time": "182", "sort_type": "1", "content_types": ["video"],
    })
    assert body == {
        "keyword": "空气净化器", "cursor": 0, "search_id": "", "backtrace": "",
        "sort_type": "1", "publish_time": "180", "content_type": "1",
    }


def test_douyin_first_body_content_type_mapping():
    assert N.douyin_first_body("k", {"content_types": ["note"]})["content_type"] == "2"
    assert N.douyin_first_body("k", {"content_types": ["video", "note"]})["content_type"] == "0"
    assert N.douyin_first_body("k", {})["content_type"] == "1"          # 缺省=仅视频


def test_douyin_normalize_real_fixture_filters_non_video_cards():
    raw = _load("tikhub_search_douyin.json")
    cards = N.normalize_douyin_search(raw, {"content_types": ["video"]})
    # fixture 里 business_data 4 项：3 张 type==1 视频卡 + 1 张 type==66668 非视频卡
    assert len(cards) == 3
    c = cards[0]
    assert c.platform == "douyin"
    assert c.platform_video_id == "7454425478926060809"
    assert c.author_name == "秋叶"
    assert c.like_count == 3936
    assert c.duration_sec == 142
    assert c.published_at == "2024-12-31T09:01:37Z"
    assert c.url.startswith("https://")


def test_douyin_next_body_reads_business_config():
    raw = _load("tikhub_search_douyin.json")
    prev = N.douyin_first_body("k", {})
    nxt = N.douyin_next_body(prev, raw)
    assert nxt is not None
    assert nxt["cursor"] == 8
    assert nxt["search_id"] == "202609012007081FFCE74A7B89BE04E03E"
    assert nxt["backtrace"]                         # 非空字符串
    assert nxt["keyword"] == "k" and nxt["content_type"] == prev["content_type"]


def test_douyin_next_body_none_when_no_more():
    raw = {"data": {"business_config": {"has_more": 0}}}
    assert N.douyin_next_body(N.douyin_first_body("k", {}), raw) is None
    assert N.douyin_next_body(N.douyin_first_body("k", {}), {"data": {}}) is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest sidecar/tests/tikhub/test_search_normalize.py -q -k douyin`
Expected: FAIL —— `ModuleNotFoundError: No module named 'csm_core.mining.platforms.tikhub_normalize'`

- [ ] **Step 3: 新建 `csm_core/mining/platforms/tikhub_normalize.py`（先只写抖音部分）**

```python
"""TikHub 关键词搜索响应 → VideoCard 归一化 + 翻页请求构造（纯函数，fixture 可测）。

字段路径全部来自 2026-09-01 用真实 token 实测（spec §4.2），不是文档猜测：

- 抖音 ``POST /api/v1/douyin/search/fetch_video_search_v2``
    视频：``data.business_data[type==1].data.aweme_info``（与浏览器 XHR 的
    aweme_info **同形** → 直接借用 ``douyin_search.DouyinSearchAdapter._extract_cards``）
    翻页：``data.business_config.{has_more, next_page.cursor, next_page.search_id, backtrace}``
- B站 ``GET /api/v1/bilibili/web/fetch_general_search``
    视频：``data.data.result[type=="video"]``；翻页：``data.data.{page, numPages}``
- 快手 ``GET /api/v1/kuaishou/app/search_video_v2``
    视频：``data.mixFeeds[itemType==5].feed``（flat 字段）；
    翻页：``data.pcursor``，``data.recoPcursor=="no_more"`` 结束

约定：``*_first_*(keyword, plat_filters)`` 造首页请求；``*_next_*(prev, raw)`` 从上一页
响应造下一页请求，返回 None = 没有下一页；``normalize_*(raw, plat_filters)`` 出卡片。
"""
from __future__ import annotations

from typing import Any

from csm_core.mining.models import VideoCard
from csm_core.mining.platforms._common import (
    date_to_epoch, iso_within_epoch_range, parse_duration,
)
from csm_core.mining.platforms.bilibili_search import (
    _normalize_url, _pubdate_to_iso, _strip_em,
)
from csm_core.mining.platforms.douyin_search import DouyinSearchAdapter
from csm_core.mining.platforms.kuaishou_search import _ts_ms_to_iso

# ── 抖音 ────────────────────────────────────────────────────────────────

# UI 档位 → TikHub publish_time（UI 半年=182，TikHub 半年=180）
_DY_PUBLISH_TIME = {"0": "0", "1": "1", "7": "7", "182": "180"}


def douyin_first_body(keyword: str, f: dict[str, Any]) -> dict[str, Any]:
    """抖音首页 POST body：筛选全部下推（排序 / 发布时间 / 内容类型）。

    content_type：仅视频=1、仅图文=2、两者都要=0（全部）再由 normalize 按
    content_types 后过滤（与浏览器适配器"综合搜索 + 后过滤"同口径）。
    """
    types = set(f.get("content_types") or ["video"])
    if types == {"video"}:
        content_type = "1"
    elif types == {"note"}:
        content_type = "2"
    else:
        content_type = "0"
    return {
        "keyword": keyword,
        "cursor": 0,
        "search_id": "",
        "backtrace": "",
        "sort_type": str(f.get("sort_type") or "0"),
        "publish_time": _DY_PUBLISH_TIME.get(str(f.get("publish_time") or "0"), "0"),
        "content_type": content_type,
    }


def douyin_next_body(prev: dict[str, Any], raw: dict[str, Any]) -> dict[str, Any] | None:
    cfg = (raw.get("data") or {}).get("business_config") or {}
    if cfg.get("has_more") != 1:
        return None
    nxt = cfg.get("next_page") or {}
    if nxt.get("cursor") is None:
        return None
    body = dict(prev)
    body["cursor"] = nxt.get("cursor")
    body["search_id"] = nxt.get("search_id") or prev.get("search_id") or ""
    body["backtrace"] = cfg.get("backtrace") or ""
    return body


def normalize_douyin_search(raw: dict[str, Any], f: dict[str, Any]) -> list[VideoCard]:
    """只取 type==1 的视频卡；aweme_info 与浏览器 XHR 同形，直接借用现有抽取器。"""
    allowed = frozenset(f.get("content_types") or ["video"])
    items = [
        it["data"]
        for it in ((raw.get("data") or {}).get("business_data") or [])
        if isinstance(it, dict) and it.get("type") == 1 and isinstance(it.get("data"), dict)
    ]
    return DouyinSearchAdapter()._extract_cards({"data": items}, allowed_types=allowed)
```

- [ ] **Step 4: 跑抖音测试确认通过**

Run: `pytest sidecar/tests/tikhub/test_search_normalize.py -q -k douyin`
Expected: 5 PASS

- [ ] **Step 5: Commit**

```bash
git add csm_core/mining/platforms/tikhub_normalize.py sidecar/tests/tikhub/test_search_normalize.py
git commit -m "feat(mining): TikHub 抖音搜索归一化 + 翻页（复用 _extract_cards，真实 fixture）"
```

---

### Task 4: 归一化 —— B站（`web/fetch_general_search`，日期区间下推）

**Files:**
- Modify: `csm_core/mining/platforms/tikhub_normalize.py`（追加）
- Test: `sidecar/tests/tikhub/test_search_normalize.py`（追加）

- [ ] **Step 1: 追加失败测试**

```python
# ── B站 ─────────────────────────────────────────────────────────────────

def test_bilibili_first_params_pushes_order_and_date_range():
    p = N.bilibili_first_params("空气净化器", {
        "order": "pubdate", "time_begin": "2026-08-01", "time_end": "2026-08-31",
    })
    assert p["keyword"] == "空气净化器"
    assert p["order"] == "pubdate"
    assert p["page"] == 1 and p["page_size"] == 20
    assert isinstance(p["pubtime_begin_s"], int)
    assert isinstance(p["pubtime_end_s"], int)
    assert p["pubtime_end_s"] > p["pubtime_begin_s"]


def test_bilibili_first_params_defaults_and_bad_order():
    p = N.bilibili_first_params("k", {"order": "nonsense"})
    assert p["order"] == "totalrank"
    assert "pubtime_begin_s" not in p and "pubtime_end_s" not in p


def test_bilibili_normalize_real_fixture():
    raw = _load("tikhub_search_bilibili.json")
    cards = N.normalize_bilibili_search(raw, {})
    assert len(cards) == 3
    c = cards[0]
    assert c.platform == "bilibili"
    assert c.platform_video_id == "BV1w8Mr6VEfW"
    assert c.url == "https://www.bilibili.com/video/BV1w8Mr6VEfW"
    assert "<em" not in c.title and "空气净化器" in c.title      # <em> 高亮已 strip
    assert c.author_name == "科技先疯队"
    assert c.play_count == 173047 and c.like_count == 5297
    assert c.duration_sec == 11 * 60 + 28
    assert c.published_at == "2026-08-05T01:28:20Z"
    assert c.cover_url.startswith("https://")


def test_bilibili_next_params_increments_until_numpages():
    raw = _load("tikhub_search_bilibili.json")            # page=1, numPages=50
    prev = N.bilibili_first_params("k", {})
    nxt = N.bilibili_next_params(prev, raw)
    assert nxt is not None and nxt["page"] == 2
    last = {"data": {"data": {"page": 50, "numPages": 50, "result": [{"type": "video"}]}}}
    assert N.bilibili_next_params({"page": 50}, last) is None
    empty = {"data": {"data": {"page": 1, "numPages": 50, "result": []}}}
    assert N.bilibili_next_params({"page": 1}, empty) is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest sidecar/tests/tikhub/test_search_normalize.py -q -k bilibili`
Expected: FAIL —— `AttributeError: module ... has no attribute 'bilibili_first_params'`

- [ ] **Step 3: 在 `tikhub_normalize.py` 末尾追加**

```python
# ── B站 ─────────────────────────────────────────────────────────────────

_BL_VALID_ORDERS = {"totalrank", "click", "pubdate", "dm", "stow"}   # 与 bilibili_search 同集合
_BL_PAGE_SIZE = 20


def bilibili_first_params(keyword: str, f: dict[str, Any]) -> dict[str, Any]:
    """B站 general_search：order 必填（实测 totalrank 通过；其余为 B 站原生取值），
    日期区间 → pubtime_begin_s / pubtime_end_s（本地时区当天 00:00:00 / 23:59:59）。"""
    order = str(f.get("order") or "totalrank")
    params: dict[str, Any] = {
        "keyword": keyword,
        "order": order if order in _BL_VALID_ORDERS else "totalrank",
        "page": 1,
        "page_size": _BL_PAGE_SIZE,
    }
    begin = date_to_epoch(f.get("time_begin"))
    if begin is not None:
        params["pubtime_begin_s"] = begin
    end = date_to_epoch(f.get("time_end"), end_of_day=True)
    if end is not None:
        params["pubtime_end_s"] = end
    return params


def bilibili_next_params(prev: dict[str, Any], raw: dict[str, Any]) -> dict[str, Any] | None:
    inner = (raw.get("data") or {}).get("data") or {}
    if not inner.get("result"):
        return None
    page = int(inner.get("page") or prev.get("page") or 1)
    num_pages = int(inner.get("numPages") or 0)
    if num_pages and page >= num_pages:
        return None
    params = dict(prev)
    params["page"] = page + 1
    return params


def _int_or_none(v: Any) -> int | None:
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def normalize_bilibili_search(raw: dict[str, Any], f: dict[str, Any]) -> list[VideoCard]:
    inner = (raw.get("data") or {}).get("data") or {}
    cards: list[VideoCard] = []
    for it in inner.get("result") or []:
        if not isinstance(it, dict) or it.get("type") != "video":
            continue
        bvid = it.get("bvid")
        if not bvid:
            continue
        cards.append(VideoCard(
            platform="bilibili",
            platform_video_id=str(bvid),
            url=f"https://www.bilibili.com/video/{bvid}",
            title=_strip_em(str(it.get("title") or "")).strip(),
            author_name=str(it.get("author") or "").strip(),
            author_id=str(it.get("mid") or ""),
            cover_url=_normalize_url(str(it.get("pic") or "")),
            duration_sec=parse_duration(str(it.get("duration") or "")),
            play_count=_int_or_none(it.get("play")),
            like_count=_int_or_none(it.get("like")),
            published_at=_pubdate_to_iso(it.get("pubdate")),
            raw=it,
        ))
    return cards
```

- [ ] **Step 4: 跑 B站测试确认通过**

Run: `pytest sidecar/tests/tikhub/test_search_normalize.py -q -k bilibili`
Expected: 4 PASS

- [ ] **Step 5: Commit**

```bash
git add csm_core/mining/platforms/tikhub_normalize.py sidecar/tests/tikhub/test_search_normalize.py
git commit -m "feat(mining): TikHub B站搜索归一化 + 翻页（排序/日期区间下推，真实 fixture）"
```

---

### Task 5: 归一化 —— 快手（flat feed + 本地时间后过滤 + itemType 过滤）

**Files:**
- Modify: `csm_core/mining/platforms/tikhub_normalize.py`（追加）
- Test: `sidecar/tests/tikhub/test_search_normalize.py`（追加）

- [ ] **Step 1: 追加失败测试**

```python
# ── 快手 ────────────────────────────────────────────────────────────────

def test_kuaishou_first_params_keyword_only():
    assert N.kuaishou_first_params("k", {"time_begin": "2026-01-01"}) == {"keyword": "k", "pcursor": ""}


def test_kuaishou_normalize_real_fixture_skips_non_video_items():
    raw = _load("tikhub_search_kuaishou.json")
    cards = N.normalize_kuaishou_search(raw, {})
    # fixture：3 条 itemType==5 视频 + 1 条 itemType==28 相关搜索卡（必须跳过）
    assert len(cards) == 3
    c = cards[0]
    assert c.platform == "kuaishou"
    assert c.platform_video_id == "5226427428337552341"
    assert c.url == "https://www.kuaishou.com/short-video/5226427428337552341"
    assert c.title.startswith("空气净化器千万不要买")
    assert c.author_name == "恭喜的AI 科技"
    assert c.play_count == 141046 and c.like_count == 832
    assert c.duration_sec == 64                        # 64500ms → 64s
    assert c.published_at == "2021-12-27T11:11:59Z"    # 1640603519820ms


def test_kuaishou_normalize_local_time_filter_excludes_out_of_range():
    raw = _load("tikhub_search_kuaishou.json")
    # 首条发布于 2021-12-27；只要 2026 年的 → 应被本地后过滤掉
    cards = N.normalize_kuaishou_search(raw, {"time_begin": "2026-01-01", "time_end": "2026-12-31"})
    assert all(c.platform_video_id != "5226427428337552341" for c in cards)


def test_kuaishou_next_params_stops_on_no_more():
    raw = _load("tikhub_search_kuaishou.json")           # recoPcursor == "no_more"
    assert N.kuaishou_next_params({"keyword": "k", "pcursor": ""}, raw) is None
    more = {"data": {"pcursor": "2", "recoPcursor": "x", "mixFeeds": [{"itemType": 5}]}}
    assert N.kuaishou_next_params({"keyword": "k", "pcursor": ""}, more) == {"keyword": "k", "pcursor": "2"}
    assert N.kuaishou_next_params({"keyword": "k"}, {"data": {"pcursor": "no_more", "mixFeeds": [1]}}) is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest sidecar/tests/tikhub/test_search_normalize.py -q -k kuaishou`
Expected: FAIL —— `AttributeError ... 'kuaishou_first_params'`

- [ ] **Step 3: 在 `tikhub_normalize.py` 末尾追加**

```python
# ── 快手 ────────────────────────────────────────────────────────────────

def kuaishou_first_params(keyword: str, f: dict[str, Any]) -> dict[str, Any]:
    """快手 search_video_v2 无服务端筛选 —— 时间区间在 normalize 里本地后过滤。"""
    return {"keyword": keyword, "pcursor": ""}


def kuaishou_next_params(prev: dict[str, Any], raw: dict[str, Any]) -> dict[str, Any] | None:
    d = raw.get("data") or {}
    pc = d.get("pcursor")
    if d.get("recoPcursor") == "no_more" or not pc or pc == "no_more" or not d.get("mixFeeds"):
        return None
    params = dict(prev)
    params["pcursor"] = str(pc)
    return params


def _first_cover(v: Any) -> str:
    if isinstance(v, list) and v:
        first = v[0]
        if isinstance(first, dict):
            return str(first.get("url") or "")
        return str(first or "")
    return ""


def normalize_kuaishou_search(raw: dict[str, Any], f: dict[str, Any]) -> list[VideoCard]:
    """只取 itemType==5 的视频项；feed 为 flat 字段；时间区间本地后过滤（被滤掉的不
    计入 emitted，翻页自然补偿 —— 与浏览器快手适配器同口径）。"""
    begin = date_to_epoch(f.get("time_begin"))
    end = date_to_epoch(f.get("time_end"), end_of_day=True)
    cards: list[VideoCard] = []
    for it in (raw.get("data") or {}).get("mixFeeds") or []:
        if not isinstance(it, dict) or str(it.get("itemType")) != "5":
            continue
        feed = it.get("feed") or {}
        pid = feed.get("photo_id")
        if not pid:
            continue
        pid = str(pid)
        dur_ms = feed.get("duration") or 0
        ts_ms = feed.get("timestamp") or 0
        card = VideoCard(
            platform="kuaishou",
            platform_video_id=pid,
            url=f"https://www.kuaishou.com/short-video/{pid}",
            title=str(feed.get("caption") or "").strip(),
            author_name=str(feed.get("user_name") or "").strip(),
            author_id=str(feed.get("user_id") or ""),
            cover_url=_first_cover(feed.get("cover_thumbnail_urls")),
            duration_sec=int(dur_ms / 1000) if dur_ms else None,
            play_count=_int_or_none(feed.get("view_count")),
            like_count=_int_or_none(feed.get("like_count")),
            published_at=_ts_ms_to_iso(ts_ms) if ts_ms else None,
            raw=feed,
        )
        if not iso_within_epoch_range(card.published_at, begin, end):
            continue
        cards.append(card)
    return cards
```

- [ ] **Step 4: 跑整个归一化测试文件确认通过**

Run: `pytest sidecar/tests/tikhub/test_search_normalize.py -q`
Expected: 13 PASS

- [ ] **Step 5: Commit**

```bash
git add csm_core/mining/platforms/tikhub_normalize.py sidecar/tests/tikhub/test_search_normalize.py
git commit -m "feat(mining): TikHub 快手搜索归一化 + 翻页（itemType 过滤 + 本地时间后过滤）"
```

---

### Task 6: `TikHubSearchAdapter`（重试 / 硬顶 / 翻页硬闸 / 402 闩 / 取消）

**Files:**
- Create: `csm_core/mining/platforms/tikhub_search.py`
- Test: `sidecar/tests/tikhub/test_search_adapter.py`

- [ ] **Step 1: 写失败测试（新建文件）**

```python
"""TikHubSearchAdapter 行为测试：翻页 / 每页重试 / 402 不重试 / 硬顶 80 / 翻页硬闸 / 取消 / 无 key。"""
import json
import threading

import httpx
import pytest

from csm_core.mining.platforms import tikhub_search as S
from csm_core.monitor.tikhub import client as tclient
from csm_core.monitor.tikhub.client import TikHubClient


@pytest.fixture(autouse=True)
def _reset_latch_and_sleep(monkeypatch):
    tclient.reset_balance_latch()
    monkeypatch.setattr(S, "_RETRY_SLEEP_S", 0.0)     # 重试不真睡
    yield
    tclient.reset_balance_latch()


def _dy_page(aweme_ids, *, has_more: int, next_cursor: int):
    """最小抖音 v2 响应：只含 _extract_cards / douyin_next_body 需要的字段。"""
    cards = [{
        "type": 1,
        "data": {"aweme_info": {
            "aweme_id": aid, "desc": f"d{aid}", "author": {"nickname": "n", "uid": 1},
            "statistics": {"digg_count": 1, "play_count": 2}, "video": {"duration": 1000},
            "create_time": 1735635697, "aweme_type": 0,
        }},
    } for aid in aweme_ids]
    return {"code": 200, "data": {
        "business_data": cards,
        "business_config": {"has_more": has_more, "backtrace": "bt",
                            "next_page": {"cursor": next_cursor, "search_id": "sid"}},
    }}


def _adapter(handler, spec=S.DOUYIN_SEARCH_SPEC, key="k"):
    def cf():
        if not key:
            from csm_core.monitor.tikhub.errors import TikHubError
            raise TikHubError("未配置 TikHub API Key，请到设置页粘贴")
        return TikHubClient(base_url="https://api.tikhub.dev", api_key=key,
                            _transport=httpx.MockTransport(handler))
    return S.TikHubSearchAdapter(spec, cf)


def _run(adapter, target=50, cancel=None, filters=None):
    cards, progress = [], []
    out = adapter.search(
        keyword="k", target_count=target,
        on_card=cards.append, on_progress=progress.append,
        cancel_event=cancel or threading.Event(), filters=filters,
    )
    return out, cards, progress


def test_douyin_two_pages_propagate_cursor_and_search_id():
    bodies = []

    def h(req):
        body = json.loads(req.read())
        bodies.append(body)
        if body["cursor"] == 0:
            return httpx.Response(200, json=_dy_page(["1", "2"], has_more=1, next_cursor=8))
        return httpx.Response(200, json=_dy_page(["3"], has_more=0, next_cursor=0))

    out, cards, _ = _run(_adapter(h), target=10)
    assert out.status == "done" and out.cards_emitted == 3
    assert [c.platform_video_id for c in cards] == ["1", "2", "3"]
    assert [c.rank_in_search for c in cards] == [1, 2, 3]
    assert bodies[0]["cursor"] == 0 and bodies[0]["search_id"] == ""
    assert bodies[1]["cursor"] == 8 and bodies[1]["search_id"] == "sid" and bodies[1]["backtrace"] == "bt"


def test_dedup_within_run():
    h = lambda req: httpx.Response(200, json=_dy_page(["1", "1", "2"], has_more=0, next_cursor=0))
    out, cards, _ = _run(_adapter(h))
    assert out.cards_emitted == 2 and [c.platform_video_id for c in cards] == ["1", "2"]


def test_page_failure_retries_then_succeeds():
    calls = {"n": 0}

    def h(req):
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(429, json={"code": 429})
        return httpx.Response(200, json=_dy_page(["1"], has_more=0, next_cursor=0))

    out, cards, _ = _run(_adapter(h))
    assert out.status == "done" and out.cards_emitted == 1
    assert calls["n"] == 3


def test_page_failure_exhausts_retries_then_failed():
    calls = {"n": 0}

    def h(req):
        calls["n"] += 1
        return httpx.Response(500, json={"code": 500})

    out, cards, progress = _run(_adapter(h))
    assert out.status == "failed" and out.cards_emitted == 0
    assert calls["n"] == S.PAGE_RETRIES
    assert "TikHub" in out.error_message
    assert progress[-1].phase == "failed"


def test_402_fails_immediately_without_retry_and_trips_latch():
    calls = {"n": 0}

    def h(req):
        calls["n"] += 1
        return httpx.Response(402, json={"code": 402})

    out, _, _ = _run(_adapter(h))
    assert out.status == "failed" and calls["n"] == 1
    assert tclient.balance_exhausted() is True


def test_latch_already_tripped_short_circuits_without_request():
    tclient._trip_balance_latch()
    calls = {"n": 0}

    def h(req):
        calls["n"] += 1
        return httpx.Response(200, json=_dy_page(["1"], has_more=0, next_cursor=0))

    out, _, _ = _run(_adapter(h))
    assert out.status == "failed" and calls["n"] == 0
    assert "余额" in out.error_message


def test_hard_cap_80_even_if_more_available():
    def h(req):
        body = json.loads(req.read())
        base = int(body["cursor"])
        ids = [str(base + i) for i in range(20)]
        return httpx.Response(200, json=_dy_page(ids, has_more=1, next_cursor=base + 20))

    out, cards, _ = _run(_adapter(h), target=200)
    assert out.status == "done" and out.cards_emitted == S.HARD_CAP == 80
    assert len(cards) == 80


def test_max_pages_guard_stops_runaway_pagination():
    calls = {"n": 0}

    def h(req):
        calls["n"] += 1
        # 每页都说 has_more 但只回 1 条且不重复 → 靠 MAX_PAGES 硬闸停
        return httpx.Response(200, json=_dy_page([str(calls["n"])], has_more=1, next_cursor=calls["n"]))

    out, cards, _ = _run(_adapter(h), target=80)
    assert out.status == "done"
    assert calls["n"] == S.MAX_PAGES and len(cards) == S.MAX_PAGES


def test_cancel_before_first_page():
    ev = threading.Event(); ev.set()
    calls = {"n": 0}

    def h(req):
        calls["n"] += 1
        return httpx.Response(200, json=_dy_page(["1"], has_more=0, next_cursor=0))

    out, _, _ = _run(_adapter(h), cancel=ev)
    assert out.status == "cancelled" and calls["n"] == 0


def test_missing_key_returns_failed_not_raise():
    out, _, progress = _run(_adapter(lambda req: httpx.Response(200, json={}), key=""))
    assert out.status == "failed" and "未配置" in out.error_message
    assert progress[-1].phase == "failed"


def test_bilibili_spec_uses_get_with_query_params():
    seen = {}

    def h(req):
        seen["method"] = req.method
        seen["q"] = dict(req.url.params)
        return httpx.Response(200, json={"code": 200, "data": {"data": {
            "page": 1, "numPages": 1, "result": [{
                "type": "video", "bvid": "BV1", "title": "t", "author": "a", "mid": 1,
                "pic": "//x/p.jpg", "play": 1, "like": 2, "pubdate": 1785893300, "duration": "1:00",
            }],
        }}})

    out, cards, _ = _run(_adapter(h, spec=S.BILIBILI_SEARCH_SPEC),
                         filters={"bilibili": {"order": "click"}})
    assert seen["method"] == "GET" and seen["q"]["order"] == "click" and seen["q"]["keyword"] == "k"
    assert out.status == "done" and cards[0].platform_video_id == "BV1"


def test_build_factory_returns_three_platform_adapters():
    from unittest.mock import MagicMock
    ad = S.build_tikhub_search_adapters(lambda: MagicMock(), lambda p, c=None: "k")
    assert set(ad) == {"douyin", "bilibili", "kuaishou"}
    assert all(isinstance(a, S.TikHubSearchAdapter) for a in ad.values())
    assert ad["kuaishou"].platform == "kuaishou"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest sidecar/tests/tikhub/test_search_adapter.py -q`
Expected: FAIL —— `ModuleNotFoundError ... tikhub_search`

- [ ] **Step 3: 新建 `csm_core/mining/platforms/tikhub_search.py`**

```python
"""TikHub 付费关键词搜索适配器 —— 采集模块「找视频」这一步的 API 路径。

设计依据：docs/superpowers/specs/2026-09-01-mining-tikhub-search-design.md

实现现有 ``SearchAdapter`` Protocol；拿到 ``VideoCard`` 后走与浏览器适配器**完全相同**的
``on_card`` 管线（去重 / 入库 / 品牌预筛都不变）。与浏览器路径的差异：

- 免登录、无并发风控限速（这正是切换的动机）；
- 失败**不回退**浏览器（spec D5），该平台记 ``failed`` + 通知；
- 每页失败**重试 ≤ PAGE_RETRIES 次**（官方标注搜索端点偶发失败，搜索只读无副作用）；
  402 余额耗尽**不重试**（重试 = 继续烧），且走进程级余额闩本轮短路；
- 成本护栏：``target`` 硬顶 ``HARD_CAP``，翻页 ``MAX_PAGES`` 硬闸（防跑飞计费）。
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

from csm_core.mining.models import Platform, ProgressUpdate, SearchOutcome, VideoCard
from csm_core.mining.platforms import tikhub_normalize as N
from csm_core.mining.platforms._common import OnCard, OnProgress
from csm_core.monitor.tikhub.client import TikHubClient, balance_exhausted
from csm_core.monitor.tikhub.errors import TikHubBalanceExhausted, TikHubError

logger = logging.getLogger(__name__)

HARD_CAP = 80          # 每平台单次采集条数硬顶（spec D3）
MAX_PAGES = 12         # 翻页硬闸：抖音每页 ~6–14 条，80 条最多 ~12 页；超过视为异常停
PAGE_RETRIES = 3       # 每页最多尝试次数（官方：搜索偶发失败，同参重试 1–3 次）
_RETRY_SLEEP_S = 1.0   # 重试间隔（测试里 monkeypatch 成 0）


@dataclass(frozen=True)
class SearchSpec:
    platform: Platform
    method: str                                                        # "GET" | "POST"
    path: str
    first_request: Callable[[str, dict[str, Any]], dict[str, Any]]      # (keyword, plat_filters)
    next_request: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any] | None]  # (prev, raw)
    normalize: Callable[[dict[str, Any], dict[str, Any]], list[VideoCard]]           # (raw, plat_filters)


DOUYIN_SEARCH_SPEC = SearchSpec(
    "douyin", "POST", "/api/v1/douyin/search/fetch_video_search_v2",
    N.douyin_first_body, N.douyin_next_body, N.normalize_douyin_search,
)
BILIBILI_SEARCH_SPEC = SearchSpec(
    "bilibili", "GET", "/api/v1/bilibili/web/fetch_general_search",
    N.bilibili_first_params, N.bilibili_next_params, N.normalize_bilibili_search,
)
KUAISHOU_SEARCH_SPEC = SearchSpec(
    "kuaishou", "GET", "/api/v1/kuaishou/app/search_video_v2",
    N.kuaishou_first_params, N.kuaishou_next_params, N.normalize_kuaishou_search,
)


class TikHubSearchAdapter:
    """一个通用适配器 + 平台 spec。client_factory 惰性建 client（配置改了下个任务生效）。"""

    def __init__(self, spec: SearchSpec, client_factory: Callable[[], TikHubClient]):
        self.spec = spec
        self.platform: Platform = spec.platform
        self._cf = client_factory

    # ── 单页调用（含重试）──────────────────────────────────────────────
    def _call(self, client: TikHubClient, req: dict[str, Any]) -> dict[str, Any]:
        if self.spec.method == "POST":
            return client.post(self.spec.path, req)
        return client.get(self.spec.path, req)

    def _call_with_retry(self, client: TikHubClient, req: dict[str, Any]) -> dict[str, Any]:
        last: TikHubError | None = None
        for attempt in range(1, PAGE_RETRIES + 1):
            try:
                return self._call(client, req)
            except TikHubBalanceExhausted:
                raise                                   # 余额耗尽不重试
            except TikHubError as e:
                last = e
                logger.info(
                    "[tikhub-search] %s page attempt %d/%d failed: %s",
                    self.platform, attempt, PAGE_RETRIES, e.reason,
                )
                if attempt < PAGE_RETRIES:
                    time.sleep(_RETRY_SLEEP_S)
        assert last is not None
        raise last

    # ── SearchAdapter Protocol ─────────────────────────────────────────
    def search(
        self,
        keyword: str,
        target_count: int,
        on_card: OnCard,
        on_progress: OnProgress,
        cancel_event: threading.Event,
        max_attempts: int | None = None,
        filters: dict[str, Any] | None = None,
    ) -> SearchOutcome:
        target = max(1, min(int(target_count), HARD_CAP))
        plat_filters = (filters or {}).get(self.platform) or {}
        max_pages = min(MAX_PAGES, int(max_attempts)) if max_attempts else MAX_PAGES

        def _fail(reason: str, emitted: int, pages: int = 0) -> SearchOutcome:
            on_progress(ProgressUpdate(
                platform=self.platform, phase="failed", got=emitted, target=target, note=reason[:120],
            ))
            suffix = f"（已抓 {pages} 页）" if pages else ""
            return SearchOutcome(
                platform=self.platform, status="failed", cards_emitted=emitted,
                error_message=f"TikHub 搜索失败{suffix}：{reason}",
            )

        if balance_exhausted():
            return _fail("TikHub 余额不足（本轮短路，未发请求）", 0)
        try:
            client = self._cf()
        except Exception as e:                           # 缺 key / 配置损坏 → 记失败，不抛
            return _fail(str(getattr(e, "reason", e)), 0)

        on_progress(ProgressUpdate(platform=self.platform, phase="scrolling", got=0, target=target))
        emitted = 0
        pages = 0
        seen: set[str] = set()
        req = self.spec.first_request(keyword, plat_filters)
        try:
            while emitted < target and pages < max_pages:
                if cancel_event.is_set():
                    return SearchOutcome(platform=self.platform, status="cancelled", cards_emitted=emitted)
                raw = self._call_with_retry(client, req)
                pages += 1
                for card in self.spec.normalize(raw, plat_filters):
                    if emitted >= target:
                        break
                    if card.platform_video_id in seen:
                        continue
                    seen.add(card.platform_video_id)
                    emitted += 1
                    card.rank_in_search = emitted
                    on_card(card)
                on_progress(ProgressUpdate(
                    platform=self.platform, phase="scrolling", got=emitted, target=target,
                ))
                nxt = self.spec.next_request(req, raw)
                if nxt is None:
                    break
                req = nxt
        except TikHubError as e:
            return _fail(e.reason, emitted, pages)

        if cancel_event.is_set():
            return SearchOutcome(platform=self.platform, status="cancelled", cards_emitted=emitted)
        on_progress(ProgressUpdate(platform=self.platform, phase="done", got=emitted, target=target))
        return SearchOutcome(platform=self.platform, status="done", cards_emitted=emitted)


def build_tikhub_search_adapters(get_config, key_reader) -> dict[str, TikHubSearchAdapter]:
    """构造 {platform: adapter}。与 monitor.tikhub.build_api_adapters 同款注入方式：
    get_config() -> AppConfig（取 monitor.tikhub_base_url）；key_reader("tikhub", cfg) -> key。
    key 为空时 factory 抛 TikHubError，适配器捕获后记 failed（永不异常穿透）。"""
    def client_factory() -> TikHubClient:
        cfg = get_config()
        key = (key_reader("tikhub", cfg) or "").strip()
        if not key:
            raise TikHubError("未配置 TikHub API Key，请到设置页粘贴")
        return TikHubClient(base_url=cfg.monitor.tikhub_base_url, api_key=key)

    return {
        "douyin": TikHubSearchAdapter(DOUYIN_SEARCH_SPEC, client_factory),
        "bilibili": TikHubSearchAdapter(BILIBILI_SEARCH_SPEC, client_factory),
        "kuaishou": TikHubSearchAdapter(KUAISHOU_SEARCH_SPEC, client_factory),
    }
```

- [ ] **Step 4: 跑适配器测试确认通过**

Run: `pytest sidecar/tests/tikhub/test_search_adapter.py -q`
Expected: 12 PASS

- [ ] **Step 5: Commit**

```bash
git add csm_core/mining/platforms/tikhub_search.py sidecar/tests/tikhub/test_search_adapter.py
git commit -m "feat(mining): TikHubSearchAdapter（每页重试/硬顶80/翻页硬闸/402闩/取消）+ 三平台 spec"
```

---

### Task 7: runner 按 `mining_data_source_mode` 分派

**Files:**
- Modify: `csm_core/mining/runner.py:67-74`（`get_adapter`）、`:97-120`（`run()` 取 adapter 处）
- Test: `sidecar/tests/tikhub/test_search_dispatch.py`

- [ ] **Step 1: 写失败测试（新建文件）**

```python
"""runner.get_adapter 按 mining_data_source_mode 分派：tikhub_api → TikHubSearchAdapter；local → 浏览器适配器。"""
import pytest

from csm_core.mining import runner
from csm_core.mining.platforms.bilibili_search import BilibiliSearchAdapter
from csm_core.mining.platforms.douyin_search import DouyinSearchAdapter
from csm_core.mining.platforms.kuaishou_search import KuaishouSearchAdapter
from csm_core.mining.platforms.tikhub_search import TikHubSearchAdapter


@pytest.mark.parametrize("platform", ["douyin", "bilibili", "kuaishou"])
def test_tikhub_mode_returns_tikhub_adapter(platform, settings_path):
    a = runner.get_adapter(platform, "tikhub_api")
    assert isinstance(a, TikHubSearchAdapter) and a.platform == platform


def test_local_mode_returns_browser_adapters(settings_path):
    assert isinstance(runner.get_adapter("douyin", "local"), DouyinSearchAdapter)
    assert isinstance(runner.get_adapter("bilibili", "local"), BilibiliSearchAdapter)
    assert isinstance(runner.get_adapter("kuaishou", "local"), KuaishouSearchAdapter)


def test_default_mode_is_tikhub(settings_path):
    assert isinstance(runner.get_adapter("douyin"), TikHubSearchAdapter)


def test_unknown_platform_raises_in_both_modes(settings_path):
    with pytest.raises(ValueError):
        runner.get_adapter("xhs", "tikhub_api")
    with pytest.raises(ValueError):
        runner.get_adapter("xhs", "local")


def test_data_source_mode_reads_config(settings_path, monkeypatch):
    from csm_sidecar.services import config_service
    config_service.patch({"mining_data_source_mode": "local"})
    assert runner._data_source_mode() == "local"
    config_service.patch({"mining_data_source_mode": "tikhub_api"})
    assert runner._data_source_mode() == "tikhub_api"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest sidecar/tests/tikhub/test_search_dispatch.py -q`
Expected: FAIL —— `TypeError: get_adapter() takes 1 positional argument` / `AttributeError: _data_source_mode`

- [ ] **Step 3: 修改 `runner.py` —— 替换 `get_adapter`，新增 `_data_source_mode`**

把现有 `def get_adapter(platform: Platform) -> SearchAdapter:` 整个函数替换为：

```python
def _data_source_mode() -> str:
    """每次 run 现读 settings.json（get_config 无缓存），用户改了开关下个任务生效。
    读不到 → 走 tikhub_api（与 AppConfig 默认一致）。"""
    try:
        from csm_core.config import get_config

        mode = str(getattr(get_config(), "mining_data_source_mode", "") or "")
        return mode if mode in ("tikhub_api", "local") else "tikhub_api"
    except Exception:
        logger.info("[runner] config read failed, defaulting mining data source to tikhub_api", exc_info=True)
        return "tikhub_api"


def get_adapter(platform: Platform, mode: str = "tikhub_api") -> SearchAdapter:
    """按数据源模式选适配器：tikhub_api → TikHub 付费搜索（免登录）；local → 浏览器（兜底）。"""
    if mode == "tikhub_api":
        from csm_core.config import get_config, read_api_key
        from csm_core.mining.platforms.tikhub_search import build_tikhub_search_adapters

        adapters = build_tikhub_search_adapters(get_config, read_api_key)
        if platform in adapters:
            return adapters[platform]
        raise ValueError(f"unknown platform: {platform}")
    if platform == "bilibili":
        return BilibiliSearchAdapter()
    if platform == "kuaishou":
        return KuaishouSearchAdapter()
    if platform == "douyin":
        return DouyinSearchAdapter()
    raise ValueError(f"unknown platform: {platform}")
```

然后在 `run()` 里，把

```python
        prefilter_top_n, prefilter_threshold = _prefilter_params()
```

改为

```python
        prefilter_top_n, prefilter_threshold = _prefilter_params()
        data_source_mode = _data_source_mode()
```

把

```python
            adapter = get_adapter(platform)
```

改为

```python
            adapter = get_adapter(platform, data_source_mode)
```

- [ ] **Step 4: 跑分派测试 + 既有 mining 测试确认无回归**

Run: `pytest sidecar/tests/tikhub/test_search_dispatch.py sidecar/tests/ -q -k "dispatch or mining or runner"`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add csm_core/mining/runner.py sidecar/tests/tikhub/test_search_dispatch.py
git commit -m "feat(mining): runner 按 mining_data_source_mode 分派 TikHub / 浏览器适配器"
```

---

### Task 8: 前端 —— 平台卡「TikHub 就绪」+ 任务弹窗默认全选

**Files:**
- Modify: `frontend/src/components/mining/PlatformPickerCard.vue`
- Modify: `frontend/src/components/mining/StartJobModal.vue:12-36`、`:78-92`、`:221-228`
- Modify: `frontend/src/views/MiningView.vue`（传 `tikhubMode`）

- [ ] **Step 1: `PlatformPickerCard.vue` —— 加 `tikhubMode` prop，改点击/透明度/状态行**

把 `defineProps` 改为：

```ts
const props = defineProps<{
  platform: Platform;
  picked: boolean;
  loggedIn: boolean;
  /** 采集走 TikHub 付费搜索：不需要登录，卡片恒可选、状态行显示「TikHub 就绪」。 */
  tikhubMode?: boolean;
}>();
```

在 `<script setup>` 末尾（`const meta = ...` 之后）加：

```ts
const usable = () => props.tikhubMode || props.loggedIn;
```

模板里三处替换：

```vue
    @click="usable() ? $emit('toggle') : $emit('login')"
```

```vue
      opacity: usable() ? 1 : 0.62,
```

状态行整段替换为：

```vue
    <div
      class="text-[10.5px] mt-2 flex items-center gap-1"
      :style="{ color: usable() ? 'var(--green-deep)' : 'var(--red)' }"
    >
      <template v-if="tikhubMode">
        <Icon name="check" :size="10"/> TikHub 就绪
      </template>
      <template v-else-if="loggedIn">
        <Icon name="check" :size="10"/> 已登录
      </template>
      <template v-else>
        <Icon name="lock" :size="10"/> 未登录
      </template>
    </div>
```

- [ ] **Step 2: `StartJobModal.vue` —— 加 prop、默认勾选、透传**

`defineProps` 里加一个字段（保留原有字段）：

```ts
  /** 采集走 TikHub：三平台默认全选，不看登录态。 */
  tikhubMode?: boolean;
```

把 `picked` 初始化改为：

```ts
const pickAll = () => ({
  bilibili: props.tikhubMode || !!props.loginStatus.bilibili,
  douyin: props.tikhubMode || !!props.loginStatus.douyin,
  kuaishou: props.tikhubMode || !!props.loginStatus.kuaishou,
});
const picked = ref<Record<Platform, boolean>>(pickAll());
```

原来"重新按当前 loginStatus 自动勾选"的 `watch` 里，赋值三行改为 `picked.value = pickAll();`（保留 watch 的触发条件不动）。

模板 `<PlatformPickerCard` 加一个属性：

```vue
              :tikhub-mode="!!tikhubMode"
```

- [ ] **Step 3: `MiningView.vue` —— 从 config store 算 `tikhubMode` 并传给弹窗**

先定位：`grep -n "<StartJobModal\|useConfig\|import { use" frontend/src/views/MiningView.vue`。

在 `<script setup>` 的 import 区加（若已 import `useConfig` 则跳过）：

```ts
import { useConfig } from "@/stores/config";
```

在 store 实例化区加：

```ts
const cfg = useConfig();
const tikhubMode = computed(
  () => ((cfg.data as any)?.mining_data_source_mode ?? "tikhub_api") === "tikhub_api",
);
onMounted(() => { if (!cfg.data) void cfg.load(); });
```

（`computed` / `onMounted` 若未 import 则加进现有 `from "vue"` 的 import。）

`<StartJobModal` 标签加：

```vue
      :tikhub-mode="tikhubMode"
```

- [ ] **Step 4: 类型检查**

Run（PowerShell，`frontend/` 目录）: `npx vue-tsc --noEmit`
Expected: 0 errors

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/mining/PlatformPickerCard.vue frontend/src/components/mining/StartJobModal.vue frontend/src/views/MiningView.vue
git commit -m "feat(mining-ui): TikHub 模式平台卡显示「TikHub 就绪」且默认全选，不依赖登录态"
```

---

### Task 9: 前端 —— 设置页「采集走 TikHub」开关

**Files:**
- Modify: `frontend/src/views/SettingsView.vue:1443-1454`（监测 section「抓取数据源」块）

- [ ] **Step 1: 在监测 section 的「付费 API 抓取（TikHub）」`SettingsRow` 之后插入一行**

定位：`grep -n 'label="付费 API 抓取（TikHub）"' frontend/src/views/SettingsView.vue`，找到该 `<SettingsRow ...> ... </SettingsRow>` 的结束标签，在其后插入：

```vue
            <SettingsRow
              label="采集（找视频）走 TikHub 付费搜索"
              hint="开 = 关键词搜视频三平台走 TikHub（免登录、免并发风控，$0.01/次，每次约 6–14 条，单平台上限 80 条/次）；关 = 本地浏览器采集（需登录，作兜底）"
            >
              <FormToggle
                :model-value="(get('mining_data_source_mode') ?? 'tikhub_api') === 'tikhub_api'"
                @update:model-value="(v) => setField('mining_data_source_mode', v ? 'tikhub_api' : 'local')"
              />
            </SettingsRow>
```

- [ ] **Step 2: 让 TikHub Key 输入块在**任一**开关开启时都显示**

把 `<template v-if="get('monitor.data_source_mode') === 'tikhub_api'">` 改为：

```vue
            <template v-if="get('monitor.data_source_mode') === 'tikhub_api' || (get('mining_data_source_mode') ?? 'tikhub_api') === 'tikhub_api'">
```

- [ ] **Step 3: 类型检查**

Run（PowerShell，`frontend/`）: `npx vue-tsc --noEmit`
Expected: 0 errors

- [ ] **Step 4: Commit**

```bash
git add frontend/src/views/SettingsView.vue
git commit -m "feat(settings): 采集数据源开关（TikHub 付费搜索 ⇄ 浏览器兜底）"
```

---

### Task 10: 腾讯文档 —— `build_column_map_auto()` 按「评论X」惯例发现列

**Files:**
- Modify: `csm_core/sync/tencent_docs/sheet.py`（`build_column_map` 之后追加）
- Modify: `csm_core/sync/tencent_docs/__init__.py`（导出）
- Test: `sidecar/tests/test_tencent_docs_sync.py`（追加）

- [ ] **Step 1: 追加失败测试（放在 `# ── build_column_map` 区块末尾）**

```python
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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest sidecar/tests/test_tencent_docs_sync.py -q -k column_map_auto`
Expected: FAIL —— `ImportError: cannot import name 'build_column_map_auto'`

- [ ] **Step 3: 在 `sheet.py` 的 `build_column_map` 之后追加**

```python
# ── 表头惯例自动发现（2026-09-01 用户拍板的列命名）──────────────────────
# 评论A / 评论B / … → tier1 / tier2 / …；评论A的图片 / 评论A图片 → img1 / …
# 层数由表头实际有几列决定（不再硬顶 3 层）。链接列容忍 链接/视频链接/文章链接。
_TIER_RE = re.compile(r"^评论([A-Za-z])$")
_IMG_RE = re.compile(r"^评论([A-Za-z])的?图片$")
_ALIASES: dict[str, tuple[str, ...]] = {
    "url": ("链接", "视频链接", "文章链接"),
    "seq": ("序号",),
    "date": ("日期", "任务日期"),
}
_REQUIRED_KEYS = ("url", "tier1")


def _letter_to_tier(ch: str) -> int:
    return ord(ch.upper()) - ord("A") + 1


def build_column_map_auto(header: list[str], col_names: dict[str, str]) -> ColumnMap:
    """先按配置列名精确匹配（`build_column_map`），再按表头惯例自动发现补齐。

    发现规则（去空白、字母不分大小写）：``评论X`` → ``tierN``、``评论X的图片`` /
    ``评论X图片`` → ``imgN``（X=A→1、B→2…），``链接/视频链接/文章链接`` → ``url``，
    ``序号`` → ``seq``，``日期/任务日期`` → ``date``。精确匹配优先（不覆盖）。
    ``missing`` 只报必需列（url、tier1）—— 可选列缺失不算错。
    """
    cmap = build_column_map(header, col_names)
    for i, h in enumerate(header):
        name = _WS_RE.sub("", h or "")
        if not name:
            continue
        m = _TIER_RE.match(name)
        if m:
            cmap.by_key.setdefault(f"tier{_letter_to_tier(m.group(1))}", i)
            continue
        m = _IMG_RE.match(name)
        if m:
            cmap.by_key.setdefault(f"img{_letter_to_tier(m.group(1))}", i)
            continue
        for key, names in _ALIASES.items():
            if key not in cmap.by_key and name in names:
                cmap.by_key[key] = i
                break
    cmap.missing = [k for k in _REQUIRED_KEYS if k not in cmap.by_key]
    return cmap


def max_tier(cmap: ColumnMap) -> int:
    """表头里最深的评论层（tierN 的最大 N）；没有 → 0。"""
    return max(
        (int(k[4:]) for k in cmap.by_key if k.startswith("tier") and k[4:].isdigit()),
        default=0,
    )
```

- [ ] **Step 4: 在 `csm_core/sync/tencent_docs/__init__.py` 导出**

查看现有导出：`grep -n "build_column_map\|__all__\|^from .sheet import" csm_core/sync/tencent_docs/__init__.py`。在 `from .sheet import (...)` 列表里加上 `build_column_map_auto, max_tier,`（若有 `__all__` 也加上这两个名字）。

- [ ] **Step 5: 跑测试确认通过（含既有 column_map 测试）**

Run: `pytest sidecar/tests/test_tencent_docs_sync.py -q -k column_map`
Expected: 全部 PASS

- [ ] **Step 6: Commit**

```bash
git add csm_core/sync/tencent_docs/sheet.py csm_core/sync/tencent_docs/__init__.py sidecar/tests/test_tencent_docs_sync.py
git commit -m "feat(tdocs): build_column_map_auto —— 按「评论X/评论X的图片」表头惯例自动对列，层数由表头决定"
```

---

### Task 11: 腾讯文档 —— 同步/测试连接改用 auto 映射，层数动态

**Files:**
- Modify: `sidecar/csm_sidecar/services/tencent_docs_service.py`（`_load_sheet_state`、`sync_approved` 层数、`test_connection`）
- Test: `sidecar/tests/test_tencent_docs_sync.py`（追加）

- [ ] **Step 1: 追加失败测试（放在 `test_sync_approved_writes_rows_and_marks_synced` 之后）**

```python
_CONVENTION_HEADER = ["视频链接", "评论A", "评论A的图片", "评论B", "评论C", "评论D"]


def test_sync_convention_header_writes_four_tiers(monitor_db, settings_path, monkeypatch):
    """用户表头惯例：视频链接 + 评论A..D（无 序号/日期）→ 四层全写入，不再截到 3 层。"""
    config_service.patch({"tencent_docs": {
        "enabled": True,
        "doc_url": "https://docs.qq.com/sheet/D123?tab=BB08J2",
    }})
    monkeypatch.setattr(tds, "read_api_key", lambda p, c=None: "tok")
    fake = FakeSheetClient([list(_CONVENTION_HEADER)])
    monkeypatch.setattr(tds, "_client_factory", lambda token: fake)
    _seed_video_with_comments(1, "https://www.douyin.com/video/111",
                              ["一楼", "二楼", "三楼", "四楼"], images_on={1})

    result = tds.sync_approved()
    assert result["synced_videos"] == 1
    assert result["synced_comments"] == 4
    assert result["skipped_extra_tiers"] == 0
    row = fake.rows[1]
    assert row[0] == "标题1 https://www.douyin.com/video/111"   # 视频链接（别名）
    assert row[1] == "一楼" and row[2] == "有图，另发"
    assert row[3] == "二楼" and row[4] == "三楼" and row[5] == "四楼"
    monkeypatch.setattr(tds, "_client_factory", None)


def test_sync_skips_tiers_deeper_than_header(monitor_db, settings_path, monkeypatch):
    config_service.patch({"tencent_docs": {
        "enabled": True,
        "doc_url": "https://docs.qq.com/sheet/D123?tab=BB08J2",
    }})
    monkeypatch.setattr(tds, "read_api_key", lambda p, c=None: "tok")
    fake = FakeSheetClient([["链接", "评论A", "评论B"]])
    monkeypatch.setattr(tds, "_client_factory", lambda token: fake)
    _seed_video_with_comments(1, "https://www.douyin.com/video/111", ["一楼", "二楼", "三楼"])

    result = tds.sync_approved()
    assert result["skipped_extra_tiers"] == 1          # 第 3 层没列，留在 app 内
    assert result["synced_comments"] == 2
    monkeypatch.setattr(tds, "_client_factory", None)


def test_test_connection_reports_tiers_detected(monitor_db, settings_path, monkeypatch):
    config_service.patch({"tencent_docs": {
        "enabled": True,
        "doc_url": "https://docs.qq.com/sheet/D123?tab=BB08J2",
    }})
    monkeypatch.setattr(tds, "read_api_key", lambda p, c=None: "tok")
    fake = FakeSheetClient([list(_CONVENTION_HEADER)])
    monkeypatch.setattr(tds, "_client_factory", lambda token: fake)
    out = tds.test_connection()
    assert out["ok"] is True and out["missing"] == []
    assert all(p["tiers_detected"] == 4 for p in out["sheets"])
    monkeypatch.setattr(tds, "_client_factory", None)


def test_test_connection_missing_required_uses_friendly_labels(monitor_db, settings_path, monkeypatch):
    config_service.patch({"tencent_docs": {
        "enabled": True,
        "doc_url": "https://docs.qq.com/sheet/D123?tab=BB08J2",
    }})
    monkeypatch.setattr(tds, "read_api_key", lambda p, c=None: "tok")
    fake = FakeSheetClient([["发布类型", "平台", "文章标题"]])
    monkeypatch.setattr(tds, "_client_factory", lambda token: fake)
    out = tds.test_connection()
    assert out["ok"] is False
    assert any("视频链接" in m for m in out["missing"])
    assert any("评论A" in m for m in out["missing"])
    monkeypatch.setattr(tds, "_client_factory", None)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest sidecar/tests/test_tencent_docs_sync.py -q -k "convention or deeper or tiers_detected or friendly"`
Expected: FAIL（`KeyError: 'tiers_detected'` / 四层被截 / 缺列标签不对）

- [ ] **Step 3: 修改 `tencent_docs_service.py`**

(a) import 改为（把 `build_column_map` 换成 auto 版并加 `max_tier`）：

```python
from csm_core.sync.tencent_docs import (
    ColumnMap,
    SheetTarget,
    TencentDocsError,
    TencentDocsMCPClient,
    TokenInvalidError,
    append_rows_csv,
    build_column_map_auto,
    list_sheets,
    max_tier,
    paint_row_background,
    parse_doc_url,
    pick_fallback_sheet,
    pick_sheet_by_name,
    read_column_texts,
    read_row_texts,
)
```

(b) 删除 `_MAX_TIERS = 3` 那行，在其位置加必需列的友好标签：

```python
# 必需列缺失时给用户看的名字（同时列出旧惯例与新惯例）
_REQUIRED_LABELS = {
    "url": "链接（或 视频链接 / 文章链接）",
    "tier1": "评论A（或 内容一）",
}
```

(c) `_load_sheet_state` 改为：

```python
def _load_sheet_state(
    client: TencentDocsMCPClient, target: SheetTarget, col_names: dict[str, str],
) -> _SheetState:
    header = read_row_texts(client, target, 0)
    cmap = build_column_map_auto(header, col_names)
    if cmap.missing:
        names = "、".join(_REQUIRED_LABELS.get(k, k) for k in cmap.missing)
        raise TencentDocsError(
            f"子表「{target.sheet_name}」里找不到必需列：{names}"
            "（检查表头：需要 链接 列和 评论A 列）"
        )
    existing = read_column_texts(client, target, cmap.col("url"))
    last_used = max(existing.keys()) if existing else 0  # 表头行兜底
    return _SheetState(
        target=target,
        cmap=cmap,
        header=header,
        existing_blob="\n".join(existing.values()),
        next_row=last_used + 1,
    )
```

(d) `test_connection` 里 `_check` 改用 `build_column_map_auto`，`per_platform` 追加 `tiers_detected`，`missing` 用友好标签：

```python
        def _check(target: SheetTarget) -> tuple[list[str], ColumnMap]:
            if target.sheet_id not in header_cache:
                header = read_row_texts(client, target, 0)
                header_cache[target.sheet_id] = (
                    header, build_column_map_auto(header, td.col_map),
                )
            return header_cache[target.sheet_id]
```

```python
            per_platform.append({
                "platform": platform,
                "platform_label": _PLATFORM_LABEL[platform],
                "sheet_name": target.sheet_name,
                "matched_by_name": named is not None,
                "missing": [_REQUIRED_LABELS.get(k, k) for k in cmap.missing],
                "tiers_detected": max_tier(cmap),
            })
```

(e) `sync_approved` 里两处 `_MAX_TIERS` 改为动态。在 `cmap = state.cmap` 之后加：

```python
            tiers_available = max_tier(cmap)
```

把防双写分支里的

```python
                        c["id"] for c in item["comments"] if c["tier"] <= _MAX_TIERS
```

改为

```python
                        c["id"] for c in item["comments"] if c["tier"] <= tiers_available
```

把写行循环里的

```python
                    if c["tier"] > _MAX_TIERS:
                        # 表格只有三层结构；更深楼层留在 app 内（保持 approved）。
```

改为

```python
                    if c["tier"] > tiers_available:
                        # 表头没有这一层的「评论X」列；更深楼层留在 app 内（保持 approved）。
```

(f) 模块 docstring 里「盖楼上限 3 层」一句改为「层数 = 表头里 评论X 列的数量（build_column_map_auto 发现）」。

- [ ] **Step 4: 跑腾讯文档全部测试确认通过（旧 `_USER_HEADER` 用例零回归）**

Run: `pytest sidecar/tests/test_tencent_docs_sync.py -q`
Expected: 38 PASS

- [ ] **Step 5: Commit**

```bash
git add sidecar/csm_sidecar/services/tencent_docs_service.py sidecar/tests/test_tencent_docs_sync.py
git commit -m "feat(tdocs): 同步/测试连接改用惯例自动对列，写入层数由表头 评论X 列数决定"
```

---

### Task 12: 生成层数上限 3 → 5（与「评论A–E」对齐）

**Files:**
- Modify: `sidecar/csm_sidecar/services/comment_generation_service.py:69`
- Modify: `sidecar/csm_sidecar/routes/mining.py:581`
- Modify: `frontend/src/components/mining/GenerateBatchModal.vue:71`
- Test: `sidecar/tests/`（现有生成测试；追加一条）

- [ ] **Step 1: 追加失败测试（找现有生成服务测试文件：`grep -ln "submit_batch\|comment_generation_service" sidecar/tests/*.py`，追加到该文件末尾）**

```python
def test_submit_batch_clamps_tiers_to_five():
    from csm_sidecar.services import comment_generation_service as cgs
    assert cgs._MAX_TIERS == 5
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest sidecar/tests/ -q -k clamps_tiers_to_five`
Expected: FAIL —— `assert 3 == 5`

- [ ] **Step 3: 三处改 5**

`comment_generation_service.py:69`：

```python
_MAX_TIERS = 5  # 评论A–E；腾讯文档实际写入层数由表头「评论X」列数决定（tencent_docs_service）
```

`routes/mining.py:581`：

```python
    tiers_per_video: int = Field(1, ge=1, le=5)   # 上限 5 = 评论A–E
```

`GenerateBatchModal.vue:71`：

```vue
          v-for="n in [1, 2, 3, 4, 5]" :key="n"
```

- [ ] **Step 4: 跑测试 + 类型检查**

Run: `pytest sidecar/tests/ -q -k "generation or clamps"`
Expected: PASS
Run（PowerShell，`frontend/`）: `npx vue-tsc --noEmit`
Expected: 0 errors

- [ ] **Step 5: Commit**

```bash
git add sidecar/csm_sidecar/services/comment_generation_service.py sidecar/csm_sidecar/routes/mining.py frontend/src/components/mining/GenerateBatchModal.vue sidecar/tests/
git commit -m "feat(mining): 评论生成层数上限 3→5（对齐腾讯文档 评论A–E 列）"
```

---

### Task 13: CHANGELOG + 全量回归

**Files:**
- Modify: `CHANGELOG.md`

- [ ] **Step 1: 在 `CHANGELOG.md` 顶部标题行之后、第一个 `## ` 版本标题之前插入（若已有「未发布」段则并入其中，**不要覆盖任何版本标题**）**

```markdown
## [未发布]

### 新增
- **采集改走 TikHub 付费搜索**：关键词找视频三平台默认走 TikHub（免登录、免并发风控，$0.01/次、每次约 6–14 条、单平台上限 80 条/次）；设置页新增「采集走 TikHub」开关，浏览器采集保留为手动兜底。任务弹窗平台卡在 TikHub 模式显示「TikHub 就绪」并默认全选。
- **腾讯文档同步按表头惯例自动对列**：`评论A / 评论A的图片 / 评论B / 评论C / 评论D…` 自动映射为各层评论与配图，层数由表头决定；链接列兼容 `链接 / 视频链接 / 文章链接`。评论生成层数上限 3 → 5。

### 修复
- **腾讯文档「测试连接」报 `tool not found: sheet.get_sheet_info`**：工具名误加 `sheet.` 前缀，真服务工具名不带前缀（`get_sheet_info` 等），已去前缀；「测试连接」新增 `tools/list` 诊断，失败时列出服务端真实工具名。
```

- [ ] **Step 2: 全量 sidecar 测试**

Run: `pytest sidecar/tests/ -q`
Expected: 全部 PASS（0 failed）

- [ ] **Step 3: 全量前端检查（PowerShell，`frontend/`）**

Run: `npx vue-tsc --noEmit && npx vitest run`
Expected: 0 type errors；vitest 全绿

- [ ] **Step 4: Commit**

```bash
git add CHANGELOG.md
git commit -m "docs(changelog): 采集走 TikHub 搜索 + 腾讯文档惯例对列 + tool not found 修复"
```

---

### Task 14: 多 Agent 对抗性审查（用户全局规则，长期授权）

- [ ] **Step 1: 并行派 3 个独立 subagent（Agent 工具），各带一个视角，指令是「设法证伪、找出问题」：**
  1. **正确性**：三平台归一化字段路径 vs fixture；翻页终止条件（抖音 has_more / B站 numPages / 快手 no_more）；runner 分派与 `on_card` 管线不变量；腾讯文档 `build_column_map_auto` 与动态层数。
  2. **边界与回归**：`local` 模式浏览器路径零改动；402 闩 / 重试 / 硬顶 / 翻页硬闸的边界值；旧表头（内容一/盖楼内容二）用例不回归；前端 `tikhubMode` 未定义时的默认行为。
  3. **安全与成本**：日志绝不泄 key（POST 只记 body key 列表）；成本失控路径（重试 × 页数 × 平台）；`content_type=0` 综合搜索是否多计费；`mining_data_source_mode` 默认值对老用户的影响（首次升级即走付费）。
- [ ] **Step 2: 逐条核实审查发现；真问题修复后简要复审；误报说明理由。**
- [ ] **Step 3: 最终回复附审查结论（发现什么、修了什么、放行什么）。**

---

## 自检（写完计划后跑一遍）

**Spec 覆盖：** D1（三平台全走 TikHub）→ Task 6/7；D2（浏览器兜底开关）→ Task 2/7/9；D3（50/80）→ Task 6 `HARD_CAP`（默认 50 来自 `StartJobRequest.target_per_platform`）；D4（复用 key/base_url）→ Task 6 `build_tikhub_search_adapters`；D5（不回退）→ Task 6 `_fail`；§4.1 参数下推 → Task 3/4/5；§4.2 字段路径 → Task 3/4/5 + fixture；§5.2 POST+重试 → Task 1/6；§5.4 护栏 → Task 6；§5.5 UI → Task 8/9；§6 测试 → 各 Task；用户追加的「评论X」惯例 → Task 10/11/12。

**类型/命名一致性：** `build_tikhub_search_adapters` / `TikHubSearchAdapter` / `SearchSpec` / `HARD_CAP` / `MAX_PAGES` / `PAGE_RETRIES` / `_RETRY_SLEEP_S`（Task 6 定义，测试引用一致）；`douyin_first_body / douyin_next_body / normalize_douyin_search`、`bilibili_first_params / bilibili_next_params / normalize_bilibili_search`、`kuaishou_first_params / kuaishou_next_params / normalize_kuaishou_search`（Task 3/4/5 定义，Task 6 spec 引用一致）；`_data_source_mode` / `get_adapter(platform, mode)`（Task 7）；`build_column_map_auto` / `max_tier`（Task 10 定义，Task 11 引用）；`mining_data_source_mode`（Task 2 定义，Task 7/8/9 引用）。

**占位符扫描：** 无 TBD / "类似 Task N"；每个代码步骤都给了完整代码；Task 8 Step 3 / Task 9 Step 1 / Task 12 Step 1 用 `grep` 先定位是因为对应文件我未逐行读过，但要插入的代码已完整给出。


---

## Amendments（实现期修订，与正文冲突时**以此为准**）

### 修订 A（Tasks 3–5 审查后，已落 7a89be14）
- 快手终止判据改为 **pcursor 主判据**（缺失/空/"no_more"/与上页相同即停；`recoPcursor` 不作终止信号）；三平台 `*_next_*` 加游标不动点闸；非 dict 载荷防御（`_dict/_to_int`）；抖音 `type`/`has_more` 类型归一；B站计数 `parse_int_count` 兜底；内层错误码 `logger.warning`；`_VALID_ORDERS` 导入复用；`_DY` 单例；仅 `content_type=="0"` 时本地后过滤。
- 遗留两条一行加固并入 **Task 6 Step 0**（单独 commit）：快手 `duration` 走 `_to_int`；抖音不动点比较 `str()` 归一。

### 修订 B（Task 6 适配器，以实现者收到的代码为准）
1. 终止判据加「**整页都是重复卡**（cards 非空且 0 张新卡）→ 停」；**整页被本地过滤为空不停**（快手日期区间靠翻页补偿）。
2. 页级错误语义：**首页**失败 → `failed`；**已发出 ≥1 张卡后**的后续页失败 → `done` + note（`error_message` 与 progress note 同文，形如「第 N 页失败已停止：…」）。
3. `normalize` / `next_request` 包 try/except → 统一为页级错误（适配器层永不异常穿透）。
4. `max_attempts` 判 `is not None` 且 clamp 到 `[1, MAX_PAGES]`。
5. 每页 `logger.info` 记录游标字段（cursor/page/pcursor）与卡数，**不记 keyword**。
6. 测试相应新增：后页失败降 done、全重复页停、空过滤页不停、normalize 异常（首页→failed / 后页→done）、`max_attempts` 上限、页日志含游标不含 keyword。

### 修订 C（Task 7 分派）
1. `get_adapter(platform, mode=None)`：`mode is None` 时内部调 `_data_source_mode()`；`run()` 仍调 `get_adapter(platform)`（既有 `test_mining_runner.py` 七处单参 fake 不动）。
2. `csm_core.config.get_config()` 读 `default_config_path()`，**不受** `settings_path` fixture 影响 → Task 7 的 `_data_source_mode` 测试与分派测试改为 monkeypatch `csm_core.config.get_config`（runner 在函数内 import，patch 模块属性即生效），不再用 `config_service.patch`。
3. `run()` 里 adapter 抛异常的兜底：用 `_on_card` 计数报告已入库条数，不再写死 `got=0`。
