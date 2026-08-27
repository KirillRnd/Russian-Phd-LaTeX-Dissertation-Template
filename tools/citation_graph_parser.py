#!/usr/bin/env python3
"""Build a citation graph from the active dissertation footnotes.

Unlike the legacy flat inventory, this parser treats repeated references as
edges between ordered citation mentions.  It preserves every source string,
separates locators from work identity, creates records only for explicit full
citations, and reports dependent and root ambiguities separately.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

from bibliography_parser import ParsedEntry, parse_record, serialize_biblatex
from docx_to_latex import bibliography_entries
from full_bibliography_parser import (
    BIBLIOGRAPHIC_ABBREVIATION_KEYS,
    DOCX_JOBS,
    INITIALS_RE,
    JOURNAL_ABBREVIATIONS,
    LOCATOR_RE,
    URL_RE,
    YEAR_RE,
    Matcher,
    author_family,
    citation_payload,
    clean_reference_source,
    entry_identity,
    expand_entry_abbreviations,
    extract_abbreviations,
    extract_footnotes,
    extract_locator,
    institutional_abbreviation,
    leading_abbreviation,
    normalize,
    primary_expansion,
    split_units,
    strip_locator,
    tokens,
)


REL_SAME_WORK_RE = re.compile(r"^(?P<surface>Ibid\.?|Ibidem\.?|Там\s+же)\s*[:.,;-]?\s*", re.I)
REL_SAME_AUTHOR_RE = re.compile(
    r"^(?P<surface>Idem\.?|Eadem\.?|Iidem\.?|Его\s+же|Е[её]\s+же|"
    r"Их\s+же|Он\s+же|Она\s+же)\s*[:.,;-]?\s*",
    re.I,
)
OP_CIT_RE = re.compile(
    r"(?P<surface>(?:Op|Oр|Ор|Оp)\.?\s*cit\.?|Указ\.?\s*соч\.?|"
    r"Цит\.?\s*соч\.?)",
    re.I,
)
CROSS_REFERENCE_RE = re.compile(r"^(?P<surface>supra|infra|см\.\s*(?:выше|ниже))\b", re.I)
AUTHOR_PREFIX_RE = re.compile(
    r"^(?P<author>[A-ZА-ЯЁÀ-ÖØ-Þ][\w'’`-]{1,60}"
    r"(?:\s+(?:[A-ZА-ЯЁÀ-ÖØ-Þ]\.){1,3})?)\s+",
    re.U,
)

ACTIVE_DOCX = list(DOCX_JOBS)
EXCLUDED_SUPERSEDED_DOCX = {
    "ИСТОРИОГРАФИЯ_ВЕРСИЯ_3.docx": "superseded by ВВЕДЕНИЕ_ВЕРСИЯ_3.docx",
    "ИСТОЧНИК_ВЕРСИЯ_3.docx": "superseded by ВВЕДЕНИЕ_ВЕРСИЯ_3.docx",
}

# Families identify a historical work whose citations may leave the edition
# implicit.  They prevent a short work title from being assigned to the one
# canonical entry that happens to have the shortest title.
SOURCE_FAMILIES: list[tuple[str, re.Pattern[str], set[str]]] = [
    (
        "costums_de_tarrega",
        re.compile(r"^(?:Costums|Costumbres|Consuetudines ville) (?:de )?(?:T[aá]rreg[ae]|Tarege)\b", re.I),
        {"korneeva-sources-022"},
    ),
    (
        "coutumes_de_perpignan",
        re.compile(r"^(?:Les )?Coutumes? de Perpignan\b|^Costums de Perpignan\b", re.I),
        {"korneeva-sources-029"},
    ),
    (
        "gudiol_usatges",
        re.compile(r"^Gudiol i Cunill J\. Traducció dels Usatges\b", re.I),
        {"korneeva-sources-040"},
    ),
    (
        "usatges_de_barcelona",
        re.compile(r"^(?:Usatges de Barcelona|Usatici Barchinonae)\b", re.I),
        {f"korneeva-sources-{number:03d}" for number in (37, 38, 39, 40, 41, 42)},
    ),
    (
        "costums_de_tortosa",
        re.compile(r"^(?:Costums|Costumbres|Consuetudines) de Tortosa\b", re.I),
        {f"korneeva-sources-{number:03d}" for number in (4, 5, 9, 14, 15, 16, 30, 31, 32)},
    ),
    (
        "costums_de_lleida",
        re.compile(r"^(?:Costums|Costumbres) de (?:Lleida|Lérida|Llerida)\b", re.I),
        {f"korneeva-sources-{number:03d}" for number in (11, 12, 19)},
    ),
    (
        "costums_d_orta",
        re.compile(r"^(?:Costums|Costumbres) (?:de |d[’'])(?:Orta|Horta)\b", re.I),
        {"korneeva-sources-013", "korneeva-sources-020"},
    ),
    (
        "costums_de_miravet",
        re.compile(r"^(?:Costums|Costumbres|Constitutiones|Costituciones) .*Mirabeti?\b", re.I),
        {"korneeva-sources-007", "korneeva-sources-018", "korneeva-sources-028"},
    ),
    (
        "recognoverunt_proceres",
        re.compile(r"^Recognoverunt proceres\b", re.I),
        {"korneeva-sources-034", "korneeva-sources-035"},
    ),
    (
        "justicia_i_resolucio",
        re.compile(r"^Justícia i resolució(?: de conflictes)?\b", re.I),
        {"korneeva-sources-025", "korneeva-sources-026"},
    ),
]


def curated_short_citation_entries() -> list[ParsedEntry]:
    """Return verified editions omitted from the standalone bibliography DOCX.

    These three works occur only in shortened footnote form, so they cannot be
    reconstructed safely by the generic record parser.  Keeping the completed
    descriptions here makes the graph and ``korneeva_full.bib`` reproducible.
    """

    return [
        ParsedEntry(
            key="korneeva-curated-panormia",
            group="curated-footnote",
            entry_type="incollection",
            fields={
                "author": "Ivo Carnotensis",
                "title": "Panormia. Liber V",
                "booktitle": "Patrologiae cursus completus. Series Latina",
                "editor": "Migne, J.-P.",
                "location": "Parisiis",
                "publisher": "apud J.-P. Migne editorem",
                "date": "1855",
                "volume": "161",
                "pages": "1219",
                "note": "Cap. 33; column 1219",
                "annotation": (
                    "Ivo Carnotensis. Panormia. V. 33 // Patrologiae cursus "
                    "completus. Series Latina / accurante J.-P. Migne. "
                    "Parisiis: apud J.-P. Migne editorem, 1855. T. 161. Col. 1219"
                ),
                "keywords": "curated-footnote",
            },
            confidence="high",
        ),
        ParsedEntry(
            key="korneeva-curated-to-figueras-mujeres",
            group="curated-footnote",
            entry_type="article",
            fields={
                "author": "To Figueras, Lluís",
                "title": "Las mujeres en la sociedad catalana de los siglos IX al XI",
                "journaltitle": "Arenal: Revista de historia de las mujeres",
                "date": "2001",
                "volume": "8",
                "number": "2",
                "pages": "349--363",
                "annotation": (
                    "To Figueras L. Las mujeres en la sociedad catalana de los "
                    "siglos IX al XI // Arenal: Revista de historia de las mujeres. "
                    "2001. Vol. 8. No. 2. P. 349--363"
                ),
                "keywords": "curated-footnote",
            },
            confidence="high",
        ),
        ParsedEntry(
            key="korneeva-curated-varyash-oath",
            group="curated-footnote",
            entry_type="incollection",
            fields={
                "author": "Варьяш, И. И.",
                "title": "Клятва пиренейских сарацин",
                "booktitle": "Право в средневековом мире",
                "editor": "Варьяш, И. И. and Попова, Г. А.",
                "location": "Москва",
                "publisher": "ИВИ РАН",
                "date": "2009",
                "pages": "167--188",
                "annotation": (
                    "Варьяш И.И. Клятва пиренейских сарацин // Право в "
                    "средневековом мире / под ред. И.И. Варьяш, Г.А. Поповой. "
                    "М.: ИВИ РАН, 2009. С. 167--188"
                ),
                "keywords": "curated-footnote",
            },
            confidence="high",
        ),
    ]


@dataclass
class Relation:
    relation_type: str | None = None
    surface: str | None = None
    payload: str = ""
    explicit_author: str | None = None


@dataclass
class GraphMention:
    mention_id: str
    document: str
    footnote_ordinal: int
    note_id: str
    unit_ordinal: int
    text: str
    mention_type: str
    explicit_payload: str
    explicit_locator: str | None = None
    effective_locator: str | None = None
    relation_type: str | None = None
    relation_surface: str | None = None
    antecedent_mention_id: str | None = None
    explicit_author: str | None = None
    inherited_author: str | None = None
    inherited_work_id: str | None = None
    resolved_work_id: str | None = None
    candidate_work_ids: list[str] = field(default_factory=list)
    resolution: str = "not_bibliographic"
    resolution_method: str | None = None
    confidence: float | None = None
    abbreviation: str | None = None
    abbreviation_expansion: str | None = None
    source_family: str | None = None
    warnings: list[str] = field(default_factory=list)


def relation_normal_form(value: str) -> str:
    """Normalize common Latin/Cyrillic homoglyphs only for operator matching."""

    return value.replace("Ор.", "Op.").replace("Oр.", "Op.").replace("Оp.", "Op.")


def graph_split_units(value: str) -> list[str]:
    """Repair false boundaries caused by initials inside publisher/editor data."""

    repaired: list[str] = []
    for unit in split_units(value):
        continuation = bool(
            repaired
            and (
                re.search(r"(?:св|пер|ред|изд|сост|тип)\.\s*$", repaired[-1], re.I)
                or re.match(r"^Владимира\s+Н\.Т\.\s+Корчак-Новицкого", unit)
                or (
                    re.match(r"^Горбун\s+Г\.\s*С\.\s+\d{4}", unit)
                    and re.search(r"(?:под\s+ред|пер)\.\s*$", repaired[-1], re.I)
                )
            )
        )
        if continuation:
            repaired[-1] = f"{repaired[-1]} {unit}".strip()
        else:
            repaired.append(unit)
    refined: list[str] = []
    for unit in repaired:
        marker = re.search(
            r"\b[СC]м\.\s+также\s+(?=[A-ZА-ЯЁÀ-ÖØ-Þ][\w'’`-]+(?:\s+[\w'’`-]+){0,3}\s+[A-ZА-ЯЁ]\.?)",
            unit,
            re.I | re.U,
        )
        if marker and marker.start() > 0:
            first = unit[: marker.start()].strip()
            second = unit[marker.end() :].strip()
            if first:
                refined.append(first)
            if second:
                refined.append(second)
        else:
            nested_source = re.search(
                r"\bОб\s+этом\s+конкретном\s+случае:\s*(?=Usatges\s+de\s+Barcelona\b)",
                unit,
                re.I,
            )
            if nested_source and nested_source.start() > 0:
                first = unit[: nested_source.start()].strip()
                second = unit[nested_source.end() :].strip()
                if first:
                    refined.append(first)
                if second:
                    refined.append(second)
            else:
                refined.append(unit)
    return refined


def detect_relation(value: str) -> Relation:
    stripped = value.strip()
    normalized = relation_normal_form(stripped)
    match = REL_SAME_WORK_RE.match(normalized)
    if match:
        return Relation("same_work", stripped[: match.end()].strip(), stripped[match.end() :].strip())

    same_author = REL_SAME_AUTHOR_RE.match(normalized)
    if same_author:
        payload = stripped[same_author.end() :].strip()
        op_cit = OP_CIT_RE.match(relation_normal_form(payload))
        if op_cit:
            remainder = payload[op_cit.end() :].strip(" .,:;-")
            return Relation(
                "same_author_op_cit",
                stripped[: same_author.end() + op_cit.end()].strip(),
                remainder,
            )
        return Relation("same_author", stripped[: same_author.end()].strip(), payload)

    cross = CROSS_REFERENCE_RE.match(normalized)
    if cross:
        return Relation("cross_reference", cross.group("surface"), stripped[cross.end() :].strip())

    op_cit = OP_CIT_RE.search(normalized[:160])
    if op_cit:
        prefix = stripped[: op_cit.start()].strip(" .,:;-")
        explicit_author = prefix or None
        payload = stripped[op_cit.end() :].strip(" .,:;-")
        return Relation("op_cit", op_cit.group("surface"), payload, explicit_author)
    return Relation(None, None, stripped)


def commentary_only(value: str) -> bool:
    stripped = value.strip()
    if not stripped:
        return True
    if re.search(r"(?:настоящ(?:ей|его) (?:работы|исследования)|§\s*\d|глав[уае]\s+\d)", stripped, re.I):
        if not YEAR_RE.search(stripped) and " // " not in stripped and not URL_RE.search(stripped):
            return True
    if re.search(r"(?:см\.|см\.:|см\s*)\s*$", stripped, re.I):
        return True
    if re.match(
        r"^(?:Здесь и далее|В историографии|Для исследования|Название .+ появилось|"
        r"В данном исследовании|Проблема заключается|Детальн(?:ая|ые) библиограф|"
        r"[^:]{1,120}\s+отмечал[аи]?,?\s+что)",
        stripped,
        re.I,
    ):
        return True
    if stripped.endswith(":") and not LOCATOR_RE.search(stripped) and " // " not in stripped:
        return True
    if re.match(r"^[^.;:]{1,100}\(лат\.?.{0,80}[—-]", stripped, re.I) and " // " not in stripped:
        return True
    return False


def explicit_kind(value: str, relation: Relation) -> str:
    if relation.relation_type in {"same_work", "op_cit", "same_author_op_cit"}:
        return "relational_reference"
    if relation.relation_type == "cross_reference":
        return "cross_reference"
    candidate = citation_payload(relation.payload or value)
    if re.match(r"^[A-ZА-ЯЁÀ-ÖØ-Þ][^,]{2,80},\s*[^,]{2,100},\s*[A-ZА-ЯЁ]?\s*\d", candidate):
        return "full_reference"
    full_signals = sum(
        (
            bool(URL_RE.search(candidate)),
            bool(YEAR_RE.search(candidate)),
            " // " in candidate,
            bool(INITIALS_RE.search(candidate)),
            bool(re.search(r"\b[^.:;]{1,50}:\s*[^,.;]{2,100},\s*(?:1[5-9]|20)\d{2}", candidate)),
        )
    )
    if full_signals >= 2 or (URL_RE.search(candidate) and len(candidate) > 25):
        return "full_reference"
    if commentary_only(candidate):
        return "commentary"
    if any(pattern.search(candidate) for _, pattern, _ in SOURCE_FAMILIES):
        return "short_title_reference"
    if relation.relation_type == "same_author":
        return "author_inherited_reference"
    if LOCATOR_RE.search(candidate) or re.search(r"\.{2,}|…", candidate):
        return "short_title_reference"
    if len(tokens(candidate)) >= 2 and re.match(r"^[A-ZА-ЯЁÀ-ÖØ-Þ]", candidate):
        return "possible_reference"
    return "commentary"


def page_numbers(value: str) -> list[int]:
    numbers: list[int] = []
    for match in re.finditer(r"\b(?:С|P|S)\.\s*(\d{1,4})", value, re.I):
        numbers.append(int(match.group(1)))
    return numbers


def page_range(entry: ParsedEntry) -> tuple[int, int] | None:
    value = entry.fields.get("pages", "")
    found = [int(item) for item in re.findall(r"\d{1,4}", value)]
    if not found:
        return None
    return min(found), max(found)


def family_candidates(value: str, entries: dict[str, ParsedEntry]) -> tuple[str | None, list[str]]:
    payload = citation_payload(value)
    for family, pattern, configured in SOURCE_FAMILIES:
        if not pattern.search(payload):
            continue
        candidates = [key for key in configured if key in entries]
        years = YEAR_RE.findall(payload)
        if years:
            dated = [key for key in candidates if entries[key].fields.get("date", "").startswith(years[-1])]
            if dated:
                candidates = dated
        pages = page_numbers(payload)
        if pages:
            ranged = [
                key for key in candidates
                if page_range(entries[key])
                and all(page_range(entries[key])[0] <= page <= page_range(entries[key])[1] for page in pages)
            ]
            if ranged:
                candidates = ranged
        normalized = normalize(payload)
        edition_hints = {
            "gudiol": "korneeva-sources-040",
            "rovira": "korneeva-sources-039",
            "serrat daura": "korneeva-sources-013",
        }
        for hint, key in edition_hints.items():
            if hint in normalized and key in candidates:
                return family, [key]
        return family, sorted(candidates)
    return None, []


class WorkRegistry:
    def __init__(self, canonical: list[ParsedEntry]):
        self.entries = list(canonical)
        self.by_key = {entry.key: entry for entry in self.entries}
        self.source_fingerprints: dict[str, str] = {}
        self.identities: dict[str, str] = {}
        for entry in self.entries:
            source = entry.fields.get("annotation", entry.fields.get("title", ""))
            fingerprint = normalize(strip_locator(source))
            if fingerprint:
                self.source_fingerprints.setdefault(fingerprint, entry.key)
            identity = entry_identity(entry)
            if identity:
                self.identities.setdefault(identity, entry.key)
        self.extra: list[ParsedEntry] = []
        self.extra_stats: Counter[str] = Counter()
        self.family_nodes: dict[str, dict[str, object]] = {}
        self.inferred_work_fingerprints: dict[str, str] = {}

    def family_work_id(self, family: str, edition_candidates: list[str]) -> str:
        work_id = f"work-family-{family}"
        if work_id not in self.family_nodes:
            titles = [
                self.by_key[key].fields.get("title", key)
                for key in edition_candidates if key in self.by_key
            ]
            self.family_nodes[work_id] = {
                "work_id": work_id,
                "type": "conceptual_historical_work",
                "group": "source-family",
                "title": family.replace("_", " "),
                "author": None,
                "date": None,
                "source": "inferred_source_family",
                "edition_candidates": edition_candidates,
                "edition_titles": titles,
            }
        return work_id

    def inferred_work_id(
        self,
        mention: GraphMention,
        inherited_author: str | None = None,
    ) -> str | None:
        """Create a work-level node when a short citation identifies a work.

        This deliberately does not create a BibLaTeX edition record: a title
        and author can identify the cited work without supplying publication
        data for a particular edition.
        """

        payload = strip_locator(mention.explicit_payload or mention.text).strip(" .;,:…")
        payload = re.split(r"\s*//\s*", payload, maxsplit=1)[0]
        explicit_author = inherited_author
        title = payload
        author_title = re.match(
            r"^(?P<author>.{2,100}?\s+(?:[A-ZА-ЯЁÀ-ÖØ-Þ]\.\s*){1,3})\s+(?P<title>.+)$",
            payload,
            re.U,
        )
        if author_title:
            explicit_author = author_title.group("author").strip()
            title = author_title.group("title").strip()
        title = re.sub(r"\.\s*[IVXLCDM]+\.\d+\s*$", "", title, flags=re.I).strip(" .;,:…")
        title_tokens = tokens(title)
        if (len(title_tokens) < 2 and not explicit_author) or len(normalize(title)) < 8:
            return None
        fingerprint = f"{author_lookup_key(explicit_author or '')}|{normalize(title)}"
        existing = self.inferred_work_fingerprints.get(fingerprint)
        if existing:
            return existing
        work_id = f"work-inferred-{len(self.inferred_work_fingerprints) + 1:03d}"
        self.inferred_work_fingerprints[fingerprint] = work_id
        self.family_nodes[work_id] = {
            "work_id": work_id,
            "type": "conceptual_incomplete_work",
            "group": "short-citation-work",
            "title": title,
            "author": explicit_author,
            "date": None,
            "source": "inferred_from_short_citation",
            "edition_candidates": [],
            "first_mention_id": mention.mention_id,
        }
        return work_id

    def matcher(self) -> Matcher:
        return Matcher(self.entries)

    def add_or_find_full(
        self,
        mention: GraphMention,
        inherited_author: str | None = None,
    ) -> tuple[str | None, str]:
        raw_source = mention.explicit_payload or mention.text
        if " // " in raw_source:
            source = re.split(r"(?<=\d)[.:]\s*[«“]", raw_source, maxsplit=1)[0].strip(" .;,:")
        else:
            source = clean_reference_source(raw_source)
        fingerprint = normalize(strip_locator(source))
        if len(fingerprint) < 20:
            self.extra_stats["rejected_too_short_after_cleanup"] += 1
            return None, "too_short_after_cleanup"
        if fingerprint in self.source_fingerprints:
            self.extra_stats["resolved_duplicate_source_text"] += 1
            return self.source_fingerprints[fingerprint], "duplicate_source_text"

        key = f"korneeva-footnote-{len(self.extra) + 1:03d}"
        entry = parse_record({"key": key, "group": "footnote-only", "text": source})
        if inherited_author:
            entry.fields["author"] = inherited_author
            entry.fields["annotation"] = source
        identity = entry_identity(entry)
        if identity and identity in self.identities:
            self.extra_stats["resolved_duplicate_structured_identity"] += 1
            return self.identities[identity], "duplicate_structured_identity"

        entry.fields["keywords"] = "footnote-only"
        self.entries.append(entry)
        self.by_key[key] = entry
        self.extra.append(entry)
        self.source_fingerprints[fingerprint] = key
        if identity:
            self.identities[identity] = key
        self.extra_stats["added_unique_footnote_records"] += 1
        return key, "new_footnote_only_record"


def work_author(registry: WorkRegistry, key: str | None) -> str | None:
    if not key:
        return None
    if key in registry.by_key:
        return registry.by_key[key].fields.get("author")
    node = registry.family_nodes.get(key)
    return node.get("author") if node else None


def concise_inherited_author(value: str | None) -> str | None:
    """Trim a title accidentally absorbed into an author by a partial record."""

    if not value:
        return None
    first_sentence = value.split(". ", 1)[0].strip(" .")
    if (
        first_sentence != value.strip(" .")
        and 1 < len(first_sentence.split()) <= 5
        and not re.search(r"\b(?:ред|пер|сост)\b", first_sentence, re.I)
    ):
        return first_sentence
    return value


def accepts_usatges_locator(
    registry: WorkRegistry,
    work_id: str | None,
    locator_text: str,
) -> bool:
    if not work_id:
        return False
    if work_id == "work-family-usatges_de_barcelona":
        return True
    if work_id in registry.family_nodes:
        title = str(registry.family_nodes[work_id].get("title") or "")
        return "usatge" in normalize(title)
    entry = registry.by_key.get(work_id)
    if not entry:
        return False
    searchable = " ".join(
        (entry.fields.get("title", ""), entry.fields.get("annotation", ""))
    )
    if "usatge" not in normalize(searchable):
        return False
    bounds = page_range(entry)
    pages = page_numbers(locator_text)
    return not (bounds and pages) or all(bounds[0] <= page <= bounds[1] for page in pages)


def author_lookup_key(value: str) -> str:
    value = value.strip(" .,:;-")
    surname = value.split()[0] if value else ""
    return normalize(surname)


def author_lookup_keys(value: str, available: set[str]) -> list[str]:
    """Match abbreviated multiword surnames without discarding particles."""

    normalized = normalize(value)
    words = [word for word in normalized.split() if len(word) > 1]
    compact = " ".join(words)
    if not compact:
        return []
    exact = [key for key in available if key == compact]
    if exact:
        return exact
    prefix = [key for key in available if key.startswith(compact) or compact.startswith(key)]
    if prefix:
        return sorted(prefix)
    first = compact.split()[0]
    return sorted(key for key in available if key.split()[0] == first)


def canonical_author_candidates(
    author: str,
    locator_text: str,
    registry: WorkRegistry,
) -> list[str]:
    available: dict[str, list[str]] = defaultdict(list)
    for entry in registry.entries:
        for family in author_family(entry):
            available[family].append(entry.key)
    families = author_lookup_keys(author, set(available))
    candidates = list(dict.fromkeys(key for family in families for key in available[family]))
    pages = page_numbers(locator_text)
    if pages:
        compatible: list[str] = []
        for key in candidates:
            entry = registry.by_key[key]
            bounds = page_range(entry)
            total = entry.fields.get("pagetotal", "")
            totals = [int(item) for item in re.findall(r"\d{1,5}", total)]
            if bounds and all(bounds[0] <= page <= bounds[1] for page in pages):
                compatible.append(key)
            elif totals and all(page <= max(totals) for page in pages):
                compatible.append(key)
        if compatible:
            candidates = compatible
    return candidates


def direct_match(
    mention: GraphMention,
    registry: WorkRegistry,
) -> tuple[str | None, list[str], str | None, float | None]:
    family, candidates = family_candidates(mention.explicit_payload, registry.by_key)
    mention.source_family = family
    if family:
        if len(candidates) == 1:
            return candidates[0], candidates, "source_family_unique", 0.97
        family_work_id = registry.family_work_id(family, candidates)
        return family_work_id, candidates, "work_resolved_edition_ambiguous", 0.9

    key, score, method = registry.matcher().match(mention.explicit_payload)
    if key is None:
        author_match = re.match(
            r"^(?P<surname>[A-ZА-ЯЁÀ-ÖØ-Þ][\w'’`-]{2,60})"
            r"(?:\s+(?:[A-ZА-ЯЁÀ-ÖØ-Þ]\.){1,3})\s+(?P<title>.+)$",
            mention.explicit_payload,
            re.U,
        )
        if author_match:
            surname = normalize(author_match.group("surname"))
            title_tokens = tokens(strip_locator(author_match.group("title")))
            ranked: list[tuple[float, str]] = []
            for entry in registry.entries:
                families = author_family(entry)
                if not any(
                    SequenceMatcher(None, surname, family.split()[0]).ratio() >= 0.88
                    for family in families
                ):
                    continue
                entry_title_tokens = tokens(entry.fields.get("title", ""))
                if not title_tokens or not entry_title_tokens:
                    continue
                containment = len(title_tokens & entry_title_tokens) / len(title_tokens)
                if containment >= 0.65:
                    ranked.append((containment, entry.key))
            ranked.sort(reverse=True)
            if ranked and (len(ranked) == 1 or ranked[0][0] - ranked[1][0] >= 0.15):
                return ranked[0][1], [ranked[0][1]], "author_and_truncated_title", round(ranked[0][0], 3)
    return key, ([key] if key else []), method, score or None


def build_graph(
    footnotes,
    canonical: list[ParsedEntry],
    abbreviations: dict[str, str],
) -> tuple[list[GraphMention], WorkRegistry, list[ParsedEntry]]:
    registry = WorkRegistry(canonical + curated_short_citation_entries())
    mentions: list[GraphMention] = []
    institutional_entries: list[ParsedEntry] = []
    institution_by_fingerprint: dict[str, str] = {}
    counter = 0

    current_document: str | None = None
    last_citation: GraphMention | None = None
    author_history: dict[str, list[tuple[str, str]]] = defaultdict(list)

    def remember(mention: GraphMention) -> None:
        nonlocal last_citation
        last_citation = mention
        if not mention.resolved_work_id:
            return
        author = work_author(registry, mention.resolved_work_id)
        if not author:
            return
        if mention.resolved_work_id in registry.by_key:
            families = author_family(registry.by_key[mention.resolved_work_id])
        else:
            family = " ".join(word for word in normalize(author).split() if len(word) > 1)
            families = [family] if family else []
        for family in families:
            pair = (mention.mention_id, mention.resolved_work_id)
            if pair not in author_history[family]:
                author_history[family].append(pair)

    for footnote in footnotes:
        if footnote.document != current_document:
            current_document = footnote.document
            last_citation = None

        for unit_ordinal, unit in enumerate(graph_split_units(footnote.text), 1):
            counter += 1
            relation = detect_relation(unit)
            kind = explicit_kind(unit, relation)
            mention = GraphMention(
                mention_id=f"mention-{counter:04d}",
                document=footnote.document,
                footnote_ordinal=footnote.ordinal,
                note_id=footnote.note_id,
                unit_ordinal=unit_ordinal,
                text=unit,
                mention_type=kind,
                explicit_payload=relation.payload,
                explicit_locator=extract_locator(unit),
                effective_locator=extract_locator(unit),
                relation_type=relation.relation_type,
                relation_surface=relation.surface,
                explicit_author=relation.explicit_author,
            )

            if kind in {"commentary", "cross_reference"}:
                mention.resolution = "not_bibliographic"
                mention.resolution_method = "commentary_or_internal_cross_reference"
                mentions.append(mention)
                continue

            if (
                relation.relation_type is None
                and last_citation is not None
                and last_citation.document == mention.document
                and last_citation.footnote_ordinal == mention.footnote_ordinal
                and re.match(r"^(?:Ap[eé]ndix|Anhang)\b", unit.strip(), re.I)
            ):
                mention.relation_type = "same_work_implicit_component"
                mention.relation_surface = "implicit component of previous citation"
                mention.antecedent_mention_id = last_citation.mention_id
                mention.inherited_work_id = last_citation.resolved_work_id
                mention.resolved_work_id = last_citation.resolved_work_id
                mention.candidate_work_ids = list(last_citation.candidate_work_ids)
                if mention.resolved_work_id:
                    mention.resolution = "resolved_relation"
                    mention.resolution_method = "implicit_component_same_footnote"
                    mention.confidence = 0.95
                else:
                    mention.resolution = "dependent_pending"
                    mention.resolution_method = "implicit_component_unresolved_antecedent"
                mentions.append(mention)
                remember(mention)
                continue

            abbreviation = leading_abbreviation(unit.strip(), abbreviations)
            if abbreviation is None:
                abbreviation = institutional_abbreviation(unit, abbreviations)
            if abbreviation:
                mention.abbreviation = abbreviation
                mention.abbreviation_expansion = abbreviations[abbreviation]
                abbreviation_key = BIBLIOGRAPHIC_ABBREVIATION_KEYS.get(abbreviation)
                if abbreviation_key in registry.by_key:
                    mention.resolved_work_id = abbreviation_key
                    mention.candidate_work_ids = [abbreviation_key]
                    mention.resolution = "resolved_explicit"
                    mention.resolution_method = "authoritative_abbreviation_list"
                    mention.confidence = 1.0
                    mentions.append(mention)
                    remember(mention)
                    continue
                if abbreviation not in JOURNAL_ABBREVIATIONS:
                    fingerprint = normalize(unit)
                    key = institution_by_fingerprint.get(fingerprint)
                    if key is None:
                        key = f"korneeva-institution-{len(institutional_entries) + 1:03d}"
                        title = unit
                        marker = re.search(r"(?<![\w])" + re.escape(abbreviation) + r"\.\s*", title)
                        if marker:
                            title = title[marker.end() :].strip(" .")
                        entry = ParsedEntry(
                            key=key,
                            group="institutional",
                            entry_type="misc",
                            fields={
                                "title": title,
                                "organization": primary_expansion(abbreviations[abbreviation]),
                                "annotation": unit,
                                "keywords": "institutional",
                            },
                            confidence="high",
                        )
                        institutional_entries.append(entry)
                        registry.entries.append(entry)
                        registry.by_key[key] = entry
                        institution_by_fingerprint[fingerprint] = key
                    mention.resolved_work_id = key
                    mention.candidate_work_ids = [key]
                    mention.resolution = "resolved_explicit"
                    mention.resolution_method = "authoritative_institutional_abbreviation"
                    mention.confidence = 1.0
                    mentions.append(mention)
                    remember(mention)
                    continue

            if relation.relation_type == "same_work":
                if last_citation is None:
                    mention.resolution = "broken_relation"
                    mention.resolution_method = "no_previous_citation_in_document"
                else:
                    mention.antecedent_mention_id = last_citation.mention_id
                    mention.inherited_work_id = last_citation.resolved_work_id
                    mention.resolved_work_id = last_citation.resolved_work_id
                    if mention.explicit_locator is None:
                        mention.effective_locator = last_citation.effective_locator
                    if mention.resolved_work_id:
                        mention.candidate_work_ids = (
                            list(last_citation.candidate_work_ids)
                            if mention.resolved_work_id.startswith("work-family-")
                            else [mention.resolved_work_id]
                        )
                        mention.resolution = "resolved_relation"
                        mention.resolution_method = "same_work_previous_citation"
                        mention.confidence = 1.0
                    else:
                        mention.candidate_work_ids = list(last_citation.candidate_work_ids)
                        mention.resolution = "dependent_pending"
                        mention.resolution_method = "same_work_unresolved_antecedent"
                    if re.match(r"^Us\.\s*\d", relation.payload, re.I) and not accepts_usatges_locator(
                        registry, mention.resolved_work_id, relation.payload
                    ):
                        literal_work_id = mention.resolved_work_id
                        family, editions = family_candidates("Usatges de Barcelona", registry.by_key)
                        inferred_work_id = registry.family_work_id(family, editions) if family else None
                        mention.inherited_work_id = literal_work_id
                        mention.resolved_work_id = inferred_work_id
                        mention.candidate_work_ids = [
                            key for key in (literal_work_id, inferred_work_id) if key
                        ]
                        mention.resolution = "relation_conflict"
                        mention.resolution_method = (
                            "literal_same_work_antecedent_conflicts_with_usatges_locator"
                        )
                        mention.confidence = 0.7
                        mention.warnings.append(
                            "literal same-work antecedent conflicts with an Usatges-style locator; semantic work inferred separately"
                        )
                mentions.append(mention)
                remember(mention)
                continue

            inherited_author: str | None = None
            if relation.relation_type in {"same_author", "same_author_op_cit"}:
                if last_citation:
                    mention.antecedent_mention_id = last_citation.mention_id
                    inherited_author = concise_inherited_author(
                        work_author(registry, last_citation.resolved_work_id)
                    )
                    mention.inherited_author = inherited_author
                if inherited_author is None:
                    mention.warnings.append("same-author operator has no resolved author antecedent")

            if relation.relation_type in {"op_cit", "same_author_op_cit"}:
                author_value = relation.explicit_author or inherited_author or ""
                matching_families = author_lookup_keys(author_value, set(author_history))
                history = [
                    pair for family in matching_families for pair in author_history.get(family, [])
                ]
                history.sort(key=lambda pair: int(pair[0].split("-")[-1]))
                unique_work_ids = list(dict.fromkeys(key for _, key in history))
                if history:
                    antecedent_id, nearest_work_id = history[-1]
                    mention.antecedent_mention_id = antecedent_id
                    mention.inherited_work_id = nearest_work_id
                    mention.resolved_work_id = nearest_work_id
                    mention.candidate_work_ids = unique_work_ids
                    mention.resolution = "resolved_relation"
                    mention.resolution_method = "op_cit_nearest_prior_work_by_author"
                    mention.confidence = 0.95
                    if len(unique_work_ids) > 1:
                        mention.warnings.append(
                            "multiple earlier works by this author; nearest preceding work selected by relational order"
                        )
                    mentions.append(mention)
                    remember(mention)
                    continue
                if author_value:
                    unique_work_ids = canonical_author_candidates(author_value, unit, registry)
                mention.candidate_work_ids = unique_work_ids
                if len(unique_work_ids) == 1:
                    mention.inherited_work_id = unique_work_ids[0]
                    mention.resolved_work_id = unique_work_ids[0]
                    mention.resolution = "resolved_relation"
                    mention.resolution_method = "op_cit_unique_canonical_work_by_author_and_locator"
                    mention.confidence = 0.85
                elif len(unique_work_ids) > 1:
                    mention.resolution = "ambiguous_antecedent"
                    mention.resolution_method = "op_cit_no_prior_mention_multiple_canonical_works"
                else:
                    mention.resolution = "broken_relation"
                    mention.resolution_method = "op_cit_no_prior_work_by_author"
                mentions.append(mention)
                remember(mention)
                continue

            key, candidates, method, score = direct_match(mention, registry)
            mention.candidate_work_ids = candidates
            if key:
                mention.resolved_work_id = key
                mention.resolution = (
                    "resolved_work_edition_ambiguous"
                    if key.startswith("work-family-")
                    else "resolved_explicit"
                )
                mention.resolution_method = method
                mention.confidence = score
            elif candidates:
                mention.resolution = "ambiguous_root"
                mention.resolution_method = method
            elif kind in {"short_title_reference", "author_inherited_reference"}:
                inferred_work_id = registry.inferred_work_id(mention, inherited_author)
                if inferred_work_id:
                    mention.resolved_work_id = inferred_work_id
                    mention.candidate_work_ids = []
                    mention.resolution = "resolved_work_edition_missing"
                    mention.resolution_method = "work_identity_inferred_from_author_and_short_title"
                    mention.confidence = 0.85
                else:
                    mention.resolution = "unresolved_root"
                    mention.resolution_method = method or "short_title_insufficient_for_work_identity"
            elif kind == "full_reference":
                key, add_method = registry.add_or_find_full(mention, inherited_author)
                if key:
                    mention.resolved_work_id = key
                    mention.candidate_work_ids = [key]
                    mention.resolution = (
                        "new_footnote_only_record"
                        if add_method == "new_footnote_only_record"
                        else "resolved_explicit"
                    )
                    mention.resolution_method = add_method
                    mention.confidence = 0.9 if add_method == "new_footnote_only_record" else 0.98
                else:
                    mention.resolution = "unresolved_root"
                    mention.resolution_method = add_method
            else:
                mention.resolution = "unresolved_root"
                mention.resolution_method = method or "no_work_match"

            if relation.relation_type == "same_author" and mention.antecedent_mention_id:
                mention.relation_type = "same_author"
            mentions.append(mention)
            remember(mention)

    # Propagate resolved work identities through same-work chains until stable.
    by_id = {mention.mention_id: mention for mention in mentions}
    changed = True
    while changed:
        changed = False
        for mention in mentions:
            if mention.resolution != "dependent_pending" or not mention.antecedent_mention_id:
                continue
            antecedent = by_id[mention.antecedent_mention_id]
            if antecedent.resolved_work_id:
                mention.inherited_work_id = antecedent.resolved_work_id
                mention.resolved_work_id = antecedent.resolved_work_id
                mention.candidate_work_ids = (
                    list(antecedent.candidate_work_ids)
                    if antecedent.resolved_work_id.startswith("work-family-")
                    else [antecedent.resolved_work_id]
                )
                mention.resolution = "resolved_relation"
                mention.resolution_method = (
                    "implicit_component_propagated_through_chain"
                    if mention.relation_type == "same_work_implicit_component"
                    else "same_work_propagated_through_chain"
                )
                mention.confidence = 1.0
                changed = True

    return mentions, registry, institutional_entries


def write_csv(path: Path, mentions: list[GraphMention]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for mention in mentions:
        row = asdict(mention)
        row["candidate_work_ids"] = ";".join(mention.candidate_work_ids)
        row["warnings"] = "; ".join(mention.warnings)
        rows.append(row)
    columns = list(rows[0]) if rows else list(GraphMention.__dataclass_fields__)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def validate_graph(mentions: list[GraphMention]) -> dict[str, object]:
    ids = [mention.mention_id for mention in mentions]
    assert len(ids) == len(set(ids)), "duplicate mention ids"
    positions = {mention_id: index for index, mention_id in enumerate(ids)}
    cross_document_edges = []
    forward_edges = []
    by_id = {mention.mention_id: mention for mention in mentions}
    for mention in mentions:
        if not mention.antecedent_mention_id:
            continue
        antecedent = by_id[mention.antecedent_mention_id]
        if positions[antecedent.mention_id] >= positions[mention.mention_id]:
            forward_edges.append((mention.mention_id, antecedent.mention_id))
        if mention.relation_type == "same_work" and antecedent.document != mention.document:
            cross_document_edges.append((mention.mention_id, antecedent.mention_id))
    assert not forward_edges, f"forward citation edges: {forward_edges[:3]}"
    assert not cross_document_edges, f"cross-document immediate relations: {cross_document_edges[:3]}"
    return {
        "unique_mention_ids": True,
        "all_relation_edges_point_backward": True,
        "no_same_work_relation_crosses_document_boundary": True,
    }


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("--bib", type=Path, required=True)
    parser.add_argument("--canonical-bib", type=Path)
    parser.add_argument("--graph", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--mentions-csv", type=Path, required=True)
    parser.add_argument("--abbreviations", type=Path)
    args = parser.parse_args()

    source = args.source.resolve()
    abbreviation_source = (args.abbreviations.resolve() if args.abbreviations else source / "Sokraschenia.docx")
    abbreviations = extract_abbreviations(abbreviation_source)
    raw_entries, editorial_notes = bibliography_entries(source / "СПИСОК_ЛИТЕРАТУРЫ.docx")
    canonical = [parse_record(record) for record in raw_entries]
    field_expansions = expand_entry_abbreviations(canonical, abbreviations)
    footnotes = [
        footnote
        for filename in ACTIVE_DOCX
        for footnote in extract_footnotes(source / filename)
    ]
    mentions, registry, institutions = build_graph(footnotes, canonical, abbreviations)
    validation = validate_graph(mentions)
    curated = curated_short_citation_entries()
    merged = canonical + curated + registry.extra + institutions

    if args.canonical_bib:
        args.canonical_bib.parent.mkdir(parents=True, exist_ok=True)
        args.canonical_bib.write_text(serialize_biblatex(canonical), encoding="utf-8")
    args.bib.parent.mkdir(parents=True, exist_ok=True)
    args.bib.write_text(serialize_biblatex(merged), encoding="utf-8")
    write_csv(args.mentions_csv, mentions)

    resolution_counts = Counter(mention.resolution for mention in mentions)
    type_counts = Counter(mention.mention_type for mention in mentions)
    relation_counts = Counter(
        mention.relation_type for mention in mentions if mention.relation_type
    )
    root_problems = [
        mention for mention in mentions
        if mention.resolution in {
            "ambiguous_root", "unresolved_root", "ambiguous_antecedent",
            "broken_relation", "relation_conflict",
        }
    ]
    dependent = [mention for mention in mentions if mention.resolution == "dependent_pending"]
    warnings = [mention for mention in mentions if mention.warnings]
    relation_edges = [
        {
            "from": mention.mention_id,
            "to": mention.antecedent_mention_id,
            "type": mention.relation_type,
            "resolved_work_id": mention.resolved_work_id,
        }
        for mention in mentions if mention.antecedent_mention_id
    ]
    relation_edges.extend(
        {
            "from": mention.mention_id,
            "to": mention.antecedent_mention_id,
            "type": "same_container",
            "surface": "Ibid.",
            "resolved_work_id": mention.resolved_work_id,
        }
        for mention in mentions
        if mention.antecedent_mention_id
        and mention.relation_type == "same_author"
        and re.search(r"//\s*Ibid\.?", mention.text, re.I)
    )
    work_nodes = [
        {
            "work_id": entry.key,
            "type": entry.entry_type,
            "group": entry.group,
            "title": entry.fields.get("title"),
            "author": entry.fields.get("author"),
            "date": entry.fields.get("date"),
            "source": "canonical" if entry in canonical else ("footnote_only" if entry in registry.extra else "institutional"),
        }
        for entry in merged
    ] + list(registry.family_nodes.values())
    work_ids = {node["work_id"] for node in work_nodes}
    citation_edges = [
        {
            "from": mention.mention_id,
            "to": mention.resolved_work_id,
            "type": "cites_work",
            "resolution": mention.resolution,
        }
        for mention in mentions
        if mention.resolved_work_id
    ]
    edition_edges = [
        {
            "from": node["work_id"],
            "to": edition_id,
            "type": "has_candidate_edition",
        }
        for node in registry.family_nodes.values()
        for edition_id in node.get("edition_candidates", [])
    ]
    missing_work_targets = [
        edge for edge in citation_edges + edition_edges if edge["to"] not in work_ids
    ]
    assert not missing_work_targets, f"missing work targets: {missing_work_targets[:3]}"
    validation["all_citation_and_edition_edges_target_existing_work_nodes"] = True
    graph_relation_edge_types = Counter(edge["type"] for edge in relation_edges)
    graph = {
        "model": "ordered multi-level citation graph",
        "node_types": ["citation_mention", "work", "edition_or_bibliographic_record"],
        "edge_types": ["relates_to_antecedent", "cites_work", "has_candidate_edition"],
        "work_nodes": work_nodes,
        "mention_nodes": [asdict(mention) for mention in mentions],
        "relation_edges": relation_edges,
        "citation_edges": citation_edges,
        "edition_edges": edition_edges,
    }
    args.graph.parent.mkdir(parents=True, exist_ok=True)
    args.graph.write_text(json.dumps(graph, ensure_ascii=False, indent=2), encoding="utf-8")

    report = {
        "method": "contextual graph reconstruction of ordered footnote citations",
        "source": source.as_posix(),
        "active_documents": ACTIVE_DOCX,
        "excluded_superseded_documents": EXCLUDED_SUPERSEDED_DOCX,
        "abbreviation_source": abbreviation_source.as_posix(),
        "abbreviation_count": len(abbreviations),
        "structured_field_expansions": dict(field_expansions),
        "canonical_bibliography_records": len(canonical),
        "footnotes": len(footnotes),
        "mention_nodes": len(mentions),
        "work_nodes": len(work_nodes),
        "relation_edges": len(relation_edges),
        "citation_edges": len(citation_edges),
        "edition_edges": len(edition_edges),
        "mention_types": dict(type_counts),
        "relation_types": dict(relation_counts),
        "graph_relation_edge_types": dict(graph_relation_edge_types),
        "resolutions": dict(resolution_counts),
        "root_problem_count": len(root_problems),
        "dependent_pending_count": len(dependent),
        "warning_mentions_count": len(warnings),
        "resolved_work_edition_ambiguous_count": resolution_counts.get("resolved_work_edition_ambiguous", 0),
        "resolved_work_edition_missing_count": resolution_counts.get("resolved_work_edition_missing", 0),
        "conceptual_work_nodes": len(registry.family_nodes),
        "new_footnote_only_records": len(registry.extra),
        "institutional_records": len(institutions),
        "merged_unique_records": len(merged),
        "footnote_record_pipeline": dict(registry.extra_stats),
        "validation": validation,
        "editorial_notes": editorial_notes,
        "documents": dict(Counter(footnote.document for footnote in footnotes)),
        "root_problems": [asdict(mention) for mention in root_problems],
        "dependent_pending": [asdict(mention) for mention in dependent],
        "warning_mentions": [asdict(mention) for mention in warnings],
        "relation_examples": {
            relation: [
                asdict(mention) for mention in mentions
                if mention.relation_type == relation
            ][:5]
            for relation in relation_counts
        },
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key not in {
        "root_problems", "dependent_pending", "warning_mentions", "relation_examples"
    }}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
