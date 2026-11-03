"""BuildCore 2.41.0 — Papers with transactions.

One register for documents and one for contracts, each tied to the money records. Nothing posted is changed.
  1. One document register: Field › Drawings rows are copied once into Document control (cards of type DRG, one revision per
     drawing row, links kept in pp_dwg_link) and kept in step both ways from then on.
  2. Documents linked to money: any library document can be linked to vouchers, bills, payments, GRNs, POs, IPCs,
     measurements, claims and contracts (pp_links). Rules per record type say which ones need a paper before posting
     (new companies: bills, payments and manual vouchers over 1,00,000; updated companies: off). Data checks list posted
     records without one.
  3. One contract register: Commercial › Contracts is the record for client contracts and subcontracts (switch
     pp_con_register; new companies on, updated companies off until confirmed). The project, the Claims register, the command
     centre, Contract admin securities and subcontract work orders read value, dates, retention, advance and bonds from it.
New tables pp_*.
"""
import json
import threading

import core
from core import ApiError, audit, get, ins, now, q, q1, r2, setting, today, upd, val
import api_inventory as inv
from api_inventory import api

VERSION = "2.41.0"
FLAG = "_bco241"
EPS = 0.005
PAPERS = "Papers needed: "

SCHEMA = """
CREATE TABLE IF NOT EXISTS pp_dwg_link(fld_id INTEGER PRIMARY KEY, doc_id INTEGER, rev_id INTEGER, ts TEXT);
CREATE INDEX IF NOT EXISTS ix_ppdw_doc ON pp_dwg_link(doc_id);
CREATE TABLE IF NOT EXISTS pp_links(id INTEGER PRIMARY KEY, dl_id INTEGER, entity TEXT, entity_id INTEGER, note TEXT, user_id INTEGER,
  ts TEXT, UNIQUE(dl_id, entity, entity_id));
CREATE INDEX IF NOT EXISTS ix_ppl_ent ON pp_links(entity, entity_id);
CREATE TABLE IF NOT EXISTS pp_con_sec(contract_id INTEGER, what TEXT, security_id INTEGER, ts TEXT, PRIMARY KEY(contract_id, what));
CREATE TABLE IF NOT EXISTS pp_log(id INTEGER PRIMARY KEY, what TEXT, detail TEXT, user_id INTEGER, ts TEXT);
"""

# record type -> (table, label, file entities that count, number column, module that may view it)
ENT = {
    "invoices": ("invoices", "Bill / invoice", ("invoices", "invoice"), "no", "accounts"),
    "payments": ("payments", "Payment / receipt", ("payments", "payment"), "no", "accounts"),
    "vouchers": ("vouchers", "Voucher", ("vouchers", "voucher"), "no", "accounts"),
    "grn": ("grn", "GRN", ("grn",), "no", "inventory"),
    "po": ("po", "Purchase order", ("po",), "no", "procurement"),
    "ipc": ("ipc", "IPC", ("ipc",), "no", "commercial"),
    "measurements": ("measurements", "Measurement", ("measurements", "measurement"), "no", "commercial"),
    "cr_claims": ("events", "Claim", ("cr_claims",), "no", "commercial"),
    "contracts": ("contracts", "Contract", ("contracts",), "ref_no", "commercial"),
}
# a voucher made by another record shows that record's papers
VSOURCE = {"invoice": "invoices", "payment": "payments", "grn": "grn"}

RULES = [("bill", "Supplier bill is posted"), ("payment", "Payment to a party is made"), ("grn", "GRN is posted"),
         ("ipc", "IPC is certified"), ("journal", "Manual voucher above the amount is posted")]

_LOCAL = threading.local()


def _has(c, t):
    return bool(val(c, "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?", (t,)))


def _cols(c, t):
    return {r["name"] for r in q(c, "PRAGMA table_info(%s)" % t)}


def _f(x, d=0.0):
    try:
        return float(str(x).replace(",", "")) if x not in (None, "") else d
    except (TypeError, ValueError):
        return d


def _set(c, k, v):
    c.execute("INSERT OR REPLACE INTO settings(key, value) VALUES(?,?)", (k, str(v)))


def _right(u, module, action):
    return bool(u) and (u.get("role") == "admin" or core.can(u, module, action))


def _need(u, module, action):
    if not _right(u, module, action):
        raise ApiError("You do not have the right to do this (%s %s)." % (module, action))


def _log(c, u, what, detail):
    ins(c, "pp_log", {"what": what, "detail": json.dumps(detail, ensure_ascii=False, default=str)[:20000],
                      "user_id": u["id"] if u else None, "ts": now()})


def _inr(n):
    """1,23,45,678 (Indian grouping), no decimals."""
    n = int(round(_f(n)))
    s, neg = str(abs(n)), n < 0
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ",".join(parts) + "," + tail
    return ("-" if neg else "") + s


def _wrap(name, factory):
    cur = inv.FUNCS.get(name)
    if not cur or getattr(cur[0], FLAG, False):
        return
    w = factory(cur[0])
    setattr(w, FLAG, True)
    w._orig = cur[0]
    # every earlier release's mark stays on the function (the updater's checks look for them)
    for f in [k for k in getattr(cur[0], "__dict__", {}) if k.startswith("_bco") and k != FLAG]:
        if getattr(cur[0], f, False):
            setattr(w, f, getattr(cur[0], f))
    inv.FUNCS[name] = (w, cur[1], cur[2], cur[3])


# ═════════════════════════════ 1. one document register ═════════════════════════════
DM_OF_FLD = {"superseded": "superseded", "for_construction": "approved", "as_built": "approved", "for_information": "for_info",
             "for_approval": "draft"}
FLD_OF_DM = {"approved": "for_construction", "approved_comments": "for_construction", "for_info": "for_information",
             "superseded": "superseded"}
FLD_LABEL = {"for_construction": "For construction", "for_approval": "For approval", "for_information": "For information",
             "as_built": "As built", "superseded": "Superseded"}


def _set_current(c, doc_id, rev_id):
    r = q1(c, "SELECT * FROM dm_revs WHERE id=?", (rev_id,))
    c.execute("UPDATE dm_revs SET status='superseded' WHERE doc_id=? AND id<>? AND status NOT IN ('in_review','superseded','withdrawn')",
              (doc_id, rev_id))
    upd(c, "dm_docs", doc_id, {"current_rev": r["rev"], "current_rev_id": rev_id, "status": r["status"], "updated": now()})


def sync_drawing(c, d):
    """Copy one Field › Drawings row into Document control (card per number, one revision per row) and link them."""
    if q1(c, "SELECT fld_id FROM pp_dwg_link WHERE fld_id=?", (d["id"],)):
        return None
    number = (d["number"] or "").strip().upper()
    doc = q1(c, "SELECT * FROM dm_docs WHERE project_id=? AND UPPER(doc_no)=?", (d["project_id"], number))
    if not doc:
        did = ins(c, "dm_docs", {"project_id": d["project_id"], "doc_no": number, "title": d["title"] or number,
                                 "discipline": d["discipline"], "doc_type": "DRG", "status": "draft", "active": 1,
                                 "created_by": d["created_by"], "ts": d["ts"] or now(), "updated": now()})
    else:
        did = doc["id"]
    rev = (d["revision"] or "0").strip().upper() or "0"
    r = q1(c, "SELECT id FROM dm_revs WHERE doc_id=? AND UPPER(rev)=?", (did, rev))
    if r:
        rid = r["id"]
        if d["file_id"] and not val(c, "SELECT file_id FROM dm_revs WHERE id=?", (rid,)):
            upd(c, "dm_revs", rid, {"file_id": d["file_id"]})
    else:
        st = "superseded" if not d["current"] else DM_OF_FLD.get(d["status"] or "", "draft")
        note = "From Field › Drawings" + (" (received with %s)" % d["transmittal"] if d.get("transmittal") else "")
        rid = ins(c, "dm_revs", {"doc_id": did, "rev": rev, "file_id": d["file_id"], "status": st,
                                 "purpose": FLD_LABEL.get(d["status"] or "", d["status"]), "note": note,
                                 "uploaded_by": d["created_by"], "ts": d["ts"] or now()})
    ins(c, "pp_dwg_link", {"fld_id": d["id"], "doc_id": did, "rev_id": rid, "ts": now()})
    if d["current"]:
        if (d["status"] or "") != "superseded":
            upd(c, "dm_revs", rid, {"status": DM_OF_FLD.get(d["status"] or "", "draft")})
        _set_current(c, did, rid)
        upd(c, "dm_docs", did, {"title": d["title"] or number, "discipline": d["discipline"]})
    return did


def sync_all_drawings(c):
    if not (_has(c, "fld_drawings") and _has(c, "dm_docs")):
        return 0
    rows = q(c, "SELECT d.* FROM fld_drawings d LEFT JOIN pp_dwg_link k ON k.fld_id=d.id WHERE k.fld_id IS NULL ORDER BY d.id")
    for d in rows:
        sync_drawing(c, d)
    return len(rows)


def _w_drawing_save(orig):
    def drawing_save(c, u, a):
        res = orig(c, u, a)
        if getattr(_LOCAL, "from_dm", False):
            return res
        d = q1(c, "SELECT * FROM fld_drawings WHERE id=?", (int(res["id"]),))
        link = q1(c, "SELECT * FROM pp_dwg_link WHERE fld_id=?", (d["id"],))
        if link:
            # an edit of a row already in Document control
            ch = {}
            if d["file_id"] and d["file_id"] != val(c, "SELECT file_id FROM dm_revs WHERE id=?", (link["rev_id"],)):
                ch["file_id"] = d["file_id"]
            if d["current"] and (d["status"] or "") != "superseded":
                st = DM_OF_FLD.get(d["status"] or "", "draft")
                if val(c, "SELECT status FROM dm_revs WHERE id=?", (link["rev_id"],)) not in ("in_review",):
                    ch["status"] = st
            if ch:
                upd(c, "dm_revs", link["rev_id"], ch)
            if d["current"]:
                upd(c, "dm_docs", link["doc_id"], {"title": d["title"], "discipline": d["discipline"], "updated": now()})
        else:
            sync_drawing(c, d)
        return res
    return drawing_save


def drawing_from_dm(c, u, doc_id, rev_id):
    """A revision added in Document control to a drawing card becomes the current sheet in Field › Drawings."""
    if q1(c, "SELECT fld_id FROM pp_dwg_link WHERE rev_id=?", (rev_id,)):
        return None
    doc = q1(c, "SELECT * FROM dm_docs WHERE id=?", (doc_id,))
    rv = q1(c, "SELECT * FROM dm_revs WHERE id=?", (rev_id,))
    if not doc or not rv or not doc["project_id"]:
        return None
    if (doc["doc_type"] or "") != "DRG" and not q1(c, "SELECT fld_id FROM pp_dwg_link WHERE doc_id=?", (doc_id,)):
        return None
    prev = getattr(_LOCAL, "from_dm", False)
    _LOCAL.from_dm = True
    try:
        res = inv.FUNCS["fld.drawing_save"][0](c, u, {"row": {
            "project_id": doc["project_id"], "number": doc["doc_no"], "title": doc["title"], "discipline": doc["discipline"],
            "revision": rv["rev"], "rev_date": (rv["ts"] or today())[:10], "status": FLD_OF_DM.get(rv["status"], "for_approval"),
            "file_id": rv["file_id"], "remarks": "From Document control"}})
    finally:
        _LOCAL.from_dm = prev
    ins(c, "pp_dwg_link", {"fld_id": int(res["id"]), "doc_id": doc_id, "rev_id": rev_id, "ts": now()})
    return res["id"]


def _w_rev_add(orig):
    def rev_add(c, u, a):
        res = orig(c, u, a)
        drawing_from_dm(c, u, int(a["doc_id"]), int(res["id"]))
        return res
    return rev_add


def _w_doc_save(orig):
    def doc_save(c, u, a):
        res = orig(c, u, a)
        r = a.get("row") or {}
        if not r.get("id") and res.get("rev_id"):
            drawing_from_dm(c, u, int(res["id"]), int(res["rev_id"]))
        elif r.get("id"):
            # a change to a drawing card's title reaches its current sheet
            k = q1(c, "SELECT f.id FROM pp_dwg_link k JOIN fld_drawings f ON f.id=k.fld_id WHERE k.doc_id=? AND f.current=1", (int(r["id"]),))
            if k and r.get("title"):
                upd(c, "fld_drawings", k["id"], {"title": r["title"]})
        return res
    return doc_save


def _w_drawings(orig):
    def drawings(c, u, a):
        rows = orig(c, u, a)
        if isinstance(rows, list) and rows:
            m = {r["fld_id"]: r for r in q(c, "SELECT k.fld_id, d.id doc_id, d.doc_no FROM pp_dwg_link k JOIN dm_docs d ON d.id=k.doc_id "
                                              "WHERE d.project_id=?", (int(a.get("project_id") or 0),))}
            for r in rows:
                k = m.get(r.get("id"))
                r["dm_doc_id"], r["dm_doc_no"] = (k["doc_id"], k["doc_no"]) if k else (None, None)
        return rows
    return drawings


# ═════════════════════════════ 2. documents linked to money ═════════════════════════════
def rule_on(c, k):
    if k == "journal":
        return setting(c, "pp_need_journal") == "1" and _f(setting(c, "pp_need_journal_over")) > 0
    return setting(c, "pp_need_" + k) == "1"


def has_doc(c, ent, eid):
    if ent not in ENT or not eid:
        return False
    al = ENT[ent][2]
    ph = ",".join("?" * len(al))
    if val(c, "SELECT COUNT(*) FROM files WHERE entity IN (%s) AND entity_id=?" % ph, list(al) + [int(eid)]):
        return True
    if val(c, "SELECT COUNT(*) FROM pp_links WHERE entity=? AND entity_id=?", (ent, int(eid))):
        return True
    if _has(c, "dl_docs") and val(c, "SELECT COUNT(*) FROM dl_docs WHERE active=1 AND entity IN (%s) AND entity_id=?" % ph, list(al) + [int(eid)]):
        return True
    return False


def payment_documented(c, p):
    if has_doc(c, "payments", p["id"]):
        return True
    if _has(c, "fc_payreq") and val(c, "SELECT COUNT(*) FROM fc_payreq WHERE payment_id=?", (p["id"],)):
        return True
    al = q(c, "SELECT invoice_id FROM allocations WHERE payment_id=?", (p["id"],))
    return bool(al) and not _f(p.get("advance")) and all(has_doc(c, "invoices", x["invoice_id"]) for x in al)


def _record(c, ent, eid):
    t = ENT[ent][0]
    return q1(c, "SELECT * FROM %s WHERE id=?" % t, (int(eid),))


def _label(c, ent, eid):
    r = _record(c, ent, eid)
    if not r:
        return "%s #%s (deleted)" % (ENT[ent][1], eid)
    no = r.get(ENT[ent][3]) or ("draft #%s" % eid)
    extra = r.get("title") or r.get("party_inv_no") or r.get("narration") or ""
    return "%s %s%s" % (ENT[ent][1], no, (" · " + str(extra)[:60]) if extra else "")


def _needs(c, ent, r):
    """Whether this record needs a paper before it is posted, and why."""
    if not r:
        return None
    if ent == "invoices" and r.get("kind") == "purchase" and rule_on(c, "bill"):
        return "Supplier bills need the bill's scan or photo before posting."
    if ent == "payments" and r.get("kind") == "pay" and rule_on(c, "payment"):
        return "Payments need a paper (receipt, cheque copy) unless every bill they settle has one."
    if ent == "grn" and rule_on(c, "grn"):
        return "GRNs need the delivery challan before posting."
    if ent == "ipc" and rule_on(c, "ipc"):
        return "IPCs need the consultant's certificate before they are certified."
    if ent == "vouchers" and (r.get("source") or "manual") == "manual" and rule_on(c, "journal") and \
            _f(r.get("total")) + EPS >= _f(setting(c, "pp_need_journal_over")):
        return "Manual vouchers of %s or more need a supporting paper before posting." % _inr(setting(c, "pp_need_journal_over"))
    return None


@api("pp.papers")
def pp_papers(c, u, a):
    ent, eid = a.get("entity"), int(a.get("id") or 0)
    if ent not in ENT or not eid:
        raise ApiError("Unknown record.")
    of = None
    if ent == "vouchers":
        v = q1(c, "SELECT * FROM vouchers WHERE id=?", (eid,))
        if v and v["source"] in VSOURCE and v["source_id"]:
            ent, eid, of = VSOURCE[v["source"]], v["source_id"], v["source"]
    _need(u, ENT[ent][4], "view")
    al = ENT[ent][2]
    ph = ",".join("?" * len(al))
    files = q(c, "SELECT id, filename, caption, date, size, kind FROM files WHERE entity IN (%s) AND entity_id=? ORDER BY id" % ph,
              list(al) + [eid])
    links = q(c, "SELECT k.id, k.dl_id, k.note, k.ts, d.title, d.file_id, d.file_name, d.doc_number, d.revision, uu.name by_name "
                 "FROM pp_links k LEFT JOIN dl_docs d ON d.id=k.dl_id LEFT JOIN users uu ON uu.id=k.user_id "
                 "WHERE k.entity=? AND k.entity_id=? ORDER BY k.id", (ent, eid))
    r = _record(c, ent, eid)
    need = _needs(c, ent, r)
    ok = has_doc(c, ent, eid) or (ent == "payments" and r and payment_documented(c, r))
    return {"entity": ent, "id": eid, "label": _label(c, ent, eid), "of": of, "files": files, "links": links,
            "needs": need, "ok": ok, "status": (r or {}).get("status"),
            "can_edit": _right(u, ENT[ent][4], "edit") or _right(u, "project", "edit")}


def _check_dl(c, dl_id):
    d = q1(c, "SELECT * FROM dl_docs WHERE id=? AND active=1", (int(dl_id),)) if _has(c, "dl_docs") else None
    if not d:
        raise ApiError("That library document was not found.")
    return d


def link(c, u, dl_id, ent, eid, note=None):
    if ent not in ENT:
        raise ApiError("Unknown kind of record.")
    _check_dl(c, dl_id)
    if not _record(c, ent, eid):
        raise ApiError("%s not found." % ENT[ent][1])
    c.execute("INSERT OR IGNORE INTO pp_links(dl_id, entity, entity_id, note, user_id, ts) VALUES(?,?,?,?,?,?)",
              (int(dl_id), ent, int(eid), note, u["id"], now()))
    audit(c, u, "link", "pp_links", int(eid), {"dl_id": int(dl_id), "entity": ent})


@api("pp.link")
def pp_link(c, u, a):
    ent = a.get("entity")
    if ent not in ENT:
        raise ApiError("Choose the kind of record.")
    if not (_right(u, ENT[ent][4], "edit") or _right(u, "project", "edit")):
        raise ApiError("You do not have the right to link papers to this record.")
    eid = int(a.get("entity_id") or 0)
    if not eid and a.get("number"):
        t, _l, _al, col, _m = ENT[ent]
        hits = q(c, "SELECT id FROM %s WHERE UPPER(%s)=UPPER(?)" % (t, col), (str(a["number"]).strip(),))
        if not hits:
            raise ApiError("No %s numbered %s." % (ENT[ent][1].lower(), a["number"]))
        if len(hits) > 1:
            raise ApiError("More than one %s is numbered %s." % (ENT[ent][1].lower(), a["number"]))
        eid = hits[0]["id"]
    ids = a.get("dl_ids") or ([a["dl_id"]] if a.get("dl_id") else [])
    if not ids:
        raise ApiError("Choose the library document.")
    for d in ids:
        link(c, u, d, ent, eid, a.get("note"))
    return {"entity": ent, "entity_id": eid, "label": _label(c, ent, eid)}


@api("pp.unlink")
def pp_unlink(c, u, a):
    k = get(c, "pp_links", int(a["id"]), "Link")
    if not (_right(u, ENT.get(k["entity"], ("", "", (), "", "accounts"))[4], "edit") or _right(u, "project", "edit")):
        raise ApiError("You do not have the right to unlink papers from this record.")
    c.execute("DELETE FROM pp_links WHERE id=?", (k["id"],))
    audit(c, u, "unlink", "pp_links", k["entity_id"], k)
    return True


@api("pp.attach")
def pp_attach(c, u, a):
    """Files uploaded with no record yet (a payment not yet made) are placed on the record."""
    ent, eid = a.get("entity"), int(a.get("entity_id") or 0)
    if ent not in ENT or not _record(c, ent, eid):
        raise ApiError("Unknown record.")
    return {"placed": _place(c, u, a.get("file_ids") or [], ent, eid)}


def _place(c, u, file_ids, ent, eid):
    n = 0
    for fid in file_ids:
        f = q1(c, "SELECT * FROM files WHERE id=?", (int(fid),))
        if f and (not f.get("entity") or f["entity"] == "pp_pending") and not f.get("entity_id") and f["user_id"] == u["id"]:
            upd(c, "files", f["id"], {"entity": ent, "entity_id": eid})
            n += 1
    return n


@api("pp.links", "project", "view")
def pp_links_list(c, u, a):
    rows = q(c, "SELECT k.*, d.title, d.file_name, d.file_id, uu.name by_name FROM pp_links k LEFT JOIN dl_docs d ON d.id=k.dl_id "
                "LEFT JOIN users uu ON uu.id=k.user_id ORDER BY k.id DESC LIMIT 1000")
    out = []
    for r in rows:
        if r["entity"] in ENT and _right(u, ENT[r["entity"]][4], "view"):
            r["record"] = _label(c, r["entity"], r["entity_id"])
            r["kind"] = ENT[r["entity"]][1]
            out.append(r)
    return {"rows": out, "kinds": [[k, v[1]] for k, v in ENT.items()],
            "can_link": _right(u, "project", "edit") or _right(u, "accounts", "edit")}


@api("pp.find", "project", "view")
def pp_find(c, u, a):
    """Records of one kind whose number contains the text (for the link box)."""
    ent = a.get("entity")
    if ent not in ENT:
        raise ApiError("Choose the kind of record.")
    t, label, _al, col, mod = ENT[ent]
    if not _right(u, mod, "view"):
        return []
    rows = q(c, "SELECT id, %s no FROM %s WHERE %s LIKE ? ORDER BY id DESC LIMIT 20" % (col, t, col), ("%" + (a.get("q") or "") + "%",))
    return [{"id": r["id"], "no": r["no"], "label": _label(c, ent, r["id"])} for r in rows]


# ───────── the rules, at the moment of posting ─────────
def _refuse(what):
    raise ApiError(PAPERS + what + " Attach it (scan or photo), or link it from the Document library, then post again.")


def _w_invoice_post(orig):
    def invoice_post(c, u, a):
        r = q1(c, "SELECT * FROM invoices WHERE id=?", (int(a.get("id") or 0),))
        if r and r["status"] == "draft" and r["kind"] == "purchase" and rule_on(c, "bill") and not has_doc(c, "invoices", r["id"]):
            _refuse("this supplier bill has no copy of the bill.")
        return orig(c, u, a)
    return invoice_post


def _w_grn_post(orig):
    def grn_post(c, u, a):
        r = q1(c, "SELECT * FROM grn WHERE id=?", (int(a.get("id") or 0),))
        if r and r["status"] == "draft" and rule_on(c, "grn") and not has_doc(c, "grn", r["id"]):
            _refuse("this GRN has no delivery challan.")
        return orig(c, u, a)
    return grn_post


def _w_ipc_certify(orig):
    def ipc_certify(c, u, a):
        r = q1(c, "SELECT * FROM ipc WHERE id=?", (int(a.get("id") or 0),))
        if r and rule_on(c, "ipc") and not has_doc(c, "ipc", r["id"]):
            _refuse("this IPC has no copy of the certificate.")
        return orig(c, u, a)
    return ipc_certify


def _w_voucher_post(orig):
    def voucher_post(c, u, a):
        old = q1(c, "SELECT * FROM vouchers WHERE id=?", (int(a.get("id") or 0),))
        if old and old["status"] == "draft" and _needs(c, "vouchers", old) and not has_doc(c, "vouchers", old["id"]):
            _refuse("this voucher of %s has no supporting paper." % _inr(old["total"]))
        res = orig(c, u, a)
        nid = int(res["id"]) if isinstance(res, dict) and res.get("id") else None
        if old and nid and nid != old["id"]:
            # the draft is replaced by the posted voucher: its papers follow it
            c.execute("UPDATE files SET entity_id=? WHERE entity IN ('vouchers','voucher') AND entity_id=?", (nid, old["id"]))
            c.execute("UPDATE OR IGNORE pp_links SET entity_id=? WHERE entity='vouchers' AND entity_id=?", (nid, old["id"]))
        return res
    return voucher_post


def _from_payreq():
    try:
        import api_money as MN
        return bool(getattr(MN._LOCAL, "payreq", False))
    except Exception:
        return False


def _w_payment_create(orig):
    def payment_create(c, u, a):
        fids = [int(x) for x in (a.get("file_ids") or []) if str(x).strip().isdigit()]
        dls = [int(x) for x in (a.get("dl_ids") or []) if str(x).strip().isdigit()]
        if a.get("kind") == "pay" and rule_on(c, "payment") and not fids and not dls and not _from_payreq():
            al = [x for x in (a.get("allocations") or []) if _f(x.get("amount")) > 0]
            covered = bool(al) and not _f(a.get("advance")) and all(has_doc(c, "invoices", int(x["invoice_id"])) for x in al)
            if not covered:
                _refuse("this payment has no paper (receipt or cheque copy), and not every bill it pays has one.")
        res = orig(c, u, a)
        if isinstance(res, dict) and res.get("id"):
            _place(c, u, fids, "payments", int(res["id"]))
            for d in dls:
                link(c, u, d, "payments", int(res["id"]))
        return res
    return payment_create


@api("pp.settings")
def pp_settings(c, u, a):
    return {"rules": [{"key": k, "label": l, "on": rule_on(c, k) if k != "journal" else setting(c, "pp_need_journal") == "1",
                       "from": setting(c, "pp_need_from_" + k)} for k, l in RULES],
            "journal_over": _f(setting(c, "pp_need_journal_over")),
            "con_register": con_on(c), "con_from": setting(c, "pp_con_from"),
            "can_edit": _right(u, "accounts", "approve")}


@api("pp.settings_save", "accounts", "approve")
def pp_settings_save(c, u, a):
    before = pp_settings(c, u, {})
    for k, _l in RULES:
        if k in a:
            on = "1" if a[k] in (1, True, "1", "true", "on") else "0"
            if on == "1" and setting(c, "pp_need_" + k) != "1":
                _set(c, "pp_need_from_" + k, today())
            _set(c, "pp_need_" + k, on)
    if "journal_over" in a:
        _set(c, "pp_need_journal_over", r2(_f(a["journal_over"])))
    after = pp_settings(c, u, {})
    _log(c, u, "papers_rules", {"before": before["rules"], "after": after["rules"], "journal_over": after["journal_over"]})
    audit(c, u, "settings", "pp_rules", 0, {k: a.get(k) for k, _l in RULES})
    return after


# ───────── checks ─────────
def missing(c):
    """Posted records without a document, per kind."""
    out = {}
    if _has(c, "invoices"):
        out["bill"] = [r for r in q(c, "SELECT i.id, i.no, i.date, i.payable amount, p.name party, i.party_inv_no FROM invoices i "
                                        "LEFT JOIN parties p ON p.id=i.party_id WHERE i.kind='purchase' AND i.status='posted' ORDER BY i.date, i.id")
                       if not has_doc(c, "invoices", r["id"])]
    if _has(c, "payments"):
        out["payment"] = [r for r in q(c, "SELECT x.id, x.no, x.date, x.gross amount, x.advance, p.name party FROM payments x "
                                          "LEFT JOIN parties p ON p.id=x.party_id WHERE x.kind='pay' AND x.status='posted' ORDER BY x.date, x.id")
                          if not payment_documented(c, r)]
    if _has(c, "grn"):
        out["grn"] = [r for r in q(c, "SELECT g.id, g.no, g.date, NULL amount, p.name party FROM grn g LEFT JOIN parties p ON p.id=g.vendor_id "
                                      "WHERE g.status='posted' ORDER BY g.date, g.id") if not has_doc(c, "grn", r["id"])]
    if _has(c, "ipc"):
        out["ipc"] = [r for r in q(c, "SELECT i.id, i.no, i.date, i.net amount, NULL party FROM ipc i WHERE i.status IN ('certified','paid') "
                                      "ORDER BY i.date, i.id") if not has_doc(c, "ipc", r["id"])]
    over = _f(setting(c, "pp_need_journal_over")) or 100000
    out["journal"] = [r for r in q(c, "SELECT v.id, v.no, v.date, v.total amount, v.narration party FROM vouchers v WHERE v.source='manual' "
                                      "AND v.status='posted' AND v.total>=? ORDER BY v.date, v.id", (over - EPS,))
                      if not has_doc(c, "vouchers", r["id"])]
    return out


CHECK_NAMES = {"bill": "Posted supplier bills without the bill's copy", "payment": "Payments without a paper",
               "grn": "Posted GRNs without the delivery challan", "ipc": "Certified IPCs without the certificate",
               "journal": "Large manual vouchers without a supporting paper"}
CHECK_WHERE = {"bill": "Procurement › Invoices › the bill › Papers", "payment": "Accounts › Vouchers › the payment › Papers",
               "grn": "Store › GRN › Papers", "ipc": "Commercial › IPC › Documents", "journal": "Accounts › Vouchers › Papers"}


def checks(c):
    out = []
    m = missing(c)
    for k, rows in m.items():
        on = rule_on(c, k)
        since = setting(c, "pp_need_from_" + k) or ""
        bad = [r for r in rows if on and (r["date"] or "") >= since]
        items = [{"ref": r["no"], "date": r["date"], "amount": r.get("amount"), "detail": r.get("party") or ""} for r in rows]
        if on:
            ok = not bad
            detail = ("%d since %s (%d in all)" % (len(bad), since, len(rows))) if bad else (
                "None since %s%s" % (since, (" (%d earlier)" % len(rows)) if rows else ""))
        else:
            ok = True
            detail = ("Not required yet: %d posted without one" % len(rows)) if rows else "Not required yet; none missing"
        name = CHECK_NAMES[k] + (" (%s or more)" % _inr(_f(setting(c, "pp_need_journal_over")) or 100000) if k == "journal" else "")
        out.append({"area": "Documents", "check": name, "ok": ok, "severity": ("ok" if not rows else "info") if ok else "warn",
                    "detail": detail, "items": items[:50], "count": len(items), "fix": None if ok and not rows else CHECK_WHERE[k],
                    "amount": r2(sum(_f(r.get("amount")) for r in rows))})
    return out


def _w_fc_checks(orig):
    def fc_checks(c, u, a):
        res = orig(c, u, a)
        if isinstance(res, dict) and isinstance(res.get("checks"), list):
            res["checks"].extend(checks(c))
            if "ok" in res and isinstance(res.get("ok"), (int, bool)):
                res["ok"] = all(x["ok"] for x in res["checks"])
        return res
    return fc_checks


def _w_integrity(orig):
    def rep_integrity(c, u, a):
        res = orig(c, u, a)
        if isinstance(res, list):
            have = {x.get("check") for x in res}
            for x in checks(c):
                if x["check"] not in have:
                    res.append({"check": x["check"], "ok": x["ok"], "detail": x["detail"] + (
                        ": " + ", ".join(str(i.get("ref", "")) for i in x["items"][:8]) if x["items"] else "")})
        return res
    return rep_integrity


# ═════════════════════════════ 3. one contract register ═════════════════════════════
def con_on(c):
    return setting(c, "pp_con_register") == "1"


def client_contracts(c, pid):
    return q(c, "SELECT * FROM contracts WHERE project_id=? AND kind='client' AND COALESCE(status,'active')='active' ORDER BY id", (pid,))


def register_figures(c, pid):
    ks = client_contracts(c, pid) if _has(c, "contracts") else []
    if not ks:
        return None
    value = r2(sum(_f(k["value"]) for k in ks))
    starts = [k["start_date"] for k in ks if k["start_date"]]
    ends = [k["end_date"] for k in ks if k["end_date"]]
    ret = next((k["retention_pct"] for k in ks if k["retention_pct"] is not None), None)
    adv = [k["advance"] for k in ks if k["advance"] is not None]
    return {"contracts": [{"id": k["id"], "ref_no": k["ref_no"], "title": k["title"], "value": k["value"]} for k in ks],
            "contract_value": value, "start_date": min(starts) if starts else None, "end_date": max(ends) if ends else None,
            "retention_pct": ret, "advance_pct": r2(100.0 * sum(_f(x) for x in adv) / value) if adv and value else None}


PROJ_KEYS = ("contract_value", "start_date", "end_date", "retention_pct", "advance_pct")


def _proj_now(c, pid):
    p = q1(c, "SELECT * FROM projects WHERE id=?", (pid,)) or {}
    return {k: p.get(k) for k in PROJ_KEYS}


def _differs(a, b):
    if isinstance(a, (int, float)) or isinstance(b, (int, float)):
        return abs(_f(a) - _f(b)) > EPS
    return (a or "") != (b or "")


def push_to_project(c, u, pid, why):
    fig = register_figures(c, pid)
    if not fig:
        return None
    before = _proj_now(c, pid)
    ch = {k: fig[k] for k in PROJ_KEYS if fig.get(k) is not None and _differs(before.get(k), fig[k])}
    if ch:
        upd(c, "projects", pid, ch)
        _log(c, u, "project_from_contract", {"project_id": pid, "why": why, "before": before, "after": _proj_now(c, pid)})
    return ch


def copy_bonds(c, u, k):
    """A contract's bond and insurance go to Contract admin › Securities once, linked to the contract."""
    made = 0
    for what, kind, number, expiry in (("bond", "performance", k.get("bond_no"), k.get("bond_expiry")),
                                       ("insurance", "car", None, k.get("insurance_expiry"))):
        if not (number or expiry) or q1(c, "SELECT security_id FROM pp_con_sec WHERE contract_id=? AND what=?", (k["id"], what)):
            continue
        sid = ins(c, "ca_securities", {"project_id": k.get("project_id"), "contract_id": k["id"], "kind": kind, "number": number,
                                       "party_id": k.get("party_id"), "expiry_date": expiry, "status": "active", "history": "[]",
                                       "remarks": "Copied from Commercial › Contracts (%s)" % (k.get("ref_no") or k.get("title") or k["id"]),
                                       "created_by": u["id"] if u else None, "ts": now()})
        ins(c, "pp_con_sec", {"contract_id": k["id"], "what": what, "security_id": sid, "ts": now()})
        made += 1
    return made


def _w_con_save(orig):
    def con_save(c, u, a):
        r = a.get("row") or {}
        old = q1(c, "SELECT * FROM contracts WHERE id=?", (int(r["id"]),)) if r.get("id") else None
        if con_on(c) and old:
            r = dict(r)
            for k in ("bond_no", "bond_expiry", "insurance_expiry"):
                if k in r:
                    r[k] = old[k]          # kept in Contract admin › Securities now
            a = dict(a, row=r)
        res = orig(c, u, a)
        if con_on(c):
            k = q1(c, "SELECT * FROM contracts WHERE id=?", (int(res["id"]),))
            if not old:
                copy_bonds(c, u, k)
            for pid in {x for x in (k["project_id"], old and old["project_id"]) if x}:
                if (k["kind"] == "client") or (old and old["kind"] == "client"):
                    push_to_project(c, u, pid, "contract %s saved" % (k["ref_no"] or k["title"]))
            res = inv.FUNCS["con.get"][0](c, u, {"id": k["id"]})
        return res
    return con_save


def _w_con_delete(orig):
    def con_delete(c, u, a):
        k = q1(c, "SELECT * FROM contracts WHERE id=?", (int(a["id"]),))
        res = orig(c, u, a)
        if con_on(c) and k and k["kind"] == "client" and k["project_id"]:
            push_to_project(c, u, k["project_id"], "contract %s deleted" % (k["ref_no"] or k["title"]))
        return res
    return con_delete


def _w_con_get(orig):
    def con_get(c, u, a):
        k = orig(c, u, a)
        if isinstance(k, dict) and k.get("id") and _has(c, "ca_securities"):
            k["securities"] = q(c, "SELECT id, kind, number, issuer, amount, expiry_date, status FROM ca_securities WHERE contract_id=? "
                                   "ORDER BY expiry_date", (k["id"],))
            k["register_on"] = con_on(c)
            if _has(c, "sc_orders"):
                k["work_orders"] = q(c, "SELECT id, no, title, status, retention_pct, advance FROM sc_orders WHERE contract_id=? ORDER BY id", (k["id"],))
        return k
    return con_get


def _w_con_list(orig):
    def con_list(c, u, a):
        rows = orig(c, u, a)
        if con_on(c) and isinstance(rows, list) and _has(c, "ca_securities"):
            soon = val(c, "SELECT date('now', '+30 day')")
            t = today()
            for r in rows:
                fl = [x for x in (r.get("flags") or "").split("; ") if x and not x.startswith(("bond", "insurance"))]
                for s in q(c, "SELECT kind, number, expiry_date FROM ca_securities WHERE contract_id=? AND status IN ('active','extended','reduced') "
                              "AND expiry_date IS NOT NULL AND expiry_date<=?", (r["id"], soon)):
                    fl.append("%s %s %s %s" % ("insurance" if s["kind"] in ("car", "third_party", "workers", "vehicle", "professional") else "bond",
                                               s["number"] or "", "expired" if s["expiry_date"] < t else "expires", s["expiry_date"]))
                r["flags"] = "; ".join(fl)
        return rows
    return con_list


def _w_master_save(orig):
    def master_save(c, u, a):
        row = a.get("row") or {}
        if a.get("table") == "projects" and row.get("id") and con_on(c):
            fig = register_figures(c, int(row["id"]))
            if fig:
                cur = _proj_now(c, int(row["id"]))
                for k in ("contract_value", "start_date", "end_date"):
                    if k in row and fig.get(k) is not None and _differs(row.get(k) if k != "contract_value" else _f(row.get(k)), cur.get(k)):
                        ref = ", ".join((x["ref_no"] or x["title"] or "") for x in fig["contracts"])
                        raise ApiError("This project's contract value and dates are kept in Commercial › Contracts (%s). Change them there." % ref)
        return orig(c, u, a)
    return master_save


def _w_cr_get(orig):
    def cr_get(c, u, a):
        res = orig(c, u, a)
        if con_on(c) and isinstance(res, dict) and (res.get("project") or {}).get("id"):
            fig = register_figures(c, res["project"]["id"])
            if fig:
                if isinstance(res.get("contract"), dict):
                    res["contract"] = dict(res["contract"], price=fig["contract_value"])
                res["register"] = {"contract_value": fig["contract_value"], "contracts": fig["contracts"],
                                   "note": "Contract price from Commercial › Contracts"}
        return res
    return cr_get


def _w_cr_contract_save(orig):
    def cr_contract_save(c, u, a):
        if con_on(c) and isinstance(a.get("data"), dict):
            pid = int(a.get("project_id") or 0)
            fig = register_figures(c, pid) if pid else None
            if fig:
                a = dict(a, data=dict(a["data"], price=fig["contract_value"]))
        return orig(c, u, a)
    return cr_contract_save


def _w_sco_save(orig):
    def sco_save(c, u, a):
        if con_on(c):
            h = dict(a.get("header") or {})
            if not h.get("contract_id") and h.get("project_id") and h.get("party_id"):
                ks = q(c, "SELECT id FROM contracts WHERE project_id=? AND party_id=? AND kind='subcontract' AND COALESCE(status,'active')='active'",
                       (int(h["project_id"]), int(h["party_id"])))
                if len(ks) == 1:
                    h["contract_id"] = ks[0]["id"]
            if h.get("contract_id"):
                k = q1(c, "SELECT * FROM contracts WHERE id=?", (int(h["contract_id"]),))
                if k:
                    for src, dst in (("retention_pct", "retention_pct"), ("advance", "advance"), ("start_date", "start_date"), ("end_date", "end_date")):
                        if k[src] is not None and k[src] != "":
                            h[dst] = k[src]
            a = dict(a, header=h)
        return orig(c, u, a)
    return sco_save


def _w_sco_get(orig):
    def sco_get(c, u, a):
        o = orig(c, u, a)
        if isinstance(o, dict) and o.get("contract_id"):
            o["contract"] = q1(c, "SELECT id, ref_no, title, value, retention_pct, advance, start_date, end_date FROM contracts WHERE id=?",
                               (o["contract_id"],))
        return o
    return sco_get


def _w_fcc_summary(orig):
    def fcc_summary(c, u, a):
        res = orig(c, u, a)
        try:
            pr = ((res or {}).get("data") or {}).get("projects")
            if isinstance(pr, dict) and isinstance(pr.get("rows"), list):
                cv = {r["id"]: r for r in q(c, "SELECT id, code, contract_value FROM projects")}
                for r in pr["rows"]:
                    p = cv.get(r.get("project_id"))
                    if p:
                        r["contract_value"] = p["contract_value"]
                if con_on(c):
                    parts = ["%s %s" % (cv[r["project_id"]]["code"], _inr(cv[r["project_id"]]["contract_value"]))
                             for r in pr["rows"] if r.get("project_id") in cv and register_figures(c, r["project_id"])]
                    if parts:
                        pr["basis"] = (pr.get("basis") or "") + " Contract value from Commercial › Contracts: " + "; ".join(parts) + \
                            " (revenue above is the BOQ)."
        except Exception:
            pass
        return res
    return fcc_summary


@api("pp.con_overview", "commercial", "view")
def pp_con_overview(c, u, a):
    rows = []
    for p in q(c, "SELECT * FROM projects WHERE COALESCE(kind,'project') NOT IN ('trading','general') ORDER BY code"):
        fig = register_figures(c, p["id"])
        cur = {k: p.get(k) for k in PROJ_KEYS}
        diff = [k for k in PROJ_KEYS if fig and fig.get(k) is not None and _differs(cur.get(k), fig[k])]
        rows.append({"project_id": p["id"], "code": p["code"], "name": p["name"], "client": p.get("client"), "project": cur,
                     "register": fig, "differs": diff,
                     "status": "no client contract" if not fig else ("agrees" if not diff else "differs")})
    subs = q(c, "SELECT o.id, o.no, o.title, o.project_id, pr.code project, pa.name party, o.retention_pct, o.advance, o.contract_id, "
                "k.ref_no, k.title contract FROM sc_orders o LEFT JOIN projects pr ON pr.id=o.project_id LEFT JOIN parties pa ON pa.id=o.party_id "
                "LEFT JOIN contracts k ON k.id=o.contract_id ORDER BY o.id") if _has(c, "sc_orders") else []
    bonds = q(c, "SELECT id, ref_no, title, bond_no, bond_expiry, insurance_expiry FROM contracts WHERE COALESCE(bond_no,'')<>'' "
                 "OR bond_expiry IS NOT NULL OR insurance_expiry IS NOT NULL ORDER BY id")
    for b in bonds:
        b["in_securities"] = bool(q1(c, "SELECT 1 FROM pp_con_sec WHERE contract_id=?", (b["id"],)))
    log = q(c, "SELECT l.ts, l.what, l.detail, uu.name by_name FROM pp_log l LEFT JOIN users uu ON uu.id=l.user_id "
               "WHERE l.what IN ('con_register','project_from_contract','con_create') ORDER BY l.id DESC LIMIT 30")
    return {"on": con_on(c), "from": setting(c, "pp_con_from"), "rows": rows, "work_orders": subs, "bonds": bonds, "log": log,
            "can_edit": _right(u, "commercial", "edit"), "can_switch": _right(u, "commercial", "approve") or _right(u, "accounts", "approve")}


@api("pp.con_create_client", "commercial", "edit")
def pp_con_create_client(c, u, a):
    pids = [int(a["project_id"])] if a.get("project_id") else [r["id"] for r in q(c, "SELECT id FROM projects WHERE COALESCE(kind,'project') "
                                                                                     "NOT IN ('trading','general')")]
    made = []
    for pid in pids:
        if client_contracts(c, pid):
            continue
        p = q1(c, "SELECT * FROM projects WHERE id=?", (pid,))
        if not p or not _f(p.get("contract_value")):
            continue
        party = q1(c, "SELECT id FROM parties WHERE kind='client' AND LOWER(TRIM(name))=LOWER(TRIM(?))", (p.get("client") or "",))
        adv = r2(_f(p.get("advance_pct")) * _f(p["contract_value"]) / 100.0) if p.get("advance_pct") is not None else None
        kid = ins(c, "contracts", {"project_id": pid, "party_id": party["id"] if party else None, "kind": "client",
                                   "ref_no": None, "title": "Main contract - %s" % p["name"], "value": p["contract_value"],
                                   "start_date": p.get("start_date"), "end_date": p.get("end_date"),
                                   "retention_pct": p.get("retention_pct"), "advance": adv, "status": "active",
                                   "remarks": "Made from the project record by BuildCore 2.41", "created_by": u["id"], "ts": now()})
        audit(c, u, "create", "contracts", kid, {"from_project": pid})
        made.append({"project_id": pid, "contract_id": kid})
    _log(c, u, "con_create", {"made": made})
    return {"made": len(made), "contracts": made}


@api("pp.con_switch")
def pp_con_switch(c, u, a):
    if not (_right(u, "commercial", "approve") or _right(u, "accounts", "approve")):
        raise ApiError("Switching the contract register needs commercial or accounts approval rights.")
    on = a.get("on") in (1, True, "1", "true")
    before = pp_con_overview(c, u, {})
    _set(c, "pp_con_register", "1" if on else "0")
    pushed, bonds = {}, 0
    if on:
        _set(c, "pp_con_from", today())
        for r in before["rows"]:
            if r["register"]:
                ch = push_to_project(c, u, r["project_id"], "register switched on")
                if ch:
                    pushed[r["code"]] = ch
        for k in q(c, "SELECT * FROM contracts"):
            bonds += copy_bonds(c, u, k)
    _log(c, u, "con_register", {"on": on, "before": [{"code": r["code"], "project": r["project"], "register": r["register"] and {
        k: r["register"].get(k) for k in PROJ_KEYS}} for r in before["rows"]], "changed": pushed, "bonds_copied": bonds})
    audit(c, u, "settings", "pp_con_register", 0, {"on": on})
    return {"on": on, "changed": pushed, "bonds_copied": bonds}


# ═════════════════════════════ start-up ═════════════════════════════
def _default(c, key, new_value, old_value):
    if val(c, "SELECT COUNT(*) FROM settings WHERE key=?", (key,)):
        return
    used = val(c, "SELECT COUNT(*) FROM vouchers") if _has(c, "vouchers") else 0
    c.execute("INSERT OR IGNORE INTO settings(key, value) VALUES(?,?)", (key, old_value if used else new_value))


def init_papers(c):
    c.executescript(SCHEMA)
    for k, new in (("bill", "1"), ("payment", "1"), ("grn", "0"), ("ipc", "0"), ("journal", "1")):
        _default(c, "pp_need_" + k, new, "0")
        if setting(c, "pp_need_" + k) == "1" and not setting(c, "pp_need_from_" + k):
            _set(c, "pp_need_from_" + k, today())
    _default(c, "pp_need_journal_over", "100000", "100000")
    _default(c, "pp_con_register", "1", "0")
    if setting(c, "pp_con_register") == "1" and not setting(c, "pp_con_from"):
        _set(c, "pp_con_from", today())
    try:
        sync_all_drawings(c)
    except Exception as e:  # never stop start-up
        print("BuildCore 2.41: drawings not copied to Document control: %s" % e)
    c.commit()
    _wrap("fld.drawing_save", _w_drawing_save)
    _wrap("fld.drawings", _w_drawings)
    _wrap("dm.rev_add", _w_rev_add)
    _wrap("dm.doc_save", _w_doc_save)
    _wrap("invoice.post", _w_invoice_post)
    _wrap("grn.post", _w_grn_post)
    _wrap("ipc.certify", _w_ipc_certify)
    _wrap("voucher.post", _w_voucher_post)
    _wrap("payment.create", _w_payment_create)
    _wrap("fc.checks", _w_fc_checks)
    _wrap("rep.integrity", _w_integrity)
    _wrap("con.save", _w_con_save)
    _wrap("con.delete", _w_con_delete)
    _wrap("con.get", _w_con_get)
    _wrap("con.list", _w_con_list)
    _wrap("master.save", _w_master_save)
    _wrap("cr.get", _w_cr_get)
    _wrap("cr.contract_save", _w_cr_contract_save)
    _wrap("sco.save", _w_sco_save)
    _wrap("sco.get", _w_sco_get)
    _wrap("fcc.summary", _w_fcc_summary)
