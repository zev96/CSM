<script setup lang="ts">
/**
 * 设置页 —— 对齐 V1 设计稿 D:/CSM/CSM-RE1（V1）/src/screens/settings.jsx
 *
 *   - header: 设置 caption + 偏好 & 集成 大标题
 *   - 220px 左侧导航 (9 个 section) + 右侧面板
 *   - 面板 header：section 标题 + 副标题（无保存按钮 — autosave）
 *
 * 字段绑定到 AppConfig（csm_core/config.py）的策略：
 *   - 后端真有的字段（vault_root / out_dir / api_keys / timeout_seconds...）→
 *     维护一份 draft，setField 每次调用立即 PATCH /api/config 对应顶层
 *     字段（嵌套字段也发整块 top-level，后端 dict-merge）
 *   - V1 设计稿里有但后端没的（主题色 / 字体 / 文件名模板 / Skill 滑杆…）→
 *     用本地 ref 占位，让 UI 完整不塌；下游接入时把本地 ref 换成 draft 字段即可
 */
import { computed, defineComponent, h, onMounted, reactive, ref } from "vue";

import Btn from "@/components/ui/Btn.vue";
import Card from "@/components/ui/Card.vue";
import Icon from "@/components/ui/Icon.vue";
import Pill from "@/components/ui/Pill.vue";
// Spinner 已在下面跟 modal 一起 import，这里不重复
import FormSelect from "@/components/forms/FormSelect.vue";
import FormToggle from "@/components/forms/FormToggle.vue";
import CookieManagerModal from "@/components/monitor/CookieManagerModal.vue";
import NotificationPrefsModal from "@/components/ui/NotificationPrefsModal.vue";
import FormInput from "@/components/forms/FormInput.vue";
import Spinner from "@/components/ui/Spinner.vue";
import MiningPromptsCard from "@/components/settings/MiningPromptsCard.vue";
import TemplateLibrarySection from "@/components/settings/TemplateLibrarySection.vue";
import BaiduScrapeSettings from "@/components/settings/BaiduScrapeSettings.vue";
import logoUrl from "@/assets/logo.png";

import { useConfig } from "@/stores/config";
import { useToast } from "@/composables/useToast";
import { confirmDialog } from "@/composables/useConfirm";
import { usePathPicker } from "@/composables/usePathPicker";
import { useNotifications } from "@/composables/useNotifications";
import { useSidecar } from "@/stores/sidecar";
import { getVersion, keyringSet, keyringStatus } from "@/api/client";
import { useRoute } from "vue-router";
import { watch } from "vue";

// ── 行内子组件（避免拆 3 个单独文件）─────────────────────────
const SettingsRow = defineComponent({
  name: "SettingsRow",
  props: {
    label: { type: String, required: true },
    hint: { type: String, default: "" },
    last: { type: Boolean, default: false },
  },
  setup(props, { slots }) {
    return () =>
      h(
        "div",
        {
          class: "flex items-center gap-4 py-3.5",
          style: { borderBottom: props.last ? "none" : "1px solid var(--line)" },
        },
        [
          h("div", { class: "min-w-0 flex-1" }, [
            h("div", { class: "text-[13px] font-semibold" }, props.label),
            props.hint
              ? h(
                  "div",
                  {
                    class: "mt-0.5 text-[11.5px]",
                    style: { color: "var(--ink-3)" },
                  },
                  props.hint,
                )
              : null,
          ]),
          h(
            "div",
            { class: "flex flex-shrink-0 items-center gap-2" },
            slots.default?.(),
          ),
        ],
      );
  },
});

const PathField = defineComponent({
  name: "PathField",
  props: {
    value: { type: String, default: "" },
    title: { type: String, default: "选择文件夹" },
  },
  emits: ["update"],
  setup(props, { emit }) {
    const { pick } = usePathPicker();
    async function choose() {
      const v = await pick({
        title: props.title,
        directory: true,
        defaultPath: props.value || undefined,
      });
      if (v) emit("update", v);
    }
    return () =>
      h("div", { class: "flex items-center", style: { gap: "6px" } }, [
        h("input", {
          value: props.value,
          placeholder: "/path/to/folder",
          class: "font-mono px-3 outline-none",
          style: {
            height: "34px",
            minWidth: "280px",
            maxWidth: "340px",
            borderRadius: "10px",
            background: "var(--card-2)",
            border: "1px solid var(--line)",
            fontSize: "11px",
            color: "var(--ink-2)",
          },
          onChange: (e: Event) =>
            emit("update", (e.target as HTMLInputElement).value),
        }),
        h(
          "button",
          {
            type: "button",
            title: props.title,
            class: "inline-flex items-center justify-center",
            style: {
              height: "34px",
              padding: "0 12px",
              borderRadius: "10px",
              background: "var(--card-2)",
              border: "1px solid var(--line)",
              color: "var(--ink-2)",
              cursor: "pointer",
              fontSize: "11.5px",
              gap: "5px",
            },
            onClick: choose,
          },
          [h(Icon, { name: "folder", size: 13 }), h("span", "选择")],
        ),
      ]);
  },
});

const cfg = useConfig();
const toast = useToast();
const notifs = useNotifications();
const sidecar = useSidecar();
const route = useRoute();
const { pick: pickPath } = usePathPicker();

// Chrome 路径选择 —— directory=false 走文件选择器；Windows 过滤 .exe，
// macOS chrome.app 是个 bundle（目录），所以 mac 上不限扩展名让用户选 bundle
// 内的 Chromium 可执行；Linux 一般在 /usr/bin/google-chrome，不限制。
async function pickChromePath() {
  const isWin = typeof navigator !== "undefined" && /Win/i.test(navigator.platform);
  const current = (cfg.data as any)?.monitor?.chrome_path || "";
  const v = await pickPath({
    title: "选择 Chrome 可执行文件",
    directory: false,
    defaultPath: current || undefined,
    extensions: isWin ? ["exe"] : undefined,
  });
  if (v) setField("monitor.chrome_path", v);
}

// ── 8 个 section + 三分组 ────────────────────────────────────
// group 字段按用户重构方案分三段：
//   basics   基础配置（通用 / 存储路径）—— 安装后基本不动的
//   workflow 工作流相关（模型 / 历史查重 / 监测 / 评论模板库）—— 影响生成质量
//   system   系统/元信息（账号 / 关于）—— 跟用户/版本相关
// sidebar 模板按 group 分组渲染，组之间加灰色分隔 label。
interface SectionDef {
  k: string;
  l: string;
  icon: string;
  sub: string;
  group: "basics" | "workflow" | "system";
}
const SECTIONS: SectionDef[] = [
  { k: "general", l: "通用", icon: "settings", sub: "外观 · 行为 · 通知 · 导出", group: "basics" },
  { k: "paths", l: "存储路径", icon: "folder", sub: "Vault · 导出 · 模板 · Skills 目录", group: "basics" },
  { k: "models", l: "模型", icon: "key", sub: "API Key · 模型名 · Base URL", group: "workflow" },
  { k: "dedup", l: "历史查重", icon: "vault", sub: "历史 / vault 索引目录与重建", group: "workflow" },
  { k: "monitor", l: "监测", icon: "radar", sub: "并发 · 浏览器 · AI · Cookie", group: "workflow" },
  { k: "baidu-scrape", l: "百度抓取", icon: "radar", sub: "Native Chrome profile · 降低风控", group: "workflow" },
  { k: "templates", l: "评论模板库", icon: "bookmark", sub: "查看 · 编辑 · 批量导入 · 导出", group: "workflow" },
  { k: "account", l: "账号", icon: "user", sub: "登录态 · 工作空间", group: "system" },
  { k: "about", l: "关于", icon: "info", sub: "版本与更新", group: "system" },
];

const SECTION_GROUPS: Array<{ k: SectionDef["group"]; l: string }> = [
  { k: "basics", l: "基础" },
  { k: "workflow", l: "工作流" },
  { k: "system", l: "系统" },
];

// 按 group 分桶（template 渲染时直接 v-for 一遍 SECTION_GROUPS）
const sectionsByGroup = computed<Record<SectionDef["group"], SectionDef[]>>(() => {
  const out: Record<SectionDef["group"], SectionDef[]> = {
    basics: [], workflow: [], system: [],
  };
  for (const s of SECTIONS) out[s.group].push(s);
  return out;
});

const section = ref<string>("general");
// cur 已下线 —— 主面板顶部的「section 名 + sub」标题块按用户重构方案
// 移除（sidebar 上同样信息），不再需要这个 computed。

// ── Autosave draft ─────────────────────────────────────────────
// `draft` 是 cfg.data 的本地反射，所有 input/toggle 都通过 `setField`
// 写它一份。每次 setField 触发 → 立即 PATCH 仅那个顶层字段（嵌套字
// 段也是发整块 top-level，因为后端 PATCH 是 dict-merge）。
//
// 旧版本是 dirty=true + 「保存设置」按钮一次性 PATCH 整份 draft —— 但
// UI 没有"未保存就回滚"的需求（用户改完想看效果立刻生效），二段式
// 流程反而让人忘了点保存就走了。改成 autosave 后不再有 dirty 状态。
const draft = reactive<Record<string, any>>({});

function setField(path: string, value: unknown) {
  // path 支持嵌套：'monitor.alert_top_n' → draft.monitor.alert_top_n
  const parts = path.split(".");
  let obj: any = draft;
  for (let i = 0; i < parts.length - 1; i++) {
    if (!obj[parts[i]] || typeof obj[parts[i]] !== "object") {
      obj[parts[i]] = {};
    }
    obj = obj[parts[i]];
  }
  obj[parts[parts.length - 1]] = value;

  // Persist immediately. We send only the top-level key — backend
  // dict-merges, so `{ monitor: draft.monitor }` is enough for nested
  // updates. No throttling: every callsite is @change / click, not
  // per-keystroke, so worst case is one PATCH per UI action.
  const topKey = parts[0];
  autosave(topKey, draft[topKey]).catch(() => {
    /* autosave already toasts; swallow to avoid unhandled rejection */
  });
}

async function autosave(key: string, value: unknown) {
  try {
    await cfg.patch({ [key]: value });
  } catch (e: any) {
    toast.error(`保存失败：${e?.response?.data?.detail ?? e?.message ?? e}`);
    throw e;
  }
}

function get(path: string): any {
  const parts = path.split(".");
  let obj: any = draft;
  for (const p of parts) {
    if (obj == null) return undefined;
    obj = obj[p];
  }
  return obj;
}

function syncDraftFromCfg() {
  if (!cfg.data) return;
  // 浅拷贝顶层 + 深一层 monitor / api_keys
  Object.keys(draft).forEach((k) => delete draft[k]);
  for (const [k, v] of Object.entries(cfg.data)) {
    if (v && typeof v === "object" && !Array.isArray(v)) {
      draft[k] = { ...v };
    } else {
      draft[k] = v;
    }
  }
}

// 通知设置弹窗状态 —— 由通用 section 内的「设置」按钮 + 通知下拉的
// 「前往通知设置」hash 共同控制。声明上移到 applyHash 之前以避免
// TDZ（applyHash 在 onMounted 里跑，但显式定义在前更可读）。
const notifPrefsOpen = ref(false);

/**
 * Handle a route hash:
 *   - `#general` / `#paths` / ... → switch to that section
 *   - `#notify-prefs`             → switch to 通用 AND open the
 *                                   notification prefs modal (sentinel
 *                                   used by NotificationDropdown's
 *                                   「前往通知设置」link)
 *   - anything else               → ignore (don't silently misdirect)
 */
function applyHash(hash: string) {
  const k = hash.replace(/^#/, "");
  if (k === "notify-prefs") {
    section.value = "general";
    notifPrefsOpen.value = true;
    return;
  }
  if (SECTIONS.some((s) => s.k === k)) section.value = k;
}

onMounted(async () => {
  if (!cfg.data) await cfg.load();
  syncDraftFromCfg();
  refreshKeyringStatus();
  refreshBaiduLoginStatus();
  RPA_PLATFORMS.forEach((p) => refreshRpaLoginStatus(p.value));
  applyHash(route.hash);
});

watch(
  () => route.hash,
  (h) => applyHash(h),
);

// ── V1 设计稿里有但后端尚无的字段：本地占位 ───────────────────
// 注：language / checkUpdates / exportFrontmatter / exportDedupReport /
// imageHandling / preferredSkillId / hookStrength / density / autoVaultRefs /
// sentenceMaxLen / monitorFreq / monitorBrowser 都已随 UI 移除而清理。
const localUI = reactive({
  theme: "system",
  autoStart: false,
  filenameTemplate: "{date}-{title}-{seq}",
});

// ── Provider 信息（前端展示用，对齐 csm_core providers）────────
interface ProviderMeta {
  key: string;
  name: string;
  dot: string;
  defaultModel: string;
}
const PROVIDERS: ProviderMeta[] = [
  { key: "anthropic", name: "Anthropic", dot: "#c96442", defaultModel: "claude-sonnet-4-5" },
  { key: "deepseek", name: "DeepSeek", dot: "#4a8aa8", defaultModel: "deepseek-chat" },
  { key: "openai", name: "OpenAI", dot: "#7a9b5e", defaultModel: "gpt-4o-mini" },
  { key: "gemini", name: "Gemini", dot: "#5a7fa8", defaultModel: "gemini-2.0-flash" },
  { key: "qwen", name: "Qwen", dot: "#a85a7a", defaultModel: "qwen-max" },
  { key: "kimi", name: "Kimi", dot: "#1f1f1f", defaultModel: "kimi-k2.6" },
  { key: "doubao", name: "豆包", dot: "#3a6ea5", defaultModel: "doubao-pro-32k" },
  { key: "mock", name: "Mock", dot: "#7a7569", defaultModel: "(本地占位)" },
];

/**
 * Per-provider key-input draft. 行为：
 *   - 后端 keyring 不会返回明文，前端拿不到原始 key
 *   - 但为了让用户「看到」key 是存在的（不至于刷新后看到空框以为没存），
 *     当 providerHasKey 为真时把 draft 显示为一串掩码 (`API_KEY_MASK`)
 *   - 用户聚焦输入框时，如果当前 value 是掩码，自动清空 → 让他能输新值
 *   - 保存按钮：disabled 当 draft 为空 / 还是掩码 / 仅空白
 *   - 保存成功后回到掩码状态，输入框不留明文
 */
const API_KEY_MASK = "••••••••••••";
const providerKeyDraft = reactive<Record<string, string>>({});

/** input focus → 如果当前显示的是掩码，清空 */
function onKeyInputFocus(p: ProviderMeta) {
  if (providerKeyDraft[p.key] === API_KEY_MASK) {
    providerKeyDraft[p.key] = "";
  }
}
/** input blur → 如果用户没输新值但 provider 已经有 key 了，恢复掩码显示 */
function onKeyInputBlur(p: ProviderMeta) {
  if (!providerKeyDraft[p.key]?.trim() && providerHasKey[p.key]) {
    providerKeyDraft[p.key] = API_KEY_MASK;
  }
}
/** 判断 draft 是否是"可保存的新值"（既不为空也不是掩码） */
function isDraftRealKey(p: ProviderMeta): boolean {
  const v = providerKeyDraft[p.key];
  return Boolean(v?.trim()) && v !== API_KEY_MASK;
}
/** keyring "has-key" status per provider, loaded once on mount. */
const providerHasKey = reactive<Record<string, boolean>>({});
/** Last test outcome per provider — drives the pill colour. */
const providerTestState = reactive<
  Record<string, { state: "idle" | "testing" | "ok" | "fail"; detail?: string }>
>({});

async function refreshKeyringStatus() {
  for (const p of PROVIDERS) {
    if (p.key === "mock") {
      providerHasKey[p.key] = true;
      continue;
    }
    try {
      const s = await keyringStatus(p.key);
      providerHasKey[p.key] = Boolean(s.has_key);
    } catch {
      providerHasKey[p.key] = false;
    }
    // 同步初始化 draft：已经有 key 的 provider 显示掩码，没 key 的留空
    if (providerHasKey[p.key]) {
      providerKeyDraft[p.key] = API_KEY_MASK;
    }
  }
}

function providerStatus(p: ProviderMeta): "connected" | "untested" | "missing" {
  const t = providerTestState[p.key]?.state;
  if (t === "ok") return "connected";
  if (t === "fail") return "missing";
  if (providerHasKey[p.key]) return "untested";
  if (p.key === "mock") return "connected";
  return "missing";
}

async function saveProviderKey(p: ProviderMeta) {
  const raw = providerKeyDraft[p.key]?.trim();
  // 掩码不是真 key —— 防止用户没输新值就点保存，把一串 bullet 写到 keyring
  if (!raw || raw === API_KEY_MASK) {
    toast.warn(`${p.name}：请先粘贴 API Key`);
    return;
  }
  try {
    await keyringSet(p.key, raw);
    providerHasKey[p.key] = true;
    // 保存成功 → input 切回掩码显示，让用户视觉确认 "key 已存"
    providerKeyDraft[p.key] = API_KEY_MASK;
    toast.success(`${p.name} 密钥已保存`);
  } catch (e: any) {
    toast.error(`保存失败：${e?.message ?? e}`);
  }
}

async function testProvider(p: ProviderMeta) {
  providerTestState[p.key] = { state: "testing" };
  try {
    const resp = await sidecar.client.post("/api/polish/block", {
      text: "ping",
      provider: p.key,
    });
    const ok = Boolean(resp.data?.text);
    providerTestState[p.key] = { state: ok ? "ok" : "fail" };
    if (ok) {
      toast.success(`${p.name} 测试通过`);
    } else {
      toast.warn(`${p.name} 返回空响应`);
    }
  } catch (e: any) {
    const detail = e?.response?.data?.detail || e?.message || String(e);
    providerTestState[p.key] = { state: "fail", detail };
    toast.error(`${p.name} 测试失败：${detail}`);
  }
}

function setDefaultProvider(p: string) {
  draft.default_provider = p;
  autosave("default_provider", p).catch(() => {});
}
function setProviderModel(p: string, v: string) {
  if (!draft.default_model || typeof draft.default_model !== "object") {
    draft.default_model = {};
  }
  draft.default_model = { ...draft.default_model, [p]: v };
  autosave("default_model", draft.default_model).catch(() => {});
}
function setProviderBaseUrl(p: string, v: string) {
  if (!draft.base_urls || typeof draft.base_urls !== "object") {
    draft.base_urls = {};
  }
  draft.base_urls = { ...draft.base_urls, [p]: v };
  autosave("base_urls", draft.base_urls).catch(() => {});
}
// 豆包专属：AI 卡位采集走火山方舟 Ark「联网 bot」端点，需控制台建的 bot_id。
// 顶层 config 字段 doubao_bot_id（DoubaoProvider 读它），与 key/model 分开存。
function setDoubaoBotId(v: string) {
  draft.doubao_bot_id = v.trim();
  autosave("doubao_bot_id", draft.doubao_bot_id).catch(() => {});
}

// 关闭按钮行为下拉
const closeActionOptions = [
  { label: "最小化到托盘", value: "minimize_to_tray" },
  { label: "直接退出", value: "quit" },
];
const exportFormatOptions = [
  { label: "Markdown", value: "markdown" },
  { label: "DOCX", value: "docx" },
];
// 文件名模板：从自由文本输入改为下拉预设。两个开箱即用的方案够覆盖
// 90% 的人写文件名的习惯：要么按日期归档、要么纯标题。变量约定：
//   {date}  → MM-DD（月份-日期，由导出端拼装）
//   {title} → 文章标题
//   {seq}   → 当日序号（避免同一天多稿撞名）
const filenameTemplateOptions = [
  {
    label: "日期 + 标题 + 序号（如 05-11-文章标题-01）",
    value: "{date}-{title}-{seq}",
  },
  { label: "仅文章标题（如 文章标题）", value: "{title}" },
];

// ── 重建索引 —— 实际调后端 POST /api/dedup/build-index ─────────
// 之前这里只 toast「请到查重页操作」是错的：没有独立的查重页，本 section
// 就是查重设置 + 入口。后端 dedup_service.submit_build() 早就支持 kind
// = "history" | "vault" 异步建索引，前端只需要 POST 一下；progress 通过
// SSE 流（这里暂不订阅，简单 toast 即可，建完用户下次跑文章的"质检报告
// 重复率·历史"自然会看到对比结果）。
const rebuildBusy = ref<{ history: boolean; vault: boolean }>({
  history: false,
  vault: false,
});

async function rebuildIndex(kind: "history" | "vault") {
  if (rebuildBusy.value[kind]) return;
  const label = kind === "history" ? "历史" : "Vault";
  rebuildBusy.value[kind] = true;
  try {
    const r = await sidecar.client.post("/api/dedup/build-index", { kind });
    if (r.status === 202) {
      toast.success(`${label} 索引重建已启动，后台异步执行（job ${r.data?.job_id ?? "?"}）`);
    } else {
      toast.info(`${label} 索引重建返回 status=${r.status}`);
    }
  } catch (e: any) {
    const detail = e?.response?.data?.detail ?? e?.message ?? String(e);
    toast.error(`${label} 索引重建失败：${detail}`);
  } finally {
    rebuildBusy.value[kind] = false;
  }
}

// ── 关于：版本号从 sidecar 实时读 ───────────────────────────────
// 之前是硬编码常量 `const APP_VERSION = "0.4.0"`，跟 sidecar 实际报的
// 版本号容易脱节（v0.4.1 装好后用户看到 modal 弹"当前 v0.0.1"，因为
// sidecar __init__.py 没被 release.py bump，前端又有自己的常量，两端
// 都偏离了真版本）。改为启动时拉一次 /api/version；拉失败显示占位。
const appVersion = ref("…");
onMounted(async () => {
  try {
    const r = await getVersion();
    appVersion.value = r.sidecar;
  } catch {
    appVersion.value = "?";
  }
});

// 检查更新（完整闭环 prompt → downloading → ready → install_and_restart）：
//   1. /api/updater/check 拿 has_update + info（含 expected_sha256）
//   2. 没更新 / 出错 → toast
//   3. 有更新 → updateAlert() 弹 prompt
//   4. 用户点「立即更新」→ POST /api/updater/download 拿 job_id
//      → 切 phase=downloading → subscribe SSE 喂进度
//      → done 事件 → 切 phase=ready
//      → error / 用户「取消下载」→ 切 phase=error 或关闭弹窗
//   5. 用户点「立即重启」→ Tauri invoke install_and_restart
const updaterChecking = ref(false);
async function checkForUpdate() {
  if (updaterChecking.value) return;
  updaterChecking.value = true;
  try {
    const { updaterCheck, updaterDownload, subscribe } = await import(
      "@/api/client"
    );
    const {
      updateAlert,
      transitionToDownloading,
      updateProgress,
      transitionToReady,
      transitionToError,
    } = await import("@/composables/useUpdateAlert");
    const r = await updaterCheck();
    if (r.error) {
      toast.warn(`更新检查未完成：${r.error}`);
      return;
    }
    if (!r.has_update || !r.info) {
      toast.info(`已是最新版本（${r.current_version}）`);
      return;
    }

    const ctrl = updateAlert({
      info: r.info,
      currentVersion: r.current_version,
    });
    const decision = await ctrl.prompt;
    if (decision !== "update") return;

    // ── 触发下载 ──────────────────────────────────────────────
    let job: { job_id: string; stream_url: string };
    try {
      job = await updaterDownload(r.info.zip_url, r.info.expected_sha256);
    } catch (e: any) {
      transitionToError(
        `启动下载失败：${e?.response?.data?.detail ?? e?.message ?? e}`,
      );
      await ctrl.final;
      return;
    }

    transitionToDownloading();

    // SSE 订阅：tearDown 在 done / error / cancel 时调。
    //
    // ⚠ 关键：downloadedPath 必须**本地捕获**。不能在 invoke 时再读
    // updateAlertState.targetPath —— resolveFinal("restart") 内部同步调
    // closeAndReset() 会立刻把 state 全清掉（包括 targetPath = ""），等
    // SettingsView 这边的 await ctrl.final 在 microtask 后醒过来时，state
    // 已经是空的。本地变量不会被 reset 影响。
    let resolved = false; // 防止 done + cancel 抢双 finalResolve
    let downloadedPath = "";
    const stop = subscribe(job.stream_url, {
      progress: (d: any) => {
        if (resolved) return;
        updateProgress(d.done ?? 0, d.total ?? 0, d.percent ?? 0);
      },
      done: (d: any) => {
        if (resolved) return;
        resolved = true;
        downloadedPath = d.target ?? "";
        transitionToReady(downloadedPath);
        stop();
      },
      error: (d: any) => {
        if (resolved) return;
        resolved = true;
        transitionToError(d.error ?? "下载失败（未知原因）");
        stop();
      },
    });

    // 等用户在 ready / error / 取消下载 时做的二次决策
    const finalChoice = await ctrl.final;
    stop(); // 兜底：取消下载时 SSE 还没收到终止事件，主动断开

    if (finalChoice === "restart") {
      // dev 模式下 invoke 会失败 —— Tauri 把 "tauri" global 注入只在 release
      // 或 tauri dev 启的 webview 里；纯浏览器跑 vite 拿不到。
      try {
        const { invoke } = await import("@tauri-apps/api/core");
        await invoke("install_and_restart", {
          zipPath: downloadedPath,
        });
        // 走到这里说明 install_and_restart 没立刻 exit —— 不正常，给个 toast。
        toast.info("正在准备安装更新…");
      } catch (e: any) {
        const msg = String(e?.message ?? e ?? "");
        if (msg.includes("updater_not_found")) {
          toast.warn(
            "dev 环境下没有 updater.exe，无法测试安装重启流程。请打 release 包验证。",
          );
        } else {
          toast.error(`启动安装失败：${msg}`);
        }
      }
    }
  } catch (e: any) {
    toast.error(
      `检查更新失败：${e?.response?.data?.detail ?? e?.message ?? e}`,
    );
  } finally {
    updaterChecking.value = false;
  }
}

// ── Cookie 管理器：监测 section 内打开的弹窗 ─────────────────
const cookieMgrOpen = ref(false);

// ── 默认排除域名管理弹窗 (百度全局黑名单) ─────────────────────
// 弹窗内用 textarea 编辑；打开时 cloning 当前值到 draftRaw，避免在
// 用户敲字时频繁 setField（每次按键都会触发后端 PATCH）。
const excludeDomainsModalOpen = ref(false);
const excludeDomainsDraftRaw = ref("");

watch(excludeDomainsModalOpen, (open) => {
  if (open) {
    const list = (get("monitor.baidu_keyword.default_excluded_domains") ?? []) as string[];
    excludeDomainsDraftRaw.value = list.join("\n");
  }
});

function saveExcludeDomains() {
  const raw = excludeDomainsDraftRaw.value;
  const list = raw
    .split(/[\n,，、\s]+/)
    .map((s) => s.trim().replace(/^https?:\/\//i, "").replace(/\/$/, "").toLowerCase())
    .filter(Boolean);
  // dedupe preserving order
  const seen = new Set<string>();
  const dedup: string[] = [];
  for (const d of list) {
    if (!seen.has(d)) {
      seen.add(d);
      dedup.push(d);
    }
  }
  setField("monitor.baidu_keyword.default_excluded_domains", dedup);
  excludeDomainsModalOpen.value = false;
}

// 百度账号登录态（从 CookieManagerModal 迁回设置页百度区）
const baiduLoginStatus = ref<{ logged_in: boolean; username: string | null }>({
  logged_in: false,
  username: null,
});
const baiduLoginBusy = ref(false);

async function refreshBaiduLoginStatus() {
  try {
    const r = await sidecar.client.get("/api/monitor/baidu/login-status");
    baiduLoginStatus.value = {
      logged_in: !!r.data?.logged_in,
      username: r.data?.username ?? null,
    };
  } catch {
    baiduLoginStatus.value = { logged_in: false, username: null };
  }
}

async function startBaiduLogin() {
  if (!(await confirmDialog(
    "会打开一个浏览器窗口，登录后 CSM 抓取任务自动用登录态访问。建议使用专用账号。",
    { title: baiduLoginStatus.value.logged_in ? "重新登录百度" : "登录百度", okLabel: "登录", kind: "info" },
  ))) return;
  baiduLoginBusy.value = true;
  try {
    const r = await sidecar.client.post("/api/monitor/baidu/login", null, { timeout: 660_000 });
    const status = r.data?.status;
    if (status === "success") toast.success("百度账号登录成功");
    else if (status === "cancelled") toast.info("登录已取消");
    else if (status === "timeout") toast.error("登录超时（窗口已关闭）");
    else toast.error(`登录失败：未知状态 ${status}`);
  } catch (e: any) {
    toast.error(`登录失败：${e.response?.data?.detail ?? e.message ?? "未知错误"}`);
  } finally {
    baiduLoginBusy.value = false;
    await refreshBaiduLoginStatus();
  }
}

// AI 卡位 RPA 登录态（DeepSeek/Kimi/元宝 真浏览器持久档）
const RPA_PLATFORMS = [
  { value: "deepseek", label: "DeepSeek" },
  { value: "kimi", label: "Kimi" },
  { value: "yuanbao", label: "腾讯元宝" },
] as const;
const rpaLogin = reactive<Record<string, { logged_in: boolean; busy: boolean }>>({
  deepseek: { logged_in: false, busy: false },
  kimi: { logged_in: false, busy: false },
  yuanbao: { logged_in: false, busy: false },
});

async function refreshRpaLoginStatus(platform: string) {
  try {
    const r = await sidecar.client.get(`/api/monitor/geo/rpa/${platform}/login-status`);
    rpaLogin[platform].logged_in = !!r.data?.logged_in;
  } catch {
    rpaLogin[platform].logged_in = false;
  }
}

async function startRpaLogin(platform: string, label: string) {
  if (!(await confirmDialog(
    "会打开一个浏览器窗口，登录后 CSM 卡位采集任务自动用登录态访问。建议使用专用账号。",
    { title: `登录 ${label}`, okLabel: "登录", kind: "info" },
  ))) return;
  rpaLogin[platform].busy = true;
  try {
    const r = await sidecar.client.post(`/api/monitor/geo/rpa/${platform}/login`, null, { timeout: 360_000 });
    const status = r.data?.status;
    if (status === "success") toast.success(`${label} 登录成功`);
    else if (status === "cancelled") toast.info("登录已取消");
    else if (status === "timeout") toast.error("登录超时（窗口已关闭）");
    else toast.error(`登录失败：${r.data?.error ?? status}`);
  } catch (e: any) {
    toast.error(`登录失败：${e.response?.data?.detail ?? e.message ?? "未知错误"}`);
  } finally {
    rpaLogin[platform].busy = false;
    await refreshRpaLoginStatus(platform);
  }
}

// 「重置百度浏览器 profile」按用户要求放回设置 ——
// 它是 cookie 烫坏时的修复操作，跟日常登录不同语义，放回设置项更合理。
async function confirmResetBaiduProfile() {
  if (!(await confirmDialog(
    "下次任务会冷启重建，前几次抓取可能仍触发风控（cookie 需要慢慢累积）。",
    { title: "重置百度浏览器 profile", okLabel: "重置", kind: "danger" },
  ))) return;
  try {
    await sidecar.client.post("/api/monitor/baidu/reset-profile");
    toast.success("百度浏览器 profile 已重置");
  } catch (e: any) {
    const detail = e.response?.data?.detail ?? e.message ?? "未知错误";
    toast.error(`重置失败：${detail}`);
  }
}

// 通知设置弹窗的 ref 在文件上方声明（applyHash 需要先用）。

// ── 账号编辑弹窗 ─────────────────────────────────────────────
// 字段对齐后端 AppConfig：user_name / user_product。
// 之前误用 product_line —— Pydantic extra="ignore" 会静默丢弃，
// 看似保存成功但盘上没写，是这次 "刷新后账号变回默认" 的元凶之一。
const accountEditOpen = ref(false);
const accountEditDraft = reactive({ user_name: "", user_product: "" });

function openAccountEdit() {
  accountEditDraft.user_name = (get("user_name") as string) || "";
  accountEditDraft.user_product = (get("user_product") as string) || "";
  accountEditOpen.value = true;
}
async function saveAccountEdit() {
  try {
    setField("user_name", accountEditDraft.user_name.trim());
    setField("user_product", accountEditDraft.user_product.trim());
    // setField 已经触发了 autosave；这里再 await 一次显式 cfg.patch 是
    // 为了能拿到失败信号 —— cfg.patch 已改成抛错，try/catch 才会真的接到。
    await cfg.patch({
      user_name: accountEditDraft.user_name.trim(),
      user_product: accountEditDraft.user_product.trim(),
    });
    toast.success("账号已更新");
    accountEditOpen.value = false;
  } catch (e: any) {
    toast.error(`保存失败：${e?.response?.data?.detail ?? e?.message ?? e}`);
  }
}
</script>

<template>
  <div class="anim-up flex h-full flex-col" style="gap: var(--density-gap)">
    <!--
      header —— 按用户要求只保留小字 eyebrow「设置」，原 H1「偏好 & 集成」
      整段移除（跟 MiningView / MonitorView / DataCenterView / 模板库
      顶部统一风格）。
    -->
    <div class="flex-shrink-0">
      <div
        class="text-[11px] uppercase"
        :style="{ color: 'var(--ink-3)', letterSpacing: '1.5px' }"
      >
        设置
      </div>
    </div>

    <!--
      body —— 重构后布局：
        sidebar 260px：分三组（基础 / 工作流 / 系统），每项 icon + 主名
        + 副描述（原来藏在数据里的 sub 字段）。选中态用橙色竖条 + card-2
        浅底（替代原 dark 块），跟应用其它页面的"选中"风格一致。
        主面板：原顶部「section 大字 + sub」整段移除（sidebar 已经显示
        了，重复占空间），直接渲染 SettingsRow 列表。
    -->
    <div
      class="grid min-h-0 flex-1"
      :style="{ gridTemplateColumns: '260px 1fr', gap: 'var(--density-gap)' }"
    >
      <!-- 左侧导航 —— 分组 + 富信息 -->
      <Card padless class="overflow-y-auto" :style="{ padding: '8px' }">
        <template v-for="(grp, gi) in SECTION_GROUPS" :key="grp.k">
          <!-- 组分隔 label（首组无 margin-top；其余组顶部留 padding 拉开） -->
          <div
            class="px-3 text-[10.5px] uppercase font-medium"
            :style="{
              color: 'var(--ink-4)',
              letterSpacing: '1.2px',
              paddingTop: gi === 0 ? '6px' : '14px',
              paddingBottom: '6px',
            }"
          >
            {{ grp.l }}
          </div>
          <button
            v-for="g in sectionsByGroup[grp.k]"
            :key="g.k"
            type="button"
            class="relative mb-0.5 flex w-full items-start gap-3 text-left transition"
            :style="{
              padding: '10px 12px 10px 14px',
              borderRadius: '10px',
              background: section === g.k ? 'var(--card-2)' : 'transparent',
              color: 'var(--ink)',
            }"
            @click="section = g.k"
            @mouseenter="(e) => { if (section !== g.k) (e.currentTarget as HTMLElement).style.background = 'rgba(28,26,23,0.04)' }"
            @mouseleave="(e) => { if (section !== g.k) (e.currentTarget as HTMLElement).style.background = 'transparent' }"
          >
            <!-- 选中态左侧 3px 橙竖条（仅选中时出） -->
            <span
              v-if="section === g.k"
              :style="{
                position: 'absolute',
                left: '4px',
                top: '12px',
                bottom: '12px',
                width: '3px',
                borderRadius: '999px',
                background: 'var(--primary)',
              }"
            />
            <Icon
              :name="g.icon"
              :size="15"
              :style="{
                flexShrink: 0,
                marginTop: '1px',
                color: section === g.k ? 'var(--primary-deep)' : 'var(--ink-3)',
              }"
            />
            <div class="min-w-0 flex-1">
              <div
                class="text-[12.5px]"
                :style="{
                  fontWeight: section === g.k ? 600 : 500,
                  color: section === g.k ? 'var(--ink)' : 'var(--ink-2)',
                }"
              >{{ g.l }}</div>
              <div
                class="mt-0.5 text-[10.5px] truncate"
                :style="{ color: 'var(--ink-4)', lineHeight: 1.4 }"
                :title="g.sub"
              >{{ g.sub }}</div>
            </div>
          </button>
        </template>
      </Card>

      <!-- 右侧面板 —— 直接渲染当前 section 的内容，section 标题/副标
           已下线（sidebar 上有同样信息，主面板再来一遍重复）。 -->
      <Card class="min-h-0 overflow-y-auto">
        <div class="flex flex-col">
          <!-- ━━━━━━━━ 通用 ━━━━━━━━ -->
          <!--
            说明：用户名移到「账号」section；语言、检查更新、字体、强调色
            都已移除（强调色的反向绑定一直没生效，宁可删掉也不留死按钮）。
            导出相关的两项（默认格式 / 文件名模板）合并到这里，避免因为
            只有两项还专门开一个 section。
          -->
          <template v-if="section === 'general'">
            <SettingsRow label="主题" hint="界面配色 — 跟随系统/明亮/暗色">
              <FormSelect
                v-model="localUI.theme"
                :options="[
                  { label: '跟随系统', value: 'system' },
                  { label: '明亮', value: 'light' },
                  { label: '暗色', value: 'dark' },
                ]"
                width="140"
              />
            </SettingsRow>
            <!--
              强调色（color swatch row）被移除 —— useTweaks().state.primary
              的反向绑定一直没真正生效，多次尝试后定为不维护，避免给用户
              一个"按了没反应"的死按钮。主色继续从 useTweaks 的 localStorage
              快照里读，对最终用户来说强调色就是固定的橙色。
            -->
            <SettingsRow label="关闭按钮行为" hint="点击 × 时的处理方式">
              <FormSelect
                :model-value="get('close_action') ?? 'minimize_to_tray'"
                :options="closeActionOptions"
                width="160"
                @update:model-value="(v) => setField('close_action', v)"
              />
            </SettingsRow>
            <SettingsRow label="开机自启" hint="系统启动后驻留托盘">
              <FormToggle v-model="localUI.autoStart" />
            </SettingsRow>
            <SettingsRow
              label="通知"
              hint="右上角铃铛 — 总开关 + 点「设置」按分类配置"
            >
              <Btn variant="ghost" small @click="notifPrefsOpen = true">
                <Icon name="settings" :size="13" />
                <span>设置</span>
              </Btn>
              <FormToggle
                :model-value="notifs.enabled.value"
                @update:model-value="(v) => notifs.setEnabled(v)"
              />
            </SettingsRow>
            <SettingsRow label="导出格式" hint="导出文章时的默认格式">
              <FormSelect
                :model-value="get('export_format') ?? 'markdown'"
                :options="exportFormatOptions"
                width="140"
                @update:model-value="(v) => setField('export_format', v)"
              />
            </SettingsRow>
            <SettingsRow
              label="导出文件名模板"
              hint="预设两种命名方案，避免手写变量出错"
              last
            >
              <FormSelect
                v-model="localUI.filenameTemplate"
                :options="filenameTemplateOptions"
                width="260"
              />
            </SettingsRow>
          </template>

          <!-- ━━━━━━━━ 存储路径 ━━━━━━━━ -->
          <!--
            每个 PathField 自带「选择」按钮，调 Tauri plugin-dialog 弹原生
            文件夹选择器，避免用户手输路径。默认模板这里仍允许手填一个
            .json 文件路径（usePathPicker 默认 directory:true，但用户也可
            直接在 input 里粘贴 .json 路径，下游 cfg.patch 不区分）。
          -->
          <template v-else-if="section === 'paths'">
            <SettingsRow
              label="素材库 (Vault)"
              hint="Obsidian Vault — 文章引用的素材源"
            >
              <PathField
                :value="get('vault_root') ?? ''"
                title="选择素材库 (Vault) 目录"
                @update="(v) => setField('vault_root', v)"
              />
            </SettingsRow>
            <SettingsRow label="导出目录" hint="Markdown / 报告 默认落地位置">
              <PathField
                :value="get('out_dir') ?? ''"
                title="选择导出目录"
                @update="(v) => setField('out_dir', v)"
              />
            </SettingsRow>
            <SettingsRow
              label="历史索引目录"
              hint="成稿镜像 / 最近文档 / 查重历史 — 三合一目录，首次启动已自动建好"
            >
              <PathField
                :value="get('dedup_history_dir') ?? ''"
                title="选择历史索引目录"
                @update="(v) => setField('dedup_history_dir', v)"
              />
            </SettingsRow>
            <SettingsRow label="默认模板目录" hint="模板 .json 所在文件夹 — 首次启动已自动建好，可改位置">
              <PathField
                :value="get('default_template') ?? ''"
                title="选择模板目录"
                @update="(v) => setField('default_template', v)"
              />
            </SettingsRow>
            <SettingsRow
              label="Skills 目录"
              hint="Skill .md 目录 — 首次启动已自动建好，可改位置"
              last
            >
              <PathField
                :value="get('skill_dir') ?? ''"
                title="选择 Skills 目录"
                @update="(v) => setField('skill_dir', v)"
              />
            </SettingsRow>
          </template>

          <!-- ━━━━━━━━ 模型 ━━━━━━━━ -->
          <!--
            每张卡三个输入 + 测试按钮：
              · 模型名 (default_model[provider])    — 走 cfg.patch 保存
              · API Key  — 立刻通过 keyringSet 写系统钥匙串（不进 draft，
                因为密钥不该混在普通 config diff 里上传）
              · Base URL (base_urls[provider]) — 走 cfg.patch 保存
              · 测试连接  — POST /api/polish/block 用 ping，OK/失败两态
                Pill 直接显示在卡头。
          -->
          <template v-else-if="section === 'models'">
            <div class="mb-3 text-[11.5px]" :style="{ color: 'var(--ink-3)' }">
              已配置模型 · {{ PROVIDERS.length }} 个 · 模型名 / API Key / Base URL 可以单独修改
            </div>
            <div class="grid grid-cols-2" :style="{ gap: '12px' }">
              <div
                v-for="p in PROVIDERS"
                :key="p.key"
                class="p-4"
                :style="{
                  background: 'var(--card-2)',
                  border: '1px solid var(--line)',
                  borderRadius: '14px',
                }"
              >
                <!-- Header: avatar + name + default pill + status pill -->
                <div class="flex items-center justify-between">
                  <div class="flex items-center gap-2.5">
                    <span
                      class="inline-flex items-center justify-center font-bold"
                      :style="{
                        width: '30px',
                        height: '30px',
                        borderRadius: '9px',
                        background: p.dot,
                        color: '#fff',
                        fontSize: '11px',
                      }"
                      >{{ p.name.slice(0, 1) }}</span
                    >
                    <div>
                      <div class="flex items-center gap-1.5 text-[13px] font-semibold">
                        {{ p.name }}
                        <span
                          v-if="get('default_provider') === p.key"
                          class="rounded px-1.5 py-0.5 text-[10px] font-medium"
                          :style="{ background: 'var(--primary)', color: '#fff' }"
                          >默认</span
                        >
                      </div>
                      <div class="mt-0.5 text-[10.5px]" :style="{ color: 'var(--ink-3)' }">
                        默认 {{ p.defaultModel }}
                      </div>
                    </div>
                  </div>
                  <Pill
                    :tone="
                      providerStatus(p) === 'connected'
                        ? 'ok'
                        : providerStatus(p) === 'untested'
                        ? 'info'
                        : 'warn'
                    "
                  >
                    {{
                      providerStatus(p) === "connected"
                        ? "已连接"
                        : providerStatus(p) === "untested"
                        ? "未测试"
                        : "未配置"
                    }}
                  </Pill>
                </div>

                <!-- Three inputs -->
                <div class="mt-3 flex flex-col gap-2">
                  <!-- 模型名 -->
                  <input
                    :value="(get('default_model') ?? {})[p.key] ?? ''"
                    :placeholder="`模型名（默认 ${p.defaultModel}）`"
                    class="font-mono px-2.5 outline-none"
                    :style="{
                      height: '30px',
                      borderRadius: '8px',
                      background: 'var(--card-white)',
                      border: '1px solid var(--line)',
                      fontSize: '11px',
                      color: 'var(--ink-2)',
                    }"
                    @change="(e) => setProviderModel(p.key, (e.target as HTMLInputElement).value)"
                  />
                  <!--
                    API Key (Mock 不需要).
                    已保存的 provider 显示掩码 "••••••••••••" 让用户视觉
                    确认 "已存了"；点输入框时掩码自动清空让用户能改写。
                    保存按钮在卡片底栏与「测试 / 设为默认」并列。
                  -->
                  <input
                    v-if="p.key !== 'mock'"
                    v-model="providerKeyDraft[p.key]"
                    type="password"
                    :placeholder="providerHasKey[p.key] ? '已保存 — 点击输入新 key 可覆盖' : 'API Key'"
                    class="font-mono px-2.5 outline-none"
                    :style="{
                      height: '30px',
                      borderRadius: '8px',
                      background: 'var(--card-white)',
                      border: '1px solid var(--line)',
                      fontSize: '11px',
                      color: 'var(--ink-2)',
                    }"
                    @focus="onKeyInputFocus(p)"
                    @blur="onKeyInputBlur(p)"
                  />
                  <!-- Base URL -->
                  <input
                    :value="(get('base_urls') ?? {})[p.key] ?? ''"
                    placeholder="Base URL（留空走默认）"
                    class="font-mono px-2.5 outline-none"
                    :style="{
                      height: '30px',
                      borderRadius: '8px',
                      background: 'var(--card-white)',
                      border: '1px solid var(--line)',
                      fontSize: '11px',
                      color: 'var(--ink-2)',
                    }"
                    @change="(e) => setProviderBaseUrl(p.key, (e.target as HTMLInputElement).value)"
                  />
                  <!-- 豆包专属：AI 卡位采集联网 Bot ID（Ark 控制台建联网 bot 后填） -->
                  <input
                    v-if="p.key === 'doubao'"
                    :value="get('doubao_bot_id') ?? ''"
                    placeholder="AI 卡位联网 Bot ID（火山方舟建联网 bot 后填，采集用）"
                    class="font-mono px-2.5 outline-none"
                    :style="{
                      height: '30px',
                      borderRadius: '8px',
                      background: 'var(--card-white)',
                      border: '1px solid var(--line)',
                      fontSize: '11px',
                      color: 'var(--ink-2)',
                    }"
                    @change="(e) => setDoubaoBotId((e.target as HTMLInputElement).value)"
                  />
                </div>

                <!--
                  Footer 一行三段：
                    左侧 → [测试连接] + [设为默认] 一组（同属"应用到这个
                    provider"的语义）
                    右侧 → [保存]（写 API Key 到 keyring）
                  之前的布局把 测试 和 设为默认 分两端、保存挤进 API Key
                  行里，操作目标分散；现在两类按钮泾渭分明。
                -->
                <div class="mt-3 flex items-center justify-between gap-2">
                  <div class="flex items-center gap-2">
                    <Btn
                      variant="ghost"
                      small
                      :disabled="providerTestState[p.key]?.state === 'testing'"
                      @click="testProvider(p)"
                    >
                      <Spinner
                        v-if="providerTestState[p.key]?.state === 'testing'"
                        :size="12"
                      />
                      <Icon v-else name="check" :size="12" />
                      <span>{{
                        providerTestState[p.key]?.state === "testing"
                          ? "测试中…"
                          : "测试连接"
                      }}</span>
                    </Btn>
                    <button
                      v-if="get('default_provider') !== p.key"
                      type="button"
                      class="text-[11px]"
                      :style="{ color: 'var(--primary-deep)' }"
                      @click="setDefaultProvider(p.key)"
                    >
                      设为默认 →
                    </button>
                  </div>
                  <Btn
                    v-if="p.key !== 'mock'"
                    variant="solid"
                    small
                    :disabled="!isDraftRealKey(p)"
                    @click="saveProviderKey(p)"
                  >
                    保存
                  </Btn>
                </div>
              </div>
            </div>

            <div class="mb-3 mt-5 text-[11.5px]" :style="{ color: 'var(--ink-3)' }">
              高级
            </div>
            <div
              class="p-4"
              :style="{
                background: 'var(--card-2)',
                border: '1px solid var(--line)',
                borderRadius: '14px',
              }"
            >
              <SettingsRow
                label="超时"
                hint="单次请求等待上限，超过自动重试一次"
              >
                <input
                  :value="get('timeout_seconds') ?? 180"
                  type="number"
                  class="bg-card-white px-3 text-[12.5px] outline-none"
                  :style="{
                    width: '70px',
                    height: '34px',
                    borderRadius: '10px',
                    border: '1px solid var(--line)',
                  }"
                  @change="(e) => setField('timeout_seconds', Number((e.target as HTMLInputElement).value))"
                />
                <span class="text-[11.5px]" :style="{ color: 'var(--ink-3)' }">秒</span>
              </SettingsRow>
              <SettingsRow label="并发上限" hint="批量任务同时跑几条" last>
                <div
                  class="flex items-center"
                  :style="{
                    background: 'var(--card-white)',
                    borderRadius: '999px',
                    padding: '3px',
                    border: '1px solid var(--line)',
                  }"
                >
                  <button
                    v-for="n in [1, 2, 4, 6, 8]"
                    :key="n"
                    type="button"
                    class="inline-flex items-center font-medium"
                    :style="{
                      height: '24px',
                      padding: '0 12px',
                      borderRadius: '999px',
                      fontSize: '11.5px',
                      background:
                        (get('concurrency') ?? 3) === n ? 'var(--dark)' : 'transparent',
                      color: (get('concurrency') ?? 3) === n ? '#fbf7ec' : 'var(--ink-3)',
                      cursor: 'pointer',
                    }"
                    @click="setField('concurrency', n)"
                  >
                    {{ n }}
                  </button>
                </div>
              </SettingsRow>
            </div>

            <!--
              Outreach AI 提示词 — 评论楼 AI 速览 / AI 建议 用的 prompt
              模板的用户自定义入口。后端契约见 design §4.6，前端组件自带
              GET + PATCH，所以放在「模型」section 末尾是完整可用的。
            -->
            <div class="mb-3 mt-5 text-[11.5px]" :style="{ color: 'var(--ink-3)' }">
              Outreach AI 提示词
            </div>
            <MiningPromptsCard />
          </template>

          <!-- 导出 section 已合并到「通用」，「导出后操作」默认无动作。 -->

          <!-- ━━━━━━━━ 历史查重 ━━━━━━━━ -->
          <!--
            两类索引各自需要先指定源文件夹：
              - 历史索引 ← dedup_history_dir（历史成稿目录）
              - Vault 索引 ← vault_root（与「存储路径」共用，避免双份配置）
            没有源目录就没法重建，所以「选择文件夹 + 重建」并列展示。
          -->
          <template v-else-if="section === 'dedup'">
            <div
              class="flex items-center gap-3 p-4"
              :style="{
                background: 'var(--primary-soft)',
                color: 'var(--primary-deep)',
                borderRadius: '14px',
              }"
            >
              <Icon name="vault" :size="16" />
              <div class="flex-1 text-[12px]">
                对比历史文章库和 vault 素材，识别撞稿与未消化原文。索引在后台异步重建。
              </div>
            </div>
            <SettingsRow
              label="历史索引目录"
              hint="位置在「存储路径」section 修改"
            >
              <span
                class="font-mono truncate text-[11px]"
                :style="{
                  color: 'var(--ink-3)',
                  maxWidth: '340px',
                  display: 'inline-block',
                }"
                :title="get('dedup_history_dir') ?? ''"
              >
                {{ get('dedup_history_dir') || '— 未设置 —' }}
              </span>
            </SettingsRow>
            <SettingsRow
              label="历史索引重建"
              :hint="
                get('dedup_history_last_built')
                  ? `上次重建：${get('dedup_history_last_built')}`
                  : '尚未建立'
              "
            >
              <Btn
                variant="ghost"
                small
                :disabled="rebuildBusy.history"
                @click="rebuildIndex('history')"
              >
                <Spinner v-if="rebuildBusy.history" :size="12" />
                <Icon v-else name="refresh" :size="13" />
                <span>{{ rebuildBusy.history ? '重建中…' : '重建' }}</span>
              </Btn>
            </SettingsRow>
            <SettingsRow
              label="Vault 索引目录"
              hint="与「存储路径」中的素材库 (Vault) 同步"
            >
              <PathField
                :value="get('vault_root') ?? ''"
                title="选择 Vault 目录"
                @update="(v) => setField('vault_root', v)"
              />
            </SettingsRow>
            <SettingsRow
              label="Vault 索引重建"
              :hint="
                get('dedup_vault_last_built')
                  ? `上次重建：${get('dedup_vault_last_built')}`
                  : '尚未建立'
              "
            >
              <Btn
                variant="ghost"
                small
                :disabled="rebuildBusy.vault"
                @click="rebuildIndex('vault')"
              >
                <Spinner v-if="rebuildBusy.vault" :size="12" />
                <Icon v-else name="refresh" :size="13" />
                <span>{{ rebuildBusy.vault ? '重建中…' : '重建' }}</span>
              </Btn>
            </SettingsRow>
            <SettingsRow label="重复率告警阈值" hint="超过则在检查面板告警">
              <input
                :value="get('dedup_threshold_yellow') ?? 30"
                type="number"
                class="bg-card-white px-3 text-[12.5px] outline-none"
                :style="{
                  width: '70px',
                  height: '34px',
                  borderRadius: '10px',
                  border: '1px solid var(--line)',
                }"
                @change="(e) => setField('dedup_threshold_yellow', Number((e.target as HTMLInputElement).value))"
              />
              <span class="text-[11.5px]" :style="{ color: 'var(--ink-3)' }">%</span>
            </SettingsRow>
            <SettingsRow label="安全阈值" hint="低于则视为通过" last>
              <input
                :value="get('dedup_threshold_green') ?? 15"
                type="number"
                class="bg-card-white px-3 text-[12.5px] outline-none"
                :style="{
                  width: '70px',
                  height: '34px',
                  borderRadius: '10px',
                  border: '1px solid var(--line)',
                }"
                @change="(e) => setField('dedup_threshold_green', Number((e.target as HTMLInputElement).value))"
              />
              <span class="text-[11.5px]" :style="{ color: 'var(--ink-3)' }">%</span>
            </SettingsRow>
          </template>

          <!-- ━━━━━━━━ 监测 ━━━━━━━━ -->
          <!--
            说明：「启用监测」和「告警 Top N」两项移除 —— 监测的启停由
            监测页 task 自身的「运行/停止」按钮决定，没必要再加一层全局
            开关；Top N 没有实际告警逻辑挂钩，是 V1 设计稿的占位。
            「Cookie 池管理」整合到这里 —— 之前散落在监测页里要点 task
            才能打开，现在作为设置项一目了然。
          -->
          <template v-else-if="section === 'monitor'">
            <!--
              Cookie 池入口提到监测设置最顶 —— 按用户要求"比较重要且常用"，
              百度账号登录 + 重置浏览器 profile 都融合到了 Cookie 管理器
              modal 里，所以这里点击直接覆盖三项常用操作（百度登录 / 重置 /
              4 平台 cookie 管理）。
            -->
            <SettingsRow
              label="Cookie 池"
              hint="管理各平台登录态 — 百度账号登录 / 知乎 / B 站 / 抖音 / 快手"
            >
              <Btn variant="solid" small @click="cookieMgrOpen = true">
                <Icon name="key" :size="13" />
                <span>打开管理器</span>
              </Btn>
            </SettingsRow>
            <!--
              「常规设置」/「百度关键词」两块用同级 section header（粗体小标）
              + 顶部分割线分组，跟原来的深色 card-2 圈起来视觉权重大不一样。
            -->
            <div class="mb-3 mt-5 font-display text-[13px] font-semibold" :style="{ color: 'var(--ink)' }">
              常规设置
            </div>
            <SettingsRow label="平台并发" hint="单个平台同时发起的请求数">
              <input
                :value="get('monitor.concurrency_per_platform') ?? 2"
                type="number"
                class="bg-card-white px-3 text-[12.5px] outline-none"
                :style="{
                  width: '70px',
                  height: '34px',
                  borderRadius: '10px',
                  border: '1px solid var(--line)',
                }"
                @change="(e) => setField('monitor.concurrency_per_platform', Number((e.target as HTMLInputElement).value))"
              />
            </SettingsRow>
            <!--
              通知开关已迁至「通用」section —— 监测告警只是通知的一类，
              和「生成成功 / 排名异动 / 评论异动 / 导出完成」并列，集中
              在通用页配置更直观。
            -->
            <!--
              浏览器引擎选择 —— Patchright 是默认；DrissionPage 兜底。
              切换后需要重启 sidecar 才生效（旧引擎的 Chrome 进程不能热切）。
            -->
            <SettingsRow
              label="浏览器引擎"
              hint="Patchright = 反爬通过率高（推荐，首次跑会下载 Chromium ~170MB）；DrissionPage = 复用本机 Chrome 兜底。切换后请重启 sidecar。"
            >
              <FormSelect
                :model-value="(get('monitor.browser_engine') ?? 'patchright') as string"
                :options="[
                  { label: 'Patchright（推荐）', value: 'patchright' },
                  { label: 'DrissionPage（兜底）', value: 'drission' },
                ]"
                width="200"
                @update:model-value="(v) => setField('monitor.browser_engine', String(v))"
              />
            </SettingsRow>
            <!--
              多账号轮换：用户在 Cookie 池里放 2+ 条同平台 cookie 时启用；
              tasks_per_account 控制每条 cookie 连续承担几个 task。
            -->
            <SettingsRow
              label="多账号轮换"
              hint="Cookie 池有 2+ 条时启用 —— 每条连续抓 N 个任务后自动切下一条；命中风控立即切并冷却 30 分钟"
            >
              <FormToggle
                :model-value="get('monitor.multi_account_rotation') ?? false"
                @update:model-value="(v) => setField('monitor.multi_account_rotation', v)"
              />
            </SettingsRow>
            <SettingsRow
              label="每账号任务数"
              hint="开启「多账号轮换」时生效；推荐 2~3，太小流量太碎、太大起不到分摊作用"
            >
              <input
                :value="get('monitor.tasks_per_account') ?? 2"
                type="number"
                min="1"
                max="10"
                :disabled="!(get('monitor.multi_account_rotation') ?? false)"
                class="bg-card-white px-3 text-[12.5px] outline-none disabled:opacity-50"
                :style="{
                  width: '70px',
                  height: '34px',
                  borderRadius: '10px',
                  border: '1px solid var(--line)',
                }"
                @change="(e) => setField('monitor.tasks_per_account', Number((e.target as HTMLInputElement).value))"
              />
            </SettingsRow>
            <SettingsRow
              label="Cookie 冷却（分钟）"
              hint="命中 /unhuman / 登录墙时当前 cookie 暂停使用的时长。30 分钟够 zhihu 反爬窗口滑过去"
            >
              <input
                :value="get('monitor.cookie_cooldown_minutes') ?? 30"
                type="number"
                min="0"
                max="240"
                class="bg-card-white px-3 text-[12.5px] outline-none"
                :style="{
                  width: '70px',
                  height: '34px',
                  borderRadius: '10px',
                  border: '1px solid var(--line)',
                }"
                @change="(e) => setField('monitor.cookie_cooldown_minutes', Number((e.target as HTMLInputElement).value))"
              />
            </SettingsRow>
            <SettingsRow
              label="Chrome 路径"
              hint="DrissionPage 引擎下使用；留空 = 自动检测。Patchright 引擎用自己下载的 Chromium，不受此项影响"
            >
              <div class="flex items-center" :style="{ gap: '6px' }">
                <input
                  :value="get('monitor.chrome_path') ?? ''"
                  placeholder="留空走自动检测"
                  class="font-mono bg-card-white px-3 outline-none"
                  :style="{
                    width: '300px',
                    height: '34px',
                    borderRadius: '10px',
                    border: '1px solid var(--line)',
                    fontSize: '11.5px',
                  }"
                  @change="(e) => setField('monitor.chrome_path', (e.target as HTMLInputElement).value)"
                />
                <button
                  type="button"
                  title="选择 chrome.exe"
                  class="inline-flex items-center justify-center"
                  :style="{
                    height: '34px',
                    padding: '0 12px',
                    borderRadius: '10px',
                    background: 'var(--card-2)',
                    border: '1px solid var(--line)',
                    color: 'var(--ink-2)',
                    cursor: 'pointer',
                    fontSize: '11.5px',
                    gap: '5px',
                  }"
                  @click="pickChromePath"
                >
                  <Icon name="folder" :size="13" />
                  <span>选择</span>
                </button>
              </div>
            </SettingsRow>

            <div class="mt-6 pt-5" :style="{ borderTop: '1px solid var(--line)' }">
              <div class="mb-3 font-display text-[13px] font-semibold" :style="{ color: 'var(--ink)' }">
                AI 卡位 · RPA 登录
              </div>
              <SettingsRow
                v-for="p in RPA_PLATFORMS"
                :key="p.value"
                :label="p.label"
                hint="需登录后才能采集该平台的联网回答与来源。建议用专用账号。"
              >
                <div class="flex items-center gap-3">
                  <span
                    v-if="rpaLogin[p.value].logged_in"
                    class="text-[12px]" :style="{ color: 'var(--success, #16a34a)' }"
                  >已登录</span>
                  <span v-else class="text-[12px]" :style="{ color: 'var(--ink-3)' }">未登录</span>
                  <Btn variant="solid" small :disabled="rpaLogin[p.value].busy"
                       @click="startRpaLogin(p.value, p.label)">
                    <Icon name="user" :size="12" />
                    <span>{{ rpaLogin[p.value].logged_in ? "重新登录" : "登录" }}</span>
                  </Btn>
                </div>
              </SettingsRow>
            </div>

            <!--
              ── 百度关键词 子配置 ──
              之前用深色 card-2 背景把这组单独圈起来视觉权重过重；改为
              「常规设置」一道顶部分割线 + 一个粗体小标题（与上面那组
              用 8px 间距区分），跟其它分组保持同样的视觉层级。
            -->
            <div
              class="mt-6 pt-5"
              :style="{ borderTop: '1px solid var(--line)' }"
            >
              <div class="mb-3 font-display text-[13px] font-semibold" :style="{ color: 'var(--ink)' }">
                百度关键词
              </div>
              <SettingsRow
                label="百度账号登录"
                hint="抓取任务用登录态访问百度，显著降低风控触发率。建议用专用账号。"
              >
                <div class="flex items-center gap-3">
                  <span
                    v-if="baiduLoginStatus.logged_in"
                    class="text-[12px]"
                    :style="{ color: 'var(--success, #16a34a)' }"
                  >已登录{{ baiduLoginStatus.username ? ` @${baiduLoginStatus.username}` : "" }}</span>
                  <span v-else class="text-[12px]" :style="{ color: 'var(--ink-3)' }">未登录</span>
                  <Btn variant="solid" small :disabled="baiduLoginBusy" @click="startBaiduLogin">
                    <Icon name="user" :size="12" />
                    <span>{{ baiduLoginStatus.logged_in ? "重新登录" : "登录百度" }}</span>
                  </Btn>
                </div>
              </SettingsRow>
              <SettingsRow
                label="默认 headless"
                hint="勾选则后台跑浏览器；命中验证码会自动升级可见窗口。"
              >
                <FormToggle
                  :model-value="get('monitor.baidu_keyword.headless_default') ?? true"
                  @update:model-value="(v) => setField('monitor.baidu_keyword.headless_default', v)"
                />
              </SettingsRow>
              <SettingsRow
                label="验证码等待时长（秒）"
                hint="出现验证码后等待用户手动过验证的最长时间。"
              >
                <input
                  :value="get('monitor.baidu_keyword.captcha_visible_timeout_s') ?? 90"
                  type="number"
                  min="30"
                  max="300"
                  class="bg-card-white px-3 text-[12.5px] outline-none"
                  :style="{
                    width: '80px',
                    height: '34px',
                    borderRadius: '10px',
                    border: '1px solid var(--line)',
                  }"
                  @change="(e) => setField('monitor.baidu_keyword.captcha_visible_timeout_s', Number((e.target as HTMLInputElement).value))"
                />
              </SettingsRow>
              <SettingsRow
                label="单任务最多升级次数"
                hint="同一任务最多允许从 headless 切换到可见窗口的次数。"
              >
                <input
                  :value="get('monitor.baidu_keyword.captcha_max_promotions') ?? 1"
                  type="number"
                  min="0"
                  max="3"
                  class="bg-card-white px-3 text-[12.5px] outline-none"
                  :style="{
                    width: '80px',
                    height: '34px',
                    borderRadius: '10px',
                    border: '1px solid var(--line)',
                  }"
                  @change="(e) => setField('monitor.baidu_keyword.captcha_max_promotions', Number((e.target as HTMLInputElement).value))"
                />
              </SettingsRow>
              <SettingsRow
                label="SERP 节流（秒）"
                hint="跨任务 SERP 最小间隔；实际抖动取 [N, 2N]。"
              >
                <input
                  :value="get('monitor.baidu_keyword.serp_pacing_seconds') ?? 5"
                  type="number"
                  min="1"
                  max="60"
                  class="bg-card-white px-3 text-[12.5px] outline-none"
                  :style="{
                    width: '80px',
                    height: '34px',
                    borderRadius: '10px',
                    border: '1px solid var(--line)',
                  }"
                  @change="(e) => setField('monitor.baidu_keyword.serp_pacing_seconds', Number((e.target as HTMLInputElement).value))"
                />
              </SettingsRow>
              <SettingsRow
                label="文章节流（秒）"
                hint="SERP 解析完后逐条抓正文之间的最小间隔（抖动 [N, 2N]）；防止 10 条链接秒级连发触发 baidu 风控。"
              >
                <input
                  :value="get('monitor.baidu_keyword.article_pacing_seconds') ?? 3"
                  type="number"
                  min="0"
                  max="30"
                  class="bg-card-white px-3 text-[12.5px] outline-none"
                  :style="{
                    width: '80px',
                    height: '34px',
                    borderRadius: '10px',
                    border: '1px solid var(--line)',
                  }"
                  @change="(e) => setField('monitor.baidu_keyword.article_pacing_seconds', Number((e.target as HTMLInputElement).value))"
                />
              </SettingsRow>
              <SettingsRow
                label="百家号节流（秒）"
                hint="百家号 / mbd / mp 子域专用更宽间隔。百度自家子域反爬最严，建议比文章节流大 2–3 倍。"
              >
                <input
                  :value="get('monitor.baidu_keyword.baijiahao_pacing_seconds') ?? 8"
                  type="number"
                  min="0"
                  max="60"
                  class="bg-card-white px-3 text-[12.5px] outline-none"
                  :style="{
                    width: '80px',
                    height: '34px',
                    borderRadius: '10px',
                    border: '1px solid var(--line)',
                  }"
                  @change="(e) => setField('monitor.baidu_keyword.baijiahao_pacing_seconds', Number((e.target as HTMLInputElement).value))"
                />
              </SettingsRow>
              <SettingsRow
                label="熔断失败阈值"
                hint="连续失败达到此次数后触发熔断，暂停该平台的请求。"
              >
                <input
                  :value="get('monitor.baidu_keyword.breaker_failures') ?? 3"
                  type="number"
                  min="1"
                  max="10"
                  class="bg-card-white px-3 text-[12.5px] outline-none"
                  :style="{
                    width: '80px',
                    height: '34px',
                    borderRadius: '10px',
                    border: '1px solid var(--line)',
                  }"
                  @change="(e) => setField('monitor.baidu_keyword.breaker_failures', Number((e.target as HTMLInputElement).value))"
                />
              </SettingsRow>
              <SettingsRow
                label="熔断恢复时长（秒）"
                hint="熔断后等待多少秒再重新放行请求。"
              >
                <input
                  :value="get('monitor.baidu_keyword.breaker_cooldown_seconds') ?? 600"
                  type="number"
                  min="60"
                  max="3600"
                  class="bg-card-white px-3 text-[12.5px] outline-none"
                  :style="{
                    width: '80px',
                    height: '34px',
                    borderRadius: '10px',
                    border: '1px solid var(--line)',
                  }"
                  @change="(e) => setField('monitor.baidu_keyword.breaker_cooldown_seconds', Number((e.target as HTMLInputElement).value))"
                />
              </SettingsRow>
              <!--
                默认排除域名 —— 全局黑名单。之前直接挂个 120px 的 textarea
                在这条 row 里会把整张设置页撑得很高、滚动条乱跳；改为按钮
                +「管理排除域名」弹窗，row 高度保持跟其它字段一致。
                count 标显当前已配置的域名数，让用户不打开也知道规模。
              -->
              <div id="baidu-default-excludes">
                <SettingsRow
                  label="默认排除域名（全局黑名单）"
                  hint="所有百度任务默认应用的 SERP 过滤名单。常见 B2B/电商站点（jd.com / 1688.com / taobao.com 等）已经预置；任务级可再加自家品牌官网。"
                >
                  <div class="flex items-center gap-2">
                    <span class="text-[11.5px]" :style="{ color: 'var(--ink-3)' }">
                      {{ (get('monitor.baidu_keyword.default_excluded_domains') ?? []).length }} 条
                    </span>
                    <Btn variant="solid" small @click="excludeDomainsModalOpen = true">
                      <Icon name="edit" :size="12" />
                      <span>管理排除域名</span>
                    </Btn>
                  </div>
                </SettingsRow>
                <!--
                  「百度账号」登录已合并到 Cookie 池下拉的「百度」选项内。
                  这里只保留「重置浏览器 profile」—— cookie 烫坏时的修复
                  操作跟日常登录不同语义，留在设置项里更合理（也不容易
                  被用户误点）。
                -->
                <SettingsRow
                  label="重置百度浏览器 profile"
                  hint="如果连续触发百度风控、cookie 已经烫坏，点这里清空浏览器数据从头来。期间不能有运行中的百度任务。"
                  last
                >
                  <Btn variant="danger" small @click="confirmResetBaiduProfile">
                    <Icon name="trash" :size="12" />
                    <span>重置</span>
                  </Btn>
                </SettingsRow>
              </div>
            </div>
            <!--
              Cookie 池入口的位置：之前作为 monitor section 最后一行；按用户
              要求"是比较重要且常用的选项"——已在模板开头（SettingsRow 列表
              顶部）单独渲染了一份，这里的旧 last-row 删除。
            -->
          </template>

          <!-- ━━━━━━━━ 百度抓取 ━━━━━━━━ -->
          <!--
            Native Chrome profile 模式配置。自有独立组件 BaiduScrapeSettings，
            内部直接访问后端 5 个 API routes（Task 7）。
          -->
          <template v-else-if="section === 'baidu-scrape'">
            <BaiduScrapeSettings />
          </template>

          <!-- ━━━━━━━━ 评论模板库 ━━━━━━━━ -->
          <template v-else-if="section === 'templates'">
            <TemplateLibrarySection />
          </template>

          <!-- ━━━━━━━━ 账号 ━━━━━━━━ -->
          <!--
            「工作空间 / 同步状态」两行移除 —— 当前没有真正的云端账号
            体系，二者都是 UI 占位。账号卡片的「编辑」按钮打开弹窗，
            可以改用户名 + 负责产品线（后者是新字段，PATCH 接口透传）。
          -->
          <template v-else-if="section === 'account'">
            <div
              class="flex items-center gap-4 p-4"
              :style="{
                background: 'var(--card-2)',
                border: '1px solid var(--line)',
                borderRadius: '14px',
              }"
            >
              <span
                class="inline-flex items-center justify-center font-bold"
                :style="{
                  width: '48px',
                  height: '48px',
                  borderRadius: '50%',
                  background: 'var(--dark)',
                  color: 'var(--primary)',
                  fontSize: '18px',
                }"
                >{{ (get("user_name") || "U").slice(0, 1).toUpperCase() }}</span
              >
              <div class="flex-1">
                <div class="text-[15px] font-semibold">
                  {{ get("user_name") || "未命名用户" }}
                </div>
                <div class="text-[11.5px]" :style="{ color: 'var(--ink-3)' }">
                  {{ get("user_product") ? `负责产品线：${get("user_product")}` : "本地用户 · 个人版" }}
                </div>
              </div>
              <Pill tone="ok">活跃</Pill>
              <Btn variant="ghost" small @click="openAccountEdit">
                <Icon name="edit" :size="13" />
                <span>编辑</span>
              </Btn>
            </div>
            <SettingsRow
              label="导出账号数据"
              hint="所有设置、Skill、模板，打包为 zip"
              last
            >
              <Btn variant="ghost" small disabled>
                <Icon name="download" :size="13" />
                <span>导出</span>
              </Btn>
            </SettingsRow>
          </template>

          <!-- ━━━━━━━━ 关于 ━━━━━━━━ -->
          <template v-else-if="section === 'about'">
            <div class="mb-4 flex items-center gap-4">
              <img
                :src="logoUrl"
                alt="Content SEO Maker"
                :style="{
                  width: '56px',
                  height: '56px',
                  borderRadius: '16px',
                  objectFit: 'contain',
                  display: 'block',
                }"
              />
              <div>
                <div
                  class="font-display font-bold"
                  :style="{ fontSize: '22px' }"
                >
                  Content SEO Maker
                </div>
                <div class="text-[12px]" :style="{ color: 'var(--ink-3)' }">
                  v {{ appVersion }} · Tauri + Vue 3 + FastAPI sidecar
                </div>
              </div>
            </div>
            <!--
              更新仓库已固定（参见 csm_sidecar 内置 release URL），
              不再让用户自填；官方文档 / 许可证两行也不需要在设置面板里
              占位。「检查更新」按钮保留 —— 这是用户主动触发一次升级
              检查的唯一入口。
            -->
            <SettingsRow label="检查更新" hint="手动触发一次更新检查" last>
              <Btn
                variant="ghost"
                small
                :disabled="updaterChecking"
                @click="checkForUpdate"
              >
                <Spinner v-if="updaterChecking" :size="12" />
                <Icon v-else name="refresh" :size="13" />
                <span>{{ updaterChecking ? "检查中…" : "检查" }}</span>
              </Btn>
            </SettingsRow>
          </template>
        </div>
      </Card>
    </div>

    <!--
      Cookie 池管理器（监测 section 触发）。Teleport 到 body 是组件自己
      做的，这里只要保证组件被实例化就行。
    -->
    <CookieManagerModal v-model:open="cookieMgrOpen" />

    <!-- 通知设置弹窗（通用 section 触发，按分类勾选）-->
    <NotificationPrefsModal v-model:open="notifPrefsOpen" />

    <!--
      百度全局排除域名管理弹窗 —— 跟 AddTaskModal 同款的 header/body/footer
      三段式：header + 滚动 body + 固定 footer，rounded-card 圆角下 overflow
      不溢出。draft 模型让用户连续敲不会触发 PATCH，点保存才一次落盘。
    -->
    <Teleport to="body">
      <div
        v-if="excludeDomainsModalOpen"
        class="fixed inset-0 z-40 flex items-center justify-center"
        :style="{ background: 'rgba(28,26,23,0.4)' }"
        @click.self="excludeDomainsModalOpen = false"
      >
        <div
          class="anim-up bg-bg-inner flex flex-col overflow-hidden"
          :style="{
            width: '480px',
            maxWidth: '92vw',
            height: '70vh',
            maxHeight: '80vh',
            minHeight: '420px',
            borderRadius: 'var(--radius-card)',
            border: '1px solid var(--line)',
          }"
        >
          <div class="flex flex-shrink-0 items-center justify-between" :style="{ padding: '20px 24px 12px' }">
            <div>
              <div class="font-display text-[16px] font-semibold">管理排除域名</div>
              <div class="mt-1 text-[11.5px]" :style="{ color: 'var(--ink-3)' }">
                所有百度任务默认应用；一行一个 host pattern（不带协议头）。
              </div>
            </div>
            <button type="button" @click="excludeDomainsModalOpen = false">
              <Icon name="x" :size="18" />
            </button>
          </div>
          <div class="flex min-h-0 flex-1 flex-col" :style="{ padding: '4px 24px' }">
            <!--
              用户反馈：textarea 太小（之前 modal 无 height，flex-1 没空间撑开）。
              对外 modal 加 height: 70vh / minHeight: 420px 给容器一个明确高度，
              然后 textarea 走 flex-1 自然占满。同时给 textarea 兜 min-height
              以防极小窗口下塌成一行。
            -->
            <textarea
              v-model="excludeDomainsDraftRaw"
              class="bg-card-white px-3 py-2 text-[12.5px] outline-none flex-1 min-h-0"
              placeholder="jd.com&#10;taobao.com&#10;1688.com&#10;cewey.com"
              :style="{
                width: '100%',
                minHeight: '220px',
                borderRadius: '10px',
                border: '1px solid var(--line)',
                fontFamily: 'ui-monospace, SF Mono, Menlo, Consolas, monospace',
                resize: 'none',
                color: 'var(--ink)',
              }"
            />
            <div class="mt-2 text-[11px]" :style="{ color: 'var(--ink-3)' }">
              规则：host 后缀匹配 —— <code>jd.com</code> 同时命中 <code>www.jd.com</code> / <code>mall.jd.com</code>。
              支持换行 / 逗号 / 空格分隔；保存时自动剥协议头和尾斜杠。
            </div>
          </div>
          <div class="flex flex-shrink-0 justify-end gap-2" :style="{ padding: '12px 24px 20px', borderTop: '1px solid var(--line)' }">
            <Btn variant="ghost" small @click="excludeDomainsModalOpen = false">取消</Btn>
            <Btn variant="solid" small @click="saveExcludeDomains">保存</Btn>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- 账号编辑弹窗 -->
    <Teleport to="body">
      <div
        v-if="accountEditOpen"
        class="fixed inset-0 z-50 flex items-center justify-center bg-black/30"
        @click.self="accountEditOpen = false"
      >
        <div
          class="anim-up bg-bg-inner flex flex-col p-6"
          :style="{
            width: '420px',
            maxWidth: '92vw',
            borderRadius: 'var(--radius-card)',
            boxShadow: '0 16px 48px rgba(0,0,0,0.18)',
          }"
        >
          <div class="mb-4 flex items-center justify-between">
            <div class="font-display text-[15px] font-semibold">编辑账号</div>
            <button type="button" @click="accountEditOpen = false">
              <Icon name="x" :size="16" />
            </button>
          </div>
          <div class="flex flex-col gap-3">
            <div>
              <div class="mb-1 text-[12px] font-medium">账号名称</div>
              <FormInput v-model="accountEditDraft.user_name" placeholder="例如 Uzui" debounce="live" />
            </div>
            <div>
              <div class="mb-1 text-[12px] font-medium">负责产品线</div>
              <FormInput
                v-model="accountEditDraft.user_product"
                placeholder="例如 内容引擎 · 知乎组"
                debounce="live"
              />
            </div>
          </div>
          <div class="mt-5 flex justify-end gap-2">
            <Btn variant="ghost" small @click="accountEditOpen = false">取消</Btn>
            <Btn variant="solid" small @click="saveAccountEdit">保存</Btn>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

