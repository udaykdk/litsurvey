"""OpenAlex (https://openalex.org): no key needed; an email gives the faster polite pool."""
import re
import urllib.parse

from .. import http, papers
from ..config import CFG

BASE = "https://api.openalex.org"


def _abstract(inv):
    """OpenAlex returns abstracts as an inverted index; rebuild the text."""
    if not inv:
        return ""
    pos = {}
    for word, idxs in inv.items():
        for i in idxs:
            pos[i] = word
    return " ".join(pos[i] for i in sorted(pos))


def _map(w):
    loc = w.get("primary_location") or {}
    src = loc.get("source") or {}
    ids = w.get("ids") or {}
    landing = loc.get("landing_page_url") or ""
    arxiv = ""
    if "arxiv.org" in landing:
        m = re.search(r"(\d{4}\.\d{4,5})", landing)
        arxiv = m.group(1) if m else ""
    return papers.make(
        title=w.get("title") or "",
        year=w.get("publication_year"),
        venue=src.get("display_name") or "",
        authors=[a["author"]["display_name"] for a in (w.get("authorships") or [])[:12]
                 if a.get("author")],
        doi=w.get("doi") or "",
        arxiv=arxiv,
        citations=w.get("cited_by_count", 0),
        abstract=_abstract(w.get("abstract_inverted_index")),
        url=ids.get("doi") or landing or w.get("id") or "",
        sources=["openalex"],
    )


def search(query, limit=20, year_from=None):
    params = {"search": query, "per-page": str(limit)}
    if CFG["openalex_mailto"]:
        params["mailto"] = CFG["openalex_mailto"]
    if year_from:
        params["filter"] = f"from_publication_date:{year_from}-01-01"
    data = http.get_json(f"{BASE}/works?" + urllib.parse.urlencode(params))
    return [_map(w) for w in data.get("results", [])]
