/**
 * 事实变更 session 级 store（§7.2）——App 启动 + 重建索引后拉 /api/facts/changes，
 * 累积「参数已更新」的型号集，供素材库型号行显示 Pill。会话级、不持久化。
 */
import { defineStore } from "pinia";

import { factsChanges as fetchFactsChanges, type ModelChange } from "@/api/client";

interface FactsChangesState {
  changes: ModelChange[];
  staleModels: string[];
}

export const useFactsChanges = defineStore("factsChanges", {
  state: (): FactsChangesState => ({ changes: [], staleModels: [] }),
  getters: {
    count: (s): number => s.staleModels.length,
    // 用普通数组 + includes（比 Set 在 Pinia 里响应式更稳）。
    isStale: (s) => (model: string): boolean => s.staleModels.includes(model),
  },
  actions: {
    ingest(changes: ModelChange[]) {
      for (const c of changes) {
        if (!this.staleModels.includes(c.model)) this.staleModels.push(c.model);
        this.changes.push(c);
      }
    },
    /** 拉一次变更并累积。fail-safe：非关键数据，失败静默返回 []。 */
    async pull(): Promise<ModelChange[]> {
      try {
        const r = await fetchFactsChanges();
        if (r.changes?.length) this.ingest(r.changes);
        return r.changes ?? [];
      } catch {
        return [];
      }
    },
  },
});
