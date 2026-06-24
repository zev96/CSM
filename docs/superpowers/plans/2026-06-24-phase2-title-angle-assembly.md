# 标题 + 角度 智能组装 实现计划（Phase 2a）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现。步骤用 `- [ ]` 复选框跟踪。

**Goal:** 让用户换「角度」（人群/卖点/语调/标题）就能产出结构和侧重明显不同、但参数依旧接地的文章；不传角度 = 今天行为（零回归）。

**Architecture:** 混合路线——确定性层做廉价两件（人群按 `人群分类` frontmatter 过滤用户人群块、卖点维度在注入时优先该维度话术），其余（排序/侧重/语调/标题领衔）由 LLM 角度指令块承载；语调走 LLM 改写不动 vault；保守 LLM 契约（保信息点、不取舍删减、不新增改动事实）。新增 `csm_core/angle/` 纯逻辑包，存量改动集中在 sampler/inject/prompts/generate_service。

**Tech Stack:** Python（csm_core 纯逻辑 + FastAPI sidecar，pydantic v2，pytest）、Vue 3 + Pinia + TS（Vitest）。

**Spec:** [2026-06-24-phase2-title-angle-assembly-design.md](../specs/2026-06-24-phase2-title-angle-assembly-design.md)

---

## 文件结构

| 层 | 新增 | 必改 |
|---|---|---|
| `csm_core/angle/`（新包） | `__init__.py`、`model.py`、`taxonomy.py`、`filters.py`、`directive.py` | — |
| `csm_core/assembler/` | — | `plan.py`、`constraints.py`、`sampler.py`、`reroll.py` |
| `csm_core/brand_memory/` | — | `inject.py` |
| `csm_core/llm/` | — | `prompts.py` |
| `sidecar/csm_sidecar/services/` | — | `generate_service.py` |
| `sidecar/csm_sidecar/routes/` | `angle.py` | `generate.py`、`__init__.py`(注册路由) |
| `frontend/src/` | `components/article/AnglePicker.vue` | `stores/article.ts`、`components/home/CreateArticleHero.vue`、`views/ArticleView.vue` |

**不改**：`assembler_service.py`、`routes/assembler.py`（reroll 读 `plan.angle`，无需新参数）；`title/generator.py`、`routes/article.py`（标题端点复用）。

**关键命令**（worktree 内，用 PowerShell 工具；cwd 已是本 worktree）：
- 后端测试：`python -m pytest tests/core/angle -v`（按目录调整）
- 前端测试：`cd frontend; npx vitest run src/...`
- 跑测试前若 `git status` 显示 `@esbuild/*` 被 npm 改动，`git checkout -- frontend/package-lock.json` 还原（勿提交）。

---

## Unit A — `csm_core/angle/` 词表与派生（纯数据，测试密）

### Task A1：`Angle` 模型

**Files:**
- Create: `csm_core/angle/__init__.py`
- Create: `csm_core/angle/model.py`
- Test: `tests/core/angle/__init__.py`（空）、`tests/core/angle/test_model.py`

- [ ] **Step 1: 写失败测试** `tests/core/angle/test_model.py`

```python
from csm_core.angle.model import Angle


def test_empty_angle_is_empty():
    assert Angle().is_empty() is True
    assert Angle(audience=None, sellpoints=[], tone=None).is_empty() is True


def test_any_facet_makes_nonempty():
    assert Angle(audience="铲屎官").is_empty() is False
    assert Angle(sellpoints=["防缠绕技术"]).is_empty() is False
    assert Angle(tone="口语").is_empty() is False


def test_json_round_trip():
    a = Angle(audience="老年人", sellpoints=["机身重量"], tone="专业")
    assert Angle.model_validate(a.model_dump()) == a


def test_defaults_are_safe():
    a = Angle()
    assert a.audience is None and a.sellpoints == [] and a.tone is None
```

- [ ] **Step 2: 跑测试确认失败** — `python -m pytest tests/core/angle/test_model.py -v` → ModuleNotFoundError。

- [ ] **Step 3: 实现** `csm_core/angle/model.py`

```python
"""Angle — per-request 选材意图（人群/卖点/语调），全可空。"""
from __future__ import annotations
from pydantic import BaseModel, Field


class Angle(BaseModel):
    audience: str | None = None        # 16 人群之一，如 "铲屎官"
    sellpoints: list[str] = Field(default_factory=list)  # 卖点维度键，0..N
    tone: str | None = None            # "口语" | "专业" | "极客"

    def is_empty(self) -> bool:
        """等价于「不传 angle」⇔ 今天行为。"""
        return not self.audience and not self.sellpoints and not self.tone
```

`csm_core/angle/__init__.py`：

```python
"""角度智能组装 — 词表 + 派生（Phase 2a）。"""
from .model import Angle
from .filters import effective_filters, effective_sellpoints
from .directive import render_angle_directive

__all__ = [
    "Angle", "effective_filters", "effective_sellpoints", "render_angle_directive",
]
```

> 注：`__init__` 引用了 A3/A4/A5 的符号，先建文件但这些 import 会在 A3-A5 完成后才解析通过。本任务可先只 `from .model import Angle`，A5 后补全 `__all__`。

- [ ] **Step 4: 跑测试确认通过** — `python -m pytest tests/core/angle/test_model.py -v` → 4 passed。

- [ ] **Step 5: 提交**

```bash
git add csm_core/angle/__init__.py csm_core/angle/model.py tests/core/angle/
git commit -m "feat(angle): Angle 模型（人群/卖点/语调，全可空 opt-in）"
```

---

### Task A2：受控词表 `taxonomy.py`

**Files:**
- Create: `csm_core/angle/taxonomy.py`
- Test: `tests/core/angle/test_taxonomy.py`

- [ ] **Step 1: 写失败测试**（引用完整性 — 守门）

```python
from csm_core.angle import taxonomy as t


def test_tones_three():
    assert set(t.TONES) == {"口语", "专业", "极客"}
    assert all(t.TONES[k].strip() for k in t.TONES)


def test_dimensions_have_key_and_label():
    keys = [d["key"] for d in t.SELLPOINT_DIMENSIONS]
    assert len(keys) == len(set(keys)), "维度 key 不可重复"
    assert all(d["key"] and d["label"] for d in t.SELLPOINT_DIMENSIONS)


def test_audiences_16_and_dims_valid():
    assert len(t.AUDIENCES) == 16
    valid = {d["key"] for d in t.SELLPOINT_DIMENSIONS}
    for name, prof in t.AUDIENCES.items():
        # 主推维度要么空、要么在维度表里
        assert prof["主推维度"] in valid or prof["主推维度"] == ""
        assert prof["痛点主题"] and prof["科普主题"]


def test_presets_reference_valid_facets():
    valid_dim = {d["key"] for d in t.SELLPOINT_DIMENSIONS}
    for p in t.PRESETS:
        assert p["name"]
        if p["audience"] is not None:
            assert p["audience"] in t.AUDIENCES
        if p["tone"] is not None:
            assert p["tone"] in t.TONES
        for s in p["sellpoints"]:
            assert s in valid_dim
```

- [ ] **Step 2: 跑测试确认失败**。

- [ ] **Step 3: 实现** `csm_core/angle/taxonomy.py`（维度键对齐 resolver `_dimension_from_stem` 产出 = 关联数据库 §2.1 的 4 核心 + 8 次要，去掉①②③）

```python
"""受控词表（小映射）— 角度选项 / 预设 / LLM 指令文案的单一来源。
仅吸尘器品类；多品类是未来。维度 key 必须等于品牌话术维度键（resolver
_dimension_from_stem 产出），见 test_taxonomy_real_vault（A6）校准。"""
from __future__ import annotations

AUDIENCE_MODULE_MARKER = "用户人群"  # 人群 filter 只加在 source.module 含此标记的块

TONES: dict[str, str] = {
    "口语": "在保持人设前提下偏口语：多用短句、第二人称「你」、生活化比喻，像朋友唠嗑；少术语堆砌。",
    "专业": "在保持人设前提下偏专业：准确术语 + 参数化表达、结构清晰，像测评编辑；克制情绪化修辞。",
    "极客": "在保持人设前提下偏极客：强调原理、参数、横向对比与技术机制，面向懂行读者；可深入细节。",
}

# key = 话术维度键（dict 匹配 scripts）；label = 人话标签（UI/指令显示）
SELLPOINT_DIMENSIONS: list[dict] = [
    {"key": "动力系统",   "label": "吸力·电机"},
    {"key": "气旋技术",   "label": "气旋分离"},
    {"key": "过滤系统",   "label": "过滤·HEPA"},
    {"key": "防缠绕技术", "label": "防缠绕"},
    {"key": "绿光显尘",   "label": "绿光显尘"},
    {"key": "机身重量",   "label": "机身重量"},
    {"key": "尘杯容量",   "label": "尘杯容量"},
    {"key": "续航时间",   "label": "续航"},
    {"key": "万向吸头",   "label": "万向吸头"},
    {"key": "刷头配置",   "label": "刷头配件"},
    {"key": "噪音大小",   "label": "噪音·静音"},
    {"key": "维护耗材",   "label": "维护耗材"},
]

# 16 人群 → 主推维度 / 痛点主题 / 科普主题（关联数据库 §5）；
# 痛点主题为编辑性短语种子，用户可调。
AUDIENCES: dict[str, dict] = {
    "铲屎官":       {"主推维度": "防缠绕技术", "痛点主题": "宠物毛发缠绕刷头",   "科普主题": "防缠绕设计选购"},
    "过敏人群":     {"主推维度": "过滤系统",   "痛点主题": "粉尘过敏与二次污染", "科普主题": "过滤系统选购"},
    "宝妈":         {"主推维度": "绿光显尘",   "痛点主题": "看不见的灰尘与儿童健康", "科普主题": "显尘功能选购"},
    "老年人":       {"主推维度": "机身重量",   "痛点主题": "机身太重推不动",     "科普主题": "机身重量选购"},
    "大户型用户":   {"主推维度": "续航时间",   "痛点主题": "一次打扫续航不够",   "科普主题": "续航时间选购"},
    "上班族":       {"主推维度": "动力系统",   "痛点主题": "吸力衰减、清洁效率低", "科普主题": "吸力参数选购"},
    "小户型用户":   {"主推维度": "机身重量",   "痛点主题": "收纳难、要轻便",     "科普主题": "机身重量选购"},
    "租房党":       {"主推维度": "机身重量",   "痛点主题": "轻便易搬、好收纳",   "科普主题": "机身重量选购"},
    "有地毯家庭":   {"主推维度": "防缠绕技术", "痛点主题": "地毯深尘与缠绕",     "科普主题": "刷头配件选购"},
    "硬地板用户":   {"主推维度": "万向吸头",   "痛点主题": "贴边清洁与灵活转向", "科普主题": "刷头配件选购"},
    "科技爱好者":   {"主推维度": "动力系统",   "痛点主题": "参数与极致性能",     "科普主题": "吸力参数选购"},
    "性价比党":     {"主推维度": "",           "痛点主题": "怕虚标、怕交智商税", "科普主题": "综合使用体验选购避坑指南"},
    "家居爱好者":   {"主推维度": "刷头配置",   "痛点主题": "配件齐全度与多场景", "科普主题": "刷头配件选购"},
    "精致生活人群": {"主推维度": "噪音大小",   "痛点主题": "噪音扰民、要静音",   "科普主题": "噪音大小选购"},
    "多层住宅用户": {"主推维度": "机身重量",   "痛点主题": "上下楼搬运负担",     "科普主题": "机身重量选购"},
    "通用人群":     {"主推维度": "动力系统",   "痛点主题": "选购迷茫、信息过载", "科普主题": "综合使用体验选购避坑指南"},
}

# 预设组合（关联数据库 §4.3 内容流）；template_id 不确定就 None（实现期可填真实模板 id）
PRESETS: list[dict] = [
    {"name": "宝妈/儿童健康", "template_id": None, "audience": "宝妈",
     "sellpoints": ["绿光显尘", "过滤系统"], "tone": "口语"},
    {"name": "测评博主",     "template_id": None, "audience": None,
     "sellpoints": [], "tone": "专业"},
    {"name": "技术维修视角", "template_id": None, "audience": None,
     "sellpoints": [], "tone": "极客"},
    {"name": "选购困难",     "template_id": None, "audience": "通用人群",
     "sellpoints": [], "tone": "口语"},
]
```

- [ ] **Step 4: 跑测试确认通过**。

- [ ] **Step 5: 提交**

```bash
git add csm_core/angle/taxonomy.py tests/core/angle/test_taxonomy.py
git commit -m "feat(angle): 受控词表（3 语调/12 维度/16 人群矩阵/4 预设，单一来源）"
```

---

### Task A3：`effective_sellpoints`

**Files:** Modify `csm_core/angle/filters.py`（与 A4 同文件，先建）；Test `tests/core/angle/test_filters.py`

- [ ] **Step 1: 写失败测试**（追加到 test_filters.py）

```python
from csm_core.angle.model import Angle
from csm_core.angle.filters import effective_sellpoints


def test_explicit_sellpoints_win():
    a = Angle(audience="铲屎官", sellpoints=["续航时间"])
    assert effective_sellpoints(a) == ["续航时间"]


def test_audience_derives_primary_dim():
    a = Angle(audience="铲屎官")  # 主推维度=防缠绕技术
    assert effective_sellpoints(a) == ["防缠绕技术"]


def test_audience_with_empty_primary_dim():
    a = Angle(audience="性价比党")  # 主推维度=""
    assert effective_sellpoints(a) == []


def test_no_audience_no_sellpoints():
    assert effective_sellpoints(Angle()) == []
    assert effective_sellpoints(None) == []
```

- [ ] **Step 2: 跑测试确认失败**。

- [ ] **Step 3: 实现**（`csm_core/angle/filters.py`，A4 会往同文件加 `effective_filters`）

```python
"""角度派生：有效卖点 + 有效查询 filter（采样/reroll/持久化共用）。"""
from __future__ import annotations
from typing import Any
from .model import Angle
from .taxonomy import AUDIENCES, AUDIENCE_MODULE_MARKER


def effective_sellpoints(angle: Angle | None) -> list[str]:
    """显式卖点 > 人群派生主推维度 > 空。用于注入优先 + 指令侧重。"""
    if angle is None:
        return []
    if angle.sellpoints:
        return list(angle.sellpoints)
    if angle.audience and angle.audience in AUDIENCES:
        dim = AUDIENCES[angle.audience]["主推维度"]
        return [dim] if dim else []
    return []
```

- [ ] **Step 4: 跑测试确认通过**。
- [ ] **Step 5: 提交** — `git commit -m "feat(angle): effective_sellpoints（显式>人群派生>空）"`

---

### Task A4：`effective_filters`

**Files:** Modify `csm_core/angle/filters.py`；Test `tests/core/angle/test_filters.py`

- [ ] **Step 1: 写失败测试**（追加）

```python
from types import SimpleNamespace
from csm_core.angle.filters import effective_filters


def _src(module, flt=None):
    return SimpleNamespace(module=module, filter=flt)


def test_audience_block_gets_renqun_filter():
    a = Angle(audience="铲屎官")
    eff = effective_filters(_src("营销资料库/用户人群/吸尘器"), a)
    assert eff == {"人群分类": "铲屎官"}


def test_audience_merges_with_existing_filter():
    a = Angle(audience="老年人")
    eff = effective_filters(_src("营销资料库/用户人群/吸尘器", {"产品": "吸尘器"}), a)
    assert eff == {"产品": "吸尘器", "人群分类": "老年人"}


def test_non_audience_block_untouched():
    a = Angle(audience="铲屎官")
    assert effective_filters(_src("营销资料库/科普模块/吸尘器", {"x": 1}), a) == {"x": 1}


def test_no_angle_returns_source_filter():
    assert effective_filters(_src("营销资料库/用户人群/吸尘器", {"x": 1}), None) == {"x": 1}
    assert effective_filters(_src("营销资料库/用户人群/吸尘器"), Angle()) == {}
```

- [ ] **Step 2: 跑测试确认失败**。

- [ ] **Step 3: 实现**（追加到 `filters.py`）

```python
def effective_filters(source: Any, angle: Angle | None) -> dict:
    """该块的有效查询 filter = source.filter ∪ 角度人群 filter。
    人群 filter 只在 source.module 含「用户人群」标记的块生效。
    采样、reroll、持久化共用此函数，避免逻辑漂移。"""
    base = dict(getattr(source, "filter", None) or {})
    if angle is None or not angle.audience:
        return base
    module = getattr(source, "module", "") or ""
    if AUDIENCE_MODULE_MARKER in module:
        base["人群分类"] = angle.audience
    return base
```

- [ ] **Step 4: 跑测试确认通过**。
- [ ] **Step 5: 提交** — `git commit -m "feat(angle): effective_filters（用户人群块按人群分类过滤，采样/reroll 共用）"`

---

### Task A5：`render_angle_directive`

**Files:** Create `csm_core/angle/directive.py`；Test `tests/core/angle/test_directive.py`

- [ ] **Step 1: 写失败测试**

```python
from csm_core.angle.model import Angle
from csm_core.angle.directive import render_angle_directive


def test_empty_angle_no_directive():
    assert render_angle_directive(Angle()) is None
    assert render_angle_directive(None) is None


def test_full_directive_mentions_facets():
    a = Angle(audience="铲屎官", sellpoints=["防缠绕技术", "续航时间"], tone="口语")
    d = render_angle_directive(a)
    assert "铲屎官" in d
    assert "宠物毛发缠绕刷头" in d        # 来自 AUDIENCES 痛点主题
    assert "防缠绕" in d and "续航" in d   # 维度 display 标签
    assert "口语" in d


def test_audience_only_uses_primary_dim():
    d = render_angle_directive(Angle(audience="铲屎官"))
    assert "防缠绕" in d                   # 主推维度派生进侧重


def test_unknown_values_skipped_not_crash():
    d = render_angle_directive(Angle(audience="火星人", sellpoints=["不存在"], tone="???"))
    assert isinstance(d, str)              # 不抛异常；非法值跳过
```

- [ ] **Step 2: 跑测试确认失败**。

- [ ] **Step 3: 实现** `csm_core/angle/directive.py`

```python
"""把 Angle 渲染成一段中文「角度指令块」喂给 LLM（保守契约）。"""
from __future__ import annotations
from .model import Angle
from .taxonomy import AUDIENCES, SELLPOINT_DIMENSIONS, TONES
from .filters import effective_sellpoints

_DIM_LABEL = {d["key"]: d["label"] for d in SELLPOINT_DIMENSIONS}


def render_angle_directive(angle: Angle | None) -> str | None:
    if angle is None or angle.is_empty():
        return None
    lines: list[str] = ["【写作角度】"]
    if angle.audience and angle.audience in AUDIENCES:
        prof = AUDIENCES[angle.audience]
        lines.append(f"- 目标读者：{angle.audience}（核心痛点：{prof['痛点主题']}）")
    elif angle.audience:
        lines.append(f"- 目标读者：{angle.audience}")
    dims = [d for d in effective_sellpoints(angle) if d in _DIM_LABEL]
    if dims:
        labels = "、".join(_DIM_LABEL[d] for d in dims)
        lines.append(f"- 主打卖点：{labels}（优先展开、突出差异）")
    if angle.tone and angle.tone in TONES:
        lines.append(f"- 语调：{angle.tone} —— {TONES[angle.tone]}")
    lines.append("请据此组织素材的详略与顺序；不得新增或改动任何参数/数字/认证。")
    return "\n".join(lines)
```

- [ ] **Step 4: 跑测试确认通过**。补全 `__init__.py` 的 `from .filters import ...` / `from .directive import ...`（A1 Step 3 注里说的）。
- [ ] **Step 5: 提交** — `git commit -m "feat(angle): render_angle_directive（角度→中文指令块，宽松校验）"`

---

### Task A6：真实库维度键校准（skip-by-default 集成测试）

**Files:** Test `tests/core/angle/test_taxonomy_real_vault.py`（仿 `tests/core/brand_memory/test_inject_real_vault.py` 的 skip 习惯）

- [ ] **Step 1: 写测试**（默认 skip；设环境变量才跑真实盘）

```python
import os
from pathlib import Path
import pytest
from csm_core.vault.scanner import scan_vault
from csm_core.brand_memory.resolver import resolve_memory
from csm_core.angle.taxonomy import SELLPOINT_DIMENSIONS

VAULT = os.environ.get("CSM_REAL_VAULT")  # e.g. D:\家电组共享\DATA\营销资料库


@pytest.mark.skipif(not VAULT, reason="set CSM_REAL_VAULT to run")
def test_sellpoint_keys_exist_in_real_scripts():
    index = scan_vault(Path(VAULT))
    mem = resolve_memory("CEWEY", "DS18", "吸尘器", index, own_brands={"CEWEY"})
    real_dims = set(mem.scripts.keys())
    declared = {d["key"] for d in SELLPOINT_DIMENSIONS}
    missing = declared - real_dims
    assert not missing, f"词表维度键在真实话术里找不到：{missing}（对齐 resolver 维度名）"
```

- [ ] **Step 2: 本地用真实盘跑一次**（实现者手动）：`CSM_REAL_VAULT=... python -m pytest tests/core/angle/test_taxonomy_real_vault.py -v`。**若 missing 非空 → 回 A2 修维度 key**（这是校准守门，spec §2.4）。
- [ ] **Step 3: 提交** — `git commit -m "test(angle): 真实库维度键校准（默认 skip）"`

> Unit A 收尾：`python -m pytest tests/core/angle -v` 全绿（A6 skip）。

---

## Unit B1 — csm_core 组装接线

### Task B1.1：`AssemblyPlan.angle` 字段

**Files:** Modify `csm_core/assembler/plan.py`；Test `tests/core/assembler/test_plan_angle.py`

- [ ] **Step 1: 写失败测试**

```python
from csm_core.assembler.plan import AssemblyPlan
from csm_core.angle.model import Angle


def test_plan_carries_angle_round_trip():
    p = AssemblyPlan(keyword="k", template_id="t", seed=0,
                     angle=Angle(audience="铲屎官"))
    assert AssemblyPlan.from_json(p.to_json()).angle == Angle(audience="铲屎官")


def test_old_json_without_angle_defaults_none():
    p = AssemblyPlan(keyword="k", template_id="t", seed=0)
    assert p.angle is None
    # 模拟旧 JSON（无 angle 键）
    j = '{"keyword":"k","template_id":"t","seed":0,"results":[],"warnings":[]}'
    assert AssemblyPlan.from_json(j).angle is None
```

- [ ] **Step 2: 跑测试确认失败**。

- [ ] **Step 3: 实现** — `plan.py` 顶部 import + `AssemblyPlan` 加字段：

```python
from csm_core.angle.model import Angle  # 顶部 import 区

# AssemblyPlan 内，warnings 字段之后加：
    angle: Angle | None = None         # Phase 2a 角度（旧 JSON 无此字段 → None）
```

- [ ] **Step 4: 跑测试确认通过**。
- [ ] **Step 5: 提交** — `git commit -m "feat(assembler): AssemblyPlan 持久化 angle（旧 JSON 兼容 None）"`

---

### Task B1.2：`assemble_plan(angle=…)` 透传 + 写入 plan.angle

**Files:** Modify `csm_core/assembler/constraints.py`（[constraints.py:163](../../../csm_core/assembler/constraints.py)）；Test `tests/core/assembler/test_assemble_angle.py`

- [ ] **Step 1: 写失败测试**（用现成最小 template/index fixture，参考 `tests/core/assembler/` 既有 conftest）

```python
# 复用既有 assembler 测试夹具（template + index）。断言：
#  - assemble_plan(..., angle=Angle(audience="铲屎官")) 返回的 plan.angle == 该 angle
#  - angle=None → plan.angle is None
# （过滤行为在 B1.3 测；这里只验透传 + 落 plan.angle）
```

- [ ] **Step 2: 跑测试确认失败**。

- [ ] **Step 3: 实现** — `assemble_plan` 签名加 `angle: "Angle | None" = None`，把 `angle` 传进 `sample_block(...)` 调用（3 处：paragraph tree、test_framework 分支不需要、else 分支），并在返回 `AssemblyPlan(...)` 时加 `angle=angle`。`sample_paragraph_tree` 内 `sample_block(p, index, registry, seed=seed, user_config=user_config, aligned_models=aligned, angle=angle)`；else 分支 `sample_block(b, index, registry, seed=seed, user_config=user_config, angle=angle)`。顶部 `from csm_core.angle.model import Angle`。

- [ ] **Step 4: 跑测试确认通过**。
- [ ] **Step 5: 提交** — `git commit -m "feat(assembler): assemble_plan 透传 angle 并落 plan.angle"`

---

### Task B1.3：sampler 用 `effective_filters` + 空池回退

**Files:** Modify `csm_core/assembler/sampler.py`（`sample_block` 签名、`_sample_notes_source`、`_sample_source_for_block`）；Test `tests/core/assembler/test_sampler_angle.py`

- [ ] **Step 1: 写失败测试**

```python
# 用一个含「用户人群」module 的 NumberedList/Paragraph 块 + 两条带不同 人群分类
# frontmatter 的 note 的 index：
#  - angle=Angle(audience="铲屎官") → 只采到 人群分类=铲屎官 的 note
#  - angle 含未命中人群（空池）→ 回退到不过滤池（不抛 EmptyPoolError）
#  - 非用户人群 module 块不受 angle 影响
```

- [ ] **Step 2: 跑测试确认失败**。

- [ ] **Step 3: 实现**：
  - `sample_block(...)` 加形参 `angle: "Angle | None" = None`，传给 paragraph/numbered/competitor 分支调用的 `_sample_notes_source(..., angle=angle)` 与 `_sample_source_for_block(..., angle=angle)`。
  - `_sample_notes_source(...)` 加 `angle` 形参，把池查询改为：

```python
from csm_core.angle.filters import effective_filters  # 顶部

    eff = effective_filters(source, angle)
    pool = index.query(module=source.module, filters=eff)
    if not pool and eff != (source.filter or {}):
        # 角度过滤把池清空了 → 回退不带角度过滤（别让角度把文章搞空）
        import logging
        logging.getLogger(__name__).info(
            "block '%s': 角度过滤后空池，回退不过滤", block_id,
        )
        pool = index.query(module=source.module, filters=source.filter)
    if not pool:
        raise EmptyPoolError(f"block '{block_id}': empty pool in module '{source.module}'")
```

  - `_sample_source_for_block(...)` 加 `angle` 形参，仅把它转给 `_sample_notes_source`（其余 source 类型不涉及 notes_query filter，不变）。

- [ ] **Step 4: 跑测试确认通过 + 回归** — `python -m pytest tests/core/assembler -v`（既有采样测试默认 `angle=None`，必须仍全绿）。
- [ ] **Step 5: 提交** — `git commit -m "feat(assembler): sampler 按角度过滤用户人群块 + 空池回退"`

---

### Task B1.4：注入卖点优先 `render_brand_facts(sellpoints=)`

**Files:** Modify `csm_core/brand_memory/inject.py`（[inject.py:82](../../../csm_core/brand_memory/inject.py)）；Test `tests/core/brand_memory/test_inject_sellpoints.py`

- [ ] **Step 1: 写失败测试**

```python
# 构造一个 scripts 含多维度的 ModelScope，断言：
#  - render_brand_facts([scope], sellpoints=["防缠绕技术"]) 里 防缠绕技术 段在最前 + 标【主打】
#  - 其余维度仍在（不丢）
#  - sellpoints=[] → 行为同今天（顺序不变、无【主打】）
```

- [ ] **Step 2: 跑测试确认失败**。

- [ ] **Step 3: 实现** — `render_brand_facts` 加形参 `sellpoints: list[str] | None = None`，在渲染 `m.scripts` 那段按命中维度排前并加标记：

```python
def render_brand_facts(
    scopes: list[ModelScope], *,
    variant_cap: int = 3, endorsement_cap: int = 5,
    sellpoints: list[str] | None = None,
) -> str:
    primary = set(sellpoints or [])
    ...
        # 替换原 `for dim, variants in m.scripts.items():` 段：
        dim_items = list(m.scripts.items())
        if primary:
            dim_items.sort(key=lambda kv: kv[0] not in primary)  # 命中维度排前（稳定）
        for dim, variants in dim_items:
            shown = variants[:variant_cap]
            if shown:
                mark = "【主打】" if dim in primary else ""
                lines.append(f"{mark}{dim}：")
                lines.extend(f"- {v}" for v in shown)
```

- [ ] **Step 4: 跑测试确认通过 + 回归** — `python -m pytest tests/core/brand_memory -v`（`sellpoints=None` 默认必须等于今天，含真实库 inject 测试逻辑不变）。
- [ ] **Step 5: 提交** — `git commit -m "feat(brand_memory): 注入按卖点维度优先（命中排前+标【主打】，不丢其余）"`

---

### Task B1.5：prompts 标题领衔 + 角度指令 + 零回归分支

**Files:** Modify `csm_core/llm/prompts.py`；Test `tests/core/llm/test_prompts_angle.py`

- [ ] **Step 1: 写失败测试**

```python
from csm_core.llm.prompts import PromptInputs, build_prompt


def test_no_angle_no_title_snapshot_unchanged():
    # 钉死零回归：title/angle_directive 都 None 时，user prompt 与今天字节一致
    sys_, user = build_prompt(PromptInputs(
        user_skill_prompt="人设", keyword="无线吸尘器", draft="毛坯", brand_facts=None))
    assert "【关键词】无线吸尘器" in user
    assert "请按**润色模式**重写" in user
    assert "【写作角度】" not in user and "【标题】" not in user


def test_title_leads_and_directive_present():
    sys_, user = build_prompt(PromptInputs(
        user_skill_prompt="人设", keyword="无线吸尘器", draft="毛坯",
        brand_facts=None, title="无线吸尘器哪款好用？实测分享",
        angle_directive="【写作角度】\n- 目标读者：铲屎官"))
    assert "无线吸尘器哪款好用？实测分享" in user
    assert "【写作角度】" in user
    assert "围绕标题" in user  # 保守契约措辞
```

- [ ] **Step 2: 跑测试确认失败**。

- [ ] **Step 3: 实现** — `PromptInputs` 加 `title: str | None = None`、`angle_directive: str | None = None`；`build_prompt` 调整 user 拼装 + 指令分支：

```python
@dataclass
class PromptInputs:
    user_skill_prompt: str | None
    keyword: str
    draft: str
    brand_facts: str | None = None
    title: str | None = None
    angle_directive: str | None = None


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

    title_block = f"【标题】{inputs.title.strip()}\n\n" if inputs.title and inputs.title.strip() else ""
    angle_block = f"{inputs.angle_directive.strip()}\n\n" if inputs.angle_directive else ""

    if title_block or angle_block:
        # 保守契约：保信息点 + 按角度调侧重/顺序/详略/语调 + 标题领衔；不取舍删减、不增改事实
        instruction = (
            "请按上面【写作角度】组织成文：保留所有信息点，可调整侧重、顺序、详略与语调；"
            + ("围绕【标题】开篇点题、贯穿全文；" if title_block else "")
            + "不新增虚构事实，不改动任何数字、单位、认证，不删减关键信息点。"
        )
    else:
        instruction = (
            "请按**润色模式**重写：保留所有信息点和段落结构，只改进文字流畅度、"
            "衔接和风格一致性；不新增虚构事实，不删减关键信息。"
        )

    user = (
        f"【关键词】{inputs.keyword}\n\n"
        f"{title_block}"
        f"{angle_block}"
        f"{facts_block}"
        f"【毛坯文】\n{inputs.draft}\n\n"
        f"{instruction}"
        f"{constraint}"
    )
    return system, user
```

> ⚠ 零回归校验：`title`/`angle_directive` 都空时 user 拼装结果与今天**字节一致**（`title_block`/`angle_block` 为空串，instruction 走 else 原文）。快照测试守门。

- [ ] **Step 4: 跑测试确认通过 + 回归** — `python -m pytest tests/core/llm -v`（既有 build_prompt 测试不变）。
- [ ] **Step 5: 提交** — `git commit -m "feat(prompts): 标题领衔 + 角度指令块 + 零回归分支（保守契约）"`

---

### Task B1.6：reroll 跟随 `plan.angle`

**Files:** Modify `csm_core/assembler/reroll.py`（[reroll.py:62](../../../csm_core/assembler/reroll.py)）；Test `tests/core/assembler/test_reroll_angle.py`

- [ ] **Step 1: 写失败测试**

```python
# plan.angle=Angle(audience="铲屎官") + 用户人群块 → reroll_pick 重查池仍受 人群分类 约束
# （swap-in 的 note 必是 人群分类=铲屎官）；plan.angle=None → 行为同今天（纯 source.filter）
```

- [ ] **Step 2: 跑测试确认失败**。

- [ ] **Step 3: 实现** — `reroll_pick` 内把 `pool = vault_index.query(module=source.module, filters=source.filter)` 改为：

```python
from csm_core.angle.filters import effective_filters  # 顶部

    pool = vault_index.query(
        module=source.module, filters=effective_filters(source, plan.angle),
    )
```

（`plan` 已是入参，`plan.angle` 旧 plan 为 None → effective_filters 退回 source.filter。）

- [ ] **Step 4: 跑测试确认通过 + 回归** — `python -m pytest tests/core/assembler -v`。
- [ ] **Step 5: 提交** — `git commit -m "feat(assembler): reroll 跟随 plan.angle（用户人群不跳出）"`

---

## Unit B2 — sidecar 接线

### Task B2.1：generate_service 接角度全链

**Files:** Modify `sidecar/csm_sidecar/services/generate_service.py`；Test `tests/sidecar/test_generate_angle.py`（或扩展既有 generate 测试）

- [ ] **Step 1: 写失败测试**（单元级，mock LLM）

```python
# 断言：
#  - GenerateRequest 接受 title/angle
#  - 传 angle 时：assemble_plan 收到 angle（plan.angle 落库）；
#    render_brand_facts 收到 effective_sellpoints；build_prompt 收到 title + angle_directive
#  - 传 title 时 factcheck 白名单源含 title
# 用 monkeypatch 截获 build_prompt 的 PromptInputs 验证字段最简。
```

- [ ] **Step 2: 跑测试确认失败**。

- [ ] **Step 3: 实现**：
  - `GenerateRequest` 加 `title: str | None = None`、`angle: "Angle | None" = None`（顶部 `from csm_core.angle import Angle, effective_sellpoints, render_angle_directive`）。
  - `assemble_plan(...)` 调用加 `angle=req.angle`。
  - 注入段：`brand_facts = render_brand_facts(scopes, variant_cap=..., endorsement_cap=..., sellpoints=effective_sellpoints(req.angle))`（仅 `cfg_bm.inject` 分支内，保持原 `if scopes:` 结构）。
  - `build_prompt(PromptInputs(... , title=req.title, angle_directive=render_angle_directive(req.angle)))`。
  - `_maybe_block_for_factcheck(...)` 传入 `title=req.title`，其 `sources` 改为 `[draft] + ([req.title] if req.title else []) + ([brand_facts] if brand_facts else [])`（给函数加 `title` 形参）。

- [ ] **Step 4: 跑测试确认通过 + 回归** — `python -m pytest tests/sidecar -k generate -v`。
- [ ] **Step 5: 提交** — `git commit -m "feat(generate): 接角度全链（采样/注入卖点/角度指令/标题领衔/白名单纳标题）"`

---

### Task B2.2：`GenerateBody` 加 title/angle

**Files:** Modify `sidecar/csm_sidecar/routes/generate.py`；Test `tests/sidecar/test_routes_generate_angle.py`

- [ ] **Step 1: 写失败测试** — POST /api/generate 带 `title` + `angle:{audience,sellpoints,tone}` → 202，且服务层 GenerateRequest 收到 Angle 对象（mock submit 截获）。

- [ ] **Step 2: 跑测试确认失败**。

- [ ] **Step 3: 实现** — `GenerateBody` 加 `title: str | None = None`、`angle: Angle | None = None`（`from csm_core.angle import Angle`）；`start_generate` 显式构造避免 dict 污染：

```python
    req = generate_service.GenerateRequest(
        **body.model_dump(exclude={"angle"}),
        angle=body.angle,
    )
```

- [ ] **Step 4: 跑测试确认通过**。
- [ ] **Step 5: 提交** — `git commit -m "feat(routes): /api/generate 接 title/angle"`

---

### Task B2.3：`GET /api/angle/taxonomy`

**Files:** Create `sidecar/csm_sidecar/routes/angle.py`；Modify 路由注册（`sidecar/csm_sidecar/routes/__init__.py` 或 app 装配处，仿其它 router 注册）；Test `tests/sidecar/test_routes_angle.py`

- [ ] **Step 1: 写失败测试** — GET /api/angle/taxonomy → 200 且含 `tones`(3)、`dimensions`(12，每个 {key,label})、`audiences`(16 名)、`presets`(4)。

- [ ] **Step 2: 跑测试确认失败**。

- [ ] **Step 3: 实现** `routes/angle.py`：

```python
"""只读：角度受控词表（前端 picker 数据源，单一来源在后端）。"""
from __future__ import annotations
from fastapi import APIRouter
from ..auth import RequireToken
from csm_core.angle import taxonomy as t

router = APIRouter(tags=["angle"], dependencies=[RequireToken])


@router.get("/api/angle/taxonomy")
def get_taxonomy() -> dict:
    return {
        "tones": [{"key": k, "hint": v} for k, v in t.TONES.items()],
        "dimensions": t.SELLPOINT_DIMENSIONS,
        "audiences": list(t.AUDIENCES.keys()),
        "presets": [
            {"name": p["name"], "template_id": p["template_id"],
             "audience": p["audience"], "sellpoints": p["sellpoints"], "tone": p["tone"]}
            for p in t.PRESETS
        ],
    }
```

注册：在装配处 `app.include_router(angle.router)`（仿 assembler/generate router）。

- [ ] **Step 4: 跑测试确认通过**。
- [ ] **Step 5: 提交** — `git commit -m "feat(routes): GET /api/angle/taxonomy（词表只读，picker 数据源）"`

> Unit B 收尾：`python -m pytest tests/core tests/sidecar -q`（角度相关全绿 + 既有零回归；预存的 5 个无关失败见记忆，不排查）。

---

## Unit C — 前端 angle picker

### Task C1：store 类型与 submit 接角度

**Files:** Modify `frontend/src/stores/article.ts`；Test `frontend/src/stores/__tests__/article.angle.spec.ts`（仿既有 article store 测试）

- [ ] **Step 1: 写失败 Vitest** — 断言 `GenerateRequest` 含可选 `title`/`angle`；`submit` POST body 带上；`lastRequest` 保留 angle/title（`rerun` 不丢）。

- [ ] **Step 2: 跑测试确认失败**。

- [ ] **Step 3: 实现**：
  - 加 TS 类型 `export interface Angle { audience: string|null; sellpoints: string[]; tone: string|null }`。
  - `GenerateRequest` 接口加 `title?: string|null; angle?: Angle|null`。
  - `submit(req)` 把 `title`/`angle` 一并 POST（透传即可，现有 `client.post("/api/generate", req)`）。
  - `lastRequest` 已存整个 req → 自动含 angle/title；确认 `rerun()` 用 lastRequest 不剥字段。
  - （可选）加 `angleTaxonomy` state + `fetchAngleTaxonomy()`（GET /api/angle/taxonomy，缓存）。

- [ ] **Step 4: 跑测试确认通过** — `cd frontend; npx vitest run src/stores/__tests__/article.angle.spec.ts`。
- [ ] **Step 5: 提交** — `git commit -m "feat(article-store): GenerateRequest 接 title/angle + 词表拉取"`

---

### Task C2：`AnglePicker.vue` 组件

**Files:** Create `frontend/src/components/article/AnglePicker.vue`；Test `frontend/src/components/article/__tests__/AnglePicker.spec.ts`

- [ ] **Step 1: 写失败 Vitest** — mock `/api/angle/taxonomy`；断言渲染 16 人群/12 维度/3 语调/4 预设；点预设填充对应 facet（emit 出 `{audience,sellpoints,tone,template_id?}`）；空选 emit 空 angle。

- [ ] **Step 2: 跑测试确认失败**。

- [ ] **Step 3: 实现** `AnglePicker.vue`（`<script setup lang="ts">`）：
  - props：`modelValue: Angle | null`、`title: string`；emits：`update:modelValue`、`update:title`、`pick-template(id)`、`gen-titles`。
  - 拉 `fetchAngleTaxonomy()`；渲染：预设 chip 行 → 人群 `FormSelect`（含「不限」空项）→ 卖点维度多选 chips → 语调 `FormSelect` → 标题 `FormInput` +「生成候选」按钮。
  - 选预设：填 audience/sellpoints/tone，若 `template_id` 非空 emit `pick-template`。
  - 复用 `FormSelect`/`FormInput`/`FormField`；中文硬编码；teleport 组件测试加 `global:{stubs:{teleport:true}}`。

- [ ] **Step 4: 跑测试确认通过**。
- [ ] **Step 5: 提交** — `git commit -m "feat(angle-ui): AnglePicker 组件（预设/人群/卖点/语调/标题）"`

---

### Task C3：CreateArticleHero 角度 chip + query

**Files:** Modify `frontend/src/components/home/CreateArticleHero.vue`；Test 扩展其既有 spec（若有）或新建。

- [ ] **Step 1: 写失败 Vitest** — 选角度后 `takeoff()` push 的 query 含 `audience`/`sellpoints`(逗号连)/`tone`/`title`；不选则不带这些键。

- [ ] **Step 2: 跑测试确认失败**。

- [ ] **Step 3: 实现** — 加「角度」chip（与 模板/风格 平级）打开 `AnglePicker`（popover/dialog）；`takeoff()` 把 angle 扁平进 query：`audience`、`sellpoints: arr.join(",")`、`tone`、`title`；`pick-template` 回调更新 `tplId`。空值不入 query。

- [ ] **Step 4: 跑测试确认通过**。
- [ ] **Step 5: 提交** — `git commit -m "feat(home): 起飞条加角度 chip + 角度/标题进 query"`

---

### Task C4：ArticleView 重建角度 + header chip

**Files:** Modify `frontend/src/views/ArticleView.vue`；Test 扩展其既有 spec。

- [ ] **Step 1: 写失败 Vitest** — mount 带 query `audience=铲屎官&sellpoints=防缠绕技术,续航时间&tone=口语&title=...` → `takeoff()` 提交的 req 含重建的 `angle`(对象) + `title`；header 显示「角度」chip。

- [ ] **Step 2: 跑测试确认失败**。

- [ ] **Step 3: 实现** — `takeoff()`/launch 从 `route.query` 重建 `Angle`（`sellpoints` split `,`，空串→`[]`；空 facet→`null`）+ `title`，纳入 `article.submit(req)`；header 加「角度」chip（有 audience/sellpoints/tone 任一才显示，文案如「铲屎官·防缠绕·口语」）；成稿 tab「换标题」复用既有 `titleCandidates`（无需改）。

- [ ] **Step 4: 跑测试确认通过 + 前端全跑** — `cd frontend; npx vitest run`（含既有，零回归）。先 `git checkout -- frontend/package-lock.json` 若 esbuild 被改。
- [ ] **Step 5: 提交** — `git commit -m "feat(article-view): 从 query 重建角度+标题提交 + header 角度 chip"`

---

## 最终整体审查（全 Unit 完成后）

派一个 opus code-reviewer 子代理对整支 Phase 2a 做整体审查（对照 spec + 零回归 + 保守契约 + 维度键对齐 + reroll 跟随），再走 finishing-a-development-branch 收尾出 PR。重点核查：
1. `angle/title` 全空时端到端 == 今天（build_prompt 字节级 + 采样不变 + reroll 纯 filter）。
2. 维度键对齐（A6 真实库跑过，missing 为空）。
3. 注入卖点优先不丢其余维度；factcheck 白名单含 title。
4. 空池回退不让角度把文章搞空。
5. 前端 `package-lock.json` 没把 `@esbuild/*` 裁剪进提交。

---

## 自检（writing-plans 自审）

- **Spec 覆盖**：词表(A2)/Angle(A1)/派生(A3-A5)/人群过滤(B1.3)/卖点优先(B1.4)/角度指令+标题+零回归(B1.5)/持久化(B1.1-2)/reroll 跟随(B1.6)/sidecar 全链(B2.1)/路由(B2.2-3)/前端(C1-4)/真实库回归(A6+整体审查) —— spec §1-§11 各条都有对应任务。
- **占位符**：词表 16/12/4 已给全量真实值；无 TBD。
- **类型一致**：`Angle`、`effective_filters(source, angle)`、`effective_sellpoints(angle)`、`render_angle_directive(angle)`、`render_brand_facts(..., sellpoints=)`、`PromptInputs.title/angle_directive`、`AssemblyPlan.angle` 跨任务签名一致。
