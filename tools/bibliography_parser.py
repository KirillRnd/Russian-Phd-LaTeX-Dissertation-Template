#!/usr/bin/env python3
"""Parse the dissertation's formatted bibliography into BibLaTeX fields.

The source list is human-edited and multilingual.  This parser therefore uses
conservative, auditable rules: every record keeps its exact source string in
``annotation`` while fields that can be identified deterministically are split
out for BibLaTeX.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Iterable


YEAR = r"(?:1[5-9]|20)\d{2}"
YEAR_RANGE_RE = re.compile(rf"(?<!\d)({YEAR})(?:\s*[–—-]\s*({YEAR}))?(?!\d)")
URL_RE = re.compile(r"(?:URL:\s*)?(https?://[^\s)]+)", re.I)
ACCESS_RE = re.compile(
    r"\s*\((?:дата обращения|last access|accessed)\s*:\s*"
    r"(\d{1,2})\.(\d{1,2})\.((?:19|20)\d{2})\)\.?",
    re.I,
)
PAGES_RE = re.compile(r"(?:С|P|pp?)\.\s*([0-9]+(?:\s*[–—-]\s*[0-9]+)?)", re.I)
PAGETOTAL_RE = re.compile(r"(?:^|\.\s*)([IVXLCDM]+,\s*)?(\d+)\s*(с|p|fol)\.?\s*$", re.I)
VOLUME_RE = re.compile(r"(?:(?<!\w)(?:Т|Vol|Bd|Tome)\.\s*([^.;]+)|(\d+)\s+vol\.)")
NUMBER_RE = re.compile(r"(?<!\w)(?:№\s*|No(?:\.|\s)\s*|Núm(?:\.|\s)\s*|Вып\.\s*)([^.;()]+(?:\([^)]*\))?)", re.I)
INITIALS_RE = re.compile(r"(?:[A-ZА-ЯЁ]\.?\s*){1,3}\.")
NAME_RE = re.compile(r"^(.+?)\s+((?:[A-ZА-ЯЁ]\.\s*){1,3})$")


@dataclass
class ParsedEntry:
    key: str
    group: str
    entry_type: str
    fields: dict[str, str] = field(default_factory=dict)
    confidence: str = "low"
    warnings: list[str] = field(default_factory=list)


# Four source rows contain editorial placeholders left by the original author.
# Keep their verbatim strings in ``annotation`` for audit, but use verified
# publication data in the printable BibLaTeX fields.  Keeping the corrections
# here makes them reproducible for both DOCX conversion and graph rebuilding.
CURATED_RECORD_CORRECTIONS: dict[str, tuple[str, dict[str, str]]] = {
    "korneeva-research-014": (
        "article",
        {
            "author": "Ауров, О. В.",
            "title": "К вопросу о характере эдикта Эвриха: сюжет из истории права переходной эпохи",
            "journaltitle": "Электронный научно-образовательный журнал «История»",
            "date": "2012",
            "volume": "3",
            "number": "3 (11)",
            "pages": "16--29",
            "url": "https://history.jes.su/s207987840000375-1-1/",
        },
    ),
    "korneeva-research-037": (
        "incollection",
        {
            "author": "Варьяш, О. И.",
            "title": "Проблемы социализации индивида. Предисловие",
            "booktitle": "Пиренейские тетради: право, общество, власть и человек в средние века",
            "location": "Москва",
            "publisher": "Наука",
            "date": "2006",
        },
    ),
    "korneeva-research-038": (
        "incollection",
        {
            "author": "Варьяш, О. И.",
            "title": "Юридическая культура португальского двора XIV в. (corte — двор, corte — суд)",
            "booktitle": "Пиренейские тетради: право, общество, власть и человек в средние века",
            "location": "Москва",
            "publisher": "Наука",
            "date": "2006",
            "pages": "64--77",
        },
    ),
    "korneeva-research-039": (
        "incollection",
        {
            "author": "Варьяш, О. И.",
            "title": "Язык средневекового права",
            "booktitle": "Пиренейские тетради: право, общество, власть и человек в средние века",
            "location": "Москва",
            "publisher": "Наука",
            "date": "2006",
            "pages": "86--90",
        },
    ),
}


def clean_space(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip(" .;,\t\n")


def extract_url(text: str) -> tuple[str, str | None, str | None]:
    access = ACCESS_RE.search(text)
    urldate = None
    if access:
        day, month, year = access.groups()
        urldate = f"{year}-{int(month):02d}-{int(day):02d}"
        text = text[: access.start()] + text[access.end() :]
    match = URL_RE.search(text)
    url = None
    if match:
        url = match.group(1).rstrip(".,;:")
        text = text[: match.start()] + text[match.end() :]
    text = re.sub(r"\s*\[Электронный ресурс\]", "", text, flags=re.I)
    return clean_space(text), url, urldate


def split_leading_names(text: str) -> tuple[str | None, str]:
    """Return a conservative author prefix and the remaining title."""

    candidates: list[tuple[int, str, str]] = []
    for match in INITIALS_RE.finditer(text[:220]):
        end = match.end()
        if end >= len(text) or not text[end].isspace():
            continue
        prefix = text[:end].strip()
        remainder = text[end:].strip()
        if (
            not remainder
            or remainder.startswith((",", ".", ";", ":"))
            or "/" in prefix
            or ":" in prefix
            or re.search(r"\d", prefix)
            or len(prefix) > 90
            or len(prefix.split()) > 8
        ):
            continue
        if re.match(r"^[A-ZА-ЯЁ]\.\s", remainder):
            continue
        candidates.append((end, prefix, remainder))
    if not candidates:
        return None, text
    _, names, title = candidates[-1]
    return names, title


def biblatex_names(raw: str) -> str:
    value = re.sub(r"\s+et\s+al\.?$", "", raw, flags=re.I)
    # The source list consistently separates co-authors with commas; commas
    # inside inverted ``family, given`` forms are not used there.
    parts = re.split(r"\s*[,;]\s*|\s+(?:and|и)\s+", value)
    result: list[str] = []
    for part in parts:
        part = re.sub(r"\s+", " ", part).strip(" ,;")
        match = NAME_RE.match(part)
        if match:
            family, initials = match.groups()
            initials = " ".join(re.findall(r"[A-ZА-ЯЁ]\.", initials))
            result.append(f"{family}, {initials}")
        elif part:
            result.append(part)
    return " and ".join(result)


def publication_block(text: str) -> tuple[str, dict[str, str]]:
    """Split a trailing ``Place: Publisher, Year`` block when present."""

    fields: dict[str, str] = {}
    matches = list(
        re.finditer(
            rf"\.\s+(?P<location>[^:]{{1,90}}?):\s*"
            rf"(?P<publisher>.{{1,200}}?),\s*(?P<start>{YEAR})"
            rf"(?:\s*[–—-]\s*(?P<end>{YEAR}))?",
            text,
        )
    )
    if matches:
        match = matches[-1]
        location_raw = match.group("location")
        split_at = location_raw.rfind(". ")
        location_offset = split_at + 2 if split_at >= 0 else 0
        fields["location"] = clean_space(location_raw[location_offset:])
        fields["publisher"] = clean_space(match.group("publisher"))
        fields["date"] = match.group("start") + ("/" + match.group("end") if match.group("end") else "")
        location_start = match.start("location") + location_offset
        return clean_space(text[:location_start]), fields

    matches = list(re.finditer(rf"\.\s+(?P<location>[^,]{{1,60}}?),\s*(?P<year>{YEAR})(?=\.|$)", text))
    if matches:
        match = matches[-1]
        location_raw = match.group("location")
        split_at = location_raw.rfind(". ")
        location_offset = split_at + 2 if split_at >= 0 else 0
        fields["location"] = clean_space(location_raw[location_offset:])
        fields["date"] = match.group("year")
        location_start = match.start("location") + location_offset
        return clean_space(text[:location_start]), fields
    return clean_space(text), fields


def last_date(text: str) -> str | None:
    matches = list(YEAR_RANGE_RE.finditer(text))
    if not matches:
        return None
    match = matches[-1]
    return match.group(1) + ("/" + match.group(2) if match.group(2) else "")


def strip_unlocated_publication(text: str) -> str:
    """Remove a trailing year/apparatus block when no place block exists."""

    matches = list(YEAR_RANGE_RE.finditer(text))
    if not matches:
        return clean_space(text)
    match = matches[-1]
    tail = text[match.end() :]
    # A final year or a year followed only by volume/issue/page apparatus is a
    # publication date, not part of the title. Earlier historical years remain.
    if len(tail) <= 140 and (
        not clean_space(tail)
        or PAGES_RE.search(tail)
        or PAGETOTAL_RE.search(tail)
        or VOLUME_RE.search(tail)
        or NUMBER_RE.search(tail)
    ):
        return clean_space(text[: match.start()])
    return clean_space(text)


def extract_common_fields(text: str) -> tuple[str, dict[str, str]]:
    fields: dict[str, str] = {}
    page_match = PAGES_RE.search(text)
    if page_match:
        fields["pages"] = re.sub(r"\s*[–—-]\s*", "--", page_match.group(1))
    total_match = PAGETOTAL_RE.search(text)
    if total_match:
        fields["pagetotal"] = total_match.group(2)
    volume_match = VOLUME_RE.search(text)
    if volume_match:
        fields["volume"] = clean_space(volume_match.group(1) or volume_match.group(2))
    number_match = NUMBER_RE.search(text)
    if number_match:
        fields["number"] = clean_space(number_match.group(1))
    date = last_date(text)
    if date:
        fields["date"] = date
    return text, fields


def classify_container(container: str) -> str:
    has_publisher = bool(re.search(rf":\s*[^.]+?,\s*{YEAR}", container))
    has_serial_marks = bool(re.search(r"(?:^|\.\s*)(?:Т|Vol|Bd|№|No|Núm|Вып)\.", container, re.I))
    if has_publisher or re.search(r"/\s*(?:отв\.\s*)?(?:ред|ed|dir)\.", container, re.I):
        return "incollection"
    return "article" if has_serial_marks or PAGES_RE.search(container) else "incollection"


def parse_record(record: dict[str, str]) -> ParsedEntry:
    raw = clean_space(record["text"])
    text, url, urldate = extract_url(raw)
    author_raw, body = split_leading_names(text)

    fields: dict[str, str] = {"title": body, "annotation": raw, "keywords": record["group"]}
    if author_raw:
        fields["author"] = biblatex_names(author_raw)
    if url:
        fields["url"] = url
    if urldate:
        fields["urldate"] = urldate

    if " // " in body:
        work, container = body.split(" // ", 1)
        if " / " in work:
            work, responsibility = work.split(" / ", 1)
            fields["note"] = clean_space(responsibility)
        fields["title"] = clean_space(work)
        entry_type = classify_container(container)
        _, common = extract_common_fields(container)
        if entry_type == "incollection":
            container_head, publication = publication_block(container)
            common.update(publication)
        else:
            container_head = clean_space(container)
        fields.update(common)
        if entry_type == "article":
            year_match = YEAR_RANGE_RE.search(container_head)
            fields["journaltitle"] = clean_space(container_head[: year_match.start()] if year_match else container_head)
        else:
            booktitle = container_head
            if " / " in booktitle:
                booktitle, book_resp = booktitle.split(" / ", 1)
                fields.setdefault("note", clean_space(book_resp))
            fields["booktitle"] = clean_space(booktitle)
    else:
        title_head, publication = publication_block(body)
        _, common = extract_common_fields(body)
        common.update(publication)
        fields.update(common)
        if not publication and fields.get("date"):
            title_head = strip_unlocated_publication(title_head)
        if " / " in title_head:
            title_head, responsibility = title_head.split(" / ", 1)
            fields["note"] = clean_space(responsibility)
        fields["title"] = clean_space(title_head)
        if url and not publication and not fields.get("pagetotal"):
            entry_type = "online"
        else:
            entry_type = "book"

    # Remove apparatus that has already been assigned to dedicated fields.
    fields["title"] = clean_space(re.sub(r"\s*\[Электронный ресурс\]", "", fields["title"], flags=re.I))
    warnings: list[str] = []
    if not fields.get("date") and entry_type != "online":
        warnings.append("publication date not identified")
    if re.search(r"\?\?\?|\bссылка\b", raw, re.I):
        warnings.append("source contains an editorial placeholder")
    if entry_type == "article" and not fields.get("journaltitle"):
        warnings.append("journal title not identified")
    if entry_type == "incollection" and not fields.get("booktitle"):
        warnings.append("container title not identified")

    correction = CURATED_RECORD_CORRECTIONS.get(record["key"])
    if correction:
        entry_type, corrected_fields = correction
        # Audit-only fields preserve the original row and its source group.
        fields = {
            **corrected_fields,
            "annotation": raw,
            "keywords": record["group"],
        }
        warnings = []

    required = {
        "online": bool(fields.get("url")),
        "article": bool(fields.get("journaltitle") and fields.get("date")),
        "incollection": bool(fields.get("booktitle") and fields.get("date")),
        "book": bool(fields.get("date")),
    }[entry_type]
    confidence = "high" if required and not warnings else "medium" if fields.get("date") else "low"
    return ParsedEntry(record["key"], record["group"], entry_type, fields, confidence, warnings)


def latex_escape(value: str) -> str:
    replacements = {
        "\\": r"\textbackslash{}",
        "{": r"\{",
        "}": r"\}",
        "&": r"\&",
        "%": r"\%",
        "#": r"\#",
        "_": r"\_",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
        "–": "--",
        "—": "---",
    }
    fallback_chars = set("ṭṬʾἐὁὅꝑꝗ")
    return "".join(
        r"{\unicodefallback " + char + "}" if char in fallback_chars else replacements.get(char, char)
        for char in value
    )


def url_escape(value: str) -> str:
    return value.replace("%", r"\%").replace("#", r"\#")


def serialize_biblatex(entries: Iterable[ParsedEntry]) -> str:
    lines = [
        "% Структурированные записи автоматически разобраны из СПИСОК_ЛИТЕРАТУРЫ.docx.",
        "% Исходная строка каждой записи сохранена в поле annotation для аудита.",
        "",
    ]
    order = [
        "author", "editor", "title", "journaltitle", "booktitle", "location",
        "publisher", "organization", "institution", "date", "volume", "number", "pages", "pagetotal",
        "url", "urldate", "note", "annotation", "keywords",
    ]
    for entry in entries:
        lines.append(f"@{entry.entry_type}{{{entry.key},")
        for name in order:
            value = entry.fields.get(name)
            if not value:
                continue
            rendered = url_escape(value) if name == "url" else latex_escape(value)
            lines.append(f"  {name:<12} = {{{rendered}}},")
        lines += ["}", ""]
    return "\n".join(lines)


def audit(entries: list[ParsedEntry]) -> dict[str, object]:
    type_counts = Counter(entry.entry_type for entry in entries)
    confidence_counts = Counter(entry.confidence for entry in entries)
    field_counts = Counter(name for entry in entries for name in entry.fields)
    return {
        "entries": len(entries),
        "types": dict(type_counts),
        "confidence": dict(confidence_counts),
        "field_coverage": {name: {"count": count, "percent": round(count * 100 / len(entries), 1)} for name, count in sorted(field_counts.items())},
        "records_requiring_review": [
            {"key": entry.key, "confidence": entry.confidence, "warnings": entry.warnings, "source": entry.fields["annotation"]}
            for entry in entries
            if entry.confidence == "low" or entry.warnings
        ],
        "method": "deterministic multilingual field parser with verbatim annotation fallback",
    }
