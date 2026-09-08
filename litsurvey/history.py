"""Run history: ~/.litsurvey/history.jsonl (index) and ~/.litsurvey/runs/<id>.json."""
import json
import os
import time

from .config import DATA_DIR

INDEX = os.path.join(DATA_DIR, "history.jsonl")
RUNS = os.path.join(DATA_DIR, "runs")


def new_id(mode):
    return time.strftime("%Y%m%d-%H%M%S") + "-" + mode


def record(mode, inputs, papers=None, report=None, log=None, out_file=None,
           stats=None, run_id=None):
    """Save one run. Returns the run id."""
    os.makedirs(RUNS, exist_ok=True)
    run_id = run_id or new_id(mode)
    entry = {"id": run_id, "time": time.strftime("%Y-%m-%d %H:%M:%S"), "mode": mode,
             "inputs": inputs, "n_results": len(papers) if papers is not None else None,
             "out_file": out_file or "", "has_report": bool(report)}
    with open(os.path.join(RUNS, run_id + ".json"), "w", encoding="utf-8") as f:
        json.dump({**entry, "papers": papers, "report": report, "log": log,
                   "stats": stats}, f, indent=1, ensure_ascii=False)
    with open(INDEX, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return run_id


def list_runs(limit=50):
    if not os.path.exists(INDEX):
        return []
    with open(INDEX, encoding="utf-8") as f:
        rows = [json.loads(line) for line in f if line.strip()]
    return list(reversed(rows))[:limit]


def load(run_id):
    path = os.path.join(RUNS, run_id + ".json")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def delete(run_id):
    path = os.path.join(RUNS, run_id + ".json")
    if os.path.exists(path):
        os.remove(path)
    if os.path.exists(INDEX):
        with open(INDEX, encoding="utf-8") as f:
            rows = [line for line in f if line.strip() and json.loads(line)["id"] != run_id]
        with open(INDEX, "w", encoding="utf-8") as f:
            f.writelines(rows)


def runs_since(epoch):
    """Index entries recorded at or after the given time.time() value, oldest first."""
    stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(epoch))
    return [r for r in reversed(list_runs(limit=100000)) if r["time"] >= stamp]
