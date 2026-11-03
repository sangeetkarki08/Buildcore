"""BuildCore 2.37 - speed for many projects and many users.

  Faster reading   every screen's connection to the data file becomes fastdb's (same answers, read faster;
                   see fastdb.py): one answer per repeated question within a request, the project of a voucher
                   line asked in a way that can use an index.
  Indexes          voucher lines and vouchers by project, BOQ item and activity, made once here at start-up.
                   An index changes no data and no figure; a data file with them still opens in older versions.
"""
import os
import sqlite3
import sys

import core
import fastdb

_ORIG = core.connect


def connect():
    os.makedirs(core.DATA_DIR, exist_ok=True)
    c = fastdb.connect(core.DB_PATH, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=OFF")
    try:
        c.execute("PRAGMA journal_mode=WAL")
    except sqlite3.OperationalError:  # e.g. network drive
        c.execute("PRAGMA journal_mode=DELETE")
    return c


connect._bco237 = True


def _install():
    """Every module that took core.connect by name ("from core import connect") gets the faster one too."""
    if getattr(core.connect, "_bco237", False):
        return
    orig = core.connect
    for m in list(sys.modules.values()):
        try:
            if getattr(m, "connect", None) is orig:
                setattr(m, "connect", connect)
        except Exception:
            pass
    core.connect = connect


def init_speed(c):
    _install()
    fastdb.add_indexes(c)
