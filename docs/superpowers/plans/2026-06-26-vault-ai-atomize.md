# Phase 3b：AI 拆条归类入库 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 粘贴一篇家电营销资料 → LLM 忠实拆成原子素材并归类 → 人工逐条审阅修正 → 复用 3a 写入器落库到共享盘 Obsidian vault。

**Architecture:** 写入侧零改动复用 3a（`writer.py` 引擎 + `/api/vault/{plan,commit,undo}`）。新增 1 个后端 `POST /api/vault/atomize`（`atomize_service` 调 `llm_factory` + 真实库菜单 grounding，纯函数 `csm_core/vault/atomizer.py` 解析 LLM JSON 数组）+ 1 个前端 tab「AI 拆条」（`AtomizePanel` 粘贴 → N 张 `AtomCard` 逐条 plan/commit/undo +「全部入库」）。

**Tech Stack:** Python（csm_core 纯函数 + FastAPI sidecar，pytest）、Vue 3 + Pinia + TS（vitest + vue-tsc）。LLM 走 `llm_factory.build_client()`，解析镜像 `xhs_ai_service`。

**依据 spec:** `docs/superpowers/specs/2026-06-26-vault-ai-atomize-design.md`（5 决策 D1–D5）。

---

## 测试命令前缀（每个后端步骤复用）

后端（PowerShell，worktree 根）：
```powershell
$env:PYTHONPATH = "D:\CSM\.claude\worktrees\busy-matsumoto-c087bd;D:\CSM\.claude\worktrees\busy-matsumoto-c087bd\sidecar"
& "D:\CSM\.venv\Scripts\python.exe" -X utf8 -m pytest <测试路径> -v
```
前端（worktree\frontend）：
```powershell
cd D:\CSM\.claude\worktrees\busy-matsumoto-c087bd\frontend
npx vitest run <spec 路径>
# 全部完成后必跑：npx vue-tsc -b
```

## File Structure

| 文件 | 职责 | 动作 |
|---|---|---|
| `csm_core/vault/atomizer.py` | 纯函数：AtomDraft + build_menu + _safe_filename + parse_atoms（解析 LLM JSON 数组、grounding 校验） | Create |
| `tests/core/vault/test_atomizer.py` | atomizer 纯函数单测 | Create |
| `sidecar/csm_sidecar/services/atomize_service.py` | scan 库 → build_menu → llm_factory.complete → parse_atoms；空输入/超长/未配 provider 处理 | Create |
| `sidecar/csm_sidecar/routes/vault_atomize.py` | `POST /api/vault/atomize`，503/400/422 映射（LLMConfigError 先于 ValueError） | Create |
| `sidecar/csm_sidecar/main.py` | 注册 vault_atomize router | Modify |
| `sidecar/tests/test_atomize_service.py` | service 测试（mock LLM + tmp 库） | Create |
| `sidecar/tests/test_vault_atomize_routes.py` | 路由测试（200/503/400/422） | Create |
| `frontend/src/components/materials/payload.ts` | 共享 helper：assembleFrontmatter + filenameError | Create |
| `frontend/src/components/materials/IntakeForm.vue` | 改用共享 helper（DRY，测试保持绿） | Modify |
| `frontend/src/stores/materials.ts` | AtomDraft 接口 + atomizeText/commitAtom/undoAtom（返回值型，不碰 3a 单槽位） | Modify |
| `frontend/src/components/materials/AtomCard.vue` | 一条原子的可编辑卡 + 逐条 commit/undo + commitAuto 暴露 | Create |
| `frontend/src/components/materials/AtomizePanel.vue` | 粘贴框 + 拆条 + N 卡（low 置顶）+ 全部入库 | Create |
| `frontend/src/views/MaterialsView.vue` | 第 3 个 tab「AI 拆条」 | Modify |
| `frontend/src/components/materials/__tests__/payload.spec.ts` | helper 测试 | Create |
| `frontend/src/stores/__tests__/materials.atomize.spec.ts` | store 动作测试 | Create |
| `frontend/src/components/materials/__tests__/AtomCard.spec.ts` | 卡测试 | Create |
| `frontend/src/components/materials/__tests__/AtomizePanel.spec.ts` | 面板测试 | Create |

---

# Unit A —— `csm_core/vault/atomizer.py`（纯函数）

### Task A1：AtomDraft + build_menu + _safe_filename

**Files:** Create `csm_core/vault/atomizer.py`、`tests/core/vault/test_atomizer.py`

- [ ] **Step 1: 写失败测试**（`tests/core/vault/test_atomizer.py`）

```python
from csm_core.vault import atomizer as A
from csm_core.vault.folder_profile import FolderProfile


def _folders():
    return [
        FolderProfile(rel_folder="科普模块/吸尘器/挑选攻略",
                      frontmatter_keys=["产品", "素材类型", "核心关键词"],
                      defaults={"产品": "吸尘器"}, body_shape="variants",
                      sample_count=2, material_types=["科普选购", "引言痛点"]),
        FolderProfile(rel_folder="产品模块/吸尘器/产品参数",
                      frontmatter_keys=["品牌", "型号"], defaults={},
                      body_shape="spec_table", sample_count=1, material_types=["产品参数"]),
    ]


def test_build_menu_excludes_spec_table_and_lists_types():
    menu = A.build_menu(_folders())
    assert "科普模块/吸尘器/挑选攻略" in menu
    assert "科普选购" in menu and "引言痛点" in menu
    assert "产品模块/吸尘器/产品参数" not in menu     # spec_table 不进菜单


def test_safe_filename_spaces_and_seps():
    assert A._safe_filename("吸力 选购", "kw") == "吸力-选购.md"
    assert A._safe_filename("a/b\\c", "kw") == "a-b-c.md"


def test_safe_filename_empty_uses_fallback():
    assert A._safe_filename("", "吸力") == "吸力.md"
    assert A._safe_filename("   ", "") == "素材.md"


def test_safe_filename_keeps_md_suffix():
    assert A._safe_filename("吸力选购.md", "kw") == "吸力选购.md"
```

- [ ] **Step 2: 跑测试确认失败**

Run（backend）: `... -m pytest tests/core/vault/test_atomizer.py -v`
Expected: FAIL `ModuleNotFoundError: csm_core.vault.atomizer`

- [ ] **Step 3: 实现 atomizer.py 第一部分**

```python
"""把一篇资料拆成原子素材的纯函数层（无 LLM、无磁盘）。

LLM 调用在 sidecar 的 atomize_service；本模块只负责：把真实库文件夹拼成
喂 LLM 的菜单（build_menu）、把 LLM 返回的 JSON 数组解析+校验成 AtomDraft
（parse_atoms）。grounding：建议文件夹必须在真实菜单里，否则置空+warning
——off-menu 进不了库。忠实拆条（spec D1）：正文 = 原文，写成单变体①。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from .folder_profile import FolderProfile


@dataclass(frozen=True)
class AtomDraft:
    text: str                       # 正文（单变体①，忠实原文）
    rel_folder: str | None          # 已对真实菜单校验；off-menu → None
    material_type: str              # 素材类型（预填提示，人工可改）
    product: str                    # 产品：希喂/戴森/小米/追觅/通用
    keyword: str                    # 核心关键词
    filename: str                   # 已 sanitize，.md 结尾
    confidence: str                 # high|med|low（非法 → low）
    warnings: list[str] = field(default_factory=list)


def build_menu(folders: list[FolderProfile]) -> str:
    """把可写文件夹拼成喂 LLM 的菜单串。只取内容型（body_shape != spec_table）
    ——产品参数表归 3a 手动录入，prose 拆条不该落进参数表。"""
    lines = []
    for f in folders:
        if f.body_shape == "spec_table":
            continue
        types = "/".join(f.material_types) if f.material_types else "（无固定类型）"
        lines.append(f"- {f.rel_folder} ｜ 素材类型: {types}")
    return "\n".join(lines)


def _safe_filename(raw: str, fallback: str) -> str:
    """空格/路径分隔符 → 连字符；空 → fallback（取关键词或正文首段）；保证 .md 结尾。
    中文允许（库里就是中文笔记名）。"""
    s = (raw or "").strip()
    if not s:
        s = (fallback or "").strip() or "素材"
    s = re.sub(r"[\s/\\]+", "-", s).strip("-") or "素材"
    if not s.endswith(".md"):
        s = s + ".md"
    return s
```

- [ ] **Step 4: 跑测试确认通过**

Run: `... -m pytest tests/core/vault/test_atomizer.py -v`
Expected: PASS（4 passed）

- [ ] **Step 5: 提交**

```bash
git add csm_core/vault/atomizer.py tests/core/vault/test_atomizer.py
git commit -m "feat(3b): atomizer AtomDraft + build_menu + _safe_filename

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

### Task A2：parse_atoms（解析 LLM JSON 数组 + grounding）

**Files:** Modify `csm_core/vault/atomizer.py`、`tests/core/vault/test_atomizer.py`

- [ ] **Step 1: 追加失败测试**（接到 `test_atomizer.py` 末尾）

```python
import json as _json


def test_parse_atoms_valid_array():
    raw = _json.dumps([
        {"正文": "看吸力", "建议文件夹": "科普模块/吸尘器/挑选攻略", "素材类型": "科普选购",
         "产品": "通用", "核心关键词": "吸力", "建议文件名": "吸力选购", "置信度": "high"},
        {"正文": "看噪音", "建议文件夹": "科普模块/吸尘器/挑选攻略", "素材类型": "科普选购",
         "产品": "希喂", "核心关键词": "噪音", "建议文件名": "噪音", "置信度": "med"},
    ], ensure_ascii=False)
    atoms = A.parse_atoms(raw, _folders())
    assert len(atoms) == 2
    assert atoms[0].text == "看吸力"
    assert atoms[0].rel_folder == "科普模块/吸尘器/挑选攻略"
    assert atoms[0].filename == "吸力选购.md"
    assert atoms[0].confidence == "high"
    assert atoms[1].product == "希喂"


def test_parse_atoms_strips_code_fence():
    raw = "```json\n" + _json.dumps([{"正文": "x", "置信度": "low"}], ensure_ascii=False) + "\n```"
    atoms = A.parse_atoms(raw, _folders())
    assert len(atoms) == 1 and atoms[0].text == "x"


def test_parse_atoms_extracts_array_with_preamble():
    raw = "好的，拆好了：\n" + _json.dumps([{"正文": "y", "置信度": "high"}], ensure_ascii=False)
    atoms = A.parse_atoms(raw, _folders())
    assert len(atoms) == 1 and atoms[0].text == "y"


def test_parse_atoms_non_array_returns_empty():
    assert A.parse_atoms('{"正文": "x"}', _folders()) == []
    assert A.parse_atoms("根本不是 JSON", _folders()) == []


def test_parse_atoms_offmenu_folder_blanked_with_warning():
    raw = _json.dumps([{"正文": "z", "建议文件夹": "不存在/文件夹", "置信度": "med"}], ensure_ascii=False)
    atoms = A.parse_atoms(raw, _folders())
    assert atoms[0].rel_folder is None
    assert any("不在素材库" in w for w in atoms[0].warnings)


def test_parse_atoms_invalid_confidence_defaults_low():
    raw = _json.dumps([{"正文": "z", "置信度": "拿不准"}], ensure_ascii=False)
    assert A.parse_atoms(raw, _folders())[0].confidence == "low"


def test_parse_atoms_empty_text_skipped():
    raw = _json.dumps([{"正文": "   ", "置信度": "high"}, {"正文": "ok", "置信度": "high"}], ensure_ascii=False)
    atoms = A.parse_atoms(raw, _folders())
    assert len(atoms) == 1 and atoms[0].text == "ok"


def test_parse_atoms_filename_from_keyword_when_missing():
    raw = _json.dumps([{"正文": "z", "核心关键词": "续航", "置信度": "high"}], ensure_ascii=False)
    assert A.parse_atoms(raw, _folders())[0].filename == "续航.md"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `... -m pytest tests/core/vault/test_atomizer.py -v`
Expected: FAIL `AttributeError: module 'csm_core.vault.atomizer' has no attribute 'parse_atoms'`

- [ ] **Step 3: 追加 parse_atoms 实现**（接到 `atomizer.py` 末尾）

```python
def _strip_code_fence(text: str) -> str:
    """去掉模型偶尔包裹的 ```json ... ``` 围栏（逻辑同 xhs_ai_service，本层自带一份）。"""
    t = text.strip()
    if not t.startswith("```"):
        return t
    lines = t.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _loads_array(raw: str):
    """整体解析失败时，正则抠出第一个 [...] 再试；都失败 → None。"""
    t = _strip_code_fence((raw or "").strip())
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        m = re.search(r"\[.*\]", t, re.DOTALL)
        if not m:
            return None
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            return None


def parse_atoms(raw_llm_text: str, folders: list[FolderProfile]) -> list[AtomDraft]:
    """把 LLM 返回解析+校验成 AtomDraft 列表（忠实拆条 spec §4.1/§5）。

    grounding：建议文件夹必须 ∈ 真实菜单，否则置空 + warning（off-menu 进不了库）。
    正文空 → 跳过；置信度非 high/med/low → low；文件名 sanitize（空则取关键词/正文首段）。
    整体非数组 → 返回 []。
    """
    data = _loads_array(raw_llm_text)
    if not isinstance(data, list):
        return []
    allowed = {f.rel_folder for f in folders}
    out: list[AtomDraft] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        text = str(item.get("正文") or "").strip()
        if not text:
            continue
        warnings: list[str] = []
        rel = (str(item.get("建议文件夹") or "").strip()) or None
        if rel is not None and rel not in allowed:
            warnings.append(f"建议文件夹「{rel}」不在素材库中，请人工选择")
            rel = None
        keyword = str(item.get("核心关键词") or "").strip()
        conf = str(item.get("置信度") or "").strip().lower()
        if conf not in ("high", "med", "low"):
            conf = "low"
        filename = _safe_filename(str(item.get("建议文件名") or ""), keyword or text[:12])
        out.append(AtomDraft(
            text=text, rel_folder=rel,
            material_type=str(item.get("素材类型") or "").strip(),
            product=str(item.get("产品") or "").strip(),
            keyword=keyword, filename=filename, confidence=conf, warnings=warnings))
    return out
```

- [ ] **Step 4: 跑测试确认通过**

Run: `... -m pytest tests/core/vault/test_atomizer.py -v`
Expected: PASS（12 passed）

- [ ] **Step 5: 提交**

```bash
git add csm_core/vault/atomizer.py tests/core/vault/test_atomizer.py
git commit -m "feat(3b): parse_atoms 解析 LLM JSON 数组 + 真实库 grounding

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

# Unit B —— sidecar atomize service + route

### Task B1：atomize_service

**Files:** Create `sidecar/csm_sidecar/services/atomize_service.py`、`sidecar/tests/test_atomize_service.py`

- [ ] **Step 1: 写失败测试**（`sidecar/tests/test_atomize_service.py`）

```python
"""atomize_service 测试。Mock 策略同 xhs_ai_service：recording fake client +
monkeypatch build_client；503 分支不打 patch 让真 build_client 抛 LLMConfigError。
vault 走 tmp_path，绝不碰真实库。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from csm_sidecar.services import atomize_service, config_service, vault_service
from csm_sidecar.services.llm_factory import LLMConfigError


def _seed_vault(tmp_path: Path) -> Path:
    root = tmp_path / "vault"
    d = root / "科普模块/吸尘器/挑选攻略"
    d.mkdir(parents=True, exist_ok=True)
    (d / "吸尘器-吸力选购.md").write_text(
        "---\n产品: 吸尘器\n素材类型: 科普选购\n核心关键词:\n  - 吸力\n---\n\n① 看吸力\n",
        encoding="utf-8")
    return root


@pytest.fixture(autouse=True)
def _cfg(tmp_path: Path):
    config_service.init(tmp_path / "settings.json")
    yield
    config_service.init(None)
    vault_service.invalidate()


class _Rec:
    def __init__(self, resp: str = ""):
        self.resp = resp
        self.calls: list[dict] = []

    def complete(self, *, system: str, user: str, temperature: float | None = None) -> str:
        self.calls.append({"system": system, "user": user, "temperature": temperature})
        return self.resp


@pytest.fixture
def fake(monkeypatch):
    c = _Rec()
    monkeypatch.setattr(atomize_service.llm_factory, "build_client", lambda **kw: c)
    return c


def test_atomize_returns_grounded(tmp_path, fake):
    config_service.patch({"vault_root": str(_seed_vault(tmp_path)), "default_provider": "mock"})
    fake.resp = json.dumps([{"正文": "看吸力", "建议文件夹": "科普模块/吸尘器/挑选攻略",
                             "素材类型": "科普选购", "产品": "通用", "核心关键词": "吸力",
                             "建议文件名": "吸力", "置信度": "high"}], ensure_ascii=False)
    atoms = atomize_service.atomize("一段关于吸力的资料")
    assert len(atoms) == 1
    assert atoms[0]["rel_folder"] == "科普模块/吸尘器/挑选攻略"
    assert atoms[0]["filename"].endswith(".md")
    assert atoms[0]["confidence"] == "high"
    assert "科普模块/吸尘器/挑选攻略" in fake.calls[0]["user"]   # 菜单注入
    assert fake.calls[0]["temperature"] == 0.2


def test_atomize_empty_no_llm(tmp_path, fake):
    config_service.patch({"vault_root": str(_seed_vault(tmp_path)), "default_provider": "mock"})
    assert atomize_service.atomize("   ") == []
    assert fake.calls == []


def test_atomize_offmenu_folder_blanked(tmp_path, fake):
    config_service.patch({"vault_root": str(_seed_vault(tmp_path)), "default_provider": "mock"})
    fake.resp = json.dumps([{"正文": "x", "建议文件夹": "不存在/文件夹", "置信度": "med"}], ensure_ascii=False)
    atoms = atomize_service.atomize("资料")
    assert atoms[0]["rel_folder"] is None
    assert any("不在素材库" in w for w in atoms[0]["warnings"])


def test_atomize_no_provider_raises(tmp_path):
    config_service.patch({"vault_root": str(_seed_vault(tmp_path))})   # 不设 provider
    with pytest.raises(LLMConfigError):
        atomize_service.atomize("资料")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `... -m pytest sidecar/tests/test_atomize_service.py -v`
Expected: FAIL `ImportError: cannot import name 'atomize_service'`

- [ ] **Step 3: 实现 atomize_service.py**

```python
"""AI 拆条服务（spec 3b §4.2）。

scan 真实库 → build_menu（grounding）→ llm_factory.complete → parse_atoms。
LLM client 复用 llm_factory（与润色/mining/xhs 同一套设置）；未配 provider 时
LLMConfigError 透传给路由层包成 503。vault_root 解析复用 3a 的
vault_writer_service._root()（同 services 包，同一份存在性校验，避免重复）。
"""
from __future__ import annotations

from dataclasses import asdict

from csm_core.vault import folder_profile
from csm_core.vault.atomizer import build_menu, parse_atoms

from . import config_service, llm_factory, vault_service, vault_writer_service

_MAX_INPUT = 8000   # v1 不分块：超长截断 + warning

ATOMIZE_SYSTEM = (
    "你是家电营销资料的素材拆条助手。把用户给的原文【忠实拆分】成多条可复用的"
    "原子素材，每条只讲一个要点。严格要求：\n"
    "1) 忠实：尽量保留原文措辞，不改写、不扩写、不编造，不要把不同要点合并；一个要点一条。\n"
    "2) 归类：从【可选归类菜单】里给每条选一个最合适的「建议文件夹」和「素材类型」；"
    "菜单里没有合适的就把这两项留空字符串（交给人工定）。\n"
    "3) 产品：从 希喂 / 戴森 / 小米 / 追觅 / 通用 中选（希喂是自家品牌）。\n"
    "4) 置信度：给每条一个「置信度」= high / med / low，只评你对【归类】的把握，不评正文。\n"
    "5) 文件名：给一个简短的「建议文件名」（中文可，不含空格和斜杠，可不带 .md）。\n"
    "只返回一个 JSON 数组，每个元素形如 "
    '{"正文": "...", "建议文件夹": "...", "素材类型": "...", "产品": "...", '
    '"核心关键词": "...", "建议文件名": "...", "置信度": "high"}，'
    "不要输出 JSON 数组以外的任何文字、解释或 markdown 代码块标记。"
)


def atomize(text: str) -> list[dict]:
    """把 text 拆成原子素材列表（每个元素 = asdict(AtomDraft)）。

    Raises
    ------
    ValueError
        vault_root 未配置/不存在（路由层 → 400）。
    llm_factory.LLMConfigError
        未配 default provider / api key（路由层 → 503）。
    OSError
        共享盘断开/占用（scan 阶段，路由层 → 503）。
    """
    text = (text or "").strip()
    if not text:
        return []
    if len(text) > _MAX_INPUT:
        text = text[:_MAX_INPUT]
    root = vault_writer_service._root()          # 复用 3a 的 vault_root 解析
    index = vault_service.scan(root)
    folders = folder_profile.list_writable_folders(index)
    menu = build_menu(folders)
    client = llm_factory.build_client()
    raw = client.complete(
        system=ATOMIZE_SYSTEM,
        user=f"【可选归类菜单】\n{menu}\n\n【待拆分原文】\n{text}",
        temperature=0.2)
    return [asdict(a) for a in parse_atoms(raw, folders)]
```

- [ ] **Step 4: 跑测试确认通过**

Run: `... -m pytest sidecar/tests/test_atomize_service.py -v`
Expected: PASS（4 passed）

- [ ] **Step 5: 提交**

```bash
git add sidecar/csm_sidecar/services/atomize_service.py sidecar/tests/test_atomize_service.py
git commit -m "feat(3b): atomize_service 拆条服务（grounding + mock 测试）

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

### Task B2：vault_atomize 路由 + 注册

**Files:** Create `sidecar/csm_sidecar/routes/vault_atomize.py`、`sidecar/tests/test_vault_atomize_routes.py`；Modify `sidecar/csm_sidecar/main.py`

- [ ] **Step 1: 写失败测试**（`sidecar/tests/test_vault_atomize_routes.py`）

```python
"""vault_atomize 路由测试。复用 conftest 的 client（已带 token）+ tmp 库。"""
from __future__ import annotations

import json
from pathlib import Path

from csm_sidecar.services import config_service, vault_service


def _seed_vault(tmp_path: Path) -> Path:
    root = tmp_path / "vault"
    d = root / "科普模块/吸尘器/挑选攻略"
    d.mkdir(parents=True, exist_ok=True)
    (d / "吸尘器-吸力选购.md").write_text(
        "---\n产品: 吸尘器\n素材类型: 科普选购\n核心关键词:\n  - 吸力\n---\n\n① 看吸力\n",
        encoding="utf-8")
    return root


def _use_vault(root: Path) -> None:
    config_service.patch({"vault_root": str(root)})
    vault_service.invalidate()


def test_atomize_200(client, tmp_path, monkeypatch):
    _use_vault(_seed_vault(tmp_path))
    config_service.patch({"default_provider": "mock"})
    from csm_sidecar.routes import vault_atomize as va

    class _Rec:
        def complete(self, *, system, user, temperature=None):
            return json.dumps([{"正文": "看吸力", "建议文件夹": "科普模块/吸尘器/挑选攻略",
                                "置信度": "high"}], ensure_ascii=False)

    monkeypatch.setattr(va.atomize_service.llm_factory, "build_client", lambda **kw: _Rec())
    r = client.post("/api/vault/atomize", json={"text": "资料"})
    assert r.status_code == 200
    assert r.json()["atoms"][0]["rel_folder"] == "科普模块/吸尘器/挑选攻略"


def test_atomize_503_no_provider(client, tmp_path):
    _use_vault(_seed_vault(tmp_path))
    config_service.patch({"default_provider": None})
    assert client.post("/api/vault/atomize", json={"text": "资料"}).status_code == 503


def test_atomize_400_no_vault(client):
    config_service.patch({"vault_root": None})
    assert client.post("/api/vault/atomize", json={"text": "资料"}).status_code == 400


def test_atomize_422_missing_text(client):
    assert client.post("/api/vault/atomize", json={}).status_code == 422
```

- [ ] **Step 2: 跑测试确认失败**

Run: `... -m pytest sidecar/tests/test_vault_atomize_routes.py -v`
Expected: FAIL（404，路由未注册）

- [ ] **Step 3: 实现 routes/vault_atomize.py**

```python
"""AI 拆条路由（与确定性 vault_writer 分文件——单一职责，它会因 LLM 配置 503）。

关键顺序：LLMConfigError 必须先于 ValueError 捕获（它 subclass ValueError），
否则未配 provider 会被误判成 400 而不是 503。
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from ..auth import RequireToken
from ..services import atomize_service
from ..services.llm_factory import LLMConfigError

router = APIRouter(tags=["vault_atomize"], dependencies=[RequireToken])


class AtomizeBody(BaseModel):
    text: str            # 缺字段 → 422；空串 → service 返回 []（不打 LLM）


@router.post("/api/vault/atomize")
def atomize(body: AtomizeBody) -> dict:
    try:
        return {"atoms": atomize_service.atomize(body.text)}
    except LLMConfigError as e:        # 必须先于 ValueError（subclass）
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e))
    except ValueError as e:            # vault_root 未配/不存在
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except OSError as e:               # 共享盘断开/占用（scan 阶段）
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"拆条失败：素材库不可读（共享盘断开或文件被占用）: {e}")
```

- [ ] **Step 4: 注册 router**（`sidecar/csm_sidecar/main.py`）

在 `from .routes import vault_writer as vault_writer_routes`（35 行附近）下一行加：
```python
from .routes import vault_atomize as vault_atomize_routes
```
在 `app.include_router(vault_writer_routes.router)`（82 行附近）下一行加：
```python
app.include_router(vault_atomize_routes.router)
```

- [ ] **Step 5: 跑测试确认通过**

Run: `... -m pytest sidecar/tests/test_vault_atomize_routes.py -v`
Expected: PASS（4 passed）

- [ ] **Step 6: 跑 Unit A+B 全量回归**

Run: `... -m pytest tests/core/vault/test_atomizer.py sidecar/tests/test_atomize_service.py sidecar/tests/test_vault_atomize_routes.py sidecar/tests/test_vault_writer_routes.py -v`
Expected: 全 PASS（3a 路由零回归）

- [ ] **Step 7: 提交**

```bash
git add sidecar/csm_sidecar/routes/vault_atomize.py sidecar/csm_sidecar/main.py sidecar/tests/test_vault_atomize_routes.py
git commit -m "feat(3b): /api/vault/atomize 路由 + 注册（LLMConfigError→503 先于 ValueError）

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

# Unit C —— 前端 AI 拆条 tab

### Task C1：共享 payload helper + IntakeForm 改用（DRY）

**Files:** Create `frontend/src/components/materials/payload.ts`、`frontend/src/components/materials/__tests__/payload.spec.ts`；Modify `frontend/src/components/materials/IntakeForm.vue`

- [ ] **Step 1: 写 helper 测试**（`payload.spec.ts`）

```ts
import { describe, it, expect } from "vitest";
import { assembleFrontmatter, filenameError } from "@/components/materials/payload";

describe("payload helper", () => {
  it("核心关键词 拆成数组、空值丢弃", () => {
    expect(assembleFrontmatter({ 产品: "吸尘器", 核心关键词: "吸力, 续航" }))
      .toEqual({ 产品: "吸尘器", 核心关键词: ["吸力", "续航"] });
    expect(assembleFrontmatter({ 产品: "", 素材类型: "科普选购" }))
      .toEqual({ 素材类型: "科普选购" });
  });
  it("filenameError 规则", () => {
    expect(filenameError("a b.md")).toContain("空格");
    expect(filenameError("a/b.md")).toContain("空格");
    expect(filenameError("a.txt")).toContain(".md");
    expect(filenameError("a.md")).toBe("");
    expect(filenameError("")).toBe("");
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run（frontend）: `npx vitest run src/components/materials/__tests__/payload.spec.ts`
Expected: FAIL（找不到 payload 模块）

- [ ] **Step 3: 实现 payload.ts**

```ts
// 素材库录入/拆条共用的 payload 组装（DRY：IntakeForm 与 AtomCard 同源）。
export function assembleFrontmatter(fm: Record<string, string>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(fm)) {
    if (k === "核心关键词") out[k] = String(v).split(/[，,\s]+/).filter(Boolean);
    else if (v) out[k] = v;
  }
  return out;
}

export function filenameError(name: string): string {
  const v = (name || "").trim();
  if (!v) return "";
  if (/\s/.test(v) || v.includes("/") || v.includes("\\")) return "不能含空格/路径分隔符";
  if (!v.endsWith(".md")) return "须以 .md 结尾";
  return "";
}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `npx vitest run src/components/materials/__tests__/payload.spec.ts`
Expected: PASS（2 passed）

- [ ] **Step 5: IntakeForm 改用 helper**（`IntakeForm.vue`）

① import 行（第 5 行附近）下加：
```ts
import { assembleFrontmatter, filenameError as fnError } from "@/components/materials/payload";
```
② `buildPayload()` 里把手写的 frontmatter 循环：
```ts
  const frontmatter: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(fm)) {
    if (k === "核心关键词") frontmatter[k] = String(v).split(/[，,\s]+/).filter(Boolean);
    else if (v) frontmatter[k] = v;
  }
```
替换成：
```ts
  const frontmatter = assembleFrontmatter(fm);
```
③ `filenameError` computed：
```ts
const filenameError = computed(() => {
  const v = filename.value.trim();
  if (!v) return "";
  if (/\s/.test(v) || v.includes("/") || v.includes("\\")) return "不能含空格/路径分隔符";
  if (!v.endsWith(".md")) return "须以 .md 结尾";
  return "";
});
```
替换成：
```ts
const filenameError = computed(() => fnError(filename.value));
```

- [ ] **Step 6: 跑 IntakeForm 既有测试确认零回归**

Run: `npx vitest run src/components/materials/__tests__/IntakeForm.spec.ts`
Expected: PASS（3 passed，行为不变）

- [ ] **Step 7: 提交**

```bash
git add frontend/src/components/materials/payload.ts frontend/src/components/materials/__tests__/payload.spec.ts frontend/src/components/materials/IntakeForm.vue
git commit -m "refactor(3b): 抽 payload helper（assembleFrontmatter/filenameError），IntakeForm 改用

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

### Task C2：store 拆条动作

**Files:** Modify `frontend/src/stores/materials.ts`；Create `frontend/src/stores/__tests__/materials.atomize.spec.ts`

- [ ] **Step 1: 写 store 测试**（`materials.atomize.spec.ts`）

```ts
import { setActivePinia, createPinia } from "pinia";
import { describe, it, expect, vi, beforeEach } from "vitest";

const getMock = vi.fn();
const postMock = vi.fn();
vi.mock("@/stores/sidecar", () => ({
  useSidecar: () => ({ client: { get: getMock, post: postMock } }),
}));

import { useMaterials } from "@/stores/materials";

describe("materials store — AI 拆条", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    getMock.mockReset(); postMock.mockReset();
  });

  it("atomizeText 打 /atomize 返回 atoms", async () => {
    postMock.mockResolvedValueOnce({ data: { atoms: [
      { text: "看吸力", rel_folder: "a", material_type: "科普选购", product: "通用",
        keyword: "吸力", filename: "x.md", confidence: "high", warnings: [] }] } });
    const m = useMaterials();
    const atoms = await m.atomizeText("资料");
    expect(atoms.length).toBe(1);
    expect(atoms[0].confidence).toBe("high");
    expect(postMock).toHaveBeenCalledWith("/api/vault/atomize", { text: "资料" });
  });

  it("atomizeText 失败 → [] + intakeError", async () => {
    postMock.mockRejectedValueOnce({ response: { data: { detail: "未配置 provider" } } });
    const m = useMaterials();
    expect(await m.atomizeText("资料")).toEqual([]);
    expect(m.intakeError).toContain("provider");
  });

  it("commitAtom 返回 receipt", async () => {
    postMock.mockResolvedValueOnce({ data: { created_rel: "a/x.md", content_sha: "s" } });
    const m = useMaterials();
    const rc = await m.commitAtom({ rel_folder: "a", filename: "x.md", frontmatter: {}, body_shape: "variants", variants: ["y"] });
    expect(rc?.created_rel).toBe("a/x.md");
  });

  it("commitAtom 失败 → null + intakeError", async () => {
    postMock.mockRejectedValueOnce({ response: { data: { detail: "同名笔记已存在" } } });
    const m = useMaterials();
    expect(await m.commitAtom({ rel_folder: "a", filename: "x.md", frontmatter: {}, body_shape: "variants", variants: ["y"] })).toBeNull();
    expect(m.intakeError).toContain("同名");
  });

  it("undoAtom 打 /undo", async () => {
    postMock.mockResolvedValueOnce({ data: { undone: true, warnings: [] } });
    const m = useMaterials();
    await m.undoAtom({ created_rel: "a/x.md", content_sha: "s", index_rel: null, index_line: null });
    expect(postMock).toHaveBeenCalledWith("/api/vault/undo", expect.objectContaining({ created_rel: "a/x.md" }));
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `npx vitest run src/stores/__tests__/materials.atomize.spec.ts`
Expected: FAIL（`m.atomizeText is not a function`）

- [ ] **Step 3: 加 AtomDraft 接口 + 4 个动作**（`materials.ts`）

在 `NotePayload` 接口（第 56 行附近）后加：
```ts
export interface AtomDraft {
  text: string;
  rel_folder: string | null;
  material_type: string;
  product: string;
  keyword: string;
  filename: string;
  confidence: "high" | "med" | "low";
  warnings: string[];
}
```
在 `undoLast` 函数（第 138 行附近 `}` 之后、`return {` 之前）加 4 个动作（返回值型，不碰 currentPlan/lastReceipt 单槽位）：
```ts
  async function atomizeText(text: string): Promise<AtomDraft[]> {
    intakeError.value = null;
    try {
      const r = await useSidecar().client.post("/api/vault/atomize", { text });
      return r.data.atoms ?? [];
    } catch (e: any) {
      intakeError.value = errMsg(e); return [];
    }
  }

  async function commitAtom(payload: NotePayload): Promise<WriteReceipt | null> {
    try {
      const r = await useSidecar().client.post("/api/vault/commit", payload);
      return r.data;
    } catch (e: any) {
      intakeError.value = errMsg(e); return null;
    }
  }

  async function undoAtom(receipt: WriteReceipt): Promise<void> {
    try {
      await useSidecar().client.post("/api/vault/undo", receipt);
    } catch (e: any) {
      intakeError.value = errMsg(e);
    }
  }
```
在 `return { ... }` 里把 `loadFolders, planNote, commitNote, undoLast,` 一行改为：
```ts
    loadFolders, planNote, commitNote, undoLast,
    atomizeText, commitAtom, undoAtom,
```

- [ ] **Step 4: 跑测试确认通过**

Run: `npx vitest run src/stores/__tests__/materials.atomize.spec.ts`
Expected: PASS（5 passed）

- [ ] **Step 5: 提交**

```bash
git add frontend/src/stores/materials.ts frontend/src/stores/__tests__/materials.atomize.spec.ts
git commit -m "feat(3b): materials store 加拆条动作（atomizeText/commitAtom/undoAtom）

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

### Task C3：AtomCard.vue

**Files:** Create `frontend/src/components/materials/AtomCard.vue`、`frontend/src/components/materials/__tests__/AtomCard.spec.ts`

- [ ] **Step 1: 写卡测试**（`AtomCard.spec.ts`）

```ts
import { setActivePinia, createPinia } from "pinia";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { mount } from "@vue/test-utils";

const getMock = vi.fn();
const postMock = vi.fn();
vi.mock("@/stores/sidecar", () => ({
  useSidecar: () => ({ client: { get: getMock, post: postMock } }),
}));
vi.mock("@/composables/useNotifications", () => ({ useNotifications: () => ({ push: vi.fn() }) }));

import AtomCard from "@/components/materials/AtomCard.vue";

const FOLDERS = [
  { rel_folder: "科普模块/吸尘器/挑选攻略", frontmatter_keys: ["产品", "素材类型", "核心关键词"],
    defaults: { 产品: "吸尘器" }, body_shape: "variants", sample_count: 2, material_types: ["科普选购"] },
];

function atom(over: any = {}) {
  return { text: "看吸力", rel_folder: "科普模块/吸尘器/挑选攻略", material_type: "科普选购",
    product: "吸尘器", keyword: "吸力", filename: "吸力.md", confidence: "high", warnings: [], ...over };
}

describe("AtomCard", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    getMock.mockReset(); postMock.mockReset();
  });

  it("off-menu 原子显示 warning", () => {
    const w = mount(AtomCard, { props: { atom: atom({ rel_folder: null, warnings: ["建议文件夹「x」不在素材库中，请人工选择"] }), folders: FOLDERS } });
    expect(w.text()).toContain("不在素材库");
  });

  it("确认入库走 commitAtom，成功后出撤销", async () => {
    postMock.mockResolvedValue({ data: { created_rel: "科普模块/吸尘器/挑选攻略/吸力.md", content_sha: "s", index_rel: null, index_line: null } });
    const w = mount(AtomCard, { props: { atom: atom(), folders: FOLDERS } });
    await w.vm.$nextTick();
    await w.find("[data-atom-commit]").trigger("click");
    await new Promise((r) => setTimeout(r));
    expect(postMock).toHaveBeenCalledWith("/api/vault/commit", expect.objectContaining({
      rel_folder: "科普模块/吸尘器/挑选攻略", body_shape: "variants" }));
    expect(w.find("[data-atom-undo]").exists()).toBe(true);
  });

  it("commitAuto 跳过 low 置信度", async () => {
    const w = mount(AtomCard, { props: { atom: atom({ confidence: "low" }), folders: FOLDERS } });
    await w.vm.$nextTick();
    await (w.vm as any).commitAuto();
    expect(postMock).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `npx vitest run src/components/materials/__tests__/AtomCard.spec.ts`
Expected: FAIL（找不到 AtomCard）

- [ ] **Step 3: 实现 AtomCard.vue**

```vue
<script setup lang="ts">
import { reactive, ref, watch, computed } from "vue";
import { useMaterials, type AtomDraft, type FolderProfile, type NotePayload, type WriteReceipt } from "@/stores/materials";
import { useNotifications } from "@/composables/useNotifications";
import { assembleFrontmatter, filenameError } from "@/components/materials/payload";

const props = defineProps<{ atom: AtomDraft; folders: FolderProfile[] }>();
const m = useMaterials();
const notify = useNotifications();

const selectedRel = ref<string | null>(props.atom.rel_folder);
const fm = reactive<Record<string, string>>({});
const filename = ref(props.atom.filename);
const text = ref(props.atom.text);
const receipt = ref<WriteReceipt | null>(null);
const committing = ref(false);

function folderOf(rel: string | null): FolderProfile | null {
  return props.folders.find((f) => f.rel_folder === rel) ?? null;
}

function rebuildFm(rel: string | null): void {
  for (const k of Object.keys(fm)) delete fm[k];
  const f = folderOf(rel);
  if (!f) return;
  for (const k of f.frontmatter_keys) fm[k] = f.defaults[k] ?? "";
  if ("产品" in fm && props.atom.product) fm["产品"] = props.atom.product;
  if ("素材类型" in fm && props.atom.material_type) fm["素材类型"] = props.atom.material_type;
  if ("核心关键词" in fm && props.atom.keyword) fm["核心关键词"] = props.atom.keyword;
}
watch(selectedRel, (rel) => rebuildFm(rel), { immediate: true });

const fnErr = computed(() => filenameError(filename.value));
const confLabel = computed(() => ({ high: "高", med: "中", low: "低" }[props.atom.confidence]));

function buildPayload(): NotePayload | null {
  if (!selectedRel.value || fnErr.value) return null;
  const variants = [text.value].filter((t) => t.trim());
  if (!variants.length) return null;
  return { rel_folder: selectedRel.value, filename: filename.value.trim(),
    frontmatter: assembleFrontmatter(fm), body_shape: "variants", variants };
}

const canCommit = computed(() => !!buildPayload() && !receipt.value && !committing.value);

async function commit(): Promise<void> {
  const p = buildPayload();
  if (!p || receipt.value || committing.value) return;
  committing.value = true;
  try {
    const rc = await m.commitAtom(p);
    if (rc) { receipt.value = rc; notify.push(`已入库：${p.filename}`, { tone: "success" }); }
  } finally {
    committing.value = false;
  }
}

async function undo(): Promise<void> {
  if (!receipt.value) return;
  await m.undoAtom(receipt.value);
  receipt.value = null;
  notify.push("已撤销该条", { tone: "info" });
}

// 面板「全部入库」用：仅 high/med 且未入库才提交。
async function commitAuto(): Promise<void> {
  if (["high", "med"].includes(props.atom.confidence) && !receipt.value) await commit();
}
defineExpose({ commitAuto });
</script>

<template>
  <div data-atom-card :data-confidence="atom.confidence"
    class="flex flex-col gap-2 rounded-xl border p-3"
    :style="{ borderColor: atom.confidence === 'low' ? 'var(--amber, #d97706)' : 'rgba(0,0,0,0.1)',
              background: receipt ? 'rgba(16,185,129,0.06)' : 'transparent' }">
    <div class="flex items-center gap-2 text-xs">
      <span class="rounded-full px-2 py-0.5"
        :style="{ background: atom.confidence === 'low' ? 'rgba(217,119,6,0.15)' : 'rgba(0,0,0,0.06)' }">
        置信度 {{ confLabel }}
      </span>
      <span v-if="receipt" class="text-emerald-600">✓ 已入库</span>
    </div>

    <p v-for="w in atom.warnings" :key="w" class="text-xs text-amber-600">⚠ {{ w }}</p>

    <textarea v-model="text" rows="3" data-atom-text
      class="w-full rounded-lg border border-ink/15 px-2 py-1.5 text-sm" />

    <div class="flex flex-wrap gap-2">
      <select v-model="selectedRel" data-atom-folder
        class="rounded-lg border border-ink/15 px-2 py-1 text-xs">
        <option :value="null">— 选择文件夹 —</option>
        <option v-for="f in folders" :key="f.rel_folder" :value="f.rel_folder">{{ f.rel_folder }}</option>
      </select>
      <input v-model="filename" data-atom-filename placeholder="文件名.md"
        class="w-40 rounded-lg border border-ink/15 px-2 py-1 text-xs" />
    </div>
    <p v-if="fnErr" class="text-xs" :style="{ color: 'var(--red)' }">{{ fnErr }}</p>

    <div v-for="k in folderOf(selectedRel)?.frontmatter_keys || []" :key="k" class="flex items-center gap-2">
      <label class="w-16 shrink-0 text-xs text-ink/50">{{ k }}</label>
      <input v-model="fm[k]" :data-atom-fm="k"
        class="flex-1 rounded-lg border border-ink/15 px-2 py-1 text-xs" />
    </div>

    <div class="flex items-center gap-2 pt-1">
      <button data-atom-commit
        class="rounded-lg px-3 py-1 text-xs font-medium text-white disabled:opacity-40"
        :style="{ background: 'var(--primary)' }" :disabled="!canCommit" @click="commit">确认入库</button>
      <button v-if="receipt" data-atom-undo class="rounded-lg px-3 py-1 text-xs text-ink/70" @click="undo">撤销</button>
    </div>
  </div>
</template>
```

- [ ] **Step 4: 跑测试确认通过**

Run: `npx vitest run src/components/materials/__tests__/AtomCard.spec.ts`
Expected: PASS（3 passed）

- [ ] **Step 5: 提交**

```bash
git add frontend/src/components/materials/AtomCard.vue frontend/src/components/materials/__tests__/AtomCard.spec.ts
git commit -m "feat(3b): AtomCard 原子卡（逐条 commit/undo + commitAuto 跳过 low）

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

### Task C4：AtomizePanel.vue + MaterialsView tab

**Files:** Create `frontend/src/components/materials/AtomizePanel.vue`、`frontend/src/components/materials/__tests__/AtomizePanel.spec.ts`；Modify `frontend/src/views/MaterialsView.vue`

- [ ] **Step 1: 写面板测试**（`AtomizePanel.spec.ts`）

```ts
import { setActivePinia, createPinia } from "pinia";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { mount } from "@vue/test-utils";

const getMock = vi.fn();
const postMock = vi.fn();
vi.mock("@/stores/sidecar", () => ({
  useSidecar: () => ({ client: { get: getMock, post: postMock } }),
}));
vi.mock("@/composables/useNotifications", () => ({ useNotifications: () => ({ push: vi.fn() }) }));

import AtomizePanel from "@/components/materials/AtomizePanel.vue";

describe("AtomizePanel", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    getMock.mockReset(); postMock.mockReset();
    getMock.mockResolvedValue({ data: { folders: [] } });   // loadFolders
  });

  it("拆条渲染 N 卡且 low 置顶", async () => {
    postMock.mockResolvedValueOnce({ data: { atoms: [
      { text: "高条", rel_folder: null, material_type: "", product: "", keyword: "", filename: "a.md", confidence: "high", warnings: [] },
      { text: "低条", rel_folder: null, material_type: "", product: "", keyword: "", filename: "b.md", confidence: "low", warnings: [] },
    ] } });
    const w = mount(AtomizePanel);
    await new Promise((r) => setTimeout(r));
    await w.find("[data-atomize-input]").setValue("一些资料");
    await w.find("[data-atomize-run]").trigger("click");
    await new Promise((r) => setTimeout(r));
    const cards = w.findAll("[data-atom-card]");
    expect(cards.length).toBe(2);
    expect(cards[0].attributes("data-confidence")).toBe("low");   // low 置顶
  });

  it("空输入不调拆条", async () => {
    const w = mount(AtomizePanel);
    await new Promise((r) => setTimeout(r));
    await w.find("[data-atomize-run]").trigger("click");
    expect(postMock).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `npx vitest run src/components/materials/__tests__/AtomizePanel.spec.ts`
Expected: FAIL（找不到 AtomizePanel）

- [ ] **Step 3: 实现 AtomizePanel.vue**

```vue
<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useMaterials, type AtomDraft } from "@/stores/materials";
import { useNotifications } from "@/composables/useNotifications";
import Spinner from "@/components/ui/Spinner.vue";
import AtomCard from "@/components/materials/AtomCard.vue";

const m = useMaterials();
const notify = useNotifications();
const text = ref("");
const atoms = ref<AtomDraft[]>([]);
const atomizing = ref(false);
const cards = ref<any[]>([]);

onMounted(() => m.loadFolders());

const ORDER: Record<string, number> = { low: 0, med: 1, high: 2 };

async function run(): Promise<void> {
  if (!text.value.trim() || atomizing.value) return;
  atomizing.value = true; atoms.value = []; cards.value = [];
  try {
    const a = await m.atomizeText(text.value);
    a.sort((x, y) => ORDER[x.confidence] - ORDER[y.confidence]);   // low 置顶
    atoms.value = a;
  } finally {
    atomizing.value = false;
  }
}

async function commitAll(): Promise<void> {
  let n = 0;
  for (const c of cards.value) {
    if (c?.commitAuto) { await c.commitAuto(); n++; }
  }
  notify.push(`已尝试入库 ${n} 条（low 置信度需逐条确认）`, { tone: "info" });
}
</script>

<template>
  <div class="flex h-full min-h-0 gap-4">
    <!-- 左：粘贴 + 拆条 -->
    <div class="flex w-96 min-w-0 flex-col gap-2">
      <label class="text-xs text-ink/50">粘贴一篇家电营销资料，AI 忠实拆条 + 归类</label>
      <textarea v-model="text" data-atomize-input rows="12" placeholder="把文章/资料整段贴这里…"
        class="w-full flex-1 rounded-lg border border-ink/15 px-2 py-1.5 text-sm" />
      <div class="flex items-center gap-2">
        <button data-atomize-run
          class="rounded-lg px-3 py-1.5 text-sm font-medium text-white disabled:opacity-40"
          :style="{ background: 'var(--primary)' }" :disabled="!text.trim() || atomizing" @click="run">
          <span v-if="atomizing" class="inline-flex items-center gap-1"><Spinner :size="12" /> 拆条中…</span>
          <span v-else>AI 拆条</span>
        </button>
        <button v-if="atoms.length" class="rounded-lg border border-ink/15 px-3 py-1.5 text-sm text-ink/70" @click="commitAll">
          全部入库（high/med）
        </button>
      </div>
      <p v-if="m.intakeError" class="text-xs" :style="{ color: 'var(--red)' }">{{ m.intakeError }}</p>
    </div>

    <!-- 右：原子卡列表 -->
    <div class="flex min-w-0 flex-1 flex-col gap-3 overflow-y-auto">
      <div v-if="!atoms.length && !atomizing" class="grid h-full place-items-center text-sm text-ink/40">
        拆条结果会出现在这里（低置信度置顶，请重点核对）
      </div>
      <AtomCard v-for="(a, i) in atoms" :key="i" :ref="(el) => (cards[i] = el)"
        :atom="a" :folders="m.writableFolders" />
    </div>
  </div>
</template>
```

- [ ] **Step 4: MaterialsView 加第 3 tab**（`MaterialsView.vue`）

① import（第 7 行 `import IntakeForm` 后）加：
```ts
import AtomizePanel from "@/components/materials/AtomizePanel.vue";
```
② tab 类型（第 10 行）：
```ts
const tab = ref<"models" | "intake">("models");
```
改为：
```ts
const tab = ref<"models" | "intake" | "atomize">("models");
```
③ tab 按钮区——把「浏览（建设中）」那行（第 37 行）**前面**插入「AI 拆条」按钮：
```vue
        <button :data-tab="'atomize'" class="rounded-full px-3 py-1 font-medium"
          :style="{ background: tab === 'atomize' ? 'var(--ink)' : 'transparent', color: tab === 'atomize' ? '#fff' : 'inherit' }"
          @click="tab = 'atomize'">AI 拆条</button>
```
④ 内容区——把 `<IntakeForm v-else-if="tab === 'intake'" />`（第 162 行）改为：
```vue
    <IntakeForm v-else-if="tab === 'intake'" />
    <AtomizePanel v-else-if="tab === 'atomize'" />
```

- [ ] **Step 5: 跑面板测试 + 全前端套件**

Run: `npx vitest run src/components/materials/__tests__/AtomizePanel.spec.ts`
Expected: PASS（2 passed）
Run: `npx vitest run`
Expected: 全 PASS（含 3a 既有 + 新增，零回归）

- [ ] **Step 6: vue-tsc 类型检查（强制）**

Run: `npx vue-tsc -b`
Expected: exit 0，无类型错误
> 注意：`vue-tsc -b` 可能 emit `vite.config.js`/`.d.ts` 触发 vite restart；跑完 `git checkout -- vite.config.js *.d.ts 2>$null` 还原（若有改动）。

- [ ] **Step 7: 提交**

```bash
git add frontend/src/components/materials/AtomizePanel.vue frontend/src/components/materials/__tests__/AtomizePanel.spec.ts frontend/src/views/MaterialsView.vue
git commit -m "feat(3b): AtomizePanel 拆条面板 + MaterialsView「AI 拆条」tab

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## 收尾（最终综合审查后）

- [ ] 全后端：`... -m pytest tests/core/vault sidecar/tests/test_atomize_service.py sidecar/tests/test_vault_atomize_routes.py sidecar/tests/test_vault_writer_routes.py -v`
- [ ] 全前端：`npx vitest run` + `npx vue-tsc -b`（exit 0）
- [ ] 最终综合审查（superpowers:requesting-code-review）→ SHIP
- [ ] 推分支 `claude/ai-atomize` + `gh pr create`（中文 PR 体 + `🤖 Generated with [Claude Code]` trailer）→ 停在 pending 等 merge
- [ ] 等 CI 绿（Frontend：vue-tsc + vite + vitest）
- [ ] 更新项目记忆 `project_csm_creation_studio_upgrade.md`

## DRY / YAGNI / 非目标 守则（实现时）

- 写入引擎、`/api/vault/{plan,commit,undo}` 零改动；只新增 atomize。
- frontmatter 组装 + 文件名校验唯一源在 `payload.ts`（IntakeForm 与 AtomCard 共用）。
- 不改写正文（单变体①）、不自动建文件夹、不分块、不拆参数表、不做阈值门禁、不持久化拆条会话。
- 中文 commit message；commit trailer `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`。
