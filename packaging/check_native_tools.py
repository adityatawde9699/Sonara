"""Exercise the staged PDF text, PDF rendering, and English OCR tools."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tests.fixtures.pdf_fixture import make_pdf  # noqa: E402


def _run(command: list[str], environment: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=True, capture_output=True, text=True, env=environment, timeout=60)


def check_tools(tools: Path) -> None:
    binary_directory = tools / "bin"
    required = ("pdftotext", "pdftoppm", "tesseract")
    suffix = ".exe" if os.name == "nt" else ""
    executables = {name: binary_directory / f"{name}{suffix}" for name in required}
    missing = [str(path) for path in executables.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError("Staged PDF/OCR executable(s) are missing: " + ", ".join(missing))
    if not (tools / "tessdata/eng.traineddata").is_file():
        raise FileNotFoundError("Staged English OCR model is missing: tessdata/eng.traineddata")

    environment = os.environ.copy()
    environment["PATH"] = str(binary_directory) + os.pathsep + environment.get("PATH", "")
    environment["TESSDATA_PREFIX"] = str(tools / "tessdata")
    environment["POPPLER_DATADIR"] = str(tools / "share/poppler")
    if os.name == "posix" and sys.platform.startswith("linux"):
        environment["LD_LIBRARY_PATH"] = str(tools / "lib") + os.pathsep + environment.get("LD_LIBRARY_PATH", "")

    _run([str(executables["pdftotext"]), "-v"], environment)
    _run([str(executables["pdftoppm"]), "-v"], environment)
    language_report = _run([str(executables["tesseract"]), "--list-langs"], environment)
    if "eng" not in language_report.stdout:
        raise RuntimeError("Staged Tesseract runtime does not report the English language model.")

    with tempfile.TemporaryDirectory(prefix="sonara-native-tools-") as temporary:
        temporary_path = Path(temporary)
        pdf = make_pdf(temporary_path / "tool-smoke.pdf")
        extracted = _run([str(executables["pdftotext"]), "-bbox-layout", "-enc", "UTF-8", str(pdf), "-"], environment)
        if "Sonara reads local documents aloud." not in extracted.stdout:
            raise RuntimeError("Staged Poppler did not extract the expected PDF text.")
        image_prefix = temporary_path / "rendered"
        _run([str(executables["pdftoppm"]), "-png", "-r", "300", "-f", "1", "-l", "1", str(pdf), str(image_prefix)], environment)
        images = sorted(temporary_path.glob("rendered-*.png"))
        if not images:
            raise RuntimeError("Staged Poppler did not render a PDF page for OCR.")
        recognized = _run([str(executables["tesseract"]), str(images[0]), "stdout", "-l", "eng", "--psm", "6"], environment)
        normalized = " ".join(recognized.stdout.casefold().split())
        expected = "sonara reads local documents aloud."
        if expected not in normalized:
            raise RuntimeError(f"Staged Tesseract did not recognize the smoke text: {recognized.stdout[:200]!r}")
    print("Packaged Poppler extraction/rendering and Tesseract English OCR smoke checks passed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tools", type=Path, required=True)
    arguments = parser.parse_args()
    check_tools(arguments.tools)
