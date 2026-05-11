# Migration: PyQt6 → Tauri + Vue 3 + Python Sidecar

This folder holds the working artefacts for the v0.4 architecture
migration. The authoritative plan lives at
`C:\Users\EDY\.claude\plans\python-seo-sharded-sparrow.md`; the files
here are the executable / reviewable outputs.

## Stage A — sidecar + alignment

| File | Purpose | Status |
|---|---|---|
| `feature-ui-mapping.md` | Cross-table of `csm_core/` capabilities × CSM-RE1 V1 screens. Source of truth for what each Vue view needs and what `csm_core` can supply. | **A2 — to fill** |
| `api-contract.openapi.yaml` | Sidecar HTTP/SSE contract derived from the mapping. Generated/maintained alongside `sidecar/`. | A3 — to draft |

## Stage B/C/D

To be added when those phases start.
