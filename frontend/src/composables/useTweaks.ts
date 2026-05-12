/**
 * Runtime design-token tweaks — radius / density / primary colour.
 *
 * Mirrors the React prototype's TweaksPanel: writes to ``document.body``
 * data-attributes and the ``--primary`` CSS variable so the change is
 * visible immediately. Persisted in localStorage so reloads remember.
 */
import { onMounted, reactive, watch } from "vue";

export type Radius = "tight" | "medium" | "bold";
export type Density = "compact" | "cozy" | "loose";

interface Tweaks {
  radius: Radius;
  density: Density;
  primary: string;
}

const DEFAULTS: Tweaks = {
  radius: "medium",
  density: "cozy",
  primary: "#ee6a2a",
};

const STORAGE_KEY = "csm.tweaks.v1";

const state = reactive<Tweaks>({ ...DEFAULTS });

function apply() {
  if (typeof document === "undefined") return;
  document.body.dataset.radius = state.radius;
  document.body.dataset.density = state.density;
  document.documentElement.style.setProperty("--primary", state.primary);
}

function load() {
  if (typeof localStorage === "undefined") return;
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return;
    const parsed = JSON.parse(raw);
    if (parsed.radius) state.radius = parsed.radius;
    if (parsed.density) state.density = parsed.density;
    if (parsed.primary) state.primary = parsed.primary;
  } catch {
    /* ignore corrupt storage */
  }
}

function save() {
  if (typeof localStorage === "undefined") return;
  localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
}

let booted = false;

export function useTweaks() {
  onMounted(() => {
    if (booted) return;
    booted = true;
    load();
    apply();
    watch(state, () => {
      apply();
      save();
    });
  });

  function reset() {
    Object.assign(state, DEFAULTS);
  }

  return { state, reset };
}
