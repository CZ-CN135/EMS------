# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['ems_waveform_viewer/app.py'],
    pathex=['.'],
    binaries=[],
    datas=[('竖曲线.ico', '.')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'matplotlib',
        'PySide6.QtTest',
        'OpenGL',
        'openpyxl',
        'et_xmlfile',
        'scipy',
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='EMS录波曲线工具',
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
    icon=['竖曲线.ico'],
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name='EMS录波曲线工具-快速启动',
)
