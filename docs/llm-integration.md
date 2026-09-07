# LLM backends, and using litsurvey from an LLM agent

This page covers two different things:

1. **litsurvey using an LLM**: the `novelty` and `research` commands need a
   model to plan searches and write reports.
2. **An LLM using litsurvey**: coding agents such as Claude Code or Codex can
   run litsurvey as a tool when you ask them literature questions.

## Part 1: backends for `novelty` and `research`

| Backend | Runs where | Setup |
|---|---|---|
| `ollama` | locally | install Ollama, `ollama pull <model>` |
| `openai` | wherever the base URL points | `OPENAI_BASE_URL`, `OPENAI_API_KEY` if the server needs one |
| `anthropic` | Anthropic's API | `ANTHROPIC_API_KEY` |

Selection order: `--backend` flag, then `backend` in the config file, then
auto-detection (Ollama if it is running, else a configured cloud key).
`litsurvey doctor` prints what will be used. The model comes from
`--model`, then the config, then a backend default (for Ollama, the first
installed model).

Set a permanent choice with `litsurvey init`, or:

```json
{ "backend": "ollama", "model": "qwen3:30b" }
```

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

### Cloud backends

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
