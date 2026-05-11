# CSM Frontend

Tauri 2 shell + Vue 3 + TypeScript + Vite + Tailwind. Talks to the Python
[sidecar](../sidecar/) over local HTTP + SSE.

Stage status: **B1–B3 + C1 complete** — full UI, system tray, single-instance
lock, and file logging are wired. C2 (PyInstaller packaging + NSIS bundle)
is what runs the production build below.

## Layout

```
frontend/
├── package.json
├── vite.config.ts          # Tauri-aware dev server
├── tailwind.config.js      # CSS-var-driven palette
├── tsconfig.json
├── postcss.config.js
├── index.html
├── env.d.ts                # window.__SIDECAR__ ambient type
├── .env.example            # browser-only dev fallback
├── src/
│   ├── main.ts             # Vue + Pinia + Router boot
│   ├── App.vue             # Outer paper-card layout
│   ├── style.css           # Design tokens (ported from CSM-RE1)
│   ├── api/client.ts       # axios + SSE helpers
│   ├── stores/             # sidecar / config / article / batch
│   ├── router/index.ts     # 7 routes
│   ├── composables/        # useToast / usePathPicker / useSidecarReady / useTweaks
│   ├── components/
│   │   ├── LeftNav.vue
│   │   ├── TweaksPanel.vue
│   │   ├── ui/             # Card / Btn / Pill / Icon / Sparkline / Bars / ProgressBar / Spinner / Toast
│   │   ├── forms/          # FormInput / FormSelect / FormToggle / FormPathPicker / FormSlider / FormSection / FormField
│   │   ├── home/           # Home cards (greeting / hero / calendar / alerts / retention / recents / quick)
│   │   ├── settings/       # 8 sections + ProviderCard
│   │   ├── monitor/        # AddTaskModal + CookieManagerModal
│   │   └── templates/      # TemplateBuilder + BlockEditor
│   └── views/              # Home / Article / Batch / Monitor / Templates / Settings / States
└── src-tauri/
    ├── Cargo.toml
    ├── tauri.conf.json
    ├── build.rs
    ├── binaries/           # ★ created by scripts/build_sidecar.py — PyInstaller onedir
    └── src/
        ├── main.rs         # Entry — calls into lib.rs::run()
        ├── lib.rs          # Builder + invoke_handler + lifecycle + tray + single-instance + log
        ├── sidecar.rs      # Spawn csm-sidecar, parse handshake JSON, kill on exit
        └── tray.rs         # System tray icon, menu, click-to-toggle behaviour
```

## Prerequisites

- **Node.js 20+** (for Vite + Vue tooling)
- **Rust 1.78+** with the `cargo` toolchain (for Tauri)
- **Python 3.11+** (the sidecar — set up via the parent project)
- On Windows: WebView2 runtime (ships with Win11; auto-installer for Win10)

The first time you run `npm run tauri:dev`, Cargo will compile the Tauri
shell — expect ~2–4 min of dependency download / build. Subsequent runs
are seconds.

## Dev workflows

### A. Browser-only (no Tauri, no native shell)

UI iteration without compiling Rust. Hand-launch the sidecar, copy the
token, point Vite at it:

```powershell
# Shell 1 — sidecar:
pip install -e ../sidecar[dev]   # one-time
python -m csm_sidecar

# Note the JSON line on stdout: {"port": 12345, "token": "...", ...}
# Copy port + token into frontend/.env.local (see .env.example).

# Shell 2 — Vite:
cd frontend
npm install
npm run dev
# Open http://localhost:5173
```

System tray, single-instance, and file dialogs are unavailable in this
mode (they need the Tauri shell). Path-picker fields fall back to a
plain text prompt.

### B. Tauri (full stack)

Pre-requisite: a built sidecar bundle under `src-tauri/binaries/`. Build
it once via:

```powershell
# from the worktree root:
python scripts/build_sidecar.py
# produces: frontend/src-tauri/binaries/csm-sidecar-<triple>/
```

Then:

```powershell
cd frontend
npm install                     # first time only
npm run tauri:dev
```

Tauri spawns the bundled `csm-sidecar` automatically, captures the
handshake from its stdout, and injects `port`/`token` into the webview
via the `get_sidecar` invoke command.

## Production build (NSIS installer)

End-to-end: build sidecar → build frontend → bundle Tauri.

```powershell
# 1. Build the Python sidecar bundle (~150 MB onedir).
python scripts/build_sidecar.py --clean

# 2. Build the Tauri shell (compiles Rust + Vite + bundles NSIS).
cd frontend
npm install
npm run tauri:build
```

Output: `frontend/src-tauri/target/release/bundle/nsis/CSM_<version>_x64-setup.exe`
— ~180 MB single installer that drops both the Tauri exe and the
`csm-sidecar/` onedir into `%LOCALAPPDATA%/CSM/`.

### Build flags worth knowing

* **UPX is OFF.** Per the migration memory note (PyQt6+PyInstaller
  history) UPX broke produced binaries on Win11. Don't re-enable.
* **Console window is ON for the sidecar binary** in dev/prod —
  required so Tauri can read the handshake JSON line off stdout. The
  *user* never sees this console (Tauri spawns the sidecar with
  inherited handles, not a new console window).
* **The Tauri shell hides its console in release** via
  `windows_subsystem = "windows"` in `src-tauri/src/main.rs`.

## Behaviours wired in C1

| Concern | File |
|---|---|
| System tray (icon + menu + click-toggle) | `src-tauri/src/tray.rs` |
| Single-instance lock (focus existing window) | `src-tauri/src/lib.rs` (plugin) |
| Tauri shell file logging (`%APPDATA%/com.csm.app/logs/csm-shell.log`) | `src-tauri/src/lib.rs` |
| Sidecar file logging (`%LOCALAPPDATA%/CSM/CSM/logs/sidecar.log`) | `sidecar/csm_sidecar/logging_setup.py` |
| Sidecar heartbeat self-shutdown (10 min idle) | `sidecar/csm_sidecar/heartbeat.py` |
| Window-close → minimise to tray (X button) | `src-tauri/src/lib.rs` `WindowEvent::CloseRequested` |
| Sidecar kill on app exit | `src-tauri/src/lib.rs` `WindowEvent::Destroyed` |

## Where things live

| Concern | File |
|---|---|
| Token + axios | `src/stores/sidecar.ts` |
| Per-endpoint TS wrappers | `src/api/client.ts` |
| Design tokens | `src/style.css` (CSS variables) + `tailwind.config.js` (alias map) |
| Route definitions | `src/router/index.ts` |
| Sidecar process management | `src-tauri/src/sidecar.rs` |
| Window config | `src-tauri/tauri.conf.json` |
| Build automation | `scripts/build_sidecar.py` (sidecar) + `npm run tauri:build` (Tauri) |
