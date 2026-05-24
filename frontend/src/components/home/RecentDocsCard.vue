<script setup lang="ts">
/**
 * 最近文档 — Row 3。
 *
 *   ┌─────────────────────────────────────────────────────────────────────┐
 *   │ 最近文档 · 继续未完成的工作 · N 篇                            [全部→]│
 *   ├──────────┬──────────┬──────────┬───────────────────────────────────┤
 *   │ [chip]    │ [chip]    │ [chip]    │ [chip]                           │
 *   │ title     │ title     │ title     │ title                            │
 *   │           │           │           │                                  │
 *   │ tpl · 时间 │ tpl · 时间 │ tpl · 时间 │ tpl · 时间                       │
 *   └──────────┴──────────┴──────────┴───────────────────────────────────┘
 *
 * Row3 height 由 HomeView 给 flex-1 兜底；卡片本体最多展示 4 篇横排。
 * 多于 4 篇时点 "全部 →" 进 RecentHistoryView 看完整列表。
 *
 * 数据：listRecent(4, 7) — 近 7 天最近 4 篇。
 */
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";

import Icon from "@/components/ui/Icon.vue";
import { listRecent } from "@/api/client";
import { useSidecarReady } from "@/composables/useSidecarReady";

type Status = "已发布" | "草稿" | "归档";

interface Doc {
  id: string;
  title: string;
  tpl: string;
  when: string;
  status: Status;
  path?: string;
}

const router = useRouter();
const { whenReady } = useSidecarReady();

const docs = ref<Doc[]>([]);
const loaded = ref(false);

function relativeTime(iso: string): string {
  try {
    const ms = Date.now() - new Date(iso).getTime();
    const m = Math.floor(ms / 60000);
    if (m < 1) return "刚刚";
    if (m < 60) return `${m} 分钟前`;
    const h = Math.floor(m / 60);
    if (h < 24) return `${h} 小时前`;
    const d = Math.floor(h / 24);
    if (d === 1) return "昨天";
    if (d < 7) return `${d} 天前`;
    const date = new Date(iso);
    return `${date.getMonth() + 1} 月 ${date.getDate()} 日`;
  } catch {
    return "—";
  }
}

const visibleDocs = computed(() => docs.value.slice(0, 4));

onMounted(async () => {
  try {
    await whenReady();
    // 卡片横排 4 列，多于 4 篇靠"全部 →"跳转完整历史。
    const r = await listRecent(4, 7);
    docs.value = r.documents.map((d) => ({
      id: d.path,
      title: d.title,
      tpl: d.template_name ?? "—",
      when: relativeTime(d.modified_at),
      status: "草稿" as Status,
      path: d.path,
    }));
  } catch {
    /* 静默 */
  } finally {
    loaded.value = true;
  }
});

function chipStyle(status: Status) {
  if (status === "已发布") return { background: "#dde7d2", color: "#4d6b2f" };
  if (status === "草稿")
    return { background: "var(--yellow-soft)", color: "#7a5400" };
  return { background: "rgba(28,26,23,0.06)", color: "var(--ink-2)" };
}

/**
 * 把本地路径转 file:// URL（跟 RecentHistoryView.toFileURL 同款），
 * 让 Tauri plugin-shell 的 open scope 校验更好通过（默认 scope 是
 * mailto/tel/https 三种，纯 Windows 绝对路径会被拒）。
 */
function toFileURL(p: string): string {
  if (!p) return "";
  if (/^[a-z]+:\/\//i.test(p)) return p;
  const normalized = p.replace(/\\/g, "/");
  if (/^[A-Za-z]:\//.test(normalized)) return `file:///${normalized}`;
  if (normalized.startsWith("/")) return `file://${normalized}`;
  return `file:///${normalized}`;
}

async function openDoc(d: Doc) {
  if (!d.path) {
    router.push({ name: "article" });
    return;
  }
  try {
    const isTauri =
      typeof window !== "undefined" &&
      // @ts-expect-error — ambient Tauri global
      Boolean(window.__TAURI_INTERNALS__ || window.__TAURI__);
    if (!isTauri) {
      const { useToast } = await import("@/composables/useToast");
      useToast().info(`文件位置：${d.path}`);
      return;
    }
    const { open } = await import("@tauri-apps/plugin-shell");
    await open(toFileURL(d.path));
  } catch (e: any) {
    const { useToast } = await import("@/composables/useToast");
    useToast().error(`打开失败：${e?.message ?? e}`);
  }
}
</script>

<template>
  <section
    class="card-frosted relative flex h-full min-h-0 flex-col overflow-hidden"
    :style="{ padding: '12px 14px' }"
  >
    <!-- 标题区（紧凑单行：「最近文档」 + 「全部 →」） -->
    <div class="mb-2 flex flex-shrink-0 items-center justify-between">
      <div
        class="font-display font-semibold"
        :style="{ fontSize: '13px', color: 'var(--ink)' }"
      >
        最近文档
      </div>
      <button
        type="button"
        class="inline-flex h-6 items-center gap-1 rounded-full px-2.5 text-[11px]"
        :style="{
          background: 'var(--card-2)',
          color: 'var(--ink-2)',
          border: '1px solid var(--line)',
        }"
        @click="router.push({ name: 'recent-history' })"
      >
        全部
        <Icon name="arrowRight" :size="10" />
      </button>
    </div>

    <!-- 4 卡横排 grid -->
    <div
      v-if="loaded && visibleDocs.length === 0"
      class="flex min-h-0 flex-1 flex-col items-center justify-center py-4 text-center"
      :style="{ color: 'var(--ink-3)' }"
    >
      <Icon name="fileText" :size="22" :style="{ color: 'var(--ink-4)' }" />
      <div class="mt-2 text-[12.5px]">暂无文档</div>
      <div class="mt-1 text-[10.5px]" :style="{ color: 'var(--ink-4)' }">
        起飞一篇试试 · 完成后会出现在这里
      </div>
    </div>

    <div
      v-else
      class="grid min-h-0 flex-1 grid-cols-2 gap-2 sm:grid-cols-4"
    >
      <div
        v-for="d in visibleDocs"
        :key="d.id"
        class="flex cursor-pointer flex-col gap-1 rounded-[10px] transition"
        :style="{
          background: 'var(--card-2)',
          border: '1px solid var(--line)',
          padding: '8px 10px',
        }"
        @click="openDoc(d)"
        @mouseenter="
          (e: MouseEvent) =>
            ((e.currentTarget as HTMLElement).style.background =
              'var(--card-white)')
        "
        @mouseleave="
          (e: MouseEvent) =>
            ((e.currentTarget as HTMLElement).style.background =
              'var(--card-2)')
        "
      >
        <span
          class="inline-flex h-4 w-fit items-center gap-1 rounded-full px-1.5 text-[10px] font-medium"
          :style="chipStyle(d.status)"
        >
          <Icon name="fileText" :size="9" />
          {{ d.status }}
        </span>
        <div
          class="font-display line-clamp-1 text-[12.5px] font-semibold leading-snug"
          :style="{ color: 'var(--ink)' }"
        >
          {{ d.title }}
        </div>
        <div
          class="mt-auto truncate text-[10.5px]"
          :style="{ color: 'var(--ink-3)' }"
        >
          {{ d.tpl }} · {{ d.when }}
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
/* line-clamp utility — Tailwind v3 has it built in (.line-clamp-2) so this
   is a no-op safety net for older builds. */
.line-clamp-2 {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
</style>
