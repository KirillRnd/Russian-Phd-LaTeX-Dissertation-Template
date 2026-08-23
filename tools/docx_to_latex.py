#!/usr/bin/env python3
"""Convert the canonical dissertation DOCX files to maintainable LaTeX.

The converter is intentionally conservative: it preserves source wording and
footnotes, normalises only document structure, and records conversion counts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import zipfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from lxml import etree


W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
PR = "http://schemas.openxmlformats.org/package/2006/relationships"
NS = {"w": W, "r": R, "a": A, "wp": WP, "pr": PR}
WVAL = f"{{{W}}}val"
RID = f"{{{R}}}id"
REMBED = f"{{{R}}}embed"


def normalise_text(text: str) -> str:
    return (
        text.replace("\u00ad", "")
        .replace("\u200b", "")
        .replace("\r", "")
        .replace("\u2011", "-")
    )


def escape_plain(text: str) -> str:
    text = normalise_text(text)
    replacements = {
        "\\": r"\textbackslash{}",
        "{": r"\{",
        "}": r"\}",
        "$": r"\$",
        "&": r"\&",
        "#": r"\#",
        "%": r"\%",
        "_": r"\_",
        "^": r"\textasciicircum{}",
        "~": r"\textasciitilde{}",
        "\u00a0": "~",
        "\u202f": "~",
        "\u2013": "--",
        "\u2014": "---",
        "\u2192": r"$\rightarrow$",
        "\u2190": r"$\leftarrow$",
        "\u2264": r"$\leq$",
        "\u2265": r"$\geq$",
        "\u00b1": r"$\pm$",
        "\u00d7": r"$\times$",
    }
    return "".join(replacements.get(char, char) for char in text)


URL_RE = re.compile(r"https?://[^\s<>()]+", re.I)


def escape_text(text: str) -> str:
    chunks: list[str] = []
    cursor = 0
    for match in URL_RE.finditer(text):
        chunks.append(escape_plain(text[cursor : match.start()]))
        url = match.group(0)
        trailing = ""
        while url and url[-1] in ".,;:":
            trailing = url[-1] + trailing
            url = url[:-1]
        chunks.append(r"\url{" + url.replace("%", r"\%") + "}")
        chunks.append(escape_plain(trailing))
        cursor = match.end()
    chunks.append(escape_plain(text[cursor:]))
    return "".join(chunks)


def xml_part(archive: zipfile.ZipFile, name: str) -> etree._Element | None:
    try:
        return etree.fromstring(archive.read(name))
    except KeyError:
        return None


def relationship_map(archive: zipfile.ZipFile, name: str) -> dict[str, str]:
    root = xml_part(archive, name)
    if root is None:
        return {}
    result: dict[str, str] = {}
    for rel in root.xpath("//*[local-name()='Relationship']"):
        result[rel.get("Id", "")] = rel.get("Target", "")
    return result


def style_map(archive: zipfile.ZipFile) -> dict[str, str]:
    root = xml_part(archive, "word/styles.xml")
    if root is None:
        return {}
    result: dict[str, str] = {}
    for style in root.xpath("//w:style", namespaces=NS):
        style_id = style.get(f"{{{W}}}styleId", "")
        name = style.find("w:name", namespaces=NS)
        result[style_id] = name.get(WVAL, style_id) if name is not None else style_id
    return result


def node_text(node: etree._Element) -> str:
    parts: list[str] = []
    for item in node.xpath(".//w:t | .//w:tab | .//w:br | .//w:cr", namespaces=NS):
        if item.tag == f"{{{W}}}t":
            parts.append(item.text or "")
        elif item.tag == f"{{{W}}}tab":
            parts.append("\t")
        else:
            parts.append("\n")
    return normalise_text("".join(parts)).strip()


def safe_bool(element: etree._Element | None) -> bool:
    if element is None:
        return False
    return element.get(WVAL, "1") not in {"0", "false", "off"}


@dataclass
class ImageRef:
    source: str
    output: str
    alt: str


class DocxConverter:
    def __init__(self, source: Path, image_dir: Path, image_tex_prefix: str):
        self.source = source
        self.archive = zipfile.ZipFile(source)
        self.document = xml_part(self.archive, "word/document.xml")
        if self.document is None:
            raise ValueError(f"Missing document.xml: {source}")
        self.relationships = relationship_map(
            self.archive, "word/_rels/document.xml.rels"
        )
        self.styles = style_map(self.archive)
        self.image_dir = image_dir
        self.image_tex_prefix = image_tex_prefix.rstrip("/")
        self.image_counter = 0
        self.images: list[ImageRef] = []
        self.footnotes = self._load_footnotes()
        self.stats: Counter[str] = Counter()

    def close(self) -> None:
        self.archive.close()

    def _load_footnotes(self) -> dict[str, etree._Element]:
        root = xml_part(self.archive, "word/footnotes.xml")
        if root is None:
            return {}
        result: dict[str, etree._Element] = {}
        for note in root.xpath("//w:footnote", namespaces=NS):
            note_id = note.get(f"{{{W}}}id", "")
            if note_id and int(note_id) >= 0:
                result[note_id] = note
        return result

    def _extract_image(self, drawing: etree._Element) -> str:
        blip = drawing.find(".//a:blip", namespaces=NS)
        if blip is None:
            return ""
        rel_id = blip.get(REMBED, "")
        target = self.relationships.get(rel_id, "")
        if not target:
            return ""
        archive_name = str(PurePosixPath("word") / PurePosixPath(target))
        archive_name = str(PurePosixPath(archive_name))
        try:
            payload = self.archive.read(archive_name)
        except KeyError:
            return ""
        self.image_counter += 1
        extension = PurePosixPath(target).suffix.lower() or ".bin"
        chapter_match = re.match(r"ГЛАВА_(\d+)", self.source.stem, re.I)
        stem = f"chapter{chapter_match.group(1)}" if chapter_match else "source"
        output_name = f"{stem}_{self.image_counter:02d}{extension}"
        output_path = self.image_dir / output_name
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(payload)
        doc_pr = drawing.find(".//wp:docPr", namespaces=NS)
        alt = ""
        if doc_pr is not None:
            alt = doc_pr.get("descr") or doc_pr.get("title") or ""
        self.images.append(ImageRef(archive_name, output_name, alt))
        self.stats["images"] += 1
        return (
            "\n\\begin{figure}[htbp]\n"
            "\\centering\n"
            f"\\includegraphics[width=0.95\\textwidth]{{{self.image_tex_prefix}/{output_name}}}\n"
            f"\\caption{{{escape_text(alt) if alt else 'Иллюстрация из исходного документа'}}}\n"
            f"\\label{{fig:{stem}-{self.image_counter:02d}}}\n"
            "\\end{figure}\n"
        )

    def _footnote_latex(self, note_id: str) -> str:
        note = self.footnotes.get(note_id)
        if note is None:
            return r"\footnote{[Текст сноски отсутствует в исходном DOCX.]}"
        paragraphs: list[str] = []
        for paragraph in note.findall("w:p", namespaces=NS):
            value = self.paragraph_inline(paragraph, allow_footnote=False).strip()
            value = re.sub(r"^\s*\d+\s*", "", value)
            if value:
                paragraphs.append(value)
        self.stats["footnotes"] += 1
        return r"\footnote{" + r"\par ".join(paragraphs) + "}"

    def _run_latex(self, run: etree._Element, allow_footnote: bool) -> str:
        chunks: list[str] = []
        for child in run:
            if child.tag == f"{{{W}}}t":
                chunks.append(escape_text(child.text or ""))
            elif child.tag == f"{{{W}}}tab":
                chunks.append(r"\quad{}")
            elif child.tag in {f"{{{W}}}br", f"{{{W}}}cr"}:
                chunks.append(r"\\{}")
            elif child.tag == f"{{{W}}}noBreakHyphen":
                chunks.append("-")
            elif child.tag == f"{{{W}}}softHyphen":
                continue
            elif child.tag == f"{{{W}}}footnoteReference" and allow_footnote:
                chunks.append(self._footnote_latex(child.get(f"{{{W}}}id", "")))
            elif child.tag == f"{{{W}}}drawing":
                chunks.append(self._extract_image(child))
        value = "".join(chunks)
        if not value:
            return ""
        props = run.find("w:rPr", namespaces=NS)
        if props is None or value.startswith("\n\\begin{figure}"):
            return value
        if r"\footnote{" not in value and safe_bool(props.find("w:vertAlign[@w:val='superscript']", namespaces=NS)):
            value = r"\textsuperscript{" + value + "}"
        elif safe_bool(props.find("w:vertAlign[@w:val='subscript']", namespaces=NS)):
            value = r"\textsubscript{" + value + "}"
        if safe_bool(props.find("w:smallCaps", namespaces=NS)):
            value = r"\textsc{" + value + "}"
        if safe_bool(props.find("w:i", namespaces=NS)):
            value = r"\emph{" + value + "}"
        if safe_bool(props.find("w:b", namespaces=NS)):
            value = r"\textbf{" + value + "}"
        return value

    def _inline_children(self, parent: etree._Element, allow_footnote: bool) -> str:
        chunks: list[str] = []
        for child in parent:
            if child.tag == f"{{{W}}}r":
                chunks.append(self._run_latex(child, allow_footnote))
            elif child.tag == f"{{{W}}}hyperlink":
                label = self._inline_children(child, allow_footnote)
                target = self.relationships.get(child.get(RID, ""), "")
                if r"\url{" in label or not re.match(r"^https?://", target, re.I):
                    chunks.append(label)
                else:
                    safe_target = target.replace("%", r"\%").replace("#", r"\#")
                    chunks.append(r"\href{" + safe_target + "}{" + label + "}")
            elif child.tag in {f"{{{W}}}smartTag", f"{{{W}}}sdt", f"{{{W}}}ins"}:
                chunks.append(self._inline_children(child, allow_footnote))
            elif child.tag == f"{{{W}}}fldSimple":
                chunks.append(self._inline_children(child, allow_footnote))
            elif child.tag == f"{{{W}}}del":
                continue
        return "".join(chunks)

    def paragraph_inline(self, paragraph: etree._Element, allow_footnote: bool = True) -> str:
        return self._inline_children(paragraph, allow_footnote)

    def paragraph_style(self, paragraph: etree._Element) -> str:
        style = paragraph.find("w:pPr/w:pStyle", namespaces=NS)
        style_id = style.get(WVAL, "Normal") if style is not None else "Normal"
        return self.styles.get(style_id, style_id)

    def table_latex(self, table: etree._Element) -> str:
        rows = table.findall("w:tr", namespaces=NS)
        if not rows:
            return ""
        parsed_rows: list[list[str]] = []
        column_count = 1
        for row in rows:
            cells: list[str] = []
            for cell in row.findall("w:tc", namespaces=NS):
                paragraphs = []
                for paragraph in cell.findall("w:p", namespaces=NS):
                    value = self.paragraph_inline(paragraph).strip()
                    if value:
                        paragraphs.append(value)
                cells.append(r"\par ".join(paragraphs))
            column_count = max(column_count, len(cells))
            parsed_rows.append(cells)
        spec = "|" + "|".join(
            [r"p{\dimexpr0.94\textwidth/" + str(column_count) + r"\relax}"]
            * column_count
        ) + "|"
        lines = [r"\begin{center}", r"\small", f"\\begin{{longtable}}{{{spec}}}", r"\hline"]
        for cells in parsed_rows:
            cells = cells + [""] * (column_count - len(cells))
            lines.append(" & ".join(cells) + r" \\ \hline")
        lines += [r"\end{longtable}", r"\end{center}"]
        self.stats["tables"] += 1
        return "\n".join(lines)

    def body_elements(self) -> list[etree._Element]:
        body = self.document.find("w:body", namespaces=NS)
        if body is None:
            return []
        return [child for child in body if child.tag in {f"{{{W}}}p", f"{{{W}}}tbl"}]


SECTION_RE = re.compile(r"^§\s*(\d+(?:\.\d+){0,3})\.?\s*(.*)$", re.S)
CHAPTER_RE = re.compile(r"^Глава\s+\d+\.?\s*(.*)$", re.I | re.S)


def cleaned_heading(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().rstrip(".")


def heading_latex(text: str, style: str, mode: str) -> str | None:
    raw = cleaned_heading(text)
    chapter = CHAPTER_RE.match(raw)
    if mode == "chapter" and chapter:
        return r"\chapter{" + escape_text(chapter.group(1)) + "}"
    if re.match(r"^Выводы\s+к\s+главе", raw, re.I):
        title = escape_text(raw)
        return r"\section*{" + title + "}\n" + r"\addcontentsline{toc}{section}{" + title + "}"
    section = SECTION_RE.match(raw)
    if section:
        number, title = section.groups()
        title = title.strip()
        depth = len(number.split("."))
        if mode == "chapter":
            command = {2: "section", 3: "subsection", 4: "subsubsection"}.get(depth)
            if command:
                return f"\\{command}{{{escape_text(title)}}}"
        else:
            command = {1: "subsection", 2: "subsubsection", 3: "paragraph"}.get(depth, "paragraph")
            display = escape_text("§" + number + ". " + title)
            if command == "paragraph":
                return r"\paragraph*{" + display + "}"
            return (
                f"\\{command}*{{{display}}}\n"
                f"\\addcontentsline{{toc}}{{{command}}}{{{display}}}"
            )
    if re.search(r"heading\s*1|заголовок\s*1", style, re.I) and mode == "front":
        title = escape_text(raw)
        return r"\section*{" + title + "}\n" + r"\addcontentsline{toc}{section}{" + title + "}"
    if re.search(r"heading\s*2|заголовок\s*2", style, re.I):
        command = "section" if mode == "chapter" else "subsection"
        return f"\\{command}{{{escape_text(raw)}}}" if mode == "chapter" else f"\\{command}*{{{escape_text(raw)}}}"
    if re.search(r"heading\s*3|заголовок\s*3", style, re.I):
        command = "subsection" if mode == "chapter" else "subsubsection"
        return f"\\{command}{{{escape_text(raw)}}}" if mode == "chapter" else f"\\{command}*{{{escape_text(raw)}}}"
    return None


def markdown_inline(text: str) -> str:
    def render_code(value: str) -> str:
        parts = re.split(r"(`[^`]+`)", value)
        return "".join(
            r"\texttt{" + escape_text(part[1:-1]) + "}"
            if len(part) >= 2 and part.startswith("`") and part.endswith("`")
            else escape_text(part)
            for part in parts
        )

    match = re.match(r"^\*\*(.+?)\*\*\s*(.*)$", text, re.S)
    if match:
        return r"\textbf{" + escape_text(match.group(1)) + "} " + render_code(match.group(2))
    return render_code(text)


def convert_standard(converter: DocxConverter, mode: str) -> str:
    lines: list[str] = ["% Автоматически перенесено из " + converter.source.name, ""]
    first_nonempty = True
    in_list = False
    for element in converter.body_elements():
        if element.tag == f"{{{W}}}tbl":
            if in_list:
                lines.append(r"\end{itemize}")
                in_list = False
            lines += [converter.table_latex(element), ""]
            continue
        plain = node_text(element)
        inline = converter.paragraph_inline(element).strip()
        if not plain and not inline:
            continue
        if element.xpath(".//w:drawing", namespaces=NS) and re.match(r"^Рис\.\s*\d+\.", plain):
            caption = re.sub(r"^Рис\.\s*\d+\.\s*", "", plain).strip().rstrip(".")
            inline = inline.replace(
                r"\caption{Иллюстрация из исходного документа}",
                r"\caption{" + escape_text(caption) + "}",
            )
            inline = re.sub(r"(\\end\{figure\}\n).*", r"\1", inline, flags=re.S).strip()
        style = converter.paragraph_style(element)
        heading = heading_latex(plain, style, mode)
        if mode == "front" and first_nonempty and heading is None:
            title = escape_text(cleaned_heading(plain))
            heading = r"\section*{" + title + "}\n" + r"\addcontentsline{toc}{section}{" + title + "}"
        first_nonempty = False
        if heading:
            if in_list:
                lines.append(r"\end{itemize}")
                in_list = False
            lines += [heading, ""]
            converter.stats["headings"] += 1
            continue
        list_match = re.match(r"^\s*[-–—•]\s+(.*)$", plain, re.S)
        if list_match:
            if not in_list:
                lines.append(r"\begin{itemize}")
                in_list = True
            # Preserve inline formatting when possible, removing only the marker.
            inline_item = re.sub(r"^\s*[-–—•]\s+", "", inline, count=1)
            lines.append(r"\item " + inline_item)
            continue
        if in_list:
            lines.append(r"\end{itemize}")
            in_list = False
        lines += [inline, ""]
        converter.stats["paragraphs"] += 1
    if in_list:
        lines.append(r"\end{itemize}")
    result = "\n".join(lines).rstrip() + "\n"
    if mode == "chapter":
        header_end = result.find("\n\n") + 2
        chapter = re.search(r"\\chapter\{.*?\}\n", result[header_end:], flags=re.S)
        if chapter and chapter.start() > 0:
            start = header_end + chapter.start()
            end = header_end + chapter.end()
            result = result[:header_end] + result[start:end] + "\n" + result[header_end:start] + result[end:]
    return result


def convert_appendix(converter: DocxConverter) -> str:
    lines = ["% Автоматически перенесено из " + converter.source.name, ""]
    in_code = False
    first = True
    for element in converter.body_elements():
        if element.tag == f"{{{W}}}tbl":
            lines += [converter.table_latex(element), ""]
            continue
        plain = node_text(element)
        if not plain:
            continue
        if first:
            first = False
            continue
        if plain.startswith("```"):
            if in_code:
                lines += [r"\end{lstlisting}", ""]
            else:
                language = plain[3:].strip()
                option = ""
                if language.lower() == "json":
                    option = ",language={}"  # JSON is kept verbatim without a fragile custom lexer.
                lines.append(r"\begin{lstlisting}[breaklines=true,basicstyle=\ttfamily\small" + option + "]")
            in_code = not in_code
            continue
        if in_code:
            lines.append(normalise_text(plain))
            continue
        heading = re.match(r"^(#{1,4})\s+(.*)$", plain, re.S)
        if heading:
            level = len(heading.group(1))
            title = escape_text(cleaned_heading(heading.group(2)))
            command = {1: "section", 2: "subsection", 3: "subsubsection", 4: "paragraph"}[level]
            lines += [f"\\{command}{{{title}}}", ""]
            converter.stats["headings"] += 1
        else:
            lines += [markdown_inline(plain), ""]
            converter.stats["paragraphs"] += 1
    if in_code:
        lines.append(r"\end{lstlisting}")
    return "\n".join(lines).rstrip() + "\n"


BIB_GROUPS = {
    "Справочная литература": "reference",
    "Электронные ресурсы и программное обеспечение": "software",
    "Исследовательская литература": "research",
}


def bibliography_entries(source: Path) -> tuple[list[dict[str, str]], list[str]]:
    with zipfile.ZipFile(source) as archive:
        document = xml_part(archive, "word/document.xml")
        if document is None:
            raise ValueError("Missing bibliography document.xml")
        texts = [node_text(p) for p in document.xpath("//w:body/w:p", namespaces=NS)]
    texts = [t for t in texts if t]
    entries: list[dict[str, str]] = []
    notes: list[str] = []
    group = "sources"
    source_instruction_seen = False
    for text in texts:
        if text == "Библиография":
            continue
        if text in BIB_GROUPS:
            group = BIB_GROUPS[text]
            continue
        if text.startswith("Издания исторических источников"):
            notes.append(text)
            source_instruction_seen = True
            continue
        text = re.sub(r"^\s*\d+\.\s*", "", text).strip()
        if not text:
            continue
        key = f"korneeva-{group}-{sum(1 for e in entries if e['group'] == group) + 1:03d}"
        entries.append({"key": key, "group": group, "text": text})
    if not source_instruction_seen:
        notes.append("Порядок источников сохранён по исходному документу.")
    return entries, notes


def bib_escape(text: str) -> str:
    return (
        normalise_text(text)
        .replace("\\", r"\textbackslash{}")
        .replace("{", r"\{")
        .replace("}", r"\}")
        .replace("%", r"\%")
        .replace("&", r"\&")
        .replace("#", r"\#")
        .replace("_", r"\_")
        .replace("\u00a0", " ")
        .replace("\u202f", " ")
    )


def write_bibliography(source: Path, output: Path, report_output: Path) -> dict[str, object]:
    entries, notes = bibliography_entries(source)
    lines = ["% Полные записи перенесены из СПИСОК_ЛИТЕРАТУРЫ.docx.", "% Поле title намеренно хранит исходную запись без библиографического домысливания.", ""]
    for entry in entries:
        lines += [
            f"@MISC{{{entry['key']},",
            f"  title    = {{{{{bib_escape(entry['text'])}}}}},",
            f"  keywords = {{{entry['group']}}},",
            "  language = {russian},",
            "}",
            "",
        ]
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines), encoding="utf-8")
    groups = Counter(entry["group"] for entry in entries)
    report = {
        "source": source.as_posix(),
        "entries": len(entries),
        "groups": dict(groups),
        "editorial_notes": notes,
        "method": "verbatim records in BibLaTeX misc entries",
    }
    report_output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--images", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()

    source = args.source.resolve()
    output = args.output.resolve()
    image_dir = args.images.resolve()
    output.mkdir(parents=True, exist_ok=True)
    image_dir.mkdir(parents=True, exist_ok=True)

    jobs = [
        ("КОНТЕКСТ_ВЕРСИЯ_3.docx", "introduction_context.tex", "front"),
        ("ИСТОРИОГРАФИЯ_ВЕРСИЯ_3.docx", "introduction_historiography.tex", "front"),
        ("ИСТОЧНИК_ВЕРСИЯ_3.docx", "introduction_sources.tex", "front"),
        ("ГЛАВА_1_ВЕРСИЯ_3.docx", "chapter1.tex", "chapter"),
        ("ГЛАВА_2_ВЕРСИЯ_3.docx", "chapter2.tex", "chapter"),
        ("ГЛАВА_3_ВЕРСИЯ_3.docx", "chapter3.tex", "chapter"),
        ("ПРИЛОЖЕНИЕ 3.docx", "appendix_computational_report.tex", "appendix"),
    ]
    report: dict[str, object] = {"source": source.as_posix(), "documents": []}
    for docx_name, tex_name, mode in jobs:
        converter = DocxConverter(source / docx_name, image_dir, "Dissertation/images/korneeva")
        try:
            latex = convert_appendix(converter) if mode == "appendix" else convert_standard(converter, mode)
            (output / tex_name).write_text(latex, encoding="utf-8")
            report["documents"].append(
                {
                    "source": docx_name,
                    "output": tex_name,
                    "sha256": hashlib.sha256((source / docx_name).read_bytes()).hexdigest(),
                    "stats": dict(converter.stats),
                    "images": [image.__dict__ for image in converter.images],
                }
            )
        finally:
            converter.close()

    bibliography_report = write_bibliography(
        source / "СПИСОК_ЛИТЕРАТУРЫ.docx",
        Path("biblio/korneeva.bib").resolve(),
        Path("migration/bibliography_report.json").resolve(),
    )
    report["bibliography"] = bibliography_report
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
