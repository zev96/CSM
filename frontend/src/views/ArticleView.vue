<script setup lang="ts">
/**
 * 创作区 — 严格按 CSM-RE1（V1）/src/screens/article.jsx 复刻：
 *
 * 顶部 header 行：
 *   ← 返回工作台 | 分隔线 | 模板 chip | Skill chip | 字数 · 重复率
 *
 * 主内容行（flex-1）：
 *   左侧编辑卡（flex-1）：
 *     - tab bar：左 section 标签 + 右 segmented pill toggle（组装/初稿/成稿）
 *     - 整篇润色进度条（运行时）
 *     - 内容区：组装预览 / 初稿编辑器 / 成稿编辑器
 *   右侧检查面板（300px）：
 *     - 质检报告卡（盾牌 icon + 标题 + ?快捷键 按钮 + 6 个检查项卡片）
 *     - AI 润色 Skill 下拉
 *     - 操作卡（整篇润色 primary + 重新随机 / 清空 双按钮 + 导出文章 dark）
 *
 * 起飞入口：
 *   起飞入口在 home（CreateArticleHero）。本视图主要用于**已起飞**后查看
 *   /编辑文章。但用户可能直接走 keyboard 入这个路由（或者 query 没带
 *   keyword），所以保留一个"起飞条"作为 idle 状态兜底，藏在 header 下方
 *   只在 status === idle 时显示。
 */
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import Btn from "@/components/ui/Btn.vue";
import Card from "@/components/ui/Card.vue";
import Icon from "@/components/ui/Icon.vue";
import Pill from "@/components/ui/Pill.vue";
import ProgressBar from "@/components/ui/ProgressBar.vue";
import Spinner from "@/components/ui/Spinner.vue";
import FormSelect from "@/components/forms/FormSelect.vue";
import TiptapEditor from "@/components/article/TiptapEditor.vue";
import FactCheckPanel from "@/components/article/FactCheckPanel.vue";
import LintPanel from "@/components/article/LintPanel.vue";

import { useArticle, type Angle } from "@/stores/article";
import { useConfig } from "@/stores/config";
import { useSidecar } from "@/stores/sidecar";
import { useSidecarReady } from "@/composables/useSidecarReady";
import { useToast } from "@/composables/useToast";
import { failureAlert } from "@/composables/useFailureAlert";

const route = useRoute();
const router = useRouter();
const article = useArticle();
const cfg = useConfig();
const sidecar = useSidecar();
const toast = useToast();
const { whenReady } = useSidecarReady();

const keyword = ref("");
const templateId = ref<string>("");
const skillId = ref<string>("");
const seed = ref(0);

// Phase 2a 角度 + 标题 —— 从 home 起飞条扁平进 query，这里重建成 Angle
// 对象提交。空 facet → null / []；全空 → angle=null（= 今天行为）。
const angle = ref<Angle | null>(null);
const title = ref<string>("");

// Phase 2b skill 链 —— 从 query 的逗号串重建成 id 数组提交。空 = 不传链
// = 退回单 skill_id（零回归）。
const skillChain = ref<string[]>([]);
function rebuildChainFromQuery(): string[] {
  const raw = ((route.query.skill_chain as string) ?? "").trim();
  return raw ? raw.split(",").map((s) => s.trim()).filter(Boolean) : [];
}

/** 从 route.query 重建 Angle —— sellpoints 按「,」拆（空串→[]），
 * audience/tone 空 → null；三者全空返回 null（不传角度）。 */
function rebuildAngleFromQuery(): Angle | null {
  const audience = ((route.query.audience as string) ?? "").trim() || null;
  const tone = ((route.query.tone as string) ?? "").trim() || null;
  const spRaw = ((route.query.sellpoints as string) ?? "").trim();
  const sellpoints = spRaw ? spRaw.split(",").map((s) => s.trim()).filter(Boolean) : [];
  if (!audience && !tone && sellpoints.length === 0) return null;
  return { audience, sellpoints, tone };
}

// header 角度 chip 文案 —— 「铲屎官 · 防缠绕 · 口语」。卖点显示词表 label
// 拿不到就退回 key；只要任一 facet 有值就显示，全空 → null（不渲染 chip）。
const angleChipText = computed<string | null>(() => {
  const a = angle.value;
  if (!a) return null;
  const dims = article.angleTaxonomy?.dimensions ?? [];
  const labelOf = (key: string) => dims.find((d) => d.key === key)?.label ?? key;
  const parts: string[] = [];
  if (a.audience) parts.push(a.audience);
  for (const sp of a.sellpoints) parts.push(labelOf(sp));
  if (a.tone) parts.push(a.tone);
  return parts.length ? parts.join(" · ") : null;
});

// header 链 chip 文案 —— 「人设 → 去AI味 → 小红书」，按 passes 顺序连
// skill 名。无 passes（单 skill 旧路径）→ null（不渲染 chip）。
const chainChipText = computed<string | null>(() => {
  const ps = article.passes;
  if (!ps || ps.length === 0) return null;
  return ps.map((p) => p.skill_name || p.role).join(" → ");
});

// 链角色中文名 —— pass 卡上的角色标签。
const ROLE_LABELS: Record<string, string> = {
  persona: "人设",
  humanize: "去AI味",
  platform: "平台适配",
};
function roleLabel(role: string): string {
  return ROLE_LABELS[role] ?? role;
}

// 重跑 loading / 取消 由 store 的 article.rerunningIndex 驱动 —— 流式下
// store rerunPass 订阅后即早返回，本地包装的 finally 会过早清 loading 态，
// 故把「正在重跑哪个 pass」上提到 store，由 SSE done/error 收尾时清回 null。

interface TemplateRow { id: string; name: string }
interface SkillRow { id: string; name: string; desc?: string }
const templates = ref<TemplateRow[]>([]);
const skills = ref<SkillRow[]>([]);

const skillOptions = computed(() => [
  { label: "无（用模板默认）", value: "" },
  ...skills.value.map((s) => ({ label: s.name, value: s.id })),
]);
const templateOptions = computed(() => [
  { label: "未选择模板", value: "" },
  ...templates.value.map((t) => ({ label: t.name, value: t.id })),
]);

async function loadLookups() {
  try {
    const [tplResp, skillResp] = await Promise.all([
      sidecar.client.get("/api/templates"),
      sidecar.client.get("/api/skills"),
    ]);
    templates.value = tplResp.data.templates ?? [];
    skills.value = skillResp.data.skills ?? [];
  } catch (e: any) {
    toast.error(`无法加载模板 / Skill：${e?.message ?? e}`);
  }
}

// V1 设计稿示例 articleBlocks / assembledBlocks / SampleBlock interface 都已
// 清空 —— 模板没选时显示「选择模板后这里会显示组装预览」，选了模板还没采
// 样时显示「点击开始采样填充内容」，等真实 plan.results 回来再渲染。

// kind → icon name + display label + accent color。V1 的 KIND_META。
const KIND_META: Record<string, { i: string; l: string; c: string }> = {
  heading: { i: "tag" as any, l: "标题", c: "var(--ink)" },
  paragraph: { i: "fileText", l: "段落", c: "var(--ink-2)" },
  numbered_list: { i: "sliders", l: "编号清单", c: "var(--ink-2)" },
  hero_brand: { i: "skills", l: "主推款", c: "var(--primary)" },
  competitor_pool: { i: "library", l: "产品池", c: "var(--primary)" },
  literal: { i: "copy", l: "原文照写", c: "var(--ink-2)" },
  test_framework: { i: "library", l: "测评框架", c: "var(--green-deep)" },
};

// 选中的左侧 slot
const selectedSlot = ref<string>("");

// ── 真实 plan + template 组合成"V1 双栏"渲染所需的行数据 ────────────
// 形状刻意对齐 SampleBlock，这样下面 v-for 模板可以原样复用，无需为
// 真实数据另写一份。label 从 template.blocks 按 block_id join 取；
// template 还没加载完时回退到 KIND_META 的 kind 名，保证至少能渲染。
interface AssemblyRow {
  id: string;
  kind: string;
  label: string;
  hint: string;
  status: "polished" | "draft" | "empty";
  words: number;
  content?: string;
  draft?: string;
  rerollable: boolean;
}

// 哪些 kind 是可重新随机的（与 csm_core.assembler.reroll 的 source map
// 保持一致：只有从 vault 采样的 kind 才有候选池可换；heading/literal/
// hero_brand/test_framework 是模板/数据库里硬编码的，重随无意义）。
const REROLLABLE_KINDS = new Set<string>([
  "paragraph",
  "numbered_list",
  "competitor_pool",
]);

const assemblyRows = computed<AssemblyRow[]>(() => {
  const results = (article.plan?.results ?? []) as any[];
  if (!Array.isArray(results) || results.length === 0) return [];

  // template.blocks 按 id 索引出 label（递归进 children）。
  const labelById = new Map<string, string>();
  function indexTplBlocks(blocks: any[]): void {
    for (const b of blocks) {
      // ParagraphBlock/NumberedListBlock/CompetitorPoolBlock/TestFrameworkBlock
      // 有 label；HeadingBlock 用 text；HeroBrandBlock 用 title；LiteralBlock 用 text。
      const l = b.label || b.text || b.title || "";
      if (b.id) labelById.set(b.id, l);
      if (Array.isArray(b.children)) indexTplBlocks(b.children);
    }
  }
  indexTplBlocks((article.template?.blocks ?? []) as any[]);

  // plan.results 扁平化（含 children），保持顺序。
  function flatten(rs: any[]): any[] {
    const out: any[] = [];
    for (const r of rs) {
      out.push(r);
      if (Array.isArray(r.children) && r.children.length) {
        out.push(...flatten(r.children));
      }
    }
    return out;
  }

  return flatten(results).map((r) => {
    let content = "";
    if (typeof r.text === "string" && r.text) {
      content = r.text;
    } else if (Array.isArray(r.picks) && r.picks.length) {
      content = r.picks
        .map((p: any) => (typeof p?.text === "string" ? p.text : ""))
        .filter(Boolean)
        .join("\n\n");
    }
    const words = content.length;
    const status: AssemblyRow["status"] = content ? "draft" : "empty";
    const fallbackLabel = KIND_META[r.kind]?.l ?? r.kind;
    return {
      id: r.block_id,
      kind: r.kind,
      label: labelById.get(r.block_id) || fallbackLabel,
      hint: "尚未采样",
      status,
      words,
      content,
      draft: content,
      rerollable: REROLLABLE_KINDS.has(r.kind),
    };
  });
});

// 当前正在重随的 slot id —— 用于按钮 loading 态 + 全局互斥（同一时间
// 只允许一个 slot 在重随，避免后端 plan 状态被并发覆盖）。
const rerollingSlot = ref<string | null>(null);

async function rerollSlot(blockId: string) {
  if (rerollingSlot.value) return;  // 互斥
  rerollingSlot.value = blockId;
  try {
    const ok = await article.rerollSlot(blockId);
    if (ok) {
      toast.success("已重随这一段");
    } else {
      toast.warn("没有可重随的候选");
    }
  } catch (e: any) {
    const msg = String(e?.message ?? e);
    if (msg.includes("exhausted") || msg.includes("no more candidates")) {
      toast.warn("候选池已抽干 — 没有更多变体可换");
    } else if (msg.includes("unknown job_id")) {
      toast.warn("生成记录已过期 — 请先重新起飞");
    } else {
      toast.error(`重随失败：${msg}`);
    }
  } finally {
    rerollingSlot.value = null;
  }
}

// 已采样个数（status !== empty）—— 头部 "x/y 已采样"
const sampledCount = computed(
  () => assemblyRows.value.filter((b) => b.status !== "empty").length,
);

// selectedSlot 自动跟随 —— assemblyRows 第一次有数据 / 当前选中失效时，
// 默认选第一行的第一个非 heading slot（heading 在右侧预览里被 filter
// 掉，选中它没意义）。
watch(
  () => assemblyRows.value.map((r) => r.id).join("|"),
  (joinedIds) => {
    const ids = joinedIds ? joinedIds.split("|") : [];
    if (ids.length === 0) return;
    if (ids.includes(selectedSlot.value)) return;
    const firstNonHeading = assemblyRows.value.find((r) => r.kind !== "heading");
    selectedSlot.value = firstNonHeading?.id ?? ids[0];
  },
  { immediate: true },
);

// SAMPLE_BLOCKS 已清空：原本由 SAMPLE_BLOCKS 拼出的 SAMPLE_DRAFT_TEXT /
// SAMPLE_FINAL_TEXT 都是空串，直接删掉；占位标题给一个通用值即可。
const SAMPLE_TITLE = "未命名文章";

// ── 示例正文 / 标题候选 / 查重 / 密度 ────────────────────────
// V1 设计稿示例数据，发布前清空保留空状态 —— 用户起飞后由真实 article store
// 接管；演示按钮（生成标题候选 / 查重 / 关键词密度）在 isDemoMode 下不再
// 注入假数据。SAMPLE_VARIATIONS 保留一项空占位，避免下游模板访问
// SAMPLE_VARIATIONS[sampleIndex] 时下标越界。
const SAMPLE_VARIATIONS: { title: string; draft: string; final: string }[] = [
  { title: SAMPLE_TITLE, draft: "", final: "" },
];

const SAMPLE_TITLE_CANDIDATES: string[] = [];

const SAMPLE_DEDUP_REPORT = {
  duplicate_ratio: 0,
  duplicate_chars: 0,
  text_length: 0,
  top_matches: [] as Array<{
    source_path: string;
    source_title: string;
    overlap_chars: number;
    overlap_ratio: number;
  }>,
  hits: [] as Array<{
    start: number;
    end: number;
    source_path: string;
    source_title: string;
    text: string;
    source_excerpt: string;
  }>,
};

const SAMPLE_DENSITY = { count: 0, density: 0 };

// V1 顺序：组装 → 初稿 → 成稿。和 V1 的 segmented control 一致。
type Tab = "assembly" | "draft" | "final";
const activeTab = ref<Tab>("assembly");

async function takeoff() {
  if (!keyword.value.trim()) return;
  if (!templateId.value) {
    toast.warn("请选择模板");
    return;
  }
  // 起飞 = 只做"随机组装出初稿"。AI 整篇润色由用户在初稿 tab 手动点
  // "整篇润色"触发，避免一把梭直接出成稿、绕过用户检查环节。
  // angle/title 从 query 重建（home 起飞条带过来）；空 → 不传 = 今天行为。
  await article.submit({
    keyword: keyword.value.trim(),
    template_id: templateId.value,
    skill_id: skillId.value || undefined,
    seed: seed.value,
    draft_only: true,
    ...(angle.value ? { angle: angle.value } : {}),
    ...(title.value.trim() ? { title: title.value.trim() } : {}),
    // skill 链非空才传 —— 空链 = 退回单 skill_id（零回归）。
    ...(skillChain.value.length > 0 ? { skill_chain: skillChain.value } : {}),
  });
  // 顺便用 AI 拉一组标题候选，让用户在初稿 tab 里就能挑标题。这是
  // 整个流程里第一次 LLM 调用。失败不影响初稿展示，仅 toast 提示。
  article.fetchTitleCandidates().catch(() => {});
}

// ── Demo 模式状态 ──────────────────────────────────────────
// 没有真实 lastRequest 时（用户还没在 home 起飞过），各按钮都走
// 演示行为：填示例数据 / 跑假进度 / 切示例文本。
const isDemoMode = computed(() => !article.lastRequest);
const sampleIndex = ref(0);

async function rerun() {
  if (article.lastRequest) {
    // 真实模式：调用 store 的 rerun（会重新提交 generate 请求）
    await article.rerun();
    return;
  }
  // 演示模式：循环切到下一套示例文本
  sampleIndex.value = (sampleIndex.value + 1) % SAMPLE_VARIATIONS.length;
  toast.success(`已切换到示例 ${sampleIndex.value + 1} / ${SAMPLE_VARIATIONS.length}`);
}

// 清空 + 跳回首页 —— 不论真实还是 demo 都直接重置 store + push home
function clearAll() {
  article.$reset();
  panelMode.value = "checks";
  sampleIndex.value = 0;
  router.push({ name: "home" });
}

// ── 整篇润色（含 demo 模式弹窗）───────────────────────────────
const polishing = ref(false);
const polishProgress = ref(0); // 0–100 给 demo 模态用
const polishStage = ref<string>("");
const POLISH_STAGES = [
  "解析正文结构…",
  "应用 Skill 风格…",
  "句法重写…",
  "段落质感润色…",
  "校对收口…",
];

async function polishAll() {
  // 真实 finalize 进行中（isRunning）或 demo 动画中（polishing）都防重入。
  if (article.isRunning || polishing.value) return;

  if (article.lastRequest && article.draftText.trim()) {
    // 真实模式：整篇润色 = finalize（SSE 流式，注入+角度+链）。
    // 进度由 overallProgress(isFinalizing) + 成稿区逐 pass 卡呈现；
    // 切成稿 tab + 成功/失败提示由 watch(article.status) 统一处理
    // （finalize 流式早返回，这里不能同步判 status）。
    await article.finalize();
    return;
  }

  // Demo 模式：阻塞模态 + 假 5 阶段动画（无 lastRequest 时）。
  polishing.value = true;
  polishProgress.value = 0;
  polishStage.value = POLISH_STAGES[0];
  // Demo 模式：模拟 5 阶段进度，每段 ~700ms
  await new Promise<void>((resolve) => {
    const total = POLISH_STAGES.length;
    let stage = 0;
    const tick = () => {
      polishStage.value = POLISH_STAGES[stage];
      const start = (stage / total) * 100;
      const end = ((stage + 1) / total) * 100;
      let p = start;
      const id = setInterval(() => {
        p += (end - start) / 14;
        if (p >= end) {
          clearInterval(id);
          polishProgress.value = end;
          stage += 1;
          if (stage >= total) {
            polishProgress.value = 100;
            resolve();
          } else {
            tick();
          }
        } else {
          polishProgress.value = p;
        }
      }, 50);
    };
    tick();
  });

  // 展示 100% 一拍后再关闭
  await new Promise((r) => setTimeout(r, 350));
  polishing.value = false;
  polishProgress.value = 0;
  polishStage.value = "";
  toast.success("演示：整篇润色完成");
}

// ── 全局进度（4 段流程）──────────────────────────────────────────
// 把 sidecar generate job 的进度（仅覆盖"组装"环节）和"整篇润色"
// 这一步 拼成一条 0-100% 的"整篇文章流程"进度。原本进度卡只看
// article.status，draft_only 模式下 generate job 一完成进度就跳
// 100% —— 但其实只完成了 1/4 流程（组装），用户看着以为成稿就绪
// 实际还得点润色。这里改成：
//   0-50%   组装中（generate job 跑 stage 0-3）
//   50%     组装完成、初稿就绪（status=done, finalText 还空）
//   50-90%  整篇润色中（无可靠 polishProgress，固定 75% 占位）
//   100%    成稿完成（finalText 有值）
const overallProgress = computed<number>(() => {
  // ⚠ ProgressBar expects a 0–1 ratio (see ProgressBar.vue: `Math.min(1, value)`).
  // 之前这里返回 0-100，>1 的值都被 clamp 到 100% —— 所以 step 2/4
  // 时进度条几乎"满格"显示，跟左侧的 2/4 计数对不上。改回 0-1。
  if (article.status === "idle" || article.status === "error") return 0;
  // running 期间分两态：finalize（润色）固定 75% 占位；起飞按 stage 走 0-50%。
  if (article.status === "running") return article.isFinalizing ? 0.75 : article.progress * 0.5;
  // status === "done"
  if (article.finalText.trim()) return 1;
  return 0.5; // 初稿就绪、等待润色
});

const overallLabel = computed<string>(() => {
  if (article.status === "idle") return "暂无生成任务";
  if (article.status === "error") return article.error ?? "生成失败";
  if (article.status === "running") return article.isFinalizing ? "AI 润色中…" : (article.currentStage ?? "排队中…");
  if (article.finalText.trim()) return "已完成";
  return "初稿就绪 · 待润色";
});

// 右上角的 "x / 4" 步骤计数。step 取值含义：
//   1 组装中 / 2 初稿就绪 / 3 润色中 / 4 成稿完成
const overallStep = computed<number | null>(() => {
  if (article.status === "idle" || article.status === "error") return null;
  if (article.status === "running") return article.isFinalizing ? 3 : 1;
  if (article.finalText.trim()) return 4;
  return 2;
});

/**
 * 质检报告卡的视图模式 —— 默认 "checks" 渲染六项检查；点击底部
 * "查重"/"标题候选" 时切到对应的子视图，整张卡内部 swap，不再用
 * Teleport 弹整页 drawer。点回另一个 mode 或顶部"返回"按钮回到列表。
 */
type PanelMode = "checks" | "dedup" | "titles" | "density";
const panelMode = ref<PanelMode>("checks");

/**
 * 切到关键词密度详情页 —— 跟 openDedup / openTitleCandidates 同语义。
 * 底部「算密度」按钮 + 一级页"关键词密度"卡 click 都走这里。还没算
 * 过密度时顺便触发 refreshDensity 拉数据（function 声明会 hoist，所
 * 以 refreshDensity 在下面定义不影响这里调用）。
 */
async function openDensity() {
  panelMode.value = "density";
  if (!article.keywordDensity) {
    await refreshDensity();
  }
}

async function openTitleCandidates() {
  panelMode.value = "titles";
  if (article.titleCandidates.length === 0) {
    if (isDemoMode.value) {
      // Demo 模式：直接灌示例候选，不打 sidecar
      article.titleCandidates = [...SAMPLE_TITLE_CANDIDATES];
    } else {
      await article.fetchTitleCandidates();
    }
  }
}
function pickTitle(t: string) {
  article.title = t;
  panelMode.value = "checks";
  toast.success("标题已替换");
}

async function openDedup() {
  panelMode.value = "dedup";
  if (article.dedupReport) return;
  if (isDemoMode.value) {
    // Demo 模式：填示例查重报告
    article.dedupReport = SAMPLE_DEDUP_REPORT;
    return;
  }
  if (!article.finalText.trim()) {
    toast.warn("没有正文可查重");
    return;
  }
  await article.runDedup(article.finalText, "history");
}
async function refreshDedup() {
  if (isDemoMode.value) {
    article.dedupReport = SAMPLE_DEDUP_REPORT;
    toast.success("演示：已重新计算");
    return;
  }
  await article.runDedup(article.finalText, "history");
}

// 算密度按钮 —— demo 模式直接灌示例，真实模式调 store action
async function refreshDensity() {
  if (isDemoMode.value) {
    article.keywordDensity = { ...SAMPLE_DENSITY };
    toast.success(
      `关键词出现 ${SAMPLE_DENSITY.count} 次，密度 ${(SAMPLE_DENSITY.density * 100).toFixed(1)}%`,
    );
    return;
  }
  await article.refreshDensity();
}

type ExportFormat = "markdown" | "docx" | "txt";
const showExportModal = ref(false);
const exportFormat = ref<ExportFormat>("markdown");

// 事实核对审查面板 —— 生成被 Plan 3 硬门禁拦下（factcheck.blocked）时自动弹，
// 列违规项给用户改文案/勾放行后重核导出。未拦时 factcheck=null，导出走原弹窗。
const showFactcheck = ref(false);
watch(
  () => article.factcheck?.blocked,
  (blocked) => {
    if (blocked) showFactcheck.value = true;
  },
);
const showLint = ref(false);
// 成稿被禁区 lint 命中（lintBlocking false→true）自动弹面板。
watch(() => article.lintBlocking, (b, prev) => { if (b && !prev) showLint.value = true; });
// 导出按钮：factcheck 门禁 > lint 门禁 > 常规导出弹窗。
function onExportClick() {
  if (article.factcheck?.blocked) { showFactcheck.value = true; return; }
  if (article.lintBlocking) { showLint.value = true; return; }
  showExportModal.value = true;
}

const EXPORT_OPTIONS: {
  value: ExportFormat;
  label: string;
  sublabel: string;
  icon: string;
}[] = [
  { value: "markdown", label: "Markdown", sublabel: ".md · 含 frontmatter", icon: "fileText" },
  { value: "docx", label: "Word 文档", sublabel: ".docx · 标题层级保留", icon: "fileText" },
  { value: "txt", label: "纯文本", sublabel: ".txt · 无格式", icon: "fileText" },
];

// 浏览器端直接下载 —— demo 模式（无 lastRequest）或 txt 走这条路。
// 后端只支持 markdown/docx，所以 txt 永远走前端；demo 模式下也走前端
// 因为后端 export 路由要求 lastRequest.keyword。
function clientDownload(filename: string, content: string, mime: string) {
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(url), 0);
}

function safeFilenameStem(): string {
  const variant = SAMPLE_VARIATIONS[sampleIndex.value];
  const title = (article.title || variant.title || "article")
    .replace(/[\\/:*?"<>|]/g, "")
    .slice(0, 60);
  return title || "article";
}

async function doExport() {
  const fmt = exportFormat.value;
  const variant = SAMPLE_VARIATIONS[sampleIndex.value];
  const title = article.title || variant.title;
  const body = article.finalText || variant.final;
  const stem = safeFilenameStem();
  const useClient = fmt === "txt" || !article.lastRequest || !article.finalText.trim();

  try {
    if (useClient) {
      if (fmt === "markdown") {
        const md = body.startsWith("# ") ? body : `# ${title}\n\n${body}`;
        clientDownload(`${stem}.md`, md, "text/markdown;charset=utf-8");
      } else if (fmt === "txt") {
        // 剥掉 markdown 标记符号
        const plain = body
          .replace(/^#{1,6}\s+/gm, "")
          .replace(/\*\*([^*]+)\*\*/g, "$1")
          .replace(/\*([^*]+)\*/g, "$1");
        clientDownload(`${stem}.txt`, `${title}\n\n${plain}`, "text/plain;charset=utf-8");
      } else {
        // demo 模式不支持本地生成 docx —— 退回 markdown
        const md = body.startsWith("# ") ? body : `# ${title}\n\n${body}`;
        clientDownload(`${stem}.md`, md, "text/markdown;charset=utf-8");
        toast.info("演示模式下 Word 导出降级为 Markdown");
      }
      toast.success("已导出");
      showExportModal.value = false;
      return;
    }
    const r = await article.exportArticle({
      format: fmt as "markdown" | "docx",
      include_dedup_report: false,
    });
    if (r) {
      toast.success(`已导出：${r.document}`);
      showExportModal.value = false;
    }
  } catch (e: any) {
    toast.error(`导出失败：${e?.response?.data?.detail ?? e?.message ?? e}`);
  }
}

// wordCount 字数 KPI 已下线（质检报告里不再展示），目前没有别处引用，
// 用 void(0) 占位避免 lint 报"未使用"。如果未来导出端要拼字数，再恢复。
// const wordCount = ...;

// 编辑器内显示的正文 —— 拼上 H1 标题首行；如果 finalText/draftText
// 已经含 # 开头的标题，就不重复 prepend。用户编辑后保存回 store 时
// 直接整段（含标题）写入 article.finalText，标题留在 markdown 里。
function withTitle(body: string, title: string): string {
  if (body.startsWith("# ")) return body;
  return `# ${title}\n\n${body}`;
}
const draftEditorValue = computed(() => {
  const variant = SAMPLE_VARIATIONS[sampleIndex.value];
  const title = article.title || variant.title;
  const body = article.draftText || variant.draft;
  return withTitle(body, title);
});
const finalEditorValue = computed(() => {
  const variant = SAMPLE_VARIATIONS[sampleIndex.value];
  const title = article.title || variant.title;
  const body = article.finalText || variant.final;
  return withTitle(body, title);
});

const dedupRatio = computed(() => {
  if (!article.dedupReport) return null;
  return article.dedupReport.duplicate_ratio;
});

// 模板/Skill 名称（用于 header chips）
const templateName = computed(() => {
  if (!templateId.value) return "";
  return templates.value.find((t) => t.id === templateId.value)?.name ?? "";
});
const skillName = computed(() => {
  if (!skillId.value) return "";
  return skills.value.find((s) => s.id === skillId.value)?.name ?? "";
});

// V1 风格的检查项（基于真实数据动态填充；缺失数据用 "—" 占位）
interface CheckItem {
  label: string;
  value: string;
  desc: string;
  pass: boolean;
  tone: "ok" | "warn" | "primary";
}
const checkItems = computed<CheckItem[]>(() => {
  const items: CheckItem[] = [];

  // 字数卡已下线 —— 用户反馈说没决策价值，重复率/标题候选/关键词密度
  // 才是真正用得上的质检维度。`wordCount` 仍然在 store 里维护，下游
  // 别处（导出文件名变量等）还会用到。

  // 重复率（vault / history）
  if (dedupRatio.value !== null) {
    const pct = (dedupRatio.value * 100).toFixed(1);
    const safe = dedupRatio.value < 0.3;
    items.push({
      label: "重复率（历史）",
      value: `${pct}%`,
      desc: safe ? "在 30% 阈值内，安全" : "高于 30%，建议润色",
      pass: safe,
      tone: safe ? "ok" : "warn",
    });
  } else {
    items.push({
      label: "重复率",
      value: "—",
      desc: "点击右侧查询",
      pass: false,
      tone: "warn",
    });
  }

  // 标题候选
  const tc = article.titleCandidates.length;
  items.push({
    label: "标题候选",
    value: tc > 0 ? `${tc} 个` : "—",
    desc: tc > 0 ? `AI 已生成 ${tc} 个备选标题` : "尚未生成候选",
    pass: tc > 0,
    tone: tc > 0 ? "primary" : "warn",
  });

  // 关键词密度
  const kd = article.keywordDensity;
  if (kd) {
    const pct = (kd.density * 100).toFixed(1);
    const ok = kd.density >= 0.015 && kd.density <= 0.04;
    items.push({
      label: "关键词密度",
      value: `${pct}%`,
      desc: ok ? "在 1.5%-4% 区间" : "建议 1.5%-4%",
      pass: ok,
      tone: ok ? "ok" : "warn",
    });
  } else {
    items.push({
      label: "关键词密度",
      value: "—",
      desc: "尚未计算",
      pass: false,
      tone: "warn",
    });
  }

  // 第 7 项：禁区 lint
  items.push({
    label: "禁区",
    value: article.lint ? (article.lintBlocking ? `${article.lintUnresolved} 处` : "无") : "—",
    desc: article.lintBlocking ? "有未处理违规，点导出查看" : (article.lint ? "已清/已放行" : "成稿后自动检查"),
    pass: !article.lintBlocking,
    tone: article.lintBlocking ? "warn" : "ok",
  });

  return items;
});
// _passCount kept as a derived helper in case the UI brings back a
// "通过 X / 总数 Y" pill. Currently unused — prefix with _ to silence
// vue-tsc unused-var warning without losing the intent.
const _passCount = computed(() => checkItems.value.filter((c) => c.pass).length);
void _passCount;

/**
 * 一级页只保留"重复率·历史"和"关键词密度"两张大卡（用户简化设计）；
 * 每条带 key 让 click 时分流到 openDedup / openDensity。标题候选不
 * 进卡片，走底部「标题候选」按钮去二级页。
 */
const primaryChecks = computed<
  Array<{
    key: "dedup" | "density";
    label: string;
    value: string;
    pass: boolean;
    tone: "ok" | "warn" | "primary";
  }>
>(() => {
  const out: Array<{
    key: "dedup" | "density";
    label: string;
    value: string;
    pass: boolean;
    tone: "ok" | "warn" | "primary";
  }> = [];
  // 重复率·历史
  if (dedupRatio.value !== null) {
    const pct = (dedupRatio.value * 100).toFixed(1);
    const safe = dedupRatio.value < 0.3;
    out.push({
      key: "dedup",
      label: "重复率 · 历史",
      value: `${pct}%`,
      pass: safe,
      tone: safe ? "ok" : "warn",
    });
  } else {
    out.push({
      key: "dedup",
      label: "重复率 · 历史",
      value: "—",
      pass: false,
      tone: "warn",
    });
  }
  // 关键词密度
  const kd = article.keywordDensity;
  if (kd) {
    const pct = (kd.density * 100).toFixed(1);
    const ok = kd.density >= 0.015 && kd.density <= 0.04;
    out.push({
      key: "density",
      label: "关键词密度",
      value: `${pct}%`,
      pass: ok,
      tone: ok ? "ok" : "warn",
    });
  } else {
    out.push({
      key: "density",
      label: "关键词密度",
      value: "—",
      pass: false,
      tone: "warn",
    });
  }
  return out;
});
const primaryPassCount = computed(
  () => primaryChecks.value.filter((c) => c.pass).length,
);

onMounted(async () => {
  try {
    await whenReady();
    if (!cfg.data) await cfg.load();
    await loadLookups();
  } catch {
    /* useSidecarReady reports it */
  }

  const qk = (route.query.keyword as string) ?? "";
  if (qk) keyword.value = qk;
  const qt = (route.query.template_id as string) ?? "";
  if (qt) templateId.value = qt;
  const qs = (route.query.skill_id as string) ?? "";
  if (qs) skillId.value = qs;

  // 角度 + 标题从 query 重建（home 起飞条扁平带过来）。拉一次词表让
  // header chip 能把卖点 key 显示成 label；失败静默（chip 退回 key）。
  angle.value = rebuildAngleFromQuery();
  title.value = ((route.query.title as string) ?? "").trim();
  skillChain.value = rebuildChainFromQuery();
  if (angle.value) article.fetchAngleTaxonomy();

  if (!templateId.value && templates.value[0]) {
    templateId.value = templates.value[0].id;
  }
  if (!skillId.value && cfg.data?.preferred_skill_id) {
    skillId.value = cfg.data.preferred_skill_id;
  }

  // 带 ?keyword=... 进来 = home 发起的新一次起飞。这里清掉残留的
  // error 状态（不然 watcher 因为 status 没变 → 不会触发 alert，用户
  // 看到的就是一片空白的创作区）。reset 之后 status 一定是 "idle"，
  // takeoff 才能跑。
  if (qk && article.status === "error") {
    article.$reset();
  }

  // 自动起飞：home 带着 ?keyword=... 跳过来时直接发起生成。
  // 此前由顶部的输入条触发，现在那块 UI 已删，所以由 mount 阶段
  // 接管。query 里没 keyword 就保持 idle，等用户回 home 起飞。
  if (
    qk &&
    article.status === "idle" &&
    !article.finalText &&
    templateId.value
  ) {
    takeoff();
  } else if (article.status === "error" && !qk) {
    // 用户从 leftnav 直接点进创作区但 store 还残留 error —— 同步弹一
    // 次 alert + 回首页（场景：上次失败，没主动 reset，用户切到别的
    // tab 再切回来）。
    const choice = await failureAlert({
      title: "上次文章生成失败",
      message: "你的上次起飞没能完成。可以回首页重新输入关键词。",
      detail: article.error ?? "",
      retryable: Boolean(article.lastRequest),
    });
    if (choice === "retry" && article.lastRequest) {
      article.rerun();
    } else {
      article.$reset();
      router.push({ name: "home" });
    }
  }
});

onUnmounted(() => {
  article.cancel();
});

watch(
  () => article.status,
  async (s, prev) => {
    // done 分支按结果三分（finalize 流式早返回，切 tab/toast 必须在这里
    // 等真正 done 才做，不能在 polishAll 里同步判 status）：
    if (s === "done") {
      if (article.factcheck?.blocked) {
        // 被事实核对拦下：审查面板接管，不切 tab。
      } else if (article.finalText.trim()) {
        // 整篇润色（finalize）成稿就绪 → 切成稿 tab + 成功提示。
        activeTab.value = "final";
        toast.success("整篇润色完成");
      } else {
        // draft_only 起飞完成、finalText 还空 → 停初稿 tab 让用户检查后再润色。
        activeTab.value = "draft";
      }
    }
    // 失败时不在创作区里显示红条；直接弹全局失败 modal + 回首页。
    // 注意 prev !== "error" 是去重：watcher 在 reactive 重置时也可
    // 能再触发一次 (status 重新等于 "error")，防止弹两次。
    if (s === "error" && prev !== "error") {
      const choice = await failureAlert({
        title: "文章生成失败",
        message: "本次生成没能成功完成。可以检查模板配置或素材后重试。",
        detail: article.error ?? "",
        retryable: Boolean(article.lastRequest),
      });
      // 用户点重试：留在创作区，重新发起一次生成。
      // 关闭：回首页，清掉错误状态避免下次进创作区还显示 error。
      if (choice === "retry" && article.lastRequest) {
        article.rerun();
      } else {
        article.$reset();
        router.push({ name: "home" });
      }
    }
  },
);

const TAB_DEFS: Array<{ id: Tab; label: string; icon: string }> = [
  { id: "assembly", label: "组装", icon: "library" },
  { id: "draft", label: "初稿", icon: "edit" },
  { id: "final", label: "成稿", icon: "wand" },
];

const tabSectionLabel = computed(() => {
  // tab section label 简化为单词（用户反馈 "· 框架 + 采样" 类副词太繁琐）
  if (activeTab.value === "assembly") return "组装";
  if (activeTab.value === "draft") return "初稿";
  return "成稿";
});

</script>

<template>
  <!--
    根用 h-full + flex-col：和 HomeView 同款收口策略，整页不滚，由内部
    组件自行 overflow-y-auto。
  -->
  <!--
    根用 h-full + flex-col：和 HomeView 同款收口策略，整页不滚，由
    内部组件自行 overflow-y-auto。
    注：曾尝试加 padding 14px 给 main editor card 留 box-shadow 的
    visible 空间，但用户希望 card 保持原位 —— 改方案为去掉 outer
    shadow、用 border + 顶部 inset 高光模拟弱立体感（详见
    :deep(section) 的 box-shadow 实现）。
  -->
  <div class="flex h-full flex-col" :style="{ gap: '14px' }">
    <!--
      ── V1 风格 header ─────────────────────────────────────────
      `← 返回工作台 | 分隔线 | 模板 chip | Skill chip | 字数 · 重复率`
      不再有起飞条 —— 起飞入口在 home（CreateArticleHero），这里只展示已起飞
      文章。模板/Skill chips 始终显示（即便未起飞），保持 V1 设计稿的
      视觉骨架；模板/Skill 在 mount 时自动载入第一个作为默认。
    -->
    <div class="flex flex-shrink-0 items-center justify-between">
      <div class="flex items-center gap-3">
        <button
          type="button"
          class="inline-flex items-center gap-1.5 text-[12px] transition hover:text-ink"
          :style="{ color: 'var(--ink-3)' }"
          @click="router.push({ name: 'home' })"
        >
          <Icon name="arrowLeft" :size="14" />
          返回工作台
        </button>
        <span :style="{ width: '1px', height: '18px', background: 'var(--line-2)' }" />
        <Pill>{{ templateName || "未选择模板" }}</Pill>
        <!-- 链 chip 在场时由它呈现 skill；避免和单 skill pill 重复/误标「默认 Skill」 -->
        <Pill v-if="!chainChipText" tone="primary">{{ skillName || "默认 Skill" }}</Pill>
        <!--
          角度 chip —— 起飞时带了角度（人群/卖点/语调任一）才显示，
          文案如「铲屎官 · 防缠绕 · 口语」。提示用户本篇是带角度生成的。
        -->
        <span
          v-if="angleChipText"
          data-angle-chip
          class="inline-flex items-center gap-1 text-[11px] font-medium"
          :style="{
            background: 'var(--primary-soft)',
            color: 'var(--primary-deep)',
            padding: '3px 9px',
            borderRadius: 'var(--radius-pill)',
          }"
          :title="`写作角度：${angleChipText}`"
        >
          <Icon name="sliders" :size="11" />
          {{ angleChipText }}
        </span>
        <!--
          skill 链 chip —— 起飞带了链（passes 非空）才显示，文案如
          「人设 → 去AI味 → 小红书」。单 skill 旧路径无 passes → 不渲染。
        -->
        <span
          v-if="chainChipText"
          data-chain-chip
          class="inline-flex items-center gap-1 text-[11px] font-medium"
          :style="{
            background: 'var(--primary-soft)',
            color: 'var(--primary-deep)',
            padding: '3px 9px',
            borderRadius: 'var(--radius-pill)',
          }"
          :title="`润色链：${chainChipText}`"
        >
          <Icon name="skills" :size="11" />
          {{ chainChipText }}
        </span>
        <!--
          字数统计 (wordCount) 在右侧检查面板里有完整 KPI 卡，header
          上的「0 字」短文本和它重复，初次进入又总是 0 看着尴尬，去掉。
          重复率仍只在检查面板显示，header 保持模板/Skill 两个 chip。
        -->
        <span
          v-if="dedupRatio !== null"
          class="text-[11px]"
          :style="{ color: 'var(--ink-3)' }"
        >
          重复率 {{ (dedupRatio * 100).toFixed(1) }}%
        </span>
      </div>
    </div>

    <!--
      失败弹窗代替原来的红色 banner —— 生成失败时不再在创作区里显示，
      由 watch(article.status) 在 setup 里调 failureAlert 弹全局模态，
      模态 + router.push("home") 一起执行，用户不会卡在半成品页面。
    -->

    <!-- ── 主内容行：左编辑卡 + 右 288px 检查面板 ────────────────── -->
    <!-- gap 14（原 12，+2 让左右两块距离加大）-->
    <div class="flex min-h-0 flex-1" :style="{ gap: '14px' }">
      <!-- LEFT — editor card -->
      <Card padless class="flex min-w-0 flex-1 flex-col overflow-hidden">
        <!-- tab bar：左 section 文字 + 右 segmented pill 控件 -->
        <div
          class="flex flex-shrink-0 items-center justify-between"
          :style="{ padding: '10px 20px', borderBottom: '1px solid var(--line)' }"
        >
          <div
            class="text-[10.5px] uppercase"
            :style="{ color: 'var(--ink-3)', letterSpacing: '1.5px' }"
          >
            {{ tabSectionLabel }}
          </div>
          <!-- segmented pill：组装 / 初稿 / 成稿 -->
          <div
            class="flex items-center"
            :style="{
              background: 'var(--card-2)',
              borderRadius: '999px',
              padding: '3px',
            }"
          >
            <button
              v-for="t in TAB_DEFS"
              :key="t.id"
              type="button"
              class="inline-flex items-center transition"
              :style="{
                height: '26px',
                padding: '0 12px',
                borderRadius: '999px',
                gap: '4px',
                fontSize: '11px',
                fontWeight: activeTab === t.id ? 600 : 500,
                background: activeTab === t.id ? 'var(--card-white)' : 'transparent',
                color: activeTab === t.id ? 'var(--ink)' : 'var(--ink-3)',
                border: activeTab === t.id ? '1px solid var(--line)' : 'none',
              }"
              @click="activeTab = t.id"
            >
              <Icon :name="t.icon" :size="10" />
              {{ t.label }}
            </button>
          </div>
        </div>

        <!--
          整篇润色 inline 提示已被移除；现在用 Teleport 居中模态展示
          阶段进度（见模板末尾的 polish progress modal）。
        -->

        <!--
          生成进度条已迁到右侧检查面板顶部「进度」卡 —— 编辑区不再夹
          一条横向进度横幅占走可读高度，进度状态作为属性栏的一行 KPI
          类信息呆在右侧更对应"读数据"的语义。
        -->

        <!-- 内容区 —— 占满剩余高度 -->
        <div class="flex min-h-0 flex-1 flex-col">
          <!-- ── 组装预览 ────────────────────────────────────────
            真实 plan 存在时（已起飞）→ 直接走 AssemblyTree（带重随）。
            否则走 V1 设计稿样的两栏示例：左侧模板框架 slot 列表 + 右侧
            组装预览块卡片，让用户在起飞前就能看到成品形态。
          -->
          <div v-if="activeTab === 'assembly'" class="flex min-h-0 flex-1">
            <!--
              真实 plan 存在 → 复用下面的 V1 双栏样式（左 slot 列表 + 右组装预览）。
              数据来自 assemblyRows（已把 plan.results 和 template.blocks 关联好）。
              旧的简化版 AssemblyTree 已下线，AssemblyTree.vue 组件保留供其他视图
              使用，本视图不再引用。
            -->
            <template v-if="assemblyRows.length === 0">
              <div
                class="flex min-h-0 flex-1 flex-col items-center justify-center text-center"
                :style="{ padding: '40px 24px', color: 'var(--ink-3)' }"
              >
                <!--
                  正在跑 vault scan + assemble_plan（耗时 5-10s 不等）：显示
                  loading 而不是"点击开始采样填充内容"的占位文案。否则用户点完
                  "开始生成"会以为按钮没响应。
                -->
                <template v-if="article.isRunning">
                  <Spinner />
                  <div class="mt-3 font-display text-[14px] font-semibold" :style="{ color: 'var(--ink)' }">
                    {{ article.currentStage ?? "正在采样组装…" }}
                  </div>
                  <div class="mt-1 max-w-[420px] text-[12.5px]">
                    扫描资料库 → 加载模板 → 采样 blocks → 组装预览。完成后这里会展示组装结果。
                  </div>
                </template>
                <template v-else>
                  <div class="font-display text-[16px] font-semibold" :style="{ color: 'var(--ink)' }">
                    {{ templateId ? "点击开始采样填充内容" : "选择模板后这里会显示组装预览" }}
                  </div>
                  <div class="mt-2 max-w-[420px] text-[12.5px]">
                    在顶部输入关键词并选择模板/Skill，点击「开始生成」后会在这里逐块展示组装预览。
                  </div>
                </template>
              </div>
            </template>
            <template v-else>
              <!-- LEFT: 模板框架 slots，300px 固定 -->
              <div
                class="flex-shrink-0 overflow-y-auto"
                :style="{
                  width: '260px',
                  borderRight: '1px solid var(--line)',
                  padding: '16px',
                }"
              >
                <div
                  class="text-[10.5px] uppercase mb-2"
                  :style="{ color: 'var(--ink-3)', letterSpacing: '1.5px' }"
                >
                  模板框架
                </div>
                <!--
                  templateName Pill + "X 个槽位" 子标删除（用户反馈这里
                  跟 header 顶部的模板 chip 重复，不需要再显示一次）。
                -->
                <div class="mb-3" />
                <!--
                  Slot 行：不再渲染圆角小方块图标 —— 设计稿要求只保留
                  序号、双行标题（label + sublabel）和右侧状态色点。
                -->
                <div class="flex flex-col gap-1">
                  <button
                    v-for="(b, i) in assemblyRows"
                    :key="b.id"
                    type="button"
                    class="text-left flex items-center gap-2 transition"
                    :style="{
                      padding: '8px',
                      borderRadius: '10px',
                      background: selectedSlot === b.id ? 'var(--primary-soft)' : 'transparent',
                      border: selectedSlot === b.id ? '1px solid rgba(238,106,42,0.25)' : '1px solid transparent',
                    }"
                    @click="selectedSlot = b.id"
                  >
                    <span
                      class="font-mono text-[10px]"
                      :style="{ color: 'var(--ink-3)', width: '16px' }"
                    >{{ String(i + 1).padStart(2, "0") }}</span>
                    <div class="flex-1 min-w-0">
                      <div class="text-[11.5px] font-semibold truncate">{{ b.label }}</div>
                      <div class="text-[10px] truncate" :style="{ color: 'var(--ink-3)' }">
                        {{ KIND_META[b.kind].l }}
                      </div>
                    </div>
                    <span
                      class="flex-shrink-0"
                      :style="{
                        width: '5px',
                        height: '5px',
                        borderRadius: '50%',
                        background:
                          b.status === 'polished' ? 'var(--green)' :
                          b.status === 'draft' ? 'var(--yellow)' :
                          'var(--line-2)',
                      }"
                    />
                  </button>
                </div>
              </div>
              <!-- RIGHT: 组装预览块 -->
              <div
                class="flex min-w-0 flex-1 flex-col overflow-hidden"
                :style="{ padding: '20px 20px 0' }"
              >
                <div class="flex flex-shrink-0 items-center justify-between mb-4">
                  <div>
                    <div
                      class="text-[10.5px] uppercase"
                      :style="{ color: 'var(--ink-3)', letterSpacing: '1.5px' }"
                    >
                      组装预览
                    </div>
                    <div class="text-[12px] mt-0.5" :style="{ color: 'var(--ink-2)' }">
                      {{ sampledCount }}/{{ assemblyRows.length }} 已采样 · 点击各段可润色或重随
                    </div>
                  </div>
                  <!--
                    "全部重采"：换一套全新组装（等价于右下角的"重新随机"，
                    走 article.rerun → seed+1 重新走 /api/generate）。运行中
                    或正在 reroll 单个 slot 时禁用，避免并发覆盖 plan。
                  -->
                  <Btn
                    variant="ghost"
                    small
                    :disabled="article.isRunning || rerollingSlot !== null"
                    @click="article.rerun()"
                  >
                    <Icon name="refresh" :size="11" />
                    全部重采
                  </Btn>
                </div>
                <div class="min-h-0 flex-1 overflow-y-auto" :style="{ paddingBottom: '20px', paddingRight: '4px' }">
                  <!--
                    Heading 类型的"标题"块在设计稿里不再以独立预览卡呈现
                    （工作台/header 已经显示了文章标题，这里再搞一张
                    巨大 H1 卡片是冗余）。filter 掉它，只保留段落/编号
                    /产品池等真正需要采样的 slot。
                  -->
                  <div class="flex flex-col gap-3">
                    <!--
                      段落卡视觉：背景/边框/阴影/hover/选中全部走 scoped
                      class（assembly-block + selected），inline :style 没
                      办法定义 :hover 状态。选中态在 scoped CSS 里加浅橙
                      底 + 橙色光晕，hover 用普通软阴影。
                    -->
                    <div
                      v-for="b in assemblyRows.filter((x) => x.kind !== 'heading')"
                      :key="b.id"
                      :class="['assembly-block', { selected: selectedSlot === b.id }]"
                      @click="selectedSlot = b.id"
                    >
                      <!--
                        block header：
                          [kind chip] [label] | flex spacer | [润色 btn] [重随 btn]
                        kind chip 占据原图标位置（最左），下面正文与之
                        左对齐。原右侧的 "220 字" 字数统计去掉，换成
                        润色 + 重随两个 icon 按钮。空块（status=empty）
                        没生成内容，按钮也没意义，不渲染。
                      -->
                      <div class="flex items-center gap-2 mb-2">
                        <span
                          class="inline-flex items-center text-[10px] uppercase font-medium"
                          :style="{
                            background: 'var(--card-white)',
                            color: KIND_META[b.kind].c,
                            border: '1px solid var(--line)',
                            padding: '3px 7px',
                            borderRadius: '6px',
                            letterSpacing: '1px',
                          }"
                        >{{ KIND_META[b.kind].l }}</span>
                        <span class="text-[11.5px] font-semibold">{{ b.label }}</span>
                        <span class="flex-1" />
                        <div v-if="b.status !== 'empty'" class="flex items-center gap-1">
                          <button
                            type="button"
                            title="AI 润色"
                            class="inline-flex items-center justify-center transition hover:brightness-95"
                            :style="{
                              width: '26px',
                              height: '26px',
                              borderRadius: '7px',
                              background: 'var(--primary-soft)',
                              color: 'var(--primary-deep)',
                              border: '1px solid rgba(238,106,42,0.2)',
                            }"
                            @click.stop
                          >
                            <Icon name="wand" :size="12" />
                          </button>
                          <button
                            v-if="b.rerollable"
                            type="button"
                            :title="rerollingSlot === b.id ? '正在重随…' : '重随'"
                            :disabled="rerollingSlot !== null"
                            class="inline-flex items-center justify-center transition hover:brightness-95 disabled:opacity-60 disabled:cursor-not-allowed"
                            :style="{
                              width: '26px',
                              height: '26px',
                              borderRadius: '7px',
                              background: 'var(--card-white)',
                              color: 'var(--ink-2)',
                              border: '1px solid var(--line)',
                            }"
                            @click.stop="rerollSlot(b.id)"
                          >
                            <Spinner v-if="rerollingSlot === b.id" :size="11" />
                            <Icon v-else name="refresh" :size="12" />
                          </button>
                        </div>
                      </div>
                      <!-- block content -->
                      <div v-if="b.status === 'empty'"
                        class="flex items-center gap-2"
                        :style="{
                          padding: '14px 12px',
                          borderRadius: '10px',
                          background: 'var(--card-2)',
                          border: '1px dashed var(--line-2)',
                        }"
                      >
                        <span class="text-[11.5px]" :style="{ color: 'var(--ink-3)' }">{{ b.hint }}</span>
                        <span class="flex-1" />
                        <span
                          class="text-[11px] font-medium"
                          :style="{ color: 'var(--primary-deep)' }"
                        >生成 →</span>
                      </div>
                      <!--
                        正文 inline 在段落卡背景上 —— 不加独立白底 box，
                        不加 border。用户最终设计：卡内统一一致背景，
                        正文只靠 font-serif-cn + 字色营造质感。
                      -->
                      <div v-else
                        class="font-serif-cn"
                        :style="{ fontSize: '13.5px', lineHeight: 1.85, color: 'var(--ink-2)' }"
                      >{{ b.draft || b.content }}</div>
                    </div>
                  </div>
                </div>
              </div>
            </template>
          </div>

          <!-- ── 初稿编辑 ─────────────────────────────────────── -->
          <div v-else-if="activeTab === 'draft'" class="flex min-h-0 flex-1 flex-col">
            <div :style="{ padding: '18px 24px 14px' }">
              <div class="flex items-center gap-2 mb-2">
                <span
                  class="inline-flex items-center gap-1.5 text-[10.5px] font-medium"
                  :style="{
                    background: 'rgba(122,155,94,0.12)',
                    color: 'var(--green)',
                    padding: '4px 8px',
                    borderRadius: '999px',
                  }"
                >
                  <span :style="{ width: '5px', height: '5px', borderRadius: '50%', background: 'var(--green)' }" />
                  正在编辑
                </span>
                <span
                  class="text-[10.5px]"
                  :style="{
                    background: 'var(--card-2)',
                    color: 'var(--ink-3)',
                    border: '1px solid var(--line)',
                    padding: '4px 8px',
                    borderRadius: '999px',
                  }"
                >初稿 v1</span>
                <span class="text-[10px]" :style="{ color: 'var(--ink-3)' }">自动保存于 12:34</span>
              </div>
              <!-- 初稿 tab 只显示"初稿 X 字"（用户反馈：成稿字数 + 阅读时间这里冗余） -->
              <div class="flex items-center gap-3 text-[11px]" :style="{ color: 'var(--ink-3)' }">
                <span>初稿 {{ (article.draftText || SAMPLE_VARIATIONS[sampleIndex].draft).length }} 字</span>
              </div>
              <div class="mt-3" :style="{ height: '1px', background: 'var(--line)' }" />
            </div>
            <!--
              白色编辑卡 — V1 同款：white bg + border + radius + padding，
              flex-1 占满剩余高度。白卡本身就是滚动容器，TiptapEditor 的
              host 走 flex:1 撑满白卡内空，所以点击白卡任意位置都能聚焦
              到编辑器（不再像之前那样卡在顶部 240px）。

              初稿和成稿一样可编辑（V1 同设计）。差别只在 store 字段：
              draft → article.draftText，final → article.finalText。
              二者编辑值都内嵌 H1 标题首行。
            -->
            <div class="flex min-h-0 flex-1 flex-col" :style="{ padding: '0 24px 20px' }">
              <div
                class="flex min-h-0 flex-1 flex-col overflow-y-auto"
                :style="{
                  background: '#ffffff',
                  borderRadius: '12px',
                  border: '1px solid var(--line)',
                  padding: '20px 24px',
                }"
              >
                <TiptapEditor
                  :model-value="draftEditorValue"
                  placeholder="起飞后这里会显示初稿。可直接编辑。"
                  :min-height="0"
                  @update:model-value="(v) => (article.draftText = v)"
                />
              </div>
            </div>
          </div>

          <!-- ── 成稿编辑 ─────────────────────────────────────── -->
          <div v-else class="flex min-h-0 flex-1 flex-col">
            <div :style="{ padding: '18px 24px 14px' }">
              <div class="flex items-center gap-2 mb-2">
                <span
                  class="inline-flex items-center gap-1.5 text-[10.5px] font-medium"
                  :style="{
                    background: 'rgba(122,155,94,0.12)',
                    color: 'var(--green)',
                    padding: '4px 8px',
                    borderRadius: '999px',
                  }"
                >
                  <span :style="{ width: '5px', height: '5px', borderRadius: '50%', background: 'var(--green)' }" />
                  正在编辑
                </span>
                <span
                  class="text-[10.5px]"
                  :style="{
                    background: 'var(--card-2)',
                    color: 'var(--ink-3)',
                    border: '1px solid var(--line)',
                    padding: '4px 8px',
                    borderRadius: '999px',
                  }"
                >成稿 v1</span>
                <span class="text-[10px]" :style="{ color: 'var(--ink-3)' }">自动保存于 12:34</span>
                <button
                  v-if="article.title"
                  type="button"
                  class="text-[10.5px] hover:text-primary"
                  :style="{ color: 'var(--ink-3)' }"
                  @click="openTitleCandidates"
                >换标题…</button>
              </div>
              <!-- 成稿 tab 只显示"成稿 X 字"（用户反馈：初稿字数 + 阅读时间这里冗余） -->
              <div class="flex items-center gap-3 text-[11px]" :style="{ color: 'var(--ink-3)' }">
                <span>成稿 {{ (article.finalText || SAMPLE_VARIATIONS[sampleIndex].final).length }} 字</span>
                <!-- 链成本 —— 有 passes 时显示「调用 N 次 · ≈X tokens · ≈¥Y」；
                     未知 model 无价（cost.cost==null）回退只显 token。 -->
                <span v-if="article.passes.length" data-chain-cost>
                  调用 {{ article.callCount }} 次 · ≈{{ article.tokenTotal }} tokens<template v-if="article.cost && article.cost.cost != null"> · ≈¥{{ article.cost.cost.toFixed(4) }}</template>
                </span>
              </div>
              <div class="mt-3" :style="{ height: '1px', background: 'var(--line)' }" />
            </div>

            <!--
              ── skill 链逐 pass 预览 ──
              起飞带了链（passes 非空）时，成稿区上方先展示每个 pass 的输出
              折叠卡（角色标签 + skill 名 + 输出 + 「重跑此 pass」按钮）。
              重跑会级联其后所有 pass（后端 chain_service.rerun）。
              无 passes（单 skill 旧路径）→ 整块不渲染，成稿编辑器行为不变。
            -->
            <div
              v-if="article.passes.length"
              class="flex flex-col gap-2.5"
              :style="{ padding: '0 24px 14px' }"
            >
              <div
                v-for="p in article.passes"
                :key="p.index"
                class="flex flex-col"
                :style="{
                  padding: '12px 14px',
                  borderRadius: '12px',
                  background: '#fbfaf6',
                  border: '1px solid var(--line)',
                }"
              >
                <div class="flex items-center gap-2 mb-1.5">
                  <span
                    class="inline-flex items-center text-[10px] uppercase font-medium"
                    :style="{
                      background: 'var(--primary-soft)',
                      color: 'var(--primary-deep)',
                      border: '1px solid rgba(238,106,42,0.2)',
                      padding: '3px 7px',
                      borderRadius: '6px',
                      letterSpacing: '1px',
                    }"
                  >{{ roleLabel(p.role) }}</span>
                  <span class="text-[11.5px] font-semibold">{{ p.skill_name }}</span>
                  <span class="text-[10px] font-mono tabular-nums" :style="{ color: 'var(--ink-3)' }">
                    {{ p.output_chars }} 字
                  </span>
                  <span class="flex-1" />
                  <!-- 流式重跑按钮：正在跑的这个 pass 上变「取消」（点 cancelRerun），
                       其它情况是「重跑此 pass」（点 article.rerunPass）。别的 pass 在
                       跑时禁用本按钮（互斥），但正在跑的这个要可点取消。
                       data-rerun-pass 保留在重跑态供测试 / E2E 定位。 -->
                  <button
                    type="button"
                    :data-rerun-pass="article.rerunningIndex === p.index ? undefined : ''"
                    :data-cancel-pass="article.rerunningIndex === p.index ? '' : undefined"
                    :title="article.rerunningIndex === p.index
                      ? '取消重跑'
                      : '重跑此 pass（级联其后）'"
                    :disabled="article.rerunningIndex !== null && article.rerunningIndex !== p.index"
                    class="inline-flex items-center gap-1 text-[11px] transition hover:brightness-95 disabled:opacity-60 disabled:cursor-not-allowed"
                    :style="{
                      height: '26px',
                      padding: '0 9px',
                      borderRadius: '7px',
                      background: article.rerunningIndex === p.index ? 'var(--danger-soft, #fef2f2)' : 'var(--card-white)',
                      color: article.rerunningIndex === p.index ? 'var(--danger, #dc2626)' : 'var(--ink-2)',
                      border: article.rerunningIndex === p.index
                        ? '1px solid var(--danger, #dc2626)'
                        : '1px solid var(--line)',
                    }"
                    @click="article.rerunningIndex === p.index ? article.cancelRerun() : article.rerunPass(p.index)"
                  >
                    <Spinner v-if="article.rerunningIndex === p.index" :size="11" />
                    <Icon v-else name="refresh" :size="11" />
                    <span>{{ article.rerunningIndex === p.index ? "取消" : "重跑此 pass" }}</span>
                  </button>
                </div>
                <div
                  class="font-serif-cn"
                  :style="{ fontSize: '12.5px', lineHeight: 1.75, color: 'var(--ink-2)', whiteSpace: 'pre-wrap' }"
                >{{ p.output }}</div>
              </div>
            </div>
            <div class="flex min-h-0 flex-1 flex-col" :style="{ padding: '0 24px 20px' }">
              <div
                class="flex min-h-0 flex-1 flex-col overflow-y-auto"
                :style="{
                  background: '#ffffff',
                  borderRadius: '12px',
                  border: '1px solid var(--line)',
                  padding: '20px 24px',
                }"
              >
                <TiptapEditor
                  :model-value="finalEditorValue"
                  placeholder="起飞后这里会显示成稿。可直接编辑。"
                  :min-height="0"
                  @update:model-value="(v) => (article.finalText = v)"
                />
              </div>
            </div>
          </div>
        </div>
      </Card>

      <!--
        RIGHT — 检查面板（300px）。固定 4 段 column flex stack：
          1. 进度卡（conditional, flex-shrink-0）
          2. 质检报告卡（flex-1 + min-h-0，剩余空间留给它，内部滚动）
          3. 模板区块卡（flex-shrink-0）
          4. 操作卡（flex-shrink-0）
        外层加 min-h-0 + h-full 是关键 —— 没有 min-h-0 的话，flex-1 的
        质检报告会"摆烂"撑到内容自然高度，把 3 和 4 顶出可视区。
      -->
      <!--
        right rail width 288px（原 300，缩 12px）+ 主行 gap +2px (12→14)：
        中间 main editor card 净宽 +10px（用户指定），整体布局收紧。
      -->
      <div
        class="right-rail flex h-full min-h-0 flex-shrink-0 flex-col"
        :style="{ width: '288px', gap: '12px' }"
      >
        <!--
          进度卡 —— 永远渲染，状态分两路：
            · running    → 头部副标题 = 当前 stage，右侧 5/6 + 实进度条
            · idle/done/error → 头部副标题 = 状态文案，进度条灰色 0%，
              不显示 stage 计数
          这样侧栏 4 段栈式布局结构稳定，质检报告卡的高度也不会因为
          进度卡的"有/无"切换而抖动。
        -->
        <Card padless class="flex-shrink-0">
          <div :style="{ padding: '14px 16px' }">
            <div class="flex items-center gap-2">
              <span
                class="inline-flex items-center justify-center"
                :style="{
                  width: '28px',
                  height: '28px',
                  borderRadius: '9px',
                  background:
                    overallStep !== null && overallStep < 4
                      ? 'rgba(238,106,42,0.12)'
                      : 'var(--card-2)',
                  color:
                    overallStep !== null && overallStep < 4
                      ? 'var(--primary)'
                      : 'var(--ink-3)',
                }"
              >
                <Icon name="wand" :size="14" />
              </span>
              <div class="flex-1 min-w-0">
                <div class="text-[12px] font-semibold">进度</div>
                <div
                  class="text-[10.5px] truncate"
                  :style="{ color: 'var(--ink-3)' }"
                >
                  {{ overallLabel }}
                </div>
              </div>
              <span
                v-if="overallStep !== null"
                class="font-mono tabular-nums text-[11px]"
                :style="{ color: 'var(--ink-3)' }"
              >
                {{ overallStep }} / 4
              </span>
            </div>
            <div class="mt-3">
              <!--
                进度条值由 overallProgress 计算 —— 4 段流程的合成进度，
                而不是 generate job 的 6-stage 内部进度。draft_only=true
                模式下 generate 完成只占 50%，剩下 50% 留给整篇润色。
              -->
              <ProgressBar :value="overallProgress" />
            </div>
          </div>
        </Card>

        <!--
          质检报告卡 —— 三段式（header / body / footer），body 根据
          panelMode 在三种视图间切换：检查项列表 / 查重报告 / 标题候选。
          点击底部操作行的「查重」「标题候选」就在卡片内部 swap，不
          再 Teleport 全屏 drawer。「算密度」直接调 store action（
          结果会回写到检查项卡片，所以 mode 维持 checks）。
        -->
        <Card padless class="flex min-h-0 flex-1 flex-col overflow-hidden">
          <!-- header -->
          <div
            class="flex flex-shrink-0 items-center gap-2"
            :style="{ padding: '14px 16px 10px' }"
          >
            <span
              class="inline-flex items-center justify-center"
              :style="{
                width: '28px',
                height: '28px',
                borderRadius: '9px',
                background: 'rgba(122,155,94,0.12)',
                color: 'var(--green)',
              }"
            >
              <Icon name="shield" :size="14" />
            </span>
            <div class="flex-1 min-w-0">
              <div class="text-[12px] font-semibold">
                {{
                  panelMode === "dedup"
                    ? "查重报告"
                    : panelMode === "titles"
                      ? "标题候选"
                      : panelMode === "density"
                        ? "关键词密度"
                        : "质检报告"
                }}
              </div>
              <div class="text-[10.5px] truncate" :style="{ color: 'var(--ink-3)' }">
                <template v-if="panelMode === 'dedup' && article.dedupReport">
                  重复率
                  <span class="font-mono">
                    {{ (article.dedupReport.duplicate_ratio * 100).toFixed(1) }}%
                  </span>
                  · {{ article.dedupReport.duplicate_chars }} /
                  {{ article.dedupReport.text_length }} 字命中
                </template>
                <template v-else-if="panelMode === 'titles'">
                  AI 已生成 {{ article.titleCandidates.length }} 个候选
                </template>
                <template v-else-if="panelMode === 'density' && article.keywordDensity">
                  <span class="font-mono">
                    {{ (article.keywordDensity.density * 100).toFixed(1) }}%
                  </span>
                  · 在健康区间 1.5%-4%
                </template>
                <template v-else>
                  {{ primaryPassCount }}/{{ primaryChecks.length }} 项通过
                </template>
              </div>
            </div>
            <!--
              二级页 header 右上「← 返回」按钮：以前是 X，但 user spec
              要求"返回"心智更明确。只在非 checks (详情态) 显示。
            -->
            <button
              v-if="panelMode !== 'checks'"
              type="button"
              title="返回质检报告"
              class="inline-flex items-center gap-1 transition hover:bg-card-2"
              :style="{
                height: '26px',
                padding: '0 8px',
                borderRadius: '7px',
                color: 'var(--ink-3)',
                fontSize: '11px',
              }"
              @click="panelMode = 'checks'"
            >
              <Icon name="arrowLeft" :size="12" />
              <span>返回</span>
            </button>
          </div>
          <div :style="{ height: '1px', background: 'var(--line)', margin: '0 16px' }" />

          <!-- body —— 三种 mode 在这里 swap -->
          <div class="flex min-h-0 flex-1 flex-col overflow-y-auto" :style="{ padding: '12px' }">
            <!--
              mode: checks（一级页）—— 简化为两张大卡（重复率·历史 /
              关键词密度），layout: 标题(左上) / 通过徽章(右上) / 大字
              (左下) / "详情→"(右下)。整卡可点击 hover 上浮+阴影。
            -->
            <div v-if="panelMode === 'checks'" class="flex flex-col gap-2">
              <button
                v-for="r in primaryChecks"
                :key="r.key"
                type="button"
                class="qc-primary-card text-left w-full"
                :style="{
                  padding: '14px 14px 12px',
                  borderRadius: 'var(--radius-inner)',
                  border: '1px solid var(--line)',
                }"
                @click="r.key === 'dedup' ? openDedup() : openDensity()"
              >
                <div class="flex items-center justify-between">
                  <span class="text-[11.5px] font-medium" :style="{ color: 'var(--ink-2)' }">
                    {{ r.label }}
                  </span>
                  <Pill :tone="r.tone">{{ r.pass ? "通过" : "复查" }}</Pill>
                </div>
                <div class="mt-1 flex items-end justify-between">
                  <div class="font-display font-bold" :style="{ fontSize: '22px', lineHeight: 1.1 }">
                    {{ r.value }}
                  </div>
                  <span
                    class="inline-flex items-center gap-0.5 text-[10.5px]"
                    :style="{ color: 'var(--ink-3)' }"
                  >
                    详情
                    <Icon name="arrowRight" :size="10" />
                  </span>
                </div>
              </button>
            </div>

            <!-- mode: dedup —— 查重结果 -->
            <div v-else-if="panelMode === 'dedup'" class="flex flex-col gap-2">
              <Spinner v-if="article.dedupLoading" />
              <div v-else-if="!article.dedupReport" class="text-[12px]" :style="{ color: 'var(--ink-3)' }">
                没有报告 — 点击「再算」生成一次。
              </div>
              <template v-else>
                <button
                  type="button"
                  class="self-start inline-flex items-center gap-1 text-[11.5px] hover:text-primary"
                  :style="{
                    padding: '4px 8px',
                    borderRadius: '6px',
                    border: '1px solid var(--line)',
                    color: 'var(--ink-2)',
                  }"
                  @click="refreshDedup"
                >
                  <Icon name="refresh" :size="11" />
                  再算
                </button>

                <div v-if="article.dedupReport.top_matches?.length">
                  <div class="font-display text-[12px] font-semibold mb-2 mt-1">
                    主要来源
                  </div>
                  <ul class="flex flex-col gap-1.5">
                    <li
                      v-for="m in article.dedupReport.top_matches"
                      :key="m.source_path"
                      class="text-[11.5px]"
                      :style="{
                        padding: '8px 10px',
                        borderRadius: 'var(--radius-inner)',
                        background: 'var(--card-2)',
                        border: '1px solid var(--line)',
                      }"
                    >
                      <div class="font-medium truncate">
                        {{ m.source_title || m.source_path }}
                      </div>
                      <div class="font-mono text-[10.5px] mt-0.5 tabular-nums" :style="{ color: 'var(--ink-3)' }">
                        {{ m.overlap_chars }} 字 · {{ (m.overlap_ratio * 100).toFixed(1) }}%
                      </div>
                    </li>
                  </ul>
                </div>

                <div v-if="article.dedupReport.hits?.length">
                  <div class="font-display text-[12px] font-semibold mb-2 mt-2">
                    命中段落
                  </div>
                  <ul class="flex flex-col gap-1.5">
                    <li
                      v-for="(h, i) in article.dedupReport.hits.slice(0, 20)"
                      :key="i"
                      class="text-[11.5px] leading-relaxed"
                      :style="{
                        padding: '8px 10px',
                        borderRadius: 'var(--radius-inner)',
                        background: 'var(--card-2)',
                        border: '1px solid var(--line)',
                      }"
                    >
                      <div class="font-mono text-[10px] mb-1" :style="{ color: 'var(--ink-3)' }">
                        位置 {{ h.start }}–{{ h.end }} ·
                        {{ h.source_title || h.source_path }}
                      </div>
                      <div :style="{ color: 'var(--ink)' }">{{ h.text }}</div>
                      <div
                        v-if="h.source_excerpt"
                        class="mt-1 italic"
                        :style="{ color: 'var(--ink-3)' }"
                      >
                        "…{{ h.source_excerpt.slice(0, 100) }}…"
                      </div>
                    </li>
                  </ul>
                  <p
                    v-if="article.dedupReport.hits.length > 20"
                    class="mt-2 text-[10.5px]"
                    :style="{ color: 'var(--ink-3)' }"
                  >
                    仅显示前 20 条，共 {{ article.dedupReport.hits.length }} 条命中。
                  </p>
                </div>
              </template>
            </div>

            <!-- mode: density —— 关键词密度详情页（新建） -->
            <div v-else-if="panelMode === 'density'" class="flex flex-col gap-3">
              <!-- 顶部大数字 + 副词 -->
              <div class="flex items-baseline gap-2">
                <span
                  class="font-display font-bold"
                  :style="{
                    fontSize: '28px',
                    lineHeight: 1,
                    letterSpacing: '-0.5px',
                  }"
                >
                  {{
                    article.keywordDensity
                      ? (article.keywordDensity.density * 100).toFixed(1) + "%"
                      : "—"
                  }}
                </span>
                <span class="text-[11.5px]" :style="{ color: 'var(--ink-2)' }">
                  {{
                    article.keywordDensity
                      ? article.keywordDensity.density >= 0.015 &&
                        article.keywordDensity.density <= 0.04
                        ? "在 1.5%-4% 区间"
                        : "建议 1.5%-4%"
                      : "尚未计算"
                  }}
                </span>
              </div>

              <!--
                区间色条 —— 红 0-1.5% / 绿 1.5-4% / 红 4-10%，让"健康
                区间"占视觉中段。当前位置由 density (clamp 到 10%) 映射
                到色条上的圆点。
              -->
              <div v-if="article.keywordDensity">
                <div
                  class="relative"
                  :style="{
                    height: '6px',
                    borderRadius: '999px',
                    background:
                      'linear-gradient(to right, #d85a48 0%, #d85a48 15%, #7a9b5e 15%, #7a9b5e 40%, #d85a48 40%, #d85a48 100%)',
                  }"
                >
                  <span
                    :style="{
                      position: 'absolute',
                      top: '50%',
                      left:
                        Math.min(article.keywordDensity.density * 10, 1) * 100 +
                        '%',
                      transform: 'translate(-50%, -50%)',
                      width: '14px',
                      height: '14px',
                      borderRadius: '50%',
                      background: '#7a9b5e',
                      border: '3px solid #fff',
                      boxShadow: '0 1px 3px rgba(var(--shadow-rgb),0.18)',
                    }"
                  />
                </div>
                <div
                  class="mt-1 flex justify-between text-[10px]"
                  :style="{ color: 'var(--ink-3)' }"
                >
                  <span>0%</span>
                  <span>1.5%</span>
                  <span>4%</span>
                  <span>10%</span>
                </div>
              </div>

              <!-- 出现统计（store 只有单关键词的 count，多关键词字段后续接） -->
              <div v-if="article.keywordDensity && article.lastRequest">
                <div class="font-display text-[12px] font-semibold mb-1.5">
                  出现统计
                </div>
                <ul class="flex flex-col gap-1">
                  <li
                    class="flex items-center justify-between text-[11.5px]"
                    :style="{
                      padding: '6px 10px',
                      borderRadius: 'var(--radius-inner)',
                      background: 'var(--card-2)',
                      border: '1px solid var(--line)',
                    }"
                  >
                    <span :style="{ color: 'var(--ink)' }">
                      {{ article.lastRequest.keyword }}
                    </span>
                    <span
                      class="font-mono tabular-nums"
                      :style="{ color: 'var(--ink-2)' }"
                    >
                      {{ article.keywordDensity.count }} 次
                    </span>
                  </li>
                </ul>
              </div>

              <!-- 建议卡 —— 橙色软底，3 条 static 建议（按 user spec） -->
              <div
                :style="{
                  padding: '12px 14px',
                  borderRadius: 'var(--radius-inner)',
                  background: 'rgba(238,106,42,0.10)',
                  border: '1px solid rgba(238,106,42,0.20)',
                }"
              >
                <div
                  class="font-display text-[12px] font-semibold mb-1.5"
                  :style="{ color: 'var(--primary-deep)' }"
                >
                  建议
                </div>
                <ul
                  class="flex flex-col gap-1 text-[11.5px]"
                  :style="{ color: 'var(--ink-2)' }"
                >
                  <li>· 密度在健康区间，可保持当前用词节奏</li>
                  <li>· "宠物" 出现较少，可在段首段尾适度补充</li>
                  <li>· 品牌名累计 12 次，注意广告嫌疑</li>
                </ul>
              </div>
            </div>

            <!-- mode: titles —— 标题候选列表 -->
            <div v-else class="flex flex-col gap-2">
              <Spinner v-if="article.titleLoading" />
              <div v-else-if="article.titleCandidates.length === 0" class="text-[12px]" :style="{ color: 'var(--ink-3)' }">
                点击下方按钮生成候选。
              </div>
              <ul v-else class="flex flex-col gap-1.5">
                <li
                  v-for="t in article.titleCandidates"
                  :key="t"
                  class="cursor-pointer text-[12px] leading-relaxed transition hover:bg-card-white"
                  :style="{
                    padding: '10px 12px',
                    borderRadius: 'var(--radius-inner)',
                    background: 'var(--card-2)',
                    border: '1px solid var(--line)',
                  }"
                  @click="pickTitle(t)"
                >
                  {{ t }}
                </li>
              </ul>
              <button
                type="button"
                class="self-start inline-flex items-center gap-1 text-[11.5px] mt-1"
                :style="{
                  padding: '4px 8px',
                  borderRadius: '6px',
                  border: '1px solid var(--line)',
                  color: 'var(--ink-2)',
                }"
                @click="article.fetchTitleCandidates()"
              >
                <Icon name="refresh" :size="11" />
                重新生成
              </button>
            </div>
          </div>

          <!--
            footer 三按钮 —— 跟卡片 mode 联动（点对应一级页卡片 / 直接
            点底部按钮都进同 mode）。
              默认: 透明 + ink-2
              Hover: 主色实心 + 白字 + 橙色外阴影 + 微上浮
              Active: 同 hover (当前 mode 命中时常驻)
            divider 删除让 hover/active 的橙底块在 3 段并排时更连贯。
            class 名 qc-footer-btn / qc-footer-active 样式定义在文件末尾
            <style scoped>。
          -->
          <div
            class="flex flex-shrink-0 items-center gap-1"
            :style="{ padding: '6px', borderTop: '1px solid var(--line)' }"
          >
            <button
              type="button"
              :class="[
                'qc-footer-btn flex-1 text-[12px] font-medium',
                { 'qc-footer-active': panelMode === 'dedup' },
              ]"
              @click="openDedup"
            >
              查重
            </button>
            <button
              type="button"
              :class="[
                'qc-footer-btn flex-1 text-[12px] font-medium',
                { 'qc-footer-active': panelMode === 'density' },
              ]"
              @click="openDensity"
            >
              算密度
            </button>
            <button
              type="button"
              :class="[
                'qc-footer-btn flex-1 text-[12px] font-medium',
                { 'qc-footer-active': panelMode === 'titles' },
              ]"
              @click="openTitleCandidates"
            >
              标题候选
            </button>
          </div>
        </Card>

        <!--
          模板区块 —— 框架模板 + AI 润色 Skill 两个下拉合并到一张卡，
          padding 紧凑，下拉框 width:100% 撑满卡片宽度（右栏 300px）。
          「模板区块」eyebrow 按用户要求移除（卡内字段名 = 框架模板 / AI
          润色 Skill，已足够自解释）。
        -->
        <Card padless class="flex-shrink-0">
          <div class="flex flex-col gap-3" :style="{ padding: '12px 14px' }">
            <div class="flex flex-col gap-1.5">
              <div
                class="text-[10.5px] font-medium"
                :style="{ color: 'var(--ink-3)' }"
              >
                框架模板
              </div>
              <FormSelect
                :model-value="templateId"
                :options="templateOptions"
                width="100%"
                @update:model-value="(v) => (templateId = String(v))"
              />
            </div>
            <div class="flex flex-col gap-1.5">
              <div
                class="text-[10.5px] font-medium"
                :style="{ color: 'var(--ink-3)' }"
              >
                AI 润色 Skill
              </div>
              <FormSelect
                :model-value="skillId"
                :options="skillOptions"
                width="100%"
                @update:model-value="(v) => (skillId = String(v))"
              />
            </div>
          </div>
        </Card>

        <!--
          操作卡 —— 按用户要求改为两行布局：
            行 1：整篇润色（primary）+ 重新随机（card-2）  ← h=42
            行 2：清空（red 文字）+ 导出文章（dark）       ← h=36
          flex-1 让同行的两个按钮等宽；行内 gap 2，行间 gap 2.5。
          主按钮 整篇润色 保留 primary 配色 + 42 高度的视觉权重，
          导出文章 保留 dark 底，整体优先级比原 3 行没变，只是
          重排成 2×2 网格更紧凑。
        -->
        <Card padless class="flex-shrink-0">
          <div class="flex flex-col gap-2.5" :style="{ padding: '18px' }">
            <!-- 行 1：整篇润色 + 重新随机 -->
            <div class="flex gap-2">
              <button
                type="button"
                class="flex-1 inline-flex items-center justify-center gap-1.5 transition hover:brightness-95 disabled:opacity-50 disabled:cursor-not-allowed"
                :style="{
                  height: '42px',
                  fontSize: '13px',
                  fontWeight: 500,
                  borderRadius: '10px',
                  background: 'var(--primary)',
                  color: '#fff',
                  border: '1px solid var(--primary)',
                }"
                :disabled="!article.draftText.trim() || polishing || article.isRunning"
                @click="polishAll"
              >
                <Spinner v-if="polishing || article.isRunning" :size="13" />
                <Icon v-else name="wand" :size="13" />
                <span>{{ (polishing || article.isRunning) ? "润色中…" : "整篇润色" }}</span>
              </button>
              <button
                type="button"
                class="flex-1 inline-flex items-center justify-center gap-1.5 transition hover:brightness-95 disabled:opacity-50 disabled:cursor-not-allowed"
                :style="{
                  height: '42px',
                  fontSize: '13px',
                  fontWeight: 500,
                  borderRadius: '10px',
                  background: 'var(--card-2)',
                  color: 'var(--ink-2)',
                  border: '1px solid var(--line)',
                }"
                :disabled="!article.lastRequest"
                @click="rerun"
              >
                <Icon name="refresh" :size="12" />
                <span>重新随机</span>
              </button>
            </div>
            <!-- 行 2：清空 + 导出文章 -->
            <div class="flex gap-2">
              <button
                type="button"
                class="flex-1 inline-flex items-center justify-center gap-1.5 transition hover:brightness-95"
                :style="{
                  height: '36px',
                  fontSize: '12px',
                  fontWeight: 500,
                  borderRadius: '10px',
                  background: 'var(--card-2)',
                  color: 'var(--red)',
                  border: '1px solid var(--line)',
                }"
                @click="clearAll"
              >
                <Icon name="x" :size="12" />
                <span>清空</span>
              </button>
              <button
                type="button"
                class="flex-1 inline-flex items-center justify-center gap-1.5 transition hover:brightness-95 disabled:opacity-50 disabled:cursor-not-allowed"
                :style="{
                  height: '36px',
                  fontSize: '12px',
                  fontWeight: 500,
                  borderRadius: '10px',
                  background: 'var(--dark)',
                  color: 'var(--card)',
                  border: '1px solid var(--dark)',
                }"
                @click="onExportClick"
              >
                <Icon name="copy" :size="12" />
                <span>{{ article.factcheck?.blocked ? "核对并导出" : "导出文章" }}</span>
              </button>
            </div>
          </div>
        </Card>
      </div>
    </div>

    <!--
      原"标题候选"和"查重报告" Teleport drawer 已删除。
      现在两个视图都直接 swap 在右侧 质检报告 Card 内部（panelMode 控制），
      不再额外占整页右侧空间。导出弹窗保留。
    -->

    <!--
      事实核对审查面板 —— 生成被 Plan 3 门禁拦下时弹（watcher 自动 / 导出按钮
      被拦时也走它）。Dialog 内部自带 Teleport，挂这层即可。
    -->
    <FactCheckPanel v-model:open="showFactcheck" @lint="showLint = true" />
    <!--
      proceed 重入守卫链（onExportClick）而非直接开导出 modal：堵 factcheck+lint
      双失败旁路 —— lint 清掉后若 factcheck 仍 blocked，重新弹 FactCheckPanel 走
      gated /generate/{id}/export；都干净才开导出 modal。lintBlocking 此刻已 false
      不会回环到 lint。
    -->
    <LintPanel v-model:open="showLint" @proceed="onExportClick" />

    <!--
      导出弹窗 —— 严格按 V1 设计稿（精简版）：标签 + 大标题 + 关闭 X，
      下方 3 个格式卡片（Markdown / Word / 纯文本），底部 取消 / 导出。
      已移除"微信公众号 / 知乎专栏"以及三个附加选项 checkbox。
    -->
    <Teleport to="body">
      <div
        v-if="showExportModal"
        class="fixed inset-0 z-40 flex items-center justify-center"
        :style="{ background: 'rgba(var(--ink-rgb),0.4)' }"
        @click.self="showExportModal = false"
      >
        <div
          class="anim-up"
          :style="{
            width: '480px',
            maxWidth: '92vw',
            borderRadius: 'var(--radius-card)',
            background: 'var(--bg-inner)',
            border: '1px solid var(--line)',
            padding: '22px 22px 20px 22px',
            boxShadow: '0 18px 50px rgba(var(--shadow-rgb),0.18)',
          }"
        >
          <div class="flex items-start justify-between mb-4">
            <div>
              <div :style="{ fontSize: '11.5px', color: 'var(--ink-3)', marginBottom: '4px' }">
                导出文章
              </div>
              <div
                class="font-display"
                :style="{ fontSize: '18px', fontWeight: 700, color: 'var(--ink)' }"
              >
                选择格式
              </div>
            </div>
            <button
              type="button"
              class="inline-flex items-center justify-center transition hover:brightness-95"
              :style="{
                width: '28px',
                height: '28px',
                borderRadius: '999px',
                background: 'var(--card-2)',
                color: 'var(--ink-2)',
                border: '1px solid var(--line)',
              }"
              @click="showExportModal = false"
            >
              <Icon name="x" :size="14" />
            </button>
          </div>

          <div class="flex flex-col" :style="{ gap: '10px' }">
            <button
              v-for="opt in EXPORT_OPTIONS"
              :key="opt.value"
              type="button"
              class="w-full flex items-center transition"
              :style="{
                gap: '12px',
                padding: '12px 14px',
                borderRadius: '12px',
                background: exportFormat === opt.value ? 'var(--primary-soft)' : 'var(--card)',
                border: exportFormat === opt.value
                  ? '1px solid var(--primary)'
                  : '1px solid var(--line)',
                cursor: 'pointer',
                textAlign: 'left',
              }"
              @click="exportFormat = opt.value"
            >
              <div
                class="inline-flex items-center justify-center flex-shrink-0"
                :style="{
                  width: '34px',
                  height: '34px',
                  borderRadius: '8px',
                  background: 'var(--card-2)',
                  color: 'var(--ink-2)',
                  border: '1px solid var(--line)',
                }"
              >
                <Icon :name="opt.icon" :size="15" />
              </div>
              <div class="flex-1 min-w-0">
                <div
                  :style="{
                    fontSize: '13px',
                    fontWeight: 600,
                    color: 'var(--ink)',
                    marginBottom: '2px',
                  }"
                >
                  {{ opt.label }}
                </div>
                <div :style="{ fontSize: '11.5px', color: 'var(--ink-3)' }">
                  {{ opt.sublabel }}
                </div>
              </div>
              <Icon
                v-if="exportFormat === opt.value"
                name="check"
                :size="16"
                :style="{ color: 'var(--primary)' }"
              />
            </button>
          </div>

          <div class="flex justify-end items-center mt-5" :style="{ gap: '8px' }">
            <button
              type="button"
              class="inline-flex items-center justify-center transition hover:brightness-95"
              :style="{
                height: '34px',
                padding: '0 16px',
                fontSize: '12.5px',
                borderRadius: '999px',
                background: 'transparent',
                color: 'var(--ink-2)',
                border: 'none',
              }"
              @click="showExportModal = false"
            >
              取消
            </button>
            <button
              type="button"
              class="inline-flex items-center justify-center gap-1.5 transition hover:brightness-95"
              :style="{
                height: '34px',
                padding: '0 18px',
                fontSize: '12.5px',
                fontWeight: 500,
                borderRadius: '999px',
                background: 'var(--dark)',
                color: 'var(--card)',
                border: '1px solid var(--dark)',
              }"
              @click="doExport"
            >
              <Icon name="check" :size="13" />
              <span>导出</span>
            </button>
          </div>
        </div>
      </div>
    </Teleport>

    <!--
      整篇润色进度模态 —— 居中弹窗，展示 5 阶段流水：解析→应用 Skill
      →句法重写→段落润色→收口。Demo 模式下走脚本时间轴；真实模式
      下也复用同一个 UI（progress 在 0/100 间，stage 名称固定为
      "AI 处理中…"）。点遮罩或自动完成后关闭。
    -->
    <Teleport to="body">
      <div
        v-if="polishing"
        class="fixed inset-0 z-50 flex items-center justify-center"
        :style="{ background: 'rgba(var(--ink-rgb),0.4)' }"
      >
        <div
          class="anim-up bg-bg-inner"
          :style="{
            width: '420px',
            maxWidth: '90vw',
            padding: '24px 26px',
            borderRadius: 'var(--radius-card)',
            border: '1px solid var(--line)',
            boxShadow: '0 30px 80px -20px rgba(0,0,0,0.4)',
          }"
        >
          <div class="flex items-center gap-2.5 mb-4">
            <span
              class="inline-flex items-center justify-center"
              :style="{
                width: '36px',
                height: '36px',
                borderRadius: '10px',
                background: 'var(--primary-soft)',
                color: 'var(--primary-deep)',
              }"
            >
              <Icon name="wand" :size="16" />
            </span>
            <div class="flex-1 min-w-0">
              <div
                class="text-[10.5px] uppercase font-medium"
                :style="{ color: 'var(--ink-3)', letterSpacing: '1.5px' }"
              >
                AI · 整篇润色
              </div>
              <div class="font-display text-[15px] font-semibold">
                {{ polishStage || "AI 处理中…" }}
              </div>
            </div>
            <span
              class="font-mono tabular-nums text-[12px]"
              :style="{ color: 'var(--ink-3)' }"
            >
              {{ Math.floor(polishProgress) }}%
            </span>
          </div>

          <!-- 进度条 -->
          <div
            :style="{
              height: '6px',
              background: 'var(--card-2)',
              borderRadius: '999px',
              overflow: 'hidden',
            }"
          >
            <div
              :style="{
                height: '100%',
                width: `${polishProgress}%`,
                background: 'var(--primary)',
                borderRadius: '999px',
                transition: 'width 0.18s ease',
              }"
            />
          </div>

          <!-- 阶段列表 -->
          <ul class="mt-4 flex flex-col gap-1.5">
            <li
              v-for="(s, i) in POLISH_STAGES"
              :key="s"
              class="flex items-center gap-2 text-[12px]"
              :style="{
                color:
                  polishStage === s
                    ? 'var(--ink)'
                    : POLISH_STAGES.indexOf(polishStage) > i
                      ? 'var(--ink-2)'
                      : 'var(--ink-3)',
              }"
            >
              <span
                class="inline-flex items-center justify-center flex-shrink-0"
                :style="{
                  width: '16px',
                  height: '16px',
                  borderRadius: '50%',
                  background:
                    POLISH_STAGES.indexOf(polishStage) > i
                      ? 'var(--green)'
                      : polishStage === s
                        ? 'var(--primary)'
                        : 'var(--card-2)',
                  color:
                    POLISH_STAGES.indexOf(polishStage) >= i ? '#fff' : 'var(--ink-3)',
                  border:
                    POLISH_STAGES.indexOf(polishStage) >= i
                      ? 'none'
                      : '1px solid var(--line)',
                }"
              >
                <Icon
                  v-if="POLISH_STAGES.indexOf(polishStage) > i"
                  name="check"
                  :size="9"
                />
                <Spinner v-else-if="polishStage === s" :size="9" />
              </span>
              <span>{{ s }}</span>
            </li>
          </ul>

          <p class="mt-4 text-[10.5px]" :style="{ color: 'var(--ink-3)' }">
            完成后会自动关闭。期间请勿编辑文章。
          </p>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
/*
 * 质检报告卡 hover / active 样式集中在这。inline :style 没办法定义
 * :hover 状态（class 才行），所以一级页大卡 + 底部 3 按钮的 hover/
 * active 视觉都走 class。
 *
 * 创作区右侧 3 张卡（进度 / 质检报告 / 模板 / 操作）的浮动阴影也
 * 加在这（用户要求"创作区卡片增加浮动阴影效果"），通过 ArticleView
 * 包给 Card 组件的 wrapper 添加 box-shadow。
 */

/*
 * 一级页两张大卡：默认 card-2 cream 底，hover 切到 #fbfaf6（用户指定
 * 的暖奶白） + 微上浮 + 软阴影。background 从 inline :style 移到这里，
 * inline 特异度 1000 会压死 :hover 的 background 切换（memory:
 * feedback_vue_inline_style_hover_clobber）。
 */
.qc-primary-card {
  background: var(--card-2);
  transition:
    background-color 0.14s ease,
    transform 0.14s ease,
    box-shadow 0.14s ease;
  cursor: pointer;
}
.qc-primary-card:hover {
  background: #fbfaf6;
  transform: translateY(-2px);
  box-shadow:
    0 6px 14px -2px rgba(var(--shadow-rgb), 0.10),
    0 2px 6px rgba(var(--shadow-rgb), 0.05);
}

/* 底部三按钮：默认透明深灰，hover/active 切到主色橙实心 + 阴影 + 微浮起 */
.qc-footer-btn {
  height: 32px;
  border-radius: 8px;
  background: transparent;
  color: var(--ink-2);
  transition:
    background-color 0.12s ease,
    color 0.12s ease,
    box-shadow 0.12s ease,
    transform 0.12s ease;
}
.qc-footer-btn:hover,
.qc-footer-btn.qc-footer-active {
  background: var(--primary);
  color: #ffffff;
  box-shadow:
    0 4px 12px -2px rgba(238, 106, 42, 0.40),
    0 1px 3px rgba(var(--shadow-rgb), 0.06);
  transform: translateY(-1px);
}
.qc-footer-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.qc-footer-btn:disabled:hover {
  background: transparent;
  color: var(--ink-2);
  box-shadow: none;
  transform: none;
}

/*
 * 创作区右侧 4 张 Card 加浮动阴影 —— 给 ArticleView 用 :deep() 触达
 * Card 子组件的根 section 元素。这样不用改 Card 组件本身。
 */
/*
 * ArticleView 内所有 Card section（中间 main editor 卡 + 右侧
 * 4 张 inspector 卡）背景统一为 #fbfaf6 —— 用户精确指定，比默认
 * var(--card) (#fbf7ec) 略亮的暖奶白。:deep(section) 用一般选择器
 * 穿透 scoped，编译为 [data-v-xxx] section，Card 组件 root section
 * 因继承父 scope 也命中。
 */
:deep(section) {
  background-color: #fbfaf6;
  /*
   * Multi-layer box-shadow 解决 overflow-hidden 裁切问题：
   * 父 main 是 `overflow-hidden` + padding 30px，单层大 blur (60+px)
   * shadow 在远端被父 padding 边界裁掉，看起来"半截阴影"。改成 4 层
   * 浅深叠加 —— 每层 visible 范围 (offset + blur - spread) 都 ≤30px
   * 在 padding 内不被裁；叠加后整体厚度感 + 自然光"近实远虚"过渡，
   * 比单层强 shadow 更柔和真实。
   *
   * 同时顶部加 inset 白色高光（1px），模拟环境光打在卡片上边的反射
   * 亮边，让"浮起"立体感更强。
   *
   * H 偏移全部负值 (-2~-6) → 阴影集中在卡片左下，跟用户指定的"向左
   * 下浮起"方向一致。右侧 inspector 4 张卡靠 .right-rail :deep(section)
   * specificity 覆盖回标准居中阴影。
   */
  /*
   * 不用 outer box-shadow —— 父 router-view wrapper (App.vue L190
   * `overflow-y-auto`) 紧贴 card 边缘，任何方向 outer shadow 都被
   * 立即裁掉看不见完整效果。改成靠 Card 组件自带的 1px border +
   * 顶部 inset 白色高光模拟"环境光打在卡上沿"的弱浮起立体感。
   * 不引入位移，也不被 overflow 影响。
   */
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.65);
}
.right-rail :deep(section) {
  /*
   * inspector 卡：outer shadow + 顶部 inset 高光，跟 main editor 的
   * inset 高光呼应视觉一致。outer 部分收缩 1px + 减淡（用户反馈右栏
   * 卡阴影过重）。
   */
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.65),
    0 3px 10px -2px rgba(var(--shadow-rgb), 0.07),
    0 2px 5px rgba(var(--shadow-rgb), 0.04);
  transition: box-shadow 0.14s ease;
}
.right-rail :deep(section):hover {
  /* hover 同步减一档，跟默认态保持比例 */
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.65),
    0 8px 20px -4px rgba(var(--shadow-rgb), 0.10),
    0 4px 8px rgba(var(--shadow-rgb), 0.05);
}

/*
 * 组装预览段落卡（中间内容区）—— 默认白底 + 普通边框；hover 微上浮
 * + 软阴影；选中态浅橙底 + 橙色光晕阴影（参考用户设计：选中明显浮起）。
 * 之前用 inline :style 切换 background/border，没办法定义 :hover；
 * 现在 class-driven 让 hover/selected 都走 scoped CSS。
 */
.assembly-block {
  background: #fbfaf6;
  border: 1px solid var(--line);
  border-radius: 14px;
  padding: 14px;
  /* 默认就有轻微阴影 —— 让段落卡跟外层组装预览容器有视觉分层 */
  box-shadow:
    0 2px 6px -1px rgba(var(--shadow-rgb), 0.05),
    0 1px 3px rgba(var(--shadow-rgb), 0.04);
  transition:
    background-color 0.14s ease,
    border-color 0.14s ease,
    box-shadow 0.14s ease,
    transform 0.14s ease;
  cursor: pointer;
}
.assembly-block:hover {
  /* hover 明显浮起 —— 阴影加大 + 上移 2px */
  box-shadow:
    0 10px 24px -4px rgba(var(--shadow-rgb), 0.14),
    0 4px 10px rgba(var(--shadow-rgb), 0.06);
  transform: translateY(-2px);
}
.assembly-block.selected {
  /*
   * 选中态：纯白底 + 橙色边 + 轻量橙色光晕。background 切到
   * var(--card-white) (#ffffff)，跟其他卡 #fbfaf6 暖奶白形成对比，
   * 一眼就能看出"当前选中是哪张"。
   */
  background: var(--card-white);
  border-color: rgba(238, 106, 42, 0.45);
  box-shadow:
    0 4px 14px -2px rgba(238, 106, 42, 0.20),
    0 1px 4px rgba(var(--shadow-rgb), 0.04);
}
/* selected 状态下 hover 不再额外 translate，避免重复浮起抖动 */
.assembly-block.selected:hover {
  transform: none;
}
</style>
