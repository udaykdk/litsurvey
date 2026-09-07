"""arXiv: search via the Atom API, full text via the HTML rendering."""
import html as html_lib
import re
import urllib.parse
import xml.etree.ElementTree as ET

from .. import http, papers

NS = {"a": "http://www.w3.org/2005/Atom"}
_BLOCK_RE = re.compile(r"<(script|style|math|svg|nav|header)[^>]*>.*?</\1>", re.S | re.I)


def search(query, limit=20, year_from=None):
    q = f'all:"{query}"' if " " in query else f"all:{query}"
    params = {"search_query": q, "max_results": str(limit), "sortBy": "relevance"}
    raw = http.get("http://export.arxiv.org/api/query?" + urllib.parse.urlencode(params))
    root = ET.fromstring(raw)
    out = []
    for e in root.findall("a:entry", NS):
        aid = e.findtext("a:id", "", NS) or ""
        m = re.search(r"abs/([\w.\-/]+?)(v\d+)?$", aid)
        arxiv_id = m.group(1) if m else ""
        pub = e.findtext("a:published", "", NS)
        year = int(pub[:4]) if pub[:4].isdigit() else None
        if year_from and year and year < year_from:
            continue
        doi = e.findtext("{http://arxiv.org/schemas/atom}doi", "") or ""
        out.append(papers.make(
            title=re.sub(r"\s+", " ", e.findtext("a:title", "", NS)).strip(),
            year=year, venue="arXiv",
            authors=[a.findtext("a:name", "", NS) for a in e.findall("a:author", NS)][:12],
            doi=doi, arxiv=arxiv_id,
            abstract=re.sub(r"\s+", " ", e.findtext("a:summary", "", NS)).strip(),
            url=f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id else aid,
            sources=["arxiv"],
        ))
    return out


def strip_html(raw):
    txt = _BLOCK_RE.sub(" ", raw)
    txt = re.sub(r"<[^>]+>", " ", txt)
    return re.sub(r"\s+", " ", html_lib.unescape(txt)).strip()


def full_text(arxiv_id, max_chars=40000):
    """Plain text of a paper from arxiv.org/html (native) or ar5iv (fallback)."""
    aid = re.sub(r"(?i)^arxiv:", "", arxiv_id.strip())
    last = None
    for base in (f"https://arxiv.org/html/{aid}", f"https://ar5iv.labs.arxiv.org/html/{aid}"):
        try:
            txt = strip_html(http.get(base, timeout=60).decode("utf-8", "replace"))
            if len(txt) > 2000:
                return txt[:max_chars]
        except Exception as e:  # noqa: BLE001 - try the next mirror
            last = e
    raise RuntimeError(f"no HTML full text for arXiv:{aid} ({last})")
