"""Semantic Scholar Academic Graph API. Works without a key on a shared pool;
a free key (https://www.semanticscholar.org/product/api) gives 1 request/second."""
import urllib.parse

from .. import http, papers
from ..config import CFG

BASE = "https://api.semanticscholar.org/graph/v1"
REC_BASE = "https://api.semanticscholar.org/recommendations/v1"
FIELDS = "title,abstract,year,venue,authors,citationCount,externalIds,url,paperId"


def _headers():
    return {"x-api-key": CFG["s2_api_key"]} if CFG["s2_api_key"] else {}


def _map(p):
    ext = p.get("externalIds") or {}
    return papers.make(
        title=p.get("title") or "",
        year=p.get("year"),
        venue=p.get("venue") or "",
        authors=[a.get("name", "") for a in (p.get("authors") or [])[:12]],
        doi=ext.get("DOI", "") or "",
        arxiv=ext.get("ArXiv", "") or "",
        s2_id=p.get("paperId", "") or "",
        citations=p.get("citationCount", 0) or 0,
        abstract=p.get("abstract") or "",
        url=p.get("url") or "",
        sources=["s2"],
    )


def search(query, limit=20, year_from=None):
    params = {"query": query, "limit": str(limit), "fields": FIELDS}
    if year_from:
        params["year"] = f"{year_from}-"
    data = http.get_json(f"{BASE}/paper/search?" + urllib.parse.urlencode(params),
                         headers=_headers())
    return [_map(p) for p in data.get("data", [])]


def paper(paper_id):
    pid = urllib.parse.quote(paper_id, safe="")
    return _map(http.get_json(f"{BASE}/paper/{pid}?fields={FIELDS}", headers=_headers()))


def linked(paper_id, direction, limit=20):
    """direction: 'citations' (papers citing it) or 'references' (papers it cites)."""
    inner = "citingPaper" if direction == "citations" else "citedPaper"
    pid = urllib.parse.quote(paper_id, safe="")
    data = http.get_json(f"{BASE}/paper/{pid}/{direction}?limit={limit}&fields={FIELDS}",
                         headers=_headers())
    out = [_map(row.get(inner) or {}) for row in data.get("data", [])]
    out = [p for p in out if p["title"]]
    out.sort(key=lambda p: p["citations"], reverse=True)
    return out


def related(paper_id, limit=15):
    """Recommendation engine: papers similar to the given one."""
    pid = urllib.parse.quote(paper_id, safe="")
    data = http.get_json(f"{REC_BASE}/papers/forpaper/{pid}?limit={limit}&fields={FIELDS}",
                         headers=_headers())
    return [_map(p) for p in data.get("recommendedPapers", [])]
