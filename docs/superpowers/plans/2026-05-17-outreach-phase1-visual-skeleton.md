# Outreach Phase 1 Visual Skeleton — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development.

**Goal:** Translate `examples/CSM-RE1-handoff/csm-re1/project/src/screens/outreach.jsx` (1067 lines React) into Vue 3 components inside `frontend/src/`, matching the design pixel-for-pixel. Backend untouched.

**Architecture:** Reuse existing design tokens in `frontend/src/style.css` (`--card`, `--primary`, etc — already verbatim-ported from the same CSM-RE1 V1 origin as the jsx). Reuse existing `Btn` / `Card` / `Icon` / `Pill` UI primitives with small extensions. Add 3 new ui components (`Avatar`, `Blob`, `PlatformPickerCard`). Rewrite the 4 mining view files.

**Reference:**
- Source design: `examples/CSM-RE1-handoff/csm-re1/project/src/screens/outreach.jsx` (or wherever the path resolves — adjust per environment)
- Spec: `docs/superpowers/specs/2026-05-17-outreach-phase1-visual-skeleton-design.md`

---

## Task 1: Extend Icon.vue with 18 new icons

**Files:** Modify `frontend/src/components/ui/Icon.vue`

The current `PATHS` dict in Icon.vue has ~20 icons. Phase 1 needs ~18 more. All paths follow Lucide-style 24x24 viewBox with `stroke="currentColor"`.

- [ ] **Step 1: Read the current Icon.vue PATHS dict** (around lines 17-50) to confirm what's already there and to copy the existing style (stroke-based, single line per icon).

- [ ] **Step 2: Append these entries to PATHS** (after `info` line, preserving alphabetical sort isn't required since existing entries aren't alphabetical):

```typescript
  spark: '<path d="M12 3v3M12 18v3M5.5 5.5l2 2M16.5 16.5l2 2M3 12h3M18 12h3M5.5 18.5l2-2M16.5 7.5l2-2"/>',
  comment: '<path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/>',
  copy: '<rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>',
  more: '<circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/><circle cx="5" cy="12" r="1"/>',
  stack: '<polygon points="12 2 2 7 12 12 22 7 12 2"/><polyline points="2 17 12 22 22 17"/><polyline points="2 12 12 17 22 12"/>',
  eye: '<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/>',
  heart: '<path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"/>',
  clock: '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>',
  key: '<path d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.778 7.778 5.5 5.5 0 0 1 7.777-7.777zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4"/>',
  lock: '<rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>',
  warn: '<path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>',
  download: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>',
  sort: '<path d="M3 6h18"/><path d="M7 12h10"/><path d="M11 18h2"/>',
  pause: '<rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/>',
  external: '<path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/>',
  video: '<polygon points="23 7 16 12 23 17 23 7"/><rect x="1" y="5" width="15" height="14" rx="2" ry="2"/>',
  play: '<polygon points="5 3 19 12 5 21 5 3"/>',
```

(Existing entries `arrowDown`, `check`, `x`, `plus`, `search`, `wand` are already present — do not duplicate.)

- [ ] **Step 3: Smoke test by importing Icon and rendering one of the new names**

Run: `pnpm --filter frontend build`
Expected: zero errors. (No runtime check needed — the icons are only `<path>` strings; the failure mode would be a SVG with no children, which Vue tolerates.)

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/ui/Icon.vue
git commit -m "feat(ui): add 18 new icons for Outreach Phase 1 (spark/eye/heart/clock/key/lock/etc)"
```

---

## Task 2: Add `dark` prop to Card.vue

**Files:** Modify `frontend/src/components/ui/Card.vue`

- [ ] **Step 1: Read Card.vue** (27 lines, already known) to confirm current shape.

- [ ] **Step 2: Add `dark` boolean prop and conditional styling**

Replace the whole file with:

```vue
<script setup lang="ts">
/**
 * Base card surface — paper-coloured background, soft shadow, density
 * padding driven by --density-pad. Mirrors the ``Card`` primitive in
 * CSM-RE1（V1）/src/ui.jsx.
 */
defineProps<{
  /** Use the deeper ``--card-2`` shade (for nested or "muted" cards). */
  muted?: boolean;
  /** Drop the inner padding — for cards that want their own layout. */
  padless?: boolean;
  /** Dark hero treatment — used by OutreachHero. */
  dark?: boolean;
}>();
</script>

<template>
  <section
    class="transition-colors"
    :class="[
      dark
        ? 'bg-dark text-card border-transparent'
        : muted
          ? 'bg-card-2 border-line'
          : 'bg-card border-line',
      padless ? '' : 'pad-d',
      !dark && 'border',
    ]"
    :style="{ borderRadius: 'var(--radius-card)' }"
  >
    <slot />
  </section>
</template>
```

- [ ] **Step 3: Verify build**

Run: `pnpm --filter frontend build`
Expected: pass.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/ui/Card.vue
git commit -m "feat(ui): Card.vue add dark prop for hero treatments"
```

---

## Task 3: Create Avatar.vue

**Files:** Create `frontend/src/components/ui/Avatar.vue`

Simple "first character in a colored circle" avatar.

- [ ] **Step 1: Write the component**

```vue
<script setup lang="ts">
/**
 * Tiny first-letter avatar used in author chips. Ported from CSM-RE1
 * ui.jsx::Avatar. If no ``color`` prop is supplied we hash the name
 * into one of a handful of palette colors so repeated renders are
 * stable.
 */
const props = withDefaults(
  defineProps<{
    name: string;
    size?: number;
    /** Background color — pass an explicit color or let us hash one. */
    color?: string;
  }>(),
  { size: 24 },
);

const PALETTE = [
  "#ee6a2a", "#f5c042", "#7a9b5e", "#5b8def",
  "#c25d8f", "#9f7ab0", "#d8946a", "#5fa8b3",
];

function hashColor(name: string): string {
  let h = 0;
  for (const c of name) h = (h * 31 + c.charCodeAt(0)) | 0;
  return PALETTE[Math.abs(h) % PALETTE.length];
}

const bg = () => props.color || hashColor(props.name || "?");
const letter = () => (props.name || "?").trim().slice(0, 1).toUpperCase();
</script>

<template>
  <span
    class="inline-flex items-center justify-center font-semibold text-white flex-shrink-0"
    :style="{
      width: size + 'px',
      height: size + 'px',
      borderRadius: '999px',
      background: bg(),
      fontSize: Math.max(9, size * 0.42) + 'px',
      lineHeight: 1,
    }"
  >
    {{ letter() }}
  </span>
</template>
```

- [ ] **Step 2: Verify build**

Run: `pnpm --filter frontend build`
Expected: pass.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/ui/Avatar.vue
git commit -m "feat(ui): Avatar — first-letter circle, name-hash color"
```

---

## Task 4: Create Blob.vue

**Files:** Create `frontend/src/components/ui/Blob.vue`

A blurred glow div used as hero decoration.

- [ ] **Step 1: Write the component**

```vue
<script setup lang="ts">
/**
 * Soft blurred decoration blob — used to recreate the warm glow on
 * dark hero cards. Heavy CSS blur turns a solid round div into a
 * lighting effect. Always pointer-events: none.
 */
withDefaults(
  defineProps<{
    color: string;
    size?: number;
    top?: number | string;
    left?: number | string;
    right?: number | string;
    bottom?: number | string;
    opacity?: number;
  }>(),
  { size: 200, opacity: 0.35 },
);
</script>

<template>
  <span
    aria-hidden="true"
    class="blur-blob"
    :style="{
      position: 'absolute',
      width: size + 'px',
      height: size + 'px',
      borderRadius: '999px',
      background: color,
      opacity,
      top: top != null ? (typeof top === 'number' ? top + 'px' : top) : undefined,
      left: left != null ? (typeof left === 'number' ? left + 'px' : left) : undefined,
      right: right != null ? (typeof right === 'number' ? right + 'px' : right) : undefined,
      bottom: bottom != null ? (typeof bottom === 'number' ? bottom + 'px' : bottom) : undefined,
    }"
  />
</template>
```

(`.blur-blob` class is already in `style.css:179` with `filter: blur(40px); pointer-events: none;`)

- [ ] **Step 2: Verify build**

Run: `pnpm --filter frontend build`

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/ui/Blob.vue
git commit -m "feat(ui): Blob — blurred glow decoration for hero cards"
```

---

## Task 5: Create PlatformPickerCard.vue

**Files:** Create `frontend/src/components/mining/PlatformPickerCard.vue`

One platform's card inside the new StartJobModal — shows letter badge + name + login status.

- [ ] **Step 1: Write the component**

```vue
<script setup lang="ts">
import Icon from "@/components/ui/Icon.vue";
import type { Platform } from "@/stores/mining";

const props = defineProps<{
  platform: Platform;
  picked: boolean;
  loggedIn: boolean;
}>();

defineEmits<{
  (e: "toggle"): void;
  (e: "login"): void;
}>();

const META: Record<Platform, { l: string; letter: string; color: string }> = {
  bilibili: { l: "B 站", letter: "B", color: "#fb7299" },
  douyin: { l: "抖音", letter: "D", color: "#1c1a17" },
  kuaishou: { l: "快手", letter: "K", color: "#ff6633" },
};

const meta = () => META[props.platform];
</script>

<template>
  <button
    @click="loggedIn ? $emit('toggle') : $emit('login')"
    :style="{
      position: 'relative',
      textAlign: 'left',
      borderRadius: '14px',
      padding: '12px 12px 11px',
      background: picked ? 'var(--card-white)' : 'var(--card-2)',
      border: picked ? `1.5px solid ${meta().color}` : '1.5px solid transparent',
      opacity: loggedIn ? 1 : 0.62,
      transition: 'all .15s',
      cursor: 'pointer',
    }"
  >
    <div class="flex items-center gap-2">
      <span
        :style="{
          width: '26px', height: '26px', borderRadius: '8px',
          background: meta().color, color: '#fff',
          display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
          fontSize: '12px', fontWeight: 800,
        }"
      >{{ meta().letter }}</span>
      <span class="font-display font-semibold text-[13.5px]">{{ meta().l }}</span>
      <span
        v-if="picked"
        :style="{
          marginLeft: 'auto',
          width: '16px', height: '16px', borderRadius: '999px',
          background: meta().color, color: '#fff',
          display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
        }"
      ><Icon name="check" :size="10"/></span>
    </div>
    <div
      class="text-[10.5px] mt-2 flex items-center gap-1"
      :style="{ color: loggedIn ? '#4d6b2f' : 'var(--red)' }"
    >
      <template v-if="loggedIn">
        <Icon name="check" :size="10"/> 已登录
      </template>
      <template v-else>
        <Icon name="lock" :size="10"/> 未登录
      </template>
    </div>
  </button>
</template>
```

(We currently can't distinguish "即将过期" from "未登录" because monitor.db's `platform_credentials.cooldown_until` isn't surfaced; treat that as a Phase 2 enhancement.)

- [ ] **Step 2: Verify build**

Run: `pnpm --filter frontend build`

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/mining/PlatformPickerCard.vue
git commit -m "feat(mining-fe): PlatformPickerCard for new StartJobModal"
```

---

## Task 6: Rewrite JobProgressCard.vue → OutreachHero.vue

**Files:**
- Create: `frontend/src/components/mining/OutreachHero.vue`
- Delete (or keep as transient until Task 9 finishes wiring): `frontend/src/components/mining/JobProgressCard.vue` — defer the delete to Task 11 so we don't break MiningView mid-flight

Translate the dark hero (jsx lines 848-916) into Vue. The hero has two states:

- **Running**: shows current task (keyword + platforms + progress + 暂停/历史 + 4 KPI)
- **Idle (no activeJob)**: shows just the 4 KPI summary; left side compresses to a small "起一个抓取任务" CTA

Phase 1 just covers the **running** state. Idle state can render a placeholder ("没有进行中的任务 — 点右上角新建抓取任务" or similar).

- [ ] **Step 1: Write the component**

```vue
<script setup lang="ts">
import { computed } from "vue";
import Card from "@/components/ui/Card.vue";
import Btn from "@/components/ui/Btn.vue";
import Icon from "@/components/ui/Icon.vue";
import Blob from "@/components/ui/Blob.vue";
import PlatformChip from "./PlatformChip.vue";
import type { MiningJob, Platform } from "@/stores/mining";

const props = defineProps<{
  job: MiningJob | null;
  counts: { unread: number; done: number; all: number };
}>();

defineEmits<{
  (e: "cancel"): void;
}>();

const totalProgress = computed(() => {
  if (!props.job) return { got: 0, target: 0 };
  let got = 0, target = 0;
  for (const p of props.job.platforms) {
    const pp = props.job.progress[p as Platform];
    if (pp) { got += pp.got; target += pp.target; }
  }
  return { got, target };
});

const isRunning = computed(() =>
  props.job && ["pending", "running"].includes(props.job.status)
);

const startedLabel = computed(() => {
  if (!props.job?.started_at) return "";
  const d = new Date(props.job.started_at);
  return `今天 ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
});
</script>

<template>
  <Card dark padless style="position: relative; overflow: hidden;">
    <Blob color="#ee6a2a" :size="260" :top="-60" :left="50" :opacity="0.42"/>
    <Blob color="#fb7299" :size="220" :top="40" :left="460" :opacity="0.32"/>
    <div
      class="relative grid items-center"
      style="grid-template-columns: 1.4fr 1fr; gap: 24px; padding: var(--density-pad);"
    >
      <!-- 左半 -->
      <div v-if="job && isRunning">
        <div class="flex items-center gap-2">
          <span :style="{ width: '6px', height: '6px', borderRadius: '999px', background: 'var(--primary)', boxShadow: '0 0 0 4px rgba(238,106,42,0.22)' }"/>
          <span class="text-[10.5px] uppercase tracking-[1.5px]" style="color: rgba(255,255,255,0.55)">
            正在抓取 · {{ startedLabel }}
          </span>
        </div>
        <div class="font-display font-bold mt-2.5" style="font-size: 28px; color: #fbf7ec; letter-spacing: -0.5px;">
          「{{ job.keyword }}」
        </div>
        <div class="flex items-center gap-1.5 mt-3 flex-wrap">
          <PlatformChip v-for="p in job.platforms" :key="p" :k="p as Platform"/>
          <span class="text-[11px] ml-1" style="color: rgba(255,255,255,0.45)">
            · 每平台 {{ job.target_per_platform }} 条
          </span>
        </div>
        <!-- progress bar -->
        <div class="mt-5">
          <div class="flex items-baseline justify-between mb-1.5">
            <span class="text-[11px]" style="color: rgba(255,255,255,0.55)">进度</span>
            <span class="font-mono text-[11.5px]" style="color: #fbf7ec">
              {{ totalProgress.got }} / {{ totalProgress.target }}
            </span>
          </div>
          <div :style="{ height: '6px', background: 'rgba(255,255,255,0.10)', borderRadius: '999px', overflow: 'hidden' }">
            <div :style="{ height: '100%', width: totalProgress.target > 0 ? (totalProgress.got / totalProgress.target * 100) + '%' : '0%', background: 'linear-gradient(90deg, var(--yellow), var(--primary))', borderRadius: '999px' }"/>
          </div>
        </div>
        <div class="flex items-center gap-2 mt-4">
          <Btn variant="soft" small @click="$emit('cancel')">
            <Icon name="pause" :size="11"/> 暂停
          </Btn>
          <Btn variant="ghost" small disabled style="color: rgba(255,255,255,0.65)">
            查看历史任务
          </Btn>
        </div>
      </div>

      <!-- 左半: idle -->
      <div v-else>
        <div class="text-[10.5px] uppercase tracking-[1.5px]" style="color: rgba(255,255,255,0.45)">
          Outreach · 闲置
        </div>
        <div class="font-display font-bold mt-2.5" style="font-size: 24px; color: #fbf7ec; letter-spacing: -0.5px;">
          没有进行中的任务
        </div>
        <div class="text-[12px] mt-2" style="color: rgba(255,255,255,0.6)">
          点右上「新建抓取任务」起一个吧。
        </div>
      </div>

      <!-- 右半: 4 KPI 卡片 -->
      <div class="grid grid-cols-2 gap-2.5">
        <div
          v-for="s in [
            { l: '累计抓取', v: totalProgress.got || counts.all, sub: '本任务', tone: 'primary' },
            { l: '待评论', v: counts.unread, sub: '未处理', tone: 'yellow' },
            { l: '已评论', v: counts.done, sub: '已留言', tone: 'green' },
            { l: '留存率', v: '—', sub: '近 24h', tone: 'neutral' },
          ]"
          :key="s.l"
          :style="{
            background: 'rgba(255,255,255,0.06)',
            border: '1px solid rgba(255,255,255,0.06)',
            borderRadius: '14px',
            padding: '12px 14px',
          }"
        >
          <div class="text-[10.5px] uppercase tracking-[1.2px]" style="color: rgba(255,255,255,0.5)">{{ s.l }}</div>
          <div
            class="font-display font-bold mt-1.5"
            :style="{
              fontSize: '26px', letterSpacing: '-0.6px',
              color: s.tone === 'primary' ? 'var(--primary)' :
                     s.tone === 'yellow' ? 'var(--yellow)' :
                     s.tone === 'green' ? '#aec890' : '#fbf7ec',
            }"
          >{{ s.v }}</div>
          <div class="text-[10.5px] mt-0.5" style="color: rgba(255,255,255,0.45)">{{ s.sub }}</div>
        </div>
      </div>
    </div>
  </Card>
</template>
```

- [ ] **Step 2: Also create `PlatformChip.vue` it imports**

Create `frontend/src/components/mining/PlatformChip.vue`:

```vue
<script setup lang="ts">
import type { Platform } from "@/stores/mining";

const props = withDefaults(
  defineProps<{ k: Platform; size?: "sm" | "md" }>(),
  { size: "sm" },
);

const META: Record<Platform, { l: string; letter: string; color: string; dark: string }> = {
  bilibili: { l: "B 站", letter: "B", color: "#fb7299", dark: "#a13a5e" },
  douyin: { l: "抖音", letter: "D", color: "#1c1a17", dark: "#1c1a17" },
  kuaishou: { l: "快手", letter: "K", color: "#ff6633", dark: "#a13d1f" },
};

const m = () => META[props.k];
const h = () => (props.size === "sm" ? 22 : 26);
</script>

<template>
  <span
    class="inline-flex items-center gap-1.5 font-medium"
    :style="{
      height: h() + 'px',
      padding: '0 9px',
      borderRadius: '999px',
      background: 'rgba(255,255,255,0.92)',
      color: m().dark,
      fontSize: size === 'sm' ? '11px' : '12px',
      boxShadow: '0 1px 2px rgba(28,26,23,0.08)',
      border: '1px solid rgba(28,26,23,0.04)',
    }"
  >
    <span
      :style="{
        width: '14px', height: '14px', borderRadius: '4px',
        background: m().color, color: '#fff',
        display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
        fontSize: '9px', fontWeight: 800,
      }"
    >{{ m().letter }}</span>
    {{ m().l }}
  </span>
</template>
```

- [ ] **Step 3: Verify build**

`pnpm --filter frontend build` — expect pass. (May error if `PlatformChip` is used by `OutreachHero` before it exists; create `PlatformChip.vue` first.)

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/mining/OutreachHero.vue frontend/src/components/mining/PlatformChip.vue
git commit -m "feat(mining-fe): OutreachHero (dark + glow + 4 KPI) and PlatformChip"
```

---

## Task 7: Rewrite StartJobModal.vue

**Files:** Modify `frontend/src/components/mining/StartJobModal.vue`

The new modal has 5 sections (jsx lines 530-754): keyword input / 3 platform picker cards / sort segmented / time range segmented / count slider / estimate info box / footer.

- [ ] **Step 1: Replace entire StartJobModal.vue** with this content:

```vue
<script setup lang="ts">
import { ref, computed } from "vue";
import Btn from "@/components/ui/Btn.vue";
import Icon from "@/components/ui/Icon.vue";
import Blob from "@/components/ui/Blob.vue";
import PlatformPickerCard from "./PlatformPickerCard.vue";
import type { Platform } from "@/stores/mining";

const props = defineProps<{
  loginStatus: Record<Platform, boolean>;
}>();

const emit = defineEmits<{
  (e: "close"): void;
  (e: "submit", payload: { keyword: string; platforms: Platform[]; target: number }): void;
}>();

const kw = ref("");
// Auto-pick all logged-in platforms by default.
const picked = ref<Record<Platform, boolean>>({
  bilibili: !!props.loginStatus.bilibili,
  douyin: !!props.loginStatus.douyin,
  kuaishou: !!props.loginStatus.kuaishou,
});
const cap = ref(50);
const sort = ref("综合");
const range = ref("近 1 周");

const total = computed(() =>
  Object.values(picked.value).filter(Boolean).length * cap.value
);

const canSubmit = computed(
  () => kw.value.trim() && Object.values(picked.value).some(v => v)
);

function togglePlatform(p: Platform) {
  picked.value[p] = !picked.value[p];
}

function onSubmit() {
  if (!canSubmit.value) return;
  emit("submit", {
    keyword: kw.value.trim(),
    platforms: (["bilibili", "douyin", "kuaishou"] as Platform[]).filter(p => picked.value[p]),
    target: cap.value,
  });
}
</script>

<template>
  <div
    class="anim-in"
    @click="$emit('close')"
    style="position: fixed; inset: 0; z-index: 50; background: rgba(28,26,23,0.42); backdrop-filter: blur(4px); display: flex; align-items: center; justify-content: center; padding: 24px;"
  >
    <div
      class="anim-up"
      @click.stop
      style="width: 560px; max-width: 100%; max-height: 92%; background: var(--card); border-radius: 22px; border: 1px solid var(--line); box-shadow: 0 30px 60px -20px rgba(28,26,23,0.4); overflow: hidden; display: flex; flex-direction: column; position: relative;"
    >
      <Blob color="#f5c042" :size="220" :top="-80" :left="-40" :opacity="0.32"/>

      <!-- 顶部 -->
      <div class="relative" style="padding: 22px 24px 0;">
        <div class="flex items-start justify-between">
          <div>
            <div class="text-[10.5px] tracking-[1.5px] uppercase font-medium" style="color: var(--ink-3)">
              Outreach · 新建抓取任务
            </div>
            <div class="font-display font-bold mt-1.5" style="font-size: 22px; letter-spacing: -0.5px;">
              起一个抓取任务
            </div>
          </div>
          <button
            @click="$emit('close')"
            class="inline-flex items-center justify-center"
            style="width: 32px; height: 32px; border-radius: 999px; background: var(--card-2); color: var(--ink-2); border: 1px solid var(--line);"
          >
            <Icon name="x" :size="14"/>
          </button>
        </div>
      </div>

      <div class="relative flex-1 overflow-y-auto" style="padding: 18px 24px 0;">
        <!-- 关键词 -->
        <div>
          <div class="flex items-center justify-between mb-1.5">
            <label class="text-[11.5px] font-semibold">关键词</label>
            <span class="text-[10.5px]" style="color: var(--ink-4)">多个关键词暂不支持（Phase 2）</span>
          </div>
          <div
            class="flex items-center"
            style="background: var(--card-white); border: 1px solid var(--line-2); border-radius: 14px; padding: 0 14px; height: 46px;"
          >
            <Icon name="search" :size="15" style="opacity: 0.6"/>
            <input
              v-model="kw"
              placeholder="例如：宠物家庭吸尘器"
              class="flex-1 bg-transparent outline-none px-2.5"
              style="font-size: 14px; color: var(--ink);"
            />
            <button
              v-if="kw"
              @click="kw = ''"
              class="inline-flex items-center justify-center"
              style="width: 22px; height: 22px; border-radius: 999px; color: var(--ink-3);"
            ><Icon name="x" :size="12"/></button>
          </div>
        </div>

        <!-- 平台 -->
        <div class="mt-5">
          <div class="flex items-center justify-between mb-2">
            <label class="text-[11.5px] font-semibold">在哪些平台抓</label>
            <span class="text-[10.5px]" style="color: var(--ink-4)">未登录的去监控中心扫码</span>
          </div>
          <div class="grid grid-cols-3 gap-2">
            <PlatformPickerCard
              v-for="p in (['bilibili', 'douyin', 'kuaishou'] as Platform[])"
              :key="p"
              :platform="p"
              :picked="!!picked[p]"
              :logged-in="!!loginStatus[p]"
              @toggle="togglePlatform(p)"
              @login="$emit('close')"
            />
          </div>
        </div>

        <!-- 排序 / 时间 (UI only, not wired to backend in Phase 1) -->
        <div class="grid grid-cols-2 gap-3 mt-5">
          <div>
            <label class="text-[11.5px] font-semibold mb-1.5 block">排序</label>
            <div class="flex" style="background: var(--card-2); border-radius: 999px; padding: 3px; border: 1px solid var(--line);">
              <button
                v-for="s in ['综合', '最新', '最热']" :key="s"
                @click="sort = s"
                :style="{
                  flex: 1, height: '28px', borderRadius: '999px', fontSize: '11.5px', fontWeight: 500,
                  background: sort === s ? 'var(--dark)' : 'transparent',
                  color: sort === s ? '#fbf7ec' : 'var(--ink-2)',
                  border: 'none', cursor: 'pointer',
                }"
              >{{ s }}</button>
            </div>
          </div>
          <div>
            <label class="text-[11.5px] font-semibold mb-1.5 block">时间范围</label>
            <div class="flex" style="background: var(--card-2); border-radius: 999px; padding: 3px; border: 1px solid var(--line);">
              <button
                v-for="s in ['不限', '近 1 天', '近 1 周', '近 1 月']" :key="s"
                @click="range = s"
                :style="{
                  flex: 1, height: '28px', borderRadius: '999px', fontSize: '11px', fontWeight: 500,
                  background: range === s ? 'var(--dark)' : 'transparent',
                  color: range === s ? '#fbf7ec' : 'var(--ink-2)',
                  border: 'none', cursor: 'pointer',
                  whiteSpace: 'nowrap', padding: '0 4px',
                }"
              >{{ s }}</button>
            </div>
          </div>
        </div>

        <!-- 数量滑条 -->
        <div class="mt-5">
          <div class="flex items-center justify-between mb-2">
            <label class="text-[11.5px] font-semibold">每平台抓取数量</label>
            <div class="flex items-baseline gap-1">
              <span class="font-display font-bold" style="font-size: 18px; color: var(--primary-deep); letter-spacing: -0.4px;">{{ cap }}</span>
              <span class="text-[10.5px]" style="color: var(--ink-3)">条 / 平台</span>
            </div>
          </div>
          <div style="position: relative; padding: 10px 0;">
            <div style="height: 6px; background: var(--card-2); border-radius: 999px; position: relative; border: 1px solid var(--line);">
              <div :style="{ height: '100%', width: (cap / 200 * 100) + '%', background: 'var(--primary)', borderRadius: '999px' }"/>
            </div>
            <input
              type="range" min="10" max="200" step="10" v-model.number="cap"
              style="position: absolute; inset: 0; width: 100%; opacity: 0; cursor: pointer;"
            />
            <div class="flex justify-between mt-1.5 font-mono text-[10px]" style="color: var(--ink-4)">
              <span>10</span><span>50</span><span>100</span><span>200</span>
            </div>
          </div>
        </div>

        <!-- 预估 -->
        <div
          class="mt-4 flex items-center gap-2.5 px-3.5 py-3"
          style="background: rgba(245,192,66,0.10); border: 1px solid rgba(245,192,66,0.36); border-radius: 12px;"
        >
          <span
            style="width: 26px; height: 26px; border-radius: 8px; background: var(--yellow-soft); color: #7a5400; display: inline-flex; align-items: center; justify-content: center; flex-shrink: 0;"
          ><Icon name="info" :size="13"/></span>
          <div class="text-[11.5px] leading-snug" style="color: var(--ink-2)">
            预计抓取 <b class="font-display" style="color: var(--ink)">{{ total }}</b> 条视频，约需
            <b class="font-mono" style="color: var(--ink)">{{ Math.max(2, Math.round(total / 25)) }}–{{ Math.max(4, Math.round(total / 15)) }} 分钟</b>。
            抓完后会自动去重 &amp; 过滤已评论。
          </div>
        </div>
      </div>

      <!-- footer -->
      <div
        class="relative flex items-center justify-between"
        style="padding: 16px 24px; border-top: 1px solid var(--line); background: var(--card-2);"
      >
        <div class="text-[11px]" style="color: var(--ink-3)">
          <Icon name="key" :size="11" style="display: inline-block; margin-right: 4px; opacity: 0.6;"/>
          登录 cookie 来自监控中心 · 仅存于本地
        </div>
        <div class="flex items-center gap-2">
          <Btn variant="ghost" @click="$emit('close')">取消</Btn>
          <Btn variant="solid" :disabled="!canSubmit" @click="onSubmit">
            <Icon name="play" :size="11"/> 开始抓取
          </Btn>
        </div>
      </div>
    </div>
  </div>
</template>
```

- [ ] **Step 2: Verify build**

`pnpm --filter frontend build` — expect pass.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/mining/StartJobModal.vue
git commit -m "feat(mining-fe): rewrite StartJobModal to Outreach design (cookie/sort/time range/slider)"
```

---

## Task 8: Rewrite VideoTable.vue → VideoCard.vue

**Files:**
- Create: `frontend/src/components/mining/VideoCard.vue` (single-card render — the workhorse of the view)
- Leave `VideoTable.vue` for now; the next task will replace its usage in MiningView and a later task deletes the file.

This is the most important file — jsx lines 151-527 covering the entire video card. Phase 1 keeps the structure but Phase 2/3 features are placeholders.

- [ ] **Step 1: Write VideoCard.vue**

```vue
<script setup lang="ts">
import { computed } from "vue";
import Icon from "@/components/ui/Icon.vue";
import Pill from "@/components/ui/Pill.vue";
import Avatar from "@/components/ui/Avatar.vue";
import PlatformChip from "./PlatformChip.vue";
import type { Video, Platform } from "@/stores/mining";

const props = defineProps<{
  v: Video;
  selected: boolean;
}>();

defineEmits<{
  (e: "toggle-select", id: number): void;
  (e: "open", url: string): void;
}>();

// Phase 1 surrogate for "done": already_commented from monitor reverse-lookup.
const isDone = computed(() => props.v.already_commented);

function fmt(n: number | null): string {
  if (n == null) return "—";
  if (n >= 10000) return (n / 10000).toFixed(n >= 100000 ? 0 : 1) + "w";
  if (n >= 1000) return (n / 1000).toFixed(1) + "k";
  return String(n);
}

function fmtDuration(s: number | null): string {
  if (s == null || s <= 0) return "—";
  const m = Math.floor(s / 60), ss = s % 60;
  return `${m}:${String(ss).padStart(2, "0")}`;
}

function relativeTime(iso: string): string {
  const d = new Date(iso);
  const diff = (Date.now() - d.getTime()) / 1000;
  if (diff < 3600) return Math.floor(diff / 60) + " 分钟前";
  if (diff < 86400) return Math.floor(diff / 3600) + " 小时前";
  if (diff < 604800) return Math.floor(diff / 86400) + " 天前";
  return d.toLocaleDateString();
}
</script>

<template>
  <div
    class="flex flex-col transition"
    :style="{
      background: 'var(--card)',
      borderRadius: 'var(--radius-card)',
      border: selected ? '1.5px solid var(--primary)' : '1px solid var(--line)',
      padding: '16px',
      position: 'relative',
    }"
  >
    <!-- 顶部 meta 行 -->
    <div class="flex items-center gap-2">
      <button
        @click="$emit('toggle-select', v.id)"
        :style="{
          width: '18px', height: '18px', borderRadius: '5px', flexShrink: 0,
          background: selected ? 'var(--primary)' : 'transparent',
          color: selected ? '#fff' : 'var(--ink-3)',
          border: '1.5px solid ' + (selected ? 'var(--primary)' : 'var(--line-2)'),
          display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
          cursor: 'pointer',
        }"
        title="选中"
      >
        <Icon v-if="selected" name="check" :size="10"/>
      </button>

      <PlatformChip :k="v.platform as Platform"/>

      <div class="flex items-center gap-1 min-w-0">
        <Avatar :name="v.author_name" :size="18"/>
        <span class="text-[11.5px] font-medium truncate" style="color: var(--ink-2); max-width: 110px;">
          @{{ v.author_name || "(无作者)" }}
        </span>
      </div>

      <span class="text-[10.5px]" style="color: var(--ink-4)">· {{ relativeTime(v.first_seen_at) }}</span>

      <div class="ml-auto flex items-center gap-2">
        <Pill v-if="isDone" tone="ok"><Icon name="check" :size="10"/> 已评论</Pill>
        <Pill v-else tone="warn">待评论</Pill>
        <button
          class="inline-flex items-center justify-center"
          style="width: 24px; height: 24px; border-radius: 999px; color: var(--ink-3);"
          title="更多"
        ><Icon name="more" :size="13"/></button>
      </div>
    </div>

    <!-- 标题 + 视频数据 -->
    <div class="flex items-baseline gap-3 mt-3">
      <a
        :href="v.url"
        target="_blank"
        rel="noopener"
        class="font-display font-semibold hover:underline flex-1 min-w-0"
        :style="{
          fontSize: '15.5px', lineHeight: 1.4, color: 'var(--ink)',
          textWrap: 'pretty',
          display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden',
        }"
        title="在浏览器中打开原视频"
      >{{ v.title || "(无标题)" }}</a>
      <div class="flex items-center gap-2.5 flex-shrink-0" style="color: var(--ink-3); font-size: 10.5px;">
        <span v-if="v.duration_sec" class="inline-flex items-center gap-1">
          <Icon name="clock" :size="11"/><span class="font-mono">{{ fmtDuration(v.duration_sec) }}</span>
        </span>
        <span v-if="v.play_count" class="inline-flex items-center gap-1">
          <Icon name="eye" :size="11"/><span class="font-mono">{{ fmt(v.play_count) }}</span>
        </span>
        <span v-if="v.like_count" class="inline-flex items-center gap-1">
          <Icon name="heart" :size="11"/><span class="font-mono">{{ fmt(v.like_count) }}</span>
        </span>
      </div>
    </div>

    <!-- AI 速览 (Phase 1 placeholder) -->
    <div
      class="mt-3"
      style="background: rgba(245,192,66,0.10); border: 1px solid rgba(245,192,66,0.32); border-radius: 12px; padding: 11px 12px;"
    >
      <div class="flex items-center gap-1.5 mb-1.5">
        <span style="width: 16px; height: 16px; border-radius: 5px; background: var(--dark); color: var(--yellow); display: inline-flex; align-items: center; justify-content: center;">
          <Icon name="spark" :size="10"/>
        </span>
        <span class="text-[10.5px] font-semibold tracking-wide" style="color: #7a5400">AI 速览</span>
      </div>
      <div class="text-[12px] leading-relaxed" style="color: var(--ink-2); font-style: italic; opacity: 0.7;">
        待生成 — AI 速览会在第三期上线
      </div>
    </div>

    <!-- 评论楼占位 -->
    <div
      class="mt-3"
      style="background: var(--card-2); border: 1px solid var(--line); border-radius: 12px; padding: 12px 12px 6px;"
    >
      <div class="flex items-center gap-1.5 mb-2.5">
        <span style="width: 16px; height: 16px; border-radius: 5px; background: var(--ink-4); color: #fff; display: inline-flex; align-items: center; justify-content: center;">
          <Icon name="stack" :size="10"/>
        </span>
        <span class="text-[10.5px] font-semibold tracking-wide" style="color: var(--ink-3)">评论楼 · 0 层</span>
        <span class="ml-auto text-[10px]" style="color: var(--ink-4)">第二期上线</span>
      </div>
      <div class="flex flex-col items-center justify-center text-center" style="padding: 16px 12px;">
        <span style="width: 28px; height: 28px; border-radius: 8px; background: var(--card); color: var(--ink-4); border: 1px dashed var(--line-2); display: inline-flex; align-items: center; justify-content: center;">
          <Icon name="comment" :size="13"/>
        </span>
        <div class="text-[11px] mt-1.5" style="color: var(--ink-3)">评论楼工作流 · 第二期上线</div>
      </div>
    </div>

    <!-- composer 占位 (disabled) -->
    <div
      class="mt-3 flex flex-col relative"
      style="background: var(--card-white); border: 1.5px solid var(--line-2); border-radius: 12px; padding: 2px; opacity: 0.55;"
    >
      <textarea
        disabled
        placeholder="评论楼工作流将在第二期上线…"
        rows="2"
        class="w-full bg-transparent outline-none resize-none"
        style="padding: 9px 11px 4px; font-size: 12.5px; line-height: 1.55; color: var(--ink); font-family: inherit; min-height: 56px;"
      ></textarea>
      <div class="flex items-center gap-1.5" style="padding: 5px 6px 5px 8px;">
        <button
          disabled
          class="inline-flex items-center gap-1"
          style="height: 26px; padding: 0 9px; border-radius: 999px; font-size: 11px; background: var(--card-2); color: var(--ink-4); border: 1px solid var(--line); cursor: not-allowed;"
        >
          <Icon name="copy" :size="11"/> 图片
        </button>
        <button
          disabled
          class="inline-flex items-center gap-1"
          style="height: 26px; padding: 0 9px; border-radius: 999px; font-size: 11px; background: var(--card-2); color: var(--ink-4); border: 1px solid var(--line); cursor: not-allowed;"
        >
          <Icon name="wand" :size="11"/> AI 建议
        </button>
        <div class="flex-1"/>
        <button
          disabled
          class="inline-flex items-center gap-1.5"
          style="height: 28px; padding: 0 14px; border-radius: 999px; font-size: 11.5px; font-weight: 600; background: var(--card-2); color: var(--ink-4); border: 1px solid var(--line); cursor: not-allowed;"
          title="第二期上线"
        >
          <Icon name="play" :size="11"/> 发布第 1 层
        </button>
      </div>
    </div>
  </div>
</template>
```

- [ ] **Step 2: Verify build**

`pnpm --filter frontend build` — expect pass.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/mining/VideoCard.vue
git commit -m "feat(mining-fe): VideoCard with AI 速览/评论楼/composer 占位 (Phase 1 visual only)"
```

---

## Task 9: Rewrite MiningView.vue

**Files:** Modify `frontend/src/views/MiningView.vue`

Compose all new components into the page-level shell.

- [ ] **Step 1: Replace the entire MiningView.vue** with this content:

```vue
<script setup lang="ts">
import { ref, computed, onMounted } from "vue";
import Btn from "@/components/ui/Btn.vue";
import Icon from "@/components/ui/Icon.vue";
import StartJobModal from "@/components/mining/StartJobModal.vue";
import OutreachHero from "@/components/mining/OutreachHero.vue";
import VideoCard from "@/components/mining/VideoCard.vue";
import { useMiningStore, type Platform } from "@/stores/mining";

const store = useMiningStore();
const showNewTask = ref(false);
const tab = ref<"unread" | "done" | "all">("unread");
const platform = ref<"all" | Platform>("all");
const sortBy = ref("最新");
const selected = ref(new Set<number>());

const counts = computed(() => ({
  unread: store.videos.filter(v => !v.already_commented).length,
  done: store.videos.filter(v => v.already_commented).length,
  all: store.videos.length,
}));

const filtered = computed(() => {
  return store.videos.filter(v => {
    if (tab.value === "unread" && v.already_commented) return false;
    if (tab.value === "done" && !v.already_commented) return false;
    if (platform.value !== "all" && v.platform !== platform.value) return false;
    if (store.filters.q && !v.title.includes(store.filters.q) && !v.author_name.includes(store.filters.q)) return false;
    return true;
  });
});

function toggleSelect(id: number) {
  const s = new Set(selected.value);
  s.has(id) ? s.delete(id) : s.add(id);
  selected.value = s;
}

async function onStartSubmit(payload: { keyword: string; platforms: Platform[]; target: number }) {
  showNewTask.value = false;
  await store.startJob(payload.keyword, payload.platforms, payload.target);
}

onMounted(async () => {
  await store.refreshLoginStatus();
  await store.refreshVideos();
});
</script>

<template>
  <div class="anim-up flex flex-col" style="gap: var(--density-gap); padding-bottom: 60px; position: relative;">
    <!-- 页头 -->
    <div class="flex items-end justify-between">
      <div>
        <div class="text-[11px] tracking-[1.5px] uppercase" style="color: var(--ink-3)">
          Outreach · 引流
        </div>
        <div class="font-display font-bold mt-2" style="font-size: 30px; letter-spacing: -0.5px;">
          视频抓取
        </div>
        <div class="text-[12.5px] mt-1" style="color: var(--ink-3)">
          抓取抖音 / B 站 / 快手 关键词相关视频，把要去种草的评论区集中到一处。
        </div>
      </div>
      <div class="flex items-center gap-2">
        <a
          :href="store.exportUrl()"
          download="mining_videos.csv"
          class="inline-flex items-center gap-1.5 font-medium px-4 py-2 text-[13px] bg-transparent hover:bg-[rgba(28,26,23,0.05)]"
          style="border-radius: var(--radius-pill); color: var(--ink-2);"
        >
          <Icon name="download" :size="12"/> 导出 CSV
        </a>
        <Btn variant="solid" :disabled="store.hasRunningJob" @click="showNewTask = true">
          <Icon name="plus" :size="12"/> 新建抓取任务
        </Btn>
      </div>
    </div>

    <!-- Hero -->
    <OutreachHero
      :job="store.activeJob"
      :counts="counts"
      @cancel="store.cancelActive"
    />

    <!-- Filter 条 -->
    <div class="flex items-center justify-between gap-3 flex-wrap">
      <div class="flex items-center gap-2">
        <!-- 状态 pivot -->
        <div class="flex items-center" style="background: var(--card); border-radius: 999px; padding: 4px; border: 1px solid var(--line);">
          <button
            v-for="t in [
              { k: 'unread', l: '待评论', n: counts.unread },
              { k: 'done', l: '已评论', n: counts.done },
              { k: 'all', l: '全部', n: counts.all },
            ]"
            :key="t.k"
            @click="tab = t.k as any"
            :style="{
              height: '32px', padding: '0 14px', borderRadius: '999px',
              background: tab === t.k ? 'var(--dark)' : 'transparent',
              color: tab === t.k ? '#fbf7ec' : 'var(--ink-3)',
              fontSize: '12.5px', fontWeight: 500,
              display: 'inline-flex', alignItems: 'center', gap: '6px',
              border: 'none', cursor: 'pointer',
            }"
          >
            {{ t.l }}
            <span
              class="text-[10.5px]"
              :style="{
                color: tab === t.k ? 'rgba(255,255,255,0.55)' : 'var(--ink-4)',
                background: tab === t.k ? 'rgba(255,255,255,0.08)' : 'var(--card-2)',
                borderRadius: '999px', padding: '1px 7px',
              }"
            >{{ t.n }}</span>
          </button>
        </div>

        <!-- 平台筛选 -->
        <div class="flex items-center" style="background: var(--card); border-radius: 999px; padding: 4px; border: 1px solid var(--line);">
          <button
            v-for="p in [
              { k: 'all', l: '全部', dot: null },
              { k: 'bilibili', l: 'B 站', dot: '#fb7299' },
              { k: 'douyin', l: '抖音', dot: '#1c1a17' },
              { k: 'kuaishou', l: '快手', dot: '#ff6633' },
            ]"
            :key="p.k"
            @click="platform = p.k as any"
            :style="{
              height: '32px', padding: '0 12px', borderRadius: '999px',
              background: platform === p.k ? 'var(--card-2)' : 'transparent',
              color: platform === p.k ? 'var(--ink)' : 'var(--ink-3)',
              fontSize: '12px', fontWeight: 500,
              display: 'inline-flex', alignItems: 'center', gap: '6px',
              border: platform === p.k ? '1px solid var(--line-2)' : '1px solid transparent',
              cursor: 'pointer',
            }"
          >
            <span v-if="p.dot" :style="{ width: '6px', height: '6px', borderRadius: '999px', background: p.dot }"/>
            {{ p.l }}
          </button>
        </div>
      </div>

      <div class="flex items-center gap-2">
        <!-- sort -->
        <button
          class="inline-flex items-center gap-1.5 text-[11.5px]"
          style="height: 34px; padding: 0 12px; background: var(--card); border: 1px solid var(--line); border-radius: 999px; color: var(--ink-2); cursor: pointer;"
        >
          <Icon name="sort" :size="12"/> {{ sortBy }}
          <Icon name="arrowDown" :size="10" style="opacity: 0.5"/>
        </button>

        <!-- search -->
        <div class="flex items-center" style="height: 34px; background: var(--card); border: 1px solid var(--line); border-radius: 999px; padding: 0 12px; width: 240px;">
          <Icon name="search" :size="13" style="opacity: 0.6"/>
          <input
            v-model="store.filters.q"
            @input="store.refreshVideos()"
            placeholder="搜索标题或作者…"
            class="flex-1 bg-transparent outline-none px-2 text-[12px]"
          />
          <button v-if="store.filters.q" @click="store.filters.q = ''; store.refreshVideos();" style="color: var(--ink-3)">
            <Icon name="x" :size="12"/>
          </button>
        </div>
      </div>
    </div>

    <!-- 视频网格 -->
    <div v-if="filtered.length > 0" class="grid" style="grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px;">
      <VideoCard
        v-for="v in filtered"
        :key="v.id"
        :v="v"
        :selected="selected.has(v.id)"
        @toggle-select="toggleSelect"
      />
    </div>
    <div v-else class="pad-d flex flex-col items-center text-center" style="padding: 60px 30px; background: var(--card); border: 1px solid var(--line); border-radius: var(--radius-card);">
      <span style="width: 54px; height: 54px; border-radius: 16px; background: var(--card-2); color: var(--ink-3); display: inline-flex; align-items: center; justify-content: center;">
        <Icon name="video" :size="22"/>
      </span>
      <div class="font-display font-bold mt-4" style="font-size: 18px;">没有匹配的视频</div>
      <div class="text-[12.5px] mt-1.5" style="color: var(--ink-3); max-width: 420px;">
        换个筛选，或者起一个新任务再抓一批。
      </div>
      <div class="flex items-center gap-2 mt-5">
        <Btn variant="ghost" @click="tab = 'all'; platform = 'all'; store.filters.q = ''; store.refreshVideos();">清除筛选</Btn>
        <Btn variant="solid" @click="showNewTask = true"><Icon name="plus" :size="12"/> 新建任务</Btn>
      </div>
    </div>

    <!-- 浮动批量栏 -->
    <div
      v-if="selected.size > 0"
      class="anim-up"
      style="position: fixed; bottom: 14px; left: 50%; transform: translateX(-50%); background: var(--dark); color: #fbf7ec; border-radius: 999px; padding: 8px 8px 8px 18px; display: inline-flex; align-items: center; gap: 14px; box-shadow: 0 14px 30px -10px rgba(28,26,23,0.5); z-index: 25;"
    >
      <span class="text-[12.5px]">
        已选 <b class="font-display" style="color: var(--primary)">{{ selected.size }}</b> 条
      </span>
      <span style="width: 1px; height: 18px; background: rgba(255,255,255,0.14);"/>
      <button
        disabled
        class="inline-flex items-center gap-1.5 text-[12px] font-medium"
        style="height: 30px; padding: 0 12px; border-radius: 999px; background: rgba(255,255,255,0.08); color: rgba(255,255,255,0.45); cursor: not-allowed;"
        title="第二期上线"
      >
        <Icon name="check" :size="12"/> 标记已评论
      </button>
      <button
        class="inline-flex items-center gap-1.5 text-[12px] font-medium"
        style="height: 30px; padding: 0 12px; border-radius: 999px; background: rgba(255,255,255,0.08); color: #fbf7ec; cursor: pointer;"
      >
        <Icon name="external" :size="12"/> 全部打开
      </button>
      <button
        disabled
        class="inline-flex items-center gap-1.5 text-[12px] font-medium"
        style="height: 30px; padding: 0 12px; border-radius: 999px; background: rgba(255,255,255,0.08); color: rgba(255,255,255,0.45); cursor: not-allowed;"
        title="第二期上线"
      >
        <Icon name="download" :size="12"/> 导出选中
      </button>
      <button
        @click="selected = new Set()"
        class="inline-flex items-center justify-center"
        style="width: 30px; height: 30px; border-radius: 999px; background: rgba(255,255,255,0.06); color: rgba(255,255,255,0.55); cursor: pointer;"
      >
        <Icon name="x" :size="12"/>
      </button>
    </div>

    <StartJobModal
      v-if="showNewTask"
      :login-status="store.loginStatus"
      @close="showNewTask = false"
      @submit="onStartSubmit"
    />
  </div>
</template>
```

- [ ] **Step 2: Verify build**

`pnpm --filter frontend build` — expect pass.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/views/MiningView.vue
git commit -m "feat(mining-fe): rewrite MiningView to Outreach design (hero/filter/grid/批量栏)"
```

---

## Task 10: Delete deprecated files

**Files:**
- Delete: `frontend/src/components/mining/PlatformLoginPanel.vue`
- Delete: `frontend/src/components/mining/VideoTable.vue`
- Delete: `frontend/src/components/mining/JobProgressCard.vue`

These are superseded by the new components.

- [ ] **Step 1: Verify nothing else references them**

Run: `grep -rn "PlatformLoginPanel\|VideoTable\|JobProgressCard" frontend/src/ --include="*.vue" --include="*.ts"`
Expected: only the files themselves (zero usage in other files after Task 9).

If anything else references them, **stop and report** — do not delete yet.

- [ ] **Step 2: Delete the files**

```bash
rm frontend/src/components/mining/PlatformLoginPanel.vue
rm frontend/src/components/mining/VideoTable.vue
rm frontend/src/components/mining/JobProgressCard.vue
```

- [ ] **Step 3: Verify build still passes**

`pnpm --filter frontend build` — expect pass.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "chore(mining-fe): delete deprecated PlatformLoginPanel/VideoTable/JobProgressCard"
```

---

## Task 11: Final validation

- [ ] **Step 1: Full frontend build**

```bash
pnpm --filter frontend build
```
Expected: zero TypeScript errors. Vite build succeeds. Chunk sizes reasonable.

- [ ] **Step 2: Full backend tests**

```bash
pytest sidecar/tests/ --ignore=sidecar/tests/test_article_routes.py -q
```
Expected: 245 passed (no regression — we didn't touch any Python code).

- [ ] **Step 3: Push to PR**

```bash
git push
```

- [ ] **Step 4: Manual visual smoke**

This step is for the user, not automatable. Open [http://localhost:5173/#/mining](http://localhost:5173/#/mining) in a browser (after restarting `dev.ps1` if needed), and visually compare against the 4 design-doc screenshots:

1. Header: "OUTREACH · 引流" eyebrow + "视频抓取" h1 + 副标题 + 右上「导出 CSV」「+ 新建抓取任务」
2. Hero: dark bg + orange/pink glow + "正在抓取" pulse dot + keyword + platform chips + progress bar + 4 KPI cards on right
3. Filter row: 待评论/已评论/全部 pivot (dark active state) + 平台 chip (B站/抖音/快手) + 排序 + 搜索
4. Video grid: 2 columns, each card has platform chip + avatar + author + status pill + title + metadata + AI 速览 yellow box + 评论楼 placeholder + disabled composer
5. New task modal: keyword + 3 platform picker cards (with logged-in indicator) + 排序/时间 segmented + count slider + 预估 yellow info + footer

Note any visual deltas vs design screenshots. Phase 2/3 will address functional gaps (评论楼 working, AI 速览 generated, etc).

---

## Done criteria

- All 11 tasks ticked
- Backend tests 245/245 pass (no regression)
- Frontend builds cleanly
- Branch pushed to PR `#26`
- Visual smoke compared against design screenshots (note discrepancies as Phase 2 work items)
