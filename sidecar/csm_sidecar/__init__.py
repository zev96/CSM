"""CSM Sidecar — FastAPI service that wraps csm_core for the Tauri frontend.

The ``__version__`` here MUST stay in lock-step with
``frontend/src-tauri/tauri.conf.json::version`` and
``frontend/src-tauri/Cargo.toml [package].version``. ``release.py`` bumps
all three together — don't edit by hand outside of a release cut.

It's the source of truth for ``/api/system/version`` and the
``current_version`` field returned by ``/api/updater/check``, which the
update modal shows to the user as "当前 vX.Y.Z".
"""

__version__ = "0.6.5"
