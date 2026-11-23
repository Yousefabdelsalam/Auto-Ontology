"""Shared helpers for the test scripts. Keeps secrets out of output and out of code.

Secrets come from auto-ontology/.env (or from environment variables) and are never printed.
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / "auto-ontology" / ".env"
QUESTIONS = Path(__file__).with_name("questions.json")
# Use 127.0.0.1, not "localhost": on Windows "localhost" tries IPv6 ::1 first, Docker only publishes
# on IPv4 127.0.0.1, so ::1 hangs until a timeout (seen: 8 s per connection, and unbounded without a timeout).
BASE_URL = os.environ.get("AUTO_ONTOLOGY_URL", "http://127.0.0.1:3000")


def load_env() -> dict[str, str]:
    """Parse auto-ontology/.env into a dict (simple KEY=VALUE lines; no printing)."""
    env: dict[str, str] = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def db_connect(dbname: str = "wideworldimporters"):
    """Read-only connection straight to the sample database on localhost."""
    import psycopg

    env = load_env()
    conn = psycopg.connect(
        host="127.0.0.1",
        port=int(env.get("POSTGRES_PORT", "5432")),
        user=env.get("POSTGRES_USER", "postgres"),
        password=env["POSTGRES_PASSWORD"],
        dbname=dbname,
        connect_timeout=10,  # never hang silently
    )
    conn.read_only = True  # ground truth must never modify data
    return conn


RESULTS_DIR = Path(__file__).with_name("results")


def load_questions() -> dict:
    import json
    return json.loads(QUESTIONS.read_text(encoding="utf-8"))


def save_result(name: str, obj) -> None:
    """Keep raw evidence (answers, SQL, steps) so RESULTS.md can cite it. Never contains secrets."""
    import json
    RESULTS_DIR.mkdir(exist_ok=True)
    (RESULTS_DIR / f"{name}.json").write_text(json.dumps(obj, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


# ---------------------------------------------------------------- REST client (API token) ----------
def token() -> str | None:
    """API token from the environment, else from auto-ontology/.env (mint it in the UI: user menu -> API Tokens).

    .env is the only file that may hold a secret. The token is never printed or logged.
    """
    return os.environ.get("AUTO_ONTOLOGY_API_TOKEN") or load_env().get("AUTO_ONTOLOGY_API_TOKEN") or None


class NoToken(Exception):
    pass


def api(method: str, path: str, timeout: int = 60, **kw):
    """Call the web app's public API with the API token. Raises NoToken if no token is set."""
    import requests

    tok = token()
    if not tok:
        raise NoToken("AUTO_ONTOLOGY_API_TOKEN is not set")
    headers = {"x-api-key": tok, **kw.pop("headers", {})}
    return requests.request(method, BASE_URL + path, headers=headers, timeout=timeout, **kw)


def api_json(method: str, path: str, **kw):
    r = api(method, path, **kw)
    if r.status_code >= 400:
        raise RuntimeError(f"HTTP {r.status_code} {method} {path}: {r.text[:300]}")
    return r.json()


def normalize_rows(rows) -> list[list]:
    """Rows may come back as list[dict], list[list] or {'rows': [...]}; make it list[list]."""
    if isinstance(rows, dict):
        rows = rows.get("rows") or rows.get("data") or []
    out = []
    for r in rows or []:
        out.append(list(r.values()) if isinstance(r, dict) else (list(r) if isinstance(r, (list, tuple)) else [r]))
    return out


def ask(script: str, qid: str, question: str, timeout: int = 600) -> dict:
    """POST /api/chat/completions (stateless: no conversation_id => no chart step, fewer model calls).

    Returns response text, sql_code, rows, steps and thoughts, plus an 'error' if the run failed.
    Every call is appended to results/ask_log.jsonl so the report can count questions asked.
    """
    import json
    import time

    t0 = time.time()
    out = {"qid": qid, "question": question, "response": "", "sql_code": "", "rows": [], "steps": [], "thoughts": None,
           "sql_events": [], "error": None, "event_types": []}
    try:
        r = api("POST", "/api/chat/completions", timeout=timeout, stream=True, json={"question": question})
        if r.status_code >= 400:
            out["error"] = f"HTTP {r.status_code}: {r.text[:300]}"
        else:
            for raw in r.iter_lines():  # bytes: decode as UTF-8 ourselves (SSE default charset guess is wrong)
                line = raw.decode("utf-8", errors="replace")
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    break
                ev = json.loads(payload)
                out["event_types"].append(ev.get("type"))
                if ev["type"] == "step":
                    out["steps"].append({"node": ev.get("node"), "phase": ev.get("phase")})
                elif ev["type"] == "sql":
                    out["sql_events"].append(ev)
                elif ev["type"] == "result":
                    a = ev.get("answer") or {}
                    out["response"] = a.get("response") or ""
                    out["sql_code"] = a.get("sql_code") or ""
                    out["rows"] = normalize_rows(a.get("sql_response_from_db"))
                    out["thoughts"] = a.get("thoughts")
                elif ev["type"] == "error":
                    out["error"] = ev.get("message") or "unknown error"
    except NoToken:
        raise
    except Exception as e:  # network/timeout/parse problems are reported, never hidden
        out["error"] = f"{type(e).__name__}: {str(e)[:300]}"
    out["seconds"] = round(time.time() - t0, 1)
    RESULTS_DIR.mkdir(exist_ok=True)
    with (RESULTS_DIR / "ask_log.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"script": script, "qid": qid, "seconds": out["seconds"], "step_events": len(out["steps"]),
                            "error": out["error"], "time": time.strftime("%Y-%m-%dT%H:%M:%S")}) + "\n")
    return out


# ---------------------------------------------------------------- answer checking (no LLM) --------
def numbers_in(text: str) -> list[float]:
    """All numbers in a text, e.g. '$36,018.00' -> 36018.0, '4.48 million' -> 4480000.0 (raw value also kept)."""
    import re
    vals: list[float] = []
    for m in re.finditer(r"(-?\d[\d,]*(?:\.\d+)?)\s*(million|billion|thousand|k|m|bn)?\b", text or "", re.I):
        try:
            v = float(m.group(1).replace(",", ""))
        except ValueError:
            continue
        vals.append(v)
        mult = {"million": 1e6, "m": 1e6, "billion": 1e9, "bn": 1e9, "thousand": 1e3, "k": 1e3}.get((m.group(2) or "").lower())
        if mult:
            vals.append(v * mult)
    return vals


def within(value: float, expected: float, tol: dict) -> bool:
    allowed = max(tol.get("abs", 0), tol.get("rel", 0) * abs(expected))
    return abs(value - expected) <= allowed + 1e-9


def first_row_numbers(rows: list[list]) -> list[float]:
    out = []
    for cell in (rows[0] if rows else []):
        try:
            out.append(float(cell))
        except (TypeError, ValueError):
            pass
    return out


def check_scalar(expected: float, tol: dict, ans: dict) -> tuple[bool, str]:
    """PASS needs the number in the ANSWER TEXT to match ground truth; also reports what the SQL rows say."""
    text_vals = numbers_in(ans["response"])
    row_vals = first_row_numbers(ans["rows"])
    in_text = [v for v in text_vals if within(v, expected, tol)]
    in_rows = [v for v in row_vals if within(v, expected, tol)]
    if in_text:
        note = "SQL rows agree" if in_rows else ("SQL rows not comparable (none/other values)" if not row_vals else f"but SQL rows say {row_vals[:3]}")
        return True, f"answer states {in_text[0]:g} (expected {expected:g}); {note}"
    if in_rows:
        return False, f"SQL rows have {in_rows[0]:g} (expected {expected:g}) but the answer text states {text_vals[:4]}"
    return False, f"expected {expected:g}; answer text numbers {text_vals[:5]}, SQL row values {row_vals[:3]}"


def report(name: str, status: str, reason: str) -> str:
    """One-line result. status is PASS, FAIL or SKIPPED (SKIPPED = could not run, never PASS)."""
    assert status in {"PASS", "FAIL", "SKIPPED"}
    line = f"{status:<7} {name}: {reason}"
    print(line)
    return status
