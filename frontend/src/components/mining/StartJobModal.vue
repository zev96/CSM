<script setup lang="ts">
import { ref, computed, watch } from "vue";
import Btn from "@/components/ui/Btn.vue";
import Dialog from "@/components/ui/Dialog.vue";
import Icon from "@/components/ui/Icon.vue";
import Blob from "@/components/ui/Blob.vue";
import PlatformPickerCard from "./PlatformPickerCard.vue";
import type { Platform } from "@/stores/mining";

const props = defineProps<{
  open: boolean;
  loginStatus: Record<Platform, boolean>;
}>();

const emit = defineEmits<{
  (e: "update:open", v: boolean): void;
  (e: "submit", payload: { keyword: string; platforms: Platform[]; target: number }): void;
}>();

const kw = ref("");
// Auto-pick all logged-in platforms by default.
const picked = ref<Record<Platform, boolean>>({
  bilibili: !!props.loginStatus.bilibili,
  douyin: !!props.loginStatus.douyin,
  kuaishou: !!props.loginStatus.kuaishou,
});
const cap = ref(50);
const sort = ref("综合");
const range = ref("近 1 周");

const total = computed(() =>
  Object.values(picked.value).filter(Boolean).length * cap.value
);

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
    kw.value = "";
    picked.value = {
      bilibili: !!props.loginStatus.bilibili,
      douyin: !!props.loginStatus.douyin,
      kuaishou: !!props.loginStatus.kuaishou,
    };
    cap.value = 50;
    sort.value = "综合";
    range.value = "近 1 周";
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
  });
}
</script>

<template>
  <Dialog :open="open" size="lg" @update:open="close">
    <Blob color="#f5c042" :size="220" :top="-80" :left="-40" :opacity="0.32"/>

    <!-- 顶部 -->
    <div class="relative mb-4">
      <div class="flex items-start justify-between">
        <div>
          <div class="text-[10.5px] tracking-[1.5px] uppercase font-medium" style="color: var(--ink-3)">
            Outreach · 新建抓取任务
          </div>
          <div class="font-display font-bold mt-1.5" style="font-size: 22px; letter-spacing: -0.5px;">
            新建抓取任务
          </div>
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
          <div class="flex items-center justify-between mb-1.5">
            <label class="text-[11.5px] font-semibold">关键词</label>
            <span class="text-[10.5px]" style="color: var(--ink-4)">多个关键词暂不支持（Phase 2）</span>
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
        </div>

        <!-- 平台 -->
        <div class="mt-5">
          <div class="flex items-center justify-between mb-2">
            <label class="text-[11.5px] font-semibold">在哪些平台抓</label>
            <span class="text-[10.5px]" style="color: var(--ink-4)">未登录的去监控中心扫码</span>
          </div>
          <div class="grid grid-cols-3 gap-2">
            <PlatformPickerCard
              v-for="p in (['bilibili', 'douyin', 'kuaishou'] as Platform[])"
              :key="p"
              :platform="p"
              :picked="!!picked[p]"
              :logged-in="!!loginStatus[p]"
              @toggle="togglePlatform(p)"
              @login="$emit('close')"
            />
          </div>
        </div>

        <!-- 排序 / 时间 (UI only, not wired to backend in Phase 1) -->
        <div class="grid grid-cols-2 gap-3 mt-5">
          <div>
            <label class="text-[11.5px] font-semibold mb-1.5 block">排序</label>
            <div class="flex" style="background: var(--card-2); border-radius: 999px; padding: 3px; border: 1px solid var(--line);">
              <button
                v-for="s in ['综合', '最新', '最热']" :key="s"
                @click="sort = s"
                :style="{
                  flex: 1, height: '28px', borderRadius: '999px', fontSize: '11.5px', fontWeight: 500,
                  background: sort === s ? 'var(--dark)' : 'transparent',
                  color: sort === s ? '#fbf7ec' : 'var(--ink-2)',
                  border: 'none', cursor: 'pointer',
                }"
              >{{ s }}</button>
            </div>
          </div>
          <div>
            <label class="text-[11.5px] font-semibold mb-1.5 block">时间范围</label>
            <div class="flex" style="background: var(--card-2); border-radius: 999px; padding: 3px; border: 1px solid var(--line);">
              <button
                v-for="s in ['不限', '近 1 天', '近 1 周', '近 1 月']" :key="s"
                @click="range = s"
                :style="{
                  flex: 1, height: '28px', borderRadius: '999px', fontSize: '11px', fontWeight: 500,
                  background: range === s ? 'var(--dark)' : 'transparent',
                  color: range === s ? '#fbf7ec' : 'var(--ink-2)',
                  border: 'none', cursor: 'pointer',
                  whiteSpace: 'nowrap', padding: '0 4px',
                }"
              >{{ s }}</button>
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
              <div :style="{ height: '100%', width: (cap / 200 * 100) + '%', background: 'var(--primary)', borderRadius: '999px' }"/>
            </div>
            <input
              type="range" min="10" max="200" step="10" v-model.number="cap"
              style="position: absolute; inset: 0; width: 100%; opacity: 0; cursor: pointer;"
            />
            <div class="flex justify-between mt-1.5 font-mono text-[10px]" style="color: var(--ink-4)">
              <span>10</span><span>50</span><span>100</span><span>200</span>
            </div>
          </div>
        </div>

        <!-- 预估 -->
        <div
          class="mt-4 flex items-center gap-2.5 px-3.5 py-3"
          style="background: rgba(245,192,66,0.10); border: 1px solid rgba(245,192,66,0.36); border-radius: 12px;"
        >
          <span
            style="width: 26px; height: 26px; border-radius: 8px; background: var(--yellow-soft); color: #7a5400; display: inline-flex; align-items: center; justify-content: center; flex-shrink: 0;"
          ><Icon name="info" :size="13"/></span>
          <div class="text-[11.5px] leading-snug" style="color: var(--ink-2)">
            预计抓取 <b class="font-display" style="color: var(--ink)">{{ total }}</b> 条视频，约需
            <b class="font-mono" style="color: var(--ink)">{{ Math.max(2, Math.round(total / 25)) }}–{{ Math.max(4, Math.round(total / 15)) }} 分钟</b>。
            抓完后会自动去重 &amp; 过滤已评论。
          </div>
        </div>
      </div>

    <template #footer>
      <div class="flex-1 text-[11px]" style="color: var(--ink-3)">
        <Icon name="key" :size="11" style="display: inline-block; margin-right: 4px; opacity: 0.6;"/>
        登录 cookie 来自监控中心 · 仅存于本地
      </div>
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
</style>
