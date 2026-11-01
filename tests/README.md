# What was checked (1 November 2026, BuildCore web 2.35.0)

All on a local PostgreSQL 16 database with the web engine, against BuildCore desktop 2.35.0 on SQLite
(2.16.1 install + the shipped `UPDATE_BuildCore_Complete_2.35.0` updater). The test company is the 2.24 seed
(`buildcore/2.24/tests/seed.py`), brought into the web database through the web's own restore path
(`transfer.import_sqlite`), as Backup & restore does on the website. `kits/harness_web.py` is the harness
used: the same calls as the desktop kits' `harness.py`, on PostgreSQL. Files went through a local stand-in
for Supabase Storage (`tools/dev_storage.py`).

| Test kit | Web (PostgreSQL) | Desktop (SQLite) |
|---|---|---|
| 2.24 (T1–T12) | 12 of 12 | 12 of 12 |
| 2.25 Universal DPR (U1–U14) | 14 of 14 | 14 of 14 |
| 2.26 billing / receivables / payables (F1–F13) | 13 of 13 | 13 of 13 |
| 2.27 cash forecast (W1–W9) | 9 of 9 | 9 of 9 |
| 2.28 DPR to cost (X1–X10) | 10 of 10 | 10 of 10 |
| 2.29 command centre (Y1–Y12) | 11 of 12 | 11 of 12 (Y9 fails the same way on both; date-dependent) |
| 2.29 kit as of 2.31 | 12 of 12 | 12 of 12 |
| 2.30 (Z1–Z10) | 10 of 10 | 10 of 10 |
| 2.31 report generator (G1–G12) | 12 of 12 | 12 of 12 |
| 2.32 monthly logsheets (V1–V10) | 10 of 10 | 10 of 10 |
| 2.33 equipment hours (M1–M10) | 10 of 10 | 10 of 10 |
| 2.34 document library + claims (D1–D9, C1–C11) | 20 of 20 | 20 of 20 |
| 2.35 DPR machine hours (P1–P12) | 11 of 12 | 11 of 12 (P6 fails the same way on both in this test set-up) |

Every result line, with every figure the kits print, is identical on web and desktop
(`results/2.35/web_postgres_*.txt` against `results/2.35/desktop_sqlite_*.txt`).

**Every screen in a browser** (`crawl.js`): 180 screens in the company workspace and again in a project
workspace, 360 visits, no errors (`results/2.35/screens_web.json`).

**Fresh site over HTTP**: an empty database opens on *Activate BuildCore* with a request code; the setup key is
refused when wrong and accepted when right; a file uploaded through `/api/upload` goes to Storage, is added to
the document library, read, found by an exact phrase (and not by the phrase reversed), passes *Check*, and
comes back byte for byte from its `/files/` link.

Results of the 2.29.0 web build are kept in `results/` (files without a version folder).
