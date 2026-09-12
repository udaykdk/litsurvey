"""Search across the sources and fuse the results."""
import sys

from .. import papers
from . import arxiv, crossref, europepmc, iacr, openalex, pubmed, semanticscholar

# name -> (search function, rank-fusion weight). The three big indexes carry full
# weight; single-portal sources carry half so a niche preprint does not outrank
# a well-cited paper merely by being first in its own short list.
SOURCES = {
    "openalex": (openalex.search, 1.0),
    "s2": (semanticscholar.search, 1.0),
    "arxiv": (arxiv.search, 1.0),
    "pubmed": (pubmed.search, 1.0),       # the authority for the life sciences
    "techrxiv": (crossref.portal("techrxiv"), 0.5),
    "researchsquare": (crossref.portal("researchsquare"), 0.5),
    "iacr": (iacr.search, 0.5),
    # off by default, each because it largely repeats a source already listed
    "europepmc": (europepmc.search, 0.7),  # PubMed's ground plus bioRxiv/medRxiv preprints
    "crossref": (crossref.search, 0.7),    # all DOI-registered works; overlaps OpenAlex
}
DEFAULT_SOURCES = ("openalex", "s2", "arxiv", "pubmed", "techrxiv", "researchsquare", "iacr")


def run_search(query, limit=20, year_from=None, sources=None):
    """Returns (papers, stats). stats = {source: hit count or 'error: ...'}."""
    names = [s for s in (sources or DEFAULT_SOURCES) if s in SOURCES]
    unknown = [s for s in (sources or ()) if s not in SOURCES]
    if unknown:
        raise ValueError(f"unknown source(s) {unknown}; choose from {list(SOURCES)}")
    lists, stats = [], {}
    for name in names:
        fn, weight = SOURCES[name]
        try:
            res = fn(query, limit=limit, year_from=year_from)
            lists.append((res, weight))
            stats[name] = len(res)
        except Exception as e:  # noqa: BLE001 - one source failing must not stop the rest
            stats[name] = f"error: {e}"
            print(f"[warn] {name} failed: {e}", file=sys.stderr)
    if not lists:
        raise RuntimeError("all search sources failed: " + "; ".join(
            f"{k} {v}" for k, v in stats.items()))
    return papers.merge(lists), stats
