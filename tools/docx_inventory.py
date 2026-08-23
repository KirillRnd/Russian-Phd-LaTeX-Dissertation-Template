#!/usr/bin/env python3
"""Build a structural inventory for the canonical DOCX dissertation sources."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from lxml import etree


W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS = {"w": W, "r": R}
WVAL = f"{{{W}}}val"


def xml_part(archive: zipfile.ZipFile, name: str) -> etree._Element | None:
    try:
        return etree.fromstring(archive.read(name))
    except KeyError:
        return None


def paragraph_text(paragraph: etree._Element) -> str:
    chunks: list[str] = []
    for node in paragraph.xpath(".//w:t | .//w:tab | .//w:br", namespaces=NS):
        if node.tag == f"{{{W}}}t":
            chunks.append(node.text or "")
        elif node.tag == f"{{{W}}}tab":
            chunks.append("\t")
        else:
            chunks.append("\n")
    return "".join(chunks).strip()


def style_names(styles_root: etree._Element | None) -> dict[str, str]:
    result: dict[str, str] = {}
    if styles_root is None:
        return result
    for style in styles_root.xpath("//w:style", namespaces=NS):
        style_id = style.get(f"{{{W}}}styleId", "")
        name = style.find("w:name", namespaces=NS)
        result[style_id] = name.get(WVAL, style_id) if name is not None else style_id
    return result


def likely_heading(text: str, style: str) -> bool:
    if not text or len(text) > 260:
        return False
    if re.search(r"heading|заголов", style, flags=re.I):
        return True
    return bool(
        re.match(r"^(глава|приложение|историограф|источников|библиограф)", text, re.I)
        or re.match(r"^§\s*\d", text)
        or re.match(r"^\d+(?:\.\d+){1,3}\.?\s+\D", text)
    )


def count_notes(root: etree._Element | None, tag: str) -> tuple[int, int]:
    if root is None:
        return 0, 0
    nodes = root.xpath(f"//w:{tag}", namespaces=NS)
    real = [n for n in nodes if int(n.get(f"{{{W}}}id", "0")) >= 0]
    words = sum(len(paragraph_text(n).split()) for n in real)
    return len(real), words


def inspect_docx(path: Path, root: Path) -> dict[str, object]:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    with zipfile.ZipFile(path) as archive:
        document = xml_part(archive, "word/document.xml")
        if document is None:
            raise ValueError(f"No word/document.xml in {path}")
        styles = style_names(xml_part(archive, "word/styles.xml"))
        paragraphs = document.xpath("//w:body//w:p", namespaces=NS)
        texts = [paragraph_text(p) for p in paragraphs]
        nonempty = [t for t in texts if t]
        style_counter: Counter[str] = Counter()
        headings: list[dict[str, str]] = []
        for paragraph, text in zip(paragraphs, texts):
            style_node = paragraph.find("w:pPr/w:pStyle", namespaces=NS)
            style_id = style_node.get(WVAL, "Normal") if style_node is not None else "Normal"
            style = styles.get(style_id, style_id)
            style_counter[style] += 1
            if likely_heading(text, style):
                headings.append({"style": style, "text": text})

        footnotes, footnote_words = count_notes(xml_part(archive, "word/footnotes.xml"), "footnote")
        endnotes, endnote_words = count_notes(xml_part(archive, "word/endnotes.xml"), "endnote")
        comments_root = xml_part(archive, "word/comments.xml")
        comments = len(comments_root.xpath("//w:comment", namespaces=NS)) if comments_root is not None else 0

        tables = document.xpath("//w:tbl", namespaces=NS)
        table_cells = document.xpath("//w:tc", namespaces=NS)
        media = [n for n in archive.namelist() if n.startswith("word/media/") and not n.endswith("/")]
        charts = [n for n in archive.namelist() if n.startswith("word/charts/") and n.endswith(".xml")]
        equations = len(document.xpath("//*[local-name()='oMath' or local-name()='oMathPara']"))
        hyperlinks = len(document.xpath("//w:hyperlink", namespaces=NS))
        insertions = len(document.xpath("//w:ins", namespaces=NS))
        deletions = len(document.xpath("//w:del", namespaces=NS))
        sections = len(document.xpath("//w:sectPr", namespaces=NS))

        return {
            "file": path.relative_to(root).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": digest,
            "paragraphs": len(paragraphs),
            "nonempty_paragraphs": len(nonempty),
            "words_approx": sum(len(t.split()) for t in nonempty),
            "styles": dict(style_counter.most_common()),
            "headings": headings,
            "tables": len(tables),
            "table_cells": len(table_cells),
            "media": media,
            "charts": len(charts),
            "equations": equations,
            "footnotes": footnotes,
            "footnote_words_approx": footnote_words,
            "endnotes": endnotes,
            "endnote_words_approx": endnote_words,
            "comments": comments,
            "tracked_insertions": insertions,
            "tracked_deletions": deletions,
            "hyperlinks": hyperlinks,
            "sections": sections,
            "first_paragraphs": nonempty[:5],
        }


def markdown_report(payload: dict[str, object]) -> str:
    docs = payload["documents"]
    lines = [
        "# Реестр канонических DOCX версии 3",
        "",
        "Реестр сформирован автоматически без изменения исходных документов.",
        "",
        "| Файл | Абзацы | Слова (оценка) | Таблицы | Медиа | Сноски | Комментарии | Правки |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for doc in docs:
        edits = int(doc["tracked_insertions"]) + int(doc["tracked_deletions"])
        lines.append(
            f"| `{Path(doc['file']).name}` | {doc['nonempty_paragraphs']} | {doc['words_approx']} | "
            f"{doc['tables']} | {len(doc['media'])} | {doc['footnotes']} | {doc['comments']} | {edits} |"
        )
    lines += ["", "## Предполагаемая иерархия заголовков", ""]
    for doc in docs:
        lines.append(f"### {Path(doc['file']).name}")
        lines.append("")
        if doc["headings"]:
            for item in doc["headings"]:
                lines.append(f"- `{item['style']}` — {item['text']}")
        else:
            lines.append("- Явные заголовки стилями Word не обнаружены.")
        lines.append("")
    lines += [
        "## Ограничения автоматического реестра",
        "",
        "- Количество слов является оценкой по текстовым узлам OOXML.",
        "- Заголовки определены по стилям Word и типовым текстовым шаблонам; итоговая иерархия проверяется при переносе.",
        "- Наличие медиа не означает, что каждый объект является самостоятельной иллюстрацией: возможны служебные изображения.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("--json", type=Path, required=True)
    parser.add_argument("--markdown", type=Path, required=True)
    args = parser.parse_args()

    source = args.source.resolve()
    documents = [inspect_docx(path, source) for path in sorted(source.glob("*.docx"))]
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": source.as_posix(),
        "documents": documents,
    }
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.markdown.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    args.markdown.write_text(markdown_report(payload), encoding="utf-8")


if __name__ == "__main__":
    main()
