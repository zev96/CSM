"""``python -m csm_sidecar`` entry point.

PyInstaller's spec uses this file as the analysis entry, so the bundled
binary's ``main()`` is just ``csm_sidecar.main.run()``. Keep it tiny.
"""
from csm_sidecar.main import run


if __name__ == "__main__":
    run()
