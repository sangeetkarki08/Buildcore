"""
BuildCore 2.20 - Company Workspace and Project Workspace.

After sign-in a person works in one of two places:

  Company Workspace   the legal entity: consolidated accounting, payables and receivables, VAT,
                      central store, trading, equipment and asset registers, HR masters,
                      project portfolio and administration.
  Project Workspace   one project: its dashboard, BOQ, DPR, schedule, store, procurement,
                      expenses, equipment use, subcontracts, IPC billing, documents and reports.

Nothing about the books changes: one general ledger, one supplier master, one stock engine.
The workspaces decide which screens a person sees, and this module makes the ENGINE refuse what
the person may not reach - whatever the screen, link or direct request used:

  1. Role templates (ws_roles) say whether a role may enter the company workspace, which projects
     it may enter, and what it may do per module. The ten built-in roles become editable templates
     with exactly their old rights; three new templates are added (finance manager, project
     accountant, site supervisor). core.ROLES is fed from the table, so every existing
     require()/can() check keeps working for custom templates too.
  2. Company-only actions (trial balance, balance sheet, day book, VAT/TDS books, fiscal years,
     bank, NFRS books, fixed assets, administration, Copilot, trading sales...) are refused for
     users without company access.
  3. Project-restricted users: every request that names a project is checked against the user's
     projects; a missing project is filled with the session's active project; list results and
     the lookup tables come back with other projects' rows removed; stored files of other
     projects cannot be downloaded.
  4. The chosen workspace and project live on the session row and are re-checked on every
     request (ws.enter).

Like 2.17-2.19 this is an add-on: new tables and wrappers only, no existing row is modified.
"""
import json

import core
from core import ApiError, audit, ins, q, q1, setting, upd, val
import api_inventory as inv
from api_inventory import api

VERSION = "2.22.0"

SCHEMA = """
CREATE TABLE IF NOT EXISTS ws_roles(id INTEGER PRIMARY KEY, key TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
  company INTEGER DEFAULT 0, projects TEXT DEFAULT 'none', perms TEXT, builtin INTEGER DEFAULT 0,
  active INTEGER DEFAULT 1, sort INTEGER DEFAULT 0);
"""
SESSION_COLS = {"ws": "TEXT", "ws_project": "INTEGER"}
USER_COLS = {"ws_default": "TEXT"}

V, E, A = "view", "edit", "approve"
_R = lambda m, *acts: {m: list(acts)}  # noqa: E731


def _perms(**mods):
    return {m: sorted(a) for m, a in mods.items() if a}


# The built-in templates. company: may enter the Company Workspace. projects: 'all' | 'assigned'
# (only the projects given on the user) | 'none'. perms: module -> actions, exactly core.ROLES
# for the ten roles that already exist, so the update changes nobody's rights.
TEMPLATES = [
    ("admin", "Administrator", 1, "all", None),
    ("director", "Director", 1, "all", None),
    ("accountant", "Company accountant", 1, "all", None),
    ("finance_manager", "Finance manager", 1, "all",
     _perms(masters={V}, inventory={V}, procurement={V, A}, accounts={V, E, A}, equipment={V},
            project={V}, commercial={V, A}, quality={V}, plant={V}, assets={V, E, A})),
    ("procurement_officer", "Procurement officer", 1, "all", None),
    ("equipment_manager", "Equipment manager", 1, "all", None),
    ("viewer", "Viewer (read only)", 1, "all", None),
    ("project_manager", "Project manager", 0, "assigned", None),
    ("site_engineer", "Site engineer", 0, "assigned", None),
    ("quantity_surveyor", "Quantity surveyor (QS)", 0, "assigned", None),
    ("storekeeper", "Storekeeper", 0, "assigned", None),
    ("project_accountant", "Project accountant", 0, "assigned",
     _perms(masters={V}, inventory={V}, procurement={V, E}, accounts={V, E}, equipment={V},
            project={V}, commercial={V, E}, quality={V}, plant={V}, assets={V})),
    ("site_supervisor", "Site supervisor", 0, "assigned",
     _perms(masters={V}, inventory={V, E}, procurement={V}, equipment={V, E},
            project={V, E}, quality={V, E}, plant={V, E}, assets={V})),
]

# ───────────────────── which engine actions are company-only ─────────────────────
# A user whose role template has no company access is refused these, whatever screen,
# URL or direct request asked. Everything else is governed by module rights and the
# project checks below.
COMPANY_FNS = {
    "rep.tb", "rep.bs", "rep.daybook", "rep.vat", "rep.tds", "rep.party", "rep.party_summary",
    "rep.ageing", "cash.company", "cash.settings", "co.list", "co.info", "co.create", "co.update", "kpi.finance", "ratio.get", "ratio.targets",
    "bank.lines", "bank.clear", "dep.run", "dep.preview", "internal.run", "stock.opening",
    "team.logins", "team.sessions", "team.signout", "server.access",
}
COMPANY_PREFIXES = ("fy.", "period.", "adm.", "admin.", "books.", "nfrs15.", "fa.",
                    "asset.", "cop.", "oh.", "loan.", "trade.", "cf.def")
# allowed to everyone signed in, whatever the template says about companies
OPEN_FNS = {"auth.", "license.", "lookups", "help.", "cm.", "comments.", "files.", "ws.",
            "dash.approvals", "team.tick", "team.presence", "site.cfg_get"}


def company_only(fn):
    for p in OPEN_FNS:
        if fn == p or fn.startswith(p):
            return False
    return fn in COMPANY_FNS or fn.startswith(COMPANY_PREFIXES)


# ───────────────────── templates kept in the data file ─────────────────────
_CACHE = {}


def _key(c):
    try:
        return c.execute("PRAGMA database_list").fetchone()[2] or id(c)
    except Exception:
        return id(c)


def load_roles(c):
    """Read the templates and feed core.ROLES, so can()/require() know custom templates too."""
    rows = q(c, "SELECT * FROM ws_roles WHERE active=1")
    out = {}
    for r in rows:
        try:
            perms = {m: set(a) for m, a in json.loads(r["perms"] or "{}").items()}
        except ValueError:
            perms = {}
        out[r["key"]] = {"name": r["name"], "company": bool(r["company"]),
                         "projects": r["projects"] or "none", "perms": perms, "builtin": r["builtin"]}
        core.ROLES[r["key"]] = {m: {x for x in a if x in (V, E, A)} for m, a in perms.items()}
    _CACHE[_key(c)] = out
    return out


def roles(c):
    return _CACHE.get(_key(c)) or load_roles(c)


def template(c, user):
    t = roles(c).get(user["role"])
    if t:
        return t
    # a role that has no template row (should not happen): fall back to the old fixed table
    legacy = core.ROLES.get(user["role"], {})
    return {"name": user["role"], "company": user["role"] not in
            ("project_manager", "site_engineer", "quantity_surveyor", "storekeeper"),
            "projects": "all", "perms": legacy, "builtin": 1}


def init_workspace(c):
    c.executescript(SCHEMA)
    for tbl, cols in (("sessions", SESSION_COLS), ("users", USER_COLS)):
        have = {r[1] for r in c.execute("PRAGMA table_info(%s)" % tbl)}
        for col, typ in cols.items():
            if col not in have:
                c.execute("ALTER TABLE %s ADD COLUMN %s %s" % (tbl, col, typ))
    for i, (key, name, comp, proj, perms) in enumerate(TEMPLATES):
        if q1(c, "SELECT id FROM ws_roles WHERE key=?", (key,)):
            continue
        p = perms if perms is not None else {m: sorted(a) for m, a in core.ROLES.get(key, {}).items()}
        ins(c, "ws_roles", {"key": key, "name": name, "company": comp, "projects": proj,
                            "perms": json.dumps(p), "builtin": 1, "active": 1, "sort": i})
    load_roles(c)
    _guard()


# ───────────────────── who may see which projects ─────────────────────
def allowed_projects(c, user):
    """None = every project; otherwise the set of project ids this user may enter."""
    if not user:
        return set()
    t = template(c, user)
    if t["projects"] == "all":
        return None
    ids = set()
    try:
        raw = user["project_ids"] if "project_ids" in user.keys() else None
    except Exception:
        raw = None
    for x in str(raw or "").replace(";", ",").split(","):
        if x.strip().isdigit():
            ids.add(int(x))
    if t["projects"] == "none":
        return ids            # explicit assignments still count
    # 'assigned' with nothing assigned yet: every project, so the update locks nobody out
    return ids or None


def _session_ws(c, token):
    r = q1(c, "SELECT ws, ws_project FROM sessions WHERE token=?", (token,)) if token else None
    return (r["ws"], r["ws_project"]) if r else (None, None)


# ───────────────────── the engine checks ─────────────────────
PID_KEYS = ("project_id", "from_project", "to_project")


def _args_projects(a, depth=0):
    """Every project id named anywhere in the request."""
    out = set()
    if depth > 4:
        return out
    if isinstance(a, dict):
        for k, v in a.items():
            if k in PID_KEYS and v not in (None, "", 0, "0"):
                try:
                    out.add(int(v))
                except (TypeError, ValueError):
                    pass
            else:
                out |= _args_projects(v, depth + 1)
    elif isinstance(a, (list, tuple)):
        for v in a:
            out |= _args_projects(v, depth + 1)
    return out


def _filter_rows(x, allow, depth=0):
    """Remove other projects' rows from list results (lists of dicts that carry project_id)."""
    if depth > 4:
        return x
    if isinstance(x, list):
        if x and isinstance(x[0], dict) and any(k in x[0] for k in PID_KEYS):
            x = [r for r in x if not isinstance(r, dict) or _row_ok(r, allow)]
        return [_filter_rows(r, allow, depth + 1) for r in x]
    if isinstance(x, dict):
        return {k: _filter_rows(v, allow, depth + 1) for k, v in x.items()}
    return x


def _row_ok(r, allow):
    for k in PID_KEYS:
        v = r.get(k)
        if v not in (None, "", 0) and int(v) not in allow:
            return False
    return True


NO_DEFAULT_PID = {"lookups", "search", "ws.enter", "ws.meta", "auth.me"}     # these may run project-wide even in a project workspace


def _guard():
    import sys
    for name in ("__main__", "server"):
        mod = sys.modules.get(name)
        if not mod or not hasattr(mod, "call") or not hasattr(mod, "Handler"):
            continue
        cur = mod.call
        if getattr(cur, "_bco_ws", False):
            continue

        def call(fn, args, token, ip=None, device=None, _orig=cur):
            pre = _precheck(fn, args, token)
            if pre is not None:
                fn, args, allow = pre
            else:
                allow = None
            result = _orig(fn, args, token, ip, device)
            if allow is not None:
                result = _postcheck(fn, result, allow)
            return result
        call._bco_ws = True
        mod.call = call
        _patch_files(mod)
    _wrap_user_save()
    _wrap_me()


def _precheck(fn, args, token):
    """Runs before the engine lock work: company gate, project gate, active-project default."""
    with core.LOCK:
        c = core.connect()
        try:
            user = core.user_from_token(c, token)
            if not user:
                return None
            t = template(c, user)
            if not t["company"] and company_only(fn):
                raise ApiError("This is a company-level action. Your role (%s) works in the "
                               "Project Workspace only." % t["name"])
            allow = allowed_projects(c, user)
            args = dict(args or {})
            ws, ws_pid = _session_ws(c, token)
            if ws == "project" and ws_pid and fn not in NO_DEFAULT_PID and \
                    not any(args.get(k) for k in PID_KEYS) and "row" not in args:
                args["project_id"] = ws_pid       # the active project fills a missing one
            if allow is not None:
                bad = _args_projects(args) - allow
                if bad:
                    raise ApiError("PROJECT_DENIED: this record belongs to a project that is not "
                                   "assigned to you. Ask an administrator to assign you to it "
                                   "(Administration - Users and roles).")
            return fn, args, allow
        finally:
            c.close()


def _postcheck(fn, result, allow):
    if fn == "lookups" and isinstance(result, dict):
        result["projects"] = [p for p in result.get("projects", []) if p["id"] in allow]
    if isinstance(result, dict):
        for k in PID_KEYS:
            v = result.get(k)
            if v not in (None, "", 0) and int(v) not in allow:
                raise ApiError("PROJECT_DENIED: this record belongs to a project that is not assigned to you.")
    return _filter_rows(result, allow)


def _patch_files(mod):
    """Stored files: a project-restricted user cannot download another project's file."""
    H = mod.Handler
    orig = getattr(H, "send_stored_file", None)
    if orig is None or getattr(orig, "_bco_ws", False):
        return

    def send_stored_file(self, path, _orig=orig):
        try:
            fid = int(path.rsplit("/", 1)[1])
        except ValueError:
            return _orig(self, path)
        with core.LOCK:
            c = core.connect()
            try:
                user = core.user_from_token(c, self._token())
                row = q1(c, "SELECT project_id FROM files WHERE id=?", (fid,)) if user else None
                allow = allowed_projects(c, user) if user else set()
            finally:
                c.close()
        if user and row and allow is not None and row["project_id"] and int(row["project_id"]) not in allow:
            return self._json(403, {"error": "This file belongs to a project that is not assigned to you."})
        return _orig(self, path)
    send_stored_file._bco_ws = True
    H.send_stored_file = send_stored_file


def _wrap_user_save():
    """Administration - Users: save the assigned projects and the default workspace too."""
    us = inv.FUNCS.get("admin.user_save")
    if not us or getattr(us[0], "_bco_ws", False):
        return
    orig = us[0]

    def user_save(c, u, a, _orig=orig):
        load_roles(c)                      # custom template keys must pass the role check
        r = a.get("row") or {}
        res = _orig(c, u, a)
        extra = {}
        if "project_ids" in r:
            ids = r["project_ids"]
            if isinstance(ids, (list, tuple)):
                ids = ",".join(str(int(x)) for x in ids)
            extra["project_ids"] = str(ids or "")
        if "ws_default" in r:
            extra["ws_default"] = r["ws_default"] or None
        if extra:
            upd(c, "users", res["id"], extra)
        return res
    user_save._bco_ws = True
    inv.FUNCS["admin.user_save"] = (user_save, us[1], us[2], us[3])


def _wrap_me():
    """auth.me also says which workspaces and projects this person may enter."""
    me = inv.FUNCS.get("auth.me")
    if not me or getattr(me[0], "_bco_ws", False):
        return
    orig = me[0]

    def me2(c, u, a, _orig=orig):
        out = _orig(c, u, a)
        t = template(c, u)
        allow = allowed_projects(c, u)
        ws, ws_pid = _session_ws(c, a.get("_token"))
        pj = q(c, "SELECT id, code, name, COALESCE(kind,'') kind, status FROM projects "
                  "WHERE status='active' AND COALESCE(kind,'') NOT IN ('trading','general') ORDER BY code")
        if allow is not None:
            pj = [p for p in pj if p["id"] in allow]
        out["perms"] = {m: sorted(x) for m, x in t["perms"].items()} or out["perms"]
        out["workspace"] = {"company": t["company"], "projects": pj, "all_projects": allow is None,
                            "active": ws, "active_project": ws_pid,
                            "default": (u["ws_default"] if "ws_default" in u.keys() else None),
                            "role_name": t["name"], "version": VERSION}
        return out
    me2._bco_ws = True
    inv.FUNCS["auth.me"] = (me2, me[1], me[2], me[3])


# ───────────────────── choosing the workspace ─────────────────────
@api("ws.enter", public=False)
def ws_enter(c, u, a):
    """Record the workspace (and project) this sign-in works in; checked, never trusted."""
    t = template(c, u)
    ws = a.get("workspace") or ("company" if t["company"] else "project")
    pid = a.get("project_id")
    if ws == "company":
        if not t["company"]:
            raise ApiError("Your role (%s) does not have Company Workspace access." % t["name"])
        pid = None
    else:
        allow = allowed_projects(c, u)
        pj = q(c, "SELECT id FROM projects WHERE status='active' AND COALESCE(kind,'') NOT IN "
                  "('trading','general')")
        ids = [p["id"] for p in pj if allow is None or p["id"] in allow]
        if not ids:
            raise ApiError("No project is assigned to you yet. Ask an administrator "
                           "(Administration - Users and roles).")
        pid = int(pid) if pid else (ids[0] if len(ids) == 1 else None)
        if pid is None:
            raise ApiError("CHOOSE_PROJECT")
        if pid not in ids:
            raise ApiError("That project is not assigned to you.")
    c.execute("UPDATE sessions SET ws=?, ws_project=? WHERE token=?", (ws, pid, a.get("_token")))
    upd(c, "users", u["id"], {"ws_default": ws})      # remembered as a convenience only
    audit(c, u, "workspace", "sessions", None, {"ws": ws, "project_id": pid})
    return {"workspace": ws, "project_id": pid}


@api("ws.meta")
def ws_meta(c, u, a):
    t = template(c, u)
    return {"company": t["company"], "role_name": t["name"], "version": VERSION,
            "company_name": setting(c, "company_name")}


# ───────────────────── roles and permissions screen ─────────────────────
@api("ws.roles", "admin", "view")
def ws_roles(c, u, a):
    rows = q(c, "SELECT * FROM ws_roles ORDER BY sort, id")
    for r in rows:
        r["perms"] = json.loads(r["perms"] or "{}")
        r["users"] = val(c, "SELECT COUNT(*) FROM users WHERE role=? AND active=1", (r["key"],))
    return {"roles": rows, "modules": core.MODULES,
            "actions": ["view", "create", "edit", "submit", "approve", "post", "export", "delete"]}


# The engine's own checks know view / edit / approve. The finer verbs on a template are kept
# and mapped: create, edit, submit -> edit; approve, post -> approve; export -> view;
# delete only together with approve.
MAP = {"create": E, "edit": E, "submit": E, "approve": A, "post": A, "export": V, "delete": A, "view": V}


@api("ws.role_save", "admin", "edit")
def ws_role_save(c, u, a):
    r = a.get("row") or {}
    core.need(r, "key", "name")
    key = str(r["key"]).strip().lower().replace(" ", "_")
    perms = r.get("perms") or {}
    stored = {m: sorted({x for x in acts if x in MAP} | {MAP[x] for x in acts if x in MAP})
              for m, acts in perms.items() if acts}
    row = q1(c, "SELECT * FROM ws_roles WHERE key=?", (key,))
    data = {"name": r["name"], "company": 1 if r.get("company") else 0,
            "projects": r.get("projects") or "assigned", "perms": json.dumps(stored),
            "active": 0 if r.get("active") in (0, "0", False) else 1}
    if row:
        if row["builtin"] and key == "admin":
            raise ApiError("The administrator template cannot be changed.")
        upd(c, "ws_roles", row["id"], data)
        rid = row["id"]
    else:
        data.update({"key": key, "builtin": 0, "sort": 100})
        rid = ins(c, "ws_roles", data)
    load_roles(c)
    audit(c, u, "save", "ws_roles", rid, {"key": key, "name": r["name"]})
    return {"id": rid, "key": key}


# ───────────────────── the new company-level views ─────────────────────
def _fn(name):
    f = inv.FUNCS.get(name)
    return f[0] if f else None


def _try(f, *a):
    try:
        return f(*a) if f else None
    except Exception:
        return None


@api("ws.company_overview", "accounts", "view")
def company_overview(c, u, a):
    """The company dashboard: only figures BuildCore already calculates, side by side."""
    out = {"as_of": core.today(), "company": setting(c, "company_name")}
    k = _try(_fn("kpi.finance"), c, u, {})
    out["finance"] = (k or {}).get("kpis", [])
    ins_ = _try(_fn("insight.overview"), c, u, {})
    if ins_:
        out["projects"] = ins_.get("projects", [])
        out["kpis"] = ins_.get("kpis", {})
        out["cash"] = ins_.get("cash")
        out["risks"] = ins_.get("risks")
    d = _try(_fn("dash.summary"), c, u, {})
    if d:
        out["approvals"] = d.get("approvals")
        out["stock_value"] = d.get("stock_value")
        out["open_po_value"] = d.get("open_po_value")
        out["pending_deliveries"] = d.get("pending_deliveries")
        out["payables_due"] = d.get("payables_due")
        out["receivables_due"] = d.get("receivables_due")
        out["cash_bank"] = d.get("cash_bank", [])
        out["breakdowns"] = len(d.get("breakdowns") or [])
        out["maintenance_due"] = len(d.get("maintenance_due") or [])
    out["budget"] = q(c, "SELECT p.id project_id, p.code, p.name, SUM(b.amount) budget, "
                         "(SELECT COALESCE(SUM(l.debit-l.credit),0) FROM voucher_lines l JOIN vouchers v ON "
                         " v.id=l.voucher_id JOIN accounts ac ON ac.id=l.account_id WHERE l.project_id=p.id AND "
                         " ac.type='expense' AND v.status IN ('posted','reversed')) actual "
                         "FROM projects p LEFT JOIN budgets b ON b.project_id=p.id "
                         "WHERE p.status='active' AND COALESCE(p.kind,'') NOT IN ('trading','general') "
                         "GROUP BY p.id ORDER BY p.code")
    out["stock_locations"] = stock_locations(c, u, {"summary": 1})["groups"]
    return out


@api("ws.project_overview", "project", "view")
def project_overview(c, u, a):
    """The project dashboard: the control room, store, budget and approvals of one project."""
    core.need(a, "project_id")
    pid = int(a["project_id"])
    out = {"as_of": core.today(), "project": core.get(c, "projects", pid, "Project")}
    cr = _try(_fn("control.room"), c, u, {"project_id": pid})
    if cr:
        for k in ("health", "progress", "cost", "billing", "resources", "commercial",
                  "critical", "milestones", "attention"):
            out[k] = cr.get(k)
    sv = _try(_fn("store.view"), c, u, {"project_id": pid})
    out["store"] = (sv or {}).get("summary", [])
    out["budget"] = q1(c, "SELECT SUM(amount) budget FROM budgets WHERE project_id=?", (pid,))
    appr = _try(_fn("dash.approvals"), c, u, {}) or []
    out["approvals"] = [x for x in appr if not x.get("project_id") or int(x["project_id"]) == pid]
    out["issues_open"] = val(c, "SELECT COUNT(*) FROM fld_issues WHERE project_id=? AND status IN "
                                "('open','in_progress')", (pid,)) if _has(c, "fld_issues") else 0
    return out


def _has(c, t):
    return bool(c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (t,)).fetchone())


@api("ws.stock_locations", "inventory", "view")
def stock_locations(c, u, a):
    """Company stock split into project stores, central store, trading store and in transit,
    added once, next to the inventory accounts in the ledger."""
    rows = q(c, "SELECT b.project_id, p.code pcode, p.name pname, COALESCE(p.kind,'') kind, s.type store_type, "
                "s.name store, COUNT(DISTINCT b.material_id) items, SUM(b.qty) qty, SUM(b.value) value "
                "FROM stock_balances b JOIN stores s ON s.id=b.store_id JOIN projects p ON p.id=b.project_id "
                "WHERE ABS(b.qty) > 1e-9 OR ABS(b.value) > 0.005 "
                "GROUP BY b.project_id, b.store_id ORDER BY p.code, s.type")
    groups = {"project": [], "central": [], "trading": [], "transit": []}
    for r in rows:
        g = "transit" if r["store_type"] == "transit" else \
            ("trading" if r["kind"] == "trading" else ("central" if r["kind"] == "general" else "project"))
        groups[g].append(r)
    total = core.r2(sum(r["value"] or 0 for r in rows))
    ledger = core.r2(val(c, "SELECT COALESCE(SUM(l.debit-l.credit),0) + "
                            "(SELECT COALESCE(SUM(a2.opening_balance),0) FROM accounts a2 WHERE a2.role LIKE 'inventory%') "
                            "FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id "
                            "JOIN accounts ac ON ac.id=l.account_id WHERE ac.role LIKE 'inventory%' "
                            "AND v.status IN ('posted','reversed')"))
    out = {"groups": {g: {"rows": rs, "value": core.r2(sum(x["value"] or 0 for x in rs))}
                      for g, rs in groups.items()},
           "total": total, "ledger_inventory": ledger, "difference": core.r2(total - ledger)}
    if a.get("summary"):
        out["groups"] = {g: {"stores": len(v["rows"]), "value": v["value"]} for g, v in out["groups"].items()}
    return out


@api("ws.central_setup", "masters", "edit")
def central_setup(c, u, a):
    """Make sure the central store exists: 2.19's GENERAL cost centre with its main store
    renamed Central Store."""
    f = _fn("proc.setup")
    if f:
        f(c, u, {"only": "general"})
    p = q1(c, "SELECT id FROM projects WHERE kind='general' ORDER BY id LIMIT 1")
    if not p:
        raise ApiError("The general cost centre could not be created.")
    core.ensure_project_stores(c, p["id"])
    st = q1(c, "SELECT id, name FROM stores WHERE project_id=? AND type='main'", (p["id"],))
    if st and st["name"] != "Central Store":
        upd(c, "stores", st["id"], {"name": "Central Store"})
    return {"project_id": p["id"], "store_id": st["id"] if st else None}


@api("ws.compare", "project", "view")
def ws_compare(c, u, a):
    """One row per project: contract, progress, SPI, CPI, budget, cost, stock and receivable."""
    ins_ = _try(_fn("insight.overview"), c, u, {}) or {}
    rows = ins_.get("projects", [])
    for r in rows:
        r["budget"] = val(c, "SELECT SUM(amount) FROM budgets WHERE project_id=?", (r["id"],)) or 0
        r["stock_value"] = core.r2(val(c, "SELECT COALESCE(SUM(value),0) FROM stock_balances WHERE project_id=?",
                                       (r["id"],)))
    return {"rows": rows, "kpis": ins_.get("kpis", {}), "as_of": core.today()}


@api("ws.project_cost", "accounts", "view")
def project_cost(c, u, a):
    """Cost by project straight from the posted ledger; the total equals the company ledger."""
    frm, to = a.get("from") or "0000-01-01", a.get("to") or "9999-12-31"
    rows = q(c, "SELECT l.project_id, p.code, p.name, COALESCE(p.kind,'') kind, "
                "SUM(CASE WHEN ac.type='expense' THEN l.debit-l.credit ELSE 0 END) cost, "
                "SUM(CASE WHEN ac.type='income' THEN l.credit-l.debit ELSE 0 END) income "
                "FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id "
                "JOIN accounts ac ON ac.id=l.account_id LEFT JOIN projects p ON p.id=l.project_id "
                "WHERE v.status IN ('posted','reversed') AND ac.type IN ('expense','income') "
                "AND v.date BETWEEN ? AND ? GROUP BY l.project_id ORDER BY cost DESC", (frm, to))
    for r in rows:
        if not r["project_id"]:
            r["code"], r["name"] = "", "Not allocated to a project"
    tot_cost = core.r2(sum(r["cost"] or 0 for r in rows))
    tot_inc = core.r2(sum(r["income"] or 0 for r in rows))
    return {"rows": rows, "total_cost": tot_cost, "total_income": tot_inc,
            "from": None if frm.startswith("0000") else frm, "to": None if to.startswith("9999") else to}
