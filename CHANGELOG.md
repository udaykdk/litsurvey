# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/) and the project uses
[Semantic Versioning](https://semver.org/).

## [1.0.0] - 2026-09-07

First public release.

### Added
- `search`: fused, de-duplicated keyword search over OpenAlex, Semantic Scholar and arXiv.
- `paper`, `cites`, `refs`, `related`: one paper and its citation neighbourhood.
- `oa`: legal open-access copies via Unpaywall.
- `novelty` and `research`: LLM-driven agents with pluggable backends and a
  reproducible search log. Backends: `cli` (delegates the task to a signed-in
  Claude Code, Codex CLI or Gemini CLI under the user's subscription),
  `ollama` (local), `openai` (any OpenAI-compatible server), `anthropic`.
- Export to BibTeX, RIS, CSV, JSON and Markdown from any result list.
- Run history (`litsurvey history`) shared by the CLI and the web page.
- `litsurvey web`: local browser interface with a History tab, a photo
  banner, a three-way choice of where the LLM runs (subscription CLI, local
  model, cloud API key) with a privacy banner, BibTeX/RIS/CSV downloads,
  URL detection with DOI/arXiv conversion, and a report-a-bug link.
- `init` and `doctor` commands.
- Per-host rate limiting (Semantic Scholar 1 req/s, arXiv 1 req/3 s) and
  `Retry-After` handling.
