<script setup lang="ts">
/**
 * Cookie pool manager — list + add + delete entries per platform.
 * Sidecar never exposes ``cookies_text`` once stored, so we offer no
 * "view raw" affordance — only label + status + delete.
 */
import { onMounted, onUnmounted, ref, watch } from "vue";

import Btn from "@/components/ui/Btn.vue";
import Dialog from "@/components/ui/Dialog.vue";
import Icon from "@/components/ui/Icon.vue";
import Pill from "@/components/ui/Pill.vue";
import Spinner from "@/components/ui/Spinner.vue";
import FormField from "@/components/forms/FormField.vue";
import FormInput from "@/components/forms/FormInput.vue";
import FormSelect from "@/components/forms/FormSelect.vue";

import { useSidecar } from "@/stores/sidecar";
import { useToast } from "@/composables/useToast";
import { confirmDialog } from "@/composables/useConfirm";
import { useStaleGuard } from "@/composables/useStaleGuard";

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
  // 后端 _safe_cred 派生字段（v2 schema 之后）：
  cooldown_until: number; // unix 秒；0 = 不在冷却
  cooldown_seconds_remaining: number; // 后端算好的 max(0, cooldown_until - now)
  status: "ok" | "cooldown" | "stale" | "disabled";
  auto_disable_threshold: number;
}
const cookies = ref<Cookie[]>([]);
const loading = ref(false);

// 冷却倒计时刷新 —— 后端只在 loadCookies() 时返回一次 remaining 秒数，
// 这里在前端按秒往下扣，每 1s 触发响应式更新，避免 UI 显示成「冷却中
// 还剩 600s」一直不动。tick 用 ref 不用真减 cookies 数据，保留后端
// 的权威值；显示侧用 computed 用 tick 重算 remaining。
const nowTick = ref(Math.floor(Date.now() / 1000));
let tickTimer: number | null = null;
function startTick() {
  if (tickTimer !== null) return;
  tickTimer = window.setInterval(() => {
    nowTick.value = Math.floor(Date.now() / 1000);
  }, 1000);
}
function stopTick() {
  if (tickTimer !== null) {
    clearInterval(tickTimer);
    tickTimer = null;
  }
}

function liveCooldownRemaining(c: Cookie): number {
  if (!c.cooldown_until) return 0;
  return Math.max(0, c.cooldown_until - nowTick.value);
}
function formatCooldown(seconds: number): string {
  if (seconds <= 0) return "";
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  if (m === 0) return `${s}s`;
  return `${m}m ${s.toString().padStart(2, "0")}s`;
}

// 显示用 status 跟着 nowTick 实时更新 —— 冷却到 0s 那一刻不再显示
// "冷却中" 状态。后端的 status 是请求时刻的快照；前端在自然到期时
// 自动把 UI 推回 ok（实际下次 loadCookies 时后端也会确认）。
function liveStatus(c: Cookie): Cookie["status"] {
  if (!c.enabled) return "disabled";
  if (liveCooldownRemaining(c) > 0) return "cooldown";
  if (c.fail_count >= 3) return "stale";
  return "ok";
}

// Pill 组件支持的 tone：ok | warn | alert | primary | info。
// 这里把语义状态映射到 Pill 的视觉色阶。
const statusMeta: Record<Cookie["status"], { label: string; tone: "ok" | "warn" | "alert" | "info"; hint: string }> = {
  ok: { label: "正常", tone: "ok", hint: "" },
  cooldown: { label: "冷却中", tone: "warn", hint: "近期失败过，暂停一段时间后自动恢复" },
  stale: { label: "可能失效", tone: "alert", hint: "已连续多次失败 — 建议用「内置浏览器登录」重抓 cookie" },
  disabled: { label: "已禁用", tone: "info", hint: "失败次数过多自动禁用 — 请删除后重抓" },
};

// Add-form fields
const newLabel = ref("");
const newCookies = ref("");
const newUserAgent = ref("");
const adding = ref(false);

// 内置浏览器登录捕获 —— 一次请求阻塞最长 5 分钟（用户登录窗口），
// 期间这里 ref 控制按钮 disabled 状态 + 进度提示。
const captureLoading = ref(false);
const captureLabel = ref("");

async function captureViaLogin() {
  if (captureLoading.value) return;
  captureLoading.value = true;
  const platformLabel = PLATFORMS.find((p) => p.value === platform.value)?.label ?? platform.value;
  toast.info(`已打开 ${platformLabel} 登录窗口，请在弹出的浏览器中完成登录（最多 5 分钟）…`);
  try {
    const r = await sidecar.client.post(
      `/api/monitor/cookies/${platform.value}/login`,
      { label: captureLabel.value.trim(), timeout_s: 300 },
      // axios 默认 timeout 是 sidecar.client 配的（通常 30s），
      // 这里手动放大到 6 分钟 —— 后端最多等 5 分钟，留 1 分钟余量。
      { timeout: 360_000 },
    );
    const data = r.data ?? {};
    if (data.success) {
      toast.success(`登录成功，已保存 ${data.cookie_count} 条 cookie`);
      captureLabel.value = "";
      await loadCookies();
      emit("changed");
    } else {
      const reason =
        data.error === "timeout"
          ? "登录超时（5 分钟内未完成）"
          : data.error === "window_closed_by_user"
            ? "浏览器窗口被关闭"
            : `失败：${data.error || "未知原因"}`;
      toast.warn(reason);
    }
  } catch (e: any) {
    const status = e?.response?.status;
    const detail = e?.response?.data?.detail;
    // 503 covers a few distinct setup failures — show the backend's
    // detail string verbatim so the user sees the actual fix (rebuild
    // sidecar / install chromium / etc.) instead of one stock hint.
    if (status === 503) {
      toast.error(`登录服务不可用：${detail ?? "patchright 未安装或 sidecar 缺少 driver"}`);
    } else if (status === 500) {
      toast.error(`登录失败（服务端异常）：${detail ?? e?.message ?? "未知错误"}`);
    } else if (!e?.response) {
      // No response at all → genuine transport-level failure. Distinguish
      // from server-returned errors so user knows where to look.
      toast.error(`网络中断：${e?.message ?? e} — 请查看 sidecar.log`);
    } else {
      toast.error(`登录失败：${detail ?? e?.message ?? e}`);
    }
  } finally {
    captureLoading.value = false;
  }
}

// Guard against rapid platform switches: `watch(platform, loadCookies)`
// fires a fresh load on every change, but the older response could
// resolve last and overwrite the newer platform's cookie list.
const loadGuard = useStaleGuard();

async function loadCookies() {
  const my = loadGuard.issue();
  loading.value = true;
  try {
    const r = await sidecar.client.get("/api/monitor/cookies", {
      params: { platform: platform.value },
    });
    if (loadGuard.isStale(my)) return;
    cookies.value = r.data.cookies ?? [];
  } catch (e: any) {
    if (loadGuard.isStale(my)) return;
    cookies.value = [];
    if (e?.response?.status !== 503) {
      toast.error(`加载失败：${e?.message ?? e}`);
    }
  } finally {
    // Only the most recent load owns the loading indicator. A stale
    // response setting it false here would prematurely hide the spinner
    // for the in-flight call.
    if (!loadGuard.isStale(my)) {
      loading.value = false;
    }
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
      startTick();
    } else {
      stopTick();
    }
  },
);

onMounted(() => {
  if (props.open) {
    loadCookies();
    startTick();
  }
});
onUnmounted(() => stopTick());
</script>

<template>
  <Dialog
    :open="open"
    size="lg"
    title="Cookie 池管理"
    show-close
    @update:open="close"
  >
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
              :style="{
                borderRadius: 'var(--radius-inner)',
                border: '1px solid var(--line)',
                // 失效 / 冷却 cookie 加左边色条提示，比纯 pill 更显眼
                borderLeft:
                  liveStatus(c) === 'stale' || liveStatus(c) === 'disabled'
                    ? '3px solid var(--red, #d33)'
                    : liveStatus(c) === 'cooldown'
                      ? '3px solid var(--amber, #d39e00)'
                      : '1px solid var(--line)',
              }"
            >
              <div class="min-w-0 flex-1">
                <div class="font-medium truncate">{{ c.label || `#${c.id}` }}</div>
                <div class="font-mono text-ink-3 mt-0.5 text-[11px]">
                  失败 {{ c.fail_count }} / {{ c.auto_disable_threshold }} 次 · 最近
                  {{ c.last_used_at ? new Date(c.last_used_at).toLocaleString() : "未使用" }}
                  <span v-if="liveStatus(c) === 'cooldown'" class="ml-2">
                    · 冷却剩余 {{ formatCooldown(liveCooldownRemaining(c)) }}
                  </span>
                </div>
                <div
                  v-if="statusMeta[liveStatus(c)].hint"
                  class="text-[10.5px] mt-0.5"
                  :style="{
                    color:
                      statusMeta[liveStatus(c)].tone === 'alert'
                        ? 'var(--red, #d33)'
                        : 'var(--ink-3)',
                  }"
                >
                  {{ statusMeta[liveStatus(c)].hint }}
                </div>
              </div>
              <Pill :tone="statusMeta[liveStatus(c)].tone">
                {{ statusMeta[liveStatus(c)].label }}
              </Pill>
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

        <!-- 内置浏览器登录 —— 推荐路径，跳过手动粘贴 -->
        <div
          class="mt-6 bg-card-2 p-4"
          :style="{ borderRadius: 'var(--radius-inner)', border: '1px solid var(--line)' }"
        >
          <div class="font-display text-[13px] font-semibold mb-1">
            <Icon name="zap" :size="13" /> 内置浏览器登录（推荐）
          </div>
          <div class="text-[11.5px] text-ink-3 mb-3 leading-relaxed">
            自动打开一个浏览器窗口让你手动登录所选平台 ——
            登录成功后 cookie 由这个浏览器签发，指纹一致，
            <strong>抓取通过率比手动复制粘贴高得多</strong>。
          </div>
          <div class="flex items-center gap-2">
            <FormInput
              v-model="captureLabel"
              placeholder="给这个账号起个名字（如『号-1』）"
              debounce="live"
              :disabled="captureLoading"
              class="flex-1"
            />
            <Btn variant="solid" small :disabled="captureLoading" @click="captureViaLogin">
              <Spinner v-if="captureLoading" :size="12" />
              <Icon v-else name="external-link" :size="13" />
              <span>{{ captureLoading ? "登录中…" : "打开登录窗口" }}</span>
            </Btn>
          </div>
          <div v-if="captureLoading" class="text-[11.5px] text-ink-3 mt-2">
            ⚠️ 浏览器窗口已弹出，请完成登录。窗口会自动关闭。
          </div>
        </div>

        <!-- Add form -->
        <div class="mt-6">
          <div class="font-display text-[13px] font-semibold mb-2">手动粘贴 Cookie（备用）</div>
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
  </Dialog>
</template>
