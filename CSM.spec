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
# tldextract ships a bundled suffix-list snapshot used by geo/classify.py in
# offline mode (suffix_list_urls=()). Include its data files so the snapshot
# is present in the bundle.
datas += collect_data_files('tldextract')

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
    'datasketch',
    'datasketch.minhash',
    'datasketch.lsh',
    # LLM providers are conditionally imported inside make_client();
    # list them so PyInstaller bundles every provider.
    'csm_core.llm.providers.mock',
    'csm_core.llm.providers.anthropic',
    'csm_core.llm.providers.openai',
    'csm_core.llm.providers.openai_compat',
    'csm_core.llm.providers.deepseek',
    'csm_core.llm.providers.gemini',
    'csm_core.llm.providers.qwen',
    # Dedup module
    'csm_core.dedup',
    'csm_core.dedup.shingles',
    'csm_core.dedup.corpus',
    'csm_core.dedup.index',
    'csm_core.dedup.analyzer',
    'csm_core.dedup.report',
    # Tray module (feature 1)
    'csm_gui.tray',
    'csm_gui.tray.manager',
    'csm_gui.tray.menu',
    'csm_gui.tray.icon',
    'csm_gui.tray.single_instance',
    # Workers
    'csm_gui.workers.dedup_worker',
    'csm_gui.workers.update_check_worker',
    # Widgets
    'csm_gui.widgets.dedup_panel',
    'csm_gui.widgets.dedup_drill_dialog',
    'csm_gui.widgets.update_dialog',
    'csm_gui.widgets.update_progress_dialog',
    # Updater client
    'csm_core.updater_client',
    'csm_core.updater_client.manifest',
    'csm_core.updater_client.checker',
    'csm_core.updater_client.downloader',
    'csm_core.updater_client.github_client',
    # _token.py is created by CI at build time; the import is inside a
    # try/except in main_window which PyInstaller's static analyzer
    # sometimes skips. List explicitly so it's always bundled.
    'csm_core.updater_client._token',
    # Version
    'csm_gui._version',
    # tldextract: GEO 信源域名规整（csm_core/monitor/geo/classify.py）。
    'tldextract',
]
hiddenimports += collect_submodules('docx')
hiddenimports += collect_submodules('qfluentwidgets')
hiddenimports += collect_submodules('anthropic')
hiddenimports += collect_submodules('datasketch')


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
