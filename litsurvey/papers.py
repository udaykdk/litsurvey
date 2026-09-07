"""The paper record, de-duplication, rank fusion and text formatting."""
import re

FIELDS = ("title", "year", "venue", "authors", "doi", "arxiv", "s2_id",
          "citations", "abstract", "url", "sources")


def make(**kw):
    p = {"title": "", "year": None, "venue": "", "authors": [], "doi": "",
         "arxiv": "", "s2_id": "", "citations": 0, "abstract": "", "url": "",
         "sources": []}
    p.update({k: v for k, v in kw.items() if k in FIELDS})
    p["citations"] = int(p["citations"] or 0)
    p["doi"] = (p["doi"] or "").replace("https://doi.org/", "").strip()
    return p


def norm_title(t):
    return re.sub(r"[^a-z0-9]", "", (t or "").lower())[:80]


def key(p):
    if p.get("doi"):
        return "doi:" + p["doi"].lower()
    if p.get("arxiv"):
        return "arxiv:" + p["arxiv"].lower()
    return "title:" + norm_title(p.get("title"))


def best_id(p):
    """The identifier to pass to paper/cites/refs/related."""
    if p.get("s2_id"):
        return p["s2_id"]
    if p.get("doi"):
        return "DOI:" + p["doi"]
    if p.get("arxiv"):
        return "ARXIV:" + p["arxiv"]
    return ""


def merge(result_lists, k=60):
    """Dedupe across sources and fuse rankings with reciprocal rank fusion."""
    papers, scores = {}, {}
    for results in result_lists:
        for rank, p in enumerate(results):
            kk = key(p)
            if kk in papers:
                q = papers[kk]
                q["sources"] = sorted(set(q["sources"]) | set(p["sources"]))
                q["citations"] = max(q["citations"], p["citations"])
                for f in ("doi", "arxiv", "s2_id", "venue", "abstract", "url"):
                    if not q[f] and p.get(f):
                        q[f] = p[f]
                if len(p.get("authors") or []) > len(q["authors"]):
                    q["authors"] = p["authors"]
            else:
                papers[kk] = dict(p)
            scores[kk] = scores.get(kk, 0.0) + 1.0 / (k + rank)
    return [papers[kk] for kk in sorted(papers, key=lambda x: scores[x], reverse=True)]


def format_paper(p, i=None, snippet=0):
    head = f"{i}. " if i is not None else ""
    authors = ", ".join(p["authors"][:3]) + (" et al." if len(p["authors"]) > 3 else "")
    line = (f"{head}**{p['title']}** ({p['year']}) — {authors or 'unknown authors'}\n"
            f"   {p['venue'] or '?'} · {p['citations']} citations · "
            f"[{'+'.join(p['sources']) or '?'}] · id: `{best_id(p) or 'n/a'}`\n"
            f"   {p['url']}")
    if snippet and p["abstract"]:
        line += f"\n   > {p['abstract'][:snippet].strip()}…"
    return line


def compact(papers, n=8, abstract_chars=350):
    """Small dicts for feeding an LLM."""
    return [{"title": p["title"], "year": p["year"], "venue": p["venue"],
             "citations": p["citations"], "id": best_id(p),
             "doi": p["doi"], "arxiv": p["arxiv"],
             "abstract": (p["abstract"] or "")[:abstract_chars]} for p in papers[:n]]


def scholar_url(query):
    import urllib.parse
    return "https://scholar.google.com/scholar?q=" + urllib.parse.quote_plus(query)
