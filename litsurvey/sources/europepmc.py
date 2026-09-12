"""Europe PMC (https://europepmc.org/RestfulWebService).

Keyless. Covers the same life-science literature as PubMed and adds two things
PubMed does not give: citation counts, and preprints from bioRxiv, medRxiv and
Research Square. One request per search, against PubMed's two."""
import re
import urllib.parse

from .. import http, papers

BASE = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
# Europe PMC's own record ids; the "source" field says which collection a hit is in
SOURCE_LABEL = {"MED": "PubMed", "PPR": "preprint", "PMC": "PubMed Central",
                "AGR": "AGRICOLA", "PAT": "patent"}


def _map(r):
    journal = ((r.get("journalInfo") or {}).get("journal") or {}).get("title", "")
    venue = journal or r.get("journalTitle") or SOURCE_LABEL.get(r.get("source", ""), "")
    authors = [n for n in ((a.get("fullName") or "").strip() for a in
                           ((r.get("authorList") or {}).get("author") or [])) if n][:12]
    if not authors and r.get("authorString"):
        authors = [a.strip() for a in r["authorString"].split(",") if a.strip()][:12]
    src, rid = r.get("source", ""), r.get("id", "")
    return papers.make(
        title=re.sub(r"\s+", " ", r.get("title") or "").strip().rstrip("."),
        year=int(r["pubYear"]) if str(r.get("pubYear", "")).isdigit() else None,
        venue=venue,
        authors=authors,
        doi=r.get("doi") or "",
        citations=r.get("citedByCount", 0) or 0,
        abstract=re.sub(r"\s+", " ", r.get("abstractText") or "").strip(),
        url=(f"https://europepmc.org/article/{src}/{rid}" if src and rid
             else ("https://doi.org/" + r["doi"] if r.get("doi") else "")),
        sources=["europepmc"],
    )


def parse(data):
    return [_map(r) for r in ((data.get("resultList") or {}).get("result") or [])]


def search(query, limit=20, year_from=None):
    q = query
    if year_from:
        q = f"({query}) AND (FIRST_PDATE:[{year_from}-01-01 TO 3000-12-31])"
    # no sort parameter: Europe PMC's default is relevance, and the rank fusion
    # in papers.merge() needs each source's list in its own relevance order
    params = {"query": q, "format": "json", "pageSize": str(min(limit, 100)),
              "resultType": "core"}
    data = http.get_json(BASE + "?" + urllib.parse.urlencode(params))
    return parse(data)[:limit]
