# Phase 2b 设计：skill 链多-pass（人设→去AI味→平台适配）

- 日期：2026-06-24
- 上位文档：[创作台升级总体路线图](2026-06-23-creation-studio-upgrade-roadmap-design.md) 的 **Phase 2 头牌的另一半**（与已交付的 [Phase 2a 角度组装](2026-06-24-phase2-title-angle-assembly-design.md) 并列）。
- 范围：把今天的「单 skill 一次润色」升级为**按 role 顺序的多-pass 链**（人设→去AI味→平台适配），分多次调用、逐 pass 可预览可单独重跑。
- **不在本轮**：禁区 lint（emoji/破折号/绝对化/引流话术 确定性扫描）—— 独立留后续轮；真·token×单价成本估算（要改 LLMClient + 8 providers）。

---

## 0. 目标与现状

**目标**：让早就存在却从不自动跑的「去AI味」真正进流程；persona/humanize/platform 各一段聚焦 pass，质量优于单段混做；逐 pass 可预览、可只重跑坏的那一段（省钱省时）。

**现状基线（实勘 main，2026-06-24）**：
- 生成主链路：毛坯 → 注入(Plan3) → **单次** `build_prompt`（skill body 作 system + 角度指令 + 事实）→ **单次** `client.complete` → factcheck 门禁 → export（[generate_service.py:225-234](../../../sidecar/csm_sidecar/services/generate_service.py)）。
- 后置润色：`POST /api/polish/block` → `polish_service.polish_block`（单 skill、单 complete，[polish_service.py](../../../sidecar/csm_sidecar/services/polish_service.py)）—— 是「精修 pass」的现成模板。
- **Skill 有 `role` 字段**（persona/humanize，缺省 persona；任意字符串可存，[skills_service.py:32](../../../sidecar/csm_sidecar/services/skills_service.py)）；`SkillEditView` role 下拉现仅 人设/去AI味。无 platform skill。
- **`LLMClient.complete(system, user, temperature) -> str`** —— 只返回字符串，**无 token/usage**（[llm/client.py](../../../csm_core/llm/client.py)）。
- 有状态缓存范式现成：`assembler_service`（job_id LRU 缓存 + reroll）、`factcheck_service`（cache_pending + /export resume）。

---

## 1. 决策记录（已与用户拍板）

1. **分多次（真多 pass）**：每个 role 一次独立 LLM 调用，上段输出喂下段。（vs 合成一次；路线图 §7.4 开放决策）
2. **逐 pass 重跑进 v1**：缓存链状态 + 重跑端点 + 逐 pass UI（仿 assembler reroll）。
3. **位置定职责**：`step[0]` = 组装 pass（`build_prompt`，拿毛坯+事实+角度+标题）；`step[1:]` = 精修 pass（`build_refine_prompt`，上段输出 + skill + 保守约束）。role 只用于前端分槽 + UI 标签，**执行顺序 = 列表顺序**。
4. **3 role 槽**：人设/去AI味/平台，每槽一个该 role 的 skill 下拉（可空），产出有序链；空槽不入链。
5. **role:platform 启用** + SkillEditView 加「平台适配」选项 + **seed 1 个示例平台 skill**（`examples/skills/小红书适配.md`）。
6. **成本 v1 = 调用次数 + 字符数 proxy**；真·token×单价留后续。
7. **全 opt-in / 向后兼容**：不传 `skill_chain` → 回退单 `skill_id`（= 链 `[skill_id]` = 1 个组装 pass = **今天逐字节一致**，快照钉死）。

---

## 2. 数据模型

### 2.1 请求扩展
- `GenerateRequest` / `GenerateBody` 加 `skill_chain: list[str] | None = None`（有序 skill id 列表，前端按 role 槽产出）。`skill_chain` 非空 → 以它为准；否则回退 `skill_id`（单步）。`list[str]` 是普通值，路由 `**body.model_dump()` 直接透传（无 angle 那种对象坑）。

### 2.2 链状态缓存（sidecar `chain_service`，仿 `assembler_service`）
```
ChainPass:  index:int, skill_id:str|None, role:str, skill_name:str,
            input:str, output:str            # input/output 用于重跑 + 字符数成本
ChainState: job_id, draft, brand_facts:str|None, angle_directive:str|None,
            title:str|None, keyword:str, provider:str|None, model:str|None,
            passes: list[ChainPass]
```
LRU 缓存（job_id → ChainState，MAX 同 assembler）。`reset_for_test()`。

### 2.3 SSE `pass` 事件（每 pass 一个，流式预览）
```
event: pass
data: { index, role, skill_id, skill_name, output, input_chars, output_chars }
```
与现有 `stage`/`assembly`/`done`/`error` 并列（[generate.py:48 events 端点](../../../sidecar/csm_sidecar/routes/generate.py)）。`done` 仍带最终 `final_text`，另加 `passes`（完整 ChainPass 列表，含字符数，供成本汇总）。

---

## 3. 精修 pass 提示（csm_core/llm/prompts.py 新增纯函数）

```python
def build_refine_prompt(skill_body: str | None, prev_text: str) -> tuple[str, str]:
    """链 step[1:] 的精修 prompt：按 skill 风格改写上段输出，保守约束。"""
    system = (skill_body or "").strip()
    user = (
        f"【待改写正文】\n{prev_text}\n\n"
        "请按上面的风格指引改写这段正文：保留所有信息点、段落要点与全部"
        "数字/单位/认证名称，只改进措辞、语感与风格一致性；不新增虚构事实，"
        "不删减关键信息，不改动任何参数数字或认证。"
    )
    return system, user
```
（与 `build_prompt` 形状一致：system = skill body，user = 文 + 指令。`step[0]` 仍用现有 `build_prompt`。）

---

## 4. 链执行（改 `generate_service._run_job` + 新 `chain_service`）

`_run_job` 在「调用 LLM」段（现 index 4，标签改「skill 链润色」）改为：

1. **解析链**：`steps = resolve_chain(req)` —— `skill_chain` 非空则 load 各 skill（失效的跳过 + warning）；否则 `[skill_id]`（或空 → 单步无 skill 组装 = 今天 skill_id=None）。
2. **跑链**（`chain_service.run_chain`）：
   - `step[0]`：`build_prompt(PromptInputs(user_skill_prompt=steps[0].body, keyword, draft, brand_facts(若 inject), title, angle_directive))` → `complete` → out0。**= 今天的 build_prompt 那一步**（角度/事实只在这段）。
   - `step[k≥1]`：`build_refine_prompt(steps[k].body, prev_out)` → `complete` → outk。
   - 每 pass 发 `pass` SSE 事件；记 ChainPass（含 input/output + 字符数）。
   - `final_text = passes[-1].output`。
3. **缓存** ChainState（job_id），供重跑。
4. **factcheck 跑末段**（`_maybe_block_for_factcheck`，白名单仍 = 毛坯 ∪ 事实 ∪ 标题）。改数字会被拦（新数 ∉ 白名单）；漏数字仍是已知边界（保守约束兜）。链状态在 factcheck 前已缓存 → 即使被拦也能重跑。
5. `done` 带 `final_text` + `passes`；**factcheck 拦截时 done(blocked) 也带 `passes`**（前端拦截态仍显示链各段，可重跑后再走 /export 重核）。

**零回归**：`skill_chain=None` 且单 `skill_id` → 链 = `[skill_id]` → 只跑 `step[0]` = `build_prompt`+`complete`，与今天**逐字节一致**（`build_refine_prompt` 不触发）。

## 5. 逐 pass 重跑（同步，仿 reroll）

- `POST /api/chain/rerun { job_id, pass_index }`：
  - 取缓存 ChainState；用 `passes[pass_index].input` 重调（step0 用 build_prompt 重建、step≥1 用 build_refine_prompt）→ 得新 output；
  - **级联重跑** pass_index+1..N（各喂上一段新 output，step≥1 路径）；
  - 更新缓存 passes；返回 `{ passes, final_text }`。
- **同步**返回（一次重跑 ≤ N 次调用，前端转圈；async 流式留后续）。
- factcheck **不在重跑里**；导出走已有 `POST /api/generate/{id}/export`（前端传当前 final_text 重核）—— 与今天门禁一致。
- 旧 job 无缓存 / pass_index 越界 → 404/400（仿 [assembler.py reroll 端点](../../../sidecar/csm_sidecar/routes/assembler.py)）。

## 6. role:platform

- `skills_service` 已存任意 role 字符串，`platform` 直接可用；`SkillEditView` 角色下拉加「平台适配」(platform)。
- **seed** `examples/skills/小红书适配.md`（`role: platform`，body = 小红书风格适配指引：口语化、分点、适度 emoji 留给用户、标题钩子等）。仅版本控制种子；live skill 走 `cfg.skill_dir`，现有用户零影响（fresh install 才 seed）。
- 平台 pass 可选：没平台 skill → persona→humanize 两段，仍有价值。

## 7. 成本显示
- v1：`done.passes` 带每 pass `input_chars`/`output_chars`；前端显示「**调用 N 次 · 共 X 字**」（N=pass 数，X=∑output_chars 或 in+out）。
- 真·token×单价**留后续**（需 `LLMClient.complete` 返回 usage + 8 provider + 定价表，跨切面大改）。

## 8. 前端
- **链组合器**（新组件 `SkillChainPicker.vue`，`components/article/`）：3 role 槽（人设/去AI味/平台），每槽 `FormSelect`（该 role 的 skill + 空）；产出有序 `skill_chain`。
  - `CreateArticleHero` 的「风格」chip → 打开链组合器；`takeoff()` 把 `skill_chain`（逗号连或 query 数组）带进 query。
  - `ArticleView` header 显示链 chip（如 `家电科普人设 → 去AI味 → 小红书适配`）。
  - 向后兼容：只选人设 = 单步 = 今天。
- **逐 pass 预览 + 重跑**：`ArticleView` 成稿区显示链各 pass（pass 卡：role+skill 名+输出 + 「重跑此 pass」按钮）+ 末段成稿；按钮调 `chain.rerunPass(index)`。
- **成本**：显示「调用 N 次 · 共 X 字」。
- `stores/article.ts`：`GenerateRequest` 加 `skill_chain?`；`passes: ChainPass[]` 状态（SSE `pass`/`done` 填充）；`rerunPass(index)` action（POST `/api/chain/rerun`，更新 passes+finalText）；`skills` store 已有列表（按 role 分组喂槽）。
- 复用 `FormSelect`/`FormField`；硬编码中文。

## 9. 错误处理 & 兼容
- 不传 chain / 单 skill → 今天行为（step0 组装字节级快照钉死）。
- 链中 skill_id 失效 → 跳过该 pass + warning（不中断链）。
- 空链（全空槽）→ 回退「无 skill 组装」（step0 system 空，= 今天 skill_id=None）。
- 某 pass LLM 失败 → 该 job error（与今天单调用失败一致）；已成功的 pass 已发 SSE，前端可见。
- 重跑越界/旧 job 无缓存 → 404/400。
- 取消：链跑各 pass 前 `_checkpoint`（与今天一致）。

## 10. 测试
- `build_refine_prompt`：含保守约束 + 上段文；skill_body 空 → system 空。
- 链跑：单步 == 今天（build_prompt 字节快照）；多步顺序喂（out_{k-1} 进 step_k）；空槽跳过；skill 失效跳过+warning；factcheck 跑末段。
- SSE `pass` 事件每 pass 一个 + `done.passes` 完整。
- 链缓存 + 重跑：重跑 K → K..N 级联、passes 更新、final 变；旧 job 404；越界 400。
- `role:platform` 解析 + SkillEditView 选项 + seed skill 加载为 platform。
- 前端：链组合器产出有序链 / query 往返 / 逐 pass 预览 / 重跑 update / 成本汇总 / **无链零回归**（只选人设 == 今天 submit）。
- 真实库回归：人设+去AI味 两段链 → 末段比单段更「不像 AI」且参数接地；单 skill_id 端到端 == 今天。

## 11. 代码影响

| 层 | 新增 | 必改 |
|---|---|---|
| `csm_core/llm/` | — | `prompts.py`（`build_refine_prompt`） |
| `sidecar/.../services/` | `chain_service.py`（run_chain + 缓存 + rerun） | `generate_service.py`（GenerateRequest.skill_chain + 解析链 + 跑链替换单调用 + `done.passes`） |
| `sidecar/.../routes/` | — | `generate.py`（GenerateBody.skill_chain）、`assembler.py` 同级加 `POST /api/chain/rerun`（或新 `chain.py`） |
| `examples/skills/` | `小红书适配.md`(role:platform) | — |
| `frontend/src/` | `components/article/SkillChainPicker.vue` | `stores/article.ts`(skill_chain+passes+rerunPass)、`components/home/CreateArticleHero.vue`、`views/ArticleView.vue`、`views/SkillEditView.vue`(role 加 platform) |

**不改**：`polish_service`/`/api/polish/block`（后置单块润色保留）；`factcheck_service`/`/export`（重核走它）；角度/注入链路（Phase 2a/1 不动）。

## 12. 拆分（交 writing-plans）
- **Unit A**：`build_refine_prompt`（csm_core 纯函数）+ `chain_service`（run_chain + 缓存 + rerun，纯 sidecar 逻辑，mock LLM 测）。
- **Unit B**：API 接线（GenerateRequest/Body.skill_chain + generate_service 接链跑 + SSE `pass` + `done.passes` + `POST /api/chain/rerun` + role:platform 启用 + seed 小红书适配.md）。
- **Unit C**：前端（SkillChainPicker + CreateArticleHero 链入口 + ArticleView 逐 pass 预览/重跑/成本 + SkillEditView platform 选项 + store）。
- 每 Unit 子代理驱动 + 逐单元 opus 两段审查 + 最终整体审查（同 Phase 2a）。**B 体量大可再拆 B1（chain 跑 + generate 接）/B2（rerun 端点 + role + seed）。**

## 13. 留给后续轮（明确不做）
- 禁区 lint（emoji/破折号/绝对化/引流话术 确定性扫描 + 一键清 + 可拦导出）。
- 真·token×单价成本（改 LLMClient 返回 usage + 8 provider + 定价表）。
- 重跑异步流式（v1 同步）。
- 角度感知的 platform pass、平台 skill 丰富库、`role:platform` 与小红书编辑器模块打通。
