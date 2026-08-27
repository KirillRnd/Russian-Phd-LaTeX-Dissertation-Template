#!/usr/bin/env python3
"""Repair four root citation problems in the active dissertation footnotes."""

from __future__ import annotations

import argparse
import shutil
import tempfile
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from lxml import etree


W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": W_NS}
EDITION = (
    "Usatges de Barcelona / ed. J. Bastardas i Parera. "
    "Barcelona: Fundació Noguera, 1991."
)
ALEJANDRE_SHORT = "Alejandre García J.A. Op. cit. P. 153–156"
ALEJANDRE_FULL = (
    "Alejandre García J.A. Estudio histórico del delito de falsedad documental // "
    "Anuario de Historia del Derecho Español. 1972. T. 42. P. 117–188. "
    "Здесь: P. 153–156"
)

REPLACEMENTS = {
    "ГЛАВА_2_ВЕРСИЯ_3.docx": (171, 252),
    "ГЛАВА_3_ВЕРСИЯ_3.docx": (35,),
}


def visible_text(footnote: etree._Element) -> str:
    return "".join(footnote.xpath(".//w:t/text()", namespaces=NS))


def replace_across_nodes(text_nodes: list[etree._Element], old: str, new: str) -> bool:
    combined = "".join(node.text or "" for node in text_nodes)
    start = combined.find(old)
    if start < 0:
        return False
    end = start + len(old)
    position = 0
    first_index = last_index = None
    first_offset = last_offset = 0
    for index, node in enumerate(text_nodes):
        length = len(node.text or "")
        if first_index is None and position + length > start:
            first_index = index
            first_offset = start - position
        if position + length >= end:
            last_index = index
            last_offset = end - position
            break
        position += length
    if first_index is None or last_index is None:
        raise RuntimeError(f"could not map replacement span: {old!r}")
    first_text = text_nodes[first_index].text or ""
    last_text = text_nodes[last_index].text or ""
    text_nodes[first_index].text = first_text[:first_offset] + new + last_text[last_offset:]
    for index in range(first_index + 1, last_index + 1):
        text_nodes[index].text = ""
    return True


def patch_document(
    path: Path,
    note_ids: tuple[int, ...],
    backup_dir: Path,
    locked_output_dir: Path,
) -> None:
    with ZipFile(path) as source:
        infos = source.infolist()
        payloads = {info.filename: source.read(info.filename) for info in infos}

    root = etree.fromstring(payloads["word/footnotes.xml"])
    changed = 0
    for note_id in note_ids:
        matches = root.xpath(f"w:footnote[@w:id='{note_id}']", namespaces=NS)
        if len(matches) != 1:
            raise RuntimeError(f"{path.name}: footnote id {note_id} not found uniquely")
        footnote = matches[0]
        full_text = visible_text(footnote)
        normalized_start = full_text.lstrip()
        if normalized_start.startswith(EDITION):
            continue
        if not normalized_start.startswith("Ibid."):
            raise RuntimeError(
                f"{path.name}: footnote {note_id} does not start with Ibid.: {full_text[:80]!r}"
            )
        text_nodes = footnote.xpath(".//w:t", namespaces=NS)
        first = next((node for node in text_nodes if node.text and "Ibid." in node.text), None)
        if first is None:
            split_index = next(
                (index for index, node in enumerate(text_nodes) if (node.text or "") == "Ibid"),
                None,
            )
            if split_index is None or split_index + 1 >= len(text_nodes):
                raise RuntimeError(
                    f"{path.name}: Ibid. text node not found in footnote {note_id}: "
                    f"{[node.text for node in text_nodes[:12]]!r}"
                )
            first = text_nodes[split_index]
            punctuation = text_nodes[split_index + 1]
            if not (punctuation.text or "").startswith("."):
                raise RuntimeError(f"{path.name}: split Ibid punctuation not found in footnote {note_id}")
            first.text = EDITION
            punctuation.text = punctuation.text[1:]
        else:
            first.text = first.text.replace("Ibid.", EDITION, 1)
        changed += 1

    if path.name == "ГЛАВА_3_ВЕРСИЯ_3.docx":
        matches = root.xpath("w:footnote[@w:id='171']", namespaces=NS)
        if len(matches) != 1:
            raise RuntimeError(f"{path.name}: footnote id 171 not found uniquely")
        footnote = matches[0]
        full_text = visible_text(footnote)
        if ALEJANDRE_FULL not in full_text:
            text_nodes = footnote.xpath(".//w:t", namespaces=NS)
            if not replace_across_nodes(text_nodes, ALEJANDRE_SHORT, ALEJANDRE_FULL):
                raise RuntimeError(f"{path.name}: Alejandre short citation not found")
            changed += 1

    if not changed:
        print(f"{path.name}: already updated")
        return

    backup_dir.mkdir(parents=True, exist_ok=True)
    backup = backup_dir / path.name
    if not backup.exists():
        shutil.copy2(path, backup)

    payloads["word/footnotes.xml"] = etree.tostring(
        root,
        encoding="UTF-8",
        xml_declaration=True,
        standalone=True,
    )
    with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".docx", delete=False) as stream:
        temporary = Path(stream.name)
    try:
        with ZipFile(temporary, "w", compression=ZIP_DEFLATED) as target:
            for info in infos:
                target.writestr(info, payloads[info.filename])
        try:
            temporary.replace(path)
        except PermissionError:
            locked_output_dir.mkdir(parents=True, exist_ok=True)
            fallback = locked_output_dir / path.name
            shutil.copy2(temporary, fallback)
            print(
                f"{path.name}: source is locked; corrected copy written to {fallback}; "
                f"backup: {backup}"
            )
            return
    finally:
        temporary.unlink(missing_ok=True)
    print(f"{path.name}: updated {changed} footnote(s); backup: {backup}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("--backup-dir", type=Path, required=True)
    parser.add_argument("--locked-output-dir", type=Path, required=True)
    args = parser.parse_args()
    for filename, note_ids in REPLACEMENTS.items():
        patch_document(
            args.source / filename,
            note_ids,
            args.backup_dir,
            args.locked_output_dir,
        )


if __name__ == "__main__":
    main()
