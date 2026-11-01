"""
Split procurement: project use and trading use from one supplier purchase (BuildCore 2.19).

One supplier delivers one lot (for example 3,000 cement bags) and sends one bill. Part of it goes to a project
store, part to the trading store for resale. This module adds that split ON TOP of the existing documents:

  * The GRN and the purchase bill get an optional "Procurement purpose" (project use, trading / resale,
    general company use or mixed). Nothing is required: a document without a purpose posts exactly as before.
  * A MIXED GRN carries allocation rows (destination cost centre, store, BOQ item, quantity). Posting it puts
    each quantity straight into its own store through the existing stock engine (stock_in) and one GRN voucher
    (post_voucher). The header store is not used, so no quantity is posted twice.
  * The purchase bill is still ONE invoice, ONE liability, ONE VAT amount, posted by the existing invoice
    engine. Its net value and VAT are then allocated to the destinations (actual line values, or quantity x
    unit price when one bill line covers several destinations) and the allocation is checked to the paisa.
  * Payments still go through the existing payment engine against the real bank account. Each payment is
    tagged with the funding cost centre that paid it and its money is allocated to the bill's destinations.
  * Trading stock leaves by a trading sale (an ordinary sales invoice plus a cost-of-goods-sold entry at the
    store's weighted average) and comes back by a sales return (credit note).
  * Reclassification, return to supplier and transfers are separate, auditable adjustments.

The views by purpose, project and trading are calculated from these allocation rows. No second supplier master,
general ledger, stock ledger or VAT register is created. Trading and general use are cost centres: a project
record whose "Cost-centre type" is Trading or General company use, with its own stores.
"""
from datetime import date

import core
from core import (ApiError, EPS, audit, check_store, get, ins, inventory_role, material, need, next_no, now, num,
                  post_voucher, q, q1, r2, r4, require, reverse_voucher, stock_in, stock_out, today, upd, val)
import api_inventory as inv
from api_inventory import api

VERSION = "2.19.0"
POSTED = "v.status IN ('posted','reversed')"

SCHEMA = """
CREATE TABLE IF NOT EXISTS proc_alloc(id INTEGER PRIMARY KEY, grn_id INTEGER, grn_line_id INTEGER,
  material_id INTEGER, purpose TEXT, project_id INTEGER, store_id INTEGER, boq_item_id INTEGER,
  qty REAL DEFAULT 0, rate REAL DEFAULT 0, landed_rate REAL DEFAULT 0, value REAL DEFAULT 0,
  status TEXT DEFAULT 'draft', kind TEXT DEFAULT 'receipt', adjust_id INTEGER, remarks TEXT,
  created_by INTEGER, ts TEXT);
CREATE INDEX IF NOT EXISTS ix_pa_line ON proc_alloc(grn_line_id, status);
CREATE INDEX IF NOT EXISTS ix_pa_grn ON proc_alloc(grn_id);
CREATE TABLE IF NOT EXISTS proc_inv_alloc(id INTEGER PRIMARY KEY, invoice_id INTEGER, invoice_line_id INTEGER,
  grn_line_id INTEGER, purpose TEXT, project_id INTEGER, store_id INTEGER, qty REAL DEFAULT 0,
  net REAL DEFAULT 0, vat_rate REAL DEFAULT 0, vat REAL DEFAULT 0, rounding REAL DEFAULT 0, method TEXT,
  status TEXT DEFAULT 'posted', adjust_id INTEGER, ts TEXT);
CREATE INDEX IF NOT EXISTS ix_pia_inv ON proc_inv_alloc(invoice_id, status);
CREATE INDEX IF NOT EXISTS ix_pia_line ON proc_inv_alloc(grn_line_id, status);
CREATE TABLE IF NOT EXISTS proc_pay_alloc(id INTEGER PRIMARY KEY, payment_id INTEGER, allocation_id INTEGER,
  invoice_id INTEGER, purpose TEXT, project_id INTEGER, funding_purpose TEXT, funding_project_id INTEGER,
  amount REAL DEFAULT 0, kind TEXT DEFAULT 'payment', active INTEGER DEFAULT 1, ts TEXT);
CREATE INDEX IF NOT EXISTS ix_ppa_inv ON proc_pay_alloc(invoice_id, active);
CREATE INDEX IF NOT EXISTS ix_ppa_pay ON proc_pay_alloc(payment_id);
CREATE TABLE IF NOT EXISTS proc_adjust(id INTEGER PRIMARY KEY, no TEXT, date TEXT, kind TEXT, grn_id INTEGER,
  grn_line_id INTEGER, invoice_id INTEGER, material_id INTEGER, qty REAL DEFAULT 0, value REAL DEFAULT 0,
  net REAL DEFAULT 0, vat REAL DEFAULT 0, from_purpose TEXT, from_project INTEGER, from_store INTEGER,
  to_purpose TEXT, to_project INTEGER, to_store INTEGER, voucher_id INTEGER, reason TEXT,
  created_by INTEGER, ts TEXT);
CREATE TABLE IF NOT EXISTS trade_moves(id INTEGER PRIMARY KEY, no TEXT, kind TEXT, date TEXT, invoice_id INTEGER,
  sale_move_id INTEGER, party_id INTEGER, project_id INTEGER, store_id INTEGER, material_id INTEGER,
  qty REAL DEFAULT 0, price REAL DEFAULT 0, vat_rate REAL DEFAULT 0, net REAL DEFAULT 0, vat REAL DEFAULT 0,
  cost_rate REAL DEFAULT 0, cost_value REAL DEFAULT 0, voucher_id INTEGER, cn_voucher_id INTEGER,
  returned_qty REAL DEFAULT 0, status TEXT DEFAULT 'posted', reason TEXT, created_by INTEGER, ts TEXT);
CREATE INDEX IF NOT EXISTS ix_tm_inv ON trade_moves(invoice_id);
"""
# optional columns on existing tables: empty for every existing record, so nothing old is reclassified
COLUMNS = {"projects": {"kind": "TEXT"},
           "grn": {"procurement_purpose": "TEXT"},
           "invoices": {"procurement_purpose": "TEXT"},
           "invoice_lines": {"proc_alloc_id": "INTEGER"},
           "payments": {"funding_purpose": "TEXT"}}
PURPOSES = [("project", "Project use"), ("trading", "Trading / resale"), ("general", "General company use"),
            ("mixed", "Mixed purchase")]
DEST = ("project", "trading", "general")
PURPOSE_NAME = dict(PURPOSES)
CC_KINDS = [("project", "Construction project"), ("trading", "Trading / resale"), ("general", "General company use")]
# accounts the trading side needs; added only when no account carries the role yet
ACCOUNTS = [("4101", "Trading Sales", "income", "I", "trading_sales"),
            ("4102", "Trading Sales Returns", "income", "I", "trading_returns"),
            ("5301", "Cost of Goods Sold - Trading", "expense", "X4", "cogs_trading")]
Q4 = 0.0005


def init_procure(c):
    for st in SCHEMA.strip().split(";"):
        if st.strip():
            c.execute(st)
    for table, cols in COLUMNS.items():
        have = {r[1] for r in c.execute("PRAGMA table_info(%s)" % table)}
        for col, typ in cols.items():
            if col not in have:
                c.execute("ALTER TABLE %s ADD COLUMN %s %s" % (table, col, typ))
    if val(c, "SELECT COUNT(*) FROM account_groups"):
        _ensure_accounts(c)
    _extend_lists()


def _ensure_accounts(c):
    if not q1(c, "SELECT id FROM account_groups WHERE code='X4'"):
        x = q1(c, "SELECT id FROM account_groups WHERE code='X'") or q1(c, "SELECT id FROM account_groups WHERE type='expense' ORDER BY id")
        if x:
            ins(c, "account_groups", {"code": "X4", "name": "Cost of Trading Goods", "type": "expense", "parent_id": x["id"]})
    for code, name, typ, grp, role in ACCOUNTS:
        if q1(c, "SELECT id FROM accounts WHERE role=?", (role,)):
            continue
        g = q1(c, "SELECT id FROM account_groups WHERE code=?", (grp,)) or \
            q1(c, "SELECT id FROM account_groups WHERE type=? ORDER BY id", (typ,))
        cc, n = code, 0
        while q1(c, "SELECT id FROM accounts WHERE code=?", (cc,)):
            n += 1
            cc = "%s-%d" % (code, n)
        ins(c, "accounts", {"code": cc, "name": name, "type": typ, "group_id": g["id"] if g else None, "role": role,
                            "opening_balance": 0, "active": 1})


def _extend_lists():
    """The generic document and master screens save only the fields they list; add the new optional ones."""
    for t in ("grn", "invoice"):
        hf = inv.DOCS[t][6]
        if "procurement_purpose" not in hf:
            hf.append("procurement_purpose")
    lf = inv.DOCS["invoice"][7]
    if "proc_alloc_id" not in lf:
        lf.append("proc_alloc_id")
    inv.DOC_ID.add("proc_alloc_id")
    pf = inv.MASTERS["projects"][1]
    if "kind" not in pf:
        pf.append("kind")


# ───────────────────────── helpers ─────────────────────────
def cc_kind(c, project_id):
    """What a cost centre is for: 'project' (every existing project), 'trading' or 'general'."""
    k = val(c, "SELECT kind FROM projects WHERE id=?", (project_id,), None) if project_id else None
    return k if k in ("trading", "general") else "project"


def _purpose(p, allow_mixed=True):
    p = (p or "").strip().lower() or None
    if p and p not in (dict(PURPOSES) if allow_mixed else DEST):
        raise ApiError("Unknown procurement purpose '%s'." % p)
    return p


def _check_dest(c, purpose, project_id, store_id=None, boq_item_id=None):
    if purpose not in DEST:
        raise ApiError("Each destination needs a purpose: project use, trading / resale or general company use.")
    if not project_id:
        raise ApiError("Each destination needs a project or cost centre.")
    k = cc_kind(c, project_id)
    if k != purpose:
        p = get(c, "projects", project_id, "Project")
        raise ApiError("%s is a %s cost centre; it cannot take %s material. Choose a %s cost centre "
                       "(set its Cost-centre type in Master data › Projects)." %
                       (p["code"], dict(CC_KINDS)[k].lower(), PURPOSE_NAME[purpose].lower(), PURPOSE_NAME[purpose].lower()))
    if store_id:
        s = check_store(c, store_id, project_id)
        if s["type"] == "transit":
            raise ApiError("Material cannot be received into the in-transit store.")
    if boq_item_id:
        if purpose != "project":
            raise ApiError("Only project-use material can be linked to a BOQ item.")
        inv.check_boq(c, boq_item_id, project_id)


def _main_store(c, project_id):
    core.ensure_project_stores(c, project_id)
    return val(c, "SELECT id FROM stores WHERE project_id=? AND type='main' ORDER BY id LIMIT 1", (project_id,))


def _grn_is_mixed(c, grn_id):
    return val(c, "SELECT procurement_purpose FROM grn WHERE id=?", (grn_id,), None) == "mixed"


def _accepted(l):
    return num(l["received_qty"]) if l.get("accepted_qty") is None else num(l["accepted_qty"])


def _dest_balance(c, grn_line_id):
    """Quantity held by each destination of a mixed GRN line after adjustments: {(purpose, project, store): row}."""
    out = {}
    for a in q(c, "SELECT * FROM proc_alloc WHERE grn_line_id=? AND status='posted' ORDER BY id", (grn_line_id,)):
        k = (a["purpose"], a["project_id"], a["store_id"])
        r = out.setdefault(k, {"purpose": a["purpose"], "project_id": a["project_id"], "store_id": a["store_id"],
                               "boq_item_id": a["boq_item_id"], "qty": 0.0, "value": 0.0,
                               "landed_rate": a["landed_rate"], "rate": a["rate"], "alloc_id": a["id"]})
        r["qty"] = r4(r["qty"] + a["qty"])
        r["value"] = r2(r["value"] + a["value"])
        if a["kind"] == "receipt" and a["boq_item_id"]:
            r["boq_item_id"] = a["boq_item_id"]
    return out


def _dest_invoiced(c, grn_line_id):
    out = {}
    for a in q(c, "SELECT purpose, project_id, store_id, SUM(qty) qty, SUM(net) net, SUM(vat) vat FROM proc_inv_alloc "
                  "WHERE grn_line_id=? AND status='posted' GROUP BY purpose, project_id, store_id", (grn_line_id,)):
        out[(a["purpose"], a["project_id"], a["store_id"])] = a
    return out


# ───────────────────────── setup ─────────────────────────
@api("proc.meta")
def proc_meta(c, u, a):
    return {"purposes": PURPOSES, "cc_kinds": CC_KINDS, "version": VERSION,
            "cost_centres": q(c, "SELECT id, code, name, COALESCE(kind,'project') kind, status FROM projects ORDER BY code")}


@api("proc.setup", "masters", "edit")
def proc_setup(c, u, a):
    """Create the Trading and General-use cost centres (each with a main store) if they do not exist yet."""
    made = []
    for kind, code, name in (("trading", "TRADING", "Trading / resale"), ("general", "GENERAL", "General company use")):
        if a.get("only") and a["only"] != kind:
            continue
        p = q1(c, "SELECT id FROM projects WHERE kind=? ORDER BY id LIMIT 1", (kind,))
        if not p:
            cc, n = code, 0
            while q1(c, "SELECT id FROM projects WHERE code=?", (cc,)):
                n += 1
                cc = "%s-%d" % (code, n)
            pid = ins(c, "projects", {"code": cc, "name": name, "kind": kind, "status": "active", "contract_value": 0})
            made.append(cc)
        else:
            pid = p["id"]
        core.ensure_project_stores(c, pid)
        if kind == "trading":
            upd(c, "stores", _main_store(c, pid), {"name": "Trading Store"})
    _ensure_accounts(c)
    if made:
        audit(c, u, "proc_setup", "projects", None, made)
    return {"created": made, "cost_centres": proc_meta(c, u, {})["cost_centres"]}


# ───────────────────────── GRN allocation (draft) ─────────────────────────
@api("proc.alloc_get", "inventory", "view")
def alloc_get(c, u, a):
    g = inv.load_doc(c, "grn", int(a["grn_id"]))
    rows = q(c, "SELECT * FROM proc_alloc WHERE grn_id=? AND status IN ('draft','posted') ORDER BY grn_line_id, id",
             (g["id"],))
    lines = []
    for l in g["lines"]:
        acc = _accepted(l)
        mine = [r for r in rows if r["grn_line_id"] == l["id"]]
        if g["status"] == "draft":
            done = r4(sum(r["qty"] for r in mine if r["status"] == "draft"))
            dest = [r for r in mine if r["status"] == "draft"]
        else:
            bal = _dest_balance(c, l["id"])
            inv_ = _dest_invoiced(c, l["id"])
            dest = []
            for k, r in bal.items():
                x = inv_.get(k) or {}
                dest.append(dict(r, invoiced_qty=r4(x.get("qty") or 0), net=r2(x.get("net") or 0),
                                 vat=r2(x.get("vat") or 0)))
            done = r4(sum(r["qty"] for r in dest))
        lines.append({"grn_line_id": l["id"], "material_id": l["material_id"], "accepted_qty": r4(acc),
                      "rate": l["rate"], "landed_rate": l["landed_rate"], "invoiced_qty": l["invoiced_qty"],
                      "allocated": done, "unallocated": r4(acc - done), "destinations": dest})
    adj = q(c, "SELECT * FROM proc_adjust WHERE grn_id=? ORDER BY id", (g["id"],))
    return {"grn_id": g["id"], "no": g["no"], "status": g["status"], "purpose": g.get("procurement_purpose"),
            "project_id": g["project_id"], "lines": lines, "adjustments": adj}


@api("proc.alloc_save", "inventory", "edit")
def alloc_save(c, u, a):
    """Replace the draft allocation of a draft GRN. rows: grn_line_id, purpose, project_id, store_id, boq_item_id, qty."""
    g = inv.draft_doc(c, "grn", int(a["grn_id"]))
    lines = {l["id"]: l for l in g["lines"]}
    clean = []
    for r in a.get("rows") or []:
        qty = r4(num(r.get("qty"), "quantity"))
        if qty <= 0:
            continue
        lid = int(r.get("grn_line_id") or 0)
        if lid not in lines:
            raise ApiError("An allocation row does not belong to a line of this GRN. Save the GRN and try again.")
        purpose = _purpose(r.get("purpose"), allow_mixed=False)
        pid = int(r["project_id"]) if r.get("project_id") else None
        sid = int(r["store_id"]) if r.get("store_id") else (_main_store(c, pid) if pid else None)
        boq = int(r["boq_item_id"]) if r.get("boq_item_id") else None
        _check_dest(c, purpose, pid, sid, boq)
        clean.append({"grn_id": g["id"], "grn_line_id": lid, "material_id": lines[lid]["material_id"], "purpose": purpose,
                      "project_id": pid, "store_id": sid, "boq_item_id": boq, "qty": qty, "status": "draft",
                      "kind": "receipt", "remarks": r.get("remarks"), "created_by": u["id"], "ts": now()})
    for lid, l in lines.items():
        tot = sum(x["qty"] for x in clean if x["grn_line_id"] == lid)
        if tot > _accepted(l) + Q4:
            m = material(c, l["material_id"])
            raise ApiError("%s: allocated %s is more than the accepted quantity %s." % (m["name"], r4(tot), r4(_accepted(l))))
    c.execute("DELETE FROM proc_alloc WHERE grn_id=? AND status='draft'", (g["id"],))
    for x in clean:
        ins(c, "proc_alloc", x)
    if g.get("procurement_purpose") != "mixed":
        upd(c, "grn", g["id"], {"procurement_purpose": "mixed"})
    audit(c, u, "proc_alloc", "grn", g["id"], clean)
    return alloc_get(c, u, {"grn_id": g["id"]})


# ───────────────────────── GRN posting ─────────────────────────
def _post_mixed_grn(c, u, g):
    """grn.post for a mixed GRN: the same checks and the same posting functions, but every accepted quantity
    goes into its own destination store. The header store receives nothing."""
    need(g, "project_id", "vendor_id", "date")
    vendor = get(c, "parties", g["vendor_id"], "Vendor")
    if vendor["blacklisted"]:
        raise ApiError("Vendor %s is blacklisted." % vendor["name"])
    po = None
    if g["po_id"]:
        po = get(c, "po", g["po_id"], "PO")
        if po["status"] not in ("approved", "partially_received"):
            raise ApiError("PO %s is %s." % (po["no"], po["status"]))
        if po["vendor_id"] != g["vendor_id"] or po["project_id"] != g["project_id"]:
            raise ApiError("GRN vendor/project must match the PO.")
    tol = core.fsetting(c, "over_receipt_pct")
    if not g["lines"]:
        raise ApiError("Add at least one line.")
    c.execute("DELETE FROM proc_alloc WHERE grn_id=? AND status='draft' AND grn_line_id NOT IN "
              "(SELECT id FROM grn_lines WHERE grn_id=?)", (g["id"], g["id"]))
    allocs = q(c, "SELECT * FROM proc_alloc WHERE grn_id=? AND status='draft' ORDER BY id", (g["id"],))
    prepared = []
    for l in g["lines"]:
        m = material(c, l["material_id"])
        rec = num(l["received_qty"])
        acc = rec if l["accepted_qty"] is None else num(l["accepted_qty"])
        if acc < 0 or acc > rec + EPS:
            raise ApiError("%s: accepted quantity must be between 0 and received quantity." % m["name"])
        rate = num(l["rate"])
        if po:
            if not l["po_line_id"]:
                raise ApiError("%s: pick the PO line it belongs to." % m["name"])
            pl = get(c, "po_lines", l["po_line_id"], "PO line")
            if pl["po_id"] != po["id"] or pl["material_id"] != l["material_id"]:
                raise ApiError("%s does not match its PO line." % m["name"])
            if (pl["received_qty"] or 0) + acc > pl["qty"] * (1 + tol / 100) + EPS:
                raise ApiError("%s: receiving %s would exceed PO quantity %s (+%s%% tolerance). Already received %s." %
                               (m["name"], acc, pl["qty"], tol, pl["received_qty"] or 0))
            rate = pl["rate"]
        if rate <= 0 and acc > 0:
            raise ApiError("%s: rate is required." % m["name"])
        mine = [x for x in allocs if x["grn_line_id"] == l["id"]]
        tot = r4(sum(x["qty"] for x in mine))
        if abs(tot - acc) > Q4:
            raise ApiError("%s: the destinations add up to %s but %s was accepted. Allocate the full quantity "
                           "(a mixed purchase must be allocated completely before posting)." % (m["name"], tot, r4(acc)))
        for x in mine:
            _check_dest(c, x["purpose"], x["project_id"], x["store_id"], x["boq_item_id"])
        prepared.append((l, m, rec, acc, rate, mine))
    base = sum(acc * rate for _l, _m, _r, acc, rate, _x in prepared)
    freight = num(g["freight"])
    if freight > 0 and base <= 0:
        raise ApiError("Freight needs at least one accepted line with value.")
    no = next_no(c, "GRN", g["date"])
    by_dest = {}
    total_val = 0.0
    for l, m, rec, acc, rate, mine in prepared:
        share = (acc * rate / base * freight) if base > 0 else 0
        landed = rate + (share / acc if acc > EPS else 0)
        upd(c, "grn_lines", l["id"], {"accepted_qty": acc, "rejected_qty": r4(rec - acc), "rate": rate,
                                      "landed_rate": r4(landed)})
        for x in mine:
            v = stock_in(c, u, x["project_id"], x["store_id"], m["id"], x["qty"], landed, g["date"], "GRN", g["id"], no,
                         l["batch_no"])
            key = (inventory_role(m), x["project_id"])
            by_dest[key] = by_dest.get(key, 0) + v
            total_val += v
            upd(c, "proc_alloc", x["id"], {"rate": rate, "landed_rate": r4(landed), "value": v, "status": "posted"})
        if po:
            c.execute("UPDATE po_lines SET received_qty=COALESCE(received_qty,0)+? WHERE id=?", (acc, l["po_line_id"]))
    vl = [{"role": r, "debit": v, "project_id": p, "narration": "Received for %s" % _cc_code(c, p)}
          for (r, p), v in by_dest.items()]
    if freight > 0:
        vl.append({"role": "freight_clearing", "credit": freight, "narration": "Freight on " + no})
    vl.append({"role": "grni", "credit": r2(total_val - freight), "party_id": g["vendor_id"]})
    vid = post_voucher(c, u, "journal", g["date"], "Goods received %s from %s (mixed purchase)" % (no, vendor["name"]), vl,
                       project_id=g["project_id"], source="grn", source_id=g["id"], party_id=g["vendor_id"],
                       ref_no=g["challan_no"])
    upd(c, "grn", g["id"], {"status": "posted", "no": no, "voucher_id": vid})
    if po:
        inv.po_refresh_status(c, po["id"])
    audit(c, u, "post", "grn", g["id"], {"no": no, "mixed": True})
    return {"no": no}


def _cc_code(c, pid):
    return val(c, "SELECT code FROM projects WHERE id=?", (pid,), "") or ""


def _wrap(name, fn):
    orig = inv.FUNCS[name]
    if getattr(orig[0], "_bco219", False):
        return
    w = fn(orig[0])
    w._bco219 = True
    inv.FUNCS[name] = (w, orig[1], orig[2], orig[3])


def _grn_post_w(orig):
    def grn_post2(c, u, a):
        g = inv.draft_doc(c, "grn", a["id"])
        p = _purpose(g.get("procurement_purpose"))
        if p == "mixed":
            return _post_mixed_grn(c, u, g)
        if p in DEST and g.get("project_id"):
            _check_dest(c, p, g["project_id"])
        return orig(c, u, a)
    return grn_post2


def _grn_cancel_w(orig):
    def grn_cancel2(c, u, a):
        g = inv.load_doc(c, "grn", a["id"])
        if g.get("procurement_purpose") != "mixed" or g["status"] != "posted":
            return orig(c, u, a)
        if any((l["invoiced_qty"] or 0) > EPS for l in g["lines"]):
            raise ApiError("This GRN is already invoiced. Cancel the invoice first.")
        if q1(c, "SELECT id FROM proc_adjust WHERE grn_id=? AND voucher_id IS NOT NULL AND kind<>'review'", (g["id"],)):
            raise ApiError("This GRN has reclassifications or returns. Cancel by a stock transfer or return instead.")
        for l in g["lines"]:
            for d in _dest_balance(c, l["id"]).values():
                if d["qty"] > EPS:
                    stock_out(c, u, d["project_id"], d["store_id"], l["material_id"], d["qty"], today(),
                              "GRN-CANCEL", g["id"], g["no"], rate=l["landed_rate"])
            if (l["accepted_qty"] or 0) > EPS and l["po_line_id"]:
                c.execute("UPDATE po_lines SET received_qty=received_qty-? WHERE id=?", (l["accepted_qty"], l["po_line_id"]))
        reverse_voucher(c, u, g["voucher_id"], today(), a.get("reason") or "GRN cancelled")
        c.execute("UPDATE proc_alloc SET status='reversed' WHERE grn_id=? AND status='posted'", (g["id"],))
        upd(c, "grn", g["id"], {"status": "cancelled", "remarks": ((g["remarks"] or "") + " | Cancelled: " +
                                                                 (a.get("reason") or "")).strip(" |")})
        if g["po_id"]:
            inv.po_refresh_status(c, g["po_id"])
        audit(c, u, "cancel", "grn", g["id"], a.get("reason"))
        return True
    return grn_cancel2


def _issue_post_w(orig):
    def issue_post2(c, u, a):
        d = inv.load_doc(c, "issue", a["id"])
        if d.get("project_id") and cc_kind(c, d["project_id"]) == "trading":
            raise ApiError("Trading stock is not consumed on site. It leaves by a Trading sale, or by a stock transfer "
                           "to a project store (which makes it project material).")
        return orig(c, u, a)
    return issue_post2


# ───────────────────────── purchase bill ─────────────────────────
def _line_dest(c, inv_row, l):
    """Purpose and destination of a bill line that has no allocation rows (single-purpose or legacy)."""
    if l.get("grn_line_id"):
        g = q1(c, "SELECT g.* FROM grn g JOIN grn_lines gl ON gl.grn_id=g.id WHERE gl.id=?", (l["grn_line_id"],))
        if g:
            return (g.get("procurement_purpose") if g.get("procurement_purpose") in DEST else cc_kind(c, g["project_id"]),
                    g["project_id"], g["store_id"])
    p = inv_row.get("procurement_purpose")
    return (p if p in DEST else cc_kind(c, inv_row["project_id"]), inv_row["project_id"], None)


def _split_line(c, l, amount, lv):
    """Allocate one bill line taken from a mixed GRN line to its destinations. Returns rows to store."""
    qty = num(l["qty"])
    if l.get("proc_alloc_id"):
        x = get(c, "proc_alloc", int(l["proc_alloc_id"]), "Destination")
        return [{"purpose": x["purpose"], "project_id": x["project_id"], "store_id": x["store_id"], "qty": r4(qty),
                 "net": r2(amount), "vat": r2(lv), "rounding": 0.0, "method": "line"}]
    bal, done = _dest_balance(c, l["grn_line_id"]), _dest_invoiced(c, l["grn_line_id"])
    rem = []
    for k, d in bal.items():
        r = r4(d["qty"] - ((done.get(k) or {}).get("qty") or 0))
        if r > Q4:
            rem.append((k, d, r))
    tot = sum(r for _k, _d, r in rem)
    if tot < qty - Q4:
        raise ApiError("A bill line asks for %s but only %s of that GRN line is left to bill across its destinations."
                       % (r4(qty), r4(tot)))
    out, aq, an, av = [], 0.0, 0.0, 0.0
    for i, (k, d, r) in enumerate(rem):
        last = i == len(rem) - 1
        qi = r4(qty - aq) if last else (r if abs(tot - qty) <= Q4 else r4(qty * r / tot))
        exact_n = amount * qi / qty if qty else 0
        exact_v = lv * qi / qty if qty else 0
        ni = r2(amount - an) if last else r2(exact_n)
        vi = r2(lv - av) if last else r2(exact_v)
        out.append({"purpose": d["purpose"], "project_id": d["project_id"], "store_id": d["store_id"], "qty": qi,
                    "net": ni, "vat": vi, "rounding": r2((ni - exact_n) + (vi - exact_v)) if last else 0.0,
                    "method": "qty"})
        aq, an, av = aq + qi, an + ni, av + vi
    return [o for o in out if o["qty"] > Q4 or abs(o["net"]) > 0.004]


def _inv_post_w(orig):
    def invoice_post2(c, u, a):
        d = inv.load_doc(c, "invoice", a["id"])
        if d["kind"] != "purchase" or d["status"] != "draft":
            return orig(c, u, a)
        p = _purpose(d.get("procurement_purpose"))
        mixed_lines = [l for l in d["lines"] if l["grn_line_id"] and
                       _grn_is_mixed(c, val(c, "SELECT grn_id FROM grn_lines WHERE id=?", (l["grn_line_id"],)))]
        for l in d["lines"]:
            if l.get("proc_alloc_id"):
                x = get(c, "proc_alloc", int(l["proc_alloc_id"]), "Destination")
                if x["grn_line_id"] != l["grn_line_id"] or x["status"] != "posted":
                    raise ApiError("A bill line names a destination that is not part of its GRN line.")
                k = (x["purpose"], x["project_id"], x["store_id"])
                left = (_dest_balance(c, x["grn_line_id"]).get(k) or {}).get("qty", 0) - \
                       ((_dest_invoiced(c, x["grn_line_id"]).get(k) or {}).get("qty") or 0)
                if num(l["qty"]) > left + Q4:
                    raise ApiError("A bill line asks for %s at %s but only %s is left to bill there." %
                                   (l["qty"], _cc_code(c, x["project_id"]), r4(left)))
        if p in DEST:
            for l in d["lines"]:
                if l["grn_line_id"] and l in mixed_lines:
                    raise ApiError("This bill is marked %s but it bills a mixed GRN. Mark the bill Mixed purchase."
                                   % PURPOSE_NAME[p])
                if l["grn_line_id"]:
                    lp = _line_dest(c, d, l)[0]
                    if lp != p:
                        raise ApiError("This bill is marked %s but a GRN line on it went to %s. Mark the bill "
                                       "Mixed purchase, or reclassify the GRN first." % (PURPOSE_NAME[p], PURPOSE_NAME[lp]))
        if mixed_lines and p != "mixed":
            upd(c, "invoices", d["id"], {"procurement_purpose": "mixed"})
        res = orig(c, u, a)
        if mixed_lines:
            _allocate_invoice(c, u, d["id"])
        return res
    return invoice_post2


def _allocate_invoice(c, u, invoice_id):
    d = inv.load_doc(c, "invoice", invoice_id)
    header = d["project_id"]
    var_by_dest = {}
    for l in d["lines"]:
        if not l["grn_line_id"]:
            continue
        gl = get(c, "grn_lines", l["grn_line_id"])
        if not _grn_is_mixed(c, gl["grn_id"]):
            continue
        amount = r2(num(l["qty"]) * num(l["rate"]))
        lv = r2(amount * num(l["vat_rate"]) / 100)
        rows = _split_line(c, l, amount, lv)
        if abs(r2(sum(r["net"] for r in rows)) - amount) > 0.004 or abs(r2(sum(r["vat"] for r in rows)) - lv) > 0.004 \
                or abs(r4(sum(r["qty"] for r in rows)) - r4(l["qty"])) > Q4:
            raise ApiError("The allocation of a bill line does not add up to the line (%s). Nothing was posted." % amount)
        for r in rows:
            ins(c, "proc_inv_alloc", dict(r, invoice_id=d["id"], invoice_line_id=l["id"], grn_line_id=l["grn_line_id"],
                                          vat_rate=l["vat_rate"], status="posted", ts=now()))
            diff = r2(r["net"] - r["qty"] * gl["rate"])
            if abs(diff) > 0.004 and r["project_id"] != header:
                var_by_dest[r["project_id"]] = r2(var_by_dest.get(r["project_id"], 0) + diff)
    if var_by_dest:
        # the invoice engine books a rate difference on the bill's project; move each destination's share to it
        vl = []
        for pid, amt in var_by_dest.items():
            vl.append({"role": "price_variance", "debit": amt, "project_id": pid, "narration": "Rate difference share"})
            vl.append({"role": "price_variance", "credit": amt, "project_id": header, "narration": "Rate difference share"})
        vid = post_voucher(c, u, "journal", d["date"], "Rate difference on %s shared to its destinations" % d["no"], vl,
                           project_id=header, source="proc_variance", source_id=d["id"], party_id=d["party_id"])
        ins(c, "proc_adjust", {"no": d["no"], "date": d["date"], "kind": "variance", "invoice_id": d["id"],
                               "value": r2(sum(var_by_dest.values())), "voucher_id": vid, "created_by": u["id"], "ts": now()})


def _inv_cancel_w(orig):
    def invoice_cancel2(c, u, a):
        res = orig(c, u, a)
        for x in q(c, "SELECT * FROM proc_adjust WHERE invoice_id=? AND kind='variance' AND voucher_id IS NOT NULL",
                   (a["id"],)):
            reverse_voucher(c, u, x["voucher_id"], today(), "Bill cancelled")
        c.execute("UPDATE proc_inv_alloc SET status='cancelled' WHERE invoice_id=? AND status='posted'", (a["id"],))
        return res
    return invoice_cancel2


# ───────────────────────── destinations of a bill ─────────────────────────
def invoice_dests(c, invoice):
    """Each destination's share of one posted purchase bill: net, VAT, gross and share of the payable."""
    rows = {}

    def add(k, net, vat, qty, method):
        r = rows.setdefault(k, {"purpose": k[0], "project_id": k[1], "net": 0.0, "vat": 0.0, "qty": 0.0, "methods": set()})
        r["net"] += net
        r["vat"] += vat
        r["qty"] += qty
        r["methods"].add(method)
    # returns are settlements of the bill (debit notes), not a change of the bill, so they are left out here
    stored = q(c, "SELECT * FROM proc_inv_alloc WHERE invoice_id=? AND status='posted' AND COALESCE(method,'')<>'return'",
               (invoice["id"],))
    stored_lines = {x["invoice_line_id"] for x in stored}
    for x in stored:
        add((x["purpose"], x["project_id"]), x["net"], x["vat"], x["qty"], x["method"] or "qty")
    for l in q(c, "SELECT * FROM invoice_lines WHERE invoice_id=?", (invoice["id"],)):
        if l["id"] in stored_lines:
            continue
        amount = r2(l["amount"] if l["amount"] is not None else num(l["qty"]) * num(l["rate"]))
        p, pid, _s = _line_dest(c, invoice, l)
        add((p, pid), amount, r2(amount * num(l["vat_rate"]) / 100), num(l["qty"]),
            "legacy" if not invoice.get("procurement_purpose") else "line")
    out = sorted(rows.values(), key=lambda r: (-(r["net"] + r["vat"])))
    gross = sum(r["net"] + r["vat"] for r in out)
    payable = invoice["payable"] or 0
    acc = 0.0
    for i, r in enumerate(out):
        r["net"], r["vat"], r["qty"] = r2(r["net"]), r2(r["vat"]), r4(r["qty"])
        r["gross"] = r2(r["net"] + r["vat"])
        r["method"] = "/".join(sorted(r.pop("methods")))
        r["payable"] = r2(payable - acc) if i == len(out) - 1 else (r2(r["gross"] * payable / gross) if gross else 0)
        acc += r["payable"]
    return out


def _settled_by_dest(c, invoice_id):
    out = {}
    for x in q(c, "SELECT purpose, project_id, SUM(amount) amt FROM proc_pay_alloc WHERE invoice_id=? AND active=1 "
                  "GROUP BY purpose, project_id", (invoice_id,)):
        out[(x["purpose"], x["project_id"])] = x["amt"] or 0
    return out


def _split_settlement(c, invoice, amount, prefer=None):
    """Spread an amount paid on a bill over its destinations: first the funding source's own share, then the rest
    in proportion to what each destination still owes."""
    dests = invoice_dests(c, invoice)
    done = _settled_by_dest(c, invoice["id"])
    # payments made before 2.19 (no destination record) are counted proportionally
    legacy = r2(core.val(c, "SELECT SUM(amount) FROM allocations WHERE invoice_id=? AND active=1", (invoice["id"],))
                - sum(done.values()) - amount)
    tot_pay = sum(d["payable"] for d in dests) or 1
    for d in dests:
        k = (d["purpose"], d["project_id"])
        d["open"] = r2(d["payable"] - (done.get(k) or 0) - (legacy * d["payable"] / tot_pay if legacy > 0.004 else 0))
    out, left = [], r2(amount)
    if prefer:
        for d in dests:
            if left <= 0.004:
                break
            if d["purpose"] == prefer[0] and (prefer[0] != "project" or not prefer[1] or d["project_id"] == prefer[1]):
                take = r2(min(left, max(d["open"], 0)))
                if take > 0.004:
                    out.append((d, take, False))
                    d["open"] = r2(d["open"] - take)
                    left = r2(left - take)
    if left > 0.004:
        opn = [d for d in dests if d["open"] > 0.004] or dests
        tot = sum(max(d["open"], 0) for d in opn) or len(opn)
        acc = 0.0
        for i, d in enumerate(opn):
            take = r2(left - acc) if i == len(opn) - 1 else r2(left * (max(d["open"], 0) if tot else 1) / tot)
            acc += take
            if abs(take) > 0.004:
                out.append((d, take, bool(prefer)))
    return out


def _record_settlement(c, invoice, allocation_id, payment_id, amount, kind, funding):
    fp, fpid = funding
    for d, amt, cross in _split_settlement(c, invoice, amount, (fp, fpid) if fp else None):
        ins(c, "proc_pay_alloc", {"payment_id": payment_id, "allocation_id": allocation_id, "invoice_id": invoice["id"],
                                  "purpose": d["purpose"], "project_id": d["project_id"], "funding_purpose": fp,
                                  "funding_project_id": fpid, "amount": amt,
                                  "kind": kind + ("_cross" if cross else ""), "active": 1, "ts": now()})


def _pay_create_w(orig):
    def payment_create2(c, u, a):
        res = orig(c, u, a)
        if a.get("kind") != "pay":
            return res
        pay = get(c, "payments", res["id"])
        fpid = int(a["project_id"]) if a.get("project_id") else pay["project_id"]
        fp = _purpose(a.get("funding_purpose"), allow_mixed=False) or cc_kind(c, fpid)
        upd(c, "payments", pay["id"], {"funding_purpose": fp})
        for al in q(c, "SELECT * FROM allocations WHERE payment_id=? AND active=1", (pay["id"],)):
            invoice = get(c, "invoices", al["invoice_id"])
            _record_settlement(c, invoice, al["id"], pay["id"], al["amount"], "payment", (fp, fpid))
        if (pay["advance"] or 0) > 0.004:
            ins(c, "proc_pay_alloc", {"payment_id": pay["id"], "invoice_id": None, "purpose": fp, "project_id": fpid,
                                      "funding_purpose": fp, "funding_project_id": fpid, "amount": pay["advance"],
                                      "kind": "advance", "active": 1, "ts": now()})
        return res
    return payment_create2


def _pay_cancel_w(orig):
    def payment_cancel2(c, u, a):
        res = orig(c, u, a)
        c.execute("UPDATE proc_pay_alloc SET active=0 WHERE payment_id=?", (a["id"],))
        return res
    return payment_cancel2


def _adv_adjust_w(orig):
    def advance_adjust2(c, u, a):
        res = orig(c, u, a)
        invoice = get(c, "invoices", int(a["invoice_id"]))
        if invoice["kind"] == "purchase":
            al = q1(c, "SELECT * FROM allocations WHERE invoice_id=? AND payment_id IS NULL AND active=1 ORDER BY id DESC "
                       "LIMIT 1", (invoice["id"],))
            if al:
                _record_settlement(c, invoice, al["id"], None, al["amount"], "advance_adjust", (None, None))
        return res
    return advance_adjust2


def _patch_advance_balance():
    """Credit/debit notes from returns are recorded as settlements of the bill; they are not advances."""
    import api_finance as F
    orig = F.party_advance_balance
    if getattr(orig, "_bco219", False):
        return

    def party_advance_balance(c, party_id, kind):
        back = val(c, "SELECT SUM(a.amount) FROM allocations a JOIN invoices i ON i.id=a.invoice_id JOIN vouchers v ON "
                      "v.id=a.voucher_id WHERE a.active=1 AND a.payment_id IS NULL AND i.party_id=? AND i.kind=? AND "
                      "v.source IN ('proc_return','trade_return')", (party_id, kind))
        return r2(orig(c, party_id, kind) + back)
    party_advance_balance._bco219 = True
    F.party_advance_balance = party_advance_balance


# ───────────────────────── adjustments ─────────────────────────
def _find_dest(c, grn_line_id, purpose, project_id, store_id):
    bal = _dest_balance(c, grn_line_id)
    k = (purpose, int(project_id), int(store_id)) if store_id else None
    if k and k in bal:
        return k, bal[k]
    for kk, d in bal.items():
        if d["purpose"] == purpose and d["project_id"] == int(project_id) and (not store_id or d["store_id"] == int(store_id)):
            return kk, d
    raise ApiError("That destination is not part of this GRN line.")


@api("proc.reclass", "inventory", "approve")
def proc_reclass(c, u, a):
    """Move quantity of a posted mixed GRN line from one destination to another (for example trading -> project).
    Stock moves at the GRN's landed rate, the inventory value moves between cost centres, and any billed net and VAT
    move with it. Everything is kept as an adjustment record; the original allocation is not edited."""
    need(a, "grn_line_id", "from_purpose", "from_project_id", "to_purpose", "to_project_id", "qty")
    gl = get(c, "grn_lines", int(a["grn_line_id"]), "GRN line")
    g = get(c, "grn", gl["grn_id"])
    if g["status"] != "posted" or g.get("procurement_purpose") != "mixed":
        raise ApiError("Only posted mixed GRNs are reclassified here. For any other stock use a stock transfer.")
    d = a.get("date") or today()
    qty = r4(num(a["qty"], "quantity"))
    k, src = _find_dest(c, gl["id"], a["from_purpose"], a["from_project_id"], a.get("from_store_id"))
    if qty <= 0 or qty > src["qty"] + Q4:
        raise ApiError("Quantity must be between 0 and %s." % src["qty"])
    to_p = _purpose(a["to_purpose"], allow_mixed=False)
    to_pid = int(a["to_project_id"])
    to_sid = int(a["to_store_id"]) if a.get("to_store_id") else _main_store(c, to_pid)
    to_boq = int(a["boq_item_id"]) if a.get("boq_item_id") else None
    _check_dest(c, to_p, to_pid, to_sid, to_boq)
    if (to_p, to_pid, to_sid) == k:
        raise ApiError("Source and destination are the same.")
    m = material(c, gl["material_id"])
    no = next_no(c, "PRC", d)
    rate = gl["landed_rate"] or gl["rate"]
    _r, v = stock_out(c, u, src["project_id"], src["store_id"], m["id"], qty, d, "PRC-OUT", g["id"], no, rate=rate)
    stock_in(c, u, to_pid, to_sid, m["id"], qty, rate, d, "PRC-IN", g["id"], no)
    role = inventory_role(m)
    vid = None
    if src["project_id"] != to_pid:
        vid = post_voucher(c, u, "journal", d, "Reclassified %s %s from %s to %s (%s)" %
                           (qty, m["name"], _cc_code(c, src["project_id"]), _cc_code(c, to_pid), g["no"]),
                           [{"role": role, "debit": v, "project_id": to_pid, "narration": m["name"]},
                            {"role": role, "credit": v, "project_id": src["project_id"], "narration": m["name"]}],
                           project_id=g["project_id"], source="proc_reclass", source_id=g["id"], party_id=g["vendor_id"])
    aid = ins(c, "proc_adjust", {"no": no, "date": d, "kind": "reclass", "grn_id": g["id"], "grn_line_id": gl["id"],
                                 "material_id": m["id"], "qty": qty, "value": v, "from_purpose": src["purpose"],
                                 "from_project": src["project_id"], "from_store": src["store_id"], "to_purpose": to_p,
                                 "to_project": to_pid, "to_store": to_sid, "voucher_id": vid,
                                 "reason": a.get("reason"), "created_by": u["id"], "ts": now()})
    base = {"grn_id": g["id"], "grn_line_id": gl["id"], "material_id": m["id"], "rate": gl["rate"],
            "landed_rate": rate, "status": "posted", "kind": "reclass", "adjust_id": aid, "created_by": u["id"], "ts": now()}
    ins(c, "proc_alloc", dict(base, purpose=src["purpose"], project_id=src["project_id"], store_id=src["store_id"],
                              qty=-qty, value=-v))
    ins(c, "proc_alloc", dict(base, purpose=to_p, project_id=to_pid, store_id=to_sid, boq_item_id=to_boq, qty=qty, value=v))
    # billed value follows the goods
    billed = _dest_invoiced(c, gl["id"]).get(k)
    net = vat = 0.0
    if billed and (billed["qty"] or 0) > Q4:
        mv = min(qty, billed["qty"])
        for x in q(c, "SELECT invoice_id, invoice_line_id, vat_rate, SUM(qty) qty, SUM(net) net, SUM(vat) vat FROM "
                      "proc_inv_alloc WHERE grn_line_id=? AND status='posted' AND purpose=? AND project_id=? AND "
                      "COALESCE(store_id,0)=? GROUP BY invoice_line_id ORDER BY invoice_line_id",
                   (gl["id"], k[0], k[1], k[2] or 0)):
            if mv <= Q4 or (x["qty"] or 0) <= Q4:
                continue
            tq = min(mv, x["qty"])
            tn, tv = r2(x["net"] * tq / x["qty"]), r2(x["vat"] * tq / x["qty"])
            row = {"invoice_id": x["invoice_id"], "invoice_line_id": x["invoice_line_id"], "grn_line_id": gl["id"],
                   "vat_rate": x["vat_rate"], "method": "reclass", "status": "posted", "adjust_id": aid, "ts": now()}
            ins(c, "proc_inv_alloc", dict(row, purpose=k[0], project_id=k[1], store_id=k[2], qty=-tq, net=-tn, vat=-tv))
            ins(c, "proc_inv_alloc", dict(row, purpose=to_p, project_id=to_pid, store_id=to_sid, qty=tq, net=tn, vat=tv))
            net, vat, mv = net + tn, vat + tv, mv - tq
        upd(c, "proc_adjust", aid, {"net": r2(net), "vat": r2(vat)})
    audit(c, u, "proc_reclass", "grn", g["id"], {"no": no, "qty": qty, "from": k, "to": [to_p, to_pid, to_sid]})
    return {"no": no, "value": v, "net_moved": r2(net), "vat_moved": r2(vat)}


@api("proc.return", "inventory", "approve")
def proc_return(c, u, a):
    """Return part of a mixed purchase to the supplier from one destination.
    Not yet billed: the receipt is reduced (Dr GRN clearing, Cr inventory).
    Already billed: needs the supplier's credit note number; a debit note reduces the supplier balance, the stock and
    the input VAT of exactly that destination, and is recorded as a settlement of the bill."""
    need(a, "grn_line_id", "purpose", "project_id", "qty")
    gl = get(c, "grn_lines", int(a["grn_line_id"]), "GRN line")
    g = get(c, "grn", gl["grn_id"])
    if g["status"] != "posted" or g.get("procurement_purpose") != "mixed":
        raise ApiError("Only posted mixed GRNs are returned here.")
    d = a.get("date") or today()
    qty = r4(num(a["qty"], "quantity"))
    k, src = _find_dest(c, gl["id"], a["purpose"], a["project_id"], a.get("store_id"))
    if qty <= 0 or qty > src["qty"] + Q4:
        raise ApiError("Quantity must be between 0 and %s." % src["qty"])
    m = material(c, gl["material_id"])
    billed = _dest_invoiced(c, gl["id"]).get(k) or {}
    unbilled_here = r4(src["qty"] - (billed.get("qty") or 0))
    no = next_no(c, "PRT", d)
    landed = gl["landed_rate"] or gl["rate"]
    _r, v = stock_out(c, u, src["project_id"], src["store_id"], m["id"], qty, d, "PRT", g["id"], no, rate=landed)
    role = inventory_role(m)
    base_val = r2(qty * gl["rate"])
    net = vat = 0.0
    invoice_id = None
    if qty <= unbilled_here + Q4 and gl["accepted_qty"] - gl["invoiced_qty"] >= qty - Q4:
        vl = [{"role": "grni", "debit": base_val, "party_id": g["vendor_id"], "project_id": g["project_id"]},
              {"role": role, "credit": v, "project_id": src["project_id"], "narration": m["name"]},
              {"role": "price_variance", "debit": r2(v - base_val), "project_id": src["project_id"],
               "narration": "Freight on returned goods"}]
        vid = post_voucher(c, u, "journal", d, "Returned %s %s to supplier before billing (%s)" % (qty, m["name"], g["no"]),
                           vl, project_id=g["project_id"], source="proc_return", source_id=g["id"], party_id=g["vendor_id"])
        c.execute("UPDATE grn_lines SET accepted_qty=accepted_qty-?, rejected_qty=COALESCE(rejected_qty,0)+? WHERE id=?",
                  (qty, qty, gl["id"]))
    else:
        need(a, "credit_note_no")
        x = q1(c, "SELECT invoice_id, vat_rate, SUM(qty) qty, SUM(net) net, SUM(vat) vat FROM proc_inv_alloc WHERE "
                  "grn_line_id=? AND status='posted' AND purpose=? AND project_id=? AND COALESCE(store_id,0)=? "
                  "GROUP BY invoice_id ORDER BY invoice_id DESC LIMIT 1", (gl["id"], k[0], k[1], k[2] or 0))
        if not x or (x["qty"] or 0) < qty - Q4:
            raise ApiError("Return the unbilled quantity first, or a quantity not more than was billed to this destination.")
        invoice = get(c, "invoices", x["invoice_id"])
        invoice_id = invoice["id"]
        net, vat = r2(x["net"] * qty / x["qty"]), r2(x["vat"] * qty / x["qty"])
        open_bal = r2(invoice["payable"] - inv.invoice_paid(c, invoice["id"]))
        if net + vat > open_bal + 0.004:
            raise ApiError("The bill %s has only %s unpaid; a return of %s needs a refund from the supplier first "
                           "(record it as a receipt), then the return." % (invoice["no"], open_bal, r2(net + vat)))
        vl = [{"role": "ap_control", "debit": r2(net + vat), "party_id": g["vendor_id"], "project_id": invoice["project_id"],
               "narration": invoice["no"]},
              {"role": "vat_input", "credit": vat},
              {"role": role, "credit": v, "project_id": src["project_id"], "narration": m["name"]},
              {"role": "price_variance", "debit": r2(v - net), "project_id": src["project_id"], "narration": "Return at billed value"}]
        vid = post_voucher(c, u, "debit_note", d, "Debit note: %s %s returned (%s, supplier credit note %s)" %
                           (qty, m["name"], invoice["no"], a["credit_note_no"]), vl, project_id=invoice["project_id"],
                           source="proc_return", source_id=g["id"], party_id=g["vendor_id"], ref_no=a["credit_note_no"])
        ins(c, "allocations", {"payment_id": None, "invoice_id": invoice["id"], "amount": r2(net + vat), "date": d,
                               "voucher_id": vid, "active": 1})
        ins(c, "proc_inv_alloc", {"invoice_id": invoice["id"], "invoice_line_id": None, "grn_line_id": gl["id"],
                                  "purpose": k[0], "project_id": k[1], "store_id": k[2], "qty": -qty, "net": -net,
                                  "vat_rate": x["vat_rate"], "vat": -vat, "method": "return", "status": "posted", "ts": now()})
        al = q1(c, "SELECT id FROM allocations WHERE voucher_id=? AND invoice_id=? AND active=1", (vid, invoice["id"]))
        ins(c, "proc_pay_alloc", {"payment_id": None, "allocation_id": al["id"] if al else None, "invoice_id": invoice["id"],
                                  "purpose": k[0], "project_id": k[1], "funding_purpose": k[0], "funding_project_id": k[1],
                                  "amount": r2(net + vat), "kind": "debit_note", "active": 1, "ts": now()})
        c.execute("UPDATE grn_lines SET accepted_qty=accepted_qty-?, invoiced_qty=invoiced_qty-?, "
                  "rejected_qty=COALESCE(rejected_qty,0)+? WHERE id=?", (qty, qty, qty, gl["id"]))
    if gl["po_line_id"]:
        c.execute("UPDATE po_lines SET received_qty=received_qty-? WHERE id=?", (qty, gl["po_line_id"]))
    aid = ins(c, "proc_adjust", {"no": no, "date": d, "kind": "return", "grn_id": g["id"], "grn_line_id": gl["id"],
                                 "invoice_id": invoice_id, "material_id": m["id"], "qty": qty, "value": v, "net": net,
                                 "vat": vat, "from_purpose": k[0], "from_project": k[1], "from_store": k[2],
                                 "voucher_id": vid, "reason": a.get("reason"), "created_by": u["id"], "ts": now()})
    ins(c, "proc_alloc", {"grn_id": g["id"], "grn_line_id": gl["id"], "material_id": m["id"], "purpose": k[0],
                          "project_id": k[1], "store_id": k[2], "qty": -qty, "value": -v, "rate": gl["rate"],
                          "landed_rate": landed, "status": "posted", "kind": "return", "adjust_id": aid,
                          "created_by": u["id"], "ts": now()})
    audit(c, u, "proc_return", "grn", g["id"], {"no": no, "qty": qty, "dest": k, "invoice_id": invoice_id})
    return {"no": no, "stock_value": v, "net": net, "vat": vat, "billed": bool(invoice_id)}


@api("proc.review", "procurement", "approve")
def proc_review(c, u, a):
    """Mark the purpose of an existing (legacy) GRN or bill after review. Only the label changes, never an amount:
    the purpose must agree with the cost centre the goods were booked to. Anything else is a reclassification."""
    need(a, "type", "id", "purpose")
    t = a["type"]
    if t not in ("grn", "invoice"):
        raise ApiError("Only GRNs and purchase bills have a procurement purpose.")
    p = _purpose(a["purpose"], allow_mixed=False)
    row = get(c, "grn" if t == "grn" else "invoices", int(a["id"]), "Document")
    if row.get("procurement_purpose"):
        raise ApiError("This document already has a purpose (%s)." % row["procurement_purpose"])
    if t == "invoice" and row["kind"] != "purchase":
        raise ApiError("Only purchase bills.")
    k = cc_kind(c, row["project_id"])
    if p != k:
        raise ApiError("This document was booked to a %s cost centre. Mark it %s, or move the goods first with a stock "
                       "transfer." % (dict(CC_KINDS)[k].lower(), PURPOSE_NAME[k]))
    upd(c, "grn" if t == "grn" else "invoices", row["id"], {"procurement_purpose": p})
    ins(c, "proc_adjust", {"no": row["no"], "date": today(), "kind": "review", "grn_id": row["id"] if t == "grn" else None,
                           "invoice_id": row["id"] if t == "invoice" else None, "to_purpose": p, "to_project": row["project_id"],
                           "reason": a.get("reason"), "created_by": u["id"], "ts": now()})
    audit(c, u, "proc_review", t, row["id"], p)
    return True


# ───────────────────────── trading sales ─────────────────────────
def _role_id(c, role):
    return core.role_account(c, role)


@api("trade.sale", "accounts", "edit")
def trade_sale(c, u, a):
    """Sell trading stock: one ordinary sales invoice (VAT output through the existing invoice engine) and one
    cost-of-goods-sold entry at the trading store's weighted average cost."""
    need(a, "party_id", "project_id", "store_id", "date")
    pid, sid = int(a["project_id"]), int(a["store_id"])
    if cc_kind(c, pid) != "trading":
        raise ApiError("Choose the Trading cost centre. Project stock is not sold here.")
    check_store(c, sid, pid)
    party = get(c, "parties", int(a["party_id"]), "Customer")
    if party["kind"] != "client":
        raise ApiError("%s is not a customer. Add the buyer in Master data › Vendors, subcontractors & clients with "
                       "type Client." % party["name"])
    lines = [x for x in (a.get("lines") or []) if x.get("material_id") and num(x.get("qty")) > 0]
    if not lines:
        raise ApiError("Add at least one line with a quantity.")
    acc = _role_id(c, "trading_sales")
    iid = ins(c, "invoices", {"kind": "sales", "party_id": party["id"], "project_id": pid, "date": a["date"],
                              "party_inv_no": a.get("bill_no"), "status": "draft", "procurement_purpose": "trading",
                              "remarks": a.get("remarks") or "Trading sale", "created_by": u["id"]})
    for x in lines:
        m = material(c, int(x["material_id"]))
        ins(c, "invoice_lines", {"invoice_id": iid, "material_id": m["id"], "description": m["name"],
                                 "qty": num(x["qty"]), "rate": num(x.get("price") or x.get("rate"), "price"),
                                 "vat_rate": num(x.get("vat_rate")), "account_id": acc})
    res = inv.FUNCS["invoice.post"][0](c, u, {"id": iid})
    vl, moves = [], []
    for l in q(c, "SELECT * FROM invoice_lines WHERE invoice_id=? ORDER BY id", (iid,)):
        m = material(c, l["material_id"])
        rate, cost = stock_out(c, u, pid, sid, m["id"], l["qty"], a["date"], "TSALE", iid, res["no"])
        vl.append({"role": "cogs_trading", "debit": cost, "project_id": pid, "narration": m["name"]})
        vl.append({"role": inventory_role(m), "credit": cost, "project_id": pid, "narration": m["name"]})
        moves.append({"no": res["no"], "kind": "sale", "date": a["date"], "invoice_id": iid, "party_id": party["id"],
                      "project_id": pid, "store_id": sid, "material_id": m["id"], "qty": l["qty"], "price": l["rate"],
                      "vat_rate": l["vat_rate"], "net": l["amount"], "vat": r2(l["amount"] * l["vat_rate"] / 100),
                      "cost_rate": r4(rate), "cost_value": cost, "status": "posted", "created_by": u["id"], "ts": now()})
    vid = post_voucher(c, u, "journal", a["date"], "Cost of goods sold %s" % res["no"], vl, project_id=pid,
                       source="trade_sale", source_id=iid)
    for mv in moves:
        mv["voucher_id"] = vid
        ins(c, "trade_moves", mv)
    audit(c, u, "trade_sale", "invoices", iid, {"no": res["no"]})
    return {"no": res["no"], "invoice_id": iid, "cogs": r2(sum(m["cost_value"] for m in moves))}


@api("trade.return", "accounts", "edit")
def trade_return(c, u, a):
    """A customer returns trading goods: a credit note (Dr sales returns and VAT output, Cr debtor) and the goods back
    into the trading store at the cost they left at (Dr inventory, Cr cost of goods sold)."""
    need(a, "invoice_id", "date")
    invoice = get(c, "invoices", int(a["invoice_id"]), "Sale")
    sales = q(c, "SELECT * FROM trade_moves WHERE invoice_id=? AND kind='sale' AND status='posted'", (invoice["id"],))
    if invoice["kind"] != "sales" or invoice["status"] != "posted" or not sales:
        raise ApiError("Choose a posted trading sale.")
    want = {int(k): num(v) for k, v in (a.get("qty") or {}).items() if num(v) > 0}
    if not want:
        raise ApiError("Enter the quantity returned.")
    no = next_no(c, "TRN", a["date"])
    vl, rows, total = [], [], 0.0
    for s in sales:
        qty = want.get(s["id"])
        if not qty:
            continue
        if qty > s["qty"] - s["returned_qty"] + Q4:
            raise ApiError("Line %s: only %s left to return." % (s["id"], r4(s["qty"] - s["returned_qty"])))
        m = material(c, s["material_id"])
        net = r2(qty * s["price"])
        vat = r2(net * s["vat_rate"] / 100)
        cost = stock_in(c, u, s["project_id"], s["store_id"], m["id"], qty, s["cost_rate"], a["date"], "TRET",
                        invoice["id"], no)
        vl += [{"role": "trading_returns", "debit": net, "project_id": s["project_id"], "narration": m["name"]},
               {"role": "vat_output", "debit": vat},
               {"role": inventory_role(m), "debit": cost, "project_id": s["project_id"], "narration": m["name"]},
               {"role": "cogs_trading", "credit": cost, "project_id": s["project_id"], "narration": m["name"]}]
        total += net + vat
        c.execute("UPDATE trade_moves SET returned_qty=returned_qty+? WHERE id=?", (qty, s["id"]))
        rows.append({"no": no, "kind": "return", "date": a["date"], "invoice_id": invoice["id"], "sale_move_id": s["id"],
                     "party_id": s["party_id"], "project_id": s["project_id"], "store_id": s["store_id"],
                     "material_id": m["id"], "qty": qty, "price": s["price"], "vat_rate": s["vat_rate"], "net": -net,
                     "vat": -vat, "cost_rate": s["cost_rate"], "cost_value": -cost, "status": "posted",
                     "reason": a.get("reason"), "created_by": u["id"], "ts": now()})
    total = r2(total)
    open_bal = r2(invoice["payable"] - inv.invoice_paid(c, invoice["id"]))
    if total > open_bal + 0.004:
        raise ApiError("Sale %s has only %s unpaid. Refund the customer first (a payment), then record the return."
                       % (invoice["no"], open_bal))
    vl.append({"role": "ar_control", "credit": total, "party_id": invoice["party_id"]})
    vid = post_voucher(c, u, "credit_note", a["date"], "Credit note %s: goods returned on %s" % (no, invoice["no"]), vl,
                       project_id=invoice["project_id"], source="trade_return", source_id=invoice["id"],
                       party_id=invoice["party_id"], ref_no=invoice["no"])
    ins(c, "allocations", {"payment_id": None, "invoice_id": invoice["id"], "amount": total, "date": a["date"],
                           "voucher_id": vid, "active": 1})
    for r in rows:
        r["cn_voucher_id"] = vid
        ins(c, "trade_moves", r)
    audit(c, u, "trade_return", "invoices", invoice["id"], {"no": no, "total": total})
    return {"no": no, "credit": total}


@api("trade.list", "accounts", "view")
def trade_list(c, u, a):
    cond, p = "", []
    if a.get("project_id"):
        cond, p = " AND t.project_id=?", [int(a["project_id"])]
    return q(c, "SELECT t.*, i.no invoice_no, m.name material, m.unit FROM trade_moves t JOIN invoices i ON i.id=t.invoice_id "
                "JOIN materials m ON m.id=t.material_id WHERE 1=1" + cond + " ORDER BY t.date DESC, t.id DESC LIMIT 500", p)


# ───────────────────────── reports ─────────────────────────
def _names(c):
    return ({p["id"]: p for p in q(c, "SELECT id, code, name, COALESCE(kind,'') kind FROM projects")},
            {s["id"]: s["name"] for s in q(c, "SELECT id, name FROM stores")},
            {m["id"]: m for m in q(c, "SELECT id, code, name, unit FROM materials")},
            {p["id"]: p["name"] for p in q(c, "SELECT id, name FROM parties")})


def receipt_rows(c, a):
    """Every posted purchase receipt by destination: mixed GRNs from their allocation rows, all others (including
    every GRN from before 2.19) as one destination - the store they were posted into."""
    cond, p = ["g.status='posted'"], []
    for k, col in (("party_id", "g.vendor_id"), ("grn_id", "g.id")):
        if a.get(k):
            cond.append(col + "=?")
            p.append(int(a[k]))
    if a.get("from"):
        cond.append("g.date>=?")
        p.append(a["from"])
    if a.get("to"):
        cond.append("g.date<=?")
        p.append(a["to"])
    out = []
    for l in q(c, "SELECT l.*, g.no grn_no, g.date, g.vendor_id, g.project_id grn_project, g.store_id grn_store, "
                  "g.procurement_purpose FROM grn_lines l JOIN grn g ON g.id=l.grn_id WHERE " + " AND ".join(cond) +
               " ORDER BY g.date, g.id, l.id", p):
        base = {"grn_id": l["grn_id"], "grn_no": l["grn_no"], "date": l["date"], "party_id": l["vendor_id"],
                "grn_line_id": l["id"], "material_id": l["material_id"], "rate": l["rate"],
                "doc_purpose": l["procurement_purpose"] or "", "reviewed": bool(l["procurement_purpose"])}
        if l["procurement_purpose"] == "mixed":
            inv_ = _dest_invoiced(c, l["id"])
            for k, d in _dest_balance(c, l["id"]).items():
                x = inv_.get(k) or {}
                out.append(dict(base, purpose=d["purpose"], project_id=d["project_id"], store_id=d["store_id"],
                                qty=d["qty"], value=d["value"], billed_qty=r4(x.get("qty") or 0),
                                net=r2(x.get("net") or 0), vat=r2(x.get("vat") or 0)))
        else:
            purpose = l["procurement_purpose"] if l["procurement_purpose"] in DEST else cc_kind(c, l["grn_project"])
            billed = q1(c, "SELECT SUM(il.qty) q, SUM(il.amount) n, SUM(ROUND(il.amount*il.vat_rate/100,2)) v FROM "
                           "invoice_lines il JOIN invoices i ON i.id=il.invoice_id WHERE il.grn_line_id=? AND "
                           "i.status='posted'", (l["id"],))
            out.append(dict(base, purpose=purpose, project_id=l["grn_project"], store_id=l["grn_store"],
                            qty=r4(l["accepted_qty"] or 0), value=r2((l["accepted_qty"] or 0) * (l["landed_rate"] or l["rate"] or 0)),
                            billed_qty=r4(billed["q"] or 0), net=r2(billed["n"] or 0), vat=r2(billed["v"] or 0)))
    if a.get("project_id"):
        out = [r for r in out if r["project_id"] == int(a["project_id"])]
    if a.get("purpose"):
        out = [r for r in out if r["purpose"] == a["purpose"]]
    return out


def _bills(c, a):
    cond, p = ["kind='purchase'", "status='posted'"], []
    for k in ("party_id",):
        if a.get(k):
            cond.append(k + "=?")
            p.append(int(a[k]))
    if a.get("invoice_id"):
        cond.append("id=?")
        p.append(int(a["invoice_id"]))
    if a.get("from"):
        cond.append("date>=?")
        p.append(a["from"])
    if a.get("to"):
        cond.append("date<=?")
        p.append(a["to"])
    return q(c, "SELECT * FROM invoices WHERE " + " AND ".join(cond) + " ORDER BY date, id", p)


def bill_rows(c, a):
    """Every posted purchase bill split by destination, with what was paid (or settled) for each destination."""
    out = []
    for b in _bills(c, a):
        dests = invoice_dests(c, b)
        paid_total = inv.invoice_paid(c, b["id"])
        done = _settled_by_dest(c, b["id"])
        legacy = r2(paid_total - sum(done.values()))
        tot_pay = sum(d["payable"] for d in dests) or 1
        for d in dests:
            k = (d["purpose"], d["project_id"])
            paid = r2((done.get(k) or 0) + (legacy * d["payable"] / tot_pay if abs(legacy) > 0.004 else 0))
            out.append({"invoice_id": b["id"], "no": b["no"], "date": b["date"], "party_id": b["party_id"],
                        "party_inv_no": b["party_inv_no"], "doc_purpose": b.get("procurement_purpose") or "",
                        "reviewed": bool(b.get("procurement_purpose")), "purpose": d["purpose"],
                        "project_id": d["project_id"], "qty": d["qty"], "net": d["net"], "vat": d["vat"],
                        "gross": d["gross"], "payable": d["payable"], "paid": paid, "outstanding": r2(d["payable"] - paid),
                        "method": d["method"]})
    if a.get("project_id"):
        out = [r for r in out if r["project_id"] == int(a["project_id"])]
    if a.get("purpose"):
        out = [r for r in out if r["purpose"] == a["purpose"]]
    return out


def _ap_book(c, party_id=None):
    cond, p = "", []
    if party_id:
        cond, p = " AND l.party_id=?", [party_id]
    return r2(-val(c, "SELECT SUM(l.debit-l.credit) FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id JOIN accounts x "
                      "ON x.id=l.account_id WHERE x.role='ap_control' AND " + POSTED + cond, p))


def _sum(rows, *keys):
    return {k: r2(sum(r.get(k) or 0 for r in rows)) for k in keys}


@api("proc.report", "procurement", "view")
def proc_report(c, u, a):
    view = a.get("view") or "mixed"
    projects, stores, mats, parties = _names(c)
    fn = REPORTS.get(view)
    if not fn:
        raise ApiError("Unknown report.")
    r = fn(c, u, a)
    r["view"] = view
    r["names"] = {"projects": {k: "%s %s" % (v["code"], v["name"]) for k, v in projects.items()},
                  "stores": stores, "materials": {k: "%s %s" % (v["code"], v["name"]) for k, v in mats.items()},
                  "units": {k: v["unit"] for k, v in mats.items()}, "parties": parties}
    return r


def rep_mixed(c, u, a):
    rows = [r for r in receipt_rows(c, a) if r["doc_purpose"] == "mixed"]
    bills = [r for r in bill_rows(c, a) if r["doc_purpose"] == "mixed"]
    by_grn = {}
    for r in rows:
        g = by_grn.setdefault(r["grn_id"], {"qty": 0.0, "accepted": 0.0})
        g["qty"] += r["qty"]
    for gid, g in by_grn.items():
        g["accepted"] = val(c, "SELECT SUM(accepted_qty) FROM grn_lines WHERE grn_id=?", (gid,))
    for r in rows:
        r["check"] = "ok" if abs(by_grn[r["grn_id"]]["qty"] - by_grn[r["grn_id"]]["accepted"]) <= Q4 * 10 else "check"
    return {"rows": rows, "bills": bills, "totals": _sum(rows, "qty", "value", "net", "vat"),
            "bill_totals": _sum(bills, "net", "vat", "gross", "payable", "paid", "outstanding")}


def _stock_moves(c, project_ids, frm, to):
    if not project_ids:
        return []
    ph = ",".join("?" * len(project_ids))
    return q(c, "SELECT project_id, material_id, doc_type, SUM(qty_in) qin, SUM(qty_out) qout, SUM(value_in) vin, "
                "SUM(value_out) vout FROM stock_ledger WHERE project_id IN (%s) AND date BETWEEN ? AND ? "
                "GROUP BY project_id, material_id, doc_type" % ph, list(project_ids) + [frm, to])


def rep_project_cost(c, u, a):
    frm, to = a.get("from") or "0000-01-01", a.get("to") or today()
    pids = [p["id"] for p in q(c, "SELECT id FROM projects WHERE COALESCE(kind,'') NOT IN ('trading','general')")]
    if a.get("project_id"):
        pids = [int(a["project_id"])]
    rec = [r for r in receipt_rows(c, dict(a, purpose="project")) if r["project_id"] in pids]
    out = {}
    for r in rec:
        x = out.setdefault((r["project_id"], r["material_id"]), {"project_id": r["project_id"], "material_id": r["material_id"],
                                                                 "purchased_qty": 0.0, "purchased_value": 0.0, "billed_net": 0.0,
                                                                 "billed_vat": 0.0, "issued_qty": 0.0, "issued_value": 0.0,
                                                                 "returned_qty": 0.0, "closing_qty": 0.0, "closing_value": 0.0,
                                                                 "grn_ids": []})
        x["purchased_qty"] += r["qty"]
        x["purchased_value"] += r["value"]
        x["billed_net"] += r["net"]
        x["billed_vat"] += r["vat"]
        x["grn_ids"].append(r["grn_id"])
    for m in _stock_moves(c, pids, frm, to):
        if (m["project_id"], m["material_id"]) not in out and m["doc_type"] not in ("MIN", "MRT"):
            continue
        x = out.setdefault((m["project_id"], m["material_id"]), {"project_id": m["project_id"], "material_id": m["material_id"],
                                                                 "purchased_qty": 0.0, "purchased_value": 0.0, "billed_net": 0.0,
                                                                 "billed_vat": 0.0, "issued_qty": 0.0, "issued_value": 0.0,
                                                                 "returned_qty": 0.0, "closing_qty": 0.0, "closing_value": 0.0,
                                                                 "grn_ids": []})
        if m["doc_type"] in ("MIN",):
            x["issued_qty"] += (m["qout"] or 0) - (m["qin"] or 0)
            x["issued_value"] += (m["vout"] or 0) - (m["vin"] or 0)
        if m["doc_type"] in ("MRT",):
            x["returned_qty"] += (m["qin"] or 0)
            x["issued_value"] -= (m["vin"] or 0)
    for x in out.values():
        b = q1(c, "SELECT SUM(qty) q, SUM(value) v FROM stock_balances WHERE project_id=? AND material_id=?",
               (x["project_id"], x["material_id"]))
        x["closing_qty"], x["closing_value"] = r4(b["q"] or 0), r2(b["v"] or 0)
        x["grn_ids"] = sorted(set(x["grn_ids"]))
        for k in ("purchased_qty", "issued_qty", "returned_qty"):
            x[k] = r4(x[k])
        for k in ("purchased_value", "billed_net", "billed_vat", "issued_value"):
            x[k] = r2(x[k])
    boq = q(c, "SELECT i.project_id, l.boq_item_id, b.code boq_code, b.description, l.material_id, SUM(l.qty) qty, "
               "SUM(l.amount) amount FROM issue_lines l JOIN issues i ON i.id=l.issue_id LEFT JOIN boq_items b ON "
               "b.id=l.boq_item_id WHERE i.status='posted' AND i.date BETWEEN ? AND ? AND i.project_id IN (%s) "
               "GROUP BY i.project_id, l.boq_item_id, l.material_id" % (",".join("?" * len(pids)) or "NULL"),
            [frm, to] + pids)
    gl = []
    for pid in pids:
        cost = val(c, "SELECT SUM(l.debit-l.credit) FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id JOIN accounts "
                      "x ON x.id=l.account_id WHERE x.role='material_cost' AND l.project_id=? AND " + POSTED +
                   " AND v.date BETWEEN ? AND ?", (pid, frm, to))
        trading_in_project = val(c, "SELECT COUNT(*) FROM stock_ledger WHERE project_id=? AND doc_type IN ('TSALE','TRET')", (pid,))
        gl.append({"project_id": pid, "material_cost_books": r2(cost), "trading_moves_in_project": trading_in_project})
    rows = sorted(out.values(), key=lambda r: (r["project_id"], r["material_id"]))
    return {"rows": rows, "boq": boq, "books": gl,
            "totals": _sum(rows, "purchased_value", "billed_net", "billed_vat", "issued_value", "closing_value")}


def rep_trading(c, u, a):
    frm, to = a.get("from") or "0000-01-01", a.get("to") or today()
    pids = [p["id"] for p in q(c, "SELECT id FROM projects WHERE kind='trading'")]
    rec = [r for r in receipt_rows(c, a) if r["purpose"] == "trading"]
    moves = []
    for pid in pids:
        for m in q(c, "SELECT material_id, SUM(CASE WHEN doc_type IN ('GRN','PRC-IN','MTN-IN','OPENING') THEN qty_in ELSE 0 END) rq, "
                      "SUM(CASE WHEN doc_type IN ('GRN','PRC-IN','MTN-IN','OPENING') THEN value_in ELSE 0 END) rv, "
                      "SUM(CASE WHEN doc_type='TSALE' THEN qty_out ELSE 0 END) sq, SUM(CASE WHEN doc_type='TSALE' THEN value_out ELSE 0 END) sv, "
                      "SUM(CASE WHEN doc_type='TRET' THEN qty_in ELSE 0 END) tq, SUM(CASE WHEN doc_type='TRET' THEN value_in ELSE 0 END) tv, "
                      "SUM(CASE WHEN doc_type NOT IN ('GRN','PRC-IN','MTN-IN','OPENING','TSALE','TRET') THEN qty_in-qty_out ELSE 0 END) oq "
                      "FROM stock_ledger WHERE project_id=? AND date BETWEEN ? AND ? GROUP BY material_id", (pid, frm, to)):
            b = q1(c, "SELECT SUM(qty) q, SUM(value) v FROM stock_balances WHERE project_id=? AND material_id=?", (pid, m["material_id"]))
            moves.append({"project_id": pid, "material_id": m["material_id"], "received_qty": r4(m["rq"] or 0),
                          "received_value": r2(m["rv"] or 0), "sold_qty": r4(m["sq"] or 0), "cogs": r2((m["sv"] or 0) - (m["tv"] or 0)),
                          "returned_qty": r4(m["tq"] or 0), "other_qty": r4(m["oq"] or 0),
                          "closing_qty": r4(b["q"] or 0), "closing_value": r2(b["v"] or 0)})
    sales = q(c, "SELECT t.*, i.no invoice_no FROM trade_moves t JOIN invoices i ON i.id=t.invoice_id WHERE t.date BETWEEN ? AND ? "
                 "ORDER BY t.date, t.id", (frm, to))
    books = {}
    for role in ("trading_sales", "trading_returns", "cogs_trading"):
        books[role] = r2(val(c, "SELECT SUM(l.debit-l.credit) FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id JOIN "
                                "accounts x ON x.id=l.account_id WHERE x.role=? AND " + POSTED + " AND v.date BETWEEN ? AND ?",
                             (role, frm, to)))
    return {"rows": rec, "moves": moves, "sales": sales, "books": books,
            "totals": _sum(rec, "qty", "value", "net", "vat"),
            "gross_profit": r2(-books["trading_sales"] - books["trading_returns"] - books["cogs_trading"])}


def rep_supplier_purpose(c, u, a):
    rows = bill_rows(c, a)
    summ = {}
    for r in rows:
        k = (r["party_id"], r["purpose"])
        s = summ.setdefault(k, {"party_id": r["party_id"], "purpose": r["purpose"], "net": 0.0, "vat": 0.0, "payable": 0.0,
                                "paid": 0.0, "outstanding": 0.0, "bills": 0})
        for f in ("net", "vat", "payable", "paid", "outstanding"):
            s[f] = r2(s[f] + r[f])
        s["bills"] += 1
    by_party = {}
    for s in summ.values():
        by_party.setdefault(s["party_id"], 0)
        by_party[s["party_id"]] = r2(by_party[s["party_id"]] + s["outstanding"])
    check = [{"party_id": pid, "sum_of_purposes": tot, "open_bills": r2(sum(r2(b["payable"] - inv.invoice_paid(c, b["id"]))
                                                                           for b in _bills(c, {"party_id": pid}))),
              "ap_books": _ap_book(c, pid)} for pid, tot in by_party.items()]
    return {"rows": rows, "summary": sorted(summ.values(), key=lambda s: (s["party_id"], s["purpose"])), "check": check}


def rep_supplier(c, u, a):
    out = []
    for b in _bills(c, a):
        paid = inv.invoice_paid(c, b["id"])
        dn = r2(val(c, "SELECT SUM(a.amount) FROM allocations a JOIN vouchers v ON v.id=a.voucher_id WHERE a.invoice_id=? AND "
                       "a.active=1 AND a.payment_id IS NULL AND v.source='proc_return'", (b["id"],)))
        out.append({"invoice_id": b["id"], "no": b["no"], "date": b["date"], "party_id": b["party_id"],
                    "party_inv_no": b["party_inv_no"], "purpose": b.get("procurement_purpose") or "",
                    "subtotal": b["subtotal"], "vat": b["vat"], "total": b["total"], "payable": b["payable"],
                    "debit_notes": dn, "paid": r2(paid - dn), "balance": r2(b["payable"] - paid)})
    parties = sorted({r["party_id"] for r in out})
    if a.get("party_id"):
        parties = [int(a["party_id"])]
    bal = [{"party_id": pid, "open_bills": r2(sum(r["balance"] for r in out if r["party_id"] == pid)),
            "ap_books": _ap_book(c, pid),
            "advance": r2(__import__("api_finance").party_advance_balance(c, pid, "purchase"))} for pid in parties]
    return {"rows": out, "balances": bal, "totals": _sum(out, "subtotal", "vat", "total", "payable", "debit_notes", "paid", "balance")}


def rep_payments(c, u, a):
    cond, p = ["pm.kind='pay'", "pm.status='posted'"], []
    if a.get("party_id"):
        cond.append("pm.party_id=?")
        p.append(int(a["party_id"]))
    if a.get("from"):
        cond.append("pm.date>=?")
        p.append(a["from"])
    if a.get("to"):
        cond.append("pm.date<=?")
        p.append(a["to"])
    out = []
    for pm in q(c, "SELECT pm.*, x.name bank FROM payments pm LEFT JOIN accounts x ON x.id=pm.bank_account_id WHERE " +
                " AND ".join(cond) + " ORDER BY pm.date, pm.id", p):
        rows = q(c, "SELECT * FROM proc_pay_alloc WHERE payment_id=? AND active=1 ORDER BY id", (pm["id"],))
        base = {"payment_id": pm["id"], "payment_no": pm["no"], "date": pm["date"], "party_id": pm["party_id"],
                "bank": pm["bank"], "bank_account_id": pm["bank_account_id"], "net_paid": pm["net"], "tds": pm["tds"],
                "funding_purpose": pm.get("funding_purpose") or cc_kind(c, pm["project_id"]),
                "funding_project_id": pm["project_id"]}
        if rows:
            for r in rows:
                out.append(dict(base, invoice_id=r["invoice_id"], invoice_no=val(c, "SELECT no FROM invoices WHERE id=?", (r["invoice_id"],), "")
                                if r["invoice_id"] else "", purpose=r["purpose"], project_id=r["project_id"], amount=r["amount"],
                                kind=r["kind"], cross=r["kind"].endswith("_cross")))
        else:  # payments from before 2.19
            for al in q(c, "SELECT * FROM allocations WHERE payment_id=? AND active=1", (pm["id"],)):
                b = get(c, "invoices", al["invoice_id"])
                out.append(dict(base, invoice_id=b["id"], invoice_no=b["no"], purpose=_line_dest(c, b, {})[0],
                                project_id=b["project_id"], amount=al["amount"], kind="legacy", cross=False))
            if (pm["advance"] or 0) > 0.004:
                out.append(dict(base, invoice_id=None, invoice_no="", purpose=base["funding_purpose"],
                                project_id=pm["project_id"], amount=pm["advance"], kind="advance", cross=False))
    banks = {}
    for r in out:
        banks.setdefault(r["payment_id"], (r["bank_account_id"], r["net_paid"], r["tds"]))
    bank_tot = {}
    for _pid, (acc, net, _t) in banks.items():
        bank_tot[acc] = r2(bank_tot.get(acc, 0) + net)
    return {"rows": out, "totals": _sum(out, "amount"),
            "by_bank": [{"bank_account_id": k, "bank": val(c, "SELECT name FROM accounts WHERE id=?", (k,), ""), "paid": v,
                         "book_balance": r2(val(c, "SELECT opening_balance FROM accounts WHERE id=?", (k,)) +
                                            val(c, "SELECT SUM(l.debit-l.credit) FROM voucher_lines l JOIN vouchers v ON "
                                                   "v.id=l.voucher_id WHERE l.account_id=? AND " + POSTED, (k,)))}
                        for k, v in bank_tot.items()]}


def rep_stores(c, u, a):
    rows = q(c, "SELECT b.project_id, b.store_id, b.material_id, b.qty, b.value, COALESCE(p.kind,'') kind, s.name store "
                "FROM stock_balances b JOIN projects p ON p.id=b.project_id JOIN stores s ON s.id=b.store_id "
                "WHERE ABS(b.qty)>0.0001 OR ABS(b.value)>0.004 ORDER BY b.material_id, p.code")
    by = {}
    for r in rows:
        r["purpose"] = r["kind"] if r["kind"] in ("trading", "general") else "project"
        x = by.setdefault(r["material_id"], {"material_id": r["material_id"], "project_qty": 0.0, "project_value": 0.0,
                                             "trading_qty": 0.0, "trading_value": 0.0, "general_qty": 0.0, "general_value": 0.0})
        x[r["purpose"] + "_qty"] = r4(x[r["purpose"] + "_qty"] + r["qty"])
        x[r["purpose"] + "_value"] = r2(x[r["purpose"] + "_value"] + r["value"])
    if a.get("material_id"):
        rows = [r for r in rows if r["material_id"] == int(a["material_id"])]
    return {"rows": rows, "by_material": list(by.values()),
            "totals": {k: r2(sum(x[k] for x in by.values())) for k in ("project_value", "trading_value", "general_value")}}


def rep_vat(c, u, a):
    rows = []
    for b in _bills(c, a):
        dests = invoice_dests(c, b)
        dn_vat = r2(-val(c, "SELECT SUM(vat) FROM proc_inv_alloc WHERE invoice_id=? AND method='return' AND status='posted'", (b["id"],)))
        alloc_vat = r2(sum(d["vat"] for d in dests))
        row = {"invoice_id": b["id"], "no": b["no"], "date": b["date"], "party_id": b["party_id"],
               "party_inv_no": b["party_inv_no"], "pan": val(c, "SELECT pan FROM parties WHERE id=?", (b["party_id"],), ""),
               "taxable": r2(val(c, "SELECT SUM(amount) FROM invoice_lines WHERE invoice_id=? AND vat_rate>0", (b["id"],))),
               "invoice_vat": b["vat"], "returned_vat": dn_vat, "allocated_vat": alloc_vat,
               "difference": r2(b["vat"] - alloc_vat), "method": "/".join(sorted({d["method"] for d in dests}))}
        for p in DEST:
            row[p + "_vat"] = r2(sum(d["vat"] for d in dests if d["purpose"] == p))
            row[p + "_net"] = r2(sum(d["net"] for d in dests if d["purpose"] == p))
        rows.append(row)
    frm, to = a.get("from") or "0000-01-01", a.get("to") or today()
    gl_in = r2(val(c, "SELECT SUM(l.debit-l.credit) FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id JOIN accounts x "
                      "ON x.id=l.account_id WHERE x.role='vat_input' AND " + POSTED + " AND v.date BETWEEN ? AND ?", (frm, to)))
    gl_out = r2(-val(c, "SELECT SUM(l.debit-l.credit) FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id JOIN accounts x "
                       "ON x.id=l.account_id WHERE x.role='vat_output' AND " + POSTED + " AND v.date BETWEEN ? AND ?", (frm, to)))
    tsales = q1(c, "SELECT SUM(CASE WHEN kind='sale' THEN vat ELSE 0 END) s, SUM(CASE WHEN kind='return' THEN vat ELSE 0 END) r "
                   "FROM trade_moves WHERE date BETWEEN ? AND ?", (frm, to))
    tot = _sum(rows, "taxable", "invoice_vat", "returned_vat", "allocated_vat", "difference", "project_vat", "trading_vat", "general_vat")
    return {"rows": rows, "totals": tot, "vat_input_books": gl_in, "vat_output_books": gl_out,
            "trading_sales_vat": r2(tsales["s"] or 0), "trading_return_vat": r2(tsales["r"] or 0),
            "note": "Project / trading / general VAT are management views. The VAT return is filed once, for the "
                    "registered company, from the VAT purchase and sales books. The purpose does not decide whether "
                    "input VAT may be claimed."}


def rep_unallocated(c, u, a):
    rows = []
    for g in q(c, "SELECT * FROM grn WHERE procurement_purpose='mixed' AND status IN ('draft','posted') ORDER BY date"):
        for l in q(c, "SELECT * FROM grn_lines WHERE grn_id=?", (g["id"],)):
            if g["status"] == "draft":
                done = val(c, "SELECT SUM(qty) FROM proc_alloc WHERE grn_line_id=? AND status='draft'", (l["id"],))
            else:
                done = sum(d["qty"] for d in _dest_balance(c, l["id"]).values())
            acc = _accepted(l)
            if abs(acc - done) > Q4:
                rows.append({"type": "grn", "id": g["id"], "no": g["no"] or "Draft #%d" % g["id"], "date": g["date"],
                             "party_id": g["vendor_id"], "material_id": l["material_id"], "qty": r4(acc),
                             "allocated": r4(done), "unallocated_qty": r4(acc - done),
                             "unallocated_value": r2((acc - done) * (l["landed_rate"] or l["rate"] or 0)), "status": g["status"]})
    for b in q(c, "SELECT * FROM invoices WHERE kind='purchase' AND status='posted' AND procurement_purpose='mixed'"):
        dests = invoice_dests(c, b)
        diff_n = r2(b["subtotal"] - sum(d["net"] for d in dests))
        diff_v = r2(b["vat"] - sum(d["vat"] for d in dests))
        if abs(diff_n) > 0.004 or abs(diff_v) > 0.004:
            rows.append({"type": "invoice", "id": b["id"], "no": b["no"], "date": b["date"], "party_id": b["party_id"],
                         "unallocated_value": diff_n, "unallocated_vat": diff_v, "status": b["status"]})
    legacy = {"grn": val(c, "SELECT COUNT(*) FROM grn WHERE status='posted' AND procurement_purpose IS NULL"),
              "invoice": val(c, "SELECT COUNT(*) FROM invoices WHERE kind='purchase' AND status='posted' AND procurement_purpose IS NULL")}
    rec = [r for r in receipt_rows(c, a) if not r["reviewed"]][:300]
    return {"rows": rows, "legacy_counts": legacy, "legacy": rec,
            "note": "Documents posted before 2.19 keep the classification of the store they went into until someone "
                    "reviews them (Review purpose). Nothing is reclassified automatically."}


def rep_reconcile(c, u, a):
    out = []
    for b in _bills(c, a):
        dests = invoice_dests(c, b)
        paid = inv.invoice_paid(c, b["id"])
        dn = q1(c, "SELECT SUM(net) n, SUM(vat) v FROM proc_inv_alloc WHERE invoice_id=? AND method='return' AND status='posted'", (b["id"],))
        settled = r2(val(c, "SELECT SUM(amount) FROM proc_pay_alloc WHERE invoice_id=? AND active=1", (b["id"],)))
        has_dest_pay = bool(val(c, "SELECT COUNT(*) FROM proc_pay_alloc WHERE invoice_id=?", (b["id"],)))
        row = {"invoice_id": b["id"], "no": b["no"], "date": b["date"], "party_id": b["party_id"],
               "party_inv_no": b["party_inv_no"], "purpose": b.get("procurement_purpose") or "",
               "subtotal": b["subtotal"], "vat": b["vat"], "payable": b["payable"],
               "alloc_net": r2(sum(d["net"] for d in dests)), "alloc_vat": r2(sum(d["vat"] for d in dests)),
               "alloc_payable": r2(sum(d["payable"] for d in dests)), "returns": r2(-(dn["n"] or 0) - (dn["v"] or 0)),
               "paid": paid, "paid_by_destination": settled if has_dest_pay else None, "outstanding": r2(b["payable"] - paid),
               "destinations": len(dests)}
        problems = []
        if abs(row["alloc_net"] - b["subtotal"]) > 0.004:
            problems.append("net")
        if abs(row["alloc_vat"] - b["vat"]) > 0.004:
            problems.append("VAT")
        if abs(row["alloc_payable"] - b["payable"]) > 0.004:
            problems.append("payable")
        uncovered = val(c, "SELECT COUNT(*) FROM allocations WHERE invoice_id=? AND active=1 AND id NOT IN "
                           "(SELECT allocation_id FROM proc_pay_alloc WHERE allocation_id IS NOT NULL AND active=1)", (b["id"],))
        if has_dest_pay and not uncovered and abs(settled - paid) > 0.01:
            problems.append("payments")
        row["status"] = "ok" if not problems else "check " + ", ".join(problems)
        out.append(row)
    ap = _ap_book(c, int(a["party_id"]) if a.get("party_id") else None)
    return {"rows": out, "totals": _sum(out, "subtotal", "vat", "payable", "alloc_net", "alloc_vat", "paid", "outstanding"),
            "ap_books": ap, "open_bills": r2(sum(r["outstanding"] for r in _all_open(c, a)))}


def _all_open(c, a):
    return [{"outstanding": r2(b["payable"] - inv.invoice_paid(c, b["id"]))}
            for b in _bills(c, {"party_id": a.get("party_id")})]


REPORTS = {"mixed": rep_mixed, "project_cost": rep_project_cost, "trading": rep_trading,
           "supplier_purpose": rep_supplier_purpose, "supplier": rep_supplier, "payments": rep_payments,
           "stores": rep_stores, "vat": rep_vat, "unallocated": rep_unallocated, "reconcile": rep_reconcile}


@api("proc.invoice_alloc", "procurement", "view")
def invoice_alloc(c, u, a):
    b = get(c, "invoices", int(a["invoice_id"]), "Bill")
    if b["kind"] != "purchase" or b["status"] != "posted":
        return {"dests": [], "lines": []}
    rows = bill_rows(c, {"invoice_id": b["id"]})
    lines = q(c, "SELECT * FROM proc_inv_alloc WHERE invoice_id=? AND status='posted' ORDER BY id", (b["id"],))
    pays = q(c, "SELECT p.*, pm.no payment_no, pm.date FROM proc_pay_alloc p LEFT JOIN payments pm ON pm.id=p.payment_id "
                "WHERE p.invoice_id=? AND p.active=1 ORDER BY p.id", (b["id"],))
    return {"dests": rows, "lines": lines, "payments": pays}


@api("proc.dests", "procurement", "view")
def proc_dests(c, u, a):
    """Destinations of the GRN lines a bill can take (to bill one destination per line)."""
    out = []
    for lid in a.get("grn_line_ids") or []:
        for k, d in _dest_balance(c, int(lid)).items():
            x = q1(c, "SELECT id FROM proc_alloc WHERE grn_line_id=? AND purpose=? AND project_id=? AND store_id=? AND "
                      "status='posted' AND qty>0 ORDER BY id LIMIT 1", (int(lid), k[0], k[1], k[2]))
            billed = (_dest_invoiced(c, int(lid)).get(k) or {}).get("qty") or 0
            out.append({"grn_line_id": int(lid), "proc_alloc_id": x["id"] if x else None, "purpose": k[0],
                        "project_id": k[1], "store_id": k[2], "qty": d["qty"], "left": r4(d["qty"] - billed)})
    return out


# ───────────────────────── connect to the existing engine ─────────────────────────
def _fix_doc_dispatch():
    """2.16 bug: the contract-documents screen (api_ai) registered endpoints also named doc.get, doc.list and
    doc.delete, hiding the generic document endpoints the store and purchase screens call. Dispatch by the
    'type' argument: store documents go to the generic endpoint, contract documents to the AI one."""
    for name, generic in (("doc.get", inv.doc_get), ("doc.list", inv.doc_list), ("doc.delete", inv.doc_delete)):
        cur = inv.FUNCS.get(name)
        if not cur or getattr(cur[0], "_bco219", False):
            continue
        ai_f, ai_mod, ai_act = cur[0], cur[1], cur[2]

        def dispatch(c, u, a, _g=generic, _f=ai_f, _m=ai_mod, _a=ai_act):
            if a.get("type") in inv.DOCS:
                return _g(c, u, a)
            if _m:
                require(u, _m, _a)
            return _f(c, u, a)
        dispatch._bco219 = True
        inv.FUNCS[name] = (dispatch, None, None, False)


def _wrap_all():
    _fix_doc_dispatch()
    _wrap("grn.post", _grn_post_w)
    _wrap("grn.cancel", _grn_cancel_w)
    _wrap("issue.post", _issue_post_w)
    _wrap("invoice.post", _inv_post_w)
    _wrap("invoice.cancel", _inv_cancel_w)
    _wrap("payment.create", _pay_create_w)
    _wrap("payment.cancel", _pay_cancel_w)
    _wrap("advance.adjust", _adv_adjust_w)
    _patch_advance_balance()
    _extend_lists()
    try:  # the 2.18 dashboard counts construction projects only
        import api_insight as I
        if not getattr(I._project_rows, "_bco219", False):
            orig = I._project_rows

            def _project_rows(c, pid=None):
                skip = {r["id"] for r in q(c, "SELECT id FROM projects WHERE kind IN ('trading','general')")}
                return [r for r in orig(c, pid) if r["id"] not in skip]
            _project_rows._bco219 = True
            I._project_rows = _project_rows
    except Exception:
        pass
    try:
        lk = inv.FUNCS["lookups"]
        if not getattr(lk[0], "_bco219", False):
            def lookups3(c, u, a):
                r = lk[0](c, u, a)
                try:
                    kinds = {x["id"]: x["kind"] for x in q(c, "SELECT id, kind FROM projects")}
                    for p in r.get("projects") or []:
                        p["kind"] = kinds.get(p["id"]) or "project"
                except Exception:
                    pass
                return r
            lookups3._bco219 = True
            inv.FUNCS["lookups"] = (lookups3, lk[1], lk[2], lk[3])
    except Exception:
        pass


_wrap_all()
