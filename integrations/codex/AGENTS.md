## Literature search: litsurvey

`litsurvey` is installed (fallback: `python3 -m litsurvey`). Use it instead of
web search for scholarly questions: finding papers, prior art, citation
neighbourhoods, reading lists, open-access copies.

- `litsurvey search "keywords" -n 15 [--year-from YEAR] [--json] [--out refs.bib]`
- `litsurvey cites <id>` / `litsurvey refs <id>` / `litsurvey related <id>`
  where `<id>` is a Semantic Scholar hash, `DOI:10...` or `ARXIV:2404.19756`
  as printed in search results
- `litsurvey oa <doi>` for a legal open-access PDF
- `litsurvey novelty "claim as generic topic" --out report.md` and
  `litsurvey research "question" --out survey.md` run a local-LLM agent and
  take minutes; run in the background
- `litsurvey doctor` if anything fails

Rules: run two or three phrasings of each question; cite only DOIs and URLs
that appear in the output; do not run litsurvey commands in parallel
(1 request/second limit); never put confidential manuscript text into a
query. Never ask for or print API keys (`~/.litsurvey/config.json`).
