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
 *     → { executable_path, user_data_dir, profiles, resolved_profile_name }
 *   POST /api/monitor/baidu/list-profiles
 *     Body = { user_data_dir } → { profiles, resolved_profile_name }
 *   POST /api/monitor/baidu/copy-profile
 *     Body = { source_user_data_dir, source_profile_name | null }
 *     → { ok, copy_path?, profile_name?, imported_at?, size_mb?, elapsed_s?, error? }
 *   POST /api/monitor/baidu/test-native
 *     Body = { chrome_executable_path, chrome_profile_copy_path }
 *     → { ok, error? }
 */
import { computed, ref, onMounted, onUnmounted } from "vue";

import Btn from "@/components/ui/Btn.vue";
import Icon from "@/components/ui/Icon.vue";
import Spinner from "@/components/ui/Spinner.vue";
import FormToggle from "@/components/forms/FormToggle.vue";
import FormInput from "@/components/forms/FormInput.vue";
import FormSelect from "@/components/forms/FormSelect.vue";
import { useSidecar } from "@/stores/sidecar";
import { useToast } from "@/composables/useToast";

interface NativeConfig {
  use_native_chrome: boolean;
  chrome_executable_path: string | null;
  chrome_user_data_dir: string | null;  // 保留，记录上次导入的源
  chrome_profile_name: string;
  chrome_profile_copy_path: string | null;  // B' 副本路径
  chrome_profile_copy_imported_at: string | null;  // B' 导入时间戳
  chrome_profile_copy_last_logged_in_at: string | null;  // B' 上次登录时间
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
  chrome_profile_copy_last_logged_in_at: null,
});

interface ChromeProfile {
  name: string;                     // 目录名："Default" / "Profile 1"
  account_email: string | null;
  display_name: string | null;      // 用户在 Chrome 里起的名字："工作" / "个人"
}

const testResult = ref<{ ok: boolean; error?: string } | null>(null);
const loading = ref(false);
const detectLoading = ref(false);
const testLoading = ref(false);
const saveLoading = ref(false);
const importing = ref(false);
const launching = ref(false);
// 探测到的 profile 列表 + 当前选中的（"" = 交给后端挑）。
// 早期版本这里写死复制 "Default" —— 用户 Chrome 里删过默认 profile、只剩
// "Profile 1" 时导入必然失败，而且 UI 里没有任何地方能改选。
const profiles = ref<ChromeProfile[]>([]);
const selectedProfile = ref<string>("");
const profilesLoading = ref(false);
// 「Chrome 数据目录」被手动改过还没落库 —— 落库（保存 / 导入成功）后清掉
const dirEdited = ref(false);
const importResult = ref<{
  ok: boolean;
  copy_path?: string;
  profile_name?: string;
  imported_at?: string;
  size_mb?: number;
  elapsed_s?: number;
  error?: string;
  warning?: string;
} | null>(null);
// 副本登录窗的结果独立于复制结果 ── 否则登录失败会被显示成"复制失败"
const loginResult = ref<{ ok: boolean; error?: string } | null>(null);

function formatTimestamp(iso: string | null | undefined): string {
  if (!iso) return "--";
  try {
    return new Date(iso).toLocaleString("zh-CN");
  } catch {
    return iso;
  }
}

async function loadConfig(refreshProfiles = true) {
  loading.value = true;
  // 用户手输还没保存的数据目录不能被覆盖 —— loadConfig 也会被「副本登录完成」
  // 事件触发，正在输路径时窗口一关，输了一半的内容就没了。
  // 留旧对象的引用而不是快照值：请求飞在路上时用户还在打字，改的是旧对象。
  const prev = config.value;
  try {
    const resp = await sidecar.client.get<NativeConfig>("/api/monitor/baidu/native-config");
    config.value = resp.data;
    if (dirEdited.value) config.value.chrome_user_data_dir = prev.chrome_user_data_dir;
    // 只在还没选过时用配置里的值兜底 —— loadConfig 也会被「副本登录完成」事件
    // 触发，那时不能把用户刚在下拉里改的选择冲掉。
    if (!selectedProfile.value && config.value.chrome_profile_name) {
      selectedProfile.value = config.value.chrome_profile_name;
    }
    if (refreshProfiles && config.value.use_native_chrome) void refreshChromeInfo();
  } catch (e: any) {
    const detail = e?.response?.data?.detail ?? e?.message ?? "未知错误";
    toast.error(`读取配置失败：${detail}`);
  } finally {
    loading.value = false;
  }
}

const profileOptions = computed(() =>
  profiles.value.map((p) => {
    const named = p.display_name && p.display_name !== p.name
      ? `${p.display_name}（${p.name}）`
      : p.name;
    return { value: p.name, label: p.account_email ? `${named} · ${p.account_email}` : named };
  }),
);

// 上次拉 profile 列表用的目录 + 请求序号。目录变了要重选（不同 Chrome 安装
// 下同名的 "Profile 2" 可能是完全不同的账号）；序号用于丢弃过期响应。
const profilesDir = ref<string | null>(null);
let refreshSeq = 0;

function applyProfiles(
  dir: string | null,
  d: { profiles?: ChromeProfile[]; resolved_profile_name?: string | null },
) {
  if (dir !== profilesDir.value) {
    profilesDir.value = dir;
    selectedProfile.value = "";  // 换目录 = 重新选
  }
  profiles.value = d.profiles ?? [];
  const names = profiles.value.map((p) => p.name);
  // 选中项失效（用户在 Chrome 里删了这个 profile）才改，
  // 否则保留用户的选择不被后台推荐值覆盖。
  if (!selectedProfile.value || !names.includes(selectedProfile.value)) {
    selectedProfile.value = d.resolved_profile_name ?? "";
  }
}

/**
 * 刷新 profile 列表，返回本次用的 Chrome 数据目录（拿不到 → null）。
 *
 * 手填的数据目录优先于自动探测（公司统一部署 / 非默认渠道的机器上自动探测
 * 走不通，必须留人工出口），但**它里面没有 profile 时要退回自动探测**：
 * 这个字段每次导入成功都会被后端写上当时的源目录，于是一旦那个路径失效
 * （换机器、改 Windows 用户名、Chrome 搬家），把它当死命令就等于永久关掉
 * 自动探测，用户在界面上看不出该去清空它。
 */
async function refreshChromeInfo(): Promise<string | null> {
  const seq = ++refreshSeq;
  const manual = config.value.chrome_user_data_dir?.trim();
  profilesLoading.value = true;
  try {
    if (manual) {
      const resp = await sidecar.client.post<{
        profiles: ChromeProfile[];
        resolved_profile_name: string | null;
        unreadable: boolean;
      }>("/api/monitor/baidu/list-profiles", { user_data_dir: manual });
      // unreadable = 目录在、只是读不动（权限 / 网络盘断了）。这种情况**不能**
      // 当成"路径失效"改用别的目录 —— 那会闷声复制成另一个账号的登录态。
      // 让它照常走下去，由 copy-profile 报出真正的权限错误。
      if (resp.data.profiles?.length || resp.data.unreadable) {
        if (seq === refreshSeq) applyProfiles(manual, resp.data);
        return manual;
      }
    }
    const resp = await sidecar.client.post<{
      executable_path: string | null;
      user_data_dir: string | null;
      profiles: ChromeProfile[];
      resolved_profile_name: string | null;
    }>("/api/monitor/baidu/detect-chrome");
    const detected = resp.data.user_data_dir;
    if (seq === refreshSeq) applyProfiles(detected, resp.data);
    if (manual && detected && detected !== manual) {
      // 提示也归到最新一次请求，否则连点会弹重复 toast
      if (seq === refreshSeq) {
        toast.warn(`「${manual}」里没有 Chrome profile，已改用自动探测到的 ${detected}`);
      }
      return detected;
    }
    // 自动探测也没结果时返回手填值，让报错针对用户填的那个路径
    return detected ?? (manual || null);
  } catch (e: any) {
    if (seq === refreshSeq) profiles.value = [];
    const detail = e?.response?.data?.detail ?? e?.message ?? String(e);
    toast.error(`检测 Chrome profile 失败：${detail}`);
    return null;
  } finally {
    if (seq === refreshSeq) profilesLoading.value = false;
  }
}

async function detectChrome() {
  detectLoading.value = true;
  // 跟 refreshChromeInfo 共用序号：两边都会写 profiles/selectedProfile，
  // 不排队的话慢的那次响应会把新的覆盖回去。
  const seq = ++refreshSeq;
  try {
    const resp = await sidecar.client.post<{
      executable_path: string | null;
      user_data_dir: string | null;
      profiles: ChromeProfile[];
      resolved_profile_name: string | null;
    }>("/api/monitor/baidu/detect-chrome");
    const data = resp.data;
    config.value.chrome_executable_path = data.executable_path;
    // 同一个响应里已经带了 profile 列表，顺手填上，省一次往返
    if (seq === refreshSeq && !config.value.chrome_user_data_dir?.trim()) {
      applyProfiles(data.user_data_dir, data);
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

async function importProfile() {
  importing.value = true;
  importResult.value = null;
  try {
    // 手填目录优先，否则自动探测；顺带刷新 profile 列表让下拉有值
    const userDataDir = await refreshChromeInfo();
    if (!userDataDir) {
      importResult.value = {
        ok: false,
        error:
          "没找到 Chrome 数据目录。请确认 Chrome 已安装并至少正常启动过一次；" +
          "如果你的 Chrome 数据不在默认位置（公司统一部署 / 装的是 Beta 版 / 换过盘），" +
          "请在上面的「Chrome 数据目录」里手动填到 User Data 这一层。",
      };
      return;
    }
    // profile 名传 null = 让后端挑（Default 不存在时兜底到实际存在的那个）
    const copyResp = await sidecar.client.post<{
      ok: boolean;
      copy_path?: string;
      profile_name?: string;
      imported_at?: string;
      size_mb?: number;
      elapsed_s?: number;
      error?: string;
      warning?: string;
    }>("/api/monitor/baidu/copy-profile", {
      source_user_data_dir: userDataDir,
      source_profile_name: selectedProfile.value || null,
    }, {
      timeout: 600_000,  // 10 分钟 ── 用户可能有大 profile (14.6GB 实测过)，默认 60s 不够
    });
    importResult.value = copyResp.data;
    if (copyResp.data.ok) {
      // 后端可能兜底换了 profile —— 同步回下拉，别让 UI 显示的和实际复制的不一致
      if (copyResp.data.profile_name) selectedProfile.value = copyResp.data.profile_name;
      // 已落库：让 loadConfig 用服务端存的（规整过的）路径覆盖输入框
      dirEdited.value = false;
      // reload config 看新 copy_path + imported_at；profile 列表刚刷过，别再来一次
      await loadConfig(false);
    }
  } catch (e) {
    importResult.value = { ok: false, error: String(e) };
  } finally {
    importing.value = false;
  }
}

async function launchLoginWindow() {
  launching.value = true;
  loginResult.value = null;
  try {
    const resp = await sidecar.client.post<{ ok: boolean; pid?: number; error?: string }>(
      "/api/monitor/baidu/launch-login-window",
    );
    if (!resp.data.ok) {
      loginResult.value = { ok: false, error: resp.data.error };
    }
    // 成功：不立即 reset launching，让 UI 短暂显示"副本已启动"提示
  } catch (e: any) {
    const detail = e?.response?.data?.detail ?? e?.message ?? String(e);
    loginResult.value = { ok: false, error: detail };
  } finally {
    // 立刻 reset launching ── 用户可以再点（重新启动副本登录窗，无副作用）
    setTimeout(() => { launching.value = false; }, 2000);
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
      chrome_user_data_dir: config.value.chrome_user_data_dir?.trim() || null,
      // 注意：不把下拉的选择写进 chrome_profile_name —— 这个字段记的是「当前
      // 副本是从哪个 profile 复制来的」（界面上原样展示）。只保存不导入就改写
      // 它，会让界面谎报副本来源。真正的选择在导入时随 copy-profile 提交。
      chrome_profile_name: config.value.chrome_profile_name,
    });
    dirEdited.value = false;
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

// 副本登录窗关闭后，monitorStatus 收到 baidu_login_saved 事件会广播这个
// window CustomEvent（解耦：设置页不直接订阅 SSE）。收到后刷新「上次登录」
// 时间显示 + 结束 launching 态 + 未登录时给出明确提示。
function onLoginSaved(e: Event): void {
  const ok = (e as CustomEvent).detail?.ok ?? true;
  launching.value = false;
  loginResult.value = ok
    ? null
    : {
        ok: false,
        error: "未检测到登录态（副本里没有 BDUSS），请确认已在副本里登录百度后再完全关闭浏览器",
      };
  void loadConfig();
}

onMounted(() => {
  void loadConfig();
  window.addEventListener("csm:baidu-login-saved", onLoginSaved as EventListener);
});
onUnmounted(() => {
  window.removeEventListener("csm:baidu-login-saved", onLoginSaved as EventListener);
});
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
            @update:model-value="(v) => { config.use_native_chrome = v; testResult = null; saveConfig(); if (v) void refreshChromeInfo(); }"
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

        <!-- Chrome 数据目录（User Data）—— 非默认位置的机器必须能手填 -->
        <div
          class="flex items-center gap-4 py-3.5"
          :style="{ borderBottom: '1px solid var(--line)' }"
        >
          <div class="min-w-0 flex-1">
            <div class="text-[13px] font-semibold">Chrome 数据目录</div>
            <div class="mt-0.5 text-[11.5px]" :style="{ color: 'var(--ink-3)' }">
              留空＝自动探测；导入成功后这里会记下当时用的目录。
              公司统一部署 / 装的是 Beta 版 / 换过盘时，可手动填到
              <code>User Data</code> 这一层（填错或失效时会自动退回探测结果）。
            </div>
          </div>
          <div class="flex flex-shrink-0 items-center gap-2">
            <FormInput
              :model-value="config.chrome_user_data_dir ?? ''"
              placeholder="C:\Users\你的用户名\AppData\Local\Google\Chrome\User Data"
              :width="340"
              debounce="live"
              @update:model-value="(v) => { config.chrome_user_data_dir = v ? String(v) : null; dirEdited = true }"
            />
            <Btn variant="ghost" small :disabled="profilesLoading" @click="refreshChromeInfo">
              <Spinner v-if="profilesLoading" :size="12" />
              <Icon v-else name="refresh" :size="13" />
              <span>{{ profilesLoading ? "检测中…" : "检测 profile" }}</span>
            </Btn>
          </div>
        </div>

        <!-- 要复制哪个 profile —— 没有 Default 的机器（删过默认 profile）靠它自救 -->
        <div
          class="flex items-center gap-4 py-3.5"
          :style="{ borderBottom: '1px solid var(--line)' }"
        >
          <div class="min-w-0 flex-1">
            <div class="text-[13px] font-semibold">要复制的 Chrome profile</div>
            <div class="mt-0.5 text-[11.5px]" :style="{ color: 'var(--ink-3)' }">
              <template v-if="profiles.length">
                选你平时登录百度的那个（多账号 Chrome 别选错），
                选完点右上的「复制 Chrome profile / 重新导入」才生效。
              </template>
              <template v-else>
                没检测到 profile。请确认 Chrome 至少正常启动过一次；
                或在上面手动填数据目录后点「检测 profile」。
              </template>
            </div>
          </div>
          <div class="flex flex-shrink-0 items-center gap-2">
            <FormSelect
              v-if="profiles.length"
              :model-value="selectedProfile"
              :options="profileOptions"
              :width="340"
              placeholder="自动选择"
              @update:model-value="(v) => (selectedProfile = String(v))"
            />
            <span v-else class="text-[12px]" :style="{ color: 'var(--ink-3)', width: '340px' }">
              --
            </span>
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
              <div>来源 profile：<code>{{ config.chrome_profile_name }}</code></div>
              <div>导入时间：{{ formatTimestamp(config.chrome_profile_copy_imported_at) }}</div>
              <div v-if="config.chrome_profile_copy_last_logged_in_at">
                上次登录：{{ formatTimestamp(config.chrome_profile_copy_last_logged_in_at) }}
              </div>
              <div v-else :style="{ color: 'var(--warning, #f57c00)' }">
                ⚠ 还未登录副本。Chrome 复制 cookie 加密后副本解不开，需要在副本里登录一次。
              </div>
            </div>
            <div v-else class="mt-0.5 text-[11.5px]" :style="{ color: 'var(--ink-3)' }">
              还未导入。点右侧按钮把上面选中的 profile 复制一份（约 30-60 秒）。
            </div>
          </div>
          <div class="flex flex-shrink-0 items-center gap-2">
            <Btn variant="ghost" small :disabled="importing" @click="importProfile">
              <Spinner v-if="importing" :size="12" />
              <Icon v-else name="copy" :size="13" />
              <span>{{ importing ? '复制中…' : (config.chrome_profile_copy_path ? '重新导入' : '复制 Chrome profile') }}</span>
            </Btn>
            <Btn
              v-if="config.chrome_profile_copy_path"
              variant="ghost"
              small
              :disabled="launching"
              @click="launchLoginWindow"
            >
              <Spinner v-if="launching" :size="12" />
              <Icon v-else name="lock" :size="13" />
              <span>{{ launching ? '启动中…' : '登录百度（副本）' }}</span>
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

        <!-- 副本登录提示 -->
        <div
          v-if="launching"
          class="py-2 text-[11.5px]"
          :style="{ color: 'var(--ink-3)' }"
        >
          副本 Chrome 已弹出，登录百度后请完全关闭浏览器
        </div>

        <!-- 副本登录失败（独立于复制结果，避免误显示成"复制失败"） -->
        <div
          v-if="loginResult && !loginResult.ok"
          class="flex items-center gap-3 rounded-[10px] px-4 py-3 text-[12.5px]"
          :style="{
            background: 'color-mix(in srgb, var(--danger, #ef4444) 12%, transparent)',
            color: 'var(--danger, #c62828)',
            border: '1px solid color-mix(in srgb, var(--danger, #ef4444) 30%, transparent)',
            marginTop: '0.5rem',
          }"
        >
          <Icon name="x" :size="14" />
          <span class="flex-1 truncate" :title="loginResult.error">
            登录副本失败：{{ loginResult.error }}
          </span>
        </div>

        <!-- 导入结果 -->
        <div
          v-if="importResult !== null"
          class="flex items-start gap-3 rounded-[10px] px-4 py-3 text-[12.5px] leading-[1.6]"
          :style="{
            background: importResult.ok ? 'color-mix(in srgb, var(--success, #4caf50) 12%, transparent)' : 'color-mix(in srgb, var(--danger, #ef4444) 12%, transparent)',
            color: importResult.ok ? 'var(--success, #2e7d32)' : 'var(--danger, #c62828)',
            border: `1px solid ${importResult.ok ? 'color-mix(in srgb, var(--success, #4caf50) 30%, transparent)' : 'color-mix(in srgb, var(--danger, #ef4444) 30%, transparent)'}`,
            marginTop: '0.5rem',
          }"
        >
          <Icon :name="importResult.ok ? 'check' : 'x'" :size="14" class="mt-0.5 shrink-0" />
          <span v-if="importResult.ok">
            复制成功（profile
            {{ importResult.profile_name ?? config.chrome_profile_name }}，{{ importResult.size_mb }}
            MB / {{ importResult.elapsed_s }}s）
          </span>
          <span v-else class="flex-1" :title="importResult.error">
            复制失败：{{ importResult.error }}
          </span>
        </div>

        <!-- 复制成功但登录态被锁的提示（Chrome 开着时常见，非致命） -->
        <div
          v-if="importResult && importResult.ok && importResult.warning"
          class="flex items-start gap-3 rounded-[10px] px-4 py-3 text-[12.5px]"
          :style="{
            background: 'color-mix(in srgb, var(--warn, #f59e0b) 12%, transparent)',
            color: 'var(--warn, #b45309)',
            border: '1px solid color-mix(in srgb, var(--warn, #f59e0b) 30%, transparent)',
            marginTop: '0.5rem',
          }"
        >
          <Icon name="warn" :size="14" class="mt-0.5 shrink-0" />
          <span class="flex-1">{{ importResult.warning }}</span>
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
