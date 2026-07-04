# PR-B contract-scoring 实现计划（激进契约+完整性 + 评分+批量选优）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ① LLM 契约可切激进（允许取舍删减）+ 主推事实完整性反向核对（软警告）；② 确定性评分引擎（禁区+AI味+核对信号）+ 批量链路升级（注入/链/核对/评分/多候选选优）。

**Architecture:** csm_core 三块纯层（prompts 契约分支 / factcheck.completeness 反向核对 / scoring 评分引擎）→ sidecar 接线（config、finalize_draft 完整性、chain 契约穿透、`POST /api/score`、批量流水线升级）→ 前端（质检卡两项、Hero 契约单次覆盖、设置卡、批量评分列）。零回归锚点：保守分支 prompt **字节级不动**；`candidates=1`+单 skill+inject 关 = 今天批量成本结构。详见 `docs/superpowers/specs/2026-07-01-phase4-plus-design.md` §3-§4。

**Tech Stack:** Python（pydantic + dataclass + re + pytest）/ FastAPI sidecar / Vue 3 + Pinia + TS + vitest。

**分支：`claude/phase4-contract-scoring`（已基于 PR-A 头創建）。PR base = `claude/phase4-vault-perf`（stacked，PR-A merge 后 GitHub 自动 retarget main）。**

**测试命令（worktree 无 .venv，用主仓解释器 + PYTHONPATH 覆盖）：**
- csm_core：
  ```powershell
  $env:PYTHONPATH="D:\CSM\.claude\worktrees\affectionate-heisenberg-9bbcf4"; & "D:\CSM\.venv\Scripts\python.exe" -X utf8 -m pytest tests/core/contract_scoring/ -v
  ```
- sidecar（双路径）：
  ```powershell
  $env:PYTHONPATH="D:\CSM\.claude\worktrees\affectionate-heisenberg-9bbcf4;D:\CSM\.claude\worktrees\affectionate-heisenberg-9bbcf4\sidecar"; & "D:\CSM\.venv\Scripts\python.exe" -X utf8 -m pytest sidecar/tests/test_score_routes.py sidecar/tests/test_generate_contract.py sidecar/tests/test_batch_scoring.py -v
  ```
- 前端（worktree 若无 node_modules 先 `cd frontend; npm ci`）：
  ```powershell
  cd frontend; npx vitest run src/stores/__tests__/article.score.spec.ts src/stores/__tests__/batch.score.spec.ts src/views/__tests__/ArticleView.contract.spec.ts
  cd frontend; npx vue-tsc -b
  ```
  > `vue-tsc -b` 可能 emit `vite.config.js` → 跑完 `git checkout -- frontend/vite.config.js` 还原。

**已知预存失败（别排查）**：tests/core+tests/scripts 有文档化基线失败（export markdown / deepseek httpx / rate_limit `_sems` / test_cli+test_batch_runner / test_release_check flake）；sidecar/tests 有 9 个与 vault 无关的预存失败（ensure_browsers_path ×3、mining schema ×3、monitor_loop ×2、monitor_routes ×1）。以「无新增失败」为准。

---

## File Structure

**Unit A — csm_core 契约 + 完整性**
- Modify: `csm_core/config.py` — `ContractConfig` + `ScoringConfig` + `AppConfig.contract/.scoring`
- Modify: `csm_core/llm/prompts.py` — `PromptInputs.contract_mode` + 激进分支
- Create: `csm_core/factcheck/completeness.py`；Modify: `csm_core/factcheck/__init__.py`（若有导出表则补）
- Test: `tests/core/contract_scoring/__init__.py`、`test_contract_prompts.py`、`test_completeness.py`

**Unit B — csm_core/scoring 评分引擎**
- Create: `csm_core/scoring/__init__.py`、`model.py`、`ai_flavor.py`、`score.py`
- Test: `tests/core/contract_scoring/test_ai_flavor.py`、`test_score.py`

**Unit C — sidecar 接线**
- Modify: `sidecar/csm_sidecar/services/chain_service.py` — `ChainState.contract_mode` + `run_chain(contract_mode=, cache=)` 
- Modify: `sidecar/csm_sidecar/services/generate_service.py` — 请求字段 + finalize_draft 完整性 + done 载荷
- Modify: `sidecar/csm_sidecar/routes/generate.py` — GenerateBody/FinalizeBody + `contract_mode`
- Create: `sidecar/csm_sidecar/services/score_service.py`、`sidecar/csm_sidecar/routes/score.py`；Modify: `main.py` 注册
- Modify: `sidecar/csm_sidecar/services/batch_service.py` + `routes/batch.py` — 批量升级
- Test: `sidecar/tests/test_generate_contract.py`、`test_score_routes.py`、`test_batch_scoring.py`

**Unit D — 前端**
- Modify: `frontend/src/stores/article.ts` — `completeness`/`score` state + `runScore` + resets + done 接收 + `GenerateRequest.contract_mode`
- Create: `frontend/src/components/article/CompletenessPanel.vue`
- Modify: `frontend/src/views/ArticleView.vue` — 质检卡两项 + 面板接线 + query 契约透传
- Modify: `frontend/src/components/home/CreateArticleHero.vue` — 契约 chip（默认跟随全局）
- Create: `frontend/src/components/settings/ContractCard.vue`；Modify: SettingsView 注册
- Modify: `frontend/src/stores/batch.ts` + `frontend/src/views/BatchView.vue` — candidates + 评分列
- Test: `article.score.spec.ts`、`batch.score.spec.ts`、`ArticleView.contract.spec.ts`、`CompletenessPanel.spec.ts`

---

# Unit A — csm_core 契约 + 完整性

## Task A1: config 两个子模型 + PromptInputs.contract_mode + 激进分支

**Files:**
- Modify: `csm_core/config.py`
- Modify: `csm_core/llm/prompts.py`
- Create: `tests/core/contract_scoring/__init__.py`（空）、`tests/core/contract_scoring/test_contract_prompts.py`

- [ ] **Step 1: 失败测试** `tests/core/contract_scoring/test_contract_prompts.py`

```python
from csm_core.config import AppConfig, ContractConfig, ScoringConfig
from csm_core.llm.prompts import PromptInputs, build_prompt


def test_config_defaults():
    assert ContractConfig().mode == "conservative"
    sc = ScoringConfig()
    assert sc.enabled is True and sc.extra_ai_words == []
    cfg = AppConfig.model_validate({})
    assert cfg.contract.mode == "conservative"
    assert cfg.scoring.enabled is True


# —— 保守分支零回归：钉死当前字节（改动 prompts.py 后这些断言不许变）——
def test_conservative_default_unchanged():
    system, user = build_prompt(PromptInputs(
        user_skill_prompt="skill正文", keyword="吸尘器", draft="毛坯"))
    assert system == "skill正文"
    assert user == (
        "【关键词】吸尘器\n\n"
        "【毛坯文】\n毛坯\n\n"
        "请按**润色模式**重写：保留所有信息点和段落结构，只改进文字流畅度、"
        "衔接和风格一致性；不新增虚构事实，不删减关键信息。"
    )


def test_conservative_with_title_angle_unchanged():
    _, user = build_prompt(PromptInputs(
        user_skill_prompt=None, keyword="k", draft="d",
        title="T", angle_directive="【写作角度】x"))
    assert "请按上面【写作角度】组织成文：保留所有信息点，可调整侧重、顺序、详略与语调；" in user
    assert "围绕标题开篇点题、贯穿全文；" in user
    assert "不新增虚构事实，不改动任何数字、单位、认证，不删减关键信息点。" in user


def test_aggressive_with_angle():
    _, user = build_prompt(PromptInputs(
        user_skill_prompt=None, keyword="k", draft="d",
        angle_directive="【写作角度】x", contract_mode="aggressive"))
    assert "可取舍删减次要或重复的信息点、让篇幅更精炼" in user
    assert "主推型号的参数、认证与标题承诺的卖点必须完整保留" in user
    assert "不删减关键信息点" not in user


def test_aggressive_default_mode():
    _, user = build_prompt(PromptInputs(
        user_skill_prompt=None, keyword="k", draft="d",
        contract_mode="aggressive"))
    assert "请按**精炼模式**重写：可删减次要或重复内容、合并冗余段落" in user
    assert "所有型号参数、认证与核心卖点必须完整保留" in user


def test_facts_constraint_present_in_both_modes():
    for mode in ("conservative", "aggressive"):
        _, user = build_prompt(PromptInputs(
            user_skill_prompt=None, keyword="k", draft="d",
            brand_facts="## CEWEY DS18", contract_mode=mode))
        assert "严禁引入上面【品牌型号事实】之外的任何参数数字或认证名称。" in user
```

- [ ] **Step 2: 跑测试确认失败** — Expected: FAIL（`ImportError: ContractConfig` / unexpected kw `contract_mode`）

- [ ] **Step 3: 实现**

`csm_core/config.py` —— `BrandMemoryConfig` 之后加两个类：

```python
class ContractConfig(BaseModel):
    """settings.contract.* —— 成文契约档（默认保守 = 今天行为）。"""
    # conservative=保留所有信息点；aggressive=允许取舍删减（主推事实必须保留，
    # finalize 后有完整性反向核对软警告兜底）。
    mode: Literal["conservative", "aggressive"] = "conservative"


class ScoringConfig(BaseModel):
    """settings.scoring.* —— 成稿确定性评分（禁区+AI味+核对信号）。"""
    enabled: bool = True
    # 追加进 AI 味套话词表（extend 不替换）。
    extra_ai_words: list[str] = Field(default_factory=list)
```

`AppConfig` 内 `vault_incremental` 字段之后加：

```python
    contract: ContractConfig = Field(default_factory=ContractConfig)
    scoring: ScoringConfig = Field(default_factory=ScoringConfig)
```

`csm_core/llm/prompts.py` —— `PromptInputs` 加字段（`angle_directive` 之后）：

```python
    # Phase 4+: 成文契约档。"conservative"（默认）= 今天行为字节级不变；
    # "aggressive" = 允许取舍删减（主推事实必须保留，另有完整性核对兜底）。
    contract_mode: str = "conservative"
```

`build_prompt` 的 instruction 选择改为四分支（**保守两分支字符串逐字节保持原样**）：

```python
    aggressive = inputs.contract_mode == "aggressive"
    if title_block or angle_block:
        if aggressive:
            instruction = (
                "请按上面【写作角度】组织成文：可取舍删减次要或重复的信息点、"
                "让篇幅更精炼；但主推型号的参数、认证与标题承诺的卖点必须完整保留；"
                "不新增虚构事实，不改动任何数字、单位、认证。"
            )
        else:
            instruction = (
                "请按上面【写作角度】组织成文：保留所有信息点，可调整侧重、顺序、详略与语调；"
                + ("围绕标题开篇点题、贯穿全文；" if title_block else "")
                + "不新增虚构事实，不改动任何数字、单位、认证，不删减关键信息点。"
            )
    else:
        if aggressive:
            instruction = (
                "请按**精炼模式**重写：可删减次要或重复内容、合并冗余段落；"
                "但所有型号参数、认证与核心卖点必须完整保留；"
                "不新增虚构事实，不改动任何数字、单位、认证。"
            )
        else:
            instruction = (
                "请按**润色模式**重写：保留所有信息点和段落结构，只改进文字流畅度、"
                "衔接和风格一致性；不新增虚构事实，不删减关键信息。"
            )
```

> 注意：激进+标题时不再单独拼「围绕标题」句（激进措辞已含「标题承诺的卖点」），与测试断言一致。`build_refine_prompt` 不动。

- [ ] **Step 4: 跑测试确认通过** — Expected: 6 passed；另跑既有 `tests/ -k "prompt"` 确认零回归

- [ ] **Step 5: commit**

```bash
git add csm_core/config.py csm_core/llm/prompts.py tests/core/contract_scoring/
git commit -m "feat(contract): ContractConfig/ScoringConfig + build_prompt 激进分支（保守字节不动）"
```

---

## Task A2: factcheck/completeness.py 反向核对

**Files:**
- Create: `csm_core/factcheck/completeness.py`
- Create: `tests/core/contract_scoring/test_completeness.py`

- [ ] **Step 1: 失败测试** `test_completeness.py`

```python
from csm_core.brand_memory.model import BrandModelMemory, SpecValue
from csm_core.brand_memory.inject import ModelScope
from csm_core.factcheck.completeness import CompletenessReport, check_completeness


def _scope(role: str, numbers: dict[str, list[float]], certs: list[str] = []) -> ModelScope:
    specs = {
        k: SpecValue(field=k, raw="x", numbers=v, unit="", is_approx=False, is_placeholder=False)
        for k, v in numbers.items()
    }
    mem = BrandModelMemory(
        brand="CEWEY", model="DS18", category="吸尘器", role=role,
        specs=specs, certs=certs)
    return ModelScope(brand="CEWEY", model="CEWEYDS18", role=role, memory=mem)


MAIN = _scope("主推", {"吸力": [250.0], "转速": [120000.0]}, certs=["CCC"])
RIVAL = _scope("竞品", {"吸力": [230.0]})


def test_missing_number_detected():
    draft = "主推吸力 250AW，转速 12万转。竞品 230AW。"
    final = "主推转速 12万转。"        # 删了 250AW
    rep = check_completeness(draft, final, [MAIN, RIVAL])
    assert rep.checked is True
    assert [m.token for m in rep.missing] == ["250AW"]
    assert rep.missing[0].value == 250.0
    assert "250AW" in rep.missing[0].sentence


def test_wan_symmetry():
    draft = "转速 12万转。"
    final = "转速 120000转。"          # 万-展开等价，不算缺失
    rep = check_completeness(draft, final, [MAIN])
    assert rep.missing == []


def test_rival_deletion_not_missing():
    draft = "主推 250AW；竞品 230AW。"
    final = "主推 250AW。"             # 竞品被删——激进契约允许
    rep = check_completeness(draft, final, [MAIN, RIVAL])
    assert rep.missing == []


def test_cert_missing():
    draft = "已通过 CCC 认证，吸力 250AW。"
    final = "吸力 250AW。"
    rep = check_completeness(draft, final, [MAIN])
    assert [m.token for m in rep.missing] == ["CCC"]
    assert rep.missing[0].kind == "cert" and rep.missing[0].value is None


def test_no_primary_scope_unchecked():
    rep = check_completeness("250AW", "", [RIVAL])
    assert rep.checked is False and rep.missing == []


def test_draft_number_not_in_specs_ignored():
    draft = "赠品价值 99元，吸力 250AW。"   # 99元 非主推 spec
    final = "吸力 250AW。"
    rep = check_completeness(draft, final, [MAIN])
    assert rep.missing == []
```

- [ ] **Step 2: 跑测试确认失败** — Expected: FAIL（module 不存在）

- [ ] **Step 3: 实现** `csm_core/factcheck/completeness.py`

```python
"""完整性反向核对：激进契约删减后，主推型号关键事实必须仍在成稿。

方向与 checker 相反 —— checker 抓「成稿多了白名单外的数」，本模块抓
「初稿有、且属于主推型号 spec/认证 的事实，在成稿里消失」。竞品内容
被删不算缺失（激进契约允许取舍竞品）。万-展开与 extract 对称。
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .extract import extract_certs, extract_number_mentions, split_sentences


class MissingFact(BaseModel):
    kind: Literal["number", "cert"]
    token: str               # 初稿原文 token，如 "250AW" / "CCC"
    value: float | None      # 归一值（万展开），cert=None
    sentence: str            # 初稿所在句（定位）


class CompletenessReport(BaseModel):
    checked: bool            # False = 无主推 scope，未核
    missing: list[MissingFact] = Field(default_factory=list)


def _sentence_of(draft: str, token: str) -> str:
    for s in split_sentences(draft):
        if token in s:
            return s
    return ""


def check_completeness(draft: str, final_text: str, scopes: list) -> CompletenessReport:
    primary = [s for s in scopes if getattr(s, "role", "") == "主推"]
    if not primary:
        return CompletenessReport(checked=False)

    spec_numbers: set[float] = set()
    cert_vocab: set[str] = set()
    for scope in primary:
        for sv in scope.memory.specs.values():
            spec_numbers.update(sv.numbers)
        cert_vocab.update(scope.memory.certs)

    final_numbers = {v for v, _tok in extract_number_mentions(final_text)}
    final_certs = set(extract_certs(final_text))

    missing: list[MissingFact] = []
    seen_values: set[float] = set()
    for value, token in extract_number_mentions(draft):
        if value not in spec_numbers or value in seen_values:
            continue
        seen_values.add(value)
        if value not in final_numbers:
            missing.append(MissingFact(
                kind="number", token=token, value=value,
                sentence=_sentence_of(draft, token)))
    for cert in extract_certs(draft):
        if cert in cert_vocab and cert not in final_certs:
            missing.append(MissingFact(
                kind="cert", token=cert, value=None,
                sentence=_sentence_of(draft, cert)))
    return CompletenessReport(checked=True, missing=missing)
```

> `scopes` 参数不打强类型（`list`）——与 `_maybe_block_for_factcheck` 同风格，避免 factcheck→brand_memory 循环导入（duck-typing `role`/`memory.specs`/`memory.certs`）。

- [ ] **Step 4: 跑测试确认通过** — Expected: 6 passed

- [ ] **Step 5: commit**

```bash
git add csm_core/factcheck/completeness.py tests/core/contract_scoring/test_completeness.py
git commit -m "feat(factcheck): check_completeness 主推事实反向核对（万对称/竞品删除豁免）"
```

---

# Unit B — csm_core/scoring 评分引擎

## Task B1: model + ai_flavor 信号

**Files:**
- Create: `csm_core/scoring/__init__.py`、`csm_core/scoring/model.py`、`csm_core/scoring/ai_flavor.py`
- Create: `tests/core/contract_scoring/test_ai_flavor.py`

- [ ] **Step 1: 失败测试** `test_ai_flavor.py`

```python
from csm_core.scoring.ai_flavor import ai_flavor_parts

HUMAN = (
    "上周把家里那台老吸尘器换掉了。原因说来好笑：猫毛缠进滚刷，拆了半小时。\n\n"
    "新机器用了十天，地毯上的猫毛一遍过。楼下邻居问我是不是换了保洁阿姨。\n\n"
    "要说缺点也有，尘杯小了点，倒得勤。但对我这种懒人，能少拆一次刷头就是胜利。"
)

AI_HEAVY = (
    "首先，吸力是选购吸尘器的核心指标。其次，续航能力同样值得关注。最后，噪音水平不容忽视。\n\n"
    "总的来说，这款产品表现出色。值得一提的是，它不是简单的清洁工具，而是智能家居的入口。"
    "不仅性能强劲，更在细节处体现匠心。众所周知，除螨需要强吸力。\n\n"
    "总之，综合来看这是一款值得推荐的产品。"
)


def _points(parts, key):
    return next((p.points for p in parts if p.key == key), 0.0)


def test_clean_human_text_low_deduction():
    parts = ai_flavor_parts(HUMAN)
    assert sum(p.points for p in parts) <= 6.0


def test_ai_heavy_text_flags_signals():
    parts = ai_flavor_parts(AI_HEAVY)
    assert _points(parts, "ai_triplet") >= 8.0          # 首先…其次…最后
    assert _points(parts, "ai_connectives") > 0
    assert _points(parts, "ai_parallel") > 0            # 不是…而是 / 不仅…更
    assert _points(parts, "ai_summary") >= 4.0          # 段首「总之」


def test_triplet_capped():
    text = ("首先A。其次B。最后C。" * 5)
    assert _points(ai_flavor_parts(text), "ai_triplet") <= 16.0


def test_connectives_capped():
    text = "首先，" * 200 + "结束。"
    assert _points(ai_flavor_parts(text), "ai_connectives") <= 15.0


def test_extra_words_extend():
    base = ai_flavor_parts("这款产品赋能千家万户。")
    extended = ai_flavor_parts("这款产品赋能千家万户。", extra_words=["赋能"])
    assert _points(extended, "ai_connectives") > _points(base, "ai_connectives")


def test_monotony_uniform_sentences():
    text = "。".join("这是一句长度基本一样的句子啊" for _ in range(12)) + "。"
    assert _points(ai_flavor_parts(text), "monotony") > 0


def test_empty_text_no_parts():
    assert ai_flavor_parts("") == []
```

- [ ] **Step 2: 跑测试确认失败** — Expected: FAIL（module 不存在）

- [ ] **Step 3: 实现**

`csm_core/scoring/model.py`：

```python
"""评分结果模型。"""
from __future__ import annotations

from pydantic import BaseModel, Field


class ScorePart(BaseModel):
    key: str
    label: str
    points: float            # 扣分（正数）；total = 100 - Σpoints
    detail: str


class ScoreReport(BaseModel):
    total: float             # 0-100
    parts: list[ScorePart] = Field(default_factory=list)
```

`csm_core/scoring/ai_flavor.py`：

```python
"""AI 味启发式（全确定性正则/词表，零 LLM）。每信号一个 ScorePart（有扣分才产出）。

阈值/权重是启发式（v1 手调）：干净人稿总扣 ≲6，重度 AI 稿各信号普遍命中。
"""
from __future__ import annotations

import re
import statistics

from .model import ScorePart

AI_CONNECTIVES: tuple[str, ...] = (
    "首先", "其次", "再者", "再次", "接着", "总的来说", "综上所述", "总而言之",
    "值得一提的是", "值得注意的是", "不难发现", "不难看出", "众所周知",
    "显而易见", "与此同时", "除此之外", "一方面", "另一方面", "综合来看", "整体而言",
)
_TRIPLET_RE = re.compile(r"首先[\s\S]{0,200}?其次[\s\S]{0,200}?最后")
_PARALLEL_RES = (
    re.compile(r"不是[^。！？\n]{1,30}而是"),
    re.compile(r"不仅[^。！？\n]{1,30}更"),
)
_SUMMARY_STARTS = ("总之", "综上", "总的来说", "综合来看")
_SENT_SPLIT = re.compile(r"[。！？!?\n]+")


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENT_SPLIT.split(text) if s.strip()]


def _paragraphs(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]


def ai_flavor_parts(text: str, *, extra_words: list[str] | None = None) -> list[ScorePart]:
    text = (text or "").strip()
    if not text:
        return []
    parts: list[ScorePart] = []
    kchars = max(1.0, len(text) / 1000.0)

    # 1) 套话连接词密度：每千字加权 ×3，上限 15
    vocab = tuple(AI_CONNECTIVES) + tuple(extra_words or [])
    n_conn = sum(text.count(w) for w in vocab)
    if n_conn:
        pts = min(15.0, round(n_conn / kchars * 3.0, 1))
        parts.append(ScorePart(
            key="ai_connectives", label="套话连接词",
            points=pts, detail=f"命中 {n_conn} 处（首先/综上所述 等）"))

    # 2) 三段式：8 分/次，上限 16
    n_tri = len(_TRIPLET_RE.findall(text))
    if n_tri:
        parts.append(ScorePart(
            key="ai_triplet", label="三段式模板",
            points=min(16.0, n_tri * 8.0), detail=f"「首先…其次…最后」×{n_tri}"))

    # 3) 否定排比：2.5 分/处，上限 10
    n_par = sum(len(r.findall(text)) for r in _PARALLEL_RES)
    if n_par:
        parts.append(ScorePart(
            key="ai_parallel", label="否定排比",
            points=min(10.0, round(n_par * 2.5, 1)), detail=f"「不是…而是/不仅…更」×{n_par}"))

    # 4) 万能总结段：4 分/段，上限 12
    n_sum = sum(1 for p in _paragraphs(text) if p.startswith(_SUMMARY_STARTS))
    if n_sum:
        parts.append(ScorePart(
            key="ai_summary", label="万能总结句",
            points=min(12.0, n_sum * 4.0), detail=f"段首「总之/综上」×{n_sum}"))

    # 5) 同质化：句长变异系数过低（≥8 句才判），上限 12
    sents = _sentences(text)
    mono = 0.0
    detail_bits: list[str] = []
    if len(sents) >= 8:
        lens = [len(s) for s in sents]
        cv = statistics.pstdev(lens) / max(1.0, statistics.mean(lens))
        if cv < 0.35:
            mono += min(8.0, round((0.35 - cv) * 40.0, 1))
            detail_bits.append(f"句长 CV={cv:.2f}")
    paras = _paragraphs(text)
    if len(paras) >= 4:
        plens = [len(p) for p in paras]
        pcv = statistics.pstdev(plens) / max(1.0, statistics.mean(plens))
        if pcv < 0.3:
            mono += min(4.0, round((0.3 - pcv) * 40.0, 1))
            detail_bits.append(f"段长 CV={pcv:.2f}")
    if mono:
        parts.append(ScorePart(
            key="monotony", label="句段同质化",
            points=min(12.0, round(mono, 1)), detail="、".join(detail_bits)))

    return parts
```

`csm_core/scoring/__init__.py`（B2 完成后补 score 导出，本 Task 先）：

```python
"""成稿确定性评分：禁区 lint + AI 味启发式 + 核对信号 → 0-100。"""
from .model import ScorePart, ScoreReport
from .ai_flavor import AI_CONNECTIVES, ai_flavor_parts

__all__ = ["ScorePart", "ScoreReport", "AI_CONNECTIVES", "ai_flavor_parts"]
```

- [ ] **Step 4: 跑测试确认通过** — Expected: 7 passed

- [ ] **Step 5: commit**

```bash
git add csm_core/scoring/ tests/core/contract_scoring/test_ai_flavor.py
git commit -m "feat(scoring): AI 味启发式信号（连接词/三段式/排比/总结段/同质化）"
```

---

## Task B2: score.score_article

**Files:**
- Create: `csm_core/scoring/score.py`；Modify: `csm_core/scoring/__init__.py`
- Create: `tests/core/contract_scoring/test_score.py`

- [ ] **Step 1: 失败测试** `test_score.py`

```python
from csm_core.config import ScoringConfig
from csm_core.lint.model import LintHit, LintReport
from csm_core.scoring import score_article


def _hit(cat: str, fixable: bool) -> LintHit:
    return LintHit(category=cat, text="x", start=0, end=1,
                   sentence="s", fixable=fixable, suggestion="")


CLEAN = (
    "上周把家里那台老吸尘器换掉了。原因说来好笑：猫毛缠进滚刷，拆了半小时。\n\n"
    "新机器用了十天，地毯上的猫毛一遍过。楼下邻居问我是不是换了保洁阿姨。\n\n"
    "要说缺点也有，尘杯小了点，倒得勤。但对我这种懒人，能少拆一次刷头就是胜利。"
)


def test_clean_text_high_score():
    rep = score_article(CLEAN, lint_report=LintReport(hits=[], fixed_text=CLEAN))
    assert rep.total >= 80.0
    assert all(p.points >= 0 for p in rep.parts)


def test_lint_weights_and_cap():
    judgment = [_hit("absolute", False)] * 3       # 3×4=12
    mech = [_hit("emoji", True)] * 2               # 2×2=4
    rep = score_article("x", lint_report=LintReport(hits=judgment + mech, fixed_text="x"))
    lint_part = next(p for p in rep.parts if p.key == "lint")
    assert lint_part.points == 16.0
    many = [_hit("traffic", False)] * 20           # 80 → cap 30
    rep2 = score_article("x", lint_report=LintReport(hits=many, fixed_text="x"))
    assert next(p for p in rep2.parts if p.key == "lint").points == 30.0


def test_factcheck_completeness_deduction():
    rep = score_article("x", lint_report=LintReport(hits=[], fixed_text="x"),
                        factcheck_violations=2, completeness_missing=1)
    assert next(p for p in rep.parts if p.key == "factcheck").points == 12.0
    assert next(p for p in rep.parts if p.key == "completeness").points == 4.0
    caps = score_article("x", lint_report=LintReport(hits=[], fixed_text="x"),
                         factcheck_violations=10, completeness_missing=10)
    assert next(p for p in caps.parts if p.key == "factcheck").points == 18.0
    assert next(p for p in caps.parts if p.key == "completeness").points == 12.0


def test_total_floor_zero():
    hits = [_hit("absolute", False)] * 30
    rep = score_article("首先，" * 300, lint_report=LintReport(hits=hits, fixed_text="x"),
                        factcheck_violations=10, completeness_missing=10)
    assert rep.total >= 0.0


def test_extra_ai_words_via_config():
    cfg = ScoringConfig(extra_ai_words=["赋能"])
    base = score_article("产品赋能生活。", lint_report=LintReport(hits=[], fixed_text="x"))
    ext = score_article("产品赋能生活。", lint_report=LintReport(hits=[], fixed_text="x"), config=cfg)
    assert ext.total <= base.total
```

- [ ] **Step 2: 跑测试确认失败** — Expected: FAIL（`ImportError: score_article`）

- [ ] **Step 3: 实现** `csm_core/scoring/score.py`

```python
"""score_article：组合 lint/AI味/核对信号 → ScoreReport（0-100，确定性）。"""
from __future__ import annotations

from csm_core.config import ScoringConfig
from csm_core.lint.model import LintReport

from .ai_flavor import ai_flavor_parts
from .model import ScorePart, ScoreReport

_JUDGMENT_CATS = {"meta_speak", "absolute", "traffic"}   # 4 分/处
_MECH_POINTS = 2.0                                        # emoji/dash/quote
_JUDGMENT_POINTS = 4.0
_LINT_CAP = 30.0
_FACTCHECK_POINTS, _FACTCHECK_CAP = 6.0, 18.0
_COMPLETENESS_POINTS, _COMPLETENESS_CAP = 4.0, 12.0


def score_article(
    text: str, *,
    lint_report: LintReport,
    factcheck_violations: int = 0,
    completeness_missing: int = 0,
    config: ScoringConfig | None = None,
) -> ScoreReport:
    cfg = config or ScoringConfig()
    parts: list[ScorePart] = []

    n_judge = sum(1 for h in lint_report.hits if h.category in _JUDGMENT_CATS)
    n_mech = len(lint_report.hits) - n_judge
    lint_pts = min(_LINT_CAP, n_judge * _JUDGMENT_POINTS + n_mech * _MECH_POINTS)
    if lint_pts:
        parts.append(ScorePart(
            key="lint", label="禁区命中", points=lint_pts,
            detail=f"判断类 {n_judge} 处、机械类 {n_mech} 处"))

    parts.extend(ai_flavor_parts(text, extra_words=cfg.extra_ai_words))

    if factcheck_violations:
        parts.append(ScorePart(
            key="factcheck", label="事实核对违规",
            points=min(_FACTCHECK_CAP, factcheck_violations * _FACTCHECK_POINTS),
            detail=f"越界 {factcheck_violations} 处"))
    if completeness_missing:
        parts.append(ScorePart(
            key="completeness", label="完整性缺失",
            points=min(_COMPLETENESS_CAP, completeness_missing * _COMPLETENESS_POINTS),
            detail=f"缺失 {completeness_missing} 处"))

    total = max(0.0, round(100.0 - sum(p.points for p in parts), 1))
    return ScoreReport(total=total, parts=sorted(parts, key=lambda p: -p.points))
```

`__init__.py` 导出补 `score_article`（`from .score import score_article`；`__all__` 加）。

- [ ] **Step 4: 跑测试确认通过** — Expected: 5 passed；`tests/core/contract_scoring/` 全绿

- [ ] **Step 5: commit**

```bash
git add csm_core/scoring/ tests/core/contract_scoring/test_score.py
git commit -m "feat(scoring): score_article 组合评分（lint/AI味/核对，0-100 确定性）"
```

---

# Unit C — sidecar 接线

## Task C1: chain 契约穿透 + finalize 完整性 + 请求字段

**Files:**
- Modify: `sidecar/csm_sidecar/services/chain_service.py`
- Modify: `sidecar/csm_sidecar/services/generate_service.py`
- Modify: `sidecar/csm_sidecar/routes/generate.py`
- Create: `sidecar/tests/test_generate_contract.py`

**chain_service.py 改动（3 处）：**

(a) `ChainState` 加字段（`brand_facts` 之后）：

```python
    contract_mode: str = "conservative"   # rerun 复用缓存值，保持同契约重跑
```

(b) `_prompt_for` 的 step0 分支 `PromptInputs(...)` 加 `contract_mode=state.contract_mode,`。

(c) `run_chain` 签名加两个 kwargs（`model` 之后）：`contract_mode: str = "conservative", cache: bool = True,`；`ChainState(...)` 构造加 `contract_mode=contract_mode,`；尾部 `_cache_put(state)` 改为 `if cache: _cache_put(state)`（批量链不进 LRU，防挤掉交互链的 rerun 缓存）。

**generate_service.py 改动：**

(a) `GenerateRequest` 与 `FinalizeRequest` 各加：

```python
    # Phase 4+: 成文契约档单次覆盖。None = 用全局 cfg.contract.mode。
    contract_mode: str | None = None
```

(b) `FinalizeOutcome` 加字段：`completeness: dict[str, Any] | None = None`。

(c) `finalize_draft` 签名加 `contract_mode: str,`（`model` 参数之后）；`run_chain(...)` 调用加 `contract_mode=contract_mode,`；链跑完、算完 cost 后加完整性核对：

```python
    # Phase 4+: 激进契约的完整性反向核对（软警告，不拦）。
    completeness: dict[str, Any] | None = None
    if contract_mode == "aggressive":
        comp = check_completeness(draft, final_text, scopes)
        completeness = comp.model_dump()
```

（import 区加 `from csm_core.factcheck.completeness import check_completeness`。）

`_maybe_block_for_factcheck(...)` 调用与签名各加 `completeness=completeness` 参数，其内部 `bus.finish(..., factcheck=...)` 同时带 `completeness=completeness`；`finalize_draft` 两个 `return FinalizeOutcome(...)` 都加 `completeness=completeness`。

(d) `_run_job` 与 `_finalize_job` 里调 `finalize_draft(...)` 处各加 `contract_mode=(req.contract_mode or cfg.contract.mode),`；两处最终 `bus.finish(...)`（非 blocked 路径）各加 `completeness=outcome.completeness,`。

**routes/generate.py**：`GenerateBody` 与 `FinalizeBody` 各加：

```python
    # Phase 4+：成文契约档单次覆盖（None=用全局设置）。
    contract_mode: Literal["conservative", "aggressive"] | None = None
```

（import 区 `from typing import Literal` 若无则加。`model_dump` 透传路径已覆盖新字段，无需改 submit 代码。）

- [ ] **Step 1: 失败测试** `sidecar/tests/test_generate_contract.py`

```python
from typing import Any

import pytest

from csm_core.config import AppConfig, BrandMemoryConfig, ContractConfig
from csm_sidecar.services import chain_service, generate_service


class _FakeClient:
    def __init__(self, out: str):
        self.out = out
        self.prompts: list[tuple[str, str]] = []

    def complete(self, *, system: str, user: str, temperature=None) -> str:
        self.prompts.append((system, user))
        return self.out


@pytest.fixture(autouse=True)
def _chain_reset():
    chain_service.reset_for_test()
    yield
    chain_service.reset_for_test()


def test_run_chain_threads_contract_mode():
    client = _FakeClient("out")
    chain_service.run_chain(
        "j1", [], draft="d", keyword="k", title=None, angle_directive=None,
        brand_facts=None, provider=None, model=None, client=client,
        contract_mode="aggressive")
    assert "精炼模式" in client.prompts[0][1]
    st = chain_service.get_state("j1")
    assert st is not None and st.contract_mode == "aggressive"


def test_run_chain_default_conservative_and_cached():
    client = _FakeClient("out")
    chain_service.run_chain(
        "j2", [], draft="d", keyword="k", title=None, angle_directive=None,
        brand_facts=None, provider=None, model=None, client=client)
    assert "润色模式" in client.prompts[0][1]


def test_run_chain_cache_false_not_cached():
    client = _FakeClient("out")
    chain_service.run_chain(
        "j3", [], draft="d", keyword="k", title=None, angle_directive=None,
        brand_facts=None, provider=None, model=None, client=client, cache=False)
    assert chain_service.get_state("j3") is None


def test_rerun_reuses_contract_mode():
    client = _FakeClient("out")
    chain_service.run_chain(
        "j4", [], draft="d", keyword="k", title=None, angle_directive=None,
        brand_facts=None, provider=None, model=None, client=client,
        contract_mode="aggressive")
    client2 = _FakeClient("out2")
    chain_service.rerun("j4", 0, client=client2)
    assert "精炼模式" in client2.prompts[0][1]
```

（`finalize_draft` 的完整性接线用既有 `test_finalize_draft.py` 的构造方式追加用例——该文件已有 fake plan/index/registry/cfg 装置；追加两测：`contract_mode="aggressive"` 且 mock 链输出删参数 → outcome.completeness["missing"] 非空；`"conservative"` → outcome.completeness is None。**先读该文件再照它的 fixture 写**，两测放它文件尾。）

- [ ] **Step 2: 跑测试确认失败** — Expected: FAIL（unexpected kw `contract_mode`/`cache`）

- [ ] **Step 3: 实现**（按上方改动清单逐处落）

- [ ] **Step 4: 跑测试** — 新测试全绿 + `test_chain_service.py`/`test_chain_rerun.py`/`test_finalize_draft.py`/`test_finalize_job.py`/`test_generate_chain.py` 零回归

- [ ] **Step 5: commit**

```bash
git add sidecar/csm_sidecar/services/chain_service.py sidecar/csm_sidecar/services/generate_service.py sidecar/csm_sidecar/routes/generate.py sidecar/tests/test_generate_contract.py sidecar/tests/test_finalize_draft.py
git commit -m "feat(contract): 契约档穿透链/finalize + 完整性软警告挂 done + cache 开关"
```

---

## Task C2: score_service + POST /api/score

**Files:**
- Create: `sidecar/csm_sidecar/services/score_service.py`、`sidecar/csm_sidecar/routes/score.py`
- Modify: `sidecar/csm_sidecar/main.py`（照 lint_routes 两行注册）
- Create: `sidecar/tests/test_score_routes.py`

- [ ] **Step 1: 失败测试** `test_score_routes.py`

```python
import pytest

from csm_core.config import AppConfig, ScoringConfig
from csm_sidecar.services import score_service


@pytest.fixture(autouse=True)
def _cfg(monkeypatch):
    monkeypatch.setattr(
        score_service.config_service, "load", lambda: AppConfig())


def test_score_ok(client):
    r = client.post("/api/score", json={"text": "上周换了台吸尘器，好用。"})
    assert r.status_code == 200
    body = r.json()
    assert 0 <= body["total"] <= 100 and isinstance(body["parts"], list)


def test_score_with_signals(client):
    r = client.post("/api/score", json={
        "text": "首先好。其次妙。最后强。", "factcheck_violations": 1,
        "completeness_missing": 2})
    body = r.json()
    keys = {p["key"] for p in body["parts"]}
    assert {"factcheck", "completeness"} <= keys


def test_score_disabled(client, monkeypatch):
    monkeypatch.setattr(
        score_service.config_service, "load",
        lambda: AppConfig(scoring=ScoringConfig(enabled=False)))
    r = client.post("/api/score", json={"text": "x"})
    assert r.status_code == 200
    assert r.json() == {"total": None, "parts": []}


def test_score_missing_text_422(client):
    assert client.post("/api/score", json={}).status_code == 422
```

- [ ] **Step 2: 跑测试确认失败** — Expected: FAIL（404）

- [ ] **Step 3: 实现**

`score_service.py`：

```python
"""成稿评分服务：读 config → lint 扫描 + score_article → dict。纯计算不写盘。"""
from __future__ import annotations

from typing import Any

from csm_core.lint import build_report, build_rules
from csm_core.scoring import score_article

from . import config_service


def score_text(
    text: str, *, factcheck_violations: int = 0, completeness_missing: int = 0,
) -> dict[str, Any]:
    cfg = config_service.load()
    if not cfg.scoring.enabled:
        return {"total": None, "parts": []}
    lint_report = build_report(text or "", build_rules(cfg.lint))
    return score_article(
        text or "", lint_report=lint_report,
        factcheck_violations=factcheck_violations,
        completeness_missing=completeness_missing,
        config=cfg.scoring,
    ).model_dump()
```

`routes/score.py`（镜像 lint 路由）：

```python
"""POST /api/score —— 无状态成稿评分。text→ScoreReport（scoring 关→total null）。"""
from __future__ import annotations
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..auth import RequireToken
from ..services import score_service

router = APIRouter(tags=["score"], dependencies=[RequireToken])


class ScoreBody(BaseModel):
    text: str
    factcheck_violations: int = Field(default=0, ge=0)
    completeness_missing: int = Field(default=0, ge=0)


@router.post("/api/score")
def score(body: ScoreBody) -> dict[str, Any]:
    return score_service.score_text(
        body.text, factcheck_violations=body.factcheck_violations,
        completeness_missing=body.completeness_missing)
```

`main.py`：`from .routes import score as score_routes` + `app.include_router(score_routes.router)`（紧跟 lint_routes）。

- [ ] **Step 4: 跑测试确认通过** — Expected: 4 passed

- [ ] **Step 5: commit**

```bash
git add sidecar/csm_sidecar/services/score_service.py sidecar/csm_sidecar/routes/score.py sidecar/csm_sidecar/main.py sidecar/tests/test_score_routes.py
git commit -m "feat(scoring): POST /api/score 无状态评分端点"
```

---

## Task C3: 批量链路升级（注入/链/核对/评分/多候选）

**Files:**
- Modify: `sidecar/csm_sidecar/services/batch_service.py`
- Modify: `sidecar/csm_sidecar/routes/batch.py`
- Create: `sidecar/tests/test_batch_scoring.py`

**batch_service.py 改动总览：**

(a) import 区：删 `from csm_core.llm.prompts import PromptInputs, build_prompt`；加

```python
from csm_core.brand_memory.inject import build_whitelist, render_brand_facts, resolve_scopes
from csm_core.factcheck import check_facts
from csm_core.factcheck.completeness import check_completeness
from csm_core.lint import build_report as lint_report_for
from csm_core.lint import build_rules
from csm_core.llm import pricing
from csm_core.scoring import score_article
```

并在 `from . import ...` 行加 `chain_service,`（字母序）。`generate_service._effective_model` 不导入——批量本地内联同逻辑（见 (e)）。

(b) `BatchItemState` 加字段：

```python
    score: float | None = None
    score_parts: list[dict] = field(default_factory=list)      # top3 扣分明细
    candidate_scores: list[float] = field(default_factory=list)
    factcheck_violations: int = 0
```

（`to_dict` 走 `vars(it)`，list/dict 自动带出，无需改。）

(c) `BatchState` 加 `skill_chain: list[str] | None = None`、`candidates: int = 1`、`contract_mode: str | None = None`（`to_dict` 同步加这三键）；`BatchRequest` 加同名三字段（默认同）。`submit()` 构造 `BatchState(...)` 时透传，并钳位 `candidates=max(1, min(3, req.candidates))`。

(d) `_run_job` 的 per-keyword 生成体（try 块内 `plan = assemble_plan(...)` 到 `item.status = "success"`）整体替换为：

```python
                best: dict | None = None       # {final_text, plan, score_report, fc_n}
                cand_scores: list[float] = []
                total_cost_acc = state_cost_acc   # 见 (e)：外层累计器
                for k in range(1, state.candidates + 1):
                    with _lock:
                        if state.cancel_requested:
                            break
                    plan = assemble_plan(
                        keyword=item.keyword, template=template,
                        index=index, registry=registry,
                        seed=state.seed + (k - 1) * 1000, user_config={},
                    )
                    draft = compose_draft(plan)
                    # 注入（与 finalize_draft 同条件：inject 或 factcheck 开才解析 scopes）
                    scopes: list = []
                    brand_facts = None
                    if cfg.brand_memory.inject or cfg.brand_memory.factcheck:
                        scopes = resolve_scopes(
                            plan, index, registry,
                            own_brands=set(cfg.brand_memory.own_brands),
                            category=template.product)
                        if scopes and cfg.brand_memory.inject:
                            brand_facts = render_brand_facts(
                                scopes,
                                variant_cap=cfg.brand_memory.inject_variant_cap,
                                endorsement_cap=cfg.brand_memory.inject_endorsement_cap)
                    chain_state = chain_service.run_chain(
                        f"{job_id}:{item.index}:{k}", chain_steps,
                        draft=draft, keyword=item.keyword, title=None,
                        angle_directive=None, brand_facts=brand_facts,
                        provider=state.provider, model=state.model,
                        client=client, contract_mode=effective_contract,
                        cache=False)
                    final_k = chain_state.final_text
                    pass_dicts = [p.to_dict() for p in chain_state.passes]
                    total_cost_acc.append(pass_dicts)
                    # 核对信号（计数不拦）
                    fc_n = 0
                    if cfg.brand_memory.factcheck and scopes:
                        sources = [draft] + ([brand_facts] if brand_facts else [])
                        wl = build_whitelist(scopes, source_texts=sources)
                        fc_n = len(check_facts(
                            final_k, allowed_numbers=wl.numbers,
                            allowed_certs=wl.certs).violations)
                    comp_n = 0
                    if effective_contract == "aggressive" and scopes:
                        comp_n = len(check_completeness(draft, final_k, scopes).missing)
                    report = score_article(
                        final_k, lint_report=lint_report_for(final_k, lint_rules),
                        factcheck_violations=fc_n, completeness_missing=comp_n,
                        config=cfg.scoring)
                    cand_scores.append(report.total)
                    if best is None or report.total > best["score_report"].total:
                        if best is not None:
                            _save_candidate(out_dir, item, best)   # 旧优胜者降级为落选稿
                        best = {"final_text": final_k, "plan": plan,
                                "score_report": report, "fc_n": fc_n}
                    else:
                        _save_candidate(out_dir, item, {
                            "final_text": final_k, "score_report": report})
                if best is None:
                    raise RuntimeError("batch item cancelled before first candidate")
                paths = export_article(
                    out_dir=out_dir, keyword=item.keyword,
                    final_text=best["final_text"], plan=best["plan"],
                    fmt=cfg.export_format)
                item.document = paths["document"]
                item.score = best["score_report"].total
                item.score_parts = [p.model_dump() for p in best["score_report"].parts[:3]]
                item.candidate_scores = cand_scores
                item.factcheck_violations = best["fc_n"]
                item.status = "success"
```

`_save_candidate` 新增模块级函数：

```python
import re as _re  # 文件顶部 import 区已有 re 则复用，无需别名


def _safe_stem(s: str) -> str:
    """Windows 安全文件名片段：非法字符与空白 → _，截 20 字。"""
    return _re.sub(r'[\\/:*?"<>|\s]+', "_", s)[:20] or "kw"


def _save_candidate(out_dir: Path, item: BatchItemState, cand: dict) -> None:
    """落选稿存 candidates/ 备查（纯 md dump，不走 export_article 的 MMDD-N 槽位）。"""
    cdir = out_dir / "candidates"
    cdir.mkdir(exist_ok=True)
    score = cand["score_report"].total
    path = cdir / f"{item.index:02d}-{_safe_stem(item.keyword)}-{score:.0f}分.md"
    try:
        path.write_text(cand["final_text"], encoding="utf-8")
    except OSError:
        logger.warning("batch 落选稿写入失败: %s", path, exc_info=True)
```

(e) `_run_job` 循环前的一次性准备区（`client = ...` 之后）加：

```python
        # 链 steps：skill_chain 优先；None 退化 [skill_id]（找不到已在上面 fail-fast）；
        # 两者皆空且模板有默认 skill → 单步默认链（沿用今天回退语义）。
        chain_steps: list[chain_service.ChainStepInput] = []
        if state.skill_chain:
            sdir = Path(cfg.skill_dir) if cfg.skill_dir else None
            for sid in state.skill_chain:
                sk = skills_service.get_skill(sdir, sid)
                if sk is None:
                    logger.warning("batch skill_chain: 跳过失效 skill %s", sid)
                    continue
                chain_steps.append(chain_service.ChainStepInput(
                    skill_id=sid, role=sk.role, name=sk.name, body=sk.body))
        elif skill_prompt is not None:
            chain_steps = [chain_service.ChainStepInput(
                skill_id=state.skill_id, role="persona", name="", body=skill_prompt)]
        effective_contract = state.contract_mode or cfg.contract.mode
        lint_rules = build_rules(cfg.lint)
        state_cost_acc: list[list[dict]] = []    # 每链的 pass_dicts，done 时求 total_cost
```

> 原 `skill_prompt` 解析块（含模板默认 skill 回退）**保留不动**——`chain_steps` 用它组装单步链；`run_chain` 空 steps 也能跑（等价单步无 skill），与今天 `build_prompt(user_skill_prompt=None)` 一致。

(f) done 汇总：`_summary(state)` 返回 dict 后、`bus.finish(job_id, **summary)` 前加 total_cost：

```python
        model_name = state.model or (
            cfg.default_model.get(state.provider or cfg.default_provider or "")
            if (state.provider or cfg.default_provider) else None)
        agg = {"input_tokens": 0, "output_tokens": 0, "cost": 0.0, "currency": "CNY"}
        any_cost = False
        for pass_dicts in state_cost_acc:
            c = pricing.chain_cost(pass_dicts, model_name, cfg.pricing)
            agg["input_tokens"] += c["input_tokens"]
            agg["output_tokens"] += c["output_tokens"]
            if c["cost"] is not None:
                agg["cost"] += c["cost"]; any_cost = True
        if not any_cost:
            agg["cost"] = None
        summary["total_cost"] = agg
```

(g) `item_finished` 事件 payload 加：`score=item.score, score_parts=item.score_parts, candidate_scores=item.candidate_scores, factcheck_violations=item.factcheck_violations,`。

(h) 候选间取消：见 (d) 内层 `with _lock: if state.cancel_requested: break`；外层循环原有检查保留。

**routes/batch.py**：`BatchBody` 加：

```python
    skill_chain: list[str] | None = None
    candidates: int = Field(default=1, ge=1, le=3)
    contract_mode: Literal["conservative", "aggressive"] | None = None
```

（import `Literal`；docstring 的 item_finished 说明加 score 字段一句。）

- [ ] **Step 1: 失败测试** `sidecar/tests/test_batch_scoring.py`

先读 `sidecar/tests/test_batch_routes.py` 的既有装置（tmp vault/template/mock LLM 的搭法），复用它的 helper 组新文件；覆盖：

```python
# 断言清单（照 test_batch_routes 装置风格实现）：
# 1) candidates=2：mock client.complete 被调 2×N 次；item_finished 带
#    score/candidate_scores(len==2)/score_parts(<=3)；导出 = 高分候选
#    （两次 mock 返回不同 AI 味浓度文本，断言 document 内容是高分那篇）；
#    落选稿存在 out_dir/candidates/ 且文件名含分数。
# 2) candidates=1（默认）零回归：client.complete 恰 N 次；item_finished
#    仍带 score（免费评分）；不建 candidates/ 目录。
# 3) inject 开（monkeypatch cfg.brand_memory.inject=True + 合成 vault 带
#    型号笔记）：mock client 收到的 user prompt 含「品牌型号事实」。
# 4) factcheck 开且成稿带越界数字：item 不 failed、factcheck_violations>0、
#    score 因此更低；绝不出现 blocked 状态。
# 5) done 事件带 total_cost{input_tokens,output_tokens,...}。
# 6) skill_chain=[两个合成 skill]：complete 每候选被调 2 次（两 pass）。
```

- [ ] **Step 2: 跑测试确认失败**
- [ ] **Step 3: 实现**（按 (a)-(h) 落）
- [ ] **Step 4: 跑测试** — 新文件全绿 + `test_batch_routes.py` 全绿（旧事件字段/导出路径 shape 兼容）
- [ ] **Step 5: commit**

```bash
git add sidecar/csm_sidecar/services/batch_service.py sidecar/csm_sidecar/routes/batch.py sidecar/tests/test_batch_scoring.py
git commit -m "feat(batch): 批量链路升级（注入+链+核对计数+评分+多候选选优+total_cost）"
```

---

# Unit D — 前端

## Task D1: article store（completeness/score/runScore/契约字段）

**Files:**
- Modify: `frontend/src/stores/article.ts`
- Create: `frontend/src/stores/__tests__/article.score.spec.ts`

- [ ] **Step 1: 失败测试** `article.score.spec.ts`

```ts
import { setActivePinia, createPinia } from "pinia";
import { describe, it, expect, vi, beforeEach } from "vitest";

const post = vi.fn();
const get = vi.fn().mockResolvedValue({ data: {} });
vi.mock("@/stores/sidecar", () => ({
  useSidecar: () => ({ client: { post, get } }),
}));

import { useArticle, type ScoreReport } from "@/stores/article";

const REPORT: ScoreReport = {
  total: 72.5,
  parts: [{ key: "lint", label: "禁区命中", points: 12, detail: "3 处" }],
};

describe("article score/completeness", () => {
  beforeEach(() => { setActivePinia(createPinia()); post.mockReset(); });

  it("runScore 存报告（形状校验）", async () => {
    post.mockResolvedValue({ data: REPORT });
    const a = useArticle();
    await a.runScore("正文");
    expect(a.score?.total).toBe(72.5);
  });

  it("runScore 非法形状 fail-open null", async () => {
    post.mockResolvedValue({ data: { foo: 1 } });
    const a = useArticle();
    await a.runScore("正文");
    expect(a.score).toBeNull();
  });

  it("runScore 带核对信号", async () => {
    post.mockResolvedValue({ data: REPORT });
    const a = useArticle();
    a.factcheck = { blocked: true, violations: [{ kind: "number", value: "9W", number: 9, sentence: "", suggestion: "" }] };
    a.completeness = { checked: true, missing: [{ kind: "cert", token: "CCC", value: null, sentence: "" }] };
    await a.runScore("正文");
    expect(post.mock.calls[0][1]).toEqual({
      text: "正文", factcheck_violations: 1, completeness_missing: 1,
    });
  });

  it("done 事件接 completeness + 自动评分", async () => {
    const a = useArticle();
    a.completeness = null;
    // 直接模拟 done handler 行为面：state 可写 + reset 清空
    a.completeness = { checked: true, missing: [] };
    a.score = REPORT;
    // submit reset 清空（复制 submit() 的 reset 清单断言两字段）
    post.mockResolvedValue({ data: { job_id: "x" } });
    // 不真跑 submit 全流程（SSE 依赖）；直接断言字段存在且可空
    expect(a.completeness.checked).toBe(true);
    a.$patch({ completeness: null, score: null });
    expect(a.completeness).toBeNull();
    expect(a.score).toBeNull();
  });
});
```

- [ ] **Step 2: 跑测试确认失败** — Expected: FAIL（`runScore`/`score` 不存在）

- [ ] **Step 3: 实现** —— `article.ts`：

(a) 类型（`FactcheckViolation` 旁）：

```ts
/** 完整性缺失项（镜像 csm_core.factcheck.completeness.MissingFact）。 */
export interface MissingFact {
  kind: "number" | "cert";
  token: string;
  value: number | null;
  sentence: string;
}
export interface ScorePart { key: string; label: string; points: number; detail: string }
export interface ScoreReport { total: number; parts: ScorePart[] }
```

(b) `GenerateRequest` TS 接口（本文件内定义处）加 `contract_mode?: "conservative" | "aggressive";`

(c) `ArticleState` 接口 + `state()` 初值加：

```ts
  completeness: { checked: boolean; missing: MissingFact[] } | null;   // 初值 null
  score: ScoreReport | null;                                            // 初值 null
```

(d) done handler（`this.factcheck = ...` 之后）加：

```ts
      // Phase 4+: 激进契约的完整性软警告（保守/未核 → null）。
      this.completeness =
        d.completeness && d.completeness.checked
          ? { checked: true, missing: d.completeness.missing ?? [] }
          : null;
```

并把末尾自动 lint 行扩为：

```ts
      if (this.finalText.trim()) {
        void this.runLint(this.finalText);
        void this.runScore(this.finalText);
      }
```

(e) `runLint` 旁加 `runScore`：

```ts
    async runScore(text: string): Promise<void> {
      if (!text.trim()) { this.score = null; return; }
      try {
        const r = await useSidecar().client.post("/api/score", {
          text,
          factcheck_violations: this.factcheck?.violations.length ?? 0,
          completeness_missing: this.completeness?.missing.length ?? 0,
        });
        const d = r.data;
        // scoring 关（total:null）或形状不对 → null（fail-open）
        this.score = d && typeof d.total === "number" && Array.isArray(d.parts)
          ? { total: d.total, parts: d.parts }
          : null;
      } catch {
        this.score = null;
      }
    },
```

(f) `submit()` reset 清单加 `this.completeness = null; this.score = null;`（lint 那行旁）；`finalize()` 的 reset 块同样加这两行。

(g) `rerunPass` 的 done 分支若有自动 lint（有——`rerunPass` 更新 final_text 后自动扫），同样补 `void this.runScore(this.finalText);`（与 runLint 并列；先 grep `rerunPass` 内 `runLint` 确认位置）。

- [ ] **Step 4: 跑测试确认通过** — Expected: 4 passed；既有 article.*.spec 全绿（done handler 变更对无 completeness 字段事件零影响）

- [ ] **Step 5: commit**

```bash
git add frontend/src/stores/article.ts frontend/src/stores/__tests__/article.score.spec.ts
git commit -m "feat(score): article store completeness/score 状态 + runScore 自动评分"
```

---

## Task D2: CompletenessPanel + 质检卡两项 + 契约 query 透传

**Files:**
- Create: `frontend/src/components/article/CompletenessPanel.vue`、`frontend/src/components/article/__tests__/CompletenessPanel.spec.ts`
- Modify: `frontend/src/views/ArticleView.vue`
- Create: `frontend/src/views/__tests__/ArticleView.contract.spec.ts`

- [ ] **Step 1: 失败测试**

`CompletenessPanel.spec.ts`：

```ts
import { mount } from "@vue/test-utils";
import { setActivePinia, createPinia } from "pinia";
import { describe, it, expect, vi, beforeEach } from "vitest";
import CompletenessPanel from "@/components/article/CompletenessPanel.vue";
import { useArticle, type MissingFact } from "@/stores/article";

vi.mock("@/stores/sidecar", () => ({ useSidecar: () => ({ client: { post: vi.fn(), get: vi.fn() } }) }));

const MISS: MissingFact = { kind: "number", token: "250AW", value: 250, sentence: "吸力 250AW。" };

describe("CompletenessPanel", () => {
  beforeEach(() => setActivePinia(createPinia()));

  it("渲染缺失项", () => {
    const a = useArticle();
    a.completeness = { checked: true, missing: [MISS] };
    const w = mount(CompletenessPanel, {
      props: { open: true }, global: { stubs: { teleport: true } } });
    expect(w.findAll("[data-missing-fact]")).toHaveLength(1);
    expect(w.text()).toContain("250AW");
  });
});
```

`ArticleView.contract.spec.ts`（镜像 ArticleView.angle.spec.ts 的 query→submit 断言法——先读那个文件，复用其 mount/mock 装置）：

```ts
// 断言：route.query.contract="aggressive" → article.submit 收到
// contract_mode:"aggressive"；query 无 contract → submit body 无该键（undefined）。
// 若 angle.spec 采用「抽纯函数断言」风格，则同样抽 query 解析断言。
```

- [ ] **Step 2: 跑测试确认失败**

- [ ] **Step 3: 实现**

`CompletenessPanel.vue`（纯信息展示、无 proceed——不进导出守卫链）：

```vue
<script setup lang="ts">
/**
 * 完整性缺失面板 —— 激进契约删稿后，主推型号关键事实缺失清单（软提醒）。
 * 纯信息展示：不拦导出、无 proceed（PR#148 教训只约束带 proceed 的门禁面板）。
 */
import Dialog from "@/components/ui/Dialog.vue";
import Pill from "@/components/ui/Pill.vue";
import { useArticle } from "@/stores/article";

const open = defineModel<boolean>("open", { default: false });
const article = useArticle();
</script>

<template>
  <Dialog v-model:open="open" title="完整性检查 — 主推事实缺失" size="md">
    <p class="text-ink-3 text-sm">
      激进契约允许删减，以下主推型号关键事实在成稿中消失了。可回「成稿」手动补回，或重新润色。
    </p>
    <ul class="mt-3 flex flex-col gap-2">
      <li v-for="(m, i) in article.completeness?.missing ?? []" :key="i"
          data-missing-fact class="border-ink/10 rounded-lg border p-3">
        <div class="flex items-center gap-2 text-sm">
          <Pill tone="warn">{{ m.kind === "number" ? "参数" : "认证" }}</Pill>
          <span class="font-medium">{{ m.token }}</span>
        </div>
        <div class="text-ink-3 mt-1 text-xs">初稿：{{ m.sentence }}</div>
      </li>
    </ul>
  </Dialog>
</template>
```

`ArticleView.vue`：

(a) import CompletenessPanel + `const showCompleteness = ref(false);`

(b) 质检卡 `checkItems` 里「禁区」项之后追加两项：

```ts
  // 第 8 项：完整性（激进契约才核；保守 → "—"）
  const comp = article.completeness;
  items.push({
    label: "完整性",
    value: comp ? (comp.missing.length ? `缺 ${comp.missing.length} 处` : "无缺失") : "—",
    desc: comp
      ? (comp.missing.length ? "主推事实被删，点下方按钮查看" : "主推事实完整保留")
      : "激进契约生成后自动核对",
    pass: !comp || comp.missing.length === 0,
    tone: comp && comp.missing.length ? "warn" : "ok",
  });

  // 第 9 项：综合评分
  const sc = article.score;
  items.push({
    label: "综合评分",
    value: sc ? `${sc.total} 分` : "—",
    desc: sc
      ? (sc.parts.length ? `扣分：${sc.parts.slice(0, 3).map((p) => `${p.label}-${p.points}`).join("、")}` : "无扣分")
      : "成稿后自动评分",
    pass: !sc || sc.total >= 60,
    tone: !sc ? "warn" : sc.total >= 80 ? "ok" : sc.total >= 60 ? "warn" : "alert",
  });
```

（`CheckItem.tone` 若无 `"alert"` 取值，先看类型定义——Pill 支持 alert；若 CheckItem 类型限窄则扩它的联合类型。）

(c) 操作卡（「导出文章」按钮附近）加条件按钮：

```html
<Btn v-if="article.completeness?.missing.length" variant="ghost" small
     data-open-completeness @click="showCompleteness = true">
  完整性缺失 {{ article.completeness.missing.length }} 处 →
</Btn>
```

模板尾 `<LintPanel ...>` 之后：`<CompletenessPanel v-model:open="showCompleteness" />`。

(d) 契约 query 透传：onMounted 的 query 解析区加 `const qc = (route.query.contract as string) ?? "";`；takeoff 组装 `GenerateRequest` 处（本文件的 takeoff/submit 调用——grep `article.submit(` 定位）把 `contract_mode: qc === "aggressive" || qc === "conservative" ? qc : undefined,` 并入请求对象。`finalize()` 走 store 内 `lastRequest`，无需改。

- [ ] **Step 4: 跑测试 + vue-tsc** — 新测试绿 + `ArticleView.*.spec` 全绿 + `npx vue-tsc -b` 0 错（fixture 显式标注 `MissingFact`）

- [ ] **Step 5: commit**

```bash
git add frontend/src/components/article/CompletenessPanel.vue frontend/src/components/article/__tests__/CompletenessPanel.spec.ts frontend/src/views/ArticleView.vue frontend/src/views/__tests__/ArticleView.contract.spec.ts
git commit -m "feat(contract): 质检卡完整性+综合评分两项 + CompletenessPanel + 契约 query 透传"
```

---

## Task D3: Hero 契约 chip + 设置卡 + 批量前端

**Files:**
- Modify: `frontend/src/components/home/CreateArticleHero.vue`
- Create: `frontend/src/components/settings/ContractCard.vue`；Modify: SettingsView（import + 列表处，先 grep `PricingCard` 定位）
- Modify: `frontend/src/stores/batch.ts`、`frontend/src/views/BatchView.vue`
- Create: `frontend/src/stores/__tests__/batch.score.spec.ts`

- [ ] **Step 1: 失败测试** `batch.score.spec.ts`（镜像既有 `batch.spec.ts` 的 mock 装置——先读它）：

```ts
// 断言清单：
// 1) submit 传 candidates（store 新字段 candidates 默认 1；设 2 → POST body
//    含 candidates:2；默认 1 → body 含 candidates:1）。
// 2) item_finished 带 score/score_parts/candidate_scores/factcheck_violations
//    → BatchItem 对应字段落位。
// 3) done 带 total_cost → store.totalCost 落位。
```

- [ ] **Step 2: 跑测试确认失败**

- [ ] **Step 3: 实现**

`batch.ts`：`BatchItem` 加 `score: number | null; score_parts: { key: string; label: string; points: number; detail: string }[]; candidate_scores: number[]; factcheck_violations: number;`（**注意 refreshSnapshot 从 to_dict 来的对象天然带这些键**）；state 加 `candidates: 1 as number` 与 `totalCost: null as { input_tokens: number; output_tokens: number; cost: number | null; currency: string } | null`；`submit()` body 加 `candidates: this.candidates,`；`item_finished` handler 补四字段赋值（`it.score = d.score ?? null;` 等）；`done` handler 加 `this.totalCost = d.total_cost ?? null;`；submit reset 区加 `this.totalCost = null;`。

`BatchView.vue`：

(a) 表单右栏 Skill 之后加：

```html
    <div>
      <div class="text-ink-3 mb-1">每词候选数</div>
      <FormSelect
        :model-value="batch.candidates"
        :options="[
          { label: '1（默认）', value: 1 },
          { label: '2（费用×2）', value: 2 },
          { label: '3（费用×3）', value: 3 },
        ]"
        :disabled="batch.isRunning"
        @update:model-value="(v) => (batch.candidates = Number(v))"
      />
    </div>
```

(b) 结果表：表头「状态」后插 `<th class="py-2 text-right font-medium">评分</th>`；行内对应位置插：

```html
      <td class="py-2 text-right">
        <Pill v-if="it.score != null" :tone="it.score >= 80 ? 'ok' : it.score >= 60 ? 'warn' : 'alert'"
              :title="scoreTooltip(it)">
          {{ it.score.toFixed(0) }}
        </Pill>
        <span v-else class="text-ink-3">—</span>
      </td>
```

script 加：

```ts
function scoreTooltip(it: BatchItem): string {
  const parts = (it.score_parts ?? []).map((p) => `${p.label} -${p.points}`).join("；");
  const cands = (it.candidate_scores ?? []).length > 1
    ? `候选分：${it.candidate_scores.map((s) => s.toFixed(0)).join(" / ")}` : "";
  return [parts, cands].filter(Boolean).join("\n") || "无扣分";
}
```

（import `type BatchItem`。设计稿写「行展开」，v1 以 Pill tooltip 呈现同等信息——表格无展开行基建，tooltip 零基建同信息量，PR 描述里注明该偏离。）

(c) done 汇总区（byStatus 展示处附近）若有汇总行，加 `total_cost` 展示：`≈{{ batch.totalCost.input_tokens + batch.totalCost.output_tokens }} tokens · ≈¥{{ batch.totalCost.cost?.toFixed(2) ?? "—" }}`（v-if totalCost）。

`CreateArticleHero.vue`：模板/风格/角度 chip 行尾加契约 chip（复用 Dropdown，同模板 chip 结构）：

```ts
const CONTRACT_ITEMS = [
  { key: "", label: "跟随全局" },
  { key: "conservative", label: "保守（保留全部信息点）" },
  { key: "aggressive", label: "激进（允许删减更精炼）" },
];
const contractMode = ref<string>("");
const contractLabel = computed(() =>
  contractMode.value === "aggressive" ? "激进" : contractMode.value === "conservative" ? "保守" : "全局");
```

chip 按钮样式照抄「模板」chip（label=「契约」，value=contractLabel）；`takeoff()` 里加 `if (contractMode.value) query.contract = contractMode.value;`。

`ContractCard.vue`（镜像 PricingCard 的卡壳与 cfg.patch 用法）：

```vue
<script setup lang="ts">
/** 生成契约设置卡 —— AppConfig.contract.mode 全局默认档（起飞可单次覆盖）。 */
import { computed, onMounted, ref } from "vue";
import Icon from "@/components/ui/Icon.vue";
import FormSelect from "@/components/forms/FormSelect.vue";
import { useConfig } from "@/stores/config";
import { useToast } from "@/composables/useToast";

const cfg = useConfig();
const toast = useToast();
const mode = ref<string>("conservative");

onMounted(async () => {
  if (!cfg.data) { try { await cfg.load(); } catch { /* store 持有 error */ } }
  mode.value = (cfg.data as any)?.contract?.mode ?? "conservative";
});

async function commit(v: string | number) {
  mode.value = String(v);
  try {
    await cfg.patch({ contract: { mode: mode.value } });
    toast.success("已保存");
  } catch (e: any) {
    toast.error(`保存失败：${cfg.error ?? e?.message ?? e}`);
  }
}
</script>

<template>
  <div class="rounded-card" :style="{ background: 'var(--card-2)', padding: '16px' }">
    <div class="flex items-center gap-2">
      <span class="inline-flex h-7 w-7 items-center justify-center rounded-lg" :style="{ background: 'var(--card)' }">
        <Icon name="stack" :size="15" />
      </span>
      <div>
        <div class="font-display text-[13.5px] font-semibold">生成契约</div>
        <div class="mt-0.5 text-[11px]" :style="{ color: 'var(--ink-4)' }">
          保守=保留全部信息点；激进=允许删减更精炼（有完整性警告兜底）。起飞时可单次覆盖。
        </div>
      </div>
    </div>
    <div class="mt-4" style="max-width: 260px">
      <FormSelect data-contract-mode :model-value="mode"
        :options="[
          { label: '保守（默认，保留全部信息点）', value: 'conservative' },
          { label: '激进（允许取舍删减）', value: 'aggressive' },
        ]"
        @update:model-value="commit" />
    </div>
  </div>
</template>
```

SettingsView：import ContractCard + 在 PricingCard 同区插 `<ContractCard />`（位置随卡片列表流）。

- [ ] **Step 4: 跑测试 + 全量前端 + vue-tsc**

```powershell
cd frontend; npx vitest run
cd frontend; npx vue-tsc -b
```
Expected: 全绿（含既有 batch.spec 零回归）；vue-tsc 0 错。还原 vite.config.js。

- [ ] **Step 5: commit**

```bash
git add frontend/src/components/home/CreateArticleHero.vue frontend/src/components/settings/ContractCard.vue frontend/src/views/SettingsView.vue frontend/src/stores/batch.ts frontend/src/views/BatchView.vue frontend/src/stores/__tests__/batch.score.spec.ts
git commit -m "feat(contract/score): Hero 契约 chip + 设置卡 + 批量候选数/评分列/成本汇总"
```

---

# 收尾

- [ ] **全量回归**：csm_core `tests/` + sidecar `sidecar/tests/` + 前端全量 vitest + `vue-tsc -b`（以「无新增失败」为准，预存失败清单见顶部）。
- [ ] **最终综合审查**（opus）：保守 prompt 字节级零回归（快照测试背书）、契约穿透三径一致（交互/finalize/批量 + rerun 复用缓存档）、完整性只核主推/万对称、批量 candidates=1 零回归 + 多候选导出高分者 + 落选稿落盘、评分确定性（同文同分）、chain cache=False 不污染 rerun 缓存、事件字段向后兼容、前端 fail-open 三处（lint/score/completeness）。
- [ ] **收尾 PR**：push `claude/phase4-contract-scoring` + `gh pr create --base claude/phase4-vault-perf`（中文 body + 🤖 trailer；body 注明 stacked on PR-A、merge 顺序），停在 pending 等网页 merge。

## 备注（实现者注意）

1. **config 隔离铁律**：所有读 config 的 sidecar 测试 monkeypatch `config_service.load`；批量测试还要 `vault_cache_reset`（batch 走 `vault_service.get`）。
2. **共享盘红线**：测试全走 tmp_path 合成 vault，绝不碰 `D:\家电组共享\DATA`。
3. **保守分支字节红线**：`build_prompt` 保守两分支字符串一个字符都不许动（A1 快照测试钉死）。
4. **vue-tsc**：fixture 字面量 union 显式标注（`MissingFact`/`ScoreReport`/`BatchItem`）；跑完还原 vite.config.js。
5. **teleport stub**：含 Dialog 的组件测试 mount 加 `global:{stubs:{teleport:true}}`。
6. **批量事件向后兼容**：`item_finished` 只加键不改旧键；旧前端（未升级 tab）忽略新键。
7. **`_effective_model` 不跨模块借私有**：批量 total_cost 的 model 解析按 (f) 内联。
