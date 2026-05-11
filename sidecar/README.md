# CSM Sidecar

FastAPI service that exposes `csm_core` capabilities to the Tauri + Vue 3
frontend over local HTTP + SSE. See the migration plan
(`docs/migration/`) for the full architecture context.

## Layout

```
sidecar/
├── pyproject.toml
├── csm_sidecar/
│   ├── main.py             # uvicorn entry, handshake, run()
│   ├── auth.py             # Bearer-token guard
│   ├── lifespan.py         # port pick + stdout handshake
│   ├── events.py           # SSE bus (stage A3)
│   ├── routes/
│   │   └── system.py       # /health, /api/version, /api/shutdown
│   └── services/           # Thin wrappers around csm_core (stage A3)
└── tests/
    └── test_health.py
```

## Run (dev)

```powershell
# from repo root
pip install -e .                      # parent project, gives us csm_core
pip install -e sidecar[dev]           # sidecar's own deps + test tools
python -m csm_sidecar.main            # mimics how Tauri spawns it
# or, with hot reload:
uvicorn csm_sidecar.main:app --reload --port 8765
```

The first stdout line on `python -m` start is the handshake JSON Tauri
consumes — `{"port": 12345, "token": "...", "version": 1}`.

## Test

```powershell
pytest sidecar/tests/
```
