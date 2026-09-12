"""PubMed, through the NCBI E-utilities (https://www.ncbi.nlm.nih.gov/books/NBK25501/).

Two calls per search: esearch returns the matching PMIDs, efetch returns the
records. efetch is used rather than esummary because only it carries abstracts,
which the LLM agents need to judge relevance. No key needed; NCBI allows three
requests a second and asks for a tool name and an email address.

An efetch reply mixes two record shapes: `PubmedArticle` for journal articles
and `PubmedBookArticle` for books and book chapters (GeneReviews, NCBI
Bookshelf). They nest the same fields under different paths, so every field
below lists the places it can be found."""
import re
import urllib.parse
import xml.etree.ElementTree as ET

from .. import http, papers
from ..config import CFG

BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
TOOL = "litsurvey"
RECORDS = ("PubmedArticle", "PubmedBookArticle")

# field -> paths tried in order; the first non-empty one wins
PATHS = {
    "pmid": ("MedlineCitation/PMID", "BookDocument/PMID"),
    "title": ("MedlineCitation/Article/ArticleTitle",
              "BookDocument/ArticleTitle",              # a chapter
              "BookDocument/Book/BookTitle"),           # the whole book
    "venue": ("MedlineCitation/Article/Journal/ISOAbbreviation",
              "MedlineCitation/Article/Journal/Title",
              "BookDocument/Book/BookTitle",
              "BookDocument/Book/Publisher/PublisherName"),
    "year": ("MedlineCitation/Article/Journal/JournalIssue/PubDate/Year",
             "MedlineCitation/Article/Journal/JournalIssue/PubDate/MedlineDate",
             "BookDocument/Book/PubDate/Year",
             "PubmedData/History/PubMedPubDate/Year"),
}
AUTHOR_PATHS = ("MedlineCitation/Article/AuthorList/Author",
                "BookDocument/AuthorList/Author",
                "BookDocument/Book/AuthorList/Author")
ABSTRACT_PATHS = ("MedlineCitation/Article/Abstract/AbstractText",
                  "BookDocument/Abstract/AbstractText")
ID_LIST_PATHS = ("PubmedData/ArticleIdList/ArticleId",
                 "BookDocument/ArticleIdList/ArticleId")


def _text(node):
    """All text under a node, including the italics and sub/sup tags PubMed puts
    inside titles and abstracts."""
    if node is None:
        return ""
    return re.sub(r"\s+", " ", "".join(node.itertext())).strip()


def _first(record, field):
    for path in PATHS[field]:
        value = _text(record.find(path))
        if value:
            return value
    return ""


def _year(record):
    m = re.search(r"\b(1[89]\d\d|20\d\d)\b", _first(record, "year"))
    return int(m.group(1)) if m else None


def _authors(record):
    out = []
    for path in AUTHOR_PATHS:
        for a in record.findall(path):
            last, fore = _text(a.find("LastName")), _text(a.find("ForeName"))
            name = " ".join(x for x in (fore, last) if x) or _text(a.find("CollectiveName"))
            if name:
                out.append(name)
        if out:
            break
    return out[:12]


def _abstract(record):
    """Structured abstracts are split into labelled sections; join them."""
    parts = []
    for path in ABSTRACT_PATHS:
        for t in record.findall(path):
            label, body = (t.get("Label") or "").strip(), _text(t)
            if body:
                parts.append(f"{label}: {body}" if label else body)
        if parts:
            break
    return " ".join(parts)


def _doi(record):
    for path in ID_LIST_PATHS:
        for aid in record.findall(path):
            if aid.get("IdType") == "doi":
                return _text(aid)
    return ""


def parse(xml_bytes, year_from=None):
    root = ET.fromstring(xml_bytes)
    out = []
    for tag in RECORDS:
        for record in root.findall(tag):
            year = _year(record)
            if year_from and year and year < year_from:
                continue
            title = _first(record, "title").rstrip(".")
            if not title:
                continue
            pmid = _first(record, "pmid")
            out.append(papers.make(
                title=title, year=year, venue=_first(record, "venue"),
                authors=_authors(record), doi=_doi(record),
                abstract=_abstract(record),
                url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else "",
                sources=["pubmed"],
            ))
    return out


def _common():
    params = {"db": "pubmed", "tool": TOOL}
    if CFG["openalex_mailto"]:
        params["email"] = CFG["openalex_mailto"]
    return params


def search(query, limit=20, year_from=None):
    params = _common()
    params.update({"term": query, "retmax": str(min(limit, 100)),
                   "retmode": "json", "sort": "relevance"})
    if year_from:
        params.update({"datetype": "pdat", "mindate": str(year_from), "maxdate": "3000"})
    data = http.get_json(f"{BASE}/esearch.fcgi?" + urllib.parse.urlencode(params))
    ids = ((data.get("esearchresult") or {}).get("idlist") or [])[:limit]
    if not ids:
        return []
    fetch = _common()
    fetch.update({"id": ",".join(ids), "retmode": "xml"})
    return parse(http.get(f"{BASE}/efetch.fcgi?" + urllib.parse.urlencode(fetch)), year_from)
