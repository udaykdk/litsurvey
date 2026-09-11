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


def _params(extra):
    params = dict(extra)
    if CFG["openalex_mailto"]:
        params["mailto"] = CFG["openalex_mailto"]
    return urllib.parse.urlencode(params)


def work_by_doi(doi):
    """The OpenAlex work record for a DOI (its 'id' is the W... identifier)."""
    doi = doi.replace("DOI:", "").replace("https://doi.org/", "").strip()
    return http.get_json(f"{BASE}/works/doi:{urllib.parse.quote(doi, safe='/')}?" + _params({}))


_SORT = {"citations": "cited_by_count:desc", "year": "publication_date:desc", "relevance": "cited_by_count:desc"}


def citing(work_id, limit=20, sort="citations"):
    """Works that cite the given work, sorted server-side."""
    wid = work_id.rsplit("/", 1)[-1]
    data = http.get_json(f"{BASE}/works?" + _params({"filter": f"cites:{wid}", "sort": _SORT.get(sort, _SORT["citations"]),
                                                    "per-page": str(min(limit, 100))}))
    return [_map(w) for w in data.get("results", [])]


def works_by_ids(ids, limit=200):
    """Fetch work records for a list of W... ids (50 per request)."""
    ids = [r.rsplit("/", 1)[-1] for r in ids][:limit]
    out = []
    for i in range(0, len(ids), 50):
        chunk = "|".join(ids[i:i + 50])
        data = http.get_json(f"{BASE}/works?" + _params({"filter": f"openalex:{chunk}", "per-page": "50"}))
        out.extend(_map(w) for w in data.get("results", []))
    return out


def _sorted(out, sort, limit):
    key = (lambda p: p["year"] or 0) if sort == "year" else (lambda p: p["citations"])
    out.sort(key=key, reverse=True)
    return out[:limit]


def references(work, limit=20, sort="citations"):
    """Works the given work record cites (its referenced_works), sorted."""
    return _sorted(works_by_ids(work.get("referenced_works") or []), sort, limit)


def related(work, limit=20, sort="citations"):
    """OpenAlex's related_works for a work record (fallback for Semantic Scholar's
    recommender). The record itself is dropped if OpenAlex lists it."""
    own = (work.get("id") or "").rsplit("/", 1)[-1]
    ids = [r for r in (work.get("related_works") or []) if r.rsplit("/", 1)[-1] != own]
    self_doi = (work.get("doi") or "").replace("https://doi.org/", "").lower()
    out = [p for p in works_by_ids(ids) if not (self_doi and p["doi"].lower() == self_doi)]
    return _sorted(out, sort, limit)


def paper_by_doi(doi):
    return _map(work_by_doi(doi))
