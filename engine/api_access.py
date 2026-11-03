"""
BuildCore 2.44 - People and access: Job + Where.

One screen sets a person up: their job (the 2.20 role templates, same keys and the same rights) and where
they work (head office - all projects, or chosen projects). Each job also lists the menu groups it shows,
so a storekeeper sees the store, an accountant sees accounts; the 2.20 engine checks are unchanged and
still decide what a person may open.

  1. users.ws_where     'all' = head office, every project; 'projects' = only the projects ticked (and the
                        Project Workspace only); empty = as before 2.44 (the job decides).
  2. ws_roles.menu      JSON list of the menu groups the job shows; empty = every group. Built-in jobs get a
                        suggested list once, when this update first runs. Setting acc_job_menus (1) turns the
                        job menus on or off for the whole company.
  3. Project teams      acc.team / acc.team_set / acc.team_copy write the same users.project_ids as the
                        Users screen, from the project side.
  4. Fix                admin.users and adm.users2 now return project_ids, so the 2.20 People list and the
                        assignment window show the real assignments (they showed "All" and saving wiped them).

New columns and one setting only: no existing row, right, id or entry is changed.
"""
import json

import core
from core import ApiError, audit, q, q1, setting, upd, val
import api_inventory as inv
from api_inventory import api
import api_workspace as W

VERSION = "2.44.0"
FLAG = "_bco244"
ALWAYS = ["Overview", "Tools & views"]          # every job keeps these: My work, approvals, help, search

# Suggested menu groups per built-in job (classic group names; Overview and Tools & views always show).
# None = every group the job's rights allow, as before.
MENUS = {
    "admin": None, "director": None, "viewer": None, "project_manager": None,
    "finance_manager": ["Accounts", "Commercial", "Procurement", "Assets", "Fixed assets"],
    "accountant": ["Accounts", "Commercial", "Procurement", "Assets", "Fixed assets", "Master data"],
    "project_accountant": ["Accounts", "Procurement"],
    "storekeeper": ["Inventory", "Procurement"],
    "procurement_officer": ["Procurement", "Inventory", "Master data"],
    "site_engineer": ["Work", "Inventory", "Equipment"],
    "quantity_surveyor": ["Commercial", "Work"],
    "site_supervisor": ["Work", "Equipment"],
    "equipment_manager": ["Equipment", "Plant", "Assets"],
}

# One line per job for the person window: what this job is for.
ABOUT = {
    "admin": "Everything, including users, settings and backups.",
    "director": "Sees everything and approves; does not enter day-to-day records.",
    "accountant": "Company books: vouchers, payments, bills, VAT/TDS, bank, fixed assets.",
    "finance_manager": "Approves money: payments, accounts, assets, budgets.",
    "procurement_officer": "Purchase requests, quotations, purchase orders, suppliers.",
    "equipment_manager": "Machines: logsheets, maintenance, hire, equipment cost.",
    "viewer": "Sees everything, changes nothing.",
    "project_manager": "Runs the project: approves DPR, store, purchases, billing.",
    "site_engineer": "DPR, quality, requisitions, equipment logs on site.",
    "quantity_surveyor": "BOQ, measurements, IPC billing, variations.",
    "storekeeper": "Store: receipts (GRN), issues, transfers, returns, stock counts.",
    "project_accountant": "Site accounts: vouchers, purchase bills and payment requests of the project.",
    "site_supervisor": "Daily site work: DPR entries, equipment logs, quality checks.",
}


# ───────────────────── data ─────────────────────
def init_access(c):
    have_u = {r[1] for r in c.execute("PRAGMA table_info(users)")}
    if "ws_where" not in have_u:
        c.execute("ALTER TABLE users ADD COLUMN ws_where TEXT")
    have_r = {r[1] for r in c.execute("PRAGMA table_info(ws_roles)")}
    if "menu" not in have_r:
        c.execute("ALTER TABLE ws_roles ADD COLUMN menu TEXT")
    if setting(c, "acc_menus_seeded") != "1":
        # once: the suggested menus for the built-in jobs (a job someone already gave a menu keeps it)
        for key, groups in MENUS.items():
            if groups is not None:
                c.execute("UPDATE ws_roles SET menu=? WHERE key=? AND (menu IS NULL OR menu='')",
                          (json.dumps(groups), key))
        _set(c, "acc_menus_seeded", "1")
    if setting(c, "acc_job_menus") is None:
        _set(c, "acc_job_menus", "1")
    _patch()


def _set(c, k, v):
    c.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (k, v))


def _where(user):
    try:
        w = user["ws_where"] if "ws_where" in user.keys() else None
    except Exception:
        w = None
    return w if w in ("all", "projects") else None


def _ids(raw):
    out = []
    for x in str(raw or "").replace(";", ",").split(","):
        x = x.strip()
        if x.isdigit() and int(x) not in out:
            out.append(int(x))
    return out


def _menu(r):
    try:
        m = json.loads(r["menu"]) if r and r.get("menu") else None
    except ValueError:
        m = None
    return m if isinstance(m, list) else None


def job_menu(c, role):
    """The menu groups a job shows, or None for every group."""
    if role == "admin" or setting(c, "acc_job_menus") == "0":
        return None
    r = q1(c, "SELECT menu FROM ws_roles WHERE key=?", (role,))
    m = _menu(r)
    return (ALWAYS + [g for g in m if g not in ALWAYS]) if m else None


# ───────────────────── engine: Where decides the projects ─────────────────────
def _patch():
    if getattr(W.allowed_projects, FLAG, False):
        _wrap_funcs()
        return
    orig_allowed, orig_template = W.allowed_projects, W.template

    def allowed_projects(c, user, _orig=orig_allowed):
        if not user:
            return _orig(c, user)
        role = user["role"] if "role" in user.keys() else None
        w = _where(user)
        if role == "admin" or w is None:
            return _orig(c, user)
        if w == "all":
            return None
        return set(_ids(user["project_ids"] if "project_ids" in user.keys() else ""))

    def template(c, user, _orig=orig_template):
        t = _orig(c, user)
        if user and _where(user) == "projects" and user["role"] != "admin" and t.get("company"):
            t = dict(t)
            t["company"] = False          # a person placed on chosen projects works in the Project Workspace
        return t

    setattr(allowed_projects, FLAG, True)
    setattr(template, FLAG, True)
    W.allowed_projects = allowed_projects
    W.template = template
    _wrap_funcs()


def _keep_flags(new, old):
    for k in dir(old):
        if k.startswith("_bco"):
            try:
                setattr(new, k, getattr(old, k))
            except Exception:
                pass
    setattr(new, FLAG, True)
    return new


def _wrap(name, make):
    cur = inv.FUNCS.get(name)
    if not cur or getattr(cur[0], FLAG, False):
        return
    inv.FUNCS[name] = (_keep_flags(make(cur[0]), cur[0]),) + tuple(cur[1:])


def _wrap_funcs():
    def users_list(orig):
        def f(c, u, a):
            rows = orig(c, u, a)
            if isinstance(rows, list):
                extra = {r["id"]: r for r in q(c, "SELECT id, project_ids, ws_where, ws_default FROM users")}
                for r in rows:
                    x = extra.get(r.get("id")) or {}
                    r["project_ids"] = ",".join(str(i) for i in _ids(x.get("project_ids")))
                    r["ws_where"] = x.get("ws_where")
            return rows
        return f
    _wrap("admin.users", users_list)
    _wrap("adm.users2", users_list)

    def user_save(orig):
        def f(c, u, a):
            r = a.get("row") or {}
            where = r.get("ws_where", "__none__")
            if where not in ("__none__", None, "", "all", "projects"):
                raise ApiError("Where must be head office (all projects) or chosen projects.")
            if where == "projects":
                ids = r.get("project_ids")
                if ids is None and r.get("id"):
                    ids = (q1(c, "SELECT project_ids FROM users WHERE id=?", (int(r["id"]),)) or {}).get("project_ids")
                if not _ids(",".join(str(x) for x in ids) if isinstance(ids, (list, tuple)) else ids):
                    raise ApiError("Choose at least one project for this person, or choose Head office - all projects.")
            res = orig(c, u, a)
            if where != "__none__":
                upd(c, "users", res["id"], {"ws_where": where or None})
            return res
        return f
    _wrap("admin.user_save", user_save)

    def me(orig):
        def f(c, u, a):
            out = orig(c, u, a)
            ws = out.get("workspace")
            if isinstance(ws, dict):
                ws["menu"] = job_menu(c, u["role"])
                ws["where"] = _where(u)
                ws["job_about"] = ABOUT.get(u["role"])
            return out
        return f
    _wrap("auth.me", me)

    def role_save(orig):
        def f(c, u, a):
            res = orig(c, u, a)
            r = a.get("row") or {}
            if "menu" in r:
                m = r.get("menu")
                m = [str(g) for g in m] if isinstance(m, (list, tuple)) and m else None
                upd(c, "ws_roles", res["id"], {"menu": json.dumps(m) if m else None})
            return res
        return f
    _wrap("ws.role_save", role_save)

    def roles(orig):
        def f(c, u, a):
            out = orig(c, u, a)
            menus = {r["key"]: _menu(r) for r in q(c, "SELECT key, menu FROM ws_roles")}
            for r in out.get("roles", []):
                r["menu"] = menus.get(r["key"])
                r["about"] = ABOUT.get(r["key"], "")
            out["always"] = ALWAYS
            out["job_menus"] = setting(c, "acc_job_menus") != "0"
            return out
        return f
    _wrap("ws.roles", roles)


# ───────────────────── the People screen ─────────────────────
def _projects(c):
    return q(c, "SELECT id, code, name, status FROM projects WHERE COALESCE(kind,'') NOT IN ('trading','general') "
                "ORDER BY status<>'active', code")


def _person(c, r, tpl, pmap):
    t = tpl.get(r["role"]) or {"name": r["role"], "company": False, "projects": "all"}
    w = r.get("ws_where") if r.get("ws_where") in ("all", "projects") else None
    ids = _ids(r.get("project_ids"))
    if r["role"] == "admin":
        where, sees = "Head office - all projects", "all"
    elif w == "all":
        where, sees = "Head office - all projects", "all"
    elif w == "projects":
        where, sees = "These projects", "chosen"
    elif t["projects"] == "all":
        where, sees = "Head office - all projects", "all"
    elif ids:
        where, sees = "These projects", "chosen"
    else:
        where, sees = "Nothing ticked - sees all projects", "unset"
    return {"id": r["id"], "username": r["username"], "name": r["name"], "role": r["role"], "job": t["name"],
            "active": r["active"], "ws_where": w, "where": where, "sees": sees,
            "workspace": "Company + Project" if (t["company"] and w != "projects") else "Project",
            "project_ids": ids, "projects": [pmap[i]["code"] for i in ids if i in pmap],
            "last_login": val(c, "SELECT MAX(ts) FROM audit WHERE action='login' AND user_id=?", (r["id"],)) or None}


@api("acc.people", "admin", "view")
def people(c, u, a):
    """Everyone with job, where they work and their projects, plus the Check access list."""
    W.load_roles(c)
    tpl = W.roles(c)
    pj = _projects(c)
    pmap = {p["id"]: p for p in pj}
    rows = q(c, "SELECT id, username, name, role, active, project_ids, ws_where FROM users ORDER BY active DESC, name")
    out = [_person(c, r, tpl, pmap) for r in rows]
    check = []
    for p in out:
        if not p["active"] or p["role"] == "admin":
            continue
        if p["sees"] == "unset":
            check.append({"id": p["id"], "name": p["name"], "job": p["job"],
                          "problem": "Nothing is ticked, so this person can open every project. Choose their projects, or Head office."})
        elif p["sees"] == "chosen" and not p["project_ids"]:
            check.append({"id": p["id"], "name": p["name"], "job": p["job"],
                          "problem": "On chosen projects but none is ticked, so this person cannot open any project."})
        elif p["sees"] == "chosen" and any(pmap.get(i, {}).get("status") not in (None, "active") for i in p["project_ids"]) \
                and not any(pmap.get(i, {}).get("status") == "active" for i in p["project_ids"]):
            check.append({"id": p["id"], "name": p["name"], "job": p["job"],
                          "problem": "Only on closed projects; this person has no active project to work in."})
    jobs = [{"key": k, "name": v["name"], "company": v["company"], "projects": v["projects"],
             "about": ABOUT.get(k, ""), "menu": job_menu(c, k) if k != "admin" else None}
            for k, v in tpl.items()]
    order = {k: i for i, k in enumerate(r["key"] for r in q(c, "SELECT key FROM ws_roles ORDER BY sort, id"))}
    jobs.sort(key=lambda j: order.get(j["key"], 999))
    return {"people": out, "check": check, "jobs": jobs, "projects": pj,
            "job_menus": setting(c, "acc_job_menus") != "0", "always": ALWAYS}


@api("acc.settings", "admin", "edit")
def acc_settings(c, u, a):
    if "job_menus" in a:
        v = "0" if a.get("job_menus") in (0, "0", False) else "1"
        _set(c, "acc_job_menus", v)
        audit(c, u, "settings", "settings", None, {"acc_job_menus": v})
    return {"job_menus": setting(c, "acc_job_menus") != "0"}


# ───────────────────── project teams ─────────────────────
@api("acc.team", "admin", "view")
def team(c, u, a):
    """Who works on a project: people placed on it, and the head-office people who see every project."""
    core.need(a, "project_id")
    pid = int(a["project_id"])
    core.get(c, "projects", pid, "Project")
    W.load_roles(c)
    tpl = W.roles(c)
    pmap = {p["id"]: p for p in _projects(c)}
    members, head = [], []
    for r in q(c, "SELECT id, username, name, role, active, project_ids, ws_where FROM users WHERE active=1 ORDER BY name"):
        p = _person(c, r, tpl, pmap)
        if p["sees"] in ("all", "unset"):
            head.append({"id": p["id"], "name": p["name"], "job": p["job"],
                         "why": "nothing ticked" if p["sees"] == "unset" else "head office"})
        elif pid in p["project_ids"]:
            p["also"] = [pmap[i]["code"] for i in p["project_ids"] if i != pid and i in pmap]
            members.append(p)
    return {"project": pmap.get(pid) or core.get(c, "projects", pid, "Project"), "members": members, "head_office": head}


def _set_ids(c, u, uid, ids, why):
    usr = core.get(c, "users", uid, "User")
    before = _ids(usr.get("project_ids"))
    data = {"project_ids": ",".join(str(i) for i in ids)}
    if usr["role"] != "admin" and _where(usr) != "all":
        data["ws_where"] = "projects"
    upd(c, "users", uid, data)
    audit(c, u, why, "users", uid, {"project_ids_before": before, "project_ids": ids})


@api("acc.team_set", "admin", "edit")
def team_set(c, u, a):
    """Add people to a project, or take them off it."""
    core.need(a, "project_id")
    pid = int(a["project_id"])
    core.get(c, "projects", pid, "Project")
    added, removed, skipped = [], [], []
    for uid in [int(x) for x in (a.get("add") or [])]:
        usr = core.get(c, "users", uid, "User")
        if usr["role"] == "admin" or _where(usr) == "all":
            skipped.append(usr["name"] + " (head office: already sees every project)")
            continue
        ids = _ids(usr.get("project_ids"))
        if pid not in ids:
            _set_ids(c, u, uid, ids + [pid], "team_add")
            added.append(usr["name"])
    for uid in [int(x) for x in (a.get("remove") or [])]:
        usr = core.get(c, "users", uid, "User")
        ids = _ids(usr.get("project_ids"))
        if pid in ids:
            _set_ids(c, u, uid, [i for i in ids if i != pid], "team_remove")
            removed.append(usr["name"] + ("" if len(ids) > 1 else " (now on no project)"))
    return {"added": added, "removed": removed, "skipped": skipped}


@api("acc.team_copy", "admin", "edit")
def team_copy(c, u, a):
    """Put everyone placed on another project onto this one too (nobody is taken off anything)."""
    core.need(a, "project_id")
    core.need(a, "from_project")
    pid, src = int(a["project_id"]), int(a["from_project"])
    if pid == src:
        raise ApiError("Choose a different project to copy the team from.")
    core.get(c, "projects", pid, "Project")
    core.get(c, "projects", src, "Project")
    add = [r["id"] for r in q(c, "SELECT id, project_ids, ws_where, role FROM users WHERE active=1")
           if src in _ids(r["project_ids"]) and r["role"] != "admin" and r["ws_where"] != "all"]
    return team_set(c, u, {"project_id": pid, "add": add})
