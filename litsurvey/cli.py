"""Command-line interface."""
import argparse
import getpass
import json
import os
import sys

from . import __version__, backends, config, export, history, http, ops, papers


def _add_list_opts(p):
    p.add_argument("-n", type=int, default=15, help="max results (default 15)")
    p.add_argument("--sort", choices=["relevance", "citations", "year"], default="relevance",
                   help="order of the printed list (default relevance; also orders a candidate list)")
    p.add_argument("--abstracts", action="store_true", help="show abstract snippets")
    p.add_argument("--json", action="store_true", help="print JSON to stdout")
    p.add_argument("--out", metavar="FILE",
                   help="also write results; extension picks the format: .bib .ris .csv .json .md")


def _add_agent_opts(p):
    p.add_argument("--backend", choices=backends.BACKENDS,
                   help="LLM backend: cli (your Claude Code / Codex / Antigravity / Gemini subscription CLI), "
                        "ollama (local), openai, anthropic. Default: config, else auto-detect "
                        "(local first)")
    p.add_argument("--model", help="model name; for --backend cli the tool name: claude, codex, agy, gemini or custom")
    p.add_argument("--base-url", metavar="URL",
                   help="for --backend openai: the API root, e.g. https://openrouter.ai/api or http://localhost:1234")
    p.add_argument("--rounds", type=int, default=8, help="max tool-calling rounds (default 8)")
    p.add_argument("--out", metavar="FILE", help="save the report as markdown (+ FILE.log.json)")
    p.add_argument("--no-log", action="store_true", help="omit the search-log appendix")


def _print_papers(args, plist):
    plist = ops.sort_papers(plist, getattr(args, "sort", "relevance"))
    if args.json:
        print(export.to_json(plist), end="")
    elif not plist:
        print("no results")
    else:
        print(ops.papers_text(plist, snippet=350 if args.abstracts else 0))


def _choose(result, args):
    """Title given instead of an id: let a person pick; scripts get the list and a hint."""
    sort = getattr(args, "sort", "relevance")
    print(ops.candidates_text(result, sort), file=sys.stderr)
    if not sys.stdin.isatty():
        sys.exit(2)
    plist = ops.sort_papers(result["candidates"], sort)
    while True:
        try:
            ans = input(f"Which paper? [1-{len(plist)}, q to quit] ").strip().lower()
        except EOFError:
            sys.exit(2)
        if ans in ("q", ""):
            sys.exit(2)
        if ans.isdigit() and 1 <= int(ans) <= len(plist):
            chosen = plist[int(ans) - 1]
            print(f"[note] using: {chosen['title']} ({chosen['year']})", file=sys.stderr)
            return papers.best_id(chosen)


def cmd_list_mode(mode):
    def run(args):
        params = {"text": args.text, "n": args.n}
        if mode == "search":
            params["year_from"] = args.year_from
            params["sources"] = args.sources.split(",") if args.sources else None
        else:
            params["pick"] = getattr(args, "pick", None)
            params["sort"] = getattr(args, "sort", "relevance")
        result = ops.run_mode(mode, params)
        if result.get("needs_choice"):
            params["text"] = _choose(result, args)
            params.pop("pick", None)
            result = ops.run_mode(mode, params)
        _print_papers(args, result["papers"])
        if mode == "search" and args.scholar:
            print(f"\nGoogle Scholar (manual check): {papers.scholar_url(args.text)}")
        run_id, written = ops.save(mode, params, result, out=args.out)
        for w in written:
            print(f"[saved] {w}", file=sys.stderr)
        print(f"[run] {run_id}", file=sys.stderr)
    return run


def cmd_oa(args):
    params = {"text": args.doi, "pick": args.pick}
    result = ops.run_mode("oa", params)
    if result.get("needs_choice"):
        params["text"] = _choose(result, args)
        params.pop("pick", None)
        result = ops.run_mode("oa", params)
    print(json.dumps(result["oa"], indent=2) if args.json else ops.oa_text(result["oa"]))
    ops.save("oa", params, result, out=args.out)


def cmd_agent_mode(mode):
    def run(args):
        params = {"text": args.text, "backend": args.backend, "model": args.model,
                  "rounds": args.rounds, "base_url": args.base_url}
        result = ops.run_mode(mode, params)
        print(result["report"])
        run_id, written = ops.save(mode, params, result, out=args.out, with_log=not args.no_log)
        for w in written:
            print(f"[saved] {w}", file=sys.stderr)
        print(f"[run] {run_id}", file=sys.stderr)
    return run


def cmd_history(args):
    if args.action == "list":
        rows = history.list_runs(limit=args.n)
        if not rows:
            print("no runs yet")
            return
        for r in rows:
            inp = (r["inputs"].get("text") or "")[:60]
            extra = f"{r['n_results']} results" if r.get("n_results") is not None else "report"
            print(f"{r['id']:32s} {r['mode']:9s} {extra:12s} {inp}")
    elif args.action == "show":
        run = history.load(args.run_id)
        if run.get("report"):
            print(run["report"])
        elif run.get("papers"):
            print(ops.papers_text(run["papers"]))
        else:
            print(json.dumps(run, indent=2))
    elif args.action == "export":
        run = history.load(args.run_id)
        if not run.get("papers"):
            sys.exit("that run has no paper list to export")
        export.write(run["papers"], args.out)
        print(f"[saved] {args.out}")
    elif args.action == "delete":
        history.delete(args.run_id)
        print(f"deleted {args.run_id}")


def _init_cli_model(tool, cur, vals):
    """Ask the installed CLI what models and effort levels it supports, and settle
    on a deliberate default. Left alone, these tools run at their top model and
    highest reasoning effort, which for a literature search burns a lot of the
    subscription's quota and time for no better answer. The choice is one model
    below the best and an effort level in the middle of the range."""
    print(f"\nasking {tool} what it supports...")
    found = backends.probe(tool)
    if found["models"]:
        print(f"  models it names : {', '.join(found['models'])} (best first)")
    else:
        print(f"  models it names : none listed in `{tool} --help`; its own default will be used")
    if found["efforts"]:
        print(f"  effort levels   : {', '.join(found['efforts'])}")
    else:
        print(f"  effort levels   : none ({tool} takes no effort setting)")
    print(f"  litsurvey picks : model={found['model'] or '(tool default)'} "
          f"effort={found['effort'] or '(tool default)'}")
    print("  Enter accepts this. Type a value to override, or '-' to leave the tool at its own default.")
    if found["models"] or cur["cli_model"]:
        m = input(f"  model [{cur['cli_model'] or found['model'] or 'tool default'}]: ").strip()
        vals["cli_model"] = m or cur["cli_model"] or found["model"] or "-"
    if found["efforts"] or cur["cli_effort"]:
        e = input(f"  effort [{cur['cli_effort'] or found['effort'] or 'tool default'}]: ").strip()
        vals["cli_effort"] = e or cur["cli_effort"] or found["effort"] or "-"


def cmd_init(args):
    print("litsurvey setup. Press Enter to keep a value.\n")
    cur = config.load()
    vals = {}
    key = getpass.getpass(f"Semantic Scholar API key [{'set' if cur['s2_api_key'] else 'none'}]: ").strip()
    if key:
        vals["s2_api_key"] = key
    mail = input(f"Your email for OpenAlex/Unpaywall polite pools [{cur['openalex_mailto'] or 'none'}]: ").strip()
    if mail:
        vals["openalex_mailto"] = mail
    print("\nLLM backend for novelty/research (leave blank to auto-detect at run time):")
    print("  cli       - your subscription's command-line agent: Claude Code, Codex CLI, Antigravity CLI or Gemini CLI")
    print("  ollama    - local model, nothing leaves the machine")
    print("  openai    - OpenAI-compatible API key (OpenAI, LM Studio, vLLM, OpenRouter)")
    print("  anthropic - Anthropic API key")
    be = input(f"backend [{cur['backend'] or 'auto'}]: ").strip().lower()
    if be:
        vals["backend"] = be
    if (be or cur["backend"]) == "cli":
        found = backends.cli_tools_available()
        print(f"subscription CLIs found on PATH: {', '.join(found) or 'none'}")
        tool = input(f"CLI tool (claude / codex / agy / gemini / custom) [{cur['cli_tool'] or (found[0] if found else 'claude')}]: ").strip().lower()
        if tool:
            vals["cli_tool"] = tool
        tool = tool or cur["cli_tool"] or (found[0] if found else "claude")
        if tool == "custom":
            cmd = input("custom command (use {prompt} for the prompt, or it is passed on stdin): ").strip()
            if cmd:
                vals["cli_command"] = cmd
        else:
            _init_cli_model(tool, cur, vals)
    else:
        model = input(f"default model name [{cur['model'] or 'auto'}]: ").strip()
        if model:
            vals["model"] = model
    if (be or cur["backend"]) == "openai":
        print("  examples: https://api.openai.com (OpenAI), https://openrouter.ai/api (OpenRouter), "
              "http://localhost:1234 (LM Studio)")
        base = input(f"OpenAI-compatible base URL [{cur['openai_base_url']}]: ").strip()
        if base:
            vals["openai_base_url"] = base
        k = getpass.getpass("OpenAI API key (blank for local servers): ").strip()
        if k:
            vals["openai_api_key"] = k
    if (be or cur["backend"]) == "anthropic":
        k = getpass.getpass("Anthropic API key: ").strip()
        if k:
            vals["anthropic_api_key"] = k
    path = config.save(vals)
    print(f"\nwritten to {path}. Run `litsurvey doctor` to check.")


def cmd_doctor(args):
    from .sources import arxiv, crossref, iacr, openalex, pubmed, semanticscholar
    cfg = config.load()
    ok, warnings = True, []
    print(f"litsurvey {__version__}, python {sys.version.split()[0]}")
    if os.path.exists(config.CONFIG_PATH):
        print(f"config       : {config.CONFIG_PATH}")
    elif os.path.exists(config.LEGACY_PATH):
        print(f"config       : {config.LEGACY_PATH} (older litsearch file, still read; `litsurvey init` writes the new one)")
    else:
        print("config       : none yet (optional; `litsurvey init` stores the key and email)")
    print(f"S2 API key   : {'set (' + cfg['s2_api_key'][:4] + '…)' if cfg['s2_api_key'] else 'NOT SET (works, shared pool, rate-limited)'}")
    print(f"email        : {cfg['openalex_mailto'] or 'not set (polite pools unavailable)'}")
    for name, fn, q in (("openalex", openalex.search, "attention transformer"),
                        ("semanticscholar", semanticscholar.search, "attention transformer"),
                        ("arxiv", arxiv.search, "attention transformer"),
                        ("pubmed", pubmed.search, "crispr off-target"),
                        ("techrxiv", crossref.portal("techrxiv"), "neural network"),
                        ("researchsquare", crossref.portal("researchsquare"), "neural network"),
                        ("iacr", iacr.search, "lattice signature")):
        try:
            r = fn(q, limit=2)
            print(f"{name:14s}: OK ({len(r)} results)")
            if name == "iacr" and not r:
                print("               (0 results: IACR's search page may have changed; other sources unaffected)")
        except Exception as e:  # noqa: BLE001
            if name == "semanticscholar" and not cfg["s2_api_key"]:
                warnings.append("semanticscholar (no API key; the shared pool is refusing, "
                                "get a free key: docs/api-keys.md)")
            elif name in ("openalex", "semanticscholar", "arxiv"):
                ok = False
            else:
                warnings.append(name)
            print(f"{name:14s}: FAIL - {e}")
    try:
        names = backends.ollama_models()
        print(f"ollama       : OK at {cfg['ollama_host']} ({len(names)} models: {', '.join(names[:5])})")
    except Exception as e:  # noqa: BLE001
        print(f"ollama       : not running ({type(e).__name__}); novelty/research need a backend")
    found = backends.cli_tools_available()
    print(f"subscr. CLIs : {', '.join(found) if found else 'none found'} (claude / codex / agy / gemini on PATH)")
    print(f"openai       : {'key set' if cfg['openai_api_key'] else 'no key'}, base {cfg['openai_base_url']}")
    print(f"anthropic    : {'key set' if cfg['anthropic_api_key'] else 'no key'}")
    agent_line = None
    try:
        be, model = backends.resolve()
        local = backends.is_local(be)
        where = "local" if local else ("subscription CLI, text goes to the vendor" if be == "cli" else "CLOUD")
        print(f"agent default: backend={be} model={model} ({where})")
        agent_line = f"novelty/research will use {be} {'tool' if be == 'cli' else 'model'} {model} ({where})"
        if be == "cli":
            cm, ce = backends.cli_defaults(model)
            print(f"  {model} run as: model={cm or '(tool default)'} effort={ce or '(tool default)'}"
                  f"  [set cli_model / cli_effort in the config, or '-' to leave the tool alone]")
        if not cfg["model"] and be == "ollama":
            agent_line += "; set a different default with `litsurvey init`"
    except Exception as e:  # noqa: BLE001
        print(f"agent default: none ({e})")
    print()
    print("(doctor does not test Unpaywall, and does not make an LLM call; it only detects backends.)")
    tail = f" Minor sources failed: {', '.join(warnings)}; searches still work without them." if warnings else ""
    if not ok:
        print("RESULT: PROBLEMS. A core source failed (see FAIL lines above); "
              "search results will be incomplete. Check your network, then `litsurvey doctor --debug`.")
    elif agent_line:
        print(("RESULT: OK WITH WARNINGS." if warnings else "RESULT: ALL OK.")
              + " Search, citation and open-access commands work; " + agent_line + "." + tail)
    else:
        print(("RESULT: OK WITH WARNINGS" if warnings else "RESULT: OK") + " for search. novelty/research are "
              "unavailable until an LLM backend is set up (see docs/llm-integration.md)." + tail)
    print("You do not need to run doctor regularly: use it after install, or when something fails.")
    sys.exit(0 if ok else 1)


def cmd_web(args):
    from . import web
    web.serve(port=args.port, open_browser=not args.no_browser)


def build_parser():
    ap = argparse.ArgumentParser(
        prog="litsurvey",
        description="Multi-source scientific literature search, with optional LLM-driven "
                    "novelty assessment and deep research.")
    ap.add_argument("--version", action="version", version=f"litsurvey {__version__}")
    ap.add_argument("--debug", action="store_true", help="print every HTTP request to stderr")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("search", help="keyword search across OpenAlex + Semantic Scholar + arXiv")
    p.add_argument("text", metavar="QUERY")
    p.add_argument("--year-from", type=int, metavar="YEAR")
    p.add_argument("--sources", help="comma list from openalex,s2,arxiv,pubmed,techrxiv,researchsquare,"
                                     "iacr,europepmc,crossref (default: all except europepmc and crossref, "
                                     "which repeat sources already in the list)")
    p.add_argument("--scholar", action="store_true", help="also print a Google Scholar URL for the query")
    _add_list_opts(p)
    p.set_defaults(fn=cmd_list_mode("search"))

    for mode, helptext in (("paper", "one paper's full record (abstract, DOI, ids); --out x.bib for its BibTeX"),
                           ("cites", "papers citing the given paper (forward snowball)"),
                           ("refs", "papers the given paper cites (backward snowball)"),
                           ("related", "similar papers via recommendation engine")):
        p = sub.add_parser(mode, help=helptext)
        p.add_argument("text", metavar="ID_OR_TITLE",
                       help="S2 hash, DOI:10.…, ARXIV:2404.19756, or a paper title (you will be asked to pick)")
        p.add_argument("--pick", type=int, metavar="N", help="with a title: take candidate N without asking")
        _add_list_opts(p)
        p.set_defaults(fn=cmd_list_mode(mode))

    p = sub.add_parser("oa", help="find a legal open-access copy of a DOI (Unpaywall)")
    p.add_argument("doi", metavar="DOI_OR_TITLE")
    p.add_argument("--pick", type=int, metavar="N")
    p.add_argument("--sort", choices=["relevance", "citations", "year"], default="relevance")
    p.add_argument("--json", action="store_true")
    p.add_argument("--out", metavar="FILE")
    p.set_defaults(fn=cmd_oa)

    p = sub.add_parser("novelty", help="LLM agent: prior-art verdict for a claim")
    p.add_argument("text", metavar="CLAIM", help="the claim as a generic topic phrase, not manuscript text")
    _add_agent_opts(p)
    p.set_defaults(fn=cmd_agent_mode("novelty"))

    p = sub.add_parser("research", help="LLM agent: cited state-of-the-art survey for a question")
    p.add_argument("text", metavar="QUESTION")
    _add_agent_opts(p)
    p.set_defaults(rounds=12, fn=cmd_agent_mode("research"))

    p = sub.add_parser("history", help="list, show, export or delete past runs")
    p.add_argument("action", nargs="?", default="list", choices=["list", "show", "export", "delete"])
    p.add_argument("run_id", nargs="?")
    p.add_argument("-n", type=int, default=30)
    p.add_argument("--out", metavar="FILE", help="for export: .bib .ris .csv .json .md")
    p.set_defaults(fn=cmd_history)

    p = sub.add_parser("init", help="interactive setup of ~/.litsurvey/config.json")
    p.set_defaults(fn=cmd_init)
    p = sub.add_parser("doctor", help="check API and LLM backend connectivity")
    p.set_defaults(fn=cmd_doctor)
    p = sub.add_parser("web", help="start the local browser interface")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--no-browser", action="store_true")
    p.set_defaults(fn=cmd_web)
    return ap


def main(argv=None):
    ap = build_parser()
    args = ap.parse_args(argv)
    if args.debug:
        http.DEBUG = True
    if getattr(args, "action", None) in ("show", "export", "delete") and not args.run_id:
        ap.error("run_id is required")
    if getattr(args, "action", None) == "export" and not args.out:
        ap.error("--out FILE is required for export")
    try:
        args.fn(args)
    except KeyboardInterrupt:
        sys.exit(130)
    except (RuntimeError, ValueError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
