import pytest

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
    c = [mk(title="No ids here", year=2021, sources=["openalex"])]
    d = [mk(title="no ids HERE", year=2021, sources=["s2"])]
    assert len(P.merge([a, b])) == 1
    assert len(P.merge([c, d])) == 1
    # a short title with no id and no year identifies nothing: kept apart
    assert len(P.merge([[mk(title="Editorial", sources=["a"])], [mk(title="Editorial", sources=["b"])]])) == 2


def test_rrf_prefers_papers_ranked_high_in_more_sources():
    x, y = mk(title="X", doi="10/x"), mk(title="Y", doi="10/y")
    merged = P.merge([[x, y], [y, x], [y]])
    assert merged[0]["title"] == "Y"


def test_best_id_priority():
    assert P.best_id(mk(s2_id="h", doi="10/x", arxiv="1")) == "DOI:10/x"
    assert P.best_id(mk(s2_id="h", arxiv="1")) == "ARXIV:1"
    assert P.best_id(mk(s2_id="h")) == "h"
    assert P.best_id(mk()) == ""


def test_format_and_compact():
    p = mk(title="T", year=2020, authors=["A B", "C D", "E F", "G H"], venue="V",
           citations=3, abstract="x" * 500, sources=["s2"], s2_id="id1")
    txt = P.format_paper(p, 1, snippet=10)
    assert "et al." in txt and "id: `id1`" in txt
    c = P.compact([p])[0]
    assert len(c["abstract"]) == 350 and c["id"] == "id1"   # no DOI/arXiv, so the hash


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


def test_clean_text_collapses_blank_lines_and_quotes():
    assert P.clean_text("Superior Thermal\n\n  Conductivity\r\n of\tGraphene\n") == "Superior Thermal Conductivity of Graphene"
    assert P.clean_text(' "Quoted Title" ') == "Quoted Title"
    assert P.normalize_input("https://doi.org/10.1234/x\n")[0] == "DOI:10.1234/x"


def test_merge_weights_keep_niche_portals_below_major_indexes():
    major = [mk(title="Major", doi="10/m")]
    niche = [mk(title="Niche", doi="10/n")]
    merged = P.merge([(major, 1.0), (niche, 0.5)])
    assert [p["title"] for p in merged] == ["Major", "Niche"]


def test_http_reporter_receives_current_host_and_retry_notes(monkeypatch):
    import urllib.error
    from litsurvey import http
    events = []
    http.set_reporter(lambda kind, text: events.append((kind, text)))
    monkeypatch.setattr(http.time, "sleep", lambda s: None)
    calls = {"n": 0}

    class Resp:
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def read(self): return b"ok"

    def urlopen(req, timeout=30):
        calls["n"] += 1
        if calls["n"] == 1:
            raise urllib.error.HTTPError(req.full_url, 429, "rate", {}, None)
        return Resp()
    monkeypatch.setattr(http.urllib.request, "urlopen", urlopen)
    assert http.get("https://api.semanticscholar.org/x") == b"ok"
    assert ("current", "Semantic Scholar") in events and ("current", "") in events
    assert any(k == "note" and "rate-limiting" in t for k, t in events)
    http.set_reporter(None)
    assert http.friendly("localhost:11434") == "the local model" and http.friendly("x.y") == "x.y"


def test_user_agent_sends_contact_only_to_arxiv(monkeypatch):
    from litsurvey import http
    monkeypatch.setitem(http.CFG, "openalex_mailto", "me@example.edu")
    for host in ("export.arxiv.org", "arxiv.org", "ar5iv.labs.arxiv.org"):
        assert "mailto:me@example.edu" in http.user_agent(host)
    for host in ("api.openai.com", "api.openalex.org", "api.crossref.org",
                  "eutils.ncbi.nlm.nih.gov", "api.unpaywall.org", "pypi.org", ""):
        assert "mailto:" not in http.user_agent(host)
    monkeypatch.setitem(http.CFG, "openalex_mailto", "")
    assert "mailto:" not in http.user_agent("export.arxiv.org")


def test_get_uses_the_host_specific_user_agent(monkeypatch):
    from litsurvey import http
    monkeypatch.setitem(http.CFG, "openalex_mailto", "me@example.edu")
    seen = []

    class Resp:
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def read(self): return b"ok"

    def urlopen(req, timeout=30):
        seen.append((req.full_url, req.get_header("User-agent")))
        return Resp()
    monkeypatch.setattr(http.urllib.request, "urlopen", urlopen)
    http.get("https://export.arxiv.org/api/query?x=1")
    http.get("https://api.openai.com/v1/models")
    assert "mailto:me@example.edu" in seen[0][1]
    assert "mailto:" not in seen[1][1]


def test_throttle_serialises_threads_per_host(tmp_path, monkeypatch):
    import threading
    import time
    from litsurvey import http as H
    monkeypatch.setattr(H, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(H, "ensure_data_dir", lambda: str(tmp_path))
    monkeypatch.setitem(H.HOST_INTERVAL, "slow.example", 0.3)
    monkeypatch.setattr(H, "_last_call", {})
    stamps = []

    def hit():
        H._throttle("slow.example")
        stamps.append(time.monotonic())
    threads = [threading.Thread(target=hit) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    stamps.sort()
    gaps = [b - a for a, b in zip(stamps, stamps[1:])]
    assert min(gaps) > 0.25          # never two requests inside one interval


def M(**kw):
    kw.setdefault("sources", ["x"])
    return P.make(**kw)


def test_non_latin_titles_are_not_merged_together():
    out = P.merge([[M(title="深度学习的研究"), M(title="Глубокое обучение")]])
    assert len(out) == 2


def test_short_generic_titles_need_the_same_year():
    out = P.merge([[M(title="Editorial", year=2019), M(title="Editorial", year=2023)]])
    assert len(out) == 2
    assert len(P.merge([[M(title="Editorial", year=2019)], [M(title="Editorial", year=2019)]])) == 1


def test_long_titles_merge_across_years():
    """A preprint (2024) and its journal version (2025) under the same title."""
    t = "Kolmogorov-Arnold networks for multi-fidelity regression"
    out = P.merge([[M(title=t, year=2024, arxiv="2410.14764")], [M(title=t, year=2025, doi="10.1088/2632-2153/adf702")]])
    assert len(out) == 1 and out[0]["doi"] and out[0]["arxiv"]


def test_arxiv_doi_meets_arxiv_id():
    out = P.merge([[M(title="KAN", arxiv="2404.19756v2")], [M(title="KAN: Kolmogorov", doi="10.48550/arXiv.2404.19756")]])
    assert len(out) == 1


@pytest.mark.parametrize("a,b", [
    ("10.36227/techrxiv.16610629.v7", "10.36227/techrxiv.16610629.v13"),
    ("10.36227/techrxiv.16610629", "10.36227/techrxiv.16610629.v1"),
    ("10.36227/techrxiv.176704133.32328897/v1", "10.36227/techrxiv.176704133.32328897/v2"),
    ("10.21203/rs.3.rs-4504342/v1", "10.21203/rs.3.rs-4504342/v4")])
def test_preprint_versions_merge(a, b):
    assert len(P.merge([[M(title="Version one", doi=a)], [M(title="Version two, renamed", doi=b)]])) == 1


def test_journal_dois_with_v_are_left_alone():
    out = P.merge([[M(title="A", doi="10.1000/abc.v1")], [M(title="B", doi="10.1000/abc.v2")]])
    assert len(out) == 2


def test_a_record_matching_two_papers_joins_them():
    t = "A sufficiently long and specific paper title for matching"
    out = P.merge([[M(title=t, year=2020), M(title="Other", doi="10.5555/x")],
                        [M(title=t, year=2020, doi="10.5555/x")]])
    assert len(out) == 1 and out[0]["doi"] == "10.5555/x"


def test_old_style_arxiv_ids_without_prefix():
    assert P.is_paper_id("hep-th/9901001") and P.is_paper_id("math.GT/0309136v2")
    assert P.canonical_id("hep-th/9901001v2") == "ARXIV:hep-th/9901001"


def test_run_ids_are_unique_within_a_second():
    from litsurvey import history
    ids = {history.new_id("search") for _ in range(200)}
    assert len(ids) > 190 and all(history.RUN_ID.match(i) for i in ids)


def test_same_title_different_dois_stay_apart():
    out = P.merge([[M(title="Editorial", year=2020, doi="10.1000/ed.1", authors=["A"])],
                   [M(title="Editorial", year=2020, doi="10.2000/ed.2", authors=["B"])]])
    assert len(out) == 2 and {p["doi"] for p in out} == {"10.1000/ed.1", "10.2000/ed.2"}


def test_long_titles_compare_in_full():
    stem = "A very long and detailed study of adaptive collocation in physics informed neural networks, part "
    out = P.merge([[M(title=stem + "one", year=2020)], [M(title=stem + "two", year=2020)]])
    assert len(out) == 2


def test_bridging_keeps_the_title():
    t = "Kolmogorov Arnold networks for operator learning in practice"
    out = P.merge([[M(title=t, arxiv="2501.00001")], [M(title="", doi="10.5555/k")],
                   [M(title="", doi="10.5555/k", arxiv="2501.00001")]])
    assert len(out) == 1 and out[0]["title"] == t


def test_a_year_learnt_while_merging_is_matched_again():
    out = P.merge([[M(title="KAN", year=2024, sources=["a"])],
                   [M(title="KAN", doi="10.5555/kan", sources=["b"])],
                   [M(title="KAN", year=2024, doi="10.5555/kan", sources=["c"])]])
    assert len(out) == 1


def test_preprint_and_journal_doi_with_the_same_title_merge():
    t = "Core temperature estimation of lithium-ion batteries using learned models"
    out = P.merge([[M(title=t, year=2025, doi="10.1109/TTE.2025.3559633")],
                   [M(title=t, year=2024, doi="10.36227/techrxiv.172468367.74530953/v1")]])
    assert len(out) == 1
