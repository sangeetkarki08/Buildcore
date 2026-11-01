"""
Workers and safety (BuildCore 2.14).

Nepal has almost no data on construction workers and accidents: unions estimate about 250 deaths and
20,000 injuries a year and say nobody counts them properly. A contractor who records them can act on them -
and the law now asks for it: Labour Act 2074 s.55 (accident insurance of at least Rs 7 lakh per worker),
the Public Procurement Act 2083 amendment (workers on public works enrolled in the Social Security Fund and
paid through banks).

  * Worker register - each worker (own or a sub-contractor's) with trade, SSF number, bank account,
    accident insurance and expiry, skill certificate. Compliance % per project and per sub-contractor.
  * Incident register - near miss, first aid, medical treatment, lost-time injury, fatality, property and
    environment; days lost, cause, action, insurance claim, reported to the labour office.
  * Safety figures - man-hours from the DPR labour, LTIFR (lost-time injuries per million hours), TRIR
    (recordable per 200,000 hours), severity (days lost per 1,000 hours), days since the last lost-time injury.
"""
from datetime import date, timedelta

from core import ApiError, audit, ins, next_no, now, num, q, q1, r2, today, upd, val
from api_inventory import api

VERSION = "2.14.0"

SCHEMA = """
CREATE TABLE IF NOT EXISTS hs_workers(id INTEGER PRIMARY KEY, code TEXT, name TEXT, trade TEXT, party_id INTEGER,
  project_id INTEGER, phone TEXT, address TEXT, ssf_no TEXT, bank_name TEXT, bank_acno TEXT, insurance_policy TEXT,
  insurance_sum REAL, insurance_expiry TEXT, skill_cert TEXT, joined TEXT, left_on TEXT, daily_wage REAL,
  emergency_contact TEXT, active INTEGER DEFAULT 1, remarks TEXT, updated TEXT);
CREATE INDEX IF NOT EXISTS ix_hsw ON hs_workers(project_id, party_id);
CREATE TABLE IF NOT EXISTS hs_incidents(id INTEGER PRIMARY KEY, no TEXT, project_id INTEGER, date TEXT, time TEXT,
  location TEXT, activity_id INTEGER, kind TEXT, worker_id INTEGER, person TEXT, party_id INTEGER, injury TEXT,
  days_lost REAL DEFAULT 0, cause TEXT, description TEXT, immediate_action TEXT, corrective_action TEXT,
  action_owner TEXT, action_due TEXT, insurance_claim TEXT, reported_labour_office INTEGER DEFAULT 0,
  cost REAL DEFAULT 0, status TEXT DEFAULT 'open', created_by INTEGER, ts TEXT);
CREATE INDEX IF NOT EXISTS ix_hsi ON hs_incidents(project_id, date);
"""
KINDS = [("near_miss", "Near miss"), ("first_aid", "First aid"), ("medical", "Medical treatment"),
         ("lti", "Lost-time injury"), ("fatality", "Fatality"), ("property", "Property / equipment damage"),
         ("environment", "Environmental")]
CAUSES = ["Fall from height", "Falling object", "Excavation / trench collapse", "Machine / vehicle", "Electrical",
          "Manual handling", "Slip / trip", "Struck by / caught in", "Blasting", "Fire", "Landslide / flood", "Other"]
RECORDABLE = ("medical", "lti", "fatality")
INSURANCE_MIN = 700000   # Labour Act 2074 s.55 - accident insurance of at least Rs 7 lakh


def init_safety(c):
    for st in SCHEMA.strip().split(";"):
        if st.strip():
            c.execute(st)


@api("hs.meta", "project", "view")
def meta(c, u, a):
    return {"kinds": KINDS, "causes": CAUSES, "insurance_min": INSURANCE_MIN,
            "parties": q(c, "SELECT id, code, name, kind FROM parties WHERE COALESCE(active,1)=1 ORDER BY name")}


@api("hs.workers", "project", "view")
def workers(c, u, a):
    w, p = ["1=1"], []
    if a.get("project_id"):
        w.append("(w.project_id=? OR w.project_id IS NULL)")
        p.append(int(a["project_id"]))
    if a.get("party_id"):
        w.append("w.party_id=?")
        p.append(int(a["party_id"]))
    if not a.get("all"):
        w.append("w.active=1")
    rows = q(c, "SELECT w.*, pa.name party FROM hs_workers w LEFT JOIN parties pa ON pa.id=w.party_id WHERE %s "
                "ORDER BY w.name" % " AND ".join(w), p)
    td = today()
    for r in rows:
        gaps = []
        if not r.get("ssf_no"):
            gaps.append("SSF")
        if not r.get("bank_acno"):
            gaps.append("bank")
        if not r.get("insurance_expiry") or r["insurance_expiry"] < td:
            gaps.append("insurance")
        elif (r.get("insurance_sum") or 0) and r["insurance_sum"] < INSURANCE_MIN:
            gaps.append("insured below Rs 7 lakh")
        r["gaps"] = gaps
    return rows


@api("hs.worker_save", "project", "edit")
def worker_save(c, u, a):
    r = a.get("row") or {}
    if not (r.get("name") or "").strip():
        raise ApiError("Write the worker's name.")
    keep = {k: (r.get(k) if r.get(k) not in ("",) else None) for k in
            ("code", "name", "trade", "party_id", "project_id", "phone", "address", "ssf_no", "bank_name", "bank_acno",
             "insurance_policy", "insurance_sum", "insurance_expiry", "skill_cert", "joined", "left_on", "daily_wage",
             "emergency_contact", "remarks")}
    for k in ("party_id", "project_id"):
        keep[k] = int(keep[k]) if keep.get(k) else None
    for k in ("insurance_sum", "daily_wage"):
        keep[k] = num(keep[k]) if keep.get(k) not in (None, "") else None
    keep["active"] = 0 if str(r.get("active", 1)) in ("0", "false") else 1
    keep["updated"] = now()
    if r.get("id"):
        upd(c, "hs_workers", int(r["id"]), keep)
        wid = int(r["id"])
    else:
        if not keep.get("code"):
            keep["code"] = "W%05d" % ((val(c, "SELECT COUNT(*) FROM hs_workers", (), 0) or 0) + 1)
        wid = ins(c, "hs_workers", keep)
    audit(c, u, "save", "hs_workers", wid, {"name": keep["name"]})
    return {"id": wid}


@api("hs.workers_paste", "project", "edit")
def workers_paste(c, u, a):
    """Many workers at once, pasted from Excel: name, trade, sub-contractor code, phone, SSF no, bank, account no,
    insurance expiry (YYYY-MM-DD)."""
    parties = {r["code"].lower(): r["id"] for r in q(c, "SELECT id, code FROM parties") if r["code"]}
    n = 0
    for line in str(a.get("text") or "").splitlines():
        cols = [x.strip() for x in line.split("\t")]
        if not cols or not cols[0] or cols[0].lower() == "name":
            continue
        cols += [""] * 8
        worker_save(c, u, {"row": {"name": cols[0], "trade": cols[1], "party_id": parties.get(cols[2].lower()),
                                   "phone": cols[3], "ssf_no": cols[4], "bank_name": cols[5], "bank_acno": cols[6],
                                   "insurance_expiry": cols[7] or None, "project_id": a.get("project_id")}})
        n += 1
    return {"added": n}


@api("hs.incidents", "project", "view")
def incidents(c, u, a):
    w, p = ["1=1"], []
    if a.get("project_id"):
        w.append("i.project_id=?")
        p.append(int(a["project_id"]))
    if a.get("from"):
        w.append("i.date>=?")
        p.append(a["from"])
    return q(c, "SELECT i.*, pa.name party, pr.code project FROM hs_incidents i LEFT JOIN parties pa ON pa.id=i.party_id "
                "LEFT JOIN projects pr ON pr.id=i.project_id WHERE %s ORDER BY i.date DESC, i.id DESC" % " AND ".join(w), p)


@api("hs.incident_save", "project", "edit")
def incident_save(c, u, a):
    r = a.get("row") or {}
    if not r.get("project_id") or not r.get("date") or not r.get("kind"):
        raise ApiError("Project, date and kind of incident are needed.")
    if r["kind"] not in dict(KINDS):
        raise ApiError("Unknown kind of incident.")
    keep = {k: r.get(k) for k in ("date", "time", "location", "kind", "person", "injury", "cause", "description",
                                  "immediate_action", "corrective_action", "action_owner", "action_due", "insurance_claim", "status")}
    for k in ("project_id", "activity_id", "worker_id", "party_id"):
        keep[k] = int(r[k]) if r.get(k) else None
    keep["days_lost"] = num(r.get("days_lost"))
    keep["cost"] = num(r.get("cost"))
    keep["reported_labour_office"] = 1 if str(r.get("reported_labour_office")) in ("1", "true") else 0
    if keep["worker_id"] and not keep.get("person"):
        wk = q1(c, "SELECT name, party_id FROM hs_workers WHERE id=?", (keep["worker_id"],))
        if wk:
            keep["person"] = wk["name"]
            keep["party_id"] = keep["party_id"] or wk["party_id"]
    if r.get("id"):
        upd(c, "hs_incidents", int(r["id"]), keep)
        iid = int(r["id"])
    else:
        keep.update({"no": next_no(c, "HSE", keep["date"]), "status": keep.get("status") or "open",
                     "created_by": u["id"], "ts": now()})
        iid = ins(c, "hs_incidents", keep)
        if keep["kind"] in ("lti", "fatality") and keep.get("corrective_action") is None:
            try:
                ins(c, "tasks", {"project_id": keep["project_id"], "title": "Investigate %s on %s" % (dict(KINDS)[keep["kind"]].lower(), keep["date"]),
                                 "description": keep.get("description"), "due_date": (date.fromisoformat(keep["date"][:10]) + timedelta(days=3)).isoformat(),
                                 "priority": "high", "status": "open", "created_by": u["id"], "ts": now()})
            except Exception:
                pass
    audit(c, u, "save", "hs_incidents", iid, {"kind": keep["kind"]})
    return {"id": iid}


def man_hours(c, project_id=None, frm=None, to=None):
    w, p = ["1=1"], []
    if project_id:
        w.append("d.project_id=?")
        p.append(int(project_id))
    if frm:
        w.append("d.date>=?")
        p.append(frm)
    if to:
        w.append("d.date<=?")
        p.append(to)
    return val(c, "SELECT COALESCE(SUM(l.count*COALESCE(l.hours,8)),0) FROM dpr_labour l JOIN dpr d ON d.id=l.dpr_id WHERE %s"
               % " AND ".join(w), p, 0) or 0


@api("hs.stats", "project", "view")
def stats(c, u, a):
    td = date.today()
    frm = a.get("from") or (td - timedelta(days=365)).isoformat()
    projs = [q1(c, "SELECT id, code, name FROM projects WHERE id=?", (int(a["project_id"]),))] if a.get("project_id") else \
        q(c, "SELECT id, code, name FROM projects WHERE COALESCE(status,'active') IN ('active','ongoing','running') ORDER BY code")
    rows = []
    for p in [x for x in projs if x]:
        mh = man_hours(c, p["id"], frm)
        inc = q(c, "SELECT kind, days_lost, date FROM hs_incidents WHERE project_id=? AND date>=?", (p["id"], frm))
        lti = sum(1 for x in inc if x["kind"] in ("lti", "fatality"))
        rec = sum(1 for x in inc if x["kind"] in RECORDABLE)
        last = val(c, "SELECT MAX(date) FROM hs_incidents WHERE project_id=? AND kind IN ('lti','fatality')", (p["id"],), None)
        w = q1(c, "SELECT COUNT(*) n, SUM(CASE WHEN COALESCE(ssf_no,'')<>'' THEN 1 ELSE 0 END) ssf, "
                  "SUM(CASE WHEN COALESCE(bank_acno,'')<>'' THEN 1 ELSE 0 END) bank, "
                  "SUM(CASE WHEN COALESCE(insurance_expiry,'')>=? THEN 1 ELSE 0 END) ins FROM hs_workers WHERE active=1 AND project_id=?",
               (td.isoformat(), p["id"])) or {}
        n = w.get("n") or 0
        rows.append({"project_id": p["id"], "project": p["code"], "man_hours": r2(mh), "incidents": len(inc),
                     "near_miss": sum(1 for x in inc if x["kind"] == "near_miss"), "first_aid": sum(1 for x in inc if x["kind"] == "first_aid"),
                     "recordable": rec, "lti": lti, "fatalities": sum(1 for x in inc if x["kind"] == "fatality"),
                     "days_lost": r2(sum(x["days_lost"] or 0 for x in inc)),
                     "ltifr": round(lti * 1e6 / mh, 2) if mh else None, "trir": round(rec * 2e5 / mh, 2) if mh else None,
                     "severity": round(sum(x["days_lost"] or 0 for x in inc) * 1000 / mh, 3) if mh else None,
                     "days_since_lti": (td - date.fromisoformat(last[:10])).days if last else None,
                     "workers": n, "ssf_pct": round(100.0 * (w.get("ssf") or 0) / n) if n else None,
                     "bank_pct": round(100.0 * (w.get("bank") or 0) / n) if n else None,
                     "insured_pct": round(100.0 * (w.get("ins") or 0) / n) if n else None})
    causes = q(c, "SELECT COALESCE(cause,'Other') cause, COUNT(*) n, SUM(CASE WHEN kind IN ('lti','fatality') THEN 1 ELSE 0 END) serious "
                  "FROM hs_incidents WHERE date>=? GROUP BY COALESCE(cause,'Other') ORDER BY n DESC", (frm,))
    open_actions = q(c, "SELECT i.no, i.date, pr.code project, i.kind, i.corrective_action, i.action_owner, i.action_due FROM hs_incidents i "
                        "LEFT JOIN projects pr ON pr.id=i.project_id WHERE i.status='open' ORDER BY i.action_due IS NULL, i.action_due")
    tot_mh = sum(r["man_hours"] for r in rows)
    tot_lti = sum(r["lti"] for r in rows)
    return {"from": frm, "rows": rows, "causes": causes, "open": open_actions,
            "total": {"man_hours": r2(tot_mh), "lti": tot_lti, "ltifr": round(tot_lti * 1e6 / tot_mh, 2) if tot_mh else None,
                      "incidents": sum(r["incidents"] for r in rows)},
            "note": "Man-hours come from the DPR labour (count x hours). LTIFR = lost-time injuries x 1,000,000 / man-hours; "
                    "TRIR = medical, lost-time and fatal cases x 200,000 / man-hours; severity = days lost x 1,000 / man-hours. "
                    "A near miss recorded today is an accident prevented tomorrow - record them."}
