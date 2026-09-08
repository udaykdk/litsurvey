# litsurvey

Scientific literature search from the command line or a local web page, with
optional LLM-driven novelty assessment and state-of-the-art surveys.
One Python package, **zero dependencies**, Python 3.10 or newer.

It searches the scholarly indexes directly, OpenAlex, Semantic Scholar and
arXiv, then de-duplicates and fuses the rankings. It walks the citation graph,
finds legal open-access copies, and exports BibTeX, RIS and CSV. When you want
more than a list, a local or cloud LLM can plan the searches, read the
results and write a prior-art verdict or a cited survey, with a reproducible
search log.

It was built for peer reviewers who must not leak a confidential manuscript:
the manuscript never has to leave your machine. Only short keyword queries go
to the public APIs. See [docs/confidentiality.md](docs/confidentiality.md).

## Install

```bash
pipx install litsurvey          # recommended: isolated, gives the `litsurvey` command
# or
pip install litsurvey
# or, from a clone, with no install at all
python3 -m litsurvey --help
```

Optional but recommended, one minute: get a free Semantic Scholar API key
and run `litsurvey init` to store it. Without a key everything still works,
only slower. See [docs/api-keys.md](docs/api-keys.md). `litsurvey doctor`
checks the setup and ends with a one-line verdict; run it once after
installing, and again if something fails.

## Quick start

```bash
litsurvey search "physics informed neural networks inverse problems" --year-from 2022
litsurvey cites "DOI:10.1016/j.cma.2022.114823"          # who built on this paper
litsurvey related "ARXIV:2404.19756"                      # similar papers, different vocabulary
litsurvey oa "10.1016/j.cma.2022.114823"                  # legal free PDF
litsurvey search "graphene thermal conductivity" --out refs.bib   # BibTeX, RIS, CSV by extension
litsurvey web                                             # the same, in your browser
```

With an LLM backend, any one of: the command-line agent of a subscription
you already have (Claude Code, Codex CLI or Gemini CLI), a local Ollama
model, or an OpenAI-compatible or Anthropic API key:

```bash
litsurvey novelty "adaptive collocation sampling in physics-informed neural networks" --out claim.md
litsurvey research "neural network surrogates for topology optimization: approaches and open problems" --out survey.md
litsurvey novelty "..." --backend cli --model claude        # use Claude Code under your Claude subscription
litsurvey novelty "..." --backend ollama --model qwen3:30b  # fully local
```

## What needs an LLM, and what leaves your machine

| Command | LLM | What is sent out, and to whom |
|---|---|---|
| `search`, `paper`, `cites`, `refs`, `related` | no | your query or a paper ID, to OpenAlex, Semantic Scholar, arXiv, Crossref and eprint.iacr.org |
| `oa` | no | one DOI, to Unpaywall |
| `history`, `init`, `doctor`, `web` | no | nothing (doctor makes one test query per source) |
| `novelty`, `research` with the **cli** backend (Claude Code, Codex CLI, Gemini CLI) | yes, vendor cloud | your claim or question and everything the agent reads, to that vendor under your subscription |
| `novelty`, `research` with the **ollama** backend | yes, local | only the keyword queries the model composes, to the same three APIs |
| `novelty`, `research` with **openai** or **anthropic** | yes, cloud | your claim or question text, and every search result, to that provider |

The full information-flow discussion, including what to do for a
confidential manuscript, is in [docs/confidentiality.md](docs/confidentiality.md).

## Documentation

- [docs/cli.md](docs/cli.md): every command, option and output format, with sample output
- [docs/web.md](docs/web.md): the browser interface and the History tab
- [docs/use-cases.md](docs/use-cases.md): seven scenarios with the exact commands, from student discovery to confidential peer review
- [docs/confidentiality.md](docs/confidentiality.md): what leaves the machine, per mode and backend
- [docs/api-keys.md](docs/api-keys.md): getting and storing the Semantic Scholar key; running without one
- [docs/llm-integration.md](docs/llm-integration.md): LLM backends and models; using litsurvey from Claude Code, Codex and other agents
- [CONTRIBUTING.md](CONTRIBUTING.md): reporting bugs, running tests, adding a source

## Coverage, and Google Scholar

Six sources are searched by default: OpenAlex (about 250 million works),
Semantic Scholar (about 220 million), arXiv, and three preprint portals:
TechRxiv and Research Square (through Crossref, by their DOI prefixes) and
the IACR Cryptology ePrint Archive (which has no search API, so litsurvey
reads its search page; if that page changes, only that source goes quiet).
`--sources` restricts the set; `crossref` (all DOI-registered works) can be
added but overlaps OpenAlex. Together they cover most of what Google
Scholar shows, except some grey literature (technical reports, theses,
standards).
Google Scholar has no API and its terms of service forbid automated access,
so litsurvey does not scrape it. `litsurvey search --scholar` prints the
matching Google Scholar URL so you can compare by hand, and the web page has
the same link.

## Data attribution

Results come from [OpenAlex](https://openalex.org) (CC0),
[Semantic Scholar](https://www.semanticscholar.org) (Semantic Scholar Open
Data Platform, Allen Institute for AI), [arXiv](https://arxiv.org) (thank you
to arXiv for use of its open access interoperability) and
[Unpaywall](https://unpaywall.org). If you publish work that used these
results, please credit them.

## Credits

The banner of the web page uses slivers of an aerial beach photograph by
[Lance Asper on Unsplash](https://unsplash.com/@lance_asper).

## Citing

See [CITATION.cff](CITATION.cff). GitHub shows a "Cite this repository"
button on the project page.

## License

MIT. See [LICENSE](LICENSE).
