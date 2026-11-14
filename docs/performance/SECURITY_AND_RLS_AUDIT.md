# BuildCore web — security and RLS audit

Scope: company isolation, authorization and session handling, and whether the speed changes on this branch weaken any of
them. Checked in code and tested over HTTP on a local copy.

## How companies are kept apart

| Layer | Mechanism | Where |
|---|---|---|
| Data | **One PostgreSQL schema per company** (`buildcore`, `buildcore_<code>`). Every connection sets `search_path` to the current company's schema only (plus `bcfn` helper functions). | `pgsqlite.Connection.__init__`, `schema_for_path` |
| Supabase public API | `REVOKE ALL ON SCHEMA <company> FROM anon, authenticated`. By default Supabase's data API also exposes only `public` (worth confirming in Supabase → Settings → API → Exposed schemas). The browser never talks to the database; the service-role key and `DATABASE_URL` live only in Vercel. | `pgsqlite.ensure_schema`, `.env.example` |
| Address | The site opens on a **company sign-in** (company ID + company password, or the setup key until a password is set). Success gives an HMAC ticket for that company (`company_ticket`). Public calls without a valid ticket get `COMPANY_LOGIN`. | `webpatch._patch_gate`, `company_pass` |
| Users | User sessions are rows in **that company's** `sessions` table. A token from company A does not exist in company B's schema. | `core.user_from_token` |
| Roles | Module × action permissions (`require`), role templates (`ws_roles`), and project workspaces (`api_workspace`: requests naming another project are refused, and list results are filtered by project). | `core.require`, `api_workspace._precheck/_postcheck` |
| Companies list | Only your own company, except the main company's administrator. A company can change only itself. | `webpatch._patch_gate` |

**Row-level security (RLS)** is not used, and adding it would not add isolation in this design. RLS limits rows per
*database role*, but BuildCore connects as one role and separates companies by schema. Isolation therefore rests on (a) the
schema switch per request and (b) the gate and session checks. Both were tested below.

## Tests run (`tests/company_isolation.py`, over HTTP, new code)

A second company was set up through the public sign-up, then each crossing was tried:

| Check | Result |
|---|---|
| A reads its own company | PASS |
| A's sign-in token is refused in B (no ticket) | PASS |
| A's sign-in token is refused in B, even with B's valid company ticket | PASS |
| B's sign-in token is refused in A | PASS |
| B's company ticket does not open A | PASS |
| A's user name and password do not sign in to B | PASS |
| B's company list does not show A | PASS |
| B's lists contain none of A's users | PASS |

**8 of 8 passed.** Re-run it on staging with
`python tests/company_isolation.py --base <url> --setup-key … --a-company … --a-company-password … --a-user … --a-password …`
(it creates a test company; remove it afterwards).

## Effect of this branch on security

| Change | Security effect |
|---|---|
| 40 indexes | None. No grants, schemas or rows change. |
| `team.tick`, `cm.unread`, `team.presence`, `team.feed` treated as read-only | Only the **company write lock** timing changes. Session, permission and project checks run exactly as before. If one of them ever writes, the lock is still taken at that write. |
| Company-password hash cached 30 s per server copy | After a company password change, **other** server copies keep accepting tickets made with the old password for up to 30 s (the copy where it was changed applies it at once). Sign-in itself always reads the database. `BCO_GATE_CACHE_SECONDS=0` turns the cache off. This is a deliberate, small trade-off: only public calls (sign-in screens, licence status) use the ticket check, and signed-in work is protected by sessions. |
| Versioned static files, WOFF2 | None. Public files as before. |
| Formatting, filter, Copilot changes | None. Browser display only. |

No check was removed or skipped for speed.

## Findings (not changed: they change permissions or behaviour, so they need your decision)

| # | Severity | Finding | Suggestion |
|---|---|---|---|
| S1 | Medium | `/files/<id>` checks that the user is signed in to the company, **not** that they may see that file's project. Ids are sequential, so a site engineer could open another project's documents in the same company by changing the number. | Check the file's `project_id` against the user's allowed projects (the same rule `api_workspace` uses) before signing the URL. |
| S2 | Medium | No `Content-Security-Policy`. Session tokens are in `localStorage`, so any injected script could read them. Screens build HTML with `h()` (text nodes, safe by default), but some use `html:` / `innerHTML`. | Add a CSP in `vercel.json` (scripts from self only; the one inline script in `index.html` needs a hash). Test every screen with it in report-only mode first. |
| S3 | Low | Company sign-in throttling is per company ID (5 tries / 10 min), not per address. Someone can keep a company's *sign-in screen* locked by repeatedly typing wrong passwords for it. Signed-in users are not affected. | Count per company ID **and** IP, or use a short back-off instead of a lock. |
| S4 | Low | Company tickets are HMAC-signed with a key derived from `BCO_SETUP_KEY` + `DATABASE_URL`. Changing either signs everyone out of the company step. That is intended, but it should be documented. | Mention it in `DEPLOY.md`. |
| S5 | Low | `web.upload_url` has no size or type limit. | See `API_PERFORMANCE_REPORT.md` → Files. |
| S6 | Info | Passwords: PBKDF2-SHA256, 120,000 iterations, per-user salt. Sessions: 48-hex-character random tokens, expiring after `session_days` (default 30) of inactivity. Failed user sign-ins are recorded and locked (`login_attempts`). | — |
| S7 | Info | Headers set: `X-Content-Type-Options: nosniff`, `Referrer-Policy: same-origin`, `X-Frame-Options: SAMEORIGIN`. | Add CSP (S2). |

## Central administration

The main company's administrator can see all companies (`_owner`). Creating companies is limited to the public sign-up
(with the setup key) or that administrator. Unchanged.
