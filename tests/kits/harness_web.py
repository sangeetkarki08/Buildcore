"""Test harness for BuildCore WEB: same calls as the desktop harness, but the engine runs on PostgreSQL
(engine/web/pgsqlite.py) and the test company (a desktop SQLite data file) is brought in through the web's
own restore path (transfer.import_sqlite), exactly as Backup & restore does on the website."""
import hashlib, os, sys
DATA = os.environ.setdefault("BCO_DATA_DIR", "/tmp/bco_t/data")
WEB = os.environ["BCO_WEB_ROOT"]
ENG = os.path.join(WEB, "engine")
import psycopg
db = "t_" + hashlib.md5(DATA.encode()).hexdigest()[:14]
src = os.path.join(DATA, "data", "buildcore.db")
have = os.path.isfile(src)
if have or not os.path.isfile(src + ".src"):      # a second process on the same test company keeps its database
    with psycopg.connect("postgresql://postgres@localhost:5432/postgres", autocommit=True) as a:
        a.execute('DROP DATABASE IF EXISTS "%s" WITH (FORCE)' % db)
        a.execute('CREATE DATABASE "%s"' % db)
os.environ["DATABASE_URL"] = "postgresql://postgres@localhost:5432/%s" % db
if have:
    os.rename(src, src + ".src")
sys.path.insert(0, ENG)
os.chdir(ENG)
from web import boot  # noqa
boot.start()
import core  # noqa
if have:
    from web import transfer
    transfer.import_sqlite(src + ".src", "buildcore")
    core.init_db()
import api_inventory as inv  # noqa
from core import q, q1, val  # noqa
USERS = {}


def conn():
    return core.connect()


def user(name="admin"):
    c = core.connect()
    u = q1(c, "SELECT * FROM users WHERE username=?", (name,))
    c.close()
    return u


def call(fn, a=None, u="admin", check=True):
    f, module, action, public = inv.FUNCS[fn]
    us = user(u) if isinstance(u, str) else u
    c = core.connect()
    try:
        if module and check:
            core.require(us, module, action)
        c.execute("BEGIN IMMEDIATE")
        r = f(c, us, dict(a or {}))
        c.commit()
        return r
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()


def ensure_admin():
    c = core.connect()
    n = val(c, "SELECT COUNT(*) FROM users")
    c.close()
    if not n:
        c = core.connect()
        inv.FUNCS["auth.setup"][0](c, None, {"username": "admin", "password": "admin12345", "name": "Admin",
                                             "company_name": "Test Builders"})
        c.commit()
        c.close()


# ───────────── extensions for seed.py (the existing API above is unchanged) ─────────────
def restart():
    """Run the engine start-up again, as a server restart would. On a brand-new data file the add-on
    modules start before the default chart of accounts exists, so their own accounts (equipment loan,
    material with subcontractors, trading...) only appear at the next start-up."""
    core.init_db()


def ensure_user(username, name, role, password):
    """Create (once) a user with a role through the Administration > Users endpoint."""
    us = user(username)
    if us:
        return us["id"]
    r = call("admin.user_save", {"row": {"username": username, "name": name, "role": role,
                                         "password": password, "active": 1}})
    return r["id"]
