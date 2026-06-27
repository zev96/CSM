# 禁区 lint 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 成稿里 emoji / 破折号 / 双引号 / 绝对化用语 / 引流话术 / 元话术六类确定性扫描 → 机械类一键清 + 判断类人工放行 → 软拦导出。

**Architecture:** 引擎 `csm_core/lint/`（纯函数）→ 无状态 `POST /api/lint` → 前端编排软拦（自动扫 + LintPanel + onExportClick 守卫）。隔离 finalize/export/factcheck-resume 脆弱链。详见 `docs/superpowers/specs/2026-06-27-forbidden-zone-lint-design.md`。

**Tech Stack:** Python（pydantic + re）/ FastAPI sidecar / Vue 3 + Pinia + TS。

**测试命令（worktree 无 .venv，用主仓解释器 + PYTHONPATH 覆盖）：**
- csm_core：
  ```powershell
  $env:PYTHONPATH="D:\CSM\.claude\worktrees\busy-matsumoto-c087bd"; & "D:\CSM\.venv\Scripts\python.exe" -X utf8 -m pytest tests/core/lint/ -v
  ```
- sidecar（双路径，否则测到主仓 editable 旧码）：
  ```powershell
  $env:PYTHONPATH="D:\CSM\.claude\worktrees\busy-matsumoto-c087bd;D:\CSM\.claude\worktrees\busy-matsumoto-c087bd\sidecar"; & "D:\CSM\.venv\Scripts\python.exe" -X utf8 -m pytest sidecar/tests/test_lint_service.py sidecar/tests/test_lint_routes.py -v
  ```
- 前端（worktree 若无 node_modules 先 `cd frontend; npm ci`）：
  ```powershell
  cd frontend; npx vitest run src/stores/__tests__/article.lint.spec.ts src/components/article/__tests__/LintPanel.spec.ts src/views/__tests__/ArticleView.lint.spec.ts
  cd frontend; npx vue-tsc -b
  ```

---

## File Structure

**Unit A — 引擎（纯函数，零 IO）**
- Create: `csm_core/lint/__init__.py` — 导出 `build_rules/scan/autofix/build_report/LintHit/LintReport/Category`
- Create: `csm_core/lint/model.py` — `LintHit` / `LintReport`
- Create: `csm_core/lint/rules.py` — 默认词表 + 正则 + `Rules` + `build_rules`
- Create: `csm_core/lint/scanner.py` — `scan` / `autofix` / `build_report` + helpers
- Modify: `csm_core/config.py` — 加 `LintConfig` + `AppConfig.lint`
- Test: `tests/core/lint/__init__.py`、`tests/core/lint/test_rules.py`、`tests/core/lint/test_scanner.py`

**Unit B — sidecar**
- Create: `sidecar/csm_sidecar/services/lint_service.py`
- Create: `sidecar/csm_sidecar/routes/lint.py`
- Modify: `sidecar/csm_sidecar/main.py` — 注册 router
- Test: `sidecar/tests/test_lint_service.py`、`sidecar/tests/test_lint_routes.py`

**Unit C — 前端**
- Modify: `frontend/src/stores/article.ts` — `LintHit`/state/getter/actions/自动 runLint/reset
- Create: `frontend/src/components/article/LintPanel.vue`
- Modify: `frontend/src/views/ArticleView.vue` — onExportClick 守卫 + watch 自动弹 + 质检卡第 7 项 + 渲染 LintPanel + FactCheckPanel @lint
- Modify: `frontend/src/components/article/FactCheckPanel.vue` — recheckExport 前置 lint 守卫
- Test: `frontend/src/stores/__tests__/article.lint.spec.ts`、`frontend/src/components/article/__tests__/LintPanel.spec.ts`、`frontend/src/views/__tests__/ArticleView.lint.spec.ts`

---

# Unit A — csm_core/lint 引擎

## Task A1: LintConfig + model

**Files:**
- Modify: `csm_core/config.py`
- Create: `csm_core/lint/__init__.py`、`csm_core/lint/model.py`
- Create: `tests/core/lint/__init__.py`、`tests/core/lint/test_rules.py`

- [ ] **Step 1: 失败测试**（`tests/core/lint/__init__.py` 空文件 + `tests/core/lint/test_rules.py`）

```python
from csm_core.config import AppConfig, LintConfig
from csm_core.lint.model import LintHit, LintReport


def test_lint_config_defaults():
    c = LintConfig()
    assert c.enabled is True
    assert c.extra_meta == [] and c.extra_absolute == [] and c.extra_traffic == []
    assert c.disabled_categories == []


def test_appconfig_has_lint_default():
    # 旧 settings.json 无 lint 键也安全：model_validate 补默认
    cfg = AppConfig.model_validate({})
    assert cfg.lint.enabled is True


def test_lint_models_construct():
    h = LintHit(category="absolute", text="最佳", start=3, end=5,
                sentence="这是最佳之选", fixable=False, suggestion="改写")
    assert h.category == "absolute" and h.fixable is False
    r = LintReport(hits=[h], fixed_text="原文")
    assert r.fixed_text == "原文" and len(r.hits) == 1
```

- [ ] **Step 2: 跑测试确认失败**

Run: csm_core 测试命令（见顶部）指向 `tests/core/lint/test_rules.py`
Expected: FAIL（`ImportError: LintConfig` / `csm_core.lint`）

- [ ] **Step 3: 实现**

`csm_core/lint/model.py`：
```python
"""禁区 lint 结果模型。"""
from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, Field

Category = Literal["meta_speak", "absolute", "traffic", "emoji", "dash", "quote"]


class LintHit(BaseModel):
    category: Category
    text: str          # 命中原文片段
    start: int         # 字符偏移
    end: int           # start + len(text)
    sentence: str      # 所在句子（≤80）
    fixable: bool      # True=机械三类，可一键清
    suggestion: str


class LintReport(BaseModel):
    hits: list[LintHit] = Field(default_factory=list)
    fixed_text: str
```

`csm_core/lint/__init__.py`：
```python
"""禁区 lint 引擎：确定性扫描成稿违规措辞/标点。"""
from .model import Category, LintHit, LintReport
from .rules import Rules, build_rules
from .scanner import autofix, build_report, scan

__all__ = [
    "Category", "LintHit", "LintReport", "Rules",
    "build_rules", "scan", "autofix", "build_report",
]
```

`csm_core/config.py` — 在已有 `BrandMemoryConfig` 旁加（与 pricing/brand_memory 并列），并挂进 `AppConfig`：
```python
class LintConfig(BaseModel):
    enabled: bool = True
    extra_meta: list[str] = Field(default_factory=list)
    extra_absolute: list[str] = Field(default_factory=list)
    extra_traffic: list[str] = Field(default_factory=list)
    disabled_categories: list[str] = Field(default_factory=list)
```
`AppConfig` 内新增字段：`lint: LintConfig = Field(default_factory=LintConfig)`（紧跟既有 `brand_memory` / `pricing` 字段风格；若它们用 `= BrandMemoryConfig()` 直接默认则照抄该写法）。

> 注：`__init__.py` 同时 import rules/scanner，但本 Task 只测 config+model。A2/A3 落 rules/scanner 后整包才 import 成功——故 Step 4 暂只跑 `test_rules.py` 里这三个测试函数（用 `-k` 选中），或先把 `__init__.py` 的 rules/scanner import 留到 A3 完成。**实现顺序**：先建 `model.py` + config 改动跑通本 Task，`__init__.py` 的完整导出留到 A3 末尾再补，避免中途 import 崩。本 Task 的 `__init__.py` 先只写 `from .model import Category, LintHit, LintReport`。

- [ ] **Step 4: 跑测试确认通过**

Run: `... -m pytest tests/core/lint/test_rules.py -v`
Expected: 3 passed

- [ ] **Step 5: commit**

```bash
git add csm_core/lint/__init__.py csm_core/lint/model.py csm_core/config.py tests/core/lint/
git commit -m "feat(lint): LintConfig + LintHit/LintReport 模型"
```

---

## Task A2: rules.py（词表 + build_rules）

**Files:**
- Create: `csm_core/lint/rules.py`
- Modify: `tests/core/lint/test_rules.py`（追加）

- [ ] **Step 1: 失败测试**（追加到 `test_rules.py`）

```python
from csm_core.lint.rules import build_rules, DEFAULT_ABSOLUTE, DEFAULT_TRAFFIC, DEFAULT_META


def test_build_rules_defaults():
    r = build_rules(None)
    assert "最佳" in r.absolute and "加微信" in r.traffic and "软文" in r.meta
    assert r.check_emoji and r.check_dash and r.check_quote


def test_build_rules_extends_not_replaces():
    r = build_rules(LintConfig(extra_absolute=["史诗级"]))
    assert "史诗级" in r.absolute and "最佳" in r.absolute  # 加而非替
    # 去重保序：默认词不因 extra 重复出现两次
    assert list(r.absolute).count("最佳") == 1


def test_build_rules_disable_category():
    r = build_rules(LintConfig(disabled_categories=["quote", "meta_speak"]))
    assert r.check_quote is False
    assert r.meta == ()          # 词类禁用 → 空
    assert r.check_emoji is True  # 未禁用的不受影响
```

- [ ] **Step 2: 跑测试确认失败** — Expected: FAIL（`ImportError: build_rules`）

- [ ] **Step 3: 实现** `csm_core/lint/rules.py`

```python
"""禁区 lint 规则：默认词表/正则 + config 覆盖合并。"""
from __future__ import annotations
import re
from dataclasses import dataclass

from csm_core.config import LintConfig

DEFAULT_META = ["广告", "推广", "赞助", "软文"]

# 绝对化 = 广告法极限词 + 承诺词。curated 短语，默认不含裸「最」/温度词（最近/最后/
# 最终/最初）/测量歧义前缀（最大/最高/最小/最低）——嫌漏经 extra_absolute 加严。
DEFAULT_ABSOLUTE = [
    "最佳", "最好", "最强", "最优", "最先进", "最值得", "最顶级", "最专业",
    "第一", "首个", "首选", "唯一", "独家", "顶级", "极致", "国家级", "世界级",
    "百分百", "100%", "绝对", "永久", "永不", "万能", "根治", "彻底根除", "包治",
    "史上最", "全网最", "全国最", "零缺陷", "永不衰减", "100%安全",
]

DEFAULT_TRAFFIC = [
    "点击下方链接", "点击链接", "戳链接", "链接在评论", "关注账号", "关注我",
    "抽奖", "免费领", "免费送", "加微信", "加V", "扫码", "扫描二维码",
    "私信", "私我", "主页领", "简介领",
]

EMOJI_PATTERN = re.compile(
    "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF"
    "\U00002B00-\U00002BFF\U00002300-\U000023FF\U0000FE00-\U0000FE0F"
    "\U0000200D\U000020E3]+"
)
DASH_PATTERN = re.compile(r"[—―]+")
QUOTE_CHARS = "“”\""   # “ ”（U+201C/201D）+ ASCII "；不含「」/单引号


@dataclass(frozen=True)
class Rules:
    meta: tuple[str, ...]
    absolute: tuple[str, ...]
    traffic: tuple[str, ...]
    check_emoji: bool
    check_dash: bool
    check_quote: bool


def _merge(default: list[str], extra: list[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    out: list[str] = []
    for w in (*default, *extra):
        if w and w not in seen:
            seen.add(w)
            out.append(w)
    return tuple(out)


def build_rules(config: LintConfig | None) -> Rules:
    config = config or LintConfig()
    disabled = set(config.disabled_categories)
    return Rules(
        meta=() if "meta_speak" in disabled else _merge(DEFAULT_META, config.extra_meta),
        absolute=() if "absolute" in disabled else _merge(DEFAULT_ABSOLUTE, config.extra_absolute),
        traffic=() if "traffic" in disabled else _merge(DEFAULT_TRAFFIC, config.extra_traffic),
        check_emoji="emoji" not in disabled,
        check_dash="dash" not in disabled,
        check_quote="quote" not in disabled,
    )
```

- [ ] **Step 4: 跑测试确认通过** — Expected: A1 的 3 个 + A2 的 3 个 = 6 passed

- [ ] **Step 5: commit**

```bash
git add csm_core/lint/rules.py tests/core/lint/test_rules.py
git commit -m "feat(lint): rules 词表 + build_rules（extend/禁用）"
```

---

## Task A3: scanner.scan（扫描 + 定位 + 去重）

**Files:**
- Create: `csm_core/lint/scanner.py`
- Modify: `csm_core/lint/__init__.py`（补 rules/scanner 导出）
- Create: `tests/core/lint/test_scanner.py`

- [ ] **Step 1: 失败测试** `tests/core/lint/test_scanner.py`

```python
from csm_core.lint.rules import build_rules
from csm_core.lint.scanner import scan

R = build_rules(None)


def cats(text):
    return [h.category for h in scan(text, R)]


def test_hits_each_category():
    assert "absolute" in cats("这是最佳之选")
    assert "traffic" in cats("加微信领取福利")
    assert "meta_speak" in cats("这其实是软文")
    assert "emoji" in cats("好用😀")
    assert "dash" in cats("高效——安静")
    assert "quote" in cats("所谓“静音”")


def test_absolute_no_false_positive():
    # 温度/序数词不该误报
    assert scan("最近更新了固件", R) == []
    assert scan("最后一步是清洁", R) == []
    assert scan("最初的设计", R) == []


def test_offsets_and_sentence():
    text = "前言。这款是最佳选择！下一句"
    hits = scan(text, R)
    h = next(h for h in hits if h.text == "最佳")
    assert text[h.start:h.end] == "最佳"
    assert h.sentence == "这款是最佳选择"   # 句子边界内、去标点


def test_dedup_longest_wins():
    # "100%安全" 与子串 "100%" 都在词表 → 只留最长
    hits = [h for h in scan("本机100%安全", R) if h.category == "absolute"]
    assert len(hits) == 1 and hits[0].text == "100%安全"


def test_sorted_by_start():
    hits = scan("😀开头最佳结尾加微信", R)
    starts = [h.start for h in hits]
    assert starts == sorted(starts)


def test_empty_text():
    assert scan("", R) == []
    assert scan("普通干净的一段文字。", R) == []
```

- [ ] **Step 2: 跑测试确认失败** — Expected: FAIL（`ImportError: scan`）

- [ ] **Step 3: 实现** `csm_core/lint/scanner.py`

```python
"""禁区 lint 扫描 + 一键清。纯函数。"""
from __future__ import annotations
import re

from .model import LintHit, LintReport
from .rules import DASH_PATTERN, EMOJI_PATTERN, QUOTE_CHARS, Rules

_SENT_BOUND = set("。！？!?\n")
_PRIORITY = {"meta_speak": 0, "absolute": 1, "traffic": 2, "emoji": 3, "dash": 4, "quote": 5}

_SUGGEST = {
    "meta_speak": "删除或改写：避免「广告/推广/软文」等元话术",
    "absolute": "改为非绝对化表述（避开 最/第一/100% 等极限词）",
    "traffic": "删除引流话术（平台违规）",
    "emoji": "删除 emoji",
    "dash": "改为逗号或删除",
    "quote": "删除双引号（保留内文）",
}


def _sentence_at(text: str, pos: int, cap: int = 80) -> str:
    start = pos
    while start > 0 and text[start - 1] not in _SENT_BOUND:
        start -= 1
    end = pos
    while end < len(text) and text[end] not in _SENT_BOUND:
        end += 1
    return text[start:end].strip()[:cap]


# (start, end, text, category, fixable)
def _word_hits(text, words, category):
    out = []
    for w in words:
        i = text.find(w)
        while i != -1:
            out.append((i, i + len(w), w, category, False))
            i = text.find(w, i + 1)
    return out


def scan(text: str, rules: Rules) -> list[LintHit]:
    raw: list[tuple] = []
    raw += _word_hits(text, rules.meta, "meta_speak")
    raw += _word_hits(text, rules.absolute, "absolute")
    raw += _word_hits(text, rules.traffic, "traffic")
    if rules.check_emoji:
        raw += [(m.start(), m.end(), m.group(), "emoji", True) for m in EMOJI_PATTERN.finditer(text)]
    if rules.check_dash:
        raw += [(m.start(), m.end(), m.group(), "dash", True) for m in DASH_PATTERN.finditer(text)]
    if rules.check_quote:
        raw += [(i, i + 1, ch, "quote", True) for i, ch in enumerate(text) if ch in QUOTE_CHARS]

    # 排序：起点升序 → 长度降序 → 优先级。贪心取不重叠（最长/最高优先覆盖）。
    raw.sort(key=lambda h: (h[0], -(h[1] - h[0]), _PRIORITY[h[3]]))
    chosen, occupied_end = [], -1
    for h in raw:
        if h[0] >= occupied_end:
            chosen.append(h)
            occupied_end = h[1]
    chosen.sort(key=lambda h: h[0])
    return [
        LintHit(category=c, text=t, start=s, end=e,
                sentence=_sentence_at(text, s), fixable=f, suggestion=_SUGGEST[c])
        for (s, e, t, c, f) in chosen
    ]
```

`csm_core/lint/__init__.py` — 现在补全导出（A1 注释里说的延后到此）：保持 Task A1 的完整版本（已含 rules/scanner import）。

- [ ] **Step 4: 跑测试确认通过** — Expected: test_scanner 全 passed；`tests/core/lint/` 整目录也通过

- [ ] **Step 5: commit**

```bash
git add csm_core/lint/scanner.py csm_core/lint/__init__.py tests/core/lint/test_scanner.py
git commit -m "feat(lint): scan 扫描 + 句子定位 + 最长优先去重"
```

---

## Task A4: scanner.autofix + build_report

**Files:**
- Modify: `csm_core/lint/scanner.py`（追加 `autofix`/`build_report`）
- Modify: `tests/core/lint/test_scanner.py`（追加）

- [ ] **Step 1: 失败测试**（追加）

```python
from csm_core.lint.scanner import autofix, build_report


def test_autofix_mechanical_only():
    t = "好用😀高效——安静，所谓“静音”模式，业内最佳"
    fixed = autofix(t, R)
    assert "😀" not in fixed
    assert "——" not in fixed and "，安静" in fixed   # —— → ，
    assert "“" not in fixed and "”" not in fixed and "静音模式" in fixed
    assert "最佳" in fixed                            # 判断类不动


def test_autofix_idempotent():
    t = "a😀b——c“d”最强"
    assert autofix(autofix(t, R), R) == autofix(t, R)


def test_autofix_collapses_commas():
    # —— 在句末不产生 。，；多个 —— 不堆叠逗号
    assert autofix("结束。——开始", R) == "结束。开始"
    assert autofix("a————b", R) == "a，b"


def test_build_report_shape():
    rep = build_report("最佳😀", R)
    assert any(h.category == "absolute" for h in rep.hits)
    assert "😀" not in rep.fixed_text and "最佳" in rep.fixed_text
```

- [ ] **Step 2: 跑测试确认失败** — Expected: FAIL（`ImportError: autofix`）

- [ ] **Step 3: 实现**（追加到 `scanner.py`）

```python
def autofix(text: str, rules: Rules) -> str:
    """只清机械三类：emoji 删 / 破折号→逗号 / 双引号删（保留内文）。判断类不动。幂等。"""
    t = text
    if rules.check_emoji:
        t = EMOJI_PATTERN.sub("", t)
    if rules.check_dash:
        t = DASH_PATTERN.sub("，", t)
        t = re.sub("，{2,}", "，", t)            # 合并连续逗号
        t = re.sub(r"([。！？!?])，", r"\1", t)   # 句末标点后多余逗号去掉
    if rules.check_quote:
        t = "".join(ch for ch in t if ch not in QUOTE_CHARS)
    return t


def build_report(text: str, rules: Rules) -> LintReport:
    return LintReport(hits=scan(text, rules), fixed_text=autofix(text, rules))
```

- [ ] **Step 4: 跑测试确认通过** — Expected: `tests/core/lint/` 全绿

- [ ] **Step 5: commit**

```bash
git add csm_core/lint/scanner.py tests/core/lint/test_scanner.py
git commit -m "feat(lint): autofix 机械类一键清（幂等）+ build_report"
```

---

# Unit B — sidecar lint service + 路由 + config

## Task B1: lint_service.scan_text（config 隔离）

**Files:**
- Create: `sidecar/csm_sidecar/services/lint_service.py`
- Create: `sidecar/tests/test_lint_service.py`

> **config 隔离铁律**（[[feedback_csm_baidu_fetch_test_config_isolation]]）：测试**必须** monkeypatch `config_service.load` 返回受控 `AppConfig`，否则会读开发机真实 settings.json，结果不可复现。

- [ ] **Step 1: 失败测试** `sidecar/tests/test_lint_service.py`

```python
import pytest
from csm_core.config import AppConfig, LintConfig
from csm_sidecar.services import lint_service


@pytest.fixture
def patch_cfg(monkeypatch):
    def _set(lint: LintConfig):
        monkeypatch.setattr(lint_service.config_service, "load",
                            lambda: AppConfig(lint=lint))
    return _set


def test_scan_text_hits(patch_cfg):
    patch_cfg(LintConfig())
    out = lint_service.scan_text("业内最佳，加微信😀")
    cats = {h["category"] for h in out["hits"]}
    assert {"absolute", "traffic", "emoji"} <= cats
    assert "😀" not in out["fixed_text"]


def test_scan_text_disabled_returns_empty(patch_cfg):
    patch_cfg(LintConfig(enabled=False))
    out = lint_service.scan_text("业内最佳😀")
    assert out == {"hits": [], "fixed_text": "业内最佳😀"}


def test_scan_text_config_extra_applies(patch_cfg):
    patch_cfg(LintConfig(extra_traffic=["私我哦"]))
    out = lint_service.scan_text("有事私我哦")
    assert any(h["category"] == "traffic" and h["text"] == "私我哦" for h in out["hits"])
```

- [ ] **Step 2: 跑测试确认失败** — Expected: FAIL（`ModuleNotFoundError: lint_service`）

- [ ] **Step 3: 实现** `sidecar/csm_sidecar/services/lint_service.py`

```python
"""禁区 lint 服务：读 config 覆盖 → 引擎 scan/autofix → dict。纯计算、不写盘。"""
from __future__ import annotations
from typing import Any

from csm_core.lint import build_report, build_rules

from . import config_service


def scan_text(text: str) -> dict[str, Any]:
    cfg = config_service.load()
    lint_cfg = cfg.lint
    if not lint_cfg.enabled:
        return {"hits": [], "fixed_text": text or ""}
    rules = build_rules(lint_cfg)
    return build_report(text or "", rules).model_dump()
```

- [ ] **Step 4: 跑测试确认通过** — Expected: 3 passed

- [ ] **Step 5: commit**

```bash
git add sidecar/csm_sidecar/services/lint_service.py sidecar/tests/test_lint_service.py
git commit -m "feat(lint): lint_service.scan_text（读 config + 引擎）"
```

---

## Task B2: routes/lint.py + main.py 注册

**Files:**
- Create: `sidecar/csm_sidecar/routes/lint.py`
- Modify: `sidecar/csm_sidecar/main.py`
- Create: `sidecar/tests/test_lint_routes.py`

> 参考既有 `routes/vault_atomize.py` 的 `RequireToken` import 路径与 router 装配；`main.py` 注册照抄 `vault_atomize` 那两行。

- [ ] **Step 1: 失败测试** `sidecar/tests/test_lint_routes.py`

```python
import pytest
from fastapi.testclient import TestClient
from csm_core.config import AppConfig, LintConfig
from csm_sidecar.main import app
from csm_sidecar.services import lint_service

# token 鉴权：复用既有 test fixture 模式（参考 test_vault_atomize_routes.py
# 如何拿 client + 注入 token header）。此处示意用同样的 conftest client。


@pytest.fixture(autouse=True)
def _cfg(monkeypatch):
    monkeypatch.setattr(lint_service.config_service, "load", lambda: AppConfig(lint=LintConfig()))


def test_lint_ok(client):                      # client fixture 来自 conftest（带 token）
    r = client.post("/api/lint", json={"text": "业内最佳😀"})
    assert r.status_code == 200
    body = r.json()
    assert "hits" in body and "fixed_text" in body
    assert any(h["category"] == "absolute" for h in body["hits"])


def test_lint_missing_text_422(client):
    assert client.post("/api/lint", json={}).status_code == 422


def test_lint_empty_text_empty_report(client):
    r = client.post("/api/lint", json={"text": ""})
    assert r.status_code == 200
    assert r.json() == {"hits": [], "fixed_text": ""}
```

> 若 conftest 没有现成 `client` fixture，照 `sidecar/tests/test_vault_atomize_routes.py` 的写法建（同款 token 注入）。

- [ ] **Step 2: 跑测试确认失败** — Expected: FAIL（404，路由未注册）

- [ ] **Step 3: 实现** `sidecar/csm_sidecar/routes/lint.py`

```python
"""POST /api/lint —— 无状态禁区扫描。text→{hits, fixed_text}。"""
from __future__ import annotations
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from ..deps import RequireToken          # 与 vault_atomize.py 同源（按实际 import 路径）
from ..services import lint_service

router = APIRouter(tags=["lint"], dependencies=[RequireToken])


class LintBody(BaseModel):
    text: str


@router.post("/api/lint")
def lint(body: LintBody) -> dict[str, Any]:
    return lint_service.scan_text(body.text)
```

`main.py`：加 `from .routes import lint as lint_routes` + `app.include_router(lint_routes.router)`（紧跟 `vault_atomize_routes` 那行）。

- [ ] **Step 4: 跑测试确认通过** — Expected: 3 passed

- [ ] **Step 5: commit**

```bash
git add sidecar/csm_sidecar/routes/lint.py sidecar/csm_sidecar/main.py sidecar/tests/test_lint_routes.py
git commit -m "feat(lint): POST /api/lint 路由 + 注册"
```

---

# Unit C — 前端 store + LintPanel + ArticleView 接线

## Task C1: article.ts store（lint 状态 + 动作 + 自动扫）

**Files:**
- Modify: `frontend/src/stores/article.ts`
- Create: `frontend/src/stores/__tests__/article.lint.spec.ts`

- [ ] **Step 1: 失败测试** `frontend/src/stores/__tests__/article.lint.spec.ts`

```ts
import { setActivePinia, createPinia } from "pinia";
import { describe, it, expect, vi, beforeEach } from "vitest";

// mock sidecar client（参考 article.finalize.spec.ts 的 mock 写法）
const post = vi.fn();
vi.mock("@/stores/sidecar", () => ({
  useSidecar: () => ({ client: { post } }),
}));

import { useArticle, type LintHit } from "@/stores/article";

const HIT: LintHit = {
  category: "absolute", text: "最佳", start: 0, end: 2,
  sentence: "最佳之选", fixable: false, suggestion: "改写",
};
const EMOJI: LintHit = {
  category: "emoji", text: "😀", start: 2, end: 3,
  sentence: "最佳😀", fixable: true, suggestion: "删",
};

describe("article lint", () => {
  beforeEach(() => { setActivePinia(createPinia()); post.mockReset(); });

  it("runLint 存结果并清放行", async () => {
    post.mockResolvedValue({ data: { hits: [HIT], fixed_text: "最佳" } });
    const a = useArticle();
    a.lintReleased = ["x"];
    await a.runLint("最佳😀");
    expect(a.lint?.hits).toHaveLength(1);
    expect(a.lintReleased).toEqual([]);
    expect(a.lintBlocking).toBe(true);
  });

  it("autofixLint 置 finalText=fixed_text 并重扫", async () => {
    const a = useArticle();
    a.lint = { hits: [HIT, EMOJI], fixed_text: "最佳" };
    post.mockResolvedValue({ data: { hits: [HIT], fixed_text: "最佳" } });
    await a.autofixLint();
    expect(a.finalText).toBe("最佳");
    expect(a.lint?.hits.every((h) => !h.fixable)).toBe(true);
  });

  it("放行后 lintBlocking 转 false", async () => {
    const a = useArticle();
    a.lint = { hits: [HIT], fixed_text: "最佳" };
    expect(a.lintBlocking).toBe(true);
    a.toggleLintRelease(HIT);
    expect(a.lintBlocking).toBe(false);
    expect(a.lintUnresolved).toBe(0);
  });

  it("runLint 失败 fail-open（lint=null，不拦）", async () => {
    post.mockRejectedValue(new Error("net"));
    const a = useArticle();
    await a.runLint("x");
    expect(a.lint).toBeNull();
    expect(a.lintBlocking).toBe(false);
  });
});
```

- [ ] **Step 2: 跑测试确认失败** — Expected: FAIL（`lint`/`runLint` 不存在）

- [ ] **Step 3: 实现** —— 改 `frontend/src/stores/article.ts`：

(a) 接口（放在 `FactcheckViolation` 旁）：
```ts
export type LintCategory = "meta_speak" | "absolute" | "traffic" | "emoji" | "dash" | "quote";
export interface LintHit {
  category: LintCategory;
  text: string; start: number; end: number;
  sentence: string; fixable: boolean; suggestion: string;
}
const lintKey = (h: LintHit) => `${h.category}:${h.start}:${h.text}`;
```

(b) state（`ArticleState` 接口 + `state()` 初值）：
```ts
// state 接口加：
lint: { hits: LintHit[]; fixed_text: string } | null;
lintReleased: string[];
// state() 初值加：
lint: null,
lintReleased: [],
```

(c) getters：
```ts
lintBlocking: (s) =>
  !!s.lint && s.lint.hits.some((h) => !s.lintReleased.includes(lintKey(h))),
lintUnresolved: (s) =>
  s.lint ? s.lint.hits.filter((h) => !s.lintReleased.includes(lintKey(h))).length : 0,
```

(d) actions：
```ts
async runLint(text: string): Promise<void> {
  if (!text.trim()) { this.lint = null; this.lintReleased = []; return; }
  try {
    const r = await useSidecar().client.post("/api/lint", { text });
    this.lint = r.data;          // {hits, fixed_text}，snake_case 零映射
    this.lintReleased = [];
  } catch {
    this.lint = null;            // fail-open：lint 基建故障不拦导出
  }
},
autofixLint(): Promise<void> {
  if (!this.lint) return Promise.resolve();
  this.finalText = this.lint.fixed_text;
  return this.runLint(this.finalText);
},
toggleLintRelease(h: LintHit): void {
  const k = lintKey(h);
  const i = this.lintReleased.indexOf(k);
  if (i >= 0) this.lintReleased.splice(i, 1);
  else this.lintReleased.push(k);
},
```

(e) 自动扫：在 `_subscribe` 的 `done` handler 末尾（`this._teardown()` 之前）加——成稿出炉自动扫：
```ts
// 整篇润色成稿出炉 → 自动跑禁区 lint（draft_only 起飞 final_text 空，不触发）。
if (this.finalText.trim()) void this.runLint(this.finalText);
```
在 `rerunPass` 的 `done` handler 里、设 `final_text` 之后也加同一句（重跑改了成稿要重扫）。

(f) reset：`submit` 与 `finalize` 的 reset 块里加 `this.lint = null; this.lintReleased = [];`（起新生成/新链清掉上轮 lint）。

(g) 导出 return：在 store `return {...}`（若是 setup store）或无需改（option store 自动暴露）。本 store 是 **options store**（`defineStore("article", { state, getters, actions })`），新增字段/getter/action 自动暴露，无需改 return。

- [ ] **Step 4: 跑测试确认通过** — Expected: 4 passed

- [ ] **Step 5: commit**

```bash
git add frontend/src/stores/article.ts frontend/src/stores/__tests__/article.lint.spec.ts
git commit -m "feat(lint): article store lint 状态+动作+自动扫"
```

---

## Task C2: LintPanel.vue

**Files:**
- Create: `frontend/src/components/article/LintPanel.vue`
- Create: `frontend/src/components/article/__tests__/LintPanel.spec.ts`

> 镜像 `FactCheckPanel.vue`（Dialog + Btn + Pill + useToast）。`<Dialog>`/`<Pill>` 含 Teleport，测试 mount 加 `global:{stubs:{teleport:true}}`（[[project_csm_creation_studio_upgrade]] 前端测试坑）。

- [ ] **Step 1: 失败测试** `frontend/src/components/article/__tests__/LintPanel.spec.ts`

```ts
import { mount } from "@vue/test-utils";
import { setActivePinia, createPinia } from "pinia";
import { describe, it, expect, vi, beforeEach } from "vitest";
import LintPanel from "@/components/article/LintPanel.vue";
import { useArticle, type LintHit } from "@/stores/article";

vi.mock("@/stores/sidecar", () => ({ useSidecar: () => ({ client: { post: vi.fn() } }) }));

const MECH: LintHit = { category: "emoji", text: "😀", start: 0, end: 1, sentence: "😀", fixable: true, suggestion: "删" };
const JUDGE: LintHit = { category: "absolute", text: "最佳", start: 1, end: 3, sentence: "x最佳", fixable: false, suggestion: "改写" };

function mountPanel() {
  return mount(LintPanel, { props: { open: true }, global: { stubs: { teleport: true } } });
}

describe("LintPanel", () => {
  beforeEach(() => setActivePinia(createPinia()));

  it("渲染命中项", () => {
    const a = useArticle();
    a.lint = { hits: [MECH, JUDGE], fixed_text: "最佳" };
    const w = mountPanel();
    expect(w.findAll("[data-lint-hit]")).toHaveLength(2);
  });

  it("一键清调 autofixLint", async () => {
    const a = useArticle();
    a.lint = { hits: [MECH], fixed_text: "" };
    const spy = vi.spyOn(a, "autofixLint").mockResolvedValue();
    const w = mountPanel();
    await w.find("[data-lint-autofix]").trigger("click");
    expect(spy).toHaveBeenCalled();
  });

  it("确认并导出仅在不拦时可点、emit proceed", async () => {
    const a = useArticle();
    a.lint = { hits: [JUDGE], fixed_text: "x最佳" };
    const w = mountPanel();
    expect(w.find("[data-lint-proceed]").attributes("disabled")).toBeDefined();
    a.toggleLintRelease(JUDGE);                 // 放行后可点
    await w.vm.$nextTick();
    expect(w.find("[data-lint-proceed]").attributes("disabled")).toBeUndefined();
    await w.find("[data-lint-proceed]").trigger("click");
    expect(w.emitted("proceed")).toBeTruthy();
  });
});
```

- [ ] **Step 2: 跑测试确认失败** — Expected: FAIL（组件不存在）

- [ ] **Step 3: 实现** `frontend/src/components/article/LintPanel.vue`

```vue
<script setup lang="ts">
/**
 * 禁区 lint 审查面板 —— 成稿被禁区 lint 命中时弹（ArticleView 监听
 * article.lintBlocking 自动弹）。机械类（emoji/破折号/双引号）「一键清」
 * 批量修；判断类（元话术/绝对化/引流）逐条「本次放行」或回成稿手改。
 * 全部清/放行后「确认并导出」emit proceed（ArticleView 开导出 modal）。
 * 镜像 FactCheckPanel 的 Dialog chrome。
 */
import { computed } from "vue";

import Btn from "@/components/ui/Btn.vue";
import Dialog from "@/components/ui/Dialog.vue";
import Pill from "@/components/ui/Pill.vue";
import { useArticle, type LintHit } from "@/stores/article";

const open = defineModel<boolean>("open", { default: false });
const emit = defineEmits<{ proceed: [] }>();
const article = useArticle();

const CAT_LABEL: Record<string, string> = {
  meta_speak: "元话术", absolute: "绝对化", traffic: "引流",
  emoji: "emoji", dash: "破折号", quote: "双引号",
};
const lintKey = (h: LintHit) => `${h.category}:${h.start}:${h.text}`;
const hits = computed<LintHit[]>(() => article.lint?.hits ?? []);
const hasMechanical = computed(() => hits.value.some((h) => h.fixable));
function isReleased(h: LintHit) { return article.lintReleased.includes(lintKey(h)); }

async function autofix() { await article.autofixLint(); }
async function recheck() { if (article.finalText.trim()) await article.runLint(article.finalText); }
function proceed() { emit("proceed"); open.value = false; }
</script>

<template>
  <Dialog v-model:open="open" title="禁区检查 — 发现违规措辞/标点" size="lg">
    <div class="flex flex-col gap-3">
      <p class="text-ink-3 text-sm">
        机械类（emoji/破折号/双引号）可「一键清」批量修；判断类（元话术/绝对化/引流）请在「成稿」改写，或勾「本次放行」（确认是合理表述）。全部处理后才可导出。
      </p>
      <ul class="flex flex-col gap-2">
        <li v-for="(h, i) in hits" :key="i" data-lint-hit class="border-ink/10 rounded-lg border p-3">
          <div class="flex items-center justify-between gap-2">
            <div class="flex items-center gap-2 text-sm">
              <Pill>{{ CAT_LABEL[h.category] }}</Pill>
              <span class="font-medium">{{ h.text }}</span>
            </div>
            <label v-if="!h.fixable" class="text-ink-3 flex items-center gap-1 text-xs">
              <input type="checkbox" :checked="isReleased(h)" @change="article.toggleLintRelease(h)" />
              本次放行
            </label>
            <span v-else class="text-ink-4 text-[11px]">可一键清</span>
          </div>
          <div class="text-ink-3 mt-1 text-xs">{{ h.sentence }}</div>
          <div class="text-ink-4 mt-1 text-[11px]">建议：{{ h.suggestion }}</div>
        </li>
      </ul>
    </div>
    <template #footer>
      <Btn v-if="hasMechanical" variant="ghost" small data-lint-autofix @click="autofix">一键清机械类</Btn>
      <Btn variant="ghost" small data-lint-recheck @click="recheck">重新检查</Btn>
      <Btn variant="solid" small data-lint-proceed :disabled="article.lintBlocking" @click="proceed">
        确认并导出
      </Btn>
    </template>
  </Dialog>
</template>
```

- [ ] **Step 4: 跑测试确认通过** — Expected: 3 passed

- [ ] **Step 5: commit**

```bash
git add frontend/src/components/article/LintPanel.vue frontend/src/components/article/__tests__/LintPanel.spec.ts
git commit -m "feat(lint): LintPanel 审查面板（一键清/放行/确认导出）"
```

---

## Task C3: ArticleView 接线 + FactCheckPanel lint 守卫 + vue-tsc

**Files:**
- Modify: `frontend/src/views/ArticleView.vue`
- Modify: `frontend/src/components/article/FactCheckPanel.vue`
- Create: `frontend/src/views/__tests__/ArticleView.lint.spec.ts`

- [ ] **Step 1: 失败测试** `frontend/src/views/__tests__/ArticleView.lint.spec.ts`

> 参考 `ArticleView.finalize.spec.ts` 的 mount + mock（sidecar/router/teleport stub）。本测专注 `onExportClick` 守卫顺序——若直接测 view 太重，可抽 `onExportClick` 的纯逻辑或用 store 驱动断言。最小可行：断言守卫顺序逻辑。

```ts
import { setActivePinia, createPinia } from "pinia";
import { describe, it, expect, beforeEach, vi } from "vitest";
import { useArticle, type LintHit } from "@/stores/article";

vi.mock("@/stores/sidecar", () => ({ useSidecar: () => ({ client: { post: vi.fn() } }) }));

// 守卫顺序的可测纯函数（与 ArticleView.onExportClick 同逻辑）：
// 返回 "factcheck" | "lint" | "export"
function exportGate(a: ReturnType<typeof useArticle>): "factcheck" | "lint" | "export" {
  if (a.factcheck?.blocked) return "factcheck";
  if (a.lintBlocking) return "lint";
  return "export";
}
const JUDGE: LintHit = { category: "absolute", text: "最佳", start: 0, end: 2, sentence: "最佳", fixable: false, suggestion: "x" };

describe("export gate order", () => {
  beforeEach(() => setActivePinia(createPinia()));
  it("factcheck 优先", () => {
    const a = useArticle();
    a.factcheck = { blocked: true, violations: [] };
    a.lint = { hits: [JUDGE], fixed_text: "" };
    expect(exportGate(a)).toBe("factcheck");
  });
  it("无 factcheck 时 lint 拦", () => {
    const a = useArticle();
    a.lint = { hits: [JUDGE], fixed_text: "" };
    expect(exportGate(a)).toBe("lint");
  });
  it("都过 → 导出", () => {
    const a = useArticle();
    expect(exportGate(a)).toBe("export");
  });
});
```

- [ ] **Step 2: 跑测试确认失败** — Expected: 初次 FAIL 或 PASS（纯函数）；关键是把 `ArticleView`/`FactCheckPanel` 的真实接线改到位让 vue-tsc 过。先让测试存在并跑。

- [ ] **Step 3: 实现** —— 改 `ArticleView.vue`：

(a) import：`import LintPanel from "@/components/article/LintPanel.vue";`

(b) 在 `const showFactcheck = ref(false);` 旁加：
```ts
const showLint = ref(false);
// 成稿被禁区 lint 命中（lintBlocking false→true）自动弹面板。
watch(() => article.lintBlocking, (b, prev) => { if (b && !prev) showLint.value = true; });
```

(c) `onExportClick` 加 lint 守卫（factcheck 之后、开 modal 之前）：
```ts
function onExportClick() {
  if (article.factcheck?.blocked) { showFactcheck.value = true; return; }
  if (article.lintBlocking) { showLint.value = true; return; }
  showExportModal.value = true;
}
```

(d) `checkItems` 末尾追加第 7 项「禁区」：
```ts
items.push({
  label: "禁区",
  value: article.lint ? (article.lintBlocking ? `${article.lintUnresolved} 处` : "无") : "—",
  desc: article.lintBlocking ? "有未处理违规，点导出查看" : (article.lint ? "已清/已放行" : "成稿后自动检查"),
  pass: !article.lintBlocking,
  tone: article.lintBlocking ? "warn" : "ok",
});
```

(e) 模板里 `<FactCheckPanel>` 标签加 `@lint="showLint = true"`，并在其后加 `<LintPanel>`：
```html
<FactCheckPanel v-model:open="showFactcheck" @lint="showLint = true" />
<LintPanel v-model:open="showLint" @proceed="showExportModal = true" />
```

改 `FactCheckPanel.vue`：`recheckExport` 在调 `article.resolveFactcheck` **之前**加 lint 守卫，堵双失败漏洞：
```ts
const emit = defineEmits<{ lint: [] }>();   // 顶部加
// recheckExport 开头加：
if (article.lintBlocking) { emit("lint"); open.value = false; return; }
```

- [ ] **Step 4: 跑测试 + vue-tsc**

```powershell
cd frontend; npx vitest run src/views/__tests__/ArticleView.lint.spec.ts src/stores/__tests__/article.lint.spec.ts src/components/article/__tests__/LintPanel.spec.ts
cd frontend; npx vue-tsc -b
```
Expected: 全 passed；**vue-tsc 0 错**（LintHit fixture 的 `category` 字面量已满足 union；如新建数组报错，显式标 `const X: LintHit = {...}` 或 `LintHit[]`——CSM#144 教训）。
> `vue-tsc -b` 可能 emit `vite.config.js`/`.d.ts` → 跑完 `git checkout -- frontend/vite.config.js` 还原（[[reference_csm_dev_worktree_setup]]）。

- [ ] **Step 5: commit**

```bash
git add frontend/src/views/ArticleView.vue frontend/src/components/article/FactCheckPanel.vue frontend/src/views/__tests__/ArticleView.lint.spec.ts
git commit -m "feat(lint): ArticleView 软拦接线 + 质检卡第7项 + factcheck 面板 lint 守卫"
```

---

# 收尾

- [ ] **全量回归**：csm_core 全测 + sidecar 全测 + 前端全测 + `vue-tsc -b`，确认零回归（注意 [[project_csm_creation_studio_upgrade]] 记的 5 个预存失败与本工作无关，别排查）。
- [ ] **最终综合审查**（opus）：端到端契约一致（LintHit 八字段 Python↔TS 同形）、守卫顺序（factcheck>lint>export）两口都守、fail-open、autofix 幂等、零回归（lint enabled=false 退回今天）。
- [ ] **收尾 PR**：push `claude/forbidden-zone-lint` + `gh pr create`（中文 body + 🤖 trailer），停在 pending 等网页 merge（[[feedback_merge_flow_pr]]）。

---

## 备注（实现者注意）

1. **config 隔离铁律**：所有读 config 的 sidecar 测试 monkeypatch `config_service.load`，绝不读真实 settings.json（[[feedback_csm_baidu_fetch_test_config_isolation]]）。
2. **共享盘红线**：本特性不碰 vault、不写盘，无共享盘风险；但仍禁止任何测试写 `D:\家电组共享\DATA`。
3. **vue-tsc 必跑**：推前 `npx vue-tsc -b` 必过（fixture union 字面量陷阱，CSM#144 同类）。
4. **RequireToken / client fixture / Dialog teleport stub**：照既有 `vault_atomize` 路由测试、`FactCheckPanel` 组件测试的现成写法，别另起炉灶。
5. **options store**：`article` 是 options store，新增字段/getter/action 自动暴露，无需改 return。
