"""
Cost and resource integration (BuildCore 2.28).

Phase 6 of the master development prompt (sections 16 to 19), built on what BuildCore already records: the 2.24
CVR and control budget, the 2.25 reported and accepted DPR quantities, the 2.26 IPC stages and receipts, the 2.27
forecast, purchase orders, subcontract orders, the store, rate analysis and the DPR labour and machine lines.
Nothing here posts, changes a balance or alters an existing table; it reads and explains.

  1. Cost to complete and profit, per cost code and project:
       remaining cost = the CVR's cost to complete, or the open commitments if they are larger (never both),
       forecast final cost = cost to date + remaining cost,
       forecast final profit = approved contract revenue - forecast final cost - allocated head-office overhead
                               - financing cost.
     Unapproved variations and claims are shown beside it and never counted as revenue.
  2. Progress to cash, per BOQ item: planned to date, reported by site, accepted, measured, billed, certified and
     cash received. A DPR quantity is never billing. Work behind plan is turned into the billing and cash it holds
     back, labelled as an estimate.
  3. Resources against the work done: labour man-days and machine hours expected from the rate analysis for the
     quantities reported, against what the DPRs show; machine utilisation, breakdowns, idle hire, fuel and repairs;
     material use against theoretical consumption (the existing store reconciliation).
  4. Before a purchase order is approved: stock, outstanding orders, the need date, supplier terms and the payment
     date they give, the project budget, the company cash forecast in that week, and the activities that wait
     for the material.
"""
import json
import math
from datetime import date, timedelta

import core
from core import ApiError, audit, q, q1, r2, setting, today, val
import api_inventory as inv
from api_inventory import api

VERSION = "2.28.0"
POSTED = "v.status IN ('posted','reversed')"
EPS = 1e-6

DEFAULTS = {
    "ctc_oh_pct": "",          # head-office overhead as % of revenue; blank = last 12 months' overhead / revenue
    "ctc_prod_low": "80",      # labour or machine productivity below this % of the norm is flagged
    "ctc_behind_pct": "10",    # an item more than this % behind its planned quantity to date is flagged
    "ctc_bd_days": "3",        # breakdowns on this many days or more in the period is a recurring breakdown
    "ctc_hire_idle_pct": "25",  # a hired machine idle for more than this % of its booked hours is flagged
}
DPR_REPORTED = ("submitted", "checked", "approved")


def init_ctc(c):
    for k, v in DEFAULTS.items():
        if q1(c, "SELECT key FROM settings WHERE key=?", (k,)) is None:
            c.execute("INSERT INTO settings(key, value) VALUES(?,?)", (k, v))


def sf(c, k):
    v = setting(c, k)
    if v in (None, ""):
        v = DEFAULTS.get(k)
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _d(s):
    try:
        return date.fromisoformat(str(s)[:10]) if s else None
    except ValueError:
        return None


def _CL():
    import api_costlink as CL
    return CL


def _need_project(c, u, pid, what="see project cost control"):
    CL = _CL()
    CL._check_project(c, u, pid)
    CL.need_right(c, u, "view", what)


def _has(c, table):
    return bool(val(c, "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?", (table,)))


def _can(u, module, action):
    return bool(u and (u.get("role") == "admin" or u.get("system") or core.can(u, module, action)))


# ───────────────────────────── commitments ─────────────────────────────
def commitments(c, pid):
    """Open purchase-order lines (ordered, not yet received) and subcontract order items (ordered, not yet billed),
    at order rates without VAT, with the BOQ item they are coded to (None when not coded)."""
    out = []
    for r in q(c, "SELECT p.id po_id, p.no, p.date, p.delivery_date, p.vendor_id, p.status, l.id line_id, l.material_id, "
                  "l.description, l.qty, l.received_qty, l.rate, l.unit, l.boq_item_id FROM po_lines l JOIN po p ON p.id=l.po_id "
                  "WHERE p.project_id=? AND p.status IN ('approved','partially_received')", (pid,)):
        open_q = max(0.0, (r["qty"] or 0) - min(r["received_qty"] or 0, r["qty"] or 0))
        if open_q * (r["rate"] or 0) < 0.5:
            continue
        out.append({"kind": "po", "doc_id": r["po_id"], "doc_no": r["no"], "date": r["date"], "due": r["delivery_date"],
                    "party_id": r["vendor_id"], "description": r["description"], "boq_item_id": r["boq_item_id"],
                    "qty": round(open_q, 4), "unit": r["unit"], "rate": r["rate"], "amount": r2(open_q * (r["rate"] or 0)),
                    "link": "#/proc/po?id=%s" % r["po_id"]})
    if _has(c, "sc_orders"):
        for r in q(c, "SELECT o.id, o.no, o.date, o.end_date, o.party_id, i.id item_id, i.boq_item_id, i.description, i.qty, i.rate, "
                      "i.unit FROM sc_order_items i JOIN sc_orders o ON o.id=i.order_id WHERE o.project_id=? AND "
                      "o.status IN ('approved','active','running')", (pid,)):
            billed = val(c, "SELECT SUM(bi.qty) FROM sc_bill_items bi JOIN sc_bills b ON b.id=bi.bill_id WHERE bi.order_item_id=? AND "
                            "b.status NOT IN ('draft','rejected','cancelled')", (r["item_id"],)) or 0
            open_q = max(0.0, (r["qty"] or 0) - billed)
            if open_q * (r["rate"] or 0) < 0.5:
                continue
            out.append({"kind": "subcontract", "doc_id": r["id"], "doc_no": r["no"], "date": r["date"], "due": r["end_date"],
                        "party_id": r["party_id"], "description": r["description"], "boq_item_id": r["boq_item_id"],
                        "qty": round(open_q, 4), "unit": r["unit"], "rate": r["rate"], "amount": r2(open_q * (r["rate"] or 0)),
                        "link": "#/x/sub"})
    return out


# ───────────────────────────── overhead and financing ─────────────────────────────
def oh_rate(c):
    """Head-office overhead as a share of revenue: the setting, else the next 12 months' overhead (budget, or the last
    12 months' average) over the last 12 months' revenue. None when it cannot be worked out."""
    fixed = setting(c, "ctc_oh_pct")
    if fixed not in (None, ""):
        try:
            return float(fixed) / 100, "set at %s%% of revenue" % fixed
        except ValueError:
            pass
    import api_cash as CA
    k0 = CA.mkey(date.today())
    oh, budgeted = CA.oh_monthly(c, [CA.add_months(k0, i) for i in range(12)])
    annual = sum(oh.values())
    since = (date.today() - timedelta(days=365)).isoformat()
    rev = val(c, "SELECT SUM(l.credit-l.debit) FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id JOIN accounts a ON "
                 "a.id=l.account_id WHERE a.type='income' AND " + POSTED + " AND v.date>=?", (since,)) or 0
    if annual <= 0.5:
        return 0.0, "no head-office overhead recorded"
    if rev <= 0.5:
        return None, "Not available: no revenue in the last 12 months to spread head-office overhead over"
    return annual / rev, "head-office overhead %s (%s) / revenue %s in the last 12 months = %.2f%%" % (
        _m(annual), "budget" if budgeted else "last 12 months", _m(rev), 100 * annual / rev)


def financing(c, pid):
    """Interest on the money the project will need from today: the project's own cash curve (schedule and payment
    terms) at the company's borrowing rate, as in the 12-month cash budget. An estimate."""
    import api_cash as CA
    try:
        res = CA.project_cash(c, pid, "early", None, 0, 0.0, CA.mkey(date.today()))
    except Exception as e:  # no schedule, no terms
        return None, "Not available: %s" % str(e)[:120], None
    rate = setting(c, "cash_interest_pct") or "12"
    return r2(res.get("financing_cost") or 0), "project cash curve from this month at %s%% a year; peak need %s in %s" % (
        rate, _m(res.get("peak_cash") or 0), res.get("peak_month") or "-"), res


def _m(x):
    try:
        return "{:,.2f}".format(float(x or 0))
    except (TypeError, ValueError):
        return str(x)


# ───────────────────────────── 1. cost to complete and profit ─────────────────────────────
def project_ctc(c, pid, asof=None):
    CL = _CL()
    asof = asof or today()
    p = q1(c, "SELECT * FROM projects WHERE id=?", (pid,))
    if not p:
        raise ApiError("Project not found.")
    rep = CL.cvr(c, pid, asof)
    com = commitments(c, pid)
    by_boq = {}
    for x in com:
        by_boq.setdefault(x["boq_item_id"], []).append(x)
    rows = []
    T = {"budget_original": 0.0, "budget_current": 0.0, "cost": 0.0, "committed": 0.0, "ctc": 0.0, "remaining": 0.0,
         "uncommitted": 0.0, "eac": 0.0, "forecast_value": 0.0, "value": 0.0}
    have_budget = False
    for r in rep["rows"]:
        coms = by_boq.pop(r.get("boq_item_id"), []) if r.get("boq_item_id") else []
        committed = r2(sum(x["amount"] for x in coms))
        ctc = r["ctc"] or 0.0
        remaining = max(ctc, committed)
        eac = (r["cost"] or 0) + remaining
        bc = r.get("budget_current")
        flags = list(r.get("flags") or [])
        if bc is not None:
            have_budget = True
            if eac > bc + 0.5:
                flags.append("over_budget")
            if committed > max(0.0, bc - (r["cost"] or 0)) + 0.5:
                flags.append("commitments_over_budget")
        if committed > ctc + 0.5:
            flags.append("forecast_raised_to_commitments")
        if r["kind"] == "boq" and (r.get("forecast_basis") or "") == "no budget" and (r.get("qty_total") or 0) - (r.get("qty_done") or 0) > EPS:
            flags.append("no_forecast")
        row = {"code_id": r["code_id"], "code": r["code"], "name": r["name"], "kind": r["kind"], "boq_item_id": r.get("boq_item_id"),
               "unit": r.get("unit"), "qty_total": r.get("qty_total"), "qty_done": r.get("qty_done"), "done_pct": r.get("done_pct"),
               "budget_original": r.get("budget_original"), "budget_current": bc, "cost": r2(r["cost"]),
               "cost_posted": r.get("cost_posted"), "cost_waiting": r.get("cost_waiting"), "cost_accrued": r.get("cost_accrued"),
               "committed": committed, "ctc": r2(ctc), "remaining": r2(remaining), "uncommitted": r2(remaining - min(committed, remaining)),
               "eac": r2(eac), "value": r.get("value") or 0.0, "forecast_value": r.get("forecast_value") or 0.0,
               "gross": r2((r.get("forecast_value") or 0) - eac), "cpi": r.get("cpi"), "forecast_basis": r.get("forecast_basis"),
               "budget_var": r2(bc - eac) if bc is not None else None, "flags": flags, "commitments": len(coms)}
        rows.append(row)
        for k in T:
            T[k] += row.get(k) or 0.0
    # commitments not coded to an item of this project's CVR
    uncoded = [x for v in by_boq.values() for x in v]
    unc_amt = r2(sum(x["amount"] for x in uncoded))
    raise_by = max(0.0, (T["committed"] + unc_amt) - T["remaining"])
    T["committed"] += unc_amt
    T["remaining"] += raise_by
    T["eac"] += raise_by
    T["uncommitted"] = max(0.0, T["remaining"] - T["committed"])
    T = {k: r2(v) for k, v in T.items()}
    if not have_budget:
        T["budget_original"] = T["budget_current"] = None
    revenue = T["forecast_value"]
    rate, oh_basis = oh_rate(c)
    oh = r2(rate * revenue) if rate is not None else None
    oh_to_date = r2(rate * T["value"]) if rate is not None else None
    fin, fin_basis, _cash = financing(c, pid)
    gross = r2(revenue - T["eac"])
    net = r2(gross - (oh or 0) - (fin or 0)) if oh is not None and fin is not None else None
    # what is not revenue yet
    potential = []
    if _has(c, "variations"):
        for v in q(c, "SELECT v.*, b.code boq_code, COALESCE(b.revised_rate, b.rate) brate FROM variations v LEFT JOIN boq_items b ON "
                      "b.id=v.boq_item_id WHERE v.project_id=? AND COALESCE(v.status,'identified') NOT IN ('approved','rejected',"
                      "'cancelled','closed')", (pid,)):
            amt = v["est_value"] if v["est_value"] else (v["var_qty"] or 0) * (v["new_rate"] or v["brate"] or 0)
            potential.append({"kind": "variation", "ref": v["no"], "title": v["title"], "status": v["status"], "amount": r2(amt or 0)})
    claims = r2(rep["total"].get("claims_pending") or 0)
    if claims > 0.5:
        potential.append({"kind": "claims", "ref": "Claims register", "title": "Claims submitted, not yet agreed", "status": "pending",
                          "amount": claims})
    # alerts, each with its basis
    alerts = []
    nof = [r for r in rows if "no_forecast" in r["flags"]]
    if nof:
        alerts.append({"key": "forecast_incomplete", "severity": "high", "text": "Forecast incomplete: %d item(s) worth %s of revenue have no budget "
                       "and no cost yet, so their remaining cost counts as zero and the profit is overstated. Add them to the control budget." %
                       (len(nof), _m(sum(r["forecast_value"] - r["value"] for r in nof))), "items": [r["code"] for r in nof]})
    if T["budget_current"] is not None and T["eac"] > T["budget_current"] + 0.5:
        alerts.append({"key": "cost_overrun", "severity": "high", "text": "Forecast final cost %s is above the current budget %s by %s" %
                       (_m(T["eac"]), _m(T["budget_current"]), _m(T["eac"] - T["budget_current"])),
                       "items": [r["code"] for r in rows if "over_budget" in r["flags"]]})
    over_c = [r for r in rows if "commitments_over_budget" in r["flags"]]
    if over_c:
        alerts.append({"key": "commitments_high", "severity": "medium", "text": "%d item(s) have open orders above their remaining budget" % len(over_c),
                       "items": [r["code"] for r in over_c]})
    low = [r for r in rows if "cpi_low" in r["flags"]]
    if low:
        alerts.append({"key": "productivity", "severity": "medium", "text": "%d item(s) earn less than their cost (CPI below %s)" %
                       (len(low), setting(c, "cl_flag_cpi") or "0.95"), "items": [r["code"] for r in low]})
    lk = CL._last_locked(c, pid)
    if lk:
        prev = (json.loads(lk["summary"] or "{}").get("total") or {}).get("forecast_margin_pct")
        cur = round(100 * gross / revenue, 2) if revenue else None
        drop = float(setting(c, "cl_flag_margin_drop") or 3)
        if prev is not None and cur is not None and cur < prev - drop:
            alerts.append({"key": "margin_fade", "severity": "high", "text": "Forecast gross margin %s%% is %.1f points below %s%% at the %s close" %
                           (cur, prev - cur, prev, CL.period_label(lk["period"])), "items": []})
    if net is not None and net < -0.5:
        alerts.append({"key": "net_loss", "severity": "high", "text": "Forecast final result after overhead and financing is a loss of %s" % _m(-net),
                       "items": []})
    elif gross < -0.5:
        alerts.append({"key": "gross_loss", "severity": "high", "text": "Forecast final cost exceeds revenue by %s" % _m(-gross), "items": []})
    for f_ in rep.get("flags") or []:
        if f_["key"] in ("billing_lag",):
            alerts.append({"key": f_["key"], "severity": "medium", "text": f_["text"], "items": []})
    return {"project": {"id": p["id"], "code": p["code"], "name": p["name"], "contract_value": p.get("contract_value")},
            "as_of": asof, "rows": rows, "total": T, "uncoded_commitments": uncoded, "uncoded_amount": unc_amt,
            "raised_by_commitments": r2(raise_by),
            "revenue": revenue, "value_to_date": T["value"], "gross": gross, "gross_pct": round(100 * gross / revenue, 2) if revenue else None,
            "overhead": oh, "overhead_to_date": oh_to_date, "overhead_rate_pct": round(100 * rate, 2) if rate is not None else None,
            "overhead_basis": oh_basis, "financing": fin, "financing_basis": fin_basis, "net": net,
            "net_pct": round(100 * net / revenue, 2) if net is not None and revenue else None,
            "incomplete": bool(nof), "incomplete_items": [r["code"] for r in nof],
            "potential": potential, "potential_total": r2(sum(x["amount"] for x in potential)), "alerts": alerts,
            "budget_version": rep.get("budget_version"), "cvr_flags": rep.get("flags") or []}


@api("ctc.project")
def ctc_project(c, u, a):
    pid = int(a.get("project_id") or 0)
    if not pid:
        raise ApiError("Choose a project.")
    _need_project(c, u, pid, "see cost to complete")
    return project_ctc(c, pid, a.get("as_of"))


@api("ctc.commitments")
def ctc_commitments(c, u, a):
    pid = int(a.get("project_id") or 0)
    _need_project(c, u, pid, "see commitments")
    rows = commitments(c, pid)
    if a.get("boq_item_id") not in (None, ""):
        rows = [x for x in rows if x["boq_item_id"] == int(a["boq_item_id"])]
    elif a.get("uncoded"):
        CL = _CL()
        coded = {r["boq_item_id"] for r in q(c, "SELECT boq_item_id FROM cl_codes WHERE project_id=? AND boq_item_id IS NOT NULL", (pid,))}
        rows = [x for x in rows if x["boq_item_id"] not in coded]
        del CL
    for x in rows:
        x["party"] = val(c, "SELECT name FROM parties WHERE id=?", (x["party_id"],), "")
    return {"rows": rows, "total": r2(sum(x["amount"] for x in rows))}


@api("ctc.portfolio")
def ctc_portfolio(c, u, a):
    CL = _CL()
    CL.need_right(c, u, "view", "see forecast profit of all projects")
    allow = CL._allowed_projects(c, u)
    out = []
    for p in q(c, "SELECT id, code, name FROM projects WHERE status='active' AND COALESCE(kind,'') NOT IN ('trading','general') ORDER BY code"):
        if allow is not None and p["id"] not in allow:
            continue
        try:
            d = project_ctc(c, p["id"], a.get("as_of"))
        except ApiError as e:
            out.append({"project_id": p["id"], "code": p["code"], "name": p["name"], "error": str(e)})
            continue
        t = d["total"]
        out.append({"project_id": p["id"], "code": p["code"], "name": p["name"], "revenue": d["revenue"], "cost": t["cost"],
                    "committed": t["committed"], "remaining": t["remaining"], "eac": t["eac"], "budget": t["budget_current"],
                    "gross": d["gross"], "gross_pct": d["gross_pct"], "overhead": d["overhead"], "financing": d["financing"],
                    "net": d["net"], "net_pct": d["net_pct"], "potential": d["potential_total"], "alerts": len(d["alerts"]),
                    "alert_text": "; ".join(x["text"] for x in d["alerts"][:2]), "incomplete": d["incomplete"]})
    tot = {k: r2(sum((r.get(k) or 0) for r in out if not r.get("error"))) for k in
           ("revenue", "cost", "committed", "remaining", "eac", "gross", "overhead", "financing", "net", "potential")}
    rate, basis = oh_rate(c)
    return {"rows": out, "total": tot, "overhead_basis": basis, "interest_pct": setting(c, "cash_interest_pct") or "12"}


# ───────────────────────────── 2. progress to cash ─────────────────────────────
def planned_to_date(c, bid, asof):
    """Planned quantity to date from the schedule activities on this BOQ item, straight-line between planned start
    and finish. None when no activity carries the item."""
    acts = q(c, "SELECT * FROM activities WHERE boq_item_id=?", (bid,))
    if not acts:
        return None, None
    t = _d(asof)
    tot = 0.0
    for x in acts:
        s, f = _d(x["planned_start"]), _d(x["planned_finish"])
        pq = x["planned_qty"] or 0
        if not s or not f or pq <= 0:
            continue
        if t < s:
            continue
        span = max(1, (f - s).days + 1)
        tot += pq * min(1.0, ((t - s).days + 1) / span)
    return tot, acts


def chain(c, pid, asof=None):
    import api_fc as FC
    asof = asof or today()
    behind_pct = sf(c, "ctc_behind_pct") or 10
    since30 = (_d(asof) - timedelta(days=29)).isoformat()
    proj = q1(c, "SELECT * FROM projects WHERE id=?", (pid,))
    tm = FC.terms(c, proj)
    cycle = int(tm.get("ipc_cycle_days") or 30)
    cert = int(tm.get("cert_days") or 21)
    pay = int(tm.get("pay_days") or 28)
    ret_pct = float(tm.get("retention_pct") or proj.get("retention_pct") or 0) if isinstance(tm, dict) else 0.0
    # IPC receipts: the share of each certified IPC the client has paid
    paid_share = {}
    for i in q(c, "SELECT * FROM ipc WHERE project_id=? AND status='certified'", (pid,)):
        s = FC.ipc_state(c, i, t=asof)
        if s.get("payable"):
            paid_share[i["id"]] = (s["paid"] or 0) / s["payable"]
    accepted_on = _has(c, "udpr_work")
    rows = []
    tot = {k: 0.0 for k in ("scope_v", "planned_v", "reported_v", "accepted_v", "measured_v", "billed_v", "certified_v", "received",
                            "unmeasured_v", "unbilled_v", "behind_v", "beyond_v")}
    delays = []
    for b in q(c, "SELECT * FROM boq_items WHERE project_id=? ORDER BY code, id", (pid,)):
        rate = b["revised_rate"] if b["revised_rate"] is not None else (b["rate"] or 0)
        scope = b["revised_qty"] if b["revised_qty"] is not None else (b["qty"] or 0)
        rep_ = val(c, "SELECT SUM(w.actual_qty) FROM dpr_work w JOIN dpr d ON d.id=w.dpr_id WHERE w.boq_item_id=? AND d.date<=? AND "
                      "d.status IN ('submitted','checked','approved')", (b["id"], asof)) or 0
        rep30 = val(c, "SELECT SUM(w.actual_qty) FROM dpr_work w JOIN dpr d ON d.id=w.dpr_id WHERE w.boq_item_id=? AND d.date BETWEEN ? AND ? "
                       "AND d.status IN ('submitted','checked','approved')", (b["id"], since30, asof)) or 0
        acc = None
        if accepted_on:
            n_acc = val(c, "SELECT COUNT(x.accepted_qty) FROM udpr_work x JOIN dpr_work w ON w.id=x.work_id JOIN dpr d ON d.id=w.dpr_id "
                           "WHERE w.boq_item_id=? AND d.date<=?", (b["id"], asof)) or 0
            if n_acc:
                acc = val(c, "SELECT SUM(x.accepted_qty) FROM udpr_work x JOIN dpr_work w ON w.id=x.work_id JOIN dpr d ON d.id=w.dpr_id "
                             "WHERE w.boq_item_id=? AND d.date<=? AND d.status<>'rejected'", (b["id"], asof)) or 0
        meas = val(c, "SELECT SUM(l.qty) FROM measurement_lines l JOIN measurements m ON m.id=l.measurement_id WHERE m.status='verified' "
                      "AND l.boq_item_id=? AND m.date<=?", (b["id"], asof)) or 0
        billed = val(c, "SELECT SUM(l.qty) FROM ipc_lines l JOIN ipc i ON i.id=l.ipc_id WHERE i.status IN ('submitted','certified') AND "
                        "l.boq_item_id=? AND i.date<=?", (b["id"], asof)) or 0
        certified = 0.0
        received = 0.0
        for l in q(c, "SELECT l.qty, l.amount, i.id ipc_id, i.gross, i.net FROM ipc_lines l JOIN ipc i ON i.id=l.ipc_id WHERE "
                      "i.status='certified' AND l.boq_item_id=? AND i.date<=?", (b["id"], asof)):
            certified += l["qty"] or 0
            sh = paid_share.get(l["ipc_id"], 0)
            if sh and l["gross"]:
                received += (l["net"] or 0) * sh * (l["amount"] or 0) / l["gross"]
        plan, acts = planned_to_date(c, b["id"], asof)
        done = acc if acc is not None else rep_
        flags = []
        if plan is not None and plan > EPS and done < plan * (1 - behind_pct / 100):
            flags.append("behind_plan")
        if done - meas > EPS and (done - meas) * rate >= 0.5:
            flags.append("done_not_measured")
        if meas - billed > EPS and (meas - billed) * rate >= 0.5:
            flags.append("measured_not_billed")
        if scope and rep_ > scope + EPS:
            flags.append("beyond_scope")
        if billed - certified > EPS:
            flags.append("awaiting_certification")
        if not any([scope, rep_, meas, billed, plan]):
            continue
        row = {"boq_item_id": b["id"], "code": b["code"], "description": b["description"], "unit": b["unit"], "rate": rate,
               "scope": round(scope, 4), "planned": round(plan, 4) if plan is not None else None, "reported": round(rep_, 4),
               "accepted": round(acc, 4) if acc is not None else None, "measured": round(meas, 4), "billed": round(billed, 4),
               "certified": round(certified, 4), "received": r2(received), "progress_pct": round(100 * done / scope, 1) if scope else None,
               "unmeasured_v": r2(max(0.0, done - meas) * rate), "unbilled_v": r2(max(0.0, meas - billed) * rate),
               "beyond_qty": round(max(0.0, rep_ - scope), 4) if scope else 0.0, "flags": flags,
               "recent_per_day": round(rep30 / 30.0, 4)}
        rows.append(row)
        tot["scope_v"] += scope * rate
        tot["planned_v"] += (plan or 0) * rate
        tot["reported_v"] += rep_ * rate
        tot["accepted_v"] += (acc if acc is not None else 0) * rate
        tot["measured_v"] += meas * rate
        tot["billed_v"] += billed * rate
        tot["certified_v"] += certified * rate
        tot["received"] += received
        tot["unmeasured_v"] += row["unmeasured_v"]
        tot["unbilled_v"] += row["unbilled_v"]
        tot["beyond_v"] += row["beyond_qty"] * rate
        if "behind_plan" in flags:
            short = plan - done
            v = short * rate
            tot["behind_v"] += v
            per_day = rep30 / 30.0
            catch = math.ceil(short / per_day) if per_day > EPS else None
            slip = (math.ceil(catch / cycle) * cycle) if catch is not None else None
            delays.append({"boq_item_id": b["id"], "code": b["code"], "description": b["description"], "unit": b["unit"],
                           "planned": round(plan, 4), "done": round(done, 4), "shortfall": round(short, 4), "billing_held": r2(v),
                           "cash_held": r2(v * (1 - ret_pct / 100)), "per_day": round(per_day, 4), "catch_up_days": catch,
                           "cash_later_days": slip, "activities": [x["code"] for x in acts or []],
                           "basis": ("at the last 30 days' rate of %s %s a day, the shortfall takes about %s days; billed in a later IPC "
                                     "(every %s days), the cash comes about %s days later (certification %s + payment %s days unchanged)"
                                     % (round(per_day, 2), b["unit"] or "", catch, cycle, slip, cert, pay)) if catch is not None else
                           "no production in the last 30 days: the catch-up time cannot be estimated"})
    delays.sort(key=lambda x: -x["billing_held"])
    tot = {k: r2(v) for k, v in tot.items()}
    basis = "accepted quantities" if any(r["accepted"] is not None for r in rows) else "reported quantities (none accepted yet)"
    return {"project": {"id": proj["id"], "code": proj["code"], "name": proj["name"]}, "as_of": asof, "rows": rows, "total": tot,
            "delays": delays, "progress_basis": basis, "terms": {"cycle": cycle, "cert_days": cert, "pay_days": pay, "retention_pct": ret_pct},
            "behind_pct": behind_pct,
            "variations_open": q(c, "SELECT no, title, status FROM variations WHERE project_id=? AND COALESCE(status,'identified') NOT IN "
                                    "('approved','rejected','cancelled','closed')", (pid,)) if _has(c, "variations") else []}


@api("ctc.chain")
def ctc_chain(c, u, a):
    pid = int(a.get("project_id") or 0)
    if not pid:
        raise ApiError("Choose a project.")
    CL = _CL()
    CL._check_project(c, u, pid)
    if not (_can(u, "project", "view") or _can(u, "commercial", "view")):
        raise ApiError("Your role cannot see progress to cash (needs project or commercial view).")
    return chain(c, pid, a.get("as_of"))


# ───────────────────────────── 3. resources against the work ─────────────────────────────
def _norms(c, bid):
    """Labour man-days and machine hours per unit from the BOQ item's rate analysis (labour lines are priced per day,
    machine lines per hour)."""
    md = val(c, "SELECT SUM(qty_per_unit) FROM rate_analysis WHERE boq_item_id=? AND kind='labour'", (bid,)) if bid else None
    mh = val(c, "SELECT SUM(qty_per_unit) FROM rate_analysis WHERE boq_item_id=? AND kind='equipment'", (bid,)) if bid else None
    return md, mh


def resources(c, pid, frm, to):
    hours_day = 8.0
    cal = q1(c, "SELECT hours_day FROM sched_calendars WHERE is_default=1") if _has(c, "sched_calendars") else None
    if cal and cal["hours_day"]:
        hours_day = float(cal["hours_day"])
    low = sf(c, "ctc_prod_low") or 80
    dprs = "SELECT id FROM dpr WHERE project_id=? AND date BETWEEN ? AND ? AND status IN ('submitted','checked','approved')"
    P = (pid, frm, to)
    # labour and machines by activity
    acts = {}
    for w in q(c, "SELECT w.activity_id, w.boq_item_id, SUM(w.actual_qty) qty FROM dpr_work w WHERE w.dpr_id IN (%s) GROUP BY "
                  "w.activity_id, w.boq_item_id" % dprs, P):
        k = w["activity_id"] or ("b%s" % w["boq_item_id"])
        x = acts.setdefault(k, {"activity_id": w["activity_id"], "boq_item_id": w["boq_item_id"], "qty": 0.0, "man_days": 0.0, "ot_hours": 0.0,
                                "labour_amount": 0.0, "machine_hours": 0.0})
        x["qty"] += w["qty"] or 0
        x["boq_item_id"] = x["boq_item_id"] or w["boq_item_id"]
    for l in q(c, "SELECT activity_id, SUM(count*hours) h, SUM(count*COALESCE(ot_hours,0)) ot, SUM(amount) amt FROM dpr_labour WHERE dpr_id IN (%s) "
                  "GROUP BY activity_id" % dprs, P):
        x = acts.setdefault(l["activity_id"], {"activity_id": l["activity_id"], "boq_item_id": None, "qty": 0.0, "man_days": 0.0,
                                               "ot_hours": 0.0, "labour_amount": 0.0, "machine_hours": 0.0})
        x["man_days"] += ((l["h"] or 0) + (l["ot"] or 0)) / hours_day
        x["ot_hours"] += l["ot"] or 0
        x["labour_amount"] += l["amt"] or 0
    for e in q(c, "SELECT activity_id, SUM(hours) h FROM dpr_equipment WHERE dpr_id IN (%s) GROUP BY activity_id" % dprs, P):
        x = acts.setdefault(e["activity_id"], {"activity_id": e["activity_id"], "boq_item_id": None, "qty": 0.0, "man_days": 0.0,
                                               "ot_hours": 0.0, "labour_amount": 0.0, "machine_hours": 0.0})
        x["machine_hours"] += e["h"] or 0
    lab = []
    for k, x in acts.items():
        a_ = q1(c, "SELECT code, name, unit, boq_item_id FROM activities WHERE id=?", (x["activity_id"],)) if x["activity_id"] else None
        bid = x["boq_item_id"] or (a_ or {}).get("boq_item_id")
        b = q1(c, "SELECT code, description, unit FROM boq_items WHERE id=?", (bid,)) if bid else None
        md_u, mh_u = _norms(c, bid)
        exp_md = x["qty"] * md_u if md_u else None
        exp_mh = x["qty"] * mh_u if mh_u else None
        lp = round(100 * exp_md / x["man_days"], 1) if exp_md is not None and x["man_days"] > EPS else None
        ep = round(100 * exp_mh / x["machine_hours"], 1) if exp_mh is not None and x["machine_hours"] > EPS else None
        flags = []
        if lp is not None and lp < low:
            flags.append("labour_low")
        if ep is not None and ep < low:
            flags.append("machines_low")
        if x["qty"] <= EPS and (x["man_days"] > EPS or x["machine_hours"] > EPS):
            flags.append("no_output")
        lab.append({"activity_id": x["activity_id"], "activity": (a_ or {}).get("code") or "", "name": (a_ or {}).get("name") or (b or {}).get("description") or "Not linked to an activity",
                    "boq_item_id": bid, "boq_code": (b or {}).get("code"), "unit": (b or {}).get("unit") or (a_ or {}).get("unit"),
                    "qty": round(x["qty"], 4), "norm_md": md_u, "expected_md": round(exp_md, 2) if exp_md is not None else None,
                    "actual_md": round(x["man_days"], 2), "labour_pct": lp, "ot_hours": round(x["ot_hours"], 1),
                    "labour_amount": r2(x["labour_amount"]), "norm_mh": mh_u, "expected_mh": round(exp_mh, 2) if exp_mh is not None else None,
                    "actual_mh": round(x["machine_hours"], 2), "machine_pct": ep, "flags": flags})
    lab.sort(key=lambda r: (r["labour_pct"] if r["labour_pct"] is not None else 999))
    # machines
    bd_days = sf(c, "ctc_bd_days") or 3
    idle_lim = sf(c, "ctc_hire_idle_pct") or 25
    util_low = float(setting(c, "cl_util_low") or 50)
    fuel_var = float(setting(c, "cl_fuel_var") or 15)
    eqs = []
    for e in q(c, "SELECT de.equipment_id, SUM(de.hours) w, SUM(de.idle_hours) i, SUM(de.breakdown_hours) b, SUM(de.amount) amt, "
                  "COUNT(DISTINCT CASE WHEN de.breakdown_hours>0 THEN d.date END) bdays, COUNT(DISTINCT d.date) days FROM dpr_equipment de "
                  "JOIN dpr d ON d.id=de.dpr_id WHERE d.id IN (%s) GROUP BY de.equipment_id" % dprs, P):
        m = q1(c, "SELECT * FROM equipment WHERE id=?", (e["equipment_id"],)) or {}
        w, i, b = e["w"] or 0, e["i"] or 0, e["b"] or 0
        booked = w + i + b
        util = round(100 * w / booked, 1) if booked > EPS else None
        fuel = q1(c, "SELECT SUM(l.qty) qty, SUM(l.amount) amt FROM issue_lines l JOIN issues s ON s.id=l.issue_id WHERE s.status='posted' AND "
                     "l.equipment_id=? AND s.project_id=? AND s.date BETWEEN ? AND ?", (e["equipment_id"], pid, frm, to)) or {}
        repairs = val(c, "SELECT SUM(COALESCE(parts_cost,0)+COALESCE(labour_cost,0)+COALESCE(external_cost,0)) FROM work_orders WHERE "
                         "equipment_id=? AND COALESCE(project_id, ?)=? AND substr(COALESCE(completed_at, reported_at),1,10) BETWEEN ? AND ?",
                      (e["equipment_id"], pid, pid, frm, to)) if _has(c, "work_orders") else 0
        hired = (m.get("ownership") or "owned") != "owned"
        rent = val(c, "SELECT SUM(l.amount) FROM invoice_lines l JOIN invoices v ON v.id=l.invoice_id WHERE l.equipment_id=? AND "
                      "v.project_id=? AND v.status='posted' AND v.date BETWEEN ? AND ?", (e["equipment_id"], pid, frm, to)) if hired else 0
        cost = (rent or 0) + (fuel.get("amt") or 0) + (repairs or 0) + (0 if hired else (e["amt"] or 0))
        flags = []
        if (e["bdays"] or 0) >= bd_days:
            flags.append("recurring_breakdown")
        if util is not None and util < util_low:
            flags.append("low_utilisation")
        if hired and booked > EPS and 100 * (i + b) / booked > idle_lim:
            flags.append("idle_hire")
        if m.get("fuel_norm") and w > EPS and (fuel.get("qty") or 0) / w > m["fuel_norm"] * (1 + fuel_var / 100):
            flags.append("fuel_over_norm")
        eqs.append({"equipment_id": e["equipment_id"], "code": m.get("code"), "name": m.get("name"), "ownership": m.get("ownership") or "owned",
                    "days": e["days"], "working": round(w, 1), "idle": round(i, 1), "breakdown": round(b, 1), "breakdown_days": e["bdays"],
                    "utilisation": util, "fuel_qty": round(fuel.get("qty") or 0, 2), "fuel_cost": r2(fuel.get("amt") or 0),
                    "fuel_per_hour": round((fuel.get("qty") or 0) / w, 2) if w > EPS else None, "fuel_norm": m.get("fuel_norm"),
                    "repairs": r2(repairs or 0), "rent": r2(rent or 0), "internal": r2(0 if hired else (e["amt"] or 0)),
                    "cost": r2(cost), "cost_per_hour": r2(cost / w) if w > EPS else None, "flags": flags})
    eqs.sort(key=lambda r: (-len(r["flags"]), r["utilisation"] if r["utilisation"] is not None else 999))
    # materials: the store reconciliation (theoretical against issued, to date) and shortages
    mats, short, mnote = [], [], None
    try:
        rc = inv.FUNCS["res.consumption"][0](c, {"role": "admin", "id": 0, "system": True}, {"project_id": pid})
        mats = [dict(m_, flag=(m_["abnormal_value"] or 0) > 0.5) for m_ in rc["materials"]]
    except Exception as ex:  # no coefficients
        mnote = "Material use against theoretical consumption is not available: %s" % str(ex)[:100]
    try:
        import api_res as R
        for r in R.material_risks(c, pid) or []:
            if r.get("risk"):           # 2.29: material_risks marks a shortage with "risk"
                short.append(r)
    except Exception:
        pass
    tl = {k: r2(sum((r.get(k) or 0) for r in lab)) for k in ("expected_md", "actual_md", "labour_amount", "expected_mh", "actual_mh")}
    # productivity only where both sides are known (work with no labour on the DPR, e.g. by a subcontractor, is left out)
    lw = [r for r in lab if r["expected_md"] is not None and r["actual_md"] > EPS]
    mw = [r for r in lab if r["expected_mh"] is not None and r["actual_mh"] > EPS]
    e_, a_ = sum(r["expected_md"] for r in lw), sum(r["actual_md"] for r in lw)
    tl["labour_pct"] = round(100 * e_ / a_, 1) if a_ > EPS else None
    tl["labour_basis"] = "%s man-days earned / %s worked on %d activities with labour on the DPRs" % (round(e_, 2), round(a_, 2), len(lw))
    e_, a_ = sum(r["expected_mh"] for r in mw), sum(r["actual_mh"] for r in mw)
    tl["machine_pct"] = round(100 * e_ / a_, 1) if a_ > EPS else None
    tl["machine_basis"] = "%s h earned / %s h worked on %d activities with machines on the DPRs" % (round(e_, 2), round(a_, 2), len(mw))
    return {"from": frm, "to": to, "hours_day": hours_day, "labour": lab, "labour_total": tl, "equipment": eqs, "materials": mats,
            "shortages": short, "materials_note": mnote, "thresholds": {"productivity_low": low, "breakdown_days": bd_days,
                                                                       "hire_idle_pct": idle_lim, "utilisation_low": util_low,
                                                                       "fuel_var_pct": fuel_var}}


@api("ctc.resources")
def ctc_resources(c, u, a):
    pid = int(a.get("project_id") or 0)
    if not pid:
        raise ApiError("Choose a project.")
    _need_project(c, u, pid, "see resources against cost")
    to = a.get("to") or today()
    frm = a.get("from") or (_d(to) - timedelta(days=29)).isoformat()
    if frm > to:
        raise ApiError("'From' is after 'to'.")
    return resources(c, pid, frm, to)


# ───────────────────────────── 4. before a purchase order is approved ─────────────────────────────
def _credit_days(c, po):
    terms = (po.get("payment_terms") or "").lower()
    digits = "".join(ch if ch.isdigit() else " " for ch in terms).split()
    if "advance" in terms:
        return 0, "payment terms '%s'" % po.get("payment_terms")
    if digits:
        return int(digits[0]), "payment terms '%s'" % po.get("payment_terms")
    cd = val(c, "SELECT credit_days FROM parties WHERE id=?", (po.get("vendor_id"),), None)
    if cd is not None:
        return int(cd), "supplier's credit days"
    return 30, "30 days assumed"


def po_check(c, u, po):
    import api_cfw as CF
    pid = po["project_id"]
    t = today()
    lines = []
    total = 0.0
    for l in po["lines"]:
        mid = l.get("material_id")
        qty = float(l.get("qty") or 0)
        rate = float(l.get("rate") or 0)
        amt = qty * rate * (1 + float(l.get("vat_rate") or 0) / 100)
        total += amt
        if not mid:
            lines.append({"description": l.get("description"), "qty": qty, "amount": r2(amt), "note": "No material: stock not checked"})
            continue
        m = q1(c, "SELECT code, name, unit FROM materials WHERE id=?", (mid,)) or {}
        here = q1(c, "SELECT SUM(qty) q, SUM(value) v FROM stock_balances WHERE project_id=? AND material_id=?", (pid, mid)) or {}
        allq = val(c, "SELECT SUM(qty) FROM stock_balances WHERE material_id=?", (mid,)) or 0
        other = q(c, "SELECT p.no, p.delivery_date, l.qty-MIN(l.received_qty,l.qty) open FROM po_lines l JOIN po p ON p.id=l.po_id WHERE "
                     "l.material_id=? AND p.project_id=? AND p.status IN ('approved','partially_received','pending_approval') AND p.id<>?",
                  (mid, pid, po.get("id") or 0))
        need = None
        if l.get("pr_line_id"):
            need = q1(c, "SELECT r.no, r.required_by, l.qty FROM pr_lines l JOIN pr r ON r.id=l.pr_id WHERE l.id=?", (l["pr_line_id"],))
        elif po.get("pr_id"):
            need = q1(c, "SELECT r.no, r.required_by, l.qty FROM pr_lines l JOIN pr r ON r.id=l.pr_id WHERE r.id=? AND l.material_id=?",
                      (po["pr_id"], mid))
        # next 30 days of scheduled use, from the coefficients on activities starting or running
        demand = 0.0
        for a_ in q(c, "SELECT a.id, a.planned_qty, a.actual_qty, a.planned_start, a.planned_finish, mc.qty_per_unit, mc.wastage_pct FROM "
                       "activities a JOIN material_coefficients mc ON mc.boq_item_id=a.boq_item_id WHERE a.project_id=? AND "
                       "mc.material_id=? AND a.actual_finish IS NULL", (pid, mid)):
            s, f = _d(a_["planned_start"]), _d(a_["planned_finish"])
            if not s or not f:
                continue
            w0, w1 = max(_d(t), s), min(_d(t) + timedelta(days=30), f)
            if w1 < w0:
                continue
            rem = max(0.0, (a_["planned_qty"] or 0) - (a_["actual_qty"] or 0))
            left = max(1, (f - max(_d(t), s)).days + 1)
            demand += rem * ((w1 - w0).days + 1) / left * (a_["qty_per_unit"] or 0) * (1 + (a_["wastage_pct"] or 0) / 100)
        lines.append({"material_id": mid, "material": "%s %s" % (m.get("code") or "", m.get("name") or ""), "unit": m.get("unit"),
                      "qty": qty, "amount": r2(amt), "stock_here": round(here.get("q") or 0, 3), "stock_value_here": r2(here.get("v") or 0),
                      "stock_company": round(allq, 3), "on_order": round(sum(x["open"] or 0 for x in other), 3),
                      "orders": [x["no"] for x in other], "need_no": (need or {}).get("no"), "need_by": (need or {}).get("required_by"),
                      "need_qty": (need or {}).get("qty"), "demand_30": round(demand, 3),
                      "cover_after": round((here.get("q") or 0) + sum(x["open"] or 0 for x in other) + qty - demand, 3)})
    days, days_basis = _credit_days(c, po)
    base = po.get("delivery_date") or po.get("date") or t
    pay_date = (_d(base) + timedelta(days=days)).isoformat()
    # project budget: the 2.24 control budget if there is one, else the older material budget check
    budget = None
    try:
        d = project_ctc(c, pid)
        T = d["total"]
        counted = po.get("status") in ("approved", "partially_received")
        if T.get("budget_current") is not None:
            left = T["budget_current"] - T["cost"] - T["committed"]
            budget = {"basis": "control budget (current version)", "budget": T["budget_current"], "cost": T["cost"],
                      "committed": T["committed"], "this_po": r2(0 if counted else po.get("subtotal") or total),
                      "left_after": r2(left - (0 if counted else (po.get("subtotal") or total)))}
    except Exception:
        pass
    if budget is None:
        import api_finance as F
        b = F.budget_check(c, pid)
        if b.get("budget"):
            budget = {"basis": "material budget", "budget": b["budget"], "cost": b["actual"], "committed": b["committed"],
                      "stock": b["stock"], "this_po": r2(po.get("subtotal") or total), "left_after": r2(b["available"] - (po.get("subtotal") or total))}
    # company cash in the payment week (only for people who may see company cash)
    cash = None
    if _can(u, "accounts", "view"):
        try:
            CF._need(c, u)
            f = CF.build(c, u, 0, 0.0)
            wk = None
            for w in f["weeks"]:
                if w["start"] <= pay_date <= w["end"]:
                    wk = w
            counted = po.get("status") in ("approved", "partially_received")
            if wk:
                cash = {"week": wk["week"], "start": wk["start"], "available": wk["available"], "this_po": r2(0 if counted else total),
                        "available_after": r2(wk["available"] - (0 if counted else total)),
                        "lowest_after": r2(min(w["available"] for w in f["weeks"] if w["week"] >= wk["week"]) - (0 if counted else total)),
                        "counted": counted}
            else:
                cash = {"week": None, "note": "Payment falls after the 13-week forecast (%s)." % pay_date if pay_date > f["weeks"][-1]["end"]
                        else "Payment date %s is already due." % pay_date}
        except ApiError as e:
            cash = {"week": None, "note": str(e).replace("PROJECT_DENIED: ", "")}
    else:
        cash = {"week": None, "note": "The company cash forecast needs accounts view; ask accounts to confirm the cash position."}
    # activities that wait for these materials
    waits = []
    mids = [l["material_id"] for l in lines if l.get("material_id")]
    if mids:
        for a_ in q(c, "SELECT DISTINCT a.id, a.code, a.name, a.planned_start, a.es, a.tf, a.actual_start, mc.material_id FROM activities a "
                       "JOIN material_coefficients mc ON mc.boq_item_id=a.boq_item_id WHERE a.project_id=? AND a.actual_finish IS NULL AND "
                       "mc.material_id IN (%s) ORDER BY COALESCE(a.es, a.planned_start)" % ",".join(map(str, mids)), (pid,)):
            start = a_["es"] or a_["planned_start"]
            tf = a_["tf"]
            deliver = po.get("delivery_date")
            ln_ = next((l for l in lines if l.get("material_id") == a_["material_id"]), {})
            if a_["actual_start"] or (start and start <= t):
                # already running: the material is needed until the stock on site runs out
                per_day = (ln_.get("demand_30") or 0) / 30.0
                latest = (_d(t) + timedelta(days=int((ln_.get("stock_here") or 0) / per_day))).isoformat() if per_day > EPS else None
            else:
                latest = (_d(start) + timedelta(days=int(tf or 0))).isoformat() if start else None
            waits.append({"activity": a_["code"], "name": a_["name"], "started": bool(a_["actual_start"]), "start": start,
                          "float_days": tf, "latest_delivery": latest,
                          "material": next((l["material"] for l in lines if l.get("material_id") == a_["material_id"]), ""),
                          "late": bool(deliver and latest and deliver > latest), "running": bool(a_["actual_start"] or (start and start <= t))})
    flags = []
    if budget and budget.get("left_after") is not None and budget["left_after"] < -0.5:
        flags.append("This order takes the project over its budget by %s." % _m(-budget["left_after"]))
    if cash and cash.get("available_after") is not None and cash["available_after"] < -0.5:
        flags.append("Company cash available to spend in week %s would be %s after this order." % (cash["week"], _m(cash["available_after"])))
    for l in lines:
        if l.get("stock_here", 0) > EPS and l.get("demand_30") is not None and l["stock_here"] + l.get("on_order", 0) >= l["demand_30"] + l["qty"] and l["demand_30"] > EPS:
            flags.append("%s: stock and open orders already cover the next 30 days of scheduled use." % l["material"])
    said = set()
    for w in waits:
        if not w["late"]:
            continue
        if w["running"]:
            if w["material"] not in said:
                said.add(w["material"])
                runs = [x["activity"] for x in waits if x["running"] and x["late"] and x["material"] == w["material"]]
                flags.append("%s: stock on site lasts until about %s at the scheduled rate, before delivery on %s (%s)." %
                             (w["material"], w["latest_delivery"], po.get("delivery_date"), ", ".join(runs)))
        else:
            flags.append("Delivery %s is after the latest date %s for activity %s (start plus float)." % (po.get("delivery_date"), w["latest_delivery"], w["activity"]))
    return {"po": {"id": po.get("id"), "no": po.get("no"), "status": po.get("status"), "total": r2(po.get("total") or total),
                   "delivery_date": po.get("delivery_date"), "vendor": val(c, "SELECT name FROM parties WHERE id=?", (po.get("vendor_id"),), "")},
            "lines": lines, "credit_days": days, "credit_basis": days_basis, "pay_date": pay_date, "budget": budget, "cash": cash,
            "waits": waits, "flags": flags}


@api("ctc.po_check")
def ctc_po_check(c, u, a):
    if not _can(u, "procurement", "view"):
        raise ApiError("Your role cannot see purchase orders (needs procurement view).")
    if a.get("po_id"):
        po = inv.load_doc(c, "po", int(a["po_id"])) if hasattr(inv, "load_doc") else None
        if po is None:
            po = dict(q1(c, "SELECT * FROM po WHERE id=?", (int(a["po_id"]),)) or {})
            po["lines"] = q(c, "SELECT * FROM po_lines WHERE po_id=?", (int(a["po_id"]),))
        if not po:
            raise ApiError("Purchase order not found.")
    else:
        po = dict(a.get("po") or {})
        po["lines"] = po.get("lines") or []
        if not po.get("project_id"):
            raise ApiError("Choose a project.")
        po["project_id"] = int(po["project_id"])
    _CL()._check_project(c, u, po["project_id"])
    return po_check(c, u, po)


@api("ctc.pending_pos")
def ctc_pending_pos(c, u, a):
    """Purchase orders waiting for approval (and drafts), each with the check."""
    if not _can(u, "procurement", "view"):
        raise ApiError("Your role cannot see purchase orders (needs procurement view).")
    allow = _CL()._allowed_projects(c, u)
    out = []
    for p in q(c, "SELECT id FROM po WHERE status IN ('pending_approval','draft') ORDER BY CASE status WHEN 'pending_approval' THEN 0 ELSE 1 END, date"):
        po = inv.load_doc(c, "po", p["id"])
        if allow is not None and po["project_id"] not in allow:
            continue
        if a.get("project_id") and int(a["project_id"]) != po["project_id"]:
            continue
        ck = po_check(c, u, po)
        out.append({"id": po["id"], "no": po["no"], "status": po["status"], "project_id": po["project_id"], "date": po["date"],
                    "vendor": ck["po"]["vendor"], "total": ck["po"]["total"], "delivery_date": po["delivery_date"], "pay_date": ck["pay_date"],
                    "budget_left_after": (ck["budget"] or {}).get("left_after"), "cash_after": (ck["cash"] or {}).get("available_after"),
                    "warnings": len(ck["flags"]), "warning_text": " ".join(ck["flags"][:2])})
    return out


# ───────────────────────────── settings ─────────────────────────────
@api("ctc.settings")
def ctc_settings(c, u, a):
    return {k: (setting(c, k) if setting(c, k) is not None else v) for k, v in DEFAULTS.items()}


@api("ctc.settings_save")
def ctc_settings_save(c, u, a):
    if not (u.get("role") == "admin" or _CL().allowed(c, u, "approve")):
        raise ApiError("Your role cannot change cost-control settings (needs approve on control).")
    for k in DEFAULTS:
        if k in a:
            v = "" if a[k] in (None, "") else str(a[k]).strip()
            if v != "":
                try:
                    f = float(v)
                except ValueError:
                    raise ApiError("%s must be a number." % k)
                if f < 0 or (k != "ctc_bd_days" and f > 100):
                    raise ApiError("%s is out of range." % k)
            elif k != "ctc_oh_pct":
                v = DEFAULTS[k]
            c.execute("INSERT OR REPLACE INTO settings(key, value) VALUES(?,?)", (k, v))
    audit(c, u, "settings", "settings", 0, {k: a.get(k) for k in DEFAULTS if k in a})
    return ctc_settings(c, u, {})
