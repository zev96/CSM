<script setup lang="ts">
import { ref, computed, watch } from "vue";
import Btn from "@/components/ui/Btn.vue";
import Dialog from "@/components/ui/Dialog.vue";
import Icon from "@/components/ui/Icon.vue";
// Blob 已下线 —— 用户要求弹窗背景跟应用默认 Dialog 一致，不要黄色
// 渐变光晕。
import PlatformPickerCard from "./PlatformPickerCard.vue";
import { defaultSearchFilters } from "@/stores/mining";
import type { Platform, SearchFilters } from "@/stores/mining";

const props = defineProps<{
  open: boolean;
  loginStatus: Record<Platform, boolean>;
  prefillKeyword?: string;
  prefillSource?: string;
  /** 采集走 TikHub：三平台默认全选，不看登录态。 */
  tikhubMode?: boolean;
  /** TikHub 模式且未配置 Key —— 不自动勾选、不可开始。 */
  tikhubKeyMissing?: boolean;
}>();

const emit = defineEmits<{
  (e: "update:open", v: boolean): void;
  (e: "submit", payload: { keyword: string; platforms: Platform[]; target: number; brandKeywords: string[]; filters: SearchFilters }): void;
}>();

const kw = ref("");
// 目标品牌词（选填）—— 抓完后逐视频抓评论区前 20 条，命中品牌词的视频判为
// 「已种草」跳过（见 mining/runner 预筛；条数/阈值可在 settings.json 的
// mining_prefilter_* 调）。留空 → 后端 brand_keywords=[] → 预筛门控
// 不满足 → 不按品牌筛。支持多个，用逗号 / 顿号 / 空格分隔。
const brandKw = ref("");
// Auto-pick all logged-in platforms by default（TikHub 模式下三平台恒全选，不看登录态）。
const pickAll = () => ({
  bilibili: (props.tikhubMode && !props.tikhubKeyMissing) || !!props.loginStatus.bilibili,
  douyin: (props.tikhubMode && !props.tikhubKeyMissing) || !!props.loginStatus.douyin,
  kuaishou: (props.tikhubMode && !props.tikhubKeyMissing) || !!props.loginStatus.kuaishou,
});
const picked = ref<Record<Platform, boolean>>(pickAll());
const cap = ref(50);
// TikHub 模式下单平台每页约 6–14 条、$0.01/页 —— 后端 runner 会把有效目标
// 钳到 min(用户目标, 80)，滑条本身也钳到 80，避免用户以为能拉满 200 条。
const capMax = computed(() => (props.tikhubMode ? 80 : 200));
watch(capMax, (m) => {
  if (cap.value > m) cap.value = m;
});
// 按平台分组的筛选条件 —— 每个平台只展示它真实支持的档位：
// 抖音只有时间档位（无任意区间）、B 站支持任意日期区间、快手只能本地后过滤。
const filters = ref<SearchFilters>(defaultSearchFilters());

function toggleDouyinType(t: "video" | "note") {
  const list = filters.value.douyin.content_types;
  if (list.includes(t)) {
    // 至少保留一种类型，全取消没有意义
    if (list.length > 1) {
      filters.value.douyin.content_types = list.filter(x => x !== t);
    }
  } else {
    filters.value.douyin.content_types = [...list, t];
  }
}

const total = computed(() =>
  Object.values(picked.value).filter(Boolean).length * Math.min(cap.value, capMax.value)
);

// 品牌词输入 → 去重后的 list[str]。逗号(中/英)、顿号、空白都当分隔符。
// 大小写不敏感去重，保留用户原始大小写写法。
const brandList = computed<string[]>(() => {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const part of brandKw.value.split(/[,，、\s]+/)) {
    const t = part.trim();
    if (t && !seen.has(t.toLowerCase())) {
      seen.add(t.toLowerCase());
      out.push(t);
    }
  }
  return out;
});

const canSubmit = computed(
  () => kw.value.trim() && Object.values(picked.value).some(v => v)
);

// 以前用 v-if 挂载，每次新开都是 fresh component → 状态天然 reset。
// 改 v-model:open 后组件常驻，必须显式在 open 变 true 时重置表单 +
// 重新按当前 loginStatus 自动勾选。
watch(
  () => props.open,
  (v) => {
    if (!v) return;
    // 先重置表单（包括 kw），再按 prefillKeyword 预填关键词。
    // 这样：新开弹窗干净 → 若有来自 GEO 信源榜的预填 → 填入。
    kw.value = "";
    brandKw.value = "";
    picked.value = pickAll();
    cap.value = Math.min(50, capMax.value);
    filters.value = defaultSearchFilters();
    // 预填关键词（来自 GEO 闭环跳转）—— 只在 kw 刚被清空时填，不覆盖用户已输入的内容。
    if (props.prefillKeyword) {
      kw.value = props.prefillKeyword;
    }
  },
);

function togglePlatform(p: Platform) {
  picked.value[p] = !picked.value[p];
}

function close() {
  emit("update:open", false);
}

function onSubmit() {
  if (!canSubmit.value) return;
  emit("submit", {
    keyword: kw.value.trim(),
    platforms: (["bilibili", "douyin", "kuaishou"] as Platform[]).filter(p => picked.value[p]),
    target: cap.value,
    brandKeywords: brandList.value,
    filters: JSON.parse(JSON.stringify(filters.value)),
  });
}
</script>

<template>
  <Dialog :open="open" size="lg" @update:open="close">
    <!-- 顶部 ——
         按用户要求移除：黄色 Blob 光晕 + "OUTREACH · 新建抓取任务" eyebrow。
         只保留 H2 标题和右上角关闭按钮，背景跟应用默认 Dialog 一致。 -->
    <div class="relative mb-4">
      <div class="flex items-start justify-between">
        <div class="font-display font-bold" style="font-size: 22px; letter-spacing: -0.5px;">
          新建抓取任务
        </div>
        <button
          @click="close"
          class="inline-flex items-center justify-center"
          style="width: 32px; height: 32px; border-radius: 999px; background: var(--card-2); color: var(--ink-2); border: 1px solid var(--line);"
        >
          <Icon name="x" :size="14"/>
        </button>
      </div>
    </div>

    <div class="relative">
      <!-- 关键词 -->
        <div>
          <div class="mb-1.5">
            <label class="text-[11.5px] font-semibold">关键词</label>
            <!-- "多个关键词暂不支持（Phase 2）" 副标按用户要求移除 —— 是
                 内部 roadmap 信息，不该让用户看。 -->
          </div>
          <div
            class="flex items-center"
            style="background: var(--card-white); border: 1px solid var(--line-2); border-radius: 14px; padding: 0 14px; height: 46px;"
          >
            <Icon name="search" :size="15" style="opacity: 0.6"/>
            <input
              v-model="kw"
              placeholder="例如：宠物家庭吸尘器"
              class="kw-input flex-1 bg-transparent outline-none px-2.5"
              style="font-size: 14px; color: var(--ink);"
            />
            <button
              v-if="kw"
              @click="kw = ''"
              class="inline-flex items-center justify-center"
              style="width: 22px; height: 22px; border-radius: 999px; color: var(--ink-3);"
            ><Icon name="x" :size="12"/></button>
          </div>
          <!-- GEO 信源域名提示 —— 仅展示，不过滤，不影响提交载荷 -->
          <div
            v-if="props.prefillSource"
            class="mt-1.5 text-[11px]"
            style="color: var(--ink-3);"
          >
            建议针对来源：{{ props.prefillSource }}
          </div>
        </div>

        <!-- 目标品牌词（选填）—— 引流预筛：评论区已有 ≥3 条命中的视频自动跳过 -->
        <div class="mt-5">
          <div class="mb-1.5 flex items-baseline gap-1.5">
            <label class="text-[11.5px] font-semibold">目标品牌词</label>
            <span class="text-[11px]" style="color: var(--ink-3);">选填 · 多个用逗号 / 空格分隔</span>
          </div>
          <div
            class="flex items-center"
            style="background: var(--card-white); border: 1px solid var(--line-2); border-radius: 14px; padding: 0 14px; height: 46px;"
          >
            <Icon name="radar" :size="15" style="opacity: 0.6"/>
            <input
              v-model="brandKw"
              placeholder="例如：CEWEY，希亦（留空＝不按品牌预筛）"
              class="kw-input flex-1 bg-transparent outline-none px-2.5"
              style="font-size: 14px; color: var(--ink);"
            />
            <button
              v-if="brandKw"
              @click="brandKw = ''"
              class="inline-flex items-center justify-center"
              style="width: 22px; height: 22px; border-radius: 999px; color: var(--ink-3);"
            ><Icon name="x" :size="12"/></button>
          </div>
          <div class="mt-1.5 text-[11px]" style="color: var(--ink-3);">
            <template v-if="brandList.length">
              抓到的视频会顺带抓评论区<b style="color: var(--ink-2)">前 20 条</b>：已出现
              <b style="color: var(--ink-2)">{{ brandList.join(' / ') }}</b>
              的视频自动跳过（评论区已有我们的品牌评论＝已种草，不重复投放）。
            </template>
            <template v-else>
              留空＝只去重、不按品牌预筛。填了品牌词，评论区前 20 条已出现品牌词的视频会自动排除。
            </template>
          </div>
        </div>

        <!-- 平台 -->
        <div class="mt-5">
          <div class="mb-2">
            <label class="text-[11.5px] font-semibold">平台范围</label>
            <!-- "未登录的去监控中心扫码" 副标按用户要求移除 —— 卡片自身的
                 「未登录 / 已登录」状态已说明，旁标是冗余引导。 -->
          </div>
          <div class="grid grid-cols-3 gap-2">
            <PlatformPickerCard
              v-for="p in (['bilibili', 'douyin', 'kuaishou'] as Platform[])"
              :key="p"
              :platform="p"
              :picked="!!picked[p]"
              :logged-in="!!loginStatus[p]"
              :tikhub-mode="!!tikhubMode"
              :tikhub-key-missing="!!tikhubKeyMissing"
              @toggle="togglePlatform(p)"
              @login="$emit('update:open', false)"
            />
          </div>
          <div v-if="tikhubMode && tikhubKeyMissing" class="mt-2 text-[11px]" style="color: var(--red);">
            采集已设为走 TikHub，但尚未配置 TikHub API Key —— 请到「设置 › 监测 › 抓取数据源」粘贴 Key，或把「采集走 TikHub」关掉改用浏览器采集。
          </div>
        </div>

        <!-- 按平台分组的筛选条件 —— 只展示各平台真实支持的档位：
             抖音=时间档位+排序+类型；B站=排序+任意日期区间；快手=日期区间(本地过滤)。 -->
        <div v-if="picked.douyin" class="filter-block mt-5">
          <div class="mb-2 flex items-baseline gap-1.5">
            <label class="text-[11.5px] font-semibold">抖音筛选</label>
          </div>
          <div class="grid grid-cols-2 gap-3">
            <div>
              <div class="filter-sub-label">发布时间</div>
              <div class="chip-row">
                <button
                  v-for="opt in [
                    { v: '0', label: '不限' }, { v: '1', label: '一天内' },
                    { v: '7', label: '一周内' }, { v: '182', label: '半年内' },
                  ]" :key="opt.v"
                  class="chip-btn"
                  :class="{ 'chip-btn--on': filters.douyin.publish_time === opt.v }"
                  @click="filters.douyin.publish_time = opt.v as any"
                >{{ opt.label }}</button>
              </div>
            </div>
            <div>
              <div class="filter-sub-label">排序</div>
              <div class="chip-row">
                <button
                  v-for="opt in [
                    { v: '0', label: '综合' }, { v: '1', label: '最多点赞' }, { v: '2', label: '最新' },
                  ]" :key="opt.v"
                  class="chip-btn"
                  :class="{ 'chip-btn--on': filters.douyin.sort_type === opt.v }"
                  @click="filters.douyin.sort_type = opt.v as any"
                >{{ opt.label }}</button>
              </div>
            </div>
          </div>
          <div class="mt-2.5">
            <div class="filter-sub-label">内容类型（可多选）</div>
            <div class="chip-row" style="max-width: 200px;">
              <button
                v-for="opt in [
                  { v: 'video', label: '视频' }, { v: 'note', label: '图文' },
                ]" :key="opt.v"
                class="chip-btn"
                :class="{ 'chip-btn--on': filters.douyin.content_types.includes(opt.v as any) }"
                @click="toggleDouyinType(opt.v as any)"
              >{{ opt.label }}</button>
            </div>
          </div>
        </div>

        <div v-if="picked.bilibili" class="filter-block mt-3">
          <div class="mb-2 flex items-baseline gap-1.5">
            <label class="text-[11.5px] font-semibold">B站筛选</label>
            <span class="text-[11px]" style="color: var(--ink-3);">仅视频 · 支持任意日期区间</span>
          </div>
          <div class="grid grid-cols-2 gap-3">
            <div>
              <div class="filter-sub-label">排序</div>
              <div class="chip-row">
                <button
                  v-for="opt in [
                    { v: 'totalrank', label: '综合' }, { v: 'click', label: '播放' },
                    { v: 'pubdate', label: '最新' }, { v: 'stow', label: '收藏' },
                  ]" :key="opt.v"
                  class="chip-btn"
                  :class="{ 'chip-btn--on': filters.bilibili.order === opt.v }"
                  @click="filters.bilibili.order = opt.v as any"
                >{{ opt.label }}</button>
              </div>
            </div>
            <div>
              <div class="filter-sub-label">发布日期</div>
              <div class="flex items-center gap-1.5">
                <input type="date" class="date-input" :value="filters.bilibili.time_begin ?? ''"
                       @input="filters.bilibili.time_begin = ($event.target as HTMLInputElement).value || null"/>
                <span class="text-[11px]" style="color: var(--ink-3);">至</span>
                <input type="date" class="date-input" :value="filters.bilibili.time_end ?? ''"
                       @input="filters.bilibili.time_end = ($event.target as HTMLInputElement).value || null"/>
              </div>
            </div>
          </div>
        </div>

        <div v-if="picked.kuaishou" class="filter-block mt-3">
          <div class="mb-2 flex items-baseline gap-1.5">
            <label class="text-[11.5px] font-semibold">快手筛选</label>
            <span class="text-[11px]" style="color: var(--ink-3);">平台无时间筛选，抓取后按发布时间过滤（产出会变慢）</span>
          </div>
          <div>
            <div class="filter-sub-label">发布日期</div>
            <div class="flex items-center gap-1.5">
              <input type="date" class="date-input" :value="filters.kuaishou.time_begin ?? ''"
                     @input="filters.kuaishou.time_begin = ($event.target as HTMLInputElement).value || null"/>
              <span class="text-[11px]" style="color: var(--ink-3);">至</span>
              <input type="date" class="date-input" :value="filters.kuaishou.time_end ?? ''"
                     @input="filters.kuaishou.time_end = ($event.target as HTMLInputElement).value || null"/>
            </div>
          </div>
        </div>

        <!-- 数量滑条 -->
        <div class="mt-5">
          <div class="flex items-center justify-between mb-2">
            <label class="text-[11.5px] font-semibold">每平台抓取数量</label>
            <div class="flex items-baseline gap-1">
              <span class="font-display font-bold" style="font-size: 18px; color: var(--primary-deep); letter-spacing: -0.4px;">{{ cap }}</span>
              <span class="text-[10.5px]" style="color: var(--ink-3)">条 / 平台</span>
            </div>
          </div>
          <div style="position: relative; padding: 10px 0;">
            <div style="height: 6px; background: var(--card-2); border-radius: 999px; position: relative; border: 1px solid var(--line);">
              <div :style="{ height: '100%', width: (cap / capMax * 100) + '%', background: 'var(--primary)', borderRadius: '999px' }"/>
            </div>
            <input
              type="range" min="10" :max="capMax" step="10" v-model.number="cap"
              style="position: absolute; inset: 0; width: 100%; opacity: 0; cursor: pointer;"
            />
            <div class="flex justify-between mt-1.5 font-mono text-[10px]" style="color: var(--ink-4)">
              <span v-for="t in (tikhubMode ? [10, 40, 80] : [10, 50, 100, 200])" :key="t">{{ t }}</span>
            </div>
          </div>
          <div v-if="tikhubMode" class="mt-1.5 text-[11px]" style="color: var(--ink-3);">
            TikHub 模式：单平台每次最多 80 条（每页约 6–14 条，$0.01/页）
          </div>
        </div>

        <!-- 预估 -->
        <div
          class="mt-4 flex items-center gap-2.5 px-3.5 py-3"
          style="background: rgba(245,192,66,0.10); border: 1px solid rgba(245,192,66,0.36); border-radius: 12px;"
        >
          <span
            style="width: 26px; height: 26px; border-radius: 8px; background: var(--yellow-soft); color: var(--yellow-deep); display: inline-flex; align-items: center; justify-content: center; flex-shrink: 0;"
          ><Icon name="info" :size="13"/></span>
          <div class="text-[11.5px] leading-snug" style="color: var(--ink-2)">
            预计抓取 <b class="font-display" style="color: var(--ink)">{{ total }}</b> 条视频，约需
            <b class="font-mono" style="color: var(--ink)">{{ Math.max(2, Math.round(total / 25)) }}–{{ Math.max(4, Math.round(total / 15)) }} 分钟</b>。
            抓完后自动去重<template v-if="brandList.length"> &amp; 按品牌词预筛已种草视频</template>。
          </div>
        </div>
      </div>

    <template #footer>
      <!-- "登录 cookie 来自监控中心 · 仅存于本地" footer 提示按用户要求
           移除（隐私/数据流细节不需要在每次新建任务时再重复说一次）。
           取消 + 开始抓取 两个按钮靠右排列。 -->
      <div class="flex-1"/>
      <Btn variant="ghost" @click="close">取消</Btn>
      <Btn variant="solid" :disabled="!canSubmit" @click="onSubmit">
        <Icon name="play" :size="11"/> 开始抓取
      </Btn>
    </template>
  </Dialog>
</template>

<style scoped>
/*
 * 抑制全局 :focus-visible 的橙色 outline(see style.css)对模态框
 * 关键词输入的影响 —— 视觉上和卡片化的输入框冲突,用户专门提过。
 * 不动其他 input 的焦点环,a11y 保留。
 */
.kw-input:focus-visible {
  outline: none;
}

/* 按平台筛选块 —— 弱边框卡片，与弹窗其它区块视觉层级一致。 */
.filter-block {
  background: var(--card-white);
  border: 1px solid var(--line-2);
  border-radius: 14px;
  padding: 12px 14px;
}
.filter-sub-label {
  font-size: 11px;
  color: var(--ink-3);
  margin-bottom: 6px;
}
.chip-row {
  display: flex;
  background: var(--card-2);
  border-radius: 999px;
  padding: 3px;
  border: 1px solid var(--line);
}
.chip-btn {
  flex: 1;
  height: 26px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 500;
  background: transparent;
  color: var(--ink-2);
  border: none;
  cursor: pointer;
  white-space: nowrap;
  padding: 0 6px;
}
.chip-btn--on {
  background: var(--dark);
  color: var(--card);
}
.date-input {
  flex: 1;
  min-width: 0;
  height: 30px;
  border: 1px solid var(--line-2);
  border-radius: 10px;
  background: var(--card-white);
  color: var(--ink);
  font-size: 11.5px;
  padding: 0 8px;
}
</style>
