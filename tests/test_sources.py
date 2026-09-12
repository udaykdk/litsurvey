from litsurvey import http
import pytest

from litsurvey.sources import arxiv, crossref, europepmc, iacr, openalex
from litsurvey.sources import pubmed, semanticscholar, unpaywall
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
    plist, stats = run_search("deep thing", sources=["openalex", "s2", "arxiv"])
    assert len(plist) == 1 and plist[0]["sources"] == ["openalex", "s2"]
    assert stats["openalex"] == 1 and stats["s2"] == 1 and stats["arxiv"].startswith("error")
    import pytest
    with pytest.raises(ValueError, match="unknown source"):
        run_search("x", sources=["nope"])


def test_openalex_citing_and_references(monkeypatch):
    calls = []

    def get_json(url, **k):
        calls.append(url)
        if "/works/doi:" in url:
            return {"id": "https://openalex.org/W1", "referenced_works": ["https://openalex.org/W2", "https://openalex.org/W3"]}
        if "cites%3AW1" in url:
            assert "sort=cited_by_count%3Adesc" in url
            return OA
        if "openalex%3AW2%7CW3" in url:
            return {"results": [dict(OA["results"][0], cited_by_count=5), dict(OA["results"][0], cited_by_count=50, title="Big")]}
        raise AssertionError(url)
    monkeypatch.setattr(http, "get_json", get_json)
    w = openalex.work_by_doi("DOI:10.5/deep")
    assert w["id"].endswith("W1")
    assert openalex.citing(w["id"], limit=5)[0]["title"] == "Deep Thing"
    refs = openalex.references(w, limit=5)
    assert [p["title"] for p in refs] == ["Big", "Deep Thing"]     # most cited first


CR = {"message": {"items": [{
    "DOI": "10.36227/techrxiv.1.v1", "title": ["A TechRxiv Preprint"], "issued": {"date-parts": [[2025, 3, 1]]},
    "author": [{"given": "Ann", "family": "Author"}], "is-referenced-by-count": 4,
    "abstract": "<jats:p>Hello <i>world</i></jats:p>", "URL": "https://doi.org/10.36227/techrxiv.1.v1"}]}}


def test_crossref_portal_map_and_prefix_filter(monkeypatch):
    seen = {}
    monkeypatch.setattr(http, "get_json", lambda url, **k: seen.setdefault("url", url) and CR)
    p = crossref.portal("techrxiv")("neural", limit=5, year_from=2024)[0]
    assert "prefix%3A10.36227" in seen["url"] and "from-pub-date%3A2024-01-01" in seen["url"]
    assert p["title"] == "A TechRxiv Preprint" and p["year"] == 2025 and p["venue"] == "TechRxiv"
    assert p["authors"] == ["Ann Author"] and p["abstract"] == "Hello world" and p["sources"] == ["techrxiv"]
    assert p["doi"] == "10.36227/techrxiv.1.v1"


IACR_HTML = """<div class="mb-4"> <div class="d-flex"><a title="2026/1885" class="paperlink" href="/2026/1885">2026/1885</a>
<span class="ms-2"><a href="/2026/1885.pdf">(PDF)</a></span> <small class="ms-auto">Last updated: 2026-09-03</small> </div>
<div class="ms-md-4"> <div> <strong>Compact Lattice-Based NIZK Arguments &amp; Ring Signatures</strong>
<div class="mt-1"><span class="fst-italic">Nam Tran, Khoa Nguyen, Dongxi Liu</span></div> </div>
<p class="mb-0 mt-1 search-abstract">Zero-knowledge proofs of set membership underpin privacy-preserving constructions...</p> </div> </div>
<div class="mb-4"> <div class="d-flex"><a title="2019/12" class="paperlink" href="/2019/12">2019/12</a></div>
<div> <strong>Old Paper</strong> <div class="mt-1"><span class="fst-italic">Solo Author</span></div> </div>
<p class="search-abstract">old</p> </div>"""


def test_iacr_parse(monkeypatch):
    out = iacr.parse(IACR_HTML)
    assert len(out) == 2
    p = out[0]
    assert p["title"] == "Compact Lattice-Based NIZK Arguments & Ring Signatures" and p["year"] == 2026
    assert p["authors"] == ["Nam Tran", "Khoa Nguyen", "Dongxi Liu"] and p["url"] == "https://eprint.iacr.org/2026/1885"
    assert p["abstract"].startswith("Zero-knowledge") and p["venue"] == "IACR ePrint"
    assert len(iacr.parse(IACR_HTML, year_from=2020)) == 1
    monkeypatch.setattr(http, "get", lambda url, **k: IACR_HTML.encode())
    assert iacr.search("lattice", limit=1)[0]["year"] == 2026


PUBMED_IDS = {"esearchresult": {"idlist": ["40000001", "40000002"]}}

PUBMED_XML = b"""<?xml version="1.0"?>
<PubmedArticleSet>
<PubmedArticle><MedlineCitation><PMID>40000001</PMID><Article>
<Journal><ISOAbbreviation>Brief Bioinform</ISOAbbreviation>
<JournalIssue><PubDate><Year>2023</Year></PubDate></JournalIssue></Journal>
<ArticleTitle>A <i>CRISPR</i> method.</ArticleTitle>
<Abstract><AbstractText Label="BACKGROUND">We looked.</AbstractText>
<AbstractText Label="RESULTS">We found   things.</AbstractText></Abstract>
<AuthorList><Author><LastName>Zhang</LastName><ForeName>Guishan</ForeName></Author>
<Author><CollectiveName>The Group</CollectiveName></Author></AuthorList>
</Article></MedlineCitation>
<PubmedData><ArticleIdList><ArticleId IdType="pubmed">40000001</ArticleId>
<ArticleId IdType="doi">10.1093/bib/bbad333</ArticleId></ArticleIdList></PubmedData></PubmedArticle>
<PubmedArticle><MedlineCitation><PMID>40000002</PMID><Article>
<Journal><Title>Old Journal</Title>
<JournalIssue><PubDate><MedlineDate>2001 Spring</MedlineDate></PubDate></JournalIssue></Journal>
<ArticleTitle>An older paper</ArticleTitle></Article></MedlineCitation></PubmedArticle>
</PubmedArticleSet>"""


def test_pubmed_parse():
    out = pubmed.parse(PUBMED_XML)
    assert len(out) == 2
    p = out[0]
    assert p["title"] == "A CRISPR method"          # markup flattened, trailing dot dropped
    assert p["year"] == 2023 and p["venue"] == "Brief Bioinform"
    assert p["doi"] == "10.1093/bib/bbad333" and p["sources"] == ["pubmed"]
    assert p["authors"] == ["Guishan Zhang", "The Group"]
    assert p["abstract"] == "BACKGROUND: We looked. RESULTS: We found things."
    assert p["url"] == "https://pubmed.ncbi.nlm.nih.gov/40000001/"
    assert out[1]["year"] == 2001 and out[1]["venue"] == "Old Journal"   # MedlineDate fallback
    assert len(pubmed.parse(PUBMED_XML, year_from=2010)) == 1


def test_pubmed_search_two_calls(monkeypatch):
    seen = []
    monkeypatch.setattr(http, "get_json", lambda url, **k: seen.append(url) or PUBMED_IDS)
    monkeypatch.setattr(http, "get", lambda url, **k: seen.append(url) or PUBMED_XML)
    out = pubmed.search("crispr", limit=5, year_from=2010)
    assert len(out) == 1 and out[0]["year"] == 2023
    assert "esearch.fcgi" in seen[0] and "mindate=2010" in seen[0] and "tool=litsurvey" in seen[0]
    assert "efetch.fcgi" in seen[1] and "40000001%2C40000002" in seen[1]


def test_pubmed_search_no_hits(monkeypatch):
    monkeypatch.setattr(http, "get_json", lambda url, **k: {"esearchresult": {"idlist": []}})
    monkeypatch.setattr(http, "get", lambda url, **k: pytest.fail("efetch must not run"))
    assert pubmed.search("nothing at all") == []


EPMC = {"resultList": {"result": [
    {"id": "38199153", "source": "MED", "title": "A PINN  study.", "pubYear": "2024",
     "journalInfo": {"journal": {"title": "Neural Networks"}}, "doi": "10.5/pinn",
     "citedByCount": 7, "abstractText": "Hello\nworld",
     "authorList": {"author": [{"fullName": "Ann Author"}]}},
    {"id": "PPR1", "source": "PPR", "title": "A preprint", "pubYear": "notayear",
     "authorString": "Bob Beta, Cid Gamma"}]}}


def test_europepmc_parse():
    a, b = europepmc.parse(EPMC)
    assert a["title"] == "A PINN study" and a["year"] == 2024 and a["citations"] == 7
    assert a["venue"] == "Neural Networks" and a["doi"] == "10.5/pinn"
    assert a["abstract"] == "Hello world" and a["sources"] == ["europepmc"]
    assert a["url"] == "https://europepmc.org/article/MED/38199153"
    assert b["year"] is None and b["venue"] == "preprint"          # bad year, source label
    assert b["authors"] == ["Bob Beta", "Cid Gamma"]               # authorString fallback


def test_europepmc_year_filter_is_a_query_clause(monkeypatch):
    seen = {}

    def fake(url, **k):
        seen["url"] = url
        return EPMC
    monkeypatch.setattr(http, "get_json", fake)
    europepmc.search("pinn", limit=1, year_from=2022)
    assert "FIRST_PDATE" in seen["url"] and "2022-01-01" in seen["url"]
    assert "sort" not in seen["url"]        # relevance order is what rank fusion needs


PUBMED_BOOK_XML = b"""<?xml version="1.0"?>
<PubmedArticleSet>
<PubmedArticle><MedlineCitation><PMID>1</PMID><Article>
<Journal><ISOAbbreviation>J Test</ISOAbbreviation>
<JournalIssue><PubDate><Year>2020</Year></PubDate></JournalIssue></Journal>
<ArticleTitle>A journal article</ArticleTitle></Article></MedlineCitation></PubmedArticle>
<PubmedBookArticle><BookDocument><PMID>20301295</PMID>
<ArticleIdList><ArticleId IdType="bookaccession">NBK1116</ArticleId>
<ArticleId IdType="doi">10.5/book</ArticleId></ArticleIdList>
<Book><Publisher><PublisherName>University of Washington</PublisherName></Publisher>
<BookTitle>GeneReviews<sup>R</sup></BookTitle><PubDate><Year>1993</Year></PubDate>
<AuthorList><Author><LastName>Adam</LastName><ForeName>Margaret P</ForeName></Author></AuthorList></Book>
<Abstract><AbstractText>A book abstract.</AbstractText></Abstract>
</BookDocument></PubmedBookArticle>
</PubmedArticleSet>"""


def test_pubmed_parses_book_records_too():
    """efetch mixes PubmedArticle and PubmedBookArticle; dropping the second
    silently loses records that esearch already counted."""
    article, book = pubmed.parse(PUBMED_BOOK_XML)
    assert article["title"] == "A journal article" and article["year"] == 2020
    assert book["title"] == "GeneReviewsR" and book["year"] == 1993
    assert book["venue"] == "GeneReviewsR" and book["doi"] == "10.5/book"
    assert book["authors"] == ["Margaret P Adam"]
    assert book["abstract"] == "A book abstract."
    assert book["url"] == "https://pubmed.ncbi.nlm.nih.gov/20301295/"


def test_europepmc_blank_author_entries_fall_back_to_the_author_string():
    out = europepmc.parse({"resultList": {"result": [
        {"id": "1", "source": "MED", "title": "T", "pubYear": "2024",
         "authorList": {"author": [{}, {"fullName": "  "}]},
         "authorString": "Ann Author, Bob Beta"}]}})
    assert out[0]["authors"] == ["Ann Author", "Bob Beta"]
