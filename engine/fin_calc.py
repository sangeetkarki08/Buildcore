"""
Time value of money and the ten decision methods (Peterson ch. 14-15). Pure functions.

Cash flows are lists indexed by period 0..n (period 0 = now, negative = money out).
"""
import math


def fp(i, n):            # F/P  single payment compound amount
    return (1 + i) ** n


def pf(i, n):            # P/F  present worth
    return (1 + i) ** -n


def ap(i, n):            # A/P  capital recovery
    if n <= 0:
        return 0.0
    if abs(i) < 1e-12:
        return 1.0 / n
    return i * (1 + i) ** n / ((1 + i) ** n - 1)


def pa(i, n):            # P/A  uniform series present worth
    if abs(i) < 1e-12:
        return float(n)
    return ((1 + i) ** n - 1) / (i * (1 + i) ** n)


def af(i, n):            # A/F  sinking fund
    if abs(i) < 1e-12:
        return 1.0 / n if n else 0.0
    return i / ((1 + i) ** n - 1)


def fa(i, n):            # F/A  uniform series compound amount
    if abs(i) < 1e-12:
        return float(n)
    return ((1 + i) ** n - 1) / i


def npv(i, flows):
    return sum(cf * (1 + i) ** -t for t, cf in enumerate(flows))


def fw(i, flows):
    n = len(flows) - 1
    return sum(cf * (1 + i) ** (n - t) for t, cf in enumerate(flows))


def ae(i, flows):
    """Annual equivalent (equivalent uniform annual worth) over the study period."""
    n = len(flows) - 1
    return npv(i, flows) * ap(i, n)


def irr(flows, lo=-0.99, hi=10.0):
    """Rate of return: the rate where NPV = 0 (bisection; None if no sign change)."""
    f_lo, f_hi = npv(lo, flows), npv(hi, flows)
    if f_lo * f_hi > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        f = npv(mid, flows)
        if abs(f) < 1e-7:
            return mid
        if f_lo * f < 0:
            hi, f_hi = mid, f
        else:
            lo, f_lo = mid, f
    return (lo + hi) / 2


def payback(flows, i=0.0):
    """Periods until the (discounted when i > 0) cumulative cash flow turns positive, with interpolation."""
    cum = 0.0
    for t, cf in enumerate(flows):
        v = cf * (1 + i) ** -t
        prev = cum
        cum += v
        if t > 0 and prev < 0 <= cum:
            return t - 1 + (-prev / v if v else 0)
    return None


def project_balance(i, flows):
    """PB_t = PB_(t-1) x (1 + i) + CF_t: how much is still tied up (negative) or earned (positive)."""
    pb = []
    b = 0.0
    for t, cf in enumerate(flows):
        b = b * (1 + i) + cf if t else cf
        pb.append(b)
    return pb


def capital_recovery(first_cost, salvage, i, n):
    """CR = (P - S)(A/P, i, n) + S i."""
    return (first_cost - salvage) * ap(i, n) + salvage * i


def real_rate(nominal, inflation):
    return (1 + nominal) / (1 + inflation) - 1


def solve_rate(p, f, n):
    """Unknown interest rate for P now and F after n periods."""
    if p <= 0 or f <= 0 or n <= 0:
        return None
    return (f / p) ** (1.0 / n) - 1


def evaluate(flows, marr, reinvest=None):
    """All the methods for one alternative."""
    r = irr(flows)
    return {"npv": npv(marr, flows), "fw": fw(marr, flows), "ae": ae(marr, flows), "irr": r,
            "payback": payback(flows), "discounted_payback": payback(flows, marr),
            "project_balance": project_balance(marr, flows)}


def incremental(a, b, marr):
    """Incremental analysis B - A (B = the costlier alternative)."""
    n = max(len(a), len(b))
    a = a + [0.0] * (n - len(a))
    b = b + [0.0] * (n - len(b))
    d = [y - x for x, y in zip(a, b)]
    r = irr(d)
    return {"flows": d, "npv": npv(marr, d), "irr": r, "choose": "B" if npv(marr, d) > 0 else "A"}


def buy_hire_lease(p):
    """p: hours_year, years, marr (decimal), buy {price, salvage, fixed_year (insurance, tax, storage),
    operating_hour (fuel, repairs, operator)}, hire {rate_hour, min_hours_month, mob_per_year},
    lease {payment_month, term_months, residual_buyout, operating_hour}.
    Returns flows and every measure for each option, cheapest annual cost first."""
    H = float(p.get("hours_year") or 0)
    n = int(p.get("years") or 5)
    i = float(p.get("marr") or 0.12)
    out = []
    b = p.get("buy") or {}
    if b.get("price"):
        flows = [-float(b["price"])]
        for t in range(1, n + 1):
            cf = -(float(b.get("fixed_year") or 0) + float(b.get("operating_hour") or 0) * H)
            if t == n:
                cf += float(b.get("salvage") or 0)
            flows.append(cf)
        out.append(("Buy", flows))
    hi = p.get("hire") or {}
    if hi.get("rate_hour"):
        hours = max(H, float(hi.get("min_hours_month") or 0) * 12)
        flows = [0.0] + [-(float(hi["rate_hour"]) * hours + float(hi.get("mob_per_year") or 0) + float(hi.get("operating_hour") or 0) * H)
                         for _ in range(n)]
        out.append(("Hire", flows))
    le = p.get("lease") or {}
    if le.get("payment_month"):
        term = int(le.get("term_months") or 36)
        flows = [0.0]
        for t in range(1, n + 1):
            months = max(0, min(12, term - 12 * (t - 1)))
            cf = -(float(le["payment_month"]) * months + float(le.get("operating_hour") or 0) * H +
                   float(le.get("fixed_year") or 0))
            if t * 12 >= term > (t - 1) * 12:
                cf -= float(le.get("residual_buyout") or 0)
            if t == n and le.get("residual_buyout"):
                cf += float(le.get("salvage") or 0)
            flows.append(cf)
        out.append(("Lease", flows))
    res = []
    for name, fl in out:
        e = evaluate(fl, i)
        res.append({"option": name, "flows": [round(x, 2) for x in fl], "npv": round(e["npv"], 2),
                    "annual_cost": round(-e["ae"], 2), "cost_per_hour": round(-e["ae"] / H, 2) if H else None})
    res.sort(key=lambda x: x["annual_cost"])
    return res


def economic_life(price, salvages, om_costs, i):
    """EUAC for keeping a machine n = 1..N years: capital recovery with the salvage at year n plus the
    equivalent annual O&M. The economic life is the n with the lowest EUAC."""
    rows = []
    for n in range(1, len(om_costs) + 1):
        s = salvages[n - 1] if n - 1 < len(salvages) else 0.0
        cr = capital_recovery(price, s, i, n)
        pw_om = sum(om_costs[t - 1] * pf(i, t) for t in range(1, n + 1))
        eom = pw_om * ap(i, n)
        rows.append({"year": n, "salvage": round(s, 2), "capital_recovery": round(cr, 2), "om_equivalent": round(eom, 2),
                     "euac": round(cr + eom, 2)})
    best = min(rows, key=lambda r: r["euac"]) if rows else None
    return {"rows": rows, "economic_life": best["year"] if best else None, "min_euac": best["euac"] if best else None}


def replace_or_keep(defender_euac_next, challenger_min_euac):
    return "replace" if defender_euac_next > challenger_min_euac else "keep"


def exp_smooth(series, alpha=0.3):
    if not series:
        return None, []
    f = series[0]
    fit = []
    for x in series:
        fit.append(f)
        f = alpha * x + (1 - alpha) * f
    return f, fit


def moving_avg(series, k=3):
    if not series:
        return None
    w = series[-k:]
    return sum(w) / len(w)
