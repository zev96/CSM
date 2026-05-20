import { ref } from "vue";

/**
 * Stale-request guard for async work whose result may be obsolete by the
 * time it resolves. The canonical motivating case (audit C7): a component
 * with `watch(selection, () => load())` fires `load()` repeatedly as the
 * user clicks rapidly through tabs / platforms. Without a guard the
 * responses race; the last to resolve wins regardless of which selection
 * is current.
 *
 * Pattern:
 *
 * ```ts
 * const guard = useStaleGuard()
 *
 * async function load() {
 *   const my = guard.issue()
 *   const data = await fetch(...)
 *   if (guard.isStale(my)) return  // a newer call superseded us
 *   state.value = data
 * }
 * ```
 *
 * Use **one guard per logical request stream**. Sharing one guard across
 * unrelated streams (e.g. "load tasks" and "load results") would make
 * one cancel the other for no reason.
 *
 * The token is exposed read-only so callers can persist it across nested
 * awaits without re-issuing (`if (guard.isStale(my)) return` is the
 * intended ergonomics).
 */
export function useStaleGuard() {
  const token = ref(0);

  function issue(): number {
    token.value += 1;
    return token.value;
  }

  function isStale(my: number): boolean {
    return my !== token.value;
  }

  return { issue, isStale, token };
}
