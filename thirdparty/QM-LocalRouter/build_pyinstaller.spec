# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the LocalRouter one-file release build.

Run with:  pyinstaller build_pyinstaller.spec --noconfirm

Cross-platform: the same spec works on Linux, macOS and Windows. litellm
loads its provider modules via importlib at runtime, so we pull the whole
package in with collect_all(); heavy optional ML deps (torch/tensorflow/...)
are not installed by backend/requirements.txt and are therefore skipped.
"""
import os

from PyInstaller.utils.hooks import collect_all

block_cipher = None

# litellm is the routing kernel and imports providers lazily -> collect all.
litellm_datas, litellm_bins, litellm_hiddenimports = collect_all("litellm")

a = Analysis(
    ["backend/launcher.py"],
    pathex=["backend"],
    binaries=litellm_bins,
    # version.json is generated at release-build time (see build-release.yml) and
    # carries the git tag/commit so the frozen exe reports a real version.
    datas=litellm_datas + ([("version.json", ".")] if os.path.exists("version.json") else []),
    hiddenimports=[
        "app",
        "app.routers",
        "app.services",
        "app.services.cline",
        "app.services.opencode",
        "app.services.workbuddy",
    ] + litellm_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "torch",
        "tensorflow",
        "tensorflow-cpu",
        "jax",
        "mxnet",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="apirouter",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
