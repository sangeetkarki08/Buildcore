"""
BuildCore 2.3 - advanced analysis, built into Schedule & WBS and Cost & earned value:

  Schedule & WBS  linear (time-location) schedule with buffers (2.12), delay analysis and EOT with fragnets,
                  impacted as-planned, windows and as-planned vs as-built (2.14), crashing (2.10),
                  acceleration calculator (2.11), PERT and Monte Carlo (2.13), learning curve (2.15)
  Cost & EV       foreman delay survey Pareto (2B), profit centres with client quadrant (3.9),
                  close-out audit with norm feedback into company norm versions (3.5, 6.12)
"""
import json
import math
from datetime import date, timedelta

from core import ApiError, EPS, audit, get, ins, need, now, num, q, q1, r2, r4, setting, today, upd, val
import api_inventory as inv
from api_inventory import api as _register
import api_project as P
import api_sched as SCH
import sched_calc as SC

POSTED = "v.status IN ('posted','reversed')"
_READY = set()


def api(name, module=None, action=None):
    def wrap(f):
        def run(c, u, a):
            SCH.ensure(c)
            ensure(c)
            return f(c, u, a)
        run.__name__, run.__doc__ = f.__name__, f.__doc__
        _register(name, module, action)(run)
        return f
    return wrap


def ensure(c):
    try:
        key = c.execute("PRAGMA database_list").fetchone()[2] or id(c)
    except Exception:
        key = id(c)
    if key not in _READY:
        if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='boq_components'").fetchone() or \
                "component_id" not in {r[1] for r in c.execute("PRAGMA table_info(boq_items)")}:
            init_adv(c)
        _READY.add(key)


SCHEMA = """
CREATE TABLE IF NOT EXISTS boq_components(id INTEGER PRIMARY KEY, project_id INTEGER, code TEXT, name TEXT, kind TEXT,
  wbs_id INTEGER, sort INTEGER DEFAULT 0, remarks TEXT, active INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS closeout_lessons(id INTEGER PRIMARY KEY, project_id INTEGER, category TEXT, what TEXT, fix TEXT,
  owner TEXT, cost_code TEXT, date TEXT, user_id INTEGER);
CREATE TABLE IF NOT EXISTS closeout_reviews(id INTEGER PRIMARY KEY, project_id INTEGER UNIQUE, status TEXT DEFAULT 'open',
  summary TEXT, reviewed_by TEXT, date TEXT);
"""


def init_adv(c):
    c.executescript(SCHEMA)
    if "component_id" not in {r[1] for r in c.execute("PRAGMA table_info(boq_items)")}:
        c.execute("ALTER TABLE boq_items ADD COLUMN component_id INTEGER")


def _f(x, d=0.0):
    try:
        return float(x) if x not in (None, "") else d
    except (TypeError, ValueError):
        return d


def _o(s):
    return date.fromisoformat(s[:10]).toordinal()


def _cal(c, pid):
    cals = SCH.load_cals(c)
    p = get(c, "projects", pid, "Project")
    return cals["cals"].get(p.get("calendar_id") or cals["default"]) or SC.Calendar(), p


# ───────────────────────── 2.12 linear schedule ─────────────────────────
@api("adv.linear", "project", "view")
def linear(c, u, a):
    """Activities with a chainage range drawn as production lines (chainage against time). Planned
    lines use the CPM dates; actual points come from DPR work lines with chainage. Crews following
    each other on the same stretch are checked against the time and distance buffers."""
    pid = int(a["project_id"])
    tb = _f(a.get("time_buffer"), 5)
    db = _f(a.get("distance_buffer"), 50)
    acts = q(c, "SELECT * FROM activities WHERE project_id=? AND chainage_from IS NOT NULL AND chainage_to IS NOT NULL "
                "ORDER BY COALESCE(linear_order, 99), code", (pid,))
    lines = []
    for x in acts:
        s, f = x.get("es") or x.get("planned_start"), x.get("ef") or x.get("planned_finish")
        if not s or not f:
            continue
        pts = q(c, "SELECT d.date, w.chainage_from cf, w.chainage_to ct, w.actual_qty qq FROM dpr_work w JOIN dpr d ON d.id=w.dpr_id "
                   "WHERE w.activity_id=? AND d.status='approved' AND w.chainage_to IS NOT NULL ORDER BY d.date", (x["id"],))
        bl = (x.get("baseline_start"), x.get("baseline_finish"))
        rate = abs(x["chainage_to"] - x["chainage_from"]) / max(1, (_o(f) - _o(s) + 1))
        lines.append({"id": x["id"], "code": x["code"], "name": x["name"], "ch_from": x["chainage_from"], "ch_to": x["chainage_to"],
                      "start": s, "finish": f, "bl_start": bl[0], "bl_finish": bl[1], "order": x.get("linear_order") or 99,
                      "critical": x.get("critical"), "rate_per_day": r2(rate), "actual": pts})
    conf = SC.linear_conflicts([{"name": l["code"] or l["name"], "ch_from": l["ch_from"], "ch_to": l["ch_to"], "start": _o(l["start"]),
                                 "finish": _o(l["finish"]) + 1, "order": l["order"]} for l in lines], tb, db)
    # actual progress fronts: last chainage reached per activity vs where the plan says it should be today
    t = date.today().toordinal()
    for l in lines:
        reached = max([max(p["cf"] or 0, p["ct"] or 0) for p in l["actual"]] or [None]) if l["actual"] else None
        s, f = _o(l["start"]), _o(l["finish"]) + 1
        frac = min(1.0, max(0.0, (t - s) / max(1, f - s)))
        l["planned_front"] = r2(l["ch_from"] + (l["ch_to"] - l["ch_from"]) * frac)
        l["actual_front"] = reached
    return {"lines": lines, "conflicts": conf, "time_buffer": tb, "distance_buffer": db}


# ───────────────────────── 2.14 delay analysis and EOT ─────────────────────────
def _net(c, pid, use_progress):
    proj, acts, A, res, cd, notes, dd = SCH.build(c, pid, today(), use_progress=use_progress)
    return proj, acts, A, res, cd


def _codes(c, pid):
    return {x["code"]: x["id"] for x in q(c, "SELECT id, code FROM activities WHERE project_id=? AND code IS NOT NULL", (pid,))}


def _fragnet_items(c, pid, e):
    try:
        frag = json.loads(e.get("fragnet") or "[]")
    except ValueError:
        frag = []
    return frag


def _impacted(c, pid, events, use_progress=False):
    """Insert the events' fragnets into the network and return the finish (ordinal) before and after."""
    proj, acts, A, res, cd = _net(c, pid, use_progress)
    base_finish = res["finish"]
    links = [{"pred": l["pred_id"], "succ": l["succ_id"], "type": l["type"], "lag": l["lag"]}
             for l in q(c, "SELECT * FROM act_links WHERE project_id=?", (pid,))]
    codes = _codes(c, pid)
    cals = SCH.load_cals(c)
    calmap = {None: cals["cals"].get(proj.get("calendar_id") or cals["default"]) or SC.Calendar()}
    calmap.update(cals["cals"])
    A2 = [dict(x) for x in A]
    L2 = list(links)
    nid = -1
    for e in events:
        for fr in _fragnet_items(c, pid, e):
            aid = nid
            nid -= 1
            item = {"id": aid, "code": fr.get("code") or ("F%d" % -aid), "name": fr.get("name") or e["title"], "dur": _f(fr.get("dur"), 1)}
            if fr.get("start"):
                item["snet"] = fr["start"]
            elif e.get("date"):
                item["snet"] = e["date"]
            A2.append(item)
            for code, typ, lag in SC.parse_pred_text(fr.get("preds")):
                if code in codes:
                    L2.append({"pred": codes[code], "succ": aid, "type": typ, "lag": lag})
            for code, typ, lag in SC.parse_pred_text(fr.get("succs")):
                if code in codes:
                    L2.append({"pred": aid, "succ": codes[code], "type": typ, "lag": lag})
    start = res["start"]
    opts = {"start": date.fromordinal(start).isoformat(), "finish_target": None,
            "data_date": today() if use_progress else None}
    try:
        r2_ = SC.cpm(A2, L2, calmap, opts)
    except SC.ScheduleError as ex:
        raise ApiError("A fragnet makes a loop: %s" % ex)
    return base_finish, r2_["finish"], cd


@api("adv.fragnet_save", "commercial", "edit")
def fragnet_save(c, u, a):
    """Fragnet = the small network that models a delay event: its activities, durations and where they tie
    into the schedule (predecessor and successor activity codes)."""
    e = get(c, "events", int(a["id"]), "Event")
    items = []
    for x in a.get("items") or []:
        if not x.get("name") and not x.get("dur"):
            continue
        items.append({"code": x.get("code"), "name": x.get("name"), "dur": _f(x.get("dur"), 1), "start": x.get("start") or None,
                      "preds": x.get("preds") or "", "succs": x.get("succs") or ""})
    upd(c, "events", e["id"], {"fragnet": json.dumps(items)})
    audit(c, u, "fragnet", "events", e["id"], {"items": len(items)})
    return {"items": len(items)}


@api("adv.delay", "commercial", "view")
def delay_analysis(c, u, a):
    """Impacted as-planned (each event's fragnet alone and all excusable together), windows between
    schedule updates, and as-planned vs as-built for the critical activities. Ends in an EOT claim:
    excusable days (compensable ones with prolongation cost at the project's site overhead per day)."""
    pid = int(a["project_id"])
    evs = q(c, "SELECT * FROM events WHERE project_id=? AND status<>'rejected' ORDER BY date", (pid,))
    proj = get(c, "projects", pid)
    indirect = _f(proj.get("indirect_per_day"))
    per_event = []
    for e in evs:
        frag = _fragnet_items(c, pid, e)
        if not frag:
            per_event.append({"id": e["id"], "no": e["no"], "title": e["title"], "date": e["date"], "fragnet": 0, "impact_days": None,
                              "excusable": e.get("excusable"), "compensable": e.get("compensable"), "concurrent": e.get("concurrent"),
                              "claimed": e.get("eot_claimed"), "granted": e.get("eot_granted"), "activity_ids": e.get("activity_ids"),
                              "fragnet_json": e.get("fragnet")})
            continue
        b, f, _cd = _impacted(c, pid, [e])
        per_event.append({"id": e["id"], "no": e["no"], "title": e["title"], "date": e["date"], "fragnet": len(frag), "impact_days": f - b,
                          "excusable": e.get("excusable"), "compensable": e.get("compensable"), "concurrent": e.get("concurrent"),
                          "claimed": e.get("eot_claimed"), "granted": e.get("eot_granted"), "activity_ids": e.get("activity_ids"),
                              "fragnet_json": e.get("fragnet")})
    exc = [e for e in evs if e.get("excusable") == 1 and _fragnet_items(c, pid, e)]
    comp = [e for e in exc if e.get("compensable") and not e.get("concurrent")]
    tot_exc = tot_comp = 0
    base = None
    if exc:
        base, fin, _cd = _impacted(c, pid, exc)
        tot_exc = fin - base
    if comp:
        b2, fin2, _cd = _impacted(c, pid, comp)
        tot_comp = fin2 - b2
    # windows between updates
    runs = q(c, "SELECT * FROM sched_runs WHERE project_id=? ORDER BY id", (pid,))
    windows = []
    for r0, r1 in zip(runs, runs[1:]):
        if r0["data_date"] == r1["data_date"] and r0["finish"] == r1["finish"]:
            continue
        slip = (date.fromisoformat(r1["finish"]) - date.fromisoformat(r0["finish"])).days
        inw = [e for e in evs if r0["data_date"] <= (e["date"] or "") <= r1["data_date"]]
        exc_w = [e for e in inw if e.get("excusable") == 1]
        cause = "no events logged" if not inw else ("excusable" + (" (compensable)" if any(e.get("compensable") for e in exc_w) else "")
                                                     if exc_w and not any(e.get("concurrent") for e in exc_w) else
                                                     ("concurrent" if exc_w else "contractor"))
        windows.append({"from": r0["data_date"], "to": r1["data_date"], "finish_before": r0["finish"], "finish_after": r1["finish"],
                        "slip_days": slip, "events": ", ".join((e["no"] or "") for e in inw), "attributed_to": cause if slip > 0 else "—"})
    # as-planned vs as-built on the baseline-0 critical activities
    b0 = q1(c, "SELECT * FROM sched_baselines WHERE project_id=? ORDER BY no LIMIT 1", (pid,))
    apab = []
    if b0:
        for r in q(c, "SELECT b.*, a.code, a.name, a.actual_start, a.actual_finish, a.es, a.ef FROM sched_baseline_acts b JOIN activities a ON "
                      "a.id=b.activity_id WHERE b.baseline_id=? AND b.critical=1 ORDER BY b.start", (b0["id"],)):
            fin = r["actual_finish"] or r["ef"]
            apab.append({"code": r["code"], "name": r["name"], "planned_start": r["start"], "planned_finish": r["finish"],
                         "actual_start": r["actual_start"] or r["es"], "finish": fin, "done": bool(r["actual_finish"]),
                         "delay": (date.fromisoformat(fin) - date.fromisoformat(r["finish"])).days if fin and r["finish"] else None})
    cd = SCH.contract_dates(c, proj)
    last = runs[-1] if runs else None
    late = (date.fromisoformat(last["finish"]) - date.fromisoformat(cd["revised"])).days if last and cd.get("revised") else None
    claim_days = tot_exc
    return {"events": per_event, "excusable_days": tot_exc, "compensable_days": tot_comp, "windows": windows, "as_planned_as_built": apab,
            "claim": {"eot_days": claim_days, "compensable_days": tot_comp, "prolongation_cost": r2(tot_comp * indirect),
                      "indirect_per_day": indirect, "already_granted": cd["eot_events"], "forecast_late_days": late,
                      "ld_saved": r2(min(max(0, late or 0), claim_days) * _f(proj.get("ld_per_day")))},
            "note": "Impacted as-planned inserts each fragnet into the as-planned (no-progress) network; windows compare successive "
                    "updates and the events logged between them; concurrent excusable delay gives time but no money."}


# ───────────────────────── 2.10 crashing ─────────────────────────
@api("adv.crash", "project", "view")
def crash(c, u, a):
    """Least-cost duration for the remaining work: shorten the cheapest critical activity a day at a
    time (normal / crash duration and cost from each activity), adding the site overhead per day and LD."""
    pid = int(a["project_id"])
    cal, p = _cal(c, pid)
    dd = p.get("data_date") or today()
    base = cal.start_up(_o(dd))
    acts = q(c, "SELECT * FROM activities WHERE project_id=? AND actual_finish IS NULL AND es IS NOT NULL", (pid,))
    ids = {x["id"] for x in acts}
    if not acts:
        return {"empty": True, "note": "Press Calculate schedule first - this uses the calculated (CPM) dates of the remaining activities."}
    has_pred = {l["succ_id"] for l in q(c, "SELECT succ_id FROM act_links WHERE project_id=?", (pid,))}
    A = []
    for x in acts:
        s, f = max(_o(x["es"]), base), _o(x["ef"]) + 1
        dur = max(0, cal.wd(s, f))
        cd_ = x.get("crash_dur")
        A.append({"id": x["id"], "code": x["code"], "dur": dur,
                  "crash_dur": min(dur, max(0, int(round(dur * (cd_ / x["duration"]))))) if cd_ is not None and x.get("duration") else dur,
                  "cost": _f(x.get("normal_cost")), "crash_cost": _f(x.get("crash_cost"), _f(x.get("normal_cost"))),
                  "min_start": cal.wd(base, s) if (x.get("actual_start") or x["id"] not in has_pred) else 0})
    links = [{"pred": l["pred_id"], "succ": l["succ_id"], "type": l["type"], "lag": l["lag"]}
             for l in q(c, "SELECT * FROM act_links WHERE project_id=?", (pid,)) if l["pred_id"] in ids and l["succ_id"] in ids]
    cdates = SCH.contract_dates(c, p)
    target = cal.wd(base, _o(cdates["revised"]) + 1) if cdates.get("revised") else None
    indirect = _f(a.get("indirect_per_day"), _f(p.get("indirect_per_day")))
    ld = _f(a.get("ld_per_day"), _f(p.get("ld_per_day")))
    r = SC.crash(A, links, indirect * 7 / 6, ld * 7 / 6, target)
    for s in r["steps"]:
        s["finish"] = date.fromordinal(cal.advance(base, s["duration"]) - 1).isoformat() if s["duration"] else dd
    r["best"]["finish"] = date.fromordinal(cal.advance(base, r["best"]["duration"]) - 1).isoformat()
    r["crashable"] = sum(1 for x in A if x["crash_dur"] < x["dur"])
    r["contract_finish"] = cdates.get("revised")
    r["note"] = ("Give each activity a crash duration and costs (Activity › Cost, risk & linear) to see savings. "
                 "Costs per working day are converted from calendar days.") if not r["crashable"] else None
    return r


# ───────────────────────── 2.11 acceleration ─────────────────────────
@api("adv.accelerate", "project", "view")
def accelerate(c, u, a):
    p = get(c, "projects", int(a["project_id"])) if a.get("project_id") else {}
    x = dict(a)
    x.setdefault("ld_per_day", p.get("ld_per_day") or 0)
    x.setdefault("indirect_per_day", p.get("indirect_per_day") or 0)
    if not x.get("wage_hour"):
        x["wage_hour"] = val(c, "SELECT AVG(rate_hour) FROM trades WHERE active=1") or 100
    if x.get("activity_id") and not x.get("dur_days"):
        act = get(c, "activities", int(x["activity_id"]))
        x["dur_days"] = act.get("remaining_dur") or act.get("duration") or 20
        crew = val(c, "SELECT AVG(n) FROM (SELECT SUM(l.count) n FROM dpr_labour l JOIN dpr d ON d.id=l.dpr_id WHERE l.activity_id=? "
                      "GROUP BY d.id)", (act["id"],))
        x.setdefault("crew", round(crew) if crew else 10)
    return SC.acceleration(x)


# ───────────────────────── 2.13 PERT and Monte Carlo ─────────────────────────
@api("adv.risk", "project", "view")
def risk(c, u, a):
    """Three-point durations (optimistic, most likely, pessimistic on the activity; blank = the calculated
    duration with the default spread) through PERT on the critical path and a Monte Carlo run over the
    whole network, giving the chance of finishing by the contract date."""
    pid = int(a["project_id"])
    cal, p = _cal(c, pid)
    dd = p.get("data_date") or today()
    base = cal.start_up(_o(dd))
    lo, hi = _f(a.get("spread_low"), 10) / 100, _f(a.get("spread_high"), 30) / 100
    acts = q(c, "SELECT * FROM activities WHERE project_id=? AND actual_finish IS NULL AND es IS NOT NULL", (pid,))
    ids = {x["id"] for x in acts}
    if not acts:
        return {"empty": True, "note": "Press Calculate schedule first - this uses the calculated (CPM) dates of the remaining activities."}
    has_pred = {l["succ_id"] for l in q(c, "SELECT succ_id FROM act_links WHERE project_id=?", (pid,))}
    A = []
    names = {}
    for x in acts:
        s, f = max(_o(x["es"]), base), _o(x["ef"]) + 1
        dur = max(0.0, float(cal.wd(s, f)))
        scale = dur / x["duration"] if x.get("duration") else 1.0
        tm = _f(x.get("dur_likely"), None) * scale if x.get("dur_likely") is not None else dur
        to = _f(x.get("dur_opt"), None) * scale if x.get("dur_opt") is not None else tm * (1 - lo)
        tp = _f(x.get("dur_pess"), None) * scale if x.get("dur_pess") is not None else tm * (1 + hi)
        ms = cal.wd(base, s) if (x.get("actual_start") or x["id"] not in has_pred) else 0
        A.append({"id": x["id"], "to": to, "tm": tm, "tp": tp, "min_start": ms})
        names[x["id"]] = (x["code"] or "") + " " + x["name"]
    links = [{"pred": l["pred_id"], "succ": l["succ_id"], "type": l["type"], "lag": l["lag"]}
             for l in q(c, "SELECT * FROM act_links WHERE project_id=?", (pid,)) if l["pred_id"] in ids and l["succ_id"] in ids]
    # keep each unlinked activity's start by chaining it behind a zero-length start milestone with a lag
    A2 = [{"id": 0, "to": 0, "tm": 0, "tp": 0}]
    L2 = list(links)
    for x in A:
        A2.append({"id": x["id"], "to": x["to"], "tm": x["tm"], "tp": x["tp"]})
        if x["min_start"]:
            L2.append({"pred": 0, "succ": x["id"], "type": "SS", "lag": x["min_start"]})
    cd = SCH.contract_dates(c, p)
    target = cal.wd(base, _o(cd["revised"]) + 1) if cd.get("revised") else None
    pr = SC.pert_network(A2, L2, target)
    mc = SC.monte_carlo(A2, L2, int(_f(a.get("runs"), 1000)), target, seed=int(_f(a.get("seed"), 1)))
    to_date = lambda n: date.fromordinal(cal.advance(base, int(math.ceil(n))) - 1).isoformat() if n and n > 0 else dd
    crit = sorted([{"activity": names.get(k), "index": round(100 * v, 1)} for k, v in mc["criticality"].items() if k and v > 0.05],
                  key=lambda x: -x["index"])[:25]
    return {"contract_finish": cd.get("revised"), "pert": {"expected": to_date(pr["expected"]), "sigma_days": round(pr["sigma"], 1),
                                                            "probability": round(100 * pr["probability"], 1) if pr["probability"] is not None else None},
            "monte_carlo": {"runs": mc["runs"], "mean": to_date(mc["mean"]), "p10": to_date(mc["p10"]), "p50": to_date(mc["p50"]),
                            "p80": to_date(mc["p80"]), "p90": to_date(mc["p90"]),
                            "probability": round(100 * mc["probability"], 1) if mc["probability"] is not None else None,
                            "histogram": [{"finish": to_date(k), "runs": v} for k, v in mc["histogram"]]},
            "criticality": crit,
            "note": "Blank three-point estimates use %d%% shorter and %d%% longer than the calculated duration. PERT looks only at the "
                    "critical path; Monte Carlo also catches near-critical paths." % (lo * 100, hi * 100)}


# ───────────────────────── 2.15 learning curve ─────────────────────────
@api("adv.learning", "project", "view")
def learning(c, u, a):
    """Unit time from the DPRs (worker-hours per unit on each day, against the cumulative units done),
    fitted to T_N = T_1 x N^s. Forecasts the remaining units and prices the learning lost after a stoppage."""
    act = get(c, "activities", int(a["activity_id"]), "Activity")
    days = q(c, "SELECT d.id, d.date, SUM(w.actual_qty) qq FROM dpr_work w JOIN dpr d ON d.id=w.dpr_id WHERE w.activity_id=? AND "
                "d.status='approved' AND w.actual_qty>0 GROUP BY d.id ORDER BY d.date", (act["id"],))
    pts = []
    cum = 0.0
    for d in days:
        mh = val(c, "SELECT SUM(count*(hours+COALESCE(ot_hours,0))) FROM dpr_labour WHERE dpr_id=? AND activity_id=?", (d["id"], act["id"]))
        if not mh or not d["qq"]:
            cum += d["qq"] or 0
            continue
        mid = cum + d["qq"] / 2
        cum += d["qq"]
        pts.append({"date": d["date"], "units": r4(d["qq"]), "cum": r4(cum), "unit_time": r4(mh / d["qq"]), "n": mid})
    if len(pts) < 3:
        return {"points": pts, "note": "Needs at least three DPR days with quantity and labour on this activity."}
    xs = [math.log(max(p["n"], 0.5)) for p in pts]
    ys = [math.log(p["unit_time"]) for p in pts]
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    s = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx if sxx else 0.0
    t1 = math.exp(my - s * mx)
    rate = 2 ** s
    remaining = max((act["planned_qty"] or 0) - cum, 0)
    fc = [t1 * (cum + k + 0.5) ** s for k in range(int(math.ceil(remaining)))] if remaining < 50000 else []
    rem_hours = sum(fc) if fc else (t1 * (cum + remaining / 2) ** s * remaining)
    lost = None
    gap = _f(a.get("units_lost"))
    if gap > 0 and remaining > 0:
        restart = max(1.0, cum - gap)
        after = sum(t1 * (restart + k + 0.5) ** s for k in range(int(math.ceil(remaining)))) if remaining < 50000 else rem_hours
        rate_h = _f(a.get("rate_hour"), val(c, "SELECT AVG(rate_hour) FROM trades WHERE active=1") or 100)
        lost = {"extra_hours": r2(after - rem_hours), "extra_cost": r2((after - rem_hours) * rate_h), "rate_hour": rate_h}
    return {"activity": {"code": act["code"], "name": act["name"], "unit": act["unit"], "planned_qty": act["planned_qty"]},
            "points": pts, "t1": r4(t1), "learning_rate": round(100 * rate, 1), "slope": round(s, 4), "done": r4(cum),
            "remaining": r4(remaining), "remaining_hours": r2(rem_hours),
            "next_unit_time": r4(t1 * (cum + 1) ** s), "lost_learning": lost,
            "fitted": [{"n": p["cum"], "fit": r4(t1 * p["n"] ** s)} for p in pts]}


# ───────────────────────── 2B delay survey ─────────────────────────
SURVEY_LABELS = {"materials": "Waiting for materials", "tools": "Waiting for tools", "design_rework": "Rework from design errors",
                 "field_rework": "Rework from field errors", "instructions": "Waiting for instructions", "inspection": "Waiting for inspection",
                 "area_not_ready": "Work area not ready", "overcrowded": "Work area overcrowded", "equipment_wait": "Waiting for equipment",
                 "breakdown": "Equipment breakdown", "owner_change": "Owner change", "interference": "Interference from another crew"}


@api("adv.survey", "project", "view")
def survey(c, u, a):
    """Foreman delay survey (Hinze ch. 11): worker-hours lost by cause, crew and area, costed at the
    burdened trade rate; Pareto and weekly trend. Evidence for claims when the cause is the employer's."""
    pid = int(a["project_id"])
    frm = a.get("from") or "0000-01-01"
    to = a.get("to") or today()
    rows = q(c, "SELECT s.*, d.date, t.name trade, COALESCE(t.rate_hour, (SELECT AVG(rate_hour) FROM trades)) rate FROM dpr_survey s JOIN dpr d "
                "ON d.id=s.dpr_id LEFT JOIN trades t ON t.id=s.trade_id WHERE d.project_id=? AND d.date BETWEEN ? AND ?", (pid, frm, to))
    tot_h = sum((r["workers"] or 0) * (r["hours"] or 0) for r in rows)
    worked = val(c, "SELECT SUM(l.count*(l.hours+COALESCE(l.ot_hours,0))) FROM dpr_labour l JOIN dpr d ON d.id=l.dpr_id WHERE "
                    "d.project_id=? AND d.date BETWEEN ? AND ?", (pid, frm, to))

    def group(key, label=None):
        g = {}
        for r in rows:
            k = r[key] or "—"
            x = g.setdefault(k, {"key": label(k) if label else k, "hours": 0.0, "cost": 0.0, "records": 0})
            h_ = (r["workers"] or 0) * (r["hours"] or 0)
            x["hours"] += h_
            x["cost"] += h_ * (r["rate"] or 0)
            x["records"] += 1
        out = sorted(g.values(), key=lambda x: -x["hours"])
        acc = 0.0
        for x in out:
            acc += x["hours"]
            x["hours"] = r2(x["hours"])
            x["cost"] = r2(x["cost"])
            x["pct"] = round(100 * x["hours"] / tot_h, 1) if tot_h else 0
            x["cum_pct"] = round(100 * acc / tot_h, 1) if tot_h else 0
        return out
    weeks = {}
    for r in rows:
        dd_ = date.fromisoformat(r["date"])
        wk = (dd_ - timedelta(days=(dd_.weekday() + 1) % 7)).isoformat()
        weeks[wk] = weeks.get(wk, 0) + (r["workers"] or 0) * (r["hours"] or 0)
    employer = {"design_rework", "instructions", "owner_change", "inspection"}
    return {"total_hours": r2(tot_h), "worked_hours": r2(worked), "lost_pct": round(100 * tot_h / (worked + tot_h), 1) if worked + tot_h else None,
            "total_cost": r2(sum((r["workers"] or 0) * (r["hours"] or 0) * (r["rate"] or 0) for r in rows)),
            "employer_hours": r2(sum((r["workers"] or 0) * (r["hours"] or 0) for r in rows if r["cause"] in employer)),
            "by_cause": group("cause", lambda k: SURVEY_LABELS.get(k, k)), "by_crew": group("trade"), "by_area": group("area"),
            "weeks": [{"week": k, "hours": r2(v)} for k, v in sorted(weeks.items())], "records": len(rows),
            "note": "Run the survey for one to three weeks, act on the top causes, and repeat after about six months. Causes 3, 5, 6 and 11 "
                    "(design rework, instructions, inspection, owner change) are usually the employer's risk and support a claim."}


# ───────────────────────── 3.9 profit centres ─────────────────────────
@api("adv.profit", "commercial", "view")
def profit_centres(c, u, a):
    """Where the profit came from on each project: (a) markup in the estimate, (b) buy-out savings on
    purchases against the budget rates, (c) crew productivity against the estimate, (d) equipment
    recovery against its cost. Grouped by project type, PM and client, with head-office overhead
    allocated four ways and the client quadrant (profit against management time)."""
    method = a.get("alloc") or "revenue"
    import api_equipment_reports as ER
    fy_from = a.get("from") or (date.today() - timedelta(days=365)).isoformat()
    to = a.get("to") or today()
    oh = val(c, "SELECT SUM(l.debit-l.credit) FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id JOIN accounts x ON x.id=l.account_id "
                "WHERE x.type='expense' AND l.project_id IS NULL AND v.date BETWEEN ? AND ? AND " + POSTED, (fy_from, to))
    rows = []
    for p in q(c, "SELECT * FROM projects ORDER BY code"):
        try:
            ev = P.project_evm(c, p["id"], to)
        except Exception:
            continue
        if not ev["earned_revenue"] and not ev["ac"]:
            continue
        rev = ev["earned_revenue"]
        # (a) estimate markup on the work done
        est_cost = sum((r["executed_qty"] or 0) * (r["unit_budget"] or 0) for r in ev["rows"] if r["unit_budget"] is not None)
        markup = rev - est_cost
        # (b) buy-out: PO rates against the budgeted material rate (rate analysis material lines are lumped, so use standard rates)
        buy = val(c, "SELECT SUM((m.standard_rate-pl.rate)*MIN(pl.received_qty,pl.qty)) FROM po_lines pl JOIN po ON po.id=pl.po_id JOIN materials m "
                     "ON m.id=pl.material_id WHERE po.project_id=? AND m.standard_rate>0 AND po.status IN ('approved','partially_received','received','closed')",
                  (p["id"],))
        # (c) labour: budgeted labour cost of work done minus actual labour cost
        lab_b = 0.0
        for r in ev["rows"]:
            lb = q(c, "SELECT SUM(qty_per_unit*rate) v FROM rate_analysis WHERE boq_item_id=? AND kind='labour'", (r["id"],))
            if lb and lb[0]["v"]:
                lab_b += (r["executed_qty"] or 0) * lb[0]["v"]
        lab_a = val(c, "SELECT SUM(l.debit-l.credit) FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id JOIN accounts x ON x.id=l.account_id "
                       "WHERE x.role='labour_cost' AND l.project_id=? AND v.date<=? AND " + POSTED, (p["id"], to))
        # (d) equipment: recovery charged to the job minus the machines' own cost
        rec = val(c, "SELECT SUM(l.credit-l.debit) FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id JOIN accounts x ON x.id=l.account_id "
                     "WHERE x.role='equipment_recovery' AND l.project_id=? AND v.date<=? AND " + POSTED, (p["id"], to))
        eq_cost = val(c, "SELECT SUM(l.debit-l.credit) FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id JOIN accounts x ON x.id=l.account_id "
                         "WHERE x.role IN ('fuel_cost','repair_cost','depreciation','hire_cost') AND l.project_id=? AND v.date<=? AND " + POSTED,
                      (p["id"], to))
        gross = rev - ev["ac"]
        rows.append({"id": p["id"], "code": p["code"], "name": p["name"], "client": p["client"], "type": p.get("project_type") or "—",
                     "pm": p.get("pm_name") or "—", "revenue": r2(rev), "cost": r2(ev["ac"]), "gross": r2(gross),
                     "from_markup": r2(markup), "from_buyout": r2(buy), "from_labour": r2(lab_b - lab_a), "from_equipment": r2(rec - eq_cost),
                     "direct_labour": r2(lab_a), "months": max(1, (date.fromisoformat(to) - date.fromisoformat(p["start_date"] or to)).days / 30.4),
                     "mgmt_hours": _f(p.get("mgmt_hours"))})
    basis = {"revenue": "revenue", "cost": "cost", "labour": "direct_labour", "time": "months"}[method if method in ("revenue", "cost", "labour", "time") else "revenue"]
    tot = sum(r[basis] for r in rows) or 1
    for r in rows:
        r["overhead"] = r2(oh * r[basis] / tot)
        r["net"] = r2(r["gross"] - r["overhead"])
        r["margin_pct"] = round(100 * r["net"] / r["revenue"], 1) if r["revenue"] else None

    def grp(k):
        g = {}
        for r in rows:
            x = g.setdefault(r[k] or "—", {"key": r[k] or "—", "revenue": 0.0, "gross": 0.0, "net": 0.0, "mgmt_hours": 0.0, "projects": 0})
            for f in ("revenue", "gross", "net", "mgmt_hours"):
                x[f] += r[f]
            x["projects"] += 1
        out = list(g.values())
        for x in out:
            x["margin_pct"] = round(100 * x["net"] / x["revenue"], 1) if x["revenue"] else None
            x["profit_per_mgmt_hour"] = r2(x["net"] / x["mgmt_hours"]) if x["mgmt_hours"] else None
            for f in ("revenue", "gross", "net"):
                x[f] = r2(x[f])
        return sorted(out, key=lambda x: -x["net"])
    clients = grp("client")
    avg_p = sum(x["net"] for x in clients) / len(clients) if clients else 0
    avg_h = sum(x["mgmt_hours"] for x in clients) / len(clients) if clients else 0
    for x in clients:
        hi_p = x["net"] >= avg_p
        hi_t = x["mgmt_hours"] > avg_h if avg_h else False
        x["quadrant"] = ("keep: profitable and easy" if hi_p and not hi_t else "profitable but demanding" if hi_p else
                         "high maintenance, low profit" if hi_t else "low profit, low effort")
    return {"rows": rows, "by_type": grp("type"), "by_pm": grp("pm"), "by_client": clients, "overhead": r2(oh), "alloc": method,
            "note": "Buy-out uses each material's standard rate as the budget rate. Enter management hours per project in the contract register "
                    "(IPC billing › Contract accounting) for the client quadrant."}


# ───────────────────────── 3.5 close-out audit and norm feedback ─────────────────────────
@api("adv.closeout", "commercial", "view")
def closeout(c, u, a):
    pid = int(a["project_id"])
    ev = P.project_evm(c, pid, today())
    items = []
    for r in ev["rows"]:
        if r["unit_budget"] is None and not r["ac"]:
            continue
        est = (r["executed_qty"] or 0) * (r["unit_budget"] or 0)
        items.append({"code": r["code"], "description": r["description"], "estimate": r2(est), "actual": r2(r["ac"]),
                      "variance": r2(est - r["ac"]), "variance_pct": round(100 * (r["ac"] - est) / est, 1) if est else None,
                      "unit_budget": r["unit_budget"], "actual_unit_cost": r["actual_unit_cost"]})
    prod = []
    norms = {n["code"]: n for n in q(c, "SELECT * FROM ra_norms")} if SCH._has(c, "ra_norms") else {}
    for x in q(c, "SELECT * FROM activities WHERE project_id=? ORDER BY code", (pid,)):
        m = P.activity_metrics(c, x, today())
        if not m.get("labour_prod"):
            continue
        norm_code = x.get("norm_code")
        if not norm_code and x.get("boq_item_id") and SCH._has(c, "ra_analyses"):
            nr = q1(c, "SELECT n.code FROM ra_analyses r JOIN ra_norms n ON n.id=r.norm_id WHERE r.boq_item_id=? ORDER BY r.id DESC LIMIT 1",
                    (x["boq_item_id"],))
            norm_code = (nr or {}).get("code")
        norm_md = None
        if norm_code and norm_code in norms:
            n = norms[norm_code]
            ls = val(c, "SELECT SUM(qty) FROM ra_norm_lines WHERE norm_id=? AND kind='L'", (n["id"],))
            if ls:
                norm_md = ls / (n["per_qty"] or 1)
        actual_md = (1 / m["labour_prod"]) / 8.0 if m["labour_prod"] else None
        prod.append({"id": x["id"], "code": x["code"], "name": x["name"], "unit": x["unit"], "done": m["actual_qty"],
                     "output_per_mh": m["labour_prod"], "std_output_per_mh": x.get("std_labour_prod") or None,
                     "vs_std_pct": m.get("labour_prod_var"), "norm_code": norm_code, "norm_md_per_unit": r4(norm_md) if norm_md else None,
                     "actual_md_per_unit": r4(actual_md) if actual_md else None,
                     "factor": round(actual_md / norm_md, 3) if norm_md and actual_md else None})
    lessons = q(c, "SELECT * FROM closeout_lessons WHERE project_id=? ORDER BY id", (pid,))
    rev = q1(c, "SELECT * FROM closeout_reviews WHERE project_id=?", (pid,))
    return {"cost_codes": items, "productivity": prod, "lessons": lessons, "review": rev,
            "totals": {"estimate": r2(sum(i["estimate"] for i in items)), "actual": r2(sum(i["actual"] for i in items))},
            "note": "Fix the problem, not the blame. Productivity below the norm can become the company's own norm version; published "
                    "DoR / DUDBC norms stay locked."}


@api("adv.lesson_save", "commercial", "edit")
def lesson_save(c, u, a):
    r = a.get("row") or {}
    need(r, "project_id", "what")
    data = {"project_id": int(r["project_id"]), "category": r.get("category"), "what": r["what"], "fix": r.get("fix"), "owner": r.get("owner"),
            "cost_code": r.get("cost_code"), "date": r.get("date") or today(), "user_id": u["id"]}
    if r.get("id"):
        upd(c, "closeout_lessons", int(r["id"]), data)
        return {"id": int(r["id"])}
    return {"id": ins(c, "closeout_lessons", data)}


@api("adv.closeout_sign", "commercial", "approve")
def closeout_sign(c, u, a):
    pid = int(a["project_id"])
    ex = q1(c, "SELECT id FROM closeout_reviews WHERE project_id=?", (pid,))
    data = {"project_id": pid, "status": a.get("status") or "closed", "summary": a.get("summary"), "reviewed_by": u.get("name"), "date": today()}
    if ex:
        upd(c, "closeout_reviews", ex["id"], data)
    else:
        ins(c, "closeout_reviews", data)
    return True


@api("adv.norm_feedback", "masters", "edit")
def norm_feedback(c, u, a):
    """Make a company norm version from what the site achieved: copy the norm and scale its labour lines
    by the achieved / norm man-days per unit. The published norm is left untouched."""
    code = a.get("norm_code")
    factor = _f(a.get("factor"))
    if not code or factor <= 0:
        raise ApiError("Choose a norm and a factor.")
    if "rnorm.copy" not in inv.FUNCS:
        raise ApiError("The norms library (1.8) is not installed.")
    src = q1(c, "SELECT * FROM ra_norms WHERE code=?", (code,))
    if not src:
        raise ApiError("Norm %s not found." % code)
    r = inv.FUNCS["rnorm.copy"][0](c, u, {"id": src["id"], "new_code": a.get("new_code") or ("CO-%s-%s" % (code, date.today().year))})
    c.execute("UPDATE ra_norm_lines SET qty=ROUND(qty*?,4), note=COALESCE(note,'')||? WHERE norm_id=? AND kind='L'",
              (factor, " (x%.3f from site records)" % factor, r["id"]))
    c.execute("UPDATE ra_norms SET derivation=COALESCE(derivation,'')||?, source='Company (site records)' WHERE id=?",
              (" Labour scaled x%.3f from %s." % (factor, a.get("basis") or "DPR productivity"), r["id"]))
    audit(c, u, "norm_feedback", "ra_norms", r["id"], {"from": code, "factor": factor})
    return r


# ═════════════════════════ COMPONENT-WISE BOQ AND MONITORING (hydropower) ═════════════════════════
# A hydropower contract is priced and watched by component (bill): headworks, headrace, surge tank, penstock,
# powerhouse, tailrace ... Every BOQ item belongs to one component; quantities, value, progress, billing, cost,
# earned value and schedule roll up by component.
HYDRO_COMPONENTS = [
    ("1", "General items & preliminaries", "general", ("prelim", "general")),
    ("2", "Headworks (weir, intake, undersluice, gravel trap)", "headworks", ("headwork", "weir", "intake", "diversion", "gravel trap")),
    ("3", "Desander / settling basin", "desander", ("desand", "settling", "basin")),
    ("4", "Headrace (canal, pipe or tunnel)", "headrace", ("headrace", "tunnel", "canal", "adit")),
    ("5", "Forebay / surge tank", "surge", ("forebay", "surge")),
    ("6", "Penstock (anchor blocks, saddles, pipe)", "penstock", ("penstock", "anchor")),
    ("7", "Powerhouse", "powerhouse", ("powerhouse", "power house")),
    ("8", "Tailrace", "tailrace", ("tailrace", "tail race")),
    ("9", "Hydro-mechanical works", "hm", ("hydromechanical", "hydro-mechanical", "hydro mechanical", "gate")),
    ("10", "Electro-mechanical works", "em", ("electromechanical", "electro-mechanical", "electro mechanical", "turbine")),
    ("11", "Switchyard", "switchyard", ("switchyard",)),
    ("12", "Transmission line", "tl", ("transmission",)),
    ("13", "Access road, bridges & camp", "access", ("access", "road", "bridge", "camp")),
    ("14", "Environmental & social", "env", ("environment", "social", "resettlement")),
]


def _comp_ready(c):
    ensure(c)


def _wbs_root(c, pid):
    """{wbs_id: top-level wbs_id} for the project."""
    rows = {r["id"]: r for r in q(c, "SELECT id, parent_id FROM wbs WHERE project_id=?", (pid,))}
    out = {}
    for i in rows:
        j, n = i, 0
        while rows.get(j) and rows[j]["parent_id"] and n < 30:
            j, n = rows[j]["parent_id"], n + 1
        out[i] = j
    return out


def _comp_of_items(c, pid):
    """{boq_item_id: component_id} - the item's own component, else through its WBS, else its bill number."""
    comps = q(c, "SELECT * FROM boq_components WHERE project_id=? AND active=1", (pid,))
    by_wbs = {x["wbs_id"]: x["id"] for x in comps if x["wbs_id"]}
    by_code = {str(x["code"]).strip().lower(): x["id"] for x in comps if x["code"]}
    root = _wbs_root(c, pid)
    out = {}
    for b in q(c, "SELECT id, code, wbs_id, component_id FROM boq_items WHERE project_id=?", (pid,)):
        cid = b["component_id"]
        if not cid and b["wbs_id"]:
            cid = by_wbs.get(b["wbs_id"]) or by_wbs.get(root.get(b["wbs_id"]))
        if not cid and b["code"]:
            cid = by_code.get(str(b["code"]).split(".")[0].split("-")[0].strip().lower())
        out[b["id"]] = cid
    return out


@api("comp.list", "commercial", "view")
def comp_list(c, u, a):
    pid = int(a["project_id"])
    rows = q(c, "SELECT * FROM boq_components WHERE project_id=? AND active=1 ORDER BY sort, CAST(code AS INTEGER), code", (pid,))
    m = _comp_of_items(c, pid)
    for r in rows:
        r["items"] = sum(1 for v in m.values() if v == r["id"])
        r["wbs"] = (q1(c, "SELECT code, name FROM wbs WHERE id=?", (r["wbs_id"],)) or {}) if r["wbs_id"] else {}
    unassigned = sum(1 for v in m.values() if not v)
    return {"rows": rows, "unassigned": unassigned, "template": [{"code": x[0], "name": x[1]} for x in HYDRO_COMPONENTS]}


@api("comp.save", "commercial", "edit")
def comp_save(c, u, a):
    r = a.get("row") or {}
    need(r, "project_id", "name")
    data = {"project_id": int(r["project_id"]), "code": (r.get("code") or "").strip(), "name": r["name"].strip(), "kind": r.get("kind"),
            "wbs_id": int(r["wbs_id"]) if r.get("wbs_id") else None, "sort": int(_f(r.get("sort"), 0)), "remarks": r.get("remarks"), "active": 1}
    dup = q1(c, "SELECT id FROM boq_components WHERE project_id=? AND active=1 AND lower(code)=lower(?) AND id<>?", (data["project_id"], data["code"], int(r.get("id") or 0)))
    if data["code"] and dup:
        raise ApiError("Component code %s is already used in this project." % data["code"])
    if r.get("id"):
        upd(c, "boq_components", int(r["id"]), data)
        return {"id": int(r["id"])}
    return {"id": ins(c, "boq_components", data)}


@api("comp.delete", "commercial", "edit")
def comp_delete(c, u, a):
    cid = int(a["id"])
    c.execute("UPDATE boq_items SET component_id=NULL WHERE component_id=?", (cid,))
    c.execute("UPDATE boq_components SET active=0 WHERE id=?", (cid,))
    return True


@api("comp.setup", "commercial", "edit")
def comp_setup(c, u, a):
    """from='wbs': one component per top-level WBS element. from='hydro': the standard hydropower bills, each
    linked to the top-level WBS element whose name matches. Existing components are kept."""
    pid = int(a["project_id"])
    have = {str(x["code"]).lower(): x for x in q(c, "SELECT * FROM boq_components WHERE project_id=? AND active=1", (pid,))}
    have_wbs = {x["wbs_id"] for x in have.values() if x["wbs_id"]}
    tops = q(c, "SELECT * FROM wbs WHERE project_id=? AND parent_id IS NULL ORDER BY CAST(code AS INTEGER), code", (pid,))
    made = 0
    if a.get("source") == "wbs":
        for i, w in enumerate(tops):
            if w["id"] in have_wbs or str(w["code"]).lower() in have:
                continue
            ins(c, "boq_components", {"project_id": pid, "code": w["code"], "name": w["name"], "wbs_id": w["id"], "sort": i, "active": 1})
            made += 1
    else:
        used = set(have_wbs)
        for i, (code, name, kind, words) in enumerate(HYDRO_COMPONENTS):
            if code.lower() in have:
                continue
            w = next((t for t in tops if t["id"] not in used and any(k in (t["name"] or "").lower() for k in words)), None)
            if w:
                used.add(w["id"])
            ins(c, "boq_components", {"project_id": pid, "code": code, "name": name, "kind": kind, "wbs_id": w["id"] if w else None, "sort": i, "active": 1})
            made += 1
    res = comp_assign(c, u, {"project_id": pid})
    return {"created": made, "assigned": res["assigned"]}


@api("comp.assign", "commercial", "edit")
def comp_assign(c, u, a):
    """Write the component on every BOQ item that has none, from its WBS or bill number; with items={id: cid}
    set them by hand."""
    pid = int(a["project_id"])
    n = 0
    if a.get("items"):
        ok = {x["id"] for x in q(c, "SELECT id FROM boq_components WHERE project_id=? AND active=1", (pid,))}
        for bid, cid in a["items"].items():
            cid = int(cid) if cid else None
            if cid and cid not in ok:
                raise ApiError("Unknown component.")
            c.execute("UPDATE boq_items SET component_id=? WHERE id=? AND project_id=?", (cid, int(bid), pid))
            n += 1
        return {"assigned": n}
    for bid, cid in _comp_of_items(c, pid).items():
        if cid and not val(c, "SELECT component_id FROM boq_items WHERE id=?", (bid,), None):
            c.execute("UPDATE boq_items SET component_id=? WHERE id=?", (cid, bid))
            n += 1
    return {"assigned": n}


@api("comp.items", "commercial", "view")
def comp_items(c, u, a):
    pid = int(a["project_id"])
    m = _comp_of_items(c, pid)
    rows = q(c, "SELECT id, code, description, unit, qty, rate, wbs_id, component_id FROM boq_items WHERE project_id=? ORDER BY code", (pid,))
    for r in rows:
        r["effective_component_id"] = m.get(r["id"])
        r["amount"] = r2((r["qty"] or 0) * (r["rate"] or 0))
    return rows


@api("comp.summary", "commercial", "view")
def comp_summary(c, u, a):
    """Per component: contract and revised value, work done, progress against plan, measured, billed and certified,
    budget, earned value, actual cost, CPI / SPI, forecast cost and margin, dates, and open issues."""
    pid = int(a["project_id"])
    asof = a.get("as_of") or today()
    comps = {x["id"]: x for x in q(c, "SELECT * FROM boq_components WHERE project_id=? AND active=1", (pid,))}
    m = _comp_of_items(c, pid)
    boqs = {b["id"]: b for b in q(c, "SELECT * FROM boq_items WHERE project_id=?", (pid,))}
    agg = {}

    def blank(cid):
        x = comps.get(cid) or {}
        return {"id": cid, "code": x.get("code") or "", "name": x.get("name") or "Not assigned to a component", "sort": x.get("sort") if cid else 9999,
                "items": 0, "contract_amount": 0.0, "revised_amount": 0.0, "done_value": 0.0, "planned_value_rev": 0.0, "measured_value": 0.0,
                "billed_value": 0.0, "certified_value": 0.0, "bac": 0.0, "ev": 0.0, "pv": 0.0, "ac": 0.0, "eac": 0.0, "forecast_revenue": 0.0,
                "activity_ids": set()}
    for bid, b in boqs.items():
        f = P.boq_figures(c, b, asof)
        cid = m.get(bid)
        x = agg.setdefault(cid, blank(cid))
        rate = f["revised_rate"] or 0
        x["items"] += 1
        x["contract_amount"] += f["contract_amount"]
        x["revised_amount"] += f["revised_amount"]
        x["done_value"] += f["earned_revenue"]
        x["measured_value"] += (f["measured_qty"] or 0) * rate
        x["billed_value"] += (f["billed_qty"] or 0) * rate
        x["certified_value"] += (f["certified_qty"] or 0) * rate
        for k in ("bac", "ev", "pv"):
            x[k] += f[k] or 0
        x["ac"] += f["ac"]
        x["eac"] += f["eac"]
        x["forecast_revenue"] += f["forecast_revenue"]
        x["no_forecast_revenue"] = x.get("no_forecast_revenue", 0.0) + (f.get("no_forecast_revenue") or 0)
        for act in q(c, "SELECT * FROM activities WHERE boq_item_id=?", (bid,)):
            x["planned_value_rev"] += (act["planned_qty"] or 0) * P.planned_fraction(act, asof) * rate
            x["activity_ids"].add(act["id"])
    # activities without a BOQ item still belong to the component through their WBS (dates, issues)
    root = _wbs_root(c, pid)
    by_wbs = {x["wbs_id"]: k for k, x in comps.items() if x["wbs_id"]}
    for act in q(c, "SELECT id, wbs_id FROM activities WHERE project_id=? AND boq_item_id IS NULL", (pid,)):
        cid = by_wbs.get(act["wbs_id"]) or by_wbs.get(root.get(act["wbs_id"]))
        if cid:
            agg.setdefault(cid, blank(cid))["activity_ids"].add(act["id"])
    for cid in comps:
        agg.setdefault(cid, blank(cid))
    tot_rev = sum(x["revised_amount"] for x in agg.values()) or 1
    rows = []
    for x in agg.values():
        ids = list(x.pop("activity_ids"))
        ph = ",".join("?" * len(ids)) if ids else "0"
        d = q1(c, "SELECT MIN(COALESCE(baseline_start, planned_start)) bs, MAX(COALESCE(baseline_finish, planned_finish)) bf, MIN(COALESCE(actual_start, es, planned_start)) fs, "
                  "MAX(COALESCE(actual_finish, ef, planned_finish)) ff, SUM(CASE WHEN critical=1 AND actual_finish IS NULL THEN 1 ELSE 0 END) crit FROM activities WHERE id IN (%s)" % ph, ids) if ids else {}
        x["planned_start"], x["planned_finish"] = (d or {}).get("bs"), (d or {}).get("bf")
        x["forecast_start"], x["forecast_finish"] = (d or {}).get("fs"), (d or {}).get("ff")
        x["critical_open"] = (d or {}).get("crit") or 0
        x["late_days"] = (date.fromisoformat(x["forecast_finish"]) - date.fromisoformat(x["planned_finish"])).days if x["forecast_finish"] and x["planned_finish"] else None
        x["open_events"] = val(c, "SELECT COUNT(*) FROM events WHERE status NOT IN ('closed','rejected') AND activity_id IN (%s)" % ph, ids) if ids else 0
        x["open_ncrs"] = val(c, "SELECT COUNT(*) FROM ncrs WHERE status<>'closed' AND activity_id IN (%s)" % ph, ids) if ids else 0
        x["activities"] = len(ids)
        rv = x["revised_amount"]
        x["weight_pct"] = round(100 * rv / tot_rev, 2)
        x["progress_pct"] = round(100 * x["done_value"] / rv, 1) if rv else 0
        x["planned_pct"] = round(100 * x["planned_value_rev"] / rv, 1) if rv else 0
        x["progress_gap"] = round(x["progress_pct"] - x["planned_pct"], 1)
        x["weighted_progress"] = round(x["progress_pct"] * x["weight_pct"] / 100, 2)
        x["cpi"] = round(x["ev"] / x["ac"], 2) if x["ac"] > EPS and x["ev"] else None
        x["spi"] = round(x["ev"] / x["pv"], 2) if x["pv"] > EPS else None
        covered = x["forecast_revenue"] - x.get("no_forecast_revenue", 0.0)    # items with no cost forecast left out
        x["forecast_margin"] = r2(covered - x["eac"])
        x["forecast_margin_pct"] = round(100 * x["forecast_margin"] / covered, 1) if covered > EPS else None
        x["unbilled_done"] = r2(x["done_value"] - x["billed_value"])
        x["status"] = ("late" if (x["late_days"] or 0) > 0 or x["progress_gap"] < -5 else "on track") if rv else ""
        for k in ("contract_amount", "revised_amount", "done_value", "planned_value_rev", "measured_value", "billed_value", "certified_value",
                  "bac", "ev", "pv", "ac", "eac", "forecast_revenue"):
            x[k] = r2(x[k])
        rows.append(x)
    rows.sort(key=lambda r: (r["sort"] if r["sort"] is not None else 999, str(r["code"]).zfill(4)))
    rows = [r for r in rows if r["id"] or r["items"]]
    t = {k: r2(sum(r[k] for r in rows)) for k in ("contract_amount", "revised_amount", "done_value", "planned_value_rev", "measured_value", "billed_value",
                                                "certified_value", "bac", "ev", "pv", "ac", "eac", "forecast_revenue")}
    t["progress_pct"] = round(100 * t["done_value"] / t["revised_amount"], 1) if t["revised_amount"] else 0
    t["planned_pct"] = round(100 * t["planned_value_rev"] / t["revised_amount"], 1) if t["revised_amount"] else 0
    t["cpi"] = round(t["ev"] / t["ac"], 2) if t["ac"] > EPS and t["ev"] else None
    t["spi"] = round(t["ev"] / t["pv"], 2) if t["pv"] > EPS else None
    return {"rows": rows, "totals": t, "as_of": asof, "has_components": bool(comps),
            "note": "Progress = value of work done ÷ revised value of the component (quantities from approved DPRs × rate). Planned = the same from the "
                    "baseline dates. Weight = share of the contract. CPI / SPI use the rate-analysis budget."}


@api("comp.curve", "commercial", "view")
def comp_curve(c, u, a):
    """Monthly cumulative progress % (value) per component, planned and actual."""
    pid = int(a["project_id"])
    m = _comp_of_items(c, pid)
    comps = {x["id"]: x for x in q(c, "SELECT * FROM boq_components WHERE project_id=? AND active=1", (pid,))}
    boqs = {b["id"]: b for b in q(c, "SELECT * FROM boq_items WHERE project_id=?", (pid,))}
    rate = {k: (b["revised_rate"] if b.get("revised_rate") is not None else b["rate"]) or 0 for k, b in boqs.items()}
    rv = {}
    for k, b in boqs.items():
        rq = b["revised_qty"] if b.get("revised_qty") is not None else b["qty"]
        rv[m.get(k)] = rv.get(m.get(k), 0) + (rq or 0) * rate[k]
    acts = q(c, "SELECT * FROM activities WHERE project_id=? AND boq_item_id IS NOT NULL", (pid,))
    dates = [x.get("baseline_start") or x.get("planned_start") for x in acts if x.get("baseline_start") or x.get("planned_start")]
    ends = [x.get("baseline_finish") or x.get("planned_finish") for x in acts if x.get("baseline_finish") or x.get("planned_finish")]
    if not dates:
        return {"months": [], "series": []}
    y, mo = int(min(dates)[:4]), int(min(dates)[5:7])
    last = max(max(ends)[:7], today()[:7])
    months = []
    while True:
        k = "%04d-%02d" % (y, mo)
        months.append(k)
        if k >= last or len(months) > 120:
            break
        mo += 1
        if mo > 12:
            y, mo = y + 1, 1
    done = {}
    for r in q(c, "SELECT w.boq_item_id, substr(d.date,1,7) mth, SUM(w.actual_qty) qq FROM dpr_work w JOIN dpr d ON d.id=w.dpr_id WHERE d.status='approved' "
                  "AND d.project_id=? AND w.boq_item_id IS NOT NULL GROUP BY w.boq_item_id, mth", (pid,)):
        cid = m.get(r["boq_item_id"])
        done.setdefault(cid, {}).setdefault(r["mth"], 0)
        done[cid][r["mth"]] += (r["qq"] or 0) * rate.get(r["boq_item_id"], 0)
    series = []
    for cid in [k for k in sorted(comps, key=lambda k: (comps[k]["sort"] or 0, str(comps[k]["code"]).zfill(4)))] + ([None] if None in rv else []):
        tot = rv.get(cid) or 0
        if not tot:
            continue
        plan, act, cum = [], [], 0.0
        for k in months:
            me = (date(int(k[:4]) + int(k[5:]) // 12, int(k[5:]) % 12 + 1, 1) - timedelta(days=1)).isoformat()
            pv = sum((x["planned_qty"] or 0) * P.planned_fraction(x, me) * rate.get(x["boq_item_id"], 0) for x in acts if m.get(x["boq_item_id"]) == cid)
            plan.append(round(100 * pv / tot, 1))
            cum += (done.get(cid) or {}).get(k, 0)
            act.append(round(100 * cum / tot, 1) if k <= today()[:7] else None)
        series.append({"id": cid, "name": ((comps.get(cid) or {}).get("code", "") + " " + (comps.get(cid) or {}).get("name", "Not assigned")).strip(),
                       "planned": plan, "actual": act})
    return {"months": months, "series": series}


@api("comp.ipc", "commercial", "view")
def comp_ipc(c, u, a):
    """Summary of bills: each IPC's amount by component (this bill, previous and cumulative)."""
    pid = int(a["project_id"])
    m = _comp_of_items(c, pid)
    comps = {x["id"]: x for x in q(c, "SELECT * FROM boq_components WHERE project_id=? AND active=1", (pid,))}
    ipcs = q(c, "SELECT id, no, date, status FROM ipc WHERE project_id=? ORDER BY date, id", (pid,))
    if a.get("ipc_id"):
        sel = int(a["ipc_id"])
    else:
        sel = ipcs[-1]["id"] if ipcs else None
    rows = {}
    order = [i["id"] for i in ipcs]
    for l in q(c, "SELECT l.ipc_id, l.boq_item_id, l.amount FROM ipc_lines l JOIN ipc i ON i.id=l.ipc_id WHERE i.project_id=?", (pid,)):
        cid = m.get(l["boq_item_id"])
        x = rows.setdefault(cid, {"id": cid, "code": (comps.get(cid) or {}).get("code", ""), "name": (comps.get(cid) or {}).get("name", "Not assigned"),
                                  "this": 0.0, "previous": 0.0, "cumulative": 0.0})
        if sel is None or order.index(l["ipc_id"]) > order.index(sel):
            continue
        amt = l["amount"] or 0
        x["cumulative"] += amt
        if l["ipc_id"] == sel:
            x["this"] += amt
        else:
            x["previous"] += amt
    rv = {}
    for b in q(c, "SELECT * FROM boq_items WHERE project_id=?", (pid,)):
        rq = b["revised_qty"] if b.get("revised_qty") is not None else b["qty"]
        rr = b["revised_rate"] if b.get("revised_rate") is not None else b["rate"]
        rv[m.get(b["id"])] = rv.get(m.get(b["id"]), 0) + (rq or 0) * (rr or 0)
    for cid in list(comps) + ([None] if rv.get(None) else []):
        rows.setdefault(cid, {"id": cid, "code": (comps.get(cid) or {}).get("code", ""), "name": (comps.get(cid) or {}).get("name", "Not assigned"),
                              "this": 0.0, "previous": 0.0, "cumulative": 0.0})
    out = []
    for cid, x in rows.items():
        x.update({k: r2(x[k]) for k in ("this", "previous", "cumulative")})
        x["contract_value"] = r2(rv.get(cid, 0))
        x["billed_pct"] = round(100 * x["cumulative"] / rv[cid], 1) if rv.get(cid) else None
        out.append(x)
    out.sort(key=lambda r: ((comps.get(r["id"]) or {}).get("sort") or (9999 if r["id"] is None else 0), str(r["code"]).zfill(4)))
    return {"ipcs": ipcs, "ipc_id": sel, "rows": out, "totals": {k: r2(sum(r[k] for r in out)) for k in ("this", "previous", "cumulative", "contract_value")}}


# BOQ items carry their component
if "component_id" not in inv.MASTERS["boq_items"][1]:
    inv.MASTERS["boq_items"][1].append("component_id")
inv.ID_FIELDS.add("component_id")
