"""Tiny HTTP layer: per-host rate limits, retries with Retry-After, debug tracing."""
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from . import __version__
from .config import DATA_DIR

USER_AGENT = f"litsurvey/{__version__} (https://github.com/udaykdk/litsurvey)"

# minimum seconds between requests to a host, per the providers' published limits
HOST_INTERVAL = {
    "api.semanticscholar.org": 1.1,   # 1 request/second with a key; shared pool without
    "export.arxiv.org": 3.0,          # arXiv asks for 3 s between requests
    "api.openalex.org": 0.15,
    "api.unpaywall.org": 0.2,
    "api.crossref.org": 0.2,
    "eprint.iacr.org": 2.0,           # no API; be gentle with their search page
}
_last_call = {}
DEBUG = False

FRIENDLY = {
    "api.semanticscholar.org": "Semantic Scholar",
    "api.openalex.org": "OpenAlex",
    "export.arxiv.org": "arXiv",
    "arxiv.org": "arXiv",
    "ar5iv.labs.arxiv.org": "arXiv (ar5iv)",
    "api.crossref.org": "Crossref (TechRxiv / Research Square)",
    "eprint.iacr.org": "IACR ePrint",
    "api.unpaywall.org": "Unpaywall",
    "api.openai.com": "OpenAI",
    "openrouter.ai": "OpenRouter",
    "api.anthropic.com": "Anthropic",
}
_local = threading.local()


def friendly(host):
    if host.startswith(("localhost", "127.0.0.1")):
        return "the local model"
    return FRIENDLY.get(host, host)


def set_reporter(callback):
    """Register a per-thread callback(kind, text). kind is "current" (the host
    being waited on, "" when done) or "note" (a retry or delay worth showing)."""
    _local.cb = callback


def _report(kind, text):
    cb = getattr(_local, "cb", None)
    if cb:
        try:
            cb(kind, text)
        except Exception:  # noqa: BLE001 - reporting must never break a request
            pass


def _throttle(host):
    """Space requests per host, both within this process and across processes
    (CLI and web page running together) via a timestamp file's mtime."""
    interval = HOST_INTERVAL.get(host, 0.0)
    if not interval:
        return
    stamp = os.path.join(DATA_DIR, ".ratelimit-" + host)
    try:
        last_file = os.stat(stamp).st_mtime
    except OSError:
        last_file = 0.0
    wait = max(_last_call.get(host, 0.0) + interval - time.monotonic(),
               last_file + interval - time.time())
    if wait > 0:
        time.sleep(min(wait, interval))
    _last_call[host] = time.monotonic()
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(stamp, "a"):
            pass
        os.utime(stamp, None)
    except OSError:
        pass


def _retry_after(err, attempt):
    try:
        ra = err.headers.get("Retry-After") if err.headers else None
        if ra:
            return min(float(ra), 60.0)
    except (TypeError, ValueError):
        pass
    return float(min(2 ** (attempt + 1), 20))     # 2, 4, 8, 16 s


def get(url, headers=None, timeout=30, retries=5):
    """GET url and return the raw bytes. Retries 429/5xx and network errors."""
    host = urllib.parse.urlparse(url).netloc
    hdrs = {"User-Agent": USER_AGENT}
    hdrs.update(headers or {})
    last = None
    name = friendly(host)
    try:
        for attempt in range(retries):
            _report("current", name)      # before the throttle pause, so the wait is attributed
            _throttle(host)
            if DEBUG:
                print(f"[http] GET {url}", file=sys.stderr)
            try:
                req = urllib.request.Request(url, headers=hdrs)
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    return r.read()
            except urllib.error.HTTPError as e:
                last = e
                if e.code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                    wait = _retry_after(e, attempt)
                    why = "is rate-limiting us" if e.code == 429 else f"answered HTTP {e.code}"
                    print(f"[warn] HTTP {e.code} from {host}, retrying in {wait:.0f}s",
                          file=sys.stderr)
                    _report("note", f"{name} {why}; retrying in {wait:.0f} s")
                    time.sleep(wait)
                    continue
                raise
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                last = e
                if attempt < retries - 1:
                    _report("note", f"{name} did not answer ({type(e).__name__}); retrying")
                    time.sleep(2 ** (attempt + 1))
                    continue
                raise
        raise last  # pragma: no cover
    finally:
        _report("current", "")


def get_json(url, headers=None, timeout=30):
    return json.loads(get(url, headers=headers, timeout=timeout).decode("utf-8"))


def post_json(url, payload, headers=None, timeout=900):
    """POST a JSON body and return the decoded JSON reply (used for LLM backends)."""
    hdrs = {"Content-Type": "application/json", "User-Agent": USER_AGENT}
    hdrs.update(headers or {})
    data = json.dumps(payload).encode("utf-8")
    if DEBUG:
        print(f"[http] POST {url} ({len(data)} bytes)", file=sys.stderr)
    req = urllib.request.Request(url, data=data, headers=hdrs)
    _report("current", friendly(urllib.parse.urlparse(url).netloc) + " (model reply)")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:500]
        raise RuntimeError(f"HTTP {e.code} from {url}: {body}") from None
    finally:
        _report("current", "")
