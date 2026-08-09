# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path


oauth_client = Path("local_credentials/google_oauth_client.json")
oauth_datas = [(str(oauth_client), "oauth")] if oauth_client.exists() else []
splash_image = Path("assets/splash_default.png")
splash_datas = [(str(splash_image), "assets")] if splash_image.exists() else []
app_icon_png = Path("assets/app_icon.png")
app_icon_ico = Path("assets/pomodoro_overlay.ico")
icon_datas = [(str(app_icon_png), "assets")] if app_icon_png.exists() else []
skin_dir = Path("assets/skins")
skin_datas = [
    (str(skin_image), "assets/skins")
    for skin_image in sorted(skin_dir.glob("*.png"), key=lambda path: path.name)
]

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=oauth_datas + splash_datas + icon_datas + skin_datas,
    hiddenimports=[],
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
    a.binaries,
    a.datas,
    [],
    name='PomodoroOverlay',
    icon=str(app_icon_ico) if app_icon_ico.exists() else None,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=True,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
