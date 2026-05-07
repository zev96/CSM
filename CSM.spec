# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

datas = [
    ('csm_gui/assets', 'csm_gui/assets'),
    ('examples', 'examples'),
    ('templates', 'templates'),
    ('README.md', '.'),
]
datas += collect_data_files('qfluentwidgets')
datas += collect_data_files('PyQt6')
datas += collect_data_files('docx')
datas += collect_data_files('anthropic')

hiddenimports = [
    'csm_gui',
    'csm_core',
    'docx',
    'frontmatter',
    'anthropic',
    'httpx',
    'tenacity',
    'pydantic',
    'click',
    # LLM providers are conditionally imported inside make_client();
    # list them so PyInstaller bundles every provider.
    'csm_core.llm.providers.mock',
    'csm_core.llm.providers.anthropic',
    'csm_core.llm.providers.openai',
    'csm_core.llm.providers.openai_compat',
    'csm_core.llm.providers.deepseek',
    'csm_core.llm.providers.gemini',
    'csm_core.llm.providers.qwen',
]
hiddenimports += collect_submodules('docx')
hiddenimports += collect_submodules('qfluentwidgets')
hiddenimports += collect_submodules('anthropic')


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'pytest', 'PyQt5', 'PySide2', 'PySide6'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='CSM',
    icon='csm_gui/assets/csm.ico',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='CSM',
)
