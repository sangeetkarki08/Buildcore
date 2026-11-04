"""BuildCore web edition - the engine's database module, on PostgreSQL (Supabase).

The BuildCore engine was written for SQLite through Python's sqlite3 module. In the web edition this
module is installed as `sqlite3` before the engine loads, so every engine file runs unchanged and keeps
its own SQL. It translates the SQLite dialect to PostgreSQL as each statement runs:

  * placeholders ?  ->  values bound on this side as SQL literals (SQLite-like loose typing)
  * INSERT OR IGNORE / OR REPLACE, IS ?, IN (), LIKE, MAX(a,b) / MIN(a,b), date('now'), rowid, ==
  * CREATE TABLE / ALTER TABLE column types (INTEGER -> numeric that comes back as int, REAL -> double),
    INTEGER PRIMARY KEY -> identity, foreign keys left out (SQLite ran with foreign_keys=OFF)
  * PRAGMA table_info / database_list, sqlite_master (a view per schema), the voucher protection triggers
  * transactions: implicit BEGIN before writes as sqlite3 does, BEGIN IMMEDIATE takes a per-company lock
    (the desktop engine's single writer), and each write runs in a savepoint so a failed statement
    leaves the rest of the transaction intact, as in SQLite
  * speed: SQLite is a file on the same computer, so the engine asks many small questions. Here each one is a trip
    over the network, so within one request the same question is asked once, questions about the tables are answered
    from a list kept in memory, and item-by-item questions on a BOQ are asked once for the whole project. The answers
    are the same; BCO_PG_FAST=0 turns all of this off.

One company = one PostgreSQL schema. The engine still names a data file per company; the file path is
mapped to the schema: <root>/data/buildcore.db -> "buildcore", <root>/<dir>/data/buildcore.db ->
"buildcore_<dir>".
"""
import datetime as _dt
import os
import re
import threading
import time
import weakref
from decimal import Decimal

import psycopg
from psycopg import ClientCursor, errors as pgerr
from psycopg.adapt import Dumper, Loader

# ───────────────────────── module surface (as sqlite3) ─────────────────────────
sqlite_version = "3.45.0"
sqlite_version_info = (3, 45, 0)
version = "2.6.0"
PARSE_DECLTYPES = 1
PARSE_COLNAMES = 2
Binary = bytes
apilevel = "2.0"
threadsafety = 1
paramstyle = "qmark"


class Warning(Exception):  # noqa: A001
    pass


class Error(Exception):
    pass


class InterfaceError(Error):
    pass


class DatabaseError(Error):
    pass


class DataError(DatabaseError):
    pass


class OperationalError(DatabaseError):
    pass


class IntegrityError(DatabaseError):
    pass


class InternalError(DatabaseError):
    pass


class ProgrammingError(DatabaseError):
    pass


class NotSupportedError(DatabaseError):
    pass


def register_adapter(*a, **k):
    pass


def register_converter(*a, **k):
    pass


def complete_statement(sql):
    return sql.strip().endswith(";")


DATABASE_URL = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL") or ""
SCHEMA_PREFIX = "buildcore"
FN_SCHEMA = "bcfn"


def schema_for_path(path):
    """Data file path the engine uses -> PostgreSQL schema name."""
    p = str(path or "")
    if p.startswith("file:"):
        p = p[5:].split("?", 1)[0]
    p = p.replace("\\", "/").rstrip("/")
    root = (os.environ.get("BCO_DATA_DIR") or "").replace("\\", "/").rstrip("/")
    if root and p.startswith(root + "/"):
        rel = p[len(root) + 1:]
    else:
        rel = p
    parts = [x for x in rel.split("/") if x]
    # <dir>/data/buildcore.db  or  data/buildcore.db
    if len(parts) >= 3 and parts[-2] == "data":
        d = re.sub(r"[^a-z0-9_]", "_", parts[-3].lower())
        return "%s_%s" % (SCHEMA_PREFIX, d)
    return SCHEMA_PREFIX


# ───────────────────────── value adapters ─────────────────────────
class _QIntDumper(Dumper):
    """ints are sent as untyped literals ('5'), so they compare with text and numeric columns alike,
    the way SQLite compares loosely typed values."""
    oid = 0

    def dump(self, obj):
        return str(int(obj)).encode()

    def quote(self, obj):
        return b"'" + str(int(obj)).encode() + b"'"


class _QBoolDumper(Dumper):
    oid = 0

    def dump(self, obj):
        return b"1" if obj else b"0"

    def quote(self, obj):
        return b"'1'" if obj else b"'0'"


class _QFloatDumper(Dumper):
    oid = 0

    def dump(self, obj):
        return repr(float(obj)).encode()

    def quote(self, obj):
        f = float(obj)
        if f != f or f in (float("inf"), float("-inf")):
            return b"NULL"
        s = repr(f)
        if "e" in s or "E" in s:
            s = format(Decimal(s), "f")
        return s.encode() if not s.startswith("-") else b"(" + s.encode() + b")"


class _QDateDumper(Dumper):
    oid = 0

    def dump(self, obj):
        return obj.isoformat().encode()

    def quote(self, obj):
        return b"'" + obj.isoformat().encode() + b"'"


class _QDateTimeDumper(Dumper):
    oid = 0

    def dump(self, obj):
        return obj.isoformat(" ").encode()

    def quote(self, obj):
        return b"'" + obj.isoformat(" ").encode() + b"'"


class _NumericLoader(Loader):
    """numeric -> int when it is whole, float otherwise (SQLite returns int for INTEGER values)."""

    def load(self, data):
        s = bytes(data)
        if b"." not in s and b"e" not in s and b"E" not in s and b"N" not in s:
            return int(s)
        d = Decimal(s.decode())
        if d.is_nan():
            return None
        if d == d.to_integral_value() and abs(d) < 10 ** 15 and b"." in s and s.rstrip(b"0").endswith(b"."):
            return int(d)
        return float(d)


class _IntLoader(Loader):
    def load(self, data):
        return int(bytes(data))


def _adapt(conn):
    a = conn.adapters
    a.register_dumper(int, _QIntDumper)
    a.register_dumper(bool, _QBoolDumper)
    a.register_dumper(float, _QFloatDumper)
    a.register_dumper(_dt.date, _QDateDumper)
    a.register_dumper(_dt.datetime, _QDateTimeDumper)
    a.register_loader("numeric", _NumericLoader)
    for t in ("int2", "int4", "int8"):
        a.register_loader(t, _IntLoader)
    # dates/times stored by PostgreSQL itself come back as ISO text, like SQLite text dates
    for t in ("date", "timestamp", "timestamptz", "time", "json", "jsonb"):
        a.register_loader(t, psycopg.types.string.TextLoader)


# ───────────────────────── tokenizer ─────────────────────────
_TOK = re.compile(r"""
    (?P<ws>\s+)
  | (?P<lc>--[^\n]*)
  | (?P<bc>/\*.*?\*/)
  | (?P<str>'(?:[^']|'')*')
  | (?P<qid>"(?:[^"]|"")*")
  | (?P<bid>`[^`]*`|\[[A-Za-z_][^\]]*\])
  | (?P<num>(?:\d+\.\d*|\.\d+|\d+)(?:[eE][+-]?\d+)?)
  | (?P<word>[A-Za-z_][A-Za-z_0-9$]*)
  | (?P<param>\?\d*|:[A-Za-z_][A-Za-z_0-9]*)
  | (?P<op><=|>=|<>|!=|==|\|\||<<|>>|::)
  | (?P<p>.)
""", re.S | re.X)


class T:
    __slots__ = ("k", "v", "u")

    def __init__(self, k, v):
        self.k = k
        self.v = v
        self.u = v.upper() if k == "word" else v

    def __repr__(self):
        return "%s:%s" % (self.k, self.v)


def tokenize(sql):
    out = []
    for m in _TOK.finditer(sql):
        k = m.lastgroup
        if k in ("ws", "lc", "bc"):
            if out and out[-1].k != "ws":
                out.append(T("ws", " "))
            continue
        v = m.group(k)
        if k == "bid":
            v = '"' + v[1:-1] + '"'
            k = "qid"
        out.append(T(k, v))
    while out and out[-1].k == "ws":
        out.pop()
    while out and out[0].k == "ws":
        out.pop(0)
    return out


def split_statements(sql):
    """Split a script into statements (trigger bodies BEGIN ... END kept together)."""
    toks = tokenize(sql)
    stmts, cur, depth = [], [], 0
    is_trigger = False
    for i, t in enumerate(toks):
        if t.k == "word":
            if t.u == "TRIGGER" and len([x for x in cur if x.k != "ws"]) <= 4:
                is_trigger = True
            if is_trigger and t.u == "BEGIN":
                depth += 1
            elif is_trigger and t.u == "END" and depth:
                depth -= 1
        if t.k == "p" and t.v == ";" and depth == 0:
            if any(x.k != "ws" for x in cur):
                stmts.append(join(cur))
            cur, is_trigger = [], False
            continue
        cur.append(t)
    if any(x.k != "ws" for x in cur):
        stmts.append(join(cur))
    return stmts


def join(toks):
    return "".join(t.v for t in toks).strip()


def _sig(toks):
    """indices of non-whitespace tokens"""
    return [i for i, t in enumerate(toks) if t.k != "ws"]


def _match_paren(toks, i):
    """toks[i] is '(' -> index of the matching ')'"""
    d = 0
    for j in range(i, len(toks)):
        t = toks[j]
        if t.k == "p" and t.v == "(":
            d += 1
        elif t.k == "p" and t.v == ")":
            d -= 1
            if d == 0:
                return j
    return len(toks) - 1


def _split_args(toks):
    """top-level comma split of a token list"""
    parts, cur, d = [], [], 0
    for t in toks:
        if t.k == "p" and t.v == "(":
            d += 1
        elif t.k == "p" and t.v == ")":
            d -= 1
        if t.k == "p" and t.v == "," and d == 0:
            parts.append(cur)
            cur = []
            continue
        cur.append(t)
    parts.append(cur)
    return parts


# ───────────────────────── type mapping ─────────────────────────
def pg_type(decl):
    d = (decl or "").upper()
    if "INT" in d:
        return "numeric"
    if any(x in d for x in ("CHAR", "CLOB", "TEXT")):
        return "text"
    if "BLOB" in d:
        return "bytea"
    if any(x in d for x in ("REAL", "FLOA", "DOUB")):
        return "double precision"
    if not d.strip():
        return "text"
    if any(x in d for x in ("DATE", "TIME", "JSON")):
        return "text"
    return "numeric"


_COLCON = {"PRIMARY", "NOT", "NULL", "DEFAULT", "UNIQUE", "CHECK", "REFERENCES", "COLLATE", "CONSTRAINT",
           "GENERATED", "AS", "AUTOINCREMENT", "ON"}
_NOW_TEXT = "to_char(now() AT TIME ZONE 'utc', 'YYYY-MM-DD HH24:MI:SS')"


def _strip_references(toks):
    """drop REFERENCES t(c) [ON DELETE|UPDATE ...] [DEFERRABLE ...] from a column definition"""
    out, i = [], 0
    while i < len(toks):
        t = toks[i]
        if t.k == "word" and t.u == "REFERENCES":
            i += 1
            while i < len(toks) and toks[i].k == "ws":
                i += 1
            i += 1  # table
            while i < len(toks) and toks[i].k == "ws":
                i += 1
            if i < len(toks) and toks[i].v == "(":
                i = _match_paren(toks, i) + 1
            while True:
                j = i
                while j < len(toks) and toks[j].k == "ws":
                    j += 1
                if j < len(toks) and toks[j].k == "word" and toks[j].u == "ON":
                    k = j + 1
                    words = 0
                    while k < len(toks) and words < 3:
                        if toks[k].k == "word":
                            words += 1
                            if words >= 2 and toks[k].u in ("CASCADE", "RESTRICT"):
                                k += 1
                                break
                            if words == 3:
                                k += 1
                                break
                        k += 1
                    i = k
                    continue
                if j < len(toks) and toks[j].k == "word" and toks[j].u in ("DEFERRABLE", "NOT", "INITIALLY", "MATCH"):
                    if toks[j].u == "NOT":
                        nxt = [x for x in toks[j + 1:j + 4] if x.k == "word"]
                        if not nxt or nxt[0].u != "DEFERRABLE":
                            break
                    i = j + 1
                    while i < len(toks) and toks[i].k == "ws":
                        i += 1
                    if i < len(toks) and toks[i].k == "word" and toks[i].u in ("DEFERRED", "IMMEDIATE", "DEFERRABLE",
                                                                              "FULL", "SIMPLE", "PARTIAL"):
                        i += 1
                    continue
                break
            continue
        out.append(t)
        i += 1
    return out


def _strip_on_conflict_clause(toks):
    out, i = [], 0
    while i < len(toks):
        t = toks[i]
        if t.k == "word" and t.u == "ON":
            s = [j for j in range(i + 1, min(i + 6, len(toks))) if toks[j].k != "ws"]
            if len(s) >= 2 and toks[s[0]].u == "CONFLICT" and toks[s[1]].k == "word":
                i = s[1] + 1
                continue
        out.append(t)
        i += 1
    return out


def translate_create_table(toks):
    """CREATE TABLE ... ( defs ) -> PostgreSQL"""
    s = _sig(toks)
    # find '(' after table name, unless CREATE TABLE ... AS SELECT
    op = None
    for i in s:
        if toks[i].k == "word" and toks[i].u == "AS":
            return xlate_expr(toks)
        if toks[i].v == "(":
            op = i
            break
    if op is None:
        return join(toks)
    cl = _match_paren(toks, op)
    head = join(toks[:op])
    tail = join(toks[cl + 1:])
    tail = re.sub(r"(?i)\bWITHOUT\s+ROWID\b", "", tail).replace(",", "").strip()
    tail = re.sub(r"(?i)\bSTRICT\b", "", tail).strip()
    defs = _split_args(toks[op + 1:cl])
    outdefs = []
    for d in defs:
        d = [t for t in d]
        while d and d[0].k == "ws":
            d.pop(0)
        if not d:
            continue
        first = d[0].u if d[0].k == "word" else ""
        if first in ("PRIMARY", "UNIQUE", "CHECK", "CONSTRAINT"):
            d = _strip_on_conflict_clause(d)
            outdefs.append(xlate_expr(d))
            continue
        if first == "FOREIGN":
            continue
        outdefs.append(_coldef(d, table=_table_name(head)))
    return "%s(%s)%s" % (head, ", ".join(outdefs), (" " + tail) if tail else "")


def _table_name(head):
    m = re.search(r'([\w"]+)\s*$', head)
    return m.group(1).strip('"') if m else ""


def _coldef(d, table=""):
    """one column definition"""
    d = _strip_references(d)
    d = _strip_on_conflict_clause(d)
    s = [i for i, t in enumerate(d) if t.k != "ws"]
    name = d[s[0]].v
    if d[s[0]].k == "word" and d[s[0]].u in QUOTE_WORDS:
        name = '"%s"' % name.lower()
    j = 1
    typ = []
    while j < len(s):
        t = d[s[j]]
        if t.k == "word" and t.u in _COLCON:
            break
        if t.v == "(":  # VARCHAR(20), DECIMAL(10,2)
            e = _match_paren(d, s[j])
            typ.append(join(d[s[j]:e + 1]))
            j = next((k for k, idx in enumerate(s) if idx > e), len(s))
            continue
        typ.append(t.v)
        j += 1
    decl = " ".join(typ)
    rest = d[s[j]:] if j < len(s) else []
    rest_s = " ".join(t.v for t in rest if t.k != "ws").upper()
    is_pk = "PRIMARY KEY" in rest_s
    if is_pk and "INT" in decl.upper() and decl.upper().strip() in ("INTEGER", "INT", "BIGINT"):
        # INTEGER PRIMARY KEY = rowid alias in SQLite: the next id is the highest + 1, as in SQLite
        rest2 = [t for t in rest if not (t.k == "word" and t.u in ("AUTOINCREMENT", "ASC", "DESC"))]
        return "%s bigint NOT NULL DEFAULT bcfn.next_id('%s', '%s') %s" % (name, table, name.strip('"'), xlate_expr(rest2))
    rest = [t for t in rest if not (t.k == "word" and t.u in ("AUTOINCREMENT",))]
    # COLLATE NOCASE etc.
    out, i = [], 0
    while i < len(rest):
        t = rest[i]
        if t.k == "word" and t.u == "COLLATE":
            i += 1
            while i < len(rest) and rest[i].k == "ws":
                i += 1
            i += 1
            continue
        out.append(t)
        i += 1
    pt = pg_type(decl)
    body = xlate_expr(out, ddl_default_type=pt)
    return "%s %s %s" % (name, pt, body)


_DEF_NOW = re.compile(r"(?i)DEFAULT\s+(\(\s*)?(CURRENT_TIMESTAMP|CURRENT_DATE|CURRENT_TIME)(\s*\))?")


def _fix_defaults(sql, pt):
    sql = _DEF_NOW.sub(lambda m: "DEFAULT " + {"CURRENT_TIMESTAMP": _NOW_TEXT,
                                                 "CURRENT_DATE": "to_char(current_date, 'YYYY-MM-DD')",
                                                 "CURRENT_TIME": "to_char(now() AT TIME ZONE 'utc', 'HH24:MI:SS')"}[
        m.group(2).upper()], sql)
    if pt in ("numeric", "double precision"):
        sql = re.sub(r"(?i)DEFAULT\s+''", "DEFAULT NULL", sql)
        sql = re.sub(r"(?i)DEFAULT\s+'(-?[0-9.]+)'", r"DEFAULT \1", sql)
    return sql


# ───────────────────────── expression translation ─────────────────────────
_FN_RENAME = {"IFNULL": "COALESCE", "GROUP_CONCAT": "bcfn.group_concat_", "SUBSTR": "bcfn.substr",
              "INSTR": "bcfn.instr", "PRINTF": "format", "JULIANDAY": "bcfn.julianday",
              "STRFTIME": "bcfn.strftime", "DATETIME": "bcfn.datetime", "DATE": "bcfn.date",
              "TOTAL": "bcfn.total", "JSON_EXTRACT": "bcfn.json_extract", "ROUND": "bcfn.round",
              "LENGTH": "bcfn.length", "TYPEOF": "bcfn.typeof", "ABS": "bcfn.abs",
              "UPPER": "bcfn.upper", "LOWER": "bcfn.lower", "TRIM": "bcfn.trim", "LTRIM": "bcfn.ltrim",
              "RTRIM": "bcfn.rtrim", "REPLACE": "bcfn.replace", "UNICODE": "ascii", "CHAR": "chr",
              "LAST_INSERT_ROWID": "lastval", "RANDOM": "bcfn.random"}
_NUMCAST = {"REAL": "double precision", "FLOAT": "double precision", "DOUBLE": "double precision",
            "INTEGER": "bigint", "INT": "bigint", "NUMERIC": "numeric", "TEXT": "text", "BLOB": "bytea"}


# words PostgreSQL reserves that the engine uses as column names
QUOTE_WORDS = {"WINDOW"}
# names PostgreSQL accepts as a column alias only after AS ("SELECT x month" -> "SELECT x AS month")
NEED_AS = {"MONTH", "YEAR", "DAY", "HOUR", "MINUTE", "SECOND", "FILTER", "OVER", "WITHIN", "VARYING", "WITHOUT",
           "CHARACTER", "PRECISION", "ESCAPE"}
_NOT_EXPR_END = {"SELECT", "BY", "AS", "AND", "OR", "NOT", "WHERE", "ON", "FROM", "JOIN", "WHEN", "THEN", "ELSE",
                 "CASE", "IN", "IS", "DISTINCT", "SET", "HAVING", "LIKE", "ILIKE", "BETWEEN", "INTERVAL", "EXTRACT"}


_BOOL_BEFORE = {"WHEN", "WHERE", "AND", "OR", "NOT", "HAVING"}
_BOOL_AFTER = {"THEN", "AND", "OR", "ORDER", "GROUP", "LIMIT", "HAVING", "UNION", "END", "ELSE"}
_KW = {"NULL", "TRUE", "FALSE", "EXISTS", "NOT", "SELECT", "CASE", "CAST", "COALESCE", "DISTINCT", "ALL", "ANY"}


def _truthy_pass(toks):
    """SQLite treats a bare number as true/false (WHERE active, CASE WHEN ok THEN ...); PostgreSQL wants
    a boolean, so a lone column in such a place becomes bcfn.truthy(column)."""
    sig = [i for i, t in enumerate(toks) if t.k != "ws"]
    if not any((toks[i].k == "word" and toks[i].u in _BOOL_BEFORE) for i in sig):
        return toks
    out = list(toks)
    between = set()                  # the AND that closes "x BETWEEN a AND b" is not a condition
    depth, pend = 0, []
    for i in sig:
        t = toks[i]
        if t.v == "(":
            depth += 1
        elif t.v == ")":
            depth -= 1
        elif t.k == "word" and t.u == "BETWEEN":
            pend.append(depth)
        elif t.k == "word" and t.u == "AND" and pend and pend[-1] == depth:
            pend.pop()
            between.add(i)
    for n, i in enumerate(sig):
        t = toks[i]
        if i in between:
            continue
        paren = t.v == "("
        if not ((t.k == "word" and t.u in _BOOL_BEFORE) or paren):
            continue
        if n + 1 >= len(sig):
            continue
        a = sig[n + 1]
        ta = toks[a]
        if not (ta.k == "qid" or (ta.k == "word" and ta.u not in _KW and ta.u not in _BOOL_BEFORE)):
            continue
        end = n + 1
        if n + 3 < len(sig) and toks[sig[n + 2]].v == "." and toks[sig[n + 3]].k in ("word", "qid"):
            end = n + 3
        nxt = toks[sig[end + 1]] if end + 1 < len(sig) else None
        if paren:
            ok_ = nxt is not None and nxt.k == "word" and nxt.u in ("AND", "OR")
        else:
            ok_ = nxt is None or nxt.v == ")" or (nxt.k == "word" and nxt.u in _BOOL_AFTER)
        if ok_:
            ref = "".join(toks[x].v for x in sig[n + 1:end + 1])
            out[a] = T("raw", "bcfn.truthy(%s)" % ref)
            for x in sig[n + 2:end + 1]:
                out[x] = T("raw", "")
    return out


def xlate_expr(toks, ddl_default_type=None):
    """Translate SQLite-only syntax inside any statement."""
    toks = _truthy_pass(toks)
    out = []
    n = len(toks)
    i = 0
    while i < n:
        t = toks[i]
        if t.k == "op" and t.v == "==":
            out.append(T("op", "="))
            i += 1
            continue
        if t.k == "qid":
            out.append(t)
            i += 1
            continue
        if t.k == "word" and t.u in QUOTE_WORDS and not (out and out[-1].k == "word" and out[-1].u == "AS"
                                                         and False):
            out.append(T("qid", '"%s"' % t.v.lower()))
            i += 1
            continue
        if t.k == "word" and t.u in NEED_AS:
            p_ = next((x for x in reversed(out) if x.k != "ws"), None)
            j_ = i + 1
            while j_ < n and toks[j_].k == "ws":
                j_ += 1
            nx_ = toks[j_] if j_ < n else None
            ends_expr = p_ is not None and (p_.v == ")" or p_.k in ("num", "str", "qid", "raw")
                                            or (p_.k == "word" and p_.u not in _NOT_EXPR_END))
            alias_end = nx_ is None or nx_.v in (",", ")") or (nx_.k == "word" and nx_.u in ("FROM", "WHERE", "GROUP",
                                                                                             "ORDER", "UNION", "LIMIT"))
            if ends_expr and alias_end and not (nx_ is not None and nx_.v == "("):
                out.append(T("raw", ' AS "%s"' % t.v.lower()))
                i += 1
                continue
        if t.k == "word":
            u = t.u
            # next significant token
            j = i + 1
            while j < n and toks[j].k == "ws":
                j += 1
            nxt = toks[j] if j < n else None
            if u == "ROWID" or u == "_ROWID_" or u == "OID":
                out.append(T("word", "__rowid__"))
                i += 1
                continue
            if u in ("LIKE",) and not (out and out[-1].k == "word" and out[-1].u == "ILIKE"):
                out.append(T("word", "ILIKE"))
                i += 1
                continue
            if u == "GLOB":
                out.append(T("word", "SIMILAR TO"))
                i += 1
                continue
            if u == "IS" and nxt is not None:
                # IS ? / IS NOT ?   -> IS [NOT] DISTINCT FROM
                k = j
                neg = False
                if nxt.k == "word" and nxt.u == "NOT":
                    neg = True
                    k = j + 1
                    while k < n and toks[k].k == "ws":
                        k += 1
                tk = toks[k] if k < n else None
                if tk is not None and (tk.k in ("param", "num", "str") or (tk.k == "word" and tk.u not in (
                        "NULL", "TRUE", "FALSE", "DISTINCT", "NOT", "UNKNOWN", "DOCUMENT", "JSON", "OF"))
                                       or tk.k == "qid" or tk.v == "("):
                    out.append(T("word", "IS NOT DISTINCT FROM" if not neg else "IS DISTINCT FROM"))
                    i = k
                    continue
            if u in ("IN",) and nxt is not None and nxt.v == "(":
                e = _match_paren(toks, j)
                inner = [x for x in toks[j + 1:e] if x.k != "ws"]
                if not inner:
                    out.append(T("word", "IN (SELECT NULL WHERE FALSE)"))
                    i = e + 1
                    continue
            if u == "CAST" and nxt is not None and nxt.v == "(":
                e = _match_paren(toks, j)
                inner = toks[j + 1:e]
                # find top-level AS
                d, as_i = 0, None
                for q, x in enumerate(inner):
                    if x.v == "(":
                        d += 1
                    elif x.v == ")":
                        d -= 1
                    elif d == 0 and x.k == "word" and x.u == "AS":
                        as_i = q
                if as_i is not None:
                    expr = xlate_expr(inner[:as_i])
                    ty = join(inner[as_i + 1:]).strip().upper()
                    if ty in ("REAL", "FLOAT", "DOUBLE", "NUMERIC", "INTEGER", "INT"):
                        fn = "bcfn.to_real" if ty in ("REAL", "FLOAT", "DOUBLE") else (
                            "bcfn.to_int" if ty in ("INTEGER", "INT") else "bcfn.to_num")
                        out.append(T("raw", "%s(%s)" % (fn, expr)))
                    else:
                        out.append(T("raw", "CAST(%s AS %s)" % (expr, _NUMCAST.get(ty, ty.lower()))))
                    i = e + 1
                    continue
            if u in ("MAX", "MIN") and nxt is not None and nxt.v == "(":
                e = _match_paren(toks, j)
                args = _split_args(toks[j + 1:e])
                if len(args) >= 2:
                    fn = "GREATEST" if u == "MAX" else "LEAST"
                    # SQLite's scalar max/min return NULL when any argument is NULL
                    xa = [xlate_expr(a) for a in args]
                    out.append(T("raw", "(CASE WHEN %s THEN NULL ELSE %s(%s) END)" % (
                        " OR ".join("(%s) IS NULL" % a for a in xa), fn, ", ".join(xa))))
                    i = e + 1
                    continue
            if u in _FN_RENAME and nxt is not None and nxt.v == "(" and not (out and out[-1].v == "."):
                if u == "DATE" and ddl_default_type:
                    pass
                if u == "REPLACE" and _is_statement_start(out):
                    out.append(t)
                    i += 1
                    continue
                e = _match_paren(toks, j)
                args = _split_args(toks[j + 1:e])
                if u == "GROUP_CONCAT":
                    a = [xlate_expr(x) for x in args]
                    dist = a[0].upper().startswith("DISTINCT ")
                    if dist:
                        a0 = a[0][9:]
                        out.append(T("raw", "string_agg(DISTINCT (%s)::text, %s)" % (a0, a[1] if len(a) > 1 else "','")))
                    else:
                        out.append(T("raw", "string_agg((%s)::text, %s)" % (a[0], a[1] if len(a) > 1 else "','")))
                    i = e + 1
                    continue
                inner = xlate_expr(toks[j + 1:e]) if any(x.k != "ws" for x in toks[j + 1:e]) else ""
                out.append(T("raw", "%s(%s)" % (_FN_RENAME[u], inner)))
                i = e + 1
                continue
            if u == "COUNT" and nxt is not None and nxt.v == "(":
                pass
        out.append(t)
        i += 1
    sql = "".join(x.v for x in out)
    if ddl_default_type:
        sql = _fix_defaults(sql, ddl_default_type)
    return sql


def _is_statement_start(out):
    return not any(x.k != "ws" for x in out)


# ───────────────────────── catalog (per schema) ─────────────────────────
_CAT = {}
_CAT_LOCK = threading.RLock()


class Table:
    __slots__ = ("name", "cols", "types", "pk", "uniques", "identity", "notnull", "defaults")

    def __init__(self, name):
        self.name = name
        self.cols = []
        self.types = {}
        self.pk = []
        self.uniques = []
        self.identity = None
        self.notnull = {}
        self.defaults = {}


def _load_catalog(pgc, schema):
    cur = pgc.cursor()
    cur.execute(
        "SELECT c.relname, a.attname, format_type(a.atttypid, a.atttypmod), a.attnotnull, "
        "pg_get_expr(d.adbin, d.adrelid), a.attidentity "
        "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
        "JOIN pg_attribute a ON a.attrelid=c.oid AND a.attnum>0 AND NOT a.attisdropped "
        "LEFT JOIN pg_attrdef d ON d.adrelid=c.oid AND d.adnum=a.attnum "
        "WHERE n.nspname=%s AND c.relkind IN ('r','p','v') ORDER BY c.relname, a.attnum", (schema,))
    tabs = {}
    for rel, col, typ, nn, dflt, ident in cur.fetchall():
        tb = tabs.get(rel)
        if tb is None:
            tb = tabs[rel] = Table(rel)
        tb.cols.append(col)
        tb.types[col] = typ
        tb.notnull[col] = nn
        tb.defaults[col] = dflt
        if ident or (dflt and "next_id(" in dflt):
            tb.identity = col
    cur.execute(
        "SELECT c.relname, i.indisprimary, array(SELECT a.attname FROM unnest(i.indkey) WITH ORDINALITY k(n, o) "
        "JOIN pg_attribute a ON a.attrelid=c.oid AND a.attnum=k.n ORDER BY k.o) "
        "FROM pg_index i JOIN pg_class c ON c.oid=i.indrelid JOIN pg_namespace n ON n.oid=c.relnamespace "
        "WHERE n.nspname=%s AND (i.indisunique OR i.indisprimary) AND i.indpred IS NULL AND i.indexprs IS NULL",
        (schema,))
    for rel, prim, cols in cur.fetchall():
        tb = tabs.get(rel)
        if tb is None:
            continue
        if prim:
            tb.pk = list(cols)
        else:
            tb.uniques.append(list(cols))
    cur.close()
    return tabs


def catalog(conn, refresh=False):
    with _CAT_LOCK:
        cat = _CAT.get(conn.ckey)
        if cat is None or refresh:
            cat = _CAT[conn.ckey] = _load_catalog(conn._pg, conn.schema)
        return cat


def _invalidate(ckey):
    with _CAT_LOCK:
        _CAT.pop(ckey, None)


def forget_names(ckey=None):
    """A schema was replaced outside this module (restore): read its table list again."""
    if ckey is None:
        _NAMES.clear()
    else:
        _NAMES.pop(ckey, None)


def table_info(conn, name):
    cat = catalog(conn)
    tb = cat.get(name) or cat.get(str(name).lower())
    if tb is None:
        cat = catalog(conn, refresh=True)
        tb = cat.get(name) or cat.get(str(name).lower())
    return tb


# ───────────────────────── rows and cursors ─────────────────────────
class Row:
    __slots__ = ("_keys", "_vals", "_idx")

    def __init__(self, cursor, values):
        self._keys = cursor._keys
        self._idx = cursor._kidx
        self._vals = values

    def keys(self):
        return list(self._keys)

    def __getitem__(self, k):
        if isinstance(k, (int, slice)):
            return self._vals[k]
        try:
            return self._vals[self._idx[k]]
        except KeyError:
            try:
                return self._vals[self._idx[k.lower()]]
            except (KeyError, AttributeError):
                raise IndexError("No item with that key")

    def __iter__(self):
        return iter(self._vals)

    def __len__(self):
        return len(self._vals)

    def __eq__(self, other):
        return isinstance(other, Row) and self._keys == other._keys and self._vals == other._vals

    def __hash__(self):
        return hash((tuple(self._keys), tuple(self._vals)))

    def __repr__(self):
        return "<Row %r>" % (dict(zip(self._keys, self._vals)),)


class Cursor:
    def __init__(self, conn):
        self.connection = conn
        self._rows = []
        self._pos = 0
        self.description = None
        self.rowcount = -1
        self.lastrowid = None
        self.arraysize = 1
        self._keys = ()
        self._kidx = {}
        self.row_factory = None

    def _set(self, desc, rows):
        if desc:
            self.description = tuple((d[0], None, None, None, None, None, None) for d in desc)
            self._keys = tuple(d[0] for d in desc)
            self._kidx = {}
            for n, k in enumerate(self._keys):
                self._kidx.setdefault(k, n)
                self._kidx.setdefault(k.lower(), n)
        else:
            self.description = None
            self._keys = ()
            self._kidx = {}
        self._rows = rows or []
        self._pos = 0

    def _wrap(self, r):
        rf = self.row_factory or self.connection.row_factory
        if rf is None:
            return tuple(r)
        if rf is Row:
            return Row(self, tuple(r))
        return rf(self, tuple(r))

    def execute(self, sql, params=()):
        self.connection._exec(self, sql, params)
        return self

    def executemany(self, sql, seq):
        for p in seq:
            self.connection._exec(self, sql, p)
        return self

    def executescript(self, script):
        self.connection.executescript(script)
        return self

    def fetchone(self):
        if self._pos >= len(self._rows):
            return None
        r = self._rows[self._pos]
        self._pos += 1
        return self._wrap(r)

    def fetchall(self):
        rows = self._rows[self._pos:]
        self._pos = len(self._rows)
        return [self._wrap(r) for r in rows]

    def fetchmany(self, size=None):
        size = size or self.arraysize
        rows = self._rows[self._pos:self._pos + size]
        self._pos += len(rows)
        return [self._wrap(r) for r in rows]

    def __iter__(self):
        while True:
            r = self.fetchone()
            if r is None:
                return
            yield r

    def close(self):
        pass

    def setinputsizes(self, *a):
        pass

    def setoutputsize(self, *a):
        pass


# ───────────────────────── connection ─────────────────────────
FAST = os.environ.get("BCO_PG_FAST") != "0"
LAZY = threading.local()      # LAZY.on: this request only reads, so it takes the company lock at its first write, if any
MEMO_MAX = 20000
_NAMES = {}                   # (dsn, schema) -> {table, view or index name: relkind}
_DDL_IFNE = re.compile(r"(?is)^\s*CREATE\s+(?:UNIQUE\s+)?(TABLE|INDEX|VIEW)\s+IF\s+NOT\s+EXISTS\s+\"?(\w+)\"?[\s(]")
_HAS_TABLE = re.compile(r"(?is)^\s*SELECT\s+(COUNT\(\*\)|1|name)\s+FROM\s+sqlite_master\s+WHERE\s+type\s*=\s*'table'\s+AND\s+name\s*=\s*"
                        r"(\?|'(\w+)')\s*$")
_BOQ_ARG = re.compile(r"(\b\w+\.)?\bboq_item_id\s*=\s*%s")
_SEL_HEAD = re.compile(r"(?is)^\s*SELECT\s+(.*?)\s+FROM\s")
_POOL = {}
_POOL_LOCK = threading.Lock()
_SCHEMA_READY = set()
_SP = 0


def _dsn():
    url = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL") or DATABASE_URL
    if not url:
        raise OperationalError("DATABASE_URL is not set. Put your Supabase connection string in the environment.")
    if re.search(r":6543(/|$|\?)", url):
        # Supabase's transaction pooler hands each transaction to a different connection, so the
        # per-connection settings BuildCore relies on (which company's tables, its locks) would be lost
        raise OperationalError("DATABASE_URL points at Supabase's transaction pooler (port 6543). Use the Session "
                               "pooler connection string instead (Supabase > Connect > Session pooler, port 5432).")
    return url


DSN_FOR_PATH = None      # tests: a separate database per data folder


MAX_IDLE = int(os.environ.get("BCO_PG_IDLE") or 2)          # open connections kept per server copy, ready for reuse
IDLE_SECONDS = float(os.environ.get("BCO_PG_IDLE_SECONDS") or 60)


def _too_many(e):
    m = str(e)
    return "EMAXCONN" in m or "max clients" in m or "too many clients" in m or "remaining connection slots" in m \
        or "too many connections" in m


def _drop_idle(dsn=None):
    """close the connections this server copy keeps ready, to give their places back to the database"""
    with _POOL_LOCK:
        keys = [k for k in _POOL if dsn is None or k == dsn]
        gone = [pg for k in keys for pg, _t in _POOL.pop(k, [])]
    for pg in gone:
        try:
            pg.close()
        except Exception:
            pass


def _raw_connect(dsn=None):
    # Supabase's free plan allows 15 connections at the same time through its pooler. When they are all in
    # use (other requests running at that moment), wait a little and try again instead of failing at once.
    last = None
    wait = 0.3
    for attempt in range(10):
        try:
            pg = psycopg.connect(dsn or _dsn(), autocommit=True, cursor_factory=ClientCursor, prepare_threshold=None,
                                 connect_timeout=15)
            _adapt(pg)
            return pg
        except psycopg.OperationalError as e:
            last = e
            if _too_many(e):
                _drop_idle()
                time.sleep(wait)
                wait = min(wait * 1.6, 3.0)
                continue
            if attempt >= 2:
                break
            time.sleep(0.5 * (attempt + 1))
    if last is not None and _too_many(last):
        raise OperationalError("The database is busy: all its connections are in use (Supabase free plan: 15 at a "
                               "time). Wait a moment and try again.")
    raise OperationalError("Cannot reach the database: %s" % last)


def _get_pg(dsn):
    """Reuse open PostgreSQL connections (a serverless copy keeps a few between requests). One pool per server
    copy, shared by its threads: each request thread takes a connection for itself and gives it back."""
    now = time.time()
    while True:
        with _POOL_LOCK:
            lst = _POOL.get(dsn)
            item = lst.pop() if lst else None
        if item is None:
            return _raw_connect(dsn)
        pg, t = item
        if pg.closed or now - t > IDLE_SECONDS:
            try:
                pg.close()
            except Exception:
                pass
            continue
        try:
            if pg.info.transaction_status != psycopg.pq.TransactionStatus.IDLE:
                pg.execute("ROLLBACK")
            return pg
        except Exception:
            try:
                pg.close()
            except Exception:
                pass


def _put_pg(pg, dsn):
    if not pg.closed:
        with _POOL_LOCK:
            lst = _POOL.setdefault(dsn, [])
            if len(lst) < MAX_IDLE:
                lst.append((pg, time.time()))
                return
    try:
        pg.close()
    except Exception:
        pass


_FN_READY = []


def ensure_functions(pg):
    """SQLite functions the engine's SQL uses, created once per database in schema bcfn."""
    if pg.info.dbname in _FN_READY:
        return
    have = pg.execute("SELECT value FROM pg_catalog.pg_namespace n LEFT JOIN LATERAL "
                      "(SELECT obj_description(n.oid, 'pg_namespace') AS value) x ON true "
                      "WHERE nspname='bcfn'").fetchone()
    if have and have[0] == FUNCTIONS_VERSION:
        _FN_READY.append(pg.info.dbname)
        return
    pg.execute("SELECT pg_advisory_lock(778899)")
    try:
        have = pg.execute("SELECT obj_description(oid, 'pg_namespace') FROM pg_namespace WHERE nspname='bcfn'").fetchone()
        if not (have and have[0] == FUNCTIONS_VERSION):
            pg.execute(FUNCTIONS_SQL)
            pg.execute("COMMENT ON SCHEMA bcfn IS '%s'" % FUNCTIONS_VERSION)
    finally:
        pg.execute("SELECT pg_advisory_unlock(778899)")
    _FN_READY.append(pg.info.dbname)


def ensure_schema(pg, schema):
    if (pg.info.dbname, schema) in _SCHEMA_READY:
        return
    pg.execute('CREATE SCHEMA IF NOT EXISTS "%s"' % schema)
    pg.execute(SQLITE_MASTER_VIEW % {"s": schema})
    # keep the company data away from Supabase's public data API
    for role in ("anon", "authenticated"):
        try:
            pg.execute("SAVEPOINT r")
            pg.execute('REVOKE ALL ON SCHEMA "%s" FROM %s' % (schema, role))
            pg.execute("RELEASE SAVEPOINT r")
        except Exception:
            try:
                pg.execute("ROLLBACK TO SAVEPOINT r")
            except Exception:
                pass
    _SCHEMA_READY.add((pg.info.dbname, schema))


def connect(database=":memory:", timeout=5.0, detect_types=0, isolation_level="", check_same_thread=True,
            factory=None, cached_statements=128, uri=False, **kw):
    return Connection(database)


_LOCKS = {"IMMEDIATE", "EXCLUSIVE"}
_SEARCH = weakref.WeakKeyDictionary()      # connection -> schema its search_path points at


def _lock_key(schema):
    import zlib
    return zlib.crc32(("bco:" + schema).encode()) & 0x7FFFFFFF


class Connection:
    def __init__(self, path):
        self.path = str(path)
        self.schema = schema_for_path(path)
        self.row_factory = None
        self.isolation_level = ""
        self.text_factory = str
        self.total_changes = 0
        self._in_tx = False
        self._locked = False
        self._closed = False
        self._memo = {}          # (statement, values) -> (columns, rows): one request asks each question once
        self._pf_seen = {}
        self._pf_done = set()
        self._boq_ids = {}
        self._dsn = DSN_FOR_PATH(self.path) if DSN_FOR_PATH else _dsn()
        self.ckey = (self._dsn, self.schema)
        self._pg = _get_pg(self._dsn)
        ensure_functions(self._pg)
        ensure_schema(self._pg, self.schema)
        try:
            if _SEARCH.get(self._pg) != self.schema:
                self._pg.execute('SET search_path TO "%s", bcfn, public' % self.schema)
                _SEARCH[self._pg] = self.schema
        except psycopg.Error:      # a connection kept from an earlier request went stale
            _SEARCH.pop(self._pg, None)
            try:
                self._pg.close()
            except Exception:
                pass
            self._pg = _raw_connect(self._dsn)
            self._pg.execute('SET search_path TO "%s", bcfn, public' % self.schema)
            _SEARCH[self._pg] = self.schema

    # sqlite3 API
    @property
    def in_transaction(self):
        return self._in_tx

    def cursor(self, factory=None):
        return Cursor(self)

    def execute(self, sql, params=()):
        cur = Cursor(self)
        self._exec(cur, sql, params)
        return cur

    def executemany(self, sql, seq):
        cur = Cursor(self)
        for p in seq:
            self._exec(cur, sql, p)
        return cur

    def executescript(self, script):
        if self._in_tx:
            self.commit()
        for st in split_statements(script):
            self._exec(Cursor(self), st, ())
        if self._in_tx:
            self.commit()
        return Cursor(self)

    def commit(self):
        self._forget()
        if self._in_tx:
            try:
                self._pg.execute("COMMIT")
            except psycopg.Error as e:
                self._in_tx = self._locked = False
                raise _map_error(e, "COMMIT")
        self._in_tx = self._locked = False

    def rollback(self):
        self._forget()
        if self._in_tx:
            try:
                self._pg.execute("ROLLBACK")
            except psycopg.Error:
                pass
        self._in_tx = self._locked = False

    def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            if self._in_tx:
                self._pg.execute("ROLLBACK")
            self._in_tx = False
            _put_pg(self._pg, self._dsn)
        except Exception:
            try:
                self._pg.close()
            except Exception:
                pass

    def __enter__(self):
        return self

    def __exit__(self, et, ev, tb):
        if et is None:
            self.commit()
        else:
            self.rollback()
        return False

    def create_function(self, *a, **k):
        pass

    def create_aggregate(self, *a, **k):
        pass

    def create_collation(self, *a, **k):
        pass

    def set_progress_handler(self, *a, **k):
        pass

    def set_trace_callback(self, *a, **k):
        pass

    def interrupt(self):
        pass

    def backup(self, target, **k):
        raise NotSupportedError("Backups of the web edition are made with Administration > Backup (download).")

    def __del__(self):
        try:
            if not self._closed:
                self.close()
        except Exception:
            pass

    # ── internals ──
    def _begin(self, lock=False):
        if not self._in_tx:
            self._pg.execute("BEGIN")
            self._in_tx = True
        if lock and not self._locked and not self.no_lock:
            self._pg.execute("SELECT pg_advisory_xact_lock(%d)" % _lock_key(self.schema))
            self._locked = True

    def _run(self, sql, params, guard):
        """execute on PostgreSQL; inside a transaction a failing statement is rolled back alone."""
        global _SP
        cur = self._pg.cursor()
        if guard and self._in_tx:
            _SP += 1
            sp = "bsp%d" % _SP
            self._pg.execute("SAVEPOINT " + sp)
            try:
                cur.execute(sql, params)
            except psycopg.Error as e:
                try:
                    self._pg.execute("ROLLBACK TO SAVEPOINT " + sp)
                    self._pg.execute("RELEASE SAVEPOINT " + sp)
                except psycopg.Error:
                    pass
                raise _map_error(e, sql)
            self._pg.execute("RELEASE SAVEPOINT " + sp)
            return cur
        try:
            cur.execute(sql, params)
        except psycopg.Error as e:
            if self._in_tx:
                # a read failed inside the transaction: PostgreSQL has aborted it. Nothing was written in
                # a savepoint-less read, so the transaction is restarted only when nothing was written.
                if not self._dirty:
                    try:
                        self._pg.execute("ROLLBACK")
                    except psycopg.Error:
                        pass
                    self._in_tx = False
                    relock = self._locked
                    self._locked = False
                    self._begin(lock=relock)
                else:
                    self._poisoned = True
            raise _map_error(e, sql)
        return cur

    def _forget(self):
        self._memo.clear()
        self._pf_done.clear()

    def _names(self):
        n = _NAMES.get(self.ckey)
        if n is None:
            rows = self._pg.execute("SELECT c.relname, c.relkind FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                                    "WHERE n.nspname=%s AND c.relkind IN ('r','p','v','i')", (self.schema,)).fetchall()
            n = _NAMES[self.ckey] = {r[0]: str(r[1]) for r in rows}
        return n

    def _quick(self, cur, sql, params):
        """Questions about the tables, answered without a trip to the database. True when answered."""
        m = _DDL_IFNE.match(sql)
        if m:
            if m.group(2).lower() in self._names():
                cur._set(None, [])
                return True
            return False
        m = _HAS_TABLE.match(sql) if "sqlite_master" in sql else None
        if m:
            name = m.group(3) or (params[0] if params else None)
            if str(name).lower() in {k for k, v in self._names().items() if v in ("r", "p") and k == str(name).lower()}:
                what = m.group(1).upper()
                cur._set([("name" if what == "NAME" else "count",)], [(name if what == "NAME" else 1,)])
                return True
        return False

    def _ids_of_boq(self, one):
        """Every BOQ item of the project this item belongs to."""
        ids = self._boq_ids.get(one)
        if ids is None:
            rows = self._pg.execute("SELECT id FROM boq_items WHERE project_id=(SELECT project_id FROM boq_items WHERE id=%s)",
                                    (int(one),)).fetchall()
            ids = [int(r[0]) for r in rows]
            for i in ids:
                self._boq_ids[i] = ids
        return ids

    def _prefetch(self, plan, sql2, args):
        """The second time one statement is asked item by item, ask it once for all the project's BOQ items."""
        if plan.recipe or not isinstance(args, list):
            return
        found = list(_BOQ_ARG.finditer(sql2))
        up = sql2.upper()
        first_only = re.search(r"(?i)\s+LIMIT\s+1\s*$", sql2)
        rest = up[:first_only.start()] if first_only else up
        if len(found) != 1 or up.count("SELECT") - up.count("EXISTS (SELECT") != 1 or any(x in rest for x in (" GROUP BY", " HAVING", " LIMIT", " UNION", " DISTINCT")):
            return
        m = found[0]
        at = sql2[:m.start()].count("%s")
        one = args[at]
        if not isinstance(one, int) or isinstance(one, bool):
            return
        group = (sql2, tuple(args[:at]), tuple(args[at + 1:]))
        self._pf_seen[group] = self._pf_seen.get(group, 0) + 1
        if self._pf_seen[group] < 2:
            return
        head = _SEL_HEAD.match(sql2)
        if not head:
            return
        cols = head.group(1).strip()
        total = re.match(r"(?i)^SUM\(", cols) is not None
        if total and " ORDER BY" in up:
            return
        if not total and re.search(r"(?i)\b(SUM|COUNT|MIN|MAX|AVG|TOTAL|STRING_AGG)\(", cols):
            return
        ids = self._ids_of_boq(one)
        if len(ids) < 2 or (group, ids[0]) in self._pf_done:
            return
        self._pf_done.add((group, ids[0]))
        alias = m.group(1) or ""
        body = sql2[:first_only.start()] if first_only else sql2
        new = body[:m.start()] + "%sboq_item_id IN (%s)" % (alias, ",".join(str(i) for i in ids)) + body[m.end():]
        new = new[:head.start(1)] + "%sboq_item_id AS bco_key, " % alias + new[head.start(1):]
        if total:
            new += " GROUP BY 1"
        try:
            res = self._run(new, args[:at] + args[at + 1:], guard=self._in_tx)
        except OperationalError:
            return
        desc = [(d[0],) for d in res.description[1:]]
        got = {}
        for r in res.fetchall():
            if not (first_only and int(r[0]) in got):
                got.setdefault(int(r[0]), []).append(tuple(r[1:]))
        empty = [tuple([None] * len(desc))] if total else []
        for i in ids:
            self._memo[(sql2, tuple(args[:at]) + (i,) + tuple(args[at + 1:]))] = (desc, got.get(i) or empty)

    _dirty = False
    _poisoned = False
    _lastrowid = 0
    no_lock = False      # set by the web layer's own small store, which may write while a request holds the lock

    def _exec(self, cur, sql, params):
        if self._closed:
            raise ProgrammingError("Cannot operate on a closed database.")
        if params is None:
            params = ()
        if "last_insert_rowid" in sql.lower():
            # SQLite's last_insert_rowid(): the id of this connection's last inserted row (ids here come from
            # bcfn.next_id, not a sequence, so PostgreSQL's lastval() does not know them)
            sql = _LAST_ROWID.sub(str(int(self._lastrowid or 0)), sql)
        if FAST and self._quick(cur, sql, params):
            return
        plan = _plan(sql)
        kind = plan.kind
        if kind == "noop":
            cur._set(None, [])
            return
        if kind == "pragma":
            return self._pragma(cur, plan)
        if kind == "begin":
            if self._in_tx:
                raise OperationalError("cannot start a transaction within a transaction")
            self._begin(lock=plan.lock and not getattr(LAZY, "on", False))
            self._dirty = False
            self._poisoned = False
            cur._set(None, [])
            return
        if kind == "commit":
            self.commit()
            cur._set(None, [])
            return
        if kind == "rollback":
            self.rollback()
            cur._set(None, [])
            return
        if kind == "savepoint":
            self._forget()
            self._begin()
            self._pg.execute(plan.sql)
            cur._set(None, [])
            return
        if self._poisoned and self._in_tx:
            raise OperationalError("An earlier statement failed; the transaction was cancelled.")
        sql2, args = plan.bind(self, params)
        if kind == "ddl":
            self._forget()
            res = self._run(sql2, args, guard=True)
            _invalidate(self.ckey)
            m = _DDL_IFNE.match(sql)
            if m and self.ckey in _NAMES:
                _NAMES[self.ckey][m.group(2).lower()] = {"TABLE": "r", "INDEX": "i", "VIEW": "v"}[m.group(1).upper()]
            elif not re.match(r"(?is)^\s*(CREATE|ALTER\s+TABLE\s+\S+\s+ADD)\b", sql):
                _NAMES.pop(self.ckey, None)
            if plan.after:
                for extra in plan.after(self):
                    self._run(extra, None, guard=True)
            cur._set(None, [])
            cur.rowcount = -1
            return
        if kind == "dml":
            self._forget()
            self._begin(lock=True)
            self._dirty = True
            res = self._run(sql2, args, guard=True)
            rows = None
            if res.description is not None:
                rows = res.fetchall()
            cur.rowcount = res.rowcount
            self.total_changes += max(res.rowcount, 0)
            if plan.returning_id:
                cur.lastrowid = rows[-1][0] if rows else None
                if cur.lastrowid is not None:
                    self._lastrowid = cur.lastrowid
                cur._set(None, [])
            else:
                cur._set(res.description, rows or [])
            return
        # select / other (after a write, reads are guarded too so a failing one leaves the writes intact)
        key = None
        if FAST and sql2.lstrip()[:6].upper() == "SELECT" and "pg_advisory" not in sql2 and "random(" not in sql2.lower():
            try:
                key = (sql2, tuple(args) if isinstance(args, list) else tuple(sorted(args.items())) if args else ())
                hit = self._memo.get(key)
                if hit is None and args and "boq_item_id" in sql2:
                    self._prefetch(plan, sql2, args)
                    hit = self._memo.get(key)
            except TypeError:           # a value that cannot be remembered
                key, hit = None, None
            if hit is not None:
                cur._set(hit[0], hit[1])
                cur.rowcount = -1
                return
        res = self._select(plan, sql2, args)
        if res.description is not None:
            desc, rows = [(d[0],) for d in res.description], res.fetchall()
            cur._set(desc, rows)
            if key is not None and len(self._memo) < MEMO_MAX:
                self._memo[key] = (desc, rows)
        else:
            cur._set(None, [])
        cur.rowcount = res.rowcount if res.description is None else -1

    def _bound(self, sql, args):
        """the statement with its values written in (for rewrites that repeat an expression)"""
        if args is None:
            return sql
        return self._pg.cursor().mogrify(sql, args)

    def _select(self, plan, sql2, args):
        """run a read; SQLite-only forms PostgreSQL refuses are rewritten once and remembered for this statement"""
        if plan.recipe:
            run_sql, run_args = _apply_recipe(self._bound(sql2, args), plan.recipe), None
        else:
            run_sql, run_args = sql2, args
        for attempt in range(10):
            try:
                return self._run(run_sql, run_args, guard=self._dirty)
            except OperationalError as e:
                pe = getattr(e, "pg", None)
                if isinstance(pe, pgerr.UndefinedColumn) and plan.rowid_alt and plan.sql != plan.rowid_alt:
                    plan.sql = sql2 = plan.rowid_alt      # table without an id column: insertion order
                    run_sql = _apply_recipe(self._bound(sql2, args), plan.recipe) if plan.recipe else sql2
                    run_args = None if plan.recipe else args
                    continue
                step = _diagnose(pe)
                if step is None or attempt == 9:
                    raise
                text = run_sql if run_args is None else self._bound(run_sql, run_args)
                fixed = _apply_step(step, text)
                if not fixed:
                    raise
                plan.recipe = (plan.recipe or []) + [step]
                run_sql, run_args = fixed, None

    def _fix_identity(self, table):
        tb = table_info(self, table)
        if tb is None or not tb.identity:
            return
        self._pg.execute(
            "SELECT setval(pg_get_serial_sequence(%s, %s), GREATEST((SELECT COALESCE(MAX(\"%s\"), 0) FROM \"%s\"), 1), "
            "(SELECT COUNT(*) > 0 FROM \"%s\"))" % ("%s", "%s", tb.identity, table, table),
            ('"%s"."%s"' % (self.schema, table), tb.identity))

    def _pragma(self, cur, plan):
        name, arg = plan.pragma
        if name == "table_info":
            tb = table_info(self, arg)
            rows = []
            if tb is not None:
                for n, col in enumerate(tb.cols):
                    typ = tb.types[col]
                    st = {"numeric": "INTEGER", "double precision": "REAL", "text": "TEXT", "bigint": "INTEGER",
                          "bytea": "BLOB"}.get(typ, typ.upper())
                    rows.append((n, col, st, 1 if tb.notnull.get(col) else 0, tb.defaults.get(col),
                                 (tb.pk.index(col) + 1) if col in tb.pk else 0))
            cur._set([("cid",), ("name",), ("type",), ("notnull",), ("dflt_value",), ("pk",)], rows)
            return
        if name == "database_list":
            cur._set([("seq",), ("name",), ("file",)], [(0, "main", self.path)])
            return
        if name == "integrity_check" or name == "quick_check":
            cur._set([("integrity_check",)], [("ok",)])
            return
        if name == "journal_mode":
            cur._set([("journal_mode",)], [("wal",)])
            return
        if name == "index_list":
            r = self._pg.execute(
                "SELECT row_number() OVER () - 1, ci.relname, i.indisunique::int, 'c', 0 FROM pg_index i "
                "JOIN pg_class c ON c.oid=i.indrelid JOIN pg_class ci ON ci.oid=i.indexrelid "
                "JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=%s AND c.relname=%s",
                (self.schema, arg)).fetchall()
            cur._set([("seq",), ("name",), ("unique",), ("origin",), ("partial",)], r)
            return
        if name in ("user_version", "schema_version", "page_count", "page_size", "freelist_count"):
            cur._set([(name,)], [(0,)])
            return
        cur._set(None, [])


ERROR_LOG = os.environ.get("BCO_PG_LOG")


def _map_error(e, sql):
    err = _map_error2(e, sql)
    err.pg = e
    return err


def _map_error2(e, sql):
    msg = str(e).strip().split("\n")[0]
    if ERROR_LOG:
        try:
            import traceback
            with open(ERROR_LOG, "a", encoding="utf-8") as fh:
                fh.write("=== %s: %s\nSQL: %s\nAT: %s\n" % (type(e).__name__, msg, sql,
                         "".join(traceback.format_stack(limit=8)[:-2]).replace("\n", "\n    ")))
        except Exception:
            pass
    if isinstance(e, (pgerr.UniqueViolation,)):
        m = re.search(r"Key \((.*?)\)=", str(e))
        return IntegrityError("UNIQUE constraint failed: %s" % (m.group(1) if m else msg))
    if isinstance(e, (pgerr.NotNullViolation,)):
        return IntegrityError("NOT NULL constraint failed: %s" % msg)
    if isinstance(e, (pgerr.CheckViolation, pgerr.ForeignKeyViolation, pgerr.IntegrityConstraintViolation)):
        return IntegrityError(msg)
    if isinstance(e, pgerr.RaiseException):
        return IntegrityError(msg)
    if isinstance(e, pgerr.DuplicateColumn):
        m = re.search(r'column "(.*?)"', msg)
        return OperationalError("duplicate column name: %s" % (m.group(1) if m else msg))
    if isinstance(e, pgerr.UndefinedTable):
        m = re.search(r'relation "(.*?)"', msg)
        return OperationalError("no such table: %s" % (m.group(1) if m else msg))
    if isinstance(e, pgerr.UndefinedColumn):
        m = re.search(r'column "?(.*?)"? does not exist', msg)
        return OperationalError("no such column: %s" % (m.group(1) if m else msg))
    if isinstance(e, (pgerr.DuplicateTable, pgerr.DuplicateObject)):
        return OperationalError("%s already exists" % msg)
    if isinstance(e, (pgerr.DataError,)):
        err = OperationalError("%s  [SQL: %s]" % (msg, sql[:300]))
        return err
    if isinstance(e, (pgerr.SyntaxError, pgerr.UndefinedFunction, pgerr.GroupingError, pgerr.DatatypeMismatch,
                      pgerr.AmbiguousColumn, pgerr.InvalidColumnReference)):
        return OperationalError("%s  [SQL: %s]" % (msg, sql[:300]))
    return OperationalError(msg)


# ───────────────────────── SQLite's loose GROUP BY ─────────────────────────
_GRP = re.compile(r'column "([^"]+)" must appear in the GROUP BY clause')
_CLAUSE_END = {"FROM", "WHERE", "GROUP", "HAVING", "ORDER", "LIMIT", "UNION", "EXCEPT", "INTERSECT", "WINDOW", "OFFSET"}


def _levels(toks):
    """for each token: paren depth, and the index of the '(' that opens its subquery (-1 = top level)"""
    depths, qids = [], []
    stack = []          # (paren index, is_subquery)
    for i, t in enumerate(toks):
        if t.v == "(":
            j = i + 1
            while j < len(toks) and toks[j].k == "ws":
                j += 1
            sub = j < len(toks) and toks[j].k == "word" and toks[j].u in ("SELECT", "WITH", "VALUES")
            stack.append((i, sub))
        q = next((p for p, sub in reversed(stack) if sub), -1)
        depths.append(len(stack))
        qids.append(q)
        if t.v == ")" and stack:
            stack.pop()
    return depths, qids


_AGG = ("MIN", "MAX", "SUM", "COUNT", "AVG", "TOTAL", "STRING_AGG", "GROUP_CONCAT", "ARRAY_AGG", "BCFN.TOTAL")


def _diagnose(pe):
    if pe is None:
        return None
    if isinstance(pe, pgerr.InvalidColumnReference) and "SELECT DISTINCT" in str(pe):
        return ("distinct", None)
    if isinstance(pe, pgerr.GroupingError):
        m = _GRP.search(str(pe))
        return ("regroup", m.group(1)) if m else None
    if isinstance(pe, pgerr.UndefinedColumn):
        m = _UNDEF.search(str(pe))
        return ("alias", m.group(1)) if m and "." not in m.group(1) else None
    return None


def _apply_step(step, sql):
    kind, arg = step
    if kind == "distinct":
        return _distinct_order(sql)
    if kind == "regroup":
        r = _regroup_ref(sql, arg)
        if r is None and "." in arg:
            r = _regroup_ref(sql, arg.split(".")[-1])
        return r
    if kind == "alias":
        return _alias_name(sql, arg)
    return None


def _apply_recipe(sql, recipe):
    for st in recipe:
        sql = _apply_step(st, sql) or sql
    return sql


def _regroup(sql, pgexc):
    """SQLite lets a grouped query show a column it did not group by (the value of one row of the group).
    PostgreSQL refuses; the column is shown as MIN(column) instead, which is one row's value as well.
    SELECT DISTINCT ... ORDER BY <column not shown> is turned into GROUP BY the shown columns."""
    if pgexc is None:
        return None
    if isinstance(pgexc, pgerr.InvalidColumnReference) and "SELECT DISTINCT" in str(pgexc):
        return _distinct_order(sql)
    if not isinstance(pgexc, pgerr.GroupingError):
        return None
    m = _GRP.search(str(pgexc))
    if not m:
        return None
    ref = m.group(1)
    r = _regroup_ref(sql, ref)
    if r is None and "." in ref:
        r = _regroup_ref(sql, ref.split(".")[-1])
    return r


def _regroup_ref(sql, ref):
    want = [x for x in re.split(r"(\.)", ref) if x]
    toks = tokenize(sql)
    n = len(toks)
    depths, qids = _levels(toks)
    out = list(toks)
    changed = False

    def is_ref(i):
        j, k = i, 0
        while k < len(want):
            if j >= n or out[j] is None:
                return None
            tv = out[j].v.strip('"') if out[j].k in ("word", "qid") else out[j].v
            if tv.lower() != want[k].lower():
                return None
            j += 1
            k += 1
        if i > 0 and out[i - 1].v == ".":
            return None
        if j < n and out[j].v in (".", "("):
            return None
        return j

    def in_aggregate(i):
        q = qids[i]
        lvl = depths[i]
        j = i - 1
        while j >= 0 and j > q:
            if out[j].v == "(" and depths[j] <= lvl:
                f = j - 1
                while f >= 0 and out[f].k == "ws":
                    f -= 1
                if f >= 0 and out[f].k in ("word", "raw") and out[f].v.upper() in _AGG:
                    return True
                lvl = depths[j] - 1
            j -= 1
        return False

    for i in range(n):
        if out[i] is None or out[i].k not in ("word", "qid"):
            continue
        e = is_ref(i)
        if e is None or in_aggregate(i):
            continue
        q = qids[i]
        j, clause = i - 1, None
        while j > q:
            if qids[j] == q and out[j].k == "word" and out[j].u in ("SELECT", "ORDER", "HAVING", "GROUP", "WHERE",
                                                                     "FROM", "ON", "BY", "JOIN"):
                if out[j].u == "BY":
                    pj = j - 1
                    while pj >= 0 and out[pj].k == "ws":
                        pj -= 1
                    clause = out[pj].u if pj >= 0 else None
                else:
                    clause = out[j].u
                break
            j -= 1
        if clause not in ("SELECT", "ORDER", "HAVING"):
            continue
        expr = "".join(x.v for x in out[i:e])
        alias = ""
        if clause == "SELECT" and depths[i] == (depths[q] + 1 if q >= 0 else 0):
            k = e
            while k < n and out[k].k == "ws":
                k += 1
            pk = i - 1
            while pk >= 0 and out[pk].k == "ws":
                pk -= 1
            bare_start = pk >= 0 and (out[pk].v == "," or (out[pk].k == "word" and out[pk].u in ("SELECT", "DISTINCT")))
            if bare_start and (k >= n or out[k].v in (",", ")") or (out[k].k == "word" and out[k].u in _CLAUSE_END)):
                alias = " AS " + want[-1].strip('"')
        out[i] = T("raw", "MIN(%s)%s" % (expr, alias))
        for z in range(i + 1, e):
            out[z] = T("raw", "")
        changed = True
    if not changed:
        return None
    return "".join(t.v for t in out if t is not None)


_UNDEF = re.compile(r'column "?([\w.]+)"? does not exist')


def _alias_name(sql, name):
    """SQLite lets WHERE / HAVING / expressions in ORDER BY use a name given in the select list;
    PostgreSQL does not, so the name is replaced by the expression it stands for."""
    name = name.lower()
    toks = tokenize(sql)
    n = len(toks)
    depths, qids = _levels(toks)
    out = list(toks)
    changed = False
    sels = [i for i in range(n) if toks[i].k == "word" and toks[i].u == "SELECT"]
    for si in sels:
        q = qids[si]
        lvl = depths[si]
        frm = next((i for i in range(si + 1, n) if qids[i] == q and depths[i] == lvl and toks[i].k == "word"
                    and toks[i].u == "FROM"), None)
        if frm is None:
            continue
        expr = None
        for it in _split_args(toks[si + 1:frm]):
            s_ = [x for x in it if x.k != "ws"]
            if s_ and s_[0].k == "word" and s_[0].u == "DISTINCT":
                it = it[it.index(s_[0]) + 1:]
                s_ = s_[1:]
            if len(s_) >= 2 and s_[-1].k in ("word", "qid") and s_[-1].v.strip('"').lower() == name and s_[-2].v != ".":
                body = list(it)
                while body and body[-1].k == "ws":
                    body.pop()
                body.pop()  # alias
                while body and body[-1].k == "ws":
                    body.pop()
                if body and body[-1].k == "word" and body[-1].u == "AS":
                    body.pop()
                expr = "".join(x.v for x in body).strip()
                break
        if not expr:
            continue
        # end of this query level
        end = next((i for i in range(frm, n) if depths[i] < lvl or (qids[i] != q and depths[i] < lvl)), n)
        clause = None
        for i in range(frm, end):
            t = out[i]
            if t is None or qids[i] != q:
                continue
            if depths[i] == lvl and t.k == "word" and t.u in ("WHERE", "HAVING", "ORDER", "GROUP", "FROM", "LIMIT", "ON"):
                clause = t.u
                continue
            if clause in ("WHERE", "HAVING", "ORDER") and t.k in ("word", "qid") and t.v.strip('"').lower() == name:
                pv = i - 1
                while pv >= 0 and toks[pv].k == "ws":
                    pv -= 1
                nx = i + 1
                while nx < n and toks[nx].k == "ws":
                    nx += 1
                if pv >= 0 and toks[pv].v == ".":
                    continue
                if nx < n and toks[nx].v in (".", "("):
                    continue
                if clause == "ORDER" and depths[i] == lvl and (toks[pv].v == "," or (toks[pv].k == "word" and toks[pv].u == "BY")) \
                        and (nx >= n or toks[nx].v == "," or (toks[nx].k == "word" and toks[nx].u in ("ASC", "DESC", "LIMIT", "NULLS"))):
                    continue
                out[i] = T("raw", "(%s)" % expr)
                changed = True
    if not changed:
        return None
    return "".join(t.v for t in out if t is not None)


def _distinct_order(sql):
    toks = tokenize(sql)
    depths, qids = _levels(toks)
    n = len(toks)
    top = [i for i in range(n) if qids[i] == -1 and depths[i] == 0]

    def kw(i, *w):
        return toks[i].k == "word" and toks[i].u in w
    sel = next((i for i in top if kw(i, "SELECT")), None)
    if sel is None:
        return None
    dis = next((i for i in top if i > sel and toks[i].k != "ws"), None)
    if dis is None or not kw(dis, "DISTINCT"):
        return None
    frm = next((i for i in top if i > dis and kw(i, "FROM")), None)
    order = next((i for i in top if i > dis and kw(i, "ORDER")), None)
    if frm is None or order is None or any(kw(i, "GROUP", "UNION", "EXCEPT", "INTERSECT") for i in top if i > dis):
        return None
    by = next(i for i in top if i > order and kw(i, "BY"))
    end = next((i for i in top if i > by and kw(i, "LIMIT", "OFFSET")), n)
    items = []
    for it in _split_args(toks[dis + 1:frm]):
        s_ = [x for x in it if x.k != "ws"]
        # drop an alias
        if len(s_) >= 3 and s_[-2].k == "word" and s_[-2].u == "AS":
            s_ = s_[:-2]
        elif len(s_) >= 2 and s_[-1].k in ("word", "qid") and s_[-2].k not in ("p", "op") and s_[-2].v != ".":
            s_ = s_[:-1]
        items.append(" ".join(x.v for x in s_).replace(" . ", ".").replace(" .", ".").replace(". ", "."))
    norm = [re.sub(r"\s+", "", x).lower() for x in items]
    orders = []
    for it in _split_args(toks[by + 1:end]):
        txt = "".join(x.v for x in it).strip()
        mdir = re.search(r"(?i)\s+(ASC|DESC)(\s+NULLS\s+(FIRST|LAST))?$", txt)
        core_ = txt[:mdir.start()] if mdir else txt
        tail = txt[mdir.start():] if mdir else ""
        if re.sub(r"\s+", "", core_).lower() in norm or re.match(r"^\d+$", core_.strip()):
            orders.append(txt)
        else:
            orders.append("MIN(%s)%s" % (core_, tail))
    head = "".join(t.v for t in toks[:dis]) + " " + "".join(t.v for t in toks[dis + 1:order])
    return "%s GROUP BY %s ORDER BY %s %s" % (head.rstrip(), ", ".join(items), ", ".join(orders),
                                               "".join(t.v for t in toks[end:]))


# ───────────────────────── statement plans (cached translation) ─────────────────────────
class Plan:
    __slots__ = ("kind", "sql", "lock", "pragma", "table", "returning_id", "fix_identity", "after",
                 "nparams", "named", "insert_cols", "replace", "ignore", "dyn", "rowid_alt", "recipe")

    def __init__(self, kind, sql=""):
        self.kind = kind
        self.sql = sql
        self.lock = False
        self.pragma = None
        self.table = None
        self.returning_id = False
        self.fix_identity = False
        self.after = None
        self.nparams = 0
        self.named = None
        self.insert_cols = None
        self.replace = False
        self.ignore = False
        self.dyn = None
        self.rowid_alt = None
        self.recipe = None

    def bind(self, conn, params):
        sql = self.sql
        if self.dyn:
            sql = self.dyn(conn)
        if isinstance(params, dict):
            if not self.named:
                return sql, None
            return sql, {k: _val(params.get(k)) for k in self.named}
        params = list(params or ())
        if self.nparams == 0:
            if params:
                raise ProgrammingError("Incorrect number of bindings supplied. The current statement uses 0, "
                                       "and there are %d supplied." % len(params))
            return sql, None
        if len(params) != self.nparams:
            raise ProgrammingError("Incorrect number of bindings supplied. The current statement uses %d, and "
                                   "there are %d supplied." % (self.nparams, len(params)))
        return sql, [_val(p) for p in params]


def _val(v):
    if isinstance(v, memoryview):
        return bytes(v)
    return v


_PLANS = {}
_LAST_ROWID = re.compile(r"(?i)\blast_insert_rowid\s*\(\s*\)")
_PLAN_LOCK = threading.Lock()


def _plan(sql):
    p = _PLANS.get(sql)
    if p is None:
        p = _make_plan(sql)
        if p.sql and "__rowid__" in p.sql:
            p.rowid_alt = p.sql.replace("__rowid__", "ctid")
            p.sql = p.sql.replace("__rowid__", "id")
        with _PLAN_LOCK:
            if len(_PLANS) > 20000:
                _PLANS.clear()
            _PLANS[sql] = p
    return p


def _params_to_pg(toks):
    """? -> %s, :name -> %(name)s, literal % -> %%; returns (sql, count, names)"""
    n, names = 0, []
    out = []
    for t in toks:
        if t.k == "param":
            if t.v.startswith(":"):
                names.append(t.v[1:])
                out.append("%%(%s)s" % t.v[1:])
            else:
                n += 1
                out.append("%s")
        elif t.k in ("str", "qid", "raw", "p", "op", "word", "num"):
            out.append(t.v.replace("%", "%%"))
        else:
            out.append(t.v)
    return "".join(out), n, names


def _make_plan(sql):
    toks = tokenize(sql)
    s = _sig(toks)
    if not s:
        return Plan("noop")
    first = toks[s[0]].u if toks[s[0]].k == "word" else toks[s[0]].v
    words = [toks[i].u for i in s[:6] if toks[i].k == "word"]
    if first == "PRAGMA":
        m = re.match(r"(?is)\s*PRAGMA\s+(?:\w+\.)?(\w+)\s*(?:\(\s*['\"]?([\w$]+)['\"]?\s*\)|=\s*(\S+))?", sql)
        p = Plan("pragma")
        p.pragma = ((m.group(1) or "").lower(), (m.group(2) or m.group(3) or "")) if m else ("", "")
        return p
    if first in ("BEGIN",):
        p = Plan("begin")
        p.lock = len(words) > 1 and words[1] in _LOCKS
        return p
    if first in ("COMMIT", "END"):
        return Plan("commit")
    if first == "ROLLBACK" and not (len(words) > 1 and words[1] == "TO"):
        return Plan("rollback")
    if first in ("SAVEPOINT", "RELEASE") or (first == "ROLLBACK"):
        return Plan("savepoint", sql)
    if first in ("VACUUM", "ANALYZE", "REINDEX", "ATTACH", "DETACH"):
        return Plan("noop")
    if first in ("CREATE", "DROP", "ALTER"):
        return _plan_ddl(sql, toks, s, words)
    if first in ("INSERT", "REPLACE", "UPDATE", "DELETE"):
        return _plan_dml(sql, toks, s, words, first)
    body = xlate_expr(toks)
    sql2, n, names = _params_to_pg(tokenize(body)) if True else (body, 0, [])
    p = Plan("select", sql2 if (n or names) else body)
    p.nparams, p.named = n, (names or None)
    return p


def _retok(sqltext):
    return tokenize(sqltext)


def _finish(p, text):
    sql2, n, names = _params_to_pg(_retok(text))
    if n or names:
        p.sql = sql2
    else:
        p.sql = text
    p.nparams, p.named = n, (names or None)
    return p


# triggers the engine installs (api_sched TRIGGERS), in PostgreSQL form
_PG_TRIGGERS = {
    "bco_voucher_no_delete": ("vouchers", "BEFORE DELETE", None,
                              "IF OLD.status IN ('posted','reversed') THEN RAISE EXCEPTION 'Posted vouchers cannot be deleted. Reverse them instead (NFRS: vouchers are permanent).'; END IF; RETURN OLD;"),
    "bco_voucher_no_edit": ("vouchers", "BEFORE UPDATE", None,
                            "IF OLD.status IN ('posted','reversed') AND (NEW.date IS DISTINCT FROM OLD.date OR NEW.total IS DISTINCT FROM OLD.total "
                            "OR NEW.no IS DISTINCT FROM OLD.no OR NEW.type IS DISTINCT FROM OLD.type OR NEW.project_id IS DISTINCT FROM OLD.project_id "
                            "OR NEW.party_id IS DISTINCT FROM OLD.party_id OR NEW.source IS DISTINCT FROM OLD.source OR NEW.source_id IS DISTINCT FROM OLD.source_id "
                            "OR (OLD.status='reversed' AND NEW.status<>'reversed') "
                            "OR (OLD.status='posted' AND NEW.status NOT IN ('posted','reversed'))) "
                            "THEN RAISE EXCEPTION 'A posted voucher cannot be changed. Post a reversal and a new voucher instead.'; END IF; RETURN NEW;"),
    "bco_vline_no_delete": ("voucher_lines", "BEFORE DELETE", None,
                            "IF (SELECT status FROM vouchers WHERE id=OLD.voucher_id) IN ('posted','reversed') THEN RAISE EXCEPTION 'Lines of a posted voucher cannot be deleted. Reverse the voucher instead.'; END IF; RETURN OLD;"),
    "bco_vline_no_edit": ("voucher_lines", "BEFORE UPDATE OF voucher_id, account_id, debit, credit", None,
                          "IF (SELECT status FROM vouchers WHERE id=OLD.voucher_id) IN ('posted','reversed') THEN RAISE EXCEPTION 'Amounts and accounts of a posted voucher cannot be changed. Reverse it instead.'; END IF; RETURN NEW;"),
}


def _plan_ddl(sql, toks, s, words):
    p = Plan("ddl")
    if len(words) >= 2 and words[0] == "CREATE" and "TRIGGER" in words[:4]:
        m = re.search(r"(?is)TRIGGER\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)", sql)
        name = m.group(1) if m else ""
        spec = _PG_TRIGGERS.get(name)
        if not spec:
            return Plan("noop")      # unknown SQLite trigger: not installed on PostgreSQL
        table, when, _x, body = spec
        p.dyn = None
        p.sql = ("CREATE OR REPLACE FUNCTION bcfn_trg_%s() RETURNS trigger LANGUAGE plpgsql AS $f$ BEGIN %s END $f$"
                 % (name, body))
        p.sql = p.sql.replace("bcfn_trg_", "trg_")
        trig = ('DO $d$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid '
                "JOIN pg_namespace n ON n.oid=c.relnamespace WHERE t.tgname='%s' AND n.nspname=current_schema()) "
                "THEN CREATE TRIGGER %s %s ON %s FOR EACH ROW EXECUTE FUNCTION trg_%s(); END IF; END $d$"
                % (name, name, when, table, name))
        p.after = lambda conn, trig=trig: [trig]
        return p
    if len(words) >= 2 and words[0] == "DROP" and words[1] == "TRIGGER":
        m = re.search(r"(?is)TRIGGER\s+(?:IF\s+EXISTS\s+)?(\w+)", sql)
        name = m.group(1) if m else ""
        spec = _PG_TRIGGERS.get(name)
        if not spec:
            return Plan("noop")
        p.sql = 'DROP TRIGGER IF EXISTS %s ON %s' % (name, spec[0])
        return p
    if len(words) >= 2 and words[0] == "CREATE" and ("TABLE" in words[1:3]):
        text = translate_create_table(toks)
        text = re.sub(r"(?i)^CREATE\s+TEMP(ORARY)?\s+", "CREATE TEMPORARY ", text)
        return _finish(p, text)
    if len(words) >= 2 and words[0] == "CREATE" and "VIEW" in words[1:3]:
        m = re.match(r"(?is)\s*CREATE\s+(?:TEMP\w*\s+)?VIEW\s+(IF\s+NOT\s+EXISTS\s+)?([\w\"]+)\s+AS\s+(.*)$", sql)
        if m:
            name = m.group(2).strip('"')
            body = xlate_expr(tokenize(m.group(3)))
            if m.group(1):
                p.sql = ("DO $v$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_views WHERE schemaname=current_schema() "
                         "AND viewname='%s') THEN EXECUTE %s; END IF; END $v$"
                         % (name, _pgquote("CREATE VIEW %s AS %s" % (name, body))))
            else:
                p.sql = "CREATE VIEW %s AS %s" % (name, body)
            return p
    if len(words) >= 2 and words[0] == "CREATE" and "INDEX" in words[1:4]:
        text = xlate_expr(toks)
        text = re.sub(r"(?i)\bCOLLATE\s+NOCASE\b", "", text)
        return _finish(p, text)
    if words[:2] == ["ALTER", "TABLE"]:
        m = re.match(r"(?is)\s*ALTER\s+TABLE\s+([\w\"]+)\s+ADD\s+(?:COLUMN\s+)?(.*)$", sql)
        if m:
            col = _coldef(tokenize(m.group(2)))
            return _finish(p, "ALTER TABLE %s ADD COLUMN %s" % (m.group(1), col))
        return _finish(p, xlate_expr(toks))
    if words[:2] == ["DROP", "TABLE"] or words[:2] == ["DROP", "VIEW"] or words[:2] == ["DROP", "INDEX"]:
        return _finish(p, xlate_expr(toks))
    return _finish(p, xlate_expr(toks))


def _pgquote(s):
    return "'" + s.replace("'", "''") + "'"


def _plan_dml(sql, toks, s, words, first):
    p = Plan("dml")
    if first in ("INSERT", "REPLACE"):
        # INSERT [OR IGNORE|OR REPLACE] INTO t[(cols)] ...
        i = 1
        mode = "replace" if first == "REPLACE" else None
        if words[1] == "OR":
            mode = words[2].lower()
            i = 3
        # find INTO
        k = s.index(next(x for x in s if toks[x].k == "word" and toks[x].u == "INTO"))
        tname_i = s[k + 1]
        table = toks[tname_i].v.strip('"')
        p.table = table
        rest = toks[tname_i + 1:]
        # column list
        rs = _sig(rest)
        cols = None
        if rs and rest[rs[0]].v == "(":
            e = _match_paren(rest, rs[0])
            # VALUES or SELECT must follow; a '(' right after the name is the column list
            cols = [join(c).strip().strip('"') for c in _split_args(rest[rs[0] + 1:e])]
            body_toks = rest[e + 1:]
            head = "INSERT INTO %s(%s) " % (table, ", ".join(cols))
        else:
            body_toks = rest
            head = "INSERT INTO %s " % table
        p.insert_cols = cols
        body = xlate_expr(body_toks).strip()
        # existing ON CONFLICT / RETURNING in the statement
        has_conflict = re.search(r"(?i)\bON\s+CONFLICT\b", body) is not None
        has_returning = re.search(r"(?i)\bRETURNING\b", body) is not None
        p.fix_identity = cols is None or "id" in [c.lower() for c in cols]

        def build(conn, head=head, body=body, cols=cols, mode=mode, table=table,
                  has_conflict=has_conflict, has_returning=has_returning):
            tb = table_info(conn, table)
            text = head + body
            if mode == "ignore" and not has_conflict:
                text += " ON CONFLICT DO NOTHING"
            elif mode == "replace" and not has_conflict:
                text += _replace_clause(tb, cols)
            if not has_returning and tb is not None and tb.identity:
                text += " RETURNING %s" % tb.identity
            return text
        # plan depends on the catalog; params counted on the base text
        sql2, n, names = _params_to_pg(tokenize(head + body))
        p.nparams, p.named = n, (names or None)
        base_conv = (lambda conn, build=build: _params_to_pg(tokenize(build(conn)))[0]) if (n or names) else build
        cache = {}

        def dyn(conn, base_conv=base_conv, cache=cache):
            key = conn.ckey
            v = cache.get(key)
            if v is None:
                v = cache[key] = base_conv(conn)
            return v
        p.dyn = dyn
        p.returning_id = not has_returning
        p.sql = ""
        return p
    if first == "UPDATE":
        m = re.match(r"(?is)\s*UPDATE\s+(?:OR\s+\w+\s+)?([\w\"]+)", sql)
        p.table = m.group(1).strip('"') if m else None
        text = xlate_expr(toks)
        text = re.sub(r"(?is)^\s*UPDATE\s+OR\s+\w+\s+", "UPDATE ", text)
        return _finish(p, text)
    # DELETE
    m = re.match(r"(?is)\s*DELETE\s+FROM\s+([\w\"]+)", sql)
    p.table = m.group(1).strip('"') if m else None
    return _finish(p, xlate_expr(toks))


def _replace_clause(tb, cols):
    """INSERT OR REPLACE -> ON CONFLICT (<the unique key the row hits>) DO UPDATE SET every column"""
    if tb is None:
        return " ON CONFLICT DO NOTHING"
    cl = [c.lower() for c in (cols or tb.cols)]
    keys = [tb.pk] + tb.uniques if tb.pk else list(tb.uniques)
    target = None
    for k in keys:
        if k and all(x.lower() in cl for x in k):
            target = k
            break
    if target is None:
        return ""
    upd = [c for c in (cols or tb.cols) if c.lower() not in [x.lower() for x in target]]
    if not upd:
        return " ON CONFLICT (%s) DO NOTHING" % ", ".join(target)
    sets = ", ".join("%s=EXCLUDED.%s" % (c, c) for c in upd)
    # columns not given are reset to their defaults, as SQLite's REPLACE (delete + insert) does
    if cols:
        given = {c.lower() for c in cols}
        for c in tb.cols:
            if c.lower() not in given and c.lower() not in [x.lower() for x in target] and c != tb.identity:
                sets += ", %s=DEFAULT" % c
    return " ON CONFLICT (%s) DO UPDATE SET %s" % (", ".join(target), sets)


# ───────────────────────── SQL run once per database ─────────────────────────
SQLITE_MASTER_VIEW = """
CREATE OR REPLACE VIEW "%(s)s".sqlite_master AS
SELECT CASE c.relkind WHEN 'v' THEN 'view' WHEN 'i' THEN 'index' ELSE 'table' END::text AS type,
       c.relname::text AS name,
       COALESCE(t.relname, c.relname)::text AS tbl_name,
       0 AS rootpage,
       CASE WHEN c.relkind='v' THEN 'CREATE VIEW ' || c.relname || ' AS ' || pg_get_viewdef(c.oid)
            WHEN c.relkind='i' THEN pg_get_indexdef(c.oid)
            ELSE 'CREATE TABLE ' || c.relname || '(...)' END::text AS sql
FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
LEFT JOIN pg_index ix ON ix.indexrelid=c.oid LEFT JOIN pg_class t ON t.oid=ix.indrelid
WHERE n.nspname='%(s)s' AND c.relkind IN ('r','p','v','i') AND c.relname <> 'sqlite_master'
UNION ALL
SELECT 'trigger', tg.tgname::text, c.relname::text, 0, NULL
FROM pg_trigger tg JOIN pg_class c ON c.oid=tg.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace
WHERE n.nspname='%(s)s' AND NOT tg.tgisinternal
"""

FUNCTIONS_VERSION = "bcfn-10"
FUNCTIONS_SQL = r"""
CREATE SCHEMA IF NOT EXISTS bcfn;
CREATE OR REPLACE FUNCTION bcfn.to_real(x anyelement) RETURNS double precision LANGUAGE plpgsql IMMUTABLE AS $$
BEGIN
  IF x IS NULL THEN RETURN NULL; END IF;
  BEGIN RETURN x::text::double precision;
  EXCEPTION WHEN others THEN
    RETURN COALESCE(NULLIF(substring(btrim(x::text) from '^[-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?'), ''), '0')::double precision;
  END;
END $$;
CREATE OR REPLACE FUNCTION bcfn.to_real(x text) RETURNS double precision LANGUAGE plpgsql IMMUTABLE AS $$
BEGIN
  IF x IS NULL THEN RETURN NULL; END IF;
  BEGIN RETURN x::double precision;
  EXCEPTION WHEN others THEN
    RETURN COALESCE(NULLIF(substring(btrim(x) from '^[-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?'), ''), '0')::double precision;
  END;
END $$;
CREATE OR REPLACE FUNCTION bcfn.to_int(x anyelement) RETURNS bigint LANGUAGE sql IMMUTABLE AS $$
  SELECT trunc(bcfn.to_real(x::text))::bigint $$;
CREATE OR REPLACE FUNCTION bcfn.to_int(x text) RETURNS bigint LANGUAGE sql IMMUTABLE AS $$
  SELECT trunc(bcfn.to_real(x))::bigint $$;
CREATE OR REPLACE FUNCTION bcfn.to_num(x anyelement) RETURNS numeric LANGUAGE sql IMMUTABLE AS $$
  SELECT bcfn.to_real(x::text)::numeric $$;
CREATE OR REPLACE FUNCTION bcfn.to_num(x text) RETURNS numeric LANGUAGE sql IMMUTABLE AS $$
  SELECT bcfn.to_real(x)::numeric $$;

-- round(x, n) for every number type; SQLite returns a real
CREATE OR REPLACE FUNCTION bcfn.round(x double precision, n integer DEFAULT 0) RETURNS double precision
  LANGUAGE sql IMMUTABLE AS $$ SELECT round(x::numeric, n)::double precision $$;
CREATE OR REPLACE FUNCTION bcfn.round(x numeric, n integer DEFAULT 0) RETURNS double precision
  LANGUAGE sql IMMUTABLE AS $$ SELECT round(x, n)::double precision $$;
CREATE OR REPLACE FUNCTION bcfn.round(x text, n integer DEFAULT 0) RETURNS double precision
  LANGUAGE sql IMMUTABLE AS $$ SELECT round(bcfn.to_real(x)::numeric, n)::double precision $$;
CREATE OR REPLACE FUNCTION bcfn.round(x bigint, n integer DEFAULT 0) RETURNS double precision
  LANGUAGE sql IMMUTABLE AS $$ SELECT x::double precision $$;
CREATE OR REPLACE FUNCTION bcfn.abs(x double precision) RETURNS double precision LANGUAGE sql IMMUTABLE AS $$ SELECT abs(x) $$;
CREATE OR REPLACE FUNCTION bcfn.abs(x numeric) RETURNS numeric LANGUAGE sql IMMUTABLE AS $$ SELECT abs(x) $$;
CREATE OR REPLACE FUNCTION bcfn.abs(x bigint) RETURNS bigint LANGUAGE sql IMMUTABLE AS $$ SELECT abs(x) $$;
CREATE OR REPLACE FUNCTION bcfn.abs(x text) RETURNS double precision LANGUAGE sql IMMUTABLE AS $$ SELECT abs(bcfn.to_real(x)) $$;

-- text functions that also accept numbers (SQLite converts silently)
CREATE OR REPLACE FUNCTION bcfn.length(x text) RETURNS integer LANGUAGE sql IMMUTABLE AS $$ SELECT length(x) $$;
CREATE OR REPLACE FUNCTION bcfn.length(x anyelement) RETURNS integer LANGUAGE sql IMMUTABLE AS $$ SELECT length(x::text) $$;
CREATE OR REPLACE FUNCTION bcfn.upper(x text) RETURNS text LANGUAGE sql IMMUTABLE AS $$ SELECT upper(x) $$;
CREATE OR REPLACE FUNCTION bcfn.upper(x anyelement) RETURNS text LANGUAGE sql IMMUTABLE AS $$ SELECT upper(x::text) $$;
CREATE OR REPLACE FUNCTION bcfn.lower(x text) RETURNS text LANGUAGE sql IMMUTABLE AS $$ SELECT lower(x) $$;
CREATE OR REPLACE FUNCTION bcfn.lower(x anyelement) RETURNS text LANGUAGE sql IMMUTABLE AS $$ SELECT lower(x::text) $$;
CREATE OR REPLACE FUNCTION bcfn.trim(x text, c text DEFAULT ' ') RETURNS text LANGUAGE sql IMMUTABLE AS $$ SELECT btrim(x, c) $$;
CREATE OR REPLACE FUNCTION bcfn.trim(x anyelement) RETURNS text LANGUAGE sql IMMUTABLE AS $$ SELECT btrim(x::text) $$;
CREATE OR REPLACE FUNCTION bcfn.ltrim(x text, c text DEFAULT ' ') RETURNS text LANGUAGE sql IMMUTABLE AS $$ SELECT ltrim(x, c) $$;
CREATE OR REPLACE FUNCTION bcfn.rtrim(x text, c text DEFAULT ' ') RETURNS text LANGUAGE sql IMMUTABLE AS $$ SELECT rtrim(x, c) $$;
CREATE OR REPLACE FUNCTION bcfn.replace(x text, a text, b text) RETURNS text LANGUAGE sql IMMUTABLE AS $$ SELECT replace(x, a, b) $$;
CREATE OR REPLACE FUNCTION bcfn.replace(x anyelement, a text, b text) RETURNS text LANGUAGE sql IMMUTABLE AS $$ SELECT replace(x::text, a, b) $$;
CREATE OR REPLACE FUNCTION bcfn.substr(x text, s integer) RETURNS text LANGUAGE sql IMMUTABLE AS $$
  SELECT CASE WHEN s > 0 THEN substr(x, s) WHEN s = 0 THEN substr(x, 1) ELSE right(x, -s) END $$;
CREATE OR REPLACE FUNCTION bcfn.substr(x text, s integer, n integer) RETURNS text LANGUAGE sql IMMUTABLE AS $$
  SELECT CASE WHEN s > 0 THEN substr(x, s, n)
              WHEN s = 0 THEN substr(x, 1, greatest(n - 1, 0))
              ELSE substr(x, length(x) + s + 1, n) END $$;
CREATE OR REPLACE FUNCTION bcfn.substr(x anyelement, s integer) RETURNS text LANGUAGE sql IMMUTABLE AS $$ SELECT bcfn.substr(x::text, s) $$;
CREATE OR REPLACE FUNCTION bcfn.substr(x anyelement, s integer, n integer) RETURNS text LANGUAGE sql IMMUTABLE AS $$ SELECT bcfn.substr(x::text, s, n) $$;
CREATE OR REPLACE FUNCTION bcfn.instr(x text, y text) RETURNS integer LANGUAGE sql IMMUTABLE AS $$ SELECT strpos(x, y) $$;
CREATE OR REPLACE FUNCTION bcfn.typeof(x anyelement) RETURNS text LANGUAGE sql IMMUTABLE AS $$
  SELECT CASE WHEN x IS NULL THEN 'null' WHEN pg_typeof(x)::text IN ('integer','bigint','smallint') THEN 'integer'
              WHEN pg_typeof(x)::text = 'numeric' THEN CASE WHEN x::text ~ '^-?[0-9]+$' THEN 'integer' ELSE 'real' END
              WHEN pg_typeof(x)::text IN ('double precision','real') THEN 'real'
              WHEN pg_typeof(x)::text = 'bytea' THEN 'blob' ELSE 'text' END $$;
CREATE OR REPLACE FUNCTION bcfn.random() RETURNS bigint LANGUAGE sql VOLATILE AS $$
  SELECT (random() * 9223372036854775807)::bigint - 4611686018427387903 $$;

-- INTEGER PRIMARY KEY: highest id + 1 (SQLite's rowid rule; writers are serialised per company)
CREATE OR REPLACE FUNCTION bcfn.next_id(tbl text, col text DEFAULT 'id') RETURNS bigint LANGUAGE plpgsql VOLATILE AS $$
DECLARE m bigint; k text := 'bco.n' || md5(current_schema() || '.' || tbl); memo text;
        st text := statement_timestamp()::text;
BEGIN
  EXECUTE format('SELECT COALESCE(MAX(%I), 0) + 1 FROM %I.%I', col, current_schema(), tbl) INTO m;
  memo := current_setting(k, true);
  IF memo IS NOT NULL AND memo <> '' AND split_part(memo, '|', 1) = st AND split_part(memo, '|', 2)::bigint >= m THEN
    m := split_part(memo, '|', 2)::bigint + 1;   -- several rows in one statement
  END IF;
  PERFORM set_config(k, st || '|' || m, true);
  RETURN m;
END $$;

-- truth of a bare value, as SQLite: non-zero numbers are true, text is true when it starts with a non-zero number
CREATE OR REPLACE FUNCTION bcfn.truthy(x boolean) RETURNS boolean LANGUAGE sql IMMUTABLE AS $$ SELECT x $$;
CREATE OR REPLACE FUNCTION bcfn.truthy(x numeric) RETURNS boolean LANGUAGE sql IMMUTABLE AS $$ SELECT x <> 0 $$;
CREATE OR REPLACE FUNCTION bcfn.truthy(x double precision) RETURNS boolean LANGUAGE sql IMMUTABLE AS $$ SELECT x <> 0 $$;
CREATE OR REPLACE FUNCTION bcfn.truthy(x bigint) RETURNS boolean LANGUAGE sql IMMUTABLE AS $$ SELECT x <> 0 $$;
CREATE OR REPLACE FUNCTION bcfn.truthy(x text) RETURNS boolean LANGUAGE sql IMMUTABLE AS $$ SELECT bcfn.to_real(x) <> 0 $$;

-- SQLite comparisons are numbers (1/0): SUM(status='open') counts rows
CREATE OR REPLACE FUNCTION bcfn.bool_sfunc(s bigint, x boolean) RETURNS bigint LANGUAGE sql IMMUTABLE AS $$
  SELECT CASE WHEN x IS NULL THEN s ELSE COALESCE(s, 0) + x::int END $$;
DROP AGGREGATE IF EXISTS bcfn.sum(boolean);
CREATE AGGREGATE bcfn.sum(boolean) (SFUNC = bcfn.bool_sfunc, STYPE = bigint);
DROP AGGREGATE IF EXISTS bcfn.total(boolean);
CREATE AGGREGATE bcfn.total(boolean) (SFUNC = bcfn.bool_sfunc, STYPE = bigint, INITCOND = '0');
CREATE OR REPLACE FUNCTION bcfn.bool_avg_final(s bigint[]) RETURNS double precision LANGUAGE sql IMMUTABLE AS $$
  SELECT CASE WHEN s[2] = 0 THEN NULL ELSE s[1]::double precision / s[2] END $$;
CREATE OR REPLACE FUNCTION bcfn.bool_avg_sfunc(s bigint[], x boolean) RETURNS bigint[] LANGUAGE sql IMMUTABLE AS $$
  SELECT CASE WHEN x IS NULL THEN s ELSE ARRAY[s[1] + x::int, s[2] + 1] END $$;
DROP AGGREGATE IF EXISTS bcfn.avg(boolean);
CREATE AGGREGATE bcfn.avg(boolean) (SFUNC = bcfn.bool_avg_sfunc, STYPE = bigint[], FINALFUNC = bcfn.bool_avg_final, INITCOND = '{0,0}');

-- total(): sum that is 0.0 on no rows
CREATE OR REPLACE FUNCTION bcfn.total_sfunc(s double precision, x double precision) RETURNS double precision
  LANGUAGE sql IMMUTABLE AS $$ SELECT s + COALESCE(x, 0) $$;
DROP AGGREGATE IF EXISTS bcfn.total(double precision);
CREATE AGGREGATE bcfn.total(double precision) (SFUNC = bcfn.total_sfunc, STYPE = double precision, INITCOND = '0');

-- dates: SQLite keeps them as 'YYYY-MM-DD' text
CREATE OR REPLACE FUNCTION bcfn._ts(x text) RETURNS timestamp LANGUAGE plpgsql STABLE AS $$
BEGIN
  IF x IS NULL OR btrim(x) = '' THEN RETURN NULL; END IF;
  IF lower(x) = 'now' THEN RETURN (now() AT TIME ZONE 'utc'); END IF;
  IF x ~ '^-?[0-9]+(\.[0-9]+)?$' THEN RETURN timestamp '4714-11-24 12:00:00 BC' + (x::double precision * interval '1 day'); END IF;
  BEGIN RETURN x::timestamp; EXCEPTION WHEN others THEN RETURN NULL; END;
END $$;
CREATE OR REPLACE FUNCTION bcfn._mod(t timestamp, m text) RETURNS timestamp LANGUAGE plpgsql STABLE AS $$
DECLARE mm text := lower(btrim(m)); n double precision; u text;
BEGIN
  IF t IS NULL THEN RETURN NULL; END IF;
  IF mm = 'localtime' THEN RETURN (t AT TIME ZONE 'utc') AT TIME ZONE coalesce(current_setting('bco.tz', true), 'Asia/Kathmandu'); END IF;
  IF mm = 'utc' THEN RETURN t; END IF;
  IF mm = 'start of month' THEN RETURN date_trunc('month', t); END IF;
  IF mm = 'start of year' THEN RETURN date_trunc('year', t); END IF;
  IF mm = 'start of day' THEN RETURN date_trunc('day', t); END IF;
  IF mm LIKE 'weekday %' THEN
    n := substr(mm, 9)::int;
    RETURN t + ((((n::int - extract(dow FROM t)::int) % 7) + 7) % 7) * interval '1 day';
  END IF;
  n := substring(mm from '^[-+]?[0-9]*\.?[0-9]+')::double precision;
  u := btrim(substring(mm from '[a-z]+$'));
  IF u IN ('day','days') THEN RETURN t + n * interval '1 day'; END IF;
  IF u IN ('month','months') THEN RETURN t + (n::int) * interval '1 month'; END IF;
  IF u IN ('year','years') THEN RETURN t + (n::int) * interval '1 year'; END IF;
  IF u IN ('hour','hours') THEN RETURN t + n * interval '1 hour'; END IF;
  IF u IN ('minute','minutes') THEN RETURN t + n * interval '1 minute'; END IF;
  IF u IN ('second','seconds') THEN RETURN t + n * interval '1 second'; END IF;
  RETURN t;
END $$;
CREATE OR REPLACE FUNCTION bcfn._apply(x text, mods text[]) RETURNS timestamp LANGUAGE plpgsql STABLE AS $$
DECLARE t timestamp := bcfn._ts(x); m text;
BEGIN
  IF mods IS NOT NULL THEN FOREACH m IN ARRAY mods LOOP t := bcfn._mod(t, m); END LOOP; END IF;
  RETURN t;
END $$;
CREATE OR REPLACE FUNCTION bcfn.date(x anyelement, VARIADIC mods text[] DEFAULT NULL) RETURNS text LANGUAGE sql STABLE AS $$
  SELECT to_char(bcfn._apply(x::text, mods), 'YYYY-MM-DD') $$;
CREATE OR REPLACE FUNCTION bcfn.date(x text, VARIADIC mods text[] DEFAULT NULL) RETURNS text LANGUAGE sql STABLE AS $$
  SELECT to_char(bcfn._apply(x, mods), 'YYYY-MM-DD') $$;
CREATE OR REPLACE FUNCTION bcfn.datetime(x text, VARIADIC mods text[] DEFAULT NULL) RETURNS text LANGUAGE sql STABLE AS $$
  SELECT to_char(bcfn._apply(x, mods), 'YYYY-MM-DD HH24:MI:SS') $$;
CREATE OR REPLACE FUNCTION bcfn.julianday(x text, VARIADIC mods text[] DEFAULT NULL) RETURNS double precision LANGUAGE sql STABLE AS $$
  SELECT extract(epoch FROM bcfn._apply(x, mods) - timestamp '4714-11-24 12:00:00 BC') / 86400.0 $$;
CREATE OR REPLACE FUNCTION bcfn.strftime(f text, x text, VARIADIC mods text[] DEFAULT NULL) RETURNS text LANGUAGE plpgsql STABLE AS $$
DECLARE t timestamp := bcfn._apply(x, mods); r text := f;
BEGIN
  IF t IS NULL THEN RETURN NULL; END IF;
  r := replace(r, '%Y', to_char(t, 'YYYY')); r := replace(r, '%m', to_char(t, 'MM'));
  r := replace(r, '%d', to_char(t, 'DD'));   r := replace(r, '%H', to_char(t, 'HH24'));
  r := replace(r, '%M', to_char(t, 'MI'));   r := replace(r, '%S', to_char(t, 'SS'));
  r := replace(r, '%w', extract(dow FROM t)::int::text); r := replace(r, '%j', to_char(t, 'DDD'));
  r := replace(r, '%W', lpad(to_char(t, 'WW'), 2, '0')); r := replace(r, '%s', extract(epoch FROM t)::bigint::text);
  r := replace(r, '%%', '%');
  RETURN r;
END $$;

-- json_extract(text, '$.a.b')
CREATE OR REPLACE FUNCTION bcfn.json_extract(j text, p text) RETURNS text LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE path text[];
BEGIN
  IF j IS NULL OR btrim(j) = '' THEN RETURN NULL; END IF;
  path := string_to_array(regexp_replace(regexp_replace(p, '^\$\.?', ''), '\[(\d+)\]', '.\1', 'g'), '.');
  BEGIN RETURN j::jsonb #>> path; EXCEPTION WHEN others THEN RETURN NULL; END;
END $$;
"""
