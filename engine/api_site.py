"""
Site mode you choose, and site packs that carry any of it to head office (BuildCore 2.12).

* Site mode is no longer a fixed set of buttons. Each user picks the screens they use at site
  (store, procurement, equipment, plant, quality, any menu screen); an administrator can set the
  default for everybody. Stored in site_mode_cfg.
* Site packs (the file a site with no internet sends to head office) can now carry, besides DPRs,
  issues and logsheets: requisitions, purchase requests, goods received, returns, transfers, stock
  counts, purchase bills, production runs, tests, NCRs, events, work orders, measurements and tasks.
  The site chooses which kinds go in the pack.
* At head office every record is matched by CODE (material, store, vendor, BOQ item, activity,
  machine ...), never by number, and loaded once only (import_map). Stock and accounting documents
  arrive as drafts so head office checks and posts them - a pack never posts into the books.
  Materials and vendors made at site that head office does not have yet are added (and listed).
"""
import json
import secrets

from core import ApiError, audit, ins, now, q, q1, setting, today, upd
from api_inventory import FUNCS, api

VERSION = "2.12.0"

SCHEMA = """
CREATE TABLE IF NOT EXISTS site_mode_cfg(scope TEXT PRIMARY KEY, items TEXT, updated TEXT, user_id INTEGER);
CREATE TABLE IF NOT EXISTS import_map(origin TEXT, kind TEXT, origin_id INTEGER, local_id INTEGER, pack_id INTEGER, ts TEXT);
"""

# ───────────────────────── what a pack can carry ─────────────────────────
# Each kind: table, date column, header references {column: code group}, child tables
# [(table, parent key, {column: code group})], the status it arrives in at head office (None = as sent),
# and whether its number is kept (stamped with the site code).
# Code groups: materials, parties, stores, boq_items, activities, equipment, wbs, trades, plants, mixes,
# accounts, projects, po (by number), po_line (special), and "kind:<k>" = another record of the same pack.
KINDS = [
    {"key": "mrq", "label": "Material requisitions", "group": "Store", "table": "mrq", "date": "date",
     "refs": {"store_id": "stores"}, "status": "submitted",
     "children": [("mrq_lines", "mrq_id", {"material_id": "materials", "boq_item_id": "boq_items"},
                   {"issued_qty": 0, "pr_qty": 0})]},
    {"key": "grn", "label": "Goods received (GRN)", "group": "Store", "table": "grn", "date": "date",
     "refs": {"store_id": "stores", "vendor_id": "parties", "po_id": "po"}, "status": "draft",
     "children": [("grn_lines", "grn_id", {"material_id": "materials", "po_line_id": "po_line"},
                   {"invoiced_qty": 0})]},
    {"key": "returns", "label": "Material returns", "group": "Store", "table": "returns", "date": "date",
     "refs": {"store_id": "stores"}, "status": "draft",
     "children": [("return_lines", "return_id", {"material_id": "materials", "boq_item_id": "boq_items",
                                                 "equipment_id": "equipment"}, {})]},
    {"key": "transfers", "label": "Stock transfers", "group": "Store", "table": "transfers", "date": "date",
     "project_col": "from_project",
     "refs": {"from_project": "projects", "to_project": "projects", "from_store": "allstores", "to_store": "allstores"},
     "status": "draft",
     "children": [("transfer_lines", "transfer_id", {"material_id": "materials"}, {"received_qty": 0})]},
    {"key": "counts", "label": "Stock counts", "group": "Store", "table": "stock_counts", "date": "date",
     "refs": {"store_id": "stores"}, "status": "draft",
     "children": [("count_lines", "count_id", {"material_id": "materials"}, {})]},
    {"key": "pr", "label": "Purchase requests", "group": "Procurement", "table": "pr", "date": "date",
     "refs": {"mrq_id": "kind:mrq"}, "status": "submitted",
     "children": [("pr_lines", "pr_id", {"material_id": "materials", "boq_item_id": "boq_items"},
                   {"ordered_qty": 0})]},
    {"key": "bills", "label": "Purchase bills (local purchase)", "group": "Procurement", "table": "invoices",
     "date": "date", "where": "kind='purchase'", "refs": {"party_id": "parties", "po_id": "po"}, "status": "draft",
     "children": [("invoice_lines", "invoice_id", {"material_id": "materials", "equipment_id": "equipment",
                                                   "boq_item_id": "boq_items", "account_id": "accounts"}, {})]},
    {"key": "runs", "label": "Plant production runs", "group": "Plant", "table": "plant_runs", "date": "date",
     "refs": {"plant_id": "plants", "mix_id": "mixes", "store_id": "stores", "output_material_id": "materials",
              "boq_item_id": "boq_items", "activity_id": "activities", "dpr_id": "kind:dpr"}, "status": "draft",
     "children": [("plant_run_lines", "run_id", {"material_id": "materials"}, {})]},
    {"key": "wo", "label": "Equipment work orders / repairs", "group": "Equipment", "table": "work_orders",
     "date": "substr(reported_at,1,10)", "refs": {"equipment_id": "equipment", "activity_id": "activities"},
     "status": None, "children": []},
    {"key": "tests", "label": "Quality tests", "group": "Quality", "table": "qa_tests", "date": "sampled_date",
     "refs": {"activity_id": "activities", "boq_item_id": "boq_items", "material_id": "materials",
              "dpr_id": "kind:dpr"}, "status": None, "children": []},
    {"key": "ncrs", "label": "Non-conformance reports (NCR)", "group": "Quality", "table": "ncrs", "date": "date",
     "refs": {"activity_id": "activities", "test_id": "kind:tests"}, "status": None, "children": []},
    {"key": "events", "label": "Events, hindrances & notices", "group": "Work", "table": "events", "date": "date",
     "refs": {"wbs_id": "wbs", "activity_id": "activities", "dpr_id": "kind:dpr"}, "status": None, "children": []},
    {"key": "measure", "label": "Measurements", "group": "Work", "table": "measurements", "date": "date",
     "refs": {}, "status": "draft",
     "children": [("measurement_lines", "measurement_id", {"boq_item_id": "boq_items"}, {})]},
    {"key": "tasks", "label": "Tasks", "group": "Work", "table": "tasks", "date": "substr(COALESCE(ts, due_date),1,10)",
     "refs": {}, "status": None, "children": []},
    {"key": "fissues", "label": "Issues & snags", "group": "Quality", "table": "fld_issues", "date": "substr(ts,1,10)",
     "refs": {"activity_id": "activities", "party_id": "parties"}, "status": None, "children": []},
    {"key": "frfis", "label": "RFIs", "group": "Work", "table": "fld_rfis", "date": "substr(ts,1,10)",
     "refs": {"party_id": "parties"}, "status": None, "children": []},
    {"key": "finsp", "label": "Inspections", "group": "Quality", "table": "fld_inspections", "date": "date",
     "refs": {"activity_id": "activities", "party_id": "parties"}, "status": None, "children": []},
    {"key": "fmeet", "label": "Meeting minutes", "group": "Work", "table": "fld_meetings", "date": "date",
     "refs": {}, "status": None, "children": [("fld_meeting_items", "meeting_id", {}, {"task_id": None, "carried_from": None})]},
]
KIND_BY = {k["key"]: k for k in KINDS}
BASE_KINDS = [("dpr", "Daily progress reports (DPR)", "Work"), ("issues", "Material issues", "Store"),
              ("logsheets", "Equipment logsheets", "Equipment")]
NEVER = {"id", "project_id", "origin", "origin_id", "voucher_id", "landed_rate", "match_status", "activity_ids"}


def _ensure(c):
    for st in SCHEMA.strip().split(";"):
        if st.strip():
            c.execute(st)


def init_site(c):
    _ensure(c)
    _wrap()


def _cols(c, t):
    return [r[1] for r in c.execute("PRAGMA table_info(%s)" % t).fetchall()]


def _has(c, t):
    return bool(c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (t,)).fetchone())


# ───────────────────────── site mode: what each person sees ─────────────────────────
@api("site.cfg_get")
def cfg_get(c, u, a):
    _ensure(c)
    _wrap()
    comp = q1(c, "SELECT items FROM site_mode_cfg WHERE scope='company'")
    mine = q1(c, "SELECT items FROM site_mode_cfg WHERE scope=?", ("user:%s" % u["id"],))
    load = lambda r: json.loads(r["items"]) if r and r["items"] else None
    return {"company": load(comp), "mine": load(mine), "is_admin": u.get("role") == "admin",
            "kinds": [{"key": k, "label": l, "group": g} for k, l, g in BASE_KINDS]
            + [{"key": k["key"], "label": k["label"], "group": k["group"]} for k in KINDS if _has(c, k["table"])],
            "site_code": setting(c, "site_code") or ""}


@api("site.cfg_save")
def cfg_save(c, u, a):
    _ensure(c)
    scope = a.get("scope") or "mine"
    if scope == "company":
        if u.get("role") != "admin":
            raise ApiError("Only an administrator can set site mode for everybody.")
        key = "company"
    else:
        key = "user:%s" % u["id"]
    items = a.get("items")
    if items is None:          # back to the default
        c.execute("DELETE FROM site_mode_cfg WHERE scope=?", (key,))
    else:
        if not isinstance(items, list):
            raise ApiError("items must be a list.")
        clean = [str(x)[:200] for x in items][:80]
        c.execute("INSERT OR REPLACE INTO site_mode_cfg(scope, items, updated, user_id) VALUES(?,?,?,?)",
                  (key, json.dumps(clean), now(), u["id"]))
    audit(c, u, "site_mode", "site_mode_cfg", None, {"scope": key, "items": items})
    return cfg_get(c, u, {})


# ───────────────────────── codes both computers share ─────────────────────────
def _code_of(c, pid):
    """id -> code, for writing a pack."""
    def m(sql, p=()):
        return {r["id"]: r["code"] for r in q(c, sql, p)}
    out = {
        "materials": m("SELECT id, code FROM materials"),
        "parties": m("SELECT id, code FROM parties"),
        "stores": m("SELECT id, code FROM stores WHERE project_id=?", (pid,)),
        "allstores": {r["id"]: "%s|%s" % (r["pcode"], r["code"]) for r in
                      q(c, "SELECT s.id, s.code, p.code pcode FROM stores s LEFT JOIN projects p ON p.id=s.project_id")},
        "boq_items": m("SELECT id, code FROM boq_items WHERE project_id=?", (pid,)),
        "activities": m("SELECT id, code FROM activities WHERE project_id=?", (pid,)),
        "equipment": m("SELECT id, code FROM equipment"),
        "wbs": m("SELECT id, code FROM wbs WHERE project_id=?", (pid,)),
        "projects": m("SELECT id, code FROM projects"),
        "po": {r["id"]: r["no"] for r in q(c, "SELECT id, no FROM po")},
        "accounts": m("SELECT id, code FROM accounts"),
    }
    out["plants"] = m("SELECT id, code FROM plants") if _has(c, "plants") else {}
    out["mixes"] = m("SELECT id, code FROM mix_designs") if _has(c, "mix_designs") else {}
    return out


def _id_of(c, pid):
    """code -> id, for loading a pack."""
    return {g: {v: k for k, v in d.items() if v not in (None, "")} for g, d in _code_of(c, pid).items()}


def _po_line_code(c, line_id):
    r = q1(c, "SELECT l.id, p.no, m.code FROM po_lines l JOIN po p ON p.id=l.po_id LEFT JOIN materials m "
              "ON m.id=l.material_id WHERE l.id=?", (line_id,))
    return "%s|%s" % (r["no"], r["code"]) if r else None


def _po_line_id(c, code):
    if not code or "|" not in code:
        return None
    no, mat = code.split("|", 1)
    r = q1(c, "SELECT l.id FROM po_lines l JOIN po p ON p.id=l.po_id JOIN materials m ON m.id=l.material_id "
              "WHERE p.no=? AND m.code=? ORDER BY l.id LIMIT 1", (no, mat))
    return r["id"] if r else None


def _row_out(c, row, refs, codes):
    rec = {}
    for k, v in row.items():
        if k in NEVER or k.endswith("_by") or k == "user_id" or k == "assigned_to":
            continue
        if k in refs:
            g = refs[k]
            if g == "skip":
                continue
            if v in (None, ""):
                rec[k] = None
            elif g == "po_line":
                rec[k] = _po_line_code(c, v)
            elif g.startswith("kind:"):
                rec[k] = v             # the site's own id; matched through import_map at head office
            else:
                rec[k] = codes[g].get(v)
            continue
        if k.endswith("_id"):
            continue                   # a link we cannot carry safely - left empty at head office
        rec[k] = v
    return rec


def _export_kind(c, spec, pid, frm, to, site, codes):
    if not _has(c, spec["table"]):
        return []
    pcol = spec.get("project_col", "project_id")
    where = "%s=? AND %s BETWEEN ? AND ?" % (pcol, spec["date"])
    if "status" in _cols(c, spec["table"]):
        where += " AND COALESCE(status,'') NOT IN ('draft','cancelled')" if spec["status"] in ("draft", "submitted") \
            else " AND COALESCE(status,'')<>'cancelled'"
    if spec.get("where"):
        where += " AND " + spec["where"]
    loaded_here = {r["local_id"] for r in q(c, "SELECT local_id FROM import_map WHERE kind=?", (spec["key"],))}
    out = []
    for row in q(c, "SELECT * FROM %s WHERE %s ORDER BY id" % (spec["table"], where), (pid, frm, to)):
        if row["id"] in loaded_here:
            continue                   # it came from another computer; never send it back
        rec = _row_out(c, row, spec["refs"], codes)
        rec["origin_id"] = row["id"]
        rec["_lines"] = {}
        for tbl, fk, crefs, _reset in spec["children"]:
            if _has(c, tbl):
                rec["_lines"][tbl] = [_row_out(c, x, dict(crefs, **{fk: "skip"}), codes)
                                      for x in q(c, "SELECT * FROM %s WHERE %s=? ORDER BY id" % (tbl, fk), (row["id"],))]
                for x in rec["_lines"][tbl]:
                    x.pop(fk, None)
        out.append(rec)
    return out


def _masters_used(c, records):
    """Full rows of the materials and vendors a pack uses, so head office can add any it lacks."""
    mats, pars = set(), set()

    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if k in ("material_id", "output_material_id", "material") and isinstance(v, str):
                    mats.add(v)
                elif k in ("vendor_id", "party_id") and isinstance(v, str):
                    pars.add(v)
                else:
                    walk(v)
        elif isinstance(o, list):
            for x in o:
                walk(x)
    walk(records)
    keep_m = [k for k in _cols(c, "materials") if k not in ("id",)]
    keep_p = [k for k in _cols(c, "parties") if k not in ("id", "bank_acno")]
    return {"materials": [{k: r[k] for k in keep_m} for r in q(c, "SELECT * FROM materials") if r["code"] in mats],
            "parties": [{k: r[k] for k in keep_p} for r in q(c, "SELECT * FROM parties") if r["code"] in pars]}


# ───────────────────────── wrapping the 1.6 site pack ─────────────────────────
_ORIG = {}


def _wrap():
    for name, fn in (("team.pack_export", pack_export), ("team.pack_preview", pack_preview),
                     ("team.pack_import", pack_import)):
        cur = FUNCS.get(name)
        if not cur or cur[0] is fn:
            continue
        _ORIG[name] = cur[0]
        FUNCS[name] = (fn,) + tuple(cur[1:])


def pack_export(c, u, a):
    want = a.get("kinds")
    want = set(want) if isinstance(want, list) and want else None
    r = _ORIG["team.pack_export"](c, u, a)
    pack = r["pack"]
    if want is not None:
        for k, _l, _g in BASE_KINDS:
            if k not in want:
                pack["records"][k] = []
    pid = int(a["project_id"])
    site = pack.get("site_code") or "SITE"
    frm, to = pack.get("from"), pack.get("to")
    codes = _code_of(c, pid)
    for spec in KINDS:
        if want is not None and spec["key"] not in want:
            continue
        pack["records"][spec["key"]] = _export_kind(c, spec, pid, frm, to, site, codes)
    pack["version"] = 2
    pack["masters"] = _masters_used(c, {k: v for k, v in pack["records"].items() if k in KIND_BY or k == "issues"})
    pack["counts"] = {k: len(v) for k, v in pack["records"].items() if v}
    r["counts"] = pack["counts"]
    last = q1(c, "SELECT id FROM site_packs WHERE direction='out' ORDER BY id DESC LIMIT 1")
    if last:
        upd(c, "site_packs", last["id"], {"counts": json.dumps(pack["counts"])})
    return r


def _seen(c, site, kind, oid):
    r = q1(c, "SELECT local_id FROM import_map WHERE origin=? AND kind=? AND origin_id=?", (site, kind, oid))
    return r["local_id"] if r else None


def pack_preview(c, u, a):
    r = _ORIG["team.pack_preview"](c, u, a)
    raw = a.get("pack")
    p = json.loads(raw) if isinstance(raw, str) else raw
    site = p.get("site_code") or "SITE"
    for spec in KINDS:
        recs = (p.get("records") or {}).get(spec["key"]) or []
        if recs:
            r["new"][spec["key"]] = sum(1 for x in recs if not _seen(c, site, spec["key"], x.get("origin_id")))
    r["new"] = {k: v for k, v in r["new"].items() if v or (r.get("counts") or {}).get(k)}
    r["labels"] = dict([(k, l) for k, l, _g in BASE_KINDS] + [(k["key"], k["label"]) for k in KINDS])
    m = p.get("masters") or {}
    r["new_masters"] = {
        "materials": [x["code"] for x in m.get("materials") or []
                      if not q1(c, "SELECT id FROM materials WHERE code=?", (x["code"],))],
        "parties": [x["code"] for x in m.get("parties") or []
                    if not q1(c, "SELECT id FROM parties WHERE code=?", (x["code"],))]}
    return r


def _add_masters(c, p, problems):
    added = []
    for table, label in (("materials", "material"), ("parties", "vendor / party")):
        cols = set(_cols(c, table))
        for x in (p.get("masters") or {}).get(table) or []:
            if not x.get("code") or q1(c, "SELECT id FROM %s WHERE code=?" % table, (x["code"],)):
                continue
            ins(c, table, {k: v for k, v in x.items() if k in cols and k != "id"})
            added.append("%s %s" % (label, x["code"]))
    if added:
        problems.append("Added from the site (check them in Master data): " + ", ".join(added[:30]))
    return added


def pack_import(c, u, a):
    raw = a.get("pack")
    p = json.loads(raw) if isinstance(raw, str) else raw
    if not isinstance(p, dict) or p.get("format") != "buildcore-site-pack":
        raise ApiError("This file is not a BuildCore site pack.")
    pid = q1(c, "SELECT id FROM projects WHERE code=?", (p.get("project_code"),))
    problems_pre = []
    if pid:
        _add_masters(c, p, problems_pre)          # before the 1.6 part, so its issue lines find new materials
    r = _ORIG["team.pack_import"](c, u, a)
    pid, pack_id, site = r["project_id"], r["pack_id"], r["site_code"]
    codes = _id_of(c, pid)
    problems = problems_pre + list(r["problems"])
    for spec in KINDS:
        recs = (p.get("records") or {}).get(spec["key"]) or []
        if not recs or not _has(c, spec["table"]):
            continue
        a_n, s_n = 0, 0
        hcols = set(_cols(c, spec["table"]))
        for rec in recs:
            oid = rec.get("origin_id")
            if _seen(c, site, spec["key"], oid):
                s_n += 1
                continue
            where = "%s %s of %s" % (spec["label"], rec.get("no") or rec.get("title") or oid, rec.get("date") or "")
            head = _row_in(c, rec, spec["refs"], codes, site, where, problems)
            if spec.get("project_col", "project_id") == "project_id":
                head["project_id"] = pid
            if spec["status"]:
                head["status"] = spec["status"]
            if "no" in head and head["no"]:
                head["no"] = _renumber(c, spec["table"], head["no"], site)
            if "created_by" in hcols:
                head["created_by"] = u["id"]
            if spec["key"] == "bills":
                head["kind"] = "purchase"
            head = {k: v for k, v in head.items() if k in hcols}
            nid = ins(c, spec["table"], head)
            for tbl, fk, crefs, reset in spec["children"]:
                if not _has(c, tbl):
                    continue
                ccols = set(_cols(c, tbl))
                for ln in (rec.get("_lines") or {}).get(tbl) or []:
                    row = _row_in(c, ln, crefs, codes, site, where, problems)
                    row.update(reset)
                    row[fk] = nid
                    ins(c, tbl, {k: v for k, v in row.items() if k in ccols})
            ins(c, "import_map", {"origin": site, "kind": spec["key"], "origin_id": oid, "local_id": nid,
                                  "pack_id": pack_id, "ts": now()})
            a_n += 1
        r["added"][spec["key"]] = a_n
        r["skipped"][spec["key"]] = s_n
    r["problems"] = problems[:60]
    upd(c, "site_packs", pack_id, {"counts": json.dumps({"added": r["added"], "skipped": r["skipped"]})})
    audit(c, u, "import_more", "site_packs", pack_id, {"added": r["added"]})
    return r


def _row_in(c, rec, refs, codes, site, where, problems):
    row = {}
    for k, v in rec.items():
        if k in ("origin_id", "_lines") or k in NEVER:
            continue
        if k in refs:
            g = refs[k]
            if v in (None, "") or g == "skip":
                row[k] = None
            elif g == "po_line":
                row[k] = _po_line_id(c, v)
            elif g.startswith("kind:"):
                row[k] = _seen(c, site, g[5:], v)
            else:
                lid = codes.get(g, {}).get(v)
                if lid is None:
                    problems.append("%s: %s \"%s\" is not on this computer" % (where, g.replace("_", " ").rstrip("s"), v))
                row[k] = lid
            continue
        row[k] = v
    return row


def _renumber(c, table, no, site):
    tagged = "%s/%s" % (site, no)
    if q1(c, "SELECT id FROM %s WHERE no=?" % table, (tagged,)):
        tagged = "%s-%s" % (tagged, secrets.token_hex(2))
    return tagged


_wrap()
