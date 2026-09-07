"""Command-line interface."""
import argparse
import getpass
import json
import os
import sys

from . import __version__, backends, config, export, history, http, ops, papers


def _add_list_opts(p):
    p.add_argument("-n", type=int, default=15, help="max results (default 15)")
    p.add_argument("--abstracts", action="store_true", help="show abstract snippets")
    p.add_argument("--json", action="store_true", help="print JSON to stdout")
    p.add_argument("--out", metavar="FILE",
                   help="also write results; extension picks the format: .bib .ris .csv .json .md")


def _add_agent_opts(p):
    p.add_argument("--backend", choices=backends.BACKENDS,
                   help="LLM backend (default: config, else auto-detect; ollama is the local one)")
    p.add_argument("--model", help="model name for the backend")
    p.add_argument("--rounds", type=int, default=8, help="max tool-calling rounds (default 8)")
    p.add_argument("--out", metavar="FILE", help="save the report as markdown (+ FILE.log.json)")
    p.add_argument("--no-log", action="store_true", help="omit the search-log appendix")


def _print_papers(args, plist):
    if args.json:
        print(export.to_json(plist), end="")
    else:
        print(ops.papers_text(plist, snippet=350 if args.abstracts else 0))


def cmd_list_mode(mode):
    def run(args):
        params = {"text": args.text, "n": args.n}
        if mode == "search":
            params["year_from"] = args.year_from
            params["sources"] = args.sources.split(",") if args.sources else None
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
    result = ops.run_mode("oa", {"text": args.doi})
    print(json.dumps(result["oa"], indent=2) if args.json else ops.oa_text(result["oa"]))
    ops.save("oa", {"text": args.doi}, result, out=args.out)


def cmd_agent_mode(mode):
    def run(args):
        params = {"text": args.text, "backend": args.backend, "model": args.model,
                  "rounds": args.rounds}
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
    print("  ollama    - local, nothing leaves the machine")
    print("  openai    - OpenAI-compatible API (OpenAI, LM Studio, vLLM, OpenRouter)")
    print("  anthropic - Anthropic API")
    be = input(f"backend [{cur['backend'] or 'auto'}]: ").strip().lower()
    if be:
        vals["backend"] = be
    model = input(f"default model name [{cur['model'] or 'auto'}]: ").strip()
    if model:
        vals["model"] = model
    if (be or cur["backend"]) == "openai":
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
    from .sources import arxiv, openalex, semanticscholar
    cfg = config.load()
    ok = True
    print(f"litsurvey {__version__}, python {sys.version.split()[0]}")
    print(f"config       : {config.CONFIG_PATH} ({'found' if os.path.exists(config.CONFIG_PATH) else 'not found'})")
    print(f"S2 API key   : {'set (' + cfg['s2_api_key'][:4] + '…)' if cfg['s2_api_key'] else 'NOT SET (works, shared pool, rate-limited)'}")
    print(f"email        : {cfg['openalex_mailto'] or 'not set (polite pools unavailable)'}")
    for name, fn in (("openalex", openalex.search), ("semanticscholar", semanticscholar.search),
                     ("arxiv", arxiv.search)):
        try:
            r = fn("attention transformer", limit=2)
            print(f"{name:13s}: OK ({len(r)} results)")
        except Exception as e:  # noqa: BLE001
            ok = False
            print(f"{name:13s}: FAIL - {e}")
    try:
        names = backends.ollama_models()
        print(f"ollama       : OK at {cfg['ollama_host']} ({len(names)} models: {', '.join(names[:5])})")
    except Exception as e:  # noqa: BLE001
        print(f"ollama       : not running ({type(e).__name__}); novelty/research need a backend")
    print(f"openai       : {'key set' if cfg['openai_api_key'] else 'no key'}, base {cfg['openai_base_url']}")
    print(f"anthropic    : {'key set' if cfg['anthropic_api_key'] else 'no key'}")
    try:
        be, model = backends.resolve()
        print(f"agent default: backend={be} model={model}"
              f" ({'local' if be in backends.LOCAL_BACKENDS else 'CLOUD'})")
    except Exception as e:  # noqa: BLE001
        print(f"agent default: none ({e})")
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
    p.add_argument("--sources", help="comma list, e.g. openalex,s2 (default all)")
    p.add_argument("--scholar", action="store_true", help="also print a Google Scholar URL for the query")
    _add_list_opts(p)
    p.set_defaults(fn=cmd_list_mode("search"))

    for mode, helptext in (("paper", "details of one paper"),
                           ("cites", "papers citing the given paper (forward snowball)"),
                           ("refs", "papers the given paper cites (backward snowball)"),
                           ("related", "similar papers via recommendation engine")):
        p = sub.add_parser(mode, help=helptext)
        p.add_argument("text", metavar="ID", help="S2 hash, DOI:10.…, or ARXIV:2404.19756")
        _add_list_opts(p)
        p.set_defaults(fn=cmd_list_mode(mode))

    p = sub.add_parser("oa", help="find a legal open-access copy of a DOI (Unpaywall)")
    p.add_argument("doi")
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
