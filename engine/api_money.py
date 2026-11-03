"""BuildCore 2.40.0 — Money end to end.

Buying, paying, wages, petty cash and loans go through the books, with one approval path. Nothing posted is changed.
  1. Machine purchase to the asset register: a draft purchase bill line marked "capital item: new machine" creates the
     equipment and Fixed assets rows when the bill posts (Dr Plant & Machinery with the machine). Existing machines can be
     linked to their ledger lines (nothing posted).
  2. Payments to vendors and subcontractors need an approved payment request (setting mn_payreq_required; new companies
     on, updated companies off until accounts switches it on). Direct payments are listed in the data checks.
  3. Wage sheet per project and month from the DPR labour already posted to Wages Payable; paying it clears that month.
     Staff salary run (monthly rate, TDS / social security tax, SSF). Site petty cash (imprest): slips with an attachment,
     replenishment, unreplenished slips in the 13-week forecast. Bank statement import (CSV / xlsx) with automatic matching.
  4. One loan register: machine loans from Equipment finance appear in Cash › Loans (read-only, balance from the ledger);
     a typed loan linked to its machine is counted once, from Equipment finance.
New tables mn_*; new columns loans.equipment_id, loans.account_id, loans.party_id.
"""
import base64
import csv
import io
import re
import threading
import zipfile
from datetime import date, datetime, timedelta
from xml.etree import ElementTree as ET

import core
from core import ApiError, audit, get, ins, now, q, q1, r2, setting, today, upd, val
import api_inventory as inv
from api_inventory import api

VERSION = "2.40.0"
FLAG = "_bco240"
EPS = 0.005

SCHEMA = """
CREATE TABLE IF NOT EXISTS mn_capital(line_id INTEGER PRIMARY KEY, invoice_id INTEGER, code TEXT, name TEXT, category TEXT,
  life_years REAL, method TEXT, residual_pct REAL, meter_type TEXT, equipment_id INTEGER, fa_id INTEGER, status TEXT DEFAULT 'marked',
  user_id INTEGER, ts TEXT);
CREATE TABLE IF NOT EXISTS mn_asset_link(id INTEGER PRIMARY KEY, equipment_id INTEGER, line_id INTEGER UNIQUE, user_id INTEGER, ts TEXT);
CREATE TABLE IF NOT EXISTS mn_wage_sheet(id INTEGER PRIMARY KEY, no TEXT, project_id INTEGER, month TEXT, from_date TEXT, to_date TEXT,
  accrued REAL DEFAULT 0, dpr_total REAL DEFAULT 0, advance_recovery REAL DEFAULT 0, tax REAL DEFAULT 0, other_deduction REAL DEFAULT 0,
  net REAL DEFAULT 0, status TEXT DEFAULT 'draft', voucher_id INTEGER, bank_account_id INTEGER, paid_date TEXT, note TEXT,
  created_by INTEGER, ts TEXT, UNIQUE(project_id, month));
CREATE TABLE IF NOT EXISTS mn_wage_lines(id INTEGER PRIMARY KEY, sheet_id INTEGER, trade_id INTEGER, trade TEXT, head_days REAL,
  hours REAL, ot_hours REAL, amount REAL);
CREATE TABLE IF NOT EXISTS mn_salary_run(id INTEGER PRIMARY KEY, month TEXT UNIQUE, date TEXT, gross REAL, tax REAL, ssf_employee REAL,
  ssf_employer REAL, net REAL, status TEXT DEFAULT 'posted', voucher_id INTEGER, pay_voucher_id INTEGER, paid_date TEXT,
  created_by INTEGER, ts TEXT);
CREATE TABLE IF NOT EXISTS mn_salary_lines(id INTEGER PRIMARY KEY, run_id INTEGER, staff_id INTEGER, name TEXT, project_id INTEGER,
  gross REAL, tax REAL, ssf_employee REAL, ssf_employer REAL, net REAL);
CREATE TABLE IF NOT EXISTS mn_imprest(id INTEGER PRIMARY KEY, project_id INTEGER, holder TEXT, account_id INTEGER, float_amount REAL,
  active INTEGER DEFAULT 1, voucher_id INTEGER, created_by INTEGER, ts TEXT);
CREATE TABLE IF NOT EXISTS mn_slips(id INTEGER PRIMARY KEY, no TEXT, imprest_id INTEGER, date TEXT, amount REAL, description TEXT,
  project_id INTEGER, boq_item_id INTEGER, overhead INTEGER DEFAULT 0, account_id INTEGER, status TEXT DEFAULT 'draft',
  voucher_id INTEGER, replenish_voucher_id INTEGER, created_by INTEGER, ts TEXT);
CREATE TABLE IF NOT EXISTS mn_stmt(id INTEGER PRIMARY KEY, import_id TEXT, bank_account_id INTEGER, row_no INTEGER, date TEXT,
  description TEXT, ref TEXT, withdrawal REAL DEFAULT 0, deposit REAL DEFAULT 0, line_id INTEGER, how TEXT, status TEXT DEFAULT 'open',
  user_id INTEGER, ts TEXT);
CREATE INDEX IF NOT EXISTS ix_mnst ON mn_stmt(import_id);
CREATE TABLE IF NOT EXISTS mn_loan_link(id INTEGER PRIMARY KEY, loan_id INTEGER, equipment_id INTEGER, prev_active INTEGER,
  user_id INTEGER, ts TEXT, undone_ts TEXT);
CREATE TABLE IF NOT EXISTS mn_log(id INTEGER PRIMARY KEY, what TEXT, value TEXT, user_id INTEGER, ts TEXT);
"""

ROLES = [("1210", "Wage Advances", "asset", "A3", "wage_advance"),
         ("2105", "SSF Payable", "liability", "L2", "ssf_payable"),
         ("6110", "Salaries - Head Office", "expense", "X3", "salary_ho"),
         ("5010", "Site Expenses (Petty Cash)", "expense", "X1", "site_expense")]
PAY_KINDS = ("vendor", "subcontractor")


def _has(c, t):
    return bool(val(c, "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?", (t,)))


def _cols(c, t):
    return {r["name"] for r in q(c, "PRAGMA table_info(%s)" % t)}


def _f(x, d=0.0):
    try:
        return float(str(x).replace(",", "")) if x not in (None, "") else d
    except (TypeError, ValueError):
        return d


def _set(c, k, v):
    c.execute("INSERT OR REPLACE INTO settings(key, value) VALUES(?,?)", (k, str(v)))


def _right(u, module, action):
    return bool(u) and (u.get("role") == "admin" or core.can(u, module, action))


def _need(u, module, action):
    if not _right(u, module, action):
        raise ApiError("You do not have the right to do this (%s %s)." % (module, action))


_LOCAL = threading.local()


def _wrap(name, factory):
    cur = inv.FUNCS.get(name)
    if not cur or getattr(cur[0], FLAG, False):
        return
    w = factory(cur[0])
    setattr(w, FLAG, True)
    w._orig = cur[0]
    for f in ("_bco219", "_bco220", "_bco221", "_bco223", "_bco226", "_bco238", "_bco239"):
        if getattr(cur[0], f, False):
            setattr(w, f, True)
    inv.FUNCS[name] = (w, cur[1], cur[2], cur[3])


def _role_acc(c, role):
    r = q1(c, "SELECT id FROM accounts WHERE role=? AND active=1 ORDER BY id LIMIT 1", (role,))
    if r:
        return r["id"]
    for code, name, typ, grp, rl in ROLES:
        if rl == role:
            g = q1(c, "SELECT id FROM account_groups WHERE code=?", (grp,)) or \
                q1(c, "SELECT id FROM account_groups WHERE type=? ORDER BY id", (typ,))
            cc, n = code, 0
            while q1(c, "SELECT id FROM accounts WHERE code=?", (cc,)):
                n += 1
                cc = "%s-%d" % (code, n)
            return ins(c, "accounts", {"code": cc, "name": name, "type": typ, "group_id": g["id"] if g else None, "role": role,
                                       "opening_balance": 0, "active": 1})
    return core.role_account(c, role)


def _post(c, u, vtype, d, narration, lines, project_id=None, source=None, source_id=None, party_id=None, ref_no=None):
    lines = [x for x in lines if (x.get("debit") or 0) > EPS or (x.get("credit") or 0) > EPS]
    return core.post_voucher(c, u, vtype, d, narration, lines, project_id=project_id, source=source, source_id=source_id,
                             party_id=party_id, ref_no=ref_no)


def _money_acc(c, acc_id):
    if not acc_id:
        raise ApiError("Choose the bank or cash account.")
    import api_finance as F
    F.is_money_account(c, int(acc_id))
    return int(acc_id)


def _pcode(c, pid):
    return val(c, "SELECT code FROM projects WHERE id=?", (pid,), "") if pid else ""


def _log(c, u, what, value):
    ins(c, "mn_log", {"what": what, "value": str(value), "user_id": u["id"] if u else None, "ts": now()})
    audit(c, u, "mn_" + what, "settings", 0, {"value": value})


# ───────────────────────────── 1. machine purchase to the asset register ─────────────────────────────
@api("mn.capital_mark", "procurement", "edit")
def mn_capital_mark(c, u, a):
    """Mark a draft purchase bill line as a new machine: the line's account becomes Plant & Machinery."""
    ln = q1(c, "SELECT l.*, i.status, i.kind, i.id inv_id FROM invoice_lines l JOIN invoices i ON i.id=l.invoice_id WHERE l.id=?",
            (int(a["line_id"]),))
    if not ln:
        raise ApiError("Bill line not found.")
    if ln["kind"] != "purchase" or ln["status"] != "draft":
        raise ApiError("Only a line of a draft purchase bill can be marked as a new machine.")
    if ln["grn_line_id"]:
        raise ApiError("This line comes from a goods receipt; a machine is billed on its own line without a GRN.")
    code = (a.get("code") or "").strip()
    if not code or not (a.get("name") or "").strip():
        raise ApiError("Give the machine a code and a name.")
    if val(c, "SELECT COUNT(*) FROM equipment WHERE code=?", (code,)) or \
            val(c, "SELECT COUNT(*) FROM mn_capital WHERE code=? AND line_id<>? AND status<>'cancelled'", (code, ln["id"])):
        raise ApiError("Machine code %s is already used." % code)
    fa = _role_acc(c, "fixed_asset")
    upd(c, "invoice_lines", ln["id"], {"account_id": fa})
    c.execute("INSERT OR REPLACE INTO mn_capital(line_id, invoice_id, code, name, category, life_years, method, residual_pct, meter_type, "
              "status, user_id, ts) VALUES(?,?,?,?,?,?,?,?,?, 'marked', ?, ?)",
              (ln["id"], ln["inv_id"], code, a["name"].strip(), a.get("category") or "Earthmoving", _f(a.get("life_years"), 10),
               (a.get("method") or "sl").lower(), _f(a.get("residual_pct"), 5), a.get("meter_type") or "hour", u["id"], now()))
    audit(c, u, "capital_mark", "invoice_lines", ln["id"], {"code": code})
    return {"line_id": ln["id"], "account_id": fa}


@api("mn.capital_unmark", "procurement", "edit")
def mn_capital_unmark(c, u, a):
    m = q1(c, "SELECT * FROM mn_capital WHERE line_id=?", (int(a["line_id"]),))
    if not m or m["status"] != "marked":
        raise ApiError("This line is not marked, or the bill is already posted.")
    c.execute("DELETE FROM mn_capital WHERE line_id=?", (m["line_id"],))
    upd(c, "invoice_lines", m["line_id"], {"account_id": None})
    return True


@api("mn.capital_list", "procurement", "view")
def mn_capital_list(c, u, a):
    """Draft purchase bill lines (to mark) and every machine bought through a bill."""
    drafts = q(c, "SELECT l.id line_id, l.description, l.qty, l.rate, ROUND(l.qty*l.rate,2) amount, i.id invoice_id, i.no, i.date, "
                  "p.name party, pr.code project, m.code machine_code, m.name machine_name, m.status mark FROM invoice_lines l "
                  "JOIN invoices i ON i.id=l.invoice_id LEFT JOIN parties p ON p.id=i.party_id LEFT JOIN projects pr ON pr.id=i.project_id "
                  "LEFT JOIN mn_capital m ON m.line_id=l.id WHERE i.kind='purchase' AND i.status='draft' AND l.grn_line_id IS NULL "
                  "ORDER BY i.id DESC, l.id")
    done = q(c, "SELECT m.*, i.no, i.date, i.status bill_status, e.code eq_code, e.purchase_value FROM mn_capital m "
                "LEFT JOIN invoices i ON i.id=m.invoice_id LEFT JOIN equipment e ON e.id=m.equipment_id WHERE m.status='posted' ORDER BY m.ts DESC")
    return {"drafts": drafts, "machines": done}


def _w_invoice_post(orig):
    def invoice_post(c, u, a):
        marks = q(c, "SELECT m.*, l.qty, l.rate, l.equipment_id line_eq, i.date, i.project_id, i.party_id, i.no inv_no FROM mn_capital m "
                     "JOIN invoice_lines l ON l.id=m.line_id JOIN invoices i ON i.id=l.invoice_id WHERE m.invoice_id=? AND m.status='marked'",
                  (int(a.get("id") or 0),))
        made = []
        for m in marks:
            if m["line_eq"]:
                continue
            amount = r2(_f(m["qty"]) * _f(m["rate"]))
            cols = _cols(c, "equipment")
            row = {"code": m["code"], "name": m["name"], "category": m["category"], "ownership": "owned",
                   "vendor_id": m["party_id"], "purchase_date": m["date"], "purchase_value": amount,
                   "residual_value": r2(amount * _f(m["residual_pct"]) / 100), "life_months": int(round(_f(m["life_years"], 10) * 12)),
                   "dep_method": "wdv" if m["method"] == "wdv" else "sl", "accumulated_dep": 0, "meter_type": m["meter_type"] or "hour",
                   "meter": 0, "status": "working", "project_id": m["project_id"], "active": 1,
                   "notes": "Bought on bill %s" % (m["inv_no"] or "")}
            eid = ins(c, "equipment", {k: v for k, v in row.items() if k in cols})
            upd(c, "invoice_lines", m["line_id"], {"equipment_id": eid})
            c.execute("UPDATE mn_capital SET equipment_id=? WHERE line_id=?", (eid, m["line_id"]))
            made.append((m, eid, amount))
        res = orig(c, u, a)
        for m, eid, amount in made:
            try:
                inv.FUNCS["fa.sync"][0](c, u, {})
            except ApiError:
                pass
            fa = val(c, "SELECT id FROM fa_register WHERE kind='equipment' AND ref_id=?", (eid,), None)
            c.execute("UPDATE mn_capital SET status='posted', fa_id=? WHERE line_id=?", (fa, m["line_id"]))
            if _has(c, "eq_finance") and not val(c, "SELECT COUNT(*) FROM eq_finance WHERE equipment_id=?", (eid,)):
                ins(c, "eq_finance", {"equipment_id": eid, "price": amount, "down_payment": amount, "loan_amount": 0,
                                      "notes": "From purchase bill %s" % (m["inv_no"] or ""), "ts": now()})
            audit(c, u, "capital_machine", "equipment", eid, {"bill": m["inv_no"], "amount": amount})
        if made and isinstance(res, dict):
            res["machines"] = [{"code": m["code"], "equipment_id": eid, "amount": amount} for m, eid, amount in made]
        return res
    return invoice_post


def asset_links(c):
    fa_acc = [r["id"] for r in q(c, "SELECT id FROM accounts WHERE role='fixed_asset'")]
    if not fa_acc:
        return []
    ph = ",".join("?" * len(fa_acc))
    lines = q(c, "SELECT l.id, l.equipment_id, l.debit-l.credit amount, v.no, v.date, v.narration, v.source FROM voucher_lines l "
                 "JOIN vouchers v ON v.id=l.voucher_id WHERE l.account_id IN (%s) AND v.status IN ('posted','reversed') "
                 "AND ABS(l.debit-l.credit)>0.004 ORDER BY v.date" % ph, fa_acc)
    links = {r["line_id"]: r["equipment_id"] for r in q(c, "SELECT line_id, equipment_id FROM mn_asset_link")}
    out = []
    for e in q(c, "SELECT id, code, name, purchase_value, purchase_date FROM equipment WHERE COALESCE(ownership,'owned')='owned' "
                  "AND COALESCE(status,'')<>'disposed' ORDER BY code"):
        mine = [x for x in lines if x["equipment_id"] == e["id"] or links.get(x["id"]) == e["id"]]
        tot = r2(sum(x["amount"] for x in mine))
        cost = r2(_f(e["purchase_value"]))
        cand = [] if abs(tot - cost) < 1 else [x for x in lines if not x["equipment_id"] and x["id"] not in links
                                              and abs(x["amount"] - (cost - tot)) < 1]
        out.append({"equipment_id": e["id"], "code": e["code"], "name": e["name"], "register_cost": cost, "ledger": tot,
                    "difference": r2(cost - tot), "lines": [dict(x, linked=x["id"] in links) for x in mine], "candidates": cand,
                    "status": "agrees" if abs(cost - tot) < 1 else ("no ledger line" if not mine else "differs")})
    return out


@api("mn.asset_links", "assets", "view")
def mn_asset_links(c, u, a):
    return {"machines": asset_links(c), "can_link": _right(u, "accounts", "edit")}


@api("mn.asset_link", "accounts", "edit")
def mn_asset_link(c, u, a):
    eid, lid = int(a["equipment_id"]), int(a["line_id"])
    get(c, "equipment", eid, "Machine")
    ln = q1(c, "SELECT l.*, ac.role FROM voucher_lines l JOIN accounts ac ON ac.id=l.account_id WHERE l.id=?", (lid,))
    if not ln or ln["role"] != "fixed_asset":
        raise ApiError("Only a line on the fixed asset account can be linked to a machine.")
    if ln["equipment_id"] and ln["equipment_id"] != eid:
        raise ApiError("This ledger line already carries another machine.")
    if a.get("undo"):
        c.execute("DELETE FROM mn_asset_link WHERE line_id=?", (lid,))
        return True
    c.execute("INSERT OR REPLACE INTO mn_asset_link(equipment_id, line_id, user_id, ts) VALUES(?,?,?,?)", (eid, lid, u["id"], now()))
    audit(c, u, "asset_link", "voucher_lines", lid, {"equipment_id": eid})
    return True


# ───────────────────────────── 2. payments through payment requests ─────────────────────────────
def payreq_on(c):
    return setting(c, "mn_payreq_required") == "1"


def _exempt(c):
    return {x.strip() for x in (setting(c, "mn_payreq_exempt") or "").split(",") if x.strip()}


def _w_payment_create(orig):
    def payment_create(c, u, a):
        if a.get("kind") == "pay" and payreq_on(c) and not getattr(_LOCAL, "payreq", False):
            p = q1(c, "SELECT kind, name FROM parties WHERE id=?", (int(a.get("party_id") or 0),))
            if p and p["kind"] in PAY_KINDS and p["kind"] not in _exempt(c):
                gross = sum(_f(x.get("amount")) for x in (a.get("allocations") or [])) + _f(a.get("advance"))
                if gross > _f(setting(c, "mn_payreq_min"), 0) + EPS:
                    raise ApiError("Payments to %s go through a payment request (Accounts › Payment requests): raise a request, "
                                   "have it approved, then pay it there." % p["name"])
        return orig(c, u, a)
    return payment_create


def _patch_payreq_pay():
    import api_fc as FC
    if getattr(FC._pay, FLAG, False):
        return
    orig = FC._pay

    def _pay(c, u, r, a, note):
        prev = getattr(_LOCAL, "payreq", False)
        _LOCAL.payreq = True
        try:
            return orig(c, u, r, a, note)
        finally:
            _LOCAL.payreq = prev
    setattr(_pay, FLAG, True)
    _pay._orig = orig
    FC._pay = _pay


def direct_payments(c):
    since = setting(c, "mn_payreq_from") or ""
    if not since:
        return []
    paid = {r["payment_id"] for r in q(c, "SELECT payment_id FROM fc_payreq WHERE payment_id IS NOT NULL")} if _has(c, "fc_payreq") else set()
    rows = q(c, "SELECT y.id, y.no, y.date, y.gross, p.name party, p.kind FROM payments y JOIN parties p ON p.id=y.party_id "
                "WHERE y.kind='pay' AND y.status='posted' AND y.date>=? AND p.kind IN ('vendor','subcontractor') ORDER BY y.date", (since,))
    ex = _exempt(c)
    return [r for r in rows if r["id"] not in paid and r["kind"] not in ex]


@api("mn.settings", "accounts", "view")
def mn_settings(c, u, a):
    return {"payreq_required": payreq_on(c), "payreq_from": setting(c, "mn_payreq_from") or "",
            "payreq_exempt": sorted(_exempt(c)), "payreq_min": _f(setting(c, "mn_payreq_min"), 0),
            "sst_pct": _f(setting(c, "mn_sst_pct"), 1), "ssf_employee_pct": _f(setting(c, "mn_ssf_emp_pct"), 11),
            "ssf_employer_pct": _f(setting(c, "mn_ssf_er_pct"), 20), "direct_payments": direct_payments(c),
            "history": q(c, "SELECT m.*, u.name user FROM mn_log m LEFT JOIN users u ON u.id=m.user_id ORDER BY m.id DESC LIMIT 20"),
            "can_change": _right(u, "accounts", "approve")}


@api("mn.settings_save", "accounts", "approve")
def mn_settings_save(c, u, a):
    if "payreq_required" in a:
        want = a["payreq_required"] not in (False, 0, "0", "false", None)
        if want != payreq_on(c):
            _set(c, "mn_payreq_required", "1" if want else "0")
            if want:
                _set(c, "mn_payreq_from", a.get("from") or today())
            _log(c, u, "payreq_required", "1" if want else "0")
    if "payreq_exempt" in a:
        v = ",".join(x for x in (a["payreq_exempt"] or []) if x in PAY_KINDS)
        _set(c, "mn_payreq_exempt", v)
        _log(c, u, "payreq_exempt", v)
    for k, key in (("payreq_min", "mn_payreq_min"), ("sst_pct", "mn_sst_pct"), ("ssf_employee_pct", "mn_ssf_emp_pct"),
                   ("ssf_employer_pct", "mn_ssf_er_pct")):
        if a.get(k) not in (None, ""):
            _set(c, key, _f(a[k]))
            _log(c, u, key, _f(a[k]))
    return mn_settings(c, u, {})


# ───────────────────────────── 3a. wage sheet from the DPR ─────────────────────────────
def _window(c, m):
    import api_pfp as PF
    return PF.window_of(c, m)


def _month_label(c, m):
    import api_pfp as PF
    return PF.month_label(c, m) if hasattr(PF, "month_label") else m


def _default_month(c, d=None):
    import api_pfp as PF
    d = d or today()
    if PF.nepali_runs(c):
        CL = PF._CL()
        k = CL.period_of_date(c, d)
        return CL._shift(k, -1) if hasattr(CL, "_shift") else k
    first = date.fromisoformat(d[:8] + "01")
    return (first - timedelta(days=1)).isoformat()[:7]


def wage_figures(c, pid, m):
    frm, to = _window(c, m)
    lines = q(c, "SELECT l.trade_id, COALESCE(t.name, 'Trade ' || l.trade_id) trade, SUM(l.count) head_days, SUM(l.count*l.hours) hours, "
                 "SUM(l.count*COALESCE(l.ot_hours,0)) ot_hours, SUM(l.amount) amount FROM dpr_labour l JOIN dpr d ON d.id=l.dpr_id "
                 "LEFT JOIN trades t ON t.id=l.trade_id WHERE d.project_id=? AND d.date BETWEEN ? AND ? AND d.status='approved' "
                 "AND l.party_id IS NULL GROUP BY l.trade_id ORDER BY trade", (pid, frm, to)) \
        if _has(c, "trades") else \
        q(c, "SELECT l.trade_id, 'Trade ' || l.trade_id trade, SUM(l.count) head_days, SUM(l.count*l.hours) hours, "
             "SUM(l.count*COALESCE(l.ot_hours,0)) ot_hours, SUM(l.amount) amount FROM dpr_labour l JOIN dpr d ON d.id=l.dpr_id "
             "WHERE d.project_id=? AND d.date BETWEEN ? AND ? AND d.status='approved' AND l.party_id IS NULL GROUP BY l.trade_id", (pid, frm, to))
    accrued = r2(_f(val(c, "SELECT SUM(l.credit-l.debit) FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id JOIN accounts ac "
                           "ON ac.id=l.account_id WHERE ac.role='payroll_payable' AND COALESCE(l.project_id, v.project_id)=? AND v.source='dpr' "
                           "AND v.status IN ('posted','submitted') AND v.date BETWEEN ? AND ?", (pid, frm, to))))
    waiting = r2(_f(val(c, "SELECT SUM(l.credit-l.debit) FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id JOIN accounts ac "
                           "ON ac.id=l.account_id WHERE ac.role='payroll_payable' AND COALESCE(l.project_id, v.project_id)=? AND v.source='dpr' "
                           "AND v.status='submitted' AND v.date BETWEEN ? AND ?", (pid, frm, to))))
    days = q(c, "SELECT d.date, SUM(l.count) heads, SUM(l.amount) amount FROM dpr_labour l JOIN dpr d ON d.id=l.dpr_id WHERE d.project_id=? "
                "AND d.date BETWEEN ? AND ? AND d.status='approved' AND l.party_id IS NULL GROUP BY d.date ORDER BY d.date", (pid, frm, to))
    adv = r2(_f(val(c, "SELECT SUM(l.debit-l.credit) FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id JOIN accounts ac ON "
                       "ac.id=l.account_id WHERE ac.role='wage_advance' AND COALESCE(l.project_id, v.project_id)=? AND v.status='posted'", (pid,))))
    for x in lines:
        for k in ("head_days", "hours", "ot_hours", "amount"):
            x[k] = r2(_f(x[k]))
    return {"project_id": pid, "month": m, "label": _month_label(c, m), "from": frm, "to": to, "lines": lines, "attendance": days,
            "dpr_total": r2(sum(x["amount"] for x in lines)), "accrued": accrued, "waiting": waiting, "advance_open": adv}


@api("mn.wage_sheet", "accounts", "view")
def mn_wage_sheet(c, u, a):
    pid = int(a["project_id"])
    m = (a.get("month") or _default_month(c))[:7]
    d = wage_figures(c, pid, m)
    d["sheet"] = q1(c, "SELECT * FROM mn_wage_sheet WHERE project_id=? AND month=?", (pid, m))
    d["sheets"] = q(c, "SELECT s.*, v.no vno, v.status vstatus FROM mn_wage_sheet s LEFT JOIN vouchers v ON v.id=s.voucher_id "
                       "WHERE s.project_id=? ORDER BY s.from_date DESC", (pid,))
    d["months"] = _month_list(c)
    return d


def _month_list(c):
    import api_pfp as PF
    if PF.nepali_runs(c):
        CL = PF._CL()
        k = CL.period_of_date(c, today())
        out = []
        for _i in range(12):
            out.append({"key": k, "label": CL.period_label(k)})
            k = CL._shift(k, -1)
        return out
    out, d = [], date.fromisoformat(today()[:8] + "01")
    for _i in range(12):
        out.append({"key": d.isoformat()[:7], "label": d.strftime("%B %Y")})
        d = (d - timedelta(days=1)).replace(day=1)
    return out


@api("mn.wage_sheet_save", "accounts", "edit")
def mn_wage_sheet_save(c, u, a):
    pid = int(a["project_id"])
    m = (a.get("month") or "")[:7]
    if not m:
        raise ApiError("Choose the month.")
    d = wage_figures(c, pid, m)
    ex = q1(c, "SELECT * FROM mn_wage_sheet WHERE project_id=? AND month=?", (pid, m))
    if ex and ex["status"] != "draft":
        raise ApiError("The wage sheet for %s is already paid." % d["label"])
    advr, tax, oth = r2(_f(a.get("advance_recovery"))), r2(_f(a.get("tax"))), r2(_f(a.get("other_deduction")))
    if advr > d["advance_open"] + EPS:
        raise ApiError("Advance recovery %s is more than the open wage advances %s." % (advr, d["advance_open"]))
    net = r2(d["accrued"] - advr - tax - oth)
    if net < -EPS:
        raise ApiError("Deductions are more than the wages.")
    row = {"project_id": pid, "month": m, "from_date": d["from"], "to_date": d["to"], "accrued": d["accrued"], "dpr_total": d["dpr_total"],
           "advance_recovery": advr, "tax": tax, "other_deduction": oth, "net": net, "note": a.get("note"), "ts": now()}
    if ex:
        upd(c, "mn_wage_sheet", ex["id"], row)
        sid = ex["id"]
    else:
        row.update({"no": "WS/%s/%s" % (_pcode(c, pid), m), "status": "draft", "created_by": u["id"]})
        if not setting(c, "mn_wages_from"):
            _set(c, "mn_wages_from", d["from"])
        sid = ins(c, "mn_wage_sheet", row)
    c.execute("DELETE FROM mn_wage_lines WHERE sheet_id=?", (sid,))
    for x in d["lines"]:
        ins(c, "mn_wage_lines", {"sheet_id": sid, "trade_id": x["trade_id"], "trade": x["trade"], "head_days": x["head_days"],
                                 "hours": x["hours"], "ot_hours": x["ot_hours"], "amount": x["amount"]})
    return {"id": sid, "net": net, "accrued": d["accrued"]}


@api("mn.wage_sheet_pay", "accounts", "edit")
def mn_wage_sheet_pay(c, u, a):
    s = get(c, "mn_wage_sheet", int(a["id"]), "Wage sheet")
    if s["status"] != "draft":
        raise ApiError("This wage sheet is already paid.")
    d = wage_figures(c, s["project_id"], s["month"])
    if abs(d["accrued"] - s["accrued"]) > 0.5:
        raise ApiError("DPR wages for this month changed since the sheet was made (%s now, %s on the sheet). Save the sheet again."
                       % (d["accrued"], s["accrued"]))
    bank = _money_acc(c, a.get("bank_account_id"))
    dt = a.get("date") or today()
    pid = s["project_id"]
    lines = [{"role": "payroll_payable", "debit": s["accrued"], "project_id": pid, "narration": "Wages %s" % _month_label(c, s["month"])},
             {"account_id": bank, "credit": s["net"]},
             {"account_id": _role_acc(c, "wage_advance"), "credit": s["advance_recovery"], "project_id": pid, "narration": "Advance recovered"},
             {"role": "tds_payable", "credit": s["tax"], "narration": "Tax on wages"},
             {"role": "payroll_payable", "credit": s["other_deduction"], "project_id": pid, "narration": "Other deductions held"}]
    vid = _post(c, u, "payment", dt, "Wages paid %s %s" % (_pcode(c, pid), _month_label(c, s["month"])), lines, project_id=pid,
                source="mn_wage", source_id=s["id"], ref_no=a.get("cheque_no"))
    upd(c, "mn_wage_sheet", s["id"], {"status": "paid", "voucher_id": vid, "bank_account_id": bank, "paid_date": dt})
    audit(c, u, "wage_pay", "mn_wage_sheet", s["id"], {"net": s["net"]})
    return {"id": s["id"], "voucher_id": vid, "net": s["net"]}


@api("mn.wage_advance", "accounts", "edit")
def mn_wage_advance(c, u, a):
    pid = int(a["project_id"])
    amt = r2(_f(a.get("amount")))
    if amt <= 0:
        raise ApiError("Enter the advance amount.")
    bank = _money_acc(c, a.get("bank_account_id"))
    dt = a.get("date") or today()
    vid = _post(c, u, "payment", dt, "Wage advance %s %s" % (_pcode(c, pid), a.get("note") or ""),
                [{"account_id": _role_acc(c, "wage_advance"), "debit": amt, "project_id": pid, "narration": a.get("note")},
                 {"account_id": bank, "credit": amt}], project_id=pid, source="mn_wage_adv")
    return {"voucher_id": vid}


def wages_due(c, days=45):
    """Per project and month: DPR wages credited to Wages Payable and not cleared by a paid wage sheet, older than `days`."""
    out = []
    since = setting(c, "mn_wages_from") or ""
    if not since:
        return out                     # wage sheets not in use yet
    lim = (date.fromisoformat(today()) - timedelta(days=days)).isoformat()
    rows = q(c, "SELECT COALESCE(l.project_id, v.project_id) pid, v.date, l.credit-l.debit amt FROM voucher_lines l JOIN vouchers v "
                "ON v.id=l.voucher_id JOIN accounts ac ON ac.id=l.account_id WHERE ac.role='payroll_payable' AND v.source='dpr' "
                "AND v.status='posted' AND v.date BETWEEN ? AND ?", (since, lim))
    paid = q(c, "SELECT project_id, from_date, to_date FROM mn_wage_sheet WHERE status='paid'")
    by = {}
    for r in rows:
        if any(p["project_id"] == r["pid"] and p["from_date"] <= r["date"] <= p["to_date"] for p in paid):
            continue
        k = (r["pid"], r["date"][:7])
        by[k] = by.get(k, 0.0) + _f(r["amt"])
    for (pid, m), v in sorted(by.items(), key=lambda x: (x[0][1], x[0][0] or 0)):
        if v > 0.5:
            out.append({"ref": "%s %s" % (_pcode(c, pid), m), "amount": r2(v), "detail": "DPR wages not on a paid wage sheet"})
    return out


# ───────────────────────────── 3b. staff salary run ─────────────────────────────
def salary_lines(c, ssf=False):
    sst = _f(setting(c, "mn_sst_pct"), 1)
    ee, er = _f(setting(c, "mn_ssf_emp_pct"), 11), _f(setting(c, "mn_ssf_er_pct"), 20)
    out = []
    for s in q(c, "SELECT * FROM staff WHERE COALESCE(active,1)=1 AND COALESCE(monthly_rate,0)>0 ORDER BY code"):
        g = r2(_f(s["monthly_rate"]))
        tax = r2(g * sst / 100)
        se = r2(g * ee / 100) if ssf else 0.0
        sr = r2(g * er / 100) if ssf else 0.0
        out.append({"staff_id": s["id"], "code": s["code"], "name": s["name"], "project_id": s["project_id"], "project": _pcode(c, s["project_id"]),
                    "gross": g, "tax": tax, "ssf_employee": se, "ssf_employer": sr, "net": r2(g - tax - se)})
    return out


@api("mn.salary", "accounts", "view")
def mn_salary(c, u, a):
    m = (a.get("month") or _default_month(c))[:7]
    return {"month": m, "label": _month_label(c, m), "months": _month_list(c),
            "lines": salary_lines(c, a.get("ssf") in (True, 1, "1", "true")),
            "run": q1(c, "SELECT * FROM mn_salary_run WHERE month=?", (m,)),
            "runs": q(c, "SELECT r.*, v.no vno FROM mn_salary_run r LEFT JOIN vouchers v ON v.id=r.voucher_id ORDER BY r.id DESC LIMIT 24")}


@api("mn.salary_run", "accounts", "edit")
def mn_salary_run(c, u, a):
    m = (a.get("month") or "")[:7]
    if not m:
        raise ApiError("Choose the month.")
    if val(c, "SELECT COUNT(*) FROM mn_salary_run WHERE month=?", (m,)):
        raise ApiError("Salaries for %s are already run." % _month_label(c, m))
    ssf = a.get("ssf") in (True, 1, "1", "true")
    ls = salary_lines(c, ssf)
    if not ls:
        raise ApiError("No active staff with a monthly rate.")
    dt = a.get("date") or _window(c, m)[1]
    vl = []
    for x in ls:
        cost = r2(x["gross"] + x["ssf_employer"])
        if x["project_id"]:
            vl.append({"role": "labour_cost", "debit": cost, "project_id": x["project_id"], "narration": "Salary %s" % x["name"]})
        else:
            vl.append({"account_id": _role_acc(c, "salary_ho"), "debit": cost, "narration": "Salary %s" % x["name"]})
        vl.append({"role": "payroll_payable", "credit": x["net"], "project_id": x["project_id"], "narration": "Salary %s" % x["name"]})
    vl.append({"role": "tds_payable", "credit": r2(sum(x["tax"] for x in ls)), "narration": "Social security tax on salaries"})
    vl.append({"account_id": _role_acc(c, "ssf_payable"), "credit": r2(sum(x["ssf_employee"] + x["ssf_employer"] for x in ls)),
               "narration": "SSF"})
    tot = {k: r2(sum(x[k] for x in ls)) for k in ("gross", "tax", "ssf_employee", "ssf_employer", "net")}
    rid = ins(c, "mn_salary_run", dict(tot, month=m, date=dt, status="posted", created_by=u["id"], ts=now()))
    vid = _post(c, u, "journal", dt, "Staff salaries %s" % _month_label(c, m), vl, source="mn_salary", source_id=rid)
    upd(c, "mn_salary_run", rid, {"voucher_id": vid})
    for x in ls:
        ins(c, "mn_salary_lines", {"run_id": rid, "staff_id": x["staff_id"], "name": x["name"], "project_id": x["project_id"],
                                   "gross": x["gross"], "tax": x["tax"], "ssf_employee": x["ssf_employee"],
                                   "ssf_employer": x["ssf_employer"], "net": x["net"]})
    return dict(tot, id=rid, voucher_id=vid)


@api("mn.salary_pay", "accounts", "edit")
def mn_salary_pay(c, u, a):
    r = get(c, "mn_salary_run", int(a["id"]), "Salary run")
    if r["pay_voucher_id"]:
        raise ApiError("These salaries are already paid.")
    bank = _money_acc(c, a.get("bank_account_id"))
    dt = a.get("date") or today()
    by = {}
    for x in q(c, "SELECT project_id, SUM(net) n FROM mn_salary_lines WHERE run_id=? GROUP BY project_id", (r["id"],)):
        by[x["project_id"]] = _f(x["n"])
    vl = [{"role": "payroll_payable", "debit": r2(v), "project_id": p} for p, v in by.items()]
    vl.append({"account_id": bank, "credit": r2(sum(by.values()))})
    vid = _post(c, u, "payment", dt, "Salaries paid %s" % _month_label(c, r["month"]), vl, source="mn_salary_pay", source_id=r["id"])
    upd(c, "mn_salary_run", r["id"], {"pay_voucher_id": vid, "paid_date": dt, "status": "paid"})
    return {"voucher_id": vid}


# ───────────────────────────── 3c. site petty cash (imprest) ─────────────────────────────
def _imprest_balance(c, acc):
    return r2(_f(val(c, "SELECT SUM(l.debit-l.credit) FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id WHERE l.account_id=? "
                        "AND v.status IN ('posted','reversed')", (acc,))))


def imprests(c):
    out = []
    for m in q(c, "SELECT * FROM mn_imprest ORDER BY id"):
        open_ = q(c, "SELECT * FROM mn_slips WHERE imprest_id=? AND status='posted' AND replenish_voucher_id IS NULL ORDER BY date", (m["id"],))
        out.append(dict(m, project=_pcode(c, m["project_id"]), account=val(c, "SELECT code || ' ' || name FROM accounts WHERE id=?", (m["account_id"],), ""),
                        balance=_imprest_balance(c, m["account_id"]), to_replenish=r2(sum(_f(x["amount"]) for x in open_)),
                        slips_open=len(open_)))
    return out


@api("mn.imprests", "accounts", "view")
def mn_imprests(c, u, a):
    res = {"imprests": imprests(c)}
    if a.get("imprest_id"):
        res["slips"] = q(c, "SELECT s.*, (SELECT COUNT(*) FROM files f WHERE f.entity='mn_slip' AND f.entity_id=s.id) files, b.code boq "
                            "FROM mn_slips s LEFT JOIN boq_items b ON b.id=s.boq_item_id WHERE s.imprest_id=? ORDER BY s.date DESC, s.id DESC",
                         (int(a["imprest_id"]),)) if _has(c, "boq_items") else \
            q(c, "SELECT s.*, (SELECT COUNT(*) FROM files f WHERE f.entity='mn_slip' AND f.entity_id=s.id) files FROM mn_slips s "
                 "WHERE s.imprest_id=? ORDER BY s.date DESC", (int(a["imprest_id"]),))
    res["expense_accounts"] = q(c, "SELECT id, code, name FROM accounts WHERE type='expense' AND active=1 ORDER BY code")
    res["default_account"] = _role_acc(c, "site_expense")
    return res


@api("mn.imprest_open", "accounts", "edit")
def mn_imprest_open(c, u, a):
    pid = int(a["project_id"])
    holder = (a.get("holder") or "").strip()
    fl = r2(_f(a.get("float_amount")))
    if not holder or fl <= 0:
        raise ApiError("Give the holder and the float amount.")
    bank = _money_acc(c, a.get("bank_account_id"))
    g = q1(c, "SELECT id FROM account_groups WHERE code='A1'") or q1(c, "SELECT id FROM account_groups WHERE type='asset' ORDER BY id")
    n = val(c, "SELECT COUNT(*) FROM mn_imprest", (), 0) + 1
    code = "1001-I%d" % n
    while q1(c, "SELECT id FROM accounts WHERE code=?", (code,)):
        n += 1
        code = "1001-I%d" % n
    acc = ins(c, "accounts", {"code": code, "name": "Imprest - %s - %s" % (_pcode(c, pid), holder), "type": "asset",
                              "group_id": g["id"] if g else None, "role": None, "opening_balance": 0, "active": 1})
    iid = ins(c, "mn_imprest", {"project_id": pid, "holder": holder, "account_id": acc, "float_amount": fl, "active": 1,
                                "created_by": u["id"], "ts": now()})
    vid = _post(c, u, "payment", a.get("date") or today(), "Petty cash float %s %s" % (_pcode(c, pid), holder),
                [{"account_id": acc, "debit": fl, "project_id": pid}, {"account_id": bank, "credit": fl}], project_id=pid,
                source="mn_imprest", source_id=iid)
    upd(c, "mn_imprest", iid, {"voucher_id": vid})
    return {"id": iid, "account_id": acc}


@api("mn.slip_save", "accounts", "edit")
def mn_slip_save(c, u, a):
    m = get(c, "mn_imprest", int(a["imprest_id"]), "Imprest")
    amt = r2(_f(a.get("amount")))
    if amt <= 0:
        raise ApiError("Enter the amount.")
    over = a.get("overhead") in (True, 1, "1", "true")
    boq = int(a["boq_item_id"]) if a.get("boq_item_id") and not over else None
    row = {"imprest_id": m["id"], "date": a.get("date") or today(), "amount": amt, "description": a.get("description"),
           "project_id": int(a.get("project_id") or m["project_id"]), "boq_item_id": boq, "overhead": 1 if over else 0,
           "account_id": int(a["account_id"]) if a.get("account_id") else _role_acc(c, "site_expense"), "ts": now()}
    if a.get("id"):
        s = get(c, "mn_slips", int(a["id"]), "Slip")
        if s["status"] != "draft":
            raise ApiError("This slip is already posted.")
        upd(c, "mn_slips", s["id"], row)
        return {"id": s["id"]}
    n = val(c, "SELECT COUNT(*) FROM mn_slips WHERE imprest_id=?", (m["id"],), 0) + 1
    row.update({"no": "PC/%s/%d/%04d" % (_pcode(c, m["project_id"]), m["id"], n), "status": "draft", "created_by": u["id"]})
    return {"id": ins(c, "mn_slips", row)}


@api("mn.slip_post", "accounts", "edit")
def mn_slip_post(c, u, a):
    s = get(c, "mn_slips", int(a["id"]), "Slip")
    if s["status"] != "draft":
        raise ApiError("This slip is already posted.")
    if not val(c, "SELECT COUNT(*) FROM files WHERE entity='mn_slip' AND entity_id=?", (s["id"],)):
        raise ApiError("Attach the bill or receipt to slip %s before posting it." % s["no"])
    m = get(c, "mn_imprest", s["imprest_id"])
    if s["boq_item_id"]:
        import api_finance as F
        if hasattr(F, "check_boq"):
            F.check_boq(c, s["boq_item_id"], s["project_id"])
    vid = _post(c, u, "payment", s["date"], "Petty cash %s %s" % (s["no"], s["description"] or ""),
                [{"account_id": s["account_id"], "debit": s["amount"], "project_id": s["project_id"], "boq_item_id": s["boq_item_id"],
                  "narration": s["description"]},
                 {"account_id": m["account_id"], "credit": s["amount"], "project_id": m["project_id"]}],
                project_id=s["project_id"], source="mn_slip", source_id=s["id"])
    upd(c, "mn_slips", s["id"], {"status": "posted", "voucher_id": vid})
    return {"voucher_id": vid}


@api("mn.replenish", "accounts", "edit")
def mn_replenish(c, u, a):
    m = get(c, "mn_imprest", int(a["imprest_id"]), "Imprest")
    open_ = q(c, "SELECT * FROM mn_slips WHERE imprest_id=? AND status='posted' AND replenish_voucher_id IS NULL", (m["id"],))
    amt = r2(sum(_f(x["amount"]) for x in open_))
    if amt <= 0:
        raise ApiError("No posted slips to replenish.")
    bank = _money_acc(c, a.get("bank_account_id"))
    vid = _post(c, u, "payment", a.get("date") or today(), "Petty cash replenished %s %s (%d slips)" % (_pcode(c, m["project_id"]), m["holder"], len(open_)),
                [{"account_id": m["account_id"], "debit": amt, "project_id": m["project_id"]}, {"account_id": bank, "credit": amt}],
                project_id=m["project_id"], source="mn_replenish", source_id=m["id"])
    for x in open_:
        upd(c, "mn_slips", x["id"], {"replenish_voucher_id": vid})
    return {"voucher_id": vid, "amount": amt, "slips": len(open_)}


def _patch_cfw():
    """Slips posted and not yet replenished show in the 13-week forecast this week."""
    import api_cfw as CF
    if getattr(CF.build, FLAG, False):
        return
    orig_build, Grid = CF.build, CF.Grid

    class Grid240(Grid):
        def __init__(self, w0):
            super().__init__(w0)
            c = getattr(_LOCAL, "cfw_c", None)
            if c is None or not _has(c, "mn_imprest"):
                return
            for m in imprests(c):
                if m["to_replenish"] > 0.5:
                    self.add("out", "Petty cash to replenish", "confirmed", max(today(), w0.isoformat()), m["to_replenish"],
                             "Imprest %s %s (%d slips)" % (m["project"], m["holder"], m["slips_open"]), m["project_id"])

    def build(c, u, *a, **k):
        prev = getattr(_LOCAL, "cfw_c", None)
        _LOCAL.cfw_c = c
        try:
            return orig_build(c, u, *a, **k)
        finally:
            _LOCAL.cfw_c = prev
    setattr(build, FLAG, True)
    build._orig = orig_build
    CF.Grid = Grid240
    CF.build = build


# ───────────────────────────── 3d. bank statement import ─────────────────────────────
_DATE_FMTS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d-%b-%Y", "%d %b %Y", "%d-%b-%y", "%Y/%m/%d", "%m/%d/%Y", "%d/%m/%y")


def _pdate(s):
    if isinstance(s, (int, float)) and 20000 < s < 80000:
        return (date(1899, 12, 30) + timedelta(days=int(s))).isoformat()
    s = str(s or "").strip()
    if not s:
        return None
    if re.match(r"^\d{5}(\.0+)?$", s):
        return (date(1899, 12, 30) + timedelta(days=int(float(s)))).isoformat()
    s = s.split(" ")[0] if re.match(r"^\d{4}-\d{2}-\d{2} ", s) else s
    for f in _DATE_FMTS:
        try:
            return datetime.strptime(s, f).date().isoformat()
        except ValueError:
            continue
    return None


def _xlsx_rows(data):
    z = zipfile.ZipFile(io.BytesIO(data))
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", ns):
            shared.append("".join(t.text or "" for t in si.iter("{%s}t" % ns["m"])))
    sheets = sorted(n for n in z.namelist() if n.startswith("xl/worksheets/sheet"))
    if not sheets:
        raise ApiError("No sheet in this Excel file.")
    rows = []
    for r in ET.fromstring(z.read(sheets[0])).iter("{%s}row" % ns["m"]):
        out = {}
        for cell in r.findall("m:c", ns):
            ref = cell.get("r") or ""
            col = 0
            for ch in re.match(r"[A-Z]+", ref).group(0) if re.match(r"[A-Z]+", ref) else "A":
                col = col * 26 + ord(ch) - 64
            v = cell.find("m:v", ns)
            t = cell.get("t")
            if t == "s" and v is not None:
                val_ = shared[int(v.text)]
            elif t == "inlineStr":
                val_ = "".join(x.text or "" for x in cell.iter("{%s}t" % ns["m"]))
            else:
                val_ = v.text if v is not None else ""
            out[col - 1] = val_
        if out:
            rows.append([out.get(i, "") for i in range(max(out) + 1)])
    return rows


def _table(name, content):
    raw = base64.b64decode(content) if content else b""
    if (name or "").lower().endswith((".xlsx", ".xlsm")):
        return _xlsx_rows(raw)
    text = raw.decode("utf-8-sig", errors="replace")
    try:
        dialect = csv.Sniffer().sniff(text[:4000], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    return [r for r in csv.reader(io.StringIO(text), dialect) if any(str(x).strip() for x in r)]


KEYS = {"date": ("value date", "txn date", "transaction date", "date"), "description": ("description", "narration", "particular", "details", "remarks"),
        "ref": ("cheque", "chq", "instrument", "reference", "ref"), "withdrawal": ("withdraw", "debit", "dr"),
        "deposit": ("deposit", "credit", "cr"), "amount": ("amount",)}


def guess_columns(rows):
    for i, r in enumerate(rows[:15]):
        cells = [str(x).strip().lower() for x in r]
        if sum(1 for x in cells if x and not re.match(r"^[\d,.\-/ ]+$", x)) < 2:
            continue
        m = {}
        for k in ("date", "withdrawal", "deposit", "ref", "description", "amount"):
            for j, x in enumerate(cells):
                if j in m.values():
                    continue
                if any(x == w or x.startswith(w) or (" " + w) in x or (w in x and len(w) > 3) for w in KEYS[k]):
                    m[k] = j
                    break
        if "date" in m and ("amount" in m or "withdrawal" in m or "deposit" in m):
            return i, m
    return None, {}


def parse_statement(rows, mapping=None, header=None):
    if mapping is None:
        header, mapping = guess_columns(rows)
        if header is None:
            raise ApiError("Could not find the date and amount columns. Choose them below.")
    out = []
    for n, r in enumerate(rows[(header or 0) + 1:], start=(header or 0) + 2):
        get_ = lambda k: r[mapping[k]] if k in mapping and mapping[k] is not None and mapping[k] < len(r) else ""
        d = _pdate(get_("date"))
        if not d:
            continue
        wd, dp = _f(get_("withdrawal")), _f(get_("deposit"))
        if "amount" in mapping and not wd and not dp:
            amt = _f(get_("amount"))
            wd, dp = (-amt, 0.0) if amt < 0 else (0.0, amt)
        if abs(wd) < EPS and abs(dp) < EPS:
            continue
        out.append({"row_no": n, "date": d, "description": str(get_("description") or "").strip(), "ref": str(get_("ref") or "").strip(),
                    "withdrawal": r2(abs(wd)), "deposit": r2(abs(dp))})
    return out, header, mapping


def _digits(s):
    return re.sub(r"\D", "", str(s or ""))


def auto_match(c, bank, stmt):
    import api_finance as F
    book = F.bank_lines(c, None, {"account_id": bank, "to": "9999-12-31"})["rows"]
    free = [b for b in book if not b["cleared_date"]]
    used = set()
    res = {}

    def amt(b):
        return ("deposit", r2(b["debit"])) if b["debit"] > EPS else ("withdrawal", r2(b["credit"]))
    for pass_ in (1, 2):
        for s in stmt:
            if s["row_no"] in res:
                continue
            side, a_ = ("deposit", s["deposit"]) if s["deposit"] > EPS else ("withdrawal", s["withdrawal"])
            best = None
            for b in free:
                if b["id"] in used or amt(b) != (side, a_):
                    continue
                gap = abs((date.fromisoformat(b["date"]) - date.fromisoformat(s["date"])).days)
                if pass_ == 1:
                    ref = _digits(s["ref"]) or _digits(s["description"])
                    br = _digits(b.get("ref_no"))
                    if ref and br and (br in ref or ref.endswith(br)) and len(br) >= 3:
                        best = (gap, b)
                        break
                elif gap <= 7 and (best is None or gap < best[0]):
                    best = (gap, b)
            if best:
                used.add(best[1]["id"])
                res[s["row_no"]] = (best[1], "reference" if pass_ == 1 else "amount and date (%d day%s)" % (best[0], "" if best[0] == 1 else "s"))
    return res, free


@api("mn.stmt_import", "accounts", "edit")
def mn_stmt_import(c, u, a):
    bank = _money_acc(c, a.get("bank_account_id"))
    rows = _table(a.get("filename") or "statement.csv", a.get("content"))
    mapping = a.get("mapping")
    if mapping:
        mapping = {k: (int(v) if v not in (None, "") else None) for k, v in mapping.items()}
    stmt, header, mapping = parse_statement(rows, mapping, int(a["header_row"]) if a.get("header_row") not in (None, "") else None)
    if not stmt:
        raise ApiError("No dated lines with an amount were found in this file.")
    imp = "%s-%s" % (bank, now().replace(":", "").replace("-", "")[:15])
    match, _free = auto_match(c, bank, stmt)
    for s in stmt:
        m = match.get(s["row_no"])
        ins(c, "mn_stmt", dict(s, import_id=imp, bank_account_id=bank, line_id=m[0]["id"] if m else None, how=m[1] if m else None,
                               status="matched" if m else "open", user_id=u["id"], ts=now()))
    return dict(mn_stmt_list(c, u, {"import_id": imp}), header=header, mapping=mapping,
                columns=rows[header] if header is not None and header < len(rows) else [])


@api("mn.stmt_list", "accounts", "view")
def mn_stmt_list(c, u, a):
    cond, p = "", []
    if a.get("import_id"):
        cond, p = "WHERE s.import_id=?", [a["import_id"]]
    elif a.get("bank_account_id"):
        cond, p = "WHERE s.bank_account_id=?", [int(a["bank_account_id"])]
    rows = q(c, "SELECT s.*, v.no vno, v.date vdate, v.ref_no FROM mn_stmt s LEFT JOIN voucher_lines l ON l.id=s.line_id "
                "LEFT JOIN vouchers v ON v.id=l.voucher_id %s ORDER BY s.import_id DESC, s.row_no" % cond, p)
    imports = q(c, "SELECT import_id, bank_account_id, MIN(date) frm, MAX(date) til, COUNT(*) n, SUM(status='matched') matched, "
                   "SUM(status='cleared') cleared FROM mn_stmt GROUP BY import_id ORDER BY import_id DESC LIMIT 20")
    return {"rows": rows, "imports": imports, "matched": sum(1 for r in rows if r["status"] == "matched"),
            "cleared": sum(1 for r in rows if r["status"] == "cleared"), "open": sum(1 for r in rows if r["status"] == "open")}


@api("mn.stmt_match", "accounts", "edit")
def mn_stmt_match(c, u, a):
    s = get(c, "mn_stmt", int(a["id"]), "Statement line")
    if s["status"] == "cleared":
        raise ApiError("This line is already cleared.")
    if a.get("line_id"):
        lid = int(a["line_id"])
        if val(c, "SELECT COUNT(*) FROM mn_stmt WHERE line_id=? AND id<>? AND status IN ('matched','cleared')", (lid, s["id"])):
            raise ApiError("That book entry is already matched to another statement line.")
        upd(c, "mn_stmt", s["id"], {"line_id": lid, "how": "by hand", "status": "matched"})
    else:
        upd(c, "mn_stmt", s["id"], {"line_id": None, "how": None, "status": "open"})
    return True


@api("mn.stmt_confirm", "accounts", "edit")
def mn_stmt_confirm(c, u, a):
    n = 0
    for s in q(c, "SELECT * FROM mn_stmt WHERE import_id=? AND status='matched' AND line_id IS NOT NULL", (a["import_id"],)):
        c.execute("UPDATE voucher_lines SET cleared_date=? WHERE id=? AND cleared_date IS NULL", (s["date"], s["line_id"]))
        upd(c, "mn_stmt", s["id"], {"status": "cleared"})
        n += 1
    audit(c, u, "stmt_confirm", "mn_stmt", None, {"import_id": a["import_id"], "cleared": n})
    return {"cleared": n}


@api("mn.stmt_candidates", "accounts", "view")
def mn_stmt_candidates(c, u, a):
    s = get(c, "mn_stmt", int(a["id"]), "Statement line")
    import api_finance as F
    used = {r["line_id"] for r in q(c, "SELECT line_id FROM mn_stmt WHERE line_id IS NOT NULL AND status IN ('matched','cleared') AND id<>?", (s["id"],))}
    book = [b for b in F.bank_lines(c, u, {"account_id": s["bank_account_id"], "to": "9999-12-31"})["rows"]
            if not b["cleared_date"] and b["id"] not in used]
    want = s["deposit"] if s["deposit"] > EPS else s["withdrawal"]
    side = "debit" if s["deposit"] > EPS else "credit"
    book.sort(key=lambda b: (abs(b[side] - want) > 0.01, abs((date.fromisoformat(b["date"]) - date.fromisoformat(s["date"])).days)))
    return [b for b in book if b[side] > EPS][:15]


# ───────────────────────────── 4. one loan register ─────────────────────────────
def machine_loans(c):
    if not _has(c, "eq_finance"):
        return []
    out = []
    for f in q(c, "SELECT f.*, e.code, e.name ename FROM eq_finance f JOIN equipment e ON e.id=f.equipment_id WHERE COALESCE(f.loan_amount,0)>0 ORDER BY e.code"):
        led = val(c, "SELECT SUM(l.credit-l.debit) FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id JOIN accounts ac ON ac.id=l.account_id "
                     "WHERE ac.role='equipment_loan' AND l.equipment_id=? AND v.status IN ('posted','reversed')", (f["equipment_id"],))
        paid = _f(val(c, "SELECT SUM(principal) FROM eq_emi WHERE equipment_id=?", (f["equipment_id"],)))
        end = None
        if f["first_emi_date"] and f["emi_count"]:
            import api_fc as FC
            end = FC._add_months(f["first_emi_date"], int(f["emi_count"]) - 1)
        out.append({"id": "eq-%s" % f["equipment_id"], "equipment_id": f["equipment_id"], "source": "equipment",
                    "name": "Machine loan %s" % f["code"], "lender": f["lender"], "kind": "equipment", "emi": f["emi"],
                    "start_date": f["first_emi_date"], "end_date": end, "rate": f["interest_rate"], "limit_amount": None,
                    "balance": r2(_f(led)) if led is not None else r2(_f(f["loan_amount"]) - paid),
                    "balance_basis": "ledger (Equipment Loans with %s)" % f["code"] if led is not None else "loan less principal paid",
                    "active": 1, "readonly": True,
                    "remarks": "From Equipment finance (%s %s). Change it there." % (f["code"], f["ename"])})
    return out


def _loan_ledger(c, l):
    if not l.get("account_id"):
        return None
    cond, p = "l.account_id=?", [l["account_id"]]
    if l.get("party_id"):
        cond += " AND l.party_id=?"
        p.append(l["party_id"])
    return r2(_f(val(c, "SELECT SUM(l.credit-l.debit) FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id WHERE %s "
                        "AND v.status IN ('posted','reversed')" % cond, p)))


def _w_loan_list(orig):
    def loan_list(c, u, a):
        rows = [dict(r) for r in orig(c, u, a)]
        for r in rows:
            r["source"] = "typed"
            if r.get("equipment_id"):
                code = val(c, "SELECT code FROM equipment WHERE id=?", (r["equipment_id"],), "")
                r["remarks"] = ("Counted from Equipment finance - %s. " % code) + (r.get("remarks") or "")
                r["linked_machine"] = code
            led = _loan_ledger(c, r)
            if led is not None:
                r["ledger_balance"] = led
                r["typed_balance"] = r.get("balance")
        return rows + machine_loans(c)
    return loan_list


def _w_loan_save(orig):
    def loan_save(c, u, a):
        r = a.get("row") or {}
        if str(r.get("id") or "").startswith("eq-"):
            raise ApiError("This loan is kept in Equipment finance. Change it there (Equipment › the machine › Finance).")
        res = orig(c, u, a)
        extra = {}
        for k in ("account_id", "party_id"):
            if k in r:
                extra[k] = int(r[k]) if r.get(k) not in (None, "") else None
        if extra and res.get("id"):
            upd(c, "loans", res["id"], extra)
        return res
    return loan_save


def _w_loan_delete(orig):
    def loan_delete(c, u, a):
        if str(a.get("id") or "").startswith("eq-"):
            raise ApiError("This loan is kept in Equipment finance.")
        return orig(c, u, a)
    return loan_delete


def link_suggestions(c):
    out = []
    ml = machine_loans(c)
    for l in q(c, "SELECT * FROM loans WHERE active=1 AND equipment_id IS NULL"):
        for m in ml:
            same_lender = (l["lender"] or "").strip().lower() and (l["lender"] or "").strip().lower() == (m["lender"] or "").strip().lower()
            same_emi = _f(l["emi"]) and abs(_f(l["emi"]) - _f(m["emi"])) < 1
            if same_lender or same_emi:
                out.append({"loan_id": l["id"], "loan": l["name"], "equipment_id": m["equipment_id"], "machine": m["name"],
                            "why": "same lender and instalment" if same_lender and same_emi else ("same lender" if same_lender else "same instalment")})
    return out


@api("mn.loans", "accounts", "view")
def mn_loans(c, u, a):
    typed = [dict(r) for r in q(c, "SELECT l.*, e.code machine FROM loans l LEFT JOIN equipment e ON e.id=l.equipment_id ORDER BY l.active DESC, l.name")]
    for r in typed:
        r["ledger_balance"] = _loan_ledger(c, r)
    return {"machine_loans": machine_loans(c), "typed": typed, "suggestions": link_suggestions(c),
            "machines": q(c, "SELECT f.equipment_id id, e.code, e.name FROM eq_finance f JOIN equipment e ON e.id=f.equipment_id WHERE COALESCE(f.loan_amount,0)>0 ORDER BY e.code") if _has(c, "eq_finance") else [],
            "accounts": q(c, "SELECT id, code, name FROM accounts WHERE type='liability' AND active=1 ORDER BY code"),
            "can_link": _right(u, "accounts", "edit")}


@api("mn.loan_link", "accounts", "edit")
def mn_loan_link(c, u, a):
    l = get(c, "loans", int(a["loan_id"]), "Loan")
    if a.get("undo"):
        k = q1(c, "SELECT * FROM mn_loan_link WHERE loan_id=? AND undone_ts IS NULL ORDER BY id DESC", (l["id"],))
        if not k:
            raise ApiError("This loan is not linked to a machine.")
        upd(c, "loans", l["id"], {"equipment_id": None, "active": k["prev_active"] if k["prev_active"] is not None else 1})
        upd(c, "mn_loan_link", k["id"], {"undone_ts": now()})
        return True
    eid = int(a["equipment_id"])
    if not val(c, "SELECT COUNT(*) FROM eq_finance WHERE equipment_id=? AND COALESCE(loan_amount,0)>0", (eid,)):
        raise ApiError("That machine has no loan in Equipment finance.")
    ins(c, "mn_loan_link", {"loan_id": l["id"], "equipment_id": eid, "prev_active": l["active"], "user_id": u["id"], "ts": now()})
    upd(c, "loans", l["id"], {"equipment_id": eid, "active": 0})
    audit(c, u, "loan_link", "loans", l["id"], {"equipment_id": eid})
    return True


# ───────────────────────────── checks ─────────────────────────────
def checks(c):
    out = []

    def add(area, name, sev, ok, detail, items=None, fix=None, amount=None):
        out.append({"area": area, "check": name, "ok": bool(ok), "severity": "ok" if ok else sev, "detail": detail,
                    "items": (items or [])[:50], "count": len(items or []), "fix": None if ok else fix, "amount": amount})
    dp = direct_payments(c)
    add("Payables", "Supplier and subcontractor payments made without a payment request", "warn", not dp,
        ("%d payment(s) since %s" % (len(dp), setting(c, "mn_payreq_from"))) if dp else
        ("None since %s" % setting(c, "mn_payreq_from") if payreq_on(c) else "Payment requests are not required (Accounts › Payments › Money settings)"),
        [{"ref": x["no"], "amount": x["gross"], "detail": "%s %s" % (x["date"], x["party"])} for x in dp], "Accounts › Payment requests")
    wd = wages_due(c)
    add("Payables", "Wages payable older than 45 days", "warn", not wd, "%d project-month(s)" % len(wd) if wd else
        ("None since %s" % setting(c, "mn_wages_from") if setting(c, "mn_wages_from") else "Wage sheets not in use yet (Accounts › Payments › Wages)"),
        wd, "Accounts › Payments › Wages", r2(sum(x["amount"] for x in wd)))
    bad = []
    for m in imprests(c):
        if m["balance"] < -0.5 or m["balance"] + m["to_replenish"] - m["float_amount"] > 0.5:
            bad.append({"ref": "%s %s" % (m["project"], m["holder"]), "amount": m["balance"],
                        "detail": "balance %s, float %s, to replenish %s" % (m["balance"], m["float_amount"], m["to_replenish"])})
    add("Cash and bank", "Petty cash: balance + slips to replenish = float", "warn", not bad, "%d imprest(s) differ" % len(bad) if bad else
        "Every imprest agrees", bad, "Accounts › Payments › Petty cash")
    lb = []
    for l in q(c, "SELECT * FROM loans WHERE active=1 AND account_id IS NOT NULL"):
        led = _loan_ledger(c, dict(l))
        if led is not None and abs(led - _f(l["balance"])) > 1:
            lb.append({"ref": l["name"], "amount": r2(_f(l["balance"]) - led), "detail": "typed %s, ledger %s" % (r2(_f(l["balance"])), led)})
    add("Loans", "Loan balances typed = ledger", "warn", not lb, "%d loan(s) differ" % len(lb) if lb else "Every loan with a ledger account agrees",
        lb, "Accounts › Cash forecast & ratios › Loans")
    ml = [x for x in asset_links(c) if x["status"] != "agrees"]
    add("Fixed assets", "Each machine's cost = its ledger lines", "warn", not ml, "%d machine(s) differ" % len(ml) if ml else "Every machine agrees",
        [{"ref": x["code"], "amount": x["difference"], "detail": "register %s, ledger lines %s (%s)" % (x["register_cost"], x["ledger"], x["status"])} for x in ml],
        "Fixed assets › Capital register › Link to ledger")
    return out


def _w_fc_checks(orig):
    def fc_checks(c, u, a):
        res = orig(c, u, a)
        if isinstance(res, dict) and isinstance(res.get("checks"), list):
            res["checks"].extend(checks(c))
            if "ok" in res and isinstance(res.get("ok"), (int, bool)):
                res["ok"] = all(x["ok"] for x in res["checks"])
        return res
    return fc_checks


def _w_integrity(orig):
    def rep_integrity(c, u, a):
        res = orig(c, u, a)
        if isinstance(res, list):
            have = {x.get("check") for x in res}
            for x in checks(c):
                if x["check"] not in have:
                    res.append({"check": x["check"], "ok": x["ok"], "detail": x["detail"] + (
                        ": " + ", ".join(str(i.get("ref", "")) for i in x["items"][:8]) if x["items"] and not x["ok"] else "")})
        return res
    return rep_integrity


# ───────────────────────────── start-up ─────────────────────────────
def _default(c, key, new_value, old_value):
    if val(c, "SELECT COUNT(*) FROM settings WHERE key=?", (key,)):
        return
    used = val(c, "SELECT COUNT(*) FROM vouchers") if _has(c, "vouchers") else 0
    c.execute("INSERT OR IGNORE INTO settings(key, value) VALUES(?,?)", (key, old_value if used else new_value))


def init_money(c):
    c.executescript(SCHEMA)
    if _has(c, "loans"):
        cols = _cols(c, "loans")
        for col in ("equipment_id", "account_id", "party_id"):
            if col not in cols:
                c.execute("ALTER TABLE loans ADD COLUMN %s INTEGER" % col)
    _default(c, "mn_payreq_required", "1", "0")
    if setting(c, "mn_payreq_required") == "1" and not setting(c, "mn_payreq_from"):
        _set(c, "mn_payreq_from", today())
    c.commit()
    _wrap("invoice.post", _w_invoice_post)
    _wrap("payment.create", _w_payment_create)
    _wrap("loan.list", _w_loan_list)
    _wrap("loan.save", _w_loan_save)
    _wrap("loan.delete", _w_loan_delete)
    _wrap("fc.checks", _w_fc_checks)
    _wrap("rep.integrity", _w_integrity)
    _patch_payreq_pay()
    _patch_cfw()
