"""The agent loop for `novelty` and `research`: an LLM plans queries and reads
results; this module runs the tools and keeps the search log."""
import json
import sys
import time

from . import backends, history, papers
from .sources import arxiv, run_search, semanticscholar

CONFIDENTIALITY = """STRICT CONFIDENTIALITY RULE: search queries must be short generic keyword phrases about the topic (e.g. "ionic liquid passivation perovskite tandem"). NEVER put verbatim sentences, author names, or identifying phrasing from a manuscript into a query."""

NOVELTY_SYSTEM = f"""You are a scientific literature scout assessing the NOVELTY of a research claim, as part of confidential peer review.

{CONFIDENTIALITY}

Method:
1. Decompose the claim into 3-6 DIVERSE keyword queries: synonyms, adjacent fields, older terminology, method-centric and application-centric phrasings.
2. Call search_papers for each. Judge relevance from titles/abstracts.
3. For the 1-3 closest matches, call get_citations, get_references and/or get_related to walk the citation graph and recommendation engine for even closer prior work.
4. If one paper is pivotal and is on arXiv, you may call read_paper ONCE to read its full text before judging how closely it anticipates the claim.
5. Stop searching when additional queries stop surfacing new relevant work.

Then write the final report in markdown:
## Novelty assessment: <short claim restatement>
### Closest prior work
For each (max 8): title, year, venue, citations, one sentence on HOW it relates and WHERE it differs.
### What appears novel / What is prior art
### Verdict
One of: [clearly novel | incremental advance | substantially anticipated | cannot determine], with confidence (low/med/high) and one-paragraph justification.
### Suggested reviewer citations
Bulleted list, using ONLY titles, years, venues and DOIs/URLs that appeared in tool results. Never cite from memory.

Be skeptical: absence of hits in your queries is weak evidence of novelty; say so when coverage feels thin."""

RESEARCH_SYSTEM = f"""You are a scientific literature research analyst producing a state-of-the-art survey answer to a research question, for an academic reader.

Method:
1. Decompose the question into 2-5 sub-questions covering its distinct aspects.
2. For each sub-question run search_papers with generic keyword queries; use synonyms and both method-centric and application-centric phrasings.
3. Use get_related / get_citations / get_references on the most central papers to find work that keyword search misses.
4. Optionally read_paper on 1-2 pivotal arXiv papers whose details matter to the answer.
5. Stop when new queries stop changing the picture.

Then write the final report in markdown:
## <question restated as a title>
A synthesized answer organized by theme (not by query), with inline numbered citations like [1] after each claim.
### Open problems / disagreements
### Coverage caveats
What your searches may have missed and why.
## Sources
Numbered list matching the inline citations. Use ONLY titles, years, venues, DOIs/URLs that appeared in tool results — never cite from memory.

{CONFIDENTIALITY}"""

TOOLS = [
    {"name": "search_papers",
     "description": "Search OpenAlex + Semantic Scholar + arXiv with a generic keyword query. Returns top papers with abstracts.",
     "parameters": {"type": "object", "properties": {
         "query": {"type": "string", "description": "3-8 generic keywords, no manuscript text"},
         "year_from": {"type": "integer", "description": "optional: only papers from this year on"}},
         "required": ["query"]}},
    {"name": "get_citations",
     "description": "Papers that CITE the given paper (forward snowball). id from a search result.",
     "parameters": {"type": "object", "properties": {"paper_id": {"type": "string"}},
                    "required": ["paper_id"]}},
    {"name": "get_references",
     "description": "Papers the given paper CITES (backward snowball). id from a search result.",
     "parameters": {"type": "object", "properties": {"paper_id": {"type": "string"}},
                    "required": ["paper_id"]}},
    {"name": "get_related",
     "description": "Papers SIMILAR to the given paper via a recommendation engine; finds relevant work that keyword queries miss. id from a search result.",
     "parameters": {"type": "object", "properties": {"paper_id": {"type": "string"}},
                    "required": ["paper_id"]}},
    {"name": "read_paper",
     "description": "Read the FULL TEXT of an arXiv paper (arXiv ids only). Expensive: use on at most 1-2 pivotal papers.",
     "parameters": {"type": "object", "properties": {
         "arxiv_id": {"type": "string", "description": "e.g. 2404.19756"}},
         "required": ["arxiv_id"]}},
]

CLI_TASK = """You are running non-interactively inside a script. Your only research tool is the shell command `litsurvey` (already installed). Map the tools named above to these commands and use nothing else (no web search, no browsing, no file writes):
  search_papers   -> litsurvey search "generic keywords" -n 10 --json [--year-from YEAR]
  get_citations   -> litsurvey cites <id> -n 10 --json
  get_references  -> litsurvey refs <id> -n 10 --json
  get_related     -> litsurvey related <id> -n 10 --json
  read_paper      -> not available here; judge from abstracts
<id> is the "id" field of a result (Semantic Scholar hash, DOI:..., or ARXIV:...).
Run commands one at a time, never in parallel (the APIs allow 1 request/second). Use at most {budget} commands.
When finished, print ONLY the final report in markdown. No preamble, no explanation of what you did."""

KINDS = {"novelty": (NOVELTY_SYSTEM, "Assess the novelty of this claim:\n\n{text}", "novelty report"),
         "research": (RESEARCH_SYSTEM, "Research question:\n\n{text}", "research report")}


def dispatch(name, args, log):
    """Run one tool; append a log entry; return a JSON-serialisable result."""
    entry = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "tool": name, "args": args}
    log.append(entry)
    try:
        if name == "search_papers":
            plist, stats = run_search(args["query"], limit=10, year_from=args.get("year_from"))
            entry["hits"] = stats
            entry["merged"] = len(plist)
            return papers.compact(plist)
        if name in ("get_citations", "get_references"):
            direction = "citations" if name == "get_citations" else "references"
            plist = semanticscholar.linked(args["paper_id"], direction, limit=15)
            entry["merged"] = len(plist)
            return papers.compact(plist)
        if name == "get_related":
            plist = semanticscholar.related(args["paper_id"], limit=15)
            entry["merged"] = len(plist)
            return papers.compact(plist)
        if name == "read_paper":
            txt = arxiv.full_text(args["arxiv_id"])
            entry["chars"] = len(txt)
            return {"full_text": txt}
        entry["error"] = f"unknown tool {name}"
        return {"error": entry["error"]}
    except Exception as e:  # noqa: BLE001 - report the failure to the model, keep going
        entry["error"] = str(e)
        return {"error": str(e)}


def run(kind, text, backend=None, model=None, rounds=8, progress=None):
    """Run the agent. Returns {"report", "log", "backend", "model", "rounds_used"}."""
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {list(KINDS)}")
    system, user_tmpl, kind_name = KINDS[kind]
    backend, model = backends.resolve(backend, model)
    say = progress or (lambda s: print(s, file=sys.stderr))
    if backend == "cli":
        return _run_cli(kind, text, model, rounds, say)
    local = backend in backends.LOCAL_BACKENDS
    say(f"[agent] backend={backend} model={model} "
        f"({'local, nothing leaves this machine except keyword queries' if local else 'CLOUD backend: the text below is sent to the provider'})")
    messages = [{"role": "system", "content": system},
                {"role": "user", "content": user_tmpl.format(text=text)
                 + f"\n\nToday's year is {time.localtime().tm_year}. Begin searching."}]
    log, final, used = [], None, 0
    for step in range(rounds):
        used = step + 1
        say(f"[agent] thinking… (round {used}/{rounds})")
        reply = backends.chat(backend, model, messages, tools=TOOLS)
        messages.append({"role": "assistant", "content": reply["content"],
                         "tool_calls": reply["tool_calls"]})
        if not reply["tool_calls"]:
            final = reply["content"]
            break
        for call in reply["tool_calls"]:
            say(f"[agent] {call['name']}({json.dumps(call['args'], ensure_ascii=False)})")
            result = dispatch(call["name"], call["args"], log)
            cap = 36000 if call["name"] == "read_paper" else 9000
            messages.append({"role": "tool", "tool_call_id": call["id"], "name": call["name"],
                             "content": json.dumps(result, ensure_ascii=False)[:cap]})
    if final is None:
        say("[agent] round limit reached, requesting final report")
        messages.append({"role": "user", "content":
                         f"Stop searching. Write the final {kind_name} now, based on everything found so far."})
        final = backends.chat(backend, model, messages)["content"]
    return {"report": final, "log": log, "backend": backend, "model": model,
            "rounds_used": used}


_CLI_MODE_TOOL = {"search": "search_papers", "cites": "get_citations", "refs": "get_references",
                  "related": "get_related", "oa": "open_access", "paper": "paper"}


def _run_cli(kind, text, tool, rounds, say):
    """Delegate the whole task to a subscription CLI agent (Claude Code, Codex, Gemini)."""
    system, user_tmpl, kind_name = KINDS[kind]
    say(f"[agent] backend=cli tool={tool} (SUBSCRIPTION CLI: your text and everything the agent "
        f"reads are sent to that vendor under your subscription)")
    budget = max(4, rounds * 3)
    prompt = (system + "\n\n" + CLI_TASK.format(budget=budget) + "\n\n"
              + user_tmpl.format(text=text)
              + f"\n\nToday's year is {time.localtime().tm_year}. Begin.")
    say(f"[agent] handing over to {tool}; this can take several minutes and shows no progress "
        f"until it finishes. Its litsurvey commands will appear in the search log.")
    start = time.time()
    report = backends.run_cli(tool, prompt)
    log = []
    for r in history.runs_since(start - 1):
        if r["mode"] not in _CLI_MODE_TOOL:
            continue
        inp = r["inputs"].get("text", "")
        key = "query" if r["mode"] == "search" else ("doi" if r["mode"] == "oa" else "paper_id")
        entry = {"time": r["time"], "tool": _CLI_MODE_TOOL[r["mode"]], "args": {key: inp},
                 "merged": r.get("n_results")}
        try:
            stats = history.load(r["id"]).get("stats")
            if stats:
                entry["hits"] = stats
        except OSError:
            pass
        log.append(entry)
    say(f"[agent] {tool} finished; {len(log)} litsurvey commands recorded")
    return {"report": report, "log": log, "backend": "cli", "model": tool, "rounds_used": None}


def search_log_markdown(log, backend=None, model=None):
    """Appendix listing every query run, for reproducibility / PRISMA-style reporting."""
    lines = ["## Search log", ""]
    if backend:
        lines.append(f"Agent backend: `{backend}` model: `{model}`  ")
    lines.append(f"Generated by litsurvey on {time.strftime('%Y-%m-%d')}. "
                 "Sources: OpenAlex, Semantic Scholar, arXiv.")
    lines.append("")
    lines.append("| # | time | tool | input | hits |")
    lines.append("|---|---|---|---|---|")
    for i, e in enumerate(log, 1):
        arg = e["args"].get("query") or e["args"].get("paper_id") or e["args"].get("arxiv_id") or ""
        if e.get("error"):
            hits = "error: " + e["error"][:60]
        elif "hits" in e:
            hits = ", ".join(f"{k} {v}" for k, v in e["hits"].items()) + f" → {e.get('merged', '?')} merged"
        elif "chars" in e:
            hits = f"{e['chars']} chars read"
        else:
            hits = str(e.get("merged", ""))
        lines.append(f"| {i} | {e['time'][11:]} | {e['tool']} | {arg} | {hits} |")
    return "\n".join(lines) + "\n"
