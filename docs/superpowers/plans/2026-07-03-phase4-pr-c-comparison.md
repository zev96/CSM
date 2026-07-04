# 横评自动化（PR-C）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在创作台加「横评」模式：用户点选 2–4 个型号 → 后端从品牌记忆确定性拼出一篇多型号对比文章骨架 → 复用现有 finalize（注入/链/核对/评分/导出）润色成稿。

**Architecture:** 一次提交产出**一篇**对比文章（非多候选）。确定性骨架 `csm_core/comparison/compose.py` 零 LLM 从 `list[ModelScope]` 拼 5 段（引言/参数对照表/各型号亮点/实测对比/总结）。sidecar 新增 `POST /api/generate/comparison` + `submit_comparison`/`_run_comparison_job` + 一个 job_id→横评元数据 LRU 缓存；`_finalize_job` 先查横评缓存命中→由 models 重解析 scopes、跳过 plan 路径，其余（链/factcheck/completeness/导出）与常规 finalize **共用同一段代码**。前端因是单篇，几乎全复用单篇 store 流（`_subscribe`/`draftText`/`plan=null`/`finalText`/`finalize`）：只加 Hero「常规|横评」切换 + 型号多选子表单 + `submitComparison` action + ArticleView init 分支。

**Tech Stack:** Python 3.12（csm_core 纯函数 + FastAPI sidecar，pytest）、Vue 3 + Pinia + TS（vitest + vue-tsc）。

**零回归铁律：** `finalize_draft` 新增的 `scopes`/`angle_directive` 两个参数都默认 `None`，None 时与今天字节级等价；`submit`/`_run_job`/`_finalize_job` 的 plan 路径不变；前端 `submit`/`_subscribe` 不改。

**测试命令（worktree 双路径覆盖，主仓 checkout 在别的分支）：**
```powershell
# csm_core 单测
$env:PYTHONPATH="D:\CSM\.claude\worktrees\affectionate-heisenberg-9bbcf4"; & "D:\CSM\.venv\Scripts\python.exe" -X utf8 -m pytest tests/core/comparison/ -v
# sidecar 单测（双路径：worktree 覆盖主仓 editable）
$env:PYTHONPATH="D:\CSM\.claude\worktrees\affectionate-heisenberg-9bbcf4;D:\CSM\.claude\worktrees\affectionate-heisenberg-9bbcf4\sidecar"; & "D:\CSM\.venv\Scripts\python.exe" -X utf8 -m pytest sidecar/tests/test_comparison_service.py sidecar/tests/test_comparison_routes.py -v
# 前端
cd frontend; npx vitest run src/stores/__tests__/article.comparison.spec.ts src/components/home/__tests__/CreateArticleHero.spec.ts src/views/__tests__/ArticleView.comparison.spec.ts
npx vue-tsc -b   # 类型门禁；跑完 git checkout -- frontend/vite.config.js 还原 emit
```

---

## File Structure

**新建：**
- `csm_core/comparison/__init__.py` — 导出 `compose_comparison_draft`, `build_comparison_directive`。
- `csm_core/comparison/compose.py` — 确定性骨架纯函数（本 PR 最核心新逻辑）。
- `csm_core/comparison/directive.py` — 对比指令块文案（LLM 润色 directive，纯函数）。
- `tests/core/comparison/__init__.py`, `tests/core/comparison/test_compose.py`, `tests/core/comparison/test_directive.py`。
- `sidecar/csm_sidecar/services/comparison_cache.py` — job_id→横评元数据 LRU（镜像 `assembler_service` 的 plan 缓存）。
- `sidecar/tests/test_comparison_service.py`, `sidecar/tests/test_comparison_routes.py`。
- `frontend/src/components/home/ComparisonPicker.vue` — 型号多选弹层子表单。
- `frontend/src/stores/__tests__/article.comparison.spec.ts`, `frontend/src/views/__tests__/ArticleView.comparison.spec.ts`。

**修改：**
- `sidecar/csm_sidecar/services/generate_service.py` — 加 `ComparisonRequest` dataclass、`submit_comparison`、`_run_comparison_job`；给 `finalize_draft` 加 `scopes`/`angle_directive` 旁路参数；`_finalize_job` 加横评缓存分支。
- `sidecar/csm_sidecar/routes/generate.py` — 加 `ComparisonBody` + `POST /api/generate/comparison`；放宽 `finalize_generate` 的 404 预检为「plan 缓存 或 横评缓存」。
- `sidecar/csm_sidecar/services/__init__.py` — 若有 `reset_for_test` 汇总点，登记 `comparison_cache.reset_for_test`（见 Task B1 步骤）。
- `frontend/src/stores/article.ts` — 加 `ComparisonRequest` 接口 + `submitComparison` action。
- `frontend/src/components/home/CreateArticleHero.vue` — 加「常规|横评」模式切换 + 挂 `ComparisonPicker` + 横评 takeoff。
- `frontend/src/views/ArticleView.vue` — `onMounted` 加 `mode==="comparison"` 分支调 `submitComparison`；放宽自动起飞的 templateId 守卫。

---

## Unit A — csm_core/comparison（确定性骨架 + 指令块，纯函数）

### Task A1: 包骨架 + `_model_label` / `_pick_sellpoint_dims` helper

**Files:**
- Create: `csm_core/comparison/__init__.py`
- Create: `csm_core/comparison/compose.py`
- Create: `tests/core/comparison/__init__.py`
- Test: `tests/core/comparison/test_compose.py`

- [ ] **Step 1: 写失败测试**

`tests/core/comparison/__init__.py` 内容为空。`tests/core/comparison/test_compose.py`：

```python
"""横评确定性骨架 compose_comparison_draft 单测（合成 memory fixtures）。"""
from __future__ import annotations

from csm_core.brand_memory.inject import ModelScope
from csm_core.brand_memory.model import BrandModelMemory, SpecValue
from csm_core.comparison.compose import _pick_sellpoint_dims, _model_label


def _mem(brand: str, model: str, role: str, *,
         specs: dict[str, str] | None = None,
         scripts: dict[str, list[str]] | None = None,
         certs: list[str] | None = None,
         endorsements: list[str] | None = None,
         tests: dict[str, str] | None = None) -> BrandModelMemory:
    spec_objs = {}
    for f, raw in (specs or {}).items():
        nums = [float(x) for x in __import__("re").findall(r"\d+(?:\.\d+)?", raw)]
        spec_objs[f] = SpecValue(field=f, raw=raw, numbers=nums)
    return BrandModelMemory(
        brand=brand, model=model, category="吸尘器", role=role,
        specs=spec_objs, certs=certs or [], scripts=scripts or {},
        endorsements=endorsements or [], intro=[], tests=tests or {})


def _scope(brand: str, model: str, role: str, **kw) -> ModelScope:
    return ModelScope(brand=brand, model=model, role=role,
                      memory=_mem(brand, model, role, **kw))


def test_pick_sellpoint_dims_one_variant_cap_three():
    scripts = {
        "动力系统": ["强劲吸力 A", "强劲吸力 B"],
        "过滤系统": ["HEPA A"],
        "防缠绕技术": ["防缠 A"],
        "噪音大小": ["静音 A"],
    }
    picked = _pick_sellpoint_dims(scripts)
    # 每维取第 1 变体，最多 3 维（插入序）
    assert picked == [
        ("动力系统", "强劲吸力 A"),
        ("过滤系统", "HEPA A"),
        ("防缠绕技术", "防缠 A"),
    ]


def test_pick_sellpoint_dims_empty_for_competitor():
    assert _pick_sellpoint_dims({}) == []


def test_model_label_brand_space_model():
    sc = _scope("CEWEY", "CEWEYDS18", "主推")
    assert _model_label(sc) == "CEWEY CEWEYDS18"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `$env:PYTHONPATH="D:\CSM\.claude\worktrees\affectionate-heisenberg-9bbcf4"; & "D:\CSM\.venv\Scripts\python.exe" -X utf8 -m pytest tests/core/comparison/test_compose.py -v`
Expected: FAIL（`ModuleNotFoundError: csm_core.comparison`）

- [ ] **Step 3: 写最小实现**

`csm_core/comparison/__init__.py`：

```python
"""多型号横评：确定性骨架 + 对比指令块（零 LLM）。"""
from csm_core.comparison.compose import compose_comparison_draft
from csm_core.comparison.directive import build_comparison_directive

__all__ = ["compose_comparison_draft", "build_comparison_directive"]
```

`csm_core/comparison/compose.py`（先只放 helper + 空 `compose_comparison_draft` 占位，后续 Task 补节）：

```python
"""横评确定性骨架 —— 从 list[ModelScope] 拼多型号对比文章，全部来自 memory
对象、零 LLM。段落：引言 / 参数对照表 / 各型号亮点 / 实测对比 / 总结。"""
from __future__ import annotations

from csm_core.brand_memory.inject import ModelScope

_MAX_TEST_CHARS = 200
_DIM_CAP = 3


def _model_label(sc: ModelScope) -> str:
    """展示名 = 品牌 + 型号全名（memory.model 是剥品牌短名，不用于展示）。"""
    return f"{sc.brand} {sc.model}".strip()


def _pick_sellpoint_dims(
    scripts: dict[str, list[str]], *, dim_cap: int = _DIM_CAP,
) -> list[tuple[str, str]]:
    """每维取第 1 变体，最多 dim_cap 维（插入序稳定）。竞品 scripts={} → []。"""
    out: list[tuple[str, str]] = []
    for dim, variants in scripts.items():
        if variants:
            out.append((dim, variants[0]))
        if len(out) >= dim_cap:
            break
    return out


def compose_comparison_draft(
    scopes: list[ModelScope], *, keyword: str, title: str | None,
) -> str:
    """占位：Task A2–A5 逐段填充。"""
    raise NotImplementedError
```

- [ ] **Step 4: 跑测试确认通过**

Run: `$env:PYTHONPATH="D:\CSM\.claude\worktrees\affectionate-heisenberg-9bbcf4"; & "D:\CSM\.venv\Scripts\python.exe" -X utf8 -m pytest tests/core/comparison/test_compose.py -v`
Expected: 3 passed（`_pick_sellpoint_dims` / `_model_label` 三条）。

- [ ] **Step 5: Commit**

```bash
git add csm_core/comparison/ tests/core/comparison/
git commit -m "feat(comparison): 包骨架 + 卖点维度选择/型号展示名 helper"
```

---

### Task A2: 参数对照表 `_param_table`（字段并集 × 型号列，— 占位）

**Files:**
- Modify: `csm_core/comparison/compose.py`
- Test: `tests/core/comparison/test_compose.py`

- [ ] **Step 1: 写失败测试**（追加到 test_compose.py）

```python
from csm_core.comparison.compose import _param_table


def test_param_table_union_columns_and_placeholder():
    a = _scope("CEWEY", "CEWEYDS18", "主推",
               specs={"吸力(AW)": "220", "转速": "12万转"})
    b = _scope("Dyson", "V12", "竞品",
               specs={"吸力(AW)": "150", "重量": "2.2kg"})
    out = _param_table([a, b])
    lines = out.splitlines()
    assert lines[0] == "## 参数对照"
    # 表头：参数 + 两个型号展示名
    assert lines[2] == "| 参数 | CEWEY CEWEYDS18 | Dyson V12 |"
    assert lines[3] == "| --- | --- | --- |"
    # 字段并集按首现序：吸力(AW)（a 有 b 有）、转速（a 有 b 无→—）、重量（a 无→—）
    assert "| 吸力(AW) | 220 | 150 |" in out
    assert "| 转速 | 12万转 | — |" in out
    assert "| 重量 | — | 2.2kg |" in out


def test_param_table_empty_when_no_specs():
    a = _scope("CEWEY", "CEWEYDS18", "主推")
    assert _param_table([a]) == ""
```

- [ ] **Step 2: 跑测试确认失败**

Run: `... -m pytest tests/core/comparison/test_compose.py::test_param_table_union_columns_and_placeholder -v`
Expected: FAIL（`_param_table` 未定义）。

- [ ] **Step 3: 写实现**（在 compose.py 的 `compose_comparison_draft` 之前插入）

```python
def _param_table(scopes: list[ModelScope]) -> str:
    """字段并集（按各型号插入序首现）× 型号列 markdown 表；缺失填 —。"""
    fields: list[str] = []
    seen: set[str] = set()
    for sc in scopes:
        for f in sc.memory.specs.keys():
            if f not in seen:
                seen.add(f)
                fields.append(f)
    if not fields:
        return ""
    labels = [_model_label(sc) for sc in scopes]
    header = "| 参数 | " + " | ".join(labels) + " |"
    sep = "| --- | " + " | ".join("---" for _ in scopes) + " |"
    rows = [header, sep]
    for f in fields:
        cells = []
        for sc in scopes:
            sv = sc.memory.specs.get(f)
            cells.append(sv.raw if sv is not None else "—")
        rows.append(f"| {f} | " + " | ".join(cells) + " |")
    return "## 参数对照\n\n" + "\n".join(rows)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `... -m pytest tests/core/comparison/test_compose.py -v`
Expected: 全 passed。

- [ ] **Step 5: Commit**

```bash
git add csm_core/comparison/compose.py tests/core/comparison/test_compose.py
git commit -m "feat(comparison): 参数对照表（字段并集×型号列 + — 占位）"
```

---

### Task A3: 各型号亮点 `_highlights` + 实测对比 `_test_comparison`

**Files:**
- Modify: `csm_core/comparison/compose.py`
- Test: `tests/core/comparison/test_compose.py`

- [ ] **Step 1: 写失败测试**（追加）

```python
from csm_core.comparison.compose import _highlights, _test_comparison


def test_highlights_one_variant_cap3_plus_certs():
    a = _scope("CEWEY", "CEWEYDS18", "主推",
               scripts={"动力系统": ["强劲吸力"], "过滤系统": ["HEPA"],
                        "防缠绕技术": ["防缠"], "噪音大小": ["静音"]},
               certs=["CE", "FCC"])
    out = _highlights([a])
    assert out.startswith("## 各型号亮点")
    assert "### CEWEY CEWEYDS18" in out
    assert "- 动力系统：强劲吸力" in out
    assert "- 过滤系统：HEPA" in out
    assert "- 防缠绕技术：防缠" in out
    assert "噪音大小" not in out          # cap 3 维，第 4 维被截
    assert "- 认证：CE、FCC" in out


def test_highlights_omitted_when_no_scripts_no_certs():
    a = _scope("Dyson", "V12", "竞品")   # 竞品无 scripts、无 certs
    assert _highlights([a]) == ""


def test_test_comparison_common_topics_intersection_and_truncation():
    long_body = "噪音实测：" + "很安静" * 100     # >200 字
    a = _scope("CEWEY", "CEWEYDS18", "主推",
               tests={"噪音测试": long_body, "尘杯测试": "0.6L"})
    b = _scope("Dyson", "V12", "竞品",
               tests={"噪音测试": "略吵", "续航测试": "60min"})
    out = _test_comparison([a, b])
    assert out.startswith("## 实测对比")
    assert "### 噪音测试" in out          # 共有话题
    assert "尘杯测试" not in out          # 非共有
    assert "续航测试" not in out
    # 主推正文截断到 200 字
    assert len([ln for ln in out.splitlines() if ln.startswith("- CEWEY CEWEYDS18：")][0]) <= 200 + len("- CEWEY CEWEYDS18：")


def test_test_comparison_omitted_when_no_common_topic():
    a = _scope("CEWEY", "CEWEYDS18", "主推", tests={"噪音测试": "安静"})
    b = _scope("Dyson", "V12", "竞品", tests={"续航测试": "60min"})
    assert _test_comparison([a, b]) == ""
```

- [ ] **Step 2: 跑测试确认失败**

Run: `... -m pytest tests/core/comparison/test_compose.py::test_highlights_one_variant_cap3_plus_certs -v`
Expected: FAIL（`_highlights` 未定义）。

- [ ] **Step 3: 写实现**（插入 compose.py）

```python
def _highlights(scopes: list[ModelScope]) -> str:
    """每型号一块：卖点话术（每维 1 变体、≤3 维）+ 认证行。空块（无卖点无认证）跳过。"""
    blocks: list[str] = []
    for sc in scopes:
        m = sc.memory
        lines = [f"### {_model_label(sc)}"]
        for dim, variant in _pick_sellpoint_dims(m.scripts):
            lines.append(f"- {dim}：{variant}")
        if m.certs:
            lines.append(f"- 认证：{'、'.join(m.certs)}")
        if len(lines) > 1:                       # 有内容才收
            blocks.append("\n".join(lines))
    if not blocks:
        return ""
    return "## 各型号亮点\n\n" + "\n\n".join(blocks)


def _test_comparison(scopes: list[ModelScope]) -> str:
    """共有测试话题（有 tests 的型号取 keys 交集，≥2 个型号才成立）逐话题
    各型号摘要（每型号 ≤200 字）；无共有话题 → 整节省略。"""
    with_tests = [sc for sc in scopes if sc.memory.tests]
    if len(with_tests) < 2:
        return ""
    common = set(with_tests[0].memory.tests.keys())
    for sc in with_tests[1:]:
        common &= set(sc.memory.tests.keys())
    if not common:
        return ""
    ordered = [t for t in with_tests[0].memory.tests.keys() if t in common]
    blocks: list[str] = []
    for topic in ordered:
        lines = [f"### {topic}"]
        for sc in with_tests:
            body = (sc.memory.tests.get(topic) or "").strip()
            if body:
                lines.append(f"- {_model_label(sc)}：{body[:_MAX_TEST_CHARS]}")
        blocks.append("\n".join(lines))
    return "## 实测对比\n\n" + "\n\n".join(blocks)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `... -m pytest tests/core/comparison/test_compose.py -v`
Expected: 全 passed。

- [ ] **Step 5: Commit**

```bash
git add csm_core/comparison/compose.py tests/core/comparison/test_compose.py
git commit -m "feat(comparison): 各型号亮点 + 实测对比（共有话题求交/摘要截断）"
```

---

### Task A4: 总结 `_summary`（主推背书 + 事实领先项，中性措辞）

**Files:**
- Modify: `csm_core/comparison/compose.py`
- Test: `tests/core/comparison/test_compose.py`

- [ ] **Step 1: 写失败测试**（追加）

```python
from csm_core.comparison.compose import _summary, _leading_fields


def test_leading_fields_unique_or_numerically_distinct():
    a = _scope("CEWEY", "CEWEYDS18", "主推",
               specs={"吸力(AW)": "220", "转速": "12万转", "认证检测": "CE"})
    b = _scope("Dyson", "V12", "竞品",
               specs={"吸力(AW)": "150"})
    # 吸力 220≠150 → 领先项；转速 b 无 → 独有项；认证无数字 → 跳过
    fields = _leading_fields(a.memory.specs, [b.memory.specs])
    keys = [f for f, _ in fields]
    assert "吸力(AW)" in keys
    assert "转速" in keys
    assert "认证检测" not in keys


def test_summary_lists_endorsements_and_leading_neutral():
    a = _scope("CEWEY", "CEWEYDS18", "主推",
               specs={"吸力(AW)": "220"}, endorsements=["十年老牌"])
    b = _scope("Dyson", "V12", "竞品", specs={"吸力(AW)": "150"})
    out = _summary([a, b])
    assert out.startswith("## 总结")
    assert "- 十年老牌" in out
    assert "吸力(AW)" in out and "220" in out      # 事实陈列
    # 中性：不出现贬损/比较级断言词
    assert "秒杀" not in out and "碾压" not in out


def test_summary_empty_without_primary():
    b = _scope("Dyson", "V12", "竞品", specs={"吸力(AW)": "150"})
    assert _summary([b]) == ""
```

- [ ] **Step 2: 跑测试确认失败**

Run: `... -m pytest tests/core/comparison/test_compose.py::test_leading_fields_unique_or_numerically_distinct -v`
Expected: FAIL。

- [ ] **Step 3: 写实现**（插入 compose.py）

```python
def _leading_fields(
    primary_specs: dict, competitor_specs: list[dict],
) -> list[tuple[str, str]]:
    """主推「独有或数值有别」的数值型 spec 字段（中性事实，不判方向优劣）。

    - 只看有 numbers 的字段（认证/占位跳过）；
    - 竞品都没这个字段 → 独有，收；
    - 竞品有但主推 max 与每个竞品 max 都不等 → 数值有别，收。"""
    out: list[tuple[str, str]] = []
    for field, sv in primary_specs.items():
        if not sv.numbers:
            continue
        comp_nums = [
            cs[field].numbers for cs in competitor_specs
            if field in cs and cs[field].numbers
        ]
        p_max = max(sv.numbers)
        if not comp_nums:
            out.append((field, sv.raw))
        elif all(p_max != max(cn) for cn in comp_nums):
            out.append((field, sv.raw))
    return out


def _summary(scopes: list[ModelScope]) -> str:
    """主推型号背书（按品牌去重）+ 事实领先/独有 spec 陈列（中性）。无主推 → 空。

    「突出主推优势」的价值判断留给 LLM 润色的对比指令块；本节只陈列事实。"""
    primary = [sc for sc in scopes if sc.role == "主推"]
    if not primary:
        return ""
    competitor_specs = [sc.memory.specs for sc in scopes if sc.role != "主推"]
    lines = ["## 总结"]
    seen_brand: set[str] = set()
    for sc in primary:
        if sc.brand in seen_brand:
            continue
        seen_brand.add(sc.brand)
        for e in sc.memory.endorsements:
            lines.append(f"- {e}")
    for sc in primary:
        for field, raw in _leading_fields(sc.memory.specs, competitor_specs):
            lines.append(f"- {_model_label(sc)} 的 {field}：{raw}")
    return "\n".join(lines)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `... -m pytest tests/core/comparison/test_compose.py -v`
Expected: 全 passed。

- [ ] **Step 5: Commit**

```bash
git add csm_core/comparison/compose.py tests/core/comparison/test_compose.py
git commit -m "feat(comparison): 总结节（主推背书 + 事实领先/独有项，中性）"
```

---

### Task A5: 组装 `compose_comparison_draft`（引言 + 拼全段）

**Files:**
- Modify: `csm_core/comparison/compose.py`
- Test: `tests/core/comparison/test_compose.py`

- [ ] **Step 1: 写失败测试**（追加）

```python
from csm_core.comparison.compose import compose_comparison_draft


def test_compose_full_draft_sections_present_and_ordered():
    a = _scope("CEWEY", "CEWEYDS18", "主推",
               specs={"吸力(AW)": "220"}, scripts={"动力系统": ["强劲"]},
               certs=["CE"], endorsements=["老牌"], tests={"噪音测试": "安静"})
    b = _scope("Dyson", "V12", "竞品",
               specs={"吸力(AW)": "150"}, tests={"噪音测试": "略吵"})
    out = compose_comparison_draft([a, b], keyword="无线吸尘器怎么选", title=None)
    # 引言点名两型号 + 关键词
    assert "无线吸尘器怎么选" in out
    assert "CEWEY CEWEYDS18" in out and "Dyson V12" in out
    # 五段按序
    i_param = out.index("## 参数对照")
    i_high = out.index("## 各型号亮点")
    i_test = out.index("## 实测对比")
    i_sum = out.index("## 总结")
    assert i_param < i_high < i_test < i_sum


def test_compose_title_prepended_as_h1():
    a = _scope("CEWEY", "CEWEYDS18", "主推", specs={"吸力(AW)": "220"})
    b = _scope("Dyson", "V12", "竞品", specs={"吸力(AW)": "150"})
    out = compose_comparison_draft([a, b], keyword="吸尘器", title="三款横评")
    assert out.startswith("# 三款横评\n\n")


def test_compose_omits_empty_sections():
    # 无 scripts/certs/tests → 亮点、实测节整块不出现，但参数/总结在
    a = _scope("CEWEY", "CEWEYDS18", "主推", specs={"吸力(AW)": "220"})
    b = _scope("Dyson", "V12", "竞品", specs={"吸力(AW)": "150"})
    out = compose_comparison_draft([a, b], keyword="吸尘器", title=None)
    assert "## 参数对照" in out
    assert "## 各型号亮点" not in out
    assert "## 实测对比" not in out
    assert "## 总结" in out
```

- [ ] **Step 2: 跑测试确认失败**

Run: `... -m pytest tests/core/comparison/test_compose.py::test_compose_full_draft_sections_present_and_ordered -v`
Expected: FAIL（`compose_comparison_draft` 现 raise NotImplementedError）。

- [ ] **Step 3: 写实现**（替换 compose.py 里占位的 `compose_comparison_draft`；`_intro` 新增在其上）

```python
def _intro(scopes: list[ModelScope], keyword: str, title: str | None) -> str:
    names = "、".join(_model_label(sc) for sc in scopes)
    kw = keyword.strip() or "这几款产品"
    lead = f"{kw}？本文把 {names} 放在一起，从参数、亮点到实测逐项对比。"
    if title:
        return f"# {title}\n\n{lead}"
    return lead


def compose_comparison_draft(
    scopes: list[ModelScope], *, keyword: str, title: str | None,
) -> str:
    """多型号对比文章骨架（零 LLM）。空节自动省略。"""
    parts = [
        _intro(scopes, keyword, title),
        _param_table(scopes),
        _highlights(scopes),
        _test_comparison(scopes),
        _summary(scopes),
    ]
    return "\n\n".join(p for p in parts if p)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `... -m pytest tests/core/comparison/test_compose.py -v`
Expected: 全 passed。

- [ ] **Step 5: Commit**

```bash
git add csm_core/comparison/compose.py tests/core/comparison/test_compose.py
git commit -m "feat(comparison): compose_comparison_draft 组装五段（空节省略/标题 H1）"
```

---

### Task A6: 对比指令块 `build_comparison_directive`

**Files:**
- Create: `csm_core/comparison/directive.py`
- Test: `tests/core/comparison/test_directive.py`

- [ ] **Step 1: 写失败测试**

`tests/core/comparison/test_directive.py`：

```python
from csm_core.comparison.directive import build_comparison_directive


def test_directive_names_primary_and_core_constraints():
    d = build_comparison_directive(primary_label="CEWEY CEWEYDS18", tone=None)
    assert "横评" in d
    assert "CEWEY CEWEYDS18" in d           # 结论突出主推
    assert "不得使用贬损" in d
    assert "照抄" in d                       # 参数不得改写


def test_directive_merges_tone():
    d = build_comparison_directive(primary_label="CEWEY CEWEYDS18", tone="口语")
    assert "口语" in d


def test_directive_without_primary_omits_primary_clause():
    d = build_comparison_directive(primary_label=None, tone=None)
    assert "横评" in d
    # 无主推时不硬塞「突出 None」
    assert "None" not in d
```

- [ ] **Step 2: 跑测试确认失败**

Run: `... -m pytest tests/core/comparison/test_directive.py -v`
Expected: FAIL（模块不存在）。

- [ ] **Step 3: 写实现**

`csm_core/comparison/directive.py`：

```python
"""对比指令块 —— 经 angle_directive 通道注入 LLM 润色 pass 的一段文本。"""
from __future__ import annotations


def build_comparison_directive(*, primary_label: str | None, tone: str | None) -> str:
    """横评润色指令：客观对比 + 不贬损 + 参数照抄 + 结论突出主推（若有）+ 语调。"""
    parts = [
        "这是一篇多型号横评文章。请基于给定事实客观对比各型号，"
        "不得使用贬损性措辞，对比表中的参数一律照抄、不得改写或杜撰。",
    ]
    if primary_label:
        parts.append(f"结论段请自然突出 {primary_label} 的事实性优势，但不夸大、不虚构。")
    if tone:
        parts.append(f"整体语调：{tone}。")
    return "".join(parts)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `... -m pytest tests/core/comparison/ -v`
Expected: 全 passed（compose + directive）。

- [ ] **Step 5: Commit**

```bash
git add csm_core/comparison/directive.py tests/core/comparison/test_directive.py
git commit -m "feat(comparison): 对比指令块 build_comparison_directive（含主推/语调）"
```

---

## Unit B — sidecar 接线（横评缓存 + service + 路由 + finalize 旁路）

### Task B1: 横评元数据 LRU 缓存 `comparison_cache.py`

**Files:**
- Create: `sidecar/csm_sidecar/services/comparison_cache.py`
- Test: `sidecar/tests/test_comparison_service.py`

- [ ] **Step 1: 写失败测试**

`sidecar/tests/test_comparison_service.py`：

```python
"""横评元数据 LRU 缓存单测（镜像 assembler_service 的 plan 缓存范式）。"""
from __future__ import annotations

from csm_sidecar.services import comparison_cache as cc


def test_cache_put_get_roundtrip():
    cc.reset_for_test()
    cc.cache_comparison("job1", models=["A", "B"], category="吸尘器",
                        keyword="k", title="t", tone="口语",
                        skill_chain=["s1"], contract_mode="conservative")
    e = cc.get_comparison("job1")
    assert e is not None
    assert e.models == ["A", "B"]
    assert e.category == "吸尘器"
    assert e.keyword == "k"
    assert e.tone == "口语"
    assert e.skill_chain == ["s1"]
    assert e.contract_mode == "conservative"


def test_cache_miss_returns_none():
    cc.reset_for_test()
    assert cc.get_comparison("nope") is None


def test_cache_lru_evicts_oldest_over_capacity():
    cc.reset_for_test()
    for i in range(cc.MAX_CACHE + 5):
        cc.cache_comparison(f"j{i}", models=["A", "B"], category="吸尘器",
                            keyword="k", title=None, tone=None,
                            skill_chain=None, contract_mode=None)
    assert cc.get_comparison("j0") is None            # 最旧被淘汰
    assert cc.get_comparison(f"j{cc.MAX_CACHE + 4}") is not None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `$env:PYTHONPATH="D:\CSM\.claude\worktrees\affectionate-heisenberg-9bbcf4;D:\CSM\.claude\worktrees\affectionate-heisenberg-9bbcf4\sidecar"; & "D:\CSM\.venv\Scripts\python.exe" -X utf8 -m pytest sidecar/tests/test_comparison_service.py -v`
Expected: FAIL（模块不存在）。

- [ ] **Step 3: 写实现**

`sidecar/csm_sidecar/services/comparison_cache.py`：

```python
"""job_id → 横评元数据 LRU 缓存（镜像 assembler_service 的 plan 缓存）。

_finalize_job 命中此缓存 → 由 models 重解析 scopes、跳过 plan 路径。"""
from __future__ import annotations

import threading
from collections import OrderedDict
from dataclasses import dataclass


@dataclass
class ComparisonMeta:
    models: list[str]
    category: str
    keyword: str
    title: str | None
    tone: str | None
    skill_chain: list[str] | None
    contract_mode: str | None


_cache: "OrderedDict[str, ComparisonMeta]" = OrderedDict()
_lock = threading.Lock()
MAX_CACHE = 50


def cache_comparison(
    job_id: str, *, models: list[str], category: str, keyword: str,
    title: str | None, tone: str | None, skill_chain: list[str] | None,
    contract_mode: str | None,
) -> None:
    with _lock:
        _cache[job_id] = ComparisonMeta(
            models=models, category=category, keyword=keyword, title=title,
            tone=tone, skill_chain=skill_chain, contract_mode=contract_mode)
        _cache.move_to_end(job_id)
        while len(_cache) > MAX_CACHE:
            _cache.popitem(last=False)


def get_comparison(job_id: str) -> ComparisonMeta | None:
    with _lock:
        e = _cache.get(job_id)
        if e is not None:
            _cache.move_to_end(job_id)
        return e


def reset_for_test() -> None:
    with _lock:
        _cache.clear()
```

- [ ] **Step 4: 跑测试确认通过**

Run: `... -m pytest sidecar/tests/test_comparison_service.py -v`
Expected: 3 passed。

- [ ] **Step 5: Commit**

```bash
git add sidecar/csm_sidecar/services/comparison_cache.py sidecar/tests/test_comparison_service.py
git commit -m "feat(comparison): job_id→横评元数据 LRU 缓存"
```

---

### Task B2: `finalize_draft` 加 `scopes`/`angle_directive` 旁路参数（零回归）

**Files:**
- Modify: `sidecar/csm_sidecar/services/generate_service.py`（`finalize_draft` 签名与两处内部用法）
- Test: `sidecar/tests/test_comparison_service.py`

**背景（recon 确认）**：`finalize_draft` 现硬编码 `scopes = resolve_scopes(plan, ...)` 且 `run_chain(..., angle_directive=render_angle_directive(angle), ...)`。加两个默认 None 的旁路参数：`scopes` 非 None 则跳过内部 resolve；`angle_directive` 非 None 则覆盖 `render_angle_directive(angle)`。

- [ ] **Step 1: 写失败测试**（追加到 test_comparison_service.py，用 monkeypatch 直验旁路）

```python
import csm_sidecar.services.generate_service as gs


def test_finalize_draft_scopes_bypass_skips_resolve(monkeypatch):
    """传入 scopes 时不再调 resolve_scopes（横评路径的关键旁路）。"""
    called = {"resolve": 0, "chain_directive": None}

    def fake_resolve(*a, **k):
        called["resolve"] += 1
        return []
    monkeypatch.setattr(gs, "resolve_scopes", fake_resolve)

    class _State:
        final_text = "X"
        passes = []
    def fake_run_chain(job_id, steps, **kw):
        called["chain_directive"] = kw.get("angle_directive")
        return _State()
    monkeypatch.setattr(gs.chain_service, "run_chain", fake_run_chain)
    monkeypatch.setattr(gs, "render_brand_facts", lambda *a, **k: "facts")
    monkeypatch.setattr(gs.pricing, "chain_cost", lambda *a, **k: {})
    monkeypatch.setattr(gs, "_maybe_block_for_factcheck", lambda *a, **k: False)
    monkeypatch.setattr(gs.bus, "publish", lambda *a, **k: None)

    class _Cfg:
        class brand_memory:
            inject = True; factcheck = False; own_brands = []
            inject_variant_cap = 3; inject_endorsement_cap = 5
        class contract: mode = "conservative"
        class pricing: pass
    prebuilt = [object()]
    gs.finalize_draft(
        "job1", chain_steps=[], draft="d", plan=None, index=None, registry=None,
        category="吸尘器", keyword="k", title=None, angle=None,
        provider=None, model=None, cfg=_Cfg, out_dir=__import__("pathlib").Path("."),
        checkpoint=lambda: None, on_pass=lambda p: None,
        stage_index=0, stage_total=1, contract_mode="conservative",
        scopes=prebuilt, angle_directive="横评指令",
    )
    assert called["resolve"] == 0                 # 旁路：未调 resolve_scopes
    assert called["chain_directive"] == "横评指令" # 旁路：directive 覆盖生效
```

- [ ] **Step 2: 跑测试确认失败**

Run: `... -m pytest sidecar/tests/test_comparison_service.py::test_finalize_draft_scopes_bypass_skips_resolve -v`
Expected: FAIL（`finalize_draft` 无 `scopes`/`angle_directive` 关键字 → TypeError）。

- [ ] **Step 3: 改实现**（`generate_service.py` `finalize_draft`）

签名末尾追加两参数（在 `contract_mode: str,` 之后）：

```python
    contract_mode: str,
    scopes: list | None = None,
    angle_directive: str | None = None,
) -> FinalizeOutcome:
```

把内部 scopes 解析改为「未预置才解析」——将现有：

```python
    cfg_bm = cfg.brand_memory
    scopes: list = []
    brand_facts: str | None = None
    if cfg_bm.inject or cfg_bm.factcheck:
        scopes = resolve_scopes(
            plan, index, registry,
            own_brands=set(cfg_bm.own_brands),
            category=category,
        )
        if scopes:
```

改为：

```python
    cfg_bm = cfg.brand_memory
    brand_facts: str | None = None
    if scopes is None:
        scopes = []
        if cfg_bm.inject or cfg_bm.factcheck:
            scopes = resolve_scopes(
                plan, index, registry,
                own_brands=set(cfg_bm.own_brands),
                category=category,
            )
    if scopes:
```

（注意：把原 `if scopes:` 从 `if cfg_bm.inject or cfg_bm.factcheck:` 块内**平移到外层**——预置 scopes 时也要渲染 brand_facts。）

把 `run_chain(..., angle_directive=render_angle_directive(angle), ...)` 改为：

```python
        angle_directive=(angle_directive if angle_directive is not None
                         else render_angle_directive(angle)),
```

- [ ] **Step 4: 跑测试确认通过（含零回归）**

Run: `... -m pytest sidecar/tests/test_comparison_service.py sidecar/tests/test_finalize_draft.py sidecar/tests/test_generate_contract.py -v`
Expected: 新旁路测试 passed；既有 finalize/contract 测试**全绿**（默认 None → 今天行为）。

- [ ] **Step 5: Commit**

```bash
git add sidecar/csm_sidecar/services/generate_service.py sidecar/tests/test_comparison_service.py
git commit -m "feat(comparison): finalize_draft 加 scopes/angle_directive 旁路（默认 None 零回归）"
```

---

### Task B3: `submit_comparison` + `_run_comparison_job`（组稿 + 缓存 + draft_only）

**Files:**
- Modify: `sidecar/csm_sidecar/services/generate_service.py`
- Test: `sidecar/tests/test_comparison_service.py`

- [ ] **Step 1: 写失败测试**（追加；仿 test_batch_scoring 的 mock client 装置，驱动 SSE 事件断言）

```python
def test_run_comparison_job_emits_skeleton_and_caches(monkeypatch, tmp_path):
    """<2 有效型号 → error；≥2 → assembly(draft, plan=None, comparison) + draft_only done + 缓存。"""
    from csm_sidecar.services import comparison_cache as cc
    cc.reset_for_test()

    events = []
    monkeypatch.setattr(gs.bus, "publish",
                        lambda job, kind, **d: events.append((kind, d)))
    finished = {}
    monkeypatch.setattr(gs.bus, "finish",
                        lambda job, **d: finished.update(d))

    # 假 index/registry/scope 解析：A=主推 B=竞品，各带一个 spec
    monkeypatch.setattr(gs.vault_service, "get", lambda root: object())
    monkeypatch.setattr(gs, "build_brand_registry", lambda root: object())

    from csm_core.brand_memory.inject import ModelScope
    from csm_core.brand_memory.model import BrandModelMemory, SpecValue
    def _mk(model, role):
        return ModelScope(brand="Br", model=model, role=role,
                          memory=BrandModelMemory(brand="Br", model=model,
                              category="吸尘器", role=role,
                              specs={"吸力": SpecValue(field="吸力", raw="200", numbers=[200.0])}))
    monkeypatch.setattr(gs, "_resolve_comparison_scopes",
                        lambda models, index, registry, category, own_brands:
                        [_mk(m, "主推" if i == 0 else "竞品") for i, m in enumerate(models)])

    class _Cfg:
        vault_root = str(tmp_path); out_dir = str(tmp_path)
        user_product = "吸尘器"; export_format = "markdown"
        class brand_memory: own_brands = ["Br"]; inject = False; factcheck = False
        class contract: mode = "conservative"
    monkeypatch.setattr(gs.config_service, "load", lambda: _Cfg)

    req = gs.ComparisonRequest(models=["A", "B"], keyword="怎么选",
                               title=None, tone=None, skill_chain=None,
                               contract_mode=None, draft_only=True)
    gs._run_comparison_job("jobC", req)

    kinds = [k for k, _ in events]
    assert "assembly" in kinds
    asm = dict(events)["assembly"]
    assert asm["plan"] is None
    assert "## 参数对照" in asm["draft"]
    assert asm["comparison"] == {"models": ["A", "B"]}
    assert finished.get("document") is None       # draft_only
    assert cc.get_comparison("jobC").models == ["A", "B"]


def test_run_comparison_job_too_few_models_errors(monkeypatch, tmp_path):
    errs = {}
    monkeypatch.setattr(gs.bus, "publish", lambda *a, **k: None)
    monkeypatch.setattr(gs.bus, "fail", lambda job, error, **d: errs.update({"error": error}))
    monkeypatch.setattr(gs.vault_service, "get", lambda root: object())
    monkeypatch.setattr(gs, "build_brand_registry", lambda root: object())
    monkeypatch.setattr(gs, "_resolve_comparison_scopes",
                        lambda *a, **k: [])       # 全部无法识别
    class _Cfg:
        vault_root = str(tmp_path); out_dir = str(tmp_path); user_product = "吸尘器"
        class brand_memory: own_brands = []
        class contract: mode = "conservative"
    monkeypatch.setattr(gs.config_service, "load", lambda: _Cfg)
    req = gs.ComparisonRequest(models=["X"], keyword="k", title=None, tone=None,
                               skill_chain=None, contract_mode=None, draft_only=True)
    gs._run_comparison_job("jobE", req)
    assert "型号" in errs["error"]                 # 中文原因
```

- [ ] **Step 2: 跑测试确认失败**

Run: `... -m pytest sidecar/tests/test_comparison_service.py::test_run_comparison_job_emits_skeleton_and_caches -v`
Expected: FAIL（`ComparisonRequest`/`submit_comparison`/`_run_comparison_job`/`_resolve_comparison_scopes` 未定义）。

- [ ] **Step 3: 写实现**（`generate_service.py`；imports 顶部加 `from csm_core.comparison import compose_comparison_draft, build_comparison_directive`、`from csm_core.brand_memory.identity import parse_brand_model`、`from csm_core.brand_memory.inject import ModelScope`、`from csm_core.brand_memory.resolver import resolve_memory`、`from . import comparison_cache`）

在 `GenerateRequest`/`FinalizeRequest` dataclass 附近加：

```python
@dataclass
class ComparisonRequest:
    models: list[str]
    keyword: str = ""
    title: str | None = None
    tone: str | None = None
    skill_chain: list[str] | None = None
    contract_mode: str | None = None
    draft_only: bool = True
    provider: str | None = None
    model: str | None = None
```

加型号解析 helper（镜像 `brand_memory_service._resolve_one`，保序去重）：

```python
def _resolve_comparison_scopes(
    models: list[str], index, registry, category: str, own_brands: set[str],
) -> list[ModelScope]:
    """点名型号 → ModelScope（registry 不识别的跳过；保序去重）。"""
    scopes: list[ModelScope] = []
    seen: set[str] = set()
    for model_full in models:
        if model_full in seen:
            continue
        seen.add(model_full)
        brand = registry.brand_of(model_full)
        if brand is None:
            continue
        parsed = parse_brand_model(model_full)
        resolver_model = parsed[1] if parsed is not None else model_full
        mem = resolve_memory(brand, resolver_model, category, index,
                             own_brands=own_brands)
        scopes.append(ModelScope(brand=brand, model=model_full,
                                 role=mem.role, memory=mem))
    return scopes
```

加 submit + worker：

```python
def submit_comparison(req: ComparisonRequest) -> str:
    job_id = bus.create_job()
    with _state_lock:
        _live.add(job_id)
    _get_executor().submit(_run_comparison_job, job_id, req)
    return job_id


def _run_comparison_job(job_id: str, req: ComparisonRequest) -> None:
    """横评 worker：扫库 → 解析型号 → 确定性组稿 → 缓存元数据 → draft_only 收尾
    （或全量 finalize）。事件 shape 与 _run_job 对齐，plan 恒 None。"""
    try:
        cfg = config_service.load()
        if not cfg.vault_root:
            raise ValueError("AppConfig.vault_root is unset")
        if not cfg.out_dir:
            raise ValueError("AppConfig.out_dir is unset")
        vault_root = Path(cfg.vault_root)
        out_dir = Path(cfg.out_dir)
        category = cfg.user_product or "吸尘器"
        own_brands = set(cfg.brand_memory.own_brands)

        _checkpoint(job_id)
        bus.publish(job_id, "stage", stage="扫描资料库", index=0, total=3)
        index = vault_service.get(vault_root)
        registry = build_brand_registry(vault_root)
        scopes = _resolve_comparison_scopes(
            req.models, index, registry, category, own_brands)
        if len(scopes) < 2:
            raise ValueError(
                f"横评需至少 2 个可识别型号，实得 {len(scopes)} 个"
                f"（型号是否在素材库/registry 里？）")

        _checkpoint(job_id)
        bus.publish(job_id, "stage", stage="组装对比稿", index=1, total=3)
        draft = compose_comparison_draft(
            scopes, keyword=req.keyword, title=req.title)
        resolved_models = [sc.model for sc in scopes]
        bus.publish(job_id, "assembly", plan=None, draft=draft,
                    comparison={"models": resolved_models})

        comparison_cache.cache_comparison(
            job_id, models=resolved_models, category=category,
            keyword=req.keyword, title=req.title, tone=req.tone,
            skill_chain=req.skill_chain, contract_mode=req.contract_mode)

        if req.draft_only:
            bus.finish(job_id, draft=draft, plan=None, document=None,
                       comparison={"models": resolved_models})
            return

        # 非 draft_only（少见）：直接一把 finalize + 导出。
        _run_comparison_finalize(
            job_id, req=req, draft=draft, scopes=scopes, cfg=cfg,
            out_dir=out_dir, keyword=req.keyword, title=req.title,
            category=category)
    except _CancelledGenerate:
        logger.info("comparison job %s cancelled by user", job_id)
        bus.fail(job_id, error="cancelled", cancelled=True)
    except Exception as e:
        logger.exception("comparison job %s failed", job_id)
        bus.fail(job_id, error=f"{type(e).__name__}: {e}")
    finally:
        with _state_lock:
            _live.discard(job_id)
            _cancelled.discard(job_id)
```

（`_run_comparison_finalize` 在 Task B4 定义；本 Task 若 draft_only 路径不触达它，可先放一个 `raise NotImplementedError` 占位或直接在 B4 补——为让 B3 测试通过，draft_only=True 不进该分支，占位可接受。）先加占位：

```python
def _run_comparison_finalize(job_id, *, req, draft, scopes, cfg, out_dir,
                             keyword, title, category):
    raise NotImplementedError  # Task B4
```

- [ ] **Step 4: 跑测试确认通过**

Run: `... -m pytest sidecar/tests/test_comparison_service.py -v`
Expected: 全 passed（缓存 3 + 旁路 1 + 组稿 2）。

- [ ] **Step 5: Commit**

```bash
git add sidecar/csm_sidecar/services/generate_service.py sidecar/tests/test_comparison_service.py
git commit -m "feat(comparison): submit_comparison + _run_comparison_job（组稿/缓存/draft_only）"
```

---

### Task B4: `_finalize_job` 横评分支 + `_run_comparison_finalize`

**Files:**
- Modify: `sidecar/csm_sidecar/services/generate_service.py`
- Test: `sidecar/tests/test_comparison_service.py`

**设计**：`_finalize_job` 开头先查 `comparison_cache.get_comparison(job_id)`。命中 → 走横评分支：新鲜 index/registry → `_resolve_comparison_scopes(meta.models,...)` → 合成 plan（`AssemblyPlan(keyword=meta.keyword, template_id="__comparison__", seed=0, core_keyword=meta.keyword)`）→ `finalize_draft(scopes=scopes, angle_directive=build_comparison_directive(...), plan=synthetic, ...)` → 导出 + finish。未命中 → 现有 plan 路径（零回归）。

- [ ] **Step 1: 写失败测试**（追加）

```python
def test_finalize_job_comparison_branch_uses_models(monkeypatch, tmp_path):
    from csm_sidecar.services import comparison_cache as cc
    cc.reset_for_test()
    cc.cache_comparison("jobF", models=["A", "B"], category="吸尘器",
                        keyword="怎么选", title=None, tone="口语",
                        skill_chain=None, contract_mode="conservative")

    seen = {}
    def fake_finalize_draft(job_id, **kw):
        seen["scopes_len"] = len(kw["scopes"]) if kw.get("scopes") else 0
        seen["directive"] = kw.get("angle_directive")
        seen["plan_keyword"] = kw["plan"].keyword
        class _O: final_text="FT"; passes=[]; blocked=False; cost={}; completeness=None
        return _O()
    monkeypatch.setattr(gs, "finalize_draft", fake_finalize_draft)
    monkeypatch.setattr(gs, "_resolve_comparison_scopes",
                        lambda models, *a, **k: [object() for _ in models])
    monkeypatch.setattr(gs.vault_service, "get", lambda root: object())
    monkeypatch.setattr(gs, "build_brand_registry", lambda root: object())
    monkeypatch.setattr(gs, "export_article",
                        lambda **k: {"document": str(tmp_path / "x.md"),
                                     "format": "markdown", "title": "T"})
    finished = {}
    monkeypatch.setattr(gs.bus, "finish", lambda job, **d: finished.update(d))
    monkeypatch.setattr(gs.bus, "publish", lambda *a, **k: None)
    monkeypatch.setattr(gs, "_checkpoint", lambda job: None)
    monkeypatch.setattr(gs, "_resolve_chain", lambda req, cfg: [])
    class _Cfg:
        vault_root=str(tmp_path); out_dir=str(tmp_path); export_format="markdown"
        class brand_memory: own_brands=["Br"]
        class contract: mode="conservative"
    monkeypatch.setattr(gs.config_service, "load", lambda: _Cfg)

    req = gs.FinalizeRequest(draft="edited draft", keyword="怎么选",
                             title=None, angle=None, skill_id=None,
                             skill_chain=None, provider=None, model=None,
                             contract_mode=None)
    gs._finalize_job("jobF", req)
    assert seen["scopes_len"] == 2               # 由 models 重解析
    assert "横评" in seen["directive"]            # 对比指令块注入
    assert seen["plan_keyword"] == "怎么选"       # 合成 plan 带 keyword
    assert finished.get("final_text") == "FT"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `... -m pytest sidecar/tests/test_comparison_service.py::test_finalize_job_comparison_branch_uses_models -v`
Expected: FAIL（`_finalize_job` 无横评分支 → 走 plan 缓存 miss 抛 FileNotFoundError）。

- [ ] **Step 3: 写实现**

顶部 imports 加 `from csm_core.assembler.plan import AssemblyPlan`。

`_finalize_job` 现有结构（recon 逐字确认）：`cfg = config_service.load()` → vault_root/out_dir 校验 → **`vault_root = Path(cfg.vault_root)`（现 L318）** → **`out_dir = Path(cfg.out_dir)`（现 L319）** → `entry = assembler_service.get_plan(job_id)`（现 L321）。把横评分支插在 **`out_dir = Path(cfg.out_dir)` 之后、`entry = assembler_service.get_plan(job_id)` 之前**，**复用**已定义的 `vault_root`/`out_dir`（不要重新定义，否则 shadow）：

```python
        vault_root = Path(cfg.vault_root)
        out_dir = Path(cfg.out_dir)

        # 横评分支：命中横评缓存 → 由 models 重解析 scopes、跳过 plan 路径。
        # 复用上面的 vault_root/out_dir，命中即 return，不落到下方 plan 路径。
        meta = comparison_cache.get_comparison(job_id)
        if meta is not None:
            _checkpoint(job_id)
            index = vault_service.get(vault_root)
            registry = build_brand_registry(vault_root)
            scopes = _resolve_comparison_scopes(
                meta.models, index, registry, meta.category,
                set(cfg.brand_memory.own_brands))
            _run_comparison_finalize(
                job_id, req=req, draft=req.draft, scopes=scopes, cfg=cfg,
                out_dir=out_dir, keyword=meta.keyword, title=req.title or meta.title,
                category=meta.category, tone=meta.tone,
                contract_mode=(req.contract_mode or meta.contract_mode
                               or cfg.contract.mode))
            return

        entry = assembler_service.get_plan(job_id)
        # ...（下方现有 plan 路径保持不动）
```

补全 `_run_comparison_finalize`（替换 B3 的占位）：

```python
def _run_comparison_finalize(
    job_id: str, *, req: "FinalizeRequest | ComparisonRequest", draft: str,
    scopes: list, cfg, out_dir: Path, keyword: str, title: str | None,
    category: str, tone: str | None = None, contract_mode: str | None = None,
) -> None:
    """横评成稿：合成 plan（供 factcheck/export）→ finalize_draft（scopes 旁路 +
    对比指令块）→ 导出 + finish。plan 恒 None 发给前端。"""
    chain_steps = _resolve_chain(req, cfg)
    synthetic = AssemblyPlan(
        keyword=keyword or "型号对比", template_id="__comparison__",
        seed=0, core_keyword=keyword or "型号对比")
    primary = next((sc for sc in scopes if getattr(sc, "role", "") == "主推"), None)
    primary_label = (f"{primary.brand} {primary.model}".strip()
                     if primary is not None else None)
    directive = build_comparison_directive(primary_label=primary_label, tone=tone)
    resolved_contract = contract_mode or cfg.contract.mode

    _checkpoint(job_id)
    outcome = finalize_draft(
        job_id, chain_steps=chain_steps, draft=draft,
        plan=synthetic, index=None, registry=None, category=category,
        keyword=keyword, title=title, angle=None,
        provider=getattr(req, "provider", None), model=getattr(req, "model", None),
        cfg=cfg, out_dir=out_dir,
        checkpoint=lambda: _checkpoint(job_id),
        on_pass=lambda p: bus.publish(job_id, "pass", **p.to_dict()),
        stage_index=0, stage_total=1, contract_mode=resolved_contract,
        scopes=scopes, angle_directive=directive)
    if outcome.blocked:
        return
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = export_article(out_dir=out_dir, keyword=keyword,
                           final_text=outcome.final_text, plan=synthetic,
                           fmt=cfg.export_format)
    bus.finish(job_id, document=paths["document"], format=paths["format"],
               title=paths["title"], plan=None, draft=draft,
               final_text=outcome.final_text, passes=outcome.passes,
               cost=outcome.cost, completeness=outcome.completeness,
               comparison={"models": [getattr(sc, "model", "") for sc in scopes]})
```

- [ ] **Step 4: 跑测试确认通过（含零回归）**

Run: `... -m pytest sidecar/tests/test_comparison_service.py sidecar/tests/test_finalize_draft.py -v`
Expected: 横评分支 passed；既有 finalize（plan 路径）测试**全绿**（横评缓存 miss → 不进分支）。

- [ ] **Step 5: Commit**

```bash
git add sidecar/csm_sidecar/services/generate_service.py sidecar/tests/test_comparison_service.py
git commit -m "feat(comparison): _finalize_job 横评分支 + _run_comparison_finalize（合成 plan/指令块/导出）"
```

---

### Task B5: 路由 `POST /api/generate/comparison` + 放宽 finalize 404 预检

**Files:**
- Modify: `sidecar/csm_sidecar/routes/generate.py`
- Test: `sidecar/tests/test_comparison_routes.py`

- [ ] **Step 1: 写失败测试**

`sidecar/tests/test_comparison_routes.py`：

```python
"""横评路由：POST /api/generate/comparison + finalize 404 预检放宽。"""
from __future__ import annotations

from fastapi.testclient import TestClient


def test_comparison_endpoint_returns_job_and_stream(client, monkeypatch):
    from csm_sidecar.services import generate_service as gs
    monkeypatch.setattr(gs, "submit_comparison", lambda req: "jobC")
    resp = client.post("/api/generate/comparison", json={
        "models": ["A", "B"], "keyword": "怎么选", "tone": "口语",
    })
    assert resp.status_code == 202
    body = resp.json()
    assert body["job_id"] == "jobC"
    assert body["stream_url"] == "/api/events/jobC"


def test_comparison_endpoint_validates_models_min_two(client):
    resp = client.post("/api/generate/comparison", json={"models": ["A"]})
    assert resp.status_code == 422           # pydantic min_items=2


def test_comparison_endpoint_validates_models_max_four(client):
    resp = client.post("/api/generate/comparison",
                       json={"models": ["A", "B", "C", "D", "E"]})
    assert resp.status_code == 422           # max_items=4


def test_finalize_precheck_accepts_comparison_cache(client, monkeypatch):
    """横评缓存命中时 finalize 不应被 404 挡掉（plan 缓存 miss 也放行）。"""
    from csm_sidecar.services import generate_service as gs
    from csm_sidecar.services import comparison_cache as cc
    from csm_sidecar.services import assembler_service
    cc.reset_for_test()
    cc.cache_comparison("jobF", models=["A", "B"], category="吸尘器",
                        keyword="k", title=None, tone=None,
                        skill_chain=None, contract_mode=None)
    monkeypatch.setattr(assembler_service, "get_plan", lambda jid: None)  # plan miss
    monkeypatch.setattr(gs, "submit_finalize", lambda jid, req: jid)
    resp = client.post("/api/generate/jobF/finalize",
                       json={"draft": "edited", "keyword": "k"})
    assert resp.status_code == 202           # 横评缓存兜住，不 404
```

（`client` fixture 复用 sidecar 既有 conftest 的 TestClient——见 `sidecar/tests/conftest.py`；若无则本文件加 `@pytest.fixture` 造 `TestClient(app)`。）

- [ ] **Step 2: 跑测试确认失败**

Run: `... -m pytest sidecar/tests/test_comparison_routes.py -v`
Expected: FAIL（端点 404；finalize 预检仍 404）。

- [ ] **Step 3: 写实现**（`routes/generate.py`）

imports 加 `from ..services import comparison_cache`（与既有 `assembler_service` 同处）。

加 Body + 端点（放在 `POST /api/generate` 附近）：

```python
class ComparisonBody(BaseModel):
    models: list[str] = Field(min_length=2, max_length=4)
    keyword: str = ""
    title: str | None = None
    tone: str | None = None
    skill_chain: list[str] | None = None
    contract_mode: Literal["conservative", "aggressive"] | None = None
    draft_only: bool = True


@router.post("/api/generate/comparison", response_model=JobAccepted, status_code=202)
def start_comparison(body: ComparisonBody) -> JobAccepted:
    """多型号横评：确定性组稿 → 复用 finalize 润色。返回 SSE 流 URL。"""
    req = generate_service.ComparisonRequest(**body.model_dump())
    job_id = generate_service.submit_comparison(req)
    return JobAccepted(job_id=job_id, stream_url=f"/api/events/{job_id}")
```

放宽 `finalize_generate` 的 404 预检——将：

```python
    if assembler_service.get_plan(job_id) is None:
        raise HTTPException(status_code=404, detail=f"plan cache miss: {job_id}")
```

改为：

```python
    if (assembler_service.get_plan(job_id) is None
            and comparison_cache.get_comparison(job_id) is None):
        raise HTTPException(status_code=404, detail=f"plan cache miss: {job_id}")
```

- [ ] **Step 4: 跑测试确认通过**

Run: `... -m pytest sidecar/tests/test_comparison_routes.py -v`
Expected: 4 passed。

- [ ] **Step 5: Commit**

```bash
git add sidecar/csm_sidecar/routes/generate.py sidecar/tests/test_comparison_routes.py
git commit -m "feat(comparison): POST /api/generate/comparison + finalize 404 预检兼容横评缓存"
```

---

## Unit C — 前端（store + Hero 切换 + ArticleView init）

### Task C1: store `ComparisonRequest` + `submitComparison`（复用 _subscribe）

**Files:**
- Modify: `frontend/src/stores/article.ts`
- Test: `frontend/src/stores/__tests__/article.comparison.spec.ts`

- [ ] **Step 1: 写失败测试**

`frontend/src/stores/__tests__/article.comparison.spec.ts`（mock 头复用 `article.chain.spec.ts` 范式）：

```ts
import { setActivePinia, createPinia } from "pinia";
import { describe, it, expect, vi, beforeEach } from "vitest";

let sseHandlers: Record<string, (d: any) => void> = {};
const postMock = vi.fn();
const getMock = vi.fn().mockResolvedValue({ data: {} });
vi.mock("@/stores/sidecar", () => ({
  useSidecar: () => ({ client: { post: postMock, get: getMock } }),
}));
vi.mock("@/api/client", () => ({
  subscribe: (_url: string, handlers: Record<string, (d: any) => void>) => {
    sseHandlers = handlers;
    return () => {};
  },
}));
vi.mock("@/composables/useNotifications", () => ({
  useNotifications: () => ({ push: vi.fn() }),
}));

import { useArticle } from "@/stores/article";

describe("article store — 横评 submitComparison", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    postMock.mockReset();
    getMock.mockReset();
    getMock.mockResolvedValue({ data: {} });
    sseHandlers = {};
  });

  it("POST /api/generate/comparison 带 models + tone", async () => {
    postMock.mockResolvedValueOnce({ data: { job_id: "jc" } });
    const a = useArticle();
    await a.submitComparison({ models: ["A", "B"], keyword: "怎么选", tone: "口语" });
    expect(postMock).toHaveBeenCalledWith(
      "/api/generate/comparison",
      expect.objectContaining({ models: ["A", "B"], tone: "口语", draft_only: true }),
    );
    expect(a.lastJobId).toBe("jc");
  });

  it("assembly(plan=null) → draftText 填骨架、plan 保持 null", async () => {
    postMock.mockResolvedValueOnce({ data: { job_id: "jc" } });
    const a = useArticle();
    await a.submitComparison({ models: ["A", "B"], keyword: "k" });
    sseHandlers.assembly({ plan: null, draft: "## 参数对照\n...", comparison: { models: ["A", "B"] } });
    expect(a.draftText).toContain("## 参数对照");
    expect(a.plan).toBeNull();
  });

  it("finalize() 复用 lastJobId 打 /finalize（横评成稿走同端点）", async () => {
    postMock.mockResolvedValueOnce({ data: { job_id: "jc" } });
    const a = useArticle();
    await a.submitComparison({ models: ["A", "B"], keyword: "k" });
    sseHandlers.assembly({ plan: null, draft: "骨架", comparison: { models: ["A", "B"] } });
    postMock.mockResolvedValueOnce({ data: { job_id: "jc" } });
    await a.finalize();
    expect(postMock).toHaveBeenLastCalledWith(
      "/api/generate/jc/finalize",
      expect.objectContaining({ draft: "骨架", keyword: "k" }),
    );
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend; npx vitest run src/stores/__tests__/article.comparison.spec.ts`
Expected: FAIL（`submitComparison` 不存在）。

- [ ] **Step 3: 写实现**（`article.ts`）

在 `GenerateRequest` 接口下方加：

```ts
export interface ComparisonRequest {
  models: string[];
  keyword?: string;
  title?: string | null;
  tone?: string | null;
  skill_chain?: string[] | null;
  contract_mode?: "conservative" | "aggressive";
}
```

在 `submit` action 后加 `submitComparison`（镜像 submit 的 reset + POST 横评端点 + 复用 `_subscribe`；`lastRequest` 存成 GenerateRequest 形以便 `finalize()` 复用）：

```ts
async submitComparison(req: ComparisonRequest): Promise<void> {
  this._teardown();
  _teardownRerun();
  this.rerunningIndex = null;
  // finalize() 从 lastRequest 取 keyword/title/skill_chain 拼 finalize body；
  // 横评专属的 models/tone 存后端缓存，前端 lastRequest 只需兼容形。
  this.lastRequest = {
    keyword: req.keyword ?? "型号对比",
    template_id: "__comparison__",
    title: req.title ?? null,
    skill_chain: req.skill_chain ?? null,
    contract_mode: req.contract_mode,
  } as GenerateRequest;
  this.status = "running";
  this.error = null;
  this.currentStage = null;
  this.stageIndex = -1;
  this.finalText = "";
  this.draftText = "";
  this.documentPath = null;
  this.title = req.keyword ?? "型号对比";
  this.plan = null;
  this.template = null;
  this.factcheck = null;
  this.passes = [];
  this.cost = null;
  this.isFinalizing = false;
  this.lint = null; this.lintReleased = [];
  this.completeness = null; this.score = null;

  const sidecar = useSidecar();
  try {
    const resp = await sidecar.client.post("/api/generate/comparison", {
      models: req.models,
      keyword: req.keyword ?? "",
      title: req.title ?? null,
      tone: req.tone ?? null,
      skill_chain: req.skill_chain ?? null,
      ...(req.contract_mode ? { contract_mode: req.contract_mode } : {}),
      draft_only: true,
    });
    this.jobId = resp.data.job_id;
    this.lastJobId = resp.data.job_id;
  } catch (e: any) {
    this.status = "error";
    this.error = e?.response?.data?.detail ?? e?.message ?? String(e);
    return;
  }
  this._subscribe(this.jobId!);
},
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd frontend; npx vitest run src/stores/__tests__/article.comparison.spec.ts`
Expected: 3 passed。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/stores/article.ts frontend/src/stores/__tests__/article.comparison.spec.ts
git commit -m "feat(comparison): article store submitComparison（复用 _subscribe/finalize）"
```

---

### Task C2: `ComparisonPicker.vue`（型号多选弹层）

**Files:**
- Create: `frontend/src/components/home/ComparisonPicker.vue`
- Test:（渲染/交互留到 C3 Hero 集成测，本 Task 只建组件；轻量组件可不单独测，交互覆盖在 C3）

- [ ] **Step 1: 写组件**（house 弹层范式：Teleport + 遮罩 @click.self + anim-up 卡 + 底部完成；数据源 `useMaterials().list()`；`role==="主推"`/`"竞品"` 分组；多选上限 4，选中回填 `v-model` 的 `string[]`）

`frontend/src/components/home/ComparisonPicker.vue`：

```vue
<script setup lang="ts">
import { computed, onMounted } from "vue";
import { useMaterials } from "@/stores/materials";
import Btn from "@/components/ui/Btn.vue";
import Icon from "@/components/ui/Icon.vue";

const props = defineProps<{ modelValue: string[]; open: boolean }>();
const emit = defineEmits<{
  (e: "update:modelValue", v: string[]): void;
  (e: "update:open", v: boolean): void;
}>();

const materials = useMaterials();
onMounted(() => { void materials.list(); });

const own = computed(() => materials.models.filter((m) => m.role === "主推"));
const competitor = computed(() => materials.models.filter((m) => m.role !== "主推"));
const MAX = 4;

function toggle(model: string) {
  const cur = [...props.modelValue];
  const i = cur.indexOf(model);
  if (i >= 0) cur.splice(i, 1);
  else if (cur.length < MAX) cur.push(model);
  emit("update:modelValue", cur);
}
function isSel(model: string) { return props.modelValue.includes(model); }
function close() { emit("update:open", false); }
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="fixed inset-0 z-50 flex items-center justify-center"
         :style="{ background: 'rgba(0,0,0,0.28)' }" @click.self="close">
      <div class="anim-up" :style="{ width: '440px', maxHeight: '70vh', overflowY: 'auto',
           background: 'var(--card)', borderRadius: '16px', padding: '20px' }">
        <div class="flex items-center justify-between" :style="{ marginBottom: '12px' }">
          <span class="font-medium">选择对比型号（2–4 个）</span>
          <button type="button" @click="close"><Icon name="x" :size="16" /></button>
        </div>
        <div v-if="own.length" :style="{ marginBottom: '10px' }">
          <div class="text-[11px]" :style="{ color: 'var(--ink-3)', marginBottom: '6px' }">主推</div>
          <div class="flex flex-wrap gap-2">
            <button v-for="m in own" :key="m.model" type="button"
                    class="qc-model-chip" :data-sel="isSel(m.model)"
                    :style="{ padding: '5px 10px', borderRadius: '8px', fontSize: '12px',
                      border: '1px solid var(--line)',
                      background: isSel(m.model) ? 'var(--primary-soft)' : 'var(--frosted-bg)' }"
                    @click="toggle(m.model)">{{ m.brand }} {{ m.model }}</button>
          </div>
        </div>
        <div v-if="competitor.length">
          <div class="text-[11px]" :style="{ color: 'var(--ink-3)', marginBottom: '6px' }">竞品</div>
          <div class="flex flex-wrap gap-2">
            <button v-for="m in competitor" :key="m.model" type="button"
                    class="qc-model-chip" :data-sel="isSel(m.model)"
                    :style="{ padding: '5px 10px', borderRadius: '8px', fontSize: '12px',
                      border: '1px solid var(--line)',
                      background: isSel(m.model) ? 'var(--primary-soft)' : 'var(--frosted-bg)' }"
                    @click="toggle(m.model)">{{ m.brand }} {{ m.model }}</button>
          </div>
        </div>
        <div class="flex justify-end" :style="{ marginTop: '16px' }">
          <Btn variant="dark" :disabled="modelValue.length < 2" @click="close">
            完成（{{ modelValue.length }}）
          </Btn>
        </div>
      </div>
    </div>
  </Teleport>
</template>
```

- [ ] **Step 2: 类型自检**

Run: `cd frontend; npx vue-tsc -b`（跑完 `git checkout -- frontend/vite.config.js` 还原 emit）
Expected: 0 错误。

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/home/ComparisonPicker.vue
git commit -m "feat(comparison): ComparisonPicker 型号多选弹层（主推/竞品分组，2-4）"
```

---

### Task C3: Hero「常规|横评」切换 + 横评 takeoff

**Files:**
- Modify: `frontend/src/components/home/CreateArticleHero.vue`
- Test: `frontend/src/components/home/__tests__/CreateArticleHero.spec.ts`

- [ ] **Step 1: 写失败测试**（追加到既有 Hero spec；需在文件头 mock 加 `@/stores/materials`）

在 mock 区加：

```ts
vi.mock("@/stores/materials", () => ({
  useMaterials: () => ({ models: [], loading: false, error: null, list: vi.fn() }),
}));
```

追加测试：

```ts
it("横评模式 takeoff → query 带 mode=comparison + models", async () => {
  const w = mount(CreateArticleHero, { global: { stubs: { teleport: true } } });
  await flushPromises();
  (w.vm as any).mode = "comparison";
  (w.vm as any).compModels = ["A", "B"];
  (w.vm as any).keyword = "怎么选";
  (w.vm as any).takeoff();
  const query = pushMock.mock.calls.at(-1)![0].query;
  expect(query.mode).toBe("comparison");
  expect(query.models).toBe("A,B");
  expect(query.keyword).toBe("怎么选");
});

it("横评模式 <2 型号时 takeoff 不跳转", async () => {
  const w = mount(CreateArticleHero, { global: { stubs: { teleport: true } } });
  await flushPromises();
  (w.vm as any).mode = "comparison";
  (w.vm as any).compModels = ["A"];
  (w.vm as any).keyword = "k";
  pushMock.mockClear();
  (w.vm as any).takeoff();
  expect(pushMock).not.toHaveBeenCalled();
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend; npx vitest run src/components/home/__tests__/CreateArticleHero.spec.ts`
Expected: FAIL（`mode`/`compModels` 未 expose）。

- [ ] **Step 3: 写实现**（`CreateArticleHero.vue`）

script 加 state + 引入 picker：

```ts
import ComparisonPicker from "@/components/home/ComparisonPicker.vue";
// 创作模式：常规单篇 | 横评多型号对比。
const mode = ref<"normal" | "comparison">("normal");
const compModels = ref<string[]>([]);
const showCompPicker = ref(false);
```

改 `takeoff()` 顶部分叉出横评路径（在现有 `if (!keyword.value.trim()) return;` 之后）：

```ts
  if (mode.value === "comparison") {
    if (compModels.value.length < 2) return;      // 需 2-4 型号
    const q: Record<string, string> = {
      mode: "comparison",
      models: compModels.value.join(","),
      keyword: keyword.value.trim(),
    };
    if (skillChain.value.length > 0) q.skill_chain = skillChain.value.join(",");
    if (angle.value?.tone) q.tone = angle.value.tone;
    if (title.value.trim()) q.title = title.value.trim();
    if (contractMode.value) q.contract = contractMode.value;
    router.push({ name: "article", query: q });
    return;
  }
```

`defineExpose` 追加 `mode, compModels, showCompPicker`：

```ts
defineExpose({ keyword, angle, title, tplId, skillChain, showChainPicker, contractMode, mode, compModels, showCompPicker, takeoff, onPickTemplate });
```

模板：在大标块与输入条之间加 segmented 切换（house 风格 chip 二选一），并在 chip 行内条件渲染横评「选型号」按钮 + 挂 `ComparisonPicker`：

```html
<!-- 模式切换：常规 | 横评 -->
<div class="flex gap-2" :style="{ marginBottom: '2px' }">
  <button type="button" :data-mode-normal="mode === 'normal'"
    :style="{ padding: '5px 12px', borderRadius: '999px', fontSize: '12px',
      border: '1px solid var(--line)',
      background: mode === 'normal' ? 'var(--primary-soft)' : 'transparent' }"
    @click="mode = 'normal'">常规</button>
  <button type="button" :data-mode-comparison="mode === 'comparison'"
    :style="{ padding: '5px 12px', borderRadius: '999px', fontSize: '12px',
      border: '1px solid var(--line)',
      background: mode === 'comparison' ? 'var(--primary-soft)' : 'transparent' }"
    @click="mode = 'comparison'">横评</button>
</div>
```

chip 行内（横评时替换模板下拉为选型号按钮）：

```html
<button v-if="mode === 'comparison'" type="button" data-comp-models-trigger
  :style="{ padding: '6px 12px', borderRadius: '10px', fontSize: '12px',
    border: '1px solid var(--line)',
    background: compModels.length ? 'var(--primary-soft)' : 'var(--frosted-bg)' }"
  @click="showCompPicker = true">
  {{ compModels.length ? `已选 ${compModels.length} 个型号` : "选择对比型号" }}
</button>
<ComparisonPicker v-model="compModels" v-model:open="showCompPicker" />
```

- [ ] **Step 4: 跑测试确认通过 + 类型门禁**

Run: `cd frontend; npx vitest run src/components/home/__tests__/CreateArticleHero.spec.ts`
Expected: 全 passed（含既有单篇测试零回归）。
Run: `npx vue-tsc -b`（跑完还原 vite.config.js）→ 0 错误。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/home/CreateArticleHero.vue frontend/src/components/home/__tests__/CreateArticleHero.spec.ts
git commit -m "feat(comparison): Hero 常规|横评 切换 + 型号选择入口 + 横评 takeoff"
```

---

### Task C4: ArticleView init 横评分支

**Files:**
- Modify: `frontend/src/views/ArticleView.vue`
- Test: `frontend/src/views/__tests__/ArticleView.comparison.spec.ts`

- [ ] **Step 1: 写失败测试**

`frontend/src/views/__tests__/ArticleView.comparison.spec.ts`（复用 `ArticleView.contract.spec.ts` 的 mock 头 + jsdom shim；`routeQuery` 注入）：

```ts
// ← 复制 ArticleView.contract.spec.ts 第 1-65 行 mock 头（matchMedia shim、
//   vue-router routeQuery、sidecar post/get、subscribe no-op、TiptapEditor/
//   FactCheckPanel stub、config/toast/failureAlert/useSidecarReady mock、
//   setupLookups），额外加 materials mock：
vi.mock("@/stores/materials", () => ({
  useMaterials: () => ({ models: [], loading: false, error: null, list: vi.fn() }),
}));

import { mount, flushPromises } from "@vue/test-utils";
import { setActivePinia, createPinia } from "pinia";
import { describe, it, expect, beforeEach } from "vitest";
import ArticleView from "@/views/ArticleView.vue";

describe("ArticleView — 横评 init 分支", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    postMock.mockReset();
    postMock.mockResolvedValue({ data: { job_id: "jc" } });
    getMock.mockReset();
    setupLookups();
    routeQuery = {};
  });

  it("query mode=comparison → POST /api/generate/comparison 带 models", async () => {
    routeQuery = { keyword: "怎么选", mode: "comparison", models: "A,B", tone: "口语" };
    mount(ArticleView, { global: { stubs: { teleport: true } } });
    await flushPromises();
    const call = postMock.mock.calls.find((c) => c[0] === "/api/generate/comparison");
    expect(call).toBeTruthy();
    expect(call![1].models).toEqual(["A", "B"]);
    expect(call![1].tone).toBe("口语");
  });

  it("无 mode（常规）不触发横评端点", async () => {
    routeQuery = { keyword: "k", template_id: "tpl-a" };
    mount(ArticleView, { global: { stubs: { teleport: true } } });
    await flushPromises();
    const call = postMock.mock.calls.find((c) => c[0] === "/api/generate/comparison");
    expect(call).toBeFalsy();
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend; npx vitest run src/views/__tests__/ArticleView.comparison.spec.ts`
Expected: FAIL（无横评分支 → 未打 comparison 端点）。

- [ ] **Step 3: 写实现**（`ArticleView.vue` `onMounted`）

在 `angle.value = rebuildAngleFromQuery()` 之后、自动起飞 `if (qk && ...)` 之前，加横评分叉。先读 mode + models：

```ts
  const qmode = (route.query.mode as string) ?? "";
  const qmodels = ((route.query.models as string) ?? "")
    .split(",").map((s) => s.trim()).filter(Boolean);
```

把自动起飞块改为「横评优先」：

```ts
  if (qmode === "comparison" && qmodels.length >= 2 && article.status === "idle" && !article.finalText) {
    void article.submitComparison({
      models: qmodels,
      keyword: qk,
      ...(title.value.trim() ? { title: title.value.trim() } : {}),
      ...(angle.value?.tone ? { tone: angle.value.tone } : {}),
      ...(skillChain.value.length > 0 ? { skill_chain: skillChain.value } : {}),
      ...(contractMode.value ? { contract_mode: contractMode.value } : {}),
    });
  } else if (
    qk &&
    article.status === "idle" &&
    !article.finalText &&
    templateId.value
  ) {
    takeoff();
  } else if (article.status === "error" && !qk) {
    // ...（现有 failureAlert 分支不动）
  }
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd frontend; npx vitest run src/views/__tests__/ArticleView.comparison.spec.ts`
Expected: 2 passed。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/views/ArticleView.vue frontend/src/views/__tests__/ArticleView.comparison.spec.ts
git commit -m "feat(comparison): ArticleView init 横评分支（query→submitComparison）"
```

---

### Task C5: 全量前端回归 + vue-tsc 门禁

**Files:** 无新增（验证 gate）

- [ ] **Step 1: 全量 vitest**

Run: `cd frontend; npx vitest run`
Expected: 全 passed（既有 + 新增横评三文件）。

- [ ] **Step 2: vue-tsc 门禁**

Run: `npx vue-tsc -b`；跑完 `git checkout -- frontend/vite.config.js`（还原 emit）
Expected: 0 错误。

- [ ] **Step 3: Commit（若有 lint/格式微调）**

```bash
git add -A frontend
git commit -m "test(comparison): 前端全量回归 + vue-tsc 0"
```

---

## Self-Review（写完计划后自查）

**1. Spec 覆盖（§5.1/§5.2 逐条）：**
- 入口 Hero 常规|横评 切换 → C3 ✓；型号多选 2-4 主推/竞品分组 → C2 ✓；可选 标题/语调/skill链/契约 → C3 query 组装 ✓；不选模板 → C3 横评分支不带 template_id ✓；router query {mode,models,tone?,title?,skill_chain?} → C3/C4 ✓。
- `POST /api/generate/comparison` + ComparisonBody → B5 ✓；submit_comparison/_run_comparison_job（扫库/组稿/error<2/assembly plan=null+comparison）→ B3 ✓；横评元数据缓存 → B1 ✓；_finalize_job 命中横评缓存走 models、其余共用 → B4 ✓。
- `compose_comparison_draft` 5 段（引言/参数对照/亮点/实测/总结）→ A1-A5 ✓；对比指令块经 angle_directive → A6 + B4 ✓；事实白名单/factcheck/lint/评分/导出走既有链 → finalize_draft 复用（B2 旁路）✓；plan=null 前端骨架/隐藏 reroll → recon 确认现状已支持，无需改 ✓。
- 测试：compose 纯函数 2/3/4 型号/占位/求交/省节/总结 → A2-A5 ✓；服务未知型号/<2/缓存命中/draft_only → B3/B4 ✓；前端 Hero 切换/query/submitComparison/init 分支 → C1/C3/C4 ✓。

**2. Placeholder 扫描：** B3 的 `_run_comparison_finalize` 占位在 B4 补全（已在 B4 Step 3 明确替换）；其余步骤均含完整代码。✓

**3. 类型一致性：** `ComparisonRequest`（B3 dataclass ↔ C1 TS 接口）字段名一致（models/keyword/title/tone/skill_chain/contract_mode/draft_only）；`ComparisonMeta`（B1）字段与 `cache_comparison` 参数一致；`_resolve_comparison_scopes`（B3 定义，B4 复用）签名一致；`finalize_draft` 新增 `scopes`/`angle_directive`（B2 定义，B4 调用）一致；query key（C3 push ↔ C4 read）：mode/models/keyword/tone/title/skill_chain/contract 一致。✓

**风险备忘（交实现者）：**
- `_run_comparison_finalize` 的 `req` 可能是 `ComparisonRequest`（非 draft_only 路径）或 `FinalizeRequest`（B4 分支），故用 `getattr(req, "provider", None)` 容两形。
- `finalize_draft` 改 scopes 解析时，务必把 `if scopes:`（渲染 brand_facts）平移到外层——预置 scopes 也要能注入。零回归测试（test_finalize_draft/test_generate_contract）必须全绿才算过 B2。
- sidecar `conftest.py` 的 `client` fixture（L98-110）在进出各 `factcheck_service.reset_for_test()` 一次。**在 B5 里同处加 `comparison_cache.reset_for_test()`**（L106 与 L110 各一行，紧邻 factcheck 那两行；顶部 import 加 `from csm_sidecar.services import comparison_cache`）——否则前一个用 `client` 的测试写进的横评缓存会泄漏到后续 finalize 预检测试。B1 的纯 service 测试各自 `cc.reset_for_test()` 已自洽，但走 `client` 的路由测试靠 fixture 兜。
- 横评 finalize 若命中 factcheck 拦截，`_maybe_block_for_factcheck` 内部会 `bus.finish(plan=_plan_to_dict(synthetic))`——synthetic 空 results，前端 `assemblyRows=[]` 仍走骨架，视觉等价 plan=null，无需特殊处理。
