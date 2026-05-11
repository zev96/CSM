<script setup lang="ts">
/**
 * 批量导入监测任务 — 一次粘贴 / 上传一张表，循环 POST /api/monitor/tasks。
 *
 * 接受三种粘贴格式：
 *   1. Excel 复制（TSV，列与列之间是 \t）
 *   2. CSV（列与列之间是 ,）
 *   3. 仅 URL（一行一个 URL，任务名自动从 URL host 截一段）
 *
 * 字段顺序固定（与设计稿里"目标 URL + 任务名 + 关键词/评论"对齐）：
 *   任务名(可选) | 目标 URL(必填) | 目标品牌 / 评论原文(必填) | Top-N(可选,默认 5)
 *
 * 平台为整批共用 —— 表里不再带"平台"列，避免一行一行核实，也不会出现
 * 一半行落到知乎、一半行落到 B 站这种意料之外的混合。
 *
 * 没有走 /api/monitor/tasks/bulk 因为后端没有这个端点；这里就老老实实
 * 顺序提交，把每行的成功/失败结果汇总成一条 toast。
 */
import { computed, ref, watch } from "vue";

import Icon from "@/components/ui/Icon.vue";
import Spinner from "@/components/ui/Spinner.vue";

import { useSidecar } from "@/stores/sidecar";
import { useToast } from "@/composables/useToast";

type Platform = "zhihu_question" | "bilibili_comment" | "douyin_comment" | "kuaishou_comment";

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
];

const platform = ref<Platform>("zhihu_question");
const rawText = ref("");
const topN = ref(5);
const scheduleMode = ref<"manual" | "daily">("manual");
const dailyTime = ref("09:00");
const enabled = ref(true);

const submitting = ref(false);
const progress = ref({ done: 0, total: 0 });

const isComment = computed(() => platform.value !== "zhihu_question");

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

function splitFields(line: string): string[] {
  // 优先 TAB（Excel 粘贴），其次逗号，最后整行当 URL。
  if (line.includes("\t")) return line.split("\t").map((s) => s.trim());
  if (line.includes(",")) return line.split(",").map((s) => s.trim());
  return [line.trim()];
}

const rows = computed<ParsedRow[]>(() => {
  const out: ParsedRow[] = [];
  const lines = rawText.value.split(/\r?\n/);
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (!line.trim()) continue;
    // 跳过表头行（用户把 Excel 表头一起粘进来了）
    if (i === 0 && /任务名|name|url|关键词|品牌|评论/i.test(line) && !/^https?:\/\//.test(line)) {
      continue;
    }
    const fields = splitFields(line);
    let name = "";
    let url = "";
    let brandOrComment = "";
    let n = topN.value;

    if (fields.length === 1) {
      // 仅 URL 模式
      url = fields[0];
      name = deriveNameFromUrl(url);
    } else if (fields.length >= 2) {
      // 自动判断：若第一列像 URL，则按 [URL, 关键词?, TopN?] 解析；否则
      // 按 [任务名, URL, 关键词, TopN?]。
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
  progress.value = { done: 0, total: 0 };
}

async function onFile(e: Event) {
  const f = (e.target as HTMLInputElement).files?.[0];
  if (!f) return;
  const text = await f.text();
  rawText.value = text;
}

function loadExample() {
  if (isComment.value) {
    rawText.value = [
      "客厅投影仪 100 寸\thttps://www.bilibili.com/video/BV1xx411c7AB\t我家这台投影仪用了半年的真实感受...\t10",
      "宠物吸尘器无线\thttps://www.bilibili.com/video/BV1yy411d8CD\t用了三个月，吸毛能力确实强...\t10",
      "加湿器除菌\thttps://www.bilibili.com/video/BV1zz411e9EF\t冬天必备，亲测除菌效果...\t5",
    ].join("\n");
  } else {
    rawText.value = [
      "无线吸尘器哪款好用\thttps://www.zhihu.com/question/12345678\t戴森\t5",
      "宠物家庭吸尘器\thttps://www.zhihu.com/question/23456789\t小米\t5",
      "母婴加湿器推荐\thttps://www.zhihu.com/question/34567890\t舒乐氏\t10",
    ].join("\n");
  }
}

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
              从 Excel 复制粘贴 / 上传 CSV / 一行一条 URL
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
              {{ isComment ? "任务名" : "问题名字" }} ⇥ 目标 URL ⇥
              <span :style="{ color: 'var(--primary-deep)' }">
                {{ isComment ? "评论原文" : "目标品牌" }}
              </span>
              ⇥ Top-N(可选)
            </div>
            <div class="mt-1.5 text-[11.5px]" :style="{ color: 'var(--ink-3)' }">
              支持从 Excel 直接复制粘贴（TAB 分隔）或上传 CSV；只粘 URL 也行，任务名会从 URL 自动派生。
            </div>
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
              <span>选择文件 (.csv / .txt)</span>
              <input
                type="file"
                accept=".csv,.txt,.tsv"
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
                <div>{{ isComment ? "任务名" : "问题名字" }}</div>
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

          <!-- 默认 Top-N + 计划 -->
          <div class="grid grid-cols-2 gap-4">
            <div>
              <div class="mb-1 text-[12px] font-medium" :style="{ color: 'var(--ink-2)' }">
                默认 Top-N
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
