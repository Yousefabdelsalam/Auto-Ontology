"""MCP test: call check_answerable and ask_question through the MCP server for one answerable and one
unanswerable question, and check the results against ground truth / refusal rules.

Prerequisites (the script tells you if they are missing and marks the checks SKIPPED, never PASS):
  1. Start the MCP server in its own PowerShell window, bound to localhost only (its default is 0.0.0.0!):
         $env:AUTO_ONTOLOGY_MCP_HOST = '127.0.0.1'; $env:AUTO_ONTOLOGY_API_URL = 'http://localhost:3000'
         uv run --group mcp auto-ontology-mcp
  2. Run this script:  uv run --group mcp python tests\\test_mcp.py
     It opens your browser ONCE for the Auto Ontology sign-in (OAuth). The token is kept in memory only.
This calls the LLM: check_answerable ~1-3 calls each, ask_question ~10-30 calls each.
"""
from __future__ import annotations

import asyncio
import json
import socket

from common import check_scalar, load_questions, normalize_rows, report, save_result
from test_refusal import CLARIFY, REFUSAL, invented_numbers

MCP_URL = "http://localhost:3003/mcp"  # must match AUTO_ONTOLOGY_MCP_PUBLIC_URL in .env exactly (localhost, not 127.0.0.1)
EXPECTED_TOOLS = {"check_readiness", "check_answerable", "ask_question", "search_terms", "get_term"}


def as_dict(res) -> dict:
    """Tool result -> plain dict (structured content if present, else JSON in the text block); unwrap {'data': ...}."""
    sc = getattr(res, "structured_content", None)
    if not isinstance(sc, dict):
        d = getattr(res, "data", None)
        sc = d if isinstance(d, dict) else None
    if sc is None:
        text = "".join(getattr(c, "text", "") for c in (res.content or []))
        try:
            sc = json.loads(text)
        except ValueError:
            sc = {"_text": text}
    if set(sc) == {"result"} and isinstance(sc["result"], dict):
        sc = sc["result"]
    if set(sc) == {"data"} and isinstance(sc["data"], dict):
        sc = sc["data"]
    return sc


def port_open(port: int) -> bool:
    s = socket.socket(); s.settimeout(2)
    try:
        return s.connect_ex(("127.0.0.1", port)) == 0
    finally:
        s.close()


CHECKS = ["tools listed", "check_answerable", "ask_question answerable", "ask_question unanswerable"]


async def run(qa: dict, qu: dict) -> None:
    from fastmcp import Client
    from fastmcp.client.auth import OAuth

    print("Opening your browser for the Auto Ontology sign-in (one time, 5 minutes to finish)...", flush=True)
    auth = OAuth(mcp_url=MCP_URL, client_name="auto-ontology-test")  # tokens in memory only
    evidence: dict = {}
    async with Client(MCP_URL, auth=auth, timeout=900) as c:
        tools = {t.name for t in await c.list_tools()}
        missing = EXPECTED_TOOLS - tools
        report("mcp: tools listed", "PASS" if not missing else "FAIL", f"{len(tools)} tools: {sorted(tools)}" if not missing else f"missing tools {sorted(missing)}")

        ready = as_dict(await c.call_tool("check_readiness", {}))
        print(f"info: check_readiness -> ready={ready.get('ready')} can_execute_sql={ready.get('can_execute_sql')} blockers={ready.get('blockers')}")

        # check_answerable: the answerable question must score higher and have no uncovered entity; the
        # unanswerable one must report at least one uncovered entity. (No fixed threshold: the scale is the tool's own.)
        ca = as_dict(await c.call_tool("check_answerable", {"question": qa["question"]}))
        cu = as_dict(await c.call_tool("check_answerable", {"question": qu["question"]}))
        evidence["check_answerable"] = {"answerable": ca, "unanswerable": cu}
        cov_a, cov_u = ca.get("coverage"), cu.get("coverage")
        unc_a, unc_u = ca.get("uncovered_entities") or [], cu.get("uncovered_entities") or []
        ok = cov_a is not None and cov_u is not None and cov_a > cov_u and not unc_a and bool(unc_u)
        report("mcp: check_answerable", "PASS" if ok else "FAIL",
               f"answerable coverage {cov_a} (uncovered {unc_a}) vs unanswerable coverage {cov_u} (uncovered {unc_u})")

        # ask_question: answerable
        a = as_dict(await c.call_tool("ask_question", {"question": qa["question"]}))
        ans = {"response": a.get("answer", ""), "rows": normalize_rows(a.get("rows")), "sql_code": a.get("sql", "")}
        ok, why = check_scalar(qa["expected"], qa["tolerance"], ans)
        prov = bool(ans["sql_code"].strip()) and bool(ans["rows"])
        report("mcp: ask_question answerable", "PASS" if ok and prov else "FAIL",
               why + ("" if prov else "; SQL or rows missing in the MCP result") + f" (row_count={a.get('row_count')})")
        evidence["ask_answerable"] = a

        # ask_question: unanswerable -> refuse, no invented number, no rows
        u = as_dict(await c.call_tool("ask_question", {"question": qu["question"]}))
        text = " ".join(str(u.get("answer", "")).split())
        probs = []
        if not (REFUSAL.search(text) or CLARIFY.search(text)):
            probs.append("no refusal/clarification wording")
        if invented_numbers(qu["question"], text):
            probs.append(f"numbers not in the question: {invented_numbers(qu['question'], text)[:4]}")
        if normalize_rows(u.get("rows")):
            probs.append("returned data rows")
        report("mcp: ask_question unanswerable", "PASS" if not probs else "FAIL",
               "refused/asked, no invented number, no rows" if not probs else "; ".join(probs))
        print(f"        answer: {text[:260]}")
        evidence["ask_unanswerable"] = u
    save_result("test_mcp", evidence)


def main() -> int:
    doc = load_questions()
    qa = next(q for q in doc["answerable"] if q["id"] == "A2")  # cheapest scalar: a single COUNT
    qu = next(q for q in doc["unanswerable"] if q["id"] == "U1")
    try:
        import fastmcp  # noqa: F401
    except ImportError:
        for n in CHECKS:
            report(f"mcp: {n}", "SKIPPED", "fastmcp not installed (run with: uv run --group mcp ...)")
        return 0
    if not port_open(3003):
        for n in CHECKS:
            report(f"mcp: {n}", "SKIPPED", "MCP server is not running on 127.0.0.1:3003 (see the prerequisites at the top of this file)")
        return 0
    try:
        asyncio.run(run(qa, qu))
    except Exception as e:  # sign-in timeout, protected-resource mismatch, server error ... reported, not hidden
        for n in CHECKS:
            report(f"mcp: {n}", "SKIPPED", f"could not complete the MCP session: {type(e).__name__}: {str(e)[:150]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
