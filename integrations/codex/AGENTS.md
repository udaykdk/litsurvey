## Literature search: litsurvey

`litsurvey` is installed (fallback: `python3 -m litsurvey`). Use it instead of
web search for scholarly questions: finding papers, prior art, citation
neighbourhoods, reading lists, open-access copies.

- `litsurvey search "keywords" -n 15 [--year-from YEAR] [--json] [--out refs.bib]`
  searches OpenAlex, Semantic Scholar, arXiv, PubMed and three preprint
  portals; `--sources openalex,s2,arxiv` is a faster subset and
  `--sources ...,europepmc,crossref` widens it
- `litsurvey cites <id>` / `litsurvey refs <id>` / `litsurvey related <id>`
  where `<id>` is a Semantic Scholar hash, `DOI:10...` or `ARXIV:2404.19756`
  as printed in search results; a paper title also works and prints a
  numbered candidate list (exit code 2): rerun with `--pick N`
- `--sort citations|year` on any list command
- `litsurvey oa <doi>` for a legal open-access PDF
- `litsurvey novelty "claim as generic topic" --out report.md` and
  `litsurvey research "question" --out survey.md` run an LLM agent and take
  minutes; run in the background. Do not call these from inside Codex: they
  may start Codex again. Run the search commands above and write the
  assessment yourself.
- `litsurvey doctor` if anything fails

If a `litsurvey` call fails with a network error, Codex is sandboxed
without network access: rerun Codex with `--sandbox workspace-write -c
sandbox_workspace_write.network_access=true`, and `--add-dir ~/.litsurvey`
so the run history can be written.

Rules: run two or three phrasings of each question; cite only DOIs and URLs
that appear in the output; do not run litsurvey commands in parallel
(1 request/second limit); never put confidential manuscript text into a
query. Never ask for or print API keys (`~/.litsurvey/config.json`).
