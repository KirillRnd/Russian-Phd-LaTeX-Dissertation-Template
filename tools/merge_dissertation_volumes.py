"""Merge exactly two internally independent dissertation volumes into one PDF."""

import logging
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from pypdf.annotations import Link
from pypdf.generic import Fit, NullObject


ROOT = Path(__file__).resolve().parent.parent
VOLUME_FILES = (
    (ROOT / "dissertation-volume1.pdf", "Том I"),
    (ROOT / "dissertation-volume2.pdf", "Том II"),
)
OUTPUT = ROOT / "output" / "pdf" / "dissertation-korneeva.pdf"


def _optional_number(value):
    return None if value is None or isinstance(value, NullObject) else float(value)


def _restore_volume_two_toc_links(
    writer: PdfWriter, volume_one: PdfReader, volume_two: PdfReader
) -> None:
    """Restore links from the full TOC in volume I to destinations in volume II."""
    destinations = volume_two.named_destinations
    volume_two_offset = len(volume_one.pages)

    for page_number, page in enumerate(volume_one.pages):
        annotations = page.get("/Annots")
        if not annotations:
            continue

        for annotation_reference in annotations.get_object():
            annotation = annotation_reference.get_object()
            action = annotation.get("/A")
            destination_name = str(action.get("/D")) if action else ""
            if not destination_name.startswith("volume2."):
                continue

            destination_name = destination_name.removeprefix("volume2.")
            if destination_name not in destinations:
                continue

            destination = destinations[destination_name]
            target_page = volume_two.get_destination_page_number(destination)
            if target_page < 0:
                continue

            rect = tuple(float(value) for value in annotation["/Rect"])
            fit = Fit.xyz(
                left=_optional_number(destination.left),
                top=_optional_number(destination.top),
                zoom=_optional_number(destination.zoom),
            )
            writer.add_annotation(
                page_number,
                Link(
                    rect=rect,
                    border=annotation.get("/Border"),
                    target_page_index=volume_two_offset + target_page,
                    fit=fit,
                ),
            )


def merge_volumes(output: Path = OUTPUT) -> Path:
    """Merge both required volumes and validate the resulting PDF."""
    logging.getLogger("pypdf").setLevel(logging.ERROR)
    writer = PdfWriter()
    expected_pages = 0
    readers = []

    for path, title in VOLUME_FILES:
        if not path.exists():
            raise FileNotFoundError(f"Не найден собранный том: {path}")

        reader = PdfReader(path)
        if not reader.pages:
            raise ValueError(f"Собранный том не содержит страниц: {path}")

        expected_pages += len(reader.pages)
        readers.append(reader)
        start_page = len(writer.pages)
        writer.add_outline_item(title, start_page)
        writer.append(reader, import_outline=True)

    _restore_volume_two_toc_links(writer, readers[0], readers[1])

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
