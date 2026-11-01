"""
Document library (BuildCore 2.34), ported from the Document Manager tool SULAV sent.

One library that finds any document by any word: title, document number, revision, project, category, tags, file
name, or words inside the file itself. It covers
  1. every file BuildCore already holds (DPR photos, letter scans, drawings, document-control revisions, attachments
     on any record), catalogued automatically the first time the library opens and whenever new files arrive, and
  2. documents added straight to the library, one by one or a whole folder at a time.
Categories are detected from the file and folder names (BOQ, IPC, letter, drawing, report, MoM, .dwg ...) and can be
edited; a revision written in the file name ("Rev B", "Rev.02", "Revision 3") is filled in. Identical files (same
content) are found and skipped. Search understands words, "exact phrases", word starts, -excluded words and OR.

The text inside files is read in small steps (dl.index) so the engine is never held for long. Rights: the Project
module (view to search, edit to add and change, approve to remove and to edit categories); each user only sees the
projects assigned to them, attachments of modules their role cannot open, or confidential document-control files they
could not open before, stay hidden. New tables only (dl_categories, dl_docs, dl_versions, dl_fts); the files store is
not changed except that a removed file also leaves the library.
"""
import csv
import hashlib
import html
import io
import os
import re
import time
from datetime import date

import core
from core import ApiError, audit, can, ins, now, q, q1, today, upd, val
import api_inventory as inv
from api_inventory import api

VERSION = "2.34.0"
FLAG = "_bco234"

SCHEMA = """
CREATE TABLE IF NOT EXISTS dl_categories(id INTEGER PRIMARY KEY, name TEXT NOT NULL, keywords TEXT DEFAULT '',
  sort_order INTEGER DEFAULT 100, active INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS dl_docs(id INTEGER PRIMARY KEY, file_id INTEGER, title TEXT, doc_number TEXT DEFAULT '',
  revision TEXT DEFAULT '', project_id INTEGER, category_id INTEGER, doc_date TEXT, tags TEXT DEFAULT '',
  description TEXT DEFAULT '', file_name TEXT, ext TEXT DEFAULT '', size INTEGER DEFAULT 0, sha256 TEXT,
  text_status TEXT DEFAULT 'pending', text_chars INTEGER DEFAULT 0, source TEXT DEFAULT 'attachment', entity TEXT,
  entity_id INTEGER, folder_hint TEXT, active INTEGER DEFAULT 1, added_by INTEGER, added_at TEXT, updated_at TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS ix_dl_file ON dl_docs(file_id);
CREATE INDEX IF NOT EXISTS ix_dl_sha ON dl_docs(sha256);
CREATE INDEX IF NOT EXISTS ix_dl_proj ON dl_docs(project_id);
CREATE INDEX IF NOT EXISTS ix_dl_status ON dl_docs(text_status);
CREATE TABLE IF NOT EXISTS dl_versions(id INTEGER PRIMARY KEY, doc_id INTEGER, file_id INTEGER, revision TEXT,
  file_name TEXT, size INTEGER, sha256 TEXT, archived_at TEXT, archived_by INTEGER, note TEXT);
CREATE INDEX IF NOT EXISTS ix_dlv ON dl_versions(doc_id)
"""

# Seed categories with the words in file or folder names that point to them (from the Document Manager).
# Entries starting with "." are file extensions. Editable in the library.
DEFAULT_CATEGORIES = [
    ("Drawings", ".dwg, .dxf, .dgn, .dwf, drawing, drg, dwg, layout, cross section, x-section, "
                 "l-section, longitudinal section, elevation, detail, sheet"),
    ("Design Calculations", "calculation, calc, calcs, design of, hydraulic design, structural design, stability, analysis"),
    ("Design Reports", "report, feasibility, dpr, detailed project report, design report, study, inception"),
    ("Bills & Payments", "ipc, interim payment, invoice, running bill, ra bill, bill, payment, claim, variation"),
    ("Estimates & BOQ", "boq, bill of quantities, estimate, estimation, rate analysis, quantity, quantities, abstract of cost, cost"),
    ("Measurement Books", "mb, measurement, measurement book"),
    ("Contracts & Agreements", "contract, agreement, tender, bid, bidding, loa, letter of acceptance, ppa, mou"),
    ("Minutes of Meeting", "minutes, mom, meeting"),
    ("Correspondence", ".eml, .msg, letter, ltr, correspondence, email, mail, reply, request, notice, memo"),
    ("Specifications", "specification, specifications, spec, specs, technical specification"),
    ("Survey & Geology", "survey, topographic, topo, geology, geological, geotechnical, borehole, ert, seismic, hydrology"),
    ("Approvals & Permits", "approval, permit, license, licence, eia, iee, clearance, consent"),
    ("Photos & Site Records", ".jpg, .jpeg, .png, .heic, .bmp, .tif, .tiff, photo, photos, site visit, progress"),
    ("Other", ""),
]

TYPE_GROUPS = {
    "pdf": ("PDF", (".pdf",)),
    "word": ("Word", (".doc", ".docx", ".docm", ".dotx", ".odt", ".rtf", ".txt", ".md")),
    "excel": ("Excel", (".xls", ".xlsx", ".xlsm", ".xlsb", ".csv", ".tsv", ".ods")),
    "cad": ("CAD", (".dwg", ".dxf", ".dgn", ".dwf", ".dwfx")),
    "ppt": ("Slides", (".ppt", ".pptx", ".pptm", ".odp")),
    "image": ("Image", (".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".gif", ".heic", ".webp")),
    "email": ("Email", (".eml", ".msg")),
}
TYPE_FILTER_LABELS = [("pdf", "PDF"), ("word", "Word & text"), ("excel", "Excel & CSV"), ("cad", "Drawings (CAD)"),
                      ("ppt", "PowerPoint"), ("image", "Images & photos"), ("email", "Emails"), ("other", "Other")]
SOURCES = [("library", "Added to the library"), ("attachment", "Attached to a record"), ("dm", "Document control")]

FTS_COLUMNS = ("title", "doc_number", "tags", "file_name", "project", "category", "description", "body")
FTS_WEIGHTS = "10.0, 8.0, 6.0, 5.0, 2.0, 2.0, 3.0, 1.0"
_FTS = {}                       # data file -> True when the search index is FTS5

# what module a record's attachments belong to (the user must be able to view that module to see the file)
ENTITY_MODULE = {
    "vouchers": "accounts", "invoices": "accounts", "payments": "accounts", "receipts": "accounts", "fc_payreq": "accounts",
    "bank_lines": "accounts", "ca_letters": "commercial", "ca_securities": "commercial", "ai_doc": "commercial",
    "ipc": "commercial", "variations": "commercial", "contracts": "commercial", "events": "commercial",
    "measurements": "commercial", "bids": "commercial", "cr_claims": "commercial", "pr": "procurement", "po": "procurement",
    "purchase_invoices": "procurement", "quotations": "procurement", "grn": "inventory", "issues": "inventory",
    "mrq": "inventory", "transfers": "inventory", "returns": "inventory", "stock_counts": "inventory",
    "asset_cases": "assets", "asset_disposals": "assets", "equipment": "equipment", "equipment_acq": "equipment",
    "work_orders": "equipment", "logbooks": "equipment", "qa_tests": "quality", "ncr": "quality",
}
ENTITY_LABEL = {"dpr": "DPR", "ca_letters": "Letter", "ca_securities": "Bond / insurance", "ai_doc": "Contract document (AI)",
                "fld_drawings": "Drawing", "fld_issues": "Issue", "fld_rfis": "RFI", "cm_posts": "Discussion",
                "activities": "Activity", "boq_items": "BOQ item", "ipc": "IPC", "asset_cases": "Asset case",
                "asset_disposals": "Asset disposal", "equipment_acq": "Equipment purchase", "dl_doc": "Library",
                "cr_claims": "Claim"}

NO_PROJECT = "No project"


def init_doclib(c):
    for st in SCHEMA.strip().split(";"):
        if st.strip():
            c.execute(st)
    _fts_ready(c)
    if not val(c, "SELECT COUNT(*) FROM dl_categories", (), 0):
        for i, (name, kw) in enumerate(DEFAULT_CATEGORIES):
            ins(c, "dl_categories", {"name": name, "keywords": kw, "sort_order": (i + 1) * 10, "active": 1})
    _hook_files_delete()
    _hook_search()


def _key(c):
    try:
        return c.execute("PRAGMA database_list").fetchone()[2] or id(c)
    except Exception:
        return id(c)


def _fts_ready(c):
    k = _key(c)
    if k in _FTS:
        return _FTS[k]
    row = c.execute("SELECT sql FROM sqlite_master WHERE name='dl_fts'").fetchone()
    if row is None:
        cols = ", ".join(FTS_COLUMNS)
        ok = False
        for tok in ("unicode61 remove_diacritics 2", "unicode61"):
            try:
                c.execute("CREATE VIRTUAL TABLE dl_fts USING fts5(%s, tokenize='%s', prefix='2 3')" % (cols, tok))
                ok = True
                break
            except Exception:
                continue
        if not ok:      # no FTS5 in this Python: a plain table, searched with LIKE
            c.execute("CREATE TABLE dl_fts (doc_id INTEGER PRIMARY KEY, " + ", ".join("%s TEXT" % x for x in FTS_COLUMNS) + ")")
        _FTS[k] = ok
    else:
        _FTS[k] = "fts5" in (row[0] or "").lower()
    return _FTS[k]


def _ensure(c):
    if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='dl_docs'").fetchone():
        init_doclib(c)
    return _fts_ready(c)


# ───────────────────────── small helpers (from the Document Manager) ─────────────────────────
def _files_dir():
    import api_project
    return api_project.FILES_DIR


def _file_path(f):
    return os.path.join(_files_dir(), os.path.basename(f["stored"] or ""))


def file_hash(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def normalize_tags(s):
    out, seen = [], set()
    for t in re.split(r"[,;\n]+", s or ""):
        t = t.strip().lstrip("#").strip()
        if t and t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    return ", ".join(out)


def tag_list(s):
    return [t for t in (x.strip() for x in (s or "").split(",")) if t]


def valid_date(s):
    s = (s or "").strip()[:10]
    try:
        return date.fromisoformat(s).isoformat() if s else None
    except ValueError:
        return None


_REV_RE = re.compile(r"(?:^|[\s_\-.(\[])rev(?:ision)?[\s_\-.]*([0-9]{1,2}|[A-Za-z]{1,2})(?=$|[\s_\-.)\]])", re.I)


def guess_revision(file_name):
    m = _REV_RE.search(os.path.splitext(os.path.basename(file_name or ""))[0])
    return m.group(1).upper() if m else ""


def title_from_filename(file_name):
    stem = os.path.splitext(os.path.basename(file_name or ""))[0].replace("_", " ")
    return re.sub(r"\s+", " ", stem).strip() or file_name


def type_of(ext):
    ext = (ext or "").lower()
    for key, (label, exts) in TYPE_GROUPS.items():
        if ext in exts:
            return key
    return "other"


def type_label(ext):
    if (ext or "").lower() in (".txt", ".md"):
        return "Text"
    key = type_of(ext)
    if key == "other":
        return (ext or "file").lstrip(".").upper()[:5] or "FILE"
    return TYPE_GROUPS[key][0]


def _norm_words(s):
    return " " + re.sub(r"[\s_\-.()\[\],&+]+", " ", (s or "").lower()).strip() + " "


def load_categories(c):
    cats = []
    for r in q(c, "SELECT id, name, keywords FROM dl_categories WHERE active=1 ORDER BY sort_order, name"):
        words, exts = [], set()
        for k in (r["keywords"] or "").split(","):
            k = k.strip().lower()
            if not k:
                continue
            if k.startswith("."):
                exts.add(k)
            else:
                words.append(_norm_words(k).strip())
        cats.append({"id": r["id"], "name": r["name"], "words": words, "exts": exts})
    return cats


_WORD_ENDINGS = ("", "s", "es", "d", "ed", "ing", "ings", "ion", "ions")


def _kw_hit(kw, norm, tokens):
    """A keyword matches a whole word or its plural/-ing/-ed form ("drawing" -> "drawings", not "contract" -> "contractor")."""
    if " " in kw:
        return " %s " % kw in norm or " %ss " % kw in norm
    return any(t[len(kw):] in _WORD_ENDINGS for t in tokens if t.startswith(kw))


def guess_category(cats, file_name, folder_hint=""):
    """The file name first, then a decisive file type (CAD, e-mail), then the folder names, then a weak file type
    (an image could be a photo or a scanned drawing)."""
    ext = os.path.splitext(file_name or "")[1].lower()
    weak = ext in TYPE_GROUPS["image"][1] or ext == ".pdf"
    name_norm = _norm_words(os.path.splitext(os.path.basename(file_name or ""))[0])
    name_tokens = name_norm.split()
    for ct in cats:
        if any(_kw_hit(k, name_norm, name_tokens) for k in ct["words"]):
            return ct["id"]
    if not weak:
        for ct in cats:
            if ext in ct["exts"]:
                return ct["id"]
    if folder_hint:
        folder_norm = _norm_words(folder_hint)
        folder_tokens = folder_norm.split()
        for ct in cats:
            if any(_kw_hit(k, folder_norm, folder_tokens) for k in ct["words"]):
                return ct["id"]
    for ct in cats:
        if ext in ct["exts"]:
            return ct["id"]
    for ct in cats:
        if ct["name"].lower() == "other":
            return ct["id"]
    return None


def _allowed(c, u):
    try:
        import api_workspace as W
        return W.allowed_projects(c, u)
    except Exception:
        return None


def _hidden_modules(u):
    return {m for m in set(ENTITY_MODULE.values()) if not can(u, m, "view")}


# ───────────────────────── the search index ─────────────────────────
def _body(c, doc_id):
    r = q1(c, "SELECT body FROM dl_fts WHERE %s=?" % ("rowid" if _fts_ready(c) else "doc_id"), (doc_id,))
    return (r or {}).get("body") or ""


def fts_write(c, doc_id, body=None):
    """(Re)write the search-index row of a document. body=None keeps the stored text."""
    fts = _fts_ready(c)
    key = "rowid" if fts else "doc_id"
    if body is None:
        body = _body(c, doc_id)
    c.execute("DELETE FROM dl_fts WHERE %s=?" % key, (doc_id,))
    d = q1(c, "SELECT d.*, p.code pcode, p.name pname, k.name cname FROM dl_docs d LEFT JOIN projects p ON p.id=d.project_id "
              "LEFT JOIN dl_categories k ON k.id=d.category_id WHERE d.id=?", (doc_id,))
    if not d:
        return
    project = " ".join(x for x in (d.get("pname"), d.get("pcode")) if x)
    c.execute("INSERT INTO dl_fts(%s, %s) VALUES(?,?,?,?,?,?,?,?,?)" % (key, ", ".join(FTS_COLUMNS)),
              (doc_id, d["title"] or "", d["doc_number"] or "", d["tags"] or "", d["file_name"] or "", project,
               d.get("cname") or "", d["description"] or "", body or ""))


def _fts_delete(c, doc_id):
    c.execute("DELETE FROM dl_fts WHERE %s=?" % ("rowid" if _fts_ready(c) else "doc_id"), (doc_id,))


# ───────────────────────── cataloguing BuildCore's own files ─────────────────────────
def sync(c, limit=5000):
    """Give every file BuildCore holds (not yet in the library) a library card. Fast: no file is read here."""
    _ensure(c)
    rows = q(c, "SELECT f.* FROM files f LEFT JOIN dl_docs d ON d.file_id=f.id WHERE d.id IS NULL AND COALESCE(f.entity,'') NOT IN ('dl_doc','dl_version') "
                "ORDER BY f.id LIMIT ?", (limit,))
    if not rows:
        return 0
    cats = load_categories(c)
    dm = {r["file_id"]: r for r in q(c, "SELECT r.file_id, r.rev, d.doc_no, d.title, d.project_id FROM dm_revs r JOIN dm_docs d ON d.id=r.doc_id "
                                       "WHERE r.file_id IS NOT NULL")} if _has(c, "dm_revs") else {}
    t = now()
    for f in rows:
        name = f["filename"] or "file"
        hit = dm.get(f["id"])
        title = (hit and hit["title"]) or (f.get("caption") or "").strip() or title_from_filename(name)
        hint = " ".join(x for x in (ENTITY_LABEL.get(f.get("entity") or "", f.get("entity") or ""), f.get("caption") or "") if x)
        ins(c, "dl_docs", {"file_id": f["id"], "title": title[:300], "doc_number": (hit and hit["doc_no"]) or "",
                           "revision": (hit and hit["rev"]) or guess_revision(name), "project_id": f.get("project_id") or (hit and hit["project_id"]),
                           "category_id": guess_category(cats, name, hint), "doc_date": valid_date(f.get("date")) or (f.get("ts") or "")[:10] or None,
                           "tags": "", "description": "", "file_name": name, "ext": os.path.splitext(name)[1].lower()[:12],
                           "size": f.get("size") or 0, "text_status": "pending", "source": "dm" if hit else "attachment",
                           "entity": f.get("entity"), "entity_id": f.get("entity_id"), "active": 1, "added_by": f.get("user_id"),
                           "added_at": f.get("ts") or t, "updated_at": t})
        fts_write(c, c.execute("SELECT last_insert_rowid()").fetchone()[0], "")
    return len(rows)


def _has(c, t):
    return bool(c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (t,)).fetchone())


def index_pending(c, budget=3.0, limit=200, ids=None):
    """Read the text of documents waiting to be read, for at most `budget` seconds. Returns (done, left)."""
    import doclib_extract as X
    _ensure(c)
    t0 = time.time()
    done = 0
    if ids:
        marks = ",".join("?" * len(ids))
        rows = q(c, "SELECT d.id, d.file_id, f.stored, f.filename FROM dl_docs d LEFT JOIN files f ON f.id=d.file_id "
                    "WHERE d.id IN (%s)" % marks, list(ids))
    else:
        rows = q(c, "SELECT d.id, d.file_id, f.stored, f.filename FROM dl_docs d LEFT JOIN files f ON f.id=d.file_id "
                    "WHERE d.text_status='pending' ORDER BY d.id LIMIT ?", (limit,))
    for r in rows:
        if done and time.time() - t0 > budget:
            break
        if not r.get("stored"):
            upd(c, "dl_docs", r["id"], {"text_status": "missing"})
            done += 1
            continue
        path = _file_path(r)
        if not os.path.isfile(path):
            upd(c, "dl_docs", r["id"], {"text_status": "missing"})
            done += 1
            continue
        try:
            sha = file_hash(path)
            size = os.path.getsize(path)
        except OSError:
            upd(c, "dl_docs", r["id"], {"text_status": "missing"})
            done += 1
            continue
        # read by the original file name's extension (the stored name is a random one)
        text, status = _extract_as(X, path, os.path.splitext(r["filename"] or "")[1].lower())
        upd(c, "dl_docs", r["id"], {"sha256": sha, "size": size, "text_status": status, "text_chars": len(text)})
        fts_write(c, r["id"], text)
        done += 1
    left = val(c, "SELECT COUNT(*) FROM dl_docs WHERE text_status='pending'", (), 0)
    return done, left


def _extract_as(X, path, ext):
    fn = X.HANDLERS.get(ext)
    if fn is None:
        return "", "unsupported"
    try:
        from pathlib import Path
        text = X._clean(fn(Path(path)))
    except Exception:
        return "", "error"
    return text, ("ok" if text else "empty")


# ───────────────────────── search (from the Document Manager) ─────────────────────────
_TERM_RE = re.compile(r'(-)?"([^"]*)"?|(\S+)')
_SPLIT_WORDS = re.compile(r"[^\wऀ-ॿ]+")


def build_fts_expr(text):
    pos, neg = [], []
    for m in _TERM_RE.finditer(text or ""):
        neg_flag, phrase, word = m.groups()
        if phrase is not None:
            t, prefix = phrase, False
        else:
            if word.upper() == "OR":
                if pos and pos[-1] != "OR":
                    pos.append("OR")
                continue
            if word.startswith("-") and len(word) > 1:
                neg_flag, word = "-", word[1:]
            t, prefix = word, True
        if not any(ch.isalnum() for ch in t):
            continue
        token = '"' + t.replace('"', '""') + '"' + ("*" if prefix else "")
        (neg if neg_flag else pos).append(token)
    while pos and pos[-1] == "OR":
        pos.pop()
    if pos and pos[0] == "OR":
        pos.pop(0)
    if not pos:
        return None
    expr = " ".join(pos)
    if neg:
        expr = "(%s) NOT (%s)" % (expr, " OR ".join(neg))
    return expr


def _simple_fts_expr(text):
    words = [w for w in _SPLIT_WORDS.split(text or "") if w]
    return " ".join('"%s"*' % w for w in words) or None


def query_terms(text, include_negative=False):
    pos, neg = [], []
    for m in _TERM_RE.finditer(text or ""):
        neg_flag, phrase, word = m.groups()
        if word is not None:
            if word.upper() == "OR":
                continue
            if word.startswith("-") and len(word) > 1:
                neg_flag, word = "-", word[1:]
        t = phrase if phrase is not None else word
        for w in _SPLIT_WORDS.split(t or ""):
            if len(w) >= 2:
                (neg if neg_flag else pos).append(w)
    return (pos, neg) if include_negative else pos


def _py_snippet(body, terms, width=110):
    if not body or not terms:
        return ""
    low = body.lower()
    hits = [low.find(t.lower()) for t in terms]
    hits = [x for x in hits if x >= 0]
    if not hits:
        return ""
    start = max(0, min(hits) - width)
    piece = body[start:start + width * 2 + 40]
    return ("… " if start else "") + piece + " …"


def _mark(text, terms):
    """[(text, marked?)] pieces, so the screen can highlight without trusting HTML from the engine."""
    text = text or ""
    if not terms:
        return [[text, 0]]
    pat = re.compile("(" + "|".join(re.escape(t) for t in sorted(set(terms), key=len, reverse=True)) + ")", re.I)
    out, last = [], 0
    for m in pat.finditer(text):
        if m.start() > last:
            out.append([text[last:m.start()], 0])
        out.append([m.group(), 1])
        last = m.end()
    if last < len(text):
        out.append([text[last:], 0])
    return out


def _filters(c, u, a):
    where, args = ["d.active=1" if not a.get("removed") else "d.active=0"], []
    allow = _allowed(c, u)
    if allow is not None:
        ids = sorted(allow)
        where.append("(d.project_id IS NULL OR d.project_id IN (%s))" % (",".join(str(int(x)) for x in ids) or "0"))
    hidden = _hidden_modules(u)
    if hidden:
        ents = [e for e, m in ENTITY_MODULE.items() if m in hidden]
        where.append("COALESCE(d.entity,'') NOT IN (%s)" % ",".join("?" * len(ents)))
        args.extend(ents)
    if not can(u, "project", "approve") and _has(c, "dm_docs"):
        where.append("NOT EXISTS (SELECT 1 FROM dm_revs rr JOIN dm_docs dd ON dd.id=rr.doc_id WHERE rr.file_id=d.file_id "
                     "AND dd.confidential=1 AND COALESCE(dd.created_by,0)<>?)")
        args.append(u["id"])
    project = a.get("project_id")
    if project == "none":
        where.append("d.project_id IS NULL")
    elif project not in (None, "", 0, "0"):
        where.append("d.project_id=?")
        args.append(int(project))
    category = a.get("category_id")
    if category == "none":
        where.append("d.category_id IS NULL")
    elif category not in (None, "", 0, "0"):
        where.append("d.category_id=?")
        args.append(int(category))
    t = a.get("type")
    if t in TYPE_GROUPS:
        exts = TYPE_GROUPS[t][1]
        where.append("d.ext IN (%s)" % ",".join("?" * len(exts)))
        args.extend(exts)
    elif t == "other":
        exts = [e for _, (_, es) in TYPE_GROUPS.items() for e in es]
        where.append("d.ext NOT IN (%s)" % ",".join("?" * len(exts)))
        args.extend(exts)
    if valid_date(a.get("date_from")):
        where.append("d.doc_date>=?")
        args.append(valid_date(a["date_from"]))
    if valid_date(a.get("date_to")):
        where.append("d.doc_date<=?")
        args.append(valid_date(a["date_to"]))
    tag = (a.get("tag") or "").strip().lower()
    if tag:
        where.append("(',' || REPLACE(LOWER(d.tags), ', ', ',') || ',') LIKE ?")
        args.append("%," + tag + ",%")
    src = a.get("source")
    if src in ("library", "attachment", "dm"):
        where.append("d.source=?")
        args.append(src)
    if a.get("text_status"):
        where.append("d.text_status=?")
        args.append(a["text_status"])
    if not a.get("old") and _has(c, "dm_revs"):
        # earlier revisions of a controlled document are kept but hidden unless asked for
        where.append("NOT EXISTS (SELECT 1 FROM dm_revs rr JOIN dm_docs dd ON dd.id=rr.doc_id WHERE rr.file_id=d.file_id "
                     "AND dd.current_rev_id IS NOT NULL AND dd.current_rev_id<>rr.id)")
    return where, args


_ORDER = {
    "newest": "d.doc_date DESC, d.id DESC",
    "oldest": "d.doc_date ASC, d.id ASC",
    "title": "d.title COLLATE NOCASE ASC",
    "added": "d.added_at DESC, d.id DESC",
}


def search(c, u, a, page=1, per_page=50):
    fts = _ensure(c)
    text = (a.get("q") or "").strip()
    sort = a.get("sort") or ""
    where, args = _filters(c, u, a)
    terms = query_terms(text)
    out = {"rows": [], "total": 0, "error": "", "terms": terms}
    joins = "LEFT JOIN projects p ON p.id=d.project_id LEFT JOIN dl_categories k ON k.id=d.category_id"
    cols = "d.*, p.code project_code, p.name project_name, k.name category_name"
    limit = "" if per_page is None else " LIMIT %d OFFSET %d" % (int(per_page), int((max(int(page or 1), 1) - 1) * per_page))

    def run(sql_from, sql_where, sql_args, order, extra=""):
        w = (" WHERE " + " AND ".join(sql_where)) if sql_where else ""
        total = val(c, "SELECT COUNT(*) FROM %s%s" % (sql_from, w), sql_args, 0)
        rows = q(c, "SELECT %s%s FROM %s%s ORDER BY %s%s" % (cols, extra, sql_from, w, order, limit), sql_args)
        return total, rows

    expr = build_fts_expr(text) if text else None
    if expr and fts:
        sql_from = "dl_fts JOIN dl_docs d ON d.id=dl_fts.rowid " + joins
        extra = (", snippet(dl_fts, 7, char(57344), char(57345), ' … ', 22) AS snip, bm25(dl_fts, %s) AS score" % FTS_WEIGHTS)
        order = _ORDER.get(sort, "score")
        try:
            total, rows = run(sql_from, ["dl_fts MATCH ?"] + where, [expr] + args, order, extra)
        except Exception:
            try:
                total, rows = run(sql_from, ["dl_fts MATCH ?"] + where, [_simple_fts_expr(text)] + args, order, extra)
            except Exception as e:
                out["error"] = "Could not understand that search (%s). Try plain words." % e
                return out
    elif expr:      # no FTS5: plain LIKE search
        pos, neg = query_terms(text, include_negative=True)
        fields = ["d.title", "d.doc_number", "d.tags", "d.file_name", "d.description", "IFNULL(p.name,'')", "IFNULL(p.code,'')",
                  "IFNULL(k.name,'')", "dl_fts.body"]
        w, ag = list(where), list(args)
        for t, negate in [(t, False) for t in pos] + [(t, True) for t in neg]:
            like = "%" + t.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            w.append(("NOT " if negate else "") + "(" + " OR ".join("%s LIKE ? ESCAPE '\\'" % f for f in fields) + ")")
            ag.extend([like] * len(fields))
        total, rows = run("dl_docs d JOIN dl_fts ON dl_fts.doc_id=d.id " + joins, w, ag, _ORDER.get(sort, _ORDER["newest"]),
                          ", dl_fts.body AS body")
    else:
        total, rows = run("dl_docs d " + joins, where, args, _ORDER.get(sort, _ORDER["newest"]))
    for d in rows:
        snip = []
        if "snip" in d:
            s = d.pop("snip") or ""
            if "" in s:
                for part in re.split("(.*?)", s):
                    if part.startswith(""):
                        snip.append([part.strip(""), 1])
                    elif part:
                        snip.append([part, 0])
        elif "body" in d:
            b = d.pop("body")
            snip = _mark(_py_snippet(b, terms), terms) if terms else []
        d.pop("score", None)
        d["snippet"] = snip
        d["title_marked"] = _mark(d["title"], terms)
        d["type"] = type_of(d["ext"])
        d["type_label"] = type_label(d["ext"])
        d["tag_list"] = tag_list(d["tags"])
        d["where"] = ENTITY_LABEL.get(d.get("entity") or "", (d.get("entity") or "").replace("_", " ")) if d["source"] != "library" else ""
    out["rows"] = rows
    out["total"] = total
    return out


def _doc(c, u, did):
    _ensure(c)
    a = {"old": 1}
    where, args = _filters(c, u, a)
    where = [w for w in where if not w.startswith("d.active")] or ["1=1"]
    r = q1(c, "SELECT d.*, p.code project_code, p.name project_name, k.name category_name FROM dl_docs d LEFT JOIN projects p ON p.id=d.project_id "
              "LEFT JOIN dl_categories k ON k.id=d.category_id WHERE d.id=? AND " + " AND ".join(where), [int(did)] + args)
    if not r:
        raise ApiError("Document not found, or it belongs to a project or module you cannot open.")
    return r


# ───────────────────────── engine actions ─────────────────────────
@api("dl.meta", "project", "view")
def dl_meta(c, u, a):
    fts = _ensure(c)
    added = sync(c)
    import doclib_extract as X
    allow = _allowed(c, u)
    projects = [p for p in q(c, "SELECT id, code, name FROM projects ORDER BY code") if allow is None or p["id"] in allow]
    cats = q(c, "SELECT k.*, (SELECT COUNT(*) FROM dl_docs d WHERE d.category_id=k.id AND d.active=1) n FROM dl_categories k "
                "WHERE k.active=1 ORDER BY k.sort_order, k.name")
    st = q1(c, "SELECT COUNT(*) n, IFNULL(SUM(size),0) size, SUM(text_status='ok') texted, SUM(text_status='pending') pending, "
               "SUM(text_status='missing') missing FROM dl_docs WHERE active=1") or {}
    return {"version": VERSION, "fts": bool(fts), "categories": cats, "projects": projects, "types": TYPE_FILTER_LABELS,
            "sources": SOURCES, "readable": X.readable_types(), "capabilities": X.capabilities(), "catalogued_now": added,
            "stats": {"total": st.get("n") or 0, "size": st.get("size") or 0, "texted": st.get("texted") or 0,
                      "pending": st.get("pending") or 0, "missing": st.get("missing") or 0},
            "can_edit": can(u, "project", "edit"), "can_approve": can(u, "project", "approve")}


@api("dl.search", "project", "view")
def dl_search(c, u, a):
    per = min(int(a.get("per_page") or 50), 200)
    return search(c, u, a, page=int(a.get("page") or 1), per_page=per)


@api("dl.index", "project", "view")
def dl_index(c, u, a):
    """Read the text of waiting documents for a few seconds; the screen calls again while some are left."""
    _ensure(c)
    sync(c)
    done, left = index_pending(c, budget=float(a.get("budget") or 3.0))
    return {"done": done, "left": left}


@api("dl.get", "project", "view")
def dl_get(c, u, a):
    d = _doc(c, u, a["id"])
    d["type_label"] = type_label(d["ext"])
    d["tag_list"] = tag_list(d["tags"])
    body = _body(c, d["id"])
    d["text_excerpt"] = body[:4000]
    d["text_more"] = max(0, len(body) - 4000)
    d["versions"] = q(c, "SELECT v.*, uu.name by_name FROM dl_versions v LEFT JOIN users uu ON uu.id=v.archived_by WHERE v.doc_id=? ORDER BY v.id DESC",
                      (d["id"],))
    dup = []
    if d.get("sha256"):
        where, args = _filters(c, u, {"old": 1})
        dup = q(c, "SELECT d.id, d.title, d.file_name, d.project_id, p.code project_code, d.source FROM dl_docs d LEFT JOIN projects p ON p.id=d.project_id "
                   "WHERE d.sha256=? AND d.id<>? AND " + " AND ".join(where), [d["sha256"], d["id"]] + args)
    d["duplicates"] = dup
    link = None
    if d.get("entity") and d.get("entity_id") and d["entity"] not in ("dl_doc", "dl_version"):
        link = {"label": ENTITY_LABEL.get(d["entity"], d["entity"].replace("_", " ")), "entity": d["entity"], "id": d["entity_id"]}
        if d["entity"] == "ca_letters":
            link["href"] = "#/ca/letters?id=%d" % d["entity_id"]
        elif d["entity"] == "dpr":
            link["href"] = "#/p/dpr?id=%d" % d["entity_id"]
        elif d["entity"] == "cr_claims":
            link["href"] = "#/cr?tab=events&ev=%d" % d["entity_id"]
    if _has(c, "dm_revs"):
        r = q1(c, "SELECT r.id rev_id, r.rev, r.status, d.id doc_id, d.doc_no, d.current_rev_id FROM dm_revs r JOIN dm_docs d ON d.id=r.doc_id WHERE r.file_id=?",
               (d["file_id"],))
        if r:
            link = {"label": "Document control %s rev %s%s" % (r["doc_no"], r["rev"], "" if r["current_rev_id"] == r["rev_id"] else " (superseded)"),
                    "href": "#/dm?doc=%d" % r["doc_id"]}
    d["link"] = link
    return d


def _place_file(c, u, fid, project_id, entity_id):
    upd(c, "files", fid, {"entity": "dl_doc", "entity_id": entity_id, "project_id": project_id})


@api("dl.add", "project", "edit")
def dl_add(c, u, a):
    """A file uploaded to /api/upload goes into the library. Same content already there = not added again."""
    _ensure(c)
    fid = int(a.get("file_id") or 0)
    f = q1(c, "SELECT * FROM files WHERE id=?", (fid,))
    if not f:
        raise ApiError("Upload the file first.")
    if val(c, "SELECT id FROM dl_docs WHERE file_id=?", (fid,), None):
        raise ApiError("This file is already in the library.")
    path = _file_path(f)
    if not os.path.isfile(path):
        raise ApiError("The uploaded file is missing from the data folder.")
    sha = file_hash(path)
    size = os.path.getsize(path)
    pid = int(a["project_id"]) if a.get("project_id") not in (None, "", 0, "0") else None
    if a.get("skip_duplicates", 1):
        dup = q1(c, "SELECT id, title FROM dl_docs WHERE sha256=? AND size=? AND active=1 LIMIT 1", (sha, size))
        if dup:
            # the copy just uploaded for the library is not kept
            if (f.get("entity") or "") in ("", "dl_doc") and not f.get("entity_id"):
                c.execute("DELETE FROM files WHERE id=?", (fid,))
                try:
                    os.remove(path)
                except OSError:
                    pass
            return {"status": "duplicate", "id": dup["id"], "title": dup["title"]}
    name = f["filename"] or "file"
    hint = a.get("folder_hint") or ""
    cid = a.get("category_id")
    if cid in (None, "", 0, "0"):
        cid = guess_category(load_categories(c), name, hint) if a.get("auto_category", 1) else None
    else:
        cid = int(cid)
    rev = a.get("revision")
    if rev in (None, ""):
        rev = guess_revision(name)
    t = now()
    did = ins(c, "dl_docs", {"file_id": fid, "title": ((a.get("title") or "").strip() or title_from_filename(name))[:300],
                             "doc_number": (a.get("doc_number") or "").strip(), "revision": (rev or "").strip(), "project_id": pid,
                             "category_id": cid, "doc_date": valid_date(a.get("doc_date")) or valid_date(f.get("date")) or today(),
                             "tags": normalize_tags(a.get("tags")), "description": (a.get("description") or "").strip(), "file_name": name,
                             "ext": os.path.splitext(name)[1].lower()[:12], "size": size, "sha256": sha, "text_status": "pending",
                             "source": "library", "entity": "dl_doc", "folder_hint": hint[:300] or None, "active": 1,
                             "added_by": u["id"], "added_at": t, "updated_at": t})
    _place_file(c, u, fid, pid, did)
    upd(c, "dl_docs", did, {"entity_id": did})
    fts_write(c, did, "")
    audit(c, u, "create", "dl_docs", did, {"file": name, "project_id": pid})
    return {"status": "added", "id": did}


EDITABLE = ("title", "doc_number", "revision", "project_id", "category_id", "doc_date", "tags", "description")


def _clean_fields(d, a):
    out = {}
    for k in EDITABLE:
        if k not in a:
            continue
        v = a[k]
        if k in ("project_id", "category_id"):
            v = int(v) if v not in (None, "", 0, "0") else None
        elif k == "doc_date":
            v = valid_date(v)
        elif k == "tags":
            v = normalize_tags(v)
        else:
            v = (v or "").strip()
            if k == "title" and not v:
                raise ApiError("Give the document a title.")
        out[k] = v
    if "project_id" in out and d["source"] != "library" and out["project_id"] != d["project_id"]:
        raise ApiError("This file is attached to a record; it stays in that record's project.")
    return out


def _check_project(c, u, pid):
    allow = _allowed(c, u)
    if pid and allow is not None and pid not in allow:
        raise ApiError("PROJECT_DENIED: that project is not assigned to you.")


@api("dl.update", "project", "edit")
def dl_update(c, u, a):
    d = _doc(c, u, a["id"])
    sets = _clean_fields(d, a.get("row") or a)
    if not sets:
        return {"id": d["id"]}
    _check_project(c, u, sets.get("project_id"))
    sets["updated_at"] = now()
    upd(c, "dl_docs", d["id"], sets)
    if "project_id" in sets and d["source"] == "library":
        upd(c, "files", d["file_id"], {"project_id": sets["project_id"]})
    fts_write(c, d["id"])
    audit(c, u, "save", "dl_docs", d["id"], {k: v for k, v in sets.items() if k != "updated_at"})
    return {"id": d["id"]}


@api("dl.bulk", "project", "edit")
def dl_bulk(c, u, a):
    ids = [int(x) for x in (a.get("ids") or []) if str(x).strip().isdigit()]
    if not ids:
        raise ApiError("Tick the documents first.")
    act = a.get("action")
    n = skipped = 0
    for i in ids:
        d = _doc(c, u, i)
        if act == "project":
            pid = int(a["project_id"]) if a.get("project_id") not in (None, "", 0, "0") else None
            _check_project(c, u, pid)
            if d["source"] != "library":
                skipped += 1
                continue
            upd(c, "dl_docs", i, {"project_id": pid, "updated_at": now()})
            upd(c, "files", d["file_id"], {"project_id": pid})
        elif act == "category":
            cid = int(a["category_id"]) if a.get("category_id") not in (None, "", 0, "0") else None
            upd(c, "dl_docs", i, {"category_id": cid, "updated_at": now()})
        elif act == "tags":
            upd(c, "dl_docs", i, {"tags": normalize_tags((d["tags"] or "") + ", " + (a.get("tags") or "")), "updated_at": now()})
        elif act in ("remove", "restore"):
            if not can(u, "project", "approve"):
                raise ApiError("Removing documents from the library needs the Project approve right.")
            upd(c, "dl_docs", i, {"active": 0 if act == "remove" else 1, "updated_at": now()})
        else:
            raise ApiError("Unknown action.")
        fts_write(c, i)
        n += 1
    audit(c, u, "bulk_" + str(act), "dl_docs", None, {"ids": ids[:200], "done": n, "skipped": skipped})
    return {"done": n, "skipped": skipped}


@api("dl.remove", "project", "approve")
def dl_remove(c, u, a):
    """Take a document out of the library. Nothing is deleted: the file and its card stay and can be brought back."""
    d = _doc(c, u, a["id"])
    upd(c, "dl_docs", d["id"], {"active": 0 if not a.get("restore") else 1, "updated_at": now()})
    audit(c, u, "restore" if a.get("restore") else "remove", "dl_docs", d["id"], {"title": d["title"]})
    return {"id": d["id"]}


@api("dl.revision", "project", "edit")
def dl_revision(c, u, a):
    """Replace a library document's file with a newer revision; the earlier file is kept under Earlier files."""
    d = _doc(c, u, a["id"])
    if d["source"] != "library":
        raise ApiError("This file belongs to a record or to Document control. Add the new revision there.")
    fid = int(a.get("file_id") or 0)
    f = q1(c, "SELECT * FROM files WHERE id=?", (fid,))
    if not f:
        raise ApiError("Upload the new file first.")
    path = _file_path(f)
    if not os.path.isfile(path):
        raise ApiError("The uploaded file is missing from the data folder.")
    ins(c, "dl_versions", {"doc_id": d["id"], "file_id": d["file_id"], "revision": d["revision"], "file_name": d["file_name"],
                           "size": d["size"], "sha256": d["sha256"], "archived_at": now(), "archived_by": u["id"],
                           "note": (a.get("note") or "").strip()})
    name = f["filename"] or "file"
    rev = (a.get("revision") or "").strip() or guess_revision(name) or d["revision"]
    upd(c, "files", d["file_id"], {"entity": "dl_version", "entity_id": d["id"]})
    upd(c, "dl_docs", d["id"], {"file_id": fid, "file_name": name, "ext": os.path.splitext(name)[1].lower()[:12],
                                "size": os.path.getsize(path), "sha256": file_hash(path), "text_status": "pending", "text_chars": 0,
                                "revision": rev, "updated_at": now()})
    _place_file(c, u, fid, d["project_id"], d["id"])
    fts_write(c, d["id"], "")
    audit(c, u, "revision", "dl_docs", d["id"], {"revision": rev, "file": name})
    return {"id": d["id"], "revision": rev}


@api("dl.reindex", "project", "edit")
def dl_reindex(c, u, a):
    """Read the text of these documents (or every document) again."""
    _ensure(c)
    if a.get("ids"):
        ids = [int(x) for x in a["ids"]]
        for i in ids:
            _doc(c, u, i)
        c.execute("UPDATE dl_docs SET text_status='pending' WHERE id IN (%s)" % ",".join("?" * len(ids)), ids)
        return {"pending": len(ids)}
    if not can(u, "project", "approve"):
        raise ApiError("Reading every document again needs the Project approve right.")
    c.execute("UPDATE dl_docs SET text_status='pending'")
    return {"pending": val(c, "SELECT COUNT(*) FROM dl_docs", (), 0)}


@api("dl.check", "project", "view")
def dl_check(c, u, a):
    """Look for library cards whose file is no longer in the data folder."""
    _ensure(c)
    n_missing = 0
    for r in q(c, "SELECT d.id, d.text_status, f.stored FROM dl_docs d LEFT JOIN files f ON f.id=d.file_id"):
        gone = not r.get("stored") or not os.path.isfile(os.path.join(_files_dir(), os.path.basename(r["stored"])))
        if gone and r["text_status"] != "missing":
            upd(c, "dl_docs", r["id"], {"text_status": "missing"})
        if gone:
            n_missing += 1
        elif r["text_status"] == "missing":
            upd(c, "dl_docs", r["id"], {"text_status": "pending"})
    return {"missing": n_missing, "catalogued": sync(c)}


@api("dl.categories", "project", "view")
def dl_categories(c, u, a):
    _ensure(c)
    return q(c, "SELECT k.*, (SELECT COUNT(*) FROM dl_docs d WHERE d.category_id=k.id AND d.active=1) n FROM dl_categories k "
                "WHERE k.active=1 ORDER BY k.sort_order, k.name")


@api("dl.category_save", "project", "approve")
def dl_category_save(c, u, a):
    _ensure(c)
    r = a.get("row") or a
    name = re.sub(r"\s+", " ", (r.get("name") or "").strip())[:80]
    if not name:
        raise ApiError("Give the category a name.")
    kw = ", ".join(k.strip() for k in re.split(r"[,\n]+", r.get("keywords") or "") if k.strip())
    so = int(r.get("sort_order") or 100)
    other = val(c, "SELECT id FROM dl_categories WHERE LOWER(name)=LOWER(?) AND active=1 AND id<>?", (name, int(r.get("id") or 0)), None)
    if other:
        raise ApiError("There is already a category called %s." % name)
    if r.get("id"):
        upd(c, "dl_categories", int(r["id"]), {"name": name, "keywords": kw, "sort_order": so})
        for (i,) in c.execute("SELECT id FROM dl_docs WHERE category_id=?", (int(r["id"]),)).fetchall():
            fts_write(c, i)
        return {"id": int(r["id"])}
    return {"id": ins(c, "dl_categories", {"name": name, "keywords": kw, "sort_order": so, "active": 1})}


@api("dl.category_delete", "project", "approve")
def dl_category_delete(c, u, a):
    _ensure(c)
    cid = int(a["id"])
    other = val(c, "SELECT id FROM dl_categories WHERE LOWER(name)='other' AND active=1 AND id<>?", (cid,), None)
    ids = [r[0] for r in c.execute("SELECT id FROM dl_docs WHERE category_id=?", (cid,)).fetchall()]
    c.execute("UPDATE dl_docs SET category_id=? WHERE category_id=?", (other, cid))
    upd(c, "dl_categories", cid, {"active": 0})
    for i in ids:
        fts_write(c, i)
    return {"moved": len(ids)}


@api("dl.recategorise", "project", "approve")
def dl_recategorise(c, u, a):
    """Detect the category again from the file and folder names (only documents still in Other or with none)."""
    _ensure(c)
    cats = load_categories(c)
    other = val(c, "SELECT id FROM dl_categories WHERE LOWER(name)='other' AND active=1", (), None)
    n = 0
    for d in q(c, "SELECT id, file_name, folder_hint, entity, category_id FROM dl_docs WHERE category_id IS NULL OR category_id=?", (other or -1,)):
        hint = d.get("folder_hint") or ENTITY_LABEL.get(d.get("entity") or "", "")
        cid = guess_category(cats, d["file_name"], hint)
        if cid and cid != d["category_id"]:
            upd(c, "dl_docs", d["id"], {"category_id": cid})
            fts_write(c, d["id"])
            n += 1
    return {"changed": n}


@api("dl.export_csv", "project", "view")
def dl_export_csv(c, u, a):
    res = search(c, u, a, per_page=None)
    if res["error"]:
        raise ApiError(res["error"])
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["ID", "Title", "Document no.", "Revision", "Project", "Category", "Date", "Tags", "Description", "File name", "Type",
                "Size (bytes)", "Attached to", "Text read", "Added"])
    for d in res["rows"]:
        w.writerow([d["id"], d["title"], d["doc_number"], d["revision"], d.get("project_code") or "", d.get("category_name") or "",
                    d["doc_date"] or "", d["tags"], d["description"], d["file_name"], d["ext"], d["size"], d.get("where") or "",
                    d["text_status"], (d["added_at"] or "")[:10]])
    return {"filename": "document_library_%s.csv" % today(), "csv": "﻿" + buf.getvalue(), "rows": len(res["rows"])}


# ───────────────────────── hooks into the existing engine ─────────────────────────
def _hook_files_delete():
    """A file deleted from a record also leaves the library (its card and search text)."""
    cur = inv.FUNCS.get("files.delete")
    if not cur or getattr(cur[0], FLAG, False):
        return
    orig = cur[0]

    def files_delete(c, u, a, _orig=orig):
        r = _orig(c, u, a)
        try:
            for (did,) in c.execute("SELECT id FROM dl_docs WHERE file_id=?", (int(a["id"]),)).fetchall():
                _fts_delete(c, did)
                c.execute("DELETE FROM dl_docs WHERE id=?", (did,))
        except Exception:
            pass
        return r
    setattr(files_delete, FLAG, True)
    inv.FUNCS["files.delete"] = (files_delete,) + tuple(cur[1:])


def _hook_search():
    try:
        import api_project as P
    except Exception:
        return
    if any(e.get("table") == "dl_docs" for e in P.SEARCH):
        return
    add = [P.S("Document library", "project", "dl_docs", "COALESCE(NULLIF(doc_number,'')||' ','')||title",
               ["@(source='library' AND (COALESCE(title,'') LIKE ? OR COALESCE(doc_number,'') LIKE ? OR COALESCE(tags,'') LIKE ? "
                "OR COALESCE(file_name,'') LIKE ? OR COALESCE(description,'') LIKE ?))"], "#/dl?doc={id}",
               "COALESCE(file_name,'')||CASE WHEN COALESCE(revision,'')<>'' THEN ' · rev '||revision ELSE '' END", "project_id", "doc_date")]
    P.SEARCH.extend(add)
    for e in add:
        P.SEARCH_BY_GROUP[e["group"]] = e


for _n in ("dl_meta", "dl_search", "dl_index", "dl_get", "dl_add", "dl_update", "dl_bulk", "dl_remove", "dl_revision", "dl_reindex",
           "dl_check", "dl_categories", "dl_category_save", "dl_category_delete", "dl_recategorise", "dl_export_csv"):
    setattr(globals()[_n], FLAG, True)
