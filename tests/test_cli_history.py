import json

import pytest

from litsurvey import cli, export, history, ops
from litsurvey import papers as P


def fake_papers():
    return [P.make(title="Alpha", year=2020, authors=["A B"], doi="10/a", venue="V", sources=["s2"]),
            P.make(title="Beta", year=2021, authors=["C D"], arxiv="2101.1", venue="arXiv", sources=["arxiv"])]


def test_version_flag():
    with pytest.raises(SystemExit) as e:
        cli.main(["--version"])
    assert e.value.code == 0


def test_search_command_prints_saves_and_records(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(ops, "run_search", lambda q, **k: (fake_papers(), {"s2": 1, "arxiv": 1}))
    out = tmp_path / "r.bib"
    cli.main(["search", "alpha beta", "-n", "5", "--scholar", "--out", str(out)])
    captured = capsys.readouterr()
    assert "**Alpha**" in captured.out and "scholar.google.com" in captured.out
    assert out.read_text().startswith("@article{b2020alpha")
    runs = history.list_runs()
    assert len(runs) == 1 and runs[0]["mode"] == "search" and runs[0]["n_results"] == 2
    full = history.load(runs[0]["id"])
    assert full["papers"][1]["arxiv"] == "2101.1" and full["stats"] == {"s2": 1, "arxiv": 1}


def test_history_show_export_delete(monkeypatch, tmp_path, capsys):
    rid = history.record("search", {"text": "q"}, papers=fake_papers())
    cli.main(["history"])
    assert rid in capsys.readouterr().out
    cli.main(["history", "show", rid])
    assert "Beta" in capsys.readouterr().out
    out = tmp_path / "x.csv"
    cli.main(["history", "export", rid, "--out", str(out)])
    assert out.read_text().startswith("title,")
    cli.main(["history", "delete", rid])
    assert history.list_runs() == []


def test_agent_command_writes_report_and_log(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(ops.agent, "run", lambda kind, text, **k: {
        "report": "## Verdict\nok", "backend": "ollama", "model": "m", "rounds_used": 1,
        "log": [{"time": "2026-01-01 10:00:00", "tool": "search_papers",
                 "args": {"query": "kw"}, "hits": {"s2": 3}, "merged": 3}]})
    out = tmp_path / "rep.md"
    cli.main(["novelty", "some claim", "--out", str(out)])
    text = out.read_text()
    assert "## Verdict" in text and "## Search log" in text and "| kw |" in text
    side = json.loads((tmp_path / "rep.log.json").read_text())
    assert side["mode"] == "novelty" and side["log"][0]["args"]["query"] == "kw"
    assert history.list_runs()[0]["has_report"]


def test_unknown_mode_and_empty_text():
    with pytest.raises(ValueError):
        ops.run_mode("search", {"text": "  "})
    with pytest.raises(ValueError):
        ops.run_mode("nope", {"text": "x"})


def test_is_paper_id_and_canonical():
    assert P.is_paper_id("a68d501c2c1b292e558a7c80d34906b400f0c799")
    assert P.is_paper_id("DOI:10.1016/j.cma.2022.114823") and P.is_paper_id("10.1021/nl0731872")
    assert P.is_paper_id("ARXIV:2404.19756") and P.is_paper_id("2404.19756v2")
    assert not P.is_paper_id("Superior thermal conductivity of single-layer graphene")
    assert not P.is_paper_id("Balandin graphene 2008")
    assert P.canonical_id("10.1234/x") == "DOI:10.1234/x" and P.canonical_id("2404.19756v2") == "ARXIV:2404.19756"
    assert P.canonical_id("DOI:10.1234/x") == "DOI:10.1234/x"


def test_title_routes_through_search_and_offers_candidates(monkeypatch):
    cands = [P.make(title="Graphene Review", year=2010, doi="10/a", citations=50, sources=["s2"]),
             P.make(title="Graphene Thermal Conductivity", year=2008, doi="10/b", citations=900, sources=["s2"])]
    monkeypatch.setattr(ops, "run_search", lambda q, **k: (cands, {"s2": 2}))
    seen = {}
    monkeypatch.setattr(ops.semanticscholar, "linked", lambda pid, d, limit=20: seen.setdefault("id", pid) and [])
    res = ops.run_mode("cites", {"text": "graphene conductivity"})
    assert res["needs_choice"] and len(res["candidates"]) == 2
    assert "Graphene Review" in ops.candidates_text(res, "relevance")
    assert ops.sort_papers(cands, "citations")[0]["title"] == "Graphene Thermal Conductivity"
    # --pick takes a candidate without asking
    res = ops.run_mode("cites", {"text": "graphene conductivity", "pick": 2})
    assert seen["id"] == "DOI:10/b" and res["papers"] == []
    # an exact title match is taken automatically
    seen.clear()
    ops.run_mode("cites", {"text": "graphene review"})
    assert seen["id"] == "DOI:10/a"
    # open access needs a DOI
    cands[0]["doi"], cands[0]["arxiv"] = "", "1001.0001"
    with pytest.raises(ValueError, match="needs a DOI"):
        ops.run_mode("oa", {"text": "graphene review"})
    # a bare DOI still works as an id
    monkeypatch.setattr(ops.unpaywall, "lookup", lambda doi: {"doi": doi, "is_oa": False, "title": "", "pdf": "", "page": ""})
    assert ops.run_mode("oa", {"text": "10.1234/x"})["oa"]["doi"] == "10.1234/x"


def test_cli_non_tty_prints_candidates_and_exits_2(monkeypatch, capsys):
    cands = [P.make(title="A", year=2020, doi="10/a", sources=["s2"]),
             P.make(title="B", year=2021, doi="10/b", sources=["s2"])]
    monkeypatch.setattr(ops, "run_search", lambda q, **k: (cands, {"s2": 2}))
    import io
    monkeypatch.setattr("sys.stdin", io.StringIO(""))     # not a TTY
    with pytest.raises(SystemExit) as e:
        cli.main(["refs", "some title words"])
    assert e.value.code == 2
    err = capsys.readouterr().err
    assert "not a paper id" in err and "--pick N" in err and "id: DOI:10/b" in err


def test_linked_papers_prefers_openalex_and_falls_back(monkeypatch):
    monkeypatch.setattr(ops.openalex, "work_by_doi", lambda doi: {"id": "W9", "referenced_works": []})
    monkeypatch.setattr(ops.openalex, "citing", lambda wid, limit, sort: [P.make(title="via openalex", sources=["openalex"])])
    assert ops.linked_papers("cites", "DOI:10.1234/x", 5, "citations", lambda s: None)[0]["title"] == "via openalex"
    # no DOI -> Semantic Scholar
    monkeypatch.setattr(ops.semanticscholar, "paper", lambda pid: P.make(title="t", doi=""))
    monkeypatch.setattr(ops.semanticscholar, "linked", lambda pid, d, limit=20: [P.make(title="via s2", year=2020, citations=1), P.make(title="newer", year=2024, citations=0)])
    out = ops.linked_papers("cites", "abc", 5, "citations", lambda s: None)
    assert [p["title"] for p in out] == ["via s2", "newer"]
    assert ops.linked_papers("cites", "abc", 5, "year", lambda s: None)[0]["title"] == "newer"


def test_linked_papers_falls_back_when_openalex_is_empty(monkeypatch):
    monkeypatch.setattr(ops.openalex, "work_by_doi", lambda doi: {"id": "W9", "referenced_works": []})
    monkeypatch.setattr(ops.openalex, "references", lambda work, limit, sort: [])
    monkeypatch.setattr(ops.semanticscholar, "linked", lambda pid, d, limit=20: [P.make(title="from s2 refs")])
    notes = []
    out = ops.linked_papers("refs", "DOI:10.1234/x", 5, "citations", notes.append)
    assert out[0]["title"] == "from s2 refs" and any("trying Semantic Scholar" in n for n in notes)
