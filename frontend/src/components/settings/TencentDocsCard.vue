<script setup lang="ts">
/**
 * 腾讯文档同步设置卡（评论工作流 P3）。
 *
 * 配置项：
 *   - enabled / doc_url / sync_images → PATCH /api/config { tencent_docs: {...} }（深合并）
 *   - token → POST /api/keyring/tencent_docs（keyring，永不回显）
 *     token 从 https://docs.qq.com/scenario/open-claw.html 获取（官方
 *     「腾讯文档 Skill」页面），泄露可在该页作废重置。
 *
 * 「识别表头」（保存链接后自动跑，也可手动点）：POST /api/mining/tencent_docs/inspect
 *   读表格里每一张子表的首行，按列名识别 链接 / 序号 / 日期 / 第 N 层评论 / 第 N 层图片
 *   （只认列名不认位置——评论列和图片列不相邻、只有 3 层都没关系），并标出各平台会写
 *   进哪张子表。识别不准的列可以在面板里逐列改成正确角色 →「保存映射」
 *   （PUT /api/mining/tencent_docs/mapping），之后同步严格按这份映射写；
 *   「恢复自动识别」删掉手动映射。表头后来改动过时，同步会自动作废旧映射并提醒。
 */
import { computed, onMounted, reactive, ref } from "vue";

import Btn from "@/components/ui/Btn.vue";
import Icon from "@/components/ui/Icon.vue";
import Pill from "@/components/ui/Pill.vue";
import Spinner from "@/components/ui/Spinner.vue";
import FormSelect from "@/components/forms/FormSelect.vue";
import FormToggle from "@/components/forms/FormToggle.vue";
import { useConfig } from "@/stores/config";
import { useSidecar } from "@/stores/sidecar";
import { useToast } from "@/composables/useToast";

const cfg = useConfig();
const sidecar = useSidecar();
const toast = useToast();

const loading = ref(true);
const enabled = ref(false);
const docUrl = ref("");
const hasToken = ref(false);
const tokenInput = ref("");
const savingToken = ref(false);
const savingUrl = ref(false);
// 评论楼层挂图直接插进表格贴图列（insert_image）；关 = 只写「有图，另发」标记。
const syncImages = ref(true);

// ── 识别表头 ───────────────────────────────────────────────────────────
interface InspectColumn {
  col: number;
  letter: string;
  header: string;
  role: string | null;          // seq / url / date / tierN / imgN
  role_label: string;
  source: "auto" | "override" | null;
}
interface InspectSheet {
  sheet_id: string;
  sheet_name: string;
  header: string[];
  columns: InspectColumn[];
  mapping: Record<string, number>;
  missing: string[];
  optional_missing: string[];
  tier_gaps: number[];
  tiers_detected: number;
  image_cols_missing: number[];
  has_override: boolean;
  override_stale: boolean;
  platforms: string[];          // 会写进这张子表的平台
  platform_labels: string[];
  is_fallback: boolean;
}
interface InspectResult {
  ok: boolean;
  doc_url: string;
  file_id: string;
  sheets: InspectSheet[];
  insert_image_supported: boolean;
  sync_images: boolean;
  detail?: string;              // 错误路径
}

const inspecting = ref(false);
const inspectResult = ref<InspectResult | null>(null);
const inspectError = ref<string | null>(null);
// 每张子表的草稿：col → role（"" = 忽略）。从识别结果初始化，用户改下拉后写回这里。
const drafts = reactive<Record<string, Record<number, string>>>({});
const savingMap = ref<Record<string, boolean>>({});

const TIER_MAX = 5;
const ROLE_OPTIONS: Array<{ label: string; value: string }> = [
  { label: "— 忽略 —", value: "" },
  { label: "链接", value: "url" },
  { label: "序号", value: "seq" },
  { label: "日期", value: "date" },
  ...Array.from({ length: TIER_MAX }, (_, i) => ({ label: `第 ${i + 1} 层评论`, value: `tier${i + 1}` })),
  ...Array.from({ length: TIER_MAX }, (_, i) => ({ label: `第 ${i + 1} 层图片`, value: `img${i + 1}` })),
];

function initDraft(s: InspectSheet) {
  const d: Record<number, string> = {};
  for (const c of s.columns) d[c.col] = c.role ?? "";
  drafts[s.sheet_id] = d;
}

function draftDirty(s: InspectSheet): boolean {
  const d = drafts[s.sheet_id];
  if (!d) return false;
  return s.columns.some((c) => (c.role ?? "") !== (d[c.col] ?? ""));
}

/** 草稿里同一角色被指到两列 → 返回冲突角色的显示名（保存前拦）。 */
function draftClash(s: InspectSheet): string[] {
  const d = drafts[s.sheet_id] ?? {};
  const seen = new Map<string, number>();
  const clash: string[] = [];
  for (const role of Object.values(d)) {
    if (!role) continue;
    const n = seen.get(role) ?? 0;
    seen.set(role, n + 1);
    if (n === 1) clash.push(ROLE_OPTIONS.find((o) => o.value === role)?.label ?? role);
  }
  return clash;
}

/** 草稿里最深的评论层（用于「该表 N 层」提示，随用户改动实时变）。 */
function draftTiers(s: InspectSheet): number {
  const d = drafts[s.sheet_id] ?? {};
  let max = 0;
  for (const role of Object.values(d)) {
    const m = /^tier(\d+)$/.exec(role);
    if (m) max = Math.max(max, Number(m[1]));
  }
  return max;
}

async function runInspect(url?: string) {
  if (inspecting.value) return;
  inspecting.value = true;
  inspectError.value = null;
  try {
    const resp = await sidecar.client.post<InspectResult>("/api/mining/tencent_docs/inspect", {
      doc_url: url ?? null,
    });
    inspectResult.value = resp.data;
    for (const s of resp.data.sheets) initDraft(s);
  } catch (e: any) {
    const data = e?.response?.data;
    inspectResult.value = null;
    inspectError.value = data?.detail ?? "连接失败，请检查网络 / Token / 表格链接";
  } finally {
    inspecting.value = false;
  }
}

async function onSaveMapping(s: InspectSheet) {
  if (!inspectResult.value || savingMap.value[s.sheet_id]) return;
  const clash = draftClash(s);
  if (clash.length) {
    toast.error(`同一角色不能指到两列：${clash.join("、")}`);
    return;
  }
  const d = drafts[s.sheet_id] ?? {};
  const mapping: Record<string, number | null> = {};
  for (const [colStr, role] of Object.entries(d)) {
    if (role) mapping[role] = Number(colStr);
  }
  // 自动识别到、但用户改成「忽略」的角色：显式记 null，同步时不会再自动写它。
  for (const c of s.columns) {
    if (c.role && !(c.role in mapping)) mapping[c.role] = null;
  }
  savingMap.value = { ...savingMap.value, [s.sheet_id]: true };
  try {
    await sidecar.client.put("/api/mining/tencent_docs/mapping", {
      file_id: inspectResult.value.file_id,
      sheet_id: s.sheet_id,
      mapping,
      header: s.header,
    });
    toast.success(`子表「${s.sheet_name}」的列映射已保存，同步时按它写`);
    await runInspect(inspectResult.value.doc_url);
  } catch (e: any) {
    toast.error("保存失败" + (e?.response?.data?.detail ? "：" + e.response.data.detail : ""));
  } finally {
    savingMap.value = { ...savingMap.value, [s.sheet_id]: false };
  }
}

async function onResetMapping(s: InspectSheet) {
  if (!inspectResult.value) return;
  try {
    await sidecar.client.delete(
      `/api/mining/tencent_docs/mapping/${encodeURIComponent(inspectResult.value.file_id)}/${encodeURIComponent(s.sheet_id)}`,
    );
    toast.success(`子表「${s.sheet_name}」已恢复自动识别`);
    await runInspect(inspectResult.value.doc_url);
  } catch {
    toast.error("恢复失败");
  }
}

const canInspect = computed(() => hasToken.value && !!docUrl.value.trim() && !inspecting.value);

// ── 基础配置 ───────────────────────────────────────────────────────────
function syncFromConfig() {
  const td = (cfg.data?.tencent_docs ?? {}) as Record<string, any>;
  enabled.value = !!td.enabled;
  docUrl.value = String(td.doc_url ?? "");
  syncImages.value = td.sync_images !== false;
}

async function loadStatus() {
  try {
    const resp = await sidecar.client.get<{ has_token: boolean }>(
      "/api/mining/tencent_docs/status",
    );
    hasToken.value = !!resp.data.has_token;
  } catch { /* status 失败不阻塞卡片渲染 */ }
}

onMounted(async () => {
  try {
    if (!cfg.data) await cfg.load();
    syncFromConfig();
    await loadStatus();
  } finally {
    loading.value = false;
  }
});

async function onToggleEnabled(v: boolean) {
  enabled.value = v;
  try {
    await cfg.patch({ tencent_docs: { enabled: v } });
    toast.success(v ? "已启用腾讯文档同步" : "已停用（同步按钮将走 CSV 导出兜底）");
  } catch (e: any) {
    enabled.value = !v;
    toast.error("保存失败");
  }
}

async function onToggleSyncImages(v: boolean) {
  syncImages.value = v;
  try {
    await cfg.patch({ tencent_docs: { sync_images: v } });
    toast.success(v ? "评论图片将直接插进表格" : "已关闭直传（贴图列只写「有图，另发」）");
  } catch {
    syncImages.value = !v;
    toast.error("保存失败");
  }
}

async function onSaveUrl() {
  if (savingUrl.value) return;
  savingUrl.value = true;
  const url = docUrl.value.trim();
  try {
    await cfg.patch({ tencent_docs: { doc_url: url } });
    toast.success("表格链接已保存");
    inspectResult.value = null;
    inspectError.value = null;
  } catch (e: any) {
    toast.error("保存失败");
    savingUrl.value = false;
    return;
  }
  savingUrl.value = false;
  // 粘贴链接就识别表头：有 token 才能读表，没 token 先提示配 token。
  if (url && hasToken.value) await runInspect(url);
}

async function onSaveToken() {
  const v = tokenInput.value.trim();
  if (!v || savingToken.value) return;
  savingToken.value = true;
  try {
    await sidecar.client.post("/api/keyring/tencent_docs", { value: v });
    hasToken.value = true;
    tokenInput.value = "";
    inspectResult.value = null;
    toast.success("Token 已保存到系统钥匙串");
  } catch (e: any) {
    const detail = e?.response?.data?.detail as string | undefined;
    toast.error("Token 保存失败" + (detail ? "：" + detail : ""));
  } finally {
    savingToken.value = false;
  }
}

async function onDeleteToken() {
  try {
    await sidecar.client.delete("/api/keyring/tencent_docs");
    hasToken.value = false;
    inspectResult.value = null;
    toast.success("Token 已删除");
  } catch {
    toast.error("删除失败");
  }
}
</script>

<template>
  <div
    :style="{
      background: 'var(--card-2)',
      border: '1px solid var(--line)',
      borderRadius: '14px',
      padding: '16px',
    }"
  >
    <!-- Header -->
    <div class="flex items-center gap-2">
      <span
        class="inline-flex items-center justify-center"
        :style="{
          width: '28px', height: '28px', borderRadius: '8px',
          background: 'var(--dark)', color: 'var(--yellow)',
        }"
      ><Icon name="external" :size="13"/></span>
      <div class="flex-1">
        <div class="font-display text-[13.5px] font-semibold">腾讯文档同步</div>
        <div class="mt-0.5 text-[11px]" :style="{ color: 'var(--ink-3)' }">
          审核通过的评论一键追加到与兼职共享的在线表格（按表头列名自动对齐，可逐列确认）
        </div>
      </div>
      <FormToggle :model-value="enabled" @update:model-value="onToggleEnabled"/>
    </div>

    <div v-if="loading" class="mt-4 flex items-center gap-2 text-[12px]" :style="{ color: 'var(--ink-3)' }">
      <Spinner :size="12"/><span>读取中…</span>
    </div>

    <template v-else>
      <!-- Token -->
      <div class="mt-4">
        <div class="flex items-center gap-2 mb-1.5">
          <div class="text-[11.5px] font-semibold">TENCENT_DOCS_TOKEN</div>
          <Pill v-if="hasToken" tone="primary">已配置</Pill>
          <Pill v-else>未配置</Pill>
        </div>
        <div class="flex items-center gap-2">
          <input
            v-model="tokenInput"
            type="password"
            :placeholder="hasToken ? '粘贴新 token 可覆盖' : '从腾讯文档 Skill 页面复制 token 粘贴到这里'"
            class="flex-1 outline-none"
            style="background: var(--card-white); border: 1px solid var(--line-2); border-radius: 10px; padding: 0 12px; height: 36px; font-size: 12px; color: var(--ink);"
          />
          <Btn variant="solid" small :disabled="!tokenInput.trim() || savingToken" @click="onSaveToken">
            {{ savingToken ? "保存中…" : "保存" }}
          </Btn>
          <Btn v-if="hasToken" variant="ghost" small @click="onDeleteToken">删除</Btn>
        </div>
        <div class="mt-1 text-[11px]" :style="{ color: 'var(--ink-3)' }">
          获取/重置：docs.qq.com/scenario/open-claw.html（腾讯文档 Skill 官方页）· 仅存本机钥匙串
        </div>
      </div>

      <!-- 表格链接 -->
      <div class="mt-4">
        <div class="text-[11.5px] font-semibold mb-1.5">表格链接</div>
        <div class="flex items-center gap-2">
          <input
            v-model="docUrl"
            placeholder="https://docs.qq.com/sheet/xxxx?tab=xxxx"
            class="flex-1 outline-none"
            style="background: var(--card-white); border: 1px solid var(--line-2); border-radius: 10px; padding: 0 12px; height: 36px; font-size: 12px; color: var(--ink);"
            @keydown.enter="onSaveUrl"
          />
          <Btn variant="solid" small :disabled="savingUrl" @click="onSaveUrl">
            {{ savingUrl ? "保存中…" : "保存并识别表头" }}
          </Btn>
        </div>
        <div class="mt-1 text-[11px]" :style="{ color: 'var(--ink-3)' }">
          保存后自动读取每张子表的表头并识别列角色；链接带 ?tab= 时该子表作为找不到平台同名子表时的兜底，否则用第一张
        </div>
      </div>

      <!-- 评论图片直传 -->
      <div class="mt-4 flex items-center gap-3">
        <div class="flex-1">
          <div class="text-[11.5px] font-semibold">评论图片直接插进表格</div>
          <div class="mt-0.5 text-[11px]" :style="{ color: 'var(--ink-3)' }">
            开 = 楼层挂图按原图插到对应「第 N 层图片」列（一格多图会叠放，可拖开）；关或服务端不支持插图时，该格写「有图，另发」
          </div>
        </div>
        <FormToggle :model-value="syncImages" @update:model-value="onToggleSyncImages"/>
      </div>

      <!-- 识别表头 -->
      <div class="mt-4">
        <div class="flex items-center gap-2">
          <Btn variant="ghost" small :disabled="!canInspect" @click="runInspect()">
            <Spinner v-if="inspecting" :size="11"/>
            <span>{{ inspecting ? "识别中…" : "识别表头 / 测试连接" }}</span>
          </Btn>
          <span v-if="!hasToken" class="text-[11px]" :style="{ color: 'var(--ink-3)' }">先配置 Token</span>
        </div>

        <div
          v-if="inspectError"
          class="mt-2 text-[11.5px] leading-relaxed"
          :style="{
            background: 'rgba(216,90,72,0.08)', border: '1px solid rgba(216,90,72,0.30)',
            borderRadius: '10px', padding: '10px 12px', color: 'var(--ink-2)', whiteSpace: 'pre-line',
          }"
        >❌ {{ inspectError }}</div>

        <template v-if="inspectResult">
          <div
            class="mt-2 text-[11.5px] leading-relaxed"
            :style="{
              background: inspectResult.ok ? 'rgba(122,155,94,0.10)' : 'rgba(216,90,72,0.08)',
              border: '1px solid ' + (inspectResult.ok ? 'rgba(122,155,94,0.32)' : 'rgba(216,90,72,0.30)'),
              borderRadius: '10px', padding: '10px 12px', color: 'var(--ink-2)',
            }"
          >
            <div>{{ inspectResult.ok ? "✅ 已连上表格，各子表识别结果如下（可逐列改）" : "⚠️ 已连上，但有子表缺必需列，请在下面指定" }}</div>
            <div v-if="inspectResult.insert_image_supported === false" class="mt-1" :style="{ color: 'var(--yellow-deep)' }">
              ⚠️ 服务端未提供 insert_image 工具，评论图片无法插进表格，同步时贴图列只写「有图，另发」
            </div>
            <div v-else class="mt-1" :style="{ color: 'var(--ink-3)' }">
              评论图片直传：{{ inspectResult.sync_images === false ? "已关闭（只写标记）" : "可用，楼层挂图会插进对应图片列" }}
            </div>
          </div>

          <div
            v-for="s in inspectResult.sheets"
            :key="s.sheet_id"
            class="mt-2"
            :style="{
              background: 'var(--card-white)', border: '1px solid var(--line-2)',
              borderRadius: '12px', padding: '10px 12px',
              opacity: s.platforms.length ? 1 : 0.75,
            }"
          >
            <!-- 子表标题行 -->
            <div class="flex flex-wrap items-center gap-1.5">
              <span class="text-[12px] font-semibold">子表「{{ s.sheet_name }}」</span>
              <Pill v-for="l in s.platform_labels" :key="l" tone="primary">{{ l }}</Pill>
              <span v-if="!s.platforms.length" class="text-[11px]" :style="{ color: 'var(--ink-3)' }">（没有平台会写进这张表）</span>
              <span v-else-if="s.is_fallback && s.platforms.length" class="text-[11px]" :style="{ color: 'var(--ink-3)' }">（兜底子表）</span>
              <span class="flex-1"/>
              <span class="text-[11px]" :style="{ color: 'var(--ink-3)' }">
                <template v-if="draftTiers(s) > 0">{{ draftTiers(s) }} 层评论列</template>
                <template v-else>未识别到评论列</template>
              </span>
            </div>

            <!-- 警告 -->
            <div class="mt-1 text-[11px] leading-relaxed">
              <div v-if="s.override_stale" :style="{ color: 'var(--red)' }">
                ⚠️ 表头和上次保存映射时不一样了，旧映射已作废、当前按自动识别显示——请重新确认并保存
              </div>
              <div v-else-if="s.has_override" :style="{ color: 'var(--green-deep)' }">
                ✓ 使用你保存的手动映射
              </div>
              <div v-if="s.missing.length" :style="{ color: 'var(--red)' }">缺必需列：{{ s.missing.join("、") }}</div>
              <div v-if="s.tier_gaps.length" :style="{ color: 'var(--yellow-deep)' }">评论列不连续，缺第 {{ s.tier_gaps.join("、") }} 层</div>
              <div v-if="s.image_cols_missing.length" :style="{ color: 'var(--yellow-deep)' }">
                第 {{ s.image_cols_missing.join("、") }} 层没有图片列：该层挂图无处可放，不会写入
              </div>
              <div v-if="s.platforms.length && draftTiers(s) > 0 && draftTiers(s) < TIER_MAX" :style="{ color: 'var(--ink-3)' }">
                该表只有 {{ draftTiers(s) }} 层：评论超出的楼层留在 app 内不同步
              </div>
            </div>

            <!-- 逐列映射 -->
            <div class="mt-2 grid gap-1" style="grid-template-columns: repeat(auto-fill, minmax(230px, 1fr));">
              <div
                v-for="c in s.columns"
                :key="c.col"
                class="flex items-center gap-1.5"
                :style="{ opacity: c.header ? 1 : 0.55 }"
              >
                <span class="font-mono text-[10.5px]" :style="{ color: 'var(--ink-4)', width: '22px', flexShrink: 0 }">{{ c.letter }}</span>
                <span
                  class="text-[11.5px] truncate"
                  :style="{ color: 'var(--ink)', flex: '1 1 0', minWidth: 0 }"
                  :title="c.header"
                >{{ c.header || "（空）" }}</span>
                <FormSelect
                  :model-value="drafts[s.sheet_id]?.[c.col] ?? ''"
                  :options="ROLE_OPTIONS"
                  width="118px"
                  @update:model-value="(v) => { if (drafts[s.sheet_id]) drafts[s.sheet_id][c.col] = String(v); }"
                />
              </div>
            </div>

            <!-- 操作 -->
            <div class="mt-2 flex items-center gap-2">
              <Btn
                variant="solid" small
                :disabled="!draftDirty(s) || !!savingMap[s.sheet_id]"
                @click="onSaveMapping(s)"
              >{{ savingMap[s.sheet_id] ? "保存中…" : "保存映射" }}</Btn>
              <Btn v-if="s.has_override" variant="ghost" small @click="onResetMapping(s)">恢复自动识别</Btn>
              <span v-if="draftClash(s).length" class="text-[11px]" :style="{ color: 'var(--red)' }">
                同一角色指到了两列：{{ draftClash(s).join("、") }}
              </span>
              <span v-else-if="draftDirty(s)" class="text-[11px]" :style="{ color: 'var(--ink-3)' }">有未保存的改动</span>
            </div>
          </div>
        </template>
      </div>
    </template>
  </div>
</template>
