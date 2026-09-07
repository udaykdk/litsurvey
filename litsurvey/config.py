"""Configuration: ~/.litsurvey/config.json, with environment variable overrides.

Keys (all optional):
  s2_api_key        Semantic Scholar API key (1 request/second dedicated)
  openalex_mailto   your email; gives OpenAlex's polite pool, also used by Unpaywall
  backend           default LLM backend: ollama | openai | anthropic
  model             default model name for the backend
  ollama_host       default http://localhost:11434
  openai_base_url   default https://api.openai.com (LM Studio: http://localhost:1234)
  openai_api_key
  anthropic_api_key
"""
import json
import os

DATA_DIR = os.path.join(os.path.expanduser("~"), ".litsurvey")
CONFIG_PATH = os.path.join(DATA_DIR, "config.json")
LEGACY_PATH = os.path.expanduser("~/.litsearch.json")

ENV_MAP = {
    "s2_api_key": ("LITSURVEY_S2_API_KEY", "S2_API_KEY"),
    "openalex_mailto": ("LITSURVEY_MAILTO", "OPENALEX_MAILTO"),
    "backend": ("LITSURVEY_BACKEND",),
    "model": ("LITSURVEY_MODEL",),
    "ollama_host": ("OLLAMA_HOST",),
    "openai_base_url": ("OPENAI_BASE_URL",),
    "openai_api_key": ("OPENAI_API_KEY",),
    "anthropic_api_key": ("ANTHROPIC_API_KEY",),
}

DEFAULTS = {
    "s2_api_key": "",
    "openalex_mailto": "",
    "backend": "",
    "model": "",
    "ollama_host": "http://localhost:11434",
    "openai_base_url": "https://api.openai.com",
    "openai_api_key": "",
    "anthropic_api_key": "",
}


def _read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        import sys
        print(f"[warn] could not read {path}: {e}", file=sys.stderr)
        return {}


def load():
    cfg = dict(DEFAULTS)
    cfg.update({k: v for k, v in _read_json(LEGACY_PATH).items() if k in DEFAULTS})
    cfg.update({k: v for k, v in _read_json(CONFIG_PATH).items() if k in DEFAULTS})
    for key, envs in ENV_MAP.items():
        for env in envs:
            val = os.environ.get(env)
            if val:
                cfg[key] = val
                break
    # a placeholder left in the file must not be sent as a key
    if "PASTE" in (cfg.get("s2_api_key") or "").upper():
        cfg["s2_api_key"] = ""
    # normalise host URLs
    for k in ("ollama_host", "openai_base_url"):
        v = cfg.get(k) or DEFAULTS[k]
        if not v.startswith("http"):
            v = "http://" + v
        cfg[k] = v.rstrip("/")
    return cfg


def save(values):
    """Write the given keys to the config file, keeping other existing keys."""
    os.makedirs(DATA_DIR, exist_ok=True)
    current = _read_json(CONFIG_PATH)
    current.update({k: v for k, v in values.items() if k in DEFAULTS})
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(current, f, indent=2)
        f.write("\n")
    try:
        os.chmod(CONFIG_PATH, 0o600)
    except OSError:
        pass
    return CONFIG_PATH


CFG = load()
