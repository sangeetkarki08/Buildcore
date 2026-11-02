# BuildCore 2.38.0 "Books agree": audit and plan

Written for: Sulav Bhatta (owner) and the company accountant.
Status: **built** after your "update all" (2 November 2026), with the recommended answers to section 9: built on
2.35 here, Allocation becomes the year-end true-up, all four switches start off on your live company. See
`CHANGELOG_2.38.0.md` for what was done and the kit results.

## 0. What this was checked against

| Item | Situation |
|---|---|
| Code audited | This Git repository (BuildCore **web**, Vercel + Supabase), engine version **2.35.0** (`engine/api_sched.py`). |
| 2.37.0 | Not in this repository. The 2.37 files (`C:\BuildCoreWeb237`) were never found, so `fastdb.py`, `api_speed.py` and `api_pwreset.py` are missing here. |
| `AUDIT_ONE_PLATFORM_2.37.md`, `reproduce_2.37.py` | Not on this computer. Each finding below was checked against the code directly instead. |
| 2.24 test company, kits 2.24–2.37 | Not on this computer. Only `tests/kits/harness_web.py` is here. |
| Desktop shell, updaters (`.bat`), server edition | Not in this repository. Only the web edition can be built and deployed from here. |

**Decision needed first (see section 9):** building 2.38 on top of 2.35 here would make the web edition differ from the
desktop line, which is already at 2.37.

## 1. Findings in the current code

Each finding is marked **Confirmed** (seen in code), **Different** (the prompt's description does not match the code; the
nearest correct fix is proposed), or **Can't check here** (needs data or files that are missing).

| # | Finding | Result | Evidence |
|---|---|---|---|
| A1 | Two depreciation routes | **Confirmed** | `dep.run` (`api_equipment_reports.py:374`) checks only `dep_runs`. `fa.dep_run` (`api_fa.py:537`, via `_dep_rows`) checks only `fa_dep`. The same machine and month can be posted by both. |
| A2 | `fa.sync` loses history | **Confirmed** | `api_fa.py:264`: machines are added with `accumulated` = 0, and method, life and residual come from class defaults (`_defaults`). `equipment.accumulated_dep`, `dep_method`, `life_months`, `residual_value` and `wdv_rate` are ignored. (Assets from the Asset register do carry `accumulated_dep`, and are left unmanaged.) |
| A2b | Ledger by machine | **New** | `fa.dep_run` posts one voucher per project **without `equipment_id`** on the lines, so "the machine's share of 1502" (R2) cannot be read from the ledger for that route. `dep.run` does set `equipment_id`. |
| A3 | Disposal without posting | **Confirmed, different place** | The posting is in `life.disp_advance` (`api_life.py:713`, step "completed"), not `life.disp_save`. With no Fixed asset row it only sets `equipment.status='disposed'`. No voucher is posted and cost stays in the books. |
| A5 | Machine hours charged more than once | **Confirmed** | `fa.alloc_run` (`api_fa.py:833`) charges every logbook hour (`hours_used`) to `equip_job_cost`/`equip_recovery`. It does not look at DPR machine lines or `internal_bills`. `internal.preview` already skips DPR hours (`dpr_id IS NULL`). |
| A5b | Two recovery accounts | **Confirmed** | `fa.alloc_run` and `fa.trueup_run` credit role `equip_recovery` (account 5490, an **expense contra** account). Internal hire (`api_equipment_reports.py:423`) and DPR charges credit `equipment_recovery` (income). *Correction made while building:* because 5490 is an expense contra, Allocation recoveries are **not** counted as income on the cash forecast or company overview, so those screens need no change. |
| C1 | Posting queue vs store | **Confirmed** | Queued vouchers have `status='submitted'` (`api_exec.py:382`). Stock moves at once, but the books move only when posted. `rep.integrity` (`api_equipment_reports.py:778`) compares stock and books per project and fails with no explanation. |
| C2 | Two check lists | **Confirmed** | `rep.integrity` (Accounts › Integrity checks, first tab) and `fc.checks` (`api_fc.py:1420`, "Financial data checks" tab on the same screen) overlap: both check voucher balance and debtors/creditors. Only `fc.checks` has "where to correct". |
| C4 | Hire bills count drafts | **Confirmed** | `hire.bill` (`api_equipment_reports.py:297`, wrapped in `api_life.py:1288`) sums all logsheets. `logsheets.status` exists (`draft`/approved) but is not checked. |
| G1 | Histogram labour 8× too low | **Confirmed** | `res.load` (`api_res.py:175-191`) labels the rate-analysis labour quantity (man-days in the norms) as unit `"hr"`. `_per_day_units` then divides it by the day's hours (8). |
| G2 | My work doubles after restore or company switch | **Already fixed on the web, open on desktop** | The web edition fixed it in `engine/web/webpatch.py` (`_patch_reinit` restores the function table after a second `core.init_db`). The desktop fix belongs in `core.init_db` or `server.py`, which is the desktop's code, not this repository's. |

## 2. What I will change (2.38.1–2.38.7)

### 2.38.1 One depreciation route
- `dep.run`: refuse with "Depreciation is posted from Fixed assets › Depreciation." when the switch is on (section 6).
  `dep.preview` stays and shows, per machine and month, the Fixed assets amount and voucher with a link.
- Shared guard `_dep_done(c, equipment_id, month)` = row in `dep_runs` **or** a `fa_dep` row for the machine's
  `fa_register` id. Both `dep.run` and `_dep_rows` (used by `fa.dep_run`) skip a machine and month that is done.
  This guard is **always on** (it only prevents double posting; it changes no existing figure).
- `fa.dep_run`: put `equipment_id` on each voucher line (one line per machine instead of one per project), so that
  1502 can be read per machine. Totals per voucher stay the same.
- `fa.sync`, for new rows: method, life, residual and WDV rate from the equipment register when filled in, otherwise
  the class defaults. Accumulated depreciation = `equipment.accumulated_dep` (which already includes `dep_runs`).
- **Bring history across** (new action on Fixed assets › Register): for machines already synced with
  accumulated 0 and history in the register, a preview (register figure, `dep_runs` total, ledger 1502 for the
  machine), then copy on confirm. It writes only `fa_register.accumulated`. **No voucher is posted**, because the
  ledger already holds the depreciation.
- **Fixed assets › Check** (new tab, read-only): every machine and month in both `dep_runs` and `fa_dep`, with
  amounts and vouchers. "Propose reversal" creates a reversing journal of the duplicate as a **draft in the posting
  queue** (`status='submitted'`). It posts only when an accounts approver approves and posts it through the
  existing queue. The duplicate's register row is corrected when the reversal is posted, not before.

### 2.38.2 One machine-charge route
- Official route: DPR machine lines + Internal hire run (logsheet hours with no DPR). Unchanged.
- `fa.alloc_run` and `fa.alloc_preview` subtract, per machine, project and month, the hours already charged by DPR
  machine lines and `internal_bills`. Only the rest is charged.
- **Recommendation:** after the switch, Allocation becomes the **year-end true-up only**, and the monthly charge button
  shows the reason. The monthly DPR and internal-hire charges already recover the machine cost at the internal rate.
  The true-up (`fa.trueup_run`) is the one thing that needs Fixed assets' actual-cost figures. The true-up must then
  compare actual cost with **all** recoveries (DPR + internal hire + allocation), not only `fa_alloc`. I will change
  `fa.trueup_preview` to do that.
- One recovery account: new postings use role `equipment_recovery`. `equip_recovery` is mapped to the same account
  for new postings. Old vouchers stay on 5490. (No report change is needed; see A5b.)

### 2.38.3 Disposal always posts
- `life.disp_advance` "completed": if the machine has no `fa_register` row, create it (with the history from 2.38.1),
  then call `fa.dispose`. Gain or loss = proceeds − costs to sell − (cost − accumulated depreciation − impairment), using
  the reconciled figure from 2.38.1. If cost or accumulated depreciation still disagree with the ledger, completion
  stops and links to Fixed assets › Check.

### 2.38.4 Posting queue and store
- The stock-against-books check (in both lists) explains differences: queued vouchers (`status='submitted'`) touching
  inventory roles for that project are listed with number and amount ("difference 33,000 = 1 issue waiting in the
  posting queue (MIN/…/0011)"). It fails only when something is left unexplained.

### 2.38.5 One data check screen
- `fc.checks` becomes the single list. Accounts › Integrity checks (`rep.integrity`) returns the same list; the menu item
  and the tab stay. The checks only in `rep.integrity` (GRN clearing, negative stock, transfers in transit) move into
  `fc.checks`.
- New checks, each with "where to correct": stock = inventory per project (queue explained); FA register cost and
  accumulated = ledger per asset class; equipment register = FA register; no machine and month depreciated twice; no
  machine hours charged twice; wages payable per project = DPR labour accrued − wages paid; each loan = its ledger
  account; every completed disposal has a voucher.

### 2.38.6 Hire bills count approved hours only
- `hire.bill` (and the attachment-rate wrapper) count logsheets with `status='approved'` only. The bill and the screen
  show "N h in draft, not yet approved" beside the total.

### 2.38.7 Open defects
- G1: `res.load` gives labour lines from rate analysis the unit `"day"` (man-days). Lines loaded earlier and still
  marked `"hr"` are relabelled once when they come from rate analysis (the `source` column tells).
- G2: no change needed on the web. The desktop fix is noted for the desktop build.

## 3. What I will not change

- No voucher, document, stock row or master row is deleted or renumbered. No posted amount changes.
- Corrections are only new reversing vouchers, proposed and posted through the posting queue after approval.
- No menu item is renamed, moved or removed. New screens are tabs (`addTabs` / `window.BCO_TABS`) or buttons.
- Equipment › Depreciation, Fixed assets › Allocation and Reports › Integrity stay visible.

## 4. Figures that can change on live data (need your "go")

| Change | Effect on an updated company |
|---|---|
| `dep.run` refused | Monthly depreciation for machines comes only from Fixed assets. If a machine is not in the FA register yet, nothing is depreciated for it until `fa.sync`. |
| `fa.sync` with history | New FA rows start with the register's accumulated depreciation instead of 0, so later FA depreciation is lower (correct). |
| Allocation net of DPR/internal hire | Project equipment cost from Allocation drops by the hours already charged. |
| True-up against all recoveries | Year-end under- or over-recovery figures change. |
| Recovery account | New recoveries go to one account. Old balances stay. |
| Hire bills, approved hours only | Bills for months with draft logsheets are lower until those sheets are approved. |
| Histogram labour | Labour on the histogram rises about 8×. This is display only, no ledger effect. |

## 5. Switches (Administration › Settings), per rule 5

| Setting | New company | Updated company |
|---|---|---|
| `one_dep_route` (2.38.1) | on | off until the accountant confirms; confirm screen shows the depreciation per machine both ways |
| `alloc_trueup_only` (2.38.2) | on | off until confirmed |
| `one_recovery_account` (2.38.2) | on | off until confirmed |
| `hire_bill_approved_only` (2.38.6) | on | off until confirmed; confirm screen shows each open month's billed hours before and after |

Always on (they only stop new double postings or add information): the double-depreciation guard, the queue
explanation, the new checks, disposal posting, and the histogram unit.

## 6. Tests

- New kit `tests/kits/kit_2_38.py` with R1–R7 on a fresh company built by `harness_web.py`.
- **Limits here:** the 2.24 test company and kits 2.24–2.37 are not on this computer, so R8 ("all earlier kits pass") and
  the R-checks on the 2.24 company cannot be run until you copy them in. The web edition needs PostgreSQL to run.
  There is none on this computer, so the kit will run the engine on SQLite (as the desktop does), plus one run against
  Supabase only if you allow it.
- Playwright screenshots of the changed screens need the app running. That is possible only with a database (see
  above).

## 7. Delivery from this repository

- Code changes, the kit and `CHANGELOG_2.38.0.md`, committed and pushed (Vercel deploys).
- **Not possible here:** `UPDATE_BuildCore_Complete_2.38.0.bat`, its zips and the server edition zip. They are built from
  the desktop project.

## 8. Order of work

1. 2.38.1 guard (always on) and 2.38.4 queue explanation: safe, no figure changes.
2. 2.38.5 single check list, 2.38.6, 2.38.7.
3. 2.38.1 switch, sync history and Check tab, then 2.38.2, then 2.38.3.

## 9. Decisions needed before building

1. **Base version.** Build 2.38 here on 2.35 (the web edition then differs from the desktop's 2.37), or first copy in the
   2.37 web files and build on those? I recommend getting 2.37 in first.
2. **Allocation**: becomes year-end true-up only (recommended), or keeps monthly charging net of DPR and internal hire?
3. **Go** for the switches in section 5, all defaulting to "off until the accountant confirms" on your live company.
