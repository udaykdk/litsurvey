"""Search across all sources and fuse the results."""
import sys

from .. import papers
from . import arxiv, openalex, semanticscholar

SOURCES = {"openalex": openalex.search, "s2": semanticscholar.search, "arxiv": arxiv.search}


def run_search(query, limit=20, year_from=None, sources=None):
    """Returns (papers, stats). stats = {source: hit count or 'error: ...'}."""
    names = [s for s in (sources or SOURCES) if s in SOURCES]
    lists, stats = [], {}
    for name in names:
        try:
            res = SOURCES[name](query, limit=limit, year_from=year_from)
            lists.append(res)
            stats[name] = len(res)
        except Exception as e:  # noqa: BLE001 - one source failing must not stop the rest
            stats[name] = f"error: {e}"
            print(f"[warn] {name} failed: {e}", file=sys.stderr)
    if not lists:
        raise RuntimeError("all search sources failed: " + "; ".join(
            f"{k} {v}" for k, v in stats.items()))
    return papers.merge(lists), stats
