# 交互式「整篇润色 = 成稿增强」设计 spec

> 状态：设计已拍板（A/B/C 同意，D=①一律 finalize），待转 writing-plans。
> 日期：2026-06-25
> 关联：Phase 1（型号事实注入 / 事实核对门禁）、Phase 2a（标题+角度组装）、Phase 2b（skill 链多-pass）。本 spec 是这三者的**交互可达性修复**。

---

## 1. 背景与问题

CSM 创作台的交互流程是**两步**，刻意不一把梭：

1. **起飞（takeoff）** = `article.submit({draft_only: true})` → `POST /api/generate`
   → `_run_job` 跑到 `compose_draft` 后发 `assembly` 事件、随即 `if req.draft_only: bus.finish(draft); return`。
   **只产出毛坯初稿，不调 LLM。**
2. 用户在「初稿」tab 检查、可手动编辑 `draftText`。
3. **整篇润色** = `polishAll()` → `article.polishWhole(draftText)` → `POST /api/polish/block`
   → `polish_service.polish_block(text, skill_id)`：**单 skill、`_POLISH_SYSTEM` + skill body 的一次改写**。

**致命缺口**：Phase 1 的型号事实注入、Phase 2a 的角度指令（`render_angle_directive`）、Phase 2b 的 skill 链多-pass，**全部写在 `_run_job` 里 `draft_only` 短路之后的 LLM 段**（`generate_service.py:206-273`）。交互 UI 永远走不到那段——它的「成稿」实际是 `polish_block` 单 skill 改写。于是：

- 注入/角度/链 在交互里**从不执行**，只有 batch 路径（`batch_service` 自带 `build_prompt`+`complete`）和「完整生成」（`draft_only=false`，UI 不触发）能跑到。
- 唯一在交互里生效的是 Phase 2a 的**人群 frontmatter 过滤**——因为 `assemble_plan(angle=...)` 在 takeoff 的 `draft_only` 短路**之前**就跑了。

这是 Phase 2b 收尾综合审查发现、并经逐行核实（读 `ArticleView.vue:341-429` takeoff/polishAll、grep `draft_only` 仅 takeoff 置 true、`batch_service.py:254` 自带 prompt、`polish_service.polish_block` 无注入/角度/链）确认的。

## 2. 目标

把交互的「整篇润色」从 `polish_block` 单 skill 改写，升级为**在用户审过的初稿上跑 LLM 增强**：

```
整篇润色 = 型号事实注入 + 角度指令 + skill 链多-pass  →  成稿
```

一次让 Phase 1 / 2a / 2b 在交互流程里**真正可达**，并复用 Phase 2b Unit C 已建的「逐 pass 卡 / 重跑此 pass / 成本行」——这些 UI 此前因链不执行而**无数据**，修复后才有内容。

## 3. 非目标

- **不**把导出并进 finalize——导出仍是独立按钮（`POST /api/export/{fmt}`），用户成稿后自行点。
- **不**动 batch 路径（`batch_service` 维持自有 prompt 装配）。
- **不**删 `POST /api/polish/block` 端点（SettingsView「测试连接」ping 依赖它，见决策 C）。
- **不**改 Phase 2a/2b 已落地的词表 / `role:platform` / 链核心。
- **不**做禁区 lint、真实 token×单价成本、流式异步重跑——延后。

## 4. 设计总览

新增一条「成稿」路径，复用 takeoff 的 `job_id` 与缓存 plan：

```
takeoff:   POST /api/generate {draft_only:true}  → job_id_A
           SSE: stage… → assembly(plan 缓存于 job_id_A) → done(draft, final_text="")
           [store: lastJobId = job_id_A，缓存 plan 留在 assembler_service]
用户检查/编辑初稿
整篇润色:  POST /api/generate/{job_id_A}/finalize {draft: 编辑后的 draftText, …}
           → 服务端 bus.create_job(job_id_A) 重开同 id 的流 + 提交 finalize worker
           SSE: stage(链润色) → pass×N → done(final_text, passes, document=null)
           [链状态缓存于 job_id_A → 重跑此 pass / 事实核对 resume 自动同源]
导出:      用户点导出 → POST /api/export/{fmt}
```

**为什么复用 `job_id_A`**：缓存 plan、链状态、factcheck pending **全部按 job_id 索引**，前端 `rerunPass`/`resolveFactcheck` 已经用 `lastJobId`。复用同一 id → 这三个接缝**零改动**自动指向正确位置。`bus.create_job(job_id)` 接受显式 id；takeoff 的 `done` 后旧 buffer 已被 reap，重开一条新 buffer 安全无冲突。

## 5. 后端设计

全部改动落在 `generate_service.py` + `routes/generate.py`，不新建模块（被抽的 `_maybe_block_for_factcheck` / `_plan_to_dict` / `_checkpoint` / `_resolve_chain` 已在 `generate_service`，跨模块搬运反而增加耦合）。

### 5.1 抽共享 `finalize_draft`（核心，_run_job 零回归）

把 `_run_job` 行 206-252（注入 scopes/facts → run_chain → factcheck block-check）抽成函数。两个调用方（`_run_job` 与新 `_finalize_job`）共用。

```python
@dataclass
class FinalizeOutcome:
    final_text: str
    passes: list[dict[str, Any]]
    blocked: bool  # True = 事实核对拦下（bus 已 finish blocked-done，调用方须停下不导出）


def finalize_draft(
    job_id: str, *,
    chain_steps: list[chain_service.ChainStepInput],
    draft: str,
    plan: Any, index: Any, registry: Any, category: str | None,
    keyword: str, title: str | None, angle: Angle | None,
    provider: str | None, model: str | None,
    cfg: Any, out_dir: Path,
    checkpoint, on_pass,
    stage_index: int, stage_total: int,
) -> FinalizeOutcome:
    cfg_bm = cfg.brand_memory
    scopes: list = []
    brand_facts: str | None = None
    if cfg_bm.inject or cfg_bm.factcheck:
        scopes = resolve_scopes(
            plan, index, registry,
            own_brands=set(cfg_bm.own_brands), category=category,
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

`_run_job` 改为：

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
        # 导出（stage 5/6）+ bus.finish 维持原样，用 final_text + outcome.passes
```

**零回归保证**：`_run_job` 传 `stage_index=4, stage_total=6` 复刻原 `bus.publish("stage","skill 链润色",4,6)` 字节级一致；scopes/brand_facts 计算、`run_chain` 入参、factcheck 全部不变。改动纯属「内联块 → 函数调用」，行为等价。现存 `_run_job` 端到端测试须保持全绿。

### 5.2 `submit_finalize` + `_finalize_job`（复用 job_id）

```python
@dataclass
class FinalizeRequest:
    draft: str
    keyword: str
    title: str | None = None
    angle: Angle | None = None
    skill_id: str | None = None
    skill_chain: list[str] | None = None
    provider: str | None = None
    model: str | None = None


def submit_finalize(job_id: str, req: FinalizeRequest) -> str:
    """在既有 takeoff job_id 上重开一条流，提交 finalize worker。
    调用方（路由）须先确认缓存 plan 存在（否则 404）。"""
    bus.create_job(job_id)            # 重开同 id buffer（旧的已 reap）
    with _state_lock:
        _live.add(job_id)             # 让协作式取消对 finalize 生效
    _get_executor().submit(_finalize_job, job_id, req)
    return job_id


def _finalize_job(job_id: str, req: FinalizeRequest) -> None:
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

        # 新鲜 scan + registry（与 _run_job 一致）。注意 takeoff 走的是
        # scan_vault 直调、不写 vault_service._index，故此处不复用
        # vault_service.cached()（可能为 None / 陈旧），重新扫描保证 scopes
        # 能命中 plan 选中的型号。vault 扫描非瓶颈（链 LLM 才是）。
        index = scan_vault(vault_root)
        registry = build_brand_registry(vault_root)

        # 链解析复用 _resolve_chain（单 skill_id 找不到抛、多链失效跳过+warning）。
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
            document=None,                       # 不导出（独立按钮）
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

注：`_resolve_chain(req, cfg)` 现签名读 `req.skill_chain` / `req.skill_id`；`FinalizeRequest` 同字段名，可直接复用（无需改 `_resolve_chain`）。

### 5.3 端点 `POST /api/generate/{job_id}/finalize`

`routes/generate.py` 新增：

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

（`angle` 是 pydantic 对象，`model_dump` 会压成 dict，须显式排除后单传——与现有 `start_generate` 同款处理。）

### 5.4 复用 job_id 的不变式

- **缓存 plan 来源**：takeoff 的 `assemble_plan` 后 `cache_plan(job_id_A, plan, template_id, seed)` 已落缓存（LRU 50，`assembler_service`）。finalize 直接 `get_plan(job_id_A)` 取**起飞时采样的那份 plan**（型号选择不变，决策 A）。
- **stream 重开无 race**：`submit_finalize` **先** `bus.create_job(job_id)` 同步建 buffer **再**返回 job_id；前端拿到响应后才 subscribe。worker 在 done 前还要 scan/registry/load_template + 跑链（数秒），subscribe 必先于 done。即便极端下 worker 先 finish，`done` 事件在 buffer 队列里等到 subscribe drain（buffer 在 600s 静默或流 attach 后才 reap）。
- **取消**：finalize 注册进 `_live`，现有 `POST /api/generate/{job_id}/cancel` + `cancelJob()` 对 finalize 同样生效（链 `checkpoint` 回调命中 `_checkpoint`）。
- **事实核对 resume 同源**：finalize 被拦时 `_maybe_block_for_factcheck` 用 job_id_A 缓存 pending + 发 blocked-done。前端 `resolveFactcheck` 用 `lastJobId=job_id_A` POST `/export`——自动命中。
- **重跑此 pass 同源**：`run_chain` 链状态缓存于 job_id_A，`rerunPass` 用 `lastJobId` POST `/api/chain/rerun`——自动命中。

## 6. 前端设计

### 6.1 store 新增 `finalize()` action

抽出 `submit()` 里的 SSE handler 装配为私有 `_subscribe(jobId)`（handler 完全相同：stage/assembly/pass/done/error），`submit()` 与 `finalize()` 共用。`finalize()` 做**更轻的 reset**——保留 `draftText`（用户编辑过的初稿是链输入）、`plan`、`template`、`lastRequest`，只重置 `status/currentStage/stageIndex/finalText/passes/factcheck`。

```ts
async finalize(): Promise<void> {
  if (!this.lastJobId || !this.lastRequest || !this.draftText.trim()) return;
  this._teardown();
  this.status = "running";
  this.error = null;
  this.finalText = "";
  this.passes = [];
  this.factcheck = null;

  const sidecar = useSidecar();
  const req = this.lastRequest;
  try {
    const resp = await sidecar.client.post(
      `/api/generate/${this.lastJobId}/finalize`, {
        draft: this.draftText,
        keyword: req.keyword,
        title: req.title ?? null,
        angle: req.angle ?? null,
        skill_id: req.skill_id ?? null,
        skill_chain: req.skill_chain ?? null,
        provider: req.provider ?? null,
        model: req.model ?? null,
      });
    this.jobId = resp.data.job_id;          // == lastJobId
  } catch (e: any) {
    this.status = "error";
    this.error = e?.response?.data?.detail ?? e?.message ?? String(e);
    return;
  }
  this._subscribe(this.jobId!);              // 复用 submit 的 handler
}
```

`done` handler 已正确：`final_text` 取 `d.final_text`、`passes` 取 `d.passes`（finalize done 带二者）、`document` 为 null（不导出）、`factcheck` 按 `d.factcheck` 设。无需改 handler。

### 6.2 `polishAll()` 改接 finalize（real 模式）

`ArticleView.vue` 的 `polishAll()` real 分支（`lastRequest && draftText.trim()`）：

```ts
// 真实模式：整篇润色 = finalize（注入+角度+链），SSE 驱动逐 pass。
await article.finalize();
if (article.status === "done" && article.finalText) {
  activeTab.value = "final";
  toast.success("整篇润色完成");
} else if (article.status === "error") {
  toast.error(article.error ?? "润色失败");
}
// factcheck 被拦时 status=done 但有 article.factcheck → 审查面板已接管，不切 tab
```

- 退役本地假进度（`polishing`/`polishProgress`/`polishStage` + `POLISH_STAGES` 定时器）在 real 模式的作用——真实进度由 SSE `pass` 事件 + 逐 pass 卡呈现。**demo 模式分支不动**（无 `lastRequest` 时仍跑假 5 阶段弹窗）。
- 按钮禁用条件由 `polishing.value` 改为 `article.isRunning`（finalize 期间 status=running）。
- 整篇润色期间的粗进度呈现：以逐 pass 卡为主信号；6-阶段生成进度条**不**在 finalize 期间复用（避免「已 done 又跳回 stage 4」的视觉），实现细节见 plan Unit C。

### 6.3 `polishWhole` 退役 / `polish_block` 端点保留

- store `polishWhole(text)` 仅 `polishAll` 调用 → 改接 finalize 后**移除** `polishWhole`（无其它引用）。
- `POST /api/polish/block` 端点 + `polish_service.polish_block` **保留**：SettingsView「测试连接」ping 依赖它（`SettingsView.vue:462`），且未来「组装 tab 单 block AI 润色」可复用（决策 C）。

## 7. 决策记录

| | 决策 | 取舍 |
|---|---|---|
| **A** | 链作用在**用户编辑后的 `draftText`**；事实/作用域从**缓存 plan**取（型号不变） | 尊重初稿 tab 的手改；型号选择固定为起飞采样那份 |
| **B** | 抽共享 `finalize_draft`，`_run_job` 与 `_finalize_job` 共用 | DRY；`_run_job` 零回归（内联→函数） |
| **C** | `polish_block` 端点保留；whole-article「整篇润色」改走 finalize | Settings ping 依赖 + 未来单 block 复用 |
| **D=①** | **一律走 finalize**（纯净场景=无链/无型号/无角度 时跑 1 段 `build_prompt(draft)`） | 统一一条路、不分叉；纯净场景措辞较旧 `_POLISH_SYSTEM` 略变但更贴「毛坯→成稿」本义 |

**D 的影响（修复本意，非回归）**：整篇润色后的成稿现在真正带「注入事实 + 角度文风 + 链多-pass」，取代今天的 `polish_block` 单 skill 改写。纯净场景下成稿措辞会变（`build_prompt` vs `_POLISH_SYSTEM`），这是预期内的行为升级。

## 8. 零回归边界

- `_run_job`（`draft_only=false`，完整生成）行为**字节级不变**——`finalize_draft` 是等价抽取，`stage_index=4/total=6` 复刻原 stage 事件。
- takeoff（`draft_only=true`）路径**完全不动**。
- batch 路径**完全不动**。
- `polish_block` 端点 + Settings ping **完全不动**。
- 单步链 / 无角度 / 无型号 的纯净 finalize：`finalize_draft` 退化为 `run_chain` 单 step0（`build_prompt`），与 Phase 2b 已验证的零回归路径一致。

## 9. 边界与风险

- **缓存 plan 淘汰 → 404**：LRU 50 满 / sidecar 重启 → `get_plan` miss → 端点 404。前端 `finalize()` 失败 toast「请重新生成初稿」。可接受（单篇活跃文章场景下罕见）。
- **vault drift**：finalize 新鲜 scan+registry 反映**当前** vault，缓存 plan 反映**起飞时**采样。两者间 vault 变动（共享盘）→ plan 选中的型号在新索引里可能查不到，scopes 缺该型号事实。罕见、影响小（注入/核对略偏，不报错），v1 接受并记录。
- **并发整篇润色**：`bus.stream` 已拒绝同 job_id 并发流（第二条 attach 被拒 + 自重连）。前端按钮 `article.isRunning` 禁用防重复点击。
- **takeoff 未起飞就点润色**：`finalize()` 头部 `!lastJobId || !lastRequest || !draftText.trim()` 守卫直接 return（demo 模式仍走假弹窗，不调 finalize）。

## 10. 测试策略

**Unit A（`finalize_draft` 抽取）**
- `finalize_draft` 与旧内联路径产出相同 `final_text`/`passes`（回归基准：同 plan+draft+chain 跑出一致结果，stub LLM）。
- blocked 路径：factcheck 命中 → 返回 `blocked=True` 且 bus 已 finish 带 violations。
- inject 关：`cfg_bm.inject=False` → 不算 scopes、`brand_facts=None` 传入链。
- 现存 `_run_job` 端到端测试全绿（完整生成不回归）。

**Unit B（端点 + worker）**
- 缓存 plan 缺失 → `POST …/finalize` 返回 404。
- happy path：takeoff（draft_only）→ finalize → SSE 收到 `pass×N` + `done`（带 `final_text` 非空、`document=None`、`passes`）。
- 复用 job_id：finalize 后 `POST /api/chain/rerun {job_id}` 能重跑（链状态在同 id 缓存）。
- 取消：finalize 跑中 `POST …/cancel` → `error{cancelled:true}`。

**Unit C（前端）**
- `polishAll` real 模式 → `finalize()` POST 到 `/api/generate/{lastJobId}/finalize`，body 带 `draft=draftText` + `lastRequest` 的 angle/title/skill_chain/skill_id/provider/model。
- SSE：`pass` → `passes` 增量、`done` → `finalText` + 切 final tab + toast。
- `finalize()` 守卫：无 lastJobId/lastRequest/draftText 时 return。
- demo 模式分支不受影响（假弹窗仍在）。
- 现存 article store / ArticleView 测试全绿。

## 11. 拆分（转 writing-plans）

- **Unit A**（`generate_service`，后端核心）：抽 `FinalizeOutcome` + `finalize_draft`；`_run_job` 改调它；单测（回归基准 + blocked + inject-off）。
- **Unit B**（`generate_service` + `routes/generate.py`，后端端点）：`FinalizeRequest` + `submit_finalize` + `_finalize_job`；`FinalizeBody` + `POST …/finalize`（404 + 202）；单测（404 / happy / 复用 job_id rerun / cancel）。
- **Unit C**（前端）：store `_subscribe` 抽取 + `finalize()` action + 移除 `polishWhole`；`ArticleView.polishAll` real 分支改接 finalize + 按钮禁用条件 + tab 切换；vitest。

每 Unit 一个 PR，用户 merge 之间衔接。全部 opt-in / 零回归。

## 12. 延后（非本轮）

- 禁区 lint（emoji/破折号/绝对化/引流话术 确定性扫描）。
- skill 链真实 token×单价成本（现为调用次数 + 字数估算）。
- 流式异步重跑此 pass。
- Phase 3：素材库浏览·录入 tab + vault writer。
