# -*- mode: python ; coding: utf-8 -*-
import os

assets_path = os.path.join(os.path.dirname(os.path.abspath('reward_tracker.py')), 'assets')
datas = [(assets_path, 'assets')] if os.path.isdir(assets_path) else []

a = Analysis(
    ['reward_tracker.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=['pynput.keyboard._darwin', 'pynput.mouse._darwin'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='奖励追踪器',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name='奖励追踪器',
)

app = BUNDLE(
    coll,
    name='奖励追踪器.app',
    bundle_identifier='com.rewardtracker.v3',
    info_plist={
        'NSHighResolutionCapable': True,
        'LSUIElement': False,
        'CFBundleShortVersionString': '3.0',
    },
)
