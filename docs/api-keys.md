# API keys and running without them

litsurvey uses six public services. None requires payment. Only one offers
a key, and it is optional.

| Service | Used for | Needs | Without it |
|---|---|---|---|
| OpenAlex | search, citation ranking, fallbacks | nothing; an email address gets the faster "polite pool" | works, slightly slower |
| Semantic Scholar | search, citation graph, recommendations | nothing; a free API key gives a dedicated 1 request/second | works on a shared pool; frequent rate-limit retries, `related` most affected |
| arXiv | search, full text for the agent | nothing | n/a |
| Crossref | TechRxiv and Research Square search | nothing; the same email gets its polite pool | works, slightly slower |
| IACR ePrint | cryptography preprint search | nothing | n/a |
| Unpaywall | open-access lookup | an email address | works with a placeholder address |

## Getting a Semantic Scholar key

1. Open https://www.semanticscholar.org/product/api and find the API key
   request form.
2. Fill in your name, email, and a one-line purpose such as "literature
   search for academic research". Institutional email helps.
3. Approval arrives by email, usually within a day or two. The key looks like
   `s2k-…` and the email states the limit: 1 request per second, cumulative
   across all endpoints.

litsurvey enforces that limit itself, across the CLI and the web page at the
same time, so you will not be blocked for exceeding it.

## Storing the key

Interactive, recommended:

```bash
litsurvey init
```

This writes `~/.litsurvey/config.json` with file permissions 600 and also
asks for your email and the default LLM backend. Or write the file yourself:

```json
{
  "s2_api_key": "s2k-…",
  "openalex_mailto": "you@university.edu"
}
```

Or use environment variables, which override the file: `S2_API_KEY`,
`OPENALEX_MAILTO`.

Check with `litsurvey doctor`; look for the line
`S2 API key : set (s2k-…)`.

Never paste the key into an issue report; `--debug` output does not print it.

## What the key changes

With a key, searches return in a few seconds and the citation-graph and
recommendation commands are reliable. Without a key, Semantic Scholar's
shared pool often answers 429; litsurvey waits and retries (2, 4, 8, 16
seconds), so a search may take half a minute at busy times, and a long agent
run will be slow. OpenAlex and arXiv are unaffected, so `search` still
returns results even when Semantic Scholar is refusing.

## Other keys

- `OPENAI_API_KEY` and `OPENAI_BASE_URL`: for the `openai` backend. Local
  servers such as LM Studio need no key; set the base URL to
  `http://localhost:1234`.
- `ANTHROPIC_API_KEY`: for the `anthropic` backend.

These are only used by `novelty` and `research`. See
[llm-integration.md](llm-integration.md).
