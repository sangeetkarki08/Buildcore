"""
Claims register (BuildCore 2.34), ported from the Claims Register tool SULAV sent.

For each project's contract it keeps the form of contract (FIDIC 1999/2017 Red, Yellow, Silver, Gold, Emerald, Green,
MDB 2010, PPMO NCB and small works, or custom), the Particular Conditions periods and time bars, and the claim
clauses; for each claim event it works out the contract's claim timeline (notice, detailed claim, determination,
dissatisfaction, board, arbitration) with due dates and time-bar risk, and keeps the evidence checklist, the
contemporaneous records, the quantum calculator and the dates each step was done.

Claim events ARE BuildCore events (Commercial > Events & claims): a new claim adds an event row (type 'claim', number
EVT/...), and any existing event can be tracked here. Letters are the Correspondence register's letters (linked by
event); bonds come from Bonds, guarantees & insurance; IPC dates come from the 2.26 billing pipeline. New tables only:
cr_contracts (one per project) and cr_claims (one per tracked event), both holding the register's own fields as JSON.

The tender review, negotiation log, letters, strength score and quantum are worked out on the screen from the same
library (pages_crlib.js); this engine works out the deadlines so My work and the portfolio can list them.
Rights: the Commercial module (view to read, edit to change).
"""
import json
import os
from datetime import date, timedelta

from core import ApiError, audit, can, ins, next_no, now, q, q1, today, upd, val
import api_inventory as inv
from api_inventory import api

VERSION = "2.34.0"
FLAG = "_bco234"

SCHEMA = """
CREATE TABLE IF NOT EXISTS cr_contracts(id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL, data TEXT, created_by INTEGER,
  created_at TEXT, updated_by INTEGER, updated_at TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS ix_crc ON cr_contracts(project_id);
CREATE TABLE IF NOT EXISTS cr_claims(event_id INTEGER PRIMARY KEY, project_id INTEGER, origin TEXT DEFAULT 'cr', data TEXT,
  created_by INTEGER, created_at TEXT, updated_by INTEGER, updated_at TEXT);
CREATE INDEX IF NOT EXISTS ix_crcl ON cr_claims(project_id)
"""

_LIB = None


def lib():
    global _LIB
    if _LIB is None:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "claims_lib.json"), encoding="utf-8") as fh:
            _LIB = json.load(fh)
    return _LIB


def init_claims(c):
    for st in SCHEMA.strip().split(";"):
        if st.strip():
            c.execute(st)
    _hook_mywork()


# ───────────────────────── dates ─────────────────────────
def is_iso(s):
    if not isinstance(s, str) or len(s) != 10:
        return False
    try:
        date.fromisoformat(s)
        return True
    except ValueError:
        return False


def add_days(iso, n):
    if not is_iso(iso):
        return None
    return (date.fromisoformat(iso) + timedelta(days=int(round(n)))).isoformat()


def diff(a, b):
    return (date.fromisoformat(a) - date.fromisoformat(b)).days


def num(v):
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ───────────────────────── contract logic (same rules as the screen) ─────────────────────────
def book_of(p):
    B = lib()["BOOKS"]
    return B.get((p or {}).get("book")) or B["custom"]


def periods_of(p):
    out = {}
    po = (p or {}).get("po") or {}
    for x in book_of(p)["periods"]:
        o = po.get(x["k"])
        out[x["k"]] = float(o) if (o == 0 or (o is not None and o != "")) and num(o) is not None else x["d"]
    return out


def bar_of(p, k):
    x = next((y for y in book_of(p)["periods"] if y["k"] == k), None)
    o = ((p or {}).get("bo") or {}).get(k)
    return bool(x and x.get("bar")) if o is None else bool(o)


def tpl(s, b):
    return str(s or "").replace("{A}", b["admin"]).replace("{B}", b["board"])


def original_completion(p):
    if is_iso(p.get("commencement")) and num(p.get("tfcDays")):
        return add_days(p["commencement"], num(p["tfcDays"]))
    return None


def current_completion(p, evs):
    o = original_completion(p)
    return add_days(o, sum(num(e.get("eotGranted")) or 0 for e in evs)) if o else None


def is_closed(ev):
    return ev.get("outcome") in ("agreed", "withdrawn")


def build_steps(p, ev, evs, td=None):
    b = book_of(p)
    P = periods_of(p)
    PROC = lib()["PROC"]
    proc = PROC.get(b.get("proc")) or PROC["p99"]
    td = td or today()
    vals = {"aware": ev.get("aware") or ev.get("occurred"), "endEffects": ev.get("endEffects"), "notice": ev.get("notice"),
            "detailed": ev.get("detailed"), "final": ev.get("final"), "response": ev.get("response"), "nod1": ev.get("nod1"),
            "referral": ev.get("referral"), "boardDecision": ev.get("boardDecision"), "nod2": ev.get("nod2"),
            "arbitration": ev.get("arbitration"), "fmNotice": ev.get("fmNotice")}
    vals = {k: (v if is_iso(v) else None) for k, v in vals.items()}
    closed = is_closed(ev)
    dispute = bool(ev.get("dispute")) or (bool(vals["response"]) and bool(ev.get("outcome")) and not closed)
    due_by, out = {}, []
    for s in proc:
        if s.get("cont") and not ev.get("continuing"):
            continue
        if s.get("onlyCat") and ev.get("cat") != s["onlyCat"]:
            continue
        ks = s.get("k")
        if ks and any(P.get(k) is None for k in ks):
            continue
        base, deemed = vals.get(s.get("base")), False
        if not base and s.get("base") == "response":
            rs = next((x for x in proc if x["id"] == "response"), None)
            if rs and rs.get("deem") and due_by.get("response") and due_by["response"] < td and not closed:
                base, deemed, dispute = due_by["response"], True, True
        due, capped = None, False
        if base and ks:
            due = add_days(base, sum(P.get(k) or 0 for k in ks))
        if s.get("cap"):
            comp = current_completion(p, evs)
            if comp:
                cdate = add_days(comp, -(P.get(s["cap"]) or 0))
                if not due or cdate < due:
                    if due or vals["aware"]:
                        due = min(cdate, due) if due else cdate
                        capped = due == cdate
        due_by[s["id"]] = due
        if s.get("onlyIfLate"):
            if not (vals["notice"] and due_by.get("notice") and vals["notice"] > due_by["notice"]):
                continue
        done = vals.get(s["f"]) if s.get("f") else None
        is_bar = bar_of(p, s["bar"]) if s.get("bar") else False
        kind = s.get("kind")
        left = None
        if kind == "info":
            st = "info"
        elif s.get("disp") and not dispute and not done:
            st = "idle"
        elif done:
            st = ("barred" if is_bar else "late") if (due and done > due and kind not in ("earliest", "open")) else "done"
        elif kind == "open":
            st = "open"
        elif not due:
            st = "wait"
        elif kind == "earliest":
            left = diff(due, td)
            st = "open" if left <= 0 else "wait"
        else:
            left = diff(due, td)
            st = "over" if left < 0 else "soon" if left <= 7 else "up"
        if closed and not done and st != "info":
            st = "idle"
        refs = []
        for k in ks or []:
            r = next((x.get("r") for x in b["periods"] if x["k"] == k), None)
            if r and r not in refs:
                refs.append(r)
        out.append({"id": s["id"], "f": s.get("f"), "who": s.get("who"), "label": tpl(s.get("l"), b), "due": due, "done": done, "st": st,
                    "daysLeft": left, "bar": is_bar, "deemed": deemed, "capped": capped, "refText": ", ".join(refs)})
    return out


def next_step(steps):
    return next((s for s in steps if s["f"] and not s["done"] and s["st"] in ("over", "soon", "up", "open")), None)


def event_status(ev, b):
    o = ev.get("outcome")
    if o == "agreed":
        return "Agreed"
    if o == "withdrawn":
        return "Withdrawn"
    if ev.get("arbitration"):
        return "In arbitration"
    if ev.get("nod2"):
        return "Referred to arbitration" if b["fam"] == "ppmo" else "NOD on decision"
    if ev.get("boardDecision"):
        return "%s decided" % b["board"]
    if ev.get("referral"):
        return "With %s" % b["board"]
    if ev.get("nod1"):
        return "NOD given"
    if ev.get("response"):
        return "Rejected" if o == "rejected" else "Partly agreed" if o == "partial" else "Determined"
    if ev.get("detailed"):
        return "Claim submitted"
    if ev.get("notice"):
        return "Notice given"
    return "Watching"


def event_row_status(ev):
    """The Events & claims status that matches where the claim stands."""
    o = ev.get("outcome")
    if o == "agreed":
        return "agreed"
    if o == "withdrawn":
        return "closed"
    if o == "rejected" and not (ev.get("nod1") or ev.get("dispute")):
        return "rejected"
    if ev.get("detailed"):
        return "claimed"
    if ev.get("notice"):
        return "notified"
    return "open"


# ───────────────────────── storage ─────────────────────────
def _allowed(c, u):
    try:
        import api_workspace as W
        return W.allowed_projects(c, u)
    except Exception:
        return None


def _pid(c, u, a):
    pid = a.get("project_id")
    if pid in (None, "", 0, "0"):
        raise ApiError("Choose a project first.")
    pid = int(pid)
    if not val(c, "SELECT id FROM projects WHERE id=?", (pid,), None):
        raise ApiError("Project not found.")
    allow = _allowed(c, u)
    if allow is not None and pid not in allow:
        raise ApiError("PROJECT_DENIED: that project is not assigned to you.")
    return pid


def _loads(s, default):
    try:
        v = json.loads(s) if s else default
        return v if isinstance(v, type(default)) else default
    except (TypeError, ValueError):
        return default


def contract_of(c, pid):
    r = q1(c, "SELECT * FROM cr_contracts WHERE project_id=?", (pid,))
    return _loads(r["data"], {}) if r else None


def claims_of(c, pid):
    """Tracked claims of a project: the register's fields with the event row's number, title and status."""
    rows = q(c, "SELECT k.event_id, k.origin, k.data, k.updated_at, e.no, e.title e_title, e.date e_date, e.status e_status, e.type e_type, "
                "e.description e_desc, e.delay_days, e.cost_impact, e.clause e_clause FROM cr_claims k JOIN events e ON e.id=k.event_id "
                "WHERE k.project_id=? ORDER BY k.event_id", (pid,))
    out = []
    for r in rows:
        d = _loads(r["data"], {})
        d["id"] = r["event_id"]
        d["no"] = r["no"]
        d["origin"] = r["origin"]
        d["eventStatus"] = r["e_status"]
        d["eventType"] = r["e_type"]
        d["updatedAt"] = r["updated_at"]
        if not d.get("title"):
            d["title"] = r["e_title"]
        out.append(d)
    return out


CLEAN_DATES = ("occurred", "aware", "endEffects", "notice", "detailed", "final", "response", "nod1", "referral", "boardDecision",
               "nod2", "arbitration", "fmNotice")


def _clean_claim(d):
    d = dict(d or {})
    for k in ("id", "no", "origin", "eventStatus", "eventType", "updatedAt"):
        d.pop(k, None)
    for k in CLEAN_DATES:
        if d.get(k) and not is_iso(d[k]):
            raise ApiError("%s is not a date (use YYYY-MM-DD)." % k)
    for k in ("eotClaimed", "eotGranted", "costClaimed", "costGranted"):
        if d.get(k) not in (None, "") and num(d[k]) is None:
            raise ApiError("%s must be a number." % k)
        if num(d.get(k)) is not None and num(d[k]) < 0:
            raise ApiError("%s cannot be negative." % k)
    if d.get("outcome") not in (None, "", "agreed", "partial", "rejected", "withdrawn"):
        raise ApiError("Unknown outcome.")
    if not isinstance(d.get("refs") or [], list) or not isinstance(d.get("records") or [], list):
        raise ApiError("Clauses and records must be lists.")
    d["title"] = (d.get("title") or "").strip()[:300] or "New event"
    return d


def _sync_event(c, eid, pid, d, origin, p):
    """Keep the BuildCore event row in step with the claim. Older events tracked here only get blanks filled."""
    e = q1(c, "SELECT * FROM events WHERE id=?", (eid,))
    if not e:
        return
    others = [x for x in claims_of(c, pid) if x["id"] != eid] + [d]
    steps = build_steps(p, d, others) if p else []
    n = next((s for s in steps if s["id"] == "notice"), None)
    clause = "; ".join(str(r) for r in (d.get("refs") or []))[:200]
    sets = {}
    if origin == "cr":
        sets = {"title": d["title"], "date": d.get("occurred") or d.get("aware") or e["date"], "description": d.get("desc") or "",
                "clause": clause, "delay_days": num(d.get("eotGranted")) if num(d.get("eotGranted")) else (num(d.get("eotClaimed")) or 0),
                "cost_impact": num(d.get("costClaimed")) or 0, "mitigation": d.get("mitigation") or "", "status": event_row_status(d)}
        if n and n["due"]:
            sets["notice_deadline"] = n["due"]
    else:
        if not (e.get("clause") or "").strip() and clause:
            sets["clause"] = clause
        if not (e.get("notice_deadline") or "").strip() and n and n["due"]:
            sets["notice_deadline"] = n["due"]
    sets = {k: v for k, v in sets.items() if e.get(k) != v}
    if sets:
        upd(c, "events", eid, sets)


# ───────────────────────── engine actions ─────────────────────────
def _projects(c, u):
    allow = _allowed(c, u)
    return [p for p in q(c, "SELECT p.id, p.code, p.name, (SELECT COUNT(*) FROM cr_claims k WHERE k.project_id=p.id) claims, "
                            "(SELECT 1 FROM cr_contracts k WHERE k.project_id=p.id) has_contract FROM projects p ORDER BY p.code")
            if allow is None or p["id"] in allow]


def _payments(c, pid):
    """IPCs from the billing pipeline, as statements on the contract's payment clock."""
    out = []
    try:
        import api_fc as F
    except Exception:
        return out
    for i in q(c, "SELECT * FROM ipc WHERE project_id=? AND status<>'draft' ORDER BY date, id", (pid,)):
        try:
            s = F.ipc_state(c, i)
        except Exception:
            continue
        out.append({"id": "ipc%d" % i["id"], "ipc_id": i["id"], "no": i["no"], "statement": s.get("submitted_at") or i["date"],
                    "amount": s.get("claimed_net"), "certified": s.get("certified_at") if s.get("stage") not in ("submitted", "under_review", "prepared") else None,
                    "certAmount": s.get("payable"), "paid": s.get("paid_at") if s.get("stage") == "paid" else None, "stage": s.get("stage"),
                    "outstanding": s.get("outstanding"), "fromBuildcore": True})
    return out


@api("cr.meta", "commercial", "view")
def cr_meta(c, u, a):
    return {"version": VERSION, "projects": _projects(c, u), "can_edit": can(u, "commercial", "edit")}


@api("cr.get", "commercial", "view")
def cr_get(c, u, a):
    pid = _pid(c, u, a)
    pr = q1(c, "SELECT * FROM projects WHERE id=?", (pid,)) or {}
    pr = {k: pr.get(k) for k in ("id", "code", "name", "client", "location", "contract_value", "start_date", "ntp_date", "tfc_days",
                                 "completion_date", "ld_cap_pct", "contract_type")}
    tracked = {r["event_id"] for r in q(c, "SELECT event_id FROM cr_claims WHERE project_id=?", (pid,))}
    others = [e for e in q(c, "SELECT id, no, date, type, title, status, delay_days, cost_impact, clause FROM events WHERE project_id=? "
                              "ORDER BY date DESC, id DESC", (pid,)) if e["id"] not in tracked]
    letters = q(c, "SELECT id, our_no, their_ref, direction, date, subject, category, status, reply_needed, reply_by, event_id FROM ca_letters "
                   "WHERE project_id=? AND event_id IS NOT NULL ORDER BY date, id", (pid,)) if _has(c, "ca_letters") else []
    open_letters = q(c, "SELECT id, our_no, direction, date, subject, reply_by FROM ca_letters WHERE project_id=? AND status='open' AND reply_needed=1 "
                        "AND reply_by IS NOT NULL ORDER BY reply_by", (pid,)) if _has(c, "ca_letters") else []
    secs = q(c, "SELECT id, kind, number, issuer, amount, currency, expiry_date, status FROM ca_securities WHERE project_id=? "
                "AND status IN ('active','extended','reduced') ORDER BY expiry_date", (pid,)) if _has(c, "ca_securities") else []
    return {"project": pr, "contract": contract_of(c, pid), "claims": claims_of(c, pid), "events": others,
            "letters": letters, "open_letters": open_letters, "securities": secs, "ipcs": _payments(c, pid),
            "can_edit": can(u, "commercial", "edit"), "today": today()}


def _has(c, t):
    return bool(val(c, "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (t,), None))


@api("cr.contract_save", "commercial", "edit")
def cr_contract_save(c, u, a):
    pid = _pid(c, u, a)
    d = a.get("data")
    if not isinstance(d, dict):
        raise ApiError("Nothing to save.")
    d = dict(d)
    d.pop("id", None)
    if d.get("book") and d["book"] not in lib()["BOOKS"]:
        raise ApiError("Unknown form of contract.")
    for k in ("commencement", "baseDate", "loa", "n81", "accessDate", "dabDate", "advDate"):
        if d.get(k) and not is_iso(d[k]):
            raise ApiError("%s is not a date (use YYYY-MM-DD)." % k)
    for k in ("tfcDays", "price", "dnpDays", "ldPct", "ldCapPct", "financeRate"):
        if d.get(k) not in (None, "") and num(d[k]) is None:
            raise ApiError("%s must be a number." % k)
    raw = json.dumps(d, ensure_ascii=False)
    if len(raw) > 2_000_000:
        raise ApiError("The contract record is too large.")
    t = now()
    r = q1(c, "SELECT id FROM cr_contracts WHERE project_id=?", (pid,))
    if r:
        upd(c, "cr_contracts", r["id"], {"data": raw, "updated_by": u["id"], "updated_at": t})
    else:
        ins(c, "cr_contracts", {"project_id": pid, "data": raw, "created_by": u["id"], "created_at": t, "updated_by": u["id"], "updated_at": t})
    if a.get("audit", 1):
        audit(c, u, "save", "cr_contracts", pid, {"book": d.get("book"), "stage": d.get("stage")})
    # a change of periods or completion moves every claim's notice date
    for k in claims_of(c, pid):
        _sync_event(c, k["id"], pid, k, k["origin"], d)
    return {"project_id": pid}


@api("cr.claim_save", "commercial", "edit")
def cr_claim_save(c, u, a):
    pid = _pid(c, u, a)
    d = _clean_claim(a.get("data"))
    p = contract_of(c, pid)
    if p is None:
        raise ApiError("Set up the contract first (Contract & conditions).")
    t = now()
    eid = a.get("event_id") or (a.get("data") or {}).get("id")
    if eid:
        eid = int(eid)
        r = q1(c, "SELECT * FROM cr_claims WHERE event_id=?", (eid,))
        if not r or r["project_id"] != pid:
            raise ApiError("Claim not found on this project.")
        c.execute("UPDATE cr_claims SET data=?, updated_by=?, updated_at=? WHERE event_id=?",
                  (json.dumps(d, ensure_ascii=False), u["id"], t, eid))
        origin = r["origin"]
        new = False
    else:
        day = d.get("occurred") or d.get("aware") or today()
        eid = ins(c, "events", {"no": next_no(c, "EVT", day), "project_id": pid, "date": day, "type": "claim", "title": d["title"],
                                "description": d.get("desc") or "", "status": "open", "created_by": u["id"]})
        ins(c, "cr_claims", {"event_id": eid, "project_id": pid, "origin": "cr", "data": json.dumps(d, ensure_ascii=False),
                             "created_by": u["id"], "created_at": t, "updated_by": u["id"], "updated_at": t})
        origin = "cr"
        new = True
    _sync_event(c, eid, pid, d, origin, p)
    if new or a.get("audit"):
        audit(c, u, "create" if new else "save", "cr_claims", eid, {"title": d["title"]})
    return {"id": eid, "no": val(c, "SELECT no FROM events WHERE id=?", (eid,), None)}


@api("cr.track", "commercial", "edit")
def cr_track(c, u, a):
    """Follow an existing BuildCore event in the claims register."""
    e = q1(c, "SELECT * FROM events WHERE id=?", (int(a["event_id"]),))
    if not e:
        raise ApiError("Event not found.")
    pid = _pid(c, u, {"project_id": e["project_id"]})
    if val(c, "SELECT 1 FROM cr_claims WHERE event_id=?", (e["id"],), None):
        return {"id": e["id"]}
    p = contract_of(c, pid)
    if p is None:
        raise ApiError("Set up the contract first (Contract & conditions).")
    cat = {"variation": "variation", "instruction": "variation", "escalation": "escalation", "eot": "delay"}.get(e.get("type") or "", "delay")
    d = {"title": e["title"] or "Event %s" % (e["no"] or e["id"]), "cat": cat, "aware": e["date"] if is_iso(e["date"]) else today(),
         "occurred": e["date"] if is_iso(e["date"]) else None, "desc": e.get("description") or "", "mitigation": e.get("mitigation") or "",
         "refs": [], "evidence": {}, "records": []}
    if num(e.get("delay_days")):
        d["eotClaimed"] = num(e["delay_days"])
    if num(e.get("cost_impact")):
        d["costClaimed"] = num(e["cost_impact"])
    t = now()
    ins(c, "cr_claims", {"event_id": e["id"], "project_id": pid, "origin": "event", "data": json.dumps(d, ensure_ascii=False),
                         "created_by": u["id"], "created_at": t, "updated_by": u["id"], "updated_at": t})
    _sync_event(c, e["id"], pid, d, "event", p)
    audit(c, u, "track", "cr_claims", e["id"], {"event": e["no"]})
    return {"id": e["id"]}


@api("cr.claim_delete", "commercial", "edit")
def cr_claim_delete(c, u, a):
    """Stop tracking a claim. An event the register created is deleted too when nothing else points to it."""
    eid = int(a["event_id"])
    r = q1(c, "SELECT * FROM cr_claims WHERE event_id=?", (eid,))
    if not r:
        raise ApiError("Claim not found.")
    _pid(c, u, {"project_id": r["project_id"]})
    c.execute("DELETE FROM cr_claims WHERE event_id=?", (eid,))
    removed = False
    if r["origin"] == "cr":
        used = any(_has(c, t) and val(c, "SELECT 1 FROM %s WHERE event_id=? LIMIT 1" % t, (eid,), None)
                   for t in ("ca_letters", "variations", "ca_timebars"))
        used = used or bool(val(c, "SELECT 1 FROM files WHERE entity IN ('events','cr_claims') AND entity_id=? LIMIT 1", (eid,), None))
        if not used:
            c.execute("DELETE FROM events WHERE id=?", (eid,))
            removed = True
    audit(c, u, "delete", "cr_claims", eid, {"event_removed": removed})
    return {"event_removed": removed}


@api("cr.portfolio", "commercial", "view")
def cr_portfolio(c, u, a):
    """Every contract set up in the register (on projects this user may open), with its claims, for the All contracts view."""
    out = []
    only = a.get("project_id") if a.get("project_id") not in (None, "", 0, "0") else None
    for pr in _projects(c, u):
        if not pr["has_contract"] or (only and int(only) != pr["id"]):
            continue
        out.append({"project": {"id": pr["id"], "code": pr["code"], "name": pr["name"]}, "contract": contract_of(c, pr["id"]),
                    "claims": claims_of(c, pr["id"]),
                    "open_letters": q(c, "SELECT id, our_no, direction, date, subject, reply_by FROM ca_letters WHERE project_id=? AND status='open' "
                                         "AND reply_needed=1 AND reply_by IS NOT NULL", (pr["id"],)) if _has(c, "ca_letters") else [],
                    "securities": q(c, "SELECT id, kind, number, expiry_date FROM ca_securities WHERE project_id=? AND status IN ('active','extended','reduced')",
                                    (pr["id"],)) if _has(c, "ca_securities") else []})
    return {"contracts": out, "today": today()}


def due_steps(c, u, within=14):
    """Our claim steps due within `within` days or overdue, across the projects this user may open."""
    td = today()
    lim = add_days(td, within)
    allow = _allowed(c, u)
    out = []
    for r in q(c, "SELECT project_id, data FROM cr_contracts"):
        pid = r["project_id"]
        if allow is not None and pid not in allow:
            continue
        p = _loads(r["data"], {})
        if p.get("stage") == "tender":
            continue
        evs = claims_of(c, pid)
        for e in evs:
            if is_closed(e):
                continue
            nx = next_step(build_steps(p, e, evs, td))
            if nx and nx["due"] and nx["due"] <= lim and nx["who"] not in ("a", "b"):
                out.append({"project_id": pid, "event_id": e["id"], "no": e.get("no"), "title": e.get("title"), "step": nx["label"],
                            "due": nx["due"], "ref": nx["refText"], "bar": nx["bar"]})
    return out


def _hook_mywork():
    cur = inv.FUNCS.get("fld.mywork")
    if not cur or getattr(cur[0], FLAG, False):
        return
    orig = cur[0]

    def mywork(c, u, a, _orig=orig):
        d = _orig(c, u, a)
        if not can(u, "commercial", "edit"):
            return d
        try:
            steps = due_steps(c, u)
        except Exception:
            return d
        td, soon = today(), add_days(today(), 7)
        items = d.setdefault("items", [])
        for s in steps:
            items.append({"kind": "Claim deadline", "title": "%s %s: %s" % (s["no"] or "", s["title"] or "", s["step"]), "project_id": s["project_id"],
                          "due": s["due"], "link": "#/cr?tab=events&ev=%d" % s["event_id"], "status": "time bar" if s["bar"] else "claim step",
                          "extra": s["ref"] or "", "overdue": s["due"] < td, "this_week": td <= s["due"] <= soon})
        items.sort(key=lambda x: (not x.get("overdue"), x.get("due") is None, x.get("due") or "9999"))
        d["counts"] = {"total": len(items), "overdue": sum(1 for x in items if x.get("overdue")),
                       "this_week": sum(1 for x in items if x.get("this_week"))}
        return d
    setattr(mywork, FLAG, True)
    inv.FUNCS["fld.mywork"] = (mywork,) + tuple(cur[1:])


for _n in ("cr_meta", "cr_get", "cr_contract_save", "cr_claim_save", "cr_track", "cr_claim_delete", "cr_portfolio"):
    setattr(globals()[_n], FLAG, True)
