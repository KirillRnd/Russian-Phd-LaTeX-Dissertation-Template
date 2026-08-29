"""Merge the two internally independent dissertation volumes into one PDF."""

from pathlib import Path

from pypdf import PdfReader, PdfWriter


ROOT = Path(__file__).resolve().parent.parent
VOLUME_FILES = (
    (ROOT / "dissertation-volume1.pdf", "Том I"),
    (ROOT / "dissertation-volume2.pdf", "Том II"),
)
OUTPUT = ROOT / "output" / "pdf" / "dissertation-korneeva.pdf"


def main() -> None:
    writer = PdfWriter()

    for path, title in VOLUME_FILES:
        if not path.exists():
            raise FileNotFoundError(f"Не найден собранный том: {path}")

        reader = PdfReader(path)
        start_page = len(writer.pages)
        writer.add_outline_item(title, start_page)
        writer.append(reader, import_outline=True)

    writer.page_mode = "/UseOutlines"
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("wb") as stream:
        writer.write(stream)

    print(f"Written {OUTPUT} ({len(writer.pages)} pages)")


if __name__ == "__main__":
    main()
