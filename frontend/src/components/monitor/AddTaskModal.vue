<script setup lang="ts">
/**
 * Monitor Add-Task modal — POST /api/monitor/tasks.
 *
 * Per-platform body shape (per csm_core.monitor.base.MonitorTask.config):
 *   zhihu_question     → { target_brand: str, top_n: int }
 *   *_comment          → { my_comment_text: str, top_n: int }
 *
 * Schedule format follows csm_core/monitor/scheduler.py: "manual" or
 * "HH:MM" (daily). Anything else is rejected by the parser.
 */
import { computed, ref, watch } from "vue";

import Btn from "@/components/ui/Btn.vue";
import Icon from "@/components/ui/Icon.vue";
import Spinner from "@/components/ui/Spinner.vue";
import FormField from "@/components/forms/FormField.vue";
import FormInput from "@/components/forms/FormInput.vue";
import FormSelect from "@/components/forms/FormSelect.vue";
import FormToggle from "@/components/forms/FormToggle.vue";

import { useSidecar } from "@/stores/sidecar";
import { useToast } from "@/composables/useToast";

const props = defineProps<{
  open: boolean;
  /** Pre-select platform when caller knows it. */
  defaultType?: "zhihu_question" | "bilibili_comment" | "douyin_comment" | "kuaishou_comment";
}>();
const emit = defineEmits<{
  (e: "update:open", v: boolean): void;
  (e: "created", taskId: number): void;
}>();

const sidecar = useSidecar();
const toast = useToast();

const TYPES = [
  { value: "zhihu_question", label: "知乎问题（排名监测）" },
  { value: "bilibili_comment", label: "B 站评论留存" },
  { value: "douyin_comment", label: "抖音评论留存" },
  { value: "kuaishou_comment", label: "快手评论留存" },
] as const;

const type = ref<(typeof TYPES)[number]["value"]>("zhihu_question");
const name = ref("");
const targetUrl = ref("");
// Zhihu-specific
const targetBrand = ref("");
// Comment-specific
const myCommentText = ref("");
// Shared
const topN = ref(5);
// Schedule
const scheduleMode = ref<"manual" | "daily">("manual");
const dailyTime = ref("09:00");
const enabled = ref(true);

const submitting = ref(false);

const isComment = computed(() => type.value !== "zhihu_question");

function close() {
  emit("update:open", false);
  // Reset for next open.
  name.value = "";
  targetUrl.value = "";
  targetBrand.value = "";
  myCommentText.value = "";
  topN.value = 5;
  scheduleMode.value = "manual";
  dailyTime.value = "09:00";
  enabled.value = true;
  submitting.value = false;
}

watch(
  () => props.open,
  (v) => {
    if (v && props.defaultType) type.value = props.defaultType;
  },
);

function validate(): string | null {
  if (!name.value.trim()) return "任务名不能为空";
  if (!targetUrl.value.trim()) return "目标 URL 不能为空";
  if (isComment.value && !myCommentText.value.trim()) {
    return "评论留存监测必须填写自己发布的评论文本";
  }
  if (!isComment.value && !targetBrand.value.trim()) {
    return "知乎监测必须填写目标品牌关键词";
  }
  if (topN.value < 1 || topN.value > 100) return "Top-N 阈值应在 1–100 之间";
  if (scheduleMode.value === "daily" && !/^\d{1,2}:\d{2}$/.test(dailyTime.value)) {
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
    const body = {
      type: type.value,
      name: name.value.trim(),
      target_url: targetUrl.value.trim(),
      config: isComment.value
        ? { my_comment_text: myCommentText.value.trim(), top_n: topN.value }
        : { target_brand: targetBrand.value.trim(), top_n: topN.value },
      schedule_cron:
        scheduleMode.value === "manual" ? "manual" : dailyTime.value,
      enabled: enabled.value,
    };
    const r = await sidecar.client.post("/api/monitor/tasks", body);
    toast.success(`任务已添加（#${r.data.id}）`);
    emit("created", r.data.id);
    close();
  } catch (e: any) {
    const detail = e?.response?.data?.detail ?? e?.message ?? e;
    toast.error(`创建失败：${typeof detail === "string" ? detail : JSON.stringify(detail)}`);
  } finally {
    submitting.value = false;
  }
}
</script>

<template>
  <Teleport to="body">
    <div
      v-if="open"
      class="fixed inset-0 z-40 flex items-center justify-center bg-black/30"
      @click.self="close"
    >
      <div
        class="anim-up bg-bg-inner max-h-[90vh] overflow-y-auto p-6"
        :style="{ width: '480px', maxWidth: '92vw', borderRadius: 'var(--radius-card)' }"
      >
        <div class="mb-4 flex items-center justify-between">
          <div class="font-display text-[16px] font-semibold">新增监测任务</div>
          <button type="button" @click="close">
            <Icon name="x" :size="18" />
          </button>
        </div>

        <div class="flex flex-col gap-4">
          <FormField label="平台">
            <FormSelect
              :model-value="type"
              :options="TYPES.map((t) => ({ label: t.label, value: t.value }))"
              @update:model-value="(v) => (type = v as any)"
            />
          </FormField>

          <FormField
            :label="isComment ? '任务名' : '问题名字'"
            :hint="isComment ? '出现在监测列表里。' : '抓取到的知乎问题标题，会显示在监测任务列表的第一列。'"
          >
            <FormInput
              v-model="name"
              :placeholder="isComment ? '如：客厅投影实测视频留存' : '如：无线吸尘器哪款好用'"
              debounce="live"
            />
          </FormField>

          <FormField
            label="目标 URL"
            :hint="
              isComment
                ? '视频 / 笔记的完整 URL'
                : '知乎问题的完整 URL（如 https://www.zhihu.com/question/12345）'
            "
          >
            <FormInput v-model="targetUrl" placeholder="https://..." debounce="live" />
          </FormField>

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

          <FormField
            v-else
            label="目标品牌关键词"
            hint="在知乎答案排序里要追的品牌关键词。"
          >
            <FormInput
              v-model="targetBrand"
              placeholder="如：戴森"
              debounce="live"
            />
          </FormField>

          <FormField
            label="Top-N 阈值"
            hint="跌出 Top-N 时触发告警；评论场景表示要追踪的最热评论数。"
            inline
          >
            <FormInput
              type="number"
              :model-value="topN"
              :width="100"
              @commit="(v) => (topN = Number(v) || 5)"
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
            </div>
          </FormField>

          <FormField label="启用" inline>
            <FormToggle v-model="enabled" />
          </FormField>
        </div>

        <div class="mt-6 flex justify-end gap-2">
          <Btn variant="ghost" small @click="close">取消</Btn>
          <Btn variant="solid" small :disabled="submitting" @click="submit">
            <Spinner v-if="submitting" :size="12" />
            <span>{{ submitting ? "提交中…" : "添加任务" }}</span>
          </Btn>
        </div>
      </div>
    </div>
  </Teleport>
</template>
