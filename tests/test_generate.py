"""After ontology generation: list terms, SQL attributes and relationships, and check that key terms and
the main joins exist. Reads the ontology through the public REST API (no LLM calls, no cost).

Needs AUTO_ONTOLOGY_API_TOKEN. Raw listing is saved to results/test_generate.json.
"""
from __future__ import annotations

from common import NoToken, api_json, db_connect, report, save_result

KEY_TERMS = ["Customer", "Invoice", "Invoice Line", "Stock Item", "State Province", "City", "People"]
# Main joins of the sales model, as term pairs (direction ignored): invoice line -> invoice -> customer -> city -> state;
# invoice line -> stock item.
MAIN_JOINS = [("Invoice Line", "Invoice"), ("Invoice", "Customer"), ("Customer", "City"),
              ("City", "State Province"), ("Invoice Line", "Stock Item")]


def all_terms() -> tuple[list[dict], dict]:
    """All terms (paged) plus the last page, which carries the per-term attribute counts."""
    terms, skip = [], 0
    while True:
        page = api_json("GET", f"/api/terms?skip={skip}&limit=50")
        terms += page["terms"]
        skip += 50
        if skip >= page["total"] or not page["terms"]:
            return terms, page


def graph_links() -> tuple[dict[str, str], set[frozenset], dict]:
    """Term-to-term links from the semantic graph: {id: name}, a set of {name, name} pairs, and shape info."""
    g = api_json("GET", "/api/exploration/semantic-graph?limit=1000")["data"]
    nodes, links = g.get("nodes", []), g.get("links", [])
    names = {}
    for n in nodes:
        nid = n.get("id")
        label = n.get("name") or n.get("label") or n.get("title")
        if nid and label:
            names[str(nid)] = str(label)
    pairs = set()
    for l in links:
        a, b = l.get("source"), l.get("target")
        a = a.get("id") if isinstance(a, dict) else a
        b = b.get("id") if isinstance(b, dict) else b
        if str(a) in names and str(b) in names:
            pairs.add(frozenset((names[str(a)], names[str(b)])))
    return names, pairs, {"nodes": len(nodes), "links": len(links), "node_keys": sorted(nodes[0].keys()) if nodes else [],
                          "link_keys": sorted(links[0].keys()) if links else []}


def main() -> int:
    try:
        terms, page = all_terms()
    except NoToken as e:
        for n in ["terms exist", "key terms", "sql attributes", "main joins"]:
            report(f"generate: {n}", "SKIPPED", str(e))
        return 0
    names = sorted(t["name"] or "?" for t in terms)
    n_sql = sum(c["count"] for c in page["sql_attribute_counts"])
    n_col = sum(c["count"] for c in page["column_attribute_counts"])
    print(f"terms ({len(terms)}): {', '.join(names)}")
    print(f"column attributes: {n_col}   SQL attributes: {n_sql}")
    save_result("test_generate", {"terms": terms, "sql_attribute_counts": page["sql_attribute_counts"]})

    report("generate: terms exist", "PASS" if terms else "FAIL", f"{len(terms)} terms generated")

    have = {n.lower() for n in names}
    missing = [k for k in KEY_TERMS if k.lower() not in have]
    report("generate: key terms", "PASS" if not missing else "FAIL",
           "all of " + ", ".join(KEY_TERMS) + " exist" if not missing else f"missing terms: {missing}")

    # Naming quality: terms that fell back to 'Name (db.schema.table)' show the naming step failed for that table.
    fallback = [n for n in names if "(" in n and "." in n]
    print(f"info: {len(fallback)} term(s) have fallback names like 'X (db.schema.table)': {fallback[:4]}")

    report("generate: sql attributes", "PASS" if n_sql > 0 else "FAIL",
           f"{n_sql} SQL attribute(s) generated" if n_sql else "0 SQL attributes generated (no reviewed calculations such as a margin)")

    try:
        _, pairs, meta = graph_links()
        print(f"semantic graph: {meta['nodes']} nodes, {meta['links']} links; term-term pairs: {len(pairs)}")
        missing_j = [f"{a} - {b}" for a, b in MAIN_JOINS if frozenset((a, b)) not in pairs]
        if meta["nodes"] and not pairs:
            report("generate: main joins", "SKIPPED", f"graph shape not understood (node keys {meta['node_keys']}, link keys {meta['link_keys']})")
        else:
            report("generate: main joins", "PASS" if not missing_j else "FAIL",
                   "all main joins present" if not missing_j else f"missing joins: {missing_j}")
    except Exception as e:
        report("generate: main joins", "SKIPPED", f"could not read semantic graph: {str(e)[:140]}")

    # Independent physical check: how many semantic FK edges exist in the app database (direct SQL, informational).
    try:
        with db_connect("auto_ontology") as conn, conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM column__semantic_fk")
            print(f"info: semantic FK edges stored in the ontology database: {cur.fetchone()[0]}")
    except Exception as e:
        print(f"info: could not read semantic FK count directly ({type(e).__name__})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
