# 交互式「整篇润色 = 成稿增强」实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把交互的「整篇润色」从 `polish_block` 单 skill 改写，升级为在用户审过的初稿上跑「型号事实注入 + 角度指令 + skill 链多-pass」→ 成稿，一次让 Phase 1/2a/2b 在交互流程真正可达。

**Architecture:** 抽 `_run_job` 的注入+链+事实核对段为共享 `finalize_draft`（`_run_job` 零回归）；新增 `POST /api/generate/{job_id}/finalize` 端点，复用 takeoff 的 `job_id` 重开 SSE 流、读缓存 plan、在前端编辑后的 `draftText` 上跑链；前端 `polishAll` 改接 store 新 `finalize()` action。复用同 job_id 让链状态/factcheck/重跑此 pass 自动同源。

**Tech Stack:** Python 3.12 / FastAPI / sse-starlette（sidecar）；Vue 3 + Pinia + TS + vitest（frontend）；pytest（后端）。

参考 spec：[2026-06-25-interactive-finalize-design.md](../specs/2026-06-25-interactive-finalize-design.md)。

---

## 文件结构

**Unit A（后端核心：抽 `finalize_draft`）**
- Modify: `sidecar/csm_sidecar/services/generate_service.py` — 加 `FinalizeOutcome` + `finalize_draft()`；`_run_job` 改调它。
- Test: `sidecar/tests/test_finalize_draft.py`（新）— 直接测 `finalize_draft`（回归基准/blocked/inject-off）。
- 现存 `sidecar/tests/test_generate_chain.py` 须保持全绿（证明 `_run_job` 零回归）。

**Unit B（后端端点：`submit_finalize` + 路由）**
- Modify: `sidecar/csm_sidecar/services/generate_service.py` — 加 `FinalizeRequest` + `submit_finalize()` + `_finalize_job()`。
- Modify: `sidecar/csm_sidecar/routes/generate.py` — 加 `FinalizeBody` + `POST /api/generate/{job_id}/finalize`。
- Test: `sidecar/tests/test_finalize_route.py`（新）— 404 / 202 capture / 422。
- Test: `sidecar/tests/test_finalize_job.py`（新）— `_finalize_job` 直驱（happy / 复用 job_id rerun / cancel）。

**Unit C（前端：store + ArticleView）**
- Modify: `frontend/src/stores/article.ts` — 抽 `_subscribe(jobId)`；加 `finalize()`；移除 `polishWhole`。
- Modify: `frontend/src/views/ArticleView.vue` — `polishAll` real 分支改接 `finalize`；按钮禁用条件。
- Test: `frontend/src/stores/__tests__/article.finalize.spec.ts`（新）。
- Test: `frontend/src/views/__tests__/ArticleView.finalize.spec.ts`（新）。

每 Unit 一个 PR，用户 merge 之间衔接。全部 opt-in / 零回归。

---

## Task A: 抽共享 `finalize_draft`（后端核心，`_run_job` 零回归）

**Files:**
- Modify: `sidecar/csm_sidecar/services/generate_service.py:206-273`
- Test: `sidecar/tests/test_finalize_draft.py`

- [ ] **Step 1: 写失败测试 `test_finalize_draft.py`**

```python
"""Task A: finalize_draft 抽取 —— 注入+链+事实核对的共享段。

直接测 finalize_draft（与 _run_job 解耦）：
- 干净路径返回 blocked=False + final_text + passes；
- inject=False → run_chain 收到 brand_facts=None；
- 事实核对拦下 → blocked=True 且 bus.finish 带 violations + passes。
_run_job 的零回归由现存 test_generate_chain.py 保证（不在此重复）。
"""
from __future__ import annotations

from pathlib import Path

from csm_core.assembler.plan import AssemblyPlan
from csm_core.brand_memory.inject import ModelScope
from csm_core.brand_memory.model import BrandModelMemory, SpecValue
from csm_core.config import AppConfig, BrandMemoryConfig
from csm_sidecar.services import chain_service, generate_service, factcheck_service


def _scope() -> ModelScope:
    mem = BrandModelMemory(
        brand="CEWEY", model="CEWEYDS18", category="吸尘器", role="主推",
        specs={"吸力(AW)": SpecValue(field="吸力(AW)", raw="220", numbers=[220.0])},
        certs=["CE"],
    )
    return ModelScope(brand="CEWEY", model="CEWEYDS18", role="主推", memory=mem)


class _StubClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def complete(self, *, system: str, user: str) -> str:
        self.calls.append((system, user))
        return "成稿：吸力220AW。"


def _wire(monkeypatch, tmp_path: Path, *, inject: bool, factcheck: bool):
    """Stub finalize_draft 的重依赖，返回截获字典 + 一个现成 cfg。"""
    captured: dict = {}
    chain_service.reset_for_test()
    factcheck_service.reset_for_test()

    cfg = AppConfig(
        vault_root=str(tmp_path / "vault"),
        out_dir=str(tmp_path / "out"),
        skill_dir=str(tmp_path / "skills"),
        brand_memory=BrandMemoryConfig(inject=inject, factcheck=factcheck),
    )
    monkeypatch.setattr(generate_service, "resolve_scopes", lambda *a, **k: [_scope()])
    monkeypatch.setattr(generate_service, "render_brand_facts", lambda scopes, **k: "品牌事实块")

    stub = _StubClient()
    monkeypatch.setattr(chain_service.llm_factory, "build_client", lambda **k: stub)
    captured["client"] = stub

    real_run_chain = chain_service.run_chain

    def spy_run_chain(job_id, steps, **kwargs):
        captured["run_chain_kwargs"] = kwargs
        return real_run_chain(job_id, steps, **kwargs)

    monkeypatch.setattr(generate_service.chain_service, "run_chain", spy_run_chain)

    monkeypatch.setattr(generate_service, "build_whitelist",
                        lambda scopes, *, source_texts: type("WL", (), {"numbers": set(), "certs": set()})())
    monkeypatch.setattr(generate_service, "check_facts",
                        lambda *a, **k: type("R", (), {"ok": True})())

    finish_calls: dict = {}
    monkeypatch.setattr(generate_service.bus, "finish",
                        lambda job_id, **d: finish_calls.update(d))
    events: list = []
    monkeypatch.setattr(generate_service.bus, "publish",
                        lambda job_id, kind, **d: events.append((kind, d)))
    captured["finish"] = finish_calls
    captured["events"] = events
    captured["cfg"] = cfg
    return captured


def _steps():
    return [chain_service.ChainStepInput(skill_id="人设", role="persona", name="克制理性", body="人设BODY")]


def test_finalize_draft_clean_returns_outcome(tmp_path: Path, monkeypatch):
    cap = _wire(monkeypatch, tmp_path, inject=True, factcheck=False)
    outcome = generate_service.finalize_draft(
        "job-clean",
        chain_steps=_steps(), draft="毛坯文",
        plan=AssemblyPlan(keyword="k", template_id="t", seed=0),
        index=object(), registry=object(), category="吸尘器",
        keyword="无线吸尘器", title=None, angle=None,
        provider=None, model=None,
        cfg=cap["cfg"], out_dir=tmp_path,
        checkpoint=lambda: None,
        on_pass=lambda p: cap["events"].append(("pass", p.to_dict())),
        stage_index=0, stage_total=1,
    )
    assert outcome.blocked is False
    assert outcome.final_text == "成稿：吸力220AW。"
    assert len(outcome.passes) == 1
    # inject=True → run_chain 收到 brand_facts
    assert cap["run_chain_kwargs"]["brand_facts"] == "品牌事实块"
    # stage 事件用传入的 index/total
    assert ("stage", {"stage": "skill 链润色", "index": 0, "total": 1}) in cap["events"]


def test_finalize_draft_inject_off_no_brand_facts(tmp_path: Path, monkeypatch):
    cap = _wire(monkeypatch, tmp_path, inject=False, factcheck=False)
    generate_service.finalize_draft(
        "job-noinject",
        chain_steps=_steps(), draft="毛坯文",
        plan=AssemblyPlan(keyword="k", template_id="t", seed=0),
        index=object(), registry=object(), category="吸尘器",
        keyword="k", title=None, angle=None, provider=None, model=None,
        cfg=cap["cfg"], out_dir=tmp_path,
        checkpoint=lambda: None, on_pass=lambda p: None,
        stage_index=4, stage_total=6,
    )
    assert cap["run_chain_kwargs"]["brand_facts"] is None


def test_finalize_draft_blocked_carries_passes(tmp_path: Path, monkeypatch):
    cap = _wire(monkeypatch, tmp_path, inject=True, factcheck=True)
    from csm_core.factcheck import Violation

    class _Report:
        ok = False
        violations = [Violation(kind="number", value="250AW", number=250.0,
                                sentence="句子", suggestion="建议")]

    monkeypatch.setattr(generate_service, "check_facts", lambda *a, **k: _Report())
    monkeypatch.setattr(generate_service.factcheck_service, "cache_pending", lambda *a, **k: None)

    outcome = generate_service.finalize_draft(
        "job-blocked",
        chain_steps=_steps(), draft="毛坯文",
        plan=AssemblyPlan(keyword="k", template_id="t", seed=0),
        index=object(), registry=object(), category="吸尘器",
        keyword="k", title=None, angle=None, provider=None, model=None,
        cfg=cap["cfg"], out_dir=tmp_path,
        checkpoint=lambda: None, on_pass=lambda p: None,
        stage_index=0, stage_total=1,
    )
    assert outcome.blocked is True
    fin = cap["finish"]
    assert fin["factcheck"]["blocked"] is True
    assert fin["document"] is None
    assert len(fin["passes"]) == 1
```

- [ ] **Step 2: 跑测试确认失败**

Run:
```
$env:PYTHONPATH="D:\CSM\.claude\worktrees\busy-matsumoto-c087bd;D:\CSM\.claude\worktrees\busy-matsumoto-c087bd\sidecar"; & "D:\CSM\.venv\Scripts\python.exe" -X utf8 -m pytest sidecar/tests/test_finalize_draft.py -v
```
Expected: FAIL — `AttributeError: module 'csm_sidecar.services.generate_service' has no attribute 'finalize_draft'`

- [ ] **Step 3: 实现 `FinalizeOutcome` + `finalize_draft`，`_run_job` 改调它**

在 `generate_service.py` 顶部（`GenerateRequest` dataclass 之后）加 `FinalizeOutcome`：

```python
@dataclass
class FinalizeOutcome:
    """finalize_draft 的产出。blocked=True 时 bus 已 finish(blocked-done)，
    调用方须停下不导出。"""
    final_text: str
    passes: list[dict[str, Any]]
    blocked: bool
```

加 `finalize_draft`（放在 `_run_job` 之后、`_resolve_chain` 之前）：

```python
def finalize_draft(
    job_id: str, *,
    chain_steps: list["chain_service.ChainStepInput"],
    draft: str,
    plan: Any, index: Any, registry: Any, category: str | None,
    keyword: str, title: str | None, angle: Angle | None,
    provider: str | None, model: str | None,
    cfg: Any, out_dir: Path,
    checkpoint, on_pass,
    stage_index: int, stage_total: int,
) -> FinalizeOutcome:
    """毛坯 → 成稿：注入型号事实 + 角度指令 + skill 链多-pass + 导出前事实核对。

    _run_job（完整生成）与 _finalize_job（交互整篇润色）共用。命中事实核对
    越界时本函数已发 done(blocked)，返回 blocked=True 让调用方停下。
    """
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
            brand_facts = render_brand_facts(
                scopes,
                variant_cap=cfg_bm.inject_variant_cap,
                endorsement_cap=cfg_bm.inject_endorsement_cap,
                sellpoints=effective_sellpoints(angle),
            )

    checkpoint()
    bus.publish(job_id, "stage", stage="skill 链润色", index=stage_index, total=stage_total)
    state = chain_service.run_chain(
        job_id, chain_steps,
        draft=draft, keyword=keyword, title=title,
        angle_directive=render_angle_directive(angle),
        brand_facts=brand_facts if cfg_bm.inject else None,
        provider=provider, model=model,
        checkpoint=checkpoint, on_pass=on_pass,
    )
    final_text = state.final_text
    passes = [p.to_dict() for p in state.passes]

    if _maybe_block_for_factcheck(
        job_id, final_text=final_text, scopes=scopes, draft=draft,
        brand_facts=brand_facts if cfg_bm.inject else None,
        title=title, cfg=cfg, plan=plan, out_dir=out_dir, passes=passes,
    ):
        return FinalizeOutcome(final_text=final_text, passes=passes, blocked=True)
    return FinalizeOutcome(final_text=final_text, passes=passes, blocked=False)
```

把 `_run_job` 的行 206-252 替换为对 `finalize_draft` 的调用。替换后 `_run_job` 该段为：

```python
        outcome = finalize_draft(
            job_id,
            chain_steps=chain_steps, draft=draft,
            plan=plan, index=index, registry=registry, category=template.product,
            keyword=req.keyword, title=req.title, angle=req.angle,
            provider=req.provider, model=req.model,
            cfg=cfg, out_dir=out_dir,
            checkpoint=lambda: _checkpoint(job_id),
            on_pass=lambda p: bus.publish(job_id, "pass", **p.to_dict()),
            stage_index=4, stage_total=6,
        )
        if outcome.blocked:
            return
        final_text = outcome.final_text

        bus.publish(job_id, "stage", stage="导出", index=5, total=6)
        out_dir.mkdir(parents=True, exist_ok=True)
        paths = export_article(
            out_dir=out_dir,
            keyword=req.keyword,
            final_text=final_text,
            plan=plan,
            fmt=cfg.export_format,
        )

        bus.finish(
            job_id,
            document=paths["document"],
            format=paths["format"],
            title=paths["title"],
            plan=_plan_to_dict(plan),
            draft=draft,
            final_text=final_text,
            passes=outcome.passes,
        )
```

注：删去原 `cfg_bm = cfg.brand_memory` / `scopes` / `brand_facts` / `state` / `passes` 等局部变量（已搬进 `finalize_draft`）；导出段改用 `outcome.passes`。`stage_index=4, stage_total=6` 复刻原 `bus.publish("stage","skill 链润色",4,6)`，零回归。

- [ ] **Step 4: 跑测试确认通过（新测试 + _run_job 回归）**

Run:
```
$env:PYTHONPATH="D:\CSM\.claude\worktrees\busy-matsumoto-c087bd;D:\CSM\.claude\worktrees\busy-matsumoto-c087bd\sidecar"; & "D:\CSM\.venv\Scripts\python.exe" -X utf8 -m pytest sidecar/tests/test_finalize_draft.py sidecar/tests/test_generate_chain.py sidecar/tests/test_generate_factcheck_gate.py sidecar/tests/test_generate_angle.py -v
```
Expected: PASS（全部）。`test_generate_chain.py` 全绿 = `_run_job` 零回归。

- [ ] **Step 5: Commit**

```bash
git add sidecar/csm_sidecar/services/generate_service.py sidecar/tests/test_finalize_draft.py
git commit -m "feat(finalize): 抽 finalize_draft 共享段（_run_job 零回归）

注入+skill链+事实核对从 _run_job 抽为 finalize_draft，供交互整篇润色复用。
_run_job 传 stage_index=4/total=6 复刻原 stage 事件，行为字节级等价。

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task B: finalize 端点 + worker（后端）

**Files:**
- Modify: `sidecar/csm_sidecar/services/generate_service.py`（加 `FinalizeRequest` + `submit_finalize` + `_finalize_job`）
- Modify: `sidecar/csm_sidecar/routes/generate.py`（加 `FinalizeBody` + 路由）
- Test: `sidecar/tests/test_finalize_route.py`、`sidecar/tests/test_finalize_job.py`

- [ ] **Step 1: 写失败测试 `test_finalize_route.py`**

```python
"""Task B: POST /api/generate/{job_id}/finalize 路由。

- 缓存 plan 缺失 → 404；
- 缓存 plan 命中 → 202，submit_finalize 收到重建的 FinalizeRequest（angle 单传）；
- 缺 draft / keyword → 422。
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from csm_sidecar.services import assembler_service, generate_service


def test_finalize_404_when_no_cached_plan(client: TestClient):
    assembler_service.reset_for_test()
    resp = client.post("/api/generate/nope/finalize",
                       json={"draft": "毛坯", "keyword": "k"})
    assert resp.status_code == 404


def test_finalize_202_and_passes_request(client: TestClient, monkeypatch):
    # 缓存 plan 命中
    monkeypatch.setattr(assembler_service, "get_plan",
                        lambda job_id: type("E", (), {"plan": object(), "template_id": "t", "seed": 0})())
    captured: dict = {}
    monkeypatch.setattr(generate_service, "submit_finalize",
                        lambda job_id, req: captured.update(job_id=job_id, req=req) or job_id)
    body = {
        "draft": "用户编辑后的初稿",
        "keyword": "无线吸尘器",
        "title": "无线吸尘器哪款好？",
        "angle": {"audience": "铲屎官", "sellpoints": ["防缠绕技术"], "tone": "口语"},
        "skill_chain": ["人设", "去味"],
    }
    resp = client.post("/api/generate/job-A/finalize", json=body)
    assert resp.status_code == 202
    assert resp.json()["job_id"] == "job-A"
    req = captured["req"]
    assert req.draft == "用户编辑后的初稿"
    assert req.keyword == "无线吸尘器"
    assert req.title == "无线吸尘器哪款好？"
    assert req.skill_chain == ["人设", "去味"]
    # angle 被重建为 Angle 对象（非 dict）
    assert req.angle.audience == "铲屎官"
    assert req.angle.sellpoints == ["防缠绕技术"]


def test_finalize_422_missing_draft(client: TestClient, monkeypatch):
    monkeypatch.setattr(assembler_service, "get_plan",
                        lambda job_id: type("E", (), {"plan": object(), "template_id": "t", "seed": 0})())
    resp = client.post("/api/generate/job-A/finalize", json={"keyword": "k"})
    assert resp.status_code == 422
```

- [ ] **Step 2: 跑测试确认失败**

Run:
```
$env:PYTHONPATH="D:\CSM\.claude\worktrees\busy-matsumoto-c087bd;D:\CSM\.claude\worktrees\busy-matsumoto-c087bd\sidecar"; & "D:\CSM\.venv\Scripts\python.exe" -X utf8 -m pytest sidecar/tests/test_finalize_route.py -v
```
Expected: FAIL — 404 路由不存在（返回 404 但因 route 未注册非因 plan-miss；其余 case 因 submit_finalize 不存在而 fail）。

- [ ] **Step 3: 实现 `FinalizeRequest` + `submit_finalize` + `_finalize_job`**

在 `generate_service.py` 加 dataclass（`GenerateRequest` 之后）：

```python
@dataclass
class FinalizeRequest:
    """交互整篇润色入参。draft = 用户审/编辑后的初稿；plan 从缓存取。"""
    draft: str
    keyword: str
    title: str | None = None
    angle: Angle | None = None
    skill_id: str | None = None
    skill_chain: list[str] | None = None
    provider: str | None = None
    model: str | None = None
```

加 `submit_finalize` + `_finalize_job`（放在 `submit` / `_run_job` 之后）：

```python
def submit_finalize(job_id: str, req: FinalizeRequest) -> str:
    """在既有 takeoff job_id 上重开一条流，提交 finalize worker。
    调用方（路由）须先确认缓存 plan 存在（否则 404）。"""
    bus.create_job(job_id)
    with _state_lock:
        _live.add(job_id)
    _get_executor().submit(_finalize_job, job_id, req)
    return job_id


def _finalize_job(job_id: str, req: FinalizeRequest) -> None:
    """整篇润色 worker：缓存 plan + 编辑后 draft → 注入+角度+链 → 成稿（不导出）。"""
    try:
        cfg = config_service.load()
        if not cfg.vault_root:
            raise ValueError("AppConfig.vault_root is unset")
        if not cfg.out_dir:
            raise ValueError("AppConfig.out_dir is unset")
        vault_root = Path(cfg.vault_root)
        out_dir = Path(cfg.out_dir)

        entry = assembler_service.get_plan(job_id)
        if entry is None:
            raise FileNotFoundError(f"plan cache miss: {job_id}")
        plan = entry.plan

        tpl_path = templates_service.resolve_dir() / f"{entry.template_id}.json"
        if not tpl_path.exists():
            raise FileNotFoundError(f"template not found: {entry.template_id}")
        template = load_template(tpl_path)

        # 新鲜 scan + registry（与 _run_job 一致；takeoff 走 scan_vault 直调、
        # 不写 vault_service._index，故不复用 cached，重扫保证 scopes 命中型号）。
        _checkpoint(job_id)
        index = scan_vault(vault_root)
        registry = build_brand_registry(vault_root)

        chain_steps = _resolve_chain(req, cfg)

        _checkpoint(job_id)
        outcome = finalize_draft(
            job_id,
            chain_steps=chain_steps, draft=req.draft,
            plan=plan, index=index, registry=registry, category=template.product,
            keyword=req.keyword, title=req.title, angle=req.angle,
            provider=req.provider, model=req.model,
            cfg=cfg, out_dir=out_dir,
            checkpoint=lambda: _checkpoint(job_id),
            on_pass=lambda p: bus.publish(job_id, "pass", **p.to_dict()),
            stage_index=0, stage_total=1,
        )
        if outcome.blocked:
            return  # finalize_draft 已发 blocked-done

        bus.finish(
            job_id,
            document=None,
            plan=_plan_to_dict(plan),
            draft=req.draft,
            final_text=outcome.final_text,
            passes=outcome.passes,
        )
    except _CancelledGenerate:
        logger.info("finalize job %s cancelled by user", job_id)
        bus.fail(job_id, error="cancelled", cancelled=True)
    except Exception as e:
        logger.exception("finalize job %s failed", job_id)
        bus.fail(job_id, error=f"{type(e).__name__}: {e}")
    finally:
        with _state_lock:
            _live.discard(job_id)
            _cancelled.discard(job_id)
```

注：`_resolve_chain(req, cfg)` 现签名读 `req.skill_chain` / `req.skill_id`；`FinalizeRequest` 同字段名，直接复用无需改 `_resolve_chain`。

在 `routes/generate.py` 加 `FinalizeBody` + 路由（`resolve_factcheck` 之后），并在文件顶部 import 处加 `assembler_service`：

```python
from ..services import assembler_service, factcheck_service, generate_service
```

```python
class FinalizeBody(BaseModel):
    draft: str = Field(min_length=1)
    keyword: str = Field(min_length=1)
    title: str | None = None
    angle: Angle | None = None
    skill_id: str | None = None
    skill_chain: list[str] | None = None
    provider: str | None = None
    model: str | None = None


@router.post("/api/generate/{job_id}/finalize", response_model=JobAccepted, status_code=202)
def finalize_generate(job_id: str, body: FinalizeBody) -> JobAccepted:
    """在 takeoff 初稿基础上跑「注入+角度+链」成稿。复用 job_id 重开流。
    缓存 plan 已淘汰 / job_id 未知 → 404（前端提示重新起飞）。"""
    if assembler_service.get_plan(job_id) is None:
        raise HTTPException(status_code=404, detail=f"plan cache miss: {job_id}")
    req = generate_service.FinalizeRequest(
        **body.model_dump(exclude={"angle"}), angle=body.angle,
    )
    generate_service.submit_finalize(job_id, req)
    return JobAccepted(job_id=job_id, stream_url=f"/api/events/{job_id}")
```

- [ ] **Step 4: 跑路由测试确认通过**

Run:
```
$env:PYTHONPATH="D:\CSM\.claude\worktrees\busy-matsumoto-c087bd;D:\CSM\.claude\worktrees\busy-matsumoto-c087bd\sidecar"; & "D:\CSM\.venv\Scripts\python.exe" -X utf8 -m pytest sidecar/tests/test_finalize_route.py -v
```
Expected: PASS（3 个）。

- [ ] **Step 5: 写失败测试 `test_finalize_job.py`（worker 直驱）**

```python
"""Task B: _finalize_job worker 直驱。

- happy：bus.finish 带 final_text + passes + document=None；
- 复用 job_id：finalize 后 chain_service.rerun(job_id, 0) 命中（链状态同 id 缓存）；
- cancel：预置取消 → bus.fail(cancelled)。
"""
from __future__ import annotations

from pathlib import Path

from csm_core.assembler.plan import AssemblyPlan
from csm_core.config import AppConfig, BrandMemoryConfig
from csm_sidecar.services import chain_service, generate_service, factcheck_service, skills_service


class _Seq:
    """确定性序列 client —— 每次 complete 自增，便于断言 rerun 改写。"""
    def __init__(self, start: int = 0) -> None:
        self.n = start

    def complete(self, *, system, user, temperature=None) -> str:
        self.n += 1
        return f"OUT[{self.n}]"


def _Skill(skill_id: str, *, role: str, name: str, body: str):
    return skills_service.Skill(
        id=skill_id, name=name, desc="", tone="", role=role,
        path=Path(f"{skill_id}.md"), body=body,
    )


def _wire(monkeypatch, tmp_path: Path, *, skills: dict, client):
    """Stub _finalize_job 的重依赖（含缓存 plan）。返回截获字典。"""
    chain_service.reset_for_test()
    factcheck_service.reset_for_test()

    cfg = AppConfig(
        vault_root=str(tmp_path / "vault"),
        out_dir=str(tmp_path / "out"),
        skill_dir=str(tmp_path / "skills"),
        brand_memory=BrandMemoryConfig(inject=False, factcheck=False),
    )
    monkeypatch.setattr(generate_service.config_service, "load", lambda: cfg)
    monkeypatch.setattr(generate_service.templates_service, "resolve_dir", lambda: tmp_path)
    (tmp_path / "t.json").write_text("{}", encoding="utf-8")

    plan = AssemblyPlan(keyword="无线吸尘器", template_id="t", seed=0)
    monkeypatch.setattr(generate_service.assembler_service, "get_plan",
                        lambda job_id: type("E", (), {"plan": plan, "template_id": "t", "seed": 0})())
    monkeypatch.setattr(generate_service, "scan_vault", lambda root: object())
    monkeypatch.setattr(generate_service, "build_brand_registry", lambda root: object())
    monkeypatch.setattr(generate_service, "load_template",
                        lambda p: type("T", (), {"product": "吸尘器"})())
    monkeypatch.setattr(generate_service.skills_service, "get_skill",
                        lambda sdir, sid: skills.get(sid))

    monkeypatch.setattr(chain_service.llm_factory, "build_client", lambda **k: client)

    finish_calls: dict = {}
    monkeypatch.setattr(generate_service.bus, "finish", lambda job_id, **d: finish_calls.update(d))
    fail_calls: dict = {}
    monkeypatch.setattr(generate_service.bus, "fail", lambda job_id, **d: fail_calls.update(d, error=d.get("error")))
    events: list = []
    monkeypatch.setattr(generate_service.bus, "publish", lambda job_id, kind, **d: events.append((kind, d)))
    # create_job 真实调用无妨（bus 是单例）；这里不 stub。
    return {"finish": finish_calls, "fail": fail_calls, "events": events}


def test_finalize_job_happy(tmp_path: Path, monkeypatch):
    skills = {"人设": _Skill("人设", role="persona", name="克制理性", body="人设BODY")}
    cap = _wire(monkeypatch, tmp_path, skills=skills, client=_Seq())
    req = generate_service.FinalizeRequest(
        draft="用户编辑后的初稿", keyword="无线吸尘器", skill_chain=["人设"],
    )
    generate_service._finalize_job("job-fin", req)

    fin = cap["finish"]
    assert fin["document"] is None
    assert fin["final_text"] == "OUT[1]"
    assert len(fin["passes"]) == 1
    assert fin["passes"][0]["role"] == "persona"
    assert fin["draft"] == "用户编辑后的初稿"
    # pass SSE 事件发出
    assert any(k == "pass" for k, _ in cap["events"])


def test_finalize_job_reuses_job_id_for_rerun(tmp_path: Path, monkeypatch):
    """finalize 后链状态缓存于同 job_id → rerun 命中（证明复用 job_id 正确）。"""
    skills = {"人设": _Skill("人设", role="persona", name="克制理性", body="B")}
    _wire(monkeypatch, tmp_path, skills=skills, client=_Seq())
    req = generate_service.FinalizeRequest(draft="初稿", keyword="k", skill_chain=["人设"])
    generate_service._finalize_job("job-reuse", req)
    # rerun 用新 client → 输出变化，证明状态在 job-reuse 下可寻
    monkeypatch.setattr(chain_service.llm_factory, "build_client", lambda **k: _Seq(start=50))
    res = chain_service.rerun("job-reuse", 0)
    assert res["passes"][0]["output"] == "OUT[51]"
    assert res["final_text"] == res["passes"][-1]["output"]


def test_finalize_job_cancel(tmp_path: Path, monkeypatch):
    skills = {"人设": _Skill("人设", role="persona", name="克制理性", body="B")}
    cap = _wire(monkeypatch, tmp_path, skills=skills, client=_Seq())
    # 预置取消：worker 第一个 _checkpoint 即命中
    with generate_service._state_lock:
        generate_service._cancelled.add("job-cancel")
    req = generate_service.FinalizeRequest(draft="初稿", keyword="k", skill_chain=["人设"])
    generate_service._finalize_job("job-cancel", req)
    assert cap["fail"].get("cancelled") is True
    assert "finish" not in cap or not cap["finish"]
```

- [ ] **Step 6: 跑 worker 测试确认通过**

Run:
```
$env:PYTHONPATH="D:\CSM\.claude\worktrees\busy-matsumoto-c087bd;D:\CSM\.claude\worktrees\busy-matsumoto-c087bd\sidecar"; & "D:\CSM\.venv\Scripts\python.exe" -X utf8 -m pytest sidecar/tests/test_finalize_job.py sidecar/tests/test_finalize_route.py -v
```
Expected: PASS（全部）。

- [ ] **Step 7: 跑后端全量回归（确认零回归）**

Run:
```
$env:PYTHONPATH="D:\CSM\.claude\worktrees\busy-matsumoto-c087bd;D:\CSM\.claude\worktrees\busy-matsumoto-c087bd\sidecar"; & "D:\CSM\.venv\Scripts\python.exe" -X utf8 -m pytest sidecar/tests/test_generate_chain.py sidecar/tests/test_chain_rerun.py sidecar/tests/test_routes_chain.py sidecar/tests/test_generate_cancel.py sidecar/tests/test_generate_factcheck_gate.py sidecar/tests/test_generate_factcheck_route.py -v
```
Expected: PASS。（已知无关失败见 spec 备注，不在此列表内。）

- [ ] **Step 8: Commit**

```bash
git add sidecar/csm_sidecar/services/generate_service.py sidecar/csm_sidecar/routes/generate.py sidecar/tests/test_finalize_route.py sidecar/tests/test_finalize_job.py
git commit -m "feat(finalize): POST /api/generate/{job_id}/finalize 端点 + worker

复用 takeoff job_id 重开 SSE 流、读缓存 plan、在编辑后 draft 上跑链成稿。
缓存 plan 缺失 404；链状态/factcheck/重跑此 pass 自动同源（同 job_id）。

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task C: 前端 `polishAll` 改接 finalize（store + ArticleView）

**Files:**
- Modify: `frontend/src/stores/article.ts`（抽 `_subscribe`、加 `finalize`、删 `polishWhole`）
- Modify: `frontend/src/views/ArticleView.vue:403-430`（`polishAll` real 分支）
- Test: `frontend/src/stores/__tests__/article.finalize.spec.ts`、`frontend/src/views/__tests__/ArticleView.finalize.spec.ts`

- [ ] **Step 1: 写失败测试 `article.finalize.spec.ts`**

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

/** 模拟 takeoff 完成后的 store 态：lastJobId + lastRequest + 已编辑 draftText。 */
function seedAfterTakeoff(a: ReturnType<typeof useArticle>) {
  a.lastJobId = "job-A";
  a.lastRequest = {
    keyword: "无线吸尘器",
    template_id: "tpl-a",
    title: "无线吸尘器哪款好？",
    angle: { audience: "铲屎官", sellpoints: ["防缠绕技术"], tone: "口语" },
    skill_chain: ["人设", "去味"],
    provider: "deepseek",
    model: "deepseek-chat",
  } as any;
  a.draftText = "用户编辑后的初稿";
}

describe("article store — finalize（整篇润色=成稿增强）", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    postMock.mockReset();
    getMock.mockReset();
    getMock.mockResolvedValue({ data: {} });
    sseHandlers = {};
  });

  it("finalize POSTs /api/generate/{lastJobId}/finalize，draft 取 draftText、其余取 lastRequest", async () => {
    postMock.mockResolvedValueOnce({ data: { job_id: "job-A" } });
    const a = useArticle();
    seedAfterTakeoff(a);
    await a.finalize();
    expect(postMock).toHaveBeenCalledWith("/api/generate/job-A/finalize", {
      draft: "用户编辑后的初稿",
      keyword: "无线吸尘器",
      title: "无线吸尘器哪款好？",
      angle: { audience: "铲屎官", sellpoints: ["防缠绕技术"], tone: "口语" },
      skill_id: null,
      skill_chain: ["人设", "去味"],
      provider: "deepseek",
      model: "deepseek-chat",
    });
  });

  it("finalize 守卫：无 lastJobId / lastRequest / draftText 时不 POST", async () => {
    const a = useArticle();
    await a.finalize();                       // 全空
    expect(postMock).not.toHaveBeenCalled();
    a.lastJobId = "job-A";
    a.lastRequest = { keyword: "k", template_id: "t" } as any;
    a.draftText = "   ";                       // 空白
    await a.finalize();
    expect(postMock).not.toHaveBeenCalled();
  });

  it("SSE pass → passes 增量；done → finalText + status done", async () => {
    postMock.mockResolvedValueOnce({ data: { job_id: "job-A" } });
    const a = useArticle();
    seedAfterTakeoff(a);
    await a.finalize();
    expect(a.status).toBe("running");
    sseHandlers.pass({ index: 0, role: "persona", skill_id: "人设", skill_name: "克制理性", output: "A", input_chars: 1, output_chars: 1 });
    sseHandlers.pass({ index: 1, role: "humanize", skill_id: "去味", skill_name: "去AI味", output: "B", input_chars: 1, output_chars: 1 });
    expect(a.passes.map((p) => p.output)).toEqual(["A", "B"]);
    sseHandlers.done({ final_text: "成稿正文", passes: a.passes, document: null, draft: "用户编辑后的初稿", title: "T" });
    expect(a.finalText).toBe("成稿正文");
    expect(a.status).toBe("done");
  });

  it("finalize 轻 reset：保留 draftText（链输入），重置 finalText/passes", async () => {
    postMock.mockResolvedValueOnce({ data: { job_id: "job-A" } });
    const a = useArticle();
    seedAfterTakeoff(a);
    a.finalText = "旧成稿";
    a.passes = [{ index: 0, role: "persona", skill_id: "x", skill_name: "x", output: "old", input_chars: 1, output_chars: 1 }];
    await a.finalize();
    expect(a.draftText).toBe("用户编辑后的初稿");  // 保留
    expect(a.finalText).toBe("");                  // 重置
    expect(a.passes).toEqual([]);                  // 重置
  });

  it("finalize POST 失败 → status error，不抛", async () => {
    postMock.mockRejectedValueOnce({ response: { data: { detail: "plan cache miss" } } });
    const a = useArticle();
    seedAfterTakeoff(a);
    await expect(a.finalize()).resolves.toBeUndefined();
    expect(a.status).toBe("error");
    expect(a.error).toBe("plan cache miss");
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run:
```
cd frontend; npx vitest run src/stores/__tests__/article.finalize.spec.ts
```
Expected: FAIL — `a.finalize is not a function`。

- [ ] **Step 3: 实现 store `_subscribe` + `finalize`，删 `polishWhole`**

在 `article.ts` 的 `submit()` 里，把 `this.stop = subscribe(...)` 整段（行 216-286）抽成私有方法 `_subscribe(jobId)`，`submit()` 末尾改为 `this._subscribe(this.jobId!)`。`_subscribe` 签名与体：

```ts
    /** 订阅一个 job 的 SSE 流，装配 stage/assembly/pass/done/error 处理。
     * submit（完整生成 draft_only）与 finalize（整篇润色）共用同一套 handler。 */
    _subscribe(jobId: string) {
      this.stop = subscribe(`/api/events/${jobId}`, {
        stage: (d: any) => {
          this.currentStage = d.stage;
          if (typeof d.index === "number") {
            this.stageIndex = d.index;
          } else {
            const i = STAGES.indexOf(d.stage);
            if (i >= 0) this.stageIndex = i;
          }
        },
        assembly: (d: any) => {
          this.plan = d.plan ?? null;
          this.draftText = d.draft ?? "";
        },
        pass: (d: any) => {
          this.passes.push(d as ChainPass);
        },
        done: (d: any) => {
          this.documentPath = d.document ?? null;
          this.format = d.format ?? null;
          this.title = d.title ?? this.title;
          this.finalText = d.final_text ?? "";
          this.draftText = d.draft ?? "";
          this.plan = d.plan ?? null;
          if (Array.isArray(d.passes)) this.passes = d.passes as ChainPass[];
          this.factcheck =
            d.factcheck && d.factcheck.blocked
              ? { blocked: true, violations: d.factcheck.violations ?? [] }
              : null;
          this.stageIndex = STAGES.length;
          this.status = "done";
          useNotifications().push("文章生成完成", {
            body: this.title,
            tone: "success",
            category: "article_success",
          });
          this._teardown();
        },
        error: (d: any) => {
          if (d?.cancelled) {
            this.status = "idle";
            this.error = null;
            this._teardown();
            return;
          }
          this.error = d.error ?? "unknown error";
          this.status = "error";
          useNotifications().push("文章生成失败", {
            body: this.error ?? "",
            tone: "error",
            category: "article_failure",
          });
          this._teardown();
        },
      });
    },
```

`submit()` 行 216 起替换为：

```ts
      this._subscribe(this.jobId!);
```

加 `finalize()` action（放在 `polishWhole` 原位置，并删掉 `polishWhole`）：

```ts
    /** 整篇润色 = 在用户审过的初稿（draftText）上跑「注入+角度+链」成稿。
     * 复用 takeoff 的 lastJobId 重开同 id 的 SSE 流（链状态/factcheck/重跑此
     * pass 自动同源）。轻 reset：保留 draftText（链输入）/plan/lastRequest。
     * 守卫：未起飞（无 lastJobId/lastRequest）或初稿为空 → 直接 return（demo
     * 模式由 ArticleView 处理，不调本函数）。从不抛。 */
    async finalize(): Promise<void> {
      if (!this.lastJobId || !this.lastRequest || !this.draftText.trim()) return;
      this._teardown();
      this.status = "running";
      this.error = null;
      this.currentStage = null;
      this.stageIndex = -1;
      this.finalText = "";
      this.passes = [];
      this.factcheck = null;

      const sidecar = useSidecar();
      const req = this.lastRequest;
      try {
        const resp = await sidecar.client.post(
          `/api/generate/${this.lastJobId}/finalize`,
          {
            draft: this.draftText,
            keyword: req.keyword,
            title: req.title ?? null,
            angle: req.angle ?? null,
            skill_id: req.skill_id ?? null,
            skill_chain: req.skill_chain ?? null,
            provider: req.provider ?? null,
            model: req.model ?? null,
          },
        );
        this.jobId = resp.data.job_id;   // == lastJobId
      } catch (e: any) {
        this.status = "error";
        this.error = e?.response?.data?.detail ?? e?.message ?? String(e);
        return;
      }
      this._subscribe(this.jobId!);
    },
```

（删除原 `polishWhole(text)` 方法整段——仅 `polishAll` 调用，下一步改接 finalize。`/api/polish/block` 端点保留，SettingsView ping 仍用。）

- [ ] **Step 4: 跑 store 测试确认通过 + 链测试回归**

Run:
```
cd frontend; npx vitest run src/stores/__tests__/article.finalize.spec.ts src/stores/__tests__/article.chain.spec.ts src/stores/__tests__/article.spec.ts
```
Expected: PASS（全部）。`article.chain.spec.ts`/`article.spec.ts` 全绿 = `submit`/`_subscribe` 抽取零回归。

- [ ] **Step 5: 写失败测试 `ArticleView.finalize.spec.ts`**

```ts
import { mount, flushPromises } from "@vue/test-utils";
import { setActivePinia, createPinia } from "pinia";
import { describe, it, expect, vi, beforeEach, beforeAll } from "vitest";

beforeAll(() => {
  vi.stubGlobal("matchMedia", (q: string) => ({
    matches: true, media: q,
    addEventListener() {}, removeEventListener() {},
    addListener() {}, removeListener() {},
    onchange: null, dispatchEvent() { return false; },
  }));
});

let routeQuery: Record<string, any> = {};
vi.mock("vue-router", () => ({
  useRoute: () => ({ query: routeQuery }),
  useRouter: () => ({ push: vi.fn() }),
}));
const postMock = vi.fn();
const getMock = vi.fn();
vi.mock("@/stores/sidecar", () => ({
  useSidecar: () => ({ client: { post: postMock, get: getMock }, ready: true, error: null, mode: "native" }),
}));
vi.mock("@/api/client", () => ({ subscribe: () => () => {} }));
vi.mock("@/composables/useNotifications", () => ({ useNotifications: () => ({ push: vi.fn() }) }));
vi.mock("@/composables/useSidecarReady", () => ({
  useSidecarReady: () => ({ whenReady: () => Promise.resolve(), ready: { value: true } }),
}));
const toastSuccess = vi.fn();
vi.mock("@/composables/useToast", () => ({
  useToast: () => ({ success: toastSuccess, error: vi.fn(), warn: vi.fn(), info: vi.fn() }),
}));
vi.mock("@/composables/useFailureAlert", () => ({ failureAlert: vi.fn().mockResolvedValue("close") }));
vi.mock("@/stores/config", () => ({ useConfig: () => ({ data: { user_name: "测试" }, load: vi.fn() }) }));
vi.mock("@/components/article/TiptapEditor.vue", () => ({ default: { name: "TiptapEditor", template: "<div />" } }));
vi.mock("@/components/article/FactCheckPanel.vue", () => ({ default: { name: "FactCheckPanel", template: "<div />" } }));

import ArticleView from "@/views/ArticleView.vue";
import { useArticle } from "@/stores/article";

describe("ArticleView — 整篇润色接 finalize", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    postMock.mockReset();
    postMock.mockResolvedValue({ data: { job_id: "j1" } });
    getMock.mockReset();
    getMock.mockResolvedValue({ data: {} });
    toastSuccess.mockReset();
    routeQuery = {};
  });

  it("real 模式 polishAll → 调 article.finalize（不再调 polishWhole/polish_block）", async () => {
    routeQuery = { keyword: "k", template_id: "tpl-a" };
    const w = mount(ArticleView, { global: { stubs: { teleport: true } } });
    await flushPromises();
    const a = useArticle();
    const spy = vi.spyOn(a, "finalize").mockResolvedValue(undefined);
    a.lastRequest = { keyword: "k", template_id: "tpl-a" } as any;
    a.lastJobId = "job-A";
    a.draftText = "初稿正文";
    a.status = "done";
    a.finalText = "成稿";        // 让 polishAll 后置判断切 tab

    await (w.vm as any).polishAll();
    expect(spy).toHaveBeenCalled();
  });

  it("demo 模式（无 lastRequest）polishAll → 不调 finalize（走假弹窗）", async () => {
    routeQuery = {};
    const w = mount(ArticleView, { global: { stubs: { teleport: true } } });
    await flushPromises();
    const a = useArticle();
    const spy = vi.spyOn(a, "finalize").mockResolvedValue(undefined);
    // 不设 lastRequest → isDemoMode；real 分支被跳过，finalize 永不调用。
    // demo 分支跑 setInterval 假动画 → 用 fake timers 同步推进，避免实时等待。
    vi.useFakeTimers();
    const p = (w.vm as any).polishAll();
    expect(spy).not.toHaveBeenCalled();   // 同步即可判定（real 分支已跳过）
    await vi.runAllTimersAsync();
    await p;
    vi.useRealTimers();
    expect(spy).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 6: 跑测试确认失败**

Run:
```
cd frontend; npx vitest run src/views/__tests__/ArticleView.finalize.spec.ts
```
Expected: FAIL — `polishAll` 仍调 `polishWhole`，`finalize` spy 未被调用。

- [ ] **Step 7: 实现 `ArticleView.polishAll` real 分支改接 finalize**

把 `ArticleView.vue` `polishAll()` 的 real 分支（行 409-430）替换为：

```ts
  if (article.lastRequest && article.draftText.trim()) {
    // 真实模式：整篇润色 = finalize（注入型号事实 + 角度指令 + skill 链多-pass）。
    // SSE 驱动逐 pass，进度由 store.passes / status 呈现；本地 polishing 仅作
    // 按钮去抖。结果 finalText 由 store done handler 写入。
    try {
      await article.finalize();
      if (article.status === "done" && article.finalText) {
        activeTab.value = "final";
        toast.success("整篇润色完成");
      } else if (article.status === "error") {
        toast.error(article.error ?? "整篇润色失败");
      }
      // factcheck 被拦：status=done 但有 article.factcheck → 审查面板接管，不切 tab
    } finally {
      polishing.value = false;
      polishProgress.value = 0;
      polishStage.value = "";
    }
    return;
  }
```

按钮禁用：把模板里整篇润色按钮（行 2153 附近 `@click="polishAll"`）的 `:disabled` 由 `polishing` 改为 `polishing || article.isRunning`（finalize 期间 status=running）。若该按钮当前无 `:disabled`，加上 `:disabled="polishing || article.isRunning"`。

- [ ] **Step 8: 跑 view 测试 + 全前端链/view 回归**

Run:
```
cd frontend; npx vitest run src/views/__tests__/ArticleView.finalize.spec.ts src/views/__tests__/ArticleView.chain.spec.ts src/views/__tests__/ArticleView.angle.spec.ts
```
Expected: PASS（全部）。

- [ ] **Step 9: Commit**

```bash
git add frontend/src/stores/article.ts frontend/src/views/ArticleView.vue frontend/src/stores/__tests__/article.finalize.spec.ts frontend/src/views/__tests__/ArticleView.finalize.spec.ts
git commit -m "feat(finalize): 前端整篇润色改接 finalize（注入+角度+链可达）

store 抽 _subscribe 共享 SSE handler + 加 finalize()（复用 lastJobId 重开流、
轻 reset 保 draftText）；删 polishWhole；ArticleView.polishAll real 分支改调
finalize。Phase 1/2a/2b 在交互里真正生效。

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## 自审清单（writing-plans 自检）

**Spec 覆盖：**
- §5.1 抽 `finalize_draft` → Task A ✓
- §5.2 `submit_finalize`/`_finalize_job` → Task B Step 3 ✓
- §5.3 端点 404+202 → Task B Step 1/3 ✓
- §5.4 复用 job_id 不变式（rerun 同源）→ Task B Step 5 复用测试 ✓；cancel → Task B cancel 测试 ✓
- §6.1 store `_subscribe`+`finalize` → Task C Step 3 ✓
- §6.2 `polishAll` 改接 → Task C Step 7 ✓
- §6.3 删 `polishWhole` / 留 `polish_block` → Task C Step 3（删）+ 未触碰端点（留）✓
- §7 决策 D=① 一律 finalize → real 分支无条件 `finalize()`，纯净场景退化单 step0 build_prompt（由 Task A `finalize_draft` 行为保证）✓
- §8 零回归 → `_run_job` stage_index=4/6 + 现存 test_generate_chain 回归（Task A Step 4）+ submit/_subscribe 抽取回归（Task C Step 4）✓

**占位扫描：** 每步含完整代码 + 实测命令 + 期望输出，无 TBD/TODO。

**类型一致性：** `FinalizeOutcome{final_text,passes,blocked}`、`FinalizeRequest{draft,keyword,title,angle,skill_id,skill_chain,provider,model}`、`finalize_draft(...)` 签名、store `finalize()`/`_subscribe(jobId)` 全程一致；`_resolve_chain(req,cfg)` 复用（字段名对齐）。

---

## 执行方式

转 subagent-driven-development：每 Task 一个 implementer subagent + 两段审查（spec 合规 → 代码质量），Task 间 controller 审。每 Task 收尾即一个 PR，用户 merge 之间衔接。三 Task 全过后，最终综合审查 + 真实库回归（按惯例）。
```
