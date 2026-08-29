"""Build both dissertation volumes and merge them into one final PDF.

This is intentionally the only supported main dissertation build path.  It has
no option for selecting a single volume: both volume entry points are always
compiled and the final artifact is always their ordered merge.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import time
from pathlib import Path

from merge_dissertation_volumes import OUTPUT, ROOT, VOLUME_FILES, merge_volumes


VOLUME_1 = ROOT / "dissertation-volume1.tex"
VOLUME_2 = ROOT / "dissertation-volume2.tex"
AUXILIARY_SUFFIXES = (
    ".aux",
    ".bbl",
    ".bcf",
    ".blg",
    ".fdb_latexmk",
    ".fls",
    ".log",
    ".nlo",
    ".out",
    ".run.xml",
    ".toc",
    ".xdv",
)
RERUN_MARKERS = (
    "There were undefined references",
    "Label(s) may have changed",
    "Rerun to get",
    "Please rerun LaTeX",
)


def find_program(name: str) -> str:
    """Locate a TeX program, including the standard per-user MiKTeX path."""
    located = shutil.which(name)
    if located:
        return located

    if sys.platform == "win32":
        candidate = (
            Path.home()
            / "AppData"
            / "Local"
            / "Programs"
            / "MiKTeX"
            / "miktex"
            / "bin"
            / "x64"
            / f"{name}.exe"
        )
        if candidate.exists():
            return str(candidate)

    raise FileNotFoundError(
        f"Не найдена программа {name}. Установите MiKTeX/TeX Live и добавьте её в PATH."
    )


def run(command: list[str]) -> None:
    print("+", " ".join(command), flush=True)
    subprocess.run(command, cwd=ROOT, check=True)


def xelatex(engine: str, source: Path) -> None:
    run(
        [
            engine,
            "-interaction=nonstopmode",
            "-halt-on-error",
            "-file-line-error",
            source.name,
        ]
    )


def settle_xelatex(
    engine: str, source: Path, *, minimum_passes: int, maximum_passes: int = 5
) -> None:
    """Run XeLaTeX until its references and generated lists are stable."""
    log_path = source.with_suffix(".log")
    for pass_number in range(1, maximum_passes + 1):
        xelatex(engine, source)
        log_text = log_path.read_text(encoding="utf-8", errors="replace")
        needs_rerun = any(marker in log_text for marker in RERUN_MARKERS)
        if pass_number >= minimum_passes and not needs_rerun:
            return

    raise RuntimeError(
        f"Ссылки в {source.name} не стабилизировались за {maximum_passes} проходов"
    )


def clean_auxiliaries() -> None:
    """Remove stale cross-run state before building the two fixed volumes."""
    for stem in (VOLUME_1.with_suffix(""), VOLUME_2.with_suffix("")):
        for suffix in AUXILIARY_SUFFIXES:
            stem.with_suffix(suffix).unlink(missing_ok=True)

    # Both volume entry points use \include and therefore share these generated
    # files.  Starting clean prevents one volume's state (or an older package
    # version's syntax) from leaking into the other volume.
    for auxiliary in (ROOT / "Dissertation").rglob("*.aux"):
        auxiliary.unlink()


def build() -> Path:
    engine = find_program("xelatex")
    biber = find_program("biber")
    started_at = time.time_ns()
    clean_auxiliaries()

    # Том I формирует .aux, от которого зависит том II.
    settle_xelatex(engine, VOLUME_1, minimum_passes=3)

    # Том II зависит от .aux тома I и содержит собственную библиографию.
    xelatex(engine, VOLUME_2)
    run([biber, VOLUME_2.stem])
    settle_xelatex(engine, VOLUME_2, minimum_passes=2)

    missing = [str(path) for path, _ in VOLUME_FILES if not path.exists()]
    if missing:
        raise FileNotFoundError("Не собраны обязательные тома: " + ", ".join(missing))

    stale = [
        str(path)
        for path, _ in VOLUME_FILES
        if path.stat().st_mtime_ns < started_at
    ]
    if stale:
        raise RuntimeError("Тома не были обновлены текущей сборкой: " + ", ".join(stale))

    result = merge_volumes(OUTPUT)
    print(f"Final dissertation: {result}")
    return result


if __name__ == "__main__":
    build()
