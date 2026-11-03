"""BuildCore 2.42.0 — Honest forecast profit.

Found on SULAV's data (home screen: work in hand 34.30 Cr, forecast profit 51.29 Cr at a 100.0% margin):
  * A BOQ item with no control budget, no rate analysis and no cost booked yet was forecast at zero cost, so all its
    revenue counted as profit. With BOQs entered and no budgets, the whole BOQ was "profit".
  * Work in hand reads the contract value typed on the project; forecast profit reads the BOQ. When they differ the two
    cards contradict each other and nothing said so.
Fix (setting fx_uncosted: 'exclude' by default in every company, 'include' gives the old figures back):
  * project_evm (project overview, control room, insight, home, portfolio, profit analysis ...) counts profit only on items
    that have a cost estimate; revenue without one is reported separately (revenue_without_cost) and the margin is
    worked on the costed revenue only, so it can never read 100% from missing costs.
  * The home screen says how much BOQ has no cost estimate, and warns when a project's BOQ total and contract value differ.
Nothing is posted; no table is changed.
"""
import threading

import core
from core import ApiError, r2, setting, val, q
import api_inventory as inv
from api_inventory import api

VERSION = "2.42.0"
FLAG = "_bco242"
EPS = 0.005
_LOCAL = threading.local()


def _f(x, d=0.0):
    try:
        return float(x) if x not in (None, "") else d
    except (TypeError, ValueError):
        return d


def exclude_on(c):
    return (setting(c, "fx_uncosted") or "exclude") != "include"


def _cache():
    if not hasattr(_LOCAL, "ev"):
        _LOCAL.ev = {}
    return _LOCAL.ev


def adjust(ev):
    """Take revenue with no cost estimate out of the forecast profit (in place)."""
    rows = ev.get("rows") or []
    unc = [r for r in rows if _f(r.get("forecast_revenue")) > EPS and _f(r.get("eac")) <= EPS]
    amt = r2(sum(_f(r["forecast_revenue"]) for r in unc))
    fr = _f(ev.get("forecast_revenue"))
    ev["revenue_without_cost"] = amt
    ev["items_without_cost"] = [r.get("code") for r in unc]
    ev["forecast_revenue_costed"] = r2(fr - amt)
    if not unc:
        return ev
    for r in unc:
        r["forecast_profit"] = 0.0
        r["no_cost_estimate"] = True
    ev["forecast_profit"] = r2(_f(ev.get("forecast_profit")) - amt)
    cov = fr - amt
    ev["forecast_margin"] = round(100 * ev["forecast_profit"] / cov, 1) if cov > EPS else None
    tm = ev.get("tender_margin")
    ev["margin_fade"] = round(tm - ev["forecast_margin"], 1) if tm is not None and ev["forecast_margin"] is not None else None
    ev["forecast_note"] = "%s of revenue has no cost estimate yet (no control budget, rate analysis or cost): it is not counted " \
                          "as profit" % "{:,.0f}".format(amt)
    return ev


def _patch_evm():
    import api_project as P
    if getattr(P.project_evm, FLAG, False):
        return
    orig = P.project_evm

    def project_evm(c, pid, asof):
        ev = orig(c, pid, asof)
        if exclude_on(c):
            adjust(ev)
        else:
            ev.setdefault("revenue_without_cost", 0)
            ev.setdefault("forecast_revenue_costed", ev.get("forecast_revenue"))
        _cache()[(int(pid), str(asof))] = {"boq": _f(ev.get("forecast_revenue")), "costed": _f(ev.get("forecast_revenue_costed")),
                                           "without": _f(ev.get("revenue_without_cost"))}
        return ev
    for k in [k for k in getattr(orig, "__dict__", {}) if k.startswith("_bco")]:
        setattr(project_evm, k, getattr(orig, k))
    setattr(project_evm, FLAG, True)
    project_evm._orig = orig
    P.project_evm = project_evm


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


def _w_overview(orig):
    def overview(c, u, a):
        _LOCAL.ev = {}
        res = orig(c, u, a)
        try:
            K = res.get("kpis") or {}
            rows = [r for r in res.get("projects") or [] if not r.get("error")]
            t = core.today()
            boq = costed = without = 0.0
            mism = []
            for r in rows:
                x = _cache().get((int(r["id"]), t))
                if not x:
                    continue
                boq += x["boq"]
                costed += x["costed"]
                without += x["without"]
                r["revenue_without_cost"] = r2(x["without"])
                r["boq_value"] = r2(x["boq"])
                cv = _f(val(c, "SELECT contract_value FROM projects WHERE id=?", (r["id"],)))
                if abs(x["boq"] - cv) > max(1.0, 0.01 * max(x["boq"], cv)):
                    mism.append({"code": r["code"], "contract_value": r2(cv), "boq": r2(x["boq"])})
            if "forecast_profit" in K:
                K["revenue_without_cost"] = r2(without)
                K["revenue_costed"] = r2(costed)
                K["boq_value"] = r2(boq)
                K["value_mismatch"] = mism
                if exclude_on(c):
                    K["forecast_margin"] = round(100 * _f(K["forecast_profit"]) / costed, 1) if costed > EPS else None
        except Exception:
            pass
        return res
    return overview


@api("fx.settings")
def fx_settings(c, u, a):
    return {"uncosted": "include" if not exclude_on(c) else "exclude", "version": VERSION}


@api("fx.settings_save", "accounts", "approve")
def fx_settings_save(c, u, a):
    v = a.get("uncosted")
    if v not in ("include", "exclude"):
        raise ApiError("Choose include or exclude.")
    c.execute("INSERT OR REPLACE INTO settings(key, value) VALUES('fx_uncosted', ?)", (v,))
    core.audit(c, u, "settings", "fx_uncosted", 0, {"value": v})
    return fx_settings(c, u, {})


def init_fcfix(c):
    c.execute("INSERT OR IGNORE INTO settings(key, value) VALUES('fx_uncosted', 'exclude')")
    c.commit()
    _patch_evm()
    _wrap("insight.overview", _w_overview)
