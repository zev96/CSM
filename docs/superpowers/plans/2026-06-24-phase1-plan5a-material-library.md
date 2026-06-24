# Phase 1 — Plan 5a：素材库入口 + 品牌型号 tab（只读）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 立「素材库」一级导航入口 + 只读「品牌型号」tab——浏览 vault 里每个 (品牌, 型号) 的结构化记忆（参数/认证/话术/背书/介绍/测试 + 缺口体检 + **注入预览**），背后新增只读 `brand-memory` API。建立用户对「生成时会喂给 LLM 什么事实」的信任。

**Architecture:** 后端新增 `brand_memory_service` + `routes/brand_memory.py`（镜像 `skills_service`/`routes/skills.py`），复用 Plan 1 `resolve_memory` + Plan 3 `render_brand_facts` 做注入预览，**纯只读、零改既有生成链**。前端新增 `素材库` nav 项 + `MaterialsView`（SplitPane 左列表右详情，镜像 `ZhihuMonitorModule`）+ `materials` store（镜像 `templates.ts`）。全部硬编码中文（代码库无 i18n）。

**Tech Stack:** Python/FastAPI/pytest（后端）；Vue 3 setup + Pinia + axios + Vitest + vue-tsc（前端）。

参考 spec：[Phase 1 §6](../specs/2026-06-23-phase1-brand-model-memory-design.md)、[路线图 §1.1](../specs/2026-06-23-creation-studio-upgrade-roadmap-design.md)。

---

## 关键设计决定（执行前已与用户确认 2026-06-24）

1. **Plan 5 拆 2 PR**：**本文档 = 5a**（brand-memory API + 素材库入口 + 品牌型号 tab）；**5b**（`SkillEditView` role 下拉 + ArticleView factcheck 审查面板）合并 5a 后另出。
2. **硬编码中文**：代码库**无任何 i18n**（grep 零命中 `vue-i18n`/`useI18n`/`$t`/`locales`），全部页面硬编码中文。本页同样硬编码中文，**不引入 vue-i18n**（那是跨几十个组件的大重构，不属本 plan）。记忆里「中英双语硬约定」已过时、需修正。
3. **品牌型号 tab 只读**：specs/认证/话术条数/背书/介绍/测试/缺口体检/注入预览全只读。**新建/编辑 = Phase 3 写入器**，本期不做。
4. **注入预览 = `render_brand_facts([scope])` 全量（按配置 cap）**：诚实展示「该型号生成时会注入的事实块（受 token cap）」；「选维度过滤预览」留未来。
5. **列表 coverage 复用同一次 `scan_vault`**：`list_models` 一次 `scan_vault` + `build_brand_registry`，再对每个型号 `resolve_memory(复用 index)` 取 coverage——避免 N 次全量重扫。
6. **路由用 full-stem 单参 `{model}`**（如 `CEWEYDS18`，registry 约定）而非 spec 的 `{品牌}/{型号}`——full-stem 唯一、brand 可由 `registry.brand_of` 反查，更简洁。
7. **前端验证 = Vitest + vue-tsc**；端到端交互（点列表、看详情）= **用户手动**（dev 服务在 agent 环境起不稳，见记忆）。镜像：service/route→`skills_service`；view→`ZhihuMonitorModule` 的 SplitPane；store→`templates.ts`。

---

## File Structure

**后端（Unit A）**
- Create `sidecar/csm_sidecar/services/brand_memory_service.py` — `list_models` + `get_model_detail`（含注入预览）。
- Create `sidecar/csm_sidecar/routes/brand_memory.py` — `GET /api/brand-memory`、`GET /api/brand-memory/{model}`。
- Modify `sidecar/csm_sidecar/main.py` — 注册 router。
- Test (Create) `sidecar/tests/test_brand_memory_routes.py` — tmp vault 夹具 + 列表/详情/404/400。

**前端（Unit B/C）**
- Modify `frontend/src/components/LeftNav.vue` — NAV_TOP 加 `素材库`。
- Modify `frontend/src/router/index.ts` — 加 `materials` 路由。
- Create `frontend/src/stores/materials.ts` — list/select store。
- Create `frontend/src/views/MaterialsView.vue` — 品牌型号 tab（SplitPane 列表+详情+注入预览）。
- Test (Create) `frontend/src/stores/__tests__/materials.spec.ts` + `frontend/src/views/__tests__/MaterialsView.spec.ts`。

---

# Unit A：brand-memory 只读 API（后端）

> 完全可 pytest 验证。先做（前端依赖它）。**测试调用见文末「测试调用」——sidecar 测试必须设 PYTHONPATH。**

### Task A1: `brand_memory_service`（list + detail + 注入预览）

**Files:**
- Create: `sidecar/csm_sidecar/services/brand_memory_service.py`
- Test: `sidecar/tests/test_brand_memory_service.py`

- [ ] **Step 1: 写失败测试**（tmp vault 夹具，照搬 Plan 1 resolver 测试结构）

`sidecar/tests/test_brand_memory_service.py`:
```python
from pathlib import Path

from csm_sidecar.services import brand_memory_service as svc

VAULT = "营销资料库/产品模块/吸尘器"


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
       "① 220AW强劲吸力。\n\n② 12万转高速电机。\n")
    _w(root / VAULT / "希喂推荐内容/品牌背书/吸尘器-CEWEY品牌背书-品牌定位①.md",
       "---\n产品: 吸尘器\n素材类型: 品牌定位\n核心关键词: x\n---\n① CEWEY 技术型品牌。\n")


def test_list_models_includes_role_and_coverage(tmp_path):
    _vault(tmp_path)
    rows = svc.list_models(tmp_path, category="吸尘器", own_brands={"CEWEY"})
    by_model = {r["model"]: r for r in rows}
    assert by_model["CEWEYDS18"]["brand"] == "CEWEY"
    assert by_model["CEWEYDS18"]["role"] == "主推"
    assert by_model["CEWEYDS18"]["coverage"]["has_specs"] is True
    assert by_model["戴森V12"]["role"] == "竞品"


def test_get_model_detail_has_specs_and_inject_preview(tmp_path):
    _vault(tmp_path)
    d = svc.get_model_detail(
        tmp_path, "CEWEYDS18", category="吸尘器", own_brands={"CEWEY"},
        variant_cap=3, endorsement_cap=5)
    assert d is not None
    assert d["model_full"] == "CEWEYDS18"
    assert d["specs"]["吸力(AW)"]["numbers"] == [220.0]
    assert "CE" in d["certs"]
    # 注入预览 = render_brand_facts，应含参数原文 + 话术
    assert "220" in d["inject_preview"]
    assert "技术型品牌" in d["inject_preview"]


def test_get_model_detail_unknown_returns_none(tmp_path):
    _vault(tmp_path)
    assert svc.get_model_detail(
        tmp_path, "杂牌X9", category="吸尘器", own_brands={"CEWEY"},
        variant_cap=3, endorsement_cap=5) is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest sidecar/tests/test_brand_memory_service.py -v`
Expected: FAIL — `ModuleNotFoundError: csm_sidecar.services.brand_memory_service`

- [ ] **Step 3: 写实现**

`sidecar/csm_sidecar/services/brand_memory_service.py`:
```python
"""Read-only brand/model memory API service (Phase 1 Plan 5a).

镜像 skills_service 的只读约定。复用 Plan 1 resolver + Plan 3 render_brand_facts，
零改既有生成链。列表一次 scan_vault + build_brand_registry，对每型号
resolve_memory(复用 index) 取 coverage；详情额外渲染注入预览。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from csm_core.brand_memory.identity import parse_brand_model
from csm_core.brand_memory.inject import ModelScope, render_brand_facts
from csm_core.brand_memory.model import BrandModelMemory
from csm_core.brand_memory.resolver import resolve_memory
from csm_core.vault.brand_registry import BrandRegistry, build_brand_registry
from csm_core.vault.scanner import VaultIndex, scan_vault


def _resolve_one(
    model_full: str, registry: BrandRegistry, index: VaultIndex,
    category: str, own_brands: set[str],
) -> tuple[str | None, BrandModelMemory] | None:
    brand = registry.brand_of(model_full)
    if brand is None:
        return None
    # registry 存 full-stem（CEWEYDS18）；resolver 期望品牌剥离（DS18）。
    parsed = parse_brand_model(model_full)
    resolver_model = parsed[1] if parsed is not None else model_full
    mem = resolve_memory(brand, resolver_model, category, index, own_brands=own_brands)
    return brand, mem


def list_models(
    vault_root: Path, *, category: str, own_brands: set[str],
) -> list[dict[str, Any]]:
    """全 (品牌, 型号) + role + 缺口体检（一次 scan，复用 index）。"""
    index = scan_vault(vault_root)
    registry = build_brand_registry(vault_root)
    out: list[dict[str, Any]] = []
    for model_full in registry.all_models():
        resolved = _resolve_one(model_full, registry, index, category, own_brands)
        if resolved is None:
            continue
        brand, mem = resolved
        out.append({
            "model": model_full,
            "brand": brand,
            "role": mem.role,            # 主推 | 竞品
            "coverage": mem.coverage,
        })
    return out


def get_model_detail(
    vault_root: Path, model_full: str, *,
    category: str, own_brands: set[str],
    variant_cap: int, endorsement_cap: int,
) -> dict[str, Any] | None:
    """单型号完整记忆 + 注入预览；registry 不识别 → None（路由转 404）。"""
    index = scan_vault(vault_root)
    registry = build_brand_registry(vault_root)
    resolved = _resolve_one(model_full, registry, index, category, own_brands)
    if resolved is None:
        return None
    brand, mem = resolved
    scope = ModelScope(brand=brand, model=model_full, role=mem.role, memory=mem)
    preview = render_brand_facts(
        [scope], variant_cap=variant_cap, endorsement_cap=endorsement_cap)
    d = mem.model_dump()
    d["model_full"] = model_full
    d["inject_preview"] = preview
    return d
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest sidecar/tests/test_brand_memory_service.py -v`
Expected: PASS（3 passed）

- [ ] **Step 5: 提交**

```bash
git add sidecar/csm_sidecar/services/brand_memory_service.py sidecar/tests/test_brand_memory_service.py
git commit -m "feat(brand_memory): 只读 service — list_models + get_model_detail（注入预览）"
```

---

### Task A2: `routes/brand_memory.py` + 注册 + 路由测试

**Files:**
- Create: `sidecar/csm_sidecar/routes/brand_memory.py`
- Modify: `sidecar/csm_sidecar/main.py`
- Test: `sidecar/tests/test_brand_memory_routes.py`

- [ ] **Step 1: 写失败测试**（用既有 `client` fixture，先读 `test_skills_routes.py` 确认 fixture 名 + 配 config 的写法照搬）

`sidecar/tests/test_brand_memory_routes.py`:
```python
from pathlib import Path

from fastapi.testclient import TestClient

VAULT = "营销资料库/产品模块/吸尘器"


def _w(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text.strip() + "\n", encoding="utf-8")


def _vault(root: Path) -> None:
    _w(root / VAULT / "产品参数/CEWEYDS18-产品参数.md",
       "---\n产品: 吸尘器\n素材类型: 产品参数\n核心关键词: x\n---\n"
       "## 性能参数\n\n| 参数 | 数值 |\n|--|--|\n| 吸力(AW) | 220 |\n\n"
       "## 基础信息\n\n| 参数 | 数值 |\n|--|--|\n| 认证检测 | CE、FCC |\n")
    _w(root / VAULT / "希喂推荐内容/核心技术/吸尘器-CEWEY核心技术-动力系统①.md",
       "---\n产品: 吸尘器\n素材类型: 动力系统\n核心关键词: x\n---\n① 220AW强劲吸力。\n")


def test_list_returns_models(client: TestClient, tmp_path):
    _vault(tmp_path)
    client.patch("/api/config", json={"vault_root": str(tmp_path)})
    r = client.get("/api/brand-memory")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] >= 1
    cewey = next(m for m in body["models"] if m["model"] == "CEWEYDS18")
    assert cewey["role"] == "主推"
    assert cewey["coverage"]["has_specs"] is True


def test_detail_returns_memory_and_preview(client: TestClient, tmp_path):
    _vault(tmp_path)
    client.patch("/api/config", json={"vault_root": str(tmp_path)})
    r = client.get("/api/brand-memory/CEWEYDS18")
    assert r.status_code == 200
    d = r.json()
    assert d["specs"]["吸力(AW)"]["numbers"] == [220.0]
    assert "220" in d["inject_preview"]


def test_detail_unknown_404(client: TestClient, tmp_path):
    _vault(tmp_path)
    client.patch("/api/config", json={"vault_root": str(tmp_path)})
    assert client.get("/api/brand-memory/杂牌X9").status_code == 404


def test_list_without_vault_root_400(client: TestClient, tmp_path):
    client.patch("/api/config", json={"vault_root": ""})
    assert client.get("/api/brand-memory").status_code == 400
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest sidecar/tests/test_brand_memory_routes.py -v`
Expected: FAIL — 404 (路由未注册)

- [ ] **Step 3: 写实现**

`sidecar/csm_sidecar/routes/brand_memory.py`:
```python
"""Read-only brand/model memory routes (Phase 1 Plan 5a)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, status

from ..auth import RequireToken
from ..services import brand_memory_service, config_service

router = APIRouter(tags=["brand_memory"], dependencies=[RequireToken])


def _cfg_or_400():
    cfg = config_service.load()
    if not cfg.vault_root:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="vault_root 未配置 — 请先在「设置」里指定素材库路径",
        )
    return cfg


@router.get("/api/brand-memory")
def list_brand_memory() -> dict[str, Any]:
    cfg = _cfg_or_400()
    models = brand_memory_service.list_models(
        Path(cfg.vault_root),
        category=cfg.user_product or "吸尘器",
        own_brands=set(cfg.brand_memory.own_brands),
    )
    return {"count": len(models), "models": models}


@router.get("/api/brand-memory/{model}")
def get_brand_memory(model: str) -> dict[str, Any]:
    cfg = _cfg_or_400()
    detail = brand_memory_service.get_model_detail(
        Path(cfg.vault_root), model,
        category=cfg.user_product or "吸尘器",
        own_brands=set(cfg.brand_memory.own_brands),
        variant_cap=cfg.brand_memory.inject_variant_cap,
        endorsement_cap=cfg.brand_memory.inject_endorsement_cap,
    )
    if detail is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"型号未找到: {model}")
    return detail
```

`main.py`：照其它 `from .routes import ... as ..._routes` + `app.include_router(...)` 的写法加一行（**先读 main.py 确认 import 块与 include_router 块位置**）：
```python
from .routes import brand_memory as brand_memory_routes
# ...
app.include_router(brand_memory_routes.router)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest sidecar/tests/test_brand_memory_routes.py -v`
Expected: PASS（4 passed）

- [ ] **Step 5: 提交**

```bash
git add sidecar/csm_sidecar/routes/brand_memory.py sidecar/csm_sidecar/main.py sidecar/tests/test_brand_memory_routes.py
git commit -m "feat(brand_memory): GET /api/brand-memory 列表 + /{model} 详情路由"
```

---

# Unit B：素材库 nav + 路由 + store（前端）

> 前端用 **Vitest + vue-tsc** 验证。测试调用：`cd frontend; npx vitest run <file>` 与 `npx vue-tsc --noEmit`（vue-tsc 会 emit vite.config.js 触发 vite restart → 跑完 `git checkout -- vite.config.js` 还原，见记忆）。

### Task B1: nav 入口 + 路由 + 占位 view

**Files:**
- Modify: `frontend/src/components/LeftNav.vue`
- Modify: `frontend/src/router/index.ts`
- Create: `frontend/src/views/MaterialsView.vue`（占位，Unit C 充实）

- [ ] **Step 1: 加 nav 项**（`LeftNav.vue` NAV_TOP，放 `templates` 之后、`xhs` 之前；图标 `stack` 已存在于 Icon.vue，区别于 模板库 的 `library`）

```typescript
const NAV_TOP = [
  { key: "home", icon: "home", label: "工作台" },
  { key: "article", icon: "edit", label: "创作区" },
  { key: "monitor", icon: "radar", label: "监测中心" },
  { key: "data-center", icon: "fileText", label: "数据中心" },
  { key: "mining", icon: "search", label: "引流" },
  { key: "templates", icon: "library", label: "模板库" },
  { key: "materials", icon: "stack", label: "素材库" },
  { key: "xhs", icon: "notebook", label: "小红书" },
] as const;
```

- [ ] **Step 2: 加路由**（`router/index.ts`，照既有 top-level lazy 路由写法；name **必须**为 `materials`，LeftNav `go(key)` 走 `router.push({name:key})`）

```typescript
{
  path: "/materials",
  name: "materials",
  component: () => import("@/views/MaterialsView.vue"),
  meta: { label: "素材库" },
},
```

- [ ] **Step 3: 占位 view**（Unit C 充实）

`frontend/src/views/MaterialsView.vue`:
```vue
<script setup lang="ts">
// 品牌型号 tab（Unit C 充实）
</script>

<template>
  <div class="p-6 text-sm text-ink/60">素材库 · 品牌型号（建设中）</div>
</template>
```

- [ ] **Step 4: 类型检查 + 构建不破**

Run: `cd frontend; npx vue-tsc --noEmit`（跑完 `git checkout -- vite.config.js 2>$null`）
Expected: 无新增类型错误。

- [ ] **Step 5: 提交**

```bash
git add frontend/src/components/LeftNav.vue frontend/src/router/index.ts frontend/src/views/MaterialsView.vue
git commit -m "feat(materials): 素材库 nav 入口 + /materials 路由 + 占位 view"
```

---

### Task B2: `materials` store + 单测

**Files:**
- Create: `frontend/src/stores/materials.ts`
- Test: `frontend/src/stores/__tests__/materials.spec.ts`

- [ ] **Step 1: 写失败测试**（mock sidecar client）

`frontend/src/stores/__tests__/materials.spec.ts`:
```typescript
import { setActivePinia, createPinia } from "pinia";
import { describe, it, expect, vi, beforeEach } from "vitest";

const getMock = vi.fn();
vi.mock("@/stores/sidecar", () => ({
  useSidecar: () => ({ client: { get: getMock } }),
}));

import { useMaterials } from "@/stores/materials";

describe("materials store", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    getMock.mockReset();
  });

  it("list() 填充 models", async () => {
    getMock.mockResolvedValueOnce({ data: { count: 1, models: [
      { model: "CEWEYDS18", brand: "CEWEY", role: "主推", coverage: { has_specs: true } },
    ] } });
    const s = useMaterials();
    await s.list();
    expect(s.models).toHaveLength(1);
    expect(s.models[0].model).toBe("CEWEYDS18");
    expect(s.loading).toBe(false);
  });

  it("select() 拉详情 + 设 selectedModel", async () => {
    getMock.mockResolvedValueOnce({ data: { model_full: "CEWEYDS18", specs: {}, inject_preview: "x" } });
    const s = useMaterials();
    await s.select("CEWEYDS18");
    expect(s.selectedModel).toBe("CEWEYDS18");
    expect(s.detail?.model_full).toBe("CEWEYDS18");
  });

  it("list() 失败设 error 不抛", async () => {
    getMock.mockRejectedValueOnce({ response: { data: { detail: "boom" } } });
    const s = useMaterials();
    await s.list();
    expect(s.error).toBe("boom");
    expect(s.models).toEqual([]);
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend; npx vitest run src/stores/__tests__/materials.spec.ts`
Expected: FAIL — 找不到 `@/stores/materials`

- [ ] **Step 3: 写实现**

`frontend/src/stores/materials.ts`:
```typescript
import { defineStore } from "pinia";
import { ref } from "vue";
import { useSidecar } from "@/stores/sidecar";

export interface Coverage {
  has_specs?: boolean;
  has_tests?: boolean;
  script_dimensions?: number;
  empty_spec_fields?: string[];
  [k: string]: unknown;
}
export interface BrandModelRow {
  model: string;       // full-stem，如 CEWEYDS18
  brand: string;
  role: string;        // 主推 | 竞品
  coverage: Coverage;
}
export interface SpecValue {
  field: string; raw: string; numbers: number[]; unit: string;
  is_approx: boolean; is_placeholder: boolean;
}
export interface ModelDetail {
  brand: string; model: string; model_full: string; category: string; role: string;
  specs: Record<string, SpecValue>;
  certs: string[];
  scripts: Record<string, string[]>;
  endorsements: string[];
  intro: string[];
  tests: Record<string, string>;
  coverage: Coverage;
  inject_preview: string;
}

function errMsg(e: any): string {
  return e?.response?.data?.detail ?? e?.message ?? String(e);
}

export const useMaterials = defineStore("materials", () => {
  const models = ref<BrandModelRow[]>([]);
  const loading = ref(false);
  const error = ref<string | null>(null);
  const selectedModel = ref<string | null>(null);
  const detail = ref<ModelDetail | null>(null);
  const detailLoading = ref(false);

  async function list(): Promise<void> {
    loading.value = true; error.value = null;
    try {
      const r = await useSidecar().client.get("/api/brand-memory");
      models.value = r.data.models ?? [];
    } catch (e: any) {
      error.value = errMsg(e); models.value = [];
    } finally { loading.value = false; }
  }

  async function select(model: string): Promise<void> {
    selectedModel.value = model;
    detail.value = null; detailLoading.value = true; error.value = null;
    try {
      const r = await useSidecar().client.get(
        `/api/brand-memory/${encodeURIComponent(model)}`);
      detail.value = r.data;
    } catch (e: any) {
      error.value = errMsg(e);
    } finally { detailLoading.value = false; }
  }

  return { models, loading, error, selectedModel, detail, detailLoading, list, select };
});
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd frontend; npx vitest run src/stores/__tests__/materials.spec.ts`
Expected: PASS（3 passed）

- [ ] **Step 5: 提交**

```bash
git add frontend/src/stores/materials.ts frontend/src/stores/__tests__/materials.spec.ts
git commit -m "feat(materials): materials store（list/select + 类型）+ 单测"
```

---

# Unit C：MaterialsView 品牌型号 tab（前端）

### Task C1: SplitPane 列表 + 详情 + 注入预览

**Files:**
- Modify: `frontend/src/views/MaterialsView.vue`
- Test: `frontend/src/views/__tests__/MaterialsView.spec.ts`

- [ ] **Step 1: 写失败测试**（mock materials store，验渲染 + 分组 + 选择 + 详情/空态）

`frontend/src/views/__tests__/MaterialsView.spec.ts`:
```typescript
import { mount } from "@vue/test-utils";
import { describe, it, expect, vi } from "vitest";

const listMock = vi.fn();
const selectMock = vi.fn();
const state: any = {
  models: [
    { model: "CEWEYDS18", brand: "CEWEY", role: "主推", coverage: { has_specs: true, has_tests: false, script_dimensions: 2 } },
    { model: "戴森V12", brand: "戴森", role: "竞品", coverage: { has_specs: true } },
  ],
  loading: false, error: null, selectedModel: null, detail: null, detailLoading: false,
  list: listMock, select: selectMock,
};
vi.mock("@/stores/materials", () => ({ useMaterials: () => state }));

import MaterialsView from "@/views/MaterialsView.vue";

describe("MaterialsView", () => {
  it("挂载即拉列表 + 渲染主推/竞品分组行", () => {
    const w = mount(MaterialsView);
    expect(listMock).toHaveBeenCalled();
    expect(w.text()).toContain("CEWEYDS18");
    expect(w.text()).toContain("戴森V12");
    expect(w.text()).toContain("主推");
    expect(w.text()).toContain("竞品");
  });

  it("点型号行调 select(model)", async () => {
    const w = mount(MaterialsView);
    await w.find("[data-model='CEWEYDS18']").trigger("click");
    expect(selectMock).toHaveBeenCalledWith("CEWEYDS18");
  });

  it("无选中显示空态提示", () => {
    const w = mount(MaterialsView);
    expect(w.text()).toContain("选择左侧型号");
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend; npx vitest run src/views/__tests__/MaterialsView.spec.ts`
Expected: FAIL — 占位 view 无这些内容。

- [ ] **Step 3: 写实现**（SplitPane 镜像 `ZhihuMonitorModule`；行 hover 用 inline-style；grid item `min-w-0`；只读）

`frontend/src/views/MaterialsView.vue`:
```vue
<script setup lang="ts">
import { computed, onMounted } from "vue";
import SplitPane from "@/components/ui/SplitPane.vue";
import Spinner from "@/components/ui/Spinner.vue";
import Pill from "@/components/ui/Pill.vue";
import { useMaterials, type BrandModelRow } from "@/stores/materials";

const m = useMaterials();
onMounted(() => m.list());

const hero = computed(() => m.models.filter((r) => r.role === "主推"));
const rivals = computed(() => m.models.filter((r) => r.role !== "主推"));

function gaps(r: BrandModelRow): string[] {
  const c = r.coverage || {};
  const out: string[] = [];
  if (!c.has_specs) out.push("缺参数");
  if (!c.has_tests) out.push("缺测试");
  if (!c.script_dimensions) out.push("缺话术");
  return out;
}
</script>

<template>
  <div class="h-full min-h-0 p-5">
    <div class="mb-4 flex items-baseline gap-3">
      <h1 class="text-lg font-semibold">素材库</h1>
      <div class="flex gap-2 text-sm">
        <span class="rounded-full bg-ink/10 px-3 py-1 font-medium">品牌型号</span>
        <span class="px-3 py-1 text-ink/35">浏览（建设中）</span>
        <span class="px-3 py-1 text-ink/35">录入（建设中）</span>
      </div>
    </div>

    <SplitPane leftWidth="300px" gap="18px">
      <template #left>
        <div class="flex h-full min-h-0 min-w-0 flex-col overflow-y-auto">
          <div v-if="m.loading" class="flex items-center gap-2 p-3 text-sm text-ink/50">
            <Spinner :size="14" /> 加载中…
          </div>
          <div v-else-if="m.error" class="p-3 text-sm text-red-600">加载失败：{{ m.error }}</div>
          <div v-else-if="!m.models.length" class="p-3 text-sm text-ink/50">
            素材库无产品参数笔记。请在「设置」确认素材库路径。
          </div>
          <template v-else>
            <template v-for="(group, gi) in [
              { label: '主推', rows: hero },
              { label: '竞品', rows: rivals },
            ]" :key="gi">
              <div v-if="group.rows.length" class="px-2 pb-1 pt-3 text-[11px] font-semibold uppercase tracking-wide text-ink/40">
                {{ group.label }}（{{ group.rows.length }}）
              </div>
              <button
                v-for="r in group.rows"
                :key="r.model"
                :data-model="r.model"
                class="flex flex-col gap-1 rounded-lg px-2 py-2 text-left transition-colors"
                :style="{ background: m.selectedModel === r.model ? 'var(--card-2, rgba(0,0,0,0.05))' : 'transparent' }"
                @click="m.select(r.model)"
              >
                <div class="flex items-center gap-2 text-sm font-medium">
                  <span>{{ r.brand }} · {{ r.model }}</span>
                </div>
                <div class="flex flex-wrap gap-1">
                  <Pill v-for="g in gaps(r)" :key="g" class="text-[10px]">{{ g }}</Pill>
                </div>
              </button>
            </template>
          </template>
        </div>
      </template>

      <template #right>
        <div class="h-full min-h-0 min-w-0 overflow-y-auto">
          <div v-if="m.detailLoading" class="flex items-center gap-2 p-4 text-sm text-ink/50">
            <Spinner :size="14" /> 加载详情…
          </div>
          <div v-else-if="!m.detail" class="grid h-full place-items-center text-sm text-ink/40">
            选择左侧型号查看记忆详情
          </div>
          <div v-else class="flex flex-col gap-5 p-1">
            <header class="flex items-center gap-3">
              <h2 class="text-base font-semibold">{{ m.detail.brand }} · {{ m.detail.model_full }}</h2>
              <span class="rounded-full bg-ink/10 px-2 py-0.5 text-xs">{{ m.detail.role }}</span>
            </header>

            <section v-if="Object.keys(m.detail.specs).length">
              <h3 class="mb-2 text-sm font-semibold">参数</h3>
              <table class="w-full text-sm">
                <tbody>
                  <tr v-for="(sv, field) in m.detail.specs" :key="field" class="border-b border-ink/5">
                    <td class="py-1 pr-3 text-ink/60">{{ field }}</td>
                    <td class="py-1" :class="sv.is_placeholder ? 'text-ink/30' : ''">{{ sv.raw }}</td>
                  </tr>
                </tbody>
              </table>
            </section>

            <section v-if="m.detail.certs.length">
              <h3 class="mb-2 text-sm font-semibold">认证</h3>
              <div class="flex flex-wrap gap-1">
                <Pill v-for="c in m.detail.certs" :key="c">{{ c }}</Pill>
              </div>
            </section>

            <section v-if="Object.keys(m.detail.scripts).length">
              <h3 class="mb-2 text-sm font-semibold">技术话术（按维度）</h3>
              <ul class="space-y-1 text-sm">
                <li v-for="(vs, dim) in m.detail.scripts" :key="dim" class="text-ink/70">
                  {{ dim }}：{{ vs.length }} 条
                </li>
              </ul>
            </section>

            <section v-if="m.detail.endorsements.length">
              <h3 class="mb-2 text-sm font-semibold">品牌背书（{{ m.detail.endorsements.length }}）</h3>
              <ul class="list-disc space-y-1 pl-5 text-sm text-ink/70">
                <li v-for="(e, i) in m.detail.endorsements.slice(0, 5)" :key="i">{{ e }}</li>
              </ul>
            </section>

            <section v-if="m.detail.intro.length">
              <h3 class="mb-2 text-sm font-semibold">介绍</h3>
              <ul class="list-disc space-y-1 pl-5 text-sm text-ink/70">
                <li v-for="(t, i) in m.detail.intro.slice(0, 5)" :key="i">{{ t }}</li>
              </ul>
            </section>

            <section v-if="Object.keys(m.detail.tests).length">
              <h3 class="mb-2 text-sm font-semibold">测试结果（{{ Object.keys(m.detail.tests).length }}）</h3>
              <ul class="space-y-1 text-sm text-ink/70">
                <li v-for="(_v, k) in m.detail.tests" :key="k">{{ k }}</li>
              </ul>
            </section>

            <section>
              <h3 class="mb-2 text-sm font-semibold">缺口体检</h3>
              <div class="flex flex-wrap gap-1 text-xs">
                <Pill>{{ m.detail.coverage.has_specs ? "有参数" : "缺参数" }}</Pill>
                <Pill>{{ m.detail.coverage.has_tests ? "有测试" : "缺测试" }}</Pill>
                <Pill>话术 {{ m.detail.coverage.script_dimensions || 0 }} 维</Pill>
              </div>
            </section>

            <section>
              <h3 class="mb-2 text-sm font-semibold">注入预览（生成时会喂给 LLM 的事实，受 token 上限）</h3>
              <pre class="whitespace-pre-wrap rounded-lg bg-ink/5 p-3 text-xs leading-relaxed text-ink/80">{{ m.detail.inject_preview || "（无可注入事实）" }}</pre>
            </section>
          </div>
        </div>
      </template>
    </SplitPane>
  </div>
</template>
```

> 样式细节（卡片/分隔/留白）以 `ZhihuMonitorModule.vue` 为基准微调；`var(--card-2)`/`text-ink` 等 token 若不存在用最近义（先 grep 既有 token）。**行选中底色用 inline-style（非 reactive class），grid item 加 `min-w-0`**（见记忆）。

- [ ] **Step 4: 跑测试 + 类型检查通过**

Run: `cd frontend; npx vitest run src/views/__tests__/MaterialsView.spec.ts`
Expected: PASS（3 passed）
Run: `cd frontend; npx vue-tsc --noEmit`（跑完 `git checkout -- vite.config.js 2>$null`）
Expected: 无新增类型错误。

- [ ] **Step 5: 提交**

```bash
git add frontend/src/views/MaterialsView.vue frontend/src/views/__tests__/MaterialsView.spec.ts
git commit -m "feat(materials): 品牌型号 tab — SplitPane 列表+详情+注入预览（只读）"
```

---

### Task C2: 整包前端检查 + 手动验证清单

- [ ] **Step 1: 前端全测 + 类型**

Run: `cd frontend; npx vitest run`（确认无回归）
Run: `cd frontend; npx vue-tsc --noEmit`（跑完还原 vite.config.js）
Expected: 全绿。

- [ ] **Step 2: 写「手动验证清单」进 PR body**（agent 起不稳 dev 服务，端到端交互交用户）：
  - 设置里素材库路径指向真实库 → 素材库 nav 点开 → 列表出 33 型号、主推/竞品分组、缺口 pill。
  - 点 CEWEY 某型号 → 右侧参数表/认证/话术维度/背书/介绍/测试/缺口/**注入预览**齐全。
  - 注入预览文本 = 生成时实际会喂的事实块（与开 `brand_memory.inject` 后的注入一致）。

---

## 验收对照（spec §6 / §9.7）

| spec 验收 | 本 Plan | 证据 |
|---|---|---|
| 「素材库」入口可见 | B1 nav + 路由 | 手动 + vue-tsc |
| 品牌型号 tab 列表（主推/竞品分组） | C1 | `MaterialsView.spec` 分组断言 |
| 详情只读：specs/话术条数/背书/intro/tests/缺口 | C1 | 详情渲染 + service 测试 |
| 按型号预览将注入什么 | A1 `render_brand_facts` + C1 预览区 | `test_get_model_detail` preview 断言 |
| `GET /api/brand-memory`、`/{model}` | A2 | 4 路由测试 |

---

## 不做（留 5b / Phase 3）

- `SkillEditView` role 下拉 + ArticleView **factcheck 审查面板** → **Plan 5b**。
- 「浏览」「录入」tab、查重、新建/编辑型号记忆（写入器）→ Phase 3。
- 注入预览的「按维度过滤」、列表分页/搜索 → 未来。

---

## Self-Review（对照 spec §6 + 决定）

- **Spec 覆盖**：§6 入口→B1；列表→C1；只读详情→C1；注入预览→A1+C1；API→A2。✅
- **占位符扫描**：后端/ store 完整代码 + 可跑命令；view 完整 SFC；测试含完整断言。✅
- **类型一致性**：service 返回 `{model,brand,role,coverage}`（list）/ `mem.model_dump()+model_full+inject_preview`（detail）与 store `BrandModelRow`/`ModelDetail`、view 引用一致；路由 full-stem `{model}` 与 store `encodeURIComponent(model)` 一致。✅
- **零回归**：纯加法（新 service/route/store/view/nav 项）；既有生成链/路由不动；前端新增页不影响其它页。✅

---

## 测试调用（关键）

**后端**（sidecar import 路径——否则解析到主仓 editable 装）：单行
```
cd D:\CSM\.claude\worktrees\phase1-plan5; $env:PYTHONPATH="D:\CSM\.claude\worktrees\phase1-plan5;D:\CSM\.claude\worktrees\phase1-plan5\sidecar"; D:/CSM/.venv/Scripts/python.exe -m pytest <args>
```
**前端**：`cd D:\CSM\.claude\worktrees\phase1-plan5\frontend; npx vitest run <file>`；类型 `npx vue-tsc --noEmit`（跑完 `git checkout -- vite.config.js` 还原，vue-tsc 会 emit 它触发 vite restart）。
