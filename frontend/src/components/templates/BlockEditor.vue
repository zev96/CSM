<script setup lang="ts">
/**
 * 单块区块编辑器 — 严格对齐 csm_gui/widgets/block_inspector.py 的字段布局：
 *
 *   eyebrow   "区块 N / M · 段落 / 标题 / ..."
 *   title     友好标题（label / title / text 的派生值）
 *   字段：
 *     paragraph        — 区块名 + 目录 + 段落高级（筛选 / 取值 + 子素材 / 链接）
 *     heading          — 序号 + 标题文本（+关键词）
 *     numbered_list    — 区块名 + 目录 + 编号样式 + 列表高级（筛选 / 取值）
 *     hero_brand       — 标题 + 编号样式 + 推荐理由前缀
 *     competitor_pool  — 目录 + 推荐理由前缀 + 对比池高级（筛选 / 取值）
 *     literal          — 固定文本
 *     test_framework   — 区块名 + 编号样式 + 框架/结果目录 + 主推/竞品标签 +
 *                        测试部分高级（测试项数量 + 跟随区块）
 *     最底部：删除此区块（红色描边）
 *
 *  pick_notes 既可以是 int，也可以是 {random_between: [min, max]}（schema 里
 *  PickCountSpec 的轻量子集），UI 用「素材数量 + 启用随机区间」交互。
 *
 *  paragraph 的 constraints 数组里如果含 "unique_notes" 视作勾选「不重复素材」。
 */
import { computed, ref, watch } from "vue";

import FormField from "@/components/forms/FormField.vue";
import FormInput from "@/components/forms/FormInput.vue";
import FormSelect from "@/components/forms/FormSelect.vue";
import Icon from "@/components/ui/Icon.vue";
import CascadePicker from "./CascadePicker.vue";
// MultiValuePicker 已下线 —— 段落筛选改为单选（用 FormSelect 替代）。
import { useSidecar } from "@/stores/sidecar";

const props = defineProps<{
  modelValue: any;
  /** 当前块在父列表中的 index（0-based）；用于「区块 N / M」的 eyebrow。 */
  index?: number;
  /** 父列表总块数。 */
  total?: number;
  /** 父列表里其它所有块（不含自身） — 用于「链接 / 跟随区块」下拉。 */
  siblings?: Array<{ id: string; label: string }>;
  /** Vault 叶子目录列表 — 喂给 CascadePicker 渲染折叠树。 */
  vaultDirs?: string[];
  /** 模板声明的结构版本；空 = 模板没有版本概念。 */
  versionOptions?: string[];
  /** 本块（竞品池）在榜单里的排位起点，用于「本池从 TOP{k} 开始」提示。 */
  startRank?: number;
}>();
const emit = defineEmits<{
  (e: "update:modelValue", v: any): void;
  (e: "delete"): void;
}>();

const block = computed(() => props.modelValue);

// ── 所属版本 ────────────────────────────────────────────────────────
const blockVersions = computed<string[]>(() => block.value.versions ?? []);

function toggleVersion(v: string, on: boolean) {
  const set = new Set(blockVersions.value);
  if (on) set.add(v);
  else set.delete(v);
  patch({ versions: [...set] });
}

// ── 卡片小节 ────────────────────────────────────────────────────────
const isCardMode = computed(() => (block.value.sections?.length ?? 0) > 0);
const isPool = computed(() => block.value.kind === "competitor_pool");

/** 打开卡片模式：给块补上卡片专属字段的默认值。 */
function enableCardMode() {
  // 卡片模式的开关是「结构性重建」sections —— 手填态的下标会失去所指，必须
  // 一起清（换块 watch 只在 block.id 变时清，开关卡片模式 id 不变）。否则
  // 关掉再开、重新加节后，某个从没选过自定义的小节会被卡在手填输入框里。
  sectionCustomKeys.value = [];
  if (isPool.value) {
    // 预填规范里约定的筛选（素材类型: 竞品卡）—— schema 强制卡片模式必须有
    // 筛选条件（否则同目录旧格式竞品笔记会混进名册），而筛选属性下拉是从
    // vault 已有笔记聚合的：卡还没写时下拉是空的，不预填就直接卡死。
    const existing = block.value.source?.filter ?? {};
    patch({
      source: {
        type: "notes_query",
        module: block.value.source?.module ?? "",
        filter: Object.keys(existing).length ? existing : { 素材类型: "竞品卡" },
      },
      sections: [{ label: "市场口碑数据", h2: "", required: true, pick_variants: 1 }],
      heading_template: block.value.heading_template ?? "### {tier} TOP{n}. {title}",
      tier_key: block.value.tier_key ?? "层级标签",
      label_layout: block.value.label_layout ?? "inline",
      card_separator: block.value.card_separator ?? "\n\n",
    });
  } else {
    patch({
      sections: [{ label: "市场口碑数据", module: null, filter: {}, pick_notes: 1, pick_variants_per_note: 1 }],
      source: block.value.source ?? { type: "notes_query", module: "", filter: {} },
      heading_template: block.value.heading_template ?? "### {tier} TOP{n}. {title}",
      tier: block.value.tier ?? "",
      label_layout: block.value.label_layout ?? "inline",
    });
  }
}

function disableCardMode() {
  sectionCustomKeys.value = [];    // 同 enableCardMode：结构性重建，清手填态
  patch({ sections: [] });
}

function addSection() {
  const sections = [...(block.value.sections ?? [])];
  sections.push(
    isPool.value
      ? { label: "", h2: "", required: true, pick_variants: 1 }
      : { label: "", module: null, filter: {}, pick_notes: 1, pick_variants_per_note: 1 },
  );
  patch({ sections });
}

function updateSection(i: number, p: Record<string, any>) {
  const sections = [...(block.value.sections ?? [])];
  sections[i] = { ...sections[i], ...p };
  patch({ sections });
}

function removeSection(i: number) {
  const sections = [...(block.value.sections ?? [])];
  sections.splice(i, 1);
  sectionCustomKeys.value = [];      // 下标会整体移位，别让手填标记串到别的小节
  patch({ sections });
}

function moveSection(i: number, dir: -1 | 1) {
  const sections = [...(block.value.sections ?? [])];
  const j = i + dir;
  if (j < 0 || j >= sections.length) return;
  [sections[i], sections[j]] = [sections[j], sections[i]];
  sectionCustomKeys.value = [];
  patch({ sections });
}

/** 小节的筛选值 —— 卡片主推小节沿用块级 filter 的单键形态。 */
function sectionFilterValue(sec: any): string {
  const v = Object.values(sec.filter ?? {})[0];
  return v === undefined ? "" : String(v);
}
function sectionFilterKey(sec: any): string {
  // 过去这里默认返回「素材类型」：filter 明明是空的，界面却显示一个用户从没
  // 选过的字段名，他填上值就把这个幽灵默认烙进了模板。真实 vault 里区分小节
  // 的字段可能叫「模块」，于是筛选恒空 —— 生成时报「没有符合条件的素材」，
  // 而目录里明明躺着素材。空就显示「不筛选」，别替用户猜。
  return Object.keys(sec.filter ?? {})[0] ?? "";
}
/** 小节可以覆盖目录 —— 属性集合得跟着它自己的目录走。 */
const sectionAttrs = ref<Record<string, VaultAttribute[]>>({});

function attrsForSection(sec: any): VaultAttribute[] {
  const blockMod = block.value?.source?.module || "";
  const mod = sec?.module || "";
  if (!mod || mod === blockMod) return vaultAttrs.value;
  return sectionAttrs.value[mod] ?? [];
}

function sectionKeyOptions(sec: any) {
  const attrs = attrsForSection(sec);
  const cur = sectionFilterKey(sec);
  const set = new Set<string>(cur ? [cur] : []);
  for (const a of attrs) set.add(a.key);
  const opts = Array.from(set).map((k) => {
    const meta = attrs.find((a) => a.key === k);
    return {
      label: meta ? `${k}  ·  ${meta.note_count} 篇` : `${k}  ·  自定义`,
      value: k,
    };
  });
  opts.push({ label: "＋ 自定义属性…", value: CUSTOM_KEY });
  return [{ label: "不筛选", value: "" }, ...opts];
}

function sectionValueOptions(sec: any): string[] {
  const key = sectionFilterKey(sec);
  if (!key) return [];
  const meta = attrsForSection(sec).find((a) => a.key === key);
  const base =
    meta && meta.value_count <= VALUE_OPTIONS_THRESHOLD
      ? meta.sample_values ?? []
      : [];
  // 已配置的值若不在样本里（素材改了名 / 之前手填过）也得显示出来，否则
  // 下拉退成占位符，用户看不出这条筛选其实还在，误以为没筛。只在本来就走
  // 下拉的分支补（高基数走 FormInput，值本身可见，不掺进来逼成单选）。
  const cur = sectionFilterValue(sec);
  if (base.length && cur && !base.includes(cur)) return [cur, ...base];
  return base;
}

function sectionValueHint(sec: any): string {
  const meta = attrsForSection(sec).find((a) => a.key === sectionFilterKey(sec));
  if (!meta || !meta.sample_values.length) return "筛选值";
  return `如：${meta.sample_values.slice(0, 2).join(" / ")}`;
}

/** 手填属性名的小节下标 —— 下拉里选了「自定义属性…」的。 */
const sectionCustomKeys = ref<number[]>([]);

function onSectionKeySelect(i: number, v: string) {
  if (v === CUSTOM_KEY) {
    if (!sectionCustomKeys.value.includes(i)) {
      sectionCustomKeys.value = [...sectionCustomKeys.value, i];
    }
    setSectionFilter(i, "", "");
    return;
  }
  sectionCustomKeys.value = sectionCustomKeys.value.filter((x) => x !== i);
  // 换字段必须清值 —— 不同字段取值集不同，留着旧值就是个永远筛不出东西的
  // 无效组合（而它看上去填得好好的）。
  setSectionFilter(i, v, "");
}

function setSectionFilter(i: number, key: string, value: string) {
  // 键非空就落库（值可以暂时留空）—— 早期实现在值为空时整条丢掉，用户先填
  // 的键就没了，界面还继续显示他敲的键，实际存的是默认值「素材类型」。
  const k = key.trim();
  updateSection(i, { filter: k ? { [k]: value } : {} });
}

// ── 覆盖度检查 ──────────────────────────────────────────────────────
const coverage = ref<any | null>(null);
const coverageLoading = ref(false);

// BlockEditor 实例在块之间复用，不重置的话切到另一个竞品池还显示上一个池的
// 体检报告 —— 运营会照着改错目录的素材。
watch(
  () => block.value?.id,
  () => {
    coverage.value = null;
    coverageLoading.value = false;
  },
);

/** 小节名与实际命中的 H2 不一致的行 —— 宽松匹配错配时的唯一线索。 */
const mismatchedRows = computed(() => {
  const rows = coverage.value?.rows ?? [];
  return rows
    .map((r: any) => ({
      path: r.path,
      model: r.model,
      mismatches: Object.entries(r.matched ?? {})
        .filter(([label, h2]) => h2 && h2 !== label)
        .map(([label, h2]) => ({ label, h2 })),
    }))
    .filter((r: any) => r.mismatches.length);
});

/** 卡片竞品池缺筛选条件 —— schema 会拒收，但错误只在保存时才弹。 */
const poolMissingFilter = computed(
  () => isPool.value && isCardMode.value
    && !Object.keys(block.value.source?.filter ?? {}).length,
);

function fillConventionalFilter() {
  patchSource({
    type: "notes_query",
    module: block.value.source?.module ?? "",
    filter: { 素材类型: "竞品卡" },
  });
}

/** 检查前的自查：目录必填、小节名必填。 */
const coverageBlocker = computed<string | null>(() => {
  if (!block.value.source?.module) return "先给竞品池选目录";
  const secs = block.value.sections ?? [];
  if (!secs.length) return "先添加小节";
  if (secs.some((x: any) => !String(x.label ?? "").trim())) return "有小节还没填名字";
  return null;
});

async function runCoverage() {
  if (coverageBlocker.value) return;
  coverageLoading.value = true;
  coverage.value = null;
  try {
    const r = await sidecar.client.post("/api/vault/card_coverage", {
      module: block.value.source?.module ?? "",
      filter: block.value.source?.filter ?? {},
      sections: (block.value.sections ?? []).map((x: any) => ({
        label: x.label,
        h2: x.h2 ?? "",
        required: x.required !== false,
      })),
      tier_key: block.value.tier_key ?? "层级标签",
    });
    coverage.value = r.data;
  } catch (e: any) {
    coverage.value = { error: apiError(e) };
  } finally {
    coverageLoading.value = false;
  }
}

/** sidecar 报错转人话：FastAPI 的 detail 可能是字符串，也可能是校验数组。 */
function apiError(e: any): string {
  const detail = e?.response?.data?.detail;
  // FastAPI 对**不存在的路由**回 404 + detail 恰好是字面量 "Not Found"，
  // 界面上就只剩这两个词，完全无法行动。而这个 404 有个很具体的根因：跑着的
  // sidecar 比界面旧（dev 下最典型 —— csm_sidecar 是 editable 装的，起 dev
  // 时没钉 PYTHONPATH 就会加载另一个 checkout 的 sidecar）。真路由自己抛的
  // 404 带的是具体 detail（如「vault root not found: ...」），不会被误伤。
  if (e?.response?.status === 404 && detail === "Not Found") {
    return "后端没有这个接口 —— 正在运行的 sidecar 比界面旧，重启一下应用"
      + "（开发环境重跑 scripts\\dev.ps1）。";
  }
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return `${detail[0]?.loc?.join(".")}: ${detail[0]?.msg}`;
  // 资料库在共享盘上时全量巡走最容易撞 axios 超时，而它原样吐的
  // "timeout of 60000ms exceeded" 既看不懂、也判断不出该重试还是该改配置。
  if (e?.code === "ECONNABORTED" || /timeout/i.test(String(e?.message ?? ""))) {
    return "扫描超时 —— 资料库在共享盘上时首次扫描较慢，稍后重试。";
  }
  return e?.message ?? String(e);
}

// ── 从目录识别小节（竞品池卡片模式）─────────────────────────────────
// 小节名原来纯手敲，得先去 Obsidian 里翻一遍卡片的 ## 标题再逐个抄进来，
// 抄错一个字这节就永远匹配不上（find_card_section 只做包含匹配，不做纠错）。
// 这里反查目录：卡里实际写了什么小节、每节多少篇有内容，一次列清。
interface DetectedSection {
  title: string;
  note_count: number;
  with_body: number;
}
const detectLoading = ref(false);
const detected = ref<DetectedSection[] | null>(null);
const detectError = ref<string | null>(null);
const detectNoteCount = ref(0);
const detectPicked = ref<string[]>([]);
const detectTruncated = ref(false);
/** 一篇都没捞到时的归因（后端 explain_empty_query）—— 目录错还是筛选错。 */
const detectHint = ref("");
/** 导入时做过的让步（跳过了谁、翻了谁的必需）—— 一律显式说，不静默。 */
const importNotice = ref<string[]>([]);

const detectBlocker = computed<string | null>(
  () => (block.value.source?.module ? null : "先给竞品池选目录"),
);

// 与上面 coverage 那条同理，但这里更要命：体检报告只是读，识别面板上的
// 「按目录替换」是**写**。残留下来切到别的块再点，就把 A 目录的小节写进
// B 块；切到 hero_brand 卡片块还会写成竞品卡形状（h2/required/pick_variants），
// 而 HeroSection 是 extra=ignore —— 那些键被静默丢弃、module/filter 被重置
// 成空，schema 照样放行、模板照样存下去，要到成稿才看得出来。
// 失效键必须含**目录与筛选**，不能只有 block.id：目录选择器在卡片模式之外、
// 随时可改，改它不动 id。而截断告警本身就在劝用户「目录选宽了，收窄一点」——
// 照做回来直接点替换，写进去的还是旧目录的小节，面板上的篇数也全是旧的。
// 返回**字符串**而不是数组/对象字面量：后者每次求值都是新引用，Object.is
// 恒判「变了」，任何无关编辑都会清掉面板。
const detectScopeKey = computed(() => [
  block.value?.id ?? "",
  block.value?.source?.module ?? "",
  JSON.stringify(block.value?.source?.filter ?? {}),
].join(" "));

watch(detectScopeKey, () => {
  dismissDetected();
  detectLoading.value = false;
  importNotice.value = [];
});

async function detectSections() {
  if (detectBlocker.value || detectLoading.value) return;
  const owner = detectScopeKey.value;   // 响应回来时块/目录可能都换了
  detectLoading.value = true;
  detected.value = null;
  detectError.value = null;
  importNotice.value = [];
  try {
    const r = await sidecar.client.post("/api/vault/card_sections", {
      module: block.value.source?.module ?? "",
      filter: block.value.source?.filter ?? {},
    });
    if (detectScopeKey.value !== owner) return;   // 迟到的响应不许落到别处
    const list: DetectedSection[] = r.data?.sections ?? [];
    detectNoteCount.value = r.data?.note_count ?? 0;
    detectHint.value = r.data?.hint ?? "";
    detectTruncated.value = !!r.data?.truncated;
    detected.value = list;
    // 默认勾「这个目录的卡都写了的小节」= 结构齐全。至于设不设**必需**是
    // 另一回事，那要看正文（contentComplete）—— 两个口径混用就会造出一份
    // 必然清空名册的配置。
    const full = list.filter(structureCovered).map((s) => s.title);
    detectPicked.value = full.length ? full : list.map((s) => s.title);
  } catch (e: any) {
    if (detectScopeKey.value !== owner) return;
    detectError.value = apiError(e);
  } finally {
    // 迟到的响应别去解锁**新**作用域正在跑的那次请求。
    if (detectScopeKey.value === owner) detectLoading.value = false;
  }
}

/** 这个目录的卡是不是都写了这个 ## 标题（结构齐全）。 */
function structureCovered(s: DetectedSection): boolean {
  return detectNoteCount.value > 0 && s.note_count >= detectNoteCount.value;
}

/**
 * 是不是每张卡的这一节都**有正文**。
 *
 * 「必需」只能按这个判，绝不能按 structureCovered：build_roster 的门槛是
 * section_body 非空，光有 ## 标题没正文的卡照样被整张剔出名册。而竞品卡
 * 几乎都是从骨架复制出来的 —— H2 早就齐了、正文才刚开始填，按结构判就会
 * 默认导出一份让名册直接清空、生成当场中止的配置。
 */
function contentComplete(s: DetectedSection): boolean {
  return detectNoteCount.value > 0 && s.with_body >= detectNoteCount.value;
}

const detectPicks = computed(
  () => (detected.value ?? []).filter((s) => detectPicked.value.includes(s.title)),
);

/**
 * 互为子串的标题。引擎 find_card_section 的第 2/3 档是包含匹配，所以「核心
 * 参数」这一节可能绑上 `## 核心参数对比` 的正文 —— 两节各印一遍同样的字。
 * 这里是全仓唯一同时拿到全部标题的地方，不报就没人报。
 *
 * 但**全覆盖的标题不报**：精确匹配是第一档，只要每张卡都写了 `## a`，它永远
 * 精确命中自己，不会去蹭别人的正文。只有确实有卡缺这个标题时宽松匹配才接管。
 */
const overlappingTitles = computed<Record<string, string[]>>(() => {
  const list = detected.value ?? [];
  const out: Record<string, string[]> = {};
  for (const a of list) {
    if (structureCovered(a)) continue;
    const hits = list
      .filter((b) => b.title !== a.title
        && (a.title.includes(b.title) || b.title.includes(a.title)))
      .map((b) => b.title);
    if (hits.length) out[a.title] = hits;
  }
  return out;
});

/** 落库小节 + 它对应的检出项（认亲带走的老小节也带着）。 */
type PlannedPair = [sec: any, from: DetectedSection | null];
interface SectionPlan {
  pairs: PlannedPair[];
  notes: string[];
}

/**
 * 算出「点这个按钮会落库成什么」。
 *
 * **面板上的数字和真正写进去的东西必须出自同一次计算。** 上一版是两套口径：
 * 上界按「勾选项 + contentComplete」算，而 replace 认亲带走的老小节是原样
 * `{...old}`、保留它自己的 required。卡片模式一启用就播下
 * `{市场口碑数据, required:true}`，而那正是规范里的约定 H2 名、必被认亲带走
 * —— 于是面板显示「最多 9」，落库却是两个必需节、真实上界 3。append 更狠：
 * 已有的必需老节压根不进上界计算，显示「最多 8」实际名册 0、生成直接中止。
 */
function planSections(mode: "replace" | "append"): SectionPlan {
  const picks = detectPicks.value;
  const list = detected.value ?? [];
  const cur: any[] = block.value.sections ?? [];
  const notes: string[] = [];
  if (!picks.length) return { pairs: [], notes };

  // 一对一认亲：认走一个就从池子里拿掉，否则「核心参数」和「核心参数对比」
  // 会抢同一节，落库出来两条指向同一处配置。
  const unclaimed = [...cur];
  const claimedBy = new Map<any, DetectedSection>();
  const claim = (s: DetectedSection) => {
    const hit = claimSection(unclaimed, s.title);
    if (hit) {
      unclaimed.splice(unclaimed.indexOf(hit), 1);
      claimedBy.set(hit, s);
    }
    return hit;
  };
  const fresh = (s: DetectedSection) => ({
    label: s.title,
    h2: "",
    required: contentComplete(s),
    pick_variants: 1,
  });

  let pairs: PlannedPair[];
  if (mode === "replace") {
    pairs = picks.map((s): PlannedPair => {
      const old = claim(s);
      return [old ? { ...old, label: old.label || s.title } : fresh(s), s];
    });
  } else {
    const added = picks.filter((s) => !claim(s));
    pairs = [
      // 已有小节留在原位，但要带上它对应的检出项 —— 找不到对应项说明目录里
      // 压根没有这个 ## ，它若是必需的，名册注定是 0。
      ...cur.map((s): PlannedPair => [
        s, claimedBy.get(s) ?? list.find((d) => d.title === topicOf(s)) ?? null,
      ]),
      ...added.map((s): PlannedPair => [fresh(s), s]),
    ];
  }

  // schema 的唯一性键是 label，而认亲键是 topic（h2 || label）—— 两者不是一
  // 回事，`{label:"甲", h2:"乙"}` 配上目录里同时有 `## 甲` 和 `## 乙` 就会产
  // 出两条 label「甲」，整个模板存不下去。比较用**原串**，与 schema 同口径
  // （trim 后再比会把「参数」和「参数 」这两条合法小节误判成重名）。
  const kept = new Map<string, any>();
  pairs = pairs.filter(([s]) => {
    const key = String(s.label ?? "");
    const survivor = kept.get(key);
    if (survivor !== undefined) {
      // 说清「谁没进来、幸存的那条绑的是哪个 ##」—— 只说「已跳过」会让人以为
      // 是无害去重，实际是勾选的一节没导入、绑定关系也变了。
      notes.push(
        `目录里的「${key}」没有导入：已有小节「${key}」对应的是 ## ${topicOf(survivor)}，`
        + `两者重名。想两个都用，先给其中一个改名。`,
      );
      return false;
    }
    kept.set(key, s);
    return true;
  });
  if (!pairs.length) return { pairs, notes };

  // schema 要求至少一个必需小节（否则空卡也能入册）。挑**正文最全**的那个，
  // 不是文档序第一个 —— 后者可能是个只有 1 篇有正文的节，名册直接塌到 1。
  if (!pairs.some(([s]) => s.required !== false)) {
    let bi = 0;
    pairs.forEach(([, d], i) => {
      if ((d?.with_body ?? -1) > (pairs[bi][1]?.with_body ?? -1)) bi = i;
    });
    const best = pairs[bi][1];
    pairs[bi] = [{ ...pairs[bi][0], required: true }, best];
    notes.push(
      `至少要有一个必需小节，已把「${pairs[bi][0].label}」设为必需`
      + (best && best.with_body === 0
        ? "；但它一篇正文都没有，名册会是空的，生成会中止" : ""),
    );
  }

  // 认亲带走的老小节保留用户设过的 required，不替他下调（那是他的显式选择），
  // 但正文不全时后果必须说出来。
  for (const [s, d] of pairs) {
    if (s.required !== false && d && !contentComplete(d)) {
      notes.push(
        `「${s.label}」是必需小节，但目录里只有 ${d.with_body}/${detectNoteCount.value} `
        + `篇有正文 —— 其余卡会被剔出名册。`,
      );
    }
  }
  return { pairs, notes };
}

const planReplace = computed(() => planSections("replace"));
const planAppend = computed(() => planSections("append"));

/**
 * 这份方案落库后最多几张竞品卡能入册 = 各必需小节 with_body 的最小值。
 *
 * 单位是**卡**不是竞品：with_body 数的是笔记，而 build_roster 按「品牌::型号」
 * 归并、还会丢掉缺 品牌/型号 frontmatter 的笔记，所以真实竞品数只会更少。
 */
function ceilingOf(plan: SectionPlan): number | null {
  const req = plan.pairs.filter(([s]) => s.required !== false);
  if (!req.length) return null;
  return Math.min(...req.map(([, d]) => d?.with_body ?? 0));
}

/** 有互为子串的标题时宽松匹配会额外救回一些卡，上界就只是个估计。 */
const ceilingIsExact = computed(() => !Object.keys(overlappingTitles.value).length);

function ceilingText(plan: SectionPlan): string {
  const n = ceilingOf(plan);
  if (n === null) return "";
  if (n === 0) return "一张卡都入不了册";
  return `${ceilingIsExact.value ? "最多" : "约"} ${n} 张卡入册`;
}

function toggleDetected(title: string) {
  detectPicked.value = detectPicked.value.includes(title)
    ? detectPicked.value.filter((x) => x !== title)
    : [...detectPicked.value, title];
}

function dismissDetected() {
  detected.value = null;
  detectError.value = null;
  detectHint.value = "";
  detectTruncated.value = false;
  detectPicked.value = [];
}

/** 小节的匹配主题 —— 与引擎 CompetitorSection.topic() 同口径。 */
function topicOf(sec: any): string {
  return String(sec.h2 || sec.label || "").trim();
}

/**
 * 给识别到的标题找已配好的小节，**与引擎 find_card_section 同优先级**：
 * 精确 → topic ⊂ H2 → H2 ⊂ topic。
 *
 * 只做精确认亲会两头错：`{label:"口碑"}` 这种简写在生成时明明绑得上
 * `## 市场口碑数据`，替换时却认不出来 —— 用户调过的候选数被清掉；追加时
 * 还会再补一条绑同一段正文的小节，成稿里同一段印两遍。
 */
function claimSection(pool: any[], title: string): any | undefined {
  return pool.find((s) => topicOf(s) === title)
    ?? pool.find((s) => { const t = topicOf(s); return !!t && title.includes(t); })
    ?? pool.find((s) => { const t = topicOf(s); return !!t && t.includes(title); });
}

/**
 * 把识别结果写进 sections —— 落库用的就是面板上算过的那份方案，不再另算。
 *
 * `replace` = 以目录为准重排小节；`append` = 只补当前没配的。两种模式都
 * 认亲：已配过的小节对上号后原样带走，用户调过的 必需 / 候选数不清回默认
 * —— 替换的是「有哪些节、什么顺序」，不是把配置推倒重来。
 */
function applyDetected(mode: "replace" | "append") {
  const plan = mode === "replace" ? planReplace.value : planAppend.value;
  if (!plan.pairs.length) return;
  const notes = [...plan.notes];
  sectionCustomKeys.value = [];    // 结构性重建，手填态的下标会失所指
  coverage.value = null;           // 旧报告按旧 label 算的，留着就是误导
  patch({ sections: plan.pairs.map(([s]) => s) });
  dismissDetected();
  importNotice.value = notes;
}

const HEADING_VARS = ["{tier}", "{n}", "{title}", "{brand}", "{model}", "{title_kw}"];

function insertHeadingVar(v: string) {
  patch({ heading_template: (block.value.heading_template ?? "") + v });
}

function patch(p: Record<string, any>) {
  emit("update:modelValue", { ...props.modelValue, ...p });
}
function patchSource(p: Record<string, any>) {
  emit("update:modelValue", {
    ...props.modelValue,
    source: { ...(props.modelValue.source ?? {}), ...p },
  });
}

const KIND_LABELS: Record<string, string> = {
  paragraph: "段落",
  heading: "标题",
  numbered_list: "编号列表",
  hero_brand: "主推",
  competitor_pool: "对比池",
  literal: "文本",
  test_framework: "测试部分",
};

const NUMBER_STYLES = [
  { label: "1.", value: "1." },
  { label: "一、", value: "一、" },
  { label: "无", value: "none" },
];

// friendlyTitle 已下线 —— 区块编辑器顶部大字标题按用户要求移除
// （跟下面 "区块名"/"标题" 输入框内容重复）。eyebrow「区块 N / 类型」
// 单独保留作为定位锚点。

const hasModule = computed(() =>
  ["paragraph", "numbered_list", "competitor_pool"].includes(block.value.kind),
);
const hasName = computed(() =>
  ["paragraph", "numbered_list", "test_framework"].includes(block.value.kind),
);

// ── 高级 · 筛选 (filter) ────────────────────────────────────────────────
// 之前直接把 rows computed 自 source.filter 反向派生，结果「+ 添加」
// 推一行 {key: "", value: ""} 进去，commit 时 trim() 把空 key 行扔掉，
// 反向派生又拿不回新行 → 视觉上点击没反应。
//
// 现在改成本地 ref 维护一份编辑态：
//   - 块切换 / source.filter 由外部变化时 watch 同步过来
//   - 用户操作只改本地 rows，再 debounced 写回 source.filter
// 这样空 key 行可以保留，用户填了 key 才落到真实 dict 里。
interface FilterRow {
  key: string;
  value: string;
}
const filterRows = ref<FilterRow[]>([]);

function rowsFromBlock(b: any): FilterRow[] {
  const f = b?.source?.filter ?? {};
  return Object.entries(f).map(([k, v]) => ({
    key: k,
    value: Array.isArray(v) ? v.join(", ") : String(v ?? ""),
  }));
}

// 只 watch 区块切换，不 watch source.filter —— 本地编辑时 filter 是
// commitFilters 的**输出**，不该再倒灌回 filterRows。否则：用户先选 key
// → commitFilters 因为 value 为空跳过这行 → source.filter = {} → watch
// 把这行从 UI 抹掉，用户感觉"点了 key 就消失"。
//
// 历史上这里有个 same 检查试图避免抹除，但它依赖 incoming.length ===
// filterRows.length，而"用户刚选 key 但 value 还空"恰好就是 length
// 不等的场景，所以 same 永远 false，本地状态被吃掉。
// 按用户要求改为单选 —— 不再支持多行 filter 也不再支持多值。filterRows
// 永远 length === 1。老数据如果有多行/多值，watch 时只保留 first row +
// first value（不破坏 source.filter 已存在的其它条目，但 UI 只暴露一个）。
watch(
  () => block.value?.id,
  () => {
    const rows = rowsFromBlock(block.value);
    if (rows.length === 0) {
      filterRows.value = [{ key: "", value: "" }];
    } else {
      const first = rows[0];
      // 若 value 是多值（逗号分隔），只取第一个
      const v = first.value.split(",")[0]?.trim() ?? "";
      filterRows.value = [{ key: first.key, value: v }];
    }
  },
  { immediate: true },
);

function commitFilters() {
  const out: Record<string, any> = {};
  // 单选模式下只看 filterRows[0]
  const r = filterRows.value[0];
  if (r) {
    const key = r.key.trim();
    const value = r.value.trim();
    if (key && value) {
      out[key] = value;
    }
  }
  patchSource({ filter: out });
}

function updateFilterRow(i: number, p: Partial<FilterRow>) {
  const old = filterRows.value[i];
  const next = { ...old, ...p };
  // 切 key 时清掉 value（不同属性取值集不同，残留旧值会变成无效筛选）
  if (p.key !== undefined && p.key !== old.key) {
    next.value = "";
  }
  filterRows.value[i] = next;
  commitFilters();
}

// ── Vault 属性自动补全 ─────────────────────────────────────────
// 旧的 key 字段是 free-text，用户得自己记得 vault 笔记 frontmatter
// 里写的 attribute 名字（"素材类型" / "核心关键词" 等），打错一个字
// 整个 filter 就失效。改成下拉：调 /api/vault/attributes 拿当前 module
// 范围内出现过的 key 列表，FormSelect 直接展示。
//
// 不挂在 sidecar store 里 cache —— 不同 block 可能 scope 到不同
// module，每个 BlockEditor 实例按自己的 source.module 单独拉一次。
// API 已经返回了 sample_values，这里把它存下来给 value 输入框做
// placeholder 提示（首条 sample 拿来用）。
const sidecar = useSidecar();
interface VaultAttribute {
  key: string;
  note_count: number;
  value_count: number;
  sample_values: string[];
}
const vaultAttrs = ref<VaultAttribute[]>([]);
const attrsLoading = ref(false);
const attrsError = ref<string | null>(null);

/** 用户点了「自定义属性…」后切成手填输入框（按块重置）。 */
const customKeyMode = ref(false);
const CUSTOM_KEY = "__custom__";

watch(
  () => block.value?.id,
  () => {
    customKeyMode.value = false;
    sectionCustomKeys.value = [];   // 换块才清，不再每次无关编辑都重置（R1）
  },
);

function onKeySelect(v: string) {
  if (v === CUSTOM_KEY) {
    customKeyMode.value = true;
    updateFilterRow(0, { key: "" });
    return;
  }
  customKeyMode.value = false;
  updateFilterRow(0, { key: v });
}

const attrKeyOptions = computed(() => {
  // 当前 filterRows 已经选过的 key 也得在选项里（不然切回 BlockEditor
  // 时已选的 key 会显示空白）。合并 vault scan 出来的 + 当前已用的。
  const usedKeys = filterRows.value.map((r) => r.key).filter(Boolean);
  const set = new Set<string>(usedKeys);
  for (const a of vaultAttrs.value) set.add(a.key);
  const opts = Array.from(set).map((k) => {
    const meta = vaultAttrs.value.find((a) => a.key === k);
    const label = meta
      ? `${k}  ·  ${meta.note_count} 篇`
      : `${k}  ·  自定义`;
    return { label, value: k };
  });
  // 末位插「自定义属性…」—— 下拉只列 vault 里已存在的属性，素材还没写
  // 的时候（先配模板后写素材是常见顺序）它是空的，没这一项就填不进任何
  // 筛选条件，而卡片模式的 schema 又强制要求有筛选 → 模板永远存不下去。
  opts.push({ label: "＋ 自定义属性…", value: CUSTOM_KEY });
  // 首位插「不筛选」—— 单选模式下用户没有"删除筛选行"按钮，得在
  // 下拉里能选回空（覆盖之前选过的 key）
  return [{ label: "不筛选", value: "" }, ...opts];
});

function valueHintFor(key: string): string {
  const meta = vaultAttrs.value.find((a) => a.key === key);
  if (!meta || !meta.sample_values.length) return "如：引言乱象";
  // 取 sample 的前 2 个拼成示例，截断避免 placeholder 过长。
  const head = meta.sample_values.slice(0, 2).join(" / ");
  return `如：${head}`;
}

const VALUE_OPTIONS_THRESHOLD = 20;

function valueOptionsFor(key: string): string[] {
  const meta = vaultAttrs.value.find((a) => a.key === key);
  if (!meta || meta.value_count > VALUE_OPTIONS_THRESHOLD) return [];
  const base = meta.sample_values ?? [];
  // 见 sectionValueOptions：已配置但不在样本里的值也要显示，别让下拉退成
  // 占位符把「其实还在筛」藏起来。
  const cur = filterRows.value[0]?.value ?? "";
  if (base.length && cur && !base.includes(cur)) return [cur, ...base];
  return base;
}

async function fetchAttrsRaw(): Promise<VaultAttribute[]> {
  const moduleScope: string | undefined = block.value?.source?.module;
  const r = await sidecar.client.get("/api/vault/attributes", {
    params: moduleScope ? { module: moduleScope } : {},
  });
  return r.data?.attributes ?? [];
}

async function loadVaultAttrs() {
  attrsLoading.value = true;
  attrsError.value = null;
  try {
    vaultAttrs.value = await fetchAttrsRaw();
  } catch (e: any) {
    if (e?.response?.status === 409) {
      // 409 = sidecar 还没有 vault 索引（lifespan 自动扫挂了 / 还没起来 /
      // 用户首次配置 vault 后还没重启）。主动触发一次 scan + retry。
      try {
        await sidecar.client.post("/api/vault/scan", {});
        vaultAttrs.value = await fetchAttrsRaw();
      } catch (inner: any) {
        const status = inner?.response?.status;
        if (status === 400) {
          attrsError.value = "尚未配置素材库 — 请在设置中指定 Vault";
        } else if (status === 404) {
          attrsError.value = "素材库目录不存在 — 请检查设置中的 Vault 路径";
        } else {
          attrsError.value = inner?.message ?? String(inner);
        }
        vaultAttrs.value = [];
      }
    } else {
      attrsError.value = e?.message ?? String(e);
      vaultAttrs.value = [];
    }
  } finally {
    attrsLoading.value = false;
  }
}

// 切换 block 或者 module 变化时重新拉一次。第一次 mount 也会触发
// （immediate: true）。
watch(
  // 返回稳定字符串而不是 [id, module] 数组：数组字面量每次都是新引用，
  // Object.is 判定恒为「变了」，于是改任何无关字段（标题、抽几篇……）都会
  // 白白重拉一次属性。拼成字符串后只有 id / 目录真变了才触发。
  () => `${block.value?.id ?? ""}\u0000${block.value?.source?.module ?? ""}`,
  () => {
    if (
      block.value &&
      ["paragraph", "numbered_list", "competitor_pool", "hero_brand"]
        .includes(block.value.kind)
    ) {
      loadVaultAttrs();
    }
  },
  { immediate: true },
);

/** 取某小节目录的属性；对齐块级 409→扫描→重试。取不到返回 null（不缓存）。 */
async function fetchSectionAttrs(mod: string): Promise<VaultAttribute[] | null> {
  try {
    const r = await sidecar.client.get("/api/vault/attributes", {
      params: { module: mod },
    });
    return r.data?.attributes ?? [];
  } catch (e: any) {
    if (e?.response?.status === 409) {
      try {
        await sidecar.client.post("/api/vault/scan", {});
        const r = await sidecar.client.get("/api/vault/attributes", {
          params: { module: mod },
        });
        return r.data?.attributes ?? [];
      } catch {
        return null;
      }
    }
    return null;
  }
}

// 主推卡小节各自覆盖目录时，再按小节目录补拉一次（块级目录的那份已有）。
watch(
  () =>
    `${block.value?.id ?? ""}\u0001` +
    (block.value?.sections ?? [])
      .map((s: any) => String(s?.module ?? ""))
      .join("\u0000"),
  async () => {
    const blockMod = block.value?.source?.module || "";
    const mods = new Set<string>(
      (block.value?.sections ?? [])
        .map((s: any) => String(s?.module ?? ""))
        .filter((m: string) => m && m !== blockMod),
    );
    for (const mod of mods) {
      if (sectionAttrs.value[mod]) continue;
      const attrs = await fetchSectionAttrs(mod);
      // 失败不写空数组：一次冷启动 409 不该把这个目录永久钉成空下拉。不缓存
      // 就还留着重试的余地，而 __custom__ 手填出口始终在，用户不会被卡。
      if (attrs) sectionAttrs.value = { ...sectionAttrs.value, [mod]: attrs };
    }
  },
  { immediate: true },
);

// ── 高级 · 取值（pick_notes / pick_count） ─────────────────────────────
const pickField = computed(() =>
  block.value.kind === "test_framework" ? "pick_count" : "pick_notes",
);
const rawPick = computed(() => block.value[pickField.value]);
const isRange = computed(
  () => typeof rawPick.value === "object" && rawPick.value?.random_between,
);
const pickMin = computed(() => {
  if (isRange.value) return Number(rawPick.value.random_between?.[0] ?? 1);
  return typeof rawPick.value === "number" ? rawPick.value : 1;
});
const pickMax = computed(() => {
  if (isRange.value)
    return Number(rawPick.value.random_between?.[1] ?? pickMin.value + 1);
  return Math.max(pickMin.value + 1, 2);
});
function setPick(opts: { min?: number; max?: number; range?: boolean }) {
  const min = Math.max(1, opts.min ?? pickMin.value);
  const max = Math.max(min + 1, opts.max ?? pickMax.value);
  const range = opts.range ?? isRange.value;
  patch({
    [pickField.value]: range ? { random_between: [min, max] } : min,
  });
}
function toggleRange(on: boolean) {
  setPick({ range: on, min: pickMin.value, max: Math.max(pickMin.value + 1, pickMax.value) });
}

// ── 高级 · 子素材 / 不重复（paragraph + numbered_list + competitor_pool） ────
// 三种块都从 notes_query 抽笔记，共用同一套"每篇抽几个变体 + 同池不重复"
// 语义。schema 上 numbered_list / competitor_pool 默认 constraints=
// ["unique_notes"] + pick_variants_per_note=1，与历史 sampler 里的硬编码
// 行为一致；UI 上把这两个开关暴露出来允许调整。
//
// **卡片模式除外**：sample_competitor_cards 只读 pick_notes 和每节的
// pick_variants，pick_variants_per_note / constraints 一个都不碰；竞品又是
// 恒不重复抽的（榜单里 TOP2 与 TOP3 同款毫无意义，sample_roster 明确不看
// unique_notes 开关）。摆着能调却不生效，跟「幽灵默认字段」是同一类坑。
const supportsSubMaterial = computed(() =>
  !isCardMode.value
  && ["paragraph", "numbered_list", "competitor_pool"].includes(block.value.kind),
);
const uniqueNotes = computed(() =>
  (block.value.constraints ?? []).includes("unique_notes"),
);
function toggleUniqueNotes(on: boolean) {
  const set = new Set<string>(block.value.constraints ?? []);
  if (on) set.add("unique_notes");
  else set.delete("unique_notes");
  patch({ constraints: Array.from(set) });
}

// ── 高级 · 链接 / 跟随（depends_on / follow_slot） ─────────────────────
// paragraph：depends_on 是 string[]
// test_framework：follow_slot 是 "id1+id2" 这种字符串
const linkedIds = computed<string[]>(() => {
  const b = block.value;
  if (b.kind === "paragraph") return b.depends_on ?? [];
  if (b.kind === "test_framework") {
    return (b.follow_slot ?? "")
      .split("+")
      .map((s: string) => s.trim())
      .filter(Boolean);
  }
  return [];
});
function setLinked(ids: string[]) {
  if (block.value.kind === "paragraph") {
    patch({ depends_on: ids });
  } else if (block.value.kind === "test_framework") {
    patch({ follow_slot: ids.join("+") });
  }
}
function toggleLink(id: string, on: boolean) {
  const set = new Set(linkedIds.value);
  if (on) set.add(id);
  else set.delete(id);
  setLinked(Array.from(set));
}
const linkButtonText = computed(() => {
  const ids = linkedIds.value;
  if (!ids.length) return "未链接";
  const map = new Map((props.siblings ?? []).map((s) => [s.id, s.label]));
  const labels = ids.map((id) => map.get(id) ?? id);
  const joined = labels.join("、");
  return joined.length > 30 ? joined.slice(0, 28) + "…" : joined;
});

// 链接下拉的开/关 — 简单 v-if，外层 click outside 由父容器的滚动天然吞掉。
const linkOpen = ref(false);

// ── + 关键词 ─────────────────────────────────────────────────────────
function insertKeyword(field: "text") {
  const cur = block.value[field] ?? "";
  patch({ [field]: cur + "{keyword}" });
}
</script>

<template>
  <div class="flex flex-col gap-3">
    <!--
      eyebrow only —— 大字 friendlyTitle 标题按用户要求移除（跟下面的
      「区块名」/「标题」输入框内容重复，看着是一个 block 名字写两次）。
      eyebrow「区块 N / 类型」保留作为定位锚点。
    -->
    <div>
      <div
        class="text-[11.5px]"
        :style="{ color: 'var(--ink-3)', letterSpacing: '0.6px' }"
      >
        <template v-if="typeof index === 'number' && total">
          区块 {{ index + 1 }} / {{ total }}
        </template>
        <template v-else>—</template>
        · {{ KIND_LABELS[block.kind] ?? block.kind }}
      </div>
    </div>

    <!-- ── 区块名（paragraph / numbered_list / test_framework） ────── -->
    <FormField v-if="hasName" label="区块名">
      <FormInput
        :model-value="block.label ?? ''"
        debounce="live"
        @update:model-value="(v) => patch({ label: String(v ?? '') })"
      />
    </FormField>

    <!-- ── 标题（hero_brand） ────────────────────────────────────────── -->
    <FormField v-if="block.kind === 'hero_brand'" label="标题">
      <FormInput
        :model-value="block.title ?? ''"
        debounce="live"
        placeholder="如：CEWEY DS18"
        @update:model-value="(v) => patch({ title: String(v ?? '') })"
      />
    </FormField>

    <!-- ── 序号（heading） ──────────────────────────────────────────── -->
    <FormField v-if="block.kind === 'heading'" label="序号">
      <FormInput
        :model-value="block.index ?? ''"
        :width="120"
        debounce="live"
        placeholder="如：一"
        @update:model-value="(v) => patch({ index: String(v ?? '') })"
      />
    </FormField>

    <!-- ── 标题文本（heading）— 带 + 关键词 ───────────────────────────── -->
    <div v-if="block.kind === 'heading'" class="flex flex-col gap-1.5">
      <div class="flex items-center gap-2">
        <div class="text-[12px]" :style="{ color: 'var(--ink-3)' }">标题文本</div>
        <span class="flex-1" />
        <button
          type="button"
          class="inline-flex h-[22px] items-center px-2.5 text-[11px]"
          :style="{
            color: 'var(--primary-deep)',
            border: '1px solid rgba(238,106,42,0.3)',
            borderRadius: '11px',
            background: 'transparent',
          }"
          title="光标位置插入 {keyword}"
          @click="insertKeyword('text')"
        >
          + 关键词
        </button>
      </div>
      <FormInput
        :model-value="block.text ?? ''"
        debounce="live"
        placeholder="如：{keyword} 推荐"
        @update:model-value="(v) => patch({ text: String(v ?? '') })"
      />
    </div>

    <!-- ── 编号样式（numbered_list / hero_brand / test_framework） ──── -->
    <FormField
      v-if="['numbered_list', 'hero_brand', 'test_framework'].includes(block.kind)"
      label="编号样式"
    >
      <FormSelect
        :model-value="block.number_style ?? '1.'"
        :options="NUMBER_STYLES"
        :width="120"
        @update:model-value="(v) => patch({ number_style: String(v) })"
      />
    </FormField>

    <!--
      推荐理由前缀 —— 只在 hero_brand 显示。competitor_pool 按用户要求
      不再单独设置，直接继承前面 hero_brand 的 reason_label（assembler
      render.py:195 已经做了 "competitor_pool inherits the preceding
      hero's reason_label" 的回退，UI 隐藏即可，无需后端改动）。
    -->
    <FormField
      v-if="block.kind === 'hero_brand'"
      label="推荐理由前缀"
    >
      <FormInput
        :model-value="block.reason_label ?? '推荐理由：'"
        debounce="live"
        placeholder="如：推荐理由："
        @update:model-value="(v) => patch({ reason_label: String(v ?? '') })"
      />
    </FormField>

    <!-- ── 所属版本（模板声明了版本组才显示）─────────────────────── -->
    <FormField v-if="(versionOptions?.length ?? 0) > 0" label="所属版本">
      <div class="flex flex-wrap gap-1.5">
        <button
          v-for="opt in versionOptions"
          :key="opt"
          type="button"
          class="rounded px-2 py-1 text-[11.5px] transition"
          :style="{
            background: blockVersions.includes(opt) ? 'var(--primary-soft)' : 'var(--card-2)',
            border: '1px solid var(--line)',
          }"
          @click="toggleVersion(opt, !blockVersions.includes(opt))"
        >
          {{ opt }}
        </button>
      </div>
      <p class="mt-1 text-[11px] text-ink-3">
        {{
          blockVersions.length
            ? "只在选中的版本里出现"
            : "未选 = 每个版本都出现（公共块）。推荐区的块务必选上版本，漏标会让两个版本的内容混在一起。"
        }}
      </p>
    </FormField>

    <!-- ── 榜单卡片模式（hero_brand / competitor_pool）────────────── -->
    <div
      v-if="block.kind === 'hero_brand' || isPool"
      class="mt-1"
      style="border-top: 1px solid var(--line); padding-top: 10px"
    >
      <div class="flex items-center gap-2">
        <span class="text-[12px] font-medium">榜单卡片</span>
        <span class="text-[11px] text-ink-3">标题行 + 加粗小节，每个点独立随机</span>
        <button
          type="button"
          class="ml-auto text-[11px] text-ink-3 hover:text-ink"
          @click="isCardMode ? disableCardMode() : enableCardMode()"
        >
          {{ isCardMode ? "关闭卡片模式" : "启用卡片模式" }}
        </button>
      </div>

      <template v-if="isCardMode">
        <div
          v-if="isPool && (startRank ?? 0) > 1"
          class="mt-2 rounded px-2 py-1 text-[11px] text-ink-3"
          :style="{ background: 'var(--card-2)' }"
        >
          本池排位从 TOP{{ startRank }} 开始（接续前面的卡）
        </div>

        <!--
          缺筛选条件就地提示。schema 强制卡片模式必须有筛选（否则同目录的
          旧格式竞品笔记会混进名册），但那个错误要等点保存才弹，而下面的
          筛选下拉在素材还没写时是空的 —— 不给这条出路就是死锁。
        -->
        <div
          v-if="poolMissingFilter"
          class="mt-2 flex flex-wrap items-center gap-2 rounded px-2 py-1.5 text-[11px]"
          :style="{ background: 'var(--card-2)', borderLeft: '2px solid var(--amber)' }"
        >
          <span>
            卡片模式需要筛选条件，否则同目录下的旧格式竞品笔记会混进名册。
          </span>
          <button
            type="button"
            class="underline"
            :style="{ color: 'var(--ink-2)' }"
            @click="fillConventionalFilter"
          >
            填入约定值（素材类型 = 竞品卡）
          </button>
        </div>

        <FormField label="标题行模板" class="mt-2">
          <FormInput
            :model-value="block.heading_template ?? '### {tier} TOP{n}. {title}'"
            debounce="live"
            @update:model-value="(v) => patch({ heading_template: String(v ?? '') })"
          />
          <div class="mt-1 flex flex-wrap gap-1">
            <button
              v-for="hv in HEADING_VARS"
              :key="hv"
              type="button"
              class="rounded px-1.5 py-0.5 text-[10.5px] text-ink-3 hover:text-ink"
              :style="{ background: 'var(--card-2)' }"
              @click="insertHeadingVar(hv)"
            >
              {{ hv }}
            </button>
          </div>
        </FormField>

        <FormField
          v-if="block.kind === 'hero_brand'"
          label="默认目录"
          class="mt-2"
        >
          <CascadePicker
            :model-value="block.source?.module ?? ''"
            :dirs="vaultDirs ?? []"
            placeholder="小节没单独指定目录时用它"
            @update:model-value="(v) => patchSource({ type: 'notes_query', module: String(v ?? '') })"
          />
        </FormField>

        <FormField v-if="block.kind === 'hero_brand'" label="层级标签" class="mt-2">
          <FormInput
            :model-value="block.tier ?? ''"
            debounce="live"
            placeholder="如：国内外知名品牌-综合性能首选"
            @update:model-value="(v) => patch({ tier: String(v ?? '') })"
          />
        </FormField>
        <FormField v-else label="层级标签字段" class="mt-2">
          <FormInput
            :model-value="block.tier_key ?? '层级标签'"
            debounce="live"
            placeholder="竞品卡 frontmatter 里的字段名"
            @update:model-value="(v) => patch({ tier_key: String(v ?? '') })"
          />
        </FormField>

        <FormField label="小节标签排版" class="mt-2">
          <FormSelect
            :model-value="block.label_layout ?? 'inline'"
            :options="[
              { label: '同行：**小节名** ：正文', value: 'inline' },
              { label: '独占一行', value: 'line' },
            ]"
            width="100%"
            @update:model-value="(v) => patch({ label_layout: String(v) })"
          />
        </FormField>

        <div v-if="isPool" class="mt-2">
          <button
            type="button"
            class="text-[11px]"
            :style="{ color: coverageBlocker ? 'var(--ink-3)' : 'var(--ink-2)', opacity: coverageBlocker ? 0.5 : 1 }"
            :disabled="coverageLoading || !!coverageBlocker"
            :title="coverageBlocker ?? '看看哪些竞品能上榜、谁缺哪节、型号写歪没有'"
            @click="runCoverage"
          >
            {{ coverageLoading ? "检查中…" : "覆盖度检查" }}
          </button>
          <span v-if="coverageBlocker" class="ml-1.5 text-[11px] text-ink-3">
            {{ coverageBlocker }}
          </span>
          <div
            v-if="coverage"
            class="mt-1.5 rounded p-2 text-[11px]"
            :style="{ background: 'var(--card-2)', border: '1px solid var(--line)' }"
          >
            <template v-if="coverage.error">
              <span class="text-red">{{ coverage.error }}</span>
            </template>
            <template v-else>
              <div class="mb-1">
                合格竞品 {{ coverage.eligible_count }} / {{ coverage.competitors.length }}
                （目录里 {{ coverage.note_count }} 张卡）
              </div>
              <div
                v-for="c in coverage.competitors"
                :key="c.identity_key"
                class="flex items-center gap-1.5 py-0.5"
              >
                <span :style="{ color: c.eligible ? 'var(--ink-2)' : 'var(--red)' }">
                  {{ c.eligible ? "✓" : "✕" }}
                </span>
                <span>{{ c.title }}</span>
                <span v-if="c.card_count > 1" class="text-ink-3">{{ c.card_count }} 张卡</span>
                <span v-if="c.tiers.length > 1" class="text-ink-3">
                  层级标签不一致：{{ c.tiers.join("/") }}
                </span>
              </div>

              <!--
                小节 → 实际命中的 H2 对照。匹配是宽松的（H2 名与小节名互为
                子串即算命中），错配时这是唯一的诊断线索：一张只有「## 口碑」
                的卡会被判定覆盖了「市场口碑数据」，不摊开就只显示一个 ✓。
              -->
              <div v-if="mismatchedRows.length" class="mt-1.5">
                <div class="text-ink-3">小节命中的 H2 与小节名不一致：</div>
                <div v-for="r in mismatchedRows" :key="r.path" class="text-ink-3">
                  {{ r.model }}：
                  <span v-for="(m, li) in r.mismatches" :key="li">
                    {{ m.label }} ← 「{{ m.h2 }}」{{ li < r.mismatches.length - 1 ? "，" : "" }}
                  </span>
                </div>
              </div>
              <div
                v-for="r in coverage.rows.filter((x: any) => x.missing_required.length)"
                :key="r.path"
                class="mt-1 text-ink-3"
              >
                {{ r.model }} 缺「{{ r.missing_required.join("、") }}」——
                该卡实有小节：{{ r.h2_present.join("、") || "（无）" }}
              </div>
              <div
                v-for="(x, xi) in coverage.notes_missing_identity"
                :key="'ni' + xi"
                class="mt-1 text-ink-3"
              >
                缺品牌/型号 frontmatter：{{ x }}
              </div>
              <div
                v-for="(x, xi) in coverage.stem_conflicts"
                :key="'sc' + xi"
                class="mt-1"
                :style="{ color: 'var(--red)' }"
              >
                文件名重复「{{ x.stem }}」——重随会串到别的竞品，请改成带型号的文件名
              </div>
              <div
                v-for="(x, xi) in coverage.near_duplicates"
                :key="'nd' + xi"
                class="mt-1 text-ink-3"
              >
                疑似同款各占一个排位：{{ x.join(" / ") }}
              </div>
            </template>
          </div>
        </div>

        <div class="mt-3">
          <div class="mb-1.5 flex items-center gap-2">
            <span class="text-[12px] font-medium">小节</span>
            <span class="text-[11px] text-ink-3">
              {{ isPool ? "对应竞品卡里的 ## 小节" : "每节独立配目录与筛选" }}
            </span>
            <span class="ml-auto flex items-center gap-3">
              <button
                v-if="isPool"
                type="button"
                class="text-[11px]"
                :style="{
                  color: detectBlocker ? 'var(--ink-3)' : 'var(--ink-2)',
                  opacity: detectBlocker ? 0.5 : 1,
                }"
                :disabled="detectLoading || !!detectBlocker"
                :title="detectBlocker ?? '扫这个目录里的竞品卡，列出它们实际写了哪些 ## 小节'"
                @click="detectSections"
              >
                {{ detectLoading ? "识别中…" : "从目录识别" }}
              </button>
              <button
                type="button"
                class="text-[11px] text-ink-3 hover:text-ink"
                @click="addSection"
              >
                + 添加小节
              </button>
            </span>
          </div>

          <!--
            识别结果面板。刻意做成「先看再导」而不是识别完直接落库：小节的
            必需/候选数是用户逐个调过的，静默覆盖等于把他的配置吃掉；而且
            目录选错时（识别出一堆不相干的 H2）也得有机会退出来。
          -->
          <div
            v-if="isPool && (detectError || detected)"
            class="mb-2 rounded p-2 text-[11px]"
            :style="{ background: 'var(--card-2)', border: '1px solid var(--line)' }"
          >
            <div v-if="detectError" :style="{ color: 'var(--red)' }">
              {{ detectError }}
            </div>
            <!--
              「一篇都没捞到」和「捞到了但没写 ## 」是两回事，提示必须分开：
              目录/筛选写错时说「这些笔记里没有 ## 小节」会把人引去改素材，
              而素材根本没毛病。空池归因由后端 explain_empty_query 给。
            -->
            <div v-else-if="detected && !detectNoteCount" class="text-ink-3">
              这个目录 + 筛选没匹配到任何笔记。{{ detectHint }}
            </div>
            <div v-else-if="detected && !detected.length" class="text-ink-3">
              这个目录的 {{ detectNoteCount }} 篇笔记里没有任何 ## 小节 ——
              竞品卡要写成「## 小节名」加节内 ①②③，只有 frontmatter 的笔记识别不出东西。
            </div>
            <template v-else-if="detected">
              <div class="mb-1.5 text-ink-3">
                共 {{ detectNoteCount }} 篇卡。「有内容」= 该小节底下真写了正文；
                只有标题没内容的，这张卡照样进不了名册。
              </div>
              <div v-if="detectTruncated" class="mb-1.5" :style="{ color: 'var(--amber)' }">
                这个目录有超过 50 种不同的 ## 标题，只列出了前 50 个 ——
                多半是目录选宽了或混进了别的素材，「按目录替换」会删掉没列出来的小节。
              </div>
              <label
                v-for="s in detected"
                :key="s.title"
                class="flex flex-wrap items-center gap-1.5 py-0.5"
              >
                <input
                  type="checkbox"
                  :checked="detectPicked.includes(s.title)"
                  @change="toggleDetected(s.title)"
                />
                <span class="font-medium">{{ s.title }}</span>
                <span class="text-ink-3">
                  {{ s.note_count }}/{{ detectNoteCount }} 篇有此小节 ·
                  {{ s.with_body }} 篇有内容
                </span>
                <!--
                  三条告警对应三种不同的后果，不能合并成一句「非全覆盖」：
                  正文全空 = 设必需就名册清零；正文不全 = 必需会剔掉那几张卡；
                  结构不全 = 有些卡压根没这一节。
                -->
                <span v-if="!s.with_body" :style="{ color: 'var(--red)' }">
                  一篇正文都没有，设为必需会让名册清空
                </span>
                <span v-else-if="!contentComplete(s)" :style="{ color: 'var(--amber)' }">
                  {{ s.note_count - s.with_body }} 篇只有标题没正文
                </span>
                <span v-else-if="!structureCovered(s)" :style="{ color: 'var(--amber)' }">
                  {{ detectNoteCount - s.note_count }} 篇没有这一节
                </span>
                <span
                  v-if="overlappingTitles[s.title]"
                  :style="{ color: 'var(--amber)' }"
                >
                  与「{{ overlappingTitles[s.title].join("」「") }}」互为子串，
                  会绑到同一段正文各印一遍
                </span>
              </label>
              <!--
                名册上界挂在**各自的按钮**上，而不是笼统写一个数：两种模式落
                库出来的必需集合不同，上界也就不同。数字由 planSections 出，
                与真正写进去的小节同源 —— 上一版两套口径，面板说 9 实际 3。
              -->
              <div class="mt-2 flex flex-col gap-1.5">
                <div class="flex flex-wrap items-baseline gap-2">
                  <button
                    type="button"
                    class="underline disabled:opacity-40"
                    :style="{ color: 'var(--ink-2)' }"
                    :disabled="!detectPicked.length"
                    @click="applyDetected('replace')"
                  >
                    按目录替换（现有 {{ (block.sections ?? []).length }} 节）
                  </button>
                  <span
                    v-if="ceilingText(planReplace)"
                    :style="{ color: ceilingOf(planReplace) ? 'var(--ink-3)' : 'var(--red)' }"
                  >
                    → {{ ceilingText(planReplace) }}
                  </span>
                </div>
                <div class="flex flex-wrap items-baseline gap-2">
                  <button
                    type="button"
                    class="underline disabled:opacity-40"
                    :style="{ color: 'var(--ink-2)' }"
                    :disabled="!detectPicked.length"
                    @click="applyDetected('append')"
                  >
                    只补未配置的
                  </button>
                  <span
                    v-if="ceilingText(planAppend)"
                    :style="{ color: ceilingOf(planAppend) ? 'var(--ink-3)' : 'var(--red)' }"
                  >
                    → {{ ceilingText(planAppend) }}
                  </span>
                </div>
              </div>
            </template>

            <!--
              「取消」必须在所有分支之外：报错分支和空结果分支原来都没有出口，
              面板一挂上就只能靠切块或刷新才清得掉。
            -->
            <div class="mt-2 flex">
              <button type="button" class="ml-auto text-ink-3" @click="dismissDetected">
                取消
              </button>
            </div>
          </div>

          <!-- 导入时做过的让步 —— 跳过重名、强制翻必需，一条都不许静默。 -->
          <div
            v-if="importNotice.length"
            class="mb-2 flex gap-2 rounded px-2 py-1.5 text-[11px]"
            :style="{ background: 'var(--card-2)', borderLeft: '2px solid var(--amber)' }"
          >
            <div class="flex-1">
              <div v-for="(n, ni) in importNotice" :key="ni">{{ n }}</div>
            </div>
            <!-- 用户按提示改完小节后这段就过期了，得能自己收掉。 -->
            <button type="button" class="text-ink-3" @click="importNotice = []">
              知道了
            </button>
          </div>

          <div
            v-for="(sec, si) in block.sections"
            :key="si"
            class="mb-2 rounded p-2"
            :style="{ background: 'var(--card-2)', border: '1px solid var(--line)' }"
          >
            <div class="flex items-center gap-1.5">
              <FormInput
                :model-value="sec.label ?? ''"
                debounce="live"
                :placeholder="isPool ? '小节名' : '小节名（留空 = 上一节的续段）'"
                style="flex: 1"
                @update:model-value="(v) => updateSection(si, { label: String(v ?? '') })"
              />
              <button type="button" class="px-1 text-ink-3 hover:text-ink" title="上移" @click="moveSection(si, -1)">
                <Icon name="arrowUp" :size="11" />
              </button>
              <button type="button" class="px-1 text-ink-3 hover:text-ink" title="下移" @click="moveSection(si, 1)">
                <Icon name="arrowDown" :size="11" />
              </button>
              <button type="button" class="hover:text-red px-1 text-ink-3" title="删除" @click="removeSection(si)">
                <Icon name="trash" :size="11" />
              </button>
            </div>

            <div v-if="isPool" class="mt-1.5 flex flex-wrap items-center gap-2">
              <FormInput
                :model-value="sec.h2 ?? ''"
                debounce="live"
                placeholder="卡片里的 ## 名（留空 = 用小节名匹配）"
                style="width: 210px"
                @update:model-value="(v) => updateSection(si, { h2: String(v ?? '') })"
              />
              <label class="flex items-center gap-1 text-[11.5px]">
                <input
                  type="checkbox"
                  :checked="sec.required !== false"
                  @change="updateSection(si, { required: ($event.target as HTMLInputElement).checked })"
                />
                必需
              </label>
              <label class="flex items-center gap-1 text-[11.5px]">
                候选数
                <FormInput
                  :model-value="String(sec.pick_variants ?? 1)"
                  type="number"
                  style="width: 56px"
                  @update:model-value="(v) => updateSection(si, { pick_variants: Math.max(1, Number(v) || 1) })"
                />
              </label>
            </div>

            <div v-else class="mt-1.5 space-y-1.5">
              <CascadePicker
                :model-value="sec.module ?? ''"
                :dirs="vaultDirs ?? []"
                placeholder="目录（留空 = 用块上的默认目录）"
                @update:model-value="(v) => updateSection(si, { module: String(v ?? '') || null })"
              />
              <!--
                字段与值都走 vault 下拉：这两格原来是纯手敲，字段还带一个
                「素材类型」的幽灵默认，用户照着填值就配出了一个恒空的筛选。
                下拉直接列出该目录笔记里真实存在的字段与取值，填错的可能性
                从「记得住吗」变成「选得到吗」。
              -->
              <div class="flex flex-wrap items-center gap-2">
                <FormInput
                  v-if="sectionCustomKeys.includes(si)"
                  :model-value="sectionFilterKey(sec)"
                  debounce="live"
                  placeholder="属性名"
                  style="width: 120px"
                  @update:model-value="(v) => setSectionFilter(si, String(v ?? ''), sectionFilterValue(sec))"
                />
                <FormSelect
                  v-else
                  :model-value="sectionFilterKey(sec)"
                  :options="sectionKeyOptions(sec)"
                  placeholder="筛选字段…"
                  :width="120"
                  @update:model-value="(v) => onSectionKeySelect(si, String(v))"
                />
                <FormSelect
                  v-if="sectionValueOptions(sec).length > 0"
                  :model-value="sectionFilterValue(sec)"
                  :options="sectionValueOptions(sec).map((v) => ({ label: v, value: v }))"
                  placeholder="筛选值…"
                  :width="170"
                  @update:model-value="(v) => setSectionFilter(si, sectionFilterKey(sec), String(v))"
                />
                <FormInput
                  v-else
                  :model-value="sectionFilterValue(sec)"
                  debounce="live"
                  :placeholder="sectionValueHint(sec)"
                  :disabled="!sectionFilterKey(sec)"
                  style="width: 170px"
                  @update:model-value="(v) => setSectionFilter(si, sectionFilterKey(sec), String(v ?? ''))"
                />
                <label class="flex items-center gap-1 text-[11.5px]">
                  抽几篇
                  <FormInput
                    :model-value="String(typeof sec.pick_notes === 'number' ? sec.pick_notes : 1)"
                    type="number"
                    style="width: 56px"
                    @update:model-value="(v) => updateSection(si, { pick_notes: Math.max(1, Number(v) || 1) })"
                  />
                </label>
              </div>
            </div>
          </div>
        </div>
      </template>
    </div>

    <!-- ── 目录（paragraph / numbered_list / competitor_pool） ──────── -->
    <FormField v-if="hasModule" label="目录">
      <CascadePicker
        :model-value="block.source?.module ?? ''"
        :dirs="vaultDirs ?? []"
        placeholder="选择数据库文件夹"
        @update:model-value="(v) => patchSource({ module: v })"
      />
    </FormField>

    <!-- ── 测试框架/结果目录 + 主推/竞品标签（test_framework） ───────── -->
    <template v-if="block.kind === 'test_framework'">
      <FormField label="测试框架目录">
        <CascadePicker
          :model-value="block.framework_module ?? ''"
          :dirs="vaultDirs ?? []"
          placeholder="选择测试框架笔记目录"
          @update:model-value="(v) => patch({ framework_module: v })"
        />
      </FormField>
      <FormField label="测试结果目录">
        <CascadePicker
          :model-value="block.results_module ?? ''"
          :dirs="vaultDirs ?? []"
          placeholder="选择品牌结果笔记目录"
          @update:model-value="(v) => patch({ results_module: v })"
        />
      </FormField>
      <FormField label="主推槽位标签">
        <FormInput
          :model-value="block.hero_slot ?? '主推'"
          debounce="live"
          placeholder="如：主推"
          @update:model-value="(v) => patch({ hero_slot: String(v ?? '主推') })"
        />
      </FormField>
      <FormField label="竞品槽位标签（逗号分隔）">
        <FormInput
          :model-value="(block.competitor_slots ?? ['竞品A', '竞品B']).join(', ')"
          debounce="blur"
          placeholder="如：竞品A, 竞品B"
          @update:model-value="(v) =>
            patch({
              competitor_slots: String(v ?? '')
                .split(/[,，、]/)
                .map((s) => s.trim())
                .filter(Boolean),
            })
          "
        />
      </FormField>
    </template>

    <!-- ── literal 文本 ─────────────────────────────────────────────── -->
    <div v-if="block.kind === 'literal'" class="flex flex-col gap-1.5">
      <div class="flex items-center gap-2">
        <div class="text-[12px]" :style="{ color: 'var(--ink-3)' }">固定文本</div>
        <span class="flex-1" />
        <button
          type="button"
          class="inline-flex h-[22px] items-center px-2.5 text-[11px]"
          :style="{
            color: 'var(--primary-deep)',
            border: '1px solid rgba(238,106,42,0.3)',
            borderRadius: '11px',
          }"
          @click="insertKeyword('text')"
        >
          + 关键词
        </button>
      </div>
      <textarea
        :value="block.text ?? ''"
        rows="6"
        class="font-serif-cn w-full bg-card-2 px-3 py-2 text-[12.5px] outline-none focus:bg-card-white"
        :style="{
          minHeight: '120px',
          borderRadius: 'var(--radius-inner)',
          border: '1px solid var(--line)',
        }"
        @blur="(e) => patch({ text: (e.target as HTMLTextAreaElement).value })"
      />
    </div>

    <!-- ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ -->
    <!-- ── 高级设置（paragraph / numbered_list / competitor_pool / test_framework） ── -->
    <!-- ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ -->
    <template
      v-if="['paragraph', 'numbered_list', 'competitor_pool', 'test_framework'].includes(block.kind)"
    >
      <div :style="{ height: '1px', background: 'var(--line)', margin: '4px 0' }" />

      <div class="font-display text-[13px] font-semibold">
        {{
          ({
            paragraph: '段落高级设置',
            numbered_list: '列表高级设置',
            competitor_pool: '对比池高级设置',
            test_framework: '测试部分高级设置',
          } as Record<string, string>)[block.kind] ?? '高级设置'
        }}
      </div>

      <!-- ── 筛选（paragraph / numbered_list / competitor_pool） ───── -->
      <template v-if="block.kind !== 'test_framework'">
        <div class="flex items-center justify-between">
          <div class="text-[12px]" :style="{ color: 'var(--ink-3)' }">筛选</div>
          <!--
            状态条 —— 拉取属性中 / 失败 / 无属性。成功且非空就不显示。
            把 vault 没扫描的语义讲清楚，比一个空下拉强。
          -->
          <div
            v-if="attrsLoading"
            class="text-[10.5px]"
            :style="{ color: 'var(--ink-4)' }"
          >读取属性…</div>
          <div
            v-else-if="attrsError"
            class="text-[10.5px]"
            :style="{ color: 'var(--red)' }"
            :title="attrsError"
          >{{ attrsError }}</div>
          <div
            v-else-if="!vaultAttrs.length"
            class="text-[10.5px]"
            :style="{ color: 'var(--ink-4)' }"
          >
            当前目录下还没有带 frontmatter 的素材 —— 选「＋ 自定义属性…」直接手填即可（先配模板后写素材是正常顺序）。
          </div>
        </div>
        <!--
          单选筛选 —— 按用户要求改为只有一行 key + value 下拉。原来支持
          多行 filter + 每行 value 多选（checkbox-style MultiValuePicker），
          被用户判定为"容易出错"+"UI 跟应用其它下拉不一致"。
          - key 走 FormSelect（含「不筛选」首选项，用户能清掉）
          - value 当有候选值时走 FormSelect（跟 key 同款下拉），
            没候选值（vault 高基数 / 未扫）时回退 FormInput 兜底
          - 不再有 添加 / 删除 按钮
        -->
        <div class="flex items-center gap-2">
          <div class="flex-[2]" :style="{ minWidth: '0' }">
            <FormInput
              v-if="customKeyMode"
              :model-value="filterRows[0]?.key ?? ''"
              debounce="live"
              placeholder="属性名，如 素材类型"
              @update:model-value="(v) => updateFilterRow(0, { key: String(v ?? '') })"
            />
            <FormSelect
              v-else
              :model-value="filterRows[0]?.key ?? ''"
              :options="attrKeyOptions"
              placeholder="选择属性…"
              width="100%"
              @update:model-value="(v) => onKeySelect(String(v))"
            />
          </div>
          <div class="flex-[3]" :style="{ minWidth: '0' }">
            <FormSelect
              v-if="filterRows[0]?.key && valueOptionsFor(filterRows[0].key).length > 0"
              :model-value="filterRows[0]?.value ?? ''"
              :options="valueOptionsFor(filterRows[0].key).map((v) => ({ label: v, value: v }))"
              placeholder="选择值…"
              width="100%"
              @update:model-value="(v) => updateFilterRow(0, { value: String(v) })"
            />
            <FormInput
              v-else
              :model-value="filterRows[0]?.value ?? ''"
              :placeholder="valueHintFor(filterRows[0]?.key ?? '')"
              :disabled="!filterRows[0]?.key"
              @update:model-value="(v) => updateFilterRow(0, { value: String(v) })"
            />
          </div>
        </div>
      </template>

      <!-- ── 取值 / 测试项数量 ──────────────────────────────────────── -->
      <div class="text-[12px]" :style="{ color: 'var(--ink-3)' }">
        {{ block.kind === 'test_framework' ? '测试项数量' : '取值' }}
      </div>
      <div class="flex flex-wrap items-center gap-3 text-[12.5px]">
        <span :style="{ color: 'var(--ink-2)' }">素材数量：</span>
        <FormInput
          type="number"
          :model-value="pickMin"
          :width="100"
          @update:model-value="(v) => setPick({ min: Math.max(1, Number(v) || 1) })"
        />
        <label class="inline-flex cursor-pointer items-center gap-1.5">
          <input
            type="checkbox"
            :checked="isRange"
            @change="(e) => toggleRange((e.target as HTMLInputElement).checked)"
          />
          <span>启用随机区间</span>
        </label>
        <template v-if="isRange">
          <span :style="{ color: 'var(--ink-2)' }">最多：</span>
          <FormInput
            type="number"
            :model-value="pickMax"
            :width="100"
            @update:model-value="(v) => setPick({ max: Math.max(pickMin + 1, Number(v) || pickMin + 1) })"
          />
        </template>
      </div>

      <!-- ── 子素材 + 不重复（paragraph + numbered_list） ─────────── -->
      <template v-if="supportsSubMaterial">
        <div class="flex flex-wrap items-center gap-3 text-[12.5px]">
          <span :style="{ color: 'var(--ink-2)' }">子素材随机数量：</span>
          <FormInput
            type="number"
            :model-value="block.pick_variants_per_note ?? 1"
            :width="100"
            @update:model-value="(v) => patch({ pick_variants_per_note: Math.max(1, Number(v) || 1) })"
          />
        </div>
        <label class="inline-flex cursor-pointer items-center gap-1.5 text-[12.5px]">
          <input
            type="checkbox"
            :checked="uniqueNotes"
            @change="(e) => toggleUniqueNotes((e.target as HTMLInputElement).checked)"
          />
          <span>不重复素材</span>
          <span class="text-[10.5px]" :style="{ color: 'var(--ink-3)' }">
            {{
              block.kind === 'numbered_list' ? '（同列表内不抽中重复笔记）'
              : block.kind === 'competitor_pool' ? '（同对比池内不抽中重复竞品）'
              : '（父子段落不复用同一素材）'
            }}
          </span>
        </label>
      </template>

      <!-- ── 链接（paragraph） / 跟随区块（test_framework） ─────────── -->
      <template
        v-if="['paragraph', 'test_framework'].includes(block.kind)"
      >
        <div class="text-[12px]" :style="{ color: 'var(--ink-3)' }">
          {{ block.kind === 'paragraph' ? '链接' : '跟随区块' }}
        </div>
        <div class="relative">
          <button
            type="button"
            class="flex w-full items-center justify-between gap-2 px-3 py-2 text-[12.5px]"
            :style="{
              background: 'var(--card-2)',
              border: '1px solid var(--line)',
              borderRadius: 'var(--radius-inner)',
              color: linkedIds.length ? 'var(--ink)' : 'var(--ink-3)',
            }"
            @click="linkOpen = !linkOpen"
          >
            <span class="truncate text-left">{{ linkButtonText }}</span>
            <Icon name="arrowDown" :size="12" />
          </button>
          <!--
            下拉皮肤对齐 native <select>：cream 底 + dark hover row。
            选中行用 primary-soft 提示，已勾选项右边补一个 ✓。
          -->
          <div
            v-if="linkOpen"
            class="absolute z-10 mt-1 max-h-[240px] w-full overflow-y-auto p-1.5"
            :style="{
              background: 'var(--card-2)',
              border: '1px solid var(--line)',
              borderRadius: 'var(--radius-inner)',
              boxShadow: '0 6px 18px rgba(var(--shadow-rgb),0.10)',
            }"
            @click.stop
          >
            <div
              v-if="!siblings || siblings.length === 0"
              class="px-2 py-1 text-[12px]"
              :style="{ color: 'var(--ink-3)' }"
            >
              （无可用区块）
            </div>
            <button
              v-for="s in siblings"
              :key="s.id"
              type="button"
              class="link-row flex w-full cursor-pointer items-center gap-2 px-2 py-1.5 text-left text-[12.5px]"
              :style="{
                borderRadius: '6px',
                background: linkedIds.includes(s.id) ? 'var(--primary-soft)' : 'transparent',
                color: linkedIds.includes(s.id) ? 'var(--primary-deep)' : 'var(--ink)',
              }"
              @click="toggleLink(s.id, !linkedIds.includes(s.id))"
            >
              <span class="flex-1 truncate">{{ s.label }}</span>
              <Icon
                v-if="linkedIds.includes(s.id)"
                name="check"
                :size="11"
                :style="{ color: 'var(--primary-deep)' }"
              />
            </button>
            <div class="flex justify-end pt-1">
              <button
                type="button"
                class="px-2 py-1 text-[11px]"
                :style="{ color: 'var(--ink-3)' }"
                @click="linkOpen = false"
              >
                完成
              </button>
            </div>
          </div>
        </div>
      </template>
    </template>

    <!-- ── 删除此区块 ─────────────────────────────────────────────── -->
    <div :style="{ height: '1px', background: 'var(--line)', margin: '4px 0' }" />
    <button
      type="button"
      class="w-full px-4 py-2 text-[13px]"
      :style="{
        color: 'var(--red)',
        background: 'transparent',
        border: '1px solid rgba(194,92,77,0.32)',
        borderRadius: '8px',
      }"
      @click="emit('delete')"
    >
      删除此区块
    </button>
  </div>
</template>

<style scoped>
/*
 * 链接 / 跟随区块下拉的 hover 行 —— 对齐原生 <select> 的深色 hover：
 * 任意行 hover 时翻成 --dark 底 + cream 字，覆盖选中态的 primary-soft。
 * 用 !important 是因为行的内联 :style 优先级比类高，否则压不住。
 */
.link-row:hover {
  background: var(--dark) !important;
  color: var(--card) !important;
}
.link-row:hover :deep(svg) {
  color: var(--card) !important;
}
</style>
