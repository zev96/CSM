# Frontend assets

## `logo.png`

The application logo used in:

- LeftNav top-left (44 × 44 rounded square)
- Settings → 关于 header (56 × 56 rounded square)

**Recommended source size:** 1024 × 1024 PNG, transparent background,
content centred with ~10% padding on all sides. The image is rendered
`object-fit: contain` inside a rounded mask, so a square source avoids
distortion.

## Regenerating Tauri task icons

The Tauri runtime ships its own platform-specific icons (`.ico`,
`.icns`, multiple PNG sizes for Windows / Linux / Android / iOS) which
live under `frontend/src-tauri/icons/`. **These are separate from the
in-app `logo.png`** — replacing `logo.png` does NOT update the taskbar
icon, dock icon, or installer icon.

To regenerate the whole set from `logo.png`:

```bash
cd frontend
npx @tauri-apps/cli icon src/assets/logo.png
```

That command overwrites every file in `src-tauri/icons/` from one
source image. A subsequent `npm run tauri:build` (or `tauri:dev`)
picks them up automatically.
