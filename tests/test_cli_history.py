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
