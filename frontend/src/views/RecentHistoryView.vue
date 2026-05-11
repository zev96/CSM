<script setup lang="ts">
/**
 * 最近文档完整历史页 —— HomeView 的 RecentDocsCard 是缩略版（10 条 +
 * 一个跳转按钮），这里是全量、可操作的视图：
 *
 *   - 列：图标 + 标题 + 模板 + 字数 + 修改时间 + [打开位置] + [打开文章]
 *   - "打开位置" 调 Tauri shell.open(folder) 打开导出目录到 OS 文件
 *     管理器；"打开文章" 还是跳 ArticleView
 *   - 顶栏「清除记录」按钮 —— 把当前所有 path 加入本地隐藏集合
 *     (localStorage "csm.recent.hidden.v1")，下次进来过滤掉
 *     **不动磁盘文件**（清单页清的是"显示"，不是实际文档）
 *
 * 与 RecentDocsCard 的关系：那张卡共享同一个 /api/recent 数据源，但
 * 它没接 hidden 集合（首页保持简单，10 条够用）。这里独立维护。
 *
 * 隐藏集合是单向的：清空后想恢复显示，只能 DevTools localStorage 手动
 * 清。这是有意为之 —— 给用户一个"立刻清屏"的逃生口，不做太精细的
 * undo/redo 复杂度。
 */
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";

import Card from "@/components/ui/Card.vue";
import Btn from "@/components/ui/Btn.vue";
import Icon from "@/components/ui/Icon.vue";
import Pill from "@/components/ui/Pill.vue";
import Spinner from "@/components/ui/Spinner.vue";
import { listRecent } from "@/api/client";
import { useSidecarReady } from "@/composables/useSidecarReady";
import { useToast } from "@/composables/useToast";
import { confirmDialog } from "@/composables/useConfirm";

const router = useRouter();
const toast = useToast();
const { whenReady } = useSidecarReady();

interface Doc {
  path: string;
  filename: string;
  title: string;
  template_name: string | null;
  words: number;
  modified_at: string;
  format: "markdown" | "docx";
}

const docs = ref<Doc[]>([]);
const loading = ref(true);
const error = ref<string | null>(null);

// localStorage 隐藏集合：path → true。用集合而不是数组方便 O(1) 查询。
const HIDDEN_KEY = "csm.recent.hidden.v1";
const hidden = ref<Set<string>>(loadHidden());

function loadHidden(): Set<string> {
  try {
    const raw = localStorage.getItem(HIDDEN_KEY);
    if (!raw) return new Set();
    const arr = JSON.parse(raw) as string[];
    return new Set(Array.isArray(arr) ? arr : []);
  } catch {
    return new Set();
  }
}

function saveHidden() {
  try {
    localStorage.setItem(HIDDEN_KEY, JSON.stringify([...hidden.value]));
  } catch {
    /* private-mode browsers — best effort */
  }
}

const visibleDocs = computed(() => docs.value.filter((d) => !hidden.value.has(d.path)));

function relativeTime(iso: string): string {
  try {
    const ms = Date.now() - new Date(iso).getTime();
    const m = Math.floor(ms / 60_000);
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

function fileFolder(path: string): string {
  // path 可能用 / 或 \；取到最后一个分隔符前的部分即父目录。
  const idx = Math.max(path.lastIndexOf("/"), path.lastIndexOf("\\"));
  return idx > 0 ? path.slice(0, idx) : path;
}

async function openLocation(d: Doc) {
  // 用 Tauri plugin-shell 的 open() 打开父目录到系统文件管理器
  // （Windows → Explorer，macOS → Finder）。capabilities/default.json
  // 已经放行 shell:allow-open，不需要再申请权限。
  // 浏览器 dev 模式 (不是 Tauri 窗口) 下 import 会拿不到 plugin，那
  // 时降级成 toast 显示路径让用户自己复制。
  const folder = fileFolder(d.path);
  try {
    const isTauri =
      typeof window !== "undefined" &&
      // @ts-expect-error — ambient Tauri global
      Boolean(window.__TAURI_INTERNALS__ || window.__TAURI__);
    if (!isTauri) {
      toast.info(`导出位置：${folder}`);
      return;
    }
    const { open } = await import("@tauri-apps/plugin-shell");
    await open(folder);
  } catch (e: any) {
    toast.error(`打开位置失败：${e?.message ?? e}`);
  }
}

function openDoc(_d: Doc) {
  // 跟 RecentDocsCard 同样的占位行为 —— v2 路线再接 ArticleView 的
  // "open existing" 真实入口（带 path 参数 + store 拉文件内容）。
  router.push({ name: "article" });
}

async function clearAll() {
  if (!visibleDocs.value.length) return;
  const ok = await confirmDialog(
    "确定清除当前的最近文档记录？磁盘上的文件不会被删除，只是从这个列表里隐藏。",
    {
      title: "清除最近文档记录",
      okLabel: "全部清除",
      cancelLabel: "取消",
      kind: "danger",
    },
  );
  if (!ok) return;
  for (const d of visibleDocs.value) hidden.value.add(d.path);
  // trigger reactivity（Set 突变不会自动触发 computed）
  hidden.value = new Set(hidden.value);
  saveHidden();
  toast.success("已清除显示记录");
}

async function reload() {
  loading.value = true;
  error.value = null;
  try {
    await whenReady();
    // 30 条 / 30 天，比 home 卡的 10/7 宽很多 —— 这是历史页，越全越好
    const r = await listRecent(30, 30);
    docs.value = r.documents;
  } catch (e: any) {
    error.value = e?.message ?? String(e);
  } finally {
    loading.value = false;
  }
}

onMounted(reload);
</script>

<template>
  <div class="anim-up flex h-full flex-col" style="gap: var(--density-gap)">
    <!-- header -->
    <div class="flex flex-shrink-0 items-end justify-between gap-3">
      <div>
        <button
          type="button"
          class="inline-flex items-center gap-1 text-[12px] transition hover:text-ink"
          :style="{ color: 'var(--ink-3)' }"
          @click="router.push({ name: 'home' })"
        >
          <Icon name="arrowLeft" :size="13" />
          返回工作台
        </button>
        <div
          class="font-display mt-2 font-bold"
          :style="{ fontSize: '26px', letterSpacing: '-0.5px' }"
        >
          最近文档
        </div>
        <div
          class="mt-1 text-[12px]"
          :style="{ color: 'var(--ink-3)' }"
        >
          近 30 天 · {{ visibleDocs.length }} 篇
          <template v-if="hidden.size > 0">
            · 已隐藏 {{ hidden.size }} 条
          </template>
        </div>
      </div>
      <div class="flex flex-shrink-0 gap-2">
        <Btn variant="ghost" small @click="reload">
          <Icon name="refresh" :size="13" />
          <span>刷新</span>
        </Btn>
        <Btn
          variant="ghost"
          small
          :disabled="!visibleDocs.length"
          @click="clearAll"
        >
          <Icon name="trash" :size="13" />
          <span>清除记录</span>
        </Btn>
      </div>
    </div>

    <!-- body -->
    <Card class="min-h-0 flex-1 overflow-y-auto">
      <div v-if="loading" class="flex items-center justify-center py-12">
        <Spinner :size="18" />
      </div>
      <div
        v-else-if="error"
        class="py-12 text-center text-[12.5px]"
        :style="{ color: 'var(--red)' }"
      >
        加载失败：{{ error }}
      </div>
      <div
        v-else-if="!visibleDocs.length"
        class="flex flex-col items-center justify-center py-16"
      >
        <Icon name="fileText" :size="28" :style="{ color: 'var(--ink-3)' }" />
        <div class="mt-3 text-[13px]" :style="{ color: 'var(--ink-2)' }">
          {{ docs.length ? "记录已清空" : "近 30 天内没有导出文档" }}
        </div>
        <div class="mt-1 text-[11.5px]" :style="{ color: 'var(--ink-3)' }">
          {{
            docs.length
              ? "如需恢复显示，请到 localStorage 删 csm.recent.hidden.v1"
              : "回到工作台输入关键词起飞一篇试试"
          }}
        </div>
      </div>

      <div v-else class="flex flex-col gap-2">
        <div
          v-for="d in visibleDocs"
          :key="d.path"
          class="flex items-center gap-3 transition"
          :style="{
            padding: '12px 14px',
            borderRadius: 'var(--radius-inner)',
            background: 'var(--card-2)',
            border: '1px solid var(--line)',
          }"
        >
          <span
            class="inline-flex flex-shrink-0 items-center justify-center"
            :style="{
              width: '32px',
              height: '32px',
              borderRadius: '9px',
              background: 'var(--yellow-soft)',
              color: '#7a5400',
            }"
          >
            <Icon name="fileText" :size="14" />
          </span>
          <div class="min-w-0 flex-1">
            <div class="truncate text-[13px] font-semibold">{{ d.title }}</div>
            <div
              class="font-mono mt-0.5 truncate text-[10.5px]"
              :style="{ color: 'var(--ink-3)' }"
              :title="d.path"
            >
              {{ d.path }}
            </div>
            <div
              class="mt-1 flex items-center gap-2 text-[10.5px]"
              :style="{ color: 'var(--ink-3)' }"
            >
              <Pill :tone="d.format === 'docx' ? 'primary' : 'info'">
                {{ d.format === "docx" ? "DOCX" : "Markdown" }}
              </Pill>
              <span>{{ d.template_name ?? "—" }}</span>
              <span>·</span>
              <span>{{ d.words.toLocaleString() }} 字</span>
              <span>·</span>
              <span>{{ relativeTime(d.modified_at) }}</span>
            </div>
          </div>
          <div class="flex flex-shrink-0 items-center gap-2">
            <Btn variant="ghost" small @click="openLocation(d)">
              <Icon name="folder" :size="12" />
              <span>打开位置</span>
            </Btn>
            <Btn variant="ghost" small @click="openDoc(d)">
              <Icon name="edit" :size="12" />
              <span>打开</span>
            </Btn>
          </div>
        </div>
      </div>
    </Card>
  </div>
</template>
