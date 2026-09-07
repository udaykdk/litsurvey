---
name: litsurvey
description: Search scientific literature (OpenAlex + Semantic Scholar + arXiv), walk citations, find open-access copies, export BibTeX, or run a local-LLM novelty assessment. Use whenever the user asks to find papers, check prior art or the state of the art, assess novelty of a claim, list what cites a paper, get a reading list, or says "litsurvey". Prefer this over generic web search for scholarly questions.
---

# litsurvey: scholarly search and novelty assessment

`litsurvey` is a command on PATH (if not, try `python3 -m litsurvey`).
Configuration lives in `~/.litsurvey/config.json`; never ask the user for
API keys and never print that file.

## Commands

```bash
litsurvey search "keyword query" -n 15 [--year-from 2022] [--abstracts] [--json] [--out refs.bib]
litsurvey paper   <id>          # id: S2 hash, DOI:10..., or ARXIV:2404.19756
litsurvey cites   <id> [-n 20]  # forward snowball: who cites it
litsurvey refs    <id> [-n 20]  # backward snowball: what it cites
litsurvey related <id> [-n 20]  # similar papers via recommender (different vocabulary)
litsurvey oa      <doi>         # legal open-access PDF via Unpaywall
litsurvey novelty  "claim as generic topic" [--rounds 8]  [--out report.md]   # local-LLM agent, minutes
litsurvey research "question"               [--rounds 12] [--out survey.md]   # local-LLM agent, minutes
litsurvey history [show <id> | export <id> --out x.bib | delete <id>]
litsurvey doctor                # run this first if anything fails
```

## How to use it well

- For a literature question, run 2 to 4 `search` calls with different
  phrasings (synonyms, method-centric and application-centric), then
  `cites`/`related` on the closest hits. Use `--json` when you will process
  results further.
- Cite only titles, DOIs and URLs that appear in the tool output. Do not
  reformat references from memory.
- `novelty` and `research` hand the whole job to the user's local model and
  take minutes; run them in the background. Use them when the user asks for
  the local agent or is working on confidential material; otherwise drive
  `search`/`cites`/`related` yourself and synthesise.
- To read a paper: `oa <doi>` for a PDF link, or fetch
  `https://arxiv.org/html/<arxiv id>` for arXiv full text.
- Semantic Scholar is limited to 1 request/second; do not run litsurvey
  commands in parallel.

## Confidentiality rule

Users may be reviewing confidential manuscripts. Queries must be short
generic keyword phrases. Never put verbatim sentences, titles, author names
or identifying phrasing from a manuscript into a query, and never send
manuscript text to any web service.
