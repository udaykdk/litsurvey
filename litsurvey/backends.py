"""LLM backends behind one small interface.

Neutral transcript format used by the agent:
  {"role": "system"|"user", "content": str}
  {"role": "assistant", "content": str, "tool_calls": [{"id", "name", "args"}]}
  {"role": "tool", "tool_call_id": str, "name": str, "content": str}
Neutral tool format: {"name", "description", "parameters"} (JSON schema).

chat() returns {"content": str, "tool_calls": [{"id", "name", "args"}]}.
"""
import ipaddress
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
import uuid

from . import http
from .config import CFG, DATA_DIR, ensure_data_dir

BACKENDS = ("cli", "ollama", "openai", "anthropic")
LOCAL_BACKENDS = ("ollama",)   # data never leaves the machine


def is_loopback_url(url):
    """True only when the URL's host is this machine. The host name is parsed and
    compared exactly: a substring test would call https://localhost.evil.com or
    https://api.evil.com/?x=127.0.0.1 local, and the banner would then tell the
    user a cloud run stays on the machine."""
    raw = (url or "").strip()
    if "://" not in raw:
        raw = "http://" + raw
    try:
        host = (urllib.parse.urlsplit(raw).hostname or "").lower()
    except ValueError:
        return False
    if host in ("localhost", "::1", "0.0.0.0") or host.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def is_local(backend, base_url=None):
    """True when the model runs on this machine: Ollama, or an OpenAI-compatible
    server on a loopback address (LM Studio, vLLM, llama.cpp)."""
    if backend in LOCAL_BACKENDS:
        return True
    if backend == "openai":
        return is_loopback_url(base_url or CFG["openai_base_url"])
    return False


def openai_v1_url(base, path):
    """Join a configured OpenAI-compatible base URL with a /v1 API path.

    The base may be given with or without the trailing version segment
    (https://api.openai.com and https://api.openai.com/v1 are both valid), so the
    segment is added only when it is not already present. Without this a base
    that already ends in /v1 would produce /v1/v1/... and a 404."""
    base = (base or "").rstrip("/")
    if base.endswith("/v1"):
        base = base[:-len("/v1")].rstrip("/")
    return base + "/v1" + path

# Subscription command-line agents. Each is run non-interactively with the task as
# its prompt; it uses the `litsurvey` command itself as its search tool.
#
# Placeholders substituted in cli_command()/run_cli():
#   {prompt}   the task text (tools with "stdin": True get it on stdin instead)
#   {datadir}  ~/.litsurvey, so a sandboxed agent may write the run history
#   {workdir}  an empty temporary directory used as the agent's working root,
#              so a write sandbox scoped to "the workspace" cannot reach the
#              user's files
#   {outfile}  a temporary file the tool writes its final message to; preferred
#              over stdout, which also carries progress and tool-call chatter
#
# "models" is a capability ordering, highest first. A tool's --help says which
# names the installed build knows but never ranks them, so the ranking lives
# here; an empty tuple means "do not pass a model, use the tool's own default".
# "efforts" is a fallback ladder, lowest first, for tools whose --help does not
# enumerate the levels. See probe() for how a default is picked from these.
CLI_TOOLS = {
    "claude": {"label": "Claude Code (Claude Pro / Max subscription)",
               # --tools Bash leaves the shell as the only built-in tool, so Read,
               # Grep and Glob (allowed without asking by default) are not there
               # for a hostile abstract to use; the shell is limited to litsurvey.
               "argv": ["claude", "-p", "--output-format", "text", "--tools", "Bash",
                        "--allowedTools", ",".join(f"Bash(litsurvey {c}:*)" for c in
                                                   ("search", "paper", "cites", "refs", "related"))],
               "stdin": True,
               "model_flag": ("--model", "{v}"), "effort_flag": ("--effort", "{v}"),
               "models": ("fable", "opus", "sonnet", "haiku"), "efforts": ()},
    # codex exec sandboxes the commands it runs: without these it has no network
    # (so every litsurvey call returns nothing), refuses to start outside a git
    # repository, and cannot write the run history under ~/.litsurvey.
    "codex": {"label": "Codex CLI (ChatGPT subscription)",
              "argv": ["codex", "exec", "--skip-git-repo-check", "-C", "{workdir}",
                       "--sandbox", "workspace-write", "--add-dir", "{datadir}",
                       "-c", "sandbox_workspace_write.network_access=true",
                       # "-": read the prompt from stdin, so the claim is not visible
                       # to other accounts in the process list
                       "-o", "{outfile}", "-"], "stdin": True,
              "model_flag": ("-m", "{v}"), "effort_flag": ("-c", "model_reasoning_effort={v}"),
              "models": (),
              "efforts": ("minimal", "low", "medium", "high", "xhigh", "max")},
    "agy": {"label": "Antigravity CLI (Google account)",
            "argv": ["agy", "--dangerously-skip-permissions", "--output-format", "text", "-p", "{prompt}"], "stdin": False,
            "model_flag": ("--model", "{v}"), "effort_flag": ("--effort", "{v}"),
            "models": (),
            "efforts": ("low", "medium", "high")},
    "gemini": {"label": "Gemini CLI (Google account)",
               "argv": ["gemini", "--yolo", "-o", "text", "-p", "{prompt}"], "stdin": False,
               "model_flag": ("-m", "{v}"), "effort_flag": None,
               "models": (), "efforts": ()},
}


# ------------------------------------------------------------- time limits

DEFAULT_AGENT_MINUTES = 30   # a whole novelty/research run
REPLY_MINUTES = 15           # floor for one model reply (Ollama / API key backends)


class AgentTimeout(RuntimeError):
    """A subscription CLI agent was stopped at the time limit."""


def agent_minutes(override=None):
    """Minutes an agent run may take: the --timeout given for this run, else
    agent_timeout from the config or LITSURVEY_AGENT_TIMEOUT, else 30.
    0 means no limit."""
    raw = override if override not in (None, "") else CFG.get("agent_timeout")
    if raw in (None, ""):
        return DEFAULT_AGENT_MINUTES
    try:
        minutes = float(raw)
    except (TypeError, ValueError):
        raise ValueError(f"agent_timeout must be a number of minutes (0 for no limit), "
                         f"not {raw!r}") from None
    if minutes < 0:
        raise ValueError("agent_timeout cannot be negative; use 0 for no limit")
    return minutes


def reply_seconds(minutes):
    """How long to wait for one model reply: at least REPLY_MINUTES, longer when
    the run's limit is longer, and no limit when the run has none."""
    return None if not minutes else max(REPLY_MINUTES, minutes) * 60


def describe_minutes(minutes):
    return "no limit" if not minutes else f"{minutes:g} min"


def split_command(cmd):
    """Split a command line into argv. On Windows, POSIX splitting would strip
    the backslashes from paths, so split in non-POSIX mode and unquote tokens."""
    if os.name != "nt":
        return shlex.split(cmd)
    out = []
    for tok in shlex.split(cmd, posix=False):
        if len(tok) >= 2 and tok[0] == tok[-1] and tok[0] in "\"'":
            tok = tok[1:-1]
        out.append(tok)
    return out


def cli_tools_available():
    return [t for t in CLI_TOOLS if shutil.which(t)]


# ------------------------------------------------- what the installed CLI supports

_HELP_CACHE = {}


def cli_help(tool, timeout=20):
    """The tool's own `--help` text, or '' when it cannot be run. Used to ask the
    installed binary what it supports instead of assuming a version. Cached: the
    answer cannot change while the process runs, and this shells out."""
    if tool in _HELP_CACHE:
        return _HELP_CACHE[tool]
    _HELP_CACHE[tool] = ""
    if not shutil.which(tool):
        return ""
    try:
        proc = subprocess.run([tool, "--help"], capture_output=True, text=True,
                              timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return ""
    _HELP_CACHE[tool] = (proc.stdout or "") + "\n" + (proc.stderr or "")
    return _HELP_CACHE[tool]


def help_block(text, flag):
    """The help paragraph describing one option: the line introducing `flag` plus
    the indented continuation lines that wrap its description."""
    lines = (text or "").splitlines()
    out, indent = [], None
    for line in lines:
        stripped = line.strip()
        if indent is None:
            # an option definition, not a mention in a Usage: or prose line
            if stripped.startswith("-") and re.search(
                    r"(^|[\s,])" + re.escape(flag) + r"([\s,=<\[]|$)", line):
                indent = len(line) - len(line.lstrip())
                out.append(stripped)
            continue
        if not stripped:                      # blank line ends the paragraph
            break
        cur = len(line) - len(line.lstrip())
        if cur <= indent and stripped.startswith("-"):   # the next option starts
            break
        out.append(stripped)
    return " ".join(out)


def parse_choices(block):
    """Lowercase words from the first comma- or pipe-separated list inside a help
    paragraph, e.g. "(low, medium, high, xhigh, max)", "(low|medium|high)" or
    "[possible values: a, b, c]"."""
    for m in re.finditer(r"[(\[]([^()\[\]]*[,|][^()\[\]]*)[)\]]", block or ""):
        inner = re.sub(r"^\s*(possible values|choices|values)\s*:\s*", "",
                       m.group(1), flags=re.I)
        delim = "|" if "|" in inner else ","
        words = [w.strip().strip("'\"") for w in inner.split(delim)]
        words = [w for w in words if re.fullmatch(r"[a-z][a-z0-9_-]{1,30}", w)]
        if len(words) >= 2:
            return words
    return []


def _mentioned_models(block, known):
    """The models this build mentions, kept in the capability order given."""
    return [m for m in known
            if re.search(r"(^|[^a-z0-9-])" + re.escape(m) + r"([^a-z0-9-]|$)", block or "")]


def probe(tool):
    """Ask the installed CLI what it supports and choose a deliberate default:
    one step below the top model, and an effort level near the middle of the
    range. A subscription CLI otherwise runs at its own maximum, which is more
    model and more thinking time than a literature search needs.

    Returns {"model", "effort", "models", "efforts"}. "" means nothing could be
    established, and then no flag is passed and the tool keeps its own setting.
    Models are only ever those the installed build names in its own --help.
    Effort levels come from --help when it enumerates them and otherwise from
    the tool's known ladder in CLI_TOOLS, because some tools take an effort
    setting without documenting its values. Never raises."""
    spec = CLI_TOOLS.get(tool) or {}
    text = cli_help(tool) if spec else ""
    models, efforts = [], []
    if spec.get("model_flag") and spec.get("models"):
        models = _mentioned_models(help_block(text, spec["model_flag"][0]), spec["models"])
    if spec.get("effort_flag"):
        efforts = parse_choices(help_block(text, spec["effort_flag"][0])) or list(spec["efforts"])
        efforts = [e for e in efforts if e != "none"]   # "none" turns reasoning off
    # highest minus one, so a heavy top-tier model is not spent on a search task
    model = models[1] if len(models) >= 2 else ""
    # middle of the ladder: enough reasoning for a survey, far below the maximum
    effort = efforts[len(efforts) // 2] if len(efforts) >= 3 else ""
    return {"model": model, "effort": effort, "models": models, "efforts": efforts}


def cli_defaults(tool):
    """The (model, effort) actually used: a stored choice wins, else probe(). A
    value of "-" means "pass nothing, use the tool's own default".

    Model names do not carry across tools -- "opus" means nothing to codex -- so
    a stored cli_model/cli_effort applies only to the tool it was chosen for,
    which is the cli_tool recorded beside it. An environment variable is an
    explicit per-run override and always applies."""
    owner = CFG.get("cli_tool") or ""
    mine = owner in ("", tool)
    model = os.environ.get("LITSURVEY_CLI_MODEL") or (CFG.get("cli_model") if mine else "") or ""
    effort = os.environ.get("LITSURVEY_CLI_EFFORT") or (CFG.get("cli_effort") if mine else "") or ""
    if not (model and effort):
        found = probe(tool)
        model = model or found["model"]
        effort = effort or found["effort"]
    return ("" if model == "-" else model), ("" if effort == "-" else effort)


def cli_command(tool):
    """(argv, use_stdin) for a tool name or 'custom'."""
    if tool == "custom":
        if not CFG["cli_command"]:
            raise RuntimeError("cli_tool=custom needs cli_command in the config")
        argv = [a.replace("{datadir}", DATA_DIR) for a in split_command(CFG["cli_command"])]
        return argv, not any("{prompt}" in a for a in argv)
    if tool not in CLI_TOOLS:
        raise RuntimeError(f"unknown CLI tool {tool!r}; use one of {list(CLI_TOOLS)} or custom")
    if not shutil.which(tool):
        raise RuntimeError(f"{tool!r} is not on PATH; install it and sign in, or choose another backend")
    spec = CLI_TOOLS[tool]
    argv = list(spec["argv"])
    model, effort = cli_defaults(tool)
    extra = []
    if model and spec.get("model_flag"):
        extra += [a.replace("{v}", model) for a in spec["model_flag"]]
    if effort and spec.get("effort_flag"):
        extra += [a.replace("{v}", effort) for a in spec["effort_flag"]]
    if extra:                       # after the subcommand, before the prompt
        argv = argv[:2] + extra + argv[2:] if len(argv) > 2 else argv + extra
    argv = [a.replace("{datadir}", DATA_DIR) for a in argv]
    return argv, spec["stdin"]


def run_cli(tool, prompt, timeout=DEFAULT_AGENT_MINUTES * 60, agent_token=None):
    """Hand the whole task to a subscription CLI agent; return its final text.
    timeout is in seconds, None for no limit; reaching it raises AgentTimeout.
    agent_token marks the litsurvey runs the agent makes, so the search log can
    tell them from runs the user makes by hand at the same time."""
    argv, use_stdin = cli_command(tool)
    # substitute the template's own placeholders first; the prompt goes in last
    # so that a claim containing the literal text "{outfile}" is not rewritten
    outfile = ""
    if any("{outfile}" in a for a in argv):
        fd, outfile = tempfile.mkstemp(prefix="litsurvey-cli-", suffix=".txt")
        os.close(fd)
        argv = [a.replace("{outfile}", outfile) for a in argv]
    workdir = ""
    if any("{workdir}" in a for a in argv):
        workdir = tempfile.mkdtemp(prefix="litsurvey-cli-")
        argv = [a.replace("{workdir}", workdir) for a in argv]
    if not use_stdin:
        argv = [a.replace("{prompt}", prompt) for a in argv]
    try:
        ensure_data_dir()   # a sandboxed agent cannot create it
    except OSError:
        pass
    env = dict(os.environ)
    env.pop("CLAUDECODE", None)   # allow launching Claude Code from inside a Claude Code session
    # litsurvey then refuses --out, history and nested agents, and tags its runs
    env["LITSURVEY_AGENT"] = agent_token or "1"
    try:
        proc = subprocess.run(argv, input=prompt if use_stdin else None, capture_output=True,
                              text=True, timeout=timeout, env=env)
    except FileNotFoundError:
        raise RuntimeError(f"could not start {argv[0]!r}") from None
    except subprocess.TimeoutExpired:
        raise AgentTimeout(f"{tool} did not finish within {timeout / 60:g} minutes") from None
    finally:
        final = ""
        if outfile:
            try:
                with open(outfile, encoding="utf-8", errors="replace") as f:
                    final = f.read().strip()
            except Exception:  # noqa: BLE001 - never mask the real failure below
                final = ""
            finally:
                try:
                    os.unlink(outfile)
                except OSError:
                    pass
        if workdir:
            shutil.rmtree(workdir, ignore_errors=True)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()[-800:]
        raise RuntimeError(f"{tool} exited with code {proc.returncode}: {detail}")
    out = final or proc.stdout.strip()
    if not out:
        raise RuntimeError(f"{tool} produced no output; stderr: {proc.stderr.strip()[-400:]}")
    return out


# ------------------------------------------------------------- resolution

def ollama_models(host=None):
    data = http.get_json((host or CFG["ollama_host"]) + "/api/tags", timeout=3)
    return [m["name"] for m in data.get("models", [])]


def openai_models(base=None):
    hdrs = {"Authorization": "Bearer " + CFG["openai_api_key"]} if CFG["openai_api_key"] else {}
    data = http.get_json(openai_v1_url(base or CFG["openai_base_url"], "/models"),
                         headers=hdrs, timeout=5)
    return [m["id"] for m in data.get("data", [])]


def resolve(backend=None, model=None, options=None):
    """Pick (backend, model) from arguments, config, then auto-detection."""
    backend = (backend or CFG["backend"] or "auto").lower()
    if backend == "auto":
        # safe order: local first, then a subscription CLI, then a cloud key
        try:
            ollama_models()
            backend = "ollama"
        except Exception:  # noqa: BLE001
            if cli_tools_available():
                backend = "cli"
            elif CFG["openai_api_key"] or is_loopback_url(CFG["openai_base_url"]):
                backend = "openai"
            elif CFG["anthropic_api_key"]:
                backend = "anthropic"
            else:
                raise RuntimeError(
                    "no LLM backend found. Start Ollama, install a subscription CLI "
                    "(claude / codex / agy / gemini), or set OPENAI_API_KEY / ANTHROPIC_API_KEY; "
                    "`litsurvey init` stores a choice.") from None
    if backend not in BACKENDS:
        raise RuntimeError(f"unknown backend {backend!r}; use one of {BACKENDS}")
    if backend == "cli":
        tool = model or CFG["cli_tool"] or (cli_tools_available() or [None])[0]
        if not tool:
            raise RuntimeError("no subscription CLI found on PATH (claude, codex, agy or gemini)")
        cli_command(tool)   # validates
        return backend, tool
    model = model or CFG["model"]
    if not model:
        if backend == "ollama":
            names = [n for n in ollama_models() if "embed" not in n]
            if not names:
                raise RuntimeError("Ollama is running but has no models; "
                                   "e.g. `ollama pull qwen3:30b`")
            model = names[0]
            print(f"[agent] no model configured, using Ollama model {model!r}",
                  file=sys.stderr)
        elif backend == "openai":
            base = (options or {}).get("base_url") or CFG["openai_base_url"]
            if is_loopback_url(base):
                try:                      # a local server usually has one loaded model
                    model = openai_models(base)[0]
                except Exception as e:  # noqa: BLE001
                    raise RuntimeError(f"pass --model for the openai backend ({e})") from None
            else:
                raise RuntimeError("pass --model for a hosted OpenAI-compatible API, e.g. "
                                   "--model gpt-5 (OpenAI) or --model anthropic/claude-sonnet-4.5 "
                                   "(OpenRouter); see docs/llm-integration.md")
        else:
            model = "claude-sonnet-5"
    return backend, model


# ------------------------------------------------------------- chat

def chat(backend, model, messages, tools=None, options=None):
    """options (optional): {"base_url", "api_key"} for the openai backend, and
    "reply_timeout" (seconds, None for no limit) for any backend."""
    options = options or {}
    timeout = options.get("reply_timeout", REPLY_MINUTES * 60)
    if backend == "ollama":
        return _chat_ollama(model, messages, tools, timeout)
    if backend == "openai":
        return _chat_openai(model, messages, tools, options, timeout)
    if backend == "anthropic":
        return _chat_anthropic(model, messages, tools, timeout)
    raise RuntimeError(f"unknown backend {backend!r}")


def _parse_args(a):
    if isinstance(a, dict):
        return a
    try:
        return json.loads(a or "{}")
    except (TypeError, ValueError):
        return {}


# The agent's conversation (instructions, several searches of up to 9,000
# characters each, an arXiv paper of up to 36,000) needs far more than
# Ollama's default window of a few thousand tokens. Ollama does not say when it
# overflows: it silently drops the oldest messages, the instructions first.
MIN_OLLAMA_CTX = 32768
_OLLAMA_CTX = {}


def ollama_num_ctx(model):
    """The window to ask Ollama for: MIN_OLLAMA_CTX, unless the model's own
    Modelfile already sets a larger one (as a derived model such as one built
    for 64K or 128K does), which is then left alone. None means "send nothing"."""
    if model not in _OLLAMA_CTX:
        configured = 0
        try:
            info = http.post_json(CFG["ollama_host"] + "/api/show", {"model": model}, timeout=10)
            m = re.search(r"(?m)^\s*num_ctx\s+(\d+)", info.get("parameters") or "")
            configured = int(m.group(1)) if m else 0
        except Exception:  # noqa: BLE001 - an older server: fall back to asking for the minimum
            pass
        _OLLAMA_CTX[model] = None if configured >= MIN_OLLAMA_CTX else MIN_OLLAMA_CTX
    return _OLLAMA_CTX[model]


CUT_OFF_NOTE = ("\n\n> **litsurvey note:** the model stopped because it reached its length limit, "
                "so this report may end mid-way. Run it again with a model that allows longer "
                "replies, or ask a narrower question.")


def _chat_ollama(model, messages, tools, timeout=REPLY_MINUTES * 60):
    conv = []
    for m in messages:
        if m["role"] == "assistant":
            conv.append({"role": "assistant", "content": m.get("content") or "",
                         "tool_calls": [{"function": {"name": c["name"], "arguments": c["args"]}}
                                        for c in m.get("tool_calls", [])]})
        elif m["role"] == "tool":
            conv.append({"role": "tool", "tool_name": m["name"], "content": m["content"]})
        else:
            conv.append({"role": m["role"], "content": m["content"]})
    payload = {"model": model, "messages": conv, "stream": False}
    ctx = ollama_num_ctx(model)
    if ctx:
        payload["options"] = {"num_ctx": ctx}
    if tools:
        payload["tools"] = [{"type": "function", "function": t} for t in tools]
    resp = http.post_json(CFG["ollama_host"] + "/api/chat", payload, timeout=timeout)
    msg = resp.get("message") or {}
    calls = [{"id": uuid.uuid4().hex[:12], "name": c["function"]["name"],
              "args": _parse_args(c["function"].get("arguments"))}
             for c in (msg.get("tool_calls") or [])]
    content = msg.get("content") or ""
    if resp.get("done_reason") == "length" and not calls:
        content += CUT_OFF_NOTE
    return {"content": content, "tool_calls": calls}


def _chat_openai(model, messages, tools, options=None, timeout=REPLY_MINUTES * 60):
    options = options or {}
    base = (options.get("base_url") or CFG["openai_base_url"]).rstrip("/")
    api_key = options.get("api_key") or CFG["openai_api_key"]
    conv = []
    for m in messages:
        if m["role"] == "assistant":
            entry = {"role": "assistant", "content": m.get("content") or ""}
            if m.get("tool_calls"):
                entry["tool_calls"] = [{"id": c["id"], "type": "function",
                                        "function": {"name": c["name"],
                                                     "arguments": json.dumps(c["args"])}}
                                       for c in m["tool_calls"]]
            conv.append(entry)
        elif m["role"] == "tool":
            conv.append({"role": "tool", "tool_call_id": m["tool_call_id"],
                         "content": m["content"]})
        else:
            conv.append({"role": m["role"], "content": m["content"]})
    payload = {"model": model, "messages": conv}
    if tools:
        payload["tools"] = [{"type": "function", "function": t} for t in tools]
    hdrs = {}
    if api_key:
        hdrs["Authorization"] = "Bearer " + api_key
    if "openrouter.ai" in base:            # optional attribution headers OpenRouter asks for
        hdrs["HTTP-Referer"] = "https://github.com/udaykdk/litsurvey"
        hdrs["X-Title"] = "litsurvey"
    resp = http.post_json(openai_v1_url(base, "/chat/completions"), payload, headers=hdrs)
    choice = (resp.get("choices") or [{}])[0]
    msg = choice.get("message") or {}
    calls = [{"id": c.get("id") or uuid.uuid4().hex[:12], "name": c["function"]["name"],
              "args": _parse_args(c["function"].get("arguments"))}
             for c in (msg.get("tool_calls") or [])]
    content = msg.get("content") or ""
    if choice.get("finish_reason") == "length" and not calls:
        content += CUT_OFF_NOTE
    return {"content": content, "tool_calls": calls}


def _chat_anthropic(model, messages, tools, timeout=REPLY_MINUTES * 60):
    system = ""
    conv = []
    pending_results = []

    def flush():
        if pending_results:
            conv.append({"role": "user", "content": list(pending_results)})
            pending_results.clear()

    for m in messages:
        if m["role"] == "system":
            system = m["content"]
        elif m["role"] == "user":
            flush()
            conv.append({"role": "user", "content": m["content"]})
        elif m["role"] == "assistant":
            flush()
            blocks = []
            if m.get("content"):
                blocks.append({"type": "text", "text": m["content"]})
            for c in m.get("tool_calls", []):
                blocks.append({"type": "tool_use", "id": c["id"], "name": c["name"],
                               "input": c["args"]})
            conv.append({"role": "assistant", "content": blocks or [{"type": "text", "text": "…"}]})
        elif m["role"] == "tool":
            pending_results.append({"type": "tool_result", "tool_use_id": m["tool_call_id"],
                                    "content": m["content"]})
    flush()
    payload = {"model": model, "max_tokens": 8192, "system": system, "messages": conv}
    if tools:
        payload["tools"] = [{"name": t["name"], "description": t["description"],
                             "input_schema": t["parameters"]} for t in tools]
    hdrs = {"x-api-key": CFG["anthropic_api_key"], "anthropic-version": "2023-06-01"}
    resp = http.post_json("https://api.anthropic.com/v1/messages", payload, headers=hdrs,
                          timeout=timeout)
    text, calls = [], []
    for b in resp.get("content") or []:
        if b.get("type") == "text":
            text.append(b.get("text") or "")
        elif b.get("type") == "tool_use":
            calls.append({"id": b["id"], "name": b["name"], "args": b.get("input") or {}})
    content = "\n".join(text)
    if resp.get("stop_reason") == "max_tokens" and not calls:
        content += CUT_OFF_NOTE
    return {"content": content, "tool_calls": calls}
