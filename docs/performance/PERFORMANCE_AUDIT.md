# BuildCore web — performance audit

Audit of BuildCore web 2.48.0 (commit `8bb7de7`), November 2026. Every finding below was checked in the code,
and where a number is given it was measured. Nothing was assumed from the brief.

## How the measurements were taken

There is no Supabase connection or production data in this audit environment. To avoid guessing, the real engine
was started on a **local PostgreSQL 16** (the `pgserver` package) with the repository's own start-up code
(`engine/web/boot.py`), and every round trip to the database was counted by wrapping psycopg's cursor. Synthetic data
(10 projects, 20,000 BOQ items, 300,000 DPR work lines, 150,000 invoice lines, 200,000 IPC lines) was used for query
plans. The harnesses are committed under `tools/perf/` so the same numbers can be taken against a Supabase staging
copy.

**Round trips are the unit that matters here.** On a local database a trip costs ~0.1 ms. Between Vercel and Supabase
in the same region it costs about 1–3 ms. Between two regions it costs 100–250 ms. The engine was written for a SQLite file on the same
computer, so it asks many small questions. Its speed on the web depends almost entirely on the number of trips
multiplied by the distance to the database.

### Baseline (before any change)

| What | Database round trips | Local time |
|---|---:|---:|
| Server start (cold start of each Vercel copy), database already set up | **477** | 0.47 s |
| `auth.login` | 20 | 80 ms |
| `auth.me` | 16 | 15 ms |
| `lookups` | 24 | 24 ms |
| `dash.approvals` | 17 | 28 ms |
| `team.tick` (every 15 s per signed-in browser) | 11 | 9 ms |
| `cm.unread` (every 60 s per signed-in browser) | 10 | 11 ms |
| `dash.summary` | 41 | 30 ms |
| `cash.summary` (Command centre) | 76 | 32 ms |

These counts are for an **empty** company. They grow with the data: the 2.47 commit measured 37,574 → 1,218 trips
for the company overview on real data.

Fixed overhead per request: **~8 of the trips** come before the function does any work. These are reading role templates, looking up the
session and user twice (two different connections), reading `session_days` twice, the workspace check, `BEGIN`,
the company lock, and `COMMIT`. `team.tick` does 2 queries of real work out of 11.

| Static assets on first visit | Size |
|---|---:|
| Scripts + stylesheet loaded at start-up | 61 files, 2,474 KB raw / 705 KB gzip |
| Fonts (DejaVu TTF ×2) | 1,434 KB raw / 717 KB gzip |
| Repeat visit | 61 conditional requests (all `max-age=0, must-revalidate`) |

| Query on synthetic volume (best of 5) | Plan | Time |
|---|---|---:|
| `dpr_work WHERE dpr_id=?` (300k rows) | Parallel Seq Scan | 35.6 ms |
| `dpr_labour WHERE dpr_id=?` (200k) | Seq Scan | 13.2 ms |
| `ipc_lines WHERE ipc_id=?` (200k) | Seq Scan | 13.7 ms |
| `invoice_lines WHERE invoice_id=?` (150k) | Seq Scan | 9.9 ms |
| `grn_lines WHERE grn_id=?` (120k) | Seq Scan | 7.9 ms |
| `boq_items WHERE project_id=?` (20k) | Seq Scan | 1.4 ms |

---

## Architecture (what was found)

| Area | Finding |
|---|---|
| Frontend | Not React. 61 hand-written vanilla JS files (`public/`), loaded as classic `<script>` tags. Pages are entries in a global `PAGES` map; **later files wrap earlier files' pages** (`PAGES.command` is wrapped in `pages_project.js`, `pages_cash.js`, `pages_fcc.js`…), and the menu shows a link only if `PAGES[path]` exists. Hash routing (`#/path`), one `go()` per navigation. |
| Backend | One Vercel Python function (`api/index.py`) runs the **desktop engine unchanged**. `engine/web/pgsqlite.py` stands in for `sqlite3` and translates every statement to PostgreSQL. |
| Database | Supabase PostgreSQL. **One schema per company** (`buildcore`, `buildcore_<code>`), ~270 tables each. No `company_id` columns; isolation is by schema. |
| Concurrency | `core.LOCK` (process-wide `RLock`) runs one request at a time per Vercel copy, because the engine switches its global "current company" per request. Writes take a per-company PostgreSQL advisory lock. More users means more Vercel copies, and **every new copy is a cold start**. |
| Files | Supabase Storage (private bucket), signed URLs, uploads >4 MB go browser → Storage directly. **Cloudflare R2 is not used.** |
| Ownership | `tools/sync_desktop.py` **deletes and recopies** `public/` (except `web.js`) and `engine/` (except `engine/web/`) on each desktop version. A change made directly in a desktop file is lost on the next sync unless it is registered as a `WEB_TEXT` patch in that tool. |

Phase 2-B of the brief (React.memo, useMemo, useCallback, context providers) does not apply. There is no React.

---

## Findings

Severity: **P0** = dominant cause, fix first · **P1** = large · **P2** = moderate · **P3** = small / hygiene.
"Owner" says where a durable fix must live: **web** = web layer (survives syncs), **web-patch** = desktop file
patched through `sync_desktop.py`'s `WEB_TEXT`, **desktop** = must be fixed in the desktop source.

### A. Infrastructure

#### A1 — Function region may not match the database region · P0 · owner: config
- **Where:** `vercel.json` → `"regions": ["dub1"]` (Dublin). `README.md`, `docs/DEPLOY.md:55` and `.env.example`
  (`aws-0-ap-south-1`) all tell the user to create the database in **Mumbai**. The region was changed from `bom1` to
  `dub1` in commit `35365c9`.
- **Root cause:** If the Supabase project is in Mumbai, every one of the round trips above crosses Europe↔India (~120 ms+).
- **Impact:** A cold start would be 477 × ~120 ms ≈ **57 s**, `cash.summary` ≈ 9 s, and each `team.tick` ≈ 1.3 s. That matches
  every symptom in the brief (slow loading, dashboard delays, "freezing").
- **Correction:** Set `regions` to the Vercel region nearest the Supabase project (Supabase → Settings → General →
  Region; `ap-south-1` → `bom1`, `eu-west-1` → `dub1`, `ap-southeast-1` → `sin1`). **Not changed in this work** because the
  database region cannot be seen from the repository. See `PERFORMANCE_OPTIMIZATION_REPORT.md` → "Action for you".
- **Expected:** If they are mismatched today, this one setting reduces every server time by roughly 30–100×.

#### A2 — Cold starts repeat 477 database trips · P1 · owner: desktop (web can mitigate)
- **Where:** `engine/web/boot.py:start()` → `core.init_db()`.
- **Root cause:** Each Vercel copy runs the engine's start-up, which checks seed rows one at a time. Examples: 42× `SELECT key
  FROM settings WHERE key=?`, 49× `INSERT INTO settings … ON CONFLICT DO NOTHING`, 28× `tl_groups`, 42× `tl_vtypes`,
  33× `fcc_*`, 13× `ws_roles`.
- **Impact:** Because of `core.LOCK`, a copy serves one request at a time. When 25 users click at once, Vercel starts new
  copies, and each one pays this before its first answer.
- **Correction:** (desktop) Read each seed table once with `SELECT key FROM settings`, then insert only the
  missing rows. (web) Keep copies warm. Vercel Fluid compute reuses instances, but see A3.
- **Expected:** ~477 → ~60 trips per cold start, if fixed at the source.

#### A3 — One request at a time per server copy · P2 · owner: desktop architecture
- **Where:** `engine/server.py:call` (`with LOCK`), `engine/api_corp.py:_patch_server` (`core.LOCK.acquire(timeout=25)`).
- **Root cause:** The engine keeps the current company in module globals (`core.DB_PATH`, `api_corp.CUR`).
- **Impact:** Requests to the same copy queue up. If Vercel routes several concurrent requests into one copy (Fluid
  compute), they wait up to 25 s and then get "BuildCore is busy". The `_GATE` semaphore (3) in `webpatch.py` never
  matters because the lock admits only 1.
- **Correction:** Long term, make the company per-request (thread-local) in the engine. Short term, keep one request per
  copy (the Vercel default for Python without Fluid). Watch for "busy" errors in the Vercel logs.

### B. Server and database

#### B1 — Missing indexes on the line tables and project lists · P1 · owner: web
- **Where:** Indexes come from the engine's own `CREATE INDEX` statements (`schema.sql` has 83 for ~270 tables) plus 4 added
  by `webpatch._INDEXES`.
- **Root cause:** Most header→line columns have no index. Examples: `dpr_work/dpr_labour/dpr_equipment/dpr_delays.dpr_id`,
  `ipc_lines.ipc_id`, `invoice_lines.invoice_id`, `grn_lines.grn_id`, `po_lines.po_id`, `issue_lines.issue_id`,
  `boq_items.project_id` (used by 47 query sites), `ipc.project_id`, `invoices.project_id/party_id`,
  `sessions.user_id`. SQLite on a local disk scanned these quickly enough. PostgreSQL does not index foreign-key columns
  by itself (and the translator drops the foreign keys).
- **Impact:** Each lookup is a sequential scan, 8–36 ms each on 120k–300k rows (table above), and it grows
  linearly with the years of data. Opening one DPR touches four of these tables. Postings touch several.
- **Correction:** Add the indexes in `webpatch._INDEXES` (`CREATE INDEX IF NOT EXISTS`, no data change). They are created
  for every company schema at start-up.
- **Expected:** Index scans of well under 1 ms. Measured results are in `DATABASE_OPTIMIZATION_REPORT.md`.

#### B2 — Polling calls take the company-wide write lock · P1 · owner: web
- **Where:** `engine/web/webpatch.py:_READS`. `team.tick` (every 15 s per browser), `cm.unread` (every 60 s),
  `team.presence` and `team.feed` don't match the read-only list.
- **Root cause:** `server.call` always runs `BEGIN IMMEDIATE`, and the web layer takes the company advisory lock at
  `BEGIN` unless the function name looks read-only.
- **Impact:** With 30 users, about 2 lock acquisitions per second come from polling alone. Every save in that company
  queues behind them (and they queue behind every save).
- **Correction:** Add `tick|unread|presence|feed` to `_READS`. Verified that all four only read. If one ever writes, the
  existing lazy-lock design still takes the lock at the first write.
- **Expected:** Polls no longer contend with real work. One fewer round trip each.

#### B3 — Fixed overhead of ~8 trips per request · P2 · owner: web (partly) / desktop
- **Where:** `webpatch._wrap_call` reads `ws_roles` on its own connection for every request.
  `api_workspace._guard._precheck` and `server.call` each open a connection and each run `user_from_token`
  (sessions⋈users + `settings.session_days`). For *public* calls only (the sign-in screens, licence status), the HTTP
  path also checks the company ticket. It reads the company password hash from `web_kv` in the main company's schema,
  and for other companies that switches the pooled connection's `search_path` back and forth. *(Corrected after
  testing: an earlier draft said this happens on every request. `_wrap_call` checks it only when `entry[3]`, the
  public flag, is set.)*
- **Correction (done):** Cache the company-password hash for 30 s per server copy, and clear it at once when the password
  changes or on restore in that copy. This only affects the sign-in screens. **(Recommended, desktop):** Pass the
  connection and user from the workspace check into `call` so that sessions/users/settings are read once (−2 trips on
  *every* request).
- **Expected:** −1 to −3 trips on public calls. The desktop change would save −2 on every call.

#### B4 — N+1 queries in financial summaries · P2 · owner: desktop
- **Where:** `cash.summary` runs 25× `SUM(debit-credit) … WHERE l.account_id=?` (one per bank or cash account) and
  24× `SUM(amount) FROM oh_budget WHERE fy=? AND month=?` (one per month). `dash.summary` runs similar per-account sums.
- **Correction:** One grouped query each (`GROUP BY account_id`, `GROUP BY month`).
  **Not changed here**, because these are financial calculations in desktop-owned files. A translator-level rewrite
  (like the existing BOQ prefetch) was considered and rejected: it changes how ledger totals are computed, and the brief
  requires numerically identical results, which can only be proven with the desktop test kits on real data.
- **Expected:** `cash.summary` 76 → ~30 trips.

#### B5 — No statement timeout · P3 · owner: web
- A runaway report can hold the company advisory lock until the Vercel limit (`maxDuration: 300`). This was not changed:
  restore, backup and AI jobs legitimately run long. Recommendation: set `statement_timeout` per role for interactive traffic
  only, after the timeouts are measured on staging.

### C. Frontend

#### C1 — Static assets are revalidated on every visit · P1 · owner: web
- **Where:** `vercel.json` sets `Cache-Control: public, max-age=0, must-revalidate` for every `.js/.css`.
  `index.html` references them without a version.
- **Impact:** 61 conditional requests before the first screen on every visit. On a mobile connection with ~100 ms RTT,
  that is ~1–2 s spent only asking "has it changed?" (HTTP/2 multiplexing helps, but the scripts are parser-blocking).
- **Correction:** `tools/web_build.py` stamps each `<script>`/`<link>` with `?v=<content hash>`. `vercel.json` makes
  versioned URLs `immutable` for a year and keeps unversioned URLs on `must-revalidate`. `sync_desktop.py` runs the
  build after each sync.
- **Expected:** Repeat visits: 61 → 0 network requests for scripts and styles. Only changed files download after a deploy.

#### C2 — 1.4 MB of TTF fonts, no `font-display` · P1 · owner: web-patch
- **Where:** `public/app.css:1-2` loads `BuildCoreSans.ttf` and `BuildCoreSans-Bold.ttf` (DejaVu Sans, full glyph set).
- **Impact:** 717 KB gzip on the first visit. With the browser's default `font-display: auto`, text can stay invisible
  for up to 3 s while they download.
- **Correction:** Make WOFF2 copies (same glyphs, lossless) and list them first in `@font-face` with
  `font-display: swap`, keeping the TTF as a fallback.
- **Expected:** ~1,434 KB → ~700 KB on the wire for fonts (measured in the optimization report). No invisible text.

#### C3 — A whole-page `innerText` read every 2 seconds, on every screen · P1 · owner: web-patch
- **Where:** `public/pages_copilot.js:271-278`. A global `setInterval(…, 2000)` stores
  `#page.innerText.slice(0, 15000)` so that Copilot can use "what is on my last screen".
- **Root cause:** `innerText` forces a synchronous layout and serializes the **entire** page before it is sliced.
- **Impact:** On a ledger, BOQ or stock screen with thousands of rows, the main thread stalls every 2 s for the whole
  session, whether or not Copilot is ever opened. This is a direct cause of "lag" and "freezing during long sessions".
- **Correction:** Capture the text once, when the user navigates *to* Copilot (in a `hashchange` listener that runs before
  the router clears the page). The result is the same, without the polling.
- **Expected:** One capture per Copilot visit instead of 1,800 per hour.

#### C4 — Number formatting builds a new formatter for every figure · P1 · owner: web-patch
- **Where:** `public/lib.js:83-84`: `fmtMoney` / `fmtQty` call `Number(n).toLocaleString("en-IN", {…})`. These have 461 call
  sites and run in every money/quantity column of every table and total.
- **Root cause:** `toLocaleString` with options creates a new `Intl.NumberFormat` on each call.
- **Impact (measured, Chrome):** 60,000 figures take 1,400 ms. A CPU profile of typing in a 6,000-row list put `fmtQty` at the
  top of the JavaScript time.
- **Correction:** One `Intl.NumberFormat` per format, reused. ECMA-402 defines `toLocaleString(locale, options)` as
  `new Intl.NumberFormat(locale, options).format(x)`, so the text is the same. Verified identical on 600,033 values.
- **Expected:** 1,400 → 40 ms per 60,000 figures.

#### C4b — List filter redraws all rows on every key press · P1 · owner: web-patch
- **Where:** `public/pages_keys.js:288`. `pages_keys.js:416` replaces the global `table()` with its keyboard list `klist`,
  so this is the filter box people actually type into. *(An earlier draft of this audit pointed at the filter inside
  `lib.js`'s `table()`. A CPU profile showed that function is replaced at load, so it never runs.)*
- **Root cause:** `oninput` → `K.render()` rebuilds every visible row on each key, with no debounce.
- **Impact (measured):** Typing "cement" in a 6,000-row list blocked the page for **6.3 s** (12 long tasks).
- **Correction:** Redraw once typing pauses (150 ms), and at once when the box is left. List keys act only when focus is
  outside text fields (`pages_keys.js:903`), so the next key or click always sees the filtered rows.
- **Expected:** Measured with C4: **6.3 s → 0.8 s** of blocked page, same rows shown.

#### C5 — Live reload of the Command centre · not an issue in 2.48 (withdrawn)
- The code suggests that `liveTick` (`pages_team.js:262`) re-renders the Command centre whenever anyone saves. **At run time
  it does not:** `wrapPages()` (`pages_workspace.js:248-276`) replaces every page with a wrapper that does not copy the
  page's properties, so `PAGES.command.live` (and `PAGES["p/live"].live`) are gone. Checked in Chrome on both the original
  and the new code. A throttle written for this was removed again, since it would have been dead code.
- **Side effect to report to the desktop side (functional, not speed):** the *Live activity* screen no longer refreshes
  by itself either. If the desktop restores `.live`, revisit this: the Command centre is the heaviest screen.

#### C6 — 2.5 MB of JavaScript parsed at start-up; no lazy loading · P2 · owner: desktop
- Every page module is loaded at start. **Route-level code splitting is not safe** in this codebase as it stands:
  files patch each other's pages at load time (C-architecture above), the menu is built from `PAGES`, and 13
  places read table rows back from the DOM. Lazy loading would silently drop wrappers (e.g. the Command centre's tabs).
- **Correction now:** Long-lived caching (C1) removes the download cost on repeat visits. Parse cost stays (~150–300 ms on a
  mid-range phone).
- **Recommended (desktop):** Give each page module an explicit dependency on the pages it wraps, then load groups on
  first navigation.

#### C7 — Tables render every row · P2 · owner: desktop
- `table()` puts all rows in the DOM, and many list functions return all rows (no `LIMIT`/paging in the engine's list APIs).
  Server-side paging needs the desktop API and screens to change together. Not changed here (see C4 for the safe part).

#### C8 — Global pollers · P3
- `pages_ai.js:416` (800 ms), `pages_contract.js:497` (1.2 s), `pages_field.js:444` (1 s), `pages_adv.js:792` (700 ms) only
  check the DOM and are cheap. The bell (`pages_contract.js:505`, `cm.unread` every 60 s) and `team.tick` (15 s, skipped in
  hidden tabs) are the only network pollers. About 2.1 requests per minute per signed-in browser at rest.
- `pages_team.js:271` adds a new `visibilitychange` listener each time `startLive()` runs (once per sign-in, so
  harmless in practice).

### D. Files

#### D1 — No Cloudflare R2; no thumbnails · P2 · owner: web
- Files are in Supabase Storage. Downloads are 300 s signed redirects (good). Large uploads go browser → Storage
  directly (good). Images are always served at full resolution, and there is no thumbnail generation, no type or size check
  on `web.upload_url`, and no resumable upload.
- A move to R2 for ~1 TB is reasonable on cost (no egress fees). It is a migration rather than an optimization, so it is
  planned in `API_PERFORMANCE_REPORT.md` → "Files" and not done here.

### E. Security (details in `SECURITY_AND_RLS_AUDIT.md`)
- Company isolation is by schema plus a signed company ticket. Supabase's data API is revoked for
  `anon`/`authenticated` on company schemas. A session token from company A cannot be used against company B
  (sessions live in each schema).
- `/files/<id>` checks only that the user is signed in to the company, not their project access (P2, a permission-model change
  that needs your approval).

---

## What is fixed in this work, and what is not

| ID | Fixed here | Notes |
|---|---|---|
| A1 | No (needs your input) | Check the Supabase region and set `vercel.json` to match. |
| A2, A3, B4, C6, C7 | No | Desktop-owned code or architecture. Recommendations above. |
| B1 | Yes | `engine/web/webpatch.py` |
| B2 | Yes | `engine/web/webpatch.py` |
| B3 | Partly | `engine/web/webpatch.py` |
| C1 | Yes | `tools/web_build.py`, `vercel.json`, `tools/sync_desktop.py` |
| C2 | Yes | `tools/web_build.py` (WOFF2 + `font-display`) |
| C3, C4, C4b | Yes | `public/pages_copilot.js`, `public/lib.js`, `public/pages_keys.js`, registered in `sync_desktop.py` so they survive syncs |
| C5 | Withdrawn | Not reproducible in 2.48 (see above) |
