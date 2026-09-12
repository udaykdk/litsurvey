import json
import os
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


def test_is_local_recognises_loopback_openai(monkeypatch):
    assert backends.is_local("ollama")
    assert backends.is_local("openai", "http://localhost:1234")
    assert backends.is_local("openai", "http://127.0.0.1:8000/")
    assert not backends.is_local("openai", "https://openrouter.ai/api")
    assert not backends.is_local("anthropic") and not backends.is_local("cli")
    monkeypatch.setitem(backends.CFG, "openai_base_url", "http://localhost:1234")
    assert backends.is_local("openai")


def test_split_command_keeps_windows_paths(monkeypatch):
    monkeypatch.setattr(backends.os, "name", "nt")
    assert backends.split_command(r'C:\Python\python.exe -c "import sys; sys.exit(3)" {prompt}') == \
        [r"C:\Python\python.exe", "-c", "import sys; sys.exit(3)", "{prompt}"]
    monkeypatch.setattr(backends.os, "name", "posix")
    assert backends.split_command('/usr/bin/python3 -c "import sys"') == ["/usr/bin/python3", "-c", "import sys"]


CLAUDE_HELP = """Usage: claude [options] [command] [prompt]

Options:
  --effort <level>                      Effort level for the current session
                                        (low, medium, high, xhigh, max)
  --model <model>                       Model for the current session. Provide
                                        an alias for the latest model (e.g.
                                        'fable', 'opus', or 'sonnet') or a
                                        model's full name (e.g.
                                        'claude-fable-5').
  -n, --name <name>                     Set a display name for this session
"""

CODEX_HELP = """Usage: codex exec [OPTIONS] [PROMPT]

Options:
  -m, --model <MODEL>
          Model the agent should use

  -s, --sandbox <SANDBOX_MODE>
          [possible values: read-only, workspace-write, danger-full-access]
"""


def _help(monkeypatch, text):
    monkeypatch.setattr(backends, "_HELP_CACHE", {})
    monkeypatch.setattr(backends, "cli_help", lambda tool, timeout=20: text)


def test_help_block_stops_at_the_next_option():
    block = backends.help_block(CLAUDE_HELP, "--model")
    assert "fable" in block and "sonnet" in block
    assert "display name" not in block          # did not run into the next option
    assert "Effort level" not in block          # did not run into the previous one


def test_parse_choices():
    assert backends.parse_choices(backends.help_block(CLAUDE_HELP, "--effort")) == \
        ["low", "medium", "high", "xhigh", "max"]
    assert backends.parse_choices(backends.help_block(CODEX_HELP, "--sandbox")) == \
        ["read-only", "workspace-write", "danger-full-access"]
    assert backends.parse_choices("no list here (single)") == []


def test_probe_claude_picks_second_model_and_middle_effort(monkeypatch):
    _help(monkeypatch, CLAUDE_HELP)
    got = backends.probe("claude")
    assert got["models"] == ["fable", "opus", "sonnet"]   # haiku is unknown to this build
    assert got["model"] == "opus"                         # one below the best
    assert got["efforts"] == ["low", "medium", "high", "xhigh", "max"]
    assert got["effort"] == "high"                        # middle of the range


def test_probe_codex_falls_back_to_the_known_ladder(monkeypatch):
    _help(monkeypatch, CODEX_HELP)
    got = backends.probe("codex")
    assert got["model"] == ""                  # codex does not advertise its models
    assert got["effort"] == "high" and "none" not in got["efforts"]


def test_probe_survives_a_tool_that_says_nothing(monkeypatch):
    _help(monkeypatch, "")
    assert backends.probe("gemini") == {"model": "", "effort": "", "models": [], "efforts": []}
    assert backends.probe("claude")["model"] == ""        # no help text, no flag


def test_cli_command_inserts_model_and_effort(monkeypatch):
    _help(monkeypatch, CLAUDE_HELP)
    monkeypatch.setattr(backends.shutil, "which", lambda t: "/usr/bin/" + t)
    for k in ("cli_model", "cli_effort"):
        monkeypatch.setitem(backends.CFG, k, "")
    argv, use_stdin = backends.cli_command("claude")
    assert use_stdin is True
    assert argv[:6] == ["claude", "-p", "--model", "opus", "--effort", "high"]
    assert "--allowedTools" in argv


def test_config_overrides_and_dash_means_tool_default(monkeypatch):
    _help(monkeypatch, CLAUDE_HELP)
    monkeypatch.setattr(backends.shutil, "which", lambda t: "/usr/bin/" + t)
    monkeypatch.setitem(backends.CFG, "cli_model", "sonnet")
    monkeypatch.setitem(backends.CFG, "cli_effort", "low")
    assert backends.cli_defaults("claude") == ("sonnet", "low")
    assert backends.cli_command("claude")[0][2:6] == ["--model", "sonnet", "--effort", "low"]
    monkeypatch.setitem(backends.CFG, "cli_model", "-")
    monkeypatch.setitem(backends.CFG, "cli_effort", "-")
    assert backends.cli_defaults("claude") == ("", "")
    assert "--model" not in backends.cli_command("claude")[0]


def test_codex_argv_keeps_the_sandbox_escapes(monkeypatch):
    """codex exec has no network, no history directory and refuses to start
    outside a git repository unless these are passed."""
    _help(monkeypatch, CODEX_HELP)
    monkeypatch.setattr(backends.shutil, "which", lambda t: "/usr/bin/" + t)
    for k in ("cli_model", "cli_effort"):
        monkeypatch.setitem(backends.CFG, k, "")
    argv, use_stdin = backends.cli_command("codex")
    assert use_stdin is False and "--full-auto" not in argv
    assert "--skip-git-repo-check" in argv
    assert argv[argv.index("--sandbox") + 1] == "workspace-write"
    assert "sandbox_workspace_write.network_access=true" in argv
    assert argv[argv.index("--add-dir") + 1] == backends.DATA_DIR
    assert "{datadir}" not in " ".join(argv)
    assert "model_reasoning_effort=high" in argv


def test_run_cli_prefers_the_output_file_over_stdout(monkeypatch, tmp_path):
    monkeypatch.setattr(backends, "cli_command",
                        lambda tool: (["x", "y", "-o", "{outfile}", "{prompt}"], False))

    class Proc:
        returncode = 0
        stdout = "progress chatter\ntokens used 123"
        stderr = ""

    def fake_run(argv, **kw):
        outfile = argv[argv.index("-o") + 1]
        assert "{outfile}" not in outfile and argv[-1] == "the task"
        with open(outfile, "w", encoding="utf-8") as f:
            f.write("  the real report  ")
        return Proc()
    monkeypatch.setattr(backends.subprocess, "run", fake_run)
    assert backends.run_cli("codex", "the task") == "the real report"


def test_run_cli_falls_back_to_stdout_when_the_file_is_empty(monkeypatch):
    monkeypatch.setattr(backends, "cli_command",
                        lambda tool: (["x", "y", "-o", "{outfile}", "{prompt}"], False))

    class Proc:
        returncode = 0
        stdout = "only on stdout"
        stderr = ""
    monkeypatch.setattr(backends.subprocess, "run", lambda argv, **kw: Proc())
    assert backends.run_cli("codex", "t") == "only on stdout"


def test_run_cli_cleans_up_the_output_file_when_the_tool_hangs(monkeypatch):
    seen = {}
    monkeypatch.setattr(backends, "cli_command",
                        lambda tool: (["x", "y", "-o", "{outfile}", "{prompt}"], False))

    def hang(argv, **kw):
        seen["outfile"] = argv[argv.index("-o") + 1]
        raise backends.subprocess.TimeoutExpired(argv, 1)
    monkeypatch.setattr(backends.subprocess, "run", hang)
    with pytest.raises(RuntimeError, match="did not finish"):
        backends.run_cli("codex", "t", timeout=1)
    assert not os.path.exists(seen["outfile"])          # no temp file left behind


def test_run_cli_cleans_up_when_the_tool_is_missing(monkeypatch):
    seen = {}

    def missing(argv, **kw):
        seen["outfile"] = argv[argv.index("-o") + 1]
        raise FileNotFoundError()
    monkeypatch.setattr(backends, "cli_command",
                        lambda tool: (["x", "y", "-o", "{outfile}", "{prompt}"], False))
    monkeypatch.setattr(backends.subprocess, "run", missing)
    with pytest.raises(RuntimeError, match="could not start"):
        backends.run_cli("codex", "t")
    assert not os.path.exists(seen["outfile"])


def test_custom_command_also_gets_the_data_directory(monkeypatch):
    monkeypatch.setitem(backends.CFG, "cli_command", "mytool --hist {datadir} -p {prompt}")
    argv, use_stdin = backends.cli_command("custom")
    assert use_stdin is False
    assert argv[argv.index("--hist") + 1] == backends.DATA_DIR


def test_a_stored_model_does_not_leak_to_another_tool(monkeypatch):
    """"opus" means nothing to codex, and codex rejects an unknown model."""
    _help(monkeypatch, CODEX_HELP)
    monkeypatch.setattr(backends.shutil, "which", lambda t: "/usr/bin/" + t)
    monkeypatch.delenv("LITSURVEY_CLI_MODEL", raising=False)
    monkeypatch.delenv("LITSURVEY_CLI_EFFORT", raising=False)
    monkeypatch.setitem(backends.CFG, "cli_tool", "claude")     # chosen for claude
    monkeypatch.setitem(backends.CFG, "cli_model", "opus")
    monkeypatch.setitem(backends.CFG, "cli_effort", "xhigh")
    assert backends.cli_defaults("codex") == ("", "high")       # probed, not inherited
    assert "opus" not in backends.cli_command("codex")[0]
    assert backends.cli_defaults("claude") == ("opus", "xhigh")  # its owner still gets it


def test_environment_overrides_apply_to_any_tool(monkeypatch):
    _help(monkeypatch, CODEX_HELP)
    monkeypatch.setattr(backends.shutil, "which", lambda t: "/usr/bin/" + t)
    monkeypatch.setitem(backends.CFG, "cli_tool", "claude")
    monkeypatch.setitem(backends.CFG, "cli_model", "opus")
    monkeypatch.setenv("LITSURVEY_CLI_MODEL", "gpt-5.6-sol")
    monkeypatch.setenv("LITSURVEY_CLI_EFFORT", "low")
    assert backends.cli_defaults("codex") == ("gpt-5.6-sol", "low")


def test_a_prompt_containing_outfile_is_not_rewritten(monkeypatch):
    monkeypatch.setattr(backends, "cli_command",
                        lambda tool: (["x", "y", "-o", "{outfile}", "{prompt}"], False))
    seen = {}

    class Proc:
        returncode = 0
        stdout = "ok"
        stderr = ""

    def fake_run(argv, **kw):
        seen["argv"] = list(argv)
        return Proc()
    monkeypatch.setattr(backends.subprocess, "run", fake_run)
    backends.run_cli("codex", "is novelty claimed for {outfile} designs?")
    assert seen["argv"][-1] == "is novelty claimed for {outfile} designs?"
    assert seen["argv"][3] != seen["argv"][-1]        # -o got a real path


def test_codex_runs_in_a_throwaway_working_directory(monkeypatch):
    _help(monkeypatch, CODEX_HELP)
    monkeypatch.setattr(backends.shutil, "which", lambda t: "/usr/bin/" + t)
    for k in ("cli_model", "cli_effort", "cli_tool"):
        monkeypatch.setitem(backends.CFG, k, "")
    seen = {}

    class Proc:
        returncode = 0
        stdout = "report"
        stderr = ""

    def fake_run(argv, **kw):
        seen["workdir"] = argv[argv.index("-C") + 1]
        assert os.path.isdir(seen["workdir"]) and not os.listdir(seen["workdir"])
        return Proc()
    monkeypatch.setattr(backends.subprocess, "run", fake_run)
    backends.run_cli("codex", "task")
    assert not os.path.exists(seen["workdir"])       # removed afterwards


def test_custom_commands_ignore_cli_model(monkeypatch):
    """litsurvey cannot know where a custom command line wants a model flag."""
    monkeypatch.setitem(backends.CFG, "cli_command", "mytool -p {prompt}")
    monkeypatch.setitem(backends.CFG, "cli_model", "opus")
    monkeypatch.setitem(backends.CFG, "cli_effort", "high")
    assert backends.cli_command("custom")[0] == ["mytool", "-p", "{prompt}"]
