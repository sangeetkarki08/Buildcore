"""
Engineering-finance link and company health (BuildCore 2.24).

Every rupee of project cost lands on a BOQ item (or an indirect head), so what engineering measured and what
accounts recorded can be set side by side, item by item, every month. Built on 2.23 option B (ledger tags for
way of working and segment) and, like 2.17-2.23, purely additive: new tables and run-time wrappers. Nothing here
moves a balance, changes a posting account or edits a ledger line.

  1. Cost codes. One list per project: every BOQ item (direct cost) plus the indirect heads (preliminaries, site
     overhead, temporary works, price adjustment, idle by responsibility, defects, unallocated). Each ledger line is
     coded from the document it came from (DPR gang and machine, logsheet hours, store issue, purchase line,
     subcontract bill line, hire bill by logsheet hours, own-machine running costs by working hours). Codes live
     beside the ledger in cl_alloc (a line may be split over several codes with shares); voucher_lines is untouched.
     Lines posted before 2.24 stay uncoded until the administrator runs the back-fill (preview, apply, undo).
  2. Control budget per BOQ item and cost type from the bid's rate analysis: Original (locked at award), Current
     (plus approved variations and re-plans) and Forecast (recalculated at each monthly close).
  3. Monthly project close: cut-off (end of the Nepali month by default), self-ticking checklist, accruals,
     integrity checks, four signatures, a locked snapshot and a per-project period lock (reopen is logged).
  4. Cost-value reconciliation (CVR) and forecast to complete per BOQ item and per project.
  5. Equipment as an internal business: utilisation, availability, fuel against norm, recovery, break-even hours,
     idle cost by delay responsibility (claimable when the employer caused it).
  6. Material wastage in rupees and subcontract checks against the main contract, carried into the CVR.
  7. Company health: profitability, order book, cash cycle, liquidity, guarantees, debt and compliance, with
     thresholds; project league; returns.
  8. Twelve integrity checks run before every close and on demand; each names the documents that break it.
"""
import json
from datetime import date, timedelta

import core
from core import ApiError, EPS, audit, get, ins, need, now, q, q1, r2, r4, setting, today, upd, val
import api_inventory as inv
from api_inventory import api

VERSION = "2.24.0"
POSTED = "v.status IN ('posted','reversed')"
WAITING = ("(v.status='submitted' AND EXISTS (SELECT 1 FROM post_queue pq WHERE pq.voucher_id=v.id AND "
           "COALESCE(pq.stage,'') NOT IN ('withdrawn','posted')))")

SCHEMA = """
CREATE TABLE IF NOT EXISTS cl_codes(id INTEGER PRIMARY KEY, project_id INTEGER, code TEXT, kind TEXT, boq_item_id INTEGER,
  name TEXT, spread_rule TEXT, delay_resp TEXT, active INTEGER DEFAULT 1, sort INTEGER DEFAULT 0, ts TEXT);
CREATE INDEX IF NOT EXISTS ix_clc_p ON cl_codes(project_id, kind);
CREATE INDEX IF NOT EXISTS ix_clc_b ON cl_codes(boq_item_id);
CREATE TABLE IF NOT EXISTS cl_alloc(line_id INTEGER, cost_code_id INTEGER, share REAL DEFAULT 1, ctype TEXT,
  basis TEXT DEFAULT 'normal', how TEXT DEFAULT 'auto', user_id INTEGER, ts TEXT, PRIMARY KEY(line_id, cost_code_id));
CREATE INDEX IF NOT EXISTS ix_cla_c ON cl_alloc(cost_code_id);
CREATE TABLE IF NOT EXISTS cl_doc_codes(doc TEXT, line_id INTEGER, cost_code_id INTEGER, delay_id INTEGER,
  how TEXT DEFAULT 'manual', user_id INTEGER, ts TEXT, PRIMARY KEY(doc, line_id));
CREATE TABLE IF NOT EXISTS cl_gang_hours(id INTEGER PRIMARY KEY, dpr_id INTEGER, dpr_labour_id INTEGER,
  activity_id INTEGER, idle_resp TEXT, delay_id INTEGER, hours REAL DEFAULT 0, user_id INTEGER, ts TEXT);
CREATE INDEX IF NOT EXISTS ix_clg ON cl_gang_hours(dpr_labour_id);
CREATE TABLE IF NOT EXISTS cl_project(project_id INTEGER PRIMARY KEY, coding_from TEXT, pilot INTEGER DEFAULT 0,
  notes TEXT, user_id INTEGER, ts TEXT);
CREATE TABLE IF NOT EXISTS cl_budget_versions(id INTEGER PRIMARY KEY, project_id INTEGER, kind TEXT, version_no INTEGER,
  status TEXT DEFAULT 'draft', reason TEXT, source TEXT, close_id INTEGER, created_by INTEGER, submitted_by INTEGER,
  submitted_at TEXT, approved_by INTEGER, approved_at TEXT, ts TEXT);
CREATE INDEX IF NOT EXISTS ix_clbv ON cl_budget_versions(project_id, kind);
CREATE TABLE IF NOT EXISTS cl_budget_lines(id INTEGER PRIMARY KEY, version_id INTEGER, cost_code_id INTEGER,
  qty REAL DEFAULT 0, unit_labour REAL DEFAULT 0, unit_material REAL DEFAULT 0, unit_equip_own REAL DEFAULT 0,
  unit_equip_rent REAL DEFAULT 0, unit_subcon REAL DEFAULT 0, unit_other REAL DEFAULT 0, amount REAL,
  way_of_working TEXT, source TEXT, placeholder INTEGER DEFAULT 0, note TEXT);
CREATE INDEX IF NOT EXISTS ix_clbl ON cl_budget_lines(version_id, cost_code_id);
CREATE TABLE IF NOT EXISTS cl_budget_changes(id INTEGER PRIMARY KEY, project_id INTEGER, kind TEXT, cost_code_id INTEGER,
  variation_id INTEGER, before TEXT, after TEXT, reason TEXT, status TEXT DEFAULT 'proposed', proposed_by INTEGER,
  pm_by INTEGER, pm_at TEXT, approved_by INTEGER, approved_at TEXT, ts TEXT);
CREATE TABLE IF NOT EXISTS cl_closes(id INTEGER PRIMARY KEY, project_id INTEGER, period TEXT, from_date TEXT,
  cutoff_date TEXT, status TEXT DEFAULT 'open', signed_qs INTEGER, signed_qs_at TEXT, signed_accounts INTEGER,
  signed_accounts_at TEXT, signed_pm INTEGER, signed_pm_at TEXT, approved_by INTEGER, locked_at TEXT,
  qty_confirmed_by INTEGER, qty_confirmed_at TEXT, accruals_at TEXT, checks_at TEXT, summary TEXT, notes TEXT,
  created_by INTEGER, ts TEXT, UNIQUE(project_id, period));
CREATE TABLE IF NOT EXISTS cl_close_qty(close_id INTEGER, boq_item_id INTEGER, qty_done REAL DEFAULT 0, measured REAL,
  source TEXT, note TEXT, PRIMARY KEY(close_id, boq_item_id));
CREATE TABLE IF NOT EXISTS cl_close_scqty(close_id INTEGER, order_item_id INTEGER, qty_done REAL DEFAULT 0, note TEXT,
  PRIMARY KEY(close_id, order_item_id));
CREATE TABLE IF NOT EXISTS cl_close_lines(close_id INTEGER, cost_code_id INTEGER, qty_done REAL, value_earned REAL,
  cost_posted REAL, cost_waiting REAL, cost_accrued REAL, cost_l REAL, cost_m REAL, cost_e REAL, cost_s REAL,
  cost_o REAL, budget_cost_done REAL, cost_to_complete REAL, eac REAL, forecast_value REAL, wastage_value REAL,
  flags TEXT, data TEXT, PRIMARY KEY(close_id, cost_code_id));
CREATE TABLE IF NOT EXISTS cl_close_accruals(id INTEGER PRIMARY KEY, close_id INTEGER, kind TEXT, source_type TEXT,
  source_id INTEGER, cost_code_id INTEGER, amount REAL DEFAULT 0, voucher_id INTEGER, reversal_id INTEGER, detail TEXT);
CREATE INDEX IF NOT EXISTS ix_clca ON cl_close_accruals(close_id);
CREATE TABLE IF NOT EXISTS cl_close_checks(close_id INTEGER, check_no INTEGER, result TEXT, detail TEXT,
  override_by INTEGER, override_reason TEXT, ts TEXT, PRIMARY KEY(close_id, check_no));
CREATE TABLE IF NOT EXISTS cl_close_reopen_log(id INTEGER PRIMARY KEY, close_id INTEGER, reopened_by INTEGER,
  reason TEXT, at TEXT);
CREATE TABLE IF NOT EXISTS cl_forecast_override(project_id INTEGER, cost_code_id INTEGER, unit_cost REAL, note TEXT,
  user_id INTEGER, ts TEXT, PRIMARY KEY(project_id, cost_code_id));
CREATE TABLE IF NOT EXISTS cl_eq_params(equipment_id INTEGER PRIMARY KEY, planned_hours_year REAL, standby_rate REAL,
  market_hire_rate REAL, fuel_norm REAL, loan_id INTEGER, user_id INTEGER, ts TEXT);
CREATE TABLE IF NOT EXISTS cl_eq_months(equipment_id INTEGER, period TEXT, available_hrs REAL, working_hrs REAL,
  idle_employer REAL, idle_contractor REAL, idle_neutral REAL, breakdown_hrs REAL, fuel_litres REAL, charged REAL,
  actual_cost REAL, recovery REAL, data TEXT, ts TEXT, PRIMARY KEY(equipment_id, period));
CREATE TABLE IF NOT EXISTS cl_health(period TEXT, key TEXT, value REAL, status TEXT, data TEXT, ts TEXT,
  PRIMARY KEY(period, key));
"""

# indirect heads every project gets (kind, code, name, spread rule, delay responsibility)
HEADS = [("prelim", "PRE", "Preliminaries (site establishment, camp, lab, insurance, bonds)", "prelim_items", None),
         ("overhead", "OH", "Site overhead (staff, vehicles, utilities, security, site office)", "value", None),
         ("temp", "TW", "Temporary works (diversions, haul roads, formwork, scaffolding)", "value", None),
         ("pa", "PA", "Price adjustment (escalation)", "none", None),
         ("idle", "IDLE-E", "Idle and delay - employer (claimable)", "never", "employer"),
         ("idle", "IDLE-C", "Idle and delay - contractor (borne)", "never", "contractor"),
         ("idle", "IDLE-N", "Idle and delay - neutral (weather, force majeure)", "never", "neutral"),
         ("defect", "DEF", "Defects and rework (NCR, re-testing)", "never", None),
         ("unallocated", "UNA", "Unallocated (no code yet)", "never", None),
         ("pool", "POOL", "Own equipment pool (charged to items, not project cost)", "never", None)]
KIND_LABEL = {"boq": "BOQ item", "prelim": "Preliminaries", "overhead": "Site overhead", "temp": "Temporary works",
              "pa": "Price adjustment", "idle": "Idle and delay", "defect": "Defects and rework",
              "unallocated": "Unallocated", "pool": "Equipment pool", "opening": "Before coding"}
INDIRECT_ORDER = ["prelim", "overhead", "temp", "pa", "idle", "defect", "unallocated"]
RESP_CODE = {"employer": "IDLE-E", "contractor": "IDLE-C", "neutral": "IDLE-N", "concurrent": "IDLE-C"}
# cost type from the 2.23 way of working
MODE_TYPE = {"direct_labour": "L", "labour_sc": "S", "supplied_sc": "S", "b2b_sc": "S", "sc_other": "S",
             "material": "M", "own_eq": "EO", "rented_eq": "ER", "overhead": "O", "trading": "O"}
TYPES = [("L", "Labour"), ("M", "Material"), ("E", "Equipment"), ("S", "Subcontract"), ("O", "Other")]
PRELIM_WORDS = ("insurance", "guarantee", "bond", "bank charge", "commission", "camp", "establishment", "mobilis")

DEFAULTS = {
    "cl_cutoff": "end",            # 'end' = last day of each Nepali month, or a day number of the Nepali month
    "cl_accrual_post": "0",        # 1 = accounts posts accruals as reversing journals through the posting queue
    "cl_ctc_rule": "actual_after",  # actual_after | budget | pm
    "cl_ctc_pct": "20",
    "cl_spread": "both",           # both = own line and spread by value in a second column | never
    "cl_unalloc_target": "5", "cl_unalloc_block": "10",
    "cl_flag_cpi": "0.95", "cl_flag_done_pct": "20", "cl_flag_margin_drop": "3", "cl_flag_billing_months": "1",
    "cl_fuel_var": "15", "cl_util_low": "50", "cl_util_months": "3", "cl_under_rec": "10",
    "cl_sc_tol": "2", "cl_sc_adv_billed": "80", "cl_chk4_tol": "1", "cl_chk12_over": "10",
    "cl_bg_limit": "", "cl_od_limit": "",
}
HEALTH_DEFAULTS = {
    "margin_amber": 1, "margin_red": 3, "overhead_green": 6, "overhead_red": 10, "pool_red": -5,
    "months_green": 12, "months_red": 6, "unbilled_green": 30, "unbilled_red": 60, "debtor_green": 60,
    "debtor_red": 120, "supplier_lo": 30, "supplier_hi": 60, "supplier_red": 90, "current_green": 1.3,
    "current_red": 1.0, "bg_green": 75, "bg_red": 90, "de_green": 1.5, "de_red": 2.5, "dscr_green": 1.5,
    "dscr_red": 1.1, "trading_plan_pct": 0,
}

# rights: a new "control" row in the 2.20 role templates. Nobody's existing rights change.
CONTROL_RIGHTS = {"director": ["view", "approve", "post", "export"],
                  "finance_manager": ["view", "post", "export"],
                  "accountant": ["view", "edit", "export"],
                  "project_manager": ["view", "create", "edit", "submit", "export"],
                  "quantity_surveyor": ["view", "create", "edit", "submit", "export"],
                  "project_accountant": ["view", "edit", "export"],
                  "equipment_manager": ["view"], "viewer": ["view"]}


def init_costlink(c):
    c.executescript(SCHEMA)
    for k, v in DEFAULTS.items():
        if not _has_setting(c, k):
            _set(c, k, v)
    if not _has_setting(c, "cl_health_thresholds"):
        _set(c, "cl_health_thresholds", json.dumps(HEALTH_DEFAULTS))
    if setting(c, "cl_from") in (None, ""):
        _set(c, "cl_from", int(val(c, "SELECT MAX(id) FROM voucher_lines") or 0))
        _set(c, "cl_installed", today())
    if "control" not in core.MODULES:
        core.MODULES.append("control")
    _seed_rights(c)
    _install()
    try:
        import api_workspace as W
        W.COMPANY_FNS.update({"cl.health", "cl.health_publish", "cl.league", "cl.board", "cl.cvr_all", "cl.accruals",
                              "cl.eq", "cl.eq_detail", "cl.settings_save", "cl.backfill_preview", "cl.backfill_apply",
                              "cl.backfill_undo"})
    except Exception:
        pass


def _has_setting(c, k):
    return q1(c, "SELECT key FROM settings WHERE key=?", (k,)) is not None


def _set(c, k, v):
    c.execute("INSERT OR REPLACE INTO settings(key, value) VALUES(?,?)", (k, str(v)))


def _f(v, d=0.0):
    try:
        return float(v) if v not in (None, "") else d
    except (TypeError, ValueError):
        return d


def sf(c, k):
    return _f(setting(c, k), _f(DEFAULTS.get(k), 0.0))


def _seed_rights(c):
    """Add the 2.24 'control' rights to the built-in role templates once. Existing rights are not touched."""
    if setting(c, "cl_rights_seeded") == "1":
        return
    try:
        have = {r[1] for r in c.execute("PRAGMA table_info(ws_roles)")}
    except Exception:
        have = set()
    if not have:
        return
    for key, acts in CONTROL_RIGHTS.items():
        r = q1(c, "SELECT id, perms FROM ws_roles WHERE key=? AND builtin=1", (key,))
        if not r:
            continue
        try:
            p = json.loads(r["perms"] or "{}")
        except ValueError:
            p = {}
        if "control" in p:
            continue
        p["control"] = acts
        c.execute("UPDATE ws_roles SET perms=? WHERE id=?", (json.dumps(p), r["id"]))
    _set(c, "cl_rights_seeded", "1")
    try:
        import api_workspace as W
        W.load_roles(c)
    except Exception:
        pass


def allowed(c, u, action, module="control"):
    try:
        import api_exec as X
        return X.allowed(c, u, module, action)
    except Exception:
        return bool(u and (u.get("role") == "admin" or core.can(u, module, {"post": "approve", "submit": "edit",
                                                                              "create": "edit"}.get(action, action))))


def need_right(c, u, action, what, module="control"):
    if not allowed(c, u, action, module):
        raise ApiError("Your role cannot %s (needs '%s' on %s in Administration > Users and roles)." % (what, action, module))


def _allowed_projects(c, u):
    try:
        import api_workspace as W
        return W.allowed_projects(c, u) if u else None
    except Exception:
        return None


def _check_project(c, u, pid):
    allow = _allowed_projects(c, u)
    if allow is not None and int(pid) not in allow:
        raise ApiError("PROJECT_DENIED: you are not assigned to this project.")


def _has(c, table):
    return bool(val(c, "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?", (table,)))


def _cols(c, table):
    return {r[1] for r in c.execute("PRAGMA table_info(%s)" % table)}


def projects(c, u=None, active_only=True):
    cond = "COALESCE(kind,'') IN ('','project')"
    if active_only:
        cond += " AND status='active'"
    rows = q(c, "SELECT * FROM projects WHERE " + cond + " ORDER BY code")
    allow = _allowed_projects(c, u) if u else None
    return [r for r in rows if allow is None or r["id"] in allow]


def is_project(c, pid):
    k = val(c, "SELECT COALESCE(kind,'') FROM projects WHERE id=?", (pid,), None)
    return k in ("", "project")


# ───────────────────────────── Nepali months, cut-off ─────────────────────────────
def _SC():
    import sched_calc as SC
    return SC


def bs_period(d):
    y, m, _d = _SC().ad_to_bs(d)
    return "%04d-%02d" % (y, m)


def period_label(p):
    SC = _SC()
    try:
        y, m = int(p[:4]), int(p[5:7])
        return "%s %d" % (SC.BS_MONTHS[m - 1], y)
    except Exception:
        return p


def _shift(p, n):
    y, m = int(p[:4]), int(p[5:7]) + n
    while m > 12:
        y, m = y + 1, m - 12
    while m < 1:
        y, m = y - 1, m + 12
    return "%04d-%02d" % (y, m)


def _cut_in(c, p):
    """Cut-off date (ISO) of a BS period."""
    SC = _SC()
    y, m = int(p[:4]), int(p[5:7])
    n = SC._lens(y)[m - 1]
    rule = (setting(c, "cl_cutoff") or "end").strip()
    day = n if rule == "end" or not rule.isdigit() else min(int(rule), n)
    return SC.bs_to_ad(y, m, day).isoformat()


def period_bounds(c, p):
    cut = _cut_in(c, p)
    prev = _cut_in(c, _shift(p, -1))
    return (date.fromisoformat(prev) + timedelta(days=1)).isoformat(), cut


def period_of_date(c, d):
    """The BS period whose cut-off covers an AD date (with a fixed cut-off day, the 26th belongs to next month)."""
    p = bs_period(d)
    frm, to = period_bounds(c, p)
    if d > to:
        return _shift(p, 1)
    if d < frm:
        return _shift(p, -1)
    return p


def next_month_start(c, d=None):
    p = _shift(period_of_date(c, d or today()), 1)
    return period_bounds(c, p)[0]


# ───────────────────────────── cost code master ─────────────────────────────
def ensure_codes(c, pid):
    """The project's cost code list: one per BOQ item plus the indirect heads. New BOQ items get a code."""
    pid = int(pid)
    have = {(r["kind"], r["code"]): r for r in q(c, "SELECT * FROM cl_codes WHERE project_id=?", (pid,))}
    by_boq = {r["boq_item_id"] for r in have.values() if r["boq_item_id"]}
    t = now()
    for i, (kind, code, name, spread, resp) in enumerate(HEADS):
        if (kind, code) not in have:
            ins(c, "cl_codes", {"project_id": pid, "code": code, "kind": kind, "name": name, "spread_rule": spread,
                                "delay_resp": resp, "active": 1, "sort": 900000 + i, "ts": t})
    for b in q(c, "SELECT id, code, description FROM boq_items WHERE project_id=? ORDER BY code, id", (pid,)):
        if b["id"] not in by_boq:
            ins(c, "cl_codes", {"project_id": pid, "code": b["code"], "kind": "boq", "boq_item_id": b["id"],
                                "name": (b["description"] or "")[:160], "spread_rule": "none", "active": 1,
                                "sort": 0, "ts": t})
    if not q1(c, "SELECT project_id FROM cl_project WHERE project_id=?", (pid,)):
        c.execute("INSERT INTO cl_project(project_id, coding_from, ts) VALUES(?,?,?)", (pid, next_month_start(c), t))


class Codes:
    """Code lookups of the projects touched in one pass."""
    def __init__(self, c):
        self.c = c
        self.p = {}

    def of(self, pid):
        if pid not in self.p:
            ensure_codes(self.c, pid)
            rows = q(self.c, "SELECT * FROM cl_codes WHERE project_id=?", (pid,))
            self.p[pid] = {"boq": {r["boq_item_id"]: r["id"] for r in rows if r["kind"] == "boq"},
                           "code": {r["code"]: r["id"] for r in rows if r["kind"] != "boq"},
                           "rows": {r["id"]: r for r in rows}}
        return self.p[pid]

    def boq(self, pid, bid):
        m = self.of(pid)
        if bid not in m["boq"]:
            self.p.pop(pid, None)
            m = self.of(pid)
        return m["boq"].get(bid)

    def head(self, pid, code):
        return self.of(pid)["code"].get(code)


@api("cl.codes", "project", "view")
def cl_codes(c, u, a):
    """Cost code list of a project with cost to date per code and the unallocated share."""
    need(a, "project_id")
    pid = int(a["project_id"])
    _check_project(c, u, pid)
    ensure_codes(c, pid)
    asof = a.get("as_of") or today()
    cost = {}
    for r in project_cost_rows(c, pid, asof):
        cost[r["code_id"]] = cost.get(r["code_id"], 0) + r["amount"]
    rows = q(c, "SELECT k.*, b.unit, b.qty, b.revised_qty, b.rate, b.revised_rate FROM cl_codes k LEFT JOIN boq_items b "
                "ON b.id=k.boq_item_id WHERE k.project_id=? ORDER BY k.sort, k.code", (pid,))
    for r in rows:
        r["kind_label"] = KIND_LABEL.get(r["kind"], r["kind"])
        r["cost"] = r2(cost.get(r["id"], 0))
    share = unallocated_share(c, pid, asof)
    pr = q1(c, "SELECT * FROM cl_project WHERE project_id=?", (pid,)) or {}
    return {"rows": [r for r in rows if r["kind"] != "pool"], "unallocated": share, "coding_from": pr.get("coding_from"),
            "pilot": pr.get("pilot"), "opening": r2(cost.get(None, 0)),
            "target": sf(c, "cl_unalloc_target"), "block": sf(c, "cl_unalloc_block")}


@api("cl.code_save", "project", "view")
def cl_code_save(c, u, a):
    """Add an indirect head (for example a named temporary work), rename a code or switch it off. BOQ codes follow
    the BOQ and cannot be added here."""
    need_right(c, u, "create", "keep the cost code list")
    r = a.get("row") or {}
    if r.get("id"):
        k = get(c, "cl_codes", int(r["id"]), "Cost code")
        _check_project(c, u, k["project_id"])
        ch = {}
        if r.get("name"):
            ch["name"] = r["name"][:160]
        if "active" in r and k["kind"] not in ("unallocated", "pool", "boq"):
            ch["active"] = 1 if r["active"] in (1, "1", True) else 0
        if "spread_rule" in r and r["spread_rule"] in ("value", "never", "none", "prelim_items"):
            ch["spread_rule"] = r["spread_rule"]
        upd(c, "cl_codes", k["id"], ch)
        audit(c, u, "edit", "cl_codes", k["id"], ch)
        return {"id": k["id"]}
    need(r, "project_id", "kind", "code", "name")
    pid = int(r["project_id"])
    _check_project(c, u, pid)
    if r["kind"] not in ("prelim", "overhead", "temp", "defect"):
        raise ApiError("New codes can be preliminaries, site overhead, temporary works or defects; BOQ items come from the BOQ.")
    if q1(c, "SELECT id FROM cl_codes WHERE project_id=? AND code=?", (pid, r["code"])):
        raise ApiError("Code %s already exists on this project." % r["code"])
    nid = ins(c, "cl_codes", {"project_id": pid, "code": r["code"][:30], "kind": r["kind"], "name": r["name"][:160],
                              "spread_rule": "value" if r["kind"] in ("overhead", "temp") else "never", "active": 1,
                              "sort": 900000 + 50 + val(c, "SELECT COUNT(*) FROM cl_codes WHERE project_id=?", (pid,)),
                              "ts": now()})
    audit(c, u, "create", "cl_codes", nid, r)
    return {"id": nid}


# ───────────────────────────── coding the ledger lines ─────────────────────────────
RECOVERY_ROLES = ("equipment_recovery", "equip_recovery")
CHARGE_ROLES = ("equipment_cost", "equip_job_cost")
LINE_SQL = ("SELECT l.*, v.project_id vproject, v.source, v.source_id, v.date vdate, v.status vstatus, v.reversal_of, "
            "x.role, x.type, x.name aname FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id "
            "JOIN accounts x ON x.id=l.account_id ")


def _M():
    import api_mgmt as M
    return M


def _resp_sql(alias="dd"):
    try:
        import api_exec as X
        return X._resp_sql(alias)
    except Exception:
        return "COALESCE(%s.responsibility,'contractor')" % alias


class Ctx:
    def __init__(self, c):
        self.c = c
        self.codes = Codes(c)
        M = _M()
        M.sync_tags(c)
        self.mg = M._Ctx(c)
        self.kinds = self.mg.kinds
        self.own = {k: (v or "owned") == "owned" for k, v in self.mg.eq.items()}
        self._act, self._inv, self._lab, self._dd, self._norm, self._idx = {}, {}, {}, {}, {}, {}

    # small lookups
    def act_boq(self, aid):
        if aid not in self._act:
            self._act[aid] = val(self.c, "SELECT boq_item_id FROM activities WHERE id=?", (aid,), None)
        return self._act[aid]

    def inv_source(self, iid):
        if iid not in self._inv:
            self._inv[iid] = val(self.c, "SELECT source FROM invoices WHERE id=?", (iid,), None) if iid else None
        return self._inv[iid]

    def code_for_boq(self, pid, bid):
        return self.codes.boq(pid, bid) if bid else None

    def head(self, pid, code):
        return self.codes.head(pid, code)

    def delay_resp(self, delay_id):
        if delay_id not in self._dd:
            self._dd[delay_id] = val(self.c, "SELECT %s FROM dpr_delays dd WHERE dd.id=?" % _resp_sql(), (delay_id,), None)
        return self._dd[delay_id]

    def idle_resp_for(self, pid, d, log_id=None):
        """Who caused idle time on a logsheet row: the linked delay record, else the one responsibility recorded in the
        project's DPR delays that day, else contractor (borne)."""
        if log_id:
            dc = q1(self.c, "SELECT delay_id, cost_code_id FROM cl_doc_codes WHERE doc='logsheet' AND line_id=?", (log_id,))
            if not (dc and dc["delay_id"]):
                dc = q1(self.c, "SELECT k.delay_id FROM cl_doc_codes k JOIN dpr_equipment x ON x.id=k.line_id WHERE "
                                "k.doc='dpr_equipment' AND x.logsheet_id=? AND k.delay_id IS NOT NULL", (log_id,))
            if dc and dc["delay_id"]:
                return self.delay_resp(dc["delay_id"]) or "contractor"
        rs = [r["r"] for r in q(self.c, "SELECT DISTINCT %s r FROM dpr_delays dd JOIN dpr d ON d.id=dd.dpr_id WHERE d.project_id=? "
                                        "AND d.date=?" % _resp_sql(), (pid, d))]
        return rs[0] if len(rs) == 1 else "contractor"

    def idle_code(self, pid, resp):
        return self.head(pid, RESP_CODE.get(resp or "contractor", "IDLE-C"))

    def labour_norm(self, pid, bid):
        """Labour cost per unit of a BOQ item: current control budget, else the item's rate analysis, else its rate."""
        if bid not in self._norm:
            n = None
            cur = current_version(self.c, pid)
            k = self.code_for_boq(pid, bid)
            if cur and k:
                bl = q1(self.c, "SELECT unit_labour FROM cl_budget_lines WHERE version_id=? AND cost_code_id=?", (cur["id"], k))
                n = (bl or {}).get("unit_labour") or None
            if not n:
                try:
                    import api_project as P
                    _ub, parts = P.unit_budget(self.c, bid)
                    n = (parts or {}).get("labour") or None
                except Exception:
                    n = None
            if not n:
                n = val(self.c, "SELECT COALESCE(revised_rate, rate) FROM boq_items WHERE id=?", (bid,), 0) or 0
            self._norm[bid] = n or 0
        return self._norm[bid]

    def pair_index(self, ln, kind):
        """Which source row a ledger line came from, by the order the posting engine wrote them."""
        key = (kind, ln["voucher_id"])
        if key not in self._idx:
            if kind == "dpr":
                lines = [r["id"] for r in q(self.c, "SELECT l.id FROM voucher_lines l JOIN accounts x ON x.id=l.account_id WHERE "
                                                  "l.voucher_id=? AND x.role='labour_cost' AND l.debit>0 ORDER BY l.id", (ln["voucher_id"],))]
                rows = [r for r in q(self.c, "SELECT * FROM dpr_labour WHERE dpr_id=? ORDER BY id", (ln["source_id"],))
                        if not r["party_id"] and (r["amount"] or 0) > 0]
            else:  # store issue: consumption lines in the order of the issue lines
                lines = [r["id"] for r in q(self.c, "SELECT id FROM voucher_lines WHERE voucher_id=? AND debit>0 ORDER BY id",
                                            (ln["voucher_id"],))]
                rows = [r for r in q(self.c, "SELECT * FROM issue_lines WHERE issue_id=? ORDER BY id", (ln["source_id"],))
                        if (r["amount"] or 0) > 0.005]
            self._idx[key] = dict(zip(lines, rows)) if len(lines) == len(rows) else {}
        return self._idx[key].get(ln["id"])


def _parts(weights, ct, basis, how):
    tot = sum(w for w in weights.values() if w > 0)
    if tot <= EPS:
        return []
    return [{"code_id": k, "share": w / tot, "ctype": ct, "basis": basis, "how": how} for k, w in weights.items() if w > 0]


def _log_rows(c, pid, eid, frm, to):
    return q(c, "SELECT id, date, hours, idle_hours, COALESCE(standby_hours,0) standby_hours, breakdown_hours, boq_item_id, "
                "activity_id, status FROM logsheets WHERE equipment_id=? AND project_id=? AND date BETWEEN ? AND ?",
             (eid, pid, frm, to))


def _hours_weights(ctx, pid, logs, with_idle):
    w = {}
    una = ctx.head(pid, "UNA")
    for g in logs:
        bid = g["boq_item_id"] or (ctx.act_boq(g["activity_id"]) if g["activity_id"] else None)
        k = ctx.code_for_boq(pid, bid) or una
        if (g["hours"] or 0) > 0:
            w[k] = w.get(k, 0) + g["hours"]
        idle = (g["idle_hours"] or 0) + (g["standby_hours"] or 0)
        if with_idle and idle > 0:
            ik = ctx.idle_code(pid, ctx.idle_resp_for(pid, g["date"], g["id"]))
            w[ik] = w.get(ik, 0) + idle
    return w


def _eq_hours_split(ctx, pid, eid, d, ct, basis):
    if not eid or not d:
        return []
    w = _hours_weights(ctx, pid, _log_rows(ctx.c, pid, eid, d, d), False)
    if not w:
        w = _hours_weights(ctx, pid, _log_rows(ctx.c, pid, eid, d[:8] + "01", core.month_end(d[:7])), False)
    return _parts(w, ct, basis, "machine_hours")


def _hire_split(ctx, pid, ln, ct):
    eid = ln["equipment_id"]
    d = ln["vdate"]
    if not eid:
        return []
    w = _hours_weights(ctx, pid, _log_rows(ctx.c, pid, eid, d[:8] + "01", core.month_end(d[:7])), True)
    return _parts(w, ct, "normal", "hire_hours")


def _bill_spread(ctx, pid, ln, ct, how):
    w = {}
    for r in q(ctx.c, "SELECT boq_item_id, amount FROM invoice_lines WHERE invoice_id=? AND boq_item_id IS NOT NULL AND amount>0",
               (ln["source_id"],)):
        k = ctx.code_for_boq(pid, r["boq_item_id"])
        if k:
            w[k] = w.get(k, 0) + r["amount"]
    return _parts(w, ct, "normal", how)


def _gang_split(ctx, pid, ln, ct):
    row = ctx.pair_index(ln, "dpr")
    if not row:
        return None
    gh = q(ctx.c, "SELECT * FROM cl_gang_hours WHERE dpr_labour_id=?", (row["id"],))
    una = ctx.head(pid, "UNA")
    if gh:
        w = {}
        for g in gh:
            if g["activity_id"]:
                k = ctx.code_for_boq(pid, ctx.act_boq(g["activity_id"])) or una
            else:
                resp = g["idle_resp"] or (ctx.delay_resp(g["delay_id"]) if g["delay_id"] else None) or "contractor"
                k = ctx.idle_code(pid, resp)
            w[k] = w.get(k, 0) + (g["hours"] or 0)
        return _parts(w, ct, "normal", "gang_hours") or None
    if row["activity_id"]:
        return None  # the line already carries the activity's BOQ item
    # no work line named: spread over the DPR's work lines by quantity x labour norm
    w = {}
    for x in q(ctx.c, "SELECT w.boq_item_id, w.activity_id, w.actual_qty FROM dpr_work w WHERE w.dpr_id=? AND w.actual_qty>0",
               (row["dpr_id"],)):
        bid = x["boq_item_id"] or ctx.act_boq(x["activity_id"])
        k = ctx.code_for_boq(pid, bid)
        if k:
            w[k] = w.get(k, 0) + (x["actual_qty"] or 0) * (ctx.labour_norm(pid, bid) or 1)
    return _parts(w, ct, "normal", "dpr_norm") or None


def basis_of(ctx, ln):
    role = ln["role"] or ""
    if role in RECOVERY_ROLES:
        return "normal" if (ln["source"] == "invoice" and ctx.inv_source(ln["source_id"]) == "sc_bill") else "recovery"
    if role in CHARGE_ROLES:
        return "charge"
    if ln["equipment_id"] and ctx.own.get(ln["equipment_id"], True) and ln["type"] == "expense" \
            and not (ln["source"] == "invoice" and ctx.inv_source(ln["source_id"]) == "hire"):
        return "eq_run"
    return "normal"


def alloc(ctx, ln):
    """The cost codes of one ledger line: [{code_id, share, ctype, basis, how}]. [] = not project cost."""
    pid = ln["project_id"] or ln["vproject"]
    if not pid or (ctx.kinds.get(pid) or "project") not in ("", "project"):
        return []
    role = ln["role"] or ""
    if not (ln["type"] == "expense" or role in RECOVERY_ROLES):
        return []
    mode, _seg = _M().classify(ctx.mg, ln)
    ct = MODE_TYPE.get(mode or "", "O")
    una = ctx.head(pid, "UNA")

    def one(cid, how, basis="normal"):
        return [{"code_id": cid or una, "share": 1.0, "ctype": ct, "basis": basis, "how": how}]
    src = ln["source"] or ""
    if src == "reversal" and ln["source_id"]:
        orig = _reversal_twin(ctx, ln)
        if orig:
            rows = q(ctx.c, "SELECT * FROM cl_alloc WHERE line_id=? AND cost_code_id<>0", (orig["id"],))
            if rows:
                return [{"code_id": r["cost_code_id"], "share": r["share"], "ctype": r["ctype"], "basis": r["basis"],
                         "how": "reversal"} for r in rows]
            got = alloc(ctx, dict(orig, source=orig["source"]))
            if got:
                return [dict(x, how="reversal") for x in got]
    basis = basis_of(ctx, ln)
    if role in RECOVERY_ROLES:
        if basis == "normal":
            return _bill_spread(ctx, pid, ln, ct, "bill_recovery") or one(una, "bill_recovery")
        return one(ctx.head(pid, "POOL"), "eq_recovery", "recovery")
    if basis == "charge":
        bid = ln["boq_item_id"] or (ctx.act_boq(ln["activity_id"]) if ln["activity_id"] else None)
        if bid and ctx.code_for_boq(pid, bid):
            return one(ctx.code_for_boq(pid, bid), "machine_charge", "charge")
        return _eq_hours_split(ctx, pid, ln["equipment_id"], ln["vdate"], ct, "charge") or one(una, "machine_charge", "charge")
    if src == "dpr" and role == "labour_cost":
        g = _gang_split(ctx, pid, ln, ct)
        if g:
            return g
    if ln["boq_item_id"] and ctx.code_for_boq(pid, ln["boq_item_id"]):
        return one(ctx.code_for_boq(pid, ln["boq_item_id"]), "boq", basis)
    if ln["activity_id"]:
        k = ctx.code_for_boq(pid, ctx.act_boq(ln["activity_id"]))
        if k:
            return one(k, "activity", basis)
    isrc = ctx.inv_source(ln["source_id"]) if src == "invoice" else None
    if ln["equipment_id"] and (isrc == "hire" or role == "hire_cost" or not ctx.own.get(ln["equipment_id"], True)):
        h = _hire_split(ctx, pid, ln, ct)
        if h:
            return h
    if isrc == "sc_bill":
        return _bill_spread(ctx, pid, ln, ct, "bill_spread") or one(una, "bill_spread")
    if basis == "eq_run":
        return _eq_hours_split(ctx, pid, ln["equipment_id"], ln["vdate"], ct, "eq_run") or one(una, "machine_no_hours", "eq_run")
    if src == "issue":
        il = ctx.pair_index(ln, "issue")
        if il:
            dc = q1(ctx.c, "SELECT cost_code_id FROM cl_doc_codes WHERE doc='issue_line' AND line_id=?", (il["id"],))
            if dc and dc["cost_code_id"]:
                return one(dc["cost_code_id"], "issue_code")
            if (il["target"] or "") == "overhead":
                return one(ctx.head(pid, "OH"), "issue_overhead")
    if mode == "overhead":
        nm = (ln["aname"] or "").lower() + " " + role.lower()
        if any(w in nm for w in PRELIM_WORDS):
            return one(ctx.head(pid, "PRE"), "overhead_rule")
        return one(ctx.head(pid, "OH"), "overhead_rule")
    return one(una, "none")


def _reversal_twin(ctx, ln):
    orig_lines = q(ctx.c, LINE_SQL + "WHERE l.voucher_id=? ORDER BY l.id", (ln["source_id"],))
    mine = [r["id"] for r in q(ctx.c, "SELECT id FROM voucher_lines WHERE voucher_id=? ORDER BY id", (ln["voucher_id"],))]
    if len(orig_lines) != len(mine):
        return None
    try:
        return orig_lines[mine.index(ln["id"])]
    except ValueError:
        return None


def _store(c, line_id, parts, how_default="auto", user=None):
    t = now()
    c.execute("DELETE FROM cl_alloc WHERE line_id=?", (line_id,))
    if not parts:
        c.execute("INSERT OR REPLACE INTO cl_alloc(line_id, cost_code_id, share, how, ts) VALUES(?,0,0,'none',?)", (line_id, t))
        return
    merged = {}
    for p in parts:
        m = merged.setdefault(p["code_id"], dict(p, share=0.0))
        m["share"] += p["share"]
    for p in merged.values():
        c.execute("INSERT INTO cl_alloc(line_id, cost_code_id, share, ctype, basis, how, user_id, ts) VALUES(?,?,?,?,?,?,?,?)",
                  (line_id, p["code_id"], round(p["share"], 10), p["ctype"], p["basis"], p.get("how") or how_default,
                   user["id"] if user else None, t))


def sync(c):
    """Code every ledger line posted since 2.24 was installed (lines of the posting queue once they are posted)."""
    frm = int(_f(setting(c, "cl_from"), 0))
    scanned = int(_f(setting(c, "cl_scanned"), frm))
    rows = q(c, LINE_SQL + "WHERE l.id>? ORDER BY l.id LIMIT 200000", (max(scanned, frm),))
    late = q(c, LINE_SQL + "JOIN post_queue pq ON pq.voucher_id=v.id WHERE pq.stage='posted' AND l.id>? AND " + POSTED +
             " AND NOT EXISTS (SELECT 1 FROM cl_alloc a WHERE a.line_id=l.id)", (frm,)) if _has(c, "post_queue") else []
    todo = [r for r in rows if r["vstatus"] in ("posted", "reversed")] + late
    if todo:
        ctx = Ctx(c)
        for ln in todo:
            if q1(c, "SELECT line_id FROM cl_alloc WHERE line_id=? AND how='manual'", (ln["id"],)):
                continue
            _store(c, ln["id"], alloc(ctx, ln))
    if rows:
        _set(c, "cl_scanned", rows[-1]["id"])
    return len(todo)


def invalidate(c, vids):
    """Recode the lines of these vouchers (after a DPR's gang hours or a logsheet's delay link change)."""
    vids = [int(v) for v in vids if v]
    if not vids:
        return 0
    frm = int(_f(setting(c, "cl_from"), 0))
    ctx = Ctx(c)
    n = 0
    for ln in q(c, LINE_SQL + "WHERE l.voucher_id IN (%s) AND l.id>? AND " % ",".join("?" * len(vids)) + POSTED, vids + [frm]):
        if q1(c, "SELECT line_id FROM cl_alloc WHERE line_id=? AND how='manual'", (ln["id"],)):
            continue
        _store(c, ln["id"], alloc(ctx, ln))
        n += 1
    return n


def eq_mode(c):
    return setting(c, "mg_eq_costing") or "actual"


def _keep(basis, mode):
    if basis == "recovery":
        return False
    if mode == "rate":
        return basis != "eq_run"
    return basis != "charge"


def project_cost_rows(c, pid, asof, frm=None, include_waiting=True, with_lines=False):
    """Project cost, one row per (ledger line, code): code_id None = posted before coding started (not split).
    status 'posted' or 'waiting'. Own equipment follows the 2.23 costing switch (actual running costs or rate)."""
    sync(c)
    pid = int(pid)
    mode = eq_mode(c)
    cfrom = int(_f(setting(c, "cl_from"), 0))
    cond = ["COALESCE(l.project_id, v.project_id)=?", "v.date<=?", "(x.type='expense' OR x.role IN ('equipment_recovery','equip_recovery'))",
            "COALESCE(v.source,'') NOT IN ('cl_accrual','cl_accrual_rev')"]
    p = [pid, asof]
    if frm:
        cond.append("v.date>=?")
        p.append(frm)
    out = []
    ctx = None
    posted = q(c, LINE_SQL + "WHERE " + " AND ".join(cond) + " AND " + POSTED + " ORDER BY l.id", p)
    allocs = {}
    if posted:
        ids = [r["id"] for r in posted]
        for i in range(0, len(ids), 900):
            chunk = ids[i:i + 900]
            for a in q(c, "SELECT * FROM cl_alloc WHERE line_id IN (%s)" % ",".join("?" * len(chunk)), chunk):
                allocs.setdefault(a["line_id"], []).append(a)
    for ln in posted:
        amt = (ln["debit"] or 0) - (ln["credit"] or 0)
        al = allocs.get(ln["id"])
        if al is None:
            if ctx is None:
                ctx = Ctx(c)
            if ln["id"] <= cfrom:  # before 2.24: one opening line, not split (until the back-fill)
                b = basis_of(ctx, ln)
                if _keep(b, mode) and (ctx.kinds.get(pid) or "project") in ("", "project"):
                    out.append(_row(ln, None, amt, "O", b, "opening", "posted"))
                continue
            al = [{"cost_code_id": x["code_id"], "share": x["share"], "ctype": x["ctype"], "basis": x["basis"], "how": x["how"]}
                  for x in alloc(ctx, ln)]
        for a in al:
            if not a["cost_code_id"] or not _keep(a["basis"], mode):
                continue
            out.append(_row(ln, a["cost_code_id"], amt * a["share"], a["ctype"], a["basis"], a["how"], "posted"))
    if include_waiting and _has(c, "post_queue"):
        wl = q(c, LINE_SQL + "WHERE " + " AND ".join(cond) + " AND " + WAITING.replace("v.", "v.") + " ORDER BY l.id", p)
        if wl:
            ctx = ctx or Ctx(c)
            for ln in wl:
                amt = (ln["debit"] or 0) - (ln["credit"] or 0)
                for a in alloc(ctx, ln):
                    if _keep(a["basis"], mode):
                        out.append(_row(ln, a["code_id"], amt * a["share"], a["ctype"], a["basis"], a["how"], "waiting"))
    return out


def _row(ln, code_id, amount, ctype, basis, how, status):
    return {"line_id": ln["id"], "voucher_id": ln["voucher_id"], "date": ln["vdate"], "code_id": code_id,
            "amount": amount, "ctype": "E" if ctype in ("EO", "ER") else (ctype or "O"), "eq": ctype, "basis": basis,
            "how": how, "status": status, "account": ln["aname"], "source": ln["source"], "source_id": ln["source_id"],
            "narration": ln["narration"]}


def unallocated_share(c, pid, asof, rows=None):
    rows = rows if rows is not None else project_cost_rows(c, pid, asof)
    una = val(c, "SELECT id FROM cl_codes WHERE project_id=? AND code='UNA'", (pid,), None)
    coded = sum(r["amount"] for r in rows if r["code_id"])
    u_ = sum(r["amount"] for r in rows if r["code_id"] == una)
    return {"amount": r2(u_), "total": r2(coded), "pct": round(100 * u_ / coded, 2) if abs(coded) > EPS else 0.0}


# ───────────────────────────── coding on the source documents ─────────────────────────────
def coding_from(c, pid):
    ensure_codes(c, pid)
    return val(c, "SELECT coding_from FROM cl_project WHERE project_id=?", (pid,), None) or "9999-12-31"


def coding_on(c, pid, d):
    return bool(pid) and is_project(c, pid) and (d or today()) >= coding_from(c, pid)


def _code_row(c, cid):
    return q1(c, "SELECT * FROM cl_codes WHERE id=?", (cid,)) if cid else None


def _doc_code(c, doc, line_id):
    return q1(c, "SELECT * FROM cl_doc_codes WHERE doc=? AND line_id=?", (doc, line_id))


def dpr_problems(c, d):
    """Gangs and machines on a DPR whose hours are not linked to a work line or to Idle (Module 1 control)."""
    out = []
    delays = q(c, "SELECT dd.id, %s resp FROM dpr_delays dd WHERE dd.dpr_id=?" % _resp_sql(), (d["id"],))
    resps = {x["resp"] for x in delays}
    for g in q(c, "SELECT l.*, t.name trade FROM dpr_labour l LEFT JOIN trades t ON t.id=l.trade_id WHERE l.dpr_id=? ORDER BY l.id",
               (d["id"],)):
        hrs = (g["hours"] or 0)
        if hrs <= 0 or not (g["count"] or 0):
            continue
        gh = q(c, "SELECT * FROM cl_gang_hours WHERE dpr_labour_id=?", (g["id"],))
        if gh:
            tot = sum(x["hours"] or 0 for x in gh)
            if abs(tot - hrs) > 0.01:
                out.append({"kind": "gang", "id": g["id"], "what": "%s x%s: %s of %s hours linked" % (g["trade"] or "Gang", g["count"], r2(tot), r2(hrs))})
            for x in gh:
                if not x["activity_id"] and not (x["idle_resp"] or x["delay_id"]):
                    out.append({"kind": "gang", "id": g["id"], "what": "%s x%s: idle hours need the delay that caused them" % (g["trade"] or "Gang", g["count"])})
        elif not g["activity_id"]:
            out.append({"kind": "gang", "id": g["id"], "what": "%s x%s: %s hours not linked to a work line or to Idle" % (g["trade"] or "Gang", g["count"], r2(hrs))})
    for e in q(c, "SELECT x.*, q.code FROM dpr_equipment x LEFT JOIN equipment q ON q.id=x.equipment_id WHERE x.dpr_id=? ORDER BY x.id",
               (d["id"],)):
        if (e["hours"] or 0) > 0 and not e["activity_id"]:
            out.append({"kind": "machine", "id": e["id"], "what": "%s: %s working hours not linked to a work line" % (e["code"] or "Machine", r2(e["hours"]))})
        if (e["idle_hours"] or 0) > 0:
            dc = _doc_code(c, "dpr_equipment", e["id"])
            if not (dc and dc["delay_id"]) and len(resps) != 1:
                out.append({"kind": "machine_idle", "id": e["id"], "what": "%s: %s idle hours need the delay that caused them%s" %
                            (e["code"] or "Machine", r2(e["idle_hours"]), "" if delays else " (add the delay on the DPR)")})
    return out


def _doc_lines_problems(c, doc, rows):
    bad = []
    for r in rows:
        if r.get("boq_item_id"):
            continue
        dc = _doc_code(c, doc, r["id"])
        if not (dc and dc["cost_code_id"]):
            bad.append(r)
    return bad


def _refuse(what, items, where="Commercial › Cost codes › Waiting for a code"):
    raise ApiError("%s cannot go ahead without a cost code: %s. Choose the BOQ item or the indirect head (%s)." %
                   (what, "; ".join(items[:6]) + (" and %d more" % (len(items) - 6) if len(items) > 6 else ""), where))


_ORIG = {}


def _wrap(name, factory):
    cur = inv.FUNCS.get(name)
    if not cur or getattr(cur[0], "_bco224", False):
        return
    w = factory(cur[0])
    w._bco224 = True
    for flag in ("_bco219", "_bco220", "_bco221", "_bco223"):
        if getattr(cur[0], flag, False):
            setattr(w, flag, True)
    inv.FUNCS[name] = (w, cur[1], cur[2], cur[3])


def _dpr_submit_w(orig):
    def dpr_submit2(c, u, a):
        d = get(c, "dpr", int(a["id"]), "DPR")
        if coding_on(c, d["project_id"], d["date"]):
            pr = dpr_problems(c, d)
            if pr:
                raise ApiError("This DPR cannot be submitted yet: " + "; ".join(x["what"] for x in pr[:6]) +
                               ". Link each gang and machine to a work line, or to Idle with the delay that caused it "
                               "(Commercial › Cost codes › Waiting for a code, or the DPR's own work lines).")
        return orig(c, u, a)
    return dpr_submit2


def _mrq_approve_w(orig):
    def mrq_approve2(c, u, a):
        m = get(c, "mrq", int(a["id"]), "Requisition")
        if coding_on(c, m["project_id"], m["date"]):
            rows = q(c, "SELECT l.*, x.name mname FROM mrq_lines l JOIN materials x ON x.id=l.material_id WHERE l.mrq_id=?", (m["id"],))
            bad = _doc_lines_problems(c, "mrq_line", rows)
            if bad:
                _refuse("Requisition %s" % (m["no"] or ""), [b["mname"] for b in bad])
        return orig(c, u, a)
    return mrq_approve2


def _pr_approve_w(orig):
    def pr_approve2(c, u, a):
        p = get(c, "pr", int(a["id"]), "Purchase request")
        if coding_on(c, p["project_id"], p["date"]):
            rows = q(c, "SELECT * FROM pr_lines WHERE pr_id=?", (p["id"],))
            for r in rows:  # a code given on the requisition line comes down the chain
                if not r["boq_item_id"] and r.get("mrq_line_id") and not _doc_code(c, "pr_line", r["id"]):
                    dc = _doc_code(c, "mrq_line", r["mrq_line_id"])
                    if dc and dc["cost_code_id"]:
                        _set_doc_code(c, None, "pr_line", r["id"], dc["cost_code_id"], None, "chain")
            bad = _doc_lines_problems(c, "pr_line", rows)
            if bad:
                _refuse("Purchase request %s" % (p["no"] or ""), [b["description"] or "line %s" % b["id"] for b in bad])
        return orig(c, u, a)
    return pr_approve2


def _sco_approve_w(orig):
    def sco_approve2(c, u, a):
        o = get(c, "sc_orders", int(a["id"]), "Work order")
        if coding_on(c, o["project_id"], o["date"] or today()):
            rows = q(c, "SELECT * FROM sc_order_items WHERE order_id=?", (o["id"],))
            bad = _doc_lines_problems(c, "sc_item", rows)
            if bad:
                _refuse("Work order %s" % (o["no"] or ""), [b["description"] or "line %s" % b["id"] for b in bad],
                        "Commercial › Subcontract work orders: main BOQ item per line, or Cost codes › Waiting for a code")
        return orig(c, u, a)
    return sco_approve2


def _issue_post_w(orig):
    def issue_post2(c, u, a):
        d = get(c, "issues", int(a["id"]), "Issue")
        for il in q(c, "SELECT * FROM issue_lines WHERE issue_id=?", (d["id"],)):
            if il.get("mrq_line_id") and not il["boq_item_id"] and not _doc_code(c, "issue_line", il["id"]):
                dc = _doc_code(c, "mrq_line", il["mrq_line_id"])
                if dc and dc["cost_code_id"]:
                    _set_doc_code(c, None, "issue_line", il["id"], dc["cost_code_id"], None, "chain")
        r = orig(c, u, a)
        return r
    return issue_post2


def _var_decide_w(orig):
    def var_decide2(c, u, a):
        r = orig(c, u, a)
        v = get(c, "variations", int(a["id"]), "Variation")
        if v["status"] == "approved":
            try:
                variation_to_budget(c, u, v)
            except ApiError:
                pass
        return r
    return var_decide2


DOC_RIGHTS = {"mrq_line": ("inventory", "edit"), "pr_line": ("procurement", "edit"), "issue_line": ("inventory", "edit"),
              "sc_item": ("commercial", "edit"), "logsheet": ("equipment", "edit"), "dpr_equipment": ("project", "edit")}
DOC_TABLE = {"mrq_line": "mrq_lines", "pr_line": "pr_lines", "issue_line": "issue_lines", "sc_item": "sc_order_items",
             "logsheet": "logsheets", "dpr_equipment": "dpr_equipment"}


def _doc_project(c, doc, line_id):
    sql = {"mrq_line": "SELECT h.project_id FROM mrq_lines l JOIN mrq h ON h.id=l.mrq_id WHERE l.id=?",
           "pr_line": "SELECT h.project_id FROM pr_lines l JOIN pr h ON h.id=l.pr_id WHERE l.id=?",
           "issue_line": "SELECT h.project_id FROM issue_lines l JOIN issues h ON h.id=l.issue_id WHERE l.id=?",
           "sc_item": "SELECT h.project_id FROM sc_order_items l JOIN sc_orders h ON h.id=l.order_id WHERE l.id=?",
           "logsheet": "SELECT project_id FROM logsheets WHERE id=?",
           "dpr_equipment": "SELECT h.project_id FROM dpr_equipment l JOIN dpr h ON h.id=l.dpr_id WHERE l.id=?"}[doc]
    return val(c, sql, (line_id,), None)


def _set_doc_code(c, u, doc, line_id, code_id, delay_id, how="manual"):
    c.execute("INSERT OR REPLACE INTO cl_doc_codes(doc, line_id, cost_code_id, delay_id, how, user_id, ts) VALUES(?,?,?,?,?,?,?)",
              (doc, line_id, code_id, delay_id, how, u["id"] if u else None, now()))


@api("cl.doc_code_set", "project", "view")
def cl_doc_code_set(c, u, a):
    """Give source-document lines their cost code (a BOQ item or an indirect head), or link idle hours to a delay."""
    doc = a.get("doc")
    if doc not in DOC_TABLE:
        raise ApiError("Unknown document line.")
    mod, act = DOC_RIGHTS[doc]
    if not (core.can(u, mod, act) or allowed(c, u, "edit")):
        raise ApiError("Your role cannot code %s lines (needs %s %s)." % (doc.replace("_", " "), act, mod))
    ids = [int(x) for x in (a.get("line_ids") or [a.get("line_id")]) if x]
    code_id = int(a["cost_code_id"]) if a.get("cost_code_id") else None
    delay_id = int(a["delay_id"]) if a.get("delay_id") else None
    n = 0
    touched = set()
    for lid in ids:
        pid = _doc_project(c, doc, lid)
        if not pid:
            continue
        _check_project(c, u, pid)
        k = _code_row(c, code_id)
        if k and k["project_id"] != pid:
            raise ApiError("That cost code belongs to another project.")
        if k and k["kind"] == "boq" and doc in ("mrq_line", "pr_line", "sc_item"):
            # a BOQ item goes on the line itself, so it is copied down the chain as before
            row = q1(c, "SELECT * FROM %s WHERE id=?" % DOC_TABLE[doc], (lid,))
            if doc == "mrq_line" and (row.get("issued_qty") or 0) > EPS:
                raise ApiError("This requisition line is already issued; code the issue instead.")
            c.execute("UPDATE %s SET boq_item_id=? WHERE id=?" % DOC_TABLE[doc], (k["boq_item_id"], lid))
            c.execute("DELETE FROM cl_doc_codes WHERE doc=? AND line_id=?", (doc, lid))
        else:
            _set_doc_code(c, u, doc, lid, code_id, delay_id)
        if doc == "dpr_equipment":
            lg = val(c, "SELECT logsheet_id FROM dpr_equipment WHERE id=?", (lid,), None)
            if lg and delay_id:
                _set_doc_code(c, u, "logsheet", lg, None, delay_id)
                touched.add(lg)
        if doc == "logsheet":
            touched.add(lid)
        if doc == "issue_line":
            touched.add(("issue", val(c, "SELECT issue_id FROM issue_lines WHERE id=?", (lid,), None)))
        n += 1
    _recode_after(c, touched)
    audit(c, u, "code", "cl_doc_codes", None, {"doc": doc, "lines": ids[:50], "code": code_id, "delay": delay_id})
    return {"coded": n}


def _recode_after(c, touched):
    vids = set()
    for t in touched:
        if isinstance(t, tuple):
            v = val(c, "SELECT voucher_id FROM issues WHERE id=?", (t[1],), None)
            if v:
                vids.add(v)
            continue
        lg = q1(c, "SELECT * FROM logsheets WHERE id=?", (t,))
        if not lg:
            continue
        m0, m1 = lg["date"][:8] + "01", core.month_end(lg["date"][:7])
        for r in q(c, "SELECT DISTINCT l.voucher_id FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id WHERE "
                      "l.equipment_id=? AND v.date BETWEEN ? AND ?", (lg["equipment_id"], m0, m1)):
            vids.add(r["voucher_id"])
    invalidate(c, list(vids))


@api("cl.dpr_coding", "project", "view")
def cl_dpr_coding(c, u, a):
    d = get(c, "dpr", int(a["dpr_id"]), "DPR")
    _check_project(c, u, d["project_id"])
    gangs = q(c, "SELECT l.*, t.name trade, p.name party FROM dpr_labour l LEFT JOIN trades t ON t.id=l.trade_id LEFT JOIN parties p "
                 "ON p.id=l.party_id WHERE l.dpr_id=? ORDER BY l.id", (d["id"],))
    for g in gangs:
        g["split"] = q(c, "SELECT * FROM cl_gang_hours WHERE dpr_labour_id=? ORDER BY id", (g["id"],))
    machines = q(c, "SELECT x.*, q.code, q.name FROM dpr_equipment x LEFT JOIN equipment q ON q.id=x.equipment_id WHERE x.dpr_id=? "
                    "ORDER BY x.id", (d["id"],))
    for m in machines:
        m["delay_id"] = (_doc_code(c, "dpr_equipment", m["id"]) or {}).get("delay_id")
    work = q(c, "SELECT w.*, act.code acode, act.name aname, b.code boq_code FROM dpr_work w LEFT JOIN activities act ON "
                "act.id=w.activity_id LEFT JOIN boq_items b ON b.id=COALESCE(w.boq_item_id, act.boq_item_id) WHERE w.dpr_id=?",
             (d["id"],))
    acts = q(c, "SELECT a.id, a.code, a.name, b.code boq_code FROM activities a LEFT JOIN boq_items b ON b.id=a.boq_item_id "
                "WHERE a.project_id=? ORDER BY a.code", (d["project_id"],))
    delays = q(c, "SELECT dd.*, %s resp FROM dpr_delays dd WHERE dd.dpr_id=?" % _resp_sql(), (d["id"],))
    return {"dpr": d, "gangs": gangs, "machines": machines, "work": work, "activities": acts, "delays": delays,
            "problems": dpr_problems(c, d), "coding_on": coding_on(c, d["project_id"], d["date"])}


@api("cl.dpr_coding_save", "project", "edit")
def cl_dpr_coding_save(c, u, a):
    """Split each gang's hours over the DPR's work lines and Idle (with the delay that caused it)."""
    d = get(c, "dpr", int(a["dpr_id"]), "DPR")
    _check_project(c, u, d["project_id"])
    if d["status"] == "approved" and d["date"] < coding_from(c, d["project_id"]):
        raise ApiError("This DPR is from before coding started on the project.")
    lock_check(c, d["project_id"], d["date"], "Recoding this DPR")
    t = now()
    for g in a.get("gangs") or []:
        gid = int(g["dpr_labour_id"])
        row = q1(c, "SELECT * FROM dpr_labour WHERE id=? AND dpr_id=?", (gid, d["id"]))
        if not row:
            continue
        c.execute("DELETE FROM cl_gang_hours WHERE dpr_labour_id=?", (gid,))
        tot = 0.0
        for s in g.get("split") or []:
            hrs = _f(s.get("hours"))
            if hrs <= 0:
                continue
            tot += hrs
            resp = s.get("idle_resp") or None
            did = int(s["delay_id"]) if s.get("delay_id") else None
            if not s.get("activity_id") and not resp and did:
                resp = val(c, "SELECT %s FROM dpr_delays dd WHERE dd.id=?" % _resp_sql(), (did,), None)
            ins(c, "cl_gang_hours", {"dpr_id": d["id"], "dpr_labour_id": gid, "activity_id": int(s["activity_id"]) if s.get("activity_id") else None,
                                     "idle_resp": None if s.get("activity_id") else (resp or "contractor"), "delay_id": did,
                                     "hours": hrs, "user_id": u["id"], "ts": t})
        if tot - (row["hours"] or 0) > 0.01:
            raise ApiError("A gang has %s hours on the DPR; %s hours were split." % (r2(row["hours"]), r2(tot)))
    for m in a.get("machines") or []:
        if m.get("delay_id"):
            mid = int(m["dpr_equipment_id"])
            _set_doc_code(c, u, "dpr_equipment", mid, None, int(m["delay_id"]))
            lg = val(c, "SELECT logsheet_id FROM dpr_equipment WHERE id=?", (mid,), None)
            if lg:
                _set_doc_code(c, u, "logsheet", lg, None, int(m["delay_id"]))
    vids = [r["id"] for r in q(c, "SELECT id FROM vouchers WHERE source='dpr' AND source_id=?", (d["id"],))]
    invalidate(c, vids)
    audit(c, u, "code", "dpr", d["id"], {"gangs": len(a.get("gangs") or []), "machines": len(a.get("machines") or [])})
    return cl_dpr_coding(c, u, {"dpr_id": d["id"]})


@api("cl.queue", "project", "view")
def cl_queue(c, u, a):
    """Everything on a project still waiting for a cost code, in one list."""
    need(a, "project_id")
    pid = int(a["project_id"])
    _check_project(c, u, pid)
    ensure_codes(c, pid)
    cf = coding_from(c, pid)
    out = []
    for d in q(c, "SELECT * FROM dpr WHERE project_id=? AND date>=? AND status NOT IN ('approved','cancelled') ORDER BY date", (pid, cf)):
        for p in dpr_problems(c, d):
            out.append({"doc": "dpr", "doc_id": d["id"], "no": d["no"] or "DPR %s" % d["date"], "date": d["date"],
                        "what": p["what"], "line_id": p["id"], "kind": p["kind"]})
    for r in q(c, "SELECT l.id, l.qty, h.id hid, h.no, h.date, h.status, m.name FROM mrq_lines l JOIN mrq h ON h.id=l.mrq_id JOIN materials m "
                  "ON m.id=l.material_id WHERE h.project_id=? AND h.date>=? AND h.status IN ('draft','submitted') AND l.boq_item_id IS NULL "
                  "AND NOT EXISTS (SELECT 1 FROM cl_doc_codes k WHERE k.doc='mrq_line' AND k.line_id=l.id AND k.cost_code_id IS NOT NULL)",
               (pid, cf)):
        out.append({"doc": "mrq_line", "doc_id": r["hid"], "no": r["no"] or "Requisition (draft)", "date": r["date"],
                    "what": "%s %s" % (r["name"], r4(r["qty"])), "line_id": r["id"], "kind": "line"})
    for r in q(c, "SELECT l.id, l.qty, l.description, h.id hid, h.no, h.date, m.name FROM pr_lines l JOIN pr h ON h.id=l.pr_id LEFT JOIN "
                  "materials m ON m.id=l.material_id WHERE h.project_id=? AND h.date>=? AND h.status IN ('draft','submitted') AND "
                  "l.boq_item_id IS NULL AND NOT EXISTS (SELECT 1 FROM cl_doc_codes k WHERE k.doc='pr_line' AND k.line_id=l.id AND "
                  "k.cost_code_id IS NOT NULL)", (pid, cf)):
        out.append({"doc": "pr_line", "doc_id": r["hid"], "no": r["no"] or "Purchase request (draft)", "date": r["date"],
                    "what": "%s %s" % (r["name"] or r["description"] or "", r4(r["qty"])), "line_id": r["id"], "kind": "line"})
    if _has(c, "sc_orders"):
        for r in q(c, "SELECT l.id, l.description, l.qty, h.id hid, h.no, h.date FROM sc_order_items l JOIN sc_orders h ON h.id=l.order_id "
                      "WHERE h.project_id=? AND h.status='draft' AND l.boq_item_id IS NULL AND NOT EXISTS (SELECT 1 FROM cl_doc_codes k "
                      "WHERE k.doc='sc_item' AND k.line_id=l.id AND k.cost_code_id IS NOT NULL)", (pid,)):
            out.append({"doc": "sc_item", "doc_id": r["hid"], "no": r["no"] or "Work order (draft)", "date": r["date"],
                        "what": "%s %s" % (r["description"] or "", r4(r["qty"])), "line_id": r["id"], "kind": "line"})
    ctx = None
    for lg in q(c, "SELECT l.*, e.code FROM logsheets l JOIN equipment e ON e.id=l.equipment_id WHERE l.project_id=? AND l.date>=? AND "
                   "(COALESCE(l.idle_hours,0)+COALESCE(l.standby_hours,0))>0 ORDER BY l.date DESC LIMIT 300", (pid, cf)):
        dc = _doc_code(c, "logsheet", lg["id"])
        if dc and dc["delay_id"]:
            continue
        ctx = ctx or Ctx(c)
        rs = {r["r"] for r in q(c, "SELECT DISTINCT %s r FROM dpr_delays dd JOIN dpr d ON d.id=dd.dpr_id WHERE d.project_id=? AND d.date=?"
                                   % _resp_sql(), (pid, lg["date"]))}
        if len(rs) == 1:
            continue
        out.append({"doc": "logsheet", "doc_id": lg["id"], "no": "%s logsheet" % lg["code"], "date": lg["date"],
                    "what": "%s idle hours: link the delay that caused them" % r2((lg["idle_hours"] or 0) + (lg["standby_hours"] or 0)),
                    "line_id": lg["id"], "kind": "idle"})
    una = q1(c, "SELECT id FROM cl_codes WHERE project_id=? AND code='UNA'", (pid,))
    posted = [r for r in project_cost_rows(c, pid, today()) if una and r["code_id"] == una["id"]]
    return {"rows": out, "unallocated_lines": posted[:500], "unallocated": unallocated_share(c, pid, today()),
            "coding_from": cf, "codes": q(c, "SELECT id, code, kind, name FROM cl_codes WHERE project_id=? AND active=1 AND kind<>'pool' "
                                              "ORDER BY sort, code", (pid,)),
            "delays": q(c, "SELECT dd.id, d.date, d.no, dd.category, dd.hours, %s resp FROM dpr_delays dd JOIN dpr d ON d.id=dd.dpr_id "
                           "WHERE d.project_id=? AND d.date>=? ORDER BY d.date DESC LIMIT 300" % _resp_sql(), (pid, cf))}


@api("cl.lines", "project", "view")
def cl_lines(c, u, a):
    """The ledger lines (posted and waiting) behind a cost figure."""
    need(a, "project_id")
    pid = int(a["project_id"])
    _check_project(c, u, pid)
    rows = project_cost_rows(c, pid, a.get("as_of") or today(), a.get("from") or None)
    code = a.get("code_id")
    if code == "opening":
        rows = [r for r in rows if r["code_id"] is None]
    elif code:
        rows = [r for r in rows if r["code_id"] == int(code)]
    if a.get("ctype"):
        rows = [r for r in rows if r["ctype"] == a["ctype"]]
    if a.get("status"):
        rows = [r for r in rows if r["status"] == a["status"]]
    vno = {}
    for r in rows:
        if r["voucher_id"] not in vno:
            vno[r["voucher_id"]] = val(c, "SELECT no FROM vouchers WHERE id=?", (r["voucher_id"],), None)
        r["no"] = vno[r["voucher_id"]]
        r["amount"] = r2(r["amount"])
    lim = int(_f(a.get("limit"), 1500))
    return {"rows": rows[:lim], "count": len(rows), "total": r2(sum(r["amount"] for r in rows))}


@api("cl.recode", "project", "view")
def cl_recode(c, u, a):
    """Accounts or the QS moves ledger lines to another cost code. Amounts and accounts never change."""
    if not (allowed(c, u, "edit") or core.can(u, "accounts", "edit")):
        raise ApiError("Your role cannot recode cost (needs edit on control or accounts).")
    ids = [int(x) for x in (a.get("line_ids") or []) if str(x).strip()]
    k = get(c, "cl_codes", int(a["cost_code_id"]), "Cost code")
    _check_project(c, u, k["project_id"])
    sync(c)
    ctx = Ctx(c)
    n = 0
    for lid in ids:
        ln = q1(c, LINE_SQL + "WHERE l.id=?", (lid,))
        if not ln or (ln["project_id"] or ln["vproject"]) != k["project_id"]:
            continue
        lock_check(c, k["project_id"], ln["vdate"], "Recoding a line")
        cur = alloc(ctx, ln)
        basis = cur[0]["basis"] if cur else "normal"
        ct = cur[0]["ctype"] if cur else "O"
        _store(c, lid, [{"code_id": k["id"], "share": 1.0, "ctype": ct, "basis": basis, "how": "manual"}], user=u)
        n += 1
    audit(c, u, "recode", "cl_alloc", k["id"], {"lines": ids[:50]})
    return {"recoded": n}


@api("cl.project_save", "project", "view")
def cl_project_save(c, u, a):
    """When coding (and its controls on DPRs, requisitions and work orders) starts on a project; pilot flag."""
    need_right(c, u, "approve", "set when coding starts")
    pid = int(a["project_id"])
    ensure_codes(c, pid)
    ch = {}
    if a.get("coding_from"):
        ch["coding_from"] = a["coding_from"][:10]
    if "pilot" in a:
        ch["pilot"] = 1 if a["pilot"] in (1, "1", True) else 0
    if ch:
        c.execute("UPDATE cl_project SET %s, user_id=?, ts=? WHERE project_id=?" % ",".join(k + "=?" for k in ch),
                  list(ch.values()) + [u["id"], now(), pid])
    audit(c, u, "edit", "cl_project", pid, ch)
    return q1(c, "SELECT * FROM cl_project WHERE project_id=?", (pid,))


# ── back-fill of lines posted before 2.24 ──
def _legacy(c):
    frm = int(_f(setting(c, "cl_from"), 0))
    return q(c, LINE_SQL + "WHERE l.id<=? AND " + POSTED + " AND NOT EXISTS (SELECT 1 FROM cl_alloc a WHERE a.line_id=l.id) ORDER BY l.id",
             (frm,))


@api("cl.backfill_preview", "accounts", "view")
def cl_backfill_preview(c, u, a):
    ctx = Ctx(c)
    by = {}
    n = 0
    for ln in _legacy(c):
        parts = alloc(ctx, ln)
        if not parts:
            continue
        n += 1
        amt = (ln["debit"] or 0) - (ln["credit"] or 0)
        pid = ln["project_id"] or ln["vproject"]
        for p in parts:
            k = ctx.codes.of(pid)["rows"].get(p["code_id"]) or {}
            key = (pid, k.get("kind") or "?")
            b = by.setdefault(key, {"project_id": pid, "kind": k.get("kind"), "label": KIND_LABEL.get(k.get("kind"), "?"),
                                    "lines": 0, "amount": 0.0})
            b["lines"] += 1
            b["amount"] += amt * p["share"]
    codes = {r["id"]: r["code"] for r in q(c, "SELECT id, code FROM projects")}
    rows = [dict(b, amount=r2(b["amount"]), project=codes.get(b["project_id"])) for b in by.values()]
    rows.sort(key=lambda x: (x["project"] or "", INDIRECT_ORDER.index(x["kind"]) + 1 if x["kind"] in INDIRECT_ORDER else 0))
    return {"lines": n, "rows": rows, "backfilled": val(c, "SELECT COUNT(DISTINCT line_id) FROM cl_alloc WHERE how LIKE 'backfill%'")}


@api("cl.backfill_apply", "accounts", "approve")
def cl_backfill_apply(c, u, a):
    if not (u.get("role") == "admin" or allowed(c, u, "approve")):
        raise ApiError("Only the administrator or a director runs the back-fill.")
    ctx = Ctx(c)
    n = 0
    for ln in _legacy(c):
        parts = alloc(ctx, ln)
        _store(c, ln["id"], [dict(p, how="backfill:" + p["how"]) for p in parts], user=u)
        n += 1
    audit(c, u, "backfill", "cl_alloc", 0, {"lines": n})
    return {"coded": n}


@api("cl.backfill_undo", "accounts", "approve")
def cl_backfill_undo(c, u, a):
    if not (u.get("role") == "admin" or allowed(c, u, "approve")):
        raise ApiError("Only the administrator or a director undoes the back-fill.")
    frm = int(_f(setting(c, "cl_from"), 0))
    n = val(c, "SELECT COUNT(DISTINCT line_id) FROM cl_alloc WHERE line_id<=?", (frm,))
    c.execute("DELETE FROM cl_alloc WHERE line_id<=? AND (how LIKE 'backfill%' OR how='none')", (frm,))
    audit(c, u, "backfill_undo", "cl_alloc", 0, {"lines": n})
    return {"removed": n}


# ───────────────────────────── Module 2: control budget ─────────────────────────────
UNITS = ("unit_labour", "unit_material", "unit_equip_own", "unit_equip_rent", "unit_subcon", "unit_other")
UNIT_TYPE = {"unit_labour": "L", "unit_material": "M", "unit_equip_own": "E", "unit_equip_rent": "E", "unit_subcon": "S",
             "unit_other": "O"}


def unit_total(bl):
    return sum((bl.get(k) or 0) for k in UNITS) if bl else 0.0


def line_amount(bl):
    if not bl:
        return 0.0
    if bl.get("amount") is not None and not unit_total(bl):
        return bl["amount"] or 0.0
    return r2((bl.get("qty") or 0) * unit_total(bl))


def _version(c, pid, kind, statuses):
    return q1(c, "SELECT * FROM cl_budget_versions WHERE project_id=? AND kind=? AND status IN (%s) ORDER BY version_no DESC, id DESC "
                 "LIMIT 1" % ",".join("?" * len(statuses)), (pid, kind) + tuple(statuses))


def original_version(c, pid):
    return _version(c, pid, "original", ("approved",))


def current_version(c, pid):
    return _version(c, pid, "current", ("approved",))


def draft_version(c, pid):
    return _version(c, pid, "original", ("draft", "submitted"))


def vlines(c, vid):
    return {r["cost_code_id"]: r for r in q(c, "SELECT * FROM cl_budget_lines WHERE version_id=?", (vid,))} if vid else {}


def _ra_units(c, bid):
    """Cost per unit of a BOQ item before overhead and profit, split L / M / E / other, from BuildCore's rate analysis."""
    ra = q1(c, "SELECT * FROM ra_analyses WHERE boq_item_id=? ORDER BY CASE status WHEN 'approved' THEN 0 ELSE 1 END, id DESC LIMIT 1",
            (bid,)) if _has(c, "ra_analyses") else None
    if ra:
        try:
            res = json.loads(ra["result"] or "{}")
        except ValueError:
            res = {}
        per = _f(res.get("per_qty"), 1) or 1
        cpu = _f(ra["cost_per_unit"]) or _f(res.get("cost_per_unit"))
        lab = round(_f(res.get("labour")) / per, 4)
        mat = round((_f(res.get("material")) + _f(res.get("cartage"))) / per, 4)
        eq = round(_f(res.get("equipment")) / per, 4)
        oth = round(cpu - lab - mat - eq, 4)   # sundries, and the rounding, so the parts add up to the analysed cost
        return {"L": lab, "M": mat, "E": eq, "O": oth, "cpu": cpu, "source": "Rate analysis %s" % (ra["no"] or ra["id"])}
    rows = q(c, "SELECT kind, qty_per_unit, rate, description FROM rate_analysis WHERE boq_item_id=?", (bid,)) if _has(c, "rate_analysis") else []
    rows = [r for r in rows if r["kind"] != "overhead_pct" and not str(r["description"] or "").lower().startswith("overhead")]
    if rows:
        p = {"L": 0.0, "M": 0.0, "E": 0.0, "O": 0.0}
        for r in rows:
            k = {"labour": "L", "material": "M", "equipment": "E"}.get(r["kind"], "O")
            p[k] += (r["qty_per_unit"] or 0) * (r["rate"] or 0)
        p = {k: round(v, 4) for k, v in p.items()}
        p["cpu"] = round(sum(p.values()), 4)
        p["source"] = "BOQ rate analysis"
        return p
    return None


def _plan(c, bid):
    rows = q(c, "SELECT * FROM exec_plan WHERE boq_item_id=? ORDER BY share_pct DESC", (bid,)) if _has(c, "exec_plan") else []
    return rows[0] if rows else None


def _split_by_plan(u_, plan):
    """The budget split follows the planned way of working: a subcontracted item carries subcontract cost."""
    wm = (plan or {}).get("work_mode") or "direct"
    em = (plan or {}).get("equip_mode") or "owned"
    L, M, E, O = u_["L"], u_["M"], u_["E"], u_["O"]
    out = dict.fromkeys(UNITS, 0.0)
    if wm == "b2b_sc":
        out["unit_subcon"] = L + M + E + O
    elif wm == "supplied_sc":
        out["unit_subcon"], out["unit_material"], out["unit_other"] = L + E, M, O
    elif wm == "labour_sc":
        out["unit_subcon"], out["unit_material"], out["unit_other"] = L, M, O
        out["unit_equip_rent" if em == "rented" else "unit_equip_own"] = E
    else:
        out["unit_labour"], out["unit_material"], out["unit_other"] = L, M, O
        out["unit_equip_rent" if em == "rented" else "unit_equip_own"] = E
    return {k: round(v, 4) for k, v in out.items()}, wm


@api("cl.budget", "project", "view")
def cl_budget(c, u, a):
    need(a, "project_id")
    pid = int(a["project_id"])
    _check_project(c, u, pid)
    ensure_codes(c, pid)
    p = get(c, "projects", pid, "Project")
    org, cur, dr = original_version(c, pid), current_version(c, pid), draft_version(c, pid)
    fc = _version(c, pid, "forecast", ("approved",))
    lo, lc, ld, lf = vlines(c, org and org["id"]), vlines(c, cur and cur["id"]), vlines(c, dr and dr["id"]), vlines(c, fc and fc["id"])
    rows = []
    for k in q(c, "SELECT k.*, b.unit, b.qty bqty, b.revised_qty, COALESCE(b.revised_rate, b.rate) rate FROM cl_codes k LEFT JOIN "
                  "boq_items b ON b.id=k.boq_item_id WHERE k.project_id=? AND k.kind NOT IN ('pool','unallocated') ORDER BY k.sort, k.code", (pid,)):
        o, cu, d, f = lo.get(k["id"]), lc.get(k["id"]), ld.get(k["id"]), lf.get(k["id"])
        main = cu or d or o
        r = {"code_id": k["id"], "code": k["code"], "kind": k["kind"], "name": k["name"], "unit": k["unit"], "rate": k["rate"],
             "contract_qty": k["bqty"], "revised_qty": k["revised_qty"],
             "original": line_amount(o) if o else None, "current": line_amount(cu) if cu else None,
             "draft": line_amount(d) if d else None, "forecast": line_amount(f) if f else None,
             "line": main, "unit_cost": unit_total(main) if main else None,
             "contract_amount": r2((k["bqty"] or 0) * (k["rate"] or 0)) if k["kind"] == "boq" else None,
             "placeholder": (main or {}).get("placeholder")}
        if k["kind"] == "boq" and main and r["unit_cost"] is not None and k["rate"]:
            r["margin_unit"] = r2(k["rate"] - r["unit_cost"])
            r["margin_pct"] = round(100 * (k["rate"] - r["unit_cost"]) / k["rate"], 1)
        rows.append(r)
    tot = lambda key: r2(sum(r[key] or 0 for r in rows))  # noqa: E731
    contract = r2(sum(r["contract_amount"] or 0 for r in rows))
    orig_t = tot("original")
    changes = q(c, "SELECT ch.*, k.code FROM cl_budget_changes ch LEFT JOIN cl_codes k ON k.id=ch.cost_code_id WHERE ch.project_id=? "
                   "ORDER BY ch.id DESC", (pid,))
    for ch in changes:
        for f_ in ("before", "after"):
            try:
                ch[f_] = json.loads(ch[f_] or "null")
            except ValueError:
                pass
    by_type = {}
    src = lc or ld or lo
    for k_id, bl in src.items():
        for f_ in UNITS:
            by_type[UNIT_TYPE[f_]] = by_type.get(UNIT_TYPE[f_], 0) + (bl.get("qty") or 0) * (bl.get(f_) or 0)
        if bl.get("amount") is not None and not unit_total(bl):
            by_type["O"] = by_type.get("O", 0) + (bl["amount"] or 0)
    return {"project": {"id": pid, "code": p["code"], "name": p["name"], "contract_value": p["contract_value"]},
            "original": org, "current": cur, "draft": dr, "forecast": fc, "rows": rows, "changes": changes,
            "totals": {"original": orig_t, "current": tot("current"), "draft": tot("draft"), "forecast": tot("forecast"),
                       "contract": contract},
            "by_type": {k: r2(v) for k, v in by_type.items()},
            "bid_margin_pct": round(100 * (contract - orig_t) / contract, 2) if contract and org else None,
            "rights": {x: allowed(c, u, x) for x in ("view", "create", "edit", "submit", "approve")},
            "pm_right": core.can(u, "project", "approve")}


def _new_version(c, u, pid, kind, status="draft", source=None, reason=None, close_id=None):
    n = (val(c, "SELECT MAX(version_no) FROM cl_budget_versions WHERE project_id=? AND kind=?", (pid, kind)) or 0) + 1
    return ins(c, "cl_budget_versions", {"project_id": pid, "kind": kind, "version_no": n, "status": status, "source": source,
                                         "reason": reason, "close_id": close_id, "created_by": u["id"] if u else None, "ts": now()})


def _copy_lines(c, src_vid, dst_vid):
    for bl in q(c, "SELECT * FROM cl_budget_lines WHERE version_id=?", (src_vid,)):
        bl.pop("id")
        bl["version_id"] = dst_vid
        ins(c, "cl_budget_lines", bl)


@api("cl.budget_import", "project", "view")
def cl_budget_import(c, u, a):
    """Build the draft Original budget from the bid's rate analysis (BuildCore rate analyses, or a workbook)."""
    need_right(c, u, "create", "prepare the control budget")
    pid = int(a["project_id"])
    _check_project(c, u, pid)
    ensure_codes(c, pid)
    if original_version(c, pid):
        raise ApiError("The Original budget is approved and locked. Propose a change to the Current budget instead.")
    dr = draft_version(c, pid)
    if dr and dr["status"] == "submitted":
        raise ApiError("The draft is waiting for approval. Ask the director to return it first.")
    sheet = {}
    if a.get("b64") or a.get("text"):
        sheet = _read_budget_sheet(a)
    vid = dr["id"] if dr else _new_version(c, u, pid, "original", source="workbook" if sheet else "rate analysis")
    c.execute("DELETE FROM cl_budget_lines WHERE version_id=?", (vid,))
    codes = Codes(c).of(pid)
    done, missing = 0, []
    for b in q(c, "SELECT * FROM boq_items WHERE project_id=? ORDER BY code", (pid,)):
        k = codes["boq"].get(b["id"])
        plan = _plan(c, b["id"])
        if sheet:
            row = sheet.get(str(b["code"]).strip().lower())
            if not row:
                missing.append(b["code"])
                continue
            units = {f_: round(_f(row.get(f_)), 4) for f_ in UNITS}
            wm, src = (plan or {}).get("work_mode") or "direct", "workbook"
        else:
            ra = _ra_units(c, b["id"])
            if not ra:
                missing.append(b["code"])
                ins(c, "cl_budget_lines", {"version_id": vid, "cost_code_id": k, "qty": b["qty"] or 0, "placeholder": 1,
                                           "source": "no rate analysis", "way_of_working": (plan or {}).get("work_mode") or "direct"})
                continue
            units, wm = _split_by_plan(ra, plan)
            src = ra["source"]
        ins(c, "cl_budget_lines", dict({"version_id": vid, "cost_code_id": k, "qty": b["qty"] or 0, "way_of_working": wm,
                                        "source": src}, **units))
        done += 1
    p = get(c, "projects", pid)
    for kind in ("prelim", "overhead", "temp", "pa"):
        cid = q1(c, "SELECT id FROM cl_codes WHERE project_id=? AND kind=? ORDER BY id LIMIT 1", (pid, kind))["id"]
        amt = 0.0
        if sheet and sheet.get("__" + kind) is not None:
            amt = _f(sheet["__" + kind])
        elif kind == "overhead" and (p.get("indirect_per_day") or 0) and p.get("start_date") and p.get("end_date"):
            days = (date.fromisoformat(p["end_date"][:10]) - date.fromisoformat(p["start_date"][:10])).days + 1
            amt = r2(p["indirect_per_day"] * max(days, 0))
        ins(c, "cl_budget_lines", {"version_id": vid, "cost_code_id": cid, "qty": 1, "unit_other": amt, "amount": None,
                                   "source": "workbook" if sheet else ("indirect cost per day x contract days" if amt else "enter the amount")})
    audit(c, u, "import", "cl_budget_versions", vid, {"items": done, "missing": missing[:50]})
    return {"version_id": vid, "items": done, "missing": missing}


BUDGET_SPEC = [("code", True, ["boq code", "item", "item no", "boq item"]), ("unit_labour", False, ["labour", "l"]),
               ("unit_material", False, ["material", "m"]), ("unit_equip_own", False, ["own equipment", "equipment", "e"]),
               ("unit_equip_rent", False, ["rented equipment", "hire"]), ("unit_subcon", False, ["subcontract", "s"]),
               ("unit_other", False, ["other", "sundries", "o"])]


def _read_budget_sheet(a):
    import api_books as B
    grid, _x = B._grid(a)
    start, cols, _unknown = B._map_header(grid, BUDGET_SPEC)
    if "code" not in cols.values():
        raise ApiError("The workbook needs a 'BOQ code' column and cost per unit columns (labour, material, equipment, subcontract, other).")
    out = {}
    for r in grid[start:]:
        row = {f_: (r[j] if j < len(r) else "") for j, f_ in cols.items()}
        code = str(row.get("code") or "").strip()
        if not code:
            continue
        low = code.lower()
        for kind, words in (("prelim", ("preliminar",)), ("overhead", ("site overhead", "overhead")), ("temp", ("temporary",)),
                            ("pa", ("price adjust", "escalat"))):
            if any(w in low for w in words):
                out["__" + kind] = sum(_f(row.get(f_)) for f_ in UNITS)
                break
        else:
            out[low] = row
    return out


@api("cl.budget_line_save", "project", "view")
def cl_budget_line_save(c, u, a):
    """Change one line of the draft Original budget (cost per unit by type, quantity, way of working, or an indirect amount)."""
    need_right(c, u, "create", "edit the draft budget")
    pid = int(a["project_id"])
    _check_project(c, u, pid)
    dr = draft_version(c, pid)
    if not dr or dr["status"] != "draft":
        raise ApiError("There is no draft budget to edit. Once approved, change the Current budget through a proposed change.")
    k = get(c, "cl_codes", int(a["cost_code_id"]), "Cost code")
    data = {f_: round(_f(a.get(f_)), 4) for f_ in UNITS if f_ in a}
    if "qty" in a:
        data["qty"] = _f(a["qty"])
    if a.get("way_of_working"):
        data["way_of_working"] = a["way_of_working"]
    data["placeholder"] = 0
    data["source"] = "edited"
    ex = q1(c, "SELECT id FROM cl_budget_lines WHERE version_id=? AND cost_code_id=?", (dr["id"], k["id"]))
    if ex:
        upd(c, "cl_budget_lines", ex["id"], data)
    else:
        ins(c, "cl_budget_lines", dict({"version_id": dr["id"], "cost_code_id": k["id"], "qty": data.get("qty", 1)}, **data))
    audit(c, u, "edit", "cl_budget_lines", k["id"], data)
    return True


@api("cl.budget_submit", "project", "view")
def cl_budget_submit(c, u, a):
    need_right(c, u, "submit", "submit the budget")
    pid = int(a["project_id"])
    dr = draft_version(c, pid)
    if not dr or dr["status"] != "draft":
        raise ApiError("There is no draft budget to submit.")
    upd(c, "cl_budget_versions", dr["id"], {"status": "submitted", "submitted_by": u["id"], "submitted_at": now()})
    audit(c, u, "submit", "cl_budget_versions", dr["id"])
    return True


@api("cl.budget_approve", "project", "view")
def cl_budget_approve(c, u, a):
    """The director approves the Original budget: it is locked for good and the Current budget starts from it."""
    need_right(c, u, "approve", "approve the Original budget")
    pid = int(a["project_id"])
    dr = draft_version(c, pid)
    if not dr or dr["status"] != "submitted":
        raise ApiError("The project manager submits the draft budget first.")
    if a.get("decision") == "return":
        upd(c, "cl_budget_versions", dr["id"], {"status": "draft", "reason": a.get("note")})
        audit(c, u, "return", "cl_budget_versions", dr["id"], a.get("note"))
        return True
    upd(c, "cl_budget_versions", dr["id"], {"status": "approved", "approved_by": u["id"], "approved_at": now()})
    cv = _new_version(c, u, pid, "current", status="approved", source="original", reason="Original budget approved")
    _copy_lines(c, dr["id"], cv)
    upd(c, "cl_budget_versions", cv, {"approved_by": u["id"], "approved_at": now()})
    # quantities in Current follow the revised BOQ (approved variations already on the items)
    for b in q(c, "SELECT k.id kid, b.revised_qty FROM cl_codes k JOIN boq_items b ON b.id=k.boq_item_id WHERE k.project_id=? AND "
                  "b.revised_qty IS NOT NULL", (pid,)):
        c.execute("UPDATE cl_budget_lines SET qty=? WHERE version_id=? AND cost_code_id=?", (b["revised_qty"], cv, b["kid"]))
    audit(c, u, "approve", "cl_budget_versions", dr["id"])
    return {"original": dr["id"], "current": cv}


def _apply_change(c, u, ch):
    """A new Current version: the previous one plus this change."""
    pid = ch["project_id"]
    cur = current_version(c, pid)
    if not cur:
        raise ApiError("There is no approved budget yet.")
    nv = _new_version(c, u, pid, "current", status="approved", source=ch["kind"], reason=ch["reason"])
    _copy_lines(c, cur["id"], nv)
    upd(c, "cl_budget_versions", nv, {"approved_by": u["id"] if u else None, "approved_at": now()})
    after = json.loads(ch["after"] or "{}")
    ex = q1(c, "SELECT id FROM cl_budget_lines WHERE version_id=? AND cost_code_id=?", (nv, ch["cost_code_id"]))
    data = {f_: after[f_] for f_ in list(UNITS) + ["qty", "way_of_working", "placeholder", "source", "note"] if f_ in after}
    if ex:
        upd(c, "cl_budget_lines", ex["id"], data)
    else:
        ins(c, "cl_budget_lines", dict({"version_id": nv, "cost_code_id": ch["cost_code_id"]}, **data))
    return nv


@api("cl.budget_change", "project", "view")
def cl_budget_change(c, u, a):
    """The QS proposes a change to the Current budget (new item, re-plan of the way of working, corrected cost), with a reason."""
    need_right(c, u, "create", "propose a budget change")
    pid = int(a["project_id"])
    _check_project(c, u, pid)
    need(a, "cost_code_id", "reason")
    cur = current_version(c, pid)
    if not cur:
        raise ApiError("The Original budget must be approved first.")
    k = get(c, "cl_codes", int(a["cost_code_id"]), "Cost code")
    before = vlines(c, cur["id"]).get(k["id"])
    after = dict(before or {"qty": val(c, "SELECT COALESCE(revised_qty, qty) FROM boq_items WHERE id=?", (k["boq_item_id"],), 1) if k["boq_item_id"] else 1})
    for f_ in list(UNITS) + ["qty"]:
        if f_ in a and a[f_] not in (None, ""):
            after[f_] = round(_f(a[f_]), 4)
    if a.get("way_of_working"):
        after["way_of_working"] = a["way_of_working"]
    after["placeholder"] = 0
    for f_ in ("id", "version_id", "cost_code_id"):
        after.pop(f_, None)
    kind = a.get("kind") or ("replan" if a.get("way_of_working") and (before or {}).get("way_of_working") != a.get("way_of_working")
                             else ("new_item" if not before else "edit"))
    cid = ins(c, "cl_budget_changes", {"project_id": pid, "kind": kind, "cost_code_id": k["id"], "before": json.dumps(before),
                                        "after": json.dumps(after), "reason": a["reason"], "status": "proposed",
                                        "proposed_by": u["id"], "ts": now()})
    audit(c, u, "propose", "cl_budget_changes", cid, a.get("reason"))
    return {"id": cid}


@api("cl.budget_change_decide", "project", "view")
def cl_budget_change_decide(c, u, a):
    """The project manager approves first, then the director; the change then becomes a new Current version."""
    ch = get(c, "cl_budget_changes", int(a["id"]), "Budget change")
    _check_project(c, u, ch["project_id"])
    if ch["status"] not in ("proposed", "pm_approved"):
        raise ApiError("This change is already decided.")
    if a.get("decision") == "reject":
        if not (core.can(u, "project", "approve") or allowed(c, u, "approve")):
            raise ApiError("Only the project manager or the director can reject a budget change.")
        upd(c, "cl_budget_changes", ch["id"], {"status": "rejected", "approved_by": u["id"], "approved_at": now()})
        return True
    if ch["status"] == "proposed":
        if allowed(c, u, "approve") and u.get("role") in ("admin", "director"):
            pass  # the director may approve both steps at once
        else:
            if not core.can(u, "project", "approve"):
                raise ApiError("The project manager approves the change first.")
            if ch["proposed_by"] == u["id"] and u.get("role") != "admin":
                raise ApiError("Another person must approve what you proposed.")
            upd(c, "cl_budget_changes", ch["id"], {"status": "pm_approved", "pm_by": u["id"], "pm_at": now()})
            return {"status": "pm_approved"}
    need_right(c, u, "approve", "give the final approval to a budget change")
    nv = _apply_change(c, u, ch)
    upd(c, "cl_budget_changes", ch["id"], {"status": "approved", "approved_by": u["id"], "approved_at": now(),
                                           "pm_by": ch["pm_by"] or u["id"], "pm_at": ch["pm_at"] or now()})
    audit(c, u, "approve", "cl_budget_changes", ch["id"], {"version": nv})
    return {"status": "approved", "version_id": nv}


def variation_to_budget(c, u, v):
    """An approved variation adds its budget line to the Current budget automatically: the rate analysis attached to the
    variation's item, or the item's own cost per unit for a quantity change, or a zero-cost placeholder (flagged)."""
    pid = v["project_id"]
    ensure_codes(c, pid)
    cur = current_version(c, pid)
    if not cur or not v["boq_item_id"]:
        return None
    if q1(c, "SELECT id FROM cl_budget_changes WHERE variation_id=?", (v["id"],)):
        return None
    k = Codes(c).boq(pid, v["boq_item_id"])
    before = vlines(c, cur["id"]).get(k)
    b = get(c, "boq_items", v["boq_item_id"])
    qty = b["revised_qty"] if b["revised_qty"] is not None else b["qty"]
    if before and unit_total(before):
        after = {f_: before.get(f_) or 0 for f_ in UNITS}
        after.update({"qty": qty, "way_of_working": before.get("way_of_working"), "source": "variation %s" % (v["no"] or v["id"])})
    else:
        ra = _ra_units(c, v["boq_item_id"])
        if ra:
            units, wm = _split_by_plan(ra, _plan(c, v["boq_item_id"]))
            after = dict(units, qty=qty, way_of_working=wm, source="variation %s, %s" % (v["no"] or v["id"], ra["source"]))
        else:
            after = dict(dict.fromkeys(UNITS, 0.0), qty=qty, placeholder=1,
                         source="variation %s: no rate analysis yet (placeholder)" % (v["no"] or v["id"]))
    cid = ins(c, "cl_budget_changes", {"project_id": pid, "kind": "variation", "cost_code_id": k, "variation_id": v["id"],
                                        "before": json.dumps(before), "after": json.dumps(after),
                                        "reason": "Variation %s approved: %s" % (v["no"] or v["id"], v["title"] or ""),
                                        "status": "approved", "proposed_by": u["id"] if u else None, "approved_by": u["id"] if u else None,
                                        "approved_at": now(), "ts": now()})
    nv = _apply_change(c, u, q1(c, "SELECT * FROM cl_budget_changes WHERE id=?", (cid,)))
    return nv


def budget_unit(c, pid, code_id, cur_lines=None):
    """Current budget cost per unit of a code (Original before any change)."""
    if cur_lines is None:
        cur = current_version(c, pid) or original_version(c, pid)
        cur_lines = vlines(c, cur and cur["id"])
    bl = cur_lines.get(code_id)
    return (unit_total(bl), bl) if bl else (None, None)


# ───────────────────────────── value side ─────────────────────────────
def measured_qty(c, pid, asof):
    return {r["b"]: r["q"] or 0 for r in q(c, "SELECT l.boq_item_id b, SUM(l.qty) q FROM measurement_lines l JOIN measurements m ON "
                                               "m.id=l.measurement_id WHERE m.status='verified' AND m.project_id=? AND m.date<=? "
                                               "GROUP BY l.boq_item_id", (pid, asof))}


def executed_qty(c, pid, asof):
    return {r["b"]: r["q"] or 0 for r in q(c, "SELECT COALESCE(w.boq_item_id, a.boq_item_id) b, SUM(w.actual_qty) q FROM dpr_work w "
                                               "JOIN dpr d ON d.id=w.dpr_id LEFT JOIN activities a ON a.id=w.activity_id WHERE "
                                               "d.status='approved' AND d.project_id=? AND d.date<=? GROUP BY 1", (pid, asof))}


def ipc_qty(c, pid, asof, statuses=("submitted", "certified")):
    return {r["b"]: r["q"] or 0 for r in q(c, "SELECT l.boq_item_id b, SUM(l.qty) q FROM ipc_lines l JOIN ipc i ON i.id=l.ipc_id WHERE "
                                               "i.project_id=? AND i.date<=? AND i.status IN (%s) GROUP BY l.boq_item_id"
                                               % ",".join("?" * len(statuses)), (pid, asof) + tuple(statuses))}


def _events(c, pid, asof):
    cols = _cols(c, "events")
    cv = "COALESCE(claim_value, cost_impact, 0)" if "claim_value" in cols else "COALESCE(cost_impact, 0)"
    pa = val(c, "SELECT SUM(%s) FROM events WHERE project_id=? AND type='escalation' AND status IN ('agreed','approved','certified','closed') "
                "AND COALESCE(date,'')<=?" % cv, (pid, asof))
    claims = val(c, "SELECT SUM(%s) FROM events WHERE project_id=? AND COALESCE(type,'')<>'escalation' AND status NOT IN "
                    "('closed','rejected','agreed','approved','certified') AND COALESCE(date,'')<=?" % cv, (pid, asof))
    return r2(pa), r2(claims)


# ───────────────────────────── Module 6: material and subcontract reconciliation ─────────────────────────────
def material_recon(c, pid, asof):
    """Per BOQ item and material: theoretical use on measured work, actual use (net issues plus what subcontractors
    consumed on the item), allowed wastage (the coefficient's %), material in place not yet measured, excess wastage
    and its value at weighted average cost."""
    meas, exe = measured_qty(c, pid, asof), executed_qty(c, pid, asof)
    rows = q(c, "SELECT mc.*, b.code boq_code, b.description, m.code mat_code, m.name mat_name, m.unit, m.standard_rate FROM "
                "material_coefficients mc JOIN boq_items b ON b.id=mc.boq_item_id JOIN materials m ON m.id=mc.material_id WHERE "
                "b.project_id=? ORDER BY b.code, m.code", (pid,))
    sub = {}
    if _has(c, "sc_order_mats"):
        for r in q(c, "SELECT oi.boq_item_id b, sm.material_id m, SUM(bi.qty*sm.per_unit) q FROM sc_bill_items bi JOIN sc_bills sb ON "
                      "sb.id=bi.bill_id JOIN sc_order_items oi ON oi.id=bi.order_item_id JOIN sc_order_mats sm ON sm.order_id=oi.order_id "
                      "AND (sm.order_item_id=oi.id OR sm.order_item_id IS NULL) WHERE sb.project_id=? AND sb.status NOT IN "
                      "('draft','cancelled') AND sb.date<=? AND oi.boq_item_id IS NOT NULL GROUP BY 1, 2", (pid, asof)):
            sub[(r["b"], r["m"])] = r["q"] or 0
    out = []
    for r in rows:
        k = (r["boq_item_id"], r["material_id"])
        iss = q1(c, "SELECT SUM(l.qty) q, SUM(l.amount) v FROM issue_lines l JOIN issues i ON i.id=l.issue_id WHERE i.status='posted' "
                    "AND l.boq_item_id=? AND l.material_id=? AND i.date<=?", (k[0], k[1], asof)) or {}
        ret = val(c, "SELECT SUM(l.qty) FROM return_lines l JOIN returns x ON x.id=l.return_id WHERE x.status='posted' AND "
                     "l.condition IN ('usable','repairable') AND l.boq_item_id=? AND l.material_id=? AND x.date<=?", (k[0], k[1], asof))
        iq = iss.get("q") or 0
        rate = (iss.get("v") or 0) / iq if iq > EPS else (r["standard_rate"] or 0)
        coef, wpct = r["qty_per_unit"] or 0, r["wastage_pct"] or 0
        mq, eq_ = meas.get(k[0], 0), exe.get(k[0], 0)
        theo = mq * coef
        allowed = theo * wpct / 100
        sc_use = sub.get(k, 0)
        actual = iq - (ret or 0) + sc_use
        over = actual - theo - allowed
        in_place = min(max(0.0, (eq_ - mq) * coef * (1 + wpct / 100)), max(0.0, over))
        excess = max(0.0, over - in_place)
        under = actual < theo * 0.98 - EPS and theo > EPS
        out.append({"boq_item_id": k[0], "boq_code": r["boq_code"], "description": r["description"], "material_id": k[1],
                    "mat_code": r["mat_code"], "mat_name": r["mat_name"], "unit": r["unit"], "measured": r4(mq), "executed": r4(eq_),
                    "coefficient": coef, "allowed_pct": wpct, "theoretical": r4(theo), "allowed": r4(allowed),
                    "issued_net": r4(iq - (ret or 0)), "by_subcontractor": r4(sc_use), "actual": r4(actual),
                    "in_place": r4(in_place), "in_place_value": r2(in_place * rate), "excess": r4(excess), "rate": r2(rate),
                    "excess_value": r2(excess * rate), "under_use": under})
    return out


def subcon_checks(c, pid, asof):
    """Each work-order line mapped to a main-contract BOQ item: paid ahead of measured, back-to-back margin against the
    budget, material left with the subcontractor, advance and retention."""
    if not _has(c, "sc_orders"):
        return []
    tol = sf(c, "cl_sc_tol")
    adv_pct = sf(c, "cl_sc_adv_billed")
    meas = measured_qty(c, pid, asof)
    cur = current_version(c, pid) or original_version(c, pid)
    cl = vlines(c, cur and cur["id"])
    codes = Codes(c)
    billed_by_boq = {}
    rows = []
    for o in q(c, "SELECT o.*, p.name party FROM sc_orders o LEFT JOIN parties p ON p.id=o.party_id WHERE o.project_id=? AND "
                  "o.status NOT IN ('draft','cancelled') ORDER BY o.no", (pid,)):
        bills = q(c, "SELECT * FROM sc_bills WHERE order_id=? AND status NOT IN ('draft','cancelled') AND date<=?", (o["id"], asof))
        ordered = val(c, "SELECT SUM(qty*rate) FROM sc_order_items WHERE order_id=?", (o["id"],)) or 0
        gross = sum(b["gross"] or 0 for b in bills)
        adv_out = max(0.0, (o["advance"] or 0) - sum(b["advance_recovery"] or 0 for b in bills))
        retention = sum(b["retention"] or 0 for b in bills)
        try:
            import api_exec as X
            cust = X._custody(c, o["id"], asof)
        except Exception:
            cust = {}
        for it in q(c, "SELECT oi.*, b.code boq_code, COALESCE(b.revised_rate, b.rate) main_rate FROM sc_order_items oi LEFT JOIN "
                       "boq_items b ON b.id=oi.boq_item_id WHERE oi.order_id=?", (o["id"],)):
            bq = val(c, "SELECT SUM(bi.qty) FROM sc_bill_items bi JOIN sc_bills sb ON sb.id=bi.bill_id WHERE bi.order_item_id=? AND "
                        "sb.status NOT IN ('draft','cancelled') AND sb.date<=?", (it["id"], asof)) or 0
            mq = meas.get(it["boq_item_id"], 0) if it["boq_item_id"] else None
            if it["boq_item_id"]:
                billed_by_boq[it["boq_item_id"]] = billed_by_boq.get(it["boq_item_id"], 0) + bq
            k = codes.boq(pid, it["boq_item_id"]) if it["boq_item_id"] else None
            bu = unit_total(cl.get(k)) if k and cl.get(k) else None
            planned_unit = r2((it["main_rate"] or 0) - bu) if bu is not None and it["main_rate"] is not None else None
            actual_unit = r2((it["main_rate"] or 0) - (it["rate"] or 0)) if it["main_rate"] is not None else None
            mats = q(c, "SELECT * FROM sc_order_mats WHERE order_id=? AND (order_item_id=? OR order_item_id IS NULL)", (o["id"], it["id"])) \
                if _has(c, "sc_order_mats") else []
            theo_val = 0.0
            with_sub = 0.0
            for m in mats:
                cu = cust.get(m["material_id"]) or {}
                theo = bq * (m["per_unit"] or 0)
                bal = (cu.get("issued", 0) - cu.get("returned", 0) - cu.get("recovered", 0)) - theo
                with_sub += max(0.0, bal) * (cu.get("avg_cost") or 0)
                theo_val += theo * (cu.get("avg_cost") or 0)
            complete = (it["qty"] or 0) > 0 and bq >= (it["qty"] or 0) - EPS
            flags = []
            if mq is not None and bq > mq * (1 + tol / 100) + EPS:
                flags.append("paid_ahead")
            if planned_unit is not None and actual_unit is not None and o["type"] == "b2b" and actual_unit < planned_unit - 0.005:
                flags.append("margin_below_plan")
            if complete and with_sub > 0.5:
                flags.append("material_with_sub")
            if ordered and gross / ordered * 100 >= adv_pct and adv_out > 0.5:
                flags.append("advance_outstanding")
            rows.append({"order_id": o["id"], "order_no": o["no"], "party": o["party"], "type": o["type"], "order_item_id": it["id"],
                         "description": it["description"], "boq_item_id": it["boq_item_id"], "boq_code": it["boq_code"],
                         "qty": it["qty"], "rate": it["rate"], "billed_qty": r4(bq), "main_measured": r4(mq) if mq is not None else None,
                         "ahead_qty": r4(bq - mq) if mq is not None else None, "main_rate": it["main_rate"],
                         "b2b_margin": r2(actual_unit * bq) if actual_unit is not None else None,
                         "planned_margin": r2(planned_unit * bq) if planned_unit is not None else None,
                         "material_with_sub": r2(with_sub), "retention": r2(retention), "advance_outstanding": r2(adv_out),
                         "billed_pct": round(100 * gross / ordered, 1) if ordered else None, "flags": flags,
                         "mapped": bool(it["boq_item_id"])})
    return rows


# ───────────────────────────── Module 5: equipment as an internal business ─────────────────────────────
def eq_params(c, e):
    p = q1(c, "SELECT * FROM cl_eq_params WHERE equipment_id=?", (e["id"],)) or {}
    f = q1(c, "SELECT * FROM eq_finance WHERE equipment_id=?", (e["id"],)) if _has(c, "eq_finance") else None
    f = f or {}
    rt = q1(c, "SELECT * FROM equipment_rates WHERE equipment_id=? ORDER BY effective_from DESC, id DESC LIMIT 1", (e["id"],)) or {}
    planned = p.get("planned_hours_year")
    if not planned:
        life_y = (e.get("life_months") or 0) / 12.0
        planned = (e["est_total_hours"] / life_y) if e.get("est_total_hours") and life_y else None
    standby = p.get("standby_rate")
    if standby in (None, ""):
        standby = ((rt.get("ownership_hr") or 0) + (rt.get("insurance_hr") or 0)) or None
    try:
        import api_exec as X
        rate = X._internal_rate(c, e)
    except Exception:
        rate = e.get("internal_rate") or 0
    return {"planned_hours_year": planned, "standby_rate": standby, "market_hire_rate": p.get("market_hire_rate") or f.get("market_rate") or None,
            "fuel_norm": p.get("fuel_norm") or e.get("fuel_norm") or None, "loan_id": p.get("loan_id"), "rate": rate,
            "emi": f.get("emi") or 0, "emi_count": f.get("emi_count") or 0, "first_emi_date": f.get("first_emi_date"),
            "set": {k: p.get(k) for k in ("planned_hours_year", "standby_rate", "market_hire_rate", "fuel_norm", "loan_id")}}


def _available_hours(c, e, frm, to):
    shift = core.fsetting(c, "shift_hours") or 10
    cal = None
    if e.get("project_id") and _has(c, "sched_calendars"):
        cal = q1(c, "SELECT * FROM sched_calendars WHERE project_id=? ORDER BY is_default DESC, id LIMIT 1", (e["project_id"],))
    if not cal and _has(c, "sched_calendars"):
        cal = q1(c, "SELECT * FROM sched_calendars WHERE project_id IS NULL ORDER BY is_default DESC, id LIMIT 1")
    week = (cal or {}).get("week") or ""
    hrs = (cal or {}).get("hours_day") or shift
    hol = {r["date"] for r in q(c, "SELECT date FROM sched_holidays WHERE calendar_id=? AND date BETWEEN ? AND ?", (cal["id"], frm, to))} if cal else set()
    d0, d1 = date.fromisoformat(frm), date.fromisoformat(to)
    n = 0
    while d0 <= d1:
        wd = d0.weekday()
        work = week[wd] == "1" if len(week) == 7 and week.isdigit() else wd != 5   # Monday..Sunday; Saturday off
        if work and d0.isoformat() not in hol:
            n += 1
        d0 += timedelta(days=1)
    return r2(n * hrs)


def eq_month(c, e, period):
    """One machine, one month (a BS period): hours, idle by responsibility, fuel against norm, charge, cost, recovery."""
    frm, to = period_bounds(c, period)
    par = eq_params(c, e)
    logs = q(c, "SELECT * FROM logsheets WHERE equipment_id=? AND date BETWEEN ? AND ?", (e["id"], frm, to))
    working = sum(l["hours"] or 0 for l in logs)
    breakdown = sum(l["breakdown_hours"] or 0 for l in logs)
    ctx = Ctx(c)
    idle = {"employer": 0.0, "contractor": 0.0, "neutral": 0.0}
    for l in logs:
        h_ = (l["idle_hours"] or 0) + (l.get("standby_hours") or 0)
        if h_ > 0:
            r = ctx.idle_resp_for(l["project_id"], l["date"], l["id"])
            idle[r if r in idle else "contractor"] += h_
    fuel = sum(l.get("fuel_qty") or 0 for l in logs)
    if not fuel:
        for il in q(c, "SELECT l.qty, m.category FROM issue_lines l JOIN issues i ON i.id=l.issue_id JOIN materials m ON m.id=l.material_id "
                       "WHERE i.status='posted' AND l.equipment_id=? AND i.date BETWEEN ? AND ?", (e["id"], frm, to)):
            if core.inventory_role({"category": il["category"]}) == "inventory_fuel":
                fuel += il["qty"] or 0
    avail = _available_hours(c, e, frm, to)
    try:
        import api_exec as X
        cost = X.eq_cost_row(c, e, frm, to)
    except Exception:
        cost = {"economic_cost": 0, "operating": 0, "depreciation": 0, "interest": 0, "earned": 0}
    charged = r2(cost.get("earned") or 0)
    actual = r2(cost.get("economic_cost") or 0)
    norm = par["fuel_norm"]
    fv = round(100 * (fuel - working * norm) / (working * norm), 1) if norm and working > EPS else None
    emi_due = 0.0
    if par["emi"] and par["first_emi_date"]:
        first = par["first_emi_date"][:10]
        d0_ = date.fromisoformat(first)
        n_ = 0
        while True:
            y_, m_ = divmod(d0_.month - 1 + n_, 12)
            d = date(d0_.year + y_, m_ + 1, min(d0_.day, 28))
            if d.isoformat() > to or (par["emi_count"] and n_ >= par["emi_count"]):
                break
            if d.isoformat() >= frm:
                emi_due += par["emi"]
            n_ += 1
    standby = par["standby_rate"] or 0
    return {"equipment_id": e["id"], "code": e["code"], "name": e["name"], "period": period, "from": frm, "to": to,
            "available_hrs": avail, "working_hrs": r2(working), "breakdown_hrs": r2(breakdown),
            "idle_employer": r2(idle["employer"]), "idle_contractor": r2(idle["contractor"]), "idle_neutral": r2(idle["neutral"]),
            "utilisation_pct": round(100 * working / avail, 1) if avail else None,
            "availability_pct": round(100 * (avail - breakdown) / avail, 1) if avail else None,
            "fuel_litres": r2(fuel), "fuel_norm": norm, "fuel_expected": r2(working * norm) if norm else None, "fuel_var_pct": fv,
            "rate": par["rate"], "charged": charged, "actual_cost": actual, "recovery": r2(charged - actual),
            "operating": cost.get("operating"), "depreciation": cost.get("depreciation"), "interest": cost.get("interest"),
            "standby_rate": standby or None, "idle_cost_employer": r2(idle["employer"] * standby),
            "idle_cost_contractor": r2(idle["contractor"] * standby), "idle_cost_neutral": r2(idle["neutral"] * standby),
            "emi_due": r2(emi_due), "market_hire_rate": par["market_hire_rate"], "planned_hours_year": par["planned_hours_year"]}


def eq_flags(c, e, months):
    """Flags on the last month, with the history needed for the 'three months running' and break-even tests."""
    if not months:
        return []
    m = months[-1]
    fl = []
    if m["fuel_var_pct"] is not None and m["fuel_var_pct"] > sf(c, "cl_fuel_var"):
        fl.append(("fuel", "Fuel %s%% above norm" % m["fuel_var_pct"]))
    n = int(sf(c, "cl_util_months") or 3)
    low = sf(c, "cl_util_low")
    last = months[-n:]
    if len(last) == n and all(x["utilisation_pct"] is not None and x["utilisation_pct"] < low for x in last):
        fl.append(("utilisation", "Utilisation under %s%% for %d months: move, hire out or sell" % (int(low), n)))
    if m["actual_cost"] and -m["recovery"] > m["actual_cost"] * sf(c, "cl_under_rec") / 100:
        fl.append(("under_recovery", "Under-recovered by %s this month" % fmt(-m["recovery"])))
    if m["emi_due"] and m["emi_due"] > m["charged"] + 0.5:
        fl.append(("emi", "EMI due %s is more than the machine earned %s" % (fmt(m["emi_due"]), fmt(m["charged"]))))
    be = break_even(c, e, months)
    if be.get("break_even_hours") and be.get("hours_year") is not None and be["hours_year"] < be["break_even_hours"]:
        fl.append(("break_even", "Working %s h a year, below break-even %s h" % (int(be["hours_year"]), int(be["break_even_hours"]))))
    return fl


def break_even(c, e, months):
    last = months[-12:]
    if not last:
        return {}
    k = len(last)
    fixed = sum((x["depreciation"] or 0) + (x["interest"] or 0) for x in last) * 12.0 / k
    hrs = sum(x["working_hrs"] for x in last)
    running = sum(x["operating"] or 0 for x in last) / hrs if hrs > EPS else None
    mkt = last[-1]["market_hire_rate"]
    be = r2(fixed / (mkt - running)) if mkt and running is not None and mkt > running else None
    return {"fixed_annual": r2(fixed), "running_per_hour": r2(running) if running is not None else None, "market_rate": mkt,
            "break_even_hours": be, "hours_year": r2(hrs * 12.0 / k)}


def fmt(x):
    return "{:,.0f}".format(x or 0)


def idle_standby(c, pid, frm, asof):
    """Idle hours of own machines at a project by responsibility x standby rate (a management figure, never posted)."""
    ctx = Ctx(c)
    out = {"employer": 0.0, "contractor": 0.0, "neutral": 0.0}
    hrs = {"employer": 0.0, "contractor": 0.0, "neutral": 0.0}
    rows = []
    cond, p = "l.project_id=? AND l.date<=? AND (COALESCE(l.idle_hours,0)+COALESCE(l.standby_hours,0))>0", [pid, asof]
    if frm:
        cond += " AND l.date>=?"
        p.append(frm)
    for l in q(c, "SELECT l.*, e.code, e.name, COALESCE(e.ownership,'owned') own FROM logsheets l JOIN equipment e ON e.id=l.equipment_id "
                  "WHERE " + cond + " ORDER BY l.date", p):
        if l["own"] != "owned":
            continue
        e = get(c, "equipment", l["equipment_id"])
        sb = eq_params(c, e)["standby_rate"] or 0
        h_ = (l["idle_hours"] or 0) + (l["standby_hours"] or 0)
        r = ctx.idle_resp_for(pid, l["date"], l["id"])
        r = r if r in out else "contractor"
        out[r] += h_ * sb
        hrs[r] += h_
        dl = q1(c, "SELECT k.delay_id FROM cl_doc_codes k WHERE k.doc='logsheet' AND k.line_id=?", (l["id"],))
        rows.append({"date": l["date"], "equipment": l["code"], "hours": r2(h_), "resp": r, "standby_rate": sb, "cost": r2(h_ * sb),
                     "logsheet_id": l["id"], "delay_id": (dl or {}).get("delay_id")})
    return {k: r2(v) for k, v in out.items()}, {k: r2(v) for k, v in hrs.items()}, rows


# ───────────────────────────── accruals ─────────────────────────────
def accruals(c, pid, asof, close=None):
    """Work done not billed, billed not certified, labour / subcontract / hire not billed, goods received not billed,
    advances to recover. side: value | receivable | cost | memo | liability."""
    out = []
    ctx = Ctx(c)
    una = ctx.head(pid, "UNA")
    qty = (close_qty(c, close) if close else None) or measured_qty(c, pid, asof)
    billed = ipc_qty(c, pid, asof)
    for b in q(c, "SELECT id, code, COALESCE(revised_rate, rate) rate FROM boq_items WHERE project_id=?", (pid,)):
        d = (qty.get(b["id"], 0) or 0) - (billed.get(b["id"], 0) or 0)
        if d > EPS and b["rate"]:
            out.append({"kind": "work_not_billed", "side": "value", "source_type": "boq_item", "source_id": b["id"],
                        "code_id": ctx.code_for_boq(pid, b["id"]), "amount": r2(d * b["rate"]),
                        "detail": "%s: %s measured not yet in an IPC" % (b["code"], r4(d))})
    for i in q(c, "SELECT * FROM ipc WHERE project_id=? AND status='submitted' AND date<=?", (pid, asof)):
        out.append({"kind": "billed_not_certified", "side": "receivable", "source_type": "ipc", "source_id": i["id"], "code_id": None,
                    "amount": r2(i["gross"] or 0), "detail": "IPC %s submitted %s, not certified" % (i["no"] or i["id"], i["date"])})
    # labour supply gangs on approved DPRs, not yet in a labour-supply bill
    by_party = {}
    for g in q(c, "SELECT l.party_id, l.activity_id, l.amount FROM dpr_labour l JOIN dpr d ON d.id=l.dpr_id WHERE d.project_id=? AND "
                  "d.status='approved' AND d.date<=? AND l.party_id IS NOT NULL AND l.amount>0", (pid, asof)):
        bp = by_party.setdefault(g["party_id"], {"amount": 0.0, "w": {}})
        bp["amount"] += g["amount"]
        k = ctx.code_for_boq(pid, ctx.act_boq(g["activity_id"])) if g["activity_id"] else una
        bp["w"][k or una] = bp["w"].get(k or una, 0) + g["amount"]
    for party, bp in by_party.items():
        billed_amt = val(c, "SELECT SUM(b.gross) FROM sc_bills b JOIN sc_orders o ON o.id=b.order_id WHERE o.project_id=? AND o.party_id=? "
                            "AND o.type='labour' AND b.status='posted' AND b.date<=?", (pid, party, asof)) if _has(c, "sc_bills") else 0
        d = bp["amount"] - (billed_amt or 0)
        if d > 0.5:
            nm = val(c, "SELECT name FROM parties WHERE id=?", (party,), "")
            for k, amt in _split_amount(d, bp["w"]):
                out.append({"kind": "labour_not_billed", "side": "cost", "source_type": "party", "source_id": party, "code_id": k,
                            "amount": amt, "ctype": "S", "detail": "%s: DPR hours not yet billed" % nm})
    # subcontract work done (as the QS measured it for the close, else the main measurement) not yet billed
    if _has(c, "sc_orders"):
        scq = close_scqty(c, close) if close else {}
        for it in q(c, "SELECT oi.*, o.no, o.id oid, b.qty bqty, b.revised_qty brq FROM sc_order_items oi JOIN sc_orders o ON o.id=oi.order_id "
                       "LEFT JOIN boq_items b ON b.id=oi.boq_item_id WHERE o.project_id=? AND o.status NOT IN ('draft','cancelled')", (pid,)):
            done = scq.get(it["id"])
            if done is None:
                done = default_sc_done(it, qty)
            bil = val(c, "SELECT SUM(bi.amount) FROM sc_bill_items bi JOIN sc_bills sb ON sb.id=bi.bill_id WHERE bi.order_item_id=? AND "
                         "sb.status='posted' AND sb.date<=?", (it["id"], asof)) or 0
            d = done * (it["rate"] or 0) - bil
            if d > 0.5:
                out.append({"kind": "subcontract_not_billed", "side": "cost", "source_type": "sc_order_item", "source_id": it["id"],
                            "code_id": ctx.code_for_boq(pid, it["boq_item_id"]) or una, "amount": r2(d), "ctype": "S",
                            "detail": "Work order %s: %s done, %s billed" % (it["no"], r4(done), fmt(bil))})
    # hire of rented machines: approved logsheet hours not yet billed
    for ag in q(c, "SELECT h.*, e.code FROM hire_agreements h JOIN equipment e ON e.id=h.equipment_id WHERE h.project_id=?", (pid,)):
        logs = q(c, "SELECT * FROM logsheets WHERE equipment_id=? AND project_id=? AND status='approved' AND date<=? AND date>=?",
                 (ag["equipment_id"], pid, asof, ag["start_date"] or "0000-01-01"))
        unit = ag["unit"] or "hour"
        if unit == "hour":
            units = sum(l["hours"] or 0 for l in logs)
        elif unit == "day":
            units = len({l["date"] for l in logs if (l["hours"] or 0) > 0})
        else:
            units = len({l["date"][:7] for l in logs})
        earned = units * (ag["rate"] or 0)
        bil = val(c, "SELECT SUM(b.amount) FROM hire_bills b JOIN invoices i ON i.id=b.invoice_id WHERE b.agreement_id=? AND "
                     "i.status IN ('posted','awaiting_posting') AND i.date<=?", (ag["id"], asof)) or 0
        d = earned - bil
        if d > 0.5:
            w = _hours_weights(ctx, pid, [dict(l, standby_hours=l.get("standby_hours") or 0) for l in logs], True)
            for k, amt in _split_amount(d, w or {una: 1}):
                out.append({"kind": "hire_not_billed", "side": "cost", "source_type": "hire_agreement", "source_id": ag["id"],
                            "code_id": k, "amount": amt, "ctype": "E",
                            "detail": "%s: %s %s approved, %s billed" % (ag["code"], r2(units), unit, fmt(bil))})
    # goods received not billed: already in stock (cost when issued), shown for information
    g = val(c, "SELECT SUM((gl.accepted_qty-gl.invoiced_qty)*gl.rate) FROM grn_lines gl JOIN grn g ON g.id=gl.grn_id WHERE g.project_id=? "
               "AND g.status='posted' AND g.date<=? AND gl.accepted_qty>gl.invoiced_qty", (pid, asof))
    if g and g > 0.5:
        out.append({"kind": "grn_not_billed", "side": "memo", "source_type": "grn", "source_id": None, "code_id": None, "amount": r2(g),
                    "detail": "Goods received without a supplier bill (in stock; cost when issued)"})
    adv = -val(c, "SELECT SUM(l.debit-l.credit) FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id JOIN accounts x ON x.id=l.account_id "
                  "WHERE x.role='client_advance' AND COALESCE(l.project_id, v.project_id)=? AND v.date<=? AND " + POSTED, (pid, asof))
    if adv and adv > 0.5:
        out.append({"kind": "advance_to_recover", "side": "liability", "source_type": "project", "source_id": pid, "code_id": None,
                    "amount": r2(adv), "detail": "Mobilisation advance received, not yet recovered through IPCs"})
    return out


def _split_amount(total, weights):
    """Split an amount over codes by weight in rupees and paisa; the last share takes the rounding so the parts add up."""
    items = list(weights.items())
    tot_w = sum(w for _k, w in items) or 1
    out, left = [], r2(total)
    for i, (k, w) in enumerate(items):
        amt = left if i == len(items) - 1 else r2(total * w / tot_w)
        left = r2(left - amt)
        out.append((k, amt))
    return out


def default_sc_done(it, qty):
    mq = qty.get(it["boq_item_id"]) if it["boq_item_id"] else None
    if mq is None:
        return 0.0
    tot = it["brq"] if it.get("brq") is not None else it.get("bqty")
    share = min(1.0, (it["qty"] or 0) / tot) if tot else 1.0
    return min(it["qty"] or 0, mq * share)


ACCRUAL_LABEL = {"work_not_billed": "Work done not billed", "billed_not_certified": "Billed not certified",
                 "labour_not_billed": "Labour cost not billed", "subcontract_not_billed": "Subcontract work not billed",
                 "hire_not_billed": "Hire not billed", "grn_not_billed": "Goods received not billed",
                 "advance_to_recover": "Advances to recover"}


# ───────────────────────────── Module 4: CVR and forecast ─────────────────────────────
def close_qty(c, close):
    if not close:
        return {}
    return {r["boq_item_id"]: r["qty_done"] or 0 for r in q(c, "SELECT * FROM cl_close_qty WHERE close_id=?", (close["id"],))}


def close_scqty(c, close):
    if not close:
        return {}
    return {r["order_item_id"]: r["qty_done"] or 0 for r in q(c, "SELECT * FROM cl_close_scqty WHERE close_id=?", (close["id"],))}


def _months_between(a, b):
    if not a or not b or b <= a:
        return 0.0
    return (date.fromisoformat(b[:10]) - date.fromisoformat(a[:10])).days / 30.4375


def cvr(c, pid, asof, close=None, acc=None):
    """Cost-value reconciliation of one project at a date: every BOQ item, then the indirect heads, then the total."""
    pid = int(pid)
    ensure_codes(c, pid)
    p = get(c, "projects", pid, "Project")
    mode = eq_mode(c)
    codes = q(c, "SELECT k.*, b.unit, b.qty bqty, b.revised_qty, COALESCE(b.revised_rate, b.rate) rate FROM cl_codes k LEFT JOIN "
                 "boq_items b ON b.id=k.boq_item_id WHERE k.project_id=? ORDER BY k.sort, k.code", (pid,))
    qty = (close_qty(c, close) if close else None) or measured_qty(c, pid, asof)
    cur = current_version(c, pid) or original_version(c, pid)
    cl_ = vlines(c, cur and cur["id"])
    org = original_version(c, pid)
    ol = vlines(c, org and org["id"])
    ov = {r["cost_code_id"]: r for r in q(c, "SELECT * FROM cl_forecast_override WHERE project_id=?", (pid,))}
    period = period_of_date(c, asof)
    pfrom = close["from_date"] if close else period_bounds(c, period)[0]
    qty_prev = measured_qty(c, pid, (date.fromisoformat(pfrom) - timedelta(days=1)).isoformat())
    rows_cost = project_cost_rows(c, pid, asof)
    acc = acc if acc is not None else accruals(c, pid, asof, close)
    std_amt, std_hrs, _std_rows = idle_standby(c, pid, None, asof)
    wast = {}
    for w in material_recon(c, pid, asof):
        wast[w["boq_item_id"]] = wast.get(w["boq_item_id"], 0) + w["excess_value"]
    pa_val, claims = _events(c, pid, asof)
    agg = {}

    def A(cid):
        return agg.setdefault(cid, {"posted": 0.0, "waiting": 0.0, "accrued": 0.0, "L": 0.0, "M": 0.0, "E": 0.0, "S": 0.0, "O": 0.0,
                                    "period": 0.0, "standby": 0.0})
    last3 = {}
    for r in rows_cost:
        a = A(r["code_id"])
        a[r["status"]] += r["amount"]
        a[r["ctype"]] += r["amount"]
        if r["date"] >= pfrom:
            a["period"] += r["amount"]
        last3.setdefault(r["code_id"], []).append((r["date"], r["amount"]))
    for x in acc:
        if x["side"] == "cost":
            a = A(x["code_id"])
            a["accrued"] += x["amount"]
            a[x.get("ctype") or "O"] += x["amount"]
    idle_codes = {k["delay_resp"]: k["id"] for k in codes if k["kind"] == "idle"}
    for resp, amt in std_amt.items():
        k = idle_codes.get(resp) or idle_codes.get("contractor")
        if k:
            A(k)["standby"] += amt
            if mode == "rate":
                A(k)["accrued"] += amt
                A(k)["E"] += amt
    tot_val = 0.0
    rows = []
    rule = setting(c, "cl_ctc_rule") or "actual_after"
    pct_rule = sf(c, "cl_ctc_pct")
    end = p.get("completion_date") or p.get("end_date")
    rem_months = _months_between(asof, end)
    fl_cpi, fl_done = sf(c, "cl_flag_cpi"), sf(c, "cl_flag_done_pct")
    for k in codes:
        if k["kind"] == "pool":
            continue
        a = agg.get(k["id"]) or A(k["id"])
        cost = a["posted"] + a["waiting"] + a["accrued"]
        bl = cl_.get(k["id"])
        bu = unit_total(bl) if bl else None
        r = {"code_id": k["id"], "code": k["code"], "kind": k["kind"], "name": k["name"], "unit": k["unit"], "boq_item_id": k["boq_item_id"],
             "cost_posted": r2(a["posted"]), "cost_waiting": r2(a["waiting"]), "cost_accrued": r2(a["accrued"]), "cost": r2(cost),
             "cost_l": r2(a["L"]), "cost_m": r2(a["M"]), "cost_e": r2(a["E"]), "cost_s": r2(a["S"]), "cost_o": r2(a["O"]),
             "cost_period": r2(a["period"]), "standby_memo": r2(a["standby"]) if k["kind"] == "idle" else None, "flags": [],
             "budget_unit": r2(bu) if bu is not None else None, "budget_original": line_amount(ol.get(k["id"])) if ol.get(k["id"]) else None,
             "budget_current": line_amount(bl) if bl else None, "placeholder": (bl or {}).get("placeholder")}
        if k["kind"] == "boq":
            rate = k["rate"] or 0
            qt = (bl or {}).get("qty") if bl and bl.get("qty") else (k["revised_qty"] if k["revised_qty"] is not None else k["bqty"]) or 0
            qd = qty.get(k["boq_item_id"], 0) or 0
            value = qd * rate
            done_pct = 100 * qd / qt if qt else (100.0 if qd else 0.0)
            bcwd = qd * bu if bu is not None else None
            remaining = max(0.0, qt - qd)
            o = ov.get(k["id"])
            if o and o["unit_cost"] is not None:
                fu, fsrc = o["unit_cost"], "PM: " + (o["note"] or "")
            elif rule == "actual_after" and qd > EPS and done_pct >= pct_rule:
                fu, fsrc = cost / qd, "actual"
            elif bu is not None:
                fu, fsrc = bu, "budget"
            elif qd > EPS:
                fu, fsrc = cost / qd, "actual (no budget)"
            else:
                fu, fsrc = 0.0, "no budget"
            ctc = remaining * fu
            fval = max(qt, qd) * rate
            r.update({"qty_total": r4(qt), "qty_done": r4(qd), "done_pct": round(done_pct, 1), "rate": rate, "value": r2(value),
                      "bcwd": r2(bcwd) if bcwd is not None else None, "margin": r2(value - cost),
                      "cpi": round(bcwd / cost, 2) if bcwd is not None and cost > EPS else None,
                      "forecast_unit": r2(fu), "forecast_basis": fsrc, "ctc": r2(ctc), "eac": r2(cost + ctc),
                      "forecast_value": r2(fval), "forecast_margin": r2(fval - cost - ctc), "wastage_value": r2(wast.get(k["boq_item_id"], 0)),
                      "qty_period": r4(qd - (qty_prev.get(k["boq_item_id"], 0) or 0))})
            tot_val += value
            if r["cpi"] is not None and r["cpi"] < fl_cpi:
                r["flags"].append("cpi_low")
            if r["margin"] < -0.5 and done_pct > fl_done:
                r["flags"].append("negative_margin")
            if a["period"] > 0.5 and r["qty_period"] <= EPS:
                r["flags"].append("cost_no_progress")
            if r["placeholder"]:
                r["flags"].append("budget_placeholder")
        else:
            r.update({"qty_total": None, "qty_done": None, "done_pct": None, "rate": None, "value": r2(pa_val) if k["kind"] == "pa" else 0.0,
                      "bcwd": None, "cpi": None, "wastage_value": None})
            if k["kind"] == "overhead":
                months = {}
                for d_, amt in last3.get(k["id"], []):
                    months.setdefault(period_of_date(c, d_), 0.0)
                    months[period_of_date(c, d_)] += amt
                prev = [months.get(_shift(period, -i), 0.0) for i in (1, 2, 3)]
                avg = sum(prev) / 3.0
                ctc = rem_months * avg
                r["forecast_basis"] = "%.1f months x %s (last three months' average)" % (rem_months, fmt(avg))
            elif k["kind"] in ("prelim", "temp", "pa"):
                ctc = max(0.0, (r["budget_current"] or 0) - cost)
                r["forecast_basis"] = "budget less cost to date"
            else:
                ctc = 0.0
                r["forecast_basis"] = "not forecast"
            r.update({"ctc": r2(ctc), "eac": r2(cost + ctc), "forecast_value": r["value"], "margin": r2(r["value"] - cost),
                      "forecast_margin": r2(r["value"] - cost - ctc)})
        rows.append(r)
    # cost posted before coding started: one opening line, not split
    op = agg.get(None)
    if op and (abs(op["posted"]) > 0.004 or abs(op["waiting"]) > 0.004):
        cost = op["posted"] + op["waiting"]
        rows.append({"code_id": None, "code": "OPEN", "kind": "opening", "name": "Cost before coding started (not split by item)",
                     "cost_posted": r2(op["posted"]), "cost_waiting": r2(op["waiting"]), "cost_accrued": 0.0, "cost": r2(cost),
                     "cost_l": r2(op["L"]), "cost_m": r2(op["M"]), "cost_e": r2(op["E"]), "cost_s": r2(op["S"]), "cost_o": r2(op["O"]),
                     "value": 0.0, "margin": r2(-cost), "ctc": 0.0, "eac": r2(cost), "forecast_value": 0.0, "forecast_margin": r2(-cost),
                     "flags": [], "forecast_basis": "not forecast", "cost_period": r2(op["period"])})
    # indirect progress: budgeted indirect heads earn their budget in step with the work done
    fval_t = sum(r["forecast_value"] or 0 for r in rows if r["kind"] == "boq")
    prog = tot_val / fval_t if fval_t else 0.0
    oh = sum(r["cost"] for r in rows if r["kind"] == "overhead")
    spread = (setting(c, "cl_spread") or "both") == "both"
    for r in rows:
        if r["kind"] in ("prelim", "overhead", "temp") and r.get("budget_current"):
            r["bcwd"] = r2(r["budget_current"] * prog)
            r["cpi"] = round(r["bcwd"] / r["cost"], 2) if r["cost"] > EPS else None
        if r["kind"] == "boq" and spread:
            r["oh_spread"] = r2(oh * (r["value"] / tot_val)) if tot_val else 0.0
            r["margin_after_oh"] = r2(r["margin"] - r["oh_spread"])
    T = lambda f_: r2(sum((r.get(f_) or 0) for r in rows))  # noqa: E731
    tot = {f_: T(f_) for f_ in ("value", "cost_posted", "cost_waiting", "cost_accrued", "cost", "cost_l", "cost_m", "cost_e", "cost_s",
                                "cost_o", "ctc", "eac", "forecast_value", "wastage_value", "cost_period")}
    tot["bcwd"] = T("bcwd")
    with_b = [r for r in rows if r.get("bcwd") is not None]
    cb = sum(r["cost"] for r in with_b)
    tot["cpi"] = round(tot["bcwd"] / cb, 2) if cb > EPS else None
    tot["margin"] = r2(tot["value"] - tot["cost"])
    tot["forecast_margin"] = r2(tot["forecast_value"] - tot["eac"])
    tot["forecast_margin_pct"] = round(100 * tot["forecast_margin"] / tot["forecast_value"], 2) if tot["forecast_value"] else None
    tot["margin_pct"] = round(100 * tot["margin"] / tot["value"], 2) if tot["value"] else None
    contract = sum((k["bqty"] or 0) * (k["rate"] or 0) for k in codes if k["kind"] == "boq")
    orig_total = sum(line_amount(v_) for v_ in ol.values())
    bid_margin = round(100 * (contract - orig_total) / contract, 2) if contract and ol else None
    tot["bid_margin_pct"] = bid_margin
    tot["claims_pending"] = claims
    tot["pa_certified"] = pa_val
    # billing lag
    billed_val = val(c, "SELECT SUM(l.amount) FROM ipc_lines l JOIN ipc i ON i.id=l.ipc_id WHERE i.project_id=? AND i.date<=? AND "
                        "i.status IN ('submitted','certified')", (pid, asof)) or 0
    six = (date.fromisoformat(asof) - timedelta(days=183)).isoformat()
    recent = val(c, "SELECT SUM(l.amount) FROM ipc_lines l JOIN ipc i ON i.id=l.ipc_id WHERE i.project_id=? AND i.date>? AND i.date<=? AND "
                    "i.status IN ('submitted','certified')", (pid, six, asof)) or 0
    first = val(c, "SELECT MIN(date) FROM ipc WHERE project_id=? AND status IN ('submitted','certified')", (pid,), None)
    mths = max(1.0, min(6.0, _months_between(first, asof))) if first else 6.0
    avg_bill = recent / mths
    tot["billed_value"] = r2(billed_val)
    tot["unbilled_value"] = r2(tot["value"] - billed_val)
    tot["avg_monthly_billing"] = r2(avg_bill)
    flags = []
    if bid_margin is not None and tot["forecast_margin_pct"] is not None and tot["forecast_margin_pct"] < bid_margin - sf(c, "cl_flag_margin_drop"):
        flags.append({"key": "margin_fade", "text": "Forecast margin %s%% is more than %s points below the bid margin %s%%" %
                      (tot["forecast_margin_pct"], fmt(sf(c, "cl_flag_margin_drop")), bid_margin)})
    if tot["forecast_margin"] < -0.5:
        flags.append({"key": "loss", "text": "Forecast final loss %s: accounts to consider a loss provision (NFRS 15)" % fmt(-tot["forecast_margin"])})
    if tot["unbilled_value"] > max(avg_bill * sf(c, "cl_flag_billing_months"), 0.5) and tot["value"] > 0:
        flags.append({"key": "billing_lag", "text": "Value earned is %s ahead of IPCs, more than %s month(s) of average billing (%s)" %
                      (fmt(tot["unbilled_value"]), fmt(sf(c, "cl_flag_billing_months")), fmt(avg_bill))})
    for r in rows:
        for f_ in r.get("flags") or []:
            flags.append({"key": f_, "code": r["code"], "text": "%s %s" % (r["code"], FLAG_TEXT.get(f_, f_))})
    una = next((r for r in rows if r["kind"] == "unallocated"), None)
    coded = sum(r["cost"] for r in rows if r["kind"] != "opening")
    tot["unallocated_pct"] = round(100 * (una["cost"] if una else 0) / coded, 2) if abs(coded) > EPS else 0.0
    return {"project": {"id": pid, "code": p["code"], "name": p["name"], "contract_value": p["contract_value"], "end": end},
            "as_of": asof, "period": period, "period_label": period_label(period), "from": pfrom, "rows": rows, "total": tot,
            "flags": flags, "mode": mode, "budget_version": cur and cur["version_no"], "qty_source": "close" if close else "measurement",
            "accruals": acc, "standby_hours": std_hrs, "standby_cost": std_amt, "provisional": close is None or close.get("status") != "locked"}


FLAG_TEXT = {"cpi_low": "cost performance below the threshold", "negative_margin": "negative margin on an item more than the threshold done",
             "cost_no_progress": "cost this month with no measured progress", "budget_placeholder": "budget is a zero-cost placeholder"}


# ───────────────────────────── per-project period lock ─────────────────────────────
LOCK_EXEMPT = ("cl_accrual", "cl_accrual_rev")


def locked_close(c, pid, d):
    if not pid or not d or not _has(c, "cl_closes"):
        return None
    return q1(c, "SELECT * FROM cl_closes WHERE project_id=? AND status='locked' AND from_date<=? AND cutoff_date>=? "
                 "ORDER BY cutoff_date DESC LIMIT 1", (int(pid), d[:10], d[:10]))


def lock_check(c, pid, d, what="This entry"):
    k = locked_close(c, pid, d)
    if k:
        p = q1(c, "SELECT code FROM projects WHERE id=?", (int(pid),)) or {}
        raise ApiError("%s is dated %s, inside %s which is closed and locked for project %s. Date it after %s, or ask the "
                       "director to reopen the month (Project close › Reopen); the reopening is logged." %
                       (what, d[:10], period_label(k["period"]), p.get("code") or pid, k["cutoff_date"]))


def _voucher_projects(project_id, lines):
    ps = {int(project_id)} if project_id else set()
    for ln in lines or []:
        if ln.get("project_id"):
            ps.add(int(ln["project_id"]))
    return ps


_LOCKW = {}


def _locked_post_for(f):
    w = _LOCKW.get(id(f))
    if w:
        return w

    def post_voucher(c, user, vtype, d, narration, lines, project_id=None, source="manual", source_id=None, party_id=None,
                     ref_no=None, status="posted", _f=f):
        if status in ("posted", "submitted") and (source or "") not in LOCK_EXEMPT and _has(c, "cl_closes"):
            for p_ in _voucher_projects(project_id, lines):
                lock_check(c, p_, d, "This entry (%s)" % (narration or vtype or "voucher")[:80])
        return _f(c, user, vtype, d, narration, lines, project_id=project_id, source=source, source_id=source_id,
                  party_id=party_id, ref_no=ref_no, status=status)
    for flag in ("_bco219", "_bco220", "_bco221", "_bco223"):
        if getattr(f, flag, False):
            setattr(post_voucher, flag, True)
    post_voucher._bco224 = True
    post_voucher._inner = f
    _LOCKW[id(f)] = post_voucher
    return post_voucher


def _install_lock():
    import sys
    for name, m in list(sys.modules.items()):
        if m is None or not name:
            continue
        f = getattr(m, "post_voucher", None)
        if not callable(f) or getattr(f, "_bco224", False):
            continue
        if getattr(f, "__name__", "") not in ("post_voucher", "gated_post_voucher"):
            continue   # api_fa's post_voucher(c, u, head, lines) calls core.post_voucher, which is wrapped
        if getattr(f, "__module__", "") not in ("core", "api_exec"):
            continue
        try:
            setattr(m, "post_voucher", _locked_post_for(f))
        except Exception:
            pass


def _pq_post_w(orig):
    def pq_post2(c, u, a):
        for vid in a.get("ids") or [a.get("id")]:
            if not vid:
                continue
            v = q1(c, "SELECT * FROM vouchers WHERE id=?", (int(vid),))
            if not v:
                continue
            d = a.get("date") or v["date"]
            if (v["source"] or "") not in LOCK_EXEMPT:
                ps = {r["p"] for r in q(c, "SELECT DISTINCT COALESCE(project_id, ?) p FROM voucher_lines WHERE voucher_id=?",
                                        (v["project_id"], v["id"])) if r["p"]}
                if v["project_id"]:
                    ps.add(v["project_id"])
                for p_ in ps:
                    lock_check(c, p_, d, "Posting %s" % (v["narration"] or "this entry")[:80])
            pq = q1(c, "SELECT * FROM post_queue WHERE voucher_id=?", (v["id"],))
            if pq and pq["source"] == "invoice":
                inv_ = q1(c, "SELECT * FROM invoices WHERE id=?", (pq["source_id"],))
                if inv_ and inv_["source"] == "hire":
                    bad = hire_overbilled(c, inv_["id"])
                    if bad and not (a.get("override_hire") and allowed(c, u, "approve")):
                        raise ApiError("Hire bill held (integrity check 5): %s. The bill may not exceed the approved "
                                       "logsheet hours. Approve the missing logsheets or correct the bill; a director can "
                                       "release it with a note." % bad["text"])
                    if bad:
                        audit(c, u, "hire_release", "invoices", inv_["id"], {"note": a.get("note"), "detail": bad["text"]})
        return orig(c, u, a)
    return pq_post2


def _dpr_approve_w(orig):
    def dpr_approve2(c, u, a):
        d = get(c, "dpr", int(a["id"]), "DPR")
        lock_check(c, d["project_id"], d["date"], "DPR %s" % (d.get("no") or d["id"]))
        if coding_on(c, d["project_id"], d["date"]):
            pr = dpr_problems(c, d)
            if pr:
                raise ApiError("This DPR cannot be approved yet: " + "; ".join(x["what"] for x in pr[:6]) +
                               ". Link each gang and machine to a work line, or to Idle with the delay that caused it.")
        return orig(c, u, a)
    return dpr_approve2


def _install():
    _install_lock()
    _wrap("dpr.submit", _dpr_submit_w)
    _wrap("dpr.approve", _dpr_approve_w)
    _wrap("mrq.approve", _mrq_approve_w)
    _wrap("pr.approve", _pr_approve_w)
    _wrap("sco.approve", _sco_approve_w)
    _wrap("issue.post", _issue_post_w)
    _wrap("var.decide", _var_decide_w)
    _wrap("pq.post", _pq_post_w)


# ───────────────────────────── Module 8: integrity checks ─────────────────────────────
CHECKS = [(1, "Project cost equals ledger", True), (2, "Stock equals inventory accounts", True),
          (3, "Labour hours carried to cost", True), (4, "Machine hours agree", True), (5, "Hire not overbilled", True),
          (6, "Billing within measurement", False), (7, "Receivables agree", True), (8, "Subcontract within main measurement", False),
          (9, "Cost is coded", True), (10, "Queue cleared", True), (11, "Variations budgeted", False), (12, "Overruns explained", False)]
CHECK_NAME = {n: t for n, t, _b in CHECKS}
CHECK_BLOCKS = {n: b for n, _t, b in CHECKS}


def _doc(kind, id_, ref, text, link=None):
    return {"doc": kind, "id": id_, "ref": ref, "text": text, "link": link}


def hire_overbilled(c, invoice_id):
    hb = q1(c, "SELECT b.*, h.unit, h.equipment_id, h.project_id, h.min_units, e.code FROM hire_bills b JOIN hire_agreements h ON "
               "h.id=b.agreement_id JOIN equipment e ON e.id=h.equipment_id WHERE b.invoice_id=?", (invoice_id,))
    if not hb:
        return None
    from calendar import monthrange
    y, m = int(hb["month"][:4]), int(hb["month"][5:7])
    frm, to = hb["month"] + "-01", "%s-%02d" % (hb["month"], monthrange(y, m)[1])
    logs = q(c, "SELECT date, hours, status FROM logsheets WHERE equipment_id=? AND project_id=? AND date BETWEEN ? AND ?",
             (hb["equipment_id"], hb["project_id"], frm, to))
    ok = [l for l in logs if l["status"] == "approved"]
    unit = hb["unit"] or "hour"
    if unit == "hour":
        appr = sum(l["hours"] or 0 for l in ok)
    elif unit == "day":
        appr = len({l["date"] for l in ok if (l["hours"] or 0) > 0})
    else:
        appr = 1 if ok else 0
    billed_work = hb["units"] or 0   # the minimum-hire top-up (billed_units - units) is a contract term, not overbilling
    if billed_work > appr + 0.01:
        return {"billed": r2(billed_work), "approved": r2(appr), "unit": unit, "month": hb["month"], "machine": hb["code"],
                "text": "%s %s: bill %s %s, approved logsheets %s %s" % (hb["code"], hb["month"], r2(billed_work), unit, r2(appr), unit)}
    return None


def run_checks(c, pid, frm, cutoff, close=None):
    """The twelve checks. Each returns result pass | fail | warn, the figures compared and the documents that break it."""
    pid = int(pid)
    out = []
    mode = eq_mode(c)
    rows = project_cost_rows(c, pid, cutoff)

    def add(no, ok, detail, items=(), figures=None, warn_only=None):
        blocks = CHECK_BLOCKS[no] if warn_only is None else not warn_only
        res = "pass" if ok else ("fail" if blocks else "warn")
        out.append({"no": no, "name": CHECK_NAME[no], "blocking": CHECK_BLOCKS[no], "result": res, "detail": detail,
                    "items": list(items)[:200], "count": len(items), "figures": figures or {}})

    # 1. project cost = ledger (posted part)
    ctx = Ctx(c)
    led = q(c, LINE_SQL + "WHERE COALESCE(l.project_id, v.project_id)=? AND v.date<=? AND x.type='expense' AND " + POSTED +
            " AND COALESCE(v.source,'') NOT IN ('cl_accrual','cl_accrual_rev')", (pid, cutoff))
    by_line = {}
    for r in rows:
        if r["status"] == "posted":
            by_line[r["line_id"]] = by_line.get(r["line_id"], 0) + r["amount"]
    ledger_total = ledger_kept = 0.0
    bad = []
    for ln in led:
        amt = (ln["debit"] or 0) - (ln["credit"] or 0)
        ledger_total += amt
        b = basis_of(ctx, ln)
        exp = amt if _keep(b, mode) else 0.0
        ledger_kept += exp
        got = by_line.pop(ln["id"], 0.0)
        if abs(got - exp) > 0.01:
            vno = val(c, "SELECT no FROM vouchers WHERE id=?", (ln["voucher_id"],), "")
            bad.append(_doc("voucher", ln["voucher_id"], vno, "%s: ledger %s, in CVR %s" % (ln["aname"], fmt(exp), fmt(got)),
                            "#/acc/voucher?id=%s" % ln["voucher_id"]))
    extra = sum(v_ for v_ in by_line.values())   # recovery lines and other non-expense rows the CVR kept
    cvr_posted = sum(r["amount"] for r in rows if r["status"] == "posted")
    excluded = ledger_total - ledger_kept
    add(1, not bad and abs(cvr_posted - ledger_kept - extra) < 0.01,
        "CVR posted cost %s; ledger project expense %s%s." % (fmt(cvr_posted), fmt(ledger_total),
                                                             (", less own-equipment %s %s left out under the %s costing switch" %
                                                              ("running costs" if mode == "rate" else "charges", fmt(excluded), mode))
                                                             if abs(excluded) > 0.5 else ""),
        bad, {"cvr_posted": r2(cvr_posted), "ledger": r2(ledger_total), "excluded_by_switch": r2(excluded)})

    # 2. stock = inventory accounts (company, as 2.20) and this project's stores
    try:
        import api_workspace as W
        sl = W.stock_locations(c, None, {})
        diff = sl["difference"]
        items = []
        if abs(diff) >= 0.01:
            for s_ in q(c, "SELECT b.store_id, s.name, p.code, SUM(b.value) v FROM stock_balances b JOIN stores s ON s.id=b.store_id "
                           "JOIN projects p ON p.id=b.project_id GROUP BY b.store_id"):
                led_s = val(c, "SELECT SUM(COALESCE(value_in,0)-COALESCE(value_out,0)) FROM stock_ledger WHERE store_id=?",
                            (s_["store_id"],), None)
                if led_s is not None and abs((led_s or 0) - (s_["v"] or 0)) >= 0.01:
                    items.append(_doc("store", s_["store_id"], s_["name"], "%s %s: balance %s, movements %s" %
                                      (s_["code"], s_["name"], fmt(s_["v"]), fmt(led_s))))
            if not items:
                items.append(_doc("ledger", None, "Inventory accounts", "Stock %s, inventory accounts %s" %
                                  (fmt(sl["total"]), fmt(sl["ledger_inventory"])), "#/ws/stock"))
        add(2, abs(diff) < 0.01, "Stock %s; inventory accounts %s; difference %s." % (fmt(sl["total"]), fmt(sl["ledger_inventory"]),
                                                                                       fmt(diff)), items,
            {"stock": sl["total"], "ledger": sl["ledger_inventory"]})
    except Exception as e:  # pragma: no cover
        add(2, False, "Could not compare stock: %s" % e)

    # 3. labour hours carried to cost: own gangs on approved DPRs against the DPR's labour entry (posted or waiting);
    #    labour-supply gangs are carried by the accrual until their bill posts
    items = []
    hrs_dpr = hrs_cost = 0.0
    for d in q(c, "SELECT * FROM dpr WHERE project_id=? AND status='approved' AND date<=? ORDER BY date", (pid, cutoff)):
        gangs = q(c, "SELECT * FROM dpr_labour WHERE dpr_id=? AND party_id IS NULL AND COALESCE(amount,0)>0", (d["id"],))
        if not gangs:
            continue
        amt = sum(g["amount"] for g in gangs)
        hrs = sum((g["count"] or 0) * ((g["hours"] or 0) + (g["ot_hours"] or 0)) for g in gangs)
        posted = val(c, "SELECT SUM(l.debit-l.credit) FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id JOIN accounts x ON "
                        "x.id=l.account_id WHERE v.source='dpr' AND v.source_id=? AND x.role='labour_cost' AND (" + POSTED + " OR " +
                        WAITING + ")", (d["id"],)) or 0
        hrs_dpr += hrs
        hrs_cost += hrs * (posted / amt if amt else 0)
        if abs(posted - amt) > 0.5:
            items.append(_doc("dpr", d["id"], d.get("no") or d["date"], "DPR %s: own gangs %s h worth %s, labour cost %s" %
                              (d["date"], r2(hrs), fmt(amt), fmt(posted)), "#/p/dpr?id=%s" % d["id"]))
    add(3, not items, "DPR own-labour hours %s; hours behind labour cost %s." % (r2(hrs_dpr), r2(hrs_cost)), items,
        {"dpr_hours": r2(hrs_dpr), "cost_hours": r2(hrs_cost)})

    # 4. machine hours: logsheets against DPR equipment hours, per machine and month (1% tolerance)
    tol = sf(c, "cl_chk4_tol")
    items = []
    lg = {(r["e"], r["m"]): r["h"] or 0 for r in q(c, "SELECT equipment_id e, substr(date,1,7) m, SUM(hours) h FROM logsheets WHERE "
                                                     "project_id=? AND date<=? AND date>=? GROUP BY 1, 2", (pid, cutoff, frm))}
    dp = {(r["e"], r["m"]): r["h"] or 0 for r in q(c, "SELECT x.equipment_id e, substr(d.date,1,7) m, SUM(x.hours) h FROM dpr_equipment x "
                                                     "JOIN dpr d ON d.id=x.dpr_id WHERE d.project_id=? AND d.status='approved' AND "
                                                     "d.date<=? AND d.date>=? GROUP BY 1, 2", (pid, cutoff, frm))}
    for k in sorted(set(lg) | set(dp)):
        a_, b_ = lg.get(k, 0), dp.get(k, 0)
        if abs(a_ - b_) > max(a_, b_) * tol / 100 + 0.01:
            code = val(c, "SELECT code FROM equipment WHERE id=?", (k[0],), "?")
            items.append(_doc("equipment", k[0], code, "%s %s: logsheets %s h, DPR %s h" % (code, k[1], r2(a_), r2(b_)),
                              "#/eq/logsheets?equipment_id=%s" % k[0]))
    add(4, not items, "Logsheet hours %s; DPR machine hours %s (this period)." % (r2(sum(lg.values())), r2(sum(dp.values()))), items)

    # 5. hire bills against approved logsheets
    items = []
    for b in q(c, "SELECT b.invoice_id, i.no, i.status FROM hire_bills b JOIN hire_agreements h ON h.id=b.agreement_id JOIN invoices i ON "
                  "i.id=b.invoice_id WHERE h.project_id=? AND i.status NOT IN ('cancelled') AND i.date<=?", (pid, cutoff)):
        x = hire_overbilled(c, b["invoice_id"])
        if x:
            items.append(_doc("invoice", b["invoice_id"], b["no"], x["text"] + (" (held)" if b["status"] == "awaiting_posting" else ""),
                              "#/acc/invoices?id=%s" % b["invoice_id"]))
    add(5, not items, "Hire bills within approved logsheet hours." if not items else "%d hire bill(s) above approved logsheets." % len(items), items)

    # 6. IPC qty within measured qty
    meas, ipq = measured_qty(c, pid, cutoff), ipc_qty(c, pid, cutoff)
    items = []
    for b, qn in ipq.items():
        if qn > meas.get(b, 0) + EPS:
            code = val(c, "SELECT code FROM boq_items WHERE id=?", (b,), "?")
            nos = [r["no"] or str(r["id"]) for r in q(c, "SELECT DISTINCT i.id, i.no FROM ipc_lines l JOIN ipc i ON i.id=l.ipc_id WHERE "
                                                         "i.project_id=? AND l.boq_item_id=? AND i.date<=? AND i.status IN "
                                                         "('submitted','certified') ORDER BY i.date, i.id", (pid, b, cutoff))]
            items.append(_doc("boq_item", b, code, "%s: IPC %s, measured %s (%s)" % (code, r4(qn), r4(meas.get(b, 0)), ", ".join(nos)),
                              "#/p/ipc"))
    add(6, not items, "IPC quantities within measured quantities." if not items else "%d item(s) billed beyond measurement." % len(items), items)

    # 7. receivables: certified invoices less receipts against the ledger's receivable for the project
    sales = q(c, "SELECT * FROM invoices WHERE kind='sales' AND project_id=? AND status='posted' AND date<=?", (pid, cutoff))
    open_ = 0.0
    for i in sales:
        open_ += (i["payable"] or 0) - (val(c, "SELECT SUM(amount) FROM allocations WHERE invoice_id=? AND active=1 AND date<=?",
                                            (i["id"], cutoff)) or 0)
    led_ar = val(c, "SELECT SUM(l.debit-l.credit) FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id JOIN accounts x ON "
                    "x.id=l.account_id WHERE x.role='ar_control' AND COALESCE(l.project_id, v.project_id)=? AND v.date<=? AND " + POSTED,
                 (pid, cutoff)) or 0
    items = []
    if abs(open_ - led_ar) >= 0.01:
        for v in q(c, "SELECT v.id, v.no, v.source, SUM(l.debit-l.credit) amt FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id "
                      "JOIN accounts x ON x.id=l.account_id WHERE x.role='ar_control' AND COALESCE(l.project_id, v.project_id)=? AND "
                      "v.date<=? AND " + POSTED + " AND COALESCE(v.source,'') NOT IN ('invoice','payment','advance_adjust','reversal') "
                      "GROUP BY v.id", (pid, cutoff)):
            items.append(_doc("voucher", v["id"], v["no"], "Receivable entry not from an invoice or receipt: %s" % fmt(v["amt"]),
                              "#/acc/voucher?id=%s" % v["id"]))
        for i in sales:
            led_i = val(c, "SELECT SUM(l.debit-l.credit) FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id JOIN accounts x ON "
                           "x.id=l.account_id WHERE x.role='ar_control' AND v.id=?", (i["voucher_id"],)) or 0
            if abs(led_i - (i["payable"] or 0)) >= 0.01:
                items.append(_doc("invoice", i["id"], i["no"], "Invoice receivable %s, ledger %s" % (fmt(i["payable"]), fmt(led_i)),
                                  "#/acc/invoices?id=%s" % i["id"]))
        if not items:
            items.append(_doc("project", pid, "Receivable", "Certified less receipts %s; ledger %s. Receipts or invoices posted "
                              "without the project on the receivable line." % (fmt(open_), fmt(led_ar))))
    add(7, abs(open_ - led_ar) < 0.01, "Certified IPCs less receipts %s; receivable in the ledger %s." % (fmt(open_), fmt(led_ar)), items,
        {"documents": r2(open_), "ledger": r2(led_ar)})

    # 8. subcontract within main measurement
    items = []
    for r in subcon_checks(c, pid, cutoff):
        if "paid_ahead" in r["flags"]:
            items.append(_doc("sc_order", r["order_id"], r["order_no"], "%s %s: billed %s, main measured %s on %s" %
                              (r["order_no"], (r["description"] or "")[:40], r["billed_qty"], r["main_measured"], r["boq_code"]),
                              "#/x/sub?id=%s" % r["order_id"]))
    add(8, not items, ("Subcontract quantities within the main measurement (tolerance %s%%)." % fmt(sf(c, "cl_sc_tol"))) if not items else
        "%d subcontract line(s) billed beyond the main measurement (tolerance %s%%)." % (len(items), fmt(sf(c, "cl_sc_tol"))), items)

    # 9. cost is coded
    us = unallocated_share(c, pid, cutoff, rows)
    items = []
    if us["pct"] >= sf(c, "cl_unalloc_block"):
        una = val(c, "SELECT id FROM cl_codes WHERE project_id=? AND code='UNA'", (pid,), None)
        seen = set()
        for r in rows:
            if r["code_id"] == una and r["voucher_id"] not in seen:
                seen.add(r["voucher_id"])
                vno = val(c, "SELECT no FROM vouchers WHERE id=?", (r["voucher_id"],), "")
                items.append(_doc("voucher", r["voucher_id"], vno, "%s %s %s" % (r["date"], r["account"], fmt(r["amount"])),
                                  "#/cl/codes?tab=queue"))
    add(9, us["pct"] < sf(c, "cl_unalloc_block"), "Unallocated %s of %s coded cost (%s%%; limit %s%%)." %
        (fmt(us["amount"]), fmt(us["total"]), us["pct"], fmt(sf(c, "cl_unalloc_block"))), items, us)

    # 10. queue cleared to the cut-off
    items = []
    if _has(c, "post_queue"):
        for r in q(c, "SELECT pq.*, v.date FROM post_queue pq JOIN vouchers v ON v.id=pq.voucher_id WHERE v.status='submitted' AND "
                      "COALESCE(pq.stage,'') NOT IN ('posted','withdrawn') AND v.date<=? AND (pq.project_id=? OR EXISTS (SELECT 1 FROM "
                      "voucher_lines l WHERE l.voucher_id=v.id AND l.project_id=?))", (cutoff, pid, pid)):
            items.append(_doc("queue", r["voucher_id"], r["label"], "%s %s: %s (%s)" % (r["date"], r["label"] or r["source"],
                                                                                    fmt(r["amount"]), r["stage"]), "#/x/queue"))
    add(10, not items, "No entries waiting for accounts dated on or before %s." % cutoff if not items else
        "%d entr%s dated on or before %s still waiting for accounts." % (len(items), "y" if len(items) == 1 else "ies", cutoff), items)

    # 11. approved variations have a budget line
    items = []
    cur = current_version(c, pid)
    cl_ = vlines(c, cur and cur["id"]) if cur else {}
    codes = Codes(c)
    for v in q(c, "SELECT * FROM variations WHERE project_id=? AND status='approved'", (pid,)):
        k = codes.boq(pid, v["boq_item_id"]) if v["boq_item_id"] else None
        line = cl_.get(k) if k else None
        ch = q1(c, "SELECT id FROM cl_budget_changes WHERE variation_id=? AND status='approved'", (v["id"],))
        if not cur:
            if original_version(c, pid):
                items.append(_doc("variation", v["id"], v["no"], "Approved, but the budget has no Current version yet",
                                  "#/p/variations?id=%s" % v["id"]))
            continue
        if not line or (not ch and not line.get("placeholder") and not v["boq_item_id"]):
            items.append(_doc("variation", v["id"], v["no"], "No budget line in the Current budget", "#/cl/budget"))
        elif line.get("placeholder"):
            items.append(_doc("variation", v["id"], v["no"], "Budget line is a zero-cost placeholder: enter its unit costs",
                              "#/cl/budget"))
    add(11, not items, "Every approved variation has a budget line." if not items else
        "%d approved variation(s) without a costed budget line." % len(items), items)

    # 12. overruns explained
    items = []
    over = sf(c, "cl_chk12_over")
    for b in q(c, "SELECT id, code, qty FROM boq_items WHERE project_id=? AND COALESCE(qty,0)>0", (pid,)):
        mq = meas.get(b["id"], 0)
        if mq > b["qty"] * (1 + over / 100) + EPS and not val(c, "SELECT COUNT(*) FROM variations WHERE boq_item_id=? AND "
                                                                 "status IN ('approved','submitted','pending','draft')", (b["id"],)):
            nos = [r["no"] or str(r["id"]) for r in q(c, "SELECT DISTINCT m.id, m.no FROM measurement_lines l JOIN measurements m ON "
                                                         "m.id=l.measurement_id WHERE m.project_id=? AND l.boq_item_id=? AND "
                                                         "m.status='verified' AND m.date<=? ORDER BY m.date, m.id", (pid, b["id"], cutoff))]
            items.append(_doc("boq_item", b["id"], b["code"], "%s: measured %s against contract %s (+%s%%), no variation (%s)" %
                              (b["code"], r4(mq), r4(b["qty"]), round(100 * (mq / b["qty"] - 1), 1), ", ".join(nos)), "#/p/variations"))
    add(12, not items, "No unexplained overruns above %s%%." % fmt(over) if not items else "%d item(s) overrun with no variation." % len(items),
        items)
    if close:
        prev = {r["check_no"]: r for r in q(c, "SELECT * FROM cl_close_checks WHERE close_id=?", (close["id"],))}
        for x in out:
            p_ = prev.get(x["no"])
            if p_ and p_["override_by"] and x["result"] == "fail":
                x["overridden"] = True
                x["override_reason"] = p_["override_reason"]
                x["override_by"] = val(c, "SELECT name FROM users WHERE id=?", (p_["override_by"],), "")
    return out


def checks_ok(checks):
    return all(x["result"] != "fail" or x.get("overridden") for x in checks)


@api("cl.checks", "project", "view")
def cl_checks(c, u, a):
    """Run the twelve checks on demand for a project at a date (default today, period to date)."""
    need(a, "project_id")
    pid = int(a["project_id"])
    _check_project(c, u, pid)
    need_right(c, u, "view", "see the integrity checks")
    asof = a.get("as_of") or today()
    frm = period_bounds(c, period_of_date(c, asof))[0]
    return {"as_of": asof, "from": frm, "checks": run_checks(c, pid, frm, asof)}


# ───────────────────────────── Module 3: monthly project close ─────────────────────────────
SIGN = {"qs": ("signed_qs", "create", "sign value (QS)"), "accounts": ("signed_accounts", "edit", "sign cost (project accountant)"),
        "pm": ("signed_pm", "submit", "sign the forecast (PM)")}
STEP_NAMES = ["Site cut-off: DPRs, logsheets, issues and returns approved", "Measurement to date entered and confirmed by the QS",
              "Subcontract and hire quantities to the cut-off approved", "Accounts queue cleared to the cut-off",
              "Accruals calculated", "Integrity checks pass (or director override)", "Reviewed and signed (QS, accounts, PM)",
              "Director approval and snapshot locked"]


def _close(c, cid):
    return get(c, "cl_closes", int(cid), "Close")


def default_period(c):
    p = period_of_date(c, today())
    return _shift(p, -1)


def site_pending(c, pid, cutoff):
    out = []
    for d in q(c, "SELECT id, no, date, status FROM dpr WHERE project_id=? AND date<=? AND COALESCE(status,'draft') NOT IN "
                  "('approved','cancelled','rejected') ORDER BY date", (pid, cutoff)):
        out.append(_doc("dpr", d["id"], d["no"] or d["date"], "DPR %s is %s" % (d["date"], d["status"] or "draft"), "#/p/dpr?id=%s" % d["id"]))
    for l in q(c, "SELECT l.id, l.date, l.status, e.code, COALESCE(e.ownership,'owned') own FROM logsheets l JOIN equipment e ON "
                  "e.id=l.equipment_id WHERE l.project_id=? AND l.date<=? AND COALESCE(l.status,'draft')<>'approved' ORDER BY l.date",
                  (pid, cutoff)):
        out.append(_doc("logsheet", l["id"], l["code"], "Logsheet %s %s is %s%s" % (l["code"], l["date"], l["status"] or "draft",
                                                                                 " (hired)" if l["own"] != "owned" else ""),
                        "#/eq/logsheets?id=%s" % l["id"]))
    for t, lab, link in (("issues", "Issue", "#/inv/issues"), ("returns", "Return", "#/inv/returns")):
        for d in q(c, "SELECT id, no, date, status FROM %s WHERE project_id=? AND date<=? AND COALESCE(status,'draft') NOT IN "
                      "('posted','cancelled','rejected') ORDER BY date" % t, (pid, cutoff)):
            out.append(_doc(t[:-1], d["id"], d["no"], "%s %s %s is %s" % (lab, d["no"] or "", d["date"], d["status"] or "draft"), link))
    return out


def close_steps(c, k, checks=None):
    pid, cutoff = k["project_id"], k["cutoff_date"]
    sp = site_pending(c, pid, cutoff)
    hired = [x for x in sp if x["doc"] == "logsheet" and "(hired)" in x["text"]]
    q10 = q(c, "SELECT pq.voucher_id FROM post_queue pq JOIN vouchers v ON v.id=pq.voucher_id WHERE v.status='submitted' AND "
               "COALESCE(pq.stage,'') NOT IN ('posted','withdrawn') AND v.date<=? AND (pq.project_id=? OR EXISTS (SELECT 1 FROM "
               "voucher_lines l WHERE l.voucher_id=v.id AND l.project_id=?))", (cutoff, pid, pid)) if _has(c, "post_queue") else []
    has_sc = bool(val(c, "SELECT COUNT(*) FROM sc_orders WHERE project_id=? AND status NOT IN ('draft','cancelled')", (pid,))) \
        if _has(c, "sc_orders") else False
    if checks is None:
        checks = [{"no": r["check_no"], "result": r["result"], "overridden": bool(r["override_by"])}
                  for r in q(c, "SELECT * FROM cl_close_checks WHERE close_id=?", (k["id"],))]
    chk_ok = bool(k["checks_at"]) and bool(checks) and checks_ok(checks)
    signed = all(k[f] for f in ("signed_qs", "signed_accounts", "signed_pm"))
    st = [(not sp, "%d document(s) still open" % len(sp) if sp else "All approved"),
          (bool(k["qty_confirmed_by"]), "Confirmed" if k["qty_confirmed_by"] else "Enter quantities done to date and confirm"),
          (not hired and (not has_sc or bool(k["qty_confirmed_by"])),
           ("%d hired-machine logsheet(s) not approved" % len(hired)) if hired else ("Confirmed" if not has_sc or k["qty_confirmed_by"]
                                                                                 else "Confirm subcontract quantities")),
          (not q10, "%d entr%s waiting" % (len(q10), "y" if len(q10) == 1 else "ies") if q10 else "Cleared"),
          (bool(k["accruals_at"]), "Calculated %s" % k["accruals_at"][:16] if k["accruals_at"] else "Not calculated"),
          (chk_ok, ("Run %s" % k["checks_at"][:16]) if chk_ok else ("Not run" if not k["checks_at"] else "Blocking check(s) failing")),
          (signed, "%d of 3 signed" % sum(1 for f in ("signed_qs", "signed_accounts", "signed_pm") if k[f])),
          (k["status"] == "locked", "Locked %s" % (k["locked_at"] or "")[:16] if k["status"] == "locked" else "Waiting")]
    return [{"no": i + 1, "name": STEP_NAMES[i], "done": bool(ok), "note": note} for i, (ok, note) in enumerate(st)], sp


def _uname(c, uid):
    return val(c, "SELECT name FROM users WHERE id=?", (uid,), None) if uid else None


@api("cl.closes", "project", "view")
def cl_closes(c, u, a):
    need(a, "project_id")
    pid = int(a["project_id"])
    _check_project(c, u, pid)
    ensure_codes(c, pid)
    rows = q(c, "SELECT * FROM cl_closes WHERE project_id=? ORDER BY period DESC", (pid,))
    for r in rows:
        r["period_label"] = period_label(r["period"])
        r["summary"] = json.loads(r["summary"]) if r["summary"] else None
    dp = default_period(c)
    return {"rows": rows, "default_period": dp, "default_label": period_label(dp), "coding_from": coding_from(c, pid),
            "can": {k: allowed(c, u, v) for k, v in (("open", "create"), ("lock", "approve"), ("view", "view"))}}


@api("cl.close_open", "project", "view")
def cl_close_open(c, u, a):
    need(a, "project_id")
    pid = int(a["project_id"])
    _check_project(c, u, pid)
    need_right(c, u, "create", "start a project close")
    per = a.get("period") or default_period(c)
    frm, cut = period_bounds(c, per)
    if cut > today():
        raise ApiError("%s ends on %s; a month is closed after its cut-off." % (period_label(per), cut))
    ex = q1(c, "SELECT * FROM cl_closes WHERE project_id=? AND period=?", (pid, per))
    if ex:
        return {"id": ex["id"], "existing": True}
    cid = ins(c, "cl_closes", {"project_id": pid, "period": per, "from_date": frm, "cutoff_date": cut, "status": "open",
                               "created_by": u["id"], "ts": now()})
    # quantities done to date start from the verified measurement book; the QS changes and confirms them
    for b, qn in measured_qty(c, pid, cut).items():
        c.execute("INSERT OR REPLACE INTO cl_close_qty(close_id, boq_item_id, qty_done, measured, source) VALUES(?,?,?,?,?)",
                  (cid, b, qn, qn, "measurement"))
    audit(c, u, "open", "cl_closes", cid, {"project_id": pid, "period": per})
    return {"id": cid}


@api("cl.close_get", "project", "view")
def cl_close_get(c, u, a):
    k = _close(c, a["id"])
    pid = k["project_id"]
    _check_project(c, u, pid)
    steps, pending = close_steps(c, k)
    meas = measured_qty(c, pid, k["cutoff_date"])
    ipq = ipc_qty(c, pid, k["cutoff_date"])
    saved = {r["boq_item_id"]: r for r in q(c, "SELECT * FROM cl_close_qty WHERE close_id=?", (k["id"],))}
    qrows = []
    for b in q(c, "SELECT id, code, description, unit, qty, revised_qty, COALESCE(revised_rate, rate) rate FROM boq_items WHERE "
                  "project_id=? ORDER BY code", (pid,)):
        s_ = saved.get(b["id"]) or {}
        done = s_.get("qty_done") if s_ else meas.get(b["id"], 0)
        qrows.append({"boq_item_id": b["id"], "code": b["code"], "description": b["description"], "unit": b["unit"],
                      "contract_qty": b["qty"], "revised_qty": b["revised_qty"], "rate": b["rate"], "measured": r4(meas.get(b["id"], 0)),
                      "ipc_qty": r4(ipq.get(b["id"], 0)), "qty_done": r4(done or 0), "note": s_.get("note"),
                      "not_billed": r4((done or 0) - ipq.get(b["id"], 0))})
    scs = {r["order_item_id"]: r for r in q(c, "SELECT * FROM cl_close_scqty WHERE close_id=?", (k["id"],))}
    sc_rows = []
    if _has(c, "sc_orders"):
        qty_done = {r["boq_item_id"]: r["qty_done"] for r in qrows}
        for it in q(c, "SELECT oi.*, o.no, p.name party, b.code boq_code, b.qty bqty, b.revised_qty brq FROM sc_order_items oi JOIN sc_orders o "
                       "ON o.id=oi.order_id LEFT JOIN parties p ON p.id=o.party_id LEFT JOIN boq_items b ON b.id=oi.boq_item_id WHERE "
                       "o.project_id=? AND o.status NOT IN ('draft','cancelled') ORDER BY o.no, oi.id", (pid,)):
            billed = val(c, "SELECT SUM(bi.qty) FROM sc_bill_items bi JOIN sc_bills sb ON sb.id=bi.bill_id WHERE bi.order_item_id=? AND "
                            "sb.status NOT IN ('draft','cancelled') AND sb.date<=?", (it["id"], k["cutoff_date"])) or 0
            s_ = scs.get(it["id"])
            sc_rows.append({"order_item_id": it["id"], "order_no": it["no"], "party": it["party"], "description": it["description"],
                            "boq_code": it["boq_code"], "qty": it["qty"], "rate": it["rate"], "billed_qty": r4(billed),
                            "qty_done": r4(s_["qty_done"]) if s_ else r4(default_sc_done(it, qty_done)), "saved": bool(s_)})
    acc = q(c, "SELECT a.*, k.code FROM cl_close_accruals a LEFT JOIN cl_codes k ON k.id=a.cost_code_id WHERE a.close_id=? ORDER BY a.kind, a.id",
            (k["id"],))
    for x in acc:
        x["label"] = ACCRUAL_LABEL.get(x["kind"], x["kind"])
    chk = q(c, "SELECT * FROM cl_close_checks WHERE close_id=? ORDER BY check_no", (k["id"],))
    for x in chk:
        x["name"] = CHECK_NAME.get(x["check_no"])
        x["blocking"] = CHECK_BLOCKS.get(x["check_no"])
        x["detail"] = json.loads(x["detail"]) if x["detail"] else {}
        x["override_name"] = _uname(c, x["override_by"])
    k2 = dict(k, period_label=period_label(k["period"]), summary=json.loads(k["summary"]) if k["summary"] else None)
    for f in ("signed_qs", "signed_accounts", "signed_pm", "approved_by", "qty_confirmed_by", "created_by"):
        k2[f + "_name"] = _uname(c, k[f])
    p = get(c, "projects", pid)
    return {"close": k2, "project": {"id": pid, "code": p["code"], "name": p["name"]}, "steps": steps, "pending": pending[:200],
            "qty": qrows, "sc": sc_rows, "accruals": acc, "checks": chk,
            "reopen_log": [dict(r, by=_uname(c, r["reopened_by"])) for r in q(c, "SELECT * FROM cl_close_reopen_log WHERE close_id=? ORDER BY id",
                                                                             (k["id"],))],
            "can": {"qty": allowed(c, u, "create"), "accruals": allowed(c, u, "edit"), "qs": allowed(c, u, "create"),
                    "accounts": allowed(c, u, "edit"), "pm": allowed(c, u, "submit"), "lock": allowed(c, u, "approve"),
                    "post": allowed(c, u, "post")},
            "accrual_post": setting(c, "cl_accrual_post") == "1"}


def _editable(k):
    if k["status"] == "locked":
        raise ApiError("%s is locked. The director can reopen it." % period_label(k["period"]))


def _unsign(c, k):
    c.execute("UPDATE cl_closes SET signed_qs=NULL, signed_qs_at=NULL, signed_accounts=NULL, signed_accounts_at=NULL, signed_pm=NULL, "
              "signed_pm_at=NULL WHERE id=?", (k["id"],))


@api("cl.close_qty_save", "project", "view")
def cl_close_qty_save(c, u, a):
    k = _close(c, a["id"])
    _check_project(c, u, k["project_id"])
    _editable(k)
    need_right(c, u, "create", "enter quantities done for the close")
    for r in a.get("rows") or []:
        b = int(r["boq_item_id"])
        if not q1(c, "SELECT id FROM boq_items WHERE id=? AND project_id=?", (b, k["project_id"])):
            raise ApiError("BOQ item %s is not on this project." % b)
        qn = float(r.get("qty_done") or 0)
        if qn < 0:
            raise ApiError("Quantity done cannot be negative.")
        m = val(c, "SELECT measured FROM cl_close_qty WHERE close_id=? AND boq_item_id=?", (k["id"], b), None)
        c.execute("INSERT OR REPLACE INTO cl_close_qty(close_id, boq_item_id, qty_done, measured, source, note) VALUES(?,?,?,?,?,?)",
                  (k["id"], b, qn, m, "qs", r.get("note")))
    for r in a.get("sc_rows") or []:
        c.execute("INSERT OR REPLACE INTO cl_close_scqty(close_id, order_item_id, qty_done, note) VALUES(?,?,?,?)",
                  (k["id"], int(r["order_item_id"]), float(r.get("qty_done") or 0), r.get("note")))
    upd(c, "cl_closes", k["id"], {"status": "review" if k["status"] == "open" else k["status"], "ts": now()})
    if a.get("confirm"):
        upd(c, "cl_closes", k["id"], {"qty_confirmed_by": u["id"], "qty_confirmed_at": now()})
    else:
        upd(c, "cl_closes", k["id"], {"qty_confirmed_by": None, "qty_confirmed_at": None})
    _unsign(c, k)
    audit(c, u, "qty", "cl_closes", k["id"], {"rows": len(a.get("rows") or []), "confirm": bool(a.get("confirm"))})
    return True


@api("cl.close_accruals", "project", "view")
def cl_close_accruals(c, u, a):
    k = _close(c, a["id"])
    _check_project(c, u, k["project_id"])
    _editable(k)
    need_right(c, u, "edit", "calculate accruals")
    acc = accruals(c, k["project_id"], k["cutoff_date"], k)
    _store_accruals(c, k, acc)
    upd(c, "cl_closes", k["id"], {"accruals_at": now(), "status": "review" if k["status"] == "open" else k["status"]})
    _unsign(c, k)
    return {"accruals": acc}


def _store_accruals(c, k, acc):
    if q1(c, "SELECT id FROM cl_close_accruals WHERE close_id=? AND voucher_id IS NOT NULL", (k["id"],)):
        return   # posted as journals: the register keeps what was posted
    c.execute("DELETE FROM cl_close_accruals WHERE close_id=?", (k["id"],))
    for x in acc:
        ins(c, "cl_close_accruals", {"close_id": k["id"], "kind": x["kind"], "source_type": x["source_type"], "source_id": x["source_id"],
                                     "cost_code_id": x.get("code_id"), "amount": x["amount"], "detail": x["detail"]})


@api("cl.close_checks", "project", "view")
def cl_close_checks(c, u, a):
    k = _close(c, a["id"])
    _check_project(c, u, k["project_id"])
    _editable(k)
    need_right(c, u, "view", "run the integrity checks")
    res = run_checks(c, k["project_id"], k["from_date"], k["cutoff_date"], k)
    _store_checks(c, k, res)
    upd(c, "cl_closes", k["id"], {"checks_at": now()})
    return {"checks": res, "ok": checks_ok(res)}


def _store_checks(c, k, res):
    old = {r["check_no"]: r for r in q(c, "SELECT * FROM cl_close_checks WHERE close_id=?", (k["id"],))}
    for x in res:
        o = old.get(x["no"]) or {}
        keep = x["result"] == "fail" and o.get("override_by")
        c.execute("INSERT OR REPLACE INTO cl_close_checks(close_id, check_no, result, detail, override_by, override_reason, ts) "
                  "VALUES(?,?,?,?,?,?,?)", (k["id"], x["no"], x["result"],
                                            json.dumps({"text": x["detail"], "items": x["items"][:60], "count": x["count"],
                                                        "figures": x["figures"]}),
                                            o.get("override_by") if keep else None, o.get("override_reason") if keep else None, now()))


@api("cl.close_override", "project", "view")
def cl_close_override(c, u, a):
    k = _close(c, a["id"])
    _check_project(c, u, k["project_id"])
    _editable(k)
    need_right(c, u, "approve", "override a blocking check (director)")
    reason = (a.get("reason") or "").strip()
    if len(reason) < 5:
        raise ApiError("Write the reason for the override; it is saved on the close record.")
    n = int(a["check_no"])
    r = q1(c, "SELECT * FROM cl_close_checks WHERE close_id=? AND check_no=?", (k["id"], n))
    if not r or r["result"] != "fail":
        raise ApiError("Only a failing check can be overridden.")
    c.execute("UPDATE cl_close_checks SET override_by=?, override_reason=?, ts=? WHERE close_id=? AND check_no=?",
              (u["id"], reason, now(), k["id"], n))
    audit(c, u, "override", "cl_closes", k["id"], {"check": n, "reason": reason})
    return True


@api("cl.close_sign", "project", "view")
def cl_close_sign(c, u, a):
    k = _close(c, a["id"])
    _check_project(c, u, k["project_id"])
    _editable(k)
    who = a.get("as")
    if who not in SIGN:
        raise ApiError("Sign as qs, accounts or pm.")
    f, right, what = SIGN[who]
    need_right(c, u, right, what)
    steps, _p = close_steps(c, k)
    missing = [s_["name"] for s_ in steps[:6] if not s_["done"]]
    if missing:
        raise ApiError("Finish these steps before signing: " + "; ".join(missing) + ".")
    if u.get("role") != "admin":
        for g, (f2, _r, _w) in SIGN.items():
            if g != who and k[f2] == u["id"]:
                raise ApiError("You already signed this close as %s; another person signs %s." % (g, what.split(" (")[0]))
    upd(c, "cl_closes", k["id"], {f: u["id"], f + "_at": now(), "status": "review"})
    audit(c, u, "sign_" + who, "cl_closes", k["id"], None)
    return True


def close_snapshot(c, k, user=None):
    """Freeze value, cost, accruals, forecast and the KPIs of the project for that month."""
    pid = k["project_id"]
    acc = accruals(c, pid, k["cutoff_date"], k)
    _store_accruals(c, k, acc)
    rep = cvr(c, pid, k["cutoff_date"], k, acc)
    c.execute("DELETE FROM cl_close_lines WHERE close_id=?", (k["id"],))
    for r in rep["rows"]:
        c.execute("INSERT OR REPLACE INTO cl_close_lines(close_id, cost_code_id, qty_done, value_earned, cost_posted, cost_waiting, "
                  "cost_accrued, cost_l, cost_m, cost_e, cost_s, cost_o, budget_cost_done, cost_to_complete, eac, forecast_value, "
                  "wastage_value, flags, data) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (k["id"], r["code_id"] or 0, r.get("qty_done"), r.get("value"), r["cost_posted"], r["cost_waiting"], r["cost_accrued"],
                   r["cost_l"], r["cost_m"], r["cost_e"], r["cost_s"], r["cost_o"], r.get("bcwd"), r.get("ctc"), r.get("eac"),
                   r.get("forecast_value"), r.get("wastage_value"), json.dumps(r.get("flags") or []), json.dumps(r)))
    card = health_card_from(c, pid, rep, k)
    summary = {"total": rep["total"], "flags": rep["flags"], "mode": rep["mode"], "budget_version": rep["budget_version"],
               "standby_cost": rep["standby_cost"], "standby_hours": rep["standby_hours"], "card": card,
               "accruals": {kd: r2(sum(x["amount"] for x in acc if x["kind"] == kd)) for kd in ACCRUAL_LABEL},
               "material_excess": r2(sum(w["excess_value"] for w in material_recon(c, pid, k["cutoff_date"]))),
               "overrides": val(c, "SELECT COUNT(*) FROM cl_close_checks WHERE close_id=? AND override_by IS NOT NULL", (k["id"],))}
    # forecast budget version for this month: forecast unit cost per item, split like the current budget
    cur = current_version(c, pid) or original_version(c, pid)
    if cur:
        old = q1(c, "SELECT id FROM cl_budget_versions WHERE project_id=? AND kind='forecast' AND close_id=?", (pid, k["id"]))
        if old:
            c.execute("DELETE FROM cl_budget_lines WHERE version_id=?", (old["id"],))
            fid = old["id"]
            upd(c, "cl_budget_versions", fid, {"ts": now()})
        else:
            fid = _new_version(c, user, pid, "forecast", "approved", "close", "Forecast at %s" % period_label(k["period"]), k["id"])
        cl_ = vlines(c, cur["id"])
        for r in rep["rows"]:
            if not r["code_id"]:
                continue
            bl = cl_.get(r["code_id"]) or {}
            row = {"version_id": fid, "cost_code_id": r["code_id"], "qty": r.get("qty_total") or bl.get("qty") or 0,
                   "amount": r.get("eac"), "source": "close", "note": r.get("forecast_basis")}
            fu = r.get("forecast_unit")
            if fu is not None:
                tot = unit_total(bl) if bl else 0
                for f in UNITS:
                    row[f] = r2(fu * (bl.get(f) or 0) / tot) if tot else (fu if f == "unit_other" else 0)
            ins(c, "cl_budget_lines", row)
    # machine months (company level) for the period
    for e in q(c, "SELECT * FROM equipment WHERE COALESCE(ownership,'owned')='owned' AND COALESCE(active,1)=1"):
        _save_eq_month(c, e, k["period"])
    return summary


def _save_eq_month(c, e, period):
    m = eq_month(c, e, period)
    c.execute("INSERT OR REPLACE INTO cl_eq_months(equipment_id, period, available_hrs, working_hrs, idle_employer, idle_contractor, "
              "idle_neutral, breakdown_hrs, fuel_litres, charged, actual_cost, recovery, data, ts) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
              (e["id"], period, m["available_hrs"], m["working_hrs"], m["idle_employer"], m["idle_contractor"], m["idle_neutral"],
               m["breakdown_hrs"], m["fuel_litres"], m["charged"], m["actual_cost"], m["recovery"], json.dumps(m), now()))
    return m


@api("cl.close_lock", "project", "view")
def cl_close_lock(c, u, a):
    k = _close(c, a["id"])
    _check_project(c, u, k["project_id"])
    _editable(k)
    need_right(c, u, "approve", "approve and lock a close (director)")
    # the checks run again at the lock: what passed on Monday must still pass now
    res = run_checks(c, k["project_id"], k["from_date"], k["cutoff_date"], k)
    _store_checks(c, k, res)
    upd(c, "cl_closes", k["id"], {"checks_at": now()})
    k = _close(c, k["id"])
    steps, _p = close_steps(c, k, res)
    missing = [s_["name"] for s_ in steps[:7] if not s_["done"]]
    if missing:
        raise ApiError("The close cannot be locked yet: " + "; ".join(missing) + ".")
    summary = close_snapshot(c, k, u)
    upd(c, "cl_closes", k["id"], {"status": "locked", "approved_by": u["id"], "locked_at": now(), "summary": json.dumps(summary),
                                  "notes": a.get("notes") or k["notes"]})
    audit(c, u, "lock", "cl_closes", k["id"], {"period": k["period"], "margin": summary["total"].get("margin")})
    return {"locked": True, "summary": summary}


@api("cl.close_reopen", "project", "view")
def cl_close_reopen(c, u, a):
    k = _close(c, a["id"])
    _check_project(c, u, k["project_id"])
    need_right(c, u, "approve", "reopen a locked month (director)")
    if k["status"] != "locked":
        raise ApiError("Only a locked month can be reopened.")
    reason = (a.get("reason") or "").strip()
    if len(reason) < 5:
        raise ApiError("Write why the month is reopened; it is logged.")
    ins(c, "cl_close_reopen_log", {"close_id": k["id"], "reopened_by": u["id"], "reason": reason, "at": now()})
    upd(c, "cl_closes", k["id"], {"status": "reopened", "approved_by": None, "locked_at": None})
    _unsign(c, k)
    audit(c, u, "reopen", "cl_closes", k["id"], {"reason": reason})
    return True


def _accrued_account(c):
    acc = q1(c, "SELECT id FROM accounts WHERE role='accrued_cost'")
    if acc:
        return acc["id"]
    ap = q1(c, "SELECT * FROM accounts WHERE role='ap_control'")
    code = "2005"
    while q1(c, "SELECT id FROM accounts WHERE code=?", (code,)):
        code = str(int(code) + 1)
    return ins(c, "accounts", {"code": code, "name": "Accrued Project Costs", "type": "liability", "group_id": ap and ap["group_id"],
                               "role": "accrued_cost", "opening_balance": 0, "active": 1})


ACCRUAL_ROLE = {"labour_not_billed": "subcon_cost", "subcontract_not_billed": "subcon_cost", "hire_not_billed": "hire_cost"}


@api("cl.close_post_accruals", "project", "view")
def cl_close_post_accruals(c, u, a):
    """Company switch on: the cost accruals of a locked close go to the posting queue as a journal on the cut-off and its
    reversal on the first day of the next month; accounts posts both. Value accruals stay in the snapshot (NFRS 15 revenue
    is recognised by the 2.16 method)."""
    k = _close(c, a["id"])
    _check_project(c, u, k["project_id"])
    if setting(c, "cl_accrual_post") != "1":
        raise ApiError("Accruals are a management snapshot only. The finance manager can switch on posting in Control settings.")
    need_right(c, u, "post", "post accruals as reversing journals")
    if k["status"] != "locked":
        raise ApiError("Lock the close first; the posted accruals are the locked figures.")
    rows = q(c, "SELECT a.*, k.boq_item_id FROM cl_close_accruals a LEFT JOIN cl_codes k ON k.id=a.cost_code_id WHERE a.close_id=? AND "
                "a.voucher_id IS NULL AND a.kind IN (%s)" % ",".join("?" * len(ACCRUAL_ROLE)), [k["id"]] + list(ACCRUAL_ROLE))
    rows = [r for r in rows if abs(r["amount"] or 0) >= 0.01]
    if not rows:
        raise ApiError("No cost accruals to post for this month.")
    acc_id = _accrued_account(c)
    pid = k["project_id"]
    lines = []
    for r in rows:
        lines.append({"role": ACCRUAL_ROLE[r["kind"]], "debit": r["amount"], "project_id": pid, "boq_item_id": r["boq_item_id"],
                      "narration": (r["detail"] or "")[:120]})
    tot = r2(sum(r["amount"] for r in rows))
    lines.append({"account_id": acc_id, "credit": tot, "project_id": pid, "narration": "Accrued costs %s" % period_label(k["period"])})
    rev = [dict(ln, debit=ln.get("credit") or 0, credit=ln.get("debit") or 0) for ln in lines]
    nxt = (date.fromisoformat(k["cutoff_date"]) + timedelta(days=1)).isoformat()
    vids = []
    for d, ls, src, nar in ((k["cutoff_date"], lines, "cl_accrual", "Accrued costs at %s" % k["cutoff_date"]),
                            (nxt, rev, "cl_accrual_rev", "Reversal of accrued costs at %s" % k["cutoff_date"])):
        vid = core.post_voucher(c, u, "journal", d, nar, ls, project_id=pid, source=src, source_id=k["id"], status="submitted")
        v = q1(c, "SELECT * FROM vouchers WHERE id=?", (vid,))
        try:
            import api_exec as X
            X._unnumber(c, v["no"])
        except Exception:
            pass
        upd(c, "vouchers", vid, {"no": None, "approved_by": None})
        c.execute("INSERT OR REPLACE INTO post_queue(voucher_id, source, source_id, gate, module, stage, label, project_id, amount, vtype, "
                  "created_by, created_at, approved_by, approved_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (vid, src, k["id"], "cl_accrual", "accounts", "approved", nar, pid, tot, "journal", u["id"], now(), u["id"], now()))
        vids.append(vid)
    for r in rows:
        upd(c, "cl_close_accruals", r["id"], {"voucher_id": vids[0], "reversal_id": vids[1]})
    audit(c, u, "post_accruals", "cl_closes", k["id"], {"amount": tot, "vouchers": vids})
    return {"vouchers": vids, "amount": tot}


@api("cl.board", "project", "view")
def cl_board(c, u, a):
    """Every project, every month: open, in review, locked, reopened, overdue."""
    need_right(c, u, "view", "see the close board")
    n = int(a.get("months") or 12)
    last = default_period(c)
    pers = [_shift(last, -i) for i in range(n - 1, -1, -1)]
    allow = _allowed_projects(c, u)
    rows = []
    for p in projects(c):
        if allow is not None and p["id"] not in allow:
            continue
        cf = coding_from(c, p["id"])
        cells = []
        for per in pers:
            frm, cut = period_bounds(c, per)
            k = q1(c, "SELECT id, status, locked_at FROM cl_closes WHERE project_id=? AND period=?", (p["id"], per))
            if k:
                st = k["status"]
            elif cut < cf:
                st = "before"
            else:
                st = "not_started"
            due = (date.fromisoformat(cut) + timedelta(days=9)).isoformat()   # seven working days after the cut-off
            if st in ("not_started", "open", "review", "reopened") and today() > due:
                st_d = "overdue"
            else:
                st_d = st
            cells.append({"period": per, "status": st_d, "base": st, "close_id": k and k["id"], "due": due})
        rows.append({"project_id": p["id"], "code": p["code"], "name": p["name"], "cells": cells, "pilot": bool(val(
            c, "SELECT pilot FROM cl_project WHERE project_id=?", (p["id"],), 0))})
    return {"periods": [{"period": x, "label": period_label(x)} for x in pers], "rows": rows}


# ───────────────────────────── Module 4 endpoints ─────────────────────────────
@api("cl.cvr", "project", "view")
def cl_cvr(c, u, a):
    """The CVR: a locked close's snapshot, or live (provisional) at a date."""
    need(a, "project_id")
    pid = int(a["project_id"])
    _check_project(c, u, pid)
    need_right(c, u, "view", "see the CVR")
    if a.get("close_id"):
        k = _close(c, a["close_id"])
        if k["project_id"] != pid:
            raise ApiError("That close belongs to another project.")
        if k["status"] == "locked":
            return snapshot_report(c, k)
        return cvr(c, pid, k["cutoff_date"], k)
    return cvr(c, pid, a.get("as_of") or today())


def snapshot_report(c, k):
    rows = [json.loads(r["data"]) for r in q(c, "SELECT data FROM cl_close_lines WHERE close_id=? ORDER BY rowid", (k["id"],))]
    s_ = json.loads(k["summary"] or "{}")
    p = get(c, "projects", k["project_id"])
    acc = q(c, "SELECT * FROM cl_close_accruals WHERE close_id=?", (k["id"],))
    for x in acc:
        x["code_id"] = x["cost_code_id"]
        x["side"] = "value" if x["kind"] == "work_not_billed" else ("receivable" if x["kind"] == "billed_not_certified" else
                                                                 ("memo" if x["kind"] == "grn_not_billed" else
                                                                  ("liability" if x["kind"] == "advance_to_recover" else "cost")))
    return {"project": {"id": p["id"], "code": p["code"], "name": p["name"], "contract_value": p["contract_value"]},
            "as_of": k["cutoff_date"], "period": k["period"], "period_label": period_label(k["period"]), "from": k["from_date"],
            "rows": rows, "total": s_.get("total") or {}, "flags": s_.get("flags") or [], "mode": s_.get("mode"),
            "budget_version": s_.get("budget_version"), "accruals": acc, "standby_cost": s_.get("standby_cost"),
            "standby_hours": s_.get("standby_hours"), "provisional": False, "close_id": k["id"], "locked_at": k["locked_at"],
            "qty_source": "close"}


@api("cl.drill", "project", "view")
def cl_drill(c, u, a):
    """What is behind a CVR cell: ledger lines with their documents (cost) or measurement and IPC lines (value)."""
    need(a, "project_id")
    pid = int(a["project_id"])
    _check_project(c, u, pid)
    asof = a.get("as_of") or today()
    code_id = int(a["code_id"]) if a.get("code_id") not in (None, "", "null", "0", 0) else None
    if a.get("what") == "value":
        k = _code_row(c, code_id) or {}
        b = k.get("boq_item_id")
        if not b:
            return {"measurements": [], "ipc": []}
        return {"measurements": q(c, "SELECT m.id, m.no, m.date, m.status, l.qty, l.location FROM measurement_lines l JOIN measurements m ON "
                                     "m.id=l.measurement_id WHERE l.boq_item_id=? AND m.date<=? ORDER BY m.date", (b, asof)),
                "ipc": q(c, "SELECT i.id, i.no, i.date, i.status, l.qty, l.rate, l.amount FROM ipc_lines l JOIN ipc i ON i.id=l.ipc_id WHERE "
                            "l.boq_item_id=? AND i.date<=? ORDER BY i.date", (b, asof))}
    rows = [r for r in project_cost_rows(c, pid, asof, a.get("from")) if r["code_id"] == code_id]
    if a.get("ctype"):
        rows = [r for r in rows if r["ctype"] == a["ctype"]]
    vno = {}
    for r in rows:
        if r["voucher_id"] not in vno:
            vno[r["voucher_id"]] = val(c, "SELECT no FROM vouchers WHERE id=?", (r["voucher_id"],), "")
        r["voucher_no"] = vno[r["voucher_id"]]
        r["amount"] = r2(r["amount"])
        r["doc"] = DOC_LINK.get(r["source"] or "", "").format(id=r["source_id"]) if r["source_id"] else ""
    acc = []
    if a.get("with_accruals", True):
        acc = [x for x in accruals(c, pid, asof) if x["side"] == "cost" and x.get("code_id") == code_id]
    return {"lines": rows, "accruals": acc, "total": r2(sum(r["amount"] for r in rows) + sum(x["amount"] for x in acc))}


DOC_LINK = {"dpr": "#/p/dpr?id={id}", "issue": "#/inv/issues?id={id}", "invoice": "#/acc/invoices?id={id}",
            "sc_bill": "#/x/sub", "hire": "#/acc/invoices?id={id}", "internal_billing": "#/eq/internal", "payment": "#/acc/payments"}


@api("cl.forecast_override", "project", "view")
def cl_forecast_override(c, u, a):
    need(a, "project_id", "cost_code_id")
    pid = int(a["project_id"])
    _check_project(c, u, pid)
    need_right(c, u, "submit", "set a forecast unit cost (PM)")
    cid = int(a["cost_code_id"])
    if a.get("unit_cost") in (None, ""):
        c.execute("DELETE FROM cl_forecast_override WHERE project_id=? AND cost_code_id=?", (pid, cid))
        return True
    note = (a.get("note") or "").strip()
    if not note:
        raise ApiError("Say why: the note shows next to the forecast.")
    c.execute("INSERT OR REPLACE INTO cl_forecast_override(project_id, cost_code_id, unit_cost, note, user_id, ts) VALUES(?,?,?,?,?,?)",
              (pid, cid, float(a["unit_cost"]), note, u["id"], now()))
    audit(c, u, "forecast_override", "cl_codes", cid, {"unit_cost": a["unit_cost"], "note": note})
    return True


def _last_locked(c, pid):
    return q1(c, "SELECT * FROM cl_closes WHERE project_id=? AND status='locked' ORDER BY period DESC LIMIT 1", (pid,))


def health_card_from(c, pid, rep, k=None):
    t = rep["total"]
    val_6 = t.get("avg_monthly_billing") or 0
    daily = (t.get("value") or 0) / max(1.0, (date.fromisoformat(rep["as_of"]) - date.fromisoformat(
        val(c, "SELECT COALESCE(MIN(date), ?) FROM measurements WHERE project_id=?", (rep["as_of"], pid), rep["as_of"]))).days or 1)
    unb = t.get("unbilled_value") or 0
    sev = {"loss": 0, "margin_fade": 1, "billing_lag": 2, "negative_margin": 3, "cpi_low": 4, "cost_no_progress": 5}
    worst = sorted(rep["flags"], key=lambda f_: sev.get(f_["key"], 9))[:1]
    lk = _last_locked(c, pid)
    return {"margin": t.get("margin"), "margin_pct": t.get("margin_pct"), "forecast_margin": t.get("forecast_margin"),
            "forecast_margin_pct": t.get("forecast_margin_pct"), "cpi": t.get("cpi"),
            "unbilled_days": round(unb / daily, 0) if daily > EPS and unb > 0 else 0, "avg_monthly_billing": val_6,
            "last_close": lk and lk["cutoff_date"], "last_close_label": lk and period_label(lk["period"]),
            "worst_flag": worst[0]["text"] if worst else None, "unallocated_pct": t.get("unallocated_pct")}


@api("cl.health_card", "project", "view")
def cl_health_card(c, u, a):
    need(a, "project_id")
    pid = int(a["project_id"])
    _check_project(c, u, pid)
    if not allowed(c, u, "view"):
        return None
    if not is_project(c, pid):
        return None
    rep = cvr(c, pid, today())
    card = health_card_from(c, pid, rep)
    card["material_excess"] = r2(sum(r.get("wastage_value") or 0 for r in rep["rows"]))
    return card


@api("cl.cvr_all", "project", "view")
def cl_cvr_all(c, u, a):
    """CVR, all projects: the last locked close and the live provisional figure side by side."""
    need_right(c, u, "view", "see the CVR of all projects")
    allow = _allowed_projects(c, u)
    out = []
    for p in projects(c):
        if allow is not None and p["id"] not in allow:
            continue
        try:
            live = cvr(c, p["id"], a.get("as_of") or today())
        except ApiError as e:
            out.append({"project_id": p["id"], "code": p["code"], "name": p["name"], "error": str(e)})
            continue
        lk = _last_locked(c, p["id"])
        s_ = json.loads(lk["summary"]) if lk and lk["summary"] else {}
        t = live["total"]
        out.append({"project_id": p["id"], "code": p["code"], "name": p["name"], "value": t["value"], "cost": t["cost"], "margin": t["margin"],
                    "margin_pct": t["margin_pct"], "cpi": t["cpi"], "eac": t["eac"], "forecast_value": t["forecast_value"],
                    "forecast_margin": t["forecast_margin"], "forecast_margin_pct": t["forecast_margin_pct"], "bid_margin_pct": t["bid_margin_pct"],
                    "unallocated_pct": t["unallocated_pct"], "flags": len(live["flags"]),
                    "worst_flag": live["flags"][0]["text"] if live["flags"] else None,
                    "locked_period": lk and period_label(lk["period"]), "locked_margin": (s_.get("total") or {}).get("margin"),
                    "locked_forecast_margin": (s_.get("total") or {}).get("forecast_margin")})
    return {"rows": out, "as_of": a.get("as_of") or today()}


@api("cl.accruals", "accounts", "view")
def cl_accruals_register(c, u, a):
    """Accruals register: every locked close's accruals, with the journals when the company posts them."""
    cond, p = ["k.status='locked'"], []
    if a.get("period"):
        cond.append("k.period=?")
        p.append(a["period"])
    if a.get("project_id"):
        cond.append("k.project_id=?")
        p.append(int(a["project_id"]))
    rows = q(c, "SELECT a.*, k.period, k.cutoff_date, k.project_id, pr.code project, cc.code cost_code, v.no voucher_no, v.status vstatus, "
                "rv.no reversal_no FROM cl_close_accruals a JOIN cl_closes k ON k.id=a.close_id JOIN projects pr ON pr.id=k.project_id "
                "LEFT JOIN cl_codes cc ON cc.id=a.cost_code_id LEFT JOIN vouchers v ON v.id=a.voucher_id LEFT JOIN vouchers rv ON "
                "rv.id=a.reversal_id WHERE " + " AND ".join(cond) + " ORDER BY k.period DESC, pr.code, a.kind", p)
    for r in rows:
        r["label"] = ACCRUAL_LABEL.get(r["kind"], r["kind"])
        r["period_label"] = period_label(r["period"])
    pers = [x["period"] for x in q(c, "SELECT DISTINCT period FROM cl_closes WHERE status='locked' ORDER BY period DESC")]
    return {"rows": rows, "periods": [{"period": x, "label": period_label(x)} for x in pers], "posting": setting(c, "cl_accrual_post") == "1"}


# ───────────────────────────── Module 5 and 6 endpoints ─────────────────────────────
def _eq_months(c, e, last, n=12, live_last=True):
    out = []
    for i in range(n - 1, -1, -1):
        per = _shift(last, -i)
        saved = q1(c, "SELECT data FROM cl_eq_months WHERE equipment_id=? AND period=?", (e["id"], per))
        if saved and not (live_last and i == 0):
            out.append(json.loads(saved["data"]))
        else:
            out.append(eq_month(c, e, per))
    return out


def _owned(c):
    return q(c, "SELECT * FROM equipment WHERE COALESCE(ownership,'owned')='owned' AND COALESCE(active,1)=1 ORDER BY code")


@api("cl.eq", "equipment", "view")
def cl_eq(c, u, a):
    """Equipment business: every owned machine's month, its flags, break-even, own versus hire, and the pool."""
    per = a.get("period") or period_of_date(c, today())
    rows = []
    hist_n = int(sf(c, "cl_util_months") or 3)
    for e in _owned(c):
        months = _eq_months(c, e, per, max(hist_n, 12) if a.get("full") else max(hist_n, 3))
        m = months[-1]
        fl = eq_flags(c, e, months)
        be = break_even(c, e, months) if a.get("full") else {}
        econ_hr = r2(m["actual_cost"] / m["working_hrs"]) if m["working_hrs"] > EPS else None
        rows.append(dict(m, flags=[{"key": k, "text": t} for k, t in fl], economic_per_hour=econ_hr,
                         own_vs_hire=r2((m["market_hire_rate"] or 0) - econ_hr) if econ_hr is not None and m["market_hire_rate"] else None,
                         break_even=be))
    tot = {k: r2(sum(r[k] or 0 for r in rows)) for k in ("working_hrs", "available_hrs", "charged", "actual_cost", "recovery",
                                                          "idle_cost_employer", "idle_cost_contractor", "idle_cost_neutral", "emi_due")}
    tot["utilisation_pct"] = round(100 * tot["working_hrs"] / tot["available_hrs"], 1) if tot["available_hrs"] else None
    return {"period": per, "period_label": period_label(per), "rows": rows, "total": tot, "mode": eq_mode(c),
            "periods": [{"period": _shift(per, -i), "label": period_label(_shift(per, -i))} for i in range(12)]}


@api("cl.eq_detail", "equipment", "view")
def cl_eq_detail(c, u, a):
    e = get(c, "equipment", int(a["equipment_id"]), "Machine")
    per = a.get("period") or period_of_date(c, today())
    months = _eq_months(c, e, per, 12)
    return {"equipment": {"id": e["id"], "code": e["code"], "name": e["name"], "ownership": e.get("ownership")},
            "params": eq_params(c, e), "months": months, "flags": [{"key": k, "text": t} for k, t in eq_flags(c, e, months)],
            "break_even": break_even(c, e, months),
            "loans": q(c, "SELECT id, name, lender, emi, balance FROM loans WHERE COALESCE(active,1)=1 ORDER BY name") if _has(c, "loans") else []}


@api("cl.eq_params_save", "equipment", "edit")
def cl_eq_params_save(c, u, a):
    e = get(c, "equipment", int(a["equipment_id"]), "Machine")
    row = {}
    for k in ("planned_hours_year", "standby_rate", "market_hire_rate", "fuel_norm"):
        v = a.get(k)
        row[k] = float(v) if v not in (None, "") else None
        if row[k] is not None and row[k] < 0:
            raise ApiError("%s cannot be negative." % k.replace("_", " "))
    row["loan_id"] = int(a["loan_id"]) if a.get("loan_id") else None
    c.execute("INSERT OR REPLACE INTO cl_eq_params(equipment_id, planned_hours_year, standby_rate, market_hire_rate, fuel_norm, loan_id, "
              "user_id, ts) VALUES(?,?,?,?,?,?,?,?)", (e["id"], row["planned_hours_year"], row["standby_rate"], row["market_hire_rate"],
                                                       row["fuel_norm"], row["loan_id"], u["id"], now()))
    audit(c, u, "params", "equipment", e["id"], row)
    return True


@api("cl.idle_claims", "commercial", "view")
def cl_idle_claims(c, u, a):
    """Idle hours of own machines by delay responsibility x standby rate: the employer's share is claimable."""
    need(a, "project_id")
    pid = int(a["project_id"])
    _check_project(c, u, pid)
    amt, hrs, rows = idle_standby(c, pid, a.get("from"), a.get("as_of") or today())
    ev = {}
    for r in rows:
        d = q1(c, "SELECT dd.id, dd.category, dd.event_id, d.no dpr_no FROM dpr_delays dd JOIN dpr d ON d.id=dd.dpr_id WHERE d.project_id=? "
                  "AND d.date=? ORDER BY dd.id LIMIT 1", (pid, r["date"]))
        if d:
            r["delay"] = d["category"]
            r["dpr_no"] = d["dpr_no"]
            r["event_id"] = d["event_id"]
            if d["event_id"]:
                ev[d["event_id"]] = ev.get(d["event_id"], 0) + (r["cost"] if r["resp"] == "employer" else 0)
    events = []
    for eid, v in ev.items():
        e = q1(c, "SELECT id, no, title, status FROM events WHERE id=?", (eid,))
        if e:
            events.append(dict(e, idle_cost=r2(v)))
    return {"amount": amt, "hours": hrs, "rows": rows, "events": events,
            "note": "Employer-caused idle hours x standby rate (ownership cost only). Management figure; never posted."}


@api("cl.material", "inventory", "view")
def cl_material(c, u, a):
    need(a, "project_id")
    pid = int(a["project_id"])
    _check_project(c, u, pid)
    rows = material_recon(c, pid, a.get("as_of") or today())
    return {"rows": rows, "excess_value": r2(sum(r["excess_value"] for r in rows)),
            "in_place_value": r2(sum(r["in_place_value"] for r in rows)), "under_use": sum(1 for r in rows if r["under_use"])}


@api("cl.subcon", "commercial", "view")
def cl_subcon(c, u, a):
    need(a, "project_id")
    pid = int(a["project_id"])
    _check_project(c, u, pid)
    rows = subcon_checks(c, pid, a.get("as_of") or today())
    exp = r2(sum(r["material_with_sub"] for r in rows) + sum(r["advance_outstanding"] for r in rows
                                                              if r is next((x for x in rows if x["order_id"] == r["order_id"]), None)))
    return {"rows": rows, "flagged": sum(1 for r in rows if r["flags"]), "unmapped": sum(1 for r in rows if not r["mapped"]),
            "exposure": exp}


# ───────────────────────────── Module 7: company health ─────────────────────────────
def thresholds(c):
    t = dict(HEALTH_DEFAULTS)
    try:
        t.update({k: float(v) for k, v in json.loads(setting(c, "cl_health_thresholds") or "{}").items() if v not in (None, "")})
    except (ValueError, TypeError):
        pass
    return t


def _bal(c, cond, p=(), to=None):
    to = to or today()
    return (val(c, "SELECT SUM(l.debit-l.credit) FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id JOIN accounts x ON x.id=l.account_id "
                   "WHERE " + cond + " AND v.date<=? AND " + POSTED, tuple(p) + (to,)) or 0) + \
        (val(c, "SELECT SUM(opening_balance) FROM accounts x WHERE " + cond, tuple(p)) or 0)


def _role_bal(c, role, to=None):
    return _bal(c, "x.role=?", (role,), to)


def _status(v, green, red, higher_better=True):
    if v is None:
        return "info"
    if higher_better:
        return "green" if v >= green else ("red" if v < red else "amber")
    return "green" if v <= green else ("red" if v > red else "amber")


def _limit(c, key, words):
    s_ = setting(c, key)
    if s_ not in (None, ""):
        return _f(s_)
    if not _has(c, "loans"):
        return None
    tot = 0.0
    for l in q(c, "SELECT * FROM loans WHERE COALESCE(active,1)=1 AND COALESCE(limit_amount,0)>0"):
        k = ((l["kind"] or "") + " " + (l["name"] or "")).lower()
        if any(w in k for w in words):
            tot += l["limit_amount"]
    return tot or None


def _value_at(c, d):
    """Value earned by all projects at a date: measured qty x contract rate (approved variations through revised rates)."""
    return val(c, "SELECT SUM(l.qty*COALESCE(b.revised_rate, b.rate)) FROM measurement_lines l JOIN measurements m ON m.id=l.measurement_id "
                  "JOIN boq_items b ON b.id=l.boq_item_id JOIN projects p ON p.id=m.project_id WHERE m.status='verified' AND m.date<=? "
                  "AND COALESCE(p.kind,'') IN ('','project')", (d,)) or 0


def _months_ago(d, n):
    return (date.fromisoformat(d) - timedelta(days=int(round(30.4375 * n)))).isoformat()


def health(c, asof=None):
    asof = asof or today()
    T = thresholds(c)
    M = []

    def add(key, group, label, value, status, unit="", formula="", detail=None, link=None, threshold=""):
        M.append({"key": key, "group": group, "label": label, "value": value if value is None else (round(value, 2) if isinstance(value, float) else value),
                  "status": status, "unit": unit, "formula": formula, "detail": detail or [], "link": link, "threshold": threshold})
    # profitability
    rows, fv, fm, bidw, bidv = [], 0.0, 0.0, 0.0, 0.0
    losses = []
    for p in projects(c):
        try:
            rep = cvr(c, p["id"], asof)
        except Exception:
            continue
        t = rep["total"]
        rows.append({"project_id": p["id"], "code": p["code"], "name": p["name"], "rep": rep})
        fv += t["forecast_value"] or 0
        fm += t["forecast_margin"] or 0
        if t["bid_margin_pct"] is not None and t["forecast_value"]:
            bidw += t["bid_margin_pct"] * t["forecast_value"]
            bidv += t["forecast_value"]
        if (t["forecast_margin"] or 0) < -0.5:
            losses.append({"code": p["code"], "name": p["name"], "value": t["forecast_margin"], "link": "#/cl/cvr?project_id=%s" % p["id"]})
    fmp = 100 * fm / fv if fv else None
    bid = bidw / bidv if bidv else None
    add("forecast_margin", "Profitability", "Forecast margin, company", fmp,
        _status(fmp, (bid - T["margin_amber"]) if bid is not None else 0, (bid - T["margin_red"]) if bid is not None else 0) if fmp is not None else "info",
        "%", "Σ forecast margin ÷ Σ forecast final value, all projects", [{"code": r["code"], "name": r["name"],
                                                                          "value": r["rep"]["total"]["forecast_margin_pct"],
                                                                          "link": "#/cl/cvr?project_id=%s" % r["project_id"]} for r in rows],
        "#/cl/cvrall", "green ≥ bid margin %s − %s pt; red < bid − %s pt" % (round(bid, 2) if bid is not None else "?", T["margin_amber"], T["margin_red"]))
    add("loss_projects", "Profitability", "Projects forecasting a loss", len(losses), "green" if not losses else "red", "",
        "Count and total forecast loss", losses, "#/cl/cvrall", "green none; red any")
    try:
        import api_mgmt as MG
        frm12 = _months_ago(asof, 12)
        tot_inc = 0.0
        for s_, _l in MG.SEGMENTS:
            tot_inc += MG._seg_pl(c, frm12, asof, s_)[0]
        _ci, co_exp = MG._seg_pl(c, frm12, asof, "company")
        ohr = 100 * co_exp / tot_inc if tot_inc > EPS else None
        add("overhead_ratio", "Profitability", "Company overhead ratio", ohr, _status(ohr, T["overhead_green"], T["overhead_red"], False), "%",
            "Head-office cost (segment Company) ÷ turnover, rolling 12 months", [{"name": "Head-office cost", "value": r2(co_exp)},
                                                                                 {"name": "Turnover", "value": r2(tot_inc)}],
            "#/mg/segments", "green ≤ %s%%; red > %s%%" % (T["overhead_green"], T["overhead_red"]))
        fy0 = _fy_start(c, asof)
        tr = MG._trading(c, fy0, asof)
        tm = tr.get("gross_profit") if isinstance(tr, dict) and tr.get("net_sales") else None
        tmp = tr.get("gp_pct") if isinstance(tr, dict) else None
        plan = T.get("trading_plan_pct") or 0
        add("trading_margin", "Profitability", "Trading margin", tmp if tmp is not None else tm,
            "info" if tmp is None and tm is None else ("red" if (tm or 0) < 0 else ("green" if (tmp or 0) >= plan else "amber")),
            "%" if tmp is not None else "Rs", "Trading segment gross margin, fiscal year to date",
            [{"name": k, "value": v} for k, v in (tr or {}).items() if isinstance(v, (int, float))], "#/mg/segments",
            "green ≥ plan %s%%; red < 0" % plan)
    except Exception as e:
        add("overhead_ratio", "Profitability", "Company overhead ratio", None, "info", "%", "Needs the 2.23 segments: %s" % e)
    fy0 = _fy_start(c, asof)
    pool = []
    for e in _owned(c):
        try:
            import api_exec as X
            r = X.eq_cost_row(c, e, fy0, asof)
            pool.append({"code": e["code"], "name": e["name"], "charged": r["earned"], "cost": r["economic_cost"],
                         "value": r2((r["earned"] or 0) - (r["economic_cost"] or 0))})
        except Exception:
            pass
    pres = sum(x["value"] for x in pool)
    pcost = sum(x["cost"] or 0 for x in pool)
    add("pool_result", "Profitability", "Equipment pool result", r2(pres),
        "info" if not pool else ("green" if pres >= 0 else ("red" if pcost and pres < T["pool_red"] / 100 * pcost else "amber")), "Rs",
        "Σ over/under recovery, all owned machines, fiscal year to date", pool, "#/cl/equipment",
        "green ≥ 0; red < %s%% of pool cost" % T["pool_red"])
    # order book
    wih_rows = []
    for r in rows:
        p = get(c, "projects", r["project_id"])
        cv = val(c, "SELECT SUM(COALESCE(revised_qty, qty)*COALESCE(revised_rate, rate)) FROM boq_items WHERE project_id=?", (p["id"],)) \
            or p["contract_value"] or 0
        left = max(0.0, cv - (r["rep"]["total"]["value"] or 0))
        wih_rows.append({"code": p["code"], "name": p["name"], "value": r2(left)})
    wih = sum(x["value"] for x in wih_rows)
    add("works_in_hand", "Order book", "Works in hand", r2(wih), "info", "Rs",
        "Σ (contract value + approved variations − value earned)", wih_rows, "#/cl/cvrall", "—")
    v_now, v_6 = _value_at(c, asof), _value_at(c, _months_ago(asof, 6))
    avg_m = (v_now - v_6) / 6.0
    mow = wih / avg_m if avg_m > EPS else None
    add("months_of_work", "Order book", "Months of work", mow, _status(mow, T["months_green"], T["months_red"]), "months",
        "Works in hand ÷ average monthly value earned, last 6 months (%s a month)" % fmt(avg_m), [], "#/cl/cvrall",
        "green ≥ %s; red < %s" % (int(T["months_green"]), int(T["months_red"])))
    try:
        import api_decide as D
        cap = D.capacity_calc(c)
        avail = cap["A"] * cap["N"] * cap["M"] - wih
        bids = q(c, "SELECT no, title, our_bid FROM bids WHERE COALESCE(status,'') NOT IN ('won','lost','cancelled','withdrawn') AND "
                    "COALESCE(our_bid,0)>0") if _has(c, "bids") else []
        short = [b for b in bids if b["our_bid"] > avail]
        add("bid_capacity", "Order book", "Available bid capacity", r2(avail), "red" if short else ("green" if bids else "info"), "Rs",
            "A × N × M − B with A %s, N %s, M %s (set per bid document), B = works in hand" % (fmt(cap["A"]), cap["N"], cap["M"]),
            [{"name": "%s %s" % (b["no"], b["title"] or ""), "value": b["our_bid"], "short": b["our_bid"] > avail} for b in bids],
            "#/dc/capacity", "red when an open bid needs more than this")
    except Exception as e:
        add("bid_capacity", "Order book", "Available bid capacity", None, "info", "Rs", "Bid capacity unavailable: %s" % e)
    # cash cycle
    unb = sum(max(0.0, r["rep"]["total"]["unbilled_value"] or 0) for r in rows)
    daily = (v_now - v_6) / 182.0
    ud = unb / daily if daily > EPS else None
    add("unbilled_days", "Cash cycle", "Unbilled days", ud, _status(ud, T["unbilled_green"], T["unbilled_red"], False), "days",
        "Work done not billed %s ÷ average daily value earned %s" % (fmt(unb), fmt(daily)),
        [{"code": r["code"], "name": r["name"], "value": r["rep"]["total"]["unbilled_value"]} for r in rows], "#/cl/cvrall",
        "green ≤ %s; red > %s" % (int(T["unbilled_green"]), int(T["unbilled_red"])))
    open_ar = 0.0
    for i in q(c, "SELECT id, payable FROM invoices WHERE kind='sales' AND status='posted' AND date<=?", (asof,)):
        open_ar += (i["payable"] or 0) - (val(c, "SELECT SUM(amount) FROM allocations WHERE invoice_id=? AND active=1", (i["id"],)) or 0)
    cert6 = val(c, "SELECT SUM(subtotal) FROM invoices WHERE kind='sales' AND status='posted' AND date>? AND date<=?",
                (_months_ago(asof, 6), asof)) or 0
    dd = open_ar / (cert6 / 182.0) if cert6 > EPS else None
    add("debtor_days", "Cash cycle", "Debtor days", dd, _status(dd, T["debtor_green"], T["debtor_red"], False), "days",
        "Certified unpaid %s ÷ average daily certified value %s" % (fmt(open_ar), fmt(cert6 / 182.0)), [], "#/acc/ageing",
        "green ≤ %s; red > %s" % (int(T["debtor_green"]), int(T["debtor_red"])))
    ret_rows = []
    overdue = False
    for p in q(c, "SELECT * FROM projects WHERE COALESCE(kind,'') IN ('','project')"):
        rb = val(c, "SELECT SUM(l.debit-l.credit) FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id JOIN accounts x ON "
                    "x.id=l.account_id WHERE x.role='retention_receivable' AND COALESCE(l.project_id, v.project_id)=? AND v.date<=? AND "
                    + POSTED, (p["id"], asof)) or 0
        if abs(rb) < 0.5:
            continue
        end = p.get("completion_date") or p.get("end_date")
        rel = None
        if end:
            try:
                d0 = date.fromisoformat(end[:10])
                mm = int(p.get("dlp_months") or 12)
                y_, m_ = divmod(d0.month - 1 + mm, 12)
                rel = date(d0.year + y_, m_ + 1, min(d0.day, 28)).isoformat()
            except ValueError:
                rel = None
        od = bool(rel and rel < asof)
        overdue = overdue or od
        ret_rows.append({"code": p["code"], "name": p["name"], "value": r2(rb), "release": rel, "overdue": od})
    add("retention", "Cash cycle", "Retention outstanding", r2(sum(x["value"] for x in ret_rows)), "red" if overdue else "info", "Rs",
        "Retention held by employers, with expected release (completion + defects liability period)", ret_rows, "#/acc/ledger",
        "red when a release is overdue")
    ap = -_role_bal(c, "ap_control", asof)
    purch6 = val(c, "SELECT SUM(subtotal) FROM invoices WHERE kind='purchase' AND status='posted' AND date>? AND date<=?",
                 (_months_ago(asof, 6), asof)) or 0
    sd = ap / (purch6 / 182.0) if purch6 > EPS else None
    sd_st = "info" if sd is None else ("red" if sd > T["supplier_red"] else ("green" if T["supplier_lo"] <= sd <= T["supplier_hi"] else "amber"))
    add("supplier_days", "Cash cycle", "Supplier days", sd, sd_st, "days",
        "Supplier and subcontractor payables %s ÷ average daily purchases %s" % (fmt(ap), fmt(purch6 / 182.0)), [], "#/acc/ageing",
        "green %s to %s; red > %s" % (int(T["supplier_lo"]), int(T["supplier_hi"]), int(T["supplier_red"])))
    od_lim = _limit(c, "cl_od_limit", ("overdraft", " od", "od ", "working capital", "cash credit"))
    try:
        import api_cash as CS
        cc = CS.cash_company(c, None, {"months": 3})
        low = min([r["closing"] for r in cc["rows"]] + [cc["opening"]])
        st = "green" if low >= 0 else ("red" if low < -(od_lim or 0) else "amber")
        add("lowest_balance", "Cash cycle", "Lowest balance, next 13 weeks", r2(low), st, "Rs",
            "Minimum month-end balance of the cash forecast over the next three months (13 weeks), overdraft limit %s" % fmt(od_lim or 0),
            [{"name": r["month"], "value": r["closing"]} for r in cc["rows"]], "#/cash/company",
            "green ≥ 0 without overdraft; red < 0 after the overdraft")
    except Exception as e:
        add("lowest_balance", "Cash cycle", "Lowest balance, next 13 weeks", None, "info", "Rs", "Cash forecast unavailable: %s" % e)
    # liquidity
    ca = _bal(c, "x.type='asset' AND COALESCE(x.role,'') NOT IN ('fixed_asset','accum_dep') AND x.group_id NOT IN (SELECT id FROM "
                 "account_groups WHERE LOWER(name) LIKE '%fixed%' OR LOWER(name) LIKE '%non-current%')", (), asof)
    cl_ = -_bal(c, "x.type='liability' AND LOWER(x.name) NOT LIKE '%term loan%' AND LOWER(x.name) NOT LIKE '%long term%'", (), asof)
    cr = ca / cl_ if cl_ > EPS else None
    add("current_ratio", "Liquidity", "Current ratio", cr, _status(cr, T["current_green"], T["current_red"]), "",
        "Current assets %s ÷ current liabilities %s (ledger)" % (fmt(ca), fmt(cl_)), [], "#/acc/bs",
        "green ≥ %s; red < %s" % (T["current_green"], T["current_red"]))
    stock = _bal(c, "x.role LIKE 'inventory%'", (), asof)
    wc_parts = [("Unbilled", unb), ("Receivables", _role_bal(c, "ar_control", asof)), ("Retention", _role_bal(c, "retention_receivable", asof)),
                ("Stock", stock), ("Material with subcontractors", _role_bal(c, "subcon_material", asof)),
                ("Payables", _role_bal(c, "ap_control", asof)), ("Advances received", _role_bal(c, "client_advance", asof))]
    wc = sum(v for _k, v in wc_parts)
    prev = q1(c, "SELECT value FROM cl_health WHERE key='working_capital' AND period<=? ORDER BY period DESC LIMIT 1 OFFSET 11",
              (period_of_date(c, asof),))
    wc_st = "info"
    if prev and prev["value"]:
        tov_now = _value_at(c, asof) - _value_at(c, _months_ago(asof, 12))
        tov_prev = _value_at(c, _months_ago(asof, 12)) - _value_at(c, _months_ago(asof, 24))
        g_wc = wc / prev["value"] - 1
        g_t = tov_now / tov_prev - 1 if tov_prev > EPS else 0
        wc_st = "red" if g_wc > g_t + 0.0001 else "green"
    add("working_capital", "Liquidity", "Working capital tied up", r2(wc), wc_st, "Rs",
        "Unbilled + receivables + retention + stock + material with subcontractors − payables − advances received",
        [{"name": k, "value": r2(v)} for k, v in wc_parts], "#/mg/segments", "red when rising faster than turnover (needs 12 published months)")
    # guarantees
    bgs = q(c, "SELECT s.*, p.code pcode FROM ca_securities s LEFT JOIN projects p ON p.id=s.project_id WHERE s.status IN "
               "('active','extended','reduced') AND s.kind IN ('performance','advance','retention','bid','mobilisation')") \
        if _has(c, "ca_securities") else []
    out_bg = sum(b["amount"] or 0 for b in bgs)
    bg_lim = _limit(c, "cl_bg_limit", ("guarantee", "bg", "non-fund", "non fund"))
    used = 100 * out_bg / bg_lim if bg_lim else None
    add("bg_used", "Guarantees", "Guarantee limit used", used, _status(used, T["bg_green"], T["bg_red"], False), "%",
        "Outstanding guarantees %s ÷ bank limits %s" % (fmt(out_bg), fmt(bg_lim) if bg_lim else "(set the limit in Control settings)"),
        [{"code": b["pcode"], "name": "%s %s" % (b["kind"], b["number"] or ""), "value": b["amount"], "expiry": b["expiry_date"]} for b in bgs],
        "#/ca/securities", "green ≤ %s%%; red > %s%%" % (int(T["bg_green"]), int(T["bg_red"])))
    soon = (date.fromisoformat(asof) + timedelta(days=30)).isoformat()
    exp_ = [b for b in bgs if b["expiry_date"] and b["expiry_date"] <= soon]
    expired = [b for b in exp_ if b["expiry_date"] < asof]
    add("bg_expiring", "Guarantees", "Guarantees expiring in 30 days", len(exp_), "red" if expired else ("amber" if exp_ else "green"), "",
        "From Bonds, guarantees and insurance (extended ones count as renewed)",
        [{"code": b["pcode"], "name": "%s %s" % (b["kind"], b["number"] or ""), "value": b["amount"], "expiry": b["expiry_date"],
          "status": b["status"]} for b in exp_], "#/ca/securities", "green none; red any past expiry and not renewed")
    mm = _bal(c, "LOWER(x.name) LIKE '%margin%'", (), asof)
    mm_prev = _bal(c, "LOWER(x.name) LIKE '%margin%'", (), _months_ago(asof, 1))
    cash_red = any(m_["key"] == "lowest_balance" and m_["status"] == "red" for m_ in M)
    add("margin_money", "Guarantees", "Margin money blocked", r2(mm), "red" if mm > mm_prev + 0.5 and cash_red else "info", "Rs",
        "Cash held by banks against guarantees (ledger accounts named 'margin')", [], "#/acc/ledger", "red when rising while cash is red")
    # debt
    loans = q(c, "SELECT * FROM loans WHERE COALESCE(active,1)=1") if _has(c, "loans") else []
    borrow = sum(l["balance"] or 0 for l in loans) + max(0.0, -_bal(c, "x.type='liability' AND (LOWER(x.name) LIKE '%loan%' OR "
                                                                      "LOWER(x.name) LIKE '%overdraft%' OR LOWER(x.name) LIKE '%borrowing%')", (), asof))
    eq_ = -_bal(c, "x.type='equity'", (), asof)
    inc_all = -_bal(c, "x.type IN ('income','expense')", (), asof)   # profit to date not yet closed to retained earnings
    equity = eq_ + inc_all
    de = borrow / equity if equity > EPS else None
    add("debt_equity", "Debt", "Debt to equity", de, _status(de, T["de_green"], T["de_red"], False) if equity > EPS else "red", "",
        "Borrowings %s ÷ equity %s (ledger)" % (fmt(borrow), fmt(equity)),
        [{"name": l["name"], "value": l["balance"]} for l in loans], "#/cash/loans", "green ≤ %s; red > %s" % (T["de_green"], T["de_red"]))
    frm12 = _months_ago(asof, 12)
    pl = -(val(c, "SELECT SUM(l.debit-l.credit) FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id JOIN accounts x ON x.id=l.account_id "
                  "WHERE x.type IN ('income','expense') AND v.date>? AND v.date<=? AND " + POSTED, (frm12, asof)) or 0)
    dep = val(c, "SELECT SUM(l.debit-l.credit) FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id JOIN accounts x ON x.id=l.account_id "
                 "WHERE (x.role IN ('depreciation','dep_expense') OR LOWER(x.name) LIKE '%depreciation%' OR LOWER(x.name) LIKE '%interest%') AND "
                 "x.type='expense' AND v.date>? AND v.date<=? AND " + POSTED, (frm12, asof)) or 0
    ebitda = pl + dep
    due12 = sum((l["emi"] or 0) * 12 for l in loans)
    eq_emi_rows = []
    for e in _owned(c):
        f_ = q1(c, "SELECT * FROM eq_finance WHERE equipment_id=?", (e["id"],)) if _has(c, "eq_finance") else None
        if f_ and f_["emi"]:
            n12 = _emis_between(f_, asof, (date.fromisoformat(asof) + timedelta(days=365)).isoformat())
            due12 += n12 * f_["emi"]
            eq_emi_rows.append({"code": e["code"], "name": e["name"], "value": r2(n12 * f_["emi"])})
    dscr = ebitda / due12 if due12 > EPS else None
    add("dscr", "Debt", "Debt service cover", dscr, _status(dscr, T["dscr_green"], T["dscr_red"]), "",
        "Operating profit before depreciation and interest %s ÷ principal and interest due in 12 months %s" % (fmt(ebitda), fmt(due12)),
        [{"name": l["name"], "value": r2((l["emi"] or 0) * 12)} for l in loans] + eq_emi_rows, "#/cash/loans",
        "green ≥ %s; red < %s" % (T["dscr_green"], T["dscr_red"]))
    per = period_of_date(c, asof)
    pf, pt = period_bounds(c, per)
    emi_m = sum(l["emi"] or 0 for l in loans if (not l["end_date"] or l["end_date"] >= pf) and (not l["start_date"] or l["start_date"] <= pt))
    machine_emi = []
    for e in _owned(c):
        f_ = q1(c, "SELECT * FROM eq_finance WHERE equipment_id=?", (e["id"],)) if _has(c, "eq_finance") else None
        if f_ and f_["emi"]:
            n_ = _emis_between(f_, pf, pt)
            if n_:
                emi_m += n_ * f_["emi"]
                try:
                    import api_exec as X
                    earned = X.eq_cost_row(c, e, pf, pt)["earned"]
                except Exception:
                    earned = 0
                machine_emi.append({"code": e["code"], "name": e["name"], "value": r2(n_ * f_["emi"]), "earned": r2(earned),
                                    "short": n_ * f_["emi"] > (earned or 0) + 0.5})
    low_ok = next((m_["status"] for m_ in M if m_["key"] == "lowest_balance"), "info")
    add("emi_month", "Debt", "EMI due this month", r2(emi_m), "info" if not emi_m else ("green" if low_ok == "green" else
                                                                                         ("red" if low_ok == "red" else "amber")), "Rs",
        "Σ machine and other loan instalments due in %s; machines whose EMI is more than they earned are marked" % period_label(per),
        machine_emi + [{"name": l["name"], "value": l["emi"]} for l in loans if l["emi"]], "#/cash/loans",
        "green when the cash forecast covers it")
    # compliance
    tax = tax_due(c, asof)
    add("tax_due", "Compliance", "VAT, TDS and tax due", tax["total"], tax["status"], "Rs", tax["formula"], tax["rows"], "#/acc/vat",
        "green filed and paid by the 25th; red overdue")
    # overridden checks this fiscal year
    ov = q(c, "SELECT p.code, p.name, COUNT(*) n FROM cl_close_checks k JOIN cl_closes x ON x.id=k.close_id JOIN projects p ON p.id=x.project_id "
              "WHERE k.override_by IS NOT NULL AND x.cutoff_date>=? GROUP BY p.id", (fy0,))
    add("overrides", "Compliance", "Close checks overridden this year", sum(r["n"] for r in ov), "amber" if ov else "green", "",
        "Blocking integrity checks the director overrode, per project", [{"code": r["code"], "name": r["name"], "value": r["n"]} for r in ov],
        "#/cl/board", "green none")
    return M, rows


def _fy_start(c, d):
    try:
        import api_exec as X
        return X._fy_bounds(c, d)[0]
    except Exception:
        y = int(d[:4]) - (1 if d[5:] < "07-16" else 0)
        return "%d-07-16" % y


def _emis_between(f_, frm, to):
    if not f_.get("first_emi_date"):
        return 0
    d0 = date.fromisoformat(f_["first_emi_date"][:10])
    n, i = 0, 0
    while True:
        y_, m_ = divmod(d0.month - 1 + i, 12)
        d = date(d0.year + y_, m_ + 1, min(d0.day, 28)).isoformat()
        if d > to or (f_.get("emi_count") and i >= f_["emi_count"]):
            break
        if d >= frm:
            n += 1
        i += 1
    return n


def tax_due(c, asof):
    """VAT (output less input) and TDS payable at the end of the last Nepali month, less what was paid since. Due by the 25th."""
    per = period_of_date(c, asof)
    prev_end = period_bounds(c, _shift(per, -1))[1]
    rows = []
    total = 0.0
    overdue = False
    from sched_calc import bs_to_ad
    y, m = int(per[:4]), int(per[5:7])
    due = bs_to_ad(y, m, 25).isoformat()
    for lab, roles in (("VAT", ("vat_output", "vat_input")), ("TDS", ("tds_payable",))):
        bal = -sum(_role_bal(c, r_, prev_end) for r_ in roles)
        paid = sum(val(c, "SELECT SUM(l.debit) FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id JOIN accounts x ON x.id=l.account_id "
                          "WHERE x.role=? AND v.date>? AND v.date<=? AND v.type IN ('payment','journal') AND " + POSTED,
                          (r_, prev_end, asof)) or 0 for r_ in roles if r_ != "vat_input")
        left = max(0.0, bal - paid)
        od = left > 0.5 and asof > due
        overdue = overdue or od
        total += left
        rows.append({"name": lab, "value": r2(left), "due": due, "overdue": od})
    return {"total": r2(total), "rows": rows, "status": "red" if overdue else ("amber" if total > 0.5 else "green"),
            "formula": "Balance at the end of %s less payments since; due %s" % (period_label(_shift(per, -1)), due)}


@api("cl.health", "accounts", "view")
def cl_health(c, u, a):
    need_right(c, u, "view", "see company health")
    asof = a.get("as_of") or today()
    M, _rows = health(c, asof)
    per = period_of_date(c, asof)
    trend = {}
    for r in q(c, "SELECT * FROM cl_health WHERE period<=? ORDER BY period", (per,)):
        trend.setdefault(r["key"], []).append({"period": r["period"], "label": period_label(r["period"]), "value": r["value"]})
    for m_ in M:
        m_["trend"] = trend.get(m_["key"], [])[-12:]
    pub = val(c, "SELECT MAX(period) FROM cl_health", (), None)
    return {"as_of": asof, "period": per, "period_label": period_label(per), "measures": M, "thresholds": thresholds(c),
            "published": pub and period_label(pub), "can_publish": allowed(c, u, "post")}


@api("cl.health_publish", "accounts", "view")
def cl_health_publish(c, u, a):
    """The finance manager publishes the month's company health after the closes (saved for the twelve-month trend)."""
    need_right(c, u, "post", "publish company health")
    per = a.get("period") or default_period(c)
    cut = period_bounds(c, per)[1]
    M, _rows = health(c, min(cut, today()))
    for m_ in M:
        v = m_["value"]
        c.execute("INSERT OR REPLACE INTO cl_health(period, key, value, status, data, ts) VALUES(?,?,?,?,?,?)",
                  (per, m_["key"], v if isinstance(v, (int, float)) else None, m_["status"], json.dumps(m_), now()))
    audit(c, u, "publish", "cl_health", None, {"period": per})
    return {"period": per, "label": period_label(per), "measures": len(M)}


@api("cl.league", "accounts", "view")
def cl_league(c, u, a):
    """One row per project (trading and company cost centres excluded): worst first."""
    need_right(c, u, "view", "see the project league")
    asof = a.get("as_of") or today()
    out = []
    sev = {"loss": 0, "margin_fade": 1, "billing_lag": 2, "negative_margin": 3, "cpi_low": 4, "cost_no_progress": 5}
    for p in projects(c):
        try:
            rep = cvr(c, p["id"], asof)
        except Exception:
            continue
        t = rep["total"]
        card = health_card_from(c, p["id"], rep)
        open_ar = 0.0
        cert6 = val(c, "SELECT SUM(subtotal) FROM invoices WHERE kind='sales' AND status='posted' AND project_id=? AND date>? AND date<=?",
                    (p["id"], _months_ago(asof, 6), asof)) or 0
        for i in q(c, "SELECT id, payable FROM invoices WHERE kind='sales' AND status='posted' AND project_id=? AND date<=?", (p["id"], asof)):
            open_ar += (i["payable"] or 0) - (val(c, "SELECT SUM(amount) FROM allocations WHERE invoice_id=? AND active=1", (i["id"],)) or 0)
        rec = val(c, "SELECT SUM(gross) FROM payments WHERE kind='receive' AND status='posted' AND project_id=? AND date<=?", (p["id"], asof)) or 0
        paid = val(c, "SELECT SUM(gross) FROM payments WHERE kind='pay' AND status='posted' AND project_id=? AND date<=?", (p["id"], asof)) or 0
        worst = sorted(rep["flags"], key=lambda f_: sev.get(f_["key"], 9))
        out.append({"project_id": p["id"], "code": p["code"], "name": p["name"], "value": t["value"], "cost": t["cost"], "margin": t["margin"],
                    "margin_pct": t["margin_pct"], "forecast_margin": t["forecast_margin"], "forecast_margin_pct": t["forecast_margin_pct"],
                    "cpi": t["cpi"], "unbilled_days": card["unbilled_days"],
                    "debtor_days": round(open_ar / (cert6 / 182.0)) if cert6 > EPS else None, "cash": r2(rec - paid),
                    "worst_flag": worst[0]["text"] if worst else None, "rank": sev.get(worst[0]["key"], 9) if worst else 99})
    out.sort(key=lambda r: (r["rank"], r["forecast_margin_pct"] if r["forecast_margin_pct"] is not None else 999))
    return {"rows": out, "as_of": asof}


# ───────────────────────────── settings and meta ─────────────────────────────
SETTING_KEYS = list(DEFAULTS.keys())


@api("cl.meta", "project", "view")
def cl_meta(c, u, a):
    return {"version": VERSION, "settings": {k: setting(c, k) for k in SETTING_KEYS}, "thresholds": thresholds(c),
            "heads": [{"kind": k, "code": cd, "name": n} for k, cd, n, _s, _r in HEADS], "kinds": KIND_LABEL, "types": TYPES,
            "checks": [{"no": n, "name": t, "blocking": b} for n, t, b in CHECKS], "accrual_labels": ACCRUAL_LABEL,
            "period": period_of_date(c, today()), "period_label": period_label(period_of_date(c, today())),
            "default_close": default_period(c), "mode": eq_mode(c),
            "rights": {r: allowed(c, u, r) for r in ("view", "create", "edit", "submit", "approve", "post", "export")},
            "installed": setting(c, "cl_installed")}


@api("cl.settings_save", "accounts", "view")
def cl_settings_save(c, u, a):
    need_right(c, u, "post", "change control settings (finance manager)")
    ch = {}
    for k in SETTING_KEYS:
        if k in (a.get("settings") or {}):
            v = a["settings"][k]
            if k == "cl_cutoff" and v not in ("end",) and not (str(v).isdigit() and 1 <= int(v) <= 29):
                raise ApiError("Cut-off is 'end' (last day of the Nepali month) or a day 1 to 29.")
            if k == "cl_ctc_rule" and v not in ("actual_after", "budget", "pm"):
                raise ApiError("Cost-to-complete rule is actual_after, budget or pm.")
            if k == "cl_spread" and v not in ("both", "never"):
                raise ApiError("Site overhead spread is both or never.")
            _set(c, k, "" if v is None else v)
            ch[k] = v
    if a.get("thresholds"):
        t = thresholds(c)
        for k, v in a["thresholds"].items():
            if k in HEALTH_DEFAULTS:
                t[k] = float(v)
        _set(c, "cl_health_thresholds", json.dumps(t))
        ch["thresholds"] = a["thresholds"]
    audit(c, u, "settings", "settings", None, ch)
    return True
