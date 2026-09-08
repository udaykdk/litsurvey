"""One entry point for every mode, shared by the CLI and the web page."""
import json
import os
import time

from . import agent, export, history, papers
from .sources import run_search, semanticscholar, unpaywall

LIST_MODES = ("search", "paper", "cites", "refs", "related")
AGENT_MODES = ("novelty", "research")
MODES = LIST_MODES + ("oa",) + AGENT_MODES


def run_mode(mode, params, progress=None):
    """params keys: text (query / id / doi / claim), n, year_from, sources,
    backend, model, rounds. Returns a result dict."""
    text = (params.get("text") or "").strip()
    if not text:
        raise ValueError("input text is empty")
    text, note = papers.normalize_input(text)
    if note:
        params["text"] = text
        (progress or (lambda s: print(s, file=__import__("sys").stderr)))("[note] " + note)
    n = int(params.get("n") or 15)
    if mode == "search":
        plist, stats = run_search(text, limit=n, year_from=params.get("year_from"),
                                  sources=params.get("sources"))
        return {"papers": plist[:n], "stats": stats}
    if mode == "paper":
        return {"papers": [semanticscholar.paper(text)]}
    if mode == "cites":
        return {"papers": semanticscholar.linked(text, "citations", limit=n)}
    if mode == "refs":
        return {"papers": semanticscholar.linked(text, "references", limit=n)}
    if mode == "related":
        return {"papers": semanticscholar.related(text, limit=n)}
    if mode == "oa":
        return {"oa": unpaywall.lookup(text)}
    if mode in AGENT_MODES:
        return agent.run(mode, text, backend=params.get("backend"),
                         model=params.get("model"), rounds=int(params.get("rounds") or 8),
                         progress=progress)
    raise ValueError(f"unknown mode {mode!r}")


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
    run_id = history.record(mode, params, papers=result.get("papers"),
                            report=result.get("report"), log=result.get("log"),
                            stats=result.get("stats"), out_file=written[0] if written else "")
    return run_id, written


def oa_text(info):
    if info["pdf"] or info["page"]:
        return (f"**{info['title']}**\nopen access: yes ({info.get('version') or '?'})\n"
                f"pdf : {info['pdf'] or 'n/a'}\npage: {info['page'] or 'n/a'}")
    return f"**{info['title']}**\nno legal open-access copy found (is_oa={info['is_oa']})"


def papers_text(plist, snippet=0):
    return "\n\n".join(papers.format_paper(p, i, snippet=snippet)
                       for i, p in enumerate(plist, 1))
