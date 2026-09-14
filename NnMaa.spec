# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
import sys

from PyInstaller.utils.hooks import collect_all


maa_datas, maa_binaries, maa_hiddenimports = collect_all('maa')
agent_binary_dir = Path(sys.prefix) / 'Lib' / 'site-packages' / 'MaaAgentBinary'

a = Analysis(
    ['tools\\qt_workbench.py'],
    pathex=['tools'],
    binaries=maa_binaries,
    datas=[
        (str(agent_binary_dir), 'MaaAgentBinary'),
        *maa_datas,
    ],
    hiddenimports=[*maa_hiddenimports, 'job_runner', 'job_model', 'job_library', 'semantic_navigator', 'asset_model', 'asset_page', 'clothing_memory', 'stage_model', 'stage_navigator', 'scrcpy_input', 'pipeline_cli'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='NnMaa',
    icon='assets\\icons\\nnmaa.ico',
    version='assets\\windows_version_info.txt',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
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
    upx=True,
    upx_exclude=[],
    name='NnMaa',
)
