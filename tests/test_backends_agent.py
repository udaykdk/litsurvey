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

    def run_and_record(tool, prompt, timeout=1800, agent_token=None):
        assert "litsurvey search" in prompt and "Assess the novelty" in prompt
        history.record("search", {"text": "typed by the user meanwhile"}, papers=[])
        monkeypatch.setenv("LITSURVEY_AGENT", agent_token)   # the agent's own calls carry the token
        history.record("search", {"text": "kan pinn"}, papers=[], stats={"s2": 0, "openalex": 3})
        history.record("cites", {"text": "DOI:10/x"}, papers=[{}])
        monkeypatch.delenv("LITSURVEY_AGENT")
        return real(tool, prompt, timeout, agent_token)
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


def test_openai_base_url_may_include_v1(monkeypatch):
    """A base URL that already ends in /v1 must not become /v1/v1/... (#404)."""
    seen = capture(monkeypatch, {"choices": [{"message": {"content": "hi"}}]})
    monkeypatch.setitem(backends.CFG, "openai_api_key", "sk-x")
    for base in ("https://api.goedelmachines.com/v1", "https://api.goedelmachines.com/v1/"):
        backends.chat("openai", "deepseek-v4.1-flash", MSGS[:2], options={"base_url": base})
        assert seen["url"] == "https://api.goedelmachines.com/v1/chat/completions"
    assert backends.openai_v1_url("https://api.openai.com", "/models") == \
        "https://api.openai.com/v1/models"
    assert backends.openai_v1_url("https://api.openai.com/v1", "/models") == \
        "https://api.openai.com/v1/models"


def test_openai_models_accepts_v1_base(monkeypatch):
    seen = {}

    def get_json(url, headers=None, timeout=5):
        seen["url"] = url
        return {"data": [{"id": "m"}]}
    monkeypatch.setattr(backends.http, "get_json", get_json)
    monkeypatch.setitem(backends.CFG, "openai_api_key", "")
    assert backends.openai_models("https://api.goedelmachines.com/v1") == ["m"]
    assert seen["url"] == "https://api.goedelmachines.com/v1/models"


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

AGY_HELP = """Usage of agy:
  --dangerously-skip-permissions  Auto-approve all tool permission requests without prompting
  --effort                        Reasoning effort for the current CLI session (low|medium|high)
  --model                         Model for the current CLI session
  --output-format                 Output format for print mode (text, json, stream-json) (default text)
  -p                              Short alias for --print
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
    assert backends.parse_choices(backends.help_block(AGY_HELP, "--effort")) == \
        ["low", "medium", "high"]
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


def test_probe_agy_picks_middle_effort(monkeypatch):
    _help(monkeypatch, AGY_HELP)
    got = backends.probe("agy")
    assert got["model"] == ""                  # agy does not advertise its models
    assert got["efforts"] == ["low", "medium", "high"]
    assert got["effort"] == "medium"           # middle of the range


def test_probe_survives_a_tool_that_says_nothing(monkeypatch):
    _help(monkeypatch, "")
    assert backends.probe("gemini") == {"model": "", "effort": "", "models": [], "efforts": []}
    assert backends.probe("claude")["model"] == ""        # no help text, no flag
    assert backends.probe("agy")["effort"] == "medium"    # falls back to known ladder


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
    assert use_stdin is True and "--full-auto" not in argv   # prompt on stdin, not in ps
    assert "--skip-git-repo-check" in argv
    assert argv[argv.index("--sandbox") + 1] == "workspace-write"
    assert "sandbox_workspace_write.network_access=true" in argv
    assert argv[argv.index("--add-dir") + 1] == backends.DATA_DIR
    assert "{datadir}" not in " ".join(argv)
    assert "model_reasoning_effort=high" in argv


def test_agy_argv_structure_and_effort(monkeypatch):
    _help(monkeypatch, AGY_HELP)
    monkeypatch.setattr(backends.shutil, "which", lambda t: "/usr/bin/" + t)
    for k in ("cli_model", "cli_effort"):
        monkeypatch.setitem(backends.CFG, k, "")
    argv, use_stdin = backends.cli_command("agy")
    assert use_stdin is False
    assert argv[:2] == ["agy", "--dangerously-skip-permissions"]
    assert argv[2:4] == ["--effort", "medium"]
    assert "--output-format" in argv
    assert "-p" in argv
    assert "{prompt}" in argv


def test_agy_with_configured_model_and_effort(monkeypatch):
    _help(monkeypatch, AGY_HELP)
    monkeypatch.setattr(backends.shutil, "which", lambda t: "/usr/bin/" + t)
    monkeypatch.setitem(backends.CFG, "cli_tool", "agy")
    monkeypatch.setitem(backends.CFG, "cli_model", "gemini-3.8-flash-high")
    monkeypatch.setitem(backends.CFG, "cli_effort", "high")
    argv, use_stdin = backends.cli_command("agy")
    assert argv[:6] == ["agy", "--dangerously-skip-permissions", "--model", "gemini-3.8-flash-high", "--effort", "high"]


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


def test_citation_check_flags_ids_the_searches_never_returned():
    log = [{"returned": ["DOI:10.1038/nature14539", "ARXIV:2404.19756"]},
           {"returned": ["DOI:10.36227/techrxiv.16610629.v7"]}]
    report = ("[1] LeCun, Nature, doi:10.1038/nature14539. [2] KAN, arXiv:2404.19756v3. "
              "[3] Self-Refine, https://doi.org/10.36227/techrxiv.16610629.v13 "
              "[4] Invented, 10.9999/made.up.2020.")
    unverified, n = agent.check_citations(report, log)
    assert n == 4 and unverified == ["10.9999/made.up.2020"]
    note = agent.citation_note(report, log)
    assert "1 of 4" in note and "10.9999/made.up.2020" in note
    assert "all 1" in agent.citation_note("see 10.1038/nature14539.", log)
    assert agent.citation_note("no identifiers here", log) == ""


def test_builtin_loop_logs_returned_ids_and_appends_the_check(monkeypatch):
    from litsurvey import papers as P
    replies = iter([{"content": "", "tool_calls": [{"id": "1", "name": "search_papers", "args": {"query": "kan"}}]},
                    {"content": "## Report\nSee 10.1234/real and 10.5678/fake.", "tool_calls": []}])
    monkeypatch.setattr(backends, "resolve", lambda *a: ("ollama", "m"))
    monkeypatch.setattr(backends, "chat", lambda *a, **k: next(replies))
    monkeypatch.setattr(agent, "run_search", lambda *a, **k: ([P.make(title="Real", doi="10.1234/real")], {"openalex": 1}))
    res = agent.run("novelty", "a claim", progress=lambda s: None)
    assert res["log"][0]["returned"] == ["DOI:10.1234/real"]
    assert "10.5678/fake" in res["report"].split("Citation check")[1]


def test_ollama_window_respects_a_larger_modelfile_setting(monkeypatch):
    monkeypatch.setattr(backends, "_OLLAMA_CTX", {})
    shown = {"big": {"parameters": "num_ctx                        131072\nstop <|im_end|>"},
             "plain": {"parameters": "temperature 0.6"}}
    monkeypatch.setattr(backends.http, "post_json", lambda url, payload, **k: shown[payload["model"]])
    assert backends.ollama_num_ctx("big") is None
    assert backends.ollama_num_ctx("plain") == backends.MIN_OLLAMA_CTX


def test_cut_off_replies_are_flagged(monkeypatch):
    monkeypatch.setattr(backends.http, "post_json", lambda *a, **k: {
        "content": [{"type": "text", "text": "A long survey that stops"}], "stop_reason": "max_tokens"})
    monkeypatch.setitem(backends.CFG, "anthropic_api_key", "x")
    out = backends.chat("anthropic", "m", [{"role": "user", "content": "q"}])
    assert out["content"].startswith("A long survey") and "length limit" in out["content"]
    monkeypatch.setattr(backends.http, "post_json", lambda *a, **k: {
        "choices": [{"message": {"content": "partial"}, "finish_reason": "length"}]})
    assert "length limit" in backends.chat("openai", "m", [{"role": "user", "content": "q"}],
                                           options={"base_url": "http://localhost:1"})["content"]


@pytest.mark.parametrize("text,expected_unverified", [
    ("Lancet, doi:10.1016/S0140-6736(20)30183-5.", []),            # brackets inside a DOI
    ("(see 10.1016/S0140-6736(20)30183-5)", []),                    # ...and around it
    ("**10.1038/nature14539**: deep learning", []),                 # Markdown bold, colon
    ("[link](https://doi.org/10.1038/nature14539)", []),
    ("10.1234/real(fake)", ["10.1234/real(fake)"]),                  # not the returned DOI
    ("https://arxiv.org/pdf/2501.12345v2", ["arxiv:2501.12345"]),    # pdf link, never returned
    ("https://arxiv.org/html/2404.19756v1", []),
])
def test_citation_check_parses_identifiers_as_written(text, expected_unverified):
    log = [{"returned": ["DOI:10.1016/S0140-6736(20)30183-5", "DOI:10.1038/nature14539",
                         "DOI:10.1234/real", "ARXIV:2404.19756"]}]
    unverified, n = agent.check_citations(text, log)
    assert n >= 1 and unverified == expected_unverified


def test_the_log_holds_exactly_the_papers_the_model_saw(monkeypatch):
    from litsurvey import papers as P
    plist = [P.make(title=f"P{i}", doi=f"10.5555/p{i}") for i in range(12)]
    monkeypatch.setattr(agent, "run_search", lambda *a, **k: (plist, {"openalex": 12}))
    log = []
    shown = agent.dispatch("search_papers", {"query": "x"}, log)
    assert len(log[0]["returned"]) == len(shown) == 8
    assert "DOI:10.5555/p9" not in log[0]["returned"]          # never shown, so not "returned"


def test_untagged_runs_are_not_counted_as_the_agents(monkeypatch):
    monkeypatch.setitem(backends.CFG, "cli_command", f"{sys.executable} -c \"print('report 10.1038/nature14539')\"")
    monkeypatch.setitem(backends.CFG, "backend", "cli")
    monkeypatch.setitem(backends.CFG, "cli_tool", "custom")
    real = backends.run_cli

    def user_searches_meanwhile(tool, prompt, timeout=1800, agent_token=None):
        history.record("search", {"text": "typed by hand"},
                       papers=[{"doi": "10.1038/nature14539", "arxiv": ""}])
        return real(tool, prompt, timeout, agent_token)
    monkeypatch.setattr(backends, "run_cli", user_searches_meanwhile)
    res = agent.run("novelty", "claim", backend="cli", progress=lambda s: None)
    assert res["log"] == [] and "did not appear" in res["report"]


@pytest.mark.parametrize("override,config,expected", [
    (None, "", 30), (None, "45", 45), (None, "0", 0), ("90", "45", 90), (0.5, "", 0.5)])
def test_agent_time_limit_comes_from_flag_then_config_then_default(monkeypatch, override, config, expected):
    monkeypatch.setitem(backends.CFG, "agent_timeout", config)
    assert backends.agent_minutes(override) == expected


@pytest.mark.parametrize("bad", ["ten", "-5"])
def test_a_bad_time_limit_is_reported(monkeypatch, bad):
    monkeypatch.setitem(backends.CFG, "agent_timeout", bad)
    with pytest.raises(ValueError, match="agent_timeout"):
        backends.agent_minutes()


def test_reply_wait_follows_the_run_limit():
    assert backends.reply_seconds(30) == 30 * 60
    assert backends.reply_seconds(5) == backends.REPLY_MINUTES * 60     # never below the floor
    assert backends.reply_seconds(0) is None                            # no limit at all


def test_a_cli_agent_that_overruns_is_stopped_and_its_searches_kept(monkeypatch):
    script = "import time; time.sleep(30); print('too late')"
    monkeypatch.setitem(backends.CFG, "cli_command", f"{sys.executable} -c \"{script}\"")
    monkeypatch.setitem(backends.CFG, "backend", "cli")
    monkeypatch.setitem(backends.CFG, "cli_tool", "custom")
    real = backends.run_cli
    seen = {}

    def agent_searches_then_hangs(tool, prompt, timeout=1800, agent_token=None):
        seen["timeout"] = timeout
        monkeypatch.setenv("LITSURVEY_AGENT", agent_token)
        history.record("search", {"text": "kan pinn"}, papers=[], stats={"openalex": 3})
        monkeypatch.delenv("LITSURVEY_AGENT")
        return real(tool, prompt, timeout, agent_token)
    monkeypatch.setattr(backends, "run_cli", agent_searches_then_hangs)
    res = agent.run("research", "a question", backend="cli", timeout=0.02, progress=lambda s: None)
    assert seen["timeout"] == pytest.approx(1.2)                  # 0.02 min
    assert res["incomplete"] is True and "did not finish in time" in res["report"]
    assert "--timeout" in res["report"] and "agent_timeout" in res["report"]
    assert [e["args"] for e in res["log"]] == [{"query": "kan pinn"}]   # the searches survive


def test_no_limit_means_no_subprocess_timeout(monkeypatch):
    seen = {}

    class Proc:
        returncode, stdout, stderr = 0, "report", ""

    def fake_run(argv, **kw):
        seen["timeout"] = kw.get("timeout")
        return Proc()
    monkeypatch.setattr(backends, "cli_command", lambda tool: (["x", "{prompt}"], False))
    monkeypatch.setattr(backends.subprocess, "run", fake_run)
    backends.run_cli("x", "task", timeout=None)
    assert seen["timeout"] is None


def test_builtin_loop_stops_searching_at_the_limit_and_still_reports(monkeypatch):
    clock = iter([0, 0, 10_000, 10_000, 10_000, 10_000, 10_000])
    monkeypatch.setattr(agent.time, "time", lambda: next(clock, 10_000))
    calls = []

    def fake_chat(backend, model, messages, tools=None, options=None):
        calls.append(options.get("reply_timeout"))
        if tools:
            return {"content": "", "tool_calls": [{"id": "1", "name": "search_papers", "args": {"query": "kan"}}]}
        return {"content": "## Report", "tool_calls": []}
    monkeypatch.setattr(backends, "resolve", lambda *a: ("ollama", "m"))
    monkeypatch.setattr(backends, "chat", fake_chat)
    monkeypatch.setattr(agent, "run_search", lambda *a, **k: ([], {}))
    res = agent.run("research", "q", rounds=8, timeout=1, progress=lambda s: None)
    assert res["time_limited"] is True and res["report"].startswith("## Report")
    assert "time limit" in res["report"] and len(res["log"]) == 1
    assert calls[0] == backends.REPLY_MINUTES * 60


def test_cli_exits_3_when_the_agent_produced_no_report(monkeypatch, capsys):
    from litsurvey import cli, ops
    monkeypatch.setattr(ops, "run_mode", lambda mode, params, progress=None:
                        {"report": "## No report", "log": [], "incomplete": True})
    with pytest.raises(SystemExit) as e:
        cli.main(["research", "q", "--timeout", "1"])
    assert e.value.code == 3 and "## No report" in capsys.readouterr().out
