<script setup lang="ts">
/**
 * Skill 编辑/新建 独立页 —— 参考 TemplateBuilder 顶部 toolbar 设计，把字段
 * 全部塞到 header（名称 / 一句话描述 / 语气标签），下面整个区块就是
 * Prompt 正文编辑区。
 *
 * 用户指令：
 *   - 「新建SKILL 不显示 ID 这项」—— ID FormField 整段删除。create 模式下
 *     用 skillName 同时作为 id + name 提交（保留 validateName 的文件系统
 *     非法字符检查）。
 *   - 「参考模板库的顶部区块设计」—— 跟 TemplateBuilder header 同款的
 *     Card：返回 + 取消 + 保存 一行，下面 3 列 FormField 网格。
 *   - 「下面整个区块就是正文区域」—— 第二张 Card 整张是 Prompt 正文
 *     textarea，flex-1 撑满剩余高度。
 *
 * 原来的 3-step 创建向导（基础 / 风格 / 预览）和 PRESETS / buildSkeleton
 * 全部下线 —— 单一表单不适合塞向导。"起始模板"预设逻辑暂时丢失；
 * 用户要的话可后续加个「插入模板」下拉到正文 textarea 上方。
 */
import { computed, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";

import Btn from "@/components/ui/Btn.vue";
import Card from "@/components/ui/Card.vue";
import Icon from "@/components/ui/Icon.vue";
import Spinner from "@/components/ui/Spinner.vue";
import FormField from "@/components/forms/FormField.vue";
import FormInput from "@/components/forms/FormInput.vue";
import FormSelect from "@/components/forms/FormSelect.vue";

import { useSidecar } from "@/stores/sidecar";
import { useToast } from "@/composables/useToast";

const route = useRoute();
const router = useRouter();
const sidecar = useSidecar();
const toast = useToast();

const skillId = computed<string | null>(() => {
  const raw = route.params.id;
  const id = Array.isArray(raw) ? raw[0] : raw;
  if (!id || id === "new") return null;
  return id;
});

const mode = computed<"create" | "edit">(() => (skillId.value ? "edit" : "create"));

// ── State —— 单表单字段（create + edit 共用）─────────────
const name = ref("");
const desc = ref("");
const tone = ref("");
const role = ref("persona");
const body = ref("");

const loading = ref(false);
const saving = ref(false);

async function loadDetail(sid: string) {
  loading.value = true;
  try {
    const r = await sidecar.client.get(`/api/skills/${sid}`);
    name.value = r.data.name ?? sid;
    desc.value = r.data.desc ?? "";
    tone.value = r.data.tone ?? "";
    role.value = r.data.role ?? "persona";
    body.value = r.data.body ?? "";
  } catch (e: any) {
    toast.error(`Skill 加载失败：${e?.response?.data?.detail ?? e?.message ?? e}`);
    backToList();
  } finally {
    loading.value = false;
  }
}

onMounted(() => {
  if (skillId.value) loadDetail(skillId.value);
});

function backToList(savedId?: string) {
  router.push({
    name: "templates",
    query: {
      tab: "skills",
      ...(savedId ? { highlight: savedId } : {}),
    },
  });
}

// 名称 = 文件名 ID（create 模式）。Windows + POSIX 都禁的字符集放这里
// 拒掉，避免后端写文件失败时再 toast。
function validateName(s: string): string | null {
  const n = s.trim();
  if (!n) return "名称不能为空";
  if (/[\\/:*?"<>|\x00-\x1f]/.test(n)) {
    return "名称含有非法字符（不能包含 \\ / : * ? \" < > |）";
  }
  return null;
}

async function saveCreate() {
  const err = validateName(name.value);
  if (err) {
    toast.warn(err);
    return;
  }
  saving.value = true;
  try {
    const trimmed = name.value.trim();
    const r = await sidecar.client.post("/api/skills", {
      // create 模式下 id = name —— ID FormField 按用户要求已删，name 直接
      // 兼任文件名。后续 PATCH 用 route param 里的 id（不可变）。
      id: trimmed,
      name: trimmed,
      desc: desc.value.trim(),
      tone: tone.value.trim(),
      role: role.value,
      body: body.value,
    });
    toast.success(`已创建 Skill：${r.data.name ?? r.data.id}`);
    backToList(r.data.id);
  } catch (e: any) {
    toast.error(`创建失败：${e?.response?.data?.detail ?? e?.message ?? e}`);
  } finally {
    saving.value = false;
  }
}

async function saveEdit() {
  const err = validateName(name.value);
  if (err) {
    toast.warn(err);
    return;
  }
  saving.value = true;
  try {
    const sid = skillId.value!;
    const r = await sidecar.client.patch(`/api/skills/${sid}`, {
      name: name.value.trim(),
      desc: desc.value.trim(),
      tone: tone.value.trim(),
      role: role.value,
      body: body.value,
    });
    toast.success(`已保存：${r.data.name ?? sid}`);
    backToList(sid);
  } catch (e: any) {
    toast.error(`保存失败：${e?.response?.data?.detail ?? e?.message ?? e}`);
  } finally {
    saving.value = false;
  }
}

function save() {
  if (mode.value === "create") saveCreate();
  else saveEdit();
}
</script>

<template>
  <!--
    h-full + flex-col + gap-d —— 跟 TemplateBuilder 顶级容器同款，让 header
    Card flex-shrink-0，body Card 拿剩余高度。
  -->
  <div class="flex h-full flex-col gap-d">
    <!-- ── Header Card：返回 + 操作 + 3 字段 ────────────────────── -->
    <Card class="flex-shrink-0">
      <div class="mb-3 flex items-center justify-between">
        <button
          type="button"
          class="inline-flex items-center gap-1.5 text-[12px]"
          :style="{ color: 'var(--ink-3)' }"
          @click="backToList()"
        >
          <Icon name="arrowLeft" :size="14" />
          返回模板库
        </button>
        <div class="flex gap-2">
          <Btn variant="ghost" small :disabled="saving" @click="backToList()">取消</Btn>
          <Btn variant="solid" small :disabled="saving" @click="save">
            <Spinner v-if="saving" :size="12" />
            <Icon v-else name="check" :size="13" />
            <span>{{ saving ? "保存中…" : mode === "create" ? "创建" : "保存" }}</span>
          </Btn>
        </div>
      </div>

      <!--
        4 列字段：名称 / 一句话描述 / 语气标签 / 角色。lg 上等宽分布，
        跟 TemplateBuilder header 的 4 列网格逻辑一致（grid-cols-1 在窄屏
        堆叠，lg:grid-cols-4 在宽屏并排）。
      -->
      <div class="grid grid-cols-1 gap-3 lg:grid-cols-4">
        <FormField label="名称">
          <FormInput
            v-model="name"
            placeholder="如 家电科普博主"
            :disabled="mode === 'edit'"
            debounce="live"
          />
        </FormField>
        <FormField label="一句话描述">
          <FormInput
            v-model="desc"
            placeholder="如 极度克制 · 不超过 1 个感叹号"
            debounce="live"
          />
        </FormField>
        <FormField label="语气标签">
          <FormInput
            v-model="tone"
            placeholder="如 克制 / 真实 / 温柔"
            debounce="live"
          />
        </FormField>
        <FormField label="角色">
          <FormSelect
            v-model="role"
            :options="[
              { label: '人设（persona）', value: 'persona' },
              { label: '去AI味（humanize）', value: 'humanize' },
              { label: '平台适配（platform）', value: 'platform' },
            ]"
            width="100%"
          />
        </FormField>
      </div>
    </Card>

    <!-- ── Loading state ──────────────────────────────────────────── -->
    <Card v-if="loading" class="flex-shrink-0">
      <div class="flex items-center gap-2 text-ink-3">
        <Spinner :size="14" /><span>载入中…</span>
      </div>
    </Card>

    <!--
      ── Body Card：Prompt 正文 textarea ──
      整张卡就是一个 Markdown 编辑区。flex-1 + min-h-0 让它占满剩余高度，
      内层 textarea height: 100% + resize: none 把可编辑区域撑满整张卡。
      不再用 FormField 包裹 —— label 已经在卡顶部说清楚了。
    -->
    <Card v-else class="flex min-h-0 flex-1 flex-col">
      <div
        class="mb-2 flex flex-shrink-0 items-center justify-between"
      >
        <div class="font-display text-[12.5px] font-semibold">Prompt 正文（Markdown）</div>
        <div class="text-[10.5px]" :style="{ color: 'var(--ink-4)' }">
          这部分会拼到生成请求的 user_skill_prompt 里
        </div>
      </div>
      <textarea
        v-model="body"
        class="bg-card-2 px-3 py-2 font-mono text-[12.5px] outline-none transition-colors focus:bg-card-white"
        :style="{
          width: '100%',
          flex: 1,
          minHeight: 0,
          borderRadius: 'var(--radius-inner)',
          border: '1px solid var(--line)',
          resize: 'none',
          lineHeight: 1.7,
        }"
        placeholder="# 你的 Skill 名

你是一位 XX 品类的编辑。收到毛坯文后按下面规则进行**润色改写**。

## 风格约束
- 开头钩子：...
- 段落密度：...
- 语气：...

## 禁止项
- ...

## 输出
直接输出润色后的完整正文 Markdown。"
      />
    </Card>
  </div>
</template>
