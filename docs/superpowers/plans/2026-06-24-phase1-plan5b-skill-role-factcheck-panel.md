# Phase 1 — Plan 5b：SkillEditView role 下拉 + 事实核对审查面板（Phase 1 收官）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 Plan 4 的 skill `role` 和 Plan 3 的事实核对硬门禁**接到前端**：① `SkillEditView` 加「角色」下拉（人设/去AI味）；② ArticleView 加事实核对审查面板——生成被门禁拦下时弹窗列违规项，用户改文案/勾选放行后「重新核对并导出」。这是 Phase 1 的最后一块。

**Architecture:** ① SkillEditView 加一个 `FormSelect` 字段 + 进 create/edit payload（后端 Plan 4 已收 `role`）。② 事实核对面板**无需新后端**——生成被拦时 SSE `done` 事件已带 `factcheck.{blocked, violations}`，放行走已存在的 `POST /api/generate/{id}/export`。逻辑放 `article` store（可 vitest）+ 抽 `FactCheckPanel.vue`（可 vitest）；ArticleView 仅加「挂面板 + watcher + 拦截时改导出按钮」最小接线。**一处后端小修**：`Violation` 加 `number: float|None`（归一值），让前端放行 `12万转`(→120000) 这类**万-值**时能回传正确的数（否则 `parseFloat("12万转")=12` 对不上白名单 120000）。

**Tech Stack:** Python/pytest（后端小修）；Vue 3 setup + Pinia + Vitest + vue-tsc（前端）。

参考 spec：[Phase 1 §4.2/§5/§6](../specs/2026-06-23-phase1-brand-model-memory-design.md)；前置 Plan 3（门禁）/ Plan 4（role）/ Plan 5a（素材库）。

---

## 关键设计决定（执行前已确认 / 已定）

1. **Plan 5b = Phase 1 收官 PR**：SkillEditView role 下拉 + ArticleView 事实核对审查面板，一个 PR。
2. **硬编码中文**（同 5a；代码库无 i18n）。
3. **审查面板无需新后端**：blocked 的 `done` 事件已带 `factcheck.{blocked, violations[]}`（`generate_service._maybe_block_for_factcheck`）；放行走已存在的 `POST /api/generate/{id}/export`（body `ResolveFactcheckBody`: `final_text`/`released_numbers: float[]`/`released_certs: str[]`）。
4. **面板用 modal `Dialog`**（门禁是 blocker，语义+样式镜像 ArticleView 既有导出 modal）；逻辑落 `article` store（可测）+ 抽 `FactCheckPanel.vue`（可测）；ArticleView 接线最小化。
5. **后端小修 `Violation.number`**：number 违规回传**归一值**才能正确放行万-值。`checker.py` 建 number 违规处本就有归一 float（`value`），现仅存了 `raw`——补存 `number`。cert 违规 `number=None`。`released_numbers` 仍 `float[]`，`resolve_and_export` 不变。
6. **role 下拉 = 人设(persona) / 去AI味(humanize)**（Plan 4 现有两值；`platform` 留 Phase 2 skill 链时再加）。旧 skill 无 role → 后端默认 `persona` → 下拉显示「人设」。
7. **前端验证 = Vitest + vue-tsc**；端到端（真生成被拦→弹面板→放行导出）= **用户手动**。镜像：role 用 `FormSelect`；面板 Dialog 镜像 ArticleView 导出 modal。

---

## File Structure

**Unit A（前端·skill role）**
- Modify `frontend/src/views/SkillEditView.vue` — 加 `role` state + `FormSelect` 字段 + loadDetail/create/edit payload。
- Test (Create) `frontend/src/views/__tests__/SkillEditView.spec.ts` — create 保存 payload 含 role。

**Unit B（后端小修 + store）**
- Modify `csm_core/factcheck/model.py` — `Violation.number: float | None = None`。
- Modify `csm_core/factcheck/checker.py` — number 违规填 `number=value`（归一值）。
- Modify `sidecar/tests/...`（若有断言 Violation 形状）+ `tests/core/factcheck/test_checker.py` 加断言。
- Modify `frontend/src/stores/article.ts` — `factcheck` state + `done` 填充 + `resolveFactcheck` action。
- Test (Create) `frontend/src/stores/__tests__/article.spec.ts` — resolveFactcheck + done 填充 factcheck。

**Unit C（前端·面板 + 接线）**
- Create `frontend/src/components/article/FactCheckPanel.vue` — Dialog 列违规 + 放行勾选 + 重新核对并导出。
- Test (Create) `frontend/src/components/article/__tests__/FactCheckPanel.spec.ts`。
- Modify `frontend/src/views/ArticleView.vue` — 挂面板 + watcher 自动弹 + 拦截时导出按钮改走面板。

---

# Unit A：SkillEditView 角色下拉

### Task A1: role 字段 + FormSelect + payload

**Files:**
- Modify: `frontend/src/views/SkillEditView.vue`
- Test: `frontend/src/views/__tests__/SkillEditView.spec.ts`

- [ ] **Step 1: 写失败测试**（create 模式，mock route/router/sidecar/toast；断言保存 payload 含 role）

`frontend/src/views/__tests__/SkillEditView.spec.ts`:
```typescript
import { mount, flushPromises } from "@vue/test-utils";
import { describe, it, expect, vi, beforeEach } from "vitest";

const postMock = vi.fn();
const pushMock = vi.fn();
vi.mock("vue-router", () => ({
  useRoute: () => ({ params: { id: "new" } }),
  useRouter: () => ({ push: pushMock }),
}));
vi.mock("@/stores/sidecar", () => ({ useSidecar: () => ({ client: { post: postMock, get: vi.fn() } }) }));
vi.mock("@/composables/useToast", () => ({
  useToast: () => ({ success: vi.fn(), error: vi.fn(), warn: vi.fn() }),
}));

import SkillEditView from "@/views/SkillEditView.vue";

describe("SkillEditView role", () => {
  beforeEach(() => { postMock.mockReset(); pushMock.mockReset(); });

  it("创建时 payload 带 role（默认 persona）", async () => {
    postMock.mockResolvedValueOnce({ data: { id: "x", name: "x", role: "persona" } });
    const w = mount(SkillEditView);
    // 填名称
    const name = w.find("input");
    await name.setValue("测试人设");
    // 触发保存
    await w.find("button.inline-flex, [data-test='save'], button").trigger; // 见下：用更稳的方式
    // 直接调用暴露的 save 不方便 —— 改为找「创建」按钮点击
    const btns = w.findAll("button");
    const saveBtn = btns.find((b) => b.text().includes("创建"));
    await saveBtn!.trigger("click");
    await flushPromises();
    expect(postMock).toHaveBeenCalledWith("/api/skills", expect.objectContaining({ role: "persona" }));
  });
});
```

> 注：上面的按钮定位以「文本含『创建』」为准（create 模式保存按钮文案=「创建」）。若 mount 受 FormSelect 的 Teleport/监听干扰，组件测试可改为最小化断言（role select 存在 + 默认值 persona）；核心是**锁 payload 含 role**。实现者按实际渲染调稳。

- [ ] **Step 2: 跑测试确认失败**

Run: `Set-Location D:\CSM\.claude\worktrees\phase1-plan5b\frontend; npx vitest run src/views/__tests__/SkillEditView.spec.ts`
Expected: FAIL（payload 无 role）

- [ ] **Step 3: 写实现**（`SkillEditView.vue`）

- import 加 `FormSelect`：
```typescript
import FormSelect from "@/components/forms/FormSelect.vue";
```
- state 加（line 51 后）：
```typescript
const role = ref("persona");
```
- `loadDetail` 加（在 set body 后）：
```typescript
role.value = r.data.role ?? "persona";
```
- `saveCreate` 的 POST body 加 `role: role.value`；`saveEdit` 的 PATCH body 加 `role: role.value`。
- 模板：把 header 网格 `lg:grid-cols-3` 改 `lg:grid-cols-4`，并在「语气标签」FormField 后加：
```vue
<FormField label="角色">
  <FormSelect
    v-model="role"
    :options="[
      { label: '人设（persona）', value: 'persona' },
      { label: '去AI味（humanize）', value: 'humanize' },
    ]"
    width="100%"
  />
</FormField>
```

- [ ] **Step 4: 跑测试 + 类型**

Run: `npx vitest run src/views/__tests__/SkillEditView.spec.ts`（PASS）
Run: `npx vue-tsc --noEmit`（SkillEditView 无新错；如 emit vite.config.js 则 `git checkout -- frontend/vite.config.js`）

- [ ] **Step 5: 提交**

```bash
git add frontend/src/views/SkillEditView.vue frontend/src/views/__tests__/SkillEditView.spec.ts
git commit -m "feat(skills): SkillEditView 加角色下拉（人设/去AI味，接 Plan 4 role）"
```

---

# Unit B：Violation.number 后端小修 + article store factcheck

### Task B1: `Violation.number`（归一值）

**Files:**
- Modify: `csm_core/factcheck/model.py`, `csm_core/factcheck/checker.py`
- Test: `tests/core/factcheck/test_checker.py`（追加）

- [ ] **Step 1: 写失败测试**（追加）

```python
def test_number_violation_carries_normalized_number():
    from csm_core.factcheck.checker import check_facts
    # 成稿写「15万转」(→150000) 不在白名单 → 违规，且 number 应为归一值 150000
    rep = check_facts("电机 15万转。", allowed_numbers=set(), allowed_certs=set())
    v = next(v for v in rep.violations if v.kind == "number")
    assert v.value == "15万转"
    assert v.number == 150000.0


def test_cert_violation_number_is_none():
    from csm_core.factcheck.checker import check_facts
    rep = check_facts("通过 CCC 认证。", allowed_numbers=set(), allowed_certs=set())
    v = next(v for v in rep.violations if v.kind == "cert")
    assert v.number is None
```

- [ ] **Step 2: 跑测试确认失败**

Run（PYTHONPATH 见文末）：`pytest tests/core/factcheck/test_checker.py -k normalized_number -v`
Expected: FAIL — `Violation` 无 `number` 字段

- [ ] **Step 3: 写实现**

`model.py` `Violation` 加字段（在 `value` 后）：
```python
class Violation(BaseModel):
    kind: Literal["number", "cert"]
    value: str            # 成稿里的原文 token，如 "250AW" / "CCC"
    number: float | None = None  # number 违规的归一值（万已展开），cert=None；前端放行回传它
    sentence: str
    suggestion: str
```
`checker.py` number 违规处填 `number=value`（`value` 是 `extract_number_mentions` 的归一 float）：
```python
        for value, raw in extract_number_mentions(sentence):
            if value not in allowed_numbers:
                violations.append(Violation(
                    kind="number", value=raw, number=value, sentence=sentence,
                    suggestion="改用注入参数表里的数值，或标为通用表述/本次放行",
                ))
```
（cert 违规不传 number，默认 None。）

- [ ] **Step 4: 跑测试确认通过 + 不破既有**

Run: `pytest tests/core/factcheck/ sidecar/tests/test_generate_factcheck_route.py sidecar/tests/test_factcheck_service.py -v`
Expected: PASS（新增字段是加法；若某测试断言 violation 全 dict 相等需补 `number` 键——按需更新）

- [ ] **Step 5: 提交**

```bash
git add csm_core/factcheck/model.py csm_core/factcheck/checker.py tests/core/factcheck/test_checker.py
git commit -m "feat(factcheck): Violation 带归一 number（前端放行万-值用），cert 为 None"
```

---

### Task B2: article store factcheck state + resolveFactcheck

**Files:**
- Modify: `frontend/src/stores/article.ts`
- Test: `frontend/src/stores/__tests__/article.spec.ts`

- [ ] **Step 1: 写失败测试**

`frontend/src/stores/__tests__/article.spec.ts`:
```typescript
import { setActivePinia, createPinia } from "pinia";
import { describe, it, expect, vi, beforeEach } from "vitest";

const postMock = vi.fn();
let capturedHandlers: any = null;
vi.mock("@/stores/sidecar", () => ({
  useSidecar: () => ({ client: { post: postMock, get: vi.fn() } }),
}));
vi.mock("@/api/client", () => ({
  subscribe: (_url: string, handlers: any) => { capturedHandlers = handlers; return () => {}; },
}));
vi.mock("@/composables/useNotifications", () => ({
  useNotifications: () => ({ push: vi.fn() }),
}));

import { useArticle } from "@/stores/article";

describe("article factcheck", () => {
  beforeEach(() => { setActivePinia(createPinia()); postMock.mockReset(); capturedHandlers = null; });

  it("done 带 factcheck.blocked → 填充 factcheck", async () => {
    postMock.mockResolvedValueOnce({ data: { job_id: "j1" } });
    const a = useArticle();
    await a.submit({ keyword: "k", template_id: "t" });
    capturedHandlers.done({
      document: null, final_text: "成稿…",
      factcheck: { blocked: true, violations: [{ kind: "number", value: "15万转", number: 150000, sentence: "…", suggestion: "…" }] },
    });
    expect(a.factcheck?.blocked).toBe(true);
    expect(a.factcheck?.violations).toHaveLength(1);
    expect(a.status).toBe("done");
  });

  it("done 无 factcheck → factcheck=null", async () => {
    postMock.mockResolvedValueOnce({ data: { job_id: "j2" } });
    const a = useArticle();
    await a.submit({ keyword: "k", template_id: "t" });
    capturedHandlers.done({ document: "/p.md", final_text: "x" });
    expect(a.factcheck).toBeNull();
  });

  it("resolveFactcheck ok → 清 factcheck + 设 documentPath", async () => {
    postMock.mockResolvedValueOnce({ data: { job_id: "j3" } });
    const a = useArticle();
    await a.submit({ keyword: "k", template_id: "t" });
    a.lastJobId = "j3";
    a.factcheck = { blocked: true, violations: [] } as any;
    postMock.mockResolvedValueOnce({ data: { ok: true, document: "/out.md", format: "markdown" } });
    const r = await a.resolveFactcheck("成稿", [150000], []);
    expect(r.ok).toBe(true);
    expect(a.factcheck).toBeNull();
    expect(a.documentPath).toBe("/out.md");
  });

  it("resolveFactcheck 仍有违规 → 更新 violations 不清", async () => {
    postMock.mockResolvedValueOnce({ data: { job_id: "j4" } });
    const a = useArticle();
    await a.submit({ keyword: "k", template_id: "t" });
    a.lastJobId = "j4";
    postMock.mockResolvedValueOnce({ data: { ok: false, violations: [{ kind: "cert", value: "CCC", number: null, sentence: "…", suggestion: "…" }] } });
    const r = await a.resolveFactcheck("成稿", [], []);
    expect(r.ok).toBe(false);
    expect(a.factcheck?.violations).toHaveLength(1);
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `npx vitest run src/stores/__tests__/article.spec.ts`
Expected: FAIL — 无 `factcheck` / `resolveFactcheck`

- [ ] **Step 3: 写实现**（`article.ts`）

- `Violation` 类型 + state 字段（在 interface `ArticleState` 加）：
```typescript
export interface FactcheckViolation {
  kind: "number" | "cert";
  value: string;
  number: number | null;
  sentence: string;
  suggestion: string;
}
// ArticleState 内：
  factcheck: { blocked: boolean; violations: FactcheckViolation[] } | null;
```
- `state()` 初值加 `factcheck: null,`。
- `submit` 重置区加 `this.factcheck = null;`。
- `done` handler 末尾（设 status 前后）加：
```typescript
          this.factcheck =
            d.factcheck && d.factcheck.blocked
              ? { blocked: true, violations: d.factcheck.violations ?? [] }
              : null;
```
- 新 action（放在 `exportArticle` 附近）：
```typescript
    /** 事实核对放行重核 + 导出（接 Plan 3 门禁）。released* 为用户勾选放行的项。
     * ok=true → 已导出，清 factcheck；ok=false → 更新剩余 violations。*/
    async resolveFactcheck(
      finalText: string, releasedNumbers: number[], releasedCerts: string[],
    ): Promise<{ ok: boolean; violations?: FactcheckViolation[]; error?: string }> {
      if (!this.lastJobId) return { ok: false, error: "无可核对的任务" };
      const sidecar = useSidecar();
      try {
        const resp = await sidecar.client.post(`/api/generate/${this.lastJobId}/export`, {
          final_text: finalText,
          released_numbers: releasedNumbers,
          released_certs: releasedCerts,
        });
        if (resp.data.ok) {
          this.finalText = finalText;
          this.documentPath = resp.data.document ?? this.documentPath;
          this.format = resp.data.format ?? this.format;
          this.factcheck = null;
          return { ok: true };
        }
        this.factcheck = { blocked: true, violations: resp.data.violations ?? [] };
        return { ok: false, violations: resp.data.violations ?? [] };
      } catch (e: any) {
        return { ok: false, error: e?.response?.data?.detail ?? e?.message ?? String(e) };
      }
    },
```

- [ ] **Step 4: 跑测试确认通过**

Run: `npx vitest run src/stores/__tests__/article.spec.ts`
Expected: PASS（4）

- [ ] **Step 5: 提交**

```bash
git add frontend/src/stores/article.ts frontend/src/stores/__tests__/article.spec.ts
git commit -m "feat(article): store factcheck 状态 + resolveFactcheck（接 Plan 3 export 门禁）"
```

---

# Unit C：FactCheckPanel + ArticleView 接线

### Task C1: `FactCheckPanel.vue` + 组件测试

**Files:**
- Create: `frontend/src/components/article/FactCheckPanel.vue`
- Test: `frontend/src/components/article/__tests__/FactCheckPanel.spec.ts`

- [ ] **Step 1: 写失败测试**（mock `@/stores/article` + toast）

`frontend/src/components/article/__tests__/FactCheckPanel.spec.ts`:
```typescript
import { mount, flushPromises } from "@vue/test-utils";
import { describe, it, expect, vi, beforeEach } from "vitest";

const resolveMock = vi.fn();
const state: any = {
  finalText: "电机 15万转。通过 CCC 认证。",
  factcheck: {
    blocked: true,
    violations: [
      { kind: "number", value: "15万转", number: 150000, sentence: "电机 15万转。", suggestion: "改用参数表数值" },
      { kind: "cert", value: "CCC", number: null, sentence: "通过 CCC 认证。", suggestion: "删除或换实际认证" },
    ],
  },
  resolveFactcheck: resolveMock,
};
vi.mock("@/stores/article", () => ({ useArticle: () => state }));
vi.mock("@/composables/useToast", () => ({ useToast: () => ({ success: vi.fn(), error: vi.fn(), warn: vi.fn() }) }));

import FactCheckPanel from "@/components/article/FactCheckPanel.vue";

describe("FactCheckPanel", () => {
  beforeEach(() => resolveMock.mockReset());

  it("渲染所有违规项 + 句子", () => {
    const w = mount(FactCheckPanel, { props: { open: true } });
    expect(w.text()).toContain("15万转");
    expect(w.text()).toContain("CCC");
    expect(w.text()).toContain("电机 15万转。");
  });

  it("勾选放行后『重新核对并导出』回传归一 number + cert 名", async () => {
    resolveMock.mockResolvedValueOnce({ ok: true });
    const w = mount(FactCheckPanel, { props: { open: true } });
    // 勾两个放行 checkbox
    const boxes = w.findAll("input[type='checkbox']");
    for (const b of boxes) await b.setValue(true);
    const btn = w.findAll("button").find((b) => b.text().includes("重新核对并导出"));
    await btn!.trigger("click");
    await flushPromises();
    expect(resolveMock).toHaveBeenCalledWith(
      state.finalText, [150000], ["CCC"],
    );
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `npx vitest run src/components/article/__tests__/FactCheckPanel.spec.ts`
Expected: FAIL — 组件不存在

- [ ] **Step 3: 写实现**（`FactCheckPanel.vue`；Dialog 镜像导出 modal）

```vue
<script setup lang="ts">
import { computed, ref } from "vue";
import Dialog from "@/components/ui/Dialog.vue";
import Btn from "@/components/ui/Btn.vue";
import Pill from "@/components/ui/Pill.vue";
import { useArticle, type FactcheckViolation } from "@/stores/article";
import { useToast } from "@/composables/useToast";

const open = defineModel<boolean>("open", { default: false });
const article = useArticle();
const toast = useToast();

const submitting = ref(false);
const released = ref<Set<string>>(new Set());

const violations = computed<FactcheckViolation[]>(() => article.factcheck?.violations ?? []);
const vkey = (v: FactcheckViolation) => `${v.kind}:${v.value}`;
function toggle(v: FactcheckViolation) {
  const k = vkey(v);
  if (released.value.has(k)) released.value.delete(k);
  else released.value.add(k);
}
function isReleased(v: FactcheckViolation) { return released.value.has(vkey(v)); }

async function recheckExport() {
  submitting.value = true;
  const nums: number[] = [];
  const certs: string[] = [];
  for (const v of violations.value) {
    if (!isReleased(v)) continue;
    if (v.kind === "number" && v.number != null) nums.push(v.number);
    else if (v.kind === "cert") certs.push(v.value);
  }
  const r = await article.resolveFactcheck(article.finalText, nums, certs);
  submitting.value = false;
  if (r.ok) { toast.success("已通过事实核对并导出"); released.value.clear(); open.value = false; }
  else if (r.error) toast.error(`核对失败：${r.error}`);
  else toast.warn(`仍有 ${r.violations?.length ?? 0} 处未解决（已勾选的可放行，其余请在「成稿」改写）`);
}
</script>

<template>
  <Dialog v-model:open="open" title="事实核对 — 发现疑似编造的数字/认证" size="lg">
    <div class="flex flex-col gap-3">
      <p class="text-sm text-ink/60">
        以下数字/认证不在该型号的事实白名单里。可在「成稿」标签改写后重新核对，或勾选「本次放行」（确认是通用表述、非型号参数）。全部清掉才会导出。
      </p>
      <ul class="flex flex-col gap-2">
        <li
          v-for="(v, i) in violations"
          :key="i"
          class="rounded-lg border border-ink/10 p-3"
        >
          <div class="flex items-center justify-between gap-2">
            <div class="flex items-center gap-2 text-sm">
              <Pill>{{ v.kind === "number" ? "数字" : "认证" }}</Pill>
              <span class="font-medium">{{ v.value }}</span>
            </div>
            <label class="flex items-center gap-1 text-xs text-ink/60">
              <input type="checkbox" :checked="isReleased(v)" @change="toggle(v)" />
              本次放行
            </label>
          </div>
          <div class="mt-1 text-xs text-ink/55">{{ v.sentence }}</div>
          <div class="mt-1 text-[11px] text-ink/40">建议：{{ v.suggestion }}</div>
        </li>
      </ul>
    </div>
    <template #footer>
      <Btn variant="ghost" small :disabled="submitting" @click="open = false">关闭（去改正文）</Btn>
      <Btn variant="solid" small :disabled="submitting || !violations.length" @click="recheckExport">
        {{ submitting ? "核对中…" : "重新核对并导出" }}
      </Btn>
    </template>
  </Dialog>
</template>
```

> 先读 `components/ui/Dialog.vue` 确认 `v-model:open` / `title` / `size` / `#footer` slot 真实 API，照其调整（导出 modal 的 Teleport 样式可参考 ArticleView L2020-2161）。

- [ ] **Step 4: 跑测试确认通过 + 类型**

Run: `npx vitest run src/components/article/__tests__/FactCheckPanel.spec.ts`（PASS 2）
Run: `npx vue-tsc --noEmit`

- [ ] **Step 5: 提交**

```bash
git add frontend/src/components/article/FactCheckPanel.vue frontend/src/components/article/__tests__/FactCheckPanel.spec.ts
git commit -m "feat(article): FactCheckPanel 审查面板（违规列表+放行+重新核对导出）"
```

---

### Task C2: ArticleView 接线（挂面板 + 自动弹 + 拦截改导出）

**Files:**
- Modify: `frontend/src/views/ArticleView.vue`

- [ ] **Step 1: 接线**（最小改动；先读 ArticleView 找导出按钮 + status watcher）

1. import：`import FactCheckPanel from "@/components/article/FactCheckPanel.vue";` + `watch`（若未导入）。
2. 加 ref：`const showFactcheck = ref(false);`
3. watcher（生成被拦自动弹）：
```typescript
watch(
  () => article.factcheck?.blocked,
  (blocked) => { if (blocked) showFactcheck.value = true; },
);
```
4. 模板挂面板（与导出 modal 同层）：`<FactCheckPanel v-model:open="showFactcheck" />`
5. 导出按钮拦截：现有「导出文章」按钮 `@click="showExportModal = true"` 改为：
```typescript
function onExportClick() {
  if (article.factcheck?.blocked) { showFactcheck.value = true; return; }
  showExportModal.value = true;
}
```
按钮 `@click="onExportClick"`；被拦时按钮文案可显示「核对并导出」（`article.factcheck?.blocked ? "核对并导出" : "导出文章"`）。

- [ ] **Step 2: 类型 + 全前端测试**

Run: `npx vue-tsc --noEmit`（ArticleView 无新错；emit 则还原 vite.config.js）
Run: `npx vitest run`（全绿，无回归）

- [ ] **Step 3: 提交**

```bash
git add frontend/src/views/ArticleView.vue
git commit -m "feat(article): ArticleView 挂事实核对面板 + 拦截时导出走核对"
```

---

### Task C3: 整包 + 手动验证清单

- [ ] **Step 1: 后端 + 前端全测**

Run（后端）: `pytest tests/core/factcheck/ sidecar/tests/ -q`（factcheck 相关绿；预存 8 失败无关）
Run（前端）: `npx vitest run`（全绿）+ `npx vue-tsc --noEmit`

- [ ] **Step 2: 手动验证清单（进 PR body）**：
  - SkillEditView：编辑某 skill → 角色下拉显示当前 role（旧 skill = 人设）；切去AI味 → 保存 → 重开仍是去AI味。
  - 事实核对：开 `brand_memory.inject + factcheck`，锁型号生成 → 诱导 LLM 写白名单外数字（如「18万转」）→ 生成完成弹审查面板列违规 → 勾放行「18万转」→「重新核对并导出」成功；或不放行、去「成稿」删掉该数字 → 重新核对通过。
  - 万-值放行确实生效（number 回传归一值）。

---

## 验收对照（spec §4.2/§5/§6/§9）

| spec 验收 | 本 Plan | 证据 |
|---|---|---|
| §5/§7 `SkillEditView` 暴露 role | A1 | `SkillEditView.spec` payload 含 role |
| §4.2 导出被拦 → 列出 → 可放行（①改文案②标通用③本次放行） | B2+C1 | store/panel 测试 + 手动 |
| §9.3 防幻觉：编造数字被拦 + 可放行 | 接 Plan 3 门禁 + 面板 | 手动（真生成） |
| 万-值放行正确 | B1 `Violation.number` | `test_number_violation_carries_normalized_number` |

---

## 不做（Phase 2 / Phase 3）

- skill 链多-pass（人设→去AI味→平台适配）执行、`role: platform`、逐 pass 预览 → Phase 2。
- 「浏览」「录入」tab、vault 写入器 → Phase 3。
- 放行的会话级持久化/固化进白名单 → Phase 3（现为本次会话级，符合 spec §4.2）。

---

## Self-Review（对照 spec + 决定）

- **Spec 覆盖**：§5 role UI→A1；§4.2 审查面板+放行→B2/C1；万-值放行正确→B1；§6 收口（素材库已 5a）。✅
- **占位符**：后端小修完整代码；store/panel 完整代码 + 测试；ArticleView 接线给明确步骤（最小 diff，实测按钮/watcher 位置以实读为准）。✅
- **类型一致性**：`Violation.number`（后端 float|None）↔ store `FactcheckViolation.number`（number|null）↔ panel 放行 `v.number` 一致；`resolveFactcheck(finalText, number[], string[])` 与后端 `ResolveFactcheckBody`(final_text/released_numbers/released_certs) 一致。✅
- **零回归**：`Violation.number` 加法；store/面板/接线纯加；happy-path 导出不变（未拦时 factcheck=null，导出按钮走原 modal）。✅

---

## 测试调用

**后端**：`Set-Location D:\CSM\.claude\worktrees\phase1-plan5b; $env:PYTHONPATH="D:\CSM\.claude\worktrees\phase1-plan5b;D:\CSM\.claude\worktrees\phase1-plan5b\sidecar"; D:/CSM/.venv/Scripts/python.exe -m pytest <args>`
**前端**：`Set-Location D:\CSM\.claude\worktrees\phase1-plan5b\frontend; npx vitest run <file>`；类型 `npx vue-tsc --noEmit`（emit 则 `git checkout -- frontend/vite.config.js`）。
