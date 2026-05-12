/**
 * Lightweight reactive flag that says "is the sidecar ready to take
 * requests?" — views use this to gate their initial fetches so they
 * don't spam 401s during the brief window between mount and bootstrap.
 */
import { computed, watch } from "vue";

import { useSidecar } from "@/stores/sidecar";

export function useSidecarReady() {
  const sidecar = useSidecar();
  const ready = computed(() => sidecar.ready);
  const error = computed(() => sidecar.error);

  /** Resolve once the sidecar is ready. Throws if it errors out first. */
  function whenReady(): Promise<void> {
    if (sidecar.ready) return Promise.resolve();
    if (sidecar.error) return Promise.reject(new Error(sidecar.error));
    return new Promise((resolve, reject) => {
      const stop = watch(
        () => [sidecar.ready, sidecar.error] as const,
        ([r, e]) => {
          if (r) {
            stop();
            resolve();
          } else if (e) {
            stop();
            reject(new Error(e));
          }
        },
        { immediate: false },
      );
    });
  }

  return { ready, error, whenReady, mode: computed(() => sidecar.mode) };
}
