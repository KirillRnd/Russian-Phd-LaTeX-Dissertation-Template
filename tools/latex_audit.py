#!/usr/bin/env python3
"""Lightweight structural audit for the migrated LaTeX dissertation."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path


INCLUDE_RE = re.compile(r"\\(?:input|include)\{([^}]+)\}")
BEGIN_RE = re.compile(r"\\begin\{([^}]+)\}")
END_RE = re.compile(r"\\end\{([^}]+)\}")
ADD_BIB_RE = re.compile(r"\\addbibresource(?:\[[^]]*\])?\{([^}]+)\}")


def strip_comments(line: str) -> str:
    for index, char in enumerate(line):
        if char == "%" and (index == 0 or line[index - 1] != "\\"):
            return line[:index]
    return line


def resolve_include(root: Path, value: str) -> Path | None:
    candidates = [root / value, root / f"{value}.tex"]
    return next((candidate for candidate in candidates if candidate.is_file()), None)


def active_files(root: Path, entrypoint: Path) -> tuple[list[Path], list[str]]:
    seen: set[Path] = set()
    missing: list[str] = []

    def visit(path: Path) -> None:
        path = path.resolve()
        if path in seen:
            return
        seen.add(path)
        text = path.read_text(encoding="utf-8")
        for value in INCLUDE_RE.findall(text):
            included = resolve_include(root, value)
            if included:
                visit(included)
            else:
                missing.append(f"{path.relative_to(root)} -> {value}")

    visit(entrypoint)
    return sorted(seen), missing


def audit_file(path: Path) -> list[str]:
    issues: list[str] = []
    stack: list[tuple[str, int]] = []
    brace_balance = 0
    in_literal: str | None = None
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = strip_comments(raw)
        if in_literal:
            if f"\\end{{{in_literal}}}" in line:
                if stack and stack[-1][0] == in_literal:
                    stack.pop()
                in_literal = None
            continue
        for env in BEGIN_RE.findall(line):
            stack.append((env, line_number))
            if env in {"lstlisting", "verbatim", "Verbatim"}:
                in_literal = env
        for env in END_RE.findall(line):
            if not stack:
                issues.append(f"{path}:{line_number}: лишний \\end{{{env}}}")
            else:
                opened, opened_line = stack.pop()
                if opened != env:
                    issues.append(
                        f"{path}:{line_number}: закрыт {env}, ожидался {opened} с строки {opened_line}"
                    )
        escaped = False
        for char in line:
            if char == "\\":
                escaped = not escaped
                continue
            if char == "{" and not escaped:
                brace_balance += 1
            elif char == "}" and not escaped:
                brace_balance -= 1
                if brace_balance < 0:
                    issues.append(f"{path}:{line_number}: лишняя закрывающая фигурная скобка")
                    brace_balance = 0
            escaped = False
    if stack:
        issues.extend(f"{path}:{line}: не закрыто окружение {env}" for env, line in stack)
    if brace_balance:
        issues.append(f"{path}: несбалансированные фигурные скобки: {brace_balance:+d}")
    if in_literal:
        issues.append(f"{path}: не закрыто литеральное окружение {in_literal}")
    return issues


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("--entrypoint", default="dissertation.tex")
    parser.add_argument("--json", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    files, missing = active_files(root, root / args.entrypoint)
    issues = [issue for path in files for issue in audit_file(path)]
    active_text = "\n".join(path.read_text(encoding="utf-8") for path in files)
    stale_terms = {
        term: len(re.findall(term, active_text, flags=re.I))
        for term in (r"межпланет", r"баллистическ", r"электрореактив")
    }
    stale_terms = {term: count for term, count in stale_terms.items() if count}
    bibliography_files = [root / value for value in ADD_BIB_RE.findall(active_text)]
    bibliography_entries = sum(
        len(re.findall(r"^@[a-z]+\{", path.read_text(encoding="utf-8"), flags=re.M | re.I))
        for path in bibliography_files
        if path.is_file()
    )
    payload = {
        "entrypoint": args.entrypoint,
        "active_files": [path.relative_to(root).as_posix() for path in files],
        "missing_includes": missing,
        "structural_issues": issues,
        "counts": {
            "chapters": len(re.findall(r"\\chapter\{", active_text)),
            "sections": len(re.findall(r"\\section\{", active_text)),
            "subsections": len(re.findall(r"\\subsection\{", active_text)),
            "footnotes": len(re.findall(r"\\footnote\{", active_text)),
            "figures": len(re.findall(r"\\begin\{figure\}", active_text)),
            "longtables": len(re.findall(r"\\begin\{longtable\}", active_text)),
            "bibliography_entries": bibliography_entries,
        },
        "bibliography_files": [
            path.relative_to(root).as_posix() for path in bibliography_files if path.is_file()
        ],
        "stale_topic_markers": stale_terms,
    }
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if missing or issues or stale_terms:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
