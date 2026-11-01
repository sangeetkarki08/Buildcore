"""Move a company's data between a BuildCore desktop data file (SQLite) and the web database (PostgreSQL).

    import_sqlite(path_to_buildcore_db, target_schema)  -> report
    export_sqlite(schema, path_to_new_db)                -> report

Import keeps every table, row, id and value of the desktop file. It builds the tables from the file's own
definitions, copies all rows with their ids, then runs the engine's normal start-up on them (as the desktop
does after a restore), and only then swaps the result in for the company's current data. The data that was
there before is kept as a schema named <schema>__before_<time> (the two newest are kept).

PostgreSQL is stricter than SQLite about types: a text such as 'n/a' cannot be stored in a number column.
Such a value is stored as empty in the column and kept word for word in the table web_import_notes, with
its table, row id and column, so nothing is lost and it can be put right.
"""
import json
import os
import re
import time
from datetime import datetime

from web import pgsqlite

STAGE_DIR = "__import"
NUMERIC = ("numeric", "double precision", "bigint", "integer", "smallint", "real")


def _real():
    return pgsqlite.REAL


def check_sqlite(path):
    sq = _real()
    with open(path, "rb") as fh:
        if fh.read(16) != b"SQLite format 3\x00":
            raise ValueError("This is not a BuildCore data or backup file.")
    k = sq.connect("file:%s?mode=ro" % path, uri=True)
    try:
        ok = k.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        names = {r[0] for r in k.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        k.close()
    if not ok:
        raise ValueError("The file is damaged (SQLite integrity check failed).")
    if not {"vouchers", "stock_ledger", "users"} <= names:
        raise ValueError("The file is not a BuildCore data file (vouchers, stock ledger or users missing).")
    return names


def _pg_for_schema(schema):
    pg = pgsqlite._raw_connect()
    pgsqlite.ensure_functions(pg)
    pg.execute('CREATE SCHEMA IF NOT EXISTS "%s"' % schema)
    pg.execute('SET search_path TO "%s", bcfn, public' % schema)
    return pg


def _coerce(v, pgtype):
    """value from SQLite -> value PostgreSQL accepts for the column; (value, ok)"""
    if v is None:
        return None, True
    if pgtype in NUMERIC:
        if isinstance(v, bool):
            return int(v), True
        if isinstance(v, (int, float)):
            if isinstance(v, float) and (v != v or v in (float("inf"), float("-inf"))):
                return None, False
            if pgtype in ("bigint", "integer", "smallint") and isinstance(v, float) and v != int(v):
                return None, False
            return v, True
        if isinstance(v, bytes):
            return None, False
        s = str(v).strip()
        if s == "":
            return None, False
        try:
            f = float(s)
            if f != f or f in (float("inf"), float("-inf")):
                return None, False
            if re.fullmatch(r"[-+]?\d+", s):
                return int(s), True
            if pgtype in ("bigint", "integer", "smallint"):
                return (int(f), True) if f == int(f) else (None, False)
            return f, True
        except ValueError:
            return None, False
    if pgtype == "bytea":
        return (bytes(v) if isinstance(v, (bytes, bytearray, memoryview)) else str(v).encode()), True
    if isinstance(v, bytes):
        try:
            return v.decode("utf-8"), True
        except UnicodeDecodeError:
            return v.decode("latin-1"), True
    if isinstance(v, float) and v == int(v) and abs(v) < 1e15:
        return repr(v), True
    s = str(v)
    if "\x00" in s:
        return s.replace("\x00", ""), False
    return s, True


def import_sqlite(path, target_schema, progress=None, run_startup=True):
    """Copy a desktop data file into target_schema (replacing it). Returns a report dict."""
    t0 = time.time()
    say = progress or (lambda m: None)
    check_sqlite(path)
    stage = target_schema + "__in"
    sq = _real().connect("file:%s?mode=ro" % path, uri=True)
    sq.text_factory = bytes            # read text exactly as stored; decoded below
    pg = pgsqlite._raw_connect()
    pgsqlite.ensure_functions(pg)
    pg.execute('DROP SCHEMA IF EXISTS "%s" CASCADE' % stage)
    pg.execute('CREATE SCHEMA "%s"' % stage)
    pg.execute('SET search_path TO "%s", bcfn, public' % stage)
    report = {"tables": {}, "rows": 0, "notes": 0, "file": os.path.basename(path), "schema": target_schema}
    master = [(n.decode() if isinstance(n, bytes) else n, t.decode() if isinstance(t, bytes) else t,
               (s.decode() if isinstance(s, bytes) else s))
              for n, t, s in sq.execute("SELECT name, type, sql FROM sqlite_master WHERE sql IS NOT NULL "
                                        "AND name NOT LIKE 'sqlite_%' ORDER BY CASE type WHEN 'table' THEN 0 "
                                        "WHEN 'index' THEN 1 ELSE 2 END, rowid")]
    # 1. tables, from the file's own definitions
    tables = [(n, s) for n, t, s in master if t == "table"]
    for name, sql in tables:
        plan = pgsqlite._make_plan(sql)
        ddl = plan.sql
        ddl = re.sub(r"(?i)^CREATE\s+TABLE\s+(IF\s+NOT\s+EXISTS\s+)?", "CREATE TABLE IF NOT EXISTS ", ddl)
        if plan.nparams:
            raise ValueError("Unexpected parameter in the definition of %s" % name)
        pg.execute(ddl)
    pg.execute(pgsqlite.SQLITE_MASTER_VIEW % {"s": stage})
    cat = pgsqlite._load_catalog(pg, stage)
    pg.execute("CREATE TABLE IF NOT EXISTS web_import_notes(id bigint NOT NULL DEFAULT bcfn.next_id('web_import_notes', 'id') "
               "PRIMARY KEY, ts text, source_file text, tbl text, row_id text, col text, original text, note text)")
    notes = []
    # 2. rows
    for name, _sql in tables:
        tb = cat.get(name) or cat.get(name.lower())
        if tb is None:
            continue
        scols = [r[1].decode() if isinstance(r[1], bytes) else r[1]
                 for r in sq.execute('PRAGMA table_info("%s")' % name.replace('"', '""'))]
        cols = [c for c in scols if c.lower() in [x.lower() for x in tb.cols]]
        pgcols = {x.lower(): x for x in tb.cols}
        types = [tb.types[pgcols[c.lower()]] for c in cols]
        n = 0
        has_rowid = True
        try:
            sq.execute('SELECT rowid FROM "%s" LIMIT 1' % name.replace('"', '""'))
        except Exception:
            has_rowid = False
        sel = 'SELECT %s%s FROM "%s"' % ("rowid, " if has_rowid else "", ", ".join('"%s"' % c.replace('"', '""') for c in cols),
                                         name.replace('"', '""'))
        qcols = ", ".join('"%s"' % pgcols[c.lower()] for c in cols)
        cur = pg.cursor()
        with cur.copy('COPY "%s" (%s) FROM STDIN' % (tb.name, qcols)) as cp:
            for row in sq.execute(sel):
                rid = row[0] if has_rowid else None
                vals = row[1:] if has_rowid else row
                out = []
                for c, t, v in zip(cols, types, vals):
                    if isinstance(v, bytes) and t != "bytea":
                        try:
                            v = v.decode("utf-8")
                        except UnicodeDecodeError:
                            v = v.decode("latin-1")
                    nv, ok = _coerce(v, t)
                    if not ok:
                        notes.append((name, str(rid), c, v if isinstance(v, str) else repr(v)))
                    out.append(nv)
                cp.write_row(out)
                n += 1
        report["tables"][name] = n
        report["rows"] += n
        say("%s: %d rows" % (name, n))
    if notes:
        ts = datetime.now().isoformat(timespec="seconds")
        cur = pg.cursor()
        with cur.copy("COPY web_import_notes (ts, source_file, tbl, row_id, col, original, note) FROM STDIN") as cp:
            for t, rid, c, v in notes:
                cp.write_row([ts, os.path.basename(path), t, rid, c, v,
                              "Value kept here: the web database stores this column as a number"])
    report["notes"] = len(notes)
    report["note_samples"] = [{"table": t, "row": r, "column": c, "value": v[:80]} for t, r, c, v in notes[:20]]
    # 3. indexes from the file (unique ones matter for the engine's INSERT OR REPLACE)
    for name, t, sql in master:
        if t != "index":
            continue
        try:
            plan = pgsqlite._make_plan(sql)
            ddl = re.sub(r"(?i)^CREATE\s+(UNIQUE\s+)?INDEX\s+(IF\s+NOT\s+EXISTS\s+)?", lambda m: "CREATE %sINDEX IF NOT EXISTS " %
                         (m.group(1) or ""), plan.sql)
            pg.execute(ddl)
        except Exception as e:
            report.setdefault("index_warnings", []).append("%s: %s" % (name, str(e).split("\n")[0][:160]))
    sq.close()
    pg.close()
    pgsqlite._CAT.clear()
    # 4. the engine's own start-up on the copied data (adds what newer versions need, as on the desktop)
    if run_startup:
        say("Preparing the data for this version of BuildCore")
        _startup_on(stage)
    # 5. swap in
    swap(target_schema, stage)
    report["seconds"] = round(time.time() - t0, 1)
    return report


def _stage_path(schema):
    root = os.environ.get("BCO_DATA_DIR") or "/tmp/buildcore"
    sub = schema[len(pgsqlite.SCHEMA_PREFIX) + 1:] if schema.startswith(pgsqlite.SCHEMA_PREFIX + "_") else schema
    return os.path.join(root, sub, "data", "buildcore.db")


def _startup_on(schema):
    import core
    path = _stage_path(schema)
    if pgsqlite.schema_for_path(path) != schema:
        raise ValueError("internal: staging schema %s does not map back (%s)" % (schema, pgsqlite.schema_for_path(path)))
    keep = (core.DATA_DIR, core.BACKUP_DIR, core.DB_PATH)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        core.DATA_DIR, core.DB_PATH = os.path.dirname(path), path
        core.init_db()
    finally:
        core.DATA_DIR, core.BACKUP_DIR, core.DB_PATH = keep


def swap(target, stage):
    """stage becomes target; the old target is kept as <target>__before_<time> (two newest kept)"""
    pg = pgsqlite._raw_connect()
    try:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        old = "%s__before_%s" % (target, stamp)
        pg.execute("BEGIN")
        if pg.execute("SELECT 1 FROM pg_namespace WHERE nspname=%s", (target,)).fetchone():
            pg.execute('ALTER SCHEMA "%s" RENAME TO "%s"' % (target, old))
        pg.execute('ALTER SCHEMA "%s" RENAME TO "%s"' % (stage, target))
        # the web layer's own store (licence state, company list, job results) belongs to this deployment,
        # not to the company's data: it moves across to the restored schema
        if pg.execute("SELECT 1 FROM pg_tables WHERE schemaname=%s AND tablename='web_kv'", (old,)).fetchone():
            pg.execute('DROP TABLE IF EXISTS "%s".web_kv' % target)
            pg.execute('ALTER TABLE "%s".web_kv SET SCHEMA "%s"' % (old, target))
        pg.execute(pgsqlite.SQLITE_MASTER_VIEW % {"s": target})
        if pg.execute("SELECT 1 FROM pg_namespace WHERE nspname=%s", (old,)).fetchone():
            pg.execute(pgsqlite.SQLITE_MASTER_VIEW % {"s": old})
        for role in ("anon", "authenticated"):
            if pg.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (role,)).fetchone():
                pg.execute('REVOKE ALL ON SCHEMA "%s" FROM %s' % (target, role))
        pg.execute("COMMIT")
        olds = [r[0] for r in pg.execute("SELECT nspname FROM pg_namespace WHERE nspname LIKE %s ORDER BY nspname DESC",
                                          (target.replace("_", r"\_") + r"\_\_before\_%",)).fetchall()]
        for o in olds[2:]:
            pg.execute('DROP SCHEMA "%s" CASCADE' % o)
    finally:
        pg.close()
    pgsqlite._CAT.clear()
    pgsqlite._PLANS.clear()


# ───────────────────────── export ─────────────────────────
_SKIP_EXPORT = {"web_kv", "sqlite_master"}


def export_sqlite(schema, out_path):
    """Write the company's data as a BuildCore desktop data file (opens in BuildCore desktop)."""
    t0 = time.time()
    sq = _real().connect(out_path)
    pg = pgsqlite._raw_connect()
    pg.execute('SET search_path TO "%s", bcfn, public' % schema)
    cat = pgsqlite._load_catalog(pg, schema)
    kinds = dict(pg.execute("SELECT c.relname, c.relkind::text FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                            "WHERE n.nspname=%s", (schema,)).fetchall())
    report = {"tables": {}, "rows": 0}
    sq.execute("PRAGMA journal_mode=DELETE")
    for name, tb in sorted(cat.items()):
        if name in _SKIP_EXPORT or kinds.get(name) not in ("r", "p"):
            continue
        defs = []
        for col in tb.cols:
            typ = tb.types[col]
            st = {"numeric": "INTEGER", "double precision": "REAL", "text": "TEXT", "bytea": "BLOB",
                  "bigint": "INTEGER", "integer": "INTEGER"}.get(typ, "TEXT")
            d = '"%s" %s' % (col, st)
            if tb.pk == [col] and tb.identity == col:
                d = '"%s" INTEGER PRIMARY KEY' % col
            elif tb.notnull.get(col) and col not in tb.pk:
                d += " NOT NULL"
            dflt = tb.defaults.get(col)
            if dflt and "next_id" not in dflt:
                m = re.match(r"^'(.*)'::\w+$", dflt) or re.match(r"^\(?(-?[0-9.]+)\)?(::\w+)?$", dflt)
                if m:
                    v = m.group(1)
                    d += " DEFAULT " + (v if re.match(r"^-?[0-9.]+$", v) else "'%s'" % v.replace("'", "''"))
            defs.append(d)
        if tb.pk and not (tb.pk == [tb.identity]):
            defs.append("PRIMARY KEY(%s)" % ", ".join('"%s"' % x for x in tb.pk))
        for u in tb.uniques:
            defs.append("UNIQUE(%s)" % ", ".join('"%s"' % x for x in u))
        sq.execute('CREATE TABLE "%s"(%s)' % (name, ", ".join(defs)))
        cols = tb.cols
        cur = pg.cursor()
        cur.execute('SELECT %s FROM "%s"' % (", ".join('"%s"' % c for c in cols), name))
        n = 0
        ins = 'INSERT INTO "%s"(%s) VALUES(%s)' % (name, ", ".join('"%s"' % c for c in cols), ",".join("?" * len(cols)))
        while True:
            rows = cur.fetchmany(2000)
            if not rows:
                break
            sq.executemany(ins, [tuple(_out(v) for v in r) for r in rows])
            n += len(rows)
        report["tables"][name] = n
        report["rows"] += n
    # ordinary indexes
    for (idef,) in pg.execute("SELECT indexdef FROM pg_indexes WHERE schemaname=%s", (schema,)).fetchall():
        m = re.match(r'CREATE (UNIQUE )?INDEX (\w+) ON [\w"]+\.("?\w+"?) USING btree \(([^()]+)\)$', idef)
        if not m or m.group(2).endswith("_pkey") or m.group(2).endswith("_key"):
            continue
        try:
            sq.execute("CREATE %sINDEX IF NOT EXISTS %s ON %s(%s)" % (m.group(1) or "", m.group(2), m.group(3), m.group(4)))
        except Exception:
            pass
    sq.commit()
    sq.close()
    pg.close()
    report["seconds"] = round(time.time() - t0, 1)
    return report


def _out(v):
    if isinstance(v, memoryview):
        return bytes(v)
    return v
