"""
Field and quality tools (BuildCore 2.15) - the everyday tools of Autodesk Build, Procore and Fieldwire,
made for Nepali sites and kept simple to enter:

  * My work      - one inbox per person: tasks, RFIs, issues, meeting actions, inspections and submittals
                   that are theirs, overdue first.
  * Drawings     - drawing register with revisions (the old revision is superseded automatically), PDF or image,
                   viewed in BuildCore with the issues pinned on the sheet.
  * Issues       - quality, safety observations, punch / snag list, design, warranty (after handover):
                   who, where (pin on a drawing), by when, photos, closed only after it is checked.
  * RFIs         - questions to the designer / engineer, ball-in-court, due date, answer, cost and time impact,
                   linked to events and variations; response days per party.
  * Meetings     - minutes with action items; actions become tasks and open ones carry to the next meeting.
  * Inspections  - check-list forms (pour card, scaffold, excavation, safety walk, house handover ...); a failed
                   item raises an issue by itself.
  * Quality dashboard and a client progress report written from the DPRs, photos and bills.
"""
import json
from datetime import date, timedelta

from core import ApiError, audit, ins, next_no, now, num, q, q1, r2, today, upd, val
from api_inventory import api

VERSION = "2.15.0"

SCHEMA = """
CREATE TABLE IF NOT EXISTS fld_drawings(id INTEGER PRIMARY KEY, project_id INTEGER, number TEXT, title TEXT, discipline TEXT,
  revision TEXT, rev_date TEXT, status TEXT DEFAULT 'for_construction', file_id INTEGER, current INTEGER DEFAULT 1,
  transmittal TEXT, remarks TEXT, created_by INTEGER, ts TEXT);
CREATE INDEX IF NOT EXISTS ix_fdr ON fld_drawings(project_id, number);
CREATE TABLE IF NOT EXISTS fld_issues(id INTEGER PRIMARY KEY, no TEXT, project_id INTEGER, type TEXT, title TEXT,
  description TEXT, location TEXT, drawing_id INTEGER, pin_x REAL, pin_y REAL, pin_page INTEGER, activity_id INTEGER,
  party_id INTEGER, assignee_user_id INTEGER, assignee TEXT, due_date TEXT, priority TEXT DEFAULT 'normal',
  status TEXT DEFAULT 'open', root_cause TEXT, cost REAL, source TEXT, source_id INTEGER, created_by INTEGER, ts TEXT,
  closed_on TEXT, closed_by INTEGER);
CREATE INDEX IF NOT EXISTS ix_fis ON fld_issues(project_id, status);
CREATE TABLE IF NOT EXISTS fld_rfis(id INTEGER PRIMARY KEY, no TEXT, project_id INTEGER, subject TEXT, question TEXT,
  discipline TEXT, location TEXT, drawing_id INTEGER, spec_ref TEXT, party_id INTEGER, assignee_user_id INTEGER,
  assignee TEXT, ball_in_court TEXT, due_date TEXT, priority TEXT DEFAULT 'normal', status TEXT DEFAULT 'open',
  answer TEXT, answered_by TEXT, answered_on TEXT, cost_impact TEXT, schedule_impact TEXT, event_id INTEGER,
  created_by INTEGER, ts TEXT, sent_on TEXT, closed_on TEXT);
CREATE INDEX IF NOT EXISTS ix_frf ON fld_rfis(project_id, status);
CREATE TABLE IF NOT EXISTS fld_meetings(id INTEGER PRIMARY KEY, no TEXT, project_id INTEGER, title TEXT, kind TEXT,
  date TEXT, time TEXT, place TEXT, attendees TEXT, notes TEXT, status TEXT DEFAULT 'draft', next_date TEXT,
  created_by INTEGER, ts TEXT);
CREATE TABLE IF NOT EXISTS fld_meeting_items(id INTEGER PRIMARY KEY, meeting_id INTEGER, sort INTEGER, topic TEXT,
  discussion TEXT, action TEXT, owner TEXT, owner_user_id INTEGER, due_date TEXT, status TEXT DEFAULT 'open',
  task_id INTEGER, carried_from INTEGER);
CREATE TABLE IF NOT EXISTS fld_templates(id INTEGER PRIMARY KEY, name TEXT, category TEXT, items TEXT, active INTEGER DEFAULT 1,
  system INTEGER DEFAULT 0, ts TEXT);
CREATE TABLE IF NOT EXISTS fld_inspections(id INTEGER PRIMARY KEY, no TEXT, project_id INTEGER, template_id INTEGER,
  title TEXT, date TEXT, location TEXT, activity_id INTEGER, party_id INTEGER, inspector TEXT, answers TEXT,
  result TEXT, failed INTEGER DEFAULT 0, remarks TEXT, status TEXT DEFAULT 'done', created_by INTEGER, ts TEXT);
"""

ISSUE_TYPES = [("quality", "Quality"), ("safety", "Safety observation"), ("punch", "Punch / snag"), ("design", "Design"),
               ("warranty", "Warranty / defect after handover"), ("other", "Other")]
ISSUE_STATUS = [("open", "Open"), ("in_progress", "Being fixed"), ("ready", "Ready to check"), ("closed", "Closed"), ("void", "Void")]
RFI_STATUS = [("draft", "Draft"), ("open", "Sent - waiting"), ("answered", "Answered"), ("closed", "Closed"), ("void", "Void")]
DISCIPLINES = ["Civil", "Structural", "Architectural", "Hydro-mechanical", "Electro-mechanical", "Electrical", "Plumbing",
               "Mechanical", "Geotechnical", "Survey", "Road", "Other"]

# starter inspection forms: [text, kind] - kind pf = pass / fail / not applicable, num = a number, text = words
STARTER_TEMPLATES = [
    ("Concrete pour card", "Quality", [
        ("Formwork line, level and plumb checked", "pf"), ("Formwork clean, oiled, joints tight", "pf"),
        ("Reinforcement as per drawing and bar bending schedule", "pf"), ("Cover blocks in place (mm)", "num"),
        ("Embedded items, sleeves and water stops placed", "pf"), ("Construction joint prepared", "pf"),
        ("Concrete grade / mix design", "text"), ("Slump (mm)", "num"), ("Cubes taken (sets)", "num"),
        ("Vibrators and standby available", "pf"), ("Curing arranged", "pf"), ("Engineer's approval to pour", "pf")]),
    ("Excavation and trench safety", "Safety", [
        ("Excavation deeper than 1.5 m is shored or sloped", "pf"), ("Spoil kept 1 m back from the edge", "pf"),
        ("Safe access (ladder / ramp)", "pf"), ("Edge barriers and warning tape", "pf"), ("Underground services located", "pf"),
        ("Water / dewatering under control", "pf"), ("Machines kept away from the edge", "pf"), ("Daily check by competent person", "pf")]),
    ("Scaffold and work at height", "Safety", [
        ("Base plates and sole boards on firm ground", "pf"), ("Bracing and ties in place", "pf"),
        ("Full boarded platforms, no gaps", "pf"), ("Guard rails and toe boards", "pf"), ("Safe ladder access", "pf"),
        ("Harness used and anchored above 2 m", "pf"), ("Scaffold tag / inspection date", "text")]),
    ("Weekly safety walk", "Safety", [
        ("Helmets, boots, vests worn", "pf"), ("Housekeeping - walkways clear", "pf"), ("Electrical cables and boards safe", "pf"),
        ("Fire extinguisher and first-aid box", "pf"), ("Machines with trained operator, guards in place", "pf"),
        ("Edge protection and openings covered", "pf"), ("Drinking water and toilets", "pf"), ("Toolbox talk held this week", "pf")]),
    ("Brick masonry and plaster", "Quality", [
        ("Bricks soaked before use", "pf"), ("Mortar mix as specified", "text"), ("Joints filled, thickness 10 mm", "pf"),
        ("Courses level and wall plumb", "pf"), ("Lintel and band as per drawing", "pf"), ("Curing done 7 days", "pf"),
        ("Plaster thickness (mm)", "num"), ("Plaster surface true to straight edge", "pf")]),
    ("House handover", "Handover", [
        ("Doors and windows open, close and lock", "pf"), ("All taps, flush and drains work, no leaks", "pf"),
        ("Every switch, socket and light works", "pf"), ("Earthing tested", "pf"), ("Roof / terrace water test, no leak", "pf"),
        ("Paint finish clean, no patches", "pf"), ("Tiles - no hollow, cracked or chipped tile", "pf"),
        ("Site cleaned, debris removed", "pf"), ("Keys, manuals and as-built drawings handed over", "pf")]),
]


def init_field(c):
    for st in SCHEMA.strip().split(";"):
        if st.strip():
            c.execute(st)
    if not c.execute("SELECT COUNT(*) FROM fld_templates").fetchone()[0]:
        for name, cat, items in STARTER_TEMPLATES:
            c.execute("INSERT INTO fld_templates(name, category, items, active, system, ts) VALUES(?,?,?,1,1,?)",
                      (name, cat, json.dumps([{"text": t, "kind": k} for t, k in items]), now()))


def _pid(a):
    if not a.get("project_id"):
        raise ApiError("Choose a project at the top first.")
    return int(a["project_id"])


def _days(d1, d2=None):
    try:
        a = date.fromisoformat(str(d1)[:10])
        b = date.fromisoformat(str(d2)[:10]) if d2 else date.today()
        return (b - a).days
    except (ValueError, TypeError):
        return None


def _user_name(c, uid):
    return val(c, "SELECT name FROM users WHERE id=?", (uid,), None) if uid else None


def _keep(r, cols, ints=(), nums=()):
    out = {}
    for k in cols:
        if k in r:
            v = r.get(k)
            if v == "":
                v = None
            if k in ints:
                v = int(v) if v not in (None, "") else None
            if k in nums:
                v = num(v) if v not in (None, "") else None
            out[k] = v
    return out


@api("fld.meta")
def meta(c, u, a):
    pid = a.get("project_id")
    return {"issue_types": ISSUE_TYPES, "issue_status": ISSUE_STATUS, "rfi_status": RFI_STATUS, "disciplines": DISCIPLINES,
            "users": q(c, "SELECT id, name, role FROM users WHERE active=1 ORDER BY name"),
            "parties": q(c, "SELECT id, code, name, kind FROM parties WHERE COALESCE(active,1)=1 ORDER BY name"),
            "drawings": q(c, "SELECT id, number, title, revision FROM fld_drawings WHERE current=1 AND project_id=? ORDER BY number",
                          (int(pid),)) if pid else [],
            "templates": q(c, "SELECT id, name, category FROM fld_templates WHERE active=1 ORDER BY category, name")}


# ───────────────────────── drawings ─────────────────────────
@api("fld.drawings", "project", "view")
def drawings(c, u, a):
    pid = _pid(a)
    w = "d.project_id=?" + ("" if a.get("all") else " AND d.current=1")
    rows = q(c, "SELECT d.*, f.filename, f.mime, (SELECT COUNT(*) FROM fld_drawings x WHERE x.project_id=d.project_id AND x.number=d.number) revs, "
                "(SELECT COUNT(*) FROM fld_issues i WHERE i.drawing_id=d.id AND i.status NOT IN ('closed','void')) open_issues "
                "FROM fld_drawings d LEFT JOIN files f ON f.id=d.file_id WHERE %s ORDER BY d.discipline, d.number, d.id DESC" % w, (pid,))
    return rows


@api("fld.drawing_history", "project", "view")
def drawing_history(c, u, a):
    d = q1(c, "SELECT * FROM fld_drawings WHERE id=?", (int(a["id"]),))
    if not d:
        raise ApiError("Drawing not found.")
    return q(c, "SELECT d.*, f.filename, f.mime FROM fld_drawings d LEFT JOIN files f ON f.id=d.file_id "
                "WHERE d.project_id=? AND d.number=? ORDER BY d.id DESC", (d["project_id"], d["number"]))


@api("fld.drawing_save", "project", "edit")
def drawing_save(c, u, a):
    r = a.get("row") or {}
    pid = _pid(r)
    if not (r.get("number") or "").strip():
        raise ApiError("Write the drawing number.")
    keep = _keep(r, ("number", "title", "discipline", "revision", "rev_date", "status", "file_id", "transmittal", "remarks"), ints=("file_id",))
    keep["number"] = keep["number"].strip().upper()
    if r.get("id"):
        upd(c, "fld_drawings", int(r["id"]), keep)
        return {"id": int(r["id"])}
    same = q1(c, "SELECT id, revision FROM fld_drawings WHERE project_id=? AND number=? AND current=1", (pid, keep["number"]))
    if same and (same["revision"] or "") == (keep.get("revision") or ""):
        raise ApiError("Revision %s of %s is already in the register - give the new revision its letter or number." % (keep.get("revision") or "-", keep["number"]))
    keep.update({"project_id": pid, "current": 1, "status": keep.get("status") or "for_construction", "created_by": u["id"], "ts": now()})
    did = ins(c, "fld_drawings", keep)
    if same:
        c.execute("UPDATE fld_drawings SET current=0, status='superseded' WHERE project_id=? AND number=? AND id<>?", (pid, keep["number"], did))
        # open issues pinned on the old revision follow the new sheet
        c.execute("UPDATE fld_issues SET drawing_id=? WHERE drawing_id=? AND status NOT IN ('closed','void')", (did, same["id"]))
    audit(c, u, "save", "fld_drawings", did, {"number": keep["number"], "revision": keep.get("revision")})
    return {"id": did, "superseded": same["id"] if same else None}


# ───────────────────────── issues and punch list ─────────────────────────
def _issue_rows(c, where, params):
    rows = q(c, "SELECT i.*, pa.name party, d.number drawing_no, pr.code project, uu.name assignee_name FROM fld_issues i "
                "LEFT JOIN parties pa ON pa.id=i.party_id LEFT JOIN fld_drawings d ON d.id=i.drawing_id "
                "LEFT JOIN projects pr ON pr.id=i.project_id LEFT JOIN users uu ON uu.id=i.assignee_user_id "
                "WHERE %s ORDER BY CASE i.status WHEN 'open' THEN 0 WHEN 'in_progress' THEN 1 WHEN 'ready' THEN 2 ELSE 3 END, "
                "i.due_date IS NULL, i.due_date, i.id DESC" % where, params)
    td = today()
    for r in rows:
        r["overdue"] = bool(r.get("due_date") and r["due_date"] < td and r["status"] not in ("closed", "void"))
        r["who"] = r.get("assignee_name") or r.get("assignee") or r.get("party") or ""
    return rows


@api("fld.issues", "project", "view")
def issues(c, u, a):
    w, p = ["i.project_id=?"], [_pid(a)]
    for k in ("type", "status"):
        if a.get(k):
            w.append("i.%s=?" % k)
            p.append(a[k])
    if a.get("drawing_id"):
        w.append("i.drawing_id=?")
        p.append(int(a["drawing_id"]))
    if a.get("open"):
        w.append("i.status NOT IN ('closed','void')")
    return _issue_rows(c, " AND ".join(w), p)


@api("fld.issue_save", "project", "view")
def issue_save(c, u, a):
    """Anyone who can see the project may report an issue (the point is that problems get reported);
    closing needs edit rights."""
    from core import can
    r = a.get("row") or {}
    keep = _keep(r, ("type", "title", "description", "location", "drawing_id", "pin_x", "pin_y", "pin_page", "activity_id",
                     "party_id", "assignee_user_id", "assignee", "due_date", "priority", "status", "root_cause", "cost"),
                 ints=("drawing_id", "pin_page", "activity_id", "party_id", "assignee_user_id"), nums=("pin_x", "pin_y", "cost"))
    if r.get("id"):
        old = q1(c, "SELECT * FROM fld_issues WHERE id=?", (int(r["id"]),))
        if not old:
            raise ApiError("Issue not found.")
        if keep.get("status") == "closed" and old["status"] != "closed":
            if not can(u, "project", "edit"):
                raise ApiError("Only someone with edit rights can close an issue (after checking the fix).")
            keep.update({"closed_on": today(), "closed_by": u["id"]})
        upd(c, "fld_issues", old["id"], keep)
        audit(c, u, "save", "fld_issues", old["id"], {"status": keep.get("status")})
        return {"id": old["id"]}
    pid = _pid(r)
    if not (keep.get("title") or "").strip():
        raise ApiError("Write what the issue is.")
    keep.update({"project_id": pid, "no": next_no(c, "ISS", today()), "type": keep.get("type") or "quality",
                 "status": keep.get("status") or "open", "created_by": u["id"], "ts": now(),
                 "source": r.get("source"), "source_id": int(r["source_id"]) if r.get("source_id") else None})
    if not keep.get("due_date"):
        keep["due_date"] = (date.today() + timedelta(days=7)).isoformat()
    iid = ins(c, "fld_issues", keep)
    audit(c, u, "create", "fld_issues", iid, {"title": keep["title"]})
    return {"id": iid, "no": keep["no"]}


# ───────────────────────── RFIs ─────────────────────────
@api("fld.rfis", "project", "view")
def rfis(c, u, a):
    w, p = ["r.project_id=?"], [_pid(a)]
    if a.get("status"):
        w.append("r.status=?")
        p.append(a["status"])
    rows = q(c, "SELECT r.*, pa.name party, d.number drawing_no, uu.name assignee_name FROM fld_rfis r LEFT JOIN parties pa ON pa.id=r.party_id "
                "LEFT JOIN fld_drawings d ON d.id=r.drawing_id LEFT JOIN users uu ON uu.id=r.assignee_user_id WHERE %s "
                "ORDER BY CASE r.status WHEN 'open' THEN 0 WHEN 'draft' THEN 1 WHEN 'answered' THEN 2 ELSE 3 END, r.due_date IS NULL, r.due_date, r.id DESC"
             % " AND ".join(w), p)
    td = today()
    for r in rows:
        r["overdue"] = bool(r.get("due_date") and r["due_date"] < td and r["status"] == "open")
        r["days_open"] = _days(r.get("sent_on") or r["ts"], r.get("answered_on")) if r["status"] in ("open", "answered", "closed") else None
        r["who"] = r.get("assignee_name") or r.get("assignee") or r.get("party") or ""
    return rows


@api("fld.rfi_save", "project", "edit")
def rfi_save(c, u, a):
    r = a.get("row") or {}
    keep = _keep(r, ("subject", "question", "discipline", "location", "drawing_id", "spec_ref", "party_id", "assignee_user_id",
                     "assignee", "ball_in_court", "due_date", "priority", "status", "answer", "answered_by", "answered_on",
                     "cost_impact", "schedule_impact"), ints=("drawing_id", "party_id", "assignee_user_id"))
    if r.get("id"):
        old = q1(c, "SELECT * FROM fld_rfis WHERE id=?", (int(r["id"]),))
        if not old:
            raise ApiError("RFI not found.")
        if keep.get("answer") and not old.get("answer") and keep.get("status") in (None, "open"):
            keep["status"] = "answered"
        if keep.get("status") == "answered" and not (keep.get("answered_on") or old.get("answered_on")):
            keep["answered_on"] = today()
        if keep.get("status") == "open" and not old.get("sent_on"):
            keep["sent_on"] = today()
        if keep.get("status") == "closed" and not old.get("closed_on"):
            keep["closed_on"] = today()
        upd(c, "fld_rfis", old["id"], keep)
        audit(c, u, "save", "fld_rfis", old["id"], {"status": keep.get("status")})
        return {"id": old["id"]}
    pid = _pid(r)
    if not (keep.get("subject") or "").strip() or not (keep.get("question") or "").strip():
        raise ApiError("Write the subject and the question.")
    keep.update({"project_id": pid, "no": next_no(c, "RFI", today()), "status": keep.get("status") or "open",
                 "created_by": u["id"], "ts": now()})
    if keep["status"] == "open":
        keep["sent_on"] = today()
    if not keep.get("due_date"):
        keep["due_date"] = (date.today() + timedelta(days=7)).isoformat()
    rid = ins(c, "fld_rfis", keep)
    audit(c, u, "create", "fld_rfis", rid, {"subject": keep["subject"]})
    return {"id": rid, "no": keep["no"]}


@api("fld.rfi_to_event", "commercial", "edit")
def rfi_to_event(c, u, a):
    """An answer that changes cost or time becomes an event (and from there a variation or claim)."""
    r = q1(c, "SELECT * FROM fld_rfis WHERE id=?", (int(a["id"]),))
    if not r:
        raise ApiError("RFI not found.")
    if r.get("event_id"):
        raise ApiError("This RFI already has an event.")
    no = next_no(c, "EVT", today())
    eid = ins(c, "events", {"no": no, "project_id": r["project_id"], "date": today(), "type": "instruction",
                            "title": "%s: %s" % (r["no"], r["subject"]), "description": "Question: %s\nAnswer: %s" % (r["question"], r.get("answer") or ""),
                            "status": "open", "created_by": u["id"]})
    upd(c, "fld_rfis", r["id"], {"event_id": eid})
    return {"event_id": eid, "no": no}


# ───────────────────────── meetings ─────────────────────────
@api("fld.meetings", "project", "view")
def meetings(c, u, a):
    return q(c, "SELECT m.*, (SELECT COUNT(*) FROM fld_meeting_items i WHERE i.meeting_id=m.id AND COALESCE(i.action,'')<>'' AND i.status='open') open_actions "
                "FROM fld_meetings m WHERE m.project_id=? ORDER BY m.date DESC, m.id DESC", (_pid(a),))


@api("fld.meeting_get", "project", "view")
def meeting_get(c, u, a):
    m = q1(c, "SELECT * FROM fld_meetings WHERE id=?", (int(a["id"]),))
    if not m:
        raise ApiError("Meeting not found.")
    m["items"] = q(c, "SELECT * FROM fld_meeting_items WHERE meeting_id=? ORDER BY sort, id", (m["id"],))
    return m


@api("fld.meeting_new", "project", "edit")
def meeting_new(c, u, a):
    """A new meeting of the same kind starts with the open actions of the last one carried forward."""
    pid = _pid(a)
    kind = a.get("kind") or "Site progress"
    no = next_no(c, "MOM", a.get("date") or today())
    mid = ins(c, "fld_meetings", {"no": no, "project_id": pid, "title": a.get("title") or "%s meeting" % kind, "kind": kind,
                                  "date": a.get("date") or today(), "status": "draft", "created_by": u["id"], "ts": now()})
    last = q1(c, "SELECT id, attendees, place FROM fld_meetings WHERE project_id=? AND kind=? AND id<>? ORDER BY date DESC, id DESC LIMIT 1",
              (pid, kind, mid))
    n = 0
    if last:
        upd(c, "fld_meetings", mid, {"attendees": last.get("attendees"), "place": last.get("place")})
        for it in q(c, "SELECT * FROM fld_meeting_items WHERE meeting_id=? AND COALESCE(action,'')<>'' AND status='open' ORDER BY sort", (last["id"],)):
            n += 1
            ins(c, "fld_meeting_items", {"meeting_id": mid, "sort": n, "topic": it["topic"], "discussion": "Carried forward",
                                         "action": it["action"], "owner": it["owner"], "owner_user_id": it["owner_user_id"],
                                         "due_date": it["due_date"], "status": "open", "task_id": it["task_id"],
                                         "carried_from": it.get("carried_from") or it["id"]})
    return {"id": mid, "no": no, "carried": n}


@api("fld.meeting_save", "project", "edit")
def meeting_save(c, u, a):
    r = a.get("row") or {}
    mid = int(r["id"])
    keep = _keep(r, ("title", "kind", "date", "time", "place", "attendees", "notes", "status", "next_date"))
    upd(c, "fld_meetings", mid, keep)
    m = q1(c, "SELECT * FROM fld_meetings WHERE id=?", (mid,))
    keep_ids = []
    for i, it in enumerate(a.get("items") or [], 1):
        if not any((it.get(k) or "").strip() for k in ("topic", "discussion", "action")):
            continue
        row = {"meeting_id": mid, "sort": i, "topic": it.get("topic"), "discussion": it.get("discussion"), "action": it.get("action"),
               "owner": it.get("owner"), "owner_user_id": int(it["owner_user_id"]) if it.get("owner_user_id") else None,
               "due_date": it.get("due_date") or None, "status": it.get("status") or "open"}
        if it.get("id"):
            upd(c, "fld_meeting_items", int(it["id"]), row)
            iid = int(it["id"])
        else:
            iid = ins(c, "fld_meeting_items", row)
        keep_ids.append(iid)
        cur = q1(c, "SELECT * FROM fld_meeting_items WHERE id=?", (iid,))
        # an action with an owner who uses BuildCore becomes (or updates) a task
        if (cur.get("action") or "").strip() and cur.get("owner_user_id"):
            if cur.get("task_id") and q1(c, "SELECT id FROM tasks WHERE id=?", (cur["task_id"],)):
                upd(c, "tasks", cur["task_id"], {"title": cur["action"][:200], "due_date": cur["due_date"], "assigned_to": cur["owner_user_id"],
                                                 "status": "done" if cur["status"] == "done" else "open"})
            else:
                tid = ins(c, "tasks", {"project_id": m["project_id"], "title": cur["action"][:200], "description": "From %s (%s)" % (m["no"], m["date"]),
                                       "due_date": cur["due_date"], "priority": "normal", "status": "done" if cur["status"] == "done" else "open",
                                       "assigned_to": cur["owner_user_id"], "source_type": "meeting", "source_id": mid,
                                       "created_by": u["id"], "ts": now()})
                upd(c, "fld_meeting_items", iid, {"task_id": tid})
        if cur.get("carried_from") and cur["status"] == "done":
            c.execute("UPDATE fld_meeting_items SET status='done' WHERE id=?", (cur["carried_from"],))
    if keep_ids:
        c.execute("DELETE FROM fld_meeting_items WHERE meeting_id=? AND id NOT IN (%s)" % ",".join("?" * len(keep_ids)), [mid] + keep_ids)
    else:
        c.execute("DELETE FROM fld_meeting_items WHERE meeting_id=?", (mid,))
    audit(c, u, "save", "fld_meetings", mid, {"items": len(keep_ids)})
    return meeting_get(c, u, {"id": mid})


# ───────────────────────── inspections ─────────────────────────
@api("fld.templates", "project", "view")
def templates(c, u, a):
    rows = q(c, "SELECT * FROM fld_templates WHERE active=1 ORDER BY category, name")
    for r in rows:
        r["items"] = json.loads(r["items"] or "[]")
    return rows


@api("fld.template_save", "project", "edit")
def template_save(c, u, a):
    r = a.get("row") or {}
    items = [{"text": (x.get("text") or "").strip(), "kind": x.get("kind") or "pf"} for x in r.get("items") or [] if (x.get("text") or "").strip()]
    if not (r.get("name") or "").strip() or not items:
        raise ApiError("Give the form a name and at least one check item.")
    data = {"name": r["name"].strip(), "category": r.get("category") or "Quality", "items": json.dumps(items), "active": 1, "ts": now()}
    if r.get("id"):
        upd(c, "fld_templates", int(r["id"]), data)
        return {"id": int(r["id"])}
    return {"id": ins(c, "fld_templates", data)}


@api("fld.inspections", "project", "view")
def inspections(c, u, a):
    return q(c, "SELECT i.*, t.name template, pa.name party FROM fld_inspections i LEFT JOIN fld_templates t ON t.id=i.template_id "
                "LEFT JOIN parties pa ON pa.id=i.party_id WHERE i.project_id=? ORDER BY i.date DESC, i.id DESC", (_pid(a),))


@api("fld.inspection_get", "project", "view")
def inspection_get(c, u, a):
    r = q1(c, "SELECT * FROM fld_inspections WHERE id=?", (int(a["id"]),))
    if not r:
        raise ApiError("Inspection not found.")
    r["answers"] = json.loads(r["answers"] or "[]")
    return r


@api("fld.inspection_save", "project", "edit")
def inspection_save(c, u, a):
    r = a.get("row") or {}
    pid = _pid(r)
    t = q1(c, "SELECT * FROM fld_templates WHERE id=?", (int(r["template_id"]),)) if r.get("template_id") else None
    if not t:
        raise ApiError("Choose the inspection form.")
    answers = a.get("answers") or []
    failed = [x for x in answers if x.get("kind") == "pf" and x.get("value") == "fail"]
    blank = [x for x in answers if x.get("kind") == "pf" and not x.get("value")]
    result = "fail" if failed else ("incomplete" if blank else "pass")
    keep = {"project_id": pid, "template_id": t["id"], "title": r.get("title") or t["name"], "date": r.get("date") or today(),
            "location": r.get("location"), "activity_id": int(r["activity_id"]) if r.get("activity_id") else None,
            "party_id": int(r["party_id"]) if r.get("party_id") else None, "inspector": r.get("inspector") or u.get("name"),
            "answers": json.dumps(answers), "result": result, "failed": len(failed), "remarks": r.get("remarks"), "status": "done"}
    if r.get("id"):
        iid = int(r["id"])
        upd(c, "fld_inspections", iid, keep)
        no = val(c, "SELECT no FROM fld_inspections WHERE id=?", (iid,), "")
    else:
        keep.update({"no": next_no(c, "INSP", keep["date"]), "created_by": u["id"], "ts": now()})
        iid = ins(c, "fld_inspections", keep)
        no = keep["no"]
    made = []
    for x in failed:
        if q1(c, "SELECT id FROM fld_issues WHERE source='inspection' AND source_id=? AND title=?", (iid, x["text"][:200])):
            continue
        res = issue_save(c, u, {"row": {"project_id": pid, "type": "safety" if (t["category"] or "").lower() == "safety" else "quality",
                                        "title": x["text"][:200], "description": "Failed in %s %s. %s" % (no, keep["title"], x.get("note") or ""),
                                        "location": keep["location"], "activity_id": keep["activity_id"], "party_id": keep["party_id"],
                                        "priority": "high", "source": "inspection", "source_id": iid}})
        made.append(res["no"])
    audit(c, u, "save", "fld_inspections", iid, {"result": result, "issues": made})
    return {"id": iid, "no": no, "result": result, "issues_raised": made}


# ───────────────────────── my work ─────────────────────────
@api("fld.mywork")
def mywork(c, u, a):
    """Everything waiting for this person, overdue first."""
    td = today()
    soon = (date.today() + timedelta(days=7)).isoformat()
    items = []
    pids = None
    try:
        if u.get("project_ids"):
            pids = {int(x) for x in str(u["project_ids"]).replace(";", ",").split(",") if x.strip().isdigit()}
    except Exception:
        pids = None

    def add(kind, title, project_id, due, link, status="", extra=""):
        if pids and project_id and project_id not in pids:
            return
        items.append({"kind": kind, "title": title, "project_id": project_id, "due": due, "link": link, "status": status,
                      "extra": extra, "overdue": bool(due and due < td), "this_week": bool(due and td <= due <= soon)})
    for t in q(c, "SELECT * FROM tasks WHERE assigned_to=? AND status NOT IN ('done','cancelled')", (u["id"],)):
        add("Task", t["title"], t["project_id"], t.get("due_date"), "#/p/tasks", t["status"])
    for r in q(c, "SELECT * FROM fld_issues WHERE assignee_user_id=? AND status IN ('open','in_progress')", (u["id"],)):
        add("Issue", "%s %s" % (r["no"], r["title"]), r["project_id"], r.get("due_date"), "#/f/issues?id=%d" % r["id"], r["status"], r.get("location") or "")
    for r in q(c, "SELECT * FROM fld_issues WHERE created_by=? AND status='ready'", (u["id"],)):
        add("Issue to check", "%s %s" % (r["no"], r["title"]), r["project_id"], r.get("due_date"), "#/f/issues?id=%d" % r["id"], "ready to check")
    for r in q(c, "SELECT * FROM fld_rfis WHERE assignee_user_id=? AND status='open'", (u["id"],)):
        add("RFI to answer", "%s %s" % (r["no"], r["subject"]), r["project_id"], r.get("due_date"), "#/f/rfis?id=%d" % r["id"], "waiting for you")
    for r in q(c, "SELECT * FROM fld_rfis WHERE created_by=? AND status='answered'", (u["id"],)):
        add("RFI answered", "%s %s" % (r["no"], r["subject"]), r["project_id"], None, "#/f/rfis?id=%d" % r["id"], "read and close")
    for r in q(c, "SELECT i.*, m.project_id, m.no mno FROM fld_meeting_items i JOIN fld_meetings m ON m.id=i.meeting_id "
                  "WHERE i.owner_user_id=? AND i.status='open' AND COALESCE(i.action,'')<>'' AND i.task_id IS NULL", (u["id"],)):
        add("Meeting action", r["action"], r["project_id"], r.get("due_date"), "#/f/meetings", "open", r["mno"])
    if u.get("role") in ("admin", "project_manager", "site_engineer", "director") and _has(c, "submittals"):
        for r in q(c, "SELECT * FROM submittals WHERE COALESCE(status,'') NOT IN ('approved','closed','rejected') AND "
                      "COALESCE(due_back, required_by) IS NOT NULL AND COALESCE(due_back, required_by)<=?", (soon,)):
            add("Submittal", "%s %s" % (r.get("no") or "", r["title"]), r["project_id"], r.get("due_back") or r.get("required_by"), "#/p/schedule?tab=6", r.get("status") or "")
    if u.get("role") in ("admin", "project_manager", "director") and _has(c, "hs_incidents"):
        for r in q(c, "SELECT * FROM hs_incidents WHERE status='open' AND kind IN ('lti','fatality','medical')"):
            add("Incident", "%s %s" % (r["no"], r.get("person") or r["kind"]), r["project_id"], r.get("action_due"), "#/hs?tab=incidents", "open")
    items.sort(key=lambda x: (not x["overdue"], x["due"] is None, x["due"] or "9999"))
    return {"items": items, "counts": {"total": len(items), "overdue": sum(1 for x in items if x["overdue"]),
                                       "this_week": sum(1 for x in items if x["this_week"])}}


def _has(c, t):
    return bool(c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (t,)).fetchone())


# ───────────────────────── quality dashboard ─────────────────────────
@api("fld.quality", "project", "view")
def quality(c, u, a):
    pid = _pid(a)
    td = date.today()
    iss = q(c, "SELECT * FROM fld_issues WHERE project_id=?", (pid,))
    weeks = []
    for k in range(11, -1, -1):
        ws = td - timedelta(days=td.weekday() + 7 * k)
        we = ws + timedelta(days=6)
        weeks.append({"week": ws.isoformat(), "opened": sum(1 for x in iss if ws.isoformat() <= (x["ts"] or "")[:10] <= we.isoformat()),
                      "closed": sum(1 for x in iss if x.get("closed_on") and ws.isoformat() <= x["closed_on"] <= we.isoformat())})
    open_ = [x for x in iss if x["status"] not in ("closed", "void")]
    closed = [x for x in iss if x["status"] == "closed" and x.get("closed_on")]
    by_type, by_party = {}, {}
    for x in open_:
        by_type[x["type"]] = by_type.get(x["type"], 0) + 1
        k = val(c, "SELECT name FROM parties WHERE id=?", (x["party_id"],), None) if x.get("party_id") else (x.get("assignee") or "Not assigned")
        g = by_party.setdefault(k or "Not assigned", {"who": k or "Not assigned", "open": 0, "overdue": 0})
        g["open"] += 1
        if x.get("due_date") and x["due_date"] < td.isoformat():
            g["overdue"] += 1
    rf = q(c, "SELECT r.*, pa.name party FROM fld_rfis r LEFT JOIN parties pa ON pa.id=r.party_id WHERE r.project_id=?", (pid,))
    resp = {}
    for r in rf:
        who = r.get("party") or r.get("assignee") or r.get("ball_in_court") or "—"
        g = resp.setdefault(who, {"who": who, "rfis": 0, "answered": 0, "days": [], "open": 0, "overdue": 0})
        g["rfis"] += 1
        if r.get("answered_on"):
            g["answered"] += 1
            d = _days(r.get("sent_on") or r["ts"], r["answered_on"])
            if d is not None:
                g["days"].append(d)
        if r["status"] == "open":
            g["open"] += 1
            if r.get("due_date") and r["due_date"] < td.isoformat():
                g["overdue"] += 1
    resp_rows = [{"who": g["who"], "rfis": g["rfis"], "answered": g["answered"], "open": g["open"], "overdue": g["overdue"],
                  "avg_days": round(sum(g["days"]) / len(g["days"]), 1) if g["days"] else None} for g in resp.values()]
    insp = q(c, "SELECT result, COUNT(*) n FROM fld_inspections WHERE project_id=? GROUP BY result", (pid,))
    return {"open": len(open_), "overdue": sum(1 for x in open_ if x.get("due_date") and x["due_date"] < td.isoformat()),
            "closed": len(closed), "avg_days_to_close": round(sum(_days(x["ts"], x["closed_on"]) or 0 for x in closed) / len(closed), 1) if closed else None,
            "weeks": weeks, "by_type": [{"type": k, "open": v} for k, v in sorted(by_type.items(), key=lambda kv: -kv[1])],
            "by_party": sorted(by_party.values(), key=lambda g: -g["open"]), "rfi_response": sorted(resp_rows, key=lambda g: -(g["avg_days"] or 0)),
            "rfi_open": sum(1 for r in rf if r["status"] == "open"), "inspections": {x["result"]: x["n"] for x in insp}}


# ───────────────────────── client progress report ─────────────────────────
@api("fld.client_report", "project", "view")
def client_report(c, u, a):
    """A plain progress report for the client or house owner, written from the DPRs, photos, issues and bills."""
    pid = _pid(a)
    p = q1(c, "SELECT * FROM projects WHERE id=?", (pid,))
    to = a.get("to") or today()
    frm = a.get("from") or (date.fromisoformat(to) - timedelta(days=7)).isoformat()
    boq = q1(c, "SELECT SUM(COALESCE(revised_qty,qty)*COALESCE(revised_rate,rate)) v, SUM(COALESCE(executed_qty,0)*COALESCE(revised_rate,rate)) e "
                "FROM boq_items WHERE project_id=?", (pid,)) or {}
    pct = round(100.0 * (boq.get("e") or 0) / boq["v"], 1) if boq.get("v") else None
    work = q(c, "SELECT a.name activity, a.unit, SUM(w.actual_qty) qty FROM dpr_work w JOIN dpr d ON d.id=w.dpr_id "
                "LEFT JOIN activities a ON a.id=w.activity_id WHERE d.project_id=? AND d.date BETWEEN ? AND ? AND w.actual_qty>0 "
                "GROUP BY w.activity_id ORDER BY qty DESC LIMIT 12", (pid, frm, to))
    days = val(c, "SELECT COUNT(DISTINCT date) FROM dpr WHERE project_id=? AND date BETWEEN ? AND ?", (pid, frm, to), 0)
    men = val(c, "SELECT COALESCE(SUM(l.count),0) FROM dpr_labour l JOIN dpr d ON d.id=l.dpr_id WHERE d.project_id=? AND d.date BETWEEN ? AND ?", (pid, frm, to), 0)
    delays = q(c, "SELECT x.category, SUM(x.hours) h FROM dpr_delays x JOIN dpr d ON d.id=x.dpr_id WHERE d.project_id=? AND d.date BETWEEN ? AND ? "
                  "GROUP BY x.category ORDER BY h DESC", (pid, frm, to))
    photos = q(c, "SELECT id, caption, date, location FROM files WHERE project_id=? AND kind='photo' AND COALESCE(date, substr(ts,1,10)) BETWEEN ? AND ? "
                  "ORDER BY id DESC LIMIT 12", (pid, frm, to))
    nxt = q(c, "SELECT name, planned_start, planned_finish FROM activities WHERE project_id=? AND planned_start<=? AND COALESCE(planned_finish,'9999')>=? "
               "AND COALESCE(actual_finish,'')='' ORDER BY planned_start LIMIT 8",
            (pid, (date.fromisoformat(to) + timedelta(days=14)).isoformat(), to))
    closed = val(c, "SELECT COUNT(*) FROM fld_issues WHERE project_id=? AND closed_on BETWEEN ? AND ?", (pid, frm, to), 0)
    open_i = val(c, "SELECT COUNT(*) FROM fld_issues WHERE project_id=? AND status NOT IN ('closed','void')", (pid,), 0)
    bills = q(c, "SELECT no, date, gross, status FROM ipc WHERE project_id=? AND status<>'draft' ORDER BY date", (pid,))
    lines = ["Progress report - %s" % p["name"], "Period: %s to %s" % (frm, to), ""]
    if pct is not None:
        lines.append("Overall progress: about %.0f%% of the work by value is done." % pct)
    lines.append("Work went on %d day(s) in this period, with %d worker-days on site." % (days or 0, men or 0))
    if work:
        lines += ["", "Work done this period:"] + ["- %s: %s %s" % (w["activity"] or "Work", "{:,.1f}".format(w["qty"] or 0), w["unit"] or "") for w in work]
    if delays:
        lines += ["", "Time lost: " + ", ".join("%s %.0f h" % (d["category"] or "other", d["h"] or 0) for d in delays) + "."]
    if nxt:
        lines += ["", "Planned for the next two weeks:"] + ["- %s" % n["name"] for n in nxt]
    lines += ["", "Snags and issues: %d fixed this period, %d still open." % (closed or 0, open_i or 0)]
    if bills:
        paid_note = "; ".join("%s (%s) Rs %s - %s" % (b["no"], b["date"], "{:,.0f}".format(b["gross"] or 0), b["status"]) for b in bills[-4:])
        lines += ["", "Bills: " + paid_note]
    return {"text": "\n".join(lines), "photos": photos, "from": frm, "to": to, "project": p["code"], "progress_pct": pct}
