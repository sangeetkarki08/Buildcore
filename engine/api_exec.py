"""
Execution modes, approve-then-post, equipment cost and returns (BuildCore 2.21).

How a project is executed decides how it is paid, costed and posted. This module adds, ON TOP of the
existing documents and the one general ledger:

  1. The posting gate. Operational costs (DPR labour and machine charges, fuel and spares issued to
     equipment, internal hire runs, service and hire bills, small-asset hire, EMI) are no longer posted
     the moment the site acts. post_voucher() still builds the complete, balanced entry, but it is
     PARKED (status 'submitted', no number) and waits in the accounts queue: the operational owner
     approves it, then accounts posts it (2.20 role actions Approve and Post). Parked entries are
     outside every report and balance, because every report reads status posted / reversed only.
     Each source can be switched back to direct posting in the settings.
  2. Execution plan per project: each BOQ item (or a share of it) by direct labour, labour supply
     subcontract (piece rate), item-rate subcontract with our material and equipment, or back-to-back.
  3. Subcontract work orders, material issued to subcontractors (held as a recoverable asset), running
     bills with previous / this / cumulative quantities and recoveries of material (bill rate plus
     overhead, or one agreed rate), equipment, advance and retention; posted as one purchase bill so
     payments, TDS, ageing and the party ledger keep working. Material reconciliation per subcontract.
  4. Rental deductions: servicing, repairs, spares and fuel we provide on a hired machine are deducted
     from the owner's hire bill (credited back to the expense they were first charged to).
  5. Owned equipment finance (down payment, loan, EMI as paid) and cost per hour / km / day / output,
     cash view and economic view side by side, utilisation and idle time by cause.
  6. Delays by responsibility (employer / own / neutral / concurrent) with claimable idle cost and
     liquidated damages exposure.
  7. Returns: company ROA / ROE with the DuPont split, return per machine, small-asset pools
     (mixers, tools, scaffolding, shuttering) with deployment, monthly hire charge and return.

Also fixes the fixed-asset module's posting adapter (every fa.* posting failed with a TypeError).
Like 2.17-2.20 this is an add-on: new tables, optional columns and wrappers; no existing row is changed.
"""
import calendar
import sys
import threading
from datetime import date, timedelta

import core
from core import (ApiError, EPS, audit, get, ins, inventory_role, material, need, next_no, now, num, q, q1, r2, r4,
                  setting, stock_in, stock_out, today, upd, val)
import api_inventory as inv
from api_inventory import api

VERSION = "2.21.0"
POSTED = "v.status IN ('posted','reversed')"

SCHEMA = """
CREATE TABLE IF NOT EXISTS post_queue(voucher_id INTEGER PRIMARY KEY, source TEXT, source_id INTEGER, gate TEXT,
  module TEXT, stage TEXT DEFAULT 'review', label TEXT, project_id INTEGER, amount REAL DEFAULT 0, vtype TEXT,
  created_by INTEGER, created_at TEXT, approved_by INTEGER, approved_at TEXT, note TEXT, returned_by INTEGER,
  returned_at TEXT, posted_by INTEGER, posted_at TEXT, posted_no TEXT);
CREATE INDEX IF NOT EXISTS ix_pq_stage ON post_queue(stage);
CREATE TABLE IF NOT EXISTS exec_plan(id INTEGER PRIMARY KEY, project_id INTEGER, boq_item_id INTEGER,
  share_pct REAL DEFAULT 100, work_mode TEXT, equip_mode TEXT, sc_order_id INTEGER, remarks TEXT, ts TEXT);
CREATE INDEX IF NOT EXISTS ix_ep_p ON exec_plan(project_id);
CREATE TABLE IF NOT EXISTS sc_orders(id INTEGER PRIMARY KEY, no TEXT, project_id INTEGER, party_id INTEGER,
  type TEXT, title TEXT, date TEXT, start_date TEXT, end_date TEXT, retention_pct REAL DEFAULT 0,
  advance REAL DEFAULT 0, vat_rate REAL DEFAULT 0, recovery_basis TEXT DEFAULT 'bill_oh',
  overhead_pct REAL DEFAULT 0, equip_terms TEXT, status TEXT DEFAULT 'draft', contract_id INTEGER, remarks TEXT,
  created_by INTEGER, approved_by INTEGER, ts TEXT);
CREATE TABLE IF NOT EXISTS sc_order_items(id INTEGER PRIMARY KEY, order_id INTEGER, boq_item_id INTEGER,
  description TEXT, unit TEXT, qty REAL DEFAULT 0, rate REAL DEFAULT 0);
CREATE TABLE IF NOT EXISTS sc_order_mats(id INTEGER PRIMARY KEY, order_id INTEGER, material_id INTEGER,
  order_item_id INTEGER, per_unit REAL DEFAULT 0, wastage_pct REAL DEFAULT 0, fixed_rate REAL DEFAULT 0);
CREATE TABLE IF NOT EXISTS sc_moves(id INTEGER PRIMARY KEY, no TEXT, order_id INTEGER, project_id INTEGER,
  store_id INTEGER, date TEXT, kind TEXT, material_id INTEGER, qty REAL DEFAULT 0, rate REAL DEFAULT 0,
  value REAL DEFAULT 0, voucher_id INTEGER, status TEXT DEFAULT 'posted', remarks TEXT, created_by INTEGER, ts TEXT);
CREATE INDEX IF NOT EXISTS ix_scm_o ON sc_moves(order_id, status);
CREATE TABLE IF NOT EXISTS sc_bills(id INTEGER PRIMARY KEY, no TEXT, order_id INTEGER, project_id INTEGER,
  party_id INTEGER, date TEXT, period_to TEXT, party_bill_no TEXT, status TEXT DEFAULT 'draft',
  gross REAL DEFAULT 0, material_recovery REAL DEFAULT 0, material_cost REAL DEFAULT 0,
  equipment_recovery REAL DEFAULT 0, other_deduction REAL DEFAULT 0, advance_recovery REAL DEFAULT 0,
  retention REAL DEFAULT 0, vat REAL DEFAULT 0, net REAL DEFAULT 0, invoice_id INTEGER, remarks TEXT,
  note TEXT, created_by INTEGER, submitted_by INTEGER, approved_by INTEGER, posted_by INTEGER, ts TEXT);
CREATE TABLE IF NOT EXISTS sc_bill_items(id INTEGER PRIMARY KEY, bill_id INTEGER, order_item_id INTEGER,
  prev_qty REAL DEFAULT 0, qty REAL DEFAULT 0, rate REAL DEFAULT 0, amount REAL DEFAULT 0);
CREATE TABLE IF NOT EXISTS sc_bill_recoveries(id INTEGER PRIMARY KEY, bill_id INTEGER, kind TEXT,
  material_id INTEGER, equipment_id INTEGER, description TEXT, qty REAL DEFAULT 0, cost_rate REAL DEFAULT 0,
  cost REAL DEFAULT 0, rate REAL DEFAULT 0, amount REAL DEFAULT 0);
CREATE TABLE IF NOT EXISTS rent_deductions(id INTEGER PRIMARY KEY, agreement_id INTEGER, equipment_id INTEGER,
  date TEXT, kind TEXT, description TEXT, amount REAL DEFAULT 0, account_id INTEGER, source TEXT,
  source_id INTEGER, invoice_id INTEGER, status TEXT DEFAULT 'open', created_by INTEGER, ts TEXT);
CREATE INDEX IF NOT EXISTS ix_rd_ag ON rent_deductions(agreement_id, status);
CREATE TABLE IF NOT EXISTS eq_finance(equipment_id INTEGER PRIMARY KEY, price REAL DEFAULT 0,
  down_payment REAL DEFAULT 0, loan_amount REAL DEFAULT 0, lender TEXT, emi REAL DEFAULT 0,
  emi_count INTEGER DEFAULT 0, first_emi_date TEXT, interest_rate REAL DEFAULT 0, life_units REAL DEFAULT 0,
  basis TEXT DEFAULT 'hour', output_unit TEXT, market_rate REAL DEFAULT 0, notes TEXT, ts TEXT);
CREATE TABLE IF NOT EXISTS eq_emi(id INTEGER PRIMARY KEY, equipment_id INTEGER, date TEXT, amount REAL DEFAULT 0,
  principal REAL DEFAULT 0, interest REAL DEFAULT 0, bank_account_id INTEGER, voucher_id INTEGER,
  remarks TEXT, created_by INTEGER, ts TEXT);
CREATE TABLE IF NOT EXISTS sa_pools(id INTEGER PRIMARY KEY, code TEXT, name TEXT, class TEXT, unit TEXT,
  qty REAL DEFAULT 0, cost REAL DEFAULT 0, life_months INTEGER DEFAULT 36, residual_pct REAL DEFAULT 0,
  rate REAL DEFAULT 0, rate_basis TEXT DEFAULT 'day', purchase_date TEXT, active INTEGER DEFAULT 1, notes TEXT);
CREATE TABLE IF NOT EXISTS sa_moves(id INTEGER PRIMARY KEY, pool_id INTEGER, project_id INTEGER, date TEXT,
  kind TEXT, qty REAL DEFAULT 0, value REAL DEFAULT 0, remarks TEXT, created_by INTEGER, ts TEXT);
CREATE TABLE IF NOT EXISTS sa_runs(id INTEGER PRIMARY KEY, month TEXT, pool_id INTEGER, project_id INTEGER,
  unit_days REAL DEFAULT 0, amount REAL DEFAULT 0, voucher_id INTEGER, ts TEXT);
"""
COLUMNS = {"hire_agreements": {"maint_terms": "TEXT", "fuel_terms": "TEXT", "operator_terms": "TEXT"},
           "dpr_delays": {"responsibility": "TEXT"},
           "events": {"responsibility": "TEXT"}}

# accounts the new mechanisms need; added only when no account carries the role yet
GROUPS = [("L4", "Loans & Borrowings", "liability", "L")]
ACCOUNTS = [("1205", "Material with Subcontractors (Recoverable)", "asset", "A3", "subcon_material"),
            ("5006", "Material Recovery Margin - Subcontractors", "expense", "X1", "subcon_recovery_margin"),
            ("4005", "Recoveries from Subcontractors", "income", "I", "subcon_other_recovery"),
            ("2301", "Equipment Loans", "liability", "L4", "equipment_loan"),
            ("5203", "Interest on Equipment Loans", "expense", "X3", "interest_expense")]

WORK_MODES = [("direct", "Direct labour"), ("labour_sc", "Labour supply subcontract (piece rate)"),
              ("supplied_sc", "Item-rate subcontract, our material & equipment"),
              ("b2b_sc", "Back-to-back subcontract")]
EQUIP_MODES = [("owned", "Own equipment"), ("rented", "Rented equipment"), ("sub", "Subcontractor's equipment"),
               ("mixed", "Mixed"), ("none", "No equipment")]
SC_TYPES = [("labour", "Labour supply (piece rate)"), ("supplied", "Item rate, material & equipment by us"),
            ("b2b", "Back-to-back (subcontractor supplies all)")]
SC_TYPE_MODE = {"labour": "labour_sc", "supplied": "supplied_sc", "b2b": "b2b_sc"}
TERMS = [("deduct", "We provide it, deduct from rent"), ("ours", "We bear it"), ("owner", "Owner bears it")]
RESP = [("employer", "Employer"), ("contractor", "Own (contractor)"), ("neutral", "Neutral"),
        ("concurrent", "Concurrent")]
# DPR delay categories (pages_project.js DELAY_CATS) -> who is responsible, when nobody said otherwise
CAT_RESP = {"weather": "neutral", "geology": "neutral", "access": "employer", "drawing": "employer",
            "consultant_instruction": "employer", "employer_instruction": "employer",
            "equipment_breakdown": "contractor", "material_shortage": "contractor",
            "labour_shortage": "contractor", "other": "contractor"}
RESP_FLAGS = {"employer": (1, 1, 0), "contractor": (0, 0, 0), "neutral": (1, 0, 0), "concurrent": (1, 0, 1)}
SA_CLASSES = [("mixer", "Mixers & vibrators"), ("tools", "Tools"), ("scaffolding", "Scaffolding"),
              ("shuttering", "Shuttering / formwork"), ("props", "Props & jacks"), ("other", "Other small assets")]

# ───────────────────────────── the posting gate ─────────────────────────────
GATES = [("dpr", "DPR labour and machine charges", "project", "approved"),
         ("issue_equipment", "Fuel and spares issued to equipment", "equipment", "review"),
         ("internal_billing", "Internal hire runs (own machines)", "equipment", "review"),
         ("service_bill", "Service, repair and expense bills (not for goods received)", "procurement", "review"),
         ("hire_bill", "Hire bills of rented machines", "equipment", "review"),
         ("sa_hire", "Small-asset hire runs", "assets", "review"),
         ("emi", "Equipment EMI payments", "accounts", "approved")]
GATE_META = {g[0]: g for g in GATES}
_LOCAL = threading.local()
_ORIG = {}


def gate_on(c, key):
    v = setting(c, "gate_" + key)
    return v != "0"  # on unless switched off


class bypass:
    """Inside this block post_voucher posts directly (used when accounts itself posts)."""
    def __enter__(self):
        _LOCAL.depth = getattr(_LOCAL, "depth", 0) + 1

    def __exit__(self, *a):
        _LOCAL.depth -= 1


def _gate_for(c, source, source_id, lines):
    if getattr(_LOCAL, "depth", 0):
        return None
    if source == "dpr":
        key = "dpr"
    elif source == "issue":
        if not any(l.get("equipment_id") for l in lines):
            return None
        key = "issue_equipment"
    elif source == "internal_billing":
        key = "internal_billing"
    elif source in ("sa_hire", "emi"):
        key = source
    elif source == "invoice" and source_id:
        i = q1(c, "SELECT * FROM invoices WHERE id=?", (source_id,))
        if not i or i["kind"] != "purchase" or (i.get("procurement_purpose") or "") or i["source"] == "sc_bill":
            return None
        if val(c, "SELECT COUNT(*) FROM invoice_lines WHERE invoice_id=? AND grn_line_id IS NOT NULL", (source_id,)):
            return None
        key = "hire_bill" if i["source"] == "hire" else "service_bill"
    else:
        return None
    return key if gate_on(c, key) else None


def _unnumber(c, no):
    """Give back a document number if it was the last one issued, so posted numbers have no gaps."""
    try:
        doc, fy, n = no.split("/")
        n = int(n)
    except (AttributeError, ValueError):
        return
    c.execute("UPDATE sequences SET next=? WHERE doc_type=? AND fy=? AND next=?", (n, doc, fy, n + 1))


def gated_post_voucher(c, user, vtype, d, narration, lines, project_id=None, source="manual", source_id=None,
                       party_id=None, ref_no=None, status="posted"):
    orig = _ORIG["post"]
    key = _gate_for(c, source, source_id, lines) if status == "posted" else None
    if not key:
        return orig(c, user, vtype, d, narration, lines, project_id=project_id, source=source, source_id=source_id,
                    party_id=party_id, ref_no=ref_no, status=status)
    vid = orig(c, user, vtype, d, narration, lines, project_id=project_id, source=source, source_id=source_id,
               party_id=party_id, ref_no=ref_no, status="submitted")
    if not vid:
        return vid
    v = q1(c, "SELECT * FROM vouchers WHERE id=?", (vid,))
    _unnumber(c, v["no"])
    upd(c, "vouchers", vid, {"no": None, "approved_by": None})
    g = GATE_META[key]
    module = g[2]
    if key == "service_bill" and val(c, "SELECT COUNT(*) FROM invoice_lines WHERE invoice_id=? AND equipment_id IS NOT NULL",
                                     (source_id,)):
        module = "equipment"
    c.execute("INSERT OR REPLACE INTO post_queue(voucher_id, source, source_id, gate, module, stage, label, project_id, "
              "amount, vtype, created_by, created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
              (vid, source, source_id, key, module, g[3], narration, project_id, v["total"], vtype,
               user["id"] if user else None, now()))
    return vid


def fa_post_voucher(c, u, head, lines):
    """The fixed-asset module calls post_voucher(c, u, head, lines); core takes the fields one by one."""
    return core.post_voucher(c, u, head.get("type") or "journal", head["date"], head.get("narration") or "",
                             lines, project_id=head.get("project_id"), source=head.get("source") or "fa",
                             source_id=head.get("source_id"), party_id=head.get("party_id"), ref_no=head.get("ref_no"))


def _install_gate():
    cur = core.post_voucher
    if getattr(cur, "_bco221", False):
        orig = _ORIG["post"]
    else:
        orig = _ORIG.setdefault("post", cur)
        gated_post_voucher._bco221 = True
    for name, m in list(sys.modules.items()):
        if not name or m is None:
            continue
        if getattr(m, "post_voucher", None) is orig:
            try:
                setattr(m, "post_voucher", gated_post_voucher)
            except Exception:
                pass
    fa = sys.modules.get("api_fa")
    if fa is not None and not getattr(getattr(fa, "post_voucher", None), "_bco221", False):
        fa_post_voucher._bco221 = True
        fa.post_voucher = fa_post_voucher
    P = sys.modules.get("api_project")
    if P is not None and hasattr(P, "unpost_dpr") and not getattr(P.unpost_dpr, "_bco221", False):
        o = P.unpost_dpr

        def unpost_dpr(c, u, d, reason, _o=o):
            _drop_parked(c, "dpr", d["id"])
            return _o(c, u, d, reason)
        unpost_dpr._bco221 = True
        P.unpost_dpr = unpost_dpr


def _drop_parked(c, source, source_id):
    for v in q(c, "SELECT id FROM vouchers WHERE source=? AND source_id=? AND status='submitted'", (source, source_id)):
        c.execute("DELETE FROM voucher_lines WHERE voucher_id=?", (v["id"],))
        c.execute("DELETE FROM vouchers WHERE id=?", (v["id"],))
        c.execute("UPDATE post_queue SET stage='withdrawn' WHERE voucher_id=?", (v["id"],))


# ─────────── fine-grained rights from the 2.20 role templates (view/create/.../post) ───────────
FINE = ("create", "submit", "post", "export", "delete")
MAPBACK = {"post": "approve", "submit": "edit", "create": "edit", "delete": "approve", "export": "view"}


def allowed(c, u, module, action):
    if not u:
        return False
    if u.get("role") == "admin" or u.get("system"):
        return True
    perms = None
    try:
        import api_workspace as W
        t = W.roles(c).get(u["role"])
        if t:
            perms = set(t["perms"].get(module) or ())
    except Exception:
        perms = None
    if perms is None:
        perms = set(core.ROLES.get(u["role"], {}).get(module, set()))
    if action in perms:
        return True
    if perms & set(FINE):          # the template uses the fine verbs: take them literally
        return False
    return MAPBACK.get(action) in perms


def need_right(c, u, module, action, what):
    if not allowed(c, u, module, action):
        raise ApiError("Your role cannot %s %s (needs '%s' on %s in Administration > Users and roles)." %
                       (action, what, action, module))


def _not_maker(u, maker, what):
    if maker and u.get("id") == maker and u.get("role") != "admin":
        raise ApiError("Another person must %s what you raised yourself." % what)


# ───────────────────────────── init ─────────────────────────────
def init_exec(c):
    c.executescript(SCHEMA)
    for table, cols in COLUMNS.items():
        have = {r[1] for r in c.execute("PRAGMA table_info(%s)" % table)}
        if not have:
            continue
        for col, typ in cols.items():
            if col not in have:
                c.execute("ALTER TABLE %s ADD COLUMN %s %s" % (table, col, typ))
    if val(c, "SELECT COUNT(*) FROM account_groups"):
        _ensure_accounts(c)
    _install_gate()
    _wrap_all()
    try:
        import api_workspace as W
        W.COMPANY_FNS.update({"ret.company"})
    except Exception:
        pass


def _ensure_accounts(c):
    for code, name, typ, parent in GROUPS:
        if not q1(c, "SELECT id FROM account_groups WHERE code=?", (code,)):
            p = q1(c, "SELECT id FROM account_groups WHERE code=?", (parent,)) or \
                q1(c, "SELECT id FROM account_groups WHERE type=? ORDER BY id", (typ,))
            ins(c, "account_groups", {"code": code, "name": name, "type": typ, "parent_id": p["id"] if p else None})
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


def acct(c, role):
    _ensure_accounts(c)
    return core.role_account(c, role)


# ───────────────────────────── accounts posting queue ─────────────────────────────
@api("exec.meta")
def exec_meta(c, u, a):
    mods = ("accounts", "equipment", "project", "procurement", "commercial", "inventory", "assets")
    return {"version": VERSION, "work_modes": WORK_MODES, "equip_modes": EQUIP_MODES, "sc_types": SC_TYPES,
            "terms": TERMS, "resp": RESP, "sa_classes": SA_CLASSES, "cat_resp": CAT_RESP,
            "gates": [{"key": g[0], "label": g[1], "module": g[2], "on": gate_on(c, g[0])} for g in GATES],
            "rights": {m: [x for x in ("view", "create", "edit", "submit", "approve", "post") if allowed(c, u, m, x)]
                       for m in mods}}


@api("gate.save", "accounts", "approve")
def gate_save(c, u, a):
    for g in GATES:
        if g[0] in (a.get("gates") or {}):
            on = "1" if a["gates"][g[0]] in (1, "1", True) else "0"
            c.execute("INSERT OR REPLACE INTO settings(key, value) VALUES(?,?)", ("gate_" + g[0], on))
    audit(c, u, "save", "settings", None, {"gates": a.get("gates")})
    return exec_meta(c, u, {})["gates"]


def _queue_rows(c, where="", p=()):
    rows = q(c, "SELECT pq.*, v.date, v.narration, v.type, v.status vstatus, p.code pcode, us.name created_name, "
                "ap.name approved_name FROM post_queue pq JOIN vouchers v ON v.id=pq.voucher_id "
                "LEFT JOIN projects p ON p.id=pq.project_id LEFT JOIN users us ON us.id=pq.created_by "
                "LEFT JOIN users ap ON ap.id=pq.approved_by WHERE 1=1 " + where + " ORDER BY v.date, pq.voucher_id", p)
    for r in rows:
        r["gate_label"] = GATE_META.get(r["gate"], (0, r["gate"]))[1]
        r["age_days"] = (date.today() - date.fromisoformat((r["created_at"] or today())[:10])).days
    return rows


@api("pq.list")
def pq_list(c, u, a):
    """Entries waiting for approval or posting (stage review / approved / returned), or the posted history."""
    st = a.get("stage") or "open"
    if st == "open":
        rows = _queue_rows(c, "AND v.status='submitted' AND pq.stage IN ('review','approved','returned')")
    elif st == "posted":
        rows = _queue_rows(c, "AND pq.stage='posted' AND v.date>=?", (a.get("from") or "0000",))
    else:
        rows = _queue_rows(c, "AND v.status='submitted' AND pq.stage=?", (st,))
    if a.get("project_id"):
        rows = [r for r in rows if str(r["project_id"]) == str(a["project_id"])]
    for r in rows:
        r["can_approve"] = r["stage"] in ("review", "returned") and allowed(c, u, r["module"], "approve") and \
            (r["created_by"] != u["id"] or u["role"] == "admin")
        r["can_post"] = r["stage"] == "approved" and allowed(c, u, "accounts", "post") and \
            (r["created_by"] != u["id"] or u["role"] == "admin")
    return rows


@api("pq.summary")
def pq_summary(c, u, a):
    rows = pq_list(c, u, {"stage": "open"})
    oldest = max([r["age_days"] for r in rows], default=0)
    return {"review": sum(1 for r in rows if r["stage"] in ("review", "returned")),
            "approved": sum(1 for r in rows if r["stage"] == "approved"),
            "amount": r2(sum(r["amount"] or 0 for r in rows)), "oldest_days": oldest,
            "mine_to_approve": sum(1 for r in rows if r["can_approve"]),
            "mine_to_post": sum(1 for r in rows if r["can_post"])}


@api("pq.get")
def pq_get(c, u, a):
    r = _queue_rows(c, "AND pq.voucher_id=?", (int(a["id"]),))
    if not r:
        raise ApiError("Entry not found.")
    r = r[0]
    r["lines"] = q(c, "SELECT l.*, x.code account_code, x.name account_name, p.code pcode, e.code eq_code "
                      "FROM voucher_lines l JOIN accounts x ON x.id=l.account_id LEFT JOIN projects p ON p.id=l.project_id "
                      "LEFT JOIN equipment e ON e.id=l.equipment_id WHERE l.voucher_id=? ORDER BY l.id", (r["voucher_id"],))
    return r


def _open_entry(c, vid):
    pq = q1(c, "SELECT * FROM post_queue WHERE voucher_id=?", (vid,))
    v = q1(c, "SELECT * FROM vouchers WHERE id=?", (vid,))
    if not pq or not v or v["status"] != "submitted":
        raise ApiError("This entry is no longer waiting (it was posted, or its document was cancelled).")
    return pq, v


@api("pq.approve")
def pq_approve(c, u, a):
    done = 0
    for vid in a.get("ids") or [a.get("id")]:
        pq, v = _open_entry(c, int(vid))
        if pq["stage"] == "approved":
            continue
        need_right(c, u, pq["module"], "approve", "approve this cost")
        _not_maker(u, pq["created_by"], "approve")
        upd_pq(c, pq["voucher_id"], {"stage": "approved", "approved_by": u["id"], "approved_at": now(), "note": None})
        done += 1
    audit(c, u, "approve", "post_queue", None, {"ids": a.get("ids") or [a.get("id")]})
    return {"approved": done}


def upd_pq(c, vid, d):
    keys = list(d.keys())
    c.execute("UPDATE post_queue SET %s WHERE voucher_id=?" % ",".join(k + "=?" for k in keys), [d[k] for k in keys] + [vid])


@api("pq.recode")
def pq_recode(c, u, a):
    """Accounts may correct the account or cost dimensions of a waiting entry; amounts stay as raised."""
    pq, v = _open_entry(c, int(a["id"]))
    need_right(c, u, "accounts", "post", "correct a waiting entry")
    for ln in a.get("lines") or []:
        row = q1(c, "SELECT * FROM voucher_lines WHERE id=? AND voucher_id=?", (int(ln["id"]), v["id"]))
        if not row:
            continue
        ch = {}
        for k in ("account_id", "project_id", "boq_item_id", "equipment_id"):
            if k in ln and str(ln[k] or "") != str(row[k] or ""):
                ch[k] = int(ln[k]) if ln[k] not in (None, "") else None
        if ch.get("account_id"):
            ok = q1(c, "SELECT active FROM accounts WHERE id=?", (ch["account_id"],))
            if not ok or not ok["active"]:
                raise ApiError("Choose an active account.")
        if ch:
            upd(c, "voucher_lines", row["id"], ch)
    audit(c, u, "recode", "vouchers", v["id"], a.get("lines"))
    return pq_get(c, u, {"id": v["id"]})


@api("pq.post")
def pq_post(c, u, a):
    """Accounts posts approved entries: the voucher gets its number now, in an open period."""
    out = []
    for vid in a.get("ids") or [a.get("id")]:
        pq, v = _open_entry(c, int(vid))
        need_right(c, u, "accounts", "post", "post to the ledger")
        if pq["stage"] != "approved":
            raise ApiError("%s still needs approval by %s before accounts can post it." %
                           (pq["label"] or "This entry", pq["module"]))
        _not_maker(u, pq["created_by"], "post")
        d = a.get("date") or v["date"]
        core.assert_open(c, u, d)
        no = next_no(c, core.VOUCHER_PREFIX.get(v["type"], "JV"), d)
        c.execute("UPDATE vouchers SET status='posted', no=?, date=?, approved_by=? WHERE id=?", (no, d, u["id"], v["id"]))
        upd_pq(c, v["id"], {"stage": "posted", "posted_by": u["id"], "posted_at": now(), "posted_no": no})
        if pq["source"] == "invoice":
            c.execute("UPDATE invoices SET status='posted' WHERE id=? AND status='awaiting_posting'", (pq["source_id"],))
        if pq["source"] == "sc_bill":
            c.execute("UPDATE sc_bills SET status='posted' WHERE id=?", (pq["source_id"],))
        out.append(no)
    audit(c, u, "post", "post_queue", None, {"nos": out})
    return {"posted": out}


@api("pq.return")
def pq_return(c, u, a):
    """Send an entry back with a note. A bill goes back to draft (its entry is removed); for a store issue or
    DPR the note asks the site to correct or cancel the document, which removes the waiting entry."""
    pq, v = _open_entry(c, int(a["id"]))
    if not (allowed(c, u, "accounts", "post") or allowed(c, u, pq["module"], "approve")):
        raise ApiError("Your role cannot return this entry.")
    note = (a.get("note") or "").strip()
    if not note:
        raise ApiError("Say why it is returned.")
    if pq["source"] == "invoice":
        i = q1(c, "SELECT * FROM invoices WHERE id=?", (pq["source_id"],))
        if i and i["status"] == "awaiting_posting":
            c.execute("DELETE FROM voucher_lines WHERE voucher_id=?", (v["id"],))
            c.execute("DELETE FROM vouchers WHERE id=?", (v["id"],))
            _unnumber(c, i["no"])
            upd(c, "invoices", i["id"], {"status": "draft", "no": None, "voucher_id": None,
                                        "remarks": ((i["remarks"] or "") + " | Returned by accounts: " + note)[:500]})
        upd_pq(c, v["id"], {"stage": "withdrawn", "note": note, "returned_by": u["id"], "returned_at": now()})
    else:
        upd_pq(c, v["id"], {"stage": "returned", "note": note, "returned_by": u["id"], "returned_at": now(),
                            "approved_by": None, "approved_at": None})
    audit(c, u, "return", "post_queue", v["id"], note)
    return True


# ───────────────────── wrappers on existing engine functions ─────────────────────
def _wrap(name, factory):
    cur = inv.FUNCS.get(name)
    if not cur or getattr(cur[0], "_bco221", False):
        return
    w = factory(cur[0])
    w._bco221 = True
    for flag in ("_bco219", "_bco220"):   # the earlier layers stay recognisable through this one
        if getattr(cur[0], flag, False):
            setattr(w, flag, True)
    inv.FUNCS[name] = (w, cur[1], cur[2], cur[3])


def _inv_post_w(orig):
    def invoice_post3(c, u, a):
        r = orig(c, u, a)
        i = q1(c, "SELECT * FROM invoices WHERE id=?", (int(a["id"]),))
        if i and i["voucher_id"] and val(c, "SELECT status FROM vouchers WHERE id=?", (i["voucher_id"],)) == "submitted":
            upd(c, "invoices", i["id"], {"status": "awaiting_posting"})
            upd_pq(c, i["voucher_id"], {"label": "Bill %s %s" % (i["no"] or "", (i["remarks"] or "")[:60])})
            if isinstance(r, dict):
                r["awaiting_posting"] = True
        return r
    return invoice_post3


def _hire_bill_w(orig):
    def hire_bill2(c, u, a):
        r = orig(c, u, a)
        ag = get(c, "hire_agreements", int(a["agreement_id"]), "Hire agreement")
        end = core.month_end(a["month"])
        _collect_deductions(c, u, ag, end)
        ded = []
        for d in _open_deductions(c, ag["id"], end):
            ins(c, "invoice_lines", {"invoice_id": r["invoice_id"], "description": "Deduction: %s %s (%s)" %
                                     (d["kind"], d["description"] or "", d["date"]), "qty": 1, "rate": -d["amount"],
                                     "vat_rate": 0, "amount": -d["amount"], "account_id": d["account_id"],
                                     "equipment_id": d["equipment_id"]})
            upd(c, "rent_deductions", d["id"], {"invoice_id": r["invoice_id"], "status": "billed"})
            ded.append(d["amount"])
        r["deductions"] = r2(sum(ded))
        r["unapproved_logs"] = val(c, "SELECT COUNT(*) FROM logsheets WHERE equipment_id=? AND project_id=? AND date BETWEEN ? "
                                      "AND ? AND COALESCE(status,'draft')<>'approved'",
                                   (ag["equipment_id"], ag["project_id"], a["month"] + "-01", end))
        return r
    return hire_bill2


def _stock_loc_w(orig):
    def stock_locations2(c, u, a):
        r = orig(c, u, a)
        if isinstance(r, dict) and "difference" in r:
            pend = r2(val(c, "SELECT COALESCE(SUM(l.debit-l.credit),0) FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id "
                             "JOIN accounts ac ON ac.id=l.account_id WHERE ac.role LIKE 'inventory%' AND v.status='submitted'"))
            r["awaiting_posting"] = pend
            r["difference_after_pending"] = r2(r["difference"] - pend)
        return r
    return stock_locations2


def _approvals_w(orig):
    def approvals2(c, u, a):
        rows = orig(c, u, a)
        if isinstance(rows, list):
            for r in pq_list(c, u, {"stage": "open"}):
                rows.append({"kind": "posting", "label": "Accounts posting: " + r["gate_label"],
                             "id": r["voucher_id"], "no": r["label"], "date": r["date"],
                             "project_id": r["project_id"], "amount": r["amount"],
                             "can_approve": bool(r["can_approve"] or r["can_post"]), "stage": r["stage"]})
            for b in q(c, "SELECT * FROM sc_bills WHERE status IN ('submitted','approved')"):
                rows.append({"kind": "sc_bill", "label": "Subcontract bill (%s)" % b["status"], "id": b["id"],
                             "no": b["no"], "date": b["date"], "project_id": b["project_id"], "amount": b["net"],
                             "can_approve": allowed(c, u, "commercial", "approve") if b["status"] == "submitted"
                             else allowed(c, u, "accounts", "post")})
        return rows
    return approvals2


def _wrap_all():
    _wrap("invoice.post", _inv_post_w)
    _wrap("hire.bill", _hire_bill_w)
    _wrap("ws.stock_locations", _stock_loc_w)
    _wrap("dash.approvals", _approvals_w)


# ───────────────────────────── execution plan ─────────────────────────────
@api("exec.plan", "project", "view")
def exec_plan(c, u, a):
    need(a, "project_id")
    pid = int(a["project_id"])
    items = q(c, "SELECT id, code, description, unit, qty, rate FROM boq_items WHERE project_id=? ORDER BY code, id", (pid,))
    plan = q(c, "SELECT e.*, o.no order_no, pa.name party FROM exec_plan e LEFT JOIN sc_orders o ON o.id=e.sc_order_id "
                "LEFT JOIN parties pa ON pa.id=o.party_id WHERE e.project_id=? ORDER BY e.id", (pid,))
    by = {}
    for p in plan:
        by.setdefault(p["boq_item_id"], []).append(p)
    for i in items:
        i["modes"] = by.get(i["id"], [])
        i["planned_pct"] = r2(sum(m["share_pct"] or 0 for m in i["modes"]))
    return {"items": items, "summary": _plan_summary(items)}


def _plan_summary(items):
    out = {}
    for i in items:
        val_ = (i["qty"] or 0) * (i["rate"] or 0)
        for m in i["modes"]:
            out[m["work_mode"]] = out.get(m["work_mode"], 0) + val_ * (m["share_pct"] or 0) / 100
        left = max(0, 100 - i["planned_pct"])
        if left > 0.001:
            out["unplanned"] = out.get("unplanned", 0) + val_ * left / 100
    return {k: r2(v) for k, v in out.items()}


@api("exec.plan_save", "project", "edit")
def exec_plan_save(c, u, a):
    need(a, "project_id", "boq_item_id")
    pid, bid = int(a["project_id"]), int(a["boq_item_id"])
    b = get(c, "boq_items", bid, "BOQ item")
    if b["project_id"] != pid:
        raise ApiError("This BOQ item belongs to another project.")
    rows = a.get("rows") or []
    tot = 0
    clean = []
    for r in rows:
        if not r.get("work_mode"):
            continue
        if r["work_mode"] not in dict(WORK_MODES):
            raise ApiError("Unknown way of executing: %s" % r["work_mode"])
        sh = num(r.get("share_pct") if r.get("share_pct") not in (None, "") else 100, "share")
        if sh <= 0 or sh > 100:
            raise ApiError("Each share must be between 0 and 100%.")
        tot += sh
        so = int(r["sc_order_id"]) if r.get("sc_order_id") else None
        if so:
            o = get(c, "sc_orders", so, "Work order")
            if o["project_id"] != pid:
                raise ApiError("Work order %s belongs to another project." % o["no"])
        clean.append({"project_id": pid, "boq_item_id": bid, "share_pct": sh, "work_mode": r["work_mode"],
                      "equip_mode": r.get("equip_mode") or None, "sc_order_id": so, "remarks": r.get("remarks"),
                      "ts": now()})
    if tot > 100.001:
        raise ApiError("The shares add up to %s%%; they cannot be more than 100%%." % r2(tot))
    c.execute("DELETE FROM exec_plan WHERE project_id=? AND boq_item_id=?", (pid, bid))
    for r in clean:
        ins(c, "exec_plan", r)
    audit(c, u, "save", "exec_plan", bid, clean)
    return True


def _executed(c, bid):
    m = val(c, "SELECT SUM(l.qty) FROM measurement_lines l JOIN measurements m ON m.id=l.measurement_id "
               "WHERE l.boq_item_id=? AND m.status IN ('verified','approved','certified')", (bid,))
    b = val(c, "SELECT executed_qty FROM boq_items WHERE id=?", (bid,))
    d = val(c, "SELECT SUM(w.actual_qty) FROM dpr_work w JOIN dpr d ON d.id=w.dpr_id WHERE w.boq_item_id=? "
               "AND d.status='approved'", (bid,))
    return r4(max(m or 0, b or 0, d or 0))


def _gl_by_boq(c, bid, roles):
    return r2(val(c, "SELECT SUM(l.debit-l.credit) FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id JOIN accounts x "
                     "ON x.id=l.account_id WHERE l.boq_item_id=? AND " + POSTED + " AND x.role IN (%s)" %
                  ",".join("?" * len(roles)), [bid] + list(roles)))


@api("exec.mode_report", "project", "view")
def exec_mode_report(c, u, a):
    """Cost per unit of each BOQ item by the way it was actually executed."""
    need(a, "project_id")
    pid = int(a["project_id"])
    out = []
    for b in q(c, "SELECT * FROM boq_items WHERE project_id=? ORDER BY code, id", (pid,)):
        done = _executed(c, b["id"])
        sc = q(c, "SELECT o.type, SUM(bi.qty) qty, SUM(bi.amount) gross FROM sc_bill_items bi JOIN sc_bills sb ON sb.id=bi.bill_id "
                  "JOIN sc_order_items oi ON oi.id=bi.order_item_id JOIN sc_orders o ON o.id=sb.order_id "
                  "WHERE oi.boq_item_id=? AND sb.status IN ('approved','posted') GROUP BY o.type", (b["id"],))
        margin = r2(val(c, "SELECT SUM(r.amount-r.cost) FROM sc_bill_recoveries r JOIN sc_bills sb ON sb.id=r.bill_id "
                           "WHERE r.kind='material' AND sb.status IN ('approved','posted') AND sb.id IN (SELECT bi.bill_id FROM "
                           "sc_bill_items bi JOIN sc_order_items oi ON oi.id=bi.order_item_id WHERE oi.boq_item_id=?)", (b["id"],)))
        sc_qty = sum(x["qty"] or 0 for x in sc)
        done = max(done, sc_qty)                      # billed subcontract work is executed work
        direct_qty = max(0.0, done - sc_qty)
        labour = _gl_by_boq(c, b["id"], ("labour_cost",))
        matl = _gl_by_boq(c, b["id"], ("material_cost",))
        equip = _gl_by_boq(c, b["id"], ("equipment_cost", "hire_cost", "fuel_cost", "repair_cost"))
        rows = []
        if direct_qty > EPS or labour:
            rows.append({"mode": "direct", "qty": r4(direct_qty), "labour": labour,
                         "unit_labour": r2(labour / direct_qty) if direct_qty > EPS else None})
        for x in sc:
            m = SC_TYPE_MODE.get(x["type"], x["type"])
            net = r2((x["gross"] or 0) - (margin if x["type"] == "supplied" else 0))
            rows.append({"mode": m, "qty": r4(x["qty"] or 0), "subcontract": r2(x["gross"] or 0), "net_subcontract": net,
                         "unit_subcontract": r2(net / x["qty"]) if (x["qty"] or 0) > EPS else None})
        total = r2(labour + matl + equip + sum(r.get("net_subcontract") or 0 for r in rows))
        out.append({"boq_item_id": b["id"], "code": b["code"], "description": b["description"], "unit": b["unit"],
                    "boq_qty": b["qty"], "rate": b["rate"], "executed": done, "material": matl, "equipment": equip,
                    "labour": labour, "total_cost": total, "unit_cost": r2(total / done) if done > EPS else None,
                    "margin_pct": r2((b["rate"] - total / done) / b["rate"] * 100) if done > EPS and b["rate"] else None,
                    "modes": rows, "plan": q(c, "SELECT work_mode, share_pct, equip_mode FROM exec_plan WHERE boq_item_id=?",
                                             (b["id"],))})
    return out


# ───────────────────────────── subcontract work orders ─────────────────────────────
def _order(c, oid):
    o = get(c, "sc_orders", int(oid), "Work order")
    o["items"] = q(c, "SELECT oi.*, b.code boq_code FROM sc_order_items oi LEFT JOIN boq_items b ON b.id=oi.boq_item_id "
                      "WHERE oi.order_id=? ORDER BY oi.id", (o["id"],))
    o["mats"] = q(c, "SELECT m.*, x.code mcode, x.name mname, x.unit FROM sc_order_mats m JOIN materials x ON x.id=m.material_id "
                     "WHERE m.order_id=? ORDER BY m.id", (o["id"],))
    o["party"] = val(c, "SELECT name FROM parties WHERE id=?", (o["party_id"],), "")
    o["value"] = r2(sum((i["qty"] or 0) * (i["rate"] or 0) for i in o["items"]))
    for i in o["items"]:
        i["done"] = r4(val(c, "SELECT SUM(bi.qty) FROM sc_bill_items bi JOIN sc_bills b ON b.id=bi.bill_id WHERE "
                              "bi.order_item_id=? AND b.status NOT IN ('cancelled')", (i["id"],)))
    return o


@api("sco.list", "commercial", "view")
def sc_list(c, u, a):
    cond, p = ["1=1"], []
    if a.get("project_id"):
        cond.append("o.project_id=?")
        p.append(int(a["project_id"]))
    if a.get("party_id"):
        cond.append("o.party_id=?")
        p.append(int(a["party_id"]))
    rows = q(c, "SELECT o.*, pa.name party, pr.code pcode FROM sc_orders o LEFT JOIN parties pa ON pa.id=o.party_id "
                "LEFT JOIN projects pr ON pr.id=o.project_id WHERE " + " AND ".join(cond) + " ORDER BY o.date DESC, o.id DESC", p)
    for o in rows:
        o["value"] = r2(val(c, "SELECT SUM(qty*rate) FROM sc_order_items WHERE order_id=?", (o["id"],)))
        o["billed"] = r2(val(c, "SELECT SUM(gross) FROM sc_bills WHERE order_id=? AND status IN ('approved','posted')", (o["id"],)))
        o["net_paid_basis"] = r2(val(c, "SELECT SUM(net) FROM sc_bills WHERE order_id=? AND status='posted'", (o["id"],)))
        o["with_sub"] = r2(_custody_value(c, o["id"]))
        o["type_name"] = dict(SC_TYPES).get(o["type"], o["type"])
    return rows


@api("sco.get", "commercial", "view")
def sc_get(c, u, a):
    o = _order(c, a["id"])
    o["bills"] = q(c, "SELECT * FROM sc_bills WHERE order_id=? ORDER BY date, id", (o["id"],))
    o["moves"] = q(c, "SELECT m.*, x.name mname, x.unit FROM sc_moves m JOIN materials x ON x.id=m.material_id WHERE m.order_id=? "
                      "ORDER BY m.date, m.id", (o["id"],))
    o["recon"] = sc_recon(c, u, {"order_id": o["id"]})
    return o


@api("sco.save", "commercial", "edit")
def sc_save(c, u, a):
    h = a.get("header") or {}
    need(h, "project_id", "party_id", "type", "date")
    if h["type"] not in dict(SC_TYPES):
        raise ApiError("Choose the type of subcontract.")
    party = get(c, "parties", int(h["party_id"]), "Party")
    if party["kind"] == "client":
        raise ApiError("A work order is for a subcontractor or supplier, not a client.")
    basis = h.get("recovery_basis") or "bill_oh"
    if basis not in ("bill_oh", "fixed"):
        raise ApiError("Unknown recovery basis.")
    data = {k: h.get(k) for k in ("title", "date", "start_date", "end_date", "equip_terms", "remarks")}
    data.update({"project_id": int(h["project_id"]), "party_id": party["id"], "type": h["type"],
                 "retention_pct": num(h.get("retention_pct") or 0), "advance": num(h.get("advance") or 0),
                 "vat_rate": num(h.get("vat_rate") or 0), "recovery_basis": basis,
                 "overhead_pct": num(h.get("overhead_pct") or 0), "contract_id": h.get("contract_id") or None})
    if h.get("id"):
        o = get(c, "sc_orders", int(h["id"]), "Work order")
        if o["status"] == "closed":
            raise ApiError("A closed work order cannot be changed.")
        billed = val(c, "SELECT COUNT(*) FROM sc_bills WHERE order_id=? AND status<>'cancelled'", (o["id"],))
        if billed and (int(h["project_id"]) != o["project_id"] or party["id"] != o["party_id"] or h["type"] != o["type"]):
            raise ApiError("Bills exist: project, subcontractor and type can no longer change.")
        upd(c, "sc_orders", o["id"], data)
        oid = o["id"]
    else:
        data.update({"no": next_no(c, "SCO", h["date"]), "status": "draft", "created_by": u["id"], "ts": now()})
        oid = ins(c, "sc_orders", data)
    keep = set()
    for it in a.get("items") or []:
        if not (it.get("description") or it.get("boq_item_id")):
            continue
        row = {"order_id": oid, "boq_item_id": int(it["boq_item_id"]) if it.get("boq_item_id") else None,
               "description": it.get("description") or val(c, "SELECT description FROM boq_items WHERE id=?", (it.get("boq_item_id"),), ""),
               "unit": it.get("unit") or val(c, "SELECT unit FROM boq_items WHERE id=?", (it.get("boq_item_id"),), ""),
               "qty": num(it.get("qty") or 0), "rate": num(it.get("rate") or 0)}
        if row["boq_item_id"] and val(c, "SELECT project_id FROM boq_items WHERE id=?", (row["boq_item_id"],)) != int(h["project_id"]):
            raise ApiError("BOQ item of another project.")
        if it.get("id") and q1(c, "SELECT id FROM sc_order_items WHERE id=? AND order_id=?", (int(it["id"]), oid)):
            done = val(c, "SELECT SUM(bi.qty) FROM sc_bill_items bi JOIN sc_bills b ON b.id=bi.bill_id WHERE bi.order_item_id=? "
                          "AND b.status<>'cancelled'", (int(it["id"]),))
            if row["qty"] + EPS < (done or 0):
                raise ApiError("%s: quantity cannot go below the %s already billed." % (row["description"], r4(done)))
            upd(c, "sc_order_items", int(it["id"]), row)
            keep.add(int(it["id"]))
        else:
            keep.add(ins(c, "sc_order_items", row))
    for old in q(c, "SELECT id FROM sc_order_items WHERE order_id=?", (oid,)):
        if old["id"] not in keep:
            if val(c, "SELECT COUNT(*) FROM sc_bill_items WHERE order_item_id=?", (old["id"],)):
                raise ApiError("An item that is already billed cannot be removed.")
            c.execute("DELETE FROM sc_order_items WHERE id=?", (old["id"],))
    c.execute("DELETE FROM sc_order_mats WHERE order_id=?", (oid,))
    for m in a.get("mats") or []:
        if not m.get("material_id"):
            continue
        if basis == "fixed" and num(m.get("fixed_rate") or 0) <= 0:
            raise ApiError("Single agreed rate: give the recovery rate of every supplied material.")
        ins(c, "sc_order_mats", {"order_id": oid, "material_id": int(m["material_id"]),
                                 "order_item_id": int(m["order_item_id"]) if m.get("order_item_id") else None,
                                 "per_unit": num(m.get("per_unit") or 0), "wastage_pct": num(m.get("wastage_pct") or 0),
                                 "fixed_rate": num(m.get("fixed_rate") or 0)})
    audit(c, u, "save", "sc_orders", oid, h)
    return {"id": oid}


@api("sco.approve", "commercial", "approve")
def sc_approve(c, u, a):
    o = get(c, "sc_orders", int(a["id"]), "Work order")
    if o["status"] != "draft":
        raise ApiError("Only a draft work order can be approved.")
    _not_maker(u, o["created_by"], "approve")
    if not val(c, "SELECT COUNT(*) FROM sc_order_items WHERE order_id=?", (o["id"],)):
        raise ApiError("Add the items and rates first.")
    upd(c, "sc_orders", o["id"], {"status": "approved", "approved_by": u["id"]})
    for it in q(c, "SELECT * FROM sc_order_items WHERE order_id=? AND boq_item_id IS NOT NULL", (o["id"],)):
        if not q1(c, "SELECT id FROM exec_plan WHERE boq_item_id=? AND sc_order_id=?", (it["boq_item_id"], o["id"])):
            have = val(c, "SELECT SUM(share_pct) FROM exec_plan WHERE boq_item_id=?", (it["boq_item_id"],))
            bq = val(c, "SELECT qty FROM boq_items WHERE id=?", (it["boq_item_id"],)) or 0
            share = min(100.0, r2(it["qty"] / bq * 100)) if bq else 100.0
            share = min(share, max(0.0, 100 - (have or 0)))
            if share > 0:
                ins(c, "exec_plan", {"project_id": o["project_id"], "boq_item_id": it["boq_item_id"], "share_pct": share,
                                     "work_mode": SC_TYPE_MODE[o["type"]],
                                     "equip_mode": "sub" if o["type"] == "b2b" else "owned", "sc_order_id": o["id"],
                                     "remarks": "From work order %s" % o["no"], "ts": now()})
    audit(c, u, "approve", "sc_orders", o["id"])
    return True


@api("sco.close", "commercial", "approve")
def sc_close(c, u, a):
    o = get(c, "sc_orders", int(a["id"]), "Work order")
    if val(c, "SELECT COUNT(*) FROM sc_bills WHERE order_id=? AND status IN ('draft','submitted','approved')", (o["id"],)):
        raise ApiError("Finish or cancel the open bills first.")
    upd(c, "sc_orders", o["id"], {"status": "closed"})
    return True


# ── material with the subcontractor ──
def _custody(c, oid, upto=None):
    """Per material: issued, returned, recovered (qty and our cost) and what is still with the subcontractor."""
    cond, p = "", [oid]
    if upto:
        cond = " AND date<=?"
        p.append(upto)
    out = {}
    for m in q(c, "SELECT material_id, kind, SUM(qty) qty, SUM(value) value FROM sc_moves WHERE order_id=? AND status='posted'"
                  + cond + " GROUP BY material_id, kind", p):
        r = out.setdefault(m["material_id"], {"material_id": m["material_id"], "issued": 0, "issued_value": 0,
                                               "returned": 0, "returned_value": 0, "recovered": 0, "recovered_cost": 0})
        if m["kind"] == "issue":
            r["issued"], r["issued_value"] = m["qty"], m["value"]
        else:
            r["returned"], r["returned_value"] = m["qty"], m["value"]
    for m in q(c, "SELECT r.material_id, SUM(r.qty) qty, SUM(r.cost) cost FROM sc_bill_recoveries r JOIN sc_bills b ON b.id=r.bill_id "
                  "WHERE b.order_id=? AND r.kind='material' AND b.status NOT IN ('cancelled') GROUP BY r.material_id", (oid,)):
        r = out.setdefault(m["material_id"], {"material_id": m["material_id"], "issued": 0, "issued_value": 0,
                                               "returned": 0, "returned_value": 0, "recovered": 0, "recovered_cost": 0})
        r["recovered"], r["recovered_cost"] = m["qty"] or 0, m["cost"] or 0
    for r in out.values():
        r["balance"] = r4(r["issued"] - r["returned"] - r["recovered"])
        r["balance_value"] = r2(r["issued_value"] - r["returned_value"] - r["recovered_cost"])
        r["avg_cost"] = r4(r["balance_value"] / r["balance"]) if r["balance"] > EPS else \
            (r4(r["issued_value"] / r["issued"]) if r["issued"] > EPS else 0)
    return out


def _custody_value(c, oid):
    return sum(r["balance_value"] for r in _custody(c, oid).values())


@api("sco.issue", "inventory", "edit")
def sc_issue(c, u, a):
    """Issue material to a subcontractor (kind issue) or take unused material back (kind return).
    Stock moves at weighted average cost to / from 'Material with subcontractors'; nothing is expensed."""
    need(a, "order_id", "store_id", "date")
    o = get(c, "sc_orders", int(a["order_id"]), "Work order")
    if o["status"] not in ("approved",):
        raise ApiError("Material can be issued against an approved work order only.")
    if o["type"] == "b2b":
        raise ApiError("A back-to-back subcontractor brings its own material.")
    kind = a.get("kind") or "issue"
    store = int(a["store_id"])
    core.check_store(c, store, o["project_id"])
    lines = [l for l in (a.get("lines") or []) if l.get("material_id") and num(l.get("qty") or 0) > 0]
    if not lines:
        raise ApiError("Add at least one material and quantity.")
    no = next_no(c, "SCI" if kind == "issue" else "SCR", a["date"])
    vl = []
    cust = _custody(c, o["id"])
    for l in lines:
        mid, qty = int(l["material_id"]), num(l["qty"])
        mat = material(c, mid)
        mv = ins(c, "sc_moves", {"no": no, "order_id": o["id"], "project_id": o["project_id"], "store_id": store,
                                 "date": a["date"], "kind": kind, "material_id": mid, "qty": qty, "status": "posted",
                                 "remarks": a.get("remarks"), "created_by": u["id"], "ts": now()})
        if kind == "issue":
            rate, value = stock_out(c, u, o["project_id"], store, mid, qty, a["date"], "SC-ISSUE", mv, no)
            vl += [{"role": "subcon_material", "debit": value, "party_id": o["party_id"], "narration": mat["name"]},
                   {"role": inventory_role(mat), "credit": value, "narration": mat["name"]}]
        else:
            have = cust.get(mid, {}).get("balance", 0)
            if qty > have + EPS:
                raise ApiError("%s: only %s is with the subcontractor." % (mat["name"], r4(have)))
            rate = cust[mid]["avg_cost"]
            value = r2(qty * rate)
            stock_in(c, u, o["project_id"], store, mid, qty, rate, a["date"], "SC-RETURN", mv, no)
            vl += [{"role": inventory_role(mat), "debit": value, "narration": mat["name"]},
                   {"role": "subcon_material", "credit": value, "party_id": o["party_id"], "narration": mat["name"]}]
        upd(c, "sc_moves", mv, {"rate": rate, "value": value})
    acct(c, "subcon_material")
    vid = core.post_voucher(c, u, "journal", a["date"], "%s %s work order %s" %
                            ("Material to subcontractor" if kind == "issue" else "Material back from subcontractor", no, o["no"]),
                            vl, project_id=o["project_id"], source="sc_issue", party_id=o["party_id"])
    c.execute("UPDATE sc_moves SET voucher_id=? WHERE no=?", (vid, no))
    audit(c, u, kind, "sc_moves", None, {"no": no, "order": o["no"]})
    return {"no": no, "voucher_id": vid}


@api("sco.recon", "commercial", "view")
def sc_recon(c, u, a):
    """Material reconciliation: issued, returned, recovered, still with the subcontractor, theoretical use
    (billed quantity x norm + wastage allowance) and excess use."""
    o = get(c, "sc_orders", int(a["order_id"]), "Work order")
    cust = _custody(c, o["id"])
    out = []
    mats = q(c, "SELECT * FROM sc_order_mats WHERE order_id=?", (o["id"],))
    for m in mats:
        cust.setdefault(m["material_id"], {"material_id": m["material_id"], "issued": 0, "issued_value": 0, "returned": 0,
                                           "returned_value": 0, "recovered": 0, "recovered_cost": 0, "balance": 0,
                                           "balance_value": 0, "avg_cost": 0})
    for mid, r in cust.items():
        theo = allow = 0.0
        for m in [x for x in mats if x["material_id"] == mid]:
            if m["order_item_id"]:
                done = val(c, "SELECT SUM(bi.qty) FROM sc_bill_items bi JOIN sc_bills b ON b.id=bi.bill_id WHERE "
                              "bi.order_item_id=? AND b.status IN ('approved','posted')", (m["order_item_id"],))
            else:
                done = val(c, "SELECT SUM(bi.qty) FROM sc_bill_items bi JOIN sc_bills b ON b.id=bi.bill_id WHERE "
                              "b.order_id=? AND b.status IN ('approved','posted')", (o["id"],))
            theo += (done or 0) * (m["per_unit"] or 0)
            allow += (done or 0) * (m["per_unit"] or 0) * (1 + (m["wastage_pct"] or 0) / 100)
        used = r["issued"] - r["returned"]
        mat = material(c, mid)
        r.update({"material": mat["name"], "unit": mat["unit"], "net_issued": r4(used), "theoretical": r4(theo),
                  "allowed": r4(allow), "excess": r4(used - allow) if allow > EPS else None,
                  "excess_value": r2((used - allow) * (r["avg_cost"] or 0)) if allow > EPS and used > allow else 0})
        out.append(r)
    return out


# ── running bills ──
def _bill(c, bid):
    b = get(c, "sc_bills", int(bid), "Subcontract bill")
    b["items"] = q(c, "SELECT bi.*, oi.description, oi.unit, oi.qty order_qty, oi.boq_item_id FROM sc_bill_items bi "
                      "JOIN sc_order_items oi ON oi.id=bi.order_item_id WHERE bi.bill_id=? ORDER BY bi.id", (b["id"],))
    b["recoveries"] = q(c, "SELECT r.*, m.name mname, m.unit munit, e.code eq_code FROM sc_bill_recoveries r LEFT JOIN materials m "
                           "ON m.id=r.material_id LEFT JOIN equipment e ON e.id=r.equipment_id WHERE r.bill_id=? ORDER BY r.id",
                        (b["id"],))
    return b


@api("sco.bill_prefill", "commercial", "view")
def sc_bill_prefill(c, u, a):
    """A new running bill: previous quantities from earlier bills, and every supplied material not yet recovered."""
    o = _order(c, a["order_id"])
    upto = a.get("date") or today()
    items = []
    for i in o["items"]:
        prev = val(c, "SELECT SUM(bi.qty) FROM sc_bill_items bi JOIN sc_bills b ON b.id=bi.bill_id WHERE bi.order_item_id=? "
                      "AND b.status<>'cancelled'", (i["id"],))
        items.append({"order_item_id": i["id"], "description": i["description"], "unit": i["unit"], "order_qty": i["qty"],
                      "prev_qty": r4(prev or 0), "qty": 0, "rate": i["rate"]})
    recs = []
    for mid, r in _custody(c, o["id"], upto).items():
        if r["balance"] <= EPS:
            continue
        rec_rate = _recovery_rate(c, o, mid, r["avg_cost"])
        mat = material(c, mid)
        recs.append({"kind": "material", "material_id": mid, "description": mat["name"], "unit": mat["unit"],
                     "qty": r["balance"], "cost_rate": r["avg_cost"], "rate": rec_rate,
                     "with_sub": r["balance"]})
    adv_open = 0.0
    try:
        import api_finance as F
        adv_open = F.party_advance_balance(c, o["party_id"], "purchase")
    except Exception:
        pass
    return {"order": o, "items": items, "recoveries": recs, "retention_pct": o["retention_pct"], "vat_rate": o["vat_rate"],
            "advance_open": r2(adv_open)}


def _recovery_rate(c, o, mid, avg_cost):
    if o["recovery_basis"] == "fixed":
        r = val(c, "SELECT fixed_rate FROM sc_order_mats WHERE order_id=? AND material_id=? AND fixed_rate>0", (o["id"], mid))
        if not r:
            raise ApiError("No agreed recovery rate for %s on work order %s." % (material(c, mid)["name"], o["no"]))
        return r4(r)
    return r4((avg_cost or 0) * (1 + (o["overhead_pct"] or 0) / 100))


@api("sco.bill_get", "commercial", "view")
def sc_bill_get(c, u, a):
    b = _bill(c, a["id"])
    b["order"] = _order(c, b["order_id"])
    return b


def _bill_totals(o, items, recs, adv, ret_override=None):
    gross = r2(sum(r2(num(i["qty"]) * num(i["rate"])) for i in items))
    mrec = r2(sum(r["amount"] for r in recs if r["kind"] == "material"))
    mcost = r2(sum(r["cost"] for r in recs if r["kind"] == "material"))
    erec = r2(sum(r["amount"] for r in recs if r["kind"] == "equipment"))
    oth = r2(sum(r["amount"] for r in recs if r["kind"] not in ("material", "equipment")))
    ret = r2(gross * (o["retention_pct"] or 0) / 100) if ret_override in (None, "") else r2(num(ret_override))
    vat = r2(gross * (o["vat_rate"] or 0) / 100)
    net = r2(gross + vat - mrec - erec - oth - r2(adv) - ret)
    return {"gross": gross, "material_recovery": mrec, "material_cost": mcost, "equipment_recovery": erec,
            "other_deduction": oth, "advance_recovery": r2(adv), "retention": ret, "vat": vat, "net": net}


@api("sco.bill_save", "commercial", "edit")
def sc_bill_save(c, u, a):
    h = a.get("header") or {}
    need(h, "order_id", "date")
    o = _order(c, h["order_id"])
    if o["status"] != "approved":
        raise ApiError("Bills can be made on an approved work order only.")
    if h.get("id"):
        b = get(c, "sc_bills", int(h["id"]), "Subcontract bill")
        if b["status"] != "draft":
            raise ApiError("Only a draft bill can be changed (return it to draft first).")
        bid = b["id"]
        c.execute("DELETE FROM sc_bill_items WHERE bill_id=?", (bid,))
        c.execute("DELETE FROM sc_bill_recoveries WHERE bill_id=?", (bid,))
    else:
        bid = ins(c, "sc_bills", {"no": None, "order_id": o["id"], "project_id": o["project_id"], "party_id": o["party_id"],
                                  "date": h["date"], "status": "draft", "created_by": u["id"], "ts": now()})
    oi = {i["id"]: i for i in o["items"]}
    items = []
    for it in a.get("items") or []:
        if not it.get("order_item_id") or num(it.get("qty") or 0) == 0:
            continue
        i = oi.get(int(it["order_item_id"]))
        if not i:
            raise ApiError("Item is not on this work order.")
        prev = val(c, "SELECT SUM(bi.qty) FROM sc_bill_items bi JOIN sc_bills b ON b.id=bi.bill_id WHERE bi.order_item_id=? "
                      "AND b.status<>'cancelled' AND b.id<>?", (i["id"], bid)) or 0
        qty = num(it["qty"])
        if prev + qty > i["qty"] + EPS:
            raise ApiError("%s: cumulative %s would exceed the work order quantity %s." % (i["description"], r4(prev + qty), i["qty"]))
        if prev + qty < -EPS:
            raise ApiError("%s: cumulative quantity cannot be negative." % i["description"])
        row = {"bill_id": bid, "order_item_id": i["id"], "prev_qty": r4(prev), "qty": qty, "rate": i["rate"],
               "amount": r2(qty * i["rate"])}
        ins(c, "sc_bill_items", row)
        items.append(row)
    cust = _custody(c, o["id"])
    recs = []
    for r in a.get("recoveries") or []:
        kind = r.get("kind") or "other"
        qty, rate = num(r.get("qty") or 0), num(r.get("rate") or 0)
        row = {"bill_id": bid, "kind": kind, "description": r.get("description"), "qty": qty, "rate": rate,
               "amount": r2(qty * rate) if kind in ("material", "equipment") else r2(num(r.get("amount") or qty * rate)),
               "material_id": None, "equipment_id": None, "cost_rate": 0, "cost": 0}
        if kind == "material":
            mid = int(r["material_id"])
            have = cust.get(mid, {}).get("balance", 0)
            if qty > have + EPS:
                raise ApiError("%s: recovering %s but only %s is with the subcontractor." % (material(c, mid)["name"], qty, r4(have)))
            row.update({"material_id": mid, "cost_rate": cust[mid]["avg_cost"],
                        "cost": r2(qty * cust[mid]["avg_cost"]) if qty < have - EPS else r2(cust[mid]["balance_value"])})
            if o["recovery_basis"] == "fixed":
                row["rate"] = _recovery_rate(c, o, mid, row["cost_rate"])
                row["amount"] = r2(qty * row["rate"])
        elif kind == "equipment":
            row["equipment_id"] = int(r["equipment_id"]) if r.get("equipment_id") else None
        if abs(row["amount"]) < 0.005 and kind != "material":
            continue
        if kind == "material" and qty <= EPS:
            continue
        ins(c, "sc_bill_recoveries", row)
        recs.append(row)
    t = _bill_totals(o, items, recs, num(h.get("advance_recovery") or 0), h.get("retention"))
    if t["net"] < -0.005:
        raise ApiError("Deductions (%s) are more than the bill (%s). Recover the rest in a later bill." %
                       (fmt(t["gross"] + t["vat"] - t["net"]), fmt(t["gross"] + t["vat"])))
    t.update({"date": h["date"], "period_to": h.get("period_to"), "party_bill_no": h.get("party_bill_no"),
              "remarks": h.get("remarks")})
    upd(c, "sc_bills", bid, t)
    audit(c, u, "save", "sc_bills", bid, t)
    return {"id": bid, "totals": t}


def fmt(x):
    return "{:,.2f}".format(x)


@api("sco.bill_submit", "commercial", "edit")
def sc_bill_submit(c, u, a):
    b = get(c, "sc_bills", int(a["id"]), "Subcontract bill")
    if b["status"] != "draft":
        raise ApiError("Only a draft can be submitted.")
    if not val(c, "SELECT COUNT(*) FROM sc_bill_items WHERE bill_id=?", (b["id"],)):
        raise ApiError("Enter the quantities executed this period.")
    upd(c, "sc_bills", b["id"], {"status": "submitted", "submitted_by": u["id"], "note": None,
                                 "no": b["no"] or next_no(c, "SCB", b["date"])})
    return True


@api("sco.bill_approve", "commercial", "approve")
def sc_bill_approve(c, u, a):
    b = get(c, "sc_bills", int(a["id"]), "Subcontract bill")
    if b["status"] != "submitted":
        raise ApiError("Only a submitted bill can be approved.")
    _not_maker(u, b["submitted_by"] or b["created_by"], "approve")
    upd(c, "sc_bills", b["id"], {"status": "approved", "approved_by": u["id"]})
    audit(c, u, "approve", "sc_bills", b["id"])
    return True


@api("sco.bill_return")
def sc_bill_return(c, u, a):
    b = get(c, "sc_bills", int(a["id"]), "Subcontract bill")
    if b["status"] not in ("submitted", "approved"):
        raise ApiError("Only a submitted or approved bill can be returned.")
    if not (allowed(c, u, "commercial", "approve") or allowed(c, u, "accounts", "post")):
        raise ApiError("Your role cannot return subcontract bills.")
    upd(c, "sc_bills", b["id"], {"status": "draft", "note": a.get("note"), "approved_by": None})
    return True


@api("sco.bill_post")
def sc_bill_post(c, u, a):
    """Accounts posts an approved running bill: one purchase bill (gross work, minus recoveries), which the existing
    invoice engine posts with retention and advance recovery, so payments, TDS and ageing work as for any bill."""
    b = _bill(c, a["id"])
    need_right(c, u, "accounts", "post", "post subcontract bills")
    if b["status"] != "approved":
        raise ApiError("The bill must be approved before accounts posts it.")
    _not_maker(u, b["submitted_by"] or b["created_by"], "post")
    o = get(c, "sc_orders", b["order_id"])
    d = a.get("date") or b["date"]
    core.assert_open(c, u, d)
    acc_sub = acct(c, "subcon_cost")
    iid = ins(c, "invoices", {"kind": "purchase", "party_id": b["party_id"], "project_id": b["project_id"], "date": d,
                              "party_inv_no": b["party_bill_no"] or b["no"], "retention": b["retention"],
                              "advance_recovery": b["advance_recovery"], "status": "draft", "source": "sc_bill",
                              "remarks": "Running bill %s, work order %s" % (b["no"], o["no"]), "created_by": u["id"]})
    for i in b["items"]:
        if abs(i["amount"]) < 0.005:
            continue
        ins(c, "invoice_lines", {"invoice_id": iid, "description": "%s (%s %s)" % (i["description"], r4(i["qty"]), i["unit"] or ""),
                                 "qty": i["qty"], "rate": i["rate"], "vat_rate": o["vat_rate"] or 0, "amount": i["amount"],
                                 "account_id": acc_sub, "boq_item_id": i["boq_item_id"]})
    for r in b["recoveries"]:
        if r["kind"] == "material":
            lines = [("Recovery of %s (our cost)" % r["mname"], acct(c, "subcon_material"), r["cost"]),
                     ("Recovery margin on %s" % r["mname"], acct(c, "subcon_recovery_margin"), r2(r["amount"] - r["cost"]))]
        elif r["kind"] == "equipment":
            lines = [("Equipment recovery %s" % (r["description"] or r["eq_code"] or ""), acct(c, "equipment_recovery"), r["amount"])]
        else:
            lines = [("Deduction: %s" % (r["description"] or r["kind"]), acct(c, "subcon_other_recovery"), r["amount"])]
        for desc, acc, amt in lines:
            if abs(amt) < 0.005:
                continue
            ins(c, "invoice_lines", {"invoice_id": iid, "description": desc, "qty": 1, "rate": -amt, "vat_rate": 0,
                                     "amount": -amt, "account_id": acc, "equipment_id": r["equipment_id"]})
    import api_project as P
    with bypass():
        inv.FUNCS["invoice.post"][0](c, P.sysuser(u), {"id": iid})
    i = q1(c, "SELECT * FROM invoices WHERE id=?", (iid,))
    upd(c, "sc_bills", b["id"], {"status": "posted", "invoice_id": iid, "posted_by": u["id"]})
    c.execute("UPDATE vouchers SET approved_by=?, created_by=? WHERE id=?", (u["id"], b["created_by"], i["voucher_id"]))
    audit(c, u, "post", "sc_bills", b["id"], {"invoice": i["no"], "payable": i["payable"]})
    return {"invoice_id": iid, "invoice_no": i["no"], "payable": i["payable"]}


@api("sco.bill_cancel", "commercial", "edit")
def sc_bill_cancel(c, u, a):
    b = get(c, "sc_bills", int(a["id"]), "Subcontract bill")
    if b["status"] == "posted":
        raise ApiError("A posted bill is cancelled by cancelling its purchase bill in Accounts; then cancel it here.")
    if b["status"] == "cancelled":
        return True
    upd(c, "sc_bills", b["id"], {"status": "cancelled"})
    return True


def _sync_cancelled_bills(c):
    """A purchase bill cancelled in Accounts cancels its subcontract running bill (so its quantities and
    recoveries are free again)."""
    c.execute("UPDATE sc_bills SET status='cancelled' WHERE status='posted' AND invoice_id IN "
              "(SELECT id FROM invoices WHERE status='cancelled')")


@api("sco.bills", "commercial", "view")
def sc_bills(c, u, a):
    _sync_cancelled_bills(c)
    cond, p = ["1=1"], []
    for k in ("project_id", "order_id", "party_id"):
        if a.get(k):
            cond.append("b.%s=?" % k)
            p.append(int(a[k]))
    if a.get("status"):
        cond.append("b.status=?")
        p.append(a["status"])
    return q(c, "SELECT b.*, o.no order_no, o.type, pa.name party, pr.code pcode, i.no invoice_no FROM sc_bills b "
                "JOIN sc_orders o ON o.id=b.order_id LEFT JOIN parties pa ON pa.id=b.party_id LEFT JOIN projects pr ON "
                "pr.id=b.project_id LEFT JOIN invoices i ON i.id=b.invoice_id WHERE " + " AND ".join(cond) +
             " ORDER BY b.date DESC, b.id DESC", p)


# ───────────────────────────── rental deductions ─────────────────────────────
def _terms_for(ag, kind):
    if kind in ("fuel",):
        return ag.get("fuel_terms") or "ours"
    if kind in ("operator",):
        return ag.get("operator_terms") or "ours"
    return ag.get("maint_terms") or "ours"


def _rented_agreements(c, equipment_id, d):
    return q(c, "SELECT * FROM hire_agreements WHERE equipment_id=? AND COALESCE(active,1)=1 AND "
                "(start_date IS NULL OR start_date<=?) AND (end_date IS NULL OR end_date='' OR end_date>=?) ORDER BY id DESC",
             (equipment_id, d, d))


def _candidates(c, ag, upto):
    """Costs we booked on the hired machine (store issues of fuel and spares, repair and service bills)."""
    out = []
    for r in q(c, "SELECT l.id, l.amount, l.material_id, i.date, i.no, l.qty FROM issue_lines l JOIN issues i ON i.id=l.issue_id "
                  "WHERE l.equipment_id=? AND i.status='posted' AND i.date<=? AND (? IS NULL OR i.date>=?)",
                  (ag["equipment_id"], upto, ag["start_date"], ag["start_date"])):
        mat = material(c, r["material_id"])
        role = inventory_role(mat)
        kind = "fuel" if role == "inventory_fuel" else ("spares" if role == "inventory_spares" else "servicing")
        out.append({"source": "issue_line", "source_id": r["id"], "date": r["date"], "kind": kind,
                    "description": "%s %s %s" % (r["no"], mat["name"], r4(r["qty"])), "amount": r2(r["amount"]),
                    "account_id": core.role_account(c, core.consumption_role(mat, "equipment"))})
    for r in q(c, "SELECT l.id, l.amount, l.account_id, l.description, i.date, i.no FROM invoice_lines l JOIN invoices i ON i.id=l.invoice_id "
                  "WHERE l.equipment_id=? AND i.kind='purchase' AND COALESCE(i.source,'')<>'hire' AND l.amount>0 AND "
                  "i.status IN ('posted','awaiting_posting') AND i.date<=? AND (? IS NULL OR i.date>=?)",
                  (ag["equipment_id"], upto, ag["start_date"], ag["start_date"])):
        out.append({"source": "invoice_line", "source_id": r["id"], "date": r["date"], "kind": "repair",
                    "description": "%s %s" % (r["no"] or "", r["description"] or ""), "amount": r2(r["amount"]),
                    "account_id": r["account_id"]})
    return out


def _collect_deductions(c, u, ag, upto):
    """Turn every cost the agreement says to deduct into a rental deduction (once)."""
    for x in _candidates(c, ag, upto):
        if _terms_for(ag, x["kind"]) != "deduct":
            continue
        if q1(c, "SELECT id FROM rent_deductions WHERE source=? AND source_id=?", (x["source"], x["source_id"])):
            continue
        ins(c, "rent_deductions", {"agreement_id": ag["id"], "equipment_id": ag["equipment_id"], "date": x["date"],
                                   "kind": x["kind"], "description": x["description"], "amount": x["amount"],
                                   "account_id": x["account_id"], "source": x["source"], "source_id": x["source_id"],
                                   "status": "open", "created_by": u["id"] if u else None, "ts": now()})


def _open_deductions(c, ag_id, upto):
    # a deduction put on a hire bill that was later deleted or cancelled is open again
    c.execute("UPDATE rent_deductions SET status='open', invoice_id=NULL WHERE agreement_id=? AND status='billed' AND "
              "(invoice_id NOT IN (SELECT id FROM invoices) OR invoice_id IN (SELECT id FROM invoices WHERE status='cancelled'))",
              (ag_id,))
    return q(c, "SELECT * FROM rent_deductions WHERE agreement_id=? AND status='open' AND date<=? ORDER BY date, id", (ag_id, upto))


@api("rent.agreements", "equipment", "view")
def rent_agreements(c, u, a):
    rows = q(c, "SELECT h.*, e.code eq_code, e.name eq_name, pa.name owner, p.code pcode FROM hire_agreements h "
                "LEFT JOIN equipment e ON e.id=h.equipment_id LEFT JOIN parties pa ON pa.id=h.vendor_id "
                "LEFT JOIN projects p ON p.id=h.project_id ORDER BY h.id DESC")
    for r in rows:
        if a.get("refresh"):
            _collect_deductions(c, u, r, today())
        r["open_deductions"] = r2(val(c, "SELECT SUM(amount) FROM rent_deductions WHERE agreement_id=? AND status='open'", (r["id"],)))
        r["deducted"] = r2(val(c, "SELECT SUM(amount) FROM rent_deductions WHERE agreement_id=? AND status='billed'", (r["id"],)))
    return rows


@api("rent.terms_save", "equipment", "edit")
def rent_terms_save(c, u, a):
    ag = get(c, "hire_agreements", int(a["id"]), "Hire agreement")
    ch = {}
    for k in ("maint_terms", "fuel_terms", "operator_terms"):
        if k in a:
            if a[k] not in dict(TERMS):
                raise ApiError("Unknown terms.")
            ch[k] = a[k]
    upd(c, "hire_agreements", ag["id"], ch)
    audit(c, u, "terms", "hire_agreements", ag["id"], ch)
    return True


@api("rent.deductions", "equipment", "view")
def rent_deductions(c, u, a):
    ag = get(c, "hire_agreements", int(a["agreement_id"]), "Hire agreement")
    _collect_deductions(c, u, ag, today())
    _open_deductions(c, ag["id"], "9999")
    rows = q(c, "SELECT d.*, x.code acode, x.name aname, i.no invoice_no FROM rent_deductions d LEFT JOIN accounts x ON "
                "x.id=d.account_id LEFT JOIN invoices i ON i.id=d.invoice_id WHERE d.agreement_id=? ORDER BY d.date, d.id", (ag["id"],))
    cands = [x for x in _candidates(c, ag, today())
             if not q1(c, "SELECT id FROM rent_deductions WHERE source=? AND source_id=?", (x["source"], x["source_id"]))]
    return {"agreement": ag, "rows": rows, "candidates": cands}


@api("rent.deduction_add", "equipment", "edit")
def rent_deduction_add(c, u, a):
    """Add a deduction by hand, or take one of the suggested costs although the terms say otherwise."""
    ag = get(c, "hire_agreements", int(a["agreement_id"]), "Hire agreement")
    if a.get("source") and a.get("source_id"):
        x = [k for k in _candidates(c, ag, "9999") if k["source"] == a["source"] and str(k["source_id"]) == str(a["source_id"])]
        if not x:
            raise ApiError("That cost was not found on this machine.")
        x = x[0]
        if q1(c, "SELECT id FROM rent_deductions WHERE source=? AND source_id=?", (x["source"], x["source_id"])):
            raise ApiError("Already a deduction.")
        row = x
    else:
        need(a, "date", "amount")
        row = {"date": a["date"], "kind": a.get("kind") or "other", "description": a.get("description"),
               "amount": r2(num(a["amount"])), "source": "manual", "source_id": None,
               "account_id": int(a["account_id"]) if a.get("account_id") else acct(c, "repair_cost")}
        if row["amount"] <= 0:
            raise ApiError("Enter the amount to deduct.")
    rid = ins(c, "rent_deductions", dict(row, agreement_id=ag["id"], equipment_id=ag["equipment_id"], status="open",
                                         created_by=u["id"], ts=now()))
    audit(c, u, "add", "rent_deductions", rid, row)
    return {"id": rid}


@api("rent.deduction_waive", "equipment", "approve")
def rent_deduction_waive(c, u, a):
    d = get(c, "rent_deductions", int(a["id"]), "Deduction")
    if d["status"] == "billed":
        raise ApiError("Already deducted on a hire bill.")
    upd(c, "rent_deductions", d["id"], {"status": "open" if d["status"] == "waived" else "waived"})
    return True


@api("rent.statement", "equipment", "view")
def rent_statement(c, u, a):
    """Per hired machine and month: units, gross hire, deductions and net payable."""
    ag = get(c, "hire_agreements", int(a["agreement_id"]), "Hire agreement")
    rows = []
    for b in q(c, "SELECT b.*, i.no invoice_no, i.status inv_status, i.payable FROM hire_bills b LEFT JOIN invoices i ON i.id=b.invoice_id "
                  "WHERE b.agreement_id=? ORDER BY b.month", (ag["id"],)):
        ded = r2(val(c, "SELECT SUM(amount) FROM rent_deductions WHERE invoice_id=?", (b["invoice_id"],)))
        gross = r2(val(c, "SELECT SUM(amount) FROM invoice_lines WHERE invoice_id=? AND amount>0", (b["invoice_id"],)))
        rows.append({"month": b["month"], "units": b["units"], "billed_units": b["billed_units"], "gross": gross,
                     "deductions": ded, "net": r2(gross - ded), "invoice_no": b["invoice_no"], "status": b["inv_status"],
                     "payable": b["payable"]})
    return {"agreement": ag, "rows": rows, "open": r2(val(c, "SELECT SUM(amount) FROM rent_deductions WHERE agreement_id=? AND "
                                                             "status='open'", (ag["id"],)))}


# ───────────────────────────── owned equipment: finance and cost per unit ─────────────────────────────
@api("eqf.get", "equipment", "view")
def eqf_get(c, u, a):
    e = get(c, "equipment", int(a["equipment_id"]), "Equipment")
    f = q1(c, "SELECT * FROM eq_finance WHERE equipment_id=?", (e["id"],)) or \
        {"equipment_id": e["id"], "price": e["purchase_value"], "basis": "km" if (e["meter_type"] or "") == "km" else "hour",
         "life_units": e["est_total_hours"] or 0}
    f["emis"] = q(c, "SELECT m.*, v.no vno, v.status vstatus FROM eq_emi m LEFT JOIN vouchers v ON v.id=m.voucher_id "
                     "WHERE m.equipment_id=? ORDER BY m.date", (e["id"],))
    f["paid"] = r2(sum(x["amount"] for x in f["emis"]))
    f["principal_paid"] = r2(sum(x["principal"] for x in f["emis"]))
    f["loan_left"] = r2((f.get("loan_amount") or 0) - f["principal_paid"])
    f["equipment"] = e
    return f


@api("eqf.save", "equipment", "edit")
def eqf_save(c, u, a):
    e = get(c, "equipment", int(a["equipment_id"]), "Equipment")
    if (a.get("basis") or "hour") not in ("hour", "km", "day", "output"):
        raise ApiError("Basis must be hour, km, day or output.")
    d = {"equipment_id": e["id"], "price": num(a.get("price") or 0), "down_payment": num(a.get("down_payment") or 0),
         "loan_amount": num(a.get("loan_amount") or 0), "lender": a.get("lender"), "emi": num(a.get("emi") or 0),
         "emi_count": int(num(a.get("emi_count") or 0)), "first_emi_date": a.get("first_emi_date"),
         "interest_rate": num(a.get("interest_rate") or 0), "life_units": num(a.get("life_units") or 0),
         "basis": a.get("basis") or "hour", "output_unit": a.get("output_unit"), "market_rate": num(a.get("market_rate") or 0),
         "notes": a.get("notes"), "ts": now()}
    if d["down_payment"] > d["price"] + EPS and d["price"]:
        raise ApiError("Down payment is more than the price.")
    keys = list(d.keys())
    c.execute("INSERT OR REPLACE INTO eq_finance(%s) VALUES(%s)" % (",".join(keys), ",".join("?" * len(keys))), [d[k] for k in keys])
    audit(c, u, "save", "eq_finance", e["id"], d)
    return eqf_get(c, u, {"equipment_id": e["id"]})


def _split_emi(c, f, amount, d):
    """Interest part of an EMI from the outstanding loan and the yearly rate; the rest is principal."""
    paid = val(c, "SELECT SUM(principal) FROM eq_emi WHERE equipment_id=?", (f["equipment_id"],)) or 0
    left = max(0.0, (f["loan_amount"] or 0) - paid)
    interest = r2(left * (f["interest_rate"] or 0) / 1200)
    interest = min(interest, amount)
    return r2(amount - interest), interest


@api("eqf.emi_add", "equipment", "edit")
def eqf_emi_add(c, u, a):
    """Record an EMI as paid. Accounts posts it from the queue: Dr equipment loan (principal), Dr interest, Cr bank."""
    need(a, "equipment_id", "date", "amount")
    f = q1(c, "SELECT * FROM eq_finance WHERE equipment_id=?", (int(a["equipment_id"]),))
    if not f:
        raise ApiError("Enter the machine's finance (price, down payment, loan) first.")
    amt = r2(num(a["amount"]))
    if amt <= 0:
        raise ApiError("Enter the EMI amount.")
    if a.get("principal") not in (None, ""):
        pr = r2(num(a["principal"]))
        it = r2(amt - pr)
    else:
        pr, it = _split_emi(c, f, amt, a["date"])
    if pr < -EPS or it < -EPS:
        raise ApiError("Principal and interest cannot be negative.")
    rid = ins(c, "eq_emi", {"equipment_id": f["equipment_id"], "date": a["date"], "amount": amt, "principal": pr,
                            "interest": it, "bank_account_id": int(a["bank_account_id"]) if a.get("bank_account_id") else None,
                            "remarks": a.get("remarks"), "created_by": u["id"], "ts": now()})
    vid = None
    if a.get("bank_account_id"):
        e = get(c, "equipment", f["equipment_id"])
        acct(c, "equipment_loan")
        vid = core.post_voucher(c, u, "payment", a["date"], "EMI %s %s" % (e["code"], f.get("lender") or ""),
                                [{"role": "equipment_loan", "debit": pr, "equipment_id": e["id"]},
                                 {"role": "interest_expense", "debit": it, "equipment_id": e["id"], "project_id": e["project_id"]},
                                 {"account_id": int(a["bank_account_id"]), "credit": amt}],
                                project_id=None, source="emi", source_id=rid)
        upd(c, "eq_emi", rid, {"voucher_id": vid})
    audit(c, u, "emi", "eq_emi", rid, {"amount": amt, "principal": pr, "interest": it})
    return {"id": rid, "principal": pr, "interest": it, "voucher_id": vid}


@api("eqf.emi_delete", "equipment", "edit")
def eqf_emi_delete(c, u, a):
    m = get(c, "eq_emi", int(a["id"]), "EMI")
    if m["voucher_id"] and val(c, "SELECT status FROM vouchers WHERE id=?", (m["voucher_id"],)) in ("posted", "reversed"):
        raise ApiError("This EMI is posted. Reverse it in Accounts.")
    if m["voucher_id"]:
        _drop_parked(c, "emi", m["id"])
    c.execute("DELETE FROM eq_emi WHERE id=?", (m["id"],))
    return True


def _months(frm, to):
    y, m = int(frm[:4]), int(frm[5:7])
    out = []
    while "%04d-%02d" % (y, m) <= to[:7]:
        out.append("%04d-%02d" % (y, m))
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out


def _units(c, e, basis, frm, to):
    if basis == "km":
        return r2(val(c, "SELECT SUM(COALESCE(km_run, km_end-km_start, 0)) FROM logsheets WHERE equipment_id=? AND date BETWEEN ? AND ?",
                      (e["id"], frm, to)))
    if basis == "day":
        return val(c, "SELECT COUNT(DISTINCT date) FROM logsheets WHERE equipment_id=? AND hours>0 AND date BETWEEN ? AND ?",
                   (e["id"], frm, to))
    if basis == "output":
        try:
            return r2(val(c, "SELECT SUM(e.output_qty) FROM dpr_equipment e JOIN dpr d ON d.id=e.dpr_id WHERE e.equipment_id=? "
                             "AND d.date BETWEEN ? AND ?", (e["id"], frm, to)))
        except Exception:
            return 0
    return r2(val(c, "SELECT SUM(hours) FROM logsheets WHERE equipment_id=? AND date BETWEEN ? AND ?", (e["id"], frm, to)))


def _gl_eq(c, eid, frm, to, roles=None, exclude=None, types=("expense",), sign=1):
    cond, p = ["l.equipment_id=?", "v.date BETWEEN ? AND ?", POSTED], [eid, frm, to]
    cond.append("x.type IN (%s)" % ",".join("?" * len(types)))
    p += list(types)
    if roles:
        cond.append("x.role IN (%s)" % ",".join("?" * len(roles)))
        p += list(roles)
    if exclude:
        cond.append("COALESCE(x.role,'') NOT IN (%s)" % ",".join("?" * len(exclude)))
        p += list(exclude)
    return r2(sign * val(c, "SELECT SUM(l.debit-l.credit) FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id JOIN accounts x "
                            "ON x.id=l.account_id WHERE " + " AND ".join(cond), p))


DEP_ROLES = ("depreciation", "fa_dep", "dep_expense", "rou_dep")
NOT_OPERATING = DEP_ROLES + ("equipment_cost", "interest_expense", "equip_job_cost", "lease_interest", "hire_cost")


def _internal_rate(c, e):
    r = q1(c, "SELECT * FROM equipment_rates WHERE equipment_id=? ORDER BY effective_from DESC, id DESC LIMIT 1", (e["id"],))
    if r:
        base = sum((r[k] or 0) for k in ("ownership_hr", "fuel_hr", "operator_hr", "maintenance_hr", "insurance_hr"))
        return r2(base * (1 + (r["overhead_pct"] or 0) / 100))
    return e["internal_rate"] or 0


def eq_cost_row(c, e, frm, to):
    f = q1(c, "SELECT * FROM eq_finance WHERE equipment_id=?", (e["id"],)) or {}
    basis = f.get("basis") or "hour"
    units = _units(c, e, basis, frm, to)
    hours = r2(val(c, "SELECT SUM(hours) FROM logsheets WHERE equipment_id=? AND date BETWEEN ? AND ?", (e["id"], frm, to)))
    idle = q1(c, "SELECT SUM(idle_hours) idle, SUM(breakdown_hours) bd, SUM(COALESCE(standby_hours,0)) sb FROM logsheets "
                 "WHERE equipment_id=? AND date BETWEEN ? AND ?", (e["id"], frm, to)) or {}
    days = (date.fromisoformat(to) - date.fromisoformat(frm)).days + 1
    shift = core.fsetting(c, "shift_hours") or 10
    available = r2(days * shift)
    emp_idle = r2(val(c, "SELECT SUM(l.idle_hours + COALESCE(l.standby_hours,0)) FROM logsheets l WHERE l.equipment_id=? AND "
                         "l.date BETWEEN ? AND ? AND EXISTS (SELECT 1 FROM dpr_delays dd JOIN dpr d ON d.id=dd.dpr_id WHERE "
                         "d.project_id=l.project_id AND d.date=l.date AND COALESCE(dd.responsibility, CASE dd.category %s END)='employer')"
                      % " ".join("WHEN '%s' THEN '%s'" % kv for kv in CAT_RESP.items()), (e["id"], frm, to)))
    operating = _gl_eq(c, e["id"], frm, to, exclude=NOT_OPERATING)
    dep = _gl_eq(c, e["id"], frm, to, roles=DEP_ROLES)
    emi = q1(c, "SELECT SUM(amount) amt, SUM(interest) it, SUM(principal) pr FROM eq_emi WHERE equipment_id=? AND date BETWEEN ? AND ?",
             (e["id"], frm, to)) or {}
    down_share = r2((f.get("down_payment") or 0) / f["life_units"] * units) if f.get("life_units") else 0
    emi_amt = r2(emi.get("amt") or 0)
    interest = r2(emi.get("it") or 0)
    cash = r2(operating + emi_amt + down_share)
    econ = r2(operating + dep + interest)
    earned = _gl_eq(c, e["id"], frm, to, roles=("equipment_recovery", "equip_recovery"), types=("income",), sign=-1)
    hire_out = _gl_eq(c, e["id"], frm, to, exclude=("equipment_recovery", "equip_recovery"), types=("income",), sign=-1)
    rate = _internal_rate(c, e)
    return {"equipment_id": e["id"], "code": e["code"], "name": e["name"], "basis": basis, "units": units, "hours": hours,
            "available_hours": available, "utilisation_pct": r2(hours / available * 100) if available else None,
            "idle_hours": r2(idle.get("idle") or 0), "breakdown_hours": r2(idle.get("bd") or 0),
            "standby_hours": r2(idle.get("sb") or 0), "employer_idle_hours": emp_idle,
            "operating": operating, "depreciation": dep, "emi_paid": emi_amt, "interest": interest,
            "principal": r2(emi.get("pr") or 0), "down_share": down_share,
            "cash_cost": cash, "economic_cost": econ,
            "cash_per_unit": r2(cash / units) if units else None, "economic_per_unit": r2(econ / units) if units else None,
            "operating_per_unit": r2(operating / units) if units else None,
            "internal_rate": rate, "market_rate": f.get("market_rate") or 0, "earned": earned, "hire_out": hire_out,
            "employer_idle_cost": r2(emp_idle * (rate or 0)),
            "own_vs_rent": (r2((f.get("market_rate") or 0) - econ / units) if units and f.get("market_rate") else None)}


@api("eqc.report", "equipment", "view")
def eqc_report(c, u, a):
    """Cost per working unit of every owned machine: cash view and economic view, utilisation and idle time."""
    frm = a.get("from") or (today()[:8] + "01")
    to = a.get("to") or today()
    cond, p = "COALESCE(ownership,'owned')='owned' AND COALESCE(active,1)=1", []
    if a.get("equipment_id"):
        cond += " AND id=?"
        p.append(int(a["equipment_id"]))
    if a.get("project_id"):
        cond += " AND project_id=?"
        p.append(int(a["project_id"]))
    rows = [eq_cost_row(c, e, frm, to) for e in q(c, "SELECT * FROM equipment WHERE " + cond + " ORDER BY code", p)]
    return {"from": frm, "to": to, "rows": rows}


@api("eqc.trend", "equipment", "view")
def eqc_trend(c, u, a):
    e = get(c, "equipment", int(a["equipment_id"]), "Equipment")
    to = a.get("to") or today()
    frm = a.get("from") or (date.fromisoformat(to[:8] + "01") - timedelta(days=330)).isoformat()[:8] + "01"
    out = []
    for m in _months(frm, to):
        out.append(dict(eq_cost_row(c, e, m + "-01", core.month_end(m)), month=m))
    return out


# ───────────────────────────── delays by responsibility ─────────────────────────────
def _resp_sql(alias="dd"):
    return "COALESCE(%s.responsibility, CASE %s.category %s ELSE 'contractor' END)" % (
        alias, alias, " ".join("WHEN '%s' THEN '%s'" % kv for kv in CAT_RESP.items()))


@api("delay.list", "project", "view")
def delay_list(c, u, a):
    need(a, "project_id")
    pid = int(a["project_id"])
    frm, to = a.get("from") or "0000-01-01", a.get("to") or "9999-12-31"
    rows = q(c, "SELECT dd.*, d.date, d.no dpr_no, d.status dpr_status, %s resp, act.name activity FROM dpr_delays dd JOIN dpr d ON "
                "d.id=dd.dpr_id LEFT JOIN activities act ON act.id=dd.activity_id WHERE d.project_id=? AND d.date BETWEEN ? AND ? "
                "ORDER BY d.date DESC, dd.id" % _resp_sql(), (pid, frm, to))
    ev = q(c, "SELECT e.*, COALESCE(e.responsibility, CASE WHEN e.compensable=1 THEN 'employer' WHEN e.concurrent=1 THEN 'concurrent' "
              "WHEN e.excusable=1 THEN 'neutral' ELSE NULL END) resp FROM events e WHERE e.project_id=? AND COALESCE(e.type,'delay')='delay' "
              "AND COALESCE(e.date,'') BETWEEN ? AND ? ORDER BY e.date DESC", (pid, frm, to)) if _has_cols(c, "events", "compensable") else \
        q(c, "SELECT e.*, e.responsibility resp FROM events e WHERE e.project_id=? AND COALESCE(e.type,'delay')='delay' "
             "AND COALESCE(e.date,'') BETWEEN ? AND ? ORDER BY e.date DESC", (pid, frm, to))
    return {"dpr": rows, "events": ev}


def _has_cols(c, t, col):
    return col in {r[1] for r in c.execute("PRAGMA table_info(%s)" % t)}


@api("delay.classify", "project", "edit")
def delay_classify(c, u, a):
    resp = a.get("responsibility")
    if resp not in dict(RESP):
        raise ApiError("Choose who is responsible: employer, own, neutral or concurrent.")
    if a.get("kind") == "event":
        e = get(c, "events", int(a["id"]), "Event")
        ch = {"responsibility": resp}
        if _has_cols(c, "events", "compensable"):
            ex, comp, conc = RESP_FLAGS[resp]
            ch.update({"excusable": ex, "compensable": comp, "concurrent": conc})
        upd(c, "events", e["id"], ch)
        for dd in q(c, "SELECT id FROM dpr_delays WHERE event_id=?", (e["id"],)):
            upd(c, "dpr_delays", dd["id"], {"responsibility": resp})
    else:
        dd = get(c, "dpr_delays", int(a["id"]), "Delay")
        upd(c, "dpr_delays", dd["id"], {"responsibility": resp})
    audit(c, u, "classify", "delay", int(a["id"]), {"kind": a.get("kind"), "responsibility": resp})
    return True


@api("delay.summary", "project", "view")
def delay_summary(c, u, a):
    """Days lost by who caused them; idle machine cost on employer-delay days (claimable); own delay days x LD."""
    need(a, "project_id")
    pid = int(a["project_id"])
    p = get(c, "projects", pid, "Project")
    frm, to = a.get("from") or "0000-01-01", a.get("to") or "9999-12-31"
    shift = core.fsetting(c, "shift_hours") or 10
    by = {k: {"resp": k, "label": n, "hours": 0.0, "days": 0.0, "entries": 0, "event_days": 0.0, "eot_claimed": 0.0,
              "eot_granted": 0.0, "cost_impact": 0.0} for k, n in RESP}
    for r in q(c, "SELECT %s resp, SUM(dd.hours) h, COUNT(*) n, COUNT(DISTINCT d.date) dd FROM dpr_delays dd JOIN dpr d ON d.id=dd.dpr_id "
                  "WHERE d.project_id=? AND d.date BETWEEN ? AND ? GROUP BY 1" % _resp_sql(), (pid, frm, to)):
        b = by.setdefault(r["resp"], {"resp": r["resp"], "label": r["resp"], "hours": 0, "days": 0, "entries": 0,
                                      "event_days": 0, "eot_claimed": 0, "eot_granted": 0, "cost_impact": 0})
        b["hours"], b["entries"], b["days"] = r2(r["h"] or 0), r["n"], r2((r["h"] or 0) / shift)
        b["calendar_days"] = r["dd"]
    ev = delay_list(c, u, {"project_id": pid, "from": frm, "to": to})["events"]
    for e in ev:
        b = by.get(e["resp"] or "contractor")
        if not b:
            continue
        b["event_days"] = r2(b["event_days"] + (e.get("delay_days") or 0))
        b["eot_claimed"] = r2(b["eot_claimed"] + (e.get("eot_claimed") or 0))
        b["eot_granted"] = r2(b["eot_granted"] + (e.get("eot_granted") or 0))
        b["cost_impact"] = r2(b["cost_impact"] + (e.get("cost_impact") or 0))
    # idle machines on days with an employer delay at this project
    idle = q(c, "SELECT l.equipment_id, eq.code, SUM(l.idle_hours + COALESCE(l.standby_hours,0)) h FROM logsheets l JOIN equipment eq "
                "ON eq.id=l.equipment_id WHERE l.project_id=? AND l.date BETWEEN ? AND ? AND EXISTS (SELECT 1 FROM dpr_delays dd JOIN "
                "dpr d ON d.id=dd.dpr_id WHERE d.project_id=l.project_id AND d.date=l.date AND %s='employer') GROUP BY l.equipment_id"
             % _resp_sql(), (pid, frm, to))
    claim = 0.0
    for r in idle:
        e = get(c, "equipment", r["equipment_id"])
        rate = _internal_rate(c, e) or 0
        hag = q1(c, "SELECT rate, unit FROM hire_agreements WHERE equipment_id=? ORDER BY id DESC LIMIT 1", (e["id"],))
        if (e["ownership"] or "owned") != "owned" and hag and hag["unit"] == "hour":
            rate = hag["rate"] or rate
        r["rate"] = rate
        r["cost"] = r2((r["h"] or 0) * rate)
        claim += r["cost"]
    ld_day = 0.0
    try:
        ld_day = p.get("ld_per_day") or 0
    except Exception:
        pass
    own_days = by["contractor"]["event_days"] or by["contractor"]["days"]
    prolong = p.get("indirect_per_day") or 0
    emp_days = by["employer"]["event_days"] or by["employer"]["days"]
    return {"by": list(by.values()), "idle_equipment": idle, "claimable_idle_cost": r2(claim),
            "prolongation_cost": r2(emp_days * prolong), "indirect_per_day": prolong,
            "ld_per_day": ld_day, "ld_exposure": r2(own_days * ld_day), "own_days": r2(own_days), "employer_days": r2(emp_days)}


# ───────────────────────────── returns: company, machines, small-asset pools ─────────────────────────────
def _bal(c, types, upto, roles_out=()):
    """Balance of all accounts of the given types at a date (debit positive), from the posted ledger."""
    ph = ",".join("?" * len(types))
    ob = val(c, "SELECT SUM(opening_balance) FROM accounts WHERE type IN (%s)" % ph, list(types))
    mv = val(c, "SELECT SUM(l.debit-l.credit) FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id JOIN accounts x ON "
                "x.id=l.account_id WHERE x.type IN (%s) AND v.date<=? AND %s" % (ph, POSTED), list(types) + [upto])
    return r2((ob or 0) + (mv or 0))


def _pl(c, frm, to):
    inc = -val(c, "SELECT SUM(l.debit-l.credit) FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id JOIN accounts x ON "
                  "x.id=l.account_id WHERE x.type='income' AND v.date BETWEEN ? AND ? AND " + POSTED +
               " AND COALESCE(x.role,'') NOT IN ('equipment_recovery','equip_recovery') AND COALESCE(v.source,'') NOT IN ('fy_close','closing')", (frm, to))
    rec = -val(c, "SELECT SUM(l.debit-l.credit) FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id JOIN accounts x ON "
                  "x.id=l.account_id WHERE x.type='income' AND v.date BETWEEN ? AND ? AND " + POSTED +
               " AND COALESCE(x.role,'') IN ('equipment_recovery','equip_recovery')", (frm, to))
    exp = val(c, "SELECT SUM(l.debit-l.credit) FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id JOIN accounts x ON "
                 "x.id=l.account_id WHERE x.type='expense' AND v.date BETWEEN ? AND ? AND " + POSTED +
              " AND COALESCE(v.source,'') NOT IN ('fy_close','closing')", (frm, to))
    # internal hire is income and cost of the same company: net it out of both
    return r2(inc), r2((exp or 0) - (rec or 0))


def _position(c, d):
    assets = _bal(c, ("asset",), d)
    liab = -_bal(c, ("liability",), d)
    return assets, liab, r2(assets - liab)   # equity = assets - liabilities (includes this year's profit)


def _ret_period(c, frm, to):
    rev, exp = _pl(c, frm, to)
    np_ = r2(rev - exp)
    before = (date.fromisoformat(frm) - timedelta(days=1)).isoformat()
    a0, l0, e0 = _position(c, before)
    a1, l1, e1 = _position(c, to)
    avg_a, avg_e = r2((a0 + a1) / 2), r2((e0 + e1) / 2)
    days = (date.fromisoformat(to) - date.fromisoformat(frm)).days + 1
    ann = 365.0 / days if days > 0 else 1
    margin = np_ / rev if rev else None
    turnover = rev * ann / avg_a if avg_a else None
    mult = avg_a / avg_e if avg_e else None
    return {"from": frm, "to": to, "days": days, "revenue": rev, "expenses": exp, "net_profit": np_,
            "assets_open": a0, "assets_close": a1, "avg_assets": avg_a, "equity_open": e0, "equity_close": e1,
            "avg_equity": avg_e, "liabilities_close": l1,
            "roa_pct": r2(np_ * ann / avg_a * 100) if avg_a else None,
            "roe_pct": r2(np_ * ann / avg_e * 100) if avg_e > 0 else None,
            "net_margin_pct": r2(margin * 100) if margin is not None else None,
            "asset_turnover": r4(turnover) if turnover is not None else None,
            "equity_multiplier": r4(mult) if mult is not None else None,
            "annualised": days < 360}


def _fy_bounds(c, d):
    p = core.period_for(c, d)
    if p:
        r = q1(c, "SELECT MIN(start_date) s, MAX(end_date) e FROM fiscal_periods WHERE fy=?", (p["fy"],))
        if r and r["s"]:
            return r["s"], r["e"], p["fy"]
    y = int(d[:4]) - (1 if d[5:] < "07-16" else 0)
    return "%d-07-16" % y, "%d-07-15" % (y + 1), "%d-%s" % (y, str(y + 1)[-2:])


@api("ret.company", "accounts", "view")
def ret_company(c, u, a):
    """ROA, ROE and the DuPont split (net margin x asset turnover x equity multiplier) for this FY to date,
    the trailing 12 months and last FY, from the posted ledger."""
    to = a.get("to") or today()
    s, e, fy = _fy_bounds(c, to)
    ps, pe, pfy = _fy_bounds(c, (date.fromisoformat(s) - timedelta(days=1)).isoformat())
    t12 = (date.fromisoformat(to) - timedelta(days=364)).isoformat()
    trend = []
    for m in _months((date.fromisoformat(to[:8] + "01") - timedelta(days=330)).isoformat()[:7], to[:7]):
        me = min(core.month_end(m), to)
        st = (date.fromisoformat(me) - timedelta(days=364)).isoformat()
        r = _ret_period(c, st, me)
        trend.append({"month": m, "roa_pct": r["roa_pct"], "roe_pct": r["roe_pct"], "net_margin_pct": r["net_margin_pct"]})
    return {"fy": dict(_ret_period(c, s, to), label="FY %s to date" % fy),
            "ttm": dict(_ret_period(c, t12, to), label="Last 12 months"),
            "last_fy": dict(_ret_period(c, ps, pe), label="FY %s" % pfy),
            "trend": trend}


def _nbv(c, e, d):
    dep = -_gl_eq(c, e["id"], "0000-01-01", d, roles=("accum_dep", "fa_accum", "ppe_accum"), types=("asset",))
    ledger_acc = r2(dep) if dep else 0
    acc = max(ledger_acc, 0) if ledger_acc else (e["accumulated_dep"] or 0)
    return r2(max(0.0, (e["purchase_value"] or 0) - acc))


@api("ret.assets", "equipment", "view")
def ret_assets(c, u, a):
    """Return per owned machine: earnings (internal hire recovery + hire-out income) less operating cost and
    depreciation, on average book value, annualised; plus cash payback on the money put in."""
    to = a.get("to") or today()
    frm = a.get("from") or _fy_bounds(c, to)[0]
    days = (date.fromisoformat(to) - date.fromisoformat(frm)).days + 1
    ann = 365.0 / days if days > 0 else 1
    out = []
    for e in q(c, "SELECT * FROM equipment WHERE COALESCE(ownership,'owned')='owned' AND COALESCE(active,1)=1 ORDER BY code"):
        r = eq_cost_row(c, e, frm, to)
        earn = r2(r["earned"] + r["hire_out"])
        contrib = r2(earn - r["operating"] - r["depreciation"])
        nbv0 = _nbv(c, e, (date.fromisoformat(frm) - timedelta(days=1)).isoformat())
        nbv1 = _nbv(c, e, to)
        avg = r2((nbv0 + nbv1) / 2)
        f = q1(c, "SELECT * FROM eq_finance WHERE equipment_id=?", (e["id"],)) or {}
        invested = r2((f.get("down_payment") or 0) + val(c, "SELECT SUM(amount) FROM eq_emi WHERE equipment_id=?", (e["id"],)))
        life_cash = r2(_gl_eq(c, e["id"], "0000-01-01", to, roles=("equipment_recovery", "equip_recovery"), types=("income",), sign=-1)
                       + _gl_eq(c, e["id"], "0000-01-01", to, exclude=("equipment_recovery", "equip_recovery"), types=("income",), sign=-1)
                       - _gl_eq(c, e["id"], "0000-01-01", to, exclude=NOT_OPERATING))
        out.append({"equipment_id": e["id"], "code": e["code"], "name": e["name"], "earned": earn, "operating": r["operating"],
                    "depreciation": r["depreciation"], "contribution": contrib, "nbv": nbv1, "avg_nbv": avg,
                    "roa_pct": r2(contrib * ann / avg * 100) if avg > 0 else None, "utilisation_pct": r["utilisation_pct"],
                    "hours": r["hours"], "cash_invested": invested, "cash_back": life_cash,
                    "payback_pct": r2(life_cash / invested * 100) if invested else None})
    out.sort(key=lambda x: (x["roa_pct"] is None, -(x["roa_pct"] or 0)))
    pools = sa_report(c, u, {"from": frm, "to": to})
    return {"from": frm, "to": to, "machines": out, "pools": pools["rows"]}


# ── small-asset pools (mixers, tools, scaffolding, shuttering, props) ──
@api("sa.pools", "assets", "view")
def sa_pools(c, u, a):
    rows = q(c, "SELECT * FROM sa_pools ORDER BY class, code")
    for p in rows:
        p["deployed"] = _deployed(c, p["id"], today())
        p["lost"] = r4(val(c, "SELECT SUM(qty) FROM sa_moves WHERE pool_id=? AND kind IN ('loss','dispose')", (p["id"],)))
        p["owned"] = r4(p["qty"] + val(c, "SELECT SUM(qty) FROM sa_moves WHERE pool_id=? AND kind='buy'", (p["id"],)) - p["lost"])
        p["in_yard"] = r4(p["owned"] - sum(p["deployed"].values()))
    return rows


def _deployed(c, pool_id, d, project_id=None):
    out = {}
    for m in q(c, "SELECT project_id, kind, SUM(qty) qty FROM sa_moves WHERE pool_id=? AND date<=? AND project_id IS NOT NULL "
                  "GROUP BY project_id, kind", (pool_id, d)):
        s = {"deploy": 1, "return": -1, "loss": -1, "damage": 0}.get(m["kind"], 0)
        out[m["project_id"]] = r4(out.get(m["project_id"], 0) + s * (m["qty"] or 0))
    out = {k: v for k, v in out.items() if abs(v) > EPS}
    if project_id:
        return out.get(int(project_id), 0)
    return out


@api("sa.save", "assets", "edit")
def sa_save(c, u, a):
    need(a, "code", "name", "unit")
    d = {"code": a["code"].strip(), "name": a["name"], "class": a.get("class") or "other", "unit": a["unit"],
         "qty": num(a.get("qty") or 0), "cost": num(a.get("cost") or 0), "life_months": int(num(a.get("life_months") or 36)),
         "residual_pct": num(a.get("residual_pct") or 0), "rate": num(a.get("rate") or 0),
         "rate_basis": a.get("rate_basis") or "day", "purchase_date": a.get("purchase_date"),
         "active": 0 if a.get("active") in (0, "0", False) else 1, "notes": a.get("notes")}
    if d["rate_basis"] not in ("day", "month"):
        raise ApiError("Hire rate is per unit per day or per month.")
    if a.get("id"):
        upd(c, "sa_pools", int(a["id"]), d)
        return {"id": int(a["id"])}
    if q1(c, "SELECT id FROM sa_pools WHERE code=?", (d["code"],)):
        raise ApiError("Code %s is already used." % d["code"])
    return {"id": ins(c, "sa_pools", d)}


@api("sa.move", "assets", "edit")
def sa_move(c, u, a):
    need(a, "pool_id", "date", "kind", "qty")
    p = get(c, "sa_pools", int(a["pool_id"]), "Small-asset pool")
    kind, qty = a["kind"], num(a["qty"])
    if kind not in ("deploy", "return", "loss", "damage", "buy", "dispose"):
        raise ApiError("Unknown movement.")
    if qty <= 0:
        raise ApiError("Enter the quantity.")
    pid = int(a["project_id"]) if a.get("project_id") else None
    if kind in ("deploy", "return") and not pid:
        raise ApiError("Choose the project.")
    pools = {x["id"]: x for x in sa_pools(c, u, {})}
    cur = pools[p["id"]]
    if kind == "deploy" and qty > cur["in_yard"] + EPS:
        raise ApiError("Only %s %s are in the yard." % (cur["in_yard"], p["unit"]))
    if kind in ("return", "loss") and pid and qty > _deployed(c, p["id"], "9999", pid) + EPS:
        raise ApiError("Only %s %s are at that project." % (_deployed(c, p["id"], "9999", pid), p["unit"]))
    value = num(a.get("value") or 0)
    if kind in ("loss", "dispose") and not value and cur["owned"]:
        value = r2((p["cost"] or 0) / max(cur["owned"], EPS) * qty)
    rid = ins(c, "sa_moves", {"pool_id": p["id"], "project_id": pid, "date": a["date"], "kind": kind, "qty": qty,
                              "value": value, "remarks": a.get("remarks"), "created_by": u["id"], "ts": now()})
    audit(c, u, kind, "sa_moves", rid, {"pool": p["code"], "qty": qty})
    return {"id": rid}


def _unit_days(c, pool_id, project_id, frm, to):
    d0, d1 = date.fromisoformat(frm), date.fromisoformat(to)
    moves = q(c, "SELECT date, kind, qty FROM sa_moves WHERE pool_id=? AND project_id=? AND kind IN ('deploy','return','loss') "
                 "AND date<=? ORDER BY date", (pool_id, project_id, to))
    bal = sum((m["qty"] if m["kind"] == "deploy" else -m["qty"]) for m in moves if m["date"] < frm)
    by_day = {}
    for m in moves:
        if m["date"] >= frm:
            by_day[m["date"]] = by_day.get(m["date"], 0) + (m["qty"] if m["kind"] == "deploy" else -m["qty"])
    total, d = 0.0, d0
    while d <= d1:
        bal += by_day.get(d.isoformat(), 0)
        total += max(bal, 0)
        d += timedelta(days=1)
    return r4(total)


@api("sa.run", "assets", "edit")
def sa_run(c, u, a):
    """Monthly hire of small assets to projects: unit-days x rate. Goes to accounts for posting."""
    need(a, "month")
    m = a["month"]
    frm, to = m + "-01", core.month_end(m)
    dim = calendar.monthrange(int(m[:4]), int(m[5:7]))[1]
    out = []
    for p in q(c, "SELECT * FROM sa_pools WHERE active=1 AND rate>0"):
        for pid in {x["project_id"] for x in q(c, "SELECT DISTINCT project_id FROM sa_moves WHERE pool_id=? AND project_id IS NOT NULL",
                                                 (p["id"],))}:
            if q1(c, "SELECT id FROM sa_runs WHERE month=? AND pool_id=? AND project_id=?", (m, p["id"], pid)):
                continue
            ud = _unit_days(c, p["id"], pid, frm, to)
            if ud <= EPS:
                continue
            amt = r2(ud * p["rate"] if p["rate_basis"] == "day" else ud / dim * p["rate"])
            rid = ins(c, "sa_runs", {"month": m, "pool_id": p["id"], "project_id": pid, "unit_days": ud, "amount": amt, "ts": now()})
            vid = core.post_voucher(c, u, "journal", to, "Small-asset hire %s %s %s unit-days" % (p["code"], m, ud),
                                    [{"role": "equipment_cost", "debit": amt, "project_id": pid},
                                     {"role": "equipment_recovery", "credit": amt, "project_id": pid}],
                                    project_id=pid, source="sa_hire", source_id=rid)
            upd(c, "sa_runs", rid, {"voucher_id": vid})
            out.append({"pool": p["code"], "project_id": pid, "unit_days": ud, "amount": amt})
    audit(c, u, "run", "sa_runs", None, {"month": m, "rows": len(out)})
    return out


@api("sa.report", "assets", "view")
def sa_report(c, u, a):
    """Per pool: utilisation, hire earned, depreciation share, losses and return on book value."""
    to = a.get("to") or today()
    frm = a.get("from") or _fy_bounds(c, to)[0]
    days = (date.fromisoformat(to) - date.fromisoformat(frm)).days + 1
    months = days / 30.4375
    out = []
    for p in sa_pools(c, u, {}):
        owned = p["owned"] or 0
        ud = sum(_unit_days(c, p["id"], pid, frm, to) for pid in
                 {x["project_id"] for x in q(c, "SELECT DISTINCT project_id FROM sa_moves WHERE pool_id=? AND project_id IS NOT NULL", (p["id"],))})
        earned = r2(val(c, "SELECT SUM(r.amount) FROM sa_runs r JOIN vouchers v ON v.id=r.voucher_id WHERE r.pool_id=? AND "
                           "r.month BETWEEN ? AND ? AND v.status IN ('posted','reversed')", (p["id"], frm[:7], to[:7])))
        pending = r2(val(c, "SELECT SUM(r.amount) FROM sa_runs r JOIN vouchers v ON v.id=r.voucher_id WHERE r.pool_id=? AND "
                            "r.month BETWEEN ? AND ? AND v.status='submitted'", (p["id"], frm[:7], to[:7])))
        dep_m = (p["cost"] or 0) * (1 - (p["residual_pct"] or 0) / 100) / max(p["life_months"] or 1, 1)
        dep = r2(dep_m * months)
        losses = r2(val(c, "SELECT SUM(value) FROM sa_moves WHERE pool_id=? AND kind IN ('loss','damage') AND date BETWEEN ? AND ?",
                        (p["id"], frm, to)))
        age_m = 0
        if p["purchase_date"]:
            age_m = max(0, (date.fromisoformat(to) - date.fromisoformat(p["purchase_date"])).days / 30.4375)
        nbv = r2(max(0, (p["cost"] or 0) - dep_m * age_m - val(c, "SELECT SUM(value) FROM sa_moves WHERE pool_id=? AND kind IN "
                                                                 "('loss','dispose') AND date<=?", (p["id"], to))))
        contrib = r2(earned - dep - losses)
        out.append({"pool_id": p["id"], "code": p["code"], "name": p["name"], "class": p["class"], "unit": p["unit"],
                    "owned": owned, "deployed_now": r4(sum(p["deployed"].values())), "unit_days": ud,
                    "utilisation_pct": r2(ud / (owned * days) * 100) if owned and days else None,
                    "earned": earned, "pending": pending, "depreciation": dep, "losses": losses, "contribution": contrib,
                    "nbv": nbv, "roa_pct": r2(contrib * 365.0 / days / nbv * 100) if nbv > 0 and days else None})
    return {"from": frm, "to": to, "rows": out}
