# AI 卡位监控（GEO）· 阶段 2 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 补齐 GEO 的 API 层第三家平台（豆包 Ark）、信源榜 Excel 导出、调度（daily/weekly）+ 三类告警、信源榜→引流中心闭环，并收敛 V1 重做后冗余的数据中心 pivot。

**Architecture:** 全部建在 Phase 1 + V1 UI 之上（已 merge 到 main）。后端复用 `csm_core/monitor/geo/` provider/storage/metrics 范式 + `monitor_loop`/`notify`/`scheduler` 基建；前端在 V1 组件（`GeoSourceList` 等）上加按钮 + 收敛 `GeoAnalyticsPage`。豆包采集走 Ark **bot 联网端点**（探针确认），告警用纯函数 evaluator + 适配器写入 `metric["alerts"]`。

**Tech Stack:** Python 3.11 / pydantic v2 / httpx / sqlite3 / openpyxl / pytest（`integration` marker 留给真实 API）；Vue 3 + TS（vue-tsc 严格）。

**Spec:** `docs/superpowers/specs/2026-05-30-ai-geo-monitoring-design.md`（§13 阶段 2）
**前置:** Phase 1 + V1 UI 已 merge（`origin/main` `356c8fe`）。本工作树 `D:/CSM/.claude/worktrees/geo-phase2`，分支 `claude/geo-phase2`。

**约定（每个任务遵守）:**
- core 测试从仓库根跑 `python -m pytest tests/core/monitor/geo/<file> -v`。
- sidecar 测试 `PYTHONPATH="D:\CSM\.claude\worktrees\geo-phase2\sidecar" python -m pytest sidecar/tests/<file> -v`。
- 前端 typecheck `cd frontend; npx vue-tsc --noEmit`（先 junction node_modules：见 Task 0b）。
- Windows CI 下 print 仅 ASCII。每任务末尾 commit，message `feat(geo)/fix(geo)/test(geo)`，结尾加 `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`。

---

## 决策点（实施前/计划评审时与用户确认）

1. **豆包 Ark 联网机制**：Ark 的普通 `/chat/completions`（OpenAI 兼容）默认**不联网、不回信源**；联网 + `references` 走「应用（bot）」端点 `/api/v3/bots/chat/completions`（需用户在火山方舟控制台建一个开了「联网内容」插件的 bot，拿到 `bot_id`）。**Task 1 探针**实测确认：①是否需要 bot 端点 ②`references` 字段结构。provider 读一个新配置项 `doubao_bot_id`（用户在设置/任务里填）。**若用户暂无 Ark 联网 bot → 豆包采集挂起，Task 1/2 跳过，其余 Task 照做。**
2. **数据中心 `GeoAnalyticsPage` 去留**（Task 7）：V1 重做把全套分析（KPI/矩阵/趋势/信源/竞争）放进了**监测中心**详情，数据中心那个 per-task pivot 现在**冗余**。**本计划推荐：删掉数据中心的「AI 卡位」pivot + `GeoAnalyticsPage.vue`**（监测中心详情已覆盖），避免两套重复 UI。若用户想保留并改成「跨任务/跨品牌组合视图」，那是另一个增量，本计划不做——评审时确认。
3. **告警 cooldown**：复用现有 `cooldown_hours`（默认 24h）。三类告警**任一触发**即 `alert_triggered=True`；具体原因写进 `metric["alerts"]` 供 UI 展示。
4. **weekly 调度格式**：新增 `"weekly-<dow>-<HH:MM>"`（dow=0..6，0=周一），扩展现有 `scheduler.parse_schedule`/`is_task_due`，对所有任务类型通用。

---

## 文件结构（阶段 2 新建/改动）

**新建（core）**
```
csm_core/monitor/geo/providers/api_doubao.py   # 豆包 Ark bot 联网 provider + parse_doubao_response
csm_core/monitor/geo/alerts.py                 # 纯函数：evaluate_geo_alerts(result_metric, prev_metric) -> list[alert]
scripts/geo_doubao_probe.py                    # Task 1：豆包 Ark 联网探针
```
**改动（core）**
```
csm_core/monitor/geo/providers/base.py         # get_provider 加 doubao 分支
csm_core/monitor/platforms/geo_query.py        # fetch() 末尾算 geo alerts 写入 metric["alerts"]
csm_core/monitor/notify.py                     # should_alert 加 geo_query 分支
csm_core/monitor/scheduler.py                  # parse_schedule/is_task_due 支持 weekly-<dow>-<HH:MM>
csm_core/config.py                             # AppConfig 加 doubao_bot_id（或复用 default_model["doubao"] 放 bot_id）
```
**改动（sidecar）**
```
sidecar/csm-sidecar.spec                        # hiddenimports 加 api_doubao
sidecar/csm_sidecar/routes/monitor.py           # 新增 GET /api/monitor/geo/{task_id}/export（xlsx）
```
**改动（前端）**
```
frontend/src/components/monitor/geo/GeoSourceList.vue   # 「导出信源榜」按钮 + 每行「去引流中心铺」
frontend/src/components/monitor/geo/GeoKeywordDetail.vue（或父）# 透传 taskId/keyword 给 GeoSourceList
frontend/src/views/MiningView.vue               # watch route query → 预填 StartJobModal
frontend/src/views/DataCenterView.vue           # 删除「AI 卡位」pivot（Task 7）
frontend/src/components/monitor/AddTaskModal.vue + utils/monitor-types.ts  # geo 任务调度选项加 weekly
（删除）frontend/src/components/monitor/history/GeoAnalyticsPage.vue       # Task 7
```
**测试**
```
tests/core/monitor/geo/test_providers.py        # +豆包 parse 测试（fixture）
tests/core/monitor/geo/test_alerts.py           # 三类告警纯函数测试
tests/core/monitor/geo/test_geo_query_adapter.py# +adapter 写入 metric["alerts"]
tests/core/monitor/test_scheduler.py            # +weekly 调度测试
tests/core/monitor/test_notify.py               # +geo_query 告警分支测试
sidecar/tests/test_geo_routes.py                # +export 端点测试
tests/core/monitor/geo/fixtures/doubao_search.json
```

---

## Task 0b: junction 前端 node_modules（一次性，给后面前端任务 typecheck 用）

**Files:** 无（环境准备）

- [ ] **Step 1: junction node_modules（复用主仓，秒级，无 400MB 拷贝）**

PowerShell：
```powershell
$wt = "D:\CSM\.claude\worktrees\geo-phase2\frontend"
if (-not (Test-Path "$wt\node_modules")) {
  New-Item -ItemType Junction -Path "$wt\node_modules" -Target "D:\CSM\frontend\node_modules" | Out-Null
}
Set-Location $wt; npx vue-tsc --noEmit 2>&1 | Select-Object -Last 3
```
Expected: vue-tsc 干净（基线，未改任何代码）。若主仓 node_modules 缺包导致报错，改跑 `cd frontend; npm install`。
（不提交；node_modules 已 gitignore。）

---

## Task 1: 豆包 Ark 联网探针（强制前置；产出 fixture）

**为什么先做：** Ark 联网 + 信源字段未锁定。先用真实 key + bot_id 打一炮，确认机制 + 存 fixture。**无 key/bot → 跳过运行，用文档预期 fixture（Step 3），并在 PR 标注待校准。**

**Files:**
- Create: `scripts/geo_doubao_probe.py`
- Create: `tests/core/monitor/geo/fixtures/doubao_search.json`

- [ ] **Step 1: 写探针脚本**

```python
# scripts/geo_doubao_probe.py
"""豆包(火山方舟 Ark)联网探针 —— 手动运行，确认联网 + references 字段。

用法（需真实 key + 联网 bot_id）：
    ARK_API_KEY=xxx ARK_BOT_ID=bot-xxxx python scripts/geo_doubao_probe.py

Ark 联网走「应用(bot)」端点：POST https://ark.cn-beijing.volces.com/api/v3/bots/chat/completions
body 用 bot_id 当 model。联网结果常在 response 的 references / 自定义字段里。
跑完人工脱敏裁剪成 tests/core/monitor/geo/fixtures/doubao_search.json，确认信源(URL+标题)落在哪个字段。
"""
from __future__ import annotations
import json, os, sys
from pathlib import Path
import httpx

OUT = Path(__file__).resolve().parents[1] / "tests/core/monitor/geo/fixtures"
KEYWORD = "20万左右的新能源SUV推荐"
URL = "https://ark.cn-beijing.volces.com/api/v3/bots/chat/completions"


def probe(key: str, bot_id: str) -> dict:
    body = {"model": bot_id, "messages": [{"role": "user", "content": KEYWORD}], "stream": False}
    r = httpx.post(URL, headers={"Authorization": f"Bearer {key}"}, json=body, timeout=120)
    print("doubao http", r.status_code, "len", len(r.text))
    print("first 800:", r.text[:800])
    return r.json()


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    key = os.environ.get("ARK_API_KEY", "")
    bot = os.environ.get("ARK_BOT_ID", "")
    if not key or not bot:
        print("skip: need ARK_API_KEY + ARK_BOT_ID")
        return 0
    (OUT / "doubao_search.raw.json").write_text(
        json.dumps(probe(key, bot), ensure_ascii=False, indent=2), encoding="utf-8")
    print("wrote doubao_search.raw.json — 人工脱敏裁剪成 doubao_search.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: 运行（有 key+bot 时）**

Run: `python scripts/geo_doubao_probe.py`（设 `ARK_API_KEY` / `ARK_BOT_ID`）
Expected: 打印 http 200 + 响应前 800 字，生成 `doubao_search.raw.json`。**无 key/bot → 跳过，用 Step 3 fixture。**

- [ ] **Step 3: 落 fixture（脱敏；无 key 时用此预期形状）**

`tests/core/monitor/geo/fixtures/doubao_search.json`（Ark bot 联网响应的预期形状；真实不符则按真实改 + 改 Task 2 解析器）：
```json
{
  "choices": [{"index": 0, "finish_reason": "stop", "message": {
    "role": "assistant",
    "content": "20万左右新能源SUV，比较推荐比亚迪宋PLUS、小鹏G6、深蓝S7……",
    "references": [
      {"url": "https://zhuanlan.zhihu.com/p/123", "title": "2024新能源SUV推荐", "site_name": "知乎"},
      {"url": "https://www.xiaohongshu.com/explore/abc", "title": "小鹏G6实测", "site_name": "小红书"}
    ]
  }}],
  "usage": {"total_tokens": 640}
}
```
> **关键产出**：确认信源在 `choices[0].message.references[]`（含 `url`/`title`）。真实不同就改本 fixture + Task 2 的 `parse_doubao_response`。

- [ ] **Step 4: Commit**
```bash
git add scripts/geo_doubao_probe.py tests/core/monitor/geo/fixtures/doubao_search.json
git commit -m "feat(geo): 豆包 Ark 联网探针 + 响应 fixture"
```

---

## Task 2: 豆包 Ark provider（api_doubao.py + 注册 + spec）

**Files:**
- Create: `csm_core/monitor/geo/providers/api_doubao.py`
- Modify: `csm_core/monitor/geo/providers/base.py`（get_provider 加 doubao）
- Modify: `csm_core/config.py`（AppConfig 加 `doubao_bot_id: str = ""`）
- Modify: `sidecar/csm-sidecar.spec`（hiddenimports + api_doubao）
- Test: `tests/core/monitor/geo/test_providers.py`（追加豆包 parse + 错误路径）

- [ ] **Step 1: 写失败测试（豆包解析器，喂 fixture）**

追加到 `tests/core/monitor/geo/test_providers.py`：
```python
from csm_core.monitor.geo.providers.api_doubao import parse_doubao_response

def test_parse_doubao_extracts_answer_and_citations():
    raw = json.loads((FIX / "doubao_search.json").read_text(encoding="utf-8"))
    answer_text, citations = parse_doubao_response(raw)
    assert "小鹏G6" in answer_text
    urls = [c.url for c in citations]
    assert "https://zhuanlan.zhihu.com/p/123" in urls
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/core/monitor/geo/test_providers.py::test_parse_doubao_extracts_answer_and_citations -v`
Expected: FAIL — ImportError

- [ ] **Step 3: 写 api_doubao.py（镜像 api_kimi 的健壮性 + Ark bot 端点）**

```python
# csm_core/monitor/geo/providers/api_doubao.py
"""豆包(火山方舟 Ark)联网 provider —— 走「应用(bot)」端点拿 references。

Ark 普通 /chat/completions 不联网；联网 + 信源走 /api/v3/bots/chat/completions，
model 传用户在控制台建的联网 bot 的 bot_id（配置项 doubao_bot_id）。
key 用 keyring 'doubao' 项（read_api_key("doubao")，与 LLM provider 同 key）。
"""
from __future__ import annotations
import logging
import threading
import httpx

from csm_core.config import read_api_key, get_config
from csm_core.monitor.base import maybe_cancel
from ..models import GeoAnswer, Citation

logger = logging.getLogger(__name__)


def parse_doubao_response(raw: dict) -> tuple[str, list[Citation]]:
    choices = raw.get("choices") or []
    if not choices:
        return "", []
    msg = choices[0].get("message") or {}
    text = msg.get("content") or ""
    cits: list[Citation] = []
    # references 可能在 message.references 或顶层（按探针确认）；两处都看。
    refs = msg.get("references") or raw.get("references") or []
    for ref in refs:
        url = (ref or {}).get("url") or ""
        if not url:
            continue
        title = ref.get("title") or ""
        site = ref.get("site_name") or ""
        cits.append(Citation(url=url, title=f"{title} - {site}".strip(" -") if site else title))
    return text, cits


class DoubaoProvider:
    platform = "doubao"
    mode = "api"

    def __init__(self, *, bot_id: str | None = None, base_url: str | None = None,
                 timeout: float = 120.0) -> None:
        cfg = get_config()
        self._bot = bot_id or getattr(cfg, "doubao_bot_id", "") or ""
        self._base = base_url or cfg.base_urls.get("doubao") or "https://ark.cn-beijing.volces.com/api/v3"
        self._timeout = timeout

    def query(self, keyword: str, *, web_search: bool = True,
              cancel_token: "threading.Event | None" = None) -> GeoAnswer:
        maybe_cancel(cancel_token)
        key = read_api_key("doubao")
        if not key:
            return GeoAnswer(platform=self.platform, keyword=keyword,
                             status="error", error="豆包(doubao/Ark) API key 未配置")
        if not self._bot:
            return GeoAnswer(platform=self.platform, keyword=keyword, status="error",
                             error="豆包联网需配置 doubao_bot_id（控制台建联网 bot）")
        url = f"{self._base.rstrip('/')}/bots/chat/completions"
        body = {"model": self._bot, "messages": [{"role": "user", "content": keyword}], "stream": False}
        timeout = httpx.Timeout(connect=10.0, read=self._timeout, write=self._timeout, pool=10.0)
        try:
            r = httpx.post(url, headers={"Authorization": f"Bearer {key}"}, json=body, timeout=timeout)
        except httpx.HTTPError as e:
            return GeoAnswer(platform=self.platform, keyword=keyword, status="error", error=str(e))
        logger.info("[geo.doubao] kw=%s http=%d len=%d first200=%s",
                    keyword, r.status_code, len(r.text), r.text[:200].replace("\n", " "))
        if r.status_code >= 400:
            return GeoAnswer(platform=self.platform, keyword=keyword, status="error",
                             error=f"http {r.status_code}: {r.text[:300]}", raw={"status": r.status_code})
        try:
            raw = r.json()
        except Exception:
            return GeoAnswer(platform=self.platform, keyword=keyword, status="error",
                             error=f"非 JSON 响应 (http {r.status_code}): {r.text[:200]}")
        if isinstance(raw, dict) and raw.get("error"):
            err = raw["error"]
            m = err.get("message") if isinstance(err, dict) else str(err)
            return GeoAnswer(platform=self.platform, keyword=keyword, status="error",
                             error=f"ark error: {m}", raw=raw)
        fr = ((raw.get("choices") or [{}])[0]).get("finish_reason")
        if fr in ("content_filter", "sensitive"):
            return GeoAnswer(platform=self.platform, keyword=keyword, status="blocked",
                             error="内容被豆包安全过滤", raw=raw)
        text, cits = parse_doubao_response(raw)
        return GeoAnswer(platform=self.platform, keyword=keyword, answer_text=text,
                         citations=cits, raw=raw, status="ok" if text else "empty")
```

- [ ] **Step 4: 注册 + config + spec**

`csm_core/monitor/geo/providers/base.py` get_provider 加（在 kimi 分支后、final raise 前）：
```python
    if platform == "doubao":
        try:
            from .api_doubao import DoubaoProvider
        except ImportError as e:
            raise GeoProviderError(f"doubao provider 未就绪: {e}") from e
        return DoubaoProvider()
```
`csm_core/config.py` AppConfig 加字段（放 base_urls 附近）：`doubao_bot_id: str = ""`（用户配置联网 bot id）。
`sidecar/csm-sidecar.spec` 在 `"csm_core.monitor.geo.providers.api_kimi",` 后加 `"csm_core.monitor.geo.providers.api_doubao",`。

- [ ] **Step 5: 加错误路径测试**

追加到 `test_providers.py`（镜像 kimi 的 missing-key / 非 JSON）：
```python
import csm_core.monitor.geo.providers.api_doubao as doubao_mod

def test_doubao_missing_key_is_error(monkeypatch):
    monkeypatch.setattr(doubao_mod, "read_api_key", lambda p: "")
    ans = doubao_mod.DoubaoProvider(bot_id="bot-x").query("k", web_search=True)
    assert ans.status == "error"

def test_doubao_missing_bot_is_error(monkeypatch):
    monkeypatch.setattr(doubao_mod, "read_api_key", lambda p: "fake")
    ans = doubao_mod.DoubaoProvider(bot_id="").query("k", web_search=True)
    assert ans.status == "error" and "bot" in ans.error.lower()
```

- [ ] **Step 6: 跑测试 + 注册 sanity**

Run: `python -m pytest tests/core/monitor/geo/test_providers.py -v` → 全绿（含豆包 parse + 2 错误路径）。
Run: `python -c "from csm_core.monitor.geo.providers.base import get_provider; print(get_provider('doubao').platform)"` → `doubao`。

- [ ] **Step 7: Commit**
```bash
git add csm_core/monitor/geo/providers/api_doubao.py csm_core/monitor/geo/providers/base.py csm_core/config.py sidecar/csm-sidecar.spec tests/core/monitor/geo/test_providers.py
git commit -m "feat(geo): 豆包 Ark 联网 provider（bot 端点 + references）+ 注册 + spec hiddenimports"
```

---

## Task 3: 三类 GEO 告警（纯函数 evaluator）

**Files:**
- Create: `csm_core/monitor/geo/alerts.py`
- Test: `tests/core/monitor/geo/test_alerts.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/core/monitor/geo/test_alerts.py
from csm_core.monitor.geo.alerts import evaluate_geo_alerts


def test_hidden_alert_when_soc_below_20():
    cur = {"soc": 0.1, "first_rank_rate": 0.0, "by_platform": {}}
    alerts = evaluate_geo_alerts(cur, None)
    assert any(a["kind"] == "hidden" for a in alerts)


def test_no_hidden_when_soc_ok():
    cur = {"soc": 0.6, "first_rank_rate": 0.3, "by_platform": {}}
    assert evaluate_geo_alerts(cur, None) == []


def test_first_rank_drop_alert():
    prev = {"soc": 0.6, "first_rank_rate": 0.5, "by_platform": {}}
    cur = {"soc": 0.6, "first_rank_rate": 0.2, "by_platform": {}}  # 0.5→0.2 跌 0.3
    alerts = evaluate_geo_alerts(cur, prev)
    assert any(a["kind"] == "first_drop" for a in alerts)


def test_platform_dropped_alert():
    prev = {"soc": 0.6, "first_rank_rate": 0.4, "by_platform": {"tongyi": {"mentioned": 2}, "kimi": {"mentioned": 1}}}
    cur = {"soc": 0.4, "first_rank_rate": 0.2, "by_platform": {"tongyi": {"mentioned": 2}, "kimi": {"mentioned": 0}}}
    alerts = evaluate_geo_alerts(cur, prev)
    assert any(a["kind"] == "platform_dropped" and "kimi" in a["detail"] for a in alerts)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/core/monitor/geo/test_alerts.py -v`
Expected: FAIL — ImportError

- [ ] **Step 3: 写 alerts.py**

```python
# csm_core/monitor/geo/alerts.py
"""GEO 告警纯函数。比较本次运行 metric 与上次，返回触发的告警列表。

三类（spec §9）：
- hidden：本次曝光度 SoC < 阈值（默认 0.2）。
- first_drop：首推率较上次显著下降（默认跌幅 ≥ 0.1）。
- platform_dropped：某平台从「提及(>0)」变「未提及(0)」。

无 I/O、可单测。适配器在 fetch() 末尾调它，把结果塞进 metric["alerts"]；
notify.should_alert 的 geo 分支只看 metric["alerts"] 是否非空 + cooldown。
"""
from __future__ import annotations
from typing import Any


def evaluate_geo_alerts(
    result_metric: dict[str, Any],
    prev_metric: dict[str, Any] | None,
    *,
    hidden_threshold: float = 0.2,
    first_drop_threshold: float = 0.1,
) -> list[dict[str, str]]:
    alerts: list[dict[str, str]] = []
    soc = result_metric.get("soc")
    if isinstance(soc, (int, float)) and soc < hidden_threshold:
        alerts.append({"kind": "hidden", "detail": f"曝光度 {round(soc * 100)}% 低于 {round(hidden_threshold * 100)}%（隐身）"})
    if prev_metric:
        prev_first = prev_metric.get("first_rank_rate") or 0
        cur_first = result_metric.get("first_rank_rate") or 0
        if (prev_first - cur_first) >= first_drop_threshold:
            alerts.append({"kind": "first_drop", "detail": f"首推率 {round(prev_first * 100)}% → {round(cur_first * 100)}%"})
        prev_bp = prev_metric.get("by_platform") or {}
        cur_bp = result_metric.get("by_platform") or {}
        for plat, pb in prev_bp.items():
            cb = cur_bp.get(plat)
            if (pb or {}).get("mentioned", 0) > 0 and cb is not None and (cb or {}).get("mentioned", 0) == 0:
                alerts.append({"kind": "platform_dropped", "detail": f"{plat} 从提及变未提及"})
    return alerts
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/core/monitor/geo/test_alerts.py -v` → 4 passed

- [ ] **Step 5: Commit**
```bash
git add csm_core/monitor/geo/alerts.py tests/core/monitor/geo/test_alerts.py
git commit -m "feat(geo): 三类告警纯函数 evaluator（隐身/首推率下滑/平台掉出）"
```

---

## Task 4: 适配器写入 alerts + should_alert geo 分支

**Files:**
- Modify: `csm_core/monitor/platforms/geo_query.py`（fetch 末尾算 alerts → metric["alerts"]）
- Modify: `csm_core/monitor/notify.py`（should_alert 加 geo_query 分支）
- Test: `tests/core/monitor/geo/test_geo_query_adapter.py` + `tests/core/monitor/test_notify.py`

- [ ] **Step 1: 写失败测试（适配器写 alerts）**

追加到 `tests/core/monitor/geo/test_geo_query_adapter.py`（复用其 fresh_db + fake provider/client）：
```python
def test_fetch_writes_geo_alerts_into_metric(fresh_db, monkeypatch):
    # 隐身场景：fake provider 让所有 cell 未提及 → soc=0 < 0.2 → hidden 告警
    from csm_core.monitor.geo.models import GeoAnswer
    class MissProvider:
        def __init__(self, platform): self.platform = platform; self.mode = "api"
        def query(self, kw, *, web_search=True, cancel_token=None):
            return GeoAnswer(platform=self.platform, keyword=kw, answer_text="无关回答")
    monkeypatch.setattr(geo_mod, "get_provider", lambda p: MissProvider(p))
    class MissClient:
        def complete(self, *, system, user, temperature=None):
            return '{"mentioned":false,"target_rank":-1,"sentiment":"na","recommended":[],"summary":""}'
    monkeypatch.setattr(geo_mod, "build_extract_client", lambda p: MissClient())
    tid = storage.create_task(MonitorTask(type="geo_query", name="t", target_url="geo://b",
        config={"brand": "b", "keywords": ["k"], "platforms": ["tongyi"], "extract_provider": "mock"}))
    result = geo_mod.ADAPTER.fetch(storage.get_task(tid))
    assert any(a["kind"] == "hidden" for a in result.metric.get("alerts", []))
```

- [ ] **Step 2: 跑确认失败**

Run: `python -m pytest tests/core/monitor/geo/test_geo_query_adapter.py::test_fetch_writes_geo_alerts_into_metric -v`
Expected: FAIL（metric 无 "alerts"）

- [ ] **Step 3: 适配器写 alerts**

在 `csm_core/monitor/platforms/geo_query.py` `fetch()` 里，算完 `agg = metrics.aggregate(cells)` 之后、构造 MonitorResult 之前，加：
```python
        # 三类告警：与上次运行比较（上次 = 当前还没存，latest_result 即上一跑）。
        from ..geo.alerts import evaluate_geo_alerts
        from .. import storage as _storage
        prev = _storage.latest_result(task.id) if task.id else None
        prev_metric = prev.metric if prev else None
        agg["alerts"] = evaluate_geo_alerts(agg, prev_metric)
```
（`agg` 已含 soc/first_rank_rate/by_platform；evaluate_geo_alerts 读它们。）

- [ ] **Step 4: should_alert geo 分支**

`csm_core/monitor/notify.py` `should_alert` 开头加（在现有 status 检查后）：
```python
    # geo_query：告警逻辑不同 —— 看 metric["alerts"]（适配器已算好），任一非空 + cooldown。
    if task.type == "geo_query":
        if not (result.metric or {}).get("alerts"):
            return False
        if task.id is None:
            return False
        last = storage.last_alert_at(task.id)
        if last is None:
            return True
        return (datetime.utcnow() - last) >= timedelta(hours=max(1, cooldown_hours))
```
（放在 `if result.status != "ok": return False` 之后——失败运行不告警。）

加 `tests/core/monitor/test_notify.py`：
```python
def test_geo_query_alerts_trigger(fresh_db):
    from csm_core.monitor.base import MonitorTask, MonitorResult
    import datetime
    tid = storage.create_task(MonitorTask(type="geo_query", name="g", target_url="geo://b", config={"brand":"b"}))
    task = storage.get_task(tid)
    r = MonitorResult(task_id=tid, checked_at=datetime.datetime.utcnow(), status="ok", rank=-1,
                      metric={"alerts": [{"kind":"hidden","detail":"曝光度 10% 低于 20%"}]})
    assert should_alert(task, r, alert_top_n=5, cooldown_hours=24) is True

def test_geo_query_no_alerts_no_fire(fresh_db):
    from csm_core.monitor.base import MonitorTask, MonitorResult
    import datetime
    tid = storage.create_task(MonitorTask(type="geo_query", name="g2", target_url="geo://c", config={"brand":"c"}))
    r = MonitorResult(task_id=tid, checked_at=datetime.datetime.utcnow(), status="ok", rank=-1, metric={"alerts": []})
    assert should_alert(storage.get_task(tid), r, alert_top_n=5, cooldown_hours=24) is False
```
（`test_notify.py` 若无 `fresh_db` fixture，复用 `test_storage.py` 同款；或 import 它。看文件实际。）

- [ ] **Step 5: 跑测试**

Run: `python -m pytest tests/core/monitor/geo/test_geo_query_adapter.py tests/core/monitor/test_notify.py -v` → 全绿。
Run: `python -m pytest tests/core/monitor/geo/ -q` → 回归绿。

- [ ] **Step 6: Commit**
```bash
git add csm_core/monitor/platforms/geo_query.py csm_core/monitor/notify.py tests/core/monitor/geo/test_geo_query_adapter.py tests/core/monitor/test_notify.py
git commit -m "feat(geo): 适配器算三类告警写 metric[alerts] + should_alert geo 分支"
```

---

## Task 5: scheduler 支持 weekly + 前端调度选项

**Files:**
- Modify: `csm_core/monitor/scheduler.py`
- Modify: `frontend/src/utils/monitor-types.ts`（SCHEDULE_OPTIONS）+ `AddTaskModal.vue`（geo 分支调度下拉）
- Test: `tests/core/monitor/test_scheduler.py`

- [ ] **Step 1: 写失败测试（weekly）**

追加到 `tests/core/monitor/test_scheduler.py`（先读该文件看 fixture/import 风格）：
```python
import datetime
from csm_core.monitor.scheduler import parse_schedule, is_task_due
from csm_core.monitor.base import MonitorTask

def _task(cron, last=None):
    return MonitorTask(type="geo_query", name="t", target_url="geo://b", config={"brand":"b"},
                       schedule_cron=cron, enabled=True, last_check_at=last)

def test_weekly_due_on_matching_dow_after_time():
    # 2026-06-01 是周一(weekday=0)。weekly-0-09:00 → 周一 9:00 后到期。
    now = datetime.datetime(2026, 6, 1, 9, 30)   # 周一 9:30
    assert is_task_due(_task("weekly-0-09:00"), now) is True

def test_weekly_not_due_wrong_dow():
    now = datetime.datetime(2026, 6, 2, 9, 30)   # 周二
    assert is_task_due(_task("weekly-0-09:00"), now) is False

def test_weekly_not_due_before_time():
    now = datetime.datetime(2026, 6, 1, 8, 0)    # 周一 8:00（早于 9:00）
    assert is_task_due(_task("weekly-0-09:00"), now) is False

def test_weekly_not_re_due_same_day(/* already checked today */):
    now = datetime.datetime(2026, 6, 1, 10, 0)
    last = datetime.datetime(2026, 6, 1, 9, 1)   # 今天 9:01 已查
    assert is_task_due(_task("weekly-0-09:00", last), now) is False
```
（去掉非法的 `/* */` 注释——Python 用 `#`；上面第 4 个测试名改成 `test_weekly_not_re_due_same_day`，函数体保留。）

- [ ] **Step 2: 跑确认失败**

Run: `python -m pytest tests/core/monitor/test_scheduler.py -k weekly -v`
Expected: FAIL（weekly 当前不支持，is_task_due 返回 False/parse 返回 None）

- [ ] **Step 3: 扩展 scheduler（先读现有 parse_schedule/is_task_due 全文再改）**

在 `parse_schedule` 之外加一个 weekly 解析，并改 `is_task_due` 支持。建议结构：
```python
def parse_weekly(schedule: str):
    """'weekly-<dow>-<HH:MM>' → (dow:int 0..6, time) 或 None。dow 0=周一。"""
    import re
    m = re.fullmatch(r"weekly-([0-6])-(\d{1,2}):(\d{2})", schedule or "")
    if not m:
        return None
    dow, hh, mm = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if hh > 23 or mm > 59:
        return None
    from datetime import time as dtime
    return dow, dtime(hh, mm)
```
`is_task_due` 里：先判 daily（现有逻辑），再判 weekly——当 `parse_weekly(task.schedule_cron)` 命中：
```python
    wk = parse_weekly(task.schedule_cron)
    if wk is not None:
        dow, target = wk
        if now.weekday() != dow:
            return False
        from datetime import datetime as _dt
        target_today = _dt.combine(now.date(), target)
        if now < target_today:
            return False
        if task.last_check_at is not None and task.last_check_at >= target_today:
            return False
        return True
```
（保持现有 manual/HH:MM 分支不变；weekly 是新增分支。读现有文件把这段缝进 `is_task_due` 的正确位置。）

- [ ] **Step 4: 跑测试**

Run: `python -m pytest tests/core/monitor/test_scheduler.py -v` → 全绿（含现有 daily/manual 回归 + 4 weekly）。

- [ ] **Step 5: 前端调度选项**

`frontend/src/utils/monitor-types.ts` 的 `SCHEDULE_OPTIONS` 加 weekly 选项（如 `{ value: "weekly-0-09:00", label: "每周一 09:00" }`，按需多给几个常用 dow/时间）。`AddTaskModal.vue` 的 geo 分支调度下拉用这些选项（若 geo 分支当前没有调度选择，加一个 FormSelect 绑到 `schedule_cron`，含 manual / daily-09:00 / weekly-* 选项）。`cd frontend; npx vue-tsc --noEmit` 干净。

- [ ] **Step 6: Commit**
```bash
git add csm_core/monitor/scheduler.py tests/core/monitor/test_scheduler.py frontend/src/utils/monitor-types.ts frontend/src/components/monitor/AddTaskModal.vue
git commit -m "feat(geo): scheduler 支持 weekly-<dow>-<HH:MM> + 前端调度选项"
```

---

## Task 6: 信源榜 Excel 导出（端点 + 前端按钮）

**Files:**
- Modify: `sidecar/csm_sidecar/routes/monitor.py`（+ GET /geo/{task_id}/export）
- Modify: `frontend/src/components/monitor/geo/GeoSourceList.vue`（导出按钮）
- Test: `sidecar/tests/test_geo_routes.py`

- [ ] **Step 1: 写失败测试**

追加到 `sidecar/tests/test_geo_routes.py`（复用 `geo_seeded`/`client` fixture）：
```python
def test_geo_export_xlsx(client, geo_seeded):
    tid = geo_seeded
    r = client.get(f"/api/monitor/geo/{tid}/export?days=3650")
    assert r.status_code == 200
    assert "spreadsheetml" in r.headers["content-type"]
    assert r.content[:2] == b"PK"   # xlsx = zip，魔数 PK
```

- [ ] **Step 2: 跑确认失败（PYTHONPATH recipe）**

Run: `PYTHONPATH="D:\CSM\.claude\worktrees\geo-phase2\sidecar" python -m pytest sidecar/tests/test_geo_routes.py::test_geo_export_xlsx -v`
Expected: FAIL — 404

- [ ] **Step 3: 加 export 端点（镜像现有 geo 端点约定）**

在 `sidecar/csm_sidecar/routes/monitor.py` GEO 端点附近加：
```python
@router.get("/api/monitor/geo/{task_id}/export")
def geo_export(task_id: int, days: int = Query(default=30, ge=1, le=3650)):
    _require_storage()
    import io
    from openpyxl import Workbook
    from fastapi.responses import StreamingResponse
    from csm_core.monitor.geo import storage as geo_storage
    board = geo_storage.citation_leaderboard(task_id, days=days)
    wb = Workbook(); ws = wb.active; ws.title = "信源榜"
    ws.append(["排名", "域名", "类型", "引用次数", "覆盖平台数", "命中关键词"])
    for i, b in enumerate(board, start=1):
        ws.append([i, b["domain"], b["source_type"], b["count"],
                   len(b["platforms"]), " / ".join(b["keywords"])])
    buf = io.BytesIO(); wb.save(buf); buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="geo_citations_{task_id}.xlsx"'},
    )
```
（`_require_storage`/`Query`/`router` 按文件实际写法对齐；端点路径前缀别重复。）

- [ ] **Step 4: 跑测试通过**

Run: `PYTHONPATH="...\sidecar" python -m pytest sidecar/tests/test_geo_routes.py -v` → 全绿（含 export）。

- [ ] **Step 5: 前端导出按钮**

`GeoSourceList.vue` 顶部加「导出信源榜」按钮。带 token 的下载（GET 需 Bearer auth → 用 fetch+blob，不能裸 window.open）：
```ts
import { useSidecar } from "@/stores/sidecar";
const sidecar = useSidecar();
const props = defineProps<{ board: BoardRow[]; total: number; taskId: number }>();
async function exportXlsx() {
  const r = await sidecar.client.get(`/api/monitor/geo/${props.taskId}/export`, {
    params: { days: 30 }, responseType: "blob",
  });
  const url = URL.createObjectURL(r.data);
  const a = document.createElement("a");
  a.href = url; a.download = `geo_citations_${props.taskId}.xlsx`; a.click();
  URL.revokeObjectURL(url);
}
```
父组件（GeoKeywordDetail 或哪里渲染 GeoSourceList）把 `taskId` 透传进来。`vue-tsc --noEmit` 干净。

- [ ] **Step 6: Commit**
```bash
git add sidecar/csm_sidecar/routes/monitor.py sidecar/tests/test_geo_routes.py frontend/src/components/monitor/geo/GeoSourceList.vue frontend/src/components/monitor/geo/GeoKeywordDetail.vue
git commit -m "feat(geo): 信源榜 Excel 导出端点 + 前端导出按钮"
```

---

## Task 7: 信源榜→引流中心闭环 + 数据中心 pivot 收敛

**Files:**
- Modify: `frontend/src/components/monitor/geo/GeoSourceList.vue`（每行「去引流中心铺」）
- Modify: `frontend/src/views/MiningView.vue`（watch route query 预填 StartJobModal）
- Modify: `frontend/src/views/DataCenterView.vue`（删「AI 卡位」pivot）
- Delete: `frontend/src/components/monitor/history/GeoAnalyticsPage.vue`

> **决策点 2**：本任务**删除**数据中心冗余的「AI 卡位」pivot（监测中心详情已覆盖全套分析）。评审若改为「保留并重构成跨任务组合视图」，本任务只做闭环、跳过删除。

- [ ] **Step 1: 闭环按钮（GeoSourceList 每行）**

每行第三列加一个小按钮「去引流中心铺」（带 domain），点击：
```ts
import { useRouter } from "vue-router";
const router = useRouter();
const props = defineProps<{ board: BoardRow[]; total: number; taskId: number; keyword: string }>();
function goMining(domain: string) {
  router.push({ name: "mining", query: { geo_keyword: props.keyword, geo_source: domain } });
}
```
（父透传 `keyword`。按钮样式跟 V1 既有小按钮一致。）

- [ ] **Step 2: MiningView 接 query 预填**

`MiningView.vue` 加：
```ts
import { useRoute } from "vue-router";
const route = useRoute();
onMounted(() => {
  const kw = route.query.geo_keyword as string | undefined;
  if (kw) { prefillKeyword.value = kw; showNewTask.value = true; }  // 打开 StartJobModal 并预填关键词
});
```
`StartJobModal` 加可选 `:prefill-keyword` prop，mounted 时把 `kw` 填进输入框（`geo_source` 域名作为提示文案显示，不强制按域名过滤——spec 说 v1 只跳转带参）。`vue-tsc --noEmit` 干净。

- [ ] **Step 3: 删数据中心冗余 pivot**

`DataCenterView.vue`：从 `HistorySubtab` 去掉 `"geo"`、`HISTORY_TABS` 去掉 `{ k: "geo", l: "AI 卡位" }`、删掉 `<GeoAnalyticsPage>` 渲染分支 + import + `goToGeoTask`。删除 `frontend/src/components/monitor/history/GeoAnalyticsPage.vue`。确认没有其它地方 import GeoAnalyticsPage（grep）。`vue-tsc --noEmit` 干净。

- [ ] **Step 4: typecheck + commit**

Run: `cd frontend; npx vue-tsc --noEmit` → 干净。
```bash
git add frontend/src/components/monitor/geo/GeoSourceList.vue frontend/src/views/MiningView.vue frontend/src/components/mining/StartJobModal.vue frontend/src/views/DataCenterView.vue
git rm frontend/src/components/monitor/history/GeoAnalyticsPage.vue
git commit -m "feat(geo): 信源榜→引流中心闭环跳转 + 删除数据中心冗余 AI 卡位 pivot"
```

---

## Task 8: 端到端验证 + CHANGELOG

- [ ] **Step 1: 全套 geo + 相关回归**

Run: `python -m pytest tests/core/monitor/geo/ tests/core/monitor/test_scheduler.py tests/core/monitor/test_notify.py tests/core/monitor/test_storage.py -v` → 全绿。
Run: `PYTHONPATH="...\sidecar" python -m pytest sidecar/tests/test_geo_routes.py -v` → 全绿。
Run: `cd frontend; npx vue-tsc --noEmit` → 干净。

- [ ] **Step 2: 真实冒烟（有 Ark bot 时，标 integration）**

设置页配 doubao key + 在任务里填 doubao_bot_id → 建含 doubao 的 GEO 任务 → 运行 → 确认豆包 cell 有信源；设 weekly 调度看是否到期触发；制造一次 SoC<20% 看告警；点导出拿到 xlsx；点「去引流中心铺」跳转预填。**人工抽查豆包抽取准确性。**

- [ ] **Step 3: CHANGELOG**

`CHANGELOG.md` 的 `## [Unreleased]` → `### Added` 追加：
```markdown
- **GEO 阶段 2**：豆包(火山方舟 Ark 联网 bot)采集接入（第三家 API 平台）；信源榜一键导出 Excel；GEO 任务支持每周调度 + 三类告警（隐身 SoC<20% / 首推率下滑 / 平台掉出）；信源榜每行「去引流中心铺这个源」跳转带参；数据中心冗余「AI 卡位」pivot 收敛（分析统一在监测中心详情）。
```

- [ ] **Step 4: Commit**
```bash
git add CHANGELOG.md
git commit -m "docs(changelog): GEO 阶段 2"
```

---

## Self-Review 记录（写计划时已核对）

- **Spec 覆盖**（§13 阶段 2）：①豆包 Ark provider→Task 1-2 ②Excel 导出→Task 6 ③调度 weekly+三类告警→Task 3-5 ④信源榜→引流闭环→Task 7。原计划的「卡位矩阵/趋势/下钻」V1 已交付，本计划不重做（已在决策点说明）。
- **类型一致**：`evaluate_geo_alerts(result_metric, prev_metric)`、`parse_doubao_response`、`DoubaoProvider`、`parse_weekly` 签名跨任务一致；告警 `{kind, detail}` 形状统一；adapter 写 `metric["alerts"]`、notify 读它，口径一致。
- **占位符**：无 TBD；豆包 fixture 标「探针校准」、Ark bot 机制标决策点 1，均带解决路径。Task 5 Step1 第 4 个测试的非法注释已在步内注明改正。
- **已知风险**：①豆包 Ark 联网必须有 bot（决策点 1）——无 bot 则 Task 1-2 挂起、其余照做；②`references` 字段位置待探针确认；③should_alert 加 `task.type` 分支不影响其它任务类型（仅 geo_query 走新分支）；④删 GeoAnalyticsPage 前 grep 确认无其它引用。
