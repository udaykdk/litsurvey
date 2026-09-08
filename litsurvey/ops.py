"""One entry point for every mode, shared by the CLI and the web page."""
import json
import os
import time

from . import agent, export, history, papers
from .sources import openalex, run_search, semanticscholar, unpaywall

LIST_MODES = ("search", "paper", "cites", "refs", "related")
ID_MODES = ("paper", "cites", "refs", "related", "oa")
AGENT_MODES = ("novelty", "research")
MODES = LIST_MODES + ("oa",) + AGENT_MODES
CANDIDATES = 8


def resolve_title(text, params, progress=None):
    """A title or author query instead of an id: search, auto-pick an exact title
    match or the --pick'd candidate, else return None with params["_candidates"] set."""
    say = progress or (lambda s: print(s, file=__import__("sys").stderr))
    plist, _ = run_search(text, limit=CANDIDATES)
    plist = [p for p in plist if papers.best_id(p)][:CANDIDATES]
    if not plist:
        raise ValueError(f"no paper found for {text!r}; try fewer words, or give a DOI")
    pick = params.get("pick")
    if pick:
        i = int(pick)
        if not 1 <= i <= len(plist):
            raise ValueError(f"--pick must be between 1 and {len(plist)}")
        chosen = plist[i - 1]
    elif papers.norm_title(plist[0]["title"]) == papers.norm_title(text):
        chosen = plist[0]
    else:
        params["_candidates"] = plist
        return None
    say(f"[note] using: {chosen['title']} ({chosen['year']}) id {papers.best_id(chosen)}")
    params["resolved_id"] = papers.best_id(chosen)
    params["resolved_title"] = chosen["title"]
    return papers.best_id(chosen)


def run_mode(mode, params, progress=None):
    """params keys: text (query / id / doi / claim), n, year_from, sources,
    backend, model, rounds. Returns a result dict."""
    text = papers.clean_text(params.get("text"))
    if not text:
        raise ValueError("input text is empty")
    text, note = papers.normalize_input(text)
    params["text"] = text          # the cleaned form is what gets recorded
    if note:
        (progress or (lambda s: print(s, file=__import__("sys").stderr)))("[note] " + note)
    n = int(params.get("n") or 15)
    if mode in ID_MODES and not papers.is_paper_id(text):
        chosen = resolve_title(text, params, progress)
        if chosen is None:
            return {"candidates": params["_candidates"], "query": text, "needs_choice": True}
        text = chosen
    if mode in ID_MODES:
        text = papers.canonical_id(text)
        if mode == "oa" and not text.upper().startswith("DOI:"):
            raise ValueError("open-access lookup needs a DOI; this paper has none")
        if mode == "oa":
            text = text[4:]
    if mode == "search":
        plist, stats = run_search(text, limit=n, year_from=params.get("year_from"),
                                  sources=params.get("sources"))
        return {"papers": plist[:n], "stats": stats}
    if mode == "paper":
        return {"papers": [paper_record(text, progress)]}
    if mode in ("cites", "refs"):
        return {"papers": linked_papers(mode, text, n, params.get("sort") or "citations", progress)}
    if mode == "related":
        return {"papers": related_papers(text, n, params.get("sort") or "relevance", progress)}
    if mode == "oa":
        return {"oa": unpaywall.lookup(text)}
    if mode in AGENT_MODES:
        return agent.run(mode, text, backend=params.get("backend"),
                         model=params.get("model"), rounds=int(params.get("rounds") or 8),
                         progress=progress)
    raise ValueError(f"unknown mode {mode!r}")


def _say(progress):
    return progress or (lambda s: print(s, file=__import__("sys").stderr))


def paper_record(pid, progress=None):
    """One paper's record: Semantic Scholar first, OpenAlex when the id is a DOI."""
    try:
        return semanticscholar.paper(pid)
    except Exception as e:  # noqa: BLE001
        if not pid.upper().startswith("DOI:"):
            raise
        _say(progress)(f"[warn] Semantic Scholar failed ({e}); using OpenAlex")
        return openalex.paper_by_doi(pid[4:])


def related_papers(pid, n, sort, progress=None):
    """Similar papers: Semantic Scholar's recommender first; OpenAlex related_works
    as the fallback when it fails and the paper has a DOI."""
    say = _say(progress)
    try:
        return sort_papers(semanticscholar.related(pid, limit=n), sort)
    except Exception as e:  # noqa: BLE001
        if not pid.upper().startswith("DOI:"):
            raise RuntimeError(f"Semantic Scholar recommendations failed ({e}) and this id has no DOI "
                               f"for the OpenAlex fallback; try again in a minute or use the DOI") from None
        say(f"[warn] Semantic Scholar recommendations failed ({e}); using OpenAlex related works")
    work = openalex.work_by_doi(pid[4:])
    return openalex.related(work, limit=n, sort=sort if sort != "relevance" else "citations")


def linked_papers(mode, pid, n, sort, progress=None):
    """Citing papers / references, ranked by citation count (or year).

    OpenAlex can sort these server-side, so it is used whenever the paper has a
    DOI. Semantic Scholar cannot sort its citation lists (they come newest
    first), so it is the fallback for papers without a DOI."""
    say = progress or (lambda s: print(s, file=__import__("sys").stderr))
    doi = pid[4:] if pid.upper().startswith("DOI:") else ""
    if not doi:
        try:
            doi = semanticscholar.paper(pid)["doi"]
        except Exception:  # noqa: BLE001
            doi = ""
    if doi:
        try:
            work = openalex.work_by_doi(doi)
            if mode == "cites":
                out = openalex.citing(work["id"], limit=n, sort=sort)
            else:
                out = openalex.references(work, limit=n, sort=sort)
            if out:
                return out
            say("[note] OpenAlex has no " + ("citations" if mode == "cites" else "reference list")
                + " for this paper (common for preprints); trying Semantic Scholar")
        except Exception as e:  # noqa: BLE001
            say(f"[warn] OpenAlex lookup failed ({e}); falling back to Semantic Scholar (newest first)")
    else:
        say("[note] paper has no DOI; using Semantic Scholar, whose citation lists come newest first")
    direction = "citations" if mode == "cites" else "references"
    plist = semanticscholar.linked(pid, direction, limit=max(n, 100))
    return sort_papers(plist, sort)[:n]


def report_text(mode, text, result, with_log=True):
    head = f"<!-- litsurvey {mode} report -->\n<!-- input: {text} -->\n\n"
    body = result["report"].rstrip() + "\n"
    if with_log and result.get("log"):
        body += "\n" + agent.search_log_markdown(result["log"], result.get("backend"),
                                                 result.get("model"))
    return head + body


def save(mode, params, result, out=None, with_log=True):
    """Write output files (if requested), record history, return written paths."""
    written = []
    text = params.get("text", "")
    if out:
        out = os.path.expanduser(out)
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        if mode in AGENT_MODES:
            with open(out, "w", encoding="utf-8") as f:
                f.write(report_text(mode, text, result, with_log))
            written.append(out)
            if result.get("log"):
                side = os.path.splitext(out)[0] + ".log.json"
                with open(side, "w", encoding="utf-8") as f:
                    json.dump({"input": text, "mode": mode, "backend": result.get("backend"),
                               "model": result.get("model"), "date": time.strftime("%Y-%m-%d"),
                               "log": result["log"]}, f, indent=1, ensure_ascii=False)
                written.append(side)
        elif "papers" in result:
            export.write(result["papers"], out)
            written.append(out)
        elif "oa" in result:
            with open(out, "w", encoding="utf-8") as f:
                json.dump(result["oa"], f, indent=2)
            written.append(out)
    if result.get("needs_choice"):
        return None, written
    run_id = history.record(mode, params, papers=result.get("papers"),
                            report=result.get("report"), log=result.get("log"),
                            stats=result.get("stats"), out_file=written[0] if written else "")
    return run_id, written


def oa_text(info):
    if info["pdf"] or info["page"]:
        return (f"**{info['title']}**\nopen access: yes ({info.get('version') or '?'})\n"
                f"pdf : {info['pdf'] or 'n/a'}\npage: {info['page'] or 'n/a'}")
    return f"**{info['title']}**\nno legal open-access copy found (is_oa={info['is_oa']})"


def candidates_text(result, sort="relevance"):
    plist = sort_papers(result["candidates"], sort)
    head = (f"'{result['query']}' is not a paper id. Closest papers (sorted by {sort}); "
            f"rerun with the id, or add --pick N:\n")
    return head + "\n".join(
        f"{i}. {p['title']} ({p['year']}) — {', '.join(p['authors'][:2])}"
        f"{' et al.' if len(p['authors']) > 2 else ''} · {p['venue'] or '?'} · "
        f"{p['citations']} citations · id: {papers.best_id(p)}"
        for i, p in enumerate(plist, 1))


def sort_papers(plist, sort="relevance"):
    if sort == "citations":
        return sorted(plist, key=lambda p: p["citations"], reverse=True)
    if sort == "year":
        return sorted(plist, key=lambda p: p["year"] or 0, reverse=True)
    return list(plist)


def papers_text(plist, snippet=0):
    return "\n\n".join(papers.format_paper(p, i, snippet=snippet)
                       for i, p in enumerate(plist, 1))
