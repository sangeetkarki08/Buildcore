"""
One project number (BuildCore 2.39): every screen gives the same cost, value, margin and forecast for a project.

From the review of 2.37 (buildcore/review/AUDIT_ONE_PLATFORM_2.37.md), findings B1 B2 A6 C3, and the plan in
buildcore/2.39/AUDIT_AND_PLAN_2.39.md:
  1. One project position, pfp.position(project_id, as_of): cost to date (posted, waiting, accrued) on the 2.24 cost-link
     definition with own machine cost shared by machine hours; value (certified, measured, billed, earned); margin on
     certified and on earned value; forecast item by item with its basis (PM override, actual after the threshold,
     control budget, rate analysis, actual unit cost, none). The two calculators every screen uses (cvr and
     project_evm) take their headline figures from it; ledger screens keep the ledger and show the position beside it.
     Switch pfp_on: new companies on; updated companies after accounts confirms on CVR > Project position.
  2. Equipment as its own cost centre: EQUIP (a company cost centre like GENERAL), every line carrying its machine.
     From the date in eqcc_from, owned-machine cost and the credit side of machine charges post to EQUIP.
     Machine P&L per machine and Nepali month.
  3. One budget: "create control budget from rate analysis" with a preview and "only items without a line"; the PO
     budget box and the PO approval run the same check (control budget first).
  4. Nepali months for every monthly run (setting run_months): the six runs accept a Nepali month, cover the same days as
     the month close and start the day after the last day already charged.
New tables pfp_confirm and pfp_runs only. No existing row, id or posted voucher is changed or deleted.
"""
import copy
import json
import threading
from datetime import date, timedelta

import core
from core import ApiError, audit, get, ins, now, q, q1, r2, setting, today, upd, val
import api_inventory as inv
from api_inventory import api

VERSION = "2.39.0"
FLAG = "_bco239"
EPS = 0.005

SCHEMA = """
CREATE TABLE IF NOT EXISTS pfp_confirm(id INTEGER PRIMARY KEY, what TEXT, value TEXT, before_json TEXT, after_json TEXT,
  user_id INTEGER, ts TEXT, note TEXT);
CREATE TABLE IF NOT EXISTS pfp_runs(id INTEGER PRIMARY KEY, run TEXT, month TEXT, ref_kind TEXT, ref_id INTEGER,
  project_id INTEGER, from_date TEXT, to_date TEXT, qty REAL, amount REAL, voucher_id INTEGER, user_id INTEGER, ts TEXT);
CREATE INDEX IF NOT EXISTS ix_pfpr ON pfp_runs(run, ref_kind, ref_id, to_date);
"""


def _CL():
    import api_costlink as CL
    return CL


def _P():
    import api_project as P
    return P


def _has(c, t):
    return bool(val(c, "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?", (t,)))


def _f(x, d=0.0):
    try:
        return float(x if x not in (None, "") else d)
    except (TypeError, ValueError):
        return d


def _set(c, k, v):
    c.execute("INSERT OR REPLACE INTO settings(key, value) VALUES(?,?)", (k, str(v)))


def _right(u, module, action):
    return bool(u) and (u.get("role") == "admin" or core.can(u, module, action))


_LOCAL = threading.local()


def on(c):
    f = getattr(_LOCAL, "force", None)
    if f is not None:
        return f
    return setting(c, "pfp_on") == "1"


def nepali_runs(c):
    return (setting(c, "run_months") or "english") == "nepali"


def _wrap(name, factory):
    cur = inv.FUNCS.get(name)
    if not cur or getattr(cur[0], FLAG, False):
        return
    w = factory(cur[0])
    setattr(w, FLAG, True)
    w._orig = cur[0]
    for f in ("_bco219", "_bco220", "_bco221", "_bco223", "_bco238"):
        if getattr(cur[0], f, False):
            setattr(w, f, True)
    inv.FUNCS[name] = (w, cur[1], cur[2], cur[3])


# a result worked out once per request (the connection's change count tells when the data changed)
_MEMO = {}


def _memo_get(c, key):
    tc = getattr(c, "total_changes", None)
    if tc is None:
        return None
    hit = _MEMO.get((id(c), tc) + key)
    return copy.deepcopy(hit) if hit is not None else None


def _memo_put(c, key, value):
    tc = getattr(c, "total_changes", None)
    if tc is None:
        return
    if len(_MEMO) > 400:
        _MEMO.clear()
    _MEMO[(id(c), tc) + key] = copy.deepcopy(value)


# ───────────────────────────── months: one window for runs and for sharing machine cost ─────────────────────────────
def is_bs(m):
    try:
        return int(str(m)[:4]) >= 2070
    except ValueError:
        return False


def window_of(c, m):
    """(from, to) of a month key: a Nepali month (2083-05) covers the same days as the month close; an English month
    (2026-08) its calendar days."""
    CL = _CL()
    if is_bs(m):
        return CL.period_bounds(c, m[:7])
    return m[:7] + "-01", core.month_end(m[:7])


def window_of_date(c, d):
    CL = _CL()
    if nepali_runs(c):
        return CL.period_bounds(c, CL.period_of_date(c, d))
    return d[:8] + "01", core.month_end(d[:7])


def month_label(c, m):
    CL = _CL()
    if is_bs(m):
        frm, to = window_of(c, m)
        return "%s (%s to %s)" % (CL.period_label(m), frm, to)
    return m


# ───────────────────────────── 1a. own machine cost shared by machine hours ─────────────────────────────
def _hours(c, eid, frm, to, cache):
    k = (eid, frm, to)
    if k not in cache:
        cache[k] = {r["project_id"]: _f(r["h"]) for r in q(
            c, "SELECT project_id, SUM(hours) h FROM logsheets WHERE equipment_id=? AND date BETWEEN ? AND ? AND hours>0 "
               "AND project_id IS NOT NULL GROUP BY project_id", (eid, frm, to))}
    return cache[k]


def _share_machine_cost(c, pid, asof, frm, include_waiting, rows, stats=None):
    """Replace the project's own-machine running cost (basis eq_run) by its share of every machine's cost, month by month,
    in proportion to the hours each project logged. A machine with no hours logged in a month keeps its cost where it
    was posted."""
    CL = _CL()
    cache = {}
    ctx = None
    eq_rows = [r for r in rows if r.get("basis") == "eq_run" and r.get("line_id")]
    info = {}
    if eq_rows:
        ids = sorted({r["line_id"] for r in eq_rows})
        for i in range(0, len(ids), 900):
            ch = ids[i:i + 900]
            for x in q(c, "SELECT l.id, l.equipment_id, v.date FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id "
                          "WHERE l.id IN (%s)" % ",".join("?" * len(ch)), ch):
                info[x["id"]] = (x["equipment_id"], x["date"])
    out, moved_out = [], 0.0
    for r in rows:
        if r.get("basis") == "eq_run" and r.get("line_id") in info:
            eid, d = info[r["line_id"]]
            if eid:
                w0, w1 = window_of_date(c, d)
                if sum(_hours(c, eid, w0, min(w1, asof), cache).values()) > EPS:
                    moved_out += r["amount"]
                    continue
        out.append(r)
    # every machine month in which this project logged hours
    cond, p = ["project_id=?", "equipment_id IS NOT NULL", "hours>0", "date<=?"], [pid, asof]
    used = q(c, "SELECT DISTINCT equipment_id, date FROM logsheets WHERE " + " AND ".join(cond), p)
    wins = {}
    for x in used:
        wins.setdefault((x["equipment_id"],) + tuple(window_of_date(c, x["date"])), True)
    moved_in, own_back = 0.0, 0.0
    for (eid, w0, w1) in sorted(wins):
        to = min(w1, asof)
        H = _hours(c, eid, w0, to, cache)
        tot = sum(H.values())
        if tot <= EPS or H.get(pid, 0) <= EPS:
            continue
        share = H[pid] / tot
        lo = max(w0, frm) if frm else w0
        conds = ["l.equipment_id=?", "v.date BETWEEN ? AND ?", "x.type='expense'"]
        prm = [eid, lo, to]
        stat = [("posted", CL.POSTED)]
        if include_waiting and _has(c, "post_queue"):
            stat.append(("waiting", CL.WAITING))
        if ctx is None:
            ctx = CL.Ctx(c)
        parts = None
        for status, sql in stat:
            for ln in q(c, CL.LINE_SQL + "WHERE " + " AND ".join(conds) + " AND " + sql + " ORDER BY l.id", prm):
                if CL.basis_of(ctx, ln) != "eq_run":
                    continue
                if parts is None:
                    weights = CL._hours_weights(ctx, pid, CL._log_rows(c, pid, eid, w0, to), False)
                    parts = CL._parts(weights, "E", "eq_run", "shared_hours") or \
                        [{"code_id": ctx.head(pid, "UNA"), "share": 1.0, "ctype": "E", "basis": "eq_run", "how": "shared_hours"}]
                amt = ((ln["debit"] or 0) - (ln["credit"] or 0)) * share
                if (ln["project_id"] or ln["vproject"]) == pid:
                    own_back += amt
                else:
                    moved_in += amt
                for pt in parts:
                    rr = CL._row(ln, pt["code_id"], amt * pt["share"], "E", "eq_run", "shared_hours", status)
                    rr["eq"] = "EO"
                    rr["shared_from"] = ln["project_id"] or ln["vproject"]
                    out.append(rr)
    if stats is not None:
        stats["moved_out"] = r2(moved_out - own_back)
        stats["moved_in"] = r2(moved_in)
    return out


def _patch_cost_rows():
    CL = _CL()
    if getattr(CL.project_cost_rows, FLAG, False):
        return
    orig = CL.project_cost_rows

    def project_cost_rows(c, pid, asof, frm=None, include_waiting=True, with_lines=False):
        rows = orig(c, pid, asof, frm, include_waiting, with_lines)
        if not on(c) or CL.eq_mode(c) == "rate" or not pid or getattr(_LOCAL, "noshare", False):
            return rows
        st = {}
        rows = _share_machine_cost(c, int(pid), asof, frm, include_waiting, rows, st)
        if not frm:
            _SHARE[(id(c), int(pid), asof)] = st
        return rows
    setattr(project_cost_rows, FLAG, True)
    project_cost_rows._orig = orig
    # the month-close data checks compare the coded cost with the ledger line by line: they read the cost as posted
    if not getattr(CL.run_checks, FLAG, False):
        rc = CL.run_checks

        def run_checks(*a, **k):
            prev = getattr(_LOCAL, "noshare", False)
            _LOCAL.noshare = True
            try:
                return rc(*a, **k)
            finally:
                _LOCAL.noshare = prev
        setattr(run_checks, FLAG, True)
        run_checks._orig = rc
        CL.run_checks = run_checks
    CL.project_cost_rows = project_cost_rows


_SHARE = {}


# ───────────────────────────── 1b. the forecast, item by item with its basis ─────────────────────────────
def executed_asof(c, pid, asof):
    if asof >= today():
        return {r["id"]: _f(r["executed_qty"]) for r in q(c, "SELECT id, executed_qty FROM boq_items WHERE project_id=?", (pid,))}
    return {r["b"]: _f(r["qty"]) for r in q(
        c, "SELECT COALESCE(w.boq_item_id, a.boq_item_id) b, SUM(w.actual_qty) qty FROM dpr_work w JOIN dpr d ON d.id=w.dpr_id "
           "LEFT JOIN activities a ON a.id=w.activity_id WHERE d.status='approved' AND d.project_id=? AND d.date<=? GROUP BY 1",
        (pid, asof)) if r["b"]}


def _ra_cpu(c, bid, cache):
    """Cost per unit from the BOQ rate analysis, with its overhead line (the figure behind the earned-value budget and the
    tender margin); else the item's analysis in Estimating."""
    if bid not in cache:
        ub, parts = _P().unit_budget(c, bid)
        if ub and ub > EPS:
            cache[bid] = (ub, "BOQ rate analysis" + (" incl. overhead" if parts.get("overhead") or parts.get("other") else ""))
        else:
            ra = _CL()._ra_units(c, bid)
            cache[bid] = (ra["cpu"], ra.get("source")) if ra and _f(ra.get("cpu")) > EPS else (None, None)
    return cache[bid]


def _reforecast(c, pid, asof, rep):
    CL = _CL()
    rule = setting(c, "cl_ctc_rule") or "actual_after"
    pct_rule = CL.sf(c, "cl_ctc_pct")
    exq = executed_asof(c, pid, asof)
    rac = {}
    no_fc, no_budget = [], []
    for r in rep["rows"]:
        if r.get("kind") != "boq":
            r.setdefault("forecast_basis_kind", "indirect")
            continue
        bid = r["boq_item_id"]
        qd = _f(r.get("qty_done"))
        qx = max(qd, exq.get(bid, 0.0))
        qt = _f(r.get("qty_total"))
        cost = _f(r.get("cost"))
        rate = _f(r.get("rate"))
        remaining = max(0.0, qt - qx)
        done_pct = 100.0 * qx / qt if qt else (100.0 if qx else 0.0)
        old = str(r.get("forecast_basis") or "")
        flag = None
        if old.startswith("PM:"):
            fu, basis, kind = _f(r.get("forecast_unit")), old, "pm"
        elif rule == "actual_after" and qx > EPS and done_pct >= pct_rule:
            fu, basis, kind = cost / qx, "actual unit cost (%.0f%% done)" % done_pct, "actual"
        elif r.get("budget_unit") is not None:
            fu, basis, kind = _f(r["budget_unit"]), "control budget", "control_budget"
        else:
            cpu, src = _ra_cpu(c, bid, rac)
            if cpu is not None:
                fu, basis, kind = cpu, "rate analysis (%s)" % (src or "BOQ"), "rate_analysis"
            elif qx > EPS:
                fu, basis, kind, flag = cost / qx, "actual unit cost: no budget", "actual_no_budget", "no_budget"
            else:
                fu, basis, kind, flag = 0.0, "no forecast: no budget and no rate analysis", "none", "no_forecast"
        ctc = remaining * fu
        fval = max(qt, qx) * rate
        r.update({"qty_physical": round(qx, 4), "remaining_qty": round(remaining, 4), "done_pct": round(done_pct, 1),
                  "forecast_unit": r2(fu), "forecast_basis": basis, "forecast_basis_kind": kind, "ctc": r2(ctc),
                  "eac": r2(cost + ctc), "forecast_value": r2(fval), "forecast_margin": r2(fval - cost - ctc)})
        if flag == "no_forecast":
            no_fc.append({"code": r["code"], "name": r["name"], "revenue": r2(remaining * rate)})
            r.setdefault("flags", []).append("no_forecast")
        elif flag == "no_budget":
            no_budget.append({"code": r["code"], "name": r["name"], "revenue": r2(remaining * rate)})
            r.setdefault("flags", []).append("no_budget")
    rows = rep["rows"]
    T = lambda f_: r2(sum((x.get(f_) or 0) for x in rows))  # noqa: E731
    tot = rep["total"]
    for f_ in ("ctc", "eac", "forecast_value"):
        tot[f_] = T(f_)
    tot["forecast_margin"] = r2(tot["forecast_value"] - tot["eac"])
    tot["forecast_margin_pct"] = round(100 * tot["forecast_margin"] / tot["forecast_value"], 2) if tot["forecast_value"] else None
    tot["no_forecast"] = no_fc
    tot["no_budget"] = no_budget
    tot["revenue_without_cost"] = r2(sum(x["revenue"] for x in no_fc))
    fl = [x for x in rep.get("flags") or [] if x.get("key") not in ("margin_fade", "loss")]
    bid_margin = tot.get("bid_margin_pct")
    if bid_margin is not None and tot["forecast_margin_pct"] is not None and \
            tot["forecast_margin_pct"] < bid_margin - CL.sf(c, "cl_flag_margin_drop"):
        fl.insert(0, {"key": "margin_fade", "text": "Forecast margin %s%% is more than %s points below the bid margin %s%%" %
                      (tot["forecast_margin_pct"], r2(CL.sf(c, "cl_flag_margin_drop")), bid_margin)})
    if tot["forecast_margin"] < -0.5:
        fl.insert(0, {"key": "loss", "text": "Forecast final loss %s: accounts to consider a loss provision (NFRS 15)" %
                      "{:,.2f}".format(-tot["forecast_margin"])})
    for x in no_fc:
        fl.append({"key": "no_forecast", "code": x["code"], "text": "%s has no budget and no rate analysis: %s of revenue has no cost "
                                                                   "behind it in the forecast" % (x["code"], "{:,.2f}".format(x["revenue"]))})
    rep["flags"] = fl
    rep["forecast_rule"] = "PM override, actual unit cost after %s%% done, control budget, rate analysis, actual unit cost (no " \
                           "budget), none" % core.r2(pct_rule)
    return rep


def _patch_cvr():
    CL = _CL()
    if getattr(CL.cvr, FLAG, False):
        return
    orig = CL.cvr

    def cvr(c, pid, asof, close=None, acc=None):
        if not on(c):
            return orig(c, pid, asof, close, acc)
        key = ("cvr", int(pid), asof, getattr(_LOCAL, "force", None))
        if close is None and acc is None:
            hit = _memo_get(c, key)
            if hit is not None:
                return hit
        rep = _reforecast(c, int(pid), asof, orig(c, pid, asof, close, acc))
        rep["position_on"] = True
        if close is None and acc is None:
            _memo_put(c, key, rep)
        return rep
    setattr(cvr, FLAG, True)
    cvr._orig = orig
    CL.cvr = cvr


# ───────────────────────────── 1c. the position ─────────────────────────────
def _ledger(c, pid, asof):
    CL = _CL()
    r = q1(c, "SELECT SUM(CASE WHEN x.type='expense' THEN l.debit-l.credit ELSE 0 END) cost, "
              "SUM(CASE WHEN x.type='income' THEN l.credit-l.debit ELSE 0 END) income, "
              "SUM(CASE WHEN x.role IN ('equipment_cost','equip_job_cost') THEN l.debit-l.credit ELSE 0 END) charges, "
              "SUM(CASE WHEN x.role IN ('equipment_recovery','equip_recovery') THEN l.credit-l.debit ELSE 0 END) recovery "
              "FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id JOIN accounts x ON x.id=l.account_id "
              "WHERE l.project_id=? AND v.date<=? AND " + CL.POSTED, (pid, asof)) or {}
    return {k: r2(r.get(k) or 0) for k in ("cost", "income", "charges", "recovery")}


def _certified(c, pid, asof):
    return r2(val(c, "SELECT SUM(l.amount) FROM ipc_lines l JOIN ipc i ON i.id=l.ipc_id WHERE i.project_id=? AND i.date<=? AND "
                     "i.status='certified'", (pid, asof)) or 0)


def _earned(c, pid, asof):
    exq = executed_asof(c, pid, asof)
    return r2(sum(exq.get(b["id"], 0) * _f(b["rate"]) for b in q(
        c, "SELECT id, COALESCE(revised_rate, rate) rate FROM boq_items WHERE project_id=?", (pid,))))


def position(c, pid, asof=None):
    """The one position of a project at a date (see the module notes). Works with the switch off too (for the compare)."""
    pid = int(pid)
    asof = asof or today()
    hit = _memo_get(c, ("pos", pid, asof, on(c), getattr(_LOCAL, "force", None)))
    if hit is not None:
        return hit
    CL = _CL()
    p = get(c, "projects", pid, "Project")
    _SHARE.pop((id(c), pid, asof), None)
    rep = CL.cvr(c, pid, asof)
    if not rep.get("position_on"):
        rep = _reforecast(c, pid, asof, rep)        # switch off: the compare shows what the position would say
    t = rep["total"]
    led = _ledger(c, pid, asof)
    sh = _SHARE.get((id(c), pid, asof)) or {}
    cert = _certified(c, pid, asof)
    earned = _earned(c, pid, asof)
    measured = r2(t.get("value") or 0)
    billed = r2(t.get("billed_value") or 0)
    cost = r2(t["cost"])
    fval, eac = r2(t["forecast_value"]), r2(t["eac"])
    items = []
    for r in rep["rows"]:
        if r.get("kind") == "boq":
            items.append({"code": r["code"], "name": r["name"], "unit": r.get("unit"), "qty_total": r.get("qty_total"),
                          "qty_physical": r.get("qty_physical"), "qty_measured": r.get("qty_done"), "cost": r["cost"],
                          "basis": r.get("forecast_basis"), "basis_kind": r.get("forecast_basis_kind"),
                          "unit_cost": r.get("forecast_unit"), "remaining_qty": r.get("remaining_qty"), "ctc": r["ctc"],
                          "eac": r["eac"], "forecast_value": r["forecast_value"], "forecast_margin": r["forecast_margin"],
                          "flags": r.get("flags") or []})
        elif abs(_f(r.get("cost"))) > EPS or abs(_f(r.get("ctc"))) > EPS:
            items.append({"code": r["code"], "name": r["name"], "cost": r["cost"], "basis": r.get("forecast_basis"),
                          "basis_kind": "indirect", "ctc": r.get("ctc") or 0, "eac": r.get("eac") or r["cost"],
                          "forecast_value": r.get("forecast_value") or 0, "forecast_margin": r.get("forecast_margin") or 0,
                          "flags": r.get("flags") or []})
    rec = [{"label": "Expense in the ledger for this project", "amount": led["cost"]},
           {"label": "Less internal machine charges (the project charged itself; the machine's own cost is counted instead)",
            "amount": -led["charges"]}]
    if sh:
        rec.append({"label": "Less own machine cost moved to the projects that used the machine (by hours)", "amount": -sh.get("moved_out", 0)})
        rec.append({"label": "Plus this project's share of machines' cost by its hours", "amount": sh.get("moved_in", 0)})
    rest = r2(_f(t["cost_posted"]) - sum(x["amount"] for x in rec))
    if abs(rest) > 0.5:
        rec.append({"label": "Other differences (rate-mode machine cost, cost outside the cost codes, recoding)", "amount": rest})
    rec.append({"label": "Plus entries waiting in the accounts posting queue", "amount": r2(t["cost_waiting"])})
    rec.append({"label": "Plus accruals at the month close", "amount": r2(t["cost_accrued"])})
    out = {"project": {"id": pid, "code": p["code"], "name": p["name"], "contract_value": p.get("contract_value")},
           "as_of": asof, "switch_on": on(c), "eq_costing": CL.eq_mode(c),
           "cost": {"posted": r2(t["cost_posted"]), "waiting": r2(t["cost_waiting"]), "accrued": r2(t["cost_accrued"]), "total": cost,
                    "labour": r2(t.get("cost_l") or 0), "material": r2(t.get("cost_m") or 0), "equipment": r2(t.get("cost_e") or 0),
                    "subcontract": r2(t.get("cost_s") or 0), "other": r2(t.get("cost_o") or 0),
                    "machine_moved_out": sh.get("moved_out", 0.0), "machine_shared_in": sh.get("moved_in", 0.0)},
           "value": {"certified": cert, "measured": measured, "billed": billed, "earned": earned,
                     "earned_not_certified": r2(earned - cert), "measured_not_certified": r2(measured - cert)},
           "margin": {"certified": r2(cert - cost), "certified_pct": round(100 * (cert - cost) / cert, 1) if cert else None,
                      "earned": r2(earned - cost), "earned_pct": round(100 * (earned - cost) / earned, 1) if earned else None},
           "forecast": {"cost_to_complete": r2(t["ctc"]), "eac": eac, "value": fval, "profit": r2(fval - eac),
                        "margin_pct": round(100 * (fval - eac) / fval, 1) if fval else None, "bid_margin_pct": t.get("bid_margin_pct"),
                        "no_forecast": t.get("no_forecast") or [], "no_budget": t.get("no_budget") or [],
                        "revenue_without_cost": t.get("revenue_without_cost") or 0.0, "rule": rep.get("forecast_rule"),
                        "items": items},
           "ledger": dict(led, reconciliation=rec, position_cost=cost),
           "flags": rep.get("flags") or [],
           "explain": EXPLAIN}
    _memo_put(c, ("pos", pid, asof, on(c), getattr(_LOCAL, "force", None)), out)
    return out


EXPLAIN = {
    "cost": "Cost to date: posted cost of the project, entries waiting in the accounts posting queue and accruals at the month "
            "close, on the cost-code definition. Internal machine charges are left out; each own machine's running and owning "
            "cost is shared over the projects that used it, by the hours logged that month.",
    "certified": "Certified value: IPC lines of certified IPCs up to the date.",
    "earned": "Earned value: quantity executed (approved DPRs) x BOQ rate.",
    "margin": "Margin to date: certified value less cost to date (beside it, on earned value).",
    "forecast": "Forecast: cost to date plus the remaining quantity of each BOQ item at its forecast unit cost (PM override, "
                "actual after the threshold, control budget, rate analysis, actual unit cost, or none), plus indirect heads.",
}


@api("pfp.position", "project", "view")
def pfp_position(c, u, a):
    core.need(a, "project_id")
    pid = int(a["project_id"])
    _CL()._check_project(c, u, pid)
    return position(c, pid, a.get("as_of") or today())


# ───────────────────────────── 1d. project_evm (project overview, insight, portfolio ...) reads the position ─────────────
def _patch_evm():
    P = _P()
    if getattr(P.project_evm, FLAG, False):
        return
    orig = P.project_evm

    def project_evm(c, pid, asof):
        ev = orig(c, pid, asof)
        if not on(c):
            return ev
        try:
            pos = position(c, pid, asof)
        except ApiError:
            return ev
        CL = _CL()
        rep = CL.cvr(c, int(pid), asof)
        by_b = {r.get("boq_item_id"): r for r in rep["rows"] if r.get("kind") == "boq"}
        for r in ev["rows"]:
            x = by_b.get(r["id"])
            if not x:
                continue
            qx = _f(x.get("qty_physical"))
            ac = r2(x["cost"])
            r.update({"ac": ac, "etc": r2(x["ctc"]), "eac": r2(x["eac"]), "actual_unit_cost": r2(ac / qx) if qx > EPS else None,
                      "forecast_revenue": r2(x["forecast_value"]), "forecast_profit": r2(x["forecast_value"] - x["eac"]),
                      "forecast_basis": x.get("forecast_basis"), "cv": r2(r["ev"] - ac) if r.get("ev") is not None else None,
                      "cpi": round(r["ev"] / ac, 2) if r.get("ev") is not None and ac > EPS else None})
        cost = pos["cost"]
        ac_boq = r2(sum(_f(r["ac"]) for r in ev["rows"]))
        fr = pos["forecast"]["value"]
        ev.update({"ac": cost["total"], "ac_posted": cost["posted"], "waiting": cost["waiting"], "accrued": cost["accrued"],
                   "ac_boq": ac_boq, "ac_unallocated": r2(cost["total"] - ac_boq), "eac": pos["forecast"]["eac"],
                   "etc": pos["forecast"]["cost_to_complete"], "forecast_revenue": fr, "forecast_profit": pos["forecast"]["profit"],
                   "forecast_margin": pos["forecast"]["margin_pct"], "current_margin": pos["margin"]["certified_pct"],
                   "earned_margin": pos["margin"]["earned_pct"], "certified_value": pos["value"]["certified"],
                   "position": {"cost": cost, "value": pos["value"], "margin": pos["margin"],
                                "forecast": {k: v for k, v in pos["forecast"].items() if k != "items"}}})
        if ev.get("ev") is not None:
            ev["cv"] = r2(ev["ev"] - ac_boq)
            ev["cpi"] = round(ev["ev"] / ac_boq, 2) if ac_boq > EPS and ev.get("cpi") is not None else ev.get("cpi")
        tm = ev.get("tender_margin")
        ev["margin_fade"] = round(tm - ev["forecast_margin"], 1) if tm is not None and ev["forecast_margin"] is not None else None
        return ev
    setattr(project_evm, FLAG, True)
    for f_ in ("_bco223",):
        setattr(project_evm, f_, True)
    project_evm._orig = orig
    P.project_evm = project_evm


# ───────────────────────────── 1e. ledger screens keep the ledger and show the position beside it ─────────────────────────
def _is_project(c, pid):
    return bool(pid) and (val(c, "SELECT COALESCE(kind,'') FROM projects WHERE id=?", (pid,), "") or "") in ("", "project")


def _pos_brief(c, pid, asof):
    p = position(c, pid, asof)
    return {"cost": p["cost"]["total"], "certified": p["value"]["certified"], "earned": p["value"]["earned"],
            "margin": p["margin"]["certified"], "margin_pct": p["margin"]["certified_pct"], "eac": p["forecast"]["eac"],
            "forecast_profit": p["forecast"]["profit"], "forecast_margin_pct": p["forecast"]["margin_pct"],
            "reconciliation": p["ledger"]["reconciliation"],
            "note": "Project position (CVR and forecast): the ledger above stays as posted; the position leaves out internal "
                    "machine charges, shares machine cost by hours and adds waiting entries and accruals."}


def _w_rep_pl(orig):
    def rep_pl(c, u, a):
        res = orig(c, u, a)
        pid = a.get("project_id")
        if on(c) and pid and _is_project(c, int(pid)) and not a.get("from"):
            try:
                res["position"] = _pos_brief(c, int(pid), a.get("to") or today())
            except ApiError:
                pass
        return res
    return rep_pl


def _w_rep_budget(orig):
    def rep_budget(c, u, a):
        res = orig(c, u, a)
        pid = int(a["project_id"])
        if not _is_project(c, pid):
            return res
        CL = _CL()
        cur = CL.current_version(c, pid) or CL.original_version(c, pid)
        if cur:
            lines = CL.vlines(c, cur["id"])
            res["control_budget"] = {"version": cur["version_no"], "kind": cur["kind"],
                                     "total": r2(sum(CL.line_amount(x) for x in lines.values())),
                                     "note": "The control budget is the project's budget; budgets by account are for overhead and "
                                             "company budgets."}
        if on(c):
            try:
                res["position"] = _pos_brief(c, pid, today())
            except ApiError:
                pass
        return res
    return rep_budget


def _w_ws_project_cost(orig):
    def ws_project_cost(c, u, a):
        res = orig(c, u, a)
        if not on(c) or a.get("from"):
            return res
        asof = a.get("to") or today()
        for r in res.get("rows") or []:
            if r.get("project_id") and _is_project(c, r["project_id"]):
                try:
                    r["position_cost"] = position(c, r["project_id"], asof)["cost"]["total"]
                except ApiError:
                    pass
        res["position_note"] = "Cost per project above is the ledger (it adds up to the company ledger). 'Project position' is the " \
                               "one project cost used on every project screen."
        return res
    return ws_project_cost


def _w_company_overview(orig):
    def company_overview(c, u, a):
        res = orig(c, u, a)
        if on(c):
            for r in res.get("budget") or []:
                try:
                    r["position_cost"] = position(c, r["project_id"], today())["cost"]["total"]
                except ApiError:
                    pass
        return res
    return company_overview


# ───────────────────────────── 1f. compare and confirm ─────────────────────────────
def _active_projects(c):
    return q(c, "SELECT id, code, name FROM projects WHERE status='active' AND COALESCE(kind,'') NOT IN ('trading','general') "
                "ORDER BY code")


def _screens(c, pid, asof):
    """The figures each family of screens shows for a project, as BuildCore is set now."""
    P, CL = _P(), _CL()
    ev = P.project_evm(c, pid, asof)
    cv = CL.cvr(c, pid, asof)["total"]
    led = _ledger(c, pid, asof)
    return {"overview": {"cost": r2(ev["ac"]), "value": r2(ev.get("certified_value") if ev.get("certified_value") is not None
                                                             else ev["earned_revenue"]),
                         "margin_pct": ev.get("current_margin"), "eac": r2(ev["eac"]), "forecast_profit": r2(ev["forecast_profit"]),
                         "forecast_margin_pct": ev.get("forecast_margin")},
            "cvr": {"cost": r2(cv["cost"]), "value": r2(cv["value"]), "margin_pct": cv.get("margin_pct"), "eac": r2(cv["eac"]),
                    "forecast_profit": r2(cv["forecast_margin"]), "forecast_margin_pct": cv.get("forecast_margin_pct")},
            "ledger": {"cost": led["cost"], "value": led["income"],
                       "margin_pct": round(100 * (led["income"] - led["cost"]) / led["income"], 1) if led["income"] else None}}


SCREEN_NAMES = {"overview": "Project overview, control room, insight, company overview, portfolio, profit analysis, project cost & "
                            "exposure, cost & earned value",
                "cvr": "CVR, cost to complete, command centre, league, company health",
                "ledger": "Profit & loss, project cost by workspace, budget vs actual (ledger; unchanged)"}


def compare(c, asof=None, pids=None):
    asof = asof or today()
    out = []
    for p in _active_projects(c):
        if pids and p["id"] not in pids:
            continue
        try:
            _LOCAL.force = False
            before = _screens(c, p["id"], asof)
            _LOCAL.force = True
            after = _screens(c, p["id"], asof)
            pos = position(c, p["id"], asof)
        finally:
            _LOCAL.force = None
        out.append({"project_id": p["id"], "code": p["code"], "name": p["name"], "before": before, "after": after,
                    "position": {"cost": pos["cost"], "value": pos["value"], "margin": pos["margin"],
                                 "forecast": {k: v for k, v in pos["forecast"].items() if k != "items"},
                                 "items": pos["forecast"]["items"], "reconciliation": pos["ledger"]["reconciliation"]}})
    return out


REASONS = [
    "Cost: one definition everywhere - posted + waiting + accrued, internal machine charges left out, each machine's cost shared "
    "over the projects that used it by hours. Before, the project overview left out accruals and kept machine cost on the "
    "machine's home project.",
    "Value and margin: margin to date on certified value (margin on earned value beside it). Before, the overview used earned "
    "value and the ledger counted internal machine recovery as income.",
    "Forecast: item by item from the control budget, else the rate analysis, else actual unit cost (flagged), else 'no forecast' "
    "(flagged with the revenue). Before, CVR forecast items without a control budget at zero cost, and the overview used the rate "
    "analysis or the actual unit cost of the first few percent of work.",
    "Quantity still to do: the contract quantity less the physical progress (the larger of executed and measured). Before, CVR "
    "used the measured quantity, so work done but not measured was costed twice.",
]


@api("pfp.compare", "accounts", "view")
def pfp_compare(c, u, a):
    pids = [int(a["project_id"])] if a.get("project_id") else None
    return {"as_of": today(), "switch_on": on(c), "rows": compare(c, a.get("as_of"), pids), "screens": SCREEN_NAMES,
            "reasons": REASONS, "history": q(c, "SELECT p.id, p.what, p.value, p.ts, p.note, u.name user FROM pfp_confirm p LEFT JOIN "
                                                "users u ON u.id=p.user_id ORDER BY p.id DESC LIMIT 20"),
            "settings": _settings(c), "can_confirm": _right(u, "accounts", "approve")}


def _settings(c):
    return {"pfp_on": on(c), "run_months": setting(c, "run_months") or "english", "eqcc_from": setting(c, "eqcc_from") or "",
            "po_budget_block": setting(c, "po_budget_block") == "1"}


def _record(c, u, what, value, before=None, after=None, note=None):
    ins(c, "pfp_confirm", {"what": what, "value": str(value), "before_json": json.dumps(before, default=str) if before is not None else None,
                           "after_json": json.dumps(after, default=str) if after is not None else None, "user_id": u["id"], "ts": now(),
                           "note": note})
    audit(c, u, "pfp_" + what, "settings", 0, {"value": value})


@api("pfp.confirm", "accounts", "approve")
def pfp_confirm(c, u, a):
    """Accounts confirms the one project position after seeing before and after: every project screen then reads it."""
    want = a.get("on", True) not in (False, 0, "0", "false")
    if want == on(c):
        return {"pfp_on": want}
    rows = compare(c)
    brief = [{"code": r["code"], "before": r["before"], "after": r["after"]} for r in rows]
    _set(c, "pfp_on", "1" if want else "0")
    _record(c, u, "position", "1" if want else "0", [{"code": b["code"], **b["before"]} for b in brief],
            [{"code": b["code"], **b["after"]} for b in brief], a.get("note"))
    return {"pfp_on": want, "projects": len(rows)}


# ───────────────────────────── 2. equipment as its own cost centre ─────────────────────────────
RECOVERY_ROLES = ("equipment_recovery", "equip_recovery")
CHARGE_ROLES = ("equipment_cost", "equip_job_cost")
OWNING_ROLES = ("depreciation", "interest_expense", "insurance", "insurance_expense", "loan_interest", "lease_interest")


def eq_cc(c, create=False):
    pid = val(c, "SELECT id FROM projects WHERE code='EQUIP' AND kind='general' ORDER BY id LIMIT 1", (), None)
    if not pid and create:
        pid = ins(c, "projects", {"code": "EQUIP", "name": "Own equipment (machine cost centres)", "kind": "general",
                                  "status": "active", "start_date": today()})
    return pid


def _acc_info(c, ln, cache):
    acc = ln.get("account_id")
    key = ("a", acc) if acc else ("r", ln.get("role"))
    if key not in cache:
        if not acc and ln.get("role"):
            try:
                acc = core.role_account(c, ln["role"])
            except ApiError:
                acc = None
        r = q1(c, "SELECT type, role FROM accounts WHERE id=?", (acc,)) if acc else None
        cache[key] = (r["type"], r["role"] or ln.get("role") or "") if r else (None, ln.get("role") or "")
    return cache[key]


def _redirect(c, lines):
    cc = None
    cache, own = {}, {}
    out = []
    for ln in lines:
        typ, role = _acc_info(c, ln, cache)
        eid = ln.get("equipment_id")
        move = False
        if role in RECOVERY_ROLES:
            move = True
        elif eid and typ == "expense" and role not in CHARGE_ROLES and role != "hire_cost":
            if eid not in own:
                own[eid] = (val(c, "SELECT COALESCE(ownership,'owned') FROM equipment WHERE id=?", (eid,), "") or "") == "owned"
            move = own[eid]
        if move:
            if cc is None:
                cc = eq_cc(c, True)
            ln = dict(ln, project_id=cc)
        out.append(ln)
    return out


def _patch_post():
    import sys
    cur = core.post_voucher
    if getattr(cur, FLAG, False):
        return

    def post_voucher(c, user, vtype, d, narration, lines, project_id=None, source="manual", source_id=None, party_id=None,
                     ref_no=None, status="posted"):
        frm = setting(c, "eqcc_from") or ""
        if frm and d and str(d)[:10] >= frm[:10] and lines:
            lines = _redirect(c, lines)
        return cur(c, user, vtype, d, narration, lines, project_id=project_id, source=source, source_id=source_id,
                   party_id=party_id, ref_no=ref_no, status=status)
    for f_ in ("_bco219", "_bco220", "_bco221", "_bco223", "_bco224"):
        if getattr(cur, f_, False):
            setattr(post_voucher, f_, True)
    setattr(post_voucher, FLAG, True)
    post_voucher._inner = cur
    for name, m in list(sys.modules.items()):
        if m is None or not name:
            continue
        if getattr(m, "post_voucher", None) is cur:
            try:
                setattr(m, "post_voucher", post_voucher)
            except Exception:
                pass


@api("pfp.eqcc", "accounts", "view")
def pfp_eqcc(c, u, a):
    """The equipment cost centre switch and what it moves."""
    return {"eqcc_from": setting(c, "eqcc_from") or "", "cost_centre": eq_cc(c), "can_change": _right(u, "accounts", "approve"),
            "moves": ["Depreciation, EMI interest, insurance, fuel, repairs and other running cost of an owned machine",
                      "The credit side (recovery) of DPR machine charges, internal hire, Fixed assets allocation and small-asset hire"],
            "stays": ["The using project's machine charge (Dr equipment cost)", "Hired machines' bills", "Everything posted before the date"]}


@api("pfp.eqcc_set", "accounts", "approve")
def pfp_eqcc_set(c, u, a):
    d = (a.get("from") or "").strip()[:10]
    if d:
        try:
            _d(d)
        except ValueError:
            raise ApiError("Give the date as YYYY-MM-DD.")
        eq_cc(c, True)
    before = setting(c, "eqcc_from") or ""
    _set(c, "eqcc_from", d)
    _record(c, u, "eqcc_from", d, {"eqcc_from": before}, {"eqcc_from": d}, a.get("note"))
    return {"eqcc_from": d, "cost_centre": eq_cc(c)}


@api("pfp.po_block", "accounts", "approve")
def pfp_po_block(c, u, a):
    """Over-budget purchase orders: warning only (default) or an administrator must approve."""
    want = "1" if a.get("on") not in (False, 0, "0", "false", None) else "0"
    before = setting(c, "po_budget_block") or "0"
    _set(c, "po_budget_block", want)
    _record(c, u, "po_budget_block", want, {"po_budget_block": before}, {"po_budget_block": want}, a.get("note"))
    return {"po_budget_block": want == "1"}


def machine_pl(c, frm, to, eq_id=None):
    """Per owned machine and month: owning and operating cost against the recovery charged, wherever it was posted."""
    CL = _CL()
    cond, p = "ownership='owned'", []
    if eq_id:
        cond += " AND id=?"
        p.append(int(eq_id))
    machines = q(c, "SELECT id, code, name FROM equipment WHERE " + cond + " ORDER BY code", p)
    months = []
    if nepali_runs(c):
        k = CL.period_of_date(c, frm)
        while True:
            w0, w1 = CL.period_bounds(c, k)
            if w0 > to:
                break
            months.append((k, CL.period_label(k), w0, w1))
            k = CL._shift(k, 1)
    else:
        d = _d(frm[:8] + "01")
        while d.isoformat() <= to:
            m = d.isoformat()[:7]
            months.append((m, m, m + "-01", core.month_end(m)))
            d = _d(core.month_end(m)) + timedelta(days=1)
    rows = []
    for e in machines:
        for k, lab, w0, w1 in months:
            lo, hi = max(w0, frm), min(w1, to)
            x = q1(c, "SELECT SUM(CASE WHEN a.type='expense' AND a.role IN (%s) THEN l.debit-l.credit ELSE 0 END) owning, "
                      "SUM(CASE WHEN a.type='expense' AND COALESCE(a.role,'') NOT IN (%s) AND COALESCE(a.role,'') NOT IN (%s) "
                      "AND COALESCE(a.role,'')<>'hire_cost' THEN l.debit-l.credit ELSE 0 END) operating, "
                      "SUM(CASE WHEN a.role IN ('equipment_recovery','equip_recovery') THEN l.credit-l.debit ELSE 0 END) recovery "
                      "FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id JOIN accounts a ON a.id=l.account_id "
                      "WHERE l.equipment_id=? AND v.date BETWEEN ? AND ? AND " % (
                          ",".join("'%s'" % r for r in OWNING_ROLES), ",".join("'%s'" % r for r in OWNING_ROLES),
                          ",".join("'%s'" % r for r in CHARGE_ROLES)) + CL.POSTED, (e["id"], lo, hi)) or {}
            # Fixed assets allocations posted before 2.39 carry no machine on the line: count them from fa_alloc
            fa_rec = 0.0
            fa = _fa_row_of(c, e["id"])
            if fa and _has(c, "fa_alloc"):
                fa_rec = _f(val(c, "SELECT SUM(f.amount) FROM fa_alloc f JOIN voucher_lines l ON l.voucher_id=f.voucher_id JOIN "
                                   "accounts a ON a.id=l.account_id JOIN vouchers v ON v.id=f.voucher_id WHERE f.fa_id=? AND "
                                   "f.kind='charge' AND v.date BETWEEN ? AND ? AND a.role IN ('equipment_recovery','equip_recovery') "
                                   "AND l.equipment_id IS NULL AND l.credit>0 AND " + CL.POSTED, (fa["id"], lo, hi)))
            hrs = _f(val(c, "SELECT SUM(hours) FROM logsheets WHERE equipment_id=? AND date BETWEEN ? AND ?", (e["id"], lo, hi)))
            own_, opr = r2(x.get("owning") or 0), r2(x.get("operating") or 0)
            rec = r2((x.get("recovery") or 0) + fa_rec)
            if not (own_ or opr or rec or hrs):
                continue
            tot = r2(own_ + opr)
            rows.append({"equipment_id": e["id"], "code": e["code"], "name": e["name"], "month": k, "label": lab, "from": lo, "to": hi,
                         "owning": own_, "operating": opr, "cost": tot, "hours": r2(hrs), "cost_per_hour": r2(tot / hrs) if hrs > EPS else None,
                         "recovery": rec, "result": r2(rec - tot),
                         "status": "over-recovered" if rec - tot > 0.5 else ("under-recovered" if rec - tot < -0.5 else "even")})
    tot = {k: r2(sum(r[k] for r in rows)) for k in ("owning", "operating", "cost", "hours", "recovery", "result")}
    return {"from": frm, "to": to, "rows": rows, "total": tot, "months": "nepali" if nepali_runs(c) else "english"}


@api("pfp.machine_pl", "equipment", "view")
def pfp_machine_pl(c, u, a):
    to = a.get("to") or today()
    frm = a.get("from") or (_d(to) - timedelta(days=365)).isoformat()
    res = machine_pl(c, frm, to, a.get("equipment_id"))
    res["eqcc_from"] = setting(c, "eqcc_from") or ""
    return res


# ───────────────────────────── 3. one budget ─────────────────────────────
def _w_budget_import(orig):
    def cl_budget_import(c, u, a):
        """preview: what each item would get (nothing is written); only_missing: keep every line already in the draft."""
        if a.get("preview"):
            c.execute("SAVEPOINT pfp_prev")
            try:
                res = orig(c, u, dict(a, preview=None))
                CL = _CL()
                names = {k["id"]: k for k in q(c, "SELECT * FROM cl_codes WHERE project_id=?", (int(a["project_id"]),))}
                lines = []
                for bl in q(c, "SELECT * FROM cl_budget_lines WHERE version_id=? ORDER BY id", (res["version_id"],)):
                    k = names.get(bl["cost_code_id"]) or {}
                    lines.append({"code": k.get("code"), "name": k.get("name"), "kind": k.get("kind"), "qty": bl["qty"],
                                  "labour": bl["unit_labour"], "material": bl["unit_material"],
                                  "equipment": r2(_f(bl["unit_equip_own"]) + _f(bl["unit_equip_rent"])), "subcontract": bl["unit_subcon"],
                                  "other": bl["unit_other"], "unit_total": r2(CL.unit_total(bl)), "amount": r2(CL.line_amount(bl)),
                                  "source": bl["source"], "placeholder": bool(bl["placeholder"])})
                res["lines"] = lines
            finally:
                c.execute("ROLLBACK TO pfp_prev")
                c.execute("RELEASE pfp_prev")
            dr = _CL().draft_version(c, int(a["project_id"]))
            res["existing_lines"] = val(c, "SELECT COUNT(*) FROM cl_budget_lines WHERE version_id=? AND COALESCE(placeholder,0)=0",
                                        (dr["id"],)) if dr else 0
            res["preview"] = True
            return res
        if not a.get("only_missing"):
            return orig(c, u, a)
        CL = _CL()
        dr = CL.draft_version(c, int(a["project_id"]))
        keep = [dict(x) for x in q(c, "SELECT * FROM cl_budget_lines WHERE version_id=? AND COALESCE(placeholder,0)=0", (dr["id"],))] if dr else []
        res = orig(c, u, a)
        for bl in keep:
            c.execute("DELETE FROM cl_budget_lines WHERE version_id=? AND cost_code_id=?", (res["version_id"], bl["cost_code_id"]))
            bl.pop("id", None)
            bl["version_id"] = res["version_id"]
            ins(c, "cl_budget_lines", bl)
        res["kept"] = len(keep)
        return res
    return cl_budget_import


def budget_view(c, pid, extra=0.0):
    """The one budget check of a project (the PR/PO budget box and the PO approval): control budget first."""
    import api_ctc as CT
    try:
        d = CT.project_ctc(c, pid)
        T = d["total"]
        if T.get("budget_current") is not None:
            left = T["budget_current"] - T["cost"] - T["committed"]
            return {"basis": "control budget (current version)", "budget": r2(T["budget_current"]), "actual": r2(T["cost"]),
                    "committed": r2(T["committed"]), "stock": 0.0, "available": r2(left), "after": r2(left - extra)}
    except ApiError:
        pass
    import api_finance as F
    b = F.budget_check(c, pid)
    b["basis"] = "material budget by account"
    if b.get("available") is not None:
        b["after"] = r2(b["available"] - extra)
    return b


def _w_po_budget(orig):
    def po_budget(c, u, a):
        return budget_view(c, int(a["project_id"]))
    return po_budget


def _w_po_approve(orig):
    def po_approve(c, u, a):
        po = q1(c, "SELECT * FROM po WHERE id=?", (int(a["id"]),))
        if po and po["status"] == "pending_approval" and po["project_id"]:
            import api_ctc as CT
            doc = dict(po)
            doc["lines"] = q(c, "SELECT * FROM po_lines WHERE po_id=?", (po["id"],))
            try:
                ck = CT.po_check(c, u, doc)
            except ApiError:
                ck = None
            b = (ck or {}).get("budget") or {}
            over = b.get("left_after") is not None and b["left_after"] < -0.5
            if over and setting(c, "po_budget_block") == "1" and u.get("role") != "admin":
                raise ApiError("This order takes the project over its %s by %s. An administrator must approve it." %
                               (b.get("basis") or "budget", "{:,.2f}".format(-b["left_after"])))
            audit(c, u, "po_check", "po", po["id"], {"basis": b.get("basis"), "left_after": b.get("left_after"),
                                                      "flags": (ck or {}).get("flags") or []})
        return orig(c, u, a)
    return po_approve


# ───────────────────────────── 4. Nepali months for every monthly run ─────────────────────────────
def _d(x):
    return date.fromisoformat(str(x)[:10])


def _days(frm, to):
    return max(0, (_d(to) - _d(frm)).days + 1)


def _next(d):
    return (_d(d) + timedelta(days=1)).isoformat()


def _key_end(c, m):
    """Last day a month key covers (English or Nepali)."""
    return window_of(c, m)[1]


def _covered(c, keys, extra=None):
    """Last day already charged, from the month keys a run has used (and the days recorded in pfp_runs)."""
    last = None
    for m in keys:
        if not m:
            continue
        try:
            e = _key_end(c, m)
        except Exception:
            continue
        last = e if last is None or e > last else last
    for e in extra or []:
        if e and (last is None or e > last):
            last = e
    return last


def _check_key(c, a, run_label):
    """The month key of a run. Nepali keys only when the company runs by Nepali month, and the other way round."""
    m = (a.get("month") or "")[:7]
    if not m:
        raise ApiError("Choose a month.")
    if nepali_runs(c) and not is_bs(m):
        raise ApiError("This company runs monthly charges by Nepali month. Choose a Nepali month (for example %s for %s)." %
                       (_CL().period_of_date(c, today()), _CL().period_label(_CL().period_of_date(c, today()))))
    if is_bs(m) and not nepali_runs(c):
        raise ApiError("This company runs %s by English month. Accounts can switch every monthly run to Nepali months on "
                       "Commercial › CVR and forecast › Project position." % run_label)
    return m


def _windowed(c, m):
    frm, to = window_of(c, m)
    return frm, to, _days(frm, to)


def _pfp_run(c, u, run, m, kind, ref, pid, frm, to, qty, amount, vid):
    ins(c, "pfp_runs", {"run": run, "month": m, "ref_kind": kind, "ref_id": ref, "project_id": pid, "from_date": frm, "to_date": to,
                        "qty": qty, "amount": amount, "voucher_id": vid, "user_id": u["id"] if u else None, "ts": now()})


def _ran(c, run, kind, ref, pid=None):
    cond, p = "run=? AND ref_kind=? AND ref_id=?", [run, kind, ref]
    if pid is not None:
        cond += " AND project_id=?"
        p.append(pid)
    return [x["to_date"] for x in q(c, "SELECT to_date FROM pfp_runs WHERE " + cond, p)]


# 4a. depreciation (Equipment and Fixed assets keep one history, as in 2.38)
def _fa_row_of(c, eq_id):
    return q1(c, "SELECT * FROM fa_register WHERE kind='equipment' AND ref_id=? ORDER BY id LIMIT 1", (eq_id,)) if _has(c, "fa_register") else None


def _dep_covered(c, eq_id=None, fa_id=None):
    keys = []
    if eq_id:
        keys += [x["month"] for x in q(c, "SELECT month FROM dep_runs WHERE equipment_id=?", (eq_id,))]
        fa = _fa_row_of(c, eq_id)
        fa_id = fa_id or (fa["id"] if fa else None)
    if fa_id and _has(c, "fa_dep"):
        keys += [x["month"] for x in q(c, "SELECT month FROM fa_dep WHERE fa_id=?", (fa_id,))]
        r = q1(c, "SELECT kind, ref_id FROM fa_register WHERE id=?", (fa_id,))
        if r and r["kind"] == "equipment" and r["ref_id"] and not eq_id:
            keys += [x["month"] for x in q(c, "SELECT month FROM dep_runs WHERE equipment_id=?", (r["ref_id"],))]
    return _covered(c, keys)


def _eq_dep_line(c, eq, m, frm, to, ndays):
    done = q1(c, "SELECT amount FROM dep_runs WHERE equipment_id=? AND month=?", (eq["id"], m))
    fa = _fa_row_of(c, eq["id"])
    if not done and fa and _has(c, "fa_dep"):
        x = val(c, "SELECT SUM(amount) FROM fa_dep WHERE fa_id=? AND month=?", (fa["id"], m), None)
        if x:
            return {"posted": True, "amount": r2(x), "note": "Posted in Fixed assets › Depreciation run"}
    if done:
        return {"posted": True, "amount": done["amount"]}
    cov = _dep_covered(c, eq["id"])
    start = max(frm, _next(cov)) if cov else frm
    if eq["purchase_date"] and eq["purchase_date"][:10] > start:
        start = eq["purchase_date"][:10]
    if start > to:
        return {"posted": False, "amount": 0.0, "note": "Already charged to %s" % cov if cov else "Bought after this month"}
    base = _f(eq["purchase_value"]) - _f(eq["residual_value"])
    left = base - _f(eq["accumulated_dep"])
    if left <= EPS or not eq["purchase_value"]:
        return {"posted": False, "amount": 0.0, "note": "Fully depreciated"}
    frac = _days(start, to) / float(ndays)
    meth = eq["dep_method"] or "sl"
    if meth == "wdv":
        amt = (_f(eq["purchase_value"]) - _f(eq["accumulated_dep"])) * _f(eq["wdv_rate"]) / 100 / 12 * frac
    elif meth == "hours":
        hrs = _f(val(c, "SELECT SUM(hours) FROM logsheets WHERE equipment_id=? AND date BETWEEN ? AND ?", (eq["id"], start, to)))
        amt = base / _f(eq["est_total_hours"]) * hrs if _f(eq["est_total_hours"]) else 0
    else:
        amt = base / _f(eq["life_months"]) * frac if _f(eq["life_months"]) else 0
    return {"posted": False, "amount": r2(min(amt, left)), "from": start, "to": to,
            "note": ("Part month: %s to %s" % (start, to)) if start > frm else None}


def _w_dep_preview(orig):
    def dep_preview(c, u, a):
        m = (a.get("month") or "")[:7]
        if not is_bs(m):
            if nepali_runs(c) and m:
                _check_key(c, a, "depreciation")
            return orig(c, u, a)
        _check_key(c, a, "depreciation")
        frm, to, nd = _windowed(c, m)
        rows = []
        for eq in q(c, "SELECT * FROM equipment WHERE ownership='owned' AND active=1 AND purchase_value>0 ORDER BY code"):
            x = _eq_dep_line(c, eq, m, frm, to, nd)
            rows.append(dict({"equipment_id": eq["id"], "code": eq["code"], "name": eq["name"], "method": eq["dep_method"],
                              "book_value": r2(_f(eq["purchase_value"]) - _f(eq["accumulated_dep"]))}, **x))
        return rows
    return dep_preview


def _mirror_fa_bs(c, eq_id, m, to, amount, vid):
    fa = _fa_row_of(c, eq_id)
    if not fa or val(c, "SELECT COUNT(*) FROM fa_dep WHERE fa_id=? AND month=?", (fa["id"], m)):
        return
    pid = val(c, "SELECT project_id FROM vouchers WHERE id=?", (vid,), None) if vid else fa["project_id"]
    ins(c, "fa_dep", {"fa_id": fa["id"], "comp_id": 0, "month": m, "method": "EQ", "hours": 0, "amount": r2(amount),
                      "project_id": pid, "voucher_id": vid, "ts": now()})
    c.execute("UPDATE fa_register SET accumulated=COALESCE(accumulated,0)+? WHERE id=?", (r2(amount), fa["id"]))
    ins(c, "fa_costs", {"fa_id": fa["id"], "date": to, "category": "depreciation", "amount": r2(amount), "project_id": pid,
                        "voucher_id": vid, "ref": "DEP " + m, "remarks": "Equipment depreciation (twin record)", "ts": now()})


def _w_dep_run(orig):
    def dep_run(c, u, a):
        m = (a.get("month") or "")[:7]
        if not is_bs(m):
            if nepali_runs(c) and m:
                _check_key(c, a, "depreciation")
            return orig(c, u, a)
        _check_key(c, a, "depreciation")
        frm, to, nd = _windowed(c, m)
        if to >= today():
            raise ApiError("Depreciation can be run only for completed months (%s ends on %s)." % (_CL().period_label(m), to))
        total, n = 0.0, 0
        for eq in q(c, "SELECT * FROM equipment WHERE ownership='owned' AND active=1 AND purchase_value>0 ORDER BY code"):
            x = _eq_dep_line(c, eq, m, frm, to, nd)
            if x["posted"] or x["amount"] <= 0:
                continue
            amt = x["amount"]
            vid = core.post_voucher(c, u, "journal", to, "Depreciation %s %s" % (eq["code"], _CL().period_label(m)),
                                    [{"role": "depreciation", "debit": amt, "equipment_id": eq["id"], "project_id": eq["project_id"]},
                                     {"role": "accum_dep", "credit": amt, "equipment_id": eq["id"]}],
                                    project_id=eq["project_id"], source="depreciation", source_id=eq["id"])
            ins(c, "dep_runs", {"equipment_id": eq["id"], "month": m, "amount": amt, "voucher_id": vid})
            upd(c, "equipment", eq["id"], {"accumulated_dep": r2(_f(eq["accumulated_dep"]) + amt)})
            _pfp_run(c, u, "dep", m, "equipment", eq["id"], eq["project_id"], x.get("from") or frm, to, None, amt, vid)
            _mirror_fa_bs(c, eq["id"], m, to, amt, vid)
            total += amt
            n += 1
        return {"count": n, "total": r2(total), "month": m, "from": frm, "to": to}
    return dep_run


def _fa_dep_rows_bs(c, m, frm, to, nd):
    import api_fa as FA
    F = FA.F
    out = []
    for r in q(c, "SELECT * FROM fa_register WHERE status='active' AND managed=1 AND method<>'NONE' AND in_use_date IS NOT NULL "
                  "AND in_use_date<=? ORDER BY code", (to,)):
        if r["kind"] == "equipment" and r["ref_id"] and val(c, "SELECT COUNT(*) FROM dep_runs WHERE equipment_id=? AND month=?",
                                                              (r["ref_id"], m)):
            continue
        cov = _dep_covered(c, fa_id=r["id"])
        for cid, u_ in FA._units(c, r):
            if val(c, "SELECT id FROM fa_dep WHERE fa_id=? AND comp_id=? AND month=?", (r["id"], cid, m), None):
                continue
            start = max(frm, _next(cov)) if cov else frm
            first_use = (u_.get("in_use_date") or r["in_use_date"])[:10]
            start = max(start, first_use)
            if start > to:
                continue
            hrs = {}
            if r["kind"] == "equipment" and r["ref_id"]:
                hrs = {x["project_id"]: _f(x["h"]) for x in q(
                    c, "SELECT project_id, SUM(hours) h FROM logsheets WHERE equipment_id=? AND date BETWEEN ? AND ? AND hours>0 "
                       "GROUP BY project_id", (r["ref_id"], start, to)) if x["project_id"]}
            total_h = sum(hrs.values())
            m_in = F.months_between(first_use, frm)
            amt = F.month_dep(_f(u_["cost"]), _f(u_["residual"]), _f(u_["life_years"]), u_["method"], _f(u_["accumulated"]), m_in,
                              hours=total_h, life_hours=_f(u_["life_hours"]), rate=u_.get("wdv_rate") or None,
                              days_fraction=_days(start, to) / float(nd))
            if amt <= EPS:
                continue
            split = {k: amt * v / total_h for k, v in hrs.items()} if (total_h and len(hrs) > 1) \
                else {(list(hrs)[0] if hrs else r["project_id"]): amt}
            out.append({"fa_id": r["id"], "code": r["code"], "name": r["name"], "comp_id": cid, "component": u_["name"] if cid else "",
                        "method": u_["method"], "hours": r2(total_h), "amount": r2(amt), "split": {k: r2(v) for k, v in split.items()},
                        "nbv_after": r2(_f(u_["cost"]) - _f(u_["accumulated"]) - amt), "from": start, "to": to,
                        "kind": r["kind"], "ref_id": r["ref_id"]})
    return out


def _w_fa_dep_preview(orig):
    def fa_dep_preview(c, u, a):
        m = (a.get("month") or "")[:7]
        if not is_bs(m):
            if nepali_runs(c) and m:
                _check_key(c, a, "depreciation")
            return orig(c, u, a)
        _check_key(c, a, "depreciation")
        frm, to, nd = _windowed(c, m)
        rows = _fa_dep_rows_bs(c, m, frm, to, nd)
        return {"month": m, "label": month_label(c, m), "rows": rows, "total": r2(sum(x["amount"] for x in rows)), "no_hours": [],
                "posted": r2(val(c, "SELECT COALESCE(SUM(amount),0) FROM fa_dep WHERE month=?", (m,)))}
    return fa_dep_preview


def _w_fa_dep_run(orig):
    def fa_dep_run(c, u, a):
        m = (a.get("month") or "")[:7]
        if not is_bs(m):
            if nepali_runs(c) and m:
                _check_key(c, a, "depreciation")
            return orig(c, u, a)
        import api_fa as FA
        _check_key(c, a, "depreciation")
        frm, to, nd = _windowed(c, m)
        FA.assert_open(c, u, to)
        rows = _fa_dep_rows_bs(c, m, frm, to, nd)
        if not rows:
            raise ApiError("Nothing to depreciate for %s (already posted, or no hours on the logsheets)." % _CL().period_label(m))
        by_proj = {}
        for x in rows:
            for p_, v in x["split"].items():
                by_proj.setdefault(p_, []).append((x, v))
        vids = {}
        for p_, xs in by_proj.items():
            lines = []
            for x, v in xs:
                eid = x["ref_id"] if x["kind"] == "equipment" else None
                lines.append({"role": "depreciation", "debit": r2(v), "narration": "NAS 16 depreciation %s %s" % (x["code"], m),
                              "equipment_id": eid})
                lines.append({"role": "accum_dep", "credit": r2(v), "narration": "Accumulated depreciation %s" % x["code"],
                              "equipment_id": eid})
            vids[p_] = FA._post(c, u, {"date": to, "type": "journal", "project_id": p_, "source": "fa_dep", "source_id": None,
                                       "narration": "Depreciation of plant and equipment for %s" % _CL().period_label(m)}, lines)
        for x in rows:
            p0 = list(x["split"])[0]
            ins(c, "fa_dep", {"fa_id": x["fa_id"], "comp_id": x["comp_id"], "month": m, "method": x["method"], "hours": x["hours"],
                              "amount": x["amount"], "project_id": p0, "voucher_id": vids.get(p0), "ts": now()})
            if x["comp_id"]:
                c.execute("UPDATE fa_components SET accumulated=accumulated+? WHERE id=?", (x["amount"], x["comp_id"]))
            c.execute("UPDATE fa_register SET accumulated=accumulated+? WHERE id=?", (x["amount"], x["fa_id"]))
            ins(c, "fa_costs", {"fa_id": x["fa_id"], "date": to, "category": "depreciation", "amount": x["amount"], "project_id": p0,
                                "voucher_id": vids.get(p0), "ref": "DEP " + m, "ts": now()})
            _pfp_run(c, u, "fa_dep", m, "fa", x["fa_id"], p0, x["from"], to, x["hours"], x["amount"], vids.get(p0))
            if x["kind"] == "equipment" and x["ref_id"] and not val(c, "SELECT COUNT(*) FROM dep_runs WHERE equipment_id=? AND month=?",
                                                                    (x["ref_id"], m)):
                ins(c, "dep_runs", {"equipment_id": x["ref_id"], "month": m, "amount": x["amount"], "voucher_id": vids.get(p0)})
                c.execute("UPDATE equipment SET accumulated_dep=COALESCE(accumulated_dep,0)+? WHERE id=?", (x["amount"], x["ref_id"]))
        audit(c, u, "dep_run", "fa_register", None, {"month": m, "items": len(rows)})
        return {"month": m, "items": len(rows), "total": r2(sum(x["amount"] for x in rows)), "vouchers": [v for v in vids.values() if v]}
    return fa_dep_run


def _w_fa_dep_reverse(orig):
    def fa_dep_reverse(c, u, a):
        m = (a.get("month") or "")[:7]
        if not is_bs(m):
            return orig(c, u, a)
        import api_fa as FA
        to = window_of(c, m)[1]
        me = FA.month_end

        def month_end(d):
            return to if str(d)[:7] == m else me(d)
        FA.month_end = month_end
        try:
            res = orig(c, u, a)
        finally:
            FA.month_end = me
        c.execute("DELETE FROM pfp_runs WHERE run='fa_dep' AND month=?", (m,))
        return res
    return fa_dep_reverse


# 4b. hours charged to projects: internal hire and the Fixed assets allocation never charge the same day twice
def _charged_windows(c, run, eq_id, pid):
    """(from, to) of every month the run has charged for this machine and project."""
    keys = []
    if run == "internal":
        keys = [x["month"] for x in q(c, "SELECT month FROM internal_bills WHERE equipment_id=? AND project_id=?", (eq_id, pid))]
    elif run == "alloc" and _has(c, "fa_alloc"):
        fa = _fa_row_of(c, eq_id)
        if fa:
            keys = [x["month"] for x in q(c, "SELECT month FROM fa_alloc WHERE fa_id=? AND project_id=? AND kind='charge'", (fa["id"], pid))]
    out = []
    for k in keys:
        try:
            out.append(tuple(window_of(c, k)))
        except Exception:
            pass
    return out


def _hours_free(c, eq_id, pid, start, to, other_windows):
    rows = q(c, "SELECT date, hours FROM logsheets WHERE equipment_id=? AND project_id=? AND date BETWEEN ? AND ? AND hours>0 "
                "AND dpr_id IS NULL", (eq_id, pid, start, to))
    return r2(sum(_f(x["hours"]) for x in rows if not any(w0 <= x["date"][:10] <= w1 for w0, w1 in other_windows)))


def _internal_rows_bs(c, m, frm, to):
    out = []
    pairs = q(c, "SELECT DISTINCT l.equipment_id, l.project_id, e.code, e.name, e.internal_rate FROM logsheets l JOIN equipment e "
                 "ON e.id=l.equipment_id WHERE e.ownership='owned' AND e.internal_rate>0 AND l.dpr_id IS NULL AND l.date BETWEEN ? AND ? "
                 "AND l.project_id IS NOT NULL ORDER BY e.code", (frm, to))
    for r in pairs:
        posted = q1(c, "SELECT * FROM internal_bills WHERE equipment_id=? AND project_id=? AND month=?", (r["equipment_id"], r["project_id"], m))
        if posted:
            out.append(dict(r, hours=posted["hours"], amount=posted["amount"], posted=True))
            continue
        cov = _covered(c, [x["month"] for x in q(c, "SELECT month FROM internal_bills WHERE equipment_id=? AND project_id=?",
                                                 (r["equipment_id"], r["project_id"]))])
        start = max(frm, _next(cov)) if cov else frm
        if start > to:
            continue
        h = _hours_free(c, r["equipment_id"], r["project_id"], start, to, _charged_windows(c, "alloc", r["equipment_id"], r["project_id"]))
        if h <= EPS:
            continue
        out.append(dict(r, hours=h, amount=r2(h * _f(r["internal_rate"])), posted=False, **{"from": start, "to": to}))
    return out


def _w_internal_preview(orig):
    def internal_preview(c, u, a):
        m = (a.get("month") or "")[:7]
        if not is_bs(m):
            if nepali_runs(c) and m:
                _check_key(c, a, "internal hire")
            return orig(c, u, a)
        _check_key(c, a, "internal hire")
        frm, to, _nd = _windowed(c, m)
        return _internal_rows_bs(c, m, frm, to)
    return internal_preview


def _w_internal_run(orig):
    def internal_run(c, u, a):
        m = (a.get("month") or "")[:7]
        if not is_bs(m):
            if nepali_runs(c) and m:
                _check_key(c, a, "internal hire")
            return orig(c, u, a)
        _check_key(c, a, "internal hire")
        frm, to, _nd = _windowed(c, m)
        n, total = 0, 0.0
        for r in _internal_rows_bs(c, m, frm, to):
            if r["posted"] or r["amount"] <= 0:
                continue
            vid = core.post_voucher(c, u, "journal", to, "Internal hire %s %s (%s h)" % (r["code"], _CL().period_label(m), r["hours"]),
                                    [{"role": "equipment_cost", "debit": r["amount"], "equipment_id": r["equipment_id"],
                                      "project_id": r["project_id"]},
                                     {"role": "equipment_recovery", "credit": r["amount"], "equipment_id": r["equipment_id"],
                                      "project_id": r["project_id"]}],
                                    project_id=r["project_id"], source="internal_billing", source_id=r["equipment_id"])
            ins(c, "internal_bills", {"equipment_id": r["equipment_id"], "project_id": r["project_id"], "month": m, "hours": r["hours"],
                                      "rate": r["internal_rate"], "amount": r["amount"], "voucher_id": vid})
            _pfp_run(c, u, "internal", m, "equipment", r["equipment_id"], r["project_id"], r["from"], to, r["hours"], r["amount"], vid)
            n += 1
            total += r["amount"]
        return {"count": n, "total": r2(total), "month": m, "from": frm, "to": to}
    return internal_run


def _alloc_rows_bs(c, m, frm, to):
    import api_fa as FA
    out = []
    for r in q(c, "SELECT * FROM fa_register WHERE kind='equipment' AND status='active' AND ref_id IS NOT NULL ORDER BY code"):
        rate = FA._rate_on(c, r["id"], to)
        for x in q(c, "SELECT DISTINCT project_id FROM logsheets WHERE equipment_id=? AND date BETWEEN ? AND ? AND hours>0 AND "
                      "dpr_id IS NULL AND project_id IS NOT NULL", (r["ref_id"], frm, to)):
            pid = x["project_id"]
            if val(c, "SELECT COUNT(*) FROM fa_alloc WHERE fa_id=? AND month=? AND project_id=? AND kind='charge'", (r["id"], m, pid)):
                continue
            cov = _covered(c, [y["month"] for y in q(c, "SELECT month FROM fa_alloc WHERE fa_id=? AND project_id=? AND kind='charge'",
                                                     (r["id"], pid))])
            start = max(frm, _next(cov)) if cov else frm
            if start > to:
                continue
            h = _hours_free(c, r["ref_id"], pid, start, to, _charged_windows(c, "internal", r["ref_id"], pid))
            if h <= EPS:
                continue
            out.append({"fa_id": r["id"], "code": r["code"], "name": r["name"], "project_id": pid, "hours": h, "rate": rate,
                        "amount": r2(h * rate), "no_rate": not rate, "from": start, "to": to, "equipment_id": r["ref_id"]})
    return out


def _w_fa_alloc_preview(orig):
    def fa_alloc_preview(c, u, a):
        m = (a.get("month") or "")[:7]
        if not is_bs(m):
            if nepali_runs(c) and m:
                _check_key(c, a, "the allocation")
            return orig(c, u, a)
        _check_key(c, a, "the allocation")
        frm, to, _nd = _windowed(c, m)
        rows = _alloc_rows_bs(c, m, frm, to)
        return {"month": m, "label": month_label(c, m), "rows": rows, "total": r2(sum(x["amount"] for x in rows)),
                "hours": r2(sum(x["hours"] for x in rows)), "no_rate": [x["code"] for x in rows if x["no_rate"]]}
    return fa_alloc_preview


def _w_fa_alloc_run(orig):
    def fa_alloc_run(c, u, a):
        m = (a.get("month") or "")[:7]
        if not is_bs(m):
            if nepali_runs(c) and m:
                _check_key(c, a, "the allocation")
            return orig(c, u, a)
        import api_fa as FA
        _check_key(c, a, "the allocation")
        frm, to, _nd = _windowed(c, m)
        FA.assert_open(c, u, to)
        rows = [x for x in _alloc_rows_bs(c, m, frm, to) if x["amount"] > EPS]
        if not rows:
            raise ApiError("No machine hours with a rate to charge for %s." % _CL().period_label(m))
        fy = FA.fy_bounds(c, None, to)[0]
        by_proj = {}
        for x in rows:
            by_proj.setdefault(x["project_id"], []).append(x)
        vids = {}
        for pid, xs in by_proj.items():
            lines = []
            for x in xs:
                lines.append({"role": "equip_job_cost", "debit": x["amount"], "equipment_id": x["equipment_id"],
                              "narration": "%s %sh @ %s" % (x["code"], x["hours"], x["rate"])})
                lines.append({"role": "equip_recovery", "credit": x["amount"], "equipment_id": x["equipment_id"],
                              "narration": "Equipment cost recovered %s" % x["code"]})
            vids[pid] = FA._post(c, u, {"date": to, "type": "journal", "project_id": pid, "source": "fa_alloc",
                                        "narration": "Equipment hours charged to project for %s" % _CL().period_label(m)}, lines)
        for x in rows:
            ins(c, "fa_alloc", {"fa_id": x["fa_id"], "month": m, "project_id": x["project_id"], "kind": "charge", "hours": x["hours"],
                                "rate": x["rate"], "amount": x["amount"], "fy": fy, "voucher_id": vids[x["project_id"]], "ts": now()})
            _pfp_run(c, u, "alloc", m, "fa", x["fa_id"], x["project_id"], x["from"], to, x["hours"], x["amount"], vids[x["project_id"]])
        audit(c, u, "alloc_run", "fa_alloc", None, {"month": m, "lines": len(rows)})
        return {"month": m, "lines": len(rows), "total": r2(sum(x["amount"] for x in rows))}
    return fa_alloc_run


# 4b2. the Fixed assets equipment ledger and year-end true-up count allocations made by Nepali month
def _bs_alloc(c, fa_id, s, e):
    """Allocation charges keyed by a Nepali month whose last day falls in s..e: (amount, hours, {project: amount})."""
    if not _has(c, "fa_alloc"):
        return 0.0, 0.0, {}
    amt, hrs, by = 0.0, 0.0, {}
    CL = _CL()
    for x in q(c, "SELECT month, project_id, amount, hours FROM fa_alloc WHERE fa_id=? AND kind='charge' AND month>='2070'", (fa_id,)):
        try:
            end = CL.period_bounds(c, x["month"])[1]
        except Exception:
            continue
        if s <= end <= e:
            amt += _f(x["amount"])
            hrs += _f(x["hours"])
            by[x["project_id"]] = by.get(x["project_id"], 0.0) + _f(x["amount"])
    return amt, hrs, by


def _w_fa_ledger(orig):
    def fa_ledger(c, u, a):
        d = orig(c, u, a)
        changed = False
        for r in d.get("rows") or []:
            amt, hrs, _by = _bs_alloc(c, r["fa_id"], d["from"], d["to"])
            if amt or hrs:
                changed = True
                r["charged"] = r2(r["charged"] + amt)
                r["hours"] = r2(r["hours"] + hrs)
                r["variance"] = r2(r["actual"] - r["charged"])
                r["actual_per_hour"] = r2(r["actual"] / r["hours"]) if r["hours"] else None
        if changed:
            for k in ("charged", "hours", "variance"):
                d["totals"][k] = r2(sum(x[k] for x in d["rows"]))
        return d
    return fa_ledger


def _patch_trueup():
    import api_fa as FA
    if getattr(FA.fa_trueup_preview, FLAG, False):
        return
    orig = FA.fa_trueup_preview

    def fa_trueup_preview(c, u, a):
        if not _has(c, "fa_alloc") or not val(c, "SELECT COUNT(*) FROM fa_alloc WHERE kind='charge' AND month>='2070'"):
            return orig(c, u, a)
        fy, s, e = FA.fy_bounds(c, a.get("fy"), a.get("on"))
        out = []
        for r in q(c, "SELECT * FROM fa_register WHERE kind='equipment' ORDER BY code"):
            actual = _f(val(c, "SELECT SUM(amount) FROM fa_costs WHERE fa_id=? AND date BETWEEN ? AND ?", (r["id"], s, e)))
            charges = {x["project_id"]: _f(x["a"]) for x in q(
                c, "SELECT project_id, SUM(amount) a FROM fa_alloc WHERE fa_id=? AND kind='charge' AND month BETWEEN ? "
                   "AND ? GROUP BY project_id", (r["id"], s[:7], e[:7]))}
            for pid, v in _bs_alloc(c, r["id"], s, e)[2].items():
                charges[pid] = charges.get(pid, 0.0) + v
            if not charges or not actual:
                continue
            t = FA.F.true_up(actual, charges)
            t.update({"fa_id": r["id"], "code": r["code"], "name": r["name"]})
            out.append(t)
        done = bool(val(c, "SELECT COUNT(*) FROM fa_alloc WHERE kind='true_up' AND fy=?", (fy,)))
        return {"fy": fy, "date": e, "rows": out, "variance": r2(sum(x["variance"] for x in out)), "posted": done}
    setattr(fa_trueup_preview, FLAG, True)
    fa_trueup_preview._orig = orig
    FA.fa_trueup_preview = fa_trueup_preview
    cur = inv.FUNCS.get("fa.trueup_preview")
    if cur and cur[0] is orig:
        inv.FUNCS["fa.trueup_preview"] = (fa_trueup_preview, cur[1], cur[2], cur[3])


# 4c. hire bills and small-asset hire
def _w_hire_bill_bs(orig):
    def hire_bill(c, u, a):
        m = (a.get("month") or "")[:7]
        if not is_bs(m):
            if nepali_runs(c) and m:
                _check_key(c, a, "hire bills")
            return orig(c, u, a)
        _check_key(c, a, "hire bills")
        core.need(a, "agreement_id")
        ag = get(c, "hire_agreements", int(a["agreement_id"]), "Hire agreement")
        if q1(c, "SELECT id FROM hire_bills WHERE agreement_id=? AND month=?", (ag["id"], m)):
            raise ApiError("This month is already billed.")
        frm, to, nd = _windowed(c, m)
        cov = _covered(c, [x["month"] for x in q(c, "SELECT month FROM hire_bills WHERE agreement_id=?", (ag["id"],))])
        start = max(frm, _next(cov)) if cov else frm
        if start > to:
            raise ApiError("This agreement is already billed to %s." % cov)
        logs = q(c, "SELECT date, hours, status FROM logsheets WHERE equipment_id=? AND project_id=? AND date BETWEEN ? AND ?",
                 (ag["equipment_id"], ag["project_id"], start, to))
        ok = [x for x in logs if x["status"] == "approved"]
        pending = r2(sum(_f(x["hours"]) for x in logs if x["status"] != "approved"))
        if ag["unit"] == "hour":
            units = sum(_f(x["hours"]) for x in ok)
        elif ag["unit"] == "day":
            units = len({x["date"] for x in ok if _f(x["hours"]) > 0})
        else:
            units = _days(start, to) / float(nd)
        frac = _days(start, to) / float(nd)
        billed = max(units, _f(ag["min_units"]) * frac)
        first = not val(c, "SELECT COUNT(*) FROM hire_bills WHERE agreement_id=?", (ag["id"],))
        amount = r2(billed * _f(ag["rate"]))
        eq = get(c, "equipment", ag["equipment_id"])
        acc = val(c, "SELECT id FROM accounts WHERE role='hire_cost'")
        if not acc:
            raise ApiError("Set an account with role 'hire_cost'.")
        lab = _CL().period_label(m)
        iid = ins(c, "invoices", {"kind": "purchase", "party_id": ag["vendor_id"], "project_id": ag["project_id"], "date": to,
                                  "party_inv_no": a.get("party_inv_no"), "status": "draft", "source": "hire",
                                  "remarks": "Hire of %s for %s (%s to %s)" % (eq["name"], lab, start, to), "created_by": u["id"]})
        ins(c, "invoice_lines", {"invoice_id": iid, "description": "%s %s: %s %s (approved %s; %s h not yet approved, not billed)" %
                                 (eq["code"], lab, r2(billed), ag["unit"], r2(units), pending), "qty": r2(billed), "rate": ag["rate"],
                                 "vat_rate": ag["vat_rate"] or 0, "amount": amount, "account_id": acc, "equipment_id": eq["id"]})
        if first and ag["mob_cost"]:
            ins(c, "invoice_lines", {"invoice_id": iid, "description": "Mobilisation %s" % eq["code"], "qty": 1, "rate": ag["mob_cost"],
                                     "vat_rate": ag["vat_rate"] or 0, "amount": ag["mob_cost"], "account_id": acc, "equipment_id": eq["id"]})
        ins(c, "hire_bills", {"agreement_id": ag["id"], "month": m, "units": r2(units), "billed_units": r2(billed), "amount": amount,
                              "invoice_id": iid})
        _pfp_run(c, u, "hire", m, "agreement", ag["id"], ag["project_id"], start, to, r2(units), amount, None)
        return {"invoice_id": iid, "units": r2(units), "billed": r2(billed), "not_approved_hours": pending, "from": start, "to": to}
    return hire_bill


def _w_sa_run(orig):
    def sa_run(c, u, a):
        m = (a.get("month") or "")[:7]
        if not is_bs(m):
            if nepali_runs(c) and m:
                _check_key(c, a, "small-asset hire")
            return orig(c, u, a)
        _check_key(c, a, "small-asset hire")
        import api_exec as EX
        frm, to, nd = _windowed(c, m)
        out = []
        for p_ in q(c, "SELECT * FROM sa_pools WHERE active=1 AND rate>0"):
            for pid in sorted({x["project_id"] for x in q(c, "SELECT DISTINCT project_id FROM sa_moves WHERE pool_id=? AND "
                                                             "project_id IS NOT NULL", (p_["id"],))}):
                if q1(c, "SELECT id FROM sa_runs WHERE month=? AND pool_id=? AND project_id=?", (m, p_["id"], pid)):
                    continue
                cov = _covered(c, [x["month"] for x in q(c, "SELECT month FROM sa_runs WHERE pool_id=? AND project_id=?", (p_["id"], pid))])
                start = max(frm, _next(cov)) if cov else frm
                if start > to:
                    continue
                ud = EX._unit_days(c, p_["id"], pid, start, to)
                if ud <= EPS:
                    continue
                amt = r2(ud * p_["rate"] if p_["rate_basis"] == "day" else ud / float(nd) * p_["rate"])
                rid = ins(c, "sa_runs", {"month": m, "pool_id": p_["id"], "project_id": pid, "unit_days": ud, "amount": amt, "ts": now()})
                vid = core.post_voucher(c, u, "journal", to, "Small-asset hire %s %s %s unit-days" % (p_["code"], _CL().period_label(m), ud),
                                        [{"role": "equipment_cost", "debit": amt, "project_id": pid},
                                         {"role": "equipment_recovery", "credit": amt, "project_id": pid}],
                                        project_id=pid, source="sa_hire", source_id=rid)
                upd(c, "sa_runs", rid, {"voucher_id": vid})
                _pfp_run(c, u, "sa", m, "pool", p_["id"], pid, start, to, ud, amt, vid)
                out.append({"pool": p_["code"], "project_id": pid, "unit_days": ud, "amount": amt, "from": start, "to": to})
        audit(c, u, "run", "sa_runs", None, {"month": m, "rows": len(out)})
        return out
    return sa_run


@api("pfp.months", "project", "view")
def pfp_months(c, u, a):
    """Nepali months for the run screens: the last 18 and the current one, newest first, with the days each covers."""
    CL = _CL()
    cur = CL.period_of_date(c, today())
    out = []
    for i in range(0, 19):
        k = CL._shift(cur, -i)
        frm, to = CL.period_bounds(c, k)
        out.append({"key": k, "label": CL.period_label(k), "from": frm, "to": to, "complete": to < today()})
    return {"nepali": nepali_runs(c), "months": out, "default": next((x["key"] for x in out if x["complete"]), cur)}


@api("pfp.runs_switch", "accounts", "approve")
def pfp_runs_switch(c, u, a):
    """Accounts switches every monthly run to Nepali months (or back). Shows, per run, the first day the next run covers."""
    want = "nepali" if a.get("nepali", True) not in (False, 0, "0", "false") else "english"
    plan = runs_plan(c)
    if a.get("preview"):
        return {"run_months": want, "plan": plan}
    if want == (setting(c, "run_months") or "english"):
        return {"run_months": want, "plan": plan}
    _set(c, "run_months", want)
    _record(c, u, "run_months", want, None, plan, a.get("note"))
    return {"run_months": want, "plan": plan}


def runs_plan(c):
    """Per run, the last day already charged and where the first Nepali run starts."""
    CL = _CL()
    out = []
    cur = CL.period_of_date(c, today())
    nxt = CL._shift(cur, -1)
    for run, sql, label in (("dep", "SELECT month FROM dep_runs", "Equipment and Fixed assets depreciation"),
                            ("internal", "SELECT month FROM internal_bills", "Internal hire"),
                            ("alloc", "SELECT month FROM fa_alloc WHERE kind='charge'", "Fixed assets allocation"),
                            ("hire", "SELECT month FROM hire_bills", "Hire bills"),
                            ("sa", "SELECT month FROM sa_runs", "Small-asset hire")):
        try:
            last = _covered(c, [x["month"] for x in q(c, sql)])
        except Exception:
            last = None
        if last:
            k = CL.period_of_date(c, _next(last))
            start = _next(last)
        else:
            k, start = nxt, CL.period_bounds(c, nxt)[0]
        w0, w1 = CL.period_bounds(c, k)
        out.append({"run": run, "label": label, "last_charged_to": last, "next_month": k,
                    "next": "%s: %s to %s%s" % (CL.period_label(k), start, w1, " (part month: the days before were charged by "
                                                "the English month)" if start > w0 else "")})
    return out


# ───────────────────────────── start-up ─────────────────────────────
def _default(c, key, new_value, old_value):
    if val(c, "SELECT COUNT(*) FROM settings WHERE key=?", (key,)):
        return
    used = val(c, "SELECT COUNT(*) FROM vouchers") if _has(c, "vouchers") else 0
    c.execute("INSERT OR IGNORE INTO settings(key, value) VALUES(?,?)", (key, old_value if used else new_value))


def init_pfp(c):
    c.executescript(SCHEMA)
    _default(c, "pfp_on", "1", "0")
    _default(c, "run_months", "nepali", "english")
    _default(c, "eqcc_from", "", "")
    _default(c, "po_budget_block", "0", "0")
    c.commit()
    _patch_cost_rows()
    _patch_cvr()
    _patch_post()
    _patch_evm()
    _wrap("rep.pl", _w_rep_pl)
    _wrap("rep.budget", _w_rep_budget)
    _wrap("ws.project_cost", _w_ws_project_cost)
    _wrap("ws.company_overview", _w_company_overview)
    _wrap("cl.budget_import", _w_budget_import)
    _wrap("po.budget", _w_po_budget)
    _wrap("po.approve", _w_po_approve)
    _wrap("fa.ledger", _w_fa_ledger)
    _patch_trueup()
    for name, fac in (("dep.preview", _w_dep_preview), ("dep.run", _w_dep_run), ("fa.dep_preview", _w_fa_dep_preview),
                      ("fa.dep_run", _w_fa_dep_run), ("fa.dep_reverse", _w_fa_dep_reverse), ("internal.preview", _w_internal_preview),
                      ("internal.run", _w_internal_run), ("fa.alloc_preview", _w_fa_alloc_preview), ("fa.alloc_run", _w_fa_alloc_run),
                      ("hire.bill", _w_hire_bill_bs), ("sa.run", _w_sa_run)):
        _wrap(name, fac)
