"""Job and Where - acceptance checks (engine on SQLite, a fresh company; the licence check is switched off for the test only).

    python tests/kits/kit_access.py
"""
import os, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["BCO_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(ROOT, "engine")); os.chdir(os.path.join(ROOT, "engine"))
import core, server, api_inventory as inv
from core import q1, val
core.DB_PATH = os.path.join(os.environ["BCO_DATA_DIR"], "t.db"); core.init_db()
import api_license; api_license.status = lambda *a, **k: {"active": True, "reason": "", "max_users": 0}   # test only: no licence key here
R = []
def ok(name, cond, det=""): R.append(cond); print("PASS" if cond else "FAIL", name, det)
def call(fn, a=None, tok=None):
    return server.call(fn, a or {}, tok)
def err(fn, a=None, tok=None):
    try: call(fn, a, tok); return None
    except Exception as e: return str(e)
tok = call("auth.setup", {"username": "admin", "password": "secret1", "name": "Admin"})["token"]
for i in (1, 2, 3):
    call("master.save", {"table": "projects", "row": {"code": "P%d" % i, "name": "Project %d" % i, "status": "active"}}, tok) if "master.save" in inv.FUNCS else None
c = core.connect()
if not val(c, "SELECT COUNT(*) FROM projects"):
    for i in (1, 2, 3): c.execute("INSERT INTO projects(code,name,status) VALUES(?,?, 'active')", ("P%d" % i, "Project %d" % i))
# a storekeeper set up the old way (nothing ticked) with a location and phone
c.execute("INSERT INTO users(username,name,role,active,location,phone) VALUES('ram','Ram','storekeeper',1,'Yard','9800')")
c.commit()
P = {r["code"]: r["id"] for r in core.q(c, "SELECT id, code FROM projects")}
c.close()
ok("old storekeeper listed in Check access", [r["username"] for r in call("ws.access_check", {}, tok)] == ["ram"])
rows = {r["username"]: r for r in call("admin.users", {}, tok)}
ok("Users list says nothing ticked = all", rows["ram"]["where"] == "unset")
ram = rows["ram"]
e = err("admin.user_save", {"row": {"id": ram["id"], "username": "ram", "name": "Ram", "role": "storekeeper", "active": 1, "access": "projects", "project_ids": []}}, tok)
ok("These projects with none ticked refused", e and "Tick at least one project" in e, e)
call("admin.user_save", {"row": {"id": ram["id"], "username": "ram", "name": "Ram", "role": "storekeeper", "active": 1, "access": "projects", "project_ids": [P["P1"]], "password": "secret2"}}, tok)
r = {x["username"]: x for x in call("admin.users", {}, tok)}["ram"]
ok("assignments shown (bug fixed)", r["where"] == "projects" and r["project_ids"] == str(P["P1"]), r["project_ids"])
c = core.connect(); u = q1(c, "SELECT * FROM users WHERE username='ram'"); c.close()
ok("location and phone kept on save", u["location"] == "Yard" and u["phone"] == "9800")
rt = call("auth.login", {"username": "ram", "password": "secret2"})["token"]
me = call("auth.me", {}, rt)
ok("storekeeper sees P1 only, menu = Overview/Inventory/Procurement", [p["code"] for p in me["workspace"]["projects"]] == ["P1"] and me["workspace"]["menus"] == ["Overview", "Inventory", "Procurement"], me["workspace"]["menus"])
e = err("ws.enter", {"workspace": "project", "project_id": P["P2"]}, rt)
ok("storekeeper refused P2", bool(e), e)
# purchase officer at a site: a company job, these projects
call("admin.user_save", {"row": {"username": "hari", "name": "Hari", "role": "procurement_officer", "active": 1, "password": "secret3", "access": "projects", "project_ids": [P["P1"], P["P3"]]}}, tok)
ht = call("auth.login", {"username": "hari", "password": "secret3"})["token"]
e = err("ws.enter", {"workspace": "company"}, ht)
ok("site purchase officer refused the Company Workspace", bool(e), e)
call("ws.enter", {"workspace": "project", "project_id": P["P3"]}, ht)
e = err("rep.tb", {}, ht)
ok("site purchase officer refused the trial balance", bool(e), e)
# head office purchase officer keeps company access
call("admin.user_save", {"row": {"username": "sita", "name": "Sita", "role": "procurement_officer", "active": 1, "password": "secret4", "access": "all"}}, tok)
st = call("auth.login", {"username": "sita", "password": "secret4"})["token"]
call("ws.enter", {"workspace": "company"}, st)
ok("head office purchase officer enters the Company Workspace", True)
# team
t = call("ws.team", {"project_id": P["P1"]}, tok)
ok("P1 team = Hari, Ram; Sita at head office", sorted(x["username"] for x in t["members"]) == ["hari", "ram"] and "sita" in [x["username"] for x in t["head_office"]])
r = call("ws.team_copy", {"project_id": P["P2"], "from_project": P["P1"]}, tok)
t2 = call("ws.team", {"project_id": P["P2"]}, tok)
ok("copy team P1 -> P2", r["added"] == 2 and sorted(x["username"] for x in t2["members"]) == ["hari", "ram"])
call("ws.team_remove", {"project_id": P["P2"], "user_id": ram["id"]}, tok)
e = err("ws.team_remove", {"project_id": P["P1"], "user_id": ram["id"]}, tok)
ok("removing someone's last project refused", bool(e), e)
e = err("ws.team_add", {"project_id": P["P2"], "user_ids": [r2] if (r2 := None) else [{x["username"]: x for x in call("admin.users", {}, tok)}["sita"]["id"]]}, tok)
ok("head office person not added to a team", bool(e), e)
jobs = {x["key"]: x for x in call("ws.roles", {}, tok)["roles"]}
ok("jobs renamed and carry menus", jobs["project_accountant"]["name"] == "Site accountant" and jobs["storekeeper"]["menus"] == ["Overview", "Inventory", "Procurement"])
call("ws.role_save", {"row": {"key": "storekeeper", "name": "Storekeeper", "projects": "assigned", "company": 0, "perms": {"inventory": ["view", "edit", "approve"], "procurement": ["view"]}, "menus": ["Overview", "Inventory"]}}, tok)
ok("job editor saves menus", call("auth.me", {}, rt)["workspace"]["menus"] == ["Overview", "Inventory"])
print("\n%d of %d passed" % (sum(R), len(R)))
