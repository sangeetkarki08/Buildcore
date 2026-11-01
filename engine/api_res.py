"""
BuildCore 2.0 - resources and materials, built into existing screens:

  Work > Schedule & WBS > Resources         resource loading from norms / rate analysis / DPR trade mix,
                                            daily crew and machine histograms, leveling (fixed finish)
                                            and Brooks' allocation (limited resources)          (2.6-2.8)
  Inventory > Material forecast             material plan (MRP) from the CPM dates, net of stock and open
                                            POs, less measured lead time -> purchase requests; reorder
                                            points from schedule demand and measured lead time   (5.1, 6.11)
  Inventory > Material reconciliation       theoretical vs actual consumption per item, per month, with
                                            the allowed wastage, abnormal waste and cause codes   (5.2, 5.10)
  Procurement > Vendor performance          actual PO-to-GRN lead times and a supplier scorecard   (5.5)
  Master data > Labour trades               labour burden calculator -> burdened hourly rate used by DPR
                                            costing, and optionally the resource pool           (3.2, 6.5)
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
        if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='labour_burden'").fetchone():
            init_res(c)
        _READY.add(key)


SCHEMA = """
CREATE TABLE IF NOT EXISTS act_resources(id INTEGER PRIMARY KEY, project_id INTEGER, activity_id INTEGER, kind TEXT,
  ref TEXT, name TEXT, unit TEXT, qty_total REAL DEFAULT 0, material_id INTEGER, trade_id INTEGER, category TEXT,
  source TEXT DEFAULT 'manual', remarks TEXT);
CREATE INDEX IF NOT EXISTS ix_actres ON act_resources(project_id, activity_id);
CREATE TABLE IF NOT EXISTS labour_burden(id INTEGER PRIMARY KEY, trade_id INTEGER UNIQUE, pay_basis TEXT DEFAULT 'monthly',
  basic REAL DEFAULT 0, allowance_month REAL DEFAULT 0, bonus_months REAL DEFAULT 1, ssf_employer_pct REAL DEFAULT 20,
  insurance_year REAL DEFAULT 0, ppe_year REAL DEFAULT 0, other_year REAL DEFAULT 0, working_days_year REAL DEFAULT 282,
  hours_day REAL DEFAULT 8, productive_pct REAL DEFAULT 100, pool_code TEXT, burdened_hour REAL, bare_hour REAL,
  burden_pct REAL, applied TEXT, remarks TEXT);
CREATE TABLE IF NOT EXISTS mat_causes(id INTEGER PRIMARY KEY, project_id INTEGER, boq_item_id INTEGER, material_id INTEGER,
  month TEXT, kind TEXT DEFAULT 'wastage', cause TEXT, qty REAL, value REAL, note TEXT, user_id INTEGER, ts TEXT);
"""
COLUMNS = {"trades": {"base_rate_hour": "REAL", "burden_pct": "REAL"}}

CAUSES = [["design", "Design (changes, errors)"], ["client", "Client (instructions, delays)"],
          ["contractor", "Contractor (planning, supervision)"], ["site", "Site (storage, access, theft)"],
          ["labour", "Labour (poor use, over-mixing)"], ["store", "Store (issue control, damage in store)"],
          ["external", "External (weather, transport damage)"], ["market", "Market (price rise, shortage)"]]


def _cols(c, t):
    try:
        return {r[1] for r in c.execute("PRAGMA table_info(%s)" % t)}
    except Exception:
        return set()


def _has(c, t):
    return bool(c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (t,)).fetchone())


def init_res(c):
    SCH.init_sched(c) if not _has(c, "sched_runs") else None
    c.executescript(SCHEMA)
    for t, cols in COLUMNS.items():
        have = _cols(c, t)
        for k, typ in cols.items():
            if have and k not in have:
                c.execute("ALTER TABLE %s ADD COLUMN %s %s" % (t, k, typ))
    for k, v in (("mrp_cover_weeks", "4"), ("mrp_safety_days", "3"), ("waste_tolerance_pct", "3")):
        c.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", (k, v))


def _o(s):
    return date.fromisoformat(s[:10]).toordinal()


def _dd(c, pid):
    p = q1(c, "SELECT data_date FROM projects WHERE id=?", (pid,)) if "data_date" in _cols(c, "projects") else None
    return (p or {}).get("data_date") or today()


# ───────────────────────── resource loading ─────────────────────────
def _norms(c):
    if not _has(c, "ra_norms"):
        return {}
    out = {}
    for n in q(c, "SELECT * FROM ra_norms"):
        d = dict(n)
        d["lines"] = q(c, "SELECT kind, ref, qty FROM ra_norm_lines WHERE norm_id=? ORDER BY sort, id", (n["id"],))
        out[n["code"]] = d
    return out


def _expand(norm, norms, factor, out, depth=0):
    """Norm lines x factor (activity quantity / norm quantity), sub-analyses expanded."""
    if depth > 6:
        return
    per = float(norm.get("per_qty") or 1)
    for ln in norm["lines"]:
        k, ref, qty = ln["kind"], ln["ref"], float(ln["qty"] or 0)
        if k == "N":
            sub = norms.get(ref)
            if sub:
                _expand(sub, norms, factor * qty / per, out, depth + 1)
        elif k in ("L", "E", "M"):
            out[(k, ref)] = out.get((k, ref), 0) + qty * factor / per


def _activity_norm(c, a):
    if a.get("norm_code"):
        return a["norm_code"]
    if a.get("boq_item_id") and _has(c, "ra_analyses"):
        r = q1(c, "SELECT n.code FROM ra_analyses x JOIN ra_norms n ON n.id=x.norm_id WHERE x.boq_item_id=? "
                  "ORDER BY x.id DESC LIMIT 1", (a["boq_item_id"],))
        if r:
            return r["code"]
    return None


@api("res.load", "project", "edit")
def res_load(c, u, a):
    """Load labour, machines and materials onto each activity: from its norm (activity norm code or the
    BOQ item's saved rate analysis), else from the BOQ rate analysis (man-hours and machine-hours per
    unit) split by the trade and machine mix seen in the DPRs. Lines entered by hand are kept."""
    pid = int(a["project_id"])
    only = a.get("activity_id")
    norms = _norms(c)
    pool = {r["code"]: r for r in q(c, "SELECT * FROM res_pool")} if _has(c, "res_pool") else {}
    acts = q(c, "SELECT * FROM activities WHERE project_id=?%s" % (" AND id=%d" % int(only) if only else ""), (pid,))
    made = {"norm": 0, "rate_analysis": 0, "none": 0}
    trades = {t["id"]: t for t in q(c, "SELECT * FROM trades")}
    for x in acts:
        c.execute("DELETE FROM act_resources WHERE activity_id=? AND source<>'manual'", (x["id"],))
        qty = x["planned_qty"] or 0
        if qty <= 0:
            made["none"] += 1
            continue
        code = _activity_norm(c, x)
        lines = []
        if code and code in norms:
            acc = {}
            _expand(norms[code], norms, qty, acc)
            for (k, ref), tq in acc.items():
                pr = pool.get(ref) or {}
                mid = pr.get("local_id") if pr.get("local_table") == "materials" else None
                lines.append({"kind": k, "ref": ref, "name": pr.get("name") or ref, "unit": pr.get("unit") or "",
                              "qty_total": r4(tq), "material_id": mid, "category": pr.get("category"), "source": "norm"})
            made["norm"] += 1
        elif x.get("boq_item_id"):
            ra = q(c, "SELECT * FROM rate_analysis WHERE boq_item_id=?", (x["boq_item_id"],))
            mh = sum((r["qty_per_unit"] or 0) for r in ra if r["kind"] == "labour") * qty
            eh = sum((r["qty_per_unit"] or 0) for r in ra if r["kind"] == "equipment") * qty
            # split by what the DPRs show for this activity (or the whole project if none yet)
            mix = q(c, "SELECT l.trade_id, SUM(l.count*(l.hours+COALESCE(l.ot_hours,0))) h FROM dpr_labour l JOIN dpr d "
                       "ON d.id=l.dpr_id WHERE l.activity_id=? GROUP BY l.trade_id", (x["id"],)) or \
                q(c, "SELECT l.trade_id, SUM(l.count*(l.hours+COALESCE(l.ot_hours,0))) h FROM dpr_labour l JOIN dpr d "
                     "ON d.id=l.dpr_id WHERE d.project_id=? GROUP BY l.trade_id", (pid,))
            tot = sum(m["h"] or 0 for m in mix)
            if mh > EPS:
                if tot > EPS:
                    for m in mix:
                        t = trades.get(m["trade_id"]) or {}
                        lines.append({"kind": "L", "ref": "TRADE-%s" % m["trade_id"], "name": t.get("name") or "Labour",
                                      "unit": "hr", "qty_total": r4(mh * (m["h"] or 0) / tot), "trade_id": m["trade_id"],
                                      "source": "rate_analysis"})
                else:
                    lines.append({"kind": "L", "ref": "LAB", "name": "Labour (all trades)", "unit": "hr",
                                  "qty_total": r4(mh), "source": "rate_analysis"})
            if eh > EPS:
                emix = q(c, "SELECT COALESCE(e.category,'Plant') cat, SUM(de.hours) h FROM dpr_equipment de JOIN equipment e "
                            "ON e.id=de.equipment_id WHERE de.activity_id=? GROUP BY cat", (x["id"],))
                etot = sum(m["h"] or 0 for m in emix)
                if etot > EPS:
                    for m in emix:
                        lines.append({"kind": "E", "ref": "CAT-" + m["cat"], "name": m["cat"], "unit": "hr",
                                      "qty_total": r4(eh * (m["h"] or 0) / etot), "category": m["cat"], "source": "rate_analysis"})
                else:
                    lines.append({"kind": "E", "ref": "PLANT", "name": "Plant (all machines)", "unit": "hr",
                                  "qty_total": r4(eh), "source": "rate_analysis"})
            for mc in q(c, "SELECT mc.*, m.code, m.name, m.unit FROM material_coefficients mc JOIN materials m ON "
                           "m.id=mc.material_id WHERE mc.boq_item_id=?", (x["boq_item_id"],)):
                lines.append({"kind": "M", "ref": mc["code"], "name": mc["name"], "unit": mc["unit"],
                              "qty_total": r4(qty * (mc["qty_per_unit"] or 0) * (1 + (mc["wastage_pct"] or 0) / 100)),
                              "material_id": mc["material_id"], "source": "rate_analysis"})
            made["rate_analysis" if lines else "none"] += 1
        else:
            made["none"] += 1
        for ln in lines:
            ln.update({"project_id": pid, "activity_id": x["id"]})
            ins(c, "act_resources", ln)
    audit(c, u, "resource_load", "activities", pid, made)
    return made


@api("res.list", "project", "view")
def res_list(c, u, a):
    return q(c, "SELECT r.*, a.code act_code, a.name act_name FROM act_resources r JOIN activities a ON a.id=r.activity_id "
                "WHERE r.project_id=? %s ORDER BY a.code, r.kind, r.name" %
             ("AND r.activity_id=%d" % int(a["activity_id"]) if a.get("activity_id") else ""), (int(a["project_id"]),))


@api("res.save", "project", "edit")
def res_save(c, u, a):
    r = a.get("row") or {}
    need(r, "activity_id", "kind", "name")
    act = get(c, "activities", int(r["activity_id"]), "Activity")
    data = {"project_id": act["project_id"], "activity_id": act["id"], "kind": r["kind"], "ref": r.get("ref") or r["name"],
            "name": r["name"], "unit": r.get("unit"), "qty_total": num(r.get("qty_total") or 0),
            "material_id": int(r["material_id"]) if r.get("material_id") else None,
            "trade_id": int(r["trade_id"]) if r.get("trade_id") else None, "category": r.get("category"),
            "source": "manual", "remarks": r.get("remarks")}
    if r.get("id"):
        upd(c, "act_resources", int(r["id"]), data)
        return {"id": int(r["id"])}
    return {"id": ins(c, "act_resources", data)}


@api("res.delete", "project", "edit")
def res_delete(c, u, a):
    c.execute("DELETE FROM act_resources WHERE id=?", (int(a["id"]),))
    return True


def _per_day_units(unit, qty_per_day, hours_day):
    u = (unit or "").lower()
    if u in ("hr", "h", "hour", "hours", "mh", "man-hour"):
        return qty_per_day / (hours_day or 8)
    return qty_per_day


def _loads(c, pid, kind, basis="early", shifts=None):
    """[(cal, s, f, per_day, wt, ref, name, unit, activity_id)] for the remaining work."""
    cals = SCH.load_cals(c)
    dd = _dd(c, pid)
    ddo = _o(dd)
    acts = {x["id"]: x for x in q(c, "SELECT * FROM activities WHERE project_id=?", (pid,))}
    out = []
    for r in q(c, "SELECT * FROM act_resources WHERE project_id=? AND kind=?", (pid, kind)):
        x = acts.get(r["activity_id"])
        if not x or x.get("actual_finish"):
            continue
        cal = SCH.cal_for(x, cals)
        wt = x.get("work_type") or ""
        if basis == "late" and x.get("ls"):
            s, f = x["ls"], x["lf"]
        else:
            s, f = x.get("es") or x.get("planned_start"), x.get("ef") or x.get("planned_finish")
        if not s or not f:
            continue
        so, fo = _o(s), _o(f) + 1
        if shifts and x["id"] in shifts:
            n = cal.wd(so, fo, wt)
            so = shifts[x["id"]]
            fo = cal.advance(so, n, wt)
        pct = min(1.0, (x["actual_qty"] or 0) / x["planned_qty"]) if x.get("planned_qty") else 0
        rem = (r["qty_total"] or 0) * (1 - pct)
        if rem <= EPS:
            continue
        so = max(so, cal.start_up(ddo, wt)) if x.get("actual_start") else so
        n = cal.wd(so, fo, wt)
        if n <= 0:
            continue
        out.append((cal, so, fo, rem / n, wt, r["ref"], r["name"], r["unit"], x["id"]))
    return out


@api("res.histogram", "project", "view")
def res_histogram(c, u, a):
    """Crew and machine histograms (average per working day in each week) for the remaining work."""
    pid = int(a["project_id"])
    kind = a.get("kind") or "L"
    basis = a.get("basis") or "early"
    hours = 8.0
    cal = q1(c, "SELECT hours_day FROM sched_calendars WHERE is_default=1")
    if cal:
        hours = cal["hours_day"] or 8
    loads = _loads(c, pid, kind, basis)
    if not loads:
        return {"weeks": [], "series": [], "note": "No resources loaded. Press “Load resources from norms”."}
    start = min(x[1] for x in loads)
    end = max(x[2] for x in loads)
    wk0 = start - (date.fromordinal(start).weekday() + 1) % 7
    nweeks = (end - wk0) // 7 + 1
    series = {}
    for cal_, s, f, per, wt, ref, name, unit, aid in loads:
        key = ref
        sr = series.setdefault(key, {"ref": ref, "name": name, "unit": unit, "days": [0.0] * (nweeks * 7), "total": 0.0})
        for o in cal_.workdays(s, f, wt):
            i = o - wk0
            if 0 <= i < len(sr["days"]):
                sr["days"][i] += _per_day_units(unit, per, hours)
        sr["total"] += per * cal_.wd(s, f, wt)
    out = []
    for sr in series.values():
        wk = []
        for w in range(nweeks):
            d = [x for x in sr["days"][w * 7:(w + 1) * 7] if x > 0]
            wk.append(round(sum(d) / len(d), 1) if d else 0)
        out.append({"ref": sr["ref"], "name": sr["name"], "unit": sr["unit"], "weekly": wk, "peak": max(wk or [0]),
                    "avg": round(sum(wk) / max(1, len([x for x in wk if x])), 1), "total": r2(sr["total"])})
    out.sort(key=lambda s: -s["total"])
    weeks = [date.fromordinal(wk0 + 7 * w).isoformat() for w in range(nweeks)]
    return {"weeks": weeks, "series": out, "kind": kind, "basis": basis,
            "measure": "workers on site" if kind == "L" else ("machines working" if kind == "E" else "quantity per day")}


def _int_model(c, pid, kind, refs):
    """Integer working-day model on the project calendar for leveling / allocation."""
    cals = SCH.load_cals(c)
    proj = get(c, "projects", pid)
    cal = cals["cals"].get(proj.get("calendar_id") or cals["default"]) or SC.Calendar()
    dd = _dd(c, pid)
    base = cal.start_up(_o(dd))
    acts = q(c, "SELECT * FROM activities WHERE project_id=? AND actual_finish IS NULL AND es IS NOT NULL", (pid,))
    if not acts:
        raise ApiError("Calculate the schedule first.")
    ids = {x["id"] for x in acts}
    has_pred = set()
    links = []
    for l in q(c, "SELECT * FROM act_links WHERE project_id=?", (pid,)):
        if l["pred_id"] in ids and l["succ_id"] in ids:
            links.append({"pred": l["pred_id"], "succ": l["succ_id"], "type": l["type"], "lag": l["lag"]})
            has_pred.add(l["succ_id"])
    loads = {}
    hours = 8.0
    for r in q(c, "SELECT * FROM act_resources WHERE project_id=? AND kind=?", (pid, kind)):
        if refs and r["ref"] not in refs:
            continue
        loads.setdefault(r["activity_id"], []).append(r)
    A = []
    for x in acts:
        s, f = _o(x["es"]), _o(x["ef"]) + 1
        s = max(s, base)
        dur = max(0, cal.wd(s, f))
        res = {}
        pct = min(1.0, (x["actual_qty"] or 0) / x["planned_qty"]) if x.get("planned_qty") else 0
        for r in loads.get(x["id"], []):
            if dur > 0:
                res[r["ref"]] = res.get(r["ref"], 0) + round(_per_day_units(r["unit"], (r["qty_total"] or 0) * (1 - pct) / dur, hours), 2)
        off = cal.wd(base, s)
        a = {"id": x["id"], "code": x["code"], "name": x["name"], "dur": dur, "res": res,
             # started work and unlinked activities cannot move earlier than they are now
             "min_start": off if (x.get("actual_start") or x["id"] not in has_pred) else 0}
        A.append(a)
    return cal, base, A, links


def _back(cal, base, off):
    return date.fromordinal(cal.advance(base, off)).isoformat() if off > 0 else date.fromordinal(base).isoformat()


@api("res.level", "project", "edit")
def res_level(c, u, a):
    """Resource leveling with the finish fixed: non-critical activities move inside their float to
    smooth the daily demand (minimum-moment method). Apply writes start-no-earlier-than dates."""
    pid = int(a["project_id"])
    kind = a.get("kind") or "L"
    refs = set(a.get("refs") or [])
    cal, base, A, links = _int_model(c, pid, kind, refs)
    start, info = SC.level(A, links)
    base_es = SC.int_cpm(A, links)["es"]
    moves = []
    for x in A:
        if int(start[x["id"]]) != int(base_es[x["id"]]):
            moves.append({"id": x["id"], "code": x["code"], "name": x["name"], "from": _back(cal, base, base_es[x["id"]]),
                          "to": _back(cal, base, start[x["id"]]), "shift_days": int(start[x["id"]] - base_es[x["id"]])})
    if a.get("apply") and moves:
        for m in moves:
            upd(c, "activities", m["id"], {"constraint_type": "SNET", "constraint_date": m["to"]})
        audit(c, u, "level", "schedule", pid, {"moved": len(moves)})
    return {"moves": moves, "peaks_before": info["peaks_before"], "peaks_after": info["peaks_after"],
            "finish": _back(cal, base, info["finish"]), "applied": bool(a.get("apply") and moves)}


@api("res.allocate", "project", "edit")
def res_allocate(c, u, a):
    """Brooks' method: with a crew or machine type capped, activities are started in order of late
    start as the resource allows; the finish date moves if it has to."""
    pid = int(a["project_id"])
    kind = a.get("kind") or "E"
    limits = {k: num(v) for k, v in (a.get("limits") or {}).items() if v not in ("", None)}
    if not limits:
        raise ApiError("Give at least one limit (e.g. 1 drilling jumbo).")
    cal, base, A, links = _int_model(c, pid, kind, set(limits))
    if not any(k in x["res"] for x in A for k in limits):
        raise ApiError("No remaining activity uses %s. Load resources first, or pick one from the histogram list."
                       % ", ".join(limits))
    for x in A:
        for k, v in list(x["res"].items()):
            if k in limits and v > limits[k]:
                x["res"][k] = limits[k]   # an activity needing more than the cap simply runs at the cap
    try:
        start, info = SC.allocate(A, links, limits)
    except SC.ScheduleError as e:
        raise ApiError(str(e))
    base_es = SC.int_cpm(A, links)["es"]
    moves = [{"id": x["id"], "code": x["code"], "name": x["name"], "from": _back(cal, base, base_es[x["id"]]),
              "to": _back(cal, base, start[x["id"]]), "shift_days": int(start[x["id"]] - base_es[x["id"]])}
             for x in A if int(start[x["id"]]) != int(base_es[x["id"]])]
    if a.get("apply") and moves:
        for m in moves:
            upd(c, "activities", m["id"], {"constraint_type": "SNET", "constraint_date": m["to"]})
        audit(c, u, "allocate", "schedule", pid, {"moved": len(moves), "limits": limits})
    return {"moves": moves, "finish": _back(cal, base, info["finish"]), "base_finish": _back(cal, base, info["base_finish"]),
            "delay_days": info["delay"], "applied": bool(a.get("apply") and moves)}


@api("res.clear_leveling", "project", "edit")
def res_clear(c, u, a):
    n = c.execute("UPDATE activities SET constraint_type=NULL, constraint_date=NULL WHERE project_id=? AND "
                  "constraint_type='SNET'", (int(a["project_id"]),)).rowcount
    return {"cleared": n}


# ───────────────────────── lead times and suppliers ─────────────────────────
def lead_stats(c, material_id=None, vendor_id=None, since=None):
    """PO date to first GRN date per PO line."""
    w, p = ["g.status='posted'"], []
    if material_id:
        w.append("pl.material_id=?")
        p.append(material_id)
    if vendor_id:
        w.append("po.vendor_id=?")
        p.append(vendor_id)
    if since:
        w.append("po.date>=?")
        p.append(since)
    rows = q(c, "SELECT pl.id, pl.material_id, po.vendor_id, po.date po_date, po.delivery_date, MIN(g.date) grn_date, "
                "pl.qty, pl.received_qty, po.status, SUM(gl.received_qty) rec, SUM(gl.rejected_qty) rej "
                "FROM po_lines pl JOIN po ON po.id=pl.po_id JOIN grn_lines gl ON gl.po_line_id=pl.id JOIN grn g ON "
                "g.id=gl.grn_id WHERE %s GROUP BY pl.id" % " AND ".join(w), p)
    for r in rows:
        r["lead"] = (date.fromisoformat(r["grn_date"]) - date.fromisoformat(r["po_date"])).days
        r["on_time"] = bool(r["delivery_date"] and r["grn_date"] <= r["delivery_date"])
    return rows


def _summ(xs):
    if not xs:
        return None, None, None
    m = sum(xs) / len(xs)
    sd = math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1)) if len(xs) > 1 else 0.0
    return round(m, 1), round(sd, 1), max(xs)


@api("res.leadtimes", "procurement", "view")
def res_leadtimes(c, u, a):
    since = a.get("since") or (date.today() - timedelta(days=730)).isoformat()
    rows = lead_stats(c, since=since)
    mats = {m["id"]: m for m in q(c, "SELECT id, code, name, unit, lead_days FROM materials")}
    vend = {v["id"]: v for v in q(c, "SELECT id, code, name FROM parties")}
    by_m, by_v = {}, {}
    for r in rows:
        by_m.setdefault(r["material_id"], []).append(r)
        by_v.setdefault(r["vendor_id"], []).append(r)
    mat_out = []
    for mid, lst in by_m.items():
        m = mats.get(mid) or {}
        avg, sd, mx = _summ([x["lead"] for x in lst])
        mat_out.append({"material_id": mid, "code": m.get("code"), "name": m.get("name"), "orders": len(lst),
                        "avg_lead": avg, "sd_lead": sd, "max_lead": mx, "typed_lead": m.get("lead_days")})
    mat_out.sort(key=lambda x: -(x["avg_lead"] or 0))
    ven_out = []
    for vid, lst in by_v.items():
        v = vend.get(vid) or {}
        avg, sd, mx = _summ([x["lead"] for x in lst])
        with_dd = [x for x in lst if x["delivery_date"]]
        closed = [x for x in lst if x["status"] in ("received", "closed")]
        short = [x for x in closed if (x["received_qty"] or 0) + EPS < (x["qty"] or 0)]
        rec = sum(x["rec"] or 0 for x in lst)
        rej = sum(x["rej"] or 0 for x in lst)
        on_time = round(100.0 * sum(1 for x in with_dd if x["on_time"]) / len(with_dd), 1) if with_dd else None
        short_pct = round(100.0 * len(short) / len(closed), 1) if closed else None
        rej_pct = round(100.0 * rej / rec, 2) if rec else None
        score = None
        if on_time is not None:
            score = round(0.5 * on_time + 0.3 * (100 - (short_pct or 0)) + 0.2 * (100 - min(100, 10 * (rej_pct or 0))), 1)
        ven_out.append({"vendor_id": vid, "code": v.get("code"), "name": v.get("name"), "po_lines": len(lst),
                        "avg_lead": avg, "sd_lead": sd, "max_lead": mx, "on_time_pct": on_time,
                        "short_supply_pct": short_pct, "rejection_pct": rej_pct, "score": score,
                        "grade": None if score is None else ("A" if score >= 90 else "B" if score >= 75 else "C" if score >= 60 else "D")})
    ven_out.sort(key=lambda x: -(x["score"] or -1))
    return {"materials": mat_out, "vendors": ven_out, "since": since}


@api("res.leadtimes_apply", "inventory", "edit")
def leadtimes_apply(c, u, a):
    """Use the measured lead times: material lead days = average, and the 1.7 inventory policy gets the
    average and the longest, so safety stock and reorder point follow what really happens."""
    d = res_leadtimes(c, u, a)
    n = 0
    for m in d["materials"]:
        if m["avg_lead"] is None:
            continue
        upd(c, "materials", m["material_id"], {"lead_days": int(round(m["avg_lead"]))})
        if _has(c, "inv_policy"):
            if q1(c, "SELECT material_id FROM inv_policy WHERE material_id=?", (m["material_id"],)):
                c.execute("UPDATE inv_policy SET lead_days=?, max_lead_days=? WHERE material_id=?",
                          (m["avg_lead"], m["max_lead"], m["material_id"]))
            else:
                ins(c, "inv_policy", {"material_id": m["material_id"], "lead_days": m["avg_lead"], "max_lead_days": m["max_lead"]})
        n += 1
    audit(c, u, "lead_times", "materials", None, {"updated": n})
    return {"updated": n}


def lead_for(c, material_id):
    rows = lead_stats(c, material_id=material_id, since=(date.today() - timedelta(days=730)).isoformat())
    avg, sd, mx = _summ([r["lead"] for r in rows])
    m = q1(c, "SELECT lead_days FROM materials WHERE id=?", (material_id,)) or {}
    if avg is None:
        typed = m.get("lead_days") or 7
        return {"avg": typed, "max": typed, "measured": False, "orders": 0}
    return {"avg": avg, "max": mx, "sd": sd, "measured": True, "orders": len(rows)}


# ───────────────────────── MRP from the schedule ─────────────────────────
def schedule_demand(c, pid, days_ahead=None):
    """{material_id: {ordinal: qty}} for the remaining work on the CPM dates."""
    cals = SCH.load_cals(c)
    dd = _dd(c, pid)
    ddo = _o(dd)
    acts = q(c, "SELECT * FROM activities WHERE project_id=? AND actual_finish IS NULL", (pid,))
    out = {}
    for x in acts:
        s, f = x.get("es") or x.get("planned_start"), x.get("ef") or x.get("planned_finish")
        if not s or not f or not x.get("planned_qty"):
            continue
        cal = SCH.cal_for(x, cals)
        wt = x.get("work_type") or ""
        rem = max((x["planned_qty"] or 0) - (x["actual_qty"] or 0), 0)
        if rem <= EPS:
            continue
        so = max(_o(s), cal.start_up(ddo, wt))
        fo = _o(f) + 1
        days = cal.workdays(so, fo, wt)
        if not days:
            continue
        mats = {}
        if x.get("boq_item_id"):
            for mc in q(c, "SELECT * FROM material_coefficients WHERE boq_item_id=?", (x["boq_item_id"],)):
                mats[mc["material_id"]] = (mc["qty_per_unit"] or 0) * (1 + (mc["wastage_pct"] or 0) / 100)
        for r in q(c, "SELECT * FROM act_resources WHERE activity_id=? AND kind='M' AND material_id IS NOT NULL", (x["id"],)):
            if r["material_id"] not in mats and x["planned_qty"]:
                mats[r["material_id"]] = (r["qty_total"] or 0) / x["planned_qty"]
        for mid, per in mats.items():
            tot = rem * per
            if tot <= EPS:
                continue
            per_day = tot / len(days)
            bucket = out.setdefault(mid, {})
            for o in days:
                if days_ahead and o > ddo + days_ahead:
                    break
                bucket[o] = bucket.get(o, 0) + per_day
    return out


@api("res.mrp", "inventory", "view")
def res_mrp(c, u, a):
    """Material requirements from the schedule: weekly demand for the remaining work on the CPM dates,
    against stock and open purchase orders; the order-by date is the first shortfall less the measured
    lead time and a few safety days."""
    pid = int(a["project_id"])
    weeks = int(a.get("weeks") or 16)
    cover = int(float(setting(c, "mrp_cover_weeks") or 4))
    safety_days = float(setting(c, "mrp_safety_days") or 3)
    dd = _dd(c, pid)
    ddo = _o(dd)
    t0 = date.fromisoformat(dd)
    wk0 = (t0 - timedelta(days=(t0.weekday() + 1) % 7)).toordinal()
    dem = schedule_demand(c, pid)
    mats = {m["id"]: m for m in q(c, "SELECT * FROM materials")}
    open_pr = {r["material_id"]: r["q"] for r in q(c, "SELECT l.material_id, SUM(l.qty-COALESCE(l.ordered_qty,0)) q FROM "
                                                     "pr_lines l JOIN pr ON pr.id=l.pr_id WHERE pr.project_id=? AND pr.status "
                                                     "IN ('draft','submitted','approved','partially_ordered') GROUP BY l.material_id", (pid,))}
    rows = []
    for mid, daily in dem.items():
        m = mats.get(mid)
        if not m:
            continue
        lt = lead_for(c, mid)
        stock = inv.project_available(c, pid, mid)
        receipts = {}
        for po in q(c, "SELECT pl.qty-MIN(pl.received_qty,pl.qty) q, po.delivery_date, po.date FROM po_lines pl JOIN po ON "
                       "po.id=pl.po_id WHERE po.project_id=? AND pl.material_id=? AND po.status IN "
                       "('approved','partially_received')", (pid, mid)):
            due = po["delivery_date"] or (date.fromisoformat(po["date"]) + timedelta(days=int(lt["avg"]))).isoformat()
            k = max(0, (_o(due) - wk0) // 7)
            receipts[k] = receipts.get(k, 0) + (po["q"] or 0)
        wk = []
        bal = stock
        short_week = None
        total = 0.0
        for w in range(weeks):
            d = sum(v for o, v in daily.items() if wk0 + 7 * w <= o < wk0 + 7 * (w + 1))
            total += d
            rc = receipts.get(w, 0)
            bal = bal + rc - d
            wk.append({"week": date.fromordinal(wk0 + 7 * w).isoformat(), "demand": r2(d), "receipts": r2(rc), "balance": r2(bal)})
        avg_daily = total / (weeks * 6.0) if weeks else 0
        safety = max(0.0, avg_daily * max(0.0, (lt["max"] or 0) - (lt["avg"] or 0))) + avg_daily * safety_days
        for i, x in enumerate(wk):
            if x["balance"] < safety - EPS and x["demand"] > 0:
                short_week = i
                break
        need_date = order_by = None
        qty = 0.0
        if short_week is not None:
            need_date = wk[short_week]["week"]
            order_by = (date.fromisoformat(need_date) - timedelta(days=int(math.ceil(lt["avg"] + safety_days)))).isoformat()
            horizon = sum(x["demand"] for x in wk[short_week:short_week + cover])
            bal_start = (wk[short_week - 1]["balance"] if short_week > 0 else stock) + wk[short_week]["receipts"]
            qty = max(0.0, horizon + safety - bal_start)
            qty -= open_pr.get(mid, 0)
        urgency = None
        if order_by:
            urgency = "late" if order_by < today() else ("now" if order_by <= (date.today() + timedelta(days=7)).isoformat() else "planned")
        rows.append({"material_id": mid, "code": m["code"], "name": m["name"], "unit": m["unit"], "stock": r2(stock),
                     "on_order": r2(sum(receipts.values())), "open_pr": r2(open_pr.get(mid, 0)),
                     "demand_horizon": r2(total), "lead_avg": lt["avg"], "lead_max": lt["max"], "lead_measured": lt["measured"],
                     "safety": r2(safety), "need_date": need_date, "order_by": order_by, "suggested_qty": r2(max(qty, 0)),
                     "rate": m.get("standard_rate"), "urgency": urgency, "weeks": wk})
    rank = {"late": 0, "now": 1, "planned": 2, None: 3}
    rows.sort(key=lambda r: (rank[r["urgency"]], r["order_by"] or "9999"))
    return {"data_date": dd, "weeks": [date.fromordinal(wk0 + 7 * w).isoformat() for w in range(weeks)], "rows": rows,
            "cover_weeks": cover, "safety_days": safety_days}


@api("res.mrp_to_pr", "procurement", "edit")
def mrp_to_pr(c, u, a):
    """Raise one draft purchase request for the chosen suggestions, required by the earliest need date."""
    pid = int(a["project_id"])
    lines = [x for x in (a.get("rows") or []) if num(x.get("qty") or 0) > 0]
    if not lines:
        raise ApiError("Choose at least one material with a quantity.")
    mats = {m["id"]: m for m in q(c, "SELECT id, unit, standard_rate FROM materials")}
    req = min([x.get("need_date") for x in lines if x.get("need_date")] or [today()])
    r = inv.FUNCS["doc.save"][0](c, u, {"type": "pr", "header": {
        "project_id": pid, "date": today(), "required_by": req, "priority": "high" if req <= today() else "normal",
        "remarks": "Raised from the schedule material plan (MRP), data date %s" % _dd(c, pid)},
        "lines": [{"material_id": int(x["material_id"]), "qty": r4(num(x["qty"])), "unit": (mats.get(int(x["material_id"])) or {}).get("unit"),
                   "est_rate": (mats.get(int(x["material_id"])) or {}).get("standard_rate") or 0,
                   "description": "Need by %s" % (x.get("need_date") or req)} for x in lines]})
    audit(c, u, "mrp_pr", "pr", r.get("id") if isinstance(r, dict) else None, {"lines": len(lines)})
    return r


@api("res.rop", "inventory", "view")
def res_rop(c, u, a):
    """Reorder point = daily demand x lead time + safety stock, with the demand taken from the schedule
    (next 30 days) when there is one, else from the last 90 days of issues, and the lead time measured
    from POs and GRNs. Apply writes the reorder level on the material and the 1.7 policy."""
    pid = int(a["project_id"])
    dd = _dd(c, pid)
    dem = schedule_demand(c, pid, 30)
    since = (date.fromisoformat(dd) - timedelta(days=90)).isoformat()
    hist = {r["material_id"]: r["q"] for r in q(c, "SELECT l.material_id, SUM(l.qty-l.returned_qty) q FROM issue_lines l JOIN "
                                                  "issues i ON i.id=l.issue_id WHERE i.status='posted' AND i.project_id=? AND "
                                                  "i.date>=? GROUP BY l.material_id", (pid, since))}
    ids = set(dem) | set(hist)
    rows = []
    for mid in ids:
        m = q1(c, "SELECT * FROM materials WHERE id=?", (mid,))
        if not m:
            continue
        sched_daily = sum(dem.get(mid, {}).values()) / 30.0 if mid in dem else None
        hist_daily = (hist.get(mid) or 0) / 90.0
        daily = sched_daily if sched_daily else hist_daily
        lt = lead_for(c, mid)
        safety = daily * max(0.0, lt["max"] - lt["avg"]) if lt["measured"] else daily * lt["avg"] * 0.25
        rop = daily * lt["avg"] + safety
        rows.append({"material_id": mid, "code": m["code"], "name": m["name"], "unit": m["unit"],
                     "daily_schedule": r4(sched_daily) if sched_daily is not None else None, "daily_history": r4(hist_daily),
                     "basis": "schedule" if sched_daily else "history", "lead_avg": lt["avg"], "lead_max": lt["max"],
                     "lead_measured": lt["measured"], "safety": r2(safety), "rop": r2(rop), "current_rop": m["reorder_level"],
                     "stock": r2(inv.project_available(c, pid, mid))})
    rows.sort(key=lambda r: r["code"] or "")
    if a.get("apply"):
        n = 0
        for r in rows:
            if a.get("ids") and r["material_id"] not in set(int(x) for x in a["ids"]):
                continue
            upd(c, "materials", r["material_id"], {"reorder_level": r["rop"]})
            n += 1
        audit(c, u, "reorder_points", "materials", None, {"updated": n})
        return {"rows": rows, "updated": n}
    return {"rows": rows}


# the Material forecast page (material_risks) now reads schedule demand and measured lead time
_orig_risks = P.material_risks


def material_risks(c, pid):
    rows = _orig_risks(c, pid)
    try:
        ensure(c)
        dem = schedule_demand(c, pid, 30)
    except Exception:
        return rows
    have = {r["material_id"] for r in rows}
    for mid in dem:
        if mid not in have:
            m = q1(c, "SELECT * FROM materials WHERE id=?", (mid,))
            if m:
                rows.append({"material_id": mid, "code": m["code"], "name": m["name"], "unit": m["unit"], "available": 0,
                             "avg_daily": 0, "days_left": None, "lead_days": m["lead_days"] or 7, "pending_po": 0,
                             "last_rate": None, "risk": False, "why": ""})
    for r in rows:
        mid = r["material_id"]
        lt = lead_for(c, mid)
        sched = sum(dem.get(mid, {}).values()) / 30.0 if mid in dem else None
        r["history_daily"] = r["avg_daily"]
        if sched:
            r["avg_daily"] = r4(sched)
            r["basis"] = "schedule"
        else:
            r["basis"] = "history"
        r["lead_days"] = lt["avg"]
        r["lead_measured"] = lt["measured"]
        daily = r["avg_daily"]
        have = r["available"]
        r["days_left"] = round(have / daily, 1) if daily > EPS else None
        risk = daily > EPS and have + (r.get("pending_po") or 0) < daily * lt["max"]
        r["risk"] = bool(risk)
        r["why"] = ("Stock %s %s covers %.1f days of the %s demand; delivery takes %s days (%s)%s." % (
            r4(have), r["unit"], r["days_left"] or 0, r["basis"], lt["avg"], "measured" if lt["measured"] else "typed",
            "" if not r.get("pending_po") else ", %s on order" % r4(r["pending_po"]))) if risk else ""
    return rows


P.material_risks = material_risks


# ───────────────────────── theoretical vs actual consumption ─────────────────────────
@api("res.consumption", "inventory", "view")
def res_consumption(c, u, a):
    """For each BOQ item and material: work done (executed, or verified-measured) x coefficient = the
    theoretical quantity, against the net issues. Allowed wastage comes from the coefficient; anything
    beyond it plus the tolerance is abnormal waste (NAS 2 para 16a), which is expensed and kept out of
    progress. month = YYYY-MM limits both sides to that month (executed from approved DPRs)."""
    pid = int(a["project_id"])
    basis = a.get("basis") or "executed"
    month = a.get("month")
    tol = float(a.get("tolerance") or setting(c, "waste_tolerance_pct") or 3)
    rows = q(c, "SELECT mc.*, b.code boq_code, b.description, b.unit boq_unit, b.executed_qty, m.code mat_code, m.name mat_name, "
                "m.unit, m.standard_rate FROM material_coefficients mc JOIN boq_items b ON b.id=mc.boq_item_id JOIN materials m "
                "ON m.id=mc.material_id WHERE b.project_id=? ORDER BY b.code, m.code", (pid,))
    out = []
    for r in rows:
        if month:
            done = val(c, "SELECT SUM(w.actual_qty) FROM dpr_work w JOIN dpr d ON d.id=w.dpr_id WHERE d.status='approved' AND "
                          "w.boq_item_id=? AND substr(d.date,1,7)=?", (r["boq_item_id"], month))
            dw = "AND substr(i.date,1,7)=?"
            dr = "AND substr(x.date,1,7)=?"
            pm = (month,)
        else:
            if basis == "measured":
                done = val(c, "SELECT SUM(l.qty) FROM measurement_lines l JOIN measurements m ON m.id=l.measurement_id WHERE "
                              "m.status='verified' AND l.boq_item_id=?", (r["boq_item_id"],))
            else:
                done = r["executed_qty"] or 0
            dw = dr = ""
            pm = ()
        issued = val(c, "SELECT SUM(l.qty) FROM issue_lines l JOIN issues i ON i.id=l.issue_id WHERE i.status='posted' AND "
                        "l.boq_item_id=? AND l.material_id=? " + dw, (r["boq_item_id"], r["material_id"]) + pm)
        value = val(c, "SELECT SUM(l.amount) FROM issue_lines l JOIN issues i ON i.id=l.issue_id WHERE i.status='posted' AND "
                       "l.boq_item_id=? AND l.material_id=? " + dw, (r["boq_item_id"], r["material_id"]) + pm)
        returned = val(c, "SELECT SUM(l.qty) FROM return_lines l JOIN returns x ON x.id=l.return_id WHERE x.status='posted' AND "
                          "l.condition IN ('usable','repairable') AND l.boq_item_id=? AND l.material_id=? " + dr,
                       (r["boq_item_id"], r["material_id"]) + pm)
        net = issued - returned
        rate = value / issued if issued > EPS else (r["standard_rate"] or 0)
        base_q = (done or 0) * (r["qty_per_unit"] or 0)
        allowed = base_q * (1 + (r["wastage_pct"] or 0) / 100)
        wastage_pct = round(100 * (net - base_q) / base_q, 2) if base_q > EPS else None
        excess = net - allowed * (1 + tol / 100)
        cause = q1(c, "SELECT cause, note FROM mat_causes WHERE project_id=? AND boq_item_id=? AND material_id=? AND "
                      "COALESCE(month,'')=? ORDER BY id DESC LIMIT 1", (pid, r["boq_item_id"], r["material_id"], month or ""))
        out.append({"boq_item_id": r["boq_item_id"], "boq_code": r["boq_code"], "description": r["description"],
                    "material_id": r["material_id"], "mat_code": r["mat_code"], "mat_name": r["mat_name"], "unit": r["unit"],
                    "work_done": r4(done), "boq_unit": r["boq_unit"], "coefficient": r["qty_per_unit"],
                    "allowed_pct": r["wastage_pct"], "theoretical": r4(base_q), "allowed": r4(allowed), "actual": r4(net),
                    "wastage_pct": wastage_pct, "variance": r4(net - allowed), "rate": r2(rate),
                    "variance_value": r2((net - allowed) * rate), "abnormal_qty": r4(max(0.0, excess)),
                    "abnormal_value": r2(max(0.0, excess) * rate), "flag": excess > EPS or (base_q <= EPS and net > EPS),
                    "cause": (cause or {}).get("cause"), "cause_note": (cause or {}).get("note")})
    by_mat = {}
    for r in out:
        k = r["material_id"]
        s = by_mat.setdefault(k, {"material_id": k, "mat_code": r["mat_code"], "mat_name": r["mat_name"], "unit": r["unit"],
                                  "theoretical": 0.0, "allowed": 0.0, "actual": 0.0, "abnormal_value": 0.0, "variance_value": 0.0})
        for f in ("theoretical", "allowed", "actual", "abnormal_value", "variance_value"):
            s[f] += r[f]
    mats = []
    for s in by_mat.values():
        s["wastage_pct"] = round(100 * (s["actual"] - s["theoretical"]) / s["theoretical"], 2) if s["theoretical"] > EPS else None
        s["mat_cpi"] = round(s["allowed"] / s["actual"], 2) if s["actual"] > EPS else None
        for f in ("theoretical", "allowed", "actual"):
            s[f] = r4(s[f])
        s["abnormal_value"] = r2(s["abnormal_value"])
        s["variance_value"] = r2(s["variance_value"])
        mats.append(s)
    mats.sort(key=lambda x: -x["abnormal_value"])
    months = [r["m"] for r in q(c, "SELECT DISTINCT substr(i.date,1,7) m FROM issues i WHERE i.project_id=? AND i.status='posted' "
                                   "ORDER BY m DESC LIMIT 24", (pid,))]
    return {"rows": out, "materials": mats, "tolerance": tol, "basis": basis, "month": month, "months": months,
            "abnormal_total": r2(sum(r["abnormal_value"] for r in out)), "causes": CAUSES}


@api("res.cause_save", "inventory", "edit")
def cause_save(c, u, a):
    r = a.get("row") or {}
    need(r, "project_id", "material_id", "cause")
    ins(c, "mat_causes", {"project_id": int(r["project_id"]), "boq_item_id": int(r["boq_item_id"]) if r.get("boq_item_id") else None,
                          "material_id": int(r["material_id"]), "month": r.get("month") or "", "kind": r.get("kind") or "wastage",
                          "cause": r["cause"], "qty": num(r.get("qty") or 0), "value": num(r.get("value") or 0),
                          "note": r.get("note"), "user_id": u["id"], "ts": now()})
    return True


@api("res.cause_pareto", "inventory", "view")
def cause_pareto(c, u, a):
    w, p = ["1=1"], []
    if a.get("project_id"):
        w.append("project_id=?")
        p.append(int(a["project_id"]))
    if a.get("year"):
        w.append("substr(ts,1,4)=?")
        p.append(str(a["year"]))
    rows = q(c, "SELECT cause, COUNT(*) n, SUM(value) v FROM mat_causes WHERE %s GROUP BY cause ORDER BY v DESC" % " AND ".join(w), p)
    lab = dict(CAUSES)
    tot = sum(r["v"] or 0 for r in rows) or 1
    acc = 0.0
    for r in rows:
        acc += r["v"] or 0
        r["label"] = lab.get(r["cause"], r["cause"])
        r["cum_pct"] = round(100 * acc / tot, 1)
    return rows


@api("res.post_waste", "accounts", "edit")
def post_waste(c, u, a):
    """Take abnormal waste out of contract cost into a period expense (NAS 2 para 16a, NFRS 15 cost-to-cost)."""
    pid = int(a["project_id"])
    d = a.get("date") or today()
    rows = [x for x in (a.get("rows") or []) if num(x.get("value") or 0) > EPS]
    if not rows:
        raise ApiError("Nothing to post.")
    from core import post_voucher
    if not val(c, "SELECT id FROM accounts WHERE role='abnormal_waste'", (), None):
        gid = val(c, "SELECT id FROM account_groups WHERE type='expense' ORDER BY id", (), None)
        code = "5990"
        while val(c, "SELECT id FROM accounts WHERE code=?", (code,), None):
            code = str(int(code) + 1)
        ins(c, "accounts", {"code": code, "name": "Abnormal material waste (period expense)", "type": "expense",
                            "group_id": gid, "role": "abnormal_waste", "active": 1})
    lines = []
    for x in rows:
        v = r2(num(x["value"]))
        lines.append({"role": "abnormal_waste", "debit": v, "project_id": pid, "narration": "Abnormal waste %s" % (x.get("label") or "")})
        lines.append({"role": "material_cost", "credit": v, "project_id": pid,
                      "boq_item_id": int(x["boq_item_id"]) if x.get("boq_item_id") else None})
    vid = post_voucher(c, u, "journal", d, "Abnormal material waste taken out of contract cost", lines, project_id=pid,
                       source="abnormal_waste", source_id=pid)
    audit(c, u, "post", "abnormal_waste", pid, {"voucher": vid, "total": sum(num(x["value"]) for x in rows)})
    return {"voucher_id": vid}


# ───────────────────────── labour burden ─────────────────────────
def burden_calc(r):
    basic = num(r.get("basic") or 0)
    if (r.get("pay_basis") or "monthly") == "daily":
        basic_month = basic * 26
    else:
        basic_month = basic
    allow = num(r.get("allowance_month") or 0)
    bonus = num(r.get("bonus_months") if r.get("bonus_months") not in (None, "") else 1)
    ssf = num(r.get("ssf_employer_pct") if r.get("ssf_employer_pct") not in (None, "") else 20)
    ins_ = num(r.get("insurance_year") or 0)
    ppe = num(r.get("ppe_year") or 0)
    other = num(r.get("other_year") or 0)
    wdays = num(r.get("working_days_year") or 282)
    hday = num(r.get("hours_day") or 8)
    prod = num(r.get("productive_pct") or 100) / 100.0
    wages = 12 * basic_month
    parts = {"Basic wages": wages, "Allowances (site, food, dearness)": 12 * allow, "Festival (Dashain) bonus": bonus * basic_month,
             "SSF employer contribution": wages * ssf / 100, "Accident & medical insurance": ins_, "PPE and tools": ppe,
             "Other (camp, transport, training)": other}
    annual = sum(parts.values())
    hours = wdays * hday * prod
    bare = wages / (wdays * hday) if wdays * hday else 0
    burdened = annual / hours if hours else 0
    return {"parts": {k: r2(v) for k, v in parts.items()}, "annual_cost": r2(annual), "productive_hours": r2(hours),
            "bare_hour": r2(bare), "burdened_hour": r2(burdened),
            "burden_pct": round(100 * (burdened / bare - 1), 1) if bare else None, "burdened_day": r2(burdened * hday)}


@api("burden.list", "project", "view")
def burden_list(c, u, a):
    rows = q(c, "SELECT t.id trade_id, t.code, t.name, t.rate_hour, t.base_rate_hour, t.project_id, b.* FROM trades t LEFT JOIN "
                "labour_burden b ON b.trade_id=t.id WHERE t.active=1 ORDER BY t.name")
    for r in rows:
        r["trade_id"] = r["trade_id"] or r.get("id")
        r["calc"] = burden_calc(r) if r.get("basic") else None
    return {"rows": rows, "defaults": {"ssf_employer_pct": 20, "bonus_months": 1, "working_days_year": 282, "hours_day": 8},
            "note": "SSF: 31% of basic, 20% paid by the employer and 11% deducted from the worker (Social Security Act "
                    "2075) [confirm with your auditor]. Working days 282 = 365 less 52 Saturdays, 13 public holidays and "
                    "18 days of leave."}


@api("burden.save", "project", "edit")
def burden_save(c, u, a):
    r = a.get("row") or {}
    need(r, "trade_id")
    tid = int(r["trade_id"])
    res = burden_calc(r)
    data = {k: r.get(k) for k in ("pay_basis", "pool_code", "remarks")}
    for k in ("basic", "allowance_month", "bonus_months", "ssf_employer_pct", "insurance_year", "ppe_year", "other_year",
              "working_days_year", "hours_day", "productive_pct"):
        data[k] = num(r[k]) if r.get(k) not in (None, "") else None
    data.update({"burdened_hour": res["burdened_hour"], "bare_hour": res["bare_hour"], "burden_pct": res["burden_pct"]})
    ex = q1(c, "SELECT id FROM labour_burden WHERE trade_id=?", (tid,))
    if ex:
        upd(c, "labour_burden", ex["id"], data)
    else:
        data["trade_id"] = tid
        ins(c, "labour_burden", data)
    if a.get("apply"):
        t = get(c, "trades", tid, "Trade")
        upd(c, "trades", tid, {"rate_hour": res["burdened_hour"], "burden_pct": res["burden_pct"],
                               "base_rate_hour": t.get("base_rate_hour") or t["rate_hour"]})
        c.execute("UPDATE labour_burden SET applied=? WHERE trade_id=?", (now(), tid))
        if r.get("pool_code") and _has(c, "res_pool"):
            c.execute("UPDATE res_pool SET rate=?, rate_source=?, sample=0, updated=? WHERE code=? AND type='labour'",
                      (res["burdened_day"], "Burdened rate from labour burden calculator", now(), r["pool_code"]))
        audit(c, u, "burden_apply", "trades", tid, res)
    return res


@api("burden.calc", "project", "view")
def burden_calc_api(c, u, a):
    return burden_calc(a.get("row") or {})


@api("res.options", "project", "view")
def res_options(c, u, a):
    return {"causes": CAUSES, "cover_weeks": int(float(setting(c, "mrp_cover_weeks") or 4)),
            "safety_days": float(setting(c, "mrp_safety_days") or 3),
            "tolerance": float(setting(c, "waste_tolerance_pct") or 3)}
