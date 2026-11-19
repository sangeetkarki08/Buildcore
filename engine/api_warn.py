"""BuildCore 2.54 "One alerts engine" (U5, P3, expiry, fuel and re-order alerts).

Every new warning goes into the one alerts register of 2.29 (Action centre > Alerts: owner, target date, escalation,
history), as new kinds next to the fifteen there.  Nothing is posted.
* Margin trend (U5): the forecast of every active project is kept once a day (table wn_snapshots), so a monthly line
  exists without a locked close.  "Forecast margin dropped" fires when the forecast margin fell by more than the
  threshold (points) since the end of last month; "Cost probably missing" when the margin to date is more than the
  threshold above the forecast margin.  "Forecast incomplete" (items with revenue and no cost) is raised here too.
* Time (P3): "Finish after completion" with the liquidated damages exposure, "Schedule not updated" (no calculation
  for N days while DPRs come in), "Milestone at risk" (a contract milestone due within N days whose activity is not
  finished, or overdue).
* Expiry: machine insurance, registration and operator certificates; bonds, guarantees and insurance policies
  (Contract administration) expiring within N days or expired while still active.
* Fuel: a machine using more than the threshold % of its fuel norm (litres per hour) over the last 30 days.
* Re-order: a material whose stock (all stores) is below its re-order level.
New kinds start switched off on companies that already had data (Alerts > Rules, or Setup & switches > "turn on
the 2.54 alerts"); on for new companies.
"""
from datetime import date, timedelta

import core
from core import ApiError, audit, ins, now, q, q1, setting, today, upd, val
import api_inventory as inv
from api_inventory import api

VERSION = "2.54.0"
FLAG = "_bco254"

SCHEMA = """
CREATE TABLE IF NOT EXISTS wn_snapshots(project_id INTEGER, day TEXT, cost REAL, eac REAL, value REAL, profit REAL,
  margin REAL, margin_to_date REAL, finish TEXT, PRIMARY KEY(project_id, day));
"""

# key, label, domain, severity, threshold, threshold label, owner roles, target days, escalate days
NEW_KINDS = [
    ("margin_drop", "Forecast margin dropped since last month", "cost", "high", 3, "points", "project_manager,finance_manager", 7, 7),
    ("cost_missing", "Cost probably missing (margin to date far above forecast)", "cost", "medium", 25, "points",
     "accountant,quantity_surveyor", 7, 7),
    ("forecast_incomplete", "Forecast incomplete (revenue with no cost)", "cost", "high", 0, "", "quantity_surveyor,project_manager", 7, 7),
    ("finish_late", "Forecast finish after contract completion", "time", "high", 0, "days late", "project_manager,planner", 7, 7),
    ("schedule_stale", "Schedule not updated", "time", "medium", 14, "days since last calculation", "planner,project_manager", 3, 3),
    ("milestone_risk", "Contract milestone at risk", "time", "high", 14, "days ahead", "project_manager,planner", 3, 3),
    ("machine_expiry", "Machine insurance, registration or operator licence expiring", "equipment", "medium", 30, "days ahead",
     "equipment_manager", 7, 7),
    ("security_expiry", "Bond, guarantee or insurance expiring", "commercial", "high", 30, "days ahead",
     "finance_manager,quantity_surveyor", 7, 7),
    ("fuel_high", "Machine fuel above its norm", "equipment", "medium", 120, "% of norm", "equipment_manager,storekeeper", 7, 7),
    ("reorder", "Stock below re-order level", "stores", "medium", 0, "", "storekeeper,procurement_officer", 3, 3),
]
NEW_ACTIONS = {
    "margin_drop": "Open CVR and forecast, see which items and lines moved since last month, and agree recovery actions.",
    "cost_missing": "Check bills, store issues and DPR rates (CVR > Cost not yet in the books) before trusting the margin.",
    "forecast_incomplete": "Add the items to the control budget or give them a rate analysis.",
    "finish_late": "Recover time (more crews, overlap, longer shifts) or prepare the extension-of-time claim with the delays register.",
    "schedule_stale": "Approve the DPRs and press Calculate schedule (Schedule & WBS).",
    "milestone_risk": "Check the activity's float and resources; tell the Engineer early if the milestone will be missed.",
    "machine_expiry": "Renew it before the date and attach the new paper to the machine.",
    "security_expiry": "Ask the bank to extend it, or release it if the contract allows; update the register.",
    "fuel_high": "Check the meter readings, the fuel issues and the machine's condition; compare with the logsheets.",
    "reorder": "Raise a purchase request for the re-order quantity, or transfer from another store.",
}


def _F():
    import api_fcc
    return api_fcc


def _d(s):
    return date.fromisoformat(s[:10])


def _days(a, b):
    return (_d(b) - _d(a)).days


# ───────────────────────── snapshots ─────────────────────────
def snapshot(c, pid, t=None):
    t = t or today()
    import api_pfp
    pos = api_pfp.position(c, pid, t)
    f = pos["forecast"]
    run = q1(c, "SELECT finish FROM sched_runs WHERE project_id=? ORDER BY id DESC LIMIT 1", (pid,))
    c.execute("INSERT OR REPLACE INTO wn_snapshots(project_id, day, cost, eac, value, profit, margin, margin_to_date, finish) "
              "VALUES(?,?,?,?,?,?,?,?,?)", (pid, t, pos["cost"]["total"], f["eac"], f["value"], f["profit"], f["margin_pct"],
                                            pos["margin"]["certified_pct"], run["finish"] if run else None))
    return pos


def _month_start(t):
    return t[:8] + "01"


# ───────────────────────── checks ─────────────────────────
def chk_margin(c, R, ctx):
    F = _F()
    out = []
    t = ctx["today"]
    for p in ctx["active"]:
        try:
            pos = snapshot(c, p["id"], t)
        except Exception as e:
            ctx["errors"].append("snapshot %s: %s" % (p["code"], str(e)[:120]))
            continue
        f = pos["forecast"]
        prev = q1(c, "SELECT * FROM wn_snapshots WHERE project_id=? AND day<? ORDER BY day DESC LIMIT 1", (p["id"], _month_start(t)))
        if prev and prev["margin"] is not None and f["margin_pct"] is not None:
            drop = prev["margin"] - f["margin_pct"]
            if drop > R["margin_drop"]["threshold"]:
                out.append({"fkey": "mdrop:%d" % p["id"], "kind": "margin_drop", "project_id": p["id"],
                            "title": "%s: forecast margin %.1f%% (was %.1f%% on %s)" % (p["code"], f["margin_pct"], prev["margin"], prev["day"]),
                            "amount": round((prev["profit"] or 0) - (f["profit"] or 0), 2), "due_date": None, "severity": "high",
                            "basis": "Project position kept daily (2.54): forecast margin fell %.1f points since the last day of last month." % drop,
                            "detail": "", "sources": [F.src("cvr", p["code"], "#/cl/cvr", None, p["id"])]})
        mt = pos["margin"]["certified_pct"]
        if mt is not None and f["margin_pct"] is not None and mt - f["margin_pct"] > R["cost_missing"]["threshold"]:
            out.append({"fkey": "cmiss:%d" % p["id"], "kind": "cost_missing", "project_id": p["id"],
                        "title": "%s: margin to date %.1f%% against forecast %.1f%%" % (p["code"], mt, f["margin_pct"]),
                        "amount": None, "due_date": None, "severity": "medium",
                        "basis": "A margin to date far above the forecast almost always means cost is late (bills, issues, rates).",
                        "detail": "", "sources": [F.src("cvr", p["code"], "#/cl/cvr", None, p["id"])]})
        d = (ctx.get("ctc") or {}).get(p["id"])
        for al in (d or {}).get("alerts") or []:
            if al.get("key") == "forecast_incomplete":
                out.append({"fkey": "fcinc:%d" % p["id"], "kind": "forecast_incomplete", "project_id": p["id"],
                            "title": "%s: %s" % (p["code"], al["text"][:180]), "amount": None, "due_date": None, "severity": "high",
                            "basis": "Cost to complete (2.28).", "detail": ", ".join(al.get("items", [])[:15]),
                            "sources": [F.src("budget", p["code"], "#/cl/budget", None, p["id"])]})
    return out


def chk_time(c, R, ctx):
    F = _F()
    out = []
    t = ctx["today"]
    import api_sched
    for p in ctx["active"]:
        pr = q1(c, "SELECT * FROM projects WHERE id=?", (p["id"],))
        run = q1(c, "SELECT * FROM sched_runs WHERE project_id=? ORDER BY id DESC LIMIT 1", (p["id"],))
        try:
            cd = api_sched.contract_dates(c, pr)
        except Exception:
            cd = {"revised": None}
        if run and run["finish"] and cd.get("revised") and run["finish"] > cd["revised"]:
            ld = api_sched.ld_exposure(c, pr, run["finish"], cd)
            out.append({"fkey": "late:%d" % p["id"], "kind": "finish_late", "project_id": p["id"],
                        "title": "%s: forecast finish %s, %d days after completion %s" % (p["code"], run["finish"], _days(cd["revised"], run["finish"]), cd["revised"]),
                        "amount": ld.get("amount") or None, "due_date": None, "severity": "high",
                        "basis": "Last schedule calculation (data date %s); LD exposure %s." % (run["data_date"], "{:,.0f}".format(ld.get("amount") or 0)),
                        "detail": "", "sources": [F.src("schedule", p["code"], "#/p/schedule", None, p["id"])]})
        acts = val(c, "SELECT COUNT(*) FROM activities WHERE project_id=?", (p["id"],))
        if acts:
            last = run["data_date"] if run else None
            dprs = val(c, "SELECT COUNT(*) FROM dpr WHERE project_id=? AND status='approved' AND date>?", (p["id"], last or "0000"))
            lim = int(R["schedule_stale"]["threshold"] or 14)
            if dprs and (not last or _days(last, t) > lim):
                out.append({"fkey": "stale:%d" % p["id"], "kind": "schedule_stale", "project_id": p["id"],
                            "title": "%s: schedule last calculated %s; %d approved DPRs since" % (p["code"], last or "never", dprs),
                            "amount": None, "due_date": None, "severity": "medium", "basis": "Schedule runs (2.12).", "detail": "",
                            "sources": [F.src("schedule", p["code"], "#/p/schedule", None, p["id"])]})
        ahead = int(R["milestone_risk"]["threshold"] or 14)
        for m in q(c, "SELECT m.*, a.actual_finish, a.ef, a.code acode FROM contract_milestones m LEFT JOIN activities a ON a.id=m.activity_id "
                      "WHERE m.project_id=? AND m.due_date IS NOT NULL", (p["id"],)):
            if m["actual_finish"]:
                continue
            due = m["due_date"]
            fc = m["ef"]
            if due < t or _days(t, due) <= ahead or (fc and fc > due):
                out.append({"fkey": "ms:%d" % m["id"], "kind": "milestone_risk", "project_id": p["id"],
                            "title": "%s: milestone %s due %s%s" % (p["code"], m["name"], due, (", forecast " + fc) if fc else ""),
                            "amount": round((m["ld_per_day"] or 0) * max(0, _days(due, fc)) if fc and fc > due else 0, 2) or None,
                            "due_date": due, "severity": "high" if due < t or (fc and fc > due) else "medium",
                            "basis": "Contract milestones (Contract time).", "detail": "",
                            "sources": [F.src("schedule", p["code"], "#/p/schedule", None, p["id"])]})
    return out


def chk_expiry(c, R, ctx):
    F = _F()
    out = []
    t = ctx["today"]
    lim_m = (date.fromisoformat(t) + timedelta(days=int(R["machine_expiry"]["threshold"] or 30))).isoformat()
    for e in q(c, "SELECT * FROM equipment WHERE COALESCE(active,1)=1 AND COALESCE(status,'') NOT IN ('disposed','sold','scrapped')"):
        for col, what in (("insurance_expiry", "insurance"), ("registration_expiry", "registration"), ("operator_cert_expiry", "operator licence")):
            d = e[col] if col in e.keys() else None
            if d and d <= lim_m:
                out.append({"fkey": "mx:%d:%s" % (e["id"], col), "kind": "machine_expiry", "project_id": e["project_id"],
                            "title": "%s %s: %s %s %s" % (e["code"], e["name"], what, "expired on" if d < t else "expires", d),
                            "amount": None, "due_date": d, "severity": "high" if d < t else "medium",
                            "basis": "Equipment register.", "detail": "",
                            "sources": [F.src("equipment", e["code"], "#/eq/register", e["id"], e["project_id"])]})
    lim_s = (date.fromisoformat(t) + timedelta(days=int(R["security_expiry"]["threshold"] or 30))).isoformat()
    if q1(c, "SELECT 1 FROM sqlite_master WHERE name='ca_securities'"):
        for s in q(c, "SELECT s.*, p.code pcode FROM ca_securities s LEFT JOIN projects p ON p.id=s.project_id WHERE "
                      "COALESCE(s.status,'active')='active' AND s.expiry_date IS NOT NULL AND s.expiry_date<=?", (lim_s,)):
            out.append({"fkey": "sec:%d" % s["id"], "kind": "security_expiry", "project_id": s["project_id"],
                        "title": "%s: %s %s %s %s" % (s["pcode"] or "", s["kind"] or "security", s["number"] or "", "expired on" if s["expiry_date"] < t else "expires", s["expiry_date"]),
                        "amount": s["amount"], "due_date": s["expiry_date"], "severity": "high",
                        "basis": "Bonds, guarantees & insurance register.", "detail": s["issuer"] or "",
                        "sources": [F.src("security", s["number"], "#/ca/securities", s["id"], s["project_id"])]})
    return out


def chk_fuel(c, R, ctx):
    F = _F()
    out = []
    t = ctx["today"]
    frm = (date.fromisoformat(t) - timedelta(days=30)).isoformat()
    lim = (R["fuel_high"]["threshold"] or 120) / 100.0
    fuel = q(c, "SELECT l.equipment_id eid, SUM(l.qty) litres FROM issue_lines l JOIN issues i ON i.id=l.issue_id JOIN materials m ON "
                "m.id=l.material_id WHERE i.status='posted' AND i.date BETWEEN ? AND ? AND l.equipment_id IS NOT NULL AND "
                "(LOWER(COALESCE(m.category,'')) LIKE '%fuel%' OR LOWER(m.name) LIKE '%diesel%' OR LOWER(m.name) LIKE '%petrol%') "
                "GROUP BY l.equipment_id", (frm, t))
    for f in fuel:
        e = q1(c, "SELECT * FROM equipment WHERE id=?", (f["eid"],))
        if not e or not (e["fuel_norm"] or 0):
            continue
        hrs = val(c, "SELECT SUM(hours) FROM logsheets WHERE equipment_id=? AND date BETWEEN ? AND ? AND status<>'draft'", (f["eid"], frm, t)) or \
            val(c, "SELECT SUM(e.hours) FROM dpr_equipment e JOIN dpr d ON d.id=e.dpr_id WHERE e.equipment_id=? AND d.date BETWEEN ? AND ? "
                   "AND d.status='approved'", (f["eid"], frm, t)) or 0
        if hrs <= 0:
            continue
        rate = (f["litres"] or 0) / hrs
        if rate > e["fuel_norm"] * lim:
            out.append({"fkey": "fuel:%d" % e["id"], "kind": "fuel_high", "project_id": e["project_id"],
                        "title": "%s %s: %.1f litres/hour against a norm of %.1f (%d%%)" % (e["code"], e["name"], rate, e["fuel_norm"], round(100 * rate / e["fuel_norm"])),
                        "amount": None, "due_date": None, "severity": "medium",
                        "basis": "Last 30 days: %.0f litres issued, %.1f hours worked." % (f["litres"] or 0, hrs), "detail": "",
                        "sources": [F.src("equipment", e["code"], "#/eq/register", e["id"], e["project_id"])]})
    return out


def chk_reorder(c, R, ctx):
    F = _F()
    out = []
    for m in q(c, "SELECT m.id, m.code, m.name, m.unit, m.reorder_level, m.reorder_qty, COALESCE((SELECT SUM(qty_in-qty_out) FROM stock_ledger s "
                  "WHERE s.material_id=m.id),0) bal FROM materials m WHERE COALESCE(m.active,1)=1 AND COALESCE(m.reorder_level,0)>0"):
        if (m["bal"] or 0) < m["reorder_level"]:
            out.append({"fkey": "ro:%d" % m["id"], "kind": "reorder", "project_id": None,
                        "title": "%s %s: stock %.2f %s, re-order level %.2f" % (m["code"], m["name"], m["bal"] or 0, m["unit"] or "", m["reorder_level"]),
                        "amount": None, "due_date": None, "severity": "medium",
                        "basis": "Stock in all stores against the material's re-order level; order %.2f." % (m["reorder_qty"] or 0), "detail": "",
                        "sources": [F.src("material", m["code"], "#/inv/stock", m["id"], None)]})
    return out


NEW_CHECKS = [("margin_drop", chk_margin), ("finish_late", chk_time), ("machine_expiry", chk_expiry), ("fuel_high", chk_fuel),
              ("reorder", chk_reorder)]
NEW_CHECK_KINDS = {"margin_drop": ("margin_drop", "cost_missing", "forecast_incomplete"),
                   "finish_late": ("finish_late", "schedule_stale", "milestone_risk"),
                   "machine_expiry": ("machine_expiry", "security_expiry")}


def _connect(c):
    F = _F()
    have = {k[0] for k in F.KINDS}
    for k in NEW_KINDS:
        if k[0] not in have:
            F.KINDS.append(k)
            F.KIND[k[0]] = k
    F.DOMAINS.setdefault("time", "Time and programme")
    for k, v in NEW_ACTIONS.items():
        F.ACTIONS.setdefault(k, v)
    names = {x[0] for x in F.CHECKS}
    for key, fn in NEW_CHECKS:
        if key not in names:
            F.CHECKS.append((key, fn))
    for k, v in NEW_CHECK_KINDS.items():
        F.CHECK_KINDS.setdefault(k, v)


@api("wn.enable", "admin", "edit")
def wn_enable(c, u, a):
    """Turn the 2.54 alert kinds on (or off) in the alert rules."""
    flag = 1 if a.get("on", 1) else 0
    for k in NEW_KINDS:
        c.execute("UPDATE fcc_rules SET enabled=? WHERE kind=?", (flag, k[0]))
    c.execute("INSERT OR REPLACE INTO settings(key, value) VALUES('wn_alerts', ?)", (str(flag),))
    core.audit(c, u, "settings", "fcc_rules", None, {"2.54 alerts": flag})
    return wn_state(c, u, {})


@api("wn.state", "project", "view")
def wn_state(c, u, a):
    rows = {r["kind"]: r["enabled"] for r in q(c, "SELECT kind, enabled FROM fcc_rules")}
    return {"kinds": [{"kind": k[0], "label": k[1], "enabled": bool(rows.get(k[0]))} for k in NEW_KINDS],
            "on": sum(1 for k in NEW_KINDS if rows.get(k[0])), "total": len(NEW_KINDS)}


@api("wn.trend", "project", "view")
def wn_trend(c, u, a):
    """The kept forecast of a project, one row per day kept (newest last)."""
    core.need(a, "project_id")
    return {"rows": q(c, "SELECT * FROM wn_snapshots WHERE project_id=? ORDER BY day", (int(a["project_id"]),))}


def init_warn(c):
    c.executescript(SCHEMA)
    import api_fcc as F
    _connect(c)
    used = val(c, "SELECT COUNT(*) FROM vouchers") or val(c, "SELECT COUNT(*) FROM dpr")
    for k in NEW_KINDS:
        if not q1(c, "SELECT kind FROM fcc_rules WHERE kind=?", (k[0],)):
            c.execute("INSERT INTO fcc_rules(kind, enabled, threshold, owner_role, target_days, escalate_days) VALUES(?,?,?,?,?,?)",
                      (k[0], 0 if used else 1, k[4], k[6], k[7], k[8]))
    if not q1(c, "SELECT 1 FROM settings WHERE key='wn_alerts'"):
        c.execute("INSERT INTO settings(key, value) VALUES('wn_alerts', ?)", ("0" if used else "1",))
    c.commit()
    try:
        import api_safe
        if "wn_alerts" not in {s[0] for s in getattr(api_safe, "SWITCHES", [])}:
            api_safe.SWITCHES.append(("wn_alerts", "2.54 alerts (margin trend, time, expiry, fuel, re-order)",
                                      "Ten more kinds in the alerts register, with owners and escalation.",
                                      lambda v: v == "1", "#/action?tab=1", "admin", 4))
    except Exception:
        pass
