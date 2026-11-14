"""EXPLAIN ANALYZE the lookups the web indexes are for, on real data. Read-only. Run it on a staging copy.

    set DATABASE_URL=postgresql://...
    python tools/perf/explain_hot.py [--schema buildcore]

For each query it picks a real id from your data and prints the plan's top node and the execution time (best of 3).
"Index Scan" / "Bitmap Heap Scan" means the index is used; "Seq Scan" on a large table means it is not.
"""
import argparse
import json
import os

import psycopg

QUERIES = [  # (table, column, the table its ids come from)
    ("dpr_work", "dpr_id", "dpr"), ("dpr_labour", "dpr_id", "dpr"), ("dpr_equipment", "dpr_id", "dpr"),
    ("ipc_lines", "ipc_id", "ipc"), ("invoice_lines", "invoice_id", "invoices"), ("grn_lines", "grn_id", "grn"),
    ("po_lines", "po_id", "po"), ("issue_lines", "issue_id", "issues"), ("boq_items", "project_id", "projects"),
    ("ipc", "project_id", "projects"), ("invoices", "project_id", "projects"), ("voucher_lines", "voucher_id", "vouchers"),
    ("voucher_lines", "account_id", "accounts"), ("stock_ledger", "project_id", "projects"),
]


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--schema", default="buildcore")
    a = p.parse_args()
    pg = psycopg.connect(os.environ["DATABASE_URL"], autocommit=True)
    pg.execute('SET search_path TO "%s", bcfn, public' % a.schema)
    pg.execute("SET default_transaction_read_only = on")
    out = {}
    for table, col, src in QUERIES:
        try:
            rows = pg.execute('SELECT count(*) FROM "%s"' % table).fetchone()[0]
            one = pg.execute('SELECT "%s" FROM "%s" WHERE "%s" IS NOT NULL ORDER BY random() LIMIT 1' % (col, table, col)).fetchone()
            if not one:
                out["%s.%s" % (table, col)] = {"rows": rows, "note": "no data"}
                continue
            best = None
            for _ in range(3):
                plan = pg.execute('EXPLAIN (ANALYZE, FORMAT JSON) SELECT * FROM "%s" WHERE "%s"=%%s' % (table, col),
                                  (str(one[0]),)).fetchone()[0][0]
                if best is None or plan["Execution Time"] < best["Execution Time"]:
                    best = plan
            out["%s.%s" % (table, col)] = {"rows": rows, "plan": best["Plan"]["Node Type"],
                                           "ms": round(best["Execution Time"], 3)}
        except psycopg.Error as e:
            out["%s.%s" % (table, col)] = {"error": str(e).splitlines()[0]}
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
