# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [1.0.1] - 2026-09-11

### Fixed
- Without a Semantic Scholar key, searches took about a minute because the
  refusing shared pool was retried five times; keyless retries are now
  capped at two (about ten seconds), and `doctor` reports a keyless Semantic
  Scholar failure as a warning instead of a problem.
- `related` returned nothing when Semantic Scholar answered with an empty
  list; it now falls back to OpenAlex related works, which also no longer
  include the paper itself.
- Custom subscription-CLI commands on Windows lost the backslashes in paths.
- The web page's Search label listed three sources; it now says six.

### Added
- The web page accepts `?mode=<mode>&text=<query>` in the URL to preselect a
  mode and fill the input.
- README: screenshot, and how to get the Semantic Scholar key and what
  happens without it.

## [1.0.0] - 2026-09-11

First public release.

### Added
- `search`: fused, de-duplicated keyword search over OpenAlex, Semantic Scholar,
  arXiv, TechRxiv, Research Square (via Crossref) and the IACR ePrint archive,
  with `--sort relevance|citations|year`.
- `paper`, `cites`, `refs`, `related`: one paper and its citation neighbourhood;
  a title is accepted in place of an id, with a candidate list and `--pick N`.
  `cites`/`refs` rank by citation count via OpenAlex, with Semantic Scholar as
  fallback; `related` and `paper` fall back to OpenAlex when Semantic Scholar
  is unavailable.
- `oa`: legal open-access copies via Unpaywall.
- `novelty` and `research`: LLM-driven agents with pluggable backends and a
  reproducible search log. Backends: `cli` (delegates the task to a signed-in
  Claude Code, Codex CLI or Gemini CLI under the user's subscription),
  `ollama` (local), `openai` (any OpenAI-compatible server, `--base-url` for
  OpenRouter, LM Studio and others), `anthropic`.
- Export to BibTeX, RIS, CSV, JSON and Markdown from any result list.
- Run history (`litsurvey history`) shared by the CLI and the web page.
- `litsurvey web`: local browser interface with a History tab, a photo
  banner, a three-way choice of where the LLM runs (subscription CLI, local
  model, cloud API key) with a privacy banner, BibTeX/RIS/CSV downloads,
  URL detection with DOI/arXiv conversion, "waiting for <source>" status
  while a run is in progress, and a report-a-bug link.
- `init` and `doctor` commands.
- Per-host rate limiting (Semantic Scholar 1 req/s, arXiv 1 req/3 s) and
  `Retry-After` handling.
