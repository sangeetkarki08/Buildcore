"""
Billing, receivables, payables and payment control (BuildCore 2.26).

Phase 3 and 4 of the master development prompt, built on the books that already exist. Nothing here posts a voucher
of its own: payments still go through payment.create (so the cash limit, the 2.19 procurement split and the posting
rules run unchanged), invoices stay the receivable and payable, and every figure is read from the ledger, the IPCs,
the measurements and the BOQ.

  1. IPC lifecycle with dates: prepared, submitted, under review, certified, payment due, overdue, part paid, paid.
     Dates, the person responsible, the next action and a log are kept beside the IPC (fc_ipc, fc_ipc_log); the IPC
     table and its certification posting are unchanged. Work done but not measured, and measured but not billed,
     are shown at BOQ rates as estimates, never as billing.
  2. Receivables in five buckets per project (unbilled, submitted, certified not due, overdue with ageing,
     retention held) and a collection action list with follow-ups and promised dates (fc_follow).
  3. One payables register: supplier, subcontractor and hire bills, VAT and TDS to deposit, wages payable, loan and
     equipment-finance instalments, with open purchase-order commitments and retention payable as information.
  4. Payment requests with a configurable approval chain (fc_payreq, fc_payreq_log): requested, documents verified,
     accounts verified, cash reviewed, approved, paid, reconciled. The approver is never the requester; legally
     required payments cannot be deferred past their due date without a recorded reason and approver note. A
     payment plan sorts requests and dues by obligation against the cash and bank balance less a reserve; it only
     proposes, a person approves and pays.
  5. Financial data checks: ledger balance, controls against invoices by project, internal billing nets to zero,
     duplicate bills, receipts, payments and cheques, uncleared bank items, IPC and invoice agreement, documents
     without vouchers, and stale posting-queue items.
  6. Guards: a payment with a cheque number already used for the same party is refused, and so is posting a
     supplier bill whose supplier invoice number is already booked, unless an accounts approver overrides.
"""
import json
from datetime import date, timedelta

import core
from core import ApiError, audit, get, ins, now, q, q1, r2, setting, today, upd, val
import api_inventory as inv
from api_inventory import api, invoice_paid

VERSION = "2.26.0"

SCHEMA = """
CREATE TABLE IF NOT EXISTS fc_ipc(ipc_id INTEGER PRIMARY KEY, prepared_at TEXT, submitted_at TEXT, review_at TEXT,
  review_by TEXT, certified_at TEXT, expected_pay_date TEXT, responsible TEXT, next_action TEXT, next_action_date TEXT,
  delay_reason TEXT, client_comments TEXT, updated_by INTEGER, updated_at TEXT);
CREATE TABLE IF NOT EXISTS fc_ipc_log(id INTEGER PRIMARY KEY, ipc_id INTEGER, ts TEXT, user_id INTEGER, user_name TEXT,
  kind TEXT, text TEXT);
CREATE INDEX IF NOT EXISTS ix_fcil ON fc_ipc_log(ipc_id);
CREATE TABLE IF NOT EXISTS fc_follow(id INTEGER PRIMARY KEY, kind TEXT, ref_type TEXT, ref_id INTEGER, project_id INTEGER,
  party_id INTEGER, note TEXT, next_date TEXT, promised_date TEXT, promised_amount REAL, user_id INTEGER, user_name TEXT,
  ts TEXT);
CREATE INDEX IF NOT EXISTS ix_fcf ON fc_follow(ref_type, ref_id);
CREATE TABLE IF NOT EXISTS fc_payreq(id INTEGER PRIMARY KEY, no TEXT, date TEXT, party_id INTEGER, project_id INTEGER,
  category TEXT, invoice_id INTEGER, po_id INTEGER, ref TEXT, amount REAL DEFAULT 0, tax_note TEXT, due_date TEXT,
  terms TEXT, proposed_date TEXT, obligation TEXT DEFAULT 'normal', consequence TEXT, deferral_reason TEXT, note TEXT,
  stage TEXT DEFAULT 'requested', payment_id INTEGER, voucher_id INTEGER, paid_at TEXT, paid_by INTEGER,
  created_by INTEGER, created_at TEXT, updated_at TEXT);
CREATE INDEX IF NOT EXISTS ix_fcpr ON fc_payreq(stage);
CREATE INDEX IF NOT EXISTS ix_fcpr_i ON fc_payreq(invoice_id);
CREATE TABLE IF NOT EXISTS fc_payreq_log(id INTEGER PRIMARY KEY, req_id INTEGER, step TEXT, action TEXT, from_stage TEXT,
  to_stage TEXT, user_id INTEGER, user_name TEXT, note TEXT, ts TEXT);
CREATE INDEX IF NOT EXISTS ix_fcprl ON fc_payreq_log(req_id);
"""

STEP_DEFAULTS = {"docs": ["payreq", "edit"], "accounts": ["accounts", "edit"], "cash": ["accounts", "approve"],
                 "approve": ["payreq", "approve"], "pay": ["accounts", "edit"]}
DEFAULTS = {"fc_statutory_due_day": "25",     # VAT and TDS for a month are deposited by this day of the next month
            "fc_cash_reserve": "0",           # cash kept back in the payment plan
            "fc_payreq_strict": "0",          # 1 = one person may do only one step of a request
            "fc_payreq_self_approve": "0",    # 1 = the requester may also approve (one-person offices only)
            "fc_payreq_steps": json.dumps(STEP_DEFAULTS),
            "fc_stale_days": "30"}            # bank items and posting-queue items older than this are flagged

STAGES = [("requested", "Requested"), ("docs_verified", "Documents verified"), ("accounts_verified", "Accounts verified"),
          ("cash_reviewed", "Cash reviewed"), ("approved", "Approved"), ("paid", "Paid"), ("reconciled", "Reconciled"),
          ("returned", "Returned"), ("rejected", "Rejected"), ("cancelled", "Cancelled")]
STAGE_LABEL = dict(STAGES)
OPEN_STAGES = ("requested", "docs_verified", "accounts_verified", "cash_reviewed", "approved", "returned")
FLOW = {"verify_docs": ("requested", "docs_verified", "docs"),
        "verify_accounts": ("docs_verified", "accounts_verified", "accounts"),
        "review_cash": ("accounts_verified", "cash_reviewed", "cash"),
        "approve": ("cash_reviewed", "approved", "approve")}
NEXT_STEP = {"requested": "docs", "docs_verified": "accounts", "accounts_verified": "cash", "cash_reviewed": "approve",
             "approved": "pay"}
STEP_LABEL = {"docs": "Verify documents", "accounts": "Verify accounts", "cash": "Review cash", "approve": "Approve",
              "pay": "Pay"}
CATEGORIES = [("supplier", "Supplier"), ("subcontractor", "Subcontractor"), ("equipment", "Equipment hire"),
              ("advance", "Advance"), ("statutory", "Tax and statutory"), ("payroll", "Wages and salaries"),
              ("loan", "Loan or equipment instalment"), ("other", "Other")]
CAT_LABEL = dict(CATEGORIES)
OBLIGATIONS = [("statutory", "Statutory (tax, social security)"), ("payroll", "Wages and salaries"),
               ("safety", "Safety-critical"), ("contractual", "Contractual (subcontract, loan, hire)"),
               ("operational", "Operational (keeps work going)"), ("normal", "Normal")]
OBL_RANK = {k: i + 1 for i, (k, _l) in enumerate(OBLIGATIONS)}
LEGAL = ("statutory", "payroll", "safety", "contractual")
IPC_STAGES = [("unmeasured", "Work done, not measured"), ("unbilled", "Measured, not billed"),
              ("prepared", "IPC prepared"), ("submitted", "Submitted"), ("under_review", "Under review"),
              ("certified", "Certified, payment due"), ("overdue", "Payment overdue"), ("part_paid", "Partly paid"),
              ("paid", "Paid")]
IPC_STAGE_LABEL = dict(IPC_STAGES)
RIGHTS = {
    "director": ["view", "approve", "export"],
    "finance_manager": ["view", "create", "edit", "approve", "post", "export"],
    "accountant": ["view", "create", "edit", "post"],
    "project_accountant": ["view", "create", "edit"],
    "project_manager": ["view", "create"], "procurement_officer": ["view", "create"],
    "quantity_surveyor": ["view", "create"], "equipment_manager": ["view", "create"],
    "viewer": ["view"]}
NEW_MODULES = ("payreq",)


# ───────────────────────────── start-up ─────────────────────────────
def init_fc(c):
    c.executescript(SCHEMA)
    for k, v in DEFAULTS.items():
        if q1(c, "SELECT key FROM settings WHERE key=?", (k,)) is None:
            c.execute("INSERT INTO settings(key, value) VALUES(?,?)", (k, v))
    for m in NEW_MODULES:
        if m not in core.MODULES:
            core.MODULES.append(m)
    _seed_rights(c)
    _install()


def _seed_rights(c):
    if setting(c, "fc_rights_seeded") == "1":
        return
    try:
        have = {r[1] for r in c.execute("PRAGMA table_info(ws_roles)")}
    except Exception:
        have = set()
    if not have:
        return
    for key, acts in RIGHTS.items():
        r = q1(c, "SELECT id, perms FROM ws_roles WHERE key=? AND builtin=1", (key,))
        if not r:
            continue
        try:
            p = json.loads(r["perms"] or "{}")
        except ValueError:
            p = {}
        if "payreq" not in p:
            p["payreq"] = acts
        c.execute("UPDATE ws_roles SET perms=? WHERE id=?", (json.dumps(p), r["id"]))
    c.execute("INSERT OR REPLACE INTO settings(key, value) VALUES('fc_rights_seeded','1')")
    try:
        import api_workspace as W
        W.load_roles(c)
    except Exception:
        pass


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


def _days(a, b):
    """b - a in days (None when either is missing)."""
    da, db = _d(a), _d(b)
    return (db - da).days if da and db else None


def _add_days(s, n):
    d = _d(s)
    return (d + timedelta(days=int(n or 0))).isoformat() if d else None


def _add_months(s, n):
    d = _d(s)
    if not d:
        return None
    m = d.month - 1 + n
    y, m = d.year + m // 12, m % 12 + 1
    last = (date(y + (m // 12), m % 12 + 1, 1) - timedelta(days=1)).day
    return date(y, m, min(d.day, last)).isoformat()


def _uname(u):
    return (u or {}).get("name") or (u or {}).get("username")


def right(c, u, module, action):
    """Rights on the 2.26 payreq row; other modules follow the role (2.20 templates, read by core.can)."""
    if not u:
        return False
    if u.get("role") == "admin" or u.get("system"):
        return True
    if module != "payreq":
        return core.can(u, module, action)
    t = None
    try:
        import api_workspace as W
        t = W.roles(c).get(u["role"])
    except Exception:
        t = None
    if t is not None and "payreq" in (t.get("perms") or {}):
        return action in set(t["perms"].get("payreq") or ())
    # a role made before 2.26 follows its accounts and procurement rights
    if action in ("view", "export"):
        return core.can(u, "accounts", "view") or core.can(u, "procurement", "view")
    if action == "create":
        return core.can(u, "accounts", "edit") or core.can(u, "procurement", "edit")
    if action == "post":
        return core.can(u, "accounts", "edit")
    return core.can(u, "accounts", action)


def need_any(c, u, pairs, what):
    if not any(right(c, u, m, a) for m, a in pairs):
        raise ApiError("Your role cannot %s (needs %s in Administration > Users and roles)."
                       % (what, " or ".join("'%s' on %s" % (a, m) for m, a in pairs)))


def allowed(c, u):
    try:
        import api_workspace as W
        return W.allowed_projects(c, u) if u else None
    except Exception:
        return None


def check_project(c, u, pid):
    al = allowed(c, u)
    if pid and al is not None and int(pid) not in al:
        raise ApiError("PROJECT_DENIED: you are not assigned to this project.")


def project_ids(c, u, a):
    """Projects to report on: the one asked for (checked), else every project the user may see."""
    pid = _int(a.get("project_id"))
    if pid:
        check_project(c, u, pid)
        return [pid]
    al = allowed(c, u)
    rows = [r["id"] for r in q(c, "SELECT id FROM projects ORDER BY id")]
    return rows if al is None else [p for p in rows if p in al]


def company_wide(c, u, a):
    """Company-level items (VAT, TDS, loans) are shown only to people who see every project, and only unfiltered."""
    return not a.get("project_id") and allowed(c, u) is None


def _projects(c):
    return {p["id"]: p for p in q(c, "SELECT * FROM projects")}


def _parties(c):
    return {p["id"]: p for p in q(c, "SELECT id, name, kind, credit_days FROM parties")}


def role_balance(c, role, pid=None, to=None, frm=None):
    w = "a.role=? AND v.status IN ('posted','reversed')"
    p = [role]
    if pid:
        w += " AND l.project_id=?"
        p.append(pid)
    if to:
        w += " AND v.date<=?"
        p.append(to)
    if frm:
        w += " AND v.date>=?"
        p.append(frm)
    b = val(c, "SELECT SUM(l.debit-l.credit) FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id JOIN accounts a "
               "ON a.id=l.account_id WHERE " + w, p)
    if not pid and not frm:
        b += val(c, "SELECT SUM(opening_balance) FROM accounts WHERE role=?", (role,))
    return r2(b or 0.0)


def _m(x):
    return "{:,.2f}".format(x or 0)


def bucket_of(days_to_due):
    """days_to_due: due date minus today."""
    if days_to_due is None:
        return "nodate"
    if days_to_due < 0:
        return "overdue"
    if days_to_due <= 7:
        return "d7"
    if days_to_due <= 30:
        return "d30"
    if days_to_due <= 90:
        return "d90"
    return "later"


BUCKETS = [("overdue", "Overdue"), ("d7", "Due in 7 days"), ("d30", "Due in 8-30 days"), ("d90", "Due in 31-90 days"),
           ("later", "Later"), ("nodate", "No due date")]


def age_bucket(days_over):
    if days_over <= 30:
        return "a30"
    if days_over <= 60:
        return "a60"
    if days_over <= 90:
        return "a90"
    return "a90p"


def terms(c, p):
    try:
        import api_cash as CA
        return CA.terms(c, p)
    except Exception:
        return {"ipc_cycle_days": 30, "cert_days": 21, "pay_days": 28, "retention_release_pct": 50, "dlp_months": 12,
                "labour_pay_days": 7}


def inv_open(c, i):
    return r2((i["payable"] or 0) - invoice_paid(c, i["id"]))


# ───────────────────────────── IPC lifecycle ─────────────────────────────
def fc_row(c, ipc_id):
    return q1(c, "SELECT * FROM fc_ipc WHERE ipc_id=?", (ipc_id,))


def ensure_fc(c, ipc_id):
    if not fc_row(c, ipc_id):
        c.execute("INSERT INTO fc_ipc(ipc_id, updated_at) VALUES(?,?)", (ipc_id, now()))
    return fc_row(c, ipc_id)


def ipc_log(c, u, ipc_id, kind, text):
    ins(c, "fc_ipc_log", {"ipc_id": ipc_id, "ts": now(), "user_id": (u or {}).get("id"), "user_name": _uname(u),
                          "kind": kind, "text": text})


def ipc_state(c, i, f=None, t=None):
    """Stage of one IPC, with its dates. Old IPCs without 2.26 dates fall back to the IPC and invoice dates."""
    t = t or today()
    f = f or fc_row(c, i["id"]) or {}
    p = q1(c, "SELECT * FROM projects WHERE id=?", (i["project_id"],)) or {}
    tm = terms(c, p)
    out = {"id": i["id"], "no": i["no"], "project_id": i["project_id"], "party_id": i["client_id"], "date": i["date"],
           "period_to": i["period_to"], "status": i["status"], "claimed_net": r2(i["net"] or 0),
           "claimed_gross": r2(i["gross"] or 0), "submitted_at": f.get("submitted_at"), "review_at": f.get("review_at"),
           "review_by": f.get("review_by"), "certified_at": f.get("certified_at"), "responsible": f.get("responsible"),
           "next_action": f.get("next_action"), "next_action_date": f.get("next_action_date"),
           "delay_reason": f.get("delay_reason"), "client_comments": f.get("client_comments"),
           "expected_pay_date": f.get("expected_pay_date"), "invoice_id": i["invoice_id"], "invoice_no": None,
           "due_date": None, "payable": None, "paid": 0.0, "outstanding": None, "cert_due": None,
           "cert_overdue_days": 0, "pay_overdue_days": 0, "days_in_stage": None, "amount": r2(i["net"] or 0)}
    if i["status"] == "draft":
        out["stage"] = "prepared"
        out["days_in_stage"] = _days(f.get("prepared_at") or i["date"], t)
    elif i["status"] == "submitted":
        out["stage"] = "under_review" if f.get("review_at") else "submitted"
        base = f.get("submitted_at") or i["date"]
        out["cert_due"] = _add_days(base, tm.get("cert_days") or 21)
        out["cert_overdue_days"] = max(0, _days(out["cert_due"], t) or 0)
        out["days_in_stage"] = _days(f.get("review_at") or base, t)
    else:
        inv_ = q1(c, "SELECT * FROM invoices WHERE id=?", (i["invoice_id"],)) if i["invoice_id"] else None
        if not inv_:
            out.update(stage="certified", amount=r2(i["net"] or 0))
            return out
        paid = r2(invoice_paid(c, inv_["id"]))
        bal = r2((inv_["payable"] or 0) - paid)
        out.update(invoice_no=inv_["no"], due_date=inv_["due_date"], payable=r2(inv_["payable"] or 0), paid=paid,
                   outstanding=bal, certified_at=f.get("certified_at") or inv_["date"])
        out["expected_pay_date"] = f.get("expected_pay_date") or inv_["due_date"]
        if inv_["status"] == "cancelled":
            out.update(stage="certified", amount=0.0)
        elif bal <= 0.5:
            out.update(stage="paid", amount=out["payable"])
            last = val(c, "SELECT MAX(date) FROM allocations WHERE invoice_id=? AND active=1", (inv_["id"],), None)
            out["paid_at"] = last
        else:
            od = _days(inv_["due_date"] or inv_["date"], t) or 0
            out["pay_overdue_days"] = max(0, od)
            out["stage"] = "part_paid" if paid > 0.5 else ("overdue" if od > 0 else "certified")
            out["amount"] = bal
        out["days_in_stage"] = _days(out["certified_at"], t)
    return out


def unbilled(c, pid):
    """Per BOQ item at the current rate: executed (site progress) not yet measured, and verified measurement not yet
    claimed. These are estimates for planning collections. They are never billing: only a certified IPC is."""
    rows = []
    tot_um = tot_mb = tot_dr = 0.0
    for b in q(c, "SELECT * FROM boq_items WHERE project_id=? ORDER BY code", (pid,)):
        rate = b["revised_rate"] if b["revised_rate"] is not None else (b["rate"] or 0)
        measured = val(c, "SELECT SUM(l.qty) FROM measurement_lines l JOIN measurements m ON m.id=l.measurement_id "
                          "WHERE m.status='verified' AND l.boq_item_id=?", (b["id"],))
        billed = val(c, "SELECT SUM(l.qty) FROM ipc_lines l JOIN ipc i ON i.id=l.ipc_id WHERE i.status IN "
                        "('submitted','certified') AND l.boq_item_id=?", (b["id"],))
        draft = val(c, "SELECT SUM(l.qty) FROM ipc_lines l JOIN ipc i ON i.id=l.ipc_id WHERE i.status='draft' AND "
                       "l.boq_item_id=?", (b["id"],))
        executed = b["executed_qty"] or 0
        um = max(0.0, executed - measured)
        mb = max(0.0, measured - billed - draft)
        if um * rate < 0.5 and mb * rate < 0.5 and draft * rate < 0.5:
            continue
        rows.append({"boq_item_id": b["id"], "code": b["code"], "description": b["description"], "unit": b["unit"],
                     "rate": rate, "executed": round(executed, 4), "measured": round(measured, 4),
                     "billed": round(billed, 4), "in_draft": round(draft, 4), "unmeasured_qty": round(um, 4),
                     "unmeasured_value": r2(um * rate), "unbilled_qty": round(mb, 4), "unbilled_value": r2(mb * rate)})
        tot_um += um * rate
        tot_mb += mb * rate
        tot_dr += draft * rate
    return {"rows": rows, "unmeasured": r2(tot_um), "unbilled": r2(tot_mb), "in_draft": r2(tot_dr)}


@api("fc.meta")
def fc_meta(c, u, a):
    steps = _steps(c)
    return {"version": VERSION, "stages": STAGES, "categories": CATEGORIES, "obligations": OBLIGATIONS,
            "ipc_stages": IPC_STAGES, "buckets": BUCKETS, "steps": steps, "step_label": STEP_LABEL,
            "settings": {k: setting(c, k) if setting(c, k) not in (None, "") else v for k, v in DEFAULTS.items()},
            "rights": {"payreq": {x: right(c, u, "payreq", x) for x in ("view", "create", "edit", "approve", "post", "export")},
                       "accounts_edit": right(c, u, "accounts", "edit"), "accounts_approve": right(c, u, "accounts", "approve"),
                       "commercial_edit": right(c, u, "commercial", "edit"), "accounts_view": right(c, u, "accounts", "view"),
                       "commercial_view": right(c, u, "commercial", "view"),
                       "steps": {k: _can_step(c, u, k) for k in STEP_LABEL}}}


@api("fc.ipc_board")
def fc_ipc_board(c, u, a):
    need_any(c, u, [("commercial", "view"), ("accounts", "view")], "see the billing pipeline")
    pid = _int(a.get("project_id"))
    if not pid:
        raise ApiError("Choose a project first.")
    check_project(c, u, pid)
    t = today()
    p = q1(c, "SELECT * FROM projects WHERE id=?", (pid,)) or {}
    ub = unbilled(c, pid)
    ipcs = [ipc_state(c, i, t=t) for i in q(c, "SELECT * FROM ipc WHERE project_id=? ORDER BY date, id", (pid,))]
    for x in ipcs:
        x["stage_label"] = IPC_STAGE_LABEL.get(x["stage"], x["stage"])
        x["responsible"] = x["responsible"] or p.get("pm_name") or None
        lf = q1(c, "SELECT * FROM fc_follow WHERE ref_type='ipc' AND ref_id=? ORDER BY id DESC LIMIT 1", (x["id"],))
        x["last_follow"] = lf
    summary = []
    for k, label in IPC_STAGES:
        if k == "unmeasured":
            summary.append({"key": k, "label": label, "count": None, "amount": ub["unmeasured"], "estimate": True})
        elif k == "unbilled":
            summary.append({"key": k, "label": label, "count": None, "amount": ub["unbilled"], "estimate": True})
        else:
            xs = [x for x in ipcs if x["stage"] == k]
            summary.append({"key": k, "label": label, "count": len(xs), "amount": r2(sum(x["amount"] or 0 for x in xs))})
    return {"project_id": pid, "terms": terms(c, p), "summary": summary, "ipcs": ipcs, "unbilled": ub,
            "today": t, "pm_name": p.get("pm_name")}


@api("fc.ipc_detail")
def fc_ipc_detail(c, u, a):
    need_any(c, u, [("commercial", "view"), ("accounts", "view")], "see the billing pipeline")
    i = get(c, "ipc", int(a["id"]), "IPC")
    check_project(c, u, i["project_id"])
    s = ipc_state(c, i)
    s["stage_label"] = IPC_STAGE_LABEL.get(s["stage"], s["stage"])
    s["expected_set"] = (fc_row(c, i["id"]) or {}).get("expected_pay_date")
    s["log"] = q(c, "SELECT * FROM fc_ipc_log WHERE ipc_id=? ORDER BY id DESC", (i["id"],))
    s["follow"] = q(c, "SELECT * FROM fc_follow WHERE ref_type='ipc' AND ref_id=? ORDER BY id DESC", (i["id"],))
    s["receipts"] = q(c, "SELECT a.date, a.amount, p.no FROM allocations a LEFT JOIN payments p ON p.id=a.payment_id "
                         "WHERE a.invoice_id=? AND a.active=1 ORDER BY a.date", (i["invoice_id"] or 0,))
    return s


TRACK_FIELDS = ("review_at", "review_by", "expected_pay_date", "responsible", "next_action", "next_action_date",
                "delay_reason", "client_comments")


@api("fc.ipc_update")
def fc_ipc_update(c, u, a):
    """Tracking only: dates, person responsible, next action. The IPC, its lines and its invoice never change here."""
    need_any(c, u, [("commercial", "edit"), ("accounts", "edit")], "update IPC tracking")
    i = get(c, "ipc", int(a["id"]), "IPC")
    check_project(c, u, i["project_id"])
    f = ensure_fc(c, i["id"])
    ch = {}
    for k in TRACK_FIELDS:
        if k in a:
            v = (str(a[k]).strip() or None) if a[k] is not None else None
            if k in ("review_at", "expected_pay_date", "next_action_date") and v and not _d(v):
                raise ApiError("%s is not a date." % k.replace("_", " ").capitalize())
            if v != f.get(k):
                ch[k] = v
    if "review_at" in ch and ch["review_at"] and i["status"] != "submitted":
        raise ApiError("Only a submitted IPC can be marked under review.")
    if not ch:
        return {"changed": 0}
    ch.update({"updated_by": u["id"], "updated_at": now()})
    c.execute("UPDATE fc_ipc SET %s WHERE ipc_id=?" % ",".join(k + "=?" for k in ch), list(ch.values()) + [i["id"]])
    ipc_log(c, u, i["id"], "update", "; ".join("%s: %s" % (k.replace("_", " "), ch[k] or "cleared")
                                               for k in ch if k not in ("updated_by", "updated_at")))
    return {"changed": len(ch) - 2}


@api("fc.ipc_note")
def fc_ipc_note(c, u, a):
    need_any(c, u, [("commercial", "edit"), ("accounts", "edit")], "add a note to an IPC")
    i = get(c, "ipc", int(a["id"]), "IPC")
    check_project(c, u, i["project_id"])
    text = (a.get("text") or "").strip()
    if not text:
        raise ApiError("Write the note first.")
    ensure_fc(c, i["id"])
    ipc_log(c, u, i["id"], a.get("kind") or "note", text[:2000])
    return True


# wrappers on the IPC endpoints: stamp the dates, then call the original unchanged
def _ipc_save_w(orig):
    def ipc_save2(c, u, a):
        new = not (a.get("header") or {}).get("id")
        res = orig(c, u, a)
        if new and res and res.get("id"):
            ensure_fc(c, res["id"])
            c.execute("UPDATE fc_ipc SET prepared_at=? WHERE ipc_id=?", (today(), res["id"]))
            ipc_log(c, u, res["id"], "prepared", "IPC prepared")
        return res
    return ipc_save2


def _ipc_submit_w(orig):
    def ipc_submit2(c, u, a):
        res = orig(c, u, a)
        ensure_fc(c, int(a["id"]))
        c.execute("UPDATE fc_ipc SET submitted_at=?, review_at=NULL, updated_at=? WHERE ipc_id=?",
                  (a.get("submitted_at") or today(), now(), int(a["id"])))
        ipc_log(c, u, int(a["id"]), "submitted", "Submitted to the client / consultant")
        return res
    return ipc_submit2


def _ipc_return_w(orig):
    def ipc_return2(c, u, a):
        res = orig(c, u, a)
        ensure_fc(c, int(a["id"]))
        c.execute("UPDATE fc_ipc SET review_at=NULL, updated_at=? WHERE ipc_id=?", (now(), int(a["id"])))
        ipc_log(c, u, int(a["id"]), "returned", "Returned for revision" + (": " + a["reason"] if a.get("reason") else ""))
        return res
    return ipc_return2


def _ipc_certify_w(orig):
    def ipc_certify2(c, u, a):
        res = orig(c, u, a)
        ensure_fc(c, int(a["id"]))
        c.execute("UPDATE fc_ipc SET certified_at=?, updated_at=? WHERE ipc_id=?", (a.get("date") or today(), now(),
                                                                                  int(a["id"])))
        ipc_log(c, u, int(a["id"]), "certified", "Certified; receivable %s" % r2((res or {}).get("net") or 0))
        return res
    return ipc_certify2


def _ipc_uncertify_w(orig):
    def ipc_uncertify2(c, u, a):
        res = orig(c, u, a)
        ensure_fc(c, int(a["id"]))
        c.execute("UPDATE fc_ipc SET certified_at=NULL, updated_at=? WHERE ipc_id=?", (now(), int(a["id"])))
        ipc_log(c, u, int(a["id"]), "uncertified", "Certification reversed" + (": " + a["reason"] if a.get("reason") else ""))
        return res
    return ipc_uncertify2


# ───────────────────────────── receivables ─────────────────────────────
def retention_info(c, p, held, t):
    tm = terms(c, p)
    comp = p.get("completion_date")
    rel = _f(tm.get("retention_release_pct"), 50)
    out = {"held": held, "completion_date": comp, "first_release_pct": rel, "first_release": r2(held * rel / 100),
           "dlp_months": tm.get("dlp_months"), "first_date": comp, "final_date": None, "eligible_now": 0.0,
           "note": None}
    if not comp:
        out["note"] = "Not available: no completion date in the project's contract terms."
        return out
    out["final_date"] = _add_months(comp, int(_f(tm.get("dlp_months"), 12)))
    if t >= comp:
        out["eligible_now"] = out["first_release"]
    if out["final_date"] and t >= out["final_date"]:
        out["eligible_now"] = held
    out["note"] = ("Release follows the taking-over and defects certificates; the dates are from the contract "
                   "completion date and defects liability period in the project terms.")
    return out


@api("fc.receivables")
def fc_receivables(c, u, a):
    need_any(c, u, [("accounts", "view"), ("commercial", "view")], "see receivables")
    t = a.get("as_of") or today()
    projs = _projects(c)
    out = []
    for pid in project_ids(c, u, a):
        p = projs.get(pid) or {}
        ub = unbilled(c, pid)
        ipcs = [ipc_state(c, i, t=t) for i in q(c, "SELECT * FROM ipc WHERE project_id=? AND status IN "
                                                   "('draft','submitted')", (pid,))]
        sub = r2(sum(x["claimed_net"] for x in ipcs if x["status"] == "submitted"))
        cert_late = r2(sum(x["claimed_net"] for x in ipcs if x["status"] == "submitted" and x["cert_overdue_days"] > 0))
        notdue = 0.0
        ages = {"a30": 0.0, "a60": 0.0, "a90": 0.0, "a90p": 0.0}
        invs = []
        for i in q(c, "SELECT * FROM invoices WHERE kind='sales' AND status='posted' AND project_id=? AND date<=?",
                   (pid, t)):
            paid = val(c, "SELECT SUM(amount) FROM allocations WHERE invoice_id=? AND active=1 AND date<=?", (i["id"], t))
            bal = r2((i["payable"] or 0) - paid)
            if bal <= 0.5:
                continue
            od = _days(i["due_date"] or i["date"], t) or 0
            if od > 0:
                ages[age_bucket(od)] += bal
            else:
                notdue += bal
            invs.append({"id": i["id"], "no": i["no"], "party_id": i["party_id"], "date": i["date"],
                         "due_date": i["due_date"], "balance": bal, "days_overdue": max(0, od), "source": i["source"]})
        held = r2(role_balance(c, "retention_receivable", pid, to=t))
        if not (ub["unmeasured"] or ub["unbilled"] or ub["in_draft"] or sub or notdue or sum(ages.values())
                or abs(held) > 0.5) and p.get("kind") in ("trading", "general"):
            continue
        adv = r2(-role_balance(c, "client_advance", pid, to=t))
        out.append({"project_id": pid, "code": p.get("code"), "name": p.get("name"),
                    "unmeasured": ub["unmeasured"], "unbilled": ub["unbilled"], "in_draft": ub["in_draft"],
                    "submitted": sub, "cert_overdue": cert_late, "not_due": r2(notdue),
                    "overdue": r2(sum(ages.values())), "ages": {k: r2(v) for k, v in ages.items()},
                    "retention": retention_info(c, p, held, t), "client_advance": adv, "invoices": invs})
    tot = {k: r2(sum(r[k] for r in out)) for k in ("unmeasured", "unbilled", "in_draft", "submitted", "not_due", "overdue")}
    tot["retention"] = r2(sum(r["retention"]["held"] for r in out))
    return {"as_of": t, "rows": out, "totals": tot}


def _responsible(f, p):
    return (f or {}).get("responsible") or (p or {}).get("pm_name") or None


def collection_tasks(c, u, a):
    t = today()
    projs = _projects(c)
    out = []

    def last_follow(ref_type, ref_id):
        return q1(c, "SELECT * FROM fc_follow WHERE ref_type=? AND ref_id=? ORDER BY id DESC LIMIT 1", (ref_type, ref_id))

    def add(**k):
        lf = last_follow(k["ref_type"], k["ref_id"])
        k["last_follow"] = lf
        if lf and lf.get("next_date"):
            k["target_date"] = lf["next_date"]
        k["promised_date"] = (lf or {}).get("promised_date")
        k["promised_amount"] = (lf or {}).get("promised_amount")
        k["late_days"] = max(0, _days(k.get("target_date"), t) or 0) if k.get("target_date") else 0
        out.append(k)
    for pid in project_ids(c, u, a):
        p = projs.get(pid) or {}
        tm = terms(c, p)
        ub = unbilled(c, pid)
        party = None
        if ub["unmeasured"] > 0.5:
            add(key="meas:%d" % pid, action="complete_measurement", label="Complete measurements", project_id=pid,
                party_id=party, ref_type="project_meas", ref_id=pid, amount=ub["unmeasured"],
                target_date=None, responsible=p.get("pm_name"), rank=5,
                detail="Work reported done but not yet measured and verified (estimate at BOQ rates).")
        if ub["unbilled"] > 0.5:
            last = q1(c, "SELECT MAX(period_to) d FROM ipc WHERE project_id=? AND status IN ('submitted','certified')", (pid,))
            target = _add_days(last["d"], tm.get("ipc_cycle_days") or 30) if last and last["d"] else None
            add(key="bill:%d" % pid, action="prepare_ipc", label="Prepare IPC", project_id=pid, party_id=party,
                ref_type="project_bill", ref_id=pid, amount=ub["unbilled"], target_date=target,
                responsible=p.get("pm_name"), rank=4, detail="Verified measurement not yet claimed in an IPC.")
        for i in q(c, "SELECT * FROM ipc WHERE project_id=? AND status IN ('draft','submitted','certified')", (pid,)):
            f = fc_row(c, i["id"]) or {}
            s = ipc_state(c, i, f, t)
            base = dict(project_id=pid, party_id=i["client_id"], ref_type="ipc", ref_id=i["id"], ref_no=i["no"],
                        responsible=_responsible(f, p))
            if s["stage"] == "prepared":
                add(key="ipc:%d" % i["id"], action="submit_ipc", label="Submit IPC", amount=s["claimed_net"],
                    target_date=f.get("next_action_date"), rank=3, detail=f.get("next_action") or "Draft IPC waiting to go out.",
                    **base)
            elif s["stage"] in ("submitted", "under_review"):
                add(key="ipc:%d" % i["id"], action="obtain_certification",
                    label="Resolve comments and obtain certification" if f.get("client_comments") else "Obtain certification",
                    amount=s["claimed_net"], target_date=f.get("next_action_date") or s["cert_due"], rank=2,
                    detail=f.get("next_action") or f.get("client_comments") or "Waiting for the consultant's certificate.",
                    **base)
            elif s["stage"] in ("certified", "overdue", "part_paid"):
                late = s["pay_overdue_days"] > 0
                add(key="ipc:%d" % i["id"], action="escalate_overdue" if late else "follow_payment",
                    label="Escalate overdue payment" if late else "Follow up payment", amount=s["outstanding"],
                    target_date=f.get("next_action_date") or s["expected_pay_date"], rank=1 if late else 2,
                    detail=(f.get("delay_reason") or "Overdue %d days" % s["pay_overdue_days"]) if late
                    else "Certified; due %s." % (s["due_date"] or ""), **base)
        # other sales invoices (not from an IPC)
        for i in q(c, "SELECT * FROM invoices WHERE kind='sales' AND status='posted' AND project_id=? AND "
                      "COALESCE(source,'')<>'ipc'", (pid,)):
            bal = inv_open(c, i)
            if bal <= 0.5:
                continue
            od = _days(i["due_date"] or i["date"], t) or 0
            add(key="inv:%d" % i["id"], action="escalate_overdue" if od > 0 else "follow_payment",
                label="Escalate overdue payment" if od > 0 else "Follow up payment", project_id=pid,
                party_id=i["party_id"], ref_type="invoice", ref_id=i["id"], ref_no=i["no"], amount=bal,
                target_date=i["due_date"], responsible=p.get("pm_name"), rank=1 if od > 0 else 2,
                detail="Sales invoice %s" % (i["party_inv_no"] or i["no"]))
        held = role_balance(c, "retention_receivable", pid)
        if held > 0.5:
            ri = retention_info(c, p, r2(held), t)
            if ri["eligible_now"] > 0.5:
                add(key="ret:%d" % pid, action="request_retention", label="Request retention release", project_id=pid,
                    party_id=None, ref_type="retention", ref_id=pid, amount=ri["eligible_now"],
                    target_date=ri["first_date"] if ri["eligible_now"] < held - 0.5 else ri["final_date"],
                    responsible=p.get("pm_name"), rank=3, detail="Retention eligible for release under the contract terms.")
    for x in out:
        x["responsible"] = x.get("responsible") or "Not assigned"
        x["label_full"] = x["label"] + (" " + x["ref_no"] if x.get("ref_no") else "")
    out.sort(key=lambda x: (-(x["late_days"] or 0) if x["late_days"] else 0, x["rank"], x.get("target_date") or "9999"))
    return out


@api("fc.collections")
def fc_collections(c, u, a):
    need_any(c, u, [("accounts", "view"), ("commercial", "view")], "see collection actions")
    rows = collection_tasks(c, u, a)
    return {"rows": rows, "total": r2(sum(r["amount"] or 0 for r in rows if r["action"] not in ("complete_measurement",))),
            "late": len([r for r in rows if r["late_days"]])}


REF_TYPES = ("ipc", "invoice", "project_meas", "project_bill", "retention", "payable", "payreq")


@api("fc.follow_save")
def fc_follow_save(c, u, a):
    need_any(c, u, [("accounts", "edit"), ("commercial", "edit")], "record a follow-up")
    rt = a.get("ref_type")
    if rt not in REF_TYPES:
        raise ApiError("Unknown follow-up subject.")
    rid = _int(a.get("ref_id"))
    pid = _int(a.get("project_id"))
    if rt == "ipc":
        i = get(c, "ipc", rid, "IPC")
        pid = i["project_id"]
    elif rt in ("invoice", "payable"):
        i = get(c, "invoices", rid, "Invoice")
        pid = i["project_id"]
    elif rt in ("project_meas", "project_bill", "retention"):
        pid = rid
    check_project(c, u, pid)
    note = (a.get("note") or "").strip()
    if not note:
        raise ApiError("Write what was done or agreed.")
    for k in ("next_date", "promised_date"):
        if a.get(k) and not _d(a[k]):
            raise ApiError("%s is not a date." % k.replace("_", " ").capitalize())
    amt = _f(a.get("promised_amount"), None) if a.get("promised_amount") not in (None, "") else None
    if amt is not None and amt < 0:
        raise ApiError("A promised amount cannot be negative.")
    fid = ins(c, "fc_follow", {"kind": "ap" if rt in ("payable", "payreq") else "ar", "ref_type": rt, "ref_id": rid,
                               "project_id": pid, "party_id": _int(a.get("party_id")), "note": note[:2000],
                               "next_date": a.get("next_date") or None, "promised_date": a.get("promised_date") or None,
                               "promised_amount": amt, "user_id": u["id"], "user_name": _uname(u), "ts": now()})
    if rt == "ipc":
        ensure_fc(c, rid)
        ipc_log(c, u, rid, "follow_up", note[:2000])
    return {"id": fid}


@api("fc.follow_list")
def fc_follow_list(c, u, a):
    need_any(c, u, [("accounts", "view"), ("commercial", "view")], "see follow-ups")
    rows = q(c, "SELECT * FROM fc_follow WHERE ref_type=? AND ref_id=? ORDER BY id DESC", (a.get("ref_type"), _int(a.get("ref_id"))))
    for r in rows:
        check_project(c, u, r["project_id"])
    return rows


# ───────────────────────────── payables ─────────────────────────────
def _statutory_rows(c, t):
    """VAT and TDS to deposit. A month's balance is due by the set day of the next month (Nepal: the 25th)."""
    day = int(_f(setting(c, "fc_statutory_due_day"), 25)) or 25
    td = _d(t)
    month_start = td.replace(day=1).isoformat()
    prev_due = td.replace(day=min(day, 28)).isoformat()
    nxt = (td.replace(day=28) + timedelta(days=4)).replace(day=min(day, 28)).isoformat()
    out = []
    # TDS: what was withheld before this month is due this month; this month's withholding is due next month
    tds_all = -role_balance(c, "tds_payable", to=t)
    tds_this = -role_balance(c, "tds_payable", frm=month_start, to=t)
    tds_old = r2(tds_all - max(0.0, tds_this))
    if tds_old > 0.5:
        out.append({"label": "TDS withheld up to %s" % (td.replace(day=1) - timedelta(days=1)).isoformat(), "amount": tds_old,
                    "due_date": prev_due, "ref": "tds_prev"})
    if tds_this > 0.5:
        out.append({"label": "TDS withheld this month", "amount": r2(min(tds_this, tds_all)), "due_date": nxt, "ref": "tds_cur"})
    vat_all = -(role_balance(c, "vat_output", to=t) + role_balance(c, "vat_input", to=t))
    vat_this = -(role_balance(c, "vat_output", frm=month_start, to=t) + role_balance(c, "vat_input", frm=month_start, to=t))
    vat_old = r2(vat_all - vat_this)
    if vat_old > 0.5:
        out.append({"label": "VAT payable up to %s" % (td.replace(day=1) - timedelta(days=1)).isoformat(),
                    "amount": vat_old, "due_date": prev_due, "ref": "vat_prev"})
    if vat_all > 0.5 and vat_this > 0.5:
        out.append({"label": "VAT payable this month (if output stays above input)", "amount": r2(min(vat_this, vat_all)),
                    "due_date": nxt, "ref": "vat_cur"})
    return out, r2(vat_all)


def _emi_rows(c, t):
    out = []
    for ln in q(c, "SELECT * FROM loans WHERE active=1 AND COALESCE(emi,0)>0"):
        d = ln["start_date"]
        if not d:
            continue
        n = 0
        while d and d < t and n < 600:
            n += 1
            d = _add_months(ln["start_date"], n)
        if ln["end_date"] and d and d > ln["end_date"]:
            continue
        out.append({"category": "loan", "label": "Loan instalment: %s%s" % (ln["name"], " (" + ln["lender"] + ")" if ln["lender"] else ""),
                    "amount": r2(ln["emi"]), "due_date": d, "ref_type": "loan", "ref_id": ln["id"],
                    "note": "Next instalment from the loan schedule; past instalments are not tracked per date."})
    for f in q(c, "SELECT f.*, e.code, e.name FROM eq_finance f LEFT JOIN equipment e ON e.id=f.equipment_id "
                  "WHERE COALESCE(f.emi,0)>0 AND f.first_emi_date IS NOT NULL"):
        paid = val(c, "SELECT COUNT(*) FROM eq_emi WHERE equipment_id=?", (f["equipment_id"],))
        if f["emi_count"] and paid >= f["emi_count"]:
            continue
        due = _add_months(f["first_emi_date"], int(paid))
        out.append({"category": "loan", "label": "Equipment instalment %d of %s: %s %s" % (paid + 1, f["emi_count"] or "?",
                                                                                         f["code"] or "", f["name"] or ""),
                    "amount": r2(f["emi"]), "due_date": due, "ref_type": "eq_emi", "ref_id": f["equipment_id"],
                    "party_name": f["lender"], "note": None})
    return out


def open_requests(c, invoice_id=None, ref=None, exclude=None):
    w, p = "stage IN (%s)" % ",".join("'%s'" % s for s in OPEN_STAGES if s != "returned"), []
    if invoice_id:
        w += " AND invoice_id=?"
        p.append(invoice_id)
    if ref:
        w += " AND ref=?"
        p.append(ref)
    if exclude:
        w += " AND id<>?"
        p.append(exclude)
    return r2(val(c, "SELECT SUM(amount) FROM fc_payreq WHERE " + w, p))


def payables(c, u, a):
    t = a.get("as_of") or today()
    pids = project_ids(c, u, a)
    pset = set(pids)
    parties = _parties(c)
    projs = _projects(c)
    rows = []
    for i in q(c, "SELECT * FROM invoices WHERE kind='purchase' AND status IN ('posted','awaiting_posting') AND date<=?", (t,)):
        if i["project_id"] not in pset:
            continue
        bal = inv_open(c, i) if i["status"] == "posted" else r2(i["payable"] or 0)
        if bal <= 0.5:
            continue
        pk = (parties.get(i["party_id"]) or {}).get("kind")
        cat = "subcontractor" if i["source"] == "sc_bill" or pk == "subcontractor" else "equipment" if i["source"] == "hire" else "supplier"
        rows.append({"key": "inv:%d" % i["id"], "category": cat, "party_id": i["party_id"],
                     "party_name": (parties.get(i["party_id"]) or {}).get("name"), "project_id": i["project_id"],
                     "ref_type": "invoice", "ref_id": i["id"], "ref_no": i["no"], "party_ref": i["party_inv_no"],
                     "date": i["date"], "due_date": i["due_date"], "amount": bal,
                     "obligation": "contractual" if cat == "subcontractor" else "operational" if cat == "equipment" else "normal",
                     "requested": open_requests(c, invoice_id=i["id"]),
                     "note": "Awaiting posting in the accounts posting queue" if i["status"] != "posted" else None,
                     "payable_now": i["status"] == "posted"})
    for pid in pids:
        wages = -role_balance(c, "payroll_payable", pid, to=t)
        if wages > 0.5:
            p = projs.get(pid) or {}
            days = terms(c, p).get("labour_pay_days") or 7
            # first in, first out: the unpaid balance is made of the latest wage entries; the oldest of them sets the date
            last, left = None, wages
            for x in q(c, "SELECT v.date, l.credit FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id JOIN accounts a ON "
                          "a.id=l.account_id WHERE a.role='payroll_payable' AND l.project_id=? AND l.credit>0 AND "
                          "v.status IN ('posted','reversed') AND v.date<=? ORDER BY v.date DESC, v.id DESC", (pid, t)):
                last = x["date"]
                left -= x["credit"]
                if left <= 0.5:
                    break
            rows.append({"key": "wages:%d" % pid, "category": "payroll", "party_id": None, "party_name": "Site workers",
                         "project_id": pid, "ref_type": "payroll", "ref_id": pid, "ref_no": None, "date": last,
                         "due_date": _add_days(last, days) if last else t, "amount": r2(wages), "obligation": "payroll",
                         "requested": open_requests(c, ref="wages:%d" % pid),
                         "note": "Wages payable in the ledger (from DPR labour); due %d days after the oldest unpaid wage entry." % days,
                         "payable_now": True})
    statutory, vat_net = [], 0.0
    if company_wide(c, u, a):
        statutory, vat_net = _statutory_rows(c, t)
        for s in statutory:
            rows.append({"key": "stat:%s" % s["ref"], "category": "statutory", "party_id": None,
                         "party_name": "Inland Revenue (tax office)", "project_id": None, "ref_type": "statutory",
                         "ref_id": None, "ref_no": s["label"], "date": None, "due_date": s["due_date"],
                         "amount": s["amount"], "obligation": "statutory",
                         "requested": open_requests(c, ref="stat:%s" % s["ref"]), "note": None, "payable_now": True})
        for e in _emi_rows(c, t):
            rows.append({"key": "%s:%s" % (e["ref_type"], e["ref_id"]), "category": "loan", "party_id": None,
                         "party_name": e.get("party_name") or "Lender", "project_id": None, "ref_type": e["ref_type"],
                         "ref_id": e["ref_id"], "ref_no": e["label"], "date": None, "due_date": e["due_date"],
                         "amount": e["amount"], "obligation": "contractual",
                         "requested": open_requests(c, ref="%s:%s" % (e["ref_type"], e["ref_id"])), "note": e["note"],
                         "payable_now": True})
    for r in rows:
        r["days_to_due"] = _days(t, r["due_date"]) if r["due_date"] else None
        r["bucket"] = bucket_of(r["days_to_due"])
        r["days_overdue"] = max(0, -(r["days_to_due"] or 0)) if r["days_to_due"] is not None else 0
        r["unrequested"] = r2(max(0.0, r["amount"] - (r["requested"] or 0)))
    rows.sort(key=lambda r: (r["due_date"] or "9999", OBL_RANK.get(r["obligation"], 9)))
    # information only
    ret = []
    for pid in pids:
        held = -role_balance(c, "retention_payable", pid, to=t)
        if held > 0.5:
            ret.append({"project_id": pid, "amount": r2(held)})
    commits = {}
    try:
        from api_finance import po_pending
        for r in po_pending(c, u, {}):
            if r["project_id"] not in pset:
                continue
            k = commits.setdefault(r["po_id"], {"po_id": r["po_id"], "no": r["no"], "party_id": r["vendor_id"],
                                                "party_name": (parties.get(r["vendor_id"]) or {}).get("name"),
                                                "project_id": r["project_id"], "delivery_date": r["delivery_date"],
                                                "pending_value": 0.0})
            k["pending_value"] = r2(k["pending_value"] + r["pending_value"])
        for k in commits.values():
            po = q1(c, "SELECT payment_terms, vat, subtotal FROM po WHERE id=?", (k["po_id"],)) or {}
            k["payment_terms"] = po.get("payment_terms")
            k["vat_note"] = "Before VAT" if (po.get("vat") or 0) > 0 else None
    except Exception:
        pass
    return {"as_of": t, "rows": rows, "retention_payable": ret, "commitments": sorted(commits.values(), key=lambda x: x["delivery_date"] or ""),
            "vat_net": vat_net, "company_items": company_wide(c, u, a)}


@api("fc.payables")
def fc_payables(c, u, a):
    need_any(c, u, [("accounts", "view"), ("payreq", "view")], "see payables")
    d = payables(c, u, a)
    tot = {k: 0.0 for k, _l in BUCKETS}
    cats = {}
    for r in d["rows"]:
        tot[r["bucket"]] = r2(tot[r["bucket"]] + r["amount"])
        cats[r["category"]] = r2(cats.get(r["category"], 0) + r["amount"])
    d["buckets"] = [{"key": k, "label": l, "amount": tot[k]} for k, l in BUCKETS]
    d["by_category"] = [{"key": k, "label": CAT_LABEL.get(k, k), "amount": v} for k, v in cats.items()]
    d["total"] = r2(sum(tot.values()))
    return d


# ───────────────────────────── payment requests ─────────────────────────────
def _steps(c):
    try:
        s = json.loads(setting(c, "fc_payreq_steps") or "{}")
    except ValueError:
        s = {}
    out = dict(STEP_DEFAULTS)
    for k, v in (s or {}).items():
        if k in out and isinstance(v, list) and len(v) == 2:
            out[k] = v
    return out


def _can_step(c, u, step):
    m, a_ = _steps(c)[step]
    ok = right(c, u, m, a_)
    if step == "pay":
        ok = ok and right(c, u, "accounts", "edit")
    return ok


def preq_log(c, u, rid, step, action, frm, to, note=None):
    ins(c, "fc_payreq_log", {"req_id": rid, "step": step, "action": action, "from_stage": frm, "to_stage": to,
                             "user_id": (u or {}).get("id"), "user_name": _uname(u), "note": note, "ts": now()})


def _reconciled(c, r):
    if r["stage"] != "paid":
        return False
    vid = r["voucher_id"]
    if not vid:
        return False
    open_bank = val(c, "SELECT COUNT(*) FROM voucher_lines l JOIN accounts a ON a.id=l.account_id WHERE l.voucher_id=? "
                       "AND a.role IN ('bank') AND l.cleared_date IS NULL", (vid,))
    any_bank = val(c, "SELECT COUNT(*) FROM voucher_lines l JOIN accounts a ON a.id=l.account_id WHERE l.voucher_id=? "
                      "AND a.role IN ('bank')", (vid,))
    return any_bank > 0 and open_bank == 0


def preq_view(c, r, u=None):
    r = dict(r)
    if r["stage"] == "paid" and _reconciled(c, r):
        r["stage"] = "reconciled"
    r["stage_label"] = STAGE_LABEL.get(r["stage"], r["stage"])
    r["category_label"] = CAT_LABEL.get(r["category"], r["category"])
    r["next_step"] = NEXT_STEP.get(r["stage"])
    r["late"] = bool(r["due_date"] and r["stage"] in OPEN_STAGES and r["due_date"] < today())
    r["deferred"] = bool(r["due_date"] and r["proposed_date"] and r["proposed_date"] > r["due_date"])
    if r["invoice_id"]:
        i = q1(c, "SELECT * FROM invoices WHERE id=?", (r["invoice_id"],))
        if i:
            r["invoice_no"] = i["no"]
            r["invoice_outstanding"] = inv_open(c, i)
    if r["payment_id"]:
        r["payment_no"] = val(c, "SELECT no FROM payments WHERE id=?", (r["payment_id"],), None)
    if r["voucher_id"]:
        r["voucher_no"] = val(c, "SELECT no FROM vouchers WHERE id=?", (r["voucher_id"],), None)
    r["created_by_name"] = val(c, "SELECT COALESCE(name, username) FROM users WHERE id=?", (r["created_by"],), None)
    return r


@api("fc.payreq_list")
def fc_payreq_list(c, u, a):
    need_any(c, u, [("payreq", "view")], "see payment requests")
    al = allowed(c, u)
    w, p = "1=1", []
    if a.get("project_id"):
        check_project(c, u, int(a["project_id"]))
        w += " AND project_id=?"
        p.append(int(a["project_id"]))
    st = a.get("stage") or "open"
    if st == "open":
        w += " AND stage IN (%s)" % ",".join("'%s'" % s for s in OPEN_STAGES)
    elif st != "all" and st != "reconciled":
        w += " AND stage=?"
        p.append(st)
    elif st == "reconciled":
        w += " AND stage='paid'"
    rows = [preq_view(c, r, u) for r in q(c, "SELECT * FROM fc_payreq WHERE " + w + " ORDER BY COALESCE(proposed_date, due_date, date), id", p)
            if al is None or (r["project_id"] is not None and r["project_id"] in al)]
    if st == "reconciled":
        rows = [r for r in rows if r["stage"] == "reconciled"]
    elif st == "paid":
        rows = [r for r in rows if r["stage"] == "paid"]
    for r in rows:
        r["can_act"] = bool(r["next_step"]) and _can_step(c, u, r["next_step"])
    return rows


@api("fc.payreq_get")
def fc_payreq_get(c, u, a):
    need_any(c, u, [("payreq", "view")], "see payment requests")
    r = get(c, "fc_payreq", int(a["id"]), "Payment request")
    _scope(c, u, r)
    v = preq_view(c, r, u)
    v["log"] = q(c, "SELECT * FROM fc_payreq_log WHERE req_id=? ORDER BY id", (r["id"],))
    v["other_open"] = open_requests(c, invoice_id=r["invoice_id"], exclude=r["id"]) if r["invoice_id"] else 0.0
    v["actions"] = _actions(c, u, r)
    return v


def _scope(c, u, r):
    al = allowed(c, u)
    if al is None:
        return
    if r["project_id"] is None or r["project_id"] not in al:
        raise ApiError("PROJECT_DENIED: this payment request is for a project you are not assigned to.")


def _did_step(c, r, uid):
    return {x["step"] for x in q(c, "SELECT step FROM fc_payreq_log WHERE req_id=? AND user_id=? AND action IN "
                                    "('verify_docs','verify_accounts','review_cash','approve','pay','link')", (r["id"], uid))}


def _actions(c, u, r):
    st = r["stage"]
    acts = []
    if st in FLOW_BY_FROM:
        act, step = FLOW_BY_FROM[st]
        if _can_step(c, u, step):
            acts.append(act)
    if st == "approved" and _can_step(c, u, "pay"):
        acts += ["pay", "link"]
    if st in ("requested", "docs_verified", "accounts_verified", "cash_reviewed", "approved"):
        nxt = NEXT_STEP.get(st)
        if nxt and _can_step(c, u, nxt):
            acts.append("return")
        if _can_step(c, u, "approve"):
            acts.append("reject")
    if st in ("requested", "returned") and (r["created_by"] == u.get("id") or right(c, u, "payreq", "edit")):
        acts += ["edit", "cancel"]
    elif st in ("docs_verified", "accounts_verified", "cash_reviewed", "approved") and _can_step(c, u, "approve"):
        acts.append("cancel")
    if st == "returned" and (r["created_by"] == u.get("id") or right(c, u, "payreq", "edit")):
        acts.append("resubmit")
    return sorted(set(acts), key=acts.index)


FLOW_BY_FROM = {frm: (act, step) for act, (frm, _to, step) in FLOW.items()}


def _validate(c, u, d, rid=None):
    cat = d.get("category") or "supplier"
    if cat not in CAT_LABEL:
        raise ApiError("Unknown payment category.")
    obl = d.get("obligation") or "normal"
    if obl not in OBL_RANK:
        raise ApiError("Unknown obligation type.")
    amt = r2(_f(d.get("amount")))
    if amt <= 0:
        raise ApiError("Enter the amount requested.")
    pid = _int(d.get("project_id"))
    party = _int(d.get("party_id"))
    invoice_id = _int(d.get("invoice_id"))
    if invoice_id:
        i = get(c, "invoices", invoice_id, "Invoice")
        if i["kind"] != "purchase":
            raise ApiError("A payment request can only be against a purchase bill.")
        if i["status"] != "posted":
            raise ApiError("Bill %s is not posted yet (status: %s). Post it first." % (i["no"], i["status"]))
        if party and party != i["party_id"]:
            raise ApiError("Bill %s belongs to another party." % i["no"])
        party = i["party_id"]
        pid = i["project_id"]
        room = r2(inv_open(c, i) - open_requests(c, invoice_id=i["id"], exclude=rid))
        if amt > room + 0.004:
            raise ApiError("Bill %s: the amount %s is more than what is still open and not already requested (%s)."
                           % (i["no"], amt, max(0.0, room)))
        d.setdefault("due_date", i["due_date"])
        if not d.get("due_date"):
            d["due_date"] = i["due_date"]
    if cat in ("supplier", "subcontractor", "equipment", "advance") and not party:
        raise ApiError("Choose the party to be paid.")
    if cat in ("supplier", "subcontractor", "equipment", "advance", "payroll") and not pid:
        raise ApiError("Choose the project.")
    if pid:
        get(c, "projects", pid, "Project")
        check_project(c, u, pid)
    elif allowed(c, u) is not None:
        raise ApiError("PROJECT_DENIED: company-level payments (tax, loans) need access to every project.")
    if party:
        get(c, "parties", party, "Party")
    po_id = _int(d.get("po_id"))
    if po_id:
        po = get(c, "po", po_id, "Purchase order")
        if party and po["vendor_id"] != party:
            raise ApiError("Purchase order %s is for another supplier." % po["no"])
    for k in ("due_date", "proposed_date"):
        if d.get(k) and not _d(d[k]):
            raise ApiError("%s is not a date." % k.replace("_", " ").capitalize())
    if obl in LEGAL and d.get("due_date") and d.get("proposed_date") and d["proposed_date"] > d["due_date"] \
            and not (d.get("deferral_reason") or "").strip():
        raise ApiError("This is a %s payment due on %s. Proposing to pay it later needs a reason, and the approver "
                       "must confirm it." % (dict(OBLIGATIONS)[obl].split(" (")[0].lower(), d["due_date"]))
    return {"party_id": party, "project_id": pid, "category": cat, "invoice_id": invoice_id, "po_id": po_id,
            "ref": (d.get("ref") or None), "amount": amt, "tax_note": d.get("tax_note") or None,
            "due_date": d.get("due_date") or None, "terms": d.get("terms") or None,
            "proposed_date": d.get("proposed_date") or None, "obligation": obl,
            "consequence": d.get("consequence") or None, "deferral_reason": (d.get("deferral_reason") or "").strip() or None,
            "note": d.get("note") or None}


@api("fc.payreq_save")
def fc_payreq_save(c, u, a):
    rid = _int(a.get("id"))
    if rid:
        r = get(c, "fc_payreq", rid, "Payment request")
        _scope(c, u, r)
        if r["stage"] not in ("requested", "returned"):
            raise ApiError("This request is %s; it can no longer be edited. Return it first." % STAGE_LABEL[r["stage"]].lower())
        if r["created_by"] != u.get("id") and not right(c, u, "payreq", "edit"):
            raise ApiError("Only the person who made the request, or someone with payment-request edit, can change it.")
        d = _validate(c, u, dict(a), rid)
        d["updated_at"] = now()
        upd(c, "fc_payreq", rid, d)
        preq_log(c, u, rid, "request", "edit", r["stage"], r["stage"], a.get("change_note"))
        return {"id": rid, "no": r["no"]}
    need_any(c, u, [("payreq", "create")], "request a payment")
    d = _validate(c, u, dict(a))
    dt = a.get("date") or today()
    d.update({"no": core.next_no(c, "PRQ", dt), "date": dt, "stage": "requested", "created_by": u["id"],
              "created_at": now(), "updated_at": now()})
    rid = ins(c, "fc_payreq", d)
    preq_log(c, u, rid, "request", "create", None, "requested", a.get("note"))
    audit(c, u, "create", "fc_payreq", rid, {"no": d["no"], "amount": d["amount"]})
    return {"id": rid, "no": d["no"]}


@api("fc.payreq_act")
def fc_payreq_act(c, u, a):
    r = get(c, "fc_payreq", int(a["id"]), "Payment request")
    _scope(c, u, r)
    act = a.get("action")
    note = (a.get("note") or "").strip() or None
    st = r["stage"]
    if act in FLOW:
        frm, to, step = FLOW[act]
        if st != frm:
            raise ApiError("This request is %s; '%s' is not the next step." % (STAGE_LABEL[st].lower(), STEP_LABEL[step].lower()))
        _need_step(c, u, step)
        _segregation(c, u, r, step)
        if step == "approve":
            if r["created_by"] == u.get("id") and setting(c, "fc_payreq_self_approve") != "1":
                raise ApiError("You made this request, so someone else must approve it.")
            if r["obligation"] in LEGAL and r["due_date"] and r["proposed_date"] and r["proposed_date"] > r["due_date"] and not note:
                raise ApiError("This %s payment is proposed after its due date (%s). Write your approval note on the "
                               "deferral to approve it." % (r["obligation"], r["due_date"]))
            if r["invoice_id"]:
                i = get(c, "invoices", r["invoice_id"])
                room = r2(inv_open(c, i) - open_requests(c, invoice_id=i["id"], exclude=r["id"]))
                if r["amount"] > room + 0.004:
                    raise ApiError("Bill %s now has only %s open (after other requests). Return the request to correct "
                                   "the amount." % (i["no"], max(0.0, room)))
        if step == "docs" and r["invoice_id"] is None and r["category"] in ("supplier", "subcontractor", "equipment") \
                and not r["po_id"] and not note:
            raise ApiError("No bill or purchase order is linked. Write what the documents are to verify them.")
        upd(c, "fc_payreq", r["id"], {"stage": to, "updated_at": now()})
        preq_log(c, u, r["id"], step, act, st, to, note)
        return {"stage": to}
    if act == "return":
        if st not in ("requested", "docs_verified", "accounts_verified", "cash_reviewed", "approved"):
            raise ApiError("Only an open request can be returned.")
        _need_step(c, u, NEXT_STEP[st])
        if not note:
            raise ApiError("Say what needs correcting.")
        upd(c, "fc_payreq", r["id"], {"stage": "returned", "updated_at": now()})
        preq_log(c, u, r["id"], NEXT_STEP[st], "return", st, "returned", note)
        return {"stage": "returned"}
    if act == "resubmit":
        if st != "returned":
            raise ApiError("Only a returned request can be sent again.")
        if r["created_by"] != u.get("id") and not right(c, u, "payreq", "edit"):
            raise ApiError("Only the requester can send it again.")
        _validate(c, u, dict(r), r["id"])
        upd(c, "fc_payreq", r["id"], {"stage": "requested", "updated_at": now()})
        preq_log(c, u, r["id"], "request", "resubmit", st, "requested", note)
        return {"stage": "requested"}
    if act == "reject":
        if st not in ("requested", "docs_verified", "accounts_verified", "cash_reviewed", "approved"):
            raise ApiError("Only an open request can be rejected.")
        _need_step(c, u, "approve")
        if not note:
            raise ApiError("Give the reason for rejecting.")
        upd(c, "fc_payreq", r["id"], {"stage": "rejected", "updated_at": now()})
        preq_log(c, u, r["id"], "approve", "reject", st, "rejected", note)
        return {"stage": "rejected"}
    if act == "cancel":
        if st in ("paid", "rejected", "cancelled"):
            raise ApiError("This request is already %s." % STAGE_LABEL[st].lower())
        if st in ("requested", "returned"):
            if r["created_by"] != u.get("id") and not right(c, u, "payreq", "edit"):
                raise ApiError("Only the requester can cancel it.")
        else:
            _need_step(c, u, "approve")
        upd(c, "fc_payreq", r["id"], {"stage": "cancelled", "updated_at": now()})
        preq_log(c, u, r["id"], "request", "cancel", st, "cancelled", note)
        return {"stage": "cancelled"}
    if act == "pay":
        return _pay(c, u, r, a, note)
    if act == "link":
        return _link(c, u, r, a, note)
    raise ApiError("Unknown action.")


def _need_step(c, u, step):
    if not _can_step(c, u, step):
        m, a_ = _steps(c)[step]
        raise ApiError("Your role cannot %s payment requests (needs '%s' on %s)." % (STEP_LABEL[step].lower(), a_, m))


def _segregation(c, u, r, step):
    if setting(c, "fc_payreq_strict") != "1":
        return
    done = _did_step(c, r, u.get("id")) - {step}
    if done:
        raise ApiError("Strict separation of duties is on: you already did another step of this request.")


def _pay(c, u, r, a, note):
    if r["stage"] != "approved":
        raise ApiError("Only an approved request can be paid.")
    _need_step(c, u, "pay")
    _segregation(c, u, r, "pay")
    if r["category"] in ("statutory", "loan", "payroll", "other") and not r["party_id"]:
        raise ApiError("This payment has no party bill; record it in Vouchers and use 'Link payment' here.")
    if not r["party_id"]:
        raise ApiError("No party on this request.")
    args = {"kind": "pay", "party_id": r["party_id"], "date": a.get("date") or today(),
            "bank_account_id": a.get("bank_account_id"), "project_id": r["project_id"], "mode": a.get("mode"),
            "cheque_no": a.get("cheque_no"), "tds_rate_id": a.get("tds_rate_id") or None,
            "remarks": "Payment request %s" % r["no"], "cash_override": a.get("cash_override"),
            "allow_duplicate": a.get("allow_duplicate"), "funding_purpose": a.get("funding_purpose")}
    if not args["bank_account_id"]:
        raise ApiError("Choose the bank or cash account.")
    if r["invoice_id"]:
        i = get(c, "invoices", r["invoice_id"])
        bal = inv_open(c, i)
        if r["amount"] > bal + 0.004:
            raise ApiError("Bill %s now has only %s open. Return the request to correct the amount." % (i["no"], bal))
        args["allocations"] = [{"invoice_id": i["id"], "amount": r["amount"]}]
    else:
        args["advance"] = r["amount"]
    res = inv.FUNCS["payment.create"][0](c, u, args)
    pay = get(c, "payments", res["id"])
    upd(c, "fc_payreq", r["id"], {"stage": "paid", "payment_id": pay["id"], "voucher_id": pay["voucher_id"],
                                  "paid_at": now(), "paid_by": u["id"], "updated_at": now()})
    preq_log(c, u, r["id"], "pay", "pay", "approved", "paid", note or "Paid by %s" % pay["no"])
    return {"stage": "paid", "payment_id": pay["id"], "payment_no": pay["no"]}


def _link(c, u, r, a, note):
    if r["stage"] != "approved":
        raise ApiError("Only an approved request can be linked to a payment.")
    _need_step(c, u, "pay")
    pid_, vid = _int(a.get("payment_id")), _int(a.get("voucher_id"))
    if pid_:
        p = get(c, "payments", pid_, "Payment")
        if p["status"] != "posted" or p["kind"] != "pay":
            raise ApiError("Payment %s is not a posted payment." % p["no"])
        if r["party_id"] and p["party_id"] != r["party_id"]:
            raise ApiError("Payment %s is to another party." % p["no"])
        vid = p["voucher_id"]
    elif vid:
        v = get(c, "vouchers", vid, "Voucher")
        if v["status"] != "posted" or v["type"] not in ("payment", "journal", "contra"):
            raise ApiError("Voucher %s is not a posted payment voucher." % v["no"])
    else:
        raise ApiError("Choose the payment or the voucher that paid this request.")
    used = q1(c, "SELECT no FROM fc_payreq WHERE id<>? AND stage='paid' AND ((payment_id IS NOT NULL AND payment_id=?) OR "
                 "(payment_id IS NULL AND voucher_id=?))", (r["id"], pid_, vid))
    if used:
        raise ApiError("That payment is already linked to request %s." % used["no"])
    upd(c, "fc_payreq", r["id"], {"stage": "paid", "payment_id": pid_, "voucher_id": vid, "paid_at": now(),
                                  "paid_by": u["id"], "updated_at": now()})
    preq_log(c, u, r["id"], "pay", "link", "approved", "paid", note or "Linked to an existing payment")
    return {"stage": "paid"}


@api("fc.pay_plan")
def fc_pay_plan(c, u, a):
    """A proposal only: what is open or due, in obligation order, against the money available. Nothing is paid."""
    need_any(c, u, [("payreq", "view")], "see the payment plan")
    if not right(c, u, "accounts", "view"):
        raise ApiError("The payment plan shows bank balances; it needs accounts view.")
    t = today()
    horizon = int(_f(a.get("days"), 30))
    end = _add_days(t, horizon)
    cash = r2(role_balance(c, "cash") + role_balance(c, "bank"))
    reserve = r2(_f(setting(c, "fc_cash_reserve")))
    available = r2(cash - reserve)
    items = []
    al = allowed(c, u)
    for r in q(c, "SELECT * FROM fc_payreq WHERE stage IN ('requested','docs_verified','accounts_verified','cash_reviewed','approved')"):
        if al is not None and (r["project_id"] is None or r["project_id"] not in al):
            continue
        v = preq_view(c, r)
        items.append({"kind": "request", "id": r["id"], "label": "%s %s" % (r["no"], CAT_LABEL.get(r["category"], "")),
                      "party_id": r["party_id"], "project_id": r["project_id"], "obligation": r["obligation"],
                      "due_date": r["due_date"], "proposed_date": r["proposed_date"], "amount": r["amount"],
                      "stage": v["stage_label"], "category": r["category"]})
    for p in payables(c, u, {"project_id": a.get("project_id")})["rows"]:
        if p["unrequested"] <= 0.5 or not p["payable_now"]:
            continue
        if p["due_date"] and p["due_date"] > end:
            continue
        items.append({"kind": "due", "id": p["ref_id"], "key": p["key"], "label": "%s %s" % (CAT_LABEL.get(p["category"], ""), p["ref_no"] or ""),
                      "party_id": p["party_id"], "party_name": p["party_name"], "project_id": p["project_id"],
                      "obligation": p["obligation"], "due_date": p["due_date"], "proposed_date": None,
                      "amount": p["unrequested"], "stage": "Not requested", "category": p["category"]})
    items.sort(key=lambda x: (OBL_RANK.get(x["obligation"], 9), (x["proposed_date"] or x["due_date"] or "9999")))
    cum = 0.0
    for x in items:
        cum = r2(cum + x["amount"])
        x["cumulative"] = cum
        x["fits"] = cum <= available + 0.004
        x["rank"] = OBL_RANK.get(x["obligation"], 9)
        x["late"] = bool(x["due_date"] and x["due_date"] < t)
    need_ = r2(sum(x["amount"] for x in items))
    return {"cash": cash, "reserve": reserve, "available": available, "items": items, "total": need_,
            "shortfall": r2(max(0.0, need_ - available)), "horizon": horizon, "today": t,
            "note": "A proposal only. Nothing is paid until a request is approved and paid by the people set in the chain."}


@api("fc.settings_save")
def fc_settings_save(c, u, a):
    need_any(c, u, [("accounts", "approve")], "change payment-control settings")
    ch = {}
    for k in DEFAULTS:
        if k not in a:
            continue
        v = a[k]
        if k == "fc_payreq_steps":
            steps = v if isinstance(v, dict) else json.loads(v or "{}")
            for s, pair in steps.items():
                if s not in STEP_DEFAULTS or not isinstance(pair, list) or len(pair) != 2 or pair[1] not in \
                        ("view", "create", "edit", "approve", "post"):
                    raise ApiError("Step %s: choose a module and a right." % s)
            v = json.dumps(dict(_steps(c), **steps))
        elif k in ("fc_statutory_due_day",):
            if not 1 <= int(_f(v)) <= 28:
                raise ApiError("The deposit day must be from 1 to 28.")
            v = str(int(_f(v)))
        elif k in ("fc_cash_reserve", "fc_stale_days"):
            if _f(v) < 0:
                raise ApiError("Cannot be negative.")
            v = str(_f(v))
        else:
            v = "1" if str(v) in ("1", "true", "True") else "0"
        c.execute("INSERT OR REPLACE INTO settings(key, value) VALUES(?,?)", (k, v))
        ch[k] = v
    audit(c, u, "settings", "fc", None, ch)
    return ch


# ───────────────────────────── financial data checks ─────────────────────────────
@api("fc.checks")
def fc_checks(c, u, a):
    need_any(c, u, [("accounts", "view")], "run the financial data checks")
    t = today()
    stale = int(_f(setting(c, "fc_stale_days"), 30)) or 30
    cut = _add_days(t, -stale)
    POSTED = "v.status IN ('posted','reversed')"
    out = []

    def add(area, name, sev, ok, detail, items=None, fix=None, amount=None):
        out.append({"area": area, "check": name, "ok": bool(ok), "severity": "ok" if ok else sev, "detail": detail,
                    "items": (items or [])[:50], "count": len(items or []), "fix": None if ok else fix, "amount": amount})

    bad = q(c, "SELECT v.id, v.no, v.date, ROUND(SUM(l.debit)-SUM(l.credit),2) diff FROM vouchers v JOIN voucher_lines l "
               "ON l.voucher_id=v.id GROUP BY v.id HAVING ABS(SUM(l.debit)-SUM(l.credit))>0.01")
    add("Ledger", "Every voucher balances", "error", not bad, "%d unbalanced" % len(bad) if bad else "All balanced",
        [{"ref": x["no"] or "draft", "date": x["date"], "amount": x["diff"]} for x in bad], "Accounts › Vouchers")
    dr = val(c, "SELECT SUM(l.debit) FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id WHERE " + POSTED)
    cr = val(c, "SELECT SUM(l.credit) FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id WHERE " + POSTED)
    add("Ledger", "Trial balance: total debits = total credits", "error", abs(dr - cr) < 0.5,
        "Debits %s, credits %s" % (_m(dr), _m(cr)), fix="Accounts › Trial balance")
    ob = r2(val(c, "SELECT SUM(opening_balance) FROM accounts"))
    add("Ledger", "Opening balances add up to zero", "error", abs(ob) < 0.5, "Difference %s" % _m(ob),
        fix="Accounts › Chart of accounts (opening balances)", amount=ob)

    # controls against open documents, company and per project (project lines exclude opening balances)
    for role, kind, label in (("ar_control", "sales", "Debtors"), ("ap_control", "purchase", "Creditors")):
        sign = 1 if kind == "sales" else -1
        books = r2(sign * role_balance(c, role))
        docs = r2(sum(inv_open(c, i) for i in q(c, "SELECT id, payable FROM invoices WHERE kind=? AND status='posted'", (kind,))))
        add("Receivables and payables", "%s control = open %s invoices (company)" % (label, kind), "error",
            abs(books - docs) < 1, "Books %s, invoices %s" % (_m(books), _m(docs)), fix="Accounts › Ageing; Integrity checks",
            amount=r2(books - docs))
        diffs = []
        for p in q(c, "SELECT id, code FROM projects ORDER BY id"):
            b = r2(sign * role_balance(c, role, p["id"]))
            dd = r2(sum(inv_open(c, i) for i in q(c, "SELECT id, payable FROM invoices WHERE kind=? AND status='posted' "
                                                      "AND project_id=?", (kind, p["id"]))))
            if abs(b - dd) >= 1:
                diffs.append({"ref": p["code"], "amount": r2(b - dd), "detail": "Books %s, invoices %s" % (_m(b), _m(dd))})
        add("Receivables and payables", "%s control = open invoices, project by project" % label, "warning", not diffs,
            "%d project(s) differ" % len(diffs) if diffs else "Every project agrees", diffs,
            "Payments or journals posted to a different project than the invoice")
    over = []
    for i in q(c, "SELECT id, no, payable FROM invoices WHERE status='posted'"):
        pd = invoice_paid(c, i["id"])
        if pd > (i["payable"] or 0) + 0.5:
            over.append({"ref": i["no"], "amount": r2(pd - i["payable"])})
    add("Receivables and payables", "No invoice is paid or received above its amount", "error", not over,
        "%d over-settled" % len(over) if over else "None", over, "Payments & receipts (cancel the wrong allocation)")

    # project allocation
    nopj = q(c, "SELECT v.no, v.date, a.code, ROUND(l.debit-l.credit,2) amt FROM voucher_lines l JOIN vouchers v ON "
                "v.id=l.voucher_id JOIN accounts a ON a.id=l.account_id WHERE " + POSTED + " AND a.type IN "
                "('income','expense') AND l.project_id IS NULL ORDER BY v.date")
    add("Project allocation", "Income and expense lines carry a project", "warning", not nopj,
        "%d line(s) without a project, net %s" % (len(nopj), _m(sum(x["amt"] for x in nopj))) if nopj else "All allocated",
        [{"ref": x["no"], "date": x["date"], "detail": x["code"], "amount": x["amt"]} for x in nopj],
        "Head-office lines are fine on the GENERAL project; others need a project")
    ghost = q(c, "SELECT DISTINCT l.project_id FROM voucher_lines l WHERE l.project_id IS NOT NULL AND l.project_id NOT IN "
                 "(SELECT id FROM projects)")
    add("Project allocation", "No ledger line points to a missing project", "error", not ghost,
        ", ".join(str(x["project_id"]) for x in ghost) or "None", [{"ref": str(x["project_id"])} for x in ghost])
    net_int = q(c, "SELECT v.source, ROUND(SUM(l.debit-l.credit),2) net FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id "
                   "JOIN accounts a ON a.id=l.account_id WHERE " + POSTED + " AND a.type IN ('income','expense') AND "
                   "v.source IN ('internal_billing','plant_run') GROUP BY v.source")
    badint = [x for x in net_int if abs(x["net"] or 0) > 0.5]
    add("Project allocation", "Internal equipment billing nets to zero in profit", "error", not badint,
        "; ".join("%s nets %s" % (x["source"], _m(x["net"])) for x in badint) if badint else
        ("Internal billing nets to zero" if net_int else "No internal billing posted"),
        [{"ref": x["source"], "amount": x["net"]} for x in badint])

    # duplicates
    dup_bills = q(c, "SELECT party_id, LOWER(TRIM(party_inv_no)) n, GROUP_CONCAT(no, ', ') nos, COUNT(*) k FROM invoices "
                     "WHERE kind='purchase' AND status IN ('posted','awaiting_posting') AND TRIM(COALESCE(party_inv_no,''))<>'' "
                     "GROUP BY party_id, LOWER(TRIM(party_inv_no)) HAVING COUNT(*)>1")
    add("Duplicates", "No supplier bill is booked twice (same supplier and bill number)", "error", not dup_bills,
        "%d duplicate group(s)" % len(dup_bills) if dup_bills else "None",
        [{"ref": x["nos"], "detail": "%s: bill %s" % (val(c, "SELECT name FROM parties WHERE id=?", (x["party_id"],), ""), x["n"])}
         for x in dup_bills], "Cancel the duplicate in Purchase invoices")
    dup_pay = q(c, "SELECT kind, party_id, date, gross, GROUP_CONCAT(no, ', ') nos, COUNT(*) k FROM payments WHERE status='posted' "
                   "GROUP BY kind, party_id, date, ROUND(gross,2) HAVING COUNT(*)>1")
    add("Duplicates", "No payment or receipt repeated (same party, date and amount)", "warning", not dup_pay,
        "%d possible duplicate(s)" % len(dup_pay) if dup_pay else "None",
        [{"ref": x["nos"], "date": x["date"], "amount": x["gross"], "detail": x["kind"]} for x in dup_pay],
        "Check and cancel the repeated one in Payments & receipts")
    dup_chq = q(c, "SELECT kind, party_id, LOWER(TRIM(cheque_no)) ch, GROUP_CONCAT(no, ', ') nos FROM payments WHERE status='posted' "
                   "AND TRIM(COALESCE(cheque_no,''))<>'' GROUP BY kind, party_id, LOWER(TRIM(cheque_no)) HAVING COUNT(*)>1")
    add("Duplicates", "No cheque or transfer reference used twice for one party", "warning", not dup_chq,
        "%d repeated reference(s)" % len(dup_chq) if dup_chq else "None",
        [{"ref": x["nos"], "detail": "Reference " + x["ch"]} for x in dup_chq])

    # bank
    unc = q(c, "SELECT v.no, v.date, a.code, ROUND(l.debit-l.credit,2) amt FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id "
               "JOIN accounts a ON a.id=l.account_id WHERE " + POSTED + " AND a.role='bank' AND l.cleared_date IS NULL AND "
               "v.date<? ORDER BY v.date", (cut,))
    add("Bank", "No bank entry left unreconciled for over %d days" % stale, "warning", not unc,
        "%d entr%s, net %s" % (len(unc), "y" if len(unc) == 1 else "ies", _m(sum(x["amt"] for x in unc))) if unc else "All reconciled",
        [{"ref": x["no"], "date": x["date"], "amount": x["amt"], "detail": x["code"]} for x in unc],
        "Accounts › Bank reconciliation")

    # documents and the ledger
    ipc_bad = []
    for i in q(c, "SELECT * FROM ipc WHERE status='certified'"):
        inv_ = q1(c, "SELECT * FROM invoices WHERE id=?", (i["invoice_id"],)) if i["invoice_id"] else None
        if not inv_:
            ipc_bad.append({"ref": i["no"], "detail": "No invoice"})
        elif inv_["status"] == "cancelled":
            ipc_bad.append({"ref": i["no"], "detail": "Invoice %s is cancelled" % inv_["no"]})
        elif abs((inv_["payable"] or 0) - (i["net"] or 0)) > 1:
            ipc_bad.append({"ref": i["no"], "detail": "IPC net %s, invoice %s" % (_m(i["net"]), _m(inv_["payable"])),
                            "amount": r2((inv_["payable"] or 0) - (i["net"] or 0))})
    add("Billing", "Every certified IPC has its sales invoice, for the same amount", "error", not ipc_bad,
        "%d IPC(s) disagree" % len(ipc_bad) if ipc_bad else "All agree", ipc_bad, "Commercial › IPCs")
    nov = q(c, "SELECT 'invoice' t, no, date FROM invoices WHERE status='posted' AND voucher_id IS NULL UNION ALL "
               "SELECT 'payment', no, date FROM payments WHERE status='posted' AND voucher_id IS NULL")
    vgone = q(c, "SELECT 'invoice' t, i.no, i.date FROM invoices i LEFT JOIN vouchers v ON v.id=i.voucher_id WHERE "
                 "i.status='posted' AND i.voucher_id IS NOT NULL AND v.id IS NULL UNION ALL SELECT 'payment', p.no, p.date "
                 "FROM payments p LEFT JOIN vouchers v ON v.id=p.voucher_id WHERE p.status='posted' AND p.voucher_id IS NOT "
                 "NULL AND v.id IS NULL")
    allbad = nov + vgone
    add("Billing", "Every posted invoice and payment has its voucher", "error", not allbad,
        "%d without a voucher" % len(allbad) if allbad else "All have vouchers",
        [{"ref": x["no"], "date": x["date"], "detail": x["t"]} for x in allbad])
    try:
        pq = q(c, "SELECT label, created_at, amount, stage FROM post_queue WHERE stage NOT IN ('posted','rejected','cancelled') "
                  "AND created_at<?", (cut,))
    except Exception:
        pq = []
    add("Billing", "Nothing waits in the accounts posting queue over %d days" % stale, "warning", not pq,
        "%d waiting" % len(pq) if pq else "None waiting that long",
        [{"ref": x["label"], "date": (x["created_at"] or "")[:10], "amount": x["amount"], "detail": x["stage"]} for x in pq],
        "Accounts › Accounts posting queue")
    late_req = q(c, "SELECT no, due_date, amount, obligation FROM fc_payreq WHERE stage IN ('requested','docs_verified',"
                    "'accounts_verified','cash_reviewed','approved') AND obligation IN ('statutory','payroll') AND due_date<?", (t,))
    add("Payments", "No tax or wage payment request is past its due date", "error", not late_req,
        "%d late" % len(late_req) if late_req else "None late",
        [{"ref": x["no"], "date": x["due_date"], "amount": x["amount"], "detail": x["obligation"]} for x in late_req],
        "Payments & receipts › Payment requests")
    summ = {"error": len([x for x in out if x["severity"] == "error"]),
            "warning": len([x for x in out if x["severity"] == "warning"]), "ok": len([x for x in out if x["ok"]])}
    return {"checks": out, "summary": summ, "today": t}


# ───────────────────────────── guards on existing endpoints ─────────────────────────────
def _pay_dup_w(orig):
    def payment_create26(c, u, a):
        ch = (a.get("cheque_no") or "").strip().lower()
        if ch and a.get("party_id"):
            d = q1(c, "SELECT no FROM payments WHERE status='posted' AND kind=? AND party_id=? AND LOWER(TRIM(cheque_no))=?",
                   (a.get("kind"), int(a["party_id"]), ch))
            if d:
                if not a.get("allow_duplicate"):
                    raise ApiError("Reference %s is already used on %s for this party. If this really is a second payment "
                                   "with the same reference, an accounts approver can tick 'allow duplicate reference'."
                                   % (a.get("cheque_no"), d["no"]))
                if not right(c, u, "accounts", "approve"):
                    raise ApiError("Only an accounts approver can allow a duplicate cheque or transfer reference.")
                audit(c, u, "duplicate_reference", "payments", None, {"cheque_no": a.get("cheque_no"), "other": d["no"]})
        return orig(c, u, a)
    return payment_create26


def _inv_post_w(orig):
    def invoice_post26(c, u, a):
        i = q1(c, "SELECT * FROM invoices WHERE id=?", (_int(a.get("id")),))
        if i and i["kind"] == "purchase" and (i["party_inv_no"] or "").strip():
            d = q1(c, "SELECT no FROM invoices WHERE id<>? AND kind='purchase' AND party_id=? AND status IN "
                      "('posted','awaiting_posting') AND LOWER(TRIM(party_inv_no))=?",
                   (i["id"], i["party_id"], i["party_inv_no"].strip().lower()))
            if d:
                if not a.get("allow_duplicate"):
                    raise ApiError("Supplier bill %s is already booked as %s. Check it is not the same bill; an accounts "
                                   "approver can post it with 'allow duplicate'." % (i["party_inv_no"], d["no"]))
                if not right(c, u, "accounts", "approve"):
                    raise ApiError("Only an accounts approver can post a bill whose number is already booked.")
                audit(c, u, "duplicate_bill", "invoices", i["id"], {"party_inv_no": i["party_inv_no"], "other": d["no"]})
        return orig(c, u, a)
    return invoice_post26


FLAGS = ("_bco219", "_bco220", "_bco221", "_bco223", "_bco224", "_bco225")


def _wrap(name, factory):
    cur = inv.FUNCS.get(name)
    if not cur or getattr(cur[0], "_bco226", False):
        return
    w = factory(cur[0])
    w._bco226 = True
    for flag in FLAGS:
        if getattr(cur[0], flag, False):
            setattr(w, flag, True)
    w.__name__ = getattr(cur[0], "__name__", name)
    inv.FUNCS[name] = (w, cur[1], cur[2], cur[3])


def _install():
    _wrap("ipc.save", _ipc_save_w)
    _wrap("ipc.submit", _ipc_submit_w)
    _wrap("ipc.return", _ipc_return_w)
    _wrap("ipc.certify", _ipc_certify_w)
    _wrap("ipc.uncertify", _ipc_uncertify_w)
    _wrap("payment.create", _pay_dup_w)
    _wrap("invoice.post", _inv_post_w)
