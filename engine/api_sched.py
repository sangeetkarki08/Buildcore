"""
BuildCore 1.9 - schedule core, built into the existing Work > Schedule & WBS, DPR, Events and
Cost & earned value screens (no new module).

  * CPM network: FS / SS / FF / SF links with lags, forward and backward pass, four floats,
    computed critical and near-critical flags, loop and open-end checks          (roadmap 2.1, 6.2)
  * calendars: 6-day week, Nepali public holidays and festival shutdowns, monsoon no-work windows
    per work type, weather allowance learnt from DPR weather                        (2.2)
  * contract time register: NTP, time for completion, milestones, LD per day and cap, notice
    periods, float ownership, EOT granted, LD exposure                              (2.3)
  * baselines, schedule updates on a data date with remaining durations from DPR progress,
    slipped activities, float change, recovery list, as-built schedule              (2.4, 6.3)
  * look-ahead (short-interval) schedule with constraint checks and weekly PPC      (2.5)
  * cost-loaded early / late / baseline S-curve envelope with the actual curve      (2.9, 6.1)
  * submittal register linked to activities                                         (2.16)
  * posted vouchers are made immutable in the database itself (reverse only)        (NFRS 9)

Existing behaviour that changes: planned progress is spread over WORKING days between the
baseline dates instead of evenly over calendar days, the critical flag is computed, and the
forecast finish comes from the CPM update (the 14-day average is kept as a check).
"""
import json
import time
from datetime import date, timedelta

from core import ApiError, EPS, audit, get, ins, need, now, num, q, q1, r2, r4, setting, today, upd, val
import core
import api_inventory as inv
from api_inventory import api as _register
import api_project as P
import sched_calc as SC

VERSION = "2.44.1"
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
        if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='sched_runs'").fetchone() or \
                "work_type" not in _cols(c, "activities"):
            init_sched(c)
        _READY.add(key)


SCHEMA = """
CREATE TABLE IF NOT EXISTS act_links(id INTEGER PRIMARY KEY, project_id INTEGER, pred_id INTEGER, succ_id INTEGER,
  type TEXT DEFAULT 'FS', lag REAL DEFAULT 0);
CREATE INDEX IF NOT EXISTS ix_links_p ON act_links(project_id);
CREATE TABLE IF NOT EXISTS sched_calendars(id INTEGER PRIMARY KEY, project_id INTEGER, name TEXT,
  week TEXT DEFAULT '1111101', hours_day REAL DEFAULT 8, is_default INTEGER DEFAULT 0, weather TEXT, notes TEXT);
CREATE TABLE IF NOT EXISTS sched_holidays(id INTEGER PRIMARY KEY, calendar_id INTEGER, date TEXT, name TEXT,
  kind TEXT DEFAULT 'public');
CREATE TABLE IF NOT EXISTS sched_windows(id INTEGER PRIMARY KEY, calendar_id INTEGER, work_type TEXT,
  bs_from TEXT, bs_to TEXT, reason TEXT);
CREATE TABLE IF NOT EXISTS contract_milestones(id INTEGER PRIMARY KEY, project_id INTEGER, name TEXT,
  activity_id INTEGER, due_date TEXT, ld_per_day REAL DEFAULT 0, section TEXT, remarks TEXT);
CREATE TABLE IF NOT EXISTS sched_baselines(id INTEGER PRIMARY KEY, project_id INTEGER, no INTEGER, name TEXT,
  data_date TEXT, start TEXT, finish TEXT, created TEXT, created_by INTEGER, is_current INTEGER DEFAULT 0, notes TEXT);
CREATE TABLE IF NOT EXISTS sched_baseline_acts(id INTEGER PRIMARY KEY, baseline_id INTEGER, activity_id INTEGER,
  start TEXT, finish TEXT, dur REAL, tf REAL, value REAL, planned_qty REAL, critical INTEGER DEFAULT 0);
CREATE INDEX IF NOT EXISTS ix_bla ON sched_baseline_acts(baseline_id);
CREATE TABLE IF NOT EXISTS sched_runs(id INTEGER PRIMARY KEY, project_id INTEGER, data_date TEXT, start TEXT,
  finish TEXT, prev_finish TEXT, target TEXT, critical_count INTEGER, warnings TEXT, snapshot TEXT, created TEXT,
  user_id INTEGER, notes TEXT);
CREATE TABLE IF NOT EXISTS lookahead(id INTEGER PRIMARY KEY, project_id INTEGER, week_start TEXT, activity_id INTEGER,
  planned_qty REAL DEFAULT 0, foreman TEXT, done INTEGER, actual_qty REAL, reason TEXT, checks TEXT, created TEXT);
CREATE INDEX IF NOT EXISTS ix_la ON lookahead(project_id, week_start);
CREATE TABLE IF NOT EXISTS dpr_survey(id INTEGER PRIMARY KEY, dpr_id INTEGER, cause TEXT, trade_id INTEGER,
  activity_id INTEGER, area TEXT, workers REAL DEFAULT 0, hours REAL DEFAULT 0, remarks TEXT);
CREATE INDEX IF NOT EXISTS ix_dpr_survey ON dpr_survey(dpr_id);
CREATE TABLE IF NOT EXISTS submittals(id INTEGER PRIMARY KEY, no TEXT, project_id INTEGER, kind TEXT DEFAULT 'drawing',
  title TEXT, ref TEXT, activity_id INTEGER, required_by TEXT, submitted_date TEXT, review_days INTEGER DEFAULT 14,
  due_back TEXT, returned_date TEXT, status TEXT DEFAULT 'planned', revision TEXT, party TEXT, remarks TEXT,
  created_by INTEGER);
"""

COLUMNS = {
    "activities": {"duration": "REAL", "calendar_id": "INTEGER", "work_type": "TEXT", "weather_sensitive": "INTEGER",
                   "constraint_type": "TEXT", "constraint_date": "TEXT", "es": "TEXT", "ef": "TEXT", "ls": "TEXT",
                   "lf": "TEXT", "tf": "REAL", "ff": "REAL", "indep_float": "REAL", "interf_float": "REAL",
                   "near_critical": "INTEGER", "remaining_dur": "REAL", "remaining_override": "REAL",
                   "pct_complete": "REAL", "driver_id": "INTEGER", "foreman": "TEXT", "weather_days": "REAL",
                   "crash_dur": "REAL", "crash_cost": "REAL", "normal_cost": "REAL", "dur_opt": "REAL",
                   "dur_likely": "REAL", "dur_pess": "REAL", "chainage_from": "REAL", "chainage_to": "REAL",
                   "linear_order": "INTEGER", "norm_code": "TEXT", "act_start_override": "TEXT",
                   "act_finish_override": "TEXT"},
    "projects": {"ntp_date": "TEXT", "tfc_days": "REAL", "tfc_basis": "TEXT", "completion_date": "TEXT",
                 "ld_per_day": "REAL", "ld_cap_pct": "REAL", "notice_days": "REAL", "float_owner": "TEXT",
                 "near_crit_days": "REAL", "calendar_id": "INTEGER", "indirect_per_day": "REAL",
                 "time_notes": "TEXT", "data_date": "TEXT"},
    "events": {"activity_ids": "TEXT", "notice_days": "REAL", "notice_sent": "TEXT", "excusable": "INTEGER",
               "compensable": "INTEGER", "concurrent": "INTEGER", "eot_claimed": "REAL", "eot_granted": "REAL",
               "fragnet": "TEXT", "prolongation_cost": "REAL", "window": "TEXT"},
    "dpr": {"weather_lost_hours": "REAL", "rain_mm": "REAL", "lost_day": "INTEGER"},
    "dpr_work": {"chainage_from": "REAL", "chainage_to": "REAL"},
}

WORK_TYPES = [["", "General"], ["earthwork", "Earthwork (open)"], ["river", "River / diversion works"],
              ["concrete", "Concrete (open air)"], ["tunnel", "Tunnel / underground"], ["blacktop", "Blacktop / asphalt"],
              ["structure", "Building / covered work"], ["hm", "Hydro-mechanical & electrical"],
              ["transmission", "Transmission line"], ["pipeline", "Pipeline / penstock"],
              ["loe", "Level of effort (insurance, compliance, supervision)"]]
TIME_UNITS = {"ls", "l.s.", "lump sum", "item", "job", "sum", "month", "months", "day", "days", "p.s.", "ps"}
SENSITIVE = {"earthwork", "river", "concrete", "blacktop", "transmission", "pipeline"}

# Public holidays of 2083 BS as notified (verify against the Ministry of Home Affairs notice each year;
# Eid dates and the women-only Teej / Jitiya holidays are left for each company to add).
HOLIDAYS_2083 = [
    ("2083-01-01", "New Year (Baishakh 1)", "public"), ("2083-01-18", "Buddha Jayanti", "public"),
    ("2083-05-12", "Rakshya Bandhan / Janai Purnima", "public"), ("2083-05-19", "Krishna Janmashtami", "public"),
    ("2083-06-25", "Ghatasthapana", "festival"),
    ("2083-06-31", "Dashain", "festival"), ("2083-07-01", "Dashain", "festival"), ("2083-07-02", "Dashain", "festival"),
    ("2083-07-03", "Dashain", "festival"), ("2083-07-04", "Dashain", "festival"), ("2083-07-05", "Dashain", "festival"),
    ("2083-07-06", "Dashain", "festival"),
    ("2083-07-22", "Tihar", "festival"), ("2083-07-23", "Tihar", "festival"), ("2083-07-24", "Tihar", "festival"),
    ("2083-07-25", "Tihar", "festival"), ("2083-07-26", "Tihar", "festival"),
    ("2083-07-29", "Chhath", "festival"), ("2083-09-09", "Udhauli / Yomari Punhi", "public"),
    ("2083-09-10", "Christmas", "public"), ("2083-09-15", "Tamu Lhosar", "public"),
    ("2083-10-01", "Maghe Sankranti", "public"), ("2083-10-24", "Sonam Lhosar", "public"),
    ("2083-11-22", "Maha Shivaratri", "public"), ("2083-11-25", "Gyalpo Lhosar", "public"),
    ("2083-12-07", "Fagu Purnima (hill)", "public"),
]
WINDOWS = [("river", "03-01", "05-31", "Monsoon: no river-bed or diversion works Asar to Bhadra"),
           ("blacktop", "03-01", "05-31", "Monsoon: no asphalt or surface dressing Asar to Bhadra")]


def _cols(c, t):
    try:
        return {r[1] for r in c.execute("PRAGMA table_info(%s)" % t)}
    except Exception:
        return set()


TRIGGERS = """
CREATE TRIGGER IF NOT EXISTS bco_voucher_no_delete BEFORE DELETE ON vouchers
  WHEN OLD.status IN ('posted','reversed')
  BEGIN SELECT RAISE(ABORT, 'Posted vouchers cannot be deleted. Reverse them instead (NFRS: vouchers are permanent).'); END;
CREATE TRIGGER IF NOT EXISTS bco_voucher_no_edit BEFORE UPDATE ON vouchers
  WHEN OLD.status IN ('posted','reversed') AND (NEW.date IS NOT OLD.date OR NEW.total IS NOT OLD.total
    OR NEW.no IS NOT OLD.no OR NEW.type IS NOT OLD.type OR NEW.project_id IS NOT OLD.project_id
    OR NEW.party_id IS NOT OLD.party_id OR NEW.source IS NOT OLD.source OR NEW.source_id IS NOT OLD.source_id
    OR (OLD.status='reversed' AND NEW.status<>'reversed')
    OR (OLD.status='posted' AND NEW.status NOT IN ('posted','reversed')))
  BEGIN SELECT RAISE(ABORT, 'A posted voucher cannot be changed. Post a reversal and a new voucher instead.'); END;
CREATE TRIGGER IF NOT EXISTS bco_vline_no_delete BEFORE DELETE ON voucher_lines
  WHEN (SELECT status FROM vouchers WHERE id=OLD.voucher_id) IN ('posted','reversed')
  BEGIN SELECT RAISE(ABORT, 'Lines of a posted voucher cannot be deleted. Reverse the voucher instead.'); END;
CREATE TRIGGER IF NOT EXISTS bco_vline_no_edit BEFORE UPDATE OF voucher_id, account_id, debit, credit ON voucher_lines
  WHEN (SELECT status FROM vouchers WHERE id=OLD.voucher_id) IN ('posted','reversed')
  BEGIN SELECT RAISE(ABORT, 'Amounts and accounts of a posted voucher cannot be changed. Reverse it instead.'); END;
"""


def init_sched(c):
    c.executescript(SCHEMA)
    for t, cols in COLUMNS.items():
        have = _cols(c, t)
        for k, typ in cols.items():
            if have and k not in have:
                c.execute("ALTER TABLE %s ADD COLUMN %s %s" % (t, k, typ))
    try:
        c.executescript(TRIGGERS)
    except Exception as e:  # never stop start-up
        print("BuildCore: voucher protection not installed: %s" % e)
    if not val(c, "SELECT COUNT(*) FROM sched_calendars"):
        cid = ins(c, "sched_calendars", {"project_id": None, "name": "Nepal 6-day week (Sunday to Friday)",
                                         "week": SC.NEPAL_WEEK, "hours_day": 8, "is_default": 1,
                                         "notes": "Saturday off. 2083 BS public holidays and Dashain / Tihar loaded; "
                                                  "check each year against the government notice."})
        for d, n, k in HOLIDAYS_2083:
            try:
                ins(c, "sched_holidays", {"calendar_id": None, "date": SC.parse_any_date(d), "name": n, "kind": k})
            except Exception:
                pass
        for wt, a, b, why in WINDOWS:
            ins(c, "sched_windows", {"calendar_id": None, "work_type": wt, "bs_from": a, "bs_to": b, "reason": why})
        ins(c, "sched_calendars", {"project_id": None, "name": "7-day week (tunnel / continuous work)",
                                   "week": "1111111", "hours_day": 8, "is_default": 0,
                                   "notes": "Works every day except the holidays listed for all calendars."})
    for k, v in (("sched_near_days", "5"), ("sched_keep_dates", "1"), ("sched_remaining", "performance"),
                 ("contract_notice_days", "28")):
        c.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", (k, v))
    _register_submittals()
    invalidate()


# ───────────────────────── calendars ─────────────────────────
_CAL = {"t": 0, "cals": {}, "default": None, "proj": {}}


def invalidate():
    _CAL["t"] = 0


def load_cals(c, force=False):
    if not force and _CAL["t"] and time.time() - _CAL["t"] < 60:
        return _CAL
    try:
        cals = q(c, "SELECT * FROM sched_calendars")
    except Exception:
        _CAL.update(t=time.time(), cals={}, default=None, proj={})
        return _CAL
    hols = q(c, "SELECT calendar_id, date FROM sched_holidays")
    wins = q(c, "SELECT * FROM sched_windows")
    out = {}
    default = None
    for cal in cals:
        hs = [h["date"] for h in hols if h["calendar_id"] in (None, cal["id"])]
        ws = []
        for w in wins:
            if w["calendar_id"] not in (None, cal["id"]):
                continue
            ws += expand_window(w)
        try:
            weather = json.loads(cal["weather"] or "{}")
        except ValueError:
            weather = {}
        out[cal["id"]] = SC.Calendar(cal["week"], hs, ws, weather, cal["name"], cal["id"])
        if cal["is_default"] and cal["project_id"] is None:
            default = cal["id"]
    if default is None and out:
        default = min(out)
    proj = {}
    if "calendar_id" in _cols(c, "projects"):
        proj = {p["id"]: p["calendar_id"] for p in q(c, "SELECT id, calendar_id FROM projects")}
    _CAL.update(t=time.time(), cals=out, default=default, proj=proj)
    return _CAL


def expand_window(w):
    try:
        fm, fd = [int(x) for x in (w["bs_from"] or "").split("-")]
        tm, td = [int(x) for x in (w["bs_to"] or "").split("-")]
    except ValueError:
        return []
    res = []
    for y in range(2070, 2090):
        try:
            a = SC.bs_to_ad(y, fm, min(fd, SC._lens(y)[fm - 1]))
            y2 = y if (tm, td) >= (fm, fd) else y + 1
            b = SC.bs_to_ad(y2, tm, min(td, SC._lens(y2)[tm - 1]))
            res.append((w["work_type"] or "", a.isoformat(), b.isoformat()))
        except (ValueError, KeyError, IndexError):
            continue
    return res


def cal_for(act, cals=None):
    cals = cals or _CAL
    cid = act.get("calendar_id") or cals["proj"].get(act.get("project_id")) or cals["default"]
    return cals["cals"].get(cid) or SC.Calendar()


def _fresh_cals():
    """planned_fraction() has no database handle; read the calendars on a short-lived connection."""
    if _CAL["t"] and time.time() - _CAL["t"] < 60:
        return _CAL
    try:
        c2 = core.connect()
        try:
            load_cals(c2, True)
        finally:
            c2.close()
    except Exception:
        _CAL["t"] = time.time()
    return _CAL


# ───────────────────────── replacements for the even spread ─────────────────────────
_orig_planned_fraction = P.planned_fraction
_orig_metrics = P.activity_metrics
_orig_tree = P.sched_tree
_orig_prefill = P.dpr_prefill
_orig_reg_save = P.reg_save
_orig_dpr_save = P.dpr_save
_orig_master_save = inv.FUNCS["master.save"][0]
_orig_dv = P.dv


def planned_fraction(a, asof):
    """Share of an activity planned to be done by the end of `asof`, spread over the WORKING days
    of its calendar between the baseline dates (current dates when no baseline exists)."""
    s = a.get("baseline_start") or a.get("planned_start")
    f = a.get("baseline_finish") or a.get("planned_finish")
    if not s or not f:
        return 0.0
    if asof < s:
        return 0.0
    if asof >= f:
        return 1.0
    try:
        cal = cal_for(a, _fresh_cals())
        wt = a.get("work_type") or ""
        so, fo, ao = (date.fromisoformat(s[:10]).toordinal(), date.fromisoformat(f[:10]).toordinal() + 1,
                      date.fromisoformat(asof[:10]).toordinal() + 1)
        tot = cal.wd(so, fo, wt)
        if tot <= 0:
            return _orig_planned_fraction(a, asof)
        return max(0.0, min(1.0, cal.wd(so, ao, wt) / float(tot)))
    except Exception:
        return _orig_planned_fraction(a, asof)


def activity_metrics(c, a, asof):
    m = _orig_metrics(c, a, asof)
    m["avg_forecast"] = m.get("forecast_finish")
    m["avg_delay"] = m.get("delay_days")
    bf = a.get("baseline_finish") or a.get("planned_finish")
    if a.get("actual_finish"):
        m["forecast_finish"] = a["actual_finish"]
    elif a.get("ef"):
        m["forecast_finish"] = a["ef"]
    else:
        return m
    if bf and m["forecast_finish"]:
        m["delay_days"] = (date.fromisoformat(m["forecast_finish"][:10]) - date.fromisoformat(bf[:10])).days
    for k in ("tf", "ff", "es", "ef", "ls", "lf", "near_critical", "remaining_dur"):
        m.setdefault(k, a.get(k))
    return m


def sched_tree(c, u, a):
    ensure(c)
    r = _orig_tree(c, u, a)
    run = q1(c, "SELECT * FROM sched_runs WHERE project_id=? ORDER BY id DESC LIMIT 1", (a["project_id"],))
    if run:
        r["avg_forecast_finish"] = r.get("forecast_finish")
        r["forecast_finish"] = run["finish"]
        r["data_date"] = run["data_date"]
        r["cpm"] = True
        r["critical_count"] = run["critical_count"]
    return r


def dpr_prefill(c, u, a):
    """Today's planned work from the CPM dates: quantity per WORKING day, nothing on holidays."""
    r = _orig_prefill(c, u, a)
    try:
        cals = load_cals(c)
        d = a.get("date") or today()
        o = date.fromisoformat(d).toordinal()
        keep = []
        for w in r["work"]:
            act = q1(c, "SELECT * FROM activities WHERE id=?", (w["activity_id"],)) if w.get("activity_id") else None
            if not act or not act.get("planned_start") or not act.get("planned_finish"):
                keep.append(w)
                continue
            cal = cal_for(act, cals)
            wt = act.get("work_type") or ""
            if not cal.work(o, wt):
                continue
            so = date.fromisoformat(act["planned_start"]).toordinal()
            fo = date.fromisoformat(act["planned_finish"]).toordinal() + 1
            n = cal.wd(max(so, o), fo, wt) or 1
            remaining = max((act["planned_qty"] or 0) - (act["actual_qty"] or 0), 0)
            w["planned_qty"] = r2(remaining / n) if remaining else r2((act["planned_qty"] or 0) / max(cal.wd(so, fo, wt), 1))
            keep.append(w)
        r["work"] = keep
    except Exception:
        pass
    return r


def dv(k, v):
    if k in ("chainage_from", "chainage_to"):
        return None if v in ("", None) else num(v, k)
    return _orig_dv(k, v)


def dpr_save(c, u, a):
    ensure(c)
    a = dict(a)
    a["survey"] = [x for x in (a.get("survey") or []) if x.get("cause") and (num(x.get("hours") or 0) > 0)]
    r = _orig_dpr_save(c, u, a)
    h = a.get("header") or {}
    extra = {}
    for k in ("weather_lost_hours", "rain_mm"):
        if k in h:
            extra[k] = num(h[k]) if h[k] not in ("", None) else None
    if "lost_day" in h:
        extra["lost_day"] = 1 if str(h["lost_day"]) in ("1", "true", "True") else 0
    if extra:
        upd(c, "dpr", r["id"], extra)
    return r


def reg_save(c, u, a):
    """Events: the notice clock starts when the event is logged (roadmap 2.3)."""
    ensure(c)
    t = a.get("table")
    if t == "events":
        row = dict(a.get("row") or {})
        if row.get("activity_ids") and isinstance(row["activity_ids"], list):
            row["activity_ids"] = ",".join(str(x) for x in row["activity_ids"])
        if not row.get("notice_deadline") and not row.get("id"):
            pid = row.get("project_id")
            nd = row.get("notice_days")
            if nd in (None, ""):
                p = q1(c, "SELECT notice_days FROM projects WHERE id=?", (pid,)) if pid else None
                nd = (p or {}).get("notice_days") or float(setting(c, "contract_notice_days") or 28)
            d0 = row.get("date") or today()
            if (row.get("type") or "delay") in ("delay", "instruction", "claim", "eot", "notice"):
                row["notice_deadline"] = (date.fromisoformat(d0[:10]) + timedelta(days=int(float(nd)))).isoformat()
                row.setdefault("notice_days", nd)
        a = dict(a, row=row)
    return _orig_reg_save(c, u, a)


def master_save(c, u, a):
    ensure(c)
    r = _orig_master_save(c, u, a)
    if a.get("table") == "activities" and r and "predecessors" in (a.get("row") or {}):
        missing = sync_links_from_text(c, r)
        r = q1(c, "SELECT * FROM activities WHERE id=?", (r["id"],))
        if missing:
            r["warning"] = "These predecessors were not found in this project and were left out: %s" % ", ".join(missing)
    return r


def _register_submittals():
    if "submittals" not in P.REGISTERS:
        P.REGISTERS["submittals"] = ("project", "SUB", ["project_id", "kind", "title", "ref", "activity_id",
                                                         "required_by", "submitted_date", "review_days", "due_back",
                                                         "returned_date", "status", "revision", "party", "remarks"],
                                     ["project_id", "title"])
    P.REG_NUM.add("review_days")
    for f in ("activity_ids", "notice_days", "notice_sent", "excusable", "compensable", "concurrent", "eot_claimed",
              "eot_granted", "prolongation_cost", "window"):
        if f not in P.REGISTERS["events"][2]:
            P.REGISTERS["events"][2].append(f)
    P.REG_NUM.update({"notice_days", "excusable", "compensable", "concurrent", "eot_claimed", "eot_granted",
                      "prolongation_cost"})


_register_submittals()
if "chainage_from" not in P.DPR_PARTS["work"][1]:
    P.DPR_PARTS["work"][1].extend(["chainage_from", "chainage_to"])
P.DPR_NUM.update({"workers", "cause_no"})
if "survey" not in P.DPR_PARTS:
    P.DPR_PARTS["survey"] = ("dpr_survey", ["cause", "trade_id", "activity_id", "area", "workers", "hours", "remarks"])
    P.DPR_NUM.add("workers")
inv.MASTERS["activities"][1].extend([k for k in ("duration", "calendar_id", "work_type", "weather_sensitive",
                                                 "constraint_type", "constraint_date", "remaining_override", "foreman",
                                                 "crash_dur", "crash_cost", "normal_cost", "dur_opt", "dur_likely",
                                                 "dur_pess", "chainage_from", "chainage_to", "linear_order", "norm_code",
                                                 "act_start_override", "act_finish_override")
                                     if k not in inv.MASTERS["activities"][1]])
inv.NUMERIC |= {"duration", "weather_sensitive", "remaining_override", "crash_dur", "crash_cost", "normal_cost",
                "dur_opt", "dur_likely", "dur_pess", "chainage_from", "chainage_to", "linear_order"}
inv.ID_FIELDS |= {"calendar_id"}
_orig_clean = inv.clean_value


def _clean(k, v):
    if k in ("duration", "weather_sensitive", "remaining_override", "crash_dur", "crash_cost", "normal_cost",
             "dur_opt", "dur_likely", "dur_pess", "chainage_from", "chainage_to", "linear_order") and v in ("", None):
        return None
    return _orig_clean(k, v)


inv.clean_value = _clean

# install the replacements (module globals are looked up at call time, so every caller sees them)
P.planned_fraction = planned_fraction
P.activity_metrics = activity_metrics
P.sched_tree = sched_tree
P.dpr_prefill = dpr_prefill
P.reg_save = reg_save
P.dpr_save = dpr_save
P.dv = dv
for _name, _fn in (("sched.tree", sched_tree), ("dpr.prefill", dpr_prefill), ("reg.save", reg_save),
                   ("dpr.save", dpr_save), ("master.save", master_save)):
    _e = inv.FUNCS[_name]
    inv.FUNCS[_name] = (_fn, _e[1], _e[2], _e[3])
try:
    import api_team
    api_team.VERSION = VERSION
except Exception:
    pass


# ───────────────────────── links ─────────────────────────
def links_text(c, act_id):
    rows = q(c, "SELECT l.type, l.lag, a.code, a.id FROM act_links l JOIN activities a ON a.id=l.pred_id WHERE "
                "l.succ_id=? ORDER BY a.code", (act_id,))
    out = []
    for r in rows:
        s = r["code"] or ("#%d" % r["id"])
        if r["type"] != "FS" or r["lag"]:
            s += " " + r["type"]
        if r["lag"]:
            s += ("+%g" % r["lag"]) if r["lag"] > 0 else ("%g" % r["lag"])
        out.append(s)
    return ", ".join(out)


def sync_links_from_text(c, act):
    """The Predecessors box on the activity form ('A10, B20SS+3') becomes network links."""
    pid = act["project_id"]
    parsed = SC.parse_pred_text(act.get("predecessors"))
    codes = {r["code"]: r["id"] for r in q(c, "SELECT id, code FROM activities WHERE project_id=? AND code IS NOT NULL",
                                             (pid,))}
    missing = []
    c.execute("DELETE FROM act_links WHERE succ_id=?", (act["id"],))
    for code, typ, lag in parsed:
        pid_ = codes.get(code)
        if pid_ is None and code.startswith("#") and code[1:].isdigit():
            pid_ = int(code[1:])
        if pid_ is None or pid_ == act["id"]:
            missing.append(code)
            continue
        ins(c, "act_links", {"project_id": pid, "pred_id": pid_, "succ_id": act["id"], "type": typ, "lag": lag})
    txt = links_text(c, act["id"])
    c.execute("UPDATE activities SET predecessors=? WHERE id=?", (txt or None, act["id"]))
    return missing


@api("sched.links", "project", "view")
def links_list(c, u, a):
    return q(c, "SELECT l.*, p.code pred_code, p.name pred_name, s.code succ_code, s.name succ_name FROM act_links l "
                "JOIN activities p ON p.id=l.pred_id JOIN activities s ON s.id=l.succ_id WHERE l.project_id=? "
                "ORDER BY s.code, p.code", (a["project_id"],))


@api("sched.link_save", "project", "edit")
def link_save(c, u, a):
    r = a.get("row") or {}
    need(r, "pred_id", "succ_id")
    p, s = get(c, "activities", int(r["pred_id"]), "Predecessor"), get(c, "activities", int(r["succ_id"]), "Successor")
    if p["project_id"] != s["project_id"]:
        raise ApiError("Both activities must be in the same project.")
    if p["id"] == s["id"]:
        raise ApiError("An activity cannot follow itself.")
    typ = (r.get("type") or "FS").upper()
    if typ not in SC.LINK_TYPES:
        raise ApiError("Link type must be FS, SS, FF or SF.")
    data = {"project_id": p["project_id"], "pred_id": p["id"], "succ_id": s["id"], "type": typ,
            "lag": num(r.get("lag") or 0, "lag")}
    dup = q1(c, "SELECT id FROM act_links WHERE pred_id=? AND succ_id=? AND id<>?", (p["id"], s["id"], r.get("id") or 0))
    if dup:
        raise ApiError("These two activities are already linked; edit that link instead.")
    if r.get("id"):
        upd(c, "act_links", int(r["id"]), data)
        rid = int(r["id"])
    else:
        rid = ins(c, "act_links", data)
    _check_loops(c, p["project_id"])
    c.execute("UPDATE activities SET predecessors=? WHERE id=?", (links_text(c, s["id"]) or None, s["id"]))
    audit(c, u, "save", "act_links", rid, data)
    return {"id": rid}


def _check_loops(c, pid):
    acts = [{"id": x["id"], "code": x["code"]} for x in q(c, "SELECT id, code FROM activities WHERE project_id=?", (pid,))]
    links = [{"pred": l["pred_id"], "succ": l["succ_id"]} for l in q(c, "SELECT * FROM act_links WHERE project_id=?", (pid,))]
    try:
        SC.topo_order([x["id"] for x in acts], links)
    except SC.ScheduleError as e:
        names = {x["id"]: x["code"] or "#%d" % x["id"] for x in acts}
        cyc = e.args[1] if len(e.args) > 1 and e.args[1] else []
        raise ApiError("That link would make a loop: %s" % " -> ".join(names.get(i, str(i)) for i in cyc))


@api("sched.link_delete", "project", "edit")
def link_delete(c, u, a):
    l = get(c, "act_links", int(a["id"]), "Link")
    c.execute("DELETE FROM act_links WHERE id=?", (l["id"],))
    c.execute("UPDATE activities SET predecessors=? WHERE id=?", (links_text(c, l["succ_id"]) or None, l["succ_id"]))
    audit(c, u, "delete", "act_links", l["id"], l)
    return True


@api("sched.links_paste", "project", "edit")
def links_paste(c, u, a):
    """Rows of 'successor code <tab> predecessor code <tab> type <tab> lag'."""
    pid = int(a["project_id"])
    codes = {r["code"]: r["id"] for r in q(c, "SELECT id, code FROM activities WHERE project_id=?", (pid,))}
    made, errors = 0, []
    for i, line in enumerate((a.get("text") or "").splitlines()):
        parts = [x.strip() for x in line.replace(",", "\t").split("\t")]
        if not parts or not parts[0] or parts[0].lower() in ("successor", "succ", "activity"):
            continue
        s, p = codes.get(parts[0]), codes.get(parts[1] if len(parts) > 1 else "")
        typ = (parts[2] if len(parts) > 2 and parts[2] else "FS").upper()
        try:
            lag = float(parts[3]) if len(parts) > 3 and parts[3] else 0.0
        except ValueError:
            lag = 0.0
        if not s or not p:
            errors.append("line %d: %s" % (i + 1, "activity %s not found" % (parts[0] if not s else parts[1])))
            continue
        if typ not in SC.LINK_TYPES:
            errors.append("line %d: type %s" % (i + 1, typ))
            continue
        if q1(c, "SELECT id FROM act_links WHERE pred_id=? AND succ_id=?", (p, s)):
            continue
        ins(c, "act_links", {"project_id": pid, "pred_id": p, "succ_id": s, "type": typ, "lag": lag})
        made += 1
    _check_loops(c, pid)
    for x in q(c, "SELECT id FROM activities WHERE project_id=?", (pid,)):
        c.execute("UPDATE activities SET predecessors=? WHERE id=?", (links_text(c, x["id"]) or None, x["id"]))
    return {"created": made, "errors": errors}


@api("sched.links_suggest", "project", "edit")
def links_suggest(c, u, a):
    """First-cut logic for a schedule that only has dates: inside each WBS element, each activity
    follows the one that finishes before it starts (FS), or starts with it (SS) when they overlap.
    Existing links are kept. Review the result before relying on it."""
    pid = int(a["project_id"])
    acts = q(c, "SELECT * FROM activities WHERE project_id=? AND planned_start IS NOT NULL ORDER BY wbs_id, planned_start, code",
             (pid,))
    have = {(l["pred_id"], l["succ_id"]) for l in q(c, "SELECT pred_id, succ_id FROM act_links WHERE project_id=?", (pid,))}
    linked_in = {l["succ_id"] for l in q(c, "SELECT succ_id FROM act_links WHERE project_id=?", (pid,))}
    made = []
    by_wbs = {}
    for x in acts:
        by_wbs.setdefault(x["wbs_id"], []).append(x)
    for lst in by_wbs.values():
        for i, x in enumerate(lst):
            if x["id"] in linked_in or i == 0:
                continue
            prev = lst[i - 1]
            typ = "FS" if (prev["planned_finish"] or "") < x["planned_start"] else "SS"
            if (prev["id"], x["id"]) in have:
                continue
            lag = 0
            if typ == "SS":
                lag = max(0, (date.fromisoformat(x["planned_start"]) - date.fromisoformat(prev["planned_start"])).days * 6 // 7)
            ins(c, "act_links", {"project_id": pid, "pred_id": prev["id"], "succ_id": x["id"], "type": typ, "lag": lag})
            made.append("%s -> %s %s%s" % (prev["code"], x["code"], typ, ("+%d" % lag) if lag else ""))
    _check_loops(c, pid)
    for x in acts:
        c.execute("UPDATE activities SET predecessors=? WHERE id=?", (links_text(c, x["id"]) or None, x["id"]))
    return {"created": len(made), "links": made}


# ───────────────────────── calendars API ─────────────────────────
@api("sched.cal_list", "project", "view")
def cal_list(c, u, a):
    pid = a.get("project_id")
    cals = q(c, "SELECT * FROM sched_calendars WHERE project_id IS NULL OR project_id=? ORDER BY project_id, id",
             (pid or 0,))
    for x in cals:
        try:
            x["weather"] = json.loads(x["weather"] or "{}")
        except ValueError:
            x["weather"] = {}
        x["workdays"] = x["week"].count("1")
    hols = q(c, "SELECT * FROM sched_holidays WHERE calendar_id IS NULL OR calendar_id IN (%s) ORDER BY date" %
             ",".join(str(x["id"]) for x in cals) if cals else "SELECT * FROM sched_holidays WHERE 0")
    for hday in hols:
        try:
            hday["bs"] = SC.bs_text(hday["date"])
        except Exception:
            hday["bs"] = ""
    wins = q(c, "SELECT * FROM sched_windows ORDER BY work_type")
    for w in wins:
        ex = [x for x in expand_window(w) if x[1] >= (date.today() - timedelta(days=200)).isoformat()][:2]
        w["next"] = ["%s to %s" % (x[1], x[2]) for x in ex]
    proj = q1(c, "SELECT * FROM projects WHERE id=?", (pid,)) if pid else None
    return {"calendars": cals, "holidays": hols, "windows": wins, "work_types": WORK_TYPES,
            "project_calendar": (proj or {}).get("calendar_id"), "default": load_cals(c, True)["default"]}


@api("sched.cal_save", "project", "edit")
def cal_save(c, u, a):
    r = a.get("row") or {}
    need(r, "name")
    week = "".join("1" if str(x) == "1" else "0" for x in (r.get("week") or SC.NEPAL_WEEK))[:7].ljust(7, "0")
    if "1" not in week:
        raise ApiError("A calendar needs at least one working day a week.")
    data = {"name": r["name"], "week": week, "hours_day": num(r.get("hours_day") or 8), "notes": r.get("notes"),
            "project_id": int(r["project_id"]) if r.get("project_id") else None}
    if "weather" in r:
        w = r["weather"] if isinstance(r["weather"], dict) else json.loads(r["weather"] or "{}")
        data["weather"] = json.dumps({str(int(k)): round(float(v), 2) for k, v in w.items() if v not in ("", None)})
    if r.get("is_default"):
        c.execute("UPDATE sched_calendars SET is_default=0")
        data["is_default"] = 1
    if r.get("id"):
        upd(c, "sched_calendars", int(r["id"]), data)
        rid = int(r["id"])
    else:
        rid = ins(c, "sched_calendars", data)
    audit(c, u, "save", "sched_calendars", rid, data)
    invalidate()
    return {"id": rid}


@api("sched.cal_delete", "project", "approve")
def cal_delete(c, u, a):
    cid = int(a["id"])
    if val(c, "SELECT COUNT(*) FROM activities WHERE calendar_id=?", (cid,)) or \
            val(c, "SELECT COUNT(*) FROM projects WHERE calendar_id=?", (cid,)):
        raise ApiError("Activities or projects use this calendar; move them to another calendar first.")
    c.execute("DELETE FROM sched_holidays WHERE calendar_id=?", (cid,))
    c.execute("DELETE FROM sched_windows WHERE calendar_id=?", (cid,))
    c.execute("DELETE FROM sched_calendars WHERE id=?", (cid,))
    invalidate()
    return True


@api("sched.project_calendar", "project", "edit")
def project_calendar(c, u, a):
    upd(c, "projects", int(a["project_id"]), {"calendar_id": int(a["calendar_id"]) if a.get("calendar_id") else None})
    invalidate()
    return True


@api("sched.hol_save", "project", "edit")
def hol_save(c, u, a):
    """rows: [{date (AD or BS like 2083-07-22), name, kind, calendar_id (blank = all calendars)}]
    or text: one holiday per line 'date<TAB>name'. A range 'from..to' adds every day between."""
    rows = list(a.get("rows") or [])
    for line in (a.get("text") or "").splitlines():
        p = [x.strip() for x in line.replace(",", "\t").split("\t") if x.strip()]
        if p:
            rows.append({"date": p[0], "name": p[1] if len(p) > 1 else "Holiday", "kind": p[2] if len(p) > 2 else "public",
                         "calendar_id": a.get("calendar_id")})
    n, bad = 0, []
    for r in rows:
        try:
            ds = str(r["date"]).split("..")
            d0 = date.fromisoformat(SC.parse_any_date(ds[0]))
            d1 = date.fromisoformat(SC.parse_any_date(ds[1])) if len(ds) > 1 else d0
        except Exception:
            bad.append(str(r.get("date")))
            continue
        cid = int(r["calendar_id"]) if r.get("calendar_id") else None
        d = d0
        while d <= d1:
            if r.get("id"):
                upd(c, "sched_holidays", int(r["id"]), {"date": d.isoformat(), "name": r.get("name"),
                                                          "kind": r.get("kind") or "public", "calendar_id": cid})
            elif not q1(c, "SELECT id FROM sched_holidays WHERE date=? AND calendar_id IS ?", (d.isoformat(), cid)):
                ins(c, "sched_holidays", {"date": d.isoformat(), "name": r.get("name") or "Holiday",
                                          "kind": r.get("kind") or "public", "calendar_id": cid})
            n += 1
            d += timedelta(days=1)
    invalidate()
    if bad and not n:
        raise ApiError("These dates could not be read: %s (use 2026-10-17 or 2083-06-31)" % ", ".join(bad))
    return {"saved": n, "bad": bad}


@api("sched.hol_delete", "project", "edit")
def hol_delete(c, u, a):
    c.execute("DELETE FROM sched_holidays WHERE id=?", (int(a["id"]),))
    invalidate()
    return True


@api("sched.win_save", "project", "edit")
def win_save(c, u, a):
    r = a.get("row") or {}
    need(r, "work_type", "bs_from", "bs_to")
    for k in ("bs_from", "bs_to"):
        try:
            m, d = [int(x) for x in str(r[k]).split("-")]
            assert 1 <= m <= 12 and 1 <= d <= 32
        except Exception:
            raise ApiError("Give the window as BS month-day, e.g. 03-01 for Asar 1.")
    data = {"calendar_id": int(r["calendar_id"]) if r.get("calendar_id") else None, "work_type": r["work_type"],
            "bs_from": r["bs_from"], "bs_to": r["bs_to"], "reason": r.get("reason")}
    rid = upd(c, "sched_windows", int(r["id"]), data) if r.get("id") else ins(c, "sched_windows", data)
    invalidate()
    return {"id": r.get("id") or rid}


@api("sched.win_delete", "project", "edit")
def win_delete(c, u, a):
    c.execute("DELETE FROM sched_windows WHERE id=?", (int(a["id"]),))
    invalidate()
    return True


@api("sched.weather_stats", "project", "view")
def weather_stats(c, u, a):
    """Expected working days lost to weather in each month, learnt from DPR records (Hinze ch. 5):
    a day counts as lost when the DPR says so, when its weather was heavy rain or snow, or when the
    weather delay hours reach half a shift. Averaged over the years on record."""
    pid = a.get("project_id")
    cond = "WHERE d.project_id=?" if pid else ""
    rows = q(c, "SELECT d.id, d.date, d.weather, d.lost_day, d.weather_lost_hours, "
                "(SELECT SUM(hours) FROM dpr_delays x WHERE x.dpr_id=d.id AND x.category='weather') dh FROM dpr d " + cond,
             (pid,) if pid else ())
    shift = float(setting(c, "shift_hours") or 8)
    months = {m: {"month": m, "dpr_days": 0, "rain_days": 0, "lost_days": 0.0, "years": set()} for m in range(1, 13)}
    for r in rows:
        m = int(r["date"][5:7])
        x = months[m]
        x["dpr_days"] += 1
        x["years"].add(r["date"][:4])
        hrs = (r["weather_lost_hours"] or 0) + (r["dh"] or 0)
        rainy = (r["weather"] or "").lower() in ("rain", "heavy rain", "snow")
        if rainy:
            x["rain_days"] += 1
        if r["lost_day"] or (r["weather"] or "").lower() in ("heavy rain", "snow"):
            x["lost_days"] += 1
        elif hrs:
            x["lost_days"] += min(1.0, hrs / shift)
    out = []
    for m in range(1, 13):
        x = months[m]
        yrs = max(len(x["years"]), 1)
        cover = x["dpr_days"] / (26.0 * yrs)
        exp = x["lost_days"] / yrs / cover if cover > 0.25 else None  # scale partly recorded months
        out.append({"month": m, "name": date(2000, m, 1).strftime("%B"), "dpr_days": x["dpr_days"], "years": yrs if x["dpr_days"] else 0,
                    "rain_days": x["rain_days"], "lost_days": round(x["lost_days"], 1),
                    "expected_lost": round(exp, 1) if exp is not None else None})
    if a.get("apply_to"):
        cal = get(c, "sched_calendars", int(a["apply_to"]), "Calendar")
        w = {str(x["month"]): x["expected_lost"] for x in out if x["expected_lost"]}
        upd(c, "sched_calendars", cal["id"], {"weather": json.dumps(w)})
        invalidate()
    return out


# ───────────────────────── CPM run ─────────────────────────
def _o(s):
    return date.fromisoformat(s[:10]).toordinal()


def contract_dates(c, p):
    """Contractual completion (with EOT granted) for the project."""
    base = p.get("completion_date")
    cal = None
    if not base and p.get("ntp_date") and p.get("tfc_days"):
        if (p.get("tfc_basis") or "calendar") == "working":
            cals = load_cals(c)
            cal = cals["cals"].get(p.get("calendar_id") or cals["default"]) or SC.Calendar()
            s = cal.start_up(_o(p["ntp_date"]))
            base = date.fromordinal(cal.advance(s, p["tfc_days"]) - 1).isoformat()
        else:
            base = (date.fromisoformat(p["ntp_date"]) + timedelta(days=int(p["tfc_days"]) - 1)).isoformat()
    if not base:
        base = p.get("end_date")
    eot_ev = val(c, "SELECT SUM(COALESCE(eot_granted,0)) FROM events WHERE project_id=? AND status IN ('agreed','closed')",
                 (p["id"],))
    eot_vo = val(c, "SELECT SUM(COALESCE(time_impact_days,0)) FROM variations WHERE project_id=? AND status='approved'",
                 (p["id"],))
    eot = (eot_ev or 0) + (eot_vo or 0)
    revised = (date.fromisoformat(base) + timedelta(days=int(round(eot)))).isoformat() if base else None
    return {"original": base, "eot_days": r2(eot), "eot_events": r2(eot_ev), "eot_variations": r2(eot_vo),
            "revised": revised}


def build(c, pid, data_date=None, use_progress=True):
    cals = load_cals(c, True)
    proj = get(c, "projects", pid, "Project")
    acts = q(c, "SELECT * FROM activities WHERE project_id=? ORDER BY code, id", (pid,))
    links = q(c, "SELECT * FROM act_links WHERE project_id=?", (pid,))
    has_pred = {l["succ_id"] for l in links}
    keep = (setting(c, "sched_keep_dates") or "1") == "1"
    method = setting(c, "sched_remaining") or "performance"
    dd = data_date or today()
    calmap = {None: cals["cals"].get(proj.get("calendar_id") or cals["default"]) or SC.Calendar()}
    for k, v in cals["cals"].items():
        calmap[k] = v
    A, notes = [], []
    for x in acts:
        cal = calmap.get(x["calendar_id"]) or calmap[None]
        wt = x.get("work_type") or ""
        dur = x.get("duration")
        if dur is None:
            if x.get("planned_start") and x.get("planned_finish") and not x.get("is_milestone"):
                dur = cal.wd(_o(x["planned_start"]), _o(x["planned_finish"]) + 1, wt)
                if dur <= 0:
                    dur = cal.wd(_o(x["planned_start"]), _o(x["planned_finish"]) + 1) or 1
            else:
                dur = 0
        if x.get("is_milestone"):
            dur = 0
        ws = x.get("weather_sensitive")
        weather = bool(ws) if ws is not None else (wt in SENSITIVE)
        a = {"id": x["id"], "code": x["code"], "name": x["name"], "dur": float(dur), "cal": x["calendar_id"] or None,
             "wt": wt, "weather": weather, "milestone": bool(x.get("is_milestone"))}
        ct, cd = (x.get("constraint_type") or "").upper(), x.get("constraint_date")
        if ct == "SNET" and cd:
            a["snet"] = cd
        elif ct == "FNLT" and cd:
            a["fnlt"] = cd
        elif ct == "MSO" and cd:
            a["mso"] = cd
        if keep and x["id"] not in has_pred and x.get("planned_start") and not a.get("snet") and not a.get("mso"):
            a["snet"] = x["planned_start"]
        if wt == "loe" or (not wt and (x.get("unit") or "").strip().lower() in TIME_UNITS and dur >= 120):
            a["loe"] = True   # time-related items (insurance, permits, compliance) never drive the finish
            wt_loe = True
        else:
            wt_loe = False
        if use_progress:
            pq = x.get("planned_qty") or 0
            aq = x.get("actual_qty") or 0
            ast = x.get("act_start_override") or x.get("actual_start")
            afn = x.get("act_finish_override") or x.get("actual_finish")
            if x.get("is_milestone") and x.get("act_finish_override"):
                ast = afn = x["act_finish_override"]
            pct = min(1.0, aq / pq) if pq else (1.0 if afn else 0.0)
            a["pct"] = pct
            if ast and ast <= dd:
                a["actual_start"] = ast
                if afn and afn <= dd:
                    a["actual_finish"] = afn
                else:
                    rem_plan = max(0.0, dur * (1 - pct))
                    rem = rem_plan
                    unit = (x.get("unit") or "").strip().lower()
                    if x.get("remaining_override") is not None:
                        rem = float(x["remaining_override"])
                    elif wt_loe:
                        bf = x.get("baseline_finish") or x.get("planned_finish")
                        rem = max(1, cal.wd(_o(dd), _o(bf) + 1, wt)) if bf else rem_plan
                    elif method == "performance" and pq and aq > 0 and unit not in TIME_UNITS and pct >= 0.1:
                        el = cal.wd(_o(ast), _o(dd) + 1, wt)
                        if el >= 10:
                            rate = aq / el
                            rem_perf = (pq - aq) / rate if rate > 0 else rem_plan
                            rem = min(max(rem_perf, rem_plan * 0.5), max(rem_plan * 2, 1))
                    if pct < 1 and rem < 1:
                        rem = 1
                    a["remaining"] = round(rem)
            elif pct >= 1 and pq:
                notes.append("%s shows full quantity but no start date" % (x["code"] or x["name"]))
        A.append(a)
    L = [{"pred": l["pred_id"], "succ": l["succ_id"], "type": l["type"], "lag": l["lag"]} for l in links]
    cd = contract_dates(c, proj)
    start = proj.get("ntp_date") or proj.get("start_date")
    starts = [a.get("snet") for a in A if a.get("snet")] + [a.get("actual_start") for a in A if a.get("actual_start")]
    if starts:
        start = min([s for s in starts if s] + ([start] if start else []))
    near = proj.get("near_crit_days")
    if near is None:
        near = float(setting(c, "sched_near_days") or 5)
    opts = {"start": start, "data_date": dd if use_progress else None, "finish_target": cd["revised"],
            "near_days": near}
    try:
        res = SC.cpm(A, L, calmap, opts)
    except SC.ScheduleError as e:
        names = {x["id"]: (x["code"] or x["name"]) for x in acts}
        cyc = e.args[1] if len(e.args) > 1 and e.args[1] else []
        raise ApiError("The schedule has a loop: %s. Remove one of these links." % " -> ".join(
            names.get(i, str(i)) for i in cyc) if cyc else str(e))
    return proj, acts, A, res, cd, notes, dd


@api("sched.calc", "project", "edit")
def sched_calc(c, u, a):
    """Calculate the schedule (forward and backward pass) on the data date and write the dates,
    floats and critical flags back to the activities. The first run saves baseline 0 from the
    dates that were there before, so nothing typed earlier is lost."""
    pid = int(a["project_id"])
    dd = a.get("data_date") or today()
    if not q1(c, "SELECT id FROM sched_baselines WHERE project_id=?", (pid,)):
        _save_baseline(c, u, pid, "Baseline 0 - plan before the first CPM run", dd, from_planned=True)
    proj, acts, A, res, cd, notes, dd = build(c, pid, dd, use_progress=not a.get("ignore_progress"))
    byid = {x["id"]: x for x in acts}
    snap = {}
    crit_codes = []
    for ai in A:
        r = res["acts"][ai["id"]]
        s, f, ls, lf = SC.dates_out(r, ai["dur"])
        x = byid[ai["id"]]
        data = {"es": s, "ef": f, "ls": ls, "lf": lf, "tf": r["tf"], "ff": r["ff"], "indep_float": r["if_"],
                "interf_float": r["intf"], "critical": 1 if r["critical"] else 0,
                "near_critical": 1 if r["near"] else 0, "driver_id": r.get("driver"),
                "remaining_dur": r.get("rem"), "pct_complete": round(100 * ai.get("pct", 0), 1),
                "weather_days": r.get("weather_days") or 0}
        if x.get("duration") is None and not x.get("is_milestone"):
            data["duration"] = ai["dur"]
        if r["status"] != "complete":
            data["planned_start"], data["planned_finish"] = s, f
        if not x.get("baseline_start") and x.get("planned_start"):
            data["baseline_start"], data["baseline_finish"] = x["planned_start"], x["planned_finish"]
        upd(c, "activities", ai["id"], data)
        snap[ai["id"]] = [s, f, r["tf"]]
        if r["critical"]:
            crit_codes.append(x["code"] or x["name"])
    prev = q1(c, "SELECT finish FROM sched_runs WHERE project_id=? ORDER BY id DESC LIMIT 1", (pid,))
    finish = SC.iso(res["finish"] - 1)
    warnings = res["warnings"] + notes
    rid = ins(c, "sched_runs", {"project_id": pid, "data_date": dd, "start": SC.iso(res["start"]), "finish": finish,
                                "prev_finish": prev["finish"] if prev else None, "target": cd["revised"],
                                "critical_count": len(crit_codes), "warnings": json.dumps(warnings),
                                "snapshot": json.dumps(snap), "created": now(), "user_id": u["id"],
                                "notes": a.get("notes")})
    upd(c, "projects", pid, {"data_date": dd})
    audit(c, u, "calculate", "schedule", pid, {"finish": finish, "critical": len(crit_codes)})
    ld = ld_exposure(c, proj, finish, cd)
    return {"run_id": rid, "data_date": dd, "finish": finish, "previous_finish": prev["finish"] if prev else None,
            "contract_completion": cd["revised"], "critical": crit_codes, "warnings": warnings,
            "min_float": res["min_tf"], "ld": ld,
            "late_days": (date.fromisoformat(finish) - date.fromisoformat(cd["revised"])).days if cd["revised"] else None}


def ld_exposure(c, proj, finish, cd):
    if not cd.get("revised") or not finish:
        return {"days": 0, "amount": 0, "capped": False}
    days = max(0, (date.fromisoformat(finish) - date.fromisoformat(cd["revised"])).days)
    rate = proj.get("ld_per_day") or 0
    amt = days * rate
    cap = (proj.get("ld_cap_pct") or 0) / 100.0 * (proj.get("contract_value") or 0)
    capped = bool(cap and amt > cap)
    return {"days": days, "rate": rate, "amount": r2(min(amt, cap) if capped else amt), "cap": r2(cap), "capped": capped}


@api("sched.network", "project", "view")
def network(c, u, a):
    pid = int(a["project_id"])
    acts = q(c, "SELECT a.*, w.code wbs_code, w.name wbs_name FROM activities a LEFT JOIN wbs w ON w.id=a.wbs_id "
                "WHERE a.project_id=? ORDER BY COALESCE(a.es, a.planned_start), a.code", (pid,))
    links = q(c, "SELECT * FROM act_links WHERE project_id=?", (pid,))
    run = q1(c, "SELECT * FROM sched_runs WHERE project_id=? ORDER BY id DESC LIMIT 1", (pid,))
    if run:
        run["warnings"] = json.loads(run["warnings"] or "[]")
    base = q1(c, "SELECT * FROM sched_baselines WHERE project_id=? AND is_current=1", (pid,))
    bl = {}
    if base:
        bl = {r["activity_id"]: r for r in q(c, "SELECT * FROM sched_baseline_acts WHERE baseline_id=?", (base["id"],))}
    for x in acts:
        b = bl.get(x["id"])
        x["bl_start"], x["bl_finish"] = (b["start"], b["finish"]) if b else (x.get("baseline_start"), x.get("baseline_finish"))
        x["variance_days"] = ((date.fromisoformat(x["ef"]) - date.fromisoformat(x["bl_finish"])).days
                              if x.get("ef") and x.get("bl_finish") else None)
    proj = get(c, "projects", pid)
    cd = contract_dates(c, proj)
    return {"activities": acts, "links": links, "run": run, "baseline": base, "contract": cd,
            "ld": ld_exposure(c, proj, run["finish"] if run else None, cd), "near_days": proj.get("near_crit_days")
            if proj.get("near_crit_days") is not None else float(setting(c, "sched_near_days") or 5),
            "work_types": WORK_TYPES}


@api("sched.settings", "project", "edit")
def sched_settings(c, u, a):
    for k in ("sched_near_days", "sched_keep_dates", "sched_remaining", "contract_notice_days"):
        if k in a:
            c.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                      (k, str(a[k])))
    return True


# ───────────────────────── contract time register ─────────────────────────
@api("ctime.get", "project", "view")
def ctime_get(c, u, a):
    pid = int(a["project_id"])
    p = get(c, "projects", pid, "Project")
    cd = contract_dates(c, p)
    run = q1(c, "SELECT * FROM sched_runs WHERE project_id=? ORDER BY id DESC LIMIT 1", (pid,))
    finish = run["finish"] if run else None
    ms = q(c, "SELECT m.*, a.code act_code, a.name act_name, a.ef, a.actual_finish, a.tf FROM contract_milestones m "
              "LEFT JOIN activities a ON a.id=m.activity_id WHERE m.project_id=? ORDER BY m.due_date", (pid,))
    for m in ms:
        m["forecast"] = m.get("actual_finish") or m.get("ef")
        m["late_days"] = max(0, (date.fromisoformat(m["forecast"]) - date.fromisoformat(m["due_date"])).days) \
            if m["forecast"] and m["due_date"] else None
        m["ld"] = r2((m["late_days"] or 0) * (m["ld_per_day"] or 0))
    evs = q(c, "SELECT * FROM events WHERE project_id=? ORDER BY date DESC", (pid,))
    t = today()
    clock = []
    for e in evs:
        if e["status"] in ("open",) and e.get("notice_deadline"):
            left = (date.fromisoformat(e["notice_deadline"]) - date.fromisoformat(t)).days
            clock.append({"id": e["id"], "no": e["no"], "title": e["title"], "date": e["date"],
                          "deadline": e["notice_deadline"], "days_left": left, "sent": e.get("notice_sent"),
                          "state": "sent" if e.get("notice_sent") else ("late" if left < 0 else ("due" if left <= 7 else "running"))})
    eot = [e for e in evs if (e.get("eot_claimed") or e.get("eot_granted") or e["type"] == "eot")]
    return {"project": p, "contract": cd, "forecast_finish": finish, "data_date": run["data_date"] if run else None,
            "ld": ld_exposure(c, p, finish, cd), "milestones": ms, "notice_clock": clock, "eot": eot,
            "notice_default": float(setting(c, "contract_notice_days") or 28),
            "days_to_completion": (date.fromisoformat(cd["revised"]) - date.fromisoformat(t)).days if cd["revised"] else None,
            "float_owners": [["", "Not stated"], ["project", "Project (first come, first served)"],
                             ["employer", "Employer"], ["contractor", "Contractor"], ["shared", "Shared / apportioned"]]}


@api("ctime.save", "project", "approve")
def ctime_save(c, u, a):
    pid = int(a["project_id"])
    r = a.get("row") or {}
    data = {}
    for k in ("ntp_date", "completion_date", "tfc_basis", "float_owner", "time_notes"):
        if k in r:
            data[k] = r[k] or None
    for k in ("tfc_days", "ld_per_day", "ld_cap_pct", "notice_days", "near_crit_days", "indirect_per_day"):
        if k in r:
            data[k] = num(r[k], k) if r[k] not in ("", None) else None
    upd(c, "projects", pid, data)
    audit(c, u, "save", "contract_time", pid, data)
    return True


@api("ctime.ms_save", "project", "approve")
def ms_save(c, u, a):
    r = a.get("row") or {}
    need(r, "project_id", "name", "due_date")
    data = {"project_id": int(r["project_id"]), "name": r["name"], "due_date": r["due_date"],
            "activity_id": int(r["activity_id"]) if r.get("activity_id") else None,
            "ld_per_day": num(r.get("ld_per_day") or 0), "section": r.get("section"), "remarks": r.get("remarks")}
    if r.get("id"):
        upd(c, "contract_milestones", int(r["id"]), data)
        return {"id": int(r["id"])}
    return {"id": ins(c, "contract_milestones", data)}


@api("ctime.ms_delete", "project", "approve")
def ms_delete(c, u, a):
    c.execute("DELETE FROM contract_milestones WHERE id=?", (int(a["id"]),))
    return True


@api("ctime.notice_sent", "project", "edit")
def notice_sent(c, u, a):
    e = get(c, "events", int(a["id"]), "Event")
    upd(c, "events", e["id"], {"notice_sent": a.get("date") or today(),
                               "status": "notified" if e["status"] == "open" else e["status"]})
    audit(c, u, "notice", "events", e["id"], {"sent": a.get("date") or today()})
    return True


# ───────────────────────── baselines, updates, as-built ─────────────────────────
def _values(c, pid):
    acts = q(c, "SELECT * FROM activities WHERE project_id=?", (pid,))
    w = P.activity_weights(c, acts)
    tot = 0.0
    budgets = {}
    for x in acts:
        v = None
        if x.get("boq_item_id"):
            ub, _parts = P.unit_budget(c, x["boq_item_id"])
            if ub is not None:
                v = (x["planned_qty"] or 0) * ub
        budgets[x["id"]] = v
        tot += v or 0
    # activities without a budget share the rest by weight so the curve still reaches 100 %
    missing = [i for i, v in budgets.items() if v is None]
    if missing:
        known_w = sum(w.get(i, 0) for i in budgets if budgets[i] is not None)
        per_w = tot / known_w if known_w and tot else 0
        for i in missing:
            budgets[i] = w.get(i, 0) * per_w if per_w else 0.0
    return w, budgets


def _save_baseline(c, u, pid, name, dd, from_planned=False):
    no = (val(c, "SELECT MAX(no) FROM sched_baselines WHERE project_id=?", (pid,), None) or -1) + 1 \
        if q1(c, "SELECT id FROM sched_baselines WHERE project_id=?", (pid,)) else 0
    acts = q(c, "SELECT * FROM activities WHERE project_id=?", (pid,))
    starts = [x["planned_start"] if from_planned else (x.get("es") or x["planned_start"]) for x in acts]
    fins = [x["planned_finish"] if from_planned else (x.get("ef") or x["planned_finish"]) for x in acts]
    c.execute("UPDATE sched_baselines SET is_current=0 WHERE project_id=?", (pid,))
    bid = ins(c, "sched_baselines", {"project_id": pid, "no": no, "name": name, "data_date": dd,
                                     "start": min([s for s in starts if s] or [None]) if any(starts) else None,
                                     "finish": max([f for f in fins if f] or [None]) if any(fins) else None,
                                     "created": now(), "created_by": u["id"] if u else None, "is_current": 1})
    _w, vals = _values(c, pid)
    for x in acts:
        s = x["planned_start"] if from_planned else (x.get("es") or x["planned_start"])
        f = x["planned_finish"] if from_planned else (x.get("ef") or x["planned_finish"])
        ins(c, "sched_baseline_acts", {"baseline_id": bid, "activity_id": x["id"], "start": s, "finish": f,
                                       "dur": x.get("duration"), "tf": x.get("tf"), "value": r2(vals.get(x["id"]) or 0),
                                       "planned_qty": x["planned_qty"], "critical": x.get("critical") or 0})
    return bid


@api("base.list", "project", "view")
def base_list(c, u, a):
    pid = int(a["project_id"])
    bl = q(c, "SELECT * FROM sched_baselines WHERE project_id=? ORDER BY no", (pid,))
    runs = q(c, "SELECT id, data_date, start, finish, prev_finish, target, critical_count, created, user_id, notes "
                "FROM sched_runs WHERE project_id=? ORDER BY id DESC LIMIT 60", (pid,))
    return {"baselines": bl, "updates": runs}


@api("base.save", "project", "approve")
def base_save(c, u, a):
    """Save the current schedule as the next baseline and make it the one progress is measured
    against (planned value, SPI, delay days)."""
    pid = int(a["project_id"])
    if not q1(c, "SELECT id FROM sched_runs WHERE project_id=?", (pid,)):
        raise ApiError("Calculate the schedule first; a baseline is a snapshot of calculated dates.")
    bid = _save_baseline(c, u, pid, a.get("name") or "Baseline", a.get("data_date") or today())
    _apply_baseline(c, pid, bid)
    audit(c, u, "baseline", "schedule", pid, {"baseline": bid})
    return {"id": bid}


def _apply_baseline(c, pid, bid):
    for r in q(c, "SELECT * FROM sched_baseline_acts WHERE baseline_id=?", (bid,)):
        c.execute("UPDATE activities SET baseline_start=?, baseline_finish=? WHERE id=?",
                  (r["start"], r["finish"], r["activity_id"]))


@api("base.set_current", "project", "approve")
def base_set_current(c, u, a):
    b = get(c, "sched_baselines", int(a["id"]), "Baseline")
    c.execute("UPDATE sched_baselines SET is_current=0 WHERE project_id=?", (b["project_id"],))
    upd(c, "sched_baselines", b["id"], {"is_current": 1})
    _apply_baseline(c, b["project_id"], b["id"])
    audit(c, u, "baseline_current", "schedule", b["project_id"], {"baseline": b["id"]})
    return True


@api("base.delete", "project", "approve")
def base_delete(c, u, a):
    b = get(c, "sched_baselines", int(a["id"]), "Baseline")
    if b["is_current"]:
        raise ApiError("Make another baseline current before deleting this one.")
    c.execute("DELETE FROM sched_baseline_acts WHERE baseline_id=?", (b["id"],))
    c.execute("DELETE FROM sched_baselines WHERE id=?", (b["id"],))
    return True


@api("base.compare", "project", "view")
def base_compare(c, u, a):
    """Slipped activities against a baseline, and float change since an earlier update."""
    pid = int(a["project_id"])
    bid = a.get("baseline_id") or val(c, "SELECT id FROM sched_baselines WHERE project_id=? AND is_current=1", (pid,), None)
    acts = {x["id"]: x for x in q(c, "SELECT * FROM activities WHERE project_id=?", (pid,))}
    rows = []
    if bid:
        for b in q(c, "SELECT * FROM sched_baseline_acts WHERE baseline_id=?", (bid,)):
            x = acts.get(b["activity_id"])
            if not x:
                continue
            cur_f = x.get("actual_finish") or x.get("ef") or x.get("planned_finish")
            cur_s = x.get("actual_start") or x.get("es") or x.get("planned_start")
            rows.append({"id": x["id"], "code": x["code"], "name": x["name"], "bl_start": b["start"],
                         "bl_finish": b["finish"], "start": cur_s, "finish": cur_f,
                         "start_var": (date.fromisoformat(cur_s) - date.fromisoformat(b["start"])).days if cur_s and b["start"] else None,
                         "finish_var": (date.fromisoformat(cur_f) - date.fromisoformat(b["finish"])).days if cur_f and b["finish"] else None,
                         "bl_tf": b["tf"], "tf": x.get("tf"), "critical": x.get("critical"),
                         "status": "complete" if x.get("actual_finish") else ("in progress" if x.get("actual_start") else "not started")})
    rows.sort(key=lambda r: -(r["finish_var"] or 0))
    runs = q(c, "SELECT * FROM sched_runs WHERE project_id=? ORDER BY id DESC LIMIT 2", (pid,))
    fchange = []
    if len(runs) == 2 or a.get("run_id"):
        old = q1(c, "SELECT * FROM sched_runs WHERE id=?", (a["run_id"],)) if a.get("run_id") else runs[1]
        cur = runs[0]
        so, sn = json.loads(old["snapshot"] or "{}"), json.loads(cur["snapshot"] or "{}")
        for k, v in sn.items():
            o_ = so.get(k)
            if not o_ or v[2] is None or o_[2] is None:
                continue
            if abs((v[2] or 0) - (o_[2] or 0)) >= 1:
                x = acts.get(int(k))
                if x:
                    fchange.append({"code": x["code"], "name": x["name"], "old_tf": o_[2], "tf": v[2],
                                    "change": v[2] - o_[2], "old_finish": o_[1], "finish": v[1]})
        fchange.sort(key=lambda r: r["change"])
    slipped = [r for r in rows if (r["finish_var"] or 0) > 0]
    return {"rows": rows, "slipped": len(slipped), "float_change": fchange,
            "runs": [{k: r[k] for k in ("id", "data_date", "finish", "critical_count")} for r in runs]}


@api("base.recovery", "project", "view")
def base_recovery(c, u, a):
    """Recovery schedule: activities with negative float and how many days each chain must gain
    to finish on the contract date, with the cheapest ways listed first when crash data exists."""
    pid = int(a["project_id"])
    acts = q(c, "SELECT * FROM activities WHERE project_id=? AND tf IS NOT NULL AND actual_finish IS NULL "
                "ORDER BY tf, es", (pid,))
    neg = [x for x in acts if (x["tf"] or 0) < 0]
    out = []
    for x in neg:
        slope = None
        if x.get("crash_dur") is not None and x.get("duration") and x.get("crash_cost") is not None and \
                x["duration"] > x["crash_dur"]:
            slope = r2(((x["crash_cost"] or 0) - (x["normal_cost"] or 0)) / (x["duration"] - x["crash_dur"]))
        out.append({"id": x["id"], "code": x["code"], "name": x["name"], "tf": x["tf"], "es": x["es"], "ef": x["ef"],
                    "remaining": x.get("remaining_dur"), "gain_needed": -x["tf"],
                    "can_crash": (x["duration"] - x["crash_dur"]) if x.get("crash_dur") is not None and x.get("duration") else None,
                    "cost_per_day": slope, "foreman": x.get("foreman")})
    worst = min([x["tf"] for x in acts] or [0])
    return {"activities": out, "days_to_recover": max(0, -worst),
            "advice": ("Nothing to recover: every activity has zero or positive float." if worst >= 0 else
                       "Gain %d working days on the negative-float chain. Start with activities that have a crash cost "
                       "per day below the LD plus indirect cost per day; then test overtime, a bigger crew or another "
                       "work face in the acceleration calculator." % (-worst))}


@api("base.asbuilt", "project", "view")
def base_asbuilt(c, u, a):
    """As-built schedule made from DPR history: actual start, finish, days worked, and gaps."""
    pid = int(a["project_id"])
    acts = q(c, "SELECT * FROM activities WHERE project_id=? ORDER BY COALESCE(actual_start, planned_start), code", (pid,))
    out = []
    for x in acts:
        days = q(c, "SELECT d.date, SUM(w.actual_qty) q FROM dpr_work w JOIN dpr d ON d.id=w.dpr_id WHERE "
                    "d.status='approved' AND w.activity_id=? AND w.actual_qty>0 GROUP BY d.date ORDER BY d.date", (x["id"],))
        if not days:
            continue
        s, f = days[0]["date"], days[-1]["date"]
        span = (date.fromisoformat(f) - date.fromisoformat(s)).days + 1
        gaps = []
        for p1, p2 in zip(days, days[1:]):
            g = (date.fromisoformat(p2["date"]) - date.fromisoformat(p1["date"])).days - 1
            if g >= 7:
                gaps.append("%s to %s (%d days)" % (p1["date"], p2["date"], g))
        out.append({"id": x["id"], "code": x["code"], "name": x["name"], "start": s, "finish": f if x.get("actual_finish") else None,
                    "last_work": f, "days_worked": len(days), "span": span, "qty": r4(sum(d["q"] for d in days)),
                    "planned_qty": x["planned_qty"], "unit": x["unit"], "bl_start": x.get("baseline_start"),
                    "bl_finish": x.get("baseline_finish"), "gaps": gaps,
                    "days": [[d["date"], d["q"]] for d in days]})
    return out


# ───────────────────────── look-ahead ─────────────────────────
def _week_start(d=None):
    d = date.fromisoformat(d) if d else date.today() + timedelta(days=7)
    return (d - timedelta(days=(d.weekday() + 1) % 7)).isoformat()   # Sunday


def _stock(c, pid):
    st = {r["material_id"]: r["q"] for r in q(c, "SELECT material_id, SUM(qty) q FROM stock_balances WHERE project_id=? "
                                                 "GROUP BY material_id", (pid,))}
    po = {r["material_id"]: r["q"] for r in q(c, "SELECT l.material_id, SUM(l.qty-MIN(l.received_qty,l.qty)) q FROM po_lines l "
                                                 "JOIN po p ON p.id=l.po_id WHERE p.project_id=? AND p.status IN "
                                                 "('approved','partially_received') GROUP BY l.material_id", (pid,))}
    return st, po


@api("look.get", "project", "view")
def look_get(c, u, a):
    """Two or three weeks ahead and one week back, with a constraint check for each task."""
    pid = int(a["project_id"])
    ws = _week_start(a.get("week_start"))
    weeks = int(a.get("weeks") or 3)
    w0 = date.fromisoformat(ws) - timedelta(days=7)
    w1 = date.fromisoformat(ws) + timedelta(days=7 * weeks)
    cals = load_cals(c)
    acts = q(c, "SELECT * FROM activities WHERE project_id=? AND COALESCE(es, planned_start)<? AND "
                "COALESCE(actual_finish, ef, planned_finish)>=? ORDER BY COALESCE(es, planned_start), code",
             (pid, w1.isoformat(), w0.isoformat()))
    stock, onpo = _stock(c, pid)
    mats = {m["id"]: m for m in q(c, "SELECT id, code, name, unit FROM materials")}
    committed = {r["activity_id"]: r for r in q(c, "SELECT * FROM lookahead WHERE project_id=? AND week_start=?", (pid, ws))}
    subs = q(c, "SELECT * FROM submittals WHERE project_id=? AND status NOT IN ('approved','approved_as_noted')", (pid,)) \
        if _has(c, "submittals") else []
    days = [(w0 + timedelta(days=i)) for i in range((w1 - w0).days)]
    need_mat = {}
    rows = []
    for x in acts:
        cal = cal_for(x, cals)
        wt = x.get("work_type") or ""
        s = x.get("es") or x.get("planned_start")
        f = x.get("ef") or x.get("planned_finish")
        so, fo = _o(s), _o(f) + 1
        bar = []
        for d in days:
            o_ = d.toordinal()
            bar.append(2 if (so <= o_ < fo and cal.work(o_, wt)) else (1 if so <= o_ < fo else 0))
        # quantity planned inside the coming weeks (remaining quantity over remaining working days)
        rem_q = max((x["planned_qty"] or 0) - (x["actual_qty"] or 0), 0)
        start_o = max(so, _o(ws))
        tot_days = cal.wd(max(so, date.today().toordinal()), fo, wt) or 1
        in_win = cal.wd(start_o, min(fo, w1.toordinal()), wt) if fo > start_o else 0
        wk1 = cal.wd(start_o, min(fo, _o(ws) + 7), wt) if fo > start_o else 0
        qty_win = r2(rem_q * in_win / tot_days) if rem_q else 0
        qty_wk1 = r2(rem_q * wk1 / tot_days) if rem_q else 0
        checks = []
        # drawings / submittals
        mine = [s_ for s_ in subs if s_["activity_id"] == x["id"]]
        checks.append({"k": "drawings", "label": "Drawings & approvals",
                       "ok": not mine, "why": "; ".join("%s %s (%s)" % (s_["no"] or "", s_["title"], s_["status"]) for s_ in mine)
                       or "No open submittal for this activity"})
        # material from the BOQ item's coefficients
        short = []
        if x.get("boq_item_id") and qty_win:
            for mc in q(c, "SELECT * FROM material_coefficients WHERE boq_item_id=?", (x["boq_item_id"],)):
                req = qty_win * (mc["qty_per_unit"] or 0) * (1 + (mc["wastage_pct"] or 0) / 100)
                need_mat[mc["material_id"]] = need_mat.get(mc["material_id"], 0) + req
                have = (stock.get(mc["material_id"]) or 0) + (onpo.get(mc["material_id"]) or 0)
                if have + EPS < need_mat[mc["material_id"]]:
                    m = mats.get(mc["material_id"]) or {}
                    short.append("%s: need %s, stock + on order %s %s" % (m.get("name"), r2(need_mat[mc["material_id"]]),
                                                                       r2(have), m.get("unit") or ""))
        checks.append({"k": "material", "label": "Material in stock or on order", "ok": not short,
                       "why": "; ".join(short) or ("Covered" if x.get("boq_item_id") else "No material coefficients on the BOQ item")})
        # equipment used on this activity before, and its state now
        eqs = q(c, "SELECT DISTINCT e.id, e.code, e.status FROM dpr_equipment de JOIN equipment e ON e.id=de.equipment_id "
                   "WHERE de.activity_id=?", (x["id"],))
        down = [e["code"] for e in eqs if e["status"] in ("breakdown", "under_maintenance")]
        checks.append({"k": "equipment", "label": "Machines available", "ok": not down,
                       "why": ("Down: " + ", ".join(down)) if down else (("Used before: " + ", ".join(e["code"] for e in eqs[:4])) if eqs else "No machine history; confirm with the equipment manager")})
        # inspection / tests
        holds = val(c, "SELECT COUNT(*) FROM qa_tests WHERE activity_id=? AND status='failed'", (x["id"],)) + \
            val(c, "SELECT COUNT(*) FROM ncrs WHERE activity_id=? AND status='open'", (x["id"],))
        insp_ok = not holds
        why = "Open NCR or failed test" if holds else (("Inspection needed: %s" % x["test_required"]) if x.get("test_required") else "No inspection required")
        checks.append({"k": "inspection", "label": "Inspection booked / no QA hold", "ok": insp_ok, "why": why})
        # predecessors finished or finishing
        open_preds = q(c, "SELECT p.code, p.name, p.ef FROM act_links l JOIN activities p ON p.id=l.pred_id WHERE l.succ_id=? "
                          "AND p.actual_finish IS NULL AND l.type='FS' AND COALESCE(p.ef, p.planned_finish)>=?",
                       (x["id"], ws))
        checks.append({"k": "logic", "label": "Preceding work done", "ok": not open_preds,
                       "why": ", ".join("%s (%s)" % (p_["code"] or p_["name"], p_["ef"]) for p_ in open_preds) or "Ready"})
        cm = committed.get(x["id"])
        manual = json.loads(cm["checks"]) if cm and cm.get("checks") else {}
        for ch in checks:
            if ch["k"] in manual:
                ch["ok"] = bool(manual[ch["k"]])
                ch["manual"] = True
        rows.append({"id": x["id"], "code": x["code"], "name": x["name"], "foreman": (cm or {}).get("foreman") or x.get("foreman"),
                     "es": s, "ef": f, "tf": x.get("tf"), "critical": x.get("critical"), "unit": x["unit"],
                     "remaining_qty": r2(rem_q), "qty_window": qty_win, "qty_week1": qty_wk1,
                     "bar": bar, "checks": checks, "ready": all(ch["ok"] for ch in checks),
                     "committed": bool(cm), "committed_qty": (cm or {}).get("planned_qty"),
                     "location": x.get("location")})
    return {"week_start": ws, "from": w0.isoformat(), "to": (w1 - timedelta(days=1)).isoformat(),
            "days": [d.isoformat() for d in days], "rows": rows,
            "ready": sum(1 for r in rows if r["ready"]), "blocked": sum(1 for r in rows if not r["ready"])}


def _has(c, t):
    return bool(c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (t,)).fetchone())


@api("look.commit", "project", "edit")
def look_commit(c, u, a):
    """Commit next week's plan: the tasks each foreman promises to finish (the PPC base)."""
    pid = int(a["project_id"])
    ws = _week_start(a.get("week_start"))
    keep = set()
    for r in a.get("rows") or []:
        if not r.get("activity_id"):
            continue
        aid = int(r["activity_id"])
        keep.add(aid)
        data = {"project_id": pid, "week_start": ws, "activity_id": aid, "planned_qty": num(r.get("planned_qty") or 0),
                "foreman": r.get("foreman"), "checks": json.dumps(r.get("checks") or {}), "created": now()}
        ex = q1(c, "SELECT id FROM lookahead WHERE project_id=? AND week_start=? AND activity_id=?", (pid, ws, aid))
        if ex:
            upd(c, "lookahead", ex["id"], data)
        else:
            ins(c, "lookahead", data)
        if r.get("foreman"):
            c.execute("UPDATE activities SET foreman=? WHERE id=? AND (foreman IS NULL OR foreman='')", (r["foreman"], aid))
    if a.get("replace"):
        for ex in q(c, "SELECT id, activity_id FROM lookahead WHERE project_id=? AND week_start=?", (pid, ws)):
            if ex["activity_id"] not in keep:
                c.execute("DELETE FROM lookahead WHERE id=?", (ex["id"],))
    audit(c, u, "commit", "lookahead", pid, {"week": ws, "tasks": len(keep)})
    return {"week_start": ws, "tasks": len(keep)}


REASONS = [["materials", "Waiting for materials"], ["tools", "Waiting for tools"], ["design_rework", "Rework: design error"],
           ["field_rework", "Rework: field error"], ["instructions", "Waiting for instructions"],
           ["inspection", "Waiting for inspection"], ["area_not_ready", "Work area not ready"],
           ["overcrowded", "Work area overcrowded"], ["equipment_wait", "Waiting for equipment"],
           ["breakdown", "Equipment breakdown"], ["owner_change", "Owner change"],
           ["interference", "Interference from another crew"], ["weather", "Weather"], ["labour", "Labour shortage"],
           ["other", "Other"]]


@api("look.review", "project", "view")
def look_review(c, u, a):
    """PPC for a committed week: done when approved DPRs reached the promised quantity."""
    pid = int(a["project_id"])
    ws = _week_start(a.get("week_start") or (date.today() - timedelta(days=7)).isoformat())
    we = (date.fromisoformat(ws) + timedelta(days=7)).isoformat()
    rows = q(c, "SELECT l.*, a.code, a.name, a.unit FROM lookahead l JOIN activities a ON a.id=l.activity_id "
                "WHERE l.project_id=? AND l.week_start=? ORDER BY a.code", (pid, ws))
    for r in rows:
        r["actual"] = r4(val(c, "SELECT SUM(w.actual_qty) FROM dpr_work w JOIN dpr d ON d.id=w.dpr_id WHERE "
                                "d.status='approved' AND w.activity_id=? AND d.date>=? AND d.date<?", (r["activity_id"], ws, we)))
        auto = r["actual"] + EPS >= (r["planned_qty"] or 0) and (r["planned_qty"] or 0) > 0 or \
            (not r["planned_qty"] and r["actual"] > 0)
        r["auto_done"] = auto
        r["is_done"] = bool(r["done"]) if r["done"] is not None else auto
    n = len(rows)
    done = sum(1 for r in rows if r["is_done"])
    return {"week_start": ws, "rows": rows, "committed": n, "done": done,
            "ppc": round(100.0 * done / n, 1) if n else None, "reasons": REASONS}


@api("look.mark", "project", "edit")
def look_mark(c, u, a):
    r = get(c, "lookahead", int(a["id"]), "Look-ahead task")
    upd(c, "lookahead", r["id"], {"done": 1 if a.get("done") else 0, "reason": a.get("reason")})
    return True


@api("look.ppc", "project", "view")
def look_ppc(c, u, a):
    pid = int(a["project_id"])
    out = []
    reasons = {}
    for w in q(c, "SELECT DISTINCT week_start FROM lookahead WHERE project_id=? ORDER BY week_start", (pid,)):
        if w["week_start"] > today():
            continue
        r = look_review(c, u, {"project_id": pid, "week_start": w["week_start"]})
        out.append({"week_start": w["week_start"], "committed": r["committed"], "done": r["done"], "ppc": r["ppc"]})
        for x in r["rows"]:
            if not x["is_done"] and x.get("reason"):
                reasons[x["reason"]] = reasons.get(x["reason"], 0) + 1
    labels = dict(REASONS)
    return {"weeks": out, "reasons": sorted([{"reason": labels.get(k, k), "count": v} for k, v in reasons.items()],
                                            key=lambda x: -x["count"])}


# ───────────────────────── cost-loaded S-curves ─────────────────────────
@api("sched.envelope", "project", "view")
def envelope(c, u, a):
    """Early-start and late-start cost curves with the baseline (planned value), earned value and
    actual cost between them (Hinze ch. 7 and 10). Values are the activities' budget cost
    (quantity x rate-analysis unit cost); activities without a budget share by weight."""
    pid = int(a["project_id"])
    cals = load_cals(c)
    acts = q(c, "SELECT * FROM activities WHERE project_id=?", (pid,))
    if not acts:
        return {"points": [], "bac": 0}
    w, vals = _values(c, pid)
    bac = sum(vals.values())
    if bac <= 0:
        vals = {k: v * 100 for k, v in w.items()}
        bac = 100.0
        unit = "%"
    else:
        unit = "money"
    early, late, base = {}, {}, {}
    firsts, lasts = [], []
    for x in acts:
        cal = cal_for(x, cals)
        wt = x.get("work_type") or ""
        v = vals.get(x["id"]) or 0
        for (s, f, bucket) in ((x.get("es") or x.get("planned_start"), x.get("ef") or x.get("planned_finish"), early),
                               (x.get("ls") or x.get("es") or x.get("planned_start"),
                                x.get("lf") or x.get("ef") or x.get("planned_finish"), late),
                               (x.get("baseline_start") or x.get("planned_start"),
                                x.get("baseline_finish") or x.get("planned_finish"), base)):
            if not s or not f:
                continue
            if x.get("actual_start") and bucket is not base:
                # work already done sits where it happened; the rest is spread from the data date
                done = v * min(1.0, (x["actual_qty"] or 0) / x["planned_qty"]) if x.get("planned_qty") else 0
                if done:
                    sp = SC.spread(cal, _o(x["actual_start"]), _o(x.get("actual_finish") or today()) + 1, done, "")
                    for k2, v2 in sp.items():
                        bucket[k2] = bucket.get(k2, 0) + v2
                v_rest = v - done
            else:
                v_rest = v
            if v_rest:
                sp = SC.spread(cal, _o(s), _o(f) + 1, v_rest, wt)
                for k2, v2 in sp.items():
                    bucket[k2] = bucket.get(k2, 0) + v2
            firsts.append(_o(s))
            lasts.append(_o(f))
    if not firsts:
        return {"points": [], "bac": bac}
    d0, d1 = min(firsts), max(lasts + [date.today().toordinal()])
    step = max(7, (d1 - d0) // 60)
    pts = list(range(d0, d1 + 1, step))
    if pts[-1] != d1:
        pts.append(d1)
    ce, cl, cb = SC.cumulative(early, pts), SC.cumulative(late, pts), SC.cumulative(base, pts)
    # earned value and actual cost by date (EV from approved DPR quantities x budget unit cost)
    ev_daily, ac_daily = {}, {}
    for x in acts:
        v = vals.get(x["id"]) or 0
        if not x.get("planned_qty") or not v:
            continue
        per = v / x["planned_qty"]
        for d_ in q(c, "SELECT d.date, SUM(w.actual_qty) qq FROM dpr_work w JOIN dpr d ON d.id=w.dpr_id WHERE "
                       "d.status='approved' AND w.activity_id=? GROUP BY d.date", (x["id"],)):
            k2 = _o(d_["date"])
            ev_daily[k2] = ev_daily.get(k2, 0) + min(d_["qq"] or 0, x["planned_qty"]) * per
    if unit == "money":
        for r in q(c, "SELECT v.date, SUM(l.debit-l.credit) amt FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id "
                      "JOIN accounts x ON x.id=l.account_id WHERE x.type='expense' AND l.project_id=? AND " + P.POSTED +
                      " AND (x.role IS NULL OR x.role<>'equipment_recovery') GROUP BY v.date", (pid,)):
            ac_daily[_o(r["date"])] = ac_daily.get(_o(r["date"]), 0) + (r["amt"] or 0)
        rec = q(c, "SELECT v.date, SUM(l.credit-l.debit) amt FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id "
                   "JOIN accounts x ON x.id=l.account_id WHERE x.role='equipment_recovery' AND l.project_id=? AND " +
                P.POSTED + " GROUP BY v.date", (pid,))
        for r in rec:
            ac_daily[_o(r["date"])] = ac_daily.get(_o(r["date"]), 0) - (r["amt"] or 0)
    t = date.today().toordinal()
    cev = SC.cumulative(ev_daily, pts)
    cac = SC.cumulative(ac_daily, pts) if ac_daily else [None] * len(pts)
    out = []
    for i, p_ in enumerate(pts):
        out.append({"date": SC.iso(p_), "early": r2(ce[i]), "late": r2(cl[i]), "baseline": r2(cb[i]),
                    "ev": r2(cev[i]) if p_ <= t else None, "ac": r2(cac[i]) if (p_ <= t and cac[i] is not None) else None})
    # a straight-line (even spread) curve, shown only for comparison with the old method
    return {"points": out, "bac": r2(bac), "unit": unit,
            "note": "Early and late curves come from the last CPM calculation; the baseline curve is planned value."}


# ───────────────────────── helpers for the pages ─────────────────────────
@api("sched.options", "project", "view")
def sched_options(c, u, a):
    pid = a.get("project_id")
    cals = q(c, "SELECT id, name, project_id, is_default FROM sched_calendars WHERE project_id IS NULL OR project_id=? "
                "ORDER BY id", (pid or 0,))
    return {"calendars": cals, "work_types": WORK_TYPES, "reasons": REASONS,
            "near_days": float(setting(c, "sched_near_days") or 5),
            "keep_dates": setting(c, "sched_keep_dates") or "1", "remaining": setting(c, "sched_remaining") or "performance",
            "notice_days": float(setting(c, "contract_notice_days") or 28), "version": VERSION}


@api("sched.bs", "project", "view")
def bs_convert(c, u, a):
    out = {}
    if a.get("ad"):
        out["bs"] = SC.bs_text(a["ad"])
    if a.get("bs"):
        out["ad"] = SC.parse_any_date(a["bs"])
    return out
