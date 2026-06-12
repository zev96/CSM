/**
 * Runtime design-token tweaks — radius / density / primary colour / theme.
 *
 * Mirrors the React prototype's TweaksPanel: writes to ``document.body``
 * data-attributes and the ``--primary`` CSS variable so the change is
 * visible immediately. Persisted in localStorage so reloads remember.
 */
import { onMounted, reactive, watch } from "vue";

export type Radius = "tight" | "medium" | "bold";
export type Density = "compact" | "cozy" | "loose";
export type Theme = "system" | "light" | "dark";

interface Tweaks {
  radius: Radius;
  density: Density;
  primary: string;
  theme: Theme;
}

const DEFAULTS: Tweaks = {
  radius: "medium",
  density: "cozy",
  primary: "#ee6a2a",
  theme: "system",
};

const STORAGE_KEY = "csm.tweaks.v1";

const state = reactive<Tweaks>({ ...DEFAULTS });

/** 把用户偏好 + 系统是否暗色，解析成实际生效主题。纯函数，便于测试。 */
export function effectiveTheme(pref: Theme, prefersDark: boolean): "light" | "dark" {
  return pref === "system" ? (prefersDark ? "dark" : "light") : pref;
}

function systemPrefersDark(): boolean {
  return (
    typeof window !== "undefined" &&
    !!window.matchMedia &&
    window.matchMedia("(prefers-color-scheme: dark)").matches
  );
}

function apply() {
  if (typeof document === "undefined") return;
  document.body.dataset.radius = state.radius;
  document.body.dataset.density = state.density;
  document.body.dataset.theme = effectiveTheme(state.theme, systemPrefersDark());
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
    if (parsed.theme === "system" || parsed.theme === "light" || parsed.theme === "dark") {
      state.theme = parsed.theme;
    }
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
    if (typeof window !== "undefined" && window.matchMedia) {
      window
        .matchMedia("(prefers-color-scheme: dark)")
        .addEventListener("change", () => {
          if (state.theme === "system") apply();
        });
    }
  });

  function reset() {
    Object.assign(state, DEFAULTS);
  }

  return { state, reset };
}
