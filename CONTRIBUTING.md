# Contributing

## Reporting a bug

Open an issue with the bug template. Include the command, the output with
`--debug`, and the output of `litsurvey --version` and `litsurvey doctor`.
Remove your API key if it appears anywhere. Most problems are API changes on
the provider side, and the exact URL from `--debug` is what makes them
fixable.

## Development setup

```bash
git clone https://github.com/udaykdk/litsurvey
cd litsurvey
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
python -m pytest
```

The tests are offline: every HTTP call is mocked. Please keep it that way, so
CI does not depend on API availability. If you change how a source is parsed,
add a fixture for the new response shape in `tests/test_sources.py`.

## Design rules

- **Zero runtime dependencies.** Standard library only. This keeps
  installation trivial on university machines and inside agents. If a
  feature needs a dependency, make it optional and import it lazily.
- **Only public, official APIs, with one documented exception.** No
  scraping of sites whose terms forbid it (Google Scholar in particular).
  New sources should have a documented API and a rate limit we can honour in
  `http.HOST_INTERVAL`. The IACR ePrint source reads a server-rendered
  search page because the archive offers no search API and does not
  prohibit it; it is rate-limited to one request per two seconds and is
  isolated so that a markup change only silences that source.
- **Nothing leaves the machine that the docs do not say leaves.** Any change
  to what is sent where must be reflected in `docs/confidentiality.md`.
- **Every successfully completed run is recorded** in the history store
  (search runs with per-source hit counts), so results are reproducible.

## Adding a source

1. Create `litsurvey/sources/<name>.py` with a `search(query, limit,
   year_from)` function that returns a list of `papers.make(...)` records
   with `sources=["<name>"]`.
2. Register it in `litsurvey/sources/__init__.py` (`SOURCES`).
3. Add the host's rate limit to `http.HOST_INTERVAL`.
4. Add a parsing test with a fixture, and a line in `docs/cli.md`.

## Pull requests

Small, focused pull requests are easier to review. Add a line under
*Unreleased* in `CHANGELOG.md`. CI runs the tests on Linux, macOS and
Windows with Python 3.10, 3.12 and 3.13.

## Releasing (maintainers)

1. Bump `version` in `pyproject.toml`, `litsurvey/__init__.py` and
   `CITATION.cff`; move the changelog entries under the new version.
2. `git tag -a vX.Y.Z -m "vX.Y.Z"` and push the tag.
3. Create a GitHub release from the tag; the publish workflow uploads to
   PyPI via trusted publishing.
