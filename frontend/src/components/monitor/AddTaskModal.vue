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

type TaskType = "zhihu_question" | "bilibili_comment" | "douyin_comment" | "kuaishou_comment";

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
  { value: "bilibili_comment", label: "B 站评论留存" },
  { value: "douyin_comment", label: "抖音评论留存" },
  { value: "kuaishou_comment", label: "快手评论留存" },
] as const;

const type = ref<TaskType>("zhihu_question");
const name = ref("");
const targetUrl = ref("");
// Zhihu-specific
const targetBrand = ref("");
// Comment-specific
const myCommentText = ref("");
// Shared —— 默认 5；watch(type) 时知乎切到 10（zhihu_question 的合理起点）
const topN = ref(5);
// Schedule
const scheduleMode = ref<"manual" | "daily">("manual");
const dailyTime = ref("09:00");
const enabled = ref(true);

const submitting = ref(false);

const isComment = computed(() => type.value !== "zhihu_question");
const isEdit = computed(() => !!props.editingTask);

function close() {
  emit("update:open", false);
  // Reset for next open. topN 默认值按平台：知乎 10 / 评论 5。
  name.value = "";
  targetUrl.value = "";
  targetBrand.value = "";
  myCommentText.value = "";
  topN.value = type.value === "zhihu_question" ? 10 : 5;
  scheduleMode.value = "manual";
  dailyTime.value = "09:00";
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
  if (t.schedule_cron === "manual" || !t.schedule_cron) {
    scheduleMode.value = "manual";
  } else if (/^\d{1,2}:\d{2}$/.test(t.schedule_cron)) {
    scheduleMode.value = "daily";
    dailyTime.value = t.schedule_cron;
  } else {
    // 其它 cron 形式 —— 后端目前只支持 manual / HH:MM，留作 manual 兜底
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

function validate(): string | null {
  if (!name.value.trim()) return "任务名不能为空";
  if (!targetUrl.value.trim()) return "目标 URL 不能为空";
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
    // 评论场景 config 只带 my_comment_text + top_n —— 用户决定不引入
    // 品牌词，避免无用字段误导（评论匹配走 `my_comment_text` 相似度，
    // 跟品牌词无关）。target_brand 仅知乎走，那条命令链路用得上。
    const config: Record<string, any> = isComment.value
      ? {
          my_comment_text: myCommentText.value.trim(),
          top_n: topN.value,
        }
      : { target_brand: targetBrand.value.trim(), top_n: topN.value };
    const body = {
      type: type.value,
      name: name.value.trim(),
      target_url: targetUrl.value.trim(),
      config,
      schedule_cron:
        scheduleMode.value === "manual" ? "manual" : dailyTime.value,
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
          <div class="font-display text-[16px] font-semibold">
            {{ isEdit ? "编辑监测任务" : "新增监测任务" }}
          </div>
          <button type="button" @click="close">
            <Icon name="x" :size="18" />
          </button>
        </div>

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
            v-if="!isComment"
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
            :label="isComment ? '理想排名（前 N 位）' : 'Top-N（监测前 N 条答案）'"
            :hint="
              isComment
                ? '希望评论出现在前几位，默认 5。后台始终扫描前 150 条 hot 评论 —— 即使评论排到第 30 位也能找到并显示真实位置，超过 150 才算「丢失」。'
                : '监测「默认排序」下前 N 条答案里包含品牌词的数量，默认 10。范围 1–40，超过 40 抓取慢、noise 多。'
            "
            inline
          >
            <FormInput
              type="number"
              :model-value="topN"
              :width="100"
              @commit="(v) => (topN = Number(v) || (isComment ? 5 : 10))"
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
            <span>
              {{
                submitting
                  ? (isEdit ? "保存中…" : "提交中…")
                  : (isEdit ? "保存修改" : "添加任务")
              }}
            </span>
          </Btn>
        </div>
      </div>
    </div>
  </Teleport>
</template>
