# PyInstaller build for Windows:  pyinstaller callout.spec --noconfirm
# Produces dist/Callout/Callout.exe (a folder build; starts faster than one-file).

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

datas = [("assets", "assets")]
datas += collect_data_files("faster_whisper")  # bundled Silero VAD model

binaries = collect_dynamic_libs("ctranslate2")

hiddenimports = (
    collect_submodules("huggingface_hub")
    + ["hf_xet", "proctap._native", "pyaudiowpatch", "soxr", "psutil"]
)

a = Analysis(
    ["run.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=[
        "scipy",  # only used by proc-tap's optional resampler; we resample with soxr
        "tkinter",
        "matplotlib",
        "IPython",
        "pytest",
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtQml",
        "PySide6.QtQuick",
        "PySide6.Qt3DCore",
        "PySide6.QtMultimedia",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Callout",
    icon="assets/icon.ico",
    console=False,
    upx=False,
    version=None,
)
coll = COLLECT(exe, a.binaries, a.datas, name="Callout", upx=False)
