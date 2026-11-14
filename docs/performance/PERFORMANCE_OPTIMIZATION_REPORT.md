# BuildCore web — performance optimization report

Branch `perf/audit-and-optimization`, on top of 2.48.0 (`8bb7de7`). The problems found are in
[`PERFORMANCE_AUDIT.md`](PERFORMANCE_AUDIT.md). This report says what was changed, what it measured, and what is left.

## Action for you first: check the region (likely the biggest single cause)

`vercel.json` runs the server in **Dublin** (`dub1`). The setup guide and `.env.example` tell you to create the
database in **Mumbai** (`ap-south-1`). The region was changed by hand on 1 November (commit `35365c9`). The engine makes
**477 database round trips** to start a server copy and **10–76 per screen call**, so if the two regions differ, every one of those trips
crosses Europe↔India (~120 ms or more).

1. Supabase → your project → **Settings → General → Region**.
2. Set `regions` in `vercel.json` to the Vercel region in the same place:

| Supabase region | Vercel `regions` |
|---|---|
| South Asia (Mumbai) `ap-south-1` | `["bom1"]` |
| West EU (Ireland) `eu-west-1` | `["dub1"]` |
| Southeast Asia (Singapore) `ap-southeast-1` | `["sin1"]` |
| Central EU (Frankfurt) `eu-central-1` | `["fra1"]` |

If they already match, nothing to do. If they don't, this one line will matter more than everything else in this
report. It was **not changed** here because the database region cannot be seen from the code.

## What changed

| # | Change | Files | Survives a desktop sync? |
|---|---|---|---|
| 1 | 40 database indexes on line tables, document lists and sessions | `engine/web/webpatch.py` | Yes (web layer) |
| 2 | The calls every open browser polls (`team.tick`, `cm.unread`, `team.presence`, `team.feed`) no longer take the company write lock | `engine/web/webpatch.py` | Yes |
| 3 | Company-password hash for the ticket check kept 30 s per server copy (public calls only) | `engine/web/webpatch.py` | Yes |
| 4 | Every script, stylesheet and font gets a content version (`?v=hash`) and is cached by browsers for a year | `tools/web_build.py`, `vercel.json`, `public/index.html`, `public/app.css` | Yes (`sync_desktop.py` runs `web_build.py`) |
| 5 | Fonts as WOFF2 (same glyphs) with `font-display: swap`; TTF kept as fallback | `public/fonts/*.woff2`, `public/app.css` | Yes (made again by `web_build.py`, needs `pip install fonttools brotli`) |
| 6 | Money/quantity formatting reuses one formatter | `public/lib.js` | Yes (`WEB_TEXT` in `sync_desktop.py`) |
| 7 | List filter redraws once typing pauses | `public/pages_keys.js` | Yes (`WEB_TEXT`) |
| 8 | Copilot's "last screen" text read once when Copilot opens, not the whole page every 2 s | `public/pages_copilot.js` | Yes (`WEB_TEXT`) |
| 9 | `sync_desktop.py`: `WEB_TEXT` applied by a reusable `apply_web_text()`, line-ending safe, skips changes already made; runs `web_build.py` after a sync | `tools/sync_desktop.py` | — |
| 10 | Measuring tools: round trips, query plans, load test, company isolation test | `tools/perf/*.py`, `tests/company_isolation.py` | — |

No business rule, calculation, permission, URL or screen was changed. No data is changed. Indexes are additions.

### Modified source files

```
engine/web/webpatch.py          indexes, read-only polling, ticket cache
public/app.css                  @font-face: WOFF2 first, font-display: swap, versioned font URLs
public/index.html               ?v=<hash> on 61 scripts/stylesheets
public/lib.js                   fmtMoney / fmtQty reuse Intl.NumberFormat
public/pages_keys.js            list filter: debounce + flush on blur
public/pages_copilot.js         last-screen text captured on entering Copilot
public/fonts/BuildCoreSans.woff2, BuildCoreSans-Bold.woff2   (new)
vercel.json                     immutable cache for versioned assets
tools/web_build.py              (new) versions + WOFF2
tools/sync_desktop.py           new WEB_TEXT entries, apply_web_text(), runs web_build
tools/perf/db_trips.py, explain_hot.py, load_test.py          (new)
tests/company_isolation.py      (new)
docs/performance/*.md           (new) these reports
```

## Before and after (measured)

Measured on this computer: the real engine on a local PostgreSQL 16 (through `pgserver`), headless Google Chrome for the screens,
and synthetic data (10 projects, 20k BOQ items, 300k DPR work lines, 150k invoice lines, 200k IPC lines). The original code ran from a
worktree of `136ba2d` on its own copy of the same database.

### Database

| Lookup | Before | After |
|---|---:|---:|
| `dpr_work` by DPR (300k rows) | 35.6 ms, parallel seq scan | **0.04 ms**, index |
| `dpr_labour` by DPR (200k) | 13.2 ms, seq scan | **0.03 ms** |
| `ipc_lines` by IPC (200k) | 13.7 ms | **0.16 ms** |
| `invoice_lines` by invoice (150k) | 9.9 ms | **0.02 ms** |
| `grn_lines` by GRN (120k) | 7.9 ms | **0.02 ms** |
| `boq_items` by project (20k) | 1.4 ms | **0.41 ms** |

### Server round trips per call

| Call | Before | After |
|---|---:|---:|
| Server start (cold start) | 477 | 477 (indexes are checked from memory, no extra trips) |
| `team.tick` (every 15 s per browser) | 11 | **10**, and no company lock |
| `cm.unread` (every 60 s per browser) | 10 | **9**, and no company lock |
| `auth.me`, `lookups`, `dash.*`, `cash.summary` | 16 / 24 / 17 / 76 | unchanged |

### Browser

| What | Before | After |
|---|---:|---:|
| Scripts and styles re-checked on every visit | 61 requests | **0** (cached until they change) |
| Fonts downloaded on first visit | 1,433 KB TTF (717 KB gzip) | **484 KB** WOFF2 |
| Text while fonts load | may stay invisible up to 3 s | shown at once (`swap`) |
| Formatting 60,000 money/quantity figures | 1,400 ms | **40 ms** |
| Drawing a 6,000-row money table | ~2,080 ms | **~1,360 ms** |
| Typing "cement" into a 6,000-row list filter (page blocked) | 6.3 s, 12 long tasks | **0.8 s, 2 long tasks** |
| Whole-page text read for Copilot | every 2 s on every screen | once, when Copilot opens |

### Same results

* **Server:** 211 read functions × 2 argument sets = 422 calls, run on the old and the new code over identical copies of
  the database (with and without the new indexes). Identical output except a scan timestamp and the database name.
* **Formatting:** 600,033 values (edge cases, NaN/∞, strings, and random magnitudes from 10⁻⁴ to 10¹²) give exactly the same
  text from the old and new `fmtMoney`/`fmtQty`.
* **Filter:** the same rows as the original algorithm for six search terms on 6,000 rows.
* **Screens:** all 139 menu screens opened in Chrome on old and new code. No script errors and no server or database errors on either.
* **Companies:** `tests/company_isolation.py`: 8 of 8 checks pass (see `SECURITY_AND_RLS_AUDIT.md`).

Financial figures: no query, formula or posting was changed. The indexes change how rows are *found*, not which rows.

## What was not done, and why

| Brief item | Status | Reason |
|---|---|---|
| Route-level code splitting, lazy modules | Not done | Page files patch each other at load (`PAGES` wrappers in 20+ files), the menu is built from `PAGES`, and `table()` itself is replaced by `pages_keys.js`. Loading files on demand would silently drop wrappers. Long-lived caching (#4) removes the download cost on repeat visits instead. |
| React.memo / useMemo / context | Not applicable | No React in this codebase. |
| Server-side pagination, virtual scrolling | Not done | Needs the desktop list APIs and screens to change together. 13 screens read table rows back from the DOM, so rendering fewer rows would break them. |
| N+1 queries in `cash.summary`, `dash.summary` | Not done | Financial queries in desktop-owned files. Recommended fix in the audit (B4). |
| Fewer trips at server start (477) | Not done | Seed checks in desktop `init_db`. Recommended fix in the audit (A2). |
| Background jobs for exports/PDF | Partly existing | AI jobs already run as jobs. Exports are built in the browser (CSV) or by the engine in one request. |
| Cloudflare R2, thumbnails, resumable uploads | Planned, not done | A storage migration, not a speed fix. Plan in `API_PERFORMANCE_REPORT.md`. |
| Live-activity reload throttle | Withdrawn | Found not to happen in 2.48 (audit C5). |

## Remaining bottlenecks, in order

1. **Region** (above), if mismatched.
2. **One request at a time per server copy** (`core.LOCK`). One copy saturates at about **20–23 requests/second**
   locally. Capacity comes from Vercel running several copies, and each new copy is a cold start of 477 trips (≈0.5–1.5 s in
   the same region).
3. **Database connections.** Each server copy keeps up to `BCO_PG_IDLE` (2) idle connections plus the active one. The code
   notes Supabase's free plan allows 15 through the session pooler. With 25–50 people, 6+ copies can exhaust it; the engine then
   waits and retries ("The database is busy"). See hosting below.
4. **Fixed overhead of ~8 trips per call** (role templates, session read twice, workspace check). Fix in desktop (audit B3).
5. **Large lists render every row** (~1.3 s for 6,000 rows after this work). Paging needs desktop changes.
6. **2.5 MB of JavaScript parsed on each page load** (~150–300 ms on a mid-range phone). Caching removes the download, not the parse.

## Recommended production hosting

| Setting | Recommendation |
|---|---|
| Vercel region | Same as Supabase (see the table at the top). |
| Vercel function | Keep `maxDuration: 300`. Choose the larger memory/CPU size your plan offers (Project → Settings → Functions): the engine's start-up and screens are CPU-bound Python. |
| Vercel Fluid compute | **Test before relying on it.** The engine runs one request at a time per copy. If Fluid sends several requests to one copy, they queue (up to 25 s, then "BuildCore is busy"). Run `tools/perf/load_test.py` on a preview with it on and off, and keep the setting with the lower p95. |
| Supabase plan | **Pro** for 25–50 people at once: more connections in the pooler, no project pausing, daily backups. Raise the session pooler's pool size (Database → Settings → Connection pooling) to at least 3 × the number of server copies you see at peak. |
| `DATABASE_URL` | Session pooler (port 5432), as now. The transaction pooler is refused by design. |
| `BCO_PG_IDLE` | `1` if you see "database is busy" under load (fewer idle connections per copy). Keep `2` otherwise. |
| Files | Supabase Storage works today. For ~1 TB, Cloudflare R2 (no egress fees) is cheaper. See the plan in `API_PERFORMANCE_REPORT.md`. |
| Static files | Done in `vercel.json`: versioned assets immutable for a year. |

## How to deploy and check this branch

1. Push the branch (done). Vercel builds a **preview** deployment for it automatically. It uses the same database
   environment variables as production unless you set Preview-only ones, so point Preview at a **copy** of the database first
   if you want to load-test.
2. On the preview: sign in, open a few screens. In the browser's Network tab a second visit should show the scripts as
   "(disk cache)".
3. Optional, on staging: `python tools/perf/load_test.py --base <preview-url> ...`,
   `python tools/perf/explain_hot.py`, `python tests/company_isolation.py ...`.
4. Merge into `main` when satisfied. On the first start the new indexes are built (a few seconds on large tables, done
   once per company).
5. After the next desktop sync, check `sync_desktop.py`'s output for "text not found" notes. A note means the desktop changed
   that code and the speed change needs to be looked at again.
