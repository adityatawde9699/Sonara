"""Build the self-contained Python inference/backend executable for this host."""

from __future__ import annotations

import argparse
import importlib.metadata
import os
from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
STAGING = ROOT / "packaging" / "staging"
RESOURCE_ROOT = STAGING / "sonara"
REQUIRED_PACKAGES = {
    "piper-tts": "1.8.0",
    "onnxruntime": "1.31.0",
    "kokoro-onnx": "0.6.1",
    "llama-cpp-python": "0.3.36",
    "pyinstaller": "6.22.3",
}
DATA_FILES = ("sonara.py", "llm_client.py", "piper_worker.py")
COLLECT_PACKAGES = (
    "piper",
    "onnxruntime",
    "kokoro_onnx",
    "llama_cpp",
    "espeakng_loader",
)
COPY_METADATA = ("piper-tts", "onnxruntime", "kokoro-onnx", "llama-cpp-python")


def verify_build_environment() -> None:
    if sys.version_info[:2] != (3, 12):
        raise SystemExit(
            f"Build the packaged runtime with Python 3.12; found {sys.version.split()[0]}."
        )
    mismatches = []
    for package, expected in REQUIRED_PACKAGES.items():
        try:
            actual = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            mismatches.append(f"{package} is not installed (expected {expected})")
            continue
        if actual != expected:
            mismatches.append(f"{package} is {actual} (expected {expected})")
    if mismatches:
        raise SystemExit("Runtime build environment is not pinned correctly:\n- " + "\n- ".join(mismatches))


def build(*, clean: bool = False) -> Path:
    verify_build_environment()
    executable_name = "sonara-runtime.exe" if os.name == "nt" else "sonara-runtime"
    RESOURCE_ROOT.mkdir(parents=True, exist_ok=True)
    if clean:
        for path in (RESOURCE_ROOT / executable_name, STAGING / "work", STAGING / "sonara-runtime.spec"):
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink(missing_ok=True)

    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--clean",
        "--noconfirm",
        "--onefile",
        "--name",
        "sonara-runtime",
        "--distpath",
        str(RESOURCE_ROOT),
        "--workpath",
        str(STAGING / "work"),
        "--specpath",
        str(STAGING),
    ]
    for filename in DATA_FILES:
        source = ROOT / filename
        command.extend(("--add-data", f"{source}{os.pathsep}."))
    for package in COLLECT_PACKAGES:
        command.extend(("--collect-all", package))
    # Piper's long-running worker is launched by filename through sys.executable
    # and therefore is not visible to PyInstaller's static import analysis.
    command.extend(("--hidden-import", "piper_worker"))
    for package in COPY_METADATA:
        command.extend(("--copy-metadata", package))
    command.append(str(Path(__file__).with_name("runtime_entry.py")))
    subprocess.run(command, cwd=ROOT, check=True)

    for filename in DATA_FILES:
        shutil.copy2(ROOT / filename, RESOURCE_ROOT / filename)
    executable = RESOURCE_ROOT / executable_name
    if not executable.is_file():
        raise SystemExit(f"PyInstaller did not create the expected runtime: {executable}")
    return executable


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clean", action="store_true", help="remove only prior generated runtime build output")
    args = parser.parse_args()
    print(build(clean=args.clean))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
