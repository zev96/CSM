<script setup lang="ts">
/**
 * First-launch onboarding — a full-screen overlay shown when the user
 * hasn't completed the welcome flow yet.
 *
 * Detection:
 *   - cfg.data.user_name is empty AND
 *   - localStorage flag `csm.onboarded.v1` is unset
 * Both must hold; setting either one ends the flow. The flag protects
 * users who skipped the welcome step but still want to dismiss this on
 * future launches — without it, an empty name would re-trigger forever.
 *
 * State machine — `step` ∈ { "welcome" | "vault" | "model" | "skill" }:
 *
 *   welcome → vault → model → skill → done (→ home)
 *
 * Each step can also "skip" (advance without saving its inputs), and
 * vault/model/skill can also "back" (go to previous step). The first
 * welcome screen is treated as gating — the user has to either type a
 * name + click → OR localStorage will keep showing this. Hard-skipping
 * welcome would defeat the point.
 *
 * Side effects on advance:
 *   - welcome: cfg.patch({ user_name, user_product })
 *   - vault:   cfg.patch({ vault_root })
 *   - model:   keyringSet(provider, key) per filled provider
 *              + cfg.patch({ default_provider }) if exactly one was added
 *   - skill:   cfg.patch({ default_skill_preset })  // new field, server
 *              dict-merges, no migration needed.
 *
 * Done = emit("done") so the parent (App.vue) unmounts this overlay.
 */
import { onMounted, reactive, ref } from "vue";

import Btn from "@/components/ui/Btn.vue";
import Icon from "@/components/ui/Icon.vue";
import Spinner from "@/components/ui/Spinner.vue";
import FormInput from "@/components/forms/FormInput.vue";
import logoUrl from "@/assets/logo.png";
import { useConfig } from "@/stores/config";
import { useToast } from "@/composables/useToast";
import { usePathPicker } from "@/composables/usePathPicker";
import { getVersion, keyringSet } from "@/api/client";

const emit = defineEmits<{ (e: "done"): void }>();

const cfg = useConfig();
const toast = useToast();
const { pick } = usePathPicker();

// 跟 SettingsView 一致：从 sidecar 实时读版本号，避免常量过期。
const appVersion = ref("…");
onMounted(async () => {
  try {
    const r = await getVersion();
    appVersion.value = r.sidecar;
  } catch {
    appVersion.value = "?";
  }
});

const STORAGE_KEY = "csm.onboarded.v1";

type Step = "welcome" | "vault" | "model" | "skill";
const step = ref<Step>("welcome");

// ── Step state ──────────────────────────────────────────────────
const welcomeForm = reactive({ name: "", productLine: "" });

const vaultPath = ref<string>("");

interface ProviderEntry {
  key: "anthropic" | "deepseek" | "openai";
  label: string;
  letter: string;
  dot: string;
  draftKey: string;
  saved: boolean;
}
const providers = reactive<ProviderEntry[]>([
  { key: "anthropic", label: "Anthropic", letter: "A", dot: "#c96442", draftKey: "", saved: false },
  { key: "deepseek", label: "DeepSeek", letter: "D", dot: "#4a8aa8", draftKey: "", saved: false },
  { key: "openai", label: "OpenAI", letter: "O", dot: "#7a9b5e", draftKey: "", saved: false },
]);
const expandedProvider = ref<string | null>(null);

// 4 个 Skill preset 选项 —— 这里写死，因为 onboarding 是 "出厂选项"，
// 不该被用户自定义的 Skill 库影响（用户库可能空着）。下游用 cfg.patch
// 把选中 key 写到 default_skill_preset，文章生成时优先读这个字段。
interface SkillOption {
  key: string;
  label: string;
  hint: string;
}
const skillOptions: SkillOption[] = [
  { key: "kezhi", label: "克制·克制", hint: "去口语化、收口紧、避免感叹号" },
  { key: "ceping", label: "测评·真心话", hint: "第一人称、长期视角、给反例" },
  { key: "muying", label: "母婴·温柔", hint: "重视安全合规话术、案例化" },
  { key: "jijian", label: "极简·短句", hint: "句子<18 字、动词开头、删形容词" },
];
const chosenSkill = ref<string>("");

// 各步的处理逻辑 —— 都设计成失败不阻塞前进：网络抖一下不能让用户
// 卡在 onboarding，永远进不来主界面。
//
// welcomeSubmitting 在 patch 期间为 true；按钮显示 spinner 并 disable，
// 防止用户连点 + 让用户知道"程序在干活、不是卡死"。这是 v0.4.2 装好
// 后用户反馈的 bug —— 第一次冷启动 sidecar 慢，patch 要好几秒，按钮
// 又是个无标签小箭头，用户以为没反应就 force-quit 了。
const welcomeSubmitting = ref(false);
async function submitWelcome() {
  if (welcomeSubmitting.value) return;
  if (!welcomeForm.name.trim()) {
    toast.warn("请先输入姓名");
    return;
  }
  welcomeSubmitting.value = true;
  try {
    try {
      // ⚠ 字段名必须跟后端 AppConfig 对齐 —— Pydantic 默认 extra="ignore"
      //   会静默丢弃不认识的 key（之前 product_line 就这样被吃了）
      await cfg.patch({
        user_name: welcomeForm.name.trim(),
        user_product: welcomeForm.productLine.trim(),
      });
    } catch (e: any) {
      // 之前这里"保存失败仍然推进"导致一个静默 bug：sidecar 启动慢时
      // patch 503 但 step 还是跳走了，用户以为名字存了实际没存，最后
      // Settings 里只看到"未命名用户"。改成 hard-block：必须保存成功
      // 才推进，让用户重试 / 等 sidecar 起来。
      toast.error(`保存失败：${e?.response?.data?.detail ?? e?.message ?? e}`);
      return;
    }
    // 二次校验：再从 cfg.data 里读一次，确认确实写进去了。极端情况
    // patch 没抛但 data 没更新（store 实现的隐藏失败路径），这里能拦下。
    if (!(cfg.data?.user_name as string | undefined)?.trim()) {
      toast.error("保存失败：服务端未确认。请稍后重试。");
      return;
    }
    step.value = "vault";
  } finally {
    welcomeSubmitting.value = false;
  }
}

async function pickVault() {
  const v = await pick({ title: "选择 Obsidian Vault", directory: true });
  if (v) vaultPath.value = v;
}

async function submitVault() {
  if (vaultPath.value.trim()) {
    try {
      await cfg.patch({ vault_root: vaultPath.value.trim() });
    } catch (e: any) {
      toast.error(`保存失败：${e?.message ?? e}`);
    }
  }
  step.value = "model";
}

async function saveProviderKey(p: ProviderEntry) {
  const raw = p.draftKey.trim();
  if (!raw) {
    toast.warn(`${p.label}：请先粘贴 API Key`);
    return;
  }
  try {
    await keyringSet(p.key, raw);
    p.saved = true;
    p.draftKey = "";
    expandedProvider.value = null;
    toast.success(`${p.label} 密钥已保存`);
  } catch (e: any) {
    toast.error(`保存失败：${e?.message ?? e}`);
  }
}

async function submitModel() {
  const saved = providers.filter((p) => p.saved);
  // 只配了一个 provider 就自动设为默认，省一次切换；多个/零个不动。
  if (saved.length === 1) {
    try {
      await cfg.patch({ default_provider: saved[0].key });
    } catch {
      /* swallow — non-critical, user can switch in Settings later */
    }
  }
  step.value = "skill";
}

async function submitSkill() {
  if (chosenSkill.value) {
    try {
      await cfg.patch({ default_skill_preset: chosenSkill.value });
    } catch (e: any) {
      toast.error(`保存失败：${e?.message ?? e}`);
    }
  }
  finish();
}

function skip() {
  // 跳过当前步直接进下一步；不写任何配置。
  if (step.value === "welcome") {
    toast.warn("姓名是必填项，请先填写");
    return;
  }
  if (step.value === "vault") step.value = "model";
  else if (step.value === "model") step.value = "skill";
  else if (step.value === "skill") finish();
}

function back() {
  if (step.value === "model") step.value = "vault";
  else if (step.value === "skill") step.value = "model";
}

function finish() {
  // 不管走哪条路（保存 / 跳过），落地一个本地标记，下次启动不会重弹。
  try {
    localStorage.setItem(STORAGE_KEY, "1");
  } catch {
    /* private-mode browsers — best effort */
  }
  emit("done");
}

// 用于步骤进度点：3 步骤总数（vault/model/skill 是 1/3、2/3、3/3）。
function stepIndex(): number {
  if (step.value === "vault") return 0;
  if (step.value === "model") return 1;
  if (step.value === "skill") return 2;
  return -1;
}
</script>

<template>
  <Teleport to="body">
    <div
      class="fixed inset-0 z-[100] flex items-center justify-center overflow-y-auto"
      :style="{
        background: 'var(--bg-inner)',
        padding: '40px 20px',
      }"
    >
      <!-- ── Welcome (姓名 + 产品线) ──────────────────────────── -->
      <div
        v-if="step === 'welcome'"
        class="flex w-full max-w-[480px] flex-col items-center text-center"
      >
        <img
          :src="logoUrl"
          alt="CSM"
          :style="{ width: '40px', height: '40px', borderRadius: '12px', marginBottom: '32px' }"
        />
        <div
          class="text-[11px] uppercase"
          :style="{ letterSpacing: '2px', color: 'var(--ink-3)' }"
        >
          WELCOME
        </div>
        <div
          class="font-display mt-3 font-bold"
          :style="{ fontSize: '32px', lineHeight: '1.2', letterSpacing: '-0.5px' }"
        >
          你的内容工作台，<br />从这里开始。
        </div>
        <div
          class="mt-3 text-[12.5px]"
          :style="{ color: 'var(--ink-3)' }"
        >
          先让 CSM 认识你 —— 名字会出现在工作台问候里，产品线用于文档分类。
        </div>

        <!--
          form 包裹 + @submit.prevent 让 Enter 键也能触发提交（之前只能
          点按钮、键盘用户没法走完欢迎页）。type="submit" 的按钮才能
          被表单 submit 事件接住。
        -->
        <form
          class="mt-8 flex w-full flex-col gap-4"
          @submit.prevent="submitWelcome"
        >
          <div>
            <div class="mb-1.5 text-center text-[12.5px] font-semibold">姓名</div>
            <FormInput
              v-model="welcomeForm.name"
              placeholder="如：小王、Wang Xi"
              debounce="live"
            />
          </div>
          <div>
            <div class="mb-1.5 text-center text-[12.5px] font-semibold">
              负责产品线
              <span :style="{ color: 'var(--ink-3)', fontWeight: 400 }">（选填）</span>
            </div>
            <FormInput
              v-model="welcomeForm.productLine"
              placeholder="如：吸尘器、投影仪"
              debounce="live"
            />
          </div>

          <!--
            按钮带文字 + spinner。之前是 46px 圆圈只有箭头，没人意识到
            那是按钮 + sidecar 冷启动慢时按了没反馈，用户以为卡死。
            disabled 状态让 Btn 自带的 :disabled="true" 样式生效。
          -->
          <Btn
            type="submit"
            variant="solid"
            class="mt-2 self-center"
            :disabled="welcomeSubmitting || !welcomeForm.name.trim()"
            @click="submitWelcome"
          >
            <Spinner v-if="welcomeSubmitting" :size="14" />
            <span>{{ welcomeSubmitting ? "正在保存…" : "下一步" }}</span>
            <Icon v-if="!welcomeSubmitting" name="arrowRight" :size="14" />
          </Btn>
        </form>

        <div
          class="mt-8 text-[11px]"
          :style="{ color: 'var(--ink-4)', letterSpacing: '0.5px' }"
        >
          V {{ appVersion }} · 本地版本 · 数据仅保存在你电脑上
        </div>
      </div>

      <!-- ── 步骤卡（vault / model / skill 共享外壳）─────────────── -->
      <div
        v-else
        class="relative flex w-full max-w-[680px] flex-col overflow-hidden"
        :style="{
          background: 'var(--card-2)',
          borderRadius: '24px',
          padding: '36px 40px 28px',
          border: '1px solid var(--line)',
          boxShadow: '0 24px 64px rgba(0,0,0,0.10)',
        }"
      >
        <!-- 装饰 blob —— 暖橙径向，跟主界面 hero blob 同源 -->
        <div
          aria-hidden="true"
          :style="{
            position: 'absolute',
            top: '-80px',
            right: '-60px',
            width: '320px',
            height: '320px',
            background: 'radial-gradient(circle, rgba(238,106,42,0.18), transparent 70%)',
            filter: 'blur(20px)',
            pointerEvents: 'none',
            zIndex: 0,
          }"
        />

        <div class="relative" :style="{ zIndex: 1 }">
          <!-- 进度条 — 3 个段，当前段亮 primary、已过段也亮 primary 但更深 -->
          <div class="mb-6 flex items-center gap-2">
            <div
              v-for="(_, i) in [0, 1, 2]"
              :key="i"
              :style="{
                height: '4px',
                flex: i === stepIndex() ? '2 1 0' : '1 1 0',
                background:
                  i < stepIndex()
                    ? 'var(--primary)'
                    : i === stepIndex()
                      ? 'var(--primary)'
                      : 'var(--line)',
                borderRadius: '999px',
                opacity: i === stepIndex() ? 1 : i < stepIndex() ? 0.5 : 1,
              }"
            />
            <span
              class="ml-2 text-[11.5px]"
              :style="{ color: 'var(--ink-3)' }"
            >第 {{ stepIndex() + 1 }} / 3 步</span>
          </div>

          <div
            class="text-[11.5px]"
            :style="{ color: 'var(--ink-3)', letterSpacing: '0.5px' }"
          >
            欢迎使用 CSM
          </div>

          <!-- ── 步骤 1：选 Vault ──────────────────────── -->
          <template v-if="step === 'vault'">
            <div
              class="font-display mt-2 font-bold"
              :style="{ fontSize: '24px', letterSpacing: '-0.5px' }"
            >
              选择你的素材库
            </div>
            <div
              class="mt-2 text-[12.5px]"
              :style="{ color: 'var(--ink-3)' }"
            >
              CSM 会从这个 Obsidian Vault 里读笔记，作为文章的素材源。
            </div>

            <div
              class="mt-6 flex items-center gap-3 p-4"
              :style="{
                background: 'var(--card-white)',
                border: '1px solid var(--line)',
                borderRadius: 'var(--radius-inner)',
              }"
            >
              <span
                class="inline-flex items-center justify-center"
                :style="{
                  width: '40px',
                  height: '40px',
                  borderRadius: '10px',
                  background: 'var(--dark)',
                  color: 'var(--primary)',
                }"
              >
                <Icon name="folder" :size="18" />
              </span>
              <div class="min-w-0 flex-1">
                <div class="text-[13px] font-semibold">
                  {{ vaultPath ? "已选择 Vault" : "尚未选择 Vault" }}
                </div>
                <div
                  class="font-mono mt-0.5 truncate text-[11px]"
                  :style="{ color: 'var(--ink-3)' }"
                >
                  {{ vaultPath || "建议挑一个已有笔记 30+ 篇的 Vault 起步" }}
                </div>
              </div>
              <Btn variant="ghost" small @click="pickVault">
                <Icon name="folder" :size="13" />
                <span>选择…</span>
              </Btn>
            </div>

            <div class="mt-8 flex items-center justify-end gap-2">
              <Btn variant="ghost" small @click="skip">跳过</Btn>
              <Btn variant="solid" small @click="submitVault">
                <Icon name="arrowRight" :size="13" />
                <span>选择 Vault 文件夹</span>
              </Btn>
            </div>
          </template>

          <!-- ── 步骤 2：接入模型 ──────────────────────── -->
          <template v-else-if="step === 'model'">
            <div
              class="font-display mt-2 font-bold"
              :style="{ fontSize: '24px', letterSpacing: '-0.5px' }"
            >
              接入一个模型
            </div>
            <div
              class="mt-2 text-[12.5px]"
              :style="{ color: 'var(--ink-3)' }"
            >
              至少配置一个：Anthropic / DeepSeek / OpenAI。Key 只保存在本地。
            </div>

            <div
              class="mt-6 grid grid-cols-3 gap-3 p-3"
              :style="{
                background: 'var(--card-white)',
                border: '1px solid var(--line)',
                borderRadius: 'var(--radius-inner)',
              }"
            >
              <div
                v-for="p in providers"
                :key="p.key"
                class="flex items-center gap-2 p-2"
                :style="{
                  background: 'var(--card-2)',
                  border: '1px solid var(--line)',
                  borderRadius: '12px',
                }"
              >
                <span
                  class="inline-flex items-center justify-center font-bold"
                  :style="{
                    width: '28px',
                    height: '28px',
                    borderRadius: '8px',
                    background: p.dot,
                    color: '#fff',
                    fontSize: '12px',
                  }"
                  >{{ p.letter }}</span
                >
                <span class="flex-1 truncate text-[13px] font-semibold">{{ p.label }}</span>
                <button
                  v-if="!p.saved"
                  type="button"
                  class="inline-flex items-center justify-center"
                  :title="`添加 ${p.label} API Key`"
                  :style="{
                    width: '22px',
                    height: '22px',
                    borderRadius: '999px',
                    background: 'transparent',
                    color: 'var(--ink-2)',
                    cursor: 'pointer',
                    border: '1px solid var(--line)',
                  }"
                  @click="expandedProvider = expandedProvider === p.key ? null : p.key"
                >
                  <Icon name="plus" :size="12" />
                </button>
                <Icon
                  v-else
                  name="check"
                  :size="14"
                  :style="{ color: 'var(--primary)' }"
                />
              </div>
            </div>

            <!-- 展开行：当前点开的 provider 的 API Key 输入 + 保存 -->
            <div
              v-if="expandedProvider"
              class="mt-3 flex items-center gap-2 p-3"
              :style="{
                background: 'var(--card-white)',
                border: '1px solid var(--line)',
                borderRadius: 'var(--radius-inner)',
              }"
            >
              <span class="text-[12px]" :style="{ color: 'var(--ink-3)' }">
                {{ providers.find((p) => p.key === expandedProvider)?.label }} Key
              </span>
              <input
                v-model="providers.find((p) => p.key === expandedProvider)!.draftKey"
                type="password"
                placeholder="粘贴 API Key…"
                class="font-mono min-w-0 flex-1 px-2.5 outline-none"
                :style="{
                  height: '32px',
                  borderRadius: '8px',
                  background: 'var(--card-2)',
                  border: '1px solid var(--line)',
                  fontSize: '11.5px',
                  color: 'var(--ink-2)',
                }"
              />
              <Btn
                variant="solid"
                small
                @click="saveProviderKey(providers.find((p) => p.key === expandedProvider)!)"
              >
                保存
              </Btn>
            </div>

            <div class="mt-8 flex items-center justify-between gap-2">
              <button
                type="button"
                class="text-[12px]"
                :style="{ color: 'var(--ink-3)', background: 'transparent' }"
                @click="back"
              >
                ← 上一步
              </button>
              <div class="flex gap-2">
                <Btn variant="ghost" small @click="skip">跳过</Btn>
                <Btn variant="solid" small @click="submitModel">
                  <Icon name="arrowRight" :size="13" />
                  <span>添加 API Key</span>
                </Btn>
              </div>
            </div>
          </template>

          <!-- ── 步骤 3：写作风格 ──────────────────────── -->
          <template v-else-if="step === 'skill'">
            <div
              class="font-display mt-2 font-bold"
              :style="{ fontSize: '24px', letterSpacing: '-0.5px' }"
            >
              选一种写作风格
            </div>
            <div
              class="mt-2 text-[12.5px]"
              :style="{ color: 'var(--ink-3)' }"
            >
              Skill 决定语气与收口 —— 选一个起步，之后随时改。
            </div>

            <div
              class="mt-6 grid grid-cols-3 gap-3 p-3"
              :style="{
                background: 'var(--card-white)',
                border: '1px solid var(--line)',
                borderRadius: 'var(--radius-inner)',
              }"
            >
              <button
                v-for="s in skillOptions"
                :key="s.key"
                type="button"
                class="text-left transition"
                :style="{
                  padding: '14px',
                  borderRadius: '12px',
                  background:
                    chosenSkill === s.key ? 'var(--primary-soft)' : 'var(--card-2)',
                  border:
                    chosenSkill === s.key
                      ? '2px solid var(--primary)'
                      : '1px solid var(--line)',
                  cursor: 'pointer',
                }"
                @click="chosenSkill = s.key"
              >
                <div
                  class="text-[13px] font-bold"
                  :style="{
                    color:
                      chosenSkill === s.key ? 'var(--primary-deep)' : 'var(--ink)',
                  }"
                >
                  {{ s.label }}
                </div>
                <div
                  class="mt-1.5 text-[11px] leading-relaxed"
                  :style="{ color: 'var(--ink-3)' }"
                >
                  {{ s.hint }}
                </div>
              </button>
            </div>

            <div class="mt-8 flex items-center justify-between gap-2">
              <button
                type="button"
                class="text-[12px]"
                :style="{ color: 'var(--ink-3)', background: 'transparent' }"
                @click="back"
              >
                ← 上一步
              </button>
              <div class="flex gap-2">
                <Btn variant="ghost" small @click="skip">跳过</Btn>
                <Btn variant="solid" small @click="submitSkill">
                  <Icon name="arrowRight" :size="13" />
                  <span>完成设置</span>
                </Btn>
              </div>
            </div>
          </template>
        </div>
      </div>
    </div>
  </Teleport>
</template>
