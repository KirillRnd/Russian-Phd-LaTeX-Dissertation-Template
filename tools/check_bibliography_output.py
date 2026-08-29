#!/usr/bin/env python3
"""Regression checks for the readable bibliography HTML."""

from __future__ import annotations

import re
from pathlib import Path

from audit_bibliography import DEFAULT_BIB, parse_bibtex


ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "output" / "bibliography" / "bibliography-preview.html"


def main() -> None:
    if not HTML.is_file():
        raise SystemExit(f"Нет результата сборки: {HTML}")
    text = HTML.read_text(encoding="utf-8")
    entries = parse_bibtex(DEFAULT_BIB)
    rendered_keys = set(re.findall(r"id=['\"]X0-([^'\"]+)['\"]", text))
    missing = [entry.key for entry in entries if entry.key not in rendered_keys]
    if missing:
        raise SystemExit(f"В HTML отсутствуют {len(missing)} записей: {', '.join(missing[:10])}")

    required_fragments = (
        "Вестготская",
        "Código de las costumbres",
        "edició crítica",
        "Über",
        "Österreichische",
        "L’écriture comme prisme",
        "https://www.enciclopedia.cat/gran-enciclopedia-catalana/catarisme",
    )
    absent = [fragment for fragment in required_fragments if fragment not in text]
    if absent:
        raise SystemExit(f"Потеряны регрессионные фрагменты: {absent}")
    for marker in ("�", "C´odigo", "edici´o", "Fundaci´o"):
        if marker in text:
            raise SystemExit(f"Обнаружен дефект Unicode: {marker!r}")
    print(f"Bibliography HTML check: {len(entries)} entries, Unicode and URLs OK")


if __name__ == "__main__":
    main()
