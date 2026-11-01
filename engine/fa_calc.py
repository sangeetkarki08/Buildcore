"""
BuildCore - fixed asset and equipment accounting engine (pure functions, no database).

Everything the Fixed Assets & Equipment module calculates lives here so that it can be
tested on its own and re-used by reports. Only the Python standard library is used.

Sources (see BuildCore_NFRS_Accounting_Reference.md for full references)
  NAS 16  Property, Plant and Equipment - cost, components, depreciation methods, review, derecognition
  NAS 36  Impairment of Assets - indicators, recoverable amount
  NFRS 16 Leases - right-of-use asset, lease liability, short-term / low-value exemptions
  NAS 2   Inventories - FIFO / weighted average only, NRV, abnormal waste
  NAS 12  Income Taxes - deferred tax on book vs tax base
  Income Tax Act 2058 (Nepal) Schedule 2 - pooled depreciation, 1 / 2/3 / 1/3 rule, 7% repairs
  Peterson, Construction Accounting & Financial Management - equipment cost ledger, hourly
      charge-out rate, allocation to jobs, year-end over/under recovery
  Hinze, Construction Planning & Scheduling - owning & operating cost build-up
  Wang (2022) Construction Machinery & Equipment Management - ABC classification & maintenance levels
  Bajet & Manalo (2025) Asset Management Practices - ISO 55000 lifecycle stages
  Malik & Sharma (2022) Inventory Management - ABC / VED / EOQ / JIT
"""
from datetime import date
from math import sqrt

EPS = 1e-6


def r2(x):
    return round((x or 0) + 0.0, 2)


def _d(x):
    if isinstance(x, date):
        return x
    return date.fromisoformat(str(x)[:10])


def months_between(a, b):
    """Whole months from date a to date b (b after a). 15 Jan -> 14 Feb is 0, -> 15 Feb is 1."""
    a, b = _d(a), _d(b)
    m = (b.year - a.year) * 12 + (b.month - a.month)
    if b.day < a.day:
        m -= 1
    return max(m, 0)


# ════════════════════════════ lifecycle (ISO 55000) ════════════════════════════
LIFECYCLE = [
    ("plan", "Plan / business case", "Need, options, whole-life cost, buy vs hire decision"),
    ("acquire", "Create / acquire", "Purchase, import, commissioning; costs capitalised under NAS 16"),
    ("operate", "Operate", "Deployed on a project, logsheet hours recorded, hire charged"),
    ("maintain", "Maintain", "Preventive / corrective maintenance per ABC class"),
    ("idle", "Idle / standby", "Not deployed - NAS 36 impairment indicator after the idle threshold"),
    ("renew", "Renew / overhaul", "Major overhaul capitalised as a new component"),
    ("dispose", "Dispose / replace", "Sold, scrapped or written off; gain or loss recognised"),
]

# ════════════════════════════ policies ════════════════════════════
METHODS = {
    "SL": "Straight line",
    "WDV": "Written down value (declining balance)",
    "SOY": "Sum of the years' digits",
    "UOP": "Units of production (hour meter)",
    "NONE": "Not depreciated (land, CWIP)",
}

# Income Tax Act 2058, Schedule 2 - depreciation pools
TAX_POOLS = {
    "A": (0.05, "Buildings, structures and similar works of a permanent nature"),
    "B": (0.25, "Computers, data-handling equipment, furniture, fixtures, office equipment"),
    "C": (0.20, "Automobiles, buses and minibuses"),
    "D": (0.15, "Construction and earth-moving equipment and any other depreciable asset not in A, B, C, E"),
    "E": (None, "Intangible assets other than depreciable assets in pools A-D (cost / useful life)"),
}

# Default policy per asset class. Book life/residual are management estimates (NAS 16 para 51
# requires annual review); tax pool is fixed by Schedule 2.
CLASS_POLICY = {
    # class            name                                method life  hours   resid% pool  abc
    "land":           ("Land",                               "NONE", 0,  0,      0.00, None, "C"),
    "building":       ("Buildings and camp structures",      "SL",  20,  0,      0.05, "A",  "C"),
    "temp_structure": ("Temporary site structures",          "SL",   3,  0,      0.00, "A",  "C"),
    "heavy_earth":    ("Excavators, dozers, loaders",        "UOP",  8, 12000,   0.10, "D",  "A"),
    "haulage":        ("Tippers, dumpers, trucks",           "WDV",  7,  0,      0.10, "D",  "B"),
    "crane_lift":     ("Cranes and lifting equipment",       "UOP", 10, 15000,   0.10, "D",  "A"),
    "concrete":       ("Batching plant, mixers, pumps",      "UOP", 10, 20000,   0.05, "D",  "A"),
    "crusher":        ("Crushers and screening plant",       "UOP", 10, 20000,   0.05, "D",  "A"),
    "tunnel":         ("Drill jumbos, shotcrete, ventilation", "UOP", 8, 14000,  0.05, "D",  "A"),
    "compaction":     ("Rollers and compactors",             "UOP",  8, 10000,   0.10, "D",  "B"),
    "generator":      ("Generators and compressors",         "UOP",  8, 20000,   0.05, "D",  "B"),
    "light_vehicle":  ("Pickups, jeeps, motorcycles",        "WDV",  6,  0,      0.10, "C",  "C"),
    "survey_lab":     ("Survey and laboratory instruments",  "SL",   5,  0,      0.00, "D",  "C"),
    "small_tools":    ("Small plant and tools",              "SL",   3,  0,      0.00, "D",  "C"),
    "it_office":      ("Computers and office equipment",     "SL",   4,  0,      0.00, "B",  "C"),
    "furniture":      ("Furniture and fixtures",             "SL",   8,  0,      0.00, "B",  "C"),
    "software":       ("Software and licences",              "SL",   3,  0,      0.00, "E",  "C"),
}

# Components commonly separated under NAS 16 para 43 for heavy equipment
COMPONENT_TEMPLATES = {
    "heavy_earth": [("Base machine", 0.60, "UOP", 12000), ("Engine", 0.15, "UOP", 10000),
                    ("Undercarriage", 0.15, "UOP", 5000), ("Bucket and GET", 0.10, "UOP", 3000)],
    "haulage": [("Chassis and body", 0.75, "WDV", 0), ("Engine and drivetrain", 0.17, "UOP", 12000),
                ("Tyres", 0.08, "UOP", 3000)],
    "crane_lift": [("Structure and boom", 0.70, "UOP", 15000), ("Engine and hydraulics", 0.20, "UOP", 10000),
                   ("Wire ropes and hooks", 0.10, "UOP", 3000)],
    "crusher": [("Structure and chassis", 0.55, "SL", 0), ("Jaw / cone chamber", 0.25, "UOP", 12000),
                ("Screens and belts", 0.20, "UOP", 4000)],
}

# Wang (2022): ABC classes of construction machinery and the management that goes with them
ABC_POLICY = {
    "A": {"share": "About 20% of the fleet", "maintenance": "Level I - planned preventive + condition monitoring",
          "fund_share": 0.70, "repair": "Priority repair, standby or hire arranged immediately",
          "spares": 1.00, "safety_check": "Monthly", "inspect_days": 30, "service_hours": 250},
    "B": {"share": "About 30% of the fleet", "maintenance": "Level II - scheduled preventive",
          "fund_share": 0.20, "repair": "Planned repair within the week",
          "spares": 0.80, "safety_check": "Quarterly", "inspect_days": 90, "service_hours": 500},
    "C": {"share": "About 50% of the fleet", "maintenance": "Level III - run to repair",
          "fund_share": 0.10, "repair": "Repair when convenient",
          "spares": 0.00, "safety_check": "Yearly", "inspect_days": 365, "service_hours": 1000},
}
ABC_CRITERIA = [
    ("workload", "Workload / utilisation"),
    ("impact_other", "Impact on other equipment"),
    ("impact_production", "Impact on production / critical path"),
    ("repair_ease", "Difficulty of repair (hard = high)"),
    ("price", "Purchase price"),
]


# ════════════════════════════ book depreciation ════════════════════════════
def wdv_rate(cost, residual, life):
    """Rate that brings cost down to residual over life (NAS 16 diminishing balance)."""
    if life <= 0 or cost <= 0:
        return 0.0
    if residual <= 0:
        residual = cost * 0.01            # declining balance never reaches zero
    return 1 - (residual / cost) ** (1.0 / life)


def annual_schedule(cost, residual, life, method, hours_by_year=None, life_hours=0, rate=None):
    """Year-by-year book depreciation. Returns a list of dicts year/opening/dep/closing/basis."""
    method = (method or "SL").upper()
    rows, nbv, dep_base = [], float(cost), float(cost) - float(residual)
    if method == "NONE" or life <= 0 and method != "UOP":
        return [{"year": 1, "opening": r2(cost), "dep": 0.0, "closing": r2(cost), "basis": "not depreciated"}]
    years = life if method != "UOP" else max(life, len(hours_by_year or []))
    rate = rate if rate is not None else wdv_rate(cost, residual, life)
    soy_total = life * (life + 1) / 2.0
    for y in range(1, int(years) + 1):
        if method == "SL":
            d, basis = dep_base / life, "%s / %s yrs" % (r2(dep_base), life)
        elif method == "WDV":
            d, basis = nbv * rate, "%.2f%% of %s" % (rate * 100, r2(nbv))
            if y == years:
                d = nbv - residual                  # last year lands exactly on residual
        elif method == "SOY":
            f = (life - y + 1) / soy_total
            d, basis = dep_base * f, "%d/%d of %s" % (life - y + 1, soy_total, r2(dep_base))
        elif method == "UOP":
            hrs = (hours_by_year or [0] * years)[y - 1] if y <= len(hours_by_year or []) else 0
            d = dep_base * hrs / life_hours if life_hours else 0
            basis = "%s hrs x %s/hr" % (hrs, r2(dep_base / life_hours) if life_hours else 0)
        else:
            raise ValueError("Unknown method " + method)
        d = max(0.0, min(d, nbv - residual))
        rows.append({"year": y, "opening": r2(nbv), "dep": r2(d), "closing": r2(nbv - d), "basis": basis})
        nbv -= d
    return rows


def month_dep(cost, residual, life, method, accumulated, months_in_use, hours=0, life_hours=0,
              rate=None, days_fraction=1.0):
    """
    Depreciation for one month of an item that has already been in use for months_in_use months
    before this one, with accumulated depreciation so far. days_fraction pro-rates the first/last
    month (NAS 16 para 55: depreciation begins when the asset is available for use).
    """
    method = (method or "SL").upper()
    nbv = cost - accumulated
    room = max(0.0, nbv - residual)
    if room <= EPS or method == "NONE":
        return 0.0
    dep_base = cost - residual
    if method == "SL":
        d = dep_base / (life * 12) if life else 0
    elif method == "WDV":
        rate = rate if rate is not None else wdv_rate(cost, residual, life)
        d = nbv * rate / 12
    elif method == "SOY":
        y = months_in_use // 12 + 1
        if y > life:
            d = room
        else:
            d = dep_base * (life - y + 1) / (life * (life + 1) / 2.0) / 12
    elif method == "UOP":
        d = dep_base * hours / life_hours if life_hours else 0
        days_fraction = 1.0                          # hours already reflect the part month
    else:
        raise ValueError("Unknown method " + method)
    return r2(min(d * days_fraction, room))


def split_components(cost, klass, template=None):
    """Break a heavy item into NAS 16 components. Rounding difference goes to the first line."""
    tpl = template or COMPONENT_TEMPLATES.get(klass)
    if not tpl:
        return []
    out = [{"name": n, "cost": r2(cost * s), "share": s, "method": m, "life_hours": lh} for n, s, m, lh in tpl]
    out[0]["cost"] = r2(out[0]["cost"] + cost - sum(x["cost"] for x in out))
    return out


def revise_estimate(nbv, new_residual, remaining_life_years=None, remaining_hours=None):
    """NAS 8 / NAS 16 para 51: change in estimate is prospective - spread NBV over what is left."""
    base = max(0.0, nbv - new_residual)
    return {"per_year": r2(base / remaining_life_years) if remaining_life_years else None,
            "per_hour": r2(base / remaining_hours) if remaining_hours else None, "base": r2(base)}


# ════════════════════════════ Nepal tax pools ════════════════════════════
def addition_factor(purchase_date, fy_end):
    """
    Schedule 2 clause 4: an asset added in the first 6 months of the income year (to Poush end)
    counts in full; from Magh to Chaitra end, 2/3; from Baishakh 1 onward, 1/3. The fraction left
    out is not lost - it stays in the pool and is depreciated from the following year.
    """
    left = months_between(purchase_date, fy_end) + 1   # months still to run including the month bought
    if left > 6:
        return 1.0, "full"
    if left > 3:
        return 2.0 / 3.0, "2/3"
    return 1.0 / 3.0, "1/3"


def tax_pool_year(pool, opening, additions, fy_end, disposals=0.0, repairs=0.0, rate=None,
                  pool_empty_after=False):
    """
    One income year of one depreciation pool.
      additions: list of (date, amount)
      disposals: sale proceeds of assets leaving the pool this year
      repairs:   repair & improvement spend on assets of the pool (Sec 16: allowed up to 7% of
                 the depreciation base; any excess is added to the pool's base next year)
    Returns the full working including balancing charge / loss (Sec 14 & Schedule 2).
    """
    rate = TAX_POOLS[pool][0] if rate is None else rate
    adds, add_counted, add_total = [], 0.0, 0.0
    for dt, amt in additions:
        f, lab = addition_factor(dt, fy_end)
        adds.append({"date": str(dt), "amount": r2(amt), "factor": lab, "counted": r2(amt * f)})
        add_counted += amt * f
        add_total += amt
    base = opening + add_counted - disposals
    deferred = add_total - add_counted               # carried into next year's base
    balancing_charge, terminal_loss = 0.0, 0.0
    if base < 0:
        balancing_charge = -base                     # proceeds exceed the pool: taxable gain
        base = 0.0
    repair_allowed = min(repairs, 0.07 * base) if base > 0 else 0.0
    repair_excess = repairs - repair_allowed
    if pool_empty_after and base > 0:
        terminal_loss, dep = base, 0.0               # whole remaining base deducted when pool is emptied
    else:
        dep = base * rate if rate else 0.0
    closing = base - dep - terminal_loss + deferred + repair_excess
    return {"pool": pool, "rate": rate, "opening": r2(opening), "additions": adds, "additions_total": r2(add_total),
            "additions_counted": r2(add_counted), "disposals": r2(disposals), "base": r2(base),
            "depreciation": r2(dep), "deferred_additions": r2(deferred), "repairs": r2(repairs),
            "repairs_allowed": r2(repair_allowed), "repairs_added_to_pool": r2(repair_excess),
            "balancing_charge": r2(balancing_charge), "terminal_loss": r2(terminal_loss), "closing": r2(closing)}


def pool_e_amortisation(cost, life_years, months_held_this_year=12):
    """Pool E: intangible cost divided by useful life, pro-rated for part years."""
    return r2(cost / life_years * months_held_this_year / 12.0) if life_years else 0.0


def deferred_tax(carrying_amount, tax_base, rate=0.25):
    """NAS 12: temporary difference x rate. Positive = deferred tax liability."""
    diff = carrying_amount - tax_base
    return {"carrying": r2(carrying_amount), "tax_base": r2(tax_base), "difference": r2(diff),
            "rate": rate, "dtl": r2(diff * rate) if diff > 0 else 0.0, "dta": r2(-diff * rate) if diff < 0 else 0.0,
            "net": r2(diff * rate)}


# ════════════════════════════ owning & operating cost ════════════════════════════
def hire_rate(cost, residual, life_years, annual_hours, interest_rate=0.10, insurance_tax_pct=0.025,
              vehicle_tax=0.0, repair_pct_of_dep=0.8, fuel_lph=0.0, fuel_price=0.0, lube_pct_of_fuel=0.15,
              tyre_cost=0.0, tyre_life_hours=0.0, operator_hr=0.0, overhead_pct=0.10, idle_allowance=0.0):
    """
    Hourly owning and operating cost (Hinze ch. equipment cost; Peterson equipment ledger).
      Ownership:  depreciation + interest on average investment + insurance/tax/storage + vehicle tax
      Operating:  repairs & maintenance + fuel + lubricants + tyres/wear parts + operator
    The machine's charge-out rate is the total plus overhead, spread over productive hours.
    """
    hrs = max(annual_hours * (1 - idle_allowance), 1)
    dep_yr = (cost - residual) / life_years if life_years else 0
    avg_inv = (cost * (life_years + 1) + residual * (life_years - 1)) / (2.0 * life_years) if life_years else cost
    interest_yr = avg_inv * interest_rate
    ins_yr = avg_inv * insurance_tax_pct + vehicle_tax
    own = {"depreciation": dep_yr / hrs, "interest": interest_yr / hrs, "insurance_tax_storage": ins_yr / hrs}
    fuel = fuel_lph * fuel_price
    op = {"repairs_maintenance": dep_yr * repair_pct_of_dep / hrs, "fuel": fuel, "lubricants": fuel * lube_pct_of_fuel,
          "tyres_wear_parts": tyre_cost / tyre_life_hours if tyre_life_hours else 0.0, "operator": operator_hr}
    own_t, op_t = sum(own.values()), sum(op.values())
    total = own_t + op_t
    return {"hours": r2(hrs), "average_investment": r2(avg_inv),
            "ownership": {k: r2(v) for k, v in own.items()}, "ownership_total": r2(own_t),
            "operating": {k: r2(v) for k, v in op.items()}, "operating_total": r2(op_t),
            "cost_per_hour": r2(total), "overhead": r2(total * overhead_pct),
            "rate_per_hour": r2(total * (1 + overhead_pct)),
            "dry_rate_per_hour": r2((own_t + op["repairs_maintenance"]) * (1 + overhead_pct))}


def true_up(actual_cost, charges):
    """
    Peterson: equipment is charged to jobs at the budget hourly rate during the year; at year end
    the difference between the actual equipment cost and what was charged is spread back over the
    jobs in proportion to what each was charged.
      charges: {job: amount charged}
    """
    charged = sum(charges.values())
    diff = actual_cost - charged
    out, left = {}, r2(diff)
    jobs = sorted(charges)
    for i, j in enumerate(jobs):
        share = r2(diff * charges[j] / charged) if charged else 0.0
        if i == len(jobs) - 1:
            share = r2(left)
        out[j] = share
        left -= share
    return {"actual": r2(actual_cost), "charged": r2(charged), "variance": r2(diff),
            "status": "under-recovered" if diff > EPS else ("over-recovered" if diff < -EPS else "exact"),
            "by_job": out}


# ════════════════════════════ ABC classification ════════════════════════════
def abc_score(scores):
    """Each criterion scored 5 (high), 3 (medium) or 1 (low). Returns the total."""
    tot = 0
    for k, _ in ABC_CRITERIA:
        v = int(scores.get(k) or 1)
        if v not in (1, 3, 5):
            raise ValueError("%s must be scored 5, 3 or 1" % k)
        tot += v
    return tot


def abc_class_by_score(total):
    """Fixed bands for a single machine: 19-25 A, 11-17 B, 5-9 C."""
    return "A" if total >= 19 else ("B" if total >= 11 else "C")


def abc_rank_fleet(items):
    """
    Rank a whole fleet by score (then price) and cut at 20% / 50% as Wang describes.
    items: list of dicts with id, score, price
    """
    ordered = sorted(items, key=lambda x: (-x["score"], -(x.get("price") or 0)))
    n = len(ordered)
    out = {}
    for i, it in enumerate(ordered):
        pos = (i + 1) / n if n else 1
        out[it["id"]] = "A" if pos <= 0.2 + EPS else ("B" if pos <= 0.5 + EPS else "C")
    return out


def maintenance_budget(total_fund, fleet):
    """Split a maintenance fund 70/20/10 across classes, then equally within the class."""
    counts = {"A": 0, "B": 0, "C": 0}
    for f in fleet:
        counts[f["abc"]] += 1
    out = {}
    for f in fleet:
        k = f["abc"]
        out[f["id"]] = r2(total_fund * ABC_POLICY[k]["fund_share"] / counts[k]) if counts[k] else 0.0
    return out


def next_service(last_hour, klass, current_hour):
    iv = ABC_POLICY[klass]["service_hours"]
    due = last_hour + iv
    return {"interval": iv, "due_at": due, "hours_left": r2(due - current_hour), "overdue": current_hour >= due}


# ════════════════════════════ NFRS 16 leases ════════════════════════════
def lease_schedule(payment, n_periods, annual_rate, periods_per_year=12, in_advance=False, direct_costs=0.0,
                   term_months=None, low_value=False):
    """
    Lessee accounting. Returns ROU asset, lease liability and the amortisation table.
    Short-term (12 months or less) and low-value leases may be expensed straight line.
    """
    term = term_months if term_months is not None else n_periods * 12 // periods_per_year
    if term <= 12 or low_value:
        return {"exempt": True, "reason": "short-term" if term <= 12 else "low-value",
                "expense_per_period": r2(payment), "total_expense": r2(payment * n_periods), "rows": []}
    i = annual_rate / periods_per_year
    pv = payment * (1 - (1 + i) ** -n_periods) / i if i else payment * n_periods
    if in_advance:
        pv *= (1 + i)
    liab, rows = pv, []
    rou = pv + direct_costs
    rou_dep = rou / n_periods
    for p in range(1, n_periods + 1):
        opening = liab
        if in_advance:
            liab -= payment
            interest = liab * i
            liab += interest
        else:
            interest = liab * i
            liab = liab + interest - payment
        if p == n_periods:
            liab = 0.0
        rows.append({"period": p, "opening": r2(opening), "interest": r2(interest), "payment": r2(payment),
                     "closing": r2(liab), "rou_dep": r2(rou_dep), "rou_nbv": r2(rou - rou_dep * p)})
    return {"exempt": False, "pv": r2(pv), "rou_asset": r2(rou), "liability": r2(pv),
            "total_interest": r2(sum(r["interest"] for r in rows)), "rows": rows}


# ════════════════════════════ impairment & disposal ════════════════════════════
def impairment_review(carrying, fair_value_less_costs=None, value_in_use=None, idle_days=0, idle_threshold=90,
                      damage=False, obsolete=False, market_decline=False):
    """NAS 36: look for indicators; if any, compare carrying amount with recoverable amount."""
    indicators = []
    if idle_days >= idle_threshold:
        indicators.append("Idle %d days (threshold %d)" % (idle_days, idle_threshold))
    if damage:
        indicators.append("Physical damage")
    if obsolete:
        indicators.append("Technological obsolescence / plan to dispose")
    if market_decline:
        indicators.append("Significant fall in market value")
    vals = [v for v in (fair_value_less_costs, value_in_use) if v is not None]
    recoverable = max(vals) if vals else None
    loss = max(0.0, carrying - recoverable) if (indicators and recoverable is not None) else 0.0
    return {"indicators": indicators, "test_required": bool(indicators), "recoverable": r2(recoverable)
            if recoverable is not None else None, "loss": r2(loss), "carrying_after": r2(carrying - loss)}


def value_in_use(cash_flows, rate):
    """Present value of expected net cash flows (e.g. net hire earnings) plus terminal value last."""
    return r2(sum(cf / (1 + rate) ** (t + 1) for t, cf in enumerate(cash_flows)))


def disposal(cost, accumulated, proceeds, costs_to_sell=0.0, impairment=0.0):
    nbv = cost - accumulated - impairment
    gain = proceeds - costs_to_sell - nbv
    return {"cost": r2(cost), "accumulated": r2(accumulated), "impairment": r2(impairment), "nbv": r2(nbv),
            "net_proceeds": r2(proceeds - costs_to_sell), "gain": r2(gain), "result": "gain" if gain >= 0 else "loss"}


# ════════════════════════════ inventory (NAS 2 + Malik & Sharma) ════════════════════════════
def value_issues(moves, formula="WAVG"):
    """
    moves: list of dicts kind ('in'|'out'), qty, rate (for 'in').
    Returns each issue valued, plus closing qty/value. NAS 2 allows FIFO or weighted average only.
    """
    formula = formula.upper()
    if formula not in ("FIFO", "WAVG"):
        raise ValueError("NAS 2 permits FIFO or weighted average only (LIFO is not allowed)")
    layers, qty, val, out = [], 0.0, 0.0, []
    for m in moves:
        if m["kind"] == "in":
            layers.append([m["qty"], m["rate"]])
            qty += m["qty"]
            val += m["qty"] * m["rate"]
            out.append({"kind": "in", "qty": m["qty"], "rate": r2(m["rate"]), "value": r2(m["qty"] * m["rate"]),
                        "bal_qty": r2(qty), "bal_value": r2(val)})
        else:
            need = m["qty"]
            if need > qty + EPS:
                raise ValueError("Issue of %s exceeds stock %s" % (need, qty))
            if formula == "WAVG":
                rate = val / qty if qty else 0
                cost = need * rate
                layers = [[qty - need, rate]]
            else:
                cost, left = 0.0, need
                while left > EPS:
                    lq, lr = layers[0]
                    take = min(lq, left)
                    cost += take * lr
                    left -= take
                    layers[0][0] -= take
                    if layers[0][0] <= EPS:
                        layers.pop(0)
            qty -= need
            val -= cost
            out.append({"kind": "out", "qty": need, "rate": r2(cost / need if need else 0), "value": r2(cost),
                        "bal_qty": r2(qty), "bal_value": r2(val)})
    return {"rows": out, "closing_qty": r2(qty), "closing_value": r2(val)}


def abc_inventory(items, a_cut=0.70, b_cut=0.90):
    """items: list of dicts id, annual_value. Cumulative 70% A, next 20% B, rest C."""
    tot = sum(i["annual_value"] for i in items) or 1
    run, out = 0.0, []
    for it in sorted(items, key=lambda x: -x["annual_value"]):
        run += it["annual_value"]
        share = run / tot
        prev = (run - it["annual_value"]) / tot
        cls = "A" if prev < a_cut - EPS else ("B" if prev < b_cut - EPS else "C")
        out.append(dict(it, cum_pct=r2(share * 100), abc=cls))
    return out


VED = {"V": "Vital - work stops without it (cement, reinforcement, explosives, critical spares)",
       "E": "Essential - work slows without it (shuttering, admixture, consumables)",
       "D": "Desirable - can wait (stationery, minor tools)"}


def ved_policy(abc, ved):
    """Combined ABC-VED matrix: category I items get the tightest control and safety stock."""
    cat = {("A", "V"): "I", ("A", "E"): "I", ("B", "V"): "I", ("C", "V"): "I",
           ("A", "D"): "II", ("B", "E"): "II", ("C", "E"): "II", ("B", "D"): "III", ("C", "D"): "III"}[(abc, ved)]
    return {"category": cat, "control": {"I": "Weekly review, safety stock mandatory, approval by PM",
                                         "II": "Monthly review, EOQ ordering",
                                         "III": "Quarterly review, order on requisition"}[cat]}


def eoq(annual_demand, order_cost, unit_cost, carrying_pct):
    h = unit_cost * carrying_pct
    q = sqrt(2 * annual_demand * order_cost / h) if h > 0 and annual_demand > 0 else 0.0
    orders = annual_demand / q if q else 0
    return {"eoq": r2(q), "orders_per_year": r2(orders), "ordering_cost": r2(orders * order_cost),
            "carrying_cost": r2(q / 2 * h), "total": r2(orders * order_cost + q / 2 * h)}


def reorder_point(daily_use, lead_days, max_daily_use=None, max_lead_days=None, safety=None):
    if safety is None:
        safety = max(0.0, (max_daily_use or daily_use) * (max_lead_days or lead_days) - daily_use * lead_days)
    return {"safety_stock": r2(safety), "reorder_point": r2(daily_use * lead_days + safety)}


def nrv_writedown(qty, cost_rate, selling_price, cost_to_complete=0.0, cost_to_sell=0.0):
    """NAS 2 para 9: lower of cost and NRV, item by item."""
    nrv = selling_price - cost_to_complete - cost_to_sell
    wd = max(0.0, cost_rate - nrv) * qty
    return {"cost": r2(cost_rate * qty), "nrv_rate": r2(nrv), "writedown": r2(wd), "carrying": r2(cost_rate * qty - wd)}


def wastage(issued_qty, used_in_work_qty, allowed_pct, rate):
    """NAS 2 para 16(a): abnormal waste is expensed, not added to contract cost."""
    allowed = used_in_work_qty * allowed_pct
    actual = issued_qty - used_in_work_qty
    abnormal = max(0.0, actual - allowed)
    return {"actual_waste": r2(actual), "allowed_waste": r2(allowed), "abnormal_qty": r2(abnormal),
            "abnormal_value": r2(abnormal * rate), "normal_value": r2(min(actual, allowed) * rate)}
