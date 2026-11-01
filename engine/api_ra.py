"""
Resource pool, norms library and rate analysis (BuildCore 1.8).

* Resource pool - a shipped catalogue of about 750 construction materials, labour trades,
  equipment and transport modes (res_seed.py). Users pick from it, edit it, add their own lines,
  and adopt what a project needs into the Materials / Trades masters with one click.
* Rate books - one per district and fiscal year (e.g. "DRC Kaski 2082/83"). A resource's rate
  comes from the chosen book, else from the pool (flagged when that is only a sample rate).
* Norms library - labour / material / equipment coefficients per unit of work, with sub-norms
  (mortar inside masonry). Import the DoR and DUDBC norms from a sheet; copy any norm to make
  a company version; the shipped starter set is marked unverified.
* Rate analysis - build-up to rate excluding and including VAT, with cartage by road class,
  saved per project / BOQ item and pushed into the BOQ rate analysis.
"""
import base64
import csv
import io
import json
import re
import zipfile
from xml.etree import ElementTree as ET

from core import ApiError, audit, get, ins, need, now, num, q, q1, r2, upd, val
from api_inventory import api as _register

_READY = set()


def api(name, module, perm):
    """Register an endpoint, making sure this module's tables exist in the open database first
    (so the screens work even if start-up could not create them)."""
    def wrap(f):
        def run(c, u, a):
            try:
                key = c.execute("PRAGMA database_list").fetchone()[2] or id(c)
            except Exception:
                key = id(c)
            if key not in _READY:
                if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='ra_norm_lines'").fetchone() \
                        or c.execute("SELECT COUNT(*) FROM res_pool WHERE system=1").fetchone()[0] < len(res_seed.POOL) \
                        or not _official_done(c):
                    init_ra(c)
                _READY.add(key)
            return f(c, u, a)
        run.__name__, run.__doc__ = f.__name__, f.__doc__
        _register(name, module, perm)(run)
        return f
    return wrap

import ra_calc
import res_seed
import ra_norms

MOD = "masters"          # who may view/edit the pool and norms
MOD_RA = "commercial"    # who may prepare rate analyses for BOQ items

SCHEMA_RA = """
CREATE TABLE IF NOT EXISTS res_pool(id INTEGER PRIMARY KEY, code TEXT UNIQUE, type TEXT, category TEXT, subcategory TEXT,
  name TEXT, spec TEXT, unit TEXT, weight REAL DEFAULT 0, rate REAL, rate_source TEXT, sample INTEGER DEFAULT 0,
  system INTEGER DEFAULT 0, active INTEGER DEFAULT 1, local_table TEXT, local_id INTEGER, remarks TEXT, updated TEXT);
CREATE INDEX IF NOT EXISTS ix_respool ON res_pool(type, category);
CREATE TABLE IF NOT EXISTS rate_books(id INTEGER PRIMARY KEY, code TEXT UNIQUE, name TEXT, district TEXT, fy TEXT,
  source TEXT, is_default INTEGER DEFAULT 0, active INTEGER DEFAULT 1, remarks TEXT);
CREATE TABLE IF NOT EXISTS res_rates(id INTEGER PRIMARY KEY, book_id INTEGER, res_id INTEGER, rate REAL, source TEXT,
  updated TEXT, UNIQUE(book_id, res_id));
CREATE TABLE IF NOT EXISTS ra_norms(id INTEGER PRIMARY KEY, code TEXT UNIQUE, source TEXT, section TEXT, title TEXT,
  unit TEXT, per_qty REAL DEFAULT 1, remarks TEXT, derivation TEXT, verified INTEGER DEFAULT 0, system INTEGER DEFAULT 0,
  active INTEGER DEFAULT 1, copied_from TEXT, updated TEXT);
CREATE TABLE IF NOT EXISTS ra_norm_lines(id INTEGER PRIMARY KEY, norm_id INTEGER, sort INTEGER, kind TEXT, ref TEXT,
  qty REAL DEFAULT 0, note TEXT);
CREATE INDEX IF NOT EXISTS ix_ranl ON ra_norm_lines(norm_id);
CREATE TABLE IF NOT EXISTS ra_analyses(id INTEGER PRIMARY KEY, no TEXT, project_id INTEGER, boq_item_id INTEGER,
  norm_id INTEGER, book_id INTEGER, title TEXT, unit TEXT, overhead_pct REAL, vat_pct REAL, leads TEXT, result TEXT,
  cost_per_unit REAL, rate_ex_vat REAL, rate_incl_vat REAL, status TEXT DEFAULT 'draft', remarks TEXT,
  created_by INTEGER, ts TEXT);
"""

TYPES = [("material", "Material"), ("tool", "Tools & PPE"), ("labour", "Labour"), ("equipment", "Equipment"),
         ("transport", "Transport")]
PREFIX = {"material": "M", "tool": "TL", "labour": "L", "equipment": "E", "transport": "T"}
POOL_COLS = ["code", "type", "category", "subcategory", "name", "spec", "unit", "weight", "rate", "rate_source", "remarks"]
NORM_COLS = ["norm_code", "source", "section", "title", "unit", "per_qty", "verified", "kind", "ref", "qty", "note"]


# ───────────────────────── set-up and seeding ─────────────────────────
def init_ra(c):
    """Create the tables and add any shipped resources / starter norms not yet present.
    Never overwrites a line the user has edited."""
    c.executescript(SCHEMA_RA)
    have = {r[0] for r in c.execute("SELECT code FROM res_pool").fetchall()}
    for x in res_seed.POOL:
        if x["code"] in have:
            continue
        c.execute("INSERT INTO res_pool(code,type,category,subcategory,name,spec,unit,weight,rate,rate_source,sample,system,"
                  "updated) VALUES(?,?,?,?,?,?,?,?,?,?,?,1,?)",
                  (x["code"], x["type"], x["category"], x["subcategory"], x["name"], x["spec"], x["unit"], x["weight"],
                   x["rate"], "Sample rate - replace with DRC / quotation" if x["rate"] is not None else None,
                   1 if x["rate"] is not None else 0, now()))
    haven = {r[0] for r in c.execute("SELECT code FROM ra_norms").fetchall()}
    for n in ra_norms.NORMS:
        if n["code"] in haven:
            continue
        nid = c.execute("INSERT INTO ra_norms(code,source,section,title,unit,per_qty,remarks,derivation,verified,system,updated) "
                        "VALUES(?,?,?,?,?,?,?,?,0,1,?)", (n["code"], n["source"], n["section"], n["title"], n["unit"],
                                                        n["per_qty"], n["remarks"], n["derivation"], now())).lastrowid
        for i, (k, ref, qty, note) in enumerate(n["lines"], 1):
            c.execute("INSERT INTO ra_norm_lines(norm_id,sort,kind,ref,qty,note) VALUES(?,?,?,?,?,?)", (nid, i, k, ref, qty, note))
    if not c.execute("SELECT COUNT(*) FROM rate_books").fetchone()[0]:
        c.execute("INSERT INTO rate_books(code,name,source,is_default) VALUES('POOL','Pool rates (sample)','Resource pool',1)")
    try:
        c.execute("SAVEPOINT bco_official")
        try:
            seed_official(c)
            c.execute("RELEASE SAVEPOINT bco_official")
        except Exception:
            c.execute("ROLLBACK TO SAVEPOINT bco_official")   # all or nothing
            c.execute("RELEASE SAVEPOINT bco_official")
            raise
    except Exception as e:  # never stop BuildCore from starting
        print("BuildCore: official norms not loaded: %s" % e)


# ───────────────────────── official norm books (2.11) ─────────────────────────
OFFICIAL_TAG = "official-norms-2.11"
OFFICIAL_FILE = "ra_official.json"
BOOK_MKT = ("MKT-2083", "Market reference 2083/84 (Kathmandu)", "Kathmandu", "2083/84",
            "BuildCore market reference: published market prices (Kantipur, pricenepal, expertsewa, NOC, 2026) and "
            "flagged estimates - replace with the district rate (DRC) or quotations")
BOOK_79 = ("RA-2079", "Electrical & sanitary rate analysis 2079/80 (as published)", "", "2079/80",
           "Rates printed in the Electrical and Sanitary rate analysis books 2079/80 - reference only")


def _official_done(c):
    try:
        return bool(c.execute("SELECT 1 FROM ra_seed_log WHERE tag=?", (OFFICIAL_TAG,)).fetchone())
    except Exception:
        return False


def _official_data():
    import os
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), OFFICIAL_FILE)
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def seed_official(c):
    """Load the DoR 2075, DUDBC building, Electrical 2079/80 and Sanitary 2079/80 norm books once per company:
    their resources into the pool, the norms into the library, and two rate books (market reference 2083/84
    and the 2079/80 book rates). Adds only what is missing - a norm, resource or rate the company already has
    (same code) is never replaced."""
    c.execute("CREATE TABLE IF NOT EXISTS ra_seed_log(tag TEXT PRIMARY KEY, ts TEXT, info TEXT)")
    if "ref_rate" not in _cols(c, "ra_norms"):
        c.execute("ALTER TABLE ra_norms ADD COLUMN ref_rate REAL")
    if "checks" not in _cols(c, "ra_norms"):
        c.execute("ALTER TABLE ra_norms ADD COLUMN checks TEXT")
    if _official_done(c):
        return
    data = _official_data()
    if not data:
        return
    ts = now()
    have = {r[0]: r[1] for r in c.execute("SELECT code, id FROM res_pool").fetchall()}
    rid, added_res = dict(have), 0
    for r in data["resources"]:
        if r["code"] in have:
            continue
        est = "estimate" in (r.get("market_source") or "").lower()
        rid[r["code"]] = c.execute(
            "INSERT INTO res_pool(code,type,category,subcategory,name,spec,unit,weight,rate,rate_source,sample,system,remarks,updated) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,1,?,?)",
            (r["code"], r["type"], r["category"], "Norm books", r["name"], None, r["unit"], r.get("weight") or 0,
             r.get("rate_market"), r.get("market_source"), 1 if (est or r.get("rate_market") is None) else 0,
             "From the official norm books (DoR / DUDBC / Electrical / Sanitary)", ts)).lastrowid
        added_res += 1

    def book(spec, make_default):
        code, name, district, fy, source = spec
        b = c.execute("SELECT id FROM rate_books WHERE code=?", (code,)).fetchone()
        if b:
            return b[0]
        bid = c.execute("INSERT INTO rate_books(code,name,district,fy,source,is_default,active,remarks) VALUES(?,?,?,?,?,0,1,?)",
                        (code, name, district, fy, source, "Shipped with BuildCore 2.11")).lastrowid
        if make_default:
            # only take over the default from the shipped sample book, never from a book the company made
            cur = c.execute("SELECT code FROM rate_books WHERE is_default=1").fetchall()
            if all(x[0] == "POOL" for x in cur):
                c.execute("UPDATE rate_books SET is_default=0")
                c.execute("UPDATE rate_books SET is_default=1 WHERE id=?", (bid,))
        return bid

    bm, b79 = book(BOOK_MKT, True), book(BOOK_79, False)
    for r in data["resources"]:
        res_id = rid.get(r["code"])
        if not res_id:
            continue
        if r.get("rate_market") is not None:
            c.execute("INSERT OR IGNORE INTO res_rates(book_id,res_id,rate,source,updated) VALUES(?,?,?,?,?)",
                      (bm, res_id, r["rate_market"], r.get("market_source"), ts))
        if r.get("rate_2079") is not None:
            c.execute("INSERT OR IGNORE INTO res_rates(book_id,res_id,rate,source,updated) VALUES(?,?,?,?,?)",
                      (b79, res_id, r["rate_2079"], "Rate analysis book 2079/80", ts))
    haven = {r[0] for r in c.execute("SELECT code FROM ra_norms").fetchall()}
    added, skipped = 0, 0
    for n in data["norms"]:
        if n["code"] in haven:
            skipped += 1
            continue
        haven.add(n["code"])
        chk = n.get("check") or []
        rem = n.get("remarks") or ""
        if chk:
            rem = ("CHECK AGAINST THE BOOK: " + "; ".join(chk) + ". " + rem).strip()
        nid = c.execute("INSERT INTO ra_norms(code,source,section,title,unit,per_qty,remarks,derivation,verified,system,active,updated,"
                        "ref_rate,checks) VALUES(?,?,?,?,?,?,?,?,?,1,1,?,?,?)",
                        (n["code"], n["source"], n["section"], n["title"], n["unit"], n["per_qty"] or 1, rem,
                         "Read from the published book PDF by BuildCore 2.11", 0 if chk else 1, ts, n.get("book_rate"),
                         "; ".join(chk) or None)).lastrowid
        c.executemany("INSERT INTO ra_norm_lines(norm_id,sort,kind,ref,qty,note) VALUES(?,?,?,?,?,?)",
                      [(nid, i, l["kind"], l["ref"], l["qty"], l.get("note")) for i, l in enumerate(n["lines"], 1)])
        added += 1
    c.execute("INSERT OR REPLACE INTO ra_seed_log(tag,ts,info) VALUES(?,?,?)",
              (OFFICIAL_TAG, ts, json.dumps({"norms": added, "skipped": skipped, "resources": added_res})))


def _cols(c, t):
    return {r[1] for r in c.execute("PRAGMA table_info(%s)" % t).fetchall()}


def _has(c, t):
    return bool(c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (t,)).fetchone())


# ───────────────────────── resource pool ─────────────────────────
@api("respool.meta", MOD, "view")
def pool_meta(c, u, a):
    cats = [dict(r) for r in q(c, "SELECT type, category, COUNT(*) n FROM res_pool WHERE active=1 GROUP BY type, category "
                                  "ORDER BY type, category")]
    counts = {r["type"]: r["n"] for r in q(c, "SELECT type, COUNT(*) n FROM res_pool WHERE active=1 GROUP BY type")}
    return {"types": TYPES, "categories": cats, "counts": counts,
            "books": [dict(r) for r in q(c, "SELECT * FROM rate_books WHERE active=1 ORDER BY is_default DESC, code")],
            "sections": [r["section"] for r in q(c, "SELECT DISTINCT section FROM ra_norms WHERE active=1 ORDER BY section")],
            "norm_sources": [r["source"] for r in q(c, "SELECT DISTINCT source FROM ra_norms ORDER BY source")]}


def _book_rates(c, book_id):
    if not book_id:
        return {}
    return {r["res_id"]: r for r in q(c, "SELECT res_id, rate, source FROM res_rates WHERE book_id=?", (int(book_id),))}


@api("respool.list", MOD, "view")
def pool_list(c, u, a):
    w, p = ["1=1"], []
    if not a.get("include_inactive"):
        w.append("active=1")
    for k in ("type", "category"):
        if a.get(k):
            w.append("%s=?" % k)
            p.append(a[k])
    if a.get("q"):
        for word in str(a["q"]).split():
            w.append("(code LIKE ? OR name LIKE ? OR spec LIKE ? OR subcategory LIKE ?)")
            p += ["%" + word + "%"] * 4
    if a.get("adopted"):
        w.append("local_id IS NOT NULL")
    lim = min(int(a.get("limit") or 2000), 5000)
    rows = [dict(r) for r in q(c, "SELECT * FROM res_pool WHERE %s ORDER BY type, category, code LIMIT %d" % (" AND ".join(w), lim), p)]
    br = _book_rates(c, a.get("book_id"))
    for r in rows:
        b = br.get(r["id"])
        r["book_rate"] = b["rate"] if b else None
        r["effective_rate"] = b["rate"] if b else r["rate"]
        r["rate_is_sample"] = bool(not b and r["sample"])
    return {"rows": rows, "count": len(rows)}


def _next_code(c, typ):
    pre = "U%s-" % PREFIX.get(typ, "X")
    n = val(c, "SELECT COUNT(*) FROM res_pool WHERE code LIKE ?", (pre + "%",), 0) + 1
    while val(c, "SELECT id FROM res_pool WHERE code=?", (pre + "%04d" % n,), None):
        n += 1
    return pre + "%04d" % n


@api("respool.save", MOD, "edit")
def pool_save(c, u, a):
    row = a.get("row") or {}
    keep = {k: row.get(k) for k in ("type", "category", "subcategory", "name", "spec", "unit", "weight", "rate",
                                    "rate_source", "remarks", "active") if k in row}
    if "rate" in keep:
        keep["rate"] = None if keep["rate"] in (None, "") else num(keep["rate"])
        keep["sample"] = 0                      # a rate typed by the user is no longer the shipped sample
        keep["rate_source"] = keep.get("rate_source") or "Edited by user"
    if keep.get("type") and keep["type"] not in PREFIX:
        raise ApiError("Type must be material, tool, labour, equipment or transport.")
    keep["updated"] = now()
    if row.get("id"):
        get(c, "res_pool", int(row["id"]), "Resource")
        upd(c, "res_pool", int(row["id"]), keep)
        rid = int(row["id"])
    else:
        need(row, "type", "name", "unit")
        code = (row.get("code") or "").strip().upper() or _next_code(c, row["type"])
        if val(c, "SELECT id FROM res_pool WHERE code=?", (code,), None):
            raise ApiError("Code %s already exists in the pool." % code)
        keep.update({"code": code, "system": 0, "active": 1})
        keep.setdefault("category", "User-defined")
        rid = ins(c, "res_pool", keep)
    audit(c, u, "save", "res_pool", rid, keep)
    return {"id": rid}


@api("respool.delete", MOD, "edit")
def pool_delete(c, u, a):
    r = get(c, "res_pool", int(a["id"]), "Resource")
    used = val(c, "SELECT COUNT(*) FROM ra_norm_lines WHERE ref=? AND kind IN ('L','M','E')", (r["code"],), 0)
    if r["system"] or used:
        upd(c, "res_pool", r["id"], {"active": 0, "updated": now()})
        return {"deactivated": True, "used_in_norms": used}
    c.execute("DELETE FROM res_pool WHERE id=?", (r["id"],))
    c.execute("DELETE FROM res_rates WHERE res_id=?", (r["id"],))
    return {"deleted": True}


@api("respool.adopt", MOD, "edit")
def pool_adopt(c, u, a):
    """Create Materials / Trades master rows from pool lines, so stores and BOQ can use them.
    Existing masters with the same code are linked, not duplicated."""
    ids = [int(x) for x in (a.get("ids") or [])]
    if not ids:
        raise ApiError("Choose one or more resources.")
    made, linked, skipped = 0, 0, []
    br = _book_rates(c, a.get("book_id"))
    for rid in ids:
        r = get(c, "res_pool", rid, "Resource")
        if r["type"] in ("material", "tool") and _has(c, "materials"):
            table = "materials"
        elif r["type"] == "labour" and _has(c, "trades"):
            table = "trades"
        else:
            skipped.append(r["code"])
            continue
        cols = _cols(c, table)
        ex = val(c, "SELECT id FROM %s WHERE code=?" % table, (r["code"],), None) if "code" in cols else None
        if ex:
            upd(c, "res_pool", r["id"], {"local_table": table, "local_id": ex})
            linked += 1
            continue
        rate = br[r["id"]]["rate"] if r["id"] in br else r["rate"]
        d = {"code": r["code"], "name": r["name"]}
        opt = {"unit": r["unit"], "category": r["category"], "spec": r["spec"], "specification": r["spec"],
               "std_rate": rate, "rate": rate, "unit_weight": r["weight"], "active": 1,
               "rate_hour": (num(rate) / 8.0) if (table == "trades" and rate) else None,
               "project_id": a.get("project_id") if table == "trades" else None}
        d.update({k: v for k, v in opt.items() if k in cols and v is not None})
        lid = ins(c, table, {k: v for k, v in d.items() if k in cols})
        upd(c, "res_pool", r["id"], {"local_table": table, "local_id": lid})
        made += 1
    audit(c, u, "adopt", "res_pool", None, {"made": made, "linked": linked})
    return {"created": made, "linked": linked, "skipped": skipped}


# ───────────────────────── import / export ─────────────────────────
def _xlsx_rows(data, sheet_hint=None):
    """Read the first (or named) sheet of an .xlsx with the standard library only."""
    z = zipfile.ZipFile(io.BytesIO(data))
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", ns):
            shared.append("".join(t.text or "" for t in si.iter("{%s}t" % ns["m"])))
    wbx = ET.fromstring(z.read("xl/workbook.xml"))
    rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    rmap = {r.get("Id"): r.get("Target") for r in rels}
    sheets = [(s.get("name"), rmap[s.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")])
              for s in wbx.find("m:sheets", ns)]
    target = sheets[0][1]
    for name, tgt in sheets:
        if sheet_hint and name.lower() == sheet_hint.lower():
            target = tgt
    path = "xl/" + target.lstrip("/").replace("xl/", "")
    out = []
    for row in ET.fromstring(z.read(path)).iter("{%s}row" % ns["m"]):
        vals = {}
        for cel in row.findall("m:c", ns):
            ref = re.match(r"([A-Z]+)", cel.get("r")).group(1)
            col = 0
            for ch in ref:
                col = col * 26 + ord(ch) - 64
            v = cel.find("m:v", ns)
            t = cel.get("t")
            if t == "s" and v is not None:
                x = shared[int(v.text)]
            elif t == "inlineStr":
                x = "".join(tt.text or "" for tt in cel.iter("{%s}t" % ns["m"]))
            else:
                x = v.text if v is not None else ""
            vals[col - 1] = x
        if vals:
            out.append([vals.get(i, "") for i in range(max(vals) + 1)])
    return out


def _table_from(a, sheet_hint=None):
    """Rows as dicts from {csv: text} or {b64: file, filename}. The header row is found by looking
    for the expected first column name so title rows above it are ignored."""
    if a.get("rows"):
        return a["rows"]
    if a.get("csv"):
        grid = list(csv.reader(io.StringIO(a["csv"])))
    elif a.get("b64"):
        data = base64.b64decode(a["b64"].split(",")[-1])
        if (a.get("filename") or "").lower().endswith(".csv"):
            grid = list(csv.reader(io.StringIO(data.decode("utf-8-sig"))))
        else:
            grid = _xlsx_rows(data, sheet_hint)
    else:
        raise ApiError("Attach a .xlsx or .csv file.")
    hi = None
    for i, r in enumerate(grid[:30]):
        cells = [str(x).strip().lower() for x in r]
        if "code" in cells or "norm_code" in cells:
            hi = i
            break
    if hi is None:
        raise ApiError("No header row with a 'code' / 'norm_code' column was found.")
    head = [str(x).strip().lower().replace(" ", "_") for x in grid[hi]]
    rows = []
    for r in grid[hi + 1:]:
        if not any(str(x).strip() for x in r):
            continue
        rows.append({head[i]: (r[i] if i < len(r) else "") for i in range(len(head)) if head[i]})
    return rows


@api("respool.import", MOD, "edit")
def pool_import(c, u, a):
    """Add or update pool lines from a sheet with columns code, type, category, name, unit, rate ...
    A blank code creates a user line. With book_id, the rate goes into that rate book instead."""
    rows = _table_from(a, "Resources")
    added = updated = 0
    errs = []
    book = int(a["book_id"]) if a.get("book_id") else None
    for i, r in enumerate(rows, 1):
        code = str(r.get("code") or "").strip().upper()
        ex = q1(c, "SELECT * FROM res_pool WHERE code=?", (code,)) if code else None
        rate = r.get("rate")
        rate = None if rate in (None, "") else num(rate)
        if ex:
            if book:
                if rate is not None:
                    _set_book_rate(c, book, ex["id"], rate, r.get("rate_source") or "Imported")
                    updated += 1
                continue
            d = {k: r[k] for k in ("category", "subcategory", "name", "spec", "unit", "remarks")
                 if r.get(k) not in (None, "") and str(r[k]) != str(ex[k] or "")}
            if r.get("weight") not in (None, "") and abs(num(r["weight"]) - num(ex["weight"])) > 1e-6:
                d["weight"] = num(r["weight"])
            if rate is not None and rate != ex["rate"]:
                d.update({"rate": rate, "sample": 0, "rate_source": r.get("rate_source") or "Imported"})
            if d:
                d["updated"] = now()
                upd(c, "res_pool", ex["id"], d)
                updated += 1
        else:
            typ = str(r.get("type") or "").strip().lower()
            if typ not in PREFIX or not r.get("name") or not r.get("unit"):
                errs.append("Row %d: needs type, name and unit" % i)
                continue
            rid = ins(c, "res_pool", {"code": code or _next_code(c, typ), "type": typ,
                                      "category": r.get("category") or "User-defined", "subcategory": r.get("subcategory"),
                                      "name": r["name"], "spec": r.get("spec"), "unit": r["unit"],
                                      "weight": num(r.get("weight")), "rate": rate,
                                      "rate_source": r.get("rate_source") or ("Imported" if rate is not None else None),
                                      "sample": 0, "system": 0, "active": 1, "updated": now()})
            if book and rate is not None:
                _set_book_rate(c, book, rid, rate, "Imported")
            added += 1
    audit(c, u, "import", "res_pool", None, {"added": added, "updated": updated})
    return {"added": added, "updated": updated, "errors": errs[:20]}


@api("respool.export", MOD, "view")
def pool_export(c, u, a):
    rows = pool_list(c, u, dict(a, limit=5000))["rows"]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(POOL_COLS + ["book_rate"])
    for r in rows:
        w.writerow([r.get(k) if r.get(k) is not None else "" for k in POOL_COLS] + [r["book_rate"] or ""])
    return {"filename": "resource_pool.csv", "csv": buf.getvalue(), "count": len(rows)}


# ───────────────────────── rate books ─────────────────────────
def _set_book_rate(c, book_id, res_id, rate, source):
    ex = q1(c, "SELECT id FROM res_rates WHERE book_id=? AND res_id=?", (book_id, res_id))
    if ex:
        upd(c, "res_rates", ex["id"], {"rate": rate, "source": source, "updated": now()})
    else:
        ins(c, "res_rates", {"book_id": book_id, "res_id": res_id, "rate": rate, "source": source, "updated": now()})


@api("ratebook.save", MOD, "edit")
def book_save(c, u, a):
    row = a.get("row") or {}
    need(row, "code", "name")
    keep = {k: row.get(k) for k in ("code", "name", "district", "fy", "source", "remarks", "is_default") if k in row}
    keep["is_default"] = 1 if keep.get("is_default") in (1, "1", True) else 0
    if keep["is_default"]:
        c.execute("UPDATE rate_books SET is_default=0")
    if row.get("id"):
        upd(c, "rate_books", int(row["id"]), keep)
        bid = int(row["id"])
    else:
        if val(c, "SELECT id FROM rate_books WHERE code=?", (row["code"],), None):
            raise ApiError("A rate book with that code exists.")
        bid = ins(c, "rate_books", keep)
        if a.get("copy_from"):
            f = 1 + num(a.get("escalation_pct")) / 100.0
            for r in q(c, "SELECT res_id, rate FROM res_rates WHERE book_id=?", (int(a["copy_from"]),)):
                _set_book_rate(c, bid, r["res_id"], r2(num(r["rate"]) * f), "Copied +%s%%" % num(a.get("escalation_pct")))
    return {"id": bid}


@api("ratebook.set_rates", MOD, "edit")
def book_set_rates(c, u, a):
    """Set rates for many resources in one book: rates = [{res_id, rate}] (blank rate removes it)."""
    need(a, "book_id")
    n = 0
    for x in a.get("rates") or []:
        if x.get("rate") in (None, ""):
            c.execute("DELETE FROM res_rates WHERE book_id=? AND res_id=?", (int(a["book_id"]), int(x["res_id"])))
        else:
            _set_book_rate(c, int(a["book_id"]), int(x["res_id"]), num(x["rate"]), x.get("source") or "Entered")
        n += 1
    return {"saved": n}


# ───────────────────────── norms ─────────────────────────
def _norm_dict(c, n):
    d = dict(n)
    d["lines"] = [dict(x) for x in q(c, "SELECT * FROM ra_norm_lines WHERE norm_id=? ORDER BY sort, id", (n["id"],))]
    return d


@api("rnorm.list", MOD, "view")
def norm_list(c, u, a):
    w, p = ["active=1"], []
    for k in ("section", "source"):
        if a.get(k):
            w.append("%s=?" % k)
            p.append(a[k])
    if a.get("q"):
        for word in str(a["q"]).split():
            w.append("(code LIKE ? OR title LIKE ?)")
            p += ["%" + word + "%"] * 2
    if a.get("verified") not in (None, ""):
        w.append("verified=?")
        p.append(int(a["verified"]))
    rows = [dict(r) for r in q(c, "SELECT n.*, (SELECT COUNT(*) FROM ra_norm_lines l WHERE l.norm_id=n.id) lines "
                                  "FROM ra_norms n WHERE %s ORDER BY section, code" % " AND ".join(w), p)]
    return {"rows": rows}


@api("rnorm.get", MOD, "view")
def norm_get(c, u, a):
    n = q1(c, "SELECT * FROM ra_norms WHERE id=?", (int(a["id"]),)) if a.get("id") else \
        q1(c, "SELECT * FROM ra_norms WHERE code=?", (a.get("code"),))
    if not n:
        raise ApiError("Norm not found.")
    d = _norm_dict(c, n)
    names = {r["code"]: dict(r) for r in q(c, "SELECT code, name, unit, type FROM res_pool")}
    nnames = {r["code"]: dict(r) for r in q(c, "SELECT code, title name, unit FROM ra_norms")}
    for ln in d["lines"]:
        info = (nnames if ln["kind"] == "N" else names).get(ln["ref"]) or {}
        if ln["kind"] == "X":
            letters = "".join(ch for ch in str(ln["ref"] or "").upper() if ch in "LME") or "L"
            ln["name"], ln["unit"] = "% of " + ra_calc.X_BASES.get(letters, letters), "%"
            continue
        ln["name"], ln["unit"] = info.get("name") or "?", info.get("unit") or ""
    return d


def _check_lines(c, lines):
    bad = []
    for ln in lines:
        k = ln.get("kind")
        if k not in ra_calc.KINDS:
            bad.append("kind %s" % k)
        elif k == "N":
            if not val(c, "SELECT id FROM ra_norms WHERE code=?", (ln.get("ref"),), None):
                bad.append("sub-norm %s" % ln.get("ref"))
        elif k != "X" and not val(c, "SELECT id FROM res_pool WHERE code=?", (ln.get("ref"),), None):
            bad.append("resource %s" % ln.get("ref"))
    if bad:
        raise ApiError("Unknown in the lines: " + ", ".join(bad[:8]))


@api("rnorm.save", MOD, "edit")
def norm_save(c, u, a):
    row = a.get("row") or {}
    need(row, "code", "title", "unit")
    lines = a.get("lines") or []
    _check_lines(c, lines)
    keep = {k: row.get(k) for k in ("code", "source", "section", "title", "unit", "per_qty", "remarks", "derivation")}
    keep["per_qty"] = num(keep.get("per_qty")) or 1
    keep["updated"] = now()
    if row.get("id"):
        n = get(c, "ra_norms", int(row["id"]), "Norm")
        if n["system"] or n["verified"]:
            raise ApiError("Shipped and verified norms are kept as published. Use 'Copy to edit' for a company version.")
        upd(c, "ra_norms", n["id"], keep)
        nid = n["id"]
        c.execute("DELETE FROM ra_norm_lines WHERE norm_id=?", (nid,))
    else:
        if val(c, "SELECT id FROM ra_norms WHERE code=?", (row["code"],), None):
            raise ApiError("Norm code %s exists." % row["code"])
        keep.update({"source": keep.get("source") or "Company", "verified": 0, "system": 0, "active": 1})
        nid = ins(c, "ra_norms", keep)
    for i, ln in enumerate(lines, 1):
        ins(c, "ra_norm_lines", {"norm_id": nid, "sort": i, "kind": ln["kind"], "ref": ln.get("ref") or "",
                                 "qty": num(ln.get("qty")), "note": ln.get("note")})
    audit(c, u, "save", "ra_norms", nid, {"code": row["code"], "lines": len(lines)})
    return {"id": nid}


@api("rnorm.copy", MOD, "edit")
def norm_copy(c, u, a):
    n = norm_get(c, u, a)
    code = a.get("new_code") or ("CO-" + n["code"])
    while val(c, "SELECT id FROM ra_norms WHERE code=?", (code,), None):
        code += "A"
    nid = ins(c, "ra_norms", {"code": code, "source": "Company", "section": n["section"], "title": n["title"],
                              "unit": n["unit"], "per_qty": n["per_qty"], "remarks": n["remarks"],
                              "derivation": n["derivation"], "verified": 0, "system": 0, "active": 1,
                              "copied_from": n["code"], "updated": now()})
    for ln in n["lines"]:
        ins(c, "ra_norm_lines", {"norm_id": nid, "sort": ln["sort"], "kind": ln["kind"], "ref": ln["ref"], "qty": ln["qty"],
                                 "note": ln["note"]})
    return {"id": nid, "code": code}


@api("rnorm.delete", MOD, "edit")
def norm_delete(c, u, a):
    n = get(c, "ra_norms", int(a["id"]), "Norm")
    if val(c, "SELECT COUNT(*) FROM ra_norm_lines WHERE kind='N' AND ref=?", (n["code"],), 0):
        raise ApiError("Other norms use %s as a sub-analysis." % n["code"])
    upd(c, "ra_norms", n["id"], {"active": 0, "updated": now()})
    return {"retired": True}


@api("rnorm.import", MOD, "edit")
def norm_import(c, u, a):
    """Load norms from a sheet: one row per resource line, the norm header repeated on each row
    (norm_code, source, section, title, unit, per_qty, verified, kind, ref, qty, note).
    This is how the DoR / DUDBC books are fed. Existing norms with the same code are replaced
    when replace=true, otherwise skipped. Unknown resource codes are listed, not guessed."""
    rows = _table_from(a, "Norm lines")
    groups = {}
    order = []
    for r in rows:
        code = str(r.get("norm_code") or r.get("code") or "").strip()
        if not code:
            continue
        if code not in groups:
            groups[code] = {"head": r, "lines": []}
            order.append(code)
        if str(r.get("kind") or "").strip():
            groups[code]["lines"].append({"kind": str(r["kind"]).strip().upper()[:1], "ref": str(r.get("ref") or "").strip(),
                                          "qty": num(r.get("qty")), "note": r.get("note") or ""})
    added, replaced, skipped, missing = 0, 0, [], set()
    for code in order:
        g = groups[code]
        h = g["head"]
        for ln in g["lines"]:
            if ln["kind"] in "LME" and not val(c, "SELECT id FROM res_pool WHERE code=?", (ln["ref"],), None):
                missing.add(ln["ref"])
        ex = q1(c, "SELECT id FROM ra_norms WHERE code=?", (code,))
        if ex and not a.get("replace"):
            skipped.append(code)
            continue
        if ex:
            c.execute("DELETE FROM ra_norm_lines WHERE norm_id=?", (ex["id"],))
            c.execute("DELETE FROM ra_norms WHERE id=?", (ex["id"],))
            replaced += 1
        else:
            added += 1
        nid = ins(c, "ra_norms", {"code": code, "source": h.get("source") or a.get("source") or "Imported",
                                  "section": h.get("section"), "title": h.get("title") or code, "unit": h.get("unit"),
                                  "per_qty": num(h.get("per_qty")) or 1,
                                  "verified": 1 if str(h.get("verified") or a.get("verified") or "").lower()
                                  in ("1", "yes", "true", "y") else 0,
                                  "system": 0, "active": 1, "remarks": h.get("remarks"), "updated": now()})
        for i, ln in enumerate(g["lines"], 1):
            ins(c, "ra_norm_lines", dict(ln, norm_id=nid, sort=i))
    audit(c, u, "import", "ra_norms", None, {"added": added, "replaced": replaced})
    return {"added": added, "replaced": replaced, "skipped": skipped[:30], "missing_resources": sorted(missing)[:50]}


@api("rnorm.export", MOD, "view")
def norm_export(c, u, a):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(NORM_COLS)
    for n in norm_list(c, u, a)["rows"]:
        d = _norm_dict(c, q1(c, "SELECT * FROM ra_norms WHERE id=?", (n["id"],)))
        head = [d["code"], d["source"], d["section"], d["title"], d["unit"], d["per_qty"], d["verified"]]
        for ln in d["lines"] or [{"kind": "", "ref": "", "qty": "", "note": ""}]:
            w.writerow(head + [ln["kind"], ln["ref"], ln["qty"], ln["note"] or ""])
    return {"filename": "norms.csv", "csv": buf.getvalue()}


# ───────────────────────── rate analysis ─────────────────────────
def _resources(c, book_id):
    br = _book_rates(c, book_id)
    out = {}
    for r in q(c, "SELECT * FROM res_pool"):
        b = br.get(r["id"])
        out[r["code"]] = {"name": r["name"], "unit": r["unit"], "weight": r["weight"],
                          "rate": b["rate"] if b else r["rate"], "sample": (not b) and bool(r["sample"]), "type": r["type"]}
    return out


def _norm_map(c):
    out, by_id = {}, {}
    for n in q(c, "SELECT * FROM ra_norms"):
        d = dict(n)
        d["lines"] = []
        out[n["code"]] = d
        by_id[n["id"]] = d
    for x in q(c, "SELECT norm_id, kind, ref, qty, note FROM ra_norm_lines ORDER BY norm_id, sort, id"):
        d = by_id.get(x["norm_id"])
        if d is not None:
            d["lines"].append({"kind": x["kind"], "ref": x["ref"], "qty": x["qty"], "note": x["note"]})
    return out


def _book(c, a):
    if a.get("book_id"):
        return int(a["book_id"])
    return val(c, "SELECT id FROM rate_books WHERE is_default=1 ORDER BY id LIMIT 1", (), None)


@api("ranal.compute", MOD, "view")
def ra_compute(c, u, a):
    """Work out a rate without saving. Pass norm_id or norm_code, and optionally book_id,
    overhead_pct (15), vat_pct (13) and leads {transport code: km}."""
    norms = _norm_map(c)
    if a.get("norm_id"):
        code = val(c, "SELECT code FROM ra_norms WHERE id=?", (int(a["norm_id"]),), None)
    else:
        code = a.get("norm_code")
    if code not in norms:
        raise ApiError("Choose a norm.")
    bid = _book(c, a)
    res = _resources(c, bid)
    trates = {k: (v["rate"] or 0, v["unit"]) for k, v in res.items() if v["type"] == "transport"}
    leads = {k: num(v) for k, v in (a.get("leads") or {}).items() if num(v)}
    oh = 15.0 if a.get("overhead_pct") in (None, "") else num(a["overhead_pct"])
    vat = 13.0 if a.get("vat_pct") in (None, "") else num(a["vat_pct"])
    out = ra_calc.analyse(norms[code], res, norms, oh, vat, leads, trates)
    out.update({"book_id": bid, "leads": leads, "norm_id": norms[code]["id"], "source": norms[code]["source"],
                "verified": norms[code]["verified"]})
    return out


def _push_to_boq(c, boq_item_id, result):
    """Write the per-unit build-up into BuildCore's rate_analysis table and the BOQ item's rate
    column when those exist. Returns what was updated."""
    done = []
    if _has(c, "rate_analysis"):
        c.execute("DELETE FROM rate_analysis WHERE boq_item_id=?", (boq_item_id,))
        per = result["per_qty"] or 1
        kind = {"L": "labour", "M": "material", "E": "equipment", "N": "material", "X": "other"}
        for r in result["rows"]:
            ref = val(c, "SELECT local_id FROM res_pool WHERE code=?", (r["ref"],), None)
            c.execute("INSERT INTO rate_analysis(boq_item_id,kind,ref_id,description,qty_per_unit,rate) VALUES(?,?,?,?,?,?)",
                      (boq_item_id, kind[r["kind"]], ref, "%s %s" % (r["ref"], r["name"]), r["qty"] / per,
                       r["rate"] + (r.get("cartage_rate") or 0)))
        if result["overhead"]:
            c.execute("INSERT INTO rate_analysis(boq_item_id,kind,ref_id,description,qty_per_unit,rate) VALUES(?,?,?,?,?,?)",
                      (boq_item_id, "other", None, "Overhead & profit %s%%" % result["overhead_pct"], 1, result["overhead"]))
        done.append("rate_analysis")
    if _has(c, "boq_items"):
        cols = _cols(c, "boq_items")
        col = next((x for x in ("est_rate", "analysed_rate", "cost_rate") if x in cols), None)
        if col:
            c.execute("UPDATE boq_items SET %s=? WHERE id=?" % col, (result["rate_ex_vat"], boq_item_id))
            done.append("boq_items." + col)
    return done


@api("ranal.save", MOD_RA, "edit")
def ra_save(c, u, a):
    res = ra_compute(c, u, a)
    no = "RA-%04d" % (num(val(c, "SELECT COUNT(*) FROM ra_analyses", (), 0)) + 1)
    rid = ins(c, "ra_analyses", {"no": no, "project_id": a.get("project_id"), "boq_item_id": a.get("boq_item_id"),
                                 "norm_id": res["norm_id"], "book_id": res["book_id"], "title": a.get("title") or res["title"],
                                 "unit": res["unit"], "overhead_pct": res["overhead_pct"], "vat_pct": res["vat_pct"],
                                 "leads": json.dumps(res["leads"]), "result": json.dumps(res),
                                 "cost_per_unit": res["cost_per_unit"], "rate_ex_vat": res["rate_ex_vat"],
                                 "rate_incl_vat": res["rate_incl_vat"], "remarks": a.get("remarks"), "created_by": u["id"],
                                 "ts": now()})
    pushed = _push_to_boq(c, int(a["boq_item_id"]), res) if a.get("boq_item_id") and a.get("push") else []
    audit(c, u, "save", "ra_analyses", rid, {"rate": res["rate_ex_vat"]})
    return {"id": rid, "no": no, "rate_ex_vat": res["rate_ex_vat"], "pushed": pushed}


@api("ranal.list", MOD_RA, "view")
def ra_list(c, u, a):
    w, p = ["1=1"], []
    if a.get("project_id"):
        w.append("a.project_id=?")
        p.append(int(a["project_id"]))
    rows = [dict(r) for r in q(c, "SELECT a.id, a.no, a.project_id, a.boq_item_id, a.title, a.unit, a.cost_per_unit, "
                                  "a.rate_ex_vat, a.rate_incl_vat, a.status, a.ts, n.code norm_code, n.verified, b.code book "
                                  "FROM ra_analyses a LEFT JOIN ra_norms n ON n.id=a.norm_id LEFT JOIN rate_books b "
                                  "ON b.id=a.book_id WHERE %s ORDER BY a.id DESC" % " AND ".join(w), p)]
    return {"rows": rows}


@api("ranal.get", MOD_RA, "view")
def ra_get(c, u, a):
    r = get(c, "ra_analyses", int(a["id"]), "Analysis")
    d = dict(r)
    d["result"] = json.loads(r["result"] or "{}")
    return d


@api("ranal.recompute_all", MOD_RA, "edit")
def ra_recompute_all(c, u, a):
    """Re-price every saved analysis of a project with a new rate book (e.g. next year's DRC rates)."""
    n = 0
    for r in q(c, "SELECT * FROM ra_analyses WHERE (? IS NULL OR project_id=?)", (a.get("project_id"), a.get("project_id"))):
        res = ra_compute(c, u, {"norm_id": r["norm_id"], "book_id": a.get("book_id") or r["book_id"],
                                "overhead_pct": r["overhead_pct"], "vat_pct": r["vat_pct"], "leads": json.loads(r["leads"] or "{}")})
        upd(c, "ra_analyses", r["id"], {"result": json.dumps(res), "book_id": res["book_id"], "cost_per_unit": res["cost_per_unit"],
                                        "rate_ex_vat": res["rate_ex_vat"], "rate_incl_vat": res["rate_incl_vat"], "ts": now()})
        if r["boq_item_id"] and a.get("push"):
            _push_to_boq(c, r["boq_item_id"], res)
        n += 1
    return {"recomputed": n}


# ───────────────────────── item rates (every norm priced with one book) ─────────────────────────
@api("ranal.items", MOD, "view")
def ra_items(c, u, a):
    """Price every norm in the library (or a filtered part of it) with one rate book.
    Returns one row per norm with the build-up totals and flags: rates missing, rates that are estimates,
    and norms marked for checking against the printed book."""
    norms = _norm_map(c)
    bid = _book(c, a)
    res = _resources(c, bid)
    est = {r["res_id"] for r in q(c, "SELECT res_id FROM res_rates WHERE book_id=? AND LOWER(COALESCE(source,'')) LIKE '%estimate%'",
                                     (bid or 0,))}
    est_codes = {r["code"] for r in q(c, "SELECT id, code FROM res_pool") if r["id"] in est}
    trates = {k: (v["rate"] or 0, v["unit"]) for k, v in res.items() if v["type"] == "transport"}
    oh = 15.0 if a.get("overhead_pct") in (None, "") else num(a["overhead_pct"])
    vat = 13.0 if a.get("vat_pct") in (None, "") else num(a["vat_pct"])
    words = str(a.get("q") or "").lower().split()
    out, sums = [], {"norms": 0, "complete": 0, "missing": 0, "estimates": 0, "to_check": 0}
    for code, n in sorted(norms.items(), key=lambda kv: ((kv[1]["source"] or ""), kv[1]["section"] or "", kv[0])):
        if not n.get("active", 1):
            continue
        if a.get("source") and n["source"] != a["source"]:
            continue
        if a.get("section") and n["section"] != a["section"]:
            continue
        if words and not all(w in (code + " " + (n["title"] or "")).lower() for w in words):
            continue
        try:
            r = ra_calc.analyse(n, res, norms, oh, vat, {}, trates)
        except Exception as e:
            r = {"labour": 0, "material": 0, "equipment": 0, "sundries": 0, "cost_per_unit": 0, "rate_ex_vat": 0,
                 "rate_incl_vat": 0, "warnings": [str(e)]}
        miss = sum(1 for w in r["warnings"] if "No rate for" in w or "not in the pool" in w or "not found" in w)
        nest = len({ln["ref"] for ln in n["lines"] if ln["kind"] in "LME" and ln["ref"] in est_codes})
        row = {"id": n["id"], "code": code, "source": n["source"], "section": n["section"], "title": n["title"], "unit": n["unit"],
               "per_qty": n["per_qty"], "labour": r["labour"], "material": r["material"], "equipment": r["equipment"],
               "sundries": r["sundries"], "cost_per_unit": r["cost_per_unit"], "rate_ex_vat": r["rate_ex_vat"],
               "rate_incl_vat": r["rate_incl_vat"], "missing": miss, "estimates": nest, "verified": n.get("verified"),
               "checks": n.get("checks") or "", "ref_rate": n.get("ref_rate")}
        sums["norms"] += 1
        sums["complete"] += 0 if miss else 1
        sums["missing"] += 1 if miss else 0
        sums["estimates"] += 1 if nest else 0
        sums["to_check"] += 1 if row["checks"] else 0
        out.append(row)
    book = q1(c, "SELECT code, name FROM rate_books WHERE id=?", (bid or 0,))
    return {"rows": out, "summary": sums, "book_id": bid, "book": dict(book) if book else None, "overhead_pct": oh, "vat_pct": vat}


@api("ranal.items_xlsx", MOD, "view")
def ra_items_xlsx(c, u, a):
    d = ra_items(c, u, a)
    cols = ["Code", "Source", "Section", "Description", "Unit", "Labour", "Material", "Equipment", "Sundries",
            "Cost per unit", "Rate excl. VAT", "Rate incl. VAT", "Rates missing", "Estimated rates", "Check against book",
            "Book rate (2079/80)"]
    per = lambda r, k: round((r[k] or 0) / (r["per_qty"] or 1), 2)
    rows = [[r["code"], r["source"], r["section"], r["title"], r["unit"], per(r, "labour"), per(r, "material"), per(r, "equipment"),
             per(r, "sundries"), r["cost_per_unit"], r["rate_ex_vat"], r["rate_incl_vat"], r["missing"], r["estimates"], r["checks"],
             r["ref_rate"]] for r in d["rows"]]
    title = "Item rates - %s (overhead %s%%, VAT %s%%)" % ((d["book"] or {}).get("name") or "pool rates", d["overhead_pct"], d["vat_pct"])
    try:
        from api_copilot import make_xlsx
        data = make_xlsx(title, cols, rows)
        return {"filename": "item_rates.xlsx", "b64": base64.b64encode(data).decode("ascii")}
    except Exception:
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(cols)
        w.writerows(rows)
        return {"filename": "item_rates.csv", "csv": buf.getvalue()}
