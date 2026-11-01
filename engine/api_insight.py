"""
Decision dashboard and risk register (BuildCore 2.18).

One screen that answers "where do I need to act, and what is it worth?" - built from figures BuildCore
already calculates (schedule, earned value, billing, cash forecast, stock, equipment, contract notices),
in the way international project-control systems present them:

  * Portfolio health - every active project placed by SPI (time) and CPI (cost), sized by contract value,
    like the portfolio quadrants of Primavera / Autodesk Construction Cloud Insight.
  * Decisions this week - a ranked list of what to act on, each with its money at stake and a link to the
    screen that fixes it (unbilled work, overdue receipts, cost overruns, slipping programmes, cash
    shortfall, shortages, notices about to time-bar, high risks).
  * Trends - one snapshot of each project's key figures per day, so the dashboard can show whether SPI,
    CPI and forecast profit are getting better or worse (the "KPI over time" view of Procore analytics).
  * Risk register - ISO 31000 style: cause, effect, owner, probability and impact 1-5, score, expected
    money value (EMV = probability x cost impact), response (avoid / reduce / transfer / accept), action
    and due date; shown as a 5 x 5 heat map.

Every part is optional: a part that fails or that the user's role may not see is left out, never the screen.
"""
from datetime import date, timedelta

import core
from core import ApiError, EPS, audit, ins, next_no, now, num, q, q1, r2, today, upd, val
import api_inventory as inv
from api_inventory import api

VERSION = "2.18.0"

SCHEMA = """
CREATE TABLE IF NOT EXISTS kpi_snapshots(id INTEGER PRIMARY KEY, project_id INTEGER, date TEXT,
  planned_pct REAL, actual_pct REAL, spi REAL, cpi REAL, earned REAL, cost REAL, eac REAL,
  forecast_profit REAL, forecast_margin REAL, receivable REAL, UNIQUE(project_id, date));
CREATE TABLE IF NOT EXISTS risks(id INTEGER PRIMARY KEY, no TEXT, project_id INTEGER, title TEXT, category TEXT,
  cause TEXT, effect TEXT, owner TEXT, probability INTEGER DEFAULT 3, impact INTEGER DEFAULT 3,
  cost_impact REAL DEFAULT 0, time_impact_days REAL DEFAULT 0, response TEXT DEFAULT 'reduce', action TEXT,
  due_date TEXT, status TEXT DEFAULT 'open', created_by INTEGER, created TEXT, updated TEXT);
CREATE INDEX IF NOT EXISTS ix_risks ON risks(project_id, status);
"""
CATEGORIES = ["Design", "Ground / geology", "Weather / monsoon", "Site access / land", "Permits & approvals",
              "Supply & materials", "Equipment", "Labour", "Subcontractor", "Client / payment", "Contract / claims",
              "Health & safety", "Environment / social", "Price escalation", "Other"]
RESPONSES = [("avoid", "Avoid"), ("reduce", "Reduce"), ("transfer", "Transfer / insure"), ("accept", "Accept")]
# probability 1-5 read as a chance, for the expected money value
PROB_PCT = {1: 0.05, 2: 0.2, 3: 0.4, 4: 0.6, 5: 0.85}
SEV_ORDER = {"critical": 0, "high": 1, "medium": 2, "info": 3}


def init_insight(c):
    for st in SCHEMA.strip().split(";"):
        if st.strip():
            c.execute(st)


def _f(x, d=0.0):
    try:
        return float(x) if x not in (None, "") else d
    except (TypeError, ValueError):
        return d


def _try(fn, *a, default=None):
    try:
        return fn(*a)
    except Exception:  # one missing part never stops the dashboard
        return default


def _risk_row(r):
    p, i = int(r.get("probability") or 3), int(r.get("impact") or 3)
    r["score"] = p * i
    r["level"] = "critical" if r["score"] >= 15 else ("attention" if r["score"] >= 8 else "ok")
    r["emv"] = r2(PROB_PCT.get(p, 0.4) * _f(r.get("cost_impact")))
    return r


# ───────────────────────── project figures ─────────────────────────
def _project_rows(c, pid=None):
    import api_project as P
    from api_finance import invoice_paid
    sql = "SELECT * FROM projects WHERE status='active'" + (" AND id=%d" % int(pid) if pid else "") + " ORDER BY code"
    out = []
    for p in q(c, sql):
        try:
            dims, sched, ev = P.health(c, p["id"], today())
        except Exception as e:
            out.append({"id": p["id"], "code": p["code"], "name": p["name"], "error": str(e),
                        "contract_value": p["contract_value"] or 0})
            continue
        recv = 0.0
        for r in q(c, "SELECT id, payable FROM invoices WHERE project_id=? AND kind='sales' AND status='posted'", (p["id"],)):
            recv += (r["payable"] or 0) - invoice_paid(c, r["id"])
        unbilled = sum((r.get("unbilled_measured") or 0) * (r.get("revised_rate") or 0) for r in ev.get("rows") or []
                       if (r.get("unbilled_measured") or 0) > EPS)
        days_left = None
        if p["end_date"]:
            try:
                days_left = (date.fromisoformat(p["end_date"]) - date.today()).days
            except ValueError:
                pass
        out.append({"id": p["id"], "code": p["code"], "name": p["name"], "client": p["client"],
                    "contract_value": p["contract_value"] or 0, "end_date": p["end_date"], "days_left": days_left,
                    "planned_pct": sched.get("planned_pct"), "actual_pct": sched.get("actual_pct"),
                    "spi": sched.get("spi"), "forecast_finish": sched.get("forecast_finish"),
                    "cpi": ev.get("cpi"), "earned": ev.get("earned_revenue"), "cost": ev.get("ac"),
                    "bac": ev.get("bac"), "eac": ev.get("eac"), "cv": ev.get("cv"),
                    "forecast_profit": ev.get("forecast_profit"), "forecast_revenue": ev.get("forecast_revenue"), "forecast_margin": ev.get("forecast_margin"),
                    "tender_margin": ev.get("tender_margin"), "margin_fade": ev.get("margin_fade"),
                    "receivable": r2(recv), "unbilled": r2(unbilled),
                    "health": {k: v["level"] for k, v in dims.items()},
                    "reasons": {k: v["reasons"] for k, v in dims.items() if v["level"] != "ok"}})
    return out


def snapshot(c, rows):
    """One row of key figures per project per day; the trend lines are drawn from these."""
    t = today()
    for r in rows:
        if r.get("error"):
            continue
        c.execute("INSERT OR REPLACE INTO kpi_snapshots(project_id, date, planned_pct, actual_pct, spi, cpi, earned, cost, "
                  "eac, forecast_profit, forecast_margin, receivable) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                  (r["id"], t, r["planned_pct"], r["actual_pct"], r["spi"], r["cpi"], r["earned"], r["cost"], r["eac"],
                   r["forecast_profit"], r["forecast_margin"], r["receivable"]))


def trends(c, ids, days=120):
    since = (date.today() - timedelta(days=days)).isoformat()
    out = {}
    if not ids:
        return out
    for r in q(c, "SELECT * FROM kpi_snapshots WHERE date>=? AND project_id IN (%s) ORDER BY date" %
               ",".join(str(int(i)) for i in ids), (since,)):
        out.setdefault(r["project_id"], []).append({k: r[k] for k in ("date", "spi", "cpi", "actual_pct", "forecast_profit",
                                                                      "forecast_margin", "earned", "cost")})
    return out


# ───────────────────────── decisions ─────────────────────────
def decisions(c, u, rows, cash, pid=None):
    """What to act on, most urgent and most valuable first."""
    from api_finance import invoice_paid
    out = []
    t = today()

    def add(sev, kind, title, why, link, impact=None, project_id=None, action=None):
        out.append({"severity": sev, "kind": kind, "title": title, "why": why, "link": link,
                    "impact": r2(impact) if impact else None, "project_id": project_id, "action": action})
    money = core.can(u, "commercial", "view") or core.can(u, "accounts", "view")
    for r in rows:
        if r.get("error"):
            continue
        code = r["code"]
        if money and (r["forecast_profit"] or 0) < 0:
            add("critical", "cost", "%s is forecast to lose money" % code,
                "Forecast cost %s against revenue; margin %s%%. Review the cost codes over budget and the variations "
                "not yet claimed." % (fmt(r["eac"]), r["forecast_margin"]), "#/p/evm",
                -(r["forecast_profit"] or 0), r["id"], "Review cost")
        elif money and r["cpi"] is not None and r["cpi"] < 0.95:
            over = max(0.0, (r["eac"] or 0) - (r["bac"] or 0))
            add("critical" if r["cpi"] < 0.85 else "high", "cost", "%s: work is costing more than budgeted" % code,
                "CPI %.2f - every 100 of budgeted work costs %.0f. Forecast overrun %s." % (r["cpi"], 100 / r["cpi"], fmt(over)),
                "#/p/evm", over or None, r["id"], "Review cost")
        if money and (r["margin_fade"] or 0) > 2 and (r["forecast_profit"] or 0) >= 0:
            add("high" if r["margin_fade"] > 5 else "medium", "cost", "%s: margin is fading" % code,
                "Forecast margin %s%% against %s%% at tender (%s points lost)." % (r["forecast_margin"], r["tender_margin"],
                                                                               round(r["margin_fade"], 1)),
                "#/p/evm", (r["margin_fade"] or 0) / 100 * (r["contract_value"] or 0), r["id"], "Find the leak")
        if r["spi"] is not None and r["spi"] < 0.95:
            late = r["forecast_finish"] and r["end_date"] and r["forecast_finish"] > r["end_date"]
            add("critical" if (r["spi"] < 0.85 or late) else "high", "time", "%s is behind programme" % code,
                "Progress %s%% against %s%% planned (SPI %.2f)%s." % (round(r["actual_pct"] or 0, 1), round(r["planned_pct"] or 0, 1),
                                                                     r["spi"], ("; forecast finish %s after contract completion %s"
                                                                                % (r["forecast_finish"], r["end_date"])) if late else ""),
                "#/p/schedule", None, r["id"], "Plan recovery")
        if money and (r["unbilled"] or 0) > 0:
            add("high" if r["unbilled"] > 0.02 * (r["contract_value"] or 1e18) else "medium", "cash",
                "Bill %s of measured work on %s" % (fmt(r["unbilled"]), code),
                "Work is measured but not in any IPC yet - this is cash you have earned and not asked for.",
                "#/p/ipc", r["unbilled"], r["id"], "Make the IPC")
    if core.can(u, "accounts", "view"):
        pc = " AND i.project_id=%d" % int(pid) if pid else ""
        by_party = {}
        for r in q(c, "SELECT i.id, i.kind, i.payable, i.due_date, i.project_id, p.name pname, p.id party_id FROM invoices i "
                      "JOIN parties p ON p.id=i.party_id WHERE i.status='posted' AND i.due_date<?" + pc, (t,)):
            bal = (r["payable"] or 0) - invoice_paid(c, r["id"])
            if bal <= 0.5:
                continue
            k = (r["kind"] == "sales", r["party_id"])
            g = by_party.setdefault(k, {"name": r["pname"], "bal": 0.0, "oldest": r["due_date"], "n": 0, "party_id": r["party_id"]})
            g["bal"] += bal
            g["n"] += 1
            g["oldest"] = min(g["oldest"], r["due_date"])
        for (sales, _pid), g in sorted(by_party.items(), key=lambda x: -x[1]["bal"])[:6]:
            age = (date.today() - date.fromisoformat(g["oldest"])).days if g["oldest"] else 0
            if sales:
                add("critical" if age > 90 else ("high" if age > 45 else "medium"), "cash", "Collect %s from %s" % (fmt(g["bal"]), g["name"]),
                    "%d bill(s) overdue, oldest by %d days." % (g["n"], age), "#/acc/party?party=%d" % g["party_id"], g["bal"],
                    None, "Chase payment")
            elif age > 30:
                add("high" if age > 60 else "medium", "supply", "Overdue to %s: %s" % (g["name"], fmt(g["bal"])),
                    "%d bill(s), oldest %d days past due - deliveries may stop." % (g["n"], age),
                    "#/acc/payments", g["bal"], None, "Plan payment")
        if cash and cash.get("first_shortfall"):
            add("critical", "cash", "Cash falls below the minimum in %s" % cash["first_shortfall"],
                "Lowest balance %s in %s. Bill and collect sooner, delay non-critical buying, or arrange a facility."
                % (fmt((cash.get("lowest") or {}).get("balance")), (cash.get("lowest") or {}).get("month")),
                "#/acc/cash", cash.get("max_overdraft") or None, None, "Plan cash")
    if core.can(u, "inventory", "view"):
        import api_project as P
        for r in rows:
            for m in _try(P.material_risks, c, r["id"], default=[]) or []:
                if m.get("risk"):
                    add("high", "supply", "Order %s for %s" % (m["name"], r["code"]), m["why"], "#/proc/pr",
                        None, r["id"], "Raise a PR")
    if core.can(u, "equipment", "view"):
        pc = " AND project_id=%d" % int(pid) if pid else ""
        down = q(c, "SELECT code, name, project_id FROM equipment WHERE status='breakdown'" + pc)
        if down:
            add("high", "equipment", "%d machine(s) broken down" % len(down), ", ".join(d["code"] for d in down[:6]) + ".",
                "#/eq/wo", None, None, "Open work orders")
    if core.can(u, "project", "view"):
        soon = (date.today() + timedelta(days=7)).isoformat()
        pc = " AND project_id=%d" % int(pid) if pid else ""
        for e in q(c, "SELECT * FROM events WHERE status='open' AND notice_deadline IS NOT NULL AND notice_deadline<>'' "
                      "AND notice_deadline<=?" + pc, (soon,)):
            add("critical", "contract", "Send notice: %s" % e["title"],
                "Notice due %s%s - after that the claim may be time-barred." % (e["notice_deadline"], (" (clause %s)" % e["clause"]) if e["clause"] else ""),
                "#/p/events", e["cost_impact"] or None, e["project_id"], "Write the notice")
        pc = " AND project_id=%d" % int(pid) if pid else ""
        for r in q(c, "SELECT * FROM risks WHERE status='open'" + pc):
            r = _risk_row(dict(r))
            if r["score"] >= 15 or (r["due_date"] and r["due_date"] < t):
                add("high" if r["score"] >= 15 else "medium", "risk", "Risk %s: %s" % (r["no"] or "", r["title"]),
                    "Score %d of 25%s%s." % (r["score"], (", expected cost %s" % fmt(r["emv"])) if r["emv"] else "",
                                             (", action was due %s" % r["due_date"]) if r["due_date"] and r["due_date"] < t else ""),
                    "#/risks?id=%d" % r["id"], r["emv"] or None, r["project_id"], "Act on the risk")
    out.sort(key=lambda x: (SEV_ORDER[x["severity"]], -(x["impact"] or 0)))
    return out


def fmt(x):
    try:
        x = float(x or 0)
    except (TypeError, ValueError):
        return str(x)
    a = abs(x)
    if a >= 1e7:
        return "NPR %.2f Cr" % (x / 1e7)
    if a >= 1e5:
        return "NPR %.2f lakh" % (x / 1e5)
    return "NPR {:,.0f}".format(x)


# ───────────────────────── endpoints ─────────────────────────
@api("insight.overview")
def overview(c, u, a):
    pid = int(a["project_id"]) if a.get("project_id") else None
    see = core.can(u, "project", "view") or core.can(u, "commercial", "view") or core.can(u, "accounts", "view")
    rows = _project_rows(c, pid) if see else []
    _try(snapshot, c, rows)
    ok = [r for r in rows if not r.get("error")]
    money = core.can(u, "commercial", "view") or core.can(u, "accounts", "view")
    cash = None
    if core.can(u, "accounts", "view") and not pid:
        import api_cash
        cash = _try(api_cash.cash_company, c, u, {"months": 12})
    tot = lambda k: r2(sum(_f(r.get(k)) for r in ok))  # noqa: E731
    cv = tot("contract_value")
    wsum = lambda k: (sum(_f(r.get(k)) * _f(r["contract_value"]) for r in ok if r.get(k) is not None) /  # noqa: E731
                      max(EPS, sum(_f(r["contract_value"]) for r in ok if r.get(k) is not None))) if any(r.get(k) is not None for r in ok) else None
    kpis = {"projects": len(rows), "contract_value": cv, "earned": tot("earned"), "backlog": r2(max(0.0, cv - tot("earned"))),
            "spi": round(wsum("spi"), 2) if wsum("spi") is not None else None,
            "cpi": round(wsum("cpi"), 2) if wsum("cpi") is not None else None}
    if money:
        rev = sum(_f(r.get("forecast_revenue")) or (_f(r["eac"]) + _f(r["forecast_profit"])) for r in ok)
        kpis.update({"forecast_profit": tot("forecast_profit"), "cost": tot("cost"), "unbilled": tot("unbilled"),
                     "forecast_margin": round(100 * tot("forecast_profit") / rev, 1) if rev > EPS else None})
    if core.can(u, "accounts", "view"):
        from api_finance import invoice_paid
        t = today()
        od = 0.0
        pc = " AND project_id=%d" % pid if pid else ""
        for r in q(c, "SELECT id, payable FROM invoices WHERE kind='sales' AND status='posted' AND due_date<?" + pc, (t,)):
            od += (r["payable"] or 0) - invoice_paid(c, r["id"])
        kpis["receivable"] = tot("receivable")
        kpis["receivable_overdue"] = r2(od)
        if cash:
            kpis["cash"] = cash.get("opening")
            kpis["cash_lowest"] = cash.get("lowest")
            kpis["cash_shortfall"] = cash.get("first_shortfall")
    if not money:
        for r in rows:
            for k in ("earned", "cost", "eac", "cv", "forecast_profit", "forecast_margin", "tender_margin", "margin_fade",
                      "receivable", "unbilled", "bac", "forecast_revenue", "contract_value"):
                r.pop(k, None)
            for k in ("cost", "commercial"):
                (r.get("reasons") or {}).pop(k, None)
        for k in ("contract_value", "earned", "backlog"):
            kpis.pop(k, None)
    rk = [_risk_row(dict(r)) for r in q(c, "SELECT * FROM risks WHERE status='open'" + (" AND project_id=%d" % pid if pid else ""))]
    heat = [[0] * 5 for _ in range(5)]
    for r in rk:
        heat[max(1, min(5, int(r["probability"] or 3))) - 1][max(1, min(5, int(r["impact"] or 3))) - 1] += 1
    rk.sort(key=lambda r: (-r["score"], -(r["emv"] or 0)))
    counts = {}
    try:
        import api_project as P
        for it in P.action_items(c, u, pid):
            counts[it["category"]] = counts.get(it["category"], 0) + 1
    except Exception:
        pass
    return {"as_of": today(), "kpis": kpis, "projects": rows, "trends": trends(c, [r["id"] for r in ok]),
            "decisions": decisions(c, u, rows, cash, pid)[:12],
            "cash": {"rows": cash["rows"], "min_balance": cash.get("min_balance"), "opening": cash.get("opening")} if cash else None,
            "risks": {"top": rk[:5], "heat": heat, "open": len(rk), "emv": r2(sum(r["emv"] for r in rk))},
            "attention": counts, "money": money, "version": VERSION}


@api("risk.meta")
def risk_meta(c, u, a):
    return {"categories": CATEGORIES, "responses": RESPONSES, "prob_pct": PROB_PCT}


@api("risk.list", "project", "view")
def risk_list(c, u, a):
    w, p = ["1=1"], []
    if a.get("project_id"):
        w.append("r.project_id=?")
        p.append(int(a["project_id"]))
    if a.get("status"):
        w.append("r.status=?")
        p.append(a["status"])
    rows = q(c, "SELECT r.*, pr.code project_code FROM risks r LEFT JOIN projects pr ON pr.id=r.project_id WHERE %s "
                "ORDER BY CASE r.status WHEN 'open' THEN 0 WHEN 'occurred' THEN 1 ELSE 2 END, r.probability*r.impact DESC, r.id DESC"
             % " AND ".join(w), p)
    return [_risk_row(dict(r)) for r in rows]


@api("risk.save", "project", "edit")
def risk_save(c, u, a):
    r = a.get("row") or {}
    if not (r.get("title") or "").strip():
        raise ApiError("Write what the risk is.")
    keep = {k: (r.get(k) if r.get(k) != "" else None) for k in
            ("project_id", "title", "category", "cause", "effect", "owner", "response", "action", "due_date", "status")}
    keep["project_id"] = int(keep["project_id"]) if keep.get("project_id") else None
    for k in ("probability", "impact"):
        v = int(_f(r.get(k), 3))
        if v < 1 or v > 5:
            raise ApiError("Probability and impact are 1 (very low) to 5 (very high).")
        keep[k] = v
    keep["cost_impact"] = num(r.get("cost_impact")) if r.get("cost_impact") not in (None, "") else 0
    keep["time_impact_days"] = num(r.get("time_impact_days")) if r.get("time_impact_days") not in (None, "") else 0
    keep["status"] = keep.get("status") or "open"
    if keep["status"] not in ("open", "occurred", "closed"):
        raise ApiError("Status is open, occurred or closed.")
    if keep.get("response") and keep["response"] not in dict(RESPONSES):
        raise ApiError("Response is avoid, reduce, transfer or accept.")
    keep["updated"] = now()
    if r.get("id"):
        upd(c, "risks", int(r["id"]), keep)
        rid = int(r["id"])
    else:
        keep["no"] = "R-%03d" % ((val(c, "SELECT COUNT(*) FROM risks", (), 0) or 0) + 1)
        keep["created_by"] = u["id"]
        keep["created"] = now()
        rid = ins(c, "risks", keep)
    audit(c, u, "save", "risks", rid, {"title": keep["title"], "score": keep["probability"] * keep["impact"]})
    return {"id": rid}


@api("risk.delete", "project", "approve")
def risk_delete(c, u, a):
    rid = int(a["id"])
    row = q1(c, "SELECT * FROM risks WHERE id=?", (rid,))
    if not row:
        raise ApiError("That risk is not in the register.")
    c.execute("DELETE FROM risks WHERE id=?", (rid,))
    audit(c, u, "delete", "risks", rid, {"title": row["title"]})
    return True


@api("risk.suggest", "project", "view")
def risk_suggest(c, u, a):
    """Risks the figures already point to, ready to add to the register with one click."""
    pid = int(a["project_id"]) if a.get("project_id") else None
    rows = _project_rows(c, pid)
    have = {(r["project_id"], (r["title"] or "").lower()) for r in q(c, "SELECT project_id, title FROM risks WHERE status<>'closed'")}
    out = []

    def add(r, title, cat, p, i, cost, why):
        if (r["id"], title.lower()) not in have:
            out.append({"project_id": r["id"], "project_code": r["code"], "title": title, "category": cat,
                        "probability": p, "impact": i, "cost_impact": r2(cost or 0), "cause": why})
    for r in rows:
        if r.get("error"):
            continue
        if r["spi"] is not None and r["spi"] < 0.95:
            add(r, "Completion later than the contract date", "Contract / claims", 4 if r["spi"] < 0.85 else 3, 4,
                0, "SPI %.2f." % r["spi"])
        if r["cpi"] is not None and r["cpi"] < 0.95:
            add(r, "Final cost above budget", "Price escalation", 4 if r["cpi"] < 0.85 else 3, 4,
                max(0.0, _f(r.get("eac")) - _f(r.get("bac"))), "CPI %.2f." % r["cpi"])
        if (r.get("receivable") or 0) > 0.1 * (r["contract_value"] or 1e18):
            add(r, "Client pays late", "Client / payment", 3, 3, r["receivable"], "Receivable %s." % fmt(r["receivable"]))
        mon = date.today().month
        if 4 <= mon <= 6:
            add(r, "Monsoon stops outdoor work", "Weather / monsoon", 4, 3, 0, "Monsoon starts in June.")
    return out[:12]
