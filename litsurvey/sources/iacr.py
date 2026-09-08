"""IACR Cryptology ePrint Archive (https://eprint.iacr.org).

The archive has no search API (only OAI-PMH harvesting and RSS), so this reads
its server-rendered search page. The markup it relies on: an <a class="paperlink">
with the paper number, the title in <strong>, authors in <span class="fst-italic">,
and the abstract in <p class="search-abstract">. If IACR changes the page, this
source stops returning results and the other sources still work."""
import html as html_lib
import re
import urllib.parse

from .. import http, papers

BASE = "https://eprint.iacr.org"
_BLOCK = re.compile(
    r'class="paperlink"\s+href="/(\d{4})/(\d+)".*?<strong>(.*?)</strong>'
    r'(?:.*?<span class="fst-italic">(.*?)</span>)?'
    r'(?:.*?<p class="[^"]*search-abstract[^"]*">(.*?)</p>)?',
    re.S)


def _clean(s):
    return re.sub(r"\s+", " ", html_lib.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def parse(page, limit=20, year_from=None):
    out = []
    for m in _BLOCK.finditer(page):
        year, num, title, authors, abstract = m.groups()
        year = int(year)
        if year_from and year < year_from:
            continue
        out.append(papers.make(
            title=_clean(title), year=year, venue="IACR ePrint",
            authors=[a.strip() for a in _clean(authors).split(",") if a.strip()][:12],
            abstract=_clean(abstract),
            url=f"{BASE}/{year}/{num}", sources=["iacr"]))
        if len(out) >= limit:
            break
    return out


def search(query, limit=20, year_from=None):
    page = http.get(f"{BASE}/search?" + urllib.parse.urlencode({"q": query}), timeout=40)
    return parse(page.decode("utf-8", "replace"), limit=limit, year_from=year_from)
