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


_ID_RES = (re.compile(r"^[0-9a-f]{40}$", re.I),                  # Semantic Scholar hash
           re.compile(r"^(DOI:)?10\.\d{4,9}/\S+$", re.I),         # DOI
           re.compile(r"^(ARXIV:)?\d{4}\.\d{4,5}(v\d+)?$", re.I),  # new-style arXiv id
           re.compile(r"^ARXIV:[a-z\-]+(\.[A-Z]{2})?/\d{7}$", re.I))  # old-style arXiv id


def is_paper_id(text):
    t = (text or "").strip()
    return any(r.match(t) for r in _ID_RES)


def canonical_id(text):
    """Add the DOI:/ARXIV: prefix Semantic Scholar expects when it is missing."""
    t = (text or "").strip()
    if re.match(r"^10\.\d{4,9}/", t):
        return "DOI:" + t
    if re.match(r"^\d{4}\.\d{4,5}(v\d+)?$", t):
        return "ARXIV:" + re.sub(r"v\d+$", "", t)
    return t


URL_RE = re.compile(r"^\s*(https?://|www\.)", re.I)
URL_HELP = ("URLs are not accepted. Use keywords for a search, or a paper id: "
            "DOI:10.xxxx/..., ARXIV:2404.19756, or a Semantic Scholar hash. "
            "For a publisher page (IEEE Xplore, Elsevier, Springer, ...) copy the DOI shown on that page.")


def clean_text(text):
    """Collapse newlines, tabs and repeated spaces (pasted titles often carry line
    breaks) and strip surrounding whitespace and stray quotes."""
    t = re.sub(r"\s+", " ", (text or "")).strip()
    return t.strip("\"'\u201c\u201d ").strip()


def normalize_input(text):
    """Clean whitespace; convert well-known paper URLs to ids; reject other URLs
    with guidance. Returns (text, note). note is '' when nothing changed."""
    t = clean_text(text)
    if not URL_RE.match(t):
        return t, ""
    m = re.search(r"doi\.org/(10\.[^\s?#]+)", t, re.I)
    if m:
        return "DOI:" + m.group(1).rstrip("/"), "converted DOI URL to " + "DOI:" + m.group(1).rstrip("/")
    m = re.search(r"arxiv\.org/(?:abs|pdf|html)/([\w.\-/]+?)(?:v\d+)?(?:\.pdf)?/?(?:[?#].*)?$", t, re.I)
    if m:
        return "ARXIV:" + m.group(1), "converted arXiv URL to ARXIV:" + m.group(1)
    m = re.search(r"semanticscholar\.org/paper/(?:[^/\s]+/)*([0-9a-f]{40})", t, re.I)
    if m:
        return m.group(1), "converted Semantic Scholar URL to its paper id"
    raise ValueError(URL_HELP)


def scholar_url(query):
    import urllib.parse
    return "https://scholar.google.com/scholar?q=" + urllib.parse.quote_plus(query)
