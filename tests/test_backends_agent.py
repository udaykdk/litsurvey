import json
import sys

import pytest

from litsurvey import agent, backends, history, http

MSGS = [{"role": "system", "content": "sys"},
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "c1", "name": "search_papers", "args": {"query": "q1"}},
            {"id": "c2", "name": "get_related", "args": {"paper_id": "p"}}]},
        {"role": "tool", "tool_call_id": "c1", "name": "search_papers", "content": "[1]"},
        {"role": "tool", "tool_call_id": "c2", "name": "get_related", "content": "[2]"}]


def capture(monkeypatch, reply):
    seen = {}

    def post(url, payload, headers=None, timeout=900):
        seen["url"], seen["payload"], seen["headers"] = url, payload, headers
        return reply
    monkeypatch.setattr(http, "post_json", post)
    return seen


def test_openai_conversion_and_parse(monkeypatch):
    seen = capture(monkeypatch, {"choices": [{"message": {"content": None, "tool_calls": [
        {"id": "x", "function": {"name": "search_papers", "arguments": '{"query": "kan"}'}}]}}]})
    monkeypatch.setitem(backends.CFG, "openai_api_key", "sk")
    out = backends.chat("openai", "m", MSGS, tools=agent.TOOLS)
    p = seen["payload"]
    assert p["messages"][2]["tool_calls"][0]["function"]["arguments"] == '{"query": "q1"}'
    assert p["messages"][3] == {"role": "tool", "tool_call_id": "c1", "content": "[1]"}
    assert p["tools"][0]["type"] == "function"
    assert seen["headers"]["Authorization"] == "Bearer sk"
    assert out["tool_calls"] == [{"id": "x", "name": "search_papers", "args": {"query": "kan"}}]
    assert out["content"] == ""


def test_anthropic_groups_tool_results(monkeypatch):
    seen = capture(monkeypatch, {"content": [{"type": "text", "text": "report"},
                                             {"type": "tool_use", "id": "t1", "name": "read_paper",
                                              "input": {"arxiv_id": "1"}}]})
    monkeypatch.setitem(backends.CFG, "anthropic_api_key", "ak")
    out = backends.chat("anthropic", "m", MSGS, tools=agent.TOOLS)
    p = seen["payload"]
    assert p["system"] == "sys" and p["messages"][0]["role"] == "user"
    assert p["messages"][1]["content"][0]["type"] == "tool_use"
    results = p["messages"][2]["content"]
    assert p["messages"][2]["role"] == "user" and len(results) == 2
    assert results[1] == {"type": "tool_result", "tool_use_id": "c2", "content": "[2]"}
    assert p["tools"][0]["input_schema"]["type"] == "object"
    assert out == {"content": "report", "tool_calls": [{"id": "t1", "name": "read_paper",
                                                        "args": {"arxiv_id": "1"}}]}


def test_ollama_conversion(monkeypatch):
    seen = capture(monkeypatch, {"message": {"content": "", "tool_calls": [
        {"function": {"name": "get_citations", "arguments": {"paper_id": "z"}}}]}})
    out = backends.chat("ollama", "m", MSGS, tools=agent.TOOLS)
    p = seen["payload"]
    assert p["messages"][3] == {"role": "tool", "tool_name": "search_papers", "content": "[1]"}
    assert out["tool_calls"][0]["name"] == "get_citations" and out["tool_calls"][0]["args"] == {"paper_id": "z"}


def test_agent_loop_runs_tools_and_stops(monkeypatch):
    replies = iter([
        {"content": "", "tool_calls": [{"id": "a", "name": "search_papers", "args": {"query": "kan pinn"}},
                                       {"id": "b", "name": "read_paper", "args": {"arxiv_id": "9"}}]},
        {"content": "## Verdict\nfine", "tool_calls": []},
    ])
    monkeypatch.setattr(backends, "resolve", lambda b, m, o=None: ("ollama", "test-model"))
    monkeypatch.setattr(backends, "chat", lambda *a, **k: next(replies))
    monkeypatch.setattr(agent, "run_search", lambda q, **k: ([], {"openalex": 0, "s2": 0, "arxiv": 0}))
    monkeypatch.setattr(agent.arxiv, "full_text", lambda aid: (_ for _ in ()).throw(RuntimeError("no html")))
    lines = []
    res = agent.run("novelty", "claim", rounds=5, progress=lines.append)
    assert res["report"].startswith("## Verdict") and res["rounds_used"] == 2
    assert res["log"][0]["tool"] == "search_papers" and res["log"][0]["merged"] == 0
    assert res["log"][1]["error"] == "no html"
    assert any("search_papers" in ln for ln in lines)
    md = agent.search_log_markdown(res["log"], "ollama", "test-model")
    assert "| 1 |" in md and "kan pinn" in md and "error: no html" in md


def test_agent_round_limit_forces_report(monkeypatch):
    calls = {"n": 0}

    def chat(backend, model, messages, tools=None, options=None):
        calls["n"] += 1
        if tools:
            return {"content": "", "tool_calls": [{"id": "a", "name": "search_papers", "args": {"query": "x"}}]}
        assert messages[-1]["role"] == "user" and "Stop searching" in messages[-1]["content"]
        return {"content": "forced report", "tool_calls": []}
    monkeypatch.setattr(backends, "resolve", lambda b, m, o=None: ("ollama", "m"))
    monkeypatch.setattr(backends, "chat", chat)
    monkeypatch.setattr(agent, "run_search", lambda q, **k: ([], {}))
    res = agent.run("research", "q", rounds=2, progress=lambda s: None)
    assert res["report"] == "forced report" and calls["n"] == 3 and len(res["log"]) == 2


def test_resolve_errors_without_backend(monkeypatch):
    monkeypatch.setattr(backends, "ollama_models", lambda host=None: (_ for _ in ()).throw(ConnectionError()))
    monkeypatch.setattr(backends, "cli_tools_available", lambda: [])
    for k in ("backend", "openai_api_key", "anthropic_api_key"):
        monkeypatch.setitem(backends.CFG, k, "")
    monkeypatch.setitem(backends.CFG, "openai_base_url", "https://api.openai.com")
    try:
        backends.resolve()
        assert False
    except RuntimeError as e:
        assert "no LLM backend" in str(e)


def test_cli_backend_custom_command_and_search_log(monkeypatch, tmp_path):
    script = tmp_path / "fake_agent.py"
    script.write_text("import sys; p = sys.stdin.read(); print('## Verdict\\nfake report,', len(p), 'chars of prompt')")
    monkeypatch.setitem(backends.CFG, "cli_command", f"{sys.executable} {script}")
    monkeypatch.setitem(backends.CFG, "backend", "cli")
    monkeypatch.setitem(backends.CFG, "cli_tool", "custom")
    assert backends.resolve(None, None) == ("cli", "custom")
    real = backends.run_cli

    def run_and_record(tool, prompt, timeout=1800):   # the agent's own litsurvey calls get recorded
        assert "litsurvey search" in prompt and "Assess the novelty" in prompt
        history.record("search", {"text": "kan pinn"}, papers=[], stats={"s2": 0, "openalex": 3})
        history.record("cites", {"text": "DOI:10/x"}, papers=[{}])
        return real(tool, prompt, timeout)
    monkeypatch.setattr(backends, "run_cli", run_and_record)
    res = agent.run("novelty", "some claim", backend="cli", rounds=2, progress=lambda s: None)
    assert res["report"].startswith("## Verdict") and res["backend"] == "cli" and res["model"] == "custom"
    assert [e["tool"] for e in res["log"]] == ["search_papers", "get_citations"]
    assert res["log"][0]["args"] == {"query": "kan pinn"} and res["log"][0]["hits"] == {"s2": 0, "openalex": 3}
    assert res["log"][1]["args"] == {"paper_id": "DOI:10/x"} and res["log"][1]["merged"] == 1


def test_cli_backend_errors(monkeypatch):
    monkeypatch.setitem(backends.CFG, "cli_command", "")
    with pytest.raises(RuntimeError, match="cli_command"):
        backends.cli_command("custom")
    with pytest.raises(RuntimeError, match="unknown CLI tool"):
        backends.cli_command("nope")
    monkeypatch.setattr(backends.shutil, "which", lambda t: None)
    with pytest.raises(RuntimeError, match="not on PATH"):
        backends.cli_command("claude")
    monkeypatch.setitem(backends.CFG, "cli_command", f"{sys.executable} -c \"import sys; sys.exit(3)\"")
    with pytest.raises(RuntimeError, match="exited with code 3"):
        backends.run_cli("custom", "hi")


def test_openai_base_url_override_and_openrouter_headers(monkeypatch):
    seen = capture(monkeypatch, {"choices": [{"message": {"content": "hi"}}]})
    monkeypatch.setitem(backends.CFG, "openai_api_key", "sk-or-x")
    out = backends.chat("openai", "anthropic/claude-sonnet-4.5", MSGS[:2],
                        options={"base_url": "https://openrouter.ai/api/"})
    assert seen["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert seen["headers"]["X-Title"] == "litsurvey" and seen["headers"]["Authorization"] == "Bearer sk-or-x"
    assert out["content"] == "hi"


def test_hosted_openai_requires_a_model(monkeypatch):
    for k in ("model",):
        monkeypatch.setitem(backends.CFG, k, "")
    with pytest.raises(RuntimeError, match="pass --model"):
        backends.resolve("openai", None, {"base_url": "https://openrouter.ai/api"})
    monkeypatch.setattr(backends, "openai_models", lambda base=None: ["local-model"])
    assert backends.resolve("openai", None, {"base_url": "http://localhost:1234"}) == ("openai", "local-model")
