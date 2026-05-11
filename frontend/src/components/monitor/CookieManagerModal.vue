<script setup lang="ts">
/**
 * Cookie pool manager — list + add + delete entries per platform.
 * Sidecar never exposes ``cookies_text`` once stored, so we offer no
 * "view raw" affordance — only label + status + delete.
 */
import { onMounted, ref, watch } from "vue";

import Btn from "@/components/ui/Btn.vue";
import Icon from "@/components/ui/Icon.vue";
import Pill from "@/components/ui/Pill.vue";
import Spinner from "@/components/ui/Spinner.vue";
import FormField from "@/components/forms/FormField.vue";
import FormInput from "@/components/forms/FormInput.vue";
import FormSelect from "@/components/forms/FormSelect.vue";

import { useSidecar } from "@/stores/sidecar";
import { useToast } from "@/composables/useToast";
import { confirmDialog } from "@/composables/useConfirm";

const props = defineProps<{
  open: boolean;
  defaultPlatform?: string;
}>();
const emit = defineEmits<{
  (e: "update:open", v: boolean): void;
  (e: "changed"): void;
}>();

const sidecar = useSidecar();
const toast = useToast();

const PLATFORMS = [
  { value: "zhihu_question", label: "知乎" },
  { value: "bilibili_comment", label: "B 站" },
  { value: "douyin_comment", label: "抖音" },
  { value: "kuaishou_comment", label: "快手" },
];

const platform = ref<string>("zhihu_question");

interface Cookie {
  id: number;
  platform: string;
  label: string;
  enabled: boolean;
  fail_count: number;
  last_used_at: string | null;
}
const cookies = ref<Cookie[]>([]);
const loading = ref(false);

// Add-form fields
const newLabel = ref("");
const newCookies = ref("");
const newUserAgent = ref("");
const adding = ref(false);

async function loadCookies() {
  loading.value = true;
  try {
    const r = await sidecar.client.get("/api/monitor/cookies", {
      params: { platform: platform.value },
    });
    cookies.value = r.data.cookies ?? [];
  } catch (e: any) {
    cookies.value = [];
    if (e?.response?.status !== 503) {
      toast.error(`加载失败：${e?.message ?? e}`);
    }
  } finally {
    loading.value = false;
  }
}

async function addCookie() {
  if (!newCookies.value.trim()) {
    toast.warn("Cookie 文本不能为空");
    return;
  }
  adding.value = true;
  try {
    await sidecar.client.post(`/api/monitor/cookies/${platform.value}`, {
      cookies_text: newCookies.value.trim(),
      label: newLabel.value.trim(),
      user_agent: newUserAgent.value.trim(),
    });
    toast.success("Cookie 已添加");
    newLabel.value = "";
    newCookies.value = "";
    newUserAgent.value = "";
    await loadCookies();
    emit("changed");
  } catch (e: any) {
    toast.error(`添加失败：${e?.response?.data?.detail ?? e?.message ?? e}`);
  } finally {
    adding.value = false;
  }
}

async function deleteCookie(id: number) {
  if (!(await confirmDialog("删除这条 cookie？", { title: "删除 Cookie" }))) return;
  try {
    await sidecar.client.delete(`/api/monitor/cookies/${id}`);
    await loadCookies();
    emit("changed");
  } catch (e: any) {
    toast.error(`删除失败：${e?.message ?? e}`);
  }
}

function close() {
  emit("update:open", false);
}

watch(platform, () => loadCookies());
watch(
  () => props.open,
  (v) => {
    if (v) {
      if (props.defaultPlatform) platform.value = props.defaultPlatform;
      loadCookies();
    }
  },
);

onMounted(() => {
  if (props.open) loadCookies();
});
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
        :style="{ width: '560px', maxWidth: '92vw', borderRadius: 'var(--radius-card)' }"
      >
        <div class="mb-4 flex items-center justify-between">
          <div class="font-display text-[16px] font-semibold">Cookie 池管理</div>
          <button type="button" @click="close">
            <Icon name="x" :size="18" />
          </button>
        </div>

        <FormField label="平台" inline>
          <FormSelect
            :model-value="platform"
            :options="PLATFORMS"
            @update:model-value="(v) => (platform = String(v))"
          />
        </FormField>

        <!-- Existing cookies -->
        <div class="mt-4">
          <div class="font-display text-[13px] font-semibold mb-2">已存 Cookie</div>
          <Spinner v-if="loading" :size="14" />
          <div v-else-if="!cookies.length" class="text-[12.5px] text-ink-3">
            还没有 Cookie。在下方添加。
          </div>
          <ul v-else class="flex flex-col gap-2">
            <li
              v-for="c in cookies"
              :key="c.id"
              class="bg-card-2 flex items-center gap-2 px-3 py-2 text-[12.5px]"
              :style="{ borderRadius: 'var(--radius-inner)', border: '1px solid var(--line)' }"
            >
              <div class="min-w-0 flex-1">
                <div class="font-medium truncate">{{ c.label || `#${c.id}` }}</div>
                <div class="font-mono text-ink-3 mt-0.5 text-[11px]">
                  失败 {{ c.fail_count }} 次 · 最近
                  {{ c.last_used_at ? new Date(c.last_used_at).toLocaleString() : "未使用" }}
                </div>
              </div>
              <Pill v-if="c.enabled" tone="ok">启用</Pill>
              <Pill v-else>禁用</Pill>
              <button
                type="button"
                class="text-ink-3 hover:text-red"
                title="删除"
                @click="deleteCookie(c.id)"
              >
                <Icon name="trash" :size="13" />
              </button>
            </li>
          </ul>
        </div>

        <!-- Add form -->
        <div class="mt-6">
          <div class="font-display text-[13px] font-semibold mb-2">添加 Cookie</div>
          <div class="flex flex-col gap-3">
            <FormField label="标签（可选）" hint="给这条 cookie 起个名字（如『主账号』）。">
              <FormInput v-model="newLabel" placeholder="主账号" debounce="live" />
            </FormField>
            <FormField label="Cookie 文本" hint="完整的 Cookie 串（浏览器开发者工具复制）。">
              <textarea
                v-model="newCookies"
                placeholder="z_c0=...; q_c1=...; _zap=..."
                class="font-mono bg-card-2 w-full px-3 py-2 text-[11.5px] outline-none focus:bg-card-white"
                :style="{
                  minHeight: '80px',
                  borderRadius: 'var(--radius-inner)',
                  border: '1px solid var(--line)',
                }"
              />
            </FormField>
            <FormField label="User-Agent（可选）">
              <FormInput
                v-model="newUserAgent"
                placeholder="Mozilla/5.0 (Windows NT 10.0; Win64; x64) ..."
                debounce="live"
              />
            </FormField>
          </div>
          <div class="mt-3 flex justify-end gap-2">
            <Btn variant="solid" small :disabled="adding" @click="addCookie">
              <Spinner v-if="adding" :size="12" />
              <span>{{ adding ? "添加中…" : "添加" }}</span>
            </Btn>
          </div>
        </div>
      </div>
    </div>
  </Teleport>
</template>
