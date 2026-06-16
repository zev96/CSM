# 小红书图文笔记编辑器 · P1 文字素材面板 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 P0 留的 9 面板骨架里的 6 个文字面板（模版 / 表情 / 标题 / 文案 / 话题 / 装饰）与排版主题快捷插入做成真功能——全部由打包 JSON 驱动、纯前端零后端，点一下即「插入正文光标处 / 填标题 / 加话题 / 载入模板 / 应用主题」。

**Architecture:** 新增 `frontend/src/data/xhs/` 起步素材（7 个 JSON）+ 一个带类型的 `assets.ts` 加载层。`useXhs` store 扩两个 action（`applyTemplate` / `applyTheme`）与两个 getter（`activeTheme` / `themeToolbar`）——主题/模板写入复用 P0 已有的 `theme_id`/`title`/`body`/`topics` 持久化路径，**后端一行不改**。前端新增一个共享的分类标签条 `CategoryTabs.vue` + 7 个面板组件（`components/xhs/panels/`），改造 `PanelRail.vue` 用 `<component :is>` 派发到真实面板、改造 `NoteEditor.vue` 工具条为主题快捷符号 + 表情快捷入口。

**Tech Stack:** 纯前端。Vue 3.5 `<script setup lang="ts">` + Pinia（options 风格）+ Tailwind 3 + vitest(jsdom) + @vue/test-utils。素材为静态 JSON（`resolveJsonModule` 已开）。

---

## 设计依据

本计划实现设计稿 [2026-06-16-xiaohongshu-editor-design.md](../specs/2026-06-16-xiaohongshu-editor-design.md) 的 **P1 阶段**（见该稿 §1「P1 — 文字素材面板」、§3.3「起步素材 JSON 结构」、§5「9 面板详细规格」、§6「表情与排版边界」）。

**P1 范围（in scope）**
- 6 个「点一下＝插入/应用」的文字面板，全部 JSON 驱动、纯前端零后端：
  - **模版**：分类笔记模板，点击载入 title+body+topics（编辑器非空时弹确认覆盖）
  - **表情**：三段式 —— 常用分组（色系/题材）+ 全量 Unicode 分类 + 小红书代码组；点击在正文光标处插入
  - **标题**：爆款标题公式（带 `xx` 占位），点击填入标题（替换）
  - **文案**：文案片段库（互动/简介/结尾），点击光标处插入
  - **话题**：分类 #话题清单，点击加 chip（store 已实现去重、去前导 #）
  - **装饰**：分割线 + 项目符号，点击光标处插入
- **排版主题快捷插入**：主题面板「应用」= 设定当前激活主题；编辑器工具条出现这套主题的小标题/无序/分割线一键插入符号 + 表情快捷入口。P1 先放 3 套起步主题（P3 扩到 6–8 套色系）。

**P1 明确不做**（留给后续阶段）
- 图片上传 / 管理（P2）；预览显示真实图（P2）。
- AI 生成 / 润色（P3）；排版主题扩到 6–8 套色系（P3）。
- 自定义素材「存为我的模版 / 自定义文案 / 自定义话题分组」（P4）。
- 有序列表样式（`ordered` 字段）的工具条按钮：P1 工具条只做小标题 / 无序 / 分割线三个单符号快捷；`ordered`（emoji|circle|superscript 编号样式）保留在数据与类型里供 P3 接，不在 P1 出 UI。
- 预览里把 `[害羞R]` 类代码渲染成占位 chip（§6）：P1 中代码以纯文本插入、预览也按纯文本显示（这正是复制到小红书 App 的内容）；chip 化属 §1 P4「打磨」。
- 后端 / sidecar / pytest / 打包 spec：**P1 全程不动后端**（主题与模板落盘走 P0 已有的 `PATCH /api/xhs/drafts/{id}`，`theme_id`/`title`/`body`/`topics` 列与字段 P0 已就绪）。

**P1 验收标准**（设计稿 §7 P1 行）
> 每个面板点击都能正确插入/应用；模版载入弹确认；话题去重；正文光标插入位置正确。
> 追加：应用主题后工具条出现该主题符号、点击插入到光标处；表情代码插入为文字代码；`npx vitest run` 全绿、`npx vue-tsc -b` 零错、`npm run build` 通过。

---

## 前置：测试运行环境（执行者必读）

**P1 是纯前端任务，不碰后端**，所以不需要 P0 那套 `PYTHONPATH` 覆盖。所有命令在 `frontend/` 目录下执行：

- 单测（跑单个文件）：`npx vitest run <spec 路径>`，例如 `npx vitest run src/data/xhs/__tests__/assets.spec.ts`
- 全量单测：`npx vitest run`
- 类型检查：`npx vue-tsc -b`
- 完整构建门禁：`npm run build`（= `vue-tsc -b && vite build`）

> ⚠ 已知坑（项目记忆）：直接跑 `npx vue-tsc -b` 可能 emit 出 `vite.config.js` / `*.d.ts` 等构建产物并触发 vite 重启。类型检查后若 `git status` 出现这些被改/新增的产物，用 `git checkout -- frontend/vite.config.js` 还原，新增的 `.d.ts` 直接删。`npm run build` 的产物在 `frontend/dist/`（已 .gitignore，无需处理）。
>
> ⚠ 依赖：若本 worktree 是全新 checkout、`frontend/node_modules` 不存在，先在 `frontend/` 跑一次 `npm install`（不是 pnpm —— CI 只认 `package-lock.json`）。本计划不新增任何 npm 依赖（`@vue/test-utils`、`vitest`、`jsdom`、`pinia` 均已在 devDeps/deps），所以**不应**产生 `package-lock.json` 改动；若 `git status` 显示 lockfile 被改（本机 npm 版本与 CI 不一致所致），用 `git checkout -- frontend/package-lock.json` 还原。

每个任务最后一步是 commit，提交信息用中文（项目约定）。

---

## 文件结构（P1 落地清单）

**前端新增 —— 起步素材**
- `frontend/src/data/xhs/templates.json` —— 模板（分类笔记示例）
- `frontend/src/data/xhs/themes.json` —— 排版主题（emoji 结构符号套装）
- `frontend/src/data/xhs/emoji.json` —— 常用分组 + Unicode 分类 + 小红书代码
- `frontend/src/data/xhs/titles.json` —— 爆款标题公式（分类）
- `frontend/src/data/xhs/copy.json` —— 文案片段（分组）
- `frontend/src/data/xhs/topics.json` —— #话题（分组）
- `frontend/src/data/xhs/decorations.json` —— 分割线 / 项目符号
- `frontend/src/data/xhs/assets.ts` —— 带类型的加载层（import 上面 7 个 JSON，导出类型化常量 + `findTheme`）
- `frontend/src/data/xhs/__tests__/assets.spec.ts` —— 素材完整性测试

**前端新增 —— 组件**
- `frontend/src/components/xhs/panels/CategoryTabs.vue` —— 共享分类标签条
- `frontend/src/components/xhs/panels/TemplatePanel.vue`
- `frontend/src/components/xhs/panels/TitlePanel.vue`
- `frontend/src/components/xhs/panels/CopyPanel.vue`
- `frontend/src/components/xhs/panels/TopicPanel.vue`
- `frontend/src/components/xhs/panels/DecorationPanel.vue`
- `frontend/src/components/xhs/panels/EmojiPanel.vue`
- `frontend/src/components/xhs/panels/ThemePanel.vue`
- 各组件对应 `__tests__/*.spec.ts`

**前端改动**
- `frontend/src/stores/xhs.ts` —— 加 `applyTemplate` / `applyTheme` action + `activeTheme` / `themeToolbar` getter + import assets 的 `THEMES`/`findTheme`
- `frontend/src/stores/__tests__/xhs.spec.ts` —— 追加 P1 store 测试
- `frontend/src/components/xhs/NoteEditor.vue` —— 工具条改为主题快捷符号 + 表情快捷入口
- `frontend/src/components/xhs/__tests__/NoteEditor.spec.ts` —— 新建（工具条行为）
- `frontend/src/components/xhs/PanelRail.vue` —— 内容区用 `<component :is>` 派发到 7 个真实面板（image/ai 仍占位）

**后端**：不动。

---

## Task 1: 起步素材 JSON + 类型化加载层 + 完整性测试

**Files:**
- Create: `frontend/src/data/xhs/templates.json`
- Create: `frontend/src/data/xhs/themes.json`
- Create: `frontend/src/data/xhs/emoji.json`
- Create: `frontend/src/data/xhs/titles.json`
- Create: `frontend/src/data/xhs/copy.json`
- Create: `frontend/src/data/xhs/topics.json`
- Create: `frontend/src/data/xhs/decorations.json`
- Create: `frontend/src/data/xhs/assets.ts`
- Test: `frontend/src/data/xhs/__tests__/assets.spec.ts`

素材结构对齐设计稿 §3.3。`assets.ts` 用 `as` 把 `resolveJsonModule` 推断的宽类型收成业务接口，给组件一个唯一、类型安全的导入口。下面的 JSON 是本计划交付的**完整可用起步库**（质量优先于数量，见 §8）；上线后可按相同结构继续补充。

- [ ] **Step 1: 写失败测试（素材完整性）**

Create `frontend/src/data/xhs/__tests__/assets.spec.ts`：

```typescript
import { describe, it, expect } from "vitest";
import {
  TEMPLATES, TEMPLATE_CATEGORIES, THEMES, EMOJI,
  TITLE_CATEGORIES, COPY_GROUPS, TOPIC_GROUPS, DECORATION_GROUPS,
  findTheme,
} from "@/data/xhs/assets";

describe("xhs 起步素材完整性", () => {
  it("模板：非空、id 唯一、字段齐全", () => {
    expect(TEMPLATES.length).toBeGreaterThan(0);
    const ids = TEMPLATES.map((t) => t.id);
    expect(new Set(ids).size).toBe(ids.length);
    for (const t of TEMPLATES) {
      expect(t.category).toBeTruthy();
      expect(t.name).toBeTruthy();
      expect(t.title).toBeTruthy();
      expect(typeof t.body).toBe("string");
      expect(Array.isArray(t.topics)).toBe(true);
    }
  });

  it("模板分类列表由模板去重得到、非空、无重复", () => {
    expect(TEMPLATE_CATEGORIES.length).toBeGreaterThan(0);
    expect(new Set(TEMPLATE_CATEGORIES).size).toBe(TEMPLATE_CATEGORIES.length);
    for (const c of TEMPLATE_CATEGORIES) {
      expect(TEMPLATES.some((t) => t.category === c)).toBe(true);
    }
  });

  it("主题：非空、id 唯一、ordered 合法、符号齐全、findTheme 命中", () => {
    expect(THEMES.length).toBeGreaterThan(0);
    const ids = THEMES.map((t) => t.id);
    expect(new Set(ids).size).toBe(ids.length);
    for (const t of THEMES) {
      expect(["emoji", "circle", "superscript"]).toContain(t.ordered);
      expect(t.heading).toBeTruthy();
      expect(t.bullet).toBeTruthy();
      expect(t.divider).toBeTruthy();
    }
    expect(findTheme(THEMES[0].id)?.id).toBe(THEMES[0].id);
    expect(findTheme(null)).toBeNull();
    expect(findTheme("不存在的id")).toBeNull();
  });

  it("表情：三段都非空，每个 emoji 分组有内容，代码以 [ 开头", () => {
    expect(EMOJI.curatedGroups.length).toBeGreaterThan(0);
    expect(EMOJI.unicodeGroups.length).toBeGreaterThan(0);
    expect(EMOJI.xhsCodes.length).toBeGreaterThan(0);
    for (const g of [...EMOJI.curatedGroups, ...EMOJI.unicodeGroups]) {
      expect(g.key).toBeTruthy();
      expect(g.name).toBeTruthy();
      expect(g.emojis.length).toBeGreaterThan(0);
    }
    for (const c of EMOJI.xhsCodes) {
      expect(c.code.startsWith("[")).toBe(true);
      expect(c.label).toBeTruthy();
    }
  });

  it("标题/文案/话题/装饰：分组非空且每组有条目", () => {
    expect(TITLE_CATEGORIES.length).toBeGreaterThan(0);
    expect(COPY_GROUPS.length).toBeGreaterThan(0);
    expect(TOPIC_GROUPS.length).toBeGreaterThan(0);
    expect(DECORATION_GROUPS.length).toBeGreaterThan(0);
    for (const c of TITLE_CATEGORIES) expect(c.items.length).toBeGreaterThan(0);
    for (const g of COPY_GROUPS) expect(g.items.length).toBeGreaterThan(0);
    for (const g of TOPIC_GROUPS) expect(g.tags.length).toBeGreaterThan(0);
    for (const g of DECORATION_GROUPS) expect(g.items.length).toBeGreaterThan(0);
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `npx vitest run src/data/xhs/__tests__/assets.spec.ts`
Expected: FAIL —— 无法解析 `@/data/xhs/assets`（文件不存在）。

- [ ] **Step 3: 写 7 个 JSON 素材文件**

Create `frontend/src/data/xhs/templates.json`：

```json
[
  { "id": "tpl_zhishi_kaozheng", "category": "知识技能", "name": "考证攻略",
    "title": "各类证书报考时间合集｜建议收藏✨",
    "body": "今天帮大家整理了下半年的考证时间线📅\n\n💛 教师资格证\n🔸 笔试报名：9月初\n🔸 笔试时间：10月底\n\n💛 计算机二级\n🔸 报名：6月 / 12月\n\n⚠️ 具体以官网为准，记得提前备考～\n\n你还想了解哪个证书？评论区告诉我👇",
    "topics": ["考证", "大学生", "干货分享", "自我提升"] },
  { "id": "tpl_zhishi_zilv", "category": "知识技能", "name": "自律打卡",
    "title": "21天自律打卡计划｜亲测有效",
    "body": "坚持不下去？试试这个方法🌟\n\n☀️ 早起：6:30 起床，先喝一杯水\n📖 学习：番茄钟 25min×4\n🏃 运动：每天 30 分钟\n🌙 复盘：睡前写 3 件小事\n\n关键不是完美，是别断更～\n打卡第几天了？扣个数字💪",
    "topics": ["自律", "自我提升", "学习日常", "打卡"] },
  { "id": "tpl_zhishi_tools", "category": "知识技能", "name": "效率工具",
    "title": "学生党必备的免费效率工具📌",
    "body": "挖到宝了！这几个工具好用到哭😭\n\n🔸 笔记：Obsidian / 飞书\n🔸 待办：滴答清单\n🔸 专注：Forest\n🔸 录屏：OBS\n\n全都免费，照着装就行～\n你还在用什么神器？分享一下👇",
    "topics": ["效率工具", "干货分享", "大学生", "学习日常"] },
  { "id": "tpl_meizhuang_kongping", "category": "美妆护肤", "name": "空瓶记录",
    "title": "上半年空瓶记录｜无限回购清单",
    "body": "用空才有发言权！这几个我会闭眼回购✨\n\n💛 洁面：氨基酸温和不紧绷\n💛 精华：熬夜党救星\n💛 防晒：油皮不闷痘\n\n踩雷的下次再扒～\n你有什么空瓶好物？评论区交流💬",
    "topics": ["空瓶", "好物分享", "护肤", "回购清单"] },
  { "id": "tpl_meizhuang_xinshou", "category": "美妆护肤", "name": "新手化妆",
    "title": "新手化妆必备清单｜照着买不踩雷",
    "body": "从0开始学化妆，先买这些就够了🌷\n\n🔸 底妆：隔离 + 粉底液\n🔸 眉毛：眉笔（新手选灰棕）\n🔸 眼妆：大地色眼影盘\n🔸 唇部：豆沙色口红\n\n少即是多，先练熟基础～\n需要详细教程吗？想看扣1",
    "topics": ["新手化妆", "美妆", "化妆教程", "学生党"] },
  { "id": "tpl_meizhuang_huning", "category": "美妆护肤", "name": "护肤步骤",
    "title": "正确护肤步骤｜别再乱涂啦",
    "body": "顺序错了等于白涂😵\n\n1️⃣ 洁面\n2️⃣ 爽肤水\n3️⃣ 精华\n4️⃣ 乳液 / 面霜\n5️⃣ 防晒（早上必做）\n\n记住：质地从稀到稠～\n你护肤几步走？",
    "topics": ["护肤", "护肤步骤", "干货分享", "变美"] },
  { "id": "tpl_chuanda_tongqin", "category": "穿搭", "name": "通勤穿搭",
    "title": "通勤穿搭公式｜轻松get同事夸",
    "body": "上班再也不用纠结穿什么👔\n\n💙 衬衫 + 西装裤 + 乐福鞋\n💙 针织衫 + 半身裙 + 平底鞋\n💙 基础T + 西装外套 + 直筒裤\n\n配色别超过三种最高级～\n你公司穿搭自由吗？",
    "topics": ["通勤穿搭", "穿搭分享", "职场", "ootd"] },
  { "id": "tpl_chuanda_xianshou", "category": "穿搭", "name": "显瘦技巧",
    "title": "小个子显高显瘦的5个穿搭技巧",
    "body": "155也能穿出170的气场🌟\n\n🔸 高腰线！高腰线！高腰线！\n🔸 上短下长 / 同色系\n🔸 V领拉长脖颈\n🔸 尖头鞋显腿长\n🔸 少穿横条纹\n\n学会立省10cm～\n还想看什么身材的穿搭？",
    "topics": ["显瘦穿搭", "小个子穿搭", "穿搭技巧", "穿搭分享"] },
  { "id": "tpl_chuanda_peise", "category": "穿搭", "name": "配色公式",
    "title": "穿搭配色公式｜照着穿绝不出错",
    "body": "不会配色？记这几组就够了🎨\n\n💛 米白 + 燕麦 = 高级温柔\n💙 牛仔蓝 + 白 = 清爽\n🧡 焦糖 + 棕 = 秋日氛围\n🖤 黑白灰 = 永不踩雷\n\n收藏起来照着搭～\n你最爱哪一组？",
    "topics": ["穿搭配色", "穿搭技巧", "ootd", "穿搭分享"] },
  { "id": "tpl_meishi_tandian", "category": "美食探店", "name": "探店笔记",
    "title": "藏在巷子里的宝藏小店｜人均30吃到撑",
    "body": "被这家店圈粉了！😍\n\n📍 位置：XX路XX巷\n🍜 必点：招牌面 / 卤味拼盘\n💰 人均：30+\n⏰ 建议：避开饭点不排队\n\n本地人都懂的老味道～\n你家附近有什么宝藏店？",
    "topics": ["美食探店", "探店", "美食分享", "本地生活"] },
  { "id": "tpl_meishi_jianzhi", "category": "美食探店", "name": "减脂餐",
    "title": "一周减脂餐食谱｜好吃不挨饿",
    "body": "减脂也能吃得很满足🥗\n\n🔸 早：鸡蛋 + 全麦 + 牛奶\n🔸 午：鸡胸 + 糙米 + 西兰花\n🔸 晚：清蒸鱼 + 蔬菜\n🔸 加餐：水果 / 无糖酸奶\n\n少油少盐，循序渐进～\n需要详细做法吗？扣1",
    "topics": ["减脂餐", "健康饮食", "食谱", "减肥"] },
  { "id": "tpl_meishi_hongbei", "category": "美食探店", "name": "周末烘焙",
    "title": "新手0失败烘焙｜厨房小白也能做",
    "body": "周末在家烤了一炉，太治愈了🍰\n\n🔸 第一次：先做饼干（最不易失败）\n🔸 工具：电子秤一定要有\n🔸 配方：严格按克数\n🔸 烤箱：提前预热\n\n按步骤来基本不翻车～\n想看哪款教程？评论区点单👇",
    "topics": ["烘焙", "烘焙食谱", "美食分享", "周末"] }
]
```

Create `frontend/src/data/xhs/themes.json`：

```json
[
  { "id": "warm_yellow", "name": "温暖黄", "heading": "💛", "bullet": "🔸", "ordered": "emoji", "divider": "✨━━━━━━━━✨" },
  { "id": "sky_blue", "name": "天空蓝", "heading": "💙", "bullet": "🔹", "ordered": "circle", "divider": "·｡✦ ──────── ✦｡·" },
  { "id": "energy_orange", "name": "元气橙", "heading": "🧡", "bullet": "🔶", "ordered": "emoji", "divider": "🍊─────────🍊" }
]
```

Create `frontend/src/data/xhs/emoji.json`：

```json
{
  "curatedGroups": [
    { "key": "warm", "name": "温暖黄", "emojis": ["💛", "🌟", "🔆", "🍯", "🌻", "⭐", "✨", "🟡", "🌼", "🥯"] },
    { "key": "food", "name": "美食探店", "emojis": ["🍰", "☕", "🍜", "🍔", "🍣", "🍮", "🧋", "🍕", "🍦", "🥗"] },
    { "key": "travel", "name": "出行户外", "emojis": ["✈️", "🏖️", "⛰️", "🗺️", "🎒", "📷", "🚗", "🏝️", "🧳", "🌅"] },
    { "key": "outfit", "name": "穿搭好物", "emojis": ["👗", "👜", "👠", "🧥", "👚", "👢", "🕶️", "💄", "🎀", "👒"] }
  ],
  "unicodeGroups": [
    { "key": "smileys", "name": "笑脸", "emojis": ["😀", "😄", "😁", "😆", "😊", "🙂", "😉", "😍", "🥰", "😘", "😋", "😎", "🤩", "🥳", "😏", "😌", "😅", "🤗", "🤭", "😇", "🙃", "😜"] },
    { "key": "gestures", "name": "手势", "emojis": ["👍", "👎", "👌", "✌️", "🤞", "🙏", "👏", "🙌", "💪", "🤝", "👋", "✋", "🤙", "👇", "👉", "👆", "☝️", "✊", "🤟", "🫶"] },
    { "key": "hearts", "name": "爱心", "emojis": ["❤️", "🧡", "💛", "💚", "💙", "💜", "🤍", "🖤", "🤎", "💖", "💗", "💓", "💞", "💕", "❣️", "💟"] },
    { "key": "animals", "name": "动物", "emojis": ["🐶", "🐱", "🐭", "🐹", "🐰", "🦊", "🐻", "🐼", "🐨", "🐯", "🦁", "🐮", "🐷", "🐸", "🐵", "🐔", "🐧", "🐦", "🦄", "🐝"] },
    { "key": "plants", "name": "花草", "emojis": ["🌸", "🌹", "🌺", "🌻", "🌷", "🌼", "🌿", "🍀", "🌱", "🌲", "🌳", "🌴", "🌵", "🍁", "🍂", "🍃", "💐", "🪴", "🌾", "🍄"] },
    { "key": "weather", "name": "天气星空", "emojis": ["☀️", "🌤️", "⛅", "🌥️", "☁️", "🌦️", "🌧️", "⛈️", "❄️", "⛄", "🌈", "🌙", "⭐", "🌟", "✨", "⚡", "🔥", "💧", "🌊", "💫"] },
    { "key": "symbols", "name": "符号标记", "emojis": ["✅", "❌", "⭕", "❗", "❓", "💯", "🔔", "🎁", "🎀", "⚠️", "♻️", "🆕", "📌", "📍", "🎉", "🎊", "💡", "🔑", "🏆", "🎯"] }
  ],
  "xhsCodes": [
    { "code": "[害羞R]", "label": "害羞" },
    { "code": "[偷笑R]", "label": "偷笑" },
    { "code": "[飙泪R]", "label": "飙泪" },
    { "code": "[赞R]", "label": "赞" },
    { "code": "[笑哭R]", "label": "笑哭" },
    { "code": "[再见R]", "label": "再见" },
    { "code": "[惊恐R]", "label": "惊恐" },
    { "code": "[嘘声R]", "label": "嘘声" },
    { "code": "[可怜R]", "label": "可怜" },
    { "code": "[doge]", "label": "doge" }
  ]
}
```

Create `frontend/src/data/xhs/titles.json`：

```json
{
  "categories": [
    { "key": "hot", "name": "爆款通用", "items": [
      "99%的人都不知道的xx，看完直接收藏！",
      "保姆级xx教程，小白也能一次学会",
      "我宣布，xx就是yyds！",
      "后悔没早点知道的xx，相见恨晚",
      "关于xx，我有话要说……",
      "xx的正确打开方式，第3点绝了",
      "刷到就是赚到！xx合集来啦",
      "新手必看｜xx避坑指南"
    ] },
    { "key": "beauty", "name": "好物美妆", "items": [
      "闭眼入！xx空瓶N次的回购清单",
      "学生党平价xx，便宜又好用",
      "油皮亲测｜xx夏天不脱妆",
      "xx测评｜到底值不值得买？",
      "新手必备的xx，照着买不踩雷",
      "黄黑皮显白xx，谁用谁知道",
      "xx种草｜性价比天花板",
      "敏感肌也能用的xx，温和不刺激"
    ] },
    { "key": "travel", "name": "旅行出行", "items": [
      "xx旅行攻略｜3天2夜怎么玩",
      "小众宝藏xx，人少景美还出片",
      "xx自由行｜人均xxx搞定",
      "周末去哪儿？xx一日游路线",
      "去了N次xx总结的避雷指南",
      "xx必打卡｜不去后悔系列",
      "懒人版xx攻略，照着走就行",
      "xx拍照机位｜随手出大片"
    ] },
    { "key": "guide", "name": "干货教程", "items": [
      "xx从入门到精通，一篇讲清楚",
      "手把手教你xx，附详细步骤",
      "xx超全整理｜建议收藏反复看",
      "0基础学xx，这些坑别再踩",
      "xx效率翻倍的N个技巧",
      "干货｜xx的5个实用方法",
      "整理了xx的全流程，拿走不谢",
      "xx速成指南｜一周见效"
    ] }
  ]
}
```

Create `frontend/src/data/xhs/copy.json`：

```json
{
  "groups": [
    { "key": "interact", "name": "互动文案", "items": [
      "喜欢的话就点个赞吧，比心❤️",
      "觉得有用记得收藏＋关注哦😋",
      "评论区聊聊你的看法～",
      "double tap 如果你也这么觉得👆",
      "求关注求点赞，你们的支持是我更新的动力💪",
      "有问题评论区问我，看到都会回～"
    ] },
    { "key": "intro", "name": "个人简介", "items": [
      "一个爱分享生活的小红薯🍠",
      "记录普通女孩的变美日常✨",
      "和我一起好好生活📖",
      "分享｜好物 · 穿搭 · 日常",
      "用心生活，认真分享🌷",
      "这里有你想要的全部干货📌"
    ] },
    { "key": "ending", "name": "结尾引导", "items": [
      "以上就是今天的分享啦，下期见👋",
      "希望对你有帮助，记得收藏哦～",
      "码字不易，点赞收藏走一波吧🙏",
      "更多内容关注我，持续更新中✨",
      "你学会了吗？评论区告诉我～",
      "我们下篇笔记见，拜拜👋"
    ] }
  ]
}
```

Create `frontend/src/data/xhs/topics.json`：

```json
{
  "groups": [
    { "key": "hot", "name": "热门", "tags": ["每日穿搭", "好物分享", "干货分享", "生活记录", "学习日常", "自我提升", "周末去哪儿", "治愈系", "沉浸式", "vlog日常"] },
    { "key": "outfit", "name": "穿搭", "tags": ["穿搭分享", "ootd", "显瘦穿搭", "通勤穿搭", "小个子穿搭", "学生党穿搭", "平价穿搭", "秋冬穿搭", "穿搭配色", "穿搭技巧"] },
    { "key": "food", "name": "美食", "tags": ["美食探店", "美食分享", "家常菜", "减脂餐", "烘焙", "咖啡", "探店", "食谱", "下午茶", "早餐"] },
    { "key": "travel", "name": "旅行", "tags": ["旅行", "旅游攻略", "周边游", "城市漫步", "民宿", "露营", "自驾游", "小众景点", "旅行vlog", "打卡"] }
  ]
}
```

Create `frontend/src/data/xhs/decorations.json`：

```json
{
  "groups": [
    { "key": "divider", "name": "分割线", "items": ["✨━━━━━━✨", "·｡✦ ──── ✦｡·", "▶▷▶▷▶▷", "· · · · · ·", "❀❀❀❀❀❀", "─── ⋆⋅☆⋅⋆ ───", "🍊─────🍊", "✼ • • • ✼"] },
    { "key": "bullet", "name": "项目符号", "items": ["🔸 ", "🔹 ", "🔶 ", "▪️ ", "◦ ", "✅ ", "👉 ", "💛 "] }
  ]
}
```

- [ ] **Step 4: 写类型化加载层 `assets.ts`**

Create `frontend/src/data/xhs/assets.ts`：

```typescript
/**
 * 小红书起步素材的类型化加载层（设计稿 §3.3）。
 *
 * resolveJsonModule 会把 JSON 推断成很宽的字面量类型，这里用 `as` 收成业务
 * 接口，让所有面板组件/store 只从这一个文件导入、拿到稳定的类型。素材内容
 * 的合法性由 __tests__/assets.spec.ts 校验。
 */
import templatesRaw from "./templates.json";
import themesRaw from "./themes.json";
import emojiRaw from "./emoji.json";
import titlesRaw from "./titles.json";
import copyRaw from "./copy.json";
import topicsRaw from "./topics.json";
import decorationsRaw from "./decorations.json";

export interface XhsTemplate {
  id: string;
  category: string;
  name: string;
  title: string;
  body: string;
  topics: string[];
}

/** 排版主题：用 emoji 当结构符号。ordered 是有序列表样式，P1 未用、留给 P3。 */
export interface XhsTheme {
  id: string;
  name: string;
  heading: string;
  bullet: string;
  ordered: "emoji" | "circle" | "superscript";
  divider: string;
}

export interface EmojiGroup {
  key: string;
  name: string;
  emojis: string[];
}
export interface XhsCode {
  code: string;
  label: string;
}
export interface EmojiLibrary {
  curatedGroups: EmojiGroup[];
  unicodeGroups: EmojiGroup[];
  xhsCodes: XhsCode[];
}

/** 标题分类 / 文案分组 / 装饰分组：统一「key + name + items(字符串数组)」。 */
export interface ItemGroup {
  key: string;
  name: string;
  items: string[];
}
/** 话题分组：tags 而非 items（元素不含前导 #）。 */
export interface TopicGroup {
  key: string;
  name: string;
  tags: string[];
}

export const TEMPLATES = templatesRaw as XhsTemplate[];
// themes.json 的 ordered 被推断成 string，与联合类型不直接兼容，经 unknown 收窄；
// 合法性（只能是三种值之一）由 assets.spec.ts 保证。
export const THEMES = themesRaw as unknown as XhsTheme[];
export const EMOJI = emojiRaw as EmojiLibrary;
export const TITLE_CATEGORIES = (titlesRaw as { categories: ItemGroup[] }).categories;
export const COPY_GROUPS = (copyRaw as { groups: ItemGroup[] }).groups;
export const TOPIC_GROUPS = (topicsRaw as { groups: TopicGroup[] }).groups;
export const DECORATION_GROUPS = (decorationsRaw as { groups: ItemGroup[] }).groups;

/** 模板分类（按出现顺序去重）。 */
export const TEMPLATE_CATEGORIES: string[] = [...new Set(TEMPLATES.map((t) => t.category))];

/** 按 id 找主题；id 为 null / 找不到时返回 null。 */
export function findTheme(id: string | null): XhsTheme | null {
  if (!id) return null;
  return THEMES.find((t) => t.id === id) ?? null;
}
```

- [ ] **Step 5: 跑测试确认通过**

Run: `npx vitest run src/data/xhs/__tests__/assets.spec.ts`
Expected: PASS（5 条素材完整性测试全绿）。

- [ ] **Step 6: Commit**

```powershell
git add frontend/src/data/xhs/
git commit -m "feat(xhs): 起步素材 JSON + 类型化加载层 (P1 T1)"
```

---

## Task 2: store 扩展——applyTemplate / applyTheme / activeTheme / themeToolbar

**Files:**
- Modify: `frontend/src/stores/xhs.ts`
- Test: `frontend/src/stores/__tests__/xhs.spec.ts`（追加 P1 测试）

主题与模板都复用 P0 既有持久化（`scheduleSave` → PATCH，`theme_id`/`title`/`body`/`topics` 已在 `_payload()` 里）。新增：`applyTemplate` 整篇覆盖、`applyTheme` 设激活主题、`activeTheme` getter 解析主题对象、`themeToolbar` getter 把激活主题映射成工具条按钮（小标题/无序/分割线）。

- [ ] **Step 1: 追加失败测试**

在 `frontend/src/stores/__tests__/xhs.spec.ts` 顶部 `import { useXhs, _resetXhsModuleState } from "@/stores/xhs";` **之后**追加一行导入：

```typescript
import { THEMES } from "@/data/xhs/assets";
```

在文件**末尾**追加：

```typescript
describe("useXhs — 模板载入", () => {
  it("applyTemplate 覆盖标题/正文/话题并去抖保存", async () => {
    postMock.mockResolvedValue({ data: { id: "d1" } });
    patchMock.mockResolvedValue({ data: {} });
    const x = useXhs();
    x.$patch({ title: "旧", body: "旧正文", topics: ["旧"] });
    x.applyTemplate({ title: "新标题", body: "新正文\n第二行", topics: ["a", "b"] });
    expect(x.title).toBe("新标题");
    expect(x.body).toBe("新正文\n第二行");
    expect(x.topics).toEqual(["a", "b"]);
    // 触发了去抖保存：800ms 后建草稿
    await vi.advanceTimersByTimeAsync(800);
    expect(postMock).toHaveBeenCalledTimes(1);
  });
});

describe("useXhs — 排版主题", () => {
  it("默认无激活主题，activeTheme=null、themeToolbar 为空", () => {
    const x = useXhs();
    expect(x.activeTheme).toBeNull();
    expect(x.themeToolbar).toEqual([]);
  });

  it("applyTheme 设激活主题，activeTheme 解析出主题对象", () => {
    const x = useXhs();
    const t = THEMES[0];
    x.applyTheme(t.id);
    expect(x.themeId).toBe(t.id);
    expect(x.activeTheme?.id).toBe(t.id);
  });

  it("themeToolbar 由激活主题映射出 小标题/无序/分割线 三个按钮", () => {
    const x = useXhs();
    const t = THEMES[0];
    x.applyTheme(t.id);
    const tb = x.themeToolbar;
    expect(tb.map((b) => b.key)).toEqual(["heading", "bullet", "divider"]);
    expect(tb.find((b) => b.key === "heading")?.symbol).toBe(t.heading);
    expect(tb.find((b) => b.key === "bullet")?.symbol).toBe(t.bullet);
    expect(tb.find((b) => b.key === "divider")?.symbol).toBe(t.divider);
  });

  it("applyTheme 触发去抖保存", async () => {
    postMock.mockResolvedValue({ data: { id: "d1" } });
    patchMock.mockResolvedValue({ data: {} });
    const x = useXhs();
    x.$patch({ title: "有内容" }); // 非空才会真的建草稿
    x.applyTheme(THEMES[0].id);
    await vi.advanceTimersByTimeAsync(800);
    expect(postMock).toHaveBeenCalledTimes(1);
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `npx vitest run src/stores/__tests__/xhs.spec.ts`
Expected: FAIL —— `x.applyTemplate is not a function` / `activeTheme` 为 undefined。

- [ ] **Step 3: 实现 store 扩展**

在 `frontend/src/stores/xhs.ts` 顶部 import 区，`import { buildFullText, countChars } from "@/utils/xhsText";` **之后**追加（**只 import `findTheme` 与类型**——store 主体不直接用 `THEMES`，多 import 会被 `noUnusedLocals` 判错）：

```typescript
import { findTheme, type XhsTheme } from "@/data/xhs/assets";
```

在 `getters: { ... }` 块里，`isEmpty` 那一行**之后**追加两个 getter：

```typescript
    isEmpty: (s): boolean => s.title.trim() === "" && s.body.trim() === "",
    /** 当前激活的排版主题对象（无则 null）。 */
    activeTheme: (s): XhsTheme | null => findTheme(s.themeId),
    /** 工具条快捷符号按钮：激活主题 → 小标题/无序/分割线（无主题时空）。
     *  用 function 形式以便通过 this 访问 activeTheme（设计稿 §1 P1 工具条）。 */
    themeToolbar(): { key: string; label: string; symbol: string }[] {
      const t = this.activeTheme;
      if (!t) return [];
      return [
        { key: "heading", label: "小标题", symbol: t.heading },
        { key: "bullet", label: "无序", symbol: t.bullet },
        { key: "divider", label: "分割线", symbol: t.divider },
      ];
    },
```

在 `actions: { ... }` 块里，`newDraft()` 之后（或任意合适位置）追加两个 action：

```typescript
    /** 模板载入：整篇覆盖标题/正文/话题（是否弹确认由调用方面板决定）。 */
    applyTemplate(tpl: { title: string; body: string; topics: string[] }): void {
      this.title = tpl.title;
      this.body = tpl.body;
      this.topics = [...tpl.topics];
      this.scheduleSave();
    },
    /** 应用排版主题：设激活主题 id，工具条随即出现该主题快捷符号。 */
    applyTheme(themeId: string): void {
      this.themeId = themeId;
      this.scheduleSave();
    },
```

- [ ] **Step 4: 跑测试确认通过**

Run: `npx vitest run src/stores/__tests__/xhs.spec.ts`
Expected: PASS（P0 原有 + P1 新增的模板/主题测试全绿）。

- [ ] **Step 5: Commit**

```powershell
git add frontend/src/stores/xhs.ts frontend/src/stores/__tests__/xhs.spec.ts
git commit -m "feat(xhs): store 加 applyTemplate/applyTheme + activeTheme/themeToolbar (P1 T2)"
```

---

## Task 3: 共享分类标签条 CategoryTabs.vue

**Files:**
- Create: `frontend/src/components/xhs/panels/CategoryTabs.vue`
- Test: `frontend/src/components/xhs/panels/__tests__/CategoryTabs.spec.ts`

受控展示组件（仿 `ui/Pill.vue`/`ui/Select.vue` 那种带测试的小 UI）：横向可滚动的分类胶囊，`v-model` 绑定当前 key，激活项橙色高亮。模版/标题/文案/话题/装饰/表情面板共用。

- [ ] **Step 1: 写失败测试**

Create `frontend/src/components/xhs/panels/__tests__/CategoryTabs.spec.ts`：

```typescript
import { describe, it, expect } from "vitest";
import { mount } from "@vue/test-utils";
import CategoryTabs from "@/components/xhs/panels/CategoryTabs.vue";

const tabs = [
  { key: "a", name: "甲" },
  { key: "b", name: "乙" },
];

describe("CategoryTabs", () => {
  it("渲染所有分类名", () => {
    const w = mount(CategoryTabs, { props: { tabs, modelValue: "a" } });
    expect(w.text()).toContain("甲");
    expect(w.text()).toContain("乙");
  });

  it("点击分类 emit update:modelValue 带该 key", async () => {
    const w = mount(CategoryTabs, { props: { tabs, modelValue: "a" } });
    await w.findAll("button")[1].trigger("click");
    expect(w.emitted("update:modelValue")?.[0]).toEqual(["b"]);
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `npx vitest run src/components/xhs/panels/__tests__/CategoryTabs.spec.ts`
Expected: FAIL —— 无法解析 `@/components/xhs/panels/CategoryTabs.vue`。

- [ ] **Step 3: 实现组件**

Create `frontend/src/components/xhs/panels/CategoryTabs.vue`：

```vue
<script setup lang="ts">
/**
 * 素材面板通用「分类标签条」（设计稿 §5 多面板共用）。
 * 受控组件：v-model 绑定当前分类 key；横向可滚动，激活项橙色高亮。
 */
defineProps<{ tabs: { key: string; name: string }[]; modelValue: string }>();
defineEmits<{ (e: "update:modelValue", key: string): void }>();
</script>

<template>
  <div
    class="flex"
    :style="{ gap: '6px', overflowX: 'auto', flexWrap: 'nowrap', flexShrink: 0, paddingBottom: '2px' }"
  >
    <button
      v-for="t in tabs"
      :key="t.key"
      type="button"
      :style="{
        flexShrink: 0,
        fontSize: '12px',
        padding: '5px 12px',
        borderRadius: '999px',
        cursor: 'pointer',
        whiteSpace: 'nowrap',
        border: '1px solid transparent',
        background: modelValue === t.key ? 'var(--primary)' : 'rgba(var(--ink-rgb),0.05)',
        color: modelValue === t.key ? '#fff' : 'var(--ink-2)',
      }"
      @click="$emit('update:modelValue', t.key)"
    >
      {{ t.name }}
    </button>
  </div>
</template>
```

- [ ] **Step 4: 跑测试确认通过**

Run: `npx vitest run src/components/xhs/panels/__tests__/CategoryTabs.spec.ts`
Expected: PASS。

- [ ] **Step 5: Commit**

```powershell
git add frontend/src/components/xhs/panels/CategoryTabs.vue frontend/src/components/xhs/panels/__tests__/CategoryTabs.spec.ts
git commit -m "feat(xhs): 共享分类标签条 CategoryTabs (P1 T3)"
```

---

## Task 4: 模版面板 TemplatePanel.vue

**Files:**
- Create: `frontend/src/components/xhs/panels/TemplatePanel.vue`
- Test: `frontend/src/components/xhs/panels/__tests__/TemplatePanel.spec.ts`

分类 tab + 模板卡。点击：编辑器为空直接 `applyTemplate`；非空先 `confirmDialog` 确认覆盖。

- [ ] **Step 1: 写失败测试**

Create `frontend/src/components/xhs/panels/__tests__/TemplatePanel.spec.ts`：

```typescript
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { mount, flushPromises } from "@vue/test-utils";

vi.mock("@/stores/sidecar", () => ({
  useSidecar: () => ({
    client: {
      get: vi.fn(),
      post: vi.fn().mockResolvedValue({ data: { id: "d1" } }),
      patch: vi.fn().mockResolvedValue({ data: {} }),
      delete: vi.fn(),
    },
    sseURL: (p: string) => p,
  }),
}));
vi.mock("@/composables/useConfirm", () => ({
  confirmDialog: vi.fn().mockResolvedValue(true),
}));

import TemplatePanel from "@/components/xhs/panels/TemplatePanel.vue";
import { useXhs, _resetXhsModuleState } from "@/stores/xhs";
import { confirmDialog } from "@/composables/useConfirm";

beforeEach(() => {
  setActivePinia(createPinia());
  _resetXhsModuleState();
  vi.mocked(confirmDialog).mockClear();
  vi.useFakeTimers();
});
afterEach(() => {
  vi.clearAllTimers();
  vi.useRealTimers();
});

describe("TemplatePanel", () => {
  it("编辑器为空时点击模板直接载入（不弹确认）", async () => {
    const store = useXhs();
    const w = mount(TemplatePanel);
    await w.find(".xhs-tpl-card").trigger("click");
    await flushPromises();
    expect(store.title.length).toBeGreaterThan(0);
    expect(confirmDialog).not.toHaveBeenCalled();
    w.unmount();
  });

  it("编辑器非空时先弹确认，确认后覆盖", async () => {
    const store = useXhs();
    store.$patch({ body: "已有内容" });
    const w = mount(TemplatePanel);
    await w.find(".xhs-tpl-card").trigger("click");
    await flushPromises();
    expect(confirmDialog).toHaveBeenCalledTimes(1);
    expect(store.body).not.toBe("已有内容");
    w.unmount();
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `npx vitest run src/components/xhs/panels/__tests__/TemplatePanel.spec.ts`
Expected: FAIL —— 无法解析 `@/components/xhs/panels/TemplatePanel.vue`。

- [ ] **Step 3: 实现组件**

Create `frontend/src/components/xhs/panels/TemplatePanel.vue`：

```vue
<script setup lang="ts">
/**
 * 模版面板（设计稿 §5「模版」）。分类 tab + 模板卡；点击载入 title/body/topics，
 * 编辑器非空时先弹确认覆盖。
 */
import { ref, computed } from "vue";
import CategoryTabs from "./CategoryTabs.vue";
import { TEMPLATES, TEMPLATE_CATEGORIES, type XhsTemplate } from "@/data/xhs/assets";
import { useXhs } from "@/stores/xhs";
import { confirmDialog } from "@/composables/useConfirm";

const xhs = useXhs();
const cat = ref(TEMPLATE_CATEGORIES[0] ?? "");
const tabs = TEMPLATE_CATEGORIES.map((c) => ({ key: c, name: c }));
const list = computed(() => TEMPLATES.filter((t) => t.category === cat.value));

async function pick(t: XhsTemplate) {
  if (!xhs.isEmpty) {
    const ok = await confirmDialog("载入模板会覆盖当前的标题 / 正文 / 话题，确定吗？", {
      title: "载入模板",
      okLabel: "载入",
      kind: "danger",
    });
    if (!ok) return;
  }
  xhs.applyTemplate({ title: t.title, body: t.body, topics: t.topics });
}
</script>

<template>
  <div class="flex h-full flex-col" :style="{ gap: '10px' }">
    <CategoryTabs v-model="cat" :tabs="tabs" />
    <div class="min-h-0 flex-1 overflow-y-auto flex flex-col" :style="{ gap: '10px' }">
      <button v-for="t in list" :key="t.id" type="button" class="xhs-tpl-card" @click="pick(t)">
        <div :style="{ fontSize: '13px', fontWeight: 600, color: 'var(--ink)', marginBottom: '4px' }">{{ t.name }}</div>
        <div
          :style="{
            fontSize: '12px', color: 'var(--ink)', marginBottom: '4px',
            display: '-webkit-box', WebkitLineClamp: 1, WebkitBoxOrient: 'vertical', overflow: 'hidden',
          }"
        >{{ t.title }}</div>
        <div
          :style="{
            fontSize: '11px', color: 'var(--ink-2)', whiteSpace: 'pre-wrap',
            display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden',
          }"
        >{{ t.body }}</div>
      </button>
    </div>
  </div>
</template>

<style scoped>
.xhs-tpl-card {
  text-align: left;
  border: 1px solid var(--line-2);
  border-radius: 12px;
  padding: 10px 12px;
  background: #fff;
  cursor: pointer;
  transition: border-color 0.15s, box-shadow 0.15s;
}
.xhs-tpl-card:hover {
  border-color: var(--primary);
  box-shadow: 0 4px 14px -8px rgba(var(--shadow-rgb), 0.3);
}
</style>
```

- [ ] **Step 4: 跑测试确认通过**

Run: `npx vitest run src/components/xhs/panels/__tests__/TemplatePanel.spec.ts`
Expected: PASS（空/非空两条路径绿）。

- [ ] **Step 5: Commit**

```powershell
git add frontend/src/components/xhs/panels/TemplatePanel.vue frontend/src/components/xhs/panels/__tests__/TemplatePanel.spec.ts
git commit -m "feat(xhs): 模版面板 TemplatePanel (P1 T4)"
```

---

## Task 5: 标题面板 TitlePanel.vue

**Files:**
- Create: `frontend/src/components/xhs/panels/TitlePanel.vue`
- Test: `frontend/src/components/xhs/panels/__tests__/TitlePanel.spec.ts`

分类 tab + 标题公式列表。点击 → `xhs.setTitle(item)`（替换标题，保留 `xx` 占位让用户改）。

- [ ] **Step 1: 写失败测试**

Create `frontend/src/components/xhs/panels/__tests__/TitlePanel.spec.ts`：

```typescript
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { mount } from "@vue/test-utils";

vi.mock("@/stores/sidecar", () => ({
  useSidecar: () => ({
    client: {
      get: vi.fn(),
      post: vi.fn().mockResolvedValue({ data: { id: "d1" } }),
      patch: vi.fn().mockResolvedValue({ data: {} }),
      delete: vi.fn(),
    },
    sseURL: (p: string) => p,
  }),
}));

import TitlePanel from "@/components/xhs/panels/TitlePanel.vue";
import { useXhs, _resetXhsModuleState } from "@/stores/xhs";

beforeEach(() => {
  setActivePinia(createPinia());
  _resetXhsModuleState();
  vi.useFakeTimers();
});
afterEach(() => {
  vi.clearAllTimers();
  vi.useRealTimers();
});

describe("TitlePanel", () => {
  it("点击标题条目填入标题（替换）", async () => {
    const store = useXhs();
    const w = mount(TitlePanel);
    const first = w.find(".xhs-row");
    await first.trigger("click");
    expect(store.title).toBe(first.text().trim());
    w.unmount();
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `npx vitest run src/components/xhs/panels/__tests__/TitlePanel.spec.ts`
Expected: FAIL —— 无法解析 `@/components/xhs/panels/TitlePanel.vue`。

- [ ] **Step 3: 实现组件**

Create `frontend/src/components/xhs/panels/TitlePanel.vue`：

```vue
<script setup lang="ts">
/** 标题面板（设计稿 §5「标题」）。分类 tab + 爆款标题公式；点击填入标题（替换）。 */
import { ref, computed } from "vue";
import CategoryTabs from "./CategoryTabs.vue";
import { TITLE_CATEGORIES } from "@/data/xhs/assets";
import { useXhs } from "@/stores/xhs";

const xhs = useXhs();
const cat = ref(TITLE_CATEGORIES[0]?.key ?? "");
const tabs = TITLE_CATEGORIES.map((c) => ({ key: c.key, name: c.name }));
const items = computed(() => TITLE_CATEGORIES.find((c) => c.key === cat.value)?.items ?? []);
</script>

<template>
  <div class="flex h-full flex-col" :style="{ gap: '10px' }">
    <CategoryTabs v-model="cat" :tabs="tabs" />
    <div :style="{ fontSize: '11px', color: 'var(--ink-2)', flexShrink: 0 }">
      点击填入标题，把 <b>xx</b> 换成你的关键词
    </div>
    <div class="min-h-0 flex-1 overflow-y-auto flex flex-col" :style="{ gap: '8px' }">
      <button v-for="(it, i) in items" :key="i" type="button" class="xhs-row" @click="xhs.setTitle(it)">
        {{ it }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.xhs-row {
  text-align: left;
  border: 1px solid var(--line-2);
  border-radius: 10px;
  padding: 8px 12px;
  background: #fff;
  color: var(--ink);
  font-size: 13px;
  cursor: pointer;
  transition: border-color 0.15s;
}
.xhs-row:hover {
  border-color: var(--primary);
}
</style>
```

- [ ] **Step 4: 跑测试确认通过**

Run: `npx vitest run src/components/xhs/panels/__tests__/TitlePanel.spec.ts`
Expected: PASS。

- [ ] **Step 5: Commit**

```powershell
git add frontend/src/components/xhs/panels/TitlePanel.vue frontend/src/components/xhs/panels/__tests__/TitlePanel.spec.ts
git commit -m "feat(xhs): 标题面板 TitlePanel (P1 T5)"
```

---

## Task 6: 文案面板 CopyPanel.vue

**Files:**
- Create: `frontend/src/components/xhs/panels/CopyPanel.vue`
- Test: `frontend/src/components/xhs/panels/__tests__/CopyPanel.spec.ts`

分组 tab + 文案片段列表。点击 → `xhs.insertAtCursor(item)`（插入正文光标处）。

- [ ] **Step 1: 写失败测试**

Create `frontend/src/components/xhs/panels/__tests__/CopyPanel.spec.ts`：

```typescript
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { mount } from "@vue/test-utils";

vi.mock("@/stores/sidecar", () => ({
  useSidecar: () => ({
    client: {
      get: vi.fn(),
      post: vi.fn().mockResolvedValue({ data: { id: "d1" } }),
      patch: vi.fn().mockResolvedValue({ data: {} }),
      delete: vi.fn(),
    },
    sseURL: (p: string) => p,
  }),
}));

import CopyPanel from "@/components/xhs/panels/CopyPanel.vue";
import { useXhs, _resetXhsModuleState } from "@/stores/xhs";

beforeEach(() => {
  setActivePinia(createPinia());
  _resetXhsModuleState();
  vi.useFakeTimers();
});
afterEach(() => {
  vi.clearAllTimers();
  vi.useRealTimers();
});

describe("CopyPanel", () => {
  it("点击文案片段调 insertAtCursor", async () => {
    const store = useXhs();
    const spy = vi.spyOn(store, "insertAtCursor");
    const w = mount(CopyPanel);
    const first = w.find(".xhs-row");
    await first.trigger("click");
    expect(spy).toHaveBeenCalledWith(first.text().trim());
    w.unmount();
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `npx vitest run src/components/xhs/panels/__tests__/CopyPanel.spec.ts`
Expected: FAIL —— 无法解析 `@/components/xhs/panels/CopyPanel.vue`。

- [ ] **Step 3: 实现组件**

Create `frontend/src/components/xhs/panels/CopyPanel.vue`：

```vue
<script setup lang="ts">
/** 文案面板（设计稿 §5「文案」）。分组 tab + 文案片段；点击插入正文光标处。 */
import { ref, computed } from "vue";
import CategoryTabs from "./CategoryTabs.vue";
import { COPY_GROUPS } from "@/data/xhs/assets";
import { useXhs } from "@/stores/xhs";

const xhs = useXhs();
const grp = ref(COPY_GROUPS[0]?.key ?? "");
const tabs = COPY_GROUPS.map((g) => ({ key: g.key, name: g.name }));
const items = computed(() => COPY_GROUPS.find((g) => g.key === grp.value)?.items ?? []);
</script>

<template>
  <div class="flex h-full flex-col" :style="{ gap: '10px' }">
    <CategoryTabs v-model="grp" :tabs="tabs" />
    <div class="min-h-0 flex-1 overflow-y-auto flex flex-col" :style="{ gap: '8px' }">
      <button v-for="(it, i) in items" :key="i" type="button" class="xhs-row" @click="xhs.insertAtCursor(it)">
        {{ it }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.xhs-row {
  text-align: left;
  border: 1px solid var(--line-2);
  border-radius: 10px;
  padding: 8px 12px;
  background: #fff;
  color: var(--ink);
  font-size: 13px;
  cursor: pointer;
  transition: border-color 0.15s;
}
.xhs-row:hover {
  border-color: var(--primary);
}
</style>
```

- [ ] **Step 4: 跑测试确认通过**

Run: `npx vitest run src/components/xhs/panels/__tests__/CopyPanel.spec.ts`
Expected: PASS。

- [ ] **Step 5: Commit**

```powershell
git add frontend/src/components/xhs/panels/CopyPanel.vue frontend/src/components/xhs/panels/__tests__/CopyPanel.spec.ts
git commit -m "feat(xhs): 文案面板 CopyPanel (P1 T6)"
```

---

## Task 7: 话题面板 TopicPanel.vue

**Files:**
- Create: `frontend/src/components/xhs/panels/TopicPanel.vue`
- Test: `frontend/src/components/xhs/panels/__tests__/TopicPanel.spec.ts`

分组 tab + #话题胶囊。点击 → `xhs.addTopic(tag)`（store 已去重、去前导 #）。已添加的高亮。

- [ ] **Step 1: 写失败测试**

Create `frontend/src/components/xhs/panels/__tests__/TopicPanel.spec.ts`：

```typescript
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { mount } from "@vue/test-utils";

vi.mock("@/stores/sidecar", () => ({
  useSidecar: () => ({
    client: {
      get: vi.fn(),
      post: vi.fn().mockResolvedValue({ data: { id: "d1" } }),
      patch: vi.fn().mockResolvedValue({ data: {} }),
      delete: vi.fn(),
    },
    sseURL: (p: string) => p,
  }),
}));

import TopicPanel from "@/components/xhs/panels/TopicPanel.vue";
import { useXhs, _resetXhsModuleState } from "@/stores/xhs";

beforeEach(() => {
  setActivePinia(createPinia());
  _resetXhsModuleState();
  vi.useFakeTimers();
});
afterEach(() => {
  vi.clearAllTimers();
  vi.useRealTimers();
});

describe("TopicPanel", () => {
  it("点击话题加入 topics，重复点击不重复", async () => {
    const store = useXhs();
    const w = mount(TopicPanel);
    const first = w.find(".xhs-tag");
    const tag = first.text().replace(/^#/, "").trim();
    await first.trigger("click");
    expect(store.topics).toContain(tag);
    await first.trigger("click"); // 再点一次
    expect(store.topics.filter((t) => t === tag)).toHaveLength(1);
    w.unmount();
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `npx vitest run src/components/xhs/panels/__tests__/TopicPanel.spec.ts`
Expected: FAIL —— 无法解析 `@/components/xhs/panels/TopicPanel.vue`。

- [ ] **Step 3: 实现组件**

Create `frontend/src/components/xhs/panels/TopicPanel.vue`：

```vue
<script setup lang="ts">
/** 话题面板（设计稿 §5「话题」）。分组 tab + #话题；点击加 chip（store 去重去 #）。已加的高亮。 */
import { ref, computed } from "vue";
import CategoryTabs from "./CategoryTabs.vue";
import { TOPIC_GROUPS } from "@/data/xhs/assets";
import { useXhs } from "@/stores/xhs";

const xhs = useXhs();
const grp = ref(TOPIC_GROUPS[0]?.key ?? "");
const tabs = TOPIC_GROUPS.map((g) => ({ key: g.key, name: g.name }));
const tags = computed(() => TOPIC_GROUPS.find((g) => g.key === grp.value)?.tags ?? []);
function added(tag: string): boolean {
  return xhs.topics.includes(tag);
}
</script>

<template>
  <div class="flex h-full flex-col" :style="{ gap: '10px' }">
    <CategoryTabs v-model="grp" :tabs="tabs" />
    <div class="min-h-0 flex-1 overflow-y-auto flex flex-wrap" :style="{ gap: '8px', alignContent: 'flex-start' }">
      <button
        v-for="(t, i) in tags"
        :key="i"
        type="button"
        class="xhs-tag"
        :style="{
          fontSize: '13px', padding: '5px 12px', borderRadius: '999px', cursor: 'pointer',
          border: '1px solid ' + (added(t) ? '#3a6fb0' : 'var(--line-2)'),
          background: added(t) ? 'rgba(58,111,176,0.10)' : '#fff',
          color: added(t) ? '#3a6fb0' : 'var(--ink)',
        }"
        @click="xhs.addTopic(t)"
      >
        #{{ t }}
      </button>
    </div>
  </div>
</template>
```

- [ ] **Step 4: 跑测试确认通过**

Run: `npx vitest run src/components/xhs/panels/__tests__/TopicPanel.spec.ts`
Expected: PASS（加入 + 去重两条断言绿）。

- [ ] **Step 5: Commit**

```powershell
git add frontend/src/components/xhs/panels/TopicPanel.vue frontend/src/components/xhs/panels/__tests__/TopicPanel.spec.ts
git commit -m "feat(xhs): 话题面板 TopicPanel (P1 T7)"
```

---

## Task 8: 装饰面板 DecorationPanel.vue

**Files:**
- Create: `frontend/src/components/xhs/panels/DecorationPanel.vue`
- Test: `frontend/src/components/xhs/panels/__tests__/DecorationPanel.spec.ts`

分组 tab（分割线 / 项目符号）+ 符号胶囊。点击 → `xhs.insertAtCursor(item)`。

- [ ] **Step 1: 写失败测试**

Create `frontend/src/components/xhs/panels/__tests__/DecorationPanel.spec.ts`：

```typescript
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { mount } from "@vue/test-utils";

vi.mock("@/stores/sidecar", () => ({
  useSidecar: () => ({
    client: {
      get: vi.fn(),
      post: vi.fn().mockResolvedValue({ data: { id: "d1" } }),
      patch: vi.fn().mockResolvedValue({ data: {} }),
      delete: vi.fn(),
    },
    sseURL: (p: string) => p,
  }),
}));

import DecorationPanel from "@/components/xhs/panels/DecorationPanel.vue";
import { useXhs, _resetXhsModuleState } from "@/stores/xhs";

beforeEach(() => {
  setActivePinia(createPinia());
  _resetXhsModuleState();
  vi.useFakeTimers();
});
afterEach(() => {
  vi.clearAllTimers();
  vi.useRealTimers();
});

describe("DecorationPanel", () => {
  it("点击装饰符号调 insertAtCursor", async () => {
    const store = useXhs();
    const spy = vi.spyOn(store, "insertAtCursor");
    const w = mount(DecorationPanel);
    const first = w.find(".xhs-deco");
    await first.trigger("click");
    expect(spy).toHaveBeenCalledTimes(1);
    expect(typeof spy.mock.calls[0][0]).toBe("string");
    expect((spy.mock.calls[0][0] as string).length).toBeGreaterThan(0);
    w.unmount();
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `npx vitest run src/components/xhs/panels/__tests__/DecorationPanel.spec.ts`
Expected: FAIL —— 无法解析 `@/components/xhs/panels/DecorationPanel.vue`。

- [ ] **Step 3: 实现组件**

Create `frontend/src/components/xhs/panels/DecorationPanel.vue`：

```vue
<script setup lang="ts">
/** 装饰面板（设计稿 §5「装饰」）。分割线 / 项目符号分组；点击插入正文光标处。 */
import { ref, computed } from "vue";
import CategoryTabs from "./CategoryTabs.vue";
import { DECORATION_GROUPS } from "@/data/xhs/assets";
import { useXhs } from "@/stores/xhs";

const xhs = useXhs();
const grp = ref(DECORATION_GROUPS[0]?.key ?? "");
const tabs = DECORATION_GROUPS.map((g) => ({ key: g.key, name: g.name }));
const items = computed(() => DECORATION_GROUPS.find((g) => g.key === grp.value)?.items ?? []);
</script>

<template>
  <div class="flex h-full flex-col" :style="{ gap: '10px' }">
    <CategoryTabs v-model="grp" :tabs="tabs" />
    <div class="min-h-0 flex-1 overflow-y-auto flex flex-wrap" :style="{ gap: '8px', alignContent: 'flex-start' }">
      <button
        v-for="(it, i) in items"
        :key="i"
        type="button"
        class="xhs-deco"
        :style="{
          fontSize: '14px', padding: '8px 12px', borderRadius: '10px', cursor: 'pointer',
          border: '1px solid var(--line-2)', background: '#fff', color: 'var(--ink)', whiteSpace: 'nowrap',
        }"
        @click="xhs.insertAtCursor(it)"
      >
        {{ it }}
      </button>
    </div>
  </div>
</template>
```

- [ ] **Step 4: 跑测试确认通过**

Run: `npx vitest run src/components/xhs/panels/__tests__/DecorationPanel.spec.ts`
Expected: PASS。

- [ ] **Step 5: Commit**

```powershell
git add frontend/src/components/xhs/panels/DecorationPanel.vue frontend/src/components/xhs/panels/__tests__/DecorationPanel.spec.ts
git commit -m "feat(xhs): 装饰面板 DecorationPanel (P1 T8)"
```

---

## Task 9: 表情面板 EmojiPanel.vue

**Files:**
- Create: `frontend/src/components/xhs/panels/EmojiPanel.vue`
- Test: `frontend/src/components/xhs/panels/__tests__/EmojiPanel.spec.ts`

三模式（常用分组 / 全部 Unicode / 小红书代码）。前两者再用 CategoryTabs 选子分组，渲染 emoji 网格；第三个渲染代码胶囊。点击都走 `xhs.insertAtCursor`（emoji 插字形、代码插文字代码）。

- [ ] **Step 1: 写失败测试**

Create `frontend/src/components/xhs/panels/__tests__/EmojiPanel.spec.ts`：

```typescript
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { mount } from "@vue/test-utils";

vi.mock("@/stores/sidecar", () => ({
  useSidecar: () => ({
    client: {
      get: vi.fn(),
      post: vi.fn().mockResolvedValue({ data: { id: "d1" } }),
      patch: vi.fn().mockResolvedValue({ data: {} }),
      delete: vi.fn(),
    },
    sseURL: (p: string) => p,
  }),
}));

import EmojiPanel from "@/components/xhs/panels/EmojiPanel.vue";
import { useXhs, _resetXhsModuleState } from "@/stores/xhs";

beforeEach(() => {
  setActivePinia(createPinia());
  _resetXhsModuleState();
  vi.useFakeTimers();
});
afterEach(() => {
  vi.clearAllTimers();
  vi.useRealTimers();
});

describe("EmojiPanel", () => {
  it("点击 emoji 调 insertAtCursor 插入该字形", async () => {
    const store = useXhs();
    const spy = vi.spyOn(store, "insertAtCursor");
    const w = mount(EmojiPanel);
    const e = w.find(".xhs-emoji");
    await e.trigger("click");
    expect(spy).toHaveBeenCalledWith(e.text());
    w.unmount();
  });

  it("切到「小红书代码」模式，点击插入代码文本（以 [ 开头）", async () => {
    const store = useXhs();
    const spy = vi.spyOn(store, "insertAtCursor");
    const w = mount(EmojiPanel);
    const codeTab = w.findAll("button").find((b) => b.text() === "小红书代码");
    expect(codeTab).toBeTruthy();
    await codeTab!.trigger("click");
    const codeBtn = w.find(".xhs-code");
    await codeBtn.trigger("click");
    expect(spy).toHaveBeenCalledTimes(1);
    expect((spy.mock.calls[0][0] as string).startsWith("[")).toBe(true);
    w.unmount();
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `npx vitest run src/components/xhs/panels/__tests__/EmojiPanel.spec.ts`
Expected: FAIL —— 无法解析 `@/components/xhs/panels/EmojiPanel.vue`。

- [ ] **Step 3: 实现组件**

Create `frontend/src/components/xhs/panels/EmojiPanel.vue`：

```vue
<script setup lang="ts">
/**
 * 表情面板（设计稿 §5「表情」/§6 边界）。三模式：常用分组 / 全部(Unicode) / 小红书代码。
 * 前两者再用 CategoryTabs 选子分组。点击 emoji 或代码插入正文光标处。
 * 小红书代码插入的是文字代码（如 [害羞R]），复制到小红书 App 会渲染成贴纸；
 * 本应用不打包官方贴纸图片（版权 / ToS），代码在本编辑器内按纯文本显示。
 */
import { ref, computed } from "vue";
import CategoryTabs from "./CategoryTabs.vue";
import { EMOJI } from "@/data/xhs/assets";
import { useXhs } from "@/stores/xhs";

const xhs = useXhs();
type Mode = "curated" | "unicode" | "codes";
const mode = ref<Mode>("curated");
const modeTabs = [
  { key: "curated", name: "常用分组" },
  { key: "unicode", name: "全部" },
  { key: "codes", name: "小红书代码" },
];

const curatedKey = ref(EMOJI.curatedGroups[0]?.key ?? "");
const unicodeKey = ref(EMOJI.unicodeGroups[0]?.key ?? "");

const subTabs = computed(() =>
  mode.value === "curated"
    ? EMOJI.curatedGroups.map((g) => ({ key: g.key, name: g.name }))
    : mode.value === "unicode"
      ? EMOJI.unicodeGroups.map((g) => ({ key: g.key, name: g.name }))
      : [],
);
const subKey = computed<string>({
  get: () => (mode.value === "curated" ? curatedKey.value : unicodeKey.value),
  set: (v) => {
    if (mode.value === "curated") curatedKey.value = v;
    else unicodeKey.value = v;
  },
});
const emojis = computed(() => {
  if (mode.value === "curated") return EMOJI.curatedGroups.find((g) => g.key === curatedKey.value)?.emojis ?? [];
  if (mode.value === "unicode") return EMOJI.unicodeGroups.find((g) => g.key === unicodeKey.value)?.emojis ?? [];
  return [];
});
</script>

<template>
  <div class="flex h-full flex-col" :style="{ gap: '10px' }">
    <CategoryTabs :model-value="mode" :tabs="modeTabs" @update:model-value="(v) => (mode = v as Mode)" />
    <CategoryTabs v-if="mode !== 'codes'" v-model="subKey" :tabs="subTabs" />

    <!-- emoji 网格 -->
    <div
      v-if="mode !== 'codes'"
      class="min-h-0 flex-1 overflow-y-auto"
      :style="{ display: 'grid', gridTemplateColumns: 'repeat(7, 1fr)', gap: '4px', alignContent: 'flex-start' }"
    >
      <button v-for="(e, i) in emojis" :key="i" type="button" class="xhs-emoji" @click="xhs.insertAtCursor(e)">
        {{ e }}
      </button>
    </div>

    <!-- 小红书代码 -->
    <div v-else class="min-h-0 flex-1 overflow-y-auto flex flex-wrap" :style="{ gap: '6px', alignContent: 'flex-start' }">
      <button
        v-for="c in EMOJI.xhsCodes"
        :key="c.code"
        type="button"
        class="xhs-code"
        :title="`插入代码 ${c.code}`"
        :style="{
          fontSize: '12px', padding: '5px 10px', borderRadius: '999px', cursor: 'pointer',
          border: '1px dashed var(--line-2)', background: 'rgba(var(--ink-rgb),0.04)', color: 'var(--ink)',
        }"
        @click="xhs.insertAtCursor(c.code)"
      >
        {{ c.label }} <span :style="{ color: 'var(--ink-2)' }">{{ c.code }}</span>
      </button>
    </div>
  </div>
</template>

<style scoped>
.xhs-emoji {
  font-size: 20px;
  line-height: 1;
  padding: 6px 0;
  border-radius: 8px;
  cursor: pointer;
  background: transparent;
  transition: background 0.12s;
}
.xhs-emoji:hover {
  background: rgba(var(--ink-rgb), 0.06);
}
</style>
```

- [ ] **Step 4: 跑测试确认通过**

Run: `npx vitest run src/components/xhs/panels/__tests__/EmojiPanel.spec.ts`
Expected: PASS（emoji 插入 + 代码模式插入两条绿）。

- [ ] **Step 5: Commit**

```powershell
git add frontend/src/components/xhs/panels/EmojiPanel.vue frontend/src/components/xhs/panels/__tests__/EmojiPanel.spec.ts
git commit -m "feat(xhs): 表情面板 EmojiPanel——常用/Unicode/小红书代码三模式 (P1 T9)"
```

---

## Task 10: 主题面板 ThemePanel.vue

**Files:**
- Create: `frontend/src/components/xhs/panels/ThemePanel.vue`
- Test: `frontend/src/components/xhs/panels/__tests__/ThemePanel.spec.ts`

主题卡列表，每卡带样例预览（小标题符号 / 列表项 / 分割线）。点击 → `xhs.applyTheme(id)`，激活卡显 check + 橙框。

- [ ] **Step 1: 写失败测试**

Create `frontend/src/components/xhs/panels/__tests__/ThemePanel.spec.ts`：

```typescript
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { mount } from "@vue/test-utils";

vi.mock("@/stores/sidecar", () => ({
  useSidecar: () => ({
    client: {
      get: vi.fn(),
      post: vi.fn().mockResolvedValue({ data: { id: "d1" } }),
      patch: vi.fn().mockResolvedValue({ data: {} }),
      delete: vi.fn(),
    },
    sseURL: (p: string) => p,
  }),
}));

import ThemePanel from "@/components/xhs/panels/ThemePanel.vue";
import { useXhs, _resetXhsModuleState } from "@/stores/xhs";
import { THEMES } from "@/data/xhs/assets";

beforeEach(() => {
  setActivePinia(createPinia());
  _resetXhsModuleState();
  vi.useFakeTimers();
});
afterEach(() => {
  vi.clearAllTimers();
  vi.useRealTimers();
});

describe("ThemePanel", () => {
  it("点击主题卡设激活主题", async () => {
    const store = useXhs();
    const w = mount(ThemePanel);
    await w.find(".xhs-theme-card").trigger("click");
    expect(store.themeId).toBe(THEMES[0].id);
    expect(store.activeTheme?.id).toBe(THEMES[0].id);
    w.unmount();
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `npx vitest run src/components/xhs/panels/__tests__/ThemePanel.spec.ts`
Expected: FAIL —— 无法解析 `@/components/xhs/panels/ThemePanel.vue`。

- [ ] **Step 3: 实现组件**

Create `frontend/src/components/xhs/panels/ThemePanel.vue`：

```vue
<script setup lang="ts">
/**
 * 主题面板（设计稿 §5「主题」/§1 P1 排版主题）。点击应用排版主题，
 * 编辑器工具条随即出现这套主题的小标题/无序/分割线快捷符号。P1 起步 3 套。
 */
import Icon from "@/components/ui/Icon.vue";
import { THEMES } from "@/data/xhs/assets";
import { useXhs } from "@/stores/xhs";

const xhs = useXhs();
</script>

<template>
  <div class="flex h-full flex-col overflow-y-auto" :style="{ gap: '10px' }">
    <div :style="{ fontSize: '11px', color: 'var(--ink-2)', flexShrink: 0 }">
      应用后，编辑器顶部工具条会出现这套排版符号的一键插入按钮
    </div>
    <button
      v-for="t in THEMES"
      :key="t.id"
      type="button"
      class="xhs-theme-card"
      :style="{ borderColor: xhs.themeId === t.id ? 'var(--primary)' : 'var(--line-2)' }"
      @click="xhs.applyTheme(t.id)"
    >
      <div class="flex items-center" :style="{ justifyContent: 'space-between', marginBottom: '6px' }">
        <span :style="{ fontSize: '13px', fontWeight: 600, color: 'var(--ink)' }">{{ t.name }}</span>
        <Icon v-if="xhs.themeId === t.id" name="check" :size="16" :style="{ color: 'var(--primary)' }" />
      </div>
      <div :style="{ fontSize: '13px', color: 'var(--ink)', lineHeight: 1.9 }">
        <div>{{ t.heading }} 小标题示例</div>
        <div>{{ t.bullet }} 列表项一</div>
        <div :style="{ color: 'var(--ink-2)' }">{{ t.divider }}</div>
      </div>
    </button>
  </div>
</template>

<style scoped>
.xhs-theme-card {
  text-align: left;
  border: 1px solid var(--line-2);
  border-radius: 12px;
  padding: 12px;
  background: #fff;
  cursor: pointer;
  transition: border-color 0.15s;
}
.xhs-theme-card:hover {
  border-color: var(--primary);
}
</style>
```

- [ ] **Step 4: 跑测试确认通过**

Run: `npx vitest run src/components/xhs/panels/__tests__/ThemePanel.spec.ts`
Expected: PASS。

- [ ] **Step 5: Commit**

```powershell
git add frontend/src/components/xhs/panels/ThemePanel.vue frontend/src/components/xhs/panels/__tests__/ThemePanel.spec.ts
git commit -m "feat(xhs): 主题面板 ThemePanel——应用排版主题 (P1 T10)"
```

---

## Task 11: NoteEditor 工具条——主题快捷符号 + 表情快捷入口

**Files:**
- Modify: `frontend/src/components/xhs/NoteEditor.vue`（替换 P0 占位工具条）
- Test: `frontend/src/components/xhs/__tests__/NoteEditor.spec.ts`（新建）

把 P0 的占位工具条（"排版工具栏将在 P1 上线…"）换成：有激活主题时渲染 `xhs.themeToolbar` 的快捷符号按钮（点击 `insertAtCursor(symbol)`）；无主题时显示「选择排版主题」入口（切到 theme 面板）；右侧常驻「表情」快捷（切到 emoji 面板）。

- [ ] **Step 1: 写失败测试**

Create `frontend/src/components/xhs/__tests__/NoteEditor.spec.ts`：

```typescript
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { mount } from "@vue/test-utils";

vi.mock("@/stores/sidecar", () => ({
  useSidecar: () => ({
    client: {
      get: vi.fn(),
      post: vi.fn().mockResolvedValue({ data: { id: "d1" } }),
      patch: vi.fn().mockResolvedValue({ data: {} }),
      delete: vi.fn(),
    },
    sseURL: (p: string) => p,
  }),
}));

import NoteEditor from "@/components/xhs/NoteEditor.vue";
import { useXhs, _resetXhsModuleState } from "@/stores/xhs";
import { THEMES } from "@/data/xhs/assets";

beforeEach(() => {
  setActivePinia(createPinia());
  _resetXhsModuleState();
  vi.useFakeTimers();
});
afterEach(() => {
  vi.clearAllTimers();
  vi.useRealTimers();
});

describe("NoteEditor 工具条", () => {
  it("无激活主题时显示「选择排版主题」入口", () => {
    useXhs();
    const w = mount(NoteEditor);
    expect(w.text()).toContain("选择排版主题");
    w.unmount();
  });

  it("有激活主题时点击小标题快捷符号插入该符号", async () => {
    const store = useXhs();
    store.applyTheme(THEMES[0].id);
    const spy = vi.spyOn(store, "insertAtCursor");
    const w = mount(NoteEditor);
    const btn = w.findAll(".xhs-tool-btn").find((b) => b.text().includes("小标题"));
    expect(btn).toBeTruthy();
    await btn!.trigger("click");
    expect(spy).toHaveBeenCalledWith(THEMES[0].heading);
    w.unmount();
  });

  it("点击「表情」快捷切到 emoji 面板", async () => {
    const store = useXhs();
    const w = mount(NoteEditor);
    const btn = w.findAll(".xhs-tool-btn").find((b) => b.text().includes("表情"));
    expect(btn).toBeTruthy();
    await btn!.trigger("click");
    expect(store.activePanel).toBe("emoji");
    w.unmount();
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `npx vitest run src/components/xhs/__tests__/NoteEditor.spec.ts`
Expected: FAIL —— 现工具条是占位文案，找不到 `.xhs-tool-btn` / 「选择排版主题」。

- [ ] **Step 3: 改 NoteEditor 工具条**

在 `frontend/src/components/xhs/NoteEditor.vue` 中，把 `<template>` 里这一段 P0 占位工具条整体替换：

```vue
    <!-- 工具条（P0 占位；P1 放排版主题快捷符号 + emoji 快捷） -->
    <div
      class="flex items-center"
      :style="{
        gap: '8px', padding: '8px 10px', borderRadius: '10px',
        background: 'rgba(var(--ink-rgb),0.03)', color: 'var(--ink-2)', fontSize: '12px',
      }"
    >
      <Icon name="wand" :size="14" />
      <span>排版工具栏将在 P1 上线（一键插入小标题符号 / 分割线 / emoji）</span>
    </div>
```

替换为：

```vue
    <!-- 工具条：排版主题快捷符号 + 表情快捷（设计稿 §4.1 中栏工具条 / §1 P1） -->
    <div class="flex flex-wrap items-center" :style="{ gap: '6px', flexShrink: 0 }">
      <template v-if="xhs.themeToolbar.length">
        <button
          v-for="b in xhs.themeToolbar"
          :key="b.key"
          type="button"
          class="xhs-tool-btn"
          :title="`插入${b.label}符号`"
          @click="xhs.insertAtCursor(b.symbol)"
        >
          <span :style="{ fontSize: '14px' }">{{ b.symbol }}</span>
          <span :style="{ fontSize: '12px', color: 'var(--ink-2)' }">{{ b.label }}</span>
        </button>
      </template>
      <button v-else type="button" class="xhs-tool-btn" @click="xhs.setActivePanel('theme')">
        <Icon name="wand" :size="14" /> 选择排版主题
      </button>
      <button type="button" class="xhs-tool-btn" :style="{ marginLeft: 'auto' }" @click="xhs.setActivePanel('emoji')">
        <Icon name="heart" :size="14" /> 表情
      </button>
    </div>
```

并在 `<style scoped>` 块里（`.xhs-copy-btn` 旁边）追加：

```css
.xhs-tool-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 13px;
  padding: 6px 12px;
  border-radius: 8px;
  border: 1px solid var(--line-2);
  background: #fff;
  color: var(--ink);
  cursor: pointer;
  transition: filter 0.15s;
}
.xhs-tool-btn:hover {
  filter: brightness(0.97);
}
```

> NoteEditor 已 `import Icon`、`useXhs`，无需新增 import。`xhs.themeToolbar` / `setActivePanel` / `insertAtCursor` 均在 T2/P0 已就绪。

- [ ] **Step 4: 跑测试确认通过**

Run: `npx vitest run src/components/xhs/__tests__/NoteEditor.spec.ts`
Expected: PASS（无主题入口 / 主题快捷插入 / 表情切面板 三条绿）。

- [ ] **Step 5: Commit**

```powershell
git add frontend/src/components/xhs/NoteEditor.vue frontend/src/components/xhs/__tests__/NoteEditor.spec.ts
git commit -m "feat(xhs): NoteEditor 工具条接主题快捷符号 + 表情入口 (P1 T11)"
```

---

## Task 12: PanelRail 派发到真实面板

**Files:**
- Modify: `frontend/src/components/xhs/PanelRail.vue`

把内容区从「占位说明」改成 `<component :is>` 派发到 7 个真实面板；image / ai 两个 tab 仍保留 P0 占位（P2 / P3 上线）。左侧图标 tab 列不变。

> 本任务是纯接线（无新逻辑），交付门禁是 `npm run build`（vue-tsc 类型检查通过）+ 手动验收（T13）。面板自身行为已在 T4–T10 单测覆盖，故不再为 PanelRail 单独写 mount 测试（与 P0 PanelRail 无单测一致）。

- [ ] **Step 1: 改 PanelRail —— `<script setup>` 部分**

把 `frontend/src/components/xhs/PanelRail.vue` 的 `<script setup lang="ts">` 整体替换为：

```vue
<script setup lang="ts">
/**
 * 左栏素材面板（设计稿 §4.1 左 / §5 九面板）。
 * 左侧 9 个图标 tab；右侧内容区按 activePanel 派发到对应面板组件。
 * 文字面板（模版/主题/表情/标题/文案/话题/装饰）P1 已上线；图片(P2)/AI(P3) 仍占位。
 */
import { computed, type Component } from "vue";
import Icon from "@/components/ui/Icon.vue";
import { useXhs, type XhsPanel } from "@/stores/xhs";
import TemplatePanel from "./panels/TemplatePanel.vue";
import ThemePanel from "./panels/ThemePanel.vue";
import EmojiPanel from "./panels/EmojiPanel.vue";
import TitlePanel from "./panels/TitlePanel.vue";
import CopyPanel from "./panels/CopyPanel.vue";
import TopicPanel from "./panels/TopicPanel.vue";
import DecorationPanel from "./panels/DecorationPanel.vue";

const xhs = useXhs();

interface PanelDef {
  key: XhsPanel;
  icon: string;
  label: string;
  /** 占位说明：该面板将在哪个阶段上线（仅 image/ai 仍占位）。 */
  stage: string;
}

// icon 全部复用 Icon.vue 现有图标，避免新增 SVG。
const PANELS: PanelDef[] = [
  { key: "template", icon: "library", label: "模版", stage: "P1" },
  { key: "theme", icon: "sliders", label: "主题", stage: "P1" },
  { key: "emoji", icon: "heart", label: "表情", stage: "P1" },
  { key: "title", icon: "edit", label: "标题", stage: "P1" },
  { key: "copy", icon: "doc", label: "文案", stage: "P1" },
  { key: "topic", icon: "tag", label: "话题", stage: "P1" },
  { key: "decoration", icon: "skills", label: "装饰", stage: "P1" },
  { key: "image", icon: "image", label: "图片", stage: "P2" },
  { key: "ai", icon: "spark", label: "AI", stage: "P3" },
];

// activePanel → 面板组件；image / ai 不在表内 → 走占位分支。
const PANEL_COMPONENTS: Partial<Record<XhsPanel, Component>> = {
  template: TemplatePanel,
  theme: ThemePanel,
  emoji: EmojiPanel,
  title: TitlePanel,
  copy: CopyPanel,
  topic: TopicPanel,
  decoration: DecorationPanel,
};

const activeComponent = computed<Component | null>(() => PANEL_COMPONENTS[xhs.activePanel] ?? null);

function activeDef(): PanelDef {
  return PANELS.find((p) => p.key === xhs.activePanel) ?? PANELS[0];
}
</script>
```

- [ ] **Step 2: 改 PanelRail —— `<template>` 内容区**

把 `<template>` 里「面板内容区（P0 占位）」那个 `<div class="min-h-0 flex-1 overflow-y-auto" ...>` 整块替换为：

```vue
    <!-- 面板内容区：派发到真实面板；image/ai 仍占位 -->
    <div class="min-h-0 flex-1 overflow-hidden" :style="{ padding: '14px' }">
      <component :is="activeComponent" v-if="activeComponent" />
      <div
        v-else
        class="flex flex-col items-center justify-center"
        :style="{
          gap: '10px', textAlign: 'center', color: 'var(--ink-2)', fontSize: '13px',
          border: '1px dashed var(--line-2)', borderRadius: '12px', padding: '28px 16px',
        }"
      >
        <Icon :name="activeDef().icon" :size="26" />
        <div>「{{ activeDef().label }}」面板将在 {{ activeDef().stage }} 上线</div>
      </div>
    </div>
```

（左侧图标 tab 列那段 `<div class="flex flex-col items-center" ...>` 完全不动。）

- [ ] **Step 3: 类型检查 + 构建确认通过**

Run: `npx vue-tsc -b`
Expected: 零错误。（若 emit 了 `vite.config.js` / `.d.ts` 产物，按前置说明 `git checkout --` 还原 / 删除。）

Run: `npm run build`
Expected: 构建成功（`vue-tsc -b && vite build` 均过）。

- [ ] **Step 4: Commit**

```powershell
git add frontend/src/components/xhs/PanelRail.vue
git commit -m "feat(xhs): PanelRail 派发到 7 个真实文字面板 (P1 T12)"
```

---

## Task 13: 全量验证 + 手动验收

**Files:** 无（仅验证）

- [ ] **Step 1: 全量前端单测**

Run（在 `frontend/`）: `npx vitest run`
Expected: PASS。新增：assets(5) + CategoryTabs(2) + Template(2) + Title(1) + Copy(1) + Topic(1) + Decoration(1) + Emoji(2) + Theme(1) + NoteEditor(3) + store P1(5) = 24 条新增，叠加 P0 既有（xhsText 10 + useCursorInsert 7 + xhs store 12 + 其它既有 suite）全绿。

- [ ] **Step 2: 类型检查 + 构建门禁**

Run: `npx vue-tsc -b` → 零错误（产物按前置说明还原）。
Run: `npm run build` → 成功。

- [ ] **Step 3: 后端零回归 sanity（可选但建议）**

P1 不碰后端，跑一次确认没误伤（在仓库根，先设 P0 那套 PYTHONPATH）：

```powershell
$env:PYTHONPATH = "D:\CSM\.claude\worktrees\cranky-varahamihira-d53003\sidecar;D:\CSM\.claude\worktrees\cranky-varahamihira-d53003"
python -m pytest sidecar/tests/test_xhs_storage.py sidecar/tests/test_xhs_routes.py -q
```

Expected: PASS（与 P0 一致，18 条）。

- [ ] **Step 4: 手动验收（启动浏览器 dev）**

启动器已在 P0 备好：双击 `D:\CSM\.claude\worktrees\cranky-varahamihira-d53003\.csm-dev\启动小红书测试.bat`（会用 worktree 代码起 sidecar + vite 并打开 `http://localhost:5173/#/xhs`）。逐条对照设计稿 §7 P1 验收：

  1. **模版**：切分类 tab → 卡片显示对应分类；编辑器为空时点卡片直接载入 title/body/topics；编辑器已有内容时点卡片先弹确认，取消则不变、确认则覆盖。
  2. **表情**：常用分组 / 全部 / 小红书代码三模式可切；点 emoji 在正文**光标处**插入（不是末尾）；小红书代码点了插入 `[害羞R]` 这类文字代码。
  3. **标题**：点条目填入标题输入框（替换原标题），`xx` 占位保留。
  4. **文案**：点片段在正文光标处插入。
  5. **话题**：点 #话题加 chip；重复点不重复；已加的胶囊高亮。
  6. **装饰**：点分割线 / 项目符号在正文光标处插入。
  7. **主题**：点主题卡 → 卡片橙框 + check；编辑器工具条出现该主题的「小标题/无序/分割线」按钮；点按钮在光标处插入对应符号；点「表情」快捷切到表情面板。
  8. **联动 & 持久化**：右侧预览随插入实时更新；停 ~1s 后自动保存（顶部「已保存」）；刷新页面 / 重开草稿，主题与内容都在。
  9. **复制全文**：仍输出「标题 + 空行 + 正文 + 空行 + #话题」。

- [ ] **Step 5: 收尾**

确认 `git status` 干净（无残留 `vite.config.js` / `.d.ts` / `package-lock.json` 改动 / `.log`）。P1 全部任务已各自 commit，无需额外提交。

---

## Self-Review（写完计划后自查）

**1. Spec coverage（设计稿 §1 P1 / §5 六面板 + 主题）**
- 模版 → T4 ✓；表情（三段式）→ T9 ✓；标题 → T5 ✓；文案 → T6 ✓；话题 → T7 ✓；装饰 → T8 ✓。
- 排版主题「应用 + 工具条快捷符号」→ 数据 T1 + store T2（applyTheme/activeTheme/themeToolbar）+ 面板 T10 + 工具条 T11 ✓。
- JSON 驱动、纯前端零后端 → T1 数据 + 全程不动 sidecar ✓（主题/模板落盘复用 P0 PATCH）。
- 面板挂载（9 tab 派发）→ T12 ✓。
- §6 版权边界（代码插入文字、不打包贴纸图）→ EmojiPanel 注释 + 仅 xhsCodes 文字 ✓。

**2. Placeholder scan**：无 "TBD/TODO/待补"；每个 step 都有完整代码 / 命令 / 期望输出；JSON 为完整可用起步内容（非占位）。明确「不做」项（ordered 工具条、预览代码 chip、自定义素材）已在范围里写清是后续阶段，非本计划遗漏。

**3. Type consistency**：
- assets 导出名贯穿全程一致：`TEMPLATES`/`TEMPLATE_CATEGORIES`/`THEMES`/`EMOJI`/`TITLE_CATEGORIES`/`COPY_GROUPS`/`TOPIC_GROUPS`/`DECORATION_GROUPS`/`findTheme`（T1 定义，T2–T10 引用一致）。
- store 新增：`applyTemplate({title,body,topics})`、`applyTheme(id)`、getter `activeTheme`/`themeToolbar`（T2 定义；T4 调 applyTemplate、T10/T11 调 applyTheme、T11 读 themeToolbar）一致。
- 既有沿用：`insertAtCursor`/`addTopic`/`setTitle`/`setActivePanel`/`isEmpty`/`themeId`（P0 已有，签名未改）。
- `CategoryTabs` 接口 `{tabs:{key,name}[], modelValue}` + `update:modelValue`（T3 定义；T4–T9 用 `v-model` 或显式 `:model-value`+`@update:model-value` 一致）。
- 测试用类名钩子一致：`.xhs-tpl-card`(T4)、`.xhs-row`(T5/T6)、`.xhs-tag`(T7)、`.xhs-deco`(T8)、`.xhs-emoji`/`.xhs-code`(T9)、`.xhs-theme-card`(T10)、`.xhs-tool-btn`(T11) —— 实现与测试两侧用名对齐。

---

## Execution Handoff

实现按任务顺序有依赖：**T1（数据）→ T2（store）→ T3（CategoryTabs）** 是地基，必须先做；**T4–T10** 七个面板互相独立（都只依赖 T1/T2/T3），可并行或顺序；**T11/T12** 接线依赖 T2/T3 与 T4–T10 全部就绪；**T13** 收尾。

两种执行方式：
1. **子代理逐任务（推荐）** —— 每个任务派新 subagent + 两阶段评审（规格合规 → 代码质量），与 P0 同套路。
2. **本会话内逐任务执行** —— executing-plans，批量带检查点。
