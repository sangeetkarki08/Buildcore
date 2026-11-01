"""
BuildCore 2.8 - company and year, store, KPIs, contracts, machine history.

  Companies         several companies on one BuildCore, each with its own data file (like Tally); choose one at
                    sign-in, switch with Alt+F3. A request carries its company (X-Company header or bco_co
                    cookie); the engine switches the data file under its lock, so two people can work in two
                    companies at the same time.
  Sign-in           clear reasons (no such user, switched off, wrong password with tries left), sign in with the
                    full name too, administrator can unlock a user.
  Fiscal years      year list, year-end close (balances and stock frozen, periods locked, next year created),
                    opening balances of a year, tax summary by year, trial balance and balance sheet split into
                    "brought forward" and "this year".
  Store             every material has a kind (consumable, tool, spare part, other); one store page per kind;
                    tools are tracked with the people who hold them.
  KPIs              stock accuracy, stock-outs, turnover, dead stock, issue and GRN times, requisition fill,
                    on-time delivery, rejection, order accuracy, wastage, budget variance, loss, returns;
                    finance and accounts figures.
  Contracts         contract register (subcontract, supply, hire, client, consultant) with letters, reports,
                    deliveries and milestones due, bonds and insurance expiry, late deliveries.
  Machines          repair record (parts, labour, workshop, cause) on every work order, repairs entered after
                    the fact, and the full maintenance and repair history of each machine.
"""
import json
import os
import re
import sqlite3
import sys
import threading
import time
from datetime import date, datetime, timedelta

import core
from core import ApiError, audit, get, ins, need, now, q, q1, r2, r4, setting, today, upd, val
import api_inventory as inv
from api_inventory import api as _register

POSTED = "v.status IN ('posted','reversed')"
_READY = set()


def api(name, module=None, action=None, public=False):
    def wrap(f):
        def run(c, u, a):
            ensure(c)
            return f(c, u, a)
        run.__name__, run.__doc__ = f.__name__, f.__doc__
        if public:
            _register(name, module, action, public=True)(run)
        else:
            _register(name, module, action)(run)
        return f
    return wrap


def _cols(c, t):
    return {r[1] for r in c.execute("PRAGMA table_info(%s)" % t).fetchall()}


def _has(c, t):
    return bool(c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (t,)).fetchone())


def _f(v, d=0.0):
    try:
        if v in (None, ""):
            return d
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return d


SCHEMA = """
CREATE TABLE IF NOT EXISTS fy_close(id INTEGER PRIMARY KEY, fy TEXT, start_date TEXT, end_date TEXT, status TEXT,
  profit REAL, closed_at TEXT, closed_by INTEGER, reopened_at TEXT, remarks TEXT);
CREATE TABLE IF NOT EXISTS fy_balances(id INTEGER PRIMARY KEY, fy TEXT, account_id INTEGER, code TEXT, name TEXT, type TEXT,
  opening REAL, debit REAL, credit REAL, closing REAL);
CREATE INDEX IF NOT EXISTS ix_fy_bal ON fy_balances(fy);
CREATE TABLE IF NOT EXISTS fy_stock(id INTEGER PRIMARY KEY, fy TEXT, project_id INTEGER, store_id INTEGER, material_id INTEGER,
  qty REAL, value REAL);
CREATE TABLE IF NOT EXISTS contracts(id INTEGER PRIMARY KEY, project_id INTEGER, party_id INTEGER, kind TEXT, ref_no TEXT,
  title TEXT, value REAL DEFAULT 0, start_date TEXT, end_date TEXT, retention_pct REAL DEFAULT 0, advance REAL DEFAULT 0,
  bond_no TEXT, bond_expiry TEXT, insurance_expiry TEXT, contact TEXT, status TEXT DEFAULT 'active', remarks TEXT,
  created_by INTEGER, ts TEXT);
CREATE TABLE IF NOT EXISTS contract_items(id INTEGER PRIMARY KEY, contract_id INTEGER, kind TEXT, title TEXT, due_date TEXT,
  repeat TEXT DEFAULT 'none', responsible TEXT, direction TEXT DEFAULT 'we_send', status TEXT DEFAULT 'pending',
  done_date TEXT, ref_no TEXT, qty REAL, unit TEXT, remarks TEXT);
CREATE INDEX IF NOT EXISTS ix_citem ON contract_items(contract_id);
"""
WO_COLS = {"parts_cost": "REAL", "labour_cost": "REAL", "external_cost": "REAL", "workshop": "TEXT",
           "parts_replaced": "TEXT", "failure_code": "TEXT", "cause_detail": "TEXT", "repair_remarks": "TEXT"}


def init_corp(c):
    c.executescript(SCHEMA)
    if "kind" not in _cols(c, "materials"):
        c.execute("ALTER TABLE materials ADD COLUMN kind TEXT")
    have = _cols(c, "work_orders")
    for k, t in WO_COLS.items():
        if k not in have:
            c.execute("ALTER TABLE work_orders ADD COLUMN %s %s" % (k, t))
    _patch_server()


def ensure(c):
    try:
        key = c.execute("PRAGMA database_list").fetchone()[2] or id(c)
    except Exception:
        key = id(c)
    if key not in _READY:
        if not _has(c, "contract_items") or "kind" not in _cols(c, "materials") or "parts_cost" not in _cols(c, "work_orders"):
            init_corp(c)
        _READY.add(key)


# ═════════════════════════ companies ═════════════════════════
def _root():
    return core._ROOT


def _reg_path():
    return os.path.join(_root(), "companies.json")


def _db_name(path):
    try:
        k = sqlite3.connect("file:%s?mode=ro" % path, uri=True, timeout=5)
        try:
            r = k.execute("SELECT value FROM settings WHERE key='company_name'").fetchone()
            return r[0] if r else None
        finally:
            k.close()
    except Exception:
        return None


def registry():
    try:
        with open(_reg_path(), "r", encoding="utf-8") as fh:
            reg = json.load(fh)
        if not reg.get("companies"):
            raise ValueError("empty")
    except Exception:
        reg = {"companies": [{"code": "main", "name": None, "dir": ""}], "default": "main"}
    if not any(x["code"] == "main" for x in reg["companies"]):
        reg["companies"].insert(0, {"code": "main", "name": None, "dir": ""})
    return reg


def save_registry(reg):
    tmp = _reg_path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(reg, fh, indent=2, ensure_ascii=False)
    if os.path.exists(_reg_path()):
        os.remove(_reg_path())
    os.rename(tmp, _reg_path())


def _paths(co):
    base = _root() if not co.get("dir") else os.path.join(_root(), co["dir"])
    data = os.path.join(base, "data")
    return data, os.path.join(base, "backups"), os.path.join(data, "buildcore.db")


def _find(code):
    reg = registry()
    for x in reg["companies"]:
        if x["code"] == code:
            return x
    for x in reg["companies"]:
        if x["code"] == reg.get("default"):
            return x
    return reg["companies"][0]


CUR = {"code": None}
_INIT_DONE = set()
_SERVER = {"mod": None}


def _server_mod():
    if _SERVER["mod"] is None:
        for name in ("__main__", "server"):
            m = sys.modules.get(name)
            if m is not None and hasattr(m, "Handler") and hasattr(m, "call"):
                _SERVER["mod"] = m
                break
    return _SERVER["mod"]


def switch(code):
    """Point the engine at one company's data file. Call with core.LOCK held."""
    co = _find(code or "")
    data, bk, db = _paths(co)
    if CUR["code"] == co["code"] and core.DB_PATH == db:
        return co
    if CUR["code"] is None:
        _INIT_DONE.add(os.path.normcase(core.DB_PATH))
    core.DATA_DIR, core.BACKUP_DIR, core.DB_PATH = data, bk, db
    srv = _server_mod()
    for m in (srv, sys.modules.get("server"), sys.modules.get("__main__")):
        if m is not None:
            for k, v in (("DB_PATH", db), ("BACKUP_DIR", bk)):
                if hasattr(m, k):
                    setattr(m, k, v)
    ap = sys.modules.get("api_project")
    if ap is not None and hasattr(ap, "FILES_DIR"):
        ap.FILES_DIR = os.path.join(data, "files")
    CUR["code"] = co["code"]
    key = os.path.normcase(db)
    if key not in _INIT_DONE:
        os.makedirs(data, exist_ok=True)
        _INIT_DONE.add(key)
        core.init_db()
    return co


def _req_company(handler):
    code = handler.headers.get("X-Company")
    if not code:
        ck = handler.headers.get("Cookie") or ""
        m = re.search(r"(?:^|;\s*)bco_co=([A-Za-z0-9_-]+)", ck)
        if m:
            code = m.group(1)
    if not code:
        try:
            from urllib.parse import urlparse, parse_qs
            code = parse_qs(urlparse(handler.path).query).get("co", [None])[0]
        except Exception:
            code = None
    return code


LOCK_WAIT = 25          # seconds a request waits for the engine before it is told "busy"
_HELD = {"since": None, "what": None, "dumped": False}


def _log(msg):
    try:
        d = _paths({"code": "main", "dir": ""})[0]
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "error.log"), "a", encoding="utf-8") as fh:
            fh.write("%s %s\n" % (now(), msg))
    except Exception:
        pass


def _dump_threads(reason):
    """Write where every engine thread is to error.log, so a stuck engine can be diagnosed."""
    import traceback
    lines = ["=" * 60, "%s ENGINE REPORT: %s" % (now(), reason)]
    for tid, frame in sys._current_frames().items():
        lines.append("--- thread %s" % tid)
        lines.extend(x.rstrip() for x in traceback.format_stack(frame))
    _log("\n".join(lines))


def _watchdog():
    while True:
        time.sleep(5)
        try:
            since = _HELD["since"]
            if since and not _HELD["dumped"] and time.time() - since > 45:
                _HELD["dumped"] = True
                _dump_threads("a request has held the engine for %d s: %s" % (time.time() - since, _HELD["what"]))
        except Exception:
            pass


def _mark_broken(code, err):
    if not code or code == "main":
        return
    try:
        reg = registry()
        for x in reg["companies"]:
            if x["code"] == code:
                x["broken"] = str(err)[:300]
        save_registry(reg)
    except Exception:
        pass
    _log("company %s could not be opened and was set aside: %s" % (code, err))


def _patch_server():
    srv = _server_mod()
    if srv is None or getattr(srv.Handler, "_bco_company", False):
        return
    from urllib.parse import urlparse as _up
    for meth in ("do_GET", "do_POST"):
        orig = getattr(srv.Handler, meth, None)
        if orig is None:
            continue

        def make(orig, meth):
            def handler(self, *a, **k):
                path = _up(self.path).path
                if path == "/api/ping" or not (path.startswith("/api") or path.startswith("/files/")):
                    return orig(self, *a, **k)          # screens, scripts, styles: no data file needed
                code = _req_company(self)
                if not core.LOCK.acquire(timeout=LOCK_WAIT):
                    if not _HELD["dumped"]:
                        _HELD["dumped"] = True
                        _dump_threads("a request waited %d s for the engine" % LOCK_WAIT)
                    try:
                        self._json(200 if meth == "do_POST" else 503, {"ok": False, "error": "BuildCore is busy with another task. Wait a minute and try again; "
                                                                        "if it stays like this, close BuildCore and open it again."})
                    except Exception:
                        pass
                    return None
                _HELD.update(since=time.time(), what="%s %s" % (meth[3:], path), dumped=False)
                try:
                    co = _find(code or "")
                    if co.get("broken"):
                        code = "main"
                    try:
                        switch(code)
                    except Exception as e:  # a broken company must never stop the others
                        _mark_broken(code, e)
                        switch("main")
                    return orig(self, *a, **k)
                finally:
                    _HELD["since"] = None
                    core.LOCK.release()
            return handler
        setattr(srv.Handler, meth, make(orig, meth))
    srv.Handler._bco_company = True
    threading.Thread(target=_backup_loop, daemon=True).start()
    threading.Thread(target=_watchdog, daemon=True).start()


def _backup_loop():
    """Daily copy of every extra company (the default company keeps its own daily backup)."""
    time.sleep(120)
    while True:
        try:
            for co in registry()["companies"]:
                if co["code"] == "main":
                    continue
                if co.get("broken") or not core.LOCK.acquire(timeout=5):
                    continue
                try:
                    switch(co["code"])
                    bk = core.BACKUP_DIR
                    os.makedirs(bk, exist_ok=True)
                    stamp = date.today().isoformat()
                    if not any(f.startswith("buildcore_auto_" + stamp) for f in os.listdir(bk)):
                        try:
                            core.backup_now("auto")
                        except Exception:
                            pass
                finally:
                    core.LOCK.release()
        except Exception:
            pass
        time.sleep(6 * 3600)


def _company_rows(c=None):
    reg = registry()
    out = []
    cur = CUR["code"] or "main"
    here = None
    if c is not None:
        try:
            here = setting(c, "company_name")
        except Exception:
            here = None
    changed = False
    for co in reg["companies"]:
        _d, _b, db = _paths(co)
        name = co.get("name")
        if co["code"] == cur and here:
            if name != here:
                co["name"] = here
                changed = True
            name = here
        out.append({"code": co["code"], "name": name or ("Main company" if co["code"] == "main" else co["code"]), "default": co["code"] == reg.get("default"),
                    "current": co["code"] == cur, "exists": os.path.exists(db), "created": co.get("created"), "broken": co.get("broken")})
    if changed and os.path.exists(_reg_path()):
        try:
            save_registry(reg)
        except Exception:
            pass
    return out


@api("co.list", public=True)
def co_list(c, u, a):
    """The companies on this BuildCore (names only - shown on the sign-in screen)."""
    return {"companies": _company_rows(c), "current": CUR["code"] or "main"}


@api("co.info")
def co_info(c, u, a):
    s = lambda k: setting(c, k)
    return {"code": CUR["code"] or "main", "name": s("company_name"), "pan": s("company_pan"), "address": s("company_address"),
            "companies": len(registry()["companies"])}


def _slug(name):
    s = re.sub(r"[^a-z0-9]+", "", (name or "").lower())[:16]
    return s or "co"


COPY_SETS = {
    "accounts": ["account_groups", "accounts", "tds_rates", "nfrs18_map"],
    "materials": ["materials", "inv_policy"],
    "parties": ["parties"],
    "equipment": ["equipment", "eq_tools", "check_lists", "maint_plans"],
    "staff": ["staff", "trades"],
    "settings": ["settings"],
}


def _copy_tables(c, dst_db, tables, zero=None):
    """Copy rows from the company you are in (its own open connection) into the new company's file.
    The main data file is never opened a second time."""
    k = sqlite3.connect(dst_db, timeout=30)
    try:
        for t in tables:
            if not _has(c, t):
                continue
            have_dst = k.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (t,)).fetchone()
            if not have_dst:
                continue
            sc = [r[1] for r in c.execute("PRAGMA table_info(%s)" % t).fetchall()]
            dc = {r[1] for r in k.execute("PRAGMA table_info(%s)" % t).fetchall()}
            cols = [x for x in sc if x in dc]
            if not cols:
                continue
            rows = c.execute("SELECT %s FROM %s" % (", ".join(cols), t)).fetchall()
            zc = set((zero or {}).get(t, ()))
            data = [tuple((0 if col in zc else r[i]) for i, col in enumerate(cols)) for r in rows]
            k.execute("DELETE FROM %s" % t)
            if data:
                k.executemany("INSERT INTO %s(%s) VALUES(%s)" % (t, ", ".join(cols), ", ".join("?" * len(cols))), data)
        k.commit()
    finally:
        k.close()


@api("co.create", "admin", "edit")
def co_create(c, u, a):
    """New company with its own data file. Masters can be copied from the company you are in."""
    need(a, "name")
    if u.get("role") != "admin":
        raise ApiError("Only an administrator can create a company.")
    name = a["name"].strip()
    reg = registry()
    code = _slug(a.get("code") or name)
    base = code
    n = 2
    while any(x["code"] == code for x in reg["companies"]):
        code = "%s%d" % (base, n)
        n += 1
    src_code = CUR["code"] or "main"
    entry = {"code": code, "name": name, "dir": "companies/" + code, "created": now()}
    reg["companies"].append(entry)
    save_registry(reg)
    copy = a.get("copy") or {}
    ok = False
    try:
        switch(code)
        k = core.connect()
        try:
            k.execute("INSERT INTO settings(key,value) VALUES('company_name',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (name,))
            for key in ("company_pan", "company_address"):
                if a.get(key[8:]) is not None:
                    k.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, a.get(key[8:])))
            k.commit()
        finally:
            k.close()
        new_db = core.DB_PATH
        sets = [s for s in ("accounts", "materials", "parties", "equipment", "staff") if copy.get(s)]
        tables = []
        for s in sets:
            tables += COPY_SETS[s]
        if tables:
            _copy_tables(c, new_db, tables, zero={"accounts": ("opening_balance",), "equipment": ("meter", "accumulated_dep")})
        if copy.get("users"):
            _copy_tables(c, new_db, ["users"])
        else:
            k = core.connect()
            try:
                me = q1(c, "SELECT * FROM users WHERE id=?", (u["id"],))
                k.execute("DELETE FROM users")
                k.execute("INSERT INTO users(username, name, pw_hash, salt, role, active) VALUES(?,?,?,?,?,1)",
                          (me["username"], me["name"], me["pw_hash"], me["salt"], "admin"))
                k.commit()
            finally:
                k.close()
        k = core.connect()
        try:
            k.execute("UPDATE settings SET value=? WHERE key='company_name'", (name,))
            for key in ("company_pan", "company_address"):
                if a.get(key[8:]) is not None:
                    k.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, a.get(key[8:])))
            if a.get("fy") and a.get("fy_start"):
                inv.FUNCS["period.generate"][0](k, u, {"fy": a["fy"], "start_date": a["fy_start"]})
            k.commit()
        finally:
            k.close()
        ok = True
    finally:
        switch(src_code)
        if not ok:
            try:
                reg = registry()
                reg["companies"] = [x for x in reg["companies"] if x["code"] != code]
                save_registry(reg)
            except Exception:
                pass
    audit(c, u, "company_create", "companies", None, {"code": code, "name": name, "copied": sorted(k2 for k2, v in copy.items() if v)})
    return {"code": code, "name": name}


@api("co.update", "admin", "edit")
def co_update(c, u, a):
    """Rename a company or make it the one offered first at sign-in."""
    if u.get("role") != "admin":
        raise ApiError("Only an administrator can change companies.")
    reg = registry()
    co = next((x for x in reg["companies"] if x["code"] == a.get("code")), None)
    if not co:
        raise ApiError("Unknown company.")
    if a.get("default"):
        reg["default"] = co["code"]
    if a.get("retry"):
        co.pop("broken", None)
        _INIT_DONE.discard(os.path.normcase(_paths(co)[2]))
    if a.get("name"):
        co["name"] = a["name"].strip()
        if co["code"] == (CUR["code"] or "main"):
            c.execute("UPDATE settings SET value=? WHERE key='company_name'", (co["name"],))
        else:
            _d, _b, db = _paths(co)
            k = sqlite3.connect(db, timeout=30)
            try:
                k.execute("UPDATE settings SET value=? WHERE key='company_name'", (co["name"],))
                k.commit()
            finally:
                k.close()
    save_registry(reg)
    return {"companies": _company_rows(c)}


# ═════════════════════════ sign-in ═════════════════════════
def _wrap_login():
    if "auth.login" not in inv.FUNCS or getattr(inv.FUNCS["auth.login"][0], "_bco27", False):
        return
    orig = inv.FUNCS["auth.login"]

    def login2(c, u, a):
        a = dict(a)
        name = (a.get("username") or "").strip().lower()
        if name and not q1(c, "SELECT id FROM users WHERE username=?", (name,)):
            byname = q(c, "SELECT username FROM users WHERE lower(trim(name))=? AND active=1", (name,))
            if len(byname) == 1:
                a["username"] = byname[0]["username"]
                name = byname[0]["username"]
        a["username"] = name
        try:
            return orig[0](c, u, a)
        except ApiError as e:
            msg = str(e)
            if not msg.startswith("Wrong username"):
                raise
            usr = q1(c, "SELECT * FROM users WHERE username=?", (name,))
            coname = (setting(c, "company_name") or "this company").rstrip(".")
            if not usr:
                raise ApiError("There is no user '%s' in %s. Check the company chosen above and the username "
                               "(an administrator sets usernames in Administration › Users)." % (name, coname))
            if not usr["active"]:
                raise ApiError("User '%s' is switched off. Ask the administrator to tick Active in Administration › Users." % name)
            try:
                lock_min = int(float(setting(c, "lock_minutes") or 10))
            except ValueError:
                lock_min = 10
            since = (datetime.now() - timedelta(minutes=lock_min)).isoformat(timespec="seconds")
            fails = 0
            for r in q(c, "SELECT ok FROM login_attempts WHERE username=? AND ts>=? ORDER BY id DESC LIMIT 5", (name, since)):
                if r["ok"]:
                    break
                fails += 1
            left = max(0, 5 - fails)
            raise ApiError("Wrong password for '%s'. %s Passwords are case-sensitive - check Caps Lock." %
                           (name, ("%d more tries before a %d-minute lock." % (left, lock_min)) if left else "Locked for %d minutes." % lock_min))
    login2._bco27 = True
    inv.FUNCS["auth.login"] = (login2, orig[1], orig[2], orig[3])


@api("adm.unlock", "admin", "edit")
def adm_unlock(c, u, a):
    """Clear the wrong-password lock of a user."""
    usr = get(c, "users", int(a["id"]), "User")
    c.execute("DELETE FROM login_attempts WHERE username=?", (usr["username"],))
    audit(c, u, "unlock", "users", usr["id"])
    return True


@api("adm.users2", "admin", "view")
def adm_users2(c, u, a):
    """Users with their last sign-in and whether they are locked out."""
    rows = q(c, "SELECT id, username, name, role, active, location, phone, email FROM users ORDER BY username")
    since = (datetime.now() - timedelta(minutes=int(_f(setting(c, "lock_minutes"), 10)))).isoformat(timespec="seconds")
    for r in rows:
        r["last_login"] = val(c, "SELECT MAX(ts) FROM audit WHERE action='login' AND user_id=?", (r["id"],)) or None
        rec = q(c, "SELECT ok FROM login_attempts WHERE username=? AND ts>=? ORDER BY id DESC LIMIT 5", (r["username"], since))
        r["locked"] = len(rec) == 5 and not any(x["ok"] for x in rec)
        r["failed"] = 0
        for x in rec:
            if x["ok"]:
                break
            r["failed"] += 1
    return rows


# ═════════════════════════ fiscal years ═════════════════════════
def _fy_rows(c):
    return q(c, "SELECT fy, MIN(start_date) start_date, MAX(end_date) end_date, COUNT(*) periods, "
                "SUM(status='open') open_n, SUM(status='soft_closed') soft_n, SUM(status='locked') locked_n "
                "FROM fiscal_periods GROUP BY fy ORDER BY MIN(start_date)")


def _fy_bounds(c, fy):
    r = q1(c, "SELECT MIN(start_date) s, MAX(end_date) e FROM fiscal_periods WHERE fy=?", (fy,))
    if not r or not r["s"]:
        raise ApiError("Fiscal year %s has no periods. Create it in Accounts › Periods." % fy)
    return r["s"], r["e"]


def _fy_of_date(c, d):
    p = q1(c, "SELECT fy FROM fiscal_periods WHERE start_date<=? AND end_date>=? LIMIT 1", (d, d))
    return p["fy"] if p else None


def _next_label(fy):
    m = re.match(r"^(\d{4})([-/])(\d{2,4})$", fy or "")
    if not m:
        return None
    y = int(m.group(1)) + 1
    tail = str(y + 1)[-len(m.group(3)):]
    return "%d%s%s" % (y, m.group(2), tail)


def _acc_bal(c, role_or_ids, upto, frm=None):
    ids = role_or_ids
    if isinstance(role_or_ids, str):
        ids = [r["id"] for r in q(c, "SELECT id FROM accounts WHERE role=?", (role_or_ids,))]
    if not ids:
        return 0.0
    ph = ",".join("?" * len(ids))
    ob = 0.0 if frm else (val(c, "SELECT SUM(opening_balance) FROM accounts WHERE id IN (%s)" % ph, ids) or 0)
    cond, p = "v.date<=?", [upto]
    if frm:
        cond, p = "v.date BETWEEN ? AND ?", [frm, upto]
    mv = val(c, "SELECT SUM(l.debit-l.credit) FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id WHERE l.account_id IN (%s) AND "
             % ph + POSTED + " AND " + cond, ids + p) or 0
    return r2(ob + mv)


def _pl_upto(c, upto, frm="0000-01-01"):
    pl = inv.FUNCS["rep.pl"][0]
    return pl(c, None, {"from": frm, "to": upto})["profit"]


def _pl_opening(c):
    """Opening balances typed on income / expense accounts (profit before the first entry)."""
    return sum((-(x["opening_balance"] or 0) if x["type"] == "income" else (x["opening_balance"] or 0))
               for x in q(c, "SELECT type, opening_balance FROM accounts WHERE type IN ('income','expense')"))


@api("fy.list", "accounts", "view")
def fy_list(c, u, a):
    """Fiscal years with their state, entries and profit; the year of today is marked."""
    t = today()
    out = []
    for r in _fy_rows(c):
        cl = q1(c, "SELECT * FROM fy_close WHERE fy=? ORDER BY id DESC LIMIT 1", (r["fy"],))
        r["vouchers"] = val(c, "SELECT COUNT(*) FROM vouchers v WHERE " + POSTED + " AND v.date BETWEEN ? AND ?", (r["start_date"], r["end_date"]))
        r["drafts"] = val(c, "SELECT COUNT(*) FROM vouchers WHERE status='draft' AND date BETWEEN ? AND ?", (r["start_date"], r["end_date"]))
        r["profit"] = r2(_pl_upto(c, r["end_date"], r["start_date"]))
        r["current"] = r["start_date"] <= t <= r["end_date"]
        r["closed"] = bool(cl and cl["status"] == "closed")
        r["closed_at"] = cl["closed_at"] if cl else None
        r["state"] = "closed" if r["closed"] else ("locked" if r["locked_n"] == r["periods"] else ("current" if r["current"] else ("future" if r["start_date"] > t else "open")))
        out.append(r)
    return {"years": out, "current": _fy_of_date(c, t)}


def _year_checks(c, s, e):
    out = []
    n = val(c, "SELECT COUNT(*) FROM vouchers WHERE status='draft' AND date BETWEEN ? AND ?", (s, e))
    if n:
        out.append("%d draft voucher(s)" % n)
    for t, label in (("grn", "goods receipts"), ("issues", "material issues"), ("returns", "returns"), ("transfers", "transfers"),
                     ("stock_counts", "stock counts"), ("invoices", "bills / invoices"), ("payments", "payments")):
        if _has(c, t) and "status" in _cols(c, t) and "date" in _cols(c, t):
            n = val(c, "SELECT COUNT(*) FROM %s WHERE status='draft' AND date BETWEEN ? AND ?" % t, (s, e))
            if n:
                out.append("%d draft %s" % (n, label))
    if _has(c, "dpr"):
        n = val(c, "SELECT COUNT(*) FROM dpr WHERE status<>'approved' AND date BETWEEN ? AND ?", (s, e))
        if n:
            out.append("%d DPR(s) not approved" % n)
    return out


@api("fy.close", "accounts", "approve")
def fy_close(c, u, a):
    """Year-end: freeze every account's opening / movement / closing and the stock, lock the year's periods
    and make sure the next year exists. The next year opens with these closing balances (balance-sheet
    accounts carry forward; income and expense start at zero with the profit brought forward)."""
    need(a, "fy")
    fy = a["fy"]
    s, e = _fy_bounds(c, fy)
    if q1(c, "SELECT id FROM fy_close WHERE fy=? AND status='closed'", (fy,)):
        raise ApiError("%s is already closed." % fy)
    warn = _year_checks(c, s, e)
    if e > today():
        warn.insert(0, "the year ends on %s (not over yet)" % e)
    if warn and not a.get("force"):
        return {"needs_confirm": True, "warnings": warn}
    tb = inv.FUNCS["rep.tb"][0](c, u, {"from": s, "to": e})
    c.execute("DELETE FROM fy_balances WHERE fy=?", (fy,))
    for r in tb:
        ins(c, "fy_balances", {"fy": fy, "account_id": r.get("id") or 0, "code": r.get("code"), "name": r.get("name"), "type": r.get("type"),
                               "opening": r["opening"], "debit": r["debit"], "credit": r["credit"], "closing": r["closing"]})
    c.execute("DELETE FROM fy_stock WHERE fy=?", (fy,))
    items = 0
    for r in q(c, "SELECT project_id, store_id, material_id, SUM(qty_in-qty_out) qty, SUM(value_in-value_out) value FROM stock_ledger "
                  "WHERE date<=? GROUP BY project_id, store_id, material_id HAVING ABS(SUM(qty_in-qty_out))>0.0001", (e,)):
        ins(c, "fy_stock", {"fy": fy, "project_id": r["project_id"], "store_id": r["store_id"], "material_id": r["material_id"],
                            "qty": r4(r["qty"]), "value": r2(r["value"] or 0)})
        items += 1
    profit = r2(_pl_upto(c, e, s))
    c.execute("UPDATE fiscal_periods SET status='locked' WHERE fy=?", (fy,))
    ins(c, "fy_close", {"fy": fy, "start_date": s, "end_date": e, "status": "closed", "profit": profit, "closed_at": now(),
                        "closed_by": u["id"], "remarks": a.get("remarks") or ("; ".join(warn) if warn else None)})
    nxt = None
    after = (date.fromisoformat(e) + timedelta(days=1)).isoformat()
    if not q1(c, "SELECT id FROM fiscal_periods WHERE start_date<=? AND end_date>=?", (after, after)):
        lbl = _next_label(fy)
        if lbl and not q1(c, "SELECT id FROM fiscal_periods WHERE fy=?", (lbl,)):
            inv.FUNCS["period.generate"][0](c, u, {"fy": lbl, "start_date": after})
            nxt = lbl
    else:
        nxt = _fy_of_date(c, after)
    audit(c, u, "fy_close", "fiscal_periods", None, {"fy": fy, "profit": profit, "accounts": len(tb), "stock_items": items})
    return {"fy": fy, "profit": profit, "accounts": len(tb), "stock_items": items, "next": nxt, "warnings": warn}


@api("fy.reopen", "admin", "edit")
def fy_reopen(c, u, a):
    """Administrator: open a closed year again (its periods become open; the frozen figures stay for comparison)."""
    need(a, "fy")
    cl = q1(c, "SELECT * FROM fy_close WHERE fy=? AND status='closed' ORDER BY id DESC LIMIT 1", (a["fy"],))
    if not cl:
        raise ApiError("%s is not closed." % a["fy"])
    upd(c, "fy_close", cl["id"], {"status": "reopened", "reopened_at": now()})
    c.execute("UPDATE fiscal_periods SET status='open' WHERE fy=?", (a["fy"],))
    audit(c, u, "fy_reopen", "fiscal_periods", None, {"fy": a["fy"], "reason": a.get("reason")})
    return True


@api("fy.opening", "accounts", "view")
def fy_opening(c, u, a):
    """Opening balances of a year = closing balances of the year before (balance-sheet accounts) plus the
    profit brought forward. If the previous year was closed, its frozen closing is shown beside it."""
    need(a, "fy")
    s, _e = _fy_bounds(c, a["fy"])
    day_before = (date.fromisoformat(s) - timedelta(days=1)).isoformat()
    prev = _fy_of_date(c, day_before)
    frozen = {}
    if prev and q1(c, "SELECT id FROM fy_close WHERE fy=? AND status='closed'", (prev,)):
        for r in q(c, "SELECT * FROM fy_balances WHERE fy=?", (prev,)):
            frozen[r["account_id"]] = r["closing"]
    rows = []
    for acc in q(c, "SELECT * FROM accounts WHERE type IN ('asset','liability','equity') ORDER BY code"):
        b = _acc_bal(c, [acc["id"]], day_before)
        f = frozen.get(acc["id"])
        if abs(b) < 0.005 and not f:
            continue
        rows.append({"id": acc["id"], "code": acc["code"], "name": acc["name"], "type": acc["type"],
                     "debit": r2(b) if b > 0 else 0, "credit": r2(-b) if b < 0 else 0, "balance": r2(b), "frozen": f,
                     "differs": f is not None and abs(f - b) > 0.01})
    bf = r2(_pl_upto(c, day_before) - _pl_opening(c))
    if abs(bf) > 0.004:
        f = frozen.get(0)
        rows.append({"id": None, "code": "", "name": "Profit & loss brought forward", "type": "equity",
                     "debit": r2(-bf) if bf < 0 else 0, "credit": r2(bf) if bf > 0 else 0, "balance": r2(-bf), "frozen": f,
                     "differs": False})
    td = r2(sum(r["debit"] for r in rows))
    tc = r2(sum(r["credit"] for r in rows))
    stock = q(c, "SELECT s.*, m.code, m.name, m.unit FROM fy_stock s JOIN materials m ON m.id=s.material_id WHERE s.fy=? ORDER BY m.code", (prev,)) if prev else []
    return {"fy": a["fy"], "start": s, "previous": prev, "previous_closed": bool(frozen), "rows": rows, "total_debit": td,
            "total_credit": tc, "difference": r2(td - tc), "stock": stock,
            "stock_value": r2(sum(x["value"] or 0 for x in stock))}


def _role_ids(c, *roles):
    return [r["id"] for r in q(c, "SELECT id FROM accounts WHERE role IN (%s)" % ",".join("?" * len(roles)), roles)]


def _sum(c, ids, s, e, sign=1):
    if not ids:
        return 0.0
    ph = ",".join("?" * len(ids))
    return r2(sign * (val(c, "SELECT SUM(l.debit-l.credit) FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id WHERE l.account_id IN (%s) AND "
                           % ph + POSTED + " AND v.date BETWEEN ? AND ?", ids + [s, e]) or 0))


@api("fy.tax", "accounts", "view")
def fy_tax(c, u, a):
    """Tax summary of one fiscal year, month by month: sales and output VAT, input VAT, net VAT, TDS we deducted
    and TDS deducted from us; with the year's book profit."""
    need(a, "fy")
    s, e = _fy_bounds(c, a["fy"])
    out_ids, in_ids = _role_ids(c, "vat_output"), _role_ids(c, "vat_input")
    tdsp, tdsr = _role_ids(c, "tds_payable"), _role_ids(c, "tds_receivable")
    inc_ids = [r["id"] for r in q(c, "SELECT id FROM accounts WHERE type='income' AND COALESCE(role,'')<>'equipment_recovery'")]
    months = []
    for p in q(c, "SELECT * FROM fiscal_periods WHERE fy=? ORDER BY start_date", (a["fy"],)):
        ps, pe = p["start_date"], p["end_date"]
        out_vat = -_sum(c, out_ids, ps, pe)
        in_vat = _sum(c, in_ids, ps, pe)
        months.append({"period": p["code"], "from": ps, "to": pe, "status": p["status"],
                       "sales": r2(-_sum(c, inc_ids, ps, pe)), "output_vat": r2(out_vat), "input_vat": r2(in_vat),
                       "net_vat": r2(out_vat - in_vat),
                       "tds_deducted": r2(-_sum(c, tdsp, ps, pe)), "tds_suffered": r2(_sum(c, tdsr, ps, pe))})
    tot = {k: r2(sum(m[k] for m in months)) for k in ("sales", "output_vat", "input_vat", "net_vat", "tds_deducted", "tds_suffered")}
    pl = inv.FUNCS["rep.pl"][0](c, u, {"from": s, "to": e})
    return {"fy": a["fy"], "from": s, "to": e, "months": months, "totals": tot, "profit": pl["profit"],
            "income": pl["total_income"], "expense": pl["total_expense"],
            "vat_balance_end": r2(-(_acc_bal(c, out_ids, e) + _acc_bal(c, in_ids, e))),
            "note": "Book figures from the VAT and TDS accounts. Confirm each month with the VAT return and TDS deposits; "
                    "taxable income needs the tax adjustments (tax depreciation, disallowed costs) from Fixed assets › Tax depreciation."}


def _wrap_reports():
    if "rep.tb" in inv.FUNCS and not getattr(inv.FUNCS["rep.tb"][0], "_bco28", False):
        tb = inv.FUNCS["rep.tb"]

        def tb2(c, u, a):
            rows = tb[0](c, u, a)
            frm = a.get("from") or "0000-01-01"
            if frm <= "0001-01-01":
                return rows
            out, bf = [], 0.0
            for r in rows:
                if r.get("type") in ("income", "expense") and abs(r.get("opening") or 0) > 0.004:
                    bf += r["opening"]
                    r = dict(r, opening=0.0, closing=r2((r["debit"] or 0) - (r["credit"] or 0)))
                    if abs(r["debit"]) < 0.005 and abs(r["credit"]) < 0.005:
                        continue
                out.append(r)
            if abs(bf) > 0.004:
                out.append({"id": None, "code": "", "name": "Profit & loss brought forward (earlier years)", "type": "equity",
                            "group_id": None, "opening": r2(bf), "debit": 0.0, "credit": 0.0, "closing": r2(bf), "pl_bf": True})
            return out
        tb2._bco28 = True
        inv.FUNCS["rep.tb"] = (tb2, tb[1], tb[2], tb[3])
    if "rep.bs" in inv.FUNCS and not getattr(inv.FUNCS["rep.bs"][0], "_bco28", False):
        bs = inv.FUNCS["rep.bs"]

        def bs2(c, u, a):
            r = bs[0](c, u, a)
            to = a.get("as_of") or today()
            fy = _fy_of_date(c, to)
            if not fy:
                return r
            s, _e = _fy_bounds(c, fy)
            year = r2(_pl_upto(c, to, s))
            before = r2(r["profit"] - year)
            if abs(before) > 0.004:
                r["equity"] = list(r["equity"]) + [{"id": None, "code": "", "name": "Profit & loss brought forward (to %s)" % s,
                                                     "group_id": None, "amount": before}]
            r["profit"] = year
            r["profit_bf"] = before
            r["fy"] = fy
            return r
        bs2._bco28 = True
        inv.FUNCS["rep.bs"] = (bs2, bs[1], bs[2], bs[3])


# ═════════════════════════ store by kind ═════════════════════════
KINDS = [("consumable", "Regular consumables"), ("tool", "Tools"), ("spare", "Spare parts"), ("other", "Other items")]
_SPARE = re.compile(r"spare|part|filter|bearing|tyre|tire|belt|seal|gasket|hose|battery|bushing|nozzle|pin\b|tooth|teeth", re.I)
_TOOL = re.compile(r"\btool|drill bit|jack hammer|hammer|spanner|wrench|grinder|vibrator|shovel|crowbar|wheel ?barrow|ladder|pump\b|"
                   r"saw\b|helmet|harness|level\b|theodolite|total station", re.I)


def kind_of(m):
    k = (m.get("kind") or "").strip().lower()
    if k in ("consumable", "tool", "spare", "other"):
        return k
    txt = "%s %s" % (m.get("category") or "", m.get("name") or "")
    if _SPARE.search(m.get("category") or "") or re.search(r"spare", txt, re.I):
        return "spare"
    if _TOOL.search(m.get("category") or "") or re.search(r"\btools?\b", m.get("category") or "", re.I):
        return "tool"
    return "consumable"


def _wrap_masters():
    m = inv.MASTERS.get("materials")
    if m and "kind" not in m[1]:
        m[1].append("kind")
    if "lookups" in inv.FUNCS and not getattr(inv.FUNCS["lookups"][0], "_bco28", False):
        lk = inv.FUNCS["lookups"]

        def lookups2(c, u, a):
            ensure(c)
            r = lk[0](c, u, a)
            try:
                kinds = {x["id"]: x for x in q(c, "SELECT id, kind, category, name FROM materials")}
                for mm in r.get("materials") or []:
                    x = kinds.get(mm["id"])
                    mm["kind"] = kind_of(x) if x else "consumable"
            except Exception:
                pass
            return r
        lookups2._bco28 = True
        inv.FUNCS["lookups"] = (lookups2, lk[1], lk[2], lk[3])


def _custody(c, pid=None, mat_ids=None):
    """Tools held by people: issued to a person minus returned by that person."""
    cond, p = "", []
    if pid:
        cond += " AND i.project_id=?"
        p.append(int(pid))
    out = {}
    for r in q(c, "SELECT l.material_id, TRIM(COALESCE(i.issued_to,'')) who, SUM(l.qty) qty, MAX(i.date) last FROM issue_lines l JOIN issues i "
                  "ON i.id=l.issue_id WHERE i.status='posted'" + cond + " GROUP BY l.material_id, lower(TRIM(COALESCE(i.issued_to,'')))", p):
        if mat_ids is not None and r["material_id"] not in mat_ids:
            continue
        key = (r["material_id"], (r["who"] or "").lower())
        out[key] = {"material_id": r["material_id"], "who": r["who"] or "(not named)", "issued": r["qty"] or 0, "returned": 0.0,
                    "damaged": 0.0, "last_issue": r["last"], "last_return": None}
    cond2 = cond.replace("i.", "t.")
    for r in q(c, "SELECT l.material_id, TRIM(COALESCE(t.returned_by,'')) who, SUM(l.qty) qty, "
                  "SUM(CASE WHEN COALESCE(l.condition,'usable')<>'usable' THEN l.qty ELSE 0 END) bad, MAX(t.date) last "
                  "FROM return_lines l JOIN returns t ON t.id=l.return_id WHERE t.status='posted'" + cond2 +
               " GROUP BY l.material_id, lower(TRIM(COALESCE(t.returned_by,'')))", p):
        key = (r["material_id"], (r["who"] or "").lower())
        if key not in out:
            if mat_ids is not None and r["material_id"] not in mat_ids:
                continue
            out[key] = {"material_id": r["material_id"], "who": r["who"] or "(not named)", "issued": 0.0, "returned": 0.0,
                        "damaged": 0.0, "last_issue": None, "last_return": None}
        out[key]["returned"] += r["qty"] or 0
        out[key]["damaged"] += r["bad"] or 0
        out[key]["last_return"] = r["last"]
    rows = []
    for x in out.values():
        x["holding"] = r4(x["issued"] - x["returned"])
        rows.append(x)
    return rows


@api("store.view", "inventory", "view")
def store_view(c, u, a):
    """Everything about the store on one page, split by kind of item."""
    pid = int(a["project_id"]) if a.get("project_id") else None
    t = today()
    d30 = (date.today() - timedelta(days=30)).isoformat()
    d90 = (date.today() - timedelta(days=90)).isoformat()
    sb_cond, sb_p = ("WHERE project_id=?", [pid]) if pid else ("", [])
    bal = {r["material_id"]: r for r in q(c, "SELECT material_id, SUM(qty) qty, SUM(value) value FROM stock_balances %s GROUP BY material_id" % sb_cond, sb_p)}
    lc, lp = (" AND project_id=?", [pid]) if pid else ("", [])
    last_in = {r["material_id"]: r["d"] for r in q(c, "SELECT material_id, MAX(date) d FROM stock_ledger WHERE qty_in>0" + lc + " GROUP BY material_id", lp)}
    last_out = {r["material_id"]: r["d"] for r in q(c, "SELECT material_id, MAX(date) d FROM stock_ledger WHERE qty_out>0 AND doc_type IN ('issue','MIN')" + lc + " GROUP BY material_id", lp)}
    if not last_out:
        last_out = {r["material_id"]: r["d"] for r in q(c, "SELECT material_id, MAX(date) d FROM stock_ledger WHERE qty_out>0" + lc + " GROUP BY material_id", lp)}
    used30 = {r["material_id"]: r["q"] for r in q(c, "SELECT material_id, SUM(qty_out) q FROM stock_ledger WHERE qty_out>0 AND date>=?" + lc + " GROUP BY material_id", [d30] + lp)}
    custody = {}
    for x in _custody(c, pid):
        if x["holding"] > 0.0001:
            custody.setdefault(x["material_id"], []).append(x)
    fits = {}
    if _has(c, "equipment_spares") and "material_id" in _cols(c, "equipment_spares"):
        for r in q(c, "SELECT s.material_id, e.code FROM equipment_spares s JOIN equipment e ON e.id=s.equipment_id"):
            fits.setdefault(r["material_id"], set()).add(r["code"])
    ic, ip = (" AND i.project_id=?", [pid]) if pid else ("", [])
    for r in q(c, "SELECT DISTINCT l.material_id, e.code FROM issue_lines l JOIN issues i ON i.id=l.issue_id JOIN equipment e ON e.id=l.equipment_id "
                  "WHERE i.status='posted' AND i.date>=?" + ic, [d90] + ip):
        fits.setdefault(r["material_id"], set()).add(r["code"])
    groups = {k: [] for k, _l in KINDS}
    for m in q(c, "SELECT * FROM materials ORDER BY code"):
        k = kind_of(m)
        b = bal.get(m["id"]) or {}
        qty, value = r4(b.get("qty") or 0), r2(b.get("value") or 0)
        if not m["active"] and abs(qty) < 0.0001:
            continue
        u30 = used30.get(m["id"]) or 0
        lo = last_out.get(m["id"])
        row = {"id": m["id"], "code": m["code"], "name": m["name"], "category": m["category"], "unit": m["unit"], "kind": k,
               "kind_set": bool(m.get("kind")), "qty": qty, "value": value, "rate": r2(value / qty) if qty else (m["standard_rate"] or 0),
               "reorder_level": m["reorder_level"] or 0, "min_level": m["min_level"] or 0,
               "below": (m["reorder_level"] or 0) > 0 and qty <= (m["reorder_level"] or 0),
               "last_in": last_in.get(m["id"]), "last_out": lo, "used_30": r4(u30),
               "cover_days": r2(qty / (u30 / 30.0)) if u30 > 0 else None,
               "idle": qty > 0.0001 and (not lo or lo < d90)}
        if k == "tool":
            held = custody.get(m["id"], [])
            row["out_with_people"] = r4(sum(x["holding"] for x in held))
            row["holders"] = ", ".join("%s (%s)" % (x["who"], ("%g" % x["holding"])) for x in sorted(held, key=lambda z: -z["holding"])[:6])
            row["total_owned"] = r4(qty + row["out_with_people"])
        if k == "spare":
            row["fits"] = ", ".join(sorted(fits.get(m["id"], set()))[:8])
        groups[k].append(row)
    summary = []
    for k, label in KINDS:
        rows = groups[k]
        summary.append({"kind": k, "label": label, "items": len(rows), "in_stock": sum(1 for r in rows if r["qty"] > 0.0001),
                        "value": r2(sum(r["value"] for r in rows)), "below": sum(1 for r in rows if r["below"]),
                        "idle_value": r2(sum(r["value"] for r in rows if r["idle"])),
                        "out_with_people": r4(sum(r.get("out_with_people") or 0 for r in rows))})
    return {"kinds": [{"kind": k, "label": l} for k, l in KINDS], "groups": groups, "summary": summary, "as_of": t}


@api("store.custody", "inventory", "view")
def store_custody(c, u, a):
    """Tools in the hands of people (issued less returned), oldest first."""
    pid = a.get("project_id")
    mats = {m["id"]: m for m in q(c, "SELECT * FROM materials")}
    tool_ids = {i for i, m in mats.items() if kind_of(m) == "tool"}
    rows = [x for x in _custody(c, pid, tool_ids) if x["holding"] > 0.0001 or x["damaged"] > 0]
    for x in rows:
        m = mats.get(x["material_id"]) or {}
        x["code"], x["name"], x["unit"] = m.get("code"), m.get("name"), m.get("unit")
        x["days_out"] = (date.today() - date.fromisoformat(x["last_issue"])).days if x.get("last_issue") else None
    rows.sort(key=lambda z: (-(z["days_out"] or 0), z["who"]))
    return rows


@api("store.set_kind", "masters", "edit")
def store_set_kind(c, u, a):
    """Set the kind of several materials at once."""
    k = a.get("kind")
    if k not in ("consumable", "tool", "spare", "other"):
        raise ApiError("Kind must be consumable, tool, spare or other.")
    ids = [int(x) for x in (a.get("ids") or [])]
    for i in ids:
        c.execute("UPDATE materials SET kind=? WHERE id=?", (k, i))
    audit(c, u, "set_kind", "materials", None, {"kind": k, "ids": ids})
    return {"updated": len(ids)}


# ═════════════════════════ KPIs ═════════════════════════
def _ts(x):
    try:
        return datetime.fromisoformat(str(x).replace("Z", "")[:19])
    except Exception:
        return None


def _status(v, target, higher=True, warn_gap=None):
    if v is None or target is None:
        return "info"
    gap = warn_gap if warn_gap is not None else abs(target) * 0.1 + 0.0001
    if higher:
        return "good" if v >= target else ("warn" if v >= target - gap else "bad")
    return "good" if v <= target else ("warn" if v <= target + gap else "bad")


def _stock_at(c, store_id, material_id, d):
    return val(c, "SELECT SUM(qty_in-qty_out) FROM stock_ledger WHERE store_id=? AND material_id=? AND date<=?", (store_id, material_id, d)) or 0


def _stock_value_at(c, d, pid):
    cond, p = ("AND project_id=?", [pid]) if pid else ("", [])
    return val(c, "SELECT SUM(value_in-value_out) FROM stock_ledger WHERE date<=? %s" % cond, [d] + p) or 0


@api("kpi.store", "inventory", "view")
def kpi_store(c, u, a):
    """Store, issue / receipt, procurement and wastage KPIs for a period."""
    pid = int(a["project_id"]) if a.get("project_id") else None
    to = a.get("to") or today()
    frm = a.get("from") or (date.fromisoformat(to) - timedelta(days=90)).isoformat()
    days = max(1, (date.fromisoformat(to) - date.fromisoformat(frm)).days + 1)
    pc = lambda alias: ((" AND %s.project_id=?" % alias), [pid]) if pid else ("", [])
    k = []

    def add(group, key, label, value, unit, target=None, higher=True, note="", detail=None, fmt=None):
        k.append({"group": group, "key": key, "label": label, "value": value, "unit": unit, "target": target,
                  "status": _status(value, target, higher) if target is not None else "info", "note": note,
                  "detail": detail or [], "higher_better": higher, "fmt": fmt})

    # ── inventory accuracy and control
    cc, cp = pc("s")
    cl = q(c, "SELECT l.*, s.date, s.no, m.code, m.name FROM count_lines l JOIN stock_counts s ON s.id=l.count_id JOIN materials m ON m.id=l.material_id "
              "WHERE s.status='posted' AND s.date BETWEEN ? AND ?" + cc, [frm, to] + cp)
    if cl:
        ok = sum(1 for x in cl if abs((x["counted_qty"] or 0) - (x["system_qty"] or 0)) <= max(0.005 * abs(x["system_qty"] or 0), 0.0001))
        acc = r2(100.0 * ok / len(cl))
        det = [{"Count": x["no"], "Date": x["date"], "Item": x["code"] + " " + x["name"], "System": x["system_qty"], "Counted": x["counted_qty"],
                "Difference": r4((x["counted_qty"] or 0) - (x["system_qty"] or 0)), "Reason": x["reason"] or ""}
               for x in cl if abs((x["counted_qty"] or 0) - (x["system_qty"] or 0)) > max(0.005 * abs(x["system_qty"] or 0), 0.0001)]
        add("Inventory accuracy and control", "accuracy", "Stock accuracy", acc, "%", 98, True,
            "%d of %d counted lines match the books within 0.5%%." % (ok, len(cl)), det)
    else:
        add("Inventory accuracy and control", "accuracy", "Stock accuracy", None, "%", 98, True, "No posted stock count in this period. Count the A items monthly (Inventory › Stock count).")
    # stock-outs: requisition lines that could not be met from stock that day, and DPR hours lost to material
    mc, mp = pc("r")
    outs = []
    for x in q(c, "SELECT l.*, r.date, r.no, r.store_id, m.code, m.name FROM mrq_lines l JOIN mrq r ON r.id=l.mrq_id JOIN materials m ON m.id=l.material_id "
                  "WHERE r.status<>'draft' AND r.date BETWEEN ? AND ?" + mc, [frm, to] + mp):
        have = _stock_at(c, x["store_id"], x["material_id"], x["date"]) if x["store_id"] else None
        need_q = x["approved_qty"] if x["approved_qty"] is not None else x["qty"]
        if have is not None and (need_q or 0) > have + 0.0001:
            outs.append({"Requisition": x["no"], "Date": x["date"], "Item": x["code"] + " " + x["name"], "Asked": need_q, "In stock": r4(have)})
    dc, dp = pc("d")
    lost = q1(c, "SELECT COUNT(*) n, SUM(y.hours) h FROM dpr_delays y JOIN dpr d ON d.id=y.dpr_id WHERE lower(COALESCE(y.category,'')) LIKE 'material%' "
                 "AND d.date BETWEEN ? AND ?" + dc, [frm, to] + dp) if _has(c, "dpr_delays") else {"n": 0, "h": 0}
    add("Inventory accuracy and control", "stockouts", "Stock-out incidents", len(outs) + (lost["n"] or 0), "times", 0, False,
        "%d requisition lines asked for more than the store held; DPRs record %s hours of work lost waiting for material." % (len(outs), fmt_n(lost["h"] or 0)), outs)
    # turnover and days on hand
    sc, sp = pc("l")
    issued_val = val(c, "SELECT SUM(l.value_out) FROM stock_ledger l WHERE l.date BETWEEN ? AND ? AND l.qty_out>0 AND l.doc_type NOT IN ('transfer','MTN','count','PSV')" + sc, [frm, to] + sp) or 0
    avg_stock = (_stock_value_at(c, frm, pid) + _stock_value_at(c, to, pid)) / 2.0
    turns = r2(issued_val / avg_stock * (365.0 / days)) if avg_stock > 0 else None
    doh = r2(avg_stock / (issued_val / days)) if issued_val > 0 else None
    add("Inventory accuracy and control", "turnover", "Inventory turnover (a year)", turns, "times", 6, True,
        "Material issued %s against an average stock of %s in the period." % (fmt_m(issued_val), fmt_m(avg_stock)))
    add("Inventory accuracy and control", "doh", "Days on hand", doh, "days", 60, False, "How long material sits in the store before it is used.")
    # dead and slow stock
    dead, slow = [], []
    bc, bp = ("WHERE b.project_id=?", [pid]) if pid else ("", [])
    for b in q(c, "SELECT b.material_id, SUM(b.qty) qty, SUM(b.value) value, m.code, m.name FROM stock_balances b JOIN materials m ON m.id=b.material_id %s "
                  "GROUP BY b.material_id HAVING SUM(b.qty)>0.0001" % bc, bp):
        lo = val(c, "SELECT MAX(date) FROM stock_ledger WHERE material_id=? AND qty_out>0" + (" AND project_id=?" if pid else ""), [b["material_id"]] + ([pid] if pid else []))
        age = (date.fromisoformat(to) - date.fromisoformat(lo)).days if lo else 9999
        row = {"Item": b["code"] + " " + b["name"], "Qty": r4(b["qty"]), "Value": r2(b["value"] or 0), "Last issue": lo or "never", "Days": age if age < 9999 else ""}
        if age >= 90:
            dead.append(row)
        elif age >= 60:
            slow.append(row)
    add("Inventory accuracy and control", "dead", "Dead stock (no issue 90+ days)", r2(sum(x["Value"] for x in dead)), "NPR", None, False,
        "%d items. Transfer to another site, return to the supplier or write down." % len(dead), dead, "money")
    add("Inventory accuracy and control", "slow", "Slow-moving stock (60-90 days)", r2(sum(x["Value"] for x in slow)), "NPR", None, False, "%d items." % len(slow), slow, "money")

    # ── issue and receipt efficiency
    ic, ip = pc("i")
    turn = []
    for x in q(c, "SELECT i.id, i.no, i.date, i.mrq_id, r.no mno, r.date mdate FROM issues i JOIN mrq r ON r.id=i.mrq_id WHERE i.status='posted' AND i.date BETWEEN ? AND ?" + ic, [frm, to] + ip):
        t_req = val(c, "SELECT MIN(ts) FROM audit WHERE entity='mrq' AND entity_id=? AND action IN ('save','submit','approve')", (x["mrq_id"],))
        t_iss = val(c, "SELECT MAX(ts) FROM audit WHERE entity='issues' AND entity_id=? AND action='post'", (x["id"],))
        a1, b1 = _ts(t_req) or _ts(x["mdate"] + "T09:00:00"), _ts(t_iss) or _ts(x["date"] + "T17:00:00")
        if a1 and b1:
            turn.append({"Issue": x["no"], "Requisition": x["mno"], "Hours": r2(max(0, (b1 - a1).total_seconds() / 3600.0))})
    if turn:
        hrs = sorted(t["Hours"] for t in turn)
        med = hrs[len(hrs) // 2]
        within = r2(100.0 * sum(1 for h in hrs if h <= 2) / len(hrs))
        add("Issue and receipt efficiency", "issue_time", "Issue turnaround (median)", r2(med), "hours", 2, False,
            "%s%% of %d issues were made within 2 hours of the requisition." % (fmt_n(within), len(hrs)), sorted(turn, key=lambda z: -z["Hours"])[:50])
    else:
        add("Issue and receipt efficiency", "issue_time", "Issue turnaround (median)", None, "hours", 2, False, "No issue against a requisition in this period.")
    gc, gp = pc("g")
    gtimes = []
    for g in q(c, "SELECT g.id, g.no, g.date FROM grn g WHERE g.status='posted' AND g.date BETWEEN ? AND ?" + gc, [frm, to] + gp):
        t_post = _ts(val(c, "SELECT MAX(ts) FROM audit WHERE entity='grn' AND entity_id=? AND action='post'", (g["id"],)))
        if t_post:
            d = (t_post.date() - date.fromisoformat(g["date"])).days
            gtimes.append({"GRN": g["no"], "Delivered": g["date"], "Entered": t_post.isoformat(timespec="minutes"), "Days": max(0, d)})
    if gtimes:
        same = r2(100.0 * sum(1 for x in gtimes if x["Days"] == 0) / len(gtimes))
        add("Issue and receipt efficiency", "grn_time", "GRN entered the same day", same, "%", 95, True,
            "Average %.1f days from delivery to entry." % (sum(x["Days"] for x in gtimes) / len(gtimes)), sorted(gtimes, key=lambda z: -z["Days"])[:50])
    else:
        add("Issue and receipt efficiency", "grn_time", "GRN entered the same day", None, "%", 95, True, "No goods receipt in this period.")
    fill = q(c, "SELECT l.qty, l.approved_qty, l.issued_qty, r.no, r.date, m.code, m.name FROM mrq_lines l JOIN mrq r ON r.id=l.mrq_id JOIN materials m ON m.id=l.material_id "
                "WHERE r.status NOT IN ('draft','rejected','cancelled') AND r.date BETWEEN ? AND ?" + mc, [frm, to] + mp)
    if fill:
        full = [x for x in fill if (x["issued_qty"] or 0) + 0.0001 >= (x["approved_qty"] if x["approved_qty"] is not None else x["qty"] or 0)]
        linked = val(c, "SELECT COUNT(*) FROM issue_lines WHERE mrq_line_id IS NOT NULL") or 0
        add("Issue and receipt efficiency", "fill", "Requisition fulfilment", r2(100.0 * len(full) / len(fill)), "%", 95, True,
            ("%d of %d requisition lines issued in full." % (len(full), len(fill))) + ("" if linked else
            " No issue is linked to a requisition yet - make issues from the requisition (Issue against requisition) so this can be measured."),
            [{"Requisition": x["no"], "Date": x["date"], "Item": x["code"] + " " + x["name"], "Asked": x["approved_qty"] if x["approved_qty"] is not None else x["qty"],
              "Issued": x["issued_qty"] or 0} for x in fill if x not in full][:80])
    else:
        add("Issue and receipt efficiency", "fill", "Requisition fulfilment", None, "%", 95, True, "No requisition in this period.")

    # ── procurement and supplier
    pcnd, pp = pc("p")
    late, ontime, total_po = [], 0, 0
    for p in q(c, "SELECT p.id, p.no, p.vendor_id, p.delivery_date FROM po p WHERE p.status NOT IN ('draft','cancelled') AND p.delivery_date IS NOT NULL "
                  "AND p.delivery_date BETWEEN ? AND ?" + pcnd, [frm, to] + pp):
        ordered = val(c, "SELECT SUM(qty) FROM po_lines WHERE po_id=?", (p["id"],)) or 0
        by_due = val(c, "SELECT SUM(gl.accepted_qty) FROM grn_lines gl JOIN grn g ON g.id=gl.grn_id WHERE g.po_id=? AND g.status='posted' AND g.date<=?",
                     (p["id"], p["delivery_date"])) or 0
        total_po += 1
        if ordered and by_due + 0.0001 >= ordered * 0.98:
            ontime += 1
        else:
            last = val(c, "SELECT MAX(g.date) FROM grn g WHERE g.po_id=? AND g.status='posted'", (p["id"],))
            late.append({"PO": p["no"], "Supplier": val(c, "SELECT name FROM parties WHERE id=?", (p["vendor_id"],)) or "", "Due": p["delivery_date"],
                         "Received by due": "%g of %g" % (by_due, ordered), "Last delivery": last or "none yet"})
    add("Procurement and supplier", "otd", "On-time delivery", r2(100.0 * ontime / total_po) if total_po else None, "%", 90, True,
        ("%d of %d orders due in the period arrived in full by the promised date." % (ontime, total_po)) if total_po else "No order due in this period.", late)
    rej = q1(c, "SELECT SUM(l.received_qty) rq, SUM(COALESCE(l.rejected_qty, l.received_qty-l.accepted_qty)) bad, SUM(COALESCE(l.rejected_qty, l.received_qty-l.accepted_qty)*l.rate) badv, "
                "SUM(l.received_qty*l.rate) rv FROM grn_lines l JOIN grn g ON g.id=l.grn_id WHERE g.status='posted' AND g.date BETWEEN ? AND ?" + gc, [frm, to] + gp)
    add("Procurement and supplier", "reject", "Quality rejection rate", r2(100.0 * (rej["badv"] or 0) / rej["rv"]) if rej["rv"] else None, "%", 2, False,
        "Value rejected on inspection %s of %s received." % (fmt_m(rej["badv"] or 0), fmt_m(rej["rv"] or 0)) if rej["rv"] else "No receipt in this period.")
    acc_l = q(c, "SELECT l.qty, l.received_qty, p.no, m.code, m.name FROM po_lines l JOIN po p ON p.id=l.po_id LEFT JOIN materials m ON m.id=l.material_id "
                 "WHERE p.status IN ('closed','received','completed') OR (l.received_qty>0 AND p.date BETWEEN ? AND ?)" + (" AND p.project_id=?" if pid else ""), [frm, to] + ([pid] if pid else []))
    acc_l = [x for x in acc_l if x["received_qty"]]
    if acc_l:
        good = [x for x in acc_l if abs((x["received_qty"] or 0) - (x["qty"] or 0)) <= 0.02 * (x["qty"] or 0) + 0.0001]
        add("Procurement and supplier", "order_acc", "Order accuracy (quantity as ordered)", r2(100.0 * len(good) / len(acc_l)), "%", 95, True,
            "%d of %d order lines delivered within 2%% of the ordered quantity." % (len(good), len(acc_l)),
            [{"PO": x["no"], "Item": (x["code"] or "") + " " + (x["name"] or ""), "Ordered": x["qty"], "Received": x["received_qty"]} for x in acc_l if x not in good][:80])
    else:
        add("Procurement and supplier", "order_acc", "Order accuracy (quantity as ordered)", None, "%", 95, True, "No delivered order line yet.")

    # ── wastage and cost
    wc, wp = pc("d")
    theo = {}
    for x in q(c, "SELECT w.boq_item_id, SUM(w.actual_qty) q FROM dpr_work w JOIN dpr d ON d.id=w.dpr_id WHERE d.status='approved' AND w.boq_item_id IS NOT NULL "
                  "AND d.date BETWEEN ? AND ?" + wc + " GROUP BY w.boq_item_id", [frm, to] + wp):
        for co in q(c, "SELECT material_id, qty_per_unit, wastage_pct FROM material_coefficients WHERE boq_item_id=?", (x["boq_item_id"],)):
            t = theo.setdefault(co["material_id"], {"q": 0.0, "allow": 0.0})
            t["q"] += (x["q"] or 0) * (co["qty_per_unit"] or 0)
            t["allow"] += (x["q"] or 0) * (co["qty_per_unit"] or 0) * (1 + (co["wastage_pct"] or 0) / 100.0)
    actual = {r["material_id"]: r for r in q(c, "SELECT l.material_id, SUM(l.qty) q, SUM(COALESCE(l.amount, 0)) v FROM issue_lines l JOIN issues i ON i.id=l.issue_id "
                                                "WHERE i.status='posted' AND l.boq_item_id IS NOT NULL AND i.date BETWEEN ? AND ?" + ic + " GROUP BY l.material_id", [frm, to] + ip)}
    rets = {r["material_id"]: r["q"] for r in q(c, "SELECT l.material_id, SUM(l.qty) q FROM return_lines l JOIN returns t ON t.id=l.return_id WHERE t.status='posted' "
                                              "AND l.boq_item_id IS NOT NULL AND t.date BETWEEN ? AND ?" + ic.replace("i.", "t."), [frm, to] + ip)}
    wrows, th_tot, ac_tot, plan_v, act_v = [], 0.0, 0.0, 0.0, 0.0
    for mid, t in theo.items():
        m = q1(c, "SELECT code, name, unit, standard_rate FROM materials WHERE id=?", (mid,)) or {}
        aq = (actual.get(mid) or {}).get("q") or 0
        aq -= rets.get(mid) or 0
        av = (actual.get(mid) or {}).get("v") or 0
        rate = (av / ((actual.get(mid) or {}).get("q") or 1)) if av else (m.get("standard_rate") or 0)
        if t["q"] <= 0:
            continue
        w = 100.0 * (aq - t["q"]) / t["q"]
        allow = 100.0 * (t["allow"] - t["q"]) / t["q"]
        wrows.append({"Item": (m.get("code") or "") + " " + (m.get("name") or ""), "Theoretical": r4(t["q"]), "Actual": r4(aq), "Unit": m.get("unit") or "",
                      "Wastage %": r2(w), "Allowed %": r2(allow), "Excess value": r2(max(0, aq - t["allow"]) * rate)})
        th_tot += t["q"] * rate
        ac_tot += aq * rate
        plan_v += t["allow"] * rate
        act_v += aq * rate
    wrows.sort(key=lambda z: -abs(z["Wastage %"]))
    add("Wastage and cost", "wastage", "Wastage (actual vs BOQ norm)", r2(100.0 * (ac_tot - th_tot) / th_tot) if th_tot else None, "%", 5, False,
        "Material issued to BOQ work against the norm for the work done in approved DPRs (by value)." if th_tot else
        "Needs material norms on BOQ items (Masters › BOQ items) and approved DPR quantities.", wrows)
    if th_tot and (ac_tot - th_tot) / th_tot < -0.10:
        k[-1]["status"] = "warn"
        k[-1]["note"] += " Much less was issued than the norm needs: check that issues name the BOQ item, or that the norms are right."
    add("Wastage and cost", "budget", "Material cost variance to budget", r2(100.0 * (act_v - plan_v) / plan_v) if plan_v else None, "%", 0, False,
        "Actual %s against planned %s (norm plus allowed wastage)." % (fmt_m(act_v), fmt_m(plan_v)) if plan_v else "No planned quantity in this period.")
    loss_rows = []
    for x in cl:
        d = (x["counted_qty"] or 0) - (x["system_qty"] or 0)
        if d < -0.0001:
            loss_rows.append({"Source": "Count " + x["no"], "Date": x["date"], "Item": x["code"] + " " + x["name"], "Qty": r4(-d), "Value": r2(-d * (x["rate"] or 0)), "Reason": x["reason"] or "shortage"})
    rc, rp = pc("t")
    for x in q(c, "SELECT l.qty, l.amount, l.rate, l.condition, t.no, t.date, m.code, m.name FROM return_lines l JOIN returns t ON t.id=l.return_id JOIN materials m ON m.id=l.material_id "
                  "WHERE t.status='posted' AND COALESCE(l.condition,'usable')<>'usable' AND t.date BETWEEN ? AND ?" + rc, [frm, to] + rp):
        loss_rows.append({"Source": "Return " + x["no"], "Date": x["date"], "Item": x["code"] + " " + x["name"], "Qty": x["qty"], "Value": r2(x["amount"] or (x["qty"] or 0) * (x["rate"] or 0)), "Reason": x["condition"]})
    add("Wastage and cost", "loss", "Damage, loss and theft", r2(sum(x["Value"] for x in loss_rows)), "NPR", 0, False,
        "Count shortages and damaged returns. Write the reason (weather, pilferage, breakage) on the count line.", loss_rows, "money")
    ret_v = val(c, "SELECT SUM(COALESCE(l.amount, l.qty*l.rate)) FROM return_lines l JOIN returns t ON t.id=l.return_id WHERE t.status='posted' AND t.date BETWEEN ? AND ?" + rc, [frm, to] + rp) or 0
    iss_v = val(c, "SELECT SUM(COALESCE(l.amount,0)) FROM issue_lines l JOIN issues i ON i.id=l.issue_id WHERE i.status='posted' AND i.date BETWEEN ? AND ?" + ic, [frm, to] + ip) or 0
    add("Wastage and cost", "returns", "Return to store", r2(100.0 * ret_v / iss_v) if iss_v else None, "%", None, True,
        "Surplus returned from site %s of %s issued." % (fmt_m(ret_v), fmt_m(iss_v)))
    # store position
    sv = r2(_stock_value_at(c, to, pid))
    below = 0
    for m in q(c, "SELECT id, reorder_level FROM materials WHERE active=1 AND reorder_level>0"):
        qn = val(c, "SELECT SUM(qty) FROM stock_balances WHERE material_id=?" + (" AND project_id=?" if pid else ""), [m["id"]] + ([pid] if pid else [])) or 0
        if qn <= m["reorder_level"]:
            below += 1
    return {"from": frm, "to": to, "kpis": k, "stock_value": sv, "below_reorder": below}


def fmt_n(v):
    return ("%.1f" % v).rstrip("0").rstrip(".") if v else "0"


def fmt_m(v):
    return "{:,.0f}".format(v or 0)


@api("kpi.finance", "accounts", "view")
def kpi_finance(c, u, a):
    """Money position: cash and bank, receivables, payables, VAT and TDS, revenue, margin, ratios."""
    to = a.get("to") or today()
    fy = _fy_of_date(c, to)
    s = _fy_bounds(c, fy)[0] if fy else (date.fromisoformat(to) - timedelta(days=365)).isoformat()
    bal = lambda *roles: _acc_bal(c, _role_ids(c, *roles), to)
    cash = bal("cash", "bank")
    ar, ap = bal("ar_control"), -bal("ap_control")
    vat = -(bal("vat_output") + bal("vat_input"))
    tdsp, tdsr = -bal("tds_payable"), bal("tds_receivable")
    ret_r, ret_p = bal("retention_receivable"), -bal("retention_payable")
    adv_c, adv_s = -bal("client_advance"), bal("supplier_advance", "subcon_advance")
    pl = inv.FUNCS["rep.pl"][0](c, u, {"from": s, "to": to})
    inc = pl["total_income"]
    margin = r2(100.0 * pl["profit"] / inc) if inc else None
    ca_ids = [r["id"] for r in q(c, "SELECT id FROM accounts WHERE type='asset' AND COALESCE(role,'') NOT IN ('fixed_asset','accum_dep')")]
    cl_ids = [r["id"] for r in q(c, "SELECT id FROM accounts WHERE type='liability'")]
    ca, cl = _acc_bal(c, ca_ids, to), -_acc_bal(c, cl_ids, to)
    m30 = (date.fromisoformat(to) - timedelta(days=30)).isoformat()
    exp30 = sum(r["amount"] for r in inv.FUNCS["rep.pl"][0](c, u, {"from": m30, "to": to})["expense"])
    overdue_r = overdue_p = None
    try:
        ag = inv.FUNCS.get("rep.ageing")
        if ag:
            r_ = ag[0](c, u, {"kind": "sales", "as_of": to})
            p_ = ag[0](c, u, {"kind": "purchase", "as_of": to})
            ov = lambda rows: r2(sum((x.get("d30") or 0) + (x.get("d60") or 0) + (x.get("d90") or 0) + (x.get("over90") or x.get("d90p") or 0) for x in (rows if isinstance(rows, list) else rows.get("rows", []))))
            overdue_r, overdue_p = ov(r_), ov(p_)
    except Exception:
        pass
    k = []

    def add(group, label, value, unit="NPR", note="", status="info", fmt="money"):
        k.append({"group": group, "label": label, "value": value, "unit": unit, "note": note, "status": status, "fmt": fmt})
    add("Cash", "Cash and bank", cash, status="good" if cash > 0 else "bad")
    add("Cash", "Spent in the last 30 days", r2(exp30))
    add("Cash", "Cash cover", r2(cash / (exp30 / 30.0)) if exp30 else None, "days", "Days of spending the cash and bank balance covers.",
        _status(cash / (exp30 / 30.0) if exp30 else None, 30), "num")
    add("Receivables and payables", "Receivable from clients", ar)
    add("Receivables and payables", "Overdue receivables", overdue_r, note="Past due date (Accounts › Ageing).", status="warn" if overdue_r else "info")
    add("Receivables and payables", "Payable to suppliers", ap)
    add("Receivables and payables", "Overdue payables", overdue_p, status="warn" if overdue_p else "info")
    add("Receivables and payables", "Retention receivable / payable", ret_r, note="Retention payable %s." % fmt_m(ret_p))
    add("Receivables and payables", "Advances: from clients / to suppliers", adv_c, note="Advances given to suppliers and subcontractors %s." % fmt_m(adv_s))
    add("Tax", "VAT payable (output less input)", r2(vat), note="Negative = VAT credit carried forward.", status="warn" if vat > 0 else "info")
    add("Tax", "TDS to deposit", r2(tdsp), status="warn" if tdsp > 0 else "info")
    add("Tax", "TDS deducted from us (advance tax)", r2(tdsr))
    add("Profit (this fiscal year)", "Income", inc)
    add("Profit (this fiscal year)", "Profit", pl["profit"], status="good" if pl["profit"] >= 0 else "bad")
    add("Profit (this fiscal year)", "Margin", margin, "%", status=_status(margin, 8), fmt="num")
    add("Ratios", "Current ratio", r2(ca / cl) if cl else None, "times", "Current assets ÷ liabilities.", _status(ca / cl if cl else None, 1.2), "num")
    return {"as_of": to, "fy": fy, "from": s, "kpis": k}


# ═════════════════════════ contracts, letters, reports, deliveries ═════════════════════════
CON_FIELDS = ["project_id", "party_id", "kind", "ref_no", "title", "value", "start_date", "end_date", "retention_pct", "advance",
              "bond_no", "bond_expiry", "insurance_expiry", "contact", "status", "remarks"]
CI_FIELDS = ["contract_id", "kind", "title", "due_date", "repeat", "responsible", "direction", "status", "done_date", "ref_no", "qty", "unit", "remarks"]
NUMF = {"value", "retention_pct", "advance", "qty"}
IDF = {"project_id", "party_id", "contract_id"}


def _clean(fields, row):
    out = {}
    for k in fields:
        if k not in row:
            continue
        v = row[k]
        if k in IDF:
            out[k] = int(v) if v not in (None, "") else None
        elif k in NUMF:
            out[k] = _f(v)
        else:
            out[k] = (str(v).strip() or None) if v is not None else None
    return out


def _add_period(d, rep):
    x = date.fromisoformat(d)
    if rep == "weekly":
        return (x + timedelta(days=7)).isoformat()
    if rep == "fortnightly":
        return (x + timedelta(days=14)).isoformat()
    months = {"monthly": 1, "quarterly": 3, "yearly": 12}.get(rep)
    if not months:
        return None
    y, m = x.year + (x.month - 1 + months) // 12, (x.month - 1 + months) % 12 + 1
    day = min(x.day, 28 if m == 2 else 30 if m in (4, 6, 9, 11) else 31)
    return date(y, m, day).isoformat()


def _con_figures(c, k):
    pid, party = k["project_id"], k["party_id"]
    f = {"billed": 0.0, "paid": 0.0, "po_value": 0.0, "pending_lines": 0, "late_lines": 0}
    if party:
        cond, p = "party_id=? AND status='posted'", [party]
        if pid:
            cond += " AND project_id=?"
            p.append(pid)
        if _has(c, "invoices"):
            f["billed"] = r2(val(c, "SELECT SUM(total) FROM invoices WHERE " + cond, p) or 0) if "total" in _cols(c, "invoices") else 0
        if _has(c, "payments"):
            col = "gross" if "gross" in _cols(c, "payments") else "net"
            f["paid"] = r2(val(c, "SELECT SUM(%s) FROM payments WHERE " % col + cond, p) or 0)
        pc_, pp_ = "vendor_id=? AND status NOT IN ('draft','cancelled')", [party]
        if pid:
            pc_ += " AND project_id=?"
            pp_.append(pid)
        f["po_value"] = r2(val(c, "SELECT SUM(total) FROM po WHERE " + pc_, pp_) or 0)
        for l in q(c, "SELECT l.qty, l.received_qty, p.delivery_date FROM po_lines l JOIN po p ON p.id=l.po_id WHERE " + pc_.replace("vendor_id", "p.vendor_id").replace("status", "p.status").replace("project_id", "p.project_id"), pp_):
            if (l["received_qty"] or 0) + 0.0001 < (l["qty"] or 0):
                f["pending_lines"] += 1
                if l["delivery_date"] and l["delivery_date"] < today():
                    f["late_lines"] += 1
    v = k["value"] or 0
    f["billed_pct"] = r2(100.0 * f["billed"] / v) if v else None
    f["retention_held"] = r2(f["billed"] * (k["retention_pct"] or 0) / 100.0)
    return f


@api("con.list", "commercial", "view")
def con_list(c, u, a):
    """Contracts of the project (or all), with what is due and what has been billed."""
    cond, p = "1=1", []
    if a.get("project_id"):
        cond += " AND (project_id=? OR project_id IS NULL)"
        p.append(int(a["project_id"]))
    if a.get("kind"):
        cond += " AND kind=?"
        p.append(a["kind"])
    rows = q(c, "SELECT * FROM contracts WHERE " + cond + " ORDER BY status, end_date", p)
    t = today()
    for r in rows:
        r["party"] = val(c, "SELECT name FROM parties WHERE id=?", (r["party_id"],)) if r["party_id"] else None
        r["due"] = val(c, "SELECT COUNT(*) FROM contract_items WHERE contract_id=? AND status='pending' AND due_date<=?", (r["id"], (date.today() + timedelta(days=7)).isoformat()))
        r["overdue"] = val(c, "SELECT COUNT(*) FROM contract_items WHERE contract_id=? AND status='pending' AND due_date<?", (r["id"], t))
        r["next_due"] = val(c, "SELECT MIN(due_date) FROM contract_items WHERE contract_id=? AND status='pending'", (r["id"],))
        r.update(_con_figures(c, r))
        flags = []
        for k, lbl in (("bond_expiry", "bond"), ("insurance_expiry", "insurance"), ("end_date", "contract")):
            if r[k] and r["status"] == "active" and r[k] <= (date.today() + timedelta(days=30)).isoformat():
                flags.append("%s %s %s" % (lbl, "expired" if r[k] < t else "expires", r[k]))
        r["flags"] = "; ".join(flags)
    return rows


@api("con.get", "commercial", "view")
def con_get(c, u, a):
    k = get(c, "contracts", int(a["id"]), "Contract")
    k["items"] = q(c, "SELECT * FROM contract_items WHERE contract_id=? ORDER BY status DESC, due_date", (k["id"],))
    k["party"] = val(c, "SELECT name FROM parties WHERE id=?", (k["party_id"],)) if k["party_id"] else None
    k["figures"] = _con_figures(c, k)
    k["deliveries"] = []
    if k["party_id"]:
        cond, p = "p.vendor_id=? AND p.status NOT IN ('draft','cancelled')", [k["party_id"]]
        if k["project_id"]:
            cond += " AND p.project_id=?"
            p.append(k["project_id"])
        k["deliveries"] = q(c, "SELECT p.no, p.date, p.delivery_date, p.status, l.description, m.name material, l.qty, l.received_qty, l.unit, "
                               "(SELECT MAX(g.date) FROM grn g WHERE g.po_id=p.id AND g.status='posted') last_grn FROM po_lines l JOIN po p ON p.id=l.po_id "
                               "LEFT JOIN materials m ON m.id=l.material_id WHERE " + cond + " ORDER BY p.delivery_date", p)
    return k


@api("con.save", "commercial", "edit")
def con_save(c, u, a):
    r = a.get("row") or {}
    data = _clean(CON_FIELDS, r)
    if not r.get("id"):
        need(r, "title")
        data.setdefault("status", "active")
        data["created_by"], data["ts"] = u["id"], now()
        rid = ins(c, "contracts", data)
        # standard deliverables by kind of contract
        for it in a.get("template") or []:
            ins(c, "contract_items", dict(_clean(CI_FIELDS, it), contract_id=rid, status="pending"))
    else:
        rid = int(r["id"])
        upd(c, "contracts", rid, data)
    audit(c, u, "save", "contracts", rid, data)
    return con_get(c, u, {"id": rid})


@api("con.delete", "commercial", "approve")
def con_delete(c, u, a):
    k = get(c, "contracts", int(a["id"]), "Contract")
    if val(c, "SELECT COUNT(*) FROM contract_items WHERE contract_id=? AND status='done'", (k["id"],)):
        raise ApiError("This contract has completed letters / reports. Mark it completed instead.")
    c.execute("DELETE FROM contract_items WHERE contract_id=?", (k["id"],))
    c.execute("DELETE FROM contracts WHERE id=?", (k["id"],))
    audit(c, u, "delete", "contracts", k["id"], k)
    return True


@api("citem.save", "commercial", "edit")
def citem_save(c, u, a):
    r = a.get("row") or {}
    data = _clean(CI_FIELDS, r)
    if r.get("id"):
        upd(c, "contract_items", int(r["id"]), data)
        rid = int(r["id"])
    else:
        need(r, "contract_id", "title")
        data.setdefault("status", "pending")
        rid = ins(c, "contract_items", data)
    return q1(c, "SELECT * FROM contract_items WHERE id=?", (rid,))


@api("citem.done", "commercial", "edit")
def citem_done(c, u, a):
    """Mark a letter / report / delivery done; a repeating one gets its next date."""
    it = get(c, "contract_items", int(a["id"]), "Item")
    upd(c, "contract_items", it["id"], {"status": "done", "done_date": a.get("done_date") or today(), "ref_no": a.get("ref_no") or it["ref_no"]})
    nxt = None
    if it["repeat"] and it["repeat"] != "none" and it["due_date"]:
        nd = _add_period(it["due_date"], it["repeat"])
        k = q1(c, "SELECT end_date FROM contracts WHERE id=?", (it["contract_id"],))
        if nd and (not k or not k["end_date"] or nd <= k["end_date"]):
            x = {kk: it[kk] for kk in CI_FIELDS if kk in it}
            x.update({"due_date": nd, "status": "pending", "done_date": None, "ref_no": None})
            nxt = ins(c, "contract_items", x)
    audit(c, u, "done", "contract_items", it["id"], {"next": nxt})
    return {"next_id": nxt}


@api("citem.delete", "commercial", "edit")
def citem_delete(c, u, a):
    c.execute("DELETE FROM contract_items WHERE id=?", (int(a["id"]),))
    return True


@api("con.schedule", "commercial", "view")
def con_schedule(c, u, a):
    """What is due: letters, reports, deliveries and milestones of every contract; expiring bonds and insurance;
    late deliveries on purchase orders."""
    days = int(_f(a.get("days"), 30))
    t = today()
    horizon = (date.today() + timedelta(days=days)).isoformat()
    cond, p = "", []
    if a.get("project_id"):
        cond = " AND (k.project_id=? OR k.project_id IS NULL)"
        p.append(int(a["project_id"]))
    items = q(c, "SELECT i.*, k.title contract, k.ref_no contract_ref, k.party_id, k.kind contract_kind FROM contract_items i JOIN contracts k ON k.id=i.contract_id "
                 "WHERE i.status='pending' AND k.status='active' AND i.due_date<=?" + cond + " ORDER BY i.due_date", [horizon] + p)
    for x in items:
        x["party"] = val(c, "SELECT name FROM parties WHERE id=?", (x["party_id"],)) if x["party_id"] else None
        x["days"] = (date.fromisoformat(x["due_date"]) - date.today()).days if x["due_date"] else None
        x["state"] = "overdue" if x["due_date"] and x["due_date"] < t else ("today" if x["due_date"] == t else "due")
    expiring = []
    for k in q(c, "SELECT * FROM contracts k WHERE k.status='active'" + cond, p):
        for col, lbl in (("bond_expiry", "Performance bond / guarantee"), ("insurance_expiry", "Insurance"), ("end_date", "Contract end")):
            if k[col] and k[col] <= horizon:
                expiring.append({"contract": k["title"], "ref_no": k["ref_no"], "what": lbl, "date": k[col],
                                 "party": val(c, "SELECT name FROM parties WHERE id=?", (k["party_id"],)) if k["party_id"] else None,
                                 "state": "expired" if k[col] < t else "soon"})
    pc_, pp_ = "", []
    if a.get("project_id"):
        pc_, pp_ = " AND p.project_id=?", [int(a["project_id"])]
    late = q(c, "SELECT p.no, p.delivery_date, pa.name party, COALESCE(m.name, l.description) item, l.qty, l.received_qty, l.unit FROM po_lines l "
                "JOIN po p ON p.id=l.po_id LEFT JOIN parties pa ON pa.id=p.vendor_id LEFT JOIN materials m ON m.id=l.material_id "
                "WHERE p.status IN ('approved','partly_received','sent','open') AND p.delivery_date IS NOT NULL AND p.delivery_date<=? "
                "AND COALESCE(l.received_qty,0)+0.0001<l.qty" + pc_ + " ORDER BY p.delivery_date", [horizon] + pp_)
    for x in late:
        x["state"] = "late" if x["delivery_date"] < t else "due"
    return {"items": items, "expiring": expiring, "deliveries": late, "today": t, "days": days}


CON_TEMPLATES = {
    "subcontract": [("report", "Monthly progress report", "monthly", "they_send"), ("payment", "Running bill (RA bill) submission", "monthly", "they_send"),
                    ("report", "Safety report", "monthly", "they_send"), ("milestone", "Completion / handover", "none", "they_send")],
    "supply": [("delivery", "Delivery as per PO schedule", "none", "they_send"), ("letter", "Test certificates with each lot", "none", "they_send")],
    "hire": [("report", "Monthly logsheet signed by both", "monthly", "we_send"), ("payment", "Monthly hire bill", "monthly", "they_send")],
    "client": [("report", "Monthly progress report to the employer / engineer", "monthly", "we_send"),
               ("payment", "IPC submission", "monthly", "we_send"), ("report", "Quality / test report", "monthly", "we_send"),
               ("letter", "Programme update", "quarterly", "we_send"), ("letter", "Insurance renewal", "yearly", "we_send")],
    "consultant": [("report", "Monthly report", "monthly", "they_send")],
}


@api("con.templates", "commercial", "view")
def con_templates(c, u, a):
    return {k: [{"kind": x[0], "title": x[1], "repeat": x[2], "direction": x[3]} for x in v] for k, v in CON_TEMPLATES.items()}


# ═════════════════════════ machines: repairs and history ═════════════════════════
@api("wo.repair", "equipment", "edit")
def wo_repair(c, u, a):
    """Repair details of a work order: parts, labour, workshop, cause. Can be filled after completion."""
    w = get(c, "work_orders", int(a["id"]), "Work order")
    if w["status"] == "cancelled":
        raise ApiError("This work order is cancelled.")
    data = {}
    for k in ("parts_cost", "labour_cost", "external_cost"):
        if k in a:
            data[k] = _f(a.get(k))
    for k in ("workshop", "parts_replaced", "failure_code", "cause_detail", "repair_remarks", "action_taken", "technician"):
        if k in a:
            data[k] = (a.get(k) or "").strip() or None
    if "downtime_hours" in a and a.get("downtime_hours") not in (None, ""):
        data["downtime_hours"] = _f(a["downtime_hours"])
    upd(c, "work_orders", w["id"], data)
    audit(c, u, "repair", "work_orders", w["id"], data)
    return q1(c, "SELECT * FROM work_orders WHERE id=?", (w["id"],))


@api("wo.record", "equipment", "edit")
def wo_record(c, u, a):
    """Enter a repair or service that is already finished (e.g. done at an outside workshop)."""
    need(a, "equipment_id", "description")
    eq = get(c, "equipment", int(a["equipment_id"]), "Machine")
    start = a.get("reported_at") or (today() + "T08:00:00")
    end = a.get("completed_at") or start
    if len(start) == 10:
        start += "T08:00:00"
    if len(end) == 10:
        end += "T17:00:00"
    dt = a.get("downtime_hours")
    if dt in (None, ""):
        s1, e1 = _ts(start), _ts(end)
        dt = r2((e1 - s1).total_seconds() / 3600.0) if s1 and e1 and e1 > s1 else 0
    data = {"no": core.next_no(c, "WO", start[:10]), "equipment_id": eq["id"], "project_id": int(a["project_id"]) if a.get("project_id") else None,
            "type": a.get("type") or "breakdown", "status": "completed", "reported_at": start, "started_at": start, "completed_at": end,
            "description": a["description"], "action_taken": a.get("action_taken"), "downtime_hours": _f(dt), "meter": _f(a.get("meter"), None),
            "technician": a.get("technician"), "created_by": u["id"]}
    for k in ("parts_cost", "labour_cost", "external_cost"):
        data[k] = _f(a.get(k))
    for k in ("workshop", "parts_replaced", "failure_code", "cause_detail", "repair_remarks"):
        data[k] = (a.get(k) or "").strip() or None
    cols = _cols(c, "work_orders")
    data = {k: v for k, v in data.items() if k in cols}
    rid = ins(c, "work_orders", data)
    if a.get("plan_id"):
        plan = q1(c, "SELECT * FROM maint_plans WHERE id=?", (int(a["plan_id"]),))
        if plan:
            upd(c, "work_orders", rid, {"plan_id": plan["id"]})
            upd(c, "maint_plans", plan["id"], {"last_date": end[:10], "last_meter": _f(a.get("meter"), plan["last_meter"] or 0)})
    audit(c, u, "record", "work_orders", rid, data)
    return q1(c, "SELECT * FROM work_orders WHERE id=?", (rid,))


def _wo_spares(c, wo_id):
    return r2(val(c, "SELECT SUM(COALESCE(l.amount,0)) FROM issue_lines l JOIN issues i ON i.id=l.issue_id WHERE i.wo_id=? AND i.status='posted'", (wo_id,)) or 0)


@api("eq.history", "equipment", "view")
def eq_history(c, u, a):
    """Complete maintenance and repair history: every breakdown, repair and service, parts and oil issued,
    downtime and cost, with MTBF / MTTR / availability per machine."""
    frm = a.get("from") or "0000-01-01"
    to = a.get("to") or today()
    eq_cond, ep = "", []
    if a.get("equipment_id"):
        eq_cond, ep = " AND id=?", [int(a["equipment_id"])]
    machines = q(c, "SELECT id, code, name, category, status, meter, meter_type FROM equipment WHERE 1=1" + eq_cond + " ORDER BY code", ep)
    one = bool(a.get("equipment_id"))
    events, summary = [], []
    for e in machines:
        wos = q(c, "SELECT * FROM work_orders WHERE equipment_id=? AND status<>'cancelled' AND substr(COALESCE(completed_at, reported_at),1,10) BETWEEN ? AND ? "
                   "ORDER BY COALESCE(completed_at, reported_at)", (e["id"], frm, to))
        bd = [w for w in wos if (w["type"] or "breakdown") == "breakdown"]
        cost_total, down = 0.0, 0.0
        for w in wos:
            sp = _wo_spares(c, w["id"])
            cost = r2(sp + (w.get("parts_cost") or 0) + (w.get("labour_cost") or 0) + (w.get("external_cost") or 0))
            cost_total += cost
            down += w["downtime_hours"] or 0
            if one or a.get("timeline"):
                events.append({"date": (w["completed_at"] or w["reported_at"] or "")[:10], "equipment_id": e["id"], "machine": e["code"],
                               "kind": {"breakdown": "Breakdown / repair", "preventive": "Service (plan)", "inspection": "Inspection"}.get(w["type"], w["type"]),
                               "ref": w["no"], "status": w["status"], "what": w["description"], "action": w.get("action_taken"),
                               "parts": w.get("parts_replaced"), "workshop": w.get("workshop") or w.get("technician"),
                               "cause": w.get("cause_detail") or w.get("failure_code"), "downtime": w["downtime_hours"] or 0,
                               "meter": w["meter"], "spares": sp, "cost": cost, "wo_id": w["id"]})
        if one or a.get("timeline"):
            if _has(c, "log_service"):
                for s in q(c, "SELECT * FROM log_service WHERE equipment_id=? AND date BETWEEN ? AND ? AND wo_id IS NULL ORDER BY date", (e["id"], frm, to)):
                    events.append({"date": s["date"], "equipment_id": e["id"], "machine": e["code"], "kind": "Service (logsheet)", "ref": "",
                                   "status": "done", "what": s["description"], "action": None, "parts": ((s["part_no"] or "") + " " + ("%g %s" % (s["qty"] or 0, s["unit"] or "") if s["qty"] else "")).strip(),
                                   "workshop": s.get("brand"), "cause": None, "downtime": 0, "meter": s.get("at_hour") or s.get("at_km"), "spares": 0, "cost": 0})
            for x in q(c, "SELECT i.date, i.no, i.wo_id, m.name, m.unit, l.qty, l.amount FROM issue_lines l JOIN issues i ON i.id=l.issue_id JOIN materials m ON m.id=l.material_id "
                          "WHERE l.equipment_id=? AND i.status='posted' AND i.wo_id IS NULL AND i.date BETWEEN ? AND ? ORDER BY i.date", (e["id"], frm, to)):
                events.append({"date": x["date"], "equipment_id": e["id"], "machine": e["code"], "kind": "Issued from store", "ref": x["no"], "status": "posted",
                               "what": x["name"], "action": None, "parts": "%g %s" % (x["qty"] or 0, x["unit"] or ""), "workshop": None, "cause": None,
                               "downtime": 0, "meter": None, "spares": x["amount"] or 0, "cost": x["amount"] or 0, "oil_fuel": True})
        lg = q1(c, "SELECT SUM(hours) h, SUM(breakdown_hours) b, SUM(idle_hours) i, COUNT(DISTINCT date) d FROM logsheets WHERE equipment_id=? AND date BETWEEN ? AND ?",
                (e["id"], frm, to))
        worked, bdh = lg["h"] or 0, lg["b"] or 0
        nb = len(bd)
        down_bd = sum(w["downtime_hours"] or 0 for w in bd) or bdh
        issued = r2(val(c, "SELECT SUM(COALESCE(l.amount,0)) FROM issue_lines l JOIN issues i ON i.id=l.issue_id WHERE l.equipment_id=? AND i.status='posted' "
                           "AND i.wo_id IS NULL AND i.date BETWEEN ? AND ?", (e["id"], frm, to)) or 0)
        summary.append({"equipment_id": e["id"], "code": e["code"], "name": e["name"], "status": e["status"], "meter": e["meter"],
                        "breakdowns": nb, "services": len(wos) - nb, "downtime": r2(down), "worked": r2(worked),
                        "mtbf": r2(worked / nb) if nb else None, "mttr": r2(down_bd / nb) if nb else None,
                        "availability": r2(100.0 * worked / (worked + bdh)) if (worked + bdh) else None,
                        "repair_cost": r2(cost_total), "store_issues": issued,
                        "cost_per_hour": r2((cost_total) / worked) if worked else None,
                        "last_repair": (bd[-1]["completed_at"] or bd[-1]["reported_at"] or "")[:10] if bd else None})
    events.sort(key=lambda x: (x["date"] or "", x["machine"]), reverse=True)
    plans = []
    try:
        plans = inv.FUNCS["maint.status"][0](c, u, {"equipment_id": int(a["equipment_id"])} if one else {}) if "maint.status" in inv.FUNCS else []
    except Exception:
        plans = []
    return {"from": frm, "to": to, "summary": summary, "events": events, "plans": plans}


# ═════════════════════════ wrap-ups at start ═════════════════════════
_wrap_login()
_wrap_reports()
_wrap_masters()
