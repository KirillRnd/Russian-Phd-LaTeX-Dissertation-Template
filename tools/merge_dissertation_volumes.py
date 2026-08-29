"""Merge exactly two internally independent dissertation volumes into one PDF."""

import logging
from pathlib import Path

from pypdf import PdfReader, PdfWriter


ROOT = Path(__file__).resolve().parent.parent
VOLUME_FILES = (
    (ROOT / "dissertation-volume1.pdf", "Том I"),
    (ROOT / "dissertation-volume2.pdf", "Том II"),
)
OUTPUT = ROOT / "output" / "pdf" / "dissertation-korneeva.pdf"


def merge_volumes(output: Path = OUTPUT) -> Path:
    """Merge both required volumes and validate the resulting PDF."""
    logging.getLogger("pypdf").setLevel(logging.ERROR)
    writer = PdfWriter()
    expected_pages = 0

    for path, title in VOLUME_FILES:
        if not path.exists():
            raise FileNotFoundError(f"Не найден собранный том: {path}")

        reader = PdfReader(path)
        if not reader.pages:
            raise ValueError(f"Собранный том не содержит страниц: {path}")

        expected_pages += len(reader.pages)
        start_page = len(writer.pages)
        writer.add_outline_item(title, start_page)
        writer.append(reader, import_outline=True)

    writer.page_mode = "/UseOutlines"
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary_output = output.with_suffix(".tmp.pdf")
    with temporary_output.open("wb") as stream:
        writer.write(stream)

    merged = PdfReader(temporary_output)
    if len(merged.pages) != expected_pages:
        temporary_output.unlink(missing_ok=True)
        raise ValueError(
            f"Ожидалось {expected_pages} страниц, получено {len(merged.pages)}"
        )

    temporary_output.replace(output)
    print(f"Written {output} ({len(merged.pages)} pages, 2 volumes)")
    return output


def main() -> None:
    merge_volumes()


if __name__ == "__main__":
    main()
