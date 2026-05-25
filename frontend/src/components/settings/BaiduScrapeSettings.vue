<script setup lang="ts">
/**
 * 百度抓取 — Native Chrome profile 副本模式（方案 B'）
 *
 * 后端 API：
 *   GET  /api/monitor/baidu/native-config
 *     → { use_native_chrome, chrome_executable_path, chrome_user_data_dir,
 *          chrome_profile_name, chrome_profile_copy_path,
 *          chrome_profile_copy_imported_at }
 *   POST /api/monitor/baidu/native-config   Body = 同结构（省略 copy_path 字段）
 *   POST /api/monitor/baidu/detect-chrome
 *     → { executable_path, user_data_dir }
 *   POST /api/monitor/baidu/copy-profile
 *     Body = { source_user_data_dir, source_profile_name }
 *     → { ok, copy_path?, imported_at?, size_mb?, elapsed_s?, error? }
 *   POST /api/monitor/baidu/test-native
 *     Body = { chrome_executable_path, chrome_profile_copy_path }
 *     → { ok, error? }
 */
import { ref, onMounted } from "vue";

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
  chrome_user_data_dir: string | null;  // 保留，记录上次导入的源
  chrome_profile_name: string;
  chrome_profile_copy_path: string | null;  // B' 副本路径
  chrome_profile_copy_imported_at: string | null;  // B' 导入时间戳
}

const sidecar = useSidecar();
const toast = useToast();

const config = ref<NativeConfig>({
  use_native_chrome: false,
  chrome_executable_path: null,
  chrome_user_data_dir: null,
  chrome_profile_name: "Default",
  chrome_profile_copy_path: null,
  chrome_profile_copy_imported_at: null,
});

const testResult = ref<{ ok: boolean; error?: string } | null>(null);
const loading = ref(false);
const detectLoading = ref(false);
const testLoading = ref(false);
const saveLoading = ref(false);
const importing = ref(false);
const importResult = ref<{
  ok: boolean;
  copy_path?: string;
  imported_at?: string;
  size_mb?: number;
  elapsed_s?: number;
  error?: string;
} | null>(null);

function formatTimestamp(iso: string | null | undefined): string {
  if (!iso) return "--";
  try {
    return new Date(iso).toLocaleString("zh-CN");
  } catch {
    return iso;
  }
}

async function loadConfig() {
  loading.value = true;
  try {
    const resp = await sidecar.client.get<NativeConfig>("/api/monitor/baidu/native-config");
    config.value = resp.data;
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

async function importProfile() {
  importing.value = true;
  importResult.value = null;
  try {
    // 用 detect-chrome 拿到 user_data_dir
    const detectResp = await sidecar.client.post<{ executable_path: string | null; user_data_dir: string | null }>(
      "/api/monitor/baidu/detect-chrome",
    );
    const detected = detectResp.data;
    if (!detected.user_data_dir) {
      importResult.value = { ok: false, error: "未检测到 Chrome User Data 目录，请确认 Chrome 已安装" };
      return;
    }
    // 复制 Default profile
    const copyResp = await sidecar.client.post<{
      ok: boolean;
      copy_path?: string;
      imported_at?: string;
      size_mb?: number;
      elapsed_s?: number;
      error?: string;
    }>("/api/monitor/baidu/copy-profile", {
      source_user_data_dir: detected.user_data_dir,
      source_profile_name: "Default",
    });
    importResult.value = copyResp.data;
    if (copyResp.data.ok) {
      // reload config 看新 copy_path + imported_at
      await loadConfig();
    }
  } catch (e) {
    importResult.value = { ok: false, error: String(e) };
  } finally {
    importing.value = false;
  }
}

async function testStartup() {
  if (!config.value.chrome_executable_path || !config.value.chrome_profile_copy_path) return;
  testLoading.value = true;
  testResult.value = null;
  try {
    const resp = await sidecar.client.post<{ ok: boolean; error?: string }>(
      "/api/monitor/baidu/test-native",
      {
        chrome_executable_path: config.value.chrome_executable_path,
        chrome_profile_copy_path: config.value.chrome_profile_copy_path,
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
    await sidecar.client.post("/api/monitor/baidu/native-config", {
      use_native_chrome: config.value.use_native_chrome,
      chrome_executable_path: config.value.chrome_executable_path,
      chrome_user_data_dir: config.value.chrome_user_data_dir,
      chrome_profile_name: config.value.chrome_profile_name,
    });
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
            启用后用你 Chrome profile 的副本跑监控，降低风控触发率。<br />
            跑监控时不需要关 Chrome（副本独立运行）。
          </div>
        </div>
        <div class="flex flex-shrink-0 items-center gap-2">
          <FormToggle
            :model-value="config.use_native_chrome"
            @update:model-value="(v) => { config.use_native_chrome = v; testResult = null; saveConfig(); }"
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

        <!-- Chrome profile 副本 -->
        <div
          class="flex items-center gap-4 py-3.5"
          :style="{ borderBottom: '1px solid var(--line)' }"
        >
          <div class="min-w-0 flex-1">
            <div class="text-[13px] font-semibold">Chrome profile 副本</div>
            <div v-if="config.chrome_profile_copy_path" class="mt-0.5 text-[11.5px]" :style="{ color: 'var(--ink-3)' }">
              <div>副本路径：<code>{{ config.chrome_profile_copy_path }}</code></div>
              <div>导入时间：{{ formatTimestamp(config.chrome_profile_copy_imported_at) }}</div>
            </div>
            <div v-else class="mt-0.5 text-[11.5px]" :style="{ color: 'var(--ink-3)' }">
              还未导入。点右侧按钮一键复制你的 Chrome Default profile（约 30-60 秒）。
            </div>
          </div>
          <div class="flex flex-shrink-0 items-center gap-2">
            <Btn variant="ghost" small :disabled="importing" @click="importProfile">
              <Spinner v-if="importing" :size="12" />
              <Icon v-else name="copy" :size="13" />
              <span>{{ importing ? '复制中…' : (config.chrome_profile_copy_path ? '重新导入' : '复制 Chrome profile') }}</span>
            </Btn>
          </div>
        </div>

        <!-- 导入进度提示 -->
        <div
          v-if="importing"
          class="py-2 text-[11.5px]"
          :style="{ color: 'var(--ink-3)' }"
        >
          正在复制中（约 30-60 秒，副本约 200MB）…
        </div>

        <!-- 导入结果 -->
        <div
          v-if="importResult !== null"
          class="flex items-center gap-3 rounded-[10px] px-4 py-3 text-[12.5px]"
          :style="{
            background: importResult.ok ? 'color-mix(in srgb, var(--success, #4caf50) 12%, transparent)' : 'color-mix(in srgb, var(--danger, #ef4444) 12%, transparent)',
            color: importResult.ok ? 'var(--success, #2e7d32)' : 'var(--danger, #c62828)',
            border: `1px solid ${importResult.ok ? 'color-mix(in srgb, var(--success, #4caf50) 30%, transparent)' : 'color-mix(in srgb, var(--danger, #ef4444) 30%, transparent)'}`,
            marginTop: '0.5rem',
          }"
        >
          <Icon :name="importResult.ok ? 'check' : 'x'" :size="14" />
          <span v-if="importResult.ok">
            复制成功（{{ importResult.size_mb }} MB / {{ importResult.elapsed_s }}s）
          </span>
          <span v-else class="flex-1 truncate" :title="importResult.error">
            复制失败：{{ importResult.error }}
          </span>
        </div>

        <!-- 操作按钮行 -->
        <div class="flex items-center gap-3 py-3.5">
          <Btn
            variant="ghost"
            small
            :disabled="testLoading || !config.chrome_executable_path || !config.chrome_profile_copy_path"
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
