# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files

block_cipher = None

a = Analysis(
    ['synclight_app.py'],
    pathex=[],
    binaries=[],
    datas=(
        collect_data_files('flask') +
        collect_data_files('jinja2')
    ),
    hiddenimports=[
        # pystray Windows backend
        'pystray._win32',
        'pystray._util',
        'pystray._util.win32',
        # Flask 3.x split subpackages
        'flask.sansio',
        'flask.sansio.app',
        'flask.sansio.blueprints',
        'flask.sansio.scaffold',
        'werkzeug.routing.rules',
        'werkzeug.routing.matcher',
        'werkzeug.routing.map',
        # Pillow plugin
        'PIL.IcoImagePlugin',
        # Indirect deps
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
    icon='assets/icon.ico',
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
