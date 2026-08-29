#!/usr/bin/env python3
"""Extract bibliography sections from the two local dissertation examples.

The page ranges and section headings are intentionally explicit: this is a
one-off, reviewable extraction rather than a general PDF import facility.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs" / "bibliography-examples"


@dataclass(frozen=True)
class Example:
    slug: str
    author: str
    filename: str
    first_page: int
    last_page: int
    internal_first: int
    internal_last: int
    headings: tuple[str, ...]


EXAMPLES = (
    Example(
        slug="lunyashin-bibliography",
        author="Луняшин",
        filename="Луняшин.pdf",
        first_page=360,
        last_page=383,
        internal_first=139,
        internal_last=162,
        headings=(
            "Архивные источники:",
            "Опубликованные источники:",
            "Литература:",
            "на русском языке:",
            "на иностранных языках:",
        ),
    ),
    Example(
        slug="kovalev-bibliography",
        author="Ковалев",
        filename="Ковалев.pdf",
        first_page=215,
        last_page=260,
        internal_first=215,
        internal_last=260,
        headings=(
            "Список источников:",
            "Список литературы:",
            "Справочные издания и базы данных:",
        ),
    ),
)

ENTRY_START = re.compile(r"^(\d+)\.\s*(.*)$")


def compact(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s+([,.;:)])", r"\1", text)
    text = re.sub(r"([(])\s+", r"\1", text)
    text = re.sub(r"(?<=\w)-\s+(?=\w)", "-", text)
    text = re.sub(r"(?<=\d)([–—-])\s+(?=\d)", r"\1", text)

    def compact_url(match: re.Match[str]) -> str:
        return re.sub(r"\s+", "", match.group(0))

    text = re.sub(
        r"https?://.*?(?=(?:\s*\(дата обращения:|\s*;?\s*DOI:|$))",
        compact_url,
        text,
        flags=re.IGNORECASE,
    )
    return text


def canonical_heading(line: str, headings: tuple[str, ...]) -> str | None:
    candidate = re.sub(r"\s+", " ", line).replace(" :", ":").strip()
    for heading in headings:
        if candidate.casefold() == heading.casefold():
            return heading
    return None


def parse(example: Example) -> list[tuple[str, str | tuple[int, str]]]:
    reader = PdfReader(ROOT / "ПримерыДиисеров" / example.filename)
    blocks: list[tuple[str, str | tuple[int, str]]] = []
    current_number: int | None = None
    current_parts: list[str] = []
    expected_number = 1

    def flush_entry() -> None:
        nonlocal current_number, current_parts
        if current_number is not None:
            blocks.append(("entry", (current_number, compact(" ".join(current_parts)))))
        current_number = None
        current_parts = []

    for page_number in range(example.first_page, example.last_page + 1):
        lines = (reader.pages[page_number - 1].extract_text() or "").splitlines()
        for index, raw_line in enumerate(lines):
            line = raw_line.strip()
            if not line:
                continue
            if index == 0 and line.isdigit():
                continue
            if line.casefold() == "библиография":
                continue
            heading = canonical_heading(line, example.headings)
            if heading:
                flush_entry()
                blocks.append(("heading", heading))
                continue
            match = ENTRY_START.match(line)
            if match and int(match.group(1)) == expected_number:
                flush_entry()
                current_number = int(match.group(1))
                current_parts = [match.group(2)]
                expected_number += 1
            elif current_number is not None:
                current_parts.append(line)
    flush_entry()
    return blocks


def validate(blocks: list[tuple[str, str | tuple[int, str]]], author: str) -> None:
    numbers = [payload[0] for kind, payload in blocks if kind == "entry"]  # type: ignore[index]
    expected = list(range(1, numbers[-1] + 1))
    if numbers != expected:
        missing = sorted(set(expected) - set(numbers))
        duplicates = sorted(number for number in set(numbers) if numbers.count(number) > 1)
        raise ValueError(f"{author}: numbering mismatch; missing={missing}, duplicates={duplicates}")


def render(example: Example, blocks: list[tuple[str, str | tuple[int, str]]]) -> str:
    source = f"../../ПримерыДиисеров/{example.filename}"
    entry_count = sum(kind == "entry" for kind, _ in blocks)
    lines = [
        f"# Библиография из примера диссертации: {example.author}",
        "",
        "> Статус: исследовательский пример, не нормативный образец и не окончательный арбитр оформления.",
        "",
        f"Источник: [{example.filename}]({source}).",
        f"Извлечено с PDF-страниц {example.first_page}–{example.last_page} "
        f"(печатные страницы {example.internal_first}–{example.internal_last}).",
        f"Записей: {entry_count}.",
        "",
        "Переносы строк и пробельные артефакты текстового слоя нормализованы. "
        "Содержательные формулировки, пунктуация и порядок элементов намеренно сохранены; "
        "при точной проверке спорного знака следует сверяться с PDF.",
        "",
    ]
    for kind, payload in blocks:
        if kind == "heading":
            lines.extend((f"## {str(payload).removesuffix(':')}", ""))
        else:
            number, entry = payload  # type: ignore[misc]
            lines.extend((f"{number}. {entry}", ""))
    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for example in EXAMPLES:
        blocks = parse(example)
        validate(blocks, example.author)
        destination = OUTPUT / f"{example.slug}.md"
        destination.write_text(render(example, blocks), encoding="utf-8")
        count = sum(kind == "entry" for kind, _ in blocks)
        print(f"{destination.relative_to(ROOT)}: {count} entries")


if __name__ == "__main__":
    main()
