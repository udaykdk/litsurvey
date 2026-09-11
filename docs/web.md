# The browser interface

```bash
litsurvey web
```

This starts a small web server on your own machine (`127.0.0.1:8765`) and
opens the page in your default browser. Nothing is served to the network;
only programs on your computer can reach it. Stop it with Ctrl-C in the
terminal.

The page covers the main search, lookup, agent and history operations, for
people who prefer forms to flags. A few options stay command-line only:
`--sources`, `--scholar`, `--debug`, `init` and `doctor`.

## The Run tab

1. **Mode.** Radio buttons in two groups: *Search and lookup* (no LLM) and
   *LLM agent* (needs a backend). Each has a one-line description.
2. **Input box.** Its label changes with the mode: keyword query, paper ID,
   DOI, claim, or research question.
3. **Options.** Max results and a from-year for searches. For the agent
   modes, a box asks where the LLM runs, with three choices in the order
   most people have them: a subscription command-line agent (Claude Code,
   Codex CLI, Gemini CLI), a local Ollama model, or a cloud API key. The
   box is greyed out until Novelty or Research is selected, and the page
   remembers your last choice. The model box offers the Ollama models it
   can see.
4. **Output file.** Optional. An absolute path. For paper lists the
   extension picks the format (`.bib`, `.ris`, `.csv`, `.json`, `.md`);
   agent reports are always Markdown, with a `.log.json` beside them; an
   open-access lookup is always written as JSON.
5. **The privacy banner.** Before you press Run, a green or orange banner
   says what will leave the machine for this mode and backend. Orange means
   a cloud backend will receive your text.
6. **Run.** Ctrl-Enter (Cmd-Enter on a Mac) in the input box also runs.

While an agent runs, the progress lines (`[agent] search_papers(...)`)
stream into a dark box, so you can see the queries as they are made.

If you typed a title where an id was expected, the page searches for it
and shows the closest papers with a "Use this paper" button on each; the
lookup you asked for runs on the one you pick. Every paper list has sort
buttons: relevance (the fused ranking), citations, or year.

Results appear below: a paper list with links, citation counts and IDs, or
the rendered report with a collapsible search log. Download buttons give
BibTeX, RIS, CSV, JSON or Markdown of the same run. For a search, a link
opens the same query in Google Scholar for comparison.

## The History tab

Every completed run, from the page or the command line, is listed with time, mode,
input and result count. Click a row to see it again, with the same download
buttons. The delete button removes a run from the store.

The store is `~/.litsurvey/runs/`; see
[confidentiality.md](confidentiality.md) for what it contains.

## Notes

- The page is a single file with no external resources, so it works
  offline apart from the API calls themselves.
- Long agent runs continue on the server even if you close the tab; reopen
  the page and look in History once they finish.
- To use a different port: `litsurvey web --port 9000`. To start without
  opening a browser: `--no-browser`.
- The server is single-user by design. Do not expose it to a network; it has
  no authentication.
