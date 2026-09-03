<script setup lang="ts">
/**
 * 腾讯文档同步设置卡（评论工作流 P3）。
 *
 * 三个配置项：
 *   - enabled / doc_url → PATCH /api/config { tencent_docs: {...} }（深合并）
 *   - token → POST /api/keyring/tencent_docs（keyring，永不回显）
 *     token 从 https://docs.qq.com/scenario/open-claw.html 获取（官方
 *     「腾讯文档 Skill」页面），泄露可在该页作废重置。
 *   - 「测试连接」→ POST /api/mining/tencent_docs/test 读表头验证 token/
 *     链接/列名映射，绿灯即可在引流页一键同步。
 */
import { onMounted, ref } from "vue";

import Btn from "@/components/ui/Btn.vue";
import Icon from "@/components/ui/Icon.vue";
import Pill from "@/components/ui/Pill.vue";
import Spinner from "@/components/ui/Spinner.vue";
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
const testing = ref(false);

interface TestResultSheet {
  platform: string;
  platform_label: string;
  sheet_name: string;
  matched_by_name: boolean;
  missing: string[];
}

interface TestResult {
  ok: boolean;
  sheet_name?: string;
  header?: string[];
  sheets?: TestResultSheet[];   // 每平台路由到哪张子表 + 缺列情况
  missing?: string[];
  detail?: string;   // 错误路径（400/502 结构化错误）
}
const testResult = ref<TestResult | null>(null);

function syncFromConfig() {
  const td = (cfg.data?.tencent_docs ?? {}) as Record<string, any>;
  enabled.value = !!td.enabled;
  docUrl.value = String(td.doc_url ?? "");
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

async function onSaveUrl() {
  if (savingUrl.value) return;
  savingUrl.value = true;
  try {
    await cfg.patch({ tencent_docs: { doc_url: docUrl.value.trim() } });
    toast.success("表格链接已保存");
    testResult.value = null;
  } catch (e: any) {
    toast.error("保存失败");
  } finally {
    savingUrl.value = false;
  }
}

async function onSaveToken() {
  const v = tokenInput.value.trim();
  if (!v || savingToken.value) return;
  savingToken.value = true;
  try {
    await sidecar.client.post("/api/keyring/tencent_docs", { value: v });
    hasToken.value = true;
    tokenInput.value = "";
    testResult.value = null;
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
    testResult.value = null;
    toast.success("Token 已删除");
  } catch {
    toast.error("删除失败");
  }
}

async function onTest() {
  if (testing.value) return;
  testing.value = true;
  testResult.value = null;
  try {
    const resp = await sidecar.client.post<TestResult>("/api/mining/tencent_docs/test");
    testResult.value = resp.data;
  } catch (e: any) {
    const data = e?.response?.data;
    testResult.value = { ok: false, detail: data?.detail ?? "连接失败，请检查网络" };
  } finally {
    testing.value = false;
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
          审核通过的评论一键追加到与兼职共享的在线表格（按表头列名自动对齐）
        </div>
      </div>
      <FormToggle :model-value="enabled" @update:model-value="onToggleEnabled"/>
    </div>

    <div v-if="loading" class="mt-4 flex items-center gap-2 text-[12px]" :style="{ color: 'var(--ink-3)' }">
      <Spinner :size="12"/><span>读取中…</span>
    </div>

    <template v-else>
      <!-- 表格链接 -->
      <div class="mt-4">
        <div class="text-[11.5px] font-semibold mb-1.5">表格链接</div>
        <div class="flex items-center gap-2">
          <input
            v-model="docUrl"
            placeholder="https://docs.qq.com/sheet/xxxx?tab=xxxx"
            class="flex-1 outline-none"
            style="background: var(--card-white); border: 1px solid var(--line-2); border-radius: 10px; padding: 0 12px; height: 36px; font-size: 12px; color: var(--ink);"
          />
          <Btn variant="solid" small :disabled="savingUrl" @click="onSaveUrl">
            {{ savingUrl ? "保存中…" : "保存" }}
          </Btn>
        </div>
        <div class="mt-1 text-[11px]" :style="{ color: 'var(--ink-3)' }">
          链接带 ?tab= 时锁定该子表；不带则用第一张工作表
        </div>
      </div>

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

      <!-- 测试连接 -->
      <div class="mt-4">
        <Btn variant="ghost" small :disabled="testing || !hasToken || !docUrl.trim()" @click="onTest">
          <Spinner v-if="testing" :size="11"/>
          <span>{{ testing ? "连接中…" : "测试连接" }}</span>
        </Btn>

        <div
          v-if="testResult"
          class="mt-2 text-[11.5px] leading-relaxed"
          :style="{
            background: testResult.ok ? 'rgba(122,155,94,0.10)' : 'rgba(216,90,72,0.08)',
            border: '1px solid ' + (testResult.ok ? 'rgba(122,155,94,0.32)' : 'rgba(216,90,72,0.30)'),
            borderRadius: '10px',
            padding: '10px 12px',
            color: 'var(--ink-2)',
            whiteSpace: 'pre-line',
          }"
        >
          <template v-if="testResult.sheets?.length">
            <div>{{ testResult.ok ? "✅ 连接成功，各平台将写入：" : "⚠️ 已连上，但有问题：" }}</div>
            <div v-for="s in testResult.sheets" :key="s.platform" class="mt-0.5">
              {{ s.platform_label }} → 子表「{{ s.sheet_name }}」
              <template v-if="!s.matched_by_name">（未找到同名子表，回落到此表）</template>
              <template v-if="s.missing.length">
                · <b style="color: var(--red);">缺列：{{ s.missing.join("、") }}</b>
              </template>
            </div>
            <div v-if="!testResult.ok" class="mt-1" :style="{ color: 'var(--ink-3)' }">
              表头参考：{{ (testResult.header ?? []).join(" | ") }}
            </div>
          </template>
          <template v-else>
            ❌ {{ testResult.detail || "连接失败" }}
          </template>
        </div>
      </div>
    </template>
  </div>
</template>
