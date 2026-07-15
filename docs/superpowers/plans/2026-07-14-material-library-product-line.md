# 素材库产品线通用化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 素材库(品牌型号/录入)从吸尘器单产品线假设升级为数据驱动的多产品线通用显示。

**Architecture:** 后端抽出共享 `note_identity` 判定链(frontmatter 优先→文件名兜底)让 registry 与 resolver 永不分歧;`SpecValue` 保留笔记 H2 小节名,前端按真实小节分组渲染;registry 从路径提取产品线;录入树改为文件系统全目录枚举 + 空文件夹借兄弟产品线模板。

**Tech Stack:** Python (csm_core 纯函数 + FastAPI sidecar, pydantic), Vue 3 + Pinia + TypeScript, pytest / vitest。

**Spec:** `docs/superpowers/specs/2026-07-14-material-library-product-line-design.md`

**对 spec 的一处替换(已论证):** spec 说在共享 mini_vault 夹具里加净化器产品线;实查发现 mini_vault 被 ~10 个无关测试文件断言引用,加笔记会大面积涟漪。改为在相关测试文件里用 tmp_path 自建微型 vault(该目录测试的既有惯例,见 test_resolver.py / test_brand_registry.py),覆盖意图不变。

## 环境准备(每个执行会话开头跑一次)

```powershell
# worktree 跑测试必须用 PYTHONPATH 覆盖主仓 editable 安装(见记忆:csm-dev-worktree-setup)
$env:PYTHONPATH = "D:\CSM\.claude\worktrees\inspiring-euclid-dfa60a;D:\CSM\.claude\worktrees\inspiring-euclid-dfa60a\sidecar"
```

前端若未装依赖:`cd frontend && npm install`(必须 npm,pnpm 不跑 esbuild postinstall)。

---

### Task 1: `note_identity` 共享判定链

**Files:**
- Modify: `csm_core/brand_memory/identity.py`
- Test: `tests/core/brand_memory/test_identity.py`

- [ ] **Step 1: Write the failing tests**

在 `tests/core/brand_memory/test_identity.py` 末尾追加:

```python
from csm_core.brand_memory.identity import note_identity


def test_note_identity_frontmatter_first():
    # frontmatter 品牌/型号 优先于文件名解析(未知品牌 DARZ 不在别名表也能命中)
    fm = {"品牌": "DARZ", "型号": "DARZD9"}
    assert note_identity("DARZD9-产品参数", fm, ALIASES) == ("DARZ", "DARZD9")


def test_note_identity_frontmatter_brand_folds_alias():
    fm = {"品牌": "米家", "型号": "米家3C"}
    assert note_identity("米家3C-产品参数", fm, ALIASES) == ("小米", "米家3C")


def test_note_identity_filename_fallback():
    # 无 frontmatter → 文件名解析品牌 + full-stem 型号(与 registry 现行为一致)
    assert note_identity("CEWEYDS18-产品参数", {}, ALIASES) == ("CEWEY", "CEWEYDS18")


def test_note_identity_partial_frontmatter():
    # 只有 型号 没有 品牌 → 品牌走文件名解析
    fm = {"型号": "CEWEYDS18"}
    assert note_identity("CEWEYDS18-产品参数", fm, ALIASES) == ("CEWEY", "CEWEYDS18")


def test_note_identity_unresolvable_returns_none():
    # 品牌既不在 frontmatter 也解析不出 → None(registry 的 skip 行为)
    assert note_identity("某杂牌X9-产品参数", {}, ALIASES) is None
    assert note_identity("某杂牌X9-产品参数", None, ALIASES) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/core/brand_memory/test_identity.py -v`
Expected: 新增 5 个用例 FAIL(ImportError: cannot import name 'note_identity')

- [ ] **Step 3: Implement `note_identity`**

在 `csm_core/brand_memory/identity.py` 末尾追加:

```python
def note_identity(
    stem: str,
    frontmatter: dict | None,
    aliases: dict[str, list[str]] = BRAND_ALIASES,
) -> tuple[str, str] | None:
    """产品参数/测试结果笔记的 (canonical品牌, 型号全名) 单一判定链。

    frontmatter ``品牌``/``型号`` 优先(未知品牌靠它命中,别名表不再是白名单),
    文件名解析兜底 —— 与 build_brand_registry 的历史行为完全一致,registry 与
    resolver 都必须走这里,两处永不分歧。型号保持 full-stem 约定(CEWEYDS18)。
    """
    fm = frontmatter or {}
    parsed = parse_brand_model(stem, aliases)
    brand = str(fm.get("品牌") or "").strip() or (parsed[0] if parsed else "")
    model = str(fm.get("型号") or "").strip() or stem.split("-")[0].strip()
    if not brand or not model:
        return None
    return canonical_brand(brand, aliases), model
```

同时更新模块 docstring 第一段,追加一句:「note_identity 是 registry/resolver 共用的
(品牌,型号) 判定链;BRAND_ALIASES 只做别名折叠,不是品牌白名单。」

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/core/brand_memory/test_identity.py -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add csm_core/brand_memory/identity.py tests/core/brand_memory/test_identity.py
git commit -m "feat(brand-memory): note_identity 共享判定链,frontmatter 优先文件名兜底"
```

---

### Task 2: `SpecValue.section` 保留 H2 小节

**Files:**
- Modify: `csm_core/brand_memory/model.py:7-13`
- Modify: `csm_core/brand_memory/specs.py:43-67`
- Test: `tests/core/brand_memory/test_specs.py`

- [ ] **Step 1: Write the failing test**

在 `tests/core/brand_memory/test_specs.py` 末尾追加:

```python
def test_section_retained_in_note_order():
    # 每字段记录所属 H2 小节名(原文),dict 插入序 = 笔记顺序(前端分组渲染依赖)。
    specs = parse_spec_table(BODY)
    assert specs["吸力(AW)"].section == "性能参数"
    assert specs["电机功率"].section == "性能参数"      # 占位字段也带 section
    assert specs["不同档位续航"].section == "续航电池"
    assert specs["认证检测"].section == "基础信息"      # 认证字段也带 section
    assert list(specs) == [
        "吸力(AW)", "真空度(Pa)", "最低噪音（dB）", "电机功率",
        "不同档位续航", "认证检测",
    ]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/core/brand_memory/test_specs.py -v`
Expected: 新用例 FAIL(AttributeError 或 section == ""),旧用例 PASS

- [ ] **Step 3: Implement**

`csm_core/brand_memory/model.py` — `SpecValue` 加一行字段(放在 `is_placeholder` 之后):

```python
    section: str = ""                # 所属 H2 小节名(原文),如 "核心净化性能"
```

`csm_core/brand_memory/specs.py` — `parse_spec_table` 里三处 `SpecValue(...)` 构造都
带上 `section=`。改后的循环体:

```python
def parse_spec_table(body: str) -> dict[str, SpecValue]:
    specs: dict[str, SpecValue] = {}
    for section in extract_brand_sections(body):
        sec_title = section.raw_title.strip()
        for line in section.body.splitlines():
            m = _ROW_RE.match(line)
            if not m:
                continue
            field, value = m.group(1).strip(), m.group(2).strip()
            if not field or field == "参数" or _SEP_CELL_RE.match(field):
                continue
            # 占位/0：保留字段但标记为缺口（供缺口体检），不出数字。
            if _is_placeholder(value):
                specs[field] = SpecValue(
                    field=field, raw=value, is_placeholder=True, section=sec_title)
                continue
            # 认证字段：认证名清单（含 3C），非数值但也非缺口 → 不抽数字、不算占位。
            if _is_cert_field(field):
                specs[field] = SpecValue(field=field, raw=value, section=sec_title)
                continue
            numbers = [float(n) for n in _NUM_RE.findall(value)]
            specs[field] = SpecValue(
                field=field, raw=value, numbers=numbers,
                unit=_extract_unit(value),
                is_approx=any(mark in value for mark in _APPROX),
                section=sec_title,
            )
    return specs
```

模块 docstring 里「小节分组在 parse_spec_table 里已被拍平」的旧说法同步改为
「扁平 dict 保序,每个 SpecValue 带 section 小节名(前端按它分组)」。

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/core/brand_memory/ -v`
Expected: 全部 PASS(section 有默认值,pydantic 序列化向后兼容)

- [ ] **Step 5: Commit**

```bash
git add csm_core/brand_memory/model.py csm_core/brand_memory/specs.py tests/core/brand_memory/test_specs.py
git commit -m "feat(brand-memory): SpecValue 保留 H2 小节名,specs 不再拍平分组"
```

---

### Task 3: registry 走 note_identity + 产品线提取

**Files:**
- Modify: `csm_core/vault/brand_registry.py`
- Test: `tests/core/vault/test_brand_registry.py`

- [ ] **Step 1: Write the failing tests**

在 `tests/core/vault/test_brand_registry.py` 中追加(放在 `_REAL_VAULT` 定义之前):

```python
def test_registry_unknown_brand_via_frontmatter(tmp_path: Path):
    # 未知品牌(不在 BRAND_ALIASES)靠 frontmatter 品牌/型号 进 registry
    d = tmp_path / "营销资料库/产品模块/空气净化器/产品参数"
    d.mkdir(parents=True)
    (d / "DARZD9-产品参数.md").write_text(
        "---\n产品: 空气净化器\n品牌: DARZ\n型号: DARZD9\n素材类型: 产品参数\n核心关键词: [x]\n---\n体\n",
        encoding="utf-8",
    )
    reg = build_brand_registry(tmp_path)
    assert reg.brands() == ["DARZ"]
    assert reg.brand_of("DARZD9") == "DARZ"


def test_registry_product_line_from_path(tmp_path: Path):
    # 产品线 = 产品参数 目录的上一段(产品模块/<产品线>/产品参数)
    for line, stem in (("吸尘器", "CEWEYDS18"), ("空气净化器", "DARZD9")):
        d = tmp_path / f"营销资料库/产品模块/{line}/产品参数"
        d.mkdir(parents=True)
        (d / f"{stem}-产品参数.md").write_text(
            f"---\n产品: {line}\n品牌: X\n型号: {stem}\n素材类型: 产品参数\n核心关键词: [x]\n---\n体\n",
            encoding="utf-8",
        )
    reg = build_brand_registry(tmp_path)
    assert reg.line_of("CEWEYDS18") == "吸尘器"
    assert reg.line_of("DARZD9") == "空气净化器"
    assert reg.line_of("不存在") is None


def test_registry_product_line_old_flat_layout_falls_back_to_frontmatter(tmp_path: Path):
    # 旧扁平布局(产品模块/产品参数,无产品线层)→ 兜底 frontmatter 产品
    d = tmp_path / "营销资料库/产品模块/产品参数"
    d.mkdir(parents=True)
    (d / "CEWEYDS18-产品参数.md").write_text(
        "---\n产品: 吸尘器\n素材类型: 产品参数\n核心关键词: [x]\n---\n体\n",
        encoding="utf-8",
    )
    reg = build_brand_registry(tmp_path)
    assert reg.line_of("CEWEYDS18") == "吸尘器"


def test_registry_product_line_unknown_when_nothing_to_derive(tmp_path: Path):
    # 顶层就是 产品参数 且 frontmatter 无 产品 → "未分类"
    d = tmp_path / "产品参数"
    d.mkdir(parents=True)
    (d / "CEWEYDS18-产品参数.md").write_text(
        "---\n素材类型: 产品参数\n核心关键词: [x]\n---\n体\n",
        encoding="utf-8",
    )
    reg = build_brand_registry(tmp_path)
    assert reg.line_of("CEWEYDS18") == "未分类"
```

并把钉死 33 的真机集成测试整体替换为:

```python
@pytest.mark.integration
@pytest.mark.skipif(not _REAL_VAULT.exists(), reason="真实 vault 不在本机")
def test_real_vault_registry_covers_both_lines():
    reg = build_brand_registry(_REAL_VAULT)
    # 2026-07: 吸尘器 33 + 空气净化器 29;不钉死总数,防用户加型号即碎
    assert len(reg.all_models()) >= 60
    assert "CEWEY" in reg.brands()
    assert "DARZ" in reg.brands()          # 未知品牌靠 frontmatter 进表
    assert "米家" not in reg.brands()       # 别名归一不回退
    assert reg.line_of("CEWEYDS18") == "吸尘器"
    assert reg.line_of("DARZD9") == "空气净化器"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/core/vault/test_brand_registry.py -v`
Expected: 新用例 FAIL(`line_of` 不存在;DARZ 用例 FAIL 因 registry 兜底逻辑虽在但
`brands()==["DARZ"]` 应已过——若它 PASS 属预期,其余必 FAIL)

- [ ] **Step 3: Implement**

`csm_core/vault/brand_registry.py` 整文件改为:

```python
"""Build brand-model registry from 产品参数 note filenames + frontmatter."""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from .note_parser import parse_note
from ..brand_memory.identity import BRAND_ALIASES, note_identity


@dataclass
class BrandRegistry:
    _brand_to_models: dict[str, list[str]] = field(default_factory=dict)
    _model_to_brand: dict[str, str] = field(default_factory=dict)
    _model_to_line: dict[str, str] = field(default_factory=dict)

    def brands(self) -> list[str]:
        return sorted(self._brand_to_models.keys())

    def models(self, brand: str) -> list[str]:
        return sorted(self._brand_to_models.get(brand, []))

    def all_models(self) -> list[str]:
        return sorted(self._model_to_brand.keys())

    def brand_of(self, model: str) -> str | None:
        return self._model_to_brand.get(model)

    def line_of(self, model: str) -> str | None:
        """产品线(吸尘器/空气净化器/...);registry 不识别该型号 → None。"""
        return self._model_to_line.get(model)

    def competitors_of(self, brand: str) -> list[str]:
        return [m for m, b in self._model_to_brand.items() if b != brand]

    def add(self, brand: str, model: str, line: str = "未分类") -> None:
        self._brand_to_models.setdefault(brand, [])
        if model not in self._brand_to_models[brand]:
            self._brand_to_models[brand].append(model)
        self._model_to_brand[model] = brand
        self._model_to_line[model] = line


def _line_of_path(md: Path, vault_root: Path, frontmatter: dict) -> str:
    """产品线 = 产品参数 目录的上一段;旧扁平布局/顶层兜底 frontmatter 产品。"""
    parent = md.parent.parent
    if parent != vault_root and parent.name not in ("产品模块", ""):
        return parent.name
    return str(frontmatter.get("产品") or "").strip() or "未分类"


def build_brand_registry(
    vault_root: Path, *, aliases: dict[str, list[str]] = BRAND_ALIASES,
) -> BrandRegistry:
    """Scan <vault>/**/产品参数/*.md and construct registry.

    (品牌, 型号) 判定链见 brand_memory.identity.note_identity(frontmatter 优先、
    文件名兜底,与 resolver 共用)。型号保持 full-stem 约定(incl. brand prefix,
    e.g. CEWEYDS18)used across the assembler 型号-join (sampler.py /
    constraints.py); see plan §关键设计决定 #1。产品线取自路径
    产品模块/<产品线>/产品参数 的中间段,旧扁平布局兜底 frontmatter 产品。
    """
    registry = BrandRegistry()
    for md in sorted(vault_root.rglob("产品参数/*.md")):
        note = parse_note(md)
        ident = note_identity(md.stem, note.frontmatter, aliases)
        if ident is None:
            continue
        brand, model = ident
        registry.add(brand, model, line=_line_of_path(md, vault_root, note.frontmatter))
    return registry
```

注意:旧实现 `model = str(note.frontmatter.get("型号") or md.stem.split("-")[0])` 与
note_identity 内部逻辑逐字等价,行为不变仅收拢。

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/core/vault/test_brand_registry.py tests/scripts/ -v`
Expected: 全部 PASS(含真机 integration 用例,本机有真实 vault 会跑)。
`tests/scripts/test_backfill_brand_model.py` 一并跑,确认 backfill 脚本没被 add 签名影响。

- [ ] **Step 5: Commit**

```bash
git add csm_core/vault/brand_registry.py tests/core/vault/test_brand_registry.py
git commit -m "feat(vault): registry 走 note_identity + 从路径提取产品线 line_of"
```

---

### Task 4: resolver 产品参数匹配走 note_identity

**Files:**
- Modify: `csm_core/brand_memory/resolver.py:62-72`
- Test: `tests/core/brand_memory/test_resolver.py`

- [ ] **Step 1: Write the failing tests**

在 `tests/core/brand_memory/test_resolver.py` 末尾追加:

```python
def test_resolves_unknown_brand_specs_via_frontmatter(tmp_path):
    # DARZ 不在 BRAND_ALIASES;调用方(service)对未知品牌回退 full-stem 型号。
    # 修复前 specs 恒空(参数 0/32 根因),修复后靠 frontmatter 命中。
    _write(tmp_path / "营销资料库/产品模块/空气净化器/产品参数/DARZD9-产品参数.md",
           "---\n产品: 空气净化器\n素材类型: 产品参数\n品牌: DARZ\n型号: DARZD9\n核心关键词: x\n---\n"
           "## 核心净化性能\n\n| 参数 | 数值 |\n|--|--|\n| 颗粒物CADR | 512m³/h |\n| 甲醛CADR | 308m³/h |\n")
    index = scan_vault(tmp_path)
    mem = resolve_memory("DARZ", "DARZD9", "空气净化器", index,
                         own_brands={"CEWEY", "DARZ"})
    assert mem.role == "主推"
    assert mem.specs["颗粒物CADR"].numbers == [512.0]
    assert mem.specs["颗粒物CADR"].section == "核心净化性能"
    assert mem.coverage["has_specs"] is True


def test_known_brand_stripped_model_still_matches(tmp_path):
    # 已知品牌 + 剥品牌型号(DS18)的既有调用形态不回归(两种型号形式都接受)。
    _make_vault(tmp_path)
    index = scan_vault(tmp_path)
    mem = resolve_memory("CEWEY", "DS18", "吸尘器", index, own_brands={"CEWEY"})
    assert mem.specs["吸力(AW)"].numbers == [220.0]


def test_spec_note_of_other_brand_not_matched(tmp_path):
    # 品牌相同才比对型号;不同品牌同型号名不误命中。
    _write(tmp_path / "营销资料库/产品模块/空气净化器/产品参数/权尚KJ410-产品参数.md",
           "---\n产品: 空气净化器\n素材类型: 产品参数\n品牌: 权尚\n型号: 权尚KJ410\n核心关键词: x\n---\n"
           "## 基础信息\n\n| 参数 | 数值 |\n|--|--|\n| 价格 | 999 |\n")
    index = scan_vault(tmp_path)
    mem = resolve_memory("DARZ", "权尚KJ410", "空气净化器", index,
                         own_brands={"CEWEY", "DARZ"})
    assert mem.specs == {}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/core/brand_memory/test_resolver.py -v`
Expected: 第 1、3 个新用例 FAIL(specs 空 / 匹配逻辑未变),第 2 个 PASS(现状即
如此——它是防回归钉子)

- [ ] **Step 3: Implement**

`csm_core/brand_memory/resolver.py`:

import 行改为:

```python
from .identity import BRAND_ALIASES, canonical_brand, note_identity, parse_brand_model
```

在 `_model_in_stem` 后新增匹配辅助:

```python
def _spec_model_matches(
    full_model: str, brand: str, model: str, aliases: dict[str, list[str]],
) -> bool:
    # 调用方传入的 model 有两种历史形态:full-stem(DARZD9)或剥品牌(DS18)。
    # note_identity 恒返 full-stem → 直等,或剥掉本品牌任一别名前缀后相等。
    if full_model == model:
        return True
    for al in _brand_folder_aliases(brand, aliases):
        if full_model.startswith(al) and full_model[len(al):] == model:
            return True
    return False
```

`resolve_memory` 循环里的产品参数分支(现 66-72 行)替换为:

```python
        # 产品参数：note_identity(frontmatter 优先)命中 —— 与 registry 同一判定链
        if "产品参数" in parts:
            ident = note_identity(note.id, note.frontmatter, aliases)
            if (ident is not None and ident[0] == brand
                    and _spec_model_matches(ident[1], brand, model, aliases)):
                specs = parse_spec_table(note.raw_body)
                certs = _certs_from_specs(specs)
            continue
```

模块 docstring 的 Mapping 注释首行补一句:「产品参数匹配走 note_identity,
未知品牌靠 frontmatter 命中(别名表不再是白名单)。」
(`parse_brand_model` 仍被 品牌产品测试结果 分支使用,import 保留。)

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/core/brand_memory/ tests/core/factcheck/ -v`
Expected: 全部 PASS(factcheck 消费 resolver 输出,一并验证零回归)

- [ ] **Step 5: Commit**

```bash
git add csm_core/brand_memory/resolver.py tests/core/brand_memory/test_resolver.py
git commit -m "fix(brand-memory): resolver 产品参数匹配走 note_identity,未知品牌参数不再恒空"
```

---

### Task 5: service 层 product_line + category 用真实产品线

**Files:**
- Modify: `sidecar/csm_sidecar/services/brand_memory_service.py:22-56`
- Test: `sidecar/tests/test_brand_memory_routes.py`

- [ ] **Step 1: Write the failing tests**

在 `sidecar/tests/test_brand_memory_routes.py` 中,`_vault` 函数追加一条净化器笔记
(函数体末尾加):

```python
    _w(root / "营销资料库/产品模块/空气净化器/产品参数/DARZD9-产品参数.md",
       "---\n产品: 空气净化器\n素材类型: 产品参数\n品牌: DARZ\n型号: DARZD9\n核心关键词: x\n---\n"
       "## 核心净化性能\n\n| 参数 | 数值 |\n|--|--|\n| 颗粒物CADR | 512m³/h |\n")
```

文件末尾追加用例:

```python
def test_list_carries_product_line(client: TestClient, tmp_path):
    _vault(tmp_path)
    client.patch("/api/config", json={"vault_root": str(tmp_path)})
    body = client.get("/api/brand-memory").json()
    by_model = {m["model"]: m for m in body["models"]}
    assert by_model["CEWEYDS18"]["product_line"] == "吸尘器"
    assert by_model["DARZD9"]["product_line"] == "空气净化器"


def test_detail_unknown_brand_has_specs_and_line_category(client: TestClient, tmp_path):
    # 未知品牌净化器:specs 非空(根因修复端到端)+ category=真实产品线 + section 下发
    _vault(tmp_path)
    client.patch("/api/config", json={"vault_root": str(tmp_path)})
    d = client.get("/api/brand-memory/DARZD9").json()
    assert d["category"] == "空气净化器"
    assert d["specs"]["颗粒物CADR"]["numbers"] == [512.0]
    assert d["specs"]["颗粒物CADR"]["section"] == "核心净化性能"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest sidecar/tests/test_brand_memory_routes.py -v`
Expected: 两个新用例 FAIL(product_line 键不存在 / category=="吸尘器")

- [ ] **Step 3: Implement**

`sidecar/csm_sidecar/services/brand_memory_service.py` 改 `_resolve_one` 与 `list_models`:

```python
def _resolve_one(
    model_full: str, registry: BrandRegistry, index: VaultIndex,
    category: str, own_brands: set[str],
) -> tuple[str, BrandModelMemory] | None:
    brand = registry.brand_of(model_full)
    if brand is None:
        return None
    # registry 存 full-stem（CEWEYDS18）；已知品牌剥前缀（DS18）保竞品 intro 文件名
    # 匹配质量；未知品牌回退 full-stem —— resolver 的 spec 匹配两种形式都接受。
    parsed = parse_brand_model(model_full)
    resolver_model = parsed[1] if parsed is not None else model_full
    # category = 真实产品线(路径推导),registry 不知道时才用调用方兜底值。
    line = registry.line_of(model_full) or category
    mem = resolve_memory(brand, resolver_model, line, index, own_brands=own_brands)
    return brand, mem
```

`list_models` 的 out.append 加一键:

```python
        out.append({
            "model": model_full,
            "brand": brand,
            "role": mem.role,            # 主推 | 竞品
            "product_line": mem.category,
            "coverage": mem.coverage,
        })
```

(`get_model_detail` 无须改——`d = mem.model_dump()` 已带 category=真实产品线。)

- [ ] **Step 4: Run tests**

Run: `python -m pytest sidecar/tests/test_brand_memory_routes.py sidecar/tests/test_brand_memory_service.py -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add sidecar/csm_sidecar/services/brand_memory_service.py sidecar/tests/test_brand_memory_routes.py
git commit -m "feat(sidecar): 型号列表带 product_line,detail category 用真实产品线"
```

---

### Task 6: 录入树 — 全目录枚举 + 空文件夹借兄弟模板

**Files:**
- Modify: `csm_core/vault/folder_profile.py`
- Test: `tests/core/vault/test_folder_profile.py`
- Test: `sidecar/tests/test_vault_writer_routes.py`

- [ ] **Step 1: Write the failing tests (csm_core)**

在 `tests/core/vault/test_folder_profile.py` 末尾追加:

```python
def _two_line_vault(root: Path) -> None:
    # 吸尘器线有笔记;空气净化器线是空骨架(真实 vault 2026-07 形态)
    _write(root, "引言模块/吸尘器/人设引入/引言-人设①.md",
           "---\n产品: 吸尘器\n素材类型: 人设引入\n核心关键词:\n  - 人设\n---\n\n① 大家好\n\n② 我是…\n")
    (root / "引言模块/空气净化器/人设引入").mkdir(parents=True, exist_ok=True)
    (root / "总结模块/空气净化器/对比总结").mkdir(parents=True, exist_ok=True)
    (root / ".obsidian/plugins").mkdir(parents=True, exist_ok=True)


def test_tree_includes_intermediate_and_empty_dirs(tmp_path):
    _two_line_vault(tmp_path)
    idx = scan_vault(tmp_path)
    rels = {p.rel_folder for p in fp.list_writable_folders(idx)}
    assert "引言模块" in rels                       # 中间层
    assert "引言模块/吸尘器" in rels
    assert "引言模块/空气净化器/人设引入" in rels    # 空文件夹
    assert not any(r.startswith(".obsidian") for r in rels)  # 隐藏目录整树排除


def test_empty_dir_borrows_sibling_line_template(tmp_path):
    _two_line_vault(tmp_path)
    idx = scan_vault(tmp_path)
    by_rel = {p.rel_folder: p for p in fp.list_writable_folders(idx)}
    prof = by_rel["引言模块/空气净化器/人设引入"]
    assert prof.template_from == "引言模块/吸尘器/人设引入"
    assert prof.sample_count == 0
    assert prof.body_shape == "variants"
    assert prof.frontmatter_keys[:3] == ["产品", "素材类型", "核心关键词"]
    assert prof.defaults["产品"] == "空气净化器"     # 产品默认值换成新产品线
    assert prof.defaults["素材类型"] == "人设引入"


def test_empty_dir_without_sibling_gets_generic_template(tmp_path):
    _two_line_vault(tmp_path)
    idx = scan_vault(tmp_path)
    by_rel = {p.rel_folder: p for p in fp.list_writable_folders(idx)}
    prof = by_rel["总结模块/空气净化器/对比总结"]     # 吸尘器线没有 对比总结
    assert prof.template_from is None
    assert prof.frontmatter_keys == ["产品", "素材类型", "核心关键词"]
    assert prof.body_shape == "variants"


def test_borrow_swap_guard_same_line_other_module(tmp_path):
    # 兄弟差异段不是产品线时(同线跨模块借),产品默认值不被错误替换
    _write(tmp_path, "科普模块/空气净化器/挑选攻略/科普①.md",
           "---\n产品: 空气净化器\n素材类型: 科普选购\n核心关键词:\n  - 选购\n---\n\n① 看CADR\n\n② 看CCM\n")
    (tmp_path / "引言模块/空气净化器/挑选攻略").mkdir(parents=True, exist_ok=True)
    idx = scan_vault(tmp_path)
    by_rel = {p.rel_folder: p for p in fp.list_writable_folders(idx)}
    prof = by_rel["引言模块/空气净化器/挑选攻略"]
    assert prof.template_from == "科普模块/空气净化器/挑选攻略"
    # 差异段是模块名(引言模块≠产品默认值)→ 不替换,保持 空气净化器
    assert prof.defaults["产品"] == "空气净化器"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/core/vault/test_folder_profile.py -v`
Expected: 4 个新用例 FAIL(中间层/空目录不在列表;template_from 属性不存在)

- [ ] **Step 3: Implement**

`csm_core/vault/folder_profile.py`:

模块 docstring 补一段:「2026-07 起 vault 是多产品线布局(模块/<产品线>/子类),树
枚举走文件系统全目录(含中间层与空目录);空目录借"同叶名、同深度、恰差一段"的
兄弟目录模板,产品默认值随差异段替换。」

`FolderProfile` 加字段(`material_types` 之后):

```python
    template_from: str | None = None   # 空目录借模板的来源目录(rel);非借用 None
```

顶部 import 加 `import os`。

`list_writable_folders` 整体替换为:

```python
def _all_dirs(root) -> list[str]:
    """vault 根下全部非隐藏目录(rel, '/'-joined),点开头目录整棵剪枝。"""
    out: list[str] = []
    for dirpath, dirnames, _ in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        for d in dirnames:
            rel = os.path.relpath(os.path.join(dirpath, d), root)
            out.append(rel.replace(os.sep, "/"))
    return sorted(out)


def _borrow_profile(rel: str, profiled: dict[str, FolderProfile]) -> FolderProfile:
    """空目录模板:借"同叶名、同深度、恰差一段"的兄弟;取样本最多者。

    产品默认值仅当兄弟的差异段==其 产品 默认值时才替换(即差异段确为产品线);
    同线跨模块借用时差异段是模块名,不动 产品。无兄弟 → 通用三件套。
    """
    segs = rel.split("/")
    best: FolderProfile | None = None
    best_target_seg = ""
    best_cand_seg = ""
    for cand_rel, prof in profiled.items():
        csegs = cand_rel.split("/")
        if len(csegs) != len(segs) or csegs[-1] != segs[-1]:
            continue
        diffs = [i for i in range(len(segs)) if csegs[i] != segs[i]]
        if len(diffs) != 1:
            continue
        if best is None or prof.sample_count > best.sample_count:
            best = prof
            best_target_seg = segs[diffs[0]]
            best_cand_seg = csegs[diffs[0]]
    if best is None:
        return FolderProfile(
            rel_folder=rel, frontmatter_keys=list(_LEAD_KEYS),
            body_shape="variants")
    defaults = dict(best.defaults)
    if defaults.get("产品") == best_cand_seg:
        defaults["产品"] = best_target_seg
    return FolderProfile(
        rel_folder=rel,
        frontmatter_keys=list(best.frontmatter_keys),
        defaults=defaults,
        body_shape=best.body_shape,
        sample_count=0,
        material_types=list(best.material_types),
        template_from=best.rel_folder,
    )


def list_writable_folders(index: VaultIndex) -> list[FolderProfile]:
    """vault 全部非隐藏目录:有直属笔记的照常 profile,空目录借兄弟模板。"""
    with_notes: dict[str, None] = {}
    for n in index.notes:
        rel = _rel_folder_of(n, index.root)
        if rel:
            with_notes.setdefault(rel, None)
    profiled = {r: profile_folder(index, r) for r in with_notes}
    out: list[FolderProfile] = []
    for rel in _all_dirs(index.root):
        out.append(profiled.get(rel) or _borrow_profile(rel, profiled))
    return out
```

注意保序:`_all_dirs` 返回按路径排序,树渲染父在子前。

- [ ] **Step 4: Run csm_core tests**

Run: `python -m pytest tests/core/vault/ -v`
Expected: 全部 PASS(既有 `test_list_writable_folders` 断言用 `in`,兼容新增行)

- [ ] **Step 5: Write & run sidecar route test**

`sidecar/tests/test_vault_writer_routes.py` 末尾追加:

```python
def test_writable_folders_includes_empty_with_borrowed_template(client, tmp_path):
    root = _seed_vault(tmp_path)
    (root / "科普模块/空气净化器/挑选攻略").mkdir(parents=True, exist_ok=True)
    _use_vault(root)
    folders = {f["rel_folder"]: f for f in
               client.get("/api/vault/writable-folders").json()["folders"]}
    empty = folders["科普模块/空气净化器/挑选攻略"]
    assert empty["sample_count"] == 0
    assert empty["template_from"] == "科普模块/吸尘器/挑选攻略"
    assert empty["defaults"]["产品"] == "空气净化器"
    assert "科普模块/空气净化器" in folders          # 中间层也在树里
```

Run: `python -m pytest sidecar/tests/test_vault_writer_routes.py -v`
Expected: 全部 PASS(service 的 asdict 自动带上 template_from)

- [ ] **Step 6: Commit**

```bash
git add csm_core/vault/folder_profile.py tests/core/vault/test_folder_profile.py sidecar/tests/test_vault_writer_routes.py
git commit -m "feat(vault): 录入树全目录枚举,空文件夹借兄弟产品线模板"
```

---

### Task 7: 前端 modelSpecs 重写 — 按真实 H2 分组 + 摘要卡分线

**Files:**
- Modify: `frontend/src/stores/materials.ts:18-21`(SpecValue/BrandModelRow 类型)
- Rewrite: `frontend/src/components/materials/modelSpecs.ts`
- Rewrite: `frontend/src/components/materials/__tests__/modelSpecs.spec.ts`

- [ ] **Step 1: 更新 store 类型**

`frontend/src/stores/materials.ts`:

```ts
export interface SpecValue {
  field: string; raw: string; numbers: number[]; unit: string;
  is_approx: boolean; is_placeholder: boolean;
  section: string;               // 所属 H2 小节名(后端 v2 起下发)
}
export interface BrandModelRow {
  model: string;       // full-stem，如 CEWEYDS18
  brand: string;
  role: string;        // 主推 | 竞品
  product_line: string; // 吸尘器 | 空气净化器 | 未分类…
  coverage: Coverage;
}
```

- [ ] **Step 2: Rewrite the spec file (failing tests)**

`frontend/src/components/materials/__tests__/modelSpecs.spec.ts` 整文件替换:

```ts
import { describe, it, expect } from "vitest";
import {
  buildSpecGroups,
  buildStats,
  productHref,
  stripBrand,
} from "@/components/materials/modelSpecs";
import type { SpecValue } from "@/stores/materials";

function sv(over: Partial<SpecValue> & { raw: string }): SpecValue {
  return {
    field: over.field ?? "x",
    raw: over.raw,
    numbers: over.numbers ?? [],
    unit: over.unit ?? "",
    is_approx: over.is_approx ?? false,
    is_placeholder: over.is_placeholder ?? false,
    section: over.section ?? "",
  };
}

describe("modelSpecs.buildSpecGroups(按笔记真实 H2 小节分组)", () => {
  // 净化器形态:字段带 section,插入序 = 笔记顺序
  const specs: Record<string, SpecValue> = {
    "价格": sv({ raw: "899", numbers: [899], section: "基础信息" }),
    "产品链接": sv({ raw: "https://x.com/1", section: "基础信息" }),
    "颗粒物CADR": sv({ raw: "512m³/h", numbers: [512], section: "核心净化性能" }),
    "甲醛CADR": sv({ raw: "308m³/h", numbers: [308], section: "核心净化性能" }),
    "净化方式": sv({ raw: "无", is_placeholder: true, section: "核心净化性能" }),
  };

  it("小节即分组,保持笔记顺序,字段名原样展示", () => {
    const { groups } = buildSpecGroups(specs);
    expect(groups.map((g) => g.title)).toEqual(["基础信息", "核心净化性能"]);
    const perf = groups[1];
    expect(perf.rows.map((r) => r.label)).toEqual(["颗粒物CADR", "甲醛CADR", "净化方式"]);
    expect(perf.rows[0].value).toBe("512m³/h");
    expect(perf.filled).toBe("2 / 3");
  });

  it("占位字段显示「—」并标 dim;进度分母=真实字段总数", () => {
    const { groups, filled, total } = buildSpecGroups(specs);
    const ph = groups[1].rows.find((r) => r.label === "净化方式")!;
    expect(ph.dim).toBe(true);
    expect(ph.value).toBe("—");
    expect(total).toBe(5);
    expect(filled).toBe(4);
  });

  it("无 section 的字段(旧数据兜底)归入「参数」组", () => {
    const { groups } = buildSpecGroups({ "怪字段": sv({ raw: "1" }) });
    expect(groups[0].title).toBe("参数");
  });

  it("空 specs → 空 groups(上层渲染空态)", () => {
    const { groups, filled, total } = buildSpecGroups({});
    expect(groups).toEqual([]);
    expect(filled).toBe(0);
    expect(total).toBe(0);
  });
});

describe("modelSpecs.buildStats(分产品线精选 + 通用兜底)", () => {
  it("吸尘器精选:数字+设计单位,避免「70dB」双单位;价格加 ¥", () => {
    const specs: Record<string, SpecValue> = {
      "价格": sv({ raw: "1999", numbers: [1999] }),
      "最低噪音（dB）": sv({ raw: "70dB", numbers: [70] }),
      "主机重量(kg)": sv({ raw: "1.5kg", numbers: [1.5] }),
    };
    const stats = buildStats(specs, "吸尘器");
    expect(stats.find((s) => s.label === "价格")!.value).toBe("¥1999");
    expect(stats.find((s) => s.label === "最低噪音")!.value).toBe("70 dB");
    expect(stats.find((s) => s.label === "整机重量")!.value).toBe("1.5 kg");
    expect(stats.find((s) => s.label === "吸力")!.value).toBe("—"); // 缺失恒 5 项
    expect(stats).toHaveLength(5);
  });

  it("净化器精选:显示 raw 原文(区间值/复合单位不失真)", () => {
    const specs: Record<string, SpecValue> = {
      "价格": sv({ raw: "899", numbers: [899] }),
      "颗粒物CADR": sv({ raw: "512m³/h", numbers: [512] }),
      "最低档声功率级噪音": sv({ raw: "30-60dB", numbers: [30, 60] }),
      "适用面积": sv({ raw: "20-80㎡", numbers: [20, 80] }),
    };
    const stats = buildStats(specs, "空气净化器");
    expect(stats.find((s) => s.label === "颗粒物CADR")!.value).toBe("512m³/h");
    expect(stats.find((s) => s.label === "噪音")!.value).toBe("30-60dB");
    expect(stats.find((s) => s.label === "适用面积")!.value).toBe("20-80㎡");
    expect(stats.find((s) => s.label === "价格")!.value).toBe("¥899");
  });

  it("未知产品线兜底:价格优先 + 前 4 个短数值字段,排除链接/占位/长文本", () => {
    const specs: Record<string, SpecValue> = {
      "产品链接": sv({ raw: "https://x.com/9", numbers: [9] }),
      "价格": sv({ raw: "599", numbers: [599] }),
      "转速": sv({ raw: "3000rpm", numbers: [3000] }),
      "描述": sv({ raw: "这是一段很长很长的描述文本超过限制", numbers: [1] }),
      "缺口": sv({ raw: "无", is_placeholder: true }),
      "档位": sv({ raw: "3档", numbers: [3] }),
    };
    const stats = buildStats(specs, "扫地机器人");
    expect(stats[0]).toEqual({ label: "价格", value: "¥599", dim: false });
    expect(stats.map((s) => s.label)).toEqual(["价格", "转速", "档位"]);
  });

  it("未知产品线无可用字段 → 空数组(上层隐藏 stat 行)", () => {
    expect(buildStats({}, "扫地机器人")).toEqual([]);
  });
});

describe("modelSpecs.productHref", () => {
  it("已是完整 URL 直接用,不重复拼 https", () => {
    const specs = { "产品链接": sv({ raw: "https://item.jd.com/x.html" }) };
    expect(productHref(specs)).toBe("https://item.jd.com/x.html");
  });
  it("裸链接补 https://", () => {
    const specs = { "产品链接": sv({ raw: "item.jd.com/x.html" }) };
    expect(productHref(specs)).toBe("https://item.jd.com/x.html");
  });
  it("占位/缺失返回 null", () => {
    expect(productHref({ "产品链接": sv({ raw: "无", is_placeholder: true }) })).toBeNull();
    expect(productHref({})).toBeNull();
  });
  it("非 URL 描述文本返回 null(不拼成死链)", () => {
    expect(productHref({ "产品链接": sv({ raw: "京东搜索 XXX" }) })).toBeNull();
    expect(productHref({ "产品链接": sv({ raw: "见官网" }) })).toBeNull();
  });
});

describe("modelSpecs.stripBrand", () => {
  it("去掉品牌前缀", () => {
    expect(stripBrand("CEWEYDS18", "CEWEY")).toBe("DS18");
    expect(stripBrand("DARZD9", "DARZ")).toBe("D9");
  });
  it("不含前缀时原样返回", () => {
    expect(stripBrand("V15", "戴森")).toBe("V15");
  });
});
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/components/materials/__tests__/modelSpecs.spec.ts`
Expected: FAIL(buildSpecGroups 仍按 6 组本体;buildStats 签名不带产品线)

- [ ] **Step 4: Rewrite `modelSpecs.ts`**

`frontend/src/components/materials/modelSpecs.ts` 整文件替换:

```ts
/**
 * 品牌型号页参数展示(素材库 V3 · 产品线通用化,2026-07-14 spec)。
 *
 * 分组不再用前端硬编码本体(V2 的设计稿 6 组已废,用户拍板):后端 SpecValue
 * 自带 section(笔记真实 H2 小节名),按它分组、保持笔记顺序 —— vault 即真相源,
 * 任何产品线(吸尘器 7 节/净化器 5 节/未来新线)自动正确。
 *
 * 摘要卡是唯一保留的每线小配置(5 个头条数字的展示偏好):已知产品线精选,
 * 未知产品线兜底「价格 + 前 4 个短数值字段」;缺配置只影响观感不影响可用。
 */
import type { SpecValue } from "@/stores/materials";

export interface SpecRow {
  label: string;
  value: string;
  dim: boolean; // 占位/未收集 → 显示「—」、弱化配色
}
export interface SpecGroup {
  idx: number;
  title: string;
  rows: SpecRow[];
  filled: string; // "3 / 5"
}
export interface StatItem {
  label: string;
  value: string;
  dim: boolean;
}

interface StatSpec {
  key: string;      // 规范化后命中真实字段
  label: string;
  unit?: string;    // 指定时用 numbers[0]+unit(避免 "70dB"+dB 双单位)
  money?: boolean;  // ¥ 前缀
}

/** 已知产品线的摘要卡精选;未知线走 genericStats 兜底。 */
const STATS_BY_LINE: Record<string, StatSpec[]> = {
  吸尘器: [
    { key: "价格", label: "价格", money: true },
    { key: "吸力(AW)", label: "吸力", unit: "AW" },
    { key: "真空度(Pa)", label: "真空度", unit: "Pa" },
    { key: "最低噪音(dB)", label: "最低噪音", unit: "dB" },
    { key: "主机重量(kg)", label: "整机重量", unit: "kg" },
  ],
  空气净化器: [
    { key: "价格", label: "价格", money: true },
    { key: "颗粒物CADR", label: "颗粒物CADR" },
    { key: "甲醛CADR", label: "甲醛CADR" },
    { key: "最低档声功率级噪音", label: "噪音" },
    { key: "适用面积", label: "适用面积" },
  ],
};

/** 吃掉空格 + 全角括号→半角 + 小写,跨「配置 key vs 真实字段」匹配。 */
export function normKey(s: string): string {
  return s
    .replace(/\s+/g, "")
    .replace(/（/g, "(")
    .replace(/）/g, ")")
    .toLowerCase();
}

function specMap(specs: Record<string, SpecValue>): Map<string, SpecValue> {
  const map = new Map<string, SpecValue>();
  for (const k of Object.keys(specs)) map.set(normKey(k), specs[k]);
  return map;
}

/** 数字格式化：220.0 → "220"、1.5 → "1.5"（JS Number 无 int/float 之分，String 即可）。 */
function fnum(n: number): string {
  return String(n);
}

/**
 * 按 SpecValue.section 分组(笔记真实 H2 小节),保持笔记原始顺序。
 * 进度:分母 = 真实字段总数,分子 = 非占位字段数。空 specs → 空 groups。
 */
export function buildSpecGroups(specs: Record<string, SpecValue>): {
  groups: SpecGroup[];
  filled: number;
  total: number;
} {
  const groups: SpecGroup[] = [];
  const byTitle = new Map<string, SpecGroup>();
  let filled = 0;
  let total = 0;

  for (const k of Object.keys(specs)) {
    const s = specs[k];
    const title = s.section || "参数"; // 旧缓存/无小节笔记兜底
    let g = byTitle.get(title);
    if (!g) {
      g = { idx: groups.length, title, rows: [], filled: "" };
      byTitle.set(title, g);
      groups.push(g);
    }
    const dim = s.is_placeholder;
    total += 1;
    if (!dim) filled += 1;
    g.rows.push({ label: k, value: dim ? "—" : s.raw, dim });
  }
  for (const g of groups) {
    g.filled = `${g.rows.filter((r) => !r.dim).length} / ${g.rows.length}`;
  }
  return { groups, filled, total };
}

function curatedStats(specs: Record<string, SpecValue>, curated: StatSpec[]): StatItem[] {
  const map = specMap(specs);
  return curated.map((s) => {
    const spec = map.get(normKey(s.key));
    const dim = !spec || spec.is_placeholder;
    if (dim) return { label: s.label, value: "—", dim: true };
    let value: string;
    if (s.money) {
      value = spec!.numbers.length ? "¥" + fnum(spec!.numbers[0]) : spec!.raw;
    } else if (s.unit && spec!.numbers.length) {
      value = fnum(spec!.numbers[0]) + " " + s.unit;
    } else {
      value = spec!.raw; // 无单位配置 → raw 原文(区间/复合单位不失真)
    }
    return { label: s.label, value, dim: false };
  });
}

function genericStats(specs: Record<string, SpecValue>): StatItem[] {
  const out: StatItem[] = [];
  const price = specMap(specs).get(normKey("价格"));
  if (price && !price.is_placeholder) {
    out.push({
      label: "价格",
      value: price.numbers.length ? "¥" + fnum(price.numbers[0]) : price.raw,
      dim: false,
    });
  }
  for (const k of Object.keys(specs)) {
    if (out.length >= 5) break;
    if (normKey(k) === normKey("价格") || k.includes("链接")) continue;
    const s = specs[k];
    if (s.is_placeholder || !s.numbers.length || s.raw.length > 12) continue;
    out.push({ label: k, value: s.raw, dim: false });
  }
  return out;
}

/** 摘要卡:已知产品线精选(恒 5 项,缺失显「—」);未知线兜底(有几项显几项)。 */
export function buildStats(
  specs: Record<string, SpecValue>,
  productLine: string,
): StatItem[] {
  const curated = STATS_BY_LINE[productLine];
  if (curated) return curatedStats(specs, curated);
  return genericStats(specs);
}

/**
 * 商品页链接：真实值已是完整 URL 时直接用；裸链接（像域名：含点、无空白）补 https://；
 * 否则视为描述文本而非链接，返回 null（避免拼出打不开的死链或 `https://https://`）。
 */
export function productHref(specs: Record<string, SpecValue>): string | null {
  const map = specMap(specs);
  const spec = map.get(normKey("产品链接"));
  if (!spec || spec.is_placeholder || !spec.raw.trim()) return null;
  const raw = spec.raw.trim();
  if (/^https?:\/\//i.test(raw)) return raw;
  // 裸链接必须像域名：含点、无空白；否则是描述文本不是链接。
  if (/\s/.test(raw) || !raw.includes(".")) return null;
  return "https://" + raw;
}

/** 去掉型号里的品牌前缀：strip("CEWEYDS18","CEWEY") → "DS18"。 */
export function stripBrand(name: string, brand: string): string {
  return (name.startsWith(brand) ? name.slice(brand.length) : name) || name;
}
```

- [ ] **Step 5: Run tests**

Run: `cd frontend && npx vitest run src/components/materials/__tests__/modelSpecs.spec.ts`
Expected: 全部 PASS

- [ ] **Step 6: Commit**

```bash
git add frontend/src/stores/materials.ts frontend/src/components/materials/modelSpecs.ts frontend/src/components/materials/__tests__/modelSpecs.spec.ts
git commit -m "feat(前端): 参数按笔记真实 H2 小节分组,摘要卡分产品线精选+通用兜底"
```

---

### Task 8: ModelsTab 产品线筛选 + 空态 + MaterialsView 汇总联动

**Files:**
- Modify: `frontend/src/stores/materials.ts`(加 lineFilter)
- Modify: `frontend/src/components/materials/ModelsTab.vue`
- Modify: `frontend/src/views/MaterialsView.vue:34-39`

- [ ] **Step 1: store 加 lineFilter**

`frontend/src/stores/materials.ts` — `useMaterials` 里 `models` 定义后加:

```ts
  const lineFilter = ref<string>("全部");   // 品牌型号页产品线筛选(汇总栏联动)
```

return 对象里在 `models,` 后加 `lineFilter,`。

- [ ] **Step 2: ModelsTab script 改造**

`frontend/src/components/materials/ModelsTab.vue` `<script setup>`:

顶部 import 加:

```ts
import Select from "@/components/ui/Select.vue";
```

文件头注释第 3-5 行改为:

```
 * 品牌型号页（素材库 V3）：左型号列表（产品线筛选·主推/竞品·品牌分组·搜索）
 * + 右详情（摘要卡 + 按笔记真实 H2 小节分组的参数卡）。数据接 useMaterials，
 * 分组/摘要逻辑见 modelSpecs.ts（V3 起数据驱动，设计稿 6 组本体已废）。
```

`const q = computed(...)` 之前加:

```ts
// ── 产品线筛选(store 持有,汇总栏联动) ─────────────────────────────
const lineOptions = computed(() => {
  const counts = new Map<string, number>();
  for (const r of m.models) {
    const line = r.product_line || "未分类";
    counts.set(line, (counts.get(line) ?? 0) + 1);
  }
  const opts = [{ value: "全部", label: `全部产品线（${m.models.length}）` }];
  for (const [line, n] of counts) opts.push({ value: line, label: `${line}（${n}）` });
  return opts;
});
const lineModels = computed(() =>
  m.lineFilter === "全部"
    ? m.models
    : m.models.filter((r) => (r.product_line || "未分类") === m.lineFilter),
);
```

`sideSections` 里两处 `m.models.filter` 改为 `lineModels.value.filter`:

```ts
  const primary = lineModels.value.filter((r) => r.role === "主推" && match(r.brand, r.model));
  const comps = lineModels.value.filter((r) => r.role !== "主推" && match(r.brand, r.model));
```

`stats` computed 改为传产品线(category 即产品线,Task 5 起后端保证):

```ts
const stats = computed(() => (detail.value ? buildStats(detail.value.specs, detail.value.category) : []));
```

`href` computed 之后加空态判定:

```ts
const hasSpecs = computed(() => !!detail.value && Object.keys(detail.value.specs).length > 0);
```

- [ ] **Step 3: ModelsTab template 改造**

(a) 左栏搜索框容器(`<div class="flex-none px-3.5 pb-2.5 pt-3.5">`)内、搜索 `<div class="relative">` 之前加:

```html
        <Select
          v-if="lineOptions.length > 2"
          v-model="m.lineFilter"
          :options="lineOptions"
          size="sm"
          min-width="100%"
          class="mb-2 w-full"
        />
```

(仅一条产品线时不显示下拉——`lineOptions.length > 2` = 「全部」+ ≥2 条线。)

(b) 摘要卡进度块(`参数 {{ filled }} / {{ total }}` 所在 `<div class="flex items-center gap-2">`)外层加 `v-if="hasSpecs"`;并在其后(仍在 `ml-auto` 容器内)加:

```html
              <span v-if="!hasSpecs" class="text-[11.5px]" style="color: var(--ink-4)">暂无参数笔记</span>
```

(c) stat 行容器 `<div class="flex min-w-0 items-stretch overflow-x-auto">` 加 `v-if="stats.length"`。

(d) 分组锚点导航 `<div class="flex flex-none items-center gap-[7px]">` 与参数分组卡滚动容器 `<div ref="scrollRef" ...>` 都加 `v-if="hasSpecs"`;滚动容器之后加空态块:

```html
        <div v-if="!hasSpecs" class="grid flex-1 place-items-center text-sm" style="color: var(--ink-4)">
          该型号暂无产品参数笔记 · 可在「录入」页选择对应产品线的「产品参数」文件夹补录
        </div>
```

- [ ] **Step 4: MaterialsView 汇总联动**

`frontend/src/views/MaterialsView.vue` 的 `summary` computed 替换为:

```ts
const summary = computed(() => {
  const pool = m.lineFilter === "全部"
    ? m.models
    : m.models.filter((r) => (r.product_line || "未分类") === m.lineFilter);
  const total = pool.length;
  if (!total) return "";
  const primary = pool.filter((r) => r.role === "主推").length;
  const prefix = m.lineFilter === "全部" ? "" : `${m.lineFilter} · `;
  return `${prefix}共 ${total} 个型号 · 主推 ${primary} · 竞品 ${total - primary}`;
});
```

- [ ] **Step 5: 类型检查 + 全量前端测试**

```powershell
cd frontend
npx vue-tsc -b
git checkout -- vite.config.js 2>$null   # vue-tsc 会 emit vite.config.js(见记忆)
npx vitest run
```

Expected: 类型 0 error,vitest 全绿。

- [ ] **Step 6: Commit**

```bash
git add frontend/src/stores/materials.ts frontend/src/components/materials/ModelsTab.vue frontend/src/views/MaterialsView.vue
git commit -m "feat(前端): 品牌型号页产品线筛选+无参数空态,汇总栏联动"
```

---

### Task 9: IntakeForm 借模板提示

**Files:**
- Modify: `frontend/src/stores/materials.ts:34-41`(FolderProfile 类型)
- Modify: `frontend/src/components/materials/IntakeForm.vue`

- [ ] **Step 1: FolderProfile 类型加字段**

`frontend/src/stores/materials.ts`:

```ts
export interface FolderProfile {
  rel_folder: string;
  frontmatter_keys: string[];
  defaults: Record<string, string>;
  body_shape: "variants" | "spec_table" | "unknown";
  sample_count: number;
  material_types: string[];
  template_from: string | null;   // 空文件夹借模板来源(v3 录入树)
}
```

- [ ] **Step 2: IntakeForm 树注释 + 借模板提示**

`frontend/src/components/materials/IntakeForm.vue`:

(a) 第 32 行注释改为:

```ts
// 素材树:后端已含中间层与空文件夹(空文件夹借兄弟产品线模板),按路径深度缩进渲染。
```

(b) template 里「录入素材」标题行(`mat-dir-pill` 所在 `<div class="flex flex-none items-center gap-2 ...">`)之后、可滚动表单区之前,插入借模板提示行:

```html
        <div v-if="selected.template_from" class="flex-none px-[var(--density-pad)] pt-1 text-[11px]" style="color: var(--ink-4)">
          空文件夹 · 表单模板借自「{{ selected.template_from }}」
        </div>
```

- [ ] **Step 3: 类型检查 + 测试**

```powershell
cd frontend
npx vue-tsc -b
git checkout -- vite.config.js 2>$null
npx vitest run
```

Expected: 0 error、全绿。

- [ ] **Step 4: Commit**

```bash
git add frontend/src/stores/materials.ts frontend/src/components/materials/IntakeForm.vue
git commit -m "feat(前端): 录入树空文件夹显示借模板来源提示"
```

---

### Task 10: 全量回归 + 真机验证

**Files:** 无新改动(验证任务)

- [ ] **Step 1: Python 全量**

```powershell
$env:PYTHONPATH = "D:\CSM\.claude\worktrees\inspiring-euclid-dfa60a;D:\CSM\.claude\worktrees\inspiring-euclid-dfa60a\sidecar"
python -m pytest tests/ -v
python -m pytest sidecar/tests/ -v   # 不在默认收集里,必须显式跑(见记忆)
```

Expected: 全绿(真机 integration 用例在本机也会跑,验证真实 vault 62 型号双线)。

- [ ] **Step 2: 前端全量**

```powershell
cd frontend && npx vitest run && npx vue-tsc -b
git checkout -- vite.config.js 2>$null
```

Expected: 全绿、0 类型错误。

- [ ] **Step 3: 真机冒烟(standalone 探针,不起 GUI)**

```powershell
python -c "
import sys; sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path
from csm_core.vault.scanner import scan_vault
from csm_core.vault.brand_registry import build_brand_registry
from csm_core.vault import folder_profile as fp
from csm_core.brand_memory.resolver import resolve_memory
root = Path(r'D:\家电组共享\DATA')
reg = build_brand_registry(root)
print('models:', len(reg.all_models()), 'DARZ line:', reg.line_of('DARZD9'))
idx = scan_vault(root)
mem = resolve_memory('DARZ', 'DARZD9', '空气净化器', idx, own_brands={'CEWEY','DARZ'})
print('DARZD9 specs:', len(mem.specs), 'sections:', sorted({v.section for v in mem.specs.values()}))
folders = fp.list_writable_folders(idx)
empty = [f for f in folders if f.sample_count == 0 and f.template_from]
print('folders:', len(folders), 'borrowed:', len(empty), empty[0].rel_folder if empty else '')
"
```

Expected: models ≥ 62;DARZ line=空气净化器;DARZD9 specs ≥ 20 且 sections 含
基础信息/核心净化性能;borrowed > 0。

- [ ] **Step 4: Commit(如有零星修复)**

```bash
git add -A && git commit -m "test: 全量回归修复"
```

---

### Task 11: 用户配置 own_brands 加 DARZ(部署步骤,最后做)

**Files:**
- Modify: `%LOCALAPPDATA%\CSM-Data\settings.json`(用户运行时数据,非仓库文件)

- [ ] **Step 1: 确认 CSM 应用未在运行**(运行中应用退出时会回写覆盖配置)

```powershell
Get-Process csm* -ErrorAction SilentlyContinue
```

若有进程,提醒用户先关闭应用再执行下一步。

- [ ] **Step 2: 修改 own_brands**

```powershell
$p = "$env:LOCALAPPDATA\CSM-Data\settings.json"
$cfg = Get-Content $p -Raw | ConvertFrom-Json
$cfg.brand_memory.own_brands = @("CEWEY", "DARZ")
$cfg | ConvertTo-Json -Depth 32 | Set-Content $p -Encoding UTF8
Get-Content $p -Raw | ConvertFrom-Json | ForEach-Object { $_.brand_memory.own_brands }
```

Expected: 输出 `CEWEY` `DARZ`。

- [ ] **Step 3: 提醒用户**

告知:重启 CSM 后 DARZ 型号显示「主推」;生成链对 DARZ 文章按自有品牌待遇。

---

## Self-Review 结论(计划作者自查)

- **Spec 覆盖:** ①→Task 1/3/4;②→Task 2/7 + 空态 Task 8;③→Task 3/5/8;
  ④→Task 11;⑤→Task 6/9;测试防线→各 task TDD + Task 10。无缺口。
- **类型一致:** `note_identity(stem, frontmatter, aliases)` 三处调用一致;
  `line_of` registry/service/测试一致;`template_from` 后端 dataclass/前端 ts 一致;
  `buildStats(specs, productLine)` 组件调用点已同步(Task 8 Step 2)。
- **占位符扫描:** 无 TBD/TODO;所有代码块完整可落。
