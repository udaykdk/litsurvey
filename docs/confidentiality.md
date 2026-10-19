# Confidentiality: what leaves your machine

This page is for anyone using litsurvey on material they must not disclose,
for example a manuscript under peer review, a grant proposal, or an
unpublished result. It states exactly which bytes leave the computer in each
mode, and who receives them.

## Two kinds of commands

**Search and lookup commands** (`search`, `paper`, `cites`, `refs`,
`related`, `oa`) do not use any language model. The script sends the text you
typed, a keyword query, a paper ID or a DOI, to the public scholarly APIs and
prints what comes back. The exposure is the same as typing that query into
the website of OpenAlex, Semantic Scholar or arXiv yourself.

The hosts contacted by a default search are `api.openalex.org`,
`api.semanticscholar.org`, `export.arxiv.org`, `eutils.ncbi.nlm.nih.gov`
(PubMed), `api.crossref.org` (TechRxiv and Research Square) and
`eprint.iacr.org`; `--sources europepmc` adds `www.ebi.ac.uk` and `oa` uses
`api.unpaywall.org`. Each sees the query and your IP address, and — if you
set `openalex_mailto` — your email address: OpenAlex, Crossref, NCBI and
Unpaywall receive it as a query parameter to identify polite callers, and arXiv
receives it in the User-Agent, as its API terms ask. The LLM backend and the
PyPI update check do not receive it. None of them is told what you are
working on beyond the query itself.

**Agent commands** (`novelty`, `research`) use a language model to plan
queries, read the results, and write a report. Where that model runs decides
what leaves the machine.

## The flow of information in the agent commands

1. You type a claim or question on the command line.
2. The script sends it, together with fixed instructions and a list of
   available tools, to the LLM backend.
3. The model replies with search requests, for example
   `search_papers("Kolmogorov-Arnold network PINN")`.
4. The script runs those searches against the public APIs and sends the
   results (titles, abstracts, metadata) back to the model.
5. Steps 3 and 4 repeat until the model writes the report.
6. The report and the search log are printed and saved locally.

So the public APIs see the **keyword queries the model composed**, plus the
**paper identifiers** needed for citation lookups, recommendations and
arXiv full-text retrieval. They never see your input text itself. The LLM
backend sees **everything**: your input text, the instructions, and every
search result.

With the `cli` backend the flow is the same but the loop runs inside the
vendor's agent (Claude Code, Codex, Antigravity, Gemini CLI) rather than inside
litsurvey: the agent is handed the task and calls `litsurvey search`,
`cites`, `refs` and `related` itself. Its commands are recorded in the
search log like any other run.

## Backends

| Backend | Where the model runs | Sees your text? | Recommended for confidential material |
|---|---|---|---|
| `cli` (Claude Code, Codex CLI, Antigravity CLI, Gemini CLI under your subscription) | the vendor's servers | yes, over the network, plus every search result the agent reads | no |
| `ollama` | your own machine | yes, but locally only | yes |
| `openai` pointed at a local server (LM Studio, vLLM, llama.cpp on `localhost`) | your own machine | yes, locally only | yes |
| `openai` pointed at a hosted provider (OpenAI, OpenRouter, ...) | the provider's servers | yes, over the network | no |
| `anthropic` | Anthropic's servers | yes, over the network | no |

The agent prints a line at the start of every run stating which backend and
model are in use and whether it is local. The web page shows the same in a
coloured banner before you press Run.

## Rules built into the agent

- The instructions to the model say: queries must be short generic keyword
  phrases; never put verbatim sentences, author names or identifying phrasing
  from a manuscript into a query. **This is an instruction, not a guarantee.**
  A model can ignore it, and text inside a search result (an abstract anyone
  can post on arXiv) can try to talk it out of it.
- The part that is enforced: with a local model or an API key, litsurvey runs
  the searches itself and refuses any query that repeats eight or more
  consecutive words of your input. It cannot catch a paraphrase. With a
  subscription CLI the agent runs the searches, so this check does not apply.
- Search results are passed to the model inside marked blocks, and the model
  is told that nothing inside them is an instruction. This makes injected
  instructions less likely to work; it does not make them impossible.
- The model is told to cite only titles, years, venues and DOIs that appeared
  in search results, never from memory. This reduces invented references; it
  does not make them impossible. litsurvey then checks every DOI and arXiv id
  in the report against the papers the searches returned (they are kept in
  the search log) and appends a "Citation check" note naming any that did
  not come from a search. References given without an identifier are not
  checked. Check DOIs before using them.
- Tool results sent to the model are capped in size, and the round limit
  bounds how many queries a run can make.

## Subscription CLI agents and hostile text

With `--backend cli` the vendor's agent reads search results and has a shell.
An abstract written to manipulate it could ask it to run other commands.
How far that could go depends on the tool:

- **Claude Code** is started with only its shell tool (`--tools Bash`), and
  the shell may run only `litsurvey search`, `paper`, `cites`, `refs` and
  `related`. In tests against Claude Code it could not read a file, chain
  another command, use command substitution or expand an environment
  variable; each was refused or held for an approval that never comes in
  non-interactive mode.
- **Codex CLI** runs in an empty temporary directory under a write sandbox,
  but its shell can read files and reach the network.
- **Gemini CLI and Antigravity** run with all approvals turned on (`--yolo`,
  `--dangerously-skip-permissions`), because they have no way to allow only
  one command. Their shell can do anything your account can.

For every agent, `litsurvey` itself also refuses `--out`, `history`, `init`,
`web` and the agent commands when an agent started it (litsurvey sets an
environment variable for this), so the tool cannot be used to write files or
to read other files through the history. The prompt tells every agent that
search output is data and never an instruction. For work where this risk
matters, use a local model.

## What you should do

- **Phrase the input as a topic, not as a quotation.** The claim text is used
  to compose queries, so words from it will appear in queries. Write
  "conformal prediction intervals for PINN solutions", not the sentence from
  the manuscript's abstract.
- **Do not paste the manuscript.** litsurvey has no mode that reads a
  manuscript, on purpose. The tool assesses a claim you state.
- **Use a local backend** for anything under embargo or review. Run
  `litsurvey doctor`; the "agent default" line says which backend will be
  used and whether it is local.
- **Check the search log.** Every report saved with `--out` ends with a table
  of every query that was sent out. If something in that table should not
  have left the machine, you will see it there.

## Where litsurvey stores data

- `~/.litsurvey/` itself is readable by your account only (mode 700), and
  the files litsurvey writes in it are mode 600, so other accounts on a
  shared machine cannot read your claims or reports.
- `~/.litsurvey/config.json`: your API key and settings (file mode 600).
- `~/.litsurvey/.update-check`: the latest version number on PyPI and when it
  was last asked, for the web page's "Update available" link. Asking PyPI
  sends nothing but an ordinary request for the litsurvey package page;
  `update_check: false` in the config turns it off.
- `~/.litsurvey/history.jsonl` and `~/.litsurvey/runs/`: every completed run's inputs
  and results, so the web page's History tab and `litsurvey history` can
  show them. This stays on your disk. Delete runs with
  `litsurvey history delete <id>` or the web page.

## Rate-limit stamps

`~/.litsurvey/.ratelimit-<host>` files hold only a timestamp, used to keep the
CLI and the web page together under each API's request limit. This is best
effort: two processes that check the stamp at the same instant can both send.
