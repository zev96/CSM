<script setup lang="ts">
/**
 * 批量导入监测任务 — 一次粘贴 / 上传一张表，循环 POST /api/monitor/tasks。
 *
 * 接受四种粘贴/上传格式：
 *   1. Excel 复制（TSV，列与列之间是 \t）
 *   2. CSV（列与列之间是 ,）
 *   3. xlsx / xls 文件上传（SheetJS 读取第一个 sheet 转 TSV）
 *   4. 分享文案（B 站 / 抖音「复制链接」整段文字粘贴；URL 内嵌在中文里）
 *
 * 字段顺序按平台分两套：
 *   - 知乎问题（排名监测）：问题名(可选) | 目标 URL | 目标品牌 | Top-N(可选)
 *   - 评论留存（B站/抖音/快手）：视频 URL | 评论原文     —— 只 2 列
 *     评论留存场景下任务名 / Top-N 都来自模态里的输入，不再要表里每行写。
 *     最终每行任务名 = `${批次名} - 视频 ID 尾段`，方便在任务列表里区分。
 *
 * 平台为整批共用 —— 表里不再带"平台"列，避免一行一行核实，也不会出现
 * 一半行落到知乎、一半行落到 B 站这种意料之外的混合。
 *
 * URL 抽取策略：每行先用 regex 在整行任意位置找 https://... 链接，命中
 * 则把它当作 URL 字段，剩下文本（视频标题 / 分享文案尾部「复制此链接...」）
 * 作为噪音丢掉。这样用户从抖音、B站「复制」按钮拿到的整段文案能直接粘进来。
 * 抓到 URL 后会做一道清洗：剥 B 站的 share_source / vd_source / spm 追踪参数、
 * 去掉中文末尾标点。
 *
 * 没有走 /api/monitor/tasks/bulk 因为后端没有这个端点；这里就老老实实
 * 顺序提交，把每行的成功/失败结果汇总成一条 toast。
 */
import { computed, ref, watch } from "vue";
import * as XLSX from "xlsx";

import Icon from "@/components/ui/Icon.vue";
import Spinner from "@/components/ui/Spinner.vue";

import { useSidecar } from "@/stores/sidecar";
import { useToast } from "@/composables/useToast";

type Platform = "zhihu_question" | "bilibili_comment" | "douyin_comment" | "kuaishou_comment" | "baidu_keyword";

const props = defineProps<{
  open: boolean;
  defaultType?: Platform;
}>();
const emit = defineEmits<{
  (e: "update:open", v: boolean): void;
  (e: "imported", count: number): void;
}>();

const sidecar = useSidecar();
const toast = useToast();

const TYPES: Array<{ value: Platform; label: string }> = [
  { value: "zhihu_question", label: "知乎问题（排名监测）" },
  { value: "bilibili_comment", label: "B 站评论留存" },
  { value: "douyin_comment", label: "抖音评论留存" },
  { value: "kuaishou_comment", label: "快手评论留存" },
  { value: "baidu_keyword", label: "百度关键词排名" },
];

const platform = ref<Platform>("zhihu_question");
const rawText = ref("");
const topN = ref(5);
const scheduleMode = ref<"manual" | "daily">("manual");
const dailyTime = ref("09:00");
const enabled = ref(true);
// 评论场景下整批共用的任务名（"戴森评论监测"之类）。每行最终的 task.name
// 会派生成 `${batchName} - <video id 尾段>`，方便在监测中心列表里区分。
const batchName = ref("");
// 二进制（xlsx / 图片）误传时记下的错误，给 UI 显示一条明确提示。
const importError = ref<string | null>(null);

const submitting = ref(false);
const progress = ref({ done: 0, total: 0 });

const isComment = computed(() =>
  platform.value !== "zhihu_question" && platform.value !== "baidu_keyword"
);

watch(
  () => props.open,
  (v) => {
    if (v && props.defaultType) platform.value = props.defaultType;
  },
);

interface ParsedRow {
  name: string;
  url: string;
  brandOrComment: string;
  topN: number;
  // Computed: 行号（1-based）+ 错误信息（若有）
  line: number;
  error?: string;
}

function deriveNameFromUrl(url: string): string {
  try {
    const u = new URL(url);
    const seg = u.pathname.split("/").filter(Boolean);
    return seg[seg.length - 1] ?? u.hostname;
  } catch {
    return url.slice(0, 30);
  }
}

// 整行任意位置抽 URL；中文标点、全角空格都算 URL 边界。
const URL_RE = /https?:\/\/[^\s　，。！？、（）()【】《》"'`<>]+/i;

/**
 * 从一段杂文里抽 URL 并清洗。返回 null 表示没找到。
 *
 * 处理两种典型分享文案：
 *   - 抖音：「8.71 :9pm 05/09 FHV:/ s@E.hO 自动上下水洗地机... # 洗地机
 *     https://v.douyin.com/_S2Z9a5iv74/ 复制此链接，打开Dou音搜索...」
 *   - B 站：「【499元小米无线吸尘器Lite体验好吗？】
 *     https://www.bilibili.com/video/BV1fT4y1T7pK/?share_source=copy_web&vd_source=...」
 *
 * B 站 URL 上的 share_source / vd_source / spm_id_from / from_spmid /
 * buvid 这些追踪参数会被剥掉；保留 `?p=N` 等真正影响视频定位的参数。
 */
function extractAndNormalizeUrl(text: string): string | null {
  const m = text.match(URL_RE);
  if (!m) return null;
  let url = m[0];
  // URL 末尾常常粘上「,」「。」「)」之类的，先做一道宽松 strip
  url = url.replace(/[.,;:!?，。！？、)\]）】>}]+$/u, "");
  // B 站追踪参数清洗（其它平台保留全部参数，避免误伤）
  try {
    const u = new URL(url);
    if (/(^|\.)bilibili\.com$/i.test(u.hostname) || /^b23\.tv$/i.test(u.hostname)) {
      const dropKeys = [
        "share_source",
        "share_medium",
        "share_plat",
        "share_session_id",
        "share_tag",
        "share_times",
        "share_from",
        "vd_source",
        "spm_id_from",
        "from_spmid",
        "from_source",
        "bbid",
        "ts",
        "buvid",
        "msource",
        "unique_k",
        "up_id",
      ];
      for (const k of dropKeys) u.searchParams.delete(k);
      url = u.toString();
      // URL 构造器会给空 query 留个 `?`，手动清掉
      if (url.endsWith("?")) url = url.slice(0, -1);
    }
  } catch {
    /* URL 不合法的就保持原样让后端去处理 */
  }
  return url;
}

function splitFields(line: string): string[] {
  // 优先 TAB（Excel 粘贴），其次逗号，最后整行当一个字段（后续会再
  // 用 extractAndNormalizeUrl 从里面抽 URL）。
  if (line.includes("\t")) return line.split("\t").map((s) => s.trim());
  if (line.includes(",")) return line.split(",").map((s) => s.trim());
  return [line.trim()];
}

/**
 * 给一行字段数组里的 URL「就地清洗」：保留字段顺序不变。
 *
 *   1. 每个以 http(s):// 开头的字段，跑一次 normalize（剥 B 站追踪参数、
 *      去末尾标点）。这是已经成形的 TAB/CSV 表格的常见情形。
 *   2. 若整行没有任何字段以 http 开头，但某个字段「内嵌」了 URL（分享
 *      文案场景），把那个字段替换成抽到的纯 URL。剩下的列（评论原文等）
 *      不动。
 *
 * 保持原列顺序非常重要：现有的知乎 3 列格式 `问题名 ⇥ URL ⇥ 品牌` 完全
 * 依赖 fields 的位置语义；如果重排会导致品牌字段被识别成问题名。
 */
function normalizeFieldUrls(fields: string[]): string[] {
  const out = [...fields];
  let anyHttpPrefix = false;
  for (let i = 0; i < out.length; i++) {
    if (/^https?:\/\//.test(out[i])) {
      anyHttpPrefix = true;
      const cleaned = extractAndNormalizeUrl(out[i]);
      if (cleaned) out[i] = cleaned;
    }
  }
  if (anyHttpPrefix) return out;
  // 没有以 http 开头的字段 —— 看是否有字段内嵌 URL（分享文案）
  for (let i = 0; i < out.length; i++) {
    if (!out[i]) continue;
    const cleaned = extractAndNormalizeUrl(out[i]);
    if (cleaned) {
      out[i] = cleaned;
      return out;
    }
  }
  return out;
}

const rows = computed<ParsedRow[]>(() => {
  const out: ParsedRow[] = [];
  const lines = rawText.value.split(/\r?\n/);
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (!line.trim()) continue;
    // 跳过表头行（用户把 Excel 表头一起粘进来了）。注意：分享文案里也
    // 经常出现「视频」「链接」二字（"打开抖音直接观看视频" / "复制此链接"），
    // 所以这里不能只看关键词 —— 必须确认整行任意位置都没有 URL，才当作纯表头。
    if (i === 0 && /任务名|name|url|关键词|品牌|评论|链接|视频/i.test(line) && !URL_RE.test(line)) {
      continue;
    }
    // 按 TAB/逗号切完后再就地清洗每个字段里的 URL：
    //   - 已经是 URL 的字段做一次 normalize（剥 B 站追踪参数）
    //   - 整行没有字段以 http 开头时，会扫一遍把内嵌 URL 抽出来，覆盖
    //     掉原字段里的中文壳子（分享文案路径）
    // 列顺序保持原样 —— 知乎的 `问题名 ⇥ URL ⇥ 品牌` 顺序依赖位置语义。
    const fields = normalizeFieldUrls(splitFields(line));
    let name = "";
    let url = "";
    let brandOrComment = "";
    let n = topN.value;

    if (isComment.value) {
      // 评论场景固定 2 列：视频 URL + 评论原文。任务名 / Top-N 来自模态。
      // 若用户只粘了 URL（没填评论），也能识别，但 brandOrComment 会留空
      // 然后被下面的校验判错。
      const first = fields[0] ?? "";
      if (/^https?:\/\//.test(first)) {
        url = first;
        brandOrComment = fields[1] ?? "";
      } else if (fields.length >= 2 && /^https?:\/\//.test(fields[1] ?? "")) {
        // 容错：用户把列顺序写反（评论 + URL），还是按 URL/评论 拆开。
        url = fields[1];
        brandOrComment = fields[0];
      } else {
        url = first;
        brandOrComment = fields[1] ?? "";
      }
      const tail = deriveNameFromUrl(url);
      const trimmedBatch = batchName.value.trim();
      // 任务名由模态里的「任务名」+ 视频 ID 尾段拼成，避免列表里一整排
      // 同名条目相互覆盖；用户没填批次名时退回纯 URL 尾段。
      name = trimmedBatch ? `${trimmedBatch} - ${tail}` : tail;
    } else {
      // 知乎排名监测沿用原来的 3-列格式：问题名 | URL | 品牌 | Top-N(可选)
      if (fields.length === 1) {
        url = fields[0];
        name = deriveNameFromUrl(url);
      } else if (fields.length >= 2) {
        if (/^https?:\/\//.test(fields[0])) {
          url = fields[0];
          brandOrComment = fields[1] ?? "";
          if (fields[2]) n = Number(fields[2]) || topN.value;
          name = deriveNameFromUrl(url);
        } else {
          name = fields[0];
          url = fields[1] ?? "";
          brandOrComment = fields[2] ?? "";
          if (fields[3]) n = Number(fields[3]) || topN.value;
        }
      }
    }

    // 评论场景：Top-N 始终来自模态的输入，忽略表里任何第三列数字
    if (isComment.value) n = topN.value;

    const row: ParsedRow = {
      name: name.trim(),
      url: url.trim(),
      brandOrComment: brandOrComment.trim(),
      topN: n,
      line: i + 1,
    };

    // 校验
    if (!row.url) row.error = "缺少 URL";
    else if (!/^https?:\/\//.test(row.url)) row.error = "URL 无效";
    else if (!row.name) row.error = "缺少任务名";
    else if (isComment.value && !row.brandOrComment) row.error = "缺少评论原文";
    else if (!isComment.value && !row.brandOrComment) row.error = "缺少目标品牌";

    out.push(row);
  }
  return out;
});

const validRows = computed(() => rows.value.filter((r) => !r.error));
const errorRows = computed(() => rows.value.filter((r) => r.error));

function close() {
  if (submitting.value) return;
  emit("update:open", false);
  rawText.value = "";
  importError.value = null;
  batchName.value = "";
  progress.value = { done: 0, total: 0 };
}

/** xlsx / docx / 图片等 ZIP/二进制文件的前几个字节，命中就拒掉。 */
function detectBinaryHeader(bytes: Uint8Array): string | null {
  if (bytes.length < 4) return null;
  // ZIP-based formats (xlsx, docx, pptx, ods) — 头四字节 "PK\x03\x04"
  if (bytes[0] === 0x50 && bytes[1] === 0x4b) {
    return "检测到 Excel/Zip 二进制格式（.xlsx 不是纯文本）。请在 Excel 里「另存为 CSV (逗号分隔)」或选中数据复制粘贴到下方文本框。";
  }
  // 老式 .xls (CFB) — D0 CF 11 E0
  if (
    bytes[0] === 0xd0 &&
    bytes[1] === 0xcf &&
    bytes[2] === 0x11 &&
    bytes[3] === 0xe0
  ) {
    return "检测到旧版 .xls 二进制格式。请另存为 .csv 后再上传，或直接从 Excel 选中数据复制粘贴。";
  }
  return null;
}

/**
 * 按 BOM → 严格 UTF-8 → GB18030 顺序探测 CSV/TXT 编码。
 *
 * 中国版 Excel 默认导出 CSV 是 GBK/GB18030，不是 UTF-8 —— `File.text()`
 * 默认按 UTF-8 解会把中文解成 "����" 乱码（替换字符 U+FFFD）。这里：
 *   1. 看 BOM 字节，命中直接按 BOM 解
 *   2. 否则用 fatal:true 严格 UTF-8 试；GBK 数据里 0x80-0xFF 高位双字节
 *      碰到 UTF-8 解析器一定抛错，借此识别
 *   3. 落到 GB18030（GB18030 ⊇ GBK ⊇ GB2312，覆盖 99% 中文 Excel 导出）
 *
 * 浏览器 TextDecoder 必带 utf-8，不一定带 gb18030 —— 实测 Chrome/Edge
 * (Tauri WebView2) 都支持；如果某天遇到不支持的环境会抛 RangeError，
 * 这里捕到就提示用户改存 UTF-8。
 */
function decodeFileBytes(bytes: Uint8Array): { text: string; encoding: string; warn?: string } {
  // BOM 优先
  if (bytes.length >= 3 && bytes[0] === 0xef && bytes[1] === 0xbb && bytes[2] === 0xbf) {
    return { text: new TextDecoder("utf-8").decode(bytes.subarray(3)), encoding: "utf-8 (BOM)" };
  }
  if (bytes.length >= 2 && bytes[0] === 0xff && bytes[1] === 0xfe) {
    return { text: new TextDecoder("utf-16le").decode(bytes.subarray(2)), encoding: "utf-16le" };
  }
  if (bytes.length >= 2 && bytes[0] === 0xfe && bytes[1] === 0xff) {
    return { text: new TextDecoder("utf-16be").decode(bytes.subarray(2)), encoding: "utf-16be" };
  }
  // 严格 UTF-8
  try {
    const text = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
    return { text, encoding: "utf-8" };
  } catch {
    /* fall through */
  }
  // GB18030 兜底（Windows 中文 Excel 默认）
  try {
    const text = new TextDecoder("gb18030").decode(bytes);
    return { text, encoding: "gb18030" };
  } catch {
    // 极少数环境不支持 gb18030，退回 UTF-8 宽松模式（坏字节变 U+FFFD）
    const text = new TextDecoder("utf-8").decode(bytes);
    return {
      text,
      encoding: "utf-8 (lossy)",
      warn: "无法识别 GBK 编码，已宽松按 UTF-8 解。若仍乱码请在 Excel 另存为时选择「CSV UTF-8（逗号分隔）」。",
    };
  }
}

/**
 * 用 SheetJS 读 xlsx/xls：取第一个 sheet，按 TSV 输出（列与列之间 \t），
 * 后续 rawText → rows 解析路径完全不动。
 *
 * 用 `sheet_to_csv(sheet, { FS: "\t" })` 而非 `sheet_to_json` 是为了和
 * Excel 复制粘贴产生的剪贴板内容（也是 TAB 分隔）保持一致的字段语义；
 * 同时避开 sheet_to_json 在空表头/合并单元格上的坑。
 *
 * RAW: true 让数字保持原文本，不会被本地化成 `1,234.5`（默认 Excel 区域设置）。
 */
function xlsxToTsv(bytes: Uint8Array): string {
  const wb = XLSX.read(bytes, { type: "array" });
  const firstName = wb.SheetNames[0];
  if (!firstName) return "";
  const sheet = wb.Sheets[firstName];
  return XLSX.utils.sheet_to_csv(sheet, { FS: "\t", RS: "\n", blankrows: false });
}

async function onFile(e: Event) {
  const input = e.target as HTMLInputElement;
  const f = input.files?.[0];
  if (!f) return;
  importError.value = null;
  const name = (f.name || "").toLowerCase();
  const buf = await f.arrayBuffer();
  const bytes = new Uint8Array(buf);

  // xlsx / xls / xlsm —— 走 SheetJS 解析。扩展名先卡一道，避免把同样
  // PK 开头的 docx/pptx 当成表格强解。
  if (name.endsWith(".xlsx") || name.endsWith(".xls") || name.endsWith(".xlsm")) {
    try {
      const tsv = xlsxToTsv(bytes);
      if (!tsv.trim()) {
        importError.value = "Excel 文件第一个 sheet 是空的，没读到任何行。";
        rawText.value = "";
      } else {
        rawText.value = tsv;
      }
    } catch (err: any) {
      importError.value = `读取 Excel 失败：${err?.message ?? err}。请确认文件没损坏，或在 Excel 里另存为 CSV 后再上传。`;
      rawText.value = "";
    }
    input.value = "";
    return;
  }

  // 非 xlsx 但二进制头（图片 / 老式 docx 等误传） —— 给明确提示
  const binErr = detectBinaryHeader(bytes);
  if (binErr) {
    importError.value = binErr;
    rawText.value = "";
    input.value = "";
    return;
  }
  const decoded = decodeFileBytes(bytes);
  if (decoded.warn) importError.value = decoded.warn;
  rawText.value = decoded.text;
}

function loadExample() {
  importError.value = null;
  if (isComment.value) {
    // 2 列：视频 URL + 评论原文。任务名 + Top-N 由模态填。
    rawText.value = [
      "https://www.bilibili.com/video/BV1xx411c7AB\t我家这台投影仪用了半年的真实感受...",
      "https://www.bilibili.com/video/BV1yy411d8CD\t用了三个月，吸毛能力确实强...",
      "https://www.bilibili.com/video/BV1zz411e9EF\t冬天必备，亲测除菌效果...",
    ].join("\n");
  } else {
    rawText.value = [
      "无线吸尘器哪款好用\thttps://www.zhihu.com/question/12345678\t戴森\t5",
      "宠物家庭吸尘器\thttps://www.zhihu.com/question/23456789\t小米\t5",
      "母婴加湿器推荐\thttps://www.zhihu.com/question/34567890\t舒乐氏\t10",
    ].join("\n");
  }
}

// 用户直接往 textarea 里粘内容（不是上传文件）时也嗅探一下，命中
// "PK"-zip 头或 \x00 都意味着粘了 xlsx 二进制片段。
watch(rawText, (v) => {
  if (!v) return;
  if (v.startsWith("PK")) {
    importError.value =
      "粘贴的内容像是 Excel 二进制（以 PK 开头）。请改用上方的『选择文件』按钮上传 .xlsx，或在 Excel 里选中单元格复制（不是复制整个文件）。";
    return;
  }
  if (v.includes("\x00")) {
    importError.value = "粘贴的内容含有 0x00 字节，不像是纯文本。";
  }
});

async function submitAll() {
  if (!validRows.value.length) {
    toast.warn("没有可提交的行");
    return;
  }
  submitting.value = true;
  progress.value = { done: 0, total: validRows.value.length };
  let okCount = 0;
  const failures: string[] = [];

  for (const row of validRows.value) {
    try {
      const body = {
        type: platform.value,
        name: row.name,
        target_url: row.url,
        config: isComment.value
          ? { my_comment_text: row.brandOrComment, top_n: row.topN }
          : { target_brand: row.brandOrComment, top_n: row.topN },
        schedule_cron:
          scheduleMode.value === "manual" ? "manual" : dailyTime.value,
        enabled: enabled.value,
      };
      await sidecar.client.post("/api/monitor/tasks", body);
      okCount++;
    } catch (e: any) {
      const detail = e?.response?.data?.detail ?? e?.message ?? e;
      failures.push(`第 ${row.line} 行 (${row.name})：${typeof detail === "string" ? detail : JSON.stringify(detail)}`);
    } finally {
      progress.value.done++;
    }
  }

  submitting.value = false;
  if (failures.length === 0) {
    toast.success(`已批量创建 ${okCount} 个任务`);
    emit("imported", okCount);
    close();
  } else {
    toast.warn(`完成 ${okCount} / ${validRows.value.length}，失败 ${failures.length} 行`);
    if (okCount > 0) emit("imported", okCount);
    // 失败详情打印到 console，避免 toast 太长
    console.warn("[batch import failures]", failures);
  }
}
</script>

<template>
  <Teleport to="body">
    <div
      v-if="open"
      class="fixed inset-0 z-40 flex items-center justify-center"
      :style="{ background: 'rgba(28,26,23,0.4)' }"
      @click.self="close"
    >
      <div
        class="anim-up overflow-hidden"
        :style="{
          background: 'var(--bg-inner)',
          width: '720px',
          maxWidth: '94vw',
          maxHeight: '92vh',
          borderRadius: 'var(--radius-card)',
          border: '1px solid var(--line)',
          boxShadow: '0 24px 64px rgba(0,0,0,0.18)',
          display: 'flex',
          flexDirection: 'column',
        }"
      >
        <!-- header -->
        <div
          class="flex items-center justify-between flex-shrink-0"
          :style="{ padding: '20px 24px', borderBottom: '1px solid var(--line)' }"
        >
          <div>
            <div class="font-display text-[18px] font-bold">批量导入监测任务</div>
            <div class="mt-1 text-[11.5px]" :style="{ color: 'var(--ink-3)' }">
              支持 .xlsx / .csv 上传 · Excel 复制粘贴 · 抖音/B站「复制链接」分享文案
            </div>
          </div>
          <button
            type="button"
            class="inline-flex items-center justify-center"
            :style="{
              width: '32px',
              height: '32px',
              borderRadius: '999px',
              background: 'var(--card)',
              border: '1px solid var(--line)',
              color: 'var(--ink-2)',
            }"
            :disabled="submitting"
            @click="close"
          >
            <Icon name="x" :size="16" />
          </button>
        </div>

        <!-- body (scrollable) -->
        <div
          class="flex flex-col gap-4 flex-1 min-h-0 overflow-y-auto"
          :style="{ padding: '20px 24px' }"
        >
          <!-- platform + 模板选择行 -->
          <div class="flex items-center gap-2">
            <label class="text-[12px] font-medium" :style="{ color: 'var(--ink-2)', minWidth: '60px' }">平台</label>
            <select
              v-model="platform"
              class="text-[12.5px]"
              :style="{
                flex: 1,
                height: '34px',
                background: 'var(--card)',
                border: '1px solid var(--line)',
                borderRadius: '8px',
                padding: '0 12px',
                color: 'var(--ink)',
              }"
            >
              <option v-for="t in TYPES" :key="t.value" :value="t.value">
                {{ t.label }}
              </option>
            </select>
          </div>

          <!-- 任务名（评论场景才需要，整批共用一个名字） -->
          <div v-if="isComment" class="flex items-center gap-2">
            <label
              class="text-[12px] font-medium"
              :style="{ color: 'var(--ink-2)', minWidth: '60px' }"
            >任务名</label>
            <input
              v-model="batchName"
              type="text"
              placeholder="如：戴森评论监测（每条视频会自动加上视频 ID 后缀）"
              :style="{
                flex: 1,
                height: '34px',
                background: 'var(--card)',
                border: '1px solid var(--line)',
                borderRadius: '8px',
                padding: '0 12px',
                fontSize: '12.5px',
                color: 'var(--ink)',
              }"
            >
          </div>

          <!-- 格式说明 -->
          <div
            class="text-[12px]"
            :style="{
              background: 'var(--card-2)',
              border: '1px solid var(--line)',
              borderRadius: '10px',
              padding: '12px',
              color: 'var(--ink-2)',
              lineHeight: 1.7,
            }"
          >
            <div class="mb-1 font-medium" :style="{ color: 'var(--ink)' }">列顺序</div>
            <div class="font-mono text-[11.5px]" :style="{ color: 'var(--ink-2)' }">
              <template v-if="isComment">
                视频 URL ⇥
                <span :style="{ color: 'var(--primary-deep)' }">评论原文</span>
              </template>
              <template v-else-if="platform === 'baidu_keyword'">
                任务名 ⇥ search:关键词1|关键词2|... ⇥
                <span :style="{ color: 'var(--primary-deep)' }">目标品牌（单词）</span>
              </template>
              <template v-else>
                问题名字 ⇥ 目标 URL ⇥
                <span :style="{ color: 'var(--primary-deep)' }">目标品牌</span>
                ⇥ Top-N(可选)
              </template>
            </div>
            <div class="mt-1.5 text-[11.5px]" :style="{ color: 'var(--ink-3)' }">
              <template v-if="isComment">
                只两列：视频链接 + 评论原文。任务名 / Top-N 在上方填一次即可应用到整批。支持 .xlsx / .csv 上传，也支持把抖音/B站「复制链接」整段分享文案直接粘进来（URL 会自动识别）。
              </template>
              <template v-else-if="platform === 'baidu_keyword'">
                URL 列填 <code>search:</code> 加多个搜索关键词（用 <code>|</code> 分隔，每个关键词单独搜一次）；
                品牌列填 <strong>一个</strong> 目标品牌词。支持从 Excel 复制粘贴（TAB 分隔）、上传 .xlsx / .csv。
              </template>
              <template v-else>
                支持从 Excel 复制粘贴（TAB 分隔）、上传 .xlsx / .csv；只粘 URL 也行，任务名会从 URL 自动派生。
              </template>
            </div>
          </div>

          <!-- 二进制 / xlsx 误传错误条 -->
          <div
            v-if="importError"
            class="text-[12px]"
            :style="{
              background: 'rgba(216,90,72,0.08)',
              border: '1px solid rgba(216,90,72,0.35)',
              borderRadius: '10px',
              padding: '10px 12px',
              color: 'var(--red, #d85a48)',
              lineHeight: 1.55,
            }"
          >
            {{ importError }}
          </div>

          <!-- file + example -->
          <div class="flex items-center gap-2">
            <label
              class="inline-flex cursor-pointer items-center gap-1.5 text-[12px]"
              :style="{
                background: 'var(--card)',
                border: '1px solid var(--line)',
                borderRadius: '999px',
                padding: '6px 14px',
                color: 'var(--ink-2)',
              }"
            >
              <Icon name="folder" :size="13" />
              <span>选择文件 (.xlsx / .csv / .txt)</span>
              <input
                type="file"
                accept=".csv,.txt,.tsv,.xlsx,.xls,.xlsm"
                class="hidden"
                @change="onFile"
              />
            </label>
            <button
              type="button"
              class="inline-flex items-center gap-1.5 text-[12px]"
              :style="{
                background: 'transparent',
                border: '1px solid var(--line)',
                borderRadius: '999px',
                padding: '6px 14px',
                color: 'var(--ink-2)',
              }"
              @click="loadExample"
            >
              <Icon name="copy" :size="12" />
              <span>填入示例</span>
            </button>
            <span class="ml-auto text-[11.5px]" :style="{ color: 'var(--ink-3)' }">
              {{ rows.length }} 行 · 有效 {{ validRows.length }} · 错误 {{ errorRows.length }}
            </span>
          </div>

          <!-- textarea -->
          <textarea
            v-model="rawText"
            spellcheck="false"
            placeholder="无线吸尘器哪款好用&#9;https://www.zhihu.com/question/12345&#9;戴森&#9;5"
            :style="{
              width: '100%',
              minHeight: '180px',
              padding: '12px',
              background: 'var(--card)',
              border: '1px solid var(--line)',
              borderRadius: '10px',
              fontFamily: 'ui-monospace, SF Mono, Menlo, Consolas, monospace',
              fontSize: '12px',
              lineHeight: 1.55,
              color: 'var(--ink)',
              resize: 'vertical',
              outline: 'none',
            }"
          />

          <!-- preview table -->
          <div v-if="rows.length" class="flex flex-col">
            <div class="mb-2 text-[12px] font-medium" :style="{ color: 'var(--ink)' }">
              预览
            </div>
            <div
              :style="{
                border: '1px solid var(--line)',
                borderRadius: '10px',
                overflow: 'hidden',
              }"
            >
              <div
                class="grid items-center text-[11px] uppercase"
                :style="{
                  gridTemplateColumns: '40px 1.6fr 1.4fr 1fr 60px 80px',
                  background: 'var(--card-2)',
                  padding: '8px 12px',
                  letterSpacing: '1px',
                  color: 'var(--ink-3)',
                }"
              >
                <div>#</div>
                <div>{{ isComment ? "任务名（自动）" : "问题名字" }}</div>
                <div>URL</div>
                <div>{{ isComment ? "评论" : "品牌" }}</div>
                <div>Top-N</div>
                <div>状态</div>
              </div>
              <div :style="{ maxHeight: '200px', overflowY: 'auto' }">
                <div
                  v-for="r in rows"
                  :key="r.line"
                  class="grid items-center text-[12px]"
                  :style="{
                    gridTemplateColumns: '40px 1.6fr 1.4fr 1fr 60px 80px',
                    padding: '8px 12px',
                    borderTop: '1px solid var(--line)',
                    background: r.error ? 'rgba(216,90,72,0.06)' : 'transparent',
                  }"
                >
                  <div :style="{ color: 'var(--ink-3)' }">{{ r.line }}</div>
                  <div class="truncate">{{ r.name || "—" }}</div>
                  <div class="truncate font-mono text-[11px]" :style="{ color: 'var(--ink-2)' }">
                    {{ r.url || "—" }}
                  </div>
                  <div class="truncate" :style="{ color: 'var(--ink-2)' }">
                    {{ r.brandOrComment || "—" }}
                  </div>
                  <div class="font-mono text-[11px]">{{ r.topN }}</div>
                  <div>
                    <span
                      v-if="r.error"
                      class="text-[10.5px]"
                      :style="{ color: 'var(--red, #d85a48)' }"
                    >{{ r.error }}</span>
                    <span
                      v-else
                      class="text-[10.5px]"
                      :style="{ color: 'var(--green, #6c9b5d)' }"
                    >就绪</span>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- 默认理想排名 + 计划 -->
          <div class="grid grid-cols-2 gap-4">
            <div>
              <div class="mb-1 text-[12px] font-medium" :style="{ color: 'var(--ink-2)' }">
                <span :title="isComment ? '希望评论排在前几位（默认 5）。后台始终扫描前 150 条，能看到真实位置。' : 'Top-N 阈值'">
                  {{ isComment ? '理想排名（前 N 位）' : '默认 Top-N' }}
                </span>
              </div>
              <input
                type="number"
                :value="topN"
                min="1"
                max="100"
                :style="{
                  width: '100%',
                  height: '34px',
                  padding: '0 12px',
                  background: 'var(--card)',
                  border: '1px solid var(--line)',
                  borderRadius: '8px',
                  fontSize: '12.5px',
                  color: 'var(--ink)',
                }"
                @change="(e) => (topN = Number((e.target as HTMLInputElement).value) || 5)"
              >
            </div>
            <div>
              <div class="mb-1 text-[12px] font-medium" :style="{ color: 'var(--ink-2)' }">
                计划
              </div>
              <div class="flex items-center gap-2">
                <select
                  v-model="scheduleMode"
                  class="text-[12.5px]"
                  :style="{
                    flex: 1,
                    height: '34px',
                    background: 'var(--card)',
                    border: '1px solid var(--line)',
                    borderRadius: '8px',
                    padding: '0 12px',
                    color: 'var(--ink)',
                  }"
                >
                  <option value="manual">手动触发</option>
                  <option value="daily">每天</option>
                </select>
                <input
                  v-if="scheduleMode === 'daily'"
                  v-model="dailyTime"
                  placeholder="HH:MM"
                  :style="{
                    width: '90px',
                    height: '34px',
                    padding: '0 10px',
                    background: 'var(--card)',
                    border: '1px solid var(--line)',
                    borderRadius: '8px',
                    fontSize: '12.5px',
                    color: 'var(--ink)',
                  }"
                >
              </div>
            </div>
          </div>
        </div>

        <!-- footer -->
        <div
          class="flex items-center justify-between flex-shrink-0"
          :style="{ padding: '14px 24px', borderTop: '1px solid var(--line)' }"
        >
          <div class="text-[11.5px]" :style="{ color: 'var(--ink-3)' }">
            <template v-if="submitting">
              提交中… {{ progress.done }} / {{ progress.total }}
            </template>
            <template v-else-if="rows.length">
              即将提交 <span :style="{ color: 'var(--ink)' }">{{ validRows.length }}</span> 行
            </template>
          </div>
          <div class="flex gap-2">
            <button
              type="button"
              :style="{
                background: 'transparent',
                border: '1px solid var(--line)',
                color: 'var(--ink-2)',
                padding: '7px 18px',
                fontSize: '12.5px',
                borderRadius: '999px',
              }"
              :disabled="submitting"
              @click="close"
            >取消</button>
            <button
              type="button"
              class="inline-flex items-center gap-1.5"
              :style="{
                background: validRows.length ? 'var(--dark)' : 'var(--card-2)',
                color: validRows.length ? '#fff' : 'var(--ink-3)',
                padding: '7px 18px',
                fontSize: '12.5px',
                fontWeight: 500,
                borderRadius: '999px',
                cursor: validRows.length && !submitting ? 'pointer' : 'not-allowed',
                opacity: submitting ? 0.6 : 1,
              }"
              :disabled="submitting || !validRows.length"
              @click="submitAll"
            >
              <Spinner v-if="submitting" :size="12" />
              <Icon v-else name="check" :size="13" />
              <span>{{ submitting ? "提交中…" : `批量提交 (${validRows.length})` }}</span>
            </button>
          </div>
        </div>
      </div>
    </div>
  </Teleport>
</template>
