<script setup lang="ts">
/**
 * Monitor Add-Task modal — POST /api/monitor/tasks (or PATCH in edit mode).
 *
 * Per-platform body shape (per csm_core.monitor.base.MonitorTask.config):
 *   zhihu_question     → { target_brand: str, top_n: int }
 *   *_comment          → { my_comment_text: str, top_n: int }
 *
 * 评论场景不带 target_brand —— 匹配走的是 my_comment_text 文本相似度，
 * 品牌词在这条流水线上没用，UI 端也不暴露这个输入框（避免混淆）。
 *
 * 编辑模式：传入 ``editingTask`` 切到 PATCH 模式 —— 把已有任务的字段
 * 反填进表单，submit 时走 PATCH /api/monitor/tasks/{id} 而不是 POST。
 * 平台 / URL 在编辑模式下置灰不可改（后端约束 + 改了就该是新任务）。
 *
 * Schedule format follows csm_core/monitor/scheduler.py: "manual" or
 * "HH:MM" (daily). Anything else is rejected by the parser.
 */
import { computed, onMounted, ref, watch } from "vue";
import { useRouter } from "vue-router";

import Btn from "@/components/ui/Btn.vue";
import Dialog from "@/components/ui/Dialog.vue";
import Spinner from "@/components/ui/Spinner.vue";
import FormField from "@/components/forms/FormField.vue";
import FormInput from "@/components/forms/FormInput.vue";
import FormSelect from "@/components/forms/FormSelect.vue";
import FormToggle from "@/components/forms/FormToggle.vue";

import { useSidecar } from "@/stores/sidecar";
import { useConfig } from "@/stores/config";
import { useToast } from "@/composables/useToast";
import { GEO_PLATFORMS } from "@/utils/monitor-types";
import { uniqueSearchTargetUrl, uniqueGeoTargetUrl } from "@/utils/taskTargetUrl";

type TaskType = "zhihu_question" | "zhihu_search" | "bilibili_comment" | "douyin_comment" | "kuaishou_comment" | "baidu_keyword" | "geo_query";

interface EditingTask {
  id: number;
  type: TaskType | string;
  name: string;
  target_url: string;
  config: Record<string, any>;
  schedule_cron: string;
  enabled: boolean;
}

const props = defineProps<{
  open: boolean;
  /** Pre-select platform when caller knows it. */
  defaultType?: TaskType;
  /** 传入即进入编辑模式。 */
  editingTask?: EditingTask | null;
}>();
const emit = defineEmits<{
  (e: "update:open", v: boolean): void;
  (e: "created", taskId: number): void;
  (e: "updated", taskId: number): void;
}>();

const sidecar = useSidecar();
const toast = useToast();

const TYPES = [
  { value: "zhihu_question", label: "知乎问题（排名监测）" },
  { value: "zhihu_search", label: "知乎搜索排名" },
  { value: "bilibili_comment", label: "B 站评论留存" },
  { value: "douyin_comment", label: "抖音评论留存" },
  { value: "kuaishou_comment", label: "快手评论留存" },
  { value: "baidu_keyword", label: "百度关键词排名" },
  { value: "geo_query", label: "AI 卡位监控（GEO）" },
] as const;

const type = ref<TaskType>("zhihu_question");
const name = ref("");
const targetUrl = ref("");
// Zhihu-specific / Baidu target brand (single word)
const targetBrand = ref("");
// Comment-specific
const myCommentText = ref("");
// Shared —— 默认 5；watch(type) 时知乎切到 10（zhihu_question 的合理起点）
const topN = ref(5);
// Baidu-specific
const searchKeywordsRaw = ref(""); // newline-separated string; split to list on submit
const baiduAliasesText = ref(""); // 品牌别名，逗号分隔；提交时 split 成 list（任一命中算自家）
const baiduHeadless = ref(true);
const baiduIdealRank = ref<number>(5);
// 排除域名：换行/逗号分隔，提交时拆成 list。默认空表示「只走全局
// B2B/电商黑名单」（由 settings.monitor.baidu_keyword.default_excluded_domains 提供）。
// 用户在这里加自家品牌官网 / 其他不算"软文"的域名即可。
const baiduExcludeDomainsRaw = ref("");
const baiduUseDefaultExcludes = ref(true);
// GEO-specific（AI 卡位监控）
const geoBrand = ref("");
const geoAliasesText = ref(""); // comma-separated; split to list on submit
const geoKeywordsText = ref(""); // newline-separated; split to list on submit
const geoPlatforms = ref<string[]>(GEO_PLATFORMS.map((p) => p.value));
const geoWebSearch = ref(true);
// 抽取/分析模型固定用 DeepSeek（不再给选项）——通义免费额度易耗尽会致抽取 403 静默降级。
// 知乎搜索（zhihu_search）—— 关键词 list + 单品牌词 + 别名
const zsKeywordsRaw = ref(""); // newline-separated
const zsTargetBrand = ref("");
const zsAliasesText = ref(""); // comma-separated
const zsMatchFullText = ref(false); // 可选全文级匹配（默认关，需配置知乎 Cookie）

// Popover that shows the current global default_excluded_domains
// (read-only, with a button to jump to the Settings section for editing).
// Data is pulled live from useConfig — the store is hydrated at app boot,
// but onMounted in this component is a defensive fallback if a user opens
// the modal before the config has loaded.
const cfgStore = useConfig();
const router = useRouter();
const showDefaultDomainsPopover = ref(false);
const defaultExcludeDomains = computed<string[]>(
  () => cfgStore.data?.monitor?.baidu_keyword?.default_excluded_domains ?? []
);

function goToSettingsExcludeDomains() {
  showDefaultDomainsPopover.value = false;
  emit("update:open", false); // close AddTaskModal first so the Settings view is visible
  router.push({ name: "settings", hash: "#baidu-default-excludes" });
}

// Schedule
const scheduleMode = ref<"manual" | "daily" | "weekly">("manual");
const dailyTime = ref("09:00");
// Weekly schedule: day-of-week (0=Monday…6=Sunday) + time
const weeklyDow = ref<number>(0);
const weeklyTime = ref("09:00");
const DOW_OPTIONS = [
  { value: 0, label: "周一" },
  { value: 1, label: "周二" },
  { value: 2, label: "周三" },
  { value: 3, label: "周四" },
  { value: 4, label: "周五" },
  { value: 5, label: "周六" },
  { value: 6, label: "周日" },
] as const;
const enabled = ref(true);

const submitting = ref(false);

const isGeo = computed(() => type.value === "geo_query");
const isZhihuSearch = computed(() => type.value === "zhihu_search");
const isComment = computed(() =>
  type.value !== "zhihu_question" &&
  type.value !== "zhihu_search" &&
  type.value !== "baidu_keyword" &&
  type.value !== "geo_query"
);
const isBaidu = computed(() => type.value === "baidu_keyword");
const isEdit = computed(() => !!props.editingTask);

function close() {
  emit("update:open", false);
  // Reset for next open. topN 默认值按平台：知乎 10 / 评论 5。
  name.value = "";
  targetUrl.value = "";
  targetBrand.value = "";
  myCommentText.value = "";
  topN.value = type.value === "zhihu_question" ? 10 : 5;
  searchKeywordsRaw.value = "";
  baiduAliasesText.value = "";
  targetBrand.value = "";
  baiduHeadless.value = true;
  baiduIdealRank.value = 5;
  baiduExcludeDomainsRaw.value = "";
  baiduUseDefaultExcludes.value = true;
  geoBrand.value = "";
  geoAliasesText.value = "";
  geoKeywordsText.value = "";
  geoPlatforms.value = GEO_PLATFORMS.map((p) => p.value);
  geoWebSearch.value = true;
  zsKeywordsRaw.value = "";
  zsTargetBrand.value = "";
  zsAliasesText.value = "";
  zsMatchFullText.value = false;
  scheduleMode.value = "manual";
  dailyTime.value = "09:00";
  weeklyDow.value = 0;
  weeklyTime.value = "09:00";
  enabled.value = true;
  submitting.value = false;
}

// 切平台时同步 topN 默认 —— 用户刚切到知乎应该看到 10 而不是 5（除非
// 已经手动改过；编辑模式 hydrate 会覆盖这里）。
watch(
  () => type.value,
  (next) => {
    if (isEdit.value) return;
    const knownDefaults = new Set([5, 10]);
    if (knownDefaults.has(topN.value)) {
      topN.value = next === "zhihu_question" ? 10 : 5;
    }
  },
);

/** 把 editingTask 反填进表单字段。 */
function hydrateFromTask(t: EditingTask) {
  type.value = (t.type as TaskType) || "zhihu_question";
  name.value = t.name ?? "";
  targetUrl.value = t.target_url ?? "";
  const cfg = t.config ?? {};
  targetBrand.value = String(cfg.target_brand ?? "");
  myCommentText.value = String(cfg.my_comment_text ?? "");
  topN.value = Number(cfg.top_n) || 5;
  // Baidu-specific hydration (inverted model: search_keywords list + target_brand single word)
  const keywords: string[] = Array.isArray(cfg.search_keywords) ? cfg.search_keywords : [];
  searchKeywordsRaw.value = keywords.join("\n");
  baiduHeadless.value = cfg.headless !== false; // default true
  baiduIdealRank.value = Number(cfg.ideal_rank ?? 5);
  const exDomains: string[] = Array.isArray(cfg.exclude_domains) ? cfg.exclude_domains : [];
  baiduExcludeDomainsRaw.value = exDomains.join("\n");
  baiduUseDefaultExcludes.value = cfg.use_default_excludes !== false;
  baiduAliasesText.value = (Array.isArray(cfg.brand_aliases) ? cfg.brand_aliases : []).join("，");
  // GEO-specific hydration
  geoBrand.value = String(cfg.brand ?? "");
  const aliases: string[] = Array.isArray(cfg.brand_aliases) ? cfg.brand_aliases : [];
  geoAliasesText.value = aliases.join("，");
  const geoKeywords: string[] = Array.isArray(cfg.keywords) ? cfg.keywords : [];
  geoKeywordsText.value = geoKeywords.join("\n");
  geoPlatforms.value = Array.isArray(cfg.platforms) && cfg.platforms.length
    ? cfg.platforms
    : GEO_PLATFORMS.map((p) => p.value);
  geoWebSearch.value = cfg.web_search !== false; // default true
  // 知乎搜索 hydration
  const zsKeywords: string[] = Array.isArray(cfg.search_keywords) ? cfg.search_keywords : [];
  // 注意：baidu 也用 search_keywords，这里只在 type==zhihu_search 时用到，互不干扰
  zsKeywordsRaw.value = zsKeywords.join("\n");
  zsTargetBrand.value = String(cfg.target_brand ?? "");
  const zsAliases: string[] = Array.isArray(cfg.brand_aliases) ? cfg.brand_aliases : [];
  zsAliasesText.value = zsAliases.join("，");
  zsMatchFullText.value = Boolean(cfg.match_full_text);
  const weeklyMatch = /^weekly-([0-6])-(\d{1,2}:\d{2})$/.exec(t.schedule_cron);
  if (t.schedule_cron === "manual" || !t.schedule_cron) {
    scheduleMode.value = "manual";
  } else if (weeklyMatch) {
    scheduleMode.value = "weekly";
    weeklyDow.value = Number(weeklyMatch[1]);
    weeklyTime.value = weeklyMatch[2];
  } else if (/^\d{1,2}:\d{2}$/.test(t.schedule_cron)) {
    scheduleMode.value = "daily";
    dailyTime.value = t.schedule_cron;
  } else {
    // 其它 cron 形式 —— 留作 manual 兜底
    scheduleMode.value = "manual";
  }
  enabled.value = Boolean(t.enabled);
}

watch(
  () => props.open,
  (v) => {
    if (!v) return;
    if (props.editingTask) {
      hydrateFromTask(props.editingTask);
    } else {
      if (props.defaultType) type.value = props.defaultType;
      // 打开新增模态时按平台带默认 Top-N（知乎 10 / 评论 5），
      // 不依赖 ref 初值
      topN.value = type.value === "zhihu_question" ? 10 : 5;
    }
  },
  { immediate: true },
);

// editingTask 可能后挂上（父组件懒加载），watch 这个再 hydrate 一次。
watch(
  () => props.editingTask,
  (t) => {
    if (t && props.open) hydrateFromTask(t);
  },
);

onMounted(async () => {
  // If the config store wasn't hydrated yet (rare race in cold start),
  // load it now so the popover's count badge shows the right number.
  if (!cfgStore.data) {
    try {
      await cfgStore.load();
    } catch {
      // Non-fatal: popover will show "(空)" — the user can still proceed
      // with the rest of the form. Logging handled by the store itself.
    }
  }
});

function validate(): string | null {
  if (!name.value.trim()) return "任务名不能为空";
  // 百度 / GEO / 知乎搜索 分支：target_url 由关键词/品牌派生，不需要用户填 URL
  if (!isBaidu.value && !isGeo.value && !isZhihuSearch.value && !targetUrl.value.trim()) return "目标 URL 不能为空";
  if (isGeo.value) {
    if (!geoBrand.value.trim()) return "品牌名不能为空";
    const keywords = geoKeywordsText.value.split(/\r?\n/).map((s) => s.trim()).filter(Boolean);
    if (keywords.length === 0) return "关键词至少填一个";
    if (geoPlatforms.value.length === 0) return "至少选一个 AI 平台";
  } else if (isZhihuSearch.value) {
    const keywords = zsKeywordsRaw.value.split(/\r?\n/).map((s) => s.trim()).filter(Boolean);
    if (keywords.length === 0) return "搜索关键词至少填一个";
    if (!zsTargetBrand.value.trim()) return "目标品牌词不能为空";
  } else if (isBaidu.value) {
    const keywords = searchKeywordsRaw.value.split("\n").map(s => s.trim()).filter(Boolean);
    if (keywords.length === 0) return "搜索关键词至少填一个";
    if (!targetBrand.value.trim()) return "目标品牌词不能为空";
  } else {
    if (isComment.value && !myCommentText.value.trim()) {
      return "评论留存监测必须填写自己发布的评论文本";
    }
    // 评论场景不要求 target_brand（UI 里也不暴露）；知乎必填。
    if (!isComment.value && !targetBrand.value.trim()) {
      return "知乎监测必须填写目标品牌关键词";
    }
    // 知乎 Top-N 上限 40（后端 silent clamp，UI 多卡一道避免用户写 100 再奇怪）；
    // 评论"理想排名"软上限 100。
    const topNMax = isComment.value ? 100 : 40;
    if (topN.value < 1 || topN.value > topNMax) {
      return `Top-N 阈值应在 1–${topNMax} 之间`;
    }
  }
  if (scheduleMode.value === "daily" && !/^\d{1,2}:\d{2}$/.test(dailyTime.value)) {
    return "时间格式应为 HH:MM";
  }
  if (scheduleMode.value === "weekly" && !/^\d{1,2}:\d{2}$/.test(weeklyTime.value)) {
    return "时间格式应为 HH:MM";
  }
  return null;
}

async function submit() {
  const err = validate();
  if (err) {
    toast.warn(err);
    return;
  }
  submitting.value = true;
  try {
    // 评论场景 config 只带 my_comment_text + top_n —— 用户决定不引入
    // 品牌词，避免无用字段误导（评论匹配走 `my_comment_text` 相似度，
    // 跟品牌词无关）。target_brand 仅知乎走，那条命令链路用得上。
    let config: Record<string, any>;
    let computedTargetUrl = targetUrl.value.trim();
    if (isGeo.value) {
      const brand = geoBrand.value.trim();
      config = {
        brand,
        brand_aliases: geoAliasesText.value
          .split(/[，,]/)
          .map((s) => s.trim())
          .filter(Boolean),
        keywords: geoKeywordsText.value
          .split(/\r?\n/)
          .map((s) => s.trim())
          .filter(Boolean),
        platforms: [...geoPlatforms.value],
        web_search: geoWebSearch.value,
        extract_provider: "deepseek",   // 固定 DeepSeek 抽取（不再给选项）
        top_n_citations: 20,
      };
      // target_url 对 geo_query 只是 UNIQUE 键（adapter 不实际请求它）。必须每个任务
      // 唯一，否则同品牌任务会撞 UNIQUE(type,target_url) → create_task 的 ON CONFLICT
      // DO UPDATE 把原任务覆盖掉（数据丢失！）。编辑时沿用原 target_url（update 按 id、
      // 键不变）；新建时（targetUrl 为空）生成唯一值。详见 utils/taskTargetUrl.ts。
      computedTargetUrl = uniqueGeoTargetUrl(brand, targetUrl.value);
    } else if (isZhihuSearch.value) {
      const keywords = zsKeywordsRaw.value.split(/\r?\n/).map((s) => s.trim()).filter(Boolean);
      config = {
        search_keywords: keywords,
        target_brand: zsTargetBrand.value.trim(),
        brand_aliases: zsAliasesText.value.split(/[，,]/).map((s) => s.trim()).filter(Boolean),
        count: 10,
        match_full_text: zsMatchFullText.value,
      };
      // target_url 由第一个关键词派生 —— 后端要求非空；点开是真实知乎搜索页。
      // 追加唯一参数避免同首词任务撞 UNIQUE 键被 create_task 覆盖；编辑沿用原键。
      computedTargetUrl = uniqueSearchTargetUrl(
        "https://www.zhihu.com/search?type=content&q=",
        keywords[0],
        targetUrl.value,
      );
    } else if (isBaidu.value) {
      const keywords = searchKeywordsRaw.value.split("\n").map(s => s.trim()).filter(Boolean);
      // 排除域名解析：换行 / 逗号 / 空格 / 顿号都拆开；剥掉协议头 +
      // 末尾斜杠。后端 adapter 用 hostsuffix 匹配，所以 "https://www.jd.com/"
      // 和 "jd.com" 都最终能命中 jd.com 这个 pattern。
      const excludeDomains = baiduExcludeDomainsRaw.value
        .split(/[\n,，、\s]+/)
        .map((s) => s.trim().replace(/^https?:\/\//i, "").replace(/\/$/, "").toLowerCase())
        .filter(Boolean);
      config = {
        search_keywords: keywords,
        target_brand: targetBrand.value.trim(),
        headless: baiduHeadless.value,
        ideal_rank: baiduIdealRank.value,
        exclude_domains: excludeDomains,
        use_default_excludes: baiduUseDefaultExcludes.value,
        brand_aliases: baiduAliasesText.value.split(/[，,]/).map((s) => s.trim()).filter(Boolean),
      };
      // target_url 由第一个 search_keyword 派生 —— 后端要求非空。
      // 追加唯一参数避免同首词任务撞 UNIQUE 键被 create_task 覆盖；编辑沿用原键。
      computedTargetUrl = uniqueSearchTargetUrl(
        "https://www.baidu.com/s?wd=",
        keywords[0],
        targetUrl.value,
      );
    } else if (isComment.value) {
      config = {
        my_comment_text: myCommentText.value.trim(),
        top_n: topN.value,
      };
    } else {
      config = { target_brand: targetBrand.value.trim(), top_n: topN.value };
    }
    const body = {
      type: type.value,
      name: name.value.trim(),
      target_url: computedTargetUrl,
      config,
      schedule_cron:
        scheduleMode.value === "weekly"
          ? `weekly-${weeklyDow.value}-${weeklyTime.value}`
          : scheduleMode.value === "daily"
            ? dailyTime.value
            : "manual",
      enabled: enabled.value,
    };
    if (isEdit.value && props.editingTask) {
      const id = props.editingTask.id;
      await sidecar.client.patch(`/api/monitor/tasks/${id}`, body);
      toast.success(`已保存修改（#${id}）`);
      emit("updated", id);
    } else {
      const r = await sidecar.client.post("/api/monitor/tasks", body);
      toast.success(`任务已添加（#${r.data.id}）`);
      emit("created", r.data.id);
    }
    close();
  } catch (e: any) {
    const detail = e?.response?.data?.detail ?? e?.message ?? e;
    const action = isEdit.value ? "保存" : "创建";
    toast.error(`${action}失败：${typeof detail === "string" ? detail : JSON.stringify(detail)}`);
  } finally {
    submitting.value = false;
  }
}
</script>

<template>
  <Dialog
    :open="open"
    :title="isEdit ? '编辑监测任务' : '新增监测任务'"
    show-close
    :closable="!showDefaultDomainsPopover"
    @update:open="close"
  >
    <div class="flex flex-col gap-4">
          <FormField label="平台">
            <!--
              编辑模式下平台改不了 —— task.type 决定后端 adapter 路由，
              改了等同于建新任务；FormSelect 没有 :disabled 就用静态展示
              替代，保留原有的胶囊样式不至于突兀。
            -->
            <div
              v-if="isEdit"
              class="text-[12.5px]"
              :style="{
                padding: '6px 12px',
                background: 'var(--card-2)',
                border: '1px solid var(--line)',
                borderRadius: 'var(--radius-inner)',
                color: 'var(--ink-2)',
              }"
            >{{ TYPES.find((t) => t.value === type)?.label ?? type }}（不可改）</div>
            <FormSelect
              v-else
              :model-value="type"
              :options="TYPES.map((t) => ({ label: t.label, value: t.value }))"
              @update:model-value="(v) => (type = v as any)"
            />
          </FormField>

          <FormField
            :label="isBaidu || isComment || isGeo || isZhihuSearch ? '任务名' : '问题名字'"
            :hint="isBaidu || isComment || isGeo || isZhihuSearch ? '出现在监测列表里。' : '抓取到的知乎问题标题，会显示在监测任务列表的第一列。'"
          >
            <FormInput
              v-model="name"
              :placeholder="isBaidu ? '如：Claude Code 排名监测' : isComment ? '如：客厅投影实测视频留存' : isGeo ? '如：小鹏 AI 卡位监控' : isZhihuSearch ? '如：扫地机器人知乎搜索卡位' : '如：无线吸尘器哪款好用'"
              debounce="live"
            />
          </FormField>

          <!-- 百度 / GEO / 知乎搜索 分支：target_url 由关键词/品牌派生，不暴露 URL 输入框 -->
          <FormField
            v-if="!isBaidu && !isGeo && !isZhihuSearch"
            label="目标 URL"
            :hint="
              isEdit
                ? '编辑模式下不可改 —— 想换 URL 请删掉后重新添加'
                : isComment
                  ? '视频 / 笔记的完整 URL'
                  : '知乎问题的完整 URL（如 https://www.zhihu.com/question/12345）'
            "
          >
            <FormInput
              v-model="targetUrl"
              placeholder="https://..."
              debounce="live"
              :disabled="isEdit"
            />
          </FormField>

          <!-- 百度关键词排名：专属字段 -->
          <template v-if="isBaidu">
            <FormField label="搜索关键词" hint="一行一个，每个关键词单独搜一次">
              <textarea
                v-model="searchKeywordsRaw"
                rows="4"
                placeholder="如：&#10;Claude Code 教程&#10;Claude Code 怎么用&#10;Anthropic Claude"
                class="bg-card-2 focus:bg-card-white outline-none transition-colors"
                :style="{
                  width: '100%',
                  resize: 'vertical',
                  padding: '6px 10px',
                  fontSize: '12.5px',
                  fontFamily: 'inherit',
                  border: '1px solid var(--line)',
                  borderRadius: 'var(--radius-inner)',
                  color: 'var(--ink)',
                  boxSizing: 'border-box',
                }"
              />
            </FormField>

            <FormField label="目标品牌词" hint="命中关键词的搜索结果就标「自家」">
              <FormInput
                v-model="targetBrand"
                placeholder="如：Claude Code"
                debounce="live"
              />
            </FormField>

            <FormField label="品牌别名" hint="逗号分隔；命中任一别名的结果也算「自家」（如：CEWEY，希喂）">
              <FormInput
                v-model="baiduAliasesText"
                placeholder="如：CEWEY，希喂"
                debounce="live"
              />
            </FormField>

            <FormField
              label="理想卡位（数量）"
              hint="该关键词下目标品牌软文的理想卡位总数 ＝ 默认搜索卡位 ＋ 最新资讯卡位（若有）"
              inline
            >
              <!--
                跟 Top-N 同 bug：单向绑定时 proxy 卡死，blur commit 旧值。
                改 v-model 双向；@commit 保留做 clamp + 空值 fallback。
              -->
              <FormInput
                type="number"
                v-model="baiduIdealRank"
                :width="100"
                @commit="(v) => (baiduIdealRank = Math.min(50, Math.max(1, Number(v) || 5)))"
              />
            </FormField>

            <details>
              <summary
                :style="{
                  cursor: 'pointer',
                  fontSize: '12.5px',
                  color: 'var(--ink-2)',
                  userSelect: 'none',
                }"
              >高级</summary>
              <div class="mt-2 flex flex-col gap-3">
                <FormField
                  label="默认尝试隐藏窗口"
                  hint="开启后窗口会被推到屏外（offscreen + 最小化），用户视觉上看不见。命中验证码会自动升级到可见窗口让你手动过验证。"
                  inline
                >
                  <FormToggle v-model="baiduHeadless" />
                </FormField>

                <!--
                  Baidu SERP 常混进 jd / 1688 / taobao / 自家品牌官网，这些
                  即便品牌词命中也不是"软文卡位"。开启全局黑名单 + 手动加
                  自家域名即可在 SERP 解析后清干净再编号 rank。
                -->
                <FormField
                  label="启用默认电商/B2B 黑名单"
                  hint="默认过滤 jd / 1688 / taobao / pinduoduo 等采购与电商站点（这些命中目标品牌也不是软文）。如果你确实要监测这些站，关掉。"
                  inline
                >
                  <div class="flex items-center gap-2">
                    <FormToggle v-model="baiduUseDefaultExcludes" />
                    <button
                      type="button"
                      class="text-[11px] text-[var(--ink-2)] hover:text-[var(--primary-deep)] underline-offset-2 hover:underline"
                      @click="showDefaultDomainsPopover = true"
                    >
                      查看名单（{{ defaultExcludeDomains.length }}）
                    </button>
                  </div>
                </FormField>

                <FormField
                  label="自定义排除域名"
                  hint="一行一个；自家品牌官网 / 其他非软文站点写这里。可写 cewey.com 或 https://www.cewey.com/，会按 host 后缀匹配（cewey.com 同时命中 www.cewey.com / shop.cewey.com）。会和上方「默认黑名单」合并去重。"
                >
                  <textarea
                    v-model="baiduExcludeDomainsRaw"
                    rows="3"
                    placeholder="cewey.com&#10;example.com"
                    class="bg-card-2 focus:bg-card-white outline-none transition-colors"
                    :style="{
                      width: '100%',
                      resize: 'vertical',
                      padding: '6px 10px',
                      fontSize: '12.5px',
                      fontFamily: 'inherit',
                      border: '1px solid var(--line)',
                      borderRadius: 'var(--radius-inner)',
                      color: 'var(--ink)',
                      boxSizing: 'border-box',
                    }"
                  />
                </FormField>
              </div>
            </details>
          </template>

          <!-- AI 卡位监控（GEO）：品牌 / 别名 / 批量关键词 / 平台多选 / 联网 / 抽取模型 -->
          <template v-if="isGeo">
            <FormField label="品牌名" hint="要在 AI 回答里追踪卡位的品牌（如：小鹏）">
              <FormInput
                v-model="geoBrand"
                placeholder="如：小鹏"
                debounce="live"
              />
            </FormField>

            <FormField label="品牌别名" hint="逗号分隔；命中任一别名都算提及（如：小鹏汽车，XPENG）">
              <FormInput
                v-model="geoAliasesText"
                placeholder="如：小鹏汽车，XPENG"
                debounce="live"
              />
            </FormField>

            <FormField label="关键词" hint="一行一个，每个关键词在每个平台各问一次">
              <textarea
                v-model="geoKeywordsText"
                rows="6"
                placeholder="如：&#10;20万左右的新能源SUV推荐&#10;智驾最好的车"
                class="bg-card-2 focus:bg-card-white outline-none transition-colors"
                :style="{
                  width: '100%',
                  resize: 'vertical',
                  padding: '6px 10px',
                  fontSize: '12.5px',
                  fontFamily: 'inherit',
                  border: '1px solid var(--line)',
                  borderRadius: 'var(--radius-inner)',
                  color: 'var(--ink)',
                  boxSizing: 'border-box',
                }"
              />
            </FormField>

            <FormField label="AI 平台" hint="勾选要采集的 AI 平台（需先在设置里配好对应 API key）">
              <div class="flex flex-col gap-2 text-[12.5px]">
                <label
                  v-for="p in GEO_PLATFORMS"
                  :key="p.value"
                  class="flex items-center gap-2"
                >
                  <input type="checkbox" :value="p.value" v-model="geoPlatforms" />
                  {{ p.label }}
                </label>
              </div>
            </FormField>

            <FormField
              label="联网搜索"
              hint="让 AI 联网检索后再回答（关掉则只用模型内置知识，无信源）。"
              inline
            >
              <FormToggle v-model="geoWebSearch" />
            </FormField>
          </template>

          <!-- 知乎搜索排名：关键词 / 品牌词 / 别名 -->
          <template v-if="isZhihuSearch">
            <FormField label="搜索关键词" hint="一行一个，每个关键词单独搜一次（每次消耗 1 次知乎 API 配额，每天 1000）">
              <textarea
                v-model="zsKeywordsRaw"
                rows="4"
                placeholder="如：&#10;扫地机器人推荐&#10;宠物吸尘器"
                class="bg-card-2 focus:bg-card-white outline-none transition-colors"
                :style="{
                  width: '100%', resize: 'vertical', padding: '6px 10px',
                  fontSize: '12.5px', fontFamily: 'inherit', border: '1px solid var(--line)',
                  borderRadius: 'var(--radius-inner)', color: 'var(--ink)', boxSizing: 'border-box',
                }"
              />
            </FormField>
            <FormField label="目标品牌词" hint="命中前 10 结果的标题/摘要/作者就算「我」">
              <FormInput v-model="zsTargetBrand" placeholder="如：示例品牌" debounce="live" />
            </FormField>
            <FormField label="品牌别名" hint="逗号分隔；命中任一别名都算命中（可留空）">
              <FormInput v-model="zsAliasesText" placeholder="如：ExampleBrand，EB" debounce="live" />
            </FormField>
            <FormField
              label="全文级匹配"
              hint="开启后对前 10 结果逐条抓正文再匹配（更全但更慢，需在 Cookie 管理配置知乎 Cookie）"
              inline
            >
              <FormToggle v-model="zsMatchFullText" />
            </FormField>
          </template>

          <FormField
            v-if="isComment"
            label="自己发布的评论文本"
            hint="用于在评论列表里识别自家评论是否还在。"
          >
            <FormInput
              v-model="myCommentText"
              placeholder="把你发出去的评论原文粘进来"
              debounce="live"
            />
          </FormField>

          <!--
            目标品牌关键词：只对知乎有意义 —— zhihu_question adapter 的
            `_rank_brand` 用它在答案里检索品牌出现位置。评论场景这边
            匹配走的是 `my_comment_text` 文本相似度，跟品牌词没关系，
            放这里只会让用户多填一个无用字段；评论场景下整段隐藏。
          -->
          <FormField
            v-if="!isComment && !isBaidu && !isGeo && !isZhihuSearch"
            label="目标品牌关键词"
            hint="在知乎答案排序里要追的品牌关键词"
          >
            <FormInput
              v-model="targetBrand"
              placeholder="如：戴森"
              debounce="live"
            />
          </FormField>

          <FormField
            v-if="!isBaidu && !isGeo && !isZhihuSearch"
            :label="isComment ? '理想排名（前 N 位）' : 'Top-N（监测前 N 条答案）'"
            :hint="
              isComment
                ? '希望评论出现在前几位，默认 5。后台始终扫描前 150 条 hot 评论 —— 即使评论排到第 30 位也能找到并显示真实位置，超过 150 才算「丢失」。'
                : '监测「默认排序」下前 N 条答案里包含品牌词的数量，默认 10。范围 1–40，超过 40 抓取慢、noise 多。'
            "
            inline
          >
            <!--
              v-model 双向绑定（之前只有 :model-value + @commit 单向是 bug
              根因 —— FormInput 内部 proxy computed 的 getter 永远读父级
              props.modelValue，单向绑定时 proxy 实际从未变，blur 时 commit
              的还是旧值，用户改完保存毫无反应）。@commit 保留做"空值/非
              数字 fallback 到默认值"语义。
            -->
            <FormInput
              type="number"
              v-model="topN"
              :width="100"
              @commit="(v) => { if (v == null) topN = isComment ? 5 : 10; }"
            />
          </FormField>

          <FormField label="计划">
            <div class="flex flex-col gap-2 text-[12.5px]">
              <label class="flex items-center gap-2">
                <input v-model="scheduleMode" type="radio" value="manual" />
                手动 — 仅"立刻跑"按钮触发
              </label>
              <div class="flex items-center gap-2">
                <input v-model="scheduleMode" type="radio" value="daily" />
                <span>每天</span>
                <FormInput
                  v-model="dailyTime"
                  :width="100"
                  placeholder="HH:MM"
                  debounce="live"
                  :disabled="scheduleMode !== 'daily'"
                />
                <span class="text-ink-3">本地时间</span>
              </div>
              <div class="flex items-center gap-2">
                <input v-model="scheduleMode" type="radio" value="weekly" />
                <span>每周</span>
                <FormSelect
                  :model-value="weeklyDow"
                  :options="DOW_OPTIONS.map((d) => ({ label: d.label, value: d.value }))"
                  :disabled="scheduleMode !== 'weekly'"
                  width="80"
                  @update:model-value="(v) => (weeklyDow = Number(v))"
                />
                <FormInput
                  v-model="weeklyTime"
                  :width="100"
                  placeholder="HH:MM"
                  debounce="live"
                  :disabled="scheduleMode !== 'weekly'"
                />
                <span class="text-ink-3">本地时间</span>
              </div>
            </div>
          </FormField>

          <FormField label="启用" inline>
            <FormToggle v-model="enabled" />
          </FormField>
    </div>

    <template #footer>
      <Btn variant="ghost" small @click="close">取消</Btn>
      <Btn variant="solid" small :disabled="submitting" @click="submit">
        <Spinner v-if="submitting" :size="12" />
        <span>
          {{
            submitting
              ? (isEdit ? "保存中…" : "提交中…")
              : (isEdit ? "保存修改" : "添加任务")
          }}
        </span>
      </Btn>
    </template>
  </Dialog>

  <!--
    默认排除域名展示弹层（modal-in-modal）。独立 Teleport 让它直接挂在
    body 下，z-[60] 堆在 Dialog 的 z-50 之上。Dialog 的 ESC 在 popover
    open 时被 :closable="!showDefaultDomainsPopover" 关掉，避免按 ESC
    误关外层 AddTaskModal —— popover 自己用 X 按钮或 backdrop click 关。
  -->
  <Teleport to="body">
    <div
      v-if="showDefaultDomainsPopover"
      class="fixed inset-0 z-[60] flex items-center justify-center bg-black/30"
      @click.self="showDefaultDomainsPopover = false"
    >
      <div class="w-[400px] max-h-[60vh] flex flex-col rounded-lg bg-[var(--card)] p-4 shadow-xl">
        <div class="flex items-center justify-between mb-3">
          <div class="text-[13px] font-medium">默认排除域名（{{ defaultExcludeDomains.length }}）</div>
          <button
            type="button"
            class="text-[16px] leading-none"
            @click="showDefaultDomainsPopover = false"
          >×</button>
        </div>

        <div class="flex-1 overflow-auto text-[12px] font-mono space-y-1">
          <div v-if="defaultExcludeDomains.length === 0" class="text-[var(--ink-3)]">
            （空 —— 去应用设置里添加）
          </div>
          <div v-for="d in defaultExcludeDomains" :key="d">{{ d }}</div>
        </div>

        <div class="mt-3 pt-3 border-t border-[var(--line)] flex justify-between items-center">
          <button
            type="button"
            class="text-[11.5px] text-[var(--primary-deep)] hover:underline"
            @click="goToSettingsExcludeDomains"
          >
            去应用设置编辑 →
          </button>
          <button
            type="button"
            class="text-[11.5px] px-3 py-1 rounded bg-[var(--card-2)]"
            @click="showDefaultDomainsPopover = false"
          >
            关闭
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>
