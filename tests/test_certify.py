"""Certification test: ask the same margin question BEFORE and AFTER certifying a precise SQL attribute.

1. Ask C1 ("gross margin percentage in 2015") -> record answer + SQL.
2. Create the SQL attribute "Gross Margin Percentage" under the term "Invoice Line" through the API, then certify it.
   (No UI click needed: POST /api/sql-attributes + PATCH {certified: true}.)
3. Ask the same question again and compare answer and SQL. One sample per side: an LLM can vary run to run,
   so a difference is evidence, not proof.
The attribute is left in place (so test_export includes it); pass --cleanup to delete it again afterwards.
This calls the LLM: about 10-30 model calls per ask (2 asks) plus 1-2 embedding calls.
"""
from __future__ import annotations

import re
import sys

from common import NoToken, api, api_json, ask, check_scalar, load_questions, report, save_result

ATTR_NAME = "Gross Margin Percentage"
DESCRIPTION = ("Gross margin percentage = total line profit divided by total extended price, times 100: "
               "SUM(lineprofit) / SUM(extendedprice) * 100 over invoice lines. Also called margin, profit margin or gross margin %.")
# Full query over catalog tables (a bare expression is rejected by the API). Table-name spellings are tried in order;
# the first one /validate accepts is used.
EXPRESSIONS = [
    "SELECT SUM(il.lineprofit) / SUM(il.extendedprice) * 100 AS gross_margin_pct FROM sales.invoicelines il",
    "SELECT SUM(il.lineprofit) / SUM(il.extendedprice) * 100 AS gross_margin_pct FROM wideworldimporters.sales.invoicelines il",
]


def norm(sql: str) -> str:
    return re.sub(r"\s+", " ", sql or "").strip().lower()


def find_term(name: str) -> dict | None:
    skip = 0
    while True:
        page = api_json("GET", f"/api/terms?skip={skip}&limit=50")
        for t in page["terms"]:
            if (t["name"] or "").lower() == name.lower():
                return t
        skip += 50
        if skip >= page["total"]:
            return None


def main(cleanup: bool) -> int:
    q = load_questions()["certify"]
    try:
        before = ask("test_certify", "C1-before", q["question"])
    except NoToken as e:
        for n in ["before answer", "create+certify attribute", "after answer", "comparison"]:
            report(f"certify: {n}", "SKIPPED", str(e))
        return 0
    b_ok, b_why = check_scalar(q["expected"], q["tolerance"], before) if not before["error"] else (False, f"agent error: {before['error'][:140]}")
    report("certify: before answer", "PASS" if b_ok else "FAIL", b_why)
    print(f"        before SQL: {norm(before['sql_code'])[:300] or '(none)'}")

    term = find_term("Invoice Line")
    if not term:
        report("certify: create+certify attribute", "FAIL", "term 'Invoice Line' not found")
        return 0
    existing = api_json("GET", f"/api/terms/{term['id']}/sql-attributes")["data"]
    attr = next((a for a in existing if (a["name"] or "").lower() == ATTR_NAME.lower()), None)
    if attr is None:
        expr, last = None, ""
        for cand in EXPRESSIONS:
            r = api_json("POST", "/api/sql-attributes/validate", json={"expression": cand, "term_id": term["id"]})
            if r["data"]["valid"]:
                expr = cand
                break
            last = str(r)
        if expr is None:
            report("certify: create+certify attribute", "FAIL", f"API rejected every expression spelling: {last[:160]}")
            return 0
        created = api_json("POST", "/api/sql-attributes", json={"name": ATTR_NAME, "description": DESCRIPTION, "expression": expr,
                                                                 "term_id": term["id"], "source": "manual"})
        attr = created.get("data", created)
    done = api_json("PATCH", f"/api/sql-attributes/{attr['id']}", json={"certified": True})
    cert = done["data"].get("certified")
    report("certify: create+certify attribute", "PASS" if cert else "FAIL",
           f"'{ATTR_NAME}' under 'Invoice Line', certified={cert}, term certification={done.get('term_certification')}")

    after = ask("test_certify", "C1-after", q["question"])
    a_ok, a_why = check_scalar(q["expected"], q["tolerance"], after) if not after["error"] else (False, f"agent error: {after['error'][:140]}")
    report("certify: after answer", "PASS" if a_ok else "FAIL", a_why)
    print(f"        after SQL:  {norm(after['sql_code'])[:300] or '(none)'}")

    same_sql = norm(before["sql_code"]) == norm(after["sql_code"])
    same_ans = (before["response"].strip() == after["response"].strip())
    uses_attr = all(w in norm(after["sql_code"]) for w in ("lineprofit", "extendedprice"))
    print(f"        answer text changed: {not same_ans}   SQL changed: {not same_sql}   after-SQL uses lineprofit/extendedprice: {uses_attr}")
    # The comparison passes only if the result got better or stayed correct; "changed but still wrong" or
    # "got worse" is a FAIL. A single before/after pair cannot prove cause and effect.
    if b_ok and a_ok:
        report("certify: comparison", "PASS", "correct before and after" + ("; SQL changed" if not same_sql else "; SQL identical"))
    elif a_ok and not b_ok:
        report("certify: comparison", "PASS", "wrong/unverified before, correct after certification")
    else:
        report("certify: comparison", "FAIL", "answer is not correct after certification" + (" (was correct before)" if b_ok else ""))
    save_result("test_certify", {"before": before, "after": after, "attribute_id": attr["id"], "sql_changed": not same_sql, "answer_changed": not same_ans})

    if cleanup:
        resp = api("DELETE", f"/api/sql-attributes/{attr['id']}")
        print(f"cleanup: DELETE attribute -> HTTP {resp.status_code}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main("--cleanup" in sys.argv))
