from litsurvey import papers as P


def mk(**kw):
    return P.make(**kw)


def test_merge_dedupes_by_doi_and_fuses_sources():
    a = [mk(title="Paper One", doi="10.1/ONE", citations=5, sources=["openalex"]),
         mk(title="Only in A", doi="10.1/a", sources=["openalex"])]
    b = [mk(title="paper one (preprint)", doi="10.1/one", citations=9, sources=["s2"],
            s2_id="abc")]
    merged = P.merge([a, b])
    assert len(merged) == 2
    top = merged[0]
    assert top["doi"] == "10.1/ONE"
    assert top["sources"] == ["openalex", "s2"]
    assert top["citations"] == 9          # max across sources
    assert top["s2_id"] == "abc"          # filled from the other source


def test_merge_dedupes_by_arxiv_then_title():
    a = [mk(title="Same Title!", arxiv="2404.19756", sources=["arxiv"])]
    b = [mk(title="same title", arxiv="2404.19756", sources=["s2"])]
    c = [mk(title="No ids here", sources=["openalex"])]
    d = [mk(title="no ids HERE", sources=["s2"])]
    assert len(P.merge([a, b])) == 1
    assert len(P.merge([c, d])) == 1


def test_rrf_prefers_papers_ranked_high_in_more_sources():
    x, y = mk(title="X", doi="10/x"), mk(title="Y", doi="10/y")
    merged = P.merge([[x, y], [y, x], [y]])
    assert merged[0]["title"] == "Y"


def test_best_id_priority():
    assert P.best_id(mk(s2_id="h", doi="10/x", arxiv="1")) == "h"
    assert P.best_id(mk(doi="10/x", arxiv="1")) == "DOI:10/x"
    assert P.best_id(mk(arxiv="1")) == "ARXIV:1"
    assert P.best_id(mk()) == ""


def test_format_and_compact():
    p = mk(title="T", year=2020, authors=["A B", "C D", "E F", "G H"], venue="V",
           citations=3, abstract="x" * 500, sources=["s2"], s2_id="id1")
    txt = P.format_paper(p, 1, snippet=10)
    assert "et al." in txt and "id: `id1`" in txt
    c = P.compact([p])[0]
    assert len(c["abstract"]) == 350 and c["id"] == "id1"


def test_scholar_url():
    assert P.scholar_url("a b") == "https://scholar.google.com/scholar?q=a+b"


def test_throttle_uses_stamp_file(tmp_path, monkeypatch):
    import time
    from litsurvey import http
    monkeypatch.setattr(http, "DATA_DIR", str(tmp_path))
    monkeypatch.setitem(http.HOST_INTERVAL, "example.test", 0.3)
    http._throttle("example.test")
    t0 = time.monotonic()
    http._throttle("example.test")          # second call must wait ~0.3 s
    assert time.monotonic() - t0 >= 0.25
    assert (tmp_path / ".ratelimit-example.test").exists()


def test_normalize_input_converts_known_urls_and_rejects_others():
    import pytest
    n = P.normalize_input
    assert n("  keyword query ") == ("keyword query", "")
    assert n("https://doi.org/10.1016/j.cma.2022.114823")[0] == "DOI:10.1016/j.cma.2022.114823"
    assert n("http://dx.doi.org/10.1/x/")[0] == "DOI:10.1/x"
    assert n("https://arxiv.org/abs/2404.19756v3")[0] == "ARXIV:2404.19756"
    assert n("https://arxiv.org/pdf/2404.19756.pdf")[0] == "ARXIV:2404.19756"
    assert n("https://www.semanticscholar.org/paper/Some-Title/a68d501c2c1b292e558a7c80d34906b400f0c799")[0] \
        == "a68d501c2c1b292e558a7c80d34906b400f0c799"
    with pytest.raises(ValueError, match="copy the DOI"):
        n("https://ieeexplore.ieee.org/document/10772013")
    with pytest.raises(ValueError):
        n("www.example.com/paper")
