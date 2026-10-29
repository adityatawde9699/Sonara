"""Stage Poppler and Tesseract plus non-core shared libraries for Linux."""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import shutil
import subprocess


CORE_LIBRARIES = ("libc.so", "libm.so", "libpthread.so", "libdl.so", "librt.so", "ld-linux")


def dependencies(executable: Path) -> set[Path]:
    result = subprocess.run(["ldd", str(executable)], check=True, capture_output=True, text=True)
    found: set[Path] = set()
    for line in result.stdout.splitlines():
        match = re.search(r"=>\s+(/[^\s]+)", line)
        if not match:
            match = re.match(r"\s*(/[^\s]+)", line)
        if match:
            path = Path(match.group(1))
            if path.is_file() and not path.name.startswith(CORE_LIBRARIES):
                found.add(path)
    return found


def dependency_closure(executables: list[Path]) -> set[Path]:
    pending = list(executables)
    visited: set[Path] = set()
    libraries: set[Path] = set()
    while pending:
        current = pending.pop()
        resolved = current.resolve()
        if resolved in visited:
            continue
        visited.add(resolved)
        for library in dependencies(current):
            if library not in libraries:
                libraries.add(library)
                pending.append(library)
    return libraries


def copy_license(source: Path, destination: Path, name: str) -> None:
    if source.is_file():
        destination.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination / name)


def package_for_file(path: Path) -> str | None:
    result = subprocess.run(["dpkg-query", "-S", str(path)], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        return None
    package = result.stdout.split(":", 1)[0].strip()
    return package.split(",", 1)[0].split(":", 1)[0] if package else None


def stage(output: Path) -> None:
    bin_dir = output / "bin"
    lib_dir = output / "lib"
    tessdata_dir = output / "tessdata"
    bin_dir.mkdir(parents=True, exist_ok=True)
    lib_dir.mkdir(parents=True, exist_ok=True)

    tool_paths: list[Path] = []
    for name in ("pdftotext", "pdftoppm", "tesseract"):
        resolved = shutil.which(name)
        if not resolved:
            raise FileNotFoundError(f"Required build tool is missing: {name}")
        destination = bin_dir / name
        shutil.copy2(Path(resolved).resolve(), destination)
        tool_paths.append(destination)

    libraries = dependency_closure(tool_paths)
    licensed_packages = {"poppler-utils", "poppler-data", "tesseract-ocr", "tesseract-ocr-eng"}
    for library in sorted(libraries):
        shutil.copy2(library, lib_dir / library.name)
        owner = package_for_file(library)
        if owner:
            licensed_packages.add(owner)

    source_tessdata = next(
        (path for path in (Path("/usr/share/tesseract-ocr/5/tessdata"), Path("/usr/share/tessdata")) if path.is_dir()),
        None,
    )
    if source_tessdata is None or not (source_tessdata / "eng.traineddata").is_file():
        raise FileNotFoundError("English Tesseract data (eng.traineddata) was not installed.")
    tessdata_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_tessdata / "eng.traineddata", tessdata_dir / "eng.traineddata")
    for directory_name in ("configs", "tessconfigs"):
        source = source_tessdata / directory_name
        if source.is_dir():
            shutil.copytree(source, tessdata_dir / directory_name, dirs_exist_ok=True)

    poppler_data = Path("/usr/share/poppler")
    if not poppler_data.is_dir():
        raise FileNotFoundError("Poppler data directory /usr/share/poppler is missing.")
    shutil.copytree(poppler_data, output / "share/poppler", dirs_exist_ok=True)
    for package in sorted(licensed_packages):
        copy_license(
            Path("/usr/share/doc") / package / "copyright",
            output / "licenses",
            f"{package}-copyright",
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    stage(args.output)
