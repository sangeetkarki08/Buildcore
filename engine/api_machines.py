"""BuildCore 2.59 "Machines" (C1/R6, P4, C3/R7, C6, P5).

* One machine page (C1): for one machine and a period - hours, idle and breakdown, utilisation; cost per hour (running,
  depreciation, loan interest); what it charged each project; depreciation by month and loan instalments; repairs and
  work orders; fuel against its norm by month; papers and expiry dates; where it has worked; and the answer to
  "is this machine making or losing money?".  The eight older screens stay; Monthly review pack > Simpler menu can
  hide five of them (R6), off until chosen.
* Company-wide machines and manpower (P4): machine hours each project's programme needs week by week (resources on
  the activities, spread over the remaining dates), against the machines on that project and the whole fleet; weeks
  short, machines with no work ahead, machines under repair; suggestions "move X from A to B" or "hire".  Labour
  heads per week from the programme and key staff per project.  Nothing moves by itself.
* One depreciation screen (C3/R7): switch mc_dep_one (off on existing companies) makes Fixed assets > Depreciation run
  the only screen that posts; Equipment > Depreciation and Assets > Asset depreciation then refuse with a pointer.
  It can be turned on only when every owned machine is in the capital register.
* Breakdown to repair (C6): logsheet days with breakdown hours and no work order are listed; "Open the work orders"
  opens one breakdown work order per machine and spell.  Switch mc_bd_on (off on existing companies) does it when a
  logsheet is saved or approved.  The work order's downtime already feeds availability.
* Weekly planning (P5): look-ahead constraint "Machines on the project" from the machine plan; company view of which
  projects committed this week and their PPC; printable week plan per foreman; alerts "Week not committed",
  "PPC below 60% two weeks running", "Machines short", "Machine with no work ahead" in the alerts register (off on
  existing companies).
"""
import json
import math
from datetime import date, timedelta

import core
from core import ApiError, audit, ins, now, q, q1, setting, today, upd, val
import api_inventory as inv
from api_inventory import api

VERSION = "2.59.0"
FLAG = "_bco259"
EPS = 0.0005

SCHEMA = """
CREATE TABLE IF NOT EXISTS mc_map(id INTEGER PRIMARY KEY, name TEXT UNIQUE, mkey TEXT);
"""
# machine kinds: key, label, words matched in a resource or machine name (first match wins, specific first)
KINDS = [("tanker", "Water tanker", ("tanker", "bowser")), ("transit", "Transit mixer", ("transit mixer",)),
         ("pump", "Concrete pump", ("concrete pump",)), ("batching", "Batching plant", ("batching",)),
         ("mixer", "Concrete mixer", ("mixer",)), ("excavator", "Excavator", ("excavator", "breaker", "poclain")),
         ("backhoe", "Backhoe / loader", ("backhoe", "loader", "jcb")), ("dozer", "Dozer", ("dozer",)),
         ("grader", "Motor grader", ("grader",)), ("roller", "Roller", ("roller", "compactor")),
         ("paver", "Paver", ("paver", "finisher")), ("tipper", "Tipper / truck", ("tipper", "dump", "truck")),
         ("tractor", "Tractor", ("tractor",)), ("crane", "Crane", ("crane",)), ("compressor", "Compressor", ("compressor",)),
         ("generator", "Generator", ("generator", "genset")), ("bitumen", "Bitumen plant", ("bitumen", "distributor", "sprayer")),
         ("broom", "Broom", ("broom",)), ("vibrator", "Vibrator", ("vibrator",))]
KLABEL = {k: l for k, l, _w in KINDS}
DOWN = ("breakdown", "under_maintenance")


def _f(x, d=0.0):
    try:
        return float(x) if x not in (None, "") else d
    except (TypeError, ValueError):
        return d


def r2(x):
    return round(_f(x) + 0.0, 2)


def _set(c, k, v):
    c.execute("INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (k, v))


def _has(c, t):
    return bool(q1(c, "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (t,)))


def _call(c, u, name, args):
    f, module, action, _p = inv.FUNCS[name]
    if module:
        core.require(u, module, action)
    return f(c, u, dict(args))


def kind_of(text, mp=None):
    t = (text or "").lower()
    if mp and t in mp:
        return mp[t]
    for k, _l, words in KINDS:
        if any(w in t for w in words):
            return k
    return None


def eq_kind(c, e, mp=None):
    return kind_of(e["name"], mp) or kind_of(e["category"], mp)


def _sunday(d):
    d = date.fromisoformat(d[:10]) if isinstance(d, str) else d
    return d - timedelta(days=(d.weekday() + 1) % 7)


def _cap(c):
    return (core.fsetting(c, "shift_hours") or 10) * 6


# ───────────────────────── C1: one machine page ─────────────────────────
@api("mc.machines", "equipment", "view")
def mc_machines(c, u, a):
    rows = q(c, "SELECT e.id, e.code, e.name, e.category, e.ownership, e.status, p.code project FROM equipment e LEFT JOIN projects p ON p.id=e.project_id "
                "WHERE COALESCE(e.active,1)=1 ORDER BY e.code")
    return {"rows": rows}


@api("mc.machine", "equipment", "view")
def mc_machine(c, u, a):
    eid = int(a["equipment_id"])
    e = q1(c, "SELECT e.*, p.code pcode, pa.name vendor FROM equipment e LEFT JOIN projects p ON p.id=e.project_id LEFT JOIN parties pa ON pa.id=e.vendor_id WHERE e.id=?", (eid,))
    if not e:
        raise ApiError("Machine not found.")
    to = a.get("to") or today()
    frm = a.get("from") or (date.fromisoformat(to) - timedelta(days=364)).isoformat()
    import api_exec as X
    cost = X.eq_cost_row(c, e, frm, to)
    gain = r2(_f(cost["earned"]) + _f(cost["hire_out"]) - _f(cost["economic_cost"]))
    if e["ownership"] in ("hired", "rented", "rental"):
        verdict = "Hired machine: the hire bills are its cost (shown under cost per hour)."
    elif cost["economic_cost"] <= EPS and cost["earned"] <= EPS:
        verdict = "No cost or charge in the books for this period."
    else:
        verdict = ("Making money: charged %s more than it cost" if gain >= 0 else "Losing money: cost %s more than it charged") % fmt(abs(gain))
    charged = q(c, "SELECT p.code project, SUM(l.credit-l.debit) amount FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id JOIN accounts ac ON ac.id=l.account_id "
                   "LEFT JOIN projects p ON p.id=l.project_id WHERE l.equipment_id=? AND ac.role IN ('equipment_recovery','equip_recovery') AND v.status='posted' "
                   "AND v.date BETWEEN ? AND ? GROUP BY l.project_id ORDER BY amount DESC", (eid, frm, to))
    hours_by = {r["project_id"]: r for r in q(c, "SELECT project_id, SUM(hours) h, SUM(idle_hours) i, SUM(breakdown_hours) b FROM logsheets WHERE equipment_id=? "
                                                 "AND date BETWEEN ? AND ? GROUP BY project_id", (eid, frm, to))}
    by_project = []
    for pid, r in hours_by.items():
        pc = val(c, "SELECT code FROM projects WHERE id=?", (pid,))
        ch = next((x["amount"] for x in charged if x["project"] == pc), 0)
        by_project.append({"project": pc, "hours": r2(r["h"]), "idle": r2(r["i"]), "breakdown": r2(r["b"]), "charged": r2(ch)})
    months = []
    m0 = date.fromisoformat(frm[:8] + "01")
    while m0.isoformat() <= to:
        m1 = (m0.replace(day=28) + timedelta(days=4)).replace(day=1)
        ms, me = m0.isoformat(), (m1 - timedelta(days=1)).isoformat()
        h = q1(c, "SELECT SUM(hours) h, SUM(idle_hours) i, SUM(breakdown_hours) b FROM logsheets WHERE equipment_id=? AND date BETWEEN ? AND ?", (eid, ms, me))
        fuel = _f(val(c, "SELECT SUM(l.qty-COALESCE(l.returned_qty,0)) FROM issue_lines l JOIN issues i ON i.id=l.issue_id JOIN materials m ON m.id=l.material_id "
                         "WHERE i.status='posted' AND l.equipment_id=? AND i.date BETWEEN ? AND ? AND (LOWER(COALESCE(m.category,'')) LIKE '%fuel%' OR "
                         "LOWER(m.name) LIKE '%diesel%' OR LOWER(m.name) LIKE '%petrol%')", (eid, ms, me)))
        dep = _f(val(c, "SELECT SUM(amount) FROM dep_runs WHERE equipment_id=? AND month=?", (eid, ms[:7])))
        emi = _f(val(c, "SELECT SUM(amount) FROM eq_emi WHERE equipment_id=? AND date BETWEEN ? AND ?", (eid, ms, me))) if _has(c, "eq_emi") else 0
        hrs = _f(h["h"])
        months.append({"month": ms[:7], "hours": r2(hrs), "idle": r2(h["i"]), "breakdown": r2(h["b"]), "fuel": r2(fuel),
                       "fuel_per_hour": r2(fuel / hrs) if hrs > EPS else None, "norm": e["fuel_norm"],
                       "over_norm": bool(hrs > EPS and e["fuel_norm"] and fuel / hrs > e["fuel_norm"] * 1.15), "depreciation": r2(dep), "emi": r2(emi)})
        m0 = m1
    while len(months) > 1 and not (months[0]["hours"] or months[0]["fuel"] or months[0]["depreciation"] or months[0]["emi"]):
        months.pop(0)
    wos = q(c, "SELECT no, type, status, reported_at, completed_at, description, downtime_hours, parts_cost, labour_cost, external_cost, source FROM work_orders "
               "WHERE equipment_id=? ORDER BY id DESC LIMIT 60", (eid,))
    parts = q(c, "SELECT i.date, i.no, m.name material, l.qty, m.unit, l.amount FROM issue_lines l JOIN issues i ON i.id=l.issue_id JOIN materials m ON m.id=l.material_id "
                 "WHERE i.status='posted' AND l.equipment_id=? AND NOT (LOWER(COALESCE(m.category,'')) LIKE '%fuel%' OR LOWER(m.name) LIKE '%diesel%' OR LOWER(m.name) LIKE '%petrol%') "
                 "AND i.date BETWEEN ? AND ? ORDER BY i.date DESC LIMIT 100", (eid, frm, to))
    t = today()
    papers = []
    for col, what in (("insurance_expiry", "Insurance"), ("registration_expiry", "Registration (bluebook)"), ("operator_cert_expiry", "Operator licence")):
        d = e[col]
        papers.append({"paper": what, "expiry": d, "state": "missing" if not d else "expired" if d < t else "due in %d days" % (date.fromisoformat(d) - date.fromisoformat(t)).days
                       if d <= (date.fromisoformat(t) + timedelta(days=60)).isoformat() else "valid"})
    docs = q(c, "SELECT id, title, doc_number, doc_date, file_name FROM dl_docs WHERE entity='equipment' AND entity_id=? AND COALESCE(active,1)=1 ORDER BY doc_date DESC", (eid,)) \
        if _has(c, "dl_docs") else []
    deps = q(c, "SELECT d.*, p.code project FROM deployments d LEFT JOIN projects p ON p.id=d.project_id WHERE d.equipment_id=? ORDER BY d.mob_date DESC", (eid,))
    hire = q(c, "SELECT h.*, pa.name vendor FROM hire_agreements h LEFT JOIN parties pa ON pa.id=h.vendor_id WHERE h.equipment_id=? ORDER BY h.start_date DESC", (eid,)) \
        if _has(c, "hire_agreements") else []
    fin = q1(c, "SELECT * FROM eq_finance WHERE equipment_id=?", (eid,)) if _has(c, "eq_finance") else None
    return {"machine": dict(e), "from": frm, "to": to, "cost": cost, "gain": gain, "verdict": verdict, "by_project": by_project, "months": months,
            "work_orders": wos, "parts": parts, "papers": papers, "docs": docs, "deployments": deps, "hire": hire, "finance": fin,
            "kind": KLABEL.get(eq_kind(c, e, _map(c)))}


def fmt(x):
    return "{:,.0f}".format(_f(x))


# ───────────────────────── P4: company-wide machines and manpower ─────────────────────────
def _map(c):
    return {r["name"]: r["mkey"] for r in q(c, "SELECT name, mkey FROM mc_map")} if _has(c, "mc_map") else {}


def _spread(c, kind_letter, weeks, start):
    """{(project_id, name): {week_index: qty}} from the programme's activity resources, spread over the remaining dates."""
    end = start + timedelta(days=7 * len(weeks))
    t0 = max(start, date.fromisoformat(today()))
    out = {}
    for r in q(c, "SELECT r.project_id, r.name, r.unit, r.qty_total, a.es, a.ef, a.planned_start, a.planned_finish, a.actual_finish, a.pct_complete, "
                  "a.planned_qty, a.actual_qty FROM act_resources r JOIN activities a ON a.id=r.activity_id JOIN projects p ON p.id=r.project_id "
                  "WHERE r.kind=? AND COALESCE(p.status,'active')='active' AND a.actual_finish IS NULL", (kind_letter,)):
        s, f = r["es"] or r["planned_start"], r["ef"] or r["planned_finish"]
        if not s or not f:
            continue
        s, f = date.fromisoformat(s[:10]), date.fromisoformat(f[:10])
        done = _f(r["pct_complete"]) / 100 if r["pct_complete"] is not None else ((_f(r["actual_qty"]) / _f(r["planned_qty"])) if _f(r["planned_qty"]) > 0 else 0)
        left = _f(r["qty_total"]) * max(0.0, 1 - min(done, 1))
        s2 = max(s, t0)
        if f < s2 or left <= EPS or s2 >= end:
            continue
        span = (f - s2).days + 1
        per = left / span
        d = out.setdefault((r["project_id"], r["name"]), {})
        for i, w in enumerate(weeks):
            ws, we = max(w, s2), min(w + timedelta(days=6), f)
            n = (we - ws).days + 1
            if n > 0:
                d[i] = d.get(i, 0) + per * n
    return out


@api("mc.plan", "equipment", "view")
def mc_plan(c, u, a):
    nweeks = max(4, min(int(a.get("weeks") or 12), 26))
    start = _sunday(a.get("from") or today())
    weeks = [start + timedelta(days=7 * i) for i in range(nweeks)]
    cap = _cap(c)
    mp = _map(c)
    projects = {p["id"]: p["code"] for p in q(c, "SELECT id, code FROM projects")}
    # demand (machines needed) per kind, project, week
    dem = {}
    unmatched = {}
    for (pid, name), wk in _spread(c, "E", weeks, start).items():
        k = kind_of(name, mp)
        if not k:
            unmatched[name] = unmatched.get(name, 0) + sum(wk.values())
            continue
        for i, hrs in wk.items():
            dem.setdefault(k, {}).setdefault(pid, [0.0] * nweeks)[i] += hrs / cap
    # supply
    fleet = {}
    machines = []
    since = (date.fromisoformat(today()) - timedelta(days=14)).isoformat()
    for e in q(c, "SELECT * FROM equipment WHERE COALESCE(active,1)=1 AND COALESCE(status,'') NOT IN ('disposed','sold','scrapped') ORDER BY code"):
        k = eq_kind(c, e, mp)
        last = val(c, "SELECT MAX(date) FROM logsheets WHERE equipment_id=?", (e["id"],))
        recent = _f(val(c, "SELECT SUM(hours) FROM logsheets WHERE equipment_id=? AND date>=?", (e["id"], since)))
        m = {"id": e["id"], "code": e["code"], "name": e["name"], "kind": k, "kind_label": KLABEL.get(k, "Other"), "project_id": e["project_id"],
             "project": projects.get(e["project_id"]), "status": e["status"], "ownership": e["ownership"], "down": e["status"] in DOWN,
             "last_log": last, "hours_14d": r2(recent)}
        machines.append(m)
        if k:
            fleet.setdefault(k, []).append(m)
    rows, clashes, suggestions, idle = [], [], [], []
    for k in sorted(set(dem) | set(fleet), key=lambda x: KLABEL.get(x, x)):
        have = fleet.get(k, [])
        up = [m for m in have if not m["down"]]
        pids = set(dem.get(k, {})) | {m["project_id"] for m in have if m["project_id"]}
        for pid in sorted(pids, key=lambda x: projects.get(x) or ""):
            need = [r2(x) for x in dem.get(k, {}).get(pid, [0.0] * nweeks)]
            on = len([m for m in up if m["project_id"] == pid])
            rows.append({"kind": k, "kind_label": KLABEL.get(k, k), "project_id": pid, "project": projects.get(pid), "have": on,
                         "down": len([m for m in have if m["project_id"] == pid and m["down"]]), "need": need,
                         "short": [max(0, math.ceil(x - 0.15) - on) for x in need]})
        tot = [sum(dem.get(k, {}).get(p, [0.0] * nweeks)[i] for p in dem.get(k, {})) for i in range(nweeks)]
        tot_need = [math.ceil(x - 0.15) if x > 0.15 else 0 for x in tot]
        rows.append({"kind": k, "kind_label": KLABEL.get(k, k), "project_id": None, "project": "Company", "have": len(up), "down": len(have) - len(up),
                     "need": [r2(x) for x in tot], "short": [max(0, n - len(up)) for n in tot_need], "total": True})
        for i, n in enumerate(tot_need):
            if n > len(up):
                clashes.append({"week": weeks[i].isoformat(), "kind": KLABEL.get(k, k), "need": n, "have": len(up), "short": n - len(up)})
        # suggestions: project short while another has a spare
        for i in range(min(nweeks, 4)):
            spare = {}
            for pid in pids:
                n = math.ceil(dem.get(k, {}).get(pid, [0.0] * nweeks)[i] - 0.15)
                on = [m for m in up if m["project_id"] == pid]
                spare[pid] = (max(0, n), on)
            for pid, (n, on) in spare.items():
                gap = n - len(on)
                if gap <= 0:
                    continue
                for opid, (on_, mach) in spare.items():
                    if opid == pid or len(mach) <= on_ or gap <= 0:
                        continue
                    for m in mach[on_:]:
                        if gap <= 0:
                            break
                        s = {"week": weeks[i].isoformat(), "kind": KLABEL.get(k, k), "machine": m["code"], "machine_id": m["id"], "from": projects.get(opid),
                             "to": projects.get(pid), "to_id": pid, "text": "Move %s from %s to %s by %s" % (m["code"], projects.get(opid) or "the yard", projects.get(pid), weeks[i].isoformat())}
                        if not any(x["machine"] == s["machine"] for x in suggestions):
                            suggestions.append(s)
                        gap -= 1
                if gap > 0 and not any(x["kind"] == KLABEL.get(k, k) and x["to"] == projects.get(pid) and x.get("hire") for x in suggestions):
                    suggestions.append({"week": weeks[i].isoformat(), "kind": KLABEL.get(k, k), "to": projects.get(pid), "to_id": pid, "hire": gap,
                                        "text": "Hire %d %s for %s from %s (no spare in the fleet)" % (gap, KLABEL.get(k, k).lower(), projects.get(pid), weeks[i].isoformat())})
        # idle: on a project with no demand for its kind in the next 4 weeks and no hours in 14 days
        for m in up:
            ahead = sum(dem.get(k, {}).get(m["project_id"], [0.0] * nweeks)[:4])
            if ahead < 0.15 and m["hours_14d"] <= EPS:
                idle.append(dict(m, why="No %s work in the programme for the next 4 weeks and no logsheet hours in 14 days" % KLABEL.get(k, k).lower()))
    for m in machines:
        if not m["kind"] and m["hours_14d"] <= EPS and not m["down"]:
            idle.append(dict(m, why="No hours in 14 days (machine kind not known to the plan)"))
    return {"weeks": [w.isoformat() for w in weeks], "capacity_hours": cap, "rows": rows, "clashes": clashes, "suggestions": suggestions, "idle": idle,
            "down": [m for m in machines if m["down"]], "unmatched": [{"name": k, "hours": r2(v)} for k, v in sorted(unmatched.items(), key=lambda x: -x[1])],
            "kinds": [{"key": k, "label": l} for k, l, _w in KINDS], "machines": machines}


@api("mc.map_save", "equipment", "edit")
def mc_map_save(c, u, a):
    name = (a.get("name") or "").strip().lower()
    if not name:
        raise ApiError("Give the resource name.")
    k = a.get("kind") or None
    if k and k not in KLABEL:
        raise ApiError("Unknown machine kind.")
    if k:
        c.execute("INSERT INTO mc_map(name, mkey) VALUES(?, ?) ON CONFLICT(name) DO UPDATE SET mkey=excluded.mkey", (name, k))
    else:
        c.execute("DELETE FROM mc_map WHERE name=?", (name,))
    audit(c, u, "save", "mc_map", None, {"name": name, "kind": k})
    return {"ok": True}


@api("mc.people", "project", "view")
def mc_people(c, u, a):
    nweeks = max(4, min(int(a.get("weeks") or 12), 26))
    start = _sunday(a.get("from") or today())
    weeks = [start + timedelta(days=7 * i) for i in range(nweeks)]
    projects = {p["id"]: p for p in q(c, "SELECT id, code, name, status, kind FROM projects")}
    lab = {}
    for (pid, name), wk in _spread(c, "L", weeks, start).items():
        nm = "Skilled" if any(w in name.lower() for w in ("skilled", "mason", "carpenter", "finisher", "operator", "सिपालु", "fitter", "welder")) and "unskilled" not in name.lower() else "Unskilled"
        row = lab.setdefault((pid, nm), [0.0] * nweeks)
        for i, d in wk.items():
            row[i] += d / 6.0
    labour = [{"project": projects[p]["code"] if p in projects else p, "kind": k, "heads": [round(x, 1) for x in v]} for (p, k), v in sorted(lab.items(), key=lambda x: (str(x[0][0]), x[0][1]))]
    staff = q(c, "SELECT s.code, s.name, s.designation, p.code project, s.project_id FROM staff s LEFT JOIN projects p ON p.id=s.project_id WHERE COALESCE(s.active,1)=1 ORDER BY p.code, s.designation")
    key = ("engineer", "manager", "surveyor", "supervisor", "foreman")
    gaps = []
    for pid, p in projects.items():
        if (p["kind"] or "project") != "project" or (p["status"] or "active") != "active":
            continue
        work = val(c, "SELECT COUNT(*) FROM activities WHERE project_id=? AND actual_finish IS NULL AND COALESCE(es, planned_start)<=?", (pid, weeks[min(3, nweeks - 1)].isoformat()))
        if not work:
            continue
        mine = [s for s in staff if s["project_id"] == pid]
        for kword, label in (("engineer", "engineer"), ("manager", "project manager")):
            if not any(kword in (s["designation"] or "").lower() for s in mine):
                gaps.append({"project": p["code"], "missing": label, "why": "Work in the programme in the next 4 weeks, no %s on the staff list" % label})
    free = [s for s in staff if not s["project_id"] and any(k in (s["designation"] or "").lower() for k in key)]
    return {"weeks": [w.isoformat() for w in weeks], "labour": labour, "staff": staff, "gaps": gaps, "free": free}


# ───────────────────────── C6: breakdown to repair ─────────────────────────
def _breakdown_spells(c, eid=None, since=None):
    cond, p = "breakdown_hours>0", []
    if eid:
        cond += " AND equipment_id=?"
        p.append(eid)
    if since:
        cond += " AND date>=?"
        p.append(since)
    out = []
    cur = None
    for r in q(c, "SELECT id, equipment_id, project_id, date, breakdown_hours, down_reason FROM logsheets WHERE " + cond + " ORDER BY equipment_id, date", p):
        if cur and cur["equipment_id"] == r["equipment_id"] and (date.fromisoformat(r["date"]) - date.fromisoformat(cur["to"])).days <= 1:
            cur["to"] = r["date"]
            cur["hours"] += _f(r["breakdown_hours"])
            cur["ids"].append(r["id"])
            if r["down_reason"] and not cur["reason"]:
                cur["reason"] = r["down_reason"]
        else:
            cur = {"equipment_id": r["equipment_id"], "project_id": r["project_id"], "from": r["date"], "to": r["date"], "hours": _f(r["breakdown_hours"]),
                   "reason": r["down_reason"], "ids": [r["id"]]}
            out.append(cur)
    res = []
    for s in out:
        wo = q1(c, "SELECT id, no, status FROM work_orders WHERE equipment_id=? AND type='breakdown' AND substr(reported_at,1,10)<=? AND "
                   "(completed_at IS NULL OR substr(completed_at,1,10)>=?) ORDER BY id DESC LIMIT 1", (s["equipment_id"], s["to"], s["from"]))
        if not wo:
            wo = q1(c, "SELECT id, no, status FROM work_orders WHERE equipment_id=? AND source='logsheet' AND source_ref=?", (s["equipment_id"], "%s:%s" % (s["equipment_id"], s["from"])))
        e = q1(c, "SELECT code, name FROM equipment WHERE id=?", (s["equipment_id"],))
        res.append(dict(s, hours=r2(s["hours"]), days=len(s["ids"]), code=e["code"] if e else None, name=e["name"] if e else None, work_order=wo))
    return res


@api("mc.breakdowns", "equipment", "view")
def mc_breakdowns(c, u, a):
    since = a.get("from") or (date.fromisoformat(today()) - timedelta(days=90)).isoformat()
    rows = _breakdown_spells(c, since=since)
    return {"rows": rows, "missing": sum(1 for r in rows if not r["work_order"]), "on": setting(c, "mc_bd_on") == "1", "from": since}


def open_work_orders(c, u, eid=None, since=None):
    made = []
    for s in _breakdown_spells(c, eid, since):
        if s["work_order"]:
            continue
        wid = ins(c, "work_orders", {"no": core.next_no(c, "WO", s["from"]), "equipment_id": s["equipment_id"], "project_id": s["project_id"], "type": "breakdown",
                                    "status": "open", "reported_at": s["from"] + "T08:00:00", "description": "Breakdown on the logsheet %s%s: %s h%s" % (
                                        s["from"], (" to " + s["to"]) if s["to"] != s["from"] else "", s["hours"], (" - " + s["reason"]) if s["reason"] else ""),
                                    "created_by": u["id"], "source": "logsheet", "source_ref": "%s:%s" % (s["equipment_id"], s["from"])})
        made.append(wid)
    if made:
        audit(c, u, "create", "work_orders", None, {"from_logsheets": len(made)})
    return made


@api("mc.open_work_orders", "equipment", "edit")
def mc_open_work_orders(c, u, a):
    since = a.get("from") or (date.fromisoformat(today()) - timedelta(days=90)).isoformat()
    made = open_work_orders(c, u, None, since)
    return {"made": len(made)}


def _w_log(orig):
    def log_fn(c, u, a):
        r = orig(c, u, a)
        if setting(c, "mc_bd_on") == "1":
            try:
                row = a.get("row") or {}
                since = (date.fromisoformat(today()) - timedelta(days=60)).isoformat()
                eids = [row.get("equipment_id")] if row.get("equipment_id") else []
                if not eids and a.get("id") and a.get("_dpr"):
                    eids = [x["equipment_id"] for x in q(c, "SELECT DISTINCT equipment_id FROM logsheets WHERE dpr_id=? AND breakdown_hours>0", (int(a["id"]),))]
                elif not eids and a.get("id"):
                    eids = [val(c, "SELECT equipment_id FROM logsheets WHERE id=?", (int(a["id"]),))]
                for eid in eids:
                    if eid:
                        open_work_orders(c, u, int(eid), since)
            except Exception:
                pass
        return r
    return log_fn


def _w_dpr(orig):
    inner = _w_log(orig)

    def dpr_approve(c, u, a):
        return inner(c, u, dict(a, _dpr=1))
    return dpr_approve


# ───────────────────────── C3/R7: one depreciation screen ─────────────────────────
def _w_dep(orig, where):
    def dep_fn(c, u, a):
        if setting(c, "mc_dep_one") == "1":
            raise ApiError("Depreciation is posted only from Fixed assets › Depreciation run on this company (one screen for all machines and assets). "
                           "This screen (%s) shows; it no longer posts." % where)
        return orig(c, u, a)
    return dep_fn


@api("mc.dep_view", "accounts", "view")
def mc_dep_view(c, u, a):
    """Which screen posted each month's depreciation, per machine (last 12 months)."""
    to = today()[:7]
    rows = q(c, "SELECT d.month, e.code, e.name, d.amount, v.no voucher, v.source FROM dep_runs d JOIN equipment e ON e.id=d.equipment_id LEFT JOIN vouchers v ON v.id=d.voucher_id "
                "WHERE d.month>=? ORDER BY d.month DESC, e.code", ((date.fromisoformat(to + "-01") - timedelta(days=365)).isoformat()[:7],))
    for r in rows:
        r["posted_from"] = "Fixed assets" if (r["source"] or "").startswith("fa") else "Equipment"
    missing = q(c, "SELECT code, name FROM equipment WHERE COALESCE(ownership,'owned') NOT IN ('hired','rented','rental') AND COALESCE(active,1)=1 AND "
                   "id NOT IN (SELECT ref_id FROM fa_register WHERE kind='equipment')") if _has(c, "fa_register") else []
    return {"rows": rows, "on": setting(c, "mc_dep_one") == "1", "not_in_register": missing}


# ───────────────────────── P5: weekly planning ─────────────────────────
def _w_look(orig):
    def look_get(c, u, a):
        d = orig(c, u, a)
        try:
            pid = int(a["project_id"])
            mp = _map(c)
            have = {}
            tracked = {eq_kind(c, e, mp) for e in q(c, "SELECT * FROM equipment WHERE COALESCE(active,1)=1")} - {None}
            for e in q(c, "SELECT * FROM equipment WHERE project_id=? AND COALESCE(active,1)=1", (pid,)):
                k = eq_kind(c, e, mp)
                if k:
                    have.setdefault(k, []).append(e)
            for r in d.get("rows") or []:
                need = {kind_of(x["name"], mp) for x in q(c, "SELECT name FROM act_resources WHERE activity_id=? AND kind='E'", (r["id"],))} & tracked
                if not need:
                    continue
                miss = [KLABEL[k] for k in need if not [e for e in have.get(k, []) if e["status"] not in DOWN]]
                chk = {"k": "machines_plan", "label": "Machines on the project (machine plan)", "ok": not miss,
                       "why": ("Not on the project or under repair: " + ", ".join(sorted(miss))) if miss else "All machine kinds this activity needs are on the project"}
                r["checks"].append(chk)
                r["ready"] = r["ready"] and chk["ok"]
            d["ready"] = sum(1 for r in d.get("rows") or [] if r["ready"])
            d["blocked"] = sum(1 for r in d.get("rows") or [] if not r["ready"])
        except Exception as e:
            d["machine_check_error"] = str(e)[:160]
        return d
    return look_get


def _wk(d=None):
    d = date.fromisoformat(d) if d else date.fromisoformat(today())
    return (d - timedelta(days=(d.weekday() + 1) % 7)).isoformat()


@api("mc.weeks", "project", "view")
def mc_weeks(c, u, a):
    this = _wk()
    nxt = (date.fromisoformat(this) + timedelta(days=7)).isoformat()
    out = []
    for p in q(c, "SELECT id, code, name FROM projects WHERE COALESCE(status,'active')='active' AND COALESCE(kind,'project') NOT IN ('trading','general') ORDER BY code"):
        acts = val(c, "SELECT COUNT(*) FROM activities WHERE project_id=?", (p["id"],))
        if not acts:
            continue
        ppc = _call(c, u, "look.ppc", {"project_id": p["id"]})["weeks"]
        last2 = [w["ppc"] for w in ppc[-2:]]
        out.append({"project_id": p["id"], "project": p["code"], "name": p["name"],
                    "this_week": val(c, "SELECT COUNT(*) FROM lookahead WHERE project_id=? AND week_start=?", (p["id"], this)),
                    "next_week": val(c, "SELECT COUNT(*) FROM lookahead WHERE project_id=? AND week_start=?", (p["id"], nxt)),
                    "ppc": last2, "low": len(last2) == 2 and all(x is not None and x < 60 for x in last2)})
    return {"this_week": this, "next_week": nxt, "rows": out}


@api("mc.week_plan", "project", "view")
def mc_week_plan(c, u, a):
    """The committed week grouped by foreman, for printing."""
    pid = int(a["project_id"])
    ws = a.get("week_start") or _wk()
    rows = q(c, "SELECT l.planned_qty, COALESCE(l.foreman, a.foreman, '(no foreman)') foreman, a.code, a.name, a.unit, a.location, a.chainage_from, a.chainage_to "
                "FROM lookahead l JOIN activities a ON a.id=l.activity_id WHERE l.project_id=? AND l.week_start=? ORDER BY foreman, a.code", (pid, ws))
    by = {}
    for r in rows:
        by.setdefault(r["foreman"], []).append(r)
    p = q1(c, "SELECT code, name FROM projects WHERE id=?", (pid,))
    return {"project": p, "week_start": ws, "week_end": (date.fromisoformat(ws) + timedelta(days=6)).isoformat(),
            "foremen": [{"foreman": k, "rows": v} for k, v in by.items()]}


# ───────────────────────── alerts ─────────────────────────
NEW_KINDS = [
    ("week_not_committed", "Week not committed (look-ahead)", "time", "medium", 0, "", "planner,project_manager", 2, 3),
    ("ppc_low", "PPC below the threshold two weeks running", "time", "medium", 60, "% PPC", "project_manager,planner", 7, 7),
    ("machine_short", "Machines short for the programme", "equipment", "medium", 0, "", "equipment_manager,project_manager", 7, 7),
    ("machine_idle", "Machine with no work ahead", "equipment", "low", 0, "", "equipment_manager", 7, 7),
]
NEW_ACTIONS = {
    "week_not_committed": "Open Look-ahead, check the constraints and commit the coming week's tasks with the foremen.",
    "ppc_low": "Look at the reasons for the missed tasks (Look-ahead › Review) and remove the main constraint.",
    "machine_short": "Open Machines › Company plan: move a machine from another project or hire.",
    "machine_idle": "Move it to a project that needs it (Company plan), hire it out, or return it if hired.",
}


def chk_plan(c, R, ctx):
    import api_fcc as F
    out = []
    t = ctx["today"]
    d = date.fromisoformat(t)
    this = (d - timedelta(days=(d.weekday() + 1) % 7)).isoformat()
    nxt = (date.fromisoformat(this) + timedelta(days=7)).isoformat()
    for p in q(c, "SELECT id, code FROM projects WHERE COALESCE(status,'active')='active' AND COALESCE(kind,'project') NOT IN ('trading','general')"):
        if not val(c, "SELECT COUNT(*) FROM activities WHERE project_id=? AND actual_finish IS NULL", (p["id"],)):
            continue
        used = val(c, "SELECT COUNT(*) FROM lookahead WHERE project_id=?", (p["id"],))
        if used and d.weekday() in (3, 4, 5) and not val(c, "SELECT COUNT(*) FROM lookahead WHERE project_id=? AND week_start=?", (p["id"], nxt)):
            out.append({"fkey": "wk:%d:%s" % (p["id"], nxt), "kind": "week_not_committed", "project_id": p["id"],
                        "title": "%s: the week from %s is not committed" % (p["code"], nxt), "amount": None, "due_date": nxt, "severity": "medium",
                        "basis": "Look-ahead: no committed task for the coming week.", "detail": "",
                        "sources": [F.src("look-ahead", nxt, "#/p/schedule", None, p["id"])]})
        if used:
            weeks = []
            for w in q(c, "SELECT DISTINCT week_start FROM lookahead WHERE project_id=? AND week_start<? ORDER BY week_start DESC LIMIT 2", (p["id"], this)):
                import api_sched
                weeks.append(api_sched.look_review(c, None, {"project_id": p["id"], "week_start": w["week_start"]})["ppc"])
            lim = R["ppc_low"]["threshold"] or 60
            if len(weeks) == 2 and all(x is not None and x < lim for x in weeks):
                out.append({"fkey": "ppc:%d:%s" % (p["id"], this), "kind": "ppc_low", "project_id": p["id"],
                            "title": "%s: PPC %s%% and %s%% in the last two weeks" % (p["code"], weeks[1], weeks[0]), "amount": None, "due_date": None,
                            "severity": "medium", "basis": "Look-ahead review from the approved DPRs.", "detail": "",
                            "sources": [F.src("look-ahead", this, "#/p/schedule", None, p["id"])]})
    try:
        pl = mc_plan(c, None, {"weeks": 4})
    except Exception:
        return out
    first = {}
    for x in pl["clashes"]:
        f = first.setdefault(x["kind"], dict(x, weeks=0))
        f["weeks"] += 1
    for x in first.values():
        out.append({"fkey": "mshort:%s" % x["kind"], "kind": "machine_short", "project_id": None,
                    "title": "%s: %d needed from the week of %s (%d of the next 4 weeks short), %d in the fleet" % (x["kind"], x["need"], x["week"], x["weeks"], x["have"]), "amount": None, "due_date": x["week"],
                    "severity": "medium", "basis": "Machine hours in the programmes against the machines working.", "detail": "", "sources": [F.src("machine plan", x["kind"], "#/mc/plan")]})
    for m in pl["idle"][:30]:
        out.append({"fkey": "midle:%d" % m["id"], "kind": "machine_idle", "project_id": m["project_id"],
                    "title": "%s %s (%s): %s" % (m["code"], m["name"], m["project"] or "no project", m["why"]), "amount": None, "due_date": None, "severity": "low",
                    "basis": "Programme and logsheets.", "detail": "", "sources": [F.src("equipment", m["code"], "#/mc/machine?id=%d" % m["id"], m["id"], m["project_id"])]})
    return out


def _connect(c):
    import api_fcc as F
    have = {k[0] for k in F.KINDS}
    for k in NEW_KINDS:
        if k[0] not in have:
            F.KINDS.append(k)
            F.KIND[k[0]] = k
    for k, v in NEW_ACTIONS.items():
        F.ACTIONS.setdefault(k, v)
    if "week_not_committed" not in {x[0] for x in F.CHECKS}:
        F.CHECKS.append(("week_not_committed", chk_plan))
    F.CHECK_KINDS.setdefault("week_not_committed", tuple(k[0] for k in NEW_KINDS))


# ───────────────────────── settings ─────────────────────────
@api("mc.settings", "equipment", "view")
def mc_settings(c, u, a):
    rows = {r["kind"]: r["enabled"] for r in q(c, "SELECT kind, enabled FROM fcc_rules")} if _has(c, "fcc_rules") else {}
    return {"bd_on": setting(c, "mc_bd_on") == "1", "dep_one": setting(c, "mc_dep_one") == "1",
            "alerts": [{"kind": k[0], "label": k[1], "enabled": bool(rows.get(k[0]))} for k in NEW_KINDS]}


@api("mc.settings_save", "accounts", "approve")
def mc_settings_save(c, u, a):
    if "dep_one" in a:
        on_ = a["dep_one"] in (1, "1", True)
        if on_ and _has(c, "fa_register"):
            miss = mc_dep_view(c, u, {})["not_in_register"]
            if miss:
                raise ApiError("%d owned machine(s) are not in the capital register yet (%s). Open Fixed assets and press \"Bring machines in\" first."
                               % (len(miss), ", ".join(m["code"] for m in miss[:6])))
        _set(c, "mc_dep_one", "1" if on_ else "0")
    if "bd_on" in a:
        _set(c, "mc_bd_on", "1" if a["bd_on"] in (1, "1", True) else "0")
    if "alerts" in a and _has(c, "fcc_rules"):
        flag = 1 if a["alerts"] in (1, "1", True) else 0
        for k in NEW_KINDS:
            c.execute("UPDATE fcc_rules SET enabled=? WHERE kind=?", (flag, k[0]))
    audit(c, u, "save", "settings", None, {"mc_bd_on": setting(c, "mc_bd_on"), "mc_dep_one": setting(c, "mc_dep_one"), "alerts": a.get("alerts")})
    return mc_settings(c, u, {})


def _wrap(name, factory):
    cur = inv.FUNCS.get(name)
    if not cur or getattr(cur[0], FLAG, False):
        return
    w = factory(cur[0])
    for f in [x for x in dir(cur[0]) if x.startswith("_bco")]:
        setattr(w, f, getattr(cur[0], f))
    setattr(w, FLAG, True)
    w._orig = cur[0]
    inv.FUNCS[name] = (w, cur[1], cur[2], cur[3])


def init_machines(c):
    c.executescript(SCHEMA)
    used = val(c, "SELECT COUNT(*) FROM vouchers") or val(c, "SELECT COUNT(*) FROM logsheets")
    for k in ("mc_bd_on", "mc_dep_one"):
        if not q1(c, "SELECT 1 FROM settings WHERE key=?", (k,)):
            _set(c, k, "0" if used else "1")
    if _has(c, "fcc_rules"):
        for k in NEW_KINDS:
            if not q1(c, "SELECT kind FROM fcc_rules WHERE kind=?", (k[0],)):
                c.execute("INSERT INTO fcc_rules(kind, enabled, threshold, owner_role, target_days, escalate_days) VALUES(?,?,?,?,?,?)",
                          (k[0], 0 if used else 1, k[4], k[6], k[7], k[8]))
    c.commit()
    try:
        _connect(c)
    except Exception:
        pass
    _wrap("log.save", _w_log)
    _wrap("log.approve", _w_log)
    _wrap("dpr.approve", _w_dpr)
    _wrap("dep.run", lambda o: _w_dep(o, "Equipment › Depreciation & hire charges"))
    _wrap("asset.dep_run", lambda o: _w_dep(o, "Assets › Asset depreciation"))
    _wrap("look.get", _w_look)
    try:
        import api_pack as P
        have = {x[0] for x in P.HIDE_CANDIDATES}
        for r in [("x/eqcost", "Equipment cost per hour", "Equipment", "The machine page (Machines › Machine page) shows cost per hour with the rest.", "yes"),
                  ("fa/costing", "Equipment costing", "Assets", "The machine page shows cost, depreciation and what it charged.", "yes"),
                  ("mg/eqpool", "Own equipment recovery", "Equipment", "The machine page shows what each machine charged against its cost.", "yes"),
                  ("cl/equipment", "Equipment business", "Equipment", "The machine page answers whether each machine makes or loses money.", "yes"),
                  ("eq/dep", "Depreciation & hire charges", "Equipment", "Fixed assets › Depreciation run and the machine page show it.", "yes")]:
            if r[0] not in have:
                P.HIDE_CANDIDATES.append(r)
    except Exception:
        pass
    try:
        import api_safe
        have = {s[0] for s in getattr(api_safe, "SWITCHES", [])}
        if "mc_bd_on" not in have:
            api_safe.SWITCHES.append(("mc_bd_on", "Breakdown opens a work order (2.59)", "Breakdown hours on a logsheet open a breakdown work order by themselves.",
                                      lambda v: v == "1", "#/mc/plan?tab=5", "accounts approve", 13))
        if "mc_dep_one" not in have:
            api_safe.SWITCHES.append(("mc_dep_one", "Depreciation from one screen (2.59)", "Only Fixed assets › Depreciation run posts depreciation; the other two screens show.",
                                      lambda v: v == "1", "#/mc/plan?tab=5", "accounts approve", 14))
    except Exception:
        pass
