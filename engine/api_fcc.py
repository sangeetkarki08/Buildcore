"""
Financial command centre, early warnings, financing scenarios and the report builder (BuildCore 2.29).

Phase 7 and 8 of the master development prompt (sections 20 to 24), built on what 2.24 to 2.28 already calculate.
Nothing here posts, changes a balance or alters an existing table.

  1. Command centre (fcc.summary): company cash, reserve and restricted funds, the 13-week forecast and its lowest
     point, receivables and ageing, payables due in 7 / 30 / 90 days, IPCs by stage, the funding gap, project cash
     consumption and funding requirement, cost to complete and profit, purchase commitments, loans and advances,
     priority alerts and assigned actions. One view per role; every figure is computed by the engine the screen
     links to, so a drill-down shows the same records. A section the user may not see is left out by the engine.
  2. Early warnings (fcc_alerts, fcc_alert_log, fcc_rules): fifteen deterministic checks. Each alert has a fixed
     key, so a scan updates it instead of adding a duplicate. Owner, target date, acknowledgement, escalation,
     resolution and dismissal are kept with a full history. When the condition goes away the alert is cleared,
     never deleted.
  3. Funding gap and financing options (fcc_fin_options): the section 20 funding gap from the 13-week forecast,
     the management actions in the prescribed order with the amounts behind them, and financing options entered
     by hand compared with no financing. A comparison only: nothing is borrowed, posted or recommended.
  4. Report builder (fcc_reports): datasets that apply the same rights and project assignment as their screens,
     filters, columns, grouping, sorting, totals, header, footer and page orientation; Excel and print.
"""
import base64
import json
import re
from datetime import date, timedelta

import core
from core import ApiError, audit, get, ins, now, q, q1, r2, setting, today, upd, val
import api_inventory as inv
from api_inventory import api

VERSION = "2.29.0"
EPS = 1e-6
SYS = {"id": None, "role": "admin", "system": True, "name": "BuildCore check"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS fcc_alerts(
  id INTEGER PRIMARY KEY, fkey TEXT UNIQUE NOT NULL, kind TEXT NOT NULL, domain TEXT NOT NULL, project_id INTEGER,
  title TEXT NOT NULL, detail TEXT, amount REAL, due_date TEXT, sources TEXT, severity TEXT NOT NULL DEFAULT 'medium',
  basis TEXT, action TEXT, owner_id INTEGER, target_date TEXT, status TEXT NOT NULL DEFAULT 'open',
  escalation_level INTEGER NOT NULL DEFAULT 0, escalated_to INTEGER, escalated_at TEXT, present INTEGER NOT NULL DEFAULT 1,
  hold_until TEXT, first_seen TEXT, last_seen TEXT, closed_at TEXT, closed_by INTEGER, note TEXT,
  created_at TEXT, updated_at TEXT);
CREATE INDEX IF NOT EXISTS ix_fcc_alerts_status ON fcc_alerts(status, severity);
CREATE INDEX IF NOT EXISTS ix_fcc_alerts_project ON fcc_alerts(project_id);
CREATE INDEX IF NOT EXISTS ix_fcc_alerts_owner ON fcc_alerts(owner_id);
CREATE TABLE IF NOT EXISTS fcc_alert_log(
  id INTEGER PRIMARY KEY, alert_id INTEGER NOT NULL, ts TEXT NOT NULL, user_id INTEGER, user_name TEXT, action TEXT NOT NULL,
  from_status TEXT, to_status TEXT, note TEXT, data TEXT);
CREATE INDEX IF NOT EXISTS ix_fcc_alert_log ON fcc_alert_log(alert_id);
CREATE TABLE IF NOT EXISTS fcc_rules(
  kind TEXT PRIMARY KEY, enabled INTEGER NOT NULL DEFAULT 1, threshold REAL, owner_role TEXT, target_days INTEGER,
  escalate_days INTEGER, updated_by INTEGER, updated_at TEXT);
CREATE TABLE IF NOT EXISTS fcc_fin_options(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL, amount REAL NOT NULL, rate_pct REAL, fee_pct REAL,
  fee_fixed REAL, draw_date TEXT NOT NULL, tenor_months INTEGER, repayment TEXT NOT NULL DEFAULT 'bullet',
  collateral TEXT, risks TEXT, notes TEXT, active INTEGER NOT NULL DEFAULT 1, created_by INTEGER, created_at TEXT,
  updated_at TEXT);
CREATE TABLE IF NOT EXISTS fcc_reports(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, dataset TEXT NOT NULL, definition TEXT NOT NULL, owner_id INTEGER,
  shared INTEGER NOT NULL DEFAULT 0, builtin INTEGER NOT NULL DEFAULT 0, code TEXT, active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT, updated_at TEXT);
"""

DEFAULTS = {"fcc_scan_minutes": "60", "fcc_escalation_finance": "finance_manager,director",
            "fcc_escalation_project": "project_manager,director"}

# kind, label, domain, severity, threshold, what the threshold means, owner roles (first found), target days, escalate days
KINDS = [
    ("cash_reserve", "Forecast cash below reserve", "cash", "high", 13, "weeks ahead", "finance_manager,accountant", 3, 2),
    ("cash_negative", "Negative projected cash", "cash", "high", 13, "weeks ahead", "finance_manager,accountant", 2, 1),
    ("obligations_due", "Payroll, tax or loan instalment due", "cash", "high", 14, "days ahead", "accountant,finance_manager", 2, 1),
    ("receipt_overdue", "Client payment overdue", "receivables", "medium", 1, "days overdue", "finance_manager,accountant", 7, 7),
    ("ipc_waiting", "IPC waiting for submission or certification", "receivables", "medium", 7, "days in draft",
     "quantity_surveyor,project_manager", 7, 7),
    ("unbilled_work", "Measured work not yet claimed", "receivables", "medium", 100000, "minimum value",
     "quantity_surveyor,project_manager", 7, 7),
    ("payables_due", "Supplier or subcontractor payments due", "payables", "medium", 7, "days ahead",
     "accountant,finance_manager", 3, 3),
    ("po_over_budget", "Purchase order above the budget left", "procurement", "high", 0, "", "project_manager,procurement_officer", 3, 3),
    ("material_shortage", "Material shortage for scheduled work", "stores", "high", 0, "", "procurement_officer,storekeeper,project_manager", 3, 2),
    ("excess_stock", "Stock not moved for 90 days or more", "stores", "low", 50000, "minimum value",
     "storekeeper,procurement_officer,project_manager", 14, 14),
    ("idle_equipment", "Idle or under-used equipment", "equipment", "medium", 0, "", "equipment_manager,project_manager", 7, 7),
    ("cost_overrun", "Project cost overrun", "cost", "high", 0, "", "project_manager,quantity_surveyor", 7, 7),
    ("margin_fade", "Project margin deteriorating", "cost", "high", 0, "", "project_manager,finance_manager", 7, 7),
    ("variation_unapproved", "Variation work not approved", "commercial", "medium", 30, "days pending",
     "quantity_surveyor,project_manager", 14, 14),
    ("forecast_deviation", "Cash differs from the saved forecast", "cash", "medium", 20, "% difference",
     "finance_manager,accountant", 7, 7),
    ("dpr_delay", "DPR reporting delay", "progress", "medium", 2, "days without a DPR", "project_manager,site_engineer", 2, 2),
]
KIND = {k[0]: k for k in KINDS}
DOMAINS = {"cash": "Cash", "receivables": "Receivables and billing", "payables": "Payables", "procurement": "Procurement",
           "stores": "Stores", "equipment": "Equipment", "cost": "Cost and margin", "commercial": "Commercial",
           "progress": "Progress reporting"}
FINANCE_DOMAINS = ("cash", "receivables", "payables")
STATUSES = [("open", "Open"), ("acknowledged", "Acknowledged"), ("in_progress", "In progress"), ("escalated", "Escalated"),
            ("resolved", "Resolved"), ("dismissed", "Dismissed"), ("cleared", "Cleared (condition gone)")]
STATUS_LABEL = dict(STATUSES)
LIVE = ("open", "acknowledged", "in_progress", "escalated")
SEV_RANK = {"high": 0, "medium": 1, "low": 2}

# the section 20 order of management actions
ACTIONS = {
    "cash_reserve": "Collect certified receivables first, then bring forward measurement and IPC submission; review the timing of "
                    "uncommitted purchases; only then compare financing options (Funding gap & financing).",
    "cash_negative": "As for the reserve: collections, measurement and IPCs, purchase timing, then financing options. Agree the plan "
                     "at the finance meeting; nothing is borrowed automatically.",
    "obligations_due": "Make sure the payment is in a payment request and the money is in the right bank account before the due date. "
                       "Statutory and payroll payments are never deferred automatically.",
    "receipt_overdue": "Call the client, record the promise in Collection actions, and escalate in writing if the contract allows.",
    "ipc_waiting": "Submit the prepared IPC, or follow up the engineer for certification and record the reason for any delay.",
    "unbilled_work": "Include the measured quantities in the next IPC.",
    "payables_due": "Raise payment requests in priority order, or agree new dates with the supplier before the due date.",
    "po_over_budget": "Hold approval until the budget is changed (Control budget change) or the order is reduced.",
    "material_shortage": "Expedite the open order or raise a purchase request; consider a transfer from another store.",
    "excess_stock": "Transfer the stock to a site that needs it, return it to the supplier, or review it for net realisable value.",
    "idle_equipment": "Return idle hired machines, move owned machines to where they are needed, or fix recurring breakdowns.",
    "cost_overrun": "Review the cost codes over budget with the project team and update the forecast; raise a budget change if needed.",
    "margin_fade": "Review the forecast with the project team at the next monthly close; check unbilled work and claims.",
    "variation_unapproved": "Prepare the variation documents and get the engineer's approval before more work is done on it.",
    "forecast_deviation": "Find the receipts or payments that moved and correct the dates the forecast uses.",
    "dpr_delay": "Ask the site to submit the missing DPRs, or check and approve the waiting ones.",
}

# rights: one new row, 'alerts'. Existing rights decide what each alert is about.
ALERT_RIGHTS = {
    "director": ["view", "approve", "export"], "finance_manager": ["view", "edit", "approve", "export"],
    "accountant": ["view", "edit", "export"], "project_accountant": ["view", "edit"],
    "project_manager": ["view", "edit", "approve", "export"], "quantity_surveyor": ["view", "edit"],
    "procurement_officer": ["view", "edit"], "storekeeper": ["view", "edit"], "equipment_manager": ["view", "edit"],
    "site_engineer": ["view", "edit"], "site_supervisor": ["view"], "viewer": ["view"]}
REPORT_RIGHTS = {
    "director": ["view", "create", "export"], "finance_manager": ["view", "create", "approve", "export"],
    "accountant": ["view", "create", "export"], "project_accountant": ["view", "create", "export"],
    "project_manager": ["view", "create", "export"], "quantity_surveyor": ["view", "create", "export"],
    "procurement_officer": ["view", "create", "export"], "storekeeper": ["view", "export"],
    "equipment_manager": ["view", "create", "export"], "site_engineer": ["view", "create", "export"],
    "site_supervisor": ["view"], "viewer": ["view"]}
NEW_MODULES = ("alerts", "reports")


# ───────────────────────────── start-up ─────────────────────────────
def init_fcc(c):
    c.executescript(SCHEMA)
    for k, v in DEFAULTS.items():
        if q1(c, "SELECT key FROM settings WHERE key=?", (k,)) is None:
            c.execute("INSERT INTO settings(key, value) VALUES(?,?)", (k, v))
    for k in KINDS:
        if not q1(c, "SELECT kind FROM fcc_rules WHERE kind=?", (k[0],)):
            c.execute("INSERT INTO fcc_rules(kind, enabled, threshold, owner_role, target_days, escalate_days) VALUES(?,?,?,?,?,?)",
                      (k[0], 1, k[4], k[6], k[7], k[8]))
    for m in NEW_MODULES:
        if m not in core.MODULES:
            core.MODULES.append(m)
    _seed_rights(c)
    _seed_reports(c)


def _seed_rights(c):
    if setting(c, "fcc_rights_seeded") == "1":
        return
    try:
        have = {r[1] for r in c.execute("PRAGMA table_info(ws_roles)")}
    except Exception:
        have = set()
    if not have:
        return
    for key in set(ALERT_RIGHTS) | set(REPORT_RIGHTS):
        r = q1(c, "SELECT id, perms FROM ws_roles WHERE key=? AND builtin=1", (key,))
        if not r:
            continue
        try:
            p = json.loads(r["perms"] or "{}")
        except ValueError:
            p = {}
        if "alerts" not in p and key in ALERT_RIGHTS:
            p["alerts"] = ALERT_RIGHTS[key]
        if "reports" not in p and key in REPORT_RIGHTS:
            p["reports"] = REPORT_RIGHTS[key]
        c.execute("UPDATE ws_roles SET perms=? WHERE id=?", (json.dumps(p), r["id"]))
    c.execute("INSERT OR REPLACE INTO settings(key, value) VALUES('fcc_rights_seeded','1')")
    try:
        import api_workspace as W
        W.load_roles(c)
    except Exception:
        pass


# ───────────────────────────── helpers ─────────────────────────────
def _f(v, d=0.0):
    try:
        return float(v) if v not in (None, "") else d
    except (TypeError, ValueError):
        return d


def _int(v):
    try:
        return int(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _d(s):
    try:
        return date.fromisoformat(str(s)[:10]) if s else None
    except ValueError:
        return None


def _add(s, n):
    d = _d(s)
    return (d + timedelta(days=int(n))).isoformat() if d else None


def _days(a, b):
    da, db = _d(a), _d(b)
    return (db - da).days if da and db else None


def _m(x):
    return "{:,.2f}".format(x or 0)


def _has(c, table):
    return bool(val(c, "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?", (table,)))


def _roles(c):
    try:
        import api_workspace as W
        return W.roles(c)
    except Exception:
        return {}


def right(c, u, module, action):
    """The 2.29 rows ('alerts', 'reports') are read literally when the role has them; a role without them follows
    the rights it already had: anyone may see alerts and run reports on what their other rights show, approvers of
    accounts or cost control manage alerts, and editors save reports."""
    if not u:
        return False
    if u.get("role") == "admin" or u.get("system"):
        return True
    t = _roles(c).get(u.get("role"))
    if t is not None and module in (t.get("perms") or {}):
        return action in set(t["perms"].get(module) or ())
    if module in ("alerts", "reports"):
        if action in ("view", "export"):
            return True
        if action in ("edit", "create"):
            return any(core.can(u, m, "edit") for m in ("accounts", "project", "commercial", "procurement", "inventory", "equipment"))
        if action == "approve":
            return core.can(u, "accounts", "approve") or _cl_allowed(c, u, "approve")
        return False
    return core.can(u, module, {"create": "edit", "submit": "edit", "post": "approve", "export": "view"}.get(action, action))


def _cl_allowed(c, u, action):
    try:
        import api_costlink as CL
        return CL.allowed(c, u, action)
    except Exception:
        return bool(u and u.get("role") == "admin")


def need(c, u, module, action, what):
    if not right(c, u, module, action):
        raise ApiError("Your role cannot %s (needs '%s' on %s in Administration > Users and roles)." % (what, action, module))


def allowed_projects(c, u):
    try:
        import api_workspace as W
        return W.allowed_projects(c, u) if u else set()
    except Exception:
        return None


def all_projects(c, u):
    return u.get("system") or u.get("role") == "admin" or allowed_projects(c, u) is None


def check_project(c, u, pid):
    al = allowed_projects(c, u)
    if pid and al is not None and int(pid) not in al:
        raise ApiError("PROJECT_DENIED: you are not assigned to this project.")


def domain_ok(c, u, domain):
    """May this person see this kind of figure at all (project assignment is checked separately)."""
    if u.get("role") == "admin" or u.get("system"):
        return True
    if domain == "cash":
        return core.can(u, "accounts", "view") and all_projects(c, u)
    if domain == "payables":
        return core.can(u, "accounts", "view") or right_fc(c, u, "payreq", "view")
    if domain == "receivables":
        return core.can(u, "accounts", "view") or core.can(u, "commercial", "view")
    if domain == "procurement":
        return core.can(u, "procurement", "view")
    if domain == "stores":
        return core.can(u, "inventory", "view")
    if domain == "equipment":
        return core.can(u, "equipment", "view")
    if domain == "cost":
        return _cl_allowed(c, u, "view")
    if domain == "commercial":
        return core.can(u, "commercial", "view")
    if domain == "progress":
        return core.can(u, "project", "view")
    return False


def right_fc(c, u, module, action):
    try:
        import api_fc as FC
        return FC.right(c, u, module, action)
    except Exception:
        return False


def can_see_alert(c, u, a):
    if not right(c, u, "alerts", "view"):
        return False
    if a.get("owner_id") and u.get("id") == a["owner_id"]:
        return True
    if not domain_ok(c, u, a["domain"]):
        return False
    if a.get("project_id"):
        al = allowed_projects(c, u)
        return al is None or a["project_id"] in al
    return all_projects(c, u)


def user_row(c, uid):
    r = q1(c, "SELECT * FROM users WHERE id=?", (uid,)) if uid else None
    return dict(r) if r else None


def uname(c, uid):
    return val(c, "SELECT name FROM users WHERE id=?", (uid,), None) if uid else None


def _projects(c):
    return {p["id"]: p for p in q(c, "SELECT * FROM projects")}


def _pcode(projs, pid):
    return (projs.get(pid) or {}).get("code") or "Company"


def _active_projects(c):
    return q(c, "SELECT * FROM projects WHERE status='active' AND COALESCE(kind,'') NOT IN ('trading','general') ORDER BY code")


def F(c, name, a, u=None):
    """Call another engine function on the same connection."""
    return inv.FUNCS[name][0](c, u or SYS, a)


def rules(c):
    out = {}
    for k in KINDS:
        r = q1(c, "SELECT * FROM fcc_rules WHERE kind=?", (k[0],)) or {}
        out[k[0]] = {"kind": k[0], "label": k[1], "domain": k[2], "severity": k[3], "threshold_label": k[5],
                     "enabled": bool(r.get("enabled", 1)), "threshold": _f(r.get("threshold"), k[4]),
                     "owner_role": r.get("owner_role") or k[6], "target_days": int(_f(r.get("target_days"), k[7])),
                     "escalate_days": int(_f(r.get("escalate_days"), k[8]))}
    return out


def src(kind, no, route, id_=None, project_id=None, label=None):
    return {"type": kind, "id": id_, "no": no, "route": route, "project_id": project_id, "label": label}


# ───────────────────────────── the fifteen checks ─────────────────────────────
def chk_cash(c, R, ctx):
    """Forecast cash below the reserve (available to spend < 0) and below zero, from the 13-week forecast."""
    out = []
    fc = ctx.get("forecast")
    if fc is None:
        return out
    for kind, field in (("cash_reserve", "available"), ("cash_negative", "closing")):
        rule = R[kind]
        weeks = [w for w in fc["weeks"] if w["week"] <= max(1, int(rule["threshold"] or 13))]
        bad = [w for w in weeks if w[field] < -0.5]
        if not bad:
            continue
        first = bad[0]
        worst = min(bad, key=lambda w: w[field])
        if kind == "cash_reserve":
            title = "Cash available to spend goes below zero in week %d (%s)" % (first["week"], first["start"])
            basis = ("13-week forecast, as expected: closing cash less the reserve %s and restricted funds. Lowest available %s in week %d. "
                     "%d of %d weeks short." % (_m(fc["reserve"]), _m(worst["available"]), worst["week"], len(bad), len(weeks)))
        else:
            title = "Projected cash goes below zero in week %d (%s)" % (first["week"], first["start"])
            basis = "13-week forecast, as expected: lowest closing %s in week %d; %d week(s) below zero." % (
                _m(worst["closing"]), worst["week"], len(bad))
        out.append({"fkey": kind, "kind": kind, "project_id": None, "title": title, "amount": r2(-worst[field]),
                    "due_date": first["start"], "severity": "high", "basis": basis,
                    "detail": "Shortfall of %s at the worst point (week %d, %s)." % (_m(-worst[field]), worst["week"], worst["start"]),
                    "sources": [src("forecast", "13-week cash forecast", "#/acc/cash?tab=3")]})
    return out


def chk_obligations(c, R, ctx):
    out = []
    rule = R["obligations_due"]
    t = ctx["today"]
    lim = _add(t, rule["threshold"])
    projs = ctx["projects"]
    for r in ctx["payables"]["rows"]:
        if r["category"] not in ("payroll", "statutory", "loan") or not r["due_date"] or r["due_date"] > lim:
            continue
        if r["amount"] <= 0.5:
            continue
        od = r["days_to_due"] is not None and r["days_to_due"] < 0
        what = "Wages of site workers" if r["category"] == "payroll" else (r["ref_no"] or ("Tax" if r["category"] == "statutory" else "Instalment"))
        title = "%s %s %s" % (what, "overdue since" if od else "due on", r["due_date"])
        if r["project_id"]:
            title += " (%s)" % _pcode(projs, r["project_id"])
        req = r.get("requested") or 0
        out.append({"fkey": "obl:%s" % r["key"], "kind": "obligations_due", "project_id": r["project_id"], "title": title.replace("  ", " "),
                    "amount": r2(r["amount"]), "due_date": r["due_date"],
                    "severity": "high" if od or (r["days_to_due"] or 0) <= 3 else "medium",
                    "basis": "Payables register: %s due %s; %s already in payment requests, %s not yet requested." % (
                        _m(r["amount"]), r["due_date"], _m(req), _m(r["unrequested"])),
                    "detail": r.get("note") or "", "sources": [src("payables", r["ref_no"] or r["key"], "#/acc/ageing?tab=3", r.get("ref_id"),
                                                                 r["project_id"])]})
    return out


def chk_receipts(c, R, ctx):
    out = []
    rule = R["receipt_overdue"]
    for p in ctx["receivables"]["rows"]:
        for i in p["invoices"]:
            if i["days_overdue"] < max(1, rule["threshold"]):
                continue
            ipc = q1(c, "SELECT id, no FROM ipc WHERE invoice_id=?", (i["id"],))
            pr = q1(c, "SELECT * FROM fc_follow WHERE ref_type IN ('ipc','invoice') AND ref_id IN (?,?) ORDER BY id DESC LIMIT 1",
                    (ipc["id"] if ipc else -1, i["id"])) if _has(c, "fc_follow") else None
            promise = " Client promised %s on %s." % (_m(pr["promised_amount"]), pr["promised_date"]) if pr and pr.get("promised_date") else ""
            out.append({"fkey": "rcv:%d" % i["id"], "kind": "receipt_overdue", "project_id": p["project_id"],
                        "title": "%s %s overdue %d days (%s)" % (ipc["no"] if ipc else i["no"], _m(i["balance"]), i["days_overdue"], p["code"]),
                        "amount": i["balance"], "due_date": i["due_date"],
                        "severity": "high" if i["days_overdue"] > 60 else "medium",
                        "basis": "Invoice %s due %s, balance %s after receipts.%s" % (i["no"], i["due_date"] or i["date"], _m(i["balance"]), promise),
                        "detail": "Certified and invoiced, not yet paid in full.",
                        "sources": [src("invoice", i["no"], "#/acc/ageing?tab=1", i["id"], p["project_id"])] +
                                   ([src("ipc", ipc["no"], "#/p/ipc?tab=1", ipc["id"], p["project_id"])] if ipc else [])})
    return out


def chk_ipcs(c, R, ctx):
    import api_fc as FC
    out = []
    rule, rule_u = R["ipc_waiting"], R["unbilled_work"]
    t = ctx["today"]
    for p in ctx["active"]:
        for i in q(c, "SELECT * FROM ipc WHERE project_id=? AND status IN ('draft','submitted')", (p["id"],)):
            s = FC.ipc_state(c, i, t=t)
            if i["status"] == "draft" and (s["days_in_stage"] or 0) >= rule["threshold"]:
                out.append({"fkey": "ipc:%d" % i["id"], "kind": "ipc_waiting", "project_id": p["id"],
                            "title": "%s prepared %d days ago, not submitted (%s)" % (i["no"], s["days_in_stage"], p["code"]),
                            "amount": s["claimed_net"], "due_date": None, "severity": "medium",
                            "basis": "IPC in draft for %d days (limit %d); net claim %s." % (s["days_in_stage"], rule["threshold"], _m(s["claimed_net"])),
                            "detail": "", "sources": [src("ipc", i["no"], "#/p/ipc?tab=1", i["id"], p["id"])]})
            elif i["status"] == "submitted" and s["cert_overdue_days"] > 0:
                out.append({"fkey": "ipc:%d" % i["id"], "kind": "ipc_waiting", "project_id": p["id"],
                            "title": "%s certification %d days late (%s)" % (i["no"], s["cert_overdue_days"], p["code"]),
                            "amount": s["claimed_net"], "due_date": s["cert_due"],
                            "severity": "high" if s["cert_overdue_days"] > 30 else "medium",
                            "basis": "Submitted IPC; certification was due %s under the project terms; net claim %s." % (s["cert_due"], _m(s["claimed_net"])),
                            "detail": s.get("delay_reason") or "", "sources": [src("ipc", i["no"], "#/p/ipc?tab=1", i["id"], p["id"])]})
        ub = FC.unbilled(c, p["id"])
        if ub["unbilled"] >= max(0.5, rule_u["threshold"]):
            out.append({"fkey": "unb:%d" % p["id"], "kind": "unbilled_work", "project_id": p["id"],
                        "title": "Measured work of %s not yet in an IPC (%s)" % (_m(ub["unbilled"]), p["code"]),
                        "amount": ub["unbilled"], "due_date": None, "severity": "medium",
                        "basis": "Verified measurements less quantities in submitted or certified IPCs, at the current rates, on %d BOQ item(s)." %
                                 len([r for r in ub["rows"] if r["unbilled_value"] > 0.5]),
                        "detail": "An estimate for planning. Only a certified IPC is billing.",
                        "sources": [src("boq", r["code"], "#/p/ipc?tab=1", r["boq_item_id"], p["id"]) for r in ub["rows"] if r["unbilled_value"] > 0.5][:20]})
    return out


def chk_payables(c, R, ctx):
    out = []
    rule = R["payables_due"]
    lim = _add(ctx["today"], rule["threshold"])
    groups = {}
    for r in ctx["payables"]["rows"]:
        if r["category"] not in ("supplier", "subcontractor", "equipment") or not r["due_date"] or r["due_date"] > lim:
            continue
        if r["unrequested"] <= 0.5:
            continue
        g = groups.setdefault((r["project_id"], r["category"]), [])
        g.append(r)
    names = {"supplier": "supplier", "subcontractor": "subcontractor", "equipment": "equipment hire"}
    for (pid, cat), rows in groups.items():
        amt = r2(sum(r["unrequested"] for r in rows))
        od = [r for r in rows if (r["days_to_due"] or 0) < 0]
        out.append({"fkey": "pay:%s:%s" % (pid or 0, cat), "kind": "payables_due", "project_id": pid,
                    "title": "%d %s bill(s) of %s due by %s%s (%s)" % (len(rows), names[cat], _m(amt), lim,
                                                                       ", %d overdue" % len(od) if od else "", _pcode(ctx["projects"], pid)),
                    "amount": amt, "due_date": min(r["due_date"] for r in rows), "severity": "high" if od else "medium",
                    "basis": "Payables register: bills due within %d days with no payment request for %s." % (rule["threshold"], _m(amt)),
                    "detail": ", ".join("%s %s" % (r["ref_no"] or "", r["party_name"] or "") for r in rows[:6]),
                    "sources": [src("purchase_bill", r["ref_no"], "#/acc/ageing?tab=3", r.get("ref_id"), pid) for r in rows[:20]]})
    return out


def chk_po_budget(c, R, ctx):
    out = []
    for p in ctx["pending_pos"]:
        left = p.get("budget_left_after")
        if left is None or left >= -0.5:
            continue
        out.append({"fkey": "po:%d" % p["id"], "kind": "po_over_budget", "project_id": p["project_id"],
                    "title": "%s takes %s over its budget by %s" % (p["no"], _pcode(ctx["projects"], p["project_id"]), _m(-left)),
                    "amount": r2(-left), "due_date": p.get("delivery_date"), "severity": "high",
                    "basis": "Purchase order check (2.28): budget left after this order %s." % _m(left),
                    "detail": p.get("warning_text") or "", "sources": [src("po", p["no"], "#/proc/po?tab=1", p["id"], p["project_id"])]})
    return out


def chk_shortage(c, R, ctx):
    out = []
    try:
        import api_res as RES
    except Exception:
        return out
    for p in ctx["active"]:
        try:
            risks = RES.material_risks(c, p["id"]) or []
        except Exception:
            continue
        for r in risks:
            if not r.get("risk"):
                continue
            daily = r.get("avg_daily") or 0
            short_qty = max(0.0, daily * (r.get("lead_days") or 0) - (r.get("available") or 0) - (r.get("pending_po") or 0))
            val_ = r2(short_qty * (r.get("last_rate") or 0)) if r.get("last_rate") else None
            runs = _add(ctx["today"], int(r["days_left"])) if r.get("days_left") is not None else ctx["today"]
            out.append({"fkey": "short:%d:%d" % (p["id"], r["material_id"]), "kind": "material_shortage", "project_id": p["id"],
                        "title": "%s %s may run short around %s (%s)" % (r["code"], r["name"], runs, p["code"]),
                        "amount": val_, "due_date": runs, "severity": "high" if (r.get("days_left") or 0) <= 7 else "medium",
                        "basis": r.get("why") or "", "detail": "Scheduled use from the activities and material coefficients.",
                        "sources": [src("material", r["code"], "#/inv/risk", r["material_id"], p["id"])]})
    return out


def chk_excess(c, R, ctx):
    out = []
    rule = R["excess_stock"]
    try:
        d = F(c, "books.slow", {})
    except Exception:
        return out
    by = {}
    for r in d["rows"]:
        by.setdefault(r["project_id"], []).append(r)
    for pid, rows in by.items():
        v = r2(sum(r["value"] for r in rows))
        if v < max(0.5, rule["threshold"]):
            continue
        out.append({"fkey": "excess:%s" % (pid or 0), "kind": "excess_stock", "project_id": pid,
                    "title": "Stock of %s not moved for 90 days or more (%s)" % (_m(v), _pcode(ctx["projects"], pid)),
                    "amount": v, "due_date": None, "severity": "medium" if v >= 5 * rule["threshold"] else "low",
                    "basis": "Store balances with no issue or receipt for 90+ days, at stock value, %d item(s)." % len(rows),
                    "detail": "; ".join("%s %s %s" % (r["code"], r["qty"], r["unit"]) + (" (%s)" % r["transfer_to"] if r["transfer_to"] else "")
                                        for r in rows[:6]),
                    "sources": [src("material", r["code"], "#/inv/stock", r["material_id"], pid) for r in rows[:20]]})
    return out


def chk_equipment(c, R, ctx):
    out = []
    to = ctx["today"]
    frm = _add(to, -29)
    import api_ctc as CT
    for p in ctx["active"]:
        try:
            res = CT.resources(c, p["id"], frm, to)
        except Exception:
            continue
        for e in res["equipment"]:
            fl = [f for f in e["flags"] if f in ("idle_hire", "low_utilisation", "recurring_breakdown")]
            if not fl:
                continue
            words = {"idle_hire": "hired and idle", "low_utilisation": "used %s%% of its time" % e["utilisation"],
                     "recurring_breakdown": "broken down on %s days" % e["breakdown_days"]}
            out.append({"fkey": "eq:%d:%d" % (p["id"], e["equipment_id"]), "kind": "idle_equipment", "project_id": p["id"],
                        "title": "%s %s: %s (%s)" % (e["code"], e["name"], ", ".join(words[f] for f in fl), p["code"]),
                        "amount": e["rent"] if "idle_hire" in fl else None, "due_date": None,
                        "severity": "medium" if "idle_hire" in fl or "recurring_breakdown" in fl else "low",
                        "basis": "DPR machine lines %s to %s: %s h working, %s h idle, %s h breakdown, utilisation %s%%; hire billed %s." % (
                            frm, to, e["working"], e["idle"], e["breakdown"], e["utilisation"], _m(e["rent"])),
                        "detail": "", "sources": [src("equipment", e["code"], "#/cl/cvr?tab=2", e["equipment_id"], p["id"])]})
    return out


def chk_cost(c, R, ctx):
    out = []
    for p, d in ctx["ctc"].items():
        if d is None:
            continue
        proj = ctx["projects"][p]
        for al in d["alerts"]:
            if al["key"] == "cost_overrun":
                T = d["total"]
                out.append({"fkey": "over:%d" % p, "kind": "cost_overrun", "project_id": p, "title": "%s: %s" % (proj["code"], al["text"]),
                            "amount": r2(T["eac"] - (T["budget_current"] or 0)), "due_date": None, "severity": "high",
                            "basis": "Cost to complete (2.28): final cost = cost to date + the larger of cost to complete and open orders, "
                                     "against the current control budget. Codes over budget: %s." % (", ".join(al["items"][:12]) or "none listed"),
                            "detail": "", "sources": [src("cvr", proj["code"], "#/cl/cvr?tab=1", None, p)]})
            elif al["key"] in ("margin_fade", "net_loss", "gross_loss"):
                out.append({"fkey": "margin:%d" % p, "kind": "margin_fade", "project_id": p, "title": "%s: %s" % (proj["code"], al["text"]),
                            "amount": r2(-d["net"]) if al["key"] == "net_loss" and d.get("net") is not None else None, "due_date": None,
                            "severity": "high", "basis": "Cost to complete and profit after overhead and financing (2.28); margin against "
                                                         "the last locked monthly close (2.24).",
                            "detail": "", "sources": [src("cvr", proj["code"], "#/cl/cvr?tab=1", None, p)]})
    # one margin alert per project: the first found wins
    seen, res = set(), []
    for x in out:
        if x["fkey"] in seen:
            continue
        seen.add(x["fkey"])
        res.append(x)
    return res


def chk_variations(c, R, ctx):
    out = []
    rule = R["variation_unapproved"]
    if not _has(c, "variations"):
        return out
    t = ctx["today"]
    for v in q(c, "SELECT * FROM variations WHERE COALESCE(status,'identified') NOT IN ('approved','rejected','cancelled','closed')"):
        if v["project_id"] not in ctx["active_ids"]:
            continue
        age = _days(v["date"], t) or 0
        if age < rule["threshold"]:
            continue
        amt = v["est_value"]
        if amt is None and v["var_qty"] is not None:
            rate = v["new_rate"] if v["new_rate"] is not None else val(c, "SELECT COALESCE(revised_rate, rate) FROM boq_items WHERE id=?",
                                                                    (v["boq_item_id"],), None)
            amt = r2((v["var_qty"] or 0) * (rate or 0)) if rate is not None else None
        out.append({"fkey": "vo:%d" % v["id"], "kind": "variation_unapproved", "project_id": v["project_id"],
                    "title": "%s %s pending %d days (%s)" % (v["no"], v["title"] or "", age, _pcode(ctx["projects"], v["project_id"])),
                    "amount": amt, "due_date": None, "severity": "high" if age > 2 * rule["threshold"] else "medium",
                    "basis": "Variation status '%s' since %s; not counted as revenue until approved." % (v["status"] or "identified", v["date"]),
                    "detail": v["reason"] or "", "sources": [src("variation", v["no"], "#/p/variations", v["id"], v["project_id"])]})
    for p, ch in ctx["chain"].items():
        if ch is None:
            continue
        for r in ch["rows"]:
            if "beyond_scope" in r["flags"] and r["beyond_qty"] > 0:
                out.append({"fkey": "scope:%d:%d" % (p, r["boq_item_id"]), "kind": "variation_unapproved", "project_id": p,
                            "title": "%s reported %s %s beyond the approved quantity (%s)" % (r["code"], r["beyond_qty"], r["unit"] or "",
                                                                                           ctx["projects"][p]["code"]),
                            "amount": r2(r["beyond_qty"] * (r["rate"] or 0)), "due_date": None, "severity": "medium",
                            "basis": "Progress to cash (2.28): reported %s against approved scope %s." % (r["reported"], r["scope"]),
                            "detail": "Work beyond the contract quantity needs an approved variation before it can be billed.",
                            "sources": [src("boq", r["code"], "#/p/dpr", r["boq_item_id"], p)]})
    return out


def chk_fva(c, R, ctx):
    out = []
    rule = R["forecast_deviation"]
    snap = q1(c, "SELECT id, label, week0 FROM cfw_snapshots ORDER BY id DESC LIMIT 1") if _has(c, "cfw_snapshots") else None
    if not snap:
        return out
    try:
        d = F(c, "cfw.snapshot_compare", {"id": snap["id"]})
    except Exception:
        return out
    for w in d["weeks"]:
        if not w.get("complete"):
            continue
        for side, f_, a_ in (("in", "f_in", "a_in"), ("out", "f_out", "a_out")):
            fv, av = w[f_], w[a_]
            base = max(abs(fv), 1.0)
            dev = 100 * abs(av - fv) / base
            if dev < rule["threshold"] or abs(av - fv) < 1000:
                continue
            out.append({"fkey": "fva:%d:%d:%s" % (snap["id"], w["week"], side), "kind": "forecast_deviation", "project_id": None,
                        "title": "Week %d (%s): actual money %s %s against %s forecast" % (w["week"], w["start"], side, _m(av), _m(fv)),
                        "amount": r2(av - fv), "due_date": None, "severity": "medium",
                        "basis": "Saved forecast '%s' against cash and bank vouchers; difference %.0f%% (limit %s%%)." % (
                            snap["label"] or snap["id"], dev, rule["threshold"]),
                        "detail": "", "sources": [src("forecast", "Forecast vs actual", "#/acc/cash?tab=3", snap["id"])]})
    return out


def chk_dpr(c, R, ctx):
    out = []
    rule = R["dpr_delay"]
    t = ctx["today"]
    for p in ctx["active"]:
        running = val(c, "SELECT COUNT(*) FROM activities WHERE project_id=? AND actual_start IS NOT NULL AND actual_start<=? AND "
                         "(actual_finish IS NULL OR actual_finish='')", (p["id"], t))
        last = val(c, "SELECT MAX(date) FROM dpr WHERE project_id=? AND status<>'rejected'", (p["id"],), None)
        gap = _days(last, t) if last else None
        if running and (gap is None or gap > rule["threshold"]):
            out.append({"fkey": "dprgap:%d" % p["id"], "kind": "dpr_delay", "project_id": p["id"],
                        "title": "No DPR for %s days on %s" % (gap if gap is not None else "any", p["code"]),
                        "amount": None, "due_date": None, "severity": "high" if gap is None or gap > 3 * rule["threshold"] else "medium",
                        "basis": "%d activities in progress; last DPR %s (limit %d days). Progress, labour cost and billing are not visible "
                                 "without DPRs." % (running, last or "never", rule["threshold"]),
                        "detail": "", "sources": [src("dpr", "Daily progress", "#/p/dpr", None, p["id"])]})
        waiting = q(c, "SELECT id, no, date, status FROM dpr WHERE project_id=? AND status IN ('submitted','checked') AND date<=? ORDER BY date",
                    (p["id"], _add(t, -rule["threshold"])))
        if waiting:
            out.append({"fkey": "dprwait:%d" % p["id"], "kind": "dpr_delay", "project_id": p["id"],
                        "title": "%d DPR(s) waiting for approval since %s (%s)" % (len(waiting), waiting[0]["date"], p["code"]),
                        "amount": None, "due_date": None, "severity": "medium",
                        "basis": "Submitted or checked DPRs older than %d days; their labour and machine costs are not posted until approval." % rule["threshold"],
                        "detail": ", ".join(w["no"] or str(w["id"]) for w in waiting[:10]),
                        "sources": [src("dpr", w["no"], "#/p/dpr", w["id"], p["id"]) for w in waiting[:20]]})
    return out


CHECKS = [("cash_reserve", chk_cash), ("obligations_due", chk_obligations), ("receipt_overdue", chk_receipts),
          ("ipc_waiting", chk_ipcs), ("payables_due", chk_payables), ("po_over_budget", chk_po_budget),
          ("material_shortage", chk_shortage), ("excess_stock", chk_excess), ("idle_equipment", chk_equipment),
          ("cost_overrun", chk_cost), ("variation_unapproved", chk_variations), ("forecast_deviation", chk_fva),
          ("dpr_delay", chk_dpr)]


def context(c, need_=None):
    """Everything the checks read, built once per scan as the system (company-wide, all projects)."""
    import api_ctc as CT
    t = today()
    projs = _projects(c)
    act = _active_projects(c)
    ctx = {"today": t, "projects": projs, "active": act, "active_ids": {p["id"] for p in act}, "errors": []}

    def safe(key, fn):
        try:
            ctx[key] = fn()
        except Exception as e:  # one failing source never stops the other checks
            ctx[key] = None
            ctx["errors"].append("%s: %s" % (key, str(e)[:160]))

    safe("forecast", lambda: F(c, "cfw.forecast", {"compare": False}))
    safe("payables", lambda: F(c, "fc.payables", {}))
    safe("receivables", lambda: F(c, "fc.receivables", {}))
    safe("pending_pos", lambda: F(c, "ctc.pending_pos", {}))
    ctx["payables"] = ctx["payables"] or {"rows": []}
    ctx["receivables"] = ctx["receivables"] or {"rows": []}
    ctx["pending_pos"] = ctx["pending_pos"] or []
    ctx["ctc"], ctx["chain"] = {}, {}
    for p in act:
        try:
            ctx["ctc"][p["id"]] = CT.project_ctc(c, p["id"], t)
        except Exception as e:
            ctx["ctc"][p["id"]] = None
            ctx["errors"].append("cost to complete %s: %s" % (p["code"], str(e)[:120]))
        try:
            ctx["chain"][p["id"]] = CT.chain(c, p["id"], t)
        except Exception as e:
            ctx["chain"][p["id"]] = None
            ctx["errors"].append("progress to cash %s: %s" % (p["code"], str(e)[:120]))
    return ctx


# which context sources and kinds each check depends on: a failed source never clears alerts it could not check
CHECK_KINDS = {"cash_reserve": ("cash_reserve", "cash_negative"), "ipc_waiting": ("ipc_waiting", "unbilled_work"),
               "cost_overrun": ("cost_overrun", "margin_fade")}
CHECK_SOURCES = {"cash_reserve": "forecast", "obligations_due": "payables", "payables_due": "payables",
                 "receipt_overdue": "receivables", "po_over_budget": "pending_pos"}


def _log(c, aid, u, action, frm=None, to=None, note=None, data=None):
    ins(c, "fcc_alert_log", {"alert_id": aid, "ts": now(), "user_id": (u or {}).get("id"),
                             "user_name": (u or {}).get("name") or ("BuildCore check" if (u or {}).get("system") else None),
                             "action": action, "from_status": frm, "to_status": to, "note": note,
                             "data": json.dumps(data, default=str) if data is not None else None})


def _notify(c, uids, a, text, by=None):
    try:
        import api_cadmin as CA
        CA.notify(c, [x for x in uids if x], "alert", text, "#/action?tab=1&alert=%d" % a["id"], a.get("project_id"), by)
    except Exception:
        pass


def _users_with_role(c, role):
    return [dict(r) for r in q(c, "SELECT * FROM users WHERE active=1 AND role=? ORDER BY id", (role,))]


def default_owner(c, rule, a):
    for role in [x.strip() for x in (rule["owner_role"] or "").split(",") if x.strip()]:
        for usr in _users_with_role(c, role):
            if can_see_alert(c, usr, dict(a, owner_id=None)):
                return usr["id"]
    return None


def chain_roles(c, domain):
    k = "fcc_escalation_finance" if domain in FINANCE_DOMAINS else "fcc_escalation_project"
    return [x.strip() for x in (setting(c, k) or DEFAULTS[k]).split(",") if x.strip()]


def escalate(c, a, u, note=None, manual=False):
    """Move one level up the escalation chain: the users of that role who may see the alert are told."""
    roles = chain_roles(c, a["domain"])
    owner_role = (user_row(c, a["owner_id"]) or {}).get("role")
    lvl = a["escalation_level"] or 0
    targets, role = [], None
    while lvl < len(roles):
        role = roles[lvl]
        lvl += 1
        if role == owner_role and lvl < len(roles):
            continue
        targets = [x for x in _users_with_role(c, role) if x["id"] != a["owner_id"] and can_see_alert(c, x, dict(a, owner_id=None))]
        if targets:
            break
    if not targets:
        if manual:
            raise ApiError("Nobody further up the escalation chain (%s) can see this alert." % ", ".join(roles))
        return False
    frm = a["status"]
    upd(c, "fcc_alerts", a["id"], {"escalation_level": lvl, "escalated_to": targets[0]["id"], "escalated_at": today(),
                                   "status": "escalated", "updated_at": now()})
    _log(c, a["id"], u, "escalated", frm, "escalated", note or ("Target date %s passed" % a["target_date"] if not manual else None),
         {"level": lvl, "role": role, "to": [x["id"] for x in targets]})
    _notify(c, [x["id"] for x in targets] + [a["owner_id"]], a, "Escalated: " + a["title"], by=(u or {}).get("id"))
    return True


def scan(c, u=None):
    u = u or SYS
    R = rules(c)
    ctx = context(c)
    t = today()
    found, failed = {}, set()
    for key, fn in CHECKS:
        kinds = CHECK_KINDS.get(key, (key,))
        srcname = CHECK_SOURCES.get(key)
        if srcname and ctx.get(srcname) is None:
            failed.update((k, "*") for k in kinds)
        try:
            for x in fn(c, R, ctx):
                if R[x["kind"]]["enabled"]:
                    found[x["fkey"]] = x
        except Exception as e:
            ctx["errors"].append("%s: %s" % (key, str(e)[:160]))
            failed.update((k, "*") for k in kinds)
    for pid, d in ctx["ctc"].items():
        if d is None:
            failed.update({("cost_overrun", pid), ("margin_fade", pid)})
    for pid, d in ctx["chain"].items():
        if d is None:
            failed.add(("variation_unapproved", pid))
    stats = {"raised": 0, "updated": 0, "reopened": 0, "cleared": 0, "escalated": 0}
    fields = ("kind", "project_id", "title", "detail", "amount", "due_date", "severity", "basis")
    for fk, x in found.items():
        k = KIND[x["kind"]]
        row = {f: x.get(f) for f in fields}
        row.update(domain=k[2], sources=json.dumps(x.get("sources") or [], default=str), action=ACTIONS.get(x["kind"]), present=1,
                   last_seen=now(), updated_at=now())
        ex = q1(c, "SELECT * FROM fcc_alerts WHERE fkey=?", (fk,))
        if not ex:
            row.update(fkey=fk, status="open", first_seen=now(), created_at=now(), escalation_level=0)
            rule = R[x["kind"]]
            tgt = _add(t, rule["target_days"])
            if x.get("due_date") and t <= x["due_date"] < tgt:
                tgt = x["due_date"]
            row["target_date"] = tgt
            row["owner_id"] = default_owner(c, rule, row)
            aid = ins(c, "fcc_alerts", row)
            _log(c, aid, u, "raised", None, "open", None, {"amount": x.get("amount"), "owner_id": row["owner_id"], "target_date": tgt})
            _notify(c, [row["owner_id"]], dict(row, id=aid), "New alert: " + row["title"])
            stats["raised"] += 1
            continue
        ex = dict(ex)
        upd(c, "fcc_alerts", ex["id"], row)
        if SEV_RANK.get(row["severity"], 1) < SEV_RANK.get(ex["severity"], 1) and ex["status"] in LIVE:
            _log(c, ex["id"], u, "severity raised", ex["status"], ex["status"], "%s to %s" % (ex["severity"], row["severity"]))
        reopen = None
        if ex["status"] == "cleared":
            reopen = "The condition is back."
        elif ex["status"] in ("resolved", "dismissed") and ex["hold_until"] and t > ex["hold_until"]:
            reopen = "Still present after the %s period ended on %s." % (ex["status"], ex["hold_until"])
        if reopen:
            rule = R[x["kind"]]
            upd(c, "fcc_alerts", ex["id"], {"status": "open", "escalation_level": 0, "escalated_to": None, "escalated_at": None,
                                            "hold_until": None, "closed_at": None, "closed_by": None,
                                            "target_date": _add(t, rule["target_days"])})
            _log(c, ex["id"], u, "reopened", ex["status"], "open", reopen)
            _notify(c, [ex["owner_id"]], ex, "Alert open again: " + row["title"])
            stats["reopened"] += 1
        else:
            stats["updated"] += 1
    # alerts not found this time: cleared, unless their check could not run
    for a in q(c, "SELECT * FROM fcc_alerts WHERE present=1"):
        if a["fkey"] in found:
            continue
        if (a["kind"], "*") in failed or (a["kind"], a["project_id"]) in failed:
            continue
        if a["status"] in LIVE:
            upd(c, "fcc_alerts", a["id"], {"status": "cleared", "present": 0, "closed_at": now(), "closed_by": None, "updated_at": now()})
            _log(c, a["id"], u, "cleared", a["status"], "cleared", "The condition is no longer found.")
            stats["cleared"] += 1
        else:
            upd(c, "fcc_alerts", a["id"], {"present": 0, "updated_at": now()})
            _log(c, a["id"], u, "condition gone", a["status"], a["status"], "The condition is no longer found.")
    # escalation: k x escalate_days past the target date reaches level k
    for a in q(c, "SELECT * FROM fcc_alerts WHERE status IN ('open','acknowledged','in_progress','escalated') AND target_date IS NOT NULL"):
        a = dict(a)
        over = _days(a["target_date"], t) or 0
        step = max(1, R[a["kind"]]["escalate_days"])
        if over >= step * ((a["escalation_level"] or 0) + 1):
            if escalate(c, a, u):
                stats["escalated"] += 1
    c.execute("INSERT OR REPLACE INTO settings(key, value) VALUES('fcc_last_scan', ?)", (now(),))
    stats["errors"] = ctx["errors"]
    stats["at"] = now()
    return stats


# ───────────────────────────── alert endpoints ─────────────────────────────
def _view(c, a, users=None):
    a = dict(a)
    a["sources"] = json.loads(a.get("sources") or "[]")
    a["owner_name"] = uname(c, a["owner_id"])
    a["escalated_to_name"] = uname(c, a["escalated_to"])
    a["status_label"] = STATUS_LABEL.get(a["status"], a["status"])
    a["kind_label"] = KIND[a["kind"]][1] if a["kind"] in KIND else a["kind"]
    a["domain_label"] = DOMAINS.get(a["domain"], a["domain"])
    a["project_code"] = val(c, "SELECT code FROM projects WHERE id=?", (a["project_id"],), None) if a["project_id"] else None
    a["overdue_days"] = max(0, _days(a["target_date"], today()) or 0) if a["target_date"] and a["status"] in LIVE else 0
    return a


def _auto_scan(c):
    last = setting(c, "fcc_last_scan")
    mins = _f(setting(c, "fcc_scan_minutes"), 60)
    if not last:
        return True
    try:
        from datetime import datetime
        lt = datetime.fromisoformat(str(last)[:19].replace("T", " "))
        return (datetime.now() - lt).total_seconds() > mins * 60
    except ValueError:
        return True


def _can_manage(c, u, a):
    return right(c, u, "alerts", "approve") and (u.get("role") == "admin" or u.get("system") or
                                                  (domain_ok(c, u, a["domain"]) and can_see_alert(c, u, dict(a, owner_id=None))))


def _can_act(c, u, a):
    """The owner, someone who manages alerts, or, while nobody owns it, anyone who may act on alerts and sees it."""
    return (a.get("owner_id") == u.get("id") and right(c, u, "alerts", "edit")) or _can_manage(c, u, a) or \
        (not a.get("owner_id") and right(c, u, "alerts", "edit") and can_see_alert(c, u, a))


@api("fcc.scan")
def fcc_scan(c, u, a):
    need(c, u, "alerts", "view", "run the financial checks")
    return scan(c, u)


@api("fcc.alerts")
def fcc_alerts(c, u, a):
    need(c, u, "alerts", "view", "see financial alerts")
    scanned = None
    if a.get("scan") or (a.get("auto_scan", True) and _auto_scan(c)):
        scanned = scan(c, SYS)
    st = a.get("status") or "live"
    sql, args = "SELECT * FROM fcc_alerts WHERE 1=1", []
    if st == "live":
        sql += " AND status IN ('open','acknowledged','in_progress','escalated')"
    elif st == "closed":
        sql += " AND status IN ('resolved','dismissed','cleared')"
    elif st in STATUS_LABEL:
        sql += " AND status=?"
        args.append(st)
    pid = _int(a.get("project_id"))
    if pid:
        check_project(c, u, pid)
        sql += " AND project_id=?"
        args.append(pid)
    if a.get("domain"):
        sql += " AND domain=?"
        args.append(a["domain"])
    if a.get("kind"):
        sql += " AND kind=?"
        args.append(a["kind"])
    if a.get("mine"):
        sql += " AND (owner_id=? OR escalated_to=?)"
        args += [u.get("id"), u.get("id")]
    rows = [r for r in q(c, sql, tuple(args)) if can_see_alert(c, u, dict(r))]
    rows = [_view(c, r) for r in rows]
    rows.sort(key=lambda r: (r["status"] not in LIVE, SEV_RANK.get(r["severity"], 1), r["target_date"] or "9999", -(r["amount"] or 0)))
    lim = min(int(_f(a.get("limit"), 500)), 2000)
    counts = {"high": sum(1 for r in rows if r["status"] in LIVE and r["severity"] == "high"),
              "live": sum(1 for r in rows if r["status"] in LIVE),
              "mine": sum(1 for r in rows if r["status"] in LIVE and u.get("id") in (r["owner_id"], r["escalated_to"])),
              "overdue": sum(1 for r in rows if r["overdue_days"] > 0), "escalated": sum(1 for r in rows if r["status"] == "escalated"),
              "unassigned": sum(1 for r in rows if r["status"] in LIVE and not r["owner_id"])}
    return {"rows": rows[:lim], "total_rows": len(rows), "counts": counts, "last_scan": setting(c, "fcc_last_scan"), "scan": scanned,
            "statuses": STATUSES, "domains": [(k, v) for k, v in DOMAINS.items() if domain_ok(c, u, k)],
            "kinds": [(k[0], k[1]) for k in KINDS],
            "rights": {"manage": right(c, u, "alerts", "approve"), "act": right(c, u, "alerts", "edit"),
                       "export": right(c, u, "alerts", "export")}}


@api("fcc.alert_get")
def fcc_alert_get(c, u, a):
    need(c, u, "alerts", "view", "see financial alerts")
    al = dict(get(c, "fcc_alerts", int(a["id"]), "Alert"))
    if not can_see_alert(c, u, al):
        raise ApiError("PROJECT_DENIED: you cannot see this alert.")
    out = _view(c, al)
    out["log"] = q(c, "SELECT * FROM fcc_alert_log WHERE alert_id=? ORDER BY id", (al["id"],))
    out["can_manage"] = _can_manage(c, u, al)
    out["can_act"] = _can_act(c, u, al)
    if out["can_manage"]:
        out["owners"] = [{"id": x["id"], "name": x["name"], "role": x["role"]} for x in
                         (dict(r) for r in q(c, "SELECT * FROM users WHERE active=1 ORDER BY name"))
                         if can_see_alert(c, x, dict(al, owner_id=None))]
    return out


@api("fcc.alert_act")
def fcc_alert_act(c, u, a):
    al = dict(get(c, "fcc_alerts", int(a["id"]), "Alert"))
    if not can_see_alert(c, u, al):
        raise ApiError("PROJECT_DENIED: you cannot see this alert.")
    act = a.get("action")
    note = (a.get("note") or "").strip() or None
    t = today()
    st = al["status"]
    manage = _can_manage(c, u, al)
    if act == "assign":
        if not manage:
            raise ApiError("Your role cannot assign alerts (needs 'approve' on alerts).")
        oid = _int(a.get("owner_id"))
        tgt = a.get("target_date") or al["target_date"]
        if oid:
            usr = user_row(c, oid)
            if not usr or not usr.get("active"):
                raise ApiError("Choose an active user.")
            if not can_see_alert(c, usr, dict(al, owner_id=None)):
                raise ApiError("%s cannot see this kind of figure or this project, so cannot own the alert." % usr["name"])
        if tgt and not _d(tgt):
            raise ApiError("Target date is not a date.")
        if tgt and tgt < t and tgt != al["target_date"]:
            raise ApiError("The target date cannot be in the past.")
        upd(c, "fcc_alerts", al["id"], {"owner_id": oid, "target_date": tgt, "updated_at": now()})
        _log(c, al["id"], u, "assigned", st, st, note, {"owner_id": oid, "owner": uname(c, oid), "target_date": tgt,
                                                       "was": {"owner_id": al["owner_id"], "target_date": al["target_date"]}})
        _notify(c, [oid], al, "Alert assigned to you: " + al["title"], by=u.get("id"))
    elif act in ("acknowledge", "start", "resolve", "comment"):
        if not _can_act(c, u, al):
            raise ApiError("Only the owner or someone who manages alerts can do this.")
        if act == "comment":
            if not note:
                raise ApiError("Write the comment.")
            _log(c, al["id"], u, "comment", st, st, note)
        else:
            to = {"acknowledge": "acknowledged", "start": "in_progress", "resolve": "resolved"}[act]
            if st not in LIVE:
                raise ApiError("This alert is %s; reopen it first." % STATUS_LABEL.get(st, st).lower())
            if act == "acknowledge" and st not in ("open", "escalated"):
                raise ApiError("Only an open or escalated alert can be acknowledged.")
            d = {"status": to, "updated_at": now()}
            if act == "resolve":
                if not note:
                    raise ApiError("Say how it was resolved.")
                days = int(_f(a.get("hold_days"), 7))
                if days < 1 or days > 30:
                    raise ApiError("Check again after 1 to 30 days.")
                d.update(hold_until=_add(t, days), closed_at=now(), closed_by=u.get("id"), note=note)
            upd(c, "fcc_alerts", al["id"], d)
            _log(c, al["id"], u, act if act != "start" else "work started", st, to, note,
                 {"hold_until": d.get("hold_until")} if act == "resolve" else None)
    elif act == "dismiss":
        if not manage:
            raise ApiError("Your role cannot dismiss alerts (needs 'approve' on alerts).")
        if st not in LIVE:
            raise ApiError("This alert is already closed.")
        if not note:
            raise ApiError("Give the reason for dismissing it.")
        until = a.get("until") or _add(t, 30)
        if not _d(until) or until < t or until > _add(t, 90):
            raise ApiError("Dismiss until a date within the next 90 days.")
        upd(c, "fcc_alerts", al["id"], {"status": "dismissed", "hold_until": until, "closed_at": now(), "closed_by": u.get("id"),
                                        "note": note, "updated_at": now()})
        _log(c, al["id"], u, "dismissed", st, "dismissed", note, {"until": until})
    elif act == "escalate":
        if not (manage or (al["owner_id"] == u.get("id") and right(c, u, "alerts", "edit"))):
            raise ApiError("Only the owner or someone who manages alerts can escalate.")
        if st not in LIVE:
            raise ApiError("This alert is closed.")
        escalate(c, al, u, note, manual=True)
    elif act == "reopen":
        if not manage:
            raise ApiError("Your role cannot reopen alerts (needs 'approve' on alerts).")
        if st in LIVE:
            raise ApiError("This alert is already open.")
        upd(c, "fcc_alerts", al["id"], {"status": "open", "hold_until": None, "closed_at": None, "closed_by": None,
                                        "escalation_level": 0, "escalated_to": None, "escalated_at": None,
                                        "target_date": a.get("target_date") or _add(t, rules(c)[al["kind"]]["target_days"]),
                                        "updated_at": now()})
        _log(c, al["id"], u, "reopened", st, "open", note)
    else:
        raise ApiError("Unknown action.")
    audit(c, u, "alert_" + act, "fcc_alerts", al["id"], {"note": note, "owner_id": a.get("owner_id"), "target_date": a.get("target_date")})
    return fcc_alert_get(c, u, {"id": al["id"]})


@api("fcc.rules")
def fcc_rules(c, u, a):
    need(c, u, "alerts", "view", "see the alert rules")
    return {"rules": list(rules(c).values()), "escalation": {k: setting(c, k) or v for k, v in DEFAULTS.items()},
            "roles": sorted(_roles(c).keys()), "can_edit": right(c, u, "alerts", "approve") and all_projects(c, u)}


@api("fcc.rules_save")
def fcc_rules_save(c, u, a):
    if not (right(c, u, "alerts", "approve") and all_projects(c, u)):
        raise ApiError("Your role cannot change the alert rules (needs 'approve' on alerts and every project).")
    roles = set(_roles(c).keys()) | {"admin"}
    for r in a.get("rules") or []:
        k = r.get("kind")
        if k not in KIND:
            raise ApiError("Unknown alert kind %s." % k)
        thr = _f(r.get("threshold"), KIND[k][4])
        if thr < 0:
            raise ApiError("%s: the threshold cannot be negative." % KIND[k][1])
        td, ed = int(_f(r.get("target_days"), KIND[k][7])), int(_f(r.get("escalate_days"), KIND[k][8]))
        if not (1 <= td <= 90 and 1 <= ed <= 90):
            raise ApiError("%s: target and escalation days must be 1 to 90." % KIND[k][1])
        own = ",".join(x.strip() for x in str(r.get("owner_role") or KIND[k][6]).split(",") if x.strip())
        bad = [x for x in own.split(",") if x and x not in roles]
        if bad:
            raise ApiError("%s: unknown role %s." % (KIND[k][1], ", ".join(bad)))
        c.execute("INSERT OR REPLACE INTO fcc_rules(kind, enabled, threshold, owner_role, target_days, escalate_days, updated_by, updated_at) "
                  "VALUES(?,?,?,?,?,?,?,?)", (k, 1 if r.get("enabled", True) else 0, thr, own, td, ed, u.get("id"), now()))
    for k in ("fcc_escalation_finance", "fcc_escalation_project"):
        if k in a:
            v = ",".join(x.strip() for x in str(a[k] or "").split(",") if x.strip())
            bad = [x for x in v.split(",") if x and x not in roles]
            if bad or not v:
                raise ApiError("Escalation chain: unknown or missing role %s." % ", ".join(bad))
            c.execute("INSERT OR REPLACE INTO settings(key, value) VALUES(?,?)", (k, v))
    if "fcc_scan_minutes" in a:
        m = int(_f(a["fcc_scan_minutes"], 60))
        if not 5 <= m <= 1440:
            raise ApiError("Check every 5 to 1440 minutes.")
        c.execute("INSERT OR REPLACE INTO settings(key, value) VALUES('fcc_scan_minutes', ?)", (str(m),))
    audit(c, u, "settings", "fcc_rules", None, a)
    return fcc_rules(c, u, {})


# ───────────────────────────── command centre ─────────────────────────────
VIEWS = [("director", "Director"), ("finance", "Finance manager"), ("accounts", "Accounts"), ("project_manager", "Project manager"),
         ("procurement", "Procurement"), ("stores", "Stores"), ("site", "Site engineer")]
VIEW_SECTIONS = {
    "director": ["cash", "funding", "receivables", "payables", "ipcs", "projects", "commitments", "loans", "alerts", "actions"],
    "finance": ["cash", "funding", "receivables", "payables", "ipcs", "projects", "commitments", "loans", "alerts", "actions"],
    "accounts": ["cash", "receivables", "payables", "ipcs", "loans", "alerts", "actions"],
    "project_manager": ["projects", "ipcs", "receivables", "commitments", "site", "alerts", "actions"],
    "procurement": ["procurement", "commitments", "stores", "payables", "alerts"],
    "stores": ["stores", "procurement", "alerts"],
    "site": ["site", "stores", "alerts"]}
ROLE_VIEW = {"director": "director", "finance_manager": "finance", "accountant": "accounts", "project_accountant": "accounts",
             "project_manager": "project_manager", "quantity_surveyor": "project_manager", "procurement_officer": "procurement",
             "storekeeper": "stores", "site_engineer": "site", "site_supervisor": "site", "equipment_manager": "site",
             "admin": "director", "viewer": "director"}
SECTION_DOMAIN = {"cash": "cash", "funding": "cash", "loans": "cash", "receivables": "receivables", "ipcs": "receivables",
                  "payables": "payables", "projects": "cost", "commitments": "procurement", "procurement": "procurement",
                  "stores": "stores", "site": "progress"}
SECTION_LABEL = {"cash": "Company cash", "funding": "Funding gap", "receivables": "Receivables", "payables": "Payables due",
                 "ipcs": "IPCs", "projects": "Projects: cash, cost to complete and profit", "commitments": "Major purchase commitments",
                 "loans": "Loans and advances", "alerts": "Priority alerts", "actions": "Assigned actions", "procurement": "Orders waiting for approval",
                 "stores": "Stores: shortages and slow stock", "site": "Site reporting and progress"}


def section_ok(c, u, sec):
    if sec in ("alerts", "actions"):
        return right(c, u, "alerts", "view")
    d = SECTION_DOMAIN[sec]
    if sec == "commitments":
        return domain_ok(c, u, "procurement") or domain_ok(c, u, "cost")
    return domain_ok(c, u, d)


def cash_by_project(c, pids=None, to=None):
    """Cash received and paid per project to date. A voucher's cash and bank movement is shared among its other lines'
    projects in proportion to their amounts; a transfer between two cash or bank accounts moves nothing."""
    import api_cfw as CF
    _b, ids = CF.money_balance(c, to)
    out, unattributed = {}, 0.0
    if not ids:
        return out, 0.0
    idl = ",".join(map(str, ids))
    w, p = "", []
    if to:
        w, p = " AND v.date<=?", [to]
    vids = [r["id"] for r in q(c, "SELECT DISTINCT v.id FROM vouchers v JOIN voucher_lines l ON l.voucher_id=v.id WHERE "
                                  "v.status IN ('posted','reversed') AND l.account_id IN (%s)%s" % (idl, w), tuple(p))]
    money = set(ids)
    for k in range(0, len(vids), 400):
        chunk = vids[k:k + 400]
        lines = q(c, "SELECT l.voucher_id, l.account_id, l.debit, l.credit, COALESCE(l.project_id, v.project_id) pid FROM voucher_lines l "
                     "JOIN vouchers v ON v.id=l.voucher_id WHERE l.voucher_id IN (%s)" % ",".join(map(str, chunk)))
        byv = {}
        for ln in lines:
            byv.setdefault(ln["voucher_id"], []).append(ln)
        for vid, ls in byv.items():
            net = sum((x["debit"] or 0) - (x["credit"] or 0) for x in ls if x["account_id"] in money)
            if abs(net) < 0.005:
                continue
            other = [x for x in ls if x["account_id"] not in money]
            wts = {}
            for x in other:
                if x["pid"]:
                    wts[x["pid"]] = wts.get(x["pid"], 0) + abs((x["debit"] or 0) - (x["credit"] or 0))
            tot = sum(wts.values())
            if tot < 0.005:
                unattributed += net
                continue
            for pid, wt in wts.items():
                share = net * wt / tot
                o = out.setdefault(pid, {"received": 0.0, "paid": 0.0})
                if share >= 0:
                    o["received"] += share
                else:
                    o["paid"] += -share
    res = {}
    for pid, o in out.items():
        if pids is not None and pid not in pids:
            continue
        res[pid] = {"received": r2(o["received"]), "paid": r2(o["paid"]), "net": r2(o["received"] - o["paid"])}
    return res, r2(unattributed)


def funding(c, fc):
    """Section 20: required cash to meet obligations and the reserve, less available cash, less reliable receipts before
    those obligations fall due. Worked week by week on the prudent view (confirmed and likely receipts only); the
    largest positive value is the funding gap."""
    if not fc:
        return None
    lines = fc["lines"]
    rows, cum_out, cum_rel, cum_all = [], 0.0, 0.0, 0.0
    for i, w in enumerate(fc["weeks"]):
        cum_out += sum(ln["values"][i] for ln in lines if ln["kind"] == "out")
        cum_rel += sum(ln["values"][i] for ln in lines if ln["kind"] == "in" and ln["confidence"] in ("confirmed", "likely"))
        cum_all += sum(ln["values"][i] for ln in lines if ln["kind"] == "in")
        required = cum_out + w["reserve"] + w["restricted"]
        gap = required - fc["opening"] - cum_rel
        rows.append({"week": w["week"], "start": w["start"], "required": r2(required), "available": fc["opening"],
                     "reliable_receipts": r2(cum_rel), "all_receipts": r2(cum_all), "gap": r2(gap), "shortfall": r2(max(0.0, gap)),
                     "expected_gap": r2(max(0.0, w["gap"]))})
    short = [r for r in rows if r["shortfall"] > 0.5]
    worst = max(rows, key=lambda r: r["gap"]) if rows else None
    return {"rows": rows, "gap": r2(max([r["shortfall"] for r in rows] or [0])), "first_week": short[0]["week"] if short else None,
            "last_week": short[-1]["week"] if short else None, "weeks_short": len(short),
            "worst": worst, "expected_gap": fc["max_gap"], "opening": fc["opening"], "reserve": fc["reserve"],
            "formula": "Funding gap = cash needed for payments to date plus the reserve and restricted funds - cash today - "
                       "confirmed and likely receipts to date, each week of the 13; the largest positive value."}


class _Pids(list):
    """Project ids a section covers; scoped is True when one project was chosen (company-wide items are left out)."""
    scoped = False


def _in_scope(r, pids):
    if r["project_id"]:
        return r["project_id"] in pids
    return not getattr(pids, "scoped", False)


def summary(c, u, view, pid=None):
    t = today()
    al = allowed_projects(c, u)
    pids = _Pids(p["id"] for p in _active_projects(c) if (al is None or p["id"] in al) and (not pid or p["id"] == pid))
    pids.scoped = bool(pid)
    projs = _projects(c)
    secs = VIEW_SECTIONS[view]
    out = {"view": view, "today": t, "sections": [], "hidden": [], "project_id": pid}
    data = {}
    fc = None

    def need_fc():
        nonlocal fc
        if fc is None:
            fc = F(c, "cfw.forecast", {"compare": False})
        return fc

    for sec in secs:
        if not section_ok(c, u, sec) or (sec in ("cash", "funding", "loans") and pid):
            out["hidden"].append(sec)
            continue
        try:
            data[sec] = SECTION_FN[sec](c, u, pids, projs, need_fc, t)
            out["sections"].append(sec)
        except ApiError as e:
            data[sec] = {"error": str(e)}
            out["sections"].append(sec)
        except Exception as e:  # one section never hides the others
            data[sec] = {"error": "Not available: %s" % str(e)[:160]}
            out["sections"].append(sec)
    out["data"] = data
    out["labels"] = SECTION_LABEL
    return out


def s_cash(c, u, pids, projs, need_fc, t):
    fc = need_fc()
    w1 = fc["weeks"][0]
    low_av = min(fc["weeks"], key=lambda w: w["available"])
    return {"opening": fc["opening"], "reserve": fc["reserve"], "restricted": w1["restricted"],
            "available_now": r2(fc["opening"] - fc["reserve"] - w1["restricted"]), "lowest": fc["lowest"],
            "lowest_available": {"week": low_av["week"], "start": low_av["start"], "available": low_av["available"]},
            "first_gap": fc["first_gap"], "max_gap": fc["max_gap"], "prudent_lowest": fc["prudent_lowest"],
            "series": [{k: w[k] for k in ("week", "start", "closing", "available", "prudent_closing", "in", "out")} for w in fc["weeks"]],
            "route": "#/acc/cash?tab=3"}


def s_funding(c, u, pids, projs, need_fc, t):
    f = funding(c, need_fc())
    f["route"] = "#/acc/cash?tab=4"
    return f


def s_receivables(c, u, pids, projs, need_fc, t):
    rows = []
    for p in pids:
        try:
            rows += F(c, "fc.receivables", {"project_id": p}, u)["rows"]
        except ApiError:
            continue
    tot = {k: r2(sum(r[k] for r in rows)) for k in ("unmeasured", "unbilled", "in_draft", "submitted", "not_due", "overdue")}
    ages = {k: r2(sum(r["ages"][k] for r in rows)) for k in ("a30", "a60", "a90", "a90p")}
    return {"totals": tot, "ages": ages, "retention": r2(sum(r["retention"]["held"] for r in rows)),
            "client_advance": r2(sum(r["client_advance"] for r in rows)),
            "by_project": [{"project_id": r["project_id"], "code": r["code"], "overdue": r["overdue"], "not_due": r["not_due"],
                            "submitted": r["submitted"], "unbilled": r["unbilled"]} for r in rows],
            "route": "#/acc/ageing?tab=1"}


def s_payables(c, u, pids, projs, need_fc, t):
    d = F(c, "fc.payables", {}, u)
    company = all_projects(c, u) and set(pids) == {p["id"] for p in _active_projects(c)}
    rows = d["rows"] if company else [r for r in d["rows"] if r["project_id"] in pids]
    def due(n):
        lim = _add(t, n)
        return r2(sum(r["amount"] for r in rows if r["due_date"] and t <= r["due_date"] <= lim))
    over = r2(sum(r["amount"] for r in rows if r["due_date"] and r["due_date"] < t))
    cats = {}
    for r in rows:
        cats[r["category"]] = r2(cats.get(r["category"], 0) + r["amount"])
    return {"overdue": over, "d7": due(7), "d30": due(30), "d90": due(90), "total": r2(sum(r["amount"] for r in rows)),
            "by_category": cats, "requested": r2(sum(r["requested"] or 0 for r in rows)), "route": "#/acc/ageing?tab=3"}


def s_ipcs(c, u, pids, projs, need_fc, t):
    import api_fc as FC
    groups = {"submission": [], "certification": [], "payment": []}
    for i in q(c, "SELECT * FROM ipc WHERE project_id IN (%s)" % ",".join(map(str, pids or [0]))):
        s = FC.ipc_state(c, i, t=t)
        g = {"prepared": "submission", "submitted": "certification", "under_review": "certification", "certified": "payment",
             "overdue": "payment", "part_paid": "payment"}.get(s["stage"])
        if g:
            groups[g].append({"id": s["id"], "no": s["no"], "project": _pcode(projs, s["project_id"]), "project_id": s["project_id"],
                              "amount": s["amount"], "stage": s["stage"], "days": s["days_in_stage"],
                              "late": s["cert_overdue_days"] or s["pay_overdue_days"]})
    return {k: {"count": len(v), "amount": r2(sum(x["amount"] or 0 for x in v)), "items": v[:15]} for k, v in groups.items()} | \
        {"route": "#/p/ipc?tab=1"}


def s_projects(c, u, pids, projs, need_fc, t):
    import api_ctc as CT
    import api_cash as CA
    money = domain_ok(c, u, "cash") or core.can(u, "accounts", "view")
    used, unattr = cash_by_project(c, set(pids)) if money else ({}, None)
    rows = []
    for p in pids:
        r = {"project_id": p, "code": projs[p]["code"], "name": projs[p]["name"]}
        try:
            d = CT.project_ctc(c, p, t)
            T = d["total"]
            r.update(revenue=d["revenue"], cost=T["cost"], eac=T["eac"], committed=T["committed"], remaining=T["remaining"],
                     gross=d.get("gross"), net=d.get("net"), net_pct=d.get("net_pct"), incomplete=d["incomplete"],
                     alerts=len(d["alerts"]))
        except Exception as e:
            r["error"] = "Forecast not available: %s" % str(e)[:100]
        if money:
            cu = used.get(p) or {"received": 0.0, "paid": 0.0, "net": 0.0}
            r.update(cash_received=cu["received"], cash_paid=cu["paid"], cash_used=r2(max(0.0, -cu["net"])), cash_net=cu["net"])
            try:
                pc = CA.project_cash(c, p, "early", None, 0, 0.0, CA.mkey(_d(t)))
                r.update(funding_need=pc["peak_cash"], funding_month=pc["peak_month"], financing_cost=pc["financing_cost"])
            except Exception:
                r.update(funding_need=None, funding_month=None)
        rows.append(r)
    return {"rows": rows, "cash_shown": money, "unattributed_cash": unattr, "route": "#/cl/cvrall?tab=1",
            "basis": "Cash in − out = receipts less payments to date (negative: the project has used company cash), each voucher's cash and bank movement shared among its "
                     "projects. Funding need = the peak cash the 12-month cash budget needs for the project's remaining work."}


def s_commitments(c, u, pids, projs, need_fc, t):
    import api_ctc as CT
    rows = []
    for p in pids:
        for x in CT.commitments(c, p):
            x = dict(x)
            x["project"] = projs[p]["code"]
            x["party"] = val(c, "SELECT name FROM parties WHERE id=?", (x.get("party_id"),), "")
            rows.append(x)
    groups = {}
    for x in rows:
        k = (x["kind"], x["doc_id"])
        g = groups.setdefault(k, {"kind": x["kind"], "doc_id": x["doc_id"], "doc_no": x["doc_no"], "project": x["project"],
                                  "project_id": x.get("project_id"), "party": x["party"], "due": x.get("due"), "amount": 0.0})
        g["amount"] = r2(g["amount"] + x["amount"])
    top = sorted(groups.values(), key=lambda g: -g["amount"])
    return {"total": r2(sum(g["amount"] for g in top)), "count": len(top), "top": top[:10], "route": "#/cl/cvr?tab=1",
            "basis": "Open purchase-order lines (without VAT) and subcontract work not yet billed."}


def s_loans(c, u, pids, projs, need_fc, t):
    import api_fc as FC
    loans = []
    for ln in q(c, "SELECT * FROM loans WHERE active=1"):
        nxt = None
        if ln["start_date"] and ln["emi"]:
            for n in range(0, 600):
                d = FC._add_months(ln["start_date"], n)
                if ln["end_date"] and d > ln["end_date"]:
                    break
                if d >= t:
                    nxt = d
                    break
        loans.append({"name": ln["name"], "lender": ln["lender"], "kind": ln["kind"], "balance": ln["balance"], "rate": ln["rate"],
                      "emi": ln["emi"], "next_date": nxt, "limit": ln["limit_amount"], "end_date": ln["end_date"]})
    eq = []
    for f in q(c, "SELECT f.*, e.code FROM eq_finance f LEFT JOIN equipment e ON e.id=f.equipment_id WHERE COALESCE(f.emi,0)>0"):
        paid = int(val(c, "SELECT COUNT(*) FROM eq_emi WHERE equipment_id=?", (f["equipment_id"],)))
        left = max(0, (f["emi_count"] or 0) - paid) if f["emi_count"] else None
        eq.append({"code": f["code"], "lender": f["lender"], "emi": f["emi"], "left": left,
                   "remaining": r2(left * f["emi"]) if left is not None else None, "rate": f["interest_rate"]})
    adv = {"client_advance": r2(-FC.role_balance(c, "client_advance")), "supplier_advance": r2(FC.role_balance(c, "supplier_advance")),
           "subcon_advance": r2(FC.role_balance(c, "subcon_advance"))}
    fc = need_fc()
    inst = r2(sum(sum(ln["values"]) for ln in fc["lines"] if ln["label"] == "Loan and equipment instalments"))
    return {"loans": loans, "equipment": eq, "advances": adv, "instalments_13w": inst, "route": "#/acc/ageing?tab=3",
            "basis": "Loan balances as recorded on each loan; advances from the ledger (client advances still to be recovered "
                     "through IPCs; supplier and subcontractor advances still to be recovered from their bills)."}


def s_alerts(c, u, pids, projs, need_fc, t):
    rows = [dict(r) for r in q(c, "SELECT * FROM fcc_alerts WHERE status IN ('open','acknowledged','in_progress','escalated')")]
    rows = [_view(c, r) for r in rows if can_see_alert(c, u, r) and _in_scope(r, pids)]
    rows.sort(key=lambda r: (SEV_RANK.get(r["severity"], 1), r["target_date"] or "9999", -(r["amount"] or 0)))
    return {"count": len(rows), "high": sum(1 for r in rows if r["severity"] == "high"), "top": rows[:8],
            "last_scan": setting(c, "fcc_last_scan"), "route": "#/action?tab=1"}


def s_actions(c, u, pids, projs, need_fc, t):
    rows = [dict(r) for r in q(c, "SELECT * FROM fcc_alerts WHERE status IN ('open','acknowledged','in_progress','escalated')")]
    rows = [r for r in rows if can_see_alert(c, u, r) and _in_scope(r, pids)]
    by = {}
    for r in rows:
        k = r["owner_id"] or 0
        g = by.setdefault(k, {"owner_id": r["owner_id"], "owner": uname(c, r["owner_id"]) or "Not assigned", "count": 0, "overdue": 0,
                              "escalated": 0, "high": 0})
        g["count"] += 1
        g["overdue"] += 1 if r["target_date"] and r["target_date"] < t else 0
        g["escalated"] += 1 if r["status"] == "escalated" else 0
        g["high"] += 1 if r["severity"] == "high" else 0
    mine = [_view(c, r) for r in rows if u.get("id") in (r["owner_id"], r["escalated_to"])]
    mine.sort(key=lambda r: (r["target_date"] or "9999"))
    return {"owners": sorted(by.values(), key=lambda g: (-g["overdue"], -g["count"])), "mine": mine[:10], "route": "#/action?tab=1"}


def s_procurement(c, u, pids, projs, need_fc, t):
    rows = [r for r in F(c, "ctc.pending_pos", {}, u) if r["project_id"] in pids]
    for r in rows:
        r["project"] = _pcode(projs, r["project_id"])
    return {"rows": rows, "count": len(rows), "total": r2(sum(r["total"] or 0 for r in rows)), "route": "#/proc/po?tab=1"}


def s_stores(c, u, pids, projs, need_fc, t):
    try:
        import api_res as RES
    except Exception:
        RES = None
    short = []
    for p in pids:
        if not RES:
            break
        try:
            for r in RES.material_risks(c, p) or []:
                if r.get("risk"):
                    short.append({"project": projs[p]["code"], "project_id": p, "code": r["code"], "name": r["name"], "unit": r["unit"],
                                  "available": r["available"], "days_left": r["days_left"], "lead_days": r["lead_days"],
                                  "pending_po": r.get("pending_po"), "why": r.get("why")})
        except Exception:
            continue
    slow = {"rows": [], "total": 0.0}
    try:
        d = F(c, "books.slow", {}, u)
        rows = [r for r in d["rows"] if r["project_id"] in pids]
        slow = {"rows": rows[:10], "total": r2(sum(r["value"] for r in rows)), "count": len(rows)}
    except Exception:
        pass
    return {"shortages": short, "slow": slow, "route": "#/inv/risk"}


def s_site(c, u, pids, projs, need_fc, t):
    import api_ctc as CT
    rows = []
    for p in pids:
        last = val(c, "SELECT MAX(date) FROM dpr WHERE project_id=? AND status<>'rejected'", (p,), None)
        waiting = val(c, "SELECT COUNT(*) FROM dpr WHERE project_id=? AND status IN ('submitted','checked')", (p,))
        drafts = val(c, "SELECT COUNT(*) FROM dpr WHERE project_id=? AND status='draft'", (p,))
        r = {"project_id": p, "code": projs[p]["code"], "name": projs[p]["name"], "last_dpr": last,
             "days_since": _days(last, t) if last else None, "waiting_approval": waiting, "drafts": drafts}
        try:
            ch = CT.chain(c, p, t)
            r.update(behind=len(ch["delays"]), billing_held=ch["total"]["behind_v"], unmeasured=ch["total"]["unmeasured_v"],
                     basis=ch["progress_basis"])
        except Exception:
            r.update(behind=None)
        rows.append(r)
    return {"rows": rows, "route": "#/p/dpr"}


SECTION_FN = {"cash": s_cash, "funding": s_funding, "receivables": s_receivables, "payables": s_payables, "ipcs": s_ipcs,
              "projects": s_projects, "commitments": s_commitments, "loans": s_loans, "alerts": s_alerts, "actions": s_actions,
              "procurement": s_procurement, "stores": s_stores, "site": s_site}


@api("fcc.summary")
def fcc_summary(c, u, a):
    view = a.get("view") or ROLE_VIEW.get(u.get("role"), "director")
    if view not in VIEW_SECTIONS:
        raise ApiError("Unknown view.")
    pid = _int(a.get("project_id"))
    if pid:
        check_project(c, u, pid)
    if right(c, u, "alerts", "view") and _auto_scan(c):
        try:
            scan(c, SYS)
        except Exception:
            pass
    out = summary(c, u, view, pid)
    out["views"] = VIEWS
    out["default_view"] = ROLE_VIEW.get(u.get("role"), "director")
    return out


# ───────────────────────────── funding gap and financing options ─────────────────────────────
FIN_KINDS = [("overdraft", "Overdraft / working-capital limit"), ("term_loan", "Term loan"),
             ("invoice_discounting", "Discounting certified bills"), ("supplier_credit", "Longer supplier credit"),
             ("equity", "Owner's equity / capital"), ("other", "Other")]
REPAYMENTS = [("bullet", "Interest monthly, principal at the end"), ("emi", "Equal monthly instalments"),
              ("upfront", "Interest deducted at the start, repaid at the end")]


def _cash_need(c, u, action="view"):
    import api_cfw as CF
    CF._need(c, u, action)


def _add_months(s, n):
    import api_fc as FC
    return FC._add_months(s, n)


def option_flows(o):
    """Every cash movement the option causes, by date: (date, amount, what). Positive = money in."""
    amt = _f(o["amount"])
    d0 = o["draw_date"]
    n = int(_f(o.get("tenor_months"), 0))
    rate = _f(o.get("rate_pct")) / 100.0
    fee = amt * _f(o.get("fee_pct")) / 100.0 + _f(o.get("fee_fixed"))
    fl = []
    kind, rep = o["kind"], o.get("repayment") or "bullet"
    if kind == "equity":
        fl.append((d0, amt, "drawn"))
        if fee:
            fl.append((d0, -fee, "fees"))
        return fl
    if kind == "supplier_credit":
        # payments of this amount are made n months later than planned; the supplier's price or fee is the cost
        fl.append((d0, amt, "payment deferred"))
        fl.append((_add_months(d0, max(1, n)), -amt, "deferred payment made"))
        if fee:
            fl.append((d0, -fee, "fees"))
        if rate:
            fl.append((_add_months(d0, max(1, n)), -amt * rate / 12 * max(1, n), "interest"))
        return fl
    n = max(1, n)
    if rep == "upfront" or kind == "invoice_discounting":
        disc = amt * rate / 12 * n
        fl.append((d0, amt, "drawn"))
        if disc:
            fl.append((d0, -disc, "interest"))
        fl.append((_add_months(d0, n), -amt, "repaid"))
        if fee:
            fl.append((d0, -fee, "fees"))
        return fl
    fl.append((d0, amt, "drawn"))
    if fee:
        fl.append((d0, -fee, "fees"))
    if rep == "emi" and rate > 0:
        r = rate / 12
        emi = amt * r / (1 - (1 + r) ** -n)
        bal = amt
        for k in range(1, n + 1):
            it = bal * r
            pr = emi - it
            bal -= pr
            fl.append((_add_months(d0, k), -it, "interest"))
            fl.append((_add_months(d0, k), -pr, "principal"))
    elif rep == "emi":
        for k in range(1, n + 1):
            fl.append((_add_months(d0, k), -amt / n, "principal"))
    else:
        for k in range(1, n + 1):
            if rate:
                fl.append((_add_months(d0, k), -amt * rate / 12, "interest"))
        fl.append((_add_months(d0, n), -amt, "principal"))
    return fl


def compare_option(o, fc):
    fl = option_flows(o)
    w0 = _d(fc["week0"])
    end = w0 + timedelta(days=7 * len(fc["weeks"]) - 1)
    add = [0.0] * len(fc["weeks"])
    cost13 = 0.0
    for d, amt, what in fl:
        dd = _d(d)
        if dd is None or dd > end:
            continue
        i = max(0, (dd - w0).days // 7)
        add[i] += amt
        if what in ("interest", "fees"):
            cost13 += -amt
    cum, rows = 0.0, []
    for i, w in enumerate(fc["weeks"]):
        cum += add[i]
        rows.append({"week": w["week"], "closing": r2(w["closing"] + cum), "available": r2(w["available"] + cum),
                     "prudent_closing": r2(w["prudent_closing"] + cum)})
    gaps = [r for r in rows if r["available"] < -0.5]
    interest_total = sum(-a for _d2, a, w in fl if w == "interest")
    fees = sum(-a for _d2, a, w in fl if w == "fees")
    repay = [d for d, a, w in fl if w in ("principal", "repaid", "deferred payment made")]
    return {"id": o.get("id"), "name": o["name"], "kind": o["kind"], "amount": r2(_f(o["amount"])), "rate_pct": o.get("rate_pct"),
            "draw_date": o["draw_date"], "tenor_months": o.get("tenor_months"), "repayment": o.get("repayment"),
            "collateral": o.get("collateral"), "risks": o.get("risks"), "notes": o.get("notes"),
            "lowest_available": min(r["available"] for r in rows), "max_gap": r2(max([-r["available"] for r in gaps] or [0])),
            "gap_weeks": len(gaps), "first_gap": gaps[0]["week"] if gaps else None, "closes_gap": not gaps,
            "cost_13w": r2(cost13), "interest_total": r2(interest_total), "fees": r2(fees),
            "total_cost": r2(interest_total + fees) if o["kind"] != "equity" else None,
            "first_repayment": min(repay) if repay else None, "last_repayment": max(repay) if repay else None,
            "rate_missing": o["kind"] not in ("equity",) and o.get("rate_pct") in (None, ""),
            "weeks": rows, "flows": [{"date": d, "amount": r2(a), "what": w} for d, a, w in sorted(fl)]}


def management_actions(c, fc):
    """Section 20, in its order. Each line gives the amount behind it from the records; none of it is certain cash."""
    import api_ctc as CT
    out = []
    try:
        rc = F(c, "fc.receivables", {})["totals"]
    except Exception:
        rc = None
    acts = _active_projects(c)
    out.append({"step": 1, "label": "Collect earned and certified receivables",
                "amount": r2(rc["overdue"] + rc["not_due"]) if rc else None,
                "basis": "Certified invoices not yet paid: %s overdue, %s not yet due." % (_m(rc["overdue"]), _m(rc["not_due"])) if rc else "Not available",
                "route": "#/acc/ageing?tab=2"})
    out.append({"step": 2, "label": "Measure work on time and submit IPCs",
                "amount": r2(rc["unmeasured"] + rc["unbilled"] + rc["in_draft"]) if rc else None,
                "basis": ("Work done not measured %s, measured not claimed %s, IPCs in draft %s (estimates at current rates)." %
                          (_m(rc["unmeasured"]), _m(rc["unbilled"]), _m(rc["in_draft"]))) if rc else "Not available",
                "route": "#/p/ipc?tab=1"})
    pot = 0.0
    for p in acts:
        try:
            pot += CT.project_ctc(c, p["id"], today())["potential_total"]
        except Exception:
            pass
    out.append({"step": 3, "label": "Resolve certification objections and document variations",
                "amount": r2((rc["submitted"] if rc else 0) + pot),
                "basis": "IPCs awaiting certification %s; variations and claims not yet approved %s (not revenue until approved)." % (
                    _m(rc["submitted"] if rc else 0), _m(pot)), "route": "#/p/variations"})
    try:
        slow = F(c, "books.slow", {})["total"]
    except Exception:
        slow = None
    out.append({"step": 4, "label": "Reduce excess inventory and early purchasing", "amount": slow,
                "basis": "Stock with no movement for 90 days or more, at stock value." if slow is not None else "Not available",
                "route": "#/inv/stock"})
    idle, hire = 0, 0.0
    for p in acts:
        try:
            res = CT.resources(c, p["id"], _add(today(), -29), today())
        except Exception:
            continue
        for e in res["equipment"]:
            if "idle_hire" in e["flags"] or "low_utilisation" in e["flags"]:
                idle += 1
                hire += e["rent"] if "idle_hire" in e["flags"] else 0
    out.append({"step": 5, "label": "Use equipment better and cut avoidable cost", "amount": r2(hire) if hire else None,
                "basis": "%d machine(s) idle or under-used in the last 30 days; hire billed on idle hired machines %s." % (idle, _m(hire)),
                "route": "#/cl/cvr?tab=2"})
    po = r2(sum(sum(ln["values"]) for ln in fc["lines"] if ln["label"] == "Purchase orders to be delivered")) if fc else None
    out.append({"step": 6, "label": "Time purchases and payments to the contract terms", "amount": po,
                "basis": "Open purchase orders the forecast pays in the 13 weeks; check each against when the work needs it "
                         "(Purchase orders > Approval check).", "route": "#/proc/po?tab=1"})
    n = val(c, "SELECT COUNT(*) FROM fcc_fin_options WHERE active=1")
    out.append({"step": 7, "label": "Compare working-capital financing", "amount": None,
                "basis": "%d option(s) entered below. Nothing is borrowed from here." % n, "route": "#/acc/cash?tab=4"})
    bad = []
    for p in acts:
        try:
            d = CT.project_ctc(c, p["id"], today())
        except Exception:
            continue
        if (d.get("net") is not None and d["net"] < 0) or any(a_["key"] in ("margin_fade", "net_loss", "gross_loss") for a_ in d["alerts"]):
            bad.append(p["code"])
    out.append({"step": 8, "label": "Review projects with negative forecasts or falling margins", "amount": None,
                "basis": ("Projects: " + ", ".join(bad)) if bad else "No project has a forecast loss or a falling margin.",
                "route": "#/cl/cvrall?tab=1"})
    return out


@api("fcc.funding")
def fcc_funding(c, u, a):
    _cash_need(c, u)
    fc = F(c, "cfw.forecast", {"compare": False})
    f = funding(c, fc)
    opts = [dict(o) for o in q(c, "SELECT * FROM fcc_fin_options WHERE active=1 ORDER BY id")]
    comps = [compare_option(o, fc) for o in opts]
    base = {"name": "No financing", "lowest_available": min(w["available"] for w in fc["weeks"]), "max_gap": fc["max_gap"],
            "gap_weeks": sum(1 for w in fc["weeks"] if w["gap"] > 0.5), "first_gap": fc["first_gap"], "closes_gap": not fc["first_gap"],
            "cost_13w": 0.0, "total_cost": 0.0, "weeks": [{"week": w["week"], "closing": w["closing"], "available": w["available"]}
                                                          for w in fc["weeks"]]}
    return {"funding": f, "actions": management_actions(c, fc), "base": base, "options": comps, "kinds": FIN_KINDS,
            "repayments": REPAYMENTS, "week0": fc["week0"], "weeks": [{"week": w["week"], "start": w["start"]} for w in fc["weeks"]],
            "can_edit": right(c, u, "accounts", "edit"),
            "note": "A comparison only. BuildCore does not borrow, post or recommend; figures depend on the terms entered."}


@api("fcc.option_save")
def fcc_option_save(c, u, a):
    _cash_need(c, u, "edit")
    d = a.get("row") or a
    name = (d.get("name") or "").strip()
    if not name:
        raise ApiError("Give the option a name.")
    if d.get("kind") not in dict(FIN_KINDS):
        raise ApiError("Choose the kind of financing.")
    amt = _f(d.get("amount"), -1)
    if amt <= 0:
        raise ApiError("The amount must be more than zero.")
    if not _d(d.get("draw_date")):
        raise ApiError("Give the date the money would come in.")
    for k, lo, hi in (("rate_pct", 0, 100), ("fee_pct", 0, 100)):
        if d.get(k) not in (None, "") and not lo <= _f(d.get(k), -1) <= hi:
            raise ApiError("%s must be 0 to 100." % k.replace("_pct", " %"))
    ten = _int(d.get("tenor_months"))
    if d["kind"] != "equity" and (not ten or ten < 1 or ten > 360):
        raise ApiError("Give the term in months (1 to 360).")
    rep = d.get("repayment") or "bullet"
    if rep not in dict(REPAYMENTS):
        raise ApiError("Unknown repayment.")
    row = {"name": name[:120], "kind": d["kind"], "amount": r2(amt), "rate_pct": _f(d.get("rate_pct")) if d.get("rate_pct") not in (None, "") else None,
           "fee_pct": _f(d.get("fee_pct")) if d.get("fee_pct") not in (None, "") else None, "fee_fixed": _f(d.get("fee_fixed")) or None,
           "draw_date": d["draw_date"][:10], "tenor_months": ten, "repayment": rep, "collateral": (d.get("collateral") or "")[:500] or None,
           "risks": (d.get("risks") or "")[:1000] or None, "notes": (d.get("notes") or "")[:1000] or None, "updated_at": now()}
    rid = _int(d.get("id"))
    if rid:
        old = get(c, "fcc_fin_options", rid, "Option")
        upd(c, "fcc_fin_options", rid, row)
        audit(c, u, "edit", "fcc_fin_options", rid, {"was": dict(old), "now": row})
    else:
        row.update(created_by=u.get("id"), created_at=now(), active=1)
        rid = ins(c, "fcc_fin_options", row)
        audit(c, u, "create", "fcc_fin_options", rid, row)
    return {"id": rid}


@api("fcc.option_delete")
def fcc_option_delete(c, u, a):
    _cash_need(c, u, "edit")
    rid = int(a["id"])
    get(c, "fcc_fin_options", rid, "Option")
    upd(c, "fcc_fin_options", rid, {"active": 0, "updated_at": now()})
    audit(c, u, "remove", "fcc_fin_options", rid, None)
    return {"id": rid}


# ───────────────────────────── report builder ─────────────────────────────
def C(k, label, t="text"):
    return {"k": k, "label": label, "type": t}


def _udpr_right(c, u, action):
    try:
        import api_udpr as UD
        return UD.right(c, u, "dpr", action)
    except Exception:
        return core.can(u, "project", "view")


def _pids_for(c, u, f):
    al = allowed_projects(c, u)
    want = [int(x) for x in (f.get("project_ids") or []) if str(x).strip().isdigit()]
    if want:
        for p in want:
            check_project(c, u, p)
        return want
    ids = [r["id"] for r in q(c, "SELECT id FROM projects ORDER BY id")]
    return ids if al is None else [p for p in ids if p in al]


def _in(ids):
    return ",".join(str(int(x)) for x in ids) or "0"


def ds_dpr(c, u, f):
    pids = _pids_for(c, u, f)
    sql = ("SELECT d.id dpr_id, d.date, d.no dpr_no, d.shift, d.status dpr_status, d.project_id, p.code project, w.id line_id, "
           "a.code activity, a.name activity_name, b.code boq, b.description boq_description, w.location, w.chainage_from, w.chainage_to, "
           "COALESCE(a.unit, b.unit) unit, w.planned_qty, w.actual_qty reported_qty, x.accepted_qty, x.delay_reason, w.remarks, "
           "fp.name package, ff.name front, h.locked_at, x.vals FROM dpr_work w JOIN dpr d ON d.id=w.dpr_id JOIN projects p ON p.id=d.project_id "
           "LEFT JOIN activities a ON a.id=w.activity_id LEFT JOIN boq_items b ON b.id=w.boq_item_id "
           "LEFT JOIN udpr_work x ON x.work_id=w.id LEFT JOIN udpr_head h ON h.dpr_id=d.id "
           "LEFT JOIN udpr_fronts fp ON fp.id=COALESCE(x.package_id, h.package_id) LEFT JOIN udpr_fronts ff ON ff.id=COALESCE(x.front_id, h.front_id) "
           "WHERE d.project_id IN (%s)" % _in(pids))
    args = []
    if f.get("from"):
        sql += " AND d.date>=?"
        args.append(f["from"])
    if f.get("to"):
        sql += " AND d.date<=?"
        args.append(f["to"])
    rows = [dict(r) for r in q(c, sql + " ORDER BY d.date, d.no, w.id", tuple(args))]
    hv = {}
    if rows:
        for r in q(c, "SELECT dpr_id, key, value FROM udpr_values WHERE dpr_id IN (%s)" % _in({r["dpr_id"] for r in rows})):
            hv.setdefault(r["dpr_id"], {})[r["key"]] = r["value"]
    att = {}
    if f.get("attachments") and rows:
        for r in q(c, "SELECT dpr_id, filename, caption FROM files WHERE dpr_id IN (%s)" % _in({r["dpr_id"] for r in rows})):
            att.setdefault(r["dpr_id"], []).append(r["caption"] or r["filename"])
    for r in rows:
        if r.pop("locked_at", None):
            r["dpr_status"] = "locked"
        try:
            lv = json.loads(r.pop("vals") or "{}")
        except ValueError:
            lv = {}
        for k, v in (lv or {}).items():
            r["cf_" + k] = v if not isinstance(v, (list, dict)) else json.dumps(v)
        for k, v in hv.get(r["dpr_id"], {}).items():
            r["cf_" + k] = v
        if f.get("attachments"):
            r["attachments"] = "; ".join(att.get(r["dpr_id"], []))
    return rows


def ds_cash_weeks(c, u, f):
    fc = F(c, "cfw.forecast", {"compare": False})
    return [dict(w) for w in fc["weeks"]]


def ds_cash_lines(c, u, f):
    fc = F(c, "cfw.forecast", {"compare": False})
    out = []
    for ln in fc["lines"]:
        for i, v in enumerate(ln["values"]):
            if abs(v) > 0.005:
                out.append({"line": ln["label"], "direction": "in" if ln["kind"] == "in" else "out", "confidence": ln["confidence_label"],
                            "week": i + 1, "start": fc["weeks"][i]["start"], "amount": v, "signed": v if ln["kind"] == "in" else -v})
    return out


def ds_receivables(c, u, f):
    out = []
    pids = set(_pids_for(c, u, f))
    d = F(c, "fc.receivables", {"as_of": f.get("to") or today()}, u)
    for p in d["rows"]:
        if p["project_id"] not in pids:
            continue
        for i in p["invoices"]:
            ipc = q1(c, "SELECT no FROM ipc WHERE invoice_id=?", (i["id"],))
            od = i["days_overdue"]
            out.append({"project": p["code"], "project_id": p["project_id"], "client": val(c, "SELECT name FROM parties WHERE id=?", (i["party_id"],), ""),
                        "invoice": i["no"], "ipc": ipc["no"] if ipc else None, "date": i["date"], "due_date": i["due_date"],
                        "balance": i["balance"], "days_overdue": od,
                        "bucket": "Not due" if od <= 0 else "1-30" if od <= 30 else "31-60" if od <= 60 else "61-90" if od <= 90 else "Over 90"})
    return out


def ds_ipcs(c, u, f):
    import api_fc as FC
    pids = _pids_for(c, u, f)
    out = []
    for i in q(c, "SELECT * FROM ipc WHERE project_id IN (%s) ORDER BY date, id" % _in(pids)):
        s = FC.ipc_state(c, i)
        out.append({"project": val(c, "SELECT code FROM projects WHERE id=?", (i["project_id"],)), "project_id": i["project_id"],
                    "ipc": s["no"], "date": s["date"], "status": s["status"], "stage": FC.IPC_STAGE_LABEL.get(s["stage"], s["stage"]),
                    "claimed_net": s["claimed_net"], "cert_due": s["cert_due"], "cert_overdue_days": s["cert_overdue_days"],
                    "certified_at": s["certified_at"], "payable": s["payable"], "paid": s["paid"], "outstanding": s["outstanding"],
                    "pay_overdue_days": s["pay_overdue_days"], "responsible": s["responsible"], "next_action": s["next_action"]})
    return out


def ds_payables(c, u, f):
    pids = set(_pids_for(c, u, f))
    d = F(c, "fc.payables", {"as_of": f.get("to") or today()}, u)
    out = []
    for r in d["rows"]:
        if r["project_id"] and r["project_id"] not in pids:
            continue
        out.append({"category": r["category"], "party": r["party_name"], "project": val(c, "SELECT code FROM projects WHERE id=?", (r["project_id"],), None),
                    "project_id": r["project_id"], "ref": r["ref_no"], "date": r["date"], "due_date": r["due_date"], "amount": r["amount"],
                    "requested": r["requested"], "unrequested": r["unrequested"], "days_overdue": r["days_overdue"],
                    "bucket": r["bucket"], "obligation": r["obligation"]})
    return out


def ds_projects(c, u, f):
    import api_ctc as CT
    out = []
    pids = set(_pids_for(c, u, f))
    for p in _active_projects(c):
        if p["id"] not in pids:
            continue
        r = {"project": p["code"], "project_id": p["id"], "name": p["name"], "contract_value": p["contract_value"]}
        try:
            d = CT.project_ctc(c, p["id"], today())
            T = d["total"]
            r.update(revenue=d["revenue"], cost=T["cost"], committed=T["committed"], remaining=T["remaining"], eac=T["eac"],
                     budget=T["budget_current"], gross=d.get("gross"), overhead=d.get("overhead"), financing=d.get("financing"),
                     net=d.get("net"), net_pct=d.get("net_pct"), incomplete="yes" if d["incomplete"] else "",
                     alerts="; ".join(x["text"] for x in d["alerts"]))
        except Exception as e:
            r["alerts"] = "Not available: %s" % str(e)[:80]
        try:
            ch = CT.chain(c, p["id"], today())
            r.update(unmeasured=ch["total"]["unmeasured_v"], unbilled=ch["total"]["unbilled_v"], received=ch["total"]["received"],
                     billing_held=ch["total"]["behind_v"])
        except Exception:
            pass
        out.append(r)
    return out


def ds_equipment(c, u, f):
    import api_ctc as CT
    out = []
    to = f.get("to") or today()
    frm = f.get("from") or _add(to, -29)
    for p in _pids_for(c, u, f):
        try:
            res = CT.resources(c, p, frm, to)
        except Exception:
            continue
        code = val(c, "SELECT code FROM projects WHERE id=?", (p,))
        for e in res["equipment"]:
            out.append(dict({k: e[k] for k in ("code", "name", "ownership", "days", "working", "idle", "breakdown", "utilisation", "fuel_qty",
                                                "fuel_cost", "repairs", "rent", "internal", "cost", "cost_per_hour")},
                            project=code, project_id=p, flags=", ".join(e["flags"]), period="%s to %s" % (frm, to)))
    return out


def ds_labour(c, u, f):
    import api_ctc as CT
    out = []
    to = f.get("to") or today()
    frm = f.get("from") or _add(to, -29)
    for p in _pids_for(c, u, f):
        try:
            res = CT.resources(c, p, frm, to)
        except Exception:
            continue
        code = val(c, "SELECT code FROM projects WHERE id=?", (p,))
        for r in res["labour"]:
            out.append({"project": code, "project_id": p, "activity": r.get("activity"), "name": r.get("name"), "qty": r.get("qty"),
                        "unit": r.get("unit"), "expected_md": r.get("expected_md"), "actual_md": r.get("actual_md"),
                        "labour_pct": r.get("labour_pct"), "expected_mh": r.get("expected_mh"), "actual_mh": r.get("actual_mh"),
                        "machine_pct": r.get("machine_pct"), "labour_amount": r.get("labour_amount"), "flags": ", ".join(r.get("flags") or [])})
    return out


def ds_ledger(c, u, f):
    al = allowed_projects(c, u)
    pids = _pids_for(c, u, f)
    sql = ("SELECT v.date, v.no voucher, v.type voucher_type, v.status, a.code account_code, a.name account, a.type account_type, "
           "COALESCE(l.project_id, v.project_id) project_id, p.code project, l.debit, l.credit, (COALESCE(l.debit,0)-COALESCE(l.credit,0)) net, "
           "COALESCE(l.narration, v.narration) narration, pt.name party, l.id line_id FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id "
           "JOIN accounts a ON a.id=l.account_id LEFT JOIN projects p ON p.id=COALESCE(l.project_id, v.project_id) "
           "LEFT JOIN parties pt ON pt.id=COALESCE(l.party_id, v.party_id) WHERE v.status IN ('posted','reversed')")
    args = []
    if f.get("project_ids") or al is not None:
        sql += " AND COALESCE(l.project_id, v.project_id) IN (%s)" % _in(pids)
    if f.get("from"):
        sql += " AND v.date>=?"
        args.append(f["from"])
    if f.get("to"):
        sql += " AND v.date<=?"
        args.append(f["to"])
    rows = [dict(r) for r in q(c, sql + " ORDER BY v.date, v.id, l.id LIMIT 200000", tuple(args))]
    if rows and _has(c, "cl_alloc"):
        codes = {}
        for r in q(c, "SELECT a.line_id, k.code FROM cl_alloc a JOIN cl_codes k ON k.id=a.cost_code_id WHERE a.line_id IN (%s)" %
                      _in(r["line_id"] for r in rows)):
            codes.setdefault(r["line_id"], []).append(r["code"])
        for r in rows:
            r["cost_code"] = ", ".join(codes.get(r["line_id"], []))
    return rows


def ds_alerts(c, u, f):
    pids = set(_pids_for(c, u, f))
    out = []
    for r in q(c, "SELECT * FROM fcc_alerts ORDER BY id"):
        r = dict(r)
        if not can_see_alert(c, u, r) or (r["project_id"] and r["project_id"] not in pids):
            continue
        v = _view(c, r)
        out.append({"title": v["title"], "kind": v["kind_label"], "area": v["domain_label"], "project": v["project_code"],
                    "project_id": v["project_id"], "severity": v["severity"], "status": v["status_label"], "amount": v["amount"],
                    "due_date": v["due_date"], "owner": v["owner_name"], "target_date": v["target_date"], "overdue_days": v["overdue_days"],
                    "escalation_level": v["escalation_level"], "first_seen": (v["first_seen"] or "")[:10], "basis": v["basis"],
                    "action": v["action"]})
    return out


def ds_commitments(c, u, f):
    import api_ctc as CT
    out = []
    for p in _pids_for(c, u, f):
        code = val(c, "SELECT code FROM projects WHERE id=?", (p,))
        for x in CT.commitments(c, p):
            out.append({"project": code, "project_id": p, "kind": x["kind"], "document": x["doc_no"], "date": x.get("date"),
                        "due": x.get("due"), "party": val(c, "SELECT name FROM parties WHERE id=?", (x.get("party_id"),), ""),
                        "item": x.get("description"), "boq": val(c, "SELECT code FROM boq_items WHERE id=?", (x.get("boq_item_id"),), None),
                        "qty_open": x.get("qty"),
                        "rate": x.get("rate"), "amount": x["amount"]})
    return out


DATASETS = {
    "dpr": {"label": "DPR work lines", "domain": "progress", "date": "date", "rows": ds_dpr, "dynamic": "cf_",
            "cols": [C("date", "Date", "date"), C("project", "Project"), C("dpr_no", "DPR"), C("shift", "Shift"), C("dpr_status", "DPR status"),
                     C("package", "Package"), C("front", "Work front"), C("activity", "Activity"), C("activity_name", "Activity name"),
                     C("boq", "BOQ item"), C("boq_description", "BOQ description"), C("location", "Location"),
                     C("chainage_from", "Chainage from", "number"), C("chainage_to", "Chainage to", "number"), C("unit", "Unit"),
                     C("planned_qty", "Planned qty", "number"), C("reported_qty", "Reported qty", "number"),
                     C("accepted_qty", "Accepted qty", "number"), C("delay_reason", "Delay reason"), C("remarks", "Remarks"),
                     C("attachments", "Attachments")]},
    "cash_weeks": {"label": "13-week cash forecast (weeks)", "domain": "cash", "date": "start", "rows": ds_cash_weeks, "company": True,
                   "cols": [C("week", "Week", "number"), C("start", "From", "date"), C("end", "To", "date"), C("opening", "Opening", "money"),
                            C("in", "Money in", "money"), C("out", "Money out", "money"), C("net", "Net", "money"), C("closing", "Closing", "money"),
                            C("prudent_closing", "Prudent closing", "money"), C("reserve", "Reserve", "money"),
                            C("restricted", "Restricted", "money"), C("available", "Available to spend", "money"), C("gap", "Funding gap", "money")]},
    "cash_lines": {"label": "13-week cash forecast (lines)", "domain": "cash", "date": "start", "rows": ds_cash_lines, "company": True,
                   "cols": [C("line", "Line"), C("direction", "In / out"), C("confidence", "Confidence"), C("week", "Week", "number"),
                            C("start", "Week from", "date"), C("amount", "Amount", "money"), C("signed", "Signed amount", "money")]},
    "receivables": {"label": "Receivables (IPC ageing)", "domain": "receivables", "date": "date", "rows": ds_receivables,
                    "cols": [C("project", "Project"), C("client", "Client"), C("invoice", "Invoice"), C("ipc", "IPC"), C("date", "Date", "date"),
                             C("due_date", "Due", "date"), C("balance", "Balance", "money"), C("days_overdue", "Days overdue", "number"),
                             C("bucket", "Age")]},
    "ipcs": {"label": "IPCs and their stage", "domain": "receivables", "date": "date", "rows": ds_ipcs,
             "cols": [C("project", "Project"), C("ipc", "IPC"), C("date", "Date", "date"), C("status", "Status"), C("stage", "Stage"),
                      C("claimed_net", "Net claimed", "money"), C("cert_due", "Certification due", "date"),
                      C("cert_overdue_days", "Certification late (days)", "number"), C("certified_at", "Certified", "date"),
                      C("payable", "Payable", "money"), C("paid", "Paid", "money"), C("outstanding", "Outstanding", "money"),
                      C("pay_overdue_days", "Payment late (days)", "number"), C("responsible", "Responsible"), C("next_action", "Next action")]},
    "payables": {"label": "Payables (ageing)", "domain": "payables", "date": "due_date", "rows": ds_payables,
                 "cols": [C("category", "Category"), C("party", "Party"), C("project", "Project"), C("ref", "Reference"), C("date", "Date", "date"),
                          C("due_date", "Due", "date"), C("amount", "Amount", "money"), C("requested", "In payment requests", "money"),
                          C("unrequested", "Not requested", "money"), C("days_overdue", "Days overdue", "number"), C("bucket", "Due bucket"),
                          C("obligation", "Obligation")]},
    "projects": {"label": "Project financial health", "domain": "cost", "date": None, "rows": ds_projects,
                 "cols": [C("project", "Project"), C("name", "Name"), C("contract_value", "Contract", "money"), C("revenue", "Revenue", "money"),
                          C("cost", "Cost to date", "money"), C("committed", "Open orders", "money"), C("remaining", "Remaining cost", "money"),
                          C("eac", "Final cost", "money"), C("budget", "Budget", "money"), C("gross", "Gross profit", "money"),
                          C("overhead", "Overhead", "money"), C("financing", "Financing", "money"), C("net", "Net profit", "money"),
                          C("net_pct", "Net %", "number"), C("unmeasured", "Done, not measured", "money"),
                          C("unbilled", "Measured, not billed", "money"), C("received", "Cash received", "money"),
                          C("billing_held", "Billing held by delay", "money"), C("incomplete", "Forecast incomplete"), C("alerts", "Alerts")]},
    "equipment": {"label": "Resource costs: equipment", "domain": "equipment", "date": None, "period": True, "rows": ds_equipment,
                  "cols": [C("project", "Project"), C("code", "Machine"), C("name", "Name"), C("ownership", "Owned / hired"), C("days", "Days", "number"),
                           C("working", "Working h", "number"), C("idle", "Idle h", "number"), C("breakdown", "Breakdown h", "number"),
                           C("utilisation", "Utilisation %", "number"), C("fuel_qty", "Fuel qty", "number"), C("fuel_cost", "Fuel", "money"),
                           C("repairs", "Repairs", "money"), C("rent", "Hire", "money"), C("internal", "Own machine charge", "money"),
                           C("cost", "Cost", "money"), C("cost_per_hour", "Cost per hour", "money"), C("flags", "Flags"), C("period", "Period")]},
    "labour": {"label": "Resource costs: labour and machine productivity", "domain": "progress", "date": None, "period": True, "rows": ds_labour,
               "cols": [C("project", "Project"), C("activity", "Activity"), C("name", "Name"), C("qty", "Qty done", "number"), C("unit", "Unit"),
                        C("expected_md", "Man-days allowed", "number"), C("actual_md", "Man-days worked", "number"),
                        C("labour_pct", "Labour %", "number"), C("expected_mh", "Machine h allowed", "number"),
                        C("actual_mh", "Machine h worked", "number"), C("machine_pct", "Machine %", "number"),
                        C("labour_amount", "Labour cost", "money"), C("flags", "Flags")]},
    "ledger": {"label": "Ledger lines (accounts and cost codes)", "domain": "ledger", "date": "date", "rows": ds_ledger,
               "cols": [C("date", "Date", "date"), C("voucher", "Voucher"), C("voucher_type", "Type"), C("status", "Status"),
                        C("account_code", "Account code"), C("account", "Account"), C("account_type", "Account type"), C("project", "Project"),
                        C("cost_code", "Cost code"), C("party", "Party"), C("debit", "Debit", "money"), C("credit", "Credit", "money"),
                        C("net", "Debit - credit", "money"), C("narration", "Narration")]},
    "alerts": {"label": "Financial alerts", "domain": "alerts", "date": "first_seen", "rows": ds_alerts,
               "cols": [C("title", "Alert"), C("kind", "Kind"), C("area", "Area"), C("project", "Project"), C("severity", "Severity"),
                        C("status", "Status"), C("amount", "Amount", "money"), C("due_date", "Expected date", "date"), C("owner", "Owner"),
                        C("target_date", "Target date", "date"), C("overdue_days", "Days past target", "number"),
                        C("escalation_level", "Escalation level", "number"), C("first_seen", "First seen", "date"), C("basis", "Basis"),
                        C("action", "Next action")]},
    "commitments": {"label": "Purchase and subcontract commitments", "domain": "procurement", "date": "date", "rows": ds_commitments,
                    "cols": [C("project", "Project"), C("kind", "Kind"), C("document", "Document"), C("date", "Date", "date"), C("due", "Due", "date"),
                             C("party", "Party"), C("item", "Item"), C("boq", "BOQ / code"), C("qty_open", "Open qty", "number"),
                             C("rate", "Rate", "money"), C("amount", "Open value", "money")]},
}


def dataset_ok(c, u, key):
    ds = DATASETS[key]
    d = ds["domain"]
    if d == "progress" and key == "dpr":
        return _udpr_right(c, u, "view")
    if d == "ledger":
        return core.can(u, "accounts", "view") or u.get("role") == "admin" or bool(u.get("system"))
    if d == "alerts":
        return right(c, u, "alerts", "view")
    if d == "procurement":
        return domain_ok(c, u, "procurement") or domain_ok(c, u, "cost")
    return domain_ok(c, u, d)


OPS = ("eq", "ne", "contains", "gt", "gte", "lt", "lte", "in", "empty", "notempty")


def _cmp(v, op, x, typ):
    if op == "empty":
        return v in (None, "")
    if op == "notempty":
        return v not in (None, "")
    if v is None:
        return op == "ne"
    if typ in ("number", "money"):
        try:
            v, x2 = float(v), float(x)
        except (TypeError, ValueError):
            return False
    else:
        v, x2 = str(v).lower(), str(x if x is not None else "").lower()
    if op == "eq":
        return v == x2
    if op == "ne":
        return v != x2
    if op == "contains":
        return x2 in str(v)
    if op == "in":
        return str(v).lower() in [s.strip().lower() for s in str(x).split(",")]
    return {"gt": v > x2, "gte": v >= x2, "lt": v < x2, "lte": v <= x2}[op]


PERIODS = [("custom", "Dates below"), ("last_7", "Last 7 days"), ("last_30", "Last 30 days"), ("last_90", "Last 90 days"),
           ("this_month", "This month"), ("last_month", "Last month"), ("this_year", "This calendar year"), ("all", "All dates")]


def period_dates(p, frm=None, to=None):
    t = _d(today())
    if p in (None, "", "custom"):
        return frm or None, to or None
    if p == "all":
        return None, None
    if p in ("last_7", "last_30", "last_90"):
        n = int(p.split("_")[1])
        return (t - timedelta(days=n - 1)).isoformat(), t.isoformat()
    if p == "this_month":
        return t.replace(day=1).isoformat(), t.isoformat()
    if p == "last_month":
        e = t.replace(day=1) - timedelta(days=1)
        return e.replace(day=1).isoformat(), e.isoformat()
    if p == "this_year":
        return t.replace(month=1, day=1).isoformat(), t.isoformat()
    raise ApiError("Unknown period.")


def run_report(c, u, d, limit=5000):
    key = d.get("dataset")
    if key not in DATASETS:
        raise ApiError("Choose what the report is about.")
    if not dataset_ok(c, u, key):
        raise ApiError("Your role cannot see %s." % DATASETS[key]["label"].lower())
    ds = DATASETS[key]
    if ds.get("company") and not all_projects(c, u):
        raise ApiError("PROJECT_DENIED: %s is company-wide and needs access to every project." % ds["label"])
    frm, to = period_dates(d.get("period"), d.get("from"), d.get("to"))
    f = {"from": frm, "to": to, "project_ids": d.get("project_ids") or [], "attachments": bool(d.get("attachments"))}
    rows = ds["rows"](c, u, f)
    cols = list(ds["cols"])
    if ds.get("dynamic"):
        seen = []
        for r in rows:
            for k in r:
                if k.startswith(ds["dynamic"]) and k not in seen:
                    seen.append(k)
        cols += [C(k, "Field: " + k[len(ds["dynamic"]):]) for k in seen]
    if not f["attachments"]:
        cols = [x for x in cols if x["k"] != "attachments"]
    cmap = {x["k"]: x for x in cols}
    # date filter on rows the dataset did not filter itself
    df = ds.get("date")
    if df and key not in ("dpr", "ledger") and (frm or to):
        rows = [r for r in rows if r.get(df) and (not frm or str(r[df])[:10] >= frm) and (not to or str(r[df])[:10] <= to)]
    for flt in d.get("filters") or []:
        k, op = flt.get("field"), flt.get("op") or "eq"
        if k not in cmap or op not in OPS:
            raise ApiError("Unknown filter %s %s." % (k, op))
        rows = [r for r in rows if _cmp(r.get(k), op, flt.get("value"), cmap[k]["type"])]
    sel = [k for k in (d.get("columns") or []) if k in cmap] or [x["k"] for x in ds["cols"][:8]]
    for srt in reversed(d.get("sort") or []):
        k = srt.get("field")
        if k in cmap:
            num = cmap[k]["type"] in ("number", "money")
            rows.sort(key=lambda r: ((r.get(k) is None), (r.get(k) or 0) if num else str(r.get(k) or "").lower()),
                      reverse=srt.get("dir") == "desc")
    groups = [g for g in (d.get("group_by") or []) if g in cmap][:2]
    if groups:
        rows.sort(key=lambda r: tuple(str(r.get(g) if r.get(g) is not None else "") for g in groups))
    summ = {k: v for k, v in (d.get("summaries") or {}).items() if k in cmap and v in ("sum", "avg", "min", "max", "count")}
    total_rows = len(rows)
    truncated = total_rows > limit

    def agg(rs):
        out = {}
        for k, how in summ.items():
            vals = [r.get(k) for r in rs if r.get(k) not in (None, "")]
            if how == "count":
                out[k] = len(vals)
                continue
            try:
                nums = [float(v) for v in vals]
            except (TypeError, ValueError):
                continue
            if not nums:
                out[k] = None
            elif how == "sum":
                out[k] = r2(sum(nums))
            elif how == "avg":
                out[k] = r2(sum(nums) / len(nums))
            elif how == "min":
                out[k] = min(nums)
            else:
                out[k] = max(nums)
        return out

    lines = []
    shown = rows[:limit]

    def emit(rs, level):
        if level >= len(groups):
            for r in rs:
                lines.append({"type": "row", "values": {k: r.get(k) for k in sel}})
            return
        g = groups[level]
        cur, buf = object(), []

        def flush():
            if not buf:
                return
            lines.append({"type": "group", "level": level, "label": "%s: %s" % (cmap[g]["label"], buf[0].get(g) if buf[0].get(g) not in (None, "") else "(none)")})
            emit(buf, level + 1)
            if summ:
                lines.append({"type": "subtotal", "level": level, "label": "Total %s" % (buf[0].get(g) if buf[0].get(g) not in (None, "") else "(none)"),
                              "values": agg(buf), "count": len(buf)})

        for r in rs:
            kv = r.get(g)
            if buf and kv != cur:
                flush()
                buf = []
            cur = kv
            buf.append(r)
        flush()

    emit(shown, 0)
    if summ:
        lines.append({"type": "total", "label": "Total", "values": agg(rows), "count": total_rows})
    return {"title": d.get("title") or d.get("name") or ds["label"], "dataset": key, "dataset_label": ds["label"],
            "columns": [cmap[k] for k in sel], "all_columns": cols, "lines": lines, "rows": total_rows, "truncated": truncated,
            "limit": limit, "from": frm, "to": to, "orientation": d.get("orientation") or "portrait", "header": d.get("header") or "",
            "footer": d.get("footer") or "", "summaries": summ, "group_by": groups,
            "projects": ", ".join(val(c, "SELECT code FROM projects WHERE id=?", (int(p),), "") for p in f["project_ids"]) or "All you may see",
            "generated": now(), "by": u.get("name")}


BUILTIN_REPORTS = [
    ("dpr_daily", "DPR report: work done by day", {"dataset": "dpr", "period": "last_7",
     "columns": ["date", "project", "dpr_no", "dpr_status", "front", "activity", "activity_name", "unit", "planned_qty", "reported_qty", "accepted_qty", "remarks"],
     "group_by": ["date"], "summaries": {"reported_qty": "sum", "accepted_qty": "sum"}, "orientation": "landscape"}),
    ("cash_13w", "13-week cash forecast", {"dataset": "cash_weeks", "period": "all",
     "columns": ["week", "start", "opening", "in", "out", "closing", "prudent_closing", "available", "gap"],
     "summaries": {"in": "sum", "out": "sum"}, "orientation": "landscape"}),
    ("ipc_ageing", "IPC ageing (receivables)", {"dataset": "receivables", "period": "all",
     "columns": ["project", "client", "ipc", "invoice", "date", "due_date", "days_overdue", "balance"], "group_by": ["bucket"],
     "sort": [{"field": "days_overdue", "dir": "desc"}], "summaries": {"balance": "sum"}}),
    ("payable_ageing", "Payables ageing", {"dataset": "payables", "period": "all",
     "columns": ["party", "project", "ref", "due_date", "days_overdue", "amount", "requested", "unrequested"], "group_by": ["bucket"],
     "sort": [{"field": "due_date", "dir": "asc"}], "summaries": {"amount": "sum", "unrequested": "sum"}}),
    ("project_health", "Project financial health", {"dataset": "projects", "period": "all",
     "columns": ["project", "revenue", "cost", "committed", "eac", "gross", "overhead", "financing", "net", "net_pct", "unbilled", "incomplete"],
     "summaries": {"revenue": "sum", "cost": "sum", "eac": "sum", "net": "sum"}, "orientation": "landscape"}),
    ("resource_costs", "Resource costs: equipment", {"dataset": "equipment", "period": "last_30",
     "columns": ["project", "code", "name", "ownership", "working", "idle", "utilisation", "fuel_cost", "repairs", "rent", "cost", "cost_per_hour", "flags"],
     "group_by": ["project"], "summaries": {"fuel_cost": "sum", "repairs": "sum", "rent": "sum", "cost": "sum"}, "orientation": "landscape"}),
    ("company_summary", "Company financial summary", {"dataset": "ledger", "period": "this_year",
     "columns": ["account_code", "account", "debit", "credit", "net"], "group_by": ["account_type"],
     "sort": [{"field": "account_code", "dir": "asc"}], "summaries": {"debit": "sum", "credit": "sum", "net": "sum"}}),
]


def _seed_reports(c):
    for code, name, d in BUILTIN_REPORTS:
        if q1(c, "SELECT id FROM fcc_reports WHERE code=? AND builtin=1", (code,)):
            continue
        ins(c, "fcc_reports", {"name": name, "dataset": d["dataset"], "definition": json.dumps(d), "owner_id": None, "shared": 1,
                               "builtin": 1, "code": code, "active": 1, "created_at": now(), "updated_at": now()})


def _report_visible(c, u, r):
    return r["active"] and (r["builtin"] or r["shared"] or r["owner_id"] == u.get("id") or u.get("role") == "admin") \
        and r["dataset"] in DATASETS and dataset_ok(c, u, r["dataset"])


@api("fcc.report_meta")
def fcc_report_meta(c, u, a):
    need(c, u, "reports", "view", "use the report builder")
    ds = [{"key": k, "label": v["label"], "columns": v["cols"], "date": v.get("date"), "period": bool(v.get("date") or v.get("period")),
           "company": bool(v.get("company")), "dynamic": bool(v.get("dynamic"))} for k, v in DATASETS.items() if dataset_ok(c, u, k)]
    al = allowed_projects(c, u)
    projs = [{"id": p["id"], "code": p["code"], "name": p["name"]} for p in q(c, "SELECT id, code, name FROM projects ORDER BY code")
             if al is None or p["id"] in al]
    reps = []
    for r in q(c, "SELECT * FROM fcc_reports WHERE active=1 ORDER BY builtin DESC, name"):
        r = dict(r)
        if _report_visible(c, u, r):
            r["definition"] = json.loads(r["definition"])
            r["owner"] = uname(c, r["owner_id"])
            r["can_edit"] = not r["builtin"] and (r["owner_id"] == u.get("id") or (r["shared"] and right(c, u, "reports", "approve"))
                                                  or u.get("role") == "admin")
            reps.append(r)
    return {"datasets": ds, "projects": projs, "reports": reps, "periods": PERIODS, "ops": OPS,
            "rights": {"create": right(c, u, "reports", "create"), "share": right(c, u, "reports", "approve"),
                       "export": right(c, u, "reports", "export")}}


@api("fcc.report_run")
def fcc_report_run(c, u, a):
    need(c, u, "reports", "view", "run reports")
    d = a.get("definition") or {}
    if a.get("id"):
        r = dict(get(c, "fcc_reports", int(a["id"]), "Report"))
        if not _report_visible(c, u, r):
            raise ApiError("You cannot open this report.")
        d = dict(json.loads(r["definition"]), **{k: v for k, v in d.items() if v not in (None, "", [])})
        d.setdefault("name", r["name"])
    return run_report(c, u, d, min(int(_f(a.get("limit"), 2000)), 5000))


@api("fcc.report_xlsx")
def fcc_report_xlsx(c, u, a):
    need(c, u, "reports", "export", "export reports")
    res = fcc_report_run(c, u, dict(a, limit=50000))
    import api_copilot as CP
    cols = res["columns"]
    out = []
    for ln in res["lines"]:
        if ln["type"] == "row":
            out.append([ln["values"].get(x["k"]) for x in cols])
        elif ln["type"] == "group":
            out.append([("  " * ln["level"]) + ln["label"]] + [None] * (len(cols) - 1))
        else:
            row = [ln["values"].get(x["k"]) for x in cols]
            row[0] = ln["label"] + (" (%d)" % ln["count"] if ln.get("count") is not None else "")
            out.append(row)
    title = res["title"] + (" %s to %s" % (res["from"] or "start", res["to"] or "today") if res["from"] or res["to"] else "")
    data = CP.make_xlsx(title[:120], [x["label"] for x in cols], out)
    audit(c, u, "export", "fcc_report", a.get("id"), {"dataset": res["dataset"], "rows": res["rows"]})
    return {"filename": re.sub(r"[^A-Za-z0-9_.-]+", "_", res["title"])[:80] + ".xlsx", "b64": base64.b64encode(data).decode("ascii"),
            "rows": res["rows"]}


@api("fcc.report_save")
def fcc_report_save(c, u, a):
    need(c, u, "reports", "create", "save reports")
    d = a.get("definition") or {}
    name = (a.get("name") or d.get("title") or "").strip()
    if not name:
        raise ApiError("Give the report a name.")
    if d.get("dataset") not in DATASETS or not dataset_ok(c, u, d["dataset"]):
        raise ApiError("Choose what the report is about.")
    run_report(c, u, d, 1)          # refuses a definition this person could not run
    shared = 1 if a.get("shared") else 0
    if shared and not right(c, u, "reports", "approve"):
        raise ApiError("Your role cannot share reports with everyone (needs 'approve' on reports).")
    clean = {k: d.get(k) for k in ("dataset", "period", "from", "to", "project_ids", "columns", "filters", "group_by", "sort", "summaries",
                                    "orientation", "header", "footer", "title", "attachments") if k in d}
    rid = _int(a.get("id"))
    if rid:
        r = dict(get(c, "fcc_reports", rid, "Report"))
        if r["builtin"]:
            raise ApiError("A built-in template cannot be changed; save it under a new name.")
        if not (r["owner_id"] == u.get("id") or (r["shared"] and right(c, u, "reports", "approve")) or u.get("role") == "admin"):
            raise ApiError("Only the person who made this report can change it.")
        upd(c, "fcc_reports", rid, {"name": name[:120], "dataset": d["dataset"], "definition": json.dumps(clean), "shared": shared,
                                    "updated_at": now()})
        audit(c, u, "edit", "fcc_reports", rid, {"was": r["definition"], "now": clean})
    else:
        rid = ins(c, "fcc_reports", {"name": name[:120], "dataset": d["dataset"], "definition": json.dumps(clean), "owner_id": u.get("id"),
                                     "shared": shared, "builtin": 0, "active": 1, "created_at": now(), "updated_at": now()})
        audit(c, u, "create", "fcc_reports", rid, clean)
    return {"id": rid}


@api("fcc.report_delete")
def fcc_report_delete(c, u, a):
    r = dict(get(c, "fcc_reports", int(a["id"]), "Report"))
    if r["builtin"]:
        raise ApiError("A built-in template cannot be removed.")
    if not (r["owner_id"] == u.get("id") or (r["shared"] and right(c, u, "reports", "approve")) or u.get("role") == "admin"):
        raise ApiError("Only the person who made this report can remove it.")
    upd(c, "fcc_reports", r["id"], {"active": 0, "updated_at": now()})
    audit(c, u, "remove", "fcc_reports", r["id"], None)
    return {"id": r["id"]}


@api("fcc.meta")
def fcc_meta(c, u, a):
    return {"version": VERSION, "kinds": [{"kind": k[0], "label": k[1], "domain": k[2]} for k in KINDS], "domains": DOMAINS,
            "statuses": STATUSES, "views": VIEWS, "default_view": ROLE_VIEW.get(u.get("role"), "director"),
            "rights": {"alerts": {x: right(c, u, "alerts", x) for x in ("view", "edit", "approve", "export")},
                       "reports": {x: right(c, u, "reports", x) for x in ("view", "create", "approve", "export")},
                       "cash": domain_ok(c, u, "cash"), "accounts_edit": right(c, u, "accounts", "edit")}}
