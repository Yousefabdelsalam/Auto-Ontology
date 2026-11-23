"""Ask the 6 answerable questions through the REST chat endpoint and compare with direct-SQL ground truth.

Per question, three checks: VALUE (answer text vs ground truth), SQL (SQL returned), PROVENANCE (SQL + steps + rows).
Usage:  uv run python tests\\test_answers.py          (all 6)
        uv run python tests\\test_answers.py A1 A4    (only these; handy for a cheap smoke test)
This calls the LLM: roughly 10-30 model calls per question.
"""
from __future__ import annotations

import sys

from common import NoToken, ask, check_scalar, load_questions, numbers_in, report, save_result, within


def check_list(expected: list[dict], tol: dict, ans: dict) -> tuple[bool, str]:
    """Top-N list: names must appear in the right ORDER (rows first column, else order of first mention in the text)."""
    names = [e["name"] for e in expected]
    row_names = [str(r[0]) for r in ans["rows"][: len(names)]]
    text = ans["response"]
    positions = [text.lower().find(n.lower()) for n in names]
    all_found = all(p >= 0 for p in positions)
    text_in_order = all_found and positions == sorted(positions)
    rows_match = row_names == names  # SQL rows must list the same names in the same order
    if text_in_order and (rows_match or not row_names):
        stated = numbers_in(text)
        has_values = all(any(within(v, e["value"], tol) for v in stated) for e in expected)
        return True, f"names in the correct order ({'revenue values also stated' if has_values else 'revenue values not all stated'})"
    found = [n for n, p in zip(names, positions) if p >= 0]
    if all_found and not text_in_order:
        order = [names[i] for i in sorted(range(len(names)), key=lambda i: positions[i])]
        return False, f"right names, wrong order in the text: {order}; SQL rows {row_names}"
    return False, f"expected {names}; names found in text {found}; SQL rows {row_names}"


def main(ids: list[str]) -> int:
    qs = [q for q in load_questions()["answerable"] if not ids or q["id"] in ids]
    results, value_pass = [], 0
    for q in qs:
        try:
            ans = ask("test_answers", q["id"], q["question"])
        except NoToken as e:
            for q2 in qs:
                for what in ("value", "sql", "provenance"):
                    report(f"{q2['id']} {what}", "SKIPPED", str(e))
            return 0
        if ans["error"] and not ans["response"]:
            report(f"{q['id']} value", "FAIL", f"agent error: {ans['error'][:160]}")
            report(f"{q['id']} sql", "FAIL", "no SQL returned (agent error)")
            report(f"{q['id']} provenance", "FAIL", "no result event")
            results.append({**ans, "checks": {"value": "FAIL"}})
            continue
        ok, why = check_list(q["expected"], q["tolerance"], ans) if q["kind"] == "list" else check_scalar(q["expected"], q["tolerance"], ans)
        s_value = report(f"{q['id']} value", "PASS" if ok else "FAIL", why)
        s_sql = report(f"{q['id']} sql", "PASS" if ans["sql_code"].strip() else "FAIL",
                       f"{len(ans['sql_code'])} chars of SQL returned" if ans["sql_code"].strip() else "no sql_code in the answer")
        have = {"sql": bool(ans["sql_code"].strip()), "steps": bool(ans["steps"] or ans["thoughts"]), "rows": bool(ans["rows"])}
        missing = [k for k, v in have.items() if not v]
        s_prov = report(f"{q['id']} provenance", "PASS" if not missing else "FAIL",
                        "SQL, steps and rows present" if not missing else f"missing: {', '.join(missing)}")
        value_pass += s_value == "PASS"
        print(f"        ({ans['seconds']}s) answer: {' '.join(ans['response'].split())[:230]}")
        results.append({**ans, "expected": q["expected"], "checks": {"value": s_value, "sql": s_sql, "provenance": s_prov}})
    save_result("test_answers", results)
    print(f"\nanswerable correct: {value_pass}/{len(qs)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
