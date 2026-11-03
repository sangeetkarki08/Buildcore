"""BuildCore 2.46.0 — Tally-style accounting: Gateway, groups, ledgers, voucher types, keyboard voucher entry, Edit Log.

From SULAV's "Combined Upgrade Prompt v2" (Tally layer + Oracle controls), first release (phases 0, 1 and 2.1–2.3).
Accountants trained on TallyPrime can record vouchers and read reports in BuildCore with the words and keys they know,
while every record stays the one BuildCore record (no copies):

  * 28 predefined groups (15 primary, 13 sub-groups) + optional contractor pack. They are a second view of the chart of
    accounts: every account gets a Tally group (proposed from its role and BuildCore group, confirmed on the Group
    mapping screen). No voucher line changes, so balances never move.
  * Party ledgers: a vendor posts to Sundry Creditors - Suppliers with the party on the line; the Tally view shows each
    party as its own ledger under Sundry Creditors / Sundry Debtors. One party = one record.
  * Ledger master extras (alias, bill-by-bill, credit days, credit limit, PAN, default TDS) in tl_ledger.
  * 24 predefined voucher types + BuildCore child types; users add child types (e.g. "Site Payment - SMK" under
    Payment) with their own numbering: method, prefix/suffix with {FY} {MM} {PROJECT}, yearly/monthly restart, a series
    per project. Statutory types (Sales, Credit Note, Debit Note and their children) are always automatic, never
    renumbered and never deleted.
  * Keyboard voucher entry (F4 Contra, F5 Payment, F6 Receipt, F7 Journal) with bill-wise New Ref / Agst Ref / Advance /
    On Account, cost centre split (project, BOQ item, machine) and the ledger's current balance. It saves through the
    same engine functions as before (voucher.save / voucher.post, or payment.create for a payment against BuildCore
    bills), so the posting queue, maker-checker, the 2.40 payment-request rule and period locks all still apply.
  * Features (F11), Configure (F12), audit lock date, back-date and alteration limits per job.
  * Alteration policy: "reverse only" (posted vouchers are reversed, the old BuildCore rule) or "edit with log"
    (Tally-like: a manual voucher can be altered while it is not locked; the number is kept).
  * Edit Log: every voucher and master created, altered, cancelled or deleted, with the full record, so two versions
    can be compared.
  * Trial Balance, Profit & Loss A/c and Balance Sheet in Tally groups with drill-down; Day Book with voucher types.
  * Amount in words, English and Nepali.

Company switch tl_on: updated companies start with it off, new companies with it on. With it off nothing behaves
differently (the Gateway reports can still be opened). Only new tl_* tables and settings are added.
"""
import json
import re
from datetime import date, timedelta

import core
from core import ApiError, q, q1, val, r2, today, now, setting, ins, upd, get
import api_inventory as inv
from api_inventory import api

VERSION = "2.46.0"
FLAG = "_bco246"
POSTED = "v.status IN ('posted','reversed')"
PARTY_ROLES = ("ap_control", "ar_control", "supplier_advance", "subcon_advance", "client_advance",
               "retention_payable", "retention_receivable")
STOCK_ROLES = ("inventory", "inventory_fuel", "inventory_spares", "grni")

SCHEMA = """
CREATE TABLE IF NOT EXISTS tl_groups(id INTEGER PRIMARY KEY, name TEXT UNIQUE, parent_id INTEGER, nature TEXT,
  gp INTEGER DEFAULT 0, system INTEGER DEFAULT 0, pack INTEGER DEFAULT 0, sort INTEGER DEFAULT 0, created_at TEXT,
  skey TEXT);
CREATE TABLE IF NOT EXISTS tl_amap(account_id INTEGER PRIMARY KEY, tl_group_id INTEGER, confirmed INTEGER DEFAULT 0,
  user_id INTEGER, ts TEXT);
CREATE TABLE IF NOT EXISTS tl_ledger(account_id INTEGER PRIMARY KEY, alias TEXT, billwise INTEGER DEFAULT 0,
  credit_days INTEGER, credit_limit REAL, pan TEXT, tds_rate_id INTEGER, cc_on INTEGER DEFAULT 1, note TEXT, ts TEXT);
CREATE TABLE IF NOT EXISTS tl_vtypes(id INTEGER PRIMARY KEY, name TEXT UNIQUE, parent_id INTEGER, base TEXT,
  category TEXT, abbr TEXT, active INTEGER DEFAULT 1, system INTEGER DEFAULT 0, statutory INTEGER DEFAULT 0,
  entry TEXT, method TEXT DEFAULT 'automatic', prevent_dup INTEGER DEFAULT 1, prefix TEXT, suffix TEXT,
  restart TEXT DEFAULT 'yearly', width INTEGER DEFAULT 4, series_by TEXT DEFAULT 'none', start_no INTEGER DEFAULT 1,
  print_title TEXT, line_narration INTEGER DEFAULT 0, default_mode TEXT, sort INTEGER DEFAULT 0, note TEXT,
  created_by INTEGER, ts TEXT);
CREATE TABLE IF NOT EXISTS tl_seq(vtype_id INTEGER, series TEXT, period TEXT, next INTEGER,
  PRIMARY KEY(vtype_id, series, period));
CREATE TABLE IF NOT EXISTS tl_vmeta(voucher_id INTEGER PRIMARY KEY, vtype_id INTEGER, vno TEXT, mode TEXT,
  core_no TEXT, entered_by INTEGER, ts TEXT, altered INTEGER DEFAULT 0, cancelled INTEGER DEFAULT 0, ref_date TEXT,
  root_id INTEGER, superseded_by INTEGER, reversal_id INTEGER);
CREATE INDEX IF NOT EXISTS ix_tl_vmeta_t ON tl_vmeta(vtype_id);
CREATE TABLE IF NOT EXISTS tl_bills(id INTEGER PRIMARY KEY, voucher_id INTEGER, party_id INTEGER, account_id INTEGER,
  ref_type TEXT, bill_name TEXT, bill_date TEXT, due_date TEXT, amount REAL, invoice_id INTEGER,
  status TEXT DEFAULT 'active', ts TEXT);
CREATE INDEX IF NOT EXISTS ix_tl_bills_p ON tl_bills(party_id, bill_name);
CREATE INDEX IF NOT EXISTS ix_tl_bills_v ON tl_bills(voucher_id);
CREATE TABLE IF NOT EXISTS tl_editlog(id INTEGER PRIMARY KEY, entity TEXT, entity_id INTEGER, version INTEGER,
  activity TEXT, snapshot TEXT, user_id INTEGER, ts TEXT, reason TEXT);
CREATE INDEX IF NOT EXISTS ix_tl_editlog_e ON tl_editlog(entity, entity_id);
CREATE TABLE IF NOT EXISTS tl_uicfg(user_id INTEGER, key TEXT, value TEXT, PRIMARY KEY(user_id, key));
"""

# ───────────────────────────── the 28 groups ─────────────────────────────
PRIMARY = [  # name, nature, affects gross profit
    ("Branch / Divisions", "liability", 0), ("Capital Account", "liability", 0), ("Current Assets", "asset", 0),
    ("Current Liabilities", "liability", 0), ("Direct Expenses", "expense", 1), ("Direct Incomes", "income", 1),
    ("Fixed Assets", "asset", 0), ("Indirect Expenses", "expense", 0), ("Indirect Incomes", "income", 0),
    ("Investments", "asset", 0), ("Loans (Liability)", "liability", 0), ("Misc. Expenses (ASSET)", "asset", 0),
    ("Purchase Accounts", "expense", 1), ("Sales Accounts", "income", 1), ("Suspense A/c", "liability", 0),
]
SUBGROUPS = [  # name, parent
    ("Bank Accounts", "Current Assets"), ("Bank OD A/c", "Loans (Liability)"), ("Cash-in-Hand", "Current Assets"),
    ("Deposits (Asset)", "Current Assets"), ("Duties & Taxes", "Current Liabilities"),
    ("Loans & Advances (Asset)", "Current Assets"), ("Provisions", "Current Liabilities"),
    ("Reserves & Surplus", "Capital Account"), ("Secured Loans", "Loans (Liability)"),
    ("Stock-in-Hand", "Current Assets"), ("Sundry Creditors", "Current Liabilities"),
    ("Sundry Debtors", "Current Assets"), ("Unsecured Loans", "Loans (Liability)"),
]
PACK = [
    ("Retention Receivable", "Current Assets"), ("Contract Asset / WIP", "Current Assets"),
    ("Advance to Subcontractors", "Current Assets"), ("Mobilization Advance Received", "Current Liabilities"),
    ("Retention Payable", "Current Liabilities"), ("Contract Liability", "Current Liabilities"),
    ("Site Expenses", "Direct Expenses"), ("Subcontract Costs", "Direct Expenses"),
    ("Equipment Running Costs", "Direct Expenses"), ("VAT", "Duties & Taxes"), ("TDS", "Duties & Taxes"),
]
BS_SIDE_L = ("Capital Account", "Loans (Liability)", "Current Liabilities", "Suspense A/c", "Branch / Divisions")
BS_SIDE_A = ("Fixed Assets", "Investments", "Current Assets", "Misc. Expenses (ASSET)")

# account role -> (group without the contractor pack, group with it)
ROLE_GROUP = {
    "cash": ("Cash-in-Hand", None), "bank": ("Bank Accounts", None),
    "inventory": ("Stock-in-Hand", None), "inventory_fuel": ("Stock-in-Hand", None), "inventory_spares": ("Stock-in-Hand", None),
    "ar_control": ("Sundry Debtors", None), "ap_control": ("Sundry Creditors", None),
    "supplier_advance": ("Loans & Advances (Asset)", None),
    "subcon_advance": ("Loans & Advances (Asset)", "Advance to Subcontractors"),
    "retention_receivable": ("Current Assets", "Retention Receivable"),
    "vat_input": ("Duties & Taxes", "VAT"), "vat_output": ("Duties & Taxes", "VAT"),
    "tds_receivable": ("Loans & Advances (Asset)", None), "tds_payable": ("Duties & Taxes", "TDS"),
    "fixed_asset": ("Fixed Assets", None), "accum_dep": ("Fixed Assets", None),
    "grni": ("Current Liabilities", None), "freight_clearing": ("Current Liabilities", None),
    "payroll_payable": ("Current Liabilities", None),
    "client_advance": ("Current Liabilities", "Mobilization Advance Received"),
    "retention_payable": ("Current Liabilities", "Retention Payable"),
    "capital": ("Capital Account", None), "retained_earnings": ("Reserves & Surplus", None),
    "contract_revenue": ("Sales Accounts", None), "equipment_recovery": ("Direct Incomes", None),
    "stock_gain": ("Indirect Incomes", None),
    "material_cost": ("Direct Expenses", None), "labour_cost": ("Direct Expenses", "Site Expenses"),
    "subcon_cost": ("Direct Expenses", "Subcontract Costs"), "price_variance": ("Direct Expenses", None),
    "hire_cost": ("Direct Expenses", "Equipment Running Costs"), "fuel_cost": ("Direct Expenses", "Equipment Running Costs"),
    "repair_cost": ("Direct Expenses", "Equipment Running Costs"), "equipment_cost": ("Direct Expenses", "Equipment Running Costs"),
    "depreciation": ("Indirect Expenses", None), "overhead": ("Direct Expenses", "Site Expenses"),
    "inventory_loss": ("Indirect Expenses", None),
}

# ───────────────────────────── voucher types ─────────────────────────────
# name, base, category, abbr, statutory, entry (how BuildCore records it)
VTYPES = [
    ("Contra", "contra", "accounting", "Ctra", 0, "voucher"), ("Payment", "payment", "accounting", "Pymt", 0, "voucher"),
    ("Receipt", "receipt", "accounting", "Rcpt", 0, "voucher"), ("Journal", "journal", "accounting", "Jrnl", 0, "voucher"),
    ("Sales", "sales", "accounting", "Sale", 1, "acc/sales"), ("Purchase", "purchase", "accounting", "Purc", 0, "proc/invoices"),
    ("Credit Note", "credit_note", "accounting", "C/Note", 1, "acc/sales"), ("Debit Note", "debit_note", "accounting", "D/Note", 1, "proc/invoices"),
    ("Reversing Journal", "reversing_journal", "accounting", "Rev Jrnl", 0, "later"), ("Memorandum", "memorandum", "accounting", "Memo", 0, "later"),
    ("Purchase Order", "purchase_order", "inventory", "Pur Ord", 0, "proc/po"), ("Sales Order", "sales_order", "inventory", "Sal Ord", 0, "later"),
    ("Receipt Note", "receipt_note", "inventory", "Rcpt Note", 0, "inv/grn"), ("Delivery Note", "delivery_note", "inventory", "Dely Note", 0, "inv/issue"),
    ("Rejection In", "rejection_in", "inventory", "Rej In", 0, "later"), ("Rejection Out", "rejection_out", "inventory", "Rej Out", 0, "inv/return"),
    ("Stock Journal", "stock_journal", "inventory", "Stk Jrnl", 0, "inv/transfer"), ("Physical Stock", "physical_stock", "inventory", "Phys Stk", 0, "inv/count"),
    ("Material In", "material_in", "inventory", "Mat In", 0, "later"), ("Material Out", "material_out", "inventory", "Mat Out", 0, "x/sub"),
    ("Job Work In Order", "job_work_in", "inventory", "JW In", 0, "later"), ("Job Work Out Order", "job_work_out", "inventory", "JW Out", 0, "later"),
    ("Payroll", "payroll", "payroll", "Pyrl", 0, "acc/payments"), ("Attendance", "attendance", "payroll", "Attd", 0, "later"),
]
# BuildCore child types: name, parent, the existing record (vouchers.source) it stands for
CHILD_TYPES = [
    ("IPC Invoice", "Sales", "ipc"), ("Mobilization Advance Receipt", "Receipt", None),
    ("Subcontractor Bill", "Purchase", "sco_bill"), ("Supplier Bill", "Purchase", "invoice"), ("Site Payment", "Payment", None),
    ("Material Receipt (GRN)", "Receipt Note", "grn"), ("Material Transfer", "Stock Journal", "transfer"),
    ("Material Issue to BOQ", "Stock Journal", "issue"), ("Material Return", "Rejection Out", "return"),
    ("Plant Production", "Stock Journal", "plant_run"), ("Free-Issue to Subcontractor", "Material Out", "sc_issue"),
    ("Equipment Internal Billing", "Journal", "internal_billing"), ("Accrual (Auto-Reverse)", "Journal", None),
    ("Auto - DPR", "Journal", "dpr"), ("Auto - Depreciation", "Journal", "depreciation"),
    ("Auto - Loan Instalment", "Payment", "emi"), ("Auto - Reversal", "Journal", "reversal"),
]
ENTRY_BASES = ("contra", "payment", "receipt", "journal")
STATUTORY_BASES = ("sales", "credit_note", "debit_note")
METHODS = ("automatic", "automatic_manual_override", "manual", "none")

FEATURES = [  # key, label, group, default for a new company, live in this version
    ("billWise", "Maintain bill-wise details (New Ref, Agst Ref, Advance, On Account)", "Accounting", 1, 1),
    ("costCentres", "Cost centres in voucher entry (project, BOQ item, machine) with split allocation", "Accounting", 1, 1),
    ("editLog", "Edit Log for vouchers and masters", "Accounting", 1, 1),
    ("lineNarration", "Narration for each ledger line", "Accounting", 0, 1),
    ("costCategories", "Cost categories (parallel allocation)", "Accounting", 0, 0),
    ("budgets", "Budgets and budget variance", "Accounting", 0, 0),
    ("budgetControl", "Funds control on PR / PO / work orders", "Controls", 0, 0),
    ("interest", "Interest calculation", "Accounting", 0, 0),
    ("multiCurrency", "Multiple currencies", "Accounting", 0, 0),
    ("scenarios", "Optional, memorandum and reversing journals (scenarios)", "Accounting", 0, 0),
    ("postDated", "Post-dated vouchers", "Accounting", 0, 0),
    ("godowns", "Godowns (stores and locations)", "Inventory", 1, 1),
    ("batches", "Batches and lots", "Inventory", 0, 0),
    ("multipleUnits", "Alternate units with conversion", "Inventory", 0, 0),
    ("payroll", "Payroll vouchers", "Payroll", 0, 0),
    ("chequePrinting", "Cheque printing", "Banking", 0, 0),
    ("bankReconciliation", "Bank reconciliation", "Banking", 1, 1),
    ("approvals", "Approval rules by amount", "Controls", 0, 0),
    ("jvAccounting", "Joint venture accounting", "Controls", 0, 0),
    ("statutoryNepal", "Nepal VAT and TDS", "Statutory", 1, 1),
    ("irdEBilling", "IRD e-billing readiness (CBMS)", "Statutory", 0, 0),
]
LATER = {"costCategories": "2.47", "budgets": "2.52", "budgetControl": "2.52", "interest": "2.49", "multiCurrency": "2.57",
         "scenarios": "2.49", "postDated": "2.49", "batches": "2.57", "multipleUnits": "2.57", "payroll": "2.49",
         "chequePrinting": "2.54", "approvals": "2.51", "jvAccounting": "2.56", "irdEBilling": "2.47"}
UICFG = {"drcr": "0", "show_balance": "1", "line_narration": "0", "bs_first": "0", "keys": "1", "mode_payment": "single",
         "mode_receipt": "single", "mode_contra": "single", "mode_journal": "double"}


# ───────────────────────────── helpers ─────────────────────────────
def _f(x, d=0.0):
    try:
        return float(x) if x not in (None, "") else d
    except (TypeError, ValueError):
        return d


def _i(x):
    try:
        return int(x) if x not in (None, "", 0, "0") else None
    except (TypeError, ValueError):
        return None


def _set(c, k, v):
    c.execute("INSERT INTO settings(key, value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (k, str(v)))


def _json(c, key, default):
    try:
        v = json.loads(setting(c, key) or "null")
        return v if isinstance(v, type(default)) else default
    except ValueError:
        return default


def on(c):
    return setting(c, "tl_on") == "1"


def need_on(c):
    if not on(c):
        raise ApiError("Tally-style accounting is off for this company. Accounts can turn it on in Accounts › Gateway › "
                       "Features (F11).")


def features(c):
    f = _json(c, "tl_features", {})
    out = {}
    for k, _l, _g, d, live in FEATURES:
        out[k] = bool(f.get(k, d)) and bool(live)
    return out


def feature(c, k):
    return features(c).get(k, False)


def policy(c):
    return "edit_with_log" if setting(c, "tl_policy") == "edit_with_log" else "reverse_only"


def is_admin(u):
    return bool(u) and u.get("role") == "admin"


def _job_days(c, key, u):
    m = _json(c, key, {})
    try:
        return int(_f(m.get((u or {}).get("role") or "", 0)))
    except (TypeError, ValueError):
        return 0


def _log(c, u, entity, eid, activity, snap, reason=None):
    if not on(c) or not feature(c, "editLog") or not eid:
        return
    ver = val(c, "SELECT MAX(version) FROM tl_editlog WHERE entity=? AND entity_id=?", (entity, eid)) or 0
    ins(c, "tl_editlog", {"entity": entity, "entity_id": eid, "version": ver + 1, "activity": activity,
                          "snapshot": json.dumps(snap, default=str), "user_id": (u or {}).get("id"), "ts": now(),
                          "reason": reason})


def _first_log(c, u, entity, eid, snap):
    """Before the first change of a record made before logging began, keep how it was as version 1."""
    if on(c) and feature(c, "editLog") and eid and snap and not val(
            c, "SELECT COUNT(*) FROM tl_editlog WHERE entity=? AND entity_id=?", (entity, eid)):
        _log(c, u, entity, eid, "created", snap, "as it was before the Edit Log began")


def voucher_snap(c, vid):
    v = q1(c, "SELECT * FROM vouchers WHERE id=?", (vid,))
    if not v:
        return None
    v["lines"] = q(c, "SELECT l.account_id, a.name account, l.debit, l.credit, l.narration, l.project_id, l.boq_item_id, "
                      "l.equipment_id, l.party_id FROM voucher_lines l LEFT JOIN accounts a ON a.id=l.account_id "
                      "WHERE l.voucher_id=? ORDER BY l.id", (vid,))
    v["bills"] = q(c, "SELECT party_id, ref_type, bill_name, bill_date, due_date, amount, invoice_id FROM tl_bills "
                      "WHERE voucher_id=? ORDER BY id", (vid,))
    m = q1(c, "SELECT * FROM tl_vmeta WHERE voucher_id=?", (vid,))
    v["shown_no"] = (m or {}).get("vno") or v["no"]
    if m:
        v["voucher_type"] = val(c, "SELECT name FROM tl_vtypes WHERE id=?", (m["vtype_id"],), None)
        v["tl_no"] = m["vno"]
    return v


# ───────────────────────────── amount in words ─────────────────────────────
_EN1 = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten", "Eleven", "Twelve", "Thirteen",
        "Fourteen", "Fifteen", "Sixteen", "Seventeen", "Eighteen", "Nineteen"]
_EN10 = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]
_NE = ("शून्य एक दुई तीन चार पाँच छ सात आठ नौ दश एघार बाह्र तेह्र चौध पन्ध्र सोह्र सत्र अठार उन्नाइस बीस एक्काइस बाइस तेइस "
       "चौबीस पच्चीस छब्बीस सत्ताइस अठ्ठाइस उनन्तीस तीस एकतीस बत्तीस तेत्तीस चौंतीस पैंतीस छत्तीस सैंतीस अठतीस उनन्चालीस "
       "चालीस एकचालीस बयालीस त्रिचालीस चवालीस पैंतालीस छयालीस सतचालीस अठचालीस उनन्चास पचास एकाउन्न बाउन्न त्रिपन्न "
       "चउन्न पचपन्न छपन्न सन्ताउन्न अन्ठाउन्न उनन्साठी साठी एकसट्ठी बयसट्ठी त्रिसट्ठी चौसट्ठी पैंसट्ठी छयसट्ठी सतसट्ठी "
       "अठसट्ठी उनन्सत्तरी सत्तरी एकहत्तर बहत्तर त्रिहत्तर चौहत्तर पचहत्तर छयहत्तर सतहत्तर अठहत्तर उनासी असी एकासी "
       "बयासी त्रियासी चौरासी पचासी छयासी सतासी अठासी उनान्नब्बे नब्बे एकानब्बे बयानब्बे त्रियानब्बे चौरानब्बे "
       "पन्चानब्बे छयानब्बे सन्तानब्बे अन्ठानब्बे उनान्सय").split()


def _en99(n):
    return _EN1[n] if n < 20 else (_EN10[n // 10] + ("-" + _EN1[n % 10] if n % 10 else ""))


def _parts(n):
    """Indian / Nepali grouping: arab, crore, lakh, thousand, hundred, rest"""
    out = []
    for name, size in (("arab", 10 ** 9), ("crore", 10 ** 7), ("lakh", 10 ** 5), ("thousand", 1000), ("hundred", 100)):
        k, n = divmod(n, size)
        if k:
            out.append((name, k))
    if n:
        out.append(("", n))
    return out


def words_en(n):
    if n == 0:
        return "Zero"
    names = {"arab": "Arab", "crore": "Crore", "lakh": "Lakh", "thousand": "Thousand", "hundred": "Hundred"}
    out = []
    for name, k in _parts(n):
        out.append((words_en(k) if k >= 100 else _en99(k)) + (" " + names[name] if name else ""))
    return " ".join(out)


def words_ne(n):
    if n == 0:
        return _NE[0]
    names = {"arab": "अर्ब", "crore": "करोड", "lakh": "लाख", "thousand": "हजार", "hundred": "सय"}
    out = []
    for name, k in _parts(n):
        out.append((words_ne(k) if k >= 100 else _NE[k]) + (" " + names[name] if name else ""))
    return " ".join(out)


def amount_words(amount, lang="en"):
    amt = round(abs(_f(amount)) + 1e-9, 2)
    rs, ps = int(amt), int(round((amt - int(amt)) * 100))
    if lang == "ne":
        s = "रुपैयाँ " + words_ne(rs)
        if ps:
            s += " र " + words_ne(ps) + " पैसा"
        return s + " मात्र"
    s = "Rupees " + words_en(rs)
    if ps:
        s += " and " + words_en(ps) + " Paisa"
    return s + " Only"


@api("tl.words")
def tl_words(c, u, a):
    return {"en": amount_words(a.get("amount"), "en"), "ne": amount_words(a.get("amount"), "ne")}


# ───────────────────────────── seeding ─────────────────────────────
def _gid(c, key):
    """a predefined (or contractor pack) group by its original name, even after the user renamed it"""
    return val(c, "SELECT id FROM tl_groups WHERE skey=?", (key,), None) or \
        val(c, "SELECT id FROM tl_groups WHERE name=? AND skey IS NULL", (key,), None)


def _gkey(c, key):
    return q1(c, "SELECT * FROM tl_groups WHERE id=?", (_gid(c, key),))


def seed_groups(c):
    for i, (name, nature, gp) in enumerate(PRIMARY):
        if not _gid(c, name):
            ins(c, "tl_groups", {"name": name, "parent_id": None, "nature": nature, "gp": gp, "system": 1, "sort": i,
                                 "created_at": now(), "skey": name})
    for i, (name, parent) in enumerate(SUBGROUPS):
        if not _gid(c, name):
            p = _gkey(c, parent)
            ins(c, "tl_groups", {"name": name, "parent_id": p["id"], "nature": p["nature"], "gp": p["gp"], "system": 1,
                                 "sort": 100 + i, "created_at": now(), "skey": name})


def seed_vtypes(c):
    for i, (name, base, cat, abbr, stat, entry) in enumerate(VTYPES):
        if not val(c, "SELECT COUNT(*) FROM tl_vtypes WHERE name=?", (name,)):
            ins(c, "tl_vtypes", {"name": name, "base": base, "category": cat, "abbr": abbr, "system": 1, "statutory": stat,
                                 "entry": entry, "method": "automatic", "prevent_dup": 1, "restart": "yearly", "width": 4,
                                 "series_by": "none", "default_mode": "single" if base in ("payment", "receipt", "contra") else "double",
                                 "sort": i, "ts": now()})
    for i, (name, parent, source) in enumerate(CHILD_TYPES):
        if not val(c, "SELECT COUNT(*) FROM tl_vtypes WHERE note=? AND system=1", (source,)) and \
                not val(c, "SELECT COUNT(*) FROM tl_vtypes WHERE name=?", (name,)):
            p = q1(c, "SELECT * FROM tl_vtypes WHERE name=?", (parent,))
            ins(c, "tl_vtypes", {"name": name, "parent_id": p["id"], "base": p["base"], "category": p["category"],
                                 "abbr": name[:8], "system": 1, "statutory": p["statutory"], "entry": p["entry"],
                                 "method": "automatic", "prevent_dup": 1, "restart": "yearly", "width": 4, "series_by": "none",
                                 "default_mode": p["default_mode"], "sort": 200 + i, "note": source, "ts": now()})


def pack_on(c):
    return bool(val(c, "SELECT COUNT(*) FROM tl_groups WHERE pack=1"))


def propose(c, acc, groups_by_name, pack):
    role = acc.get("role") or ""
    if role in ROLE_GROUP:
        plain, packed = ROLE_GROUP[role]
        name = packed if (pack and packed) else plain
        return groups_by_name.get(name)
    gname = (val(c, "SELECT name FROM account_groups WHERE id=?", (acc.get("group_id"),), "") or "").lower()
    nm = (acc.get("name") or "").lower()
    t = acc.get("type")
    pick = None
    if t == "asset":
        if "fixed" in gname or "fixed" in nm or "machinery" in nm or "vehicle" in nm:
            pick = "Fixed Assets"
        elif "bank" in nm:
            pick = "Bank Accounts"
        elif "cash" in nm or "petty" in nm or "imprest" in nm:
            pick = "Cash-in-Hand"
        elif "deposit" in nm:
            pick = "Deposits (Asset)"
        elif "invest" in nm:
            pick = "Investments"
        elif "advance" in nm or "loan" in nm or "tds" in nm:
            pick = "Loans & Advances (Asset)"
        elif "debtor" in nm or "receivable" in nm:
            pick = "Sundry Debtors"
        elif "inventor" in gname or "stock" in nm:
            pick = "Stock-in-Hand"
        else:
            pick = "Current Assets"
    elif t == "liability":
        if "loan" in gname or "loan" in nm or "borrow" in nm:
            pick = "Bank OD A/c" if "overdraft" in nm or " od" in nm else (
                "Unsecured Loans" if "unsecured" in nm else "Secured Loans")
        elif "vat" in nm or "tds" in nm or "tax" in nm or "duties" in gname:
            pick = "Duties & Taxes"
        elif "provision" in nm:
            pick = "Provisions"
        elif "creditor" in nm or "payable" in gname:
            pick = "Sundry Creditors"
        else:
            pick = "Current Liabilities"
    elif t == "equity":
        pick = "Reserves & Surplus" if ("reserve" in nm or "retained" in nm) else "Capital Account"
    elif t == "income":
        pick = "Sales Accounts" if ("revenue" in nm or "sales" in nm or "contract" in nm) else "Indirect Incomes"
    elif t == "expense":
        if "trading" in gname or "purchase" in nm:
            pick = "Purchase Accounts"
        elif "direct" in gname or "equipment" in gname or "site" in nm or "material" in nm or "labour" in nm:
            pick = "Direct Expenses"
        else:
            pick = "Indirect Expenses"
    return groups_by_name.get(pick or "Suspense A/c")


def refresh_proposals(c, only_unconfirmed=True):
    gb = {g["name"]: g["id"] for g in q(c, "SELECT id, name FROM tl_groups WHERE skey IS NULL")}
    gb.update({g["skey"]: g["id"] for g in q(c, "SELECT id, skey FROM tl_groups WHERE skey IS NOT NULL")})
    pack = pack_on(c)
    n = 0
    for acc in q(c, "SELECT * FROM accounts"):
        cur = q1(c, "SELECT * FROM tl_amap WHERE account_id=?", (acc["id"],))
        if cur and (cur["confirmed"] and only_unconfirmed):
            continue
        g = propose(c, acc, gb, pack)
        if cur:
            if cur["tl_group_id"] != g:
                c.execute("UPDATE tl_amap SET tl_group_id=?, ts=? WHERE account_id=?", (g, now(), acc["id"]))
                n += 1
        else:
            ins(c, "tl_amap", {"account_id": acc["id"], "tl_group_id": g, "confirmed": 0, "ts": now()})
            n += 1
    return n


# ───────────────────────────── settings, features, F12 ─────────────────────────────
@api("tl.meta", "accounts", "view")
def tl_meta(c, u, a):
    refresh_proposals(c)
    fe = _json(c, "tl_features", {})
    feats = [{"key": k, "label": l, "group": g, "on": bool(fe.get(k, d)) and bool(live), "live": bool(live),
              "later": LATER.get(k)} for k, l, g, d, live in FEATURES]
    cfg = dict(UICFG)
    for r in q(c, "SELECT key, value FROM tl_uicfg WHERE user_id=?", (u["id"],)):
        cfg[r["key"]] = r["value"]
    jobs = [r["role"] for r in q(c, "SELECT DISTINCT role FROM users WHERE role<>'admin' ORDER BY role")]
    try:
        jobs = sorted(set(jobs) | {r["key"] for r in q(c, "SELECT key FROM ws_roles") if r["key"] != "admin"})
    except Exception:
        pass
    unconfirmed = val(c, "SELECT COUNT(*) FROM tl_amap m JOIN accounts a ON a.id=m.account_id WHERE m.confirmed=0")
    return {"on": on(c), "version": VERSION, "policy": policy(c), "lock_date": setting(c, "tl_lock_date") or "",
            "backdate": _json(c, "tl_backdate", {}), "alterdays": _json(c, "tl_alterdays", {}), "jobs": jobs,
            "features": feats, "cfg": cfg, "pack": pack_on(c), "unconfirmed": unconfirmed,
            "company": setting(c, "company_name"), "can_change": core.can(u, "accounts", "approve"),
            "can_enter": core.can(u, "accounts", "edit"), "fy": core.fy_of(c, today()), "today": today()}


@api("tl.settings_save", "accounts", "approve")
def tl_settings_save(c, u, a):
    old = {k: setting(c, k) for k in ("tl_on", "tl_policy", "tl_lock_date", "tl_backdate", "tl_alterdays", "tl_features")}
    if "on" in a:
        _set(c, "tl_on", "1" if a.get("on") in (1, "1", True) else "0")
    if "policy" in a:
        if a["policy"] not in ("edit_with_log", "reverse_only"):
            raise ApiError("Alteration policy must be 'edit with log' or 'reverse only'.")
        _set(c, "tl_policy", a["policy"])
    if "lock_date" in a:
        d = (a.get("lock_date") or "").strip()
        if d:
            try:
                date.fromisoformat(d)
            except ValueError:
                raise ApiError("Audit lock date must be a date (YYYY-MM-DD).")
            if d > today():
                raise ApiError("The audit lock date cannot be in the future.")
            prev = setting(c, "tl_lock_date") or ""
            if prev and d < prev and not is_admin(u):
                raise ApiError("Only the administrator can move the audit lock date back.")
        elif setting(c, "tl_lock_date") and not is_admin(u):
            raise ApiError("Only the administrator can remove the audit lock date.")
        _set(c, "tl_lock_date", d)
    for key, arg in (("tl_backdate", "backdate"), ("tl_alterdays", "alterdays")):
        if arg in a:
            m = {}
            for k, v in (a.get(arg) or {}).items():
                n = int(_f(v))
                if n < 0:
                    raise ApiError("Days cannot be negative.")
                if n:
                    m[str(k)] = n
            _set(c, key, json.dumps(m))
    if "features" in a:
        cur = _json(c, "tl_features", {})
        known = {k for k, *_ in FEATURES}
        for k, v in (a.get("features") or {}).items():
            if k in known:
                cur[k] = 1 if v in (1, "1", True) else 0
        _set(c, "tl_features", json.dumps(cur))
    new = {k: setting(c, k) for k in old}
    if new != old:
        _log(c, u, "company_settings", 1, "altered", new)
        core.audit(c, u, "settings", "tl", None, {"old": old, "new": new})
    return tl_meta(c, u, {})


@api("tl.cfg_save", "accounts", "view")
def tl_cfg_save(c, u, a):
    for k, v in (a.get("cfg") or {}).items():
        if k in UICFG:
            c.execute("INSERT OR REPLACE INTO tl_uicfg(user_id, key, value) VALUES(?,?,?)", (u["id"], k, str(v)))
    return True


# ───────────────────────────── groups and mapping ─────────────────────────────
def _groups(c):
    return q(c, "SELECT g.*, p.name parent FROM tl_groups g LEFT JOIN tl_groups p ON p.id=g.parent_id ORDER BY g.sort, g.name")


def _primary_of(gs_by_id, gid):
    g = gs_by_id.get(gid)
    while g and g["parent_id"]:
        g = gs_by_id.get(g["parent_id"])
    return g


@api("tl.groups", "accounts", "view")
def tl_groups(c, u, a):
    refresh_proposals(c)
    gs = _groups(c)
    counts = {r["tl_group_id"]: r["n"] for r in q(c, "SELECT tl_group_id, COUNT(*) n FROM tl_amap GROUP BY tl_group_id")}
    for g in gs:
        g["accounts"] = counts.get(g["id"], 0)
        g["children"] = sum(1 for x in gs if x["parent_id"] == g["id"])
    return {"groups": gs, "pack": pack_on(c)}


@api("tl.group_save", "accounts", "edit")
def tl_group_save(c, u, a):
    name = (a.get("name") or "").strip()
    if not name:
        raise ApiError("Group name is required.")
    dup = q1(c, "SELECT id FROM tl_groups WHERE lower(name)=lower(?) AND id<>?", (name, _i(a.get("id")) or 0))
    if dup:
        raise ApiError("A group called %s already exists." % name)
    if a.get("id"):
        g = get(c, "tl_groups", int(a["id"]), "Group")
        _first_log(c, u, "group", g["id"], g)
        d = {"name": name}
        if not g["system"] and a.get("parent_id"):
            p = get(c, "tl_groups", int(a["parent_id"]), "Parent group")
            x = p
            while x:
                if x["id"] == g["id"]:
                    raise ApiError("A group cannot sit under itself.")
                x = q1(c, "SELECT * FROM tl_groups WHERE id=?", (x["parent_id"],)) if x["parent_id"] else None
            d.update({"parent_id": p["id"], "nature": p["nature"], "gp": p["gp"]})
        upd(c, "tl_groups", g["id"], d)
        _log(c, u, "group", g["id"], "altered", q1(c, "SELECT * FROM tl_groups WHERE id=?", (g["id"],)))
        return q1(c, "SELECT * FROM tl_groups WHERE id=?", (g["id"],))
    p = get(c, "tl_groups", int(a.get("parent_id") or 0), "Parent group (Under)")
    gid = ins(c, "tl_groups", {"name": name, "parent_id": p["id"], "nature": p["nature"], "gp": p["gp"], "system": 0,
                               "sort": 500, "created_at": now()})
    _log(c, u, "group", gid, "created", q1(c, "SELECT * FROM tl_groups WHERE id=?", (gid,)))
    return q1(c, "SELECT * FROM tl_groups WHERE id=?", (gid,))


@api("tl.group_delete", "accounts", "edit")
def tl_group_delete(c, u, a):
    g = get(c, "tl_groups", int(a.get("id") or 0), "Group")
    if g["system"]:
        raise ApiError("%s is a predefined group: it can be renamed but not deleted." % g["name"])
    if val(c, "SELECT COUNT(*) FROM tl_amap WHERE tl_group_id=?", (g["id"],)) or \
            val(c, "SELECT COUNT(*) FROM tl_groups WHERE parent_id=?", (g["id"],)):
        raise ApiError("Move the ledgers and groups under %s first." % g["name"])
    c.execute("DELETE FROM tl_groups WHERE id=?", (g["id"],))
    _log(c, u, "group", g["id"], "deleted", g)
    return True


@api("tl.pack", "accounts", "edit")
def tl_pack(c, u, a):
    made = []
    for name, parent in PACK:
        if not _gid(c, name):
            if q1(c, "SELECT id FROM tl_groups WHERE name=?", (name,)):
                continue  # the user already has a group of that name
            p = _gkey(c, parent)
            gid = ins(c, "tl_groups", {"name": name, "parent_id": p["id"], "nature": p["nature"], "gp": p["gp"],
                                       "system": 0, "pack": 1, "sort": 300, "created_at": now(), "skey": name})
            made.append(name)
            _log(c, u, "group", gid, "created", {"name": name, "under": parent, "pack": 1})
    changed = refresh_proposals(c)
    return {"created": made, "proposals_changed": changed}


def _is_pl_group(gs_by_id, gid):
    p = _primary_of(gs_by_id, gid)
    return bool(p) and p["nature"] in ("income", "expense")


@api("tl.map", "accounts", "view")
def tl_map(c, u, a):
    refresh_proposals(c)
    rows = q(c, "SELECT a.id, a.code, a.name, a.type, a.role, a.active, g.name buildcore_group, m.tl_group_id, m.confirmed, "
                "t.name tl_group FROM accounts a LEFT JOIN account_groups g ON g.id=a.group_id "
                "LEFT JOIN tl_amap m ON m.account_id=a.id LEFT JOIN tl_groups t ON t.id=m.tl_group_id ORDER BY a.code")
    return {"rows": rows, "groups": _groups(c), "unconfirmed": sum(1 for r in rows if not r["confirmed"])}


@api("tl.map_save", "accounts", "edit")
def tl_map_save(c, u, a):
    gs = {g["id"]: g for g in _groups(c)}
    n = 0
    for r in a.get("rows") or []:
        acc = get(c, "accounts", int(r["account_id"]), "Account")
        gid = int(r.get("tl_group_id") or 0)
        if gid not in gs:
            raise ApiError("Choose a group for %s." % acc["name"])
        pl = acc["type"] in ("income", "expense")
        if pl != _is_pl_group(gs, gid):
            raise ApiError("%s is a %s account: it must sit under a %s group, not under %s." % (
                acc["name"], acc["type"], "Profit & Loss" if pl else "Balance Sheet", gs[gid]["name"]))
        cur = q1(c, "SELECT * FROM tl_amap WHERE account_id=?", (acc["id"],))
        if cur and cur["tl_group_id"] == gid and cur["confirmed"]:
            continue
        c.execute("INSERT OR REPLACE INTO tl_amap(account_id, tl_group_id, confirmed, user_id, ts) VALUES(?,?,1,?,?)",
                  (acc["id"], gid, u["id"], now()))
        if not cur or cur["tl_group_id"] != gid:
            if cur:
                _first_log(c, u, "ledger", acc["id"], dict(acc, tl_group=gs.get(cur["tl_group_id"], {}).get("name")))
            _log(c, u, "ledger", acc["id"], "altered", dict(acc, tl_group=gs[gid]["name"]))
        n += 1
    return {"saved": n, "unconfirmed": val(c, "SELECT COUNT(*) FROM tl_amap WHERE confirmed=0")}


# ───────────────────────────── ledger master extras ─────────────────────────────
@api("tl.ledger_get", "accounts", "view")
def tl_ledger_get(c, u, a):
    acc = get(c, "accounts", int(a.get("account_id") or 0), "Ledger")
    refresh_proposals(c)
    ex = q1(c, "SELECT * FROM tl_ledger WHERE account_id=?", (acc["id"],)) or {"account_id": acc["id"], "billwise": 1 if acc["role"] in PARTY_ROLES else 0, "cc_on": 1}
    m = q1(c, "SELECT m.*, t.name tl_group FROM tl_amap m JOIN tl_groups t ON t.id=m.tl_group_id WHERE account_id=?", (acc["id"],))
    return {"account": acc, "extra": ex, "map": m}


@api("tl.ledger_save", "accounts", "edit")
def tl_ledger_save(c, u, a):
    acc = get(c, "accounts", int(a.get("account_id") or 0), "Ledger")
    old = q1(c, "SELECT * FROM tl_ledger WHERE account_id=?", (acc["id"],))
    pan = (a.get("pan") or "").strip()
    if pan and not re.fullmatch(r"\d{9}", pan):
        raise ApiError("PAN must be 9 digits.")
    tds = _i(a.get("tds_rate_id"))
    if tds:
        get(c, "tds_rates", tds, "TDS nature of payment")
    d = {"account_id": acc["id"], "alias": (a.get("alias") or "").strip() or None,
         "billwise": 1 if a.get("billwise") in (1, "1", True) else 0, "credit_days": _i(a.get("credit_days")),
         "credit_limit": _f(a.get("credit_limit"), None) if a.get("credit_limit") not in (None, "") else None,
         "pan": pan or None, "tds_rate_id": tds, "cc_on": 0 if a.get("cc_on") in (0, "0", False) else 1,
         "note": a.get("note"), "ts": now()}
    if old:
        _first_log(c, u, "ledger", acc["id"], dict(acc, extra=old))
    c.execute("INSERT OR REPLACE INTO tl_ledger(%s) VALUES(%s)" % (",".join(d), ",".join("?" * len(d))), list(d.values()))
    if a.get("tl_group_id"):
        tl_map_save(c, u, {"rows": [{"account_id": acc["id"], "tl_group_id": a["tl_group_id"]}]})
    _log(c, u, "ledger", acc["id"], "altered" if old else "created", dict(acc, extra=d))
    return tl_ledger_get(c, u, {"account_id": acc["id"]})


def party_account_role(p):
    return "ar_control" if p["kind"] == "client" else "ap_control"


def _balances(c, to=None, project_id=None):
    """closing balance (Dr +) per account and per (account, party) up to a date"""
    to = to or "9999-12-31"
    pc, pp = (" AND l.project_id=?", [project_id]) if project_id else ("", [])
    acc = {r["account_id"]: r["b"] for r in q(c, "SELECT l.account_id, SUM(l.debit-l.credit) b FROM voucher_lines l JOIN vouchers v "
                                                  "ON v.id=l.voucher_id WHERE " + POSTED + " AND v.date<=?" + pc +
                                                  " GROUP BY l.account_id", [to] + pp)}
    if not project_id:
        for r in q(c, "SELECT id, opening_balance FROM accounts WHERE opening_balance<>0"):
            acc[r["id"]] = (acc.get(r["id"]) or 0) + r["opening_balance"]
    return acc


def party_balances(c, to=None):
    roles = ",".join("'%s'" % r for r in PARTY_ROLES)
    return {r["party_id"]: r["b"] for r in q(
        c, "SELECT l.party_id, SUM(l.debit-l.credit) b FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id JOIN accounts a "
           "ON a.id=l.account_id WHERE l.party_id IS NOT NULL AND a.role IN (%s) AND " % roles + POSTED +
           " AND v.date<=? GROUP BY l.party_id", (to or "9999-12-31",))}


@api("tl.ledgers", "accounts", "view")
def tl_ledgers(c, u, a):
    """Everything a voucher line can be posted to: accounts (ledgers) and parties (party ledgers)."""
    refresh_proposals(c)
    bal = _balances(c)
    pb = party_balances(c)
    gname = {r["account_id"]: r["name"] for r in q(c, "SELECT m.account_id, t.name FROM tl_amap m JOIN tl_groups t ON t.id=m.tl_group_id")}
    ex = {r["account_id"]: r for r in q(c, "SELECT * FROM tl_ledger")}
    out = []
    for acc in q(c, "SELECT * FROM accounts WHERE active=1 ORDER BY name"):
        e = ex.get(acc["id"]) or {}
        stock = acc["role"] in STOCK_ROLES
        out.append({"key": "a:%d" % acc["id"], "account_id": acc["id"], "name": acc["name"], "code": acc["code"],
                    "alias": e.get("alias"), "group": gname.get(acc["id"]), "type": acc["type"], "role": acc["role"],
                    "money": acc["role"] in ("cash", "bank"), "pl": acc["type"] in ("income", "expense"),
                    "balance": r2(bal.get(acc["id"]) or 0), "billwise": bool(e.get("billwise")),
                    "blocked": "updated by store documents (GRN, issue, stock count)" if stock else None,
                    "party_control": acc["role"] in PARTY_ROLES})
    for p in q(c, "SELECT * FROM parties WHERE COALESCE(active,1)=1 ORDER BY name"):
        role = party_account_role(p)
        aid = val(c, "SELECT id FROM accounts WHERE role=? AND active=1 ORDER BY id LIMIT 1", (role,), None)
        if not aid:
            continue
        out.append({"key": "p:%d" % p["id"], "party_id": p["id"], "account_id": aid, "name": p["name"], "code": p["code"],
                    "group": gname.get(aid) or ("Sundry Debtors" if role == "ar_control" else "Sundry Creditors"), "kind": p["kind"],
                    "pan": p.get("pan"), "credit_days": p.get("credit_days"), "balance": r2(pb.get(p["id"]) or 0),
                    "billwise": True, "party": True, "type": "asset" if role == "ar_control" else "liability"})
    return out


# ───────────────────────────── voucher types and numbering ─────────────────────────────
def vt_root(c, vt):
    while vt and vt["parent_id"]:
        vt = q1(c, "SELECT * FROM tl_vtypes WHERE id=?", (vt["parent_id"],))
    return vt


@api("tl.vtypes", "accounts", "view")
def tl_vtypes(c, u, a):
    rows = q(c, "SELECT t.*, p.name parent FROM tl_vtypes t LEFT JOIN tl_vtypes p ON p.id=t.parent_id ORDER BY t.sort, t.name")
    used = {r["vtype_id"]: r["n"] for r in q(c, "SELECT vtype_id, COUNT(*) n FROM tl_vmeta GROUP BY vtype_id")}
    for r in rows:
        r["used"] = used.get(r["id"], 0)
        r["can_enter"] = r["base"] in ENTRY_BASES
    return rows


@api("tl.vtype_save", "accounts", "approve")
def tl_vtype_save(c, u, a):
    name = (a.get("name") or "").strip()
    if not name:
        raise ApiError("Name is required.")
    if q1(c, "SELECT id FROM tl_vtypes WHERE lower(name)=lower(?) AND id<>?", (name, _i(a.get("id")) or 0)):
        raise ApiError("A voucher type called %s already exists." % name)
    method = a.get("method") or "automatic"
    if method not in METHODS:
        raise ApiError("Unknown numbering method.")
    restart = a.get("restart") or "yearly"
    if restart not in ("yearly", "monthly", "never"):
        raise ApiError("Restart numbering must be yearly, monthly or never.")
    series_by = a.get("series_by") or "none"
    if series_by not in ("none", "project"):
        raise ApiError("Numbering series must be one series or one per project.")
    for k in ("prefix", "suffix"):
        bad = set(re.findall(r"\{([A-Z]+)\}", a.get(k) or "")) - {"FY", "MM", "PROJECT", "YYYY"}
        if bad:
            raise ApiError("Unknown token {%s}: use {FY}, {MM}, {YYYY} or {PROJECT}." % ", ".join(bad))
    d = {"name": name, "abbr": (a.get("abbr") or name[:8]).strip(), "active": 0 if a.get("active") in (0, "0", False) else 1,
         "method": method, "prevent_dup": 0 if a.get("prevent_dup") in (0, "0", False) else 1,
         "prefix": a.get("prefix") or None, "suffix": a.get("suffix") or None, "restart": restart,
         "width": max(1, min(8, int(_f(a.get("width"), 4)))), "series_by": series_by,
         "start_no": max(1, int(_f(a.get("start_no"), 1))), "print_title": a.get("print_title") or None,
         "line_narration": 1 if a.get("line_narration") in (1, "1", True) else 0,
         "default_mode": a.get("default_mode") if a.get("default_mode") in ("single", "double") else None, "ts": now()}
    if a.get("id"):
        vt = get(c, "tl_vtypes", int(a["id"]), "Voucher type")
        _first_log(c, u, "voucher_type", vt["id"], vt)
        if vt["system"]:
            d = {k: v for k, v in d.items() if k not in ("name",)} if vt["parent_id"] is None else d
        if vt["statutory"] or vt_root(c, vt)["base"] in STATUTORY_BASES:
            d.update({"method": "automatic", "prevent_dup": 1})
            if (d.get("prefix") != vt["prefix"] or d.get("suffix") != vt["suffix"] or d["restart"] != vt["restart"]) and \
                    val(c, "SELECT COUNT(*) FROM tl_vmeta WHERE vtype_id=?", (vt["id"],)):
                raise ApiError("%s is a statutory voucher type already in use: its numbering cannot change." % vt["name"])
        upd(c, "tl_vtypes", vt["id"], d)
        _log(c, u, "voucher_type", vt["id"], "altered", q1(c, "SELECT * FROM tl_vtypes WHERE id=?", (vt["id"],)))
        return q1(c, "SELECT * FROM tl_vtypes WHERE id=?", (vt["id"],))
    p = get(c, "tl_vtypes", int(a.get("parent_id") or 0), "Type of voucher (parent)")
    root = vt_root(c, p)
    d.update({"parent_id": p["id"], "base": root["base"], "category": root["category"], "system": 0,
              "statutory": 1 if root["base"] in STATUTORY_BASES else 0, "entry": p["entry"], "sort": 600,
              "created_by": u["id"], "default_mode": d["default_mode"] or p["default_mode"]})
    if d["statutory"]:
        d.update({"method": "automatic", "prevent_dup": 1})
    vid = ins(c, "tl_vtypes", d)
    _log(c, u, "voucher_type", vid, "created", q1(c, "SELECT * FROM tl_vtypes WHERE id=?", (vid,)))
    return q1(c, "SELECT * FROM tl_vtypes WHERE id=?", (vid,))


@api("tl.vtype_delete", "accounts", "approve")
def tl_vtype_delete(c, u, a):
    vt = get(c, "tl_vtypes", int(a.get("id") or 0), "Voucher type")
    if vt["system"]:
        raise ApiError("%s is a predefined voucher type: make it inactive instead." % vt["name"])
    if val(c, "SELECT COUNT(*) FROM tl_vmeta WHERE vtype_id=?", (vt["id"],)) or \
            val(c, "SELECT COUNT(*) FROM tl_vtypes WHERE parent_id=?", (vt["id"],)):
        raise ApiError("%s is already used: make it inactive instead." % vt["name"])
    c.execute("DELETE FROM tl_vtypes WHERE id=?", (vt["id"],))
    _log(c, u, "voucher_type", vt["id"], "deleted", vt)
    return True


def _month_code(c, d):
    p = core.period_for(c, d)
    m = re.findall(r"-(\d\d)\b", (p or {}).get("code") or "")
    return m[-1] if m else d[5:7]


def _period_key(c, vt, d):
    fy = core.fy_of(c, d)
    if vt["restart"] == "monthly":
        return fy + "/" + _month_code(c, d)
    if vt["restart"] == "never":
        return "-"
    return fy


def _tokens(c, s, d, project_id):
    if not s:
        return ""
    fy = core.fy_of(c, d).replace("-", "/")
    mm = _month_code(c, d)
    pc = val(c, "SELECT code FROM projects WHERE id=?", (project_id,), "") if project_id else ""
    return s.replace("{FY}", fy).replace("{MM}", mm).replace("{YYYY}", d[:4]).replace("{PROJECT}", pc or "HO")


def custom_numbering(vt):
    """BuildCore's own number (PV/2083-84/0001) is kept unless the type asks for something else."""
    return bool(vt) and (vt["method"] != "automatic" or bool(vt["prefix"]) or bool(vt["suffix"]) or vt["restart"] != "yearly"
                         or vt["series_by"] != "none" or (vt["start_no"] or 1) != 1 or bool(vt["parent_id"]))


def number_for(c, vt, d, project_id, take=True, manual=None):
    if vt["method"] == "none":
        return None
    if vt["method"] == "manual" or (vt["method"] == "automatic_manual_override" and manual):
        no = (manual or "").strip()
        if not no:
            raise ApiError("Enter the voucher number (numbering for %s is manual)." % vt["name"])
        return no
    series = str(project_id or "HO") if vt["series_by"] == "project" else ""
    per = _period_key(c, vt, d)
    r = q1(c, "SELECT next FROM tl_seq WHERE vtype_id=? AND series=? AND period=?", (vt["id"], series, per))
    n = r["next"] if r else (vt["start_no"] or 1)
    if take:
        c.execute("INSERT OR REPLACE INTO tl_seq(vtype_id, series, period, next) VALUES(?,?,?,?)", (vt["id"], series, per, n + 1))
    return _tokens(c, vt["prefix"], d, project_id) + str(n).zfill(int(vt["width"] or 4)) + _tokens(c, vt["suffix"], d, project_id)


@api("tl.next_no", "accounts", "view")
def tl_next_no(c, u, a):
    vt = get(c, "tl_vtypes", int(a.get("vtype_id") or 0), "Voucher type")
    d = a.get("date") or today()
    if not custom_numbering(vt):
        prefix = core.VOUCHER_PREFIX.get(vt_root(c, vt)["base"], "JV")
        fy = core.fy_of(c, d)
        n = val(c, "SELECT next FROM sequences WHERE doc_type=? AND fy=?", (prefix, fy), 1)
        return {"no": "%s/%s/%04d" % (prefix, fy, n), "method": "automatic", "buildcore": True}
    if vt["method"] in ("manual", "none"):
        return {"no": "", "method": vt["method"]}
    return {"no": number_for(c, vt, d, _i(a.get("project_id")), take=False), "method": vt["method"]}


def _unnumber(c, no):
    try:
        doc, fy, n = no.split("/")
        n = int(n)
    except (AttributeError, ValueError):
        return
    c.execute("UPDATE sequences SET next=? WHERE doc_type=? AND fy=? AND next=?", (n, doc, fy, n + 1))


def apply_number(c, vid, vt, project_id, manual=None):
    """The voucher type's own number (posted vouchers are permanent, so BuildCore's number stays on the voucher and the
    type's number is kept beside it and shown on every Tally screen)."""
    v = q1(c, "SELECT * FROM vouchers WHERE id=?", (vid,))
    if not v or not custom_numbering(vt) or v["status"] not in ("posted",):
        return v and v["no"]
    no = number_for(c, vt, v["date"], project_id, manual=manual)
    if no is None:
        return v["no"]
    if vt["prevent_dup"] and val(c, "SELECT COUNT(*) FROM tl_vmeta WHERE vtype_id=? AND vno=? AND voucher_id<>? AND "
                                    "COALESCE(root_id, voucher_id)<>?", (vt["id"], no, vid, root_of(c, vid))):
        raise ApiError("Voucher number %s is already used. Choose another number." % no)
    c.execute("UPDATE tl_vmeta SET vno=?, core_no=? WHERE voucher_id=?", (no, v["no"], vid))
    return no


def root_of(c, vid):
    return val(c, "SELECT root_id FROM tl_vmeta WHERE voucher_id=?", (vid,), None) or vid


def disp_no(c, v):
    return val(c, "SELECT vno FROM tl_vmeta WHERE voucher_id=?", (v["id"],), None) or v["no"]


def vtype_of(c, v, cache=None):
    m = q1(c, "SELECT t.name FROM tl_vmeta x JOIN tl_vtypes t ON t.id=x.vtype_id WHERE x.voucher_id=?", (v["id"],))
    if m:
        return m["name"]
    if cache is None:
        cache = {}
    if "src" not in cache:
        cache["src"] = {r["note"]: r["name"] for r in q(c, "SELECT note, name FROM tl_vtypes WHERE note IS NOT NULL")}
        cache["base"] = {r["base"]: r["name"] for r in q(c, "SELECT base, name FROM tl_vtypes WHERE parent_id IS NULL")}
    src = v.get("source") or ""
    if src == "invoice":
        return "IPC Invoice" if v.get("type") == "sales" else "Supplier Bill"
    if src in cache["src"]:
        return cache["src"][src]
    if src == "payment":
        return cache["base"].get(v.get("type"), "Payment")
    return cache["base"].get(v.get("type") or "journal", "Journal")


# ───────────────────────────── locks, back-date, alteration ─────────────────────────────
def check_backdate(c, u, d, action="create"):
    if not on(c) or is_admin(u) or not d:
        return
    n = _job_days(c, "tl_backdate", u)
    if n and d < (date.today() - timedelta(days=n)).isoformat():
        raise ApiError("BACKDATE_NOT_ALLOWED: your job (%s) may enter vouchers dated up to %d days before today; %s is "
                       "older. Ask accounts to enter it." % ((u or {}).get("role"), n, d))


def check_lock_date(c, d):
    lk = setting(c, "tl_lock_date") if on(c) else ""
    if lk and d and d <= lk:
        raise ApiError("PERIOD_CLOSED: the books are locked up to %s (audit lock date). Entries dated %s are not allowed." % (lk, d))


def lock_reason(c, u, v):
    """Why a posted voucher cannot be altered (None = it can)."""
    if policy(c) != "edit_with_log":
        return "The company's alteration policy is 'reverse only': cancel (reverse) the voucher and enter it again."
    nxt = val(c, "SELECT superseded_by FROM tl_vmeta WHERE voucher_id=?", (v["id"],), None)
    if nxt:
        return "This voucher was altered: open the latest version (voucher #%s)." % nxt
    if v["source"] != "manual":
        return "This voucher was posted from %s: alter the source document instead." % (v["source"] or "another screen")
    if v["status"] != "posted":
        return "This voucher is %s." % v["status"]
    if v.get("reversal_of"):
        return "This is a reversal voucher."
    p = core.period_for(c, v["date"])
    if p and p["status"] != "open":
        return "Period %s is %s." % (p["code"], p["status"].replace("_", "-"))
    lk = setting(c, "tl_lock_date")
    if lk and v["date"] <= lk:
        return "The books are locked up to %s (audit lock date)." % lk
    if not is_admin(u):
        n = _job_days(c, "tl_alterdays", u)
        if n and v["date"] < (date.today() - timedelta(days=n)).isoformat():
            return "Your job may alter vouchers up to %d days old." % n
    if val(c, "SELECT COUNT(*) FROM voucher_lines WHERE voucher_id=? AND cleared_date IS NOT NULL", (v["id"],)):
        return "A line of this voucher is reconciled with the bank statement."
    for t in ("mn_stmt", "mn_capital", "mn_asset_link"):
        try:
            if val(c, "SELECT COUNT(*) FROM %s WHERE line_id IN (SELECT id FROM voucher_lines WHERE voucher_id=?)" % t, (v["id"],)):
                return "A line of this voucher is linked in %s." % t.replace("mn_", "the ").replace("_", " ")
        except Exception:
            pass
    return None


def _settled(c, vid):
    """bills made by this voucher that other vouchers have settled: (party, name) -> amount settled"""
    out = {}
    for b in q(c, "SELECT * FROM tl_bills WHERE voucher_id=? AND ref_type='new' AND status='active'", (vid,)):
        s = val(c, "SELECT SUM(amount) FROM tl_bills WHERE party_id=? AND bill_name=? AND ref_type='agst' AND status='active' "
                   "AND voucher_id<>?", (b["party_id"], b["bill_name"], vid)) or 0
        if abs(s) > 0.004:
            out[(b["party_id"], b["bill_name"])] = abs(s)
    return out


# ───────────────────────────── pending bills ─────────────────────────────
def tl_pending(c, party_id, skip_voucher=None):
    rows = q(c, "SELECT bill_name, MIN(bill_date) bill_date, MAX(due_date) due_date, SUM(amount) amt, "
                "SUM(CASE WHEN ref_type='new' THEN amount ELSE 0 END) orig FROM tl_bills WHERE party_id=? AND status='active' "
                "AND ref_type IN ('new','agst') AND voucher_id<>? GROUP BY bill_name", (party_id, skip_voucher or 0))
    return [dict(r, balance=r2(r["amt"])) for r in rows if abs(r["amt"] or 0) > 0.004]


@api("tl.pending_bills", "accounts", "view")
def tl_pending_bills(c, u, a):
    pid = int(a.get("party_id") or 0)
    p = get(c, "parties", pid, "Party")
    kind = "sales" if p["kind"] == "client" else "purchase"
    out = []
    for r in inv.FUNCS["invoice.open"][0](c, u, {"party_id": pid, "kind": kind}):
        bal = r2(r["balance"])
        out.append({"source": "invoice", "invoice_id": r["id"], "name": r.get("party_inv_no") or r["no"], "no": r["no"],
                    "bill_date": r["date"], "due_date": r.get("due_date"), "balance": -bal if kind == "purchase" else bal,
                    "project_id": r.get("project_id")})
    for r in tl_pending(c, pid, _i(a.get("skip_voucher"))):
        out.append({"source": "tl", "name": r["bill_name"], "bill_date": r["bill_date"], "due_date": r["due_date"],
                    "balance": r["balance"]})
    adv = inv.FUNCS["invoice.advance_balance"][0](c, u, {"party_id": pid, "kind": kind}) if "invoice.advance_balance" in inv.FUNCS else None
    return {"party": p, "bills": out, "advance": adv, "note": "Balance: positive = Dr (party owes us), negative = Cr (we owe the party)."}


# ───────────────────────────── voucher entry ─────────────────────────────
def _resolve(c, key):
    m = re.fullmatch(r"([ap]):(\d+)", str(key or ""))
    if not m:
        raise ApiError("Choose a ledger for every line.")
    if m.group(1) == "a":
        acc = get(c, "accounts", int(m.group(2)), "Ledger")
        return acc, None
    p = get(c, "parties", int(m.group(2)), "Party")
    aid = val(c, "SELECT id FROM accounts WHERE role=? AND active=1 ORDER BY id LIMIT 1", (party_account_role(p),), None)
    if not aid:
        raise ApiError("No Sundry Debtors / Creditors control account is set.")
    return get(c, "accounts", aid), p


def _clean_lines(c, a, header_project):
    lines, bills = [], []
    for i, l in enumerate(a.get("lines") or []):
        if not l.get("ledger"):
            continue
        acc, party = _resolve(c, l["ledger"])
        dr, cr = r2(_f(l.get("dr"))), r2(_f(l.get("cr")))
        if dr < 0 or cr < 0 or (dr > 0 and cr > 0) or (dr == 0 and cr == 0):
            raise ApiError("Line %d (%s): enter either a debit or a credit amount." % (i + 1, acc["name"] if not party else party["name"]))
        if not acc["active"]:
            raise ApiError("%s is inactive." % acc["name"])
        if acc["role"] in STOCK_ROLES:
            raise ApiError("%s is updated by store documents (GRN, issue, stock count), not by vouchers." % acc["name"])
        amt = dr or cr
        base = {"account_id": acc["id"], "narration": l.get("narration") or None, "party_id": party["id"] if party else
                (_i(l.get("party_id")) if acc["role"] in PARTY_ROLES else None)}
        if acc["role"] in PARTY_ROLES and not base["party_id"]:
            raise ApiError("%s needs a party: choose the party's own ledger instead." % acc["name"])
        cc = [x for x in (l.get("cc") or []) if _f(x.get("amount")) > 0]
        if cc:
            if abs(r2(sum(_f(x["amount"]) for x in cc)) - amt) > 0.004:
                raise ApiError("Line %d: the cost centre allocation (%s) must add up to the line amount (%s)." % (
                    i + 1, r2(sum(_f(x["amount"]) for x in cc)), amt))
            for x in cc:
                pj = _i(x.get("project_id")) or header_project
                if pj:
                    get(c, "projects", pj, "Project")
                boq = _i(x.get("boq_item_id"))
                if boq and pj and val(c, "SELECT project_id FROM boq_items WHERE id=?", (boq,)) != pj:
                    raise ApiError("Line %d: the BOQ item belongs to another project." % (i + 1))
                xa = r2(_f(x["amount"]))
                lines.append(dict(base, debit=xa if dr else 0, credit=xa if cr else 0, project_id=pj, boq_item_id=boq,
                                  equipment_id=_i(x.get("equipment_id"))))
        else:
            lines.append(dict(base, debit=dr, credit=cr, project_id=_i(l.get("project_id")) or header_project,
                              boq_item_id=_i(l.get("boq_item_id")), equipment_id=_i(l.get("equipment_id"))))
        sign = 1 if dr else -1
        refs = [x for x in (l.get("bills") or []) if _f(x.get("amount")) > 0]
        if refs:
            if not party:
                raise ApiError("Line %d: bill-wise details are for party ledgers." % (i + 1))
            if abs(r2(sum(_f(x["amount"]) for x in refs)) - amt) > 0.004:
                raise ApiError("BILLWISE_MISMATCH: line %d (%s): bill-wise details add up to %s, the line is %s." % (
                    i + 1, party["name"], r2(sum(_f(x["amount"]) for x in refs)), amt))
            for x in refs:
                t = x.get("ref_type")
                if t not in ("new", "agst", "advance", "onaccount"):
                    raise ApiError("Type of reference must be New Ref, Agst Ref, Advance or On Account.")
                if t in ("new", "agst") and not (x.get("name") or x.get("invoice_id")):
                    raise ApiError("Line %d: give the bill name." % (i + 1))
                bills.append({"line": i, "party_id": party["id"], "account_id": acc["id"], "ref_type": t,
                              "bill_name": (x.get("name") or "").strip() or None, "invoice_id": _i(x.get("invoice_id")),
                              "bill_date": x.get("bill_date") or None, "due_date": x.get("due_date") or None,
                              "amount": r2(sign * _f(x["amount"])), "tds_rate_id": _i(x.get("tds_rate_id"))})
        elif party and feature(c, "billWise"):
            bills.append({"line": i, "party_id": party["id"], "account_id": acc["id"], "ref_type": "onaccount",
                          "bill_name": None, "invoice_id": None, "amount": r2(sign * amt)})
    if len(lines) < 2:
        raise ApiError("A voucher needs at least two lines.")
    td, tc = r2(sum(x["debit"] for x in lines)), r2(sum(x["credit"] for x in lines))
    if abs(td - tc) > 0.004:
        raise ApiError("Debit (%s) and credit (%s) totals must be equal." % (td, tc))
    return lines, bills, td


def _check_agst(c, bills, skip_voucher=None):
    for b in bills:
        if b["ref_type"] != "agst" or b["invoice_id"]:
            continue
        open_ = {r["bill_name"]: r["balance"] for r in tl_pending(c, b["party_id"], skip_voucher)}
        if b["bill_name"] not in open_:
            raise ApiError("BILLWISE_MISMATCH: bill %s is not pending for this party. Choose it from the pending list or "
                           "use New Ref." % b["bill_name"])
        if abs(b["amount"]) > abs(open_[b["bill_name"]]) + 0.004 or (b["amount"] > 0) == (open_[b["bill_name"]] > 0):
            raise ApiError("BILLWISE_MISMATCH: %s against bill %s exceeds its balance %s (or is on the same side)." % (
                abs(b["amount"]), b["bill_name"], abs(open_[b["bill_name"]])))


def _payment_route(c, base, lines, bills):
    """A payment / receipt to ONE party with bills of BuildCore (or an advance / on account) is a normal BuildCore payment."""
    if base not in ("payment", "receipt"):
        return None
    parties = {x["party_id"] for x in lines if x.get("party_id")}
    money = [x for x in lines if val(c, "SELECT role FROM accounts WHERE id=?", (x["account_id"],), "") in ("cash", "bank")]
    other = [x for x in lines if x not in money and not x.get("party_id")]
    if len(parties) != 1 or len(money) != 1 or any(b["ref_type"] in ("new",) or (b["ref_type"] == "agst" and not b["invoice_id"]) for b in bills):
        return None
    tds_lines = [x for x in other if val(c, "SELECT role FROM accounts WHERE id=?", (x["account_id"],), "") == "tds_payable"]
    if len(other) != len(tds_lines):
        return None
    pay = base == "payment"
    party_lines = [x for x in lines if x.get("party_id")]
    if pay and any(x["credit"] for x in party_lines) or (not pay and any(x["debit"] for x in party_lines)):
        return None
    if (pay and money[0]["debit"]) or (not pay and money[0]["credit"]):
        return None
    if any(x["boq_item_id"] or x["equipment_id"] for x in party_lines):
        return None
    if tds_lines and not pay:
        return None
    return {"party_id": parties.pop(), "bank": money[0]["account_id"], "money": money[0]["debit"] or money[0]["credit"],
            "tds": r2(sum(x["credit"] for x in tds_lines)), "project_id": money[0]["project_id"] or party_lines[0]["project_id"]}


def _write_bills(c, vid, bills, status="active"):
    c.execute("DELETE FROM tl_bills WHERE voucher_id=?", (vid,))
    for b in bills:
        ins(c, "tl_bills", {"voucher_id": vid, "party_id": b["party_id"], "account_id": b["account_id"], "ref_type": b["ref_type"],
                            "bill_name": b["bill_name"], "bill_date": b.get("bill_date"), "due_date": b.get("due_date"),
                            "amount": b["amount"], "invoice_id": b.get("invoice_id"), "status": status, "ts": now()})


@api("tl.save", "accounts", "edit")
def tl_save(c, u, a):
    """Save a voucher from the keyboard voucher screen. New: through voucher.save (+ voucher.post) or payment.create.
    With "id": alter a posted manual voucher in place (policy edit with log), keeping its number."""
    need_on(c)
    vt = get(c, "tl_vtypes", int(a.get("vtype_id") or 0), "Voucher type")
    root = vt_root(c, vt)
    if root["base"] not in ENTRY_BASES:
        raise ApiError("%s vouchers are entered on their own BuildCore screen." % vt["name"])
    if not vt["active"]:
        raise ApiError("%s is inactive." % vt["name"])
    d = a.get("date") or ""
    try:
        date.fromisoformat(d)
    except ValueError:
        raise ApiError("Date is required (YYYY-MM-DD).")
    narration = (a.get("narration") or "").strip() or vt["name"]
    hp = _i(a.get("project_id"))
    if hp:
        get(c, "projects", hp, "Project")
    lines, bills, total = _clean_lines(c, a, hp)
    if root["base"] == "contra":
        for x in lines:
            if val(c, "SELECT role FROM accounts WHERE id=?", (x["account_id"],), "") not in ("cash", "bank"):
                raise ApiError("A contra voucher moves money between cash and bank ledgers only.")
    if root["base"] in ("payment", "receipt") and not any(
            val(c, "SELECT role FROM accounts WHERE id=?", (x["account_id"],), "") in ("cash", "bank") for x in lines):
        raise ApiError("A %s needs a cash or bank ledger." % root["base"])
    check_lock_date(c, d)
    if a.get("id"):
        return _alter(c, u, int(a["id"]), vt, d, narration, hp, lines, bills, total, a)
    check_backdate(c, u, d)
    if a.get("vno") and vt["method"] == "manual" and vt["prevent_dup"] and val(c, "SELECT COUNT(*) FROM vouchers WHERE no=?", (a["vno"],)):
        raise ApiError("Voucher number %s is already used." % a["vno"])
    _check_agst(c, bills)
    route = _payment_route(c, root["base"], lines, bills)
    if route:
        allocs, adv, tds_rate = [], 0.0, None
        for b in bills:
            if b["ref_type"] == "agst":
                allocs.append({"invoice_id": b["invoice_id"], "amount": abs(b["amount"])})
            else:
                adv += abs(b["amount"])
            tds_rate = tds_rate or b.get("tds_rate_id")
        if route["tds"] and not tds_rate:
            raise ApiError("Choose the TDS nature of payment (section) in the bill-wise details of the party line.")
        res = inv.FUNCS["payment.create"][0](c, u, {"kind": "pay" if root["base"] == "payment" else "receive",
                                                    "party_id": route["party_id"], "date": d, "bank_account_id": route["bank"],
                                                    "allocations": allocs, "advance": r2(adv), "tds_rate_id": tds_rate,
                                                    "project_id": route["project_id"], "mode": a.get("instrument") or None,
                                                    "cheque_no": a.get("ref_no") or None, "remarks": narration})
        if route["tds"] and abs(r2(res["tds"]) - route["tds"]) > 0.01:
            raise ApiError("TDS by the chosen section is %s, the voucher shows %s. Correct the TDS line." % (res["tds"], route["tds"]))
        if abs(r2(res["net"]) - r2(route["money"])) > 0.01:
            raise ApiError("The cash / bank amount (%s) must equal the net paid (%s)." % (route["money"], res["net"]))
        p = q1(c, "SELECT * FROM payments WHERE id=?", (res["id"],))
        vid = p["voucher_id"]
        ins(c, "tl_vmeta", {"voucher_id": vid, "vtype_id": vt["id"], "vno": None, "mode": a.get("mode") or "single",
                            "entered_by": u["id"], "ts": now(), "ref_date": a.get("ref_date")})
        no = apply_number(c, vid, vt, hp or route["project_id"], a.get("vno"))
        c.execute("UPDATE tl_vmeta SET vno=COALESCE(vno, ?) WHERE voucher_id=?", (no, vid))
        _log(c, u, "voucher", vid, "created", voucher_snap(c, vid))
        return {"id": vid, "no": no, "status": "posted", "payment_id": res["id"], "route": "payment"}
    if any(b["invoice_id"] for b in bills):
        raise ApiError("Agst Ref to a BuildCore bill works in a Payment or Receipt to one party with one cash/bank ledger. "
                       "Put the other lines in a separate voucher.")
    res = inv.FUNCS["voucher.save"][0](c, u, {"header": {"date": d, "type": root["base"], "narration": narration,
                                                         "project_id": hp, "ref_no": a.get("ref_no") or None},
                                              "lines": [dict(x) for x in lines]})
    vid = res["id"]
    ins(c, "tl_vmeta", {"voucher_id": vid, "vtype_id": vt["id"], "vno": a.get("vno") or None, "mode": a.get("mode") or "double",
                        "entered_by": u["id"], "ts": now(), "ref_date": a.get("ref_date")})
    _write_bills(c, vid, bills, "draft")
    if setting(c, "voucher_approval") != "1" or core.can(u, "accounts", "approve"):
        try:
            vid = inv.FUNCS["voucher.post"][0](c, u, {"id": vid})["id"]
        except ApiError as e:
            if "Another person must approve" not in str(e):
                raise
    v = q1(c, "SELECT * FROM vouchers WHERE id=?", (vid,))
    return {"id": vid, "no": disp_no(c, v), "core_no": v["no"],
            "status": "posted" if v["status"] == "posted" else "pending approval", "route": "voucher"}


def _alter(c, u, vid, vt, d, narration, hp, lines, bills, total, a):
    v = get(c, "vouchers", vid, "Voucher")
    why = lock_reason(c, u, v)
    if why:
        raise ApiError("VOUCHER_LOCKED: " + why)
    if core.fy_of(c, d) != core.fy_of(c, v["date"]):
        raise ApiError("An altered voucher must stay in its fiscal year (%s). Cancel it and enter a new one." % core.fy_of(c, v["date"]))
    core.assert_open(c, u, d)
    if d != v["date"]:
        check_backdate(c, u, d)
    _first_log(c, u, "voucher", root_of(c, vid), voucher_snap(c, vid))
    _check_agst(c, bills, skip_voucher=vid)
    for (pid, name), amt in _settled(c, vid).items():
        keep = sum(abs(b["amount"]) for b in bills if b["ref_type"] == "new" and b["party_id"] == pid and b["bill_name"] == name)
        if keep + 0.004 < amt:
            raise ApiError("VOUCHER_LOCKED: bill %s is already settled for %s by other vouchers; keep it as a New Ref of at "
                           "least that amount." % (name, r2(amt)))
    if any(b["invoice_id"] for b in bills):
        raise ApiError("Agst Ref to a BuildCore bill cannot be added by alteration: cancel and enter a payment.")
    reason = (a.get("reason") or "").strip() or None
    root = root_of(c, vid)
    m = q1(c, "SELECT * FROM tl_vmeta WHERE voucher_id=?", (vid,)) or {}
    shown = m.get("vno") or v["no"]
    # posted vouchers are permanent (NFRS): the old version is reversed on its own date and the new version posted,
    # both under the same voucher number on the Tally screens; the Day Book shows only the latest version
    rid = core.reverse_voucher(c, u, vid, v["date"], "Altered%s" % (": " + reason if reason else ""))
    nid = core.post_voucher(c, u, v["type"], d, narration, [dict(x) for x in lines], project_id=hp, source="manual",
                            party_id=v["party_id"], ref_no=a.get("ref_no") or None)
    if not nid:
        raise ApiError("The altered voucher has no amounts.")
    upd(c, "vouchers", nid, {"created_by": v["created_by"]})
    c.execute("UPDATE tl_bills SET status='superseded' WHERE voucher_id=?", (vid,))
    _write_bills(c, nid, bills, "active")
    if m:
        c.execute("UPDATE tl_vmeta SET superseded_by=?, reversal_id=? WHERE voucher_id=?", (nid, rid, vid))
    else:
        ins(c, "tl_vmeta", {"voucher_id": vid, "vtype_id": vt["id"], "vno": shown, "mode": a.get("mode"), "entered_by": v["created_by"],
                            "ts": now(), "root_id": root, "superseded_by": nid, "reversal_id": rid})
    ins(c, "tl_vmeta", {"voucher_id": nid, "vtype_id": m.get("vtype_id") or vt["id"], "vno": shown, "mode": a.get("mode") or m.get("mode"),
                        "core_no": val(c, "SELECT no FROM vouchers WHERE id=?", (nid,), None), "entered_by": m.get("entered_by") or v["created_by"],
                        "ts": now(), "altered": (m.get("altered") or 0) + 1, "root_id": root, "ref_date": a.get("ref_date")})
    if rid:
        ins(c, "tl_vmeta", {"voucher_id": rid, "vtype_id": m.get("vtype_id") or vt["id"], "vno": shown, "mode": "reversal",
                            "ts": now(), "root_id": root, "superseded_by": nid})
    _log(c, u, "voucher", root, "altered", voucher_snap(c, nid), reason)
    core.audit(c, u, "alter", "vouchers", vid, {"no": shown, "new_id": nid, "reversal_id": rid, "reason": reason})
    return {"id": nid, "no": shown, "status": "posted", "altered": True, "previous_id": vid}


@api("tl.get", "accounts", "view")
def tl_get(c, u, a):
    v = get(c, "vouchers", int(a.get("id") or 0), "Voucher")
    snap = voucher_snap(c, v["id"])
    m = q1(c, "SELECT * FROM tl_vmeta WHERE voucher_id=?", (v["id"],))
    snap["vtype_id"] = m["vtype_id"] if m else val(c, "SELECT id FROM tl_vtypes WHERE name=?", (vtype_of(c, v),), None)
    snap["voucher_type"] = vtype_of(c, v)
    snap["mode"] = (m or {}).get("mode")
    if v["status"] == "posted":
        snap["lock"] = lock_reason(c, u, v)
    elif (m or {}).get("superseded_by"):
        snap["lock"] = "This voucher was altered: open the latest version (voucher #%s)." % m["superseded_by"]
    elif (m or {}).get("cancelled"):
        snap["lock"] = "This voucher was cancelled."
    else:
        snap["lock"] = "This voucher is %s." % ("pending approval" if v["status"] == "draft" else v["status"])
    snap["policy"] = policy(c)
    snap["words"] = amount_words(v["total"])
    snap["words_ne"] = amount_words(v["total"], "ne")
    snap["root_id"] = root_of(c, v["id"])
    snap["shown_no"] = disp_no(c, v)
    snap["edits"] = val(c, "SELECT COUNT(*) FROM tl_editlog WHERE entity='voucher' AND entity_id=?", (snap["root_id"],))
    names = {r["id"]: r["name"] for r in q(c, "SELECT id, name FROM parties")}
    for ln in snap["lines"]:
        ln["party"] = names.get(ln["party_id"])
    return snap


@api("tl.nav", "accounts", "view")
def tl_nav(c, u, a):
    """Previous / next voucher (Page Up / Page Down) of the same voucher type, by date and number."""
    v = get(c, "vouchers", int(a.get("id") or 0), "Voucher") if a.get("id") else None
    vt = _i(a.get("vtype_id"))
    cond = ["v.status IN ('posted','reversed','draft')"]
    p = []
    if vt:
        cond.append("v.id IN (SELECT voucher_id FROM tl_vmeta WHERE vtype_id=?)")
        p.append(vt)
    if v:
        if a.get("dir") == "prev":
            cond.append("(v.date<? OR (v.date=? AND v.id<?))")
            order = "v.date DESC, v.id DESC"
        else:
            cond.append("(v.date>? OR (v.date=? AND v.id>?))")
            order = "v.date, v.id"
        p += [v["date"], v["date"], v["id"]]
    else:
        order = "v.date DESC, v.id DESC"
    r = q1(c, "SELECT v.id FROM vouchers v WHERE " + " AND ".join(cond) + " ORDER BY " + order + " LIMIT 1", p)
    return {"id": r["id"] if r else None}


@api("tl.cancel", "accounts", "approve")
def tl_cancel(c, u, a):
    """Cancel (Alt+X): the voucher keeps its number and is reversed on the same date; nothing is deleted."""
    v = get(c, "vouchers", int(a.get("id") or 0), "Voucher")
    reason = (a.get("reason") or "").strip()
    if not reason:
        raise ApiError("Give the reason for cancelling.")
    if v["status"] != "posted":
        raise ApiError("Only posted vouchers can be cancelled.")
    check_lock_date(c, v["date"])
    root = root_of(c, v["id"])
    _first_log(c, u, "voucher", root, voucher_snap(c, v["id"]))
    if v["source"] == "payment":
        inv.FUNCS["payment.cancel"][0](c, u, {"id": v["source_id"], "reason": reason})
    elif v["source"] == "manual":
        rid = core.reverse_voucher(c, u, v["id"], v["date"] if (core.period_for(c, v["date"]) or {}).get("status", "open") == "open" else today(), reason)
        if rid:
            c.execute("UPDATE tl_bills SET status='cancelled' WHERE voucher_id=?", (v["id"],))
    else:
        raise ApiError("This voucher came from %s. Cancel the source document instead." % v["source"])
    c.execute("UPDATE tl_bills SET status='cancelled' WHERE voucher_id=?", (v["id"],))
    c.execute("UPDATE tl_vmeta SET cancelled=1 WHERE voucher_id=?", (v["id"],))
    _log(c, u, "voucher", root, "cancelled", voucher_snap(c, v["id"]), reason)
    core.audit(c, u, "cancel", "vouchers", v["id"], reason)
    return {"id": v["id"], "status": "reversed"}


# ───────────────────────────── Edit Log ─────────────────────────────
@api("tl.editlog", "accounts", "view")
def tl_editlog(c, u, a):
    ent, eid = a.get("entity") or "voucher", int(a.get("entity_id") or 0)
    if ent == "voucher":
        eid = root_of(c, eid)
    rows = q(c, "SELECT e.*, us.name user FROM tl_editlog e LEFT JOIN users us ON us.id=e.user_id WHERE entity=? AND entity_id=? "
                "ORDER BY version", (ent, eid))
    for r in rows:
        r["snapshot"] = json.loads(r["snapshot"] or "null")
    if not rows and ent == "voucher":
        s = voucher_snap(c, eid)
        if s:
            rows = [{"version": 1, "activity": "created", "snapshot": s, "user": val(c, "SELECT name FROM users WHERE id=?", (s.get("created_by"),), None),
                     "ts": s.get("ts"), "reason": "as recorded (no alteration since)"}]
    return {"entity": ent, "entity_id": eid, "versions": rows}


@api("tl.editlog_company", "accounts", "view")
def tl_editlog_company(c, u, a):
    frm, to = a.get("from") or "0000-01-01", (a.get("to") or today()) + "T99"
    cond, p = ["e.ts BETWEEN ? AND ?"], [frm, to]
    for k in ("entity", "activity"):
        if a.get(k):
            cond.append("e.%s=?" % k)
            p.append(a[k])
    rows = q(c, "SELECT e.id, e.entity, e.entity_id, e.version, e.activity, e.ts, e.reason, us.name user, e.snapshot FROM tl_editlog e "
                "LEFT JOIN users us ON us.id=e.user_id WHERE " + " AND ".join(cond) + " ORDER BY e.id DESC LIMIT 2000", p)
    for r in rows:
        s = json.loads(r.pop("snapshot") or "null") or {}
        r["label"] = s.get("no") or s.get("name") or s.get("account") or ("#%s" % r["entity_id"])
    return rows


def _diff(a, b, path=""):
    out = []
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            if k in ("ts", "id", "no", "approved_by", "created_by", "core_no", "voucher_id") and not path:
                continue
            out += _diff(a.get(k), b.get(k), (path + "." if path else "") + str(k))
    elif isinstance(a, list) and isinstance(b, list):
        for i in range(max(len(a), len(b))):
            out += _diff(a[i] if i < len(a) else None, b[i] if i < len(b) else None, "%s[%d]" % (path, i + 1))
    elif a != b:
        out.append({"field": path, "old": a, "new": b})
    return out


@api("tl.compare", "accounts", "view")
def tl_compare(c, u, a):
    log = tl_editlog(c, u, a)["versions"]
    by = {r["version"]: r for r in log}
    v2 = int(a.get("v2") or (max(by) if by else 1))
    v1 = int(a.get("v1") or max(1, v2 - 1))
    if v1 not in by or v2 not in by:
        raise ApiError("Choose two versions from the Edit Log.")
    return {"v1": v1, "v2": v2, "changes": _diff(by[v1]["snapshot"], by[v2]["snapshot"])}


# ───────────────────────────── reports in Tally groups ─────────────────────────────
def _movements(c, frm, to, project_id):
    pc, pp = (" AND l.project_id=?", [project_id]) if project_id else ("", [])
    rows = q(c, "SELECT l.account_id, l.party_id, SUM(CASE WHEN v.date<? THEN l.debit-l.credit ELSE 0 END) op, "
                "SUM(CASE WHEN v.date>=? THEN l.debit ELSE 0 END) d, SUM(CASE WHEN v.date>=? THEN l.credit ELSE 0 END) cr "
                "FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id WHERE " + POSTED + " AND v.date<=?" + pc +
             " GROUP BY l.account_id, l.party_id", [frm, frm, frm, to] + pp)
    return rows


def tb_tree(c, frm, to, project_id=None, parties=True, pl_reset=False):
    refresh_proposals(c)
    gs = _groups(c)
    gby = {g["id"]: dict(g, opening=0.0, debit=0.0, credit=0.0, closing=0.0, ledgers=[], groups=[]) for g in gs}
    amap = {r["account_id"]: r["tl_group_id"] for r in q(c, "SELECT account_id, tl_group_id FROM tl_amap")}
    accs = {r["id"]: r for r in q(c, "SELECT * FROM accounts")}
    pname = {r["id"]: r["name"] for r in q(c, "SELECT id, name FROM parties")}
    led = {}
    for r in _movements(c, frm, to, project_id):
        acc = accs.get(r["account_id"])
        if not acc:
            continue
        split = parties and r["party_id"] and acc["role"] in PARTY_ROLES
        key = (acc["id"], r["party_id"] if split else None)
        x = led.setdefault(key, {"account_id": acc["id"], "party_id": key[1], "opening": 0.0, "debit": 0.0, "credit": 0.0})
        x["opening"] += r["op"] or 0
        x["debit"] += r["d"] or 0
        x["credit"] += r["cr"] or 0
    if not project_id:
        for acc in accs.values():
            if acc["opening_balance"]:
                x = led.setdefault((acc["id"], None), {"account_id": acc["id"], "party_id": None, "opening": 0.0, "debit": 0.0, "credit": 0.0})
                x["opening"] += acc["opening_balance"]
    if pl_reset:  # P&L ledgers start each period at 0 (their earlier balance sits in Profit & Loss A/c)
        for x in led.values():
            if accs[x["account_id"]]["type"] in ("income", "expense"):
                x["opening"] = 0.0
    for (aid, pid), x in led.items():
        acc = accs[aid]
        x["closing"] = x["opening"] + x["debit"] - x["credit"]
        if max(abs(x["opening"]), abs(x["debit"]), abs(x["credit"]), abs(x["closing"])) < 0.005:
            continue
        gid = amap.get(aid) or _gid(c, "Suspense A/c")
        name = pname.get(pid, "Party %s" % pid) if pid else acc["name"]
        row = {"key": ("p:%d:%d" % (aid, pid)) if pid else ("a:%d" % aid), "account_id": aid, "party_id": pid,
               "name": name, "code": acc["code"], "under_account": acc["name"] if pid else None,
               "opening": r2(x["opening"]), "debit": r2(x["debit"]), "credit": r2(x["credit"]), "closing": r2(x["closing"]),
               "type": acc["type"]}
        gby[gid]["ledgers"].append(row)
        g = gby[gid]
        while g:
            for k in ("opening", "debit", "credit", "closing"):
                g[k] += row[k]
            g = gby.get(g["parent_id"]) if g["parent_id"] else None
    for g in gby.values():
        for k in ("opening", "debit", "credit", "closing"):
            g[k] = r2(g[k])
        g["ledgers"].sort(key=lambda r: r["name"].lower())
    roots = []
    for g in sorted(gby.values(), key=lambda g: (g["sort"], g["name"])):
        if g["parent_id"] and g["parent_id"] in gby:
            gby[g["parent_id"]]["groups"].append(g)
        else:
            roots.append(g)
    return roots, gby


def _prune(g):
    g["groups"] = [_prune(x) for x in g["groups"] if x["ledgers"] or x["groups"] and _has_rows(x)]
    return g


def _has_rows(g):
    return bool(g["ledgers"]) or any(_has_rows(x) for x in g["groups"])


@api("tl.tb", "accounts", "view")
def tl_tb(c, u, a):
    frm, to = a.get("from") or "0000-01-01", a.get("to") or today()
    roots, _ = tb_tree(c, frm, to, _i(a.get("project_id")), a.get("parties", True) not in (0, "0", False))
    roots = [_prune(g) for g in roots if _has_rows(g)]
    tot = {k: r2(sum(g[k] for g in roots)) for k in ("opening", "debit", "credit", "closing")}
    dr = r2(sum(g["closing"] for g in roots if g["closing"] > 0))
    cr = r2(-sum(g["closing"] for g in roots if g["closing"] < 0))
    return {"from": frm, "to": to, "groups": roots, "totals": tot, "closing_dr": dr, "closing_cr": cr,
            "difference": r2(dr - cr), "unconfirmed": val(c, "SELECT COUNT(*) FROM tl_amap WHERE confirmed=0")}


@api("tl.pl", "accounts", "view")
def tl_pl(c, u, a):
    """Profit & Loss A/c in the Tally layout: Trading (gross profit) then indirect items (net profit)."""
    frm, to = a.get("from") or _fy_start(c, a.get("to") or today()), a.get("to") or today()
    roots, gby = tb_tree(c, frm, to, _i(a.get("project_id")), False, pl_reset=True)
    by = {g["name"]: g for g in roots}

    def mv(name, sign):
        g = by.get(name)
        if not g:
            return {"name": name, "amount": 0.0, "group": None}
        amt = r2(sign * (g["debit"] - g["credit"]))
        return {"name": name, "amount": amt, "group": _prune(g) if _has_rows(g) else None}
    purchase, direct_exp = mv("Purchase Accounts", 1), mv("Direct Expenses", 1)
    sales, direct_inc = mv("Sales Accounts", -1), mv("Direct Incomes", -1)
    gross = r2(sales["amount"] + direct_inc["amount"] - purchase["amount"] - direct_exp["amount"])
    ind_exp, ind_inc = mv("Indirect Expenses", 1), mv("Indirect Incomes", -1)
    user_pl = [mv(g["name"], 1 if g["nature"] == "expense" else -1) for g in roots
               if g["nature"] in ("income", "expense") and g["name"] not in (
                   "Purchase Accounts", "Direct Expenses", "Sales Accounts", "Direct Incomes", "Indirect Expenses", "Indirect Incomes")]
    extra = r2(sum(-x["amount"] if (by[x["name"]]["nature"] == "expense") else x["amount"] for x in user_pl))
    net = r2(gross + ind_inc["amount"] - ind_exp["amount"] + extra)
    return {"from": frm, "to": to, "trading_dr": [purchase, direct_exp], "trading_cr": [sales, direct_inc],
            "gross_profit": gross, "indirect_dr": [ind_exp] + [x for x in user_pl if by[x["name"]]["nature"] == "expense"],
            "indirect_cr": [ind_inc] + [x for x in user_pl if by[x["name"]]["nature"] == "income"], "net_profit": net,
            "note": "Stock is perpetual in BuildCore: purchases of stock go to Stock-in-Hand and what is used is charged to "
                    "Direct Expenses, so there are no opening / closing stock lines."}


def _fy_start(c, d):
    fy = core.fy_of(c, d)
    r = q1(c, "SELECT MIN(start_date) s FROM fiscal_periods WHERE fy=?", (fy,))
    if r and r["s"]:
        return r["s"]
    y = int(d[:4]) - (1 if d[5:] < "07-16" else 0)
    return "%d-07-16" % y


@api("tl.bs", "accounts", "view")
def tl_bs(c, u, a):
    to = a.get("as_of") or a.get("to") or today()
    roots, gby = tb_tree(c, "0000-01-01", to, None, True)
    side = {"liabilities": [], "assets": []}
    pl_total = 0.0
    for g in roots:
        if g["nature"] in ("income", "expense"):
            pl_total += g["closing"]
            continue
        amt = r2(-g["closing"]) if g["nature"] == "liability" else r2(g["closing"])
        if abs(amt) < 0.005 and not _has_rows(g):
            continue
        (side["liabilities"] if g["nature"] == "liability" else side["assets"]).append(
            {"name": g["name"], "amount": amt, "group": _prune(g)})
    profit = r2(-pl_total)
    fys = _fy_start(c, to)
    cur = tl_pl(c, u, {"from": fys, "to": to})["net_profit"]
    side["liabilities"].append({"name": "Profit & Loss A/c", "amount": profit, "opening": r2(profit - cur), "current": cur, "group": None})
    tl_ = r2(sum(x["amount"] for x in side["liabilities"]))
    ta = r2(sum(x["amount"] for x in side["assets"]))
    diff = r2(ta - tl_)
    return {"as_of": to, "liabilities": side["liabilities"], "assets": side["assets"], "total_liabilities": tl_,
            "total_assets": ta, "difference": diff,
            "difference_note": ("Difference in opening balances %s: the accounts' opening balances do not agree." % diff) if abs(diff) > 0.01 else ""}


@api("tl.daybook", "accounts", "view")
def tl_daybook(c, u, a):
    frm, to = a.get("from") or today(), a.get("to") or today()
    vs = q(c, "SELECT * FROM vouchers WHERE (status IN ('posted','reversed','draft')) AND date BETWEEN ? AND ? ORDER BY date, id", (frm, to))
    cache = {}
    want = a.get("vtype")
    out = []
    hide = set()
    if not a.get("show_altered"):
        for r in q(c, "SELECT voucher_id, reversal_id FROM tl_vmeta WHERE superseded_by IS NOT NULL"):
            hide.add(r["voucher_id"])
            if r["reversal_id"]:
                hide.add(r["reversal_id"])
    pname = {r["id"]: r["name"] for r in q(c, "SELECT id, name FROM parties")}
    for v in vs:
        if v["id"] in hide:
            continue
        v["voucher_type"] = vtype_of(c, v, cache)
        v["shown_no"] = disp_no(c, v)
        v["altered"] = val(c, "SELECT altered FROM tl_vmeta WHERE voucher_id=?", (v["id"],), 0) or 0
        if want and v["voucher_type"] != want:
            continue
        lines = q(c, "SELECT l.debit, l.credit, l.party_id, a.name FROM voucher_lines l JOIN accounts a ON a.id=l.account_id "
                     "WHERE voucher_id=? ORDER BY l.id", (v["id"],))
        first = next((x for x in lines if x["party_id"]), None) or (lines[0] if lines else None)
        v["particulars"] = (pname.get(first["party_id"]) if first and first["party_id"] else (first or {}).get("name")) or ""
        v["debit"] = r2(sum(x["debit"] for x in lines))
        v["credit"] = r2(sum(x["credit"] for x in lines))
        v["state"] = {"draft": "pending approval", "reversed": "cancelled"}.get(v["status"], "") if v["source"] != "reversal" else "reversal"
        out.append(v)
    return {"from": frm, "to": to, "rows": out, "types": sorted({r["voucher_type"] for r in out})}


# ───────────────────────────── wrappers on existing functions ─────────────────────────────
def _w_voucher_save(orig):
    def voucher_save(c, u, a):
        h = a.get("header") or {}
        if on(c):
            check_lock_date(c, h.get("date"))
            if not h.get("id"):
                check_backdate(c, u, h.get("date"))
        res = orig(c, u, a)
        if on(c) and res and res.get("id"):
            _log(c, u, "voucher", res["id"], "altered" if h.get("id") else "created", voucher_snap(c, res["id"]))
        return res
    return voucher_save


def _w_voucher_post(orig):
    def voucher_post(c, u, a):
        did = a.get("id")
        meta = q1(c, "SELECT * FROM tl_vmeta WHERE voucher_id=?", (did,))
        bills = q(c, "SELECT * FROM tl_bills WHERE voucher_id=?", (did,))
        old_log = q(c, "SELECT id FROM tl_editlog WHERE entity='voucher' AND entity_id=?", (did,))
        if on(c):
            check_lock_date(c, val(c, "SELECT date FROM vouchers WHERE id=?", (did,), None))
        res = orig(c, u, a)
        nid = res.get("id") if res else None
        if nid:
            c.execute("DELETE FROM tl_vmeta WHERE voucher_id=?", (did,))
            if meta:
                meta["voucher_id"] = nid
                ins(c, "tl_vmeta", meta)
            for b in bills:
                c.execute("UPDATE tl_bills SET voucher_id=?, status='active' WHERE id=?", (nid, b["id"]))
            for r in old_log:
                c.execute("UPDATE tl_editlog SET entity_id=? WHERE id=?", (nid, r["id"]))
            if meta:
                vt = q1(c, "SELECT * FROM tl_vtypes WHERE id=?", (meta["vtype_id"],))
                no = apply_number(c, nid, vt, val(c, "SELECT project_id FROM vouchers WHERE id=?", (nid,), None), meta.get("vno"))
                c.execute("UPDATE tl_vmeta SET vno=? WHERE voucher_id=?", (no, nid))
            if on(c):
                _log(c, u, "voucher", nid, "posted", voucher_snap(c, nid))
        return res
    return voucher_post


def _w_voucher_reverse(orig):
    def voucher_reverse(c, u, a):
        if on(c):
            _first_log(c, u, "voucher", a.get("id"), voucher_snap(c, a.get("id")))
        res = orig(c, u, a)
        c.execute("UPDATE tl_bills SET status='cancelled' WHERE voucher_id=?", (a.get("id"),))
        c.execute("UPDATE tl_vmeta SET cancelled=1 WHERE voucher_id=?", (a.get("id"),))
        if on(c):
            _log(c, u, "voucher", a.get("id"), "cancelled", voucher_snap(c, a.get("id")), a.get("reason"))
        return res
    return voucher_reverse


def _w_voucher_delete(orig):
    def voucher_delete(c, u, a):
        snap = voucher_snap(c, a.get("id"))
        res = orig(c, u, a)
        c.execute("DELETE FROM tl_bills WHERE voucher_id=?", (a.get("id"),))
        c.execute("DELETE FROM tl_vmeta WHERE voucher_id=?", (a.get("id"),))
        if on(c) and snap:
            _log(c, u, "voucher", a.get("id"), "deleted", snap)
        return res
    return voucher_delete


def _w_payment_create(orig):
    def payment_create(c, u, a):
        if on(c):
            check_lock_date(c, a.get("date"))
            check_backdate(c, u, a.get("date"))
        res = orig(c, u, a)
        if on(c) and res and res.get("id"):
            vid = val(c, "SELECT voucher_id FROM payments WHERE id=?", (res["id"],), None)
            if vid and not val(c, "SELECT COUNT(*) FROM tl_vmeta WHERE voucher_id=?", (vid,)):
                _log(c, u, "voucher", vid, "created", voucher_snap(c, vid))
        return res
    return payment_create


def _w_payment_cancel(orig):
    def payment_cancel(c, u, a):
        vid = val(c, "SELECT voucher_id FROM payments WHERE id=?", (a.get("id"),), None)
        if on(c) and vid:
            _first_log(c, u, "voucher", vid, voucher_snap(c, vid))
        res = orig(c, u, a)
        if vid:
            c.execute("UPDATE tl_vmeta SET cancelled=1 WHERE voucher_id=?", (vid,))
            if on(c):
                _log(c, u, "voucher", vid, "cancelled", voucher_snap(c, vid), a.get("reason"))
        return res
    return payment_cancel


MASTER_ENTITY = {"accounts": "ledger", "account_groups": "account_group", "parties": "party", "materials": "item",
                 "projects": "project", "boq_items": "boq_item", "equipment": "machine", "tds_rates": "tds_rate",
                 "stores": "godown", "staff": "staff"}


def _w_master_save(orig):
    def master_save(c, u, a):
        t = a.get("table")
        rid = (a.get("row") or {}).get("id")
        if on(c) and t in MASTER_ENTITY and rid:
            _first_log(c, u, MASTER_ENTITY[t], rid, q1(c, "SELECT * FROM %s WHERE id=?" % t, (rid,)))
        res = orig(c, u, a)
        if on(c) and t in MASTER_ENTITY and res and res.get("id"):
            _log(c, u, MASTER_ENTITY[t], res["id"], "altered" if rid else "created", res)
        return res
    return master_save


def _w_master_delete(orig):
    def master_delete(c, u, a):
        t = a.get("table")
        snap = q1(c, "SELECT * FROM %s WHERE id=?" % t, (a.get("id"),)) if t in MASTER_ENTITY else None
        res = orig(c, u, a)
        if on(c) and snap:
            _log(c, u, MASTER_ENTITY[t], a.get("id"), "deleted", snap)
        if t == "accounts":
            c.execute("DELETE FROM tl_amap WHERE account_id=?", (a.get("id"),))
            c.execute("DELETE FROM tl_ledger WHERE account_id=?", (a.get("id"),))
        return res
    return master_delete


def _w_integrity(orig):
    """Creditors / Debtors checks: bills made on the voucher screen (New Ref, On Account) are open items too."""
    def rep_integrity(c, u, a):
        res = orig(c, u, a)
        checks = res if isinstance(res, list) else (res or {}).get("checks", [])
        for ck in checks:
            name = ck.get("check") or ""
            role = "ap_control" if name.startswith("Creditors = open") else "ar_control" if name.startswith("Debtors = open") else None
            if not role or ck.get("ok"):
                continue
            tl = r2(val(c, "SELECT SUM(b.amount) FROM tl_bills b JOIN accounts x ON x.id=b.account_id "
                           "WHERE b.status='active' AND b.invoice_id IS NULL AND x.role=?", (role,), 0) or 0)
            if not tl:
                continue
            tl = -tl if role == "ap_control" else tl
            nums = re.findall(r"-?\d+(?:\.\d+)?", ck.get("detail") or "")
            try:
                books, inv_open = float(nums[0]), float(nums[1])
            except Exception:
                continue
            ck["detail"] = "Books %s, invoices %s + voucher-screen bills %s" % (books, inv_open, tl)
            ck["ok"] = abs(books - inv_open - tl) < 1
        return res
    return rep_integrity


def _assert_open_factory(orig):
    def assert_open(c, user, d):
        orig(c, user, d)
        check_lock_date(c, d)
    return assert_open


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


def init_tally(c):
    c.executescript(SCHEMA)
    seed_groups(c)
    seed_vtypes(c)
    try:
        _default(c, "tl_on", "1", "0")
        _default(c, "tl_policy", "edit_with_log", "reverse_only")
    except Exception:
        c.execute("INSERT OR IGNORE INTO settings(key, value) VALUES('tl_on', '0')")
        c.execute("INSERT OR IGNORE INTO settings(key, value) VALUES('tl_policy', 'reverse_only')")
    for k, v in (("tl_lock_date", ""), ("tl_backdate", "{}"), ("tl_alterdays", "{}"), ("tl_features", "{}")):
        c.execute("INSERT OR IGNORE INTO settings(key, value) VALUES(?,?)", (k, v))
    c.commit()
    for name, fac in (("voucher.save", _w_voucher_save), ("voucher.post", _w_voucher_post),
                      ("voucher.reverse", _w_voucher_reverse), ("voucher.delete", _w_voucher_delete),
                      ("payment.create", _w_payment_create), ("payment.cancel", _w_payment_cancel),
                      ("master.save", _w_master_save), ("master.delete", _w_master_delete),
                      ("rep.integrity", _w_integrity)):
        _wrap(name, fac)
    if not getattr(core.assert_open, FLAG, False):
        w = _assert_open_factory(core.assert_open)
        setattr(w, FLAG, True)
        core.assert_open = w
    try:
        import api_workspace as W
        for fn in ("tl.tb", "tl.bs", "tl.pl", "tl.daybook", "tl.editlog_company", "tl.map", "tl.map_save", "tl.settings_save",
                   "tl.pack", "tl.group_save", "tl.group_delete", "tl.vtype_save", "tl.vtype_delete"):
            W.COMPANY_FNS.add(fn)
    except Exception:
        pass
