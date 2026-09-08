# LLM backends, and using litsurvey from an LLM agent

This page covers two different things:

1. **litsurvey using an LLM**: the `novelty` and `research` commands need a
   model to plan searches and write reports.
2. **An LLM using litsurvey**: coding agents such as Claude Code or Codex can
   run litsurvey as a tool when you ask them literature questions.

## Part 1: backends for `novelty` and `research`

Three ways to supply the model, in the order most people will have them:

| Option | Backend name | Runs where | Setup |
|---|---|---|---|
| 1. The command-line agent of a subscription you already pay for: Claude Code (Claude Pro / Max), Codex CLI (ChatGPT), Gemini CLI (Google) | `cli` | the vendor's servers | install the tool, sign in once in a terminal |
| 2. A local model | `ollama` | your machine | install Ollama, `ollama pull <model>` |
| 3. An API key for a cloud model | `openai`, `anthropic` | the provider's servers | `OPENAI_API_KEY` / `ANTHROPIC_API_KEY`; `OPENAI_BASE_URL` for compatible servers |

Selection order: `--backend` flag, then `backend` in the config file, then
auto-detection. Auto-detection is deliberately conservative: a running
Ollama wins, then an installed subscription CLI, then a configured cloud
key. `litsurvey doctor` prints what will be used.

Set a permanent choice with `litsurvey init`, or write the config:

```json
{ "backend": "cli", "cli_tool": "claude" }
{ "backend": "ollama", "model": "qwen3:30b" }
```

### Option 1: your subscription's command-line agent

If you have Claude Pro or Max, ChatGPT Plus or Pro, or a Google account
with Gemini access, you probably already have (or can install) the matching
command-line agent: `claude` (Claude Code), `codex` (Codex CLI) or `gemini`
(Gemini CLI). These tools are signed in with your subscription, so no API
key is involved.

The mechanism is different from the other backends. litsurvey does not run
the search loop itself; it hands the whole task to the agent in
non-interactive mode, with the same instructions the built-in loop uses,
and tells it to use the `litsurvey` command as its only tool. The agent
runs `litsurvey search`, `cites`, `refs` and `related` as it sees fit and
prints the report. Every one of those commands is recorded in the history,
so the saved report still ends with a complete search log.

```bash
litsurvey novelty "conformal prediction intervals for PINN solutions" --backend cli --model claude --out claim.md
litsurvey research "..." --backend cli --model gemini
```

For `--backend cli`, `--model` names the tool: `claude`, `codex`, `gemini`,
or `custom`. The commands used are:

| Tool | Command litsurvey runs |
|---|---|
| claude | `claude -p --output-format text --allowedTools "Bash(litsurvey:*)"`, prompt on stdin |
| codex | `codex exec --full-auto "<prompt>"` |
| gemini | `gemini --yolo -o text -p "<prompt>"` |
| custom | whatever `cli_command` in the config says; `{prompt}` is substituted, otherwise the prompt is passed on stdin |

Things to know:

- Sign in first, and check it the way the non-interactive mode sees it.
  For Claude Code run `claude auth status`; it must say `"loggedIn": true`.
  If it says false, run `claude auth login` (or `/login` inside `claude`).
  An interactive `claude` that opens without complaint does not prove print
  mode is signed in: the interactive session can borrow a token from the
  Claude desktop app, print mode cannot. When signed out, litsurvey reports
  the tool's own error ("OAuth session expired and could not be refreshed").
- Your claim or question and everything the agent reads go to that vendor
  under your subscription's terms. This is not the option for confidential
  manuscripts; use option 2.
- There is no progress display while the agent works; a run typically takes
  one to five minutes. The `[agent]` line at the start says which tool is
  running.
- Codex CLI's sandbox blocks network access by default in some
  configurations, which stops litsurvey's API calls. If runs fail with
  network errors, allow network in your Codex config, or use the `custom`
  tool with the flags your version needs.
- The Claude Code path has been run end to end by the author (a real
  novelty assessment with a full search log). The Codex and Gemini commands
  follow those tools' documented flags but have not been run; reports
  welcome.
- `--rounds` becomes a command budget for the agent (about three commands
  per round).

### Option 2: a local model

### Local models that work well

The agent needs a model that handles tool calling and reads long search
results. In our testing, on a laptop with 48 GB of unified memory:

- **Qwen3 30B-A3B (2507, thinking variant)**: best accuracy; mixture-of-experts,
  so it is fast for its size. `ollama pull qwen3:30b-thinking`.
- **Qwen3 30B-A3B instruct**: same, without the deliberation step.
- **Gemma 3 27B**: good, also reads images if you use it elsewhere.
- **gpt-oss 20B**: lighter, fits 16 GB machines.

Ollama's default context window (4096 tokens) is too small for the agent's
search results. Create a variant with a larger window once:

```
printf 'FROM qwen3:30b-thinking\nPARAMETER num_ctx 65536\n' > Modelfile
ollama create surveyor -f Modelfile
litsurvey novelty "..." --model surveyor
```

Machines with 16 GB can run 8B to 14B models (`qwen3:8b`, `qwen3:14b`); the
reports are weaker but the search work is the same.

### OpenAI-compatible local servers

LM Studio, vLLM, llama.cpp's server and similar all speak the OpenAI chat
API. Point litsurvey at them:

```bash
export OPENAI_BASE_URL=http://localhost:1234
litsurvey novelty "..." --backend openai --model <name shown by the server>
```

### Option 3: cloud API keys

`--backend openai` with the default base URL, or `--backend anthropic`. Your
input text and every search result are sent to the provider. Do not use for
material you must keep confidential; see
[confidentiality.md](confidentiality.md).

## Part 2: using litsurvey from a coding agent

litsurvey is a plain command, so any agent that can run shell commands can
use it. What it needs is a short description of the commands and the rules.
Ready-made files are in the `integrations/` folder of the repository.

### Claude Code

Copy the skill folder into your user skills directory:

```bash
cp -r integrations/claude-code/litsurvey ~/.claude/skills/
```

(Or into a project's `.claude/skills/` to enable it for that project only.)
From then on, in any Claude Code session, questions such as *"has anyone
published X?"* or *"find recent papers on Y"* make Claude run litsurvey,
read the results and answer with DOIs. `/litsurvey` invokes it explicitly.

### Codex

Copy the contents of `integrations/codex/AGENTS.md` into your project's
`AGENTS.md`, or into `~/.codex/AGENTS.md` for all projects.

### Any other agent

Give it the text of `docs/cli.md`, or this summary:

> `litsurvey` is installed. Use `litsurvey search "keywords" --json`,
> `litsurvey cites ID`, `litsurvey related ID` and `litsurvey oa DOI` for
> literature questions; run two or three phrasings; cite only DOIs and URLs
> from the output. Never put confidential manuscript text into a query.

### Which agent should do the reasoning?

Two agents can drive the same tool: litsurvey's own `novelty`/`research`
loop with a local model, or the coding agent (Claude, Codex) itself running
the search commands. The difference is where your text goes:

| | litsurvey agent, local backend | Coding agent running litsurvey |
|---|---|---|
| Reasoning happens | on your machine | on the agent provider's servers |
| Sees your prompt | yes, locally | yes, in the cloud |
| Quality | good | usually better |
| Use for | confidential manuscripts | general literature questions |

### MCP

A Model Context Protocol server would make litsurvey a native tool in Claude
Desktop, Claude Code, Codex and others without a skill file. It is on the
roadmap; the CLI approach above works today.
