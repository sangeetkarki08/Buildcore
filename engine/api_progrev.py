"""BuildCore 2.60 "Programme revisions and stages" (P6, P7, L2, R16).

* Programme revisions (P6): each baseline gets a status - draft, submitted (with the letter from the correspondence
  register), approved, rejected.  Approving one makes it the contract baseline (the current one progress is measured
  against).  EOT: the extension granted (events agreed and approved variations) moves the contractual completion, as
  before; the EOT tab shows the revised completion against the forecast finish and the current baseline, and
  "Save the revised programme" saves the calculated programme as a new draft baseline to submit.
* Gantt chart (P6): bars with link arrows, the critical path in red, baseline bars under the current bars, actual
  progress, data date and contract completion lines; zoom by week, month or quarter; English or Nepali months; print
  on A4, A3 or A1.  The bar column in the schedule table can be hidden (R16, setting pv_hide_bar, off).
* Project stages and checklists (P7): stage per project (tender, mobilisation, execution, substantial completion,
  defects period, closed) and a checklist for each stage from templates the company edits; items found in the books
  (performance security, insurance, programme, staff, machines, first IPC, retention, final bill) are ticked by
  themselves; alert "Stage checklist item late" in the alerts register (off on existing companies); company view by
  stage.
* Civil 3D quantities (L2): paste the Civil 3D volume report (Excel / CSV) or open a LandXML file with cross
  sections; the cut and fill between two chainages (average end area where no volume is given) become a draft
  measurement on the BOQ items chosen.
"""
import json
import re
import xml.etree.ElementTree as ET
from datetime import date, timedelta

import core
from core import ApiError, audit, ins, now, q, q1, setting, today, upd, val
import api_inventory as inv
from api_inventory import api

VERSION = "2.60.0"
FLAG = "_bco260"
EPS = 0.0005

SCHEMA = """
CREATE TABLE IF NOT EXISTS pv_base(baseline_id INTEGER PRIMARY KEY, status TEXT DEFAULT 'draft', letter_id INTEGER, submitted_on TEXT, decided_on TEXT,
  reason TEXT, note TEXT, user_id INTEGER, ts TEXT);
CREATE TABLE IF NOT EXISTS pv_stage(project_id INTEGER PRIMARY KEY, stage TEXT, since TEXT, target_end TEXT, note TEXT, user_id INTEGER, ts TEXT);
CREATE TABLE IF NOT EXISTS pv_stage_log(id INTEGER PRIMARY KEY, project_id INTEGER, stage TEXT, since TEXT, user_id INTEGER, ts TEXT);
CREATE TABLE IF NOT EXISTS pv_tpl(id INTEGER PRIMARY KEY, stage TEXT, item TEXT, auto TEXT, route TEXT, due_days INTEGER, sort INTEGER, active INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS pv_check(id INTEGER PRIMARY KEY, project_id INTEGER, tpl_id INTEGER, done_on TEXT, done_by INTEGER, note TEXT, ts TEXT,
  UNIQUE(project_id, tpl_id));
"""
STAGES = [("tender", "Tender"), ("mobilisation", "Mobilisation"), ("execution", "Execution"), ("substantial", "Substantial completion"),
          ("defects", "Defects liability period"), ("closed", "Closed")]
SLABEL = dict(STAGES)
TPL = [  # stage, item, auto check, route, due days after the stage starts
    ("tender", "Bid security submitted", "bid_security", "#/ca/securities", 0),
    ("tender", "Bid prices and markup approved", None, "#/c/bids", 0),
    ("mobilisation", "Site handed over (letter or minute)", None, "#/ca/letters", 14),
    ("mobilisation", "Performance security given", "perf_security", "#/ca/securities", 21),
    ("mobilisation", "Advance payment guarantee given (if advance taken)", "adv_security", "#/ca/securities", 21),
    ("mobilisation", "Contractor's all-risk / third-party insurance", "insurance", "#/ca/securities", 28),
    ("mobilisation", "Work programme submitted", "programme_submitted", "#/pv/revisions", 28),
    ("mobilisation", "Site camp, store and office set up", "store", "#/m/stores", 30),
    ("mobilisation", "Key staff on site (project manager, engineer)", "staff", "#/m/staff", 30),
    ("mobilisation", "Machines on site", "machines", "#/eq/register", 30),
    ("mobilisation", "Control budget prepared", "budget", "#/cl/budget", 45),
    ("execution", "First IPC submitted", "first_ipc", "#/p/ipc", 45),
    ("execution", "Programme approved by the Engineer", "programme_approved", "#/pv/revisions", 60),
    ("execution", "Quality plan and test lab in place", None, "#/qa", 45),
    ("substantial", "Snag list made and cleared", None, "#/fld/issues", 30),
    ("substantial", "As-built drawings submitted", None, "#/dl", 60),
    ("substantial", "Taking-over certificate received", None, "#/ca/letters", 60),
    ("substantial", "First half of retention claimed", "retention_claim", "#/sb/control?tab=5", 60),
    ("defects", "Defects notified during the period repaired", None, "#/fld/issues", 0),
    ("defects", "Performance certificate received", None, "#/ca/letters", 0),
    ("defects", "Retention released by the client", "retention_released", "#/sb/control?tab=5", 0),
    ("defects", "Final bill submitted", "final_bill", "#/p/ipc", 0),
    ("defects", "Securities released and returned", "securities_closed", "#/ca/securities", 0),
    ("closed", "Project closed in the books (CVR final)", None, "#/cl/close", 0),
]


def _f(x, d=0.0):
    try:
        return float(x) if x not in (None, "") else d
    except (TypeError, ValueError):
        return d


def r2(x):
    return round(_f(x) + 0.0, 2)


def _set(c, k, v):
    c.execute("INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (k, v))


def _has(c, t):
    return bool(q1(c, "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (t,)))


def _call(c, u, name, args):
    f, module, action, _p = inv.FUNCS[name]
    if module:
        core.require(u, module, action)
    return f(c, u, dict(args))


# ───────────────────────── P6: baselines with status ─────────────────────────
@api("pv.baselines", "project", "view")
def pv_baselines(c, u, a):
    pid = int(a["project_id"])
    rows = q(c, "SELECT b.*, s.status, s.letter_id, s.submitted_on, s.decided_on, s.reason, s.note snote, l.our_no letter_no, l.subject letter_subject "
                "FROM sched_baselines b LEFT JOIN pv_base s ON s.baseline_id=b.id LEFT JOIN ca_letters l ON l.id=s.letter_id WHERE b.project_id=? ORDER BY b.no", (pid,))
    for r in rows:
        r["status"] = r["status"] or ("in use, not recorded" if r["is_current"] else "not recorded")
        r["acts"] = val(c, "SELECT COUNT(*) FROM sched_baseline_acts WHERE baseline_id=?", (r["id"],))
    letters = q(c, "SELECT id, our_no, their_ref, date, subject, direction FROM ca_letters WHERE project_id=? ORDER BY date DESC LIMIT 200", (pid,)) if _has(c, "ca_letters") else []
    contract = [x for x in rows if x["status"] == "approved"]
    return {"rows": rows, "letters": letters, "contract_baseline": contract[-1]["id"] if contract else None}


@api("pv.base_status", "project", "approve")
def pv_base_status(c, u, a):
    b = q1(c, "SELECT * FROM sched_baselines WHERE id=?", (int(a["baseline_id"]),))
    if not b:
        raise ApiError("Baseline not found.")
    st = a.get("status")
    if st not in ("draft", "submitted", "approved", "rejected"):
        raise ApiError("Unknown status.")
    d = a.get("date") or today()
    cur = q1(c, "SELECT * FROM pv_base WHERE baseline_id=?", (b["id"],)) or {}
    row = {"status": st, "letter_id": int(a["letter_id"]) if a.get("letter_id") else cur.get("letter_id"), "note": a.get("note") if a.get("note") is not None else cur.get("note"),
           "submitted_on": d if st == "submitted" else cur.get("submitted_on"), "decided_on": d if st in ("approved", "rejected") else (None if st == "draft" else cur.get("decided_on")),
           "reason": a.get("reason") if st == "rejected" else cur.get("reason"), "user_id": u["id"], "ts": now()}
    if st == "rejected" and not (a.get("reason") or "").strip():
        raise ApiError("Give the Engineer's reason for rejecting.")
    c.execute("INSERT INTO pv_base(baseline_id, status, letter_id, submitted_on, decided_on, reason, note, user_id, ts) VALUES(?,?,?,?,?,?,?,?,?) "
              "ON CONFLICT(baseline_id) DO UPDATE SET status=excluded.status, letter_id=excluded.letter_id, submitted_on=excluded.submitted_on, "
              "decided_on=excluded.decided_on, reason=excluded.reason, note=excluded.note, user_id=excluded.user_id, ts=excluded.ts",
              (b["id"], row["status"], row["letter_id"], row["submitted_on"], row["decided_on"], row["reason"], row["note"], row["user_id"], row["ts"]))
    if st == "approved":
        _call(c, u, "base.set_current", {"id": b["id"]})
    audit(c, u, "baseline_status", "sched_baselines", b["id"], {"status": st, "letter": row["letter_id"]})
    return pv_baselines(c, u, {"project_id": b["project_id"]})


@api("pv.eot", "project", "view")
def pv_eot(c, u, a):
    pid = int(a["project_id"])
    import api_sched as SC
    p = q1(c, "SELECT * FROM projects WHERE id=?", (pid,))
    cd = SC.contract_dates(c, p)
    run = q1(c, "SELECT * FROM sched_runs WHERE project_id=? ORDER BY id DESC LIMIT 1", (pid,))
    cur = q1(c, "SELECT * FROM sched_baselines WHERE project_id=? AND is_current=1", (pid,))
    evs = q(c, "SELECT no, date, title, status, eot_claimed, eot_granted, delay_days FROM events WHERE project_id=? AND (COALESCE(eot_claimed,0)>0 OR COALESCE(eot_granted,0)>0) "
               "ORDER BY date", (pid,))
    vos = q(c, "SELECT no, date, title, status, time_impact_days FROM variations WHERE project_id=? AND COALESCE(time_impact_days,0)>0 ORDER BY date", (pid,))
    finish = run["finish"] if run else None
    since = cur["created"][:10] if cur and cur.get("created") else None
    granted_after = _f(val(c, "SELECT SUM(COALESCE(eot_granted,0)) FROM events WHERE project_id=? AND status IN ('agreed','closed') AND date>=?", (pid, since or "0000"))) if since else None
    gap = (date.fromisoformat(finish) - date.fromisoformat(cd["revised"])).days if finish and cd.get("revised") else None
    advice = None
    if cur and cd.get("revised") and cur["finish"] and cur["finish"] < cd["revised"] and granted_after:
        advice = "EOT of %s days was granted after the current baseline (%s). Calculate the schedule with the new completion and save the revised programme for submission." % (r2(granted_after), cur["name"])
    elif gap is not None and gap > 0:
        advice = "The forecast finish is %d days after the revised completion: recover time or claim more extension." % gap
    return {"contract": cd, "forecast_finish": finish, "data_date": run["data_date"] if run else None, "current_baseline": cur, "events": evs, "variations": vos,
            "late_days": gap, "advice": advice}


@api("pv.revise", "project", "approve")
def pv_revise(c, u, a):
    """Save the calculated programme as a new draft baseline (the revised programme to submit). The current one stays current until approved."""
    pid = int(a["project_id"])
    import api_sched as SC
    if not q1(c, "SELECT id FROM sched_runs WHERE project_id=?", (pid,)):
        raise ApiError("Calculate the schedule first.")
    cur = q1(c, "SELECT id FROM sched_baselines WHERE project_id=? AND is_current=1", (pid,))
    bid = SC._save_baseline(c, u, pid, a.get("name") or "Revised programme", a.get("data_date") or today())
    if cur:   # keep the measured baseline until the Engineer approves the revision
        c.execute("UPDATE sched_baselines SET is_current=0 WHERE project_id=?", (pid,))
        c.execute("UPDATE sched_baselines SET is_current=1 WHERE id=?", (cur["id"],))
    c.execute("INSERT OR REPLACE INTO pv_base(baseline_id, status, note, user_id, ts) VALUES(?, 'draft', ?, ?, ?)", (bid, a.get("note") or "Revised programme", u["id"], now()))
    audit(c, u, "revise", "schedule", pid, {"baseline": bid})
    return {"id": bid}


@api("pv.gantt", "project", "view")
def pv_gantt(c, u, a):
    pid = int(a["project_id"])
    import api_sched as SC
    p = q1(c, "SELECT * FROM projects WHERE id=?", (pid,))
    bid = int(a["baseline_id"]) if a.get("baseline_id") else val(c, "SELECT id FROM sched_baselines WHERE project_id=? AND is_current=1", (pid,))
    base = {r["activity_id"]: r for r in q(c, "SELECT activity_id, start, finish FROM sched_baseline_acts WHERE baseline_id=?", (bid,))} if bid else {}
    acts = []
    for x in q(c, "SELECT a.id, a.code, a.name, a.wbs_id, a.es, a.ef, a.ls, a.lf, a.tf, a.critical, a.planned_start, a.planned_finish, a.actual_start, a.actual_finish, "
                  "a.pct_complete, a.is_milestone, a.planned_qty, a.actual_qty, w.code wbs, w.name wbs_name FROM activities a LEFT JOIN wbs w ON w.id=a.wbs_id "
                  "WHERE a.project_id=? ORDER BY COALESCE(w.code,''), COALESCE(a.es, a.planned_start), a.code", (pid,)):
        s = x["actual_start"] or x["es"] or x["planned_start"]
        f = x["actual_finish"] or x["ef"] or x["planned_finish"]
        pct = _f(x["pct_complete"]) if x["pct_complete"] is not None else (100 * _f(x["actual_qty"]) / _f(x["planned_qty"]) if _f(x["planned_qty"]) > 0 else 0)
        b = base.get(x["id"]) or {}
        acts.append({"id": x["id"], "code": x["code"], "name": x["name"], "wbs": x["wbs"], "wbs_name": x["wbs_name"], "start": s, "finish": f, "tf": x["tf"],
                     "critical": bool(x["critical"]) or (x["tf"] is not None and _f(x["tf"]) <= 0 and not x["actual_finish"]), "done": bool(x["actual_finish"]),
                     "pct": round(min(100, max(0, pct)), 1), "milestone": bool(x["is_milestone"]), "b_start": b.get("start"), "b_finish": b.get("finish")})
    links = q(c, "SELECT pred_id, succ_id, type, lag FROM act_links WHERE project_id=?", (pid,))
    if not links:   # older programmes keep predecessors as text
        ids = {x["code"]: x["id"] for x in acts if x["code"]}
        for x in q(c, "SELECT id, predecessors FROM activities WHERE project_id=? AND COALESCE(predecessors,'')<>''", (pid,)):
            for tok in re.split(r"[,;\s]+", x["predecessors"]):
                m = re.match(r"^([A-Za-z0-9\-_.]+?)(FS|SS|FF|SF)?([+-]\d+)?$", tok.strip())
                if m and m.group(1) in ids:
                    links.append({"pred_id": ids[m.group(1)], "succ_id": x["id"], "type": m.group(2) or "FS", "lag": int(m.group(3) or 0)})
    run = q1(c, "SELECT data_date, finish FROM sched_runs WHERE project_id=? ORDER BY id DESC LIMIT 1", (pid,))
    cd = SC.contract_dates(c, p)
    bl = q(c, "SELECT b.id, b.no, b.name, s.status FROM sched_baselines b LEFT JOIN pv_base s ON s.baseline_id=b.id WHERE b.project_id=? ORDER BY b.no", (pid,))
    return {"project": {"code": p["code"], "name": p["name"]}, "acts": acts, "links": links, "data_date": (run or {}).get("data_date") or today(),
            "forecast_finish": (run or {}).get("finish"), "completion": cd.get("revised"), "baseline_id": bid, "baselines": bl, "hide_bar": setting(c, "pv_hide_bar") == "1"}


# ───────────────────────── P7: stages and checklists ─────────────────────────
def _auto(c, pid, key):
    """True / False from the books, None when BuildCore cannot tell."""
    if not key:
        return None
    try:
        if key in ("bid_security", "perf_security", "adv_security", "insurance"):
            if not _has(c, "ca_securities"):
                return None
            words = {"bid_security": "bid", "perf_security": "perform", "adv_security": "advance", "insurance": "insur"}[key]
            return bool(val(c, "SELECT COUNT(*) FROM ca_securities WHERE project_id=? AND LOWER(COALESCE(kind,'')) LIKE ?", (pid, "%" + words + "%")))
        if key == "securities_closed":
            return _has(c, "ca_securities") and not val(c, "SELECT COUNT(*) FROM ca_securities WHERE project_id=? AND COALESCE(status,'active')='active'", (pid,))
        if key == "programme_submitted":
            return bool(val(c, "SELECT COUNT(*) FROM pv_base s JOIN sched_baselines b ON b.id=s.baseline_id WHERE b.project_id=? AND s.status IN ('submitted','approved')", (pid,)))
        if key == "programme_approved":
            return bool(val(c, "SELECT COUNT(*) FROM pv_base s JOIN sched_baselines b ON b.id=s.baseline_id WHERE b.project_id=? AND s.status='approved'", (pid,)))
        if key == "store":
            return bool(val(c, "SELECT COUNT(*) FROM stores WHERE project_id=?", (pid,)))
        if key == "staff":
            ds = [(r["designation"] or "").lower() for r in q(c, "SELECT designation FROM staff WHERE project_id=? AND COALESCE(active,1)=1", (pid,))]
            return any("manager" in d for d in ds) and any("engineer" in d for d in ds)
        if key == "machines":
            return bool(val(c, "SELECT COUNT(*) FROM equipment WHERE project_id=? AND COALESCE(active,1)=1", (pid,)))
        if key == "budget":
            return _has(c, "cl_budget_versions") and bool(val(c, "SELECT COUNT(*) FROM cl_budget_versions WHERE project_id=?", (pid,)))
        if key == "first_ipc":
            return bool(val(c, "SELECT COUNT(*) FROM ipc WHERE project_id=? AND status IN ('submitted','certified')", (pid,)))
        if key == "final_bill":
            return None
        if key in ("retention_claim", "retention_released"):
            held = _f(val(c, "SELECT SUM(l.debit) FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id JOIN accounts ac ON ac.id=l.account_id WHERE ac.role='retention_receivable' "
                             "AND v.status='posted' AND COALESCE(l.project_id, v.project_id)=?", (pid,)))
            back = _f(val(c, "SELECT SUM(l.credit) FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id JOIN accounts ac ON ac.id=l.account_id WHERE ac.role='retention_receivable' "
                             "AND v.status='posted' AND COALESCE(l.project_id, v.project_id)=?", (pid,)))
            if held <= 0.5:
                return None
            return back > 0.5 if key == "retention_claim" else back >= held - 0.5
    except Exception:
        return None
    return None


def _guess_stage(c, p):
    if (p.get("status") or "") in ("closed", "completed"):
        return "closed"
    if val(c, "SELECT COUNT(*) FROM dpr WHERE project_id=?", (p["id"],)) or val(c, "SELECT COUNT(*) FROM ipc WHERE project_id=?", (p["id"],)):
        return "execution"
    if p.get("ntp_date") or val(c, "SELECT COUNT(*) FROM activities WHERE project_id=?", (p["id"],)):
        return "mobilisation"
    return "tender"


def stage_of(c, p):
    s = q1(c, "SELECT * FROM pv_stage WHERE project_id=?", (p["id"],))
    if s:
        return s["stage"], s["since"], s, False
    return _guess_stage(c, p), p.get("ntp_date") or p.get("start_date"), None, True


@api("pv.stage", "project", "view")
def pv_stage(c, u, a):
    pid = int(a["project_id"])
    p = q1(c, "SELECT * FROM projects WHERE id=?", (pid,))
    if not p:
        raise ApiError("Project not found.")
    stage, since, row, guessed = stage_of(c, p)
    order = [s for s, _l in STAGES]
    t = today()
    out = []
    for s, label in STAGES:
        items = []
        st_since = since if s == stage else val(c, "SELECT since FROM pv_stage_log WHERE project_id=? AND stage=? ORDER BY id DESC LIMIT 1", (pid, s))
        for tp in q(c, "SELECT * FROM pv_tpl WHERE stage=? AND active=1 ORDER BY sort, id", (s,)):
            ck = q1(c, "SELECT * FROM pv_check WHERE project_id=? AND tpl_id=?", (pid, tp["id"]))
            au = _auto(c, pid, tp["auto"])
            due = (date.fromisoformat(st_since[:10]) + timedelta(days=int(tp["due_days"] or 0))).isoformat() if st_since and tp["due_days"] else None
            done = bool(ck and ck["done_on"]) or au is True
            late = bool(not done and due and due < t and order.index(s) <= order.index(stage))
            items.append({"id": tp["id"], "item": tp["item"], "route": tp["route"], "auto": au, "done": done, "done_on": ck["done_on"] if ck else None,
                          "note": ck["note"] if ck else None, "due": due, "late": late})
        out.append({"stage": s, "label": label, "current": s == stage, "past": order.index(s) < order.index(stage), "since": st_since, "items": items,
                    "done": sum(1 for i in items if i["done"]), "total": len(items)})
    return {"project": {"id": p["id"], "code": p["code"], "name": p["name"]}, "stage": stage, "stage_label": SLABEL[stage], "since": since, "guessed": guessed,
            "target_end": row["target_end"] if row else None, "stages": out}


@api("pv.stage_save", "project", "approve")
def pv_stage_save(c, u, a):
    pid = int(a["project_id"])
    st = a.get("stage")
    if st not in SLABEL:
        raise ApiError("Choose the stage.")
    since = a.get("since") or today()
    old = q1(c, "SELECT stage FROM pv_stage WHERE project_id=?", (pid,))
    c.execute("INSERT INTO pv_stage(project_id, stage, since, target_end, note, user_id, ts) VALUES(?,?,?,?,?,?,?) ON CONFLICT(project_id) DO UPDATE SET "
              "stage=excluded.stage, since=excluded.since, target_end=excluded.target_end, note=excluded.note, user_id=excluded.user_id, ts=excluded.ts",
              (pid, st, since, a.get("target_end") or None, a.get("note"), u["id"], now()))
    if not old or old["stage"] != st:
        ins(c, "pv_stage_log", {"project_id": pid, "stage": st, "since": since, "user_id": u["id"], "ts": now()})
    audit(c, u, "stage", "projects", pid, {"stage": st, "since": since})
    return pv_stage(c, u, {"project_id": pid})


@api("pv.check_save", "project", "edit")
def pv_check_save(c, u, a):
    pid, tid = int(a["project_id"]), int(a["tpl_id"])
    done = a.get("done") in (1, "1", True)
    c.execute("INSERT INTO pv_check(project_id, tpl_id, done_on, done_by, note, ts) VALUES(?,?,?,?,?,?) ON CONFLICT(project_id, tpl_id) DO UPDATE SET "
              "done_on=excluded.done_on, done_by=excluded.done_by, note=excluded.note, ts=excluded.ts",
              (pid, tid, (a.get("done_on") or today()) if done else None, u["id"] if done else None, a.get("note"), now()))
    audit(c, u, "check", "pv_check", tid, {"project": pid, "done": done})
    return {"ok": True}


@api("pv.tpl", "project", "view")
def pv_tpl(c, u, a):
    return {"rows": q(c, "SELECT * FROM pv_tpl ORDER BY CASE stage " + " ".join("WHEN '%s' THEN %d" % (s, i) for i, (s, _l) in enumerate(STAGES)) + " END, sort, id"),
            "stages": [{"key": s, "label": l} for s, l in STAGES]}


@api("pv.tpl_save", "admin", "edit")
def pv_tpl_save(c, u, a):
    r = a.get("row") or {}
    if r.get("stage") not in SLABEL or not (r.get("item") or "").strip():
        raise ApiError("Stage and item are needed.")
    data = {"stage": r["stage"], "item": r["item"].strip(), "route": r.get("route") or None, "due_days": int(_f(r.get("due_days"))),
            "sort": int(_f(r.get("sort"), 50)), "active": 0 if r.get("active") in (0, "0", False) else 1}
    if r.get("id"):
        upd(c, "pv_tpl", int(r["id"]), data)
        tid = int(r["id"])
    else:
        tid = ins(c, "pv_tpl", data)
    audit(c, u, "save", "pv_tpl", tid, data)
    return {"id": tid}


@api("pv.company", "project", "view")
def pv_company(c, u, a):
    out = []
    for p in q(c, "SELECT * FROM projects WHERE COALESCE(kind,'project') NOT IN ('trading','general') ORDER BY code"):
        d = pv_stage(c, u, {"project_id": p["id"]})
        cur = next(s for s in d["stages"] if s["current"])
        late = [i["item"] for s in d["stages"] for i in s["items"] if i["late"]]
        out.append({"project_id": p["id"], "project": p["code"], "name": p["name"], "stage": d["stage"], "stage_label": d["stage_label"], "since": d["since"],
                    "guessed": d["guessed"], "done": cur["done"], "total": cur["total"], "late": late, "target_end": d["target_end"],
                    "overrun": bool(d["target_end"] and d["target_end"] < today() and d["stage"] != "closed")})
    return {"rows": out, "stages": [{"key": s, "label": l, "count": sum(1 for r in out if r["stage"] == s)} for s, l in STAGES]}


# ───────────────────────── L2: Civil 3D quantities ─────────────────────────
def _sta(v):
    s = str(v or "").strip().replace(" ", "")
    m = re.match(r"^(\d+)\+(\d+(?:\.\d+)?)$", s)
    if m:
        return float(m.group(1)) * 1000 + float(m.group(2))
    return float(s.replace(",", ""))


def parse_c3d(text):
    text = (text or "").strip()
    rows = []
    if text.startswith("<") or "<LandXML" in text[:500]:
        try:
            root = ET.fromstring(text.encode("utf-8") if isinstance(text, str) else text)
        except ET.ParseError as e:
            raise ApiError("The LandXML file could not be read: %s" % e)
        for el in root.iter():
            if el.tag.split("}")[-1] == "CrossSect":
                at = {k.lower(): v for k, v in el.attrib.items()}
                if "sta" not in at:
                    continue
                rows.append({"sta": _f(at.get("sta")), "cut_area": _f(at.get("areacut")), "fill_area": _f(at.get("areafill")),
                             "cut_vol": _f(at.get("volumecut"), None), "fill_vol": _f(at.get("volumefill"), None)})
        src = "LandXML"
    else:
        lines = [l for l in re.split(r"\r?\n", text) if l.strip()]
        if not lines:
            raise ApiError("Nothing pasted.")
        sep = "\t" if "\t" in lines[0] else ","
        hdr = None
        for i, l in enumerate(lines[:15]):
            cells = [x.strip().lower() for x in l.split(sep)]
            if any("station" in x or x in ("sta", "chainage", "ch") for x in cells) and any("cut" in x for x in cells + [""]) or any("fill" in x for x in cells):
                if any("station" in x or x in ("sta", "chainage", "ch") for x in cells):
                    hdr = (i, cells)
                    break
        if not hdr:
            raise ApiError("No header row with Station, Cut and Fill found. Paste the Civil 3D volume report with its headings.")
        i0, cells = hdr

        def col(*words, avoid=()):
            for j, x in enumerate(cells):
                if all(w in x for w in words) and not any(v in x for v in avoid):
                    return j
            return None
        js = col("station") if col("station") is not None else next(j for j, x in enumerate(cells) if x in ("sta", "chainage", "ch"))
        jca, jfa = col("cut", "area"), col("fill", "area")
        jcv = col("cut", "vol", avoid=("cum",)) if col("cut", "vol", avoid=("cum",)) is not None else col("cut", avoid=("area", "cum"))
        jfv = col("fill", "vol", avoid=("cum",)) if col("fill", "vol", avoid=("cum",)) is not None else col("fill", avoid=("area", "cum"))
        for l in lines[i0 + 1:]:
            x = [v.strip().strip('"') for v in l.split(sep)]
            try:
                st = _sta(x[js])
            except (ValueError, IndexError):
                continue
            g = lambda j: _f(x[j].replace(",", ""), None) if j is not None and j < len(x) else None
            rows.append({"sta": st, "cut_area": g(jca), "fill_area": g(jfa), "cut_vol": g(jcv), "fill_vol": g(jfv)})
        src = "volume report"
    rows.sort(key=lambda r: r["sta"])
    if len(rows) < 2:
        raise ApiError("At least two stations are needed.")
    # incremental volume per station (volume given, else average end area)
    for k, r in enumerate(rows):
        if k == 0:
            r["cut"], r["fill"] = 0.0, 0.0
            continue
        p = rows[k - 1]
        L = r["sta"] - p["sta"]
        r["cut"] = r["cut_vol"] if r["cut_vol"] is not None else ((_f(p["cut_area"]) + _f(r["cut_area"])) / 2 * L)
        r["fill"] = r["fill_vol"] if r["fill_vol"] is not None else ((_f(p["fill_area"]) + _f(r["fill_area"])) / 2 * L)
    return rows, src


def _ch(x):
    km = int(x // 1000)
    return "%d+%03d" % (km, int(round(x - km * 1000)))


@api("pv.c3d_preview", "commercial", "view")
def pv_c3d_preview(c, u, a):
    rows, src = parse_c3d(a.get("text"))
    lo = _sta(a["from"]) if a.get("from") not in (None, "") else rows[0]["sta"]
    hi = _sta(a["to"]) if a.get("to") not in (None, "") else rows[-1]["sta"]
    inside = [r for r in rows if lo < r["sta"] <= hi + EPS]
    cut = sum(r["cut"] for r in inside)
    fill = sum(r["fill"] for r in inside)
    return {"source": src, "stations": len(rows), "first": _ch(rows[0]["sta"]), "last": _ch(rows[-1]["sta"]), "from": _ch(lo), "to": _ch(hi),
            "cut": round(cut, 3), "fill": round(fill, 3), "rows": [dict(r, ch=_ch(r["sta"]), cut=round(r["cut"], 3), fill=round(r["fill"], 3)) for r in rows[:400]]}


@api("pv.c3d_make", "commercial", "edit")
def pv_c3d_make(c, u, a):
    pid = int(a["project_id"])
    d = pv_c3d_preview(c, u, a)
    lines = []
    loc = "Ch %s - %s (Civil 3D %s)" % (d["from"], d["to"], d["source"])
    for k, key in (("cut_boq_id", "cut"), ("fill_boq_id", "fill")):
        if a.get(k) and d[key] > EPS:
            lines.append({"boq_item_id": int(a[k]), "qty": d[key], "location": loc, "remarks": "%s from Civil 3D" % key})
    if not lines:
        raise ApiError("Choose the BOQ item for cut and / or fill.")
    r = _call(c, u, "meas.save", {"header": {"project_id": pid, "date": a.get("date") or today(), "remarks": "Civil 3D quantities " + loc}, "lines": lines})
    return {"id": r["id"], "cut": d["cut"], "fill": d["fill"]}


# ───────────────────────── alerts ─────────────────────────
NEW_KINDS = [("stage_item_late", "Stage checklist item late", "time", "medium", 0, "", "project_manager", 7, 7)]
NEW_ACTIONS = {"stage_item_late": "Open the project's Stages & checklists, finish the item or note why it waits."}


def chk_stage(c, R, ctx):
    import api_fcc as F
    out = []
    for p in q(c, "SELECT * FROM projects WHERE COALESCE(kind,'project') NOT IN ('trading','general') AND COALESCE(status,'active')='active'"):
        if not q1(c, "SELECT 1 FROM pv_stage WHERE project_id=?", (p["id"],)):
            continue          # only projects whose stage someone has set
        d = pv_stage(c, None, {"project_id": p["id"]})
        for s in d["stages"]:
            for i in s["items"]:
                if i["late"]:
                    out.append({"fkey": "stg:%d:%d" % (p["id"], i["id"]), "kind": "stage_item_late", "project_id": p["id"],
                                "title": "%s (%s): %s - due %s" % (p["code"], s["label"], i["item"], i["due"]), "amount": None, "due_date": i["due"],
                                "severity": "medium", "basis": "Stage checklist.", "detail": "", "sources": [F.src("checklist", s["label"], "#/pv/stages", None, p["id"])]})
    return out


def _connect():
    import api_fcc as F
    for k in NEW_KINDS:
        if k[0] not in F.KIND:
            F.KINDS.append(k)
            F.KIND[k[0]] = k
    for k, v in NEW_ACTIONS.items():
        F.ACTIONS.setdefault(k, v)
    if "stage_item_late" not in {x[0] for x in F.CHECKS}:
        F.CHECKS.append(("stage_item_late", chk_stage))


@api("pv.settings", "project", "view")
def pv_settings(c, u, a):
    r = q1(c, "SELECT enabled FROM fcc_rules WHERE kind='stage_item_late'") if _has(c, "fcc_rules") else None
    return {"hide_bar": setting(c, "pv_hide_bar") == "1", "alert": bool(r and r["enabled"])}


@api("pv.settings_save", "project", "approve")
def pv_settings_save(c, u, a):
    if "hide_bar" in a:
        _set(c, "pv_hide_bar", "1" if a["hide_bar"] in (1, "1", True) else "0")
    if "alert" in a and _has(c, "fcc_rules"):
        c.execute("UPDATE fcc_rules SET enabled=? WHERE kind='stage_item_late'", (1 if a["alert"] in (1, "1", True) else 0,))
    audit(c, u, "save", "settings", None, {"pv_hide_bar": setting(c, "pv_hide_bar"), "alert": a.get("alert")})
    return pv_settings(c, u, {})


def init_progrev(c):
    c.executescript(SCHEMA)
    if not val(c, "SELECT COUNT(*) FROM pv_tpl"):
        for i, (s, item, auto, route, due) in enumerate(TPL):
            ins(c, "pv_tpl", {"stage": s, "item": item, "auto": auto, "route": route, "due_days": due, "sort": (i + 1) * 10, "active": 1})
    used = val(c, "SELECT COUNT(*) FROM vouchers") or val(c, "SELECT COUNT(*) FROM dpr")
    if not q1(c, "SELECT 1 FROM settings WHERE key='pv_hide_bar'"):
        _set(c, "pv_hide_bar", "0")
    if _has(c, "fcc_rules"):
        for k in NEW_KINDS:
            if not q1(c, "SELECT kind FROM fcc_rules WHERE kind=?", (k[0],)):
                c.execute("INSERT INTO fcc_rules(kind, enabled, threshold, owner_role, target_days, escalate_days) VALUES(?,?,?,?,?,?)",
                          (k[0], 0 if used else 1, k[4], k[6], k[7], k[8]))
    c.commit()
    try:
        _connect()
    except Exception:
        pass
