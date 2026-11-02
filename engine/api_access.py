"""BuildCore - Job and Where: one place to set up a person.

Each person gets a Job (the role template of 2.20, same rights) and a Where:

  Head office    every project; the Company Workspace as the job allows
  These projects only the projects ticked, and no Company Workspace

Each job also lists the menu groups it shows (the familiar groups, names and order unchanged); a person can
always open "Show all my screens". Nothing here widens or narrows what the engine allows for an existing person:
people set up before this have no Where yet and keep exactly their old access (they are listed under Check
access when they see every project only because nothing was ticked).

Also: Administration > Users now returns each person's projects (the old People list read a list without them,
so it showed "All", opened the assign window with nothing ticked, and saving wiped the assignments), and saving
a person keeps their location, phone and email.
"""
import json

import core
from core import ApiError, audit, q, q1, setting, upd, val
import api_inventory as inv
from api_inventory import api

GROUPS = ["Overview", "Work", "Commercial", "Inventory", "Procurement", "Accounts", "Plant", "Assets", "Fixed assets",
          "Resources & rates", "Equipment", "Master data", "Administration"]
PROJECT_GROUPS = ["Overview", "Work", "Commercial", "Inventory", "Procurement", "Equipment", "Plant", "Resources & rates",
                  "Master data"]

# menu groups each built-in job shows (None = all)
DEFAULT_MENUS = {
    "admin": None,
    "director": None,
    "viewer": None,
    "accountant": ["Overview", "Accounts", "Procurement", "Commercial"],
    "finance_manager": ["Overview", "Accounts", "Procurement", "Commercial", "Assets", "Fixed assets"],
    "project_accountant": ["Overview", "Accounts", "Procurement"],
    "storekeeper": ["Overview", "Inventory", "Procurement"],
    "procurement_officer": ["Overview", "Procurement", "Inventory", "Master data"],
    "project_manager": PROJECT_GROUPS,
    "site_engineer": ["Overview", "Work", "Inventory", "Equipment"],
    "quantity_surveyor": ["Overview", "Commercial", "Work"],
    "site_supervisor": ["Overview", "Work", "Equipment"],
    "equipment_manager": ["Overview", "Equipment", "Plant", "Assets"],
}
# built-in names that read better as jobs (changed only while the name is still the original)
RENAME = {"project_accountant": ("Project accountant", "Site accountant"),
          "procurement_officer": ("Procurement officer", "Purchase officer"),
          "equipment_manager": ("Equipment manager", "Equipment / plant manager"),
          "director": ("Director", "Director / owner")}
WHERE_USUAL = {"project_accountant": "projects", "storekeeper": "projects", "project_manager": "projects",
               "site_engineer": "projects", "quantity_surveyor": "projects", "site_supervisor": "projects"}

_ORIG = {}
_DONE = set()


def W():
    import api_workspace
    return api_workspace


def access_of(user):
    """'all' (head office), 'projects' (these projects) or None (set up before Job and Where)."""
    try:
        v = user["access"] if "access" in user.keys() else None
    except Exception:
        v = None
    return v if v in ("all", "projects") else None


def ids_of(user):
    try:
        raw = user["project_ids"] if "project_ids" in user.keys() else None
    except Exception:
        raw = None
    return [int(x) for x in str(raw or "").replace(";", ",").split(",") if x.strip().isdigit()]


# ───────────────────────── the engine's view of a person ─────────────────────────
def template(c, user):
    t = _ORIG["template"](c, user)
    acc = access_of(user) if user else None
    if acc == "projects":
        t = dict(t, company=False, projects="these")
    elif acc == "all":
        t = dict(t, projects="all")
    return t


def allowed_projects(c, user):
    if user and access_of(user) == "projects":
        return set(ids_of(user))            # never "every project" by accident
    if user and access_of(user) == "all":
        return None
    return _ORIG["allowed_projects"](c, user)


def menus_of(c, role):
    r = q1(c, "SELECT menus FROM ws_roles WHERE key=?", (role,))
    if not r or not r["menus"]:
        return None
    try:
        v = json.loads(r["menus"])
    except ValueError:
        return None
    return v if isinstance(v, list) and v else None


# ───────────────────────── wrappers ─────────────────────────
def _wrap(name, factory):
    cur = inv.FUNCS.get(name)
    if not cur or name in _DONE:
        return
    _DONE.add(name)
    inv.FUNCS[name] = (factory(cur[0]), cur[1], cur[2], cur[3])


def _users_w(orig):
    def users(c, u, a):
        rows = orig(c, u, a)
        extra = {r["id"]: r for r in q(c, "SELECT id, project_ids, access FROM users")}
        roles = W().roles(c)
        for r in rows:
            x = extra.get(r["id"]) or {}
            r["project_ids"] = x.get("project_ids") or ""
            r["access"] = x.get("access")
            t = roles.get(r["role"]) or {}
            ids = [int(i) for i in str(r["project_ids"]).split(",") if i.strip().isdigit()]
            if r["access"] == "projects":
                r["where"] = "projects"
            elif r["access"] == "all" or t.get("projects") == "all":
                r["where"] = "all"
            else:
                r["where"] = "projects" if ids else "unset"   # set up before Job and Where
            r["job"] = t.get("name") or r["role"]
        return rows
    return users


def _user_save_w(orig):
    def user_save(c, u, a):
        r = dict(a.get("row") or {})
        old = q1(c, "SELECT * FROM users WHERE id=?", (int(r["id"]),)) if r.get("id") else None
        for k in ("location", "phone", "email"):          # a save that does not show these keeps them
            if old and k not in r:
                r[k] = old[k]
        where = r.get("access")
        if where not in (None, "", "all", "projects"):
            raise ApiError("Choose where this person works: head office or these projects.")
        ids = r.get("project_ids")
        if isinstance(ids, str):
            ids = [x for x in ids.split(",") if x.strip()]
        if where == "projects":
            ids = [int(x) for x in (ids or [])]
            known = {p["id"] for p in q(c, "SELECT id FROM projects")}
            ids = [x for x in ids if x in known]
            if not ids:
                raise ApiError("Tick at least one project for %s, or choose Head office." % (r.get("name") or "this person"))
            r["project_ids"] = ids
        elif where == "all":
            r["project_ids"] = []
        res = orig(c, u, dict(a, row=r))
        if where:
            upd(c, "users", res["id"], {"access": where})
            audit(c, u, "access", "users", res["id"], {"where": where, "projects": r.get("project_ids")})
        return res
    return user_save


def _me_w(orig):
    def me(c, u, a):
        out = orig(c, u, a)
        ws = out.get("workspace")
        if ws is not None:
            ws["menus"] = menus_of(c, u["role"])
            ws["access"] = access_of(u)
            ws["groups"] = GROUPS
        return out
    return me


def _roles_w(orig):
    def roles(c, u, a):
        out = orig(c, u, a)
        for r in out["roles"]:
            x = q1(c, "SELECT menus, description FROM ws_roles WHERE id=?", (r["id"],)) or {}
            try:
                r["menus"] = json.loads(x.get("menus") or "null")
            except ValueError:
                r["menus"] = None
            r["description"] = x.get("description")
            r["where_usual"] = WHERE_USUAL.get(r["key"], "all" if r["projects"] == "all" else "projects")
        out["groups"] = GROUPS
        return out
    return roles


def _role_save_w(orig):
    def role_save(c, u, a):
        res = orig(c, u, a)
        r = a.get("row") or {}
        data = {}
        if "menus" in r:
            m = [g for g in (r.get("menus") or []) if isinstance(g, str)]
            data["menus"] = json.dumps(m) if m and set(m) != set(GROUPS) else None
        if "description" in r:
            data["description"] = (r.get("description") or "").strip()[:500] or None
        if data:
            c.execute("UPDATE ws_roles SET %s WHERE id=?" % ",".join(k + "=?" for k in data), list(data.values()) + [res["id"]])
        return res
    return role_save


# ───────────────────────── Check access ─────────────────────────
@api("ws.access_check", "admin", "view")
def access_check(c, u, a):
    """People who see every project only because nothing was ticked for them (set up before Job and Where)."""
    out = []
    roles = W().roles(c)
    for r in q(c, "SELECT id, username, name, role, project_ids, access FROM users WHERE active=1 ORDER BY name"):
        t = roles.get(r["role"]) or {}
        if r["access"] in ("all", "projects") or t.get("projects") == "all":
            continue
        if not [x for x in str(r["project_ids"] or "").split(",") if x.strip().isdigit()]:
            out.append({"id": r["id"], "username": r["username"], "name": r["name"], "job": t.get("name") or r["role"],
                        "why": "Sees every project because no project is ticked"})
    return out


# ───────────────────────── project Team ─────────────────────────
def _team(c, pid):
    roles = W().roles(c)
    members, office, other = [], [], []
    for r in q(c, "SELECT id, username, name, role, project_ids, access, active FROM users WHERE active=1 ORDER BY name"):
        t = roles.get(r["role"]) or {}
        ids = [int(x) for x in str(r["project_ids"] or "").split(",") if x.strip().isdigit()]
        row = {"id": r["id"], "username": r["username"], "name": r["name"], "job": t.get("name") or r["role"]}
        if r["access"] == "all" or (r["access"] is None and t.get("projects") == "all"):
            office.append(row)
        elif pid in ids:
            members.append(row)
        else:
            row["unset"] = not ids and r["access"] is None
            other.append(row)
    return members, office, other


@api("ws.team", "admin", "view")
def team(c, u, a):
    pid = int(a["project_id"])
    m, o, x = _team(c, pid)
    return {"members": m, "head_office": o, "others": x}


def _set_ids(c, u, uid, ids, why):
    upd(c, "users", uid, {"project_ids": ",".join(str(i) for i in sorted(set(ids))), "access": "projects"})
    audit(c, u, "team", "users", uid, {"projects": sorted(set(ids)), "why": why})


@api("ws.team_add", "admin", "edit")
def team_add(c, u, a):
    pid = int(a["project_id"])
    core.get(c, "projects", pid, "Project")
    n = 0
    for uid in a.get("user_ids") or [a.get("user_id")]:
        usr = core.get(c, "users", int(uid), "Person")
        t = W().roles(c).get(usr["role"]) or {}
        if usr["access"] == "all" or (usr["access"] is None and t.get("projects") == "all"):
            raise ApiError("%s works at head office and already sees every project." % usr["name"])
        ids = ids_of(usr)
        if pid not in ids:
            _set_ids(c, u, usr["id"], ids + [pid], "added to team")
            n += 1
    return {"added": n}


@api("ws.team_remove", "admin", "edit")
def team_remove(c, u, a):
    pid = int(a["project_id"])
    usr = core.get(c, "users", int(a["user_id"]), "Person")
    ids = [i for i in ids_of(usr) if i != pid]
    if not ids:
        raise ApiError("%s would have no project left. Give them another project first, or set them to Head office "
                       "in Administration › Users." % usr["name"])
    _set_ids(c, u, usr["id"], ids, "removed from team")
    return True


@api("ws.team_copy", "admin", "edit")
def team_copy(c, u, a):
    """Start a new project's team from another project's."""
    src, dst = int(a["from_project"]), int(a["project_id"])
    if src == dst:
        raise ApiError("Choose another project to copy from.")
    m, _o, _x = _team(c, src)
    n = 0
    for p in m:
        usr = core.get(c, "users", p["id"])
        ids = ids_of(usr)
        if dst not in ids:
            _set_ids(c, u, usr["id"], ids + [dst], "team copied from project %s" % src)
            n += 1
    return {"added": n}


# ───────────────────────── start-up ─────────────────────────
def init_access(c):
    have = {r[1] for r in c.execute("PRAGMA table_info(users)")}
    if "access" not in have:
        c.execute("ALTER TABLE users ADD COLUMN access TEXT")
    have = {r[1] for r in c.execute("PRAGMA table_info(ws_roles)")}
    if not have:
        return
    for col in ("menus", "description"):
        if col not in have:
            c.execute("ALTER TABLE ws_roles ADD COLUMN %s TEXT" % col)
    if not q1(c, "SELECT 1 FROM settings WHERE key='access_jobs_seeded'"):
        for key, menus in DEFAULT_MENUS.items():
            if menus:
                c.execute("UPDATE ws_roles SET menus=? WHERE key=? AND menus IS NULL", (json.dumps(menus), key))
        for key, (old, new) in RENAME.items():
            c.execute("UPDATE ws_roles SET name=? WHERE key=? AND name=?", (new, key, old))
        c.execute("INSERT INTO settings(key, value) VALUES('access_jobs_seeded', '1')")
    w = W()
    w.load_roles(c)
    if "template" not in _ORIG:
        _ORIG["template"], _ORIG["allowed_projects"] = w.template, w.allowed_projects
        w.template, w.allowed_projects = template, allowed_projects
    _wrap("admin.users", _users_w)
    _wrap("admin.user_save", _user_save_w)
    _wrap("auth.me", _me_w)
    _wrap("ws.roles", _roles_w)
    _wrap("ws.role_save", _role_save_w)
