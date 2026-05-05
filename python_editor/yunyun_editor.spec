from pathlib import Path

from PyInstaller.utils.hooks import collect_dynamic_libs


project_dir = Path(SPECPATH)

binaries = []
binaries += collect_dynamic_libs("sounddevice")
binaries += collect_dynamic_libs("soundfile")

datas = [
    (str(project_dir / "assets" / "audio" / "NoteTick.ogg"), "assets/audio"),
    (str(project_dir / "assets" / "yunIcon.ico"), "assets"),
]

a = Analysis(
    [str(project_dir / "run_yunyun_editor.py")],
    pathex=[str(project_dir / "src")],
    binaries=binaries,
    datas=datas,
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
    [],
    exclude_binaries=True,
    name="YunYunEditor",
    icon=str(project_dir / "assets" / "yunIcon.ico"),
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="YunYunEditor",
)