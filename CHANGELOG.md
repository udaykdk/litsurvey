# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]
### Fixed
- An OpenAI-compatible base URL that already ends in `/v1` (for example
  `https://api.goedelmachines.com/v1`) produced `/v1/v1/chat/completions` and a
  404. The version segment is now added only when the base does not carry it,
  for both the chat and the model-listing endpoints.
- arXiv requests now send the configured contact email (`openalex_mailto`)
  in the User-Agent, as arXiv asks automated clients to do, so they can
  reach the operator instead of blocking the address. It is sent only to
  arXiv; the full-text hosts `arxiv.org` and `ar5iv.labs.arxiv.org` are
  also rate-limited now.
  
## [1.2.1] - 2026-10-17
### Added
- **A time limit you can set for `novelty` and `research`.** It was fixed at
  30 minutes for the subscription CLI backends, with no way to change it.
  Now `--timeout MINUTES` sets it for one run, and `agent_timeout` in the
  config (or `LITSURVEY_AGENT_TIMEOUT`) for every run; `0` means no limit.
  The default stays 30 minutes. `litsurvey init` asks for it and
  `litsurvey doctor` shows it, and reports an invalid value as a problem.
- The limit now also applies with a local model or an API key, where there
  was none: at the limit the agent stops searching and writes its report from
  what it has, with a note saying so. The wait for a single model reply,
  fixed at 15 minutes before, grows with the run's limit.
- The skill is listed free on Agensi
  (https://agensi.io/skills/litsurvey-scientific-literature-search-and-prior-art-checks);
  the README and `docs/llm-integration.md` point to it.

### Fixed
- When a subscription CLI agent ran out of time, the run ended in a bare
  error, with no record of which searches the agent had made. Now the run is
  saved with the agent's search log, the message says how to raise the
  limit, and the command exits with code 3 so scripts can tell.

### Changed
- The Claude Code skill (`integrations/claude-code/litsurvey/SKILL.md`) now
  opens with the install step and links, so it works when distributed on its
  own (for example on a skills marketplace), and no longer describes the
  agent commands as local-only.

## [1.2.0] - 2026-10-10

Most of these were found by Anant Goyal in the same review as the 1.1.1
security fixes.

### Fixed
- **arXiv returned almost nothing for multi-word queries.** The whole query was
  sent as one exact phrase, so "deep learning inverse scattering" found 0
  papers. Every word is now required in any field (stop words such as "of"
  are dropped, since arXiv does not index them and they would empty the
  result). Three test queries went from 1, 0 and 0 arXiv papers to 20 each.
- Duplicates in merged results. A record now matches another when its DOI,
  arXiv id or title agrees, so: every version of a TechRxiv or Research
  Square preprint is one paper (they register a DOI per version; one search
  had listed the same preprint 8 times); an arXiv DOI meets the same arXiv
  id; a preprint meets its journal version under the same long title. A
  matching title never joins records whose journal DOIs (or arXiv ids)
  disagree. On four real queries this removed every repeated title and year
  (5, 10, 8 and 12 before).
- Titles in non-Latin scripts were all reduced to the same empty key and
  merged into one paper; two different papers titled "Editorial" were merged;
  long titles were compared only on their first 80 characters. Titles are now
  compared in full, and a short title also needs the same year.
- Two runs in the same second got the same history id, and the second
  overwrote the first. Ids now carry a random part, and an id already in use
  is never reused.
- BibTeX: `#`, `_`, `$`, `~`, `^` and literal braces in titles, venues,
  names and abstracts are escaped (an unmatched brace used to break the whole
  file), and "Martin Luther King Jr." becomes `King, Jr., Martin Luther`
  (citation key `king…`). Checked by compiling with pdflatex and bibtex.
- Old-style arXiv ids are accepted without the `ARXIV:` prefix
  (`hep-th/9901001`).
- With Ollama, the agent's conversation silently overflowed the default
  context window, dropping its instructions first. litsurvey now asks for a
  32k window unless the model's Modelfile already sets a larger one.
- A reply cut off at the model's length limit (Anthropic `max_tokens`,
  OpenAI-compatible `length`, Ollama `length`) now ends with a visible note
  instead of stopping mid-sentence without warning.
- The search log of a subscription-CLI run picked up any search the user ran
  by hand at the same time. The agent's own runs are now tagged and only
  those are listed.
- Several web jobs running at once could each decide no wait was needed and
  exceed a source's rate limit together. Rate limiting is now locked per host
  within one process. Two separate litsurvey processes (say the command line
  and the web page) are still spaced only on a best-effort basis.
- Finished web jobs stayed in memory until the server stopped. Jobs that
  finished more than an hour earlier are now dropped whenever a new job
  starts (their runs remain in History).

### Changed
- PubMed carries half weight in the rank fusion, like the other
  single-field sources: for engineering queries its own top hits were often
  biomedical papers with no citations.
- The README now says plainly that a Semantic Scholar key is needed in
  practice: without one the shared pool often refuses every request.

### Added
- **Citation check.** The search log now keeps the identifiers of exactly
  the papers the model was shown, and every `novelty` and `research` report
  ends with a note listing any DOI or arXiv id (including arXiv abs, pdf and
  html links) that did not come from a search in that run. References without
  an identifier are not checked. With a subscription CLI only the agent's own
  tagged searches count.
- **"Update available" in the web page.** When PyPI has a newer version, a
  small link appears to the right of the History tab. The local server asks
  pypi.org at most once a day; `"update_check": false` in the config (or
  `LITSURVEY_UPDATE_CHECK=false`) turns this off.
- The web page's header wraps on narrow screens instead of running off the
  edge.

## [1.1.1] - 2026-10-10

### Security
These were found and reported privately by Anant Goyal. Upgrade if you use
`litsurvey web`.

- The web server accepted requests from other web sites. A page open in the
  same browser could start jobs and, through the output-file field, write a
  file anywhere in the user's home folder; a page that points its own domain
  name at 127.0.0.1 could read the run history. The server now refuses any
  request whose `Host` is not its own loopback address and port, any request
  carrying another site's `Origin` or `Sec-Fetch-Site: cross-site`, and any
  POST that is not `application/json`. The web API no longer takes an output
  path at all; results are downloaded from the page.
- `is_local()` decided "local" by a substring test, so a cloud URL such as
  `https://localhost.example.com` was reported as a local model. The host name
  is now parsed and compared exactly, here and in the page's banner.
- `~/.litsurvey` is now readable by its owner only (mode 700, tightened at
  start-up on existing installs) and run files and the history index are
  mode 600.
- Codex CLI now gets the prompt on stdin, so the claim is not visible to other
  accounts in the process list.
- Claude Code is started with only its shell tool (`--tools Bash`), and its
  shell may run only the five lookup commands (`litsurvey search`, `paper`,
  `cites`, `refs`, `related`). Before, its read tools were available without
  asking, and `litsurvey history show` accepted a path such as `../../file`.
- History run ids are checked against litsurvey's own format, so neither the
  command line nor the web API can be pointed at another file.
- When a subscription agent runs `litsurvey`, it refuses `--out`, `history`,
  `init`, `web` and the agent commands (an environment variable marks the
  agent's shell). This applies to Codex, Gemini and Antigravity as well.
- Search results reach the model inside marked blocks, with an instruction
  that nothing in them is a command. With a local model or an API key, a
  search query that repeats eight or more consecutive words of the user's
  input is refused. `docs/confidentiality.md` now says plainly which parts of
  the confidentiality rules are instructions and which are enforced, and what
  each subscription CLI could do if a hostile abstract steered it.

### Added
- `SECURITY.md`: how to report a vulnerability privately.
- **Google Antigravity CLI (`agy`) support** as a subscription CLI backend
  alongside Claude Code, Codex, and Gemini CLI. Automatically probes reasoning
  effort from `agy --help` (defaulting to `medium`).

## [1.1.0] - 2026-09-12

### Added
- **PubMed** as a default search source, through the NCBI E-utilities
  (esearch for the matching record ids, efetch for the records, so abstracts
  come back and the LLM agents can judge relevance). More than 40 million
  biomedical citations, authoritatively indexed; the general indexes cover
  much of the same ground but not with PubMed's subject indexing. Journal
  articles and book/chapter records are both parsed.
- **Europe PMC** as an opt-in source (`--sources europepmc`): PubMed's ground
  again, but with citation counts and the bioRxiv/medRxiv preprints. Off by
  default because it largely repeats PubMed.
- Subscription CLI backends now run at a deliberate model and reasoning
  effort instead of the tool's own maximum. `litsurvey init` asks the
  installed binary what it supports and picks one model below the best at an
  effort level in the middle of the range — for Claude Code, Opus at `high`.
  Stored as `cli_model` / `cli_effort` in the config (`"-"` means "leave the
  tool at its own default"), shown by `litsurvey doctor`, and overridable
  with `LITSURVEY_CLI_MODEL` / `LITSURVEY_CLI_EFFORT`. The stored choice
  belongs to the tool it was made for, so switching `cli_tool` re-runs the
  poll instead of passing a Claude model name to codex.

### Fixed
- **The `codex` CLI backend was broken**: `codex exec --full-auto` no longer
  exists (removed by codex-cli; it fails with "unexpected argument"). The
  command is now `codex exec --skip-git-repo-check --sandbox workspace-write
  --add-dir ~/.litsurvey -c sandbox_workspace_write.network_access=true`.
  Without the sandbox flags codex has no network — every `litsurvey` call
  inside it returns nothing while codex still exits 0 and writes a
  confident, empty report — refuses to start outside a git repository, and
  cannot write the run history. Codex is given an empty temporary directory
  as its working root, so its write sandbox covers a scratch area and
  `~/.litsurvey` rather than the directory you started from. Verified end to
  end against codex-cli 0.153.4.
- A subscription CLI's final report is now read from a file it writes
  (`-o`), not from stdout, which also carries progress and tool-call
  chatter.

### Notes
- DBLP was considered and left out: its search API sits behind a
  proof-of-work bot wall on every mirror (dblp.org, dblp.uni-trier.de,
  dblp.dagstuhl.de), which litsurvey will not try to defeat.

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
