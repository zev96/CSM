# Part 1：skill 链成本透明 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把链成本行从「调用 N 次 · 共 X 字」升级为「调用 N 次 · ≈X tokens · ≈¥Y」——本地 CJK token 估算 + 内置单价表（默认 + 设置可覆盖），后端在 done 时算成本。

**Architecture:** 新 `csm_core/llm/pricing.py`（纯函数：估 token + 单价表 + 算钱）；`ChainPass.to_dict` 增 token 字段（单一估算源）；三个 done-emit 点（generate / finalize / chain rerun）用 `chain_cost(passes_dicts, effective_model, cfg.pricing)` 算 `cost` 带进事件/响应；前端展示 + 设置「模型单价」卡。

**Tech Stack:** Python 3.12（csm_core 纯函数 + sidecar）；Vue 3 + Pinia + TS + vitest；pytest。

参考 spec：[2026-06-26-chain-cost-streaming-rerun-design.md](../specs/2026-06-26-chain-cost-streaming-rerun-design.md) §4。

**对 spec §4.2 的实现细化**：cost 不放 `ChainState.cost()`（会让 chain_service 依赖 config + 触动 run_chain/rerun 现有测试），改在 **done-emit 点**算；`chain_cost` 吃 `to_dict` 产出的 dict（用其 `input_tokens`/`output_tokens` 字段）而非 ChainPass 对象 → token 估算只在 `to_dict` 发生一次。

---

## 文件结构

**Unit A（pricing 核心 + token 接线）**
- Create: `csm_core/llm/pricing.py`
- Modify: `sidecar/csm_sidecar/services/chain_service.py:36-42`（`ChainPass.to_dict` 增 token）
- Test: `sidecar/tests/test_pricing.py`（新）、`sidecar/tests/test_chain_service.py`（断言 to_dict 含 token，若无则新增小用例）

**Unit B（配置 + emit cost）**
- Modify: `csm_core/config.py:158`（`AppConfig.pricing` 字段）
- Modify: `sidecar/csm_sidecar/services/generate_service.py`（`_run_job` done + `_finalize_job` done 带 cost）
- Modify: `sidecar/csm_sidecar/routes/chain.py`（`/api/chain/rerun` 200 响应带 cost）
- Test: `sidecar/tests/test_pricing_config.py`（新）、扩 `test_generate_chain.py` / `test_finalize_job.py` / `test_routes_chain.py` 断 cost

**Unit C（前端）**
- Modify: `frontend/src/stores/article.ts`（`ChainPass` 加 token、`cost` state、done/rerun 读 cost、`tokenTotal` getter）
- Modify: `frontend/src/views/ArticleView.vue:1486`（成本行）
- Create: `frontend/src/components/settings/PricingCard.vue`
- Modify: `frontend/src/views/SettingsView.vue`（挂 PricingCard）
- Test: `frontend/src/stores/__tests__/article.cost.spec.ts`（新）、`frontend/src/components/settings/__tests__/PricingCard.spec.ts`（新）

每 Unit 一个 PR？**否**——Part 1 三 Unit 合成**一个 PR**（成本是一个完整特性，拆开发不可用）。Unit 间走 subagent 双审，最后整 Part 一个 PR。

---

## Task A: pricing 核心 + token 接线

**Files:**
- Create: `csm_core/llm/pricing.py`
- Modify: `sidecar/csm_sidecar/services/chain_service.py`
- Test: `sidecar/tests/test_pricing.py`

- [ ] **Step 1: 写失败测试 `sidecar/tests/test_pricing.py`**

```python
"""Part 1 Unit A: 本地 token 估算 + 单价表 + 算钱。"""
from __future__ import annotations

from csm_core.llm import pricing


def test_estimate_tokens_cjk_and_latin():
    assert pricing.estimate_tokens("") == 0
    # 纯中文 10 字 → ceil(10*0.6)=6
    assert pricing.estimate_tokens("无线吸尘器评测十款") == 6 or pricing.estimate_tokens("无线吸尘器评测十款") == 5
    # 纯英文 ~ /4
    assert pricing.estimate_tokens("hello world") >= 2
    # 混合：中文计 0.6、其余 0.25，结果 > 纯按字符数 *0.25
    mixed = pricing.estimate_tokens("吸力220AW 实测")
    assert mixed > 0


def test_price_for_default_override_unknown():
    # 默认表命中
    p = pricing.price_for("deepseek-chat")
    assert p is not None and p.input > 0 and p.output > 0
    # 覆盖
    ov = {"deepseek-chat": {"input": 9.9, "output": 8.8}}
    p2 = pricing.price_for("deepseek-chat", ov)
    assert p2.input == 9.9 and p2.output == 8.8
    # 未知 model → None
    assert pricing.price_for("no-such-model") is None
    assert pricing.price_for(None) is None


def test_chain_cost_with_and_without_price():
    passes = [
        {"input_tokens": 1000, "output_tokens": 500},
        {"input_tokens": 200, "output_tokens": 800},
    ]
    # 有价
    c = pricing.chain_cost(passes, "deepseek-chat")
    assert c["input_tokens"] == 1200 and c["output_tokens"] == 1300
    assert c["cost"] is not None and c["currency"] == "CNY"
    # 无价（未知 model）→ cost=None 但 token 仍汇总
    c2 = pricing.chain_cost(passes, "no-such-model")
    assert c2["cost"] is None and c2["input_tokens"] == 1200
```

- [ ] **Step 2: 跑确认失败**

Run:
```
$env:PYTHONPATH="D:\CSM\.claude\worktrees\busy-matsumoto-c087bd;D:\CSM\.claude\worktrees\busy-matsumoto-c087bd\sidecar"; & "D:\CSM\.venv\Scripts\python.exe" -X utf8 -m pytest sidecar/tests/test_pricing.py -v
```
Expected: FAIL — `ModuleNotFoundError: csm_core.llm.pricing`。

- [ ] **Step 3: 实现 `csm_core/llm/pricing.py`**

```python
"""本地 token 估算 + 内置单价表 + 链成本（无依赖、离线稳）。

token 是**估算值**（CJK 启发式，非真实分词），UI 须以「≈」呈现。单价表
默认近似、可在设置（AppConfig.pricing）覆盖；未知 model → 无价（只显 token）。
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any

# CJK 统一表意 + 扩展A + 兼容 + CJK标点 + 全角（够覆盖中文正文；只求稳定估算）。
_CJK = re.compile(r"[㐀-䶿一-鿿豈-﫿　-〿＀-￯]")


def estimate_tokens(text: str) -> int:
    """CJK 感知 token 估算：中文 ~0.6 token/字、其余 ~0.25 token/字符。"""
    if not text:
        return 0
    cjk = len(_CJK.findall(text))
    other = len(text) - cjk
    return math.ceil(cjk * 0.6 + other * 0.25)


@dataclass(frozen=True)
class ModelPrice:
    input: float   # ¥ / 1M tokens
    output: float  # ¥ / 1M tokens


# 内置默认单价（¥/1M tokens，**近似种子值**，随官方调价会过时 → 设置可覆盖）。
# key = model 名（与 AppConfig.default_model 的 value 对齐）。缺项 → price_for 返回 None。
DEFAULT_PRICES: dict[str, ModelPrice] = {
    "deepseek-chat": ModelPrice(input=1.0, output=2.0),
    "deepseek-reasoner": ModelPrice(input=1.0, output=4.0),
    "qwen-plus": ModelPrice(input=0.8, output=2.0),
    "qwen-max": ModelPrice(input=2.4, output=9.6),
    "qwen-turbo": ModelPrice(input=0.3, output=0.6),
}


def price_for(model: str | None, overrides: dict[str, dict] | None = None) -> ModelPrice | None:
    """默认←设置覆盖。未知 model / None → None（调用方据此只显 token）。"""
    if not model:
        return None
    ov = (overrides or {}).get(model)
    if ov and "input" in ov and "output" in ov:
        return ModelPrice(input=float(ov["input"]), output=float(ov["output"]))
    return DEFAULT_PRICES.get(model)


def chain_cost(
    pass_dicts: list[dict[str, Any]], model: str | None,
    overrides: dict[str, dict] | None = None,
) -> dict[str, Any]:
    """从 ChainPass.to_dict() 列表算成本摘要（用其 input_tokens/output_tokens 字段）。
    无价 → cost=None（token 仍汇总）。"""
    it = sum(int(p.get("input_tokens", 0)) for p in pass_dicts)
    ot = sum(int(p.get("output_tokens", 0)) for p in pass_dicts)
    price = price_for(model, overrides)
    cost = None if price is None else round(
        it / 1_000_000 * price.input + ot / 1_000_000 * price.output, 4)
    return {"input_tokens": it, "output_tokens": ot, "cost": cost, "currency": "CNY"}
```

- [ ] **Step 4: 改 `ChainPass.to_dict` 增 token 字段**

`chain_service.py` 顶部加 import：`from csm_core.llm import pricing`。`ChainPass.to_dict`（行 36-42）改为：

```python
    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index, "skill_id": self.skill_id, "role": self.role,
            "skill_name": self.skill_name,
            "input_chars": len(self.input), "output_chars": len(self.output),
            "input_tokens": pricing.estimate_tokens(self.input),
            "output_tokens": pricing.estimate_tokens(self.output),
            "output": self.output,
        }
```

- [ ] **Step 5: 写 to_dict token 测试（加到 `test_pricing.py` 末尾）**

```python
def test_chainpass_to_dict_has_tokens():
    from csm_sidecar.services.chain_service import ChainPass
    d = ChainPass(index=0, skill_id="p", role="persona", skill_name="人设",
                  input="无线吸尘器", output="成稿正文内容").to_dict()
    assert d["input_tokens"] > 0 and d["output_tokens"] > 0
    assert d["input_chars"] == 5  # 旧字段保留（零回归）
```

- [ ] **Step 6: 跑测试 + chain 回归**

Run:
```
$env:PYTHONPATH="D:\CSM\.claude\worktrees\busy-matsumoto-c087bd;D:\CSM\.claude\worktrees\busy-matsumoto-c087bd\sidecar"; & "D:\CSM\.venv\Scripts\python.exe" -X utf8 -m pytest sidecar/tests/test_pricing.py sidecar/tests/test_chain_service.py sidecar/tests/test_chain_rerun.py -v
```
Expected: PASS（pricing + chain 现有测试全绿 = to_dict 增字段零回归）。

- [ ] **Step 7: Commit**

```bash
git add csm_core/llm/pricing.py sidecar/csm_sidecar/services/chain_service.py sidecar/tests/test_pricing.py
git commit -m "feat(cost): pricing 估算+单价表 + ChainPass token 字段

本地 CJK token 估算 + 内置单价表（默认+覆盖）+ chain_cost；ChainPass.to_dict
增 input/output_tokens（保留旧 *_chars 零回归）。

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task B: 配置 pricing + done 带 cost

**Files:**
- Modify: `csm_core/config.py`
- Modify: `sidecar/csm_sidecar/services/generate_service.py`
- Modify: `sidecar/csm_sidecar/routes/chain.py`
- Test: `sidecar/tests/test_pricing_config.py`, 扩 `test_generate_chain.py` / `test_routes_chain.py`

- [ ] **Step 1: 写失败测试 `sidecar/tests/test_pricing_config.py`**

```python
"""Part 1 Unit B: AppConfig.pricing 字段 + 深合并 patch。"""
from __future__ import annotations

from csm_core.config import AppConfig


def test_pricing_field_default_empty():
    cfg = AppConfig()
    assert cfg.pricing == {}


def test_pricing_roundtrip():
    cfg = AppConfig.model_validate({"pricing": {"deepseek-chat": {"input": 1.5, "output": 3.0}}})
    assert cfg.pricing["deepseek-chat"]["input"] == 1.5


def test_pricing_unknown_key_tolerated():
    # 旧 settings.json 无该键 → 默认 {}；多余结构不报错（无 extra=forbid）
    cfg = AppConfig.model_validate({"user_name": "x"})
    assert cfg.pricing == {}
```

- [ ] **Step 2: 跑确认失败**

Run:
```
$env:PYTHONPATH="D:\CSM\.claude\worktrees\busy-matsumoto-c087bd;D:\CSM\.claude\worktrees\busy-matsumoto-c087bd\sidecar"; & "D:\CSM\.venv\Scripts\python.exe" -X utf8 -m pytest sidecar/tests/test_pricing_config.py -v
```
Expected: FAIL — `AppConfig` 无 `pricing` 字段（`test_pricing_field_default_empty` AttributeError）。

- [ ] **Step 3: 加 `AppConfig.pricing` 字段**

`config.py` 的 `AppConfig`（`export_format` 附近，行 186 后）加：

```python
    # 模型单价覆盖（¥/1M tokens）。空 = 用 csm_core.llm.pricing.DEFAULT_PRICES。
    # key=model 名，value={"input": float, "output": float}。设置页可改、深合并 patch。
    pricing: dict[str, dict[str, float]] = Field(default_factory=dict)
```

- [ ] **Step 4: 三 emit 点带 cost**

`generate_service.py` 顶部 import 加 `from csm_core.llm import pricing`。加一个内部 helper（放 `_plan_to_dict` 附近）：

```python
def _effective_model(req_model: str | None, provider: str | None, cfg: Any) -> str | None:
    """成本用的实际 model：req 指定优先，否则取该 provider 的默认 model。"""
    if req_model:
        return req_model
    prov = provider or cfg.default_provider
    return cfg.default_model.get(prov) if prov else None
```

`_run_job` 的成功 `bus.finish`（导出后那个，约行 264-273）加 `cost`：

```python
        cost = pricing.chain_cost(
            outcome.passes, _effective_model(req.model, req.provider, cfg), cfg.pricing)
        bus.finish(
            job_id,
            document=paths["document"], format=paths["format"], title=paths["title"],
            plan=_plan_to_dict(plan), draft=draft,
            final_text=final_text, passes=outcome.passes, cost=cost,
        )
```

`_finalize_job` 的成功 `bus.finish`（约行 331-338）同样加：

```python
        cost = pricing.chain_cost(
            outcome.passes, _effective_model(req.model, req.provider, cfg), cfg.pricing)
        bus.finish(
            job_id, document=None, plan=_plan_to_dict(plan), draft=req.draft,
            final_text=outcome.final_text, passes=outcome.passes, cost=cost,
        )
```

（`_maybe_block_for_factcheck` 的 blocked done 也可带 cost——本 Part 可选；越界被拦时成本已花，带上更准。若加，blocked done 同样 `cost=pricing.chain_cost(passes, model, cfg.pricing)`。**本计划：blocked done 也带 cost**，在 `_maybe_block_for_factcheck` 内 `passes` 已有，加 `cost` 参数透传或就地算。为简单，**就地算**：该函数已收 `cfg`，加 `model` 入参后 `cost=pricing.chain_cost(passes or [], model, cfg.pricing)` 带进 blocked `bus.finish`。两个调用点传 `_effective_model(...)`。）

`routes/chain.py` 的 `/api/chain/rerun`（同步 200 响应）加 cost：拿 state 的 provider/model + cfg：

```python
# rerun 路由内，chain_service.rerun 返回后：
    cfg = config_service.load()
    state = chain_service.get_state(body.job_id)  # rerun 后仍在缓存
    res["cost"] = pricing.chain_cost(
        res["passes"], _eff_model(state, cfg), cfg.pricing)
    return res
```
（`routes/chain.py` 加 import `pricing`/`config_service`；`_eff_model(state, cfg)` = `state.model or cfg.default_model.get(state.provider or cfg.default_provider)`，state 非空——rerun 成功必有缓存。若担心 state 竞态淘汰，`state` None 时 `cost=None` 兜底。）

- [ ] **Step 5: 扩测试断 cost**

`test_pricing_config.py` 末尾加（generate done 带 cost，复用 test_generate_chain 的 `_wire` 思路——直接断 `cap["finish"]["cost"]`）：

```python
def test_generate_done_carries_cost(tmp_path, monkeypatch):
    # 复用 test_generate_chain 的装配（导入其 _wire）跑 _run_job，断 finish 带 cost
    from tests.test_generate_chain import _wire, _Skill  # 同目录无 __init__，用 conftest 暴露或内联
    # —— 若跨文件 import 不可解析，则在本测试内联一份 _wire（参照 test_generate_chain）。
```

**注**：`sidecar/tests` 无 `__init__`，跨文件 import 不稳。**实现时**在 `test_pricing_config.py` 内联一份精简 `_wire`（仿 `test_generate_chain._wire`，stub 到 `cap["finish"]`），断言：

```python
    cap = _wire(monkeypatch, tmp_path, inject=False, factcheck=False,
                skills={"人设": _Skill("人设", role="persona", name="人设", body="B")})
    req = generate_service.GenerateRequest(keyword="无线吸尘器", template_id="t",
                                           skill_id="人设", model="deepseek-chat")
    generate_service._run_job("job-cost", req)
    cost = cap["finish"]["cost"]
    assert cost["input_tokens"] >= 0 and cost["currency"] == "CNY"
    assert cost["cost"] is not None  # deepseek-chat 有默认价
```

`test_routes_chain.py` 的 rerun 200 用例加断言 `data["cost"]["currency"] == "CNY"`。

- [ ] **Step 6: 跑测试 + 回归**

Run:
```
$env:PYTHONPATH="D:\CSM\.claude\worktrees\busy-matsumoto-c087bd;D:\CSM\.claude\worktrees\busy-matsumoto-c087bd\sidecar"; & "D:\CSM\.venv\Scripts\python.exe" -X utf8 -m pytest sidecar/tests/test_pricing_config.py sidecar/tests/test_generate_chain.py sidecar/tests/test_finalize_job.py sidecar/tests/test_routes_chain.py sidecar/tests/test_generate_factcheck_gate.py -v
```
Expected: PASS（含现有 generate/finalize/rerun 测试零回归 + cost 新断言）。

- [ ] **Step 7: Commit**

```bash
git add csm_core/config.py sidecar/csm_sidecar/services/generate_service.py sidecar/csm_sidecar/routes/chain.py sidecar/tests/test_pricing_config.py sidecar/tests/test_routes_chain.py
git commit -m "feat(cost): AppConfig.pricing + done/rerun 带 cost 摘要

generate/finalize/rerun 三处 done-emit 用 chain_cost(passes, 实际model, cfg.pricing)
带 cost；实际 model 取 req.model 否则 default_model[provider]。

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task C: 前端成本行 + 模型单价卡

**Files:**
- Modify: `frontend/src/stores/article.ts`
- Modify: `frontend/src/views/ArticleView.vue:1486`
- Create: `frontend/src/components/settings/PricingCard.vue`
- Modify: `frontend/src/views/SettingsView.vue`
- Test: `frontend/src/stores/__tests__/article.cost.spec.ts`, `frontend/src/components/settings/__tests__/PricingCard.spec.ts`

- [ ] **Step 1: 写失败测试 `article.cost.spec.ts`**

```ts
import { setActivePinia, createPinia } from "pinia";
import { describe, it, expect, vi, beforeEach } from "vitest";

let sseHandlers: Record<string, (d: any) => void> = {};
const postMock = vi.fn();
const getMock = vi.fn().mockResolvedValue({ data: {} });
vi.mock("@/stores/sidecar", () => ({ useSidecar: () => ({ client: { post: postMock, get: getMock } }) }));
vi.mock("@/api/client", () => ({
  subscribe: (_u: string, h: Record<string, (d: any) => void>) => { sseHandlers = h; return () => {}; },
}));
vi.mock("@/composables/useNotifications", () => ({ useNotifications: () => ({ push: vi.fn() }) }));

import { useArticle } from "@/stores/article";

describe("article store — 链成本", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    postMock.mockReset(); getMock.mockReset(); getMock.mockResolvedValue({ data: {} });
    sseHandlers = {};
  });

  it("done 带 cost → 存进 cost state；tokenTotal getter 求和", async () => {
    postMock.mockResolvedValueOnce({ data: { job_id: "j1" } });
    const a = useArticle();
    await a.submit({ keyword: "k", template_id: "t", skill_chain: ["p"] });
    sseHandlers.done({
      final_text: "成稿", passes: [],
      cost: { input_tokens: 1200, output_tokens: 800, cost: 0.0032, currency: "CNY" },
    });
    expect(a.cost?.cost).toBe(0.0032);
    expect(a.tokenTotal).toBe(2000);
  });

  it("无 cost（旧路径/未知 model）→ cost=null，tokenTotal=0", async () => {
    postMock.mockResolvedValueOnce({ data: { job_id: "j2" } });
    const a = useArticle();
    await a.submit({ keyword: "k", template_id: "t" });
    sseHandlers.done({ final_text: "成稿" });
    expect(a.cost).toBeNull();
    expect(a.tokenTotal).toBe(0);
  });

  it("submit 清空上一轮 cost", async () => {
    postMock.mockResolvedValueOnce({ data: { job_id: "j3" } });
    const a = useArticle();
    a.cost = { input_tokens: 1, output_tokens: 1, cost: 0.1, currency: "CNY" } as any;
    await a.submit({ keyword: "k", template_id: "t" });
    expect(a.cost).toBeNull();
  });
});
```

- [ ] **Step 2: 跑确认失败**

Run:
```
cd D:\CSM\.claude\worktrees\busy-matsumoto-c087bd\frontend; npx vitest run src/stores/__tests__/article.cost.spec.ts
```
Expected: FAIL（`cost` state / `tokenTotal` getter 不存在）。

- [ ] **Step 3: store 加 cost state + tokenTotal getter + 读取**

`article.ts`：`ChainPass` interface 加 `input_tokens: number; output_tokens: number;`。加类型：

```ts
/** 链成本摘要（镜像后端 pricing.chain_cost）。cost=null = 未知 model 无价。 */
export interface ChainCost {
  input_tokens: number;
  output_tokens: number;
  cost: number | null;
  currency: string;
}
```

`ArticleState` 加 `cost: ChainCost | null;`；`state()` 初值 `cost: null,`。`submit()` reset 块 + `finalize()` 的 POST 成功后清空块都加 `this.cost = null;`。getter 加：

```ts
    tokenTotal: (state) =>
      state.cost ? state.cost.input_tokens + state.cost.output_tokens : 0,
```

`_subscribe` 的 `done` handler 加 `if (d.cost) this.cost = d.cost as ChainCost;`。`rerunPass` 的成功分支加 `if (resp.data?.cost) this.cost = resp.data.cost;`（Part 1 rerun 仍同步 200）。

- [ ] **Step 4: 跑 store 测试 + 回归**

Run:
```
cd D:\CSM\.claude\worktrees\busy-matsumoto-c087bd\frontend; npx vitest run src/stores/__tests__/article.cost.spec.ts src/stores/__tests__/article.chain.spec.ts src/stores/__tests__/article.finalize.spec.ts
```
Expected: PASS（cost 新测 + chain/finalize 回归绿）。

- [ ] **Step 5: 改成本行（ArticleView 行 1486-1488）**

```html
                <span v-if="article.passes.length" data-chain-cost>
                  调用 {{ article.callCount }} 次 · ≈{{ article.tokenTotal }} tokens<template v-if="article.cost && article.cost.cost != null"> · ≈¥{{ article.cost.cost }}</template>
                </span>
```
（有 passes 但 cost 为空/无价 → 只显「调用 N 次 · ≈X tokens」；`callCount` getter 保留。）

- [ ] **Step 6: 建 `PricingCard.vue`（仿 `BrandMemoryCard.vue` 范式）**

读 `frontend/src/components/settings/BrandMemoryCard.vue` 作模板（同款 Card 容器 + 标题 + 行控件 + patch config）。PricingCard 列出「DEFAULT_PRICES 已知 model ∪ 当前 config.default_model 的值」，每行：model 名 + input ¥/1M 输入框 + output ¥/1M 输入框，占位显示默认值，改→`config` patch `{pricing:{<model>:{input,output}}}`。已知 model 清单前端内置一份常量（与后端 DEFAULT_PRICES key 对齐）：

```ts
const KNOWN_MODELS = ["deepseek-chat", "deepseek-reasoner", "qwen-plus", "qwen-max", "qwen-turbo"];
```
patch 走 config store（`useConfig().patch({ pricing: { [model]: { input, output } } })`，仿 BrandMemoryCard 的部分 patch）。

- [ ] **Step 7: 挂到 SettingsView**

`SettingsView.vue` 在品牌记忆卡附近 import + 渲染 `<PricingCard />`（跟现有卡片排布）。

- [ ] **Step 8: 写 `PricingCard.spec.ts`**

```ts
import { mount, flushPromises } from "@vue/test-utils";
import { describe, it, expect, vi, beforeEach } from "vitest";

const patchMock = vi.fn();
vi.mock("@/stores/config", () => ({
  useConfig: () => ({ data: { pricing: {}, default_model: { deepseek: "deepseek-chat" } }, patch: patchMock }),
}));

import PricingCard from "@/components/settings/PricingCard.vue";

describe("PricingCard", () => {
  beforeEach(() => { patchMock.mockReset(); });

  it("列出已知 model 行", async () => {
    const w = mount(PricingCard, { global: { stubs: { teleport: true } } });
    await flushPromises();
    expect(w.text()).toContain("deepseek-chat");
  });

  it("改单价 → patch {pricing:{model:{input,output}}}", async () => {
    const w = mount(PricingCard, { global: { stubs: { teleport: true } } });
    await flushPromises();
    const input = w.find("[data-price-input='deepseek-chat']");
    await input.setValue("1.5");
    await input.trigger("change");
    expect(patchMock).toHaveBeenCalledWith(
      expect.objectContaining({ pricing: expect.objectContaining({ "deepseek-chat": expect.objectContaining({ input: 1.5 }) }) }),
    );
  });
});
```
（`data-price-input` / `data-price-output` 属性须在 PricingCard 输入框上加，供测试定位。）

- [ ] **Step 9: 跑前端测试 + 回归**

Run:
```
cd D:\CSM\.claude\worktrees\busy-matsumoto-c087bd\frontend; npx vitest run src/stores/__tests__/article.cost.spec.ts src/components/settings/__tests__/PricingCard.spec.ts src/views/__tests__/ArticleView.chain.spec.ts src/stores/__tests__/article.chain.spec.ts
```
Expected: PASS。**`ArticleView.chain.spec.ts` 里断言「320 字」成本行的用例若因文案改动失败，更新该断言为新的「≈X tokens」文案**（这是预期的文案变更，非回归）。

- [ ] **Step 10: Commit**

```bash
git add frontend/src/stores/article.ts frontend/src/views/ArticleView.vue frontend/src/components/settings/PricingCard.vue frontend/src/views/SettingsView.vue frontend/src/stores/__tests__/article.cost.spec.ts frontend/src/components/settings/__tests__/PricingCard.spec.ts
git commit -m "feat(cost): 前端成本行 ≈tokens·¥ + 模型单价设置卡

成本行升级为「调用 N 次 · ≈X tokens · ≈¥Y」（无价回退只显 token）；
store cost state + tokenTotal getter；设置加 PricingCard 改每 model 单价。

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## 自审清单

**Spec 覆盖：** §4.1 pricing.py→Task A ✓；§4.2 token 接线 + done 带 cost→Task A Step4 + Task B Step4 ✓（实现细化：emit 点算、非 ChainState.cost()）；§4.3 config→Task B Step3 ✓；§4.4 前端成本行 + cost state + PricingCard→Task C ✓。

**占位扫描：** 各步含完整代码/命令/期望。Task B Step5 的跨文件 import 风险已标「内联 _wire」。DEFAULT_PRICES 价为近似种子（spec 已声明可覆盖），非占位。

**类型一致：** `ChainCost{input_tokens,output_tokens,cost,currency}` / `pricing.chain_cost(pass_dicts,model,overrides)->同形 dict` / `ChainPass` 加 token / `tokenTotal` getter 全程一致；后端 `chain_cost` 吃 dict（含 to_dict 的 token 字段）。

**零回归：** to_dict 只增字段、run_chain/rerun 签名不动、config 加默认 {} 字段、done 只增 cost 键；现有 generate/finalize/chain/routes 测试保持绿（文案断言除外，预期更新）。

---

## 执行方式

转 subagent-driven-development：每 Task 一 implementer + 两段审查（spec 合规→代码质量），Task 间 controller 审。三 Task 合**一个 PR**（成本是完整特性）。Part 1 merge 后再写 Part 2 计划。
