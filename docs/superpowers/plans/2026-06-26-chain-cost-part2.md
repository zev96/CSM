# Part 2：skill 链流式异步重跑 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把「重跑此 pass」从同步阻塞（`POST /api/chain/rerun` 200 等完）改为异步 SSE 流式——逐 pass 实时刷新 + 可取消，仿 finalize 的 EventBus 模式、复用 job_id。

**Architecture:** `chain_service.rerun` 加 `on_pass`/`checkpoint` 回调（同步签名保留、默认 no-op = 零回归）；`generate_service.submit_rerun`/`_rerun_job` 复用 `bus.create_job(job_id)`+`_live`/`_checkpoint` 异步跑、done 带 cost；`POST /api/chain/rerun` 契约 200→202（404/400 同步前置校验）；前端 `rerunPass` 改流式轻量订阅（pass 按 index 替换、可取消、从不抛）。

**Tech Stack:** Python 3.12 / FastAPI / sse-starlette；Vue 3 + Pinia + TS + vitest；pytest。

参考 spec：[2026-06-26-chain-cost-streaming-rerun-design.md](../specs/2026-06-26-chain-cost-streaming-rerun-design.md) §5。Part 1（成本）已 merge（PR#144）。

---

## 文件结构

**Unit A（后端核心：rerun 流式 + worker）**
- Modify: `sidecar/csm_sidecar/services/chain_service.py:136-156`（`rerun` 加 `on_pass`/`checkpoint`）
- Modify: `sidecar/csm_sidecar/services/generate_service.py`（`submit_rerun` + `_rerun_job`）
- Test: `sidecar/tests/test_chain_rerun.py`（加 on_pass/checkpoint 用例）、`sidecar/tests/test_rerun_stream.py`（新，worker 直驱）

**Unit B（路由契约 200→202）**
- Modify: `sidecar/csm_sidecar/routes/chain.py`（202 + 同步 404/400 + submit_rerun）
- Test: `sidecar/tests/test_routes_chain.py`（rerun 用例 200→202 改写）

**Unit C（前端流式 rerunPass + 取消）**
- Modify: `frontend/src/stores/article.ts`（`rerunPass` 流式 + `rerunningIndex`/`_rerunStop`/`cancelRerun`）
- Modify: `frontend/src/views/ArticleView.vue`（pass 卡重跑中 loading + 取消按钮）
- Test: `frontend/src/stores/__tests__/article.chain.spec.ts` + `article.cost.spec.ts`（rerunPass 用例改流式）、新 `frontend/src/stores/__tests__/article.rerun-stream.spec.ts`

三 Unit 合**一个 PR**（流式重跑是一个完整特性）。Unit 间 subagent 双审，最后整 Part 一个 PR。

---

## Task A: rerun 流式回调 + 异步 worker

**Files:**
- Modify: `chain_service.py`、`generate_service.py`
- Test: `test_chain_rerun.py`、`test_rerun_stream.py`

- [ ] **Step 1: 写失败测试（rerun 回调）—— 加到 `test_chain_rerun.py` 末尾**

```python
def test_rerun_on_pass_per_pass(fake_chain_client, chain_steps):
    _run_two(fake_chain_client, chain_steps)
    seen = []
    from csm_sidecar.services import chain_service as cs
    import csm_sidecar.services.llm_factory as lf
    class _Seq:
        def __init__(self): self.n = 0
        def complete(self, *, system, user, temperature=None):
            self.n += 1; return f"R{self.n}"
    cs.rerun("j", 0, client=_Seq(), on_pass=lambda p: seen.append(p.index))
    assert seen == [0, 1]  # 从 pass0 级联 → 两段都回调，按序


def test_rerun_checkpoint_cancels(fake_chain_client, chain_steps):
    _run_two(fake_chain_client, chain_steps)
    from csm_sidecar.services import chain_service as cs

    class _Boom:
        def __call__(self): raise RuntimeError("cancelled-here")
    import pytest
    with pytest.raises(RuntimeError, match="cancelled-here"):
        cs.rerun("j", 0, client=type("C", (), {
            "complete": staticmethod(lambda *, system, user, temperature=None: "x")})(),
            checkpoint=_Boom())
```

- [ ] **Step 2: 跑确认失败**

Run:
```
$env:PYTHONPATH="D:\CSM\.claude\worktrees\busy-matsumoto-c087bd;D:\CSM\.claude\worktrees\busy-matsumoto-c087bd\sidecar"; & "D:\CSM\.venv\Scripts\python.exe" -X utf8 -m pytest sidecar/tests/test_chain_rerun.py -v
```
Expected: FAIL — `rerun()` 不接 `on_pass`/`checkpoint`（TypeError unexpected keyword）。

- [ ] **Step 3: `chain_service.rerun` 加 `on_pass`/`checkpoint`**

`rerun`（行 136-156）改为：
```python
def rerun(
    job_id: str, pass_index: int, *, client: Any | None = None,
    checkpoint: Callable[[], None] = lambda: None,
    on_pass: Callable[[ChainPass], None] = lambda p: None,
) -> dict[str, Any]:
    """从 pass_index 起重跑（级联 pass_index..N），更新缓存，返回 {passes, final_text}。

    on_pass 逐段回调（流式）；checkpoint 每段前调（可取消）。两者默认 no-op =
    同步调用零回归。"""
    state = get_state(job_id)
    if state is None:
        raise KeyError(f"unknown job_id: {job_id} (chain cache miss)")
    if not (0 <= pass_index < len(state.passes)):
        raise IndexError(f"pass_index {pass_index} out of range (0..{len(state.passes)-1})")
    if client is None:
        client = llm_factory.build_client(provider=state.provider, model=state.model)
    prev = state.passes[pass_index - 1].output if pass_index >= 1 else ""
    for idx in range(pass_index, len(state.passes)):
        checkpoint()
        system, user, input_text = _prompt_for(state, idx, prev)
        out = client.complete(system=system, user=user)
        old = state.passes[idx]
        p = ChainPass(
            index=idx, skill_id=old.skill_id, role=old.role,
            skill_name=old.skill_name, input=input_text, output=out)
        state.passes[idx] = p
        on_pass(p)
        prev = out
    _cache_put(state)
    return {"passes": [p.to_dict() for p in state.passes], "final_text": state.final_text}
```

- [ ] **Step 4: 跑 rerun 回调测试 + 现有 rerun 回归**

Run:
```
$env:PYTHONPATH="...;...\sidecar"; & "D:\CSM\.venv\Scripts\python.exe" -X utf8 -m pytest sidecar/tests/test_chain_rerun.py -v
```
Expected: PASS（新 2 个 + 现有 4 个同步用例零回归——默认 no-op 不变行为）。

- [ ] **Step 5: 写失败测试 `sidecar/tests/test_rerun_stream.py`（worker 直驱）**

```python
"""Part 2 Unit A: _rerun_job 异步 worker（流式 + 取消 + cost）。"""
from __future__ import annotations

from csm_sidecar.services import chain_service, generate_service


def _seed(job_id: str, client):
    chain_service.reset_for_test()
    steps = [
        chain_service.ChainStepInput(skill_id="p", role="persona", name="人设", body="P"),
        chain_service.ChainStepInput(skill_id="h", role="humanize", name="去AI味", body="H"),
    ]
    chain_service.run_chain(
        job_id, steps, draft="d", keyword="k", title=None, angle_directive=None,
        brand_facts=None, provider="mock", model="deepseek-chat", client=client,
        checkpoint=lambda: None, on_pass=lambda p: None,
    )


class _Seq:
    def __init__(self, start=0): self.n = start
    def complete(self, *, system, user, temperature=None):
        self.n += 1; return f"R{self.n}"


def _wire_bus(monkeypatch):
    events: list = []
    finish: dict = {}
    fail: dict = {}
    monkeypatch.setattr(generate_service.bus, "publish", lambda j, kind, **d: events.append((kind, d)))
    monkeypatch.setattr(generate_service.bus, "finish", lambda j, **d: finish.update(d))
    monkeypatch.setattr(generate_service.bus, "fail", lambda j, **d: fail.update(d, error=d.get("error")))
    monkeypatch.setattr(generate_service.bus, "create_job", lambda j=None: j)
    monkeypatch.setattr(chain_service.llm_factory, "build_client", lambda **k: _Seq(start=50))
    return {"events": events, "finish": finish, "fail": fail}


def test_rerun_job_streams_and_finishes_with_cost(monkeypatch):
    _seed("job-rr", _Seq())
    cap = _wire_bus(monkeypatch)
    generate_service._rerun_job("job-rr", 0)
    # 逐 pass 事件（级联 0..1 → 2 条 pass）
    pass_idx = [d["index"] for k, d in cap["events"] if k == "pass"]
    assert pass_idx == [0, 1]
    fin = cap["finish"]
    assert len(fin["passes"]) == 2
    assert fin["final_text"] == fin["passes"][-1]["output"]
    # cost：model=deepseek-chat（链缓存）有默认价 → cost 非 None
    assert fin["cost"]["currency"] == "CNY" and fin["cost"]["cost"] is not None


def test_rerun_job_cancel(monkeypatch):
    _seed("job-rrc", _Seq())
    cap = _wire_bus(monkeypatch)
    with generate_service._state_lock:
        generate_service._cancelled.add("job-rrc")
    generate_service._rerun_job("job-rrc", 0)
    assert cap["fail"].get("cancelled") is True
    assert not cap["finish"]


def test_rerun_job_cache_miss(monkeypatch):
    chain_service.reset_for_test()
    cap = _wire_bus(monkeypatch)
    generate_service._rerun_job("nope", 0)
    assert "cache miss" in cap["fail"].get("error", "") or "KeyError" in cap["fail"].get("error", "")
```

- [ ] **Step 6: 实现 `submit_rerun` + `_rerun_job`**

`generate_service.py`（`submit_finalize`/`_finalize_job` 之后）加：
```python
def submit_rerun(job_id: str, pass_index: int) -> str:
    """在既有链 job_id 上重开一条流，提交 rerun worker（复用 job_id：链状态/cost
    /取消都按同 id 同源）。调用方（路由）须先同步校验 job 存在 + pass_index 合法。"""
    bus.create_job(job_id)
    with _state_lock:
        _cancelled.discard(job_id)
        _live.add(job_id)
    _get_executor().submit(_rerun_job, job_id, pass_index)
    return job_id


def _rerun_job(job_id: str, pass_index: int) -> None:
    """rerun worker：从 pass_index 级联重跑，逐 pass 经 SSE 推，done 带 passes
    + final_text + cost。复用 chain_service.rerun（流式回调）。"""
    try:
        cfg = config_service.load()
        res = chain_service.rerun(
            job_id, pass_index,
            checkpoint=lambda: _checkpoint(job_id),
            on_pass=lambda p: bus.publish(job_id, "pass", **p.to_dict()),
        )
        state = chain_service.get_state(job_id)
        model = _effective_model(
            state.model if state else None,
            state.provider if state else None, cfg) if state else None
        cost = pricing.chain_cost(res["passes"], model, cfg.pricing)
        bus.finish(job_id, passes=res["passes"], final_text=res["final_text"], cost=cost)
    except _CancelledGenerate:
        logger.info("rerun job %s cancelled by user", job_id)
        bus.fail(job_id, error="cancelled", cancelled=True)
    except (KeyError, IndexError) as e:
        # 缓存淘汰 / 越界（路由已同步前置校验，这里是竞态兜底）。
        bus.fail(job_id, error=f"{type(e).__name__}: {e}")
    except Exception as e:
        logger.exception("rerun job %s failed", job_id)
        bus.fail(job_id, error=f"{type(e).__name__}: {e}")
    finally:
        with _state_lock:
            _live.discard(job_id)
            _cancelled.discard(job_id)
```

- [ ] **Step 7: 跑 worker 测试 + 后端回归**

Run:
```
$env:PYTHONPATH="...;...\sidecar"; & "D:\CSM\.venv\Scripts\python.exe" -X utf8 -m pytest sidecar/tests/test_rerun_stream.py sidecar/tests/test_chain_rerun.py sidecar/tests/test_finalize_job.py sidecar/tests/test_generate_cancel.py -v
```
Expected: PASS（worker 3 + rerun 6 + finalize/cancel 回归）。

- [ ] **Step 8: Commit**

```bash
git add sidecar/csm_sidecar/services/chain_service.py sidecar/csm_sidecar/services/generate_service.py sidecar/tests/test_chain_rerun.py sidecar/tests/test_rerun_stream.py
git commit -m "feat(rerun): chain_service.rerun 流式回调 + submit_rerun/_rerun_job 异步 worker

rerun 加 on_pass/checkpoint（默认 no-op 零回归）；submit_rerun/_rerun_job 仿
finalize 复用 job_id 异步跑、逐 pass SSE、done 带 cost、支持取消。

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task B: 路由契约 200→202

**Files:**
- Modify: `sidecar/csm_sidecar/routes/chain.py`
- Test: `sidecar/tests/test_routes_chain.py`

- [ ] **Step 1: 改写 `test_routes_chain.py` 的 rerun 用例（200→202）**

把现有 `test_rerun_200_returns_passes_and_final` 改为 202 + submit 校验；404/400/422 保留语义：
```python
def test_rerun_202_accepts_and_submits(client: TestClient, monkeypatch):
    _seed_chain("j-ok")
    captured: dict = {}
    monkeypatch.setattr(generate_service, "submit_rerun",
                        lambda job_id, pass_index: captured.update(job_id=job_id, idx=pass_index) or job_id)
    resp = client.post("/api/chain/rerun", json={"job_id": "j-ok", "pass_index": 1})
    assert resp.status_code == 202
    data = resp.json()
    assert data["job_id"] == "j-ok"
    assert data["stream_url"] == "/api/events/j-ok"
    assert captured == {"job_id": "j-ok", "idx": 1}


def test_rerun_404_unknown_job(client: TestClient):
    chain_service.reset_for_test()
    resp = client.post("/api/chain/rerun", json={"job_id": "nope", "pass_index": 0})
    assert resp.status_code == 404


def test_rerun_400_index_out_of_range(client: TestClient):
    _seed_chain("j-oor")
    resp = client.post("/api/chain/rerun", json={"job_id": "j-oor", "pass_index": 9})
    assert resp.status_code == 400


def test_rerun_422_negative_index(client: TestClient):
    resp = client.post("/api/chain/rerun", json={"job_id": "x", "pass_index": -1})
    assert resp.status_code == 422
```
（删掉 Part 1 的 `data["cost"]` 断言——cost 现在走 SSE done 不在 202 响应里。`generate_service` 须在 test 顶部 import。`_seed_chain` 现有 helper 保留。）

- [ ] **Step 2: 跑确认失败**

Run:
```
$env:PYTHONPATH="...;...\sidecar"; & "D:\CSM\.venv\Scripts\python.exe" -X utf8 -m pytest sidecar/tests/test_routes_chain.py -v
```
Expected: FAIL — 现路由返回 200（Part 1）+ 算 cost，新测试期望 202 + submit_rerun。

- [ ] **Step 3: 路由改 202**

`routes/chain.py` 改为（去掉 Part 1 的 cost 计算 + pricing/config_service import，加 generate_service）：
```python
"""skill 链逐 pass 重跑端点（异步流式：202 + SSE，仿 generate/finalize）。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..auth import RequireToken
from ..services import chain_service, generate_service

router = APIRouter(tags=["chain"], dependencies=[RequireToken])


class ChainRerunBody(BaseModel):
    job_id: str = Field(min_length=1)
    pass_index: int = Field(ge=0)


@router.post("/api/chain/rerun", status_code=202)
def chain_rerun(body: ChainRerunBody) -> dict[str, Any]:
    """从 pass_index 起级联重跑，异步流式。返回 {job_id, stream_url}，逐 pass 经
    SSE `pass` 推、`done` 带 passes+final_text+cost。

    404 未知 job（缓存淘汰 / 旧 job）；400 pass_index 越界 —— 均同步前置校验
    （worker 异步无法回 HTTP 码）。"""
    state = chain_service.get_state(body.job_id)
    if state is None:
        raise HTTPException(status_code=404, detail=f"chain cache miss: {body.job_id}")
    if not (0 <= body.pass_index < len(state.passes)):
        raise HTTPException(
            status_code=400,
            detail=f"pass_index {body.pass_index} out of range (0..{len(state.passes)-1})")
    generate_service.submit_rerun(body.job_id, body.pass_index)
    return {"job_id": body.job_id, "stream_url": f"/api/events/{body.job_id}"}
```

- [ ] **Step 4: 跑路由测试 + 回归**

Run:
```
$env:PYTHONPATH="...;...\sidecar"; & "D:\CSM\.venv\Scripts\python.exe" -X utf8 -m pytest sidecar/tests/test_routes_chain.py sidecar/tests/test_rerun_stream.py -v
```
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add sidecar/csm_sidecar/routes/chain.py sidecar/tests/test_routes_chain.py
git commit -m "feat(rerun): POST /api/chain/rerun 契约 200→202 异步流式

同步前置校验 404（cache miss）/400（越界）后 submit_rerun + 返回 stream_url；
cost 移到 SSE done（_rerun_job 算）。

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task C: 前端流式 rerunPass + 取消

**Files:**
- Modify: `frontend/src/stores/article.ts`、`frontend/src/views/ArticleView.vue`
- Test: `article.chain.spec.ts`、`article.cost.spec.ts`、新 `article.rerun-stream.spec.ts`

- [ ] **Step 1: 写失败测试 `frontend/src/stores/__tests__/article.rerun-stream.spec.ts`**

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

import { useArticle, type ChainPass } from "@/stores/article";

function mkPass(i: number, out: string): ChainPass {
  return { index: i, role: "persona", skill_id: "p", skill_name: "x", output: out, input_chars: 1, output_chars: 1 };
}

describe("article store — 流式重跑", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    postMock.mockReset(); getMock.mockReset(); getMock.mockResolvedValue({ data: {} });
    sseHandlers = {};
  });

  it("rerunPass POST 后订阅 SSE，pass 事件按 index 替换、done 覆盖+cost", async () => {
    const a = useArticle();
    a.lastJobId = "j1";
    a.passes = [mkPass(0, "A"), mkPass(1, "B")];
    postMock.mockResolvedValueOnce({ data: { job_id: "j1", stream_url: "/api/events/j1" } });
    await a.rerunPass(0);
    expect(postMock).toHaveBeenCalledWith("/api/chain/rerun", { job_id: "j1", pass_index: 0 });
    expect(a.rerunningIndex).toBe(0);
    // SSE 逐 pass 替换
    sseHandlers.pass(mkPass(0, "A2"));
    expect(a.passes[0].output).toBe("A2");
    sseHandlers.pass(mkPass(1, "B2"));
    expect(a.passes[1].output).toBe("B2");
    // done 覆盖 + cost + 清 rerunningIndex
    sseHandlers.done({ passes: [mkPass(0, "A2"), mkPass(1, "B2")], final_text: "B2",
      cost: { input_tokens: 5, output_tokens: 5, cost: 0.001, currency: "CNY" } });
    expect(a.finalText).toBe("B2");
    expect(a.cost?.cost).toBe(0.001);
    expect(a.rerunningIndex).toBeNull();
  });

  it("rerunPass POST 失败 → rerunningIndex 清空，从不抛", async () => {
    const a = useArticle();
    a.lastJobId = "j2";
    postMock.mockRejectedValueOnce(new Error("boom"));
    await expect(a.rerunPass(0)).resolves.toBeUndefined();
    expect(a.rerunningIndex).toBeNull();
  });

  it("无 lastJobId → 不 POST", async () => {
    const a = useArticle();
    await a.rerunPass(0);
    expect(postMock).not.toHaveBeenCalled();
  });

  it("cancelRerun POSTs /cancel", async () => {
    const a = useArticle();
    a.lastJobId = "j3"; a.rerunningIndex = 1;
    postMock.mockResolvedValueOnce({ data: {} });
    await a.cancelRerun();
    expect(postMock).toHaveBeenCalledWith("/api/generate/j3/cancel");
  });
});
```

- [ ] **Step 2: 跑确认失败**

Run:
```
cd D:\CSM\.claude\worktrees\busy-matsumoto-c087bd\frontend; npx vitest run src/stores/__tests__/article.rerun-stream.spec.ts
```
Expected: FAIL（`rerunningIndex`/`cancelRerun` 不存在 + rerunPass 仍同步）。

- [ ] **Step 3: store `rerunPass` 改流式 + `rerunningIndex`/`cancelRerun`**

`ArticleState` 加 `rerunningIndex: number | null;`；`state()` 初值 `rerunningIndex: null,`。加私有 `_rerunStop: (() => void) | null` —— 但 Pinia state 不放函数，改用模块级或 action 内闭包。**简化**：复用现有 `this.stop` 机制不行（rerun 与 generate 流独立）。用一个 **action 外的模块级变量**存 teardown：

```ts
// article.ts 文件顶部（store 定义外）
let _rerunStop: (() => void) | null = null;
function _teardownRerun() {
  if (_rerunStop) { try { _rerunStop(); } catch { /* ignore */ } _rerunStop = null; }
}
```

`rerunPass` 重写：
```ts
    /** 重跑链上第 `index` 个 pass —— 异步流式（POST→202→订阅 SSE）。后端从该
     * pass 级联其后所有 pass，逐 pass 经 SSE `pass` 实时替换 passes[index]，
     * `done` 覆盖全量 + cost。轻量订阅（不碰 status/通知/tab）。从不抛。 */
    async rerunPass(index: number): Promise<void> {
      if (!this.lastJobId) return;
      _teardownRerun();
      this.rerunningIndex = index;
      const sidecar = useSidecar();
      let jobId: string;
      try {
        const resp = await sidecar.client.post("/api/chain/rerun", {
          job_id: this.lastJobId, pass_index: index,
        });
        jobId = resp.data.job_id;
      } catch {
        this.rerunningIndex = null;  // 404/400/网络 静默
        return;
      }
      _rerunStop = subscribe(`/api/events/${jobId}`, {
        pass: (d: any) => { this.passes[d.index] = d as ChainPass; },
        done: (d: any) => {
          if (Array.isArray(d.passes)) this.passes = d.passes as ChainPass[];
          if (d.cost) this.cost = d.cost as ChainCost;
          if (typeof d.final_text === "string") this.finalText = d.final_text;
          this.rerunningIndex = null;
          _teardownRerun();
        },
        error: () => { this.rerunningIndex = null; _teardownRerun(); },  // 含 cancelled，静默
      });
    },
    /** 取消进行中的重跑（复用 generate 的协作式取消端点，对 _live 里的同 job 生效）。
     * 从不抛；真正收尾由 SSE error(cancelled) → 上面 error handler 清 rerunningIndex。 */
    async cancelRerun(): Promise<void> {
      if (this.lastJobId == null || this.rerunningIndex == null) return;
      const sidecar = useSidecar();
      try { await sidecar.client.post(`/api/generate/${this.lastJobId}/cancel`); }
      catch { /* 网络异常 —— 事件流自会收尾 */ }
    },
```
（`subscribe` 已在 article.ts import；`ChainPass`/`ChainCost` 已有。）

- [ ] **Step 4: 跑 store 测试 + 更新旧 rerun 用例**

`article.chain.spec.ts` 的 `rerunPass POSTs /api/chain/rerun 并更新 passes + finalText` + `rerunPass 从不抛` 两个用例是**旧同步契约**（断言 `resp.data.passes` 直接覆盖）。改为流式：POST 返回 `{job_id}`，再 `sseHandlers.done({passes, final_text})` 才覆盖。参照 `article.rerun-stream.spec.ts` 改写这两个用例（或删除、由新 spec 覆盖——但保留「从不抛」语义）。`article.cost.spec.ts` 的 `rerunPass 成功带 cost` 用例同样改流式（POST→done(cost)）。

Run:
```
cd ...\frontend; npx vitest run src/stores/__tests__/article.rerun-stream.spec.ts src/stores/__tests__/article.chain.spec.ts src/stores/__tests__/article.cost.spec.ts src/stores/__tests__/article.finalize.spec.ts
```
Expected: PASS（新流式 spec + 改写后的 chain/cost rerun 用例 + finalize 回归）。

- [ ] **Step 5: ArticleView pass 卡——重跑中 loading + 取消按钮**

pass 卡（`v-for="p in article.passes"`，约行 1506）的「重跑此 pass」按钮区：`article.rerunningIndex === p.index` 时显示 spinner + 「取消」按钮（点 `article.cancelRerun()`），其它 pass 的重跑按钮在有重跑进行时禁用（`article.rerunningIndex != null`）。读当前按钮 markup（`data-rerun-pass`）按实际结构改：重跑中那张卡按钮换成 `<Spinner> + 取消`，调 `cancelRerun`；非重跑态显示原「重跑此 pass」调 `rerunPass(p.index)`。

- [ ] **Step 6: 跑 view 测试**

Run:
```
cd ...\frontend; npx vitest run src/views/__tests__/ArticleView.chain.spec.ts
```
Expected: PASS。`ArticleView.chain.spec.ts` 的「点重跑此 pass 调 rerunPass(i)」用例若因按钮结构变化失败，更新选择器/断言（保留「点击触发 rerunPass(i)」意图）。

- [ ] **Step 7: 本地 vue-tsc 类型检查（PR 前必跑——vitest 不查类型）**

Run:
```
cd D:\CSM\.claude\worktrees\busy-matsumoto-c087bd\frontend; npx vue-tsc -b
```
Expected: exit 0。**若 emit 了 `vite.config.js`/`.d.ts` 杂散文件，`git checkout -- frontend/vite.config.js frontend/vite.config.d.ts` 还原。**

- [ ] **Step 8: Commit**

```bash
git add frontend/src/stores/article.ts frontend/src/views/ArticleView.vue frontend/src/stores/__tests__/article.rerun-stream.spec.ts frontend/src/stores/__tests__/article.chain.spec.ts frontend/src/stores/__tests__/article.cost.spec.ts
git commit -m "feat(rerun): 前端 rerunPass 改流式 + 逐 pass 实时 + 可取消

POST→202→订阅 SSE：pass 按 index 实时替换、done 覆盖+cost；rerunningIndex
驱动 pass 卡 loading+取消按钮；cancelRerun 复用协作式取消端点。从不抛。

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## 自审清单

**Spec 覆盖：** §5.1 rerun 流式→Task A Step3 ✓；§5.2 submit_rerun/_rerun_job→Task A Step6 ✓；§5.3 路由 200→202→Task B ✓；§5.4 前端 rerunPass 流式+取消→Task C ✓。

**占位扫描：** 各步含完整代码/命令/期望。Task C Step4/5/6 的旧用例改写是「按实际结构改 + 保留意图」的明确指令（旧契约变更必然要改测试）。

**类型一致：** `rerun(..., checkpoint, on_pass)` / `submit_rerun(job_id, pass_index)` / `_rerun_job` / 路由 `{job_id, stream_url}` / 前端 `rerunningIndex`/`cancelRerun`/`_teardownRerun` 全程一致；`_effective_model` 复用 Part 1。

**零回归：** `rerun` 同步签名保留（默认 no-op）→ `test_chain_rerun.py` 现有同步用例不变；`run_chain` 不动；契约变更（200→202）显式更新 routes_chain + article.chain/cost rerun 用例（预期变更非回归）；前端 generate/finalize 流不受影响（rerun 用独立 `_rerunStop`）。

---

## 执行方式

转 subagent-driven-development：每 Task 一 implementer + 两段审查（spec 合规→代码质量），Task 间 controller 审。三 Task 合**一个 PR**。**PR 前必跑 `vue-tsc -b`（Part 1 栽过：vitest 绿 ≠ 类型对）。**
