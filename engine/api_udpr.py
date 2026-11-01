"""
Universal daily progress reporting (BuildCore 2.25).

The DPR of 1.x-2.24 stays the posting document (one per project, date and shift: labour and machine costs, logsheets,
2.24 cost coding). 2.25 grows it into a configurable reporting engine without touching its tables:

  1. Packages and work fronts per project (udpr_fronts); every work, labour and machine line can carry one.
  2. Executive summary, temperature and named signatories on the report (udpr_head).
  3. Reported vs accepted quantities. dpr_work.actual_qty stays what the site reported (every existing screen reads
     it). The QS / engineer accepts quantities beside it (udpr_work); cumulative, balance and progress are worked
     from accepted quantities against the approved scope (BOQ revised quantity incl. approved variations).
     Accepting beyond scope needs an approver's override with a reason. A per-project switch (with a start date)
     makes BOQ executed quantity and activity progress follow accepted quantities.
  4. Templates as data: sections of fields, repeating tables and extra columns on work rows; nine built-in
     templates; versions frozen on every DPR so old reports keep their meaning.
  5. Continuing issue register on the existing issues list (fld_issues): one issue, one line per day reported.
  6. Workflow: Returned for correction, Rejected, Locked; revision snapshots and a step log with timestamps.
  7. Reports (daily, weekly, monthly, activity, work front, planned vs actual, manpower, equipment, materials,
     quality, safety, issues, photos, custom fields) with print and Excel.

Nothing here posts to the ledger, changes a balance or alters an existing table.
"""
import json
import re
from datetime import date, datetime, timedelta

import core
from core import ApiError, EPS, audit, get, ins, now, q, q1, r2, r4, setting, today, upd, val
import api_inventory as inv
from api_inventory import api
import udpr_templates as T

VERSION = "2.25.0"

SCHEMA = """
CREATE TABLE IF NOT EXISTS udpr_fronts(id INTEGER PRIMARY KEY, project_id INTEGER, kind TEXT DEFAULT 'front', code TEXT,
  name TEXT, parent_id INTEGER, party_id INTEGER, contract_id INTEGER, discipline TEXT, location TEXT, ch_from REAL,
  ch_to REAL, active INTEGER DEFAULT 1, sort INTEGER DEFAULT 0, ts TEXT);
CREATE INDEX IF NOT EXISTS ix_udf_p ON udpr_fronts(project_id, kind);
CREATE TABLE IF NOT EXISTS udpr_head(dpr_id INTEGER PRIMARY KEY, package_id INTEGER, front_id INTEGER, temp_min REAL,
  temp_max REAL, humidity REAL, conditions TEXT, prepared_name TEXT, checked_name TEXT, approved_name TEXT,
  s_work TEXT, s_achieve TEXT, s_activities TEXT, s_problems TEXT, s_instructions TEXT, s_decisions TEXT, s_next TEXT,
  tpl_versions TEXT, submitted_at TEXT, checked_at TEXT, returned_at TEXT, returned_by INTEGER, return_comment TEXT,
  rejected_at TEXT, rejected_by INTEGER, reject_reason TEXT, locked_at TEXT, locked_by INTEGER,
  revision INTEGER DEFAULT 0, client_token TEXT, created_at TEXT, updated_at TEXT);
CREATE INDEX IF NOT EXISTS ix_udh_tok ON udpr_head(client_token);
CREATE TABLE IF NOT EXISTS udpr_work(work_id INTEGER PRIMARY KEY, dpr_id INTEGER, front_id INTEGER, package_id INTEGER,
  accepted_qty REAL, accepted_by INTEGER, accepted_at TEXT, accept_note TEXT, over_scope_by INTEGER,
  over_scope_reason TEXT, delay_reason TEXT, vals TEXT);
CREATE INDEX IF NOT EXISTS ix_udw_d ON udpr_work(dpr_id);
CREATE TABLE IF NOT EXISTS udpr_lx(part TEXT, line_id INTEGER, dpr_id INTEGER, front_id INTEGER, vals TEXT,
  PRIMARY KEY(part, line_id));
CREATE INDEX IF NOT EXISTS ix_udl_d ON udpr_lx(dpr_id);
CREATE TABLE IF NOT EXISTS udpr_values(dpr_id INTEGER, key TEXT, value TEXT, PRIMARY KEY(dpr_id, key));
CREATE TABLE IF NOT EXISTS udpr_rows(id INTEGER PRIMARY KEY, dpr_id INTEGER, section TEXT, row_no INTEGER,
  front_id INTEGER, data TEXT, created_by INTEGER, ts TEXT);
CREATE INDEX IF NOT EXISTS ix_udr ON udpr_rows(dpr_id, section);
CREATE INDEX IF NOT EXISTS ix_udr_s ON udpr_rows(section);
CREATE TABLE IF NOT EXISTS udpr_templates(id INTEGER PRIMARY KEY, code TEXT, name TEXT, category TEXT, description TEXT,
  project_id INTEGER, system INTEGER DEFAULT 0, active INTEGER DEFAULT 1, draft TEXT, current_version_id INTEGER,
  updated_by INTEGER, updated_at TEXT);
CREATE TABLE IF NOT EXISTS udpr_tpl_versions(id INTEGER PRIMARY KEY, template_id INTEGER, version_no INTEGER,
  definition TEXT, note TEXT, published_by INTEGER, published_at TEXT);
CREATE INDEX IF NOT EXISTS ix_udtv ON udpr_tpl_versions(template_id, version_no);
CREATE TABLE IF NOT EXISTS udpr_project(project_id INTEGER PRIMARY KEY, templates TEXT, hidden TEXT, sections TEXT,
  progress_basis TEXT DEFAULT 'reported', basis_from TEXT, scope_tol REAL DEFAULT 0, updated_by INTEGER, updated_at TEXT);
CREATE TABLE IF NOT EXISTS udpr_log(id INTEGER PRIMARY KEY, dpr_id INTEGER, action TEXT, from_status TEXT, to_status TEXT,
  user_id INTEGER, user_name TEXT, comment TEXT, ts TEXT);
CREATE INDEX IF NOT EXISTS ix_udlog ON udpr_log(dpr_id);
CREATE TABLE IF NOT EXISTS udpr_revisions(id INTEGER PRIMARY KEY, dpr_id INTEGER, rev_no INTEGER, kind TEXT, reason TEXT,
  snapshot TEXT, user_id INTEGER, ts TEXT);
CREATE INDEX IF NOT EXISTS ix_udrev ON udpr_revisions(dpr_id);
CREATE TABLE IF NOT EXISTS udpr_issue_x(issue_id INTEGER PRIMARY KEY, category TEXT, front_id INTEGER, impact TEXT,
  mitigation TEXT, decision_required TEXT, claim_relevant INTEGER DEFAULT 0, responsible_party TEXT, event_id INTEGER,
  first_dpr_id INTEGER, first_date TEXT, last_dpr_id INTEGER, last_date TEXT, days_reported INTEGER DEFAULT 0,
  hours_total REAL DEFAULT 0);
CREATE TABLE IF NOT EXISTS udpr_issue_days(issue_id INTEGER, dpr_id INTEGER, date TEXT, hours REAL DEFAULT 0, note TEXT,
  PRIMARY KEY(issue_id, dpr_id));
CREATE INDEX IF NOT EXISTS ix_udid ON udpr_issue_days(dpr_id);
CREATE TABLE IF NOT EXISTS udpr_layouts(id INTEGER PRIMARY KEY, name TEXT, kind TEXT, params TEXT, owner_id INTEGER,
  shared INTEGER DEFAULT 1, ts TEXT);
"""

DEFAULTS = {"udpr_form": "smart",            # smart = short form for new DPRs | classic = the 10-step wizard
            "udpr_autolock_days": "0",       # lock approved DPRs automatically after N days (0 = only by hand)
            "udpr_report_header": "",        # extra line under the company name on printed reports
            "udpr_signatures": "Prepared by|Checked by|Approved by",
            "udpr_scope_tol": "0"}           # % above approved scope that may be accepted without override

FIELD_TYPES = [("text", "Text"), ("longtext", "Long text"), ("int", "Whole number"), ("decimal", "Decimal"),
               ("percent", "Percentage"), ("currency", "Amount (Rs)"), ("date", "Date"), ("time", "Time"),
               ("datetime", "Date and time"), ("select", "Dropdown"), ("multiselect", "Multi-select"),
               ("checkbox", "Checkbox"), ("yesno", "Yes / No"), ("measure", "Measurement with unit"),
               ("location", "Location"), ("chainage", "Chainage (m)"), ("person", "Person / responsible party"),
               ("boq", "BOQ item"), ("wbs", "WBS"), ("equipment", "Equipment"), ("material", "Material"),
               ("file", "File"), ("photo", "Photograph")]
TYPE_KEYS = {k for k, _ in FIELD_TYPES}
NUMERIC = {"int", "decimal", "percent", "currency", "measure", "chainage"}
REF_TABLE = {"boq": ("boq_items", True), "wbs": ("wbs", True), "equipment": ("equipment", False),
             "material": ("materials", False), "file": ("files", False), "photo": ("files", False)}
SECTION_KINDS = ("fields", "table", "line")
CORE_SECTIONS = [("summary", "Executive summary", 1), ("work", "Activities and quantities", 1), ("labour", "Manpower", 1),
                 ("equipment", "Equipment", 1), ("problems", "Major problems and issues", 1), ("photos", "Photographs", 1),
                 ("next", "Next-day plan", 1), ("materials", "Materials (from the store)", 0), ("quality", "Quality", 0),
                 ("hse", "Safety and environment", 0), ("delays", "Delays (hours lost)", 0), ("custom", "Project fields", 0)]
ISSUE_CATEGORIES = ["Design / drawings", "Access / land", "Utilities shifting", "Weather", "Materials", "Equipment",
                    "Labour", "Subcontractor", "Employer instruction", "Permits / approvals", "Community", "Safety",
                    "Quality", "Payment / funds", "Other"]
STATUS_LABEL = {"draft": "Draft", "submitted": "Submitted", "checked": "Checked", "approved": "Approved",
                "rejected": "Rejected", "returned": "Returned for correction", "locked": "Locked"}
KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,39}$")

# rights: three new rows in the 2.20 role templates. Existing DPR rights (project module) are unchanged.
DPR_RIGHTS = {
    "director": {"dpr": ["view", "approve", "export"], "dpr_setup": ["view"], "hse_private": ["view"]},
    "project_manager": {"dpr": ["view", "create", "edit", "submit", "approve", "export"], "dpr_setup": ["view", "edit"],
                        "hse_private": ["view"]},
    "site_engineer": {"dpr": ["view", "create", "edit", "submit", "export"]},
    "site_supervisor": {"dpr": ["view", "create", "edit", "submit"]},
    "quantity_surveyor": {"dpr": ["view", "edit", "export"]},
    "finance_manager": {"dpr": ["view", "export"]},
    "accountant": {"dpr": ["view"]}, "project_accountant": {"dpr": ["view", "export"]},
    "storekeeper": {"dpr": ["view"]}, "equipment_manager": {"dpr": ["view"]}, "procurement_officer": {"dpr": ["view"]},
    "viewer": {"dpr": ["view"]}}
NEW_MODULES = ("dpr", "dpr_setup", "hse_private")
FALLBACK = {"create": "edit", "submit": "edit", "export": "view", "delete": "approve", "post": "approve"}


# ───────────────────────────── start-up ─────────────────────────────
def init_udpr(c):
    c.executescript(SCHEMA)
    for k, v in DEFAULTS.items():
        if q1(c, "SELECT key FROM settings WHERE key=?", (k,)) is None:
            c.execute("INSERT INTO settings(key, value) VALUES(?,?)", (k, v))
    for m in NEW_MODULES:
        if m not in core.MODULES:
            core.MODULES.append(m)
    _seed_templates(c)
    _seed_rights(c)
    _install()
    try:
        import api_field as FLD
        for t in (("site", "Site problem / constraint"),):
            if t not in FLD.ISSUE_TYPES:
                FLD.ISSUE_TYPES.append(t)
    except Exception:
        pass


def _seed_templates(c):
    """Built-in templates are created once (version 1). Later edits by the company are never overwritten."""
    for code, name, cat, desc, sections in T.BUILTIN:
        if q1(c, "SELECT id FROM udpr_templates WHERE code=? AND system=1", (code,)):
            continue
        d = json.dumps({"sections": sections})
        tid = ins(c, "udpr_templates", {"code": code, "name": name, "category": cat, "description": desc, "system": 1,
                                        "active": 1, "draft": d, "updated_at": now()})
        vid = ins(c, "udpr_tpl_versions", {"template_id": tid, "version_no": 1, "definition": d,
                                           "note": "Built-in template (BuildCore %s)" % VERSION, "published_at": now()})
        upd(c, "udpr_templates", tid, {"current_version_id": vid})


def _seed_rights(c):
    if setting(c, "udpr_rights_seeded") == "1":
        return
    try:
        have = {r[1] for r in c.execute("PRAGMA table_info(ws_roles)")}
    except Exception:
        have = set()
    if not have:
        return
    for key, rows in DPR_RIGHTS.items():
        r = q1(c, "SELECT id, perms FROM ws_roles WHERE key=? AND builtin=1", (key,))
        if not r:
            continue
        try:
            p = json.loads(r["perms"] or "{}")
        except ValueError:
            p = {}
        for m, acts in rows.items():
            if m not in p:
                p[m] = acts
        c.execute("UPDATE ws_roles SET perms=? WHERE id=?", (json.dumps(p), r["id"]))
    c.execute("INSERT OR REPLACE INTO settings(key, value) VALUES('udpr_rights_seeded','1')")
    try:
        import api_workspace as W
        W.load_roles(c)
    except Exception:
        pass


# ───────────────────────────── small helpers ─────────────────────────────
def _f(v, d=0.0):
    try:
        return float(v) if v not in (None, "") else d
    except (TypeError, ValueError):
        return d


def _j(s, d=None):
    if s in (None, ""):
        return d
    try:
        return json.loads(s)
    except (TypeError, ValueError):
        return d


def _int(v):
    try:
        return int(v) if v not in (None, "", "null") else None
    except (TypeError, ValueError):
        return None


def right(c, u, module, action):
    """Rights on the 2.25 rows. A role template made before 2.25 (without the rows) follows the DPR rights it has."""
    if not u:
        return False
    if u.get("role") == "admin" or u.get("system"):
        return True
    t = None
    try:
        import api_workspace as W
        t = W.roles(c).get(u["role"])
    except Exception:
        t = None
    if t is not None and module in (t.get("perms") or {}):
        return action in set(t["perms"].get(module) or ())   # the 2.25 rows are read literally (export is its own right)
    base = {"dpr": "project", "dpr_setup": "admin"}.get(module)
    if base is None:   # hse_private: managers who can approve DPRs
        return core.can(u, "project", "approve")
    return core.can(u, base, FALLBACK.get(action, action))


def need(c, u, module, action, what):
    if not right(c, u, module, action):
        raise ApiError("Your role cannot %s (needs '%s' on %s in Administration > Users and roles)." % (what, action, module))


def _allowed_projects(c, u):
    try:
        import api_workspace as W
        return W.allowed_projects(c, u) if u else None
    except Exception:
        return None


def check_project(c, u, pid):
    allow = _allowed_projects(c, u)
    if allow is not None and int(pid) not in allow:
        raise ApiError("PROJECT_DENIED: you are not assigned to this project.")


def _pid(a):
    p = a.get("project_id")
    if p in (None, ""):
        raise ApiError("Choose a project first.")
    return int(p)


def _uname(c, uid):
    return val(c, "SELECT COALESCE(name, username) FROM users WHERE id=?", (uid,), None) if uid else None


def log(c, u, dpr_id, action, frm=None, to=None, comment=None):
    ins(c, "udpr_log", {"dpr_id": dpr_id, "action": action, "from_status": frm, "to_status": to,
                        "user_id": (u or {}).get("id"), "user_name": (u or {}).get("name") or (u or {}).get("username"),
                        "comment": comment, "ts": now()})


def head(c, dpr_id):
    return q1(c, "SELECT * FROM udpr_head WHERE dpr_id=?", (dpr_id,))


def ensure_head(c, d):
    h = head(c, d["id"])
    if h:
        return h
    vers = [x["version_id"] for x in current_templates(c, d["project_id"])]
    c.execute("INSERT INTO udpr_head(dpr_id, tpl_versions, created_at, updated_at) VALUES(?,?,?,?)",
              (d["id"], json.dumps(vers), now(), now()))
    return head(c, d["id"])


def fronts(c, pid, active_only=False):
    return q(c, "SELECT f.*, p.name party FROM udpr_fronts f LEFT JOIN parties p ON p.id=f.party_id WHERE f.project_id=?" +
             (" AND f.active=1" if active_only else "") + " ORDER BY f.kind DESC, f.sort, f.code, f.id", (pid,))


def scope_qty(b):
    """Approved scope of a BOQ item: the revised quantity (approved variations are added to it), else the contract."""
    if not b:
        return None
    return b["revised_qty"] if b["revised_qty"] is not None else b["qty"]


# ───────────────────────────── templates ─────────────────────────────
def project_cfg(c, pid):
    r = q1(c, "SELECT * FROM udpr_project WHERE project_id=?", (pid,))
    cfg = {"project_id": pid, "templates": None, "hidden": [], "sections": {}, "progress_basis": "reported",
           "basis_from": None, "scope_tol": _f(setting(c, "udpr_scope_tol")), "saved": bool(r)}
    if r:
        cfg.update({"templates": _j(r["templates"], None), "hidden": _j(r["hidden"], []) or [],
                    "sections": _j(r["sections"], {}) or {}, "progress_basis": r["progress_basis"] or "reported",
                    "basis_from": r["basis_from"], "scope_tol": r["scope_tol"] if r["scope_tol"] is not None else cfg["scope_tol"]})
    if cfg["templates"] is None:
        cfg["templates"] = suggested_templates(c, pid)
    core_sec = {k: bool(on) for k, _l, on in CORE_SECTIONS}
    core_sec.update({k: bool(v) for k, v in (cfg["sections"] or {}).items() if k in core_sec})
    cfg["sections"] = core_sec
    return cfg


def suggested_templates(c, pid):
    p = q1(c, "SELECT * FROM projects WHERE id=?", (pid,)) or {}
    words = " ".join(str(p.get(k) or "") for k in ("project_type", "name", "code")).lower()
    ids = []
    basic = val(c, "SELECT id FROM udpr_templates WHERE code='BASIC' AND system=1", (), None)
    if basic:
        ids.append(basic)
    for w, code in T.SUGGEST:
        if w in words:
            t = val(c, "SELECT id FROM udpr_templates WHERE code=? AND system=1 AND active=1", (code,), None)
            if t and t not in ids:
                ids.append(t)
            break
    return ids


def current_templates(c, pid):
    out = []
    for tid in project_cfg(c, pid)["templates"] or []:
        t = q1(c, "SELECT * FROM udpr_templates WHERE id=? AND active=1", (int(tid),))
        if not t or not t["current_version_id"]:
            continue
        v = q1(c, "SELECT * FROM udpr_tpl_versions WHERE id=?", (t["current_version_id"],))
        if v:
            out.append({"template_id": t["id"], "version_id": v["id"], "version_no": v["version_no"], "code": t["code"],
                        "name": t["name"], "definition": _j(v["definition"], {"sections": []})})
    return out


def templates_for_dpr(c, d):
    h = head(c, d["id"]) if d.get("id") else None
    vers = _j(h["tpl_versions"], None) if h else None
    if vers is None:
        return current_templates(c, d["project_id"])
    out = []
    for vid in vers:
        v = q1(c, "SELECT v.*, t.code, t.name FROM udpr_tpl_versions v JOIN udpr_templates t ON t.id=v.template_id WHERE v.id=?",
               (int(vid),))
        if v:
            out.append({"template_id": v["template_id"], "version_id": v["id"], "version_no": v["version_no"],
                        "code": v["code"], "name": v["name"], "definition": _j(v["definition"], {"sections": []})})
    return out


def merged_sections(tpls, hidden=()):
    """Sections of all templates in force, hidden sections and fields removed (per project), keys unique."""
    hid = set(hidden or ())
    out, seen = [], set()
    for t in tpls:
        for s in (t["definition"] or {}).get("sections") or []:
            if s.get("key") in seen or s.get("key") in hid or s.get("active") is False:
                continue
            seen.add(s["key"])
            s2 = dict(s)
            s2["template"] = t["code"]
            s2["template_name"] = t["name"]
            s2["version_no"] = t["version_no"]
            s2["fields"] = [f for f in s.get("fields") or [] if "%s.%s" % (s["key"], f.get("key")) not in hid
                            and f.get("active") is not False]
            out.append(s2)
    return out


def validate_definition(d):
    if not isinstance(d, dict) or not isinstance(d.get("sections"), list):
        raise ApiError("The template must have a list of sections.")
    keys = set()
    for s in d["sections"]:
        if not KEY_RE.match(str(s.get("key") or "")):
            raise ApiError("Section '%s': the internal name must start with a letter and use a-z, 0-9 and _ (max 40)." %
                           (s.get("label") or s.get("key") or "?"))
        if s["key"] in keys:
            raise ApiError("Two sections use the internal name '%s'." % s["key"])
        keys.add(s["key"])
        if s.get("kind") not in SECTION_KINDS:
            raise ApiError("Section '%s': choose fields, table or work-row columns." % s.get("label"))
        if not (s.get("label") or "").strip():
            raise ApiError("Section '%s' needs a label." % s["key"])
        fk = set()
        for f in s.get("fields") or []:
            if not KEY_RE.match(str(f.get("key") or "")):
                raise ApiError("%s: field '%s' needs an internal name (a-z, 0-9, _)." % (s["label"], f.get("label") or "?"))
            if f["key"] in fk:
                raise ApiError("%s: two fields use the internal name '%s'." % (s["label"], f["key"]))
            fk.add(f["key"])
            if f.get("type") not in TYPE_KEYS:
                raise ApiError("%s / %s: unknown field type '%s'." % (s["label"], f.get("label"), f.get("type")))
            if not (f.get("label") or "").strip():
                raise ApiError("%s: field '%s' needs a label." % (s["label"], f["key"]))
            if f["type"] in ("select", "multiselect") and not [o for o in f.get("options") or [] if str(o).strip()]:
                raise ApiError("%s / %s: a dropdown needs its options." % (s["label"], f["label"]))
            for k in ("min", "max"):
                if f.get(k) not in (None, "") and not isinstance(f.get(k), (int, float)):
                    try:
                        f[k] = float(f[k])
                    except (TypeError, ValueError):
                        raise ApiError("%s / %s: %s must be a number." % (s["label"], f["label"], k))
            si = f.get("show_if")
            if si and (not isinstance(si, dict) or si.get("op") not in ("eq", "ne", "in", "filled", "empty", "gt", "lt")):
                raise ApiError("%s / %s: the condition is not valid." % (s["label"], f["label"]))
    return d


def visible(f, rec):
    si = f.get("show_if")
    if not si:
        return True
    v = rec.get(si.get("field"))
    op, want = si.get("op"), si.get("value")
    if op == "filled":
        return v not in (None, "", [], "No", "0")
    if op == "empty":
        return v in (None, "", [])
    if op == "eq":
        return str(v) == str(want)
    if op == "ne":
        return str(v) != str(want)
    if op == "in":
        opts = want if isinstance(want, list) else [x.strip() for x in str(want or "").split(",")]
        return str(v) in [str(x) for x in opts]
    try:
        return (float(v) > float(want)) if op == "gt" else (float(v) < float(want))
    except (TypeError, ValueError):
        return False


def clean_value(c, f, v, pid, where):
    """Validate one value against its field definition and return it as stored (text), or None when blank."""
    t, lab = f.get("type"), "%s: %s" % (where, f.get("label"))
    if v is None or v == "" or v == []:
        return None
    if t in NUMERIC:
        try:
            x = float(str(v).replace(",", ""))
        except ValueError:
            raise ApiError("%s must be a number." % lab)
        if t == "int" and abs(x - round(x)) > EPS:
            raise ApiError("%s must be a whole number." % lab)
        lo = f.get("min")
        hi = f.get("max")
        if t == "percent" and hi in (None, ""):
            hi = 100
        if lo not in (None, "") and x < float(lo) - EPS:
            raise ApiError("%s cannot be below %s." % (lab, lo))
        if hi not in (None, "") and x > float(hi) + EPS:
            raise ApiError("%s cannot be above %s." % (lab, hi))
        return str(int(round(x))) if t == "int" else repr(round(x, 6)).rstrip("0").rstrip(".") if "." in repr(round(x, 6)) else str(x)
    if t == "date":
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", str(v)):
            raise ApiError("%s: date as YYYY-MM-DD." % lab)
        return str(v)
    if t == "time":
        if not re.match(r"^\d{1,2}:\d{2}$", str(v)):
            raise ApiError("%s: time as HH:MM." % lab)
        return str(v)
    if t == "datetime":
        if not re.match(r"^\d{4}-\d{2}-\d{2}[T ]\d{1,2}:\d{2}", str(v)):
            raise ApiError("%s: date and time as YYYY-MM-DD HH:MM." % lab)
        return str(v).replace(" ", "T")[:16]
    if t == "select":
        if str(v) not in [str(o) for o in f.get("options") or []]:
            raise ApiError("%s must be one of: %s" % (lab, ", ".join(str(o) for o in f.get("options") or [] if o)))
        return str(v)
    if t == "multiselect":
        vals = v if isinstance(v, list) else _j(v, None) if str(v).startswith("[") else [x.strip() for x in str(v).split(",") if x.strip()]
        bad = [x for x in vals if str(x) not in [str(o) for o in f.get("options") or []]]
        if bad:
            raise ApiError("%s: '%s' is not an option." % (lab, bad[0]))
        return json.dumps([str(x) for x in vals]) if vals else None
    if t in ("checkbox", "yesno"):
        s = str(v).strip().lower()
        if s in ("1", "true", "yes", "y", "on"):
            return "Yes"
        if s in ("0", "false", "no", "n", "off"):
            return "No"
        raise ApiError("%s must be Yes or No." % lab)
    if t in REF_TABLE:
        tbl, by_project = REF_TABLE[t]
        rid = _int(v)
        if not rid:
            raise ApiError("%s: choose from the list." % lab)
        r = q1(c, "SELECT * FROM %s WHERE id=?" % tbl, (rid,))
        if not r:
            raise ApiError("%s: the record chosen no longer exists." % lab)
        if by_project and r.get("project_id") not in (None, pid):
            raise ApiError("%s belongs to another project." % lab)
        return str(rid)
    s = str(v).strip()
    if len(s) > (8000 if t == "longtext" else 500):
        raise ApiError("%s is too long." % lab)
    return s


def can_edit_field(u, f):
    roles = f.get("edit_roles") or []
    return not roles or u.get("role") in roles or u.get("role") == "admin"


# ───────────────────────────── wrappers on the DPR engine ─────────────────────────────
KEEP_RULE = {"work": lambda ln: _int(ln.get("activity_id")) or _int(ln.get("boq_item_id")),
             "labour": lambda ln: _int(ln.get("trade_id")) and _f(ln.get("count")),
             "equipment": lambda ln: _int(ln.get("equipment_id"))}
PART_TABLE = {"work": "dpr_work", "labour": "dpr_labour", "equipment": "dpr_equipment"}
MATCH = {"work": ("activity_id", "boq_item_id"), "labour": ("trade_id", "activity_id"), "equipment": ("equipment_id",)}


def _extras_of(c, part, line_id):
    if part == "work":
        r = q1(c, "SELECT * FROM udpr_work WHERE work_id=?", (line_id,))
        return {k: r[k] for k in r if k not in ("work_id", "dpr_id")} if r else None
    r = q1(c, "SELECT * FROM udpr_lx WHERE part=? AND line_id=?", (part, line_id))
    return {"front_id": r["front_id"], "vals": r["vals"]} if r else None


def _put_extras(c, part, line_id, dpr_id, x):
    if part == "work":
        c.execute("DELETE FROM udpr_work WHERE work_id=?", (line_id,))
        if x:
            row = {k: x.get(k) for k in ("front_id", "package_id", "accepted_qty", "accepted_by", "accepted_at", "accept_note",
                                         "over_scope_by", "over_scope_reason", "delay_reason", "vals")}
            row.update(work_id=line_id, dpr_id=dpr_id)
            ins(c, "udpr_work", row)
        return
    c.execute("DELETE FROM udpr_lx WHERE part=? AND line_id=?", (part, line_id))
    if x:
        ins(c, "udpr_lx", {"part": part, "line_id": line_id, "dpr_id": dpr_id, "front_id": x.get("front_id"), "vals": x.get("vals")})


def _ux_from_payload(part, ln, old):
    """Extras sent with a line from the 2.25 form (key _ux); accepted quantities are never set through a save."""
    ux = ln.get("_ux")
    if not isinstance(ux, dict):
        return None
    x = dict(old or {})
    x["front_id"] = _int(ux.get("front_id"))
    if part == "work":
        x["package_id"] = _int(ux.get("package_id"))
        x["delay_reason"] = (ux.get("delay_reason") or "").strip()[:300] or None
    vals = ux.get("vals")
    x["vals"] = json.dumps(vals) if isinstance(vals, dict) and vals else None
    return x


def _dpr_save_w(orig):
    def dpr_save25(c, u, a):
        h = a.get("header") or {}
        rid = _int(h.get("id"))
        old = {}
        if rid:
            d0 = get(c, "dpr", rid, "DPR")
            hh = head(c, rid)
            if hh and hh["locked_at"]:
                raise ApiError("This DPR is locked.")
            for part, t in PART_TABLE.items():
                old[part] = [(r, _extras_of(c, part, r["id"])) for r in q(c, "SELECT * FROM %s WHERE dpr_id=? ORDER BY id" % t, (rid,))]
        r = orig(c, u, a)
        did = r["id"]
        d = get(c, "dpr", did)
        ensure_head(c, d)
        for part, t in PART_TABLE.items():
            if part not in a and rid:
                continue
            new = q(c, "SELECT * FROM %s WHERE dpr_id=? ORDER BY id" % t, (did,))
            kept = [ln for ln in (a.get(part) or []) if KEEP_RULE[part](ln)]
            olds = old.get(part) or []
            for o, _x in olds:
                _put_extras(c, part, o["id"], did, None)
            used = set()
            for i, nr in enumerate(new):
                ln = kept[i] if i < len(kept) and len(kept) == len(new) else {}
                prev = None
                # the same line as before (same position and same activity / trade / machine), else the first unused match
                cands = ([i] if i < len(olds) else []) + list(range(len(olds)))
                for j in cands:
                    if j in used:
                        continue
                    o, ox = olds[j]
                    if all((o.get(k) or None) == (nr.get(k) or None) for k in MATCH[part]):
                        prev = ox
                        used.add(j)
                        break
                x = _ux_from_payload(part, ln, prev) if ln else None
                if x is None:
                    x = prev
                if part == "work" and x and prev and x.get("accepted_qty") is not None:
                    o_line = next((o for o, ox in olds if ox is prev), None)
                    if o_line and abs((o_line.get("actual_qty") or 0) - (nr.get("actual_qty") or 0)) > EPS:
                        x["accept_note"] = ((x.get("accept_note") or "") + " [site quantity changed after acceptance]").strip()
                if x and any(x.get(k) not in (None, "", "null") for k in x):
                    _put_extras(c, part, nr["id"], did, x)
        c.execute("UPDATE udpr_head SET updated_at=? WHERE dpr_id=?", (now(), did))
        if not rid:
            log(c, u, did, "created", None, "draft")
        return r
    return dpr_save25


def required_missing(c, d):
    """Required fields (visible ones only) still empty: checked when the DPR is submitted, not on a draft save."""
    cfg = project_cfg(c, d["project_id"])
    secs = merged_sections(templates_for_dpr(c, d), cfg["hidden"])
    vals = {r["key"]: r["value"] for r in q(c, "SELECT key, value FROM udpr_values WHERE dpr_id=?", (d["id"],))}
    miss = []
    for s in secs:
        if s["kind"] == "fields":
            rec = {f["key"]: vals.get("%s.%s" % (s["key"], f["key"])) for f in s["fields"]}
            for f in s["fields"]:
                if f.get("required") and visible(f, rec) and rec.get(f["key"]) in (None, ""):
                    miss.append("%s: %s" % (s["label"], f["label"]))
        elif s["kind"] == "table":
            for r in q(c, "SELECT * FROM udpr_rows WHERE dpr_id=? AND section=? ORDER BY row_no", (d["id"], s["key"])):
                rec = _j(r["data"], {}) or {}
                for f in s["fields"]:
                    if f.get("required") and visible(f, rec) and rec.get(f["key"]) in (None, ""):
                        miss.append("%s row %s: %s" % (s["label"], r["row_no"], f["label"]))
        elif s["kind"] == "line":
            for w in q(c, "SELECT w.id, x.vals FROM dpr_work w LEFT JOIN udpr_work x ON x.work_id=w.id WHERE w.dpr_id=? ORDER BY w.id", (d["id"],)):
                rec = _j(w["vals"], {}) or {}
                for f in s["fields"]:
                    if f.get("required") and visible(f, rec) and rec.get(f["key"]) in (None, ""):
                        miss.append("Work row %s: %s" % (w["id"], f["label"]))
    return miss


def _dpr_submit_w(orig):
    def dpr_submit25(c, u, a):
        d = get(c, "dpr", int(a["id"]), "DPR")
        miss = required_missing(c, d) if head(c, d["id"]) else []
        if miss:
            raise ApiError("Fill the required fields before submitting: " + "; ".join(miss[:8]) + (" ..." if len(miss) > 8 else ""))
        r = orig(c, u, a)
        ensure_head(c, d)
        c.execute("UPDATE udpr_head SET submitted_at=?, returned_at=NULL, return_comment=NULL WHERE dpr_id=?", (now(), d["id"]))
        log(c, u, d["id"], "submitted", d["status"], "submitted")
        return r
    return dpr_submit25


def _dpr_check_w(orig):
    def dpr_check25(c, u, a):
        d = get(c, "dpr", int(a["id"]), "DPR")
        r = orig(c, u, a)
        ensure_head(c, d)
        c.execute("UPDATE udpr_head SET checked_at=?, checked_name=COALESCE(checked_name, ?) WHERE dpr_id=?",
                  (now(), u.get("name") or u.get("username"), d["id"]))
        log(c, u, d["id"], "checked", d["status"], "checked")
        return r
    return dpr_check25


def _dpr_return_w(orig):
    def dpr_return25(c, u, a):
        d = get(c, "dpr", int(a["id"]), "DPR")
        r = orig(c, u, a)
        ensure_head(c, d)
        c.execute("UPDATE udpr_head SET returned_at=?, returned_by=?, return_comment=? WHERE dpr_id=?",
                  (now(), u["id"], (a.get("reason") or "").strip() or None, d["id"]))
        log(c, u, d["id"], "returned", d["status"], "draft", a.get("reason"))
        return r
    return dpr_return25


def _dpr_approve_w(orig):
    def dpr_approve25(c, u, a):
        d = get(c, "dpr", int(a["id"]), "DPR")
        r = orig(c, u, a)
        h = ensure_head(c, d)
        rev = (h["revision"] or 0) + 1
        c.execute("UPDATE udpr_head SET revision=?, approved_name=COALESCE(approved_name, ?) WHERE dpr_id=?",
                  (rev, u.get("name") or u.get("username"), d["id"]))
        snapshot(c, u, d["id"], rev, "approved", "Approved")
        log(c, u, d["id"], "approved", d["status"], "approved")
        return r
    return dpr_approve25


def _dpr_reopen_w(orig):
    def dpr_reopen25(c, u, a):
        d = get(c, "dpr", int(a["id"]), "DPR")
        h = head(c, d["id"])
        if h and h["locked_at"]:
            raise ApiError("This DPR is locked (since %s). Unlock it first; unlocking is logged." % h["locked_at"][:16])
        if h:
            snapshot(c, u, d["id"], h["revision"] or 0, "before_amendment", a.get("reason"))
        r = orig(c, u, a)
        ensure_head(c, d)
        log(c, u, d["id"], "reopened for amendment", "approved", "draft", a.get("reason"))
        return r
    return dpr_reopen25


def snapshot(c, u, dpr_id, rev, kind, reason):
    d = inv.FUNCS["dpr.get"][0](c, u, {"id": dpr_id})
    data = {"dpr": d, "head": head(c, dpr_id),
            "work_x": q(c, "SELECT * FROM udpr_work WHERE dpr_id=?", (dpr_id,)),
            "lines_x": q(c, "SELECT * FROM udpr_lx WHERE dpr_id=?", (dpr_id,)),
            "values": q(c, "SELECT key, value FROM udpr_values WHERE dpr_id=?", (dpr_id,)),
            "rows": q(c, "SELECT section, row_no, front_id, data FROM udpr_rows WHERE dpr_id=? ORDER BY section, row_no", (dpr_id,)),
            "issues": q(c, "SELECT * FROM udpr_issue_days WHERE dpr_id=?", (dpr_id,))}
    ins(c, "udpr_revisions", {"dpr_id": dpr_id, "rev_no": rev, "kind": kind, "reason": reason,
                              "snapshot": json.dumps(data, default=str), "user_id": (u or {}).get("id"), "ts": now()})


def _recompute_w(orig):
    def recompute_progress25(c, project_id):
        orig(c, project_id)
        try:
            cfg = project_cfg(c, project_id)
        except Exception:
            return
        if cfg["progress_basis"] != "accepted":
            return
        frm = cfg["basis_from"] or "0000-00-00"
        expr = ("SUM(CASE WHEN d.date>=? THEN COALESCE(x.accepted_qty,0) ELSE w.actual_qty END)")
        for a_ in q(c, "SELECT id, planned_qty FROM activities WHERE project_id=?", (project_id,)):
            agg = q1(c, "SELECT " + expr + " q, MIN(d.date) s, MAX(d.date) f FROM dpr_work w JOIN dpr d ON d.id=w.dpr_id "
                        "LEFT JOIN udpr_work x ON x.work_id=w.id WHERE d.status='approved' AND w.activity_id=? AND "
                        "(CASE WHEN d.date>=? THEN COALESCE(x.accepted_qty,0) ELSE w.actual_qty END)>0", (frm, a_["id"], frm))
            qty = r4(agg["q"] or 0)
            done = a_["planned_qty"] and qty + EPS >= a_["planned_qty"]
            upd(c, "activities", a_["id"], {"actual_qty": qty, "actual_start": agg["s"], "actual_finish": agg["f"] if done else None})
        for b in q(c, "SELECT id FROM boq_items WHERE project_id=?", (project_id,)):
            qty = val(c, "SELECT " + expr + " FROM dpr_work w JOIN dpr d ON d.id=w.dpr_id LEFT JOIN udpr_work x ON "
                         "x.work_id=w.id WHERE d.status='approved' AND w.boq_item_id=?", (frm, b["id"]))
            if qty or val(c, "SELECT COUNT(*) FROM dpr_work WHERE boq_item_id=?", (b["id"],)):
                upd(c, "boq_items", b["id"], {"executed_qty": r4(qty)})
    recompute_progress25._bco225 = True
    return recompute_progress25


FLAGS = ("_bco219", "_bco220", "_bco221", "_bco223", "_bco224")


def _wrap(name, factory):
    cur = inv.FUNCS.get(name)
    if not cur or getattr(cur[0], "_bco225", False):
        return
    w = factory(cur[0])
    w._bco225 = True
    for flag in FLAGS:
        if getattr(cur[0], flag, False):
            setattr(w, flag, True)
    w.__name__ = getattr(cur[0], "__name__", name)
    inv.FUNCS[name] = (w, cur[1], cur[2], cur[3])


def _install():
    _wrap("dpr.save", _dpr_save_w)
    _wrap("dpr.submit", _dpr_submit_w)
    _wrap("dpr.check", _dpr_check_w)
    _wrap("dpr.return", _dpr_return_w)
    _wrap("dpr.approve", _dpr_approve_w)
    _wrap("dpr.reopen", _dpr_reopen_w)
    try:
        import api_project as P
        if not getattr(P.recompute_progress, "_bco225", False):
            P.recompute_progress = _recompute_w(P.recompute_progress)
    except Exception:
        pass


def auto_lock(c, pid=None):
    days = int(_f(setting(c, "udpr_autolock_days")))
    if days <= 0:
        return 0
    cut = (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")
    n = 0
    for d in q(c, "SELECT d.* FROM dpr d LEFT JOIN udpr_head h ON h.dpr_id=d.id WHERE d.status='approved' AND h.locked_at IS NULL "
                  "AND d.approved_at IS NOT NULL AND d.approved_at<?" + (" AND d.project_id=%d" % int(pid) if pid else ""), (cut,)):
        ensure_head(c, d)
        c.execute("UPDATE udpr_head SET locked_at=?, locked_by=NULL WHERE dpr_id=?", (now(), d["id"]))
        log(c, {"name": "BuildCore (automatic, %d days after approval)" % days}, d["id"], "locked", "approved", "approved")
        n += 1
    return n


# ───────────────────────────── quantities ─────────────────────────────
def _key_of(w):
    return ("b", w["boq_item_id"]) if w.get("boq_item_id") else ("a", w.get("activity_id"))


def line_figures(c, d, works):
    """Per work line: approved scope, previous accepted cumulative, today's accepted, current cumulative, balance, %.
    Previous = all accepted quantities on DPRs before this one (earlier date, or same date and an earlier DPR)."""
    out = {}
    for w in works:
        k = _key_of(w)
        col = "boq_item_id" if k[0] == "b" else "activity_id"
        if not k[1]:
            continue
        b = q1(c, "SELECT * FROM boq_items WHERE id=?", (w["boq_item_id"],)) if w.get("boq_item_id") else None
        a_ = q1(c, "SELECT * FROM activities WHERE id=?", (w["activity_id"],)) if w.get("activity_id") else None
        if b:
            scope, basis, unit = scope_qty(b), "BOQ approved quantity", b["unit"]
        elif a_ and (a_["planned_qty"] or 0) > 0:
            scope, basis, unit = a_["planned_qty"], "activity planned quantity", a_["unit"]
        else:
            scope, basis, unit = None, "milestone / no quantity", (a_ or {}).get("unit")
        cond = ("x2.dpr_id IN (SELECT id FROM dpr WHERE project_id=? AND status NOT IN ('rejected') AND "
                "(date<? OR (date=? AND id<?)))")
        prev_acc = val(c, "SELECT SUM(x2.accepted_qty) FROM udpr_work x2 JOIN dpr_work w2 ON w2.id=x2.work_id WHERE w2.%s=? AND %s"
                       % (col, cond), (k[1], d["project_id"], d["date"], d["date"], d["id"]))
        prev_rep = val(c, "SELECT SUM(w2.actual_qty) FROM dpr_work w2 JOIN dpr d2 ON d2.id=w2.dpr_id WHERE w2.%s=? AND d2.project_id=? "
                          "AND d2.status IN ('submitted','checked','approved') AND (d2.date<? OR (d2.date=? AND d2.id<?))" % col,
                       (k[1], d["project_id"], d["date"], d["date"], d["id"]))
        x = q1(c, "SELECT * FROM udpr_work WHERE work_id=?", (w["id"],)) or {}
        acc = x.get("accepted_qty")
        cur = r4((prev_acc or 0) + (acc or 0))
        out[w["id"]] = {"scope": r4(scope) if scope is not None else None, "scope_basis": basis, "unit": unit,
                        "prev_accepted": r4(prev_acc), "accepted": acc, "current_accepted": cur,
                        "balance": r4(scope - cur) if scope is not None else None,
                        "progress_pct": r2(cur / scope * 100) if scope else None,
                        "prev_reported": r4(prev_rep), "reported": w.get("actual_qty"),
                        "current_reported": r4((prev_rep or 0) + (w.get("actual_qty") or 0)),
                        "reported_over_scope": bool(scope is not None and (prev_rep or 0) + (w.get("actual_qty") or 0) > scope + EPS),
                        "accepted_by": _uname(c, x.get("accepted_by")), "accepted_at": x.get("accepted_at"),
                        "accept_note": x.get("accept_note"), "over_scope_reason": x.get("over_scope_reason")}
    return out


def accepted_total(c, pid, col, key, exclude_line=None):
    return val(c, "SELECT SUM(x.accepted_qty) FROM udpr_work x JOIN dpr_work w ON w.id=x.work_id JOIN dpr d ON d.id=w.dpr_id "
                  "WHERE d.project_id=? AND d.status<>'rejected' AND w.%s=? AND w.id<>?" % col, (pid, key, exclude_line or 0))


@api("udpr.accept", "project", "view")
def udpr_accept(c, u, a):
    """Accept (check) the site's reported quantities for contractual measurement. Needs commercial edit (QS) or the
    DPR approve right; beyond the approved scope only with an approver's override and a reason."""
    if not (core.can(u, "commercial", "edit") or right(c, u, "dpr", "approve")):
        raise ApiError("Accepting quantities needs the QS right (commercial edit) or the DPR approve right.")
    d = get(c, "dpr", int(a["dpr_id"]), "DPR")
    check_project(c, u, d["project_id"])
    h = ensure_head(c, d)
    if d["status"] not in ("submitted", "checked", "approved"):
        raise ApiError("Quantities are accepted after the DPR is submitted (this one is %s)." % d["status"])
    if h["locked_at"]:
        raise ApiError("This DPR is locked; its accepted quantities can no longer change.")
    cfg = project_cfg(c, d["project_id"])
    tol = _f(cfg["scope_tol"]) / 100.0
    override = (a.get("override_reason") or "").strip()
    changed = []
    for ln in a.get("lines") or []:
        wid = _int(ln.get("work_id"))
        w = q1(c, "SELECT * FROM dpr_work WHERE id=? AND dpr_id=?", (wid, d["id"]))
        if not w:
            raise ApiError("Work line %s is not on this DPR." % wid)
        raw = ln.get("accepted_qty")
        x = q1(c, "SELECT * FROM udpr_work WHERE work_id=?", (wid,))
        if raw in (None, ""):
            new = None
        else:
            try:
                new = r4(float(str(raw).replace(",", "")))
            except ValueError:
                raise ApiError("Accepted quantity must be a number.")
        note = (ln.get("note") or "").strip()
        if new is not None and new < 0 and not note:
            raise ApiError("A negative accepted quantity is a correction: write why in the note.")
        old = x["accepted_qty"] if x else None
        if (old is None and new is None) or (old is not None and new is not None and abs(old - new) < EPS and note == (x["accept_note"] or "")):
            continue
        col, key = ("boq_item_id", w["boq_item_id"]) if w["boq_item_id"] else ("activity_id", w["activity_id"])
        b = q1(c, "SELECT * FROM boq_items WHERE id=?", (w["boq_item_id"],)) if w["boq_item_id"] else None
        a_ = q1(c, "SELECT * FROM activities WHERE id=?", (w["activity_id"],)) if w["activity_id"] else None
        scope = scope_qty(b) if b else ((a_ or {}).get("planned_qty") or None)
        others = accepted_total(c, d["project_id"], col, key, wid)
        over = None
        if new is not None and others + new < -EPS:
            raise ApiError("%s: the accepted cumulative cannot go below zero." % ((b or a_ or {}).get("code") or "Line"))
        if new is not None and scope is not None and others + new > scope * (1 + tol) + EPS:
            label = (b or {}).get("code") or (a_ or {}).get("code") or "Line"
            if not override:
                raise ApiError("%s: accepted cumulative %s would exceed the approved scope %s%s. Record a variation, or an approver "
                               "can override with a reason." % (label, r4(others + new), r4(scope), " (+%s%% tolerance)" % cfg["scope_tol"] if tol else ""))
            if not (right(c, u, "dpr", "approve") or core.can(u, "commercial", "approve")):
                raise ApiError("%s is beyond the approved scope; only someone who can approve (commercial or DPR) may override." % label)
            over = override
        row = {"accepted_qty": new, "accepted_by": u["id"] if new is not None else None,
               "accepted_at": now() if new is not None else None, "accept_note": note or None,
               "over_scope_by": u["id"] if over else None, "over_scope_reason": over}
        if x:
            c.execute("UPDATE udpr_work SET accepted_qty=?, accepted_by=?, accepted_at=?, accept_note=?, over_scope_by=?, "
                      "over_scope_reason=? WHERE work_id=?", (row["accepted_qty"], row["accepted_by"], row["accepted_at"],
                                                              row["accept_note"], row["over_scope_by"], row["over_scope_reason"], wid))
        else:
            row.update(work_id=wid, dpr_id=d["id"])
            ins(c, "udpr_work", row)
        changed.append({"work_id": wid, "before": old, "after": new, "over_scope": over})
    if changed:
        audit(c, u, "accept_qty", "dpr", d["id"], {"lines": changed})
        log(c, u, d["id"], "quantities accepted", d["status"], d["status"],
            "; ".join("line %s: %s -> %s" % (x["work_id"], x["before"], x["after"]) for x in changed)[:900])
        if cfg["progress_basis"] == "accepted" and d["status"] == "approved":
            import api_project as P
            P.recompute_progress(c, d["project_id"])
    return {"changed": len(changed)}


# ───────────────────────────── the form ─────────────────────────────
@api("udpr.meta", "project", "view")
def udpr_meta(c, u, a):
    pid = _pid(a)
    check_project(c, u, pid)
    auto_lock(c, pid)
    cfg = project_cfg(c, pid)
    tpls = current_templates(c, pid)
    p = q1(c, "SELECT id, code, name, client, location, project_type FROM projects WHERE id=?", (pid,))
    return {"version": VERSION, "project": p, "cfg": cfg, "templates": [{k: t[k] for k in ("template_id", "version_id", "version_no", "code", "name")} for t in tpls],
            "sections": merged_sections(tpls, cfg["hidden"]), "core_sections": [{"key": k, "label": l} for k, l, _o in CORE_SECTIONS],
            "fronts": fronts(c, pid, True), "contracts": q(c, "SELECT id, ref_no, title, party_id FROM contracts WHERE project_id=?", (pid,)),
            "field_types": [{"key": k, "label": l} for k, l in FIELD_TYPES], "issue_categories": ISSUE_CATEGORIES,
            "status_label": STATUS_LABEL, "form": setting(c, "udpr_form") or "smart",
            "signatures": (setting(c, "udpr_signatures") or DEFAULTS["udpr_signatures"]).split("|"),
            "report_header": setting(c, "udpr_report_header") or "",
            "company": setting(c, "company_name") or "",
            "open_issues": open_issues(c, pid),
            "settings": {k: setting(c, k) if setting(c, k) is not None else v for k, v in DEFAULTS.items()},
            "rights": {"view": right(c, u, "dpr", "view"), "create": right(c, u, "dpr", "create") and core.can(u, "project", "edit"),
                       "edit": core.can(u, "project", "edit"), "approve": core.can(u, "project", "approve"),
                       "accept": core.can(u, "commercial", "edit") or right(c, u, "dpr", "approve"),
                       "override": right(c, u, "dpr", "approve") or core.can(u, "commercial", "approve"),
                       "lock": right(c, u, "dpr", "approve"), "unlock": u.get("role") == "admin" or right(c, u, "dpr", "approve") and core.can(u, "project", "approve"),
                       "setup": right(c, u, "dpr_setup", "edit"), "sensitive": right(c, u, "hse_private", "view"),
                       "export": right(c, u, "dpr", "export"), "reopen": core.can(u, "admin", "edit")}}


def open_issues(c, pid):
    return q(c, "SELECT i.id, i.no, i.title, i.status, x.category, x.front_id, x.days_reported, x.first_date FROM fld_issues i "
                "LEFT JOIN udpr_issue_x x ON x.issue_id=i.id WHERE i.project_id=? AND i.status NOT IN ('closed','void') AND "
                "(i.type='site' OR x.issue_id IS NOT NULL) ORDER BY i.id DESC LIMIT 300", (pid,))


@api("udpr.get", "project", "view")
def udpr_get(c, u, a):
    d = inv.FUNCS["dpr.get"][0](c, u, {"id": int(a["id"])})
    check_project(c, u, d["project_id"])
    auto_lock(c, d["project_id"])
    h = head(c, d["id"]) or {}
    tpls = templates_for_dpr(c, d)
    cfg = project_cfg(c, d["project_id"])
    secs = merged_sections(tpls, cfg["hidden"])
    sens = right(c, u, "hse_private", "view")
    rows = {}
    hidden_rows = {}
    sensitive = {s["key"] for s in secs if s.get("sensitive")}
    for r in q(c, "SELECT * FROM udpr_rows WHERE dpr_id=? ORDER BY section, row_no", (d["id"],)):
        if r["section"] in sensitive and not sens:
            hidden_rows[r["section"]] = hidden_rows.get(r["section"], 0) + 1
            continue
        x = _j(r["data"], {}) or {}
        x["_id"] = r["id"]
        x["_front_id"] = r["front_id"]
        rows.setdefault(r["section"], []).append(x)
    wx = {r["work_id"]: r for r in q(c, "SELECT * FROM udpr_work WHERE dpr_id=?", (d["id"],))}
    for w in d["work"]:
        x = wx.get(w["id"]) or {}
        w["_ux"] = {"front_id": x.get("front_id"), "package_id": x.get("package_id"), "delay_reason": x.get("delay_reason"),
                    "vals": _j(x.get("vals"), {}) or {}}
    for part in ("labour", "equipment"):
        lx = {r["line_id"]: r for r in q(c, "SELECT * FROM udpr_lx WHERE part=? AND dpr_id=?", (part, d["id"]))}
        for ln in d[part]:
            x = lx.get(ln["id"]) or {}
            ln["_ux"] = {"front_id": x.get("front_id"), "vals": _j(x.get("vals"), {}) or {}}
    problems = q(c, "SELECT i.id issue_id, i.no, i.title, i.status, i.description, i.activity_id, i.assignee, i.due_date, "
                    "x.category, x.front_id, x.impact, x.mitigation, x.decision_required, x.claim_relevant, x.responsible_party, "
                    "x.first_date, x.days_reported, dd.hours, dd.note FROM udpr_issue_days dd JOIN fld_issues i ON i.id=dd.issue_id "
                    "LEFT JOIN udpr_issue_x x ON x.issue_id=i.id WHERE dd.dpr_id=? ORDER BY i.id", (d["id"],))
    status = d["status"]
    shown = "locked" if h.get("locked_at") else ("returned" if status == "draft" and h.get("returned_at") else status)
    inc = q(c, "SELECT id, no, kind, injury, days_lost, status, description, location FROM hs_incidents WHERE project_id=? AND date=?",
            (d["project_id"], d["date"]))
    if not sens:
        inc = [{"id": r["id"], "no": r["no"], "kind": r["kind"], "status": r["status"], "restricted": True} for r in inc]
    return {"dpr": d, "head": h, "status_shown": shown, "status_label": STATUS_LABEL.get(shown, shown),
            "templates": [{k: t[k] for k in ("template_id", "version_id", "version_no", "code", "name")} for t in tpls],
            "templates_outdated": [t["code"] for t in tpls if t["version_id"] not in
                                   [x["version_id"] for x in current_templates(c, d["project_id"])]],
            "sections": secs, "values": {r["key"]: r["value"] for r in q(c, "SELECT key, value FROM udpr_values WHERE dpr_id=?", (d["id"],))},
            "rows": rows, "rows_restricted": hidden_rows, "problems": problems, "figures": line_figures(c, d, d["work"]),
            "log": q(c, "SELECT * FROM udpr_log WHERE dpr_id=? ORDER BY id", (d["id"],)),
            "revisions": q(c, "SELECT id, rev_no, kind, reason, user_id, ts FROM udpr_revisions WHERE dpr_id=? ORDER BY id", (d["id"],)),
            "materials_day": materials_day(c, d["project_id"], d["date"]),
            "quality": {"tests": q(c, "SELECT * FROM qa_tests WHERE project_id=? AND (dpr_id=? OR sampled_date=? OR result_date=?)",
                                   (d["project_id"], d["id"], d["date"], d["date"])),
                        "ncrs": q(c, "SELECT * FROM ncrs WHERE project_id=? AND date=?", (d["project_id"], d["date"])),
                        "inspections": q(c, "SELECT id, no, title, result, failed, status FROM fld_inspections WHERE project_id=? AND date=?",
                                         (d["project_id"], d["date"]))},
            "incidents": inc, "sensitive_ok": sens}


def materials_day(c, pid, d):
    """Opening, received, issued and closing per material for the project on the day, from the stock ledger."""
    return q(c, "SELECT s.material_id, m.code, m.name, m.unit, "
                "ROUND(SUM(CASE WHEN s.date<? THEN s.qty_in-s.qty_out ELSE 0 END),4) opening, "
                "ROUND(SUM(CASE WHEN s.date=? THEN s.qty_in ELSE 0 END),4) received, "
                "ROUND(SUM(CASE WHEN s.date=? THEN s.qty_out ELSE 0 END),4) issued, "
                "ROUND(SUM(CASE WHEN s.date<=? THEN s.qty_in-s.qty_out ELSE 0 END),4) closing "
                "FROM stock_ledger s JOIN materials m ON m.id=s.material_id WHERE s.project_id=? AND s.date<=? "
                "GROUP BY s.material_id HAVING ABS(opening)>0.0001 OR received>0 OR issued>0 ORDER BY m.code",
             (d, d, d, d, pid, d))


@api("udpr.save", "project", "edit")
def udpr_save(c, u, a):
    """Save the whole Universal DPR: the core DPR (through the existing engine, so costing, logsheets and the 2.24 checks
    behave exactly as before) plus summary, fronts, project fields, repeating tables and the day's issues."""
    hd = a.get("header") or {}
    pid = _pid(hd)
    check_project(c, u, pid)
    rid = _int(hd.get("id"))
    tok = (a.get("client_token") or "").strip()[:80]
    if not rid:
        need(c, u, "dpr", "create", "create a DPR")
        if tok:
            dup = q1(c, "SELECT h.dpr_id, d.no FROM udpr_head h JOIN dpr d ON d.id=h.dpr_id WHERE h.client_token=? AND d.project_id=?", (tok, pid))
            if dup:
                return {"id": dup["dpr_id"], "no": dup["no"], "duplicate": True, "warnings": []}
    else:
        d0 = get(c, "dpr", rid, "DPR")
        if d0["project_id"] != pid:
            raise ApiError("This DPR belongs to another project.")
        if d0["status"] != "draft":
            raise ApiError("Only draft DPRs can be edited. This one is %s; approved reports change only through a logged amendment." % d0["status"])
    core_a = {"header": {k: hd.get(k) for k in ("id", "project_id", "date", "shift", "weather", "site_condition", "remarks",
                                               "rain_mm", "weather_lost_hours", "lost_day") if k in hd}}
    core_a["header"]["project_id"] = pid
    if rid:
        core_a["header"]["id"] = rid
    old = inv.FUNCS["dpr.get"][0](c, u, {"id": rid}) if rid else None
    for part in ("work", "labour", "equipment", "delays", "survey"):
        if part in a:
            core_a[part] = a[part]
        elif old is not None:
            core_a[part] = old.get(part) or []
            if part in ("labour", "equipment", "work"):
                for ln in core_a[part]:
                    ln.pop("_ux", None)
    if old is not None:
        for k in ("weather", "site_condition", "remarks", "rain_mm", "weather_lost_hours", "lost_day", "date", "shift"):
            if k not in core_a["header"]:
                core_a["header"][k] = old.get(k)
    secs_now = None
    r = inv.FUNCS["dpr.save"][0](c, u, core_a)
    did = r["id"]
    d = get(c, "dpr", did)
    h = ensure_head(c, d)
    # header extras and the executive summary
    hx = {}
    for k in ("temp_min", "temp_max", "humidity"):
        if k in hd:
            hx[k] = _f(hd[k], None) if hd[k] not in (None, "") else None
            if hx[k] is not None and k.startswith("temp") and not -60 <= hx[k] <= 60:
                raise ApiError("Temperature must be between -60 and 60 °C.")
    for k in ("conditions", "prepared_name", "checked_name", "approved_name"):
        if k in hd:
            hx[k] = (hd[k] or "").strip()[:200] or None
    for k in ("package_id", "front_id"):
        if k in hd:
            hx[k] = _int(hd[k])
            if hx[k] and not q1(c, "SELECT id FROM udpr_fronts WHERE id=? AND project_id=?", (hx[k], pid)):
                raise ApiError("That package / work front belongs to another project.")
    summ = a.get("summary") or {}
    for k in ("s_work", "s_achieve", "s_activities", "s_problems", "s_instructions", "s_decisions", "s_next"):
        if k in summ:
            hx[k] = (summ[k] or "").strip()[:8000] or None
    if tok and not rid:
        hx["client_token"] = tok
    if not h["prepared_name"] and "prepared_name" not in hx:
        hx["prepared_name"] = u.get("name") or u.get("username")
    if hx:
        sets = ", ".join("%s=?" % k for k in hx)
        c.execute("UPDATE udpr_head SET %s, updated_at=? WHERE dpr_id=?" % sets, list(hx.values()) + [now(), did])
    # project fields and repeating tables, validated against the template versions this DPR was created with
    cfg = project_cfg(c, pid)
    secs = merged_sections(templates_for_dpr(c, d), cfg["hidden"])
    sens = right(c, u, "hse_private", "view")
    if "values" in a:
        cur = {r_["key"]: r_["value"] for r_ in q(c, "SELECT key, value FROM udpr_values WHERE dpr_id=?", (did,))}
        vals = a.get("values") or {}
        for s in secs:
            if s["kind"] != "fields":
                continue
            rec = {f["key"]: vals.get("%s.%s" % (s["key"], f["key"])) for f in s["fields"]}
            for f in s["fields"]:
                k = "%s.%s" % (s["key"], f["key"])
                if k not in vals:
                    continue
                v = clean_value(c, f, vals[k], pid, s["label"]) if visible(f, rec) else None
                if not can_edit_field(u, f) and v != cur.get(k):
                    raise ApiError("%s: %s can only be changed by %s." % (s["label"], f["label"], ", ".join(f["edit_roles"])))
                c.execute("DELETE FROM udpr_values WHERE dpr_id=? AND key=?", (did, k))
                if v is not None:
                    c.execute("INSERT INTO udpr_values(dpr_id, key, value) VALUES(?,?,?)", (did, k, v))
    rowsin = a.get("rows")
    if isinstance(rowsin, dict):
        known = {s["key"] for s in secs if s["kind"] == "table"}
        bad = [k for k in rowsin if k not in known and rowsin.get(k)]
        if bad:
            raise ApiError("Section '%s' is not part of this project's DPR templates." % bad[0])
        for s in secs:
            if s["kind"] != "table" or s["key"] not in rowsin:
                continue
            keep_hidden = s.get("sensitive") and not sens
            existing = q(c, "SELECT * FROM udpr_rows WHERE dpr_id=? AND section=? ORDER BY row_no", (did, s["key"]))
            if keep_hidden:
                start = len(existing)   # cannot see the stored rows: new rows are added, stored rows stay as they are
            else:
                c.execute("DELETE FROM udpr_rows WHERE dpr_id=? AND section=?", (did, s["key"]))
                start = 0
            n = start
            for raw in rowsin[s["key"]] or []:
                if not isinstance(raw, dict):
                    continue
                if keep_hidden and raw.get("_id"):
                    continue
                rec = {f["key"]: raw.get(f["key"]) for f in s["fields"]}
                if all(v in (None, "", []) for v in rec.values()):
                    continue
                n += 1
                clean = {}
                for f in s["fields"]:
                    v = clean_value(c, f, rec.get(f["key"]), pid, "%s row %d" % (s["label"], n)) if visible(f, rec) else None
                    if v is not None:
                        clean[f["key"]] = v
                ins(c, "udpr_rows", {"dpr_id": did, "section": s["key"], "row_no": n, "front_id": _int(raw.get("_front_id")),
                                     "data": json.dumps(clean), "created_by": u["id"], "ts": now()})
    # values on work rows (line sections) are checked here, after the core save gave the rows their ids
    line_secs = [s for s in secs if s["kind"] == "line"]
    if line_secs:
        for w in q(c, "SELECT w.id, x.vals FROM dpr_work w LEFT JOIN udpr_work x ON x.work_id=w.id WHERE w.dpr_id=?", (did,)):
            rec = _j(w["vals"], {}) or {}
            if not rec:
                continue
            clean = {}
            for s in line_secs:
                for f in s["fields"]:
                    if f["key"] in rec:
                        v = clean_value(c, f, rec[f["key"]], pid, "Work row") if visible(f, rec) else None
                        if v is not None:
                            clean[f["key"]] = v
            c.execute("UPDATE udpr_work SET vals=? WHERE work_id=?", (json.dumps(clean) if clean else None, w["id"]))
    for part in ("work", "labour", "equipment"):
        tbl = "udpr_work" if part == "work" else "udpr_lx"
        for f_ in q(c, "SELECT DISTINCT front_id FROM %s WHERE dpr_id=? AND front_id IS NOT NULL" % tbl, (did,)):
            if not q1(c, "SELECT id FROM udpr_fronts WHERE id=? AND project_id=?", (f_["front_id"], pid)):
                raise ApiError("A line uses a work front of another project.")
    if "problems" in a:
        save_problems(c, u, d, a.get("problems") or [])
    warnings = []
    for w in q(c, "SELECT * FROM dpr_work WHERE dpr_id=?", (did,)):
        fg = line_figures(c, d, [w]).get(w["id"])
        if fg and fg["reported_over_scope"]:
            warnings.append("%s: reported cumulative %s is above the approved scope %s %s (it will need a variation before it "
                            "can be accepted)." % (_label_line(c, w), fg["current_reported"], fg["scope"], fg["unit"] or ""))
    log(c, u, did, "saved", d["status"], d["status"]) if rid else None
    return {"id": did, "no": d["no"], "warnings": warnings}


def _label_line(c, w):
    if w.get("boq_item_id"):
        return val(c, "SELECT code FROM boq_items WHERE id=?", (w["boq_item_id"],), "") or "BOQ item"
    return val(c, "SELECT COALESCE(code, name) FROM activities WHERE id=?", (w.get("activity_id"),), "") or "Activity"


def save_problems(c, u, d, rows):
    """Issues reported on this DPR. A continuing problem is linked to its open issue (one issue, one line per day);
    a new one becomes an issue in the issue register (Work > Issues & punch list) unless an open issue with the same
    title exists, which is linked instead."""
    pid = d["project_id"]
    keep = set()
    for p in rows:
        if not isinstance(p, dict):
            continue
        iid = _int(p.get("issue_id"))
        title = (p.get("title") or "").strip()
        if not iid and not title:
            continue
        if not iid:
            same = q1(c, "SELECT id FROM fld_issues WHERE project_id=? AND status NOT IN ('closed','void') AND LOWER(TRIM(title))=?",
                      (pid, title.lower()))
            if same:
                iid = same["id"]
            else:
                r = inv.FUNCS["fld.issue_save"][0](c, u, {"row": {"project_id": pid, "type": "site", "title": title[:200],
                                                                   "description": p.get("description") or p.get("note"),
                                                                   "activity_id": _int(p.get("activity_id")),
                                                                   "assignee": p.get("assignee"), "due_date": p.get("due_date") or None,
                                                                   "priority": p.get("priority") or "normal",
                                                                   "source": "dpr", "source_id": d["id"]}})
                iid = r["id"]
        else:
            i0 = get(c, "fld_issues", iid, "Issue")
            if i0["project_id"] != pid:
                raise ApiError("Issue %s belongs to another project." % i0["no"])
        x = q1(c, "SELECT * FROM udpr_issue_x WHERE issue_id=?", (iid,))
        cat = p.get("category") if p.get("category") in ISSUE_CATEGORIES else (x or {}).get("category")
        data = {"category": cat, "front_id": _int(p.get("front_id")) or (x or {}).get("front_id")}
        for k in ("impact", "mitigation", "decision_required", "responsible_party"):
            if k in p:
                data[k] = (p.get(k) or "").strip()[:2000] or None
        if "claim_relevant" in p:
            data["claim_relevant"] = 1 if str(p.get("claim_relevant")) in ("1", "true", "True", "Yes") else 0
        if x:
            sets = ", ".join("%s=?" % k for k in data)
            c.execute("UPDATE udpr_issue_x SET %s WHERE issue_id=?" % sets, list(data.values()) + [iid])
        else:
            data["issue_id"] = iid
            ins(c, "udpr_issue_x", data)
        hrs = _f(p.get("hours"))
        if hrs < 0 or hrs > 24:
            raise ApiError("Hours lost to an issue must be between 0 and 24.")
        c.execute("INSERT OR REPLACE INTO udpr_issue_days(issue_id, dpr_id, date, hours, note) VALUES(?,?,?,?,?)",
                  (iid, d["id"], d["date"], hrs, (p.get("note") or "").strip()[:1000] or None))
        keep.add(iid)
    for r in q(c, "SELECT issue_id FROM udpr_issue_days WHERE dpr_id=?", (d["id"],)):
        if r["issue_id"] not in keep:
            c.execute("DELETE FROM udpr_issue_days WHERE issue_id=? AND dpr_id=?", (r["issue_id"], d["id"]))
            keep.add(r["issue_id"])
    for iid in keep:
        refresh_issue(c, iid)


def refresh_issue(c, iid):
    agg = q1(c, "SELECT COUNT(*) n, SUM(hours) h, MIN(date) f, MAX(date) l FROM udpr_issue_days WHERE issue_id=?", (iid,))
    first = q1(c, "SELECT dpr_id FROM udpr_issue_days WHERE issue_id=? ORDER BY date, dpr_id LIMIT 1", (iid,))
    last = q1(c, "SELECT dpr_id FROM udpr_issue_days WHERE issue_id=? ORDER BY date DESC, dpr_id DESC LIMIT 1", (iid,))
    c.execute("UPDATE udpr_issue_x SET days_reported=?, hours_total=?, first_date=?, last_date=?, first_dpr_id=?, last_dpr_id=? "
              "WHERE issue_id=?", (agg["n"] or 0, r2(agg["h"]), agg["f"], agg["l"], (first or {}).get("dpr_id"),
                                   (last or {}).get("dpr_id"), iid))


@api("udpr.step", "project", "view")
def udpr_step(c, u, a):
    """One workflow step. Submit / check / approve / return / reopen run the existing engine steps (so costing and the
    2.24 checks are unchanged); reject, revise, lock and unlock are new."""
    act = a.get("action")
    d = get(c, "dpr", int(a["id"]), "DPR")
    check_project(c, u, d["project_id"])
    h = ensure_head(c, d)
    reason = (a.get("reason") or "").strip()
    std = {"submit": ("dpr.submit", "project", "edit"), "check": ("dpr.check", "project", "edit"),
           "approve": ("dpr.approve", "project", "approve"), "return": ("dpr.return", "project", "edit"),
           "reopen": ("dpr.reopen", "admin", "edit")}
    if act in std:
        fn, m, ac = std[act]
        core.require(u, m, ac)
        if act == "submit":
            need(c, u, "dpr", "submit", "submit a DPR")
        if act in ("return", "reopen") and not reason:
            raise ApiError("Write the reason; it is kept with the report.")
        return inv.FUNCS[fn][0](c, u, {"id": d["id"], "reason": reason})
    if act == "reject":
        need(c, u, "dpr", "approve", "reject a DPR")
        if d["status"] not in ("submitted", "checked"):
            raise ApiError("Only a submitted or checked DPR can be rejected (this one is %s)." % d["status"])
        if not reason:
            raise ApiError("Write why the report is rejected.")
        upd(c, "dpr", d["id"], {"status": "rejected"})
        c.execute("UPDATE udpr_head SET rejected_at=?, rejected_by=?, reject_reason=? WHERE dpr_id=?", (now(), u["id"], reason, d["id"]))
        log(c, u, d["id"], "rejected", d["status"], "rejected", reason)
        audit(c, u, "reject", "dpr", d["id"], reason)
        return True
    if act == "revise":
        core.require(u, "project", "edit")
        if d["status"] != "rejected":
            raise ApiError("Only a rejected DPR can be taken back to draft.")
        upd(c, "dpr", d["id"], {"status": "draft"})
        log(c, u, d["id"], "revised after rejection", "rejected", "draft", reason or None)
        return True
    if act == "lock":
        need(c, u, "dpr", "approve", "lock a DPR")
        if d["status"] != "approved":
            raise ApiError("Only an approved DPR can be locked.")
        if h["locked_at"]:
            return True
        c.execute("UPDATE udpr_head SET locked_at=?, locked_by=? WHERE dpr_id=?", (now(), u["id"], d["id"]))
        log(c, u, d["id"], "locked", "approved", "approved")
        audit(c, u, "lock", "dpr", d["id"])
        return True
    if act == "unlock":
        if not (u.get("role") == "admin" or (right(c, u, "dpr", "approve") and core.can(u, "project", "approve"))):
            raise ApiError("Unlocking needs the DPR approve right.")
        if not reason:
            raise ApiError("Write why the locked report must be unlocked; it is kept in the log.")
        c.execute("UPDATE udpr_head SET locked_at=NULL, locked_by=NULL WHERE dpr_id=?", (d["id"],))
        log(c, u, d["id"], "unlocked", d["status"], d["status"], reason)
        audit(c, u, "unlock", "dpr", d["id"], reason)
        return True
    raise ApiError("Unknown step.")


@api("udpr.revision", "project", "view")
def udpr_revision(c, u, a):
    r = get(c, "udpr_revisions", int(a["id"]), "Revision")
    d = get(c, "dpr", r["dpr_id"], "DPR")
    check_project(c, u, d["project_id"])
    r["snapshot"] = _j(r["snapshot"], {})
    if not right(c, u, "hse_private", "view"):
        sens = {s["key"] for s in merged_sections(templates_for_dpr(c, d)) if s.get("sensitive")}
        r["snapshot"]["rows"] = [x for x in r["snapshot"].get("rows") or [] if x.get("section") not in sens]
    return r


@api("udpr.list", "project", "view")
def udpr_list(c, u, a):
    pid = _pid(a)
    check_project(c, u, pid)
    auto_lock(c, pid)
    cond, p = ["d.project_id=?"], [pid]
    for k, col in (("from", "d.date>=?"), ("to", "d.date<=?")):
        if a.get(k):
            cond.append(col)
            p.append(a[k])
    st = a.get("status")
    if st == "locked":
        cond.append("h.locked_at IS NOT NULL")
    elif st == "returned":
        cond.append("d.status='draft' AND h.returned_at IS NOT NULL")
    elif st:
        cond.append("d.status=?")
        p.append(st)
    if a.get("front_id"):
        cond.append("(h.front_id=? OR EXISTS (SELECT 1 FROM udpr_work x WHERE x.dpr_id=d.id AND x.front_id=?))")
        p += [int(a["front_id"])] * 2
    page = max(0, int(_f(a.get("page"))))
    size = min(200, max(10, int(_f(a.get("size"), 50))))
    total = val(c, "SELECT COUNT(*) FROM dpr d LEFT JOIN udpr_head h ON h.dpr_id=d.id WHERE " + " AND ".join(cond), p)
    rows = q(c, "SELECT d.id, d.no, d.date, d.shift, d.status, d.weather, h.locked_at, h.returned_at, h.return_comment, "
                "h.reject_reason, h.revision, h.front_id, h.package_id, h.s_work, "
                "(SELECT COUNT(*) FROM dpr_work w WHERE w.dpr_id=d.id) work_lines, "
                "(SELECT COUNT(*) FROM dpr_work w JOIN udpr_work x ON x.work_id=w.id WHERE w.dpr_id=d.id AND x.accepted_qty IS NOT NULL) accepted_lines, "
                "(SELECT ROUND(SUM(count*(hours+COALESCE(ot_hours,0))),2) FROM dpr_labour WHERE dpr_id=d.id) manhours, "
                "(SELECT ROUND(SUM(hours),2) FROM dpr_equipment WHERE dpr_id=d.id) machine_hours, "
                "(SELECT COUNT(*) FROM udpr_issue_days i WHERE i.dpr_id=d.id) issues, "
                "(SELECT COUNT(*) FROM files f WHERE f.dpr_id=d.id) photos "
                "FROM dpr d LEFT JOIN udpr_head h ON h.dpr_id=d.id WHERE " + " AND ".join(cond) +
             " ORDER BY d.date DESC, d.shift LIMIT ? OFFSET ?", p + [size, page * size])
    for r in rows:
        r["shown"] = "locked" if r["locked_at"] else ("returned" if r["status"] == "draft" and r["returned_at"] else r["status"])
        r["shown_label"] = STATUS_LABEL.get(r["shown"], r["shown"])
    return {"rows": rows, "total": total, "page": page, "size": size}


@api("udpr.import", "project", "view")
def udpr_import(c, u, a):
    """Work rows to start a DPR from: the schedule's activities due on the date (with their BOQ items), then BOQ items
    with balance and no activity, then WBS. Nothing is saved."""
    pid = _pid(a)
    check_project(c, u, pid)
    d = a.get("date") or today()
    src = a.get("source") or "schedule"
    out = []
    if src == "schedule":
        for act in q(c, "SELECT * FROM activities WHERE project_id=? AND planned_start<=? AND planned_finish>=? AND actual_finish IS NULL "
                        "ORDER BY code", (pid, d, d)):
            days = max(1, (date.fromisoformat(act["planned_finish"]) - date.fromisoformat(act["planned_start"])).days + 1)
            out.append({"activity_id": act["id"], "boq_item_id": act["boq_item_id"], "location": act["location"],
                        "planned_qty": r2((act["planned_qty"] or 0) / days), "actual_qty": "",
                        "chainage_from": act["chainage_from"], "chainage_to": act["chainage_to"]})
    elif src == "boq":
        for b in q(c, "SELECT * FROM boq_items WHERE project_id=? ORDER BY code", (pid,)):
            if (scope_qty(b) or 0) - (b["executed_qty"] or 0) <= EPS:
                continue
            act = q1(c, "SELECT id FROM activities WHERE boq_item_id=? ORDER BY id LIMIT 1", (b["id"],))
            out.append({"activity_id": act["id"] if act else "", "boq_item_id": b["id"], "location": b["location"], "planned_qty": "", "actual_qty": ""})
    elif src == "wbs":
        for act in q(c, "SELECT a.* FROM activities a WHERE a.project_id=? AND a.actual_finish IS NULL AND (? IS NULL OR a.wbs_id=?) ORDER BY a.code",
                     (pid, _int(a.get("wbs_id")), _int(a.get("wbs_id")))):
            out.append({"activity_id": act["id"], "boq_item_id": act["boq_item_id"], "location": act["location"], "planned_qty": "", "actual_qty": ""})
    return out[:500]


# ───────────────────────────── issue register ─────────────────────────────
@api("udpr.issues", "project", "view")
def udpr_issues(c, u, a):
    pid = _pid(a)
    check_project(c, u, pid)
    cond, p = ["i.project_id=?", "(i.type='site' OR x.issue_id IS NOT NULL)"], [pid]
    st = a.get("status") or "open"
    if st == "open":
        cond.append("i.status NOT IN ('closed','void')")
    elif st != "all":
        cond.append("i.status=?")
        p.append(st)
    for k in ("category", "front_id"):
        if a.get(k):
            cond.append("x.%s=?" % k)
            p.append(a[k])
    if a.get("claim"):
        cond.append("x.claim_relevant=1")
    rows = q(c, "SELECT i.*, x.category, x.front_id, x.impact, x.mitigation, x.decision_required, x.claim_relevant, "
                "x.responsible_party, x.event_id, x.first_date, x.last_date, x.days_reported, x.hours_total, "
                "f.name front, act.name activity, e.no event_no FROM fld_issues i LEFT JOIN udpr_issue_x x ON x.issue_id=i.id "
                "LEFT JOIN udpr_fronts f ON f.id=x.front_id LEFT JOIN activities act ON act.id=i.activity_id "
                "LEFT JOIN events e ON e.id=x.event_id WHERE " + " AND ".join(cond) +
             " ORDER BY CASE WHEN i.status IN ('closed','void') THEN 1 ELSE 0 END, i.due_date IS NULL, i.due_date, i.id DESC LIMIT 1000", p)
    td = today()
    for r in rows:
        r["overdue"] = bool(r["due_date"] and r["due_date"] < td and r["status"] not in ("closed", "void"))
        r["open_days"] = (date.fromisoformat(td) - date.fromisoformat((r["first_date"] or r["ts"] or td)[:10])).days
    return rows


@api("udpr.issue_save", "project", "view")
def udpr_issue_save(c, u, a):
    r = dict(a.get("row") or {})
    pid = _pid(r)
    check_project(c, u, pid)
    base = {k: r.get(k) for k in ("id", "project_id", "title", "description", "location", "activity_id", "party_id",
                                  "assignee_user_id", "assignee", "due_date", "priority", "status", "root_cause") if k in r}
    if not base.get("id"):
        base["type"] = "site"
    res = inv.FUNCS["fld.issue_save"][0](c, u, {"row": base})
    iid = res["id"]
    if r.get("event_id"):
        e = q1(c, "SELECT id, project_id FROM events WHERE id=?", (int(r["event_id"]),))
        if not e or e["project_id"] != pid:
            raise ApiError("That contract event belongs to another project.")
    x = q1(c, "SELECT * FROM udpr_issue_x WHERE issue_id=?", (iid,))
    data = {}
    for k in ("category", "impact", "mitigation", "decision_required", "responsible_party"):
        if k in r:
            data[k] = (r.get(k) or "").strip()[:2000] or None
    for k in ("front_id", "event_id"):
        if k in r:
            data[k] = _int(r.get(k))
    if "claim_relevant" in r:
        data["claim_relevant"] = 1 if str(r.get("claim_relevant")) in ("1", "true", "True", "Yes") else 0
    if x and data:
        c.execute("UPDATE udpr_issue_x SET %s WHERE issue_id=?" % ", ".join("%s=?" % k for k in data), list(data.values()) + [iid])
    elif not x:
        data["issue_id"] = iid
        ins(c, "udpr_issue_x", data)
    audit(c, u, "save", "udpr_issue_x", iid, data)
    return {"id": iid}


@api("udpr.issue_days", "project", "view")
def udpr_issue_days(c, u, a):
    i = get(c, "fld_issues", int(a["id"]), "Issue")
    check_project(c, u, i["project_id"])
    return q(c, "SELECT dd.*, d.no, d.status FROM udpr_issue_days dd JOIN dpr d ON d.id=dd.dpr_id WHERE dd.issue_id=? ORDER BY dd.date", (i["id"],))


# ───────────────────────────── fronts and project set-up ─────────────────────────────
@api("udpr.fronts", "project", "view")
def udpr_fronts(c, u, a):
    pid = _pid(a)
    check_project(c, u, pid)
    return fronts(c, pid)


@api("udpr.front_save", "project", "view")
def udpr_front_save(c, u, a):
    r = a.get("row") or {}
    pid = _pid(r)
    check_project(c, u, pid)
    need(c, u, "dpr_setup", "edit", "set up packages and work fronts")
    if not (r.get("name") or "").strip():
        raise ApiError("Give the package or work front a name.")
    kind = r.get("kind") if r.get("kind") in ("package", "front") else "front"
    data = {"project_id": pid, "kind": kind, "code": (r.get("code") or "").strip()[:30] or None, "name": r["name"].strip()[:200],
            "parent_id": _int(r.get("parent_id")), "party_id": _int(r.get("party_id")), "contract_id": _int(r.get("contract_id")),
            "discipline": (r.get("discipline") or "").strip()[:80] or None, "location": (r.get("location") or "").strip()[:200] or None,
            "ch_from": _f(r.get("ch_from"), None), "ch_to": _f(r.get("ch_to"), None),
            "active": 0 if str(r.get("active")) == "0" else 1, "sort": int(_f(r.get("sort"))), "ts": now()}
    if data["parent_id"] and not q1(c, "SELECT id FROM udpr_fronts WHERE id=? AND project_id=?", (data["parent_id"], pid)):
        raise ApiError("The package chosen belongs to another project.")
    if data["contract_id"] and not q1(c, "SELECT id FROM contracts WHERE id=? AND project_id=?", (data["contract_id"], pid)):
        raise ApiError("The contract chosen belongs to another project.")
    if r.get("id"):
        f0 = get(c, "udpr_fronts", int(r["id"]), "Work front")
        if f0["project_id"] != pid:
            raise ApiError("This work front belongs to another project.")
        upd(c, "udpr_fronts", f0["id"], data)
        fid = f0["id"]
    else:
        fid = ins(c, "udpr_fronts", data)
    audit(c, u, "save", "udpr_fronts", fid, data)
    return {"id": fid}


@api("udpr.project_cfg", "project", "view")
def udpr_project_cfg(c, u, a):
    pid = _pid(a)
    check_project(c, u, pid)
    cfg = project_cfg(c, pid)
    lib = q(c, "SELECT t.id, t.code, t.name, t.category, t.description, t.project_id, t.system, v.version_no FROM udpr_templates t "
               "LEFT JOIN udpr_tpl_versions v ON v.id=t.current_version_id WHERE t.active=1 AND (t.project_id IS NULL OR t.project_id=?) "
               "ORDER BY t.system DESC, t.id", (pid,))
    all_secs = merged_sections(current_templates(c, pid), ())
    return {"cfg": cfg, "library": lib, "all_sections": all_secs, "core_sections": [{"key": k, "label": l, "default": bool(o)} for k, l, o in CORE_SECTIONS]}


@api("udpr.project_cfg_save", "project", "view")
def udpr_project_cfg_save(c, u, a):
    pid = _pid(a)
    check_project(c, u, pid)
    need(c, u, "dpr_setup", "edit", "change the project's DPR set-up")
    old = project_cfg(c, pid)
    tids = []
    for t in a.get("templates") if a.get("templates") is not None else old["templates"]:
        r = q1(c, "SELECT id, project_id FROM udpr_templates WHERE id=? AND active=1", (int(t),))
        if not r or r["project_id"] not in (None, pid):
            raise ApiError("A template chosen is not available to this project.")
        if r["id"] not in tids:
            tids.append(r["id"])
    basis = a.get("progress_basis", old["progress_basis"])
    if basis not in ("reported", "accepted"):
        raise ApiError("Progress basis is reported or accepted.")
    frm = a.get("basis_from", old["basis_from"]) or None
    if basis == "accepted" and not frm:
        raise ApiError("Give the date from which progress follows accepted quantities (earlier DPRs keep their reported quantities).")
    if frm and not re.match(r"^\d{4}-\d{2}-\d{2}$", frm):
        raise ApiError("Date as YYYY-MM-DD.")
    tol = _f(a.get("scope_tol", old["scope_tol"]))
    if tol < 0 or tol > 25:
        raise ApiError("Scope tolerance must be between 0 and 25%.")
    hidden = [str(x) for x in (a.get("hidden") if a.get("hidden") is not None else old["hidden"])][:500]
    secs = {k: bool(v) for k, v in (a.get("sections") or old["sections"]).items() if k in {x[0] for x in CORE_SECTIONS}}
    for k in ("work",):
        secs[k] = True   # the work rows are what a DPR is
    c.execute("INSERT OR REPLACE INTO udpr_project(project_id, templates, hidden, sections, progress_basis, basis_from, scope_tol, "
              "updated_by, updated_at) VALUES(?,?,?,?,?,?,?,?,?)", (pid, json.dumps(tids), json.dumps(hidden), json.dumps(secs),
                                                                   basis, frm, tol, u["id"], now()))
    audit(c, u, "save", "udpr_project", pid, {"templates": tids, "basis": basis, "from": frm, "hidden": len(hidden)})
    if basis != old["progress_basis"] or frm != old["basis_from"]:
        import api_project as P
        P.recompute_progress(c, pid)
    return project_cfg(c, pid)


# ───────────────────────────── template library ─────────────────────────────
@api("udpr.templates", "project", "view")
def udpr_templates(c, u, a):
    rows = q(c, "SELECT t.*, v.version_no, v.published_at, (SELECT COUNT(*) FROM udpr_tpl_versions WHERE template_id=t.id) versions "
                "FROM udpr_templates t LEFT JOIN udpr_tpl_versions v ON v.id=t.current_version_id ORDER BY t.system DESC, t.id")
    for r in rows:
        cur = q1(c, "SELECT definition FROM udpr_tpl_versions WHERE id=?", (r["current_version_id"],)) if r["current_version_id"] else None
        r["unpublished"] = bool(cur and _j(cur["definition"]) != _j(r["draft"]))
        d = _j(r.pop("draft"), {}) or {}
        r["sections"] = len(d.get("sections") or [])
        r["fields"] = sum(len(s.get("fields") or []) for s in d.get("sections") or [])
        r["projects"] = sum(1 for p in q(c, "SELECT templates FROM udpr_project") if r["id"] in (_j(p["templates"], []) or []))
    return rows


@api("udpr.template_get", "project", "view")
def udpr_template_get(c, u, a):
    t = get(c, "udpr_templates", int(a["id"]), "Template")
    t["draft"] = _j(t["draft"], {"sections": []})
    t["versions"] = q(c, "SELECT id, version_no, note, published_by, published_at FROM udpr_tpl_versions WHERE template_id=? ORDER BY version_no DESC", (t["id"],))
    if a.get("version_id"):
        v = get(c, "udpr_tpl_versions", int(a["version_id"]), "Version")
        t["version_definition"] = _j(v["definition"], {})
    t["field_types"] = [{"key": k, "label": l} for k, l in FIELD_TYPES]
    return t


@api("udpr.template_save", "project", "view")
def udpr_template_save(c, u, a):
    need(c, u, "dpr_setup", "edit", "edit DPR templates and fields")
    r = a.get("row") or {}
    if not (r.get("name") or "").strip():
        raise ApiError("Give the template a name.")
    d = validate_definition(r.get("draft") if isinstance(r.get("draft"), dict) else _j(r.get("draft"), {"sections": []}))
    pid = _int(r.get("project_id"))
    if pid:
        check_project(c, u, pid)
    # section names must stay unique among the templates a project can combine
    mine = {s["key"] for s in d["sections"]}
    for t in q(c, "SELECT id, name, draft FROM udpr_templates WHERE active=1 AND id<>?", (int(r.get("id") or 0),)):
        clash = mine & {s.get("key") for s in (_j(t["draft"], {}) or {}).get("sections") or []}
        if clash:
            raise ApiError("Section name '%s' is already used by template '%s'; use another internal name." % (sorted(clash)[0], t["name"]))
    data = {"name": r["name"].strip()[:120], "category": (r.get("category") or "custom")[:40],
            "description": (r.get("description") or "").strip()[:500] or None, "project_id": pid,
            "active": 0 if str(r.get("active")) == "0" else 1, "draft": json.dumps(d), "updated_by": u["id"], "updated_at": now()}
    if r.get("id"):
        t0 = get(c, "udpr_templates", int(r["id"]), "Template")
        if t0["system"]:
            data.pop("project_id")
        upd(c, "udpr_templates", t0["id"], data)
        tid = t0["id"]
    else:
        data["code"] = re.sub(r"[^A-Z0-9]", "", (r.get("code") or r["name"]).upper())[:12] or "TPL"
        data["system"] = 0
        tid = ins(c, "udpr_templates", data)
    audit(c, u, "save", "udpr_templates", tid, {"name": data["name"], "sections": len(d["sections"])})
    if a.get("publish"):
        return udpr_template_publish(c, u, {"id": tid, "note": a.get("note")})
    return {"id": tid}


@api("udpr.template_publish", "project", "view")
def udpr_template_publish(c, u, a):
    """Publish the draft as a new version. DPRs already started keep the version they were created with."""
    need(c, u, "dpr_setup", "edit", "publish DPR templates")
    t = get(c, "udpr_templates", int(a["id"]), "Template")
    d = validate_definition(_j(t["draft"], {"sections": []}))
    cur = q1(c, "SELECT * FROM udpr_tpl_versions WHERE id=?", (t["current_version_id"],)) if t["current_version_id"] else None
    if cur and _j(cur["definition"]) == d:
        return {"id": t["id"], "version_id": cur["id"], "version_no": cur["version_no"], "unchanged": True}
    n = (val(c, "SELECT MAX(version_no) FROM udpr_tpl_versions WHERE template_id=?", (t["id"],)) or 0) + 1
    vid = ins(c, "udpr_tpl_versions", {"template_id": t["id"], "version_no": n, "definition": json.dumps(d),
                                       "note": (a.get("note") or "").strip()[:300] or None, "published_by": u["id"], "published_at": now()})
    upd(c, "udpr_templates", t["id"], {"current_version_id": vid})
    audit(c, u, "publish", "udpr_templates", t["id"], {"version": n})
    return {"id": t["id"], "version_id": vid, "version_no": n}


@api("udpr.template_copy", "project", "view")
def udpr_template_copy(c, u, a):
    need(c, u, "dpr_setup", "edit", "create DPR templates")
    t = get(c, "udpr_templates", int(a["id"]), "Template")
    d = _j(t["draft"], {"sections": []})
    suffix = (a.get("suffix") or "p%s" % (a.get("project_id") or "")).lower()
    suffix = re.sub(r"[^a-z0-9_]", "", suffix)[:8] or "copy"
    for s in d["sections"]:
        s["key"] = (s["key"][:30] + "_" + suffix)[:40]
    name = (a.get("name") or (t["name"] + " (copy)")).strip()[:120]
    return udpr_template_save(c, u, {"row": {"name": name, "category": t["category"], "description": t["description"],
                                             "project_id": _int(a.get("project_id")), "draft": d}})


@api("udpr.settings_save", "project", "view")
def udpr_settings_save(c, u, a):
    need(c, u, "dpr_setup", "edit", "change DPR settings")
    out = {}
    if "udpr_form" in a:
        if a["udpr_form"] not in ("smart", "classic"):
            raise ApiError("Form is smart or classic.")
        out["udpr_form"] = a["udpr_form"]
    if "udpr_autolock_days" in a:
        n = int(_f(a["udpr_autolock_days"]))
        if n < 0 or n > 365:
            raise ApiError("Automatic lock: 0 (off) to 365 days.")
        out["udpr_autolock_days"] = str(n)
    if "udpr_report_header" in a:
        out["udpr_report_header"] = (a["udpr_report_header"] or "").strip()[:200]
    if "udpr_signatures" in a:
        sig = [x.strip()[:40] for x in str(a["udpr_signatures"] or "").split("|") if x.strip()][:5]
        out["udpr_signatures"] = "|".join(sig) or DEFAULTS["udpr_signatures"]
    if "udpr_scope_tol" in a:
        t = _f(a["udpr_scope_tol"])
        if t < 0 or t > 25:
            raise ApiError("Scope tolerance must be between 0 and 25%.")
        out["udpr_scope_tol"] = str(t)
    for k, v in out.items():
        c.execute("INSERT OR REPLACE INTO settings(key, value) VALUES(?,?)", (k, v))
    audit(c, u, "save", "settings", None, out)
    return out


# ───────────────────────────── reports ─────────────────────────────
REPORTS = [("daily", "Daily summary"), ("weekly", "Weekly summary"), ("monthly", "Monthly summary"),
           ("activity", "Activity-wise progress"), ("front", "Work-front-wise progress"), ("plan_actual", "Planned vs actual production"),
           ("manpower", "Manpower utilisation"), ("equipment", "Equipment utilisation"), ("materials", "Material consumption"),
           ("quality", "Quality report"), ("hse", "Safety and environment"), ("issues", "Delay and issue register"),
           ("delays", "Hours lost by cause"), ("photos", "Photographic progress"), ("custom", "Custom field report")]


def _range(a):
    to = a.get("to") or today()
    frm = a.get("from") or (date.fromisoformat(to) - timedelta(days=6)).isoformat()
    if frm > to:
        raise ApiError("The start date is after the end date.")
    return frm, to


def _dpr_filter(a, alias="d"):
    """Reports read submitted, checked and approved DPRs by default (drafts are not reports yet)."""
    sts = a.get("statuses") or ["submitted", "checked", "approved"]
    sts = [s for s in sts if s in ("draft", "submitted", "checked", "approved", "rejected")] or ["approved"]
    return "%s.status IN (%s)" % (alias, ",".join("'%s'" % s for s in sts))


def _front_sql(a, line_alias):
    if not a.get("front_id"):
        return "", []
    fid = int(a["front_id"])
    return (" AND (COALESCE(%s.front_id, h.front_id)=? OR COALESCE(%s.front_id, h.front_id) IN (SELECT id FROM udpr_fronts WHERE parent_id=?))"
            % (line_alias, line_alias)), [fid, fid]


def _period_key(dstr, kind):
    d = date.fromisoformat(dstr)
    if kind == "weekly":
        y, w, _ = d.isocalendar()
        start = d - timedelta(days=d.weekday())
        return "%d-W%02d (from %s)" % (y, w, start.isoformat())
    if kind == "monthly":
        try:
            import sched_calc as SC
            by, bm, _bd = SC.ad_to_bs(d)
            return "%04d-%02d (BS) " % (by, bm)
        except Exception:
            return dstr[:7]
    return dstr


@api("udpr.report", "project", "view")
def udpr_report(c, u, a):
    kind = a.get("kind") or "daily"
    pid = _pid(a)
    check_project(c, u, pid)
    frm, to = _range(a)
    flt = _dpr_filter(a)
    sens = right(c, u, "hse_private", "view")
    notes = []
    cols, rows, totals = [], [], None
    if kind in ("daily", "weekly", "monthly"):
        base = q(c, "SELECT d.id, d.no, d.date, d.shift, d.status, d.weather, d.rain_mm, d.weather_lost_hours, h.s_work, h.s_problems, h.s_next, "
                    "h.locked_at, h.temp_min, h.temp_max, "
                    "(SELECT COUNT(*) FROM dpr_work w WHERE w.dpr_id=d.id) work_lines, "
                    "(SELECT ROUND(SUM(l.count*(l.hours+COALESCE(l.ot_hours,0))),2) FROM dpr_labour l WHERE l.dpr_id=d.id) manhours, "
                    "(SELECT ROUND(SUM(l.count),2) FROM dpr_labour l WHERE l.dpr_id=d.id) workers, "
                    "(SELECT ROUND(SUM(e.hours),2) FROM dpr_equipment e WHERE e.dpr_id=d.id) machine_hours, "
                    "(SELECT ROUND(SUM(e.idle_hours),2) FROM dpr_equipment e WHERE e.dpr_id=d.id) idle_hours, "
                    "(SELECT ROUND(SUM(e.breakdown_hours),2) FROM dpr_equipment e WHERE e.dpr_id=d.id) breakdown_hours, "
                    "(SELECT COUNT(*) FROM udpr_issue_days i WHERE i.dpr_id=d.id) issues, "
                    "(SELECT COUNT(*) FROM files f WHERE f.dpr_id=d.id) photos "
                    "FROM dpr d LEFT JOIN udpr_head h ON h.dpr_id=d.id WHERE d.project_id=? AND d.date BETWEEN ? AND ? AND " + flt +
                 " ORDER BY d.date, d.shift", (pid, frm, to))
        if kind == "daily":
            cols = [{"k": "date", "label": "Date"}, {"k": "no", "label": "DPR"}, {"k": "shift", "label": "Shift"}, {"k": "status", "label": "Status"},
                    {"k": "weather", "label": "Weather"}, {"k": "work_lines", "label": "Work rows", "fmt": "qty"},
                    {"k": "workers", "label": "Workers", "fmt": "qty"}, {"k": "manhours", "label": "Man-hours", "fmt": "qty"},
                    {"k": "machine_hours", "label": "Machine h", "fmt": "qty"}, {"k": "idle_hours", "label": "Idle h", "fmt": "qty"},
                    {"k": "breakdown_hours", "label": "Down h", "fmt": "qty"}, {"k": "issues", "label": "Issues", "fmt": "qty"},
                    {"k": "photos", "label": "Photos", "fmt": "qty"}, {"k": "s_work", "label": "Work completed"}]
            rows = base
        else:
            agg = {}
            for r in base:
                k = _period_key(r["date"], kind)
                x = agg.setdefault(k, {"period": k, "dprs": 0, "days": set(), "manhours": 0, "machine_hours": 0, "idle_hours": 0,
                                       "breakdown_hours": 0, "issues": 0, "photos": 0, "rain_mm": 0, "lost_hours": 0})
                x["dprs"] += 1
                x["days"].add(r["date"])
                for f in ("manhours", "machine_hours", "idle_hours", "breakdown_hours", "issues", "photos", "rain_mm"):
                    x[f] += r[f] or 0
                x["lost_hours"] += r["weather_lost_hours"] or 0
            for x in agg.values():
                x["days"] = len(x["days"])
                for f in ("manhours", "machine_hours", "idle_hours", "breakdown_hours", "rain_mm", "lost_hours"):
                    x[f] = r2(x[f])
            rows = list(agg.values())
            cols = [{"k": "period", "label": "Week" if kind == "weekly" else "Month"}, {"k": "days", "label": "Days reported", "fmt": "qty"},
                    {"k": "dprs", "label": "DPRs", "fmt": "qty"}, {"k": "manhours", "label": "Man-hours", "fmt": "qty"},
                    {"k": "machine_hours", "label": "Machine h", "fmt": "qty"}, {"k": "idle_hours", "label": "Idle h", "fmt": "qty"},
                    {"k": "breakdown_hours", "label": "Down h", "fmt": "qty"}, {"k": "rain_mm", "label": "Rain mm", "fmt": "qty"},
                    {"k": "lost_hours", "label": "Weather h lost", "fmt": "qty"}, {"k": "issues", "label": "Issue reports", "fmt": "qty"},
                    {"k": "photos", "label": "Photos", "fmt": "qty"}]
            prod = q(c, "SELECT w.boq_item_id, w.activity_id, d.date, w.actual_qty, x.accepted_qty FROM dpr_work w JOIN dpr d ON d.id=w.dpr_id "
                        "LEFT JOIN udpr_work x ON x.work_id=w.id WHERE d.project_id=? AND d.date BETWEEN ? AND ? AND " + flt, (pid, frm, to))
            for r in rows:
                r["reported_lines"] = sum(1 for p in prod if _period_key(p["date"], kind) == r["period"])
            cols.insert(3, {"k": "reported_lines", "label": "Work rows", "fmt": "qty"})
    elif kind in ("activity", "plan_actual", "front"):
        fs, fp = _front_sql(a, "x")
        lines = q(c, "SELECT w.*, d.date, d.status, x.accepted_qty, COALESCE(x.front_id, h.front_id) front_id FROM dpr_work w "
                     "JOIN dpr d ON d.id=w.dpr_id LEFT JOIN udpr_work x ON x.work_id=w.id LEFT JOIN udpr_head h ON h.dpr_id=d.id "
                     "WHERE d.project_id=? AND d.date BETWEEN ? AND ? AND " + flt + fs, [pid, frm, to] + fp)
        if kind == "front":
            fr = {f["id"]: f for f in fronts(c, pid)}
            agg = {}
            for w in lines:
                k = w["front_id"] or 0
                x = agg.setdefault(k, {"front": (fr.get(k) or {}).get("name") or "(no work front)", "rows": 0, "reported": {}, "accepted": {}, "dprs": set()})
                x["rows"] += 1
                x["dprs"].add(w["dpr_id"])
                unit = _unit_of(c, w)
                x["reported"][unit] = x["reported"].get(unit, 0) + (w["actual_qty"] or 0)
                if w["accepted_qty"] is not None:
                    x["accepted"][unit] = x["accepted"].get(unit, 0) + w["accepted_qty"]
            for k, x in agg.items():
                lab = q1(c, "SELECT ROUND(SUM(l.count*(l.hours+COALESCE(l.ot_hours,0))),2) mh FROM dpr_labour l JOIN dpr d ON d.id=l.dpr_id "
                            "LEFT JOIN udpr_lx lx ON lx.part='labour' AND lx.line_id=l.id LEFT JOIN udpr_head h ON h.dpr_id=d.id "
                            "WHERE d.project_id=? AND d.date BETWEEN ? AND ? AND " + flt + " AND COALESCE(lx.front_id, h.front_id, 0)=?", (pid, frm, to, k))
                eqh = q1(c, "SELECT ROUND(SUM(e.hours),2) h, ROUND(SUM(e.idle_hours),2) i FROM dpr_equipment e JOIN dpr d ON d.id=e.dpr_id "
                            "LEFT JOIN udpr_lx lx ON lx.part='equipment' AND lx.line_id=e.id LEFT JOIN udpr_head h ON h.dpr_id=d.id "
                            "WHERE d.project_id=? AND d.date BETWEEN ? AND ? AND " + flt + " AND COALESCE(lx.front_id, h.front_id, 0)=?", (pid, frm, to, k))
                iss = val(c, "SELECT COUNT(DISTINCT dd.issue_id) FROM udpr_issue_days dd JOIN udpr_issue_x ix ON ix.issue_id=dd.issue_id "
                             "WHERE dd.date BETWEEN ? AND ? AND COALESCE(ix.front_id,0)=? AND dd.dpr_id IN (SELECT id FROM dpr WHERE project_id=?)", (frm, to, k, pid))
                rows.append({"front": x["front"], "dprs": len(x["dprs"]), "rows": x["rows"],
                             "reported": "; ".join("%s %s" % (r2(v), un) for un, v in x["reported"].items()),
                             "accepted": "; ".join("%s %s" % (r2(v), un) for un, v in x["accepted"].items()) or "not yet",
                             "manhours": lab["mh"] or 0, "machine_hours": eqh["h"] or 0, "idle_hours": eqh["i"] or 0, "issues": iss})
            cols = [{"k": "front", "label": "Work front"}, {"k": "dprs", "label": "DPRs", "fmt": "qty"}, {"k": "rows", "label": "Work rows", "fmt": "qty"},
                    {"k": "reported", "label": "Reported"}, {"k": "accepted", "label": "Accepted"}, {"k": "manhours", "label": "Man-hours", "fmt": "qty"},
                    {"k": "machine_hours", "label": "Machine h", "fmt": "qty"}, {"k": "idle_hours", "label": "Idle h", "fmt": "qty"},
                    {"k": "issues", "label": "Issues", "fmt": "qty"}]
        elif kind == "plan_actual":
            agg = {}
            for w in lines:
                k = (w["activity_id"] or 0, w["boq_item_id"] or 0)
                x = agg.setdefault(k, {"item": _label_line(c, w), "name": _name_line(c, w), "unit": _unit_of(c, w), "days": 0, "planned": 0, "actual": 0})
                x["days"] += 1
                x["planned"] += w["planned_qty"] or 0
                x["actual"] += w["actual_qty"] or 0
            for x in agg.values():
                x["variance"] = r2(x["actual"] - x["planned"])
                x["pct"] = r2(x["actual"] / x["planned"] * 100) if x["planned"] else None
                x["planned"], x["actual"] = r2(x["planned"]), r2(x["actual"])
                x["flag"] = "behind plan" if x["pct"] is not None and x["pct"] < 80 else ("no plan" if x["pct"] is None else "")
                rows.append(x)
            rows.sort(key=lambda r: (r["pct"] if r["pct"] is not None else 999))
            cols = [{"k": "item", "label": "Item"}, {"k": "name", "label": "Activity"}, {"k": "unit", "label": "Unit"},
                    {"k": "days", "label": "Days", "fmt": "qty"}, {"k": "planned", "label": "Planned", "fmt": "qty"},
                    {"k": "actual", "label": "Reported", "fmt": "qty"}, {"k": "variance", "label": "Variance", "fmt": "qty"},
                    {"k": "pct", "label": "% of plan", "fmt": "qty"}, {"k": "flag", "label": ""}]
            notes.append("Planned daily quantities come from the DPR rows (schedule prefill). Reported = what the site reported.")
        else:
            rows = progress_rows(c, pid, to, a.get("front_id"), frm)
            cols = PROGRESS_COLS
            notes.append("Accepted cumulative is the QS / engineer's accepted quantity; reported is the site's. Scope = BOQ revised "
                         "quantity including approved variations. Measured, billed and certified come from verified measurements "
                         "and IPCs, so the chain from site to certificate can be read across one row.")
    elif kind == "manpower":
        fs, fp = _front_sql(a, "lx")
        rows = q(c, "SELECT t.name trade, COALESCE(p.name,'Own') gang_of, COUNT(DISTINCT d.id) days, ROUND(SUM(l.count),2) worker_days, "
                    "ROUND(SUM(l.count*l.hours),2) normal_h, ROUND(SUM(l.count*COALESCE(l.ot_hours,0)),2) ot_h, "
                    "ROUND(SUM(l.count*(l.hours+COALESCE(l.ot_hours,0))),2) manhours, "
                    "ROUND(SUM(CAST(json_extract(lx.vals,'$.planned') AS REAL)),2) planned, ROUND(SUM(l.amount),2) cost "
                    "FROM dpr_labour l JOIN dpr d ON d.id=l.dpr_id LEFT JOIN trades t ON t.id=l.trade_id LEFT JOIN parties p ON p.id=l.party_id "
                    "LEFT JOIN udpr_lx lx ON lx.part='labour' AND lx.line_id=l.id LEFT JOIN udpr_head h ON h.dpr_id=d.id "
                    "WHERE d.project_id=? AND d.date BETWEEN ? AND ? AND " + flt + fs + " GROUP BY l.trade_id, l.party_id ORDER BY manhours DESC",
                 [pid, frm, to] + fp)
        for r in rows:
            r["vs_plan"] = r2((r["worker_days"] or 0) / r["planned"] * 100) if r["planned"] else None
        cols = [{"k": "trade", "label": "Trade"}, {"k": "gang_of", "label": "Own / subcontractor"}, {"k": "days", "label": "Days", "fmt": "qty"},
                {"k": "planned", "label": "Planned worker-days", "fmt": "qty"}, {"k": "worker_days", "label": "Actual worker-days", "fmt": "qty"},
                {"k": "vs_plan", "label": "% of plan", "fmt": "qty"}, {"k": "normal_h", "label": "Normal h", "fmt": "qty"},
                {"k": "ot_h", "label": "OT h", "fmt": "qty"}, {"k": "manhours", "label": "Man-hours", "fmt": "qty"},
                {"k": "cost", "label": "Cost (approved DPRs)", "fmt": "money"}]
        notes.append("DPR attendance is the site's count; it is not verified payroll attendance. Cost is the DPR labour costing (own gangs) "
                     "on approved reports; the ledger stays the record of posted cost.")
    elif kind == "equipment":
        fs, fp = _front_sql(a, "lx")
        rows = q(c, "SELECT e.code, e.name, COALESCE(e.ownership,'owned') ownership, COUNT(DISTINCT d.id) days, ROUND(SUM(x.hours),2) work_h, "
                    "ROUND(SUM(x.idle_hours),2) idle_h, ROUND(SUM(x.breakdown_hours),2) down_h, "
                    "ROUND(SUM(CAST(json_extract(lx.vals,'$.fuel') AS REAL)),2) fuel_l, ROUND(SUM(x.amount),2) cost "
                    "FROM dpr_equipment x JOIN dpr d ON d.id=x.dpr_id JOIN equipment e ON e.id=x.equipment_id "
                    "LEFT JOIN udpr_lx lx ON lx.part='equipment' AND lx.line_id=x.id LEFT JOIN udpr_head h ON h.dpr_id=d.id "
                    "WHERE d.project_id=? AND d.date BETWEEN ? AND ? AND " + flt + fs + " GROUP BY x.equipment_id ORDER BY e.code",
                 [pid, frm, to] + fp)
        for r in rows:
            tot = (r["work_h"] or 0) + (r["idle_h"] or 0) + (r["down_h"] or 0)
            r["utilisation"] = r2((r["work_h"] or 0) / tot * 100) if tot else None
            r["availability"] = r2(((r["work_h"] or 0) + (r["idle_h"] or 0)) / tot * 100) if tot else None
            r["fuel_per_h"] = r2(r["fuel_l"] / r["work_h"]) if r["fuel_l"] and r["work_h"] else None
            r["flag"] = ", ".join(x for x in ["low utilisation" if r["utilisation"] is not None and r["utilisation"] < 50 else "",
                                             "frequent breakdowns" if (r["down_h"] or 0) > 0.15 * tot and tot else ""] if x)
        cols = [{"k": "code", "label": "Machine"}, {"k": "name", "label": "Name"}, {"k": "ownership", "label": "Owned / hired"},
                {"k": "days", "label": "Days", "fmt": "qty"}, {"k": "work_h", "label": "Working h", "fmt": "qty"},
                {"k": "idle_h", "label": "Idle h", "fmt": "qty"}, {"k": "down_h", "label": "Breakdown h", "fmt": "qty"},
                {"k": "utilisation", "label": "Utilisation %", "fmt": "qty"}, {"k": "availability", "label": "Availability %", "fmt": "qty"},
                {"k": "fuel_l", "label": "Fuel (L, DPR)", "fmt": "qty"}, {"k": "fuel_per_h", "label": "L / h", "fmt": "qty"},
                {"k": "cost", "label": "Charged (DPR)", "fmt": "money"}, {"k": "flag", "label": ""}]
        notes.append("Utilisation = working ÷ (working + idle + breakdown) hours. Fuel issued from the store stays the authoritative fuel figure "
                     "(Equipment > Equipment business); the DPR fuel column is the site's note.")
    elif kind == "materials":
        rows = q(c, "SELECT m.code, m.name, m.unit, ROUND(SUM(l.qty-COALESCE(l.returned_qty,0)),4) issued, ROUND(SUM(l.amount),2) value, "
                    "COUNT(DISTINCT i.id) issues, GROUP_CONCAT(DISTINCT COALESCE(b.code, e.code, l.target)) used_for "
                    "FROM issue_lines l JOIN issues i ON i.id=l.issue_id JOIN materials m ON m.id=l.material_id "
                    "LEFT JOIN boq_items b ON b.id=l.boq_item_id LEFT JOIN equipment e ON e.id=l.equipment_id "
                    "WHERE i.status='posted' AND i.project_id=? AND i.date BETWEEN ? AND ? GROUP BY l.material_id ORDER BY value DESC", (pid, frm, to))
        rec = {r["material_id"]: r["qty"] for r in q(c, "SELECT l.material_id, ROUND(SUM(l.accepted_qty),4) qty FROM grn_lines l JOIN grn g ON "
                                                        "g.id=l.grn_id WHERE g.status='posted' AND g.project_id=? AND g.date BETWEEN ? AND ? "
                                                        "GROUP BY l.material_id", (pid, frm, to))}
        ids = {r["code"]: val(c, "SELECT id FROM materials WHERE code=?", (r["code"],)) for r in rows}
        for r in rows:
            r["received"] = rec.get(ids[r["code"]])
        cols = [{"k": "code", "label": "Material"}, {"k": "name", "label": "Name"}, {"k": "unit", "label": "Unit"},
                {"k": "received", "label": "Received", "fmt": "qty"}, {"k": "issued", "label": "Issued (net of returns)", "fmt": "qty"},
                {"k": "value", "label": "Value", "fmt": "money"}, {"k": "issues", "label": "Issue notes", "fmt": "qty"},
                {"k": "used_for", "label": "Charged to"}]
        notes.append("From posted store issues and receipts (the authoritative record); DPRs never record consumption of their own, so nothing is counted twice.")
    elif kind == "quality":
        rows = q(c, "SELECT t.no ref, 'Test' kind, t.test_type what, COALESCE(t.result_date, t.sampled_date) date, t.location, t.result_value result, "
                    "t.status, n.no ncr FROM qa_tests t LEFT JOIN ncrs n ON n.id=t.ncr_id WHERE t.project_id=? AND "
                    "COALESCE(t.result_date, t.sampled_date) BETWEEN ? AND ?", (pid, frm, to))
        rows += q(c, "SELECT no ref, 'NCR' kind, title what, date, '' location, corrective_action result, status, no ncr FROM ncrs "
                     "WHERE project_id=? AND date BETWEEN ? AND ?", (pid, frm, to))
        rows += q(c, "SELECT no ref, 'Inspection' kind, title what, date, location, result, status, '' ncr FROM fld_inspections "
                     "WHERE project_id=? AND date BETWEEN ? AND ?", (pid, frm, to))
        rows += _section_rows(c, pid, frm, to, flt, "quality", sens)
        rows.sort(key=lambda r: (r.get("date") or "", r.get("ref") or ""))
        cols = [{"k": "date", "label": "Date"}, {"k": "kind", "label": "Record"}, {"k": "ref", "label": "Ref"}, {"k": "what", "label": "Test / item"},
                {"k": "location", "label": "Location"}, {"k": "result", "label": "Result"}, {"k": "status", "label": "Status"}, {"k": "ncr", "label": "NCR"}]
        notes.append("A test or inspection listed here does not by itself accept work; quantities are accepted separately by the QS / engineer.")
    elif kind == "hse":
        inc = q(c, "SELECT no ref, date, kind what, location, injury, days_lost, status, description, corrective_action FROM hs_incidents "
                   "WHERE project_id=? AND date BETWEEN ? AND ?", (pid, frm, to))
        if not sens:
            inc = [{"ref": r["ref"], "date": r["date"], "what": r["what"], "status": r["status"], "location": "(restricted)"} for r in inc]
            notes.append("Incident details are restricted to roles with the hse_private right; counts are shown.")
        rows = [dict(r, kind="Incident") for r in inc] + _section_rows(c, pid, frm, to, flt, "hse", sens)
        rows.sort(key=lambda r: r.get("date") or "")
        cols = [{"k": "date", "label": "Date"}, {"k": "kind", "label": "Record"}, {"k": "ref", "label": "Ref"}, {"k": "what", "label": "Type / topic"},
                {"k": "location", "label": "Location"}, {"k": "description", "label": "Details"}, {"k": "status", "label": "Status"}]
    elif kind == "issues":
        rows = udpr_issues(c, u, {"project_id": pid, "status": a.get("issue_status") or "all", "front_id": a.get("front_id"),
                                  "category": a.get("category")})
        cols = [{"k": "no", "label": "Issue"}, {"k": "first_date", "label": "First reported"}, {"k": "title", "label": "Issue"},
                {"k": "category", "label": "Category"}, {"k": "front", "label": "Work front"}, {"k": "activity", "label": "Activity"},
                {"k": "days_reported", "label": "Days reported", "fmt": "qty"}, {"k": "hours_total", "label": "Hours lost", "fmt": "qty"},
                {"k": "impact", "label": "Impact"}, {"k": "decision_required", "label": "Decision required"},
                {"k": "assignee", "label": "Assigned to"}, {"k": "due_date", "label": "Target date"}, {"k": "status", "label": "Status"},
                {"k": "claim_relevant", "label": "Notice / claim relevance", "fmt": "yesno"}, {"k": "event_no", "label": "Contract event"}]
        notes.append("Claim relevance is a flag for the commercial team to review; BuildCore does not decide entitlement or responsibility.")
    elif kind == "delays":
        rows = q(c, "SELECT dd.category, COALESCE(dd.responsibility, 'not set') responsibility, COUNT(*) entries, COUNT(DISTINCT d.id) days, "
                    "ROUND(SUM(dd.hours),2) hours FROM dpr_delays dd JOIN dpr d ON d.id=dd.dpr_id WHERE d.project_id=? AND d.date BETWEEN ? AND ? AND "
                    + flt + " GROUP BY dd.category, dd.responsibility ORDER BY hours DESC", (pid, frm, to))
        cols = [{"k": "category", "label": "Cause"}, {"k": "responsibility", "label": "Responsibility (as recorded)"},
                {"k": "entries", "label": "Entries", "fmt": "qty"}, {"k": "days", "label": "Days", "fmt": "qty"}, {"k": "hours", "label": "Hours lost", "fmt": "qty"}]
    elif kind == "photos":
        rows = q(c, "SELECT f.id file_id, f.date, f.caption, f.location, f.filename, f.ts uploaded, d.no dpr, act.name activity, f.kind "
                    "FROM files f JOIN dpr d ON d.id=f.dpr_id LEFT JOIN activities act ON act.id=f.activity_id WHERE d.project_id=? AND "
                    "d.date BETWEEN ? AND ? AND " + flt + " ORDER BY d.date, f.id LIMIT 600", (pid, frm, to))
        cols = [{"k": "date", "label": "Date"}, {"k": "dpr", "label": "DPR"}, {"k": "activity", "label": "Activity"}, {"k": "location", "label": "Location"},
                {"k": "caption", "label": "Caption"}, {"k": "filename", "label": "File"}, {"k": "uploaded", "label": "Uploaded at"}]
        notes.append("Dates shown are the report date and the upload time. BuildCore does not verify the time or place a photograph was taken.")
    elif kind == "custom":
        sec = a.get("section")
        if not sec:
            raise ApiError("Choose the project section or field to report on.")
        secs = {s["key"]: s for s in merged_sections(current_templates(c, pid))}
        allv = {}
        for t in q(c, "SELECT definition FROM udpr_tpl_versions"):
            for s in (_j(t["definition"], {}) or {}).get("sections") or []:
                allv.setdefault(s["key"], s)
        s = secs.get(sec) or allv.get(sec)
        if not s:
            raise ApiError("That section is not in any template.")
        if s.get("sensitive") and not sens:
            raise ApiError("This section holds restricted safety information.")
        fs, fp = _front_sql(a, "r")
        if s["kind"] == "table":
            for r in q(c, "SELECT r.*, d.date, d.no FROM udpr_rows r JOIN dpr d ON d.id=r.dpr_id LEFT JOIN udpr_head h ON h.dpr_id=d.id "
                          "WHERE d.project_id=? AND r.section=? AND d.date BETWEEN ? AND ? AND " + flt + fs + " ORDER BY d.date, r.row_no",
                       [pid, sec, frm, to] + fp):
                x = _j(r["data"], {}) or {}
                x.update(date=r["date"], dpr=r["no"])
                rows.append(x)
        elif s["kind"] == "fields":
            for r in q(c, "SELECT d.id, d.date, d.no FROM dpr d WHERE d.project_id=? AND d.date BETWEEN ? AND ? AND " + flt + " ORDER BY d.date",
                       (pid, frm, to)):
                x = {"date": r["date"], "dpr": r["no"]}
                for v in q(c, "SELECT key, value FROM udpr_values WHERE dpr_id=? AND key LIKE ?", (r["id"], sec + ".%")):
                    x[v["key"].split(".", 1)[1]] = v["value"]
                if len(x) > 2:
                    rows.append(x)
        else:
            for r in q(c, "SELECT w.*, d.date, d.no, x.vals FROM dpr_work w JOIN dpr d ON d.id=w.dpr_id JOIN udpr_work x ON x.work_id=w.id "
                          "WHERE d.project_id=? AND d.date BETWEEN ? AND ? AND " + flt + " AND x.vals IS NOT NULL ORDER BY d.date", (pid, frm, to)):
                x = _j(r["vals"], {}) or {}
                x.update(date=r["date"], dpr=r["no"], item=_label_line(c, r), reported=r["actual_qty"])
                rows.append(x)
        cols = [{"k": "date", "label": "Date"}, {"k": "dpr", "label": "DPR"}] + ([{"k": "item", "label": "Item"}, {"k": "reported", "label": "Reported", "fmt": "qty"}] if s["kind"] == "line" else []) + \
               [{"k": f["key"], "label": f["label"] + (" (%s)" % f["unit"] if f.get("unit") else ""),
                 "fmt": "qty" if f["type"] in NUMERIC else None} for f in s["fields"] if f.get("in_report", True) is not False]
        num = [f["key"] for f in s["fields"] if f["type"] in NUMERIC and f.get("sum", True)]
        if rows and num:
            totals = {k: r2(sum(_f(r.get(k)) for r in rows)) for k in num}
        notes.append("Section '%s' (template %s)." % (s["label"], s.get("template", "")))
    else:
        raise ApiError("Unknown report.")
    grp = a.get("group_by")
    if grp and rows and any(grp in r for r in rows):
        rows.sort(key=lambda r: str(r.get(grp) or ""))
    if a.get("sort_by") and rows:
        k = a["sort_by"]
        rows.sort(key=lambda r: (r.get(k) is None, r.get(k) if isinstance(r.get(k), (int, float)) else str(r.get(k) or "")),
                  reverse=bool(a.get("desc")))
    if a.get("columns"):
        want = [x for x in a["columns"] if any(cc["k"] == x for cc in cols)]
        if want:
            cols = [cc for cc in cols if cc["k"] in want]
    if totals is None and rows:
        nums = [cc["k"] for cc in cols if cc.get("fmt") in ("qty", "money") and kind not in ("activity",) and
                cc["k"] not in ("pct", "vs_plan", "utilisation", "availability", "fuel_per_h", "work_lines")]
        totals = {k: r2(sum(_f(r.get(k)) for r in rows)) for k in nums} if nums else None
    title = dict(REPORTS).get(kind, kind)
    p = q1(c, "SELECT code, name FROM projects WHERE id=?", (pid,))
    return {"kind": kind, "title": title, "project": p, "from": frm, "to": to, "columns": cols, "rows": rows, "totals": totals,
            "notes": notes, "header": setting(c, "udpr_report_header") or "", "company": setting(c, "company_name") or "",
            "signatures": (setting(c, "udpr_signatures") or DEFAULTS["udpr_signatures"]).split("|"), "generated": now()}


def _section_rows(c, pid, frm, to, flt, group, sens):
    out = []
    secs = [s for s in merged_sections(current_templates(c, pid)) if s.get("group") == group and s["kind"] == "table"]
    for s in secs:
        if s.get("sensitive") and not sens:
            n = val(c, "SELECT COUNT(*) FROM udpr_rows r JOIN dpr d ON d.id=r.dpr_id WHERE d.project_id=? AND r.section=? AND d.date BETWEEN ? AND ? AND " + flt,
                    (pid, s["key"], frm, to))
            if n:
                out.append({"date": to, "kind": s["label"], "what": "%d entries (restricted)" % n})
            continue
        for r in q(c, "SELECT r.data, d.date, d.no FROM udpr_rows r JOIN dpr d ON d.id=r.dpr_id WHERE d.project_id=? AND r.section=? AND "
                      "d.date BETWEEN ? AND ? AND " + flt + " ORDER BY d.date, r.row_no", (pid, s["key"], frm, to)):
            x = _j(r["data"], {}) or {}
            vals = list(x.values())
            out.append({"date": r["date"], "kind": s["label"], "ref": x.get("ir_no") or x.get("ref") or r["no"],
                        "what": x.get("topic") or x.get("test") or x.get("kind") or x.get("activity") or (vals[0] if vals else ""),
                        "location": x.get("location") or x.get("chainage") or x.get("face") or "",
                        "result": x.get("result") or "", "status": x.get("status") or "",
                        "description": x.get("description") or x.get("findings") or "", "ncr": x.get("ncr") or ""})
    return out


def _unit_of(c, w):
    if w.get("boq_item_id"):
        return val(c, "SELECT unit FROM boq_items WHERE id=?", (w["boq_item_id"],), "") or ""
    return val(c, "SELECT unit FROM activities WHERE id=?", (w.get("activity_id"),), "") or ""


def _name_line(c, w):
    if w.get("activity_id"):
        return val(c, "SELECT name FROM activities WHERE id=?", (w["activity_id"],), "") or ""
    return val(c, "SELECT description FROM boq_items WHERE id=?", (w.get("boq_item_id"),), "") or ""


PROGRESS_COLS = [{"k": "code", "label": "Item"}, {"k": "description", "label": "Description"}, {"k": "unit", "label": "Unit"},
                 {"k": "scope", "label": "Approved scope", "fmt": "qty"}, {"k": "planned_cum", "label": "Planned to date", "fmt": "qty"},
                 {"k": "reported_period", "label": "Reported in period", "fmt": "qty"}, {"k": "accepted_period", "label": "Accepted in period", "fmt": "qty"},
                 {"k": "reported_cum", "label": "Reported cumulative", "fmt": "qty"}, {"k": "accepted_cum", "label": "Accepted cumulative", "fmt": "qty"},
                 {"k": "awaiting", "label": "Awaiting acceptance", "fmt": "qty"}, {"k": "balance", "label": "Balance", "fmt": "qty"},
                 {"k": "progress_pct", "label": "Progress %", "fmt": "qty"}, {"k": "measured", "label": "Measured", "fmt": "qty"},
                 {"k": "billed", "label": "Billed (IPC)", "fmt": "qty"}, {"k": "certified", "label": "Certified", "fmt": "qty"},
                 {"k": "flags", "label": "Flags"}]


def progress_rows(c, pid, as_of, front_id=None, frm=None):
    """One row per BOQ item (and per activity without a BOQ item): scope, planned, reported, accepted, measured, billed and
    certified quantities side by side. Each status is its own figure; none is derived from another."""
    fcond, fp = "", []
    if front_id:
        fcond = " AND (COALESCE(x.front_id, h.front_id)=? OR COALESCE(x.front_id, h.front_id) IN (SELECT id FROM udpr_fronts WHERE parent_id=?))"
        fp = [int(front_id)] * 2
    lines = q(c, "SELECT w.boq_item_id, w.activity_id, w.actual_qty, d.date, d.status, x.accepted_qty FROM dpr_work w JOIN dpr d ON d.id=w.dpr_id "
                 "LEFT JOIN udpr_work x ON x.work_id=w.id LEFT JOIN udpr_head h ON h.dpr_id=d.id WHERE d.project_id=? AND d.date<=? AND "
                 "d.status IN ('submitted','checked','approved')" + fcond, [pid, as_of] + fp)
    agg = {}
    for w in lines:
        k = ("b", w["boq_item_id"]) if w["boq_item_id"] else ("a", w["activity_id"])
        x = agg.setdefault(k, {"rep": 0.0, "acc": 0.0, "rep_p": 0.0, "acc_p": 0.0, "await": 0.0, "acc_any": False})
        x["rep"] += w["actual_qty"] or 0
        if w["accepted_qty"] is not None:
            x["acc"] += w["accepted_qty"]
            x["acc_any"] = True
        else:
            x["await"] += w["actual_qty"] or 0
        if frm and w["date"] >= frm:
            x["rep_p"] += w["actual_qty"] or 0
            x["acc_p"] += w["accepted_qty"] or 0
    rows = []
    boqs = q(c, "SELECT * FROM boq_items WHERE project_id=? ORDER BY code", (pid,))
    for b in boqs:
        x = agg.get(("b", b["id"]))
        if front_id and not x:
            continue
        x = x or {"rep": 0, "acc": 0, "rep_p": 0, "acc_p": 0, "await": 0, "acc_any": False}
        scope = scope_qty(b) or 0
        planned = 0.0
        for act in q(c, "SELECT planned_qty, planned_start, planned_finish FROM activities WHERE boq_item_id=?", (b["id"],)):
            planned += _planned_to(act, as_of)
        measured = val(c, "SELECT SUM(l.qty) FROM measurement_lines l JOIN measurements m ON m.id=l.measurement_id WHERE m.status='verified' "
                          "AND l.boq_item_id=? AND m.date<=?", (b["id"], as_of))
        billed = val(c, "SELECT SUM(l.qty) FROM ipc_lines l JOIN ipc i ON i.id=l.ipc_id WHERE i.status IN ('submitted','certified') AND "
                        "l.boq_item_id=? AND i.date<=?", (b["id"], as_of))
        cert = val(c, "SELECT SUM(l.qty) FROM ipc_lines l JOIN ipc i ON i.id=l.ipc_id WHERE i.status='certified' AND l.boq_item_id=? AND i.date<=?",
                   (b["id"], as_of))
        flags = []
        if x["rep"] > scope + EPS and scope:
            flags.append("reported beyond scope: variation needed")
        if x["acc"] > scope + EPS and scope:
            flags.append("accepted beyond scope (override)")
        if x["acc"] - (measured or 0) > EPS:
            flags.append("accepted, not yet measured")
        if (measured or 0) - (billed or 0) > EPS:
            flags.append("measured, not yet billed")
        if x["await"] > EPS:
            flags.append("awaiting acceptance")
        if planned and x["acc"] + EPS < planned * 0.9 and not front_id:
            flags.append("behind plan")
        rows.append({"boq_item_id": b["id"], "code": b["code"], "description": b["description"], "unit": b["unit"],
                     "original": b["qty"], "scope": r4(scope), "variation": r4(scope - (b["qty"] or 0)), "planned_cum": r4(planned) if planned else None,
                     "reported_period": r4(x["rep_p"]) if frm else None, "accepted_period": r4(x["acc_p"]) if frm else None,
                     "reported_cum": r4(x["rep"]), "accepted_cum": r4(x["acc"]) if x["acc_any"] else None, "awaiting": r4(x["await"]),
                     "balance": r4(scope - x["acc"]) if scope else None, "progress_pct": r2(x["acc"] / scope * 100) if scope and x["acc_any"] else None,
                     "measured": r4(measured), "billed": r4(billed), "certified": r4(cert), "flags": ", ".join(flags)})
    for (kind, aid), x in agg.items():
        if kind != "a" or not aid:
            continue
        act = q1(c, "SELECT * FROM activities WHERE id=?", (aid,))
        if not act:
            continue
        scope = act["planned_qty"] or 0
        rows.append({"activity_id": aid, "code": act["code"], "description": act["name"], "unit": act["unit"], "scope": r4(scope) or None,
                     "planned_cum": r4(_planned_to(act, as_of)) or None, "reported_period": r4(x["rep_p"]) if frm else None,
                     "accepted_period": r4(x["acc_p"]) if frm else None, "reported_cum": r4(x["rep"]),
                     "accepted_cum": r4(x["acc"]) if x["acc_any"] else None, "awaiting": r4(x["await"]),
                     "balance": r4(scope - x["acc"]) if scope else None, "progress_pct": r2(x["acc"] / scope * 100) if scope and x["acc_any"] else None,
                     "measured": None, "billed": None, "certified": None,
                     "flags": "activity without a BOQ item" + (" (milestone)" if act["is_milestone"] else "")})
    return rows


def _planned_to(act, as_of):
    s, f, qty = act.get("planned_start"), act.get("planned_finish"), act.get("planned_qty") or 0
    if not (s and f and qty):
        return 0.0
    if as_of < s:
        return 0.0
    if as_of >= f:
        return qty
    tot = (date.fromisoformat(f) - date.fromisoformat(s)).days + 1
    done = (date.fromisoformat(as_of) - date.fromisoformat(s)).days + 1
    return qty * done / tot


@api("udpr.progress", "project", "view")
def udpr_progress(c, u, a):
    pid = _pid(a)
    check_project(c, u, pid)
    as_of = a.get("as_of") or today()
    return {"rows": progress_rows(c, pid, as_of, a.get("front_id"), a.get("from")), "columns": PROGRESS_COLS, "as_of": as_of,
            "cfg": project_cfg(c, pid)}


@api("udpr.report_xlsx", "project", "view")
def udpr_report_xlsx(c, u, a):
    need(c, u, "dpr", "export", "export DPR reports")
    r = udpr_report(c, u, a)
    import api_copilot as CP
    cols = [{"k": x["k"], "label": x["label"]} for x in r["columns"]]
    rows = []
    for x in r["rows"]:
        rows.append({cc["k"]: (x.get(cc["k"]) if not isinstance(x.get(cc["k"]), (list, dict)) else json.dumps(x.get(cc["k"]))) for cc in cols})
    if r.get("totals"):
        t = {cc["k"]: r["totals"].get(cc["k"], "") for cc in cols}
        t[cols[0]["k"]] = "Total"
        rows.append(t)
    title = "%s - %s - %s to %s" % (r["title"], (r["project"] or {}).get("code", ""), r["from"], r["to"])
    data = _xlsx(CP, title, cols, rows)
    import base64
    audit(c, u, "export", "udpr_report", None, {"kind": a.get("kind"), "rows": len(rows)})
    return {"filename": re.sub(r"[^A-Za-z0-9_.-]+", "_", title)[:90] + ".xlsx", "b64": base64.b64encode(data).decode("ascii")}


def _xlsx(CP, title, cols, rows):
    return CP.make_xlsx(title, [x["label"] for x in cols], [[r.get(x["k"]) for x in cols] for r in rows])


@api("udpr.layouts", "project", "view")
def udpr_layouts(c, u, a):
    return q(c, "SELECT * FROM udpr_layouts WHERE shared=1 OR owner_id=? ORDER BY name", (u["id"],))


@api("udpr.layout_save", "project", "view")
def udpr_layout_save(c, u, a):
    r = a.get("row") or {}
    if not (r.get("name") or "").strip():
        raise ApiError("Name the saved layout.")
    if r.get("kind") not in dict(REPORTS):
        raise ApiError("Choose the report.")
    data = {"name": r["name"].strip()[:80], "kind": r["kind"], "params": json.dumps(r.get("params") or {}), "owner_id": u["id"],
            "shared": 0 if str(r.get("shared")) == "0" else 1, "ts": now()}
    if r.get("delete") and r.get("id"):
        lay = get(c, "udpr_layouts", int(r["id"]), "Layout")
        if lay["owner_id"] != u["id"] and u.get("role") != "admin":
            raise ApiError("Only its owner can delete a saved layout.")
        c.execute("DELETE FROM udpr_layouts WHERE id=?", (lay["id"],))
        return True
    if r.get("id"):
        upd(c, "udpr_layouts", int(r["id"]), data)
        return {"id": int(r["id"])}
    return {"id": ins(c, "udpr_layouts", data)}


@api("udpr.reports_meta", "project", "view")
def udpr_reports_meta(c, u, a):
    pid = _pid(a)
    secs = merged_sections(current_templates(c, pid))
    return {"reports": [{"key": k, "label": l} for k, l in REPORTS], "fronts": fronts(c, pid),
            "custom": [{"key": s["key"], "label": "%s (%s)" % (s["label"], s["template_name"]), "kind": s["kind"]} for s in secs
                       if not s.get("sensitive") or right(c, u, "hse_private", "view")],
            "can_export": right(c, u, "dpr", "export"), "issue_categories": ISSUE_CATEGORIES}
