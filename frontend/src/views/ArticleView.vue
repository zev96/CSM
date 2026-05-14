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
 *   V1 的起飞入口在 home（KeywordHero）。本视图主要用于**已起飞**后查看
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

import { useArticle } from "@/stores/article";
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
  heading: { i: "tag" as any, l: "标题", c: "#1e1c19" },
  paragraph: { i: "fileText", l: "段落", c: "#5a544c" },
  numbered_list: { i: "sliders", l: "编号清单", c: "#5a544c" },
  hero_brand: { i: "skills", l: "主推款", c: "#ee6a2a" },
  competitor_pool: { i: "library", l: "产品池", c: "#ee6a2a" },
  literal: { i: "copy", l: "原文照写", c: "#5a544c" },
  test_framework: { i: "library", l: "测评框架", c: "#2e7d4d" },
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
  await article.submit({
    keyword: keyword.value.trim(),
    template_id: templateId.value,
    skill_id: skillId.value || undefined,
    seed: seed.value,
    draft_only: true,
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
  if (polishing.value) return;
  polishing.value = true;
  polishProgress.value = 0;
  polishStage.value = POLISH_STAGES[0];

  if (article.lastRequest && article.draftText.trim()) {
    // 真实模式：把组装好的初稿（draftText）整篇喂给 LLM 润色，
    // 结果写入 finalText 作为成稿。这是整个流程的第二次（也是
    // 整篇润色环节的唯一一次）LLM 调用。
    try {
      const out = await article.polishWhole(article.draftText);
      if (out) {
        article.setFinalText(out);
        // 润色完成才把视图切到成稿 tab —— 配合 watch(article.status)
        // 里 done → "draft" 的语义，组成完整的「初稿 → 润色 → 成稿」流。
        activeTab.value = "final";
        toast.success("整篇润色完成");
      } else {
        toast.error("润色失败，未返回结果");
      }
    } finally {
      polishing.value = false;
      polishProgress.value = 0;
      polishStage.value = "";
    }
    return;
  }

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
  if (article.status === "idle" || article.status === "error") return 0;
  if (article.status === "running") return article.progress * 50;
  // status === "done"
  if (polishing.value) return 75;
  if (article.finalText.trim()) return 100;
  return 50;  // 初稿就绪、等待润色
});

const overallLabel = computed<string>(() => {
  if (article.status === "idle") return "暂无生成任务";
  if (article.status === "error") return article.error ?? "生成失败";
  if (article.status === "running") return article.currentStage ?? "排队中…";
  if (polishing.value) return polishStage.value || "AI 润色中…";
  if (article.finalText.trim()) return "已完成";
  return "初稿就绪 · 待润色";
});

// 右上角的 "x / 4" 步骤计数。step 取值含义：
//   1 组装中 / 2 初稿就绪 / 3 润色中 / 4 成稿完成
const overallStep = computed<number | null>(() => {
  if (article.status === "idle" || article.status === "error") return null;
  if (article.status === "running") return 1;
  if (polishing.value) return 3;
  if (article.finalText.trim()) return 4;
  return 2;
});

/**
 * 质检报告卡的视图模式 —— 默认 "checks" 渲染六项检查；点击底部
 * "查重"/"标题候选" 时切到对应的子视图，整张卡内部 swap，不再用
 * Teleport 弹整页 drawer。点回另一个 mode 或顶部"返回"按钮回到列表。
 */
type PanelMode = "checks" | "dedup" | "titles";
const panelMode = ref<PanelMode>("checks");

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

  return items;
});
const passCount = computed(() => checkItems.value.filter((c) => c.pass).length);

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
    // done 时停在初稿 tab —— 让用户先检查组装出来的 draft，再手动
    // 点"整篇润色"。完成后由 polishAll 在润色成功时把 tab 切到 final。
    // 不直接跳 final 是因为 draft_only=true 模式下 finalText 是空的，
    // 跳过去用户只会看到空白成稿，体验更差。
    if (s === "done") activeTab.value = "draft";
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
  if (activeTab.value === "assembly") return "组装 · 框架 + 采样";
  if (activeTab.value === "draft") return "初稿 · 手动编辑 + 整篇润色";
  return "成稿 · 可编辑 + 导出";
});

</script>

<template>
  <!--
    根用 h-full + flex-col：和 HomeView 同款收口策略，整页不滚，由内部
    组件自行 overflow-y-auto。
  -->
  <div class="flex h-full flex-col" :style="{ gap: '14px' }">
    <!--
      ── V1 风格 header ─────────────────────────────────────────
      `← 返回工作台 | 分隔线 | 模板 chip | Skill chip | 字数 · 重复率`
      不再有起飞条 —— 起飞入口在 home（KeywordHero），这里只展示已起飞
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
        <Pill tone="primary">{{ skillName || "默认 Skill" }}</Pill>
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

    <!-- ── 主内容行：左编辑卡 + 右 300px 检查面板 ────────────────── -->
    <div class="flex min-h-0 flex-1" :style="{ gap: '12px' }">
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
                <div class="flex items-center gap-2 mb-3">
                  <Pill>{{ templateName || "未选模板" }}</Pill>
                  <span class="text-[10.5px]" :style="{ color: 'var(--ink-4, var(--ink-3))' }">
                    {{ assemblyRows.length }} 个槽位
                  </span>
                </div>
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
                    <div
                      v-for="b in assemblyRows.filter((x) => x.kind !== 'heading')"
                      :key="b.id"
                      class="transition cursor-pointer"
                      :style="{
                        background: selectedSlot === b.id ? 'var(--card-white)' : 'var(--card-2)',
                        border: selectedSlot === b.id ? '1px solid rgba(238,106,42,0.25)' : '1px solid var(--line)',
                        borderRadius: '14px',
                        padding: '14px',
                      }"
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
              <div class="flex items-center gap-3 text-[11px]" :style="{ color: 'var(--ink-3)' }">
                <span>初稿 {{ (article.draftText || SAMPLE_VARIATIONS[sampleIndex].draft).length }} 字</span>
                <span :style="{ width: '1px', height: '10px', background: 'var(--line-2)' }" />
                <span>成稿 {{ (article.finalText || SAMPLE_VARIATIONS[sampleIndex].final).length }} 字</span>
                <span :style="{ width: '1px', height: '10px', background: 'var(--line-2)' }" />
                <span>约需阅读 1 分钟</span>
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
              <div class="flex items-center gap-3 text-[11px]" :style="{ color: 'var(--ink-3)' }">
                <span>初稿 {{ (article.draftText || SAMPLE_VARIATIONS[sampleIndex].draft).length }} 字</span>
                <span :style="{ width: '1px', height: '10px', background: 'var(--line-2)' }" />
                <span>成稿 {{ (article.finalText || SAMPLE_VARIATIONS[sampleIndex].final).length }} 字</span>
                <span :style="{ width: '1px', height: '10px', background: 'var(--line-2)' }" />
                <span>约需阅读 1 分钟</span>
              </div>
              <div class="mt-3" :style="{ height: '1px', background: 'var(--line)' }" />
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
      <div
        class="flex h-full min-h-0 flex-shrink-0 flex-col"
        :style="{ width: '300px', gap: '12px' }"
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
                <template v-else>
                  {{ passCount }}/{{ checkItems.length }} 项通过
                </template>
              </div>
            </div>
            <button
              v-if="panelMode !== 'checks'"
              type="button"
              title="返回检查项"
              class="inline-flex items-center justify-center transition hover:bg-card-2"
              :style="{
                width: '26px',
                height: '26px',
                borderRadius: '7px',
                color: 'var(--ink-3)',
              }"
              @click="panelMode = 'checks'"
            >
              <Icon name="x" :size="14" />
            </button>
          </div>
          <div :style="{ height: '1px', background: 'var(--line)', margin: '0 16px' }" />

          <!-- body —— 三种 mode 在这里 swap -->
          <div class="flex min-h-0 flex-1 flex-col overflow-y-auto" :style="{ padding: '12px' }">
            <!-- mode: checks（默认）—— 6 项检查项卡片 -->
            <div v-if="panelMode === 'checks'" class="flex flex-col gap-2">
              <div
                v-for="r in checkItems"
                :key="r.label"
                :style="{
                  padding: '12px',
                  borderRadius: 'var(--radius-inner)',
                  background: r.pass ? 'var(--card-2)' : 'rgba(216,90,72,0.06)',
                  border: r.pass ? '1px solid var(--line)' : '1px solid rgba(216,90,72,0.15)',
                }"
              >
                <div class="flex items-center justify-between">
                  <span class="text-[11px]" :style="{ color: 'var(--ink-3)' }">
                    {{ r.label }}
                  </span>
                  <Pill :tone="r.tone">{{ r.pass ? "通过" : "复查" }}</Pill>
                </div>
                <div class="font-display font-bold mt-1" :style="{ fontSize: '17px' }">
                  {{ r.value }}
                </div>
                <div class="text-[10.5px] mt-0.5" :style="{ color: 'var(--ink-3)' }">
                  {{ r.desc }}
                </div>
              </div>
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

          <!-- footer 操作行（钉在卡片底）—— 点过的 mode 高亮 -->
          <div
            class="flex flex-shrink-0 items-center justify-between"
            :style="{ padding: '6px', borderTop: '1px solid var(--line)' }"
          >
            <button
              type="button"
              class="flex-1 text-center text-[12px] font-medium transition hover:bg-card-2 disabled:opacity-50 disabled:cursor-not-allowed"
              :style="{
                height: '32px',
                borderRadius: '8px',
                color: panelMode === 'dedup' ? 'var(--primary-deep)' : 'var(--ink-2)',
                background: panelMode === 'dedup' ? 'var(--primary-soft)' : 'transparent',
                fontWeight: panelMode === 'dedup' ? 600 : 500,
              }"
              @click="openDedup"
            >
              查重
            </button>
            <span :style="{ width: '1px', height: '16px', background: 'var(--line-2)' }" />
            <button
              type="button"
              class="flex-1 text-center text-[12px] font-medium transition hover:bg-card-2 disabled:opacity-50 disabled:cursor-not-allowed"
              :style="{
                height: '32px',
                borderRadius: '8px',
                color: 'var(--ink-2)',
              }"
              @click="refreshDensity"
            >
              算密度
            </button>
            <span :style="{ width: '1px', height: '16px', background: 'var(--line-2)' }" />
            <button
              type="button"
              class="flex-1 text-center text-[12px] font-medium transition hover:bg-card-2"
              :style="{
                height: '32px',
                borderRadius: '8px',
                color: panelMode === 'titles' ? 'var(--primary-deep)' : 'var(--ink-2)',
                background: panelMode === 'titles' ? 'var(--primary-soft)' : 'transparent',
                fontWeight: panelMode === 'titles' ? 600 : 500,
              }"
              @click="openTitleCandidates"
            >
              标题候选
            </button>
          </div>
        </Card>

        <!--
          模板区块 —— 框架模板 + AI 润色 Skill 两个下拉合并到一张卡，
          padding 紧凑，下拉框 width:100% 撑满卡片宽度（右栏 300px）。
        -->
        <Card padless class="flex-shrink-0">
          <div class="flex flex-col gap-3" :style="{ padding: '12px 14px' }">
            <div
              class="text-[10.5px] uppercase font-medium"
              :style="{ color: 'var(--ink-3)', letterSpacing: '1.5px' }"
            >
              模板区块
            </div>
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
          操作卡 —— 加高让整篇润色按钮和下面两个次按钮更显眼。padding
          从默认 pad-d 改为更舒展的 18px，主按钮高度 42 → 与 V1 设计
          稿里的视觉权重一致。
        -->
        <Card padless class="flex-shrink-0">
          <div class="flex flex-col gap-2.5" :style="{ padding: '18px' }">
            <button
              type="button"
              class="w-full inline-flex items-center justify-center gap-1.5 transition hover:brightness-95 disabled:opacity-50 disabled:cursor-not-allowed"
              :style="{
                height: '42px',
                fontSize: '13px',
                fontWeight: 500,
                borderRadius: '10px',
                background: 'var(--primary)',
                color: '#fff',
                border: '1px solid var(--primary)',
              }"
              :disabled="!article.draftText.trim() || polishing"
              @click="polishAll"
            >
              <Spinner v-if="polishing" :size="13" />
              <Icon v-else name="wand" :size="13" />
              <span>{{ polishing ? "润色中…" : "整篇润色" }}</span>
            </button>
            <div class="flex gap-2">
              <button
                type="button"
                class="flex-1 inline-flex items-center justify-center gap-1.5 transition hover:brightness-95 disabled:opacity-50 disabled:cursor-not-allowed"
                :style="{
                  height: '36px',
                  fontSize: '12px',
                  fontWeight: 500,
                  borderRadius: '10px',
                  background: 'var(--card-2)',
                  color: 'var(--ink-2)',
                  border: '1px solid var(--line)',
                }"
                :disabled="!article.lastRequest"
                @click="rerun"
              >
                <Icon name="refresh" :size="11" />
                <span>重新随机</span>
              </button>
              <button
                type="button"
                class="flex-1 inline-flex items-center justify-center gap-1.5 transition hover:brightness-95"
                :style="{
                  height: '32px',
                  fontSize: '11px',
                  fontWeight: 500,
                  borderRadius: '10px',
                  background: 'var(--card-2)',
                  color: 'var(--red)',
                  border: '1px solid var(--line)',
                }"
                @click="clearAll"
              >
                <Icon name="x" :size="11" />
                <span>清空</span>
              </button>
            </div>
            <button
              type="button"
              class="w-full inline-flex items-center justify-center gap-1.5 transition hover:brightness-95 disabled:opacity-50 disabled:cursor-not-allowed"
              :style="{
                height: '36px',
                fontSize: '12px',
                fontWeight: 500,
                borderRadius: '10px',
                background: 'var(--dark)',
                color: '#fbf7ec',
                border: '1px solid var(--dark)',
              }"
              @click="showExportModal = true"
            >
              <Icon name="copy" :size="12" />
              <span>导出文章</span>
            </button>
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
      导出弹窗 —— 严格按 V1 设计稿（精简版）：标签 + 大标题 + 关闭 X，
      下方 3 个格式卡片（Markdown / Word / 纯文本），底部 取消 / 导出。
      已移除"微信公众号 / 知乎专栏"以及三个附加选项 checkbox。
    -->
    <Teleport to="body">
      <div
        v-if="showExportModal"
        class="fixed inset-0 z-40 flex items-center justify-center"
        :style="{ background: 'rgba(28,26,23,0.4)' }"
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
            boxShadow: '0 18px 50px rgba(28,26,23,0.18)',
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
                color: '#fbf7ec',
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
        :style="{ background: 'rgba(28,26,23,0.4)' }"
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
