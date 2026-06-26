# skill 链增强：成本透明 + 流式重跑 设计 spec

> 状态：设计已拍板（A 后端算成本 / B CJK 启发式 token / C 完整流式 / D Part1 先 Part2 后），待转 writing-plans。
> 日期：2026-06-26
> 关联：Phase 2b skill 链多-pass（PR#138-140）的打磨。本 spec 两件独立可发，各一 PR。

---

## 1. 背景

Phase 2b 的 skill 链多-pass 已上线（`chain_service.run_chain` 逐 pass + `rerun` 重跑此 pass）。两处体验缺口：

1. **成本不透明**：前端「调用 N 次 · 共 X 字」只数字符（`ChainPass.to_dict` 出 `output_chars`），既非 token 也无金额，用户不知道一次链润色花多少钱。
2. **重跑无反馈**：`chain_service.rerun(job_id, pass_index)` 是**同步**的（loop 替换 `passes[K..N]`、无 `on_pass`/`checkpoint`），`POST /api/chain/rerun` 阻塞返回 200。多-pass 级联重跑（从 pass0 重跑 = 重跑全部 N 段，30-90s）时用户干等、无逐 pass 进度、不可取消。

## 2. 目标

- **Part 1 成本**：用本地 token 估算 + 内置单价表（默认 + 设置可覆盖），把成本行升级为「调用 N 次 · ≈X tokens · ≈¥Y」。
- **Part 2 流式重跑**：把 `rerun` 改为异步流式（仿 finalize 的 EventBus 模式），逐 pass 实时刷新 + 可取消。

## 3. 非目标

- **不**接真实 API usage（已拍板用本地估算——`complete()` 走流式只拼 `delta.content` 不抓 usage，加 `stream_options` + 透出 usage 要改 LLM client 层 + 8 provider，doubao(ark)/kimi 兼容性不确定，风险高）。token 是**估算值**，UI 用「≈」标注。
- **不**改 `LLMClient.complete` 签名 / 任何 provider。
- **不**做跨币种换算（默认 ¥；未知 model 无价 → 只显 token 不显 ¥）。
- **不**动 `run_chain` 的链执行逻辑（Part 2 只给 `rerun` 加流式，`run_chain` 已有 `on_pass`/`checkpoint`）。

## 4. Part 1 — 真实成本（本地 token 估算 + 单价表）

### 4.1 新模块 `csm_core/llm/pricing.py`

```python
import math, re
from dataclasses import dataclass

# CJK 统一表意文字 + 常用扩展（够覆盖中文正文；不求精确分词，只求稳定估算）。
_CJK = re.compile(r"[㐀-䶿一-鿿豈-﫿　-〿＀-￯]")


def estimate_tokens(text: str) -> int:
    """CJK 感知的 token 估算（无依赖、离线稳）。中文 ~0.6 token/字、
    其余 ~0.25 token/字符（~4 字符/token）。这是估算值，UI 须以「≈」呈现。"""
    if not text:
        return 0
    cjk = len(_CJK.findall(text))
    other = len(text) - cjk
    return math.ceil(cjk * 0.6 + other * 0.25)


@dataclass(frozen=True)
class ModelPrice:
    input: float   # ¥ / 1M tokens
    output: float  # ¥ / 1M tokens


# 内置默认单价（¥/1M tokens，近似值，随官方调价会过时 → 设置里可覆盖）。
# key = model 名（与 AppConfig.default_model 的 value 对齐）。
DEFAULT_PRICES: dict[str, ModelPrice] = {
    "deepseek-chat": ModelPrice(input=1.0, output=2.0),
    "deepseek-reasoner": ModelPrice(input=1.0, output=4.0),
    "qwen-plus": ModelPrice(input=0.8, output=2.0),
    "qwen-max": ModelPrice(input=2.4, output=9.6),
    # doubao / kimi / openai / gemini 等按需补；缺项 → price_for 返回 None。
}


def price_for(model: str | None, overrides: dict[str, dict] | None = None) -> ModelPrice | None:
    """默认←设置覆盖。未知 model → None（调用方据此只显 token、不显 ¥）。"""
    if not model:
        return None
    ov = (overrides or {}).get(model)
    if ov and "input" in ov and "output" in ov:
        return ModelPrice(input=float(ov["input"]), output=float(ov["output"]))
    return DEFAULT_PRICES.get(model)


def chain_cost(passes, model, overrides=None) -> dict:
    """从链 passes 估算成本摘要。passes 是 ChainPass 列表（用 .input/.output 文本）。
    返回 {input_tokens, output_tokens, cost, currency}；无价 → cost=None。"""
    it = sum(estimate_tokens(p.input) for p in passes)
    ot = sum(estimate_tokens(p.output) for p in passes)
    price = price_for(model, overrides)
    cost = None if price is None else round(
        it / 1_000_000 * price.input + ot / 1_000_000 * price.output, 4)
    return {"input_tokens": it, "output_tokens": ot, "cost": cost, "currency": "CNY"}
```

**默认价说明**：上表是近似种子值，不追求精确（精确靠设置覆盖）。实现时按当时已知官方价填，注释标「近似、可在设置覆盖」。

### 4.2 接线（后端单一来源算成本）

- `ChainPass.to_dict()` 增 `input_tokens`/`output_tokens`（`estimate_tokens(self.input/.output)`）——保留现有 `input_chars`/`output_chars`（零回归，前端旧字段仍可用）。
- `chain_service.run_chain` 与 `rerun` 的返回 / done 事件带 `cost` 摘要：在 `run_chain` 末尾、`rerun` 末尾调 `pricing.chain_cost(state.passes, state.model, overrides)`。`overrides` 从 `config_service.load().pricing` 取（`run_chain` 现无 cfg 入参 → 由调用方 `generate_service`/`_finalize_job` 传 `pricing_overrides` 进来，或 chain_service 自行 `config_service.load()`；**选后者**：chain_service 直接读 config，省穿参，与它已 import `llm_factory` 同层）。
- `generate_service` 的 done / `_finalize_job` 的 done / chain rerun 路由结果都带 `cost`（`run_chain` 返回 ChainState，另取 `chain_cost`；或 ChainState 加 `cost` 属性惰性算）。**选 ChainState 加 `cost()` 方法**（`chain_cost(self.passes, self.model, config 覆盖)`），done 事件 `cost=state.cost()`。

### 4.3 配置

`AppConfig` 加：

```python
    # 模型单价覆盖（¥/1M tokens）。空 = 用 pricing.DEFAULT_PRICES。
    # key=model 名，value={"input": float, "output": float}。设置页可改。
    pricing: dict[str, dict[str, float]] = Field(default_factory=dict)
```

`/api/config` PATCH 已对嵌套 dict 深合并（`config_service._deep_merge`），设置卡每改一个 model 发 `{pricing:{<model>:{input,output}}}` 部分 patch。

### 4.4 前端

- `article.ts`：`ChainPass` 类型加 `input_tokens`/`output_tokens`；store 加 `cost` state（`{input_tokens, output_tokens, cost, currency} | null`），done handler 读 `d.cost`，rerun 结果读 `cost`。
- 成本行（ArticleView 成稿区，现「调用 N 次 · 共 X 字」）→「调用 N 次 · ≈{(it+ot)} tokens · ≈¥{cost}」；`cost==null`（未知 model）→ 只显「调用 N 次 · ≈X tokens」。`callCount` getter 保留；新增 `tokenTotal` getter（`cost?.input_tokens + output_tokens`，回退 0）。
- **设置页加「模型单价」卡**（`PricingCard.vue`）：列已知 model（DEFAULT_PRICES key ∪ 当前 default_model）+ 每行 input/output ¥/1M 输入框，改→ patch `{pricing:{model:{...}}}`；占位显示默认值。

## 5. Part 2 — 流式异步重跑此 pass

### 5.1 `chain_service.rerun` 加流式 + 取消

```python
def rerun(job_id, pass_index, *, client=None,
          checkpoint=lambda: None, on_pass=lambda p: None) -> dict:
    state = get_state(job_id)               # 同今天：miss→KeyError、越界→IndexError
    ...
    prev = state.passes[pass_index - 1].output if pass_index >= 1 else ""
    for idx in range(pass_index, len(state.passes)):
        checkpoint()                         # 新增：可取消
        system, user, input_text = _prompt_for(state, idx, prev)
        out = client.complete(system=system, user=user)
        old = state.passes[idx]
        p = ChainPass(index=idx, skill_id=old.skill_id, role=old.role,
                      skill_name=old.skill_name, input=input_text, output=out)
        state.passes[idx] = p
        on_pass(p)                           # 新增：逐 pass 流式
        prev = out
    _cache_put(state)
    return {"passes": [p.to_dict() for p in state.passes],
            "final_text": state.final_text, "cost": state.cost()}
```

同步签名保留（`client`/默认 callbacks），现有同步调用方零改；新增 callbacks 默认 no-op = 零回归。

### 5.2 异步 worker（`generate_service` 或新 `chain_rerun` 接线）

仿 `submit_finalize`/`_finalize_job`，**复用 job_id**：

```python
def submit_rerun(job_id, pass_index) -> str:
    bus.create_job(job_id)                   # 重开同 id 流（链状态已在 job_id 缓存）
    with _state_lock:
        _cancelled.discard(job_id); _live.add(job_id)
    _get_executor().submit(_rerun_job, job_id, pass_index)
    return job_id

def _rerun_job(job_id, pass_index):
    try:
        res = chain_service.rerun(
            job_id, pass_index,
            checkpoint=lambda: _checkpoint(job_id),
            on_pass=lambda p: bus.publish(job_id, "pass", **p.to_dict()))
        bus.finish(job_id, passes=res["passes"], final_text=res["final_text"], cost=res["cost"])
    except _CancelledGenerate:
        bus.fail(job_id, error="cancelled", cancelled=True)
    except (KeyError, IndexError) as e:       # 缓存淘汰 / 越界
        bus.fail(job_id, error=f"{type(e).__name__}: {e}")
    except Exception as e:
        bus.fail(job_id, error=f"{type(e).__name__}: {e}")
    finally:
        with _state_lock:
            _live.discard(job_id); _cancelled.discard(job_id)
```

（worker 放 `generate_service` 复用其 `_live/_cancelled/_checkpoint/_get_executor/bus`；rerun 前 `get_state` 是否存在的 404 校验仍由路由同步做。）

### 5.3 路由契约改：同步 200 → 异步 202

`POST /api/chain/rerun`（现返回 200 `{passes, final_text}`）改为：

```python
@router.post("/api/chain/rerun", status_code=202)
def rerun_chain(body: RerunBody) -> dict:
    state = chain_service.get_state(body.job_id)
    if state is None:
        raise HTTPException(404, f"chain cache miss: {body.job_id}")
    if not (0 <= body.pass_index < len(state.passes)):
        raise HTTPException(400, f"pass_index out of range")
    generate_service.submit_rerun(body.job_id, body.pass_index)
    return {"job_id": body.job_id, "stream_url": f"/api/events/{body.job_id}"}
```

404（缓存 miss）/ 400（越界）在路由**同步**判（与今天一致）；happy 改 202 + SSE。

### 5.4 前端 `rerunPass` 改流式 + 轻量订阅

```ts
async rerunPass(index: number): Promise<void> {
  if (!this.lastJobId) return;
  const sidecar = useSidecar();
  try {
    const resp = await sidecar.client.post("/api/chain/rerun",
      { job_id: this.lastJobId, pass_index: index });
    const jobId = resp.data.job_id;
    // 轻量订阅：只更新 passes/cost，不碰 status/通知/tab（重跑是子操作）。
    this._rerunStop = subscribe(`/api/events/${jobId}`, {
      pass: (d: any) => { this.passes[d.index] = d as ChainPass; },   // 按 index 替换
      done: (d: any) => {
        if (Array.isArray(d.passes)) this.passes = d.passes;
        if (d.cost) this.cost = d.cost;
        if (typeof d.final_text === "string") this.finalText = d.final_text;
        this.rerunningIndex = null; this._rerunTeardown();
      },
      error: () => { this.rerunningIndex = null; this._rerunTeardown(); },  // 静默（含 cancelled）
    });
  } catch { this.rerunningIndex = null; }   // 404/400/网络 静默（同今天从不抛）
}
```

- 新 state `rerunningIndex: number | null`（哪个 pass 在重跑，驱动该 pass 卡 loading + 可取消按钮）+ `_rerunStop`（独立 teardown，不复用 generate 的 `this.stop`）。
- **按 index 替换**（`passes[d.index]=d`）而非 push——级联 K..N 逐个就位。
- 取消：复用 `POST /api/generate/{job_id}/cancel`（已有，对 `_live` 里的 job 生效）→ rerun worker `_checkpoint` 命中 → error(cancelled) → 静默收尾。
- `rerunPass` 仍**从不抛**（同今天契约）。

## 6. 决策记录

| | 决策 | 取舍 |
|---|---|---|
| **A** | 成本在**后端**算（run/rerun 时估 token×单价表，结果带 `cost`），前端纯展示 | 单一来源、token 估算一致；改价影响**下次**运行（可接受：显示=当次真实花费） |
| **B** | token 用 **CJK 启发式**（无依赖） | tiktoken 对中文模型也是近似 + 下载 encoding 离线不稳；估算够「成本感知」 |
| **C** | Part 2 做**完整流式**（异步+逐 pass+可取消） | 仿 finalize EventBus 模式，复用 job_id/_live/cancel；契约 200→202 |
| **D** | **Part 1 先发、Part 2 后发**，各一 PR | Part 1 小、低风险、自足；Part 2 改 SSE 契约风险略高 |

## 7. 零回归边界

- `ChainPass.to_dict` 只**增** token 字段，旧 `*_chars` 保留。
- `run_chain` 不动（已有 callbacks）。
- `rerun` 同步签名保留、新 callbacks 默认 no-op；现有同步单测仍绿（Part 1 阶段 rerun 仍同步 200，只加 `cost`）。
- Part 2 改 `/api/chain/rerun` 契约（200→202）→ 同步更新 `test_routes_chain.py` rerun 用例 + `article.chain.spec.ts` rerunPass 用例。
- `pricing`/`cost` 全 opt-in：未知 model → cost=null → 前端只显 token（不崩）。

## 8. 测试策略

**Part 1**
- `pricing.estimate_tokens`（纯中文/纯英文/混合/空）、`price_for`（默认/覆盖/未知→None）、`chain_cost`（有价/无价→cost null）。
- `ChainPass.to_dict` 带 token 字段；`ChainState.cost()`。
- 前端：store `cost` state（done/rerun 读）、成本行渲染（有价显 ¥、无价只显 token）、PricingCard patch。

**Part 2**
- `chain_service.rerun` 带 `on_pass`/`checkpoint`（逐 pass 回调按序、checkpoint 命中抛 cancel）。
- `submit_rerun`/`_rerun_job`（happy SSE pass+done / cancel / 缓存 miss→fail）。
- 路由 `/api/chain/rerun` 202 + 404 + 400。
- 前端 `rerunPass` 流式（subscribe、pass 按 index 替换、done 覆盖、取消、从不抛）。

## 9. 拆分（转 writing-plans）

**Plan 1（Part 1 成本，一 PR）**：Unit A `pricing.py`（估算+表+cost）+ `ChainPass`/`ChainState` 接线；Unit B 配置 `pricing` + 后端 done 带 cost；Unit C 前端成本行 + `cost` state + PricingCard。
**Plan 2（Part 2 流式重跑，一 PR，Part 1 之后）**：Unit A `rerun` 加 callbacks + `submit_rerun`/`_rerun_job`；Unit B 路由 200→202；Unit C 前端 `rerunPass` 流式 + 轻量订阅 + rerunningIndex/取消。

两 Plan 独立可发；Part 1 先。
