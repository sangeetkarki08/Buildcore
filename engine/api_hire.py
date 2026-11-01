"""
Machine hire rate sheets (BuildCore 2.16) - the hourly hire charge of a machine worked out the way the
Department of Roads does it.

Basis
  * DoR "Norms for Rate Analysis of Road and Bridge Works", general guideline 1.C(ii): the hire charge of equipment
    "shall include ownership charges and operation charges (fuel component + crew component + maintenance component)".
  * DoR Mechanical Branch "Guideline for Estimating Equipment Ownership and Operating Costs" (amendment 2077-12-32):
        ownership / year  = depreciation (P - S) / N + interest + insurance + taxes / licence + storage
        ownership / hour  = ownership per year / working hours per year (h)
        repair & maint.   = RF x P / H            (H = N x h, the useful life in hours)
        servicing (lube)  = SF x P / H
        fuel / hour       = SFC (litre per hp-hour) x hp x load factor x time factor x fuel rate (without VAT)
        crew / hour       = hours of crew per machine hour x daily wage x 30 / (8 x 26)
        special wear      = blades, teeth, cutting edges, per hour
        tyres             = tyre set cost / tyre life in hours (P is taken without the tyres)
    In the DoR sample sheets the interest is 10 % of P / N; a "standard average investment" option
    ((P (N+1) + S (N-1)) / 2N) is also offered.

The 24 sample machines carry the DoR sample-sheet parameters. Their purchase prices are the 2077 guideline
examples and must be replaced with a current quotation before use - the sheet says so on every line.
"""
import base64
import json

from core import ApiError, audit, can, ins, now, num, q, q1, r2, today, upd, val
from api_inventory import api

VERSION = "2.16.0"
MOD = "masters"

SCHEMA = """
CREATE TABLE IF NOT EXISTS mh_sheets(id INTEGER PRIMARY KEY, code TEXT, name TEXT, capacity TEXT, category TEXT,
  params TEXT, res_code TEXT, equipment_id INTEGER, book_id INTEGER, rate REAL, breakdown TEXT, source TEXT,
  active INTEGER DEFAULT 1, remarks TEXT, created_by INTEGER, ts TEXT, updated TEXT);
CREATE TABLE IF NOT EXISTS mh_meta(k TEXT PRIMARY KEY, v TEXT)
"""

DOR_SRC = "DoR guideline for equipment ownership & operating cost (amendment 2077-12-32), sample sheet"
PRICE_NOTE = "Purchase price is the 2077 guideline example - enter today's quotation"

# name, capacity, P, tyres (no, each), N, h, S, RF, SF, hp, SFC, LF, TF, skilled crew h/h, helper h/h, special wear / h, res code
DOR_SAMPLES = [
    ("Batching / mixing plant", "15-20 cum/hr", 4400000, (0, 0), 20, 1000, 440000, 0.40, 0.20, 60, 0.16, 0.80, 0.80, 1, 2, 0, "E-NRM-BPL", 1.0),
    ("Bitumen pressure distributor", "1750 sqm/hr", 6500000, (6, 40000), 20, 1000, 650000, 0.40, 0.20, 100, 0.16, 0.80, 0.80, 1, 1, 0, "E-NRM-BDS", 0),
    ("Bitumen boiler, oil fired", "1500 litre", 500000, (0, 0), 20, 750, 50000, 0.25, 0.10, 25, 0.16, 0.70, 0.70, 0, 1, 0, "E-NRM-BBL", 0),
    ("Concrete pump", "30-40 cum/hr", 400000, (0, 0), 10, 800, 40000, 0.20, 0.10, 25, 0.16, 0.90, 0.85, 1, 1, 0, "", 0),
    ("Concrete mixer", "0.4 cum", 400000, (0, 0), 15, 1000, 40000, 0.40, 0.10, 5, 0.60, 0.80, 0.80, 0, 1, 0, "E-NRM-MIX", 0),
    ("Crane", "3 t", 6500000, (4, 30000), 20, 750, 650000, 0.40, 0.25, 75, 0.16, 0.75, 0.75, 1, 1, 0, "", 0),
    ("Dozer (Komatsu D53E class)", "130 hp", 15000000, (0, 0), 15, 1000, 1500000, 0.55, 0.33, 130, 0.16, 0.85, 0.80, 1, 0, 80, "E-NRM-DOZ", 0),
    ("Front end loader (WA95 class)", "60 / 25 cum/hr", 6500000, (4, 75000), 15, 1000, 650000, 0.55, 0.33, 90, 0.16, 0.85, 0.80, 1, 0, 0, "E-NRM-LDR", 0),
    ("Hot mix plant", "40 t/hr", 6500000, (0, 0), 20, 750, 650000, 0.40, 0.25, 60, 0.16, 0.80, 0.90, 1, 2, 0, "E-NRM-HMP", 0),
    ("Hydraulic excavator", "1 cum bucket", 9000000, (0, 0), 12, 1500, 900000, 0.55, 0.33, 150, 0.16, 0.75, 0.80, 1, 0, 26.67, "E-NRM-EXC", 0),
    ("Mastic cooker", "1 t/hr", 800000, (0, 0), 15, 1000, 80000, 0.30, 0.10, 10, 0.40, 0.80, 0.90, 1, 1, 0, "E-DOR-0035", 0),
    ("Mechanical broom, hydraulic", "1250 sqm/hr", 3500000, (4, 25000), 15, 1000, 350000, 0.30, 0.15, 25, 0.40, 0.80, 0.80, 1, 0, 0, "E-NRM-BRM", 0),
    ("Motor grader (GD300A class)", "120 hp", 12000000, (6, 60000), 15, 1000, 1200000, 0.33, 0.33, 120, 0.10, 0.85, 0.85, 1, 0, 0, "E-NRM-GRD", 0),
    ("Mobile slurry seal machine", "2700 sqm/hr", 2500000, (4, 20000), 15, 1000, 250000, 0.40, 0.20, 70, 0.12, 0.85, 0.85, 1, 1, 0, "", 0),
    ("Paver finisher, mechanical", "100 t/hr", 9000000, (4, 20000), 15, 1000, 900000, 0.40, 0.20, 160, 0.06, 0.85, 0.85, 1, 1, 0, "E-NRM-PAV", 0),
    ("Piling rig with bentonite pump", "2 m/hr", 40000000, (0, 0), 10, 3000, 4000000, 0.20, 0.20, 160, 0.10, 0.70, 0.70, 1, 1, 0, "E-NRM-PIL", 0),
    ("Pneumatic tyred roller", "25 cum/hr", 6000000, (8, 40000), 20, 750, 600000, 0.25, 0.15, 80, 0.16, 0.80, 0.80, 1, 0, 0, "E-NRM-RPN", 0),
    ("Hydraulic jack with pump", "-", 400000, (0, 0), 10, 500, 40000, 0.25, 0.10, 10, 0.16, 0.90, 0.85, 0, 1, 0, "", 0),
    ("Road marking machine", "100 sqm/hr", 500000, (0, 0), 10, 600, 50000, 0.25, 0.10, 10, 0.16, 0.90, 0.90, 1, 0, 0, "", 0),
    ("Smooth wheeled roller 8 t", "70 / 25 cum/hr", 4000000, (0, 0), 15, 2000, 400000, 0.30, 0.10, 60, 0.16, 0.75, 0.75, 1, 0, 0, "E-NRM-RSM", 0),
    ("Tipper truck 8 t", "5.5 cum", 3500000, (6, 20000), 15, 2000, 350000, 0.40, 0.20, 100, 0.16, 0.65, 0.65, 1, 1, 0, "E-NRM-TIP", 0),
    ("Tractor with ripper", "50 hp", 2000000, (4, 25000), 15, 2000, 200000, 0.40, 0.20, 50, 0.16, 0.75, 0.75, 1, 1, 0, "E-NRM-TRC", 0),
    ("Vibratory roller 10 t", "10 t", 5000000, (2, 40000), 20, 750, 500000, 0.40, 0.20, 100, 0.16, 0.70, 0.65, 1, 0, 0, "E-NRM-RVB", 0),
    ("Water tanker 6 kl", "6 kl", 3000000, (6, 25000), 20, 750, 300000, 0.30, 0.20, 100, 0.12, 0.60, 0.60, 1, 0, 0, "E-NRM-WTK", 0),
    ("Crane, rough terrain 10 t", "10 t", 9000000, (6, 50000), 20, 750, 900000, 0.40, 0.25, 180, 0.10, 0.75, 0.75, 1, 1, 0, "", 0),
]

DEFAULTS = {"purchase": 0, "tyre_no": 0, "tyre_cost": 0, "tyre_life_h": 3000, "life_years": 15, "hours_year": 1000,
            "salvage": 0, "salvage_pct": 10, "interest_pct": 10, "interest_basis": "dor", "insurance_pct": 1, "tax_pct": 1,
            "storage_pct": 0, "rf": 0.4, "sf": 0.2, "fuel": "diesel", "hp": 0, "sfc": 0.16, "load_factor": 0.8,
            "time_factor": 0.8, "fuel_lph": None, "fuel_rate": None, "fuel_ex_vat": 1, "kwh_per_h": 0, "power_rate": 0,
            "skilled_h": 1, "helper_h": 0, "skilled_day": None, "helper_day": None, "special_wear_h": 0,
            "other_h": 0, "overhead_pct": 0, "include_crew": 1}


def init_hire(c):
    for st in SCHEMA.strip().split(";"):
        if st.strip():
            c.execute(st)
    if not c.execute("SELECT 1 FROM mh_meta WHERE k='seed_dor_2077'").fetchone():
        for s in DOR_SAMPLES:
            (name, cap, P, (tn, tc), N, h, S, RF, SF, hp, SFC, LF, TF, sk, hl, sw, res, storage) = s
            p = dict(DEFAULTS)
            p.update({"purchase": P, "tyre_no": tn, "tyre_cost": tc, "life_years": N, "hours_year": h, "salvage": S,
                      "rf": RF, "sf": SF, "hp": hp, "sfc": SFC, "load_factor": LF, "time_factor": TF, "skilled_h": sk,
                      "helper_h": hl, "special_wear_h": sw, "storage_pct": storage, "fuel": "diesel"})
            c.execute("INSERT INTO mh_sheets(code, name, capacity, category, params, res_code, source, active, remarks, ts, updated) "
                      "VALUES(?,?,?,?,?,?,?,1,?,?,?)",
                      ("DOR-%02d" % (DOR_SAMPLES.index(s) + 1), name, cap, "DoR sample", json.dumps(p), res or None, DOR_SRC,
                       PRICE_NOTE, now(), now()))
        c.execute("INSERT OR REPLACE INTO mh_meta(k, v) VALUES('seed_dor_2077', ?)", (now(),))


# ───────────────────────── the calculation ─────────────────────────
def _f(p, k):
    v = p.get(k)
    if v in (None, ""):
        v = DEFAULTS.get(k)
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def calc(p, prices=None):
    """Hourly hire rate from the sheet parameters. prices: fuel / labour rates from the rate book when the sheet
    leaves them blank. Returns lines (label, per hour, working) and totals."""
    prices = prices or {}
    P_gross = _f(p, "purchase")
    tyres = _f(p, "tyre_no") * _f(p, "tyre_cost")
    P = max(P_gross - tyres, 0)
    N = _f(p, "life_years")
    h = _f(p, "hours_year")
    if P_gross <= 0 or N <= 0 or h <= 0:
        raise ApiError("Enter the purchase price, the life in years and the working hours per year.")
    S = _f(p, "salvage") if p.get("salvage") not in (None, "", 0, "0") else P * _f(p, "salvage_pct") / 100
    H = N * h
    notes = []
    dep = (P - S) / N
    ir = _f(p, "interest_pct") / 100
    if (p.get("interest_basis") or "dor") == "avg":
        inv = (P * (N + 1) + S * (N - 1)) / (2 * N)
        inv_txt = "average investment (P(N+1)+S(N-1))/2N = %s" % _m(inv)
    else:
        inv = P / N
        inv_txt = "P / N = %s (as in the DoR sample sheets)" % _m(inv)
    interest = ir * inv
    ins_ = P * _f(p, "insurance_pct") / 100
    tax = P * _f(p, "tax_pct") / 100
    sto = P * _f(p, "storage_pct") / 100
    own_year = dep + interest + ins_ + tax + sto
    lines = []

    def add(group, label, amt, how):
        lines.append({"group": group, "label": label, "per_hour": r2(amt), "how": how})
    add("Ownership", "Depreciation", dep / h, "(%s - %s) / %g years / %g h" % (_m(P), _m(S), N, h))
    add("Ownership", "Interest", interest / h, "%g%% of %s / %g h" % (ir * 100, inv_txt, h))
    add("Ownership", "Insurance", ins_ / h, "%g%% of %s / %g h" % (_f(p, "insurance_pct"), _m(P), h))
    add("Ownership", "Taxes, licence, registration", tax / h, "%g%% of %s / %g h" % (_f(p, "tax_pct"), _m(P), h))
    if sto:
        add("Ownership", "Storage", sto / h, "%g%% of %s / %g h" % (_f(p, "storage_pct"), _m(P), h))
    rm = _f(p, "rf") * P / H
    add("Operating", "Repair & maintenance", rm, "RF %g x %s / %g h life" % (_f(p, "rf"), _m(P), H))
    sv = _f(p, "sf") * P / H
    add("Operating", "Servicing - oil, grease, filters", sv, "SF %g x %s / %g h life" % (_f(p, "sf"), _m(P), H))
    fuel = (p.get("fuel") or "diesel").lower()
    fuel_cost = 0.0
    if fuel == "electric":
        kwh, pr = _f(p, "kwh_per_h"), _f(p, "power_rate")
        if kwh and not pr:
            notes.append("Enter the electricity rate per unit.")
        fuel_cost = kwh * pr
        add("Operating", "Electricity", fuel_cost, "%g kWh x Rs %g" % (kwh, pr))
    elif fuel != "none":
        rate = p.get("fuel_rate")
        src = "entered"
        if rate in (None, ""):
            rate = prices.get(fuel)
            src = "rate book"
        rate = float(rate or 0)
        if not rate:
            notes.append("No %s rate - enter it on the sheet or in the rate book." % fuel)
        ex = rate / 1.13 if int(_f(p, "fuel_ex_vat")) else rate
        if p.get("fuel_lph") not in (None, "", 0, "0"):
            lph = _f(p, "fuel_lph")
            how_l = "%g litre/h (entered)" % lph
        else:
            lph = _f(p, "sfc") * _f(p, "hp") * _f(p, "load_factor") * _f(p, "time_factor")
            how_l = "SFC %g x %g hp x LF %g x TF %g = %.2f litre/h" % (_f(p, "sfc"), _f(p, "hp"), _f(p, "load_factor"), _f(p, "time_factor"), lph)
        fuel_cost = lph * ex
        add("Operating", "Fuel (%s)" % fuel, fuel_cost, "%s x Rs %.3f (%s%s)" % (how_l, ex, src, ", VAT taken out: /1.13" if int(_f(p, "fuel_ex_vat")) else ""))
    tyre_h = tyres / _f(p, "tyre_life_h") if tyres and _f(p, "tyre_life_h") else 0
    if tyres:
        add("Operating", "Tyres", tyre_h, "%g x %s = %s / %g h tyre life" % (_f(p, "tyre_no"), _m(_f(p, "tyre_cost")), _m(tyres), _f(p, "tyre_life_h")))
    if _f(p, "special_wear_h"):
        add("Operating", "Special wear items (blades, teeth, edges)", _f(p, "special_wear_h"), "entered per hour")
    if _f(p, "other_h"):
        add("Operating", "Other running cost", _f(p, "other_h"), "entered per hour")
    crew = 0.0
    if int(_f(p, "include_crew")):
        for key, hk, lab in (("skilled", "skilled_h", "Operator / driver (skilled)"), ("helper", "helper_h", "Helper / khalasi (unskilled)")):
            hrs = _f(p, hk)
            if not hrs:
                continue
            day = p.get(key + "_day")
            src = "entered"
            if day in (None, ""):
                day = prices.get(key)
                src = "rate book"
            day = float(day or 0)
            if not day:
                notes.append("No daily wage for the %s - enter it." % key)
            per_h = day * 30 / 208
            crew += hrs * per_h
            add("Crew", lab, hrs * per_h, "%g h x (Rs %s x 30 / (8 x 26) = %.2f / h) (%s)" % (hrs, _m(day), per_h, src))
    own_h = own_year / h
    op_h = rm + sv + fuel_cost + tyre_h + _f(p, "special_wear_h") + _f(p, "other_h")
    sub = own_h + op_h + crew
    oh = sub * _f(p, "overhead_pct") / 100
    if oh:
        add("Overhead", "Overhead / profit %g%%" % _f(p, "overhead_pct"), oh, "on the hourly cost")
    total = sub + oh
    if tyres:
        notes.append("Tyres are costed by their own life; depreciation, interest and repairs use the price without tyres (%s)." % _m(P))
    return {"lines": lines, "ownership_h": r2(own_h), "operating_h": r2(op_h), "crew_h": r2(crew), "overhead_h": r2(oh),
            "rate": r2(total), "rate_day8": r2(total * 8), "ownership_year": r2(own_year), "life_hours": H, "salvage": r2(S),
            "price_net": r2(P), "notes": notes,
            "card": {"ownership_hr": r2(dep / h), "insurance_hr": r2((interest + ins_ + tax + sto) / h), "fuel_hr": r2(fuel_cost + sv),
                     "maintenance_hr": r2(rm + tyre_h + _f(p, "special_wear_h") + _f(p, "other_h")), "operator_hr": r2(crew),
                     "overhead_pct": _f(p, "overhead_pct")}}


def _m(x):
    return "{:,.0f}".format(x or 0)


# ───────────────────────── prices from the rate book ─────────────────────────
PRICE_CODES = {"diesel": "M-NRM-DIESEL", "petrol": "M-NRM-PETROL", "skilled": "L-NRM-SK", "helper": "L-NRM-US"}


def _has(c, t):
    return bool(c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (t,)).fetchone())


def _book(c, bid):
    if bid:
        return int(bid)
    if not _has(c, "rate_books"):
        return None
    return val(c, "SELECT id FROM rate_books WHERE is_default=1 AND active=1 ORDER BY id LIMIT 1", (), None)


def prices(c, bid):
    out, src = {}, {}
    if not _has(c, "res_pool"):
        return out, src
    for k, code in PRICE_CODES.items():
        r = q1(c, "SELECT id, rate, name, unit FROM res_pool WHERE code=?", (code,))
        if not r:
            continue
        br = q1(c, "SELECT rate FROM res_rates WHERE book_id=? AND res_id=?", (bid, r["id"])) if bid else None
        rate = br["rate"] if br and br["rate"] is not None else r["rate"]
        if rate:
            out[k] = rate
            src[k] = {"code": code, "name": r["name"], "unit": r["unit"], "rate": rate, "from": "book" if br else "pool"}
    return out, src


def _row(c, r, pr):
    d = dict(r)
    p = json.loads(d.get("params") or "{}")
    d["params"] = p
    try:
        res = calc(p, pr)
        d["calc"] = res
        d["live_rate"] = res["rate"]
    except ApiError as e:
        d["calc"] = None
        d["live_rate"] = None
        d["error"] = str(e)
    return d


# ───────────────────────── endpoints ─────────────────────────
@api("mh.meta", MOD, "view")
def mh_meta(c, u, a):
    bid = _book(c, a.get("book_id"))
    pr, src = prices(c, bid)
    books = q(c, "SELECT id, code, name, is_default FROM rate_books WHERE active=1 ORDER BY is_default DESC, code") if _has(c, "rate_books") else []
    res = q(c, "SELECT code, name, unit FROM res_pool WHERE type='equipment' AND active=1 ORDER BY code") if _has(c, "res_pool") else []
    eq = q(c, "SELECT id, code, name, purchase_value, residual_value, life_months, est_total_hours, fuel_norm FROM equipment "
              "WHERE COALESCE(active,1)=1 ORDER BY code")
    return {"book_id": bid, "books": books, "prices": src, "resources": res, "equipment": eq, "defaults": DEFAULTS,
            "can_book": can(u, "masters", "edit"), "can_card": can(u, "equipment", "edit")}


@api("mh.list", MOD, "view")
def mh_list(c, u, a):
    bid = _book(c, a.get("book_id"))
    pr, _ = prices(c, bid)
    w = "active=1" if not a.get("all") else "1=1"
    out = []
    for r in q(c, "SELECT * FROM mh_sheets WHERE %s ORDER BY category DESC, name" % w):
        d = _row(c, r, pr)
        cur = None
        if d.get("res_code") and bid and _has(c, "res_pool"):
            cur = val(c, "SELECT rr.rate FROM res_rates rr JOIN res_pool rp ON rp.id=rr.res_id WHERE rr.book_id=? AND rp.code=?", (bid, d["res_code"]), None)
        d["book_rate"] = cur
        d["eq_code"] = val(c, "SELECT code FROM equipment WHERE id=?", (d["equipment_id"],), None) if d.get("equipment_id") else None
        out.append(d)
    return {"rows": out, "book_id": bid}


@api("mh.get", MOD, "view")
def mh_get(c, u, a):
    r = q1(c, "SELECT * FROM mh_sheets WHERE id=?", (int(a["id"]),))
    if not r:
        raise ApiError("Sheet not found.")
    pr, _ = prices(c, _book(c, a.get("book_id")))
    return _row(c, r, pr)


@api("mh.calc", MOD, "view")
def mh_calc(c, u, a):
    pr, src = prices(c, _book(c, a.get("book_id")))
    res = calc(a.get("params") or {}, pr)
    res["prices"] = src
    return res


@api("mh.save", MOD, "edit")
def mh_save(c, u, a):
    r = a.get("row") or {}
    if not (r.get("name") or "").strip():
        raise ApiError("Write the machine name.")
    p = dict(DEFAULTS)
    p.update({k: v for k, v in (r.get("params") or {}).items() if k in DEFAULTS})
    pr, _ = prices(c, _book(c, r.get("book_id")))
    res = calc(p, pr)
    keep = {"name": r["name"].strip(), "capacity": r.get("capacity"), "category": r.get("category") or "Own sheet",
            "params": json.dumps(p), "res_code": r.get("res_code") or None,
            "equipment_id": int(r["equipment_id"]) if r.get("equipment_id") else None,
            "book_id": _book(c, r.get("book_id")), "rate": res["rate"], "breakdown": json.dumps(res["lines"]),
            "remarks": r.get("remarks"), "updated": now()}
    if r.get("id"):
        old = q1(c, "SELECT * FROM mh_sheets WHERE id=?", (int(r["id"]),))
        if not old:
            raise ApiError("Sheet not found.")
        if old["category"] == "DoR sample" and (r.get("purchase_changed") or p["purchase"] != json.loads(old["params"]).get("purchase")):
            keep["remarks"] = r.get("remarks") if r.get("remarks") and r.get("remarks") != PRICE_NOTE else "Price updated %s" % today()
        upd(c, "mh_sheets", old["id"], keep)
        audit(c, u, "save", "mh_sheets", old["id"], {"rate": res["rate"]})
        return {"id": old["id"], "rate": res["rate"]}
    n = (val(c, "SELECT COUNT(*) FROM mh_sheets WHERE code LIKE 'MH-%'", (), 0) or 0) + 1
    keep.update({"code": r.get("code") or "MH-%03d" % n, "source": r.get("source") or "Own sheet", "active": 1, "created_by": u["id"], "ts": now()})
    sid = ins(c, "mh_sheets", keep)
    audit(c, u, "create", "mh_sheets", sid, {"name": keep["name"], "rate": res["rate"]})
    return {"id": sid, "rate": res["rate"]}


@api("mh.archive", MOD, "edit")
def mh_archive(c, u, a):
    r = q1(c, "SELECT * FROM mh_sheets WHERE id=?", (int(a["id"]),))
    if not r:
        raise ApiError("Sheet not found.")
    upd(c, "mh_sheets", r["id"], {"active": 0 if r["active"] else 1, "updated": now()})
    return {"active": 0 if r["active"] else 1}


@api("mh.apply_book", "masters", "edit")
def mh_apply_book(c, u, a):
    """Put the calculated hire rate into the rate book for the linked equipment resource, so every rate analysis
    that uses that machine is priced from this sheet."""
    r = q1(c, "SELECT * FROM mh_sheets WHERE id=?", (int(a["id"]),))
    if not r:
        raise ApiError("Sheet not found.")
    code = a.get("res_code") or r["res_code"]
    if not code:
        raise ApiError("Link the sheet to an equipment resource (E-...) first.")
    res = q1(c, "SELECT id, unit FROM res_pool WHERE code=?", (code,))
    if not res:
        raise ApiError("Resource %s is not in the resource pool." % code)
    bid = _book(c, a.get("book_id"))
    if not bid:
        raise ApiError("Choose a rate book.")
    pr, _ = prices(c, bid)
    out = calc(json.loads(r["params"] or "{}"), pr)
    rate = out["rate"] if (res["unit"] or "hour").lower() in ("hour", "hr", "hrs", "h") else (out["rate_day8"] if (res["unit"] or "").lower() == "day" else None)
    if rate is None:
        raise ApiError("Resource %s is priced per %s - only hour or day resources can take a hire rate." % (code, res["unit"]))
    from api_ra import _set_book_rate
    _set_book_rate(c, bid, res["id"], rate, "Machine hire sheet %s (%s)" % (r["code"], today()))
    upd(c, "mh_sheets", r["id"], {"res_code": code, "book_id": bid, "rate": out["rate"], "updated": now()})
    audit(c, u, "apply", "mh_sheets", r["id"], {"book_id": bid, "res": code, "rate": rate})
    return {"rate": rate, "unit": res["unit"], "book_id": bid, "res_code": code}


@api("mh.apply_card", "equipment", "edit")
def mh_apply_card(c, u, a):
    """Make an equipment rate card (used to cost DPR and logsheet hours) from the sheet."""
    r = q1(c, "SELECT * FROM mh_sheets WHERE id=?", (int(a["id"]),))
    if not r:
        raise ApiError("Sheet not found.")
    eid = int(a.get("equipment_id") or r["equipment_id"] or 0)
    if not eid or not q1(c, "SELECT id FROM equipment WHERE id=?", (eid,)):
        raise ApiError("Choose the machine in the equipment register.")
    pr, _ = prices(c, _book(c, a.get("book_id") or r["book_id"]))
    out = calc(json.loads(r["params"] or "{}"), pr)
    row = dict(out["card"])
    row.update({"equipment_id": eid, "effective_from": a.get("effective_from") or today(),
                "remarks": "From machine hire sheet %s %s: Rs %s / h" % (r["code"], r["name"], out["rate"])})
    cid = ins(c, "equipment_rates", row)
    upd(c, "mh_sheets", r["id"], {"equipment_id": eid, "updated": now()})
    audit(c, u, "create", "equipment_rates", cid, {"from_sheet": r["id"], "rate": out["rate"]})
    return {"id": cid, "rate": out["rate"]}


@api("mh.from_equipment", MOD, "view")
def mh_from_equipment(c, u, a):
    """Start a sheet from a machine in the equipment register."""
    e = q1(c, "SELECT * FROM equipment WHERE id=?", (int(a["equipment_id"]),))
    if not e:
        raise ApiError("Machine not found.")
    p = dict(DEFAULTS)
    if e.get("purchase_value"):
        p["purchase"] = e["purchase_value"]
    if e.get("residual_value"):
        p["salvage"] = e["residual_value"]
    if e.get("life_months"):
        p["life_years"] = round(e["life_months"] / 12.0, 2)
    if e.get("est_total_hours") and p["life_years"]:
        p["hours_year"] = round(e["est_total_hours"] / p["life_years"])
    if e.get("fuel_norm"):
        p["fuel_lph"] = e["fuel_norm"]
    return {"name": e["name"], "equipment_id": e["id"], "params": p,
            "note": "Filled from the register: price, salvage, life, hours and fuel litre / hour. Check RF, SF and crew."}


@api("mh.xlsx", MOD, "view")
def mh_xlsx(c, u, a):
    d = mh_list(c, u, a)
    cols = ["Code", "Machine", "Capacity", "Purchase price", "Tyres", "Life (yr)", "Hours / yr", "Salvage", "RF", "SF", "hp",
            "Fuel litre/h", "Ownership / h", "Operating / h", "Crew / h", "Overhead / h", "Hire rate / h", "Hire rate / 8-h day",
            "Rate-book resource", "Rate now in book", "Source", "Remarks"]
    rows = []
    for r in d["rows"]:
        p, k = r["params"], r.get("calc") or {}
        lph = p.get("fuel_lph") or round(_f(p, "sfc") * _f(p, "hp") * _f(p, "load_factor") * _f(p, "time_factor"), 3)
        rows.append([r["code"], r["name"], r.get("capacity"), _f(p, "purchase"), _f(p, "tyre_no") * _f(p, "tyre_cost"), _f(p, "life_years"),
                     _f(p, "hours_year"), k.get("salvage"), _f(p, "rf"), _f(p, "sf"), _f(p, "hp"), lph, k.get("ownership_h"),
                     k.get("operating_h"), k.get("crew_h"), k.get("overhead_h"), k.get("rate"), k.get("rate_day8"), r.get("res_code"),
                     r.get("book_rate"), r.get("source"), r.get("remarks") or r.get("error")])
    from api_copilot import make_xlsx
    data = make_xlsx("Machine hire rates - ownership + operating (DoR method)", cols, rows)
    return {"filename": "machine_hire_rates.xlsx", "b64": base64.b64encode(data).decode("ascii")}
