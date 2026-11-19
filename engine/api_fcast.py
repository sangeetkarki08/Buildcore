"""BuildCore 2.52 "A complete forecast and one budget" (U3, U4, one budget).

U3 Complete forecast (switch fc_on, off on companies that already had data; accounts approve).  Lines added to the
project position's final cost and value, each shown and explained, never hidden inside items:
  * Site overhead to completion at the monthly average since the project started (current month included) for the
    months left, where that is more than the overhead head already forecasts.
  * Site staff from the staff list (monthly rate x months left) when their salaries are not on the overhead head
    (they land in "Unallocated", which the forecast counted as zero).
  * Preliminaries and temporary works with no budget: their run rate for the months left.
  * Defects-period provision (% of contract value) and demobilisation (% or lump sum), company settings.
  * Price rise on the remaining materials: remaining quantity x material per unit x (latest purchase price - standard
    price).  Can be negative.
  * Liquidated damages expected (forecast finish after the completion date) taken off the forecast value.
  * Unapproved variations shown as "potential", not added.
  * Unit-cost check: items whose actual cost per unit is below 70% or above 130% of the budget / estimate.
  Months left = latest calculated finish (or the completion date) less the date.
U4 Budget from day one: "Make the control budget" builds the draft Original budget from the rate analysis when there
  is none (2.21 import) and fills the overhead head from the staff list and run rate; checks: BOQ items with no
  estimate, estimate below 40% / above 100% of the BOQ rate, analyses with no labour or machine lines, BOQ total
  against the contract value.  Switch fc_draft (off on existing data): until a budget is approved, the CVR, the cost
  to complete and the cost-overrun alert use the draft budget, labelled "draft budget".
One budget: Accounts > Budget vs actual gets a tab "Project control budgets" (control budget, cost, forecast per
  project); ledger budgets stay for head-office overheads.  The Tally plan's separate funds control is not built.
Nothing is posted.  No table is added.
"""
import json
import threading
from datetime import date

import core
from core import ApiError, audit, q, q1, setting, today, val
import api_inventory as inv
from api_inventory import api

VERSION = "2.52.0"
FLAG = "_bco252"
EPS = 1e-6
TIME_UNITS = ("ls", "l.s.", "lump sum", "item", "job", "sum", "month", "months", "p.s.", "ps")


def _CL():
    import api_costlink
    return api_costlink


def _r2(x):
    return round((x or 0) + 0.0, 2)


def _set(c, k, v):
    c.execute("INSERT OR REPLACE INTO settings(key, value) VALUES(?, ?)", (k, str(v)))


def _sf(c, k, d=0.0):
    try:
        v = setting(c, k)
        return float(v) if v not in (None, "") else d
    except (TypeError, ValueError):
        return d


def on(c):
    return setting(c, "fc_on") == "1"


def draft_on(c):
    return setting(c, "fc_draft") == "1"


def _months(a, b):
    if not a or not b or b <= a:
        return 0.0
    return (date.fromisoformat(b[:10]) - date.fromisoformat(a[:10])).days / 30.4375


def finish_of(c, p):
    run = q1(c, "SELECT finish FROM sched_runs WHERE project_id=? ORDER BY id DESC LIMIT 1", (p["id"],))
    try:
        import api_sched
        cd = api_sched.contract_dates(c, p)
    except Exception:
        cd = {"revised": p.get("completion_date") or p.get("end_date")}
    comp = cd.get("revised")
    fin = run["finish"] if run and run["finish"] else comp
    if comp and fin and comp > fin:
        fin = comp
    return fin, comp, cd


# ───────────────────────── U3: the forecast additions ─────────────────────────
def additions(c, pid, asof=None, pos=None):
    pid = int(pid)
    asof = asof or today()
    p = q1(c, "SELECT * FROM projects WHERE id=?", (pid,))
    if not p:
        raise ApiError("Project not found.")
    if pos is None:
        import api_pfp
        pos = api_pfp.position._orig(c, pid, asof) if hasattr(api_pfp.position, "_orig") else api_pfp.position(c, pid, asof)
    fin, comp, cd = finish_of(c, p)
    start = p.get("ntp_date") or p.get("start_date") or asof
    left = _months(asof, fin)
    gone = max(1.0, _months(start, asof))
    items = {x["code"]: x for x in pos["forecast"]["items"]}
    lines = []

    def add(key, label, cost=0.0, value=0.0, basis="", kind="cost"):
        if abs(cost) < 0.5 and abs(value) < 0.5:
            return
        lines.append({"key": key, "label": label, "cost": _r2(cost), "value": _r2(value), "basis": basis, "kind": kind})
    oh = items.get("OH") or {}
    oh_cost, oh_ctc = oh.get("cost") or 0, oh.get("ctc") or 0
    if left > 0 and oh_cost > 0:
        need = oh_cost / gone * left
        if need > oh_ctc + 0.5:
            add("overhead", "Site overhead to completion (run rate)", need - oh_ctc,
                basis="%s a month since the start (%.1f months) x %.1f months left = %s, less %s already forecast" % (
                    _fmt(oh_cost / gone), gone, left, _fmt(need), _fmt(oh_ctc)))
    staff = q(c, "SELECT name, monthly_rate FROM staff WHERE project_id=? AND COALESCE(active,1)=1 AND COALESCE(monthly_rate,0)>0", (pid,))
    una = items.get("UNA") or {}
    monthly = sum(s["monthly_rate"] or 0 for s in staff)
    if staff and left > 0 and (una.get("cost") or 0) > 0 and setting(c, "fc_staff") != "0":
        add("staff", "Site staff to completion (staff list)", monthly * left,
            basis="%d staff, %s a month x %.1f months left; their salaries land in Unallocated, which forecasts nothing" % (
                len(staff), _fmt(monthly), left))
    for code, label in (("PRE", "Preliminaries"), ("TW", "Temporary works")):
        it = items.get(code) or {}
        if left > 0 and (it.get("cost") or 0) > 0 and (it.get("ctc") or 0) < 0.5:
            rr = it["cost"] / gone
            add(code.lower(), "%s to completion (run rate, no budget)" % label, rr * left,
                basis="%s a month x %.1f months left" % (_fmt(rr), left))
    cv = p.get("contract_value") or pos["forecast"].get("value") or 0
    dpct = _sf(c, "fc_defects_pct", 1.0)
    if dpct and cv:
        add("defects", "Defects-period provision", cv * dpct / 100, basis="%g%% of contract value %s" % (dpct, _fmt(cv)))
    damt = _sf(c, "fc_demob_amt", 0)
    dmp = _sf(c, "fc_demob_pct", 0.5)
    if damt or (dmp and cv):
        add("demob", "Demobilisation", damt or cv * dmp / 100,
            basis="lump sum" if damt else "%g%% of contract value" % dmp)
    # price rise on remaining materials
    rise, n = 0.0, 0
    exe = {}
    try:
        exe = _CL().executed_qty(c, pid, asof)
    except Exception:
        pass
    for r in q(c, "SELECT mc.boq_item_id, mc.material_id, mc.qty_per_unit, mc.wastage_pct, m.standard_rate, m.name, "
                  "COALESCE(b.revised_qty, b.qty) bq FROM material_coefficients mc JOIN boq_items b ON b.id=mc.boq_item_id "
                  "JOIN materials m ON m.id=mc.material_id WHERE b.project_id=?", (pid,)):
        rem = max(0.0, (r["bq"] or 0) - (exe.get(r["boq_item_id"], 0) or 0))
        if rem <= EPS or not r["standard_rate"]:
            continue
        last = val(c, "SELECT gl.rate FROM grn_lines gl JOIN grn g ON g.id=gl.grn_id WHERE gl.material_id=? AND g.status='posted' "
                      "ORDER BY g.date DESC, g.id DESC LIMIT 1", (r["material_id"],))
        if not last:
            continue
        d = (last - r["standard_rate"]) * rem * (r["qty_per_unit"] or 0) * (1 + (r["wastage_pct"] or 0) / 100)
        if abs(d) > 0.5:
            rise += d
            n += 1
    if abs(rise) > 0.5:
        add("price_rise", "Price rise on remaining materials" if rise > 0 else "Price fall on remaining materials", rise,
            basis="%d material lines: remaining quantity x material per unit x (latest purchase price - standard price)" % n)
    # LD
    ld = {"days": 0, "amount": 0}
    if fin and comp and fin > comp:
        try:
            import api_sched
            ld = api_sched.ld_exposure(c, p, fin, cd)
        except Exception:
            pass
        if ld.get("amount"):
            add("ld", "Liquidated damages expected", 0, -ld["amount"],
                basis="forecast finish %s is %d days after completion %s%s" % (fin, ld["days"], comp, " (capped)" if ld.get("capped") else ""),
                kind="value")
    # potential (shown only)
    potential = []
    if q1(c, "SELECT 1 FROM sqlite_master WHERE name='variations'"):
        for v in q(c, "SELECT v.no, v.title, v.status, v.est_value, v.var_qty, v.new_rate, COALESCE(b.revised_rate, b.rate) brate FROM variations v "
                      "LEFT JOIN boq_items b ON b.id=v.boq_item_id WHERE v.project_id=? AND COALESCE(v.status,'identified') NOT IN "
                      "('approved','rejected','cancelled','closed')", (pid,)):
            amt = v["est_value"] if v["est_value"] else (v["var_qty"] or 0) * (v["new_rate"] or v["brate"] or 0)
            potential.append({"ref": v["no"], "title": v["title"], "status": v["status"], "amount": _r2(amt)})
    # unit-cost check
    checks = []
    for it in pos["forecast"]["items"]:
        if it.get("basis_kind") == "indirect" or not it.get("qty_physical") or not it.get("qty_total"):
            continue
        done = (it["qty_physical"] or 0) / it["qty_total"] if it["qty_total"] else 0
        if done < 0.2 or not it.get("cost"):
            continue
        actual = it["cost"] / it["qty_physical"]
        bud = None
        try:
            bud = _ru(c, val(c, "SELECT boq_item_id FROM cl_codes WHERE project_id=? AND code=?", (pid, it["code"])))
        except Exception:
            bud = None
        if not bud:
            continue
        ratio = actual / bud
        if ratio < 0.7 or ratio > 1.3:
            checks.append({"code": it["code"], "name": it["name"], "done_pct": round(100 * done, 1), "actual_unit": _r2(actual),
                           "budget_unit": _r2(bud), "ratio": round(ratio, 2),
                           "note": "cost probably missing (bills or issues late)" if ratio < 0.7 else "over the estimate: check the forecast basis"})
    add_cost = _r2(sum(x["cost"] for x in lines))
    add_value = _r2(sum(x["value"] for x in lines))
    eac = _r2(pos["forecast"]["eac"] + add_cost)
    val_ = _r2(pos["forecast"]["value"] + add_value)
    return {"project_id": pid, "as_of": asof, "months_left": round(left, 1), "months_gone": round(gone, 1), "finish": fin,
            "completion": comp, "lines": lines, "add_cost": add_cost, "add_value": add_value,
            "before": {"eac": pos["forecast"]["eac"], "value": pos["forecast"]["value"], "profit": pos["forecast"]["profit"],
                       "margin_pct": pos["forecast"]["margin_pct"]},
            "after": {"eac": eac, "value": val_, "profit": _r2(val_ - eac), "margin_pct": round(100 * (val_ - eac) / val_, 1) if val_ else None},
            "potential": potential, "unit_checks": checks, "switch_on": on(c),
            "settings": {"defects_pct": dpct, "demob_pct": dmp, "demob_amt": damt}}


def _ru(c, bid, u=None):
    """Estimated cost per unit of a BOQ item (rate analysis, before overhead), or None."""
    if not bid:
        return None
    if u is None:
        try:
            u = _CL()._ra_units(c, bid)
        except Exception:
            u = None
    if not isinstance(u, dict):
        return None
    tot = sum(float(u.get(k) or 0) for k in ("L", "M", "E", "O"))
    return tot or None


def _fmt(x):
    return "{:,.0f}".format(x or 0)


def _keep_flags(old, new):
    for k in [k for k in getattr(old, "__dict__", {}) if k.startswith("_bco")]:
        setattr(new, k, getattr(old, k))


def _wrap_position():
    import api_pfp
    cur = api_pfp.position
    if getattr(cur, FLAG, False):
        return

    def position(c, pid, asof=None):
        out = cur(c, pid, asof)
        if not on(c) or out.get("_fc252"):
            return out
        try:
            ad = additions(c, pid, asof or today(), out)
        except Exception:
            return out
        f = out["forecast"]
        f["before_additions"] = {"eac": f["eac"], "value": f["value"], "profit": f["profit"], "margin_pct": f["margin_pct"]}
        f["additions"] = ad["lines"]
        f["cost_to_complete"] = _r2(f["cost_to_complete"] + ad["add_cost"])
        f["eac"], f["value"] = ad["after"]["eac"], ad["after"]["value"]
        f["profit"], f["margin_pct"] = ad["after"]["profit"], ad["after"]["margin_pct"]
        out["_fc252"] = True
        return out
    _keep_flags(cur, position)
    setattr(position, FLAG, True)
    position._orig = cur
    api_pfp.position = position


# ───────────────────────── U4: draft budget until one is approved ─────────────────────────
_DRAFT = {"used": False}


_TL = threading.local()


def _wrap_current_version():
    """2.53 safety: the draft budget is handed to the CVR through a per-thread value, never by swapping a function
    that other requests may be using at the same time."""
    CL = _CL()
    keep = CL.current_version
    if getattr(keep, FLAG, False):
        return

    def current_version(c, pid):
        d = getattr(_TL, "draft", None)
        if d and int(pid) == d[0]:
            return d[1]
        return keep(c, pid)
    _keep_flags(keep, current_version)
    setattr(current_version, FLAG, True)
    current_version._orig = keep
    CL.current_version = current_version


def _wrap_cvr():
    CL = _CL()
    _wrap_current_version()
    cur = CL.cvr
    if getattr(cur, FLAG, False):
        return

    def cvr(c, pid, asof, close=None, acc=None):
        if not draft_on(c) or CL.current_version._orig(c, int(pid)) or CL.original_version(c, int(pid)):
            return cur(c, pid, asof, close, acc)
        dr = CL.draft_version(c, int(pid))
        if not dr:
            return cur(c, pid, asof, close, acc)
        prev = getattr(_TL, "draft", None)
        _TL.draft = (int(pid), dr)
        try:
            rep = cur(c, pid, asof, close, acc)
        finally:
            _TL.draft = prev
        rep = dict(rep)
        rep["budget_basis"] = "draft budget (version %s, not approved)" % (dr.get("version_no") or 1)
        return rep
    _keep_flags(cur, cvr)
    setattr(cvr, FLAG, True)
    cvr._orig = cur
    CL.cvr = cvr
    try:
        import api_ctc as CT
        pc = CT.project_ctc
        if not getattr(pc, FLAG, False):
            def project_ctc(c, pid, asof=None):
                d = pc(c, pid, asof)
                if draft_on(c) and not CL.current_version(c, int(pid)) and not CL.original_version(c, int(pid)) and CL.draft_version(c, int(pid)):
                    for al in d.get("alerts") or []:
                        if al.get("key") in ("cost_overrun", "commitments_high") and "draft budget" not in al["text"]:
                            al["text"] += " (draft budget, not yet approved)"
                    d["budget_basis"] = "draft"
                return d
            _keep_flags(pc, project_ctc)
            setattr(project_ctc, FLAG, True)
            project_ctc._orig = pc
            CT.project_ctc = project_ctc
    except Exception:
        pass


def budget_checks(c, pid):
    CL = _CL()
    p = q1(c, "SELECT * FROM projects WHERE id=?", (pid,))
    boq = q(c, "SELECT id, code, description, unit, COALESCE(revised_qty, qty) qty, COALESCE(revised_rate, rate) rate FROM boq_items "
               "WHERE project_id=? ORDER BY id", (pid,))
    out = {"no_estimate": [], "low": [], "high": [], "no_lab_eq": [], "boq_total": 0.0, "contract_value": p.get("contract_value") or 0}
    for b in boq:
        out["boq_total"] += (b["qty"] or 0) * (b["rate"] or 0)
        if (b["unit"] or "").strip().lower() in TIME_UNITS:
            continue
        try:
            u = CL._ra_units(c, b["id"])
        except Exception:
            u = None
        tot = _ru(c, b["id"], u)
        lab = {"code": b["code"], "name": (b["description"] or "")[:70]}
        if not tot:
            out["no_estimate"].append(dict(lab, value=_r2((b["qty"] or 0) * (b["rate"] or 0))))
            continue
        r = tot / b["rate"] if b["rate"] else None
        if r is not None and r < 0.4:
            out["low"].append(dict(lab, estimate=_r2(tot), rate=b["rate"], pct=round(100 * r)))
        elif r is not None and r > 1.0:
            out["high"].append(dict(lab, estimate=_r2(tot), rate=b["rate"], pct=round(100 * r)))
        if isinstance(u, dict) and not (u.get("L") or 0) and not (u.get("E") or 0):
            out["no_lab_eq"].append(lab)
    out["boq_total"] = _r2(out["boq_total"])
    out["contract_differs"] = bool(out["contract_value"]) and abs(out["boq_total"] - out["contract_value"]) > max(1.0, 0.005 * out["contract_value"])
    return out


def _oh_suggestion(c, pid):
    p = q1(c, "SELECT * FROM projects WHERE id=?", (pid,))
    start = p.get("ntp_date") or p.get("start_date")
    fin, comp, _cd = finish_of(c, p)
    total_m = _months(start, comp or fin) if start else 0
    monthly_staff = val(c, "SELECT SUM(monthly_rate) FROM staff WHERE project_id=? AND COALESCE(active,1)=1", (pid,)) or 0
    oh_cost = 0.0
    try:
        CL = _CL()
        rep = CL.cvr._orig(c, pid, today()) if hasattr(CL.cvr, "_orig") else CL.cvr(c, pid, today())
        for r in rep["rows"]:
            if r["code"] in ("OH", "UNA"):
                oh_cost += r["cost"] or 0
    except Exception:
        pass
    gone = max(1.0, _months(start, today())) if start else 1.0
    monthly = max(monthly_staff, oh_cost / gone)
    return {"months": round(total_m, 1), "monthly_staff": _r2(monthly_staff), "monthly_run_rate": _r2(oh_cost / gone),
            "monthly": _r2(monthly), "amount": _r2(monthly * total_m)}


@api("fc.additions", "project", "view")
def fc_additions(c, u, a):
    core.need(a, "project_id")
    _CL()._check_project(c, u, int(a["project_id"]))
    return additions(c, a["project_id"], a.get("as_of"))


@api("fc.budget_wizard", "project", "view")
def fc_budget_wizard(c, u, a):
    """Checks, and with apply=1: make the draft from the rate analysis (if none) and fill the overhead head."""
    core.need(a, "project_id")
    pid = int(a["project_id"])
    CL = _CL()
    CL._check_project(c, u, pid)
    st = {"original": bool(CL.original_version(c, pid)), "current": bool(CL.current_version(c, pid)),
          "draft": dict(CL.draft_version(c, pid) or {}) or None}
    out = {"state": st, "checks": budget_checks(c, pid), "overhead": _oh_suggestion(c, pid), "draft_switch": draft_on(c)}
    if not a.get("apply"):
        return out
    if st["original"]:
        raise ApiError("The Original budget is already approved. Change the Current budget through a proposed change.")
    if not st["draft"]:
        inv.FUNCS["cl.budget_import"][0](c, u, {"project_id": pid})
    oh = out["overhead"]
    k = q1(c, "SELECT id FROM cl_codes WHERE project_id=? AND code='OH'", (pid,))
    done = []
    if k and oh["amount"] > 0:
        dr = CL.draft_version(c, pid)
        bl = q1(c, "SELECT * FROM cl_budget_lines WHERE version_id=? AND cost_code_id=?", (dr["id"], k["id"]))
        if not bl or bl["placeholder"] or not CL.line_amount(dict(bl)):
            inv.FUNCS["cl.budget_line_save"][0](c, u, {"project_id": pid, "cost_code_id": k["id"], "qty": 1, "unit_other": oh["amount"]})
            done.append("Site overhead %s (%s a month x %s months)" % (_fmt(oh["amount"]), _fmt(oh["monthly"]), oh["months"]))
    out["state"]["draft"] = dict(CL.draft_version(c, pid) or {}) or None
    out["applied"] = done
    audit(c, u, "budget_wizard", "projects", pid, {"filled": done})
    return out


@api("fc.budgets", "accounts", "view")
def fc_budgets(c, u, a):
    """One budget: every active project's control budget against cost and forecast (Budget vs actual tab)."""
    CL = _CL()
    import api_ctc as CT
    out = []
    for p in q(c, "SELECT id, code, name FROM projects WHERE status='active' AND COALESCE(kind,'project') NOT IN ('trading','general') ORDER BY code LIMIT 80"):
        try:
            d = CT.project_ctc(c, p["id"])
            T = d["total"]
        except Exception as e:
            out.append({"code": p["code"], "name": p["name"], "error": str(e)})
            continue
        basis = "approved" if CL.current_version(c, p["id"]) or CL.original_version(c, p["id"]) else (
            "draft" if CL.draft_version(c, p["id"]) else "none")
        bud = T.get("budget_current")
        out.append({"project_id": p["id"], "code": p["code"], "name": p["name"], "basis": basis, "budget": bud, "cost": T["cost"],
                    "committed": T["committed"], "eac": T["eac"], "variance": _r2(bud - T["eac"]) if bud is not None else None,
                    "used_pct": round(100 * T["cost"] / bud, 1) if bud else None})
    return {"projects": out, "draft_switch": draft_on(c)}


@api("fc.settings", "accounts", "view")
def fc_settings(c, u, a):
    return {"fc_on": on(c), "fc_draft": draft_on(c), "defects_pct": _sf(c, "fc_defects_pct", 1.0), "demob_pct": _sf(c, "fc_demob_pct", 0.5),
            "demob_amt": _sf(c, "fc_demob_amt", 0), "staff": setting(c, "fc_staff") != "0"}


@api("fc.save", "accounts", "approve")
def fc_save(c, u, a):
    before = fc_settings(c, u, {})
    for k in ("fc_on", "fc_draft"):
        if k in a:
            _set(c, k, "1" if a[k] else "0")
    if "staff" in a:
        _set(c, "fc_staff", "1" if a["staff"] else "0")
    for k in ("defects_pct", "demob_pct", "demob_amt"):
        if k in a:
            v = float(a[k] or 0)
            if v < 0 or (k.endswith("pct") and v > 20):
                raise ApiError("Use a percentage between 0 and 20, or a positive amount.")
            _set(c, "fc_" + k, v)
    after = fc_settings(c, u, {})
    audit(c, u, "settings", "complete forecast", None, {"before": before, "after": after})
    return after


def init_fcast(c):
    if not q1(c, "SELECT 1 FROM settings WHERE key='fc_on'"):
        used = val(c, "SELECT COUNT(*) FROM vouchers") or val(c, "SELECT COUNT(*) FROM boq_items")
        _set(c, "fc_on", "0" if used else "1")
        _set(c, "fc_draft", "0" if used else "1")
        c.commit()
    _wrap_position()
    _wrap_cvr()
    try:
        import api_safe
        have = {s[0] for s in getattr(api_safe, "SWITCHES", [])}
        if "fc_on" not in have:
            api_safe.SWITCHES.append(("fc_on", "Complete forecast", "Overhead and staff to completion, defects, demobilisation, price rise and LD are added to the forecast.",
                                      lambda v: v == "1", "#/cl/cvr", "accounts approve", 3))
        if "fc_draft" not in have:
            api_safe.SWITCHES.append(("fc_draft", "Draft budget until one is approved", "Cost overrun and budget checks use the draft control budget until it is approved.",
                                      lambda v: v == "1", "#/cl/budget", "accounts approve", 3))
    except Exception:
        pass
