#!/usr/bin/env python3
"""Legacy flat inventory of bibliography and footnote mention strings.

This module is retained because :mod:`citation_graph_parser` reuses its DOCX
extraction, normalization, and matching helpers.  Its standalone report is not
the canonical bibliography analysis: relational formulas cannot be resolved
correctly when citation units are treated as independent rows.

The canonical bibliography and the footnotes serve different purposes.  The
former contains complete records, while the latter mixes full citations,
short citations, page locators, ``ibid.`` references, and ordinary explanatory
prose.  This module keeps every footnote verbatim, splits it into auditable
units, matches units to the canonical BibLaTeX database conservatively, and
adds only sufficiently complete footnote-only records to a merged database.

No footnote is rewritten by this program.  Ambiguous and unresolved units are
reported instead of being silently assigned to the nearest-looking record.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import unicodedata
import zipfile
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from lxml import etree

from bibliography_parser import ParsedEntry, parse_record, serialize_biblatex
from docx_to_latex import NS, W, bibliography_entries, node_text, xml_part


DOCX_JOBS = [
    "ВВЕДЕНИЕ_ВЕРСИЯ_3.docx",
    "ИСТОРИОГРАФИЯ_ВЕРСИЯ_3.docx",
    "ИСТОЧНИК_ВЕРСИЯ_3.docx",
    "КОНТЕКСТ_ВЕРСИЯ_3.docx",
    "ГЛАВА_1_ВЕРСИЯ_3.docx",
    "ГЛАВА_2_ВЕРСИЯ_3.docx",
    "ГЛАВА_3_ВЕРСИЯ_3.docx",
]

JOURNAL_ABBREVIATIONS = {"СВ", "AHDE", "Glossae", "Initium"}
BIBLIOGRAPHIC_ABBREVIATION_KEYS = {
    # Sokraschenia.docx defines LV as Lex Visigothorum; the canonical source
    # list identifies the cited K. Zeumer edition as korneeva-sources-027.
    "LV": "korneeva-sources-027",
}

YEAR_RE = re.compile(r"(?<!\d)(?:1[5-9]|20)\d{2}(?!\d)")
URL_RE = re.compile(r"https?://\S+", re.I)
INITIALS_RE = re.compile(
    r"\b[A-ZА-ЯЁ][\w'’`-]{1,40}"
    r"(?:\s+(?:(?:i|de|del|della|da|di|du|la|le|van|von)\s+)?[A-ZА-ЯЁ][\w'’`-]{1,40}){0,4}"
    r"\s+(?:[A-ZА-ЯЁ]\.\s*){1,3}",
    re.U,
)
LOCATOR_RE = re.compile(
    r"(?:\b(?:С|P|pp?|fol)\.\s*\d[\d\s,–—-]*|"
    r"\b(?:Doc|Док|№|Núm|No)\. ?\s*[\dIVXLCDM.-]+|"
    r"\b(?:Т|Vol|Bd|Вып)\.\s*[^.;]+)",
    re.I,
)
SHORT_REFERENCE_RE = re.compile(
    r"^(?:там\s+же|указ\.\s*соч\.|цит\.\s*соч\.|ibid\.?|ibidem\.?|"
    r"op\.\s*cit\.|см\.\s+выше|см\.\s+ниже)\b",
    re.I,
)
AUTHOR_SHORT_RE = re.compile(
    r"^(?P<author>[A-ZА-ЯЁ][\w'’`-]{1,40})(?:\s+[A-ZА-ЯЁ]\.\s*){1,3}\s+"
    r"(?:указ\.\s*соч\.|op\.\s*cit\.)",
    re.I | re.U,
)
LEADING_COMMENT_RE = re.compile(
    r"^(?:см\.(?:\s+также)?|подробнее|например|ср\.|о\s+.+?\s+см\.)\s*[:,-]?\s+",
    re.I,
)

STOPWORDS = {
    "and", "the", "of", "in", "a", "an", "et", "al", "ed", "eds",
    "и", "в", "во", "на", "о", "об", "по", "под", "ред", "пер", "изд",
    "том", "т", "вып", "vol", "no", "num", "с", "p", "pp", "doc",
    "м", "л", "спб", "москва", "ленинград", "barcelona", "press",
}


@dataclass
class Footnote:
    document: str
    ordinal: int
    note_id: str
    text: str


@dataclass
class Mention:
    mention_id: str
    document: str
    footnote_ordinal: int
    note_id: str
    unit_ordinal: int
    text: str
    kind: str
    locator: str | None = None
    matched_key: str | None = None
    match_score: float | None = None
    match_method: str | None = None
    resolution: str = "not_bibliographic"
    abbreviation: str | None = None
    abbreviation_expansion: str | None = None


def extract_abbreviations(path: Path) -> dict[str, str]:
    """Extract ``SIGLUM — expansion`` paragraphs from Sokraschenia.docx."""

    with zipfile.ZipFile(path) as archive:
        document = xml_part(archive, "word/document.xml")
        if document is None:
            raise ValueError(f"Missing document.xml: {path}")
        lines = [node_text(p) for p in document.xpath("//w:body/w:p", namespaces=NS)]
    result: dict[str, str] = {}
    for line in lines:
        parts = re.split(r"\s+[—–]\s+", line, maxsplit=1)
        if len(parts) != 2:
            continue
        abbreviation, expansion = (part.strip(" .") for part in parts)
        if abbreviation and expansion:
            result[abbreviation] = expansion
    return result


def primary_expansion(value: str) -> str:
    """Return the bibliographic-language name before translations/comments."""

    value = re.sub(r"\s*\(.*\)\s*$", "", value)
    value = re.split(r"\s+[—–]\s+", value, maxsplit=1)[0]
    return value.strip(" .")


def expand_entry_abbreviations(
    entries: Iterable[ParsedEntry], abbreviations: dict[str, str]
) -> Counter[str]:
    """Expand journal sigla in structured fields while preserving annotation."""

    changes: Counter[str] = Counter()
    for entry in entries:
        for field_name in ("journaltitle", "booktitle"):
            value = entry.fields.get(field_name)
            if value in JOURNAL_ABBREVIATIONS and value in abbreviations:
                entry.fields[field_name] = primary_expansion(abbreviations[value])
                changes[value] += 1
    return changes


def normalize(value: str) -> str:
    """Return a comparison form without destroying the stored source text."""

    value = unicodedata.normalize("NFKC", value).casefold().replace("ё", "е")
    value = value.replace("–", "-").replace("—", "-").replace("…", "...")
    value = re.sub(r"https?://\S+", " ", value)
    value = re.sub(r"\b(?:1[5-9]|20)\d{2}\b", " ", value)
    value = re.sub(r"\b\d+(?:[-.,/]\d+)*\b", " ", value)
    return " ".join(re.findall(r"[^\W_]+", value, re.U))


def tokens(value: str) -> set[str]:
    return {
        token for token in normalize(value).split()
        if len(token) > 1 and token not in STOPWORDS
    }


def strip_locator(value: str) -> str:
    value = LOCATOR_RE.sub(" ", value)
    value = re.sub(r"\b(?:ibid|ibidem|там\s+же)\.?", " ", value, flags=re.I)
    return re.sub(r"\s+", " ", value).strip(" .;,:")


def citation_payload(value: str) -> str:
    """Drop explanatory prose before the first conventional author heading."""

    value = LEADING_COMMENT_RE.sub("", value.strip())
    match = INITIALS_RE.search(value)
    if match and match.start() > 0:
        prefix = value[: match.start()].rstrip()
        if prefix.endswith((":", ".")) or re.search(r"\b(?:см|ср|например)\.?\s*$", prefix, re.I):
            return value[match.start() :].strip()
    return value


def clean_reference_source(value: str) -> str:
    """Remove prose that follows a complete citation inside one note unit."""

    value = citation_payload(value)
    endpoints = [match.end() for match in LOCATOR_RE.finditer(value)]
    endpoints += [match.end() for match in YEAR_RE.finditer(value)]
    for endpoint in sorted(set(endpoints)):
        remainder = value[endpoint:]
        if not re.match(r"\.\s+[A-ZА-ЯЁ]", remainder):
            continue
        prose = remainder.lstrip(". ")
        if len(prose.split()) >= 7 and not INITIALS_RE.match(prose):
            return value[:endpoint].strip(" .;,:")
    return value.strip(" .;,:")


def extract_locator(value: str) -> str | None:
    found = [re.sub(r"\s+", " ", match.group(0)).strip() for match in LOCATOR_RE.finditer(value)]
    return "; ".join(found) if found else None


def split_units(text: str) -> list[str]:
    """Split citation separators without breaking publisher/place apparatus."""

    units: list[str] = []
    start = 0
    round_depth = square_depth = 0
    for index, char in enumerate(text):
        if char == "(":
            round_depth += 1
        elif char == ")":
            round_depth = max(0, round_depth - 1)
        elif char == "[":
            square_depth += 1
        elif char == "]":
            square_depth = max(0, square_depth - 1)
        elif char == ";" and round_depth == 0 and square_depth == 0:
            following = text[index + 1 :].lstrip()
            looks_like_new_reference = bool(
                INITIALS_RE.match(following)
                or re.match(r"(?:idem|eadem|ibid|ibidem|там\s+же|указ\.\s*соч\.)\b", following, re.I)
                or re.match(r"(?:LV|ACB|ACA|MGH|PL)\b", following)
                or re.match(r"[^.;]{2,90}\s+//\s+", following)
            )
            if looks_like_new_reference:
                unit = text[start:index].strip()
                if unit:
                    units.append(unit)
                start = index + 1
    tail = text[start:].strip()
    if tail:
        units.append(tail)

    refined: list[str] = []
    for unit in units:
        starts: list[int] = []
        for match in INITIALS_RE.finditer(unit):
            if match.start() == 0:
                starts.append(0)
                continue
            prefix = unit[: match.start()].rstrip()
            if prefix.endswith((":", ".", ";")) and not re.search(r"\b(?:ed|eds|ред)\.$", prefix, re.I):
                starts.append(match.start())
        for match in re.finditer(r"\b(?:Idem|Eadem)\.\s+(?=[A-ZА-ЯЁ])", unit):
            if match.start() == 0 or unit[: match.start()].rstrip().endswith((":", ".", ";")):
                starts.append(match.start())
        starts = sorted(set(starts))
        if not starts:
            refined.append(unit)
            continue
        if starts[0] > 0:
            prefix = unit[: starts[0]].strip()
            if prefix:
                refined.append(prefix)
        for position, begin in enumerate(starts):
            end = starts[position + 1] if position + 1 < len(starts) else len(unit)
            part = unit[begin:end].strip()
            if part:
                refined.append(part)
    return refined or ([text.strip()] if text.strip() else [])


def classify_unit(value: str) -> str:
    candidate = citation_payload(value)
    full_signals = sum(
        (
            bool(URL_RE.search(candidate)),
            bool(YEAR_RE.search(candidate)),
            " // " in candidate,
            bool(re.search(r"\b[^.:;]{1,45}:\s*[^,.;]{2,80},\s*(?:1[5-9]|20)\d{2}", candidate)),
            bool(INITIALS_RE.search(candidate)),
        )
    )
    if full_signals >= 2 or (URL_RE.search(candidate) and len(candidate) > 25):
        return "full_reference"
    if SHORT_REFERENCE_RE.match(candidate) or AUTHOR_SHORT_RE.match(candidate):
        return "short_reference"
    if re.match(r"^(?:idem|eadem)\b", candidate, re.I):
        return "short_reference"
    abbreviated = bool(
        LOCATOR_RE.search(candidate)
        and (
            re.search(r"\.{2,}|\b(?:LV|ACB|ACA|PL|MGH)\b", candidate)
            or re.search(r"[A-ZА-ЯЁ][\w'’`-]+\s+[A-ZА-ЯЁ]\.", candidate)
            or len(tokens(strip_locator(candidate))) >= 2
        )
    )
    if abbreviated:
        return "abbreviated_reference"
    if re.search(r"\b(?:см\.|ср\.|ibid|idem|там\s+же|указ\.\s*соч\.)", candidate, re.I):
        return "possible_reference"
    return "commentary"


def extract_footnotes(path: Path) -> list[Footnote]:
    """Read only notes actually referenced by the Word document body."""

    with zipfile.ZipFile(path) as archive:
        document = xml_part(archive, "word/document.xml")
        note_root = xml_part(archive, "word/footnotes.xml")
        if document is None or note_root is None:
            return []
        notes = {
            note.get(f"{{{W}}}id", ""): note
            for note in note_root.xpath("//w:footnote", namespaces=NS)
        }
        ids = document.xpath("//w:footnoteReference/@w:id", namespaces=NS)
        result: list[Footnote] = []
        for ordinal, note_id in enumerate(ids, 1):
            note = notes.get(note_id)
            if note is None:
                text = ""
            else:
                paragraphs = [node_text(p) for p in note.xpath("./w:p", namespaces=NS)]
                text = " ".join(part for part in paragraphs if part).strip()
            result.append(Footnote(path.name, ordinal, note_id, text))
        return result


class Matcher:
    def __init__(self, entries: Iterable[ParsedEntry]):
        self.entries = list(entries)
        self.entry_tokens = {
            entry.key: tokens(
                " ".join(
                    entry.fields.get(name, "")
                    for name in ("author", "title", "journaltitle", "booktitle", "annotation")
                )
            )
            for entry in self.entries
        }
        self.title_tokens = {entry.key: tokens(entry.fields.get("title", "")) for entry in self.entries}
        self.normal_titles = {
            entry.key: normalize(entry.fields.get("title", "")) for entry in self.entries
        }

    def match(self, value: str) -> tuple[str | None, float, str | None]:
        payload = citation_payload(value)
        normalized_payload = normalize(payload)
        title_hits = [
            (len(title.split()), key)
            for key, title in self.normal_titles.items()
            if len(title.split()) >= 3 and len(title) >= 16 and title in normalized_payload
        ]
        if title_hits:
            title_hits.sort(reverse=True)
            longest, key = title_hits[0]
            competing = [item for item in title_hits[1:] if item[0] >= longest - 1]
            if not competing:
                return key, 0.98, "exact_title"

        query = tokens(strip_locator(payload))
        if not query:
            return None, 0.0, None
        ranked: list[tuple[float, str]] = []
        for entry in self.entries:
            corpus = self.entry_tokens[entry.key]
            overlap = len(query & corpus)
            if overlap == 0:
                continue
            containment = overlap / len(query)
            jaccard = overlap / len(query | corpus)
            title = self.title_tokens[entry.key]
            title_containment = len(query & title) / len(title) if title else 0.0
            score = 0.62 * containment + 0.23 * jaccard + 0.15 * min(1.0, title_containment)
            ranked.append((score, entry.key))
        if not ranked:
            return None, 0.0, None
        ranked.sort(reverse=True)
        best_score, best_key = ranked[0]
        second_score = ranked[1][0] if len(ranked) > 1 else 0.0
        minimum = 0.60 if len(query) >= 4 else 0.72
        if best_score < minimum or best_score - second_score < 0.06:
            return None, round(best_score, 3), "ambiguous" if best_score >= minimum else "below_threshold"
        return best_key, round(best_score, 3), "token_overlap"


def author_family(entry: ParsedEntry) -> set[str]:
    raw = entry.fields.get("author", "")
    return {normalize(part.split(",", 1)[0]) for part in raw.split(" and ") if part.strip()}


def entry_identity(entry: ParsedEntry) -> str:
    """A page-independent identity for duplicate suppression."""

    return normalize(" ".join(
        entry.fields.get(name, "")
        for name in ("author", "title", "journaltitle", "booktitle")
    ))


def leading_abbreviation(value: str, abbreviations: dict[str, str]) -> str | None:
    for abbreviation in sorted(abbreviations, key=len, reverse=True):
        if re.match(r"^" + re.escape(abbreviation) + r"(?:\.|\s)", value, re.I):
            return abbreviation
    return None


def institutional_abbreviation(value: str, abbreviations: dict[str, str]) -> str | None:
    excluded = JOURNAL_ABBREVIATIONS | set(BIBLIOGRAPHIC_ABBREVIATION_KEYS)
    for abbreviation in sorted(set(abbreviations) - excluded, key=len, reverse=True):
        if re.search(r"(?<![\w])" + re.escape(abbreviation) + r"\.(?![\w])", value):
            return abbreviation
    return None


def build_mentions(
    footnotes: list[Footnote],
    entries: list[ParsedEntry],
    abbreviations: dict[str, str],
) -> list[Mention]:
    matcher = Matcher(entries)
    by_key = {entry.key: entry for entry in entries}
    last_key: str | None = None
    last_by_author: dict[str, str] = {}
    mentions: list[Mention] = []
    counter = 0
    for footnote in footnotes:
        for unit_ordinal, unit in enumerate(split_units(footnote.text), 1):
            counter += 1
            kind = classify_unit(unit)
            mention = Mention(
                mention_id=f"mention-{counter:04d}",
                document=footnote.document,
                footnote_ordinal=footnote.ordinal,
                note_id=footnote.note_id,
                unit_ordinal=unit_ordinal,
                text=unit,
                kind=kind,
                locator=extract_locator(unit),
            )
            abbreviation = leading_abbreviation(unit.strip(), abbreviations)
            if abbreviation is None:
                abbreviation = institutional_abbreviation(unit, abbreviations)
            if abbreviation:
                mention.abbreviation = abbreviation
                mention.abbreviation_expansion = abbreviations[abbreviation]
                abbreviation_key = BIBLIOGRAPHIC_ABBREVIATION_KEYS.get(abbreviation)
                if abbreviation_key in by_key:
                    mention.kind = "abbreviated_reference"
                    mention.matched_key = abbreviation_key
                    mention.match_score = 1.0
                    mention.match_method = "authoritative_abbreviation_list"
                    mention.resolution = "matched"
                    last_key = abbreviation_key
                    mentions.append(mention)
                    continue
                if abbreviation not in JOURNAL_ABBREVIATIONS:
                    mention.kind = "institutional_reference"
                    mention.match_method = "authoritative_abbreviation_list"
                    mention.resolution = "classified_institutional"
                    mentions.append(mention)
                    continue
            if kind == "commentary":
                mentions.append(mention)
                continue

            candidate = citation_payload(unit)
            short_author = AUTHOR_SHORT_RE.match(candidate)
            pure_short = not YEAR_RE.search(candidate) and len(tokens(strip_locator(candidate))) <= 4
            if pure_short and SHORT_REFERENCE_RE.match(candidate) and last_key:
                mention.matched_key = last_key
                mention.match_score = 1.0
                mention.match_method = "sequential_short_reference"
                mention.resolution = "matched"
            elif pure_short and short_author:
                family = normalize(short_author.group("author"))
                if family in last_by_author:
                    mention.matched_key = last_by_author[family]
                    mention.match_score = 1.0
                    mention.match_method = "author_short_reference"
                    mention.resolution = "matched"
            if mention.matched_key is None:
                key, score, method = matcher.match(candidate)
                mention.matched_key = key
                mention.match_score = score if score else None
                mention.match_method = method
                mention.resolution = "matched" if key else "unresolved"

            if mention.matched_key:
                last_key = mention.matched_key
                for family in author_family(by_key[mention.matched_key]):
                    last_by_author[family] = mention.matched_key
            mentions.append(mention)
    return mentions


def footnote_only_entries(
    mentions: list[Mention], canonical: list[ParsedEntry]
) -> tuple[list[ParsedEntry], dict[str, int]]:
    """Create conservative records only for unmatched, complete citations."""

    seen = {
        normalize(strip_locator(entry.fields.get("annotation", entry.fields.get("title", ""))))
        for entry in canonical
    }
    seen_identities = {entry_identity(entry) for entry in canonical if entry_identity(entry)}
    canonical_by_key = {entry.key: entry for entry in canonical}
    extra: list[ParsedEntry] = []
    last_entry: ParsedEntry | None = None
    stats: Counter[str] = Counter()
    for mention in mentions:
        if mention.matched_key:
            last_entry = canonical_by_key.get(mention.matched_key, last_entry)
        if mention.kind != "full_reference" or mention.resolution != "unresolved":
            continue
        stats["unresolved_full_references"] += 1
        source = clean_reference_source(mention.text)
        fingerprint = normalize(strip_locator(source))
        if len(fingerprint) < 20:
            stats["rejected_too_short_after_cleanup"] += 1
            continue
        if fingerprint in seen:
            stats["rejected_duplicate_source_text"] += 1
            continue
        key = f"korneeva-footnote-{len(extra) + 1:03d}"
        idem = re.match(r"^(?:Idem|Eadem)\.\s*", source, re.I)
        parse_source = source[idem.end() :] if idem else source
        entry = parse_record({"key": key, "group": "footnote-only", "text": parse_source})
        if idem and last_entry and last_entry.fields.get("author"):
            entry.fields["author"] = last_entry.fields["author"]
            entry.fields["annotation"] = source
        identity = entry_identity(entry)
        if identity and identity in seen_identities:
            stats["rejected_duplicate_structured_identity"] += 1
            continue
        entry.fields["keywords"] = "footnote-only"
        entry.fields["note"] = (
            entry.fields.get("note", "") +
            ("; " if entry.fields.get("note") else "") +
            f"First occurrence: {mention.document}, footnote {mention.footnote_ordinal}"
        )
        extra.append(entry)
        last_entry = entry
        seen.add(fingerprint)
        if identity:
            seen_identities.add(identity)
        stats["added_unique_footnote_records"] += 1
    return extra, dict(stats)


def institutional_entries(mentions: list[Mention]) -> list[ParsedEntry]:
    """Turn identified archive/library references into explicit misc records."""

    entries: list[ParsedEntry] = []
    seen: set[str] = set()
    for mention in mentions:
        if mention.resolution != "classified_institutional" or not mention.abbreviation:
            continue
        fingerprint = normalize(mention.text)
        if fingerprint in seen:
            continue
        abbreviation = mention.abbreviation
        title = mention.text
        marker = re.search(r"(?<![\w])" + re.escape(abbreviation) + r"\.\s*", title)
        if marker:
            title = title[marker.end() :].strip(" .")
        entries.append(ParsedEntry(
            key=f"korneeva-institution-{len(entries) + 1:03d}",
            group="institutional",
            entry_type="misc",
            fields={
                "title": title,
                "organization": primary_expansion(mention.abbreviation_expansion or abbreviation),
                "annotation": mention.text,
                "keywords": "institutional",
            },
            confidence="high",
        ))
        seen.add(fingerprint)
    return entries


def write_mentions_csv(path: Path, mentions: list[Mention]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = list(asdict(mentions[0]).keys()) if mentions else list(Mention.__dataclass_fields__)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(asdict(mention) for mention in mentions)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path, help="Directory containing canonical DOCX files")
    parser.add_argument("--bib", type=Path, required=True, help="Merged BibLaTeX output")
    parser.add_argument("--report", type=Path, required=True, help="Detailed JSON report")
    parser.add_argument("--mentions-csv", type=Path, required=True, help="Flat mention table")
    parser.add_argument("--abbreviations", type=Path, help="DOCX abbreviation list")
    parser.add_argument("--canonical-bib", type=Path, help="Normalized canonical BibLaTeX output")
    args = parser.parse_args()

    source = args.source.resolve()
    abbreviation_source = (
        args.abbreviations.resolve()
        if args.abbreviations
        else source / "Sokraschenia.docx"
    )
    abbreviations = extract_abbreviations(abbreviation_source) if abbreviation_source.exists() else {}
    bibliography_source = source / "СПИСОК_ЛИТЕРАТУРЫ.docx"
    raw_entries, editorial_notes = bibliography_entries(bibliography_source)
    canonical = [parse_record(record) for record in raw_entries]
    canonical_field_expansions = expand_entry_abbreviations(canonical, abbreviations)
    footnotes = [
        footnote
        for filename in DOCX_JOBS
        for footnote in extract_footnotes(source / filename)
    ]
    mentions = build_mentions(footnotes, canonical, abbreviations)
    extra, footnote_candidate_stats = footnote_only_entries(mentions, canonical)
    extra_field_expansions = expand_entry_abbreviations(extra, abbreviations)
    institutions = institutional_entries(mentions)
    merged = canonical + extra + institutions

    if args.canonical_bib:
        args.canonical_bib.parent.mkdir(parents=True, exist_ok=True)
        args.canonical_bib.write_text(serialize_biblatex(canonical), encoding="utf-8")

    args.bib.parent.mkdir(parents=True, exist_ok=True)
    bib_text = serialize_biblatex(merged).replace(
        "% Структурированные записи автоматически разобраны из СПИСОК_ЛИТЕРАТУРЫ.docx.\n"
        "% Исходная строка каждой записи сохранена в поле annotation для аудита.",
        "% Полный объединённый инвентарь: канонический список и полные записи из сносок.\n"
        "% Исходная строка каждой записи сохранена в поле annotation для аудита.",
        1,
    )
    args.bib.write_text(bib_text, encoding="utf-8")
    write_mentions_csv(args.mentions_csv, mentions)

    kind_counts = Counter(mention.kind for mention in mentions)
    resolution_counts = Counter(mention.resolution for mention in mentions)
    commentary_units = kind_counts.get("commentary", 0)
    citation_like_units = len(mentions) - commentary_units
    matched_keys = {mention.matched_key for mention in mentions if mention.matched_key}
    report = {
        "method": "lossless footnote inventory with conservative contextual and token-overlap matching",
        "source": source.as_posix(),
        "abbreviation_source": abbreviation_source.as_posix() if abbreviation_source.exists() else None,
        "abbreviations": abbreviations,
        "abbreviation_count": len(abbreviations),
        "structured_field_expansions": dict(canonical_field_expansions + extra_field_expansions),
        "canonical_bibliography_records": len(canonical),
        "footnotes": len(footnotes),
        "footnote_units": len(mentions),
        "source_containers_before_footnote_splitting": len(canonical) + len(footnotes),
        "parsed_blocks_including_commentary": len(canonical) + len(mentions),
        "bibliographic_candidate_blocks_before_deduplication": len(canonical) + citation_like_units,
        "footnote_unit_types": dict(kind_counts),
        "resolutions": dict(resolution_counts),
        "canonical_records_cited_from_footnotes": len(matched_keys),
        "footnote_only_records_added": len(extra),
        "institutional_records_added": len(institutions),
        "merged_unique_records": len(merged),
        "derivation": {
            "source_containers_before_footnote_splitting": {
                "formula": "canonical_bibliography_records + footnotes",
                "calculation": f"{len(canonical)} + {len(footnotes)} = {len(canonical) + len(footnotes)}",
            },
            "parsed_blocks_including_commentary": {
                "formula": "canonical_bibliography_records + footnote_units",
                "calculation": f"{len(canonical)} + {len(mentions)} = {len(canonical) + len(mentions)}",
            },
            "bibliographic_candidate_blocks_before_deduplication": {
                "formula": "canonical_bibliography_records + footnote_units - commentary_units",
                "calculation": f"{len(canonical)} + {len(mentions)} - {commentary_units} = {len(canonical) + citation_like_units}",
            },
            "footnote_units_by_type": dict(kind_counts),
            "footnote_units_by_resolution": dict(resolution_counts),
            "full_reference_candidate_pipeline": footnote_candidate_stats,
            "merged_unique_records": {
                "formula": "canonical_bibliography_records + added_unique_footnote_records + institutional_records",
                "calculation": f"{len(canonical)} + {len(extra)} + {len(institutions)} = {len(merged)}",
            },
        },
        "editorial_notes": editorial_notes,
        "documents": dict(Counter(footnote.document for footnote in footnotes)),
        "footnotes_verbatim": [
            {
                **asdict(footnote),
                "mentions": [
                    asdict(mention)
                    for mention in mentions
                    if mention.document == footnote.document
                    and mention.footnote_ordinal == footnote.ordinal
                ],
            }
            for footnote in footnotes
        ],
        "footnote_only_entries": [
            {
                "key": entry.key,
                "type": entry.entry_type,
                "confidence": entry.confidence,
                "warnings": entry.warnings,
                "fields": entry.fields,
            }
            for entry in extra
        ],
        "institutional_entries": [
            {
                "key": entry.key,
                "type": entry.entry_type,
                "confidence": entry.confidence,
                "fields": entry.fields,
            }
            for entry in institutions
        ],
        "unresolved_mentions": [
            asdict(mention)
            for mention in mentions
            if mention.resolution == "unresolved"
        ],
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({key: value for key, value in report.items() if key not in {
        "footnotes_verbatim", "footnote_only_entries", "unresolved_mentions"
    }}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
