# BuildCore user guide

This guide is what the Help assistant (F1) answers from. Each topic starts with "## ". Links like [Goods received](#/inv/grn) open the screen.

## Getting started: modules, menu and finding a screen
keys: Ctrl+M, Ctrl+K, Alt+G, Ctrl+G, 1-9
After signing in you land on the Modules screen (#/home): one box per module your role can use (Dashboard, Site work & DPR, Commercial & billing, Store & inventory, Procurement, Accounts, Plant, Assets, Fixed assets, Resources & rates, Equipment & machines, Master data, Administration).
- Click a box, or press its number 1-9, to open the module. The module home shows quick-entry buttons, key figures and all its screens as boxes.
- The side menu then shows only that module's screens. "‹ All modules" or Ctrl+M goes back to the Modules screen.
- "Find a screen" at the top of the side menu (Ctrl+K) searches every module by name.
- Alt+G or Ctrl+G goes to any screen or record by typing part of its name or number.
- "Continue" on the Modules screen lists the screens you used last.
- The breadcrumb above each page shows Modules › module › screen; click a part to go back.

## Signing in, passwords and locked users
screens: admin/users
- Sign in with your username (or your full name) and password. Usernames are not case-sensitive; passwords are.
- If several companies exist, choose the company on the sign-in screen first.
- After 5 wrong passwords a user is locked for a while. An administrator opens [Users](#/admin/users) › Sign-in status and clicks Unlock.
- Forgotten password: an administrator sets a new one in [Users](#/admin/users). Passwords cannot be read back, only replaced.
- Change your own password from the round initials button (top right) › Change password.
- Sign out from the same button.

## Companies (several companies like Tally)
keys: Alt+F3
screens: admin/companies
- Each company has its own data, users, fiscal years and backups. Nothing is shared after creation.
- Create one in [Companies](#/admin/companies) › New company. You can copy the chart of accounts, materials, parties, machines, staff and users from the current company. Opening balances start at zero.
- Switch company with Alt+F3 or the company chip in the top bar; you sign in again in the company you choose.
- A company that cannot be opened is marked in Companies with "Try again"; the other companies keep working.

## Fiscal years, closing a year and opening balances
screens: acc/fy, acc/periods
- The year selector in the top bar sets the dates of reports and lists.
- [Fiscal years](#/acc/fy) › Years: "Close year" freezes the balances and stock of the year, locks its periods and creates the next year. BuildCore warns first about drafts and unbalanced items; an administrator can reopen a closed year.
- Opening balances of a year are the frozen closing balances of the previous one (Fiscal years › Opening balances). Books stay continuous, like Tally: profit of earlier years shows as "Profit & loss brought forward" in the trial balance and balance sheet.
- Fiscal years › Tax summary gives VAT, TDS and profit by year.
- [Periods](#/acc/periods) lock or open single months. A posted voucher cannot be entered in a locked period.

## Dates: AD and BS (Nepali dates)
keys: F2, F12
- F12 (Configure) switches the whole program between AD and BS dates. Dates can be typed in either form (YYYY-MM-DD).
- F2 changes the from / to dates of the screen you are on.

## Projects and changing project
keys: F3
screens: m/projects
- Projects are created in [Projects](#/m/projects). Most screens work on the project chosen in the top bar (F3 to change it).

## Daily progress report (DPR)
keys: F10 then D
screens: p/dpr
- Open [Daily progress (DPR)](#/p/dpr) and click New (or F10, D from anywhere). BuildCore fills the planned work for the date from the schedule plus labour and machines.
- Enter work done per activity / BOQ item, labour, machines and their hours, materials used, weather and delays. Delays can raise an event / claim.
- Machine hours entered in the DPR become the machine logsheets (logsheets are made only from the DPR).
- Save, then submit for approval if your company uses approvals.
- "View & print" (tab on the DPR screen, or "View report" in an open DPR) shows the formatted report; print one or several days.

## Schedule, WBS and progress
screens: p/schedule
- [Schedule & WBS](#/p/schedule) holds activities, links and calendars. "Calculate" works out dates, critical path and float. DPR progress updates the schedule.

## BOQ items, locations and BOQ control
screens: m/boq, p/boq
- BOQ items are entered in [BOQ items](#/m/boq). Each item can have a location / component (e.g. Headworks, Alignment, Powerhouse): choose it in the Location box at the top of the BOQ entry sheet, or "+ New location". The list can be filtered by location and shows subtotals per location.
- [BOQ control](#/p/boq) compares contract quantity, measured, billed and cost per item.

## Measurements, IPC and client billing
keys: Alt+F6, F10 then I, F10 then M
screens: p/measure, p/ipc, acc/sales
- Record measured quantities in [Measurements](#/p/measure) (Alt+F6).
- Make the client bill in [IPC billing](#/p/ipc) (F10, I): BuildCore pulls approved measurements, applies advance recovery, retention, VAT and deductions.
- Client invoices (sales vouchers, F8) are in [Client invoices](#/acc/sales).

## Variations and events / claims
keys: F10 then V, F10 then E
screens: p/variations, p/events
- [Variations](#/p/variations) record change orders with quantity and rate. [Events & claims](#/p/events) record delays and notices; delays from the DPR can create them.

## Contracts, letters, reports and bonds
screens: c/contracts
- [Contracts & letters](#/c/contracts) is the register of subcontracts, supply, hire, client and consultant contracts.
- Each contract has its letters, reports, deliveries, milestones, notices and payments with due dates; repeating ones (monthly report, quarterly programme) get their next date when marked done.
- Bond and insurance expiry dates and the contract end date raise warnings 30 days ahead. The Schedule tab lists everything due.
- Templates add the usual deliverables for each kind of contract.

## Reading contract and specification documents with AI
screens: c/docs
- [Contract documents](#/c/docs) holds the contract, GCC, SCC, technical specifications and other documents (PDF, Word or text).
- Upload a document (optionally linked to a contract). BuildCore reads its text; scanned PDFs are read by the AI when it is switched on.
- "Read with AI" makes a contract abstract: contract value and dates, advance, retention, bonds, insurance, liquidated damages, price adjustment, payment terms, defects liability, notices, preconditions (what must be done before work, payment or a claim) and technical requirements (materials, tests, frequencies, tolerances). Each item shows its clause and page.
- Check every item: Approve, Edit or Reject. Approved items with a date can be added to the contract's schedule so BuildCore reminds you.
- "Ask the document" answers a question from the document with clause and page. Without AI, "Search" finds the words in the document and shows the pages.
- The AI can make mistakes: always check the clause before acting. It is not legal advice.

## Store: requisition, goods received, issue, return, transfer
keys: Alt+F5, Alt+F9, Alt+F8, Alt+F7, F10 then U
screens: inv/mrq, inv/grn, inv/issue, inv/return, inv/transfer, inv/stock, inv/store
- Material requisition (Alt+F5): site asks the store for material; it can turn into a purchase request.
- Goods received / GRN (Alt+F9): receive material against a purchase order (choose the PO and quantities come in) or without one. Quality rejections are recorded on the GRN.
- Issue (Alt+F8): give material to a site, activity or machine; it can come from a requisition.
- Return (F10, U): material coming back to the store.
- Transfer (Alt+F7): move stock between stores.
- [Stock on hand](#/inv/stock) and [Store by kind](#/inv/store) show what is in each store. Store by kind separates consumables, tools, spare parts and others; tools show who holds them. Change a material's kind there with "Move items to this kind".
- [Stock card](#/inv/card) shows every movement of one material.

## Stock count, opening stock and reconciliation
keys: Ctrl+F7
screens: inv/count, inv/opening, inv/recon
- [Stock count](#/inv/count) (Ctrl+F7) records a physical count; differences are posted as adjustments after approval.
- [Opening stock](#/inv/opening) enters stock at the start.
- [Material reconciliation](#/inv/recon) compares theoretical use (from work done and norms) with actual issues to show wastage.

## Procurement: purchase request, quotations, purchase order, bills
keys: Alt+F4, F9, F10 then Q
screens: proc/pr, proc/cs, proc/po, proc/pending, proc/invoices, proc/vendors, proc/prices
- Purchase request (F10, Q) → [Quotation comparison](#/proc/cs) → purchase order (Alt+F4) → GRN → purchase bill (F9).
- [Pending deliveries](#/proc/pending) shows what is still to come and what is late.
- [Vendor performance](#/proc/vendors) shows on-time delivery, rejections and prices; [Price history](#/proc/prices) shows rates paid.

## Accounts: vouchers like Tally
keys: F4, F5, F6, F7, F8, F9, Ctrl+F8, Ctrl+F9, Alt+2, Ctrl+A
screens: acc/vouchers, acc/payments, acc/coa
- Contra F4, Payment F5, Receipt F6, Journal F7, Sales F8, Purchase F9, Credit note Ctrl+F8, Debit note Ctrl+F9. They open from anywhere.
- Ctrl+A saves (accept). Alt+2 duplicates the open voucher. Ctrl+R repeats the last narration.
- Posted vouchers cannot be edited; cancel or reverse them and enter a new one. This keeps the books auditable.
- Ledgers are in [Chart of accounts](#/acc/coa). Alt+C in a ledger box creates a new ledger; Alt+A alters it.
- All vouchers are listed in [Vouchers](#/acc/vouchers).

## Accounts reports
keys: D then T, D then B, D then P, D then D, D then A then L
screens: acc/tb, acc/ledger, acc/daybook, acc/pl, acc/bs, acc/party, acc/ageing, acc/vat, acc/tds, acc/bank, acc/budget
- Trial balance (T), Balance sheet (B), Profit & loss (P), Day book (K or D D), Ledger (L), Party statement, Ageing, VAT books, TDS register, Bank reconciliation, Budget vs actual.
- Gateway letters work like Tally: press the letters on a screen (not inside a box).
- [Integrity checks](#/acc/integrity) look for unbalanced or unusual entries.

## Equipment: register, logsheets, maintenance, repairs
keys: Alt+F11, F10 then L
screens: eq/register, eq/books, eq/logs, eq/maint, eq/wo, eq/history, eq/hire, eq/kpi
- Machines are in [Register](#/eq/register), each with its outputs (bucket, breaker …) and rates.
- [Monthly logsheets](#/eq/books) (Alt+F11) are built from the DPR machine hours; one sheet per machine and output.
- [Maintenance](#/eq/maint) holds the service plan by hours or days and shows what is due.
- [Work orders](#/eq/wo) record breakdowns and services. "Repair record" adds parts, labour, external cost, workshop, parts replaced and cause.
- [Repairs & history](#/eq/history) shows the fleet and the full maintenance and repair history of each machine; repairs done earlier can be entered there.
- [Hired equipment](#/eq/hire) and [Performance](#/eq/kpi) show hire bills, availability and utilisation.

## Plant: crusher, batching, production runs
keys: Alt+F10
screens: pl/register, pl/mix, pl/runs, pl/report
- Production runs (Alt+F10) consume materials from the mix design and add the product to stock.

## Fixed assets and depreciation
keys: Ctrl+F10
screens: fa/register, fa/dep, as/register
- [Capital register](#/fa/register) holds assets; [Depreciation run](#/fa/dep) posts depreciation; tax depreciation and the PPE note are in the same module.

## KPI dashboard
screens: p/kpi
- [KPI dashboard](#/p/kpi): stock accuracy, stock-outs, turnover and days on hand, dead and slow stock, issue and GRN time, requisition fulfilment, on-time delivery, rejections, order accuracy, wastage, budget variance, loss, return to store; finance and contract figures. Click a figure to open its screen.

## Lists: tick, filter, hide, print, export
keys: Space, Ctrl+Space, Shift+Space, Alt+F12, Ctrl+F12, Alt+R, Alt+U, Alt+S, Alt+P, Alt+E, Alt+D, Enter
- In any list: ↑ ↓ move, Enter opens, Space ticks a row, Ctrl+Space ticks all.
- Alt+F12 filters on conditions; Ctrl+F12 picks values to show.
- Alt+R hides rows, Alt+U / Alt+S bring them back.
- Alt+P prints and Alt+E exports the ticked rows (or the whole list). Alt+D deletes ticked rows (administrator, with a reason).

## Norms, rate books and item rates (DoR, DUDBC, electrical, sanitary)
Resources & rates holds the official norm books: DoR Norms for Rate Analysis of Road and Bridge Works 2075, the DUDBC building (civil) norms, and the Electrical and Sanitary rate analyses 2079/80 - about 1,740 norms, read from the published books.
- Norms library (#/rp/norms): open a norm to see its labour, material and equipment lines. Norms marked "Check against book" had text that could not be split cleanly; compare them with the printed page. Shipped norms are locked - use "Copy to edit" to make a company version.
- Rate books (#/rp/books): "Market reference 2083/84 (Kathmandu)" holds current market prices (labour, cement, rod, sand, aggregate, brick, fuel from published 2026 prices; the rest are BuildCore estimates, marked as such). "Electrical & sanitary rate analysis 2079/80" holds the rates printed in those books. Make your own book for your district (DRC rates) and enter or copy the rates.
- Item rates (#/rp/items): every norm priced with the book you choose, with overhead & profit (15%) and VAT (13%). Flags show missing rates, estimated rates and norms to check. Export to Excel.
- Rate analysis (#/rp/ra): one item in full, with cartage leads, saved against a BOQ item.
Percentage lines in a norm (tools 3% of labour, formwork 4% of the cost) use the code L, M, E, LM or LME to say what the percentage is taken on.

## Site mode and site packs (sending site work to head office)
Site mode (#/site) shows big buttons for the work done at site. Press "Choose what is here" to pick them yourself: DPR, requisition, material issue, goods received, return, transfer, stock count, purchase request, local purchase bill, equipment log, breakdown, production run, test request, events, tasks, measurement - or ANY other screen of BuildCore (search it in "Any other screen"). An administrator can save the choice "For everybody"; each user can still choose their own. The same buttons appear on Today.
Sites without internet send their work in a site pack:
- At site: Site mode (or Administration > Site packs) > pick the dates and tick what goes in the pack > Make the pack file. Send the .bcpack file by pen drive, e-mail or phone. Only finished records go; drafts stay at site.
- At head office: Administration > Site packs > Load a pack > Check the file > Load these records. Records are matched by code (material, store, vendor, BOQ item, activity, machine, PO number) and loaded once only - loading the same file again changes nothing.
- DPRs arrive as "submitted"; issues, goods received, returns, transfers, stock counts, purchase bills and production runs arrive as drafts. Check and post them at head office so stock and accounts move in the head-office books. Materials and vendors made at site are added at head office and listed so you can check them.
- Give each computer its own short code first (Administration > Remote access), e.g. HO and the project code.

## Licence keys (activating BuildCore on a computer)
Every computer that runs BuildCore itself needs a licence key made for that computer. Browsers that use another computer's BuildCore over the office network need no key.
- On a new computer BuildCore opens on "Activate BuildCore on this computer". It shows a request code (like X3APG-KLC7M-QSRDL-3TBJA). Send the code to the administrator.
- The administrator makes the key on the admin computer - the only computer holding the master key: Administration > Licence keys > Make a licence key. Type the request code, who it is for, valid until (blank = no end), users allowed (0 = no limit) and the master password, then Make the key. Copy the key or save it as a .lic file and send it back.
- On the computer: paste the key (or load the .lic file) and press Activate. To renew or change a licence later: Administration > Licence keys > Enter a new key.
- A key opens only the computer it was made for. If Windows is reinstalled the request code changes and a new key is needed.
- Installations that already had data when this was added get 15 days to enter their key; a yellow note at the bottom shows the days left.
- Admin computer: load the master key file once (Administration > Licence keys > Make this the admin computer, or on the activation screen "This is the admin computer") and choose a master password. Keep the original master key file on a pen drive in a safe place.

## Decision centre (figures for decisions)
Dashboard > Decision centre (#/dc) answers the questions that decide whether a contractor makes money, from your own records:
- Portfolio radar: every running project scored 0-100 (Critical, At risk, Watch, Healthy) with the reasons - progress against time gone, days without a DPR or an IPC, certified bills unpaid, mobilisation advance not recovered, open NCRs, lost-time injuries, guarantees and insurance running out. Open it every week; act on Critical and At risk first.
- Client payments: each client's real days to certify and to pay, learnt from your IPCs and receipts, graded A to E, what is outstanding and the interest a late payment costs. "Use this client's real days in the cash forecast" puts them into the project's cash terms.
- Bid decision: go / no-go (bid capacity, licence class, work in hand, health of the jobs in hand, client's payment record, cash needed) and a bid price simulator. It uses your competitors' past bids (Commercial > Bids & markup) to work out the chance of winning and the expected profit at each price, for the "closest to the average of the bids" award rule of the 2083 procurement amendment or the lowest-bid rule. Check the rule and the 70% floor in each bid document.
- Bid capacity: A x N x M - B from your turnover by fiscal year (add years before BuildCore in Company profile) and the work still to do on contracts in hand.
- Price adjustment: the contract's escalation formula, the price indices by month, the adjustment for every IPC, and a claim in Events & claims.
- Sub-contractors: man-days, bills, payments, safety and SSF / bank / insurance of their workers, scored.
- Benchmarks: delay causes across all projects (the few causes that take most of the hours), weather lost by month, productivity against the standard, and building cost per sq ft from your own jobs.
- Company profile: the kind of company (home builder, small, medium, large contractor, client side) decides which screens the menus show; "Show all screens" at the bottom left shows everything.

## House and small job estimate
Dashboard > House & small job estimate (#/dc/house): floor area per storey, storeys and quality give a first estimate in a minute. Cement, steel, bricks, sand and aggregate come from rules of thumb per sq ft (changeable) priced from your rate book; labour, finishing and services are shares of the total. It also gives the stage payment plan for the client. "Make it a project" creates the project with one BOQ line per stage so the house is billed by stage; give finished houses their built-up area (Decision centre > Benchmarks) and your own cost per sq ft appears next to every new estimate.

## Workers and safety
Site work > Workers & safety (#/hs):
- Workers: each worker with trade, sub-contractor, SSF number, bank account, accident insurance (Labour Act: at least Rs 7 lakh) and skill certificate; missing items are marked. Paste many from Excel.
- Incidents: near miss, first aid, medical, lost-time injury, fatality, property and environmental, with cause, days lost, actions and insurance claim. A lost-time injury makes an investigation task.
- Safety figures: man-hours from the DPR labour, LTIFR, TRIR, severity, days since the last lost-time injury, causes and open actions, per project.

## My work (your inbox) and the simpler screens
Dashboard > My work (#/mywork) lists everything waiting for you - tasks, issues to fix or to check, RFIs to answer or close, meeting actions, submittals due, serious incidents - late items first. The Modules screen shows the same count and a Quick entry row (the buttons chosen for Site mode). "+ New" now also has Issue / snag, RFI, Inspection, Meeting minutes and Drawing.
Short forms: long forms show the main fields first and keep the rest under "More details". Switch it off or on with the "Short forms" tick on My work.

## Drawings (register, revisions, issues on the sheet)
Site work > Drawings (#/f/drawings): add each drawing with its number, title, discipline, revision and the PDF or image file. Adding the same number with a new revision supersedes the old one by itself, and its open issues move to the new sheet. Click a drawing to view it inside BuildCore (zoom, pages); "Add issue on the sheet" then click the spot to pin an issue there. History shows every revision and its file.

## Issues and punch list
Site work > Issues & punch list (#/f/issues): quality problems, safety observations, snags before handover, design problems and warranty defects after handover. Say what is wrong, where, who fixes it and by when; add photos after saving. The fixer marks it "Being fixed" and "Fixed - ready to check"; the person who checks it closes it. Late items are red. Anyone on the project can report an issue.

## RFIs (requests for information)
Site work > RFIs (#/f/rfis): ask the engineer or designer in writing - subject, question, drawing, who must answer and by when. Record the answer, mark cost or time impact, and "Make an event" turns an answer that changes cost or time into an event (then a variation or claim). Print an RFI to send it. The Quality dashboard shows how many days each party takes to answer.

## Meetings and minutes
Site work > Meetings (#/f/meetings): start a site progress, client or safety meeting; the open actions of the last meeting of the same kind are carried forward. Write points, decisions and actions with who and by when - an action given to a BuildCore user becomes a task in their My work. Print the minutes.

## Inspections (check lists)
Site work > Inspections (#/f/inspections): pick a form - concrete pour card, excavation safety, scaffold, weekly safety walk, masonry and plaster, house handover - or make your own (one check per line). Tap Pass / Fail / N/A for each check. Every Fail becomes an issue by itself, given to the sub-contractor chosen.

## Quality dashboard and client progress report
Site work > Quality dashboard: issues opened and closed each week, who has open issues, inspection results and RFI answer times. Site work > Client progress report: a plain report for the client or house owner written from the DPRs, photos, issues and bills of the period - change the words, then print or copy it.

## Machine hire rate sheet (DoR method)
Resources & rates > Machine hire rates (DoR) (#/rp/hire): the hourly hire charge of a machine = ownership (depreciation (P - S) / N, interest, insurance, tax, storage, divided by working hours a year) + operating (repair RF x P / life hours, servicing SF x P / life hours, fuel SFC x hp x load factor x time factor x diesel price without VAT, tyres, wear items) + crew (daily wage x 30 / 208 per hour). This is the method of the DoR guideline for equipment ownership and operating cost; the DoR norms say the hire charge includes ownership, fuel, crew and maintenance. 25 DoR sample machines are ready - their purchase prices are the 2077 examples, so enter today's quotation first. Diesel and wages come from the chosen rate book. "Put into rate book" prices the E-... resource used by the norms; "Make rate card" costs your own machine's DPR and logsheet hours. Excel and print are on the page.

## Contract administration
Commercial > Contract administration (#/ca): what the contract needs now - letters waiting for our reply, notice clocks (time bars) running, bonds and insurance to extend, events without a notice, variations waiting, contract register items and transmittals awaiting reply.

## Correspondence register (letters in and out)
Commercial > Correspondence register (#/ca/letters): log every incoming letter (their reference, received date, who must act, reply-by date) and write outgoing letters with a register number made by BuildCore (e.g. RD-12-OUT/2083-84/0001). Reply links the answer to the letter; the whole exchange shows together. Drafts are ready for a notice of claim, extension of time request, request for instruction, notice of variation, payment reminder and acknowledgement - read and change them before sending. Attach the scan, print on letterhead, copy to a distribution list. The page shows how many days each side takes to answer.

## Notices and time bars
Commercial > Notices & time bars (#/ca/timebars): start a clock when something happens - choose the clause and the date you became aware; BuildCore shows the last day for the notice and, for a claim, the detailed claim. The outgoing letter written for it stops the clock (late ones are marked). The clause library has FIDIC 1999 and 2017 time limits as a start; add your own contract's clauses because Particular Conditions and PPMO documents can change the days.

## Bonds, guarantees and insurance
Commercial > Bonds, guarantees & insurance (#/ca/securities): performance security, advance payment and retention guarantees, bid security, CAR, third-party, workers and vehicle insurance - amount, bank or insurer, expiry. Expiry within 45 days is flagged and shows in My work; every extension, reduction and release is kept in the history.

## Discussions, mentions and inbox
Site work > Discussions (#/cm): talk about a problem or decision where the whole team can see it; write @username to call someone in - they get it in the bell at the top and in My work. Discuss buttons on letters and documents open a discussion on that record. Overview > Inbox & mentions (#/inbox) lists mentions, replies, letters given to you, reviews and transmittals. Project directory & lists (#/cm/directory): outside people (client engineer, consultant, suppliers) and distribution lists used for copies.

## Document control, reviews and transmittals
Site work > Document control (#/dm): folders for each project (made for you the first time), document numbers made from a pattern such as {P}-{DISC}-{TYPE}-{SEQ} (RD-12-STR-DRG-0001), revisions with files - the new one supersedes the old. Send for review to one or more people (all together or one after another); each answers A approved, B approved with comments, C revise and resubmit or D rejected, and the worst answer is the result. Transmittals (#/dm/transmittals) record which revision went to whom and why, with a printable cover sheet and the date it was acknowledged. Export the register to Excel.

## Import goods received (GRN) from Excel
Store & inventory > Import GRNs from Excel (#/inv/grnimport), or "Import from Excel" on the Goods received list. Download the sample sheet: one row per material, and all 15 columns are required - GRN Date, Project Code, Store, Vendor Name, Vendor PAN/VAT No, Vendor Phone, Vendor Address, Challan/Bill No, Vehicle No, Material Code, Material Name, Unit, Received Qty, Accepted Qty, Rate (excl. VAT). Rows with the same date, project, store, vendor and challan become one GRN. A vendor not in BuildCore is created (found first by PAN, then by name); a new material code is created with its name and unit. Dates may be AD or BS. Choose a date range to take only those rows. "Check the sheet" runs everything and undoes it so you see every problem first; "Import" saves and posts (or leaves drafts). A challan with a bad row is held back whole; a challan already in BuildCore is skipped, so the same sheet can be imported again after adding rows. A GRN dated in a locked period is refused with the reason.

## Shortcut keys and your own shortcuts
keys: F1, Ctrl+/
- F1 opens Help: the assistant, the shortcut key directory and your own shortcuts. Ctrl+/ opens the shortcut directory directly.
- My shortcuts: choose a key (for example Ctrl+Alt+G or Alt+1) and what it does: open a screen, start a new entry (GRN, payment, DPR …), run a command (calculator, switch company, find a screen) or type a saved text into the box you are in (for example a standard narration).
- Your shortcuts are saved with your user, so they work on any computer. An administrator can share a shortcut with everyone.
- If you pick a key that BuildCore already uses, your shortcut replaces it for you; BuildCore warns first.

## Configure and screen size
keys: F11, F12, Alt+Z
- F11 opens company settings; F12 configures dates (AD/BS), tick boxes, gateway letters and screen size; Alt+Z changes the screen size.

## Calculator
keys: Ctrl+N
- Ctrl+N opens the calculator. Enter works it out; Ctrl+Enter puts the result into the box you were in.

## Users and roles
screens: admin/users
- Roles decide what a user may view, edit and approve: admin, project manager, site engineer, quantity surveyor, accountant, storekeeper, procurement officer, equipment manager, viewer.
- Users are added in [Users](#/admin/users).

## Backup and restore
screens: admin/backup
- BuildCore makes a daily automatic backup. [Backup & restore](#/admin/backup) makes one now, downloads it, or restores one (the current data is backed up first).
- Updates and setups also back up the data before changing anything.

## Several computers and the office network
- One computer keeps the data; others connect to it: Team menu › Share this computer with the office network on the main computer, then Team › Connect to BuildCore on another computer on the others. Across offices use a VPN such as Tailscale.
- Do not share the data folder through Google Drive or similar sync: the database can be damaged. Use them only for backups.
- Site packs ([Site packs](#/admin/sync)) carry work from a site without a connection.

## Copilot: ask for a report in your own words
screens: copilot
- [Copilot](#/copilot) › Ask for a report: type what you want to see, e.g. "cement issued per site last month", "diesel per machine this month", "purchase orders late for delivery". Copilot writes the query, BuildCore runs it and shows a table (and a chart when useful).
- It only reads, and only what your role may see. The query is shown under the report.
- "Change it…" refines the report (e.g. "only Headworks", "by month"). "Save as my report" keeps it in My reports; saved reports run again any time, even with the AI off. An administrator can share a report with everyone.
- Excel downloads the table; Print prints it.

## Copilot: write letters, notices and reports
screens: copilot
- [Copilot](#/copilot?tab=write) › Write: choose what to write (letter to client or engineer, letter to supplier or subcontractor, notice of delay / claim / variation / extension of time, monthly progress report text, minutes, summary), the contract and the language (English or Nepali), and say what it should say.
- Copilot uses the contract, its approved conditions (from Contract documents) and BuildCore's figures. Facts it does not have come as [placeholders].
- Edit the text, "Change it…" (shorter, more formal …), Save draft, download as Word, Print or Copy. Drafts are in My drafts.
- "Also use what is on my last screen" lets it use the screen you were on (for example a DPR or a ledger).

## Explain this screen
- In Help (F1), tick "Let the assistant see what is on my screen" or click "Explain this screen": the assistant reads the screen you are on and explains the figures or answers your question about them.

## Extra fields (your own fields)
screens: m/fields
- [Extra fields](#/m/fields) adds your own fields to materials, machines, vendors / clients, projects, contracts, staff and BOQ items - like Tally's user-defined fields (for example "Brand", "Country of origin", "Insurance policy no.", "Operator licence expiry").
- An administrator adds the fields ("Add or change fields…"): text, number, date, choice from a list, or yes/no.
- Fill them in the grid: type in a cell and it is saved when you leave it. Excel downloads the list. Copilot reports can use the extra fields.

## AI assistant settings
screens: admin/ai
- An administrator switches the AI on in [AI settings](#/admin/ai): Claude (cloud, needs internet only while asking; an API key from the Anthropic Console) or a local AI on this computer or network (an OpenAI-compatible server such as Ollama).
- "Let the assistant look up figures" allows answers with live figures (stock, contracts due, machines, approvals); it only reads and only what the user's role can see.
- With the AI off, Help still searches this guide.
- Document text and questions are sent to the AI provider when the cloud AI is used. Switch it off for confidential companies.

## When something does not work
- "BuildCore is busy": another task is running; wait a minute. If it stays, close BuildCore and open it again.
- A blank or frozen window: View › Reset the window (keeps your data), or View › Open BuildCore in the web browser.
- "Your role cannot …": ask an administrator to change your role.
- "Period locked": the date is in a locked month or closed year; ask the accountant.
- Errors are written to error.log (Help › Open error log); send it to support.


## Universal daily progress report (2.25)

**Where:** Work › Daily progress (DPR). The first tab is the DPR list you know; the new tabs follow it.

**Filling a DPR.** Press *New DPR*. The smart form opens in steps: basics and the executive summary, work done, manpower and equipment, problems, the project's own sections, photos and the next-day plan. Only what applies to the project is shown; *Show all sections* reveals advanced ones. Changes are kept on this computer until you save ("Not yet saved"), so a closed window or a lost connection does not lose the day's report. *Full form (classic)* opens the earlier form for the same DPR.

**Reported and accepted quantities.** The site enters the quantity done today (reported). The QS or engineer presses *Accept quantities* and enters what is accepted, with a note where it differs. Beyond the approved scope (contract quantity plus approved variations) an approver must give a reason. Progress follows reported quantities unless the project's set-up says *accepted quantities from* a date.

**Workflow.** Draft → Submitted → Checked → Approved, then Locked. A report can be *Returned for correction* (with a comment) or *Rejected* (with a reason; *Revise* takes it back to draft). Approving keeps a revision; reopening an approved report keeps the version before the amendment. Locked reports can only be unlocked by an approver, with a reason.

**Issues.** A problem typed on a DPR becomes an issue in the register. Next day, pick it as a *continuing issue*: the register counts the days and hours lost and keeps the first date, impact, action, decision required and whether it matters for a claim.

**Set-up.** *Work fronts & set-up* holds packages and work fronts, the project's templates, which sections and fields show, and the progress basis. *Templates & fields* edits templates: sections of fields, repeating tables and extra columns on the work rows, with types such as number, dropdown, date, chainage, BOQ item or photo, required fields, limits, conditions (show only if) and fields only some roles may change. Publishing makes a new version for new DPRs; existing DPRs keep theirs.

**Reports.** *DPR reports* prints or exports to Excel the daily, weekly and monthly summaries and the activity, work front, manpower, equipment, material, quality, safety, issue, delay, photo and custom-field reports. Save a layout to reuse it.


## Billing, receivables, payables and payment control (2.26)

**Billing pipeline.** Commercial › IPC billing › *Billing pipeline & collections* shows each IPC as prepared, submitted, under review, certified, overdue, partly paid or paid, with the dates. Click an IPC to record who is responsible, the next action and its date, the consultant's comments, the expected payment date and any reason for delay; every change and note is kept in its history. The first two cards (work done not measured, measured not billed) are estimates at BOQ rates for planning; only a certified IPC is billing.

**Receivables.** Accounts › Ageing › *Receivables: five buckets* shows per project: work not yet billed, IPCs submitted and awaiting certification, certified but not yet due, overdue (1-30, 31-60, 61-90, 90+ days) and retention held, with the dates retention can be released under the contract terms. *Collection actions* lists the next step for each item (complete measurements, prepare or submit an IPC, obtain certification, follow up or escalate payment, request retention release), the person responsible and the target date. Record each call or letter as a follow-up, with the next date and any promised payment.

**Payables.** *Payables register* lists open supplier, subcontractor and hire bills, wages payable, VAT and TDS to deposit (by the 25th of the next month; changeable) and loan and equipment instalments, by due date. Purchase-order commitments and retention held from suppliers are shown for information. *Request payment* starts a payment request from any line.

**Payment requests.** Accounts › Payments & receipts › *Payment requests*. A request is checked step by step: documents, accounts, cash, approval, then payment, and it shows as reconciled once the bank line is cleared. The person who asked cannot approve. Tax, wage, safety and contractual payments proposed after their due date need a reason, and the approver writes a note. *Pay now* makes the normal payment (choose the bank, mode, reference and TDS); *Link payment already made* connects a payment or voucher, for example a tax deposit. *Payment plan* puts requests and dues in order of obligation and date against the cash and bank balance less the reserve, and shows any shortfall. It only proposes; people approve and pay. *Payment-control settings* sets the reserve, the deposit day, strict separation of duties and which right each step needs.

**Financial data checks.** Accounts › Integrity checks › *Financial data checks* reads the books and reports errors and warnings: unbalanced vouchers, opening balances, debtors and creditors against open invoices (company and by project), lines without a project, internal billing that does not net to zero, duplicate bills, payments and cheque references, bank entries not reconciled, certified IPCs without a matching invoice, documents without vouchers and items waiting in the posting queue. Click a row to see the items.


## 13-week cash forecast (2.27)

Accounts › Cash forecast & ratios › *13-week cash forecast* starts from today's cash and bank balance and shows each of the next 13 weeks (Monday to Sunday): opening, money in, money out, closing, the reserve and restricted funds kept back, and what is available to spend.

**Where the lines come from.** Receipts promised by the client in a collection follow-up; certified bills on their expected or due date; IPCs awaiting certification (certification days plus payment days); retention due for release; overdue receivables with no promised date (assumed collected 30 days from today, changeable). Payments: payment requests on their proposed date; the part of each bill, wage, VAT and TDS balance not yet requested, on its due date; loan and equipment-finance instalments; purchase orders still to be delivered. Future work and its costs come from each project's schedule and terms, and head-office overhead from its budget, spread over the weeks of each month. Anything already overdue is shown in week 1.

**Confidence.** Each line is marked confirmed, likely, estimate or uncertain. The prudent closing counts only confirmed and likely receipts, against every payment.

**Scenarios.** Base, client receipts 15, 30 or 45 days late, costs 10% over, or your own delay and overrun. The table below the grid compares them: the lowest closing, its week, the first week with a funding gap and the largest gap.

**Items entered by hand** add money no document shows yet: a loan or overdraft drawdown, equity, a land or machine purchase or sale, a tax payment. Financing items are never delayed by the late-receipt scenarios. **Restricted funds** are amounts in the bank that cannot be spent between two dates (margin money, escrow, a minimum balance). The general reserve is set in Payments & receipts › Payment plan › Payment-control settings.

**Forecast vs actual.** *Save forecast* keeps the forecast as it is today. *Forecast vs actual* compares a saved forecast, week by week, with the cash and bank money that actually moved, and shows the share of forecast receipts achieved.


## Cost to complete and progress to cash (2.28)

Commercial › CVR and forecast › *Cost to complete & profit* takes each cost code's forecast cost to complete and compares it with what is already ordered and not yet received (open purchase-order lines without VAT, and subcontract work not yet billed). The larger of the two is the remaining cost, so an order is never counted twice. Final cost = cost to date + remaining. Orders with no cost code are added where they exceed the remaining cost. Below the gross profit come head-office overhead (the *overhead %* setting, or when it is blank, the next 12 months' overhead budget over the last 12 months' income) and financing (the interest on the project's peak cash need from the 12-month cash budget). Unapproved variations and claims are listed as potential, never as revenue. Where a code has no budget or no forecast the figure shows as *Forecast incomplete*, not as zero.

*Resources vs plan & cost* compares the man-days and machine hours the rate analysis allows for the quantity done with those worked on the DPRs, and lists each machine's use, fuel, repairs and hire, with recurring breakdowns, low use, idle hire and fuel above norm.

Commercial › CVR, all projects › *Profit after overhead & financing* shows the same for every project you can see. *Cost to complete settings* sets the overhead %, the productivity and behind-plan limits, the breakdown count and the idle-hire limit.

Work › Daily progress (DPR) › *Progress to cash* follows each BOQ item from planned to reported (site), accepted, measured, billed, certified and received, flags work done but not measured, measured but not billed and billed beyond the contract, and estimates how many days the shortfall holds back the bill and the cash.

Procurement › Purchase orders › *Approval check* lists orders waiting for approval. Opening a draft or pending order shows, before approval, the stock on the project and in all stores, other open orders, the use scheduled over 30 days, the payment date from the credit terms, the budget left after the order and, for people with accounts view, the company cash in that week. Activities that use the materials are listed with the latest delivery date; for activities already running this is when the stock on site runs out. It is a check only: approving or holding the order stays with the approver.


## Financial command centre, alerts and reports (2.29)

**Command centre › Financial command centre** puts the company's money on one page: cash and bank today, the reserve and restricted funds, what is available to spend, the lowest point in the 13-week forecast, the funding gap, receivables (overdue, not yet due, awaiting certification, measured not billed, done not measured, retention), payables due in 7, 30 and 90 days, IPCs waiting at each stage, each project's profit after overhead and financing with its cash in and out to date and its funding need, open purchase commitments, loans and advances, the priority alerts and how many each person owns. Choose a view (director, finance, accounts, project manager, procurement, stores, site); your role chooses one for you. Sections your role may not see are left out by the engine, not hidden on the screen. Every figure opens the records behind it. Where a figure cannot be worked out it says *Not available* instead of showing zero.

**Action centre › Financial alerts** lists the alerts BuildCore raises from the records: cash below the reserve or below zero, payroll, tax and loan payments due, receipts overdue, IPCs waiting, unbilled work, supplier bills due, orders above budget, material shortages, slow stock, idle equipment, cost overruns, profit fading, unapproved variations, the cash forecast drifting from actual, and late DPRs. Each alert has an owner, a target date, the basis (the figures it came from), the recommended next action and links to the records. The owner acknowledges it, marks it as being worked on, and resolves it with a note (it is not raised again for the days chosen). Directors, finance managers and project managers assign owners and dismiss alerts with a reason. When the target date passes, the alert moves up the escalation chain and the next person is told. When the condition goes away the alert is cleared, never deleted, and it reopens if the condition comes back. *Alert rules* sets the limits, owners, target days and escalation chains. Checks run on opening the screen when the last check is older than the setting (60 minutes), or with *Check now*.

**Accounts › Cash forecast & ratios › Funding gap & financing** works the funding gap week by week: cash needed for payments to date plus the reserve and restricted funds, less cash today, less confirmed and likely receipts to date; the largest value is the gap. The eight management actions follow in order (collect, measure and bill, resolve objections, time purchases, agree supplier terms, plan the payment schedule, reduce idle cost, then financing), each with the amount behind it. Financing options you enter are compared with *no financing* on lowest cash, weeks short, interest, fees and repayment dates. It is a comparison only: BuildCore does not borrow, post or recommend.

**Command centre › Report builder** builds a report from a dataset, a period, projects, columns, filters, up to two group levels and totals (sum, average, minimum, maximum, count). The DPR dataset includes the template's own fields. Print or save as PDF in portrait or landscape with your header and footer, or export to Excel. Save a report for yourself; finance managers can share one with everyone. The seven templates cannot be changed but can be saved under a new name. A report shows only the projects and figures your role may see.
