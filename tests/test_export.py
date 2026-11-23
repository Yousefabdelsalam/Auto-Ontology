"""Export the ontology as Apache Ossie YAML and check it. No LLM calls.

Checks: the export call succeeds, the YAML parses to a non-empty mapping, it contains our key terms/tables
(and the certified SQL attribute if test_certify ran), and it does NOT contain the database password.
Re-import into a clean state is SKIPPED on purpose: a clean state means resetting the compiled ontology
(destructive, ~40 min and many LLM calls to rebuild). Strict Ossie-spec validation is SKIPPED too: no
Ossie validator is installed here, so "valid" below means "well-formed YAML with the expected content".
Needs AUTO_ONTOLOGY_API_TOKEN of an admin (export is admin-only).
"""
from __future__ import annotations

from common import NoToken, RESULTS_DIR, api, load_env, report


def main() -> int:
    try:
        r = api("POST", "/api/model/export", timeout=120, json={"databases": [], "format": "ossie"})
    except NoToken as e:
        for n in ["export call", "yaml valid", "content", "no secrets", "re-import", "strict ossie schema"]:
            report(f"export: {n}", "SKIPPED", str(e))
        return 0
    if r.status_code >= 400:
        report("export: export call", "FAIL", f"HTTP {r.status_code}: {r.text[:200]}")
        return 0
    text = r.text
    report("export: export call", "PASS", f"HTTP {r.status_code}, {len(text)} chars, content-type {r.headers.get('content-type', '?')}")

    import yaml
    try:
        docs = [d for d in yaml.safe_load_all(text) if d is not None]
        ok = bool(docs) and all(isinstance(d, (dict, list)) for d in docs)
        top = sorted(docs[0].keys()) if docs and isinstance(docs[0], dict) else []
        report("export: yaml valid", "PASS" if ok else "FAIL", f"{len(docs)} YAML document(s); top-level keys: {top[:8]}")
    except yaml.YAMLError as e:
        report("export: yaml valid", "FAIL", f"YAML parse error: {str(e)[:160]}")
        return 0

    low = text.lower()
    wanted = ["customer", "invoice", "stock item", "invoicelines", "extendedprice"]
    missing = [w for w in wanted if w not in low]
    report("export: content", "PASS" if not missing else "FAIL",
           "contains key terms/tables/columns" if not missing else f"missing from export: {missing}")
    if "gross margin percentage" in low:
        print("info: the certified SQL attribute 'Gross Margin Percentage' (from test_certify) is in the export")
    else:
        print("info: 'Gross Margin Percentage' is not in the export (test_certify not run yet, or it is not exported)")

    pw = load_env().get("POSTGRES_PASSWORD", "")
    leaked = bool(pw) and pw in text
    report("export: no secrets", "FAIL" if leaked else "PASS",
           "the export contains the database password (not saved to disk)" if leaked else "database password not present in the export")
    if not leaked:
        RESULTS_DIR.mkdir(exist_ok=True)
        (RESULTS_DIR / "ontology_ossie.yaml").write_text(text, encoding="utf-8")
        print(f"info: saved results/ontology_ossie.yaml ({len(text)} chars)")

    report("export: re-import", "SKIPPED", "needs a clean state = destructive reset + ~40 min recompile; not done")
    report("export: strict ossie schema", "SKIPPED", "no Ossie schema validator installed; only well-formedness was checked")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
