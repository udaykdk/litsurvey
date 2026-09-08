"""Crossref (https://api.crossref.org): keyword search over DOI-registered works,
optionally restricted to a DOI prefix. Used for preprint portals that have no
search API of their own but register DOIs: TechRxiv (10.36227) and Research
Square (10.21203). No key; an email gets the polite pool."""
import re
import urllib.parse

from .. import http, papers
from ..config import CFG

BASE = "https://api.crossref.org/works"
PORTALS = {"techrxiv": ("10.36227", "TechRxiv"), "researchsquare": ("10.21203", "Research Square")}


def _map(item, label):
    issued = ((item.get("issued") or {}).get("date-parts") or [[None]])[0]
    abstract = re.sub(r"<[^>]+>", " ", item.get("abstract") or "")
    return papers.make(
        title=(item.get("title") or [""])[0],
        year=issued[0] if issued else None,
        venue=(item.get("container-title") or [label])[0] or label,
        authors=[" ".join(x for x in (a.get("given"), a.get("family")) if x)
                 for a in (item.get("author") or [])][:12],
        doi=item.get("DOI") or "",
        citations=item.get("is-referenced-by-count", 0) or 0,
        abstract=re.sub(r"\s+", " ", abstract).strip(),
        url=("https://doi.org/" + item["DOI"]) if item.get("DOI") else (item.get("URL") or ""),
        sources=[label.lower().replace(" ", "")],
    )


def search(query, limit=20, year_from=None, prefix=None, label="crossref"):
    params = {"query": query, "rows": str(min(limit, 100)),
              "select": "DOI,title,author,issued,container-title,abstract,is-referenced-by-count,URL"}
    filters = []
    if prefix:
        filters.append(f"prefix:{prefix}")
    if year_from:
        filters.append(f"from-pub-date:{year_from}-01-01")
    if filters:
        params["filter"] = ",".join(filters)
    if CFG["openalex_mailto"]:
        params["mailto"] = CFG["openalex_mailto"]
    data = http.get_json(BASE + "?" + urllib.parse.urlencode(params))
    return [_map(i, label) for i in (data.get("message") or {}).get("items", [])]


def portal(name):
    """A search function restricted to one preprint portal."""
    prefix, label = PORTALS[name]

    def fn(query, limit=20, year_from=None):
        return search(query, limit=limit, year_from=year_from, prefix=prefix, label=label)
    fn.__name__ = name
    return fn
