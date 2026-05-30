# AI 卡位监控（GEO）· 阶段 1 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 monitor 模块加 `geo_query` 任务类型，批量关键词 × {通义, Kimi} 两个 API 平台采集 AI 回答 + 信源，LLM 抽取出曝光度/首推率/情感/信源榜，监测中心建任务跑、数据中心看分析。

**Architecture:** 复用现有 monitor 基建（storage / monitor_loop / scheduler / SSE / 泛型路由）。新增 `csm_core/monitor/geo/` 子包：纯函数层（models / classify / metrics）+ provider 层（API 采集）+ extract 层（LLM 抽取）+ storage 层（v7 两张规范化表）。adapter（`platforms/geo_query.py`）把这些串成 fan-out 闭环。前端新增监测中心 tab + 数据中心 pivot 两个自包含组件。

**Tech Stack:** Python 3.11 / pydantic v2 / httpx / sqlite3 / pytest（`integration` marker 留给真实 API）；Vue 3 + TypeScript（vue-tsc 严格）+ Tauri。

**Spec:** `docs/superpowers/specs/2026-05-30-ai-geo-monitoring-design.md`

**前置约定（每个任务都遵守）:**
- 工作树 `.claude/worktrees/elated-bhaskara-1aeaf1`，分支 `claude/elated-bhaskara-1aeaf1`。
- core 测试从仓库根跑：`pytest tests/core/monitor/geo/<file> -v`。
- sidecar 测试：`pytest sidecar/tests/<file> -v`。
- Windows CI 下 print 只用 ASCII（项目教训）；测试断言里中文 OK，print 调试别用 emoji。
- 每个 Task 末尾 commit，message 用项目风格 `feat(geo): ...` / `test(geo): ...`，结尾加 `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`。

---

## 文件结构（阶段 1 新建/改动）

**新建（core）**
```
csm_core/monitor/geo/__init__.py
csm_core/monitor/geo/models.py        # Citation/GeoAnswer/RecommendedEntity/ClassifiedCitation/GeoExtraction/GeoCell
csm_core/monitor/geo/classify.py      # 域名规整 + source_type 规则表
csm_core/monitor/geo/metrics.py       # 四大 KPI 聚合（纯函数）
csm_core/monitor/geo/storage.py       # v7 DDL + apply_v7_migration + record_run + 聚合查询
csm_core/monitor/geo/extract.py       # GeoAnswer → GeoExtraction（LLM）
csm_core/monitor/geo/providers/__init__.py
csm_core/monitor/geo/providers/base.py    # GeoProvider Protocol + get_provider 注册表
csm_core/monitor/geo/providers/api_tongyi.py
csm_core/monitor/geo/providers/api_kimi.py
csm_core/monitor/platforms/geo_query.py   # GeoQueryAdapter + ADAPTER 单例
scripts/geo_api_probe.py              # Task 1：真实 API 信源探针
```
**改动（core）**
```
csm_core/monitor/base.py              # TaskType Literal += "geo_query"
csm_core/monitor/storage.py           # _SCHEMA_VERSION 6→7；_migrate 调 geo apply_v7_migration
csm_core/monitor/platforms/__init__.py# 注册 GEO 到 ALL
```
**改动（sidecar）**
```
sidecar/csm_sidecar/services/monitor_service.py   # PLATFORM_TYPES += "geo_query"
sidecar/csm_sidecar/routes/monitor.py             # GEO 只读聚合端点
```
**新建/改动（前端）**
```
frontend/src/utils/monitor-types.ts               # GeoTask/GeoKpi/Citation 类型
frontend/src/components/monitor/AddTaskModal.vue  # +geo_query 分支
frontend/src/components/monitor/geo/GeoTaskModule.vue        # 新建（监测中心 tab）
frontend/src/components/monitor/history/GeoAnalyticsPage.vue # 新建（数据中心 pivot）
frontend/src/views/MonitorView.vue                # +「AI 卡位」tab
frontend/src/views/DataCenterView.vue             # +「AI 卡位」sub-pivot
```
**测试**
```
tests/core/monitor/geo/__init__.py
tests/core/monitor/geo/test_models.py
tests/core/monitor/geo/test_classify.py
tests/core/monitor/geo/test_metrics.py
tests/core/monitor/geo/test_storage.py
tests/core/monitor/geo/test_extract.py
tests/core/monitor/geo/test_providers.py
tests/core/monitor/geo/test_geo_query_adapter.py
tests/core/monitor/geo/test_registration.py      # invariant
tests/core/monitor/geo/fixtures/tongyi_search.json
tests/core/monitor/geo/fixtures/kimi_search.json
sidecar/tests/test_geo_routes.py
```

---

## Task 1: API 信源探针（强制前置，产出真实 fixture）

**为什么先做：** 三家 API「联网 + 回信源」的字段格式有把握但非锁定。先用真实 key 打一炮，把真实响应存成 fixture，后面 provider 解析器对着它写。**实测某平台不回信源 → 记录到 spec §14，该平台阶段 3 降级 RPA。**

**Files:**
- Create: `scripts/geo_api_probe.py`
- Create: `tests/core/monitor/geo/fixtures/` (目录)

- [ ] **Step 1: 写探针脚本**

```python
# scripts/geo_api_probe.py
"""真实 API 信源探针 —— 手动运行，把响应存成 fixture。

用法（需真实 key）：
    DASHSCOPE_API_KEY=sk-xxx MOONSHOT_API_KEY=sk-yyy python scripts/geo_api_probe.py

输出：
    tests/core/monitor/geo/fixtures/tongyi_search.raw.json
    tests/core/monitor/geo/fixtures/kimi_search.raw.json

拿到后人工脱敏（去掉 key/request-id），裁剪成 fixtures/tongyi_search.json /
kimi_search.json，确认 search 结果（URL+标题）落在哪个字段。
"""
from __future__ import annotations
import json, os, sys
from pathlib import Path
import httpx

OUT = Path(__file__).resolve().parents[1] / "tests/core/monitor/geo/fixtures"
KEYWORD = "20万左右的新能源SUV推荐"


def probe_tongyi(key: str) -> dict:
    url = "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation"
    body = {
        "model": "qwen-plus",
        "input": {"messages": [{"role": "user", "content": KEYWORD}]},
        "parameters": {"enable_search": True,
                       "search_options": {"enable_source": True, "enable_citation": True},
                       "result_format": "message"},
    }
    r = httpx.post(url, headers={"Authorization": f"Bearer {key}"}, json=body, timeout=120)
    print("tongyi http", r.status_code, "len", len(r.text))
    return r.json()


def probe_kimi(key: str) -> dict:
    url = "https://api.moonshot.cn/v1/chat/completions"
    body = {
        "model": "moonshot-v1-8k",
        "messages": [{"role": "user", "content": KEYWORD}],
        "tools": [{"type": "builtin_function", "function": {"name": "$web_search"}}],
    }
    r = httpx.post(url, headers={"Authorization": f"Bearer {key}"}, json=body, timeout=120)
    print("kimi http", r.status_code, "len", len(r.text))
    return r.json()


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    dk = os.environ.get("DASHSCOPE_API_KEY", "")
    mk = os.environ.get("MOONSHOT_API_KEY", "")
    if dk:
        (OUT / "tongyi_search.raw.json").write_text(
            json.dumps(probe_tongyi(dk), ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        print("skip tongyi: no DASHSCOPE_API_KEY")
    if mk:
        (OUT / "kimi_search.raw.json").write_text(
            json.dumps(probe_kimi(mk), ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        print("skip kimi: no MOONSHOT_API_KEY")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: 运行探针（有 key 时）**

Run: `python scripts/geo_api_probe.py`（设好 `DASHSCOPE_API_KEY` / `MOONSHOT_API_KEY`）
Expected: 打印两行 `http 200 len ...`，生成 `*.raw.json`。

> **无 key 时**：跳过运行，直接用 Step 3 的「文档预期形状」fixture，并在 PR 描述里标注「fixture 来自 API 文档预期、待真实 key 校准」。

- [ ] **Step 3: 落 fixture（脱敏 + 裁剪）**

把真实响应脱敏裁剪为下面两个 fixture（无 key 时直接用这两份预期形状）：

`tests/core/monitor/geo/fixtures/tongyi_search.json`
```json
{
  "output": {
    "choices": [{"message": {"role": "assistant",
      "content": "20万左右的新能源SUV，比较推荐比亚迪宋PLUS、小鹏G6、深蓝S7。其中小鹏G6智驾突出……"}}],
    "search_info": {"search_results": [
      {"index": 1, "title": "2024新能源SUV推荐", "url": "https://zhuanlan.zhihu.com/p/123456", "site_name": "知乎"},
      {"index": 2, "title": "小鹏G6实测", "url": "https://www.xiaohongshu.com/explore/abc", "site_name": "小红书"},
      {"index": 3, "title": "比亚迪宋PLUS官网", "url": "https://www.bydauto.com.cn/song-plus", "site_name": "比亚迪"}
    ]}
  },
  "usage": {"total_tokens": 512},
  "request_id": "REDACTED"
}
```

`tests/core/monitor/geo/fixtures/kimi_search.json`
```json
{
  "choices": [{"index": 0, "finish_reason": "stop", "message": {
    "role": "assistant",
    "content": "推荐小鹏G6、特斯拉Model Y、比亚迪宋PLUS……[1][2]",
    "annotations": [
      {"type": "url_citation", "url_citation": {"url": "https://www.zhihu.com/question/600", "title": "新能源SUV怎么选 - 知乎"}},
      {"type": "url_citation", "url_citation": {"url": "https://www.xiaohongshu.com/explore/def", "title": "小鹏G6车主体验 - 小红书"}}
    ]}}],
  "usage": {"total_tokens": 880}
}
```

> **关键产出**：确认 ① 通义信源在 `output.search_info.search_results[]`（含 `url`/`title`）；② Kimi 信源在 `choices[0].message.annotations[].url_citation`。真实形状不同就改这两份 fixture + 对应解析器（Task 6/7）。

- [ ] **Step 4: Commit**

```bash
git add scripts/geo_api_probe.py tests/core/monitor/geo/fixtures/
git commit -m "feat(geo): API 信源探针脚本 + 通义/Kimi 响应 fixture"
```

---

## Task 2: GEO 数据模型（models.py）

**Files:**
- Create: `csm_core/monitor/geo/__init__.py`（空文件）
- Create: `csm_core/monitor/geo/models.py`
- Test: `tests/core/monitor/geo/__init__.py`（空）, `tests/core/monitor/geo/test_models.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/core/monitor/geo/test_models.py
from csm_core.monitor.geo.models import (
    Citation, GeoAnswer, RecommendedEntity, ClassifiedCitation, GeoExtraction, GeoCell,
)


def test_geo_answer_defaults():
    a = GeoAnswer(platform="tongyi", keyword="新能源SUV", answer_text="…")
    assert a.status == "ok"
    assert a.citations == []
    assert a.raw == {}


def test_geo_extraction_roundtrip():
    e = GeoExtraction(
        mentioned=True, target_rank=2, sentiment="pos",
        recommended=[RecommendedEntity(name="小鹏", position=2, is_target=True)],
        citations=[ClassifiedCitation(url="https://zhihu.com/x", title="t", domain="zhihu.com", source_type="知乎")],
        summary="评价正面",
    )
    assert e.recommended[0].is_target is True
    assert e.citations[0].source_type == "知乎"


def test_geo_cell_carries_everything():
    c = GeoCell(platform="kimi", keyword="新能源SUV", mentioned=False, rank=-1,
                sentiment="na", answer_text="", status="empty", raw={}, citations=[])
    assert c.rank == -1
    assert c.mentioned is False
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/core/monitor/geo/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError: csm_core.monitor.geo`

- [ ] **Step 3: 写实现**

```python
# csm_core/monitor/geo/models.py
"""GEO 卡位监控数据模型。

分层：
- Citation / GeoAnswer  —— provider 采集层输出（原始信源 + 完整回答）
- RecommendedEntity / ClassifiedCitation / GeoExtraction —— 抽取层输出
- GeoCell —— 一个 (关键词,平台) cell 的最终聚合单元，写入 geo_cells/geo_citations
"""
from __future__ import annotations
from typing import Any, Literal
from pydantic import BaseModel, Field

Sentiment = Literal["pos", "neu", "neg", "na"]
AnswerStatus = Literal["ok", "empty", "blocked", "error"]


class Citation(BaseModel):
    url: str
    title: str = ""


class GeoAnswer(BaseModel):
    platform: str
    keyword: str
    answer_text: str = ""
    citations: list[Citation] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)
    status: AnswerStatus = "ok"
    error: str = ""


class RecommendedEntity(BaseModel):
    name: str
    position: int           # 1-based
    is_target: bool = False


class ClassifiedCitation(BaseModel):
    url: str
    title: str = ""
    domain: str = ""
    source_type: str = "其他"


class GeoExtraction(BaseModel):
    mentioned: bool = False
    target_rank: int = -1   # -1 = 未提及/未进推荐列表
    sentiment: Sentiment = "na"
    recommended: list[RecommendedEntity] = Field(default_factory=list)
    citations: list[ClassifiedCitation] = Field(default_factory=list)
    summary: str = ""


class GeoCell(BaseModel):
    platform: str
    keyword: str
    mentioned: bool = False
    rank: int = -1
    sentiment: Sentiment = "na"
    answer_text: str = ""
    status: str = "ok"      # 沿用 AnswerStatus 值域；cell 还可记 'error'
    raw: dict[str, Any] = Field(default_factory=dict)
    citations: list[ClassifiedCitation] = Field(default_factory=list)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/core/monitor/geo/test_models.py -v`
Expected: PASS（3 passed）

- [ ] **Step 5: Commit**

```bash
git add csm_core/monitor/geo/__init__.py csm_core/monitor/geo/models.py tests/core/monitor/geo/
git commit -m "feat(geo): 数据模型 Citation/GeoAnswer/GeoExtraction/GeoCell"
```

---

## Task 3: 信源域名分类（classify.py）

**Files:**
- Create: `csm_core/monitor/geo/classify.py`
- Test: `tests/core/monitor/geo/test_classify.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/core/monitor/geo/test_classify.py
from csm_core.monitor.geo.models import Citation
from csm_core.monitor.geo.classify import registered_domain, classify_source, classify_citations


def test_registered_domain_strips_subdomain():
    assert registered_domain("https://zhuanlan.zhihu.com/p/123") == "zhihu.com"
    assert registered_domain("https://www.xiaohongshu.com/explore/abc") == "xiaohongshu.com"
    assert registered_domain("http://mp.weixin.qq.com/s/xxx") == "qq.com"
    assert registered_domain("not a url") == ""


def test_classify_source_rule_table():
    assert classify_source("zhihu.com") == "知乎"
    assert classify_source("xiaohongshu.com") == "小红书"
    assert classify_source("people.com.cn") == "权威媒体"
    assert classify_source("gov.cn") == "权威媒体"
    assert classify_source("jd.com") == "电商"
    assert classify_source("randomblog.net") == "其他"


def test_classify_citations_fills_domain_and_type():
    out = classify_citations([Citation(url="https://zhuanlan.zhihu.com/p/1", title="t")])
    assert out[0].domain == "zhihu.com"
    assert out[0].source_type == "知乎"
    assert out[0].title == "t"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/core/monitor/geo/test_classify.py -v`
Expected: FAIL — `ModuleNotFoundError`/`ImportError`

- [ ] **Step 3: 写实现**

```python
# csm_core/monitor/geo/classify.py
"""信源域名规整 + source_type 分类。

domain：取「注册域名」（去子域）。优先用 tldextract（若装了），否则用
一个覆盖中国常见多段后缀（.com.cn/.gov.cn/.edu.cn…）的轻量回退。

source_type：规则表优先（精确域名 → 类别）。规则未命中返回「其他」；
LLM 兜底归类在抽取层（Task 8）按需调用，这里只做确定性规则。
"""
from __future__ import annotations
from urllib.parse import urlparse

from .models import Citation, ClassifiedCitation

# 多段后缀：识别 a.b.com.cn 这种注册域名 = b.com.cn
_MULTI_SUFFIX = (
    ".com.cn", ".net.cn", ".org.cn", ".gov.cn", ".edu.cn", ".ac.cn",
    ".com.hk", ".com.tw",
)

# 精确注册域名 → 类别
_RULES: dict[str, str] = {
    "zhihu.com": "知乎",
    "xiaohongshu.com": "小红书",
    "xhslink.com": "小红书",
    # 权威媒体（央媒/门户/政务）
    "people.com.cn": "权威媒体", "xinhuanet.com": "权威媒体", "gov.cn": "权威媒体",
    "cctv.com": "权威媒体", "thepaper.cn": "权威媒体", "caixin.com": "权威媒体",
    "36kr.com": "权威媒体", "ifeng.com": "权威媒体", "sina.com.cn": "权威媒体",
    # 电商
    "jd.com": "电商", "taobao.com": "电商", "tmall.com": "电商",
    "pinduoduo.com": "电商", "suning.com": "电商",
}


def registered_domain(url: str) -> str:
    try:
        host = (urlparse(url).hostname or "").lower().strip(".")
    except Exception:
        host = ""
    if not host or "." not in host:
        return ""
    try:
        import tldextract  # type: ignore
        ext = tldextract.extract(url)
        if ext.domain and ext.suffix:
            return f"{ext.domain}.{ext.suffix}"
    except Exception:
        pass
    # 回退：处理多段后缀
    for suf in _MULTI_SUFFIX:
        if host.endswith(suf):
            head = host[: -len(suf)].split(".")[-1]
            return f"{head}{suf}" if head else host
    parts = host.split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def classify_source(domain: str) -> str:
    d = (domain or "").lower()
    if d in _RULES:
        return _RULES[d]
    # 政务/教育兜底：任何 .gov.cn / .edu.cn 注册域归权威媒体
    if d.endswith(".gov.cn") or d.endswith(".edu.cn"):
        return "权威媒体"
    return "其他"


def classify_citations(cits: list[Citation]) -> list[ClassifiedCitation]:
    out: list[ClassifiedCitation] = []
    for c in cits:
        dom = registered_domain(c.url)
        out.append(ClassifiedCitation(
            url=c.url, title=c.title, domain=dom, source_type=classify_source(dom),
        ))
    return out
```

> 依赖说明：`tldextract` 非必须（有就用、没有走回退）。若决定固定依赖，在 `pyproject.toml` 的 dependencies 加 `tldextract>=5.0` 并单列一步 commit；阶段 1 不强制。

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/core/monitor/geo/test_classify.py -v`
Expected: PASS（3 passed）

- [ ] **Step 5: Commit**

```bash
git add csm_core/monitor/geo/classify.py tests/core/monitor/geo/test_classify.py
git commit -m "feat(geo): 信源域名规整 + source_type 分类规则表"
```

---

## Task 4: 四大 KPI 聚合（metrics.py）

**Files:**
- Create: `csm_core/monitor/geo/metrics.py`
- Test: `tests/core/monitor/geo/test_metrics.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/core/monitor/geo/test_metrics.py
from csm_core.monitor.geo.models import GeoCell
from csm_core.monitor.geo import metrics


def _cell(plat, kw, mentioned, rank, sentiment="na"):
    return GeoCell(platform=plat, keyword=kw, mentioned=mentioned, rank=rank, sentiment=sentiment)


def test_share_of_chat_and_bands():
    cells = [_cell("tongyi", "k1", True, 1, "pos"),
             _cell("tongyi", "k2", False, -1),
             _cell("kimi", "k1", False, -1),
             _cell("kimi", "k2", False, -1)]
    agg = metrics.aggregate(cells)
    assert agg["total"] == 4
    assert agg["mentioned"] == 1
    assert agg["soc"] == 0.25
    assert agg["status_band"] == "hidden"   # <0.2? 0.25 → weak. 见下条断言修正
    # 25% → weak（20%~50%）
    assert metrics.band(0.25) == "weak"
    assert metrics.band(0.1) == "hidden"
    assert metrics.band(0.8) == "strong"


def test_first_rank_rate_denominator_is_total():
    cells = [_cell("tongyi", "k1", True, 1), _cell("tongyi", "k2", True, 3),
             _cell("kimi", "k1", True, 1), _cell("kimi", "k2", False, -1)]
    agg = metrics.aggregate(cells)
    assert agg["first_rank_rate"] == 0.5          # 2 个 rank==1 / 4 总数
    assert agg["first_rank_rate_mentioned"] == 2 / 3  # 2 / 3 提及


def test_sentiment_score_mean_over_mentioned():
    cells = [_cell("tongyi", "k1", True, 1, "pos"),
             _cell("tongyi", "k2", True, 2, "neg"),
             _cell("kimi", "k1", True, 1, "neu"),
             _cell("kimi", "k2", False, -1, "na")]
    agg = metrics.aggregate(cells)
    assert agg["sentiment_score"] == 0.0          # (1 + -1 + 0)/3
    assert agg["sentiment_dist"] == {"pos": 1, "neu": 1, "neg": 1}


def test_by_platform_breakdown():
    cells = [_cell("tongyi", "k1", True, 1), _cell("kimi", "k1", False, -1)]
    agg = metrics.aggregate(cells)
    assert agg["by_platform"]["tongyi"]["soc"] == 1.0
    assert agg["by_platform"]["kimi"]["soc"] == 0.0


def test_representative_rank_is_median_of_mentioned():
    cells = [_cell("t", "k1", True, 1), _cell("t", "k2", True, 3), _cell("t", "k3", True, 5),
             _cell("t", "k4", False, -1)]
    assert metrics.representative_rank(cells) == 3
    assert metrics.representative_rank([_cell("t", "k", False, -1)]) == -1
```

> 注意：上面第 1 个测试里 `agg["status_band"] == "hidden"` 是**故意写错的占位**，Step 3 实现后改成 `== "weak"`。先让你看到 band 边界：<0.2 hidden / 0.2–0.5 weak / ≥0.5 strong。

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/core/monitor/geo/test_metrics.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: 写实现 + 修正测试占位**

先把测试里 `assert agg["status_band"] == "hidden"` 改成 `assert agg["status_band"] == "weak"`，再写实现：

```python
# csm_core/monitor/geo/metrics.py
"""四大 KPI 聚合（纯函数，零 I/O）。

输入一次运行的全部 GeoCell，输出仪表盘用的 KPI 汇总块。口径见 spec §7：
- 曝光度 SoC = 提及/总；band: <0.2 hidden / <0.5 weak / else strong
- 首推率 = rank==1 / 总（绝对）；另出 /提及（条件）
- 情感得分 = pos+1/neu0/neg-1 对提及取均值
- 顶层代表顺位 = 提及 cell 顺位中位数（-1 if none）
"""
from __future__ import annotations
from statistics import median
from typing import Any

from .models import GeoCell

_SENTI = {"pos": 1.0, "neu": 0.0, "neg": -1.0}


def band(soc: float) -> str:
    if soc < 0.2:
        return "hidden"
    if soc < 0.5:
        return "weak"
    return "strong"


def _block(cells: list[GeoCell]) -> dict[str, Any]:
    total = len(cells)
    mentioned = sum(1 for c in cells if c.mentioned)
    first = sum(1 for c in cells if c.mentioned and c.rank == 1)
    senti_vals = [_SENTI.get(c.sentiment, 0.0) for c in cells if c.mentioned]
    soc = (mentioned / total) if total else 0.0
    return {
        "total": total,
        "mentioned": mentioned,
        "soc": soc,
        "status_band": band(soc),
        "first_rank_rate": (first / total) if total else 0.0,
        "first_rank_rate_mentioned": (first / mentioned) if mentioned else 0.0,
        "sentiment_score": (sum(senti_vals) / len(senti_vals)) if senti_vals else 0.0,
    }


def aggregate(cells: list[GeoCell]) -> dict[str, Any]:
    agg = _block(cells)
    # 情感分布
    dist = {"pos": 0, "neu": 0, "neg": 0}
    for c in cells:
        if c.mentioned and c.sentiment in dist:
            dist[c.sentiment] += 1
    agg["sentiment_dist"] = dist
    # 顺位分布
    agg["rank_dist"] = {
        "first": sum(1 for c in cells if c.mentioned and c.rank == 1),
        "top3": sum(1 for c in cells if c.mentioned and 1 <= c.rank <= 3),
        "top5": sum(1 for c in cells if c.mentioned and 1 <= c.rank <= 5),
        "mentioned_unranked": sum(1 for c in cells if c.mentioned and c.rank <= 0),
        "absent": sum(1 for c in cells if not c.mentioned),
    }
    # 维度切分
    by_plat: dict[str, list[GeoCell]] = {}
    by_kw: dict[str, list[GeoCell]] = {}
    for c in cells:
        by_plat.setdefault(c.platform, []).append(c)
        by_kw.setdefault(c.keyword, []).append(c)
    agg["by_platform"] = {k: _block(v) for k, v in by_plat.items()}
    agg["by_keyword"] = {k: _block(v) for k, v in by_kw.items()}
    return agg


def representative_rank(cells: list[GeoCell]) -> int:
    ranks = [c.rank for c in cells if c.mentioned and c.rank > 0]
    return int(median(ranks)) if ranks else -1
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/core/monitor/geo/test_metrics.py -v`
Expected: PASS（5 passed）

- [ ] **Step 5: Commit**

```bash
git add csm_core/monitor/geo/metrics.py tests/core/monitor/geo/test_metrics.py
git commit -m "feat(geo): 四大 KPI 聚合（SoC/首推率/情感分/分布/维度切分）"
```

---

## Task 5: 存储 v7（geo/storage.py + 接入 monitor 迁移）

**Files:**
- Create: `csm_core/monitor/geo/storage.py`
- Modify: `csm_core/monitor/storage.py`（`_SCHEMA_VERSION` 6→7；`_migrate` 调用 geo 迁移）
- Test: `tests/core/monitor/geo/test_storage.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/core/monitor/geo/test_storage.py
from __future__ import annotations
import threading
from pathlib import Path
import pytest

import csm_core.monitor.storage as storage_mod
from csm_core.monitor import storage
from csm_core.monitor.base import MonitorResult, MonitorTask
from csm_core.monitor.geo import storage as geo_storage
from csm_core.monitor.geo.models import GeoCell, ClassifiedCitation


@pytest.fixture
def fresh_db(tmp_path: Path):
    storage_mod._db_path = None
    storage_mod._initialized = False
    storage_mod._local = threading.local()
    storage.init_db(tmp_path / "monitor.db")
    yield tmp_path / "monitor.db"
    conn = getattr(storage_mod._local, "conn", None)
    if conn is not None:
        conn.close()
    storage_mod._db_path = None
    storage_mod._initialized = False


def test_v7_tables_exist(fresh_db):
    conn = storage.get_conn()
    names = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert "geo_cells" in names
    assert "geo_citations" in names


def _seed_run(fresh_db) -> int:
    tid = storage.create_task(MonitorTask(
        type="geo_query", name="小鹏卡位", target_url="geo://小鹏",
        config={"brand": "小鹏"}))
    rid = storage.save_result(MonitorResult(
        task_id=tid, checked_at=__import__("datetime").datetime.utcnow(),
        status="ok", rank=2, metric={}))
    cells = [
        GeoCell(platform="tongyi", keyword="新能源SUV", mentioned=True, rank=1, sentiment="pos",
                citations=[ClassifiedCitation(url="https://zhihu.com/a", domain="zhihu.com", source_type="知乎"),
                           ClassifiedCitation(url="https://xiaohongshu.com/b", domain="xiaohongshu.com", source_type="小红书")]),
        GeoCell(platform="kimi", keyword="新能源SUV", mentioned=False, rank=-1,
                citations=[ClassifiedCitation(url="https://zhihu.com/c", domain="zhihu.com", source_type="知乎")]),
    ]
    geo_storage.record_run(rid, tid, cells)
    return tid


def test_record_run_persists_cells_and_citations(fresh_db):
    tid = _seed_run(fresh_db)
    conn = storage.get_conn()
    assert conn.execute("SELECT count(*) FROM geo_cells WHERE task_id=?", (tid,)).fetchone()[0] == 2
    assert conn.execute("SELECT count(*) FROM geo_citations WHERE task_id=?", (tid,)).fetchone()[0] == 3


def test_citation_leaderboard_ranks_by_freq(fresh_db):
    tid = _seed_run(fresh_db)
    board = geo_storage.citation_leaderboard(tid, days=3650)
    # zhihu.com 出现 2 次，xiaohongshu.com 1 次
    assert board[0]["domain"] == "zhihu.com"
    assert board[0]["count"] == 2
    assert board[0]["source_type"] == "知乎"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/core/monitor/geo/test_storage.py -v`
Expected: FAIL — `geo_cells` 表不存在 / `ImportError`

- [ ] **Step 3: 写 geo/storage.py**

```python
# csm_core/monitor/geo/storage.py
"""GEO 存储层（schema v7）—— 复用 monitor.storage 的连接与迁移 runner。

两张规范化表让信源榜/趋势能 GROUP BY；运行级 KPI 汇总仍存
monitor_results.metric_json（adapter 写）。DDL 拆在这里、由
monitor.storage._migrate 调 apply_v7_migration，仿 mining v3-v6。
"""
from __future__ import annotations
import sqlite3
from datetime import datetime
from typing import Any

from csm_core.monitor import storage as monitor_storage
from .models import GeoCell

_DDL_V7_GEO: list[str] = [
    """
    CREATE TABLE IF NOT EXISTS geo_cells (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        result_id   INTEGER NOT NULL REFERENCES monitor_results(id) ON DELETE CASCADE,
        task_id     INTEGER NOT NULL,
        checked_at  TEXT NOT NULL,
        platform    TEXT NOT NULL,
        keyword     TEXT NOT NULL,
        mentioned   INTEGER NOT NULL DEFAULT 0,
        rank        INTEGER NOT NULL DEFAULT -1,
        sentiment   TEXT NOT NULL DEFAULT 'na',
        answer_text TEXT NOT NULL DEFAULT '',
        status      TEXT NOT NULL DEFAULT 'ok',
        raw_json    TEXT NOT NULL DEFAULT '{}'
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_geo_cells_task_time ON geo_cells(task_id, checked_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_geo_cells_result ON geo_cells(result_id)",
    """
    CREATE TABLE IF NOT EXISTS geo_citations (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        cell_id     INTEGER NOT NULL REFERENCES geo_cells(id) ON DELETE CASCADE,
        task_id     INTEGER NOT NULL,
        checked_at  TEXT NOT NULL,
        platform    TEXT NOT NULL,
        keyword     TEXT NOT NULL,
        url         TEXT NOT NULL,
        title       TEXT NOT NULL DEFAULT '',
        domain      TEXT NOT NULL DEFAULT '',
        source_type TEXT NOT NULL DEFAULT '其他'
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_geo_cit_task_domain ON geo_citations(task_id, domain)",
    "CREATE INDEX IF NOT EXISTS idx_geo_cit_cell ON geo_citations(cell_id)",
]


def apply_v7_migration(conn: sqlite3.Connection) -> None:
    """Called by monitor.storage._migrate when bumping v6 → v7. Idempotent."""
    for stmt in _DDL_V7_GEO:
        conn.execute(stmt)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"


def record_run(result_id: int, task_id: int, cells: list[GeoCell]) -> None:
    """批量写一次运行的 cells + citations。一个事务，失败回滚。"""
    import json
    conn = monitor_storage.get_conn()
    now = _iso(datetime.utcnow())
    conn.execute("BEGIN")
    try:
        for c in cells:
            cur = conn.execute(
                """INSERT INTO geo_cells(result_id, task_id, checked_at, platform, keyword,
                       mentioned, rank, sentiment, answer_text, status, raw_json)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?) RETURNING id""",
                (result_id, task_id, now, c.platform, c.keyword,
                 1 if c.mentioned else 0, c.rank, c.sentiment,
                 c.answer_text, c.status, json.dumps(c.raw, ensure_ascii=False)),
            )
            cell_id = int(cur.fetchone()[0])
            for cit in c.citations:
                conn.execute(
                    """INSERT INTO geo_citations(cell_id, task_id, checked_at, platform, keyword,
                           url, title, domain, source_type)
                       VALUES(?,?,?,?,?,?,?,?,?)""",
                    (cell_id, task_id, now, c.platform, c.keyword,
                     cit.url, cit.title, cit.domain, cit.source_type),
                )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def citation_leaderboard(
    task_id: int, days: int = 30, platform: str | None = None, keyword: str | None = None,
) -> list[dict[str, Any]]:
    """域名频次降序。返回 [{domain, source_type, count, platforms, keywords}]."""
    conn = monitor_storage.get_conn()
    sql = ["SELECT domain, source_type, count(*) AS cnt,",
           "  group_concat(DISTINCT platform) AS plats,",
           "  group_concat(DISTINCT keyword) AS kws",
           "FROM geo_citations",
           "WHERE task_id=? AND checked_at >= datetime('now', ?)"]
    args: list[Any] = [task_id, f"-{int(days)} days"]
    if platform:
        sql.append("AND platform=?"); args.append(platform)
    if keyword:
        sql.append("AND keyword=?"); args.append(keyword)
    sql.append("GROUP BY domain, source_type ORDER BY cnt DESC, domain ASC")
    rows = conn.execute("\n".join(sql), args).fetchall()
    return [{"domain": r["domain"], "source_type": r["source_type"], "count": r["cnt"],
             "platforms": (r["plats"] or "").split(","),
             "keywords": (r["kws"] or "").split(",")} for r in rows]


def cells_for_run(result_id: int) -> list[dict[str, Any]]:
    """某次运行的全部 cell（下钻看原文 + 信源）。"""
    conn = monitor_storage.get_conn()
    rows = conn.execute(
        "SELECT * FROM geo_cells WHERE result_id=? ORDER BY platform, keyword", (result_id,)
    ).fetchall()
    out = []
    for r in rows:
        cits = conn.execute(
            "SELECT url, title, domain, source_type FROM geo_citations WHERE cell_id=?", (r["id"],)
        ).fetchall()
        out.append({**dict(r), "citations": [dict(c) for c in cits]})
    return out
```

- [ ] **Step 4: 接入 monitor 迁移**

在 `csm_core/monitor/storage.py`：把 `_SCHEMA_VERSION = 6` 改成 `_SCHEMA_VERSION = 7`；在 `_migrate()` 里 v6 之后加：

```python
    # v7: GEO 卡位监控两张规范化表（geo_cells / geo_citations）。
    from csm_core.monitor.geo import storage as geo_storage
    geo_storage.apply_v7_migration(conn)
```
（放在 `mining_storage.apply_v6_migration(conn)` 之后、写 `schema_meta` 之前。）

- [ ] **Step 5: 跑测试确认通过**

Run: `pytest tests/core/monitor/geo/test_storage.py -v`
Expected: PASS（3 passed）

回归现有 storage 测试不挂：
Run: `pytest tests/core/monitor/test_storage.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add csm_core/monitor/geo/storage.py csm_core/monitor/storage.py tests/core/monitor/geo/test_storage.py
git commit -m "feat(geo): schema v7 geo_cells/geo_citations + record_run + 信源榜查询"
```

---

## Task 6: GeoProvider 抽象 + 通义 provider

**Files:**
- Create: `csm_core/monitor/geo/providers/__init__.py`（空）
- Create: `csm_core/monitor/geo/providers/base.py`
- Create: `csm_core/monitor/geo/providers/api_tongyi.py`
- Test: `tests/core/monitor/geo/test_providers.py`

- [ ] **Step 1: 写失败测试（通义解析器，喂 fixture）**

```python
# tests/core/monitor/geo/test_providers.py
import json
from pathlib import Path
from csm_core.monitor.geo.providers.api_tongyi import parse_tongyi_response

FIX = Path(__file__).parent / "fixtures"


def test_parse_tongyi_extracts_answer_and_citations():
    raw = json.loads((FIX / "tongyi_search.json").read_text(encoding="utf-8"))
    answer_text, citations = parse_tongyi_response(raw)
    assert "小鹏G6" in answer_text
    urls = [c.url for c in citations]
    assert "https://zhuanlan.zhihu.com/p/123456" in urls
    assert citations[0].title.endswith("知乎")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/core/monitor/geo/test_providers.py -v`
Expected: FAIL — `ImportError`

- [ ] **Step 3: 写 base.py + api_tongyi.py**

```python
# csm_core/monitor/geo/providers/base.py
"""GeoProvider 协议 + 平台 → provider 注册表。"""
from __future__ import annotations
import threading
from typing import Protocol, runtime_checkable

from ..models import GeoAnswer


class GeoProviderError(RuntimeError):
    pass


@runtime_checkable
class GeoProvider(Protocol):
    platform: str
    mode: str  # "api" | "rpa"

    def query(self, keyword: str, *, web_search: bool,
              cancel_token: "threading.Event | None" = None) -> GeoAnswer: ...


def get_provider(platform: str) -> GeoProvider:
    """按平台名返回 provider 单例。阶段 1 只有 tongyi / kimi。"""
    if platform == "tongyi":
        from .api_tongyi import TongyiProvider
        return TongyiProvider()
    if platform == "kimi":
        from .api_kimi import KimiProvider
        return KimiProvider()
    raise GeoProviderError(f"未知 GEO 平台: {platform}")
```

```python
# csm_core/monitor/geo/providers/api_tongyi.py
"""通义千问 provider —— DashScope 原生 generation 端点 + enable_search。

信源走 output.search_info.search_results[]（含 url/title/site_name）。
key 复用现有 LLM provider 的 'qwen' keyring 项（read_api_key("qwen")）。
"""
from __future__ import annotations
import logging
import httpx

from csm_core.config import read_api_key
from ..models import GeoAnswer, Citation

logger = logging.getLogger(__name__)

_URL = "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation"


def parse_tongyi_response(raw: dict) -> tuple[str, list[Citation]]:
    out = raw.get("output") or {}
    # answer：result_format=message → output.choices[0].message.content；
    # 兼容 output.text（result_format=text）。
    text = ""
    choices = out.get("choices") or []
    if choices:
        text = (choices[0].get("message") or {}).get("content") or ""
    if not text:
        text = out.get("text") or ""
    cits: list[Citation] = []
    for sr in (out.get("search_info") or {}).get("search_results") or []:
        url = sr.get("url") or ""
        if not url:
            continue
        title = sr.get("title") or ""
        site = sr.get("site_name") or ""
        cits.append(Citation(url=url, title=f"{title} - {site}".strip(" -") if site else title))
    return text, cits


class TongyiProvider:
    platform = "tongyi"
    mode = "api"

    def __init__(self, *, model: str = "qwen-plus", timeout: float = 120.0) -> None:
        self._model = model
        self._timeout = timeout

    def query(self, keyword, *, web_search=True, cancel_token=None) -> GeoAnswer:
        key = read_api_key("qwen")
        if not key:
            return GeoAnswer(platform=self.platform, keyword=keyword,
                             status="error", error="通义(qwen) API key 未配置")
        body = {
            "model": self._model,
            "input": {"messages": [{"role": "user", "content": keyword}]},
            "parameters": {"enable_search": bool(web_search),
                           "search_options": {"enable_source": True, "enable_citation": True},
                           "result_format": "message"},
        }
        try:
            r = httpx.post(_URL, headers={"Authorization": f"Bearer {key}"},
                           json=body, timeout=self._timeout)
        except httpx.HTTPError as e:
            return GeoAnswer(platform=self.platform, keyword=keyword, status="error", error=str(e))
        # raw-logging（silent-failure 防御）
        logger.info("[geo.tongyi] kw=%s http=%d len=%d first200=%s",
                    keyword, r.status_code, len(r.text), r.text[:200].replace("\n", " "))
        if r.status_code >= 400:
            return GeoAnswer(platform=self.platform, keyword=keyword, status="error",
                             error=f"http {r.status_code}: {r.text[:300]}", raw={"status": r.status_code})
        raw = r.json()
        text, cits = parse_tongyi_response(raw)
        status = "ok" if text else "empty"
        return GeoAnswer(platform=self.platform, keyword=keyword, answer_text=text,
                         citations=cits, raw=raw, status=status)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/core/monitor/geo/test_providers.py -v`
Expected: PASS（1 passed）

- [ ] **Step 5: Commit**

```bash
git add csm_core/monitor/geo/providers/ tests/core/monitor/geo/test_providers.py
git commit -m "feat(geo): GeoProvider 协议 + 通义 DashScope enable_search provider"
```

---

## Task 7: Kimi provider

**Files:**
- Create: `csm_core/monitor/geo/providers/api_kimi.py`
- Modify: `tests/core/monitor/geo/test_providers.py`（加 Kimi 解析测试）

- [ ] **Step 1: 加失败测试**

```python
# 追加到 tests/core/monitor/geo/test_providers.py
from csm_core.monitor.geo.providers.api_kimi import parse_kimi_response


def test_parse_kimi_extracts_answer_and_citations():
    raw = json.loads((FIX / "kimi_search.json").read_text(encoding="utf-8"))
    answer_text, citations = parse_kimi_response(raw)
    assert "小鹏G6" in answer_text
    urls = [c.url for c in citations]
    assert "https://www.zhihu.com/question/600" in urls
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/core/monitor/geo/test_providers.py::test_parse_kimi_extracts_answer_and_citations -v`
Expected: FAIL — `ImportError`

- [ ] **Step 3: 写 api_kimi.py**

> Moonshot 的 `$web_search` 是 server-side builtin：首个响应若 `finish_reason=="tool_calls"`，把该 tool_call 的 `arguments` 原样作为 tool 结果回传，模型据此续写最终答案。信源来自最终 message 的 `annotations[].url_citation`（Task 1 探针确认；若实际不在 annotations，按真实形状改 `parse_kimi_response`，仍拿不到则记入 spec §14 待阶段 3 降级 RPA）。

```python
# csm_core/monitor/geo/providers/api_kimi.py
"""Kimi(Moonshot) provider —— OpenAI 兼容 + $web_search builtin。

信源走 choices[0].message.annotations[].url_citation。
key 用 keyring 'kimi' 项（read_api_key("kimi")）。
"""
from __future__ import annotations
import json
import logging
import httpx

from csm_core.config import read_api_key
from ..models import GeoAnswer, Citation

logger = logging.getLogger(__name__)

_URL = "https://api.moonshot.cn/v1/chat/completions"
_SEARCH_TOOL = {"type": "builtin_function", "function": {"name": "$web_search"}}


def parse_kimi_response(raw: dict) -> tuple[str, list[Citation]]:
    choices = raw.get("choices") or []
    if not choices:
        return "", []
    msg = choices[0].get("message") or {}
    text = msg.get("content") or ""
    cits: list[Citation] = []
    for ann in msg.get("annotations") or []:
        uc = ann.get("url_citation") or {}
        url = uc.get("url") or ""
        if url:
            cits.append(Citation(url=url, title=uc.get("title") or ""))
    return text, cits


class KimiProvider:
    platform = "kimi"
    mode = "api"

    def __init__(self, *, model: str = "moonshot-v1-8k", timeout: float = 120.0,
                 max_tool_rounds: int = 3) -> None:
        self._model = model
        self._timeout = timeout
        self._max_rounds = max_tool_rounds

    def query(self, keyword, *, web_search=True, cancel_token=None) -> GeoAnswer:
        key = read_api_key("kimi")
        if not key:
            return GeoAnswer(platform=self.platform, keyword=keyword,
                             status="error", error="Kimi(moonshot) API key 未配置")
        messages = [{"role": "user", "content": keyword}]
        tools = [_SEARCH_TOOL] if web_search else None
        try:
            with httpx.Client(timeout=self._timeout) as client:
                for _ in range(self._max_rounds):
                    body = {"model": self._model, "messages": messages}
                    if tools:
                        body["tools"] = tools
                    r = client.post(_URL, headers={"Authorization": f"Bearer {key}"}, json=body)
                    logger.info("[geo.kimi] kw=%s http=%d len=%d", keyword, r.status_code, len(r.text))
                    if r.status_code >= 400:
                        return GeoAnswer(platform=self.platform, keyword=keyword, status="error",
                                         error=f"http {r.status_code}: {r.text[:300]}")
                    raw = r.json()
                    choice = (raw.get("choices") or [{}])[0]
                    finish = choice.get("finish_reason")
                    msg = choice.get("message") or {}
                    if finish == "tool_calls":
                        # 把 $web_search 的 arguments 原样回传（server-side 执行）
                        messages.append(msg)
                        for tc in msg.get("tool_calls") or []:
                            messages.append({
                                "role": "tool",
                                "tool_call_id": tc.get("id"),
                                "name": (tc.get("function") or {}).get("name"),
                                "content": (tc.get("function") or {}).get("arguments") or "{}",
                            })
                        continue
                    text, cits = parse_kimi_response(raw)
                    return GeoAnswer(platform=self.platform, keyword=keyword, answer_text=text,
                                     citations=cits, raw=raw, status="ok" if text else "empty")
        except httpx.HTTPError as e:
            return GeoAnswer(platform=self.platform, keyword=keyword, status="error", error=str(e))
        return GeoAnswer(platform=self.platform, keyword=keyword, status="error",
                         error="超过 $web_search 工具轮次上限")
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/core/monitor/geo/test_providers.py -v`
Expected: PASS（2 passed）

- [ ] **Step 5: Commit**

```bash
git add csm_core/monitor/geo/providers/api_kimi.py tests/core/monitor/geo/test_providers.py
git commit -m "feat(geo): Kimi Moonshot \$web_search provider"
```

---

## Task 8: LLM 抽取管线（extract.py）

**Files:**
- Create: `csm_core/monitor/geo/extract.py`
- Test: `tests/core/monitor/geo/test_extract.py`

- [ ] **Step 1: 写失败测试（用假 LLMClient 注入 JSON）**

```python
# tests/core/monitor/geo/test_extract.py
from csm_core.monitor.geo.models import GeoAnswer, Citation
from csm_core.monitor.geo.extract import extract


class FakeClient:
    def __init__(self, payload: str):
        self._payload = payload
        self.last_user = ""

    def complete(self, *, system: str, user: str, temperature=None) -> str:
        self.last_user = user
        return self._payload


def test_extract_parses_llm_json():
    payload = '''{"mentioned": true, "target_rank": 2, "sentiment": "pos",
      "recommended": [{"name":"比亚迪","position":1},{"name":"小鹏","position":2}],
      "summary": "小鹏智驾被正面推荐"}'''
    ans = GeoAnswer(platform="tongyi", keyword="新能源SUV",
                    answer_text="推荐比亚迪、小鹏……",
                    citations=[Citation(url="https://zhuanlan.zhihu.com/p/1", title="知乎文")])
    ext = extract(ans, brand="小鹏", aliases=["XPeng"], client=FakeClient(payload))
    assert ext.mentioned is True
    assert ext.target_rank == 2
    assert ext.recommended[1].is_target is True          # 「小鹏」被标 target
    assert ext.recommended[0].is_target is False
    # 信源来自 answer，分类已补
    assert ext.citations[0].domain == "zhihu.com"
    assert ext.citations[0].source_type == "知乎"


def test_extract_bad_json_falls_back():
    ans = GeoAnswer(platform="kimi", keyword="k", answer_text="小鹏不错")
    ext = extract(ans, brand="小鹏", aliases=[], client=FakeClient("这不是JSON"))
    assert ext.target_rank == -1
    assert ext.summary.startswith("[抽取失败")


def test_extract_empty_answer_short_circuits():
    ans = GeoAnswer(platform="kimi", keyword="k", answer_text="", status="empty")
    called = {"n": 0}

    class Counting(FakeClient):
        def complete(self, **kw):
            called["n"] += 1
            return "{}"

    ext = extract(ans, brand="小鹏", aliases=[], client=Counting("{}"))
    assert ext.mentioned is False
    assert called["n"] == 0           # 空答案不调 LLM
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/core/monitor/geo/test_extract.py -v`
Expected: FAIL — `ImportError`

- [ ] **Step 3: 写 extract.py**

```python
# csm_core/monitor/geo/extract.py
"""把一条 GeoAnswer 抽成结构化 GeoExtraction（LLM 一次调用）。

信源不靠 LLM：直接对 answer.citations 跑 classify（确定性、省 token）。
LLM 只产出 mentioned/rank/recommended/sentiment/summary。坏 JSON 重试
一次（更严格的 system），仍失败则降级（mentioned 启发式 + rank=-1）。
"""
from __future__ import annotations
import json
import logging
import re

from csm_core.llm.client import LLMClient, make_client
from csm_core.config import read_api_key
from .models import GeoAnswer, GeoExtraction, RecommendedEntity
from .classify import classify_citations

logger = logging.getLogger(__name__)

_SYSTEM = (
    "你是品牌监测分析助手。给定一个用户问题和某 AI 的回答，判断目标品牌在回答中的情况。"
    "只输出 JSON，不要解释。字段："
    '{"mentioned":bool,"target_rank":int,"sentiment":"pos|neu|neg|na",'
    '"recommended":[{"name":str,"position":int}],"summary":str}。'
    "target_rank 是目标品牌在回答推荐序列中的 1-based 位置，未提及或未进序列填 -1。"
    "recommended 按回答里出现/推荐的顺序列出所有品牌。"
)
_SYSTEM_STRICT = _SYSTEM + " 上一次输出不是合法 JSON，请严格只输出一个 JSON 对象。"


def build_extract_client(provider: str) -> LLMClient:
    """按 provider 名建 LLM client（key 走 keyring/config）。"""
    if provider == "mock":
        return make_client(provider="mock")
    key = read_api_key(provider)
    if not key:
        raise ValueError(f"抽取 provider '{provider}' 未配置 API key")
    return make_client(provider=provider, api_key=key)


def _norm(s: str) -> str:
    return (s or "").lower().replace(" ", "").strip()


def _is_target(name: str, brand: str, aliases: list[str]) -> bool:
    n = _norm(name)
    pool = {_norm(brand), *(_norm(a) for a in aliases)}
    return any(p and (p in n or n in p) for p in pool)


def _parse_json(text: str) -> dict | None:
    text = text.strip()
    # 容忍 ```json ... ``` 包裹
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def extract(answer: GeoAnswer, *, brand: str, aliases: list[str], client: LLMClient) -> GeoExtraction:
    citations = classify_citations(answer.citations)

    # 空答案不调 LLM
    if not answer.answer_text.strip():
        return GeoExtraction(mentioned=False, target_rank=-1, sentiment="na",
                             recommended=[], citations=citations, summary="")

    user = f"用户问题：{answer.keyword}\n\nAI 回答：\n{answer.answer_text}\n\n目标品牌：{brand}"
    obj = None
    for sys_prompt in (_SYSTEM, _SYSTEM_STRICT):
        try:
            raw = client.complete(system=sys_prompt, user=user, temperature=0.0)
        except Exception as e:
            logger.warning("[geo.extract] LLM 调用失败 kw=%s: %s", answer.keyword, e)
            break
        obj = _parse_json(raw)
        if obj is not None:
            break

    if obj is None:
        # 降级：品牌名/别名在文本里出现就算 mentioned
        mentioned = _is_target(answer.answer_text, brand, aliases) or \
            any(_norm(brand) in _norm(answer.answer_text) for _ in [0])
        return GeoExtraction(mentioned=mentioned, target_rank=-1, sentiment="na",
                             recommended=[], citations=citations,
                             summary="[抽取失败，已降级为启发式]")

    recommended = []
    for item in obj.get("recommended") or []:
        name = str(item.get("name", "")).strip()
        if not name:
            continue
        recommended.append(RecommendedEntity(
            name=name, position=int(item.get("position", 0) or 0),
            is_target=_is_target(name, brand, aliases)))

    senti = obj.get("sentiment", "na")
    if senti not in ("pos", "neu", "neg", "na"):
        senti = "na"
    return GeoExtraction(
        mentioned=bool(obj.get("mentioned", False)),
        target_rank=int(obj.get("target_rank", -1) or -1),
        sentiment=senti,
        recommended=recommended,
        citations=citations,
        summary=str(obj.get("summary", "")),
    )
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/core/monitor/geo/test_extract.py -v`
Expected: PASS（3 passed）

- [ ] **Step 5: Commit**

```bash
git add csm_core/monitor/geo/extract.py tests/core/monitor/geo/test_extract.py
git commit -m "feat(geo): LLM 抽取管线（结构化 JSON + 坏 JSON 降级）"
```

---

## Task 9: GeoQueryAdapter（fan-out 闭环）

**Files:**
- Create: `csm_core/monitor/platforms/geo_query.py`
- Test: `tests/core/monitor/geo/test_geo_query_adapter.py`

> **实现前先读** `csm_core/monitor/platforms/baidu_keyword.py` 的 `fetch` 签名 + 它怎么调 `progress_cb` / `maybe_cancel` / `resume_from`，**照抄签名约定**（下面按 baidu 既有约定写；若有出入以 baidu 为准）。

- [ ] **Step 1: 写失败测试（注入假 provider + 假 client + in-memory db）**

```python
# tests/core/monitor/geo/test_geo_query_adapter.py
from __future__ import annotations
import threading
from pathlib import Path
import pytest

import csm_core.monitor.storage as storage_mod
from csm_core.monitor import storage
from csm_core.monitor.base import MonitorTask
from csm_core.monitor.geo.models import GeoAnswer, Citation
from csm_core.monitor.platforms import geo_query as geo_mod


@pytest.fixture
def fresh_db(tmp_path: Path):
    storage_mod._db_path = None
    storage_mod._initialized = False
    storage_mod._local = threading.local()
    storage.init_db(tmp_path / "monitor.db")
    yield
    conn = getattr(storage_mod._local, "conn", None)
    if conn is not None:
        conn.close()
    storage_mod._db_path = None
    storage_mod._initialized = False


class FakeProvider:
    def __init__(self, platform):
        self.platform = platform
        self.mode = "api"

    def query(self, keyword, *, web_search=True, cancel_token=None):
        return GeoAnswer(platform=self.platform, keyword=keyword,
                         answer_text=f"{self.platform} 推荐 小鹏 G6",
                         citations=[Citation(url="https://zhuanlan.zhihu.com/p/1", title="知乎")])


class FakeClient:
    def complete(self, *, system, user, temperature=None):
        return '{"mentioned":true,"target_rank":1,"sentiment":"pos","recommended":[{"name":"小鹏","position":1}],"summary":"正面"}'


def test_fetch_fans_out_and_records(fresh_db, monkeypatch):
    monkeypatch.setattr(geo_mod, "get_provider", lambda p: FakeProvider(p))
    monkeypatch.setattr(geo_mod, "build_extract_client", lambda p: FakeClient())

    tid = storage.create_task(MonitorTask(
        type="geo_query", name="小鹏卡位", target_url="geo://小鹏",
        config={"brand": "小鹏", "keywords": ["新能源SUV", "智驾车"],
                "platforms": ["tongyi", "kimi"], "extract_provider": "mock"}))
    task = storage.get_task(tid)

    progress = []
    result = geo_mod.ADAPTER.fetch(task, progress_cb=lambda c, t: progress.append((c, t)))

    assert result.status == "ok"
    assert result.rank == 1                      # 全 rank==1 → 中位 1
    assert result.metric["soc"] == 1.0
    assert result.metric["first_rank_rate"] == 1.0
    assert progress[-1] == (4, 4)                # 2 关键词 × 2 平台

    # 落库
    rid = storage.latest_result(tid).task_id  # sanity
    from csm_core.monitor.geo import storage as geo_storage
    conn = storage.get_conn()
    assert conn.execute("SELECT count(*) FROM geo_cells WHERE task_id=?", (tid,)).fetchone()[0] == 4


def test_one_provider_error_does_not_kill_run(fresh_db, monkeypatch):
    def picker(p):
        if p == "kimi":
            class Boom(FakeProvider):
                def query(self, *a, **k):
                    raise RuntimeError("boom")
            return Boom(p)
        return FakeProvider(p)
    monkeypatch.setattr(geo_mod, "get_provider", picker)
    monkeypatch.setattr(geo_mod, "build_extract_client", lambda p: FakeClient())

    tid = storage.create_task(MonitorTask(
        type="geo_query", name="t", target_url="geo://小鹏",
        config={"brand": "小鹏", "keywords": ["k1"], "platforms": ["tongyi", "kimi"],
                "extract_provider": "mock"}))
    result = geo_mod.ADAPTER.fetch(storage.get_task(tid))
    assert result.status == "ok"                 # 部分失败不整体失败
    conn = storage.get_conn()
    rows = conn.execute("SELECT platform, status FROM geo_cells WHERE task_id=?", (tid,)).fetchall()
    statuses = {r["platform"]: r["status"] for r in rows}
    assert statuses["tongyi"] == "ok"
    assert statuses["kimi"] == "error"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/core/monitor/geo/test_geo_query_adapter.py -v`
Expected: FAIL — `ModuleNotFoundError: ...platforms.geo_query`

- [ ] **Step 3: 写 geo_query.py**

```python
# csm_core/monitor/platforms/geo_query.py
"""geo_query adapter —— 批量关键词 × 多 AI 平台 fan-out 卡位监控。

fetch() 对 keywords × platforms 做笛卡尔积，逐 cell：provider 采集 →
LLM 抽取 → 信源分类 → 累积 GeoCell。cell 级错误隔离（单 cell 失败记
status 继续）。结束后聚合四大 KPI 写 MonitorResult.metric，明细落
geo_cells/geo_citations。复用 baidu 的 progress_cb / maybe_cancel /
resume_from 约定。
"""
from __future__ import annotations
import logging
import threading
from datetime import datetime
from typing import Callable

from ..base import MonitorTask, MonitorResult, maybe_cancel
from ..geo.models import GeoCell
from ..geo.providers.base import get_provider
from ..geo.extract import extract, build_extract_client
from ..geo import metrics
from ..geo import storage as geo_storage
from .. import storage

logger = logging.getLogger(__name__)


class GeoQueryAdapter:
    platform = "geo_query"

    def fetch(
        self,
        task: MonitorTask,
        progress_cb: Callable[[int, int], None] | None = None,
        cancel_token: "threading.Event | None" = None,
        resume_from: int = 0,
    ) -> MonitorResult:
        cfg = task.config or {}
        brand = str(cfg.get("brand", "")).strip()
        aliases = list(cfg.get("brand_aliases", []) or [])
        keywords = [k for k in (cfg.get("keywords") or []) if str(k).strip()]
        platforms = list(cfg.get("platforms") or [])
        web_search = bool(cfg.get("web_search", True))
        extract_provider = str(cfg.get("extract_provider") or "mock")

        if not brand or not keywords or not platforms:
            return MonitorResult(task_id=task.id or 0, checked_at=datetime.utcnow(),
                                 status="failed", rank=-1,
                                 error_message="geo_query 配置缺 brand/keywords/platforms")

        cells_plan = [(kw, plat) for kw in keywords for plat in platforms]
        total = len(cells_plan)

        # 抽取 client 建一次（失败 → 整体失败，因为每个 cell 都要用）
        try:
            client = build_extract_client(extract_provider)
        except Exception as e:
            return MonitorResult(task_id=task.id or 0, checked_at=datetime.utcnow(),
                                 status="failed", rank=-1, error_message=f"抽取 client: {e}")

        cells: list[GeoCell] = []
        for i, (kw, plat) in enumerate(cells_plan):
            if i < resume_from:
                continue
            maybe_cancel(cancel_token)
            cell = self._run_cell(kw, plat, brand, aliases, web_search, client)
            cells.append(cell)
            if progress_cb:
                progress_cb(i + 1, total)

        agg = metrics.aggregate(cells)
        rank = metrics.representative_rank(cells)
        checked_at = datetime.utcnow()
        result = MonitorResult(task_id=task.id or 0, checked_at=checked_at,
                               status="ok", rank=rank, metric=agg)
        # 落库：先存 result 拿 result_id，再 record_run 明细
        result_id = storage.save_result(result)
        geo_storage.record_run(result_id, task.id or 0, cells)
        return result

    def _run_cell(self, keyword, platform, brand, aliases, web_search, client) -> GeoCell:
        try:
            provider = get_provider(platform)
            answer = provider.query(keyword, web_search=web_search)
            if answer.status in ("error", "blocked"):
                return GeoCell(platform=platform, keyword=keyword, status=answer.status,
                               answer_text="", raw={"error": answer.error})
            ext = extract(answer, brand=brand, aliases=aliases, client=client)
            return GeoCell(
                platform=platform, keyword=keyword,
                mentioned=ext.mentioned, rank=ext.target_rank, sentiment=ext.sentiment,
                answer_text=answer.answer_text, status="ok", raw=answer.raw,
                citations=ext.citations)
        except Exception as e:                       # cell 级隔离
            logger.warning("[geo] cell 失败 kw=%s plat=%s: %s", keyword, platform, e)
            return GeoCell(platform=platform, keyword=keyword, status="error",
                           raw={"error": str(e)})


ADAPTER = GeoQueryAdapter()
```

> **注意 import 路径**：测试用 `monkeypatch.setattr(geo_mod, "get_provider", ...)` 和 `"build_extract_client"`，所以这两个名字必须在 `geo_query` 模块命名空间里（上面用 `from ..geo.providers.base import get_provider` / `from ..geo.extract import build_extract_client` 顶层导入，正好满足）。

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/core/monitor/geo/test_geo_query_adapter.py -v`
Expected: PASS（2 passed）

- [ ] **Step 5: Commit**

```bash
git add csm_core/monitor/platforms/geo_query.py tests/core/monitor/geo/test_geo_query_adapter.py
git commit -m "feat(geo): GeoQueryAdapter fan-out 闭环（采集→抽取→聚合→落库 + cell 隔离）"
```

---

## Task 10: 注册 geo_query（全链路 + invariant 测试）

**Files:**
- Modify: `csm_core/monitor/base.py`（TaskType += "geo_query"）
- Modify: `csm_core/monitor/platforms/__init__.py`（注册 GEO）
- Modify: `sidecar/csm_sidecar/services/monitor_service.py`（PLATFORM_TYPES += "geo_query"）
- Test: `tests/core/monitor/geo/test_registration.py`

- [ ] **Step 1: 写失败 invariant 测试**

```python
# tests/core/monitor/geo/test_registration.py
def test_geo_query_in_tasktype_literal():
    from csm_core.monitor.base import TaskType
    import typing
    assert "geo_query" in typing.get_args(TaskType)


def test_geo_query_in_adapter_registry():
    from csm_core.monitor.platforms import ALL
    assert "geo_query" in ALL
    assert ALL["geo_query"].platform == "geo_query"


def test_geo_adapter_has_fetch():
    from csm_core.monitor.platforms import ALL
    assert hasattr(ALL["geo_query"], "fetch")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/core/monitor/geo/test_registration.py -v`
Expected: FAIL — `"geo_query" not in (...)`

- [ ] **Step 3: 改三处注册**

`csm_core/monitor/base.py` —— TaskType Literal 末尾加 `"geo_query"`：
```python
TaskType = Literal[
    "zhihu_question",
    "bilibili_comment",
    "douyin_comment",
    "kuaishou_comment",
    "baidu_keyword",
    "geo_query",
]
```

`csm_core/monitor/platforms/__init__.py`：
```python
from .baidu_keyword import ADAPTER as BAIDU
from .geo_query import ADAPTER as GEO

ALL = {
    "zhihu_question": ZHIHU,
    "bilibili_comment": BILIBILI,
    "douyin_comment": DOUYIN,
    "kuaishou_comment": KUAISHOU,
    "baidu_keyword": BAIDU,
    "geo_query": GEO,
}

__all__ = ["ZHIHU", "BILIBILI", "DOUYIN", "KUAISHOU", "BAIDU", "GEO", "ALL"]
```

`sidecar/csm_sidecar/services/monitor_service.py` —— 在 `PLATFORM_TYPES` 元组末尾加 `"geo_query"`（先读该文件确认变量名/位置；若该常量不存在则跳过本改动，registry 已是动态分发）。

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/core/monitor/geo/test_registration.py -v`
Expected: PASS（3 passed）

跑整个 geo 套件回归：
Run: `pytest tests/core/monitor/geo/ -v`
Expected: 全 PASS

- [ ] **Step 5: Commit**

```bash
git add csm_core/monitor/base.py csm_core/monitor/platforms/__init__.py sidecar/csm_sidecar/services/monitor_service.py tests/core/monitor/geo/test_registration.py
git commit -m "feat(geo): 注册 geo_query 任务类型（TaskType/registry/service）+ invariant 测试"
```

---

## Task 11: GEO 只读聚合端点（sidecar）

**Files:**
- Modify: `sidecar/csm_sidecar/routes/monitor.py`（加 GEO 端点）
- Test: `sidecar/tests/test_geo_routes.py`

> **实现前先读** `sidecar/csm_sidecar/routes/monitor.py` 顶部：router 前缀（是否已 `/api/monitor`）、`RequireToken` 依赖名、`_require_storage()` 用法。下面按 Explore 报告的约定写；以文件实际为准。

- [ ] **Step 1: 写失败测试**

```python
# sidecar/tests/test_geo_routes.py
"""GEO 只读聚合端点。复用项目既有 TestClient fixture 风格（参考
sidecar/tests/test_baidu_keyword.py / conftest）。"""
from __future__ import annotations
import threading
from pathlib import Path
import pytest

import csm_core.monitor.storage as storage_mod
from csm_core.monitor import storage
from csm_core.monitor.base import MonitorResult, MonitorTask
from csm_core.monitor.geo import storage as geo_storage
from csm_core.monitor.geo.models import GeoCell, ClassifiedCitation


@pytest.fixture
def geo_seeded(tmp_path: Path):
    storage_mod._db_path = None
    storage_mod._initialized = False
    storage_mod._local = threading.local()
    storage.init_db(tmp_path / "monitor.db")
    tid = storage.create_task(MonitorTask(type="geo_query", name="小鹏", target_url="geo://小鹏",
                                          config={"brand": "小鹏"}))
    import datetime
    rid = storage.save_result(MonitorResult(task_id=tid, checked_at=datetime.datetime.utcnow(),
                                            status="ok", rank=1, metric={"soc": 1.0}))
    geo_storage.record_run(rid, tid, [GeoCell(platform="tongyi", keyword="k", mentioned=True, rank=1,
        citations=[ClassifiedCitation(url="https://zhihu.com/a", domain="zhihu.com", source_type="知乎")])])
    yield tid
    conn = getattr(storage_mod._local, "conn", None)
    if conn is not None:
        conn.close()
    storage_mod._db_path = None
    storage_mod._initialized = False


def test_citation_leaderboard_endpoint(client, geo_seeded):
    tid = geo_seeded
    r = client.get(f"/api/monitor/geo/{tid}/citations", params={"days": 3650})
    assert r.status_code == 200
    board = r.json()["leaderboard"]
    assert board[0]["domain"] == "zhihu.com"
    assert board[0]["count"] == 1
```

> 若 `client` fixture 不在 conftest，参考 `sidecar/tests/test_baidu_keyword.py` 怎么造 `TestClient`（同样的 import + `RequireToken` 覆盖），把它抄到本测试或 sidecar conftest。

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest sidecar/tests/test_geo_routes.py -v`
Expected: FAIL — 404（端点不存在）

- [ ] **Step 3: 加端点**

在 `sidecar/csm_sidecar/routes/monitor.py` 末尾（router 已定义处）加：

```python
# ── GEO 卡位监控只读聚合端点 ───────────────────────────────────────────
@router.get("/geo/{task_id}/citations")
def geo_citations(task_id: int, days: int = 30, platform: str | None = None,
                  keyword: str | None = None, _t=RequireToken):
    _require_storage()
    from csm_core.monitor.geo import storage as geo_storage
    return {"leaderboard": geo_storage.citation_leaderboard(
        task_id, days=days, platform=platform, keyword=keyword)}


@router.get("/geo/{task_id}/cells")
def geo_cells(task_id: int, result_id: int, _t=RequireToken):
    _require_storage()
    from csm_core.monitor.geo import storage as geo_storage
    return {"cells": geo_storage.cells_for_run(result_id)}
```

> `RequireToken` / `_require_storage` / router 前缀按文件实际写法对齐（端点路径里别重复 `/api/monitor` 前缀——router 已带）。KPI 汇总走现有 `/api/monitor/results`（metric_json 已含 KPI 块），阶段 1 不单列 kpi 端点；导出 Excel 放 Task 14 之后或阶段 2。

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest sidecar/tests/test_geo_routes.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add sidecar/csm_sidecar/routes/monitor.py sidecar/tests/test_geo_routes.py
git commit -m "feat(geo): sidecar 信源榜/下钻只读端点"
```

---

## Task 12: 前端类型 + 建任务表单（AddTaskModal geo 分支）

> **前端无单测 harness**（tests/gui 是旧 PyQt）。前端任务验证 = `npx vue-tsc --noEmit` 通过（项目发版门禁）+ 手动冒烟。**改前端前先 `cd frontend && npm install`**（fresh worktree 必须，pnpm 不跑 esbuild postinstall）。

**Files:**
- Modify: `frontend/src/utils/monitor-types.ts`
- Modify: `frontend/src/components/monitor/AddTaskModal.vue`

- [ ] **Step 1: 加类型**

`frontend/src/utils/monitor-types.ts` 加：
```typescript
export const GEO_PLATFORMS = [
  { value: "tongyi", label: "通义千问" },
  { value: "kimi", label: "Kimi" },
  // 阶段 2-3：doubao / deepseek / quark / yuanbao
] as const;

export interface GeoTaskConfig {
  brand: string;
  brand_aliases: string[];
  keywords: string[];
  platforms: string[];
  web_search: boolean;
  extract_provider: string;
  top_n_citations: number;
}

export interface CitationRow {
  domain: string; source_type: string; count: number;
  platforms: string[]; keywords: string[];
}
```

- [ ] **Step 2: AddTaskModal 加 geo_query 选项 + 表单分支**

在 `TYPES` 数组（约 line 62-68）加：
```typescript
  { value: "geo_query", label: "AI 卡位监控（GEO）" },
```
在 type union（约 line 34）加 `| "geo_query"`。

表单：当 `type === "geo_query"` 时渲染 GEO 字段（参考现有 zhihu 分支的 v-if 结构）：
```vue
<template v-if="form.type === 'geo_query'">
  <label>品牌名 <input v-model="geo.brand" /></label>
  <label>品牌别名（逗号分隔）<input v-model="geoAliasesText" /></label>
  <label>关键词（每行一个）
    <textarea v-model="geoKeywordsText" rows="6"
      placeholder="20万左右的新能源SUV推荐&#10;智驾最好的车" />
  </label>
  <fieldset>
    <legend>平台</legend>
    <label v-for="p in GEO_PLATFORMS" :key="p.value">
      <input type="checkbox" :value="p.value" v-model="geo.platforms" /> {{ p.label }}
    </label>
  </fieldset>
  <label><input type="checkbox" v-model="geo.web_search" /> 联网搜索</label>
  <label>抽取模型
    <select v-model="geo.extract_provider">
      <option value="deepseek">DeepSeek</option>
      <option value="qwen">通义</option>
    </select>
  </label>
</template>
```
提交时把 `geoKeywordsText`（按行 split）和 `geoAliasesText`（按逗号 split）组装进 `config`：
```typescript
const config = form.type === "geo_query" ? {
  brand: geo.value.brand,
  brand_aliases: geoAliasesText.value.split(/[，,]/).map(s => s.trim()).filter(Boolean),
  keywords: geoKeywordsText.value.split(/\r?\n/).map(s => s.trim()).filter(Boolean),
  platforms: geo.value.platforms,
  web_search: geo.value.web_search,
  extract_provider: geo.value.extract_provider,
  top_n_citations: 20,
} : /* 现有分支 */ existingConfig;
```
`target_url` 对 geo_query 用 `geo://${geo.value.brand}`。

- [ ] **Step 3: typecheck**

Run: `cd frontend && npx vue-tsc --noEmit`
Expected: 无新增报错

- [ ] **Step 4: Commit**

```bash
git add frontend/src/utils/monitor-types.ts frontend/src/components/monitor/AddTaskModal.vue
git commit -m "feat(geo): 前端 GEO 类型 + 建任务表单（品牌/批量关键词/平台多选）"
```

---

## Task 13: 监测中心「AI 卡位」tab（GeoTaskModule.vue）

**Files:**
- Create: `frontend/src/components/monitor/geo/GeoTaskModule.vue`
- Modify: `frontend/src/views/MonitorView.vue`（加 tab）

> 参考 `frontend/src/components/monitor/ZhihuMonitorModule.vue` 的结构（任务列表 + run + SSE 进度 + 最近一次结果），sidecar 调用走 `useSidecar().client`，SSE 走 `subscribe("/api/monitor/events")`。

- [ ] **Step 1: 建 GeoTaskModule.vue**

最小可用：任务列表（GET `/api/monitor/tasks?type=geo_query`）+ 建任务（复用 AddTaskModal）+ run-now（POST `/api/monitor/tasks/{id}/run-now`）+ SSE 进度条 + 最近一次 4 KPI 卡（读 `/api/monitor/results?task_id=` 的 `metric`：`soc / first_rank_rate / sentiment_score / status_band`）+ 信源榜 Top（GET `/api/monitor/geo/{id}/citations?days=30`）。

```vue
<script setup lang="ts">
import { ref, onMounted, onUnmounted } from "vue";
import { useSidecar } from "@/stores/sidecar";
import { subscribe } from "@/api/client";
import type { CitationRow } from "@/utils/monitor-types";

const sidecar = useSidecar();
const tasks = ref<any[]>([]);
const progress = ref<{ taskId: number; cur: number; total: number } | null>(null);
const latestKpi = ref<Record<number, any>>({});
const board = ref<CitationRow[]>([]);

async function loadTasks() {
  const r = await sidecar.client.get("/api/monitor/tasks", { params: { type: "geo_query" } });
  tasks.value = r.data.tasks ?? [];
}
async function runNow(id: number) {
  await sidecar.client.post(`/api/monitor/tasks/${id}/run-now`);
}
async function loadBoard(id: number) {
  const r = await sidecar.client.get(`/api/monitor/geo/${id}/citations`, { params: { days: 30 } });
  board.value = r.data.leaderboard ?? [];
}

let stop: (() => void) | null = null;
onMounted(async () => {
  await loadTasks();
  stop = subscribe("/api/monitor/events", (ev: any) => {
    if (ev.event === "progress" && ev.data?.task_id != null) {
      progress.value = { taskId: ev.data.task_id, cur: ev.data.current, total: ev.data.total };
    }
    if (ev.event === "finished") { loadTasks(); }
  });
});
onUnmounted(() => stop?.());
</script>

<template>
  <div>
    <!-- 任务列表：品牌 / 关键词数 / 平台数 / SoC / 首推率 / run -->
    <div v-for="t in tasks" :key="t.id">
      <span>{{ t.name }}</span>
      <button @click="runNow(t.id)">运行</button>
      <button @click="loadBoard(t.id)">看信源榜</button>
    </div>
    <div v-if="progress">进度 {{ progress.cur }}/{{ progress.total }}</div>
    <!-- 信源榜 Top -->
    <table v-if="board.length">
      <tr v-for="row in board" :key="row.domain">
        <td>{{ row.domain }}</td><td>{{ row.source_type }}</td><td>{{ row.count }}</td>
      </tr>
    </table>
  </div>
</template>
```
> 视觉对齐项目设计系统（参考 ZhihuMonitorModule 的 KPI 卡/色带样式）；上面是结构骨架，样式按现有组件补。SSE 事件字段名（`event`/`data.task_id`/`current`/`total`）以 `sidecar/csm_sidecar/monitor_bus.py` + 现有 MonitorView 订阅代码实际为准。

- [ ] **Step 2: MonitorView 加 tab**

`frontend/src/views/MonitorView.vue`：在 tab 列表加 `{ key: "geo", label: "AI 卡位" }`，`v-if` 渲染 `<GeoTaskModule />`（import 之）。参考现有 zhihu/comment/baidu tab 的注册方式。

- [ ] **Step 3: typecheck + 手动冒烟**

Run: `cd frontend && npx vue-tsc --noEmit`
Expected: 无新增报错

手动：起 dev（`npx tauri dev --no-watch`，参考 worktree cold-start memory），监测中心出现「AI 卡位」tab，能建任务（先在设置里配好 qwen + kimi key），点运行看进度条 + 信源榜。

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/monitor/geo/GeoTaskModule.vue frontend/src/views/MonitorView.vue
git commit -m "feat(geo): 监测中心「AI 卡位」tab（任务列表+run+SSE进度+信源榜）"
```

---

## Task 14: 数据中心「AI 卡位」pivot（GeoAnalyticsPage.vue）

**Files:**
- Create: `frontend/src/components/monitor/history/GeoAnalyticsPage.vue`
- Modify: `frontend/src/views/DataCenterView.vue`（加 sub-pivot）

> 参考 `frontend/src/components/monitor/history/ZhihuRankingPage.vue` + DataCenterView 现有 pivot 结构。

- [ ] **Step 1: 建 GeoAnalyticsPage.vue**

最小可用：选任务 → 4 KPI 卡（SoC 含色带 / 首推率 / 净情感分 / 信源榜 Top）+ 卡位矩阵（平台 × KPI，读 metric 的 `by_platform`）+ 信源榜表格（GET `/api/monitor/geo/{id}/citations`，可按 days 筛）。骨架同 Task 13 的表格 + KPI 卡，数据源用 `/api/monitor/results?task_id=`（取最新 metric）+ `/api/monitor/geo/{id}/citations`。

```vue
<script setup lang="ts">
import { ref } from "vue";
import { useSidecar } from "@/stores/sidecar";
import type { CitationRow } from "@/utils/monitor-types";
const sidecar = useSidecar();
const kpi = ref<any>(null);
const board = ref<CitationRow[]>([]);
async function load(taskId: number) {
  const r = await sidecar.client.get("/api/monitor/results", { params: { task_id: taskId, limit: 1 } });
  kpi.value = r.data.results?.[0]?.metric ?? null;
  const b = await sidecar.client.get(`/api/monitor/geo/${taskId}/citations`, { params: { days: 30 } });
  board.value = b.data.leaderboard ?? [];
}
defineExpose({ load });
</script>
<template>
  <div v-if="kpi">
    <!-- 4 KPI 卡 -->
    <div>曝光度 {{ (kpi.soc * 100).toFixed(0) }}% · {{ kpi.status_band }}</div>
    <div>首推率 {{ (kpi.first_rank_rate * 100).toFixed(0) }}%</div>
    <div>情感分 {{ kpi.sentiment_score.toFixed(2) }}</div>
    <!-- 卡位矩阵：平台 × KPI -->
    <table>
      <tr v-for="(v, plat) in kpi.by_platform" :key="plat">
        <td>{{ plat }}</td><td>{{ (v.soc * 100).toFixed(0) }}%</td>
        <td>{{ (v.first_rank_rate * 100).toFixed(0) }}%</td><td>{{ v.sentiment_score.toFixed(2) }}</td>
      </tr>
    </table>
    <!-- 信源榜 -->
    <table>
      <tr v-for="row in board" :key="row.domain">
        <td>{{ row.domain }}</td><td>{{ row.source_type }}</td><td>{{ row.count }}</td>
        <td>{{ row.keywords.join("、") }}</td>
      </tr>
    </table>
  </div>
</template>
```

- [ ] **Step 2: DataCenterView 加 pivot**

`frontend/src/views/DataCenterView.vue`：`HistorySubtab` 类型加 `"geo"`；`HISTORY_TABS` 加 `{ k: "geo", l: "AI 卡位" }`；`v-if` 渲染 `<GeoAnalyticsPage />`。

- [ ] **Step 3: typecheck + 冒烟**

Run: `cd frontend && npx vue-tsc --noEmit`
Expected: 无新增报错

手动：数据中心出现「AI 卡位」pivot，选任务后看到 4 KPI 卡 + 卡位矩阵 + 信源榜。

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/monitor/history/GeoAnalyticsPage.vue frontend/src/views/DataCenterView.vue
git commit -m "feat(geo): 数据中心「AI 卡位」pivot（KPI 卡+卡位矩阵+信源榜）"
```

---

## Task 15: 阶段 1 端到端验证 + 收尾

- [ ] **Step 1: 全套 core 测试**

Run: `pytest tests/core/monitor/ -v`
Expected: 全 PASS（含新增 geo/ 套件 + 现有 monitor 回归）

- [ ] **Step 2: sidecar 测试**

Run: `pytest sidecar/tests/test_geo_routes.py -v`
Expected: PASS

- [ ] **Step 3: 真实 API 冒烟（有 key 时，标 integration）**

在设置页配好 qwen + kimi key → 监测中心建一个真实任务（品牌 + 2-3 关键词 + 通义/Kimi）→ 运行 → 确认：
- 进度条到 N/N
- 数据中心 KPI 卡有真实 SoC/首推率/情感
- 信源榜出现真实域名（知乎/小红书等）
- **人工抽查 3-5 条**：打开 cell 原文，核对抽取的 mentioned/rank 是否准（校准 extract prompt）

把抽查结论 + 真实 fixture 回填 Task 1 的 fixture（若与预期形状不符）。

- [ ] **Step 4: 更新 CHANGELOG**

`CHANGELOG.md` 顶部加未发布条目（项目发版门禁要求）：
```markdown
### 新增
- AI 卡位监控（GEO）阶段 1：批量关键词 × 通义/Kimi 采集，曝光度/首推率/情感/信源榜，监测中心建任务 + 数据中心看分析。
```

- [ ] **Step 5: Commit + 收尾**

```bash
git add CHANGELOG.md
git commit -m "docs(changelog): GEO 卡位监控阶段 1"
```

---

## Self-Review 记录（写计划时已核对）

- **Spec 覆盖**：①探针(Task1) ②geo_query 注册(Task10) ③GeoProvider+通义/Kimi(Task6/7) ④抽取(Task8) ⑤分类(Task3) ⑥四大 KPI(Task4) ⑦v7 表(Task5) ⑧监测中心 tab(Task13) ⑨数据中心 pivot(Task14) — spec 阶段 1 清单逐条对应。阶段 2-3（豆包/RPA/调度告警/导出/引流闭环）不在本计划，按 spec §13 后续出。
- **类型一致**：`GeoCell`/`GeoExtraction`/`ClassifiedCitation` 字段名跨 Task 一致；`get_provider`/`build_extract_client`/`aggregate`/`representative_rank`/`record_run`/`citation_leaderboard`/`apply_v7_migration` 签名前后一致。
- **占位符**：Task4 Step1 有一处**故意**的占位断言，Step3 明确要求改正（非遗漏）。其余无 TBD。
- **已知风险**：Kimi `$web_search` 信源是否落在 `annotations` 需 Task1 探针确认；不符则按真实形状改 `parse_kimi_response`，仍拿不到则记 spec §14、阶段 3 降级 RPA。前端 SSE 字段名/`client` fixture/路由前缀以实际文件为准（各 Task 已标注「先读再写」）。
