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

Every successfully completed run is recorded in the history (see `history`
below); a failed run, or a title lookup abandoned at the candidate list, is
not.

## search

```bash
litsurvey search "QUERY" [--year-from YEAR] [--sources openalex,s2,arxiv] [--scholar] [list options]
```

Queries OpenAlex, Semantic Scholar, arXiv, PubMed, TechRxiv, Research Square
and the IACR ePrint archive, de-duplicates by DOI, arXiv ID or title, and
merges the rankings with weighted reciprocal rank fusion (the big indexes
carry full weight, the single-portal sources half). A paper found by more
than one source ranks higher and shows `[openalex+s2]`. `--scholar` prints
a Google Scholar URL for the same query, for a manual comparison.

`--sources` restricts or extends the set:

| Name | What it is | Default |
|---|---|---|
| `openalex` | about 250 million works, all fields | yes |
| `s2` | Semantic Scholar, about 220 million works | yes |
| `arxiv` | preprints in physics, maths, CS and related fields | yes |
| `pubmed` | about 38 million biomedical records, via the NCBI E-utilities | yes |
| `techrxiv` | TechRxiv preprints, via their Crossref DOI prefix | yes |
| `researchsquare` | Research Square preprints, same route | yes |
| `iacr` | IACR Cryptology ePrint Archive | yes |
| `europepmc` | Europe PMC: PubMed's ground plus bioRxiv/medRxiv, with citation counts | no |
| `crossref` | every DOI-registered work | no |

The last two are off by default because each largely repeats a source
already in the list. Restricting the set is also the way to make a search
faster: `--sources openalex,s2,arxiv` is the quick physics-and-engineering
set, and a full default run takes roughly ten to twenty seconds because the
sources are queried one after another at the rate limits they ask for.

PubMed needs two calls per search (one for the matching record ids, one for
the records themselves) and so is a little slower than the others. IACR
results carry no DOI or Semantic Scholar id, so they appear in searches but
cannot be used with `cites`, `refs` or `related`; DBLP results carry no
citation counts, which is one reason DBLP is not a source here — the other
is that its API is behind a bot wall.

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

`cites` and `refs` walk the citation graph, most-cited first (`--sort year`
for newest first). For a paper with a DOI they use OpenAlex, which ranks
citing works server-side, so a paper with thousands of citations shows its
most influential citers rather than the newest few. Papers without a DOI
fall back to Semantic Scholar, which returns at most 100 rows (newest
first); litsurvey then sorts those locally by citations or year. There is no
`--year-from` on `cites`/`refs`; use `--sort year` or filter the exported file.
`related` uses a recommendation model on Semantic Scholar's servers, which
finds papers on the same topic that use different words. When Semantic
Scholar is unavailable (it returns 429 or 500 under load), `related` and
`paper` fall back to OpenAlex for any paper with a DOI, with a `[warn]`
line saying so; only ids without a DOI then fail.

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
near hits, and writes a report. The built-in loop (ollama, openai,
anthropic backends) may also read one or two arXiv papers in full; the
subscription-CLI backend works from abstracts only.

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
litsurvey doctor    # checks the search sources and detects LLM backends; paste its output into bug reports
```

When you choose the `cli` backend, `init` also asks the installed
command-line agent which models and effort levels it supports, and proposes
one model below the best at an effort level in the middle of the range —
these tools otherwise run at their maximum, which is more model and more
thinking time than a literature search needs. See
[llm-integration.md](llm-integration.md).

Neither command is required. `init` is the convenient way to store the
key; `doctor` is a diagnostic. Run `doctor` once after installing, to
confirm the key and any LLM backend are seen, and again whenever a command
fails. It makes one small test query to each of the seven default search sources,
detects Ollama and any subscription CLI on PATH, and reports whether cloud
keys are configured. It does not query Unpaywall and does not make an LLM
call. It ends with a `RESULT:` verdict followed by one advisory line:
`ALL OK`, `OK WITH WARNINGS` (a minor source such as IACR failed; searches
still work), `OK for search` (no LLM backend found), or `PROBLEMS` (a core
source failed; exit code 1). A few `[warn] HTTP 429` lines before a source
reports OK are normal; they mean the API rate-limited the request and the
retry succeeded.

```console
$ litsurvey doctor
litsurvey 1.0.1, python 3.12.4
config       : /Users/me/.litsurvey/config.json
S2 API key   : set (s2k-…)
email        : me@university.edu
openalex      : OK (2 results)
semanticscholar: OK (2 results)
arxiv         : OK (2 results)
pubmed        : OK (2 results)
techrxiv      : OK (2 results)
researchsquare: OK (2 results)
iacr          : OK (2 results)
ollama       : OK at http://localhost:11434 (3 models: qwen3:30b, gemma3:27b, …)
subscr. CLIs : claude (claude / codex / gemini on PATH)
openai       : no key, base https://api.openai.com
anthropic    : no key
agent default: backend=ollama model=qwen3:30b (local)

(doctor does not test Unpaywall, and does not make an LLM call; it only detects backends.)
RESULT: ALL OK. Search, citation and open-access commands work; novelty/research will use ollama model qwen3:30b (local).
You do not need to run doctor regularly: use it after install, or when something fails.
```

Environment variables override the config file: `S2_API_KEY` (or
`LITSURVEY_S2_API_KEY`), `OPENALEX_MAILTO` (or `LITSURVEY_MAILTO`),
`LITSURVEY_BACKEND`, `LITSURVEY_MODEL`, `LITSURVEY_CLI_TOOL`,
`LITSURVEY_CLI_COMMAND`, `OLLAMA_HOST`, `OPENAI_BASE_URL`, `OPENAI_API_KEY`,
`ANTHROPIC_API_KEY`.

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
