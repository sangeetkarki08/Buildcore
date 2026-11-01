"""
Contract administration, communication and document control (BuildCore 2.16).

What the big systems do (Oracle Aconex mail & document registers, Procore Correspondence, Autodesk Docs reviews and
transmittals), kept short for Nepali sites and offices:

  Contract administration
    * Correspondence register - every letter in and out, our number made by BuildCore, their reference, reply-by date,
      who must act, the letter it answers, the clause it relies on; average reply days per party.
    * Notices and time bars - clause library (FIDIC 1999 and 2017 time limits as starters; add your own contract's
      clauses), running deadlines started from an event or a letter, closed by the notice letter, late ones flagged.
    * Bonds, guarantees and insurance - performance security, advance payment guarantee, retention, CAR / third party /
      workers insurance with expiry warnings, extended / released history.
    * Contract administration dashboard - replies due, time bars running, securities expiring, event notices,
      variations waiting, contract register items; plus letter drafts made from the record.
  Communication
    * Discussions on a project or on any record, @username mentions, notifications (bell and inbox), distribution
      lists and a project directory of people outside BuildCore.
  Document control
    * Folders per project, document numbers made from a pattern, revisions with files, review and approval
      (codes A / B / C / D, parallel or one after another), transmittals with acknowledgement, register export.

Nothing is ever deleted: letters are voided, documents withdrawn, revisions superseded.
"""
import base64
import json
import re
from datetime import date, timedelta

from core import ApiError, audit, can, ins, next_no, now, num, q, q1, r2, today, upd, val
from api_inventory import FUNCS, api

VERSION = "2.16.0"

SCHEMA = """
CREATE TABLE IF NOT EXISTS ca_letters(id INTEGER PRIMARY KEY, project_id INTEGER, contract_id INTEGER, direction TEXT,
  our_no TEXT, their_ref TEXT, date TEXT, received_on TEXT, party_id INTEGER, from_name TEXT, to_name TEXT, subject TEXT,
  category TEXT, clause TEXT, summary TEXT, body TEXT, reply_needed INTEGER DEFAULT 0, reply_by TEXT, in_reply_to INTEGER,
  replied_by INTEGER, status TEXT DEFAULT 'open', priority TEXT DEFAULT 'normal', assigned_to INTEGER, cc TEXT,
  list_id INTEGER, event_id INTEGER, variation_id INTEGER, timebar_id INTEGER, created_by INTEGER, ts TEXT, closed_on TEXT);
CREATE INDEX IF NOT EXISTS ix_cal ON ca_letters(project_id, direction, status);
CREATE TABLE IF NOT EXISTS ca_clauses(id INTEGER PRIMARY KEY, project_id INTEGER, form TEXT, clause TEXT, title TEXT,
  party TEXT, trigger TEXT, days INTEGER, follow_title TEXT, follow_days INTEGER, consequence TEXT, system INTEGER DEFAULT 0,
  active INTEGER DEFAULT 1, ts TEXT);
CREATE TABLE IF NOT EXISTS ca_timebars(id INTEGER PRIMARY KEY, project_id INTEGER, clause_id INTEGER, clause TEXT, title TEXT,
  party TEXT, trigger_date TEXT, due_date TEXT, status TEXT DEFAULT 'running', done_date TEXT, letter_id INTEGER,
  event_id INTEGER, parent_id INTEGER, notes TEXT, created_by INTEGER, ts TEXT);
CREATE INDEX IF NOT EXISTS ix_catb ON ca_timebars(project_id, status);
CREATE TABLE IF NOT EXISTS ca_securities(id INTEGER PRIMARY KEY, project_id INTEGER, contract_id INTEGER, kind TEXT,
  number TEXT, issuer TEXT, beneficiary TEXT, party_id INTEGER, amount REAL, currency TEXT DEFAULT 'NPR', issue_date TEXT,
  expiry_date TEXT, claim_until TEXT, status TEXT DEFAULT 'active', released_on TEXT, history TEXT, remarks TEXT,
  created_by INTEGER, ts TEXT);
CREATE TABLE IF NOT EXISTS cm_threads(id INTEGER PRIMARY KEY, project_id INTEGER, title TEXT, entity TEXT, entity_id INTEGER,
  kind TEXT DEFAULT 'discussion', pinned INTEGER DEFAULT 0, closed INTEGER DEFAULT 0, created_by INTEGER, ts TEXT, last_ts TEXT,
  posts INTEGER DEFAULT 0);
CREATE INDEX IF NOT EXISTS ix_cmt ON cm_threads(project_id, last_ts);
CREATE TABLE IF NOT EXISTS cm_posts(id INTEGER PRIMARY KEY, thread_id INTEGER, user_id INTEGER, body TEXT, ts TEXT, mentions TEXT);
CREATE INDEX IF NOT EXISTS ix_cmp ON cm_posts(thread_id);
CREATE TABLE IF NOT EXISTS cm_reads(thread_id INTEGER, user_id INTEGER, last_post_id INTEGER, PRIMARY KEY(thread_id, user_id));
CREATE TABLE IF NOT EXISTS cm_notes(id INTEGER PRIMARY KEY, user_id INTEGER, kind TEXT, title TEXT, body TEXT, link TEXT,
  project_id INTEGER, by_user INTEGER, ts TEXT, read_at TEXT);
CREATE INDEX IF NOT EXISTS ix_cmn ON cm_notes(user_id, read_at);
CREATE TABLE IF NOT EXISTS cm_lists(id INTEGER PRIMARY KEY, project_id INTEGER, name TEXT, members TEXT, active INTEGER DEFAULT 1,
  created_by INTEGER, ts TEXT);
CREATE TABLE IF NOT EXISTS cm_contacts(id INTEGER PRIMARY KEY, project_id INTEGER, name TEXT, org TEXT, role TEXT, phone TEXT,
  email TEXT, party_id INTEGER, notes TEXT, active INTEGER DEFAULT 1, ts TEXT);
CREATE TABLE IF NOT EXISTS dm_folders(id INTEGER PRIMARY KEY, project_id INTEGER, parent_id INTEGER, name TEXT, sort INTEGER,
  active INTEGER DEFAULT 1, ts TEXT);
CREATE TABLE IF NOT EXISTS dm_settings(project_id INTEGER PRIMARY KEY, pattern TEXT, org TEXT);
CREATE TABLE IF NOT EXISTS dm_docs(id INTEGER PRIMARY KEY, project_id INTEGER, folder_id INTEGER, doc_no TEXT, title TEXT,
  discipline TEXT, doc_type TEXT, originator TEXT, status TEXT DEFAULT 'draft', current_rev TEXT, current_rev_id INTEGER,
  confidential INTEGER DEFAULT 0, tags TEXT, active INTEGER DEFAULT 1, created_by INTEGER, ts TEXT, updated TEXT);
CREATE INDEX IF NOT EXISTS ix_dmd ON dm_docs(project_id, folder_id);
CREATE TABLE IF NOT EXISTS dm_revs(id INTEGER PRIMARY KEY, doc_id INTEGER, rev TEXT, file_id INTEGER, status TEXT DEFAULT 'draft',
  purpose TEXT, note TEXT, uploaded_by INTEGER, ts TEXT, review_due TEXT, review_mode TEXT, decided_on TEXT, result TEXT);
CREATE INDEX IF NOT EXISTS ix_dmr ON dm_revs(doc_id);
CREATE TABLE IF NOT EXISTS dm_reviews(id INTEGER PRIMARY KEY, rev_id INTEGER, doc_id INTEGER, step INTEGER, reviewer_id INTEGER,
  due_date TEXT, status TEXT DEFAULT 'pending', decision TEXT, comment TEXT, decided_on TEXT, ts TEXT);
CREATE INDEX IF NOT EXISTS ix_dmrv ON dm_reviews(reviewer_id, status);
CREATE TABLE IF NOT EXISTS dm_transmittals(id INTEGER PRIMARY KEY, project_id INTEGER, no TEXT, date TEXT, party_id INTEGER,
  to_name TEXT, attention TEXT, list_id INTEGER, purpose TEXT, subject TEXT, response_due TEXT, remarks TEXT,
  status TEXT DEFAULT 'draft', sent_on TEXT, ack_on TEXT, ack_by TEXT, response TEXT, letter_id INTEGER, created_by INTEGER, ts TEXT);
CREATE TABLE IF NOT EXISTS dm_trans_items(id INTEGER PRIMARY KEY, transmittal_id INTEGER, doc_id INTEGER, rev_id INTEGER,
  copies INTEGER DEFAULT 1, format TEXT DEFAULT 'PDF', note TEXT)
"""

LETTER_CATS = [("general", "General"), ("instruction", "Instruction"), ("notice", "Notice"), ("claim", "Claim"),
               ("eot", "Extension of time"), ("variation", "Variation"), ("payment", "Payment"), ("rfi", "Request for information"),
               ("submittal", "Submittal / approval"), ("warning", "Warning / non-compliance"), ("minutes", "Minutes"),
               ("handover", "Completion / handover"), ("other", "Other")]
LETTER_STATUS = [("open", "Open - action needed"), ("replied", "Replied"), ("info", "For information"), ("closed", "Closed"), ("void", "Void")]
SEC_KINDS = [("performance", "Performance security / bond"), ("advance", "Advance payment guarantee"), ("retention", "Retention money guarantee"),
             ("bid", "Bid security"), ("mobilisation", "Mobilisation advance guarantee"), ("car", "Contractor's all risk (CAR) insurance"),
             ("third_party", "Third party insurance"), ("workers", "Workers / employees accident insurance"), ("vehicle", "Vehicle & plant insurance"),
             ("professional", "Professional indemnity"), ("other", "Other")]
SEC_STATUS = [("active", "Active"), ("extended", "Extended"), ("reduced", "Reduced"), ("released", "Released / returned"),
              ("expired", "Expired"), ("encashed", "Encashed / claimed")]
DOC_TYPES = [("DRG", "Drawing"), ("SPC", "Specification"), ("BOQ", "BOQ / estimate"), ("RPT", "Report"), ("CAL", "Calculation / design"),
             ("MS", "Method statement"), ("MAT", "Material approval"), ("PRG", "Programme / schedule"), ("MOM", "Minutes"),
             ("LTR", "Letter"), ("CER", "Certificate / test"), ("CON", "Contract document"), ("PHO", "Photo set"), ("OTH", "Other")]
DISC_CODES = {"Civil": "CIV", "Structural": "STR", "Architectural": "ARC", "Hydro-mechanical": "HM", "Electro-mechanical": "EM",
              "Electrical": "ELE", "Plumbing": "PLB", "Mechanical": "MEC", "Geotechnical": "GEO", "Survey": "SUR", "Road": "RD",
              "General": "GEN", "Other": "GEN"}
REV_STATUS = [("draft", "Draft / work in progress"), ("for_info", "Shared for information"), ("in_review", "In review"),
              ("approved", "Approved (A)"), ("approved_comments", "Approved with comments (B)"), ("revise", "Revise and resubmit (C)"),
              ("rejected", "Rejected (D)"), ("superseded", "Superseded"), ("withdrawn", "Withdrawn")]
DECISIONS = [("A", "A - Approved"), ("B", "B - Approved with comments"), ("C", "C - Revise and resubmit"), ("D", "D - Rejected")]
TR_PURPOSE = [("for_information", "For information"), ("for_review", "For review / comment"), ("for_approval", "For approval"),
              ("for_construction", "For construction"), ("for_tender", "For tender"), ("as_built", "As built"), ("for_record", "For record")]
DEFAULT_FOLDERS = ["01 Contract & agreement", "02 Drawings", "03 Specifications & BOQ", "04 Correspondence", "05 Reports",
                   "06 Submittals & approvals", "07 Quality - tests & inspections", "08 Minutes of meeting", "09 Photos",
                   "10 As-built & handover"]

FIDIC_NOTE = "Starter time limit from the published form - check your contract's Particular Conditions, which often change it."
CLAUSE_LIB = [
    ("FIDIC 1999 Red Book", "4.2", "Performance Security delivered", "Contractor", "receiving the Letter of Acceptance", 28, None, None),
    ("FIDIC 1999 Red Book", "8.1", "Commencement Date (latest)", "Employer / Engineer", "the Contractor receiving the Letter of Acceptance", 42, None, None),
    ("FIDIC 1999 Red Book", "8.3", "Detailed time programme", "Contractor", "receiving the notice of the Commencement Date", 28, None, None),
    ("FIDIC 1999 Red Book", "4.21", "Monthly progress report", "Contractor", "the last day of the month reported", 7, None, None),
    ("FIDIC 1999 Red Book", "14.6", "Interim Payment Certificate issued", "Engineer", "receiving the Statement and supporting documents", 28, None, None),
    ("FIDIC 1999 Red Book", "14.7(b)", "Payment of interim certificate", "Employer", "the Engineer receiving the Statement and supporting documents", 56, None, None),
    ("FIDIC 1999 Red Book", "10.1", "Taking-Over Certificate issued or rejected", "Engineer", "receiving the Contractor's application", 28, None, None),
    ("FIDIC 1999 Red Book", "14.10", "Statement at Completion", "Contractor", "receiving the Taking-Over Certificate", 84, None, None),
    ("FIDIC 1999 Red Book", "14.11", "Draft Final Statement", "Contractor", "receiving the Performance Certificate", 56, None, None),
    ("FIDIC 1999 Red Book", "20.1", "Notice of claim (time bar)", "Contractor", "becoming aware (or when it should have become aware) of the event", 28,
     "Fully detailed claim", 42),
    ("FIDIC 1999 Red Book", "20.1", "Engineer's response to a detailed claim", "Engineer", "receiving the fully detailed claim", 42, None, None),
    ("FIDIC 1999 Red Book", "20.4", "DAB decision", "DAB", "receiving the reference of the dispute", 84, None, None),
    ("FIDIC 1999 Red Book", "20.4", "Notice of dissatisfaction with the DAB decision", "Either party", "receiving the DAB decision", 28, None, None),
    ("FIDIC 1999 Red Book", "16.1", "Suspension by Contractor (notice period)", "Contractor", "giving notice to the Employer", 21, None, None),
    ("FIDIC 1999 Red Book", "15.2", "Termination by Employer (notice period)", "Employer", "giving notice to the Contractor", 14, None, None),
    ("FIDIC 1999 Red Book", "16.2", "Termination by Contractor (notice period)", "Contractor", "giving notice to the Employer", 14, None, None),
    ("FIDIC 2017 Red Book", "20.2.1", "Notice of Claim (time bar)", "Either party", "becoming aware (or when it should have become aware) of the event", 28,
     "Fully detailed Claim (20.2.4)", 84),
    ("FIDIC 2017 Red Book", "3.7.3", "Engineer's agreement / determination of a claim", "Engineer", "receiving the fully detailed Claim", 42, None, None),
    ("FIDIC 2017 Red Book", "3.7.5", "Notice of dissatisfaction with Engineer's determination", "Either party", "receiving the Engineer's determination", 28, None, None),
    ("FIDIC 2017 Red Book", "14.6", "Interim Payment Certificate issued", "Engineer", "receiving the Statement and supporting documents", 28, None, None),
    ("FIDIC 2017 Red Book", "14.7", "Payment of interim certificate", "Employer", "the Engineer receiving the Statement and supporting documents", 56, None, None),
    ("FIDIC 2017 Red Book", "21.4.3", "DAAB decision", "DAAB", "receiving the reference of the dispute", 84, None, None),
    ("FIDIC 2017 Red Book", "21.4.4", "Notice of dissatisfaction with the DAAB decision", "Either party", "receiving the DAAB decision", 28, None, None),
]


def init_cadmin(c):
    for st in SCHEMA.strip().split(";"):
        if st.strip():
            c.execute(st)
    if not c.execute("SELECT COUNT(*) FROM ca_clauses WHERE system=1").fetchone()[0]:
        for form, cl, title, party, trig, days, ft, fd in CLAUSE_LIB:
            c.execute("INSERT INTO ca_clauses(project_id, form, clause, title, party, trigger, days, follow_title, follow_days, consequence, system, active, ts) "
                      "VALUES(NULL,?,?,?,?,?,?,?,?,?,1,1,?)", (form, cl, title, party, trig, days, ft, fd, FIDIC_NOTE, now()))
    _hook_search()
    _hook_mywork()


# ───────────────────────── small helpers ─────────────────────────
def _pid(a, need=True):
    p = a.get("project_id")
    if not p:
        if need:
            raise ApiError("Choose a project at the top first.")
        return None
    return int(p)


def _keep(r, cols, ints=(), nums=()):
    out = {}
    for k in cols:
        if k in r:
            v = r.get(k)
            if v == "":
                v = None
            if k in ints and v is not None:
                v = int(v)
            if k in nums and v is not None:
                v = num(v)
            out[k] = v
    return out


def _days(d1, d2=None):
    try:
        a = date.fromisoformat(str(d1)[:10])
        b = date.fromisoformat(str(d2)[:10]) if d2 else date.today()
        return (b - a).days
    except (ValueError, TypeError):
        return None


def _add_days(d, n):
    try:
        return (date.fromisoformat(str(d)[:10]) + timedelta(days=int(n))).isoformat()
    except (ValueError, TypeError):
        return None


def _pcode(c, pid):
    return val(c, "SELECT code FROM projects WHERE id=?", (pid,), None) or "PRJ"


def _uname(c, uid):
    return val(c, "SELECT name FROM users WHERE id=?", (uid,), None) if uid else None


def notify(c, user_ids, kind, title, link, project_id=None, by=None, body=None):
    """A notification in someone's bell / inbox. Not sent to the person who caused it."""
    seen = set()
    for uid in user_ids or []:
        if not uid or uid == by or uid in seen:
            continue
        seen.add(uid)
        c.execute("INSERT INTO cm_notes(user_id, kind, title, body, link, project_id, by_user, ts) VALUES(?,?,?,?,?,?,?,?)",
                  (int(uid), kind, title[:300], (body or "")[:500], link, project_id, by, now()))
    return len(seen)


def _list_users(c, list_id):
    if not list_id:
        return []
    r = q1(c, "SELECT members FROM cm_lists WHERE id=?", (int(list_id),))
    try:
        return [int(m["user_id"]) for m in json.loads(r["members"] or "[]") if m.get("user_id")] if r else []
    except (ValueError, TypeError):
        return []


def _list_text(c, list_id):
    r = q1(c, "SELECT name, members FROM cm_lists WHERE id=?", (int(list_id),)) if list_id else None
    if not r:
        return ""
    names = []
    for m in json.loads(r["members"] or "[]"):
        if m.get("user_id"):
            names.append(_uname(c, m["user_id"]) or "?")
        else:
            names.append(" ".join(x for x in (m.get("name"), "(%s)" % m["org"] if m.get("org") else "") if x))
    return "%s: %s" % (r["name"], ", ".join(names))


# ═════════════════════════ contract administration ═════════════════════════
@api("ca.meta")
def ca_meta(c, u, a):
    pid = a.get("project_id")
    return {"categories": LETTER_CATS, "status": LETTER_STATUS, "sec_kinds": SEC_KINDS, "sec_status": SEC_STATUS,
            "doc_types": DOC_TYPES, "disciplines": list(DISC_CODES.keys())[:-1], "rev_status": REV_STATUS, "decisions": DECISIONS,
            "tr_purpose": TR_PURPOSE,
            "users": q(c, "SELECT id, name, username, role FROM users WHERE active=1 ORDER BY name"),
            "parties": q(c, "SELECT id, code, name, kind FROM parties WHERE COALESCE(active,1)=1 ORDER BY name"),
            "contracts": q(c, "SELECT id, ref_no, title FROM contracts WHERE status='active'" + (" AND (project_id=? OR project_id IS NULL)" if pid else "") + " ORDER BY title",
                           (int(pid),) if pid else ()),
            "lists": q(c, "SELECT id, name FROM cm_lists WHERE active=1" + (" AND (project_id=? OR project_id IS NULL)" if pid else "") + " ORDER BY name",
                       (int(pid),) if pid else ()),
            "clauses": q(c, "SELECT id, form, clause, title, days, follow_title, follow_days, party FROM ca_clauses WHERE active=1" +
                         (" AND (project_id IS NULL OR project_id=?)" if pid else " AND project_id IS NULL") + " ORDER BY form, id", (int(pid),) if pid else ()),
            "events": q(c, "SELECT id, no, title FROM events WHERE project_id=? AND status NOT IN ('closed','rejected') ORDER BY id DESC", (int(pid),)) if pid else [],
            "can_edit": can(u, "commercial", "edit"), "can_doc": can(u, "project", "edit")}


def _letter_rows(c, where, params):
    rows = q(c, "SELECT l.*, pa.name party, uu.name assignee, pr.code project FROM ca_letters l LEFT JOIN parties pa ON pa.id=l.party_id "
                "LEFT JOIN users uu ON uu.id=l.assigned_to LEFT JOIN projects pr ON pr.id=l.project_id WHERE %s "
                "ORDER BY l.date DESC, l.id DESC" % where, params)
    td = today()
    for r in rows:
        r["overdue"] = bool(r["status"] == "open" and r.get("reply_needed") and r.get("reply_by") and r["reply_by"] < td)
        r["days_left"] = -_days(r["reply_by"]) if r.get("reply_by") and r["status"] == "open" else None
        r["ref"] = r.get("our_no") or ""
        r["who"] = r.get("party") or (r.get("from_name") if r["direction"] == "in" else r.get("to_name")) or ""
    return rows


@api("ca.letters", "commercial", "view")
def ca_letters(c, u, a):
    w, p = ["l.project_id=?"], [_pid(a)]
    for k in ("direction", "category", "status"):
        if a.get(k):
            w.append("l.%s=?" % k)
            p.append(a[k])
    if a.get("party_id"):
        w.append("l.party_id=?")
        p.append(int(a["party_id"]))
    if a.get("open"):
        w.append("l.status='open' AND l.reply_needed=1")
    if a.get("q"):
        for word in str(a["q"]).split():
            w.append("(l.subject LIKE ? OR l.our_no LIKE ? OR l.their_ref LIKE ? OR l.summary LIKE ? OR l.body LIKE ?)")
            p += ["%" + word + "%"] * 5
    rows = _letter_rows(c, " AND ".join(w), p)
    # how quickly each side answers (data for decisions: who is slow, by how much)
    stats = {}
    for r in _letter_rows(c, "l.project_id=? AND l.replied_by IS NOT NULL", [_pid(a)]):
        rep = q1(c, "SELECT date FROM ca_letters WHERE id=?", (r["replied_by"],))
        d = _days(r.get("received_on") or r["date"], rep["date"]) if rep else None
        if d is None:
            continue
        key = ("We answer them" if r["direction"] == "in" else "They answer us") + " - " + (r["who"] or "—")
        g = stats.setdefault(key, {"who": key, "n": 0, "days": 0, "late": 0})
        g["n"] += 1
        g["days"] += d
        if r.get("reply_by") and rep["date"] > r["reply_by"]:
            g["late"] += 1
    for g in stats.values():
        g["avg_days"] = round(g["days"] / g["n"], 1) if g["n"] else None
    return {"rows": rows, "reply_stats": sorted(stats.values(), key=lambda x: -(x["avg_days"] or 0))}


@api("ca.letter_get", "commercial", "view")
def ca_letter_get(c, u, a):
    rows = _letter_rows(c, "l.id=?", [int(a["id"])])
    if not rows:
        raise ApiError("Letter not found.")
    r = rows[0]
    chain, seen, x = [], set(), r
    while x and x.get("in_reply_to") and x["in_reply_to"] not in seen:     # walk up to the first letter
        seen.add(x["in_reply_to"])
        x = q1(c, "SELECT * FROM ca_letters WHERE id=?", (x["in_reply_to"],))
    root = x["id"] if x else r["id"]
    ids, frontier = {root}, [root]
    while frontier:                                                          # and down to every answer
        nxt = [y["id"] for y in q(c, "SELECT id FROM ca_letters WHERE in_reply_to IN (%s)" % ",".join("?" * len(frontier)), frontier)]
        frontier = [i for i in nxt if i not in ids]
        ids.update(frontier)
    chain = _letter_rows(c, "l.id IN (%s)" % ",".join("?" * len(ids)), list(ids))
    chain.sort(key=lambda z: (z["date"] or "", z["id"]))
    r["chain"] = chain
    r["files"] = q(c, "SELECT id, filename, size, date FROM files WHERE entity='ca_letters' AND entity_id=?", (r["id"],))
    r["timebar"] = q1(c, "SELECT * FROM ca_timebars WHERE id=?", (r["timebar_id"],)) if r.get("timebar_id") else None
    r["list_text"] = _list_text(c, r.get("list_id"))
    return r


@api("ca.letter_save", "commercial", "edit")
def ca_letter_save(c, u, a):
    r = a.get("row") or {}
    cols = ("contract_id", "direction", "their_ref", "date", "received_on", "party_id", "from_name", "to_name", "subject", "category",
            "clause", "summary", "body", "reply_needed", "reply_by", "in_reply_to", "status", "priority", "assigned_to", "cc", "list_id",
            "event_id", "variation_id", "timebar_id")
    keep = _keep(r, cols, ints=("contract_id", "party_id", "reply_needed", "in_reply_to", "assigned_to", "list_id", "event_id",
                                "variation_id", "timebar_id"))
    if r.get("id"):
        old = q1(c, "SELECT * FROM ca_letters WHERE id=?", (int(r["id"]),))
        if not old:
            raise ApiError("Letter not found.")
        if keep.get("status") in ("closed", "void") and old["status"] not in ("closed", "void"):
            keep["closed_on"] = today()
        keep.pop("direction", None)
        upd(c, "ca_letters", old["id"], keep)
        lid = old["id"]
        new = False
    else:
        pid = _pid(r)
        if (keep.get("direction") or "") not in ("in", "out"):
            raise ApiError("Say whether the letter came in or went out.")
        if not (keep.get("subject") or "").strip():
            raise ApiError("Write the subject.")
        keep.setdefault("date", today())
        if not keep.get("date"):
            keep["date"] = today()
        keep["our_no"] = next_no(c, "%s-%s" % (_pcode(c, pid), "OUT" if keep["direction"] == "out" else "IN"), keep["date"])
        if keep["direction"] == "in" and not keep.get("received_on"):
            keep["received_on"] = keep["date"]
        if keep.get("reply_needed") and not keep.get("reply_by"):
            keep["reply_by"] = _add_days(keep.get("received_on") or keep["date"], 7)
        keep.setdefault("status", "open" if keep.get("reply_needed") else "info")
        if not keep.get("status"):
            keep["status"] = "open" if keep.get("reply_needed") else "info"
        keep.update({"project_id": pid, "created_by": u["id"], "ts": now()})
        lid = ins(c, "ca_letters", keep)
        new = True
    L = q1(c, "SELECT * FROM ca_letters WHERE id=?", (lid,))
    # an answer closes the letter it answers
    if L.get("in_reply_to"):
        prev = q1(c, "SELECT * FROM ca_letters WHERE id=?", (L["in_reply_to"],))
        if prev and prev["status"] == "open" and not prev.get("replied_by"):
            upd(c, "ca_letters", prev["id"], {"status": "replied", "replied_by": lid})
    # a notice letter sent closes the time bar it was written for
    if L["direction"] == "out" and L.get("timebar_id"):
        tb = q1(c, "SELECT * FROM ca_timebars WHERE id=?", (L["timebar_id"],))
        if tb and tb["status"] == "running":
            late = bool(tb.get("due_date") and L["date"] > tb["due_date"])
            upd(c, "ca_timebars", tb["id"], {"status": "late" if late else "done", "done_date": L["date"], "letter_id": lid})
    if new or (r.get("assigned_to") and str(r.get("assigned_to")) != str((old or {}).get("assigned_to") if not new else "")):
        if L.get("assigned_to"):
            notify(c, [L["assigned_to"]], "letter", "%s letter %s: %s" % ("Incoming" if L["direction"] == "in" else "Outgoing", L["our_no"], L["subject"]),
                   "#/ca/letters?id=%d" % lid, L["project_id"], u["id"], "Reply by %s" % L["reply_by"] if L.get("reply_by") else None)
    if new and L.get("list_id"):
        notify(c, _list_users(c, L["list_id"]), "letter", "Copy of letter %s: %s" % (L["our_no"], L["subject"]),
               "#/ca/letters?id=%d" % lid, L["project_id"], u["id"])
    audit(c, u, "create" if new else "save", "ca_letters", lid, {"no": L["our_no"], "status": L["status"]})
    return {"id": lid, "our_no": L["our_no"]}


# ───────────────────────── letter drafts ─────────────────────────
DRAFTS = {
    "claim_notice": ("Notice of claim", "notice",
                     "We hereby give notice under Sub-Clause {clause} of the Conditions of Contract of the following event, of which we became aware on {trigger}:\n\n"
                     "{event}\n\nThe event is likely to cause delay to the Works and additional cost to the Contractor. We shall keep contemporary records and "
                     "submit a fully detailed claim, with supporting particulars of the extension of time and additional payment claimed, within the time "
                     "allowed by the Contract.\n\nThis notice is given without prejudice to any other rights under the Contract."),
    "eot_request": ("Request for extension of time", "eot",
                    "Further to our notice reference {ref}, we submit our request for an extension of the Time for Completion under Sub-Clause {clause}.\n\n"
                    "Cause: {event}\nDelay recorded: {delay} days\nSupporting records: daily progress reports, site diaries and photographs for the period.\n\n"
                    "We request an extension of {delay} days and shall provide any further particulars you may reasonably require."),
    "payment_reminder": ("Reminder: payment overdue", "payment",
                         "Interim Payment Certificate {ipc} dated {ipc_date} for NPR {amount} remains unpaid. Under Sub-Clause {clause} payment was due "
                         "by {due}. We request immediate payment and reserve our entitlement to financing charges for delayed payment."),
    "instruction_request": ("Request for instruction", "rfi",
                            "We request your instruction on the following matter, which affects the progress of the Works:\n\n{event}\n\n"
                            "Kindly instruct by {due} so that work is not delayed. Any delay beyond this date may entitle the Contractor to an extension of time."),
    "acknowledge": ("Acknowledgement", "general",
                    "We acknowledge receipt of your letter reference {their_ref} dated {their_date} regarding \"{subject}\". We are reviewing it and shall respond by {due}."),
    "variation_notice": ("Notice of variation", "variation",
                         "Your instruction / drawing {ref} changes the scope of the Works as follows:\n\n{event}\n\nWe consider this a Variation under the Contract. "
                         "We shall submit our proposal for the valuation and any time effect. Please confirm the instruction in writing."),
}


@api("ca.draft", "commercial", "view")
def ca_draft(c, u, a):
    """A ready letter text from the record - the user reads, changes and sends it. BuildCore never sends anything by itself."""
    kind = a.get("kind")
    if kind not in DRAFTS:
        raise ApiError("Unknown letter kind.")
    title, cat, text = DRAFTS[kind]
    v = {"clause": a.get("clause") or "[clause]", "trigger": a.get("trigger") or "[date]", "event": a.get("event") or "[describe the event]",
         "ref": a.get("ref") or "[reference]", "delay": a.get("delay") or "[n]", "ipc": "[IPC no.]", "ipc_date": "[date]", "amount": "[amount]",
         "due": a.get("due") or _add_days(today(), 7), "their_ref": "[their ref]", "their_date": "[date]", "subject": "[subject]"}
    if a.get("event_id"):
        e = q1(c, "SELECT * FROM events WHERE id=?", (int(a["event_id"]),))
        if e:
            v.update({"event": "%s - %s\n%s" % (e.get("no") or "", e.get("title") or "", e.get("description") or ""), "trigger": e.get("date") or v["trigger"],
                      "delay": e.get("delay_days") or v["delay"], "clause": e.get("clause") or v["clause"]})
    if a.get("ipc_id"):
        p = q1(c, "SELECT * FROM ipc WHERE id=?", (int(a["ipc_id"]),))
        if p:
            v.update({"ipc": p["no"], "ipc_date": p.get("date") or "", "amount": "{:,.2f}".format(p.get("net") or 0)})
    if a.get("letter_id"):
        L = q1(c, "SELECT * FROM ca_letters WHERE id=?", (int(a["letter_id"]),))
        if L:
            v.update({"their_ref": L.get("their_ref") or L.get("our_no"), "their_date": L.get("date") or "", "subject": L.get("subject") or "",
                      "ref": L.get("our_no") or v["ref"]})
    if a.get("timebar_id"):
        t = q1(c, "SELECT * FROM ca_timebars WHERE id=?", (int(a["timebar_id"]),))
        if t:
            v.update({"clause": t.get("clause") or v["clause"], "trigger": t.get("trigger_date") or v["trigger"]})
            if t.get("notes") and v["event"].startswith("["):
                v["event"] = t["notes"]
    return {"subject": title, "category": cat, "body": text.format(**v)}


# ───────────────────────── clauses and time bars ─────────────────────────
@api("ca.clauses", "commercial", "view")
def ca_clauses(c, u, a):
    pid = a.get("project_id")
    return q(c, "SELECT * FROM ca_clauses WHERE active=1 AND (project_id IS NULL" + (" OR project_id=?)" if pid else ")") + " ORDER BY form, id",
             (int(pid),) if pid else ())


@api("ca.clause_save", "commercial", "edit")
def ca_clause_save(c, u, a):
    r = a.get("row") or {}
    keep = _keep(r, ("form", "clause", "title", "party", "trigger", "days", "follow_title", "follow_days", "consequence", "active"),
                 ints=("days", "follow_days", "active"))
    if r.get("id"):
        old = q1(c, "SELECT * FROM ca_clauses WHERE id=?", (int(r["id"]),))
        if not old:
            raise ApiError("Clause not found.")
        upd(c, "ca_clauses", old["id"], keep)
        return {"id": old["id"]}
    if not (keep.get("title") or "").strip() or not keep.get("days"):
        raise ApiError("Write the clause title and the number of days.")
    keep.update({"project_id": _pid(r, False), "form": keep.get("form") or "This contract", "system": 0, "active": 1, "ts": now()})
    return {"id": ins(c, "ca_clauses", keep)}


def _tb_rows(c, where, params):
    rows = q(c, "SELECT t.*, l.our_no letter_no, e.no event_no FROM ca_timebars t LEFT JOIN ca_letters l ON l.id=t.letter_id "
                "LEFT JOIN events e ON e.id=t.event_id WHERE %s ORDER BY CASE t.status WHEN 'running' THEN 0 ELSE 1 END, t.due_date" % where, params)
    for r in rows:
        r["days_left"] = -_days(r["due_date"]) if r.get("due_date") and r["status"] == "running" else None
        r["state"] = ("MISSED" if r["days_left"] is not None and r["days_left"] < 0 else
                      "due in %d d" % r["days_left"] if r["days_left"] is not None else r["status"])
    return rows


@api("ca.timebars", "commercial", "view")
def ca_timebars(c, u, a):
    w, p = ["t.project_id=?"], [_pid(a)]
    if a.get("running"):
        w.append("t.status='running'")
    return _tb_rows(c, " AND ".join(w), p)


@api("ca.timebar_start", "commercial", "edit")
def ca_timebar_start(c, u, a):
    """Start the clock: from the clause and the date the event happened (or we became aware), the last day for the
    notice - and, for a claim, the detailed-claim deadline too."""
    pid = _pid(a)
    trig = a.get("trigger_date") or today()
    cl = q1(c, "SELECT * FROM ca_clauses WHERE id=?", (int(a["clause_id"]),)) if a.get("clause_id") else None
    days = int(a.get("days") or (cl["days"] if cl else 0) or 0)
    if not days:
        raise ApiError("Choose a clause or enter the number of days.")
    title = a.get("title") or (cl["title"] if cl else "Notice")
    eid = int(a["event_id"]) if a.get("event_id") else None
    base = {"project_id": pid, "clause_id": cl["id"] if cl else None, "clause": (cl["clause"] if cl else a.get("clause")),
            "party": a.get("party") or (cl["party"] if cl else None), "trigger_date": trig, "status": "running", "event_id": eid,
            "notes": a.get("notes"), "created_by": u["id"], "ts": now()}
    t1 = dict(base, title=title, due_date=_add_days(trig, days))
    tid = ins(c, "ca_timebars", t1)
    out = [tid]
    if cl and cl.get("follow_days"):
        out.append(ins(c, "ca_timebars", dict(base, title=cl["follow_title"] or "Follow-up", due_date=_add_days(trig, cl["follow_days"]), parent_id=tid)))
    if eid:
        ev = q1(c, "SELECT notice_deadline FROM events WHERE id=?", (eid,))
        if ev is not None and not ev.get("notice_deadline"):
            upd(c, "events", eid, {"notice_deadline": t1["due_date"], "clause": base["clause"]})
    audit(c, u, "create", "ca_timebars", tid, {"title": title, "due": t1["due_date"]})
    return {"ids": out, "due_date": t1["due_date"]}


@api("ca.timebar_set", "commercial", "edit")
def ca_timebar_set(c, u, a):
    t = q1(c, "SELECT * FROM ca_timebars WHERE id=?", (int(a["id"]),))
    if not t:
        raise ApiError("Time bar not found.")
    st = a.get("status")
    if st not in ("running", "done", "late", "waived", "not_needed"):
        raise ApiError("Unknown status.")
    keep = {"status": st, "notes": a.get("notes") if a.get("notes") is not None else t.get("notes")}
    if st in ("done", "late"):
        keep["done_date"] = a.get("done_date") or today()
        if t.get("due_date") and keep["done_date"] > t["due_date"]:
            keep["status"] = "late"
        if a.get("letter_id"):
            keep["letter_id"] = int(a["letter_id"])
    upd(c, "ca_timebars", t["id"], keep)
    audit(c, u, "save", "ca_timebars", t["id"], {"status": keep["status"]})
    return {"status": keep["status"]}


# ───────────────────────── bonds, guarantees and insurance ─────────────────────────
@api("ca.securities", "commercial", "view")
def ca_securities(c, u, a):
    w, p = ["1=1"], []
    if a.get("project_id"):
        w.append("(s.project_id=? OR s.project_id IS NULL)")
        p.append(int(a["project_id"]))
    rows = q(c, "SELECT s.*, pa.name party, pr.code project, k.title contract FROM ca_securities s LEFT JOIN parties pa ON pa.id=s.party_id "
                "LEFT JOIN projects pr ON pr.id=s.project_id LEFT JOIN contracts k ON k.id=s.contract_id WHERE %s "
                "ORDER BY CASE WHEN s.status IN ('released','encashed') THEN 1 ELSE 0 END, s.expiry_date" % " AND ".join(w), p)
    for r in rows:
        r["days_left"] = -_days(r["expiry_date"]) if r.get("expiry_date") else None
        live = r["status"] in ("active", "extended", "reduced")
        r["alert"] = ("EXPIRED" if live and r["days_left"] is not None and r["days_left"] < 0 else
                      "expires in %d d" % r["days_left"] if live and r["days_left"] is not None and r["days_left"] <= 45 else "")
    tot = {}
    for r in rows:
        if r["status"] in ("active", "extended", "reduced"):
            tot[r["kind"]] = tot.get(r["kind"], 0) + (r["amount"] or 0)
    return {"rows": rows, "live_total": tot}


@api("ca.security_save", "commercial", "edit")
def ca_security_save(c, u, a):
    r = a.get("row") or {}
    keep = _keep(r, ("project_id", "contract_id", "kind", "number", "issuer", "beneficiary", "party_id", "amount", "currency", "issue_date",
                     "expiry_date", "claim_until", "status", "released_on", "remarks"),
                 ints=("project_id", "contract_id", "party_id"), nums=("amount",))
    if r.get("id"):
        old = q1(c, "SELECT * FROM ca_securities WHERE id=?", (int(r["id"]),))
        if not old:
            raise ApiError("Record not found.")
        hist = json.loads(old.get("history") or "[]")
        for k in ("expiry_date", "amount", "status"):
            if k in keep and str(keep[k] or "") != str(old.get(k) or ""):
                hist.append({"date": today(), "what": k, "from": old.get(k), "to": keep[k], "by": u["name"]})
        if keep.get("status") == "released" and not (keep.get("released_on") or old.get("released_on")):
            keep["released_on"] = today()
        keep["history"] = json.dumps(hist)
        upd(c, "ca_securities", old["id"], keep)
        audit(c, u, "save", "ca_securities", old["id"], {"status": keep.get("status")})
        return {"id": old["id"]}
    if not keep.get("kind") or not keep.get("expiry_date"):
        raise ApiError("Choose what it is and enter the expiry date.")
    keep.update({"status": keep.get("status") or "active", "history": "[]", "created_by": u["id"], "ts": now()})
    sid = ins(c, "ca_securities", keep)
    audit(c, u, "create", "ca_securities", sid, {"kind": keep["kind"], "expiry": keep["expiry_date"]})
    return {"id": sid}


# ───────────────────────── dashboard ─────────────────────────
@api("ca.dash", "commercial", "view")
def ca_dash(c, u, a):
    pid = _pid(a)
    td, soon = today(), _add_days(today(), 14)
    letters = _letter_rows(c, "l.project_id=? AND l.status='open' AND l.reply_needed=1", [pid])
    tbs = _tb_rows(c, "t.project_id=? AND t.status='running'", [pid])
    sec = [s for s in ca_securities(c, u, {"project_id": pid})["rows"] if s["alert"]]
    ev = q(c, "SELECT id, no, title, date, notice_deadline, clause, delay_days, cost_impact, status FROM events WHERE project_id=? AND "
              "status NOT IN ('closed','rejected','resolved') AND notice_deadline IS NOT NULL ORDER BY notice_deadline", (pid,))
    for e in ev:
        e["days_left"] = -_days(e["notice_deadline"])
        e["has_notice"] = bool(val(c, "SELECT COUNT(*) FROM ca_letters WHERE event_id=? AND direction='out' AND status<>'void'", (e["id"],), 0))
    ev = [e for e in ev if not e["has_notice"]]
    var = q(c, "SELECT id, no, title, date, status, var_qty, new_rate, time_impact_days FROM variations WHERE project_id=? AND "
               "status IN ('identified','submitted','pending','under_review') ORDER BY date", (pid,))
    for v in var:
        v["age"] = _days(v["date"]) if v.get("date") else None
    sched = {}
    try:
        sched = FUNCS["con.schedule"][0](c, u, {"project_id": pid, "days": 14})
    except Exception:
        sched = {}
    tr_due = q(c, "SELECT id, no, subject, response_due, to_name FROM dm_transmittals WHERE project_id=? AND status='sent' AND response_due IS NOT NULL "
                  "AND response_due<=? ORDER BY response_due", (pid, soon))
    counts = {"replies_overdue": sum(1 for x in letters if x["overdue"]), "replies_due": len(letters),
              "timebars": len(tbs), "timebars_7d": sum(1 for x in tbs if x["days_left"] is not None and x["days_left"] <= 7),
              "securities": len(sec), "events_no_notice": len(ev), "variations": len(var),
              "contract_items": len((sched or {}).get("items") or []), "transmittals_due": len(tr_due)}
    month = date.today().replace(day=1).isoformat()
    flow = {"in_month": val(c, "SELECT COUNT(*) FROM ca_letters WHERE project_id=? AND direction='in' AND date>=?", (pid, month), 0),
            "out_month": val(c, "SELECT COUNT(*) FROM ca_letters WHERE project_id=? AND direction='out' AND date>=?", (pid, month), 0)}
    return {"letters": letters, "timebars": tbs, "securities": sec, "events": ev, "variations": var, "contract_items": (sched or {}).get("items") or [],
            "transmittals": tr_due, "counts": counts, "flow": flow, "today": td}


# ═════════════════════════ communication ═════════════════════════
MENTION = re.compile(r"@([A-Za-z0-9_.\-]{2,40})")


def _mentions(c, body):
    out = []
    for m in MENTION.findall(body or ""):
        uid = val(c, "SELECT id FROM users WHERE LOWER(username)=LOWER(?) AND active=1", (m.rstrip("."),), None)
        if uid and uid not in out:
            out.append(uid)
    return out


def _thread_rows(c, u, where, params):
    rows = q(c, "SELECT t.*, uu.name started_by, pr.code project, (SELECT body FROM cm_posts p WHERE p.thread_id=t.id ORDER BY p.id DESC LIMIT 1) last_body, "
                "(SELECT uu2.name FROM cm_posts p JOIN users uu2 ON uu2.id=p.user_id WHERE p.thread_id=t.id ORDER BY p.id DESC LIMIT 1) last_by, "
                "(SELECT COUNT(*) FROM cm_posts p WHERE p.thread_id=t.id AND p.id > COALESCE((SELECT last_post_id FROM cm_reads r WHERE r.thread_id=t.id AND r.user_id=?),0)) unread "
                "FROM cm_threads t LEFT JOIN users uu ON uu.id=t.created_by LEFT JOIN projects pr ON pr.id=t.project_id WHERE %s "
                "ORDER BY t.pinned DESC, t.last_ts DESC" % where, [u["id"]] + list(params))
    for r in rows:
        r["last_body"] = (r.get("last_body") or "")[:160]
    return rows


@api("cm.threads")
def cm_threads(c, u, a):
    w, p = ["1=1"], []
    if a.get("project_id"):
        w.append("t.project_id=?")
        p.append(int(a["project_id"]))
    if a.get("entity"):
        w.append("t.entity=? AND t.entity_id=?")
        p += [a["entity"], int(a.get("entity_id") or 0)]
    if a.get("q"):
        w.append("(t.title LIKE ? OR EXISTS(SELECT 1 FROM cm_posts x WHERE x.thread_id=t.id AND x.body LIKE ?))")
        p += ["%" + a["q"] + "%"] * 2
    if not a.get("closed"):
        w.append("t.closed=0")
    return _thread_rows(c, u, " AND ".join(w), p)


@api("cm.thread_get")
def cm_thread_get(c, u, a):
    t = _thread_rows(c, u, "t.id=?", [int(a["id"])])
    if not t:
        raise ApiError("Discussion not found.")
    t = t[0]
    t["posts"] = q(c, "SELECT p.*, uu.name author, uu.username FROM cm_posts p LEFT JOIN users uu ON uu.id=p.user_id WHERE p.thread_id=? ORDER BY p.id", (t["id"],))
    for p in t["posts"]:
        p["files"] = q(c, "SELECT id, filename, kind FROM files WHERE entity='cm_posts' AND entity_id=?", (p["id"],))
    last = t["posts"][-1]["id"] if t["posts"] else 0
    c.execute("INSERT OR REPLACE INTO cm_reads(thread_id, user_id, last_post_id) VALUES(?,?,?)", (t["id"], u["id"], last))
    c.execute("UPDATE cm_notes SET read_at=? WHERE user_id=? AND read_at IS NULL AND link=?", (now(), u["id"], "#/cm?id=%d" % t["id"]))
    t["link"] = _entity_link(t.get("entity"), t.get("entity_id"))
    return t


def _entity_link(entity, eid):
    links = {"ca_letters": "#/ca/letters?id=%s", "dm_docs": "#/dm?doc=%s", "fld_issues": "#/f/issues?id=%s", "fld_rfis": "#/f/rfis?id=%s",
             "dm_transmittals": "#/dm/transmittals?id=%s", "events": "#/p/events", "variations": "#/p/variations"}
    return (links.get(entity) or "") % eid if entity in links and "%s" in links[entity] else links.get(entity)


def _post(c, u, tid, body, extra_users=()):
    t = q1(c, "SELECT * FROM cm_threads WHERE id=?", (tid,))
    if not t:
        raise ApiError("Discussion not found.")
    if t["closed"]:
        raise ApiError("This discussion is closed. Open it again to write.")
    body = (body or "").strip()
    if not body:
        raise ApiError("Write something first.")
    men = _mentions(c, body)
    pid_ = ins(c, "cm_posts", {"thread_id": tid, "user_id": u["id"], "body": body, "ts": now(), "mentions": json.dumps(men)})
    c.execute("UPDATE cm_threads SET last_ts=?, posts=posts+1 WHERE id=?", (now(), tid))
    c.execute("INSERT OR REPLACE INTO cm_reads(thread_id, user_id, last_post_id) VALUES(?,?,?)", (tid, u["id"], pid_))
    link = "#/cm?id=%d" % tid
    notify(c, men, "mention", "%s mentioned you in \"%s\"" % (u["name"], t["title"]), link, t["project_id"], u["id"], body[:300])
    # everyone who already wrote in the discussion hears about a new answer
    others = [r["user_id"] for r in q(c, "SELECT DISTINCT user_id FROM cm_posts WHERE thread_id=?", (tid,)) if r["user_id"] not in men]
    notify(c, list(others) + [x for x in extra_users if x not in men], "reply", "%s wrote in \"%s\"" % (u["name"], t["title"]), link,
           t["project_id"], u["id"], body[:300])
    return pid_, men


@api("cm.thread_new")
def cm_thread_new(c, u, a):
    title = (a.get("title") or "").strip()
    if not title:
        raise ApiError("Give the discussion a subject.")
    kind = a.get("kind") if a.get("kind") in ("discussion", "announcement") else "discussion"
    if kind == "announcement" and not can(u, "project", "approve"):
        raise ApiError("Only a project manager or administrator can post an announcement.")
    tid = ins(c, "cm_threads", {"project_id": _pid(a, False), "title": title, "entity": a.get("entity"),
                                "entity_id": int(a["entity_id"]) if a.get("entity_id") else None, "kind": kind,
                                "pinned": 1 if kind == "announcement" else 0, "created_by": u["id"], "ts": now(), "last_ts": now(), "posts": 0})
    extra = []
    if kind == "announcement":
        extra = [r["id"] for r in q(c, "SELECT id FROM users WHERE active=1")]
    if a.get("list_id"):
        extra += _list_users(c, a["list_id"])
    pid_, men = _post(c, u, tid, a.get("body") or title, extra)
    return {"id": tid, "post_id": pid_, "mentioned": len(men)}


@api("cm.post")
def cm_post(c, u, a):
    pid_, men = _post(c, u, int(a["thread_id"]), a.get("body"))
    return {"id": pid_, "mentioned": len(men)}


@api("cm.thread_set")
def cm_thread_set(c, u, a):
    t = q1(c, "SELECT * FROM cm_threads WHERE id=?", (int(a["id"]),))
    if not t:
        raise ApiError("Discussion not found.")
    if t["created_by"] != u["id"] and not can(u, "project", "approve"):
        raise ApiError("Only the person who started it, or a project manager, can change this.")
    keep = {}
    for k in ("pinned", "closed"):
        if k in a:
            keep[k] = 1 if a[k] else 0
    if a.get("title"):
        keep["title"] = a["title"]
    upd(c, "cm_threads", t["id"], keep)
    return {"ok": True}


@api("cm.inbox")
def cm_inbox(c, u, a):
    w = "user_id=?" + ("" if a.get("all") else " AND (read_at IS NULL OR ts>=?)")
    p = [u["id"]] + ([] if a.get("all") else [_add_days(today(), -14)])
    notes = q(c, "SELECT n.*, uu.name by_name, pr.code project FROM cm_notes n LEFT JOIN users uu ON uu.id=n.by_user LEFT JOIN projects pr ON pr.id=n.project_id "
                 "WHERE %s ORDER BY n.read_at IS NOT NULL, n.id DESC LIMIT 200" % w.replace("user_id", "n.user_id").replace("read_at", "n.read_at").replace("ts>=", "n.ts>="), p)
    unread_threads = val(c, "SELECT COUNT(*) FROM cm_threads t WHERE t.closed=0 AND EXISTS(SELECT 1 FROM cm_posts p WHERE p.thread_id=t.id AND p.user_id<>? AND "
                            "p.id > COALESCE((SELECT last_post_id FROM cm_reads r WHERE r.thread_id=t.id AND r.user_id=?),0)) AND "
                            "(EXISTS(SELECT 1 FROM cm_posts p2 WHERE p2.thread_id=t.id AND p2.user_id=?) OR t.kind='announcement')", (u["id"], u["id"], u["id"]), 0)
    return {"notes": notes, "unread": sum(1 for n in notes if not n["read_at"]), "unread_threads": unread_threads}


@api("cm.unread")
def cm_unread(c, u, a):
    return {"unread": val(c, "SELECT COUNT(*) FROM cm_notes WHERE user_id=? AND read_at IS NULL", (u["id"],), 0)}


@api("cm.mark_read")
def cm_mark_read(c, u, a):
    if a.get("id"):
        c.execute("UPDATE cm_notes SET read_at=? WHERE id=? AND user_id=?", (now(), int(a["id"]), u["id"]))
    else:
        c.execute("UPDATE cm_notes SET read_at=? WHERE user_id=? AND read_at IS NULL", (now(), u["id"]))
    return {"ok": True}


@api("cm.lists")
def cm_lists(c, u, a):
    pid = a.get("project_id")
    rows = q(c, "SELECT * FROM cm_lists WHERE active=1" + (" AND (project_id=? OR project_id IS NULL)" if pid else "") + " ORDER BY name", (int(pid),) if pid else ())
    for r in rows:
        r["members"] = json.loads(r["members"] or "[]")
        r["text"] = _list_text(c, r["id"])
    return rows


@api("cm.list_save", "project", "edit")
def cm_list_save(c, u, a):
    r = a.get("row") or {}
    if not (r.get("name") or "").strip():
        raise ApiError("Name the list.")
    mem = []
    for m in r.get("members") or []:
        if m.get("user_id"):
            mem.append({"user_id": int(m["user_id"])})
        elif (m.get("name") or "").strip():
            mem.append({k: m.get(k) for k in ("name", "org", "email", "phone") if m.get(k)})
    keep = {"name": r["name"].strip(), "members": json.dumps(mem), "project_id": _pid(r, False)}
    if r.get("id"):
        upd(c, "cm_lists", int(r["id"]), keep)
        return {"id": int(r["id"])}
    keep.update({"active": 1, "created_by": u["id"], "ts": now()})
    return {"id": ins(c, "cm_lists", keep)}


@api("cm.contacts", "project", "view")
def cm_contacts(c, u, a):
    pid = a.get("project_id")
    rows = q(c, "SELECT k.*, pa.name party FROM cm_contacts k LEFT JOIN parties pa ON pa.id=k.party_id WHERE k.active=1" +
             (" AND (k.project_id=? OR k.project_id IS NULL)" if pid else "") + " ORDER BY k.org, k.name", (int(pid),) if pid else ())
    staff = q(c, "SELECT u.id, u.name, u.username, u.role FROM users u WHERE u.active=1 ORDER BY u.name")
    return {"contacts": rows, "users": staff}


@api("cm.contact_save", "project", "edit")
def cm_contact_save(c, u, a):
    r = a.get("row") or {}
    keep = _keep(r, ("project_id", "name", "org", "role", "phone", "email", "party_id", "notes", "active"), ints=("project_id", "party_id", "active"))
    if r.get("id"):
        upd(c, "cm_contacts", int(r["id"]), keep)
        return {"id": int(r["id"])}
    if not (keep.get("name") or "").strip():
        raise ApiError("Write the name.")
    keep.update({"active": 1, "ts": now()})
    return {"id": ins(c, "cm_contacts", keep)}


# ═════════════════════════ document control ═════════════════════════
def _settings(c, pid):
    s = q1(c, "SELECT * FROM dm_settings WHERE project_id=?", (pid,))
    return dict(s) if s else {"project_id": pid, "pattern": "{P}-{DISC}-{TYPE}-{SEQ}", "org": ""}


@api("dm.folders", "project", "view")
def dm_folders(c, u, a):
    pid = _pid(a)
    if not val(c, "SELECT COUNT(*) FROM dm_folders WHERE project_id=?", (pid,), 0):
        for i, n in enumerate(DEFAULT_FOLDERS):
            c.execute("INSERT INTO dm_folders(project_id, parent_id, name, sort, active, ts) VALUES(?,NULL,?,?,1,?)", (pid, n, i + 1, now()))
    rows = q(c, "SELECT f.*, (SELECT COUNT(*) FROM dm_docs d WHERE d.folder_id=f.id AND d.active=1) docs FROM dm_folders f WHERE f.project_id=? AND f.active=1 "
                "ORDER BY f.sort, f.name", (pid,))
    return {"folders": rows, "settings": _settings(c, pid),
            "pending_reviews": val(c, "SELECT COUNT(*) FROM dm_reviews r JOIN dm_docs d ON d.id=r.doc_id WHERE d.project_id=? AND r.status='pending'", (pid,), 0),
            "unfiled": val(c, "SELECT COUNT(*) FROM dm_docs WHERE project_id=? AND folder_id IS NULL AND active=1", (pid,), 0)}


@api("dm.folder_save", "project", "edit")
def dm_folder_save(c, u, a):
    r = a.get("row") or {}
    if not (r.get("name") or "").strip():
        raise ApiError("Name the folder.")
    keep = {"name": r["name"].strip(), "parent_id": int(r["parent_id"]) if r.get("parent_id") else None}
    if "sort" in r and r["sort"] not in (None, ""):
        keep["sort"] = int(r["sort"])
    if r.get("id"):
        if "active" in r:
            if not int(r["active"]) and val(c, "SELECT COUNT(*) FROM dm_docs WHERE folder_id=? AND active=1", (int(r["id"]),), 0):
                raise ApiError("Move the documents out of this folder first.")
            keep["active"] = int(r["active"])
        upd(c, "dm_folders", int(r["id"]), keep)
        return {"id": int(r["id"])}
    pid = _pid(r)
    keep.update({"project_id": pid, "sort": keep.get("sort") or (val(c, "SELECT MAX(sort) FROM dm_folders WHERE project_id=?", (pid,), 0) or 0) + 1,
                 "active": 1, "ts": now()})
    return {"id": ins(c, "dm_folders", keep)}


@api("dm.settings_save", "project", "approve")
def dm_settings_save(c, u, a):
    pid = _pid(a)
    pat = (a.get("pattern") or "").strip() or "{P}-{DISC}-{TYPE}-{SEQ}"
    if "{SEQ}" not in pat:
        raise ApiError("The pattern needs {SEQ} so every number is different.")
    c.execute("INSERT OR REPLACE INTO dm_settings(project_id, pattern, org) VALUES(?,?,?)", (pid, pat, (a.get("org") or "").strip().upper()))
    return {"pattern": pat}


def _make_no(c, pid, disc, dtype, org=None):
    s = _settings(c, pid)
    base = s["pattern"].replace("{P}", _pcode(c, pid)).replace("{ORG}", (org or s.get("org") or "XX").upper()) \
        .replace("{DISC}", DISC_CODES.get(disc or "General", (disc or "GEN")[:3].upper())).replace("{TYPE}", (dtype or "OTH").upper())
    pre = base.split("{SEQ}")[0]
    n = 0
    for r in q(c, "SELECT doc_no FROM dm_docs WHERE project_id=? AND doc_no LIKE ?", (pid, pre.replace("%", "") + "%")):
        m = re.search(r"(\d+)\D*$", r["doc_no"][len(pre):] or "")
        if m:
            n = max(n, int(m.group(1)))
    return base.replace("{SEQ}", "%04d" % (n + 1))


def next_rev(cur):
    cur = (cur or "").strip()
    if not cur:
        return "0"
    m = re.match(r"^(.*?)(\d+)$", cur)
    if m:
        return m.group(1) + str(int(m.group(2)) + 1).zfill(len(m.group(2)))
    if re.match(r"^[A-Y]$", cur, re.I):
        return chr(ord(cur) + 1)
    return cur + "1"


def _doc_rows(c, where, params):
    rows = q(c, "SELECT d.*, f.name folder, r.status rev_status, r.file_id, r.ts rev_ts, fl.filename, uu.name author, "
                "(SELECT COUNT(*) FROM dm_revs x WHERE x.doc_id=d.id) revs, "
                "(SELECT COUNT(*) FROM dm_reviews v WHERE v.rev_id=d.current_rev_id AND v.status='pending') reviews_open "
                "FROM dm_docs d LEFT JOIN dm_folders f ON f.id=d.folder_id LEFT JOIN dm_revs r ON r.id=d.current_rev_id "
                "LEFT JOIN files fl ON fl.id=r.file_id LEFT JOIN users uu ON uu.id=d.created_by WHERE %s ORDER BY d.doc_no" % where, params)
    return rows


@api("dm.docs", "project", "view")
def dm_docs(c, u, a):
    w, p = ["d.project_id=?"], [_pid(a)]
    if not a.get("withdrawn"):
        w.append("d.active=1")
    if a.get("folder_id"):
        w.append("d.folder_id=?")
        p.append(int(a["folder_id"]))
    for k in ("doc_type", "discipline"):
        if a.get(k):
            w.append("d.%s=?" % k)
            p.append(a[k])
    if a.get("status"):
        w.append("r.status=?")
        p.append(a["status"])
    if a.get("q"):
        for word in str(a["q"]).split():
            w.append("(d.doc_no LIKE ? OR d.title LIKE ? OR d.tags LIKE ? OR d.originator LIKE ?)")
            p += ["%" + word + "%"] * 4
    rows = _doc_rows(c, " AND ".join(w), p)
    if not can(u, "project", "approve"):
        rows = [r for r in rows if not r.get("confidential") or r.get("created_by") == u["id"]]
    return rows


@api("dm.doc_get", "project", "view")
def dm_doc_get(c, u, a):
    rows = _doc_rows(c, "d.id=?", [int(a["id"])])
    if not rows:
        raise ApiError("Document not found.")
    d = rows[0]
    if d.get("confidential") and not can(u, "project", "approve") and d.get("created_by") != u["id"]:
        raise ApiError("This document is confidential.")
    d["revisions"] = q(c, "SELECT r.*, f.filename, f.size, uu.name by_name FROM dm_revs r LEFT JOIN files f ON f.id=r.file_id "
                          "LEFT JOIN users uu ON uu.id=r.uploaded_by WHERE r.doc_id=? ORDER BY r.id DESC", (d["id"],))
    d["reviews"] = q(c, "SELECT v.*, uu.name reviewer, r.rev FROM dm_reviews v LEFT JOIN users uu ON uu.id=v.reviewer_id "
                        "LEFT JOIN dm_revs r ON r.id=v.rev_id WHERE v.doc_id=? ORDER BY v.rev_id DESC, v.step, v.id", (d["id"],))
    d["transmittals"] = q(c, "SELECT t.id, t.no, t.date, t.to_name, t.purpose, t.status, r.rev FROM dm_trans_items i JOIN dm_transmittals t ON t.id=i.transmittal_id "
                             "LEFT JOIN dm_revs r ON r.id=i.rev_id WHERE i.doc_id=? ORDER BY t.id DESC", (d["id"],))
    d["next_rev"] = next_rev(d.get("current_rev"))
    return d


@api("dm.doc_save", "project", "edit")
def dm_doc_save(c, u, a):
    """New document (with its first revision and file) or a change to the document card."""
    r = a.get("row") or {}
    keep = _keep(r, ("folder_id", "title", "discipline", "doc_type", "originator", "confidential", "tags"), ints=("folder_id", "confidential"))
    if r.get("id"):
        old = q1(c, "SELECT * FROM dm_docs WHERE id=?", (int(r["id"]),))
        if not old:
            raise ApiError("Document not found.")
        if "active" in r:
            keep["active"] = 1 if int(r["active"] or 0) else 0
            if not keep["active"]:
                keep["status"] = "withdrawn"
        keep["updated"] = now()
        upd(c, "dm_docs", old["id"], keep)
        audit(c, u, "save", "dm_docs", old["id"], {"title": keep.get("title")})
        return {"id": old["id"]}
    pid = _pid(r)
    if not (keep.get("title") or "").strip():
        raise ApiError("Write the document title.")
    no = (r.get("doc_no") or "").strip().upper() or _make_no(c, pid, keep.get("discipline"), keep.get("doc_type"), r.get("org"))
    if val(c, "SELECT id FROM dm_docs WHERE project_id=? AND doc_no=?", (pid, no), None):
        raise ApiError("Document number %s is already used in this project - add a revision to it instead." % no)
    keep.update({"project_id": pid, "doc_no": no, "status": "draft", "active": 1, "created_by": u["id"], "ts": now(), "updated": now()})
    did = ins(c, "dm_docs", keep)
    rid = None
    if r.get("file_id") or r.get("rev"):
        rid = _add_rev(c, u, did, r.get("rev") or "0", r.get("file_id"), r.get("purpose"), r.get("note"), r.get("rev_status"))
    audit(c, u, "create", "dm_docs", did, {"doc_no": no})
    return {"id": did, "doc_no": no, "rev_id": rid}


def _add_rev(c, u, did, rev, file_id, purpose=None, note=None, status=None):
    d = q1(c, "SELECT * FROM dm_docs WHERE id=?", (did,))
    rev = (str(rev).strip() or next_rev(d.get("current_rev"))).upper()
    if val(c, "SELECT id FROM dm_revs WHERE doc_id=? AND UPPER(rev)=?", (did, rev), None):
        raise ApiError("Revision %s of %s already exists." % (rev, d["doc_no"]))
    st = status if status in ("draft", "for_info", "approved") else "draft"
    rid = ins(c, "dm_revs", {"doc_id": did, "rev": rev, "file_id": int(file_id) if file_id else None, "status": st,
                             "purpose": purpose, "note": note, "uploaded_by": u["id"], "ts": now()})
    if file_id:
        c.execute("UPDATE files SET entity='dm_revs', entity_id=?, project_id=COALESCE(project_id, ?) WHERE id=?", (rid, d["project_id"], int(file_id)))
    # the earlier revisions that are not under review are superseded
    c.execute("UPDATE dm_revs SET status='superseded' WHERE doc_id=? AND id<>? AND status NOT IN ('in_review','superseded','withdrawn')", (did, rid))
    upd(c, "dm_docs", did, {"current_rev": rev, "current_rev_id": rid, "status": st, "updated": now()})
    return rid


@api("dm.rev_add", "project", "edit")
def dm_rev_add(c, u, a):
    did = int(a["doc_id"])
    if not q1(c, "SELECT id FROM dm_docs WHERE id=? AND active=1", (did,)):
        raise ApiError("Document not found or withdrawn.")
    if not a.get("file_id"):
        raise ApiError("Attach the file of the new revision.")
    rid = _add_rev(c, u, did, a.get("rev") or "", a.get("file_id"), a.get("purpose"), a.get("note"), a.get("status"))
    audit(c, u, "create", "dm_revs", rid, {"doc_id": did})
    return {"id": rid}


@api("dm.review_start", "project", "edit")
def dm_review_start(c, u, a):
    rv = q1(c, "SELECT r.*, d.project_id, d.doc_no, d.title FROM dm_revs r JOIN dm_docs d ON d.id=r.doc_id WHERE r.id=?", (int(a["rev_id"]),))
    if not rv:
        raise ApiError("Revision not found.")
    if rv["status"] == "in_review":
        raise ApiError("This revision is already in review.")
    if rv["status"] == "superseded":
        raise ApiError("This revision is superseded - review the current one.")
    who = [int(x) for x in (a.get("reviewers") or []) if str(x).strip()]
    if not who:
        raise ApiError("Choose at least one reviewer.")
    mode = "sequential" if a.get("mode") == "sequential" else "parallel"
    due = a.get("due_date") or _add_days(today(), 7)
    for i, uid in enumerate(who):
        ins(c, "dm_reviews", {"rev_id": rv["id"], "doc_id": rv["doc_id"], "step": i + 1 if mode == "sequential" else 1, "reviewer_id": uid,
                              "due_date": due, "status": "pending" if (mode == "parallel" or i == 0) else "waiting", "ts": now()})
    upd(c, "dm_revs", rv["id"], {"status": "in_review", "review_due": due, "review_mode": mode, "result": None, "decided_on": None})
    upd(c, "dm_docs", rv["doc_id"], {"status": "in_review", "updated": now()})
    first = who if mode == "parallel" else who[:1]
    notify(c, first, "review", "Please review %s rev %s: %s" % (rv["doc_no"], rv["rev"], rv["title"]), "#/dm?doc=%d" % rv["doc_id"],
           rv["project_id"], u["id"], "Due %s" % due)
    audit(c, u, "review_start", "dm_revs", rv["id"], {"reviewers": who, "mode": mode})
    return {"reviewers": len(who), "due_date": due}


RESULT = {"A": "approved", "B": "approved_comments", "C": "revise", "D": "rejected"}


@api("dm.review_decide", "project", "view")
def dm_review_decide(c, u, a):
    v = q1(c, "SELECT * FROM dm_reviews WHERE id=?", (int(a["id"]),))
    if not v:
        raise ApiError("Review not found.")
    if v["reviewer_id"] != u["id"] and u["role"] != "admin":
        raise ApiError("Only the reviewer named on this line can decide it.")
    if v["status"] != "pending":
        raise ApiError("This review is not waiting for a decision.")
    dec = (a.get("decision") or "").upper()
    if dec not in RESULT:
        raise ApiError("Choose A, B, C or D.")
    if dec in ("B", "C", "D") and not (a.get("comment") or "").strip():
        raise ApiError("Write the comments - the author needs them to revise.")
    upd(c, "dm_reviews", v["id"], {"status": "done", "decision": dec, "comment": a.get("comment"), "decided_on": today()})
    rv = q1(c, "SELECT r.*, d.project_id, d.doc_no, d.title FROM dm_revs r JOIN dm_docs d ON d.id=r.doc_id WHERE r.id=?", (v["rev_id"],))
    nxt = q1(c, "SELECT * FROM dm_reviews WHERE rev_id=? AND status='waiting' ORDER BY step, id LIMIT 1", (v["rev_id"],))
    finished = False
    if dec == "D" and rv.get("review_mode") == "sequential":
        c.execute("UPDATE dm_reviews SET status='skipped' WHERE rev_id=? AND status='waiting'", (v["rev_id"],))
        nxt = None
    if nxt:
        upd(c, "dm_reviews", nxt["id"], {"status": "pending"})
        notify(c, [nxt["reviewer_id"]], "review", "Your turn to review %s rev %s: %s" % (rv["doc_no"], rv["rev"], rv["title"]),
               "#/dm?doc=%d" % rv["doc_id"], rv["project_id"], u["id"])
    elif not val(c, "SELECT COUNT(*) FROM dm_reviews WHERE rev_id=? AND status IN ('pending','waiting')", (v["rev_id"],), 0):
        decs = [r["decision"] for r in q(c, "SELECT decision FROM dm_reviews WHERE rev_id=? AND status='done'", (v["rev_id"],))]
        worst = max(decs or ["A"])                                            # A < B < C < D
        res = RESULT[worst]
        upd(c, "dm_revs", rv["id"], {"status": res, "result": worst, "decided_on": today()})
        upd(c, "dm_docs", rv["doc_id"], {"status": res, "updated": now()})
        notify(c, [rv["uploaded_by"]], "review", "%s rev %s came back: %s" % (rv["doc_no"], rv["rev"], dict(DECISIONS)[worst]),
               "#/dm?doc=%d" % rv["doc_id"], rv["project_id"], u["id"])
        finished = True
    c.execute("UPDATE cm_notes SET read_at=? WHERE user_id=? AND kind='review' AND link=? AND read_at IS NULL", (now(), u["id"], "#/dm?doc=%d" % rv["doc_id"]))
    audit(c, u, "review", "dm_reviews", v["id"], {"decision": dec})
    return {"finished": finished}


@api("dm.review_queue")
def dm_review_queue(c, u, a):
    rows = q(c, "SELECT v.*, d.doc_no, d.title, d.project_id, r.rev, r.file_id, f.filename, pr.code project FROM dm_reviews v JOIN dm_docs d ON d.id=v.doc_id "
                "JOIN dm_revs r ON r.id=v.rev_id LEFT JOIN files f ON f.id=r.file_id LEFT JOIN projects pr ON pr.id=d.project_id "
                "WHERE v.reviewer_id=? AND v.status='pending' ORDER BY v.due_date", (u["id"],))
    for r in rows:
        r["overdue"] = bool(r.get("due_date") and r["due_date"] < today())
    return rows


@api("dm.transmittals", "project", "view")
def dm_transmittals(c, u, a):
    rows = q(c, "SELECT t.*, pa.name party, (SELECT COUNT(*) FROM dm_trans_items i WHERE i.transmittal_id=t.id) items FROM dm_transmittals t "
                "LEFT JOIN parties pa ON pa.id=t.party_id WHERE t.project_id=? ORDER BY t.id DESC", (_pid(a),))
    td = today()
    for r in rows:
        r["overdue"] = bool(r["status"] == "sent" and r.get("response_due") and r["response_due"] < td)
    return rows


@api("dm.transmittal_get", "project", "view")
def dm_transmittal_get(c, u, a):
    t = q1(c, "SELECT t.*, pa.name party, pr.code project, pr.name project_name, uu.name by_name FROM dm_transmittals t LEFT JOIN parties pa ON pa.id=t.party_id "
              "LEFT JOIN projects pr ON pr.id=t.project_id LEFT JOIN users uu ON uu.id=t.created_by WHERE t.id=?", (int(a["id"]),))
    if not t:
        raise ApiError("Transmittal not found.")
    t["items"] = q(c, "SELECT i.*, d.doc_no, d.title, d.doc_type, r.rev, r.file_id, r.status rev_status FROM dm_trans_items i JOIN dm_docs d ON d.id=i.doc_id "
                      "LEFT JOIN dm_revs r ON r.id=i.rev_id WHERE i.transmittal_id=? ORDER BY d.doc_no", (t["id"],))
    t["list_text"] = _list_text(c, t.get("list_id"))
    return t


@api("dm.transmittal_save", "project", "edit")
def dm_transmittal_save(c, u, a):
    r = a.get("row") or {}
    keep = _keep(r, ("date", "party_id", "to_name", "attention", "list_id", "purpose", "subject", "response_due", "remarks"), ints=("party_id", "list_id"))
    if r.get("id"):
        old = q1(c, "SELECT * FROM dm_transmittals WHERE id=?", (int(r["id"]),))
        if not old:
            raise ApiError("Transmittal not found.")
        if old["status"] != "draft":
            raise ApiError("A transmittal that has been sent cannot be changed - make a new one.")
        tid = old["id"]
        upd(c, "dm_transmittals", tid, keep)
        c.execute("DELETE FROM dm_trans_items WHERE transmittal_id=?", (tid,))
    else:
        pid = _pid(r)
        if not (keep.get("party_id") or keep.get("to_name")):
            raise ApiError("Say who it is going to.")
        keep.update({"project_id": pid, "no": next_no(c, "%s-TRN" % _pcode(c, pid), keep.get("date") or today()), "date": keep.get("date") or today(),
                     "purpose": keep.get("purpose") or "for_information", "status": "draft", "created_by": u["id"], "ts": now()})
        if keep["purpose"] in ("for_review", "for_approval") and not keep.get("response_due"):
            keep["response_due"] = _add_days(keep["date"], 14)
        tid = ins(c, "dm_transmittals", keep)
    items = a.get("items") or []
    if not items:
        raise ApiError("Add at least one document.")
    for it in items:
        d = q1(c, "SELECT id, current_rev_id FROM dm_docs WHERE id=?", (int(it["doc_id"]),))
        if not d:
            continue
        ins(c, "dm_trans_items", {"transmittal_id": tid, "doc_id": d["id"], "rev_id": int(it.get("rev_id") or d["current_rev_id"] or 0) or None,
                                  "copies": int(it.get("copies") or 1), "format": it.get("format") or "PDF", "note": it.get("note")})
    return {"id": tid, "no": val(c, "SELECT no FROM dm_transmittals WHERE id=?", (tid,))}


@api("dm.transmittal_send", "project", "edit")
def dm_transmittal_send(c, u, a):
    t = q1(c, "SELECT * FROM dm_transmittals WHERE id=?", (int(a["id"]),))
    if not t:
        raise ApiError("Transmittal not found.")
    if t["status"] != "draft":
        raise ApiError("Already sent.")
    if not val(c, "SELECT COUNT(*) FROM dm_trans_items WHERE transmittal_id=?", (t["id"],), 0):
        raise ApiError("Add documents first.")
    upd(c, "dm_transmittals", t["id"], {"status": "sent", "sent_on": a.get("sent_on") or today()})
    # issued for construction / approval: the revision is shared
    if t["purpose"] in ("for_construction", "for_information", "for_tender", "as_built", "for_record"):
        c.execute("UPDATE dm_revs SET status='for_info' WHERE status='draft' AND id IN (SELECT rev_id FROM dm_trans_items WHERE transmittal_id=?)", (t["id"],))
    notify(c, _list_users(c, t.get("list_id")), "transmittal", "Transmittal %s: %s" % (t["no"], t.get("subject") or ""),
           "#/dm/transmittals?id=%d" % t["id"], t["project_id"], u["id"])
    audit(c, u, "send", "dm_transmittals", t["id"], {"no": t["no"]})
    return {"ok": True}


@api("dm.transmittal_ack", "project", "edit")
def dm_transmittal_ack(c, u, a):
    t = q1(c, "SELECT * FROM dm_transmittals WHERE id=?", (int(a["id"]),))
    if not t or t["status"] == "draft":
        raise ApiError("Send the transmittal first.")
    keep = {"ack_on": a.get("ack_on") or today(), "ack_by": a.get("ack_by"), "status": "acknowledged"}
    if (a.get("response") or "").strip():
        keep.update({"response": a["response"], "status": "responded"})
    if a.get("close"):
        keep["status"] = "closed"
    upd(c, "dm_transmittals", t["id"], keep)
    return {"status": keep["status"]}


@api("dm.register_xlsx", "project", "view")
def dm_register_xlsx(c, u, a):
    rows = dm_docs(c, u, a)
    cols = ["Document no.", "Title", "Folder", "Discipline", "Type", "Current rev", "Status", "Revisions", "Originator", "File", "Updated"]
    data_rows = [[r["doc_no"], r["title"], r.get("folder"), r.get("discipline"), r.get("doc_type"), r.get("current_rev"),
                  dict(REV_STATUS).get(r.get("rev_status") or r.get("status"), r.get("status")), r.get("revs"), r.get("originator"),
                  r.get("filename"), (r.get("updated") or "")[:10]] for r in rows]
    from api_copilot import make_xlsx
    data = make_xlsx("Document register - %s" % _pcode(c, _pid(a)), cols, data_rows)
    return {"filename": "document_register.xlsx", "b64": base64.b64encode(data).decode("ascii")}


# ═════════════════════════ hooks into search and My work ═════════════════════════
def _hook_search():
    try:
        import api_project as P
    except Exception:
        return
    if any(e.get("table") == "ca_letters" for e in P.SEARCH):
        return
    add = [P.S("Letters", "commercial", "ca_letters", "COALESCE(our_no,'')||' '||COALESCE(subject,'')",
               ["our_no", "their_ref", "subject", "summary", "body"], "#/ca/letters?id={id}",
               "CASE direction WHEN 'in' THEN 'In · ' ELSE 'Out · ' END||COALESCE(status,'')", "project_id", "date"),
           P.S("Documents", "project", "dm_docs", "doc_no||' '||title", ["doc_no", "title", "tags", "originator"], "#/dm?doc={id}",
               "COALESCE(doc_type,'')||' · rev '||COALESCE(current_rev,'-')||' · '||COALESCE(status,'')", "project_id", "substr(updated,1,10)"),
           P.S("Discussions", "project", "cm_threads", "title", ["title"], "#/cm?id={id}", "COALESCE(kind,'')", "project_id", "substr(last_ts,1,10)")]
    P.SEARCH.extend(add)
    for e in add:
        P.SEARCH_BY_GROUP[e["group"]] = e


def _hook_mywork():
    cur = FUNCS.get("fld.mywork")
    if not cur or getattr(cur[0], "_bco_cadmin", False):
        return
    orig = cur[0]

    def mywork(c, u, a, _orig=orig):
        d = _orig(c, u, a)
        items = d["items"]
        td, soon = today(), _add_days(today(), 7)

        def add(kind, title, project_id, due, link, status="", extra=""):
            items.append({"kind": kind, "title": title, "project_id": project_id, "due": due, "link": link, "status": status, "extra": extra,
                          "overdue": bool(due and due < td), "this_week": bool(due and td <= due <= soon)})
        for r in q(c, "SELECT * FROM ca_letters WHERE assigned_to=? AND status='open' AND reply_needed=1", (u["id"],)):
            add("Letter to answer", "%s %s" % (r["our_no"], r["subject"]), r["project_id"], r.get("reply_by"), "#/ca/letters?id=%d" % r["id"], "reply needed",
                r.get("their_ref") or "")
        for r in q(c, "SELECT v.*, d.doc_no, d.title, d.project_id, r.rev FROM dm_reviews v JOIN dm_docs d ON d.id=v.doc_id JOIN dm_revs r ON r.id=v.rev_id "
                      "WHERE v.reviewer_id=? AND v.status='pending'", (u["id"],)):
            add("Document review", "%s rev %s %s" % (r["doc_no"], r["rev"], r["title"]), r["project_id"], r.get("due_date"), "#/dm?doc=%d" % r["doc_id"], "your review")
        for r in q(c, "SELECT * FROM cm_notes WHERE user_id=? AND read_at IS NULL AND kind='mention' ORDER BY id DESC LIMIT 20", (u["id"],)):
            add("Mention", r["title"], r.get("project_id"), None, r["link"], "unread", (r.get("body") or "")[:80])
        if can(u, "commercial", "edit"):
            for r in q(c, "SELECT * FROM ca_timebars WHERE status='running' AND due_date<=?", (_add_days(td, 14),)):
                add("Time bar", "%s %s" % (r.get("clause") or "", r["title"]), r["project_id"], r["due_date"], "#/ca/timebars", "notice needed")
            for r in q(c, "SELECT * FROM ca_securities WHERE status IN ('active','extended','reduced') AND expiry_date<=?", (_add_days(td, 30),)):
                add("Bond / insurance expiry", "%s %s" % (dict(SEC_KINDS).get(r["kind"], r["kind"]), r.get("number") or ""), r.get("project_id"),
                    r["expiry_date"], "#/ca/securities", "extend or release", r.get("issuer") or "")
        items.sort(key=lambda x: (not x["overdue"], x["due"] is None, x["due"] or "9999"))
        d["counts"] = {"total": len(items), "overdue": sum(1 for x in items if x["overdue"]), "this_week": sum(1 for x in items if x["this_week"])}
        return d
    mywork._bco_cadmin = True
    FUNCS["fld.mywork"] = (mywork,) + tuple(cur[1:])
