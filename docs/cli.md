# Command-line reference

```
litsurvey [--debug] <command> [options]
```

`--debug` prints every HTTP request to stderr. Use it when reporting a bug.
`--version` prints the version.

Result lists are printed as numbered entries. The `id:` field of every entry
is accepted by `paper`, `cites`, `refs`, `related` and, when it is a DOI, by
`oa`. Three ID forms work everywhere: a Semantic Scholar hash
(`a68d501c2c1b…`), `DOI:10.1021/nl0731872`, or `ARXIV:2404.19756`.

All list commands share these options:

| Option | Meaning |
|---|---|
| `-n N` | maximum results (default 15, API cap 100) |
| `--sort relevance\|citations\|year` | order of the printed list (default relevance, the fused ranking) |
| `--abstracts` | print the first 350 characters of each abstract |
| `--json` | print the full records as JSON instead of text |
| `--out FILE` | also write the list; the extension picks the format: `.bib`, `.ris`, `.csv`, `.json`, `.md` |

Every run is recorded in the history (see `history` below).

## search

```bash
litsurvey search "QUERY" [--year-from YEAR] [--sources openalex,s2,arxiv] [--scholar] [list options]
```

Queries OpenAlex, Semantic Scholar and arXiv, de-duplicates by DOI, arXiv ID
or title, and merges the three rankings with reciprocal rank fusion. A paper
found by more than one source ranks higher and shows `[openalex+s2]`.
`--scholar` prints a Google Scholar URL for the same query, for a manual
comparison. `--sources` restricts the sources.

```console
$ litsurvey search "physics informed neural networks inverse problems" -n 2 --year-from 2022
1. **Gradient-enhanced physics-informed neural networks for forward and inverse PDE problems** (2022) — Jeremy Yu, Lu Lu, Xuhui Meng et al.
   Computer Methods in Applied Mechanics and Engineering · 695 citations · [openalex+s2] · id: `DOI:10.1016/j.cma.2022.114823`
   https://doi.org/10.1016/j.cma.2022.114823

2. **Physics-informed neural networks for inverse problems in supersonic flows** (2022) — Ameya D. Jagtap, Zhiping Mao, Nikolaus A. Adams et al.
   Journal of Computational Physics · 318 citations · [openalex] · id: `DOI:10.1016/j.jcp.2022.111402`
   https://doi.org/10.1016/j.jcp.2022.111402
```

Queries are matched on words, so run two or three phrasings. Quoting a
phrase is not needed; the whole argument is the query.

## paper, cites, refs, related

```bash
litsurvey paper   ID          # one paper with its full abstract
litsurvey cites   ID [-n N]   # papers citing it, most cited first
litsurvey refs    ID [-n N]   # papers it cites, most cited first
litsurvey related ID [-n N]   # similar papers from Semantic Scholar's recommender
```

**A title works too.** If the argument is not an id, litsurvey searches for
it. An exact title match is used straight away (a `[note] using: …` line
says which paper). Otherwise it prints up to eight candidates with their
ids and, at a terminal, asks you to pick one; `--sort citations` or
`--sort year` orders that list. In a script or from an agent (no terminal)
it prints the list and exits with code 2; rerun with the id, or add
`--pick N` to take candidate N without asking:

```console
$ litsurvey cites "superior thermal conductivity graphene" --pick 1
[note] using: Superior Thermal Conductivity of Single-Layer Graphene (2008) id DOI:10.1021/nl0731872
1. **Two-Dimensional Phonon Transport in Supported Graphene** …
```

`cites` and `refs` walk the citation graph. `related` uses a recommendation
model on Semantic Scholar's servers, which finds papers on the same topic
that use different words. All four use Semantic Scholar only; a paper that
has no Semantic Scholar record gives an error, in which case try the DOI
form of the ID.

## oa

```bash
litsurvey oa DOI [--json] [--out FILE]
```

Asks Unpaywall for a legal open-access copy: the author's preprint, an
institutional repository copy, or the publisher's open version. A title
is accepted in place of the DOI, with the same candidate choice as above;
a paper without a DOI cannot be looked up.

```console
$ litsurvey oa 10.1016/j.cma.2022.114823
**Gradient-enhanced physics-informed neural networks for forward and inverse PDE problems**
open access: yes (submittedVersion)
pdf : https://arxiv.org/pdf/2111.02801
```

## novelty and research

```bash
litsurvey novelty  "CLAIM"    [--backend B] [--model M] [--rounds N] [--out FILE.md] [--no-log]
litsurvey research "QUESTION" [--backend B] [--model M] [--rounds N] [--out FILE.md] [--no-log]
```

These need an LLM backend: `--backend cli` (your Claude Code / Codex /
Gemini subscription CLI; `--model` names the tool), `--backend ollama`
(local), or `--backend openai` / `anthropic` (API keys). See
[llm-integration.md](llm-integration.md).
The model plans keyword queries, calls the search tools, walks citations of
near hits, may read one or two arXiv papers in full, and writes a report.

- `novelty` writes: closest prior work, what is new versus prior art, a
  verdict with confidence, and citations for the reviewer.
- `research` writes: a survey organised by theme with numbered citations,
  open problems, coverage caveats, and a source list.
- `--rounds` caps the number of tool-calling rounds (default 8 for
  `novelty`, 12 for `research`). Each round is one model call that may
  contain several tool calls. When the cap is reached the model is told to
  stop and write.
- `--out FILE.md` saves the report, appends a **Search log** table (every
  query, its time and hit counts per source), and writes `FILE.log.json` with
  the same log for scripts. `--no-log` omits the appendix.
- Progress lines prefixed `[agent]` go to stderr, so `> report.md` captures
  only the report.

State the input as a generic topic. Words from it become search queries;
see [confidentiality.md](confidentiality.md).

Typical duration: 2 to 15 minutes on a local 30B model; under a minute on a
fast cloud model.

## history

```bash
litsurvey history                       # list recent runs
litsurvey history -n 100
litsurvey history show   RUN_ID         # print the results or report again
litsurvey history export RUN_ID --out refs.bib
litsurvey history delete RUN_ID
```

Runs live in `~/.litsurvey/runs/<id>.json`; the index is
`~/.litsurvey/history.jsonl`. The web page's History tab reads the same
store, so runs made on the command line appear there and the other way
round.

## init and doctor

```bash
litsurvey init      # asks for the Semantic Scholar key, your email, and the LLM backend; writes ~/.litsurvey/config.json
litsurvey doctor    # checks every API and backend; paste its output into bug reports
```

Neither command is required. `init` is the convenient way to store the
key; `doctor` is a diagnostic. Run `doctor` once after installing, to
confirm the key and any LLM backend are seen, and again whenever a command
fails. It makes one small test query per source and ends with a one-line
verdict: `RESULT: ALL OK`, `RESULT: OK for search` (no LLM backend), or
`RESULT: PROBLEMS`. A few `[warn] HTTP 429` lines before a source reports
OK are normal; they mean the API rate-limited the request and the retry
succeeded.

```console
$ litsurvey doctor
litsurvey 1.0.0, python 3.12.4
config       : /Users/me/.litsurvey/config.json (found)
S2 API key   : set (s2k-…)
email        : me@university.edu
openalex     : OK (2 results)
semanticscholar: OK (2 results)
arxiv        : OK (2 results)
ollama       : OK at http://localhost:11434 (3 models: qwen3:30b, gemma3:27b, …)
openai       : no key, base https://api.openai.com
anthropic    : no key
agent default: backend=ollama model=qwen3:30b (local)

RESULT: ALL OK. Search, citation and open-access commands work; novelty/research will use ollama model qwen3:30b (local).
You do not need to run doctor regularly: use it after install, or when something fails.
```

Environment variables override the config file: `S2_API_KEY`,
`OPENALEX_MAILTO`, `LITSURVEY_BACKEND`, `LITSURVEY_MODEL`, `OLLAMA_HOST`,
`OPENAI_BASE_URL`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`.

## web

```bash
litsurvey web [--port 8765] [--no-browser]
```

Starts the browser interface on `127.0.0.1` only and opens it. See
[web.md](web.md).

## Exit codes and errors

Errors print `error: …` on stderr and exit 1. Network problems are retried
with backoff; a persistent rate limit prints `[warn] HTTP 429 …` lines. Use
`--debug` to see the exact URLs.
