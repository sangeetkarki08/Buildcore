# BuildCore web — load test results

## Read this first

These results were taken on **one Windows computer**: the real engine in `tools/dev_server.py` (one process, like one
Vercel server copy) on a **local** PostgreSQL. There was no Supabase connection, no staging copy and no production data in
this work. So:

* They show how **one server copy** behaves as more people use it. They do **not** show Vercel's scaling across copies,
  network distance to Supabase, or Supabase's connection limits. Those decide production behaviour.
* The before/after difference is small here by design. This work mostly removes **network round trips**, lock
  waits between server copies, and browser work, and a local database (~0.1 ms per trip) cannot show the first two.

To get production-like numbers, run the same tool against a Vercel preview on a Supabase copy (see the end).

## Set-up

* Tool: `tools/perf/load_test.py`. Each simulated person signs in on their own and repeats a weighted mix: `team.tick` ×6,
  `auth.me` ×3, `lookups` ×2, `dash.approvals` ×2, `cm.unread` ×2, `cash.summary` ×1, and the write `ws.enter` ×1, with
  0–1 s between requests.
* 20 seconds per level, 1 / 10 / 25 / 50 people.
* Data: synthetic volume (10 projects, 20k BOQ items, 300k DPR work lines, 150k invoice lines, 200k IPC lines).
* "Before" = commit `136ba2d` (2.48.0 + audit only) on its own copy of the database without the new indexes.
  "After" = this branch.

## Results

| People | Version | Requests/s | Average | p95 | p99 | Errors |
|---:|---|---:|---:|---:|---:|---:|
| 1 | before | 1.7 | 81 ms | 315 ms | 404 ms | 0% |
| 1 | after | 1.8 | 82 ms | 353 ms | 373 ms | 0% |
| 10 | before | 15.5 | 141 ms | 454 ms | 594 ms | 0% |
| 10 | after | 14.4 | 187 ms | 565 ms | 761 ms | 0% |
| 25 | before | 20.6 | 669 ms | 1,462 ms | 1,603 ms | 0% |
| 25 | after | 19.4 | 746 ms | 1,438 ms | 1,594 ms | 0% |
| 50 | before | 21.9 | 1,685 ms | 2,700 ms | 3,526 ms | 0% |
| 50 | after | 23.5 | 1,473 ms | 2,145 ms | 2,388 ms | 0% |

## What the numbers say

1. **No errors** at any level, before or after.
2. **One server copy tops out at about 20–23 requests a second.** Beyond ~10 people, time goes into waiting for the
   engine lock (`core.LOCK`, one request at a time per copy), not into work. That is the engine's design: it switches
   a global "current company" per request.
3. The before/after differences at 1–25 people are within run-to-run noise. At 50 people, p95 and p99 were lower after the change
   (2.70 → 2.15 s, 3.53 → 2.39 s). One run each, so treat it as a hint rather than proof.
4. **For 25–50 people in production, several server copies must run.** Vercel starts them as requests overlap, and each
   new copy pays a cold start (477 round trips plus the Python import). Same-region round trips matter a lot here (see the
   region note in the optimization report).

### Idle load from open browsers

Every open BuildCore tab sends `team.tick` every 15 s and `cm.unread` every 60 s: **~0.08 requests/s per person**. 50 people
means ~4 requests/s with nobody working, about one fifth of a single copy's capacity. This branch makes those calls skip the
company write lock, so they no longer queue behind saves (or hold saves up) across copies.

## Not covered here

The brief also lists simultaneous logins, DPR submissions, purchase entries, inventory and accounting entries, report
generation and document uploads, plus CPU, memory and database-connection figures. Those need a staging copy with real
masters (projects, BOQ, materials, accounts) to post against, and Vercel/Supabase dashboards to read the resource figures.
None of that was available here. The tool's mix is defined in one list (`MIX` in `load_test.py`): add your own calls and
arguments, for example a DPR save with a fresh `client_token`, once a staging copy exists.

## Running it on staging

```
python tools/perf/load_test.py --base https://<preview>.vercel.app --company <company-id> \
    --company-password <...> --user <test user> --password <...> --users 1,10,25,50 --seconds 60 --json results.json
```

While it runs, watch Vercel → Observability (function invocations, duration, cold starts) and Supabase → Reports
(connections, CPU). If you see "database is busy" errors, the Supabase pool size is the limit (see the hosting
recommendations).
