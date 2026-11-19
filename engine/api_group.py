"""BuildCore 2.61 "Group and statutory" (A4, A7, A8, A11, A12, L3, B1).

* Group view (A4): trial balance, profit and loss and balance sheet of every company on this BuildCore added up
  (each company file is read only), and the balances companies show against each other (a party whose name or PAN
  is another company's), to cancel on consolidation.
* Cheques and post-dated cheques (A7): cheque books per bank account, cheque register, cheques received from clients
  and given to suppliers with their dates (held, deposited / presented, cleared, bounced, cancelled), a cheque to
  print with the amount in words; alert "Post-dated cheque due" (off on existing companies).  Nothing is posted:
  the payment or receipt is entered as before and can be linked to its cheque.
* Approval limits (A8): per user or job, the largest purchase order, purchase bill, payment, voucher and
  subcontract bill they may approve, with a stand-in for a period.  Switch ap_on (off on existing companies).
* VAT and TDS files (A11): the monthly VAT return worksheet (sales, purchases, imports, exempt, VAT payable or credit)
  and the TDS return list per deductee with PAN, payment and TDS, both as Excel-ready CSV for the IRD portal.
* Year-end checklist (A12): before and after Fiscal years > Close: drafts, unapproved DPRs, periods locked, bank
  reconciled to the year end, depreciation run for every month, open bills carried forward bill-wise, stock frozen
  against the ledger, retention open per party, TDS deposited.
* Tally XML (L3): export the chart (ledgers under the Tally groups of the Gateway, parties as their own ledgers)
  and the vouchers of a period as a Tally import file; read a Tally export and bring its vouchers in as draft
  journal vouchers when every ledger is matched.
* Alternate units (B1): other units per material (bag = 50 kg, truck = 100 cft ...); documents may be entered in
  the other unit and are stored in the material's own unit; stock shown in both.
"""
import csv
import io
import json
import os
import re
import sqlite3
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from xml.sax.saxutils import escape

import core
from core import ApiError, audit, ins, now, q, q1, setting, today, upd, val
import api_inventory as inv
from api_inventory import api

VERSION = "2.61.0"
FLAG = "_bco261"
EPS = 0.0005
POSTED = "v.status IN ('posted','reversed')"

SCHEMA = """
CREATE TABLE IF NOT EXISTS chq_books(id INTEGER PRIMARY KEY, bank_account_id INTEGER, from_no TEXT, to_no TEXT, next_no TEXT, received_on TEXT, active INTEGER DEFAULT 1, note TEXT);
CREATE TABLE IF NOT EXISTS chq_cheques(id INTEGER PRIMARY KEY, direction TEXT, book_id INTEGER, bank_account_id INTEGER, party_id INTEGER, payee TEXT, drawer_bank TEXT,
  cheque_no TEXT, cheque_date TEXT, amount REAL, status TEXT, project_id INTEGER, payment_id INTEGER, note TEXT, status_date TEXT, history TEXT,
  created_by INTEGER, ts TEXT);
CREATE TABLE IF NOT EXISTS ap_limits(id INTEGER PRIMARY KEY, doc TEXT, user_id INTEGER, role TEXT, max_amount REAL, standin_user_id INTEGER, standin_from TEXT,
  standin_to TEXT, active INTEGER DEFAULT 1, note TEXT, ts TEXT);
CREATE TABLE IF NOT EXISTS ap_log(id INTEGER PRIMARY KEY, doc TEXT, doc_id INTEGER, amount REAL, user_id INTEGER, on_behalf INTEGER, ts TEXT);
CREATE TABLE IF NOT EXISTS mat_units(id INTEGER PRIMARY KEY, material_id INTEGER, unit TEXT, factor REAL, note TEXT, UNIQUE(material_id, unit));
"""
DOCS = [("po", "Purchase order"), ("bill", "Purchase bill"), ("payment", "Payment"), ("voucher", "Voucher"), ("subbill", "Subcontract bill")]
DLABEL = dict(DOCS)


def _f(x, d=0.0):
    try:
        return float(x) if x not in (None, "") else d
    except (TypeError, ValueError):
        return d


def r2(x):
    return round(_f(x) + 0.0, 2)


def _set(c, k, v):
    c.execute("INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (k, v))


def _has(c, t):
    return bool(q1(c, "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (t,)))


def _call(c, u, name, args):
    f, module, action, _p = inv.FUNCS[name]
    if module:
        core.require(u, module, action)
    return f(c, u, dict(args))


# ───────────────────────── A4: group view ─────────────────────────
def _companies():
    import api_corp as CO
    out = []
    for co in CO.registry()["companies"]:
        try:
            _d, _b, db = CO._paths(co)
        except Exception:
            continue
        if os.path.exists(db) and not co.get("broken"):
            out.append((co["code"], co.get("name") or co["code"], db))
    return out


def _ro(db):
    k = sqlite3.connect("file:%s?mode=ro" % db, uri=True, timeout=10)
    k.row_factory = sqlite3.Row
    return k


def _company_tb(k, frm, to):
    rows = []
    for a in k.execute("SELECT id, code, name, type, role, opening_balance FROM accounts ORDER BY code").fetchall():
        op = k.execute("SELECT COALESCE(SUM(l.debit-l.credit),0) FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id WHERE l.account_id=? AND " + POSTED +
                       " AND v.date<?", (a["id"], frm)).fetchone()[0] + (a["opening_balance"] or 0)
        mv = k.execute("SELECT COALESCE(SUM(l.debit),0), COALESCE(SUM(l.credit),0) FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id WHERE l.account_id=? AND "
                       + POSTED + " AND v.date BETWEEN ? AND ?", (a["id"], frm, to)).fetchone()
        if a["type"] in ("income", "expense"):
            op = 0.0 if frm > "0000-01-02" else op
        rows.append({"code": a["code"], "name": a["name"], "type": a["type"], "role": a["role"], "opening": op, "debit": mv[0], "credit": mv[1], "closing": op + mv[0] - mv[1]})
    return rows


def _setting_ro(k, key):
    r = k.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return r[0] if r else None


@api("gp.group", "accounts", "view")
def gp_group(c, u, a):
    to = a.get("to") or today()
    frm = a.get("from") or "0000-01-01"
    cos = _companies()
    per = []
    by_code = {}
    names = {}
    for code, name, db in cos:
        k = _ro(db)
        try:
            cname = _setting_ro(k, "company_name") or name
            pan = (_setting_ro(k, "company_pan") or "").strip()
            tb = _company_tb(k, frm, to)
        finally:
            k.close()
        names[code] = {"name": cname, "pan": pan}
        inc = sum(-(r["closing"]) for r in tb if r["type"] == "income")
        exp = sum(r["closing"] for r in tb if r["type"] == "expense")
        assets = sum(r["closing"] for r in tb if r["type"] == "asset")
        liab = sum(-r["closing"] for r in tb if r["type"] in ("liability", "equity"))
        per.append({"code": code, "name": cname, "income": r2(inc), "expense": r2(exp), "profit": r2(inc - exp), "assets": r2(assets), "liabilities": r2(liab),
                    "balanced": abs(sum(r["closing"] for r in tb)) < 1})
        for r in tb:
            key = (r["type"], r["name"].strip().lower())
            x = by_code.setdefault(key, {"type": r["type"], "name": r["name"], "codes": set(), "by": {}})
            x["codes"].add(r["code"])
            x["by"][code] = x["by"].get(code, 0) + r["closing"]
    tb_rows = []
    order = {"asset": 0, "liability": 1, "equity": 2, "income": 3, "expense": 4}
    for key, x in sorted(by_code.items(), key=lambda kv: (order.get(kv[0][0], 9), kv[1]["name"])):
        tot = sum(x["by"].values())
        if all(abs(v) < 0.5 for v in x["by"].values()):
            continue
        tb_rows.append({"type": x["type"], "name": x["name"], "codes": ", ".join(sorted(x["codes"])), "by": {k: r2(v) for k, v in x["by"].items()}, "total": r2(tot)})
    # inter-company balances
    inter = []
    for code, name, db in cos:
        k = _ro(db)
        try:
            parties = k.execute("SELECT id, name, pan, kind FROM parties").fetchall()
            for other, info in names.items():
                if other == code:
                    continue
                for p in parties:
                    same_pan = info["pan"] and (p["pan"] or "").strip() == info["pan"]
                    same_name = (p["name"] or "").strip().lower() == (info["name"] or "").strip().lower()
                    if not (same_pan or same_name):
                        continue
                    bal = k.execute("SELECT COALESCE(SUM(l.debit-l.credit),0) FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id JOIN accounts ac ON ac.id=l.account_id "
                                    "WHERE l.party_id=? AND " + POSTED + " AND v.date<=? AND ac.type IN ('asset','liability')", (p["id"], to)).fetchone()[0]
                    inter.append({"company": code, "company_name": names[code]["name"], "party": p["name"], "other": other, "other_name": info["name"],
                                  "balance": r2(bal), "matched_by": "PAN" if same_pan else "name"})
        finally:
            k.close()
    pairs = []
    for x in inter:
        mirror = next((y for y in inter if y["company"] == x["other"] and y["other"] == x["company"]), None)
        if x["company"] < x["other"] or not mirror:
            pairs.append({"a": x["company_name"], "a_shows": x["balance"], "b": x["other_name"], "b_shows": mirror["balance"] if mirror else None,
                          "difference": r2(x["balance"] + (mirror["balance"] if mirror else 0)) if mirror else None, "matched_by": x["matched_by"]})
    tot = {k: r2(sum(p[k] for p in per)) for k in ("income", "expense", "profit", "assets", "liabilities")}
    elim = r2(sum(abs(x["a_shows"]) for x in pairs))
    return {"to": to, "from": frm, "companies": per, "codes": [p["code"] for p in per], "names": {p["code"]: p["name"] for p in per}, "tb": tb_rows, "total": tot,
            "intercompany": inter, "pairs": pairs, "eliminate": elim}


# ───────────────────────── A7: cheques ─────────────────────────
CH_STATUS = {"received": ["held", "deposited", "cleared", "bounced", "returned", "cancelled"],
             "given": ["issued", "presented", "cleared", "bounced", "cancelled", "void"]}


def _inc(no):
    m = re.match(r"^(.*?)(\d+)$", no or "")
    if not m:
        return no
    return m.group(1) + str(int(m.group(2)) + 1).zfill(len(m.group(2)))


@api("chq.list", "accounts", "view")
def chq_list(c, u, a):
    t = today()
    cond, p = ["1=1"], []
    if a.get("direction"):
        cond.append("x.direction=?")
        p.append(a["direction"])
    rows = q(c, "SELECT x.*, pa.name party, ac.name bank, pr.code project, pm.no payment_no FROM chq_cheques x LEFT JOIN parties pa ON pa.id=x.party_id "
                "LEFT JOIN accounts ac ON ac.id=x.bank_account_id LEFT JOIN projects pr ON pr.id=x.project_id LEFT JOIN payments pm ON pm.id=x.payment_id WHERE "
                + " AND ".join(cond) + " ORDER BY x.cheque_date DESC, x.id DESC", p)
    for r in rows:
        r["days"] = (date.fromisoformat(r["cheque_date"]) - date.fromisoformat(t)).days if r["cheque_date"] else None
        r["pdc"] = bool(r["cheque_date"] and r["cheque_date"] > t and r["status"] in ("held", "issued"))
        r["due"] = bool(r["cheque_date"] and r["cheque_date"] <= t and r["status"] in ("held", "issued"))
    books = q(c, "SELECT b.*, ac.name bank FROM chq_books b LEFT JOIN accounts ac ON ac.id=b.bank_account_id ORDER BY b.active DESC, b.id DESC")
    s = lambda d, st: r2(sum(r["amount"] or 0 for r in rows if r["direction"] == d and r["status"] in st))
    return {"rows": rows, "books": books, "statuses": CH_STATUS,
            "summary": {"pdc_received": s("received", ("held",)), "pdc_given": s("given", ("issued",)), "deposited": s("received", ("deposited",)),
                        "presented": s("given", ("presented",)), "bounced": s("received", ("bounced",)) + s("given", ("bounced",))}}


@api("chq.book_save", "accounts", "edit")
def chq_book_save(c, u, a):
    if not a.get("bank_account_id") or not a.get("from_no") or not a.get("to_no"):
        raise ApiError("Bank account and the first and last cheque numbers are needed.")
    row = {"bank_account_id": int(a["bank_account_id"]), "from_no": a["from_no"].strip(), "to_no": a["to_no"].strip(), "next_no": (a.get("next_no") or a["from_no"]).strip(),
           "received_on": a.get("received_on") or today(), "active": 0 if a.get("active") in (0, "0") else 1, "note": a.get("note")}
    if a.get("id"):
        upd(c, "chq_books", int(a["id"]), row)
        return {"id": int(a["id"])}
    return {"id": ins(c, "chq_books", row)}


@api("chq.save", "accounts", "edit")
def chq_save(c, u, a):
    d = a.get("direction")
    if d not in CH_STATUS:
        raise ApiError("Received or given?")
    if not a.get("cheque_date") or _f(a.get("amount")) <= 0:
        raise ApiError("Cheque date and amount are needed.")
    row = {"direction": d, "party_id": int(a["party_id"]) if a.get("party_id") else None, "payee": a.get("payee"), "drawer_bank": a.get("drawer_bank"),
           "cheque_no": (a.get("cheque_no") or "").strip() or None, "cheque_date": a["cheque_date"], "amount": r2(a["amount"]),
           "bank_account_id": int(a["bank_account_id"]) if a.get("bank_account_id") else None, "project_id": int(a["project_id"]) if a.get("project_id") else None,
           "payment_id": int(a["payment_id"]) if a.get("payment_id") else None, "note": a.get("note")}
    if d == "given" and not row["cheque_no"] and a.get("book_id"):
        b = q1(c, "SELECT * FROM chq_books WHERE id=?", (int(a["book_id"]),))
        if b:
            row["cheque_no"], row["book_id"], row["bank_account_id"] = b["next_no"], b["id"], b["bank_account_id"]
            upd(c, "chq_books", b["id"], {"next_no": _inc(b["next_no"]), "active": 0 if b["next_no"] == b["to_no"] else 1})
    if not row["cheque_no"]:
        raise ApiError("Give the cheque number (or choose the cheque book).")
    if a.get("id"):
        upd(c, "chq_cheques", int(a["id"]), row)
        cid = int(a["id"])
    else:
        row.update(status="held" if d == "received" else "issued", status_date=today(), history=json.dumps([[today(), "held" if d == "received" else "issued", u["id"]]]),
                   created_by=u["id"], ts=now())
        cid = ins(c, "chq_cheques", row)
    audit(c, u, "save", "chq_cheques", cid, row)
    return {"id": cid}


@api("chq.status", "accounts", "edit")
def chq_status(c, u, a):
    x = q1(c, "SELECT * FROM chq_cheques WHERE id=?", (int(a["id"]),))
    if not x:
        raise ApiError("Cheque not found.")
    st = a.get("status")
    if st not in CH_STATUS[x["direction"]]:
        raise ApiError("Unknown status for this cheque.")
    h = json.loads(x["history"] or "[]")
    h.append([a.get("date") or today(), st, u["id"], a.get("note")])
    upd(c, "chq_cheques", x["id"], {"status": st, "status_date": a.get("date") or today(), "history": json.dumps(h),
                                    "payment_id": int(a["payment_id"]) if a.get("payment_id") else x["payment_id"]})
    audit(c, u, "status", "chq_cheques", x["id"], {"status": st})
    return {"ok": True}


@api("chq.print", "accounts", "view")
def chq_print(c, u, a):
    x = q1(c, "SELECT x.*, pa.name party FROM chq_cheques x LEFT JOIN parties pa ON pa.id=x.party_id WHERE x.id=?", (int(a["id"]),))
    if not x:
        raise ApiError("Cheque not found.")
    import api_tally as T
    return {"payee": x["payee"] or x["party"], "date": x["cheque_date"], "amount": x["amount"], "words": T.amount_words(x["amount"], "en"),
            "words_ne": T.amount_words(x["amount"], "ne"), "cheque_no": x["cheque_no"]}


# ───────────────────────── A8: approval limits ─────────────────────────
def _limit_for(c, doc, user):
    rows = q(c, "SELECT * FROM ap_limits WHERE doc=? AND active=1", (doc,))
    if not rows:
        return None, None, False
    mine = [r for r in rows if r["user_id"] == user["id"]] or [r for r in rows if r["role"] and r["role"] == user.get("role")]
    t = today()
    stand = [r for r in rows if r["standin_user_id"] == user["id"] and (not r["standin_from"] or r["standin_from"] <= t) and (not r["standin_to"] or r["standin_to"] >= t)]
    best = max(mine + stand, key=lambda r: _f(r["max_amount"]), default=None)
    behalf = best["user_id"] if best and best in stand and best not in mine else None
    return best, behalf, True


def check_limit(c, u, doc, amount, doc_id=None):
    if setting(c, "ap_on") != "1" or u.get("role") == "admin":
        return
    best, behalf, any_rule = _limit_for(c, doc, u)
    if not any_rule:
        return
    if not best:
        raise ApiError("No approval limit is set for you on %ss. Ask the administrator (Accounts › Approval limits)." % DLABEL[doc].lower())
    if amount > _f(best["max_amount"]) + 0.005:
        raise ApiError("This %s is %s; your approval limit is %s. Someone with a higher limit must approve it." % (DLABEL[doc].lower(), "{:,.2f}".format(amount), "{:,.2f}".format(_f(best["max_amount"]))))
    ins(c, "ap_log", {"doc": doc, "doc_id": doc_id, "amount": r2(amount), "user_id": u["id"], "on_behalf": behalf, "ts": now()})


def _amt_bill(c, iid):
    return _f(val(c, "SELECT SUM(amount + amount*COALESCE(vat_rate,0)/100) FROM invoice_lines WHERE invoice_id=?", (iid,)))


def _w_limit(doc, amount_fn):
    def factory(orig):
        def fn(c, u, a):
            try:
                amt, did = amount_fn(c, a)
            except ApiError:
                raise
            except Exception:
                amt, did = None, None
            if amt is not None:
                check_limit(c, u, doc, amt, did)
            return orig(c, u, a)
        return fn
    return factory


def _amt_payment(c, a):
    if a.get("kind") != "pay":
        return None, None
    return sum(_f(x.get("amount")) for x in (a.get("allocations") or [])) + _f(a.get("advance")), None


def _amt_invoice(c, a):
    k = val(c, "SELECT kind FROM invoices WHERE id=?", (int(a["id"]),))
    return (_amt_bill(c, int(a["id"])), int(a["id"])) if k == "purchase" else (None, None)


@api("ap.list", "accounts", "view")
def ap_list(c, u, a):
    rows = q(c, "SELECT l.*, us.name user, sb.name standin FROM ap_limits l LEFT JOIN users us ON us.id=l.user_id LEFT JOIN users sb ON sb.id=l.standin_user_id ORDER BY l.doc, l.max_amount DESC")
    users = q(c, "SELECT id, name, username, role FROM users WHERE COALESCE(active,1)=1 ORDER BY name")
    log = q(c, "SELECT g.*, us.name user, ob.name behalf FROM ap_log g LEFT JOIN users us ON us.id=g.user_id LEFT JOIN users ob ON ob.id=g.on_behalf ORDER BY g.id DESC LIMIT 100")
    roles = sorted({x["role"] for x in users if x["role"]})
    return {"rows": rows, "users": users, "roles": roles, "docs": [{"key": k, "label": l} for k, l in DOCS], "on": setting(c, "ap_on") == "1", "log": log}


@api("ap.save", "admin", "edit")
def ap_save(c, u, a):
    if a.get("doc") not in DLABEL:
        raise ApiError("Choose the document.")
    if not a.get("user_id") and not a.get("role"):
        raise ApiError("Choose a user or a job.")
    row = {"doc": a["doc"], "user_id": int(a["user_id"]) if a.get("user_id") else None, "role": a.get("role") or None, "max_amount": _f(a.get("max_amount")),
           "standin_user_id": int(a["standin_user_id"]) if a.get("standin_user_id") else None, "standin_from": a.get("standin_from") or None,
           "standin_to": a.get("standin_to") or None, "active": 0 if a.get("active") in (0, "0") else 1, "note": a.get("note"), "ts": now()}
    if a.get("id"):
        upd(c, "ap_limits", int(a["id"]), row)
        rid = int(a["id"])
    else:
        rid = ins(c, "ap_limits", row)
    audit(c, u, "save", "ap_limits", rid, row)
    return {"id": rid}


@api("ap.switch", "admin", "edit")
def ap_switch(c, u, a):
    _set(c, "ap_on", "1" if a.get("on") in (1, "1", True) else "0")
    audit(c, u, "settings", "ap_on", None, {"on": setting(c, "ap_on")})
    return {"on": setting(c, "ap_on") == "1"}


# ───────────────────────── A11: VAT and TDS files ─────────────────────────
@api("st.vat_return", "accounts", "view")
def st_vat_return(c, u, a):
    frm, to = a.get("from") or (today()[:8] + "01"), a.get("to") or today()
    out = {}
    for kind in ("sales", "purchase"):
        rows = _call(c, u, "rep.vat", {"kind": kind, "from": frm, "to": to})
        out[kind] = {"count": len(rows), "taxable": r2(sum(_f(r["taxable"]) for r in rows)), "exempt": r2(sum(_f(r["exempt"]) for r in rows)),
                     "vat": r2(sum(_f(r["vat"]) for r in rows)),
                     "lines": [{"date": r["date"], "no": r["no"], "party_inv_no": r.get("party_inv_no"), "party": r["party_name"], "pan": r["pan"],
                                "taxable": r2(r["taxable"]), "exempt": r2(r["exempt"]), "vat": r2(r["vat"]), "total": r2(r["total"])} for r in rows]}
    payable = r2(out["sales"]["vat"] - out["purchase"]["vat"])
    return {"from": frm, "to": to, "sales": out["sales"], "purchase": out["purchase"], "payable": payable if payable > 0 else 0, "credit": -payable if payable < 0 else 0}


@api("st.tds_return", "accounts", "view")
def st_tds_return(c, u, a):
    frm, to = a.get("from") or (today()[:8] + "01"), a.get("to") or today()
    d = _call(c, u, "rep.tds", {"from": frm, "to": to})
    by = {}
    missing = 0
    for r in d["deducted"]:
        key = (r["pan"] or "", r["party_name"], r["section"] or "")
        x = by.setdefault(key, {"pan": r["pan"], "name": r["party_name"], "section": r["section"], "rate": r["rate"], "payments": 0, "amount": 0.0, "tds": 0.0})
        x["payments"] += 1
        x["amount"] += _f(r["gross"])
        x["tds"] += _f(r["tds"])
        if not r["pan"]:
            missing += 1
    rows = [dict(x, amount=r2(x["amount"]), tds=r2(x["tds"])) for x in by.values()]
    return {"from": frm, "to": to, "rows": sorted(rows, key=lambda r: r["name"] or ""), "lines": d["deducted"], "total_tds": d["total_deducted"],
            "deposited": d["total_deposited"], "not_deposited": r2(d["total_deducted"] - d["total_deposited"]), "missing_pan": missing}


@api("st.csv", "accounts", "view")
def st_csv(c, u, a):
    kind = a.get("kind")
    buf = io.StringIO()
    w = csv.writer(buf)
    if kind in ("sales", "purchase"):
        d = st_vat_return(c, u, a)[kind]
        w.writerow(["Date", "Invoice no", "Party invoice no", "Party", "PAN", "Taxable amount", "Exempt amount", "VAT", "Total"])
        for r in d["lines"]:
            w.writerow([r["date"], r["no"], r["party_inv_no"] or "", r["party"], r["pan"] or "", r["taxable"], r["exempt"], r["vat"], r["total"]])
    elif kind == "tds":
        d = st_tds_return(c, u, a)
        w.writerow(["PAN", "Name", "TDS head / section", "Rate %", "Payments", "Amount paid", "TDS"])
        for r in d["rows"]:
            w.writerow([r["pan"] or "", r["name"], r["section"] or "", r["rate"] or "", r["payments"], r["amount"], r["tds"]])
    else:
        raise ApiError("Unknown file.")
    return {"name": "%s_%s_%s.csv" % (kind, a.get("from") or "", a.get("to") or today()), "text": buf.getvalue()}


# ───────────────────────── A12: year-end checklist ─────────────────────────
@api("ye.check", "accounts", "view")
def ye_check(c, u, a):
    import api_corp as CO
    fl = CO.fy_list(c, u, {})
    years = fl["years"]
    fy = a.get("fy") or next((y["fy"] for y in reversed(years) if y["end_date"] < today() and not y["closed"]), None) or fl.get("current") or (years[-1]["fy"] if years else None)
    if not fy:
        raise ApiError("No fiscal year set up.")
    y = next(x for x in years if x["fy"] == fy)
    s, e = y["start_date"], y["end_date"]
    items = []

    def add(key, label, ok, detail, route):
        items.append({"key": key, "label": label, "ok": ok, "detail": detail, "route": route})
    warn = CO._year_checks(c, s, e)
    add("drafts", "No drafts or unapproved DPRs left in the year", not warn, "; ".join(warn) or "None", "#/acc/vouchers")
    per = q(c, "SELECT code, status FROM fiscal_periods WHERE fy=? ORDER BY start_date", (fy,))
    open_ = [p["code"] for p in per if p["status"] != "locked"]
    add("periods", "Every month of the year locked", not open_ and bool(per), ("Open: " + ", ".join(open_)) if open_ else "All locked", "#/acc/periods")
    banks = q(c, "SELECT id, name FROM accounts WHERE role='bank' AND COALESCE(active,1)=1")
    unrec = []
    for b in banks:
        n = val(c, "SELECT COUNT(*) FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id WHERE l.account_id=? AND " + POSTED + " AND v.date<=? AND l.cleared_date IS NULL", (b["id"], e))
        if n:
            unrec.append("%s: %d entries not cleared" % (b["name"], n))
    add("bank", "Bank reconciled to the year end", not unrec, "; ".join(unrec[:5]) or "All cleared", "#/acc/bank")
    months = []
    m0 = date.fromisoformat(s[:8] + "01")
    while m0.isoformat() <= e:
        months.append(m0.isoformat()[:7])
        m0 = (m0.replace(day=28) + timedelta(days=4)).replace(day=1)
    owned = q(c, "SELECT id, code, purchase_date FROM equipment WHERE COALESCE(ownership,'owned') NOT IN ('hired','rented','rental') AND COALESCE(active,1)=1")
    miss = []
    for eq in owned:
        first = val(c, "SELECT MIN(month) FROM dep_runs WHERE equipment_id=?", (eq["id"],))
        for m in months:
            if eq["purchase_date"] and eq["purchase_date"][:7] > m:
                continue
            if (first and m < first) or (m == s[:7] and s[8:] > "15"):
                continue
            if m >= today()[:7]:
                continue
            if not val(c, "SELECT COUNT(*) FROM dep_runs WHERE equipment_id=? AND month=?", (eq["id"], m)):
                miss.append("%s %s" % (eq["code"], m))
    add("depreciation", "Depreciation run for every machine and month", not miss, ("%d missing, e.g. %s" % (len(miss), ", ".join(miss[:4]))) if miss else "Complete", "#/fa/dep")
    open_bills = q(c, "SELECT i.kind, COUNT(*) n, SUM(i.payable - COALESCE((SELECT SUM(al.amount) FROM allocations al WHERE al.invoice_id=i.id AND al.active=1 AND al.date<=?),0)) due "
                      "FROM invoices i WHERE i.status='posted' AND i.date<=? GROUP BY i.kind", (e, e))
    txt = "; ".join("%s: %d bills, %s open" % (r["kind"], r["n"], "{:,.0f}".format(_f(r["due"]))) for r in open_bills)
    add("bills", "Open bills carried forward bill by bill", True, (txt or "No bills") + " (they stay open in the new year with their own dates)", "#/acc/ageing")
    closed = y.get("closed")
    if closed:
        fz = _f(val(c, "SELECT SUM(value) FROM fy_stock WHERE fy=?", (fy,)))
        led = _f(val(c, "SELECT SUM(value_in-value_out) FROM stock_ledger WHERE date<=?", (e,)))
        add("stock", "Stock frozen at the close agrees with the stock ledger", abs(fz - led) < 1, "Frozen %s, ledger %s" % ("{:,.2f}".format(fz), "{:,.2f}".format(led)), "#/inv/stock")
    else:
        add("stock", "Stock frozen at the close agrees with the stock ledger", None, "The year is not closed yet (Fiscal years › Close)", "#/acc/fy")
    ret = q(c, "SELECT pa.name, ac.role, SUM(l.debit-l.credit) bal FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id JOIN accounts ac ON ac.id=l.account_id "
               "LEFT JOIN parties pa ON pa.id=l.party_id WHERE ac.role IN ('retention_payable','retention_receivable') AND " + POSTED + " AND v.date<=? GROUP BY l.party_id, ac.role "
               "HAVING ABS(SUM(l.debit-l.credit))>0.5", (e,))
    add("retention", "Retention carried forward per party", True, "; ".join("%s %s %s" % (r["name"] or "(no party)", "held by client" if r["role"] == "retention_receivable" else "we hold",
                                                                                         "{:,.0f}".format(abs(r["bal"]))) for r in ret[:6]) or "None open", "#/sb/control")
    tds = _call(c, u, "rep.tds", {"from": s, "to": e})
    gap = r2(tds["total_deducted"] - tds["total_deposited"])
    add("tds", "TDS deducted in the year deposited", gap <= 0.5, "Deducted %s, deposited %s" % ("{:,.0f}".format(tds["total_deducted"]), "{:,.0f}".format(tds["total_deposited"])), "#/st/files")
    add("closed", "Year closed (Fiscal years › Close)", bool(closed), "Closed" if closed else "Not closed", "#/acc/fy")
    return {"fy": fy, "start": s, "end": e, "years": [x["fy"] for x in years], "items": items, "ready": all(i["ok"] is not False for i in items if i["key"] != "closed")}


# ───────────────────────── L3: Tally XML ─────────────────────────
VT = {"journal": "Journal", "payment": "Payment", "receipt": "Receipt", "sales": "Sales", "purchase": "Purchase", "contra": "Contra"}


def _tally_date(d):
    return d.replace("-", "")


def _group_of(c, acc_id):
    r = q1(c, "SELECT g.name FROM tl_amap m JOIN tl_groups g ON g.id=m.tl_group_id WHERE m.account_id=?", (acc_id,)) if _has(c, "tl_amap") else None
    if r:
        return r["name"]
    t = val(c, "SELECT type FROM accounts WHERE id=?", (acc_id,))
    return {"asset": "Current Assets", "liability": "Current Liabilities", "equity": "Capital Account", "income": "Indirect Incomes", "expense": "Indirect Expenses"}.get(t, "Suspense A/c")


PARTY_ROLES = ("ap_control", "ar_control", "payable", "receivable", "sundry_creditors", "sundry_debtors", "trade_payable", "trade_receivable")


def _party_ledger(c, l):
    if not l["party_id"]:
        return None
    acc = q1(c, "SELECT role, type FROM accounts WHERE id=?", (l["account_id"],))
    if not acc or not ((acc["role"] or "") in PARTY_ROLES or "creditor" in (acc["role"] or "") or "debtor" in (acc["role"] or "")):
        return None
    p = q1(c, "SELECT name, kind FROM parties WHERE id=?", (l["party_id"],))
    return (p["name"], "Sundry Debtors" if p["kind"] == "client" else "Sundry Creditors") if p else None


@api("tx.export", "accounts", "view")
def tx_export(c, u, a):
    frm, to = a.get("from") or (today()[:8] + "01"), a.get("to") or today()
    company = setting(c, "company_name") or "BuildCore"
    ledgers = {}
    for acc in q(c, "SELECT * FROM accounts ORDER BY code"):
        ledgers[acc["name"]] = (_group_of(c, acc["id"]), acc["opening_balance"] or 0)
    vouchers = []
    for v in q(c, "SELECT * FROM vouchers v WHERE " + POSTED + " AND v.date BETWEEN ? AND ? ORDER BY v.date, v.id", (frm, to)):
        lines = []
        for l in q(c, "SELECT l.*, ac.name aname FROM voucher_lines l JOIN accounts ac ON ac.id=l.account_id WHERE l.voucher_id=? ORDER BY l.id", (v["id"],)):
            pl = _party_ledger(c, l)
            name = pl[0] if pl else l["aname"]
            if pl and name not in ledgers:
                ledgers[name] = (pl[1], 0)
            lines.append((name, r2(l["debit"]), r2(l["credit"])))
        vouchers.append((v, lines))
    x = ['<?xml version="1.0" encoding="UTF-8"?>', "<ENVELOPE>", "<HEADER><TALLYREQUEST>Import Data</TALLYREQUEST></HEADER>", "<BODY><IMPORTDATA>",
         "<REQUESTDESC><REPORTNAME>All Masters</REPORTNAME><STATICVARIABLES><SVCURRENTCOMPANY>%s</SVCURRENTCOMPANY></STATICVARIABLES></REQUESTDESC>" % escape(company), "<REQUESTDATA>"]
    for name, (grp, ob) in sorted(ledgers.items()):
        x.append('<TALLYMESSAGE xmlns:UDF="TallyUDF"><LEDGER NAME="%s" ACTION="Create"><NAME.LIST><NAME>%s</NAME></NAME.LIST><PARENT>%s</PARENT>'
                 "<OPENINGBALANCE>%s</OPENINGBALANCE></LEDGER></TALLYMESSAGE>" % (escape(name, {'"': "&quot;"}), escape(name), escape(grp), r2(-ob)))
    x.append("</REQUESTDATA></IMPORTDATA></BODY></ENVELOPE>")
    masters = "\n".join(x)
    y = ['<?xml version="1.0" encoding="UTF-8"?>', "<ENVELOPE>", "<HEADER><TALLYREQUEST>Import Data</TALLYREQUEST></HEADER>", "<BODY><IMPORTDATA>",
         "<REQUESTDESC><REPORTNAME>Vouchers</REPORTNAME><STATICVARIABLES><SVCURRENTCOMPANY>%s</SVCURRENTCOMPANY></STATICVARIABLES></REQUESTDESC>" % escape(company), "<REQUESTDATA>"]
    for v, lines in vouchers:
        vt = VT.get(v["type"], "Journal")
        y.append('<TALLYMESSAGE xmlns:UDF="TallyUDF"><VOUCHER VCHTYPE="%s" ACTION="Create"><DATE>%s</DATE><VOUCHERTYPENAME>%s</VOUCHERTYPENAME>'
                 "<VOUCHERNUMBER>%s</VOUCHERNUMBER><NARRATION>%s</NARRATION>" % (vt, _tally_date(v["date"]), vt, escape(v["no"] or str(v["id"])), escape(v["narration"] or "")))
        for name, dr, cr in lines:
            amt = -dr if dr else cr
            y.append("<ALLLEDGERENTRIES.LIST><LEDGERNAME>%s</LEDGERNAME><ISDEEMEDPOSITIVE>%s</ISDEEMEDPOSITIVE><AMOUNT>%s</AMOUNT></ALLLEDGERENTRIES.LIST>"
                     % (escape(name), "Yes" if dr else "No", "%.2f" % amt))
        y.append("</VOUCHER></TALLYMESSAGE>")
    y.append("</REQUESTDATA></IMPORTDATA></BODY></ENVELOPE>")
    return {"masters": masters, "vouchers": "\n".join(y), "ledgers": len(ledgers), "count": len(vouchers), "from": frm, "to": to}


def _parse_tally(text):
    text = re.sub(r"&#([0-9]+);", lambda m: "" if int(m.group(1)) < 32 and m.group(1) not in ("9", "10", "13") else m.group(0), text or "")
    try:
        root = ET.fromstring(text.encode("utf-8"))
    except ET.ParseError as e:
        raise ApiError("This is not a Tally XML file I can read: %s" % e)
    out = []
    for v in root.iter("VOUCHER"):
        g = lambda t: (v.findtext(t) or "").strip()
        lines = []
        for tag in ("ALLLEDGERENTRIES.LIST", "LEDGERENTRIES.LIST"):
            for le in v.findall(tag):
                name = (le.findtext("LEDGERNAME") or "").strip()
                amt = _f((le.findtext("AMOUNT") or "0").replace(",", ""))
                if name and abs(amt) > 0.004:
                    lines.append({"ledger": name, "debit": r2(-amt) if amt < 0 else 0, "credit": r2(amt) if amt > 0 else 0})
        d = g("DATE")
        out.append({"date": "%s-%s-%s" % (d[:4], d[4:6], d[6:8]) if len(d) == 8 else d, "type": g("VOUCHERTYPENAME") or v.get("VCHTYPE") or "Journal",
                    "no": g("VOUCHERNUMBER"), "narration": g("NARRATION"), "lines": lines})
    return out


def _match_ledger(c, name):
    n = name.strip().lower()
    a = q1(c, "SELECT id FROM accounts WHERE LOWER(TRIM(name))=? AND COALESCE(active,1)=1", (n,))
    if a:
        return {"account_id": a["id"]}
    p = q1(c, "SELECT id, kind FROM parties WHERE LOWER(TRIM(name))=?", (n,))
    if p:
        role = "ar_control" if p["kind"] == "client" else "ap_control"
        acc = q1(c, "SELECT id FROM accounts WHERE role=?", (role,)) or q1(c, "SELECT id FROM accounts WHERE role=?", ("receivable" if p["kind"] == "client" else "payable",))
        if acc:
            return {"account_id": acc["id"], "party_id": p["id"]}
    return None


STORE_ROLES = ("inventory", "inventory_fuel", "inventory_spares", "grni")


@api("tx.preview", "accounts", "view")
def tx_preview(c, u, a):
    vs = _parse_tally(a.get("text"))
    unmatched = {}
    ok = 0
    for v in vs:
        v["ready"] = bool(v["lines"]) and abs(sum(l["debit"] for l in v["lines"]) - sum(l["credit"] for l in v["lines"])) < 0.01
        for l in v["lines"]:
            m = _match_ledger(c, l["ledger"])
            l["match"] = m
            if not m:
                unmatched[l["ledger"]] = unmatched.get(l["ledger"], 0) + 1
                v["ready"] = False
            elif val(c, "SELECT role FROM accounts WHERE id=?", (m["account_id"],)) in STORE_ROLES:
                v["ready"] = False
                v["why"] = "%s is kept by store documents (GRN, issue, stock count)" % l["ledger"]
        if not v["ready"] and not v.get("why"):
            v["why"] = "ledger not found" if any(not l["match"] for l in v["lines"]) else "debits and credits differ"
        ok += v["ready"]
    return {"vouchers": vs if a.get("_all") else vs[:300], "count": len(vs), "ready": ok, "unmatched": [{"ledger": k, "uses": n} for k, n in sorted(unmatched.items(), key=lambda x: -x[1])]}


@api("tx.import", "accounts", "edit")
def tx_import(c, u, a):
    d = tx_preview(c, u, dict(a, _all=1))
    made = 0
    for v in d["vouchers"]:
        if not v["ready"]:
            continue
        lines = [dict(l["match"], debit=l["debit"], credit=l["credit"], narration=l["ledger"]) for l in v["lines"]]
        c.execute("SAVEPOINT tx1")
        try:
            _call(c, u, "voucher.save", {"header": {"date": v["date"], "type": "journal", "narration": ("Tally %s %s: %s" % (v["type"], v["no"], v["narration"])).strip()[:400],
                                                "ref_no": v["no"]}, "lines": lines})
        except ApiError:
            c.execute("ROLLBACK TO tx1")
            c.execute("RELEASE tx1")
            continue
        c.execute("RELEASE tx1")
        made += 1
    audit(c, u, "import", "vouchers", None, {"tally_drafts": made})
    return {"made": made, "skipped": d["count"] - made}


# ───────────────────────── B1: alternate units ─────────────────────────
@api("au.list", "inventory", "view")
def au_list(c, u, a):
    rows = q(c, "SELECT x.*, m.code, m.name material, m.unit base FROM mat_units x JOIN materials m ON m.id=x.material_id ORDER BY m.name, x.unit")
    return {"rows": rows}


@api("au.save", "inventory", "edit")
def au_save(c, u, a):
    if not a.get("material_id") or not (a.get("unit") or "").strip() or _f(a.get("factor")) <= 0:
        raise ApiError("Material, unit and how many base units it holds are needed.")
    m = q1(c, "SELECT unit FROM materials WHERE id=?", (int(a["material_id"]),))
    if (a["unit"].strip().lower() == (m["unit"] or "").lower()):
        raise ApiError("That is already the material's own unit.")
    if a.get("delete"):
        c.execute("DELETE FROM mat_units WHERE material_id=? AND LOWER(unit)=?", (int(a["material_id"]), a["unit"].strip().lower()))
        return {"ok": True}
    c.execute("INSERT INTO mat_units(material_id, unit, factor, note) VALUES(?,?,?,?) ON CONFLICT(material_id, unit) DO UPDATE SET factor=excluded.factor, note=excluded.note",
              (int(a["material_id"]), a["unit"].strip(), _f(a["factor"]), a.get("note")))
    audit(c, u, "save", "mat_units", int(a["material_id"]), {"unit": a["unit"], "factor": a["factor"]})
    return {"ok": True}


def factor(c, mid, unit):
    if not unit:
        return 1.0
    m = q1(c, "SELECT unit FROM materials WHERE id=?", (mid,))
    if m and (m["unit"] or "").lower() == unit.strip().lower():
        return 1.0
    r = q1(c, "SELECT factor FROM mat_units WHERE material_id=? AND LOWER(unit)=?", (mid, unit.strip().lower()))
    if not r:
        raise ApiError("No unit '%s' for this material. Add it under Store › Alternate units." % unit)
    return _f(r["factor"])


QTY = {"grn": ("received_qty", "accepted_qty"), "issue": ("qty",), "return": ("qty",), "transfer": ("qty",), "mrq": ("qty",), "po": ("qty",), "pr": ("qty",)}


def _w_doc(orig):
    def doc_save(c, u, a):
        t = a.get("type")
        if t in QTY and any(l.get("alt_unit") for l in a.get("lines") or []):
            lines = []
            for l in a.get("lines") or []:
                l = dict(l)
                if l.get("alt_unit") and l.get("material_id"):
                    f = factor(c, int(l["material_id"]), l["alt_unit"])
                    for k in QTY[t]:
                        src = l.get("alt_" + k, l.get("alt_qty"))
                        if src not in (None, ""):
                            l[k] = round(_f(src) * f, 4)
                    if l.get("alt_rate") not in (None, ""):
                        l["rate"] = round(_f(l["alt_rate"]) / f, 4)
                    note = "%s %s" % (l.get("alt_qty") or l.get("alt_" + QTY[t][0]), l["alt_unit"])
                    l["remarks"] = ((l.get("remarks") or "") + " (entered as %s)" % note).strip()
                lines.append(l)
            a = dict(a, lines=lines)
        return orig(c, u, a)
    return doc_save


@api("au.stock", "inventory", "view")
def au_stock(c, u, a):
    cond, p = "", []
    if a.get("project_id"):
        cond, p = " AND b.project_id=?", [int(a["project_id"])]
    rows = q(c, "SELECT b.material_id, m.code, m.name, m.unit, SUM(b.qty) qty FROM stock_balances b JOIN materials m ON m.id=b.material_id WHERE b.material_id IN "
                "(SELECT material_id FROM mat_units)" + cond + " GROUP BY b.material_id HAVING ABS(SUM(b.qty))>0.0001 ORDER BY m.name", p)
    for r in rows:
        r["other"] = [{"unit": x["unit"], "qty": round(_f(r["qty"]) / _f(x["factor"]), 3)} for x in q(c, "SELECT unit, factor FROM mat_units WHERE material_id=?", (r["material_id"],)) if _f(x["factor"]) > 0]
    return {"rows": rows}


# ───────────────────────── alerts ─────────────────────────
NEW_KINDS = [("pdc_due", "Post-dated cheque due", "cash", "medium", 3, "days ahead", "accountant,finance_manager", 2, 3)]
NEW_ACTIONS = {"pdc_due": "Deposit the cheque received, or keep the money in the bank for the cheque given; update its status in Accounts › Cheques."}


def chk_pdc(c, R, ctx):
    import api_fcc as F
    out = []
    lim = (date.fromisoformat(ctx["today"]) + timedelta(days=int(R["pdc_due"]["threshold"] or 3))).isoformat()
    for x in q(c, "SELECT x.*, pa.name party FROM chq_cheques x LEFT JOIN parties pa ON pa.id=x.party_id WHERE x.status IN ('held','issued') AND x.cheque_date<=?", (lim,)):
        what = "received from" if x["direction"] == "received" else "given to"
        out.append({"fkey": "pdc:%d" % x["id"], "kind": "pdc_due", "project_id": x["project_id"],
                    "title": "Cheque %s %s %s for %s dated %s" % (x["cheque_no"], what, x["party"] or x["payee"] or "", "{:,.0f}".format(_f(x["amount"])), x["cheque_date"]),
                    "amount": x["amount"], "due_date": x["cheque_date"], "severity": "high" if x["cheque_date"] < ctx["today"] else "medium",
                    "basis": "Cheque register.", "detail": "", "sources": [F.src("cheque", x["cheque_no"], "#/st/cheques", x["id"], x["project_id"])]})
    return out


def _connect():
    import api_fcc as F
    for k in NEW_KINDS:
        if k[0] not in F.KIND:
            F.KINDS.append(k)
            F.KIND[k[0]] = k
    for k, v in NEW_ACTIONS.items():
        F.ACTIONS.setdefault(k, v)
    if "pdc_due" not in {x[0] for x in F.CHECKS}:
        F.CHECKS.append(("pdc_due", chk_pdc))


def _wrap(name, factory):
    cur = inv.FUNCS.get(name)
    if not cur or getattr(cur[0], FLAG, False):
        return
    w = factory(cur[0])
    for f in [x for x in dir(cur[0]) if x.startswith("_bco")]:
        setattr(w, f, getattr(cur[0], f))
    setattr(w, FLAG, True)
    w._orig = cur[0]
    inv.FUNCS[name] = (w, cur[1], cur[2], cur[3])


def init_group(c):
    c.executescript(SCHEMA)
    used = val(c, "SELECT COUNT(*) FROM vouchers")
    if not q1(c, "SELECT 1 FROM settings WHERE key='ap_on'"):
        _set(c, "ap_on", "0")
    if _has(c, "fcc_rules"):
        for k in NEW_KINDS:
            if not q1(c, "SELECT kind FROM fcc_rules WHERE kind=?", (k[0],)):
                c.execute("INSERT INTO fcc_rules(kind, enabled, threshold, owner_role, target_days, escalate_days) VALUES(?,?,?,?,?,?)",
                          (k[0], 0 if used else 1, k[4], k[6], k[7], k[8]))
    c.commit()
    try:
        _connect()
    except Exception:
        pass
    _wrap("po.approve", _w_limit("po", lambda c, a: (_f(val(c, "SELECT total FROM po WHERE id=?", (int(a["id"]),))), int(a["id"]))))
    _wrap("invoice.post", _w_limit("bill", _amt_invoice))
    _wrap("payment.create", _w_limit("payment", _amt_payment))
    _wrap("voucher.post", _w_limit("voucher", lambda c, a: (_f(val(c, "SELECT SUM(debit) FROM voucher_lines WHERE voucher_id=?", (int(a["id"]),))), int(a["id"]))))
    _wrap("sco.bill_approve", _w_limit("subbill", lambda c, a: (_f(val(c, "SELECT gross FROM sc_bills WHERE id=?", (int(a["id"]),))), int(a["id"]))))
    _wrap("doc.save", _w_doc)
    try:
        import api_safe
        if "ap_on" not in {s[0] for s in getattr(api_safe, "SWITCHES", [])}:
            api_safe.SWITCHES.append(("ap_on", "Approval limits by amount (2.61)", "Users with a limit may approve purchase orders, bills, payments, vouchers and subcontract bills only up to it.",
                                      lambda v: v == "1", "#/st/limits", "admin", 15))
    except Exception:
        pass
