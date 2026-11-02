# BuildCore web 2.38.0 "Books agree"

Every cost is posted once, and store, fixed assets and books reconcile, or the checks say exactly why not.
Built on the web edition 2.35.0 (the 2.36 and 2.37 web files were not available).

## What changes for you

**Nothing moves on your live company until your accountant switches it on.** Your company already has vouchers,
so the four switches below start **off**. Open **Administration › Settings › Books agree**: each switch shows its
before and after figures from your data. An accounts approver confirms it with **Confirm and switch on**. A new
company starts with all four on.

| Switch | What it does when on |
|---|---|
| One depreciation route | Machines are depreciated only from **Fixed assets › Depreciation run**. **Equipment › Depreciation & hire charges** shows the result read-only, with a link. **Capital register › Bring in equipment** carries each machine's accumulated depreciation, method, life and residual value from the equipment register. |
| Allocation is the year-end true-up only | Machine hours reach projects through DPR machine lines and the Internal hire run. **Fixed assets › Equipment costing** stops the monthly charge (it explains why), and its year-end true-up compares actual machine cost with **every** recovery: DPR, internal hire and allocation. |
| One equipment recovery account | New allocation and true-up postings credit Equipment Hire Recovery, the account DPR and internal hire already use. Old postings stay on 5490. |
| Hire bills count approved hours only | A monthly hire bill counts approved logsheet hours. Hours still in draft are listed on the bill as "not yet approved, not billed". |

**Always on** (they stop new double postings or only add information):

- **No machine and month is depreciated twice**, whichever screen is used. Equipment › Depreciation skips a machine
  that Fixed assets already depreciated for the month, and the reverse.
- **Fixed assets › Depreciation run › Check** (new tab):
  - **Depreciated twice** lists each machine and month posted by both routes, with both vouchers. **Propose reversal**
    puts a reversing voucher in **Accounts › Posting queue**. Nothing changes until an accounts approver approves and
    posts it. When it is posted, the equipment register is brought in step.
  - **Bring history across**: machines already in Fixed assets with no depreciation, although the equipment register
    has some. Ticking them and confirming copies the history into the register. No voucher is posted.
- **Fixed assets depreciation vouchers name each machine** on their lines (one line per machine, same totals). Each
  machine's share of accumulated depreciation can now be read from the ledger.
- **Completing a disposal in Equipment › Lifecycle always posts it.** If the machine was not in Fixed assets yet, it is
  added first with its full history. Completion stops if the machine is depreciated twice and points to the Check tab.
  The disposal voucher's lines name the machine, so its cost and depreciation clear to zero.
- **One data check list.** Accounts › Integrity checks shows the same list on both tabs, each check with where to correct
  it. New checks:
  - stock = inventory accounts per project, with the vouchers waiting in the posting queue that explain the difference,
    e.g. "Store 132,000, books 165,000, difference −33,000 = 1 voucher waiting in the posting queue (MIN/2083/0011)"
  - Fixed asset register = ledger (cost and accumulated depreciation)
  - equipment register = Fixed asset register
  - no machine and month depreciated twice
  - no machine hours charged twice
  - wages payable per project = DPR labour accrued − wages paid
  - loans = ledger
  - every completed equipment disposal has a voucher
- **Resource histogram:** labour taken from rate analysis is in man-days. It was read as hours, so it showed about
  8 times too few workers. Plans already loaded are relabelled once, at the update.

## What does not change

- No voucher, document, stock row or master record is deleted or renumbered. No posted amount changes.
- No menu item is added, renamed or moved: the new screens are tabs.

## Acceptance (kit `tests/kits/kit_2_38.py`)

Run on fresh test companies with the engine on SQLite: **16 of 16 passed**.

| Check | Result |
|---|---|
| R1 `dep.run` then `fa.dep_run` for September: nothing posted twice; reverse order refused; `dep.run` refused when switched on | pass |
| R2 after `fa.sync`, EX-01: equipment 150,000 = fixed assets 150,000 = ledger 1502 share 150,000 | pass |
| R3 both runs forced through the old code: Check lists September for EX-01 and RL-01; the reversal posts only after approval; then equipment = fixed assets = ledger (225,000) | pass |
| R4 DPR line (8 h) + internal hire (the other 5 h only) + allocation (refused): ROAD charged once | pass |
| R5 200-litre fuel issue in the queue: "explained by 1 queued voucher"; after `pq.post` the difference is 0 | pass |
| R6 RL-01 disposed through Lifecycle with no Fixed asset row: voucher posted, Plant & Machinery and accumulated depreciation for RL-01 are 0 | pass |
| R7 hire bill with a draft logsheet: 15 approved hours billed, 6 draft hours listed | pass |
| G1 rate-analysis labour read as man-days | pass |

**Not run here:**

- R8 (kits 2.24–2.37) and the checks on the 2.24 test company: those kits, the test company and PostgreSQL are not on
  this computer.
- Playwright screenshots, which need the app running.
- Earlier kits that read `rep.integrity` may see the new single list in place of the old one.
- `UPDATE_BuildCore_Complete_2.38.0.bat`, its zips and the server edition: they are built from the desktop project.
