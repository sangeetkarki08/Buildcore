"""
Fixed assets & equipment accounting (BuildCore 1.7).

One capital register over the machines in the Equipment register and the items in the Asset
register, with everything the accounts need that the operational modules do not do:

  * NAS 16 policy per item: method (SL / WDV / sum-of-years / hour meter), life, residual,
    components, lifecycle stage (ISO 55000) and the JV partner that owns it
  * monthly book depreciation, hour-meter depreciation read from the approved logsheets
  * Nepal Income Tax Schedule 2 pools (A-E) with the full / 2/3 / 1/3 rule, the 7% repairs cap,
    balancing charge and terminal loss, and NAS 12 deferred tax on the difference
  * the equipment cost ledger and hourly owning & operating rate (Peterson / Hinze),
    monthly charge of machine hours to projects and the year-end over/under-recovery true-up
  * Wang's ABC classification with maintenance level, fund share, spares and inspection cycle
  * NFRS 16 lease schedules for machines hired for more than 12 months
  * NAS 36 impairment review (idle-days indicator) and disposal with gain or loss
  * NAS 2 inventory analysis: FIFO / weighted average check, ABC-VED, EOQ, reorder point, NRV

The arithmetic is in fa_calc.py. This file keeps the records and posts the vouchers.
"""
import json
from datetime import date, timedelta

from core import (ApiError, EPS, audit, get, ins, month_end, need, now, num, q, q1, r2, today, upd, val)
from api_inventory import api as _register

_READY = set()


def api(name, module, perm):
    """Register an endpoint, making sure this module's tables exist in the open database first
    (so the screens work even if start-up could not create them)."""
    def wrap(f):
        def run(c, u, a):
            try:
                key = c.execute("PRAGMA database_list").fetchone()[2] or id(c)
            except Exception:
                key = id(c)
            if key not in _READY:
                if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='fa_lease_rows'").fetchone() :
                    init_fa(c)
                _READY.add(key)
            return f(c, u, a)
        run.__name__, run.__doc__ = f.__name__, f.__doc__
        _register(name, module, perm)(run)
        return f
    return wrap

def _find(name):
    """The posting engine and period lock live in core.py in current BuildCore; older layouts kept
    them in an accounts module. Look them up when first used so the app always starts."""
    import importlib
    for mod in ("core", "api_accounts", "api_finance", "accounts", "api_vouchers", "api_acc"):
        try:
            m = importlib.import_module(mod)
        except Exception:
            continue
        if hasattr(m, name):
            return getattr(m, name)
    raise ApiError("This BuildCore has no %s(); posting from the fixed-asset module is not possible." % name)


def post_voucher(c, u, head, lines):
    return _find("post_voucher")(c, u, head, lines)


def assert_open(c, u, d):
    return _find("assert_open")(c, u, d)

import fa_calc as F

MODULE = "assets"

SCHEMA_FA = """
CREATE TABLE IF NOT EXISTS fa_register(id INTEGER PRIMARY KEY, kind TEXT, ref_id INTEGER, code TEXT, name TEXT,
  klass TEXT, method TEXT DEFAULT 'SL', life_years REAL DEFAULT 0, life_hours REAL DEFAULT 0, residual REAL DEFAULT 0,
  wdv_rate REAL, cost REAL DEFAULT 0, in_use_date TEXT, project_id INTEGER, tax_pool TEXT, owner_entity TEXT,
  owner_share REAL DEFAULT 100, lifecycle TEXT DEFAULT 'operate', abc_class TEXT, abc_score INTEGER,
  s_workload INTEGER DEFAULT 1, s_impact_other INTEGER DEFAULT 1, s_impact_production INTEGER DEFAULT 1,
  s_repair_ease INTEGER DEFAULT 1, s_price INTEGER DEFAULT 1, idle_threshold INTEGER DEFAULT 90,
  managed INTEGER DEFAULT 1, accumulated REAL DEFAULT 0, impairment REAL DEFAULT 0, hour_reading REAL DEFAULT 0,
  last_service_hour REAL DEFAULT 0, last_inspection TEXT, status TEXT DEFAULT 'active', disposal_date TEXT,
  disposal_proceeds REAL DEFAULT 0, remarks TEXT, created TEXT, UNIQUE(kind, ref_id));
CREATE TABLE IF NOT EXISTS fa_components(id INTEGER PRIMARY KEY, fa_id INTEGER, name TEXT, cost REAL DEFAULT 0,
  method TEXT DEFAULT 'SL', life_years REAL DEFAULT 0, life_hours REAL DEFAULT 0, residual REAL DEFAULT 0,
  accumulated REAL DEFAULT 0, in_use_date TEXT, status TEXT DEFAULT 'active', replaced_on TEXT, remarks TEXT);
CREATE INDEX IF NOT EXISTS ix_facomp ON fa_components(fa_id);
CREATE TABLE IF NOT EXISTS fa_dep(id INTEGER PRIMARY KEY, fa_id INTEGER, comp_id INTEGER DEFAULT 0, month TEXT,
  method TEXT, hours REAL DEFAULT 0, amount REAL DEFAULT 0, project_id INTEGER, voucher_id INTEGER, ts TEXT,
  UNIQUE(fa_id, comp_id, month));
CREATE TABLE IF NOT EXISTS fa_costs(id INTEGER PRIMARY KEY, fa_id INTEGER, date TEXT, category TEXT,
  amount REAL DEFAULT 0, project_id INTEGER, ref TEXT, voucher_id INTEGER, remarks TEXT, user_id INTEGER, ts TEXT);
CREATE INDEX IF NOT EXISTS ix_facost ON fa_costs(fa_id, date);
CREATE TABLE IF NOT EXISTS fa_rates(id INTEGER PRIMARY KEY, fa_id INTEGER, fy TEXT, effective_from TEXT,
  annual_hours REAL, params TEXT, rate_hour REAL DEFAULT 0, dry_rate_hour REAL DEFAULT 0, ts TEXT);
CREATE TABLE IF NOT EXISTS fa_alloc(id INTEGER PRIMARY KEY, fa_id INTEGER, month TEXT, project_id INTEGER,
  kind TEXT DEFAULT 'charge', hours REAL DEFAULT 0, rate REAL DEFAULT 0, amount REAL DEFAULT 0, fy TEXT,
  voucher_id INTEGER, ts TEXT);
CREATE INDEX IF NOT EXISTS ix_faalloc ON fa_alloc(fa_id, month);
CREATE TABLE IF NOT EXISTS fa_tax(id INTEGER PRIMARY KEY, fy TEXT, pool TEXT, opening REAL DEFAULT 0,
  working TEXT, closing REAL DEFAULT 0, locked INTEGER DEFAULT 0, ts TEXT, UNIQUE(fy, pool));
CREATE TABLE IF NOT EXISTS fa_deferred(id INTEGER PRIMARY KEY, fy TEXT UNIQUE, carrying REAL, tax_base REAL,
  rate REAL, balance REAL, movement REAL, voucher_id INTEGER, ts TEXT);
CREATE TABLE IF NOT EXISTS fa_leases(id INTEGER PRIMARY KEY, no TEXT, fa_id INTEGER, equipment_id INTEGER,
  description TEXT, lessor TEXT, party_id INTEGER, project_id INTEGER, start_date TEXT, term_months INTEGER,
  payment REAL, periods_per_year INTEGER DEFAULT 12, rate REAL, in_advance INTEGER DEFAULT 0,
  direct_costs REAL DEFAULT 0, low_value INTEGER DEFAULT 0, exempt INTEGER DEFAULT 0, rou REAL DEFAULT 0,
  liability REAL DEFAULT 0, status TEXT DEFAULT 'draft', voucher_id INTEGER, remarks TEXT);
CREATE TABLE IF NOT EXISTS fa_lease_rows(id INTEGER PRIMARY KEY, lease_id INTEGER, period INTEGER, date TEXT,
  opening REAL, interest REAL, payment REAL, closing REAL, rou_dep REAL, voucher_id INTEGER);
CREATE TABLE IF NOT EXISTS fa_impair(id INTEGER PRIMARY KEY, fa_id INTEGER, date TEXT, idle_days INTEGER,
  indicators TEXT, carrying REAL, fvlcs REAL, viu REAL, recoverable REAL, loss REAL DEFAULT 0,
  voucher_id INTEGER, user_id INTEGER, remarks TEXT);
CREATE TABLE IF NOT EXISTS fa_maint(id INTEGER PRIMARY KEY, fa_id INTEGER, date TEXT, kind TEXT, at_hour REAL,
  cost REAL DEFAULT 0, capitalise INTEGER DEFAULT 0, comp_id INTEGER, remarks TEXT, user_id INTEGER);
CREATE TABLE IF NOT EXISTS inv_policy(material_id INTEGER PRIMARY KEY, ved TEXT DEFAULT 'E', lead_days REAL DEFAULT 7,
  max_lead_days REAL, order_cost REAL DEFAULT 0, carrying_pct REAL DEFAULT 0.2, safety REAL, nrv_rate REAL,
  allowed_waste_pct REAL DEFAULT 0.02, remarks TEXT);
"""

# Ledger roles this module posts to. Existing roles are used where BuildCore already has them;
# anything missing is created once under a group of the right type.
ROLES = {
    "fixed_asset": ("1510", "Property, plant and equipment - cost", "asset"),
    "accum_dep": ("1590", "Accumulated depreciation", "asset"),
    "depreciation": ("6810", "Depreciation", "expense"),
    "accum_impairment": ("1595", "Accumulated impairment losses", "asset"),
    "impairment_loss": ("6820", "Impairment loss on PPE (NAS 36)", "expense"),
    "disposal_gain": ("4910", "Gain on disposal of PPE", "income"),
    "disposal_loss": ("6830", "Loss on disposal of PPE", "expense"),
    "equip_job_cost": ("5410", "Equipment cost charged to projects", "expense"),
    "equip_recovery": ("5490", "Equipment cost recovered (contra)", "expense"),
    "rou_asset": ("1610", "Right-of-use assets (NFRS 16)", "asset"),
    "rou_accum": ("1690", "Accumulated depreciation - right-of-use", "asset"),
    "lease_liability": ("2610", "Lease liabilities (NFRS 16)", "liability"),
    "lease_interest": ("6910", "Interest on lease liabilities", "expense"),
    "dtl": ("2710", "Deferred tax liability (NAS 12)", "liability"),
    "deferred_tax_exp": ("7110", "Deferred tax expense / (income)", "expense"),
    "inv_nrv": ("1395", "Inventory write-down to NRV (NAS 2)", "asset"),
    "inv_writedown_exp": ("6840", "Inventory write-down expense", "expense"),
}

COST_CATEGORIES = [
    ("rent_lease", "Rent and lease"), ("depreciation", "Depreciation"),
    ("repairs", "Repairs and maintenance"), ("fuel_lube", "Fuel and lubrication"),
    ("tax_insurance", "Taxes, licences, insurance"), ("operator", "Operator wages"),
    ("tyres_parts", "Tyres and wear parts"), ("transport", "Mobilisation and transport"), ("other", "Other"),
]

# Annual vehicle tax on construction machinery (Bagmati/Gandaki schedules; check your province)
VEHICLE_TAX = {"heavy_earth": 17500, "crane_lift": 17500, "compaction": 17500, "haulage": 12500,
               "light_vehicle": 6500}


# ───────────────────────── setup ─────────────────────────
def init_fa(c):
    """Call once from core.init_db() after the other schemas."""
    c.executescript(SCHEMA_FA)


def _cols(c, table):
    try:
        return {r[1] for r in c.execute("PRAGMA table_info(%s)" % table).fetchall()}
    except Exception:
        return set()


def _has(c, table):
    return bool(c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone())


def _real_type(c, typ):
    """Use the spelling of account types this BuildCore already uses (asset / Asset / assets ...)."""
    keys = {"asset": ("ass",), "liability": ("lia",), "income": ("inc", "rev"), "expense": ("exp",)}[typ]
    for t in [r[0] for r in c.execute("SELECT DISTINCT type FROM accounts UNION SELECT DISTINCT type FROM account_groups")]:
        if t and str(t).lower().startswith(keys):
            return t
    return typ


def ensure_roles(c, roles):
    for role in roles:
        if val(c, "SELECT id FROM accounts WHERE role=?", (role,), None):
            continue
        code, name, typ = ROLES[role]
        typ = _real_type(c, typ)
        gid = val(c, "SELECT id FROM account_groups WHERE type=? ORDER BY id", (typ,), None)
        while val(c, "SELECT id FROM accounts WHERE code=?", (code,), None):
            code = str(int(code) + 1)
        ins(c, "accounts", {"code": code, "name": name, "type": typ, "group_id": gid, "role": role, "active": 1})


def _post(c, u, head, lines):
    lines = [x for x in lines if (x.get("debit") or 0) > EPS or (x.get("credit") or 0) > EPS]
    if not lines:
        return None
    ensure_roles(c, {x["role"] for x in lines if x["role"] in ROLES})
    return post_voucher(c, u, head, lines)


def _row(r):
    return dict(r) if r is not None else None


def _fa(c, fid):
    return get(c, "fa_register", int(fid), "Register item")


def _setting(c, key, default=None):
    v = val(c, "SELECT value FROM settings WHERE key=?", (key,), None)
    return default if v is None else v


def fy_bounds(c, fy=None, on=None):
    """Income year from fiscal_periods (Shrawan-Ashad). Falls back to 16 Jul - 15 Jul."""
    on = on or today()
    if fy:
        r = q1(c, "SELECT fy, MIN(start_date) s, MAX(end_date) e FROM fiscal_periods WHERE fy=? GROUP BY fy", (fy,))
    else:
        r = q1(c, "SELECT fy, MIN(start_date) s, MAX(end_date) e FROM fiscal_periods GROUP BY fy "
                  "HAVING MIN(start_date)<=? AND MAX(end_date)>=?", (on, on))
    if r and r["s"]:
        return r["fy"], r["s"], r["e"]
    if fy and fy[:4].isdigit():
        y = int(fy[:4]) - 57
        return fy, "%d-07-16" % y, "%d-07-15" % (y + 1)
    d = date.fromisoformat(on[:10])
    y = d.year if (d.month, d.day) >= (7, 16) else d.year - 1
    # label the year the way fiscal_periods does: Bikram Sambat, Shrawan 2083 starts mid-July 2026
    return fy or "%d/%02d" % (y + 57, (y + 58) % 100), "%d-07-16" % y, "%d-07-15" % (y + 1)


# ───────────────────────── the register ─────────────────────────
@api("fa.policy", MODULE, "view")
def fa_policy(c, u, a):
    return {"classes": [[k] + list(v) for k, v in F.CLASS_POLICY.items()], "methods": list(F.METHODS.items()),
            "pools": [[k, v[0], v[1]] for k, v in F.TAX_POOLS.items()], "abc": F.ABC_POLICY,
            "criteria": F.ABC_CRITERIA, "lifecycle": F.LIFECYCLE, "cost_categories": COST_CATEGORIES,
            "components": {k: v for k, v in F.COMPONENT_TEMPLATES.items()}, "ved": F.VED}


def _guess_class(cat):
    s = (cat or "").lower()
    for words, k in ((("excav", "dozer", "loader", "backhoe", "tracked", "grader"), "heavy_earth"),
                     (("tipper", "truck", "dumper", "transit", "tanker"), "haulage"),
                     (("crane", "hoist", "lift"), "crane_lift"), (("batch", "mixer", "pump", "concrete"), "concrete"),
                     (("crush", "screen"), "crusher"), (("jumbo", "drill", "shotcrete", "vent"), "tunnel"),
                     (("roller", "compact"), "compaction"), (("gen", "compress"), "generator"),
                     (("jeep", "pickup", "car", "bike", "motor"), "light_vehicle"),
                     (("survey", "lab", "total station"), "survey_lab"), (("computer", "printer", "it"), "it_office"),
                     (("furniture",), "furniture"), (("land",), "land"), (("building", "camp"), "building"),
                     (("software",), "software"), (("tool",), "small_tools")):
        if any(w in s for w in words):
            return k
    return "heavy_earth" if s else "small_tools"


def _defaults(klass):
    _, meth, life, hours, resid, pool, abc = F.CLASS_POLICY.get(klass, F.CLASS_POLICY["small_tools"])
    return {"method": meth, "life_years": life, "life_hours": hours, "resid_pct": resid, "tax_pool": pool,
            "abc_class": abc}


@api("fa.sync", MODULE, "edit")
def fa_sync(c, u, a):
    """Bring every machine and every asset into the capital register (existing lines are kept)."""
    added = 0
    ecols = _cols(c, "equipment")
    cost_col = next((x for x in ("purchase_value", "purchase_cost", "cost", "value") if x in ecols), None)
    date_col = next((x for x in ("purchase_date", "commissioned", "acquired") if x in ecols), None)
    for e in q(c, "SELECT * FROM equipment ORDER BY code"):
        e = dict(e)
        if (e.get("ownership") or "owned") in ("rented", "hired", "rental"):
            continue                                    # hired machines are leases, not PPE
        if val(c, "SELECT id FROM fa_register WHERE kind='equipment' AND ref_id=?", (e["id"],), None):
            continue
        k = _guess_class(e.get("category") or e.get("name"))
        d = _defaults(k)
        cost = num(e.get(cost_col)) if cost_col else 0
        ins(c, "fa_register", {"kind": "equipment", "ref_id": e["id"], "code": e["code"], "name": e["name"],
                               "klass": k, "method": d["method"], "life_years": d["life_years"],
                               "life_hours": d["life_hours"], "cost": cost, "residual": r2(cost * d["resid_pct"]),
                               "in_use_date": e.get(date_col) if date_col else None, "project_id": e.get("project_id"),
                               "tax_pool": d["tax_pool"], "abc_class": d["abc_class"],
                               "hour_reading": num(e.get("meter")), "created": now(),
                               "status": "disposed" if e.get("status") == "disposed" else "active"})
        added += 1
    if _has(c, "assets"):
        for s in q(c, "SELECT * FROM assets ORDER BY code"):
            s = dict(s)
            if val(c, "SELECT id FROM fa_register WHERE kind='asset' AND ref_id=?", (s["id"],), None):
                continue
            k = s.get("class") if s.get("class") in F.CLASS_POLICY else _guess_class(s.get("class") or s.get("name"))
            d = _defaults(k)
            ins(c, "fa_register", {"kind": "asset", "ref_id": s["id"], "code": s["code"], "name": s["name"],
                                   "klass": k, "method": d["method"], "life_years": d["life_years"],
                                   "life_hours": 0, "cost": num(s.get("purchase_value")),
                                   "residual": 0, "in_use_date": s.get("purchase_date"),
                                   "project_id": s.get("project_id"), "tax_pool": d["tax_pool"],
                                   "abc_class": "C", "accumulated": num(s.get("accumulated_dep")),
                                   # the Asset module already posts its own depreciation - leave it there
                                   "managed": 0, "created": now(),
                                   "status": "disposed" if s.get("status") == "disposed" else "active"})
            added += 1
    audit(c, u, "sync", "fa_register", None, {"added": added})
    return {"added": added, "total": val(c, "SELECT COUNT(*) FROM fa_register", ())}


def _nbv(r):
    return r2(num(r["cost"]) - num(r["accumulated"]) - num(r["impairment"]))


@api("fa.list", MODULE, "view")
def fa_list(c, u, a):
    w, p = ["1=1"], []
    for k in ("kind", "klass", "abc_class", "tax_pool", "status", "lifecycle"):
        if a.get(k):
            w.append("%s=?" % k)
            p.append(a[k])
    if a.get("project_id"):
        w.append("project_id=?")
        p.append(int(a["project_id"]))
    rows = []
    for r in q(c, "SELECT * FROM fa_register WHERE %s ORDER BY kind DESC, code" % " AND ".join(w), p):
        d = dict(r)
        d["nbv"] = _nbv(r)
        d["components"] = val(c, "SELECT COUNT(*) FROM fa_components WHERE fa_id=? AND status='active'", (r["id"],))
        rows.append(d)
    tot = {k: r2(sum(x[k] for x in rows)) for k in ("cost", "accumulated", "impairment", "nbv")}
    by = {}
    for x in rows:
        b = by.setdefault(x["klass"], {"klass": x["klass"], "count": 0, "cost": 0, "accumulated": 0, "nbv": 0})
        b["count"] += 1
        for k in ("cost", "accumulated", "nbv"):
            b[k] = r2(b[k] + x[k])
    return {"rows": rows, "totals": tot, "by_class": sorted(by.values(), key=lambda x: -x["cost"])}


@api("fa.get", MODULE, "view")
def fa_get(c, u, a):
    need(a, "id")
    r = dict(_fa(c, a["id"]))
    r["nbv"] = _nbv(_fa(c, a["id"]))
    return {"item": r,
            "components": [dict(x) for x in q(c, "SELECT * FROM fa_components WHERE fa_id=? ORDER BY id", (r["id"],))],
            "dep": [dict(x) for x in q(c, "SELECT * FROM fa_dep WHERE fa_id=? ORDER BY month DESC, comp_id LIMIT 60",
                                       (r["id"],))],
            "maint": [dict(x) for x in q(c, "SELECT * FROM fa_maint WHERE fa_id=? ORDER BY date DESC", (r["id"],))],
            "impair": [dict(x) for x in q(c, "SELECT * FROM fa_impair WHERE fa_id=? ORDER BY date DESC", (r["id"],))],
            "rates": [dict(x) for x in q(c, "SELECT * FROM fa_rates WHERE fa_id=? ORDER BY effective_from DESC",
                                         (r["id"],))],
            "abc_policy": F.ABC_POLICY.get(r["abc_class"] or "C")}


EDITABLE = ("code", "name", "klass", "method", "life_years", "life_hours", "residual", "wdv_rate", "cost",
            "in_use_date", "project_id", "tax_pool", "owner_entity", "owner_share", "lifecycle", "abc_class",
            "s_workload", "s_impact_other", "s_impact_production", "s_repair_ease", "s_price", "idle_threshold",
            "managed", "hour_reading", "last_service_hour", "last_inspection", "remarks")


@api("fa.save", MODULE, "edit")
def fa_save(c, u, a):
    row = {k: v for k, v in (a.get("row") or {}).items() if k in EDITABLE}
    if row.get("method") and row["method"] not in F.METHODS:
        raise ApiError("Unknown depreciation method.")
    if row.get("tax_pool") and row["tax_pool"] not in F.TAX_POOLS:
        raise ApiError("Tax pool must be A, B, C, D or E.")
    if (row.get("method") == "UOP") and not num(row.get("life_hours")):
        if not (a.get("row") or {}).get("id") or not num(_fa(c, a["row"]["id"])["life_hours"]):
            raise ApiError("The hour-meter method needs the machine's life in hours.")
    rid = (a.get("row") or {}).get("id")
    if rid:
        old = _fa(c, rid)
        if val(c, "SELECT COUNT(*) FROM fa_dep WHERE fa_id=?", (rid,)) and "cost" in row \
                and abs(num(row["cost"]) - num(old["cost"])) > EPS:
            raise ApiError("Depreciation has been posted on this item. Add the extra cost as a component "
                           "(NAS 16 subsequent cost) instead of changing the original cost.")
        merged = dict(old)
        merged.update(row)
    else:
        need(row, "code", "name", "klass")
        d = _defaults(row["klass"])
        merged = {"kind": "asset" if row["klass"] in ("land", "building", "it_office", "furniture", "software")
                  else "equipment", "ref_id": None, "method": d["method"], "life_years": d["life_years"],
                  "life_hours": d["life_hours"], "tax_pool": d["tax_pool"], "abc_class": d["abc_class"],
                  "created": now(), "managed": 1}
        merged.update(row)
    sc = {k: int(merged.get("s_" + k) or 1) for k, _ in F.ABC_CRITERIA}
    merged["abc_score"] = F.abc_score(sc)
    if a.get("abc_from_score") or (not rid and any(v != 1 for v in sc.values())):
        merged["abc_class"] = F.abc_class_by_score(merged["abc_score"])
    keep = {k: merged.get(k) for k in EDITABLE + ("abc_score",)}
    if rid:
        upd(c, "fa_register", int(rid), keep)
    else:
        keep.update({k: merged[k] for k in ("kind", "ref_id", "created", "managed")})
        rid = ins(c, "fa_register", keep)
    audit(c, u, "save", "fa_register", rid, keep)
    return {"id": rid, "abc_score": merged["abc_score"], "abc_class": merged["abc_class"]}


@api("fa.components_split", MODULE, "edit")
def fa_components_split(c, u, a):
    """Split an item into its NAS 16 components from the class template (or lines given)."""
    need(a, "id")
    r = _fa(c, a["id"])
    if val(c, "SELECT COUNT(*) FROM fa_dep WHERE fa_id=?", (r["id"],)):
        raise ApiError("Depreciation already posted - split components before the first run.")
    tpl = None
    if a.get("lines"):
        tpl = [(x["name"], num(x["share"]), x.get("method") or r["method"], num(x.get("life_hours")))
               for x in a["lines"]]
        if abs(sum(t[1] for t in tpl) - 1) > 0.001:
            raise ApiError("Component shares must add up to 100%.")
    parts = F.split_components(num(r["cost"]), r["klass"], tpl)
    if not parts:
        raise ApiError("No component template for this class - enter the lines yourself.")
    c.execute("DELETE FROM fa_components WHERE fa_id=?", (r["id"],))
    res_pct = num(r["residual"]) / num(r["cost"]) if num(r["cost"]) else 0
    for p in parts:
        ins(c, "fa_components", {"fa_id": r["id"], "name": p["name"], "cost": p["cost"], "method": p["method"],
                                 "life_years": r["life_years"], "life_hours": p["life_hours"] or r["life_hours"],
                                 "residual": r2(p["cost"] * res_pct), "in_use_date": r["in_use_date"]})
    audit(c, u, "components", "fa_register", r["id"], {"n": len(parts)})
    return {"components": len(parts)}


@api("fa.component_save", MODULE, "edit")
def fa_component_save(c, u, a):
    """Add a component (overhaul, replacement engine) or edit one. Replacing derecognises the old one."""
    row = a.get("row") or {}
    need(row, "fa_id", "name", "cost")
    r = _fa(c, row["fa_id"])
    d = {k: row.get(k) for k in ("name", "cost", "method", "life_years", "life_hours", "residual", "in_use_date",
                                 "remarks") if k in row}
    if row.get("id"):
        upd(c, "fa_components", int(row["id"]), d)
        return {"id": row["id"]}
    d.update({"fa_id": r["id"], "method": d.get("method") or r["method"],
              "life_years": d.get("life_years") or r["life_years"], "in_use_date": d.get("in_use_date") or today()})
    out = {}
    if row.get("replaces"):                          # NAS 16 para 70: derecognise the replaced part
        old = get(c, "fa_components", int(row["replaces"]), "Component")
        left = r2(num(old["cost"]) - num(old["accumulated"]))
        if a.get("post", True):
            assert_open(c, u, d["in_use_date"])
            out["voucher_id"] = _post(c, u, {"date": d["in_use_date"], "type": "journal",
                                             "project_id": r["project_id"], "source": "fa_component",
                                             "source_id": old["id"],
                                             "narration": "Replaced %s of %s" % (old["name"], r["code"])}, [
                {"role": "accum_dep", "debit": r2(num(old["accumulated"])), "narration": "Depreciation written back"},
                {"role": "disposal_loss", "debit": left, "narration": "Carrying amount of replaced part"},
                {"role": "fixed_asset", "credit": r2(num(old["cost"])), "narration": old["name"] + " removed"}])
        upd(c, "fa_components", old["id"], {"status": "replaced", "replaced_on": d["in_use_date"]})
        upd(c, "fa_register", r["id"], {"cost": r2(num(r["cost"]) - num(old["cost"])),
                                        "accumulated": r2(num(r["accumulated"]) - num(old["accumulated"]))})
        r = _fa(c, r["id"])
        out["derecognised"] = left
    cid = ins(c, "fa_components", d)
    upd(c, "fa_register", r["id"], {"cost": r2(num(r["cost"]) + num(d["cost"]))})
    audit(c, u, "component", "fa_register", r["id"], d)
    out["id"] = cid
    return out


# ───────────────────────── hours from the logsheets ─────────────────────────
def hours_used(c, fa_row, month):
    """Hours the machine ran in a month, from approved (else any) logsheets, per project."""
    if fa_row["kind"] != "equipment" or not fa_row["ref_id"] or not _has(c, "logsheets"):
        return {}
    lcols = _cols(c, "logsheets")
    hcol = next((x for x in ("hours", "work_hours", "hmr_total", "total_hours") if x in lcols), None)
    if not hcol or not _has(c, "logbooks"):
        return {}
    rows = q(c, "SELECT b.project_id, SUM(l.%s) h, MAX(b.status) st FROM logsheets l JOIN logbooks b ON b.id=l.book_id "
                "WHERE b.equipment_id=? AND b.period=? AND b.sheet_type IN ('owned','hired_out','vehicle','genset',"
                "'drilling','dewatering','hoist') GROUP BY b.project_id" % hcol, (fa_row["ref_id"], month[:7]))
    return {x["project_id"]: num(x["h"]) for x in rows if num(x["h"]) > 0}


# ───────────────────────── monthly depreciation ─────────────────────────
def _units(c, fa_row):
    comps = q(c, "SELECT * FROM fa_components WHERE fa_id=? AND status='active' ORDER BY id", (fa_row["id"],))
    if comps:
        return [(x["id"], dict(x)) for x in comps]
    return [(0, dict(fa_row))]


def _dep_rows(c, month, hours_override=None):
    first, last = month + "-01", month_end(month + "-01")
    days = (date.fromisoformat(last) - date.fromisoformat(first)).days + 1
    out = []
    for r in q(c, "SELECT * FROM fa_register WHERE status='active' AND managed=1 AND method<>'NONE' "
                  "AND in_use_date IS NOT NULL AND in_use_date<=? ORDER BY code", (last,)):
        hrs_by_proj = (hours_override or {}).get(str(r["id"])) or hours_used(c, r, month)
        if isinstance(hrs_by_proj, (int, float)):
            hrs_by_proj = {r["project_id"]: num(hrs_by_proj)}
        total_h = sum(hrs_by_proj.values())
        for cid, u_ in _units(c, r):
            if val(c, "SELECT id FROM fa_dep WHERE fa_id=? AND comp_id=? AND month=?", (r["id"], cid, month), None):
                continue
            start = u_.get("in_use_date") or r["in_use_date"]
            if start > last:
                continue
            frac = 1.0
            if start[:7] == month:
                frac = ((date.fromisoformat(last) - date.fromisoformat(start[:10])).days + 1) / days
            m_in = F.months_between(start, first)
            amt = F.month_dep(num(u_["cost"]), num(u_["residual"]), num(u_["life_years"]), u_["method"],
                              num(u_["accumulated"]), m_in, hours=total_h, life_hours=num(u_["life_hours"]),
                              rate=u_.get("wdv_rate") or None, days_fraction=frac)
            if amt <= EPS:
                continue
            split = {k: amt * v / total_h for k, v in hrs_by_proj.items()} if (total_h and len(hrs_by_proj) > 1) \
                else {(list(hrs_by_proj)[0] if hrs_by_proj else r["project_id"]): amt}
            out.append({"fa_id": r["id"], "code": r["code"], "name": r["name"], "comp_id": cid,
                        "component": u_["name"] if cid else "", "method": u_["method"], "hours": r2(total_h),
                        "amount": amt, "split": {k: r2(v) for k, v in split.items()},
                        "nbv_after": r2(num(u_["cost"]) - num(u_["accumulated"]) - amt)})
    return out


@api("fa.dep_preview", MODULE, "view")
def fa_dep_preview(c, u, a):
    month = (a.get("month") or today())[:7]
    rows = _dep_rows(c, month, a.get("hours"))
    last = month_end(month + "-01")
    no_hours = [x["code"] for x in q(c, "SELECT code FROM fa_register r WHERE method='UOP' AND status='active' "
                                        "AND managed=1 AND in_use_date<=? AND NOT EXISTS(SELECT 1 FROM fa_dep d "
                                        "WHERE d.fa_id=r.id AND d.month=?) ORDER BY code", (last, month))
                if x["code"] not in {y["code"] for y in rows}]
    return {"month": month, "rows": rows, "total": r2(sum(x["amount"] for x in rows)),
            "no_hours": no_hours,
            "posted": val(c, "SELECT COALESCE(SUM(amount),0) FROM fa_dep WHERE month=?", (month,))}


@api("fa.dep_run", MODULE, "approve")
def fa_dep_run(c, u, a):
    month = (a.get("month") or today())[:7]
    end = month_end(month + "-01")
    assert_open(c, u, end)
    rows = _dep_rows(c, month, a.get("hours"))
    if not rows:
        raise ApiError("Nothing to depreciate for %s (already posted, or no hours on the logsheets)." % month)
    by_proj = {}
    for x in rows:
        for p, v in x["split"].items():
            by_proj[p] = by_proj.get(p, 0) + v
    vids = {}
    for p, amt in by_proj.items():
        vids[p] = _post(c, u, {"date": end, "type": "journal", "project_id": p, "source": "fa_dep", "source_id": None,
                               "narration": "Depreciation of plant and equipment for " + month},
                        [{"role": "depreciation", "debit": r2(amt), "narration": "NAS 16 depreciation " + month},
                         {"role": "accum_dep", "credit": r2(amt), "narration": "Accumulated depreciation"}])
    for x in rows:
        p0 = list(x["split"])[0]
        ins(c, "fa_dep", {"fa_id": x["fa_id"], "comp_id": x["comp_id"], "month": month, "method": x["method"],
                          "hours": x["hours"], "amount": x["amount"], "project_id": p0, "voucher_id": vids.get(p0),
                          "ts": now()})
        if x["comp_id"]:
            c.execute("UPDATE fa_components SET accumulated=accumulated+? WHERE id=?", (x["amount"], x["comp_id"]))
        c.execute("UPDATE fa_register SET accumulated=accumulated+? WHERE id=?", (x["amount"], x["fa_id"]))
        ins(c, "fa_costs", {"fa_id": x["fa_id"], "date": end, "category": "depreciation", "amount": x["amount"],
                            "project_id": p0, "voucher_id": vids.get(p0), "ref": "DEP " + month, "ts": now()})
    audit(c, u, "dep_run", "fa_register", None, {"month": month, "items": len(rows)})
    return {"month": month, "items": len(rows), "total": r2(sum(x["amount"] for x in rows)),
            "vouchers": [v for v in vids.values() if v]}


@api("fa.dep_reverse", MODULE, "approve")
def fa_dep_reverse(c, u, a):
    """Take a month's run back out (only the latest month, and only while its period is open)."""
    month = (a.get("month") or "")[:7]
    need(a, "month")
    if val(c, "SELECT MAX(month) FROM fa_dep", ()) != month:
        raise ApiError("Only the latest month posted can be reversed.")
    assert_open(c, u, month_end(month + "-01"))
    rows = q(c, "SELECT * FROM fa_dep WHERE month=?", (month,))
    by_proj = {}
    for x in rows:
        by_proj[x["project_id"]] = by_proj.get(x["project_id"], 0) + num(x["amount"])
        if x["comp_id"]:
            c.execute("UPDATE fa_components SET accumulated=accumulated-? WHERE id=?", (x["amount"], x["comp_id"]))
        c.execute("UPDATE fa_register SET accumulated=accumulated-? WHERE id=?", (x["amount"], x["fa_id"]))
    for p, amt in by_proj.items():
        _post(c, u, {"date": month_end(month + "-01"), "type": "journal", "project_id": p, "source": "fa_dep_rev",
                     "narration": "Reversal of depreciation for " + month},
              [{"role": "accum_dep", "debit": r2(amt)}, {"role": "depreciation", "credit": r2(amt)}])
    c.execute("DELETE FROM fa_dep WHERE month=?", (month,))
    c.execute("DELETE FROM fa_costs WHERE category='depreciation' AND ref=?", ("DEP " + month,))
    audit(c, u, "dep_reverse", "fa_register", None, {"month": month})
    return {"reversed": len(rows)}


@api("fa.schedule", MODULE, "view")
def fa_schedule(c, u, a):
    """Whole-life projection: book schedule, and the tax-pool view of the same item."""
    need(a, "id")
    r = _fa(c, a["id"])
    hrs = a.get("hours_by_year")
    if not hrs and r["method"] == "UOP":
        per = num(a.get("annual_hours")) or (num(r["life_hours"]) / num(r["life_years"]) if num(r["life_years"]) else 0)
        hrs = [per] * int(num(r["life_years"]) or 1)
    book = F.annual_schedule(num(r["cost"]), num(r["residual"]), int(num(r["life_years"]) or 0), r["method"],
                             hours_by_year=hrs, life_hours=num(r["life_hours"]), rate=r["wdv_rate"] or None)
    rate = F.TAX_POOLS.get(r["tax_pool"] or "D", (0.15,))[0] or 0
    tax, wdv = [], num(r["cost"])
    for y in range(1, len(book) + 1):
        d = wdv * rate if r["tax_pool"] != "E" else num(r["cost"]) / max(num(r["life_years"]), 1)
        tax.append({"year": y, "opening": r2(wdv), "dep": r2(d), "closing": r2(wdv - d)})
        wdv -= d
    comps = [dict(x) for x in q(c, "SELECT * FROM fa_components WHERE fa_id=? AND status='active'", (r["id"],))]
    comp_sched = [{"name": x["name"], "rows": F.annual_schedule(num(x["cost"]), num(x["residual"]),
                                                                  int(num(x["life_years"]) or 0), x["method"],
                                                                  hours_by_year=hrs, life_hours=num(x["life_hours"]))}
                  for x in comps]
    dt = [dict(F.deferred_tax(b["closing"], t["closing"], num(_setting(c, "tax_rate", 0.25))), year=b["year"])
          for b, t in zip(book, tax)]
    return {"item": dict(r), "book": book, "tax": tax, "components": comp_sched, "deferred": dt,
            "note": "Tax column is indicative: tax depreciation is computed on the pool, not per item."}


# ───────────────────────── tax pools & deferred tax ─────────────────────────
def _pool_inputs(c, fy, s, e):
    res = {}
    for pool in "ABCDE":
        prev = q1(c, "SELECT closing FROM fa_tax WHERE pool=? AND fy<? ORDER BY fy DESC LIMIT 1", (pool, fy))
        opening = num(prev["closing"]) if prev else num(_setting(c, "tax_pool_opening_" + pool, 0))
        adds = [(x["in_use_date"], num(x["cost"]) * num(x["owner_share"] or 100) / 100.0)
                for x in q(c, "SELECT in_use_date, cost, owner_share FROM fa_register WHERE tax_pool=? "
                              "AND in_use_date BETWEEN ? AND ?", (pool, s, e))]
        # components bought after the item (overhauls, engines) are additions to the pool too
        adds += [(x["in_use_date"], num(x["cost"])) for x in q(
            c, "SELECT k.in_use_date, k.cost FROM fa_components k JOIN fa_register r ON r.id=k.fa_id "
               "WHERE r.tax_pool=? AND k.in_use_date BETWEEN ? AND ? AND k.in_use_date>r.in_use_date", (pool, s, e))]
        disp = num(val(c, "SELECT SUM(disposal_proceeds) FROM fa_register WHERE tax_pool=? AND disposal_date "
                          "BETWEEN ? AND ?", (pool, s, e)))
        rep = num(val(c, "SELECT SUM(c.amount) FROM fa_costs c JOIN fa_register r ON r.id=c.fa_id WHERE "
                         "r.tax_pool=? AND c.category='repairs' AND c.date BETWEEN ? AND ?", (pool, s, e)))
        # (maintenance entries that are not capitalised are already in fa_costs as 'repairs')
        left = val(c, "SELECT COUNT(*) FROM fa_register WHERE tax_pool=? AND status='active' "
                      "AND (in_use_date IS NULL OR in_use_date<=?)", (pool, e))
        gone = val(c, "SELECT COUNT(*) FROM fa_register WHERE tax_pool=? AND disposal_date BETWEEN ? AND ?",
                   (pool, s, e))
        # the pool is dissolved only when its last asset leaves during the year
        res[pool] = {"opening": opening, "additions": adds, "disposals": disp, "repairs": rep,
                     "empty": bool(gone) and left == 0}
    return res


@api("fa.tax_pools", MODULE, "view")
def fa_tax_pools(c, u, a):
    fy, s, e = fy_bounds(c, a.get("fy"), a.get("on"))
    ins_ = _pool_inputs(c, fy, s, e)
    out = []
    for pool, x in ins_.items():
        if pool == "E":
            dep = sum(F.pool_e_amortisation(num(r["cost"]), num(r["life_years"]) or 1,
                                            min(12, F.months_between(max(r["in_use_date"], s), e) + 1))
                      for r in q(c, "SELECT * FROM fa_register WHERE tax_pool='E' AND status='active' "
                                    "AND in_use_date<=?", (e,)))
            w = {"pool": "E", "rate": None, "opening": r2(x["opening"]), "additions": [],
                 "additions_total": r2(sum(v for _, v in x["additions"])), "additions_counted": 0,
                 "disposals": r2(x["disposals"]), "base": 0, "depreciation": r2(dep), "deferred_additions": 0,
                 "repairs": 0, "repairs_allowed": 0, "repairs_added_to_pool": 0, "balancing_charge": 0,
                 "terminal_loss": 0,
                 "closing": r2(x["opening"] + sum(v for _, v in x["additions"]) - x["disposals"] - dep)}
        else:
            w = F.tax_pool_year(pool, x["opening"], x["additions"], e, x["disposals"], x["repairs"],
                                pool_empty_after=bool(x["empty"]))
        w["description"] = F.TAX_POOLS[pool][1]
        w["locked"] = bool(val(c, "SELECT locked FROM fa_tax WHERE fy=? AND pool=?", (fy, pool), 0))
        out.append(w)
    tot = {k: r2(sum(num(w[k]) for w in out)) for k in ("opening", "additions_total", "disposals", "depreciation",
                                                         "balancing_charge", "terminal_loss", "closing",
                                                         "repairs_allowed", "repairs_added_to_pool")}
    return {"fy": fy, "from": s, "to": e, "pools": out, "totals": tot}


@api("fa.tax_lock", MODULE, "approve")
def fa_tax_lock(c, u, a):
    """Freeze the year's pool working so next year opens from it (the figures filed with the return)."""
    d = fa_tax_pools(c, u, a)
    for w in d["pools"]:
        ex = q1(c, "SELECT id, locked FROM fa_tax WHERE fy=? AND pool=?", (d["fy"], w["pool"]))
        if ex and ex["locked"] and not a.get("force"):
            raise ApiError("Pool %s for %s is already locked." % (w["pool"], d["fy"]))
        rec = {"fy": d["fy"], "pool": w["pool"], "opening": w["opening"], "working": json.dumps(w),
               "closing": w["closing"], "locked": 1, "ts": now()}
        if ex:
            upd(c, "fa_tax", ex["id"], rec)
        else:
            ins(c, "fa_tax", rec)
    audit(c, u, "tax_lock", "fa_tax", None, {"fy": d["fy"]})
    return {"fy": d["fy"], "locked": len(d["pools"])}


@api("fa.deferred_tax", MODULE, "view")
def fa_deferred_tax(c, u, a):
    fy, s, e = fy_bounds(c, a.get("fy"), a.get("on"))
    rate = num(a.get("rate") or _setting(c, "tax_rate", 0.25))
    carrying = sum(_nbv(r) for r in q(c, "SELECT * FROM fa_register WHERE status='active' AND tax_pool IS NOT NULL"))
    pools = fa_tax_pools(c, u, {"fy": fy})
    tax_base = pools["totals"]["closing"]
    d = F.deferred_tax(carrying, tax_base, rate)
    prev = num(val(c, "SELECT balance FROM fa_deferred WHERE fy<? ORDER BY fy DESC LIMIT 1", (fy,), 0))
    d.update({"fy": fy, "date": e, "opening": r2(prev), "movement": r2(d["net"] - prev),
              "posted": bool(val(c, "SELECT voucher_id FROM fa_deferred WHERE fy=?", (fy,), None))})
    return d


@api("fa.deferred_post", MODULE, "approve")
def fa_deferred_post(c, u, a):
    d = fa_deferred_tax(c, u, a)
    if d["posted"]:
        raise ApiError("Deferred tax for %s is already posted." % d["fy"])
    assert_open(c, u, d["date"])
    mv = d["movement"]
    vid = _post(c, u, {"date": d["date"], "type": "journal", "source": "fa_deferred",
                       "narration": "NAS 12 deferred tax on PPE for %s" % d["fy"]},
                [{"role": "deferred_tax_exp", "debit" if mv > 0 else "credit": abs(mv)},
                 {"role": "dtl", "credit" if mv > 0 else "debit": abs(mv)}])
    ins(c, "fa_deferred", {"fy": d["fy"], "carrying": d["carrying"], "tax_base": d["tax_base"], "rate": d["rate"],
                           "balance": d["net"], "movement": mv, "voucher_id": vid, "ts": now()})
    return {"movement": mv, "voucher_id": vid}


# ───────────────────────── equipment costing ─────────────────────────
@api("fa.cost_add", MODULE, "edit")
def fa_cost_add(c, u, a):
    """A line in the equipment cost ledger (fuel, repairs, insurance...). Post it with its voucher
    in Accounts as usual; this line tags the cost to the machine for rate and true-up."""
    need(a, "fa_id", "date", "category", "amount")
    if a["category"] not in dict(COST_CATEGORIES):
        raise ApiError("Unknown cost category.")
    r = _fa(c, a["fa_id"])
    cid = ins(c, "fa_costs", {"fa_id": r["id"], "date": a["date"], "category": a["category"],
                              "amount": r2(num(a["amount"])), "project_id": a.get("project_id") or r["project_id"],
                              "ref": a.get("ref"), "voucher_id": a.get("voucher_id"), "remarks": a.get("remarks"),
                              "user_id": u["id"], "ts": now()})
    return {"id": cid}


@api("fa.ledger", MODULE, "view")
def fa_ledger(c, u, a):
    """Peterson's equipment ledger: costs by category against what was charged to the jobs."""
    fy, s, e = fy_bounds(c, a.get("fy"), a.get("on"))
    w, p = "", [s, e]
    if a.get("fa_id"):
        w = " AND r.id=?"
        p.append(int(a["fa_id"]))
    rows = []
    for r in q(c, "SELECT r.* FROM fa_register r WHERE r.kind='equipment'" + w + " ORDER BY r.code", p[2:]):
        costs = {k: 0.0 for k, _ in COST_CATEGORIES}
        for x in q(c, "SELECT category, SUM(amount) a FROM fa_costs WHERE fa_id=? AND date BETWEEN ? AND ? "
                      "GROUP BY category", (r["id"], s, e)):
            costs[x["category"]] = r2(x["a"])
        charged = r2(val(c, "SELECT COALESCE(SUM(amount),0) FROM fa_alloc WHERE fa_id=? AND (kind='charge' "
                            "AND month BETWEEN ? AND ? OR kind='true_up' AND fy=?)", (r["id"], s[:7], e[:7], fy)))
        hours = r2(val(c, "SELECT COALESCE(SUM(hours),0) FROM fa_alloc WHERE fa_id=? AND kind='charge' "
                          "AND month BETWEEN ? AND ?", (r["id"], s[:7], e[:7])))
        actual = r2(sum(costs.values()))
        rows.append(dict(costs, fa_id=r["id"], code=r["code"], name=r["name"], abc=r["abc_class"], actual=actual,
                         charged=charged, hours=hours, variance=r2(actual - charged),
                         actual_per_hour=r2(actual / hours) if hours else None))
    return {"fy": fy, "from": s, "to": e, "rows": rows, "categories": COST_CATEGORIES,
            "totals": {k: r2(sum(x[k] for x in rows)) for k in [k for k, _ in COST_CATEGORIES] +
                       ["actual", "charged", "hours", "variance"]}}


@api("fa.rate_calc", MODULE, "view")
def fa_rate_calc(c, u, a):
    need(a, "id")
    r = _fa(c, a["id"])
    p = dict(a.get("params") or {})
    kw = {"cost": num(r["cost"]), "residual": num(r["residual"]), "life_years": num(r["life_years"]) or 1,
          "annual_hours": num(p.get("annual_hours")) or (num(r["life_hours"]) / (num(r["life_years"]) or 1)
                                                         if num(r["life_hours"]) else 1600),
          "vehicle_tax": num(p.get("vehicle_tax", VEHICLE_TAX.get(r["klass"], 0)))}
    for k in ("interest_rate", "insurance_tax_pct", "repair_pct_of_dep", "fuel_lph", "fuel_price", "lube_pct_of_fuel",
              "tyre_cost", "tyre_life_hours", "operator_hr", "overhead_pct", "idle_allowance"):
        if p.get(k) not in (None, ""):
            kw[k] = num(p[k])
    res = F.hire_rate(**kw)
    res["inputs"] = kw
    return res


@api("fa.rate_save", MODULE, "edit")
def fa_rate_save(c, u, a):
    res = fa_rate_calc(c, u, a)
    fy, s, _ = fy_bounds(c, a.get("fy"), a.get("effective_from"))
    rid = ins(c, "fa_rates", {"fa_id": int(a["id"]), "fy": fy, "effective_from": a.get("effective_from") or s,
                              "annual_hours": res["hours"], "params": json.dumps(res["inputs"]),
                              "rate_hour": res["rate_per_hour"], "dry_rate_hour": res["dry_rate_per_hour"],
                              "ts": now()})
    r = _fa(c, a["id"])
    if a.get("update_equipment") and r["kind"] == "equipment" and "internal_rate" in _cols(c, "equipment"):
        c.execute("UPDATE equipment SET internal_rate=? WHERE id=?", (res["rate_per_hour"], r["ref_id"]))
    audit(c, u, "rate", "fa_register", r["id"], {"rate": res["rate_per_hour"]})
    return {"id": rid, "rate_per_hour": res["rate_per_hour"]}


def _rate_on(c, fa_id, on):
    x = q1(c, "SELECT rate_hour FROM fa_rates WHERE fa_id=? AND effective_from<=? ORDER BY effective_from DESC, id "
              "DESC LIMIT 1", (fa_id, on))
    return num(x["rate_hour"]) if x else 0.0


def _alloc_rows(c, month, only=None):
    out = []
    last = month_end(month + "-01")
    for r in q(c, "SELECT * FROM fa_register WHERE kind='equipment' AND status='active' ORDER BY code"):
        if only and r["id"] not in only:
            continue
        if val(c, "SELECT id FROM fa_alloc WHERE fa_id=? AND month=? AND kind='charge'", (r["id"], month), None):
            continue
        rate = _rate_on(c, r["id"], last)
        for pid, h in hours_used(c, r, month).items():
            out.append({"fa_id": r["id"], "code": r["code"], "name": r["name"], "project_id": pid, "hours": r2(h),
                        "rate": rate, "amount": r2(h * rate), "no_rate": not rate})
    return out


@api("fa.alloc_preview", MODULE, "view")
def fa_alloc_preview(c, u, a):
    month = (a.get("month") or today())[:7]
    rows = _alloc_rows(c, month)
    return {"month": month, "rows": rows, "total": r2(sum(x["amount"] for x in rows)),
            "hours": r2(sum(x["hours"] for x in rows)), "no_rate": [x["code"] for x in rows if x["no_rate"]]}


@api("fa.alloc_run", MODULE, "approve")
def fa_alloc_run(c, u, a):
    """Charge each project for the machine hours it used: Dr project equipment cost / Cr recovery."""
    month = (a.get("month") or today())[:7]
    end = month_end(month + "-01")
    assert_open(c, u, end)
    rows = [x for x in _alloc_rows(c, month) if x["amount"] > EPS]
    if not rows:
        raise ApiError("No machine hours with a rate to charge for %s." % month)
    fy = fy_bounds(c, None, end)[0]
    by_proj = {}
    for x in rows:
        by_proj.setdefault(x["project_id"], []).append(x)
    vids = {}
    for pid, xs in by_proj.items():
        tot = r2(sum(x["amount"] for x in xs))
        vids[pid] = _post(c, u, {"date": end, "type": "journal", "project_id": pid, "source": "fa_alloc",
                                 "narration": "Equipment hours charged to project for " + month},
                          [{"role": "equip_job_cost", "debit": tot,
                            "narration": "; ".join("%s %sh @ %s" % (x["code"], x["hours"], x["rate"]) for x in xs)[:250]},
                           {"role": "equip_recovery", "credit": tot, "narration": "Equipment cost recovered"}])
    for x in rows:
        ins(c, "fa_alloc", {"fa_id": x["fa_id"], "month": month, "project_id": x["project_id"], "kind": "charge",
                            "hours": x["hours"], "rate": x["rate"], "amount": x["amount"], "fy": fy,
                            "voucher_id": vids[x["project_id"]], "ts": now()})
    audit(c, u, "alloc_run", "fa_alloc", None, {"month": month, "lines": len(rows)})
    return {"month": month, "lines": len(rows), "total": r2(sum(x["amount"] for x in rows))}


@api("fa.trueup_preview", MODULE, "view")
def fa_trueup_preview(c, u, a):
    fy, s, e = fy_bounds(c, a.get("fy"), a.get("on"))
    out = []
    for r in q(c, "SELECT * FROM fa_register WHERE kind='equipment' ORDER BY code"):
        actual = num(val(c, "SELECT SUM(amount) FROM fa_costs WHERE fa_id=? AND date BETWEEN ? AND ?", (r["id"], s, e)))
        charges = {x["project_id"]: num(x["a"]) for x in q(
            c, "SELECT project_id, SUM(amount) a FROM fa_alloc WHERE fa_id=? AND kind='charge' AND month BETWEEN ? "
               "AND ? GROUP BY project_id", (r["id"], s[:7], e[:7]))}
        if not charges or not actual:
            continue
        t = F.true_up(actual, charges)
        t.update({"fa_id": r["id"], "code": r["code"], "name": r["name"]})
        out.append(t)
    done = bool(val(c, "SELECT COUNT(*) FROM fa_alloc WHERE kind='true_up' AND fy=?", (fy,)))
    return {"fy": fy, "date": e, "rows": out, "variance": r2(sum(x["variance"] for x in out)), "posted": done}


@api("fa.trueup_run", MODULE, "approve")
def fa_trueup_run(c, u, a):
    d = fa_trueup_preview(c, u, a)
    if d["posted"]:
        raise ApiError("The true-up for %s is already posted." % d["fy"])
    assert_open(c, u, d["date"])
    by_proj = {}
    for t in d["rows"]:
        for pid, v in t["by_job"].items():
            by_proj[pid] = by_proj.get(pid, 0) + v
            ins(c, "fa_alloc", {"fa_id": t["fa_id"], "month": d["date"][:7], "project_id": pid, "kind": "true_up",
                                "amount": v, "fy": d["fy"], "ts": now()})
    for pid, v in by_proj.items():
        if abs(v) < EPS:
            continue
        vid = _post(c, u, {"date": d["date"], "type": "journal", "project_id": pid, "source": "fa_trueup",
                           "narration": "Year-end equipment %s-recovery %s" % ("under" if v > 0 else "over", d["fy"])},
                    [{"role": "equip_job_cost", "debit" if v > 0 else "credit": r2(abs(v))},
                     {"role": "equip_recovery", "credit" if v > 0 else "debit": r2(abs(v))}])
        c.execute("UPDATE fa_alloc SET voucher_id=? WHERE kind='true_up' AND fy=? AND project_id=?", (vid, d["fy"], pid))
    audit(c, u, "trueup", "fa_alloc", None, {"fy": d["fy"], "variance": d["variance"]})
    return {"fy": d["fy"], "variance": d["variance"], "projects": len(by_proj)}


# ───────────────────────── ABC & maintenance ─────────────────────────
@api("fa.abc_rank", MODULE, "edit")
def fa_abc_rank(c, u, a):
    """Rank the whole fleet on the five criteria (Wang 2022) and cut 20% A / 30% B / 50% C."""
    items = [{"id": r["id"], "score": F.abc_score({k: r["s_" + k] for k, _ in F.ABC_CRITERIA}), "price": num(r["cost"])}
             for r in q(c, "SELECT * FROM fa_register WHERE kind='equipment' AND status='active'")]
    cls = F.abc_rank_fleet(items)
    if a.get("apply"):
        for it in items:
            upd(c, "fa_register", it["id"], {"abc_class": cls[it["id"]], "abc_score": it["score"]})
        audit(c, u, "abc_rank", "fa_register", None, {"n": len(items)})
    return {"classes": cls, "counts": {k: sum(1 for v in cls.values() if v == k) for k in "ABC"}}


@api("fa.maint_plan", MODULE, "view")
def fa_maint_plan(c, u, a):
    fund = num(a.get("fund"))
    fleet = [dict(r) for r in q(c, "SELECT * FROM fa_register WHERE kind='equipment' AND status='active' ORDER BY code")]
    budget = F.maintenance_budget(fund, [{"id": f["id"], "abc": f["abc_class"] or "C"} for f in fleet]) if fund else {}
    on = a.get("on") or today()
    rows = []
    for f in fleet:
        k = f["abc_class"] or "C"
        pol = F.ABC_POLICY[k]
        ns = F.next_service(num(f["last_service_hour"]), k, num(f["hour_reading"]))
        last = f["last_inspection"]
        due = (date.fromisoformat(last[:10]) + timedelta(days=pol["inspect_days"])).isoformat() if last else on
        rows.append({"fa_id": f["id"], "code": f["code"], "name": f["name"], "abc": k,
                     "maintenance": pol["maintenance"], "repair": pol["repair"], "spares_pct": pol["spares"] * 100,
                     "safety_check": pol["safety_check"], "inspection_due": due, "inspection_overdue": due <= on,
                     "hour": num(f["hour_reading"]), "service_due_at": ns["due_at"], "hours_left": ns["hours_left"],
                     "service_overdue": ns["overdue"], "budget": budget.get(f["id"], 0),
                     "spent": r2(val(c, "SELECT COALESCE(SUM(cost),0) FROM fa_maint WHERE fa_id=? AND capitalise=0",
                                     (f["id"],)))})
    return {"rows": rows, "policy": F.ABC_POLICY,
            "overdue": sum(1 for x in rows if x["inspection_overdue"] or x["service_overdue"])}


@api("fa.maint_add", MODULE, "edit")
def fa_maint_add(c, u, a):
    need(a, "fa_id", "date", "kind")
    r = _fa(c, a["fa_id"])
    mid = ins(c, "fa_maint", {"fa_id": r["id"], "date": a["date"], "kind": a["kind"], "at_hour": num(a.get("at_hour")),
                              "cost": r2(num(a.get("cost"))), "capitalise": 1 if a.get("capitalise") else 0,
                              "remarks": a.get("remarks"), "user_id": u["id"]})
    ch = {}
    if a["kind"] in ("service", "overhaul"):
        ch["last_service_hour"] = num(a.get("at_hour")) or num(r["hour_reading"])
    if a["kind"] == "inspection":
        ch["last_inspection"] = a["date"]
    if num(a.get("at_hour")) > num(r["hour_reading"]):
        ch["hour_reading"] = num(a["at_hour"])
    if ch:
        upd(c, "fa_register", r["id"], ch)
    if num(a.get("cost")) and not a.get("capitalise"):
        ins(c, "fa_costs", {"fa_id": r["id"], "date": a["date"], "category": "repairs", "amount": r2(num(a["cost"])),
                            "project_id": r["project_id"], "ref": "MNT %s" % mid, "remarks": a.get("remarks"),
                            "user_id": u["id"], "ts": now()})
    if a.get("capitalise") and num(a.get("cost")):     # major overhaul extends life - NAS 16 para 13
        fa_component_save(c, u, {"row": {"fa_id": r["id"], "name": a.get("remarks") or "Overhaul " + a["date"],
                                         "cost": num(a["cost"]), "in_use_date": a["date"],
                                         "life_hours": num(a.get("life_hours")) or num(r["life_hours"]) / 2,
                                         "replaces": a.get("replaces")}, "post": a.get("post", True)})
    return {"id": mid}


# ───────────────────────── NFRS 16 leases ─────────────────────────
def _lease_calc(L):
    n = int(num(L["term_months"]) * num(L["periods_per_year"] or 12) / 12)
    return F.lease_schedule(num(L["payment"]), n, num(L["rate"]), int(num(L["periods_per_year"] or 12)),
                            bool(L["in_advance"]), num(L["direct_costs"]), int(num(L["term_months"])),
                            bool(L["low_value"]))


@api("fa.lease_save", MODULE, "edit")
def fa_lease_save(c, u, a):
    row = a.get("row") or {}
    need(row, "description", "start_date", "term_months", "payment", "rate")
    keep = {k: row.get(k) for k in ("description", "lessor", "party_id", "project_id", "equipment_id", "start_date",
                                    "term_months", "payment", "periods_per_year", "rate", "in_advance", "direct_costs",
                                    "low_value", "remarks")}
    keep["periods_per_year"] = int(num(keep.get("periods_per_year")) or 12)
    keep["in_advance"] = 1 if keep.get("in_advance") else 0
    keep["low_value"] = 1 if keep.get("low_value") else 0
    if num(keep["rate"]) > 1:
        keep["rate"] = num(keep["rate"]) / 100.0              # typed as 12 rather than 0.12
    s = _lease_calc(keep)
    keep.update({"exempt": 1 if s["exempt"] else 0, "rou": s.get("rou_asset", 0), "liability": s.get("liability", 0)})
    if row.get("id"):
        L = get(c, "fa_leases", int(row["id"]), "Lease")
        if L["status"] == "active":
            raise ApiError("This lease is recognised. Record a modification as a new lease line.")
        upd(c, "fa_leases", L["id"], keep)
        lid = L["id"]
    else:
        keep["no"] = "LSE-%03d" % (num(val(c, "SELECT COUNT(*) FROM fa_leases", ())) + 1)
        keep["status"] = "draft"
        lid = ins(c, "fa_leases", keep)
    return {"id": lid, "exempt": s["exempt"], "rou": keep["rou"], "liability": keep["liability"]}


@api("fa.lease_list", MODULE, "view")
def fa_lease_list(c, u, a):
    rows = []
    for L in q(c, "SELECT * FROM fa_leases ORDER BY start_date DESC"):
        d = dict(L)
        d["balance"] = r2(val(c, "SELECT closing FROM fa_lease_rows WHERE lease_id=? AND voucher_id IS NOT NULL "
                                 "ORDER BY period DESC LIMIT 1", (L["id"],), L["liability"]))
        d["periods_posted"] = val(c, "SELECT COUNT(*) FROM fa_lease_rows WHERE lease_id=? AND voucher_id IS NOT NULL",
                                  (L["id"],))
        rows.append(d)
    return {"rows": rows}


@api("fa.lease_get", MODULE, "view")
def fa_lease_get(c, u, a):
    L = get(c, "fa_leases", int(a["id"]), "Lease")
    rows = [dict(x) for x in q(c, "SELECT * FROM fa_lease_rows WHERE lease_id=? ORDER BY period", (L["id"],))]
    return {"lease": dict(L), "rows": rows or _lease_calc(dict(L)).get("rows", [])}


def _add_months(d, m):
    d = date.fromisoformat(d[:10])
    y, mo = divmod(d.month - 1 + m, 12)
    return month_end("%04d-%02d-01" % (d.year + y, mo + 1))


@api("fa.lease_recognise", MODULE, "approve")
def fa_lease_recognise(c, u, a):
    """Day one: Dr right-of-use asset / Cr lease liability (and direct costs)."""
    L = get(c, "fa_leases", int(a["id"]), "Lease")
    if L["status"] != "draft":
        raise ApiError("Already recognised.")
    if L["exempt"]:
        upd(c, "fa_leases", L["id"], {"status": "active"})
        return {"exempt": True, "note": "Short-term / low-value: rentals are expensed as billed."}
    assert_open(c, u, L["start_date"])
    s = _lease_calc(dict(L))
    lines = [{"role": "rou_asset", "debit": s["rou_asset"], "narration": L["description"]},
             {"role": "lease_liability", "credit": s["liability"], "narration": "PV of lease payments"}]
    if num(L["direct_costs"]):
        lines.append({"role": "bank", "credit": r2(num(L["direct_costs"])), "narration": "Initial direct costs"})
    vid = _post(c, u, {"date": L["start_date"], "type": "journal", "project_id": L["project_id"], "source": "fa_lease",
                       "source_id": L["id"], "narration": "NFRS 16 recognition %s %s" % (L["no"], L["description"])},
                lines)
    step = 12 // int(L["periods_per_year"] or 12)
    for x in s["rows"]:
        ins(c, "fa_lease_rows", {"lease_id": L["id"], "period": x["period"],
                                 "date": _add_months(L["start_date"], step * x["period"] - 1),
                                 "opening": x["opening"], "interest": x["interest"], "payment": x["payment"],
                                 "closing": x["closing"], "rou_dep": x["rou_dep"]})
    upd(c, "fa_leases", L["id"], {"status": "active", "voucher_id": vid})
    return {"voucher_id": vid, "rou": s["rou_asset"], "periods": len(s["rows"])}


@api("fa.lease_post_month", MODULE, "approve")
def fa_lease_post_month(c, u, a):
    """Interest and right-of-use depreciation for every lease period falling due up to the month end.
    The rental payment itself is paid through Payments against the lessor and debited to the liability."""
    month = (a.get("month") or today())[:7]
    end = month_end(month + "-01")
    assert_open(c, u, end)
    n = 0
    for x in q(c, "SELECT r.*, l.project_id, l.no, l.description FROM fa_lease_rows r JOIN fa_leases l "
                  "ON l.id=r.lease_id WHERE r.voucher_id IS NULL AND r.date<=? AND l.status='active' "
                  "ORDER BY r.date", (end,)):
        vid = _post(c, u, {"date": x["date"], "type": "journal", "project_id": x["project_id"],
                           "source": "fa_lease", "source_id": x["lease_id"],
                           "narration": "%s period %d - interest and ROU depreciation" % (x["no"], x["period"])},
                    [{"role": "lease_interest", "debit": r2(x["interest"])},
                     {"role": "lease_liability", "credit": r2(x["interest"]), "narration": "Interest accrued"},
                     {"role": "depreciation", "debit": r2(x["rou_dep"]), "narration": "Right-of-use depreciation"},
                     {"role": "rou_accum", "credit": r2(x["rou_dep"])}])
        c.execute("UPDATE fa_lease_rows SET voucher_id=? WHERE id=?", (vid, x["id"]))
        n += 1
    return {"month": month, "periods": n}


# ───────────────────────── impairment & disposal ─────────────────────────
def _idle_days(c, r, on):
    if r["kind"] != "equipment" or not _has(c, "logbooks"):
        return 0
    lc = _cols(c, "logsheets")
    last = val(c, "SELECT MAX(l.date) FROM logsheets l JOIN logbooks b ON b.id=l.book_id WHERE b.equipment_id=? "
                  "AND COALESCE(l.hours,0)>0", (r["ref_id"],), None) if {"hours", "date"} <= lc else None
    start = last or r["in_use_date"]
    return (date.fromisoformat(on[:10]) - date.fromisoformat(start[:10])).days if start else 0


@api("fa.impair_scan", MODULE, "view")
def fa_impair_scan(c, u, a):
    """NAS 36 para 9: look for indicators at every reporting date. Idle machines come first."""
    on = a.get("on") or today()
    out = []
    for r in q(c, "SELECT * FROM fa_register WHERE status='active' AND kind='equipment' ORDER BY code"):
        idle = _idle_days(c, r, on)
        if idle >= num(r["idle_threshold"] or 90) or r["lifecycle"] == "idle":
            out.append({"fa_id": r["id"], "code": r["code"], "name": r["name"], "idle_days": idle,
                        "threshold": r["idle_threshold"], "carrying": _nbv(r)})
    return {"on": on, "rows": sorted(out, key=lambda x: -x["idle_days"])}


@api("fa.impair_review", MODULE, "approve")
def fa_impair_review(c, u, a):
    need(a, "id", "date")
    r = _fa(c, a["id"])
    idle = int(a["idle_days"]) if a.get("idle_days") not in (None, "") else _idle_days(c, r, a["date"])
    fv = num(a["fvlcs"]) if a.get("fvlcs") not in (None, "") else None
    viu = num(a["viu"]) if a.get("viu") not in (None, "") else (
        F.value_in_use([num(x) for x in a["cash_flows"]], num(a.get("discount_rate") or 0.12))
        if a.get("cash_flows") else None)
    res = F.impairment_review(_nbv(r), fv, viu, idle, int(num(r["idle_threshold"]) or 90), bool(a.get("damage")),
                              bool(a.get("obsolete")), bool(a.get("market_decline")))
    vid = None
    if res["loss"] > EPS and a.get("post", True):
        assert_open(c, u, a["date"])
        vid = _post(c, u, {"date": a["date"], "type": "journal", "project_id": r["project_id"],
                           "source": "fa_impair", "source_id": r["id"],
                           "narration": "NAS 36 impairment of %s %s" % (r["code"], r["name"])},
                    [{"role": "impairment_loss", "debit": res["loss"]},
                     {"role": "accum_impairment", "credit": res["loss"]}])
        upd(c, "fa_register", r["id"], {"impairment": r2(num(r["impairment"]) + res["loss"])})
    ins(c, "fa_impair", {"fa_id": r["id"], "date": a["date"], "idle_days": idle,
                         "indicators": "; ".join(res["indicators"]), "carrying": _nbv(r), "fvlcs": fv, "viu": viu,
                         "recoverable": res["recoverable"], "loss": res["loss"], "voucher_id": vid, "user_id": u["id"],
                         "remarks": a.get("remarks")})
    res["voucher_id"] = vid
    return res


@api("fa.dispose", MODULE, "approve")
def fa_dispose(c, u, a):
    """Sale or scrap of a register item: takes cost, depreciation and impairment out, books gain/loss."""
    need(a, "id", "date")
    r = _fa(c, a["id"])
    if r["status"] == "disposed":
        raise ApiError("Already disposed.")
    if not r["managed"] and r["kind"] == "asset":
        raise ApiError("This asset is kept by the Asset register - dispose of it there.")
    assert_open(c, u, a["date"])
    res = F.disposal(num(r["cost"]), num(r["accumulated"]), num(a.get("proceeds")), num(a.get("costs_to_sell")),
                     num(r["impairment"]))
    lines = [{"role": "accum_dep", "debit": r2(num(r["accumulated"])), "narration": "Depreciation written back"},
             {"role": "accum_impairment", "debit": r2(num(r["impairment"]))},
             {"role": "fixed_asset", "credit": r2(num(r["cost"])), "narration": "%s %s removed" % (r["code"], r["name"])}]
    if res["net_proceeds"] > EPS:
        lines.append({"role": a.get("into") or "bank", "debit": res["net_proceeds"], "narration": "Sale proceeds"})
    if abs(res["gain"]) > EPS:
        lines.append({"role": "disposal_gain" if res["gain"] > 0 else "disposal_loss",
                      "credit" if res["gain"] > 0 else "debit": abs(res["gain"])})
    vid = _post(c, u, {"date": a["date"], "type": "journal", "project_id": r["project_id"], "source": "fa_dispose",
                       "source_id": r["id"], "narration": "Disposal of %s %s" % (r["code"], r["name"])}, lines)
    upd(c, "fa_register", r["id"], {"status": "disposed", "lifecycle": "dispose", "disposal_date": a["date"],
                                    "disposal_proceeds": num(a.get("proceeds"))})
    if r["kind"] == "equipment" and r["ref_id"] and "status" in _cols(c, "equipment"):
        c.execute("UPDATE equipment SET status='disposed' WHERE id=?", (r["ref_id"],))
    audit(c, u, "dispose", "fa_register", r["id"], res)
    res["voucher_id"] = vid
    return res


# ───────────────────────── reports ─────────────────────────
@api("fa.movement", MODULE, "view")
def fa_movement(c, u, a):
    """The PPE note for the financial statements (NAS 16 para 73): opening, additions, disposals,
    depreciation, impairment, closing - by class."""
    fy, s, e = fy_bounds(c, a.get("fy"), a.get("on"))
    out = {}
    for r in q(c, "SELECT * FROM fa_register"):
        k = r["klass"]
        b = out.setdefault(k, {"klass": k, "name": F.CLASS_POLICY.get(k, (k,))[0], "cost_open": 0, "additions": 0,
                               "disposals": 0, "cost_close": 0, "dep_open": 0, "dep_year": 0, "dep_disposed": 0,
                               "impairment": 0, "dep_close": 0, "nbv_open": 0, "nbv_close": 0})
        dep_year = num(val(c, "SELECT SUM(amount) FROM fa_dep WHERE fa_id=? AND month BETWEEN ? AND ?",
                           (r["id"], s[:7], e[:7])))
        if not r["managed"]:
            dep_year = 0.0
        dep_after = num(val(c, "SELECT SUM(amount) FROM fa_dep WHERE fa_id=? AND month>?", (r["id"], e[:7])))
        acc_close = num(r["accumulated"]) - dep_after
        added = bool(r["in_use_date"] and s <= r["in_use_date"] <= e)
        gone = bool(r["disposal_date"] and s <= r["disposal_date"] <= e)
        existed_open = r["in_use_date"] and r["in_use_date"] < s and not (r["disposal_date"] and r["disposal_date"] < s)
        cost = num(r["cost"])
        if existed_open:
            b["cost_open"] += cost
            b["dep_open"] += acc_close - dep_year
        if added:
            b["additions"] += cost
        if gone:
            b["disposals"] += cost
            b["dep_disposed"] += acc_close
        if (existed_open or added) and not gone:
            b["cost_close"] += cost
            b["dep_close"] += acc_close
            b["impairment"] += num(r["impairment"])
        b["dep_year"] += dep_year
    rows = []
    for b in out.values():
        b["nbv_open"] = b["cost_open"] - b["dep_open"]
        b["nbv_close"] = b["cost_close"] - b["dep_close"] - b["impairment"]
        rows.append({k: (r2(v) if isinstance(v, float) else v) for k, v in b.items()})
    keys = [k for k in rows[0] if k not in ("klass", "name")] if rows else []
    return {"fy": fy, "from": s, "to": e, "rows": sorted(rows, key=lambda x: x["klass"]),
            "totals": {k: r2(sum(x[k] for x in rows)) for k in keys}}


# ───────────────────────── inventory (NAS 2) ─────────────────────────
def _stock_source(c):
    for t in ("stock_ledger", "stock_moves", "stock_tx", "stock_entries", "stock"):
        cols = _cols(c, t)
        if {"material_id"} <= cols and ({"qty"} & cols or {"qty_in"} & cols):
            return t, cols
    return None, set()


@api("fa.inv_analysis", MODULE, "view")
def inv_analysis(c, u, a):
    """ABC by annual consumption value, combined with VED, EOQ and reorder point per material."""
    fy, s, e = fy_bounds(c, a.get("fy"), a.get("on"))
    days = max((date.fromisoformat(e) - date.fromisoformat(s)).days + 1, 1)
    items = a.get("rows")
    if not items:
        t, cols = _stock_source(c)
        items = []
        if t:
            vcol = next((x for x in ("value_out", "amount_out", "value", "amount") if x in cols), None)
            qcol = "qty_out" if "qty_out" in cols else "qty"
            dcol = next((x for x in ("date", "tx_date", "ts") if x in cols), None)
            kind = "AND kind IN ('issue','out')" if "kind" in cols and qcol == "qty" else ""
            sign = "ABS" if qcol == "qty" else ""
            sql = ("SELECT material_id, SUM(%s(%s)) q, SUM(%s(%s)) v FROM %s WHERE %s BETWEEN ? AND ? %s "
                   "GROUP BY material_id") % (sign, qcol, sign, vcol or "0", t, dcol or "'x'", kind)
            for x in q(c, sql, (s, e)):
                items.append({"material_id": x["material_id"], "annual_qty": num(x["q"]), "annual_value": num(x["v"])})
    if not items:
        return {"fy": fy, "rows": [], "note": "No stock movements found for the year."}
    names = {}
    if _has(c, "materials"):
        mc = _cols(c, "materials")
        for m in q(c, "SELECT id, code, name%s FROM materials" % (", unit" if "unit" in mc else "")):
            names[m["id"]] = dict(m)
    ranked = F.abc_inventory([dict(x, id=x["material_id"]) for x in items])
    out = []
    for x in ranked:
        pol = q1(c, "SELECT * FROM inv_policy WHERE material_id=?", (x["material_id"],))
        pol = dict(pol) if pol else {"ved": "E", "lead_days": 7, "order_cost": 0, "carrying_pct": 0.2,
                                     "max_lead_days": None, "safety": None, "allowed_waste_pct": 0.02}
        unit_cost = x["annual_value"] / x["annual_qty"] if x.get("annual_qty") else 0
        daily = (x.get("annual_qty") or 0) / days
        ann = (x.get("annual_qty") or 0) * 365.0 / days
        eo = F.eoq(ann, num(pol["order_cost"]), unit_cost, num(pol["carrying_pct"]) or 0.2) \
            if num(pol["order_cost"]) else {"eoq": None}
        rp = F.reorder_point(daily, num(pol["lead_days"]) or 7, None, pol.get("max_lead_days"), pol.get("safety"))
        m = names.get(x["material_id"], {})
        out.append({"material_id": x["material_id"], "code": m.get("code"), "name": m.get("name"), "unit": m.get("unit"),
                    "annual_qty": r2(x.get("annual_qty")), "annual_value": r2(x["annual_value"]),
                    "unit_cost": r2(unit_cost), "cum_pct": x["cum_pct"], "abc": x["abc"], "ved": pol["ved"],
                    "category": F.ved_policy(x["abc"], pol["ved"] or "E")["category"],
                    "control": F.ved_policy(x["abc"], pol["ved"] or "E")["control"], "eoq": eo["eoq"],
                    "safety_stock": rp["safety_stock"], "reorder_point": rp["reorder_point"],
                    "lead_days": pol["lead_days"]})
    tot = sum(x["annual_value"] for x in out) or 1
    summ = {k: {"items": sum(1 for x in out if x["abc"] == k),
                "value_pct": r2(100 * sum(x["annual_value"] for x in out if x["abc"] == k) / tot)} for k in "ABC"}
    return {"fy": fy, "rows": out, "summary": summ,
            "cost_formula": _setting(c, "stock_cost_formula", "WAVG"),
            "note": "NAS 2 permits FIFO or weighted average; BuildCore's stock engine uses moving weighted average."}


@api("fa.inv_policy_save", MODULE, "edit")
def inv_policy_save(c, u, a):
    row = a.get("row") or {}
    need(row, "material_id")
    if row.get("ved") and row["ved"] not in F.VED:
        raise ApiError("VED must be V, E or D.")
    keep = {k: row.get(k) for k in ("ved", "lead_days", "max_lead_days", "order_cost", "carrying_pct", "safety",
                                    "nrv_rate", "allowed_waste_pct", "remarks") if k in row}
    if q1(c, "SELECT material_id FROM inv_policy WHERE material_id=?", (int(row["material_id"]),)):
        sets = ", ".join("%s=?" % k for k in keep)
        if sets:
            c.execute("UPDATE inv_policy SET %s WHERE material_id=?" % sets, list(keep.values()) + [int(row["material_id"])])
    else:
        keep["material_id"] = int(row["material_id"])
        ins(c, "inv_policy", keep)
    return {"ok": True}


@api("fa.inv_nrv", MODULE, "view")
def inv_nrv(c, u, a):
    """Lower of cost and NRV for each line given (qty, cost rate, selling price / replacement value)."""
    out = []
    for x in a.get("rows") or []:
        res = F.nrv_writedown(num(x["qty"]), num(x["cost_rate"]), num(x["selling_price"]),
                              num(x.get("cost_to_complete")), num(x.get("cost_to_sell")))
        res.update({"material_id": x.get("material_id"), "name": x.get("name")})
        out.append(res)
    total = r2(sum(x["writedown"] for x in out))
    if a.get("post") and total > EPS:
        need(a, "date")
        assert_open(c, u, a["date"])
        vid = _post(c, u, {"date": a["date"], "type": "journal", "source": "inv_nrv",
                           "narration": "NAS 2 write-down of inventory to net realisable value"},
                       [{"role": "inv_writedown_exp", "debit": total}, {"role": "inv_nrv", "credit": total}])
        return {"rows": out, "total": total, "voucher_id": vid}
    return {"rows": out, "total": total}


@api("fa.inv_wastage", MODULE, "view")
def inv_wastage(c, u, a):
    out = []
    for x in a.get("rows") or []:
        w = F.wastage(num(x["issued"]), num(x["used"]), num(x.get("allowed_pct", 0.02)), num(x["rate"]))
        w.update({"name": x.get("name")})
        out.append(w)
    return {"rows": out, "abnormal_total": r2(sum(x["abnormal_value"] for x in out)),
            "note": "Abnormal waste is expensed in the period (NAS 2 para 16a) and excluded from contract cost "
                    "used for the NFRS 15 cost-to-cost percentage."}
