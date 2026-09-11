# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
import site
import sys

from PyInstaller.utils.hooks import collect_all


def find_site_package_dir(name):
    candidates = []
    try:
        candidates.extend(site.getsitepackages())
    except AttributeError:
        pass
    try:
        candidates.append(site.getusersitepackages())
    except AttributeError:
        pass
    candidates.extend(sys.path)

    seen = set()
    for base in candidates:
        if not base:
            continue
        root = Path(base)
        if root in seen:
            continue
        seen.add(root)
        candidate = root / name
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"Cannot find site-package directory: {name}")


maa_datas, maa_binaries, maa_hiddenimports = collect_all("maa")
agent_binary_dir = find_site_package_dir("MaaAgentBinary")

a = Analysis(
    ["tools/qt_workbench.py"],
    pathex=["tools"],
    binaries=maa_binaries,
    datas=[
        (str(agent_binary_dir), "MaaAgentBinary"),
        *maa_datas,
    ],
    hiddenimports=[
        *maa_hiddenimports,
        "job_runner",
        "job_model",
        "job_library",
        "semantic_navigator",
        "asset_model",
        "asset_page",
        "clothing_memory",
        "stage_model",
        "stage_navigator",
    ],
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
    name="Qdd",
    icon="assets/icons/qdd.icns",
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
    name="Qdd",
)
