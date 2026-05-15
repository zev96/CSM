# -*- mode: python ; coding: utf-8 -*-

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'PyQt6', 'PyQt5', 'PySide2', 'PySide6',
              'qfluentwidgets', 'pytest', 'numpy', 'scipy'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='updater',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    # console=False → no black cmd window when the updater takes over.
    # Output still goes to %TEMP%\csm_update\updater.log via the file
    # handler in main._setup_logging. Errors are not surfaced to the
    # user via UI — the app silently relaunches the old version on
    # failure. To re-enable interactive error display, switch back to
    # console=True and the input() prompt in main() will fire.
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
