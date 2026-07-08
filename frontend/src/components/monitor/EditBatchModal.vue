<script setup lang="ts">
/**
 * 批量编辑监测批次 —— 评论 tab 的 L1 行是「批次」（同前缀的 N 条 task），
 * 单个 AddTaskModal 改不动整批共享的字段。这里提供:
 *   - 重命名批次：把所有子 task 的 name 从 `${oldName} - {tail}` 改成
 *     `${newName} - {tail}`，保留各自的 URL 尾段
 *   - 改 top_n：广播到批次内每条 task.config.top_n（"理想排名上限"）
 *
 * 不改 my_comment_text / target_url —— 这两个一定是 per-task 的（不同视频
 * 下我自己发的评论不一样），批量改会覆盖用户原始数据。target_brand 也
 * 不在这里 —— 评论匹配走 my_comment_text 相似度，跟品牌词无关。
 */
import { ref, watch } from "vue";

import Btn from "@/components/ui/Btn.vue";
import Dialog from "@/components/ui/Dialog.vue";
import Spinner from "@/components/ui/Spinner.vue";
import FormField from "@/components/forms/FormField.vue";
import FormInput from "@/components/forms/FormInput.vue";

import { useSidecar } from "@/stores/sidecar";
import { useToast } from "@/composables/useToast";

interface BatchTask {
  id: number;
  type: string;
  name: string;
  target_url: string;
  config: Record<string, any>;
  schedule_cron: string;
  enabled: boolean;
}

const props = defineProps<{
  open: boolean;
  batchName: string;
  tasks: BatchTask[];
}>();
const emit = defineEmits<{
  (e: "update:open", v: boolean): void;
  (e: "updated", batchName: string): void;
}>();

const sidecar = useSidecar();
const toast = useToast();

const newName = ref("");
const newTopN = ref(5);
const submitting = ref(false);

watch(
  () => props.open,
  (v) => {
    if (!v) return;
    // 反填：批次名 + 取第一条 task 的 config 当默认（批次内一般一致）。
    newName.value = props.batchName;
    const first = props.tasks[0]?.config ?? {};
    newTopN.value = Number(first.top_n) || 5;
  },
  { immediate: true },
);

function close() {
  if (submitting.value) return;
  emit("update:open", false);
}

function parseSuffix(taskName: string, oldBatch: string): string {
  // 从 task.name 切出"- {tail}"那一段；如果 task.name 就是批次名，
  // 表示这是单条任务（不是批量导入的），新名直接用 newName。
  if (taskName === oldBatch) return "";
  if (taskName.startsWith(oldBatch + " - ")) {
    return taskName.slice(oldBatch.length); // 包含" - tail"
  }
  // 兜底：任务名格式不规范，留原名（用 newName 替换前缀的尝试可能误伤）
  return "";
}

async function submit() {
  const target = newName.value.trim();
  if (!target) {
    toast.warn("批次名不能为空");
    return;
  }
  if (newTopN.value < 1 || newTopN.value > 100) {
    toast.warn("Top-N 应在 1–100 之间");
    return;
  }
  submitting.value = true;
  const failures: string[] = [];
  for (const t of props.tasks) {
    const suffix = parseSuffix(t.name, props.batchName);
    const renamed = suffix ? `${target}${suffix}` : target;
    const cfg = {
      ...t.config,
      top_n: newTopN.value,
    };
    // 评论批次不维护 target_brand —— 把旧值（如果之前误存了）顺手剔掉，
    // 保持 task.config 干净，UI 上以后也不再展示这个字段。
    if ("target_brand" in cfg) delete cfg.target_brand;
    try {
      await sidecar.client.patch(`/api/monitor/tasks/${t.id}`, {
        type: t.type,
        name: renamed,
        target_url: t.target_url,
        config: cfg,
        schedule_cron: t.schedule_cron,
        enabled: t.enabled,
      });
    } catch (e: any) {
      const detail = e?.response?.data?.detail ?? e?.message ?? e;
      failures.push(`#${t.id}: ${typeof detail === "string" ? detail : JSON.stringify(detail)}`);
    }
  }
  submitting.value = false;
  if (failures.length === 0) {
    toast.success(`已更新 ${props.tasks.length} 条任务`);
    emit("updated", target);
    close();
  } else {
    toast.warn(`完成 ${props.tasks.length - failures.length} / ${props.tasks.length}，失败 ${failures.length}`);
    console.warn("[batch edit failures]", failures);
  }
}
</script>

<template>
  <Dialog
    :open="open"
    title="编辑批次"
    show-close
    :closable="!submitting"
    @update:open="close"
  >
    <div class="mb-4 text-[11.5px]" :style="{ color: 'var(--ink-3)' }">
      批次内 {{ tasks.length }} 条任务会同步更新（每条视频的 URL / 评论原文不动）
    </div>

    <div class="flex flex-col gap-4">
      <FormField
        label="批次名"
        hint="子任务的名字会自动变成 `批次名 - 视频 ID 尾段`"
      >
        <FormInput v-model="newName" placeholder="如：戴森评论监测" debounce="live" />
      </FormField>

      <FormField
        label="理想排名（前 N 位）"
        hint="希望评论出现在前几位，默认 5。后台会扫描评论区靠前的一批热评，排到检索范围之外才算「丢失」。"
        inline
      >
        <FormInput
          type="number"
          :model-value="newTopN"
          :width="100"
          @commit="(v) => (newTopN = Number(v) || 5)"
        />
      </FormField>
    </div>

    <template #footer>
      <Btn variant="ghost" small @click="close">取消</Btn>
      <Btn variant="solid" small :disabled="submitting" @click="submit">
        <Spinner v-if="submitting" :size="12" />
        <span>{{ submitting ? "保存中…" : `保存（${tasks.length} 条）` }}</span>
      </Btn>
    </template>
  </Dialog>
</template>
