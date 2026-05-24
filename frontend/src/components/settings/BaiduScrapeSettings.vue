<script setup lang="ts">
/**
 * 百度抓取 — Native Chrome profile 配置
 *
 * 后端 API（Task 7 routes）：
 *   GET  /api/monitor/baidu/native-config
 *     → { use_native_chrome, chrome_executable_path, chrome_user_data_dir, chrome_profile_name }
 *   POST /api/monitor/baidu/native-config   Body = 上述同结构
 *   POST /api/monitor/baidu/detect-chrome
 *     → { executable_path, user_data_dir }
 *   POST /api/monitor/baidu/list-profiles   Body = { user_data_dir }
 *     → { profiles: [{ name, account_email }] }
 *   POST /api/monitor/baidu/test-native
 *     Body = { chrome_executable_path, chrome_user_data_dir, chrome_profile_name }
 *     → { ok, error? }
 */
import { ref, onMounted, watch } from "vue";

import Btn from "@/components/ui/Btn.vue";
import Icon from "@/components/ui/Icon.vue";
import Spinner from "@/components/ui/Spinner.vue";
import FormToggle from "@/components/forms/FormToggle.vue";
import FormInput from "@/components/forms/FormInput.vue";
import { useSidecar } from "@/stores/sidecar";
import { useToast } from "@/composables/useToast";

interface NativeConfig {
  use_native_chrome: boolean;
  chrome_executable_path: string | null;
  chrome_user_data_dir: string | null;
  chrome_profile_name: string;
}

interface ProfileInfo {
  name: string;
  account_email: string | null;
}

const sidecar = useSidecar();
const toast = useToast();

const config = ref<NativeConfig>({
  use_native_chrome: false,
  chrome_executable_path: null,
  chrome_user_data_dir: null,
  chrome_profile_name: "Default",
});
const profiles = ref<ProfileInfo[]>([]);
const testResult = ref<{ ok: boolean; error?: string } | null>(null);
const loading = ref(false);
const detectLoading = ref(false);
const testLoading = ref(false);
const saveLoading = ref(false);

async function loadConfig() {
  loading.value = true;
  try {
    const resp = await sidecar.client.get<NativeConfig>("/api/monitor/baidu/native-config");
    config.value = resp.data;
    if (config.value.chrome_user_data_dir) {
      await loadProfiles();
    }
  } catch (e: any) {
    const detail = e?.response?.data?.detail ?? e?.message ?? "未知错误";
    toast.error(`读取配置失败：${detail}`);
  } finally {
    loading.value = false;
  }
}

async function detectChrome() {
  detectLoading.value = true;
  try {
    const resp = await sidecar.client.post<{ executable_path: string | null; user_data_dir: string | null }>(
      "/api/monitor/baidu/detect-chrome",
    );
    const data = resp.data;
    config.value.chrome_executable_path = data.executable_path;
    config.value.chrome_user_data_dir = data.user_data_dir;
    if (data.user_data_dir) {
      await loadProfiles();
    }
    if (!data.executable_path) {
      toast.warn("未检测到 Chrome 安装，请手动填写路径或先安装 Chrome");
    } else {
      toast.success("已探测到 Chrome");
    }
  } catch (e: any) {
    const detail = e?.response?.data?.detail ?? e?.message ?? "未知错误";
    toast.error(`探测失败：${detail}`);
  } finally {
    detectLoading.value = false;
  }
}

async function loadProfiles() {
  if (!config.value.chrome_user_data_dir) {
    profiles.value = [];
    return;
  }
  try {
    const resp = await sidecar.client.post<{ profiles: ProfileInfo[] }>(
      "/api/monitor/baidu/list-profiles",
      { user_data_dir: config.value.chrome_user_data_dir },
    );
    profiles.value = resp.data.profiles ?? [];
    // 若当前 profile_name 不在列表内，默认切到第一个
    if (profiles.value.length > 0 && !profiles.value.some((p) => p.name === config.value.chrome_profile_name)) {
      config.value.chrome_profile_name = profiles.value[0].name;
    }
  } catch {
    // 静默失败：user_data_dir 可能还没生效
    profiles.value = [];
  }
}

async function testStartup() {
  if (!config.value.chrome_executable_path || !config.value.chrome_user_data_dir) return;
  testLoading.value = true;
  testResult.value = null;
  try {
    const resp = await sidecar.client.post<{ ok: boolean; error?: string }>(
      "/api/monitor/baidu/test-native",
      {
        chrome_executable_path: config.value.chrome_executable_path,
        chrome_user_data_dir: config.value.chrome_user_data_dir,
        chrome_profile_name: config.value.chrome_profile_name,
      },
    );
    testResult.value = resp.data;
    if (resp.data.ok) {
      toast.success("Native Chrome 配置验证通过");
    } else {
      toast.warn(`启动测试失败：${resp.data.error ?? "未知错误"}`);
    }
  } catch (e: any) {
    const detail = e?.response?.data?.detail ?? e?.message ?? String(e);
    testResult.value = { ok: false, error: detail };
    toast.error(`测试请求失败：${detail}`);
  } finally {
    testLoading.value = false;
  }
}

async function saveConfig() {
  saveLoading.value = true;
  try {
    await sidecar.client.post("/api/monitor/baidu/native-config", config.value);
    toast.success("百度抓取配置已保存");
  } catch (e: any) {
    const detail = e?.response?.data?.detail ?? e?.message ?? "未知错误";
    toast.error(`保存失败：${detail}`);
  } finally {
    saveLoading.value = false;
  }
}

function copyError() {
  const err = testResult.value?.error ?? "";
  navigator.clipboard.writeText(err).catch(() => {});
}

watch(
  () => config.value.chrome_user_data_dir,
  (newVal) => {
    if (newVal) loadProfiles();
    else profiles.value = [];
  },
);

onMounted(loadConfig);
</script>

<template>
  <div class="flex flex-col" :style="{ gap: '0' }">
    <!-- Loading shimmer -->
    <div
      v-if="loading"
      class="flex items-center gap-2 py-4 text-[12px]"
      :style="{ color: 'var(--ink-3)' }"
    >
      <Spinner :size="12" />
      <span>读取配置…</span>
    </div>

    <template v-else>
      <!-- 启用开关 -->
      <div
        class="flex items-center gap-4 py-3.5"
        :style="{ borderBottom: '1px solid var(--line)' }"
      >
        <div class="min-w-0 flex-1">
          <div class="text-[13px] font-semibold">启用日常 Chrome profile 模式</div>
          <div class="mt-0.5 text-[11.5px]" :style="{ color: 'var(--ink-3)' }">
            借用你的真实 Chrome profile 运行百度抓取，降低风控触发率。<br />
            跑监控任务前需先关闭 Chrome 浏览器（OS 单用户数据目录限制）。
          </div>
        </div>
        <div class="flex flex-shrink-0 items-center gap-2">
          <FormToggle
            :model-value="config.use_native_chrome"
            @update:model-value="(v) => { config.use_native_chrome = v; testResult = null; }"
          />
        </div>
      </div>

      <!-- 配置面板（仅启用时展示） -->
      <div
        v-if="config.use_native_chrome"
        class="mt-4 flex flex-col"
        :style="{
          paddingLeft: '1rem',
          borderLeft: '3px solid var(--line)',
          gap: '0',
        }"
      >
        <!-- Chrome 可执行文件路径 -->
        <div
          class="flex items-center gap-4 py-3.5"
          :style="{ borderBottom: '1px solid var(--line)' }"
        >
          <div class="min-w-0 flex-1">
            <div class="text-[13px] font-semibold">Chrome 可执行文件路径</div>
            <div class="mt-0.5 text-[11.5px]" :style="{ color: 'var(--ink-3)' }">
              留空则点「自动探测」让程序找
            </div>
          </div>
          <div class="flex flex-shrink-0 items-center gap-2">
            <FormInput
              :model-value="config.chrome_executable_path ?? ''"
              placeholder="C:\Program Files\Google\Chrome\Application\chrome.exe"
              :width="340"
              debounce="live"
              @update:model-value="(v) => { config.chrome_executable_path = v ? String(v) : null }"
            />
            <Btn variant="ghost" small :disabled="detectLoading" @click="detectChrome">
              <Spinner v-if="detectLoading" :size="12" />
              <Icon v-else name="search" :size="13" />
              <span>{{ detectLoading ? "探测中…" : "自动探测" }}</span>
            </Btn>
          </div>
        </div>

        <!-- Chrome User Data 目录 -->
        <div
          class="flex items-center gap-4 py-3.5"
          :style="{ borderBottom: '1px solid var(--line)' }"
        >
          <div class="min-w-0 flex-1">
            <div class="text-[13px] font-semibold">Chrome User Data 目录</div>
            <div class="mt-0.5 text-[11.5px]" :style="{ color: 'var(--ink-3)' }">
              通常位于 %LOCALAPPDATA%\Google\Chrome\User Data
            </div>
          </div>
          <div class="flex flex-shrink-0 items-center">
            <FormInput
              :model-value="config.chrome_user_data_dir ?? ''"
              placeholder="%LOCALAPPDATA%\Google\Chrome\User Data"
              :width="340"
              debounce="live"
              @update:model-value="(v) => { config.chrome_user_data_dir = v ? String(v) : null }"
            />
          </div>
        </div>

        <!-- Profile 选择 -->
        <div
          class="flex items-center gap-4 py-3.5"
          :style="{ borderBottom: '1px solid var(--line)' }"
        >
          <div class="min-w-0 flex-1">
            <div class="text-[13px] font-semibold">使用 Profile</div>
            <div class="mt-0.5 text-[11.5px]" :style="{ color: 'var(--ink-3)' }">
              {{ profiles.length > 0 ? `检测到 ${profiles.length} 个 profile` : '填写 User Data 目录后自动加载' }}
            </div>
          </div>
          <div class="flex flex-shrink-0 items-center">
            <select
              v-if="profiles.length > 0"
              v-model="config.chrome_profile_name"
              class="bg-card-2 px-3 py-2 text-[13px] outline-none transition-colors"
              :style="{
                borderRadius: 'var(--radius-inner)',
                border: '1px solid var(--line)',
                minWidth: '220px',
              }"
            >
              <option v-for="p in profiles" :key="p.name" :value="p.name">
                {{ p.name }}{{ p.account_email ? ` (${p.account_email})` : '' }}
              </option>
            </select>
            <input
              v-else
              v-model="config.chrome_profile_name"
              placeholder="Default"
              class="bg-card-2 px-3 py-2 text-[13px] outline-none transition-colors"
              :style="{
                borderRadius: 'var(--radius-inner)',
                border: '1px solid var(--line)',
                width: '220px',
              }"
            />
          </div>
        </div>

        <!-- 操作按钮行 -->
        <div class="flex items-center gap-3 py-3.5">
          <Btn
            variant="ghost"
            small
            :disabled="testLoading || !config.chrome_executable_path || !config.chrome_user_data_dir"
            @click="testStartup"
          >
            <Spinner v-if="testLoading" :size="12" />
            <Icon v-else name="check" :size="13" />
            <span>{{ testLoading ? "测试中…" : "测试启动" }}</span>
          </Btn>
          <Btn variant="solid" small :disabled="saveLoading" @click="saveConfig">
            <Spinner v-if="saveLoading" :size="12" />
            <span>{{ saveLoading ? "保存中…" : "保存配置" }}</span>
          </Btn>
        </div>

        <!-- 测试结果 -->
        <div
          v-if="testResult !== null"
          class="flex items-center gap-3 rounded-[10px] px-4 py-3 text-[12.5px]"
          :style="{
            background: testResult.ok ? 'color-mix(in srgb, var(--success, #4caf50) 12%, transparent)' : 'color-mix(in srgb, var(--danger, #ef4444) 12%, transparent)',
            color: testResult.ok ? 'var(--success, #2e7d32)' : 'var(--danger, #c62828)',
            border: `1px solid ${testResult.ok ? 'color-mix(in srgb, var(--success, #4caf50) 30%, transparent)' : 'color-mix(in srgb, var(--danger, #ef4444) 30%, transparent)'}`,
          }"
        >
          <Icon :name="testResult.ok ? 'check' : 'x'" :size="14" />
          <span v-if="testResult.ok">配置可用，Native Chrome 启动正常</span>
          <span v-else class="flex-1 truncate" :title="testResult.error">
            启动失败：{{ testResult.error }}
          </span>
          <button
            v-if="!testResult.ok && testResult.error"
            type="button"
            class="flex-shrink-0 text-[11px] underline opacity-70"
            @click="copyError"
          >
            复制错误
          </button>
        </div>
      </div>
    </template>
  </div>
</template>
