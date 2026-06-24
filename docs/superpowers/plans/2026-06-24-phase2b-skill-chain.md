# skill 链多-pass 实现计划（Phase 2b）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development 逐任务实现。步骤用 `- [ ]` 复选框跟踪。

**Goal:** 把单 skill 一次润色升级为按 role 顺序的多-pass 链（人设→去AI味→平台适配），分多次调用、逐 pass 预览、单独重跑；不传链 = 今天行为（零回归）。

**Architecture:** 新 csm_core 纯函数 `build_refine_prompt`（精修 pass）+ 新 sidecar `chain_service`（跑链 + LRU 缓存链状态 + 逐 pass 重跑，仿 `assembler_service`）。`generate_service` 用 `run_chain` 替换单次 `complete`。位置定职责：step0=组装(`build_prompt`)，step1+=精修(`build_refine_prompt`)。factcheck 跑末段（不变）。

**Tech Stack:** Python（csm_core 纯函数 + FastAPI sidecar，pytest）、Vue 3 + Pinia + TS（Vitest）。

**Spec:** [2026-06-24-phase2b-skill-chain-design.md](../specs/2026-06-24-phase2b-skill-chain-design.md)

---

## 文件结构

| 层 | 新增 | 必改 |
|---|---|---|
| `csm_core/llm/` | — | `prompts.py`（`build_refine_prompt`） |
| `sidecar/csm_sidecar/services/` | `chain_service.py` | `generate_service.py` |
| `sidecar/csm_sidecar/routes/` | `chain.py`（`POST /api/chain/rerun`） | `generate.py`（`GenerateBody.skill_chain`）、`main.py`（注册 chain 路由） |
| `examples/skills/` | `小红书适配.md`(role:platform) | — |
| `frontend/src/` | `components/article/SkillChainPicker.vue` | `stores/article.ts`、`components/home/CreateArticleHero.vue`、`views/ArticleView.vue`、`views/SkillEditView.vue` |

**不改**：`polish_service`/`/api/polish/block`；`factcheck_service`/`/export`；`assembler_service`/reroll；角度/注入链路（Phase 2a/1）。

**测试环境**（worktree 无 venv / 无 node_modules）：
- 后端：`$env:PYTHONPATH="<worktree>;<worktree>\sidecar"; $env:PYTHONIOENCODING="utf-8"; & "D:\CSM\.venv\Scripts\python.exe" -X utf8 -m pytest <paths> -q`（先验 `import csm_core, csm_sidecar` 解析在 worktree）。已知无关失败（忽略）：deepseek httpx / rate_limit / export markdown / test_cli·test_batch_runner / ms-playwright / mining schema / zhihu_search / monitor。
- 前端：`cd frontend; npm ci`（首次，不 churn lockfile）→ `npx vitest run <spec>`；提交前 `git checkout -- frontend/package-lock.json` 若被 churn。
- **PowerShell 工具跑测试，不用 Bash。** 每任务 commit 带 `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`。不 push（每 Unit 完后我统一出 PR）。

---

## Unit A — 精修 prompt + chain_service（核心，mock LLM 测）

### Task A1：`build_refine_prompt`

**Files:** Modify `csm_core/llm/prompts.py`；Test `tests/core/llm/test_refine_prompt.py`

- [ ] **Step 1: 写失败测试**

```python
from csm_core.llm.prompts import build_refine_prompt


def test_refine_system_is_skill_body():
    system, user = build_refine_prompt("小红书风格", "上一段正文")
    assert system == "小红书风格"
    assert "上一段正文" in user


def test_refine_user_has_conservative_constraint():
    _, user = build_refine_prompt("x", "正文")
    assert "保留所有信息点" in user
    assert "不改动任何参数数字或认证" in user
    assert "不删减" in user


def test_refine_empty_body_blank_system():
    system, user = build_refine_prompt(None, "正文")
    assert system == ""
    assert "正文" in user
```

- [ ] **Step 2: 跑测试确认失败** — `... -m pytest tests/core/llm/test_refine_prompt.py -v`。

- [ ] **Step 3: 实现**（追加到 `csm_core/llm/prompts.py`）

```python
def build_refine_prompt(skill_body: str | None, prev_text: str) -> tuple[str, str]:
    """链 step[1:] 的精修 prompt：按 skill 风格改写上段输出，保守约束
    （保信息点/数字/单位/认证，只改文风）。step[0] 仍用 build_prompt。"""
    system = (skill_body or "").strip()
    user = (
        f"【待改写正文】\n{prev_text}\n\n"
        "请按上面的风格指引改写这段正文：保留所有信息点、段落要点与全部"
        "数字/单位/认证名称，只改进措辞、语感与风格一致性；不新增虚构事实，"
        "不删减关键信息，不改动任何参数数字或认证。"
    )
    return system, user
```

- [ ] **Step 4: 跑测试确认通过 + 回归** — `... -m pytest tests/core/llm -q`（既有 build_prompt 测试不变）。
- [ ] **Step 5: 提交** — `git commit -m "feat(prompts): build_refine_prompt（链精修 pass 保守约束）"`

---

### Task A2：`chain_service.run_chain` + 缓存

**Files:** Create `sidecar/csm_sidecar/services/chain_service.py`；Test `sidecar/tests/test_chain_service.py`

- [ ] **Step 1: 写失败测试**（mock client；断言：单步==build_prompt、多步顺序喂、on_pass 每 pass 一次、空步=空 body step0、缓存可取）

```python
from csm_sidecar.services import chain_service
from csm_core.llm.prompts import build_prompt, PromptInputs


class FakeClient:
    def __init__(self): self.calls = []
    def complete(self, *, system, user, temperature=None):
        self.calls.append((system, user))
        return f"OUT[{len(self.calls)}]"


def _steps(*specs):
    return [chain_service.ChainStepInput(skill_id=s[0], role=s[1], name=s[2], body=s[3]) for s in specs]


def test_single_step_is_build_prompt(monkeypatch):
    chain_service.reset_for_test()
    c = FakeClient()
    state = chain_service.run_chain(
        "job1", _steps(("persona", "persona", "人设", "人设BODY")),
        draft="毛坯", keyword="无线吸尘器", title=None, angle_directive=None,
        brand_facts=None, provider="mock", model=None, client=c,
        checkpoint=lambda: None, on_pass=lambda p: None,
    )
    # step0 用 build_prompt：system/user 与 build_prompt 一致
    exp_sys, exp_user = build_prompt(PromptInputs(
        user_skill_prompt="人设BODY", keyword="无线吸尘器", draft="毛坯",
        brand_facts=None, title=None, angle_directive=None))
    assert c.calls[0] == (exp_sys, exp_user)
    assert state.final_text == "OUT[1]"
    assert len(state.passes) == 1


def test_multi_step_feeds_prev_and_emits():
    chain_service.reset_for_test()
    c = FakeClient(); seen = []
    state = chain_service.run_chain(
        "job2", _steps(("p","persona","人设","P"), ("h","humanize","去AI味","H")),
        draft="毛坯", keyword="k", title=None, angle_directive=None,
        brand_facts=None, provider="mock", model=None, client=c,
        checkpoint=lambda: None, on_pass=lambda p: seen.append(p.index),
    )
    # step1 是精修：user 含 step0 输出
    assert "OUT[1]" in c.calls[1][1]
    assert state.final_text == "OUT[2]"
    assert seen == [0, 1]
    assert chain_service.get_state("job2") is state


def test_empty_steps_runs_one_compose_pass():
    chain_service.reset_for_test()
    c = FakeClient()
    state = chain_service.run_chain(
        "job3", [], draft="毛坯", keyword="k", title=None, angle_directive=None,
        brand_facts=None, provider="mock", model=None, client=c,
        checkpoint=lambda: None, on_pass=lambda p: None)
    assert len(state.passes) == 1 and c.calls[0][0] == ""  # 空 body → system 空
```

- [ ] **Step 2: 跑测试确认失败**。

- [ ] **Step 3: 实现** `sidecar/csm_sidecar/services/chain_service.py`

```python
"""skill 链多-pass 执行 + 缓存 + 逐 pass 重跑（仿 assembler_service）。

step[0] = 组装 pass（build_prompt：毛坯+事实+角度+标题）；
step[k≥1] = 精修 pass（build_refine_prompt：上段输出+skill+保守约束）。
链状态按 job_id LRU 缓存，供 POST /api/chain/rerun 逐 pass 重跑。
"""
from __future__ import annotations

import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Callable

from csm_core.llm.prompts import PromptInputs, build_prompt, build_refine_prompt

from . import llm_factory


@dataclass
class ChainStepInput:
    skill_id: str | None
    role: str
    name: str
    body: str | None


@dataclass
class ChainPass:
    index: int
    skill_id: str | None
    role: str
    skill_name: str
    input: str
    output: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index, "skill_id": self.skill_id, "role": self.role,
            "skill_name": self.skill_name,
            "input_chars": len(self.input), "output_chars": len(self.output),
            "output": self.output,
        }


@dataclass
class ChainState:
    job_id: str
    draft: str
    keyword: str
    title: str | None
    angle_directive: str | None
    brand_facts: str | None
    provider: str | None
    model: str | None
    steps: list[ChainStepInput]
    passes: list[ChainPass] = field(default_factory=list)

    @property
    def final_text(self) -> str:
        return self.passes[-1].output if self.passes else ""


_cache: "OrderedDict[str, ChainState]" = OrderedDict()
_lock = threading.Lock()
MAX_CACHE = 50


def reset_for_test() -> None:
    with _lock:
        _cache.clear()


def get_state(job_id: str) -> ChainState | None:
    with _lock:
        st = _cache.get(job_id)
        if st is not None:
            _cache.move_to_end(job_id)
        return st


def _cache_put(state: ChainState) -> None:
    with _lock:
        _cache[state.job_id] = state
        _cache.move_to_end(state.job_id)
        while len(_cache) > MAX_CACHE:
            _cache.popitem(last=False)


def _prompt_for(state: ChainState, idx: int, prev_output: str) -> tuple[str, str, str]:
    """返回 (system, user, input_text) for pass idx。idx==0 用 build_prompt；否则精修。"""
    step = state.steps[idx] if idx < len(state.steps) else ChainStepInput(None, "persona", "", None)
    if idx == 0:
        system, user = build_prompt(PromptInputs(
            user_skill_prompt=step.body, keyword=state.keyword, draft=state.draft,
            brand_facts=state.brand_facts, title=state.title,
            angle_directive=state.angle_directive,
        ))
        return system, user, state.draft
    system, user = build_refine_prompt(step.body, prev_output)
    return system, user, prev_output


def run_chain(
    job_id: str, steps: list[ChainStepInput], *,
    draft: str, keyword: str, title: str | None, angle_directive: str | None,
    brand_facts: str | None, provider: str | None, model: str | None,
    client: Any | None = None,
    checkpoint: Callable[[], None] = lambda: None,
    on_pass: Callable[[ChainPass], None] = lambda p: None,
) -> ChainState:
    eff = steps or [ChainStepInput(None, "persona", "", None)]
    state = ChainState(
        job_id=job_id, draft=draft, keyword=keyword, title=title,
        angle_directive=angle_directive, brand_facts=brand_facts,
        provider=provider, model=model, steps=eff,
    )
    if client is None:
        client = llm_factory.build_client(provider=provider, model=model)
    prev = ""
    for idx, step in enumerate(eff):
        checkpoint()
        system, user, input_text = _prompt_for(state, idx, prev)
        out = client.complete(system=system, user=user)
        p = ChainPass(index=idx, skill_id=step.skill_id, role=step.role,
                      skill_name=step.name, input=input_text, output=out)
        state.passes.append(p)
        on_pass(p)
        prev = out
    _cache_put(state)
    return state
```

- [ ] **Step 4: 跑测试确认通过** — `... -m pytest sidecar/tests/test_chain_service.py -v`。
- [ ] **Step 5: 提交** — `git commit -m "feat(chain): chain_service.run_chain（位置定职责 step0 组装/step1+ 精修 + LRU 缓存）"`

---

### Task A3：`chain_service.rerun`（逐 pass 重跑级联）

**Files:** Modify `sidecar/csm_sidecar/services/chain_service.py`；Test `sidecar/tests/test_chain_rerun.py`

- [ ] **Step 1: 写失败测试**

```python
import pytest
from csm_sidecar.services import chain_service


class SeqClient:
    def __init__(self, start=100): self.n = start
    def complete(self, *, system, user, temperature=None):
        self.n += 1; return f"R{self.n}"


def _run_two():
    chain_service.reset_for_test()
    from .test_chain_service import FakeClient, _steps  # reuse helpers
    c = FakeClient()
    chain_service.run_chain("j", _steps(("p","persona","人设","P"), ("h","humanize","去AI味","H")),
        draft="d", keyword="k", title=None, angle_directive=None, brand_facts=None,
        provider="mock", model=None, client=c, checkpoint=lambda: None, on_pass=lambda p: None)


def test_rerun_cascades_from_k(monkeypatch):
    _run_two()
    monkeypatch.setattr(chain_service.llm_factory, "build_client", lambda **k: SeqClient())
    res = chain_service.rerun("j", 1)            # 重跑 pass1（末段）
    assert res["passes"][1]["output"].startswith("R")
    assert res["final_text"] == res["passes"][-1]["output"]


def test_rerun_pass0_recascades_all(monkeypatch):
    _run_two()
    monkeypatch.setattr(chain_service.llm_factory, "build_client", lambda **k: SeqClient())
    res = chain_service.rerun("j", 0)            # 重跑 step0 → pass1 也跟着重跑
    assert res["passes"][0]["output"].startswith("R")
    assert res["passes"][1]["output"].startswith("R")  # 级联


def test_rerun_unknown_job():
    chain_service.reset_for_test()
    with pytest.raises(KeyError):
        chain_service.rerun("nope", 0)


def test_rerun_index_out_of_range():
    _run_two()
    with pytest.raises(IndexError):
        chain_service.rerun("j", 9)
```

- [ ] **Step 2: 跑测试确认失败**。

- [ ] **Step 3: 实现**（追加到 `chain_service.py`）

```python
def rerun(job_id: str, pass_index: int, *, client: Any | None = None) -> dict[str, Any]:
    """从 pass_index 起重跑（级联 pass_index..N），更新缓存，返回 {passes, final_text}。"""
    state = get_state(job_id)
    if state is None:
        raise KeyError(f"unknown job_id: {job_id} (chain cache miss)")
    if not (0 <= pass_index < len(state.passes)):
        raise IndexError(f"pass_index {pass_index} out of range (0..{len(state.passes)-1})")
    if client is None:
        client = llm_factory.build_client(provider=state.provider, model=state.model)
    # 末段之前的输出即 pass_index 的 prev（step0 的 prev 不参与，_prompt_for 自取 draft）
    prev = state.passes[pass_index - 1].output if pass_index >= 1 else ""
    for idx in range(pass_index, len(state.passes)):
        system, user, input_text = _prompt_for(state, idx, prev)
        out = client.complete(system=system, user=user)
        old = state.passes[idx]
        state.passes[idx] = ChainPass(
            index=idx, skill_id=old.skill_id, role=old.role,
            skill_name=old.skill_name, input=input_text, output=out)
        prev = out
    _cache_put(state)
    return {"passes": [p.to_dict() for p in state.passes], "final_text": state.final_text}
```

- [ ] **Step 4: 跑测试确认通过** — `... -m pytest sidecar/tests/test_chain_rerun.py sidecar/tests/test_chain_service.py -v`。
- [ ] **Step 5: 提交** — `git commit -m "feat(chain): chain_service.rerun（逐 pass 重跑级联 K..N）"`

> Unit A 收尾：`... -m pytest tests/core/llm sidecar/tests/test_chain_service.py sidecar/tests/test_chain_rerun.py -q` 全绿。

---

## Unit B — sidecar 接线 + 路由 + seed

### Task B1：generate_service 接链跑

**Files:** Modify `sidecar/csm_sidecar/services/generate_service.py`；Test `sidecar/tests/test_generate_chain.py`

- [ ] **Step 1: 写失败测试**（mock LLM；断言：传 skill_chain → run_chain 收到对应 steps；done 带 passes；单 skill_id（无 chain）→ 1 pass、final 同今天；blocked done 也带 passes）。

- [ ] **Step 2: 跑测试确认失败**。

- [ ] **Step 3: 实现**：
  - `GenerateRequest` 加 `skill_chain: list[str] | None = None`。
  - 新 `_resolve_chain(req, cfg) -> list[chain_service.ChainStepInput]`：

```python
def _resolve_chain(req: GenerateRequest, cfg) -> list:
    from . import chain_service
    sdir = Path(cfg.skill_dir) if cfg.skill_dir else None
    ids = req.skill_chain or ([req.skill_id] if req.skill_id else [])
    steps = []
    for sid in ids:
        skill = skills_service.get_skill(sdir, sid)
        if skill is None:
            logger.warning("skill_chain: 跳过失效 skill %s", sid)
            continue
        steps.append(chain_service.ChainStepInput(
            skill_id=sid, role=skill.role, name=skill.name, body=skill.body))
    return steps
```

  - 替换「调用 LLM」段单次 `build_prompt`+`complete` 为：

```python
        from . import chain_service
        _checkpoint(job_id)
        bus.publish(job_id, "stage", stage="skill 链润色", index=4, total=6)
        state = chain_service.run_chain(
            job_id, _resolve_chain(req, cfg),
            draft=draft, keyword=req.keyword, title=req.title,
            angle_directive=render_angle_directive(req.angle),
            brand_facts=brand_facts if cfg_bm.inject else None,
            provider=req.provider, model=req.model,
            checkpoint=lambda: _checkpoint(job_id),
            on_pass=lambda p: bus.publish(job_id, "pass", **p.to_dict()),
        )
        final_text = state.final_text
        passes = [p.to_dict() for p in state.passes]
```

  - `_maybe_block_for_factcheck(...)` 加 `passes` 参数，blocked `done` 带 `passes=passes`；成功 `done` 也加 `passes=passes`。
  - 删掉旧的单次 `client=...; system,user=build_prompt(...); final_text=client.complete(...)`（其语义已进 run_chain 的 step0）。

- [ ] **Step 4: 跑测试确认通过 + 回归** — `... -m pytest sidecar/tests -k "generate or chain or factcheck" -q`（含 Phase 2a 的 test_generate_angle 仍绿；单 skill 零回归）。
- [ ] **Step 5: 提交** — `git commit -m "feat(generate): 接 skill 链跑（skill_chain + run_chain + done.passes + 拦截带 passes）"`

---

### Task B2：`POST /api/chain/rerun` + GenerateBody + seed 平台 skill

**Files:** Modify `routes/generate.py`（GenerateBody）；Create `routes/chain.py`；Modify `main.py`（注册）；Create `examples/skills/小红书适配.md`；Test `sidecar/tests/test_routes_chain.py`

- [ ] **Step 1: 写失败测试**（rerun 200/404/400；generate 接 skill_chain）。

- [ ] **Step 2: 跑测试确认失败**。

- [ ] **Step 3: 实现**：
  - `GenerateBody` 加 `skill_chain: list[str] | None = None`（[generate.py:27](../../../sidecar/csm_sidecar/routes/generate.py)）；`start_generate` 的 `**body.model_dump()` 直接透传（list[str] 普通值，无对象坑）。
  - `routes/chain.py`：

```python
"""skill 链逐 pass 重跑端点。"""
from __future__ import annotations
from typing import Any
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from ..auth import RequireToken
from ..services import chain_service

router = APIRouter(tags=["chain"], dependencies=[RequireToken])


class ChainRerunBody(BaseModel):
    job_id: str = Field(min_length=1)
    pass_index: int = Field(ge=0)


@router.post("/api/chain/rerun")
def chain_rerun(body: ChainRerunBody) -> dict[str, Any]:
    """重跑 pass_index 并级联其后；返回更新后的 passes + final_text。
    404 未知 job（缓存淘汰/旧 job）；400 pass_index 越界。"""
    try:
        return chain_service.rerun(body.job_id, body.pass_index)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except IndexError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
```

  - `main.py`：`from .routes import chain as chain_routes` + `app.include_router(chain_routes.router)`（仿 assembler 注册处）。
  - `examples/skills/小红书适配.md`：

```markdown
---
name: 小红书适配
desc: 把成稿改写成小红书风格（口语、分点、钩子标题）
tone: casual
role: platform
---
请把正文改写成适合小红书发布的风格：开头一句强钩子；多用短句和口语；
适当分点/分段、加小标题；保留全部产品参数与认证不变；不堆砌 emoji（最多每段 0-1 个由用户后加）；
不使用绝对化用语。只输出改写后的正文。
```

- [ ] **Step 4: 跑测试确认通过** — `... -m pytest sidecar/tests/test_routes_chain.py -v` + 确认 `小红书适配` 被 `list_skills` 解析为 `role=platform`（可加一条断言）。
- [ ] **Step 5: 提交** — `git commit -m "feat(routes): POST /api/chain/rerun + GenerateBody.skill_chain + seed 小红书适配(platform)"`

> Unit B 收尾：`... -m pytest sidecar/tests -q`（角度/链/事实核对全绿 + 仅已知无关失败）。

---

## Unit C — 前端

### Task C1：store 接链 + passes + rerunPass

**Files:** Modify `frontend/src/stores/article.ts`；Test `frontend/src/stores/__tests__/article.chain.spec.ts`

- [ ] **Step 1: 写失败 Vitest**：`GenerateRequest` 含 `skill_chain?: string[]`；SSE `pass` 事件 push 到 `passes`；`done` 用 `d.passes` 覆盖；`rerunPass(i)` POST `/api/chain/rerun` 更新 `passes`+`finalText`；无 chain 时 submit 不带 skill_chain（零回归）。

- [ ] **Step 2: 跑测试确认失败**。

- [ ] **Step 3: 实现**：
  - `ChainPass` 类型 `{ index:number; role:string; skill_id:string|null; skill_name:string; output:string; input_chars:number; output_chars:number }`。
  - `GenerateRequest` 加 `skill_chain?: string[] | null`。
  - state 加 `passes: ChainPass[]`（submit 时清空）。
  - SSE `subscribe` handlers 加 `pass(d)` → `this.passes.push(d)`；`done(d)` → 若 `d.passes` 则 `this.passes = d.passes`（+ 现有 finalText 等）。
  - action `rerunPass(index)`：`POST /api/chain/rerun {job_id:lastJobId, pass_index:index}` → `this.passes = data.passes; this.finalText = data.final_text`；不抛（仿 resolveFactcheck）。
  - 成本 getter：`callCount = passes.length`；`totalChars = sum(output_chars)`。

- [ ] **Step 4: 跑测试确认通过** — `cd frontend; npx vitest run src/stores/__tests__/article.chain.spec.ts`。
- [ ] **Step 5: 提交** — `git commit -m "feat(article-store): skill_chain + passes(SSE) + rerunPass + 成本 getter"`

---

### Task C2：`SkillChainPicker.vue`（3 role 槽）

**Files:** Create `frontend/src/components/article/SkillChainPicker.vue`；Test `__tests__/SkillChainPicker.spec.ts`

- [ ] **Step 1: 写失败 Vitest**：mock skills（含 persona/humanize/platform 各若干）；3 槽各只列对应 role 的 skill + 空；选出的 skill 按 人设→去AI味→平台 顺序 emit `skill_chain`（跳过空槽）；全空 → emit `[]`。

- [ ] **Step 2: 跑测试确认失败**。

- [ ] **Step 3: 实现** `SkillChainPicker.vue`：props `modelValue: string[]`；emits `update:modelValue`。3 个 `FormSelect`（人设/去AI味/平台），options 来自 skills（按 `role` 分组：persona/humanize/platform + 空「不用」）。computed 产出有序 `skill_chain = [persona?, humanize?, platform?].filter(Boolean)`。skills 来源：复用现有 skills 列表加载（`/api/skills`，含 role 字段）。复用 `FormSelect`/`FormField`；teleport 测试加 `global:{stubs:{teleport:true}}`。

- [ ] **Step 4: 跑测试确认通过**。
- [ ] **Step 5: 提交** — `git commit -m "feat(chain-ui): SkillChainPicker 三 role 槽产出有序链"`

---

### Task C3：CreateArticleHero 链入口 + ArticleView 逐 pass

**Files:** Modify `frontend/src/components/home/CreateArticleHero.vue`、`frontend/src/views/ArticleView.vue`；Test 扩展其 spec。

- [ ] **Step 1: 写失败 Vitest**：Hero「风格」chip 打开 SkillChainPicker；`takeoff()` 把 `skill_chain` 进 query（逗号连，空则不带）。ArticleView 从 query 重建 `skill_chain` 入 submit；成稿区渲染 `passes`（每 pass 卡 + 「重跑此 pass」调 `rerunPass`）；header 显示链 chip；成本「调用 N 次 · 共 X 字」。

- [ ] **Step 2: 跑测试确认失败**。

- [ ] **Step 3: 实现**：
  - `CreateArticleHero`：「风格」chip → `SkillChainPicker`（popover/dialog）；`takeoff()` query 加 `skill_chain: arr.join(",")`（空省略）；兼容旧单 skill（若只选人设 = 单元素链）。
  - `ArticleView`：launch 从 `route.query.skill_chain` split `,` → `skill_chain` 入 `article.submit`；成稿 tab 渲染 `article.passes`（role+skill 名+输出折叠卡 + 「重跑此 pass」按钮 → `article.rerunPass(i)`）；header 链 chip（skill 名 `→` 连）；成本行 `调用 {{passes.length}} 次 · 共 {{totalChars}} 字`。
  - 无 passes（单 skill 旧路径）→ 成稿区行为不变（finalText 编辑器）。

- [ ] **Step 4: 跑测试确认通过 + 前端全跑** — `cd frontend; npx vitest run`（含既有，零回归）。
- [ ] **Step 5: 提交** — `git commit -m "feat(chain-ui): Hero 链入口 + ArticleView 逐 pass 预览/重跑/成本"`

---

### Task C4：SkillEditView 加「平台适配」role

**Files:** Modify `frontend/src/views/SkillEditView.vue`；Test 扩展其 spec。

- [ ] **Step 1: 写失败 Vitest**：role 下拉含 平台适配(platform)；create/edit 带 platform 能提交。

- [ ] **Step 2: 跑测试确认失败**。

- [ ] **Step 3: 实现** — `SkillEditView` 的 role `FormSelect` options 现 `人设(persona)/去AI味(humanize)` → 加 `平台适配(platform)`；其余逻辑（Plan 5b 已建 create+edit 带 role）不变。

- [ ] **Step 4: 跑测试确认通过**。
- [ ] **Step 5: 提交** — `git commit -m "feat(skill-ui): SkillEditView role 加平台适配(platform)"`

> Unit C 收尾：`cd frontend; npx vitest run` 全绿；`git status` 无 `package-lock.json`/node_modules 暂存。

---

## 最终整体审查（全 Unit 完成后）

派 opus code-reviewer 整体审查：① 单 skill / 无 chain 端到端 == 今天（build_prompt step0 字节级 + done 仍带 final_text + 无 passes 时成稿不变）；② 多步顺序喂 + factcheck 跑末段 + 拦截带 passes；③ 重跑级联正确 + 缓存淘汰 404；④ 链中 skill 失效跳过不中断；⑤ 前端 query 往返 + 逐 pass 重跑 update + 成本；⑥ `package-lock.json` 没把 `@esbuild/*` 裁进提交。+ 真实库回归（人设+去AI味 两段 vs 单段）。

---

## 自检（writing-plans 自审）
- **Spec 覆盖**：build_refine_prompt(A1)/run_chain+缓存(A2)/rerun(A3)/generate 接线+done.passes+拦截(B1)/路由+GenerateBody+seed(B2)/store(C1)/SkillChainPicker(C2)/Hero+ArticleView 逐pass(C3)/SkillEditView platform(C4) —— spec §2-§9 各条有任务。
- **占位符**：seed skill body 已给全文；无 TBD。
- **类型一致**：`ChainStepInput`/`ChainPass.to_dict()`/`ChainState.final_text`/`run_chain(...)`/`rerun(...)`/`build_refine_prompt`/`GenerateRequest.skill_chain`/SSE `pass` 形状 跨任务一致。
