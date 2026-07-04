# BuildCore — Construction Management OS

Single-file contractor operations platform (projects, tenders, inventory,
equipment, BOQ/estimation, finance, QA/NCR, audit log). Originally a
local-only prototype; now backed by **Supabase** for real auth and
cross-device persistence, with `localStorage` kept as an offline cache.

## Project layout

```
buildcore.html                    The entire app (UI + logic)
js/buildcore-supabase.js          Auth + State<->Postgres sync layer
js/supabase-config.example.js     Copy to js/supabase-config.js
supabase/schema.sql               Tables, RLS, profile trigger
supabase/seed.sql                 (seeding is automatic — see below)
.env.example                      Config reference for CLI/CI
```

## Setup

1. **Create a Supabase project** at https://supabase.com.

2. **Apply the schema.** Supabase Dashboard → SQL Editor → paste
   `supabase/schema.sql` → Run. (Or `supabase db push` with the CLI.)

3. **Add the front-end config.**

   ```sh
   cp js/supabase-config.example.js js/supabase-config.js
   ```

   Put your **Project URL** and **anon key** (Project Settings → API)
   into `js/supabase-config.js`. This file is git-ignored. The anon key
   is browser-safe — Row Level Security is what protects the data.

4. **Serve the folder** (a static server, since the app now loads
   `js/*.js`):

   ```sh
   npx serve .
   # or: python -m http.server
   ```

   Opening `buildcore.html` directly via `file://` also works for the
   offline mode but browsers may block module/auth requests — prefer a
   local server.

## Accounts & data

- **Two-stage login.** Stage 1 is **company sign-in** — real Supabase
  email/password (first time: enter email + password → **Create
  account**); this lands on the portfolio. Stage 2: clicking **Enter
  Project** opens a per-project gate where you pick your **job role**
  (Engineer / CEO / Store / QC / PM / CFO / Estimator) and enter that
  role's **passcode**. Exiting a project drops the role; the next
  project entry re-authenticates.
- **Demo role passcodes** (change in `buildcore.html` → `ROLE_PASSCODES`
  for production): Engineer `eng123`, CEO/Admin `ceo123`, Store
  `store123`, QC `qc123`, PM `pm123`, CFO `cfo123`, Estimator `est123`.
- On your **first sign-in**, the app uploads its built-in seed data to
  your workspace. After that, every change syncs to Supabase
  (debounced) and is restored on any device you sign in from.
- If `js/supabase-config.js` is missing or still has placeholder
  values, the app silently falls back to **offline mode**
  (`localStorage` only) and behaves exactly as the original prototype.

## Data model

Every collection the app tracks — projects, tenders, materials, BOQ,
vendors, HRMS/manpower, assets, budget & cost control, AI document
intelligence, inventory (IMS), equipment, plant production, quality/lab,
documents, estimation/finance, events/todos, governance, accounting
foundation (chart of accounts, fiscal years, contractor master) — is
its own RLS-isolated table storing the record verbatim in a `data
jsonb` column, so the front-end shape migrates losslessly. See the
`collection_tables` array in `supabase/schema.sql` for the full,
authoritative list (95 tables as of this writing) and
`js/buildcore-supabase.js`'s `MAP` for the State-key ↔ table mapping.

Typed, queryable **views** (`v_projects`, `v_tenders`, `v_materials`,
`v_ra_bills`, `v_purchase_orders`, `v_assets`, `v_asset_allocations`,
`v_asset_maintenance`) expose real columns for reporting and external
CRUD on the core business entities; every other table is still fully
usable via its raw `data` JSONB column. Workspace scalars (automations
map, active project, feature flags, DPR templates, tax config) live in
`app_settings`.
