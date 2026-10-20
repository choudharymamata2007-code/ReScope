"""Task 2.1: one function for every model call.

    llm.call(prompt_id, inputs, schema)       -> validated dict, or raises LLMUnavailable
    llm.try_call(prompt_id, inputs, schema)   -> validated dict, or None (stages then use their rule-based path)

Handles retries with back-off, fallback to a second/third provider, JSON validation and SQLite logging
(prompt, response, tokens, seconds). With no API key the wrapper reports unavailable and the pipeline
still completes on its deterministic rules, so the demo never depends on a model."""
from __future__ import annotations
import json
import os
import re
import sqlite3
import time
from pathlib import Path
from typing import Callable, Optional

from . import prompts

DB_PATH = Path(os.environ.get("RESCOPE_M2_DB", Path(__file__).resolve().parent.parent / "data" / "m2_runs.db"))


class LLMUnavailable(RuntimeError):
    pass


class LLMSchemaError(ValueError):
    pass


# ------------------------------------------------------------------ providers
def _anthropic(system: str, user: str, post: Callable, timeout: int) -> tuple[str, dict]:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise LLMUnavailable("ANTHROPIC_API_KEY not set")
    model = os.environ.get("RESCOPE_LLM_MODEL", "claude-sonnet-5-5")
    r = post("https://api.anthropic.com/v1/messages",
             headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
             json={"model": model, "max_tokens": 1500, "system": system,
                   "messages": [{"role": "user", "content": user}]}, timeout=timeout)
    r.raise_for_status()
    d = r.json()
    text = "".join(b.get("text", "") for b in d.get("content", []))
    u = d.get("usage", {})
    return text, {"model": model, "tokens_in": u.get("input_tokens"), "tokens_out": u.get("output_tokens")}


def _gemini(system: str, user: str, post: Callable, timeout: int) -> tuple[str, dict]:
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise LLMUnavailable("GEMINI_API_KEY not set")
    model = os.environ.get("RESCOPE_GEMINI_MODEL", "gemini-2.0-flash")
    r = post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}",
             headers={"content-type": "application/json"},
             json={"systemInstruction": {"parts": [{"text": system}]},
                   "contents": [{"role": "user", "parts": [{"text": user}]}]}, timeout=timeout)
    r.raise_for_status()
    d = r.json()
    text = "".join(p.get("text", "") for p in d["candidates"][0]["content"]["parts"])
    u = d.get("usageMetadata", {})
    return text, {"model": model, "tokens_in": u.get("promptTokenCount"), "tokens_out": u.get("candidatesTokenCount")}


def _groq(system: str, user: str, post: Callable, timeout: int) -> tuple[str, dict]:
    key = os.environ.get("GROQ_API_KEY")
    if not key:
        raise LLMUnavailable("GROQ_API_KEY not set")
    model = os.environ.get("RESCOPE_GROQ_MODEL", "llama-3.3-70b-versatile")
    r = post("https://api.groq.com/openai/v1/chat/completions",
             headers={"Authorization": f"Bearer {key}", "content-type": "application/json"},
             json={"model": model, "messages": [{"role": "system", "content": system},
                                                 {"role": "user", "content": user}]}, timeout=timeout)
    r.raise_for_status()
    d = r.json()
    u = d.get("usage", {})
    return d["choices"][0]["message"]["content"], {"model": model, "tokens_in": u.get("prompt_tokens"),
                                                   "tokens_out": u.get("completion_tokens")}


PROVIDERS = {"anthropic": _anthropic, "gemini": _gemini, "groq": _groq}


def provider_order() -> list[str]:
    return [p.strip() for p in os.environ.get("RESCOPE_LLM_ORDER", "anthropic,gemini,groq").split(",") if p.strip()]


def available() -> bool:
    keys = {"anthropic": "ANTHROPIC_API_KEY", "gemini": "GEMINI_API_KEY", "groq": "GROQ_API_KEY"}
    return any(os.environ.get(keys[p]) for p in provider_order() if p in keys)


# ------------------------------------------------------------------ schema and JSON
def extract_json(text: str):
    t = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", t, flags=re.S)
        if not m:
            raise LLMSchemaError("reply contains no JSON object")
        return json.loads(m.group(0))


def validate(obj, schema) -> dict:
    """schema: None, a callable that returns the checked dict, or {key: type | (types...)}."""
    if schema is None:
        return obj
    if callable(schema):
        return schema(obj)
    if not isinstance(obj, dict):
        raise LLMSchemaError("reply is not a JSON object")
    for k, t in schema.items():
        if k not in obj:
            raise LLMSchemaError(f"missing key: {k}")
        if t is not None and not isinstance(obj[k], t):
            raise LLMSchemaError(f"key {k} has wrong type")
    return obj


# ------------------------------------------------------------------ logging
def _log(row: dict, db_path: Path = DB_PATH) -> None:
    try:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(db_path)
        con.execute("""CREATE TABLE IF NOT EXISTS llm_log(ts REAL, prompt_id TEXT, version TEXT, provider TEXT,
                       model TEXT, prompt TEXT, response TEXT, tokens_in INT, tokens_out INT, seconds REAL,
                       ok INT, error TEXT)""")
        con.execute("INSERT INTO llm_log VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (row["ts"], row["prompt_id"], row["version"], row["provider"], row.get("model"),
                     row["prompt"], row.get("response"), row.get("tokens_in"), row.get("tokens_out"),
                     row["seconds"], int(row["ok"]), row.get("error")))
        con.commit()
        con.close()
    except Exception:  # logging must never break a run
        pass


def read_log(limit: int = 50, db_path: Path = DB_PATH) -> list[dict]:
    if not Path(db_path).exists():
        return []
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    rows = [dict(r) for r in con.execute("SELECT * FROM llm_log ORDER BY ts DESC LIMIT ?", (limit,))]
    con.close()
    return rows


# ------------------------------------------------------------------ the one function
def call(prompt_id: str, inputs: dict, schema=None, *, post: Optional[Callable] = None,
         max_retries: int = 2, timeout: int = 60, db_path: Path = DB_PATH,
         providers: Optional[dict] = None, order: Optional[list[str]] = None) -> dict:
    spec = prompts.load(prompt_id)
    system, user = prompts.render(spec, inputs)
    if post is None:
        import requests  # imported late so tests and offline runs need no network library
        post = requests.post
    table = providers or PROVIDERS
    errors: list[str] = []
    for name in (order or provider_order()):
        fn = table.get(name)
        if fn is None:
            continue
        for attempt in range(max_retries + 1):
            t0 = time.time()
            row = {"ts": t0, "prompt_id": prompt_id, "version": str(spec.get("version", "")), "provider": name,
                   "prompt": user, "ok": False}
            try:
                text, meta = fn(system, user, post, timeout)
                row.update(meta, response=text)
                result = validate(extract_json(text), schema)
                row.update(ok=True, seconds=time.time() - t0)
                _log(row, db_path)
                return result
            except LLMUnavailable as e:  # no key for this provider: go straight to the next one
                errors.append(f"{name}: {e}")
                break
            except Exception as e:  # network, HTTP, bad JSON, schema: back off and retry, then fall back
                row.update(error=str(e), seconds=time.time() - t0)
                _log(row, db_path)
                errors.append(f"{name}: {e}")
                if attempt < max_retries:
                    time.sleep(min(2 ** attempt, 4))
    raise LLMUnavailable("; ".join(errors) or "no provider configured")


def try_call(prompt_id: str, inputs: dict, schema=None, **kw) -> Optional[dict]:
    if not available() and not kw.get("providers"):
        return None
    try:
        return call(prompt_id, inputs, schema, **kw)
    except (LLMUnavailable, LLMSchemaError):
        return None


def numbers_in(text: str) -> set[str]:
    return set(re.findall(r"\d+(?:\.\d+)?", text or ""))


def numbers_grounded(text: str, allowed_text: str) -> bool:
    """Guard: every number a model writes must already appear in the figures the code computed."""
    return numbers_in(text) <= numbers_in(allowed_text)
