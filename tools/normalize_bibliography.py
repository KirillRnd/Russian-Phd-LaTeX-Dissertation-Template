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

@book{korneeva-footnote-116b,
  title        = {Право в средневековом мире},
  editor       = {Варьяш, О. И. and Варьяш, И. И.},
  location     = {Санкт-Петербург},
  publisher    = {Алетейя},
  date         = {2001},
  langid       = {russian},
  keywords     = {footnote-only},
}

@book{korneeva-footnote-116c,
  title        = {Право в средневековом мире},
  editor       = {Варьяш, И. И. and Попова, Г. А.},
  location     = {Москва},
  publisher    = {ИВИ РАН},
  date         = {2007},
  langid       = {russian},
  keywords     = {footnote-only},
}

@book{korneeva-footnote-116d,
  title        = {Право в средневековом мире},
  editor       = {Варьяш, И. И. and Попова, Г. А.},
  location     = {Москва},
  publisher    = {ИВИ РАН},
  date         = {2008},
  langid       = {russian},
  keywords     = {footnote-only},
}

@book{korneeva-footnote-116e,
  title        = {Право в средневековом мире},
  editor       = {Варьяш, И. И. and Попова, Г. А.},
  location     = {Москва},
  publisher    = {ИВИ РАН},
  date         = {2009},
  langid       = {russian},
  keywords     = {footnote-only},
}

@book{korneeva-footnote-116f,
  title        = {Право в средневековом мире},
  editor       = {Попова, Г. А.},
  location     = {Москва},
  publisher    = {ИВИ РАН},
  date         = {2010},
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
        if key in TYPE_UPDATES:
            block = re.sub(r"^@[A-Za-z]+", f"@{TYPE_UPDATES[key]}", block, count=1)
        if key in FIELD_UPDATES:
            for field, value in FIELD_UPDATES[key].items():
                block = set_field(block, field, value)
            structural_entries += 1
        # An edited volume without a named author is a collection in BibLaTeX,
        # not a monograph.  This also removes false mandatory-author warnings.
        effective_editor = entry.fields.get("editor") or (FIELD_UPDATES.get(key, {}).get("editor"))
        effective_author = entry.fields.get("author") or (FIELD_UPDATES.get(key, {}).get("author"))
        target_type = TYPE_UPDATES.get(key, entry.entry_type)
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
