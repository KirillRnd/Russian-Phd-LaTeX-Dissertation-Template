# Библиография: рабочий контур

Каноническая база — `biblio/korneeva_full.bib`. Импорт из DOCX отсутствует.

Проверка и визуальный просмотр библиографии выполняются отдельно от
диссертации:

```powershell
python tools/build_bibliography.py
```

При установленном GNU Make ту же команду можно вызвать так:

```powershell
make bibliography
```

Результат — `output/bibliography/bibliography-preview.html`. Это обычный
читаемый HTML, сформированный теми же `biblatex-gost` и Biber, которые
используются в диссертации. PDF при этой операции не создаётся.

Нормативная выжимка и правила заполнения полей находятся в
`docs/gost-bibliography/GOST-BIBLIOGRAPHY.md`.
