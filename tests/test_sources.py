from litsurvey import http
from litsurvey.sources import arxiv, openalex, semanticscholar, unpaywall
from litsurvey.sources import run_search

OA = {"results": [{
    "title": "Deep Thing", "publication_year": 2023, "cited_by_count": 12,
    "doi": "https://doi.org/10.5/deep", "ids": {"doi": "https://doi.org/10.5/deep"},
    "primary_location": {"source": {"display_name": "Nice Journal"},
                         "landing_page_url": "https://arxiv.org/abs/2301.12345"},
    "authorships": [{"author": {"display_name": "Ann Author"}}],
    "abstract_inverted_index": {"world": [1], "Hello": [0], "again": [2]}}]}

S2 = {"data": [{"paperId": "abc123", "title": "Deep Thing", "year": 2023, "venue": "Nice Journal",
                "citationCount": 15, "externalIds": {"DOI": "10.5/deep", "ArXiv": "2301.12345"},
                "authors": [{"name": "Ann Author"}], "abstract": "Hello world again",
                "url": "https://www.semanticscholar.org/paper/abc123"}]}

ARXIV_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
<entry><id>http://arxiv.org/abs/2301.12345v2</id><published>2023-01-30T00:00:00Z</published>
<title>Deep
  Thing</title><summary>Hello   world again</summary>
<author><name>Ann Author</name></author><arxiv:doi>10.5/deep</arxiv:doi></entry>
<entry><id>http://arxiv.org/abs/1901.00001v1</id><published>2019-01-01T00:00:00Z</published>
<title>Old</title><summary>s</summary><author><name>B</name></author></entry>
</feed>"""


def test_openalex_map(monkeypatch):
    monkeypatch.setattr(http, "get_json", lambda url, **k: OA)
    p = openalex.search("deep thing")[0]
    assert p["doi"] == "10.5/deep" and p["arxiv"] == "2301.12345"
    assert p["abstract"] == "Hello world again"
    assert p["venue"] == "Nice Journal" and p["sources"] == ["openalex"]


def test_s2_map_and_headers(monkeypatch):
    seen = {}

    def fake(url, headers=None, **k):
        seen["url"], seen["headers"] = url, headers
        return S2
    monkeypatch.setattr(http, "get_json", fake)
    monkeypatch.setitem(semanticscholar.CFG, "s2_api_key", "k123")
    p = semanticscholar.search("deep", year_from=2020)[0]
    assert p["s2_id"] == "abc123" and p["citations"] == 15
    assert seen["headers"] == {"x-api-key": "k123"} and "year=2020-" in seen["url"]


def test_s2_linked_and_related(monkeypatch):
    monkeypatch.setattr(http, "get_json", lambda url, **k:
                        {"data": [{"citingPaper": S2["data"][0]}, {"citingPaper": {}}]})
    out = semanticscholar.linked("DOI:10.5/deep", "citations")
    assert len(out) == 1 and out[0]["title"] == "Deep Thing"
    monkeypatch.setattr(http, "get_json", lambda url, **k: {"recommendedPapers": S2["data"]})
    assert semanticscholar.related("abc123")[0]["s2_id"] == "abc123"


def test_arxiv_parse_and_year_filter(monkeypatch):
    monkeypatch.setattr(http, "get", lambda url, **k: ARXIV_XML)
    out = arxiv.search("deep thing")
    assert len(out) == 2
    p = out[0]
    assert p["title"] == "Deep Thing" and p["arxiv"] == "2301.12345"
    assert p["doi"] == "10.5/deep" and p["abstract"] == "Hello world again"
    assert p["url"] == "https://arxiv.org/abs/2301.12345"
    assert len(arxiv.search("deep", year_from=2020)) == 1


def test_arxiv_full_text_strips_html(monkeypatch):
    body = ("<html><head><style>x{}</style><script>bad()</script></head><body>"
            "<h1>Title</h1><p>Body &amp; text</p>" + "<p>w</p>" * 2000 + "</body></html>").encode()
    monkeypatch.setattr(http, "get", lambda url, **k: body)
    txt = arxiv.full_text("ARXIV:2301.12345", max_chars=100)
    assert txt.startswith("Title Body & text") and "bad()" not in txt and len(txt) <= 100


def test_unpaywall(monkeypatch):
    monkeypatch.setattr(http, "get_json", lambda url, **k:
                        {"title": "T", "is_oa": True, "best_oa_location":
                         {"url_for_pdf": "https://x/p.pdf", "url": "https://x", "version": "publishedVersion"}})
    info = unpaywall.lookup("DOI:10.5/deep")
    assert info["pdf"] == "https://x/p.pdf" and info["doi"] == "10.5/deep"
    monkeypatch.setattr(http, "get_json", lambda url, **k: {"title": "T", "is_oa": False})
    assert unpaywall.lookup("10.5/deep")["pdf"] == ""


def test_run_search_merges_and_survives_a_failing_source(monkeypatch):
    def get_json(url, **k):
        if "openalex" in url:
            return OA
        if "semanticscholar" in url:
            return S2
        raise AssertionError(url)

    def get(url, **k):
        raise ConnectionError("arxiv down")
    monkeypatch.setattr(http, "get_json", get_json)
    monkeypatch.setattr(http, "get", get)
    plist, stats = run_search("deep thing")
    assert len(plist) == 1 and plist[0]["sources"] == ["openalex", "s2"]
    assert stats["openalex"] == 1 and stats["s2"] == 1 and stats["arxiv"].startswith("error")
