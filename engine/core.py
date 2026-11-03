"""BuildCore Offline - core engine.

Database schema, helpers, authentication, document numbering,
double-entry posting engine and stock (weighted-average) engine.
Only the Python standard library is used.
"""
import hashlib
import json
import os
import secrets
import sqlite3
import threading
from datetime import date, datetime, timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.environ.get("BCO_DATA_DIR") or BASE_DIR  # desktop app keeps data outside the program folder
DATA_DIR = os.path.join(_ROOT, "data")
BACKUP_DIR = os.path.join(_ROOT, "backups")
DB_PATH = os.path.join(DATA_DIR, "buildcore.db")
LOCK = threading.RLock()
EPS = 1e-6


class ApiError(Exception):
    pass


def r2(x):
    return round((x or 0) + 0.0, 2)


def r4(x):
    return round((x or 0) + 0.0, 4)


def today():
    return date.today().isoformat()


def now():
    return datetime.now().isoformat(timespec="seconds")


# ─────────────────────────── schema ───────────────────────────
SCHEMA = """
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, name TEXT,
  pw_hash TEXT, salt TEXT, role TEXT NOT NULL, active INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY, user_id INTEGER, created TEXT);
CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY, ts TEXT, user_id INTEGER, action TEXT,
  entity TEXT, entity_id INTEGER, detail TEXT);
CREATE TABLE IF NOT EXISTS projects(id INTEGER PRIMARY KEY, code TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
  client TEXT, location TEXT, contract_value REAL DEFAULT 0, start_date TEXT, end_date TEXT,
  status TEXT DEFAULT 'active');
CREATE TABLE IF NOT EXISTS fiscal_periods(id INTEGER PRIMARY KEY, fy TEXT, code TEXT UNIQUE,
  start_date TEXT, end_date TEXT, status TEXT DEFAULT 'open');
CREATE TABLE IF NOT EXISTS sequences(doc_type TEXT, fy TEXT, next INTEGER, PRIMARY KEY(doc_type, fy));

CREATE TABLE IF NOT EXISTS account_groups(id INTEGER PRIMARY KEY, code TEXT UNIQUE, name TEXT,
  type TEXT, parent_id INTEGER);
CREATE TABLE IF NOT EXISTS accounts(id INTEGER PRIMARY KEY, code TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
  type TEXT NOT NULL, group_id INTEGER, role TEXT, opening_balance REAL DEFAULT 0,
  bank_name TEXT, bank_acno TEXT, active INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS tds_rates(id INTEGER PRIMARY KEY, section TEXT, description TEXT,
  rate REAL, threshold REAL DEFAULT 0, active INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS budgets(id INTEGER PRIMARY KEY, project_id INTEGER, account_id INTEGER,
  boq_item_id INTEGER, amount REAL DEFAULT 0, remarks TEXT);

CREATE TABLE IF NOT EXISTS parties(id INTEGER PRIMARY KEY, code TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
  kind TEXT NOT NULL, pan TEXT, vat_registered INTEGER DEFAULT 0, phone TEXT, email TEXT, address TEXT,
  bank TEXT, bank_acno TEXT, credit_days INTEGER DEFAULT 30, categories TEXT,
  blacklisted INTEGER DEFAULT 0, active INTEGER DEFAULT 1, notes TEXT);
CREATE TABLE IF NOT EXISTS staff(id INTEGER PRIMARY KEY, code TEXT UNIQUE, name TEXT NOT NULL,
  designation TEXT, phone TEXT, daily_rate REAL, monthly_rate REAL, project_id INTEGER, active INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS boq_items(id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL, code TEXT,
  description TEXT, unit TEXT, qty REAL DEFAULT 0, rate REAL DEFAULT 0, executed_qty REAL DEFAULT 0);
CREATE TABLE IF NOT EXISTS material_coefficients(id INTEGER PRIMARY KEY, boq_item_id INTEGER,
  material_id INTEGER, qty_per_unit REAL, wastage_pct REAL DEFAULT 0);

CREATE TABLE IF NOT EXISTS materials(id INTEGER PRIMARY KEY, code TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
  local_name TEXT, category TEXT, unit TEXT, spec TEXT, min_level REAL DEFAULT 0,
  reorder_level REAL DEFAULT 0, reorder_qty REAL DEFAULT 0, lead_days INTEGER DEFAULT 0,
  standard_rate REAL DEFAULT 0, batch_tracked INTEGER DEFAULT 0, active INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS stores(id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL, code TEXT,
  name TEXT, type TEXT DEFAULT 'sub', parent_id INTEGER, keeper TEXT, active INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS stock_balances(project_id INTEGER, store_id INTEGER, material_id INTEGER,
  qty REAL DEFAULT 0, value REAL DEFAULT 0, last_date TEXT,
  PRIMARY KEY(project_id, store_id, material_id));
CREATE TABLE IF NOT EXISTS stock_ledger(id INTEGER PRIMARY KEY, date TEXT, project_id INTEGER,
  store_id INTEGER, material_id INTEGER, doc_type TEXT, doc_id INTEGER, doc_no TEXT,
  qty_in REAL DEFAULT 0, qty_out REAL DEFAULT 0, rate REAL, value_in REAL DEFAULT 0,
  value_out REAL DEFAULT 0, batch_no TEXT, created_by INTEGER, ts TEXT);
CREATE INDEX IF NOT EXISTS ix_sl_item ON stock_ledger(project_id, material_id, store_id, date);
CREATE INDEX IF NOT EXISTS ix_sl_doc ON stock_ledger(doc_type, doc_id);

CREATE TABLE IF NOT EXISTS mrq(id INTEGER PRIMARY KEY, no TEXT, project_id INTEGER, date TEXT,
  store_id INTEGER, requested_by TEXT, status TEXT DEFAULT 'draft', remarks TEXT, auto INTEGER DEFAULT 0,
  created_by INTEGER, approved_by INTEGER);
CREATE TABLE IF NOT EXISTS mrq_lines(id INTEGER PRIMARY KEY, mrq_id INTEGER, material_id INTEGER,
  qty REAL, approved_qty REAL, issued_qty REAL DEFAULT 0, pr_qty REAL DEFAULT 0, boq_item_id INTEGER, remarks TEXT);

CREATE TABLE IF NOT EXISTS grn(id INTEGER PRIMARY KEY, no TEXT, project_id INTEGER, store_id INTEGER,
  vendor_id INTEGER, po_id INTEGER, date TEXT, challan_no TEXT, vehicle_no TEXT, freight REAL DEFAULT 0,
  status TEXT DEFAULT 'draft', remarks TEXT, voucher_id INTEGER, created_by INTEGER);
CREATE TABLE IF NOT EXISTS grn_lines(id INTEGER PRIMARY KEY, grn_id INTEGER, po_line_id INTEGER,
  material_id INTEGER, received_qty REAL, accepted_qty REAL, rejected_qty REAL DEFAULT 0, rate REAL,
  landed_rate REAL, invoiced_qty REAL DEFAULT 0, batch_no TEXT, remarks TEXT);

CREATE TABLE IF NOT EXISTS issues(id INTEGER PRIMARY KEY, no TEXT, project_id INTEGER, store_id INTEGER,
  date TEXT, issued_to TEXT, mrq_id INTEGER, wo_id INTEGER, status TEXT DEFAULT 'draft', remarks TEXT,
  voucher_id INTEGER, created_by INTEGER);
CREATE TABLE IF NOT EXISTS issue_lines(id INTEGER PRIMARY KEY, issue_id INTEGER, material_id INTEGER,
  qty REAL, rate REAL, amount REAL, target TEXT DEFAULT 'boq', boq_item_id INTEGER, equipment_id INTEGER,
  mrq_line_id INTEGER, returned_qty REAL DEFAULT 0);

CREATE TABLE IF NOT EXISTS returns(id INTEGER PRIMARY KEY, no TEXT, project_id INTEGER, store_id INTEGER,
  date TEXT, returned_by TEXT, status TEXT DEFAULT 'draft', remarks TEXT, voucher_id INTEGER, created_by INTEGER);
CREATE TABLE IF NOT EXISTS return_lines(id INTEGER PRIMARY KEY, return_id INTEGER, material_id INTEGER,
  issue_line_id INTEGER, qty REAL, condition TEXT DEFAULT 'usable', rate REAL, amount REAL,
  boq_item_id INTEGER, equipment_id INTEGER);

CREATE TABLE IF NOT EXISTS transfers(id INTEGER PRIMARY KEY, no TEXT, from_project INTEGER, from_store INTEGER,
  to_project INTEGER, to_store INTEGER, date TEXT, received_date TEXT, status TEXT DEFAULT 'draft',
  vehicle_no TEXT, remarks TEXT, voucher_id INTEGER, created_by INTEGER);
CREATE TABLE IF NOT EXISTS transfer_lines(id INTEGER PRIMARY KEY, transfer_id INTEGER, material_id INTEGER,
  qty REAL, rate REAL, received_qty REAL DEFAULT 0);

CREATE TABLE IF NOT EXISTS stock_counts(id INTEGER PRIMARY KEY, no TEXT, project_id INTEGER, store_id INTEGER,
  date TEXT, status TEXT DEFAULT 'draft', remarks TEXT, voucher_id INTEGER, created_by INTEGER);
CREATE TABLE IF NOT EXISTS count_lines(id INTEGER PRIMARY KEY, count_id INTEGER, material_id INTEGER,
  system_qty REAL, counted_qty REAL, rate REAL, reason TEXT);

CREATE TABLE IF NOT EXISTS pr(id INTEGER PRIMARY KEY, no TEXT, project_id INTEGER, date TEXT, required_by TEXT,
  source TEXT DEFAULT 'manual', mrq_id INTEGER, status TEXT DEFAULT 'draft', priority TEXT DEFAULT 'normal',
  remarks TEXT, created_by INTEGER, approved_by INTEGER);
CREATE TABLE IF NOT EXISTS pr_lines(id INTEGER PRIMARY KEY, pr_id INTEGER, material_id INTEGER,
  description TEXT, qty REAL, unit TEXT, est_rate REAL DEFAULT 0, boq_item_id INTEGER,
  ordered_qty REAL DEFAULT 0, mrq_line_id INTEGER);

CREATE TABLE IF NOT EXISTS cs(id INTEGER PRIMARY KEY, no TEXT, pr_id INTEGER, project_id INTEGER, date TEXT,
  status TEXT DEFAULT 'draft', recommended_vendor_id INTEGER, reason TEXT, remarks TEXT,
  po_id INTEGER, created_by INTEGER, approved_by INTEGER);
CREATE TABLE IF NOT EXISTS cs_quotes(id INTEGER PRIMARY KEY, cs_id INTEGER, vendor_id INTEGER, quote_no TEXT,
  freight REAL DEFAULT 0, vat_rate REAL DEFAULT 0, delivery_days INTEGER, payment_terms TEXT, rates TEXT);

CREATE TABLE IF NOT EXISTS po(id INTEGER PRIMARY KEY, no TEXT, project_id INTEGER, vendor_id INTEGER, date TEXT,
  delivery_date TEXT, store_id INTEGER, pr_id INTEGER, cs_id INTEGER, payment_terms TEXT,
  freight REAL DEFAULT 0, subtotal REAL DEFAULT 0, vat REAL DEFAULT 0, total REAL DEFAULT 0,
  status TEXT DEFAULT 'draft', revision INTEGER DEFAULT 0, terms TEXT, remarks TEXT,
  created_by INTEGER, approved_by INTEGER, approved_at TEXT, close_reason TEXT);
CREATE TABLE IF NOT EXISTS po_lines(id INTEGER PRIMARY KEY, po_id INTEGER, pr_line_id INTEGER,
  material_id INTEGER, description TEXT, qty REAL, unit TEXT, rate REAL, vat_rate REAL DEFAULT 0,
  received_qty REAL DEFAULT 0, boq_item_id INTEGER);
CREATE TABLE IF NOT EXISTS po_revisions(id INTEGER PRIMARY KEY, po_id INTEGER, revision INTEGER,
  snapshot TEXT, reason TEXT, ts TEXT, user_id INTEGER);
CREATE TABLE IF NOT EXISTS vendor_ratings(id INTEGER PRIMARY KEY, vendor_id INTEGER, po_id INTEGER,
  quality INTEGER, delivery INTEGER, price INTEGER, service INTEGER, remarks TEXT, date TEXT);

CREATE TABLE IF NOT EXISTS invoices(id INTEGER PRIMARY KEY, no TEXT, kind TEXT, party_id INTEGER,
  project_id INTEGER, date TEXT, party_inv_no TEXT, due_date TEXT, po_id INTEGER,
  subtotal REAL DEFAULT 0, vat REAL DEFAULT 0, tds REAL DEFAULT 0, retention REAL DEFAULT 0,
  advance_recovery REAL DEFAULT 0, total REAL DEFAULT 0, payable REAL DEFAULT 0,
  status TEXT DEFAULT 'draft', match_status TEXT, source TEXT, remarks TEXT,
  voucher_id INTEGER, created_by INTEGER);
CREATE TABLE IF NOT EXISTS invoice_lines(id INTEGER PRIMARY KEY, invoice_id INTEGER, grn_line_id INTEGER,
  material_id INTEGER, description TEXT, qty REAL, rate REAL, vat_rate REAL DEFAULT 0, amount REAL,
  account_id INTEGER, equipment_id INTEGER, boq_item_id INTEGER);

CREATE TABLE IF NOT EXISTS payments(id INTEGER PRIMARY KEY, no TEXT, kind TEXT, party_id INTEGER,
  project_id INTEGER, date TEXT, bank_account_id INTEGER, gross REAL, tds REAL DEFAULT 0,
  tds_rate_id INTEGER, net REAL, advance REAL DEFAULT 0, mode TEXT, cheque_no TEXT,
  status TEXT DEFAULT 'posted', remarks TEXT, voucher_id INTEGER, created_by INTEGER);
CREATE TABLE IF NOT EXISTS allocations(id INTEGER PRIMARY KEY, payment_id INTEGER, invoice_id INTEGER,
  amount REAL, date TEXT, voucher_id INTEGER, active INTEGER DEFAULT 1);

CREATE TABLE IF NOT EXISTS vouchers(id INTEGER PRIMARY KEY, no TEXT, type TEXT, date TEXT, project_id INTEGER,
  narration TEXT, status TEXT, source TEXT, source_id INTEGER, reversal_of INTEGER, party_id INTEGER,
  ref_no TEXT, total REAL, created_by INTEGER, approved_by INTEGER, ts TEXT);
CREATE INDEX IF NOT EXISTS ix_v_source ON vouchers(source, source_id);
CREATE INDEX IF NOT EXISTS ix_v_date ON vouchers(date);
CREATE TABLE IF NOT EXISTS voucher_lines(id INTEGER PRIMARY KEY, voucher_id INTEGER, account_id INTEGER,
  debit REAL DEFAULT 0, credit REAL DEFAULT 0, narration TEXT, project_id INTEGER, boq_item_id INTEGER,
  equipment_id INTEGER, party_id INTEGER, cleared_date TEXT);
CREATE INDEX IF NOT EXISTS ix_vl_v ON voucher_lines(voucher_id);
CREATE INDEX IF NOT EXISTS ix_vl_acc ON voucher_lines(account_id);
CREATE INDEX IF NOT EXISTS ix_vl_eq ON voucher_lines(equipment_id);

CREATE TABLE IF NOT EXISTS equipment(id INTEGER PRIMARY KEY, code TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
  category TEXT, make TEXT, model TEXT, serial TEXT, reg_no TEXT, ownership TEXT DEFAULT 'owned',
  vendor_id INTEGER, purchase_date TEXT, purchase_value REAL DEFAULT 0, residual_value REAL DEFAULT 0,
  life_months INTEGER DEFAULT 0, dep_method TEXT DEFAULT 'sl', wdv_rate REAL DEFAULT 0,
  est_total_hours REAL DEFAULT 0, accumulated_dep REAL DEFAULT 0, meter_type TEXT DEFAULT 'hours',
  meter REAL DEFAULT 0, fuel_norm REAL DEFAULT 0, internal_rate REAL DEFAULT 0,
  insurance_expiry TEXT, registration_expiry TEXT, status TEXT DEFAULT 'working', project_id INTEGER,
  operator TEXT, notes TEXT, active INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS equipment_status_log(id INTEGER PRIMARY KEY, equipment_id INTEGER, status TEXT,
  from_ts TEXT, to_ts TEXT, reason TEXT, user_id INTEGER);
CREATE TABLE IF NOT EXISTS deployments(id INTEGER PRIMARY KEY, equipment_id INTEGER, project_id INTEGER,
  mob_date TEXT, demob_date TEXT, meter REAL, remarks TEXT);
CREATE TABLE IF NOT EXISTS logsheets(id INTEGER PRIMARY KEY, equipment_id INTEGER, project_id INTEGER,
  date TEXT, shift TEXT DEFAULT 'day', operator TEXT, meter_start REAL, meter_end REAL, hours REAL DEFAULT 0,
  idle_hours REAL DEFAULT 0, breakdown_hours REAL DEFAULT 0, boq_item_id INTEGER, work TEXT,
  trips REAL DEFAULT 0, status TEXT DEFAULT 'draft', approved_by INTEGER, created_by INTEGER);
CREATE TABLE IF NOT EXISTS maint_plans(id INTEGER PRIMARY KEY, equipment_id INTEGER, title TEXT,
  interval_type TEXT DEFAULT 'days', interval REAL, last_date TEXT, last_meter REAL DEFAULT 0,
  checklist TEXT, active INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS work_orders(id INTEGER PRIMARY KEY, no TEXT, equipment_id INTEGER, project_id INTEGER,
  plan_id INTEGER, type TEXT DEFAULT 'breakdown', status TEXT DEFAULT 'open', reported_at TEXT,
  started_at TEXT, completed_at TEXT, description TEXT, action_taken TEXT, downtime_hours REAL DEFAULT 0,
  meter REAL, technician TEXT, created_by INTEGER);
CREATE TABLE IF NOT EXISTS hire_agreements(id INTEGER PRIMARY KEY, equipment_id INTEGER, vendor_id INTEGER,
  project_id INTEGER, rate REAL, unit TEXT DEFAULT 'hour', min_units REAL DEFAULT 0, mob_cost REAL DEFAULT 0,
  vat_rate REAL DEFAULT 0, start_date TEXT, end_date TEXT, active INTEGER DEFAULT 1, remarks TEXT);
CREATE TABLE IF NOT EXISTS hire_bills(id INTEGER PRIMARY KEY, agreement_id INTEGER, month TEXT,
  units REAL, billed_units REAL, amount REAL, invoice_id INTEGER, UNIQUE(agreement_id, month));
CREATE TABLE IF NOT EXISTS dep_runs(id INTEGER PRIMARY KEY, equipment_id INTEGER, month TEXT, amount REAL,
  voucher_id INTEGER, UNIQUE(equipment_id, month));
CREATE TABLE IF NOT EXISTS internal_bills(id INTEGER PRIMARY KEY, equipment_id INTEGER, project_id INTEGER,
  month TEXT, hours REAL, rate REAL, amount REAL, voucher_id INTEGER, UNIQUE(equipment_id, project_id, month));
"""

DEFAULT_SETTINGS = {
    "company_name": "My Construction Company",
    "company_pan": "",
    "company_address": "",
    "vat_rate": "13",
    "price_tol_pct": "2",
    "over_receipt_pct": "5",
    "allow_negative_stock": "0",
    "shift_hours": "10",
    "high_value_po": "5000000",
    "voucher_approval": "1",
    "last_auto_run": "",
    "min_quotes": "3",
    "po_terms": "1. Deliver to the project store named above.\n2. Supply as per approved specification; rejected material will be returned at vendor cost.\n3. Invoice must quote this PO number and the GRN number.",
    "date_display": "AD",
    # ── teamwork ──
    "site_code": "",            # short code of THIS copy, e.g. HO or MKHEP-SITE (only needed for site packs)
    "site_name": "",            # where this copy stands, e.g. "Head office, Kathmandu"
    "session_days": "30",       # a sign-in lasts this many days without use
    "allow_public": "0",        # serve computers outside the office network / VPN
    "lock_minutes": "10",       # how long a username is locked after repeated wrong passwords
}

DEFAULT_GROUPS = [
    ("A", "Assets", "asset", None), ("A1", "Cash & Bank", "asset", "A"),
    ("A2", "Inventories", "asset", "A"), ("A3", "Receivables & Advances", "asset", "A"),
    ("A4", "Tax Assets", "asset", "A"), ("A5", "Fixed Assets", "asset", "A"),
    ("L", "Liabilities", "liability", None), ("L1", "Payables", "liability", "L"),
    ("L2", "Duties & Taxes", "liability", "L"), ("L3", "Advances & Retention", "liability", "L"),
    ("E", "Equity", "equity", None),
    ("I", "Income", "income", None),
    ("X", "Expenses", "expense", None), ("X1", "Direct Contract Costs", "expense", "X"),
    ("X2", "Equipment Costs", "expense", "X"), ("X3", "Overheads & Other", "expense", "X"),
]

DEFAULT_ACCOUNTS = [
    ("1001", "Cash in Hand - Site", "asset", "A1", "cash"),
    ("1002", "Bank Account", "asset", "A1", "bank"),
    ("1101", "Inventory - Construction Materials", "asset", "A2", "inventory"),
    ("1102", "Inventory - Fuel & Lubricants", "asset", "A2", "inventory_fuel"),
    ("1103", "Inventory - Spare Parts", "asset", "A2", "inventory_spares"),
    ("1201", "Sundry Debtors - Clients", "asset", "A3", "ar_control"),
    ("1202", "Advance to Suppliers", "asset", "A3", "supplier_advance"),
    ("1203", "Mobilisation Advance to Subcontractors", "asset", "A3", "subcon_advance"),
    ("1204", "Retention Receivable", "asset", "A3", "retention_receivable"),
    ("1301", "VAT Input", "asset", "A4", "vat_input"),
    ("1302", "TDS Receivable", "asset", "A4", "tds_receivable"),
    ("1501", "Plant & Machinery", "asset", "A5", "fixed_asset"),
    ("1502", "Accumulated Depreciation", "asset", "A5", "accum_dep"),
    ("2001", "Sundry Creditors - Suppliers", "liability", "L1", "ap_control"),
    ("2002", "GRN Clearing (Goods Received Not Invoiced)", "liability", "L1", "grni"),
    ("2003", "Freight & Carriage Clearing", "liability", "L1", "freight_clearing"),
    ("2004", "Salary & Wages Payable", "liability", "L1", "payroll_payable"),
    ("2101", "VAT Output", "liability", "L2", "vat_output"),
    ("2102", "TDS Payable", "liability", "L2", "tds_payable"),
    ("2201", "Mobilisation Advance from Client", "liability", "L3", "client_advance"),
    ("2202", "Retention Payable", "liability", "L3", "retention_payable"),
    ("3001", "Capital / Head Office Account", "equity", "E", "capital"),
    ("3002", "Retained Earnings", "equity", "E", "retained_earnings"),
    ("4001", "Contract Revenue", "income", "I", "contract_revenue"),
    ("4002", "Equipment Hire Recovery (Internal)", "income", "I", "equipment_recovery"),
    ("4003", "Stock Adjustment Gain", "income", "I", "stock_gain"),
    ("5001", "Material Consumed", "expense", "X1", "material_cost"),
    ("5002", "Labour & Wages", "expense", "X1", "labour_cost"),
    ("5003", "Subcontract Cost", "expense", "X1", "subcon_cost"),
    ("5004", "Purchase Price Variance", "expense", "X1", "price_variance"),
    ("5101", "Equipment Hire (External)", "expense", "X2", "hire_cost"),
    ("5102", "Fuel & Lubricants Consumed", "expense", "X2", "fuel_cost"),
    ("5103", "Repairs & Maintenance - Equipment", "expense", "X2", "repair_cost"),
    ("5104", "Depreciation", "expense", "X2", "depreciation"),
    ("5105", "Internal Equipment Charges", "expense", "X2", "equipment_cost"),
    ("5201", "Site Overheads", "expense", "X3", "overhead"),
    ("5202", "Inventory Loss & Write-off", "expense", "X3", "inventory_loss"),
]

DEFAULT_TDS = [
    ("88", "Service / contract payment (verify rate)", 1.5, 50000),
    ("88", "Professional service (verify rate)", 15, 0),
    ("88", "Rent (verify rate)", 10, 0),
]

# ───────────────────────── permissions ─────────────────────────
MODULES = ["masters", "inventory", "procurement", "accounts", "equipment", "admin", "project", "commercial",
           "quality", "plant", "assets"]
V, E, A = "view", "edit", "approve"
ROLES = {
    "admin": {m: {V, E, A} for m in MODULES},
    "project_manager": {"masters": {V, E}, "inventory": {V, A}, "procurement": {V, A},
                        "accounts": {V}, "equipment": {V, A}, "project": {V, E, A}, "commercial": {V, E, A},
                        "quality": {V, E, A}, "plant": {V, A}, "assets": {V}},
    "accountant": {"masters": {V, E}, "inventory": {V}, "procurement": {V, E},
                   "accounts": {V, E, A}, "equipment": {V}, "project": {V}, "commercial": {V, E}, "quality": {V},
                   "plant": {V}, "assets": {V, E, A}},
    "storekeeper": {"masters": {V}, "inventory": {V, E}, "procurement": {V},
                    "accounts": set(), "equipment": {V}, "project": {V}, "plant": {V, E}, "assets": {V}},
    "procurement_officer": {"masters": {V, E}, "inventory": {V}, "procurement": {V, E},
                            "accounts": set(), "equipment": {V}},
    "equipment_manager": {"masters": {V}, "inventory": {V, E}, "procurement": {V},
                          "accounts": set(), "equipment": {V, E, A}, "project": {V},
                          "plant": {V, E, A}, "assets": {V, E}},
    "viewer": {m: {V} for m in MODULES if m != "admin"},
    "director": {m: {V, A} for m in MODULES if m != "admin"},
    "site_engineer": {"masters": {V}, "inventory": {V, E}, "procurement": {V}, "equipment": {V, E},
                      "project": {V, E}, "commercial": {V}, "quality": {V, E}, "plant": {V, E}, "assets": {V}},
    "quantity_surveyor": {"masters": {V, E}, "inventory": {V}, "procurement": {V}, "accounts": {V},
                          "equipment": {V}, "project": {V, E}, "commercial": {V, E}, "quality": {V},
                          "plant": {V}, "assets": {V}},
}


def can(user, module, action):
    return action in ROLES.get(user["role"], {}).get(module, set())


def require(user, module, action):
    if not can(user, module, action):
        raise ApiError("Your role (%s) cannot %s in %s." % (user["role"], action, module))


# ───────────────────────── db helpers ─────────────────────────
def connect():
    os.makedirs(DATA_DIR, exist_ok=True)
    c = sqlite3.connect(DB_PATH, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=OFF")
    try:
        c.execute("PRAGMA journal_mode=WAL")
    except sqlite3.OperationalError:  # e.g. network drive
        c.execute("PRAGMA journal_mode=DELETE")
    return c


def q(c, sql, p=()):
    return [dict(r) for r in c.execute(sql, p).fetchall()]


def q1(c, sql, p=()):
    r = c.execute(sql, p).fetchone()
    return dict(r) if r else None


def val(c, sql, p=(), default=0):
    r = c.execute(sql, p).fetchone()
    return default if (r is None or r[0] is None) else r[0]


def ins(c, table, d):
    keys = list(d.keys())
    cur = c.execute("INSERT INTO %s(%s) VALUES(%s)" % (table, ",".join(keys), ",".join("?" * len(keys))),
                    [d[k] for k in keys])
    return cur.lastrowid


def upd(c, table, rid, d):
    if not d:
        return
    keys = list(d.keys())
    c.execute("UPDATE %s SET %s WHERE id=?" % (table, ",".join(k + "=?" for k in keys)),
              [d[k] for k in keys] + [rid])


def get(c, table, rid, what="Record"):
    r = q1(c, "SELECT * FROM %s WHERE id=?" % table, (rid,))
    if not r:
        raise ApiError("%s not found." % what)
    return r


def setting(c, key):
    r = q1(c, "SELECT value FROM settings WHERE key=?", (key,))
    return r["value"] if r else DEFAULT_SETTINGS.get(key, "")


def fsetting(c, key):
    try:
        return float(setting(c, key) or 0)
    except ValueError:
        return 0.0


def audit(c, user, action, entity, eid=None, detail=None):
    ins(c, "audit", {"ts": now(), "user_id": user["id"] if user else None, "action": action,
                     "entity": entity, "entity_id": eid,
                     "detail": json.dumps(detail, default=str)[:4000] if detail is not None else None})


def num(x, name="value"):
    try:
        return float(x or 0)
    except (TypeError, ValueError):
        raise ApiError("%s must be a number." % name)


def need(d, *keys):
    for k in keys:
        if d.get(k) in (None, ""):
            raise ApiError("%s is required." % k.replace("_", " ").capitalize())


SCHEMA_PROJECT = """
CREATE TABLE IF NOT EXISTS wbs(id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL, code TEXT, name TEXT,
  parent_id INTEGER, weight REAL DEFAULT 0, sort INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS activities(id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL, wbs_id INTEGER, code TEXT,
  name TEXT, boq_item_id INTEGER, location TEXT, unit TEXT, planned_qty REAL DEFAULT 0, planned_start TEXT,
  planned_finish TEXT, baseline_start TEXT, baseline_finish TEXT, actual_start TEXT, actual_finish TEXT,
  weight REAL DEFAULT 0, responsible TEXT, predecessors TEXT, is_milestone INTEGER DEFAULT 0,
  critical INTEGER DEFAULT 0, std_labour_prod REAL DEFAULT 0, std_equip_prod REAL DEFAULT 0,
  test_required TEXT, delay_reason TEXT, actual_qty REAL DEFAULT 0);
CREATE TABLE IF NOT EXISTS trades(id INTEGER PRIMARY KEY, project_id INTEGER, code TEXT, name TEXT,
  rate_hour REAL DEFAULT 0, active INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS rate_analysis(id INTEGER PRIMARY KEY, boq_item_id INTEGER, kind TEXT, ref_id INTEGER,
  description TEXT, qty_per_unit REAL DEFAULT 0, rate REAL DEFAULT 0);
CREATE TABLE IF NOT EXISTS equipment_rates(id INTEGER PRIMARY KEY, equipment_id INTEGER, effective_from TEXT,
  ownership_hr REAL DEFAULT 0, fuel_hr REAL DEFAULT 0, operator_hr REAL DEFAULT 0, maintenance_hr REAL DEFAULT 0,
  insurance_hr REAL DEFAULT 0, overhead_pct REAL DEFAULT 0, remarks TEXT);
CREATE TABLE IF NOT EXISTS dpr(id INTEGER PRIMARY KEY, no TEXT, project_id INTEGER, date TEXT, shift TEXT DEFAULT 'day',
  weather TEXT, site_condition TEXT, status TEXT DEFAULT 'draft', remarks TEXT, version INTEGER DEFAULT 0,
  created_by INTEGER, submitted_by INTEGER, checked_by INTEGER, approved_by INTEGER, approved_at TEXT,
  UNIQUE(project_id, date, shift));
CREATE TABLE IF NOT EXISTS dpr_work(id INTEGER PRIMARY KEY, dpr_id INTEGER, activity_id INTEGER, boq_item_id INTEGER,
  location TEXT, planned_qty REAL DEFAULT 0, actual_qty REAL DEFAULT 0, remarks TEXT);
CREATE TABLE IF NOT EXISTS dpr_labour(id INTEGER PRIMARY KEY, dpr_id INTEGER, activity_id INTEGER, trade_id INTEGER,
  party_id INTEGER, count REAL DEFAULT 0, hours REAL DEFAULT 8, ot_hours REAL DEFAULT 0, rate REAL, amount REAL);
CREATE TABLE IF NOT EXISTS dpr_equipment(id INTEGER PRIMARY KEY, dpr_id INTEGER, activity_id INTEGER, equipment_id INTEGER,
  operator TEXT, meter_start REAL, meter_end REAL, hours REAL DEFAULT 0, idle_hours REAL DEFAULT 0,
  breakdown_hours REAL DEFAULT 0, rate REAL, amount REAL, logsheet_id INTEGER, created_log INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS dpr_delays(id INTEGER PRIMARY KEY, dpr_id INTEGER, activity_id INTEGER, category TEXT,
  hours REAL DEFAULT 0, description TEXT, create_event INTEGER DEFAULT 0, event_id INTEGER);
CREATE TABLE IF NOT EXISTS files(id INTEGER PRIMARY KEY, kind TEXT DEFAULT 'document', entity TEXT, entity_id INTEGER,
  project_id INTEGER, wbs_id INTEGER, activity_id INTEGER, boq_item_id INTEGER, dpr_id INTEGER, location TEXT,
  date TEXT, caption TEXT, stage TEXT, filename TEXT, stored TEXT, mime TEXT, size INTEGER, user_id INTEGER, ts TEXT);
CREATE INDEX IF NOT EXISTS ix_files_entity ON files(entity, entity_id);
CREATE TABLE IF NOT EXISTS comments(id INTEGER PRIMARY KEY, entity TEXT, entity_id INTEGER, user_id INTEGER, ts TEXT, text TEXT);
CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, no TEXT, project_id INTEGER, date TEXT, type TEXT DEFAULT 'delay',
  title TEXT, description TEXT, wbs_id INTEGER, activity_id INTEGER, dpr_id INTEGER, responsible_party TEXT,
  clause TEXT, notice_deadline TEXT, delay_days REAL DEFAULT 0, cost_impact REAL DEFAULT 0, mitigation TEXT,
  status TEXT DEFAULT 'open', created_by INTEGER);
CREATE TABLE IF NOT EXISTS variations(id INTEGER PRIMARY KEY, no TEXT, project_id INTEGER, boq_item_id INTEGER,
  new_code TEXT, new_description TEXT, new_unit TEXT, date TEXT, title TEXT, reason TEXT, instruction_ref TEXT,
  var_qty REAL DEFAULT 0, new_rate REAL, time_impact_days REAL DEFAULT 0, event_id INTEGER,
  status TEXT DEFAULT 'identified', approved_date TEXT, created_by INTEGER);
CREATE TABLE IF NOT EXISTS measurements(id INTEGER PRIMARY KEY, no TEXT, project_id INTEGER, date TEXT,
  status TEXT DEFAULT 'draft', remarks TEXT, verified_by INTEGER, created_by INTEGER);
CREATE TABLE IF NOT EXISTS measurement_lines(id INTEGER PRIMARY KEY, measurement_id INTEGER, boq_item_id INTEGER,
  qty REAL, location TEXT, remarks TEXT);
CREATE TABLE IF NOT EXISTS ipc(id INTEGER PRIMARY KEY, no TEXT, project_id INTEGER, client_id INTEGER, date TEXT,
  period_to TEXT, status TEXT DEFAULT 'draft', retention_pct REAL DEFAULT 0, tds_pct REAL DEFAULT 0,
  vat_rate REAL DEFAULT 0, advance_recovery REAL DEFAULT 0, other_deduction REAL DEFAULT 0, gross REAL DEFAULT 0,
  net REAL DEFAULT 0, invoice_id INTEGER, client_ref TEXT, remarks TEXT, created_by INTEGER, certified_by INTEGER);
CREATE TABLE IF NOT EXISTS ipc_lines(id INTEGER PRIMARY KEY, ipc_id INTEGER, boq_item_id INTEGER, prev_qty REAL DEFAULT 0,
  qty REAL DEFAULT 0, rate REAL DEFAULT 0, amount REAL DEFAULT 0);
CREATE TABLE IF NOT EXISTS qa_tests(id INTEGER PRIMARY KEY, no TEXT, project_id INTEGER, activity_id INTEGER,
  boq_item_id INTEGER, material_id INTEGER, dpr_id INTEGER, location TEXT, test_type TEXT, sample_ref TEXT,
  sampled_date TEXT, result_date TEXT, result_value TEXT, criteria TEXT, status TEXT DEFAULT 'pending',
  ncr_id INTEGER, remarks TEXT, created_by INTEGER);
CREATE TABLE IF NOT EXISTS ncrs(id INTEGER PRIMARY KEY, no TEXT, project_id INTEGER, date TEXT, title TEXT,
  description TEXT, activity_id INTEGER, test_id INTEGER, corrective_action TEXT, due_date TEXT,
  status TEXT DEFAULT 'open', closed_date TEXT, created_by INTEGER);
CREATE TABLE IF NOT EXISTS tasks(id INTEGER PRIMARY KEY, project_id INTEGER, title TEXT, description TEXT, due_date TEXT,
  priority TEXT DEFAULT 'normal', status TEXT DEFAULT 'open', assigned_to INTEGER, source_type TEXT, source_id INTEGER,
  created_by INTEGER, ts TEXT, done_at TEXT);
"""

EXTRA_COLUMNS = {
    "boq_items": {"wbs_id": "INTEGER", "location": "TEXT", "revised_qty": "REAL", "revised_rate": "REAL"},
    "voucher_lines": {"activity_id": "INTEGER", "wbs_id": "INTEGER"},
    "issue_lines": {"activity_id": "INTEGER"},
    "users": {"project_ids": "TEXT", "location": "TEXT", "phone": "TEXT", "email": "TEXT", "created": "TEXT"},
    "sessions": {"last_seen": "TEXT", "ip": "TEXT", "device": "TEXT"},
    # documents that can be written on a site copy and carried to head office
    "logsheets": {"dpr_id": "INTEGER", "activity_id": "INTEGER", "origin": "TEXT", "origin_id": "INTEGER",
                  # the monthly sheet this day belongs to, and everything the paper sheets carry
                  "book_id": "INTEGER", "time_start": "TEXT", "time_stop": "TEXT", "fuel_qty": "REAL",
                  "fuel_req_no": "TEXT", "standby_hours": "REAL", "down_reason": "TEXT", "cost_code": "TEXT",
                  "sign_store": "TEXT", "sign_operator": "TEXT", "sign_incharge": "TEXT", "sign_hirer": "TEXT",
                  "km_start": "REAL", "km_end": "REAL", "km_run": "REAL"},
    "dpr": {"origin": "TEXT", "origin_id": "INTEGER"},
    "issues": {"origin": "TEXT", "origin_id": "INTEGER"},
    # a machine may carry more than one meter (hour + kilometre, energy + hour, boom 1 + boom 2)
    "equipment": {"meters": "TEXT", "checklist_id": "INTEGER", "rating": "TEXT", "owner_name": "TEXT"},
}

# Fixed production plant (batching plant, crusher, quarry) and the asset register.
SCHEMA_PLANT = """
CREATE TABLE IF NOT EXISTS plants(id INTEGER PRIMARY KEY, code TEXT UNIQUE, name TEXT, kind TEXT DEFAULT 'batching',
  project_id INTEGER, location TEXT, capacity REAL DEFAULT 0, capacity_unit TEXT, output_material_id INTEGER,
  equipment_id INTEGER, power_kw REAL DEFAULT 0, operator TEXT, commissioned TEXT, notes TEXT,
  active INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS mix_designs(id INTEGER PRIMARY KEY, plant_id INTEGER, code TEXT, name TEXT,
  output_material_id INTEGER, output_qty REAL DEFAULT 1, unit TEXT, grade TEXT, approved_by TEXT,
  approved_date TEXT, remarks TEXT, active INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS mix_lines(id INTEGER PRIMARY KEY, mix_id INTEGER, material_id INTEGER,
  qty_per_unit REAL DEFAULT 0, wastage_pct REAL DEFAULT 0, remarks TEXT);
CREATE TABLE IF NOT EXISTS plant_runs(id INTEGER PRIMARY KEY, no TEXT, plant_id INTEGER, project_id INTEGER,
  date TEXT, shift TEXT DEFAULT 'day', mix_id INTEGER, store_id INTEGER, output_material_id INTEGER,
  output_qty REAL DEFAULT 0, rejected_qty REAL DEFAULT 0, run_hours REAL DEFAULT 0, down_hours REAL DEFAULT 0,
  down_reason TEXT, power_units REAL DEFAULT 0, diesel_qty REAL DEFAULT 0, labour_cost REAL DEFAULT 0,
  boq_item_id INTEGER, activity_id INTEGER, dpr_id INTEGER, material_cost REAL DEFAULT 0, other_cost REAL DEFAULT 0,
  total_cost REAL DEFAULT 0, unit_cost REAL DEFAULT 0, status TEXT DEFAULT 'draft', voucher_id INTEGER,
  issue_id INTEGER, remarks TEXT, operator TEXT, created_by INTEGER, approved_by INTEGER,
  UNIQUE(plant_id, date, shift, no));
CREATE TABLE IF NOT EXISTS plant_run_lines(id INTEGER PRIMARY KEY, run_id INTEGER, material_id INTEGER,
  planned_qty REAL DEFAULT 0, qty REAL DEFAULT 0, rate REAL DEFAULT 0, amount REAL DEFAULT 0);
CREATE TABLE IF NOT EXISTS plant_tests(id INTEGER PRIMARY KEY, run_id INTEGER, plant_id INTEGER, date TEXT,
  test_type TEXT, sample_ref TEXT, result_value TEXT, criteria TEXT, status TEXT DEFAULT 'pending', remarks TEXT);

CREATE TABLE IF NOT EXISTS assets(id INTEGER PRIMARY KEY, code TEXT UNIQUE, name TEXT, category TEXT,
  class TEXT DEFAULT 'furniture', project_id INTEGER, location TEXT, custodian TEXT, custodian_staff_id INTEGER,
  supplier_id INTEGER, invoice_no TEXT, purchase_date TEXT, purchase_value REAL DEFAULT 0,
  residual_value REAL DEFAULT 0, life_months INTEGER DEFAULT 60, dep_method TEXT DEFAULT 'slm',
  wdv_rate REAL DEFAULT 0, accumulated_dep REAL DEFAULT 0, book_value REAL DEFAULT 0, serial TEXT,
  warranty_expiry TEXT, insurance_policy TEXT, insurance_expiry TEXT, condition TEXT DEFAULT 'good',
  status TEXT DEFAULT 'in_use', disposal_date TEXT, disposal_value REAL DEFAULT 0, remarks TEXT,
  last_verified TEXT, active INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS asset_moves(id INTEGER PRIMARY KEY, asset_id INTEGER, date TEXT, kind TEXT,
  from_location TEXT, to_location TEXT, from_project INTEGER, to_project INTEGER, custodian TEXT,
  amount REAL DEFAULT 0, remarks TEXT, voucher_id INTEGER, user_id INTEGER, ts TEXT);
"""

# Teamwork: who is working where, what just happened, and offline exchange between two copies.
SCHEMA_TEAM = """
CREATE TABLE IF NOT EXISTS activity(id INTEGER PRIMARY KEY, ts TEXT, user_id INTEGER, user_name TEXT,
  location TEXT, project_id INTEGER, kind TEXT, title TEXT, detail TEXT, link TEXT, amount REAL);
CREATE INDEX IF NOT EXISTS ix_activity_ts ON activity(id DESC);
CREATE TABLE IF NOT EXISTS login_attempts(id INTEGER PRIMARY KEY, ts TEXT, username TEXT, ip TEXT, ok INTEGER);
CREATE INDEX IF NOT EXISTS ix_login_user ON login_attempts(username, id DESC);
CREATE TABLE IF NOT EXISTS site_packs(id INTEGER PRIMARY KEY, ts TEXT, direction TEXT, site_code TEXT,
  filename TEXT, project_id INTEGER, counts TEXT, note TEXT, user_id INTEGER);
CREATE TABLE IF NOT EXISTS import_map(origin TEXT, kind TEXT, origin_id INTEGER, local_id INTEGER,
  pack_id INTEGER, ts TEXT, PRIMARY KEY(origin, kind, origin_id));
"""

# The machine logsheet as sites actually keep it: one sheet per machine per month, with the
# daily lines, the daily check list, what was serviced and what oil went in - the same paper
# that owners, rental suppliers and the client all sign at the end of the month.
SCHEMA_LOG = """
CREATE TABLE IF NOT EXISTS logbooks(id INTEGER PRIMARY KEY, no TEXT, equipment_id INTEGER, project_id INTEGER,
  period TEXT, period_label TEXT, from_date TEXT, to_date TEXT, sheet_type TEXT DEFAULT 'owned',
  owner_party_id INTEGER, owner_name TEXT, hirer_party_id INTEGER, hirer_name TEXT,
  operator TEXT, operator2 TEXT, site TEXT, location TEXT, cost_code TEXT, meters TEXT,
  checklist_id INTEGER, rate REAL DEFAULT 0, rate_basis TEXT, payable_days REAL, payable_hours REAL,
  remarks TEXT, issues TEXT, status TEXT DEFAULT 'draft', prepared_by INTEGER, checked_by INTEGER,
  approved_by INTEGER, approved_on TEXT, created_by INTEGER, origin TEXT, origin_id INTEGER,
  UNIQUE(equipment_id, period, sheet_type));
CREATE INDEX IF NOT EXISTS ix_book_eq ON logbooks(equipment_id, period);
CREATE TABLE IF NOT EXISTS log_meters(id INTEGER PRIMARY KEY, log_id INTEGER, book_id INTEGER, code TEXT,
  r_start REAL DEFAULT 0, r_stop REAL DEFAULT 0, total REAL DEFAULT 0, UNIQUE(log_id, code));
CREATE INDEX IF NOT EXISTS ix_logmeter ON log_meters(book_id, code);
CREATE TABLE IF NOT EXISTS log_service(id INTEGER PRIMARY KEY, book_id INTEGER, equipment_id INTEGER, date TEXT,
  sn INTEGER, description TEXT, part_no TEXT, qty REAL DEFAULT 0, unit TEXT, brand TEXT, material_id INTEGER,
  issue_id INTEGER, wo_id INTEGER, at_hour REAL DEFAULT 0, at_km REAL DEFAULT 0, remarks TEXT);
CREATE INDEX IF NOT EXISTS ix_logservice ON log_service(book_id);
CREATE TABLE IF NOT EXISTS log_fluids(id INTEGER PRIMARY KEY, book_id INTEGER, equipment_id INTEGER, date TEXT,
  engine_oil REAL DEFAULT 0, gear_oil REAL DEFAULT 0, brake_oil REAL DEFAULT 0, hydraulic_oil REAL DEFAULT 0,
  transmission_oil REAL DEFAULT 0, crown_oil REAL DEFAULT 0, grease REAL DEFAULT 0, coolant REAL DEFAULT 0,
  other_name TEXT, other_qty REAL DEFAULT 0, remarks TEXT);
CREATE INDEX IF NOT EXISTS ix_logfluid ON log_fluids(book_id);
CREATE TABLE IF NOT EXISTS check_lists(id INTEGER PRIMARY KEY, code TEXT UNIQUE, name TEXT, category TEXT,
  items TEXT, active INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS log_checks(id INTEGER PRIMARY KEY, book_id INTEGER, equipment_id INTEGER, date TEXT,
  item TEXT, result TEXT DEFAULT 'ok', remarks TEXT, checked_by TEXT, UNIQUE(book_id, date, item));
CREATE INDEX IF NOT EXISTS ix_logcheck ON log_checks(book_id, date);
"""


def ensure_columns(c):
    for table, cols in EXTRA_COLUMNS.items():
        have = {r[1] for r in c.execute("PRAGMA table_info(%s)" % table)}
        for col, typ in cols.items():
            if col not in have:
                c.execute("ALTER TABLE %s ADD COLUMN %s %s" % (table, col, typ))


def init_db():
    with LOCK:
        c = connect()
        c.executescript(SCHEMA)
        c.executescript(SCHEMA_PROJECT)
        c.executescript(SCHEMA_TEAM)
        c.executescript(SCHEMA_PLANT)
        c.executescript(SCHEMA_LOG)
        # BuildCore 1.7+ modules (fixed assets, rates, schedule and control); each one is optional
        for _m in ("api_fa", "api_ra", "api_sched", "api_res", "api_cash", "api_life", "api_adv", "api_books", "api_corp", "api_ai", "api_copilot", "api_site", "api_license", "api_decide", "api_safety", "api_field", "api_hire", "api_cadmin", "api_grnimp", "api_insight", "api_procure", "api_workspace", "api_exec", "api_mgmt", "api_costlink", "api_udpr", "api_fc", "api_cfw", "api_ctc", "api_fcc", "api_logfix", "api_rgen", "api_logbs", "api_eqsum", "api_doclib", "api_claims", "api_dprmeter", "api_pwreset", "api_speed", "api_one", "api_pfp", "api_money", "api_papers", "api_fcfix", "api_prices", "api_access"):
            try:
                _mod = __import__(_m)
                getattr(_mod, "init_" + _m[4:])(c)
            except Exception as _e:  # never stop BuildCore from starting
                print("BuildCore: module %s not loaded: %s" % (_m, _e))
        ensure_columns(c)
        for k, v in DEFAULT_SETTINGS.items():
            c.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", (k, v))
        if not val(c, "SELECT COUNT(*) FROM account_groups"):
            seed_accounts(c)
        if not val(c, "SELECT COUNT(*) FROM check_lists"):
            seed_checklists(c)
        c.commit()
        c.close()


# The daily "before starting the engine, check the following" lists the sample sheets print
# across the top of the month. A site can add its own; these four cover most yards.
DEFAULT_CHECKLISTS = [
    ("CL-VEH", "Vehicle - daily check", "vehicle",
     "Engine oil\nCooling water\nBrake oil / system\nGear oil / crown oil\nTransmission oil\n"
     "U-bolt and centre bolt\nLeaf spring patta\nTyre and wheel nuts\nHorn / lighting / indicator\n"
     "Battery and switches\nLeaking pipe or hose\nChassis and others"),
    ("CL-TRK", "Tracked machine - daily check", "tracked",
     "Engine oil\nCooling water\nHydraulic oil\nHydraulic pipe\nGear oil / final drive\nTrack roller\n"
     "Track pin and bush\nTrack tension\nGrease points\nBattery and switches\nHorn / lighting / beacon\n"
     "Leaking pipe or hose\nBucket teeth and cutting edge"),
    ("CL-HST", "Hoist / lift - daily check", "hoist",
     "Engine oil\nHydraulic oil\nHydraulic pipe\nRoller and guide\nLever and cable\nBattery and switches\n"
     "Limit switch and brake\nSafety gate and railing\nRope and sling\nOther items"),
    ("CL-GEN", "Generator / pump - daily check", "genset",
     "Engine oil\nCooling water\nFuel level and filter\nBattery and charger\nBelt tension\n"
     "Exhaust and silencer\nEarthing\nPanel meters and lamps\nLeaking pipe or hose\nGuard and enclosure"),
]


def seed_checklists(c):
    for code, name, cat, items in DEFAULT_CHECKLISTS:
        ins(c, "check_lists", {"code": code, "name": name, "category": cat, "items": items, "active": 1})


def seed_accounts(c):
    ids = {}
    for code, name, typ, parent in DEFAULT_GROUPS:
        ids[code] = ins(c, "account_groups", {"code": code, "name": name, "type": typ,
                                              "parent_id": ids.get(parent)})
    for code, name, typ, grp, role in DEFAULT_ACCOUNTS:
        if not q1(c, "SELECT id FROM accounts WHERE code=?", (code,)):
            ins(c, "accounts", {"code": code, "name": name, "type": typ, "group_id": ids[grp],
                                "role": role, "opening_balance": 0, "active": 1})
    for sec, desc, rate, thr in DEFAULT_TDS:
        ins(c, "tds_rates", {"section": sec, "description": desc, "rate": rate, "threshold": thr, "active": 1})


# ───────────────────────── auth ─────────────────────────
def hash_pw(pw, salt=None):
    salt = salt or secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 120000).hex()
    return h, salt


def user_from_token(c, token):
    if not token:
        return None
    row = q1(c, "SELECT u.*, s.created AS s_created, s.last_seen AS s_last_seen FROM sessions s "
                "JOIN users u ON u.id=s.user_id WHERE s.token=? AND u.active=1", (token,))
    if not row:
        return None
    try:
        days = int(float(setting(c, "session_days") or 30))
    except ValueError:
        days = 30
    if days > 0:
        seen = row["s_last_seen"] or row["s_created"] or now()
        if seen < (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds"):
            c.execute("DELETE FROM sessions WHERE token=?", (token,))
            return None
    return row


# Presence: a sign-in is "working now" if it was seen in the last few minutes.
ONLINE_MINUTES = 6
_touched = {}


def touch_session(c, token, ip=None, device=None):
    """Record that this sign-in is alive, at most once a minute so it costs nothing."""
    if not token:
        return
    import time
    last = _touched.get(token, 0)
    if time.time() - last < 60:
        return
    _touched[token] = time.time()
    c.execute("UPDATE sessions SET last_seen=?, ip=COALESCE(?,ip), device=COALESCE(?,device) WHERE token=?",
              (now(), ip, device, token))


def client_class(ip):
    """loopback | private | vpn | public - decides who may reach this server."""
    ip = (ip or "").strip()
    if ip.startswith("::ffff:"):
        ip = ip[7:]
    if ip in ("", "::1") or ip.startswith("127."):
        return "loopback"
    if ip.startswith("fe80:") or ip.startswith("fd") or ip.startswith("fc"):
        return "private"
    parts = ip.split(".")
    if len(parts) != 4 or not all(p.isdigit() for p in parts):
        return "public"
    a, b = int(parts[0]), int(parts[1])
    if a == 10 or a == 127 or (a == 172 and 16 <= b <= 31) or (a == 192 and b == 168) or (a == 169 and b == 254):
        return "private"
    if a == 100 and 64 <= b <= 127:
        return "vpn"        # Tailscale / carrier-grade NAT range used by mesh VPNs
    if a == 25:
        return "vpn"        # Hamachi
    return "public"


# ───────────────────── periods & numbering ─────────────────────
def period_for(c, d):
    return q1(c, "SELECT * FROM fiscal_periods WHERE start_date<=? AND end_date>=? ORDER BY id LIMIT 1", (d, d))


def assert_open(c, user, d):
    if not d:
        raise ApiError("Date is required.")
    p = period_for(c, d)
    if not p or p["status"] == "open":
        return
    if p["status"] == "soft_closed" and user and user["role"] == "admin":
        return
    raise ApiError("Period %s is %s. Entries dated %s are not allowed." %
                   (p["code"], p["status"].replace("_", "-"), d))


def fy_of(c, d):
    p = period_for(c, d)
    if p:
        return p["fy"]
    y = int(d[:4])
    # Fallback: fiscal year starting mid-July (label in AD years)
    if d[5:] < "07-16":
        y -= 1
    return "%d-%s" % (y, str(y + 1)[-2:])


def next_no(c, doc_type, d):
    fy = fy_of(c, d)
    r = q1(c, "SELECT next FROM sequences WHERE doc_type=? AND fy=?", (doc_type, fy))
    n = r["next"] if r else 1
    if r:
        c.execute("UPDATE sequences SET next=? WHERE doc_type=? AND fy=?", (n + 1, doc_type, fy))
    else:
        c.execute("INSERT INTO sequences(doc_type,fy,next) VALUES(?,?,?)", (doc_type, fy, 2))
    return "%s/%s/%04d" % (doc_type, fy, n)


# ───────────────────────── posting engine ─────────────────────────
VOUCHER_PREFIX = {"journal": "JV", "payment": "PV", "receipt": "RV", "contra": "CV",
                  "purchase": "PUR", "sales": "SAL", "debit_note": "DN", "credit_note": "CN"}


def role_account(c, role):
    r = q1(c, "SELECT id FROM accounts WHERE role=? AND active=1 ORDER BY id LIMIT 1", (role,))
    if not r:
        raise ApiError("No active account is set for role '%s'. Open Accounts > Chart of accounts "
                       "and assign this role to an account." % role)
    return r["id"]


def inventory_role(material):
    cat = (material.get("category") or "").lower()
    if "fuel" in cat or "lubric" in cat or "oil" in cat:
        return "inventory_fuel"
    if "spare" in cat:
        return "inventory_spares"
    return "inventory"


def consumption_role(material, target):
    r = inventory_role(material)
    if r == "inventory_fuel":
        return "fuel_cost"
    if r == "inventory_spares":
        return "repair_cost"
    if target == "overhead":
        return "overhead"
    return "material_cost"


def post_voucher(c, user, vtype, d, narration, lines, project_id=None, source="manual",
                 source_id=None, party_id=None, ref_no=None, status="posted"):
    """lines: dicts with account_id or role, debit, credit, and optional dimensions."""
    assert_open(c, user, d)
    clean = []
    for ln in lines:
        dr, cr = r2(ln.get("debit")), r2(ln.get("credit"))
        if dr < 0:  # a negative debit is a credit
            cr, dr = r2(cr - dr), 0.0
        if cr < 0:
            dr, cr = r2(dr - cr), 0.0
        if dr > 0 and cr > 0:  # net a line that carries both sides
            dr, cr = (r2(dr - cr), 0.0) if dr >= cr else (0.0, r2(cr - dr))
        if abs(dr) < 0.005 and abs(cr) < 0.005:
            continue
        acc = ln.get("account_id") or role_account(c, ln["role"])
        a = q1(c, "SELECT id, active FROM accounts WHERE id=?", (acc,))
        if not a:
            raise ApiError("Account %s does not exist." % acc)
        if not a["active"]:
            raise ApiError("Account %s is inactive." % acc)
        clean.append({"account_id": acc, "debit": dr, "credit": cr, "narration": ln.get("narration"),
                      "project_id": ln.get("project_id", project_id), "boq_item_id": ln.get("boq_item_id"),
                      "equipment_id": ln.get("equipment_id"), "party_id": ln.get("party_id"),
                      "activity_id": ln.get("activity_id"), "wbs_id": ln.get("wbs_id")})
    if len(clean) < 2:
        return None
    td = r2(sum(x["debit"] for x in clean))
    tc = r2(sum(x["credit"] for x in clean))
    if abs(td - tc) > 0.011:
        raise ApiError("Voucher is not balanced: debit %.2f, credit %.2f." % (td, tc))
    if abs(td - tc) > 0.0001:  # push rounding cent to the largest line
        big = max(clean, key=lambda x: x["debit"] + x["credit"])
        if big["debit"]:
            big["debit"] = r2(big["debit"] - (td - tc))
        else:
            big["credit"] = r2(big["credit"] + (td - tc))
    vno = next_no(c, VOUCHER_PREFIX.get(vtype, "JV"), d)
    vid = ins(c, "vouchers", {"no": vno, "type": vtype, "date": d, "project_id": project_id,
                              "narration": narration, "status": status, "source": source,
                              "source_id": source_id, "party_id": party_id, "ref_no": ref_no,
                              "total": td, "created_by": user["id"] if user else None,
                              "approved_by": user["id"] if (user and status == "posted") else None,
                              "ts": now()})
    for x in clean:
        x["voucher_id"] = vid
        ins(c, "voucher_lines", x)
    return vid


def reverse_voucher(c, user, vid, d=None, reason=""):
    if not vid:
        return None
    v = get(c, "vouchers", vid, "Voucher")
    if v["status"] == "reversed":
        return None
    if v["status"] in ("draft", "submitted"):
        c.execute("DELETE FROM voucher_lines WHERE voucher_id=?", (vid,))
        c.execute("DELETE FROM vouchers WHERE id=?", (vid,))
        return None
    d = d or v["date"]
    p = period_for(c, d)
    if p and p["status"] != "open":
        d = today()
    lines = q(c, "SELECT * FROM voucher_lines WHERE voucher_id=?", (vid,))
    rl = [{"account_id": l["account_id"], "debit": l["credit"], "credit": l["debit"],
           "narration": "Reversal", "project_id": l["project_id"], "boq_item_id": l["boq_item_id"],
           "equipment_id": l["equipment_id"], "party_id": l["party_id"], "activity_id": l.get("activity_id"),
           "wbs_id": l.get("wbs_id")} for l in lines]
    rid = post_voucher(c, user, v["type"], d, "Reversal of %s. %s" % (v["no"], reason), rl,
                       project_id=v["project_id"], source="reversal", source_id=vid, party_id=v["party_id"])
    upd(c, "vouchers", vid, {"status": "reversed"})
    if rid:
        upd(c, "vouchers", rid, {"reversal_of": vid})
    return rid


# ───────────────────────── stock engine ─────────────────────────
def balance(c, project_id, store_id, material_id):
    r = q1(c, "SELECT qty, value FROM stock_balances WHERE project_id=? AND store_id=? AND material_id=?",
           (project_id, store_id, material_id))
    return (r["qty"], r["value"]) if r else (0.0, 0.0)


def _set_balance(c, project_id, store_id, material_id, qty, value, d):
    c.execute("INSERT INTO stock_balances(project_id,store_id,material_id,qty,value,last_date) "
              "VALUES(?,?,?,?,?,?) ON CONFLICT(project_id,store_id,material_id) DO UPDATE SET "
              "qty=excluded.qty, value=excluded.value, last_date=excluded.last_date",
              (project_id, store_id, material_id, r4(qty), r2(value), d))


def check_store(c, store_id, project_id):
    s = get(c, "stores", store_id, "Store")
    if s["project_id"] != project_id:
        raise ApiError("Store %s does not belong to the selected project." % s["name"])
    return s


def stock_in(c, user, project_id, store_id, material_id, qty, rate, d, doc_type, doc_id, doc_no, batch=None):
    qty = num(qty)
    if qty <= EPS:
        return 0.0
    rate = num(rate)
    value = r2(qty * rate)
    bq, bv = balance(c, project_id, store_id, material_id)
    _set_balance(c, project_id, store_id, material_id, bq + qty, bv + value, d)
    ins(c, "stock_ledger", {"date": d, "project_id": project_id, "store_id": store_id,
                            "material_id": material_id, "doc_type": doc_type, "doc_id": doc_id,
                            "doc_no": doc_no, "qty_in": qty, "rate": r4(rate), "value_in": value,
                            "batch_no": batch, "created_by": user["id"] if user else None, "ts": now()})
    return value


def stock_out(c, user, project_id, store_id, material_id, qty, d, doc_type, doc_id, doc_no, rate=None):
    """Removes stock at moving weighted average. Returns (rate, value)."""
    qty = num(qty)
    if qty <= EPS:
        return 0.0, 0.0
    bq, bv = balance(c, project_id, store_id, material_id)
    if bq + EPS < qty and setting(c, "allow_negative_stock") != "1":
        m = q1(c, "SELECT code, name, unit FROM materials WHERE id=?", (material_id,)) or {}
        s = q1(c, "SELECT name FROM stores WHERE id=?", (store_id,)) or {}
        raise ApiError("Not enough stock of %s %s in %s: available %s %s, requested %s." %
                       (m.get("code", ""), m.get("name", ""), s.get("name", "store"),
                        round(bq, 3), m.get("unit", ""), round(qty, 3)))
    if rate is None:
        if bq > EPS:
            rate = bv / bq
        else:
            rate = val(c, "SELECT standard_rate FROM materials WHERE id=?", (material_id,))
    value = r2(qty * rate)
    if abs(bq - qty) <= EPS:
        value = r2(bv)  # clear rounding residue when the bucket empties
    _set_balance(c, project_id, store_id, material_id, bq - qty, bv - value, d)
    ins(c, "stock_ledger", {"date": d, "project_id": project_id, "store_id": store_id,
                            "material_id": material_id, "doc_type": doc_type, "doc_id": doc_id,
                            "doc_no": doc_no, "qty_out": qty, "rate": r4(rate), "value_out": value,
                            "created_by": user["id"] if user else None, "ts": now()})
    return rate, value


def material(c, mid):
    return get(c, "materials", mid, "Material")


def ensure_project_stores(c, project_id):
    if not q1(c, "SELECT id FROM stores WHERE project_id=? AND type='main'", (project_id,)):
        ins(c, "stores", {"project_id": project_id, "code": "MS", "name": "Main Store", "type": "main", "active": 1})
    if not q1(c, "SELECT id FROM stores WHERE project_id=? AND type='transit'", (project_id,)):
        ins(c, "stores", {"project_id": project_id, "code": "TR", "name": "In Transit", "type": "transit",
                          "active": 1})


def transit_store(c, project_id):
    ensure_project_stores(c, project_id)
    return val(c, "SELECT id FROM stores WHERE project_id=? AND type='transit'", (project_id,))


def month_end(month):
    y, m = int(month[:4]), int(month[5:7])
    nxt = date(y + (m == 12), (m % 12) + 1, 1)
    return (nxt - timedelta(days=1)).isoformat()


def backup_now(tag="auto"):
    os.makedirs(BACKUP_DIR, exist_ok=True)
    name = "buildcore_%s_%s.db" % (tag, datetime.now().strftime("%Y%m%d_%H%M%S"))
    path = os.path.join(BACKUP_DIR, name)
    with LOCK:
        src = connect()
        dst = sqlite3.connect(path)
        src.backup(dst)
        dst.close()
        src.close()
    files = sorted(f for f in os.listdir(BACKUP_DIR) if f.startswith("buildcore_auto_"))
    for f in files[:-30]:
        try:
            os.remove(os.path.join(BACKUP_DIR, f))
        except OSError:
            pass
    return path
