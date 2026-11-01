"""Start the BuildCore engine for the web: PostgreSQL in place of SQLite, then the normal engine start-up.

    from web import boot; server = boot.start()

Nothing in the desktop engine files is changed for this; the differences live in this package.
"""
import importlib
import os
import sys

ENGINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ENGINE not in sys.path:
    sys.path.insert(0, ENGINE)

# The engine keeps nothing on disk in the web edition except short-lived temporary files.
os.environ.setdefault("BCO_DATA_DIR", os.path.join(os.environ.get("TMPDIR") or "/tmp", "buildcore"))
os.environ.setdefault("BCO_WEB", "1")

REAL_SQLITE3 = importlib.import_module("sqlite3")      # kept for importing / exporting desktop data files
from web import pgsqlite  # noqa: E402

pgsqlite.REAL = REAL_SQLITE3
sys.modules["sqlite3"] = pgsqlite

_STARTED = {}


def start():
    """Import the engine exactly as the desktop server does and prepare the database."""
    if "server" in _STARTED:
        return _STARTED["server"]
    import server  # noqa: F401  (registers every screen's functions)
    sys.modules.setdefault("server", server)
    from web import webpatch
    webpatch.before_init(server)
    import core
    core.init_db()
    webpatch.after_init(server)
    _STARTED["server"] = server
    return server
