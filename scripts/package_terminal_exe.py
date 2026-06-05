from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXE = ROOT / "DxmTemuTerminalRobot.exe"
LEGACY_CODE = ROOT / "work" / "extracted_terminal_app.pyc"
BASE_CODE = ROOT / "work" / "terminal_app_base.pyc"
PACKAGE_DIR = ROOT / "dist" / "DxmTemuTerminalRobot"
PACKAGE_IGNORE_NAMES = {
    "Cache",
    "Code Cache",
    "GPUCache",
    "GrShaderCache",
    "ShaderCache",
    "DawnCache",
    "Crashpad",
    "BrowserMetrics",
    "OptimizationGuidePredictionModels",
    "OptGuideOnDeviceModel",
    "component_crx_cache",
    "Safe Browsing",
    "GraphiteDawnCache",
}
PACKAGE_IGNORE_FILE_SUFFIXES = {".tmp", ".log"}


def package_ignore(_directory: str, names: list[str]) -> set[str]:
    ignored: set[str] = set()
    for name in names:
        if name in PACKAGE_IGNORE_NAMES:
            ignored.add(name)
            continue
        if any(name.endswith(suffix) for suffix in PACKAGE_IGNORE_FILE_SUFFIXES):
            ignored.add(name)
    return ignored


def main() -> None:
    if not LEGACY_CODE.exists():
        raise FileNotFoundError(f"缺少旧版完整程序模块：{LEGACY_CODE}")
    if not BASE_CODE.exists():
        raise FileNotFoundError(f"缺少机器人基座程序：{BASE_CODE}")
    build_dir = ROOT / "build" / "DxmTemuTerminalRobot"
    generated = ROOT / "dist" / "DxmTemuTerminalRobot.exe"
    for path in (build_dir, PACKAGE_DIR):
        if path.exists():
            shutil.rmtree(path)
    if generated.exists():
        generated.unlink()
    spec = ROOT / "DxmTemuTerminalRobot.spec"
    if spec.exists():
        spec.unlink()
    subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--onefile",
            "--clean",
            "--name",
            "DxmTemuTerminalRobot",
            "--collect-all",
            "playwright",
            "--hidden-import",
            "tkinter",
            "--hidden-import",
            "tkinter.ttk",
            "--hidden-import",
            "tkinter.filedialog",
            "--hidden-import",
            "tkinter.messagebox",
            "--add-data",
            f"{LEGACY_CODE};.",
            "--add-data",
            f"{BASE_CODE};.",
            "terminal_app.py",
        ],
        cwd=ROOT,
        check=True,
    )
    if EXE.exists():
        EXE.unlink()
    shutil.move(str(generated), str(EXE))
    if build_dir.exists():
        shutil.rmtree(build_dir)
    if spec.exists():
        spec.unlink()
    PACKAGE_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy2(EXE, PACKAGE_DIR / EXE.name)
    shutil.copytree(ROOT / "work", PACKAGE_DIR / "work", dirs_exist_ok=True, ignore=package_ignore)
    print(f"已生成: {EXE}")
    print(f"已生成运行包: {PACKAGE_DIR}")


if __name__ == "__main__":
    main()
