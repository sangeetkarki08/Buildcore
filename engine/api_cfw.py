"""
Thirteen-week rolling cash forecast (BuildCore 2.27).

Section 14 of the master development prompt, built on what the books, the IPCs, the payment requests and the
schedule already say. Nothing here posts, changes a balance or alters an existing table.

  1. Thirteen weeks from the Monday of the current week. Week 1 opens with today's cash and bank balance; every
     later week opens with the previous week's closing.
  2. Every line carries a confidence class:
       confirmed  documents that fix the amount and date: certified invoices not yet due, promised payments
                  recorded as follow-ups, supplier bills, wages, VAT and TDS, instalments, approved payment
                  requests, manual items entered as confirmed
       likely     IPCs submitted and awaiting certification, retention that falls due, open purchase-order
                  deliveries, payment requests still in the chain
       estimate   future work from each project's schedule and terms (as in the 12-month cash budget),
                  head-office overhead
       uncertain  overdue receivables with no promised date (assumed collected after a set number of days)
     The prudent closing counts only confirmed and likely receipts against every payment.
  3. Cash kept back: the reserve from payment control (2.26) and restricted funds (margin money, guarantee
     deposits, escrow) with their dates. Available = closing - reserve - restricted; below zero is a funding gap.
  4. Scenarios: client receipts 15, 30 and 45 days late, a cost overrun, and the user's own delay.
  5. Manual items for what no document shows yet (a loan drawdown, an equity injection, a land payment).
  6. Snapshots: a saved forecast is compared week by week with the cash that actually moved.
"""
import json
from datetime import date, timedelta

import core
from core import ApiError, audit, get, ins, now, q, q1, r2, setting, today, upd, val
import api_inventory as inv
from api_inventory import api, invoice_paid

VERSION = "2.27.0"
WEEKS = 13
POSTED = "v.status IN ('posted','reversed')"

SCHEMA = """
CREATE TABLE IF NOT EXISTS cfw_items(id INTEGER PRIMARY KEY, date TEXT, kind TEXT, amount REAL DEFAULT 0, label TEXT,
  category TEXT, project_id INTEGER, confidence TEXT DEFAULT 'likely', note TEXT, active INTEGER DEFAULT 1,
  created_by INTEGER, ts TEXT);
CREATE TABLE IF NOT EXISTS cfw_restricted(id INTEGER PRIMARY KEY, name TEXT, amount REAL DEFAULT 0, account_id INTEGER,
  from_date TEXT, until_date TEXT, note TEXT, active INTEGER DEFAULT 1, created_by INTEGER, ts TEXT);
CREATE TABLE IF NOT EXISTS cfw_snapshots(id INTEGER PRIMARY KEY, label TEXT, week0 TEXT, opening REAL, scenario TEXT,
  data TEXT, user_id INTEGER, user_name TEXT, ts TEXT);
"""
DEFAULTS = {"cfw_overdue_days": "30"}   # overdue receivables with no promise are assumed collected this many days on

CONF = [("confirmed", "Confirmed"), ("likely", "Likely"), ("estimate", "Estimate"), ("uncertain", "Uncertain")]
CONF_LABEL = dict(CONF)
SCENARIOS = [("base", "As expected", 0, 0.0), ("d15", "Client receipts 15 days late", 15, 0.0),
             ("d30", "Client receipts 30 days late", 30, 0.0), ("d45", "Client receipts 45 days late", 45, 0.0),
             ("o10", "Costs 10% over on future work", 0, 10.0)]


def init_cfw(c):
    c.executescript(SCHEMA)
    for k, v in DEFAULTS.items():
        if q1(c, "SELECT key FROM settings WHERE key=?", (k,)) is None:
            c.execute("INSERT INTO settings(key, value) VALUES(?,?)", (k, v))


# ───────────────────────────── helpers ─────────────────────────────
def _f(v, d=0.0):
    try:
        return float(v) if v not in (None, "") else d
    except (TypeError, ValueError):
        return d


def _int(v):
    try:
        return int(v) if v not in (None, "", "null") else None
    except (TypeError, ValueError):
        return None


def _d(s):
    try:
        return date.fromisoformat(str(s)[:10]) if s else None
    except ValueError:
        return None


def _need(c, u, action="view"):
    if not (u.get("role") == "admin" or u.get("system") or core.can(u, "accounts", action)):
        raise ApiError("Your role cannot %s the cash forecast (needs accounts %s)." % ("see" if action == "view" else "change", action))
    try:
        import api_workspace as W
        if W.allowed_projects(c, u) is not None:
            raise ApiError("PROJECT_DENIED: the company cash forecast needs access to every project.")
    except ImportError:
        pass


def week0(t=None):
    d = _d(t or today())
    return d - timedelta(days=d.weekday())


def money_balance(c, to=None):
    """Cash and bank today: accounts with role cash or bank, and other asset accounts that carry a bank name
    (the same opening as the 12-month company cash budget)."""
    w, p = "", []
    if to:
        w = " AND v.date<=?"
        p.append(to)
    ids = [r["id"] for r in q(c, "SELECT id FROM accounts WHERE role IN ('cash','bank') OR (role IS NULL AND type='asset' "
                                 "AND bank_name IS NOT NULL AND bank_name<>'')")]
    if not ids:
        return 0.0, []
    mov = val(c, "SELECT SUM(l.debit-l.credit) FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id WHERE " + POSTED +
              " AND l.account_id IN (%s)" % ",".join(map(str, ids)) + w, p)
    ob = val(c, "SELECT SUM(opening_balance) FROM accounts WHERE id IN (%s)" % ",".join(map(str, ids)))
    return r2((mov or 0) + (ob or 0)), ids


class Grid:
    def __init__(self, w0):
        self.w0 = w0
        self.starts = [w0 + timedelta(days=7 * i) for i in range(WEEKS)]
        self.lines = {}

    def week_of(self, d):
        d = _d(d) if not isinstance(d, date) else d
        if d is None:
            return None
        i = (d - self.w0).days // 7
        if i < 0:
            return 0          # past due: it is owed now
        return i if i < WEEKS else None

    def add(self, kind, label, conf, d, amount, ref=None, project_id=None):
        if abs(amount) < 0.005:
            return
        i = self.week_of(d)
        if i is None:
            return
        key = (kind, label, conf)
        ln = self.lines.setdefault(key, {"kind": kind, "label": label, "confidence": conf, "values": [0.0] * WEEKS, "items": []})
        ln["values"][i] += amount
        if len(ln["items"]) < 200:
            ln["items"].append({"week": i + 1, "date": str(d)[:10], "amount": r2(amount), "ref": ref, "project_id": project_id})

    def spread(self, kind, label, conf, month_key, amount, project_id=None, ref=None):
        """A monthly amount spread evenly over the days of that month inside the window."""
        y, m = int(month_key[:4]), int(month_key[5:7])
        first = date(y, m, 1)
        nxt = date(y + (m // 12), m % 12 + 1, 1)
        days = (nxt - first).days
        per = amount / days
        d = max(first, self.w0)
        inside = 0.0
        while d < nxt:
            i = (d - self.w0).days // 7
            if i >= WEEKS:
                break
            self.add(kind, label, conf, d, per, None, project_id)
            inside += per
            d += timedelta(days=1)
        # drop the per-day items: one item per month is enough for the drill-down
        ln = self.lines.get((kind, label, conf))
        if ln and inside > 0.005:
            ln["items"] = [x for x in ln["items"] if x["ref"] is not None] + [{"week": None, "date": month_key, "amount": r2(inside),
                                                                              "ref": ref or "Month " + month_key, "project_id": project_id}]


# ───────────────────────────── the forecast ─────────────────────────────
def build(c, u, delay=0, overrun=0.0, t=None):
    t = t or today()
    w0 = week0(t)
    g = Grid(w0)
    end = (w0 + timedelta(days=7 * WEEKS - 1)).isoformat()
    over_days = int(_f(setting(c, "cfw_overdue_days"), 30))
    import api_fc as FC
    projs = {p["id"]: p for p in q(c, "SELECT * FROM projects")}

    def pc(pid):
        return (projs.get(pid) or {}).get("code") or "Company"

    # ── receipts from documents ──
    promised = {}
    for f in q(c, "SELECT * FROM fc_follow WHERE promised_date IS NOT NULL AND id IN (SELECT MAX(id) FROM fc_follow GROUP BY ref_type, ref_id)"):
        promised[(f["ref_type"], f["ref_id"])] = f
    for i in q(c, "SELECT * FROM invoices WHERE kind='sales' AND status='posted'"):
        bal = r2((i["payable"] or 0) - invoice_paid(c, i["id"]))
        if bal <= 0.5:
            continue
        ipc = q1(c, "SELECT id, no FROM ipc WHERE invoice_id=?", (i["id"],))
        fr = (FC.fc_row(c, ipc["id"]) if ipc else None) or {}
        pr = promised.get(("ipc", ipc["id"])) if ipc else None
        pr = pr or promised.get(("invoice", i["id"]))
        ref = (ipc["no"] if ipc else i["no"]) + " " + pc(i["project_id"])
        if pr and pr["promised_date"] >= t:
            amt = min(bal, _f(pr["promised_amount"], bal) or bal)
            g.add("in", "Promised by the client", "confirmed", _d(pr["promised_date"]) + timedelta(days=delay), amt, ref, i["project_id"])
            bal = r2(bal - amt)
            if bal <= 0.5:
                continue
        due = fr.get("expected_pay_date") or i["due_date"] or i["date"]
        if due >= t:
            g.add("in", "Certified bills falling due", "confirmed", _d(due) + timedelta(days=delay), bal, ref, i["project_id"])
        else:
            g.add("in", "Overdue receivables (no promised date)", "uncertain", _d(t) + timedelta(days=over_days + delay), bal,
                  ref + " overdue since " + due, i["project_id"])
    for i in q(c, "SELECT * FROM ipc WHERE status='submitted'"):
        s = FC.ipc_state(c, i, t=t)
        tm = FC.terms(c, projs.get(i["project_id"]) or {})
        base = max(_d(s["cert_due"]) or _d(t), _d(t))
        g.add("in", "IPCs submitted, awaiting certification", "likely", base + timedelta(days=int(tm.get("pay_days") or 28) + delay),
              s["claimed_net"], i["no"] + " " + pc(i["project_id"]), i["project_id"])
    for pid, p in projs.items():
        held = FC.role_balance(c, "retention_receivable", pid)
        if held > 0.5:
            ri = FC.retention_info(c, p, r2(held), t)
            for dd, amt in ((ri["first_date"], ri["first_release"]), (ri["final_date"], r2(held - ri["first_release"]))):
                if dd and dd <= end:
                    g.add("in", "Retention released", "likely", _d(max(dd, t)) + timedelta(days=delay), amt, "Retention " + p["code"], pid)

    # ── payments from documents ──
    pay = FC.payables(c, u, {"as_of": t})
    req_by_key = {}
    for r in q(c, "SELECT * FROM fc_payreq WHERE stage IN ('requested','docs_verified','accounts_verified','cash_reviewed','approved')"):
        conf = "confirmed" if r["stage"] == "approved" else "likely"
        g.add("out", "Payment requests approved" if conf == "confirmed" else "Payment requests in the chain", conf,
              r["proposed_date"] or r["due_date"] or t, r["amount"], r["no"], r["project_id"])
        req_by_key[r["invoice_id"] or r["ref"]] = req_by_key.get(r["invoice_id"] or r["ref"], 0) + r["amount"]
    labels = {"supplier": "Supplier bills", "subcontractor": "Subcontractor bills", "equipment": "Equipment hire bills",
              "payroll": "Wages payable", "statutory": "VAT and TDS to deposit", "loan": "Loan and equipment instalments"}
    for r in pay["rows"]:
        amt = r["unrequested"]
        if amt <= 0.5:
            continue
        if r["ref_type"] in ("loan", "eq_emi"):
            continue                       # all instalments in the window are added below
        g.add("out", labels.get(r["category"], "Other payables"), "confirmed" if r["payable_now"] else "likely",
              r["due_date"] or t, amt, (r["ref_no"] or "") + (" " + r["party_name"] if r["party_name"] else ""), r["project_id"])
    for k in pay["commitments"]:
        cd = 30
        d0 = _d(k["delivery_date"]) or _d(t)
        g.add("out", "Purchase orders to be delivered", "likely", d0 + timedelta(days=cd), k["pending_value"] * (1 + overrun / 100),
              k["no"] + " " + (k["party_name"] or ""), k["project_id"])
    # instalments: every one inside the window
    for ln in q(c, "SELECT * FROM loans WHERE active=1 AND COALESCE(emi,0)>0 AND start_date IS NOT NULL"):
        requested = req_by_key.get("loan:%s" % ln["id"], 0)
        n = 0
        while n < 600:
            d = FC._add_months(ln["start_date"], n)
            n += 1
            if d < w0.isoformat():
                continue
            if d > end or (ln["end_date"] and d > ln["end_date"]):
                break
            amt = ln["emi"]
            if requested > 0.5:
                take = min(requested, amt)
                requested -= take
                amt -= take
            g.add("out", "Loan and equipment instalments", "confirmed", d, amt, "Loan " + (ln["name"] or ""), None)
    for f in q(c, "SELECT f.*, e.code FROM eq_finance f LEFT JOIN equipment e ON e.id=f.equipment_id WHERE COALESCE(f.emi,0)>0 "
                  "AND f.first_emi_date IS NOT NULL"):
        paid = int(val(c, "SELECT COUNT(*) FROM eq_emi WHERE equipment_id=?", (f["equipment_id"],)))
        requested = req_by_key.get("eq_emi:%s" % f["equipment_id"], 0)
        k = paid
        while not f["emi_count"] or k < f["emi_count"]:
            d = FC._add_months(f["first_emi_date"], k)
            if d > end:
                break
            amt = f["emi"]
            if requested > 0.5:
                take = min(requested, amt)
                requested -= take
                amt -= take
            g.add("out", "Loan and equipment instalments", "confirmed", max(d, w0.isoformat()), amt,
                  "Instalment %d %s" % (k + 1, f["code"] or ""), None)
            k += 1
            if k - paid > 60:
                break

    # ── future work from the schedule (estimate), as the 12-month company cash budget ──
    import api_cash as CA
    keep_in = ("IPC receipts (net of retention, TDS, advance)", "VAT collected on IPCs")
    keep_out = ("Labour", "Materials", "Equipment running", "Site overhead & other", "Subcontractors (pay when paid)",
                "VAT paid to IRD (net of input VAT)")
    k0 = CA.mkey(w0)
    notes = []
    for p in q(c, "SELECT id, code FROM projects WHERE status='active' AND COALESCE(kind,'') NOT IN ('trading','general')"):
        try:
            res = CA.project_cash(c, p["id"], "early", 4, delay, overrun, k0)
        except Exception as e:  # a project without a schedule simply adds nothing
            notes.append("%s: no schedule-based estimate (%s)" % (p["code"], str(e)[:80]))
            continue
        for row in res["rows"]:
            for cat, v in row["in_detail"].items():
                if cat in keep_in and v:
                    g.spread("in", "Future work billed (from the schedule)", "estimate", row["month"], v, p["id"], p["code"] + " " + row["month"])
            for cat, v in row["out_detail"].items():
                if cat in keep_out and v:
                    g.spread("out", "Future work costs (from the schedule)", "estimate", row["month"], v, p["id"], p["code"] + " " + cat + " " + row["month"])
    oh, budgeted = CA.oh_monthly(c, [CA.add_months(k0, i) for i in range(4)])
    for k, v in oh.items():
        if v:
            g.spread("out", "Head-office overhead" + ("" if budgeted else " (last 12 months average)"), "estimate", k, v)

    # ── manual items ──
    for it in q(c, "SELECT * FROM cfw_items WHERE active=1"):
        dd = _d(it["date"])
        if not dd or dd < w0:
            continue
        if it["kind"] == "in" and it["category"] != "financing":
            dd = dd + timedelta(days=delay)
        g.add(it["kind"], "Entered by hand: " + (it["category"] or "other"), it["confidence"] or "likely", dd, it["amount"],
              it["label"], it["project_id"])

    # ── weeks ──
    opening, _ids = money_balance(c, t)
    reserve = r2(_f(setting(c, "fc_cash_reserve")))
    restricted_rows = q(c, "SELECT * FROM cfw_restricted WHERE active=1")
    lines = sorted(g.lines.values(), key=lambda x: (x["kind"] != "in", [k for k, _l in CONF].index(x["confidence"]), x["label"]))
    for ln in lines:
        ln["values"] = [r2(v) for v in ln["values"]]
        ln["total"] = r2(sum(ln["values"]))
        ln["confidence_label"] = CONF_LABEL[ln["confidence"]]
    rows = []
    bal = prudent = opening
    for i, s in enumerate(g.starts):
        e = s + timedelta(days=6)
        cin = sum(ln["values"][i] for ln in lines if ln["kind"] == "in")
        cout = sum(ln["values"][i] for ln in lines if ln["kind"] == "out")
        safe_in = sum(ln["values"][i] for ln in lines if ln["kind"] == "in" and ln["confidence"] in ("confirmed", "likely"))
        o = bal
        bal = bal + cin - cout
        prudent = prudent + safe_in - cout
        restr = sum(_f(x["amount"]) for x in restricted_rows if (not x["from_date"] or x["from_date"] <= e.isoformat())
                    and (not x["until_date"] or x["until_date"] >= s.isoformat()))
        avail = bal - reserve - restr
        rows.append({"week": i + 1, "start": s.isoformat(), "end": e.isoformat(), "opening": r2(o), "in": r2(cin), "out": r2(cout),
                     "net": r2(cin - cout), "closing": r2(bal), "prudent_closing": r2(prudent), "reserve": reserve,
                     "restricted": r2(restr), "available": r2(avail), "gap": r2(max(0.0, -avail)),
                     "prudent_gap": r2(max(0.0, -(prudent - reserve - restr)))})
    by_conf = {k: {"in": r2(sum(ln["total"] for ln in lines if ln["kind"] == "in" and ln["confidence"] == k)),
                   "out": r2(sum(ln["total"] for ln in lines if ln["kind"] == "out" and ln["confidence"] == k))} for k, _l in CONF}
    low = min(rows, key=lambda r: r["closing"])
    gaps = [r for r in rows if r["gap"] > 0.5]
    pgaps = [r for r in rows if r["prudent_gap"] > 0.5]
    return {"today": t, "week0": w0.isoformat(), "opening": opening, "weeks": rows, "lines": lines, "by_confidence": by_conf,
            "reserve": reserve, "restricted": restricted_rows, "lowest": {"week": low["week"], "start": low["start"], "closing": low["closing"]},
            "first_gap": gaps[0]["week"] if gaps else None, "max_gap": r2(max([r["gap"] for r in rows] or [0])),
            "prudent_first_gap": pgaps[0]["week"] if pgaps else None,
            "prudent_max_gap": r2(max([r["prudent_gap"] for r in rows] or [0])),
            "prudent_lowest": r2(min(r["prudent_closing"] for r in rows)), "delay": delay, "overrun": overrun,
            "overdue_days": over_days, "overhead_budgeted": budgeted, "notes": notes}


@api("cfw.forecast")
def cfw_forecast(c, u, a):
    _need(c, u)
    sc = a.get("scenario") or "base"
    s = {k: (d, o) for k, _l, d, o in SCENARIOS}
    if sc == "custom":
        delay, over = int(_f(a.get("delay"))), _f(a.get("overrun"))
    elif sc in s:
        delay, over = s[sc]
    else:
        raise ApiError("Unknown scenario.")
    if delay < 0 or delay > 365 or over < -50 or over > 200:
        raise ApiError("Delay must be 0-365 days and overrun between -50% and 200%.")
    out = build(c, u, delay, over)
    out["scenario"] = sc
    out["scenarios"] = []
    if a.get("compare", True):
        for k, label, d, o in SCENARIOS:
            r = out if (k == sc and sc != "custom") else build(c, u, d, o)
            out["scenarios"].append({"key": k, "label": label, "lowest": r["lowest"], "first_gap": r["first_gap"],
                                     "max_gap": r["max_gap"], "closing": r["weeks"][-1]["closing"],
                                     "prudent_max_gap": r["prudent_max_gap"]})
    out["confidence"] = CONF
    out["scenario_list"] = [(k, l) for k, l, _d2, _o in SCENARIOS] + [("custom", "My own delay and overrun")]
    out["can_edit"] = bool(u.get("role") == "admin" or core.can(u, "accounts", "edit"))
    return out


# ───────────────────────────── manual items and restricted funds ─────────────────────────────
@api("cfw.items")
def cfw_items(c, u, a):
    _need(c, u)
    return q(c, "SELECT * FROM cfw_items WHERE active=1 ORDER BY date, id")


@api("cfw.item_save")
def cfw_item_save(c, u, a):
    _need(c, u, "edit")
    d = {"date": a.get("date"), "kind": a.get("kind"), "amount": r2(_f(a.get("amount"))), "label": (a.get("label") or "").strip(),
         "category": a.get("category") or "other", "project_id": _int(a.get("project_id")),
         "confidence": a.get("confidence") or "likely", "note": a.get("note") or None}
    if not _d(d["date"]):
        raise ApiError("Enter the date.")
    if d["kind"] not in ("in", "out"):
        raise ApiError("Choose money in or money out.")
    if d["amount"] <= 0:
        raise ApiError("Enter an amount above zero.")
    if not d["label"]:
        raise ApiError("Say what it is.")
    if d["confidence"] not in CONF_LABEL:
        raise ApiError("Unknown confidence.")
    if d["category"] not in ("financing", "capital", "land", "tax", "other"):
        raise ApiError("Unknown category.")
    if d["project_id"]:
        get(c, "projects", d["project_id"], "Project")
    rid = _int(a.get("id"))
    if rid:
        get(c, "cfw_items", rid, "Item")
        upd(c, "cfw_items", rid, d)
    else:
        d.update({"created_by": u["id"], "ts": now()})
        rid = ins(c, "cfw_items", d)
    audit(c, u, "save", "cfw_items", rid, d)
    return {"id": rid}


@api("cfw.item_delete")
def cfw_item_delete(c, u, a):
    _need(c, u, "edit")
    get(c, "cfw_items", int(a["id"]), "Item")
    upd(c, "cfw_items", int(a["id"]), {"active": 0})
    audit(c, u, "delete", "cfw_items", int(a["id"]))
    return True


@api("cfw.restricted")
def cfw_restricted(c, u, a):
    _need(c, u)
    return q(c, "SELECT * FROM cfw_restricted WHERE active=1 ORDER BY id")


@api("cfw.restricted_save")
def cfw_restricted_save(c, u, a):
    _need(c, u, "edit")
    d = {"name": (a.get("name") or "").strip(), "amount": r2(_f(a.get("amount"))), "account_id": _int(a.get("account_id")),
         "from_date": a.get("from_date") or None, "until_date": a.get("until_date") or None, "note": a.get("note") or None}
    if not d["name"]:
        raise ApiError("Name the restricted fund (for example: margin money for the performance guarantee).")
    if d["amount"] <= 0:
        raise ApiError("Enter an amount above zero.")
    for k in ("from_date", "until_date"):
        if d[k] and not _d(d[k]):
            raise ApiError("%s is not a date." % k.replace("_", " ").capitalize())
    if d["from_date"] and d["until_date"] and d["until_date"] < d["from_date"]:
        raise ApiError("'Until' is before 'from'.")
    rid = _int(a.get("id"))
    if rid:
        get(c, "cfw_restricted", rid, "Restricted fund")
        upd(c, "cfw_restricted", rid, d)
    else:
        d.update({"created_by": u["id"], "ts": now()})
        rid = ins(c, "cfw_restricted", d)
    audit(c, u, "save", "cfw_restricted", rid, d)
    return {"id": rid}


@api("cfw.restricted_delete")
def cfw_restricted_delete(c, u, a):
    _need(c, u, "edit")
    get(c, "cfw_restricted", int(a["id"]), "Restricted fund")
    upd(c, "cfw_restricted", int(a["id"]), {"active": 0})
    return True


@api("cfw.settings_save")
def cfw_settings_save(c, u, a):
    _need(c, u, "approve")
    n = int(_f(a.get("cfw_overdue_days"), 30))
    if n < 0 or n > 365:
        raise ApiError("Days must be 0 to 365.")
    c.execute("INSERT OR REPLACE INTO settings(key, value) VALUES('cfw_overdue_days', ?)", (str(n),))
    return {"cfw_overdue_days": n}


# ───────────────────────────── snapshots and forecast vs actual ─────────────────────────────
@api("cfw.snapshot_save")
def cfw_snapshot_save(c, u, a):
    _need(c, u, "edit")
    sc = a.get("scenario") or "base"
    d = cfw_forecast(c, u, {"scenario": sc, "delay": a.get("delay"), "overrun": a.get("overrun"), "compare": False})
    slim = {"weeks": d["weeks"], "lines": [{k: ln[k] for k in ("kind", "label", "confidence", "values", "total")} for ln in d["lines"]],
            "by_confidence": d["by_confidence"], "delay": d["delay"], "overrun": d["overrun"],
            "saved_on": d["today"], "last_voucher_id": val(c, "SELECT MAX(id) FROM vouchers") or 0}
    sid = ins(c, "cfw_snapshots", {"label": (a.get("label") or "").strip() or "Forecast of %s" % d["today"], "week0": d["week0"],
                                   "opening": d["opening"], "scenario": sc, "data": json.dumps(slim), "user_id": u["id"],
                                   "user_name": u.get("name") or u.get("username"), "ts": now()})
    return {"id": sid}


@api("cfw.snapshots")
def cfw_snapshots(c, u, a):
    _need(c, u)
    return q(c, "SELECT id, label, week0, opening, scenario, user_name, ts FROM cfw_snapshots ORDER BY id DESC")


def actual_week(c, ids, s, e, after_id=None):
    """Cash that actually moved in a week: per voucher, the net change across the cash and bank accounts
    (a transfer between two of them nets to zero). after_id: only vouchers entered after the forecast was saved,
    for the week the forecast was saved in (its opening already holds what was entered before)."""
    if not ids:
        return 0.0, 0.0
    cin = cout = 0.0
    extra, p = "", [s, e]
    if after_id is not None:
        extra, p = " AND v.id>?", [s, e, after_id]
    for r in q(c, "SELECT v.id, SUM(l.debit-l.credit) net FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id WHERE " + POSTED +
                  " AND l.account_id IN (%s) AND v.date BETWEEN ? AND ?" % ",".join(map(str, ids)) + extra + " GROUP BY v.id", p):
        if r["net"] > 0:
            cin += r["net"]
        else:
            cout += -r["net"]
    return r2(cin), r2(cout)


@api("cfw.snapshot_compare")
def cfw_snapshot_compare(c, u, a):
    _need(c, u)
    snap = get(c, "cfw_snapshots", int(a["id"]), "Snapshot")
    data = json.loads(snap["data"])
    _bal, ids = money_balance(c)
    t = today()
    out = []
    for w in data["weeks"]:
        row = {"week": w["week"], "start": w["start"], "end": w["end"], "f_in": w["in"], "f_out": w["out"], "f_closing": w["closing"]}
        if w["start"] <= t:
            saved = data.get("saved_on")
            first = saved is not None and w["start"] <= saved <= w["end"]
            ai, ao = actual_week(c, ids, w["start"], min(w["end"], t), data.get("last_voucher_id", 0) if first else None)
            closing, _x = money_balance(c, min(w["end"], t))
            row.update({"a_in": ai, "a_out": ao, "a_closing": closing, "v_in": r2(ai - w["in"]), "v_out": r2(ao - w["out"]),
                        "v_closing": r2(closing - w["closing"]), "complete": w["end"] < t})
        out.append(row)
    done = [r for r in out if r.get("complete")]
    acc = None
    if done:
        f = sum(r["f_in"] for r in done)
        acc = r2(100 * sum(r["a_in"] for r in done) / f) if f > 0.5 else None
    return {"snapshot": {k: snap[k] for k in ("id", "label", "week0", "opening", "scenario", "user_name", "ts")}, "weeks": out,
            "receipts_achieved_pct": acc, "lines": data["lines"]}
