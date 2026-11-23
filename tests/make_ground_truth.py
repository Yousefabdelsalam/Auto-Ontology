"""Build tests/questions.json by querying the sample database DIRECTLY with SQL.

Nothing here goes through Auto Ontology and no LLM is involved. Expected values are
computed from the data at generation time; never edit them by hand to suit a result.

Definitions used for the ground truth (stated so a reader can disagree with them):
  * revenue  = SUM(sales.invoicelines.extendedprice)   (same definition as the repo README example)
  * state    = state of the CUSTOMER'S DELIVERY CITY    (same join path as the README example)
  * a month / year filters on sales.invoices.invoicedate
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal

from common import QUESTIONS, db_connect

# Shared FROM/JOIN fragment: invoice line -> invoice -> customer -> city -> state, plus stock item.
JOINS = """
FROM sales.invoicelines il
JOIN sales.invoices i          ON i.invoiceid = il.invoiceid
JOIN warehouse.stockitems si   ON si.stockitemid = il.stockitemid
JOIN sales.customers c         ON c.customerid = i.customerid
JOIN sales.customercategories cc ON cc.customercategoryid = c.customercategoryid
JOIN application.cities ct     ON ct.cityid = c.deliverycityid
JOIN application.stateprovinces sp ON sp.stateprovinceid = ct.stateprovinceid
"""


def q(select: str, where: str = "", tail: str = "") -> str:
    return f"SELECT {select} {JOINS} {where} {tail}".strip()


# kind: scalar -> one number; list -> ordered names (first column) with a value (second column)
ANSWERABLE = [
    dict(id="A1", question="What was the revenue for the 20 mm Double sided bubble wrap 50m in Texas in March 2015?",
         kind="scalar", tolerance={"abs": 0.01},
         sql=q("ROUND(SUM(il.extendedprice), 2)",
               "WHERE si.stockitemname = '20 mm Double sided bubble wrap 50m' AND sp.stateprovincename = 'Texas' "
               "AND i.invoicedate >= '2015-03-01' AND i.invoicedate < '2015-04-01'")),
    dict(id="A2", question="How many invoice lines were there on invoices dated in March 2016?",
         kind="scalar", tolerance={"abs": 0},
         sql=q("COUNT(*)", "WHERE i.invoicedate >= '2016-03-01' AND i.invoicedate < '2016-04-01'")),
    dict(id="A3", question="What was the total revenue from customers in the Gift Store category in 2015?",
         kind="scalar", tolerance={"abs": 0.01},
         sql=q("ROUND(SUM(il.extendedprice), 2)",
               "WHERE cc.customercategoryname = 'Gift Store' AND i.invoicedate >= '2015-01-01' AND i.invoicedate < '2016-01-01'")),
    dict(id="A4", question="Which are the top 3 stock items by total revenue across all time? List their names.",
         kind="list", tolerance={"rel": 0.001},
         sql=q("si.stockitemname, ROUND(SUM(il.extendedprice), 2) AS revenue", "",
               "GROUP BY si.stockitemname ORDER BY SUM(il.extendedprice) DESC LIMIT 3")),
    dict(id="A5", question="What was the average revenue per invoice line in 2015?",
         kind="scalar", tolerance={"rel": 0.001},
         sql=q("ROUND(AVG(il.extendedprice), 4)", "WHERE i.invoicedate >= '2015-01-01' AND i.invoicedate < '2016-01-01'")),
    dict(id="A6", question="How many distinct customers were invoiced in 2015?",
         kind="scalar", tolerance={"abs": 0},
         sql=q("COUNT(DISTINCT i.customerid)", "WHERE i.invoicedate >= '2015-01-01' AND i.invoicedate < '2016-01-01'")),
]

# Extra question used only by test_certify.py: gross margin % has no SQL attribute after compilation,
# so we compare the agent's answer before and after we define it precisely.
CERTIFY = dict(
    id="C1", question="What was the gross margin percentage across all invoice lines in 2015?",
    kind="scalar", tolerance={"abs": 0.05},
    definition="gross margin % = SUM(lineprofit) / SUM(extendedprice) * 100",
    sql=q("ROUND(SUM(il.lineprofit) / SUM(il.extendedprice) * 100, 4)",
          "WHERE i.invoicedate >= '2015-01-01' AND i.invoicedate < '2016-01-01'"))

UNANSWERABLE = [
    dict(id="U1", question="What was our total advertising spend in 2015?"),
    dict(id="U2", question="What is the average employee satisfaction score by department?"),
    dict(id="U3", question="What will the weather be like next year in the cities where our customers are located?"),
]

# Ambiguous: no metric given. 'interpretations' are real SQL results for the plausible readings;
# the script checks that they disagree, otherwise the question is not truly ambiguous.
AMBIGUOUS = [
    dict(id="B1", question="Who is our best customer?",
         interpretations={
             "by revenue": "SELECT c.customername FROM sales.invoicelines il JOIN sales.invoices i ON i.invoiceid=il.invoiceid "
                           "JOIN sales.customers c ON c.customerid=i.customerid GROUP BY c.customername ORDER BY SUM(il.extendedprice) DESC LIMIT 1",
             "by profit": "SELECT c.customername FROM sales.invoicelines il JOIN sales.invoices i ON i.invoiceid=il.invoiceid "
                          "JOIN sales.customers c ON c.customerid=i.customerid GROUP BY c.customername ORDER BY SUM(il.lineprofit) DESC LIMIT 1",
             "by number of invoices": "SELECT c.customername FROM sales.invoices i JOIN sales.customers c ON c.customerid=i.customerid "
                                      "GROUP BY c.customername ORDER BY COUNT(*) DESC, c.customername LIMIT 1",
         }),
    dict(id="B2", question="Which product is the most popular?",
         interpretations={
             "by revenue": "SELECT si.stockitemname FROM sales.invoicelines il JOIN warehouse.stockitems si ON si.stockitemid=il.stockitemid "
                           "GROUP BY si.stockitemname ORDER BY SUM(il.extendedprice) DESC LIMIT 1",
             "by units sold": "SELECT si.stockitemname FROM sales.invoicelines il JOIN warehouse.stockitems si ON si.stockitemid=il.stockitemid "
                              "GROUP BY si.stockitemname ORDER BY SUM(il.quantity) DESC LIMIT 1",
             "by number of invoice lines": "SELECT si.stockitemname FROM sales.invoicelines il JOIN warehouse.stockitems si ON si.stockitemid=il.stockitemid "
                                           "GROUP BY si.stockitemname ORDER BY COUNT(*) DESC, si.stockitemname LIMIT 1",
         }),
]


def num(x):
    """Decimal -> float for JSON (values are rounded in SQL, so this is exact enough)."""
    return float(x) if isinstance(x, Decimal) else x


def run(cur, item: dict) -> dict:
    cur.execute(item["sql"])
    rows = cur.fetchall()
    out = {k: v for k, v in item.items()}
    if item["kind"] == "scalar":
        assert len(rows) == 1 and rows[0][0] is not None, f"{item['id']}: expected one non-null value, got {rows}"
        out["expected"] = num(rows[0][0])
    else:
        out["expected"] = [{"name": r[0], "value": num(r[1])} for r in rows]
    return out


def main() -> int:
    with db_connect() as conn, conn.cursor() as cur:
        answerable = [run(cur, it) for it in ANSWERABLE]
        certify = run(cur, CERTIFY)

        ambiguous, problems = [], []
        for it in AMBIGUOUS:
            results = {}
            for name, sql in it["interpretations"].items():
                cur.execute(sql)
                results[name] = cur.fetchone()[0]
            if len(set(results.values())) < 2:
                problems.append(f"{it['id']}: all interpretations give the same answer {results}; not truly ambiguous")
            ambiguous.append({**it, "interpretations": [{"reading": k, "sql": it["interpretations"][k], "result": v} for k, v in results.items()]})

        cur.execute("SELECT (SELECT COUNT(*) FROM sales.invoices), (SELECT COUNT(*) FROM sales.invoicelines)")
        invoices, lines = cur.fetchone()

    doc = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "database": "wideworldimporters (sample data, direct SQL)",
        "fingerprint": {"invoices": invoices, "invoicelines": lines},
        "definitions": {"revenue": "SUM(sales.invoicelines.extendedprice)",
                        "state": "state of the customer's delivery city",
                        "date_filter": "sales.invoices.invoicedate"},
        "answerable": answerable,
        "certify": certify,
        "unanswerable": [{**it, "expected_behavior": "say it cannot answer or ask for clarification; no invented number"} for it in UNANSWERABLE],
        "ambiguous": [{**it, "expected_behavior": "ask which metric is meant (answering with an explicitly stated assumption is reported separately)"} for it in ambiguous],
    }
    QUESTIONS.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"wrote {QUESTIONS}")
    for it in answerable + [certify]:
        print(f"  {it['id']}  {it['expected']}   <- {it['question']}")
    for it in ambiguous:
        print(f"  {it['id']}  " + "; ".join(f"{r['reading']}: {r['result']}" for r in it["interpretations"]))
    for p in problems:
        print("PROBLEM:", p)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
