# -*- mode: python ; coding: utf-8 -*-
# Run from repo root: pyinstaller build/synclight.spec --noconfirm
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files

ROOT = Path(SPECPATH).parent  # repo root (one level above build/)

block_cipher = None

a = Analysis(
    [str(ROOT / 'synclight_app.py')],
    pathex=[str(ROOT)],
    binaries=[],
    datas=(
        collect_data_files('flask') +
        collect_data_files('jinja2')
    ),
    hiddenimports=[
        'pystray._win32',
        'pystray._util',
        'pystray._util.win32',
        'flask.sansio',
        'flask.sansio.app',
        'flask.sansio.blueprints',
        'flask.sansio.scaffold',
        'werkzeug.routing.rules',
        'werkzeug.routing.matcher',
        'werkzeug.routing.map',
        'PIL.IcoImagePlugin',
        'blinker',
        'itsdangerous',
        'six',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'numpy', 'scipy', 'pytest'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='synclight',
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
    icon=str(ROOT / 'assets' / 'icon.ico'),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='synclight',
)
