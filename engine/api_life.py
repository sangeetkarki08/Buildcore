"""
BuildCore 2.2 - equipment and asset life cycle (ISO 55000 stages; Wang 2022; Bajet & Manalo 2025),
built into the existing Equipment, Assets and Fixed assets screens:

  Equipment > Register            business case before purchase (4.1), acquisition file (4.2),
                                  replacement and disposal workflow (4.7), QR tags and physical
                                  verification (4.8), asset-management maturity check (4.10)
  Equipment > Monthly logsheets   failed daily point-inspection items raise work orders (4.3),
                                  operator violations and penalties
  Equipment > Work orders         breakdown failure codes, downtime cost, MTBF / MTTR / availability (4.4)
  Equipment > Maintenance         class rules A/B/C with spare reserve and safety-check cycle (4.5),
                                  spare-parts demand forecast (4.6)
  Equipment > Day-by-day log      telematics CSV import (4.9)
  Fixed assets > Equipment costing   decision tools and time-value calculator (3.13, 3.14)
"""
import json
from datetime import date, timedelta

from core import ApiError, EPS, audit, get, ins, need, next_no, now, num, q, q1, r2, r4, setting, today, upd, val
import api_inventory as inv
from api_inventory import api as _register
import api_equipment_reports as ER
import api_logsheet  # noqa: F401  (book.checks must be registered first)
import fin_calc as F

POSTED = "v.status IN ('posted','reversed')"
_READY = set()


def api(name, module=None, action=None):
    def wrap(f):
        def run(c, u, a):
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
        if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='eq_tools'").fetchone() or \
                "failure_code" not in _cols(c, "work_orders") or "tool_id" not in _cols(c, "dpr_equipment"):
            init_life(c)
        _READY.add(key)


SCHEMA = """
CREATE TABLE IF NOT EXISTS eq_tools(id INTEGER PRIMARY KEY, equipment_id INTEGER, name TEXT, kind TEXT, rate_hr REAL,
  hire_rate_hr REAL, fuel_hr REAL, output_unit TEXT, norm_output_hr REAL, is_default INTEGER DEFAULT 0, active INTEGER DEFAULT 1,
  remarks TEXT);
CREATE TABLE IF NOT EXISTS log_tools(id INTEGER PRIMARY KEY, log_id INTEGER, tool_id INTEGER, hours REAL DEFAULT 0,
  output_qty REAL, activity_id INTEGER, dpr_equipment_id INTEGER);
CREATE INDEX IF NOT EXISTS ix_log_tools ON log_tools(log_id);
CREATE TABLE IF NOT EXISTS asset_cases(id INTEGER PRIMARY KEY, no TEXT, date TEXT, title TEXT, category TEXT, project_id INTEGER,
  need TEXT, hours_year REAL, years INTEGER DEFAULT 5, marr REAL DEFAULT 12, inputs TEXT, result TEXT, chosen TEXT,
  risk_likelihood INTEGER, risk_consequence INTEGER, risk_note TEXT, savings_year REAL, status TEXT DEFAULT 'draft',
  decided_by INTEGER, decided_on TEXT, equipment_id INTEGER, remarks TEXT, created_by INTEGER);
CREATE TABLE IF NOT EXISTS asset_acq(id INTEGER PRIMARY KEY, case_id INTEGER, equipment_id INTEGER, step TEXT, date TEXT,
  ref TEXT, done INTEGER DEFAULT 0, supplier TEXT, vetted INTEGER DEFAULT 0, notes TEXT, user_id INTEGER);
CREATE TABLE IF NOT EXISTS operator_violations(id INTEGER PRIMARY KEY, date TEXT, equipment_id INTEGER, operator TEXT,
  violation TEXT, penalty REAL DEFAULT 0, action TEXT, remarks TEXT, user_id INTEGER);
CREATE TABLE IF NOT EXISTS equipment_spares(id INTEGER PRIMARY KEY, equipment_id INTEGER, material_id INTEGER, qty REAL DEFAULT 1,
  remarks TEXT);
CREATE TABLE IF NOT EXISTS safety_checks(id INTEGER PRIMARY KEY, equipment_id INTEGER, date TEXT, result TEXT DEFAULT 'pass',
  checked_by TEXT, notes TEXT, next_due TEXT);
CREATE TABLE IF NOT EXISTS asset_disposals(id INTEGER PRIMARY KEY, no TEXT, equipment_id INTEGER, asset_id INTEGER, trigger TEXT,
  assessment TEXT, assessed_by TEXT, application TEXT, evaluation_value REAL, process TEXT, status TEXT DEFAULT 'proposed',
  approved_by INTEGER, approved_on TEXT, method TEXT, proceeds REAL, completed_on TEXT, voucher_id INTEGER, remarks TEXT,
  created_by INTEGER, date TEXT);
CREATE TABLE IF NOT EXISTS verify_rounds(id INTEGER PRIMARY KEY, name TEXT, date TEXT, status TEXT DEFAULT 'open', remarks TEXT);
CREATE TABLE IF NOT EXISTS verify_items(id INTEGER PRIMARY KEY, round_id INTEGER, kind TEXT, ref_id INTEGER, found INTEGER DEFAULT 1,
  location TEXT, condition TEXT, notes TEXT, by TEXT, ts TEXT, UNIQUE(round_id, kind, ref_id));
CREATE TABLE IF NOT EXISTS maturity_checks(id INTEGER PRIMARY KEY, year TEXT, stage TEXT, qkey TEXT, score INTEGER, note TEXT,
  UNIQUE(year, qkey));
"""
COLUMNS = {"dpr_equipment": {"tool_id": "INTEGER", "output_qty": "REAL"},
           "work_orders": {"failure_code": "TEXT", "cause_detail": "TEXT", "idle_crew": "REAL", "crew_rate_hour": "REAL",
                           "idle_linked_cost_hour": "REAL", "activity_id": "INTEGER", "ld_applied": "REAL",
                           "downtime_cost": "REAL", "source": "TEXT", "source_ref": "TEXT"},
           "equipment": {"operator_cert_no": "TEXT", "operator_cert_expiry": "TEXT", "responsible_person": "TEXT",
                         "location": "TEXT", "last_seen": "TEXT", "lat": "REAL", "lon": "REAL"}}

FAILURE_CODES = [["function_loss", "Function loss / will not work"], ["over_temperature", "Over-temperature"],
                 ["oil_gas_loss", "Oil or gas loss"], ["lubrication", "Lubrication failure"], ["electrical", "Electrical"],
                 ["vibration_noise", "Abnormal vibration or noise"], ["leakage", "Leakage (water, fuel, hydraulic)"],
                 ["smell", "Abnormal smell / smoke"], ["hydraulic", "Hydraulic system"], ["tyre_track", "Tyres / tracks / undercarriage"],
                 ["structural", "Structural / crack / weld"], ["operator_error", "Operator error / misuse"], ["other", "Other"]]
ACQ_STEPS = [["application", "Purchase application (need and business case)"], ["comparison", "Price comparison table"],
             ["selection", "Supplier / factory selection and vetting"], ["contract", "Contract or purchase order"],
             ["receipt", "Receipt and acceptance report"], ["install", "Installation and commissioning record"],
             ["operation", "Put into operation (register, insurance, operator named)"]]
DEFAULT_RULES = {"A": {"operator_cert": 1, "responsible": 1, "full_records": 1, "spare_reserve_pct": 100, "safety_cycle_days": 30},
                 "B": {"operator_cert": 0, "responsible": 1, "full_records": 1, "spare_reserve_pct": 80, "safety_cycle_days": 90},
                 "C": {"operator_cert": 0, "responsible": 0, "full_records": 0, "spare_reserve_pct": 0, "safety_cycle_days": 365}}
MATURITY = [
    ("business_case", "Business case", [("bc_need", "Need taken from planned work (schedule demand), not habit"),
                                        ("bc_finance", "Detailed financial evaluation (NPV / buy-hire-lease)"),
                                        ("bc_risk", "Failure-risk analysis before buying"),
                                        ("bc_savings", "Expected savings summarised and checked after purchase")]),
    ("acquire", "Acquire", [("aq_vetting", "Suppliers vetted and prices compared"), ("aq_acceptance", "Acceptance test on receipt"),
                            ("aq_commission", "Installation and commissioning recorded"), ("aq_docs", "Complete acquisition file kept")]),
    ("operate", "Operate & maintain", [("op_pm", "Preventive maintenance plan followed"), ("op_inspect", "Daily point inspection done"),
                                       ("op_training", "Operators trained and certified"), ("op_records", "Breakdowns coded, MTBF/MTTR tracked")]),
    ("dispose", "Dispose", [("dp_criteria", "Replacement criteria (economic life, repair trend)"),
                            ("dp_eval", "Disposal evaluated and approved"), ("dp_redeploy", "Idle assets redeployed before disposal"),
                            ("dp_close", "Records and books closed on disposal")])]


def _cols(c, t):
    try:
        return {r[1] for r in c.execute("PRAGMA table_info(%s)" % t)}
    except Exception:
        return set()


def _has(c, t):
    return bool(c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (t,)).fetchone())


def init_life(c):
    c.executescript(SCHEMA)
    for t, cols in COLUMNS.items():
        have = _cols(c, t)
        for k, typ in cols.items():
            if have and k not in have:
                c.execute("ALTER TABLE %s ADD COLUMN %s %s" % (t, k, typ))
    for k, v in (("class_rules", json.dumps(DEFAULT_RULES)), ("marr_pct", "12"), ("repair_trend_pct", "30"),
                 ("salvage_decline_pct", "12"), ("repair_factor_pct", "2")):
        c.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", (k, v))


def _f(x, d=0.0):
    try:
        return float(x) if x not in (None, "") else d
    except (TypeError, ValueError):
        return d


def _class_of(c, eq_id):
    if not _has(c, "fa_register"):
        return None
    r = q1(c, "SELECT abc_class FROM fa_register WHERE kind='equipment' AND ref_id=?", (eq_id,))
    return (r or {}).get("abc_class")


def rules(c):
    try:
        r = json.loads(setting(c, "class_rules") or "{}")
    except ValueError:
        r = {}
    out = json.loads(json.dumps(DEFAULT_RULES))
    for k, v in r.items():
        out.setdefault(k, {}).update(v)
    return out


# ───────────────────────── 4.1 business case ─────────────────────────
@api("life.demand", "equipment", "view")
def life_demand(c, u, a):
    """Machine demand from the resource-loaded schedules (Schedule & WBS > Resources): hours still to work
    per machine type across active projects, the span in months and the hours a year it implies."""
    if not _has(c, "act_resources"):
        return []
    rows = q(c, "SELECT r.ref, r.name, r.unit, SUM(r.qty_total*(1-MIN(1.0,COALESCE(a.actual_qty,0)/NULLIF(a.planned_qty,0)))) hrs, "
                "MIN(COALESCE(a.es,a.planned_start)) s, MAX(COALESCE(a.ef,a.planned_finish)) f FROM act_resources r JOIN activities a ON "
                "a.id=r.activity_id JOIN projects p ON p.id=a.project_id WHERE r.kind='E' AND p.status='active' AND a.actual_finish IS NULL "
                "GROUP BY r.ref ORDER BY hrs DESC")
    have = {}
    for e in q(c, "SELECT category, COUNT(*) n FROM equipment WHERE active=1 AND status<>'disposed' AND ownership='owned' GROUP BY category"):
        have[(e["category"] or "").lower()] = e["n"]
    out = []
    for r in rows:
        if not r["hrs"] or not r["s"] or not r["f"]:
            continue
        months = max(1.0, (date.fromisoformat(r["f"]) - date.fromisoformat(r["s"])).days / 30.4)
        hrs = r["hrs"] * (8 if (r["unit"] or "").lower() in ("day", "days") else 1)
        out.append({"ref": r["ref"], "name": r["name"], "hours": r2(hrs), "from": r["s"], "to": r["f"], "months": round(months, 1),
                    "hours_year": r2(hrs / months * 12), "owned": have.get((r["name"] or "").lower(), 0)})
    return out


def _case_calc(c, x):
    inp = json.loads(x.get("inputs") or "{}") if isinstance(x.get("inputs"), str) else (x.get("inputs") or {})
    p = {"hours_year": _f(x.get("hours_year")), "years": int(_f(x.get("years"), 5)), "marr": _f(x.get("marr"), 12) / 100,
         "buy": inp.get("buy") or {}, "hire": inp.get("hire") or {}, "lease": inp.get("lease") or {}}
    res = F.buy_hire_lease(p)
    lik, con = int(_f(x.get("risk_likelihood"), 0)), int(_f(x.get("risk_consequence"), 0))
    score = lik * con
    level = None if not score else ("high" if score >= 15 else "medium" if score >= 8 else "low")
    best = res[0] if res else None
    hire = next((r for r in res if r["option"] == "Hire"), None)
    savings = r2(hire["annual_cost"] - best["annual_cost"]) if best and hire and best["option"] != "Hire" else 0.0
    return {"options": res, "best": best["option"] if best else None, "risk_score": score, "risk_level": level,
            "savings_year": savings}


@api("life.case_list", "equipment", "view")
def case_list(c, u, a):
    rows = q(c, "SELECT * FROM asset_cases ORDER BY id DESC")
    for r in rows:
        r["result"] = json.loads(r["result"] or "{}")
        r["inputs"] = json.loads(r["inputs"] or "{}")
        r["actual"] = case_actual(c, r) if r.get("equipment_id") else None
    return rows


def case_actual(c, r):
    """After purchase: what the machine really cost over the last 12 months against hiring for the same hours."""
    eq_id = r["equipment_id"]
    to = today()
    frm = (date.today() - timedelta(days=365)).isoformat()
    hours = val(c, "SELECT SUM(hours) FROM logsheets WHERE equipment_id=? AND date BETWEEN ? AND ?", (eq_id, frm, to))
    cost = sum(x["amt"] or 0 for x in ER.eq_costs(c, eq_id, frm, to) if x["role"] != "equipment_recovery")
    hire_rate = _f(((r.get("inputs") or {}).get("hire") or {}).get("rate_hour"))
    hire_eq = hours * hire_rate
    return {"hours": r2(hours), "cost": r2(cost), "hire_equivalent": r2(hire_eq), "actual_savings": r2(hire_eq - cost),
            "promised_savings": r["savings_year"]}


@api("life.case_save", "equipment", "edit")
def case_save(c, u, a):
    r = a.get("row") or {}
    need(r, "title")
    data = {k: r.get(k) or None for k in ("date", "title", "category", "need", "chosen", "risk_note", "remarks")}
    data["project_id"] = int(r["project_id"]) if r.get("project_id") else None
    for k in ("hours_year", "marr"):
        data[k] = _f(r.get(k)) if r.get(k) not in (None, "") else None
    data["years"] = int(_f(r.get("years"), 5))
    data["risk_likelihood"] = int(_f(r.get("risk_likelihood"))) or None
    data["risk_consequence"] = int(_f(r.get("risk_consequence"))) or None
    data["inputs"] = json.dumps(r.get("inputs") or {})
    res = _case_calc(c, dict(data))
    data["result"] = json.dumps(res)
    data["savings_year"] = res["savings_year"]
    data["chosen"] = data.get("chosen") or res["best"]
    if r.get("id"):
        old = get(c, "asset_cases", int(r["id"]), "Business case")
        if old["status"] in ("approved", "rejected") and not r.get("equipment_id"):
            raise ApiError("This business case is %s; copy it to change it." % old["status"])
        if r.get("equipment_id"):
            data["equipment_id"] = int(r["equipment_id"])
        upd(c, "asset_cases", old["id"], data)
        cid = old["id"]
    else:
        data.update({"no": next_no(c, "BC", data.get("date") or today()), "date": data.get("date") or today(), "status": "draft",
                     "created_by": u["id"]})
        cid = ins(c, "asset_cases", data)
        for k, _l in ACQ_STEPS:
            ins(c, "asset_acq", {"case_id": cid, "step": k, "done": 0})
    audit(c, u, "save", "asset_cases", cid, {"best": res["best"]})
    return {"id": cid, "result": res}


@api("life.case_decide", "equipment", "approve")
def case_decide(c, u, a):
    x = get(c, "asset_cases", int(a["id"]), "Business case")
    st = a.get("status")
    if st not in ("submitted", "approved", "rejected", "draft"):
        raise ApiError("Unknown decision.")
    if st in ("approved", "rejected") and x["created_by"] == u["id"] and u.get("role") != "admin":
        raise ApiError("Another person must approve a business case you prepared.")
    upd(c, "asset_cases", x["id"], {"status": st, "decided_by": u["id"] if st in ("approved", "rejected") else None,
                                    "decided_on": today() if st in ("approved", "rejected") else None})
    audit(c, u, st, "asset_cases", x["id"], a.get("reason"))
    return True


@api("life.calc", "equipment", "view")
def life_calc(c, u, a):
    return _case_calc(c, a.get("row") or {})


# ───────────────────────── 4.2 acquisition file ─────────────────────────
@api("life.acq_get", "equipment", "view")
def acq_get(c, u, a):
    w, p = ("case_id=?", int(a["case_id"])) if a.get("case_id") else ("equipment_id=?", int(a["equipment_id"]))
    rows = q(c, "SELECT * FROM asset_acq WHERE " + w + " ORDER BY id", (p,))
    if not rows and a.get("equipment_id"):
        for k, _l in ACQ_STEPS:
            ins(c, "asset_acq", {"equipment_id": int(a["equipment_id"]), "step": k, "done": 0})
        rows = q(c, "SELECT * FROM asset_acq WHERE equipment_id=? ORDER BY id", (int(a["equipment_id"]),))
    lab = dict(ACQ_STEPS)
    for r in rows:
        r["label"] = lab.get(r["step"], r["step"])
    return {"steps": rows, "done": sum(1 for r in rows if r["done"]), "total": len(rows)}


@api("life.acq_save", "equipment", "edit")
def acq_save(c, u, a):
    r = a.get("row") or {}
    s = get(c, "asset_acq", int(r["id"]), "Step")
    upd(c, "asset_acq", s["id"], {"date": r.get("date") or None, "ref": r.get("ref"), "done": 1 if str(r.get("done")) in ("1", "true") else 0,
                                  "supplier": r.get("supplier"), "vetted": 1 if str(r.get("vetted")) in ("1", "true") else 0,
                                  "notes": r.get("notes"), "user_id": u["id"]})
    return True


# ───────────────────────── 4.3 point inspection & violations ─────────────────────────
_orig_checks = inv.FUNCS.get("book.checks")


def book_checks(c, u, a):
    ensure(c)
    res = _orig_checks[0](c, u, a)
    b = get(c, "logbooks", int(a["id"]))
    made = []
    for r in a.get("checks") or []:
        if (r.get("result") or "") != "repair" or r.get("clear"):
            continue
        item = (r.get("item") or "").strip()
        ref = "%s|%s" % (r.get("date"), item)
        if q1(c, "SELECT id FROM work_orders WHERE equipment_id=? AND source='point_inspection' AND source_ref=?", (b["equipment_id"], ref)):
            continue
        wid = ins(c, "work_orders", {"no": next_no(c, "WO", today()), "equipment_id": b["equipment_id"], "project_id": b["project_id"],
                                     "type": "inspection", "status": "open", "reported_at": (r.get("date") or today()) + "T08:00:00",
                                     "description": "Daily point inspection failed: %s%s" % (item, (" — " + r["remarks"]) if r.get("remarks") else ""),
                                     "created_by": u["id"], "source": "point_inspection", "source_ref": ref})
        made.append(wid)
    if made:
        res["work_orders"] = len(made)
    return res


if _orig_checks:
    inv.FUNCS["book.checks"] = (book_checks, _orig_checks[1], _orig_checks[2], _orig_checks[3])


@api("life.inspections", "equipment", "view")
def inspections(c, u, a):
    frm = a.get("from") or (date.today() - timedelta(days=30)).isoformat()
    to = a.get("to") or today()
    out = []
    for e in q(c, "SELECT id, code, name, category, operator FROM equipment WHERE active=1 AND status<>'disposed' ORDER BY code"):
        worked = {r["date"] for r in q(c, "SELECT DISTINCT date FROM logsheets WHERE equipment_id=? AND hours>0 AND date BETWEEN ? AND ?",
                                       (e["id"], frm, to))}
        checked = {r["date"] for r in q(c, "SELECT DISTINCT date FROM log_checks WHERE equipment_id=? AND date BETWEEN ? AND ?",
                                        (e["id"], frm, to))} if _has(c, "log_checks") else set()
        flagged = val(c, "SELECT COUNT(*) FROM log_checks WHERE equipment_id=? AND date BETWEEN ? AND ? AND result IN ('repair','low')",
                      (e["id"], frm, to)) if _has(c, "log_checks") else 0
        wos = val(c, "SELECT COUNT(*) FROM work_orders WHERE equipment_id=? AND source='point_inspection' AND substr(reported_at,1,10) "
                     "BETWEEN ? AND ?", (e["id"], frm, to))
        if not worked and not checked:
            continue
        out.append({"id": e["id"], "code": e["code"], "name": e["name"], "operator": e["operator"], "days_worked": len(worked),
                    "days_checked": len(worked & checked), "missed": sorted(worked - checked)[-10:],
                    "compliance_pct": round(100 * len(worked & checked) / len(worked), 1) if worked else None,
                    "flagged": flagged, "work_orders": wos})
    out.sort(key=lambda r: (r["compliance_pct"] if r["compliance_pct"] is not None else 101))
    return {"from": frm, "to": to, "rows": out}


@api("life.viol_list", "equipment", "view")
def viol_list(c, u, a):
    rows = q(c, "SELECT * FROM operator_violations ORDER BY date DESC, id DESC LIMIT 500")
    by = {}
    for r in rows:
        k = r["operator"] or "—"
        x = by.setdefault(k, {"operator": k, "count": 0, "penalty": 0.0})
        x["count"] += 1
        x["penalty"] += r["penalty"] or 0
    return {"rows": rows, "by_operator": sorted(by.values(), key=lambda x: -x["count"])}


@api("life.viol_save", "equipment", "edit")
def viol_save(c, u, a):
    r = a.get("row") or {}
    need(r, "operator", "violation")
    data = {"date": r.get("date") or today(), "equipment_id": int(r["equipment_id"]) if r.get("equipment_id") else None,
            "operator": r["operator"], "violation": r["violation"], "penalty": _f(r.get("penalty")), "action": r.get("action"),
            "remarks": r.get("remarks"), "user_id": u["id"]}
    if r.get("id"):
        upd(c, "operator_violations", int(r["id"]), data)
        return {"id": int(r["id"])}
    return {"id": ins(c, "operator_violations", data)}


@api("life.viol_delete", "equipment", "approve")
def viol_delete(c, u, a):
    c.execute("DELETE FROM operator_violations WHERE id=?", (int(a["id"]),))
    return True


# ───────────────────────── 4.4 breakdowns and reliability ─────────────────────────
def _ld_for(c, project_id):
    if not project_id or "ld_per_day" not in _cols(c, "projects"):
        return 0.0
    p = q1(c, "SELECT ld_per_day FROM projects WHERE id=?", (project_id,))
    return _f((p or {}).get("ld_per_day"))


@api("life.wo_code", "equipment", "edit")
def wo_code(c, u, a):
    """Code a breakdown and work out its downtime cost: idle crew + idle linked machines, plus LD
    exposure when the machine was working on a critical activity."""
    w = get(c, "work_orders", int(a["id"]), "Work order")
    crew = _f(a.get("idle_crew"))
    rate = _f(a.get("crew_rate_hour"))
    if not rate:
        rate = val(c, "SELECT AVG(rate_hour) FROM trades WHERE active=1") or 0
    linked = _f(a.get("idle_linked_cost_hour"))
    hours = w["downtime_hours"] or _f(a.get("downtime_hours"))
    act = int(a["activity_id"]) if a.get("activity_id") else None
    if not act:
        lg = q1(c, "SELECT activity_id FROM logsheets WHERE equipment_id=? AND activity_id IS NOT NULL AND date<=? ORDER BY date DESC LIMIT 1",
                (w["equipment_id"], (w["reported_at"] or today())[:10]))
        act = (lg or {}).get("activity_id")
    ld = 0.0
    if act:
        x = q1(c, "SELECT critical, project_id FROM activities WHERE id=?", (act,))
        if x and x["critical"]:
            shift = float(setting(c, "shift_hours") or 10)
            ld = _ld_for(c, x["project_id"]) * hours / shift
    cost = hours * (crew * rate + linked) + ld
    upd(c, "work_orders", w["id"], {"failure_code": a.get("failure_code"), "cause_detail": a.get("cause_detail"), "idle_crew": crew,
                                    "crew_rate_hour": r2(rate), "idle_linked_cost_hour": linked, "activity_id": act,
                                    "ld_applied": r2(ld), "downtime_cost": r2(cost)})
    audit(c, u, "code", "work_orders", w["id"], {"failure_code": a.get("failure_code"), "cost": cost})
    return {"downtime_cost": r2(cost), "ld": r2(ld)}


@api("life.reliability", "equipment", "view")
def reliability(c, u, a):
    """MTBF = operating hours / failures, MTTR = repair hours / failures, availability = MTBF / (MTBF + MTTR),
    per machine, per ABC class and per category, with the failure-code Pareto and downtime cost."""
    frm = a.get("from") or (date.today() - timedelta(days=365)).isoformat()
    to = a.get("to") or today()
    lab = dict(FAILURE_CODES)
    rows = []
    for e in q(c, "SELECT * FROM equipment WHERE active=1 ORDER BY code"):
        hrs = val(c, "SELECT SUM(hours) FROM logsheets WHERE equipment_id=? AND date BETWEEN ? AND ?", (e["id"], frm, to))
        wos = q(c, "SELECT * FROM work_orders WHERE equipment_id=? AND type='breakdown' AND status='completed' AND "
                   "substr(completed_at,1,10) BETWEEN ? AND ?", (e["id"], frm, to))
        if not hrs and not wos:
            continue
        n = len(wos)
        rep = sum(w["downtime_hours"] or 0 for w in wos)
        mtbf = hrs / n if n else None
        mttr = rep / n if n else None
        rows.append({"id": e["id"], "code": e["code"], "name": e["name"], "category": e["category"], "class": _class_of(c, e["id"]),
                     "hours": r2(hrs), "failures": n, "repair_hours": r2(rep), "mtbf": r2(mtbf) if mtbf is not None else None,
                     "mttr": r2(mttr) if mttr is not None else None,
                     "availability": round(100 * mtbf / (mtbf + mttr), 1) if mtbf is not None and (mtbf + mttr) > 0 else (100.0 if hrs else None),
                     "downtime_cost": r2(sum(w["downtime_cost"] or 0 for w in wos)),
                     "uncoded": sum(1 for w in wos if not w["failure_code"])})

    def roll(key):
        out = {}
        for r in rows:
            k = r[key] or "—"
            g = out.setdefault(k, {"key": k, "machines": 0, "hours": 0.0, "failures": 0, "repair_hours": 0.0, "downtime_cost": 0.0})
            g["machines"] += 1
            for f in ("hours", "failures", "repair_hours", "downtime_cost"):
                g[f] += r[f] or 0
        res = []
        for g in out.values():
            mtbf = g["hours"] / g["failures"] if g["failures"] else None
            mttr = g["repair_hours"] / g["failures"] if g["failures"] else None
            g.update({"mtbf": r2(mtbf) if mtbf is not None else None, "mttr": r2(mttr) if mttr is not None else None,
                      "availability": round(100 * mtbf / (mtbf + mttr), 1) if mtbf is not None and (mtbf + mttr) else None,
                      "hours": r2(g["hours"]), "repair_hours": r2(g["repair_hours"]), "downtime_cost": r2(g["downtime_cost"])})
            res.append(g)
        return sorted(res, key=lambda g: -g["failures"])
    codes = q(c, "SELECT COALESCE(failure_code,'uncoded') code, COUNT(*) n, SUM(downtime_hours) h, SUM(COALESCE(downtime_cost,0)) cost "
                 "FROM work_orders WHERE type='breakdown' AND status='completed' AND substr(completed_at,1,10) BETWEEN ? AND ? GROUP BY code "
                 "ORDER BY n DESC", (frm, to))
    tot = sum(x["n"] for x in codes) or 1
    acc = 0
    for x in codes:
        acc += x["n"]
        x["label"] = lab.get(x["code"], "Not coded yet" if x["code"] == "uncoded" else x["code"])
        x["cum_pct"] = round(100 * acc / tot, 1)
    open_wo = q(c, "SELECT w.*, e.code eq_code, e.name eq_name FROM work_orders w JOIN equipment e ON e.id=w.equipment_id WHERE "
                   "w.type='breakdown' AND w.failure_code IS NULL ORDER BY w.id DESC LIMIT 200")
    return {"from": frm, "to": to, "rows": rows, "by_class": roll("class"), "by_category": roll("category"), "codes": codes,
            "uncoded": open_wo, "failure_codes": FAILURE_CODES}


# ───────────────────────── 4.5 class rules, spares, safety checks ─────────────────────────
@api("life.class_status", "equipment", "view")
def class_status(c, u, a):
    R = rules(c)
    out = []
    for e in q(c, "SELECT * FROM equipment WHERE active=1 AND status<>'disposed' AND ownership='owned' ORDER BY code"):
        k = _class_of(c, e["id"]) or "C"
        rule = R.get(k, R["C"])
        last = q1(c, "SELECT * FROM safety_checks WHERE equipment_id=? ORDER BY date DESC LIMIT 1", (e["id"],))
        due = (date.fromisoformat(last["date"]) + timedelta(days=int(rule["safety_cycle_days"]))).isoformat() if last else today()
        issues = []
        if rule.get("operator_cert") and not e.get("operator_cert_no"):
            issues.append("operator certificate missing")
        if rule.get("operator_cert") and e.get("operator_cert_expiry") and e["operator_cert_expiry"] < today():
            issues.append("operator certificate expired")
        if rule.get("responsible") and not e.get("responsible_person"):
            issues.append("no named person responsible")
        if due < today():
            issues.append("safety check overdue since %s" % due)
        spares = q(c, "SELECT s.*, m.code, m.name, m.min_level FROM equipment_spares s JOIN materials m ON m.id=s.material_id "
                      "WHERE s.equipment_id=?", (e["id"],))
        short = []
        for s in spares:
            need_ = (s["qty"] or 0) * rule.get("spare_reserve_pct", 0) / 100
            have = val(c, "SELECT SUM(qty) FROM stock_balances WHERE material_id=?", (s["material_id"],))
            if have + EPS < need_:
                short.append("%s %s/%s" % (s["code"], r2(have), r2(need_)))
        if short:
            issues.append("spares below reserve: " + ", ".join(short[:3]))
        out.append({"id": e["id"], "code": e["code"], "name": e["name"], "class": k, "operator": e["operator"],
                    "operator_cert_no": e.get("operator_cert_no"), "operator_cert_expiry": e.get("operator_cert_expiry"),
                    "responsible_person": e.get("responsible_person"), "last_safety": last["date"] if last else None,
                    "safety_due": due, "spares": len(spares), "issues": issues})
    out.sort(key=lambda r: ({"A": 0, "B": 1}.get(r["class"], 2), -len(r["issues"])))
    return {"rows": out, "rules": R}


@api("life.rules_save", "equipment", "approve")
def rules_save(c, u, a):
    R = rules(c)
    for k, v in (a.get("rules") or {}).items():
        R.setdefault(k, {}).update({kk: _f(vv) for kk, vv in v.items()})
    c.execute("INSERT INTO settings(key,value) VALUES('class_rules',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
              (json.dumps(R),))
    return R


@api("life.eq_save", "equipment", "edit")
def eq_save(c, u, a):
    r = a.get("row") or {}
    e = get(c, "equipment", int(r["id"]), "Equipment")
    upd(c, "equipment", e["id"], {k: r.get(k) or None for k in ("operator_cert_no", "operator_cert_expiry", "responsible_person",
                                                                  "location") if k in r})
    return True


@api("life.spares", "equipment", "view")
def spares_list(c, u, a):
    return q(c, "SELECT s.*, m.code, m.name, m.unit FROM equipment_spares s JOIN materials m ON m.id=s.material_id WHERE s.equipment_id=?",
             (int(a["equipment_id"]),))


@api("life.spare_save", "equipment", "edit")
def spare_save(c, u, a):
    r = a.get("row") or {}
    need(r, "equipment_id", "material_id")
    data = {"equipment_id": int(r["equipment_id"]), "material_id": int(r["material_id"]), "qty": _f(r.get("qty"), 1), "remarks": r.get("remarks")}
    if r.get("id"):
        upd(c, "equipment_spares", int(r["id"]), data)
        return {"id": int(r["id"])}
    return {"id": ins(c, "equipment_spares", data)}


@api("life.spare_delete", "equipment", "edit")
def spare_delete(c, u, a):
    c.execute("DELETE FROM equipment_spares WHERE id=?", (int(a["id"]),))
    return True


@api("life.spares_apply", "inventory", "edit")
def spares_apply(c, u, a):
    """Set each linked spare's minimum level to what the class rules say to hold in reserve for the machines."""
    R = rules(c)
    need_ = {}
    for s in q(c, "SELECT s.* FROM equipment_spares s JOIN equipment e ON e.id=s.equipment_id WHERE e.active=1 AND e.status<>'disposed'"):
        k = _class_of(c, s["equipment_id"]) or "C"
        need_[s["material_id"]] = need_.get(s["material_id"], 0) + (s["qty"] or 0) * R.get(k, R["C"]).get("spare_reserve_pct", 0) / 100
    for mid, qn in need_.items():
        m = q1(c, "SELECT reorder_level FROM materials WHERE id=?", (mid,))
        upd(c, "materials", mid, {"min_level": r4(qn), "reorder_level": max(r4(qn), (m or {}).get("reorder_level") or 0)})
    audit(c, u, "spare_reserve", "materials", None, {"updated": len(need_)})
    return {"updated": len(need_)}


@api("life.safety_save", "equipment", "edit")
def safety_save(c, u, a):
    r = a.get("row") or {}
    need(r, "equipment_id")
    ins(c, "safety_checks", {"equipment_id": int(r["equipment_id"]), "date": r.get("date") or today(), "result": r.get("result") or "pass",
                             "checked_by": r.get("checked_by") or u.get("name"), "notes": r.get("notes")})
    if (r.get("result") or "pass") == "fail":
        e = get(c, "equipment", int(r["equipment_id"]))
        ins(c, "work_orders", {"no": next_no(c, "WO", today()), "equipment_id": e["id"], "project_id": e["project_id"], "type": "inspection",
                               "status": "open", "reported_at": now(), "description": "Safety check failed: %s" % (r.get("notes") or ""),
                               "created_by": u["id"], "source": "safety_check"})
    return True


# ───────────────────────── 4.6 spare-parts forecast ─────────────────────────
@api("life.spare_forecast", "equipment", "view")
def spare_forecast(c, u, a):
    """Monthly issues of spares to machines and work orders, forecast by exponential smoothing (alpha 0.3)
    and a 3-month moving average. Suggested minimum = forecast x lead time in months + one month."""
    months = int(a.get("months") or 12)
    k0 = date.today().replace(day=1)
    keys = []
    d = k0
    for _ in range(months):
        d = (d - timedelta(days=1)).replace(day=1)
        keys.append(d.isoformat()[:7])
    keys.reverse()
    rows = q(c, "SELECT l.material_id, substr(i.date,1,7) m, SUM(l.qty-l.returned_qty) qq FROM issue_lines l JOIN issues i ON i.id=l.issue_id "
                "JOIN materials mt ON mt.id=l.material_id WHERE i.status='posted' AND (l.equipment_id IS NOT NULL OR i.wo_id IS NOT NULL) AND "
                "lower(COALESCE(mt.category,'')) NOT LIKE '%fuel%' AND substr(i.date,1,7)>=? GROUP BY l.material_id, m", (keys[0],))
    by = {}
    for r in rows:
        by.setdefault(r["material_id"], {})[r["m"]] = r["qq"] or 0
    out = []
    for mid, hist in by.items():
        m = q1(c, "SELECT * FROM materials WHERE id=?", (mid,))
        if not m:
            continue
        series = [hist.get(k, 0) for k in keys]
        fc, _fit = F.exp_smooth(series, 0.3)
        ma = F.moving_avg(series, 3)
        lead_m = (m["lead_days"] or 14) / 30.0
        out.append({"material_id": mid, "code": m["code"], "name": m["name"], "unit": m["unit"], "history": [r2(x) for x in series],
                    "forecast_smoothing": r2(fc), "forecast_ma3": r2(ma), "total_12m": r2(sum(series)),
                    "suggested_min": r2(max(fc or 0, ma or 0) * (lead_m + 1)), "current_min": m["min_level"],
                    "stock": r2(val(c, "SELECT SUM(qty) FROM stock_balances WHERE material_id=?", (mid,)))})
    out.sort(key=lambda r: -r["total_12m"])
    return {"months": keys, "rows": out, "note": "Wang's neural-network forecast needs years of clean data; simple smoothing is used first."}


# ───────────────────────── 4.7 replacement and disposal ─────────────────────────
def _age_years(e):
    d = e.get("purchase_date")
    if not d:
        return None
    return (date.today() - date.fromisoformat(d[:10])).days / 365.25


@api("life.replacement_scan", "equipment", "view")
def replacement_scan(c, u, a):
    marr = _f(setting(c, "marr_pct"), 12) / 100
    decline = _f(setting(c, "salvage_decline_pct"), 12) / 100
    trend_pct = _f(setting(c, "repair_trend_pct"), 30)
    out = []
    for e in q(c, "SELECT * FROM equipment WHERE active=1 AND status<>'disposed' AND ownership='owned' ORDER BY code"):
        price = e["purchase_value"] or 0
        age = _age_years(e)
        k = _class_of(c, e["id"])
        triggers = []
        econ = None
        if price and age:
            # repairs grow with age (fuel and operator do not, so they do not move the economic life):
            # repair cost in year n = price x factor x n, the factor calibrated from the last 12 months when known
            frm12 = (date.today() - timedelta(days=365)).isoformat()
            rep12 = sum(x["amt"] or 0 for x in ER.eq_costs(c, e["id"], frm12, today())
                        if x["role"] in ("repair_cost", "inventory_spares", "maintenance_cost"))
            now_idx = max(1, int(round(age)))
            factor = rep12 / (price * now_idx) if rep12 > 0 else _f(setting(c, "repair_factor_pct"), 2) / 100
            factor = min(max(factor, 0.005), 0.25)
            horizon = max(12, int(age) + 6)
            om = [price * factor * n for n in range(1, horizon + 1)]
            salv = [price * (1 - decline) ** n for n in range(1, horizon + 1)]
            econ = F.economic_life(price, salv, om, marr)
            econ["repair_factor_pct"] = round(100 * factor, 2)
            if econ["economic_life"] and age >= econ["economic_life"]:
                triggers.append("economic life of about %d years reached (age %.1f)" % (econ["economic_life"], age))
        y1 = (date.today() - timedelta(days=365)).isoformat()
        y2 = (date.today() - timedelta(days=730)).isoformat()
        rep = lambda s, t: sum(x["amt"] or 0 for x in ER.eq_costs(c, e["id"], s, t) if x["role"] in ("repair_cost", "inventory_spares"))
        r_now, r_prev = rep(y1, today()), rep(y2, y1)
        if price and r_now > price * trend_pct / 100:
            triggers.append("repairs %s in 12 months = %.0f%% of the price" % (r2(r_now), 100 * r_now / price))
        if r_prev and r_now > r_prev * 1.5:
            triggers.append("repair cost up %.0f%% on the year before" % (100 * (r_now / r_prev - 1)))
        fails = val(c, "SELECT COUNT(*) FROM work_orders WHERE equipment_id=? AND type='breakdown' AND reported_at>=?",
                    (e["id"], (date.today() - timedelta(days=90)).isoformat()))
        if k == "A" and fails >= 3:
            triggers.append("%d breakdowns in 90 days on a class A machine" % fails)
        open_disp = q1(c, "SELECT id, no, status FROM asset_disposals WHERE equipment_id=? AND status NOT IN ('completed','cancelled')", (e["id"],))
        out.append({"id": e["id"], "code": e["code"], "name": e["name"], "class": k, "age": round(age, 1) if age else None,
                    "price": price, "repairs_12m": r2(r_now), "repairs_prev": r2(r_prev), "breakdowns_90d": fails,
                    "economic_life": econ["economic_life"] if econ else None, "min_euac": econ["min_euac"] if econ else None,
                    "euac": econ["rows"] if econ else [], "triggers": triggers, "disposal": open_disp})
    out.sort(key=lambda r: -len(r["triggers"]))
    return {"rows": out, "marr": marr * 100}


DISP_FLOW = ["proposed", "assessed", "applied", "evaluated", "approved", "completed"]


@api("life.disp_list", "equipment", "view")
def disp_list(c, u, a):
    return q(c, "SELECT d.*, e.code eq_code, e.name eq_name FROM asset_disposals d LEFT JOIN equipment e ON e.id=d.equipment_id "
                "ORDER BY d.id DESC")


@api("life.disp_save", "equipment", "edit")
def disp_save(c, u, a):
    r = a.get("row") or {}
    data = {k: r.get(k) for k in ("trigger", "assessment", "assessed_by", "application", "process", "method", "remarks") if k in r}
    for k in ("evaluation_value", "proceeds"):
        if k in r:
            data[k] = _f(r[k]) if r[k] not in (None, "") else None
    if r.get("id"):
        d = get(c, "asset_disposals", int(r["id"]), "Disposal")
        if d["status"] in ("completed", "cancelled"):
            raise ApiError("This disposal is closed.")
        upd(c, "asset_disposals", d["id"], data)
        return {"id": d["id"]}
    need(r, "equipment_id")
    data.update({"equipment_id": int(r["equipment_id"]), "no": next_no(c, "DSP", today()), "status": "proposed", "date": today(),
                 "created_by": u["id"]})
    return {"id": ins(c, "asset_disposals", data)}


@api("life.disp_advance", "equipment", "approve")
def disp_advance(c, u, a):
    """Move a disposal to its next stage (Wang: expert assessment -> scrap application -> evaluation ->
    approval -> sale or scrap). Completing it posts the disposal in Fixed assets when the machine is there."""
    d = get(c, "asset_disposals", int(a["id"]), "Disposal")
    if a.get("cancel"):
        upd(c, "asset_disposals", d["id"], {"status": "cancelled"})
        return {"status": "cancelled"}
    i = DISP_FLOW.index(d["status"]) if d["status"] in DISP_FLOW else 0
    if i >= len(DISP_FLOW) - 1:
        raise ApiError("Already completed.")
    nxt = DISP_FLOW[i + 1]
    needs = {"assessed": "assessment", "applied": "application", "evaluated": "evaluation_value"}
    if nxt in needs and not d.get(needs[nxt]):
        raise ApiError("Fill in the %s first." % needs[nxt].replace("_", " "))
    data = {"status": nxt}
    if nxt == "approved":
        if d["created_by"] == u["id"] and u.get("role") != "admin":
            raise ApiError("Another person must approve a disposal you proposed.")
        data.update({"approved_by": u["id"], "approved_on": today()})
    if nxt == "completed":
        method = a.get("method") or d.get("method") or "sale"
        proceeds = _f(a.get("proceeds"), _f(d.get("proceeds")))
        data.update({"completed_on": a.get("date") or today(), "method": method, "proceeds": proceeds})
        fa = q1(c, "SELECT id FROM fa_register WHERE kind='equipment' AND ref_id=? AND status<>'disposed'", (d["equipment_id"],)) \
            if _has(c, "fa_register") else None
        if fa and "fa.dispose" in inv.FUNCS:
            res = inv.FUNCS["fa.dispose"][0](c, u, {"id": fa["id"], "date": data["completed_on"], "proceeds": proceeds,
                                                   "costs_to_sell": _f(a.get("costs_to_sell"))})
            data["voucher_id"] = res.get("voucher_id")
        else:
            c.execute("UPDATE equipment SET status='disposed' WHERE id=?", (d["equipment_id"],))
    upd(c, "asset_disposals", d["id"], data)
    audit(c, u, "disposal_" + nxt, "asset_disposals", d["id"], data)
    return {"status": nxt}


# ───────────────────────── 4.8 QR tags and verification ─────────────────────────
@api("life.tags", "equipment", "view")
def tags(c, u, a):
    out = [{"kind": "eq", "id": e["id"], "code": e["code"], "name": e["name"], "extra": e["reg_no"] or e["serial"] or ""}
           for e in q(c, "SELECT * FROM equipment WHERE active=1 AND status<>'disposed' ORDER BY code")]
    if _has(c, "assets"):
        out += [{"kind": "as", "id": x["id"], "code": x["code"], "name": x["name"], "extra": x.get("location") or ""}
                for x in q(c, "SELECT * FROM assets WHERE COALESCE(status,'active')<>'disposed' ORDER BY code")]
    return out


@api("life.lookup")
def lookup(c, u, a):
    kind, code = a.get("kind"), (a.get("code") or "").strip()
    if kind == "eq":
        e = q1(c, "SELECT id, code, name, category, reg_no, serial, status, project_id, location, operator FROM equipment WHERE code=?", (code,))
    else:
        e = q1(c, "SELECT id, code, name, category, location, custodian, project_id, status FROM assets WHERE code=?", (code,)) \
            if _has(c, "assets") else None
    if not e:
        raise ApiError("No %s with code %s." % ("machine" if kind == "eq" else "asset", code))
    rnd = q1(c, "SELECT * FROM verify_rounds WHERE status='open' ORDER BY id DESC LIMIT 1")
    seen = q1(c, "SELECT * FROM verify_items WHERE round_id=? AND kind=? AND ref_id=?", (rnd["id"], kind, e["id"])) if rnd else None
    return {"record": e, "kind": kind, "round": rnd, "seen": seen}


@api("life.rounds", "assets", "view")
def rounds(c, u, a):
    rs = q(c, "SELECT * FROM verify_rounds ORDER BY id DESC")
    total = len(tags(c, u, {}))
    for r in rs:
        r["found"] = val(c, "SELECT COUNT(*) FROM verify_items WHERE round_id=? AND found=1", (r["id"],))
        r["missing_marked"] = val(c, "SELECT COUNT(*) FROM verify_items WHERE round_id=? AND found=0", (r["id"],))
        r["total"] = total
    return rs


@api("life.round_save", "assets", "edit")
def round_save(c, u, a):
    r = a.get("row") or {}
    if r.get("id"):
        upd(c, "verify_rounds", int(r["id"]), {k: r[k] for k in ("name", "status", "remarks") if k in r})
        return {"id": int(r["id"])}
    c.execute("UPDATE verify_rounds SET status='closed' WHERE status='open'")
    return {"id": ins(c, "verify_rounds", {"name": r.get("name") or "Verification %s" % today(), "date": today(), "status": "open",
                                           "remarks": r.get("remarks")})}


@api("life.scan", "equipment", "view")
def scan(c, u, a):
    """Record that a tagged item was seen (from the phone page opened by the QR code)."""
    rnd = q1(c, "SELECT * FROM verify_rounds WHERE id=?", (int(a["round_id"]),)) if a.get("round_id") else \
        q1(c, "SELECT * FROM verify_rounds WHERE status='open' ORDER BY id DESC LIMIT 1")
    if not rnd or rnd["status"] != "open":
        raise ApiError("Start a verification round first (Equipment > Register > QR tags & verification).")
    kind = a.get("kind")
    rid = int(a["ref_id"])
    data = {"round_id": rnd["id"], "kind": kind, "ref_id": rid, "found": 0 if str(a.get("found")) in ("0", "false") else 1,
            "location": a.get("location"), "condition": a.get("condition"), "notes": a.get("notes"), "by": u.get("name"), "ts": now()}
    ex = q1(c, "SELECT id FROM verify_items WHERE round_id=? AND kind=? AND ref_id=?", (rnd["id"], kind, rid))
    if ex:
        upd(c, "verify_items", ex["id"], data)
    else:
        ins(c, "verify_items", data)
    if kind == "eq" and a.get("location") and "location" in _cols(c, "equipment"):
        c.execute("UPDATE equipment SET location=?, last_seen=? WHERE id=?", (a["location"], now(), rid))
    return {"ok": True, "round": rnd["name"]}


@api("life.round_report", "assets", "view")
def round_report(c, u, a):
    rnd = get(c, "verify_rounds", int(a["id"]), "Round")
    items = {(x["kind"], x["ref_id"]): x for x in q(c, "SELECT * FROM verify_items WHERE round_id=?", (rnd["id"],))}
    rows = []
    for t in tags(c, u, {}):
        v = items.get((t["kind"], t["id"]))
        rows.append(dict(t, found=(v or {}).get("found"), location=(v or {}).get("location"), condition=(v or {}).get("condition"),
                         by=(v or {}).get("by"), ts=(v or {}).get("ts"),
                         state="found" if v and v["found"] else ("missing" if v else "not scanned")))
    return {"round": rnd, "rows": rows, "found": sum(1 for r in rows if r["state"] == "found"),
            "discrepancies": [r for r in rows if r["state"] != "found"]}


# ───────────────────────── 4.9 telematics import ─────────────────────────
@api("life.telematics", "equipment", "edit")
def telematics(c, u, a):
    """CSV from an OEM telematics portal: code, date, engine hours for the day (or closing hour meter),
    fuel litres, latitude, longitude, location. Creates draft day logs (approve them as usual) and
    moves the machine's location."""
    made, skipped = 0, []
    for i, line in enumerate((a.get("text") or "").splitlines()):
        p = [x.strip() for x in line.replace(";", ",").replace("\t", ",").split(",")]
        if not p or not p[0] or p[0].lower() in ("code", "equipment", "machine"):
            continue
        e = q1(c, "SELECT * FROM equipment WHERE code=?", (p[0],))
        if not e:
            skipped.append("line %d: machine %s not found" % (i + 1, p[0]))
            continue
        d = p[1] if len(p) > 1 else today()
        try:
            date.fromisoformat(d)
        except ValueError:
            skipped.append("line %d: date %s" % (i + 1, d))
            continue
        hours = _f(p[2] if len(p) > 2 else 0)
        mode = a.get("hours_mode") or "hours"
        row = {"equipment_id": e["id"], "project_id": e["project_id"], "date": d, "work": "Telematics import"}
        if not e["project_id"]:
            skipped.append("line %d: %s is not on a project" % (i + 1, e["code"]))
            continue
        if mode == "meter":
            prev = val(c, "SELECT MAX(meter_end) FROM logsheets WHERE equipment_id=? AND date<?", (e["id"], d)) or e["meter"] or 0
            row.update({"meter_start": prev, "meter_end": hours})
        else:
            row["hours"] = hours
        if q1(c, "SELECT id FROM logsheets WHERE equipment_id=? AND date=?", (e["id"], d)):
            skipped.append("line %d: %s already has a log on %s" % (i + 1, e["code"], d))
            continue
        try:
            r = ER.save_log(c, u, row)
            if len(p) > 3 and p[3] and "fuel_qty" in _cols(c, "logsheets"):
                c.execute("UPDATE logsheets SET fuel_qty=? WHERE id=?", (_f(p[3]), r["id"]))
            made += 1
        except ApiError as ex:
            skipped.append("line %d: %s" % (i + 1, ex))
            continue
        loc = {}
        if len(p) > 5 and p[4] and p[5]:
            loc.update({"lat": _f(p[4]), "lon": _f(p[5])})
        if len(p) > 6 and p[6]:
            loc["location"] = p[6]
        if loc:
            loc["last_seen"] = d
            upd(c, "equipment", e["id"], loc)
    audit(c, u, "telematics", "logsheets", None, {"created": made})
    return {"created": made, "skipped": skipped}


# ───────────────────────── 4.10 maturity ─────────────────────────
@api("life.maturity", "assets", "view")
def maturity(c, u, a):
    year = str(a.get("year") or date.today().year)
    got = {r["qkey"]: r for r in q(c, "SELECT * FROM maturity_checks WHERE year=?", (year,))}
    stages = []
    for k, label, qs in MATURITY:
        items = [{"key": qk, "question": qt, "score": (got.get(qk) or {}).get("score"), "note": (got.get(qk) or {}).get("note")} for qk, qt in qs]
        sc = [x["score"] for x in items if x["score"]]
        stages.append({"key": k, "label": label, "items": items, "mean": round(sum(sc) / len(sc), 2) if sc else None})
    hist = q(c, "SELECT year, stage, AVG(score) m FROM maturity_checks GROUP BY year, stage ORDER BY year")
    return {"year": year, "stages": stages, "history": hist,
            "scale": [[1, "Not done"], [2, "Done sometimes"], [3, "Done usually"], [4, "Always done and recorded"]],
            "note": "Bajet & Manalo (2025) found firms weakest at detailed financial evaluation, failure-risk analysis and savings summaries."}


@api("life.maturity_save", "assets", "edit")
def maturity_save(c, u, a):
    year = str(a.get("year") or date.today().year)
    stage_of = {qk: k for k, _l, qs in MATURITY for qk, _q in qs}
    for qk, v in (a.get("scores") or {}).items():
        if qk not in stage_of:
            continue
        c.execute("INSERT INTO maturity_checks(year,stage,qkey,score,note) VALUES(?,?,?,?,?) ON CONFLICT(year,qkey) DO UPDATE SET "
                  "score=excluded.score, note=excluded.note", (year, stage_of[qk], qk, int(_f(v.get("score") if isinstance(v, dict) else v)) or None,
                                                               v.get("note") if isinstance(v, dict) else None))
    return True


# ───────────────────────── 3.13 / 3.14 decision tools ─────────────────────────
@api("life.tvm", "assets", "view")
def tvm(c, u, a):
    i = _f(a.get("i")) / 100
    n = int(_f(a.get("n")))
    op = a.get("op")
    p, f_, am = _f(a.get("p")), _f(a.get("f")), _f(a.get("a"))
    out = {"factors": {"F/P": F.fp(i, n), "P/F": F.pf(i, n), "A/P": F.ap(i, n), "P/A": F.pa(i, n), "A/F": F.af(i, n) if n else None,
                       "F/A": F.fa(i, n)}}
    if op == "P2F":
        out["answer"] = p * F.fp(i, n)
    elif op == "F2P":
        out["answer"] = f_ * F.pf(i, n)
    elif op == "A2P":
        out["answer"] = am * F.pa(i, n)
    elif op == "P2A":
        out["answer"] = p * F.ap(i, n)
    elif op == "A2F":
        out["answer"] = am * F.fa(i, n)
    elif op == "F2A":
        out["answer"] = f_ * F.af(i, n)
    elif op == "rate":
        r = F.solve_rate(p, f_, n)
        out["answer"] = r * 100 if r is not None else None
    elif op == "series":
        flows = [_f(x) for x in (a.get("flows") or [])]
        out["answer"] = F.npv(i, flows)
    elif op == "real":
        out["answer"] = F.real_rate(i, _f(a.get("inflation")) / 100) * 100
    out["answer"] = r2(out.get("answer")) if out.get("answer") is not None else None
    out["factors"] = {k: (round(v, 5) if v is not None else None) for k, v in out["factors"].items()}
    return out


@api("life.decide", "assets", "view")
def decide(c, u, a):
    """The ten methods on each alternative's cash flows (period 0 = now), sunk costs left out by the user,
    with incremental analysis between each pair in order of first cost."""
    marr = _f(a.get("marr"), _f(setting(c, "marr_pct"), 12)) / 100
    alts = []
    for x in a.get("alternatives") or []:
        fl = [_f(v) for v in (x.get("flows") or [])]
        if not fl:
            continue
        e = F.evaluate(fl, marr)
        alts.append({"name": x.get("name") or "Option", "flows": fl, "npv": r2(e["npv"]), "fw": r2(e["fw"]), "ae": r2(e["ae"]),
                     "irr": round(e["irr"] * 100, 2) if e["irr"] is not None else None, "payback": round(e["payback"], 2) if e["payback"] is not None else None,
                     "discounted_payback": round(e["discounted_payback"], 2) if e["discounted_payback"] is not None else None,
                     "capital_recovery": r2(F.capital_recovery(-fl[0], fl[-1] if len(fl) > 1 and fl[-1] > 0 else 0, marr, len(fl) - 1)) if fl[0] < 0 and len(fl) > 1 else None,
                     "project_balance": [r2(v) for v in e["project_balance"]]})
    inc = []
    srt = sorted(alts, key=lambda x: -x["flows"][0])
    for x, y in zip(srt, srt[1:]):
        r = F.incremental(x["flows"], y["flows"], marr)
        inc.append({"from": x["name"], "to": y["name"], "npv": r2(r["npv"]), "irr": round(r["irr"] * 100, 2) if r["irr"] is not None else None,
                    "choose": y["name"] if r["choose"] == "B" else x["name"]})
    best = max(alts, key=lambda x: x["npv"])["name"] if alts else None
    return {"marr": marr * 100, "alternatives": alts, "incremental": inc, "best": best,
            "note": "Leave out sunk costs; use the same study period for every option (add a salvage value at the end if lives differ)."}


@api("life.bhl", "equipment", "view")
def bhl(c, u, a):
    return {"options": F.buy_hire_lease(a)}


@api("life.econ_life", "equipment", "view")
def econ_life(c, u, a):
    price = _f(a.get("price"))
    salv = [_f(x) for x in (a.get("salvages") or [])]
    om = [_f(x) for x in (a.get("om") or [])]
    return F.economic_life(price, salv, om, _f(a.get("marr"), 12) / 100)


@api("life.options", "equipment", "view")
def life_options(c, u, a):
    return {"failure_codes": FAILURE_CODES, "acq_steps": ACQ_STEPS, "rules": rules(c), "marr": _f(setting(c, "marr_pct"), 12)}


# ═════════════════════════ ATTACHMENTS: one machine, several tools and outputs ═════════════════════════
# An excavator digs with a bucket and breaks rock with a hydraulic breaker; each has its own output (m3 dug,
# m3 of rock broken), its own productivity norm and often its own rate. The day's hours are split by tool
# on the DPR (one line per tool and activity) or on the monthly logsheet.
import api_project as P

TOOL_KINDS = [["bucket", "Bucket", "m3"], ["breaker", "Hydraulic rock breaker", "m3"], ["rock_bucket", "Rock bucket", "m3"],
              ["ripper", "Ripper", "m3"], ["grapple", "Grapple / clamshell", "trip"], ["auger", "Auger / drill", "m"],
              ["compactor", "Plate compactor", "m2"], ["long_boom", "Long-reach boom", "m3"], ["other", "Other", ""]]
EXCAVATOR_WORDS = ("excavator", "backhoe", "jcb", "poclain", "hymac", "digger")


def _is_excavator(e):
    t = " ".join(str(e.get(k) or "") for k in ("category", "name")).lower()
    return any(w in t for w in EXCAVATOR_WORDS)


def seed_tools(c):
    """Every excavator / backhoe without attachments gets a bucket (default) and a hydraulic breaker."""
    have = {r["equipment_id"] for r in q(c, "SELECT DISTINCT equipment_id FROM eq_tools")}
    n = 0
    for e in q(c, "SELECT * FROM equipment WHERE active=1"):
        if e["id"] in have or not _is_excavator(e):
            continue
        ins(c, "eq_tools", {"equipment_id": e["id"], "name": "Bucket", "kind": "bucket", "output_unit": "m3", "is_default": 1, "active": 1})
        ins(c, "eq_tools", {"equipment_id": e["id"], "name": "Hydraulic rock breaker", "kind": "breaker", "output_unit": "m3", "is_default": 0,
                            "active": 1, "remarks": "Rate blank = machine rate. Enter the breaker rate if it differs."})
        n += 1
    return n


def _tool(c, tid):
    return q1(c, "SELECT * FROM eq_tools WHERE id=?", (int(tid),)) if tid else None


@api("tool.list", "equipment", "view")
def tool_list(c, u, a):
    seed_tools(c)
    w, p = "t.active=1", []
    if a.get("equipment_id"):
        w += " AND t.equipment_id=?"
        p.append(int(a["equipment_id"]))
    rows = q(c, "SELECT t.*, e.code eq_code, e.name eq_name, e.internal_rate FROM eq_tools t JOIN equipment e ON e.id=t.equipment_id WHERE " + w +
             " ORDER BY e.code, t.is_default DESC, t.id", p)
    return {"rows": rows, "kinds": TOOL_KINDS}


@api("tool.save", "equipment", "edit")
def tool_save(c, u, a):
    r = a.get("row") or {}
    need(r, "equipment_id", "name")
    data = {"equipment_id": int(r["equipment_id"]), "name": r["name"].strip(), "kind": r.get("kind") or "other",
            "output_unit": r.get("output_unit") or dict((k[0], k[2]) for k in TOOL_KINDS).get(r.get("kind"), ""),
            "remarks": r.get("remarks"), "is_default": 1 if str(r.get("is_default")) in ("1", "true") else 0, "active": 1}
    for k in ("rate_hr", "hire_rate_hr", "fuel_hr", "norm_output_hr"):
        data[k] = _f(r.get(k), None) if r.get(k) not in (None, "") else None
    if data["is_default"]:
        c.execute("UPDATE eq_tools SET is_default=0 WHERE equipment_id=?", (data["equipment_id"],))
    if r.get("id"):
        upd(c, "eq_tools", int(r["id"]), data)
        tid = int(r["id"])
    else:
        tid = ins(c, "eq_tools", data)
    audit(c, u, "save", "eq_tools", tid, data)
    return {"id": tid}


@api("tool.delete", "equipment", "edit")
def tool_delete(c, u, a):
    c.execute("UPDATE eq_tools SET active=0, is_default=0 WHERE id=?", (int(a["id"]),))
    return True


@api("tool.log_get", "equipment", "view")
def tool_log_get(c, u, a):
    """The month's logsheet days of one machine with the hours and output of each attachment."""
    eid = int(a["equipment_id"])
    m = a.get("month") or today()[:7]
    tools = tool_list(c, u, {"equipment_id": eid})["rows"]
    logs = q(c, "SELECT id, date, shift, hours, dpr_id, work FROM logsheets WHERE equipment_id=? AND date BETWEEN ? AND ? ORDER BY date, shift",
             (eid, m + "-01", ER.month_end(m) if hasattr(ER, "month_end") else m + "-31"))
    for l in logs:
        l["tools"] = {str(x["tool_id"]): {"hours": x["hours"], "output_qty": x["output_qty"]}
                      for x in q(c, "SELECT tool_id, SUM(hours) hours, SUM(output_qty) output_qty FROM log_tools WHERE log_id=? GROUP BY tool_id", (l["id"],))}
        l["from_dpr"] = bool(l["dpr_id"])
    return {"tools": tools, "logs": logs, "month": m}


@api("tool.log_save", "equipment", "edit")
def tool_log_save(c, u, a):
    """Split one logsheet day by attachment. Days that came from a DPR are split on the DPR instead."""
    log = get(c, "logsheets", int(a["log_id"]), "Logsheet")
    if log["dpr_id"] and q1(c, "SELECT id FROM log_tools WHERE log_id=? AND dpr_equipment_id IS NOT NULL", (log["id"],)):
        raise ApiError("This day came from a DPR with attachments; change it on the DPR.")
    items = [x for x in (a.get("items") or []) if x.get("tool_id") and (_f(x.get("hours")) > 0 or _f(x.get("output_qty")) > 0)]
    tot = sum(_f(x.get("hours")) for x in items)
    if tot > (log["hours"] or 0) + 0.01:
        raise ApiError("%s: attachment hours %.1f are more than the %.1f hours worked that day." % (log["date"], tot, log["hours"] or 0))
    for x in items:
        t = _tool(c, x["tool_id"])
        if not t or t["equipment_id"] != log["equipment_id"]:
            raise ApiError("That attachment does not belong to this machine.")
    c.execute("DELETE FROM log_tools WHERE log_id=? AND dpr_equipment_id IS NULL", (log["id"],))
    for x in items:
        ins(c, "log_tools", {"log_id": log["id"], "tool_id": int(x["tool_id"]), "hours": _f(x.get("hours")),
                             "output_qty": _f(x.get("output_qty"), None) if x.get("output_qty") not in (None, "") else None})
    return {"hours": r2(tot)}


def _tool_hours(c, log):
    """[(tool or None, hours, output)] for one logsheet day; hours not split go to the default tool."""
    rows = q(c, "SELECT tool_id, SUM(hours) h, SUM(output_qty) o FROM log_tools WHERE log_id=? GROUP BY tool_id", (log["id"],))
    out = [(_tool(c, r["tool_id"]), r["h"] or 0, r["o"]) for r in rows]
    rest = (log["hours"] or 0) - sum(x[1] for x in out)
    if rest > 0.01:
        d = q1(c, "SELECT * FROM eq_tools WHERE equipment_id=? AND active=1 AND is_default=1", (log["equipment_id"],))
        out.append((d, rest, None))
    return out


@api("tool.output", "equipment", "view")
def tool_output(c, u, a):
    """Hours, output and productivity per machine and attachment, with the cost per hour and per unit."""
    frm = a.get("from") or (date.today() - timedelta(days=90)).isoformat()
    to = a.get("to") or today()
    w, p = "l.date BETWEEN ? AND ?", [frm, to]
    if a.get("project_id"):
        w += " AND l.project_id=?"
        p.append(int(a["project_id"]))
    if a.get("equipment_id"):
        w += " AND l.equipment_id=?"
        p.append(int(a["equipment_id"]))
    agg = {}
    eqs = {}
    for l in q(c, "SELECT l.* FROM logsheets l WHERE " + w + " AND l.equipment_id IN (SELECT equipment_id FROM eq_tools WHERE active=1)", p):
        if l["equipment_id"] not in eqs:
            eqs[l["equipment_id"]] = get(c, "equipment", l["equipment_id"])
        eq = eqs[l["equipment_id"]]
        base, _src = P.equipment_rate(c, eq, l["date"])
        for t, hrs, outq in _tool_hours(c, l):
            k = (eq["id"], t["id"] if t else 0)
            x = agg.setdefault(k, {"equipment_id": eq["id"], "code": eq["code"], "name": eq["name"], "tool_id": t["id"] if t else None,
                                   "tool": t["name"] if t else "(not split)", "unit": (t or {}).get("output_unit") or "",
                                   "norm_output_hr": (t or {}).get("norm_output_hr"), "hours": 0.0, "output": 0.0, "output_hours": 0.0,
                                   "cost": 0.0, "days": set()})
            rate = (t or {}).get("rate_hr") or base
            x["hours"] += hrs
            x["cost"] += hrs * (rate or 0)
            x["days"].add(l["date"])
            if outq:
                x["output"] += outq
                x["output_hours"] += hrs
    rows = []
    for x in agg.values():
        x["days"] = len(x["days"])
        x["output_per_hr"] = r2(x["output"] / x["output_hours"]) if x["output_hours"] > EPS else None
        x["vs_norm_pct"] = round(100 * x["output_per_hr"] / x["norm_output_hr"], 1) if x["output_per_hr"] and x["norm_output_hr"] else None
        x["cost_per_hr"] = r2(x["cost"] / x["hours"]) if x["hours"] > EPS else None
        x["cost_per_unit"] = r2(x["cost"] * (x["output_hours"] / x["hours"]) / x["output"]) if x["output"] > EPS and x["hours"] > EPS else None
        for k in ("hours", "output", "output_hours", "cost"):
            x[k] = r2(x[k])
        rows.append(x)
    rows.sort(key=lambda r: (r["code"], -r["hours"]))
    return {"rows": rows, "from": frm, "to": to,
            "note": "Output per hour uses only the hours for which an output was recorded. Hours not split by attachment count as the default attachment."}


# ── DPR: one machine may have several lines a day (bucket on excavation, breaker on rock) ──
for _k in ("tool_id", "output_qty"):
    if _k not in P.DPR_PARTS["equipment"][1]:
        P.DPR_PARTS["equipment"][1].append(_k)
P.DPR_ID.add("tool_id")
P.DPR_NUM.add("output_qty")
_orig_post_dpr = P.post_dpr
_orig_unpost_dpr = P.unpost_dpr


def post_dpr(c, u, d):
    """Machines with one plain line keep the original posting. A machine with an attachment or with more than
    one line that day gets ONE logsheet for the day (the total hours), split by attachment, and each line is
    costed at its attachment's rate (blank = the machine rate)."""
    ensure(c)
    lines = q(c, "SELECT * FROM dpr_equipment WHERE dpr_id=? ORDER BY id", (d["id"],))
    by_eq = {}
    for e in lines:
        by_eq.setdefault(e["equipment_id"], []).append(e)
    special = {k: v for k, v in by_eq.items() if len(v) > 1 or any(x.get("tool_id") for x in v)}
    ids = [e["id"] for v in special.values() for e in v]
    if ids:
        c.execute("UPDATE dpr_equipment SET dpr_id=-dpr_id WHERE id IN (%s)" % ",".join("?" * len(ids)), ids)
    try:
        _orig_post_dpr(c, u, d)
    finally:
        if ids:
            c.execute("UPDATE dpr_equipment SET dpr_id=-dpr_id WHERE id IN (%s)" % ",".join("?" * len(ids)), ids)
    if not special:
        return
    pid = d["project_id"]
    vl = []
    for eid, grp in special.items():
        eq = get(c, "equipment", eid, "Equipment")
        for e in grp:
            t = _tool(c, e.get("tool_id"))
            if e.get("tool_id") and (not t or t["equipment_id"] != eid):
                raise ApiError("%s: the attachment on the DPR does not belong to this machine." % eq["code"])
        log = q1(c, "SELECT * FROM logsheets WHERE equipment_id=? AND date=? AND shift=?", (eid, d["date"], d["shift"]))
        line_h = sum(e["hours"] or 0 for e in grp)
        created = 0
        if log:
            total = log["hours"] or 0
            if log["dpr_id"] is None:
                upd(c, "logsheets", log["id"], {"dpr_id": d["id"], "activity_id": grp[0]["activity_id"]})
            hrs = [(e["hours"] or 0) * total / line_h for e in grp] if line_h > EPS else [total] + [0] * (len(grp) - 1)
        else:
            starts = [e["meter_start"] for e in grp if e["meter_start"] is not None]
            ends = [e["meter_end"] for e in grp if e["meter_end"] is not None]
            r = ER.log_save(c, u, {"row": {"equipment_id": eid, "project_id": pid, "date": d["date"], "shift": d["shift"],
                                           "operator": grp[0]["operator"], "meter_start": min(starts) if starts else "",
                                           "meter_end": max(ends) if ends else "", "hours": line_h,
                                           "idle_hours": sum(e["idle_hours"] or 0 for e in grp),
                                           "breakdown_hours": sum(e["breakdown_hours"] or 0 for e in grp),
                                           "work": "From %s (%d lines)" % (d["no"], len(grp))}})
            upd(c, "logsheets", r["id"], {"status": "approved", "approved_by": u["id"], "dpr_id": d["id"], "activity_id": grp[0]["activity_id"]})
            log = get(c, "logsheets", r["id"])
            hrs = [e["hours"] or 0 for e in grp]
            created = 1
        c.execute("DELETE FROM log_tools WHERE log_id=? AND dpr_equipment_id IS NULL", (log["id"],))
        base, _src = P.equipment_rate(c, eq, d["date"])
        for i, (e, h_) in enumerate(zip(grp, hrs)):
            t = _tool(c, e.get("tool_id"))
            rate = (t or {}).get("rate_hr") or base
            amount = r2(h_ * rate)
            c.execute("DELETE FROM log_tools WHERE dpr_equipment_id=?", (e["id"],))
            if t or e.get("output_qty"):
                ins(c, "log_tools", {"log_id": log["id"], "tool_id": t["id"] if t else None, "hours": r2(h_), "output_qty": e.get("output_qty"),
                                     "activity_id": e["activity_id"], "dpr_equipment_id": e["id"]})
            upd(c, "dpr_equipment", e["id"], {"rate": rate, "amount": amount, "logsheet_id": log["id"],
                                              "created_log": created if i == 0 else 0, "hours": r2(h_)})
            if eq["ownership"] == "owned" and amount > 0:
                act = q1(c, "SELECT wbs_id, boq_item_id FROM activities WHERE id=?", (e["activity_id"],)) if e["activity_id"] else {}
                dims = {"activity_id": e["activity_id"], "wbs_id": (act or {}).get("wbs_id"), "boq_item_id": (act or {}).get("boq_item_id"), "project_id": pid}
                vl.append(dict(role="equipment_cost", debit=amount, equipment_id=eid,
                               narration="%s %s h%s" % (eq["code"], r2(h_), (" " + t["name"]) if t else ""), **dims))
                vl.append({"role": "equipment_recovery", "credit": amount, "equipment_id": eid, "project_id": pid})
            if (e["breakdown_hours"] or 0) > 0:
                P.auto_task(c, u, pid, "Breakdown: %s %s" % (eq["code"], eq["name"]), "dpr_equipment", e["id"], priority="high",
                            description="Reported in %s with %s breakdown hours. Raise a work order." % (d["no"], e["breakdown_hours"]))
    if vl:
        from core import post_voucher
        post_voucher(c, u, "journal", d["date"], "Machines by attachment %s" % d["no"], vl, project_id=pid, source="dpr", source_id=d["id"])


def unpost_dpr(c, u, d, reason):
    ids = [e["id"] for e in q(c, "SELECT id FROM dpr_equipment WHERE dpr_id=?", (d["id"],))]
    _orig_unpost_dpr(c, u, d, reason)
    if ids:
        c.execute("DELETE FROM log_tools WHERE dpr_equipment_id IN (%s)" % ",".join("?" * len(ids)), ids)
    c.execute("DELETE FROM log_tools WHERE log_id NOT IN (SELECT id FROM logsheets)")


P.post_dpr = post_dpr
P.unpost_dpr = unpost_dpr


# ── monthly internal charges: attachment hours at the attachment rate ──
_orig_internal_preview = ER.internal_preview


def internal_preview(c, u, a):
    ensure(c)
    rows = _orig_internal_preview(c, u, a)
    m = a["month"]
    for r in rows:
        extra = val(c, "SELECT SUM(t.hours * (x.rate_hr - ?)) FROM log_tools t JOIN eq_tools x ON x.id=t.tool_id JOIN logsheets l ON l.id=t.log_id "
                       "WHERE l.equipment_id=? AND l.project_id=? AND l.dpr_id IS NULL AND l.date BETWEEN ? AND ? AND x.rate_hr>0",
                    (r["internal_rate"], r["equipment_id"], r["project_id"], m + "-01", ER.month_end(m)))
        if abs(extra or 0) > 0.005:
            r["amount"] = r2(r["amount"] + extra)
            r["internal_rate"] = r2(r["amount"] / r["hours"]) if r["hours"] else r["internal_rate"]
            r["by_attachment"] = True
    return rows


ER.internal_preview = internal_preview
_ip = inv.FUNCS["internal.preview"]
inv.FUNCS["internal.preview"] = (internal_preview, _ip[1], _ip[2], _ip[3])


# ── rented machines: attachment hire rate (e.g. breaker at a higher rate) on the monthly hire bill ──
_orig_hire_bill = inv.FUNCS["hire.bill"][0]


def hire_bill(c, u, a):
    ensure(c)
    r = _orig_hire_bill(c, u, a)
    ag = get(c, "hire_agreements", int(a["agreement_id"]))
    if ag["unit"] != "hour":
        return r
    m = a["month"]
    rows = q(c, "SELECT x.name, x.hire_rate_hr, SUM(t.hours) h FROM log_tools t JOIN eq_tools x ON x.id=t.tool_id JOIN logsheets l ON l.id=t.log_id "
                "WHERE l.equipment_id=? AND l.project_id=? AND l.date BETWEEN ? AND ? AND x.hire_rate_hr>0 GROUP BY x.id",
             (ag["equipment_id"], ag["project_id"], m + "-01", ER.month_end(m)))
    acc = val(c, "SELECT id FROM accounts WHERE role='hire_cost'")
    added = 0.0
    for x in rows:
        diff = r2((x["hire_rate_hr"] - (ag["rate"] or 0)) * x["h"])
        if abs(diff) < 0.005:
            continue
        ins(c, "invoice_lines", {"invoice_id": r["invoice_id"], "description": "%s: %s h at %s instead of %s" % (x["name"], r2(x["h"]), x["hire_rate_hr"], ag["rate"]),
                                 "qty": r2(x["h"]), "rate": r2(x["hire_rate_hr"] - (ag["rate"] or 0)), "vat_rate": ag["vat_rate"] or 0, "amount": diff,
                                 "account_id": acc, "equipment_id": ag["equipment_id"]})
        added += diff
    if added:
        c.execute("UPDATE hire_bills SET amount=amount+? WHERE agreement_id=? AND month=?", (added, ag["id"], m))
        r["attachment_extra"] = r2(added)
    return r


_hb = inv.FUNCS["hire.bill"]
inv.FUNCS["hire.bill"] = (hire_bill, _hb[1], _hb[2], _hb[3])


# the next DPR starts with yesterday's machine lines, now with their attachments
_pf = inv.FUNCS["dpr.prefill"]


def dpr_prefill(c, u, a):
    r = _pf[0](c, u, a)
    if r.get("previous_dpr") and r.get("equipment"):
        prev = q(c, "SELECT tool_id FROM dpr_equipment WHERE dpr_id=? ORDER BY id", (r["previous_dpr"],))
        for e, p_ in zip(r["equipment"], prev):
            if p_["tool_id"]:
                e["tool_id"] = p_["tool_id"]
    return r


inv.FUNCS["dpr.prefill"] = (dpr_prefill, _pf[1], _pf[2], _pf[3])


# ── 2.4.1: outputs for ANY machine, set on the machine itself, with ready templates ──
TOOL_TEMPLATES = {
    "excavator": ("Excavator", [("Bucket", "bucket", "m3", 1), ("Hydraulic rock breaker", "breaker", "m3", 0)]),
    "excavator3": ("Excavator (bucket, breaker, rock bucket)", [("Bucket", "bucket", "m3", 1), ("Hydraulic rock breaker", "breaker", "m3", 0),
                                                                ("Rock bucket", "rock_bucket", "m3", 0)]),
    "backhoe": ("Backhoe loader (JCB 3DX)", [("Front loader bucket", "bucket", "m3", 0), ("Backhoe bucket", "bucket", "m3", 1),
                                             ("Hydraulic breaker", "breaker", "m3", 0)]),
    "loader": ("Wheel loader", [("Bucket loading", "bucket", "m3", 1), ("Fork / pallet", "other", "trip", 0)]),
    "dozer": ("Dozer", [("Blade dozing", "other", "m3", 1), ("Ripper", "ripper", "m3", 0)]),
    "grader": ("Motor grader", [("Blade grading", "other", "m2", 1), ("Scarifier", "other", "m2", 0)]),
    "tractor": ("Tractor", [("Trolley haulage", "other", "trip", 1), ("Dozer blade", "other", "m3", 0), ("Water tanker", "other", "trip", 0)]),
    "jumbo": ("Drill jumbo", [("Face drilling", "auger", "m", 1), ("Rock bolting", "other", "nos", 0)]),
    "tipper": ("Tipper / dumper", [("Muck / earth haulage", "other", "m3", 1), ("Aggregate / sand haulage", "other", "m3", 0)]),
    "crane": ("Crane", [("Lifting", "other", "lift", 1), ("Piling / other", "other", "nos", 0)]),
    "compressor": ("Compressor", [("Jack hammer / drilling", "auger", "m", 1), ("Shotcrete / blowing", "other", "m3", 0)]),
}
_DETECT = [("backhoe", ("backhoe", "3dx", "3cx", "jcb 3", "backhoe loader")),
           ("excavator", ("excavator", "poclain", "hymac", "digger", "hydraulic excavator"))]


def detect_template(e):
    t = " ".join(str(e.get(k) or "") for k in ("category", "name", "model")).lower()
    for key, words in _DETECT:
        if any(w in t for w in words):
            return key
    return None


def seed_tools(c):
    """Excavators and backhoe loaders without outputs get their standard set."""
    have = {r["equipment_id"] for r in q(c, "SELECT DISTINCT equipment_id FROM eq_tools")}
    n = 0
    for e in q(c, "SELECT * FROM equipment WHERE active=1"):
        key = detect_template(e) if e["id"] not in have else None
        if key:
            _apply_template(c, e["id"], key)
            n += 1
    return n


def _apply_template(c, eid, key, keep=True):
    have = {r["name"].lower() for r in q(c, "SELECT name FROM eq_tools WHERE equipment_id=? AND active=1", (eid,))}
    any_default = bool(have) and keep
    for name, kind, unit, dflt in TOOL_TEMPLATES[key][1]:
        if name.lower() in have:
            continue
        ins(c, "eq_tools", {"equipment_id": eid, "name": name, "kind": kind, "output_unit": unit,
                            "is_default": 0 if any_default else dflt, "active": 1})


@api("tool.templates", "equipment", "view")
def tool_templates(c, u, a):
    return {"templates": [{"key": k, "label": v[0], "outputs": [x[0] for x in v[1]]} for k, v in TOOL_TEMPLATES.items()], "kinds": TOOL_KINDS}


@api("tool.apply_template", "equipment", "edit")
def tool_apply_template(c, u, a):
    eid = int(a["equipment_id"])
    if a.get("key") not in TOOL_TEMPLATES:
        raise ApiError("Unknown template.")
    get(c, "equipment", eid, "Equipment")
    _apply_template(c, eid, a["key"])
    return tool_list(c, u, {"equipment_id": eid})


@api("tool.save_all", "equipment", "edit")
def tool_save_all(c, u, a):
    """Replace a machine's outputs with the list given (rows without a name are dropped; removed ones are kept
    inactive so old records still read)."""
    eid = int(a["equipment_id"])
    get(c, "equipment", eid, "Equipment")
    rows = [r for r in (a.get("rows") or []) if (r.get("name") or "").strip()]
    if sum(1 for r in rows if str(r.get("is_default")) in ("1", "true")) > 1:
        raise ApiError("Only one output can be the default.")
    keep = set()
    for r in rows:
        r = dict(r, equipment_id=eid)
        keep.add(tool_save(c, u, {"row": r})["id"])
    for t in q(c, "SELECT id FROM eq_tools WHERE equipment_id=? AND active=1", (eid,)):
        if t["id"] not in keep:
            c.execute("UPDATE eq_tools SET active=0, is_default=0 WHERE id=?", (t["id"],))
    if rows and not q1(c, "SELECT id FROM eq_tools WHERE equipment_id=? AND active=1 AND is_default=1", (eid,)):
        c.execute("UPDATE eq_tools SET is_default=1 WHERE id=(SELECT MIN(id) FROM eq_tools WHERE equipment_id=? AND active=1)", (eid,))
    return tool_list(c, u, {"equipment_id": eid})


# a new excavator / backhoe gets its outputs as soon as it is saved
_ms = inv.FUNCS["master.save"]


def master_save_eq(c, u, a):
    r = _ms[0](c, u, a)
    if a.get("table") == "equipment" and r and not (a.get("row") or {}).get("id"):
        ensure(c)
        key = detect_template(r)
        if key and not q1(c, "SELECT id FROM eq_tools WHERE equipment_id=?", (r["id"],)):
            _apply_template(c, r["id"], key)
    return r


inv.FUNCS["master.save"] = (master_save_eq, _ms[1], _ms[2], _ms[3])


# ═════════════════════════ 2.6: LOGSHEETS ONLY FROM THE DPR, FUEL AND OIL ONLY FROM THE STORE ═════════════════════════
# Equipment keeps the list of machines and where they are deployed. Hours, meters, idle / breakdown time and
# outputs come from the approved DPR; fuel, oil and grease come from store issues to the machine. Typing a
# logsheet by hand is switched off (setting logsheet_dpr_only = 1, the default; an administrator can turn it off).
import api_inventory as _inv_mod

FLUID_WORDS = [("engine_oil", ("engine oil", "15w", "20w", "mobil", "servo", "crank")), ("hydraulic_oil", ("hydraulic",)),
               ("gear_oil", ("gear oil", "gear")), ("transmission_oil", ("transmission", "atf")), ("brake_oil", ("brake",)),
               ("crown_oil", ("crown",)), ("grease", ("grease",)), ("coolant", ("coolant", "antifreeze"))]


def dpr_only(c):
    return (setting(c, "logsheet_dpr_only") or "1") not in ("0", "false", "no")


def _mat_kind(m):
    """'fuel', a log_fluids column, or None."""
    cat = (m.get("category") or "").lower()
    name = (m.get("name") or "").lower()
    text = cat + " " + name
    if any(w in text for w in ("diesel", "petrol", "gasoline", "hsd", "kerosene")) or (("fuel" in cat) and not any(w in name for w in ("oil", "grease", "lubric", "coolant"))):
        return "fuel"
    if any(w in text for w in ("oil", "grease", "lubric", "coolant", "antifreeze")):
        for col, words in FLUID_WORDS:
            if any(w in name for w in words):
                return col
        return "other"
    return None


def store_issues(c, eid, frm, to):
    return q(c, "SELECT i.date, i.no, l.material_id, m.code, m.name, m.unit, m.category, SUM(l.qty-l.returned_qty) qty, SUM(l.amount) amount "
                "FROM issue_lines l JOIN issues i ON i.id=l.issue_id JOIN materials m ON m.id=l.material_id WHERE i.status='posted' AND "
                "l.equipment_id=? AND i.date BETWEEN ? AND ? GROUP BY i.id, l.material_id ORDER BY i.date, i.no", (eid, frm, to))


def sync_store(c, eid, frm, to):
    """Put the store's fuel issues on the logsheet days (first shift of the day) and its oil / grease issues in the
    sheet's oil table. Only lines BuildCore wrote itself are replaced."""
    fuel, fluids = {}, {}
    for r in store_issues(c, eid, frm, to):
        k = _mat_kind(r)
        if k == "fuel":
            fuel[r["date"]] = fuel.get(r["date"], 0) + (r["qty"] or 0)
        elif k:
            d = fluids.setdefault(r["date"], {})
            if k == "other":
                d["other"] = d.get("other", 0) + (r["qty"] or 0)
                d["other_name"] = (d.get("other_name", "") + " " + r["name"]).strip()[:60]
            else:
                d[k] = d.get(k, 0) + (r["qty"] or 0)
    for lg in q(c, "SELECT id, date, fuel_qty FROM logsheets WHERE equipment_id=? AND date BETWEEN ? AND ? ORDER BY date, CASE shift WHEN 'day' THEN 0 ELSE 1 END, id", (eid, frm, to)):
        want = r2(fuel.pop(lg["date"], 0)) if lg["date"] in fuel else 0.0
        if abs((lg["fuel_qty"] or 0) - want) > 0.0005:
            c.execute("UPDATE logsheets SET fuel_qty=? WHERE id=?", (want, lg["id"]))
    if _has(c, "log_fluids"):
        c.execute("DELETE FROM log_fluids WHERE equipment_id=? AND date BETWEEN ? AND ? AND remarks='from store issues'", (eid, frm, to))
        cols = {r[1] for r in c.execute("PRAGMA table_info(log_fluids)")}
        for dte, d in fluids.items():
            book = val(c, "SELECT id FROM logbooks WHERE equipment_id=? AND ? BETWEEN from_date AND to_date ORDER BY id DESC", (eid, dte), None)
            row = {"book_id": book, "equipment_id": eid, "date": dte, "remarks": "from store issues"}
            for k, v in d.items():
                if k == "other" and "other_qty" in cols:
                    row["other_qty"] = r2(v)
                elif k == "other_name" and "other_name" in cols:
                    row["other_name"] = v
                elif k in cols:
                    row[k] = r2(v)
            ins(c, "log_fluids", row)


def _guard(name, msg, when=None):
    ent = inv.FUNCS.get(name)
    if not ent:
        return

    def wrapped(c, u, a):
        ensure(c)
        if dpr_only(c) and (when is None or when(c, a)):
            raise ApiError(msg)
        return ent[0](c, u, a)
    inv.FUNCS[name] = (wrapped, ent[1], ent[2], ent[3])


_MSG_DPR = ("Logsheets come from the approved DPR: enter the machine's hours, meters, idle and breakdown time and its output on the "
            "DPR (Equipment step). Fuel, oil and grease come from store issues to the machine (Inventory › Issues).")
_guard("log.save", _MSG_DPR)
_guard("book.rows", _MSG_DPR)
_guard("book.fluids", "Oil and grease come from store issues to the machine (Inventory › Issues, issue to the machine).")
_guard("tool.log_save", "Output hours come from the DPR: choose the output on each machine line of the DPR.")
_guard("life.telematics", "Logsheets come from the approved DPR only, so the telematics import is switched off (Settings: logsheets only from DPR).")
_guard("log.delete", "This day came from an approved DPR; reopen the DPR to change it.",
       when=lambda c, a: bool(val(c, "SELECT dpr_id FROM logsheets WHERE id=?", (int(a.get("id") or 0),), None)))


def _wrap_after(name, fn):
    ent = inv.FUNCS.get(name)
    if not ent:
        return

    def wrapped(c, u, a):
        ensure(c)
        r = ent[0](c, u, a)
        try:
            fn(c, a, r)
        except Exception:
            pass
        return r
    inv.FUNCS[name] = (wrapped, ent[1], ent[2], ent[3])


def _after_issue(c, a, r):
    iid = int(a.get("id") or 0)
    i = q1(c, "SELECT date FROM issues WHERE id=?", (iid,))
    if i:
        for e in q(c, "SELECT DISTINCT equipment_id FROM issue_lines WHERE issue_id=? AND equipment_id IS NOT NULL", (iid,)):
            sync_store(c, e["equipment_id"], i["date"], i["date"])


_wrap_after("issue.post", _after_issue)
_wrap_after("issue.cancel", _after_issue)


def _after_dpr(c, a, r):
    d = q1(c, "SELECT date FROM dpr WHERE id=?", (int(a["id"]),))
    for e in q(c, "SELECT DISTINCT equipment_id FROM dpr_equipment WHERE dpr_id=?", (int(a["id"]),)):
        sync_store(c, e["equipment_id"], d["date"], d["date"])


_wrap_after("dpr.approve", _after_dpr)


if "book.get" in inv.FUNCS and "book.get.raw" not in inv.FUNCS:
    inv.FUNCS["book.get.raw"] = inv.FUNCS["book.get"]
    _raw = inv.FUNCS["book.get"]

    def book_get2(c, u, a):
        ensure(c)
        b = q1(c, "SELECT equipment_id, from_date, to_date FROM logbooks WHERE id=?", (int(a["id"]),))
        if b:
            sync_store(c, b["equipment_id"], b["from_date"], b["to_date"])
        r = _raw[0](c, u, a)
        r["book"]["dpr_only"] = dpr_only(c)
        r["store_issues"] = store_issues(c, r["book"]["equipment_id"], r["book"]["from_date"], r["book"]["to_date"])
        if isinstance(r.get("summary"), dict):
            _store_fuel(c, r["book"], r["summary"])
        return r
    inv.FUNCS["book.get"] = (book_get2, _raw[1], _raw[2], _raw[3])


def _store_fuel(c, b, sm):
    """The month's fuel is what the store issued to the machine, also on days without a DPR line."""
    f = sum((x["qty"] or 0) for x in store_issues(c, b["equipment_id"], b["from_date"], b["to_date"]) if _mat_kind(x) == "fuel")
    if f or dpr_only(c):
        sm["fuel"] = r2(f)
        sm["fuel_per_hour"] = r2(f / sm["hours"]) if sm.get("hours") else 0
        sm["fuel_per_km"] = r2(f / sm["km"]) if sm.get("km") else 0


if "book.summary" in inv.FUNCS:
    _bs = inv.FUNCS["book.summary"]

    def book_summary2(c, u, a):
        ensure(c)
        r = _bs[0](c, u, a)
        b = q1(c, "SELECT * FROM logbooks WHERE id=?", (int(a["id"]),))
        if b and isinstance(r, dict):
            _store_fuel(c, b, r["summary"] if isinstance(r.get("summary"), dict) else r)
        return r
    inv.FUNCS["book.summary"] = (book_summary2, _bs[1], _bs[2], _bs[3])


@api("life.log_mode", "equipment", "view")
def log_mode(c, u, a):
    """Read, or (administrator) set, whether logsheets may be typed by hand."""
    if a.get("set") is not None:
        if (u.get("role") or "") != "admin":
            raise ApiError("Only an administrator can change this.")
        c.execute("INSERT INTO settings(key,value) VALUES('logsheet_dpr_only',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                  ("1" if str(a["set"]) in ("1", "true") else "0",))
        audit(c, u, "setting", "settings", None, {"logsheet_dpr_only": a["set"]})
    return {"dpr_only": dpr_only(c)}


# ═════════════════════════ 2.7  Logsheet per output (bucket, breaker…) ═════════════════════════
@api("tool.sheet", "equipment", "view")
def tool_sheet(c, u, a):
    """One machine's month split into a separate logsheet for each output / attachment: the days it worked
    with that output, hours, quantity done, its share of the month's fuel (store issues shared by hours) and the amount
    at that output's rate.  Hours a day did not split go to the machine's default output."""
    eid = int(a["equipment_id"])
    eq = get(c, "equipment", eid, "Machine")
    m = (a.get("month") or today())[:7]
    frm = a.get("from") or m + "-01"
    to = a.get("to") or (ER.month_end(m) if hasattr(ER, "month_end") else m + "-31")
    cond, p = "equipment_id=? AND date BETWEEN ? AND ?", [eid, frm, to]
    if a.get("project_id"):
        cond += " AND project_id=?"
        p.append(int(a["project_id"]))
    logs = q(c, "SELECT * FROM logsheets WHERE " + cond + " ORDER BY date, shift", p)
    fuel_day = {}
    try:
        for x in store_issues(c, eid, frm, to):
            if _mat_kind(x) == "fuel":
                fuel_day[x["date"]] = fuel_day.get(x["date"], 0) + (x["qty"] or 0)
    except Exception:
        fuel_day = {}
    day_hours = {}
    for l in logs:
        day_hours[l["date"]] = day_hours.get(l["date"], 0) + (l["hours"] or 0)
    outs = {}
    unassigned = 0.0
    for l in logs:
        dpr_no = val(c, "SELECT no FROM dpr WHERE id=?", (l["dpr_id"],)) if l.get("dpr_id") else None
        for t, hrs, qty in _tool_hours(c, l):
            if not t:
                unassigned += hrs or 0
                key = "0"
                t = {"id": None, "name": "Not split (no default output)", "kind": "", "output_unit": "", "rate_hr": None,
                     "hire_rate_hr": None, "fuel_hr": None, "norm_output_hr": None}
            else:
                key = str(t["id"])
            o = outs.setdefault(key, {"tool_id": t["id"], "name": t["name"], "kind": t.get("kind"), "unit": t.get("output_unit") or "",
                                      "rate_hr": t.get("rate_hr") or eq.get("internal_rate") or 0,
                                      "hire_rate_hr": t.get("hire_rate_hr"), "fuel_norm_hr": t.get("fuel_hr"),
                                      "norm_output_hr": t.get("norm_output_hr"), "days": []})
            o["days"].append({"log_id": l["id"], "date": l["date"], "shift": l["shift"], "operator": l.get("operator"),
                              "meter_start": l.get("meter_start"), "meter_end": l.get("meter_end"), "day_hours": l["hours"],
                              "hours": r2(hrs or 0), "output_qty": qty, "work": l.get("work"),
                              "dpr_no": dpr_no, "status": l["status"]})
    res = []
    for o in outs.values():
        o["hours"] = r2(sum(d["hours"] for d in o["days"]))
        o["output_qty"] = r4(sum(d["output_qty"] or 0 for d in o["days"]))
        tot_h = sum(day_hours.values())
        o["fuel"] = r2(sum(fuel_day.values()) * o["hours"] / tot_h) if tot_h else 0
        o["days_worked"] = len({d["date"] for d in o["days"]})
        o["amount"] = r2(o["hours"] * (o["rate_hr"] or 0))
        o["output_per_hour"] = r4(o["output_qty"] / o["hours"]) if o["hours"] else 0
        o["fuel_per_hour"] = r2(o["fuel"] / o["hours"]) if o["hours"] else 0
        res.append(o)
    res.sort(key=lambda o: (o["tool_id"] is None, -(o["hours"] or 0)))
    # outputs that did not work this month are still listed, so each has its own (empty) sheet
    for t in q(c, "SELECT * FROM eq_tools WHERE equipment_id=? AND active=1 ORDER BY is_default DESC, id", (eid,)):
        if str(t["id"]) not in outs:
            res.append({"tool_id": t["id"], "name": t["name"], "kind": t["kind"], "unit": t["output_unit"] or "",
                        "rate_hr": t["rate_hr"] or eq.get("internal_rate") or 0, "hire_rate_hr": t["hire_rate_hr"],
                        "fuel_norm_hr": t["fuel_hr"], "norm_output_hr": t["norm_output_hr"], "days": [], "hours": 0,
                        "output_qty": 0, "fuel": 0, "days_worked": 0, "amount": 0, "output_per_hour": 0, "fuel_per_hour": 0})
    return {"equipment": {"id": eq["id"], "code": eq["code"], "name": eq["name"], "reg_no": eq.get("reg_no"),
                          "operator": eq.get("operator"), "ownership": eq.get("ownership")},
            "month": m, "from": frm, "to": to, "outputs": res, "unassigned_hours": r2(unassigned),
            "total_hours": r2(sum(l["hours"] or 0 for l in logs)), "total_fuel": r2(sum(fuel_day.values()))}
