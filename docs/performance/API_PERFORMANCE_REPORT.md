# BuildCore web — API performance report

## How a request travels

```
browser ── POST /api {fn, args} ──► Vercel (rewrite) ──► api/index.py (one Python function)
   │                                                        │
   │                                       api_corp handler: core.LOCK (one request per copy),
   │                                       switch to the company named by X-Company / cookie
   │                                                        │
   │                                       webpatch._wrap_call: company ticket (public calls),
   │                                       read-only? → no company lock until a write;
   │                                       read role templates
   │                                                        │
   │                                       api_workspace guard → licence guard → server.call:
   │                                       session → permission → BEGIN → function → COMMIT
   ◄──────────────── {ok, data} JSON ───────────────────────┘
```

There is one endpoint (`/api`) with a function name, about 1,040 functions in all, plus `/api/upload`, `/api/restore`,
`/files/<id>` and the backup download. Each function runs in one database transaction.

## Measured per-call cost (round trips to the database, empty company)

| Call | Round trips | Of which fixed overhead |
|---|---:|---:|
| `team.tick` | 10 | 8 |
| `cm.unread` | 9 | 8 |
| `auth.me` | 16 | 8 |
| `dash.approvals` | 17 | 8 |
| `lookups` | 25 | 8 |
| `dash.summary` | 41 | 8 |
| `cash.summary` | 76 | 8 |
| server start (cold) | 477 | — |

Time = round trips × trip time + database work. Same-region trip ≈ 1–3 ms; cross-region ≈ 100–250 ms.
`python tools/perf/db_trips.py` measures these on any database.

## Request volume per person

From the screens' own timers: `team.tick` every 15 s (skipped while the tab is hidden) and `cm.unread` every 60 s. That is
**~5 requests a minute per open browser while idle**, and 50 people means ~4 requests/second before anyone does anything. This work makes those
two calls lock-free (they no longer queue behind, or block, anyone's save) and one round trip cheaper.

## Changes made

| Change | Effect |
|---|---|
| `team.tick`, `cm.unread`, `team.presence`, `team.feed` added to the read-only list | No company advisory lock at `BEGIN`. −1 trip each. If one ever writes, the lock is taken at that write (existing design). |
| Company-password hash cached 30 s per copy | −1 to −3 trips on public calls (sign-in screens, licence status). A password change in the same copy applies at once; in another copy within 30 s. |
| Static assets versioned and immutable | Removes 61 requests per visit that never reached the function, but did hold up the first screen. |

## Reviewed, kept as is

| Item | Finding |
|---|---|
| Request validation | Each function checks its own arguments (`need()`, `ApiError`). The function name is checked against the registry. Unknown → "Unknown action". |
| Pagination | List functions return whole lists (the desktop design). Changing that needs screen changes too (see the optimization report). |
| Parallel processing | Not possible inside one copy (`core.LOCK`: the engine switches its global company per request). Concurrency comes from several Vercel copies. |
| Timeouts | `maxDuration: 300` on the function. The database connect timeout is 15 s. The engine lock wait is 25 s, then a "busy" answer. There is no statement timeout (see the audit, B5). |
| Retries | Connection retries with back-off on "too many clients" (up to ~10). The browser shows an offline banner and re-checks every 3 s. Writes are **not** retried automatically. That is correct for financial postings: a retry could post twice. |
| Duplicate submission | The engine numbers documents under the company lock. A DPR sent twice with the same `client_token` is recognised and not saved again (`api_udpr.py:1026`). Nothing was changed. Other forms rely on the user not clicking twice; a general guard would be a desktop change. |
| Background jobs | AI work runs as jobs (`webpatch._patch_jobs`), polled by the browser. Excel/CSV exports are built in the browser from data already loaded. PDF printing uses the browser's print. |
| Error logging | `server.log_error` → Vercel function logs. Translator errors can also go to `BCO_PG_LOG`. |
| Response compression | Handled by Vercel's edge, not the function. Worth confirming on the preview: a large `/api` reply should show `content-encoding: br` or `gzip` in the browser's Network tab. |

## Request deduplication (considered, not added)

Identical calls running at the same moment were looked for: no screen starts the same call twice in parallel (checked
across `Promise.all` uses). In-flight deduplication would add a cache layer that has to know which calls are reads, for
no measured gain, so it was not added.

## Files (Phase 5 of the brief)

### Today

* Supabase Storage, one private bucket (`BCO_STORAGE_BUCKET`, default `buildcore-files`), keys
  `<company schema>/files/<uuid>.<ext>`. Metadata and permissions in the company's `files` table. No binary data in ERP tables.
* Upload: ≤4 MB through `/api/upload`. Larger files go **browser → Storage directly** with a one-time signed URL
  (`web.upload_url` → PUT → `web.upload_done`), never through the function.
* Download: `/files/<id>` checks the sign-in, then redirects to a **300-second signed URL**. Images and PDFs open inline;
  other files download.
* Deletion removes the stored object with the record. Backups go to `<schema>/backups/`.

### Gaps

| Gap | Effect | Suggested fix |
|---|---|---|
| No thumbnails | Photo lists load full-size photos (often 3–8 MB each from phones) | Make a ~320 px WebP when the upload completes (in `web.upload_done`, or a Supabase Storage image transformation on Pro) and use it in lists. |
| No size or type check on `web.upload_url` | Any size or type can be put in the bucket | Accept a declared size and type, and refuse above a limit or outside an allow-list. Check `storage.info()` size in `upload_done`. |
| No resumable upload | A 200 MB drawing set on a site connection fails and starts over | Supabase Storage supports TUS resumable uploads, and R2 supports S3 multipart. Use it for files over ~50 MB. |
| `/files/<id>` doesn't check project access | A signed-in user who guesses a file id can open a file of a project they are not assigned to (same company only) | See the security audit. |
| No version history for general attachments | Document control (`dm_revs`) has revisions; plain attachments do not | Keep as is unless needed. |

### Moving to Cloudflare R2 (for ~1 TB)

R2 has no egress fees and costs less per GB than Supabase Storage at this size. The storage layer is one small file
(`engine/web/storage.py`: `put/get/info/delete/move/listing/signed_download/signed_upload`), so a move is contained:

1. Add `engine/web/storage_r2.py` with the same functions on R2's S3 API (SigV4 presigned PUT/GET).
2. Choose the backend with an environment variable (`BCO_STORAGE=r2` plus `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`,
   `R2_SECRET_ACCESS_KEY`, `R2_BUCKET`).
3. Copy existing objects with `rclone copy supabase:buildcore-files r2:buildcore-files`. The keys stay the same, so no database
   change is needed.
4. Set a CORS rule on the R2 bucket for the site's origin (browser PUT uploads).
5. Switch the variable. Keep Supabase Storage read-only for a month as a fallback.

This was not done in this work: it needs R2 credentials, and it is a migration with its own test plan rather than a speed fix.
