# Phase 1 — Plan 6（补遗）：品牌记忆设置卡（让 Phase 1 能从 UI 开）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在「设置」加一张「品牌记忆」卡——`inject`/`factcheck` 开关 + `own_brands`（自有品牌）+ 两个 token cap，让 Phase 1 的注入/事实核对/素材库注入预览**能从 UI 开**（现在只能手改 `settings.json`）。

**Architecture:** **纯前端**——`config` 后端早已就位：`GET /api/config` 返回完整 AppConfig（含 `brand_memory`），`PATCH /api/config` 对嵌套 dict **深合并**（`config_service._deep_merge`），故卡片发 `{brand_memory: {inject: true}}` 会保留其余 4 个字段。新 `BrandMemoryCard.vue`（镜像 `MiningPromptsCard` 结构，但读写走 `useConfig` store）+ SettingsView 加一个「品牌记忆」section。

**Tech Stack:** Vue 3 setup + Pinia(`useConfig`) + Vitest + vue-tsc。无后端改动。

参考：Phase 1 `BrandMemoryConfig`（Plan 3）；路线图 §1。

---

## 关键设计决定（已确认 / 已定）

1. **纯前端、零后端改**：`/api/config` GET 返回 `brand_memory`、PATCH 深合并嵌套 dict（已验证 `config_service._deep_merge`）→ 卡片发**部分** patch（`{brand_memory: {字段: 值}}`）即安全保留其余字段。
2. **硬编码中文**（同 5a/5b；代码库无 i18n）。
3. **专设「品牌记忆」settings section**（workflow 组，图标 `vault`）——比塞进「模型」更可发现（用户要找「怎么开注入」）。
4. **`own_brands` 用分隔符输入**（顿号/逗号/英文逗号都接受）→ commit 时 split+trim+去空成 list。代码库无 tag 编辑组件，分隔输入最简。
5. **读写走 `useConfig` store**（非自定义端点）：`cfg.data.brand_memory` 读；`cfg.patch({brand_memory: {...}})` 写。toggle 立即存、文本/数字 blur 存。
6. **前端验证 Vitest + vue-tsc**；端到端（开关→真生成注入生效）= 用户手动。镜像 `MiningPromptsCard`/`XhsPromptsCard` 结构 + 其 `__tests__` 测试范式。

---

## File Structure

- **Create** `frontend/src/components/settings/BrandMemoryCard.vue` — 卡片（2 开关 + own_brands + 2 cap）。
- **Test (Create)** `frontend/src/components/settings/__tests__/BrandMemoryCard.spec.ts`。
- **Modify** `frontend/src/views/SettingsView.vue` — `SECTIONS` 加「品牌记忆」+ 对应 `<template v-else-if>` 挂卡 + import。

---

# Unit：品牌记忆设置卡

### Task A: `BrandMemoryCard.vue` + 组件测试

**Files:**
- Create: `frontend/src/components/settings/BrandMemoryCard.vue`
- Test: `frontend/src/components/settings/__tests__/BrandMemoryCard.spec.ts`

- [ ] **Step 1: 写失败测试**（mock `@/stores/config` + `@/composables/useToast`；范式照 `XhsPromptsCard.spec.ts`）

`frontend/src/components/settings/__tests__/BrandMemoryCard.spec.ts`:
```typescript
import { describe, it, expect, vi, beforeEach } from "vitest";
import { mount, flushPromises } from "@vue/test-utils";

const { patchMock, loadMock, state } = vi.hoisted(() => {
  const state: any = {
    data: { brand_memory: { inject: false, factcheck: false, own_brands: ["CEWEY"], inject_variant_cap: 3, inject_endorsement_cap: 5 } },
    loading: false, error: null,
  };
  return { patchMock: vi.fn(), loadMock: vi.fn(), state };
});
vi.mock("@/stores/config", () => ({
  useConfig: () => ({ ...state, load: loadMock, patch: patchMock }),
}));
const { toastSuccess, toastError } = vi.hoisted(() => ({ toastSuccess: vi.fn(), toastError: vi.fn() }));
vi.mock("@/composables/useToast", () => ({
  useToast: () => ({ success: toastSuccess, error: toastError, warn: vi.fn() }),
}));

import BrandMemoryCard from "@/components/settings/BrandMemoryCard.vue";

describe("BrandMemoryCard", () => {
  beforeEach(() => { patchMock.mockReset().mockResolvedValue(undefined); toastSuccess.mockClear(); });

  it("挂载反映 config 的 inject/own_brands", async () => {
    const w = mount(BrandMemoryCard);
    await flushPromises();
    // own_brands 输入框含 CEWEY
    expect(w.html()).toContain("CEWEY");
  });

  it("打开 inject 开关 → patch({brand_memory:{inject:true}})", async () => {
    const w = mount(BrandMemoryCard);
    await flushPromises();
    await w.find("[data-test='toggle-inject'] input, [data-test='toggle-inject'] button, [data-test='toggle-inject']").trigger("click");
    await flushPromises();
    expect(patchMock).toHaveBeenCalledWith({ brand_memory: { inject: true } });
  });

  it("own_brands 改「CEWEY、希喂」commit → patch own_brands 为 list", async () => {
    const w = mount(BrandMemoryCard);
    await flushPromises();
    const inp = w.find("[data-test='own-brands'] input");
    await inp.setValue("CEWEY、希喂");
    await inp.trigger("blur");
    await flushPromises();
    expect(patchMock).toHaveBeenCalledWith({ brand_memory: { own_brands: ["CEWEY", "希喂"] } });
  });
});
```

> 注：FormToggle 的可点元素以实读为准（`[data-test='toggle-inject']` 包住 FormToggle）。测试断言核心是 **patch body**，按 FormToggle 真实 DOM 调稳触发方式。

- [ ] **Step 2: 跑测试确认失败**

Run: `Set-Location D:\CSM\.claude\worktrees\phase1-plan6\frontend; npx vitest run src/components/settings/__tests__/BrandMemoryCard.spec.ts`
Expected: FAIL — 组件不存在

- [ ] **Step 3: 写实现**（先读 `components/settings/MiningPromptsCard.vue` 取卡片外壳样式 + `forms/FormToggle.vue`/`FormInput.vue`/`FormField.vue` 真实 props）

`frontend/src/components/settings/BrandMemoryCard.vue`:
```vue
<script setup lang="ts">
/**
 * 品牌记忆设置卡（Phase 1 Plan 6 补遗）——让 brand_memory.* 能从 UI 开。
 * 读写走 useConfig；PATCH /api/config 对嵌套 dict 深合并，故每个控件只发自己那一个字段。
 */
import { onMounted, ref } from "vue";

import Icon from "@/components/ui/Icon.vue";
import Spinner from "@/components/ui/Spinner.vue";
import FormField from "@/components/forms/FormField.vue";
import FormToggle from "@/components/forms/FormToggle.vue";
import FormInput from "@/components/forms/FormInput.vue";
import { useConfig } from "@/stores/config";
import { useToast } from "@/composables/useToast";

const cfg = useConfig();
const toast = useToast();
const loading = ref(false);

const inject = ref(false);
const factcheck = ref(false);
const ownBrands = ref("");
const variantCap = ref<number>(3);
const endorsementCap = ref<number>(5);

function syncFromConfig() {
  const bm = (cfg.data?.brand_memory ?? {}) as Record<string, any>;
  inject.value = !!bm.inject;
  factcheck.value = !!bm.factcheck;
  ownBrands.value = (bm.own_brands ?? []).join("、");
  variantCap.value = Number(bm.inject_variant_cap ?? 3);
  endorsementCap.value = Number(bm.inject_endorsement_cap ?? 5);
}

onMounted(async () => {
  if (!cfg.data) {
    loading.value = true;
    try { await cfg.load(); } catch { /* error 由 store 持有 */ } finally { loading.value = false; }
  }
  syncFromConfig();
});

async function save(patch: Record<string, unknown>) {
  try {
    await cfg.patch({ brand_memory: patch });
    toast.success("已保存");
  } catch (e: any) {
    toast.error(`保存失败：${cfg.error ?? e?.message ?? e}`);
    syncFromConfig();   // 回滚 UI 到真实值
  }
}

function onInject(v: boolean) { inject.value = v; save({ inject: v }); }
function onFactcheck(v: boolean) { factcheck.value = v; save({ factcheck: v }); }
function commitOwnBrands() {
  const list = ownBrands.value.split(/[、,，]/).map((s) => s.trim()).filter(Boolean);
  save({ own_brands: list });
}
function commitVariantCap(v: number | string | null) {
  const n = Math.max(1, Number(v) || 3); variantCap.value = n; save({ inject_variant_cap: n });
}
function commitEndorsementCap(v: number | string | null) {
  const n = Math.max(1, Number(v) || 5); endorsementCap.value = n; save({ inject_endorsement_cap: n });
}
</script>

<template>
  <div class="rounded-card" :style="{ background: 'var(--card-2)', padding: '16px' }">
    <div class="flex items-center gap-2">
      <span class="inline-flex h-7 w-7 items-center justify-center rounded-lg" :style="{ background: 'var(--card)' }">
        <Icon name="vault" :size="15" />
      </span>
      <div>
        <div class="font-display text-[13.5px] font-semibold">品牌记忆</div>
        <div class="mt-0.5 text-[11px]" :style="{ color: 'var(--ink-4)' }">
          生成时注入型号事实 · 导出前事实核对 · 自有品牌
        </div>
      </div>
    </div>

    <div v-if="loading" class="mt-3 flex items-center gap-2 text-sm" :style="{ color: 'var(--ink-3)' }">
      <Spinner :size="14" /> 读取中…
    </div>

    <div v-else class="mt-4 flex flex-col gap-4">
      <FormField label="注入型号记忆" hint="生成时把命中型号的参数/认证/话术注入 LLM（关=今天行为）">
        <span data-test="toggle-inject">
          <FormToggle :model-value="inject" @update:model-value="onInject" />
        </span>
      </FormField>

      <FormField label="导出前事实核对" hint="成稿里白名单外的数字/认证拦截导出，弹审查面板放行">
        <span data-test="toggle-factcheck">
          <FormToggle :model-value="factcheck" @update:model-value="onFactcheck" />
        </span>
      </FormField>

      <FormField label="自有品牌" hint="判定主推 vs 竞品（顿号/逗号分隔，如 CEWEY、希喂）">
        <span data-test="own-brands">
          <FormInput :model-value="ownBrands" debounce="blur"
            @update:model-value="(v: any) => (ownBrands = String(v ?? ''))"
            @commit="commitOwnBrands" placeholder="CEWEY、希喂" />
        </span>
      </FormField>

      <div class="flex gap-4">
        <FormField label="话术变体上限/维度" hint="token 预算">
          <FormInput :model-value="variantCap" type="number" width="90" debounce="blur"
            @commit="commitVariantCap" />
        </FormField>
        <FormField label="背书注入条数上限" hint="token 预算">
          <FormInput :model-value="endorsementCap" type="number" width="90" debounce="blur"
            @commit="commitEndorsementCap" />
        </FormField>
      </div>
    </div>
  </div>
</template>
```

> 实读校准：`FormToggle` 用 `:model-value` + `@update:model-value`（boolean）；`FormInput` 的 `@commit` 在 blur 触发（见 forms/FormInput.vue）。若 `@commit` 名不符，用 `@update:model-value` + blur 自行触发。卡壳样式以 `MiningPromptsCard` 为基准微调（`rounded-card`/`var(--card-2)`/icon-badge）。

- [ ] **Step 4: 跑测试 + 类型**

Run: `npx vitest run src/components/settings/__tests__/BrandMemoryCard.spec.ts`（PASS）
Run: `npx vue-tsc --noEmit`（BrandMemoryCard 无新错；emit vite.config.js 则 `git checkout -- frontend/vite.config.js`；package-lock 被 prune 则还原）

- [ ] **Step 5: 提交**

```bash
git add frontend/src/components/settings/BrandMemoryCard.vue frontend/src/components/settings/__tests__/BrandMemoryCard.spec.ts
git commit -m "feat(settings): 品牌记忆卡（inject/factcheck 开关 + own_brands + cap，接 config）"
```

---

### Task B: SettingsView 挂「品牌记忆」section

**Files:**
- Modify: `frontend/src/views/SettingsView.vue`

- [ ] **Step 1: 接线**（SettingsView 大文件——先读 `SECTIONS` 数组 + 各 `<template v-else-if="section===...">` 块定位）

1. import（与其它 settings card import 同处）：`import BrandMemoryCard from "@/components/settings/BrandMemoryCard.vue";`
2. `SECTIONS` 数组加一项（workflow 组，放「模型」附近）：
```typescript
{ k: "brand-memory", l: "品牌记忆", icon: "vault", sub: "型号注入 · 事实核对 · 自有品牌", group: "workflow" },
```
3. 右栏加对应 section 模板块（照其它 `<template v-else-if="section === '...'">` 写法）：
```vue
<template v-else-if="section === 'brand-memory'">
  <BrandMemoryCard />
</template>
```

- [ ] **Step 2: 类型 + 全前端测试**

Run: `npx vue-tsc --noEmit`（SettingsView 无新错；emit 则还原 vite.config.js）
Run: `npx vitest run`（全绿，无回归）

- [ ] **Step 3: 提交**

```bash
git add frontend/src/views/SettingsView.vue
git commit -m "feat(settings): 设置加「品牌记忆」section 挂 BrandMemoryCard"
```

---

### Task C: 整包检查 + 手动验证清单

- [ ] **Step 1: 全前端测 + 类型**

Run: `npx vitest run`（全绿）+ `npx vue-tsc --noEmit`（还原 vite.config.js）
Expected: 无回归。

- [ ] **Step 2: 手动验证清单（进 PR body）**：
  - 设置 → 「品牌记忆」section 可见；开关反映当前 config（默认全关）。
  - 开「注入型号记忆」→ 刷新/重进设置仍为开（落盘 settings.json）。
  - own_brands 改「CEWEY、希喂」→ 保存 → 重进显示两项。
  - 开 inject 后去「素材库」某型号看注入预览 / 生成一篇 → 事实注入生效；开 factcheck 后诱导越界 → 弹审查面板。

---

## 验收对照

| 目标 | 本 Plan | 证据 |
|---|---|---|
| inject/factcheck 能从 UI 开 | A 卡 + B section | `BrandMemoryCard.spec` patch 断言 + 手动 |
| own_brands 可编辑 | A own_brands 分隔输入 | spec own_brands list 断言 |
| token cap 可调 | A 两 number 输入 | 手动 |
| 不丢其它 brand_memory 字段 | PATCH 深合并（已验证）+ 部分 patch | 后端既有，partial patch 安全 |

---

## 不做

- 后端改动（config GET/PATCH 已支持）。
- own_brands 的 tag/chip 富编辑（分隔输入够用）。
- Plan 4 skill 实盘应用（另一个 gated runbook）。

---

## Self-Review

- **覆盖**：inject/factcheck 开关→A；own_brands→A；cap→A；section 入口→B。✅
- **占位符**：卡 SFC 完整；测试完整；SettingsView 接线给精确 3 步（大文件，按实读定位）。✅
- **类型一致**：`cfg.data.brand_memory.{inject,factcheck,own_brands,inject_variant_cap,inject_endorsement_cap}`（后端 BrandMemoryConfig）↔ 卡 refs ↔ patch body `{brand_memory:{...}}`（深合并）一致。✅
- **零回归**：纯加法（新卡 + 新 section + import）；既有 settings section 不动；PATCH 部分更新深合并不伤其它字段。✅

---

## 测试调用

`Set-Location D:\CSM\.claude\worktrees\phase1-plan6\frontend; npx vitest run <file>`；类型 `npx vue-tsc --noEmit`（emit 则 `git checkout -- frontend/vite.config.js`，package-lock 被 prune 则 `git checkout -- frontend/package-lock.json`）。
