"""BuildCore 2.45.0 — Match site receipts, VAT bills and payments.

Asked by SULAV: material reaches site and the store receives it, but the vendor's VAT bill names another item, or
shows a lower price for the real item and puts the rest under some other item (sand at 1,000 + VAT billed as sand at
800 + VAT and 200 of "other item"), or is smaller than what was paid (part paid without a VAT bill). Store at site and
accounts in Kathmandu both enter, and the two never agree.

Three truths, each entered by the person who knows it, and never changed by the other:
  * What arrived at site: the store's GRN. Stock and project cost come only from here.
  * What the vendor billed: the bill, typed exactly as printed. Input VAT and the VAT register come only from here.
  * What was paid: payments (an amount paid before any bill is an advance, shown as "paid, no VAT bill yet").

New, all behind the company switch mt_on (Procurement › Purchase bills › Match settings). Updated companies start
with it off; new companies start with it on.
  1. Bill-to-goods mapping (mt_map). Each printed line of a draft purchase bill can be linked to one or more GRN lines
     with a quantity and an amount. A line of a different item (the "other item" 200) can be linked to the sand GRN
     with quantity 0 and its amount. When the bill is posted, BuildCore posts it against the GRN lines (one voucher,
     the usual Dr GRN clearing / VAT input, Cr vendor) and then puts the printed lines back exactly as typed, so the
     bill, its VAT and the VAT register stay as printed while stock and cost stay as received. A different-item link
     needs a reason and, above the approval limit, approval by someone with Procurement approve.
  2. Purchase without VAT bill (mt_novat). For goods received with no bill at all: a zero-VAT purchase bill against
     the GRN lines, with a reason and approval, optionally set against the cash already paid as advance. It clears
     GRN clearing and the vendor, and it is left out of the VAT purchase register.
  3. Match screen per vendor: goods received not billed, bills waiting for goods, paid with no VAT bill yet (open
     advance), payable on bills, no-VAT purchases and different-item links, each opening its documents.
  4. Bill vs actual: every mapped bill line (printed item, amount) beside what really came (GRN item, quantity).
  5. Reclassify a posted bill line (mt_reclass): for bills posted before 2.45 the "other item" amount sits in an
     expense account; with approval, a journal moves it to the right cost account (e.g. Purchase Price Variance, where
     the sand rate difference went) without touching the bill or its VAT.
  6. Financial data checks: goods received and not billed for more than 30 days; links waiting for approval.
Nothing already posted is changed; core tables are not altered; only new mt_* tables and settings are added.
"""
import json

import core
from core import ApiError, q, q1, val, r2, r4, today, now, setting, ins, upd, get
import api_inventory as inv
from api_inventory import api

VERSION = "2.45.0"
FLAG = "_bco245"
EPS = 0.005
POSTED = "v.status IN ('posted','reversed')"

SCHEMA = """
CREATE TABLE IF NOT EXISTS mt_map(id INTEGER PRIMARY KEY, invoice_id INTEGER, invoice_line_id INTEGER, grn_line_id INTEGER,
  qty REAL DEFAULT 0, amount REAL DEFAULT 0, different INTEGER DEFAULT 0, reason TEXT, status TEXT DEFAULT 'saved',
  created_by INTEGER, created_at TEXT, approved_by INTEGER, approved_at TEXT);
CREATE INDEX IF NOT EXISTS ix_mt_map_inv ON mt_map(invoice_id);
CREATE INDEX IF NOT EXISTS ix_mt_map_grn ON mt_map(grn_line_id);
CREATE TABLE IF NOT EXISTS mt_post(id INTEGER PRIMARY KEY, invoice_id INTEGER, grn_line_id INTEGER, qty REAL, amount REAL,
  vat_rate REAL, status TEXT DEFAULT 'posted', ts TEXT);
CREATE INDEX IF NOT EXISTS ix_mt_post_inv ON mt_post(invoice_id);
CREATE TABLE IF NOT EXISTS mt_print(invoice_id INTEGER PRIMARY KEY, lines TEXT, ts TEXT);
CREATE TABLE IF NOT EXISTS mt_novat(invoice_id INTEGER PRIMARY KEY, party_id INTEGER, amount REAL, reason TEXT, ref TEXT,
  adjust_advance INTEGER DEFAULT 1, status TEXT DEFAULT 'waiting', created_by INTEGER, created_at TEXT, approved_by INTEGER,
  approved_at TEXT);
CREATE TABLE IF NOT EXISTS mt_reclass(id INTEGER PRIMARY KEY, invoice_id INTEGER, from_account_id INTEGER, to_account_id INTEGER,
  amount REAL, reason TEXT, boq_item_id INTEGER, voucher_id INTEGER, status TEXT DEFAULT 'posted', created_by INTEGER, ts TEXT);
CREATE TABLE IF NOT EXISTS mt_log(id INTEGER PRIMARY KEY, ts TEXT, user_id INTEGER, action TEXT, ref TEXT, detail TEXT);
"""


def _f(x, d=0.0):
    try:
        return float(x) if x not in (None, "") else d
    except (TypeError, ValueError):
        return d


def _set(c, k, v):
    c.execute("INSERT INTO settings(key, value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (k, str(v)))


def on(c):
    return setting(c, "mt_on") == "1"


def need_on(c):
    if not on(c):
        raise ApiError("Matching of receipts, bills and payments is off for this company. Turn it on in "
                       "Procurement › Purchase bills › Match settings.")


def _log(c, u, action, ref, detail=None):
    ins(c, "mt_log", {"ts": now(), "user_id": u["id"] if u else None, "action": action, "ref": str(ref),
                      "detail": json.dumps(detail, default=str) if detail is not None else None})


def _limit(c):
    return _f(setting(c, "mt_approve_over"), 0.0)


def _can_approve(c, u, maker_id):
    if not core.can(u, "procurement", "approve"):
        raise ApiError("Approving needs Procurement approve rights.")
    if maker_id and maker_id == u["id"] and u["role"] != "admin" and setting(c, "mt_self_approve") != "1":
        raise ApiError("The person who made it cannot approve it. Ask another approver.")


def _mat_name(c, mid):
    return val(c, "SELECT name FROM materials WHERE id=?", (mid,), None) if mid else None


def _line_amount(l):
    return r2(_f(l["qty"]) * _f(l["rate"]))


def _uninvoiced(c, grn_line_id, skip_invoice=None):
    gl = q1(c, "SELECT * FROM grn_lines WHERE id=?", (grn_line_id,))
    if not gl:
        return None, 0.0
    left = _f(gl["accepted_qty"]) - _f(gl["invoiced_qty"])
    return gl, r4(left)


def _grn_line_info(c, grn_line_id):
    return q1(c, "SELECT l.*, g.no grn_no, g.date grn_date, g.vendor_id, g.project_id, g.status grn_status, "
                 "g.procurement_purpose, m.name material, m.unit FROM grn_lines l JOIN grn g ON g.id=l.grn_id "
                 "LEFT JOIN materials m ON m.id=l.material_id WHERE l.id=?", (grn_line_id,))


def _grn_mixed(c, grn_id):
    try:
        return bool(val(c, "SELECT COUNT(*) FROM proc_alloc WHERE grn_id=? AND status IN ('draft','posted')", (grn_id,)))
    except Exception:
        return False


# ───────────────────────────── settings ─────────────────────────────
@api("mt.settings", "procurement", "view")
def mt_settings(c, u, a):
    return {"on": on(c), "from": setting(c, "mt_from") or "", "approve_over": _limit(c),
            "self_approve": setting(c, "mt_self_approve") == "1", "old_days": int(_f(setting(c, "mt_old_days"), 30)),
            "can_change": core.can(u, "accounts", "approve")}


@api("mt.settings_save", "accounts", "approve")
def mt_settings_save(c, u, a):
    was = on(c)
    want = (a.get("on") in (1, True, "1", "true")) if "on" in a else was
    _set(c, "mt_on", "1" if want else "0")
    if want and not was and not a.get("from"):
        _set(c, "mt_from", today())
    if a.get("from") not in (None, ""):
        _set(c, "mt_from", str(a["from"])[:10])
    if a.get("approve_over") not in (None, ""):
        v = _f(a["approve_over"], -1)
        if v < 0:
            raise ApiError("The approval limit cannot be negative.")
        _set(c, "mt_approve_over", r2(v))
    if a.get("self_approve") is not None:
        _set(c, "mt_self_approve", "1" if a.get("self_approve") in (1, True, "1", "true") else "0")
    if a.get("old_days") not in (None, ""):
        _set(c, "mt_old_days", max(1, int(_f(a["old_days"], 30))))
    core.audit(c, u, "settings", "mt_on", 0, {"on": want})
    _log(c, u, "settings", "mt", {"on": want, "from": setting(c, "mt_from")})
    return mt_settings(c, u, {})


# ───────────────────────────── vendor figures ─────────────────────────────
def _from(c):
    return setting(c, "mt_from") or "0000-01-01"


def _received_not_billed(c, party_id=None, frm=None):
    cond, p = ["g.status='posted'", "COALESCE(l.accepted_qty,0)-COALESCE(l.invoiced_qty,0)>0.0001"], []
    if party_id:
        cond.append("g.vendor_id=?")
        p.append(int(party_id))
    if frm:
        cond.append("g.date>=?")
        p.append(frm)
    rows = q(c, "SELECT l.id grn_line_id, l.material_id, m.name material, m.unit, l.accepted_qty, l.invoiced_qty, l.rate, "
                "g.id grn_id, g.no grn_no, g.date, g.vendor_id, g.project_id, pr.code project FROM grn_lines l JOIN grn g ON g.id=l.grn_id "
                "LEFT JOIN materials m ON m.id=l.material_id LEFT JOIN projects pr ON pr.id=g.project_id WHERE " + " AND ".join(cond) +
             " ORDER BY g.date, g.id, l.id", p)
    for r in rows:
        r["unbilled_qty"] = r4(_f(r["accepted_qty"]) - _f(r["invoiced_qty"]))
        r["unbilled_value"] = r2(r["unbilled_qty"] * _f(r["rate"]))
    return rows


def _waiting_bills(c, party_id=None):
    cond, p = ["i.kind='purchase'", "i.status='draft'"], []
    if party_id:
        cond.append("i.party_id=?")
        p.append(int(party_id))
    out = []
    for i in q(c, "SELECT i.*, pa.name party FROM invoices i LEFT JOIN parties pa ON pa.id=i.party_id WHERE " + " AND ".join(cond) +
               " ORDER BY i.date, i.id", p):
        lines = q(c, "SELECT * FROM invoice_lines WHERE invoice_id=?", (i["id"],))
        sub = sum(_line_amount(l) for l in lines)
        vat = sum(r2(_line_amount(l) * _f(l["vat_rate"]) / 100) for l in lines)
        maps = q(c, "SELECT * FROM mt_map WHERE invoice_id=?", (i["id"],))
        linked = sum(1 for l in lines if l["grn_line_id"]) + len({m["invoice_line_id"] for m in maps})
        i.update(subtotal=r2(sub), vat=r2(vat), total=r2(sub + vat), lines_count=len(lines),
                 mapped=bool(maps), map_status=("waiting approval" if any(m["status"] != "approved" for m in maps) else "linked") if maps else
                 ("linked" if linked else "not linked"), novat=bool(q1(c, "SELECT 1 FROM mt_novat WHERE invoice_id=?", (i["id"],))))
        out.append(i)
    return out


def _advance(c, party_id):
    import api_finance as F
    try:
        return r2(F.party_advance_balance(c, party_id, "purchase"))
    except Exception:
        return 0.0


def _payable(c, party_id):
    tot = 0.0
    for r in q(c, "SELECT id, payable FROM invoices WHERE party_id=? AND kind='purchase' AND status='posted'", (party_id,)):
        tot += _f(r["payable"]) - inv.invoice_paid(c, r["id"])
    return r2(tot)


def _grni_ledger(c, party_id):
    return r2(val(c, "SELECT SUM(l.credit-l.debit) FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id JOIN accounts x ON "
                     "x.id=l.account_id WHERE x.role='grni' AND l.party_id=? AND " + POSTED, (party_id,)))


def _vendor_row(c, p, frm):
    rnb = _received_not_billed(c, p["id"], frm)
    old_days = int(_f(setting(c, "mt_old_days"), 30))
    import datetime as _dt
    cut = (_dt.date.fromisoformat(today()) - _dt.timedelta(days=old_days)).isoformat()
    wb = _waiting_bills(c, p["id"])
    nov = q(c, "SELECT n.*, i.no, i.date, i.status inv_status FROM mt_novat n JOIN invoices i ON i.id=n.invoice_id WHERE n.party_id=? "
               "AND i.date>=? AND n.status IN ('waiting','posted')", (p["id"], frm))
    diff = val(c, "SELECT COUNT(*) FROM mt_map m JOIN invoices i ON i.id=m.invoice_id WHERE i.party_id=? AND m.different=1 AND "
                  "i.status IN ('draft','posted') AND i.date>=?", (p["id"], frm))
    row = {"party_id": p["id"], "vendor": p["name"], "pan": p.get("pan"),
           "received_not_billed": r2(sum(r["unbilled_value"] for r in rnb)),
           "received_not_billed_old": r2(sum(r["unbilled_value"] for r in rnb if r["date"] < cut)),
           "bills_waiting": r2(sum(b["total"] for b in wb)), "bills_waiting_count": len(wb),
           "paid_no_bill": max(0.0, _advance(c, p["id"])), "payable": _payable(c, p["id"]),
           "novat": r2(sum(_f(n["amount"]) for n in nov if n["status"] == "posted")),
           "novat_waiting": sum(1 for n in nov if n["status"] == "waiting"), "different_items": diff,
           "grn_clearing_ledger": _grni_ledger(c, p["id"])}
    row["matched"] = row["received_not_billed"] < EPS and row["bills_waiting"] < EPS and row["paid_no_bill"] < EPS
    return row


@api("mt.vendors", "procurement", "view")
def mt_vendors(c, u, a):
    frm = a.get("from") or _from(c)
    ids = set(r["vendor_id"] for r in q(c, "SELECT DISTINCT vendor_id FROM grn WHERE status='posted' AND vendor_id IS NOT NULL AND date>=?", (frm,)))
    ids |= set(r["party_id"] for r in q(c, "SELECT DISTINCT party_id FROM invoices WHERE kind='purchase' AND status IN ('draft','posted') AND date>=?", (frm,)))
    ids |= set(r["party_id"] for r in q(c, "SELECT DISTINCT party_id FROM payments WHERE kind='pay' AND status='posted' AND date>=?", (frm,)))
    out = []
    for pid in ids:
        p = q1(c, "SELECT * FROM parties WHERE id=?", (pid,))
        if not p or p["kind"] == "client":
            continue
        out.append(_vendor_row(c, p, frm))
    out.sort(key=lambda r: (r["matched"], -(r["received_not_billed"] + r["bills_waiting"] + r["paid_no_bill"]), r["vendor"]))
    tot = {k: r2(sum(r[k] for r in out)) for k in ("received_not_billed", "received_not_billed_old", "bills_waiting", "paid_no_bill", "payable", "novat")}
    return {"on": on(c), "from": frm, "rows": out, "totals": tot}


@api("mt.vendor", "procurement", "view")
def mt_vendor(c, u, a):
    pid = int(a["party_id"])
    p = get(c, "parties", pid, "Vendor")
    frm = a.get("from") or _from(c)
    row = _vendor_row(c, p, frm)
    grn = q(c, "SELECT l.id grn_line_id, l.material_id, m.name material, m.unit, l.accepted_qty, l.invoiced_qty, l.rate, g.id grn_id, "
               "g.no grn_no, g.date, g.challan_no, pr.code project FROM grn_lines l JOIN grn g ON g.id=l.grn_id LEFT JOIN materials m ON "
               "m.id=l.material_id LEFT JOIN projects pr ON pr.id=g.project_id WHERE g.vendor_id=? AND g.status='posted' AND g.date>=? "
               "ORDER BY g.date DESC, g.id DESC, l.id", (pid, frm))
    for r in grn:
        r["unbilled_qty"] = r4(_f(r["accepted_qty"]) - _f(r["invoiced_qty"]))
        r["value"] = r2(_f(r["accepted_qty"]) * _f(r["rate"]))
        r["unbilled_value"] = r2(r["unbilled_qty"] * _f(r["rate"]))
    bills = q(c, "SELECT * FROM invoices WHERE party_id=? AND kind='purchase' AND status IN ('draft','posted') AND date>=? "
                 "ORDER BY date DESC, id DESC", (pid, frm))
    for b in bills:
        lines = q(c, "SELECT * FROM invoice_lines WHERE invoice_id=?", (b["id"],))
        maps = q(c, "SELECT * FROM mt_map WHERE invoice_id=?", (b["id"],))
        b["lines"] = [{"description": l["description"] or _mat_name(c, l["material_id"]) or "", "qty": l["qty"], "rate": l["rate"],
                       "amount": _line_amount(l), "vat_rate": l["vat_rate"], "grn": bool(l["grn_line_id"]),
                       "mapped": any(m["invoice_line_id"] == l["id"] for m in maps)} for l in lines]
        if b["status"] == "draft":
            sub = sum(x["amount"] for x in b["lines"])
            b["subtotal"] = r2(sub)
            b["vat"] = r2(sum(r2(x["amount"] * _f(x["vat_rate"]) / 100) for x in b["lines"]))
            b["total"] = r2(b["subtotal"] + b["vat"])
            b["balance"] = None
        else:
            b["balance"] = r2(_f(b["payable"]) - inv.invoice_paid(c, b["id"]))
        b["novat"] = bool(q1(c, "SELECT 1 FROM mt_novat WHERE invoice_id=?", (b["id"],)))
        b["map_status"] = ("waiting approval" if any(m["status"] != "approved" for m in maps) else "linked") if maps else ""
        b["different"] = any(m["different"] for m in maps)
        b["posted_mapped"] = bool(q1(c, "SELECT 1 FROM mt_post WHERE invoice_id=? AND status='posted'", (b["id"],)))
    pays = q(c, "SELECT p.*, a.name bank FROM payments p LEFT JOIN accounts a ON a.id=p.bank_account_id WHERE p.party_id=? AND p.kind='pay' "
                "AND p.status='posted' AND p.date>=? ORDER BY p.date DESC, p.id DESC", (pid, frm))
    for x in pays:
        x["against"] = ", ".join(r["no"] for r in q(c, "SELECT i.no FROM allocations al JOIN invoices i ON i.id=al.invoice_id WHERE "
                                                       "al.payment_id=? AND al.active=1", (x["id"],)))
    return {"vendor": {"id": p["id"], "name": p["name"], "pan": p.get("pan")}, "summary": row, "grn": grn, "bills": bills,
            "payments": pays, "from": frm, "on": on(c)}


# ───────────────────────────── bill-to-goods mapping ─────────────────────────────
def _bill(c, invoice_id):
    d = inv.load_doc(c, "invoice", int(invoice_id))
    if d["kind"] != "purchase":
        raise ApiError("Only purchase bills are matched to goods received.")
    return d


@api("mt.map_get", "procurement", "view")
def mt_map_get(c, u, a):
    d = _bill(c, a["invoice_id"])
    maps = q(c, "SELECT * FROM mt_map WHERE invoice_id=? ORDER BY invoice_line_id, id", (d["id"],))
    used = {}
    for m in maps:
        used[m["grn_line_id"]] = used.get(m["grn_line_id"], 0) + _f(m["qty"])
    cand = []
    for r in _received_not_billed(c, d["party_id"]):
        cand.append(r)
    seen = {r["grn_line_id"] for r in cand}
    for gid in used:
        if gid not in seen:
            gi = _grn_line_info(c, gid)
            if gi:
                cand.append({"grn_line_id": gid, "material_id": gi["material_id"], "material": gi["material"], "unit": gi["unit"],
                             "grn_no": gi["grn_no"], "date": gi["grn_date"], "rate": gi["rate"], "project_id": gi["project_id"],
                             "unbilled_qty": r4(_f(gi["accepted_qty"]) - _f(gi["invoiced_qty"])),
                             "unbilled_value": r2((_f(gi["accepted_qty"]) - _f(gi["invoiced_qty"])) * _f(gi["rate"]))})
    lines = []
    for l in d["lines"]:
        lines.append({"id": l["id"], "description": l["description"] or _mat_name(c, l["material_id"]) or "", "material_id": l["material_id"],
                      "qty": l["qty"], "rate": l["rate"], "amount": _line_amount(l), "vat_rate": l["vat_rate"], "grn_line_id": l["grn_line_id"],
                      "account_id": l["account_id"]})
    return {"invoice": {k: d[k] for k in ("id", "no", "status", "party_id", "project_id", "date", "party_inv_no")},
            "lines": lines, "maps": maps, "candidates": cand, "on": on(c), "approve_over": _limit(c),
            "can_approve": core.can(u, "procurement", "approve")}


def _check_maps(c, d, rows):
    """rows: dicts invoice_line_id, grn_line_id, qty, amount, reason. Returns cleaned rows."""
    if d["status"] != "draft":
        raise ApiError("Only a draft bill can be linked to goods (this one is %s)." % d["status"])
    if (d.get("procurement_purpose") or "") not in ("",):
        raise ApiError("This bill carries a procurement purpose (project and trading split); link it in Project & trading purchases.")
    lines = {l["id"]: l for l in d["lines"]}
    clean = []
    for r in rows:
        lid, gid = int(r.get("invoice_line_id") or 0), int(r.get("grn_line_id") or 0)
        if lid not in lines:
            raise ApiError("A link points at a bill line that is not on this bill.")
        if not gid:
            raise ApiError("Pick the goods received line for every link.")
        gi = _grn_line_info(c, gid)
        if not gi or gi["grn_status"] != "posted" or gi["vendor_id"] != d["party_id"]:
            raise ApiError("GRN line %s is not a posted receipt from this vendor." % gid)
        if (gi["procurement_purpose"] or "") == "mixed" or _grn_mixed(c, gi["grn_id"]):
            raise ApiError("GRN %s is a mixed project/trading purchase; bill it in Project & trading purchases." % gi["grn_no"])
        qty, amt = r4(_f(r.get("qty"))), r2(_f(r.get("amount")))
        if qty < 0 or amt < 0:
            raise ApiError("Quantities and amounts on links cannot be negative.")
        l = lines[lid]
        mat = l["material_id"]
        different = 0 if (mat and mat == gi["material_id"]) else 1
        reason = (r.get("reason") or "").strip()
        if different and not reason:
            raise ApiError("Bill line '%s' names a different item from the goods received (%s): give a reason." %
                           (l["description"] or _mat_name(c, mat) or "line", gi["material"]))
        clean.append({"invoice_line_id": lid, "grn_line_id": gid, "qty": qty, "amount": amt, "different": different, "reason": reason or None,
                      "_gi": gi})
    by_line, by_grn, vat_of = {}, {}, {}
    for x in clean:
        by_line[x["invoice_line_id"]] = r2(by_line.get(x["invoice_line_id"], 0) + x["amount"])
        by_grn[x["grn_line_id"]] = r4(by_grn.get(x["grn_line_id"], 0) + x["qty"])
        vr = _f(lines[x["invoice_line_id"]]["vat_rate"])
        if vat_of.setdefault(x["grn_line_id"], vr) != vr:
            raise ApiError("Bill lines with different VAT rates cannot be linked to the same goods line (GRN %s)." % x["_gi"]["grn_no"])
    for lid, amt in by_line.items():
        want = _line_amount(lines[lid])
        if abs(amt - want) > 0.004:
            raise ApiError("Bill line '%s' is %s; its links add up to %s. Link the whole line." %
                           (lines[lid]["description"] or _mat_name(c, lines[lid]["material_id"]) or lid, want, amt))
    for gid, qty in by_grn.items():
        gl, left = _uninvoiced(c, gid)
        gi = _grn_line_info(c, gid)
        if qty > left + 0.0001:
            raise ApiError("GRN %s %s: linked quantity %s is more than the quantity not yet billed (%s)." % (gi["grn_no"], gi["material"], qty, left))
        if qty <= 0.0001:
            raise ApiError("GRN %s %s: at least one bill line must carry a quantity of these goods." % (gi["grn_no"], gi["material"]))
    for x in clean:
        x.pop("_gi", None)
    return clean


@api("mt.map_save", "procurement", "edit")
def mt_map_save(c, u, a):
    need_on(c)
    d = _bill(c, a["invoice_id"])
    rows = a.get("rows") or []
    if not rows:
        raise ApiError("Add at least one link, or use 'Remove links'.")
    clean = _check_maps(c, d, rows)
    c.execute("DELETE FROM mt_map WHERE invoice_id=?", (d["id"],))
    diff_amt = r2(sum(x["amount"] for x in clean if x["different"]))
    needs = diff_amt > _limit(c) + 0.004
    st = "saved" if needs else "approved"
    for x in clean:
        ins(c, "mt_map", dict(x, invoice_id=d["id"], status=st, created_by=u["id"], created_at=now(),
                              approved_by=None if needs else u["id"], approved_at=None if needs else now()))
    _log(c, u, "map_save", d["id"], {"rows": clean, "status": st})
    core.audit(c, u, "map", "invoices", d["id"], {"links": len(clean), "different": diff_amt, "status": st})
    return {"status": st, "links": len(clean), "different_amount": diff_amt, "needs_approval": needs}


@api("mt.map_approve", "procurement", "approve")
def mt_map_approve(c, u, a):
    need_on(c)
    d = _bill(c, a["invoice_id"])
    maps = q(c, "SELECT * FROM mt_map WHERE invoice_id=?", (d["id"],))
    if not maps:
        raise ApiError("This bill has no links to approve.")
    if all(m["status"] == "approved" for m in maps):
        return {"status": "approved"}
    _can_approve(c, u, maps[0]["created_by"])
    _check_maps(c, d, [dict(m) for m in maps])
    c.execute("UPDATE mt_map SET status='approved', approved_by=?, approved_at=? WHERE invoice_id=?", (u["id"], now(), d["id"]))
    _log(c, u, "map_approve", d["id"])
    core.audit(c, u, "map_approve", "invoices", d["id"], None)
    return {"status": "approved"}


@api("mt.map_clear", "procurement", "edit")
def mt_map_clear(c, u, a):
    d = _bill(c, a["invoice_id"])
    if d["status"] != "draft":
        raise ApiError("Links of a posted bill stay with it; cancel the bill to change them.")
    n = c.execute("DELETE FROM mt_map WHERE invoice_id=?", (d["id"],)).rowcount
    _log(c, u, "map_clear", d["id"], {"removed": n})
    return {"removed": n}


def _swap_post(orig, c, u, a, d, maps):
    """Post a bill whose printed lines are linked to goods: post against the GRN lines, then put the printed lines back."""
    lines = {l["id"]: dict(l) for l in d["lines"]}
    clean = _check_maps(c, d, [dict(m) for m in maps])
    groups = {}
    for x in clean:
        g = groups.setdefault(x["grn_line_id"], {"qty": 0.0, "amount": 0.0, "vat_rate": _f(lines[x["invoice_line_id"]]["vat_rate"]),
                                                 "lines": []})
        g["qty"] = r4(g["qty"] + x["qty"])
        g["amount"] = r2(g["amount"] + x["amount"])
        g["lines"].append(x["invoice_line_id"])
    mapped_ids = {x["invoice_line_id"] for x in clean}
    printed_vat = sum(r2(_line_amount(lines[i]) * _f(lines[i]["vat_rate"]) / 100) for i in mapped_ids)
    posting_vat = sum(r2(g["amount"] * g["vat_rate"] / 100) for g in groups.values())
    if abs(printed_vat - posting_vat) > 0.004:
        raise ApiError("VAT on the printed lines (%s) and on the linked goods (%s) differ by paisa rounding; adjust a line by "
                       "the difference or link the lines differently." % (r2(printed_vat), r2(posting_vat)))
    snapshot = [lines[i] for i in sorted(lines)]
    for i in mapped_ids:
        c.execute("DELETE FROM invoice_lines WHERE id=?", (i,))
    temp = []
    for gid, g in groups.items():
        gi = _grn_line_info(c, gid)
        rate = g["amount"] / g["qty"]
        if abs(r2(g["qty"] * rate) - g["amount"]) > 0.004:
            rate = round(rate, 10)
        descs = "; ".join((lines[i]["description"] or _mat_name(c, lines[i]["material_id"]) or "") for i in g["lines"])
        temp.append(ins(c, "invoice_lines", {"invoice_id": d["id"], "grn_line_id": gid, "material_id": gi["material_id"],
                                             "description": ("%s %s (bill: %s)" % (gi["grn_no"], gi["material"] or "", descs))[:250],
                                             "qty": g["qty"], "rate": rate, "vat_rate": g["vat_rate"]}))
    res = orig(c, u, a)
    status = val(c, "SELECT status FROM invoices WHERE id=?", (d["id"],), None)
    for t in temp:
        c.execute("DELETE FROM invoice_lines WHERE id=?", (t,))
    cols = [r[1] for r in c.execute("PRAGMA table_info(invoice_lines)").fetchall()]
    for i in mapped_ids:
        row = {k: v for k, v in lines[i].items() if k in cols}
        row["amount"] = _line_amount(lines[i])
        ks = list(row)
        c.execute("INSERT INTO invoice_lines(%s) VALUES(%s)" % (",".join(ks), ",".join("?" * len(ks))), [row[k] for k in ks])
    if status == "posted":
        for gid, g in groups.items():
            ins(c, "mt_post", {"invoice_id": d["id"], "grn_line_id": gid, "qty": g["qty"], "amount": g["amount"],
                               "vat_rate": g["vat_rate"], "status": "posted", "ts": now()})
        c.execute("INSERT OR REPLACE INTO mt_print(invoice_id, lines, ts) VALUES(?,?,?)",
                  (d["id"], json.dumps(snapshot, default=str), now()))
        _log(c, u, "post_linked", d["id"], {"groups": {str(k): {"qty": v["qty"], "amount": v["amount"]} for k, v in groups.items()}})
    return res


def _w_invoice_post(orig):
    def invoice_post(c, u, a):
        d = q1(c, "SELECT * FROM invoices WHERE id=?", (a.get("id"),))
        if not d or d["kind"] != "purchase" or d["status"] != "draft":
            return orig(c, u, a)
        maps = q(c, "SELECT * FROM mt_map WHERE invoice_id=?", (d["id"],))
        if not maps:
            return orig(c, u, a)
        if not on(c):
            raise ApiError("This bill is linked to goods received, but matching is now off. Turn it on in Procurement › "
                           "Purchase bills › Match settings, or remove the links.")
        if any(m["status"] != "approved" for m in maps):
            raise ApiError("This bill's link to goods of a different item waits for approval (Procurement › Purchase bills › "
                           "Match receipts, bills & payments).")
        return _swap_post(orig, c, u, a, inv.load_doc(c, "invoice", d["id"]), maps)
    return invoice_post


def _w_invoice_cancel(orig):
    def invoice_cancel(c, u, a):
        res = orig(c, u, a)
        iid = a.get("id")
        if val(c, "SELECT status FROM invoices WHERE id=?", (iid,), None) == "cancelled":
            for p in q(c, "SELECT * FROM mt_post WHERE invoice_id=? AND status='posted'", (iid,)):
                c.execute("UPDATE grn_lines SET invoiced_qty=invoiced_qty-? WHERE id=?", (p["qty"], p["grn_line_id"]))
                c.execute("UPDATE mt_post SET status='cancelled' WHERE id=?", (p["id"],))
            c.execute("UPDATE mt_novat SET status='cancelled' WHERE invoice_id=?", (iid,))
        return res
    return invoice_cancel


def _w_doc_save(orig):
    def doc_save(c, u, a):
        res = orig(c, u, a)
        try:
            if a.get("type") == "invoice":
                iid = (res or {}).get("id") if isinstance(res, dict) else None
                iid = iid or ((a.get("header") or {}).get("id"))
                if iid and val(c, "SELECT COUNT(*) FROM mt_map WHERE invoice_id=?", (iid,)):
                    d = inv.load_doc(c, "invoice", iid)
                    try:
                        _check_maps(c, d, [dict(m) for m in q(c, "SELECT * FROM mt_map WHERE invoice_id=?", (iid,))])
                    except ApiError as e:
                        c.execute("DELETE FROM mt_map WHERE invoice_id=?", (iid,))
                        _log(c, u, "map_dropped", iid, {"why": str(e)})
                        if isinstance(res, dict):
                            res["mt_note"] = "The bill changed, so its links to goods received were removed: link it again."
        except ApiError:
            raise
        except Exception:
            pass
        return res
    return doc_save


def _w_doc_delete(orig):
    def doc_delete(c, u, a):
        res = orig(c, u, a)
        if a.get("type") == "invoice" and a.get("id") and not q1(c, "SELECT 1 FROM invoices WHERE id=?", (a["id"],)):
            c.execute("DELETE FROM mt_map WHERE invoice_id=?", (a["id"],))
            c.execute("UPDATE mt_novat SET status='deleted' WHERE invoice_id=? AND status='waiting'", (a["id"],))
        return res
    return doc_delete


# ───────────────────────────── purchase without VAT bill ─────────────────────────────
@api("mt.novat_create", "procurement", "edit")
def mt_novat_create(c, u, a):
    need_on(c)
    pid = int(a.get("party_id") or 0)
    party = get(c, "parties", pid, "Vendor")
    reason = (a.get("reason") or "").strip()
    if not reason:
        raise ApiError("Say why there is no VAT bill (for example: vendor gave no bill for the balance).")
    rows = [r for r in (a.get("lines") or []) if _f(r.get("qty")) > 0]
    if not rows:
        raise ApiError("Pick the goods received that have no bill, with a quantity.")
    lines, projects = [], set()
    for r in rows:
        gi = _grn_line_info(c, int(r["grn_line_id"]))
        if not gi or gi["grn_status"] != "posted" or gi["vendor_id"] != pid:
            raise ApiError("GRN line %s is not a posted receipt from %s." % (r.get("grn_line_id"), party["name"]))
        if (gi["procurement_purpose"] or "") == "mixed" or _grn_mixed(c, gi["grn_id"]):
            raise ApiError("GRN %s is a mixed project/trading purchase; bill it in Project & trading purchases." % gi["grn_no"])
        qty = r4(_f(r["qty"]))
        left = r4(_f(gi["accepted_qty"]) - _f(gi["invoiced_qty"]))
        if qty > left + 0.0001:
            raise ApiError("GRN %s %s: %s is more than the quantity not yet billed (%s)." % (gi["grn_no"], gi["material"], qty, left))
        amt = r2(_f(r.get("amount"))) if _f(r.get("amount")) > 0 else r2(qty * _f(gi["rate"]))
        projects.add(gi["project_id"])
        lines.append({"grn_line_id": gi["id"], "material_id": gi["material_id"], "description": "%s (no VAT bill)" % (gi["material"] or ""),
                      "qty": qty, "rate": amt / qty, "vat_rate": 0})
    if len(projects) > 1:
        raise ApiError("Pick goods of one project at a time.")
    n = val(c, "SELECT COUNT(*) FROM mt_novat WHERE party_id=?", (pid,)) + 1
    ref = (a.get("ref") or "").strip() or "NO VAT BILL %d" % n
    hdr = {"kind": "purchase", "party_id": pid, "project_id": projects.pop(), "date": a.get("date") or today(), "party_inv_no": ref,
           "remarks": "Purchase without VAT bill: " + reason}
    res = inv.FUNCS["doc.save"][0](c, u, {"type": "invoice", "header": hdr, "lines": lines})
    iid = res["id"] if isinstance(res, dict) else res
    amount = r2(sum(r2(l["qty"] * l["rate"]) for l in lines))
    ins(c, "mt_novat", {"invoice_id": iid, "party_id": pid, "amount": amount, "reason": reason, "ref": ref,
                        "adjust_advance": 0 if a.get("adjust_advance") in (0, False, "0", "false") else 1, "status": "waiting",
                        "created_by": u["id"], "created_at": now()})
    _log(c, u, "novat_create", iid, {"amount": amount, "reason": reason})
    out = {"invoice_id": iid, "amount": amount, "status": "waiting", "needs_approval": amount > _limit(c) + 0.004}
    if not out["needs_approval"]:
        out.update(_novat_post(c, u, iid, auto=True))
    return out


def _novat_post(c, u, iid, auto=False):
    n = q1(c, "SELECT * FROM mt_novat WHERE invoice_id=?", (iid,))
    if not n:
        raise ApiError("Not a purchase without VAT bill.")
    if n["status"] != "waiting":
        raise ApiError("Already %s." % n["status"])
    if not auto:
        _can_approve(c, u, n["created_by"])
    maker = q1(c, "SELECT * FROM users WHERE id=?", (n["created_by"],)) if not auto else None
    poster = maker if (maker and core.can(maker, "procurement", "edit")) else u
    r = inv.FUNCS["invoice.post"][0](c, poster, {"id": iid})
    st = val(c, "SELECT status FROM invoices WHERE id=?", (iid,), None)
    adjusted = 0.0
    if st == "posted":
        c.execute("UPDATE mt_novat SET status='posted', approved_by=?, approved_at=? WHERE invoice_id=?", (u["id"], now(), iid))
        if n["adjust_advance"]:
            adv = _advance(c, n["party_id"])
            bal = r2(val(c, "SELECT payable FROM invoices WHERE id=?", (iid,)) - inv.invoice_paid(c, iid))
            amt = r2(min(adv, bal))
            if amt > EPS:
                adj_user = poster if core.can(poster, "accounts", "edit") else u
                inv.FUNCS["advance.adjust"][0](c, adj_user, {"invoice_id": iid, "amount": amt,
                                                      "date": val(c, "SELECT date FROM invoices WHERE id=?", (iid,), today())})
                adjusted = amt
        _log(c, u, "novat_post", iid, {"adjusted": adjusted})
    return {"status": "posted" if st == "posted" else st, "no": (r or {}).get("no") if isinstance(r, dict) else None,
            "advance_adjusted": adjusted}


@api("mt.novat_approve", "procurement", "approve")
def mt_novat_approve(c, u, a):
    need_on(c)
    return _novat_post(c, u, int(a["invoice_id"]))


@api("mt.novat_list", "procurement", "view")
def mt_novat_list(c, u, a):
    frm, to = a.get("from") or _from(c), a.get("to") or today()
    rows = q(c, "SELECT n.*, i.no, i.date, i.status inv_status, i.total, pa.name vendor, pr.code project FROM mt_novat n JOIN invoices i ON "
                "i.id=n.invoice_id LEFT JOIN parties pa ON pa.id=n.party_id LEFT JOIN projects pr ON pr.id=i.project_id WHERE i.date BETWEEN ? AND ? "
                "ORDER BY i.date DESC, i.id DESC", (frm, to))
    return {"rows": rows, "total": r2(sum(_f(r["amount"]) for r in rows if r["status"] == "posted")), "from": frm, "to": to}


# ───────────────────────────── bill vs actual ─────────────────────────────
@api("mt.bill_actual", "procurement", "view")
def mt_bill_actual(c, u, a):
    frm, to = a.get("from") or "0000-01-01", a.get("to") or today()
    only_diff = a.get("different") not in (0, False, "0", "false")
    rows = []
    for m in q(c, "SELECT m.*, i.no, i.party_inv_no, i.date, i.status inv_status, pa.name vendor, ua.name approver FROM mt_map m JOIN invoices i ON "
                  "i.id=m.invoice_id LEFT JOIN parties pa ON pa.id=i.party_id LEFT JOIN users ua ON ua.id=m.approved_by WHERE i.date BETWEEN ? AND ? "
                  "AND i.status IN ('draft','posted')" + (" AND m.different=1" if only_diff else "") + " ORDER BY i.date DESC, m.id", (frm, to)):
        l = q1(c, "SELECT * FROM invoice_lines WHERE id=?", (m["invoice_line_id"],)) or {}
        gi = _grn_line_info(c, m["grn_line_id"]) or {}
        rows.append({"date": m["date"], "bill": m["party_inv_no"] or m["no"] or "draft", "bill_no": m["no"], "invoice_id": m["invoice_id"],
                     "vendor": m["vendor"], "status": m["inv_status"],
                     "printed": (l.get("description") or _mat_name(c, l.get("material_id")) or ""), "printed_qty": l.get("qty"),
                     "printed_rate": l.get("rate"), "amount": m["amount"], "vat_rate": l.get("vat_rate"),
                     "received": gi.get("material"), "grn": gi.get("grn_no"), "received_qty": m["qty"], "unit": gi.get("unit"),
                     "grn_rate": gi.get("rate"), "different": bool(m["different"]), "reason": m["reason"], "link_status": m["status"],
                     "approver": m["approver"]})
    return {"rows": rows, "from": frm, "to": to, "total_different": r2(sum(r["amount"] for r in rows if r["different"]))}


# ───────────────────────────── reclassify a posted bill line ─────────────────────────────
@api("mt.reclass_info", "accounts", "view")
def mt_reclass_info(c, u, a):
    d = _bill(c, a["invoice_id"])
    if d["status"] != "posted":
        raise ApiError("Only a posted bill can be reclassified.")
    lines = q(c, "SELECT l.account_id, x.code, x.name, x.type, x.role, SUM(l.debit) debit, SUM(l.credit) credit FROM voucher_lines l JOIN accounts x ON "
                 "x.id=l.account_id WHERE l.voucher_id=? GROUP BY l.account_id ORDER BY x.code", (d["voucher_id"],))
    done = q(c, "SELECT r.*, f.name from_name, t.name to_name FROM mt_reclass r LEFT JOIN accounts f ON f.id=r.from_account_id LEFT JOIN accounts t ON "
                "t.id=r.to_account_id WHERE r.invoice_id=? ORDER BY r.id", (d["id"],))
    movable = []
    for l in lines:
        if l["type"] != "expense" or (l["debit"] or 0) <= EPS:
            continue
        moved = val(c, "SELECT SUM(amount) FROM mt_reclass WHERE invoice_id=? AND from_account_id=? AND status='posted'", (d["id"], l["account_id"]))
        back = val(c, "SELECT SUM(amount) FROM mt_reclass WHERE invoice_id=? AND to_account_id=? AND status='posted'", (d["id"], l["account_id"]))
        movable.append(dict(l, available=r2((l["debit"] or 0) - (l["credit"] or 0) - moved + back)))
    targets = q(c, "SELECT id, code, name, role FROM accounts WHERE active=1 AND type='expense' ORDER BY code")
    return {"invoice": {k: d[k] for k in ("id", "no", "party_inv_no", "date", "project_id", "party_id")}, "lines": lines, "movable": movable,
            "targets": targets, "done": done}


@api("mt.reclass", "accounts", "approve")
def mt_reclass(c, u, a):
    d = _bill(c, a["invoice_id"])
    if d["status"] != "posted":
        raise ApiError("Only a posted bill can be reclassified.")
    reason = (a.get("reason") or "").strip()
    if not reason:
        raise ApiError("Give the reason (for example: sand billed partly as another item; real cost is sand).")
    fa, ta = int(a.get("from_account_id") or 0), int(a.get("to_account_id") or 0)
    amt = r2(_f(a.get("amount")))
    if amt <= 0:
        raise ApiError("Enter the amount to move.")
    if fa == ta:
        raise ApiError("Pick a different account to move it to.")
    info = mt_reclass_info(c, u, {"invoice_id": d["id"]})
    src = next((m for m in info["movable"] if m["account_id"] == fa), None)
    if not src:
        raise ApiError("That account is not an expense line on this bill's voucher.")
    if amt > src["available"] + 0.004:
        raise ApiError("Only %s of %s can still be moved from this bill." % (src["available"], src["name"]))
    to = q1(c, "SELECT * FROM accounts WHERE id=? AND active=1", (ta,))
    if not to or to["type"] != "expense":
        raise ApiError("Move it to an active expense (cost) account. Stock accounts change only through store documents.")
    dims = {}
    if a.get("boq_item_id"):
        inv.check_boq(c, int(a["boq_item_id"]), d["project_id"])
        dims["boq_item_id"] = int(a["boq_item_id"])
    narr = "Reclass of bill %s (%s): %s" % (d["party_inv_no"] or d["no"], d["no"], reason)
    vid = core.post_voucher(c, u, "journal", a.get("date") or today(), narr[:250],
                            [dict({"account_id": ta, "debit": amt, "narration": narr[:120]}, **dims),
                             {"account_id": fa, "credit": amt, "narration": narr[:120]}],
                            project_id=d["project_id"], source="mt_reclass", source_id=d["id"], party_id=d["party_id"])
    rid = ins(c, "mt_reclass", {"invoice_id": d["id"], "from_account_id": fa, "to_account_id": ta, "amount": amt, "reason": reason,
                                "boq_item_id": dims.get("boq_item_id"), "voucher_id": vid, "status": "posted", "created_by": u["id"], "ts": now()})
    _log(c, u, "reclass", d["id"], {"from": fa, "to": ta, "amount": amt})
    core.audit(c, u, "reclass", "invoices", d["id"], {"amount": amt, "voucher_id": vid})
    return {"id": rid, "voucher_id": vid, "amount": amt}


# ───────────────────────────── VAT register, checks ─────────────────────────────
def _w_rep_vat(orig):
    def rep_vat(c, u, a):
        res = orig(c, u, a)
        if (a.get("kind") or "purchase") == "purchase" and isinstance(res, list):
            nov = {r["invoice_id"] for r in q(c, "SELECT invoice_id FROM mt_novat")}
            if nov:
                res = [r for r in res if r.get("id") not in nov]
        return res
    return rep_vat


def checks(c):
    out = []
    if not on(c):
        return out

    def add(name, sev, ok, detail, items=None, amount=None):
        out.append({"area": "Purchases", "check": name, "ok": bool(ok), "severity": "ok" if ok else sev, "detail": detail,
                    "items": (items or [])[:50], "count": len(items or []), "fix": None if ok else "Procurement › Purchase bills › Match receipts, bills & payments",
                    "amount": amount})
    import datetime as _dt
    days = int(_f(setting(c, "mt_old_days"), 30))
    cut = (_dt.date.fromisoformat(today()) - _dt.timedelta(days=days)).isoformat()
    old = [r for r in _received_not_billed(c, None, _from(c)) if r["date"] < cut]
    add("Goods received but not billed for more than %d days" % days, "warn", not old,
        ("%d GRN line(s) since %s" % (len(old), _from(c))) if old else "None since %s" % _from(c),
        [{"ref": r["grn_no"], "amount": r["unbilled_value"], "detail": "%s %s %s" % (r["date"], r["material"] or "", r["unbilled_qty"])} for r in old],
        r2(sum(r["unbilled_value"] for r in old)))
    wait = q(c, "SELECT DISTINCT i.id, i.date, i.party_inv_no, pa.name FROM mt_map m JOIN invoices i ON i.id=m.invoice_id LEFT JOIN parties pa ON "
                "pa.id=i.party_id WHERE m.status<>'approved' AND i.status='draft'")
    wait += q(c, "SELECT i.id, i.date, i.party_inv_no, pa.name FROM mt_novat n JOIN invoices i ON i.id=n.invoice_id LEFT JOIN parties pa ON "
                 "pa.id=i.party_id WHERE n.status='waiting'")
    add("Bill links and no-VAT-bill purchases waiting for approval", "warn", not wait, "%d waiting" % len(wait) if wait else "None waiting",
        [{"ref": r["party_inv_no"] or r["id"], "detail": "%s %s" % (r["date"], r["name"])} for r in wait])
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


# ───────────────────────────── start-up ─────────────────────────────
def _wrap(name, factory):
    cur = inv.FUNCS.get(name)
    if not cur or getattr(cur[0], FLAG, False):
        return
    w = factory(cur[0])
    for k in [k for k in getattr(cur[0], "__dict__", {}) if k.startswith("_bco")]:
        setattr(w, k, getattr(cur[0], k))
    setattr(w, FLAG, True)
    w._orig = cur[0]
    inv.FUNCS[name] = (w, cur[1], cur[2], cur[3])


def _default(c, key, new_value, old_value):
    if val(c, "SELECT COUNT(*) FROM settings WHERE key=?", (key,)):
        return
    used = val(c, "SELECT COUNT(*) FROM vouchers")
    c.execute("INSERT OR IGNORE INTO settings(key, value) VALUES(?,?)", (key, old_value if used else new_value))


def init_match(c):
    c.executescript(SCHEMA)
    try:
        _default(c, "mt_on", "1", "0")
    except Exception:
        c.execute("INSERT OR IGNORE INTO settings(key, value) VALUES('mt_on', '0')")
    for k, v in (("mt_approve_over", "0"), ("mt_self_approve", "0"), ("mt_old_days", "30")):
        c.execute("INSERT OR IGNORE INTO settings(key, value) VALUES(?,?)", (k, v))
    if setting(c, "mt_on") == "1" and not setting(c, "mt_from"):
        _set(c, "mt_from", today())
    c.commit()
    _wrap("invoice.post", _w_invoice_post)
    _wrap("invoice.cancel", _w_invoice_cancel)
    _wrap("doc.save", _w_doc_save)
    _wrap("doc.delete", _w_doc_delete)
    _wrap("rep.vat", _w_rep_vat)
    _wrap("fc.checks", _w_fc_checks)
