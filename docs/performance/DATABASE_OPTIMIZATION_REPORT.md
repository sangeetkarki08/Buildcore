# BuildCore web — database optimization report

## The database as it is

* Supabase PostgreSQL. **One schema per company** (`buildcore`, `buildcore_<code>`), about 270 tables each, plus `bcfn`
  (SQLite-compatible helper functions).
* The engine's SQL is SQLite. `engine/web/pgsqlite.py` translates each statement. Values are bound as untyped literals
  (`'5'`), so `numeric` id columns compare with them and **can use indexes** (checked with `EXPLAIN`).
* Id columns are `numeric`, dates are `text` (ISO strings), as in the desktop data file. Changing types would break the
  two-way desktop ⇄ web data transfer, so they were left as they are.
* Foreign keys are not created (SQLite ran with `foreign_keys=OFF`, and the translator drops them). Integrity is kept by
  the engine, as on desktop.
* No `company_id` columns: a company is a schema, so every query is already limited to one company.
* Transactions: every request is one transaction. Writes take a per-company advisory lock
  (`pg_advisory_xact_lock(crc32('bco:'+schema))`), the desktop's single writer. Read-only calls (a name list in
  `webpatch._READS`) take it only if they write.

## Indexes

### Found

`schema.sql` has 83 indexes for ~270 tables, and `webpatch` added 4 on `voucher_lines` / `vouchers`. The engine's
queries filter on many columns that have none. The worst were the line tables read by their document, and the
document lists read by project. Every column in the list below was checked against the engine's own queries:
query sites found by search, for example `boq_items.project_id` in 47 places and `dpr.project_id`, `dpr_equipment.dpr_id` in 27.

### Added (`engine/web/webpatch.py`, `_INDEXES`)

Created with `CREATE INDEX IF NOT EXISTS ix_web_<table>_<column>` in **every company schema** at start-up (and for
each company on its first request in a server copy). If a table or column doesn't exist in an older company, that
index is skipped. No data is changed.

| Group | Indexes |
|---|---|
| DPR | `dpr_work(dpr_id)`, `dpr_work(boq_item_id)`, `dpr_labour(dpr_id)`, `dpr_equipment(dpr_id)`, `dpr_delays(dpr_id)` |
| Billing | `ipc(project_id)`, `ipc_lines(ipc_id)`, `ipc_lines(boq_item_id)`, `measurements(project_id)`, `measurement_lines(measurement_id)` |
| BOQ | `boq_items(project_id)`, `boq_components(project_id)` |
| Purchases & sales | `invoices(project_id)`, `invoices(party_id)`, `invoice_lines(invoice_id)`, `payments(project_id)`, `payments(party_id)` |
| Procurement | `pr(project_id)`, `pr_lines(pr_id)`, `po(project_id)`, `po_lines(po_id)`, `po_revisions(po_id)`, `mrq(project_id)`, `mrq_lines(mrq_id)` |
| Stores | `grn(project_id)`, `grn_lines(grn_id)`, `issues(project_id)`, `issue_lines(issue_id)`, `return_lines(return_id)`, `transfer_lines(transfer_id)`, `count_lines(count_id)` |
| Subcontract, plant, documents | `sc_order_items(order_id)`, `sc_bill_items(bill_id)`, `mix_lines(mix_id)`, `plant_run_lines(run_id)`, `fld_meeting_items(meeting_id)`, `dm_trans_items(transmittal_id)` |
| Provisions | `provisions(project_id)`, `prov_moves(provision_id)` |
| Sign-in | `sessions(user_id)` |

40 in all. Single-column on purpose: the engine's lookups are by one id. Composite indexes were not added, because
no query pattern was found that needs one beyond those the engine already makes (`stock_ledger(project_id,
material_id, store_id, date)`, `dpr(project_id, date, shift)` unique, …).

Not added, though the brief named them: `company_id` (no such column, schemas instead); `voucher_number`,
`invoice_number` (lookups by number are rare, and `vouchers(date)`, `(source, source_id)` exist); `status`
(low-selectivity, and already in the composite indexes where it matters); `created_at` (`activity` has
`ix_activity_ts`).

### Measured (EXPLAIN ANALYZE, best of 5, synthetic volume)

| Query | Rows in table | Before | After |
|---|---:|---|---|
| `SELECT * FROM dpr_work WHERE dpr_id=?` | 300,000 | Gather / parallel seq scan, 35.6 ms | Bitmap index scan, **0.037 ms** |
| `SELECT * FROM dpr_labour WHERE dpr_id=?` | 200,000 | Seq scan, 13.2 ms | **0.027 ms** |
| `SELECT * FROM ipc_lines WHERE ipc_id=?` | 200,000 | Seq scan, 13.7 ms | **0.159 ms** |
| `SELECT * FROM invoice_lines WHERE invoice_id=?` | 150,000 | Seq scan, 9.9 ms | **0.019 ms** |
| `SELECT * FROM grn_lines WHERE grn_id=?` | 120,000 | Seq scan, 7.9 ms | **0.022 ms** |
| `SELECT id FROM boq_items WHERE project_id=?` | 20,000 | Seq scan, 1.4 ms | **0.409 ms** |

On Supabase's shared CPU the "before" times are larger, and they grow with every year of data. The engine runs these per
document and per BOQ item, so one screen can run them dozens of times.

**To check on your own data:** `python tools/perf/explain_hot.py` (read-only) prints the plan and time of each lookup
with real ids. Index use over time: Supabase → Database → Query performance, or
`SELECT relname, indexrelname, idx_scan FROM pg_stat_user_indexes WHERE indexrelname LIKE 'ix_web_%' ORDER BY idx_scan;`.
An index still at `idx_scan = 0` after a few weeks of normal use can be dropped.

### Cost

Each index makes inserts into its table slightly slower. On construction-ERP volumes (hundreds to a few thousand lines a
day per company) that is negligible next to the reads it saves. The first start after deploying builds them. Building is
quick on small tables. On the largest table of a company it takes a few seconds, during which writes to that table wait.

## Results are unchanged

Indexes change how rows are found, not which rows. To make sure that holds through the translator as well, 211 read
functions were called (422 calls) on two copies of the same database, one with the original code and no new indexes, one with
the new code and the indexes. The outputs were identical except for a "last scan" timestamp and the database name.

One property worth knowing, unchanged by this work: SQL without `ORDER BY` has no guaranteed row order in
PostgreSQL, and a plan can change as tables grow, with or without these indexes. The engine's screens and reports order
what they show.

## Query patterns found (not changed: desktop-owned)

| Pattern | Where | Trips | Fix at the source |
|---|---|---:|---|
| Balance per account, one query each | `cash.summary`, `dash.summary` (`SUM(debit-credit) … WHERE account_id=?`) | 25 + 9 | one `GROUP BY account_id` |
| Budget per month, one query each | `cash.summary` (`oh_budget WHERE fy=? AND month=?`) | 24 | one `GROUP BY month` |
| Seed checks one key at a time | `core.init_db` at every server start | ~400 of 477 | read each seed table once, insert the missing rows |
| Session and user read twice per request | `api_workspace._guard` and `server.call` on separate connections | 2–3 per call | pass the connection through |

The web layer already absorbs the BOQ item-by-item pattern (2.47: `pgsqlite._prefetch`). Extending that trick to ledger
sums was considered and rejected: it would change how financial totals are computed, and proving identical figures needs
the desktop test kits on real data.

## Connection pooling and transactions

* `DATABASE_URL` must be the **session** pooler (5432). The transaction pooler (6543) is refused, because each request
  relies on `search_path` and an advisory lock on one connection. That is correct and was kept.
* Each server copy keeps `BCO_PG_IDLE` (default 2) idle connections for 60 s. On "too many clients" it drops its idle
  connections and retries with back-off (up to ~10 tries) before telling the user the database is busy.
* Financial posting runs in one transaction under the company lock, with a savepoint per statement (a failed statement
  is rolled back alone, as in SQLite). Nothing about this was changed.

## Caching

* **Kept (existing):** per-request memo of identical `SELECT`s (cleared on any write), table catalogue in memory, BOQ
  prefetch, licence status (30 s), the dashboard's daily snapshot at most hourly.
* **Added:** the company-password hash for ticket checks, 30 s per server copy (sign-in screens only).
* **Not added:** caching of balances, dashboards or reports across requests. Several server copies run at once and
  there is no shared invalidation signal, so a cached balance could be stale after another person's posting. The brief
  rules that out for financial figures. Dashboards stay computed per request.

## Row-level security

Not used, and not needed for isolation in this design. Companies are separate schemas, and BuildCore connects with the database's own credentials,
never through Supabase's public data API (whose roles have no rights on the company schemas). See
`SECURITY_AND_RLS_AUDIT.md`.
