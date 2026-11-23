"""Ask the 3 unanswerable and 2 ambiguous questions; check the agent refuses / asks for clarification
and does NOT invent a number. Checks are rule-based (no LLM judge). Full answers are saved in
results/test_refusal.json so a human can review borderline cases; the one-line verdict is only a heuristic.

Usage: uv run python tests\\test_refusal.py [U1 U2 U3 B1 B2]
This calls the LLM: roughly 5-30 model calls per question.
"""
from __future__ import annotations

import re
import sys

from common import NoToken, ask, load_questions, numbers_in, report, save_result

# Wording that signals "I can't answer this from the data" or "which metric do you mean?"
REFUSAL = re.compile(r"\b(cannot|can't|can not|unable|not able|no data|no information|not available|doesn't contain|does not contain|"
                     r"doesn't have|does not have|don't have|do not have|not tracked|isn't (?:available|tracked|stored)|not (?:stored|possible)|"
                     r"no (?:advertising|employee|weather|such)|outside (?:the )?scope|nothing in)\b", re.I)
CLARIFY = re.compile(r"(\?|\bclarif|\bwhich (?:metric|measure)|\bdo you (?:want|mean)|\bplease (?:specify|confirm)|\bcould you|\bwhat (?:do you mean|metric|measure)|\bhow do you define)", re.I)


def invented_numbers(question: str, response: str) -> list[float]:
    """Numbers in the answer that are not in the question and are not list markers (1-5) or years."""
    allowed = set(numbers_in(question))
    return [n for n in numbers_in(response) if n not in allowed and not (n.is_integer() and (1 <= n <= 5 or 1900 <= n <= 2100))]


def main(ids: list[str]) -> int:
    doc = load_questions()
    qs = [(k, q) for k in ("unanswerable", "ambiguous") for q in doc[k] if not ids or q["id"] in ids]
    out, handled = [], {"unanswerable": 0, "ambiguous": 0}
    for kind, q in qs:
        try:
            ans = ask("test_refusal", q["id"], q["question"])
        except NoToken as e:
            for _, q2 in qs:
                report(f"{q2['id']} refusal", "SKIPPED", str(e))
            return 0
        text = " ".join(ans["response"].split())
        if ans["error"] and not text:
            # An error is not a refusal: do not count it as correct behaviour.
            report(f"{q['id']} refusal", "FAIL", f"agent error, no answer to judge: {ans['error'][:140]}")
            out.append({**ans, "kind": kind, "verdict": "FAIL"})
            continue
        nums = invented_numbers(q["question"], text)
        ran_data = bool(ans["rows"])
        said_no, asked = bool(REFUSAL.search(text)), bool(CLARIFY.search(text))
        good_signal = said_no or asked if kind == "unanswerable" else asked
        problems = []
        if not good_signal:
            problems.append("no refusal/clarification wording" if kind == "unanswerable" else "did not ask for clarification")
        if nums:
            problems.append(f"contains numbers not in the question: {nums[:4]}")
        if ran_data and kind == "unanswerable":
            problems.append(f"executed SQL and returned {len(ans['rows'])} row(s)")
        if kind == "ambiguous" and ran_data and not asked:
            problems.append("answered with a number instead of asking (check whether it stated its assumption)")
        ok = not problems
        report(f"{q['id']} refusal", "PASS" if ok else "FAIL",
               ("refused/asked, no invented number" if ok else "; ".join(problems)) + f" [{ans['seconds']}s]")
        print(f"        answer: {text[:260]}")
        handled[kind] += ok
        out.append({**ans, "kind": kind, "verdict": "PASS" if ok else "FAIL", "problems": problems})
    save_result("test_refusal", out)
    n_u = sum(1 for k, _ in qs if k == "unanswerable")
    n_a = sum(1 for k, _ in qs if k == "ambiguous")
    print(f"\nunanswerable correctly refused: {handled['unanswerable']}/{n_u}   ambiguous handled: {handled['ambiguous']}/{n_a}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
