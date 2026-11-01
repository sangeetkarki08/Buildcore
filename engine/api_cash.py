"""
BuildCore 2.1 - cash and bidding, built into existing screens:

  Commercial > Cost & earned value   cost codes with committed cost and EAC (3.1), labour cost performance
                                     index LCPI (3.3), CPI/SPI control chart (3.4), project cash-flow
                                     forecast from the cost-loaded schedule and payment terms (3.10)
  Commercial > IPC billing           NFRS 15 contract accounting: transaction price with variations, claims,
                                     escalation and LD (highly probable flag), contract asset / liability,
                                     onerous contract provision, remaining performance obligations, retention
                                     and mobilisation-advance sub-ledgers (NFRS items 2, 3, 5, 6, 7, 20)
  Commercial > Bids & markup         bid register with competitors and hit rate (3.8), markup calculator
                                     with markup vs margin (3.7), overhead and profit split for rate
                                     analysis (6.4)
  Accounts > Budget vs actual        head-office overhead budget by category and month (3.6)
  Accounts > Cash forecast & ratios  company 12-month cash budget with loans, advance tax and sensitivity
                                     (3.11), financial ratios and months in backlog (3.12, NFRS 20)
  Accounts > Payments                NPR cash-payment limit check (NFRS item 8)
  Command centre                     cash position, peak-cash month, backlog, ratios, hit rate (6.10)
"""
import json
import math
from datetime import date, timedelta

from core import ApiError, EPS, audit, get, ins, need, now, num, q, q1, r2, r4, setting, today, upd, val
import core
import api_inventory as inv
import api_finance  # noqa: F401  (payment.create must be registered first)
from api_inventory import api as _register
import api_project as P
import api_sched as SCH
import sched_calc as SC

POSTED = "v.status IN ('posted','reversed')"
_READY = set()


def api(name, module=None, action=None):
    def wrap(f):
        def run(c, u, a):
            SCH.ensure(c)
            ensure(c)
            return f(c, u, a)
        run.__name__, run.__doc__ = f.__name__, f.__doc__
        _register(name, module, action)(run)
        return f
    return wrap


def ensure(c):
    try:
        key = c.execute("PRAGMA database_list").fetchone()[2] or id(c)
    except Exception:
        key = id(c)
    if key not in _READY:
        if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='bids'").fetchone() or \
                "cert_days" not in _cols(c, "projects"):
            init_cash(c)
        _READY.add(key)


SCHEMA = """
CREATE TABLE IF NOT EXISTS bids(id INTEGER PRIMARY KEY, no TEXT, date TEXT, client TEXT, title TEXT, work_type TEXT,
  location TEXT, ee REAL, our_cost REAL, our_bid REAL, markup_pct REAL, status TEXT DEFAULT 'preparing', winner TEXT,
  winning_bid REAL, project_id INTEGER, bid_security REAL, submission_date TEXT, remarks TEXT, created_by INTEGER);
CREATE TABLE IF NOT EXISTS bid_prices(id INTEGER PRIMARY KEY, bid_id INTEGER, bidder TEXT, price REAL, is_us INTEGER DEFAULT 0,
  responsive INTEGER DEFAULT 1, remarks TEXT);
CREATE TABLE IF NOT EXISTS oh_budget(id INTEGER PRIMARY KEY, fy INTEGER, category TEXT, account_id INTEGER,
  kind TEXT DEFAULT 'fixed', month INTEGER, amount REAL DEFAULT 0);
CREATE INDEX IF NOT EXISTS ix_ohb ON oh_budget(fy, category);
CREATE TABLE IF NOT EXISTS loans(id INTEGER PRIMARY KEY, name TEXT, lender TEXT, kind TEXT DEFAULT 'term', emi REAL DEFAULT 0,
  start_date TEXT, end_date TEXT, balance REAL DEFAULT 0, rate REAL, limit_amount REAL, remarks TEXT, active INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS cost_reviews(id INTEGER PRIMARY KEY, project_id INTEGER, boq_item_id INTEGER, class TEXT,
  revised_eac REAL, note TEXT, user_id INTEGER, ts TEXT);
CREATE TABLE IF NOT EXISTS provisions(id INTEGER PRIMARY KEY, no TEXT, project_id INTEGER, kind TEXT, title TEXT,
  date TEXT, amount REAL DEFAULT 0, probability TEXT, basis TEXT, status TEXT DEFAULT 'open', voucher_id INTEGER,
  reversed_voucher_id INTEGER, remarks TEXT, created_by INTEGER);
"""
COLUMNS = {
    "projects": {"cert_days": "REAL", "pay_days": "REAL", "ipc_cycle_days": "REAL", "retention_pct": "REAL",
                 "retention_release_pct": "REAL", "dlp_months": "REAL", "advance_pct": "REAL",
                 "advance_recovery_pct": "REAL", "vat_pct": "REAL", "tds_pct": "REAL", "supplier_credit_days": "REAL",
                 "labour_pay_days": "REAL", "subcon_pct": "REAL", "project_type": "TEXT", "pm_name": "TEXT",
                 "contract_type": "TEXT", "sec26": "INTEGER", "performance_obligations": "TEXT", "jv_share_pct": "REAL",
                 "jv_partners": "TEXT", "mgmt_hours": "REAL", "revenue_method": "TEXT"},
    "variations": {"highly_probable": "INTEGER", "est_value": "REAL"},
    "events": {"highly_probable": "INTEGER", "claim_value": "REAL"},
}


def _cols(c, t):
    try:
        return {r[1] for r in c.execute("PRAGMA table_info(%s)" % t)}
    except Exception:
        return set()


def _has(c, t):
    return bool(c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (t,)).fetchone())


def init_cash(c):
    c.executescript(SCHEMA)
    for t, cols in COLUMNS.items():
        have = _cols(c, t)
        for k, typ in cols.items():
            if have and k not in have:
                c.execute("ALTER TABLE %s ADD COLUMN %s %s" % (t, k, typ))
    for k, v in (("cash_interest_pct", "12"), ("cash_min_balance", "5000000"), ("cash_limit_npr", "25000"),
                 ("advance_tax_estimate", "0"), ("ra_overhead_pct", "10"), ("ra_profit_pct", "5"),
                 ("ratio_targets", json.dumps({"current": 1.3, "quick": 1.0, "debt_equity": 1.5, "collection_days": 60,
                                               "gross_margin": 12, "net_margin": 5, "backlog_months": 12}))):
        c.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", (k, v))
    for f in ("highly_probable", "est_value"):
        if f not in P.REGISTERS["variations"][2]:
            P.REGISTERS["variations"][2].append(f)
    for f in ("highly_probable", "claim_value"):
        if f not in P.REGISTERS["events"][2]:
            P.REGISTERS["events"][2].append(f)
    P.REG_NUM.update({"highly_probable", "est_value", "claim_value"})


def _reg_fields():
    for f in ("highly_probable", "est_value"):
        if f not in P.REGISTERS["variations"][2]:
            P.REGISTERS["variations"][2].append(f)
    for f in ("highly_probable", "claim_value"):
        if f not in P.REGISTERS["events"][2]:
            P.REGISTERS["events"][2].append(f)
    P.REG_NUM.update({"highly_probable", "est_value", "claim_value"})


_reg_fields()


def _set(c, k, v):
    c.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (k, str(v)))


def _f(x, d=0.0):
    try:
        return float(x) if x not in (None, "") else d
    except (TypeError, ValueError):
        return d


# ───────────────────────── months ─────────────────────────
def mkey(d):
    return d.isoformat()[:7] if isinstance(d, date) else str(d)[:7]


def month_start(k):
    return date(int(k[:4]), int(k[5:7]), 1)


def add_months(k, n):
    y, m = int(k[:4]), int(k[5:7]) + n
    y += (m - 1) // 12
    m = (m - 1) % 12 + 1
    return "%04d-%02d" % (y, m)


def month_end(k):
    return (month_start(add_months(k, 1)) - timedelta(days=1))


def role_balance(c, role, pid=None, to=None):
    w = "a.role=? AND " + POSTED
    p = [role]
    if pid:
        w += " AND l.project_id=?"
        p.append(pid)
    if to:
        w += " AND v.date<=?"
        p.append(to)
    b = val(c, "SELECT SUM(l.debit-l.credit) FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id JOIN accounts a "
               "ON a.id=l.account_id WHERE " + w, p)
    if not pid:
        b += val(c, "SELECT SUM(opening_balance) FROM accounts WHERE role=?", (role,))
    return b or 0.0


def terms(c, p):
    g = lambda k, d: p.get(k) if p.get(k) is not None else d
    return {"ipc_cycle_days": g("ipc_cycle_days", 30), "cert_days": g("cert_days", 21), "pay_days": g("pay_days", 28),
            "retention_pct": g("retention_pct", 5), "retention_release_pct": g("retention_release_pct", 50),
            "dlp_months": g("dlp_months", 12), "advance_pct": g("advance_pct", 10),
            "advance_recovery_pct": g("advance_recovery_pct", 10), "vat_pct": g("vat_pct", 13), "tds_pct": g("tds_pct", 1.5),
            "supplier_credit_days": g("supplier_credit_days", 30), "labour_pay_days": g("labour_pay_days", 7),
            "subcon_pct": g("subcon_pct", 0)}


# ───────────────────────── project cash flow (3.10) ─────────────────────────
def _activity_flows(c, pid, basis="early"):
    """Remaining revenue and cost of each activity spread over its working days: {month: {rev, lab, mat, eqp, oth}}"""
    cals = SCH.load_cals(c)
    dd = SCH.q1(c, "SELECT data_date FROM projects WHERE id=?", (pid,))
    ddo = date.fromisoformat((dd or {}).get("data_date") or today()).toordinal()
    ev = P.project_evm(c, pid, today())
    margin = (ev.get("tender_margin") or 8) / 100.0
    acts = q(c, "SELECT * FROM activities WHERE project_id=? AND actual_finish IS NULL", (pid,))
    boq = {b["id"]: b for b in q(c, "SELECT * FROM boq_items WHERE project_id=?", (pid,))}
    out = {}
    for x in acts:
        pq = x.get("planned_qty") or 0
        rem = max(pq - (x.get("actual_qty") or 0), 0)
        if rem <= EPS:
            continue
        b = boq.get(x.get("boq_item_id"))
        if not b:
            continue
        rate = b["revised_rate"] if b.get("revised_rate") is not None else b["rate"]
        rev = rem * (rate or 0)
        ub, parts = P.unit_budget(c, b["id"])
        if ub:
            cost = {k: rem * v for k, v in parts.items()}
        else:
            cost = {"other": rev * (1 - margin)}
        if basis == "late" and x.get("ls"):
            s, f = x["ls"], x["lf"]
        else:
            s, f = x.get("es") or x.get("planned_start"), x.get("ef") or x.get("planned_finish")
        if not s or not f:
            continue
        cal = SCH.cal_for(x, cals)
        wt = x.get("work_type") or ""
        so = max(date.fromisoformat(s).toordinal(), cal.start_up(ddo, wt))
        fo = max(date.fromisoformat(f).toordinal() + 1, so + 1)
        days = cal.workdays(so, fo, wt) or [so]
        n = float(len(days))
        for o in days:
            k = mkey(date.fromordinal(o))
            m = out.setdefault(k, {"rev": 0.0, "labour": 0.0, "material": 0.0, "equipment": 0.0, "other": 0.0})
            m["rev"] += rev / n
            for kk, vv in cost.items():
                key = kk if kk in ("labour", "material", "equipment") else "other"
                m[key] += vv / n
    return out, ev


def project_cash(c, pid, basis="early", months=None, extra_delay=0, overrun_pct=0.0, start_key=None):
    p = get(c, "projects", pid, "Project")
    t = terms(c, p)
    flows, ev = _activity_flows(c, pid, basis)
    k0 = start_key or mkey(date.today())
    cin, cout = {}, {}

    def add(d, bucket, cat, amt):
        k = mkey(d)
        if k < k0:
            k = k0
        b = bucket.setdefault(k, {})
        b[cat] = b.get(cat, 0.0) + amt
    over = 1 + overrun_pct / 100.0
    # work done but not yet billed goes in the first IPC
    unbilled = sum(max(0.0, (r["executed_qty"] - r["billed_qty"])) * r["revised_rate"] for r in ev["rows"])
    months_work = sorted(flows)
    bill = {}
    if unbilled > EPS:
        bill[k0] = bill.get(k0, 0) + unbilled
    for k in months_work:
        bill[k] = bill.get(k, 0) + flows[k]["rev"]
    adv_left = max(0.0, -role_balance(c, "client_advance", pid))
    ret_held = role_balance(c, "retention_receivable", pid)
    ret_new = 0.0
    last_work = max(months_work) if months_work else k0
    for k in sorted(bill):
        g = bill[k]
        paid_on = month_end(k) + timedelta(days=int(t["cert_days"] + t["pay_days"] + extra_delay))
        ret = g * t["retention_pct"] / 100
        tds = g * t["tds_pct"] / 100
        vat = g * t["vat_pct"] / 100
        rec = min(adv_left, g * t["advance_recovery_pct"] / 100) if adv_left > EPS else 0.0
        adv_left -= rec
        ret_new += ret
        add(paid_on, cin, "IPC receipts (net of retention, TDS, advance)", g - ret - tds - rec)
        add(paid_on, cin, "VAT collected on IPCs", vat)
        add(month_end(add_months(k, 1)).replace(day=25), cout, "VAT paid to IRD (net of input VAT)",
            vat - (flows.get(k, {}).get("material", 0) * over * t["vat_pct"] / 100))
        sub = g * t["subcon_pct"] / 100 * (1 - (ev.get("tender_margin") or 8) / 100)
        if sub > EPS:
            add(paid_on + timedelta(days=7), cout, "Subcontractors (pay when paid)", sub)
    # open invoices already raised
    for r in q(c, "SELECT id, payable, due_date, date, kind FROM invoices WHERE project_id=? AND status='posted'", (pid,)):
        bal = r["payable"] - inv.invoice_paid(c, r["id"])
        if bal <= EPS:
            continue
        due = r["due_date"] or r["date"]
        d = max(date.fromisoformat(due), date.today()) + (timedelta(days=int(extra_delay)) if r["kind"] == "sales" else timedelta(0))
        if r["kind"] == "sales":
            add(d, cin, "Invoices already raised (receivable)", bal)
        else:
            add(d, cout, "Bills already received (payable)", bal)
    # retention release
    comp = month_end(last_work)
    rel1 = comp + timedelta(days=int(t["cert_days"] + t["pay_days"] + extra_delay))
    total_ret = ret_held + ret_new
    if total_ret > EPS:
        add(rel1, cin, "Retention released", total_ret * t["retention_release_pct"] / 100)
        add(rel1 + timedelta(days=int(30.4 * t["dlp_months"])), cin, "Retention released", total_ret * (100 - t["retention_release_pct"]) / 100)
    # costs
    scale = 1 - t["subcon_pct"] / 100
    for k, m in flows.items():
        me = month_end(k)
        add(me + timedelta(days=int(t["labour_pay_days"])), cout, "Labour", m["labour"] * over * scale)
        add(me + timedelta(days=int(t["supplier_credit_days"])), cout, "Materials", m["material"] * over * scale * (1 + t["vat_pct"] / 100))
        add(me, cout, "Equipment running", m["equipment"] * over * scale)
        add(me, cout, "Site overhead & other", m["other"] * over * scale)
    keys = sorted(set(cin) | set(cout) | {k0})
    if months:
        keys = [add_months(k0, i) for i in range(months)]
    else:
        last = max(keys)
        n = 0
        keys = []
        while True:
            kk = add_months(k0, n)
            keys.append(kk)
            if kk >= last:
                break
            n += 1
    rate = _f(setting(c, "cash_interest_pct"), 12) / 100 / 12
    cum = 0.0
    rows = []
    fin = 0.0
    peak, peak_k = 0.0, None
    cats_in = sorted({x for b in cin.values() for x in b})
    cats_out = sorted({x for b in cout.values() for x in b})
    for k in keys:
        i = sum(cin.get(k, {}).values())
        o = sum(cout.get(k, {}).values())
        cum += i - o
        if cum < 0:
            fin += -cum * rate
        if cum < peak:
            peak, peak_k = cum, k
        rows.append({"month": k, "in": r2(i), "out": r2(o), "net": r2(i - o), "cumulative": r2(cum),
                     "in_detail": {x: r2(cin.get(k, {}).get(x, 0)) for x in cats_in},
                     "out_detail": {x: r2(cout.get(k, {}).get(x, 0)) for x in cats_out}})
    return {"project_id": pid, "code": p["code"], "terms": t, "rows": rows, "peak_cash": r2(-peak) if peak < 0 else 0.0,
            "peak_month": peak_k, "financing_cost": r2(fin), "categories_in": cats_in, "categories_out": cats_out,
            "advance_outstanding": r2(max(0.0, -role_balance(c, "client_advance", pid))),
            "retention_held": r2(ret_held), "basis": basis}


@api("cash.project", "commercial", "view")
def cash_project(c, u, a):
    """Monthly cash in and out for the rest of the project from the cost-loaded schedule and the payment
    terms; the peak cash requirement falls just before a receipt."""
    return project_cash(c, int(a["project_id"]), a.get("basis") or "early", None, _f(a.get("delay")), _f(a.get("overrun")))


@api("cash.terms_save", "commercial", "edit")
def terms_save(c, u, a):
    pid = int(a["project_id"])
    r = a.get("row") or {}
    data = {}
    for k in ("ipc_cycle_days", "cert_days", "pay_days", "retention_pct", "retention_release_pct", "dlp_months",
              "advance_pct", "advance_recovery_pct", "vat_pct", "tds_pct", "supplier_credit_days", "labour_pay_days",
              "subcon_pct", "jv_share_pct", "mgmt_hours"):
        if k in r:
            data[k] = num(r[k], k) if r[k] not in ("", None) else None
    for k in ("project_type", "pm_name", "contract_type", "performance_obligations", "jv_partners", "revenue_method"):
        if k in r:
            data[k] = r[k] or None
    if "sec26" in r:
        data["sec26"] = 1 if str(r["sec26"]) in ("1", "true") else 0
    upd(c, "projects", pid, data)
    audit(c, u, "save", "project_terms", pid, data)
    return True


# ───────────────────────── overhead budget (3.6) ─────────────────────────
OH_CATEGORIES = ["Head office salaries", "Office rent", "Vehicles & fuel (HO)", "Communication & IT", "Bid & tender costs",
                 "Insurance (HO)", "Audit, legal & professional", "Utilities", "Travel", "Depreciation (HO)",
                 "Bank charges & guarantees", "Other overheads"]


def fy_months(fy):
    """BS fiscal year (e.g. 2083 = 2083/84) -> 12 (label, AD start, AD end) from Shrawan to Ashad."""
    out = []
    for i in range(12):
        m = 4 + i
        y = fy if m <= 12 else fy + 1
        m = m if m <= 12 else m - 12
        try:
            s = SC.bs_to_ad(y, m, 1)
            e = SC.bs_to_ad(y, m, SC._lens(y)[m - 1])
        except (ValueError, KeyError):
            s = date(fy - 57, 7, 16) + timedelta(days=30 * i)
            e = s + timedelta(days=29)
        out.append((SC.BS_MONTHS[m - 1], s.isoformat(), e.isoformat()))
    return out


def current_fy():
    y, m, _ = SC.ad_to_bs(date.today())
    return y if m >= 4 else y - 1


@api("oh.get", "accounts", "view")
def oh_get(c, u, a):
    fy = int(a.get("fy") or current_fy())
    months = fy_months(fy)
    rows = {}
    for r in q(c, "SELECT * FROM oh_budget WHERE fy=? ORDER BY category, month", (fy,)):
        x = rows.setdefault(r["category"], {"category": r["category"], "account_id": r["account_id"], "kind": r["kind"],
                                            "budget": [0.0] * 12})
        if r["month"] and 1 <= r["month"] <= 12:
            x["budget"][r["month"] - 1] = r["amount"] or 0
    accs = q(c, "SELECT id, code, name FROM accounts WHERE type='expense' ORDER BY code")
    for x in rows.values():
        act = []
        for _l, s, e in months:
            if x["account_id"]:
                act.append(r2(val(c, "SELECT SUM(l.debit-l.credit) FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id "
                                     "WHERE l.account_id=? AND l.project_id IS NULL AND " + POSTED + " AND v.date BETWEEN ? AND ?",
                                  (x["account_id"], s, e))))
            else:
                act.append(0.0)
        x["actual"] = act
        x["budget_total"] = r2(sum(x["budget"]))
        x["actual_total"] = r2(sum(act))
        done = [i for i, (_l, s, e) in enumerate(months) if e < today()]
        x["budget_to_date"] = r2(sum(x["budget"][i] for i in done))
        x["variance_to_date"] = r2(x["actual_total"] - x["budget_to_date"])
        # trend: this year's actual run-rate projected over 12 months, variable costs scaled by volume
        run = x["actual_total"] / len(done) * 12 if done else x["budget_total"]
        x["projection_next_year"] = r2(run * (1 + _f(a.get("inflation"), 7) / 100))
    unmapped = q(c, "SELECT a.id, a.code, a.name, SUM(l.debit-l.credit) amt FROM voucher_lines l JOIN vouchers v ON "
                    "v.id=l.voucher_id JOIN accounts a ON a.id=l.account_id WHERE a.type='expense' AND l.project_id IS NULL AND "
                    + POSTED + " AND v.date BETWEEN ? AND ? GROUP BY a.id", (months[0][1], months[-1][2]))
    mapped = {x["account_id"] for x in rows.values()}
    return {"fy": fy, "fy_label": "%d/%02d" % (fy, (fy + 1) % 100), "months": [m[0] for m in months],
            "month_dates": [[m[1], m[2]] for m in months], "rows": list(rows.values()), "accounts": accs,
            "categories": OH_CATEGORIES, "unmapped_actuals": [x for x in unmapped if x["id"] not in mapped and abs(x["amt"] or 0) > 0.5],
            "total_budget": r2(sum(x["budget_total"] for x in rows.values())),
            "total_actual": r2(sum(x["actual_total"] for x in rows.values()))}


@api("oh.save", "accounts", "edit")
def oh_save(c, u, a):
    fy = int(a.get("fy") or current_fy())
    c.execute("DELETE FROM oh_budget WHERE fy=?", (fy,))
    for r in a.get("rows") or []:
        if not r.get("category"):
            continue
        vals = r.get("budget") or []
        if r.get("annual") not in (None, "") and not any(_f(v) for v in vals):
            vals = [_f(r["annual"]) / 12.0] * 12
        for i in range(12):
            v = _f(vals[i]) if i < len(vals) else 0.0
            ins(c, "oh_budget", {"fy": fy, "category": r["category"], "account_id": int(r["account_id"]) if r.get("account_id") else None,
                                 "kind": r.get("kind") or "fixed", "month": i + 1, "amount": r2(v)})
    audit(c, u, "save", "oh_budget", fy, {"rows": len(a.get("rows") or [])})
    return True


def oh_monthly(c, keys):
    """Overhead budget cash by AD month key (for the company cash budget); falls back to last 12 months actual."""
    out = {k: 0.0 for k in keys}
    have = False
    for fy in {current_fy(), current_fy() + 1}:
        for i, (_l, s, e) in enumerate(fy_months(fy)):
            amt = val(c, "SELECT SUM(amount) FROM oh_budget WHERE fy=? AND month=?", (fy, i + 1))
            if amt:
                have = True
            k = mkey(date.fromisoformat(s) + timedelta(days=15))
            if k in out:
                out[k] += amt or 0
    if not have:
        since = (date.today() - timedelta(days=365)).isoformat()
        tot = val(c, "SELECT SUM(l.debit-l.credit) FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id JOIN accounts a ON "
                     "a.id=l.account_id WHERE a.type='expense' AND l.project_id IS NULL AND " + POSTED + " AND v.date>=?", (since,))
        for k in out:
            out[k] = (tot or 0) / 12.0
    return out, have


# ───────────────────────── company cash budget (3.11) ─────────────────────────
ADVANCE_TAX = [(9, 0.40, "Poush"), (12, 0.30, "Chaitra"), (3, 0.30, "Ashad")]   # BS month, share, name [confirm]


@api("cash.company", "accounts", "view")
def cash_company(c, u, a):
    """Twelve months of company cash: every active project's cash flow, the head-office overhead budget,
    loan instalments and advance-tax instalments, from today's cash and bank balance. Sensitivity:
    IPC receipts late by N days, a cost overrun, and a new project starting in a given month."""
    n = int(a.get("months") or 12)
    delay = _f(a.get("delay"))
    over = _f(a.get("overrun"))
    k0 = mkey(date.today())
    keys = [add_months(k0, i) for i in range(n)]
    opening = role_balance(c, "cash") + role_balance(c, "bank")
    for acc in q(c, "SELECT id FROM accounts WHERE role IS NULL AND type='asset' AND (bank_name IS NOT NULL AND bank_name<>'')"):
        opening += val(c, "SELECT SUM(l.debit-l.credit) FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id WHERE "
                          "l.account_id=? AND " + POSTED, (acc["id"],))
    lines = {}

    def add(label, k, amt):
        if k in keys:
            lines.setdefault(label, {x: 0.0 for x in keys})[k] += amt
    projects = []
    for p in q(c, "SELECT id, code FROM projects WHERE status='active'"):
        try:
            pc = project_cash(c, p["id"], "early", None, delay, over, k0)
        except Exception as e:
            projects.append({"code": p["code"], "error": str(e)})
            continue
        projects.append({"code": p["code"], "peak_cash": pc["peak_cash"], "peak_month": pc["peak_month"]})
        for r in pc["rows"]:
            add("Receipts: " + p["code"], r["month"], r["in"])
            add("Payments: " + p["code"], r["month"], -r["out"])
    oh, oh_budgeted = oh_monthly(c, keys)
    for k, v in oh.items():
        add("Head-office overhead" + ("" if oh_budgeted else " (last 12 months average)"), k, -v)
    for l in q(c, "SELECT * FROM loans WHERE active=1"):
        for k in keys:
            if (not l["start_date"] or l["start_date"][:7] <= k) and (not l["end_date"] or l["end_date"][:7] >= k):
                add("Loan: " + (l["name"] or ""), k, -(l["emi"] or 0))
    at = _f(setting(c, "advance_tax_estimate"))
    if at:
        fy = current_fy()
        for f in (fy, fy + 1):
            for bm, share, nm in ADVANCE_TAX:
                y = f if bm >= 4 else f + 1
                try:
                    d = SC.bs_to_ad(y, bm, SC._lens(y)[bm - 1])
                except (ValueError, KeyError):
                    continue
                add("Advance tax (%s instalment)" % nm, mkey(d), -at * share)
    npj = a.get("new_project") or {}
    if _f(npj.get("value")) > 0 and npj.get("start"):
        dur = max(1, int(_f(npj.get("months"), 12)))
        val_ = _f(npj.get("value"))
        mg = _f(npj.get("margin"), 8) / 100
        adv = _f(npj.get("advance_pct"), 10) / 100
        s = npj["start"][:7]
        # trapezoid: slow first and last quarter
        w = [0.5 if (i < dur / 4 or i >= dur * 3 / 4) else 1.0 for i in range(dur)]
        tw = sum(w)
        add("New project: mobilisation advance", s, val_ * adv)
        add("New project: bid / performance security costs", s, -val_ * 0.001)
        for i in range(dur):
            k = add_months(s, i)
            work = val_ * w[i] / tw
            add("New project: payments", k, -work * (1 - mg))
            add("New project: receipts", add_months(k, 2 + int(delay // 30)), work * (1 - 0.05 - adv))
    minbal = _f(a.get("min_balance"), _f(setting(c, "cash_min_balance"), 0))
    bal = opening
    rows = []
    first_bite = None
    worst = None
    for k in keys:
        net = sum(v[k] for v in lines.values())
        bal += net
        need_od = max(0.0, minbal - bal)
        if need_od > 0 and not first_bite:
            first_bite = k
        if worst is None or bal < worst[1]:
            worst = (k, bal)
        rows.append({"month": k, "net": r2(net), "closing": r2(bal), "overdraft_needed": r2(need_od)})
    return {"opening": r2(opening), "months": keys, "lines": [{"label": k, "values": [r2(v[x]) for x in keys],
                                                              "total": r2(sum(v.values()))} for k, v in sorted(lines.items())],
            "rows": rows, "min_balance": minbal, "first_shortfall": first_bite,
            "lowest": {"month": worst[0], "balance": r2(worst[1])} if worst else None,
            "max_overdraft": r2(max([r["overdraft_needed"] for r in rows] or [0])), "projects": projects,
            "overhead_budgeted": oh_budgeted, "advance_tax_estimate": at,
            "note": "Advance tax: 40% by Poush end, 70% by Chaitra end, 100% by Ashad end (Income Tax Act s.94) [confirm]."}


@api("cash.settings", "accounts", "edit")
def cash_settings(c, u, a):
    for k in ("cash_interest_pct", "cash_min_balance", "advance_tax_estimate", "cash_limit_npr"):
        if k in a:
            _set(c, k, a[k])
    return True


@api("loan.list", "accounts", "view")
def loan_list(c, u, a):
    return q(c, "SELECT * FROM loans ORDER BY active DESC, name")


@api("loan.save", "accounts", "edit")
def loan_save(c, u, a):
    r = a.get("row") or {}
    need(r, "name")
    data = {k: r.get(k) or None for k in ("name", "lender", "kind", "start_date", "end_date", "remarks")}
    for k in ("emi", "balance", "rate", "limit_amount"):
        data[k] = num(r[k]) if r.get(k) not in (None, "") else None
    data["active"] = 1 if str(r.get("active", 1)) in ("1", "true") else 0
    if r.get("id"):
        upd(c, "loans", int(r["id"]), data)
        return {"id": int(r["id"])}
    return {"id": ins(c, "loans", data)}


@api("loan.delete", "accounts", "approve")
def loan_delete(c, u, a):
    c.execute("DELETE FROM loans WHERE id=?", (int(a["id"]),))
    return True


# ───────────────────────── markup (3.7, 6.4) ─────────────────────────
def markup_calc(overhead, profit, volume):
    """Peterson ch. 10. Revenue = direct cost x (1 + markup); markup covers overhead + profit.
    markup = (O + P) / (V - O - P); gross margin = (O + P) / V; markup = GPM / (100 - GPM)."""
    direct = volume - overhead - profit
    if direct <= 0:
        raise ApiError("Overhead plus profit must be less than the volume of work.")
    m = (overhead + profit) / direct
    gpm = (overhead + profit) / volume
    cm = m / (1 + m)
    return {"direct_cost": r2(direct), "markup_pct": round(100 * m, 2), "gross_margin_pct": round(100 * gpm, 2),
            "overhead_pct_on_cost": round(100 * overhead / direct, 2), "profit_pct_on_cost": round(100 * profit / direct, 2),
            "contribution_margin_pct": round(100 * cm, 2), "break_even_volume": r2(overhead / cm) if cm > 0 else None,
            "break_even_direct_cost": r2(overhead / m) if m > 0 else None}


@api("markup.get", "commercial", "view")
def markup_get(c, u, a):
    fy = current_fy()
    ohb = val(c, "SELECT SUM(amount) FROM oh_budget WHERE fy=?", (fy,))
    since = (date.today() - timedelta(days=365)).isoformat()
    rev12 = -val(c, "SELECT SUM(l.debit-l.credit) FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id JOIN accounts a ON "
                    "a.id=l.account_id WHERE a.type='income' AND (a.role IS NULL OR a.role<>'equipment_recovery') AND " + POSTED +
                 " AND v.date>=?", (since,))
    return {"overhead_budget": r2(ohb), "revenue_last_12m": r2(rev12),
            "ra_overhead_pct": _f(setting(c, "ra_overhead_pct"), 10), "ra_profit_pct": _f(setting(c, "ra_profit_pct"), 5),
            "table": [{"markup": m, "margin": round(100 * m / (100 + m), 2)} for m in (5, 8, 10, 12, 15, 20, 25, 30)]}


@api("markup.calc", "commercial", "view")
def markup_calc_api(c, u, a):
    r = markup_calc(_f(a.get("overhead")), _f(a.get("profit")), _f(a.get("volume")))
    adj = _f(a.get("risk_pct"))
    r["bid_markup_pct"] = round(r["markup_pct"] + adj, 2)
    r["bid_margin_pct"] = round(100 * r["bid_markup_pct"] / (100 + r["bid_markup_pct"]), 2)
    return r


@api("markup.apply", "commercial", "approve")
def markup_apply(c, u, a):
    """Use the calculated overhead and profit percentages in rate analysis (markup on cost)."""
    _set(c, "ra_overhead_pct", round(_f(a.get("overhead_pct")), 2))
    _set(c, "ra_profit_pct", round(_f(a.get("profit_pct")), 2))
    audit(c, u, "markup", "settings", None, a)
    return True


# rate analysis: split "overhead & profit" into overhead and profit; only overhead is a budget cost
try:
    import api_ra as RA
    _orig_ra_compute = RA.ra_compute
    _orig_push = RA._push_to_boq

    def ra_compute(c, u, a):
        """Markup on cost is split into overhead (a cost, goes into the BOQ budget) and profit (not a cost).
        Give overhead_pct and profit_pct; or give only overhead_pct as the total markup and it is split in the
        ratio set by the markup calculator; or give neither and the calculator's figures are used."""
        a = dict(a)
        s_oh, s_pr = _f(setting(c, "ra_overhead_pct"), 10), _f(setting(c, "ra_profit_pct"), 5)
        if a.get("profit_pct") not in (None, ""):
            oh, pr = _f(a.get("overhead_pct"), s_oh), _f(a.get("profit_pct"))
        else:
            total = _f(a.get("overhead_pct"), s_oh + s_pr) if a.get("overhead_pct") not in (None, "") else s_oh + s_pr
            share = s_oh / (s_oh + s_pr) if (s_oh + s_pr) > 0 else 1.0
            oh, pr = round(total * share, 4), round(total * (1 - share), 4)
        a["overhead_pct"] = oh + pr
        res = _orig_ra_compute(c, u, a)
        cpu = res["cost_per_unit"]
        res["overhead_only_pct"] = round(oh, 2)
        res["profit_pct"] = round(pr, 2)
        res["overhead_only"] = r2(cpu * oh / 100)
        res["profit"] = r2(cpu * pr / 100)
        res["gross_margin_pct"] = round(100 * (oh + pr) / (100 + oh + pr), 2)
        res["markup_label"] = "Markup on cost %s%% = overhead %s%% + profit %s%%; margin on price %s%%" % (
            round(oh + pr, 2), round(oh, 2), round(pr, 2), res["gross_margin_pct"])
        return res

    def push_to_boq(c, boq_item_id, result):
        done = _orig_push(c, boq_item_id, result)
        if "overhead_only" in result and "rate_analysis" in done:
            c.execute("DELETE FROM rate_analysis WHERE boq_item_id=? AND kind='other' AND description LIKE 'Overhead & profit%'",
                      (boq_item_id,))
            if result["overhead_only"]:
                c.execute("INSERT INTO rate_analysis(boq_item_id,kind,ref_id,description,qty_per_unit,rate) VALUES(?,?,?,?,?,?)",
                          (boq_item_id, "other", None, "Overhead %s%% (profit %s%% is not a cost)" % (
                              result["overhead_only_pct"], result["profit_pct"]), 1, result["overhead_only"]))
        return done

    RA.ra_compute = ra_compute
    RA._push_to_boq = push_to_boq
    _e = inv.FUNCS.get("ranal.compute")
    if _e:
        inv.FUNCS["ranal.compute"] = (lambda c, u, a: (ensure(c), ra_compute(c, u, a))[1], _e[1], _e[2], _e[3])
except Exception as _e:  # the rate module is optional
    print("BuildCore: markup split not applied: %s" % _e)


# ───────────────────────── bid register (3.8) ─────────────────────────
@api("bid.list", "commercial", "view")
def bid_list(c, u, a):
    rows = q(c, "SELECT * FROM bids ORDER BY date DESC, id DESC")
    for b in rows:
        b["prices"] = q(c, "SELECT * FROM bid_prices WHERE bid_id=? ORDER BY price", (b["id"],))
        b["our_pct_ee"] = round(100 * b["our_bid"] / b["ee"], 2) if b.get("ee") and b.get("our_bid") else None
        b["win_pct_ee"] = round(100 * b["winning_bid"] / b["ee"], 2) if b.get("ee") and b.get("winning_bid") else None
        resp = [p for p in b["prices"] if p["responsive"]]
        b["bidders"] = len(b["prices"])
        us = [i for i, p in enumerate(sorted(resp, key=lambda p: p["price"] or 0)) if p["is_us"]]
        b["our_rank"] = us[0] + 1 if us else None
    return rows


@api("bid.save", "commercial", "edit")
def bid_save(c, u, a):
    r = a.get("row") or {}
    need(r, "title")
    data = {k: r.get(k) or None for k in ("date", "client", "title", "work_type", "location", "status", "winner",
                                          "submission_date", "remarks")}
    for k in ("ee", "our_cost", "our_bid", "markup_pct", "winning_bid", "bid_security"):
        data[k] = num(r[k]) if r.get(k) not in (None, "") else None
    data["project_id"] = int(r["project_id"]) if r.get("project_id") else None
    if data.get("our_cost") and data.get("our_bid") and not data.get("markup_pct"):
        data["markup_pct"] = round(100 * (data["our_bid"] / data["our_cost"] - 1), 2)
    if r.get("id"):
        bid = int(r["id"])
        upd(c, "bids", bid, data)
    else:
        data["no"] = "BID-%04d" % (val(c, "SELECT COUNT(*) FROM bids") + 1)
        data["created_by"] = u["id"]
        data["date"] = data.get("date") or today()
        data["status"] = data.get("status") or "preparing"
        bid = ins(c, "bids", data)
    if "prices" in a:
        c.execute("DELETE FROM bid_prices WHERE bid_id=?", (bid,))
        for p in a["prices"] or []:
            if not p.get("bidder") or p.get("price") in (None, ""):
                continue
            ins(c, "bid_prices", {"bid_id": bid, "bidder": p["bidder"].strip(), "price": num(p["price"]),
                                  "is_us": 1 if str(p.get("is_us")) in ("1", "true") else 0,
                                  "responsive": 0 if str(p.get("responsive")) in ("0", "false") else 1, "remarks": p.get("remarks")})
        resp = q(c, "SELECT * FROM bid_prices WHERE bid_id=? AND responsive=1 ORDER BY price LIMIT 1", (bid,))
        if resp and data.get("status") in ("won", "lost") and not data.get("winning_bid"):
            upd(c, "bids", bid, {"winning_bid": resp[0]["price"], "winner": data.get("winner") or resp[0]["bidder"]})
    audit(c, u, "save", "bids", bid, data)
    return {"id": bid}


@api("bid.delete", "commercial", "approve")
def bid_delete(c, u, a):
    c.execute("DELETE FROM bid_prices WHERE bid_id=?", (int(a["id"]),))
    c.execute("DELETE FROM bids WHERE id=?", (int(a["id"]),))
    return True


@api("bid.stats", "commercial", "view")
def bid_stats(c, u, a):
    bids = bid_list(c, u, a)
    decided = [b for b in bids if b["status"] in ("won", "lost")]
    won = [b for b in decided if b["status"] == "won"]

    def grp(key):
        out = {}
        for b in decided:
            k = b.get(key) or "—"
            g = out.setdefault(k, {"key": k, "bids": 0, "won": 0, "win_pct": [], "our_pct": [], "gap": []})
            g["bids"] += 1
            g["won"] += 1 if b["status"] == "won" else 0
            if b["win_pct_ee"]:
                g["win_pct"].append(b["win_pct_ee"])
            if b["our_pct_ee"]:
                g["our_pct"].append(b["our_pct_ee"])
            if b.get("our_bid") and b.get("winning_bid") and b["status"] == "lost":
                g["gap"].append(100 * (b["our_bid"] / b["winning_bid"] - 1))
        res = []
        for g in out.values():
            res.append({"key": g["key"], "bids": g["bids"], "won": g["won"], "hit_rate": round(100 * g["won"] / g["bids"], 1),
                        "avg_winning_pct_ee": round(sum(g["win_pct"]) / len(g["win_pct"]), 2) if g["win_pct"] else None,
                        "avg_our_pct_ee": round(sum(g["our_pct"]) / len(g["our_pct"]), 2) if g["our_pct"] else None,
                        "avg_gap_when_lost": round(sum(g["gap"]) / len(g["gap"]), 2) if g["gap"] else None})
        return sorted(res, key=lambda x: -x["bids"])
    comp = {}
    for b in bids:
        for p in b["prices"]:
            if p["is_us"]:
                continue
            g = comp.setdefault(p["bidder"], {"bidder": p["bidder"], "bids": 0, "wins": 0, "pct": [], "beat_us": 0})
            g["bids"] += 1
            if b.get("winner") and b["winner"].strip().lower() == p["bidder"].strip().lower():
                g["wins"] += 1
            if b.get("ee") and p["price"]:
                g["pct"].append(100 * p["price"] / b["ee"])
            if b.get("our_bid") and p["price"] and p["price"] < b["our_bid"]:
                g["beat_us"] += 1
    comps = [{"bidder": g["bidder"], "bids": g["bids"], "wins": g["wins"], "beat_us": g["beat_us"],
              "avg_pct_ee": round(sum(g["pct"]) / len(g["pct"]), 2) if g["pct"] else None} for g in comp.values()]
    comps.sort(key=lambda x: (-x["wins"], -x["bids"]))
    return {"total": len(bids), "decided": len(decided), "won": len(won),
            "hit_rate": round(100 * len(won) / len(decided), 1) if decided else None,
            "won_value": r2(sum(b["our_bid"] or 0 for b in won)), "by_client": grp("client"), "by_type": grp("work_type"),
            "competitors": comps[:40]}


# ───────────────────────── cost codes, committed cost, EAC (3.1) ─────────────────────────
@api("cost.codes", "commercial", "view")
def cost_codes(c, u, a):
    """Per BOQ item (cost code): budget, actual, committed (open POs not yet received), estimate to
    complete and EAC = actual + committed + uncommitted remainder. Overruns carry a review class:
    clerical (re-code the cost), estimating (revise the forecast) or scope (variation)."""
    pid = int(a["project_id"])
    ev = P.project_evm(c, pid, today())
    out = []
    for r in ev["rows"]:
        committed = val(c, "SELECT SUM((pl.qty-MIN(pl.received_qty,pl.qty))*pl.rate) FROM po_lines pl JOIN po ON po.id=pl.po_id "
                           "WHERE po.project_id=? AND pl.boq_item_id=? AND po.status IN ('approved','partially_received')",
                        (pid, r["id"]))
        etc = r["etc"] or 0
        uncommitted = max(0.0, etc - committed)
        eac = (r["ac"] or 0) + committed + uncommitted
        rev = q1(c, "SELECT * FROM cost_reviews WHERE project_id=? AND boq_item_id=? ORDER BY id DESC LIMIT 1", (pid, r["id"]))
        if rev and rev.get("revised_eac") is not None and rev["class"] == "estimating":
            eac = rev["revised_eac"]
        bac = r["bac"] or 0
        out.append({"id": r["id"], "code": r["code"], "description": r["description"], "bac": r2(bac), "ac": r2(r["ac"]),
                    "committed": r2(committed), "etc_uncommitted": r2(uncommitted), "eac": r2(eac),
                    "variance": r2(bac - eac) if bac else None, "progress_pct": r["progress_pct"],
                    "cpi": r["cpi"], "review": rev["class"] if rev else None, "review_note": rev["note"] if rev else None,
                    "flag": bool(bac and eac > bac * 1.02)})
    unalloc = ev["ac_unallocated"]
    po_open = val(c, "SELECT SUM((pl.qty-MIN(pl.received_qty,pl.qty))*pl.rate) FROM po_lines pl JOIN po ON po.id=pl.po_id "
                     "WHERE po.project_id=? AND pl.boq_item_id IS NULL AND po.status IN ('approved','partially_received')", (pid,))
    return {"rows": out, "unallocated_actual": r2(unalloc), "unallocated_committed": r2(po_open),
            "totals": {k: r2(sum(x[k] or 0 for x in out)) for k in ("bac", "ac", "committed", "etc_uncommitted", "eac")}}


@api("cost.review", "commercial", "edit")
def cost_review(c, u, a):
    r = a.get("row") or {}
    need(r, "project_id", "boq_item_id", "class")
    if r["class"] not in ("clerical", "estimating", "scope", "ok"):
        raise ApiError("Class must be clerical, estimating, scope or ok.")
    ins(c, "cost_reviews", {"project_id": int(r["project_id"]), "boq_item_id": int(r["boq_item_id"]), "class": r["class"],
                            "revised_eac": num(r["revised_eac"]) if r.get("revised_eac") not in (None, "") else None,
                            "note": r.get("note"), "user_id": u["id"], "ts": now()})
    return True


# ───────────────────────── LCPI (3.3) ─────────────────────────
def _labour_unit_budget(c, boq_id):
    rows = q(c, "SELECT qty_per_unit, rate FROM rate_analysis WHERE boq_item_id=? AND kind='labour'", (boq_id,))
    return sum((r["qty_per_unit"] or 0) * (r["rate"] or 0) for r in rows) if rows else None


@api("cost.lcpi", "commercial", "view")
def cost_lcpi(c, u, a):
    """Labour cost performance index by week: budgeted labour cost of the work reported in approved DPRs
    divided by the labour cost of those DPRs. Available weekly, before the monthly CPI."""
    pid = int(a["project_id"])
    weeks = int(a.get("weeks") or 16)
    end = date.today()
    start = end - timedelta(days=7 * weeks)
    start = start - timedelta(days=(start.weekday() + 1) % 7)
    lub = {}
    out = []
    cum_b = cum_a = 0.0
    by_act = {}
    d = start
    while d <= end:
        e = d + timedelta(days=7)
        works = q(c, "SELECT w.activity_id, w.boq_item_id, SUM(w.actual_qty) qq FROM dpr_work w JOIN dpr x ON x.id=w.dpr_id WHERE "
                     "x.status='approved' AND x.project_id=? AND x.date>=? AND x.date<? GROUP BY w.activity_id, w.boq_item_id",
                  (pid, d.isoformat(), e.isoformat()))
        bcwp = 0.0
        for w in works:
            if not w["boq_item_id"]:
                continue
            if w["boq_item_id"] not in lub:
                lub[w["boq_item_id"]] = _labour_unit_budget(c, w["boq_item_id"])
            if lub[w["boq_item_id"]] is None:
                continue
            b = (w["qq"] or 0) * lub[w["boq_item_id"]]
            bcwp += b
            k = w["activity_id"] or 0
            by_act.setdefault(k, [0.0, 0.0])[0] += b
        acts = q(c, "SELECT l.activity_id, SUM(COALESCE(l.amount, l.count*(l.hours*COALESCE(l.rate,t.rate_hour)+COALESCE(l.ot_hours,0)*"
                    "COALESCE(l.rate,t.rate_hour)*1.5))) amt FROM dpr_labour l JOIN dpr x ON x.id=l.dpr_id JOIN trades t ON t.id=l.trade_id "
                    "WHERE x.status='approved' AND x.project_id=? AND x.date>=? AND x.date<? AND l.party_id IS NULL GROUP BY l.activity_id",
                 (pid, d.isoformat(), e.isoformat()))
        acwp = sum(r["amt"] or 0 for r in acts)
        for r in acts:
            by_act.setdefault(r["activity_id"] or 0, [0.0, 0.0])[1] += r["amt"] or 0
        cum_b += bcwp
        cum_a += acwp
        out.append({"week": d.isoformat(), "budgeted": r2(bcwp), "actual": r2(acwp),
                    "lcpi": round(bcwp / acwp, 2) if acwp > EPS else None,
                    "cum_lcpi": round(cum_b / cum_a, 2) if cum_a > EPS else None})
        d = e
    names = {x["id"]: x for x in q(c, "SELECT id, code, name FROM activities WHERE project_id=?", (pid,))}
    acts_out = [{"activity_id": k, "code": (names.get(k) or {}).get("code"), "name": (names.get(k) or {}).get("name") or "Not linked",
                 "budgeted": r2(v[0]), "actual": r2(v[1]), "lcpi": round(v[0] / v[1], 2) if v[1] > EPS else None}
                for k, v in by_act.items() if v[1] > EPS or v[0] > EPS]
    acts_out.sort(key=lambda x: (x["lcpi"] if x["lcpi"] is not None else 9))
    return {"weeks": out, "activities": acts_out, "lcpi": round(cum_b / cum_a, 2) if cum_a > EPS else None,
            "budgeted": r2(cum_b), "actual": r2(cum_a),
            "note": "Budget labour cost per unit comes from each BOQ item's rate analysis (labour lines). Subcontract gangs are left out."}


# ───────────────────────── CPI / SPI control chart (3.4) ─────────────────────────
def evm_asof(c, pid, d):
    ev = 0.0
    pv = 0.0
    for b in q(c, "SELECT * FROM boq_items WHERE project_id=?", (pid,)):
        ub, _p = P.unit_budget(c, b["id"])
        if ub is None:
            continue
        ex = val(c, "SELECT SUM(w.actual_qty) FROM dpr_work w JOIN dpr x ON x.id=w.dpr_id WHERE x.status='approved' AND "
                    "w.boq_item_id=? AND x.date<=?", (b["id"], d))
        ev += ex * ub
        for a in q(c, "SELECT * FROM activities WHERE boq_item_id=?", (b["id"],)):
            pv += (a["planned_qty"] or 0) * P.planned_fraction(a, d) * ub
    ac = val(c, "SELECT SUM(l.debit-l.credit) FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id JOIN accounts x ON "
                "x.id=l.account_id WHERE x.type='expense' AND l.boq_item_id IS NOT NULL AND l.project_id=? AND v.date<=? AND " + POSTED,
             (pid, d))
    return ev, pv, ac


@api("cost.control_chart", "commercial", "view")
def control_chart(c, u, a):
    """Monthly CPI (y) against SPI (x) with the mean and 1 and 2 standard-deviation bands (Peterson ch. 7)."""
    pid = int(a["project_id"])
    first = val(c, "SELECT MIN(date) FROM dpr WHERE project_id=? AND status='approved'", (pid,), None)
    if not first:
        return {"points": []}
    k = mkey(date.fromisoformat(first))
    last = mkey(date.today())
    pts = []
    while k <= last:
        d = min(month_end(k), date.today()).isoformat()
        ev, pv, ac = evm_asof(c, pid, d)
        if ev > EPS and ac > EPS and pv > EPS:
            pts.append({"month": k, "cpi": round(ev / ac, 3), "spi": round(ev / pv, 3), "ev": r2(ev), "pv": r2(pv), "ac": r2(ac)})
        k = add_months(k, 1)

    def stats(xs):
        if not xs:
            return None, None
        m = sum(xs) / len(xs)
        sd = math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1)) if len(xs) > 1 else 0
        return round(m, 3), round(sd, 3)
    mc, sc = stats([p["cpi"] for p in pts])
    ms, ss = stats([p["spi"] for p in pts])
    last_p = pts[-1] if pts else None
    quad = None
    if last_p:
        quad = ("under budget" if last_p["cpi"] >= 1 else "over budget") + ", " + ("ahead of schedule" if last_p["spi"] >= 1 else "behind schedule")
    return {"points": pts, "cpi_mean": mc, "cpi_sd": sc, "spi_mean": ms, "spi_sd": ss, "quadrant": quad,
            "consistency": None if sc is None else ("consistent" if (sc or 0) < 0.05 else "erratic" if sc > 0.15 else "some variation")}


# ───────────────────────── NFRS 15 contract accounting ─────────────────────────
def nfrs15(c, pid, asof=None):
    asof = asof or today()
    p = get(c, "projects", pid, "Project")
    ev = P.project_evm(c, pid, asof)
    contract = ev["contract_revenue"]
    vo_app = sum(r["forecast_revenue"] - r["contract_amount"] for r in ev["rows"])
    pending = q(c, "SELECT * FROM variations WHERE project_id=? AND status IN ('identified','submitted')", (pid,))
    vo_hp = 0.0
    for v in pending:
        if v.get("highly_probable"):
            est = v.get("est_value")
            if est is None:
                b = q1(c, "SELECT rate, revised_rate FROM boq_items WHERE id=?", (v["boq_item_id"],)) if v.get("boq_item_id") else None
                rate = v.get("new_rate") or ((b or {}).get("revised_rate") or (b or {}).get("rate") or 0)
                est = (v.get("var_qty") or 0) * rate
            vo_hp += est or 0
    claims = q(c, "SELECT * FROM events WHERE project_id=? AND type IN ('claim','escalation','eot','variation') AND status NOT IN "
                  "('rejected','closed')", (pid,))
    cl_hp = sum((e.get("claim_value") if e.get("claim_value") is not None else (e.get("cost_impact") or 0)) for e in claims
                if e.get("highly_probable"))
    cd = SCH.contract_dates(c, p)
    run = q1(c, "SELECT finish FROM sched_runs WHERE project_id=? ORDER BY id DESC LIMIT 1", (pid,))
    ld = SCH.ld_exposure(c, p, run["finish"] if run else None, cd)
    tp = contract + vo_app + vo_hp + cl_hp - ld["amount"]
    eac = ev["eac"]
    # cost-to-cost progress, abnormal waste and uninstalled material left out (NFRS item 4)
    abnormal = -val(c, "SELECT SUM(l.debit-l.credit) FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id JOIN accounts a ON "
                       "a.id=l.account_id WHERE a.role='material_cost' AND v.source='abnormal_waste' AND l.project_id=? AND v.date<=? AND "
                       + POSTED, (pid, asof))
    uninstalled = val(c, "SELECT SUM(b.value) FROM stock_balances b JOIN stores s ON s.id=b.store_id WHERE b.project_id=? AND "
                         "s.type<>'transit'", (pid,)) if (p.get("revenue_method") or "cost") == "cost" else 0.0
    ac = ev["ac"]
    method = p.get("revenue_method") or "output"
    if method == "cost":
        pct = min(1.0, max(0.0, ac / eac)) if eac > EPS else 0.0
    else:
        pct = ev["earned_revenue"] / ev["forecast_revenue"] if ev["forecast_revenue"] else 0.0
    revenue = tp * pct
    certified = val(c, "SELECT SUM(subtotal) FROM invoices WHERE project_id=? AND kind='sales' AND status='posted' AND date<=?",
                    (pid, asof))
    recognised = -val(c, "SELECT SUM(l.debit-l.credit) FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id JOIN accounts a ON "
                         "a.id=l.account_id WHERE a.role IN ('contract_revenue','contract_asset_rev') AND l.project_id=? AND v.date<=? AND "
                         + POSTED, (pid, asof))
    diff = revenue - certified
    loss = max(0.0, eac - tp)
    booked_loss = -val(c, "SELECT SUM(l.debit-l.credit) FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id JOIN accounts a ON "
                          "a.id=l.account_id WHERE a.role='onerous_provision' AND l.project_id=? AND " + POSTED, (pid,))
    adj_booked = val(c, "SELECT SUM(l.debit-l.credit) FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id JOIN accounts a ON "
                        "a.id=l.account_id WHERE a.role='contract_asset' AND l.project_id=? AND " + POSTED, (pid,)) - \
        val(c, "SELECT SUM(l.credit-l.debit) FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id JOIN accounts a ON "
               "a.id=l.account_id WHERE a.role='contract_liability' AND l.project_id=? AND " + POSTED, (pid,))
    return {"project": {"id": p["id"], "code": p["code"], "name": p["name"], "contract_type": p.get("contract_type"),
                        "sec26": p.get("sec26"), "performance_obligations": p.get("performance_obligations"),
                        "revenue_method": method, "jv_share_pct": p.get("jv_share_pct"), "jv_partners": p.get("jv_partners")},
            "as_of": asof, "contract_price": r2(contract), "approved_variations": r2(vo_app),
            "pending_variations_highly_probable": r2(vo_hp), "claims_highly_probable": r2(cl_hp), "ld_expected": ld["amount"],
            "transaction_price": r2(tp), "eac": r2(eac), "actual_cost": r2(ac), "abnormal_waste_excluded": r2(abnormal),
            "uninstalled_materials": r2(uninstalled), "progress_pct": round(100 * pct, 2), "revenue_to_date": r2(revenue),
            "certified_to_date": r2(certified), "revenue_in_books": r2(recognised),
            "contract_asset": r2(max(0.0, diff)), "contract_liability": r2(max(0.0, -diff)),
            "adjustment_needed": r2(diff - adj_booked), "adjustment_booked": r2(adj_booked),
            "remaining_obligations": r2(max(0.0, tp - revenue)), "expected_loss": r2(loss),
            "onerous_provision_needed": r2(max(0.0, loss - booked_loss)), "onerous_booked": r2(booked_loss),
            "pending_variations": pending, "claims": claims,
            "note": "Output method (measured work x rate) unless the project is set to cost-to-cost. Cost-to-cost leaves out "
                    "abnormal waste (already expensed) and material in store not yet installed."}


@api("nfrs15.get", "commercial", "view")
def nfrs15_get(c, u, a):
    return nfrs15(c, int(a["project_id"]), a.get("as_of"))


def _ensure_role(c, role, name, typ, code0):
    if val(c, "SELECT id FROM accounts WHERE role=?", (role,), None):
        return
    gid = val(c, "SELECT id FROM account_groups WHERE type=? ORDER BY id DESC", (typ,), None)
    code = code0
    while val(c, "SELECT id FROM accounts WHERE code=?", (code,), None):
        code = str(int(code) + 1)
    ins(c, "accounts", {"code": code, "name": name, "type": typ, "group_id": gid, "role": role, "active": 1})


@api("nfrs15.post", "accounts", "approve")
def nfrs15_post(c, u, a):
    """Post the contract asset / liability adjustment (revenue earned vs billed) and the onerous-contract
    provision on the date given. Earlier adjustments are taken into account, so re-posting only moves
    the difference."""
    from core import post_voucher
    pid = int(a["project_id"])
    d = a.get("date") or today()
    r = nfrs15(c, pid, d)
    _ensure_role(c, "contract_asset", "Contract assets (unbilled revenue, NFRS 15)", "asset", "1210")
    _ensure_role(c, "contract_liability", "Contract liabilities (billing in excess, NFRS 15)", "liability", "2210")
    _ensure_role(c, "onerous_provision", "Provision for onerous contracts (NAS 37)", "liability", "2310")
    _ensure_role(c, "onerous_loss", "Expected loss on onerous contracts", "expense", "5910")
    out = {}
    adj = r["adjustment_needed"]
    if abs(adj) > 0.5:
        role = "contract_asset" if adj > 0 else "contract_liability"
        lines = [{"role": role, "debit": adj, "project_id": pid}, {"role": "contract_revenue", "credit": adj, "project_id": pid}] if adj > 0 \
            else [{"role": "contract_revenue", "debit": -adj, "project_id": pid}, {"role": role, "credit": -adj, "project_id": pid}]
        out["contract_voucher"] = post_voucher(c, u, "journal", d, "NFRS 15 contract %s adjustment" % ("asset" if adj > 0 else "liability"),
                                               lines, project_id=pid, source="nfrs15", source_id=pid)
    if r["onerous_provision_needed"] > 0.5:
        amt = r["onerous_provision_needed"]
        out["onerous_voucher"] = post_voucher(c, u, "journal", d, "Onerous contract provision (NAS 37)",
                                              [{"role": "onerous_loss", "debit": amt, "project_id": pid},
                                               {"role": "onerous_provision", "credit": amt, "project_id": pid}],
                                              project_id=pid, source="nfrs15", source_id=pid)
    audit(c, u, "nfrs15", "projects", pid, out)
    return out


@api("nfrs15.subledgers", "commercial", "view")
def subledgers(c, u, a):
    """Retention and mobilisation-advance sub-ledgers per project and party (NFRS item 7)."""
    pid = a.get("project_id")
    out = {}
    for role, label in (("retention_receivable", "Retention held by clients"), ("retention_payable", "Retention we hold from subcontractors"),
                        ("client_advance", "Mobilisation advance from clients"), ("subcon_advance", "Advances to subcontractors"),
                        ("supplier_advance", "Advances to suppliers")):
        rows = q(c, "SELECT v.date, v.no, v.narration, l.debit, l.credit, l.party_id, l.project_id FROM voucher_lines l JOIN vouchers v ON "
                    "v.id=l.voucher_id JOIN accounts a ON a.id=l.account_id WHERE a.role=? AND " + POSTED +
                 (" AND l.project_id=?" if pid else "") + " ORDER BY v.date, v.id", (role, int(pid)) if pid else (role,))
        bal = 0.0
        for r in rows:
            bal += r["debit"] - r["credit"]
            r["balance"] = r2(bal)
        by_party = {}
        for r in rows:
            by_party[r["party_id"]] = by_party.get(r["party_id"], 0) + r["debit"] - r["credit"]
        out[role] = {"label": label, "rows": rows[-200:], "balance": r2(bal),
                     "by_party": [{"party_id": k, "balance": r2(v)} for k, v in by_party.items() if abs(v) > 0.5]}
    return out


# ───────────────────────── cash-payment limit (NFRS item 8) ─────────────────────────
_orig_pay = inv.FUNCS["payment.create"]


def payment_create(c, u, a):
    ensure(c)
    lim = _f(setting(c, "cash_limit_npr"), 25000)
    acc = q1(c, "SELECT role, name FROM accounts WHERE id=?", (int(a["bank_account_id"]),)) if a.get("bank_account_id") else None
    is_cash = (acc and acc.get("role") == "cash") or (a.get("mode") or "").lower() == "cash"
    gross = sum(_f(x.get("amount")) for x in (a.get("allocations") or [])) + _f(a.get("advance"))
    if is_cash and lim and gross > lim and a.get("kind") == "pay":
        if not a.get("cash_override"):
            raise ApiError("Cash payment of %s is above the %s limit for a single payment. Pay by cheque or bank "
                           "transfer, or tick the cash-limit override and give the reason (it is recorded)." % (r2(gross), r2(lim)))
        if u.get("role") not in ("admin", "director", "accountant"):
            raise ApiError("Only an accountant, director or administrator can override the cash-payment limit.")
        audit(c, u, "cash_limit_override", "payments", None, {"amount": gross, "reason": a.get("cash_override")})
    return _orig_pay[0](c, u, a)


inv.FUNCS["payment.create"] = (payment_create, _orig_pay[1], _orig_pay[2], _orig_pay[3])


# ───────────────────────── ratios and backlog (3.12, NFRS 20) ─────────────────────────
def _group_codes(c):
    return {g["id"]: g for g in q(c, "SELECT * FROM account_groups")}


def ratios(c, asof=None):
    import api_equipment_reports as ER
    asof = asof or today()
    bs = ER.rep_bs(c, None, {"as_of": asof})
    frm = (date.fromisoformat(asof) - timedelta(days=365)).isoformat()
    pl = ER.rep_pl(c, None, {"from": frm, "to": asof})
    groups = _group_codes(c)

    def gcode(r):
        g = groups.get(r.get("group_id")) or {}
        while g and g.get("parent_id") and not str(g.get("code", "")).startswith(("A1", "A2", "A3", "A4", "A5", "L1", "L2", "L3")):
            g = groups.get(g["parent_id"]) or {}
        return str(g.get("code") or "")
    accs = {a["id"]: a for a in q(c, "SELECT id, role, name FROM accounts")}
    cash = sum(r["amount"] for r in bs["assets"] if gcode(r).startswith("A1"))
    inventory = sum(r["amount"] for r in bs["assets"] if gcode(r).startswith("A2"))
    recv = sum(r["amount"] for r in bs["assets"] if gcode(r).startswith(("A3", "A4")))
    fixed = sum(r["amount"] for r in bs["assets"] if not gcode(r).startswith(("A1", "A2", "A3", "A4")))
    ret_r = sum(r["amount"] for r in bs["assets"] if (accs.get(r["id"]) or {}).get("role") == "retention_receivable")
    ar = sum(r["amount"] for r in bs["assets"] if (accs.get(r["id"]) or {}).get("role") in ("ar_control", "contract_asset"))
    cur_assets = cash + inventory + recv
    loans = sum(r["amount"] for r in bs["liabilities"] if "loan" in (r["name"] or "").lower() and "term" in (r["name"] or "").lower())
    cur_liab = bs["total_liabilities"] - loans
    ap = sum(r["amount"] for r in bs["liabilities"] if (accs.get(r["id"]) or {}).get("role") in ("ap_control", "grni"))
    equity = bs["total_equity"]
    revenue = pl["total_income"] - sum(r["amount"] for r in pl["income"] if (accs.get(r["id"]) or {}).get("role") == "equipment_recovery")
    direct = sum(r["amount"] for r in pl["expense"] if gcode(r).startswith(("X1", "X2")) or
                 (accs.get(r["id"]) or {}).get("role") in ("material_cost", "labour_cost", "subcon_cost", "hire_cost", "fuel_cost",
                                                            "repair_cost", "equipment_cost", "overhead"))
    rec_int = sum(r["amount"] for r in pl["income"] if (accs.get(r["id"]) or {}).get("role") == "equipment_recovery")
    direct -= rec_int
    gross = revenue - direct
    overhead = pl["total_expense"] - direct - rec_int
    net = pl["profit"]
    fa_rows = [r for r in bs["assets"] if gcode(r).startswith("A5") or not gcode(r).startswith(("A1", "A2", "A3", "A4"))]
    fa_gross = sum(r["amount"] for r in fa_rows if r["amount"] > 0)
    fa_dep = -sum(r["amount"] for r in fa_rows if r["amount"] < 0)
    # backlog: remaining contract value of active projects
    backlog = 0.0
    for p in q(c, "SELECT id FROM projects WHERE status='active'"):
        try:
            ev = P.project_evm(c, p["id"], asof)
            backlog += max(0.0, ev["forecast_revenue"] - ev["earned_revenue"])
        except Exception:
            pass

    def div(a_, b_, k=1.0):
        return round(k * a_ / b_, 2) if b_ and abs(b_) > EPS else None
    out = [
        ("Liquidity", "Current ratio", div(cur_assets, cur_liab), "current", "x"),
        ("Liquidity", "Quick ratio", div(cash + ar, cur_liab), "quick", "x"),
        ("Leverage", "Current liabilities to net worth", div(cur_liab, equity), None, "x"),
        ("Leverage", "Debt to equity", div(bs["total_liabilities"], equity), "debt_equity", "x"),
        ("Leverage", "Fixed assets to net worth", div(fixed, equity), None, "x"),
        ("Activity", "Collection period (days)", div(ar + ret_r, revenue, 365), "collection_days", "days"),
        ("Activity", "Collection period without retention (days)", div(ar, revenue, 365), None, "days"),
        ("Activity", "Average age of payables (days)", div(ap, direct, 365), None, "days"),
        ("Activity", "Assets to revenue", div(bs["total_assets"], revenue), None, "x"),
        ("Activity", "Working capital turns", div(revenue, cur_assets - cur_liab), None, "x"),
        ("Activity", "Payables to revenue", div(ap, revenue, 100), None, "%"),
        ("Profitability", "Gross margin", div(gross, revenue, 100), "gross_margin", "%"),
        ("Profitability", "Overhead ratio", div(overhead, revenue, 100), None, "%"),
        ("Profitability", "Net margin", div(net, revenue, 100), "net_margin", "%"),
        ("Profitability", "Return on assets", div(net, bs["total_assets"], 100), None, "%"),
        ("Profitability", "Return on equity", div(net, equity, 100), None, "%"),
        ("Other", "Degree of fixed-asset newness", div(fa_gross - fa_dep, fa_gross, 100), None, "%"),
        ("Other", "Months in backlog", div(backlog, revenue, 12), "backlog_months", "months"),
    ]
    try:
        targets = json.loads(setting(c, "ratio_targets") or "{}")
    except ValueError:
        targets = {}
    lower_better = {"debt_equity", "collection_days"}
    rows = []
    for grp, name, v, key, unit in out:
        t = targets.get(key) if key else None
        ok = None
        if t is not None and v is not None:
            ok = v <= t if key in lower_better else v >= t
        rows.append({"group": grp, "name": name, "value": v, "unit": unit, "target": t, "ok": ok, "key": key})
    return {"as_of": asof, "rows": rows, "backlog": r2(backlog), "revenue_12m": r2(revenue), "net_profit_12m": r2(net),
            "cash": r2(cash), "equity": r2(equity),
            "note": "Revenue and profit are for the 12 months to the date. Liabilities are treated as current unless the "
                    "account name contains 'term loan'. Internal equipment recovery is netted off."}


@api("ratio.get", "accounts", "view")
def ratio_get(c, u, a):
    r = ratios(c, a.get("as_of"))
    if a.get("trend"):
        tr = []
        k = mkey(date.today())
        for i in range(int(a.get("trend") or 6) - 1, -1, -1):
            d = min(month_end(add_months(k, -i)), date.today()).isoformat()
            x = ratios(c, d)
            tr.append({"as_of": d, "values": {row["name"]: row["value"] for row in x["rows"]}})
        r["trend"] = tr
    return r


@api("ratio.targets", "accounts", "edit")
def ratio_targets(c, u, a):
    _set(c, "ratio_targets", json.dumps({k: _f(v) for k, v in (a.get("targets") or {}).items() if v not in ("", None)}))
    return True


# ───────────────────────── command centre (6.10) ─────────────────────────
@api("cash.summary")
def cash_summary(c, u, a):
    out = {}
    if core.can(u, "accounts", "view"):
        out["cash"] = r2(role_balance(c, "cash") + role_balance(c, "bank"))
        try:
            cc = cash_company(c, u, {"months": 12})
            out["lowest"] = cc["lowest"]
            out["first_shortfall"] = cc["first_shortfall"]
            out["max_overdraft"] = cc["max_overdraft"]
        except Exception as e:
            out["cash_error"] = str(e)
        try:
            r = ratios(c)
            out["ratios"] = [x for x in r["rows"] if x["name"] in ("Current ratio", "Debt to equity", "Gross margin",
                                                                   "Months in backlog", "Collection period (days)")]
            out["backlog"] = r["backlog"]
        except Exception as e:
            out["ratio_error"] = str(e)
    if core.can(u, "commercial", "view"):
        s = bid_stats(c, u, {})
        out["hit_rate"] = s["hit_rate"]
        out["bids_open"] = sum(1 for b in bid_list(c, u, {}) if b["status"] in ("preparing", "submitted"))
    return out
