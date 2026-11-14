# BuildCore web 2.35.0

BuildCore in the browser: the same screens, menus, modules and figures as BuildCore desktop 2.35.0,
with the data in **Supabase** (PostgreSQL), the website on **Vercel**, and the code in **GitHub**.

**To put it online for free, follow [docs/DEPLOY.md](docs/DEPLOY.md)** (about 45 minutes, once).

## What is in this repository

| Folder / file | What it is |
|---|---|
| `public/` | The screens (HTML, CSS, JavaScript), exactly the desktop's, plus `web.js` for the few web steps. Vercel serves them as plain files. |
| `engine/` | The BuildCore engine, the same Python files as desktop 2.35.0, unchanged. |
| `engine/web/` | The web layer: lets the engine use PostgreSQL in place of its SQLite file (`pgsqlite.py`), keeps photos, documents and backups in Supabase Storage (`storage.py`), imports and exports desktop data files (`transfer.py`), and the web start-up (`boot.py`, `webpatch.py`). |
| `api/index.py` | The one Vercel function. Every `/api` and `/files` request goes to it. |
| `vercel.json` | Vercel settings: function size and time limit, the region (Mumbai), the address rewrites. |
| `supabase/schema.sql` | The database layout. Not needed: the app creates it on first start. |
| `.env.example` | The four settings to put in Vercel. |
| `tools/` | `sync_desktop.py` (bring a new desktop version in), `web_build.py` (versioned file addresses and WOFF2 fonts, run by the sync), `dev_server.py` (run it on your own computer), `dev_storage.py` (a stand-in file store for testing), `perf/` (database round trips, query plans, load test). |
| `tests/` | What was checked before delivery and the results; `company_isolation.py` (company A cannot reach company B). |
| `docs/` | `DEPLOY.md` (how to publish), `WEB_DIFFERENCES.md` (what is different from desktop), `performance/` (speed audit, what was changed, hosting advice). |

## How it works

The engine is the desktop engine. In place of Python's `sqlite3` module it is given `engine/web/pgsqlite.py`,
which speaks the same language to the engine and translates each SQLite statement for PostgreSQL. Every
company is one PostgreSQL schema (`buildcore`, then `buildcore_<name>` for each extra company), the way
each company is one data file on desktop. Ids are given out the same way SQLite does (highest + 1), so
records, voucher numbers and links keep their numbers when data moves between desktop and web.

Every request runs as one database transaction with a per-company lock, as on desktop, so two people saving
at the same moment cannot mix their entries.

## Updating to a new BuildCore version

When a new desktop version comes out:

1. Install it on a Windows computer as usual.
2. On a computer with Python 3.10+ and this repository (once: `pip install fonttools brotli`, for the WOFF2 fonts):
   `python tools/sync_desktop.py "C:\Program Files\BuildCore\resources\backend"`
   (the backend folder of the installed app). It copies the new engine and screens in, keeps the web layer, makes the
   web's speed changes again (`docs/performance/`), and versions the file addresses so browsers fetch only what changed.
3. Commit and push to GitHub. Vercel deploys the new version; on its first start the engine upgrades the
   database the same way the desktop upgrades its data file.

Check `docs/WEB_DIFFERENCES.md` for the few screen texts `sync_desktop.py` changes; it says if one was not found.
A "text not found" note on `lib.js`, `pages_keys.js` or `pages_copilot.js` means the desktop changed that code, so the
speed change there needs another look (see `docs/performance/PERFORMANCE_OPTIMIZATION_REPORT.md`).

## Running it on your own computer (optional)

```
pip install -r requirements.txt
set DATABASE_URL=...   (and the other settings from .env.example)
python tools/dev_server.py
```
Then open http://127.0.0.1:8760.
