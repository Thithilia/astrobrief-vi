"""The deliberately bounded journal registry (metadata feeds are free)."""

from __future__ import annotations

JOURNALS = (
    {
        "id": "aa",
        "name": "Astronomy & Astrophysics",
        "short": "A&A",
        "issn": "0004-6361",
        "feed": "https://feeds.feedburner.com/edp_aa?format=xml",
        "url": "https://www.aanda.org/",
    },
    {
        "id": "apj",
        "name": "The Astrophysical Journal",
        "short": "ApJ",
        "issn": "0004-637X",
        "feed": "https://iopscience.iop.org/journal/rss/0004-637X",
        "url": "https://journals.aas.org/astrophysical-journal/",
    },
    {
        "id": "apjl",
        "name": "The Astrophysical Journal Letters",
        "short": "ApJL",
        "issn": "2041-8205",
        "feed": "https://iopscience.iop.org/journal/rss/2041-8205",
        "url": "https://journals.aas.org/astrophysical-journal-letters/",
    },
    {
        "id": "apjs",
        "name": "The Astrophysical Journal Supplement Series",
        "short": "ApJS",
        "issn": "0067-0049",
        "feed": "https://iopscience.iop.org/journal/rss/0067-0049",
        "url": "https://journals.aas.org/astrophysical-supplement-series/",
    },
    {
        "id": "aj",
        "name": "The Astronomical Journal",
        "short": "AJ",
        "issn": "1538-3881",
        "feed": "https://iopscience.iop.org/journal/rss/1538-3881",
        "url": "https://journals.aas.org/astronomical-journal/",
    },
    {
        "id": "mnras",
        "name": "Monthly Notices of the Royal Astronomical Society",
        "short": "MNRAS",
        "issn": "0035-8711",
        "feed": "https://academic.oup.com/rss/site_5326/advanceAccess_3192.xml",
        "url": "https://academic.oup.com/mnras",
    },
)

BY_ID = {journal["id"]: journal for journal in JOURNALS}

TOPICS = {
    "stars": "Sao và môi trường liên sao",
    "galaxies": "Thiên hà và nhân thiên hà",
    "planets": "Hành tinh và hệ hành tinh",
    "cosmology": "Vũ trụ học",
    "compact": "Thiên thể đặc và năng lượng cao",
    "solar": "Mặt Trời và Hệ Mặt Trời",
    "methods": "Phương pháp và thiết bị",
    "other": "Các chủ đề khác",
}
