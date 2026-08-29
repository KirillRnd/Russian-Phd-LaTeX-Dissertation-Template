#!/usr/bin/env python3
"""Audit the canonical BibLaTeX database and write a readable Markdown report.

The parser is deliberately small and preserves the source file.  It understands
the braced/quoted field syntax used by this repository and reports structural
problems without trying to silently repair bibliographic facts.
"""

from __future__ import annotations

import argparse
import collections
import re
import sys
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BIB = ROOT / "biblio" / "korneeva_full.bib"
DEFAULT_REPORT = ROOT / "output" / "bibliography" / "audit.md"

# Short titles, proper names and catalogue identifiers cannot be identified
# reliably from stop words.  These decisions were reviewed against the full
# record (container, place and responsibility statement).
LANGUAGE_OVERRIDES = {
    "korneeva-sources-003": "latin",
    "korneeva-sources-007": "latin",
    "korneeva-sources-021": "latin",
    "korneeva-sources-023": "catalan",
    "korneeva-sources-027": "latin",
    "korneeva-sources-033": "spanish",
    "korneeva-sources-034": "spanish",
    "korneeva-sources-036": "latin",
    "korneeva-sources-038": "english",
    "korneeva-reference-001": "latin",
    "korneeva-research-178": "spanish",
    "korneeva-research-188": "italian",
    "korneeva-research-209": "catalan",
    "korneeva-research-233": "catalan",
    "korneeva-research-259": "french",
    "korneeva-research-326": "spanish",
    "korneeva-research-342": "catalan",
    "korneeva-research-345": "spanish",
    "korneeva-research-350": "spanish",
    "korneeva-research-371": "catalan",
    "korneeva-research-379": "spanish",
    "korneeva-research-380": "french",
    "korneeva-research-382": "spanish",
    "korneeva-research-403": "french",
    "korneeva-research-427": "french",
    "korneeva-research-435": "french",
    "korneeva-footnote-007": "italian",
    "korneeva-footnote-030": "spanish",
    "korneeva-footnote-052": "catalan",
    "korneeva-footnote-060": "spanish",
    "korneeva-footnote-072": "spanish",
    "korneeva-footnote-089": "french",
    "korneeva-footnote-112": "french",
    "korneeva-footnote-123": "catalan",
    "korneeva-footnote-129": "catalan",
    "korneeva-footnote-151": "catalan",
    "korneeva-footnote-160": "catalan",
    "korneeva-institution-001": "french",
    "korneeva-institution-002": "spanish",
    "korneeva-institution-003": "spanish",
    "korneeva-institution-004": "spanish",
    "korneeva-institution-005": "spanish",
    "korneeva-institution-006": "spanish",
    "korneeva-institution-007": "spanish",
    "korneeva-institution-008": "spanish",
    "korneeva-institution-009": "spanish",
    "korneeva-institution-010": "spanish",
    "korneeva-institution-011": "spanish",
    "korneeva-institution-012": "spanish",
    "korneeva-institution-013": "spanish",
    "korneeva-institution-014": "spanish",
    "korneeva-institution-015": "spanish",
    "korneeva-institution-016": "spanish",
    "korneeva-institution-017": "catalan",
    "korneeva-institution-018": "catalan",
    "korneeva-institution-019": "catalan",
    "korneeva-institution-020": "spanish",
    "korneeva-institution-021": "spanish",
    "korneeva-institution-022": "spanish",
}


@dataclass
class Entry:
    entry_type: str
    key: str
    fields: dict[str, str]
    line: int


def _closing(opening: str) -> str:
    return "}" if opening == "{" else ")"


def _scan_balanced(text: str, start: int, opening: str, closing: str) -> int:
    depth = 0
    quoted = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == '"':
            quoted = not quoted
            continue
        if quoted:
            continue
        if char == opening:
            depth += 1
        elif char == closing:
            depth -= 1
            if depth == 0:
                return index
    raise ValueError(f"Unclosed BibTeX block starting at offset {start}")


def _top_level_comma(text: str) -> int:
    brace_depth = 0
    quoted = False
    escaped = False
    for index, char in enumerate(text):
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
        elif char == '"':
            quoted = not quoted
        elif not quoted and char == "{":
            brace_depth += 1
        elif not quoted and char == "}":
            brace_depth -= 1
        elif not quoted and brace_depth == 0 and char == ",":
            return index
    raise ValueError("BibTeX entry has no key separator")


def _parse_fields(body: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    index = 0
    while index < len(body):
        while index < len(body) and (body[index].isspace() or body[index] == ","):
            index += 1
        if index >= len(body):
            break
        match = re.match(r"([A-Za-z][A-Za-z0-9_-]*)\s*=\s*", body[index:])
        if not match:
            raise ValueError(f"Cannot parse field near: {body[index:index + 80]!r}")
        name = match.group(1).lower()
        index += match.end()
        if body[index] == "{":
            end = _scan_balanced(body, index, "{", "}")
            value = body[index + 1 : end]
            index = end + 1
        elif body[index] == '"':
            end = index + 1
            escaped = False
            while end < len(body):
                if body[end] == '"' and not escaped:
                    break
                escaped = body[end] == "\\" and not escaped
                if body[end] != "\\":
                    escaped = False
                end += 1
            value = body[index + 1 : end]
            index = end + 1
        else:
            end = body.find(",", index)
            if end == -1:
                end = len(body)
            value = body[index:end].strip()
            index = end
        fields[name] = re.sub(r"\s+", " ", value).strip()
    return fields


def parse_bibtex(path: Path) -> list[Entry]:
    text = path.read_text(encoding="utf-8")
    entries: list[Entry] = []
    cursor = 0
    marker = re.compile(r"@([A-Za-z]+)\s*([({])")
    while match := marker.search(text, cursor):
        entry_type = match.group(1).lower()
        opening = match.group(2)
        start = match.end() - 1
        end = _scan_balanced(text, start, opening, _closing(opening))
        content = text[start + 1 : end]
        comma = _top_level_comma(content)
        key = content[:comma].strip()
        line = text.count("\n", 0, match.start()) + 1
        entries.append(Entry(entry_type, key, _parse_fields(content[comma + 1 :]), line))
        cursor = end + 1
    return entries


def normalize_title(value: str) -> str:
    value = re.sub(r"\\[A-Za-z]+", "", value)
    return re.sub(r"[^0-9a-zа-яёα-ω]+", "", value.casefold())


def duplicate_signature(entry: Entry) -> tuple[str, ...]:
    """Return a conservative identity signature, not merely a same-title key."""
    fields = entry.fields
    return (
        normalize_title(fields.get("title", "")),
        normalize_title(fields.get("author", "") or fields.get("editor", "")),
        fields.get("date", fields.get("year", "")),
        normalize_title(
            fields.get("journaltitle", "")
            or fields.get("booktitle", "")
            or fields.get("subtitle", "")
        ),
        fields.get("volume", ""),
        fields.get("number", ""),
    )


def category(entry: Entry) -> str:
    return entry.fields.get("keywords", "<нет>")


def infer_language(entry: Entry) -> tuple[str, str]:
    if entry.key in LANGUAGE_OVERRIDES:
        return LANGUAGE_OVERRIDES[entry.key], "reviewed"
    title = entry.fields.get("title", "")
    lowered = f" {title.casefold()} "
    if re.search(r"[а-яё]", lowered):
        return "russian", "high"
    if re.search(r"[α-ωάέήίόύώϊϋΐΰ]", lowered):
        return "greek", "high"
    if re.search(r"[\u0600-\u06ff]", lowered):
        return "arabic", "high"
    if re.search(r"[\u0590-\u05ff]", lowered):
        return "hebrew", "high"

    vocabularies = {
        "catalan": (
            " els ", " les ", " dels ", " dret ", " història ", " edat ",
            " catalunya ", " català ", " catalana ", " lleida ", " tortosa ",
            " usatges ", " costums ", " llengua ", " medievals ", " segle ",
        ),
        "spanish": (
            " los ", " las ", " derecho ", " historia ", " edición ",
            " españa ", " español ", " castellano ", " fueros ", " siglo ",
            " costumbres ", " reino ", " medieval ", " documentos ",
        ),
        "italian": (
            " gli ", " della ", " delle ", " diritto ", " storia ",
            " italiano ", " italia ", " medioevo ", " secolo ", " società ",
        ),
        "french": (
            " les ", " des ", " aux ", " droit ", " histoire ", " siècle ",
            " française ", " médiéval ", " études ", " royaume ", " société ",
        ),
        "german": (
            " der ", " die ", " das ", " und ", " recht ", " geschichte ",
            " zeitschrift ", " mittelalter ", " könig ", " band ", " verlag ",
        ),
        "portuguese": (" português ", " direito ", " história ", " séculos ", " reino de "),
        "latin": (
            " iuris ", " ius ", " liber ", " libri ", " opera ", " ecclesiae ",
            " constitutiones ", " consuetudines ", " codex ", " glossarium ",
            " regni ", " historiae ", " medievalis ", " latinitatis ",
        ),
    }
    scores = {
        language: sum(token in lowered for token in tokens)
        for language, tokens in vocabularies.items()
    }
    winner, score = max(scores.items(), key=lambda item: item[1])
    if score >= 2:
        return winner, "high"
    if score == 1:
        return winner, "medium"
    return "english", "low"


def issues(entry: Entry) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    fields = entry.fields
    if "title" not in fields:
        result.append(("error", "нет title"))
    if "langid" not in fields:
        language, confidence = infer_language(entry)
        result.append(("warning", f"нет langid; кандидат {language} ({confidence})"))
    if "credits" in fields:
        result.append(("error", "поле credits не поддерживается моделью BibLaTeX"))
    if "volume" in fields and not re.fullmatch(
        r"(?:\d+|[IVXLCDM]+)(?:--(?:\d+|[IVXLCDM]+))?", fields["volume"], re.I
    ):
        result.append(("error", f"volume не является номером или диапазоном томов: {fields['volume']}"))
    if entry.entry_type == "online" and "pages" in fields:
        result.append(("error", "pages недопустимо для online"))
    if "url" in fields and "urldate" not in fields:
        result.append(("warning", "у URL нет urldate"))
    if "urldate" in fields and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", fields["urldate"]):
        result.append(("error", f"urldate не в ISO-формате: {fields['urldate']}"))
    if "doi" in fields and re.match(r"(?i)https?://(?:dx\.)?doi\.org/", fields["doi"]):
        result.append(("error", "doi содержит URL-префикс"))
    if "pages" in fields and re.search(r"(?i)(?:^|\s)(?:с|p|pp|s)\.?\s*\d", fields["pages"]):
        result.append(("error", "в pages записано языковое обозначение страниц"))
    # The one-time DOCX migration frequently copied a citation postnote (the
    # exact page cited in the thesis) into ``pages``.  That is not the extent
    # of an article/chapter and therefore is a binary readiness failure.  The
    # small allowlist contains genuinely one-page/one-column source fragments,
    # checked individually rather than inferred from their type.
    single_page_components = {
        "korneeva-curated-panormia",  # one column of Panormia
        "korneeva-footnote-141",     # formula in a medieval glossary
        "korneeva-footnote-153",     # dictionary entry
        "korneeva-footnote-156",     # dictionary entry
    }
    if (
        entry.entry_type in {"article", "incollection", "inproceedings"}
        and entry.key not in single_page_components
        and re.fullmatch(r"\d+", fields.get("pages", "").strip())
    ):
        result.append(("review", "одиночная страница аналитической публикации похожа на постраничную ссылку"))
    if entry.entry_type in {"book", "collection"} and "pages" in fields:
        result.append(("review", "у книги поле pages похоже на постраничную ссылку; объём задаётся pagetotal"))
    review_title = bool(re.match(r"(?i)^\[?(?:рец|рецензия|review)\b", fields.get("title", "")))
    if not review_title and "note" in fields and re.search(
        r"(?i)(?:^|[;/])\s*(?:под ред|отв\. ред|ред\.|пер\.|ed\.|eds\.|edited by|hrsg|hg\.)",
        fields["note"],
    ):
        result.append(("review", "роли редактора/переводчика находятся в note"))
    return result


STRICT_REQUIRED_FIELDS = {
    "book": ("title", "date", "location", "publisher"),
    "collection": ("title", "date", "location", "publisher"),
    "article": ("title", "journaltitle", "date"),
    "incollection": (
        "title", "booktitle", "date", "pages",
        "location", "publisher",
    ),
    "inproceedings": (
        "title", "booktitle", "date", "pages",
        "location", "publisher",
    ),
    "online": ("title", "url", "urldate"),
    "misc": ("title",),
    "thesis": ("author", "title", "type", "institution", "date", "location"),
}


def inherited_field(entry: Entry, name: str, entries_by_key: dict[str, Entry]) -> str | None:
    """Read an explicit field or its value from a reviewed crossref parent."""
    if value := entry.fields.get(name):
        return value
    parent = entries_by_key.get(entry.fields.get("crossref", ""))
    return parent.fields.get(name) if parent else None


def strict_issues(entry: Entry, entries_by_key: dict[str, Entry]) -> list[str]:
    """Return binary readiness failures; one failure makes an entry not ready."""
    result = [message for _severity, message in issues(entry)]
    required = STRICT_REQUIRED_FIELDS.get(entry.entry_type, ("title",))
    for name in required:
        if not inherited_field(entry, name, entries_by_key):
            result.append(f"нет обязательного поля {name}")
    fields = entry.fields
    if entry.entry_type == "article" and not (
        fields.get("volume") or fields.get("number") or fields.get("issueyear")
    ):
        result.append("нет обязательного volume/number")
    if entry.entry_type == "article" and not (
        fields.get("pages") or fields.get("eid") or fields.get("doi") or fields.get("url")
    ):
        result.append("нет страниц или электронного идентификатора статьи")
    if entry.entry_type == "online" and not (fields.get("author") or fields.get("organization")):
        result.append("нет автора или ответственной организации электронного ресурса")
    if entry.entry_type == "misc" and not (fields.get("institution") or fields.get("organization")):
        result.append("нет учреждения архивного хранения")
    return sorted(set(result))


def render_report(entries: list[Entry], source: Path) -> str:
    type_counts = collections.Counter(entry.entry_type for entry in entries)
    category_counts = collections.Counter(category(entry) for entry in entries)
    language_counts = collections.Counter(entry.fields.get("langid", "<нет>") for entry in entries)
    all_issues = [(entry, severity, message) for entry in entries for severity, message in issues(entry)]
    severity_counts = collections.Counter(severity for _, severity, _ in all_issues)
    review_reason_counts = collections.Counter(
        message for _, severity, message in all_issues if severity == "review"
    )
    entries_by_key = {entry.key: entry for entry in entries}
    readiness_failures = {
        entry.key: strict_issues(entry, entries_by_key)
        for entry in entries
        if strict_issues(entry, entries_by_key)
    }
    ready_count = len(entries) - len(readiness_failures)
    readiness_reason_counts = collections.Counter(
        message for messages in readiness_failures.values() for message in messages
    )

    title_groups: dict[tuple[str, ...], list[Entry]] = collections.defaultdict(list)
    for entry in entries:
        signature = duplicate_signature(entry)
        if signature[0]:
            title_groups[signature].append(entry)
    duplicates = [group for group in title_groups.values() if len(group) > 1]

    lines = [
        "# Аудит канонической библиографии",
        "",
        f"Источник: `{source.relative_to(ROOT)}`.",
        f"Всего записей: **{len(entries)}**.",
        "",
        "## Сводка",
        "",
        "### Бинарная готовность",
        "",
        "| Статус | Количество |",
        "|---|---:|",
        f"| Готово | {ready_count} |",
        f"| Не готово | {len(readiness_failures)} |",
        "",
        "### Типы записей",
        "",
        "| Тип | Количество |",
        "|---|---:|",
    ]
    lines.extend(f"| `{name}` | {count} |" for name, count in type_counts.most_common())
    lines.extend(("", "### Категории", "", "| Категория | Количество |", "|---|---:|"))
    lines.extend(f"| `{name}` | {count} |" for name, count in category_counts.most_common())
    lines.extend(("", "### Языковая разметка", "", "| `langid` | Количество |", "|---|---:|"))
    lines.extend(f"| `{name}` | {count} |" for name, count in language_counts.most_common())
    lines.extend(
        (
            "",
            "### Найденные проблемы",
            "",
            "| Уровень | Количество |",
            "|---|---:|",
        )
    )
    lines.extend(f"| {name} | {count} |" for name, count in severity_counts.most_common())
    if review_reason_counts:
        lines.extend(("", "### Причины ручной проверки", "", "| Причина | Количество |", "|---|---:|"))
        lines.extend(f"| {message} | {count} |" for message, count in review_reason_counts.most_common())
    if readiness_reason_counts:
        lines.extend(("", "### Причины неготовности", "", "| Причина | Количество |", "|---|---:|"))
        lines.extend(f"| {message} | {count} |" for message, count in readiness_reason_counts.most_common())
    lines.extend(("", f"Групп с совпадающей сигнатурой издания: **{len(duplicates)}**.", ""))

    if duplicates:
        lines.extend(("## Возможные дубли", ""))
        for group in duplicates:
            title = group[0].fields.get("title", "")
            keys = ", ".join(f"`{entry.key}`" for entry in group)
            lines.append(f"- {keys}: {title}")
        lines.append("")

    lines.extend(("## Детализация", ""))
    for severity in ("error", "warning", "review"):
        selected = [(entry, message) for entry, level, message in all_issues if level == severity]
        lines.extend((f"### {severity.upper()} — {len(selected)}", ""))
        if not selected:
            lines.extend(("Нет.", ""))
            continue
        for entry, message in selected:
            title = entry.fields.get("title", "<без заглавия>")
            lines.append(f"- `{entry.key}` (строка {entry.line}): {message}. — {title}")
        lines.append("")
    lines.extend((f"## НЕ ГОТОВО — {len(readiness_failures)}", ""))
    if not readiness_failures:
        lines.extend(("Нет.", ""))
    else:
        for entry in entries:
            if entry.key not in readiness_failures:
                continue
            reasons = "; ".join(readiness_failures[entry.key])
            title = entry.fields.get("title", "<без заглавия>")
            lines.append(f"- `{entry.key}` (строка {entry.line}): {reasons}. — {title}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("bib", nargs="?", type=Path, default=DEFAULT_BIB)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--fail-on-error", action="store_true")
    parser.add_argument("--fail-on-not-ready", action="store_true")
    args = parser.parse_args()
    source = args.bib if args.bib.is_absolute() else ROOT / args.bib
    report = args.report if args.report.is_absolute() else ROOT / args.report
    entries = parse_bibtex(source)
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render_report(entries, source), encoding="utf-8")
    print(f"Bibliography audit: {len(entries)} entries -> {report.relative_to(ROOT)}")
    if args.fail_on_error and any(severity == "error" for entry in entries for severity, _ in issues(entry)):
        sys.exit(1)
    if args.fail_on_not_ready:
        entries_by_key = {entry.key: entry for entry in entries}
        if any(strict_issues(entry, entries_by_key) for entry in entries):
            sys.exit(2)


if __name__ == "__main__":
    main()
