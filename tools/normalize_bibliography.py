#!/usr/bin/env python3
"""Apply reviewed, deterministic normalizations to the canonical BibLaTeX file.

This script only performs decisions recorded below: explicit language metadata
and repairs of fields rejected by the BibLaTeX data model.  It does not import
documents, query external services or invent missing bibliographic facts.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from audit_bibliography import DEFAULT_BIB, infer_language, parse_bibtex


TYPE_UPDATES = {
    "korneeva-research-195": "article",
    "korneeva-research-235": "article",
    "korneeva-research-236": "article",
    "korneeva-research-237": "article",
    "korneeva-research-245": "article",
    "korneeva-research-339": "article",
    "korneeva-research-341": "article",
    "korneeva-research-363": "article",
    "korneeva-research-373": "article",
    "korneeva-research-417": "article",
    "korneeva-research-431": "article",
    "korneeva-footnote-109": "online",
    "korneeva-footnote-101": "article",
    "korneeva-footnote-111": "article",
    "korneeva-footnote-129": "online",
    "korneeva-footnote-150": "inproceedings",
    "korneeva-footnote-151": "online",
    "korneeva-footnote-155": "online",
    "korneeva-footnote-167": "online",
    "korneeva-research-046": "thesis",
    "korneeva-research-060": "thesis",
    "korneeva-footnote-079": "thesis",
    "korneeva-research-345": "article",
    "korneeva-footnote-045": "article",
    "korneeva-footnote-091": "article",
    "korneeva-research-227": "incollection",
    "korneeva-research-355": "incollection",
    "korneeva-research-362": "incollection",
    "korneeva-sources-008": "collection",
    "korneeva-sources-009": "collection",
    "korneeva-sources-029": "collection",
    "korneeva-reference-004": "collection",
    "korneeva-reference-009": "collection",
    "korneeva-footnote-123": "collection",
    "korneeva-sources-006": "incollection",
    "korneeva-sources-012": "book",
    "korneeva-research-080": "incollection",
    "korneeva-research-101": "incollection",
    "korneeva-research-106": "incollection",
    "korneeva-research-111": "incollection",
    "korneeva-research-198": "inproceedings",
    "korneeva-research-200": "incollection",
    "korneeva-research-201": "incollection",
    "korneeva-research-205": "incollection",
    "korneeva-research-210": "inproceedings",
    "korneeva-research-238": "incollection",
    "korneeva-research-332": "inproceedings",
    "korneeva-research-334": "inproceedings",
    "korneeva-research-337": "inproceedings",
    "korneeva-research-358": "incollection",
    "korneeva-research-385": "inproceedings",
    "korneeva-research-386": "incollection",
    "korneeva-research-387": "inproceedings",
    "korneeva-research-390": "incollection",
    "korneeva-research-392": "inproceedings",
    "korneeva-research-393": "inproceedings",
    "korneeva-research-394": "inproceedings",
    "korneeva-footnote-046": "incollection",
    "korneeva-footnote-067": "incollection",
    "korneeva-footnote-070": "inproceedings",
    "korneeva-footnote-094": "incollection",
    "korneeva-footnote-125": "incollection",
    "korneeva-footnote-159": "incollection",
    "korneeva-footnote-161": "inproceedings",
    "korneeva-footnote-148": "misc",
    "korneeva-research-357": "article",
    "korneeva-research-378": "inproceedings",
    "korneeva-research-435": "incollection",
    "korneeva-research-436": "incollection",
    "korneeva-footnote-025": "incollection",
    "korneeva-research-206": "inproceedings",
    "korneeva-footnote-050": "incollection",
    "korneeva-footnote-057": "incollection",
    "korneeva-footnote-121": "incollection",
    "korneeva-research-254": "inproceedings",
    "korneeva-research-361": "inproceedings",
    "korneeva-research-424": "inproceedings",
    "korneeva-footnote-054": "incollection",
    "korneeva-footnote-140": "thesis",
    "korneeva-footnote-158": "thesis",
    "korneeva-research-183": "inproceedings",
    "korneeva-research-192": "inproceedings",
    "korneeva-research-415": "inproceedings",
}

# ``Право в средневековом мире`` is not normalized as an ordinary journal.
# Its bibliographic form changed over time: the 2001 item is issues 2--3 of
# the earlier collection, while the 2007--2010 items form a renewed run of
# annual edited collections.  Keep these decisions isolated and review each
# physical issue independently instead of inferring its type from the shared
# title.  Sources and unresolved conflicts are documented in
# docs/gost-bibliography/PRAVO-V-SREDNEVEKOVOM-MIRE.md.
MEDIEVAL_LAW_TYPE_UPDATES = {
    "korneeva-footnote-116": "collection",
    "korneeva-footnote-116b": "collection",
    "korneeva-footnote-116c": "collection",
    "korneeva-footnote-116d": "collection",
    "korneeva-footnote-116e": "collection",
    "korneeva-footnote-116f": "collection",
    "korneeva-research-100": "incollection",
}

MEDIEVAL_LAW_FIELD_UPDATES: dict[str, dict[str, str | None]] = {
    "korneeva-footnote-116": {
        "title": "Право в средневековом мире",
        "subtitle": "сборник статей",
        "editor": "Варьяш, О. И.",
        "location": "Москва",
        "publisher": "ИВИ РАН",
        "date": "1996",
    },
    "korneeva-footnote-116b": {
        "title": "Право в средневековом мире",
        "subtitle": "сборник статей. Вып. 2--3",
        "editor": "Варьяш, О. И. and Глебов, А. Г. and Закс, В. А. and Варьяш, И. И.",
        "location": "Санкт-Петербург",
        "publisher": "Алетейя",
        "date": "2001",
        "pagetotal": "343, [3]",
        "isbn": "5-89329-359-2",
        "note": None,
    },
    "korneeva-footnote-116c": {
        "title": "Право в средневековом мире. 2007",
        "subtitle": "сборник статей",
        "editor": "Варьяш, И. И. and Попова, Г. А.",
        "location": "Москва",
        "publisher": "ИВИ РАН",
        "date": "2007",
        "pagetotal": "292, [1]",
        "isbn": "5-94067-213-2",
    },
    "korneeva-footnote-116d": {
        "title": "Право в средневековом мире. 2008",
        "subtitle": "сборник статей",
        "editor": "Варьяш, И. И. and Попова, Г. А.",
        "location": "Москва",
        "publisher": "ИВИ РАН",
        "date": "2008",
        "pagetotal": "276",
        "isbn": "5-94067-249-3",
    },
    "korneeva-footnote-116e": {
        "title": "Право в средневековом мире. 2009",
        "subtitle": "сборник статей",
        "editor": "Варьяш, И. И. and Попова, Г. А.",
        "location": "Москва",
        "publisher": "ИВИ РАН",
        "date": "2009",
        "pagetotal": None,
    },
    "korneeva-footnote-116f": {
        "title": "Право в средневековом мире",
        "subtitle": "сборник статей",
        "editor": "Попова, Г. А.",
        "location": "Москва",
        "publisher": "ИВИ РАН",
        "date": "2010",
        "pagetotal": "292",
    },
    "korneeva-research-096": {
        "booktitle": "Право в средневековом мире. 2009",
        "editor": "Варьяш, И. И. and Попова, Г. А.",
        "location": "Москва",
        "publisher": "ИВИ РАН",
        "crossref": "korneeva-footnote-116e",
    },
    "korneeva-research-100": {
        "booktitle": "Право в средневековом мире",
        "editor": "Попова, Г. А.",
        "location": "Москва",
        "publisher": "ИВИ РАН",
        "crossref": "korneeva-footnote-116f",
    },
    "korneeva-research-117": {
        "booktitle": "Право в средневековом мире. 2008",
        "editor": "Варьяш, И. И. and Попова, Г. А.",
        "location": "Москва",
        "publisher": "ИВИ РАН",
        "crossref": "korneeva-footnote-116d",
    },
    "korneeva-research-123": {
        "booktitle": "Право в средневековом мире. 2009",
        "editor": "Варьяш, И. И. and Попова, Г. А.",
        "location": "Москва",
        "publisher": "ИВИ РАН",
        "crossref": "korneeva-footnote-116e",
    },
    "korneeva-curated-varyash-oath": {
        "booktitle": "Право в средневековом мире. 2009",
        "editor": "Варьяш, И. И. and Попова, Г. А.",
        "location": "Москва",
        "publisher": "ИВИ РАН",
        "crossref": "korneeva-footnote-116e",
    },
}

DELETED_KEYS = {
    "korneeva-research-383",  # duplicate of korneeva-sources-020
    "korneeva-research-241",  # duplicate of korneeva-sources-022
    "korneeva-footnote-114",  # duplicate of korneeva-research-040
    "korneeva-footnote-009",  # duplicate of korneeva-research-091
    "korneeva-footnote-115",  # duplicate of korneeva-research-081
    "korneeva-footnote-115b",  # duplicate of korneeva-research-084
    "korneeva-footnote-115c",  # duplicate of korneeva-research-082
    "korneeva-footnote-115d",  # duplicate of korneeva-research-085
    "korneeva-footnote-117",  # duplicate of korneeva-research-163
    "korneeva-footnote-117b",  # duplicate of korneeva-research-161
    "korneeva-footnote-118",  # duplicate of korneeva-research-078
    "korneeva-footnote-118b",  # duplicate of korneeva-research-076
    "korneeva-footnote-118c",  # duplicate of korneeva-research-077
    "korneeva-footnote-119",  # duplicate of korneeva-research-094
    "korneeva-footnote-139",  # duplicate description of korneeva-software-002
}


ADDITIONAL_ENTRIES = r"""
@incollection{korneeva-footnote-115b,
  author       = {Мильская, Л. Т.},
  title        = {Пригородное землевладение арабов и Реконкиста в Каталонии XII века},
  booktitle    = {Проблемы испанской истории},
  editor       = {Пожарская, С. П.},
  location     = {Москва},
  publisher    = {Наука},
  date         = {1984},
  pages        = {158--165},
  langid       = {russian},
  keywords     = {footnote-only},
}

@article{korneeva-footnote-115c,
  author       = {Мильская, Л. Т.},
  title        = {К вопросу о судьбах общины в Каталонии X--XII вв.},
  journaltitle = {Средние века},
  date         = {1985},
  number       = {48},
  pages        = {38--46},
  langid       = {russian},
  keywords     = {footnote-only},
}

@incollection{korneeva-footnote-115d,
  author       = {Мильская, Л. Т.},
  title        = {Феодальная собственность и государственная власть в Каталонии в эпоху завершения Реконкисты},
  booktitle    = {Проблемы испанской истории},
  editor       = {Пожарская, С. П.},
  location     = {Москва},
  publisher    = {Наука},
  date         = {1992},
  pages        = {160--165},
  langid       = {russian},
  keywords     = {footnote-only},
}

@collection{korneeva-footnote-116b,
  title        = {Право в средневековом мире},
  subtitle     = {сборник статей. Вып. 2--3},
  editor       = {Варьяш, О. И. and Глебов, А. Г. and Закс, В. А. and Варьяш, И. И.},
  location     = {Санкт-Петербург},
  publisher    = {Алетейя},
  date         = {2001},
  pagetotal    = {343, [3]},
  isbn         = {5-89329-359-2},
  langid       = {russian},
  keywords     = {footnote-only},
}

@collection{korneeva-footnote-116c,
  title        = {Право в средневековом мире. 2007},
  subtitle     = {сборник статей},
  editor       = {Варьяш, И. И. and Попова, Г. А.},
  location     = {Москва},
  publisher    = {ИВИ РАН},
  date         = {2007},
  pagetotal    = {292, [1]},
  isbn         = {5-94067-213-2},
  langid       = {russian},
  keywords     = {footnote-only},
}

@collection{korneeva-footnote-116d,
  title        = {Право в средневековом мире. 2008},
  subtitle     = {сборник статей},
  editor       = {Варьяш, И. И. and Попова, Г. А.},
  location     = {Москва},
  publisher    = {ИВИ РАН},
  date         = {2008},
  pagetotal    = {276},
  isbn         = {5-94067-249-3},
  langid       = {russian},
  keywords     = {footnote-only},
}

@collection{korneeva-footnote-116e,
  title        = {Право в средневековом мире. 2009},
  subtitle     = {сборник статей},
  editor       = {Варьяш, И. И. and Попова, Г. А.},
  location     = {Москва},
  publisher    = {ИВИ РАН},
  date         = {2009},
  langid       = {russian},
  keywords     = {footnote-only},
}

@collection{korneeva-footnote-116f,
  title        = {Право в средневековом мире},
  subtitle     = {сборник статей},
  editor       = {Попова, Г. А.},
  location     = {Москва},
  publisher    = {ИВИ РАН},
  date         = {2010},
  pagetotal    = {292},
  langid       = {russian},
  keywords     = {footnote-only},
}

@incollection{korneeva-footnote-117b,
  author       = {Червонов, С. Д.},
  title        = {Земледелие и скотоводство в кастильском городе Куэнка в XII в.},
  booktitle    = {Проблемы истории Античности и Средних веков},
  location     = {Москва},
  date         = {1982},
  pages        = {56--71},
  langid       = {russian},
  keywords     = {footnote-only},
}

@book{korneeva-footnote-118b,
  author       = {Марей, А. В.},
  title        = {Божий суд и человеческая справедливость: судебный поединок в Леоне и Кастилии XI--XIII вв.},
  location     = {Москва},
  publisher    = {Союзник},
  date         = {2011},
  langid       = {russian},
  keywords     = {footnote-only},
}

@book{korneeva-footnote-118c,
  author       = {Марей, А. В.},
  title        = {Дружба и доверие в испанском обществе XI--XIII вв.: неправовые регуляторы правового поля},
  location     = {Москва},
  publisher    = {Союзник},
  date         = {2011},
  langid       = {russian},
  keywords     = {footnote-only},
}
""".strip()


FIELD_UPDATES: dict[str, dict[str, str | None]] = {
    "korneeva-reference-002": {
        "translator": "Пресняков, Ю. В.",
        "editor": "Черниловский, З. М.",
        "note": "специальная научная редакция и предисловие З. М. Черниловского",
    },
    "korneeva-reference-003": {"editor": "Зварич, В. В.", "note": None},
    "korneeva-software-002": {"ids": "korneeva-footnote-139"},
    "korneeva-sources-001": {"editor": "Ауров, О. В. and Марей, А. В.", "note": None},
    "korneeva-sources-002": {
        "translator": "Полдников, Д. Ю.",
        "editor": "Кофанов, Л. Л.",
        "note": None,
    },
    "korneeva-sources-003": {
        "editor": "Weber, R. and Gryson, R.",
        "edition": "5",
        "note": None,
    },
    "korneeva-sources-004": {"editor": "Foguet, R. and Marsal, J. F.", "note": None},
    "korneeva-sources-005": {"editor": "Massip i Fonollosa, J.", "note": None},
    "korneeva-sources-007": {"editor": "Sánchez y Sánchez, G.", "note": None},
    "korneeva-sources-010": {
        "editor": "Krueger, P. and Mommsen, Th. and Schoell, R. and Kroll, W.",
        "volume": None,
        "volumes": "3",
        "note": None,
    },
    "korneeva-sources-011": {"editor": "Loscertales de Valdeavellano, M. B. Pilar", "note": None},
    "korneeva-sources-013": {
        "editor": "Serrano Daura, J.",
        "volume": "2",
        "booksubtitle": "Apéndices",
        "note": None,
    },
    "korneeva-sources-014": {
        "editor": "Massip i Fonollosa, J.",
        "note": "amb la col·laboració de C. Duarte i Montserrat i M. A. Massip i Bonet",
    },
    "korneeva-sources-015": {"editor": "Oliver y Esteller, B.", "note": None},
    "korneeva-sources-016": {
        "editor": "Foguet, R.",
        "note": "continuada por J. Foguet Marsal",
    },
    "korneeva-sources-017": {"editor": "Lindsay, W. M.", "note": None},
    "korneeva-sources-018": {"editor": "Serrano Daura, J.", "note": None},
    "korneeva-sources-019": {
        "editor": "Busqueta Riu, J. J. and González, E.",
        "note": None,
    },
    "korneeva-sources-020": {
        "author": "Serrano Daura, J.",
        "ids": "korneeva-research-383",
        "note": None,
    },
    "korneeva-sources-022": {"volume": "23", "ids": "korneeva-research-241"},
    "korneeva-sources-023": {"editor": "Colón, G. and Garcia, A.", "note": None},
    "korneeva-sources-024": {
        "author": "Giraud, Charles",
        "title": "Essai sur l’histoire du droit français au moyen âge",
        "volume": "2",
    },
    "korneeva-sources-025": {
        "editor": "Salrach i Marès, J. M. and Montagut i Estragués, T. de",
        "note": None,
    },
    "korneeva-sources-026": {
        "editor": "Salrach i Marès, J. M. and Montagut i Estragués, T. de",
        "note": None,
    },
    "korneeva-sources-027": {"editor": "Zeumer, K.", "note": None},
    "korneeva-sources-028": {"editor": "Valls i Taberner, F.", "note": None},
    "korneeva-sources-030": {"editor": "Foguet, R.", "note": None},
    "korneeva-sources-031": {"editor": "Gas Carpio, F. J.", "note": None},
    "korneeva-sources-032": {"editor": "Amich, J.", "note": None},
    "korneeva-sources-033": {"editor": "Aragó, A. M. and Costa, M. M.", "note": None},
    "korneeva-sources-034": {
        "editor": "Serrano Daura, J.",
        "volume": "2",
        "booksubtitle": "Apéndices",
        "note": None,
    },
    "korneeva-sources-035": {"editor": "Rovira, J.", "note": None},
    "korneeva-sources-036": {"editor": "Mansi, Giovanni Domenico"},
    "korneeva-sources-037": {
        "author": "Vives y Cebriá, Pedro Nolasco",
        "title": "Traducción al castellano de los usages y demás derechos de Cataluña",
        "location": "Madrid; Barcelona",
        "publisher": "Librería de Emilio Font; Librería del Plus Ultra",
        "date": "1861/1867",
        "edition": "2",
        "volumes": "5",
        "pages": None,
        "pagetotal": None,
    },
    "korneeva-sources-038": {
        "title": "The Usatges of Barcelona: The Fundamental Law of Catalonia",
        "editor": "Kagay, Donald J.",
        "translator": "Kagay, Donald J.",
        "location": "Philadelphia",
        "publisher": "University of Pennsylvania Press",
        "pagetotal": "140",
        "isbn": "978-0-8122-1535-9",
    },
    "korneeva-sources-039": {
        "title": "Usatges de Barcelona i commemoracions de Pere Albert",
        "editor": "Rovira i Ermengol, Josep",
        "series": "Els Nostres Clàssics",
        "number": "43--44",
        "pagetotal": "307",
    },
    "korneeva-sources-040": {"editor": "Gudiol, J.", "note": None},
    "korneeva-sources-041": {"editor": "Bastardas i Parera, J.", "note": None},
    "korneeva-sources-042": {
        "editor": "Abadal i Vinyals, R. d’ and Valls i Taberner, F.",
        "note": None,
    },
    "korneeva-research-088": {"volume": None},
    "korneeva-research-091": {
        "author": "Пискорский, В. К.",
        "title": "Крепостное право в Каталонии в Средние века",
        "location": "Киев",
        "publisher": "Типография Университета св. Владимира Н. Т. Корчак-Новицкого",
        "ids": "korneeva-footnote-009",
        "volume": None,
    },
    "korneeva-research-168": {"volume": "39"},
    "korneeva-research-172": {"volume": None, "number": "103/104"},
    "korneeva-research-183": {"volume": "88"},
    "korneeva-research-189": {"volume": "7", "number": "2"},
    "korneeva-research-192": {"volume": "44"},
    "korneeva-research-194": {"volume": "82"},
    "korneeva-research-195": {
        "booktitle": None,
        "journaltitle": "Speculum",
        "location": None,
        "publisher": None,
        "volume": "53",
    },
    "korneeva-research-040": {
        "editor": "Ведюшкин, В. А. and Попова, Г. А.",
        "ids": "korneeva-footnote-114",
        "note": None,
    },
    "korneeva-research-002": {
        "translator": "Вадковская, Е. А. and Гармсен, О. М.",
        "note": None,
    },
    "korneeva-research-007": {"editor": "Лучицкая, С. И.", "note": None},
    "korneeva-research-025": {
        "translator": "Лысенко, Е. М.",
        "edition": "2",
        "note": "примечания и статья А. Я. Гуревича",
    },
    "korneeva-research-026": {
        "translator": "Кожевникова, М. Ю. and Лысенко, Е. М.",
        "note": None,
    },
    "korneeva-research-027": {
        "translator": "Ведюшкин, В. А. and Попова, Г. А. and Юрчик, Е. Э.",
        "note": None,
    },
    "korneeva-research-047": {
        "editor": "Ведюшкин, В. А. and Попова, Г. А.",
        "note": None,
    },
    "korneeva-research-070": {"editor": "Пожарская, С. П.", "note": None},
    "korneeva-research-071": {
        "editor": "Пожарская, С. П. and Варьяш, О. И.",
        "note": None,
    },
    "korneeva-research-072": {
        "translator": "Руткевич, А. М.",
        "edition": "2",
        "note": None,
    },
    "korneeva-research-076": {"ids": "korneeva-footnote-118b"},
    "korneeva-research-077": {"ids": "korneeva-footnote-118c"},
    "korneeva-research-078": {"ids": "korneeva-footnote-118"},
    "korneeva-research-081": {"ids": "korneeva-footnote-115"},
    "korneeva-research-082": {"ids": "korneeva-footnote-115c"},
    "korneeva-research-084": {
        "editor": "Пожарская, С. П.",
        "ids": "korneeva-footnote-115b",
        "note": None,
    },
    "korneeva-research-085": {
        "editor": "Пожарская, С. П.",
        "ids": "korneeva-footnote-115d",
        "note": None,
    },
    "korneeva-research-086": {"editor": "Сёрл, Дж. Р.", "note": None},
    "korneeva-research-094": {"ids": "korneeva-footnote-119"},
    "korneeva-research-114": {"editor": "Соколов, П. В.", "note": None},
    "korneeva-research-119": {"editor": "Кириллова, Е. Н.", "note": None},
    "korneeva-research-145": {
        "translator": "Окунева, И.",
        "editor": "Скуратов, Б. М.",
        "note": None,
    },
    "korneeva-research-146": {"editor": "Хачатурян, Н. А.", "note": None},
    "korneeva-research-155": {"editor": "Сванидзе, А. А.", "note": None},
    "korneeva-research-156": {"editor": "Хачатурян, Н. А.", "note": None},
    "korneeva-research-157": {"editor": "Хачатурян, Н. А.", "note": None},
    "korneeva-research-160": {"translator": "Сильвестров, Д. В.", "note": None},
    "korneeva-research-161": {"ids": "korneeva-footnote-117b"},
    "korneeva-research-162": {
        "editor": "Ауров, О. В. and Щербакова, Е. И.",
        "note": None,
    },
    "korneeva-research-163": {"ids": "korneeva-footnote-117"},
    "korneeva-research-216": {"volume": "36"},
    "korneeva-research-232": {"editor": "Montagut i Estragués, T. de", "note": None},
    "korneeva-research-235": {
        "booktitle": None,
        "journaltitle": "Mitteilungen des Instituts für Österreichische Geschichtsforschung",
        "pages": "1--76",
    },
    "korneeva-research-236": {
        "booktitle": None,
        "journaltitle": "Mitteilungen des Instituts für Österreichische Geschichtsforschung",
        "pages": "236--276",
    },
    "korneeva-research-237": {
        "booktitle": None,
        "journaltitle": "Mitteilungen des Instituts für Österreichische Geschichtsforschung",
        "pages": "455--542",
    },
    "korneeva-research-245": {
        "booktitle": None,
        "journaltitle": "Boletín de la Sociedad Castellonense de Cultura",
        "volume": "76",
        "number": "1--4",
        "pages": "37--56",
    },
    "korneeva-research-287": {
        "subtitle": "Pródromos para una edición sinóptica",
        "location": "Barcelona",
        "publisher": "Associació Catalana d’Història del Dret “Jaume de Montjuïc”",
        "volume": "1",
    },
    "korneeva-research-288": {
        "subtitle": "Los protagonistas: los manuscritos de los Usatici",
        "location": "Barcelona",
        "publisher": "Associació Catalana d’Història del Dret “Jaume de Montjuïc”",
        "volume": "2",
    },
    "korneeva-research-328": {"volume": "36", "number": "abril--juny"},
    "korneeva-research-339": {
        "booktitle": None,
        "journaltitle": "Zeitschrift für romanische Philologie",
        "volume": "135",
        "number": "2",
        "pages": "507--534",
        "langid": "german",
    },
    "korneeva-research-341": {
        "booktitle": None,
        "journaltitle": "Zeitschrift für Katalanistik: Revista d’Estudis Catalans",
        "pages": "155--199",
    },
    "korneeva-research-363": {
        "booktitle": None,
        "journaltitle": "Revue Historique",
        "volume": "267",
        "number": "2 (532)",
        "pages": "305--326",
    },
    "korneeva-research-373": {
        "booktitle": None,
        "journaltitle": "e-Spania. Revue interdisciplinaire d’études hispaniques médiévales et modernes",
    },
    "korneeva-research-375": {"editor": "Sabaté, F.", "note": None},
    "korneeva-research-396": {"volume": "1"},
    "korneeva-research-417": {
        "booktitle": None,
        "journaltitle": "Journal of Comparative Legislation and International Law",
        "volume": "6",
        "number": "1",
        "pages": "120--124",
    },
    "korneeva-research-426": {"credits": None, "editor": "Sabaté, F."},
    "korneeva-research-428": {"volume": None, "number": "14/15"},
    "korneeva-research-431": {
        "booktitle": None,
        "journaltitle": "e-Spania. Revue interdisciplinaire d’études hispaniques médiévales et modernes",
        "langid": "french",
    },
    "korneeva-footnote-001": {"volume": "4"},
    "korneeva-footnote-004": {"volume": "22"},
    "korneeva-footnote-009": {"volume": None},
    "korneeva-footnote-059": {"volume": "49", "number": "193"},
    "korneeva-footnote-089": {"volume": "12"},
    "korneeva-footnote-032": {"editor": "Sobrequés i Callicó, J.", "note": None},
    "korneeva-footnote-077": {"editor": "Sabaté i Curull, F.", "note": None},
    "korneeva-footnote-078": {"editor": "Sabaté i Curull, F.", "note": None},
    "korneeva-footnote-086": {
        "editor": "Milroy, L. and Muysken, P.",
        "note": None,
    },
    "korneeva-footnote-093": {
        "editor": "Mullen, A. and Woudhuysen, G.",
        "note": None,
    },
    "korneeva-footnote-100": {
        "author": "Аникьев, И. И. and Филиппов, И. С.",
        "title": "Рецензия на книгу: Banniard M. Viva voce: comunicazione scritta e comunicazione orale nell’occidente latino dal IV al IX secolo",
        "volume": "82",
    },
    "korneeva-footnote-101": {
        "booktitle": None,
        "journaltitle": "The Journal of Medieval Latin",
        "location": None,
        "publisher": None,
        "volume": "3",
        "number": None,
    },
    "korneeva-footnote-115": {
        "author": "Мильская, Л. Т.",
        "title": "К вопросу о структуре господствующего класса в Каталонии X--XII вв.",
        "journaltitle": "Средние века",
        "booktitle": None,
        "location": None,
        "publisher": None,
        "date": "1984",
        "number": "47",
        "pages": "21--28",
        "note": None,
    },
    "korneeva-footnote-116": {
        "editor": "Варьяш, О. И.",
        "location": "Москва",
        "publisher": "ИВИ РАН",
        "date": "1996",
        "note": None,
    },
    "korneeva-footnote-117": {
        "author": "Червонов, С. Д.",
        "title": "Торговля в испанском городе XII--XIII веков (по материалам фуэрос)",
        "journaltitle": "Проблемы испанской истории",
        "date": "1984",
        "pages": "146--157",
    },
    "korneeva-footnote-118": {
        "title": "Язык права средневековой Испании: от Законов XII таблиц до Семи партид",
        "location": "Москва",
        "publisher": "URSS",
        "date": "2008",
    },
    "korneeva-footnote-119": {
        "author": "Полдников, Д. Ю.",
        "title": "Особенности юридической техники западноевропейской правовой науки XIII--XV вв.",
        "journaltitle": "История государства и права",
        "date": "2015",
        "number": "6",
        "pages": "19--25",
    },
    "korneeva-footnote-104": {
        "editor": "Mostert, M. and Barnwell, P. S.",
        "note": None,
    },
    "korneeva-footnote-105": {
        "editor": "Mostert, M. and Barnwell, P. S.",
        "note": None,
    },
    "korneeva-footnote-109": {
        "title": "Луллий Раймунд",
        "booktitle": None,
        "organization": "Большая российская энциклопедия: научно-образовательный портал",
        "note": "Рамон Льюль (1232--1316?) — каталонский религиозный деятель, писатель и поэт",
    },
    "korneeva-footnote-111": {
        "booktitle": None,
        "journaltitle": "L’Atelier du Centre de recherches historiques",
        "date": "2017",
    },
    "korneeva-footnote-122": {
        "editor": "Гусейнов, А. А. and Рашковский, Е. Б.",
        "note": "составитель П. Д. Баренбойм",
    },
    "korneeva-footnote-126": {
        "editor": "Ведюшкин, В. А. and Попова, Г. А.",
        "note": None,
    },
    "korneeva-footnote-129": {
        "booktitle": None,
        "organization": "Gran Enciclopèdia Catalana. Enciclopèdia.cat",
    },
    "korneeva-footnote-131": {
        "editor": "Ведюшкин, В. А. and Попова, Г. А.",
        "note": None,
    },
    "korneeva-footnote-137": {
        "editor": "Ведюшкин, В. А. and Попова, Г. А.",
        "note": None,
    },
    "korneeva-footnote-138": {
        "editor": "Ведюшкин, В. А. and Попова, Г. А.",
        "note": None,
    },
    "korneeva-footnote-141": {"editor": "Goetz, G.", "volume": "5", "note": None},
    "korneeva-footnote-149": {
        "editor": "North, R. and Hofstra, T.",
        "note": None,
    },
    "korneeva-footnote-151": {
        "author": "Alcover, Antoni Maria and Moll, Francesc de Borja",
        "booktitle": None,
        "organization": "Diccionari català-valencià-balear",
    },
    "korneeva-footnote-164": {"editor": "Зварич, В. В.", "note": None},
    "korneeva-footnote-166": {
        "editor": "Fenster, T. and Smail, Daniel Lord",
        "note": None,
    },
    "korneeva-footnote-150": {
        "author": "Chao Fernández, Juan José and Mesa Sanz, Juan Francisco and Puche López, María Carmen",
        "title": "Latín y vernáculo en los documentos de Jaime I «El Conquistador»",
        "booktitle": "IV Congresso Internacional de Latim Medieval Hispânico: Lisboa, 12--15 de outubro de 2005: actas",
        "editor": "Nascimento, Aires Augusto and Alberto, Paulo Farmhouse",
        "location": "Lisboa",
        "publisher": "Centro de Estudos Clássicos, Universidade de Lisboa",
        "date": "2006",
        "pages": "305--315",
        "isbn": "978-972-9376-12-2",
    },
    "korneeva-footnote-154": {"volume": "45", "number": "1"},
    "korneeva-footnote-155": {
        "booktitle": None,
        "organization": "Gran Enciclopèdia Catalana",
        "url": "https://www.enciclopedia.cat/gran-enciclopedia-catalana/catarisme",
        "langid": "catalan",
    },
    "korneeva-footnote-167": {
        "title": "Bastaix",
        "booktitle": None,
        "organization": "Gran Diccionari de la llengua catalana",
        "url": "https://www.diccionari.cat/GDLC/bastaix",
        "note": "Бастайши — профессиональные переносчики тяжестей",
    },
}


# Facts recovered during the strict, binary readiness pass.  Every value here
# comes either from the preserved annotation or from a cited catalogue/site;
# unresolved facts stay absent and therefore keep the entry in NOT READY.
STRICT_READINESS_UPDATES: dict[str, dict[str, str | None]] = {
    "korneeva-reference-001": {
        "organization": "Glossarium Mediae Latinitatis Cataloniae (Universitat de Barcelona; CSIC)",
    },
    "korneeva-reference-005": {
        "organization": "Большая российская энциклопедия",
    },
    "korneeva-reference-006": {
        "author": "Lewis, Charlton T. and Short, Charles",
        "publisher": "Clarendon Press",
    },
    "korneeva-reference-007": {
        "organization": "Institut d’Estudis Catalans",
    },
    "korneeva-reference-008": {
        "organization": "Enciclopèdia Catalana",
    },
    "korneeva-reference-009": {
        "editor": "Du Cange, Charles du Fresne and others",
    },
    "korneeva-reference-010": {
        "organization": "Institut d’Estudis Catalans",
    },
    "korneeva-software-001": {
        "author": "Iasinskaia, Anna",
    },
    "korneeva-software-002": {
        "organization": "Biblissima+",
    },
    "korneeva-sources-009": {
        "editor": "Massip i Fonollosa, J.",
        "editortype": "redactor",
    },
    "korneeva-footnote-123": {
        "editor": "Sarret i Pons, Lluís",
        "location": "Tàrrega",
        "publisher": "Impr. F. Camps Calvet",
    },
    "korneeva-reference-003": {
        "publisher": "Вища школа",
    },
    "korneeva-research-046": {
        "type": "диссертация кандидата филологических наук",
        "institution": "Московский государственный университет имени М. В. Ломоносова",
        "location": "Москва",
        "pagetotal": "233",
    },
    "korneeva-research-060": {
        "type": "диссертация доктора исторических наук",
        "institution": "Институт этнологии и антропологии имени Н. Н. Миклухо-Маклая РАН",
        "location": "Москва",
        "pagetotal": "307",
    },
    "korneeva-footnote-079": {
        "type": "диссертация",
        "institution": "Universitat de Barcelona",
        "location": "Barcelona",
        "volumes": "2",
    },
    "korneeva-research-191": {
        "location": "Berkeley",
        "publisher": "University of California Press",
    },
    "korneeva-research-227": {
        "title": "The duel in medieval western mentality",
        "booktitle": "Making of the Medieval Mediterranean",
        "editor": "Sabaté i Curull, F.",
        "location": "Leeds",
        "publisher": "Arc Humanities Press",
        "pages": "175--202",
        "note": None,
    },
    "korneeva-research-325": {
        "location": "London and New York",
        "publisher": "Routledge",
    },
    "korneeva-research-343": {
        "location": "Barcelona",
        "publisher": "Editorial Selecta",
    },
    "korneeva-research-345": {
        "title": "El proceso de creación del catalán escrito",
        "journaltitle": "Aemilianense: revista internacional sobre la génesis y los orígenes históricos de las lenguas romances",
        "volume": "1",
        "pages": "431--455",
    },
    "korneeva-research-355": {
        "title": "Roman law and early representation in Spain and Italy, 1150--1250",
        "booktitle": "Studies in Medieval Legal Thought: Public Law and the State, 1100--1322",
        "location": "Princeton, New Jersey",
        "publisher": "Princeton University Press",
        "pages": "61--90",
    },
    "korneeva-research-362": {
        "title": "Auctoritas, potestas: concepts of power in medieval Spain",
        "booktitle": "Making of the Medieval Mediterranean",
        "editor": "Sabaté i Curull, F.",
        "location": "Leeds",
        "publisher": "Arc Humanities Press",
        "pages": "51--72",
        "note": None,
    },
    "korneeva-research-371": {
        "title": "L’expansió territorial de Catalunya: segles IX--XII: conquesta o repoblació?",
        "location": "Lleida",
        "publisher": "Servei de Publicacions, Universitat de Lleida",
        "pagetotal": "95",
        "series": "Espai/Temps",
        "number": "28",
    },
    "korneeva-footnote-045": {
        "title": "The convenientiae of the Catalan counts in the eleventh century: a diplomatic and historical analysis",
        "journaltitle": "Acta historica et archaeologica mediaevalia",
        "number": "19",
        "pages": "191--228",
    },
    "korneeva-footnote-048": {
        "author": "Montagut i Estragués, T. de and Ferro Delgado, V. and Serrano Daura, J.",
        "title": "Història del dret català",
        "location": "Barcelona",
        "publisher": "Universitat Oberta de Catalunya",
    },
    "korneeva-footnote-088": {
        "location": "Cambridge",
        "publisher": "Cambridge University Press",
    },
    "korneeva-footnote-091": {
        "title": "De la voz en el texto: cambios y permanencias en el proceso de afirmación de la escritura (Cataluña, siglo X--XII)",
        "journaltitle": "Acta historica et archaeologica mediaevalia",
        "number": "20",
        "pages": "139--175",
    },
    "korneeva-footnote-092": {
        "location": "University Park, Pennsylvania",
        "publisher": "Penn State University Press",
    },
    "korneeva-footnote-168": {
        "location": "Philadelphia",
        "publisher": "University of Pennsylvania Press",
    },
    "korneeva-research-259": {
        "author": "Higounet, Ch.",
        "title": "Congregare populationem: politiques de peuplement dans l’Europe Méridionale (Xe--XIVe siècles)",
    },
    "korneeva-research-400": {
        "author": "Smith, T. F. and Waterman, M. S. and Fitch, W. M.",
        "title": "Comparative biosequence metrics",
    },
    "korneeva-sources-006": {
        "booktitle": "El mercat de Balaguer a través dels documents de l’Arxiu Comarcal de la Noguera: quadern didàctic ACN",
        "journaltitle": None,
        "location": "Balaguer",
        "publisher": "Arxiu Comarcal de la Noguera",
    },
    "korneeva-sources-012": {
        "author": "Mar, Carmen J.",
        "title": "Bujaraloz: VIII centenario de su fundación y época de su pertenencia a la Orden de San Jorge de Alfama, 1205--1230",
        "booktitle": None,
        "pages": None,
        "pagetotal": "260",
        "isbn": "978-84-7820-843-2",
    },
    "korneeva-sources-021": {
        "booktitle": "Geschichte des Römischen Rechts im Mittelalter",
        "bookauthor": "Savigny, Friedrich Carl von",
        "publisher": "J. C. B. Mohr",
        "volume": "2",
        "pages": "297--392",
    },
    "korneeva-sources-008": {"pages": None},
    "korneeva-sources-024": {"pages": None},
    "korneeva-sources-033": {"pages": None},
    "korneeva-sources-025": {
        "publisher": "Parlament de Catalunya; Generalitat de Catalunya, Departament de Justícia, Drets i Memòria",
        "isbn": "978-84-09-63808-6",
    },
    "korneeva-sources-032": {"publisher": "Arnau Guillem de Montpesat"},
    "korneeva-sources-042": {"publisher": "Casa Provincial de Caritat"},
    "korneeva-reference-004": {
        "location": "Москва",
        "publisher": "Церковно-научный центр «Православная энциклопедия»",
    },
    "korneeva-research-007": {
        "location": "Москва",
        "publisher": "Аквилон",
    },
    "korneeva-research-034": {"issueyear": "1979"},
    "korneeva-research-037": {"pages": "32--35"},
    "korneeva-research-045": {"pages": "238--294"},
    "korneeva-research-069": {"pages": "21--41"},
    "korneeva-research-080": {
        "booktitle": "Власть и политическая культура в Средневековой Европе",
        "journaltitle": None,
        "location": "Москва",
        "publisher": "Наука",
        "volume": "1",
    },
    "korneeva-research-101": {
        "booktitle": "Historia animata",
        "journaltitle": None,
        "location": "Москва",
        "publisher": "ИВИ РАН",
        "volume": "1",
    },
    "korneeva-research-106": {
        "booktitle": "История: переводить, понимать, оценивать: к юбилею М. А. Юсима",
        "journaltitle": None,
        "location": "Москва",
        "publisher": "ИВИ РАН",
    },
    "korneeva-research-111": {
        "booktitle": "Доминирование и контроль: интерпретация культурных кодов",
        "journaltitle": None,
        "editor": "Михайлин, В. Ю. and Решетникова, Е. С.",
        "location": "Саратов",
        "publisher": "Саратовский государственный университет",
    },
    "korneeva-research-113": {
        "issueyear": "2014",
        "issn": "1607-6184",
    },
    "korneeva-research-114": {"publisher": "ИВИ РАН"},
    "korneeva-research-119": {"publisher": "ИВИ РАН"},
    "korneeva-research-126": {
        "volume": "10",
        "number": "10 (84)",
        "eid": None,
        "doi": "10.18254/S207987840007599-7",
        "url": "https://history.jes.su/s207987840007599-7-1/",
        "urldate": "2026-08-29",
    },
    "korneeva-research-145": {"pages": "40--172"},
    "korneeva-research-161": {"issueyear": "1982"},
    "korneeva-research-163": {"issueyear": "1984"},
    "korneeva-research-170": {
        "author": "Arvizu y Galarraga, F. de",
        "title": "Fianzas procesales en la documentación altomedieval",
        "volume": "92",
    },
    "korneeva-research-173": {"volume": "64", "number": "2"},
    "korneeva-research-183": {
        "booktitle": "L’aveu. Antiquité et Moyen Âge: actes de la table ronde de Rome (28--30 mars 1984)",
        "journaltitle": None,
        "location": "Rome",
        "publisher": "École française de Rome",
        "volume": "88",
        "number": None,
        "langid": "french",
    },
    "korneeva-research-192": {
        "booktitle": "Structures féodales et féodalisme dans l’Occident méditerranéen (Xe--XIIIe siècles): bilan et perspectives de recherches: actes du colloque de Rome (10--13 octobre 1978)",
        "journaltitle": None,
        "location": "Rome",
        "publisher": "École française de Rome",
        "volume": "44",
        "number": None,
    },
    "korneeva-research-194": {
        "journaltitle": "The American Historical Review",
    },
    "korneeva-research-198": {
        "booktitle": "Proceedings of the Thirteenth International Congress of Medieval Canon Law: Esztergom, 3--8 August 2008",
        "journaltitle": None,
        "location": "Città del Vaticano",
        "publisher": "Biblioteca Apostolica Vaticana",
    },
    "korneeva-research-200": {
        "booktitle": "Los orígenes del feudalismo en el mundo mediterráneo",
        "journaltitle": None,
        "location": "Granada",
        "publisher": "Universidad de Granada",
    },
    "korneeva-research-201": {
        "booktitle": "Histoire des Espagnols",
        "journaltitle": None,
        "location": "Paris",
        "publisher": "Armand Colin",
        "volume": "1",
    },
    "korneeva-research-205": {
        "booktitle": "Langages et peuples d’Europe: cristallisation des identités romanes et germaniques, VIIe--XIe siècle",
        "journaltitle": None,
        "location": "Toulouse",
        "publisher": "CNRS; Université Toulouse-Le Mirail",
    },
    "korneeva-research-206": {
        "booktitle": "Symposium internacional sobre els orígens de Catalunya (segles VIII--XI)",
        "journaltitle": None,
        "location": "Barcelona",
        "publisher": "Comissió del Mil·lenari de Catalunya, Generalitat de Catalunya",
        "volume": "1",
        "isbn": "84-600-7797-7",
    },
    "korneeva-research-208": {
        "author": "Brocà i de Montagut, G. M. de",
        "title": "Els Usatges de Barcelona",
        "volume": "5",
    },
    "korneeva-research-210": {
        "booktitle": "Actes del Quart Col·loqui Internacional de Llengua i Literatura Catalanes",
        "journaltitle": None,
        "location": "Barcelona",
        "publisher": "Publicacions de l’Abadia de Montserrat",
    },
    "korneeva-research-215": {"volume": "50"},
    "korneeva-research-218": {"volume": "4"},
    "korneeva-research-231": {"volume": "1"},
    "korneeva-research-232": {"publisher": "Institut d’Estudis Catalans"},
    "korneeva-research-234": {"pages": "179--230"},
    "korneeva-research-238": {
        "booktitle": "Catalunya i Europa a través de l’Edat Mitjana",
        "journaltitle": None,
        "location": "Lleida",
        "publisher": "Pagès Editors",
    },
    "korneeva-research-248": {"number": "suppl. 2", "pages": "ii53--ii59"},
    "korneeva-research-250": {"volume": "31"},
    "korneeva-research-254": {
        "title": "Animation maritime et développement urbain des côtes de l’Espagne orientale et du Languedoc au Xe siècle",
        "booktitle": "Occident et Orient au Xe siècle",
        "location": "Paris",
        "publisher": "Publications de la Sorbonne",
        "date": "1979",
        "pages": "187--201",
    },
    "korneeva-research-258": {
        "location": "València",
        "publisher": "Tirant lo Blanch",
    },
    "korneeva-research-259": {"issueyear": "1979"},
    "korneeva-research-312": {"volume": "8"},
    "korneeva-research-267": {"langid": "spanish"},
    "korneeva-research-268": {"langid": "spanish"},
    "korneeva-research-313": {"volume": "21"},
    "korneeva-research-332": {
        "booktitle": "Jaime I y su época: X Congreso de Historia de la Corona de Aragón",
        "journaltitle": None,
        "location": "Zaragoza",
        "publisher": "Institución Fernando el Católico",
    },
    "korneeva-research-334": {
        "booktitle": "Les cartes de població cristiana i de seguretat de jueus i sarraïns de Tortosa (1148--1149): actes de les Jornades d’Estudi",
        "journaltitle": None,
        "location": "Barcelona",
        "publisher": "Universitat Internacional de Catalunya",
    },
    "korneeva-research-337": {
        "booktitle": "Estudios de latín medieval hispánico: actas del V Congreso Hispánico de Latín Medieval",
        "journaltitle": None,
        "location": "Firenze",
        "publisher": "SISMEL, Edizioni del Galluzzo",
    },
    "korneeva-research-342": {
        "location": "Barcelona",
        "publisher": "Rafael Dalmau",
    },
    "korneeva-research-340": {"volume": "71", "number": "2"},
    "korneeva-research-352": {
        "eid": "jzae052",
        "doi": "10.1093/jigpal/jzae052",
    },
    "korneeva-research-358": {
        "title": "El espacio eclesiástico y la formación de las parroquias en la Cataluña de los siglos IX al XII",
        "booktitle": "L’environnement des églises et la topographie religieuse des campagnes médiévales",
        "location": "Aix-en-Provence",
        "publisher": "Société d’Archéologie Médiévale",
        "pages": "57--67",
    },
    "korneeva-research-361": {
        "title": "Combattant de Dieu ou combattant du Diable? Le combattant dans les duels judiciaires aux IXe et Xe siècles",
        "booktitle": "Le combattant au Moyen Âge",
        "location": "Paris",
        "publisher": "Publications de la Sorbonne",
        "date": "1995",
        "pages": "111--119",
    },
    "korneeva-research-373": {
        "url": "https://journals.openedition.org/e-spania/",
        "urldate": "2026-08-29",
    },
    "korneeva-research-379": {"number": "5"},
    "korneeva-research-408": {"volume": "20"},
    "korneeva-research-410": {"volume": "19"},
    "korneeva-research-418": {"pages": "77--102"},
    "korneeva-research-424": {
        "booktitle": "Les historiens et le latin médiéval: colloque tenu à la Sorbonne les 9, 10 et 11 septembre 1999",
        "location": "Paris",
        "publisher": "Publications de la Sorbonne",
        "doi": "10.4000/books.psorbonne.21127",
    },
    "korneeva-research-404": {
        "journaltitle": "Mélanges de l’École française de Rome. Moyen Âge",
        "volume": "112",
        "number": "2",
        "langid": "french",
    },
    "korneeva-research-415": {
        "author": "Virgili, A.",
        "booktitle": "L’incastellamento: actes des rencontres de Gérone (26--27 novembre 1992) et de Rome (5--7 mai 1994)",
        "journaltitle": None,
        "location": "Rome",
        "publisher": "École française de Rome",
        "volume": "241",
        "number": None,
        "langid": "spanish",
    },
    "korneeva-research-417": {
        "author": "de Villiers, M.",
        "title": "Consideration in the Roman Law of Contract",
        "booktitle": None,
        "journaltitle": "Journal of Comparative Legislation and International Law",
        "location": None,
        "publisher": None,
        "volume": "6",
        "number": "1",
        "pages": "120--124",
    },
    "korneeva-research-425": {"issueyear": "1970"},
    "korneeva-footnote-016": {"volume": "27--28"},
    "korneeva-footnote-012": {
        "author": "d’Abadal i de Vinyals, R.",
        "title": "La data i el lloc de la mort del comte Berenguer Ramon I",
        "langid": "catalan",
    },
    "korneeva-footnote-020": {"number": "5--6"},
    "korneeva-footnote-023": {"volume": "2"},
    "korneeva-footnote-043": {"volume": "11", "number": "1"},
    "korneeva-footnote-049": {
        "author": "Montagut i Estragués, T. de",
        "title": "La recepción del derecho feudal común en Cataluña I (1211--1330): la alienación del feudo sin el consentimiento del señor",
    },
    "korneeva-footnote-054": {
        "booktitle": "Western Views of Islam in Medieval and Early Modern Europe: Perception of Other",
        "editor": "Blanks, D. R. and Frassetto, M.",
        "location": "New York",
        "publisher": "St. Martin’s Press",
        "note": None,
    },
    "korneeva-footnote-050": {
        "booktitle": "Espacios y fueros en Castilla-La Mancha (siglos XI--XV): una perspectiva metodológica",
        "journaltitle": None,
        "editor": "Alvarado Planas, J.",
        "location": "Madrid",
        "publisher": "Ediciones Polifemo",
        "number": "2",
    },
    "korneeva-footnote-055": {"volume": "32", "number": "1"},
    "korneeva-footnote-056": {"volume": "24"},
    "korneeva-footnote-057": {
        "booktitle": "Mundos medievales: espacios, sociedades y poder: homenaje al profesor José Ángel García de Cortázar y Ruiz de Aguirre",
        "journaltitle": None,
        "editor": "Arízaga Bolumburu, B.",
        "location": "Santander",
        "publisher": "Ediciones de la Universidad de Cantabria",
        "volume": "1",
    },
    "korneeva-footnote-078": {"publisher": "Arc Humanities Press"},
    "korneeva-footnote-080": {"pages": "325--340"},
    "korneeva-footnote-082": {"pages": None},
    "korneeva-footnote-083": {
        "journaltitle": "Linguistics",
        "number": "1",
        "pages": "99--136",
    },
    "korneeva-footnote-084": {
        "publisher": "Oxford University Press",
        "pages": None,
    },
    "korneeva-footnote-086": {
        "editor": "Milroy, L. and Muysken, P.",
        "note": None,
        "publisher": "Cambridge University Press",
        "pages": "177--198",
        "doi": "10.1017/CBO9780511620867.009",
    },
    "korneeva-footnote-089": {
        "volume": "12",
        "pages": "61--70",
        "doi": "10.3406/medi.1993.1573",
    },
    "korneeva-footnote-096": {"pages": None},
    "korneeva-footnote-095": {"pages": None},
    "korneeva-footnote-099": {"pages": None},
    "korneeva-footnote-094": {
        "booktitle": "Languages and Communities in the Late-Roman and Post-Imperial Western Provinces",
        "journaltitle": None,
        "crossref": "korneeva-footnote-093",
        "date": "2023",
        "location": "Oxford",
        "publisher": "Oxford University Press",
    },
    "korneeva-footnote-105": {"publisher": "Brepols"},
    "korneeva-footnote-101": {
        "booktitle": None,
        "journaltitle": "The Journal of Medieval Latin",
        "location": None,
        "publisher": None,
        "volume": "3",
        "number": None,
        "pages": "78--94",
    },
    "korneeva-footnote-102": {"pages": None},
    "korneeva-footnote-103": {
        "pages": "1--10",
        "doi": "10.1017/CBO9780511584008.002",
    },
    "korneeva-footnote-106": {
        "pages": "1--8",
        "doi": "10.1017/CBO9780511597534.001",
    },
    "korneeva-footnote-107": {"pages": "67--84"},
    "korneeva-footnote-108": {"pages": None},
    "korneeva-footnote-112": {
        "pages": "9--21",
        "doi": "10.3917/cehm.041.0009",
    },
    "korneeva-footnote-113": {"pages": "431--455", "langid": "catalan"},
    "korneeva-footnote-120": {"pages": None},
    "korneeva-footnote-125": {
        "booktitle": "Как мы пишем историю?",
        "journaltitle": None,
        "location": "Москва",
        "publisher": "РОССПЭН",
    },
    "korneeva-footnote-121": {
        "booktitle": "Антология мировой правовой мысли",
        "journaltitle": None,
        "location": "Москва",
        "publisher": "Мысль",
        "pages": "209--215",
    },
    "korneeva-footnote-122": {
        "editor": "Гусейнов, А. А. and Рашковский, Е. Б.",
        "note": "составитель П. Д. Баренбойм",
        "pages": "320--368",
    },
    "korneeva-footnote-127": {
        "pages": "19--49",
        "editor": "Sabaté i Curull, F.",
    },
    "korneeva-footnote-128": {"pages": "25--55"},
    "korneeva-footnote-130": {"number": "19"},
    "korneeva-footnote-131": {
        "editor": "Ведюшкин, В. А. and Попова, Г. А.",
        "note": None,
        "location": "Москва",
        "publisher": "Индрик",
        "pages": "261--294",
        "isbn": "978-5-91674-240-4",
    },
    "korneeva-footnote-134": {"publisher": "Generalitat de Catalunya, Departament de Justícia"},
    "korneeva-footnote-123": {"pages": None},
    "korneeva-footnote-132": {"pages": "147--159"},
    "korneeva-footnote-133": {"number": "2", "pages": "290--311"},
    "korneeva-footnote-135": {"pages": None},
    "korneeva-footnote-136": {
        "pages": "53--80",
        "editor": "Ferrer Mallol, M. T. and Coulon, D.",
        "note": None,
    },
    "korneeva-footnote-137": {
        "editor": "Ведюшкин, В. А. and Попова, Г. А.",
        "note": None,
        "location": "Москва",
        "publisher": "Индрик",
        "pages": "341--352",
        "isbn": "978-5-91674-240-4",
    },
    "korneeva-footnote-138": {
        "editor": "Ведюшкин, В. А. and Попова, Г. А.",
        "note": None,
        "location": "Москва",
        "publisher": "Индрик",
        "pages": "295--315",
        "isbn": "978-5-91674-240-4",
    },
    "korneeva-footnote-148": {
        "institution": "Skoklostersamlingen",
        "location": "Stockholm",
        "shelfmark": "1, E 8641",
    },
    "korneeva-footnote-145": {"pages": None},
    "korneeva-footnote-140": {
        "type": "PhD thesis",
        "institution": "Università degli Studi di Palermo",
        "publisher": None,
        "pages": None,
    },
    "korneeva-footnote-152": {
        "pages": "169--197",
        "doi": "10.46586/ZfK.2019.169-197",
    },
    "korneeva-footnote-154": {"volume": "45", "number": "1", "pages": "195--231"},
    "korneeva-footnote-157": {"pages": "285--334"},
    "korneeva-footnote-158": {
        "type": "PhD thesis",
        "institution": "Universitat de Barcelona",
        "publisher": None,
        "pages": None,
    },
    "korneeva-footnote-159": {
        "booktitle": "Пиренейские тетради: право, общество, власть и человек в Средние века",
        "journaltitle": None,
        "editor": "Варьяш, И. И. and Попова, Г. А.",
        "location": "Москва",
        "publisher": "Наука",
        "pages": "167--214",
        "isbn": "5-02-035183-0",
    },
    "korneeva-footnote-161": {
        "booktitle": "IV Congresso Internacional de Latim Medieval Hispânico: Lisboa, 12--15 de outubro de 2005: actas",
        "journaltitle": None,
        "location": "Lisboa",
        "publisher": "Centro de Estudos Clássicos, Universidade de Lisboa",
    },
    "korneeva-footnote-164": {
        "location": "Львов",
        "publisher": "Вища школа",
        "pages": "104--105",
    },
    "korneeva-footnote-166": {
        "editor": "Fenster, T. and Smail, Daniel Lord",
        "note": None,
        "location": "Ithaca, New York",
        "publisher": "Cornell University Press",
        "pages": "95--117",
    },
    "korneeva-footnote-163": {"pages": "37--64", "note": None},
    "korneeva-footnote-160": {
        "title": "Estudi de la paraula aixovar",
        "journaltitle": "Aula de Lletres Valencianes. Revista Valenciana de Filologia",
        "pages": "95--131",
        "issn": "2253-7694",
    },
    "korneeva-footnote-169": {"pages": "67--100"},
    "korneeva-footnote-168": {"pages": None},
    "korneeva-footnote-170": {"volume": "42"},
    "korneeva-research-357": {
        "title": "Dans le Padouan des Xe--XIe siècles: évêques, vavasseurs, «cives»",
        "journaltitle": "Actes des congrès de la Société des historiens médiévistes de l’enseignement supérieur public",
        "volume": "14",
        "pages": "141--150",
        "doi": "10.3406/shmes.1983.1408",
        "location": None,
        "publisher": None,
        "note": "Numéro thématique: L’Église et le siècle de l’an mil au début du XIIe siècle",
    },
    "korneeva-research-378": {
        "title": "El juramento en los Furs de Valencia y en Las Costums de Tortosa",
        "booktitle": "Actas del VI Congreso Iberoamericano y III Congreso Internacional de Derecho romano: La prueba y los medios de prueba: de Roma al derecho moderno",
        "location": "Madrid",
        "publisher": "Universidad Rey Juan Carlos, Servicio de Publicaciones",
        "pages": "729--737",
    },
    "korneeva-research-385": {
        "booktitle": "El territori i les seves institucions històriques: actes de les jornades d’estudi commemoratives del 650è aniversari de la incorporació definitiva del marge dret del riu Ebre a Catalunya",
        "location": "Barcelona",
        "publisher": "Fundació Noguera",
        "volume": "1",
        "pages": "67--96",
        "editor": "Serrano Daura, J.",
    },
    "korneeva-research-386": {
        "booktitle": "El temps sota control: homenatge a F. Xavier Ricomà Vendrell",
        "location": "Tarragona",
        "publisher": "Diputació de Tarragona",
    },
    "korneeva-research-387": {
        "booktitle": "Les cartes de població cristiana i de seguretat de jueus i sarraïns de Tortosa (1148/1149): actes de les Jornades d’Estudi",
        "location": "Barcelona",
        "publisher": "Universitat Internacional de Catalunya",
        "editor": "Serrano Daura, J.",
    },
    "korneeva-research-390": {
        "booktitle": "Pouvoirs des familles, familles de pouvoir",
        "location": "Toulouse",
        "publisher": "Presses universitaires du Midi",
        "editor": "Bertrand, M.",
        "doi": "10.4000/books.pumi.39536",
        "pages": "51--77",
    },
    "korneeva-research-392": {
        "booktitle": "1209--1309: un siècle intense au pied des Pyrénées",
        "location": "Foix",
        "publisher": "Conseil général de l’Ariège, Archives départementales",
    },
    "korneeva-research-393": {
        "booktitle": "Jornades d’estudi sobre els costums de la batllia de Miravet: actes",
        "location": "Tarragona",
        "publisher": "Consell Comarcal de la Terra Alta; Diputació de Tarragona",
        "editor": "Montagut i Estragués, T. de and Serrano Daura, J.",
    },
    "korneeva-research-394": {
        "booktitle": "VII Centenari dels Costums d’Orta (1296--1996): actes de les Jornades d’Estudi",
        "location": "Horta de Sant Joan",
        "publisher": "Ajuntament d’Horta de Sant Joan",
    },
    "korneeva-research-435": {
        "booktitle": "Le passé à l’épreuve du présent: appropriations et usages du passé du Moyen Âge à la Renaissance",
        "editor": "Chastang, P.",
        "location": "Paris",
        "publisher": "Presses de l’Université Paris-Sorbonne",
        "pages": "139--168",
    },
    "korneeva-research-436": {
        "booktitle": "Auctor et auctoritas: invention et conformisme dans l’écriture médiévale",
        "editor": "Zimmermann, M.",
        "location": "Paris",
        "publisher": "École des chartes",
        "pages": "337--358",
    },
    "korneeva-footnote-025": {
        "author": "Bonnassie, P. and Guichard, P.",
        "booktitle": "Les communautés villageoises en Europe occidentale du Moyen Âge aux Temps modernes",
        "location": "Auch",
        "publisher": "Comité départemental du tourisme du Gers",
        "series": "Flaran",
        "number": "4",
    },
    "korneeva-footnote-046": {
        "booktitle": "Records and Processes of Dispute Settlement in Early Medieval Societies: Iberia and Beyond",
        "editor": "Alfonso Antón, I. and Andrade, J. M. and Marques, A. E.",
        "location": "Leiden; Boston",
        "publisher": "Brill",
        "doi": "10.1163/9789004683006_013",
    },
    "korneeva-footnote-067": {
        "booktitle": "Cortes y Parlamentos en la Edad Media peninsular",
        "editor": "Navarro Espinach, G. and Villanueva Morte, C.",
        "location": "Murcia",
        "publisher": "Sociedad Española de Estudios Medievales",
    },
    "korneeva-footnote-070": {
        "booktitle": "El territori i les seves institucions històriques: actes de les jornades d’estudi commemoratives del 650è aniversari de la incorporació definitiva del marge dret del riu Ebre a Catalunya",
        "location": "Barcelona",
        "publisher": "Fundació Noguera",
        "volume": "2",
        "editor": "Serrano Daura, J.",
    },
}


ENTRY_MARKER = re.compile(r"@([A-Za-z]+)\s*\{")


def entry_spans(text: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    cursor = 0
    while match := ENTRY_MARKER.search(text, cursor):
        depth = 0
        escaped = False
        end = match.end() - 1
        for end in range(match.end() - 1, len(text)):
            char = text[end]
            if escaped:
                escaped = False
                continue
            if char == "\\":
                escaped = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    spans.append((match.start(), end + 1))
                    cursor = end + 1
                    break
        else:
            raise ValueError(f"Unclosed entry at offset {match.start()}")
    return spans


def entry_key(block: str) -> str:
    match = re.match(r"@[A-Za-z]+\s*\{\s*([^,]+),", block)
    if not match:
        raise ValueError(f"Cannot read entry key: {block[:80]!r}")
    return match.group(1).strip()


def set_field(block: str, name: str, value: str | None) -> str:
    pattern = re.compile(rf"(?m)^  {re.escape(name)}\s*=\s*\{{.*\}},\r?\n")
    match = pattern.search(block)
    if value is None:
        return pattern.sub("", block, count=1)
    replacement = f"  {name:<12} = {{{value}}},\n"
    if match:
        return block[: match.start()] + replacement + block[match.end() :]
    anchor = re.search(r"(?m)^  annotation\s*=", block)
    if not anchor:
        anchor = re.search(r"(?m)^  keywords\s*=", block)
    if not anchor:
        anchor = re.search(r"\n\}$", block)
    if not anchor:
        raise ValueError(f"Cannot insert {name} into {entry_key(block)}")
    return block[: anchor.start()] + replacement + block[anchor.start() :]


def normalize(source: Path) -> tuple[str, dict[str, int]]:
    text = source.read_text(encoding="utf-8")
    parsed = {entry.key: entry for entry in parse_bibtex(source)}
    chunks: list[str] = []
    cursor = 0
    changed_entries = 0
    langids_added = 0
    structural_entries = 0
    deleted_entries = 0
    for start, end in entry_spans(text):
        chunks.append(text[cursor:start])
        original = text[start:end]
        block = original
        key = entry_key(block)
        if key in DELETED_KEYS:
            deleted_entries += 1
            cursor = end
            continue
        entry = parsed[key]
        if "langid" not in entry.fields:
            language, _confidence = infer_language(entry)
            block = set_field(block, "langid", language)
            langids_added += 1
        type_update = MEDIEVAL_LAW_TYPE_UPDATES.get(key, TYPE_UPDATES.get(key))
        field_update = {
            **FIELD_UPDATES.get(key, {}),
            **MEDIEVAL_LAW_FIELD_UPDATES.get(key, {}),
            **STRICT_READINESS_UPDATES.get(key, {}),
        }
        if type_update:
            block = re.sub(r"^@[A-Za-z]+", f"@{type_update}", block, count=1)
        if field_update:
            for field, value in field_update.items():
                block = set_field(block, field, value)
            structural_entries += 1
        # An edited volume without a named author is a collection in BibLaTeX,
        # not a monograph.  This also removes false mandatory-author warnings.
        effective_editor = entry.fields.get("editor") or field_update.get("editor")
        effective_author = entry.fields.get("author") or field_update.get("author")
        target_type = type_update or entry.entry_type
        if target_type == "book" and effective_editor and not effective_author:
            block = re.sub(r"^@[A-Za-z]+", "@collection", block, count=1)
        if block != original:
            changed_entries += 1
        chunks.append(block)
        cursor = end
    chunks.append(text[cursor:])
    normalized = "".join(chunks).rstrip() + "\n"
    existing_keys = set(parsed) - DELETED_KEYS
    additional_blocks = []
    for start, end in entry_spans(ADDITIONAL_ENTRIES):
        block = ADDITIONAL_ENTRIES[start:end]
        if entry_key(block) not in existing_keys and entry_key(block) not in DELETED_KEYS:
            additional_blocks.append(block)
    if additional_blocks:
        normalized = normalized.rstrip() + "\n\n" + "\n\n".join(additional_blocks) + "\n"
    return normalized, {
        "changed_entries": changed_entries,
        "langids_added": langids_added,
        "structural_entries": structural_entries,
        "deleted_entries": deleted_entries,
        "added_entries": len(additional_blocks),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true", help="rewrite the canonical .bib file")
    args = parser.parse_args()
    normalized, stats = normalize(DEFAULT_BIB)
    if args.write:
        DEFAULT_BIB.write_text(normalized, encoding="utf-8")
    mode = "written" if args.write else "dry-run"
    print(f"{mode}: {stats}")


if __name__ == "__main__":
    main()
