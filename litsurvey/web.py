"""Local browser interface: stdlib HTTP server on 127.0.0.1, one HTML page, JSON API."""
import json
import os
import threading
import time
import traceback
import urllib.parse
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import __version__, backends, config, export, history, http, ops, papers

REPO_URL = "https://github.com/udaykdk/litsurvey"

JOBS = {}
JOBS_LOCK = threading.Lock()


def _page():
    path = os.path.join(os.path.dirname(__file__), "web", "index.html")
    with open(path, encoding="utf-8") as f:
        return f.read().replace("{{VERSION}}", __version__)


def _start_job(mode, params, out):
    job_id = uuid.uuid4().hex[:10]
    job = {"id": job_id, "mode": mode, "status": "running", "progress": [],
           "started": time.time(), "result": None, "run_id": None, "error": None,
           "written": [], "current": "", "note": ""}
    with JOBS_LOCK:
        JOBS[job_id] = job

    def progress(line):
        job["progress"].append(line)

    def reporter(kind, text):
        if kind == "current":       # a new attempt or a finished request: the retry note is over
            job["current"] = text
            job["note"] = ""
        else:
            job["note"] = text

    def work():
        http.set_reporter(reporter)
        try:
            result = ops.run_mode(mode, params, progress=progress)
            run_id, written = ops.save(mode, params, result, out=out)
            job["result"] = {k: v for k, v in result.items() if k != "log"}
            if result.get("log"):
                job["result"]["log"] = result["log"]
            job["run_id"], job["written"] = run_id, written
            job["status"] = "done"
        except Exception as e:  # noqa: BLE001
            job["error"] = f"{type(e).__name__}: {e}"
            job["progress"].append(traceback.format_exc().splitlines()[-1])
            job["status"] = "error"

    threading.Thread(target=work, daemon=True).start()
    return job_id


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # quiet
        pass

    def _send(self, code, body, ctype="application/json", extra=None):
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype + ("; charset=utf-8" if ctype.startswith("text") or ctype == "application/json" else ""))
        self.send_header("Content-Length", str(len(data)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False))

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        parts = [p for p in u.path.split("/") if p]
        q = urllib.parse.parse_qs(u.query)
        try:
            if not parts:
                return self._send(200, _page(), "text/html")
            if parts[:2] == ["api", "config"]:
                cfg = config.load()
                info = {"version": __version__, "backend": cfg["backend"] or "auto",
                        "repo_url": REPO_URL,
                        "issues_url": REPO_URL + "/issues/new?template=bug_report.md",
                        "model": cfg["model"], "s2_key": bool(cfg["s2_api_key"]),
                        "ollama_models": [], "ollama": False}
                try:
                    info["ollama_models"] = backends.ollama_models()
                    info["ollama"] = True
                except Exception:  # noqa: BLE001
                    pass
                info["openai_base_url"] = cfg["openai_base_url"]
                info["cli_tools"] = backends.cli_tools_available() + (["custom"] if cfg["cli_command"] else [])
                info["cli_tool"] = cfg["cli_tool"]
                info["openai_key"] = bool(cfg["openai_api_key"])
                info["anthropic_key"] = bool(cfg["anthropic_api_key"])
                return self._json(info)
            if parts[:2] == ["api", "history"]:
                return self._json(history.list_runs(limit=200))
            if parts[:2] == ["api", "run"] and len(parts) >= 3:
                run = history.load(parts[2])
                if len(parts) == 4 and parts[3] == "export":
                    fmt = (q.get("fmt") or ["bib"])[0]
                    if fmt not in export.FORMATS:
                        return self._json({"error": f"unknown format {fmt!r}"}, 400)
                    if run.get("papers"):
                        text = export.render(run["papers"], fmt)
                    elif fmt == "md" and run.get("report"):
                        text = ops.report_text(run["mode"], run["inputs"].get("text", ""),
                                               {"report": run["report"], "log": run.get("log")})
                    else:
                        return self._json({"error": "nothing to export in that format"}, 400)
                    fname = f"{run['id']}.{ 'bib' if fmt == 'bibtex' else fmt}"
                    return self._send(200, text, "text/plain",
                                      {"Content-Disposition": f'attachment; filename="{fname}"'})
                return self._json(run)
            if parts[:2] == ["api", "jobs"] and len(parts) == 3:
                job = JOBS.get(parts[2])
                if not job:
                    return self._json({"error": "no such job"}, 404)
                return self._json({k: v for k, v in job.items() if k != "started"})
            return self._json({"error": "not found"}, 404)
        except FileNotFoundError:
            return self._json({"error": "not found"}, 404)
        except Exception as e:  # noqa: BLE001
            return self._json({"error": f"{type(e).__name__}: {e}"}, 500)

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        parts = [p for p in u.path.split("/") if p]
        length = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            return self._json({"error": "bad JSON"}, 400)
        if parts[:2] == ["api", "jobs"]:
            mode = body.get("mode")
            if mode not in ops.MODES:
                return self._json({"error": f"unknown mode {mode!r}"}, 400)
            params = {k: body.get(k) for k in ("text", "n", "year_from", "backend", "model", "rounds", "pick", "base_url")}
            params = {k: v for k, v in params.items() if v not in (None, "", [])}
            if "n" in params:
                params["n"] = int(params["n"])
            if "year_from" in params:
                params["year_from"] = int(params["year_from"])
            out = (body.get("out") or "").strip() or None
            try:
                papers.normalize_input(params.get("text", ""))
            except ValueError as e:
                return self._json({"error": str(e)}, 400)
            return self._json({"job_id": _start_job(mode, params, out)})
        return self._json({"error": "not found"}, 404)

    def do_DELETE(self):
        parts = [p for p in self.path.split("/") if p]
        if parts[:2] == ["api", "run"] and len(parts) == 3:
            history.delete(parts[2])
            return self._json({"ok": True})
        return self._json({"error": "not found"}, 404)


def serve(port=8765, open_browser=True):
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}/"
    print(f"litsurvey web interface at {url}  (Ctrl-C to stop)")
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        server.server_close()
