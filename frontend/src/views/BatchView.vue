<script setup lang="ts">
/**
 * 批量生成 — 关键词列表 → 队列 → SSE 实时推 item_started / item_finished
 * → 取消按钮 → 完成统计。
 */
import { computed, onMounted, ref } from "vue";

import Btn from "@/components/ui/Btn.vue";
import Card from "@/components/ui/Card.vue";
import Icon from "@/components/ui/Icon.vue";
import Pill from "@/components/ui/Pill.vue";
import ProgressBar from "@/components/ui/ProgressBar.vue";
import Spinner from "@/components/ui/Spinner.vue";
import FormSelect from "@/components/forms/FormSelect.vue";

import { useBatch } from "@/stores/batch";
import { useSidecar } from "@/stores/sidecar";
import { useSidecarReady } from "@/composables/useSidecarReady";
import { useToast } from "@/composables/useToast";

const batch = useBatch();
const sidecar = useSidecar();
const toast = useToast();
const { whenReady } = useSidecarReady();

const draft = ref("");
const templates = ref<Array<{ id: string; name: string }>>([]);
const skills = ref<Array<{ id: string; name: string }>>([]);

async function loadLookups() {
  try {
    const [t, s] = await Promise.all([
      sidecar.client.get("/api/templates"),
      sidecar.client.get("/api/skills"),
    ]);
    templates.value = t.data.templates ?? [];
    skills.value = s.data.skills ?? [];
    if (!batch.templateId && templates.value[0]) {
      batch.templateId = templates.value[0].id;
    }
  } catch (e: any) {
    toast.error(`加载失败：${e?.message ?? e}`);
  }
}

const templateOptions = computed(() => [
  { label: "选择模板…", value: "" },
  ...templates.value.map((t) => ({ label: `${t.name} (${t.id})`, value: t.id })),
]);
const skillOptions = computed(() => [
  { label: "无（用模板默认）", value: "" },
  ...skills.value.map((s) => ({ label: s.name, value: s.id })),
]);

function parseKeywords(text: string): string[] {
  return text
    .split(/\r?\n/)
    .map((s) => s.trim())
    .filter(Boolean);
}

const parsedKeywords = computed(() => parseKeywords(draft.value));

async function start() {
  const kws = parsedKeywords.value;
  if (kws.length === 0) {
    toast.warn("请至少输入 1 个关键词（每行一个）");
    return;
  }
  if (!batch.templateId) {
    toast.warn("请选择模板");
    return;
  }
  await batch.submit(kws);
}

async function cancel() {
  await batch.cancel();
  toast.info("已请求取消，运行中的任务会跑完当前一篇。");
}

const STATUS_TONE: Record<string, "ok" | "warn" | "alert" | "info" | "primary"> = {
  queued: "info",
  running: "primary",
  success: "ok",
  failed: "alert",
  cancelled: "warn",
};

const STATUS_LABEL: Record<string, string> = {
  queued: "排队",
  running: "运行中",
  success: "完成",
  failed: "失败",
  cancelled: "已取消",
};

onMounted(async () => {
  try {
    await whenReady();
    await loadLookups();
  } catch {
    /* sidecar bootstrap failure already toasted */
  }
});
</script>

<template>
  <div class="flex flex-col gap-d">
    <Card>
      <div class="font-display text-[16px] font-semibold">批量生成</div>
      <div class="mt-1 text-[12.5px] text-ink-3">
        每行一个关键词。提交后会按顺序生成，写入 out_dir/batch-XXXXXXXX/ 子目录。
      </div>

      <div class="mt-4 grid grid-cols-1 gap-3 lg:grid-cols-[1fr_280px]">
        <textarea
          v-model="draft"
          placeholder="无线吸尘器选购指南&#10;扫地机器人哪家强&#10;空气炸锅哪个值得买"
          class="font-mono bg-card-2 w-full px-3 py-2 text-[12.5px] outline-none focus:bg-card-white"
          :style="{ minHeight: '180px', borderRadius: 'var(--radius-inner)', border: '1px solid var(--line)' }"
          :disabled="batch.isRunning"
        />
        <div class="flex flex-col gap-2 text-[12.5px]">
          <div>
            <div class="text-ink-3 mb-1">模板</div>
            <FormSelect
              :model-value="batch.templateId"
              :options="templateOptions"
              :disabled="batch.isRunning"
              @update:model-value="(v) => (batch.templateId = String(v))"
            />
          </div>
          <div>
            <div class="text-ink-3 mb-1">Skill</div>
            <FormSelect
              :model-value="batch.skillId"
              :options="skillOptions"
              :disabled="batch.isRunning"
              @update:model-value="(v) => (batch.skillId = String(v))"
            />
          </div>
          <div class="text-ink-3 mt-2">
            待提交：
            <span class="font-mono text-ink tabular-nums">{{ parsedKeywords.length }}</span> 条
          </div>
        </div>
      </div>

      <div class="mt-4 flex items-center justify-between">
        <div class="flex-1">
          <ProgressBar v-if="batch.isRunning || batch.status === 'cancelled'" :value="batch.progress" />
          <span v-else class="text-ink-3 text-[12px]">就绪</span>
        </div>
        <div class="ml-3 flex shrink-0 gap-2">
          <Btn
            v-if="!batch.isRunning"
            variant="solid"
            :disabled="parsedKeywords.length === 0 || !batch.templateId"
            @click="start"
          >
            起飞 {{ parsedKeywords.length || "" }} 篇
          </Btn>
          <Btn v-else variant="dark" small @click="cancel">
            <Icon name="x" :size="13" />
            <span>取消</span>
          </Btn>
        </div>
      </div>
    </Card>

    <Card v-if="batch.items.length > 0">
      <div class="mb-3 flex items-center justify-between">
        <div class="font-display text-[14px] font-semibold">队列</div>
        <div class="flex items-center gap-2">
          <Pill v-if="batch.status === 'done'" tone="ok">已完成</Pill>
          <Pill v-if="batch.status === 'cancelled'" tone="warn">已取消</Pill>
          <Pill v-if="batch.status === 'error'" tone="alert">失败</Pill>
          <Spinner v-if="batch.isRunning" :size="14" />
        </div>
      </div>

      <table class="w-full text-[12.5px]">
        <thead class="text-ink-3 text-left text-[11.5px]">
          <tr class="border-b border-line">
            <th class="py-2 font-medium">#</th>
            <th class="py-2 font-medium">关键词</th>
            <th class="py-2 font-medium">状态</th>
            <th class="py-2 text-right font-medium">耗时</th>
            <th class="py-2 text-right font-medium">文档</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="it in batch.items"
            :key="it.index"
            class="border-b border-line last:border-0"
          >
            <td class="font-mono text-ink-3 py-2 tabular-nums">{{ it.index }}</td>
            <td class="py-2">{{ it.keyword }}</td>
            <td class="py-2">
              <Pill :tone="STATUS_TONE[it.status] ?? 'info'">
                {{ STATUS_LABEL[it.status] ?? it.status }}
              </Pill>
            </td>
            <td class="font-mono py-2 text-right tabular-nums">
              {{ it.duration_seconds > 0 ? `${it.duration_seconds.toFixed(1)}s` : "—" }}
            </td>
            <td class="py-2 text-right">
              <span
                v-if="it.document"
                class="font-mono text-ink-3 text-[11px] truncate"
                :title="it.document"
              >
                {{ it.document.split(/[/\\]/).pop() }}
              </span>
              <span
                v-else-if="it.error_message"
                class="text-red text-[11px]"
                :title="it.error_message"
              >
                {{ it.error_type || "失败" }}
              </span>
              <span v-else class="text-ink-3">—</span>
            </td>
          </tr>
        </tbody>
      </table>
    </Card>

    <Card v-if="batch.status === 'done'">
      <div class="flex flex-wrap items-center gap-4 text-[12.5px]">
        <Pill tone="ok">完成</Pill>
        <span>共 <span class="font-mono">{{ batch.total }}</span> 篇</span>
        <span class="text-ink-3">|</span>
        <span>成功 <span class="font-mono">{{ batch.byStatus.success ?? 0 }}</span></span>
        <span>失败 <span class="font-mono">{{ batch.byStatus.failed ?? 0 }}</span></span>
        <span v-if="batch.byStatus.cancelled">取消 <span class="font-mono">{{ batch.byStatus.cancelled }}</span></span>
        <span class="text-ink-3">|</span>
        <span>总耗时 <span class="font-mono">{{ batch.totalDuration.toFixed(1) }}s</span></span>
      </div>
      <div v-if="batch.outDir" class="font-mono text-ink-3 mt-3 text-[11px]">
        out_dir: {{ batch.outDir }}
      </div>
    </Card>
  </div>
</template>
