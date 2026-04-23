# Plan A: csm_core 核心引擎 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建 CSM 项目的纯 Python 核心引擎（零 Qt 依赖），从 Obsidian Vault 抽取素材、按模板 DSL 装配、调用 LLM 洗稿、导出 Markdown + 装配快照，并通过 CLI 端到端可跑。

**Architecture:** 分层纯 Python 包 `csm_core/`，按职责拆子模块（vault / template / assembler / llm / export / pipeline）。每子模块独立 TDD，使用 `tests/fixtures/mini_vault/` 小样本 Vault 作测试数据。对外暴露 `pipeline.generate(keyword, template_path)` 和 CLI `python -m csm_core "关键词" --template foo.json`。

**Tech Stack:** Python 3.11+ / Pydantic v2 / pytest / pytest-mock / httpx（LLM HTTP 调用）/ tenacity（重试）/ python-frontmatter（md 解析）/ click（CLI）

---

## File Structure

```
D:\CSM\
├─ csm_core/
│  ├─ __init__.py
│  ├─ __main__.py                    # CLI 入口
│  ├─ vault/
│  │  ├─ __init__.py
│  │  ├─ note_parser.py              # 解析单个 md：frontmatter + ①②③ 变体拆段
│  │  ├─ scanner.py                  # 扫描整个 Vault，产出 VaultIndex
│  │  └─ brand_registry.py           # 从 产品参数/ 文件名构建品牌-型号字典
│  ├─ template/
│  │  ├─ __init__.py
│  │  ├─ schema.py                   # Pydantic 模型：Template / Slot / Source
│  │  └─ loader.py                   # load_template / save_template
│  ├─ assembler/
│  │  ├─ __init__.py
│  │  ├─ plan.py                     # AssemblyPlan 数据结构（可序列化）
│  │  ├─ sampler.py                  # 两级随机采样：选笔记 → 抽变体
│  │  └─ constraints.py              # 跨槽位依赖求解（test_results_aligned）
│  ├─ llm/
│  │  ├─ __init__.py
│  │  ├─ client.py                   # LLMClient Protocol + 工厂函数
│  │  ├─ prompts.py                  # 三层 prompt 组合
│  │  └─ providers/
│  │     ├─ __init__.py
│  │     ├─ mock.py                  # 单元测试用
│  │     ├─ anthropic.py             # Claude API
│  │     └─ deepseek.py              # DeepSeek API（国内）
│  ├─ export/
│  │  ├─ __init__.py
│  │  └─ markdown.py                 # 导出 .md + .assembly.json
│  └─ pipeline.py                    # 端到端编排
├─ tests/
│  ├─ conftest.py                    # pytest fixtures（mini_vault 路径等）
│  ├─ core/
│  │  ├─ vault/
│  │  │  ├─ test_note_parser.py
│  │  │  ├─ test_scanner.py
│  │  │  └─ test_brand_registry.py
│  │  ├─ template/
│  │  │  ├─ test_schema.py
│  │  │  └─ test_loader.py
│  │  ├─ assembler/
│  │  │  ├─ test_plan.py
│  │  │  ├─ test_sampler.py
│  │  │  └─ test_constraints.py
│  │  ├─ llm/
│  │  │  ├─ test_prompts.py
│  │  │  └─ test_client.py
│  │  ├─ export/
│  │  │  └─ test_markdown.py
│  │  └─ test_pipeline.py
│  └─ fixtures/
│     └─ mini_vault/                 # 小样本 Vault
│        └─ 营销资料库/
│           ├─ 引言模块/吸尘器/痛点共鸣/*.md
│           ├─ 科普模块/吸尘器/挑选攻略/*.md
│           ├─ 产品模块/吸尘器/产品参数/*.md
│           ├─ 产品模块/吸尘器/希喂推荐内容/*.md
│           ├─ 产品模块/吸尘器/竞品推荐内容/*.md
│           └─ 测试项目模块/吸尘器/品牌产品测试结果/*.md
├─ templates/                         # 项目根目录，示例模板
│  └─ daogou-changjing-renqun.json
├─ pyproject.toml
├─ .gitignore
└─ README.md
```

---

## Task 0: 项目脚手架 + mini_vault fixture

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `README.md`, `csm_core/__init__.py`, `tests/__init__.py`, `tests/conftest.py`
- Create: 14 个 mini_vault fixture md 文件

- [ ] **Step 0.1: 初始化 git 并创建 .gitignore**

Run in `D:\CSM`:
```bash
git init
```

Create `D:\CSM\.gitignore`:
```
__pycache__/
*.pyc
.pytest_cache/
.venv/
venv/
*.egg-info/
dist/
build/
.coverage
htmlcov/
config/settings.json
config/vault_index.cache.json
output/
templates/.trash/
.vscode/
.idea/
```

- [ ] **Step 0.2: 创建 pyproject.toml**

Create `D:\CSM\pyproject.toml`:
```toml
[project]
name = "csm"
version = "0.1.0"
description = "Content SEO Maker - 基于 Obsidian Vault 的 SEO 文章生成工具"
requires-python = ">=3.11"
dependencies = [
    "pydantic>=2.6",
    "python-frontmatter>=1.1",
    "httpx>=0.27",
    "tenacity>=8.2",
    "click>=8.1",
    "anthropic>=0.39",
]

[project.optional-dependencies]
gui = [
    "PyQt6>=6.7",
    "PyQt-Fluent-Widgets[full]>=1.7",
]
dev = [
    "pytest>=8.0",
    "pytest-mock>=3.12",
    "pytest-cov>=5.0",
    "pytest-qt>=4.4",
]

[project.scripts]
csm = "csm_core.__main__:cli"

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
include = ["csm_core*"]

[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py"]
addopts = "-v --tb=short"
markers = [
    "integration: 真实外部 API 调用测试（默认不跑）",
]
```

- [ ] **Step 0.3: 创建包初始化文件**

Create `D:\CSM\csm_core\__init__.py`:
```python
"""CSM core engine (no Qt dependency)."""
__version__ = "0.1.0"
```

Create empty `D:\CSM\tests\__init__.py`.

Create `D:\CSM\tests\conftest.py`:
```python
from pathlib import Path
import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"
MINI_VAULT = FIXTURES_DIR / "mini_vault" / "营销资料库"


@pytest.fixture
def mini_vault_path() -> Path:
    return MINI_VAULT
```

- [ ] **Step 0.4: 创建 mini_vault fixture 笔记**

Create the following 14 fixture markdown files exactly as specified:

`tests/fixtures/mini_vault/营销资料库/引言模块/吸尘器/痛点共鸣/引言-吸尘器-毛发缠绕.md`:
```markdown
---
产品: 吸尘器
素材类型: 引言
组件类型: 痛点共鸣
情绪钩子: 烦躁
核心关键词: [毛发, 缠绕, 吸尘器]
---

① 每次吸完地板都要蹲下来拔刷头上的头发，五分钟清完地一分钟变两分钟清毛发。

② 养宠家庭最怕吸尘器，吸力越大毛发缠得越紧，最后工具人自己动手拆机。

③ 明明买的是"懒人神器"，结果每次用完都像做了场产后清理手术。
```

`tests/fixtures/mini_vault/营销资料库/引言模块/吸尘器/痛点共鸣/引言-吸尘器-吸力衰减.md`:
```markdown
---
产品: 吸尘器
素材类型: 引言
组件类型: 痛点共鸣
情绪钩子: 失望
核心关键词: [吸力, 衰减, 续航]
---

① 刚买来吸力猛得像台风，用了半年变电扇，这不是吸尘器是除尘毯。

② 厂家标称 20000Pa 巅峰吸力，实际用三个月电池满电都吸不起一根头发。
```

`tests/fixtures/mini_vault/营销资料库/科普模块/吸尘器/挑选攻略/吸尘器-吸力AW和Pa参数选购指南.md`:
```markdown
---
产品: 吸尘器
素材类型: 科普原理解析
核心关键词: [吸力, AW, Pa, 选购]
---

## 【选购指南】AW 和 Pa 到底看哪个

① AW（空气瓦特）代表综合吸力，能同时反映风量和真空度，建议大于 180AW 为家用合格线。

② Pa（帕）只反映真空度，数字好看但不代表实际吸附力，建议配合 AW 一起参考。
```

`tests/fixtures/mini_vault/营销资料库/科普模块/吸尘器/挑选攻略/吸尘器-吸头数量选择.md`:
```markdown
---
产品: 吸尘器
素材类型: 科普原理解析
核心关键词: [吸头, 配件, 场景]
---

## 【选购指南】吸头配几件够用

① 地毯刷 + 软毛刷 + 缝隙吸头是三件套基础配置，多出来的"豪华"刷头多数吃灰。

② 养宠家庭强烈建议额外配电动除尘螨刷头，床垫沙发深度清洁靠它。
```

`tests/fixtures/mini_vault/营销资料库/科普模块/吸尘器/挑选攻略/吸尘器-续航参数选择.md`:
```markdown
---
产品: 吸尘器
素材类型: 科普原理解析
核心关键词: [续航, 电池, 充电]
---

## 【选购指南】续航多少才够用

① 60-80 平米家庭选 40 分钟以上续航即可，标称 60 分钟多为最低档数据。

② 双电池设计比单颗大电池更实用，充一颗用一颗不受限。
```

`tests/fixtures/mini_vault/营销资料库/产品模块/吸尘器/产品参数/CEWEYDS18-产品参数.md`:
```markdown
---
产品: 吸尘器
素材类型: 产品推荐理由
品牌: CEWEY
型号: CEWEYDS18
核心关键词: [CEWEY, DS18, 参数]
---

吸力: 220AW
续航: 60 分钟
噪音: 72dB
```

`tests/fixtures/mini_vault/营销资料库/产品模块/吸尘器/产品参数/戴森V15-产品参数.md`:
```markdown
---
产品: 吸尘器
素材类型: 产品推荐理由
品牌: 戴森
型号: 戴森V15
核心关键词: [戴森, V15, 参数]
---

吸力: 240AW
续航: 60 分钟
噪音: 78dB
```

`tests/fixtures/mini_vault/营销资料库/产品模块/吸尘器/产品参数/小狗T12-产品参数.md`:
```markdown
---
产品: 吸尘器
素材类型: 产品推荐理由
品牌: 小狗
型号: 小狗T12
核心关键词: [小狗, T12, 参数]
---

吸力: 180AW
续航: 55 分钟
噪音: 70dB
```

`tests/fixtures/mini_vault/营销资料库/产品模块/吸尘器/希喂推荐内容/吸尘器-CEWEY品牌背书-认证背书.md`:
```markdown
---
产品: 吸尘器
素材类型: 品牌背书
品牌: CEWEY
核心关键词: [CEWEY, 认证, 背书]
---

① CEWEY 通过德国 TÜV 和国内 3C 双认证，电机寿命实测超过 5000 小时。

② 作为深耕家电 10 年的品牌，CEWEY 连续三年获得中国家电协会推荐产品奖。
```

`tests/fixtures/mini_vault/营销资料库/产品模块/吸尘器/竞品推荐内容/吸尘器-戴森V15-核心卖点.md`:
```markdown
---
产品: 吸尘器
素材类型: 产品推荐理由
品牌: 戴森
型号: 戴森V15
核心关键词: [戴森, V15, 激光]
---

① 戴森 V15 的激光显尘功能是它的核心亮点，地面灰尘肉眼可见。

② 240AW 吸力在无线手持里属于第一梯队，只是价格和噪音都不低。
```

`tests/fixtures/mini_vault/营销资料库/产品模块/吸尘器/竞品推荐内容/吸尘器-小狗T12-核心卖点.md`:
```markdown
---
产品: 吸尘器
素材类型: 产品推荐理由
品牌: 小狗
型号: 小狗T12
核心关键词: [小狗, T12, 性价比]
---

① 小狗 T12 主打性价比，1500 元档位能买到接近戴森 80% 的体验。

② 国产品牌里少有的自研电机，175AW 吸力搭配 55 分钟续航够用。
```

`tests/fixtures/mini_vault/营销资料库/测试项目模块/吸尘器/品牌产品测试结果/CEWEYDS18-测试结果.md`:
```markdown
---
产品: 吸尘器
素材类型: 测试数据
品牌: CEWEY
型号: CEWEYDS18
核心关键词: [CEWEY, 测试, 实测]
---

实测吸力: 218AW（标称 220AW，误差 <1%）
实测续航: 58 分钟（MAX 档 14 分钟，标准档 58 分钟）
实测噪音: 73dB
```

`tests/fixtures/mini_vault/营销资料库/测试项目模块/吸尘器/品牌产品测试结果/戴森V15-测试结果.md`:
```markdown
---
产品: 吸尘器
素材类型: 测试数据
品牌: 戴森
型号: 戴森V15
核心关键词: [戴森, V15, 测试]
---

实测吸力: 235AW（标称 240AW）
实测续航: 55 分钟
实测噪音: 80dB
```

`tests/fixtures/mini_vault/营销资料库/测试项目模块/吸尘器/品牌产品测试结果/小狗T12-测试结果.md`:
```markdown
---
产品: 吸尘器
素材类型: 测试数据
品牌: 小狗
型号: 小狗T12
核心关键词: [小狗, T12, 测试]
---

实测吸力: 176AW
实测续航: 52 分钟
实测噪音: 71dB
```

- [ ] **Step 0.5: 安装依赖并验证**

```bash
cd D:\CSM
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
pytest --collect-only
```
Expected: pytest 报告 "collected 0 items"（目前无测试），无 import 错误。

- [ ] **Step 0.6: 首次 commit**

```bash
git add .gitignore pyproject.toml README.md csm_core/__init__.py tests/__init__.py tests/conftest.py tests/fixtures/
git commit -m "chore: scaffold csm project with mini_vault fixture"
```

---

## Task 1: vault/note_parser.py — 解析单个笔记

**Files:**
- Create: `csm_core/vault/__init__.py`, `csm_core/vault/note_parser.py`
- Test: `tests/core/vault/__init__.py`, `tests/core/vault/test_note_parser.py`

- [ ] **Step 1.1: 创建测试目录 __init__**

Create empty `csm_core/vault/__init__.py` and `tests/core/__init__.py`, `tests/core/vault/__init__.py`.

- [ ] **Step 1.2: 写失败测试 test_note_parser.py**

Create `tests/core/vault/test_note_parser.py`:
```python
from pathlib import Path
from csm_core.vault.note_parser import parse_note, ParsedNote


def test_parse_note_extracts_frontmatter(mini_vault_path: Path):
    note_path = mini_vault_path / "引言模块/吸尘器/痛点共鸣/引言-吸尘器-毛发缠绕.md"
    note = parse_note(note_path)
    assert note.frontmatter["产品"] == "吸尘器"
    assert note.frontmatter["素材类型"] == "引言"
    assert note.frontmatter["组件类型"] == "痛点共鸣"


def test_parse_note_splits_numbered_variants(mini_vault_path: Path):
    note_path = mini_vault_path / "引言模块/吸尘器/痛点共鸣/引言-吸尘器-毛发缠绕.md"
    note = parse_note(note_path)
    assert len(note.variants) == 3
    assert note.variants[0].startswith("每次吸完")
    assert note.variants[1].startswith("养宠家庭")
    assert note.variants[2].startswith("明明买的")


def test_parse_note_handles_two_variants(mini_vault_path: Path):
    note_path = mini_vault_path / "引言模块/吸尘器/痛点共鸣/引言-吸尘器-吸力衰减.md"
    note = parse_note(note_path)
    assert len(note.variants) == 2


def test_parse_note_without_variants_returns_single(mini_vault_path: Path):
    # 产品参数笔记没有 ①②③，应作为单一变体返回整文
    note_path = mini_vault_path / "产品模块/吸尘器/产品参数/CEWEYDS18-产品参数.md"
    note = parse_note(note_path)
    assert len(note.variants) == 1
    assert "220AW" in note.variants[0]


def test_parsed_note_has_path_and_id(mini_vault_path: Path):
    note_path = mini_vault_path / "产品模块/吸尘器/产品参数/CEWEYDS18-产品参数.md"
    note = parse_note(note_path)
    assert note.path == note_path
    assert note.id == "CEWEYDS18-产品参数"  # filename without .md
```

- [ ] **Step 1.3: 运行测试确认失败**

```bash
pytest tests/core/vault/test_note_parser.py -v
```
Expected: ImportError — `csm_core.vault.note_parser` 不存在。

- [ ] **Step 1.4: 实现 note_parser.py**

Create `csm_core/vault/note_parser.py`:
```python
"""Parse a single Obsidian markdown note into frontmatter + variant sections."""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import re
import frontmatter

VARIANT_MARKERS = ("①", "②", "③", "④", "⑤", "⑥", "⑦", "⑧", "⑨")
_VARIANT_RE = re.compile(r"^[①②③④⑤⑥⑦⑧⑨]\s*", re.MULTILINE)


@dataclass
class ParsedNote:
    path: Path
    id: str
    frontmatter: dict[str, Any]
    variants: list[str] = field(default_factory=list)
    raw_body: str = ""


def parse_note(path: Path) -> ParsedNote:
    post = frontmatter.load(str(path))
    body = post.content.strip()
    variants = _split_variants(body)
    return ParsedNote(
        path=path,
        id=path.stem,
        frontmatter=dict(post.metadata),
        variants=variants,
        raw_body=body,
    )


def _split_variants(body: str) -> list[str]:
    """Split body on lines starting with ①/②/③/... Returns list of variant texts.

    If no numbered markers found, returns [body] as single variant.
    """
    if not any(marker in body for marker in VARIANT_MARKERS):
        return [body] if body else []

    # Split on lines starting with a variant marker
    parts: list[str] = []
    current: list[str] = []
    for line in body.splitlines():
        stripped = line.lstrip()
        if stripped and stripped[0] in VARIANT_MARKERS:
            if current:
                parts.append("\n".join(current).strip())
                current = []
            current.append(_VARIANT_RE.sub("", line, count=1))
        else:
            current.append(line)
    if current:
        tail = "\n".join(current).strip()
        if tail:
            parts.append(tail)
    return [p for p in parts if p]
```

- [ ] **Step 1.5: 运行测试确认通过**

```bash
pytest tests/core/vault/test_note_parser.py -v
```
Expected: 5 passed.

- [ ] **Step 1.6: Commit**

```bash
git add csm_core/vault/__init__.py csm_core/vault/note_parser.py tests/core/__init__.py tests/core/vault/
git commit -m "feat(vault): parse markdown notes with frontmatter and numbered variants"
```

---

## Task 2: vault/scanner.py — 扫描整个 Vault 建索引

**Files:**
- Create: `csm_core/vault/scanner.py`
- Test: `tests/core/vault/test_scanner.py`

- [ ] **Step 2.1: 写失败测试**

Create `tests/core/vault/test_scanner.py`:
```python
from pathlib import Path
from csm_core.vault.scanner import scan_vault, VaultIndex


def test_scan_vault_returns_index(mini_vault_path: Path):
    index = scan_vault(mini_vault_path)
    assert isinstance(index, VaultIndex)
    assert len(index.notes) == 14


def test_index_groups_by_module(mini_vault_path: Path):
    index = scan_vault(mini_vault_path)
    intro_notes = index.by_module("引言模块")
    assert len(intro_notes) == 2
    keypoint_notes = index.by_module("科普模块/挑选攻略")
    assert len(keypoint_notes) == 3


def test_index_filter_by_frontmatter(mini_vault_path: Path):
    index = scan_vault(mini_vault_path)
    matches = index.query(module="引言模块", filters={"组件类型": "痛点共鸣"})
    assert len(matches) == 2
    for note in matches:
        assert note.frontmatter["组件类型"] == "痛点共鸣"


def test_index_filter_returns_empty_when_no_match(mini_vault_path: Path):
    index = scan_vault(mini_vault_path)
    matches = index.query(module="引言模块", filters={"组件类型": "不存在"})
    assert matches == []


def test_index_lookup_by_id(mini_vault_path: Path):
    index = scan_vault(mini_vault_path)
    note = index.get("CEWEYDS18-产品参数")
    assert note is not None
    assert note.frontmatter["品牌"] == "CEWEY"


def test_scan_records_warnings_for_missing_frontmatter(tmp_path: Path):
    bad = tmp_path / "营销资料库" / "bad.md"
    bad.parent.mkdir(parents=True)
    bad.write_text("no frontmatter here", encoding="utf-8")
    index = scan_vault(tmp_path / "营销资料库")
    assert len(index.warnings) >= 1
    assert "bad.md" in index.warnings[0]
```

- [ ] **Step 2.2: 运行测试确认失败**

```bash
pytest tests/core/vault/test_scanner.py -v
```
Expected: ImportError.

- [ ] **Step 2.3: 实现 scanner.py**

Create `csm_core/vault/scanner.py`:
```python
"""Scan an entire Obsidian Vault directory and build a queryable index."""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from .note_parser import ParsedNote, parse_note


@dataclass
class VaultIndex:
    root: Path
    notes: list[ParsedNote] = field(default_factory=list)
    by_id: dict[str, ParsedNote] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def get(self, note_id: str) -> ParsedNote | None:
        return self.by_id.get(note_id)

    def by_module(self, module: str) -> list[ParsedNote]:
        """Return notes whose path is under <root>/<module>/**."""
        prefix = (self.root / module).resolve()
        return [
            n for n in self.notes
            if str(n.path.resolve()).startswith(str(prefix))
        ]

    def query(
        self,
        *,
        module: str | None = None,
        filters: dict[str, Any] | None = None,
    ) -> list[ParsedNote]:
        candidates = self.by_module(module) if module else list(self.notes)
        if not filters:
            return candidates
        return [
            n for n in candidates
            if all(n.frontmatter.get(k) == v for k, v in filters.items())
        ]


def scan_vault(root: Path) -> VaultIndex:
    index = VaultIndex(root=root)
    for md_path in sorted(root.rglob("*.md")):
        try:
            note = parse_note(md_path)
            if not note.frontmatter:
                index.warnings.append(f"{md_path.name}: 缺少 frontmatter")
                continue
            index.notes.append(note)
            index.by_id[note.id] = note
        except Exception as exc:
            index.warnings.append(f"{md_path.name}: 解析失败 — {exc}")
    return index
```

- [ ] **Step 2.4: 运行测试确认通过**

```bash
pytest tests/core/vault/test_scanner.py -v
```
Expected: 6 passed.

- [ ] **Step 2.5: Commit**

```bash
git add csm_core/vault/scanner.py tests/core/vault/test_scanner.py
git commit -m "feat(vault): scan vault directory and build queryable index"
```

---

## Task 3: vault/brand_registry.py — 品牌-型号字典

**Files:**
- Create: `csm_core/vault/brand_registry.py`
- Test: `tests/core/vault/test_brand_registry.py`

- [ ] **Step 3.1: 写失败测试**

Create `tests/core/vault/test_brand_registry.py`:
```python
from pathlib import Path
from csm_core.vault.brand_registry import build_brand_registry, BrandRegistry


def test_registry_lists_brands(mini_vault_path: Path):
    registry = build_brand_registry(mini_vault_path)
    assert isinstance(registry, BrandRegistry)
    assert set(registry.brands()) == {"CEWEY", "戴森", "小狗"}


def test_registry_models_for_brand(mini_vault_path: Path):
    registry = build_brand_registry(mini_vault_path)
    assert registry.models("戴森") == ["戴森V15"]
    assert registry.models("CEWEY") == ["CEWEYDS18"]


def test_registry_all_models(mini_vault_path: Path):
    registry = build_brand_registry(mini_vault_path)
    models = set(registry.all_models())
    assert models == {"CEWEYDS18", "戴森V15", "小狗T12"}


def test_registry_brand_of(mini_vault_path: Path):
    registry = build_brand_registry(mini_vault_path)
    assert registry.brand_of("戴森V15") == "戴森"
    assert registry.brand_of("不存在") is None


def test_registry_competitors_of(mini_vault_path: Path):
    registry = build_brand_registry(mini_vault_path)
    # 竞品 = 所有非指定品牌的型号
    competitors = registry.competitors_of("CEWEY")
    assert set(competitors) == {"戴森V15", "小狗T12"}
```

- [ ] **Step 3.2: 运行测试确认失败**

```bash
pytest tests/core/vault/test_brand_registry.py -v
```
Expected: ImportError.

- [ ] **Step 3.3: 实现 brand_registry.py**

Create `csm_core/vault/brand_registry.py`:
```python
"""Build brand-model registry from 产品参数 note filenames + frontmatter."""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from .note_parser import parse_note


@dataclass
class BrandRegistry:
    _brand_to_models: dict[str, list[str]] = field(default_factory=dict)
    _model_to_brand: dict[str, str] = field(default_factory=dict)

    def brands(self) -> list[str]:
        return sorted(self._brand_to_models.keys())

    def models(self, brand: str) -> list[str]:
        return sorted(self._brand_to_models.get(brand, []))

    def all_models(self) -> list[str]:
        return sorted(self._model_to_brand.keys())

    def brand_of(self, model: str) -> str | None:
        return self._model_to_brand.get(model)

    def competitors_of(self, brand: str) -> list[str]:
        return [m for m, b in self._model_to_brand.items() if b != brand]

    def add(self, brand: str, model: str) -> None:
        self._brand_to_models.setdefault(brand, [])
        if model not in self._brand_to_models[brand]:
            self._brand_to_models[brand].append(model)
        self._model_to_brand[model] = brand


def build_brand_registry(vault_root: Path) -> BrandRegistry:
    """Scan <vault>/**/产品参数/*.md and construct registry.

    Source priority:
      1. frontmatter 品牌 + 型号
      2. filename stem split on '-' (e.g. '戴森V15-产品参数' → model='戴森V15')
    """
    registry = BrandRegistry()
    for md in vault_root.rglob("产品参数/*.md"):
        note = parse_note(md)
        brand = note.frontmatter.get("品牌")
        model = note.frontmatter.get("型号")
        if not model:
            model = md.stem.split("-")[0]
        if not brand:
            continue  # skip if brand missing
        registry.add(brand, model)
    return registry
```

- [ ] **Step 3.4: 运行测试确认通过**

```bash
pytest tests/core/vault/test_brand_registry.py -v
```
Expected: 5 passed.

- [ ] **Step 3.5: Commit**

```bash
git add csm_core/vault/brand_registry.py tests/core/vault/test_brand_registry.py
git commit -m "feat(vault): build brand-model registry from 产品参数 notes"
```

---

## Task 4: template/schema.py — 模板 Pydantic 模型

**Files:**
- Create: `csm_core/template/__init__.py`, `csm_core/template/schema.py`
- Test: `tests/core/template/__init__.py`, `tests/core/template/test_schema.py`

- [ ] **Step 4.1: 创建包 + 测试初始化**

Create empty `csm_core/template/__init__.py` and `tests/core/template/__init__.py`.

- [ ] **Step 4.2: 写失败测试**

Create `tests/core/template/test_schema.py`:
```python
import pytest
from pydantic import ValidationError
from csm_core.template.schema import (
    Template, Slot, NotesQuerySource, BrandFixedSource,
    BrandPoolSource, TestResultsAlignedSource, PickCountSpec,
)


def test_template_minimal_valid():
    tpl = Template(
        id="t1",
        name="Test",
        product="吸尘器",
        slots=[
            Slot(
                id="intro",
                label="引言",
                source=NotesQuerySource(module="引言模块", filter={"组件类型": "痛点共鸣"}),
                pick_notes=1,
                pick_variants_per_note=1,
            ),
        ],
        render_order=["intro"],
    )
    assert tpl.id == "t1"
    assert len(tpl.slots) == 1


def test_render_order_must_match_slot_ids():
    with pytest.raises(ValidationError, match="render_order"):
        Template(
            id="t", name="T", product="吸尘器",
            slots=[Slot(
                id="a", label="A",
                source=NotesQuerySource(module="X"),
                pick_notes=1, pick_variants_per_note=1,
            )],
            render_order=["a", "b"],
        )


def test_depends_on_must_reference_existing_slot():
    with pytest.raises(ValidationError, match="depends_on"):
        Template(
            id="t", name="T", product="吸尘器",
            slots=[
                Slot(
                    id="a", label="A",
                    source=NotesQuerySource(module="X"),
                    pick_notes=1, pick_variants_per_note=1,
                    depends_on=["nonexistent"],
                ),
            ],
            render_order=["a"],
        )


def test_depends_on_must_be_acyclic():
    with pytest.raises(ValidationError, match="cycle"):
        Template(
            id="t", name="T", product="吸尘器",
            slots=[
                Slot(id="a", label="A",
                     source=NotesQuerySource(module="X"),
                     pick_notes=1, pick_variants_per_note=1,
                     depends_on=["b"]),
                Slot(id="b", label="B",
                     source=NotesQuerySource(module="X"),
                     pick_notes=1, pick_variants_per_note=1,
                     depends_on=["a"]),
            ],
            render_order=["a", "b"],
        )


def test_pick_count_random_between():
    spec = PickCountSpec.model_validate({"random_between": [3, 5]})
    assert spec.sample(rng_min=3, rng_max=5)  # just validates structure


def test_pick_count_user_configurable():
    spec = PickCountSpec.model_validate({
        "user_configurable": True, "default": 5, "range": [2, 9]
    })
    assert spec.default == 5
    assert spec.range == [2, 9]


def test_brand_fixed_source():
    s = BrandFixedSource(brand="CEWEY", model="CEWEYDS18")
    assert s.type == "brand_fixed"


def test_brand_pool_source():
    s = BrandPoolSource(exclude_brands=["CEWEY"])
    assert s.type == "brand_pool"


def test_test_results_aligned_source():
    s = TestResultsAlignedSource(
        follow_slot="brand_competitors",
        module="测试项目模块/品牌产品测试结果",
    )
    assert s.type == "test_results_aligned"
```

- [ ] **Step 4.3: 运行测试确认失败**

```bash
pytest tests/core/template/test_schema.py -v
```
Expected: ImportError.

- [ ] **Step 4.4: 实现 schema.py**

Create `csm_core/template/schema.py`:
```python
"""Pydantic models for template DSL."""
from __future__ import annotations
from typing import Any, Literal, Union
from pydantic import BaseModel, Field, field_validator, model_validator


class NotesQuerySource(BaseModel):
    type: Literal["notes_query"] = "notes_query"
    module: str
    filter: dict[str, Any] = Field(default_factory=dict)


class BrandFixedSource(BaseModel):
    type: Literal["brand_fixed"] = "brand_fixed"
    brand: str
    model: str


class BrandPoolSource(BaseModel):
    type: Literal["brand_pool"] = "brand_pool"
    exclude_brands: list[str] = Field(default_factory=list)


class TestResultsAlignedSource(BaseModel):
    type: Literal["test_results_aligned"] = "test_results_aligned"
    follow_slot: str  # may be "a+b" to union multiple slots
    module: str


SourceT = Union[
    NotesQuerySource, BrandFixedSource, BrandPoolSource, TestResultsAlignedSource
]


class PickCountSpec(BaseModel):
    """Union-style: either an int (via root), or random_between, or user_configurable."""
    random_between: list[int] | None = None  # [min, max]
    user_configurable: bool = False
    default: int | None = None
    range: list[int] | None = None

    @model_validator(mode="after")
    def _check(self):
        if self.random_between and len(self.random_between) != 2:
            raise ValueError("random_between must be [min, max]")
        if self.user_configurable and (self.default is None or self.range is None):
            raise ValueError("user_configurable requires default + range")
        return self

    def sample(self, rng_min: int, rng_max: int) -> int:
        return rng_min  # placeholder; real sampling lives in sampler.py


PickNotes = Union[int, PickCountSpec]


class Slot(BaseModel):
    id: str
    label: str
    source: SourceT = Field(discriminator="type")
    pick_notes: PickNotes = 1
    pick_variants_per_note: int = 1
    constraints: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)


class SEODefaults(BaseModel):
    target_word_count: list[int] = Field(default_factory=lambda: [1500, 2000])
    keyword_density: list[int] = Field(default_factory=lambda: [5, 8])
    long_tail_keywords: list[str] = Field(default_factory=list)
    tone: str = "小红书笔记体"
    force_h2: bool = True


class Template(BaseModel):
    id: str
    name: str
    product: str
    version: int = 1
    system_prompt_default: str = ""
    seo_defaults: SEODefaults = Field(default_factory=SEODefaults)
    slots: list[Slot]
    render_order: list[str]

    @model_validator(mode="after")
    def _validate_structure(self):
        slot_ids = {s.id for s in self.slots}

        if set(self.render_order) != slot_ids:
            raise ValueError(
                f"render_order {self.render_order} must match slot ids {sorted(slot_ids)}"
            )

        for s in self.slots:
            for dep in s.depends_on:
                if dep not in slot_ids:
                    raise ValueError(
                        f"slot '{s.id}' depends_on '{dep}' which does not exist"
                    )

        # Cycle check (Kahn's algorithm)
        in_degree = {s.id: 0 for s in self.slots}
        graph: dict[str, list[str]] = {s.id: [] for s in self.slots}
        for s in self.slots:
            for dep in s.depends_on:
                graph[dep].append(s.id)
                in_degree[s.id] += 1
        queue = [sid for sid, d in in_degree.items() if d == 0]
        visited = 0
        while queue:
            node = queue.pop()
            visited += 1
            for nxt in graph[node]:
                in_degree[nxt] -= 1
                if in_degree[nxt] == 0:
                    queue.append(nxt)
        if visited != len(self.slots):
            raise ValueError("depends_on graph contains a cycle")
        return self
```

- [ ] **Step 4.5: 运行测试确认通过**

```bash
pytest tests/core/template/test_schema.py -v
```
Expected: 9 passed.

- [ ] **Step 4.6: Commit**

```bash
git add csm_core/template/ tests/core/template/
git commit -m "feat(template): define Pydantic schema with dependency graph validation"
```

---

## Task 5: template/loader.py — JSON 加载/保存

**Files:**
- Create: `csm_core/template/loader.py`, `templates/daogou-changjing-renqun.json`
- Test: `tests/core/template/test_loader.py`

- [ ] **Step 5.1: 创建示例模板 JSON**

Create `D:\CSM\templates\daogou-changjing-renqun.json`:
```json
{
  "id": "daogou-changjing-renqun",
  "name": "导购文-场景人群型",
  "product": "吸尘器",
  "version": 1,
  "system_prompt_default": "你是资深家电导购编辑，风格为小红书笔记体：口语化、有情绪钩子、分段清晰、H2 标题明确。",
  "seo_defaults": {
    "target_word_count": [1500, 2000],
    "keyword_density": [5, 8],
    "long_tail_keywords": [],
    "tone": "小红书笔记体",
    "force_h2": true
  },
  "slots": [
    {
      "id": "intro",
      "label": "引言-痛点共鸣",
      "source": {
        "type": "notes_query",
        "module": "引言模块",
        "filter": {"组件类型": "痛点共鸣"}
      },
      "pick_notes": 1,
      "pick_variants_per_note": 1
    },
    {
      "id": "keypoints",
      "label": "科普大点",
      "source": {
        "type": "notes_query",
        "module": "科普模块/挑选攻略",
        "filter": {}
      },
      "pick_notes": {"random_between": [2, 3]},
      "pick_variants_per_note": 1,
      "constraints": ["unique_notes"]
    },
    {
      "id": "brand_self",
      "label": "自有品牌",
      "source": {
        "type": "brand_fixed",
        "brand": "CEWEY",
        "model": "CEWEYDS18"
      }
    },
    {
      "id": "brand_competitors",
      "label": "竞品",
      "source": {
        "type": "brand_pool",
        "exclude_brands": ["CEWEY"]
      },
      "pick_notes": {"user_configurable": true, "default": 2, "range": [1, 5]}
    }
  ],
  "render_order": ["intro", "keypoints", "brand_self", "brand_competitors"]
}
```

- [ ] **Step 5.2: 写失败测试**

Create `tests/core/template/test_loader.py`:
```python
from pathlib import Path
import json
import pytest
from csm_core.template.loader import load_template, save_template
from csm_core.template.schema import Template

TEMPLATE_PATH = Path(__file__).parent.parent.parent.parent / "templates" / "daogou-changjing-renqun.json"


def test_load_template_returns_model():
    tpl = load_template(TEMPLATE_PATH)
    assert isinstance(tpl, Template)
    assert tpl.id == "daogou-changjing-renqun"
    assert len(tpl.slots) == 4


def test_save_template_roundtrip(tmp_path: Path):
    original = load_template(TEMPLATE_PATH)
    out = tmp_path / "out.json"
    save_template(original, out)
    reloaded = load_template(out)
    assert reloaded.model_dump() == original.model_dump()


def test_load_invalid_json_raises(tmp_path: Path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        load_template(bad)


def test_load_schema_violation_raises(tmp_path: Path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({
        "id": "x", "name": "X", "product": "吸尘器",
        "slots": [], "render_order": ["missing"]
    }), encoding="utf-8")
    with pytest.raises(Exception):  # pydantic ValidationError
        load_template(bad)
```

- [ ] **Step 5.3: 运行测试确认失败**

```bash
pytest tests/core/template/test_loader.py -v
```
Expected: ImportError.

- [ ] **Step 5.4: 实现 loader.py**

Create `csm_core/template/loader.py`:
```python
"""Load and save templates as JSON."""
from __future__ import annotations
import json
from pathlib import Path
from .schema import Template


def load_template(path: Path) -> Template:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return Template.model_validate(data)


def save_template(template: Template, path: Path) -> None:
    Path(path).write_text(
        json.dumps(template.model_dump(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
```

- [ ] **Step 5.5: 运行测试确认通过**

```bash
pytest tests/core/template/test_loader.py -v
```
Expected: 4 passed.

- [ ] **Step 5.6: Commit**

```bash
git add csm_core/template/loader.py tests/core/template/test_loader.py templates/
git commit -m "feat(template): load/save templates as JSON with schema validation"
```

---

## Task 6: assembler/plan.py — AssemblyPlan 数据结构

**Files:**
- Create: `csm_core/assembler/__init__.py`, `csm_core/assembler/plan.py`
- Test: `tests/core/assembler/__init__.py`, `tests/core/assembler/test_plan.py`

- [ ] **Step 6.1: 创建包初始化**

Create empty `csm_core/assembler/__init__.py` and `tests/core/assembler/__init__.py`.

- [ ] **Step 6.2: 写失败测试**

Create `tests/core/assembler/test_plan.py`:
```python
import json
from csm_core.assembler.plan import AssemblyPlan, SlotAssignment, PickedVariant


def test_plan_serializes_to_json():
    plan = AssemblyPlan(
        keyword="宠物吸尘器推荐",
        template_id="daogou-changjing-renqun",
        seed=42,
        slots=[
            SlotAssignment(
                slot_id="intro",
                picks=[PickedVariant(note_id="引言-吸尘器-毛发缠绕", variant_index=1, text="养宠家庭...")],
            ),
        ],
    )
    as_json = plan.to_json()
    data = json.loads(as_json)
    assert data["keyword"] == "宠物吸尘器推荐"
    assert data["seed"] == 42
    assert data["slots"][0]["slot_id"] == "intro"
    assert data["slots"][0]["picks"][0]["variant_index"] == 1


def test_plan_deserializes_from_json():
    payload = json.dumps({
        "keyword": "kw",
        "template_id": "t",
        "seed": 1,
        "slots": [
            {"slot_id": "s", "picks": [
                {"note_id": "n", "variant_index": 0, "text": "hello"}
            ]}
        ],
    })
    plan = AssemblyPlan.from_json(payload)
    assert plan.keyword == "kw"
    assert plan.slots[0].picks[0].text == "hello"


def test_plan_get_slot():
    plan = AssemblyPlan(
        keyword="k", template_id="t", seed=0,
        slots=[SlotAssignment(slot_id="a", picks=[])],
    )
    assert plan.get_slot("a").slot_id == "a"
    assert plan.get_slot("nope") is None


def test_plan_all_brands_in_slot():
    plan = AssemblyPlan(
        keyword="k", template_id="t", seed=0,
        slots=[SlotAssignment(
            slot_id="comp",
            picks=[
                PickedVariant(note_id="戴森V15-核心卖点", variant_index=0, text="", meta={"model": "戴森V15", "brand": "戴森"}),
                PickedVariant(note_id="小狗T12-核心卖点", variant_index=0, text="", meta={"model": "小狗T12", "brand": "小狗"}),
            ],
        )],
    )
    models = plan.models_in_slot("comp")
    assert set(models) == {"戴森V15", "小狗T12"}
```

- [ ] **Step 6.3: 运行测试确认失败**

```bash
pytest tests/core/assembler/test_plan.py -v
```
Expected: ImportError.

- [ ] **Step 6.4: 实现 plan.py**

Create `csm_core/assembler/plan.py`:
```python
"""AssemblyPlan — serializable result of sampling."""
from __future__ import annotations
import json
from typing import Any
from pydantic import BaseModel, Field


class PickedVariant(BaseModel):
    note_id: str
    variant_index: int  # 0-based index into ParsedNote.variants
    text: str
    meta: dict[str, Any] = Field(default_factory=dict)  # brand/model/etc.


class SlotAssignment(BaseModel):
    slot_id: str
    picks: list[PickedVariant] = Field(default_factory=list)
    note: str = ""  # warnings like "缺数据"


class AssemblyPlan(BaseModel):
    keyword: str
    template_id: str
    seed: int
    slots: list[SlotAssignment] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(self.model_dump(), ensure_ascii=False, indent=2)

    @classmethod
    def from_json(cls, payload: str) -> "AssemblyPlan":
        return cls.model_validate(json.loads(payload))

    def get_slot(self, slot_id: str) -> SlotAssignment | None:
        for s in self.slots:
            if s.slot_id == slot_id:
                return s
        return None

    def models_in_slot(self, slot_id: str) -> list[str]:
        slot = self.get_slot(slot_id)
        if not slot:
            return []
        return [p.meta.get("model") for p in slot.picks if p.meta.get("model")]
```

- [ ] **Step 6.5: 运行测试确认通过**

```bash
pytest tests/core/assembler/test_plan.py -v
```
Expected: 4 passed.

- [ ] **Step 6.6: Commit**

```bash
git add csm_core/assembler/__init__.py csm_core/assembler/plan.py tests/core/assembler/
git commit -m "feat(assembler): define AssemblyPlan data structure"
```

---

## Task 7: assembler/sampler.py — 两级随机采样

**Files:**
- Create: `csm_core/assembler/sampler.py`
- Test: `tests/core/assembler/test_sampler.py`

- [ ] **Step 7.1: 写失败测试**

Create `tests/core/assembler/test_sampler.py`:
```python
from pathlib import Path
import pytest
from csm_core.vault.scanner import scan_vault
from csm_core.vault.brand_registry import build_brand_registry
from csm_core.template.schema import (
    Slot, NotesQuerySource, BrandFixedSource, BrandPoolSource, PickCountSpec,
)
from csm_core.assembler.sampler import sample_slot, EmptyPoolError


def test_sample_notes_query_slot(mini_vault_path: Path):
    index = scan_vault(mini_vault_path)
    registry = build_brand_registry(mini_vault_path)
    slot = Slot(
        id="intro", label="引言",
        source=NotesQuerySource(module="引言模块", filter={"组件类型": "痛点共鸣"}),
        pick_notes=1, pick_variants_per_note=1,
    )
    picks = sample_slot(slot, index, registry, seed=42, user_config={})
    assert len(picks) == 1
    assert picks[0].note_id in {"引言-吸尘器-毛发缠绕", "引言-吸尘器-吸力衰减"}


def test_sample_reproducible_with_seed(mini_vault_path: Path):
    index = scan_vault(mini_vault_path)
    registry = build_brand_registry(mini_vault_path)
    slot = Slot(
        id="kp", label="科普",
        source=NotesQuerySource(module="科普模块/挑选攻略"),
        pick_notes=PickCountSpec(random_between=[2, 2]),
        pick_variants_per_note=1,
    )
    r1 = sample_slot(slot, index, registry, seed=42, user_config={})
    r2 = sample_slot(slot, index, registry, seed=42, user_config={})
    assert [p.note_id for p in r1] == [p.note_id for p in r2]
    assert [p.variant_index for p in r1] == [p.variant_index for p in r2]


def test_sample_different_seeds_produce_different_picks(mini_vault_path: Path):
    index = scan_vault(mini_vault_path)
    registry = build_brand_registry(mini_vault_path)
    slot = Slot(
        id="kp", label="科普",
        source=NotesQuerySource(module="科普模块/挑选攻略"),
        pick_notes=PickCountSpec(random_between=[2, 2]),
        pick_variants_per_note=1,
    )
    # iterate seeds until we find one producing a different pick
    r1 = sample_slot(slot, index, registry, seed=0, user_config={})
    for s in range(1, 30):
        r2 = sample_slot(slot, index, registry, seed=s, user_config={})
        if [p.note_id for p in r2] != [p.note_id for p in r1]:
            return
    pytest.fail("Seed variation did not change picks across 30 seeds")


def test_sample_unique_notes_constraint(mini_vault_path: Path):
    index = scan_vault(mini_vault_path)
    registry = build_brand_registry(mini_vault_path)
    slot = Slot(
        id="kp", label="科普",
        source=NotesQuerySource(module="科普模块/挑选攻略"),
        pick_notes=3,
        pick_variants_per_note=1,
        constraints=["unique_notes"],
    )
    picks = sample_slot(slot, index, registry, seed=0, user_config={})
    assert len({p.note_id for p in picks}) == 3


def test_sample_brand_fixed(mini_vault_path: Path):
    index = scan_vault(mini_vault_path)
    registry = build_brand_registry(mini_vault_path)
    slot = Slot(
        id="self", label="自有",
        source=BrandFixedSource(brand="CEWEY", model="CEWEYDS18"),
    )
    picks = sample_slot(slot, index, registry, seed=0, user_config={})
    assert len(picks) == 1
    assert picks[0].meta["brand"] == "CEWEY"
    assert picks[0].meta["model"] == "CEWEYDS18"


def test_sample_brand_pool_respects_user_config(mini_vault_path: Path):
    index = scan_vault(mini_vault_path)
    registry = build_brand_registry(mini_vault_path)
    slot = Slot(
        id="comp", label="竞品",
        source=BrandPoolSource(exclude_brands=["CEWEY"]),
        pick_notes=PickCountSpec(user_configurable=True, default=2, range=[1, 5]),
    )
    picks = sample_slot(slot, index, registry, seed=0, user_config={"comp": 2})
    assert len(picks) == 2
    brands = {p.meta["brand"] for p in picks}
    assert "CEWEY" not in brands


def test_sample_empty_pool_raises(mini_vault_path: Path):
    index = scan_vault(mini_vault_path)
    registry = build_brand_registry(mini_vault_path)
    slot = Slot(
        id="x", label="X",
        source=NotesQuerySource(module="不存在模块"),
        pick_notes=1, pick_variants_per_note=1,
    )
    with pytest.raises(EmptyPoolError):
        sample_slot(slot, index, registry, seed=0, user_config={})
```

- [ ] **Step 7.2: 运行测试确认失败**

```bash
pytest tests/core/assembler/test_sampler.py -v
```
Expected: ImportError.

- [ ] **Step 7.3: 实现 sampler.py**

Create `csm_core/assembler/sampler.py`:
```python
"""Two-level random sampling: pick notes → pick variant per note."""
from __future__ import annotations
import random
from typing import Any
from ..vault.scanner import VaultIndex
from ..vault.brand_registry import BrandRegistry
from ..vault.note_parser import ParsedNote
from ..template.schema import (
    Slot, NotesQuerySource, BrandFixedSource, BrandPoolSource,
    TestResultsAlignedSource, PickCountSpec,
)
from .plan import PickedVariant


class EmptyPoolError(Exception):
    """Raised when a slot's candidate pool is empty."""


def _resolve_pick_count(
    pick_notes: int | PickCountSpec,
    slot_id: str,
    user_config: dict[str, int],
    rng: random.Random,
) -> int:
    if isinstance(pick_notes, int):
        return pick_notes
    if pick_notes.random_between:
        lo, hi = pick_notes.random_between
        return rng.randint(lo, hi)
    if pick_notes.user_configurable:
        return user_config.get(slot_id, pick_notes.default or 1)
    return 1


def _pick_variant(note: ParsedNote, rng: random.Random) -> tuple[int, str]:
    if not note.variants:
        return 0, note.raw_body
    idx = rng.randrange(len(note.variants))
    return idx, note.variants[idx]


def _meta_for_note(note: ParsedNote) -> dict[str, Any]:
    meta: dict[str, Any] = {}
    for key in ("品牌", "型号"):
        if key in note.frontmatter:
            meta["brand" if key == "品牌" else "model"] = note.frontmatter[key]
    return meta


def sample_slot(
    slot: Slot,
    index: VaultIndex,
    registry: BrandRegistry,
    seed: int,
    user_config: dict[str, int],
    aligned_models: list[str] | None = None,
) -> list[PickedVariant]:
    """Sample a single slot. `aligned_models` is for test_results_aligned source."""
    rng = random.Random(f"{seed}-{slot.id}")
    src = slot.source

    if isinstance(src, NotesQuerySource):
        pool = index.query(module=src.module, filters=src.filter)
        if not pool:
            raise EmptyPoolError(f"slot '{slot.id}': empty pool in module '{src.module}'")
        n = _resolve_pick_count(slot.pick_notes, slot.id, user_config, rng)
        n = min(n, len(pool)) if "unique_notes" in slot.constraints else n
        if "unique_notes" in slot.constraints:
            chosen = rng.sample(pool, n)
        else:
            chosen = [rng.choice(pool) for _ in range(n)]
        picks: list[PickedVariant] = []
        for note in chosen:
            for _ in range(slot.pick_variants_per_note):
                vi, text = _pick_variant(note, rng)
                picks.append(PickedVariant(
                    note_id=note.id, variant_index=vi, text=text,
                    meta=_meta_for_note(note),
                ))
        return picks

    if isinstance(src, BrandFixedSource):
        return [PickedVariant(
            note_id=f"{src.model}-fixed",
            variant_index=0,
            text=f"{src.brand} {src.model}",
            meta={"brand": src.brand, "model": src.model},
        )]

    if isinstance(src, BrandPoolSource):
        candidates = [
            m for m in registry.all_models()
            if registry.brand_of(m) not in src.exclude_brands
        ]
        if not candidates:
            raise EmptyPoolError(f"slot '{slot.id}': brand pool empty")
        n = _resolve_pick_count(slot.pick_notes, slot.id, user_config, rng)
        chosen = rng.sample(candidates, min(n, len(candidates)))
        return [
            PickedVariant(
                note_id=f"{m}-brand",
                variant_index=0,
                text=f"{registry.brand_of(m)} {m}",
                meta={"brand": registry.brand_of(m), "model": m},
            )
            for m in chosen
        ]

    if isinstance(src, TestResultsAlignedSource):
        if aligned_models is None:
            raise EmptyPoolError(
                f"slot '{slot.id}': test_results_aligned requires aligned_models"
            )
        picks = []
        for model in aligned_models:
            note = index.get(f"{model}-测试结果")
            if not note:
                picks.append(PickedVariant(
                    note_id=f"{model}-测试结果",
                    variant_index=0,
                    text=f"[缺数据：{model} 测试结果]",
                    meta={"model": model, "missing": True},
                ))
            else:
                vi, text = _pick_variant(note, rng)
                picks.append(PickedVariant(
                    note_id=note.id, variant_index=vi, text=text,
                    meta={"model": model, "brand": registry.brand_of(model) or ""},
                ))
        return picks

    raise EmptyPoolError(f"slot '{slot.id}': unknown source type {type(src)}")
```

- [ ] **Step 7.4: 运行测试确认通过**

```bash
pytest tests/core/assembler/test_sampler.py -v
```
Expected: 7 passed.

- [ ] **Step 7.5: Commit**

```bash
git add csm_core/assembler/sampler.py tests/core/assembler/test_sampler.py
git commit -m "feat(assembler): two-level random sampler with seeded reproducibility"
```

---

## Task 8: assembler/constraints.py — 跨槽位依赖求解

**Files:**
- Create: `csm_core/assembler/constraints.py`
- Test: `tests/core/assembler/test_constraints.py`

- [ ] **Step 8.1: 写失败测试**

Create `tests/core/assembler/test_constraints.py`:
```python
from pathlib import Path
from csm_core.vault.scanner import scan_vault
from csm_core.vault.brand_registry import build_brand_registry
from csm_core.template.schema import (
    Template, Slot, BrandFixedSource, BrandPoolSource, TestResultsAlignedSource,
)
from csm_core.assembler.constraints import assemble_plan


def _duibi_template() -> Template:
    return Template(
        id="duibi-test", name="对比文测试", product="吸尘器",
        slots=[
            Slot(id="brand_self", label="自有",
                 source=BrandFixedSource(brand="CEWEY", model="CEWEYDS18")),
            Slot(id="brand_competitors", label="竞品",
                 source=BrandPoolSource(exclude_brands=["CEWEY"]),
                 pick_notes=2),
            Slot(id="test_results", label="测试结果",
                 source=TestResultsAlignedSource(
                     follow_slot="brand_self+brand_competitors",
                     module="测试项目模块/品牌产品测试结果",
                 ),
                 depends_on=["brand_self", "brand_competitors"]),
        ],
        render_order=["brand_self", "brand_competitors", "test_results"],
    )


def test_assemble_respects_topological_order(mini_vault_path: Path):
    index = scan_vault(mini_vault_path)
    registry = build_brand_registry(mini_vault_path)
    tpl = _duibi_template()
    plan = assemble_plan(
        keyword="kw", template=tpl, index=index, registry=registry,
        seed=42, user_config={},
    )
    test_slot = plan.get_slot("test_results")
    assert test_slot is not None
    # test_results picks should reference same models as brand_self + brand_competitors
    self_models = set(plan.models_in_slot("brand_self"))
    comp_models = set(plan.models_in_slot("brand_competitors"))
    test_models = {p.meta.get("model") for p in test_slot.picks}
    assert test_models == self_models | comp_models


def test_assemble_missing_test_data_recorded(tmp_path: Path):
    # Build a tiny vault where some brand has no test result file
    vault = tmp_path / "营销资料库"
    (vault / "产品模块/吸尘器/产品参数").mkdir(parents=True)
    (vault / "产品模块/吸尘器/产品参数/CEWEYDS18-产品参数.md").write_text(
        "---\n品牌: CEWEY\n型号: CEWEYDS18\n---\n吸力 220AW",
        encoding="utf-8",
    )
    (vault / "测试项目模块/吸尘器/品牌产品测试结果").mkdir(parents=True)
    # Intentionally no test result files
    index = scan_vault(vault)
    registry = build_brand_registry(vault)

    tpl = Template(
        id="t", name="T", product="吸尘器",
        slots=[
            Slot(id="self", label="自",
                 source=BrandFixedSource(brand="CEWEY", model="CEWEYDS18")),
            Slot(id="tests", label="测",
                 source=TestResultsAlignedSource(
                     follow_slot="self",
                     module="测试项目模块/品牌产品测试结果",
                 ),
                 depends_on=["self"]),
        ],
        render_order=["self", "tests"],
    )
    plan = assemble_plan(keyword="k", template=tpl, index=index, registry=registry, seed=0, user_config={})
    test_slot = plan.get_slot("tests")
    assert len(test_slot.picks) == 1
    assert test_slot.picks[0].meta.get("missing") is True
```

- [ ] **Step 8.2: 运行测试确认失败**

```bash
pytest tests/core/assembler/test_constraints.py -v
```
Expected: ImportError.

- [ ] **Step 8.3: 实现 constraints.py**

Create `csm_core/assembler/constraints.py`:
```python
"""Orchestrate sampling over a template DAG (topological order)."""
from __future__ import annotations
from ..vault.scanner import VaultIndex
from ..vault.brand_registry import BrandRegistry
from ..template.schema import Template, TestResultsAlignedSource
from .plan import AssemblyPlan, SlotAssignment
from .sampler import sample_slot


def _topo_order(template: Template) -> list[str]:
    """Return slot ids in topological order (deps first)."""
    in_deg = {s.id: 0 for s in template.slots}
    graph: dict[str, list[str]] = {s.id: [] for s in template.slots}
    for s in template.slots:
        for dep in s.depends_on:
            graph[dep].append(s.id)
            in_deg[s.id] += 1
    queue = [sid for sid, d in in_deg.items() if d == 0]
    order: list[str] = []
    while queue:
        node = queue.pop(0)
        order.append(node)
        for nxt in graph[node]:
            in_deg[nxt] -= 1
            if in_deg[nxt] == 0:
                queue.append(nxt)
    return order


def _resolve_aligned_models(
    slot_id: str,
    source: TestResultsAlignedSource,
    assignments: dict[str, SlotAssignment],
) -> list[str]:
    follow_ids = source.follow_slot.split("+")
    models: list[str] = []
    for fid in follow_ids:
        slot_a = assignments.get(fid)
        if not slot_a:
            continue
        for p in slot_a.picks:
            m = p.meta.get("model")
            if m and m not in models:
                models.append(m)
    return models


def assemble_plan(
    *,
    keyword: str,
    template: Template,
    index: VaultIndex,
    registry: BrandRegistry,
    seed: int,
    user_config: dict[str, int],
) -> AssemblyPlan:
    order = _topo_order(template)
    slot_map = {s.id: s for s in template.slots}
    assignments: dict[str, SlotAssignment] = {}
    warnings: list[str] = []

    for slot_id in order:
        slot = slot_map[slot_id]
        aligned: list[str] | None = None
        if isinstance(slot.source, TestResultsAlignedSource):
            aligned = _resolve_aligned_models(slot.id, slot.source, assignments)
        picks = sample_slot(
            slot, index, registry, seed=seed, user_config=user_config,
            aligned_models=aligned,
        )
        missing = [p for p in picks if p.meta.get("missing")]
        if missing:
            warnings.append(
                f"slot '{slot.id}': {len(missing)} 测试数据缺失 ({[p.note_id for p in missing]})"
            )
        assignments[slot_id] = SlotAssignment(slot_id=slot_id, picks=picks)

    # Return slots in render_order so downstream renderers see natural order
    rendered_slots = [assignments[sid] for sid in template.render_order]
    return AssemblyPlan(
        keyword=keyword,
        template_id=template.id,
        seed=seed,
        slots=rendered_slots,
        warnings=warnings,
    )
```

- [ ] **Step 8.4: 运行测试确认通过**

```bash
pytest tests/core/assembler/test_constraints.py -v
```
Expected: 2 passed.

- [ ] **Step 8.5: Commit**

```bash
git add csm_core/assembler/constraints.py tests/core/assembler/test_constraints.py
git commit -m "feat(assembler): topological plan assembly with cross-slot dependencies"
```

---

## Task 9: llm/client.py + providers/mock.py — LLMClient Protocol

**Files:**
- Create: `csm_core/llm/__init__.py`, `csm_core/llm/client.py`, `csm_core/llm/providers/__init__.py`, `csm_core/llm/providers/mock.py`
- Test: `tests/core/llm/__init__.py`, `tests/core/llm/test_client.py`

- [ ] **Step 9.1: 创建包初始化**

Create empty `csm_core/llm/__init__.py`, `csm_core/llm/providers/__init__.py`, `tests/core/llm/__init__.py`.

- [ ] **Step 9.2: 写失败测试**

Create `tests/core/llm/test_client.py`:
```python
import pytest
from csm_core.llm.client import LLMClient, make_client
from csm_core.llm.providers.mock import MockClient


def test_mock_client_returns_fixed_response():
    client: LLMClient = MockClient(response="hello world")
    result = client.complete(system="sys", user="usr")
    assert result == "hello world"


def test_mock_client_records_calls():
    client = MockClient(response="ok")
    client.complete(system="S", user="U")
    assert client.calls == [{"system": "S", "user": "U"}]


def test_make_client_dispatches_by_provider():
    client = make_client(provider="mock", response="foo")
    assert isinstance(client, MockClient)


def test_make_client_unknown_provider_raises():
    with pytest.raises(ValueError, match="unknown provider"):
        make_client(provider="nonexistent")
```

- [ ] **Step 9.3: 运行测试确认失败**

```bash
pytest tests/core/llm/test_client.py -v
```
Expected: ImportError.

- [ ] **Step 9.4: 实现 client.py 和 mock.py**

Create `csm_core/llm/client.py`:
```python
"""LLMClient protocol + factory."""
from __future__ import annotations
from typing import Protocol, runtime_checkable


@runtime_checkable
class LLMClient(Protocol):
    def complete(self, *, system: str, user: str) -> str: ...


def make_client(*, provider: str, **kwargs) -> LLMClient:
    if provider == "mock":
        from .providers.mock import MockClient
        return MockClient(**kwargs)
    if provider == "anthropic":
        from .providers.anthropic import AnthropicClient
        return AnthropicClient(**kwargs)
    if provider == "deepseek":
        from .providers.deepseek import DeepSeekClient
        return DeepSeekClient(**kwargs)
    raise ValueError(f"unknown provider: {provider}")
```

Create `csm_core/llm/providers/mock.py`:
```python
"""Mock LLM client for testing."""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class MockClient:
    response: str = "mock response"
    calls: list[dict] = field(default_factory=list)

    def complete(self, *, system: str, user: str) -> str:
        self.calls.append({"system": system, "user": user})
        return self.response
```

- [ ] **Step 9.5: 运行测试确认通过**

```bash
pytest tests/core/llm/test_client.py -v
```
Expected: 4 passed.

- [ ] **Step 9.6: Commit**

```bash
git add csm_core/llm/ tests/core/llm/
git commit -m "feat(llm): LLMClient protocol with mock provider and factory"
```

---

## Task 10: llm/prompts.py — 三层 prompt 组合

**Files:**
- Create: `csm_core/llm/prompts.py`
- Test: `tests/core/llm/test_prompts.py`

- [ ] **Step 10.1: 写失败测试**

Create `tests/core/llm/test_prompts.py`:
```python
from csm_core.llm.prompts import build_prompt, PromptInputs
from csm_core.template.schema import SEODefaults


def test_build_prompt_composes_three_layers():
    inputs = PromptInputs(
        template_system_prompt="你是资深家电编辑。",
        user_skill_prompt="保持小红书语气。",
        seo=SEODefaults(
            target_word_count=[1500, 2000],
            keyword_density=[5, 8],
            long_tail_keywords=["宠物吸尘器", "毛发缠绕"],
            tone="小红书笔记体",
            force_h2=True,
        ),
        keyword="宠物吸尘器推荐",
        draft="毛坯文内容...",
    )
    system, user = build_prompt(inputs)
    assert "你是资深家电编辑" in system
    assert "保持小红书语气" in system
    assert "1500" in system and "2000" in system
    assert "5" in system and "8" in system
    assert "H2" in system or "h2" in system.lower()
    assert "小红书笔记体" in system
    assert "宠物吸尘器" in system

    assert "毛坯文内容" in user
    assert "宠物吸尘器推荐" in user
    assert "润色" in user  # polish mode instruction


def test_build_prompt_omits_optional_layers():
    inputs = PromptInputs(
        template_system_prompt="A",
        user_skill_prompt=None,
        seo=SEODefaults(),
        keyword="k",
        draft="d",
    )
    system, user = build_prompt(inputs)
    assert "A" in system
    # should still work without skill layer
    assert "d" in user
```

- [ ] **Step 10.2: 运行测试确认失败**

```bash
pytest tests/core/llm/test_prompts.py -v
```
Expected: ImportError.

- [ ] **Step 10.3: 实现 prompts.py**

Create `csm_core/llm/prompts.py`:
```python
"""Compose three-layer prompt: template default + user skill + SEO constraints."""
from __future__ import annotations
from dataclasses import dataclass
from ..template.schema import SEODefaults


@dataclass
class PromptInputs:
    template_system_prompt: str
    user_skill_prompt: str | None
    seo: SEODefaults
    keyword: str
    draft: str


def _format_seo_block(seo: SEODefaults, keyword: str) -> str:
    parts = [
        f"- 目标字数：{seo.target_word_count[0]}-{seo.target_word_count[1]} 字",
        f"- 主关键词「{keyword}」密度：{seo.keyword_density[0]}-{seo.keyword_density[1]} 次",
        f"- 口吻风格：{seo.tone}",
    ]
    if seo.long_tail_keywords:
        parts.append(f"- 长尾关键词（自然嵌入）：{', '.join(seo.long_tail_keywords)}")
    if seo.force_h2:
        parts.append("- 必须使用 H2 (##) 段落标题分隔核心板块")
    return "【SEO 约束】\n" + "\n".join(parts)


def build_prompt(inputs: PromptInputs) -> tuple[str, str]:
    layers: list[str] = [inputs.template_system_prompt.strip()]
    if inputs.user_skill_prompt:
        layers.append(inputs.user_skill_prompt.strip())
    layers.append(_format_seo_block(inputs.seo, inputs.keyword))
    system = "\n\n".join(layer for layer in layers if layer)

    user = (
        f"【关键词】{inputs.keyword}\n\n"
        f"【毛坯文】\n{inputs.draft}\n\n"
        "请按**润色模式**重写：保留所有信息点和段落结构，只改进文字流畅度、"
        "衔接和风格一致性；不新增虚构事实，不删减关键信息。"
    )
    return system, user
```

- [ ] **Step 10.4: 运行测试确认通过**

```bash
pytest tests/core/llm/test_prompts.py -v
```
Expected: 2 passed.

- [ ] **Step 10.5: Commit**

```bash
git add csm_core/llm/prompts.py tests/core/llm/test_prompts.py
git commit -m "feat(llm): three-layer prompt composition (template + skill + SEO)"
```

---

## Task 11: llm/providers/anthropic.py + deepseek.py — 真实 provider

**Files:**
- Create: `csm_core/llm/providers/anthropic.py`, `csm_core/llm/providers/deepseek.py`
- Test: extend `tests/core/llm/test_client.py`

- [ ] **Step 11.1: 追加测试（mock HTTP）**

Append to `tests/core/llm/test_client.py`:
```python
from unittest.mock import MagicMock, patch
from csm_core.llm.providers.anthropic import AnthropicClient
from csm_core.llm.providers.deepseek import DeepSeekClient


def test_anthropic_client_calls_sdk():
    fake_response = MagicMock()
    fake_response.content = [MagicMock(text="Claude says hi")]
    with patch("csm_core.llm.providers.anthropic.Anthropic") as fake_sdk:
        fake_sdk.return_value.messages.create.return_value = fake_response
        client = AnthropicClient(api_key="sk-x", model="claude-opus-4-7")
        result = client.complete(system="S", user="U")
        assert result == "Claude says hi"
        fake_sdk.return_value.messages.create.assert_called_once()
        call_kwargs = fake_sdk.return_value.messages.create.call_args.kwargs
        assert call_kwargs["system"] == "S"
        assert call_kwargs["messages"] == [{"role": "user", "content": "U"}]
        assert call_kwargs["model"] == "claude-opus-4-7"


def test_deepseek_client_calls_http(monkeypatch):
    class FakeResponse:
        status_code = 200
        def json(self):
            return {"choices": [{"message": {"content": "DS says hi"}}]}
        def raise_for_status(self): pass

    class FakeClient:
        def __init__(self, *a, **kw): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def post(self, url, **kw):
            self.last_kwargs = kw
            return FakeResponse()

    import csm_core.llm.providers.deepseek as mod
    monkeypatch.setattr(mod.httpx, "Client", FakeClient)
    client = DeepSeekClient(api_key="sk-y", model="deepseek-chat")
    result = client.complete(system="S", user="U")
    assert result == "DS says hi"
```

- [ ] **Step 11.2: 运行测试确认失败**

```bash
pytest tests/core/llm/test_client.py -v
```
Expected: ImportError for AnthropicClient / DeepSeekClient.

- [ ] **Step 11.3: 实现 anthropic.py**

Create `csm_core/llm/providers/anthropic.py`:
```python
"""Anthropic Claude provider."""
from __future__ import annotations
from dataclasses import dataclass
from anthropic import Anthropic
from tenacity import retry, stop_after_attempt, wait_exponential


@dataclass
class AnthropicClient:
    api_key: str
    model: str = "claude-opus-4-7"
    max_tokens: int = 4096

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    def complete(self, *, system: str, user: str) -> str:
        sdk = Anthropic(api_key=self.api_key)
        resp = sdk.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return resp.content[0].text
```

- [ ] **Step 11.4: 实现 deepseek.py**

Create `csm_core/llm/providers/deepseek.py`:
```python
"""DeepSeek provider (OpenAI-compatible API)."""
from __future__ import annotations
from dataclasses import dataclass
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential


@dataclass
class DeepSeekClient:
    api_key: str
    model: str = "deepseek-chat"
    base_url: str = "https://api.deepseek.com/v1"
    timeout: float = 60.0

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    def complete(self, *, system: str, user: str) -> str:
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                },
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
```

- [ ] **Step 11.5: 运行测试确认通过**

```bash
pytest tests/core/llm/test_client.py -v
```
Expected: 6 passed total.

- [ ] **Step 11.6: Commit**

```bash
git add csm_core/llm/providers/anthropic.py csm_core/llm/providers/deepseek.py tests/core/llm/test_client.py
git commit -m "feat(llm): add Anthropic and DeepSeek providers with retry"
```

---

## Task 12: export/markdown.py — 导出 .md + .assembly.json

**Files:**
- Create: `csm_core/export/__init__.py`, `csm_core/export/markdown.py`
- Test: `tests/core/export/__init__.py`, `tests/core/export/test_markdown.py`

- [ ] **Step 12.1: 创建包初始化**

Create empty `csm_core/export/__init__.py`, `tests/core/export/__init__.py`.

- [ ] **Step 12.2: 写失败测试**

Create `tests/core/export/test_markdown.py`:
```python
import json
from pathlib import Path
from csm_core.assembler.plan import AssemblyPlan, SlotAssignment, PickedVariant
from csm_core.export.markdown import export_article


def _sample_plan() -> AssemblyPlan:
    return AssemblyPlan(
        keyword="宠物吸尘器推荐",
        template_id="daogou-changjing-renqun",
        seed=42,
        slots=[SlotAssignment(
            slot_id="intro",
            picks=[PickedVariant(note_id="n", variant_index=0, text="引言内容")],
        )],
    )


def test_export_writes_md_and_assembly_json(tmp_path: Path):
    paths = export_article(
        out_dir=tmp_path,
        keyword="宠物吸尘器推荐",
        final_text="# 标题\n\n正文内容",
        plan=_sample_plan(),
        prompt_snapshot={"system": "sys", "user": "usr", "provider": "mock"},
    )
    md_path = Path(paths["markdown"])
    json_path = Path(paths["assembly_json"])
    assert md_path.exists()
    assert md_path.read_text(encoding="utf-8") == "# 标题\n\n正文内容"
    assert json_path.exists()
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data["plan"]["keyword"] == "宠物吸尘器推荐"
    assert data["prompt_snapshot"]["provider"] == "mock"


def test_export_sanitizes_filename(tmp_path: Path):
    paths = export_article(
        out_dir=tmp_path,
        keyword="带/特殊\\字符:的?关键词",
        final_text="x",
        plan=_sample_plan(),
        prompt_snapshot={},
    )
    md_path = Path(paths["markdown"])
    assert md_path.exists()
    for ch in ("/", "\\", ":", "?"):
        assert ch not in md_path.name


def test_export_raises_when_out_dir_missing(tmp_path: Path):
    nonexistent = tmp_path / "does_not_exist"
    import pytest
    with pytest.raises(FileNotFoundError):
        export_article(
            out_dir=nonexistent,
            keyword="k", final_text="t",
            plan=_sample_plan(), prompt_snapshot={},
        )
```

- [ ] **Step 12.3: 运行测试确认失败**

```bash
pytest tests/core/export/test_markdown.py -v
```
Expected: ImportError.

- [ ] **Step 12.4: 实现 markdown.py**

Create `csm_core/export/markdown.py`:
```python
"""Export final article as .md plus .assembly.json snapshot."""
from __future__ import annotations
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from ..assembler.plan import AssemblyPlan

_INVALID_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|]')


def _sanitize_filename(name: str) -> str:
    return _INVALID_FILENAME_CHARS.sub("-", name).strip()


def export_article(
    *,
    out_dir: Path,
    keyword: str,
    final_text: str,
    plan: AssemblyPlan,
    prompt_snapshot: dict[str, Any],
) -> dict[str, str]:
    out_dir = Path(out_dir)
    if not out_dir.exists():
        raise FileNotFoundError(f"output directory does not exist: {out_dir}")

    stem = _sanitize_filename(keyword)
    md_path = out_dir / f"{stem}.md"
    json_path = out_dir / f"{stem}.assembly.json"

    md_path.write_text(final_text, encoding="utf-8")

    snapshot = {
        "exported_at": datetime.now().isoformat(timespec="seconds"),
        "keyword": keyword,
        "plan": plan.model_dump(),
        "prompt_snapshot": prompt_snapshot,
    }
    json_path.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return {"markdown": str(md_path), "assembly_json": str(json_path)}
```

- [ ] **Step 12.5: 运行测试确认通过**

```bash
pytest tests/core/export/test_markdown.py -v
```
Expected: 3 passed.

- [ ] **Step 12.6: Commit**

```bash
git add csm_core/export/ tests/core/export/
git commit -m "feat(export): write article .md and .assembly.json snapshot"
```

---

## Task 13: pipeline.py — 端到端编排

**Files:**
- Create: `csm_core/pipeline.py`
- Test: `tests/core/test_pipeline.py`

- [ ] **Step 13.1: 写失败测试**

Create `tests/core/test_pipeline.py`:
```python
from pathlib import Path
from csm_core.pipeline import generate, GenerateRequest
from csm_core.llm.providers.mock import MockClient


def test_generate_runs_end_to_end(mini_vault_path: Path, tmp_path: Path):
    template_path = Path(__file__).parent.parent.parent / "templates" / "daogou-changjing-renqun.json"
    client = MockClient(response="# 洗稿后文章\n\n内容")
    req = GenerateRequest(
        keyword="宠物吸尘器推荐",
        vault_root=mini_vault_path,
        template_path=template_path,
        out_dir=tmp_path,
        llm_client=client,
        user_skill_prompt=None,
        seed=42,
        user_config={"brand_competitors": 2},
    )
    result = generate(req)
    assert Path(result.markdown_path).exists()
    assert Path(result.assembly_json_path).exists()
    assert "# 洗稿后文章" in Path(result.markdown_path).read_text(encoding="utf-8")
    # MockClient should have been called once
    assert len(client.calls) == 1
    # system prompt should contain SEO block
    assert "SEO" in client.calls[0]["system"]
```

- [ ] **Step 13.2: 运行测试确认失败**

```bash
pytest tests/core/test_pipeline.py -v
```
Expected: ImportError.

- [ ] **Step 13.3: 实现 pipeline.py**

Create `csm_core/pipeline.py`:
```python
"""End-to-end orchestration: keyword + template → article."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from .vault.scanner import scan_vault
from .vault.brand_registry import build_brand_registry
from .template.loader import load_template
from .assembler.constraints import assemble_plan
from .assembler.plan import AssemblyPlan
from .llm.client import LLMClient
from .llm.prompts import build_prompt, PromptInputs
from .export.markdown import export_article


@dataclass
class GenerateRequest:
    keyword: str
    vault_root: Path
    template_path: Path
    out_dir: Path
    llm_client: LLMClient
    user_skill_prompt: str | None = None
    seed: int = 0
    user_config: dict[str, int] | None = None


@dataclass
class GenerateResult:
    markdown_path: str
    assembly_json_path: str
    plan: AssemblyPlan
    final_text: str


def _render_draft(plan: AssemblyPlan) -> str:
    parts: list[str] = []
    for slot in plan.slots:
        if not slot.picks:
            continue
        parts.append("\n\n".join(p.text for p in slot.picks))
    return "\n\n".join(parts)


def generate(req: GenerateRequest) -> GenerateResult:
    index = scan_vault(req.vault_root)
    registry = build_brand_registry(req.vault_root)
    template = load_template(req.template_path)

    plan = assemble_plan(
        keyword=req.keyword,
        template=template,
        index=index,
        registry=registry,
        seed=req.seed,
        user_config=req.user_config or {},
    )

    draft = _render_draft(plan)

    system, user = build_prompt(PromptInputs(
        template_system_prompt=template.system_prompt_default,
        user_skill_prompt=req.user_skill_prompt,
        seo=template.seo_defaults,
        keyword=req.keyword,
        draft=draft,
    ))
    final_text = req.llm_client.complete(system=system, user=user)

    paths = export_article(
        out_dir=req.out_dir,
        keyword=req.keyword,
        final_text=final_text,
        plan=plan,
        prompt_snapshot={
            "system": system,
            "user": user,
            "provider": type(req.llm_client).__name__,
        },
    )
    return GenerateResult(
        markdown_path=paths["markdown"],
        assembly_json_path=paths["assembly_json"],
        plan=plan,
        final_text=final_text,
    )
```

- [ ] **Step 13.4: 运行测试确认通过**

```bash
pytest tests/core/test_pipeline.py -v
```
Expected: 1 passed.

- [ ] **Step 13.5: Commit**

```bash
git add csm_core/pipeline.py tests/core/test_pipeline.py
git commit -m "feat(core): end-to-end pipeline orchestration"
```

---

## Task 14: CLI 入口 `python -m csm_core "关键词" --template ...`

**Files:**
- Create: `csm_core/__main__.py`
- Test: `tests/core/test_cli.py`

- [ ] **Step 14.1: 写失败测试**

Create `tests/core/test_cli.py`:
```python
from pathlib import Path
from click.testing import CliRunner
from csm_core.__main__ import cli


def test_cli_runs_with_mock_provider(mini_vault_path: Path, tmp_path: Path):
    template_path = Path(__file__).parent.parent.parent / "templates" / "daogou-changjing-renqun.json"
    runner = CliRunner()
    result = runner.invoke(cli, [
        "宠物吸尘器推荐",
        "--template", str(template_path),
        "--vault", str(mini_vault_path),
        "--out", str(tmp_path),
        "--provider", "mock",
        "--mock-response", "# 测试输出",
        "--seed", "42",
    ])
    assert result.exit_code == 0, result.output
    md_files = list(tmp_path.glob("*.md"))
    assert len(md_files) == 1
    assert md_files[0].read_text(encoding="utf-8") == "# 测试输出"
```

- [ ] **Step 14.2: 运行测试确认失败**

```bash
pytest tests/core/test_cli.py -v
```
Expected: ImportError.

- [ ] **Step 14.3: 实现 __main__.py**

Create `csm_core/__main__.py`:
```python
"""CLI entry point: python -m csm_core 'keyword' --template ..."""
from __future__ import annotations
from pathlib import Path
import click
from .pipeline import generate, GenerateRequest
from .llm.client import make_client


@click.command()
@click.argument("keyword")
@click.option("--template", "template_path", required=True, type=click.Path(exists=True, path_type=Path))
@click.option("--vault", "vault_root", required=True, type=click.Path(exists=True, path_type=Path))
@click.option("--out", "out_dir", required=True, type=click.Path(exists=True, path_type=Path))
@click.option("--provider", default="mock", type=click.Choice(["mock", "anthropic", "deepseek"]))
@click.option("--api-key", default=None, help="API key for provider (or use env var)")
@click.option("--model", default=None, help="Model name override")
@click.option("--skill", "skill_path", default=None, type=click.Path(exists=True, path_type=Path))
@click.option("--seed", default=0, type=int)
@click.option("--mock-response", default="mock response", help="Response text for mock provider")
def cli(keyword, template_path, vault_root, out_dir, provider, api_key, model,
        skill_path, seed, mock_response):
    """Generate an SEO article from keyword + template."""
    client_kwargs = {}
    if provider == "mock":
        client_kwargs["response"] = mock_response
    else:
        if not api_key:
            import os
            api_key = os.environ.get(f"{provider.upper()}_API_KEY", "")
        client_kwargs["api_key"] = api_key
        if model:
            client_kwargs["model"] = model
    client = make_client(provider=provider, **client_kwargs)

    skill_prompt = None
    if skill_path:
        skill_prompt = Path(skill_path).read_text(encoding="utf-8")

    result = generate(GenerateRequest(
        keyword=keyword,
        vault_root=vault_root,
        template_path=template_path,
        out_dir=out_dir,
        llm_client=client,
        user_skill_prompt=skill_prompt,
        seed=seed,
    ))
    click.echo(f"✓ Generated: {result.markdown_path}")
    click.echo(f"  Snapshot : {result.assembly_json_path}")


if __name__ == "__main__":
    cli()
```

- [ ] **Step 14.4: 运行测试确认通过**

```bash
pytest tests/core/test_cli.py -v
```
Expected: 1 passed.

- [ ] **Step 14.5: 运行全量测试确认覆盖**

```bash
pytest --cov=csm_core --cov-report=term-missing
```
Expected: ≥ 40 tests pass; 总覆盖率 ≥ 80%。

- [ ] **Step 14.6: 手工烟雾测试**

```bash
python -m csm_core "宠物家庭吸尘器推荐" \
  --template templates/daogou-changjing-renqun.json \
  --vault tests/fixtures/mini_vault/营销资料库 \
  --out output \
  --provider mock \
  --mock-response "# 最终文章\n\n内容..."
```
Expected: stdout 打印 `✓ Generated: output\宠物家庭吸尘器推荐.md` 和同名 assembly.json。

（先 `mkdir D:\CSM\output` 确保目录存在）

- [ ] **Step 14.7: Commit**

```bash
git add csm_core/__main__.py tests/core/test_cli.py
git commit -m "feat(cli): add python -m csm_core entry point"
```

---

## Self-Review 检查清单（完成所有 Task 后跑一遍）

- [ ] **Spec 覆盖**：§4 模块划分 core 部分 ✓；§5 DSL 全部字段有 schema 支持 ✓；§6 数据流 5 步 Task 1-13 覆盖 ✓；§8 错误处理的 EmptyPool/缺数据 ✓
- [ ] **Placeholder 扫描**：无 TBD/TODO/appropriate error handling；所有代码步骤有完整代码块
- [ ] **类型一致性**：`ParsedNote`、`VaultIndex`、`Template`、`Slot`、`AssemblyPlan`、`PickedVariant`、`SlotAssignment`、`LLMClient` 跨 Task 引用名称统一
- [ ] **测试覆盖率** ≥ 80%（Task 14 Step 5 验证）
- [ ] **未在本 Plan 范围**（延到 Plan B/C）：GUI 层、framework md→JSON importer、docx 导出、prompts/ 目录扫描
