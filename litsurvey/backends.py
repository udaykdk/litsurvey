"""LLM backends behind one small interface.

Neutral transcript format used by the agent:
  {"role": "system"|"user", "content": str}
  {"role": "assistant", "content": str, "tool_calls": [{"id", "name", "args"}]}
  {"role": "tool", "tool_call_id": str, "name": str, "content": str}
Neutral tool format: {"name", "description", "parameters"} (JSON schema).

chat() returns {"content": str, "tool_calls": [{"id", "name", "args"}]}.
"""
import json
import os
import shlex
import shutil
import subprocess
import sys
import uuid

from . import http
from .config import CFG

BACKENDS = ("cli", "ollama", "openai", "anthropic")
LOCAL_BACKENDS = ("ollama",)   # data never leaves the machine


def is_local(backend, base_url=None):
    """True when the model runs on this machine: Ollama, or an OpenAI-compatible
    server on a loopback address (LM Studio, vLLM, llama.cpp)."""
    if backend in LOCAL_BACKENDS:
        return True
    if backend == "openai":
        base = (base_url or CFG["openai_base_url"]).lower()
        return any(h in base for h in ("localhost", "127.0.0.1", "[::1]", "0.0.0.0"))
    return False

# Subscription command-line agents. Each is run non-interactively with the task as
# its prompt; it uses the `litsurvey` command itself as its search tool.
CLI_TOOLS = {
    "claude": {"label": "Claude Code (Claude Pro / Max subscription)",
               "argv": ["claude", "-p", "--output-format", "text",
                        "--allowedTools", "Bash(litsurvey:*)"], "stdin": True},
    "codex": {"label": "Codex CLI (ChatGPT subscription)",
              "argv": ["codex", "exec", "--full-auto", "{prompt}"], "stdin": False},
    "gemini": {"label": "Gemini CLI (Google account)",
               "argv": ["gemini", "--yolo", "-o", "text", "-p", "{prompt}"], "stdin": False},
}


def cli_tools_available():
    return [t for t in CLI_TOOLS if shutil.which(t)]


def cli_command(tool):
    """(argv, use_stdin) for a tool name or 'custom'."""
    if tool == "custom":
        if not CFG["cli_command"]:
            raise RuntimeError("cli_tool=custom needs cli_command in the config")
        argv = shlex.split(CFG["cli_command"])
        return argv, not any("{prompt}" in a for a in argv)
    if tool not in CLI_TOOLS:
        raise RuntimeError(f"unknown CLI tool {tool!r}; use one of {list(CLI_TOOLS)} or custom")
    if not shutil.which(tool):
        raise RuntimeError(f"{tool!r} is not on PATH; install it and sign in, or choose another backend")
    return list(CLI_TOOLS[tool]["argv"]), CLI_TOOLS[tool]["stdin"]


def run_cli(tool, prompt, timeout=1800):
    """Hand the whole task to a subscription CLI agent; return its final text."""
    argv, use_stdin = cli_command(tool)
    if not use_stdin:
        argv = [a.replace("{prompt}", prompt) for a in argv]
    env = dict(os.environ)
    env.pop("CLAUDECODE", None)   # allow launching Claude Code from inside a Claude Code session
    try:
        proc = subprocess.run(argv, input=prompt if use_stdin else None, capture_output=True,
                              text=True, timeout=timeout, env=env)
    except FileNotFoundError:
        raise RuntimeError(f"could not start {argv[0]!r}") from None
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"{tool} did not finish within {timeout} s") from None
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()[-800:]
        raise RuntimeError(f"{tool} exited with code {proc.returncode}: {detail}")
    out = proc.stdout.strip()
    if not out:
        raise RuntimeError(f"{tool} produced no output; stderr: {proc.stderr.strip()[-400:]}")
    return out


# ------------------------------------------------------------- resolution

def ollama_models(host=None):
    data = http.get_json((host or CFG["ollama_host"]) + "/api/tags", timeout=3)
    return [m["name"] for m in data.get("models", [])]


def openai_models(base=None):
    hdrs = {"Authorization": "Bearer " + CFG["openai_api_key"]} if CFG["openai_api_key"] else {}
    data = http.get_json((base or CFG["openai_base_url"]) + "/v1/models", headers=hdrs, timeout=5)
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
            elif CFG["openai_api_key"] or "localhost" in CFG["openai_base_url"]:
                backend = "openai"
            elif CFG["anthropic_api_key"]:
                backend = "anthropic"
            else:
                raise RuntimeError(
                    "no LLM backend found. Start Ollama, install a subscription CLI "
                    "(claude / codex / gemini), or set OPENAI_API_KEY / ANTHROPIC_API_KEY; "
                    "`litsurvey init` stores a choice.") from None
    if backend not in BACKENDS:
        raise RuntimeError(f"unknown backend {backend!r}; use one of {BACKENDS}")
    if backend == "cli":
        tool = model or CFG["cli_tool"] or (cli_tools_available() or [None])[0]
        if not tool:
            raise RuntimeError("no subscription CLI found on PATH (claude, codex or gemini)")
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
            if "localhost" in base or "127.0.0.1" in base:
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
    """options (optional): {"base_url": ..., "api_key": ...} overrides for the openai backend."""
    if backend == "ollama":
        return _chat_ollama(model, messages, tools)
    if backend == "openai":
        return _chat_openai(model, messages, tools, options or {})
    if backend == "anthropic":
        return _chat_anthropic(model, messages, tools)
    raise RuntimeError(f"unknown backend {backend!r}")


def _parse_args(a):
    if isinstance(a, dict):
        return a
    try:
        return json.loads(a or "{}")
    except (TypeError, ValueError):
        return {}


def _chat_ollama(model, messages, tools):
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
    if tools:
        payload["tools"] = [{"type": "function", "function": t} for t in tools]
    resp = http.post_json(CFG["ollama_host"] + "/api/chat", payload)
    msg = resp.get("message") or {}
    calls = [{"id": uuid.uuid4().hex[:12], "name": c["function"]["name"],
              "args": _parse_args(c["function"].get("arguments"))}
             for c in (msg.get("tool_calls") or [])]
    return {"content": msg.get("content") or "", "tool_calls": calls}


def _chat_openai(model, messages, tools, options=None):
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
    resp = http.post_json(base + "/v1/chat/completions", payload, headers=hdrs)
    msg = (resp.get("choices") or [{}])[0].get("message") or {}
    calls = [{"id": c.get("id") or uuid.uuid4().hex[:12], "name": c["function"]["name"],
              "args": _parse_args(c["function"].get("arguments"))}
             for c in (msg.get("tool_calls") or [])]
    return {"content": msg.get("content") or "", "tool_calls": calls}


def _chat_anthropic(model, messages, tools):
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
    resp = http.post_json("https://api.anthropic.com/v1/messages", payload, headers=hdrs)
    text, calls = [], []
    for b in resp.get("content") or []:
        if b.get("type") == "text":
            text.append(b.get("text") or "")
        elif b.get("type") == "tool_use":
            calls.append({"id": b["id"], "name": b["name"], "args": b.get("input") or {}})
    return {"content": "\n".join(text), "tool_calls": calls}
