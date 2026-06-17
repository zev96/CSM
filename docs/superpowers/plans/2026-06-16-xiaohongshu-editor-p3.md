# 小红书编辑器 P3（主题完整化 + AI 助手）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把小红书编辑器的排版主题补到 8 套色系并接通「有序列表」符号，新增 AI 助手（生成整篇 / 润色正文，复用 `llm_factory`），未配置 LLM 时引导去设置。

**Architecture:** 两条独立轨。**主题轨**纯前端：扩 `themes.json` 数据 + 新增 `utils/xhsTheme.ts` 序号字形工具 + store/工具条/ThemePanel 接通 `ordered`。**AI 轨**前后端：新建 `services/xhs_ai_service.py`（`generate_note`/`polish_note` 包 `llm_factory.build_client()` + 内置 prompt），两条路由挂进**现有** `routes/xhs.py`（错误映射 1:1 仿 mining：`LLMConfigError→503 llm_not_configured`，其余 LLM 异常→502 `llm_error`），前端 store 把 503 解包成 `LLMNotConfiguredError`，新建 `AiPanel.vue` 接 `PanelRail`，未配置时 `toast.error` 带「去设置」动作跳 `/settings`。

**Tech Stack:** Vue 3.5 + Pinia(options store) + Vue Router 4 + TypeScript + Vitest / FastAPI sidecar + pytest。AI 走 `csm_core.llm`（`LLMClient.complete(*, system, user, temperature=None)`），P3 只用内置 prompt（用户自定义 prompt 留 P4）。

---

## 背景与既有模式（实现前必读）

P0/P1/P2 已落地，P3 在其上增量。务必复用既有模式，别另起炉灶：

- **AI service 模板**：`sidecar/csm_sidecar/services/mining_ai_service.py`（`build_client()` → `client.complete(system=, user=)` → strip）、`services/polish_service.py`（单段润色）。`llm_factory.build_client()` 未配置 default provider / api key 时抛 `LLMConfigError`（`ValueError` 子类），由路由层捕获。**P3 用内置 prompt 常量即可，不接 `config_service` 自定义 prompt（那是 P4）**，所以比 mining_ai_service 简单：无 `_resolve_prompt`/`_render`。
- **AI 路由错误映射**：`routes/mining.py` 的 `_llm_http_error(e)`（`LLMConfigError→503 {code:"llm_not_configured", detail}`，其余→`502 {code:"llm_error", detail}`）+ `try/except LLMConfigError/Exception`。照抄到 `routes/xhs.py`（本地再定义一个同名 helper，别跨模块 import mining 的）。
- **AI service 测试**：`sidecar/tests/test_mining_ai_service.py` / `test_mining_ai_routes.py` 的 `_RecordingClient`（实现 `complete(*, system, user, temperature=None)`）+ `monkeypatch.setattr(<service>.llm_factory, "build_client", lambda **kw: client)`。503 测试不打 monkeypatch（让真 `build_client` 抛 `LLMConfigError`）。
- **xhs 后端测试夹具**：`sidecar/tests/conftest.py` 的 `client`（带 token 的 TestClient）+ `xhs_db`（每测独立 xhs.db）+ `settings_path`（重置 config_service）。`config_service.patch({"default_provider": "mock"})` 设默认 provider。参考 `test_xhs_image_routes.py`。
- **前端 503→去设置 UX**：`stores/mining.ts` 的 `LLMNotConfiguredError` + `_wrapLLMError(err)`（503 + `code==="llm_not_configured"` → 抛它），消费见 `components/mining/VideoDetailPanel.vue`：
  ```ts
  toast.error("请先在设置中配置 AI 服务", { actionLabel: "去设置", onAction: () => { router.push("/settings"); } });
  ```
  设置路由 `name: "settings"`、`path: "/settings"`（`router/index.ts`）。
- **覆盖确认**：`composables/useConfirm.ts` 的 `confirmDialog(message, { title, okLabel, kind })`，用法见 `panels/TemplatePanel.vue`。
- **toast**：`composables/useToast.ts` — `success/error/warn(msg, opts?)`，`opts={ actionLabel, onAction, ttl }`。
- **光标插入**：store `insertAtCursor(text)`（有注册器走光标、否则追加正文末）。
- **主题数据 / 类型**：`data/xhs/themes.json` + `data/xhs/assets.ts`（`XhsTheme { id,name,heading,bullet,ordered:"emoji"|"circle"|"superscript",divider }`、`THEMES`、`findTheme`）。`assets.ts:25` 注释「ordered … P1 未用、留给 P3」——P3 正是接通它。
- **store 主题部分**：`stores/xhs.ts` 的 `activeTheme`(getter)、`themeToolbar`(function getter，现返回 heading/bullet/divider 三个)、`applyTheme`。`applyTemplate({title,body,topics})` 整篇覆盖 + scheduleSave —— **AI 生成填入直接复用它**。
- **前端组件测试约定**：`vi.mock("@/stores/sidecar"...)`、`vi.mock("@/composables/useConfirm", () => ({ confirmDialog: vi.fn().mockResolvedValue(true) }))`、稳定 spy 用 `vi.hoisted`。参考 `panels/__tests__/{TemplatePanel,ImagePanel}.spec.ts`。
- **打包**：`sidecar/csm-sidecar.spec` 的 `hiddenimports` 已有 `csm_sidecar.services.xhs_images_service`（222 行），P3 紧跟着加 `xhs_ai_service`。

### 后端测试环境（每次跑 pytest 都要）

worktree 代码被主仓 editable 安装遮蔽 + 系统 python 缺 fastapi/pytest，**必须用 venv python + PYTHONPATH 覆盖**：

```powershell
$env:PYTHONPATH = "D:\CSM\.claude\worktrees\cranky-varahamihira-d53003\sidecar;D:\CSM\.claude\worktrees\cranky-varahamihira-d53003"
& "D:\CSM\.venv\Scripts\python.exe" -m pytest sidecar/tests/<file> -v
```

### 前端测试 / 构建命令

```powershell
npx vitest run <相对路径>          # 单文件
npx vitest run                      # 全量
npx vue-tsc -b ; npx vite build     # 类型检查 + 构建（vue-tsc -b 可能 emit vite.config.js/.d.ts，跑完 git checkout -- 还原）
```

---

## 文件清单

### 新建

- `sidecar/csm_sidecar/services/xhs_ai_service.py` — `generate_note(intent)->dict` + `polish_note(text)->str` + JSON 解析兜底。
- `sidecar/tests/test_xhs_ai_service.py` — service 单测（recording fake）。
- `sidecar/tests/test_xhs_ai_routes.py` — 路由测试（happy / 400 / 503 / 502）。
- `frontend/src/utils/xhsTheme.ts` — `orderedMarker(n,style)` + `countOrderedMarkers(body,style)` 纯函数。
- `frontend/src/utils/__tests__/xhsTheme.spec.ts` — util 单测。
- `frontend/src/components/xhs/panels/AiPanel.vue` — AI 助手面板。
- `frontend/src/components/xhs/panels/__tests__/AiPanel.spec.ts` — AiPanel 单测。

### 修改

- `frontend/src/data/xhs/themes.json` — 3 → 8 套色系。
- `frontend/src/data/xhs/__tests__/assets.spec.ts` — 主题数量断言 `>=6`。
- `frontend/src/stores/xhs.ts` — `themeToolbar` 加「有序」、`insertOrdered()`、`generateNote()`/`polishBody()`、`LLMNotConfiguredError`/`_wrapLLMError`。
- `frontend/src/stores/__tests__/xhs.spec.ts` — 更新 themeToolbar keys 断言 + 新增 ordered / AI action 测试。
- `frontend/src/components/xhs/NoteEditor.vue` — 工具条「有序」按钮分支到 `insertOrdered()`。
- `frontend/src/components/xhs/panels/ThemePanel.vue` — 卡片预览补「有序」样例行。
- `frontend/src/components/xhs/panels/__tests__/ThemePanel.spec.ts` — 预览有序样例断言。
- `sidecar/csm_sidecar/routes/xhs.py` — 加 `POST /api/xhs/ai/generate`、`POST /api/xhs/ai/polish` + `_llm_http_error`。
- `sidecar/csm-sidecar.spec` — hiddenimports 加 `xhs_ai_service`。
- `frontend/src/components/xhs/PanelRail.vue` — `PANEL_COMPONENTS` 加 `ai` + 去陈旧占位注释。

### 不动

- `csm_core/`（AI 走 sidecar 适配层，不碰 core）、其它路由/store、图片 service。

---

# 主题轨（T1–T4，纯前端）

## Task 1: 排版主题扩到 8 套色系

**Files:**
- Modify: `frontend/src/data/xhs/themes.json`
- Test: `frontend/src/data/xhs/__tests__/assets.spec.ts:31`

- [ ] **Step 1: 把 themes.json 从 3 套扩成 8 套**

整文件替换为（全 Unicode，无任何官方贴纸图；`ordered` 覆盖 emoji/circle/superscript 三种以便后续工具条/预览验证）：

```json
[
  { "id": "warm_yellow", "name": "温暖黄", "heading": "💛", "bullet": "🔸", "ordered": "emoji", "divider": "✨━━━━━━━━✨" },
  { "id": "sky_blue", "name": "天空蓝", "heading": "💙", "bullet": "🔹", "ordered": "circle", "divider": "·｡✦ ──────── ✦｡·" },
  { "id": "energy_orange", "name": "元气橙", "heading": "🧡", "bullet": "🔶", "ordered": "emoji", "divider": "🍊─────────🍊" },
  { "id": "sweet_pink", "name": "甜心粉", "heading": "💗", "bullet": "🌸", "ordered": "emoji", "divider": "❀━━━━━━━━❀" },
  { "id": "fresh_green", "name": "清新绿", "heading": "💚", "bullet": "🍀", "ordered": "circle", "divider": "🌿┈┈┈┈┈┈┈🌿" },
  { "id": "elegant_purple", "name": "高级紫", "heading": "💜", "bullet": "🔮", "ordered": "emoji", "divider": "⋆｡˚ ──────── ˚｡⋆" },
  { "id": "milk_coffee", "name": "奶咖棕", "heading": "🤎", "bullet": "☕", "ordered": "circle", "divider": "┄┄┄┄☕┄┄┄┄" },
  { "id": "ink_gray", "name": "高级灰", "heading": "🖤", "bullet": "▪️", "ordered": "superscript", "divider": "────────────" }
]
```

- [ ] **Step 2: 收紧 assets.spec 主题数量断言（锁住 P3「完整化」）**

把 `frontend/src/data/xhs/__tests__/assets.spec.ts:31` 这一行：

```ts
    expect(THEMES.length).toBeGreaterThan(0);
```

改成：

```ts
    expect(THEMES.length).toBeGreaterThanOrEqual(6); // P3「完整化」：6–8 套色系
```

（该测试已有的 id 唯一 / `ordered` ∈ 三值 / findTheme 命中断言保持不变。）

- [ ] **Step 3: 跑 assets 测试**

Run: `npx vitest run src/data/xhs/__tests__/assets.spec.ts`
Expected: PASS（主题 8 套、ordered 全合法、id 唯一）。

- [ ] **Step 4: Commit**

```bash
git add frontend/src/data/xhs/themes.json frontend/src/data/xhs/__tests__/assets.spec.ts
git commit -m "feat(xhs): 排版主题扩到 8 套色系 (P3 T1)"
```

---

## Task 2: 有序列表序号字形工具 `xhsTheme.ts`（TDD）

**Files:**
- Create: `frontend/src/utils/xhsTheme.ts`
- Test: `frontend/src/utils/__tests__/xhsTheme.spec.ts`

`ordered` 是「有序列表样式」而非单个符号，所以工具条「有序」按钮要把第 N 个序号渲染成该样式的字形（`orderedMarker`），N 由「正文已有同样式序号个数 + 1」推算（`countOrderedMarkers`，soft helper）。两个纯函数，先写测试。

- [ ] **Step 1: 写失败测试**

Create `frontend/src/utils/__tests__/xhsTheme.spec.ts`:

```ts
import { describe, it, expect } from "vitest";
import { orderedMarker, countOrderedMarkers } from "@/utils/xhsTheme";

describe("orderedMarker", () => {
  it("emoji 样式：1→1️⃣、10→🔟、超表→`${n}.`", () => {
    expect(orderedMarker(1, "emoji")).toBe("1️⃣");
    expect(orderedMarker(10, "emoji")).toBe("🔟");
    expect(orderedMarker(11, "emoji")).toBe("11.");
  });
  it("circle 样式：1→①、20→⑳、超表→`${n}.`", () => {
    expect(orderedMarker(1, "circle")).toBe("①");
    expect(orderedMarker(20, "circle")).toBe("⑳");
    expect(orderedMarker(21, "circle")).toBe("21.");
  });
  it("superscript 样式：1→¹、9→⁹、超表→`${n}.`", () => {
    expect(orderedMarker(1, "superscript")).toBe("¹");
    expect(orderedMarker(9, "superscript")).toBe("⁹");
    expect(orderedMarker(10, "superscript")).toBe("10.");
  });
  it("n<1 返回空串（防御）", () => {
    expect(orderedMarker(0, "emoji")).toBe("");
  });
});

describe("countOrderedMarkers", () => {
  it("数出正文已有的同样式序号个数", () => {
    expect(countOrderedMarkers("1️⃣ 第一\n2️⃣ 第二", "emoji")).toBe(2);
    expect(countOrderedMarkers("① a ② b ③ c", "circle")).toBe(3);
    expect(countOrderedMarkers("¹ x", "superscript")).toBe(1);
  });
  it("无该样式序号时为 0", () => {
    expect(countOrderedMarkers("纯文本没有序号", "emoji")).toBe(0);
    expect(countOrderedMarkers("", "circle")).toBe(0);
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `npx vitest run src/utils/__tests__/xhsTheme.spec.ts`
Expected: FAIL（`xhsTheme` 模块不存在）。

- [ ] **Step 3: 实现 `xhsTheme.ts`**

Create `frontend/src/utils/xhsTheme.ts`:

```ts
/**
 * 排版主题「有序列表」符号工具（设计稿 §3.3 ordered / §5 主题）。
 *
 * P1 把 themes.json 的 `ordered` 留给 P3：工具条「有序」按钮要按主题样式
 * 插入「下一个序号」。orderedMarker 把第 n 个序号（n 从 1 起）渲染成该样式
 * 的字形；countOrderedMarkers 数出正文里已有的同样式序号个数，二者配合算出
 * 下一个序号。soft helper：跨多个列表会连续计数，作为辅助插入可接受。
 */
import type { XhsTheme } from "@/data/xhs/assets";

export type OrderedStyle = XhsTheme["ordered"]; // "emoji" | "circle" | "superscript"

// 各样式 1..N 的字形表（数组下标 0 = 序号 1）。超出表长用 `${n}.` 兜底。
const ORDERED_GLYPHS: Record<OrderedStyle, string[]> = {
  emoji: ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"],
  circle: ["①", "②", "③", "④", "⑤", "⑥", "⑦", "⑧", "⑨", "⑩",
           "⑪", "⑫", "⑬", "⑭", "⑮", "⑯", "⑰", "⑱", "⑲", "⑳"],
  superscript: ["¹", "²", "³", "⁴", "⁵", "⁶", "⁷", "⁸", "⁹"],
};

/** 第 n 个序号（n 从 1 起）渲染成 style 样式字形；n<1 返回空串、超表返回 `${n}.`。 */
export function orderedMarker(n: number, style: OrderedStyle): string {
  if (n < 1) return "";
  const glyphs = ORDERED_GLYPHS[style] ?? [];
  return glyphs[n - 1] ?? `${n}.`;
}

/** 数出 body 中 style 样式已出现的序号字形总数（用于推算下一个序号）。 */
export function countOrderedMarkers(body: string, style: OrderedStyle): number {
  const glyphs = ORDERED_GLYPHS[style] ?? [];
  let count = 0;
  for (const g of glyphs) {
    count += body.split(g).length - 1;
  }
  return count;
}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `npx vitest run src/utils/__tests__/xhsTheme.spec.ts`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/utils/xhsTheme.ts frontend/src/utils/__tests__/xhsTheme.spec.ts
git commit -m "feat(xhs): 有序列表序号字形工具 orderedMarker/countOrderedMarkers (P3 T2)"
```

---

## Task 3: store 接通「有序」+ 工具条按钮（TDD）

**Files:**
- Modify: `frontend/src/stores/xhs.ts:16`（import）、`:98`（themeToolbar）、actions 区
- Modify: `frontend/src/components/xhs/NoteEditor.vue:63`
- Test: `frontend/src/stores/__tests__/xhs.spec.ts:192`（更新既有断言）+ 新增

- [ ] **Step 1: 更新既有 themeToolbar 断言 + 新增 ordered 断言（先让测试反映目标）**

`frontend/src/stores/__tests__/xhs.spec.ts:192` 现有：

```ts
    expect(tb.map((b) => b.key)).toEqual(["heading", "bullet", "divider"]);
```

改成（顺序对齐设计稿「小标题/无序/有序/分割线」）：

```ts
    expect(tb.map((b) => b.key)).toEqual(["heading", "bullet", "ordered", "divider"]);
```

并在该 `describe("useXhs — 排版主题", ...)` 块末尾（`xhs.spec.ts:177` 之后的同级位置，紧跟现有主题用例）新增两个用例：

```ts
  it("themeToolbar 的「有序」symbol = 该主题样式的第 1 个序号字形", () => {
    const x = useXhs();
    const t = THEMES.find((th) => th.ordered === "circle") ?? THEMES[0];
    x.applyTheme(t.id);
    const ordered = x.themeToolbar.find((b) => b.key === "ordered");
    expect(ordered?.label).toBe("有序");
    expect(ordered?.symbol).toBe(orderedMarker(1, t.ordered));
  });

  it("insertOrdered 按正文已有序号数插入下一个序号", () => {
    const x = useXhs();
    const t = THEMES.find((th) => th.ordered === "emoji") ?? THEMES[0];
    x.applyTheme(t.id);
    x.setBody("1️⃣ 第一条\n"); // 已有 1 个 emoji 序号
    x.insertOrdered();          // 应插入第 2 个 → "2️⃣ "
    expect(x.body).toContain("2️⃣ ");
  });

  it("无激活主题时 insertOrdered 不动正文", () => {
    const x = useXhs();
    x.setBody("原样");
    x.insertOrdered();
    expect(x.body).toBe("原样");
  });
```

在 `xhs.spec.ts` 顶部 import 区补上工具函数 import（若尚无）：

```ts
import { orderedMarker } from "@/utils/xhsTheme";
```

（`THEMES` 该文件已 import；若无则一并补 `import { THEMES } from "@/data/xhs/assets";`。）

- [ ] **Step 2: 跑测试确认失败**

Run: `npx vitest run src/stores/__tests__/xhs.spec.ts`
Expected: FAIL（themeToolbar 仍是 3 项、`insertOrdered` 未定义）。

- [ ] **Step 3: store 加 import + themeToolbar 加「有序」+ insertOrdered**

`frontend/src/stores/xhs.ts:16` 现有：

```ts
import { findTheme, type XhsTheme } from "@/data/xhs/assets";
```

其后补一行：

```ts
import { orderedMarker, countOrderedMarkers } from "@/utils/xhsTheme";
```

把 `themeToolbar` getter（`xhs.ts:98-106`）整体替换为（在 bullet 与 divider 间插入 ordered，symbol 用第 1 个序号字形作提示）：

```ts
    /** 工具条快捷符号按钮：激活主题 → 小标题/无序/有序/分割线（无主题时空）。
     *  「有序」的 symbol 仅作按钮提示（该样式第 1 个序号字形），点击实际走
     *  insertOrdered 按正文已有序号推算下一个。用 function 形式以便 this 访问 activeTheme。 */
    themeToolbar(): { key: string; label: string; symbol: string }[] {
      const t = this.activeTheme;
      if (!t) return [];
      return [
        { key: "heading", label: "小标题", symbol: t.heading },
        { key: "bullet", label: "无序", symbol: t.bullet },
        { key: "ordered", label: "有序", symbol: orderedMarker(1, t.ordered) },
        { key: "divider", label: "分割线", symbol: t.divider },
      ];
    },
```

在 actions 区（紧跟 `applyTheme` 之后，`xhs.ts:153` 附近）新增 action：

```ts
    /** 工具条「有序」：按激活主题 ordered 样式，在光标处插入「下一个序号 + 空格」。
     *  下一个序号 = 正文已有同样式序号个数 + 1。无激活主题时不动。 */
    insertOrdered(): void {
      const t = this.activeTheme;
      if (!t) return;
      const n = countOrderedMarkers(this.body, t.ordered) + 1;
      this.insertAtCursor(orderedMarker(n, t.ordered) + " ");
    },
```

- [ ] **Step 4: NoteEditor 工具条「有序」按钮分支到 insertOrdered**

`frontend/src/components/xhs/NoteEditor.vue:63` 现有：

```html
          @click="xhs.insertAtCursor(b.symbol)"
```

改成：

```html
          @click="b.key === 'ordered' ? xhs.insertOrdered() : xhs.insertAtCursor(b.symbol)"
```

- [ ] **Step 5: 跑测试确认通过**

Run: `npx vitest run src/stores/__tests__/xhs.spec.ts src/components/xhs/__tests__/NoteEditor.spec.ts`
Expected: PASS（themeToolbar 四项、insertOrdered 递增、NoteEditor 既有用例不回归）。

- [ ] **Step 6: Commit**

```bash
git add frontend/src/stores/xhs.ts frontend/src/stores/__tests__/xhs.spec.ts frontend/src/components/xhs/NoteEditor.vue
git commit -m "feat(xhs): 工具条接通「有序」序号插入 insertOrdered (P3 T3)"
```

---

## Task 4: ThemePanel 卡片预览补「有序」样例行

**Files:**
- Modify: `frontend/src/components/xhs/panels/ThemePanel.vue`
- Test: `frontend/src/components/xhs/panels/__tests__/ThemePanel.spec.ts`

让主题卡的样例预览展示全 4 类结构符号（小标题 / 无序 / **有序** / 分割线），完成设计稿「每卡带样例预览」。

- [ ] **Step 1: 写失败测试**

在 `frontend/src/components/xhs/panels/__tests__/ThemePanel.spec.ts` 的 `describe("ThemePanel", ...)` 块内新增用例（顶部补 `import { orderedMarker } from "@/utils/xhsTheme";`）：

```ts
  it("卡片预览含有序样例（第一个主题样式的序号字形）", () => {
    const w = mount(ThemePanel);
    const firstCard = w.findAll(".xhs-theme-card")[0];
    expect(firstCard.text()).toContain(orderedMarker(1, THEMES[0].ordered));
    w.unmount();
  });
```

- [ ] **Step 2: 跑测试确认失败**

Run: `npx vitest run src/components/xhs/panels/__tests__/ThemePanel.spec.ts`
Expected: FAIL（卡片尚无有序样例行）。

- [ ] **Step 3: ThemePanel 预览补「有序」样例行**

`frontend/src/components/xhs/panels/ThemePanel.vue` 顶部 `<script setup>` 补 import（在 `import { THEMES }...` 后）：

```ts
import { orderedMarker } from "@/utils/xhsTheme";
```

把卡片预览块（`ThemePanel.vue:30-34` 的 `<div :style="{ fontSize: '13px'... }">` 内部）中「列表项一」那行之后、divider 之前插入有序样例行。即把：

```html
      <div :style="{ fontSize: '13px', color: 'var(--ink)', lineHeight: 1.9 }">
        <div>{{ t.heading }} 小标题示例</div>
        <div>{{ t.bullet }} 列表项一</div>
        <div :style="{ color: 'var(--ink-2)' }">{{ t.divider }}</div>
      </div>
```

替换为：

```html
      <div :style="{ fontSize: '13px', color: 'var(--ink)', lineHeight: 1.9 }">
        <div>{{ t.heading }} 小标题示例</div>
        <div>{{ t.bullet }} 无序列表项</div>
        <div>{{ orderedMarker(1, t.ordered) }} 有序列表项</div>
        <div :style="{ color: 'var(--ink-2)' }">{{ t.divider }}</div>
      </div>
```

- [ ] **Step 4: 跑测试确认通过**

Run: `npx vitest run src/components/xhs/panels/__tests__/ThemePanel.spec.ts`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/xhs/panels/ThemePanel.vue frontend/src/components/xhs/panels/__tests__/ThemePanel.spec.ts
git commit -m "feat(xhs): 主题卡预览补有序样例行 (P3 T4)"
```

---

# AI 轨（T5–T8，前后端）

## Task 5: 后端 `xhs_ai_service`（生成 + 润色，TDD）

**Files:**
- Create: `sidecar/csm_sidecar/services/xhs_ai_service.py`
- Test: `sidecar/tests/test_xhs_ai_service.py`
- Modify: `sidecar/csm-sidecar.spec:222`（hiddenimports）

`generate_note` 引导模型输出 JSON `{title, body, topics}`，service 端解析；解析失败兜底为「整段塞正文」（设计稿 §4.6）。`polish_note` 输入正文 → 小红书风正文。两者都走 `llm_factory.build_client()`，未配置时 `LLMConfigError` 透传给路由。**P3 用内置 prompt 常量，不读 config 自定义（P4 再做）。**

- [ ] **Step 1: 写失败测试**

Create `sidecar/tests/test_xhs_ai_service.py`:

```python
"""Tests for xhs_ai_service —— AI 生成整篇 + 润色正文（P3）.

Mock 策略同 mining：recording fake client + monkeypatch build_client；
503 分支不打 patch，让真 build_client 抛 LLMConfigError。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from csm_sidecar.services import config_service, xhs_ai_service
from csm_sidecar.services.llm_factory import LLMConfigError


class _RecordingClient:
    def __init__(self, response: str = ""):
        self.response = response
        self.calls: list[dict] = []

    def complete(self, *, system: str, user: str, temperature: float | None = None) -> str:
        self.calls.append({"system": system, "user": user, "temperature": temperature})
        return self.response


@pytest.fixture
def fake_client(monkeypatch: pytest.MonkeyPatch) -> _RecordingClient:
    client = _RecordingClient()
    monkeypatch.setattr(
        xhs_ai_service.llm_factory, "build_client", lambda **kw: client,
    )
    return client


# ── _parse_generated ────────────────────────────────────────────────────
def test_parse_generated_valid_json():
    out = xhs_ai_service._parse_generated(
        '{"title": "标题", "body": "正文", "topics": ["a", "b"]}'
    )
    assert out == {"title": "标题", "body": "正文", "topics": ["a", "b"]}


def test_parse_generated_strips_code_fence():
    out = xhs_ai_service._parse_generated(
        '```json\n{"title": "T", "body": "B", "topics": ["x"]}\n```'
    )
    assert out["title"] == "T"
    assert out["topics"] == ["x"]


def test_parse_generated_non_json_falls_back_to_body():
    out = xhs_ai_service._parse_generated("这不是 JSON，只是一段文字")
    assert out == {"title": "", "body": "这不是 JSON，只是一段文字", "topics": []}


def test_parse_generated_filters_non_string_topics():
    out = xhs_ai_service._parse_generated(
        '{"title": "T", "body": "B", "topics": ["ok", 123, null]}'
    )
    assert out["topics"] == ["ok"]


def test_parse_generated_missing_fields_default_empty():
    out = xhs_ai_service._parse_generated('{"title": "只有标题"}')
    assert out == {"title": "只有标题", "body": "", "topics": []}


# ── generate_note ─────────────────────────────────────────────────────────
def test_generate_note_returns_parsed_dict(settings_path: Path, fake_client: _RecordingClient):
    config_service.patch({"default_provider": "mock"})
    fake_client.response = '{"title": "平价护肤", "body": "正文内容", "topics": ["护肤", "学生党"]}'
    out = xhs_ai_service.generate_note("学生党平价护肤")
    assert out["title"] == "平价护肤"
    assert out["topics"] == ["护肤", "学生党"]
    # intent 进了 user message
    assert "学生党平价护肤" in fake_client.calls[0]["user"]


def test_generate_note_non_json_fallback(settings_path: Path, fake_client: _RecordingClient):
    config_service.patch({"default_provider": "mock"})
    fake_client.response = "模型没按 JSON 输出，直接给了一段正文"
    out = xhs_ai_service.generate_note("随便")
    assert out["title"] == ""
    assert out["body"] == "模型没按 JSON 输出，直接给了一段正文"
    assert out["topics"] == []


def test_generate_note_raises_when_no_provider(settings_path: Path):
    # 不 patch default_provider → 真 build_client 抛 LLMConfigError
    with pytest.raises(LLMConfigError):
        xhs_ai_service.generate_note("主题")


# ── polish_note ─────────────────────────────────────────────────────────
def test_polish_note_returns_stripped(settings_path: Path, fake_client: _RecordingClient):
    config_service.patch({"default_provider": "mock"})
    fake_client.response = "  润色后的小红书风正文  "
    out = xhs_ai_service.polish_note("朴素正文")
    assert out == "润色后的小红书风正文"
    assert fake_client.calls[0]["user"] == "朴素正文"


def test_polish_note_empty_returns_empty_without_llm(settings_path: Path, fake_client: _RecordingClient):
    config_service.patch({"default_provider": "mock"})
    out = xhs_ai_service.polish_note("   ")
    assert out == ""
    assert fake_client.calls == []  # 空输入不打 LLM


def test_polish_note_raises_when_no_provider(settings_path: Path):
    with pytest.raises(LLMConfigError):
        xhs_ai_service.polish_note("正文")
```

- [ ] **Step 2: 跑测试确认失败**

```powershell
$env:PYTHONPATH = "D:\CSM\.claude\worktrees\cranky-varahamihira-d53003\sidecar;D:\CSM\.claude\worktrees\cranky-varahamihira-d53003"
& "D:\CSM\.venv\Scripts\python.exe" -m pytest sidecar/tests/test_xhs_ai_service.py -v
```
Expected: FAIL（`xhs_ai_service` 不存在）。

- [ ] **Step 3: 实现 `xhs_ai_service.py`**

Create `sidecar/csm_sidecar/services/xhs_ai_service.py`:

```python
"""小红书 AI 助手 service（设计稿 §4.6 / P3）.

两个入口：

* :func:`generate_note` —— 输入主题/关键词，引导模型输出 JSON
  ``{title, body, topics}``；service 端解析，解析失败兜底为「整段塞正文」。
* :func:`polish_note` —— 输入正文，返回小红书风改写后的正文。

LLM client 复用 :mod:`llm_factory`（与「文章润色」/mining 同一套设置）。未配置
default provider 时 :class:`LLMConfigError` 透传给路由层包成 503。

P3 只用内置 prompt 常量；用户自定义 prompt（AppConfig.xhs_* + 设置卡）留到 P4。
"""
from __future__ import annotations

import json
import logging
from typing import Any

from . import llm_factory

logger = logging.getLogger(__name__)


# ── 内置 prompt（P3 固定，P4 再做可配置）────────────────────────────────────
DEFAULT_GENERATE_SYSTEM = (
    "你是小红书爆款图文笔记写手。根据用户给的主题 / 关键词，创作一篇小红书风格的图文笔记。\n"
    "要求：\n"
    "1) 标题：≤20 字，有钩子，可带 1-2 个 emoji；\n"
    "2) 正文：口语化、分点、适当 emoji 排版、有代入感，结尾自然引导互动（点赞/收藏/关注）；\n"
    "3) 话题：3-6 个，元素不带 # 前缀。\n"
    "只返回一个 JSON 对象，形如 "
    '{"title": "...", "body": "...", "topics": ["...", "..."]}，'
    "不要输出 JSON 以外的任何文字、解释或 markdown 代码块标记。"
)

DEFAULT_POLISH_SYSTEM = (
    "你是小红书文案润色助手。把用户给的正文改写成小红书爆款风格："
    "口语化、亲切、适当分点和 emoji 排版、保留原意不编造事实、结尾自然引导互动。"
    "只返回改写后的正文，不要加任何前后缀、引号、标题或解释。"
)


# ── helpers ───────────────────────────────────────────────────────────────
def _strip_code_fence(text: str) -> str:
    """去掉模型偶尔包裹的 ```json ... ``` 代码块围栏，留出纯 JSON 给 json.loads。"""
    t = text.strip()
    if not t.startswith("```"):
        return t
    lines = t.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _parse_generated(text: str) -> dict[str, Any]:
    """把模型输出解析成 ``{title, body, topics}``。

    解析失败（非 JSON / 非对象）→ 兜底：整段原文塞进 body（设计稿 §4.6）。
    字段缺失或类型不符 → 该字段取空。
    """
    raw = (text or "").strip()
    try:
        data = json.loads(_strip_code_fence(raw))
    except (json.JSONDecodeError, ValueError):
        data = None
    if isinstance(data, dict):
        title = data.get("title")
        body = data.get("body")
        topics = data.get("topics")
        return {
            "title": title if isinstance(title, str) else "",
            "body": body if isinstance(body, str) else "",
            "topics": [t for t in topics if isinstance(t, str)] if isinstance(topics, list) else [],
        }
    return {"title": "", "body": raw, "topics": []}


# ── 公开 API ────────────────────────────────────────────────────────────────
def generate_note(intent: str) -> dict[str, Any]:
    """根据 intent 生成一篇笔记，返回 ``{title, body, topics}``。

    Raises
    ------
    llm_factory.LLMConfigError
        未配置 default provider / api key（路由层捕获 → 503）。
    """
    intent = (intent or "").strip()
    client = llm_factory.build_client()
    text = client.complete(
        system=DEFAULT_GENERATE_SYSTEM,
        user=f"主题 / 关键词：{intent}",
    )
    return _parse_generated(text)


def polish_note(text: str) -> str:
    """把 ``text`` 润色成小红书风正文。空输入直接返回空（不打 LLM）。

    Raises 同 :func:`generate_note`。
    """
    text = (text or "").strip()
    if not text:
        return ""
    client = llm_factory.build_client()
    out = client.complete(system=DEFAULT_POLISH_SYSTEM, user=text)
    return (out or "").strip()
```

- [ ] **Step 4: 跑测试确认通过**

```powershell
& "D:\CSM\.venv\Scripts\python.exe" -m pytest sidecar/tests/test_xhs_ai_service.py -v
```
Expected: PASS（11 个）。

- [ ] **Step 5: spec 登记 hiddenimport**

`sidecar/csm-sidecar.spec:222` 现有：

```python
    "csm_sidecar.services.xhs_images_service",
```

其后紧跟新增一行：

```python
    "csm_sidecar.services.xhs_ai_service",
```

- [ ] **Step 6: Commit**

```bash
git add sidecar/csm_sidecar/services/xhs_ai_service.py sidecar/tests/test_xhs_ai_service.py sidecar/csm-sidecar.spec
git commit -m "feat(xhs): AI service 生成/润色 复用 llm_factory + 打包登记 (P3 T5)"
```

---

## Task 6: AI 路由（generate / polish，TDD）

**Files:**
- Modify: `sidecar/csm_sidecar/routes/xhs.py:18`（import）+ 文件末尾追加路由
- Test: `sidecar/tests/test_xhs_ai_routes.py`

- [ ] **Step 1: 写失败测试**

Create `sidecar/tests/test_xhs_ai_routes.py`:

```python
"""Routes for xhs AI 生成/润色（P3）.

错误映射沿用 mining：无 provider → 503 llm_not_configured；LLM 抛异常 → 502
llm_error；空入参 → 400。Happy path 用 recording fake 注入。
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from csm_sidecar.services import config_service, xhs_ai_service


class _RecordingClient:
    def __init__(self, response: str = ""):
        self.response = response
        self.calls: list[dict] = []

    def complete(self, *, system: str, user: str, temperature: float | None = None) -> str:
        self.calls.append({"system": system, "user": user, "temperature": temperature})
        return self.response


@pytest.fixture
def fake_client(monkeypatch: pytest.MonkeyPatch) -> _RecordingClient:
    client = _RecordingClient()
    monkeypatch.setattr(
        xhs_ai_service.llm_factory, "build_client", lambda **kw: client,
    )
    return client


# ── generate ──────────────────────────────────────────────────────────────
def test_generate_returns_title_body_topics(
    client: TestClient, settings_path: Path, fake_client: _RecordingClient,
):
    config_service.patch({"default_provider": "mock"})
    fake_client.response = '{"title": "T", "body": "B", "topics": ["x", "y"]}'
    r = client.post("/api/xhs/ai/generate", json={"intent": "平价护肤"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body == {"title": "T", "body": "B", "topics": ["x", "y"]}


def test_generate_empty_intent_returns_400(
    client: TestClient, settings_path: Path, fake_client: _RecordingClient,
):
    config_service.patch({"default_provider": "mock"})
    r = client.post("/api/xhs/ai/generate", json={"intent": "   "})
    assert r.status_code == 400


def test_generate_no_provider_returns_503(client: TestClient, settings_path: Path):
    r = client.post("/api/xhs/ai/generate", json={"intent": "主题"})
    assert r.status_code == 503
    assert r.json()["detail"]["code"] == "llm_not_configured"


def test_generate_llm_error_returns_502(
    client: TestClient, settings_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    config_service.patch({"default_provider": "mock"})

    class _Boom:
        def complete(self, *, system, user, temperature=None):
            raise RuntimeError("upstream 500")

    monkeypatch.setattr(
        xhs_ai_service.llm_factory, "build_client", lambda **kw: _Boom(),
    )
    r = client.post("/api/xhs/ai/generate", json={"intent": "主题"})
    assert r.status_code == 502
    assert r.json()["detail"]["code"] == "llm_error"
    assert "upstream 500" in r.json()["detail"]["detail"]


# ── polish ────────────────────────────────────────────────────────────────
def test_polish_returns_body(
    client: TestClient, settings_path: Path, fake_client: _RecordingClient,
):
    config_service.patch({"default_provider": "mock"})
    fake_client.response = "润色后正文"
    r = client.post("/api/xhs/ai/polish", json={"text": "朴素正文"})
    assert r.status_code == 200, r.text
    assert r.json() == {"body": "润色后正文"}


def test_polish_empty_text_returns_400(
    client: TestClient, settings_path: Path, fake_client: _RecordingClient,
):
    config_service.patch({"default_provider": "mock"})
    r = client.post("/api/xhs/ai/polish", json={"text": ""})
    assert r.status_code == 400


def test_polish_no_provider_returns_503(client: TestClient, settings_path: Path):
    r = client.post("/api/xhs/ai/polish", json={"text": "正文"})
    assert r.status_code == 503
    assert r.json()["detail"]["code"] == "llm_not_configured"
```

- [ ] **Step 2: 跑测试确认失败**

```powershell
& "D:\CSM\.venv\Scripts\python.exe" -m pytest sidecar/tests/test_xhs_ai_routes.py -v
```
Expected: FAIL（路由 404 / 未实现）。

- [ ] **Step 3: routes/xhs.py 加 import + AI 路由**

`sidecar/csm_sidecar/routes/xhs.py:18` 现有：

```python
from ..services import xhs_images_service
```

替换为（加 xhs_ai_service + LLMConfigError）：

```python
from ..services import xhs_ai_service, xhs_images_service
from ..services.llm_factory import LLMConfigError
```

在文件**末尾**（`get_image` 之后）追加：

```python


# ── AI 助手（P3）─────────────────────────────────────────────────────────────
class AiGenerateBody(BaseModel):
    intent: str = ""


class AiPolishBody(BaseModel):
    text: str = ""


def _llm_http_error(e: Exception) -> HTTPException:
    """LLMConfigError → 503 llm_not_configured；其余 LLM 异常 → 502 llm_error。

    与 mining AI 路由同款映射，前端据 detail.code 区分「去设置」与普通报错。
    """
    if isinstance(e, LLMConfigError):
        return HTTPException(
            status_code=503,
            detail={"code": "llm_not_configured", "detail": str(e)},
        )
    return HTTPException(
        status_code=502,
        detail={"code": "llm_error", "detail": str(e) or e.__class__.__name__},
    )


@router.post("/api/xhs/ai/generate")
def ai_generate(body: AiGenerateBody) -> dict[str, Any]:
    """输入主题/关键词 → 返回 {title, body, topics}（前端决定是否覆盖填入）。"""
    if not body.intent.strip():
        raise HTTPException(status_code=400, detail="intent required")
    try:
        return xhs_ai_service.generate_note(body.intent)
    except LLMConfigError as e:
        raise _llm_http_error(e)
    except Exception as e:  # noqa: BLE001 —— LLM client 可能抛任何异常
        logger.exception("xhs ai_generate failed")
        raise _llm_http_error(e)


@router.post("/api/xhs/ai/polish")
def ai_polish(body: AiPolishBody) -> dict[str, Any]:
    """输入正文 → 返回 {body: 润色后正文}。"""
    if not body.text.strip():
        raise HTTPException(status_code=400, detail="text required")
    try:
        return {"body": xhs_ai_service.polish_note(body.text)}
    except LLMConfigError as e:
        raise _llm_http_error(e)
    except Exception as e:  # noqa: BLE001
        logger.exception("xhs ai_polish failed")
        raise _llm_http_error(e)
```

- [ ] **Step 4: 跑测试确认通过**

```powershell
& "D:\CSM\.venv\Scripts\python.exe" -m pytest sidecar/tests/test_xhs_ai_routes.py -v
```
Expected: PASS（7 个）。

- [ ] **Step 5: Commit**

```bash
git add sidecar/csm_sidecar/routes/xhs.py sidecar/tests/test_xhs_ai_routes.py
git commit -m "feat(xhs): AI 生成/润色路由 + 503/502 错误映射 (P3 T6)"
```

---

## Task 7: store AI actions（generate / polish + 503 解包，TDD）

**Files:**
- Modify: `frontend/src/stores/xhs.ts`（import AxiosError、加 LLMNotConfiguredError/_wrapLLMError、generateNote/polishBody）
- Test: `frontend/src/stores/__tests__/xhs.spec.ts`

- [ ] **Step 1: 写失败测试**

在 `frontend/src/stores/__tests__/xhs.spec.ts` 末尾新增（顶部 import 补 `LLMNotConfiguredError`：把现有 `import { useXhs, _resetXhsModuleState } from "@/stores/xhs";` 改为 `import { useXhs, _resetXhsModuleState, LLMNotConfiguredError } from "@/stores/xhs";`）：

```ts
describe("useXhs — AI actions", () => {
  it("generateNote 返回后端 {title, body, topics}", async () => {
    const x = useXhs();
    const sidecar = useSidecar();
    vi.mocked(sidecar.client.post).mockResolvedValueOnce({
      data: { title: "T", body: "B", topics: ["a", "b"] },
    });
    const out = await x.generateNote("主题");
    expect(out).toEqual({ title: "T", body: "B", topics: ["a", "b"] });
    expect(sidecar.client.post).toHaveBeenCalledWith("/api/xhs/ai/generate", { intent: "主题" });
  });

  it("generateNote 缺字段时各自取空", async () => {
    const x = useXhs();
    const sidecar = useSidecar();
    vi.mocked(sidecar.client.post).mockResolvedValueOnce({ data: { title: "只有标题" } });
    const out = await x.generateNote("主题");
    expect(out).toEqual({ title: "只有标题", body: "", topics: [] });
  });

  it("503 llm_not_configured → 抛 LLMNotConfiguredError", async () => {
    const x = useXhs();
    const sidecar = useSidecar();
    vi.mocked(sidecar.client.post).mockRejectedValueOnce({
      response: { status: 503, data: { code: "llm_not_configured", detail: "去配置" } },
    });
    await expect(x.generateNote("主题")).rejects.toBeInstanceOf(LLMNotConfiguredError);
  });

  it("polishBody 把当前正文 POST 给 /polish 并返回 body", async () => {
    const x = useXhs();
    x.setBody("朴素正文");
    const sidecar = useSidecar();
    vi.mocked(sidecar.client.post).mockResolvedValueOnce({ data: { body: "润色后" } });
    const out = await x.polishBody();
    expect(out).toBe("润色后");
    expect(sidecar.client.post).toHaveBeenCalledWith("/api/xhs/ai/polish", { text: "朴素正文" });
  });

  it("polishBody 非 503 错误原样抛出（不包成 LLMNotConfiguredError）", async () => {
    const x = useXhs();
    x.setBody("正文");
    const sidecar = useSidecar();
    const boom = { response: { status: 502, data: { code: "llm_error" } } };
    vi.mocked(sidecar.client.post).mockRejectedValueOnce(boom);
    await expect(x.polishBody()).rejects.not.toBeInstanceOf(LLMNotConfiguredError);
  });
});
```

> 注：该 spec 顶部应已 `vi.mock("@/stores/sidecar", ...)` 且 import 了 `useSidecar`（P2 的图片 action 测试已建立此模式）。若没有，参照 `ImagePanel.spec.ts` 的 sidecar mock 形状，并确保 `client.post` 是可 `vi.mocked(...)` 的 `vi.fn()`。

- [ ] **Step 2: 跑测试确认失败**

Run: `npx vitest run src/stores/__tests__/xhs.spec.ts`
Expected: FAIL（`generateNote`/`polishBody`/`LLMNotConfiguredError` 未定义）。

- [ ] **Step 3: store 加 AxiosError import + 错误类 + 包装 + 两个 action**

`frontend/src/stores/xhs.ts` 顶部 import 区补（与其它 import 同处）：

```ts
import type { AxiosError } from "axios";
```

在 `export const useXhs = defineStore(...)` **之前**（模块级，与 `_resetXhsModuleState` 同级）新增错误类 + 包装函数：

```ts
/**
 * 503 + code="llm_not_configured" 时抛出。AiPanel 据此弹「去设置」toast，
 * 而非通用报错。与 mining store 的同名类各自独立（xhs 模块自洽，不耦合 mining）。
 */
export class LLMNotConfiguredError extends Error {
  constructor(message = "请先在设置中配置 AI 服务") {
    super(message);
    this.name = "LLMNotConfiguredError";
  }
}

/** 把 sidecar AI 路由的 503 llm_not_configured 解包成 LLMNotConfiguredError，其余原样抛。 */
function _wrapLLMError(err: unknown): never {
  const ax = err as AxiosError<{ code?: string; detail?: string }>;
  const resp = ax?.response;
  if (resp?.status === 503 && resp.data?.code === "llm_not_configured") {
    throw new LLMNotConfiguredError(resp.data.detail || undefined);
  }
  throw err;
}
```

在 actions 区末尾（`deleteDraft` 之后）新增两个 action：

```ts
    /** AI 生成整篇：返回 {title, body, topics}（调用方决定是否覆盖填入）。
     *  503 未配置 LLM → 抛 LLMNotConfiguredError（AiPanel 弹「去设置」）。 */
    async generateNote(intent: string): Promise<{ title: string; body: string; topics: string[] }> {
      const sidecar = useSidecar();
      try {
        const r = await sidecar.client.post("/api/xhs/ai/generate", { intent });
        return {
          title: typeof r.data?.title === "string" ? r.data.title : "",
          body: typeof r.data?.body === "string" ? r.data.body : "",
          topics: Array.isArray(r.data?.topics) ? r.data.topics : [],
        };
      } catch (e) {
        _wrapLLMError(e);
      }
    },
    /** AI 润色当前正文：返回润色后文本（不直接写回，调用方决定）。 */
    async polishBody(): Promise<string> {
      const sidecar = useSidecar();
      try {
        const r = await sidecar.client.post("/api/xhs/ai/polish", { text: this.body });
        return typeof r.data?.body === "string" ? r.data.body : "";
      } catch (e) {
        _wrapLLMError(e);
      }
    },
```

> `_wrapLLMError` 返回 `never`（恒抛），故 catch 块之后无 return 也满足 `Promise<...>` 返回类型（与 mining.ts 的 `summarize`/`suggestComment` 同样写法，TS 据 `never` 判定后续不可达）。

- [ ] **Step 4: 跑测试确认通过**

Run: `npx vitest run src/stores/__tests__/xhs.spec.ts`
Expected: PASS（含 T3 的主题用例 + T7 的 AI 用例）。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/stores/xhs.ts frontend/src/stores/__tests__/xhs.spec.ts
git commit -m "feat(xhs): store AI actions generateNote/polishBody + 503 解包 (P3 T7)"
```

---

## Task 8: `AiPanel.vue` + 接入 PanelRail

**Files:**
- Create: `frontend/src/components/xhs/panels/AiPanel.vue`
- Modify: `frontend/src/components/xhs/PanelRail.vue`
- Test: `frontend/src/components/xhs/panels/__tests__/AiPanel.spec.ts`

- [ ] **Step 1: 写失败测试**

Create `frontend/src/components/xhs/panels/__tests__/AiPanel.spec.ts`:

```ts
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { mount, flushPromises } from "@vue/test-utils";

vi.mock("@/stores/sidecar", () => ({
  useSidecar: () => ({
    client: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
    sseURL: (p: string) => p,
  }),
}));

// 稳定 spy（vi.hoisted 避免 vi.mock 提升导致的未初始化）。
const { toastSuccess, toastError, toastWarn, routerPush, confirmFn } = vi.hoisted(() => ({
  toastSuccess: vi.fn(),
  toastError: vi.fn(),
  toastWarn: vi.fn(),
  routerPush: vi.fn(),
  confirmFn: vi.fn().mockResolvedValue(true),
}));
vi.mock("@/composables/useToast", () => ({
  useToast: () => ({ success: toastSuccess, error: toastError, warn: toastWarn }),
}));
vi.mock("vue-router", () => ({ useRouter: () => ({ push: routerPush }) }));
vi.mock("@/composables/useConfirm", () => ({ confirmDialog: confirmFn }));

import AiPanel from "@/components/xhs/panels/AiPanel.vue";
import { useXhs, _resetXhsModuleState, LLMNotConfiguredError } from "@/stores/xhs";

beforeEach(() => {
  setActivePinia(createPinia());
  _resetXhsModuleState();
  toastSuccess.mockClear();
  toastError.mockClear();
  toastWarn.mockClear();
  routerPush.mockClear();
  confirmFn.mockClear().mockResolvedValue(true);
  vi.useFakeTimers();
});
afterEach(() => {
  vi.clearAllTimers();
  vi.useRealTimers();
});

function setIntent(w: ReturnType<typeof mount>, v: string) {
  const ta = w.find("textarea.xhs-ai-input");
  return ta.setValue(v);
}

describe("AiPanel —— 生成整篇", () => {
  it("空主题点生成 → warn，不调 store", async () => {
    const store = useXhs();
    const spy = vi.spyOn(store, "generateNote");
    const w = mount(AiPanel);
    await w.find("button.xhs-ai-btn-primary").trigger("click");
    await flushPromises();
    expect(toastWarn).toHaveBeenCalled();
    expect(spy).not.toHaveBeenCalled();
    w.unmount();
  });

  it("编辑器为空 → 不弹确认，直接 applyTemplate 填入", async () => {
    const store = useXhs();
    vi.spyOn(store, "generateNote").mockResolvedValue({ title: "T", body: "B", topics: ["x"] });
    const applySpy = vi.spyOn(store, "applyTemplate");
    const w = mount(AiPanel);
    await setIntent(w, "平价护肤");
    await w.find("button.xhs-ai-btn-primary").trigger("click");
    await flushPromises();
    expect(confirmFn).not.toHaveBeenCalled();
    expect(applySpy).toHaveBeenCalledWith({ title: "T", body: "B", topics: ["x"] });
    expect(toastSuccess).toHaveBeenCalled();
    w.unmount();
  });

  it("编辑器非空 → 先弹确认；确认后 applyTemplate", async () => {
    const store = useXhs();
    store.$patch({ body: "已有内容" });
    vi.spyOn(store, "generateNote").mockResolvedValue({ title: "T", body: "B", topics: [] });
    const applySpy = vi.spyOn(store, "applyTemplate");
    const w = mount(AiPanel);
    await setIntent(w, "主题");
    await w.find("button.xhs-ai-btn-primary").trigger("click");
    await flushPromises();
    expect(confirmFn).toHaveBeenCalledTimes(1);
    expect(applySpy).toHaveBeenCalled();
    w.unmount();
  });

  it("编辑器非空 → 取消确认 → 不调 generateNote、不 applyTemplate", async () => {
    confirmFn.mockResolvedValueOnce(false);
    const store = useXhs();
    store.$patch({ body: "已有内容" });
    const genSpy = vi.spyOn(store, "generateNote");
    const applySpy = vi.spyOn(store, "applyTemplate");
    const w = mount(AiPanel);
    await setIntent(w, "主题");
    await w.find("button.xhs-ai-btn-primary").trigger("click");
    await flushPromises();
    expect(genSpy).not.toHaveBeenCalled();
    expect(applySpy).not.toHaveBeenCalled();
    w.unmount();
  });

  it("LLMNotConfiguredError → toast.error 带「去设置」、点击跳 /settings", async () => {
    const store = useXhs();
    vi.spyOn(store, "generateNote").mockRejectedValue(new LLMNotConfiguredError());
    const w = mount(AiPanel);
    await setIntent(w, "主题");
    await w.find("button.xhs-ai-btn-primary").trigger("click");
    await flushPromises();
    expect(toastError).toHaveBeenCalledTimes(1);
    const opts = toastError.mock.calls[0][1];
    expect(opts.actionLabel).toBe("去设置");
    opts.onAction();
    expect(routerPush).toHaveBeenCalledWith("/settings");
    w.unmount();
  });
});

describe("AiPanel —— 润色正文", () => {
  it("正文为空点润色 → warn，不调 store", async () => {
    const store = useXhs();
    const spy = vi.spyOn(store, "polishBody");
    const w = mount(AiPanel);
    await w.find("button.xhs-ai-btn-polish").trigger("click");
    await flushPromises();
    expect(toastWarn).toHaveBeenCalled();
    expect(spy).not.toHaveBeenCalled();
    w.unmount();
  });

  it("正文非空 → polishBody 后 setBody 填回 + success", async () => {
    const store = useXhs();
    store.$patch({ body: "朴素正文" });
    vi.spyOn(store, "polishBody").mockResolvedValue("润色后");
    const setSpy = vi.spyOn(store, "setBody");
    const w = mount(AiPanel);
    await w.find("button.xhs-ai-btn-polish").trigger("click");
    await flushPromises();
    expect(setSpy).toHaveBeenCalledWith("润色后");
    expect(toastSuccess).toHaveBeenCalled();
    w.unmount();
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `npx vitest run src/components/xhs/panels/__tests__/AiPanel.spec.ts`
Expected: FAIL（AiPanel 不存在）。

- [ ] **Step 3: 实现 `AiPanel.vue`**

Create `frontend/src/components/xhs/panels/AiPanel.vue`:

```vue
<script setup lang="ts">
/**
 * AI 助手面板（设计稿 §5「AI 助手」/ §1 P3 / §4.6）。
 * 两个能力：① 生成整篇（输入主题 → title/body/topics 填入，编辑器非空先确认覆盖）；
 * ② 润色当前正文（小红书风改写后填回）。未配置 LLM → toast「去设置」跳 /settings。
 */
import { ref } from "vue";
import { useRouter } from "vue-router";
import Icon from "@/components/ui/Icon.vue";
import { useXhs, LLMNotConfiguredError } from "@/stores/xhs";
import { useToast } from "@/composables/useToast";
import { confirmDialog } from "@/composables/useConfirm";

const xhs = useXhs();
const toast = useToast();
const router = useRouter();

const intent = ref("");
const generating = ref(false);
const polishing = ref(false);

function handleAiError(err: unknown) {
  if (err instanceof LLMNotConfiguredError) {
    toast.error("请先在设置中配置 AI 服务", {
      actionLabel: "去设置",
      onAction: () => { router.push("/settings"); },
    });
  } else {
    toast.error("AI 服务调用失败，请稍后重试");
  }
}

async function generate() {
  const text = intent.value.trim();
  if (!text) { toast.warn("请先填写主题或关键词"); return; }
  if (generating.value) return;
  // 先确认覆盖再花 LLM 调用（取消则不请求）。
  if (!xhs.isEmpty) {
    const ok = await confirmDialog("AI 生成会覆盖当前的标题 / 正文 / 话题，确定吗？", {
      title: "AI 生成", okLabel: "覆盖", kind: "danger",
    });
    if (!ok) return;
  }
  generating.value = true;
  try {
    const result = await xhs.generateNote(text);
    xhs.applyTemplate({ title: result.title, body: result.body, topics: result.topics });
    toast.success("已填入 AI 生成内容");
  } catch (err) {
    handleAiError(err);
  } finally {
    generating.value = false;
  }
}

async function polish() {
  if (!xhs.body.trim()) { toast.warn("正文为空，先写点内容再润色"); return; }
  if (polishing.value) return;
  polishing.value = true;
  try {
    const text = await xhs.polishBody();
    xhs.setBody(text);
    toast.success("已润色正文");
  } catch (err) {
    handleAiError(err);
  } finally {
    polishing.value = false;
  }
}
</script>

<template>
  <div class="flex h-full flex-col overflow-y-auto" :style="{ gap: '16px' }">
    <!-- 生成整篇 -->
    <section :style="{ display: 'flex', flexDirection: 'column', gap: '8px' }">
      <div :style="{ fontSize: '13px', fontWeight: 600, color: 'var(--ink)' }">AI 生成整篇</div>
      <div :style="{ fontSize: '11px', color: 'var(--ink-2)' }">
        输入主题 / 关键词，生成标题 + 正文 + 话题（会覆盖当前内容，先确认）
      </div>
      <textarea
        v-model="intent"
        class="xhs-ai-input"
        placeholder="例：学生党平价护肤好物分享"
        rows="3"
      />
      <button
        type="button"
        class="xhs-ai-btn xhs-ai-btn-primary"
        :disabled="generating"
        @click="generate"
      >
        <Icon name="spark" :size="14" />
        {{ generating ? '生成中…' : '生成整篇' }}
      </button>
    </section>

    <div :style="{ height: '1px', background: 'var(--line-2)', flexShrink: 0 }" />

    <!-- 润色正文 -->
    <section :style="{ display: 'flex', flexDirection: 'column', gap: '8px' }">
      <div :style="{ fontSize: '13px', fontWeight: 600, color: 'var(--ink)' }">AI 润色正文</div>
      <div :style="{ fontSize: '11px', color: 'var(--ink-2)' }">
        把当前正文改写成更地道的小红书风（口语化 + emoji 排版）
      </div>
      <button
        type="button"
        class="xhs-ai-btn xhs-ai-btn-polish"
        :disabled="polishing"
        @click="polish"
      >
        <Icon name="wand" :size="14" />
        {{ polishing ? '润色中…' : '润色当前正文' }}
      </button>
    </section>

    <div :style="{ fontSize: '11px', color: 'var(--ink-2)', marginTop: 'auto', flexShrink: 0 }">
      使用与「文章润色」相同的 AI 设置；未配置时会提示去设置。
    </div>
  </div>
</template>

<style scoped>
.xhs-ai-input {
  width: 100%;
  border: 1px solid var(--line-2);
  border-radius: 10px;
  padding: 10px 12px;
  background: #fff;
  color: var(--ink);
  font-size: 13px;
  line-height: 1.6;
  outline: none;
  resize: none;
  box-sizing: border-box;
  font-family: inherit;
}
.xhs-ai-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  font-size: 13px;
  padding: 9px 14px;
  border-radius: 10px;
  border: 1px solid var(--line-2);
  background: #fff;
  color: var(--ink);
  cursor: pointer;
  transition: filter 0.15s;
}
.xhs-ai-btn:hover {
  filter: brightness(0.97);
}
.xhs-ai-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
.xhs-ai-btn-primary {
  background: var(--primary);
  color: #fff;
  border-color: var(--primary);
}
</style>
```

- [ ] **Step 4: 接入 PanelRail**

`frontend/src/components/xhs/PanelRail.vue` 顶部 import 区，`import ImagePanel ...` 后补：

```ts
import AiPanel from "./panels/AiPanel.vue";
```

`PANEL_COMPONENTS` 映射（`PanelRail.vue:43-52`）加 `ai`：

```ts
const PANEL_COMPONENTS: Partial<Record<XhsPanel, Component>> = {
  template: TemplatePanel,
  theme: ThemePanel,
  emoji: EmojiPanel,
  title: TitlePanel,
  copy: CopyPanel,
  topic: TopicPanel,
  decoration: DecorationPanel,
  image: ImagePanel,
  ai: AiPanel,
};
```

去掉已过时的占位注释：
- `PanelRail.vue:5` 文件头注释 `图片(P2)/AI(P3) 仍占位。` → `9 个面板全部上线。`
- `PanelRail.vue:25` PanelDef.stage 注释 `（仅 ai 仍占位，image 已于 P2 上线）。` → `（9 面板全部上线，stage 仅作展示）。`
- `PanelRail.vue:42` `// activePanel → 面板组件；ai 不在表内 → 走占位分支（image 已于 P2 接入）。` → `// activePanel → 面板组件（9 面板全部映射）。`
- `PanelRail.vue:87` 模板注释 `<!-- 面板内容区：派发到真实面板；仅 ai 仍占位 -->` → `<!-- 面板内容区：派发到对应面板组件 -->`

（占位 `v-else` 分支保留作防御兜底——若将来加未映射的 panel 仍有优雅降级。）

- [ ] **Step 5: 跑测试确认通过**

Run: `npx vitest run src/components/xhs/panels/__tests__/AiPanel.spec.ts`
Expected: PASS（7 个）。

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/xhs/panels/AiPanel.vue frontend/src/components/xhs/panels/__tests__/AiPanel.spec.ts frontend/src/components/xhs/PanelRail.vue
git commit -m "feat(xhs): AI 助手面板 AiPanel（生成/润色）+ 接入 PanelRail (P3 T8)"
```

---

## Task 9: 全量验证

**Files:** 无新增，仅跑闸门。

- [ ] **Step 1: 后端全量 pytest**

```powershell
$env:PYTHONPATH = "D:\CSM\.claude\worktrees\cranky-varahamihira-d53003\sidecar;D:\CSM\.claude\worktrees\cranky-varahamihira-d53003"
& "D:\CSM\.venv\Scripts\python.exe" -m pytest sidecar/tests -q
```
Expected: 全过（含新增 test_xhs_ai_service 11 + test_xhs_ai_routes 7）。

- [ ] **Step 2: 前端全量 vitest**

Run: `npx vitest run`
Expected: 全过（含 xhsTheme / AiPanel / ThemePanel / xhs store 新用例）。

- [ ] **Step 3: 类型检查 + 构建**

Run: `npx vue-tsc -b ; npx vite build`
Expected: 零错零警告。

> ⚠️ `vue-tsc -b` 可能 emit `vite.config.js` / `*.d.ts` 产物 → 跑完 `git status` 检查，若有这些产物 `git checkout -- vite.config.js <emit 的 .d.ts>` 还原（见记忆 reference_csm_dev_worktree_setup）。

- [ ] **Step 4: 确认无意外改动**

Run: `git status` + `git diff --stat origin/main`
Expected: 仅本计划列出的文件，main 未动。

---

## Self-Review（计划自检，已过）

1. **Spec 覆盖**：
   - §1 P3「排版主题预设完整化（多套色系）」→ T1（8 套）+ T2/T3/T4（接通 ordered，完成 §1 P1 起留给 P3 的「有序」符号）。
   - §1 P3「`POST /api/xhs/ai/generate` → {title, body, topics}」→ T5（service JSON 解析兜底）+ T6（路由）+ T7（store）+ T8（面板，覆盖前确认）。
   - §1 P3「`POST /api/xhs/ai/polish` → 文本填回」→ T5/T6/T7/T8。
   - §1 P3「复用 llm_factory.build_client + 内置默认 prompt」→ T5（DEFAULT_* 常量，不接 config）。
   - §1 P3 / §4.6「未配置 LLM 错误提示并链接到设置」→ T6（503 llm_not_configured）+ T7（LLMNotConfiguredError）+ T8（toast「去设置」→ /settings）。
   - §4.6「generate 解析失败兜底为纯文本填正文」→ T5 `_parse_generated` fallback。
   - §2「spec 补 xhs_ai_service」→ T5 Step 5。
   - §7 P3 验收「选主题后工具条符号切换 / AI 生成填入 / 润色 / 未配置跳设置」→ T3 + T8。
2. **Placeholder 扫描**：每个代码步骤均给出完整代码 / 精确行号 / 期望输出，无 TODO/TBD。
3. **类型一致性**：`generateNote` 返回 `{title,body,topics}` 与 `applyTemplate({title,body,topics})` 入参一致（T8 直接复用）；`OrderedStyle` = `XhsTheme["ordered"]`；`themeToolbar` 项形状 `{key,label,symbol}` 不变（只多一项）；`_wrapLLMError` 返回 `never` 与 mining 同模式。

## P4 衔接说明（不在本计划）

- 有序列表插入是 soft helper（按正文已有序号计数，跨多个列表会连续编号）；若需「按列表块重新计数」属 P4 打磨。
- AI prompt 可配置（`AppConfig.xhs_generate_prompt`/`xhs_polish_prompt` + 设置卡 + `GET/PATCH /api/xhs/ai_prompts`）是 P4（§1 P4），本计划用内置常量。

---

## Execution Handoff

计划已存 `docs/superpowers/plans/2026-06-16-xiaohongshu-editor-p3.md`。沿用 P1/P2 既定方式：**子代理逐任务 + 两阶段评审（spec 合规 → 代码质量）**，全部任务后跨层终审，再交浏览器验收，验收 OK 才 push + PR。
