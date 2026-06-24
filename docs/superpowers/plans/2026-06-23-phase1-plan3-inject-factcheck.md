# Phase 1 · Plan 3 — 注入 + 事实核对硬门禁 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 生成锁定型号时把该型号的结构化记忆（参数/认证/话术/背书/竞品介绍）注入 LLM prompt 并硬约束「不得新增/改动数字与认证」，导出前用「注入源并集白名单」核对成稿、拦截编造、给放行口；全部能力 feature flag 默认关、零回归。

**Architecture:** 三层。① 纯函数核对引擎 `csm_core/factcheck/`（只抽**带参数单位**的数字 + 认证名，按集合判越界）。② 注入装配 `csm_core/brand_memory/inject.py`（从 `AssemblyPlan` 提取涉及型号 → resolve 记忆 → 渲染 brand_facts 文本 + 构建白名单）。③ sidecar 接线：`generate_service` 注入步 + 导出前门禁（命中越界则缓存待导出 + 以 `done(factcheck.blocked)` 收尾、不导出），`factcheck_service` 缓存 + `POST /api/generate/{job_id}/export` resume 端点（带用户放行项重核 → 干净则导出）。所有 Vue UI（审查面板 + 素材库 tab）留 **Plan 5**。

**Tech Stack:** Python 3.11+ / pydantic v2 / FastAPI + sse-starlette / pytest（`D:/CSM/.venv/Scripts/python.exe -m pytest`，**从 worktree 根目录跑**）。

参考 spec：[Phase 1 设计稿](../specs/2026-06-23-phase1-brand-model-memory-design.md) §4（注入+门禁）、§2.3（动态白名单）、§7（opt-in）。依赖 Plan 1（`csm_core/brand_memory/` resolver/whitelist/identity/model）+ Plan 2（`build_brand_registry` 非空 33 型号）。

---

## 关键设计决定（执行前请确认 — 已与用户敲定）

1. **白名单 = 全文级·注入源并集**（用户选定）。`白名单.numbers = ⋃ 涉及型号 specs 数值 ∪ normalize_numbers(draft ∪ 已注入 brand_facts)`；`白名单.certs = ⋃ specs 认证 ∪ 源文本里出现的已知认证名`。贴 spec §2.3「所有源材料」，满足验收 #3/#4/#5。**不做**按槽位「数字张冠李戴」归属（与 §4.2 非数字类已知局限同批留后）。
2. **核对只抽「带参数单位」的数字**（防误拦的核心）：`250AW / 35kPa / 12万转 / 60% / 1700L/min` 才核；`3款 / 第1名 / 2024年` 这类**裸数字/计数词不核**（不是参数）。单位词表只含计量单位（AW/Pa/min/转/%/...），不含 款/项/档 等计数词。
3. **`万` 两侧对称展开**：注入渲染 specs 用**原始单元格文本**（`12万转` 原样），白名单用 `brand_memory.whitelist.normalize_numbers`（`12万转→120000`），核对引擎用同样的 `万→×10000`。三处一致，`12万转` 不会误判。
4. **`型号` 沿用「全名」约定**（`CEWEYDS18`，Plan 2 已定）。作用域提取**以 registry 为锚**：sampler 吐出的型号串（picks 的 `meta.title/型号`、hero `title`）只有 `registry.brand_of(它)` 非空才采纳 → 垃圾标题丢弃、品牌由 registry 统一解析。registry 不认识的型号（如只有 intro 没有产品参数的竞品）这步不贡献记忆，但其数字仍随 draft 进白名单，**不会误拦**。
5. **纯后端，UI 留 Plan 5**（用户选定）。Plan 3 交付引擎 + 注入 + 门禁 + resume API + feature flags（默认关）；审查面板（越界列表→逐条改文案/标通用/放行）和素材库 tab 都在 Plan 5。
6. **门禁绕过 EventBus「无暂停态」限制**：EventBus 只有 `done`/`error` 终态、worker 是线程池不能挂起等用户。所以命中越界时 worker **正常跑完核对 → 缓存待导出 → `bus.finish(done, factcheck={blocked,violations}, document=None)` → return（不导出）**；前端（Plan 5）据此弹审查面板；用户处理完另起 `POST /api/generate/{id}/export` 同步重核 + 导出。
7. **全部 opt-in、默认关**：`brand_memory.inject=False`、`brand_memory.factcheck=False`。两个都关 = 今天行为，happy-path `finish` 载荷一字不改。

---

## File Structure

**新增**
- `csm_core/factcheck/__init__.py` — 导出 `check_facts / Violation / FactCheckReport / extract_number_mentions / extract_certs`。
- `csm_core/factcheck/model.py` — `Violation`、`FactCheckReport`（pydantic）。
- `csm_core/factcheck/extract.py` — 带单位数字抽取 + 认证名抽取 + 分句（纯函数，**不依赖 brand_memory**）。
- `csm_core/factcheck/checker.py` — `check_facts(text, *, allowed_numbers, allowed_certs)`。
- `csm_core/brand_memory/inject.py` — `resolve_scopes / render_brand_facts / build_whitelist / ModelScope`。
- `sidecar/csm_sidecar/services/factcheck_service.py` — 待导出缓存 + `resolve_and_export`（resume）。
- `tests/core/factcheck/{__init__.py,test_extract.py,test_checker.py}`。
- `tests/core/brand_memory/test_inject.py`、`tests/core/test_config_brand_memory.py`。
- `sidecar/tests/test_factcheck_service.py`、`sidecar/tests/test_generate_factcheck_route.py`、`tests/core/brand_memory/test_inject_real_vault.py`（integration）。

**修改**
- `csm_core/llm/prompts.py` — `PromptInputs` 加可选 `brand_facts`，`build_prompt` 注入事实段 + 硬约束（向后兼容）。
- `csm_core/config.py` — 加 `BrandMemoryConfig`，挂到 `AppConfig.brand_memory`。
- `sidecar/csm_sidecar/services/generate_service.py` — 注入步 + `_maybe_block_for_factcheck` 门禁种子。
- `sidecar/csm_sidecar/routes/generate.py` — `POST /api/generate/{job_id}/export`。
- `sidecar/tests/conftest.py` — `factcheck_service` 缓存按测试重置（见 Task C3）。
- `tests/core/llm/test_prompts.py` — brand_facts 用例（追加）。
- `docs/superpowers/plans/2026-06-23-phase1-brand-memory.md` — Plan 3 行 待细化→✅ 链接（收尾）。

---

# Part A — 事实核对引擎 `csm_core/factcheck/`（纯函数）

### Task A1: 包骨架 + 数据模型 + 抽取

**Files:**
- Create: `csm_core/factcheck/__init__.py`、`csm_core/factcheck/model.py`、`csm_core/factcheck/extract.py`
- Create: `tests/core/factcheck/__init__.py`（空）
- Test: `tests/core/factcheck/test_extract.py`

- [ ] **Step 1: 写失败测试**

`tests/core/factcheck/test_extract.py`:
```python
from csm_core.factcheck.extract import (
    extract_number_mentions, extract_certs, split_sentences,
)


def test_only_unit_bearing_numbers_extracted():
    vals = [v for v, _ in extract_number_mentions("推荐3款，吸力250AW，第1名，2024年")]
    assert 250.0 in vals
    assert 3.0 not in vals      # 「3款」是计数词，不抽
    assert 1.0 not in vals      # 「第1名」不抽
    assert 2024.0 not in vals   # 「2024年」不抽


def test_wan_expanded_and_percent_and_compound_unit():
    vals = {v for v, _ in extract_number_mentions("12万转电机，效率约60%，气流1700L/min")}
    assert vals == {120000.0, 60.0, 1700.0}


def test_unit_longest_match_AW_not_W():
    mentions = extract_number_mentions("250AW")
    assert mentions == [(250.0, "250AW")]


def test_raw_token_preserved_for_review():
    mentions = extract_number_mentions("噪音70dB")
    assert mentions[0][1] == "70dB"


def test_extract_certs_word_boundaried_and_deduped():
    certs = extract_certs("通过 CE、FCC 认证，国家3C认证，再拿 CE")
    assert certs == ["CE", "FCC", "3C"]      # 去重 + 保序
    assert extract_certs("CELLULAR 的 CELL") == []   # 不在词内误命中 CE


def test_split_sentences():
    assert split_sentences("一句。两句！三句\n四句") == ["一句", "两句", "三句", "四句"]
```

- [ ] **Step 2: 跑测试确认失败** — `pytest tests/core/factcheck/test_extract.py -v` → `ModuleNotFoundError`。

- [ ] **Step 3: 写实现**

`csm_core/factcheck/model.py`:
```python
"""Fact-check result models."""
from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, Field


class Violation(BaseModel):
    kind: Literal["number", "cert"]
    value: str            # 成稿里的原文 token，如 "250AW" / "CCC"
    sentence: str         # 所在句子（审查面板定位用）
    suggestion: str       # 放行建议提示


class FactCheckReport(BaseModel):
    ok: bool
    violations: list[Violation] = Field(default_factory=list)
```

`csm_core/factcheck/extract.py`:
```python
"""Extract checkable facts (parameter numbers + cert names) from text.

只抽带**参数单位**的数字（250AW / 35kPa / 12万转 / 60%）；裸数字与计数词
（3款 / 第1名 / 2024年）不是参数，跳过 —— 这是防误拦（验收 #4）的核心。
``万`` 展开为 ×10000，与 brand_memory.whitelist.normalize_numbers 对称，
保证白名单（用同一份源文本构建）与核对口径一致。本模块**不依赖
brand_memory**（避免循环导入）。
"""
from __future__ import annotations
import re

# 计量单位词表（measurement units only —— 不含 款/项/档 等计数词）。
# 长单位在前：让 "AW" 先于 "W"、"kPa" 先于 "Pa"、"L/min" 先于 "L" 命中。
UNITS: tuple[str, ...] = (
    "L/min", "mmH2O", "mAh", "kWh", "kPa", "KPa", "rpm",
    "Wh", "kW", "AW", "Pa", "dB", "mL", "ml", "μm", "um",
    "nm", "mm", "cm", "kg", "min", "转", "倍", "元",
    "W", "L", "g", "h", "%",
)
_UNIT_ALT = "|".join(re.escape(u) for u in sorted(UNITS, key=len, reverse=True))
_NUM_UNIT_RE = re.compile(rf"(\d+(?:\.\d+)?)\s*(万)?\s*({_UNIT_ALT})")

# 认证名词表（大写、词界匹配）。常见家电认证。
CERT_VOCAB: tuple[str, ...] = (
    "RoHS", "CCC", "FCC", "CQC", "PSE", "ETL", "SGS",
    "CE", "CB", "UL", "GS", "3C",
)
_CERT_ALT = "|".join(re.escape(c) for c in sorted(CERT_VOCAB, key=len, reverse=True))
_CERT_RE = re.compile(rf"(?<![A-Za-z0-9])({_CERT_ALT})(?![A-Za-z0-9])")

_SENT_SPLIT_RE = re.compile(r"[。！？!?\n；;]+")


def _value(num: str, wan: str | None) -> float:
    return float(num) * (10000.0 if wan else 1.0)


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENT_SPLIT_RE.split(text or "") if s.strip()]


def extract_number_mentions(text: str) -> list[tuple[float, str]]:
    """[(归一值, 原文 token)]，仅限带参数单位的数字。"""
    return [
        (_value(m.group(1), m.group(2)), m.group(0).strip())
        for m in _NUM_UNIT_RE.finditer(text or "")
    ]


def extract_certs(text: str) -> list[str]:
    """文本里出现的认证名（去重、保序）。"""
    seen: set[str] = set()
    out: list[str] = []
    for m in _CERT_RE.finditer(text or ""):
        c = m.group(1)
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out
```

`csm_core/factcheck/__init__.py`:
```python
"""Export-time fact check — flag numbers/certs in a finished article that
aren't in the per-generation whitelist (= the LLM invented them)."""
from .model import FactCheckReport, Violation
from .extract import (
    CERT_VOCAB, UNITS, extract_certs, extract_number_mentions, split_sentences,
)
from .checker import check_facts

__all__ = [
    "FactCheckReport", "Violation", "check_facts",
    "extract_number_mentions", "extract_certs", "split_sentences",
    "UNITS", "CERT_VOCAB",
]
```
> ⚠ `__init__` 这一步会 import `checker`（Task A2 才建）。本 Task 先把 `__init__` 里 `from .checker import check_facts` 与 `"check_facts"` 那两行**注释掉**，A2 完成后再放开（Step 3 of A2）。或先建一个空 `checker.py` 占位。

- [ ] **Step 4: 跑测试确认通过** — `pytest tests/core/factcheck/test_extract.py -v` → PASS（6 passed）。

- [ ] **Step 5: 提交**
```bash
git add csm_core/factcheck/__init__.py csm_core/factcheck/model.py csm_core/factcheck/extract.py tests/core/factcheck/__init__.py tests/core/factcheck/test_extract.py
git commit -m "feat(factcheck): 带单位数字/认证抽取 + 数据模型（不依赖 brand_memory）"
```

---

### Task A2: 核对器 `check_facts`

**Files:**
- Create: `csm_core/factcheck/checker.py`；放开 `__init__.py` 的 checker 导出
- Test: `tests/core/factcheck/test_checker.py`

- [ ] **Step 1: 写失败测试**

`tests/core/factcheck/test_checker.py`:
```python
from csm_core.factcheck import check_facts


def test_out_of_whitelist_number_flagged():
    r = check_facts("吸力高达250AW。", allowed_numbers={220.0}, allowed_certs=set())
    assert r.ok is False
    assert len(r.violations) == 1
    v = r.violations[0]
    assert v.kind == "number" and v.value == "250AW"
    assert v.sentence == "吸力高达250AW"


def test_faithful_numbers_not_flagged():
    # 验收 #4：忠实使用注入数字 → 不拦
    text = "吸力220AW，约60%除螨率，12万转电机，1700L/min。"
    r = check_facts(
        text, allowed_numbers={220.0, 60.0, 120000.0, 1700.0}, allowed_certs=set(),
    )
    assert r.ok is True and r.violations == []


def test_bare_counts_never_flagged_even_if_absent():
    # 「3款」「第1名」不带单位 → 根本不进核对 → 即使不在白名单也不拦
    r = check_facts("推荐3款，综合第1名。", allowed_numbers=set(), allowed_certs=set())
    assert r.ok is True


def test_fabricated_cert_flagged_known_cert_passes():
    r = check_facts(
        "通过 CE 与 CCC 认证。", allowed_numbers=set(), allowed_certs={"CE"},
    )
    assert r.ok is False
    assert [v.value for v in r.violations] == ["CCC"]


def test_multiple_violations_across_sentences():
    r = check_facts(
        "吸力300AW。噪音55dB。", allowed_numbers={220.0}, allowed_certs=set(),
    )
    assert {v.value for v in r.violations} == {"300AW", "55dB"}
```

- [ ] **Step 2: 跑测试确认失败** — `ImportError`（`check_facts` 未定义）。

- [ ] **Step 3: 写实现**

`csm_core/factcheck/checker.py`:
```python
"""Compare a finished article against a fact whitelist (number/cert sets).

只看**带单位**的数字和**已知**认证名（见 extract）。membership 用精确集合
查找 —— 白名单已把区间/万展开为独立 float（见 brand_memory.whitelist），
本域数值都是良态 float，无需 math.isclose。句子上下文随违规一起返回，供
Plan 5 审查面板定位。
"""
from __future__ import annotations
from .extract import extract_certs, extract_number_mentions, split_sentences
from .model import FactCheckReport, Violation


def check_facts(
    text: str, *, allowed_numbers: set[float], allowed_certs: set[str],
) -> FactCheckReport:
    violations: list[Violation] = []
    for sentence in split_sentences(text):
        for value, raw in extract_number_mentions(sentence):
            if value not in allowed_numbers:
                violations.append(Violation(
                    kind="number", value=raw, sentence=sentence,
                    suggestion="改用注入参数表里的数值，或标为通用表述/本次放行",
                ))
        for cert in extract_certs(sentence):
            if cert not in allowed_certs:
                violations.append(Violation(
                    kind="cert", value=cert, sentence=sentence,
                    suggestion="删除或替换为该型号实际通过的认证，或本次放行",
                ))
    return FactCheckReport(ok=not violations, violations=violations)
```
放开 `csm_core/factcheck/__init__.py` 里 `from .checker import check_facts` 与 `"check_facts"`（若 A1 注释了）。

- [ ] **Step 4: 跑测试确认通过** — `pytest tests/core/factcheck/ -v` → PASS（全部）。

- [ ] **Step 5: 提交**
```bash
git add csm_core/factcheck/checker.py csm_core/factcheck/__init__.py tests/core/factcheck/test_checker.py
git commit -m "feat(factcheck): check_facts 按集合判越界数字/认证 + 句子定位"
```

---

# Part B — 注入装配 + prompt

### Task B1: `inject.py` — 作用域提取 + brand_facts 渲染 + 白名单

**Files:**
- Create: `csm_core/brand_memory/inject.py`
- Test: `tests/core/brand_memory/test_inject.py`

- [ ] **Step 1: 写失败测试**（建 tmp vault + 真扫描 + 手搭 plan，走真实 resolve/registry 路径）

`tests/core/brand_memory/test_inject.py`:
```python
from pathlib import Path

from csm_core.assembler.plan import AssemblyPlan, BlockResult, PickedVariant
from csm_core.vault.scanner import scan_vault
from csm_core.vault.brand_registry import build_brand_registry
from csm_core.brand_memory.inject import (
    resolve_scopes, render_brand_facts, build_whitelist,
)

VAULT = "营销资料库/产品模块/吸尘器"
TESTS = "营销资料库/测试项目模块/吸尘器"


def _w(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text.strip() + "\n", encoding="utf-8")


def _vault(root: Path) -> None:
    _w(root / VAULT / "产品参数/CEWEYDS18-产品参数.md",
       "---\n产品: 吸尘器\n素材类型: 产品参数\n核心关键词: x\n---\n"
       "## 性能参数\n\n| 参数 | 数值 |\n|--|--|\n| 吸力(AW) | 220 |\n"
       "| 电机转速 | 12万转 |\n\n"
       "## 基础信息\n\n| 参数 | 数值 |\n|--|--|\n| 认证检测 | CE、FCC |\n")
    _w(root / VAULT / "产品参数/戴森V12-产品参数.md",
       "---\n产品: 吸尘器\n素材类型: 产品参数\n核心关键词: x\n---\n"
       "## 性能参数\n\n| 参数 | 数值 |\n|--|--|\n| 吸力(AW) | 240 |\n")
    _w(root / VAULT / "希喂推荐内容/核心技术/吸尘器-CEWEY核心技术-动力系统①.md",
       "---\n产品: 吸尘器\n素材类型: 动力系统\n核心关键词: x\n---\n"
       "① 220AW强劲吸力。\n\n② 12万转高速电机。\n\n③ 双层增压。\n\n④ 第四条变体。\n")
    _w(root / VAULT / "希喂推荐内容/品牌背书/吸尘器-CEWEY品牌背书-品牌定位①.md",
       "---\n产品: 吸尘器\n素材类型: 品牌定位\n核心关键词: x\n---\n① CEWEY 技术型品牌。\n")
    _w(root / VAULT / "竞品推荐内容/竞品-戴森V12.md",
       "---\n产品: 吸尘器\n素材类型: 产品推荐理由\n核心关键词: x\n---\n① 戴森V12 高端机型。\n")


def _plan() -> AssemblyPlan:
    return AssemblyPlan(
        keyword="无线吸尘器哪款好", template_id="t", seed=0,
        results=[
            BlockResult(block_id="hero", kind="hero_brand", text="CEWEYDS18"),
            BlockResult(block_id="comp", kind="competitor_pool", picks=[
                PickedVariant(note_id="竞品-戴森V12", variant_index=0, text="...",
                              meta={"title": "戴森V12", "model": "竞品-戴森V12"}),
            ]),
            BlockResult(block_id="junk", kind="hero_brand", text="不是型号的标题"),
        ],
    )


def _scopes(tmp_path: Path):
    _vault(tmp_path)
    index = scan_vault(tmp_path)
    registry = build_brand_registry(tmp_path)
    return resolve_scopes(
        _plan(), index, registry, own_brands={"CEWEY"}, category="吸尘器",
    )


def test_resolve_scopes_registry_anchored(tmp_path):
    scopes = _scopes(tmp_path)
    by_model = {s.model: s for s in scopes}
    assert set(by_model) == {"CEWEYDS18", "戴森V12"}   # 垃圾标题被丢弃
    assert by_model["CEWEYDS18"].brand == "CEWEY"
    assert by_model["CEWEYDS18"].role == "主推"
    assert by_model["戴森V12"].role == "竞品"


def test_render_brand_facts_caps_variants_and_uses_raw_specs(tmp_path):
    scopes = _scopes(tmp_path)
    facts = render_brand_facts(scopes, variant_cap=3, endorsement_cap=5)
    assert "吸力(AW): 220" in facts
    assert "电机转速: 12万转" in facts        # specs 用原始文本（万 不展开）
    assert "CE、FCC" in facts
    assert facts.count("第四条变体") == 0      # 每维度 ≤3 变体
    assert "技术型品牌" in facts               # 背书


def test_build_whitelist_unions_specs_and_sources(tmp_path):
    scopes = _scopes(tmp_path)
    facts = render_brand_facts(scopes)
    wl = build_whitelist(scopes, source_texts=["草稿提到 1700L/min。", facts])
    assert 220.0 in wl.numbers          # CEWEY specs
    assert 240.0 in wl.numbers          # 竞品 specs（也并入）
    assert 120000.0 in wl.numbers       # 12万转 经 normalize 展开（来自 facts 文本）
    assert 1700.0 in wl.numbers         # 来自 draft 源文本
    assert "CE" in wl.certs and "FCC" in wl.certs
```

- [ ] **Step 2: 跑测试确认失败** — `ModuleNotFoundError: csm_core.brand_memory.inject`。

- [ ] **Step 3: 写实现**

`csm_core/brand_memory/inject.py`:
```python
"""Plan 3 injection assembly.

从一份 AssemblyPlan 算出文章涉及哪些 (品牌, 型号)、resolve 各自记忆、渲染
喂给 LLM 的结构化事实块、并构建导出前事实核对用的「注入源并集」白名单。

作用域提取**以 registry 为锚**：sampler 吐出的型号串（picks 的 meta
型号/title、hero title）只有 registry 认识才采纳 —— 垃圾标题被丢、品牌由
registry 统一解析（全名型号约定，见 Plan 2）。registry 不认识的型号（只有
intro 没有产品参数的竞品）这步不贡献记忆，但其数字仍随 draft 进白名单，
故不会误拦。本模块依赖 factcheck（extract_certs）与 whitelist（normalize_
numbers/FactWhitelist）；factcheck 不反向依赖 brand_memory，无循环。
"""
from __future__ import annotations
from dataclasses import dataclass

from csm_core.assembler.plan import AssemblyPlan, BlockResult
from csm_core.vault.brand_registry import BrandRegistry
from csm_core.vault.scanner import VaultIndex
from csm_core.factcheck import extract_certs
from .identity import BRAND_ALIASES
from .model import BrandModelMemory
from .resolver import resolve_memory
from .whitelist import FactWhitelist, normalize_numbers


@dataclass
class ModelScope:
    brand: str
    model: str
    role: str            # 主推 | 竞品
    memory: BrandModelMemory


def _model_candidates(plan: AssemblyPlan) -> list[str]:
    """sampler 吐出的型号串，保序去重（hero text + picks meta title/型号）。"""
    out: list[str] = []
    seen: set[str] = set()

    def add(m) -> None:
        m = (m or "").strip() if isinstance(m, str) else m
        if m and m not in seen:
            seen.add(m)
            out.append(m)

    def walk(results: list[BlockResult]) -> None:
        for r in results:
            if r.kind == "hero_brand" and r.text:
                add(r.text)
            for p in r.picks:
                add(p.meta.get("title") or p.meta.get("model"))
            walk(r.children)

    walk(plan.results)
    return out


def resolve_scopes(
    plan: AssemblyPlan, index: VaultIndex, registry: BrandRegistry,
    *, own_brands: set[str], category: str,
    aliases: dict[str, list[str]] = BRAND_ALIASES,
) -> list[ModelScope]:
    """registry 认识的涉及型号 → ModelScope（含 resolve 出的记忆）。"""
    scopes: list[ModelScope] = []
    seen: set[str] = set()
    for cand in _model_candidates(plan):
        brand = registry.brand_of(cand)
        if brand is None or cand in seen:
            continue
        seen.add(cand)
        mem = resolve_memory(
            brand, cand, category, index, own_brands=own_brands, aliases=aliases,
        )
        scopes.append(ModelScope(brand=brand, model=cand, role=mem.role, memory=mem))
    return scopes


def render_brand_facts(
    scopes: list[ModelScope], *,
    variant_cap: int = 3, endorsement_cap: int = 5,
) -> str:
    """渲染注入 LLM 的事实块。

    specs **全量**、用每格 *原始* 文本（``12万转`` 原样 —— 白名单两侧同样
    归一）。scripts 每维度 ≤``variant_cap`` 变体、endorsements ≤
    ``endorsement_cap``（token 预算，spec §4.1）。竞品只给 specs/certs/intro
    （无自家话术）。背书是品牌级，同品牌只渲染一次。
    """
    blocks: list[str] = []
    brand_endorsed: set[str] = set()
    for sc in scopes:
        m = sc.memory
        lines = [f"## {sc.brand} {sc.model}（{sc.role}）"]
        if m.specs:
            lines.append("参数：")
            lines.extend(f"- {sv.field}: {sv.raw}" for sv in m.specs.values())
        if m.certs:
            lines.append(f"认证：{'、'.join(m.certs)}")
        for dim, variants in m.scripts.items():
            shown = variants[:variant_cap]
            if shown:
                lines.append(f"{dim}：")
                lines.extend(f"- {v}" for v in shown)
        if m.intro:
            lines.append("介绍：")
            lines.extend(f"- {v}" for v in m.intro[:variant_cap])
        if m.endorsements and sc.brand not in brand_endorsed:
            brand_endorsed.add(sc.brand)
            lines.append("品牌背书：")
            lines.extend(f"- {v}" for v in m.endorsements[:endorsement_cap])
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def build_whitelist(
    scopes: list[ModelScope], *, source_texts: list[str],
) -> FactWhitelist:
    """全文级·注入源并集白名单（关键设计决定 #1、spec §2.3）。

    numbers = ⋃ specs 数值 ∪ normalize_numbers(源文本)；源文本 = draft +
    已注入 brand_facts。certs = ⋃ specs 认证 ∪ 源文本里出现的已知认证名
    （背书散文提到但参数表认证格没有的认证也不会被误拦）。
    """
    numbers: set[float] = set()
    certs: set[str] = set()
    for sc in scopes:
        for sv in sc.memory.specs.values():
            numbers.update(sv.numbers)
        certs.update(sc.memory.certs)
    for t in source_texts:
        numbers |= normalize_numbers(t)
        certs |= set(extract_certs(t))
    return FactWhitelist(numbers=numbers, certs=certs)
```

- [ ] **Step 4: 跑测试确认通过** — `pytest tests/core/brand_memory/test_inject.py -v` → PASS（4 passed）。

- [ ] **Step 5: 提交**
```bash
git add csm_core/brand_memory/inject.py tests/core/brand_memory/test_inject.py
git commit -m "feat(brand_memory): inject 作用域提取(registry锚) + brand_facts 渲染 + 注入源并集白名单"
```

---

### Task B2: `prompts.brand_facts` 注入 + 硬约束

**Files:**
- Modify: `csm_core/llm/prompts.py`
- Test: `tests/core/llm/test_prompts.py`（追加）

- [ ] **Step 1: 写失败测试**（追加到 `tests/core/llm/test_prompts.py` 末尾 —— `from csm_core.llm.prompts import PromptInputs, build_prompt` 已在文件首行，勿重复导入，只加下面两个函数）
```python
def test_build_prompt_without_brand_facts_is_unchanged():
    s, u = build_prompt(PromptInputs(
        user_skill_prompt="人设", keyword="无线吸尘器", draft="草稿正文"))
    assert s == "人设"
    assert "【关键词】无线吸尘器" in u
    assert "【毛坯文】" in u and "草稿正文" in u
    assert "品牌型号事实" not in u        # 无 facts 不注入该段
    assert "严禁引入" not in u


def test_build_prompt_injects_brand_facts_and_hard_constraint():
    s, u = build_prompt(PromptInputs(
        user_skill_prompt=None, keyword="kw", draft="草稿",
        brand_facts="## CEWEY DS18（主推）\n参数：\n- 吸力(AW): 220"))
    assert "品牌型号事实" in u
    assert "吸力(AW): 220" in u
    assert "严禁引入" in u                 # 硬约束句
    # facts 段排在毛坯文之前
    assert u.index("品牌型号事实") < u.index("【毛坯文】")
```

- [ ] **Step 2: 跑测试确认失败** — `TypeError: ... unexpected keyword argument 'brand_facts'`。

- [ ] **Step 3: 写实现** — 重写 `csm_core/llm/prompts.py`:
```python
"""Compose prompt from a single user-selected skill. Template-level
system_prompt / SEO constraints were folded into the skill .md at migration
time (see scripts/migrate_template_to_skill.py); they no longer live on
the Template model."""
from __future__ import annotations
from dataclasses import dataclass


@dataclass
class PromptInputs:
    user_skill_prompt: str | None
    keyword: str
    draft: str
    # Plan 3: 结构化型号事实（参数/认证/话术/背书）。None = 不注入（今天行为）。
    brand_facts: str | None = None


def build_prompt(inputs: PromptInputs) -> tuple[str, str]:
    system = (inputs.user_skill_prompt or "").strip()
    facts_block = ""
    constraint = ""
    if inputs.brand_facts:
        facts_block = (
            "【品牌型号事实（仅可使用以下参数/认证，不得新增或改动任何"
            "数字、单位、认证名）】\n"
            f"{inputs.brand_facts}\n\n"
        )
        constraint = "\n严禁引入上面【品牌型号事实】之外的任何参数数字或认证名称。"
    user = (
        f"【关键词】{inputs.keyword}\n\n"
        f"{facts_block}"
        f"【毛坯文】\n{inputs.draft}\n\n"
        "请按**润色模式**重写：保留所有信息点和段落结构，只改进文字流畅度、"
        "衔接和风格一致性；不新增虚构事实，不删减关键信息。"
        f"{constraint}"
    )
    return system, user
```

- [ ] **Step 4: 跑测试确认通过** — `pytest tests/core/llm/test_prompts.py -v` → PASS。

- [ ] **Step 5: 提交**
```bash
git add csm_core/llm/prompts.py tests/core/llm/test_prompts.py
git commit -m "feat(llm): PromptInputs.brand_facts 注入事实段 + 不得新增数字硬约束（向后兼容）"
```

---

# Part C — 配置 + 生成服务门禁 + resume 端点

### Task C1: `BrandMemoryConfig` feature flags

**Files:**
- Modify: `csm_core/config.py`
- Test: `tests/core/test_config_brand_memory.py`

- [ ] **Step 1: 写失败测试**

`tests/core/test_config_brand_memory.py`:
```python
from csm_core.config import AppConfig, BrandMemoryConfig, load_config, save_config


def test_brand_memory_defaults_off():
    cfg = AppConfig()
    assert cfg.brand_memory.inject is False
    assert cfg.brand_memory.factcheck is False
    assert cfg.brand_memory.own_brands == ["CEWEY"]
    assert cfg.brand_memory.inject_variant_cap == 3
    assert cfg.brand_memory.inject_endorsement_cap == 5


def test_brand_memory_roundtrip(tmp_path):
    p = tmp_path / "settings.json"
    save_config(AppConfig(brand_memory=BrandMemoryConfig(
        inject=True, factcheck=True, own_brands=["CEWEY", "希喂"])), p)
    loaded = load_config(p)
    assert loaded.brand_memory.inject is True
    assert loaded.brand_memory.factcheck is True
    assert loaded.brand_memory.own_brands == ["CEWEY", "希喂"]


def test_legacy_settings_without_brand_memory_defaults(tmp_path):
    # 旧 settings.json 没有 brand_memory 段 → 取默认（关）
    p = tmp_path / "s.json"
    p.write_text('{"vault_root": "x"}', encoding="utf-8")
    assert load_config(p).brand_memory.inject is False
```

- [ ] **Step 2: 跑测试确认失败** — `ImportError: cannot import name 'BrandMemoryConfig'`。

- [ ] **Step 3: 写实现** — 在 `csm_core/config.py` `class AppConfig` **之前**加：
```python
class BrandMemoryConfig(BaseModel):
    """settings.brand_memory.* —— Phase 1 注入 + 事实核对（默认全关 = 今天行为）。"""

    # 生成时注入型号记忆（参数/认证/话术/背书）到 prompt。
    inject: bool = False
    # 导出前事实核对硬门禁（拦编造数字/认证）。
    factcheck: bool = False
    # 自家品牌清单 —— 判 主推 vs 竞品（不靠文件夹名猜）。
    own_brands: list[str] = Field(default_factory=lambda: ["CEWEY"])
    # token 预算：每个话术维度注入的变体上限。
    inject_variant_cap: int = 3
    # token 预算：每个品牌背书注入的条数上限。
    inject_endorsement_cap: int = 5
```
在 `AppConfig` 里（Monitor 段附近）加字段：
```python
    # ── Brand/model memory (Phase 1: 注入 + 事实核对) ───────────────────
    brand_memory: BrandMemoryConfig = Field(default_factory=BrandMemoryConfig)
```

- [ ] **Step 4: 跑测试确认通过** — `pytest tests/core/test_config_brand_memory.py -v` → PASS（3 passed）。

- [ ] **Step 5: 提交**
```bash
git add csm_core/config.py tests/core/test_config_brand_memory.py
git commit -m "feat(config): BrandMemoryConfig feature flags（inject/factcheck/own_brands/token 上限，默认关）"
```

---

### Task C2: `generate_service` 注入步 + 门禁种子 `_maybe_block_for_factcheck`

**Files:**
- Modify: `sidecar/csm_sidecar/services/generate_service.py`
- Test: `sidecar/tests/test_generate_factcheck_gate.py`

> 门禁逻辑抽成纯接线种子 `_maybe_block_for_factcheck`，**直接单测**它（不跑全 `_run_job`，后者 happy-path 仍由现有 skipped 集成测试 + Task D1 覆盖）。

- [ ] **Step 1: 写失败测试**

`sidecar/tests/test_generate_factcheck_gate.py`:
```python
from pathlib import Path

from csm_core.config import AppConfig, BrandMemoryConfig
from csm_core.assembler.plan import AssemblyPlan
from csm_core.brand_memory.model import BrandModelMemory, SpecValue
from csm_core.brand_memory.inject import ModelScope
from csm_sidecar.services import generate_service, factcheck_service


def _scope() -> ModelScope:
    mem = BrandModelMemory(
        brand="CEWEY", model="CEWEYDS18", category="吸尘器", role="主推",
        specs={"吸力(AW)": SpecValue(field="吸力(AW)", raw="220", numbers=[220.0])},
        certs=["CE"],
    )
    return ModelScope(brand="CEWEY", model="CEWEYDS18", role="主推", memory=mem)


def _plan() -> AssemblyPlan:
    return AssemblyPlan(keyword="无线吸尘器", template_id="t", seed=0)


def _cfg(*, factcheck: bool) -> AppConfig:
    return AppConfig(out_dir="x", brand_memory=BrandMemoryConfig(factcheck=factcheck))


def _capture_finish(monkeypatch):
    calls = {}
    monkeypatch.setattr(generate_service.bus, "finish",
                        lambda job_id, **d: calls.update(job_id=job_id, **d))
    return calls


def test_gate_blocks_on_fabricated_number(tmp_path: Path, monkeypatch):
    factcheck_service.reset_for_test()
    calls = _capture_finish(monkeypatch)
    blocked = generate_service._maybe_block_for_factcheck(
        "job1", final_text="吸力高达250AW。", scopes=[_scope()],
        draft="草稿：220AW。", brand_facts=None, cfg=_cfg(factcheck=True),
        plan=_plan(), out_dir=tmp_path,
    )
    assert blocked is True
    assert calls["document"] is None
    assert calls["factcheck"]["blocked"] is True
    assert calls["factcheck"]["violations"][0]["value"] == "250AW"
    assert factcheck_service.get_pending("job1") is not None   # 待导出已缓存


def test_gate_passes_on_faithful_text(tmp_path: Path, monkeypatch):
    factcheck_service.reset_for_test()
    calls = _capture_finish(monkeypatch)
    blocked = generate_service._maybe_block_for_factcheck(
        "job2", final_text="吸力220AW，通过CE认证。", scopes=[_scope()],
        draft="草稿：220AW。", brand_facts=None, cfg=_cfg(factcheck=True),
        plan=_plan(), out_dir=tmp_path,
    )
    assert blocked is False
    assert calls == {}                                  # 未提前 finish
    assert factcheck_service.get_pending("job2") is None


def test_gate_disabled_returns_false(tmp_path: Path, monkeypatch):
    factcheck_service.reset_for_test()
    calls = _capture_finish(monkeypatch)
    blocked = generate_service._maybe_block_for_factcheck(
        "job3", final_text="吸力999AW。", scopes=[_scope()],
        draft="", brand_facts=None, cfg=_cfg(factcheck=False),
        plan=_plan(), out_dir=tmp_path,
    )
    assert blocked is False and calls == {}


def test_gate_no_scopes_returns_false(tmp_path: Path, monkeypatch):
    factcheck_service.reset_for_test()
    _capture_finish(monkeypatch)
    blocked = generate_service._maybe_block_for_factcheck(
        "job4", final_text="吸力999AW。", scopes=[], draft="",
        brand_facts=None, cfg=_cfg(factcheck=True), plan=_plan(), out_dir=tmp_path,
    )
    assert blocked is False
```

- [ ] **Step 2: 跑测试确认失败** — `AttributeError: module ... has no attribute '_maybe_block_for_factcheck'`（`factcheck_service` 也还没建 → 先做 Task C3 的 service 文件，或本 Task 先建一个最小 `factcheck_service` 桩。推荐：**先做 C3 的 `factcheck_service.py`**，再回到 C2。两者互相引用，按 C3→C2 顺序实现最顺。）

> **实现顺序提示**：C2 的门禁种子 import `factcheck_service`，C3 的 service 是被 import 方。建议先实现 C3 的 `factcheck_service.py`（Task C3 Step 3 的 service 部分），跑通 C2 测试，再补 C3 的 route。本计划保留 C2/C3 编号，执行时按「C3 service → C2 → C3 route」推进。

- [ ] **Step 3: 写实现** — 改 `sidecar/csm_sidecar/services/generate_service.py`：

顶部 import 区加：
```python
from csm_core.brand_memory.inject import build_whitelist, render_brand_facts, resolve_scopes
from csm_core.factcheck import check_facts
```
`from . import (...)` 列表里加 `factcheck_service`。

加门禁种子函数（放在 `_run_job` 之后、`_plan_to_dict` 之前）：
```python
def _maybe_block_for_factcheck(
    job_id: str, *, final_text: str, scopes: list, draft: str,
    brand_facts: str | None, cfg, plan, out_dir: Path,
) -> bool:
    """导出前事实核对。命中越界 → 缓存待导出 + 以 done(blocked) 收尾、返回
    True（调用方须在导出前停下）。核对关 / 无型号 / 成稿干净 → False。"""
    if not cfg.brand_memory.factcheck or not scopes:
        return False
    sources = [draft] + ([brand_facts] if brand_facts else [])
    wl = build_whitelist(scopes, source_texts=sources)
    report = check_facts(
        final_text, allowed_numbers=wl.numbers, allowed_certs=wl.certs,
    )
    if report.ok:
        return False
    factcheck_service.cache_pending(
        job_id, plan=plan, out_dir=out_dir, keyword=plan.keyword,
        fmt=cfg.export_format, allowed_numbers=wl.numbers, allowed_certs=wl.certs,
    )
    bus.finish(
        job_id, document=None, plan=_plan_to_dict(plan), draft=draft,
        final_text=final_text,
        factcheck={
            "blocked": True,
            "violations": [v.model_dump() for v in report.violations],
        },
    )
    return True
```

在 `_run_job` 里接线 —— 把「组装 prompt」之后到「调用 LLM / 导出」之间改为：
```python
        draft = compose_draft(plan)
        # ...（既有 assembly publish + draft_only 早退，保持不动）...

        # Plan 3: 注入型号记忆 + 事实核对作用域。两个 flag 都关 = 跳过。
        cfg_bm = cfg.brand_memory
        scopes: list = []
        brand_facts: str | None = None
        if cfg_bm.inject or cfg_bm.factcheck:
            scopes = resolve_scopes(
                plan, index, registry,
                own_brands=set(cfg_bm.own_brands),
                category=template.product,
            )
            if scopes:
                brand_facts = render_brand_facts(
                    scopes,
                    variant_cap=cfg_bm.inject_variant_cap,
                    endorsement_cap=cfg_bm.inject_endorsement_cap,
                )

        client: LLMClient = llm_factory.build_client(
            provider=req.provider, model=req.model,
        )
        system, user = build_prompt(PromptInputs(
            user_skill_prompt=skill_prompt,
            keyword=req.keyword,
            draft=draft,
            brand_facts=brand_facts if cfg_bm.inject else None,
        ))

        _checkpoint(job_id)
        bus.publish(job_id, "stage", stage="调用 LLM", index=4, total=6)
        final_text = client.complete(system=system, user=user)

        # 导出前硬门禁：命中越界则缓存待导出 + done(blocked)，不导出。
        if _maybe_block_for_factcheck(
            job_id, final_text=final_text, scopes=scopes, draft=draft,
            brand_facts=brand_facts if cfg_bm.inject else None,
            cfg=cfg, plan=plan, out_dir=out_dir,
        ):
            return

        bus.publish(job_id, "stage", stage="导出", index=5, total=6)
        # ...（既有 export_article + bus.finish，保持不动）...
```
> 注意：白名单的 `source_texts` 里 `brand_facts` 仅在 `cfg_bm.inject` 为真（即真注入了）时并入；specs 数值/认证无论是否注入都在白名单里（它们是型号真实事实）。

- [ ] **Step 4: 跑测试确认通过** — `pytest sidecar/tests/test_generate_factcheck_gate.py -v` → PASS（4 passed）。

- [ ] **Step 5: 提交**
```bash
git add sidecar/csm_sidecar/services/generate_service.py sidecar/tests/test_generate_factcheck_gate.py
git commit -m "feat(generate): 注入型号记忆 + 导出前事实核对门禁（_maybe_block_for_factcheck，flag 默认关）"
```

---

### Task C3: `factcheck_service` 缓存 + resume + `POST /api/generate/{id}/export`

**Files:**
- Create: `sidecar/csm_sidecar/services/factcheck_service.py`
- Modify: `sidecar/csm_sidecar/routes/generate.py`
- Modify: `sidecar/tests/conftest.py`（按测试重置缓存）
- Test: `sidecar/tests/test_factcheck_service.py`、`sidecar/tests/test_generate_factcheck_route.py`

- [ ] **Step 1: 写失败测试**

`sidecar/tests/test_factcheck_service.py`:
```python
from pathlib import Path

import pytest

from csm_core.assembler.plan import AssemblyPlan
from csm_sidecar.services import factcheck_service


def _plan() -> AssemblyPlan:
    return AssemblyPlan(keyword="无线吸尘器", template_id="t", seed=0)


def _seed(job_id: str, out_dir: Path) -> None:
    factcheck_service.cache_pending(
        job_id, plan=_plan(), out_dir=out_dir, keyword="无线吸尘器",
        fmt="markdown", allowed_numbers={220.0}, allowed_certs={"CE"},
    )


def test_resolve_exports_when_clean(tmp_path: Path):
    factcheck_service.reset_for_test()
    _seed("j1", tmp_path)
    res = factcheck_service.resolve_and_export(
        "j1", final_text="吸力220AW，CE认证。", released_numbers=[], released_certs=[])
    assert res["ok"] is True
    assert Path(res["document"]).exists()
    assert factcheck_service.get_pending("j1") is None   # 成功后清缓存


def test_resolve_still_blocked_when_violation_remains(tmp_path: Path):
    factcheck_service.reset_for_test()
    _seed("j2", tmp_path)
    res = factcheck_service.resolve_and_export(
        "j2", final_text="吸力250AW。", released_numbers=[], released_certs=[])
    assert res["ok"] is False
    assert res["violations"][0]["value"] == "250AW"
    assert factcheck_service.get_pending("j2") is not None  # 仍待处理


def test_resolve_with_released_number_passes(tmp_path: Path):
    factcheck_service.reset_for_test()
    _seed("j3", tmp_path)
    res = factcheck_service.resolve_and_export(
        "j3", final_text="吸力250AW。", released_numbers=[250.0], released_certs=[])
    assert res["ok"] is True and Path(res["document"]).exists()


def test_resolve_unknown_job_raises(tmp_path: Path):
    factcheck_service.reset_for_test()
    with pytest.raises(KeyError):
        factcheck_service.resolve_and_export(
            "nope", final_text="x", released_numbers=[], released_certs=[])
```

`sidecar/tests/test_generate_factcheck_route.py`:
```python
from pathlib import Path

from fastapi.testclient import TestClient

from csm_core.assembler.plan import AssemblyPlan
from csm_sidecar.services import factcheck_service


def test_export_route_404_when_no_pending(client: TestClient):
    factcheck_service.reset_for_test()
    r = client.post("/api/generate/ghost/export",
                    json={"final_text": "x", "released_numbers": [], "released_certs": []})
    assert r.status_code == 404


def test_export_route_exports_when_clean(client: TestClient, tmp_path: Path):
    factcheck_service.reset_for_test()
    factcheck_service.cache_pending(
        "jr", plan=AssemblyPlan(keyword="kw", template_id="t", seed=0),
        out_dir=tmp_path, keyword="kw", fmt="markdown",
        allowed_numbers={220.0}, allowed_certs=set())
    r = client.post("/api/generate/jr/export",
                    json={"final_text": "吸力220AW。", "released_numbers": [],
                          "released_certs": []})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True and Path(body["document"]).exists()


def test_export_route_returns_remaining_violations(client: TestClient, tmp_path: Path):
    factcheck_service.reset_for_test()
    factcheck_service.cache_pending(
        "jv", plan=AssemblyPlan(keyword="kw", template_id="t", seed=0),
        out_dir=tmp_path, keyword="kw", fmt="markdown",
        allowed_numbers={220.0}, allowed_certs=set())
    r = client.post("/api/generate/jv/export",
                    json={"final_text": "吸力300AW。", "released_numbers": [],
                          "released_certs": []})
    assert r.status_code == 200
    assert r.json()["ok"] is False
```

- [ ] **Step 2: 跑测试确认失败** — `ModuleNotFoundError` / 404 路由不存在。

- [ ] **Step 3: 写实现**

`sidecar/csm_sidecar/services/factcheck_service.py`:
```python
"""Pending-export cache for the fact-check gate + the resume/export step.

事实核对命中越界时，generate_service 把导出所需的一切（plan/out_dir/
keyword/fmt + 白名单两集合）按 job_id 缓存到这里，并以 done(blocked) 收尾
而不导出。前端审查面板（Plan 5）让用户改文案 / 标通用 / 放行后 POST
/api/generate/{job_id}/export → resolve_and_export 用放行项补进白名单重核
（成稿可能已被用户编辑），干净则落盘。

缓存 LRU 有界（仿 assembler_service）—— 条目小（plan 树 + 两个集合）。
"""
from __future__ import annotations

import threading
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from csm_core.assembler.plan import AssemblyPlan
from csm_core.export.markdown import ExportFormat, export_article
from csm_core.factcheck import check_facts


@dataclass
class _Pending:
    plan: AssemblyPlan
    out_dir: Path
    keyword: str
    fmt: ExportFormat
    allowed_numbers: set[float]
    allowed_certs: set[str]


_cache: "OrderedDict[str, _Pending]" = OrderedDict()
_lock = threading.Lock()
MAX_CACHE = 50


def cache_pending(
    job_id: str, *, plan: AssemblyPlan, out_dir: Path, keyword: str,
    fmt: ExportFormat, allowed_numbers: set[float], allowed_certs: set[str],
) -> None:
    with _lock:
        _cache[job_id] = _Pending(
            plan=plan, out_dir=Path(out_dir), keyword=keyword, fmt=fmt,
            allowed_numbers=set(allowed_numbers), allowed_certs=set(allowed_certs),
        )
        _cache.move_to_end(job_id)
        while len(_cache) > MAX_CACHE:
            _cache.popitem(last=False)


def get_pending(job_id: str) -> _Pending | None:
    with _lock:
        e = _cache.get(job_id)
        if e is not None:
            _cache.move_to_end(job_id)
        return e


def resolve_and_export(
    job_id: str, *, final_text: str,
    released_numbers: list[float], released_certs: list[str],
) -> dict[str, Any]:
    """带放行项重核（成稿可能已被编辑）；干净则导出。

    返回 {"ok": True, "document", "format", "title"} 或
    {"ok": False, "violations": [...]}。未知 job_id（过期 / 从未被拦）→ KeyError。
    """
    e = get_pending(job_id)
    if e is None:
        raise KeyError(job_id)
    allowed_numbers = e.allowed_numbers | {float(n) for n in released_numbers}
    allowed_certs = e.allowed_certs | set(released_certs)
    report = check_facts(
        final_text, allowed_numbers=allowed_numbers, allowed_certs=allowed_certs,
    )
    if not report.ok:
        return {"ok": False,
                "violations": [v.model_dump() for v in report.violations]}
    e.out_dir.mkdir(parents=True, exist_ok=True)
    paths = export_article(
        out_dir=e.out_dir, keyword=e.keyword, final_text=final_text,
        plan=e.plan, fmt=e.fmt,
    )
    with _lock:
        _cache.pop(job_id, None)
    return {"ok": True, **paths}


def reset_for_test() -> None:
    with _lock:
        _cache.clear()
```

改 `sidecar/csm_sidecar/routes/generate.py` —— import 加 `HTTPException`、`factcheck_service`，并加端点：
```python
from fastapi import APIRouter, HTTPException
# ...
from ..services import factcheck_service, generate_service
# ...


class ResolveFactcheckBody(BaseModel):
    final_text: str = Field(min_length=1)
    released_numbers: list[float] = Field(default_factory=list)
    released_certs: list[str] = Field(default_factory=list)


@router.post("/api/generate/{job_id}/export")
def resolve_factcheck(job_id: str, body: ResolveFactcheckBody) -> dict:
    """重核一篇被事实核对拦下的成稿（含用户放行项），干净则导出。

    job_id 不是「待事实核对处理」状态（过期 / 从未被拦）→ 404。
    返回 {"ok": True, document/format/title} 或 {"ok": False, violations}。
    """
    try:
        return factcheck_service.resolve_and_export(
            job_id,
            final_text=body.final_text,
            released_numbers=body.released_numbers,
            released_certs=body.released_certs,
        )
    except KeyError:
        raise HTTPException(
            status_code=404, detail=f"no pending fact-check for job {job_id}")
```

改 `sidecar/tests/conftest.py` —— 在 `client` fixture 里按测试清 factcheck 缓存（防跨测试泄漏）。把 import 加上 `factcheck_service`，并在 `client` fixture yield 前后 reset：
```python
from csm_sidecar.services import config_service, factcheck_service, vault_service
# ...
@pytest.fixture
def client(settings_path: Path, vault_cache_reset) -> Iterator[TestClient]:
    factcheck_service.reset_for_test()
    with TestClient(app) as c:
        c.headers["Authorization"] = f"Bearer {auth.get_token()}"
        yield c
    factcheck_service.reset_for_test()
```

- [ ] **Step 4: 跑测试确认通过**
```
pytest sidecar/tests/test_factcheck_service.py sidecar/tests/test_generate_factcheck_route.py -v
```
→ PASS（4 + 3）。同时回跑 Task C2：`pytest sidecar/tests/test_generate_factcheck_gate.py -v` → PASS。

- [ ] **Step 5: 提交**
```bash
git add sidecar/csm_sidecar/services/factcheck_service.py sidecar/csm_sidecar/routes/generate.py sidecar/tests/conftest.py sidecar/tests/test_factcheck_service.py sidecar/tests/test_generate_factcheck_route.py
git commit -m "feat(generate): factcheck_service 待导出缓存 + resume 重核 + POST /api/generate/{id}/export"
```

---

# Part D — 真实库回归 + 整包

### Task D1: 真实库注入/核对集成（验收 #3 #4）

**Files:**
- Test: `tests/core/brand_memory/test_inject_real_vault.py`

- [ ] **Step 1: 写测试**（默认跳过；开发机有真实 vault 时手动跑，端到端验证「忠实成稿不拦 + 编造被拦」）

`tests/core/brand_memory/test_inject_real_vault.py`:
```python
from pathlib import Path

import pytest

from csm_core.assembler.plan import AssemblyPlan, BlockResult
from csm_core.vault.scanner import scan_vault
from csm_core.vault.brand_registry import build_brand_registry
from csm_core.brand_memory.inject import (
    resolve_scopes, render_brand_facts, build_whitelist,
)
from csm_core.factcheck import check_facts

VAULT = Path(r"D:\家电组共享\DATA\营销资料库")


def _ds18_scopes():
    index = scan_vault(VAULT)
    registry = build_brand_registry(VAULT)
    plan = AssemblyPlan(
        keyword="无线吸尘器", template_id="t", seed=0,
        results=[BlockResult(block_id="hero", kind="hero_brand", text="CEWEYDS18")])
    scopes = resolve_scopes(
        plan, index, registry, own_brands={"CEWEY"}, category="吸尘器")
    return scopes, render_brand_facts(scopes)


@pytest.mark.integration
@pytest.mark.skipif(not VAULT.exists(), reason="真实 vault 不在本机")
def test_real_ds18_facts_have_specs_and_certs():
    scopes, facts = _ds18_scopes()
    assert scopes and scopes[0].model == "CEWEYDS18"
    assert "参数：" in facts            # specs 渲染到了
    assert scopes[0].memory.specs       # 有参数


@pytest.mark.integration
@pytest.mark.skipif(not VAULT.exists(), reason="真实 vault 不在本机")
def test_real_faithful_draft_not_blocked():
    # 验收 #4：用注入事实本身当「忠实成稿」→ 不应被拦
    scopes, facts = _ds18_scopes()
    wl = build_whitelist(scopes, source_texts=[facts])
    report = check_facts(
        facts, allowed_numbers=wl.numbers, allowed_certs=wl.certs)
    assert report.ok, [v.model_dump() for v in report.violations]


@pytest.mark.integration
@pytest.mark.skipif(not VAULT.exists(), reason="真实 vault 不在本机")
def test_real_fabricated_number_blocked():
    # 验收 #3：注入事实里塞一个白名单外的离谱参数 → 被拦
    scopes, facts = _ds18_scopes()
    wl = build_whitelist(scopes, source_texts=[facts])
    tampered = facts + "\n实测吸力高达99999AW，远超同级。"
    report = check_facts(
        tampered, allowed_numbers=wl.numbers, allowed_certs=wl.certs)
    assert report.ok is False
    assert any(v.value == "99999AW" for v in report.violations)
```

- [ ] **Step 2: 手动跑一次（开发机）**
```
pytest tests/core/brand_memory/test_inject_real_vault.py -v -m integration
```
Expected: PASS（真实 vault 在本机时）；否则 SKIPPED。

- [ ] **Step 3: 提交**
```bash
git add tests/core/brand_memory/test_inject_real_vault.py
git commit -m "test(brand_memory): 真实库注入/核对集成（忠实不拦 + 编造被拦，默认跳过）"
```

---

### Final: 整包回归 + 收尾

- [ ] **Step 1: 跑本计划全部新增/改动测试**
```
D:/CSM/.venv/Scripts/python.exe -m pytest tests/core/factcheck tests/core/brand_memory tests/core/llm/test_prompts.py tests/core/test_config_brand_memory.py sidecar/tests/test_generate_factcheck_gate.py sidecar/tests/test_factcheck_service.py sidecar/tests/test_generate_factcheck_route.py -v
```
Expected: 全 PASS（integration 默认 SKIPPED）。

- [ ] **Step 2: 跑既有 generate 相关回归（确认零回归）**
```
D:/CSM/.venv/Scripts/python.exe -m pytest sidecar/tests/test_generate_routes.py sidecar/tests/test_generate_cancel.py tests/core/test_pipeline.py -v
```
Expected: 全 PASS（与 base 一致）。

  （总计划 `2026-06-23-phase1-brand-memory.md` 的 Plan 3 行已在细化时标记 ✅，无需再改。）

- [ ] **Step 3: 推分支 + `gh pr create`**（PR 流程：停在 pending 等网页 merge，**不本地 merge main**）。PR 描述中文，列出 7 项验收对照 + 「Plan 3 不做」边界 + 默认关零回归。

---

## 门禁 / 验收对照（spec §9）

| 验收 | 本计划覆盖 |
|---|---|
| #3 防幻觉：编造数字/认证被拦 | A2 `test_out_of_whitelist_*` + D1 `test_real_fabricated_number_blocked` + C2/C3 gate 测试 |
| #4 不误拦（关键回归）：忠实话术数字不拦 | A2 `test_faithful_*`/`test_bare_counts_*` + D1 `test_real_faithful_draft_not_blocked` |
| #5 hero/竞品互不误判 | 并集白名单天然满足（B1 `test_build_whitelist_unions_*` 含 hero+竞品 specs） |
| §4.1 注入命中维度+token 预算 | B1 `render_brand_facts`（≤variant_cap/≤endorsement_cap）+ C1 配置 |
| §4.1 feature flag | C1 `BrandMemoryConfig`（默认关）+ C2 接线 |
| §4.2 拦截导出 + 放行口（会话级） | C2 门禁(done blocked) + C3 resume(released_numbers/certs) |
| §7 全部 opt-in、零回归 | C1 默认关 + Final Step 2 既有回归 |

> **Plan 3 不做**（明确边界，留 Plan 5 / 后续）：审查面板 + 素材库 tab（Plan 5）；按槽位「数字张冠李戴」归属、非数字非认证编造门禁（§4.2 已知局限，后续）；guardrails 注入（来自 Plan 4 拆出的人设 skill）。

---

## Self-Review（对照 spec + 一致性）

- **Spec 覆盖**：§4.1 注入（PromptInputs.brand_facts B2 / 注入步 C2 / token 预算 B1+C1 / flag C1）；§4.2 核对（引擎 A / 拦截+放行 C2+C3）；§2.3 动态白名单（B1 `build_whitelist`，并集口径）。UI（§6）与按槽位归属（§4.2#4）明确留后。✅
- **占位符扫描**：无 TBD/TODO；每个 code step 含完整代码 + 可跑命令 + 期望。✅
- **类型/签名一致性**：`check_facts(text, *, allowed_numbers, allowed_certs)` 在 A2 定义，C2/C3 一致调用；`ModelScope(brand,model,role,memory)` B1 定义，C2 测试一致构造；`FactWhitelist`(.numbers/.certs) 复用 Plan 1，B1 产出、C2 拆给 check_facts；`cache_pending(...allowed_numbers, allowed_certs)`/`resolve_and_export(...released_numbers, released_certs)` C3 定义与 C2/route 一致。✅
- **导入无环**：factcheck 不依赖 brand_memory；inject 依赖 factcheck + whitelist；brand_memory.__init__ 不引 inject/factcheck。已逐链核验。✅
- **向后兼容**：PromptInputs 加默认 None 字段（pipeline.py / batch/runner.py 关键字构造，安全）；AppConfig 加默认 sub-model（旧 settings 缺段取默认）；happy-path finish 载荷在 flag 关时一字不改。✅
- **执行顺序提醒**：C2 与 C3-service 互引，按「C3 service → C2 → C3 route」实现（已在 C2 Step 2 标注）。
