"""Build only the BibLaTeX bibliography as readable HTML, never as PDF."""

from __future__ import annotations

import shutil
import subprocess
import sys
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "bibliography-preview.tex"
BUILD_FILE = ROOT / "bibliography-preview.mk4"
OUTPUT = ROOT / "output" / "bibliography"


def clean_intermediates() -> None:
    """Remove only files generated from the dedicated preview stem."""
    keep = {SOURCE.resolve(), BUILD_FILE.resolve()}
    for path in ROOT.glob("bibliography-preview*"):
        if path.is_file() and path.resolve() not in keep:
            path.unlink()


def clean_output_artifacts() -> None:
    """Remove prior files produced by this preview, leaving the audit report."""
    if not OUTPUT.exists():
        return
    for path in OUTPUT.glob("bibliography-preview*"):
        if path.is_file():
            path.unlink()
    for name in ("biber.log", "processed.bbl"):
        path = OUTPUT / name
        if path.is_file():
            path.unlink()


def find_program(name: str) -> str:
    located = shutil.which(name)
    if located:
        return located
    if sys.platform == "win32":
        candidates = [
            Path.home() / "AppData" / "Local" / "Programs" / "MiKTeX" / "miktex" / "bin" / "x64" / f"{name}.exe"
        ]
        if local_app_data := os.environ.get("LOCALAPPDATA"):
            candidates.append(Path(local_app_data) / "Programs" / "MiKTeX" / "miktex" / "bin" / "x64" / f"{name}.exe")
        candidates.extend(sorted(Path("C:/Users").glob(f"*/AppData/Local/Programs/MiKTeX/miktex/bin/x64/{name}.exe")))
        for candidate in candidates:
            if candidate.exists():
                return str(candidate)
    raise FileNotFoundError(f"Не найдена программа {name} из поставки TeX.")


def build() -> Path:
    subprocess.run(
        [sys.executable, str(ROOT / "tools" / "audit_bibliography.py"), "--fail-on-error"],
        cwd=ROOT,
        check=True,
    )
    make4ht = find_program("make4ht")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    clean_output_artifacts()
    clean_intermediates()
    command = [
        make4ht,
        "--lua",
        "--format",
        "html5",
        "--build-file",
        BUILD_FILE.name,
        "--output-dir",
        str(OUTPUT.relative_to(ROOT)),
        SOURCE.name,
    ]
    print("+", " ".join(command), flush=True)
    try:
        subprocess.run(command, cwd=ROOT, check=True)
        html = OUTPUT / "bibliography-preview.html"
        if not html.exists() or html.stat().st_size == 0:
            raise RuntimeError(f"HTML библиографии не создан: {html}")
        log = ROOT / "bibliography-preview.blg"
        if log.exists():
            shutil.copy2(log, OUTPUT / "biber.log")
        subprocess.run(
            [sys.executable, str(ROOT / "tools" / "check_bibliography_output.py")],
            cwd=ROOT,
            check=True,
        )
        print(f"Bibliography HTML: {html}")
        return html
    finally:
        clean_intermediates()


if __name__ == "__main__":
    build()
