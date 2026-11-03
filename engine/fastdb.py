"""BuildCore 2.37 - faster reading of the data file, with exactly the same results.

Three things, all inside the connection that every screen already uses (core.connect):

1. Same question, same answer, asked once. While one request runs, the data file is locked for writing
   (BEGIN IMMEDIATE), so nobody else can change it. When a company-wide screen asks the same question many
   times (the command centre asked "income since ..." 200 times for 200 projects), the first answer is kept
   and given again. The moment the request itself writes anything, everything kept is forgotten, so a later
   question always sees the new data. Nothing is kept after the request ends.
2. Project of a voucher line. Many reports pick lines with  COALESCE(l.project_id, v.project_id)=?  ("the
   line's project, else the voucher's project"). The data file cannot use an index for that and read every
   voucher line for each project. It is asked as the identical condition
   (l.project_id=? OR (l.project_id IS NULL AND v.project_id=?)), which can use the project indexes.
3. Indexes on voucher lines and vouchers by project, BOQ item and activity (made once, at start-up).
   An index changes no data and no figure; it only finds rows faster. A data file with them still opens in
   older BuildCore versions.
"""
import os
import re
import sqlite3
import sys
import threading

_VERBOSE = bool(os.environ.get("BCO_VERBOSE"))

# Server edition with several engines side by side (bcserver.py): a request first reads without taking the
# write lock ("BEGIN" instead of "BEGIN IMMEDIATE"), so engines can answer at the same time. If it then
# needs to write and another engine wrote in the meantime, SQLite refuses the write; the request is marked
# "lost" and bcserver runs it again from the start with the write lock. Off unless bcserver turns it on.
MODE = threading.local()
BEFORE_COMMIT = []        # bcserver: work done in the same transaction as a request that wrote


def _deferred():
    return getattr(MODE, "deferred", False)


def _lost(e):
    if _deferred() and isinstance(e, sqlite3.OperationalError) and ("locked" in str(e) or "busy" in str(e).lower()):
        MODE.lost = True
        if _VERBOSE:
            import traceback
            sys.stderr.write("engine: write refused (%s) at %s\n" % (e, " | ".join(
                x.strip().replace("\n", " ") for x in traceback.format_stack(limit=5)[-4:-1])[:500]))

INDEXES = [
    "CREATE INDEX IF NOT EXISTS ix_vl_project ON voucher_lines(project_id)",
    "CREATE INDEX IF NOT EXISTS ix_v_project ON vouchers(project_id)",
    "CREATE INDEX IF NOT EXISTS ix_vl_boq ON voucher_lines(boq_item_id)",
    "CREATE INDEX IF NOT EXISTS ix_vl_act ON voucher_lines(activity_id)",
]

_COALESCE = re.compile(r"COALESCE\(\s*l\.project_id\s*,\s*v\.project_id\s*\)\s*=\s*\?", re.I)
_VOLATILE = re.compile(r"now'|'now|random\(|changes\(|last_insert_rowid|total_changes|julianday\(\s*\)|bcfn\.", re.I)
MAX_ROWS = 50000          # a very large answer is not kept
STATS = {"asked": 0, "kept": 0, "rewritten": 0}


def _is_read(sql):
    s = sql.lstrip()[:7].upper()
    return s.startswith("SELECT") or (s.startswith("PRAGMA") and "=" not in sql and "(" in sql or
                                      sql.strip().upper() == "PRAGMA DATABASE_LIST")


def rewrite(sql, params):
    """COALESCE(l.project_id, v.project_id)=?  ->  (l.project_id=? OR (l.project_id IS NULL AND v.project_id=?))"""
    if "COALESCE" not in sql.upper() or not _COALESCE.search(sql) or isinstance(params, dict):
        return sql, params
    params = list(params or ())
    out, k, pos = [], 0, 0          # k = how many ? came before (outside quotes)
    i, n, quote = 0, len(sql), None
    while i < n:
        ch = sql[i]
        if quote:
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in ("'", '"'):
            quote = ch
            i += 1
            continue
        if ch == "?":
            k += 1
            i += 1
            continue
        m = _COALESCE.match(sql, i)
        if m:
            if k >= len(params):
                return sql, tuple(params)      # unusual shape: leave it as it is
            out.append(sql[pos:i])
            out.append("(l.project_id=? OR (l.project_id IS NULL AND v.project_id=?))")
            params.insert(k, params[k])
            k += 2
            pos = i = m.end()
            STATS["rewritten"] += 1
            continue
        i += 1
    out.append(sql[pos:])
    return "".join(out), tuple(params)


class _Kept:
    """A finished answer, read like a cursor."""
    __slots__ = ("_rows", "_i", "description", "rowcount", "lastrowid", "connection", "arraysize")

    def __init__(self, rows, description, conn):
        self._rows, self._i, self.description, self.connection = rows, 0, description, conn
        self.rowcount, self.lastrowid, self.arraysize = -1, None, 1

    def fetchone(self):
        if self._i < len(self._rows):
            self._i += 1
            return self._rows[self._i - 1]
        return None

    def fetchall(self):
        r = self._rows[self._i:]
        self._i = len(self._rows)
        return list(r)

    def fetchmany(self, size=None):
        size = size or self.arraysize
        r = self._rows[self._i:self._i + size]
        self._i += len(r)
        return list(r)

    def __iter__(self):
        while self._i < len(self._rows):
            self._i += 1
            yield self._rows[self._i - 1]

    def close(self):
        pass


class _Cur(sqlite3.Cursor):
    def execute(self, sql, params=()):
        self.connection._forget(sql)
        sql, params = rewrite(sql, params)
        try:
            return super().execute(sql, params)
        except sqlite3.OperationalError as e:
            _lost(e)
            raise

    def executemany(self, sql, seq):
        self.connection._kept = None if self.connection._kept is None else {}
        try:
            return super().executemany(sql, seq)
        except sqlite3.OperationalError as e:
            _lost(e)
            raise

    def executescript(self, script):
        self.connection._kept = None if self.connection._kept is None else {}
        try:
            return super().executescript(script)
        except sqlite3.OperationalError as e:
            _lost(e)
            raise


class FastConnection(sqlite3.Connection):
    _kept = None            # answers kept during a write-locked request; None = keep nothing

    def cursor(self, factory=_Cur):
        return super().cursor(factory)

    def _forget(self, sql):
        if self._kept is not None and not _is_read(sql):
            self._kept = {}

    def execute(self, sql, params=()):
        head = sql.lstrip()[:16].upper()
        if head.startswith("BEGIN IMMEDIATE") or head.startswith("BEGIN EXCLUSIVE"):
            # one read snapshot (deferred) or the write lock (immediate): either way nothing changes under us
            r = super().execute("BEGIN" if _deferred() else sql, params)
            self._kept = {}
            return r
        if not _is_read(sql):
            if self._kept is not None:
                self._kept = {}
            if head.startswith(("COMMIT", "ROLLBACK", "END")):
                self._kept = None
            sql, params = rewrite(sql, params)
            try:
                r = super().execute(sql, params)
            except sqlite3.OperationalError as e:
                _lost(e)
                raise
            if head.startswith(("INSERT", "UPDATE", "DELETE", "REPLACE")) and getattr(MODE, "track", False):
                MODE.wrote = True
            return r
        sql, params = rewrite(sql, params)
        if self._kept is not None and not self.in_transaction:
            self._kept = None              # the write-locked request ended: keep nothing from here on
        kept = self._kept
        if kept is None or _VOLATILE.search(sql):
            return super().execute(sql, params)
        try:
            key = (sql, tuple(params) if not isinstance(params, dict) else tuple(sorted(params.items())), self.row_factory)
            hash(key)
        except TypeError:
            return super().execute(sql, params)
        STATS["asked"] += 1
        hit = kept.get(key)
        if hit is not None:
            STATS["kept"] += 1
            return _Kept(hit[0], hit[1], self)
        cur = super().execute(sql, params)
        rows = cur.fetchall()
        if len(rows) <= MAX_ROWS:
            kept[key] = (tuple(rows), cur.description)
        return _Kept(rows, cur.description, self)

    def executemany(self, sql, seq):
        if self._kept is not None:
            self._kept = {}
        try:
            return super().executemany(sql, seq)
        except sqlite3.OperationalError as e:
            _lost(e)
            raise

    def executescript(self, script):
        self._kept = None
        try:
            return super().executescript(script)
        except sqlite3.OperationalError as e:
            _lost(e)
            raise

    def commit(self):
        self._kept = None
        if getattr(MODE, "track", False) and getattr(MODE, "wrote", False) and BEFORE_COMMIT and self.in_transaction:
            MODE.track = False                 # the hooks' own writes are part of this same request
            try:
                for hook in BEFORE_COMMIT:
                    try:
                        hook(self)
                    except Exception:
                        pass
            finally:
                MODE.track = True
                self._kept = None
        return super().commit()

    def rollback(self):
        self._kept = None
        return super().rollback()


def connect(path, timeout=30):
    """sqlite3.connect with the faster connection; falls back to the plain one where it is not available."""
    try:
        if isinstance(sqlite3.Connection, type) and getattr(sqlite3, "__name__", "") == "sqlite3":
            return sqlite3.connect(path, timeout=timeout, factory=FastConnection)
    except TypeError:
        pass
    return sqlite3.connect(path, timeout=timeout)


def add_indexes(c):
    for s in INDEXES:
        try:
            c.execute(s)
        except sqlite3.OperationalError:        # a table not there yet (very old file): skip
            pass
