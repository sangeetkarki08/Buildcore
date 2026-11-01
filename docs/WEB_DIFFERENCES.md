# What is different from BuildCore desktop

The menus, module names, groups, icons, order, screens, reports, figures and permissions are the desktop's.
These are the only differences, all because a website has no Windows computer behind it.

## Where things are kept

| Desktop | Web |
|---|---|
| `data\buildcore.db` (one file per company) | Supabase PostgreSQL, one schema per company (`buildcore`, `buildcore_<name>`) |
| `data\files\` (photos, documents) | Supabase Storage, private bucket `buildcore-files`, folder `<schema>/files/`. Links are signed and last a few minutes. |
| `backups\` (made every day automatically) | Backup & restore saves to Storage `<schema>/backups/` when you press *Save a backup*. There is no automatic daily copy by BuildCore; use *Download a backup now* regularly, and Supabase's own daily backups on its paid plans. |
| `licence\` files | A small table `web_kv` in the database |
| `companies.json` | The same table `web_kv` |

## Behaviour

- **Restore** takes a desktop backup (`.db` file) and replaces the current company's data with it. The data
  that was there before is kept in schema `<schema>__before_<date_time>` (the two newest are kept).
  A number column that holds text in the desktop file (SQLite allows that, PostgreSQL does not) is left empty
  and the original text is kept word for word in table `web_import_notes`. In the tests, no such value existed.
- **Download a backup** gives a desktop data file: it opens in BuildCore desktop with the same records and ids.
- **Attachments from BuildCore desktop** is a new panel on Backup & restore, to send the desktop's
  `data\files` folder after a restore.
- **Files larger than 4 MB** go straight from the browser to Storage with a one-time link (Vercel limits a
  request to 4.5 MB).
- **First administrator**: asks for the setup key (`BCO_SETUP_KEY`).
- **Licence**: the web edition is one "computer". Its request code comes from the Supabase project.
  Keys made on the web (if the web holds the master key) are listed from the database.
- **AI document reading and other background jobs** run within the request (up to 300 seconds) instead of
  in a background thread.
- **Team & devices / Remote access** (the desktop's own local-network server) have nothing to do on the web:
  everyone simply opens the web address.
- **Sign-in** is BuildCore's own users and passwords, as on desktop. Supabase Auth is not used.

## Screen texts changed by `tools/sync_desktop.py`

- Page title "BuildCore Offline" becomes "BuildCore"; `web.js` is loaded before the screens.
- "BuildCore server is not running…" becomes "Cannot reach BuildCore. Check the internet connection and try again."
- "See data/error.log" becomes "The details are in the Vercel logs."
- First-run text: "Everything is stored on this computer" becomes "…in your own Supabase database".
- Sign-in page: "Your data stays on your own computer or office server" becomes "…in your own Supabase database".
- Licence page title: "Activate BuildCore on this computer" becomes "Activate BuildCore".
- Backup & restore subtitle is reworded by `web.js` (no automatic daily backups on the web).

## Document library (2.34) on the web

- Files are read from Supabase Storage. To read a document's words the server fetches it into a temporary
  folder first, so the first search after adding many files can take a little longer.
- **Check for missing files** looks in Storage instead of the data folder.
- Search keeps the desktop's search words: all words, "exact phrase", word starts (`penst` finds penstock),
  `OR`, and `-word` to leave a word out. PostgreSQL has no SQLite full-text index (FTS5), so the web lists
  the documents found **newest first** instead of best match first.

## Engine start-up run more than once

The web runs the engine's start-up again in the same server copy after a restore and for each extra company.
The web layer makes sure the screens' connections made at start-up (My work, search) are not made twice;
without it, My work would show each claim deadline or letter more than once after a restore.

## Earlier known issue

Up to 2.29 the web (like the desktop) showed "no such column: project_id" on 8 screens in the project
workspace. With 2.35.0 every screen opened without an error in both workspaces (see `tests/README.md`).
