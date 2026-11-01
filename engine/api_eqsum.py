"""
Machine hours and output summary (BuildCore 2.33).

Reported from site on 2.32: opening a machine in Equipment showed no summary, so nobody could see how many hours the
machine had worked on a project, or how much the bucket and the breaker had done each month. Opening a machine now
shows, for one project (or all projects the user may see):
  1. Total operating hours as per the entries (logsheet days, including those written by approved DPRs), with
     days worked, idle, breakdown, fuel and trips, first and last day.
  2. Month by month: the same figures per month, by Nepali month when logsheets are kept per Nepali month (2.32
     setting) or when dates are shown in Nepali, otherwise by English month; the user can switch.
  3. Output per month by output / attachment (e.g. excavator: Bucket and Hydraulic rock breaker), hours and quantity
     each, read exactly as the monthly sheet reads them (2.30 / 2.32 rule: attachment lines of the day, else the DPR
     machine line, hours not split count at the machine's default output).
  4. DPR machine lines not approved yet are shown apart, as on the sheet, and are in no total.
Read only: nothing here writes, posts or changes a balance, and no table is added or changed.
"""
from datetime import date

from core import ApiError, get, q, r2, val
import api_inventory as inv
from api_inventory import api

VERSION = "2.33.0"
FLAG = "_bco233"
EPS = 1e-6


def init_eqsum(c):
    return None


def _allowed(c, u):
    try:
        import api_workspace as W
        return W.allowed_projects(c, u)
    except Exception:
        return None


def _month(cal, iso):
    import api_logbs as LB
    key, frm, to, label = LB.month_of(cal, iso)
    return key, frm, to, label


def _outputs(c, log):
    """[(tool or None, hours, output)] of one day, the rule of the monthly sheet (api_logbs.outputs_of)"""
    import api_life as L
    try:
        return L._tool_hours(c, log)
    except Exception:
        return [(None, log["hours"] or 0, None)]


def summary(c, u, a):
    eq = get(c, "equipment", a.get("id") or a.get("equipment_id"), "Equipment")
    eid = eq["id"]
    import api_logbs as LB
    cal = (a.get("calendar") or "").lower()
    if cal not in ("ad", "bs"):
        cal = LB.calendar(c)
    allow = _allowed(c, u)
    # the projects this machine has days on (only those the user may enter)
    projs = []
    for r in q(c, "SELECT l.project_id, p.code, p.name, COUNT(DISTINCT CASE WHEN l.hours>0 THEN l.date END) days, "
                  "ROUND(SUM(l.hours),2) hours, MIN(l.date) first, MAX(l.date) last FROM logsheets l "
                  "LEFT JOIN projects p ON p.id=l.project_id WHERE l.equipment_id=? GROUP BY l.project_id "
                  "ORDER BY MAX(l.date) DESC", (eid,)):
        if allow is not None and r["project_id"] not in allow:
            continue
        projs.append(dict(r, hours=r2(r["hours"] or 0)))
    # a project given (in a Project Workspace always the open project) > all projects > the machine's project
    pid = a.get("project_id")
    if pid in ("", 0, "0"):
        pid = None
    if pid is None and not a.get("all"):
        if eq.get("project_id") and any(p["project_id"] == eq["project_id"] for p in projs):
            pid = eq["project_id"]
        elif len(projs) == 1:
            pid = projs[0]["project_id"]
    if pid is not None:
        pid = int(pid)
        if allow is not None and pid not in allow:
            raise ApiError("PROJECT_DENIED: this record belongs to a project that is not assigned to you.")
    cond, p = "l.equipment_id=?", [eid]
    if pid is not None:
        cond += " AND l.project_id=?"
        p.append(pid)
    elif allow is not None:
        ids = sorted(allow) or [-1]
        cond += " AND l.project_id IN (%s)" % ",".join("?" * len(ids))
        p += ids
    if a.get("from"):
        cond += " AND l.date>=?"
        p.append(a["from"][:10])
    if a.get("to"):
        cond += " AND l.date<=?"
        p.append(a["to"][:10])
    logs = q(c, "SELECT l.* FROM logsheets l WHERE " + cond + " ORDER BY l.date, l.shift, l.id", p)

    tools = q(c, "SELECT id, name, kind, output_unit, norm_output_hr, is_default FROM eq_tools WHERE equipment_id=? "
                 "AND active=1 ORDER BY is_default DESC, id", (eid,))
    cols = {}                      # output name -> column
    for t in tools:
        cols[t["name"]] = {"name": t["name"], "kind": t["kind"], "unit": t["output_unit"] or "", "norm_output_hr": t["norm_output_hr"],
                           "hours": 0.0, "qty": 0.0, "has_qty": False, "out_hours": 0.0}
    months = {}
    tot = {"days": set(), "hours": 0.0, "idle": 0.0, "breakdown": 0.0, "standby": 0.0, "fuel": 0.0, "trips": 0.0, "km": 0.0,
           "draft_hours": 0.0, "dpr_days": 0, "entries": 0}
    for l in logs:
        key, frm, to, label = _month(cal, l["date"])
        m = months.get(key)
        if not m:
            m = months[key] = {"key": key, "label": label, "from": frm, "to": to, "days": set(), "hours": 0.0, "idle": 0.0,
                               "breakdown": 0.0, "standby": 0.0, "fuel": 0.0, "trips": 0.0, "km": 0.0, "draft_hours": 0.0,
                               "entries": 0, "out": {}}
        h_ = l["hours"] or 0
        for tgt in (m, tot):
            if h_ > 0:
                tgt["days"].add(l["date"])
            tgt["hours"] += h_
            tgt["idle"] += l["idle_hours"] or 0
            tgt["breakdown"] += l["breakdown_hours"] or 0
            tgt["standby"] += l.get("standby_hours") or 0
            tgt["fuel"] += l.get("fuel_qty") or 0
            tgt["trips"] += l["trips"] or 0
            tgt["km"] += l.get("km_run") or 0
            tgt["entries"] += 1
            if (l["status"] or "draft") != "approved":
                tgt["draft_hours"] += h_
        if l.get("dpr_id"):
            tot["dpr_days"] += 1
        for t, th, oq in (_outputs(c, l) if h_ > 0 or l.get("dpr_id") else []):
            name = (t or {}).get("name") or "Not split"
            col = cols.get(name)
            if not col:
                col = cols[name] = {"name": name, "kind": (t or {}).get("kind") or "", "unit": (t or {}).get("output_unit") or "",
                                    "norm_output_hr": (t or {}).get("norm_output_hr"), "hours": 0.0, "qty": 0.0, "has_qty": False,
                                    "out_hours": 0.0}
            col["hours"] += th or 0
            o = m["out"].setdefault(name, {"hours": 0.0, "qty": 0.0})
            o["hours"] += th or 0
            if oq:
                col["qty"] += oq
                col["out_hours"] += th or 0
                col["has_qty"] = True
                o["qty"] += oq
    # DPR machine lines not approved yet (draft, submitted, checked, returned): shown apart, in no total
    waiting = []
    lo, hi = (a.get("from") or "0000-01-01")[:10], (a.get("to") or "9999-12-31")[:10]
    for w in LB.pending(c, eid, lo, hi):
        if pid is not None and w.get("project_id") != pid:
            continue
        if pid is None and allow is not None and w.get("project_id") not in allow:
            continue
        key, _f, _t, label = _month(cal, w["date"])
        waiting.append({"date": w["date"], "shift": w["shift"], "dpr_no": w["dpr_no"], "dpr_status": w["dpr_status"],
                        "hours": w["hours"], "out_text": w["out_text"], "month": key, "month_label": label})
        if key in months:
            months[key]["waiting_hours"] = r2(months[key].get("waiting_hours", 0) + (w["hours"] or 0))
    out_cols = [c_ for c_ in cols.values() if c_["hours"] > EPS or c_["has_qty"] or c_["name"] in {t["name"] for t in tools}]
    rows = []
    for k in sorted(months, key=lambda x: months[x]["from"]):
        m = months[k]
        rows.append({"key": m["key"], "label": m["label"], "from": m["from"], "to": m["to"], "days": len(m["days"]),
                     "hours": r2(m["hours"]), "idle": r2(m["idle"]), "breakdown": r2(m["breakdown"]), "standby": r2(m["standby"]),
                     "fuel": r2(m["fuel"]), "trips": r2(m["trips"]), "km": r2(m["km"]), "draft_hours": r2(m["draft_hours"]),
                     "entries": m["entries"], "waiting_hours": m.get("waiting_hours", 0),
                     "fuel_per_hour": r2(m["fuel"] / m["hours"]) if m["hours"] > EPS and m["fuel"] else None,
                     "outputs": {n: {"hours": r2(o["hours"]), "qty": r2(o["qty"])} for n, o in m["out"].items()}})
    outputs = []
    for col in out_cols:
        outputs.append({"name": col["name"], "kind": col["kind"], "unit": col["unit"], "hours": r2(col["hours"]),
                        "qty": r2(col["qty"]) if col["has_qty"] else None, "has_qty": col["has_qty"],
                        "per_hour": r2(col["qty"] / col["out_hours"]) if col["has_qty"] and col["out_hours"] > EPS else None,
                        "output_hours": r2(col["out_hours"]),
                        "norm_output_hr": col["norm_output_hr"]})
    proj = None
    if pid is not None:
        pr = q(c, "SELECT id, code, name FROM projects WHERE id=?", (pid,))
        proj = pr[0] if pr else {"id": pid, "code": "", "name": ""}
    hours = tot["hours"]
    return {"equipment": {"id": eid, "code": eq["code"], "name": eq["name"], "category": eq.get("category"),
                          "meter_type": eq.get("meter_type"), "current_project_id": eq.get("project_id")},
            "calendar": cal, "sheet_calendar": LB.calendar(c), "project_id": pid, "project": proj, "projects": projs,
            "totals": {"days": len(tot["days"]), "hours": r2(hours), "idle": r2(tot["idle"]), "breakdown": r2(tot["breakdown"]),
                       "standby": r2(tot["standby"]), "fuel": r2(tot["fuel"]), "trips": r2(tot["trips"]), "km": r2(tot["km"]),
                       "draft_hours": r2(tot["draft_hours"]), "entries": tot["entries"], "dpr_entries": tot["dpr_days"],
                       "fuel_per_hour": r2(tot["fuel"] / hours) if hours > EPS and tot["fuel"] else None,
                       "avg_per_day": r2(hours / len(tot["days"])) if tot["days"] else None,
                       "first": logs[0]["date"] if logs else None, "last": logs[-1]["date"] if logs else None,
                       "months": len(rows), "waiting_hours": r2(sum(w["hours"] or 0 for w in waiting))},
            "months": rows, "outputs": outputs, "waiting": waiting,
            "rule": "Hours as per the logsheet days of this machine (days written by approved DPRs and days entered on "
                    "the logsheet). Output by attachment as on the monthly sheet. DPR lines not approved yet are shown "
                    "apart and are in no total."}


@api("eq.summary", "equipment", "view")
def eq_summary(c, u, a):
    return summary(c, u, a)


eq_summary._bco233 = True
