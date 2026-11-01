"""Teamwork: several people, in several places, on one project.

Three things live here:

  1. The activity feed - every posting, approval and payment is written to one table as it
     happens, so an owner in another city sees the project move in near real time.
  2. Presence - who is signed in right now, from where, and on which computer.
  3. Site packs - for a site with no internet at all: the site copy writes a file, the file
     travels (pen drive, phone, e-mail), head office reads it in. Nothing is entered twice.
"""
import json
import os
import secrets

from core import (ApiError, ONLINE_MINUTES, audit, ins, need, now, num, q, q1, setting, today, upd, val)
from api_inventory import api

VERSION = "1.6.0"


# ───────────────────────── activity feed ─────────────────────────
# fn name -> (kind, sentence). %s is filled by the resolver below.
FEED = {
    "dpr.submit": ("work", "sent the daily progress report for checking"),
    "dpr.check": ("work", "checked the daily progress report"),
    "dpr.approve": ("work", "approved the daily progress report"),
    "dpr.return": ("work", "returned the daily progress report for correction"),
    "dpr.reopen": ("work", "reopened an approved daily progress report"),
    "issue.post": ("store", "issued material to site"),
    "grn.post": ("store", "received goods into store"),
    "return.post": ("store", "took material back into store"),
    "transfer.send": ("store", "sent a stock transfer"),
    "transfer.receive": ("store", "received a stock transfer"),
    "count.post": ("store", "posted a stock count"),
    "stock.opening": ("store", "entered opening stock"),
    "mrq.submit": ("procure", "raised a material requisition"),
    "mrq.approve": ("procure", "approved a material requisition"),
    "pr.approve": ("procure", "approved a purchase request"),
    "po.issue": ("procure", "issued a purchase order"),
    "po.approve": ("procure", "approved a purchase order"),
    "po.close": ("procure", "closed a purchase order"),
    "invoice.post": ("accounts", "posted a purchase bill"),
    "payment.post": ("accounts", "posted a payment"),
    "receipt.post": ("accounts", "posted a receipt"),
    "voucher.post": ("accounts", "posted a voucher"),
    "voucher.approve": ("accounts", "approved a voucher"),
    "sales.post": ("accounts", "posted a client invoice"),
    "meas.verify": ("commercial", "verified a measurement"),
    "meas.approve": ("commercial", "approved a measurement"),
    "ipc.submit": ("commercial", "submitted an IPC to the consultant"),
    "ipc.certify": ("commercial", "recorded an IPC certification"),
    "var.submit": ("commercial", "submitted a variation claim"),
    "var.decide": ("commercial", "recorded the decision on a variation"),
    "ncr.close": ("quality", "closed an NCR"),
    "qa.result": ("quality", "recorded a test result"),
    "eq.log_save": ("equipment", "entered an equipment logsheet"),
    "book.open": ("equipment", "opened a machine's monthly logsheet"),
    "book.submit": ("equipment", "sent a machine's monthly logsheet for approval"),
    "book.approve": ("equipment", "approved a machine's monthly logsheet"),
    "book.reopen": ("equipment", "reopened an approved monthly logsheet"),
    "eq.wo_save": ("equipment", "updated a work order"),
    "reg.save": ("work", "updated the site register"),
    "team.pack_import": ("sync", "loaded a site pack from another computer"),
}
# Registers write a more useful sentence than "updated the site register".
REG_WORDS = {"events": "recorded a site event", "variations": "updated a variation",
             "qa_tests": "raised a test request", "ncrs": "raised an NCR", "tasks": "set a task"}


def _first(d, *keys):
    for k in keys:
        v = (d or {}).get(k)
        if v not in (None, "", 0):
            return v
    return None


def log_call(c, user, fn, args, result):
    """Called once, centrally, after every successful action - so nothing can be forgotten."""
    entry = FEED.get(fn)
    if not entry or not user:
        return
    kind, words = entry
    args = args if isinstance(args, dict) else {}
    head = args.get("header") if isinstance(args.get("header"), dict) else {}
    row = args.get("row") if isinstance(args.get("row"), dict) else {}
    res = result if isinstance(result, dict) else {}
    if fn == "reg.save":
        words = REG_WORDS.get(args.get("table") or "", words)
    pid = _first(args, "project_id") or _first(head, "project_id") or _first(row, "project_id") \
        or _first(res, "project_id")
    ref = _first(res, "no") or _first(args, "no") or _first(res, "id") or _first(args, "id")
    amount = _first(res, "amount", "total", "net") or _first(head, "amount") or _first(args, "amount")
    link = LINKS.get(fn) or LINKS.get(fn.split(".")[0] + ".*")
    ins(c, "activity", {"ts": now(), "user_id": user["id"], "user_name": user["name"] or user["username"],
                        "location": user["location"] if "location" in user.keys() else None,
                        "project_id": int(pid) if pid else None, "kind": kind, "title": words,
                        "detail": ("No. %s" % ref) if ref else None, "link": link,
                        "amount": num(amount) if amount else None})


LINKS = {"dpr.*": "#/p/dpr", "issue.post": "#/inv/issue", "grn.post": "#/inv/grn", "return.post": "#/inv/return",
         "transfer.send": "#/inv/transfer", "transfer.receive": "#/inv/transfer", "count.post": "#/inv/count",
         "stock.opening": "#/inv/opening", "mrq.*": "#/inv/mrq", "pr.*": "#/proc/pr", "po.*": "#/proc/po",
         "invoice.post": "#/proc/invoices", "payment.post": "#/acc/payments", "receipt.post": "#/acc/payments",
         "voucher.*": "#/acc/vouchers", "sales.post": "#/acc/sales", "meas.*": "#/p/measure", "ipc.*": "#/p/ipc",
         "var.*": "#/p/variations", "ncr.close": "#/p/quality", "qa.result": "#/p/quality", "eq.log_save": "#/eq/logs",
         "eq.wo_save": "#/eq/wo", "book.*": "#/eq/books", "reg.save": "#/p/events", "team.pack_import": "#/admin/sync"}


def note(c, user, kind, title, detail=None, project_id=None, link=None, amount=None):
    """Write a line to the feed from inside any module."""
    ins(c, "activity", {"ts": now(), "user_id": user and user["id"],
                        "user_name": (user and (user["name"] or user["username"])) or "BuildCore",
                        "project_id": project_id, "kind": kind, "title": title, "detail": detail,
                        "link": link, "amount": amount})


@api("team.feed", "project", "view")
def team_feed(c, u, a):
    cond, p = [], []
    if a.get("project_id"):
        cond.append("(project_id=? OR project_id IS NULL)")
        p.append(int(a["project_id"]))
    if a.get("since_id"):
        cond.append("id>?")
        p.append(int(a["since_id"]))
    if a.get("kind"):
        cond.append("kind=?")
        p.append(a["kind"])
    if a.get("mine"):
        cond.append("user_id=?")
        p.append(u["id"])
    where = (" WHERE " + " AND ".join(cond)) if cond else ""
    rows = q(c, "SELECT * FROM activity%s ORDER BY id DESC LIMIT %d" % (where, int(a.get("limit") or 60)), p)
    return {"rows": rows, "last_id": val(c, "SELECT COALESCE(MAX(id),0) FROM activity"), "server_time": now()}


@api("team.tick")
def team_tick(c, u, a):
    """Small, frequent call: has anything happened, and who is working right now."""
    last = val(c, "SELECT COALESCE(MAX(id),0) FROM activity")
    since = int(a.get("since_id") or 0)
    new = 0
    latest = None
    if since:
        cond, p = ["id>?"], [since]
        if a.get("project_id"):
            cond.append("(project_id=? OR project_id IS NULL)")
            p.append(int(a["project_id"]))
        new = val(c, "SELECT COUNT(*) FROM activity WHERE " + " AND ".join(cond), p)
        latest = q1(c, "SELECT * FROM activity WHERE " + " AND ".join(cond) + " ORDER BY id DESC LIMIT 1", p)
    return {"last_id": last, "new": new, "latest": latest, "online": _online(c), "server_time": now()}


def _online(c):
    from datetime import datetime, timedelta
    cut = (datetime.now() - timedelta(minutes=ONLINE_MINUTES)).isoformat(timespec="seconds")
    return q(c, "SELECT u.id, u.name, u.username, u.role, u.location, MAX(s.last_seen) AS last_seen, "
                "       MAX(s.device) AS device "
                "FROM sessions s JOIN users u ON u.id=s.user_id "
                "WHERE s.last_seen>=? AND u.active=1 GROUP BY u.id ORDER BY u.name", (cut,))


@api("team.presence", "project", "view")
def team_presence(c, u, a):
    online = {r["id"]: r for r in _online(c)}
    people = q(c, "SELECT id, username, name, role, location, phone, active FROM users ORDER BY active DESC, name")
    for pe in people:
        pe["online"] = pe["id"] in online
        pe["last_seen"] = (online.get(pe["id"]) or {}).get("last_seen") or \
            val(c, "SELECT MAX(last_seen) FROM sessions WHERE user_id=?", (pe["id"],), None)
        pe["device"] = (online.get(pe["id"]) or {}).get("device")
    return {"people": people, "online": len(online), "server_time": now(),
            "site_name": setting(c, "site_name"), "site_code": setting(c, "site_code")}


@api("team.sessions", "admin", "view")
def team_sessions(c, u, a):
    return q(c, "SELECT s.token, s.created, s.last_seen, s.ip, s.device, u.username, u.name, u.role, u.id AS user_id "
                "FROM sessions s JOIN users u ON u.id=s.user_id ORDER BY COALESCE(s.last_seen,s.created) DESC")


@api("team.signout", "admin", "edit")
def team_signout(c, u, a):
    if a.get("token"):
        c.execute("DELETE FROM sessions WHERE token=?", (a["token"],))
    elif a.get("user_id"):
        c.execute("DELETE FROM sessions WHERE user_id=?", (int(a["user_id"]),))
    else:
        raise ApiError("Choose a sign-in to end.")
    audit(c, u, "signout", "sessions", a.get("user_id"))
    return True


@api("team.logins", "admin", "view")
def team_logins(c, u, a):
    return q(c, "SELECT * FROM login_attempts ORDER BY id DESC LIMIT %d" % int(a.get("limit") or 100))


# ───────────────────────── this server ─────────────────────────
SERVER = {"mode": "local", "port": 8750, "addresses": [], "tls": False, "started": None}


@api("server.info")
def server_info(c, u, a):
    return {"version": VERSION, "mode": SERVER["mode"], "port": SERVER["port"], "tls": SERVER["tls"],
            "addresses": SERVER["addresses"], "started": SERVER["started"],
            "site_code": setting(c, "site_code"), "site_name": setting(c, "site_name"),
            "allow_public": setting(c, "allow_public") == "1", "users": val(c, "SELECT COUNT(*) FROM users"),
            "online": len(_online(c)), "company": setting(c, "company_name"), "db": os.path.basename(_db_path()),
            "data_dir": os.path.dirname(_db_path()), "server_time": now()}


def _db_path():
    from core import DB_PATH
    return DB_PATH


@api("server.access", "admin", "edit")
def server_access(c, u, a):
    """Name this copy and decide who may reach it. Takes effect at once."""
    import server
    for key in ("site_code", "site_name", "allow_public", "session_days", "lock_minutes"):
        if key in a:
            v = a[key]
            v = "1" if v is True else ("0" if v is False else str(v))
            c.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                      (key, v.strip() if key in ("site_code", "site_name") else v))
    if "allow_public" in a:
        server.ALLOW_PUBLIC[0] = setting(c, "allow_public") == "1"
        note(c, u, "sync", "changed who may reach this BuildCore server",
             "outside computers are now %s" % ("allowed" if server.ALLOW_PUBLIC[0] else "refused"),
             None, "#/admin/remote")
    server.SERVER_NAME[0] = setting(c, "site_name") or setting(c, "company_name") or "BuildCore"
    audit(c, u, "settings", "server", None, {k: v for k, v in a.items() if not k.startswith("_")})
    return server_info(c, u, {})


# ───────────────────────── site packs (no internet at site) ─────────────────────────
PACK_KINDS = ["dpr", "issues", "logsheets"]


def _pack_masters(c, project_id):
    """Codes, not numbers: the two copies match records by code so ids never clash."""
    return {
        "materials": {str(r["id"]): r["code"] for r in q(c, "SELECT id, code FROM materials")},
        "trades": {str(r["id"]): r["code"] for r in q(c, "SELECT id, code FROM trades WHERE project_id=?",
                                                      (project_id,))},
        "equipment": {str(r["id"]): r["code"] for r in q(c, "SELECT id, code FROM equipment")},
        "activities": {str(r["id"]): r["code"] for r in q(c, "SELECT id, code FROM activities WHERE project_id=?",
                                                          (project_id,))},
        "boq_items": {str(r["id"]): r["code"] for r in q(c, "SELECT id, code FROM boq_items WHERE project_id=?",
                                                         (project_id,))},
        "stores": {str(r["id"]): r["code"] for r in q(c, "SELECT id, code FROM stores WHERE project_id=?",
                                                      (project_id,))},
    }


@api("team.pack_export", "project", "view")
def pack_export(c, u, a):
    need(a, "project_id")
    pid = int(a["project_id"])
    site = setting(c, "site_code") or "SITE"
    frm = a.get("from") or today()
    to = a.get("to") or today()
    pr = q1(c, "SELECT * FROM projects WHERE id=?", (pid,))
    if not pr:
        raise ApiError("Choose a project.")
    m = _pack_masters(c, pid)
    out = {"format": "buildcore-site-pack", "version": 1, "site_code": site,
           "site_name": setting(c, "site_name"), "company": setting(c, "company_name"), "made": now(),
           "made_by": u["name"] or u["username"], "project_code": pr["code"], "project_name": pr["name"],
           "from": frm, "to": to, "records": {}}
    # daily progress reports, with their lines
    dprs = q(c, "SELECT * FROM dpr WHERE project_id=? AND date BETWEEN ? AND ? AND status<>'draft' "
                "AND (origin IS NULL OR origin='')", (pid, frm, to))
    packed = []
    for d in dprs:
        rec = {k: d[k] for k in d.keys() if k not in ("id", "project_id", "origin", "origin_id")}
        rec["origin_id"] = d["id"]
        rec["work"] = [{"activity": m["activities"].get(str(w["activity_id"])),
                        "boq": m["boq_items"].get(str(w["boq_item_id"])), "planned_qty": w["planned_qty"],
                        "actual_qty": w["actual_qty"], "location": w["location"], "remarks": w["remarks"]}
                       for w in q(c, "SELECT * FROM dpr_work WHERE dpr_id=?", (d["id"],))]
        rec["labour"] = [{"trade": m["trades"].get(str(l["trade_id"])),
                          "activity": m["activities"].get(str(l["activity_id"])),
                          "count": l["count"], "hours": l["hours"], "ot_hours": l["ot_hours"],
                          "rate": l["rate"], "amount": l["amount"]}
                         for l in q(c, "SELECT * FROM dpr_labour WHERE dpr_id=?", (d["id"],))]
        rec["equipment"] = [{"equipment": m["equipment"].get(str(e["equipment_id"])),
                             "activity": m["activities"].get(str(e["activity_id"])), "operator": e["operator"],
                             "meter_start": e["meter_start"], "meter_end": e["meter_end"], "hours": e["hours"],
                             "idle_hours": e["idle_hours"], "breakdown_hours": e["breakdown_hours"],
                             "rate": e["rate"], "amount": e["amount"]}
                            for e in q(c, "SELECT * FROM dpr_equipment WHERE dpr_id=?", (d["id"],))]
        rec["delays"] = [{"activity": m["activities"].get(str(x["activity_id"])), "category": x["category"],
                          "hours": x["hours"], "description": x["description"]}
                         for x in q(c, "SELECT * FROM dpr_delays WHERE dpr_id=?", (d["id"],))]
        packed.append(rec)
    out["records"]["dpr"] = packed
    # material issues
    iss = []
    for d in q(c, "SELECT * FROM issues WHERE project_id=? AND date BETWEEN ? AND ? AND (origin IS NULL OR origin='')",
               (pid, frm, to)):
        rec = {k: d[k] for k in d.keys() if k not in ("id", "project_id", "store_id", "origin", "origin_id")}
        rec["origin_id"] = d["id"]
        rec["store"] = m["stores"].get(str(d["store_id"]))
        rec["lines"] = [{"material": m["materials"].get(str(x["material_id"])), "qty": x["qty"],
                         "target": x["target"], "boq": m["boq_items"].get(str(x["boq_item_id"])),
                         "equipment": m["equipment"].get(str(x["equipment_id"])),
                         "activity": m["activities"].get(str(x["activity_id"]))}
                        for x in q(c, "SELECT * FROM issue_lines WHERE issue_id=?", (d["id"],))]
        iss.append(rec)
    out["records"]["issues"] = iss
    # equipment logsheets
    logs = []
    for d in q(c, "SELECT * FROM logsheets WHERE project_id=? AND date BETWEEN ? AND ? "
                  "AND (origin IS NULL OR origin='')", (pid, frm, to)):
        rec = {k: d[k] for k in d.keys() if k not in ("id", "project_id", "equipment_id", "activity_id", "dpr_id",
                                                      "boq_item_id", "origin", "origin_id", "created_by",
                                                      "approved_by")}
        rec["origin_id"] = d["id"]
        rec["equipment"] = m["equipment"].get(str(d["equipment_id"]))
        rec["activity"] = m["activities"].get(str(d["activity_id"]))
        rec["boq"] = m["boq_items"].get(str(d["boq_item_id"]))
        rec.pop("book_id", None)
        # whatever second or third meter the machine carries travels with the day
        rec["meters"] = [{"code": x["code"], "start": x["r_start"], "stop": x["r_stop"], "total": x["total"]}
                         for x in q(c, "SELECT * FROM log_meters WHERE log_id=?", (d["id"],))]
        logs.append(rec)
    out["records"]["logsheets"] = logs
    out["counts"] = {k: len(v) for k, v in out["records"].items()}
    ins(c, "site_packs", {"ts": now(), "direction": "out", "site_code": site, "project_id": pid,
                          "filename": pack_name(site, pr["code"], frm, to), "counts": json.dumps(out["counts"]),
                          "user_id": u["id"], "note": a.get("note")})
    return {"pack": out, "filename": pack_name(site, pr["code"], frm, to), "counts": out["counts"]}


def pack_name(site, project, frm, to):
    return "BuildCore_%s_%s_%s_to_%s.bcpack" % (site or "SITE", project, frm, to)


@api("team.pack_preview", "project", "view")
def pack_preview(c, u, a):
    p = _load_pack(a)
    pid = _pack_project(c, p)
    seen = _already(c, p)
    return {"site_code": p.get("site_code"), "site_name": p.get("site_name"), "made": p.get("made"),
            "made_by": p.get("made_by"), "project_code": p.get("project_code"), "project_name": p.get("project_name"),
            "from": p.get("from"), "to": p.get("to"), "counts": p.get("counts") or {},
            "already_loaded": seen, "project_known": bool(pid),
            "new": {k: len(p["records"].get(k) or []) - seen.get(k, 0) for k in PACK_KINDS}}


def _load_pack(a):
    raw = a.get("pack")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            raise ApiError("This file is not a BuildCore site pack.")
    if not isinstance(raw, dict) or raw.get("format") != "buildcore-site-pack":
        raise ApiError("This file is not a BuildCore site pack.")
    raw.setdefault("records", {})
    return raw


def _pack_project(c, p):
    r = q1(c, "SELECT id FROM projects WHERE code=?", (p.get("project_code"),))
    return r["id"] if r else None


def _already(c, p):
    out = {}
    for kind in PACK_KINDS:
        ids = [x.get("origin_id") for x in (p["records"].get(kind) or [])]
        n = 0
        for i in ids:
            if q1(c, "SELECT local_id FROM import_map WHERE origin=? AND kind=? AND origin_id=?",
                  (p.get("site_code"), kind, i)):
                n += 1
        out[kind] = n
    return out


@api("team.pack_import", "project", "edit")
def pack_import(c, u, a):
    p = _load_pack(a)
    pid = _pack_project(c, p)
    if not pid:
        raise ApiError("This pack is for project %s, which does not exist on this computer. "
                       "Create that project first (same code)." % p.get("project_code"))
    site = p.get("site_code") or "SITE"
    if site == (setting(c, "site_code") or ""):
        raise ApiError("This pack was made by THIS computer. Load it on the other computer.")
    pack_id = ins(c, "site_packs", {"ts": now(), "direction": "in", "site_code": site, "project_id": pid,
                                    "filename": a.get("filename") or "", "counts": json.dumps(p.get("counts") or {}),
                                    "user_id": u["id"], "note": a.get("note")})
    codes = _code_maps(c, pid)
    added = {k: 0 for k in PACK_KINDS}
    skipped = {k: 0 for k in PACK_KINDS}
    problems = []

    def mapped(kind, oid):
        r = q1(c, "SELECT local_id FROM import_map WHERE origin=? AND kind=? AND origin_id=?", (site, kind, oid))
        return r["local_id"] if r else None

    def remember(kind, oid, lid):
        ins(c, "import_map", {"origin": site, "kind": kind, "origin_id": oid, "local_id": lid,
                              "pack_id": pack_id, "ts": now()})

    def find(group, code, what, where):
        if code in (None, ""):
            return None
        lid = codes[group].get(code)
        if not lid:
            problems.append("%s: %s \"%s\" is not on this computer" % (where, what, code))
        return lid

    for rec in p["records"].get("dpr") or []:
        oid = rec.get("origin_id")
        if mapped("dpr", oid):
            skipped["dpr"] += 1
            continue
        where = "DPR %s of %s" % (rec.get("no") or oid, rec.get("date"))
        head = {k: rec.get(k) for k in ("date", "shift", "weather", "site_condition", "remarks")
                if rec.get(k) is not None}
        if q1(c, "SELECT id FROM dpr WHERE project_id=? AND date=? AND shift=?",
              (pid, head.get("date"), head.get("shift") or "day")):
            problems.append("%s: a DPR for that date and shift already exists here" % where)
            skipped["dpr"] += 1
            continue
        head.update({"project_id": pid, "origin": site, "origin_id": oid, "created_by": u["id"],
                     "no": _renumber(c, "dpr", rec.get("no"), site),
                     # a pack is loaded for checking, never straight into the accounts
                     "status": "submitted"})
        did = ins(c, "dpr", head)
        for w in rec.get("work") or []:
            ins(c, "dpr_work", {"dpr_id": did, "activity_id": find("activities", w.get("activity"), "activity", where),
                                "boq_item_id": find("boq_items", w.get("boq"), "BOQ item", where),
                                "planned_qty": num(w.get("planned_qty")), "actual_qty": num(w.get("actual_qty")),
                                "location": w.get("location"), "remarks": w.get("remarks")})
        for l in rec.get("labour") or []:
            ins(c, "dpr_labour", {"dpr_id": did, "trade_id": find("trades", l.get("trade"), "trade", where),
                                  "activity_id": codes["activities"].get(l.get("activity")),
                                  "count": num(l.get("count")), "hours": num(l.get("hours")),
                                  "ot_hours": num(l.get("ot_hours")), "rate": num(l.get("rate")),
                                  "amount": num(l.get("amount"))})
        for e in rec.get("equipment") or []:
            ins(c, "dpr_equipment", {"dpr_id": did,
                                     "equipment_id": find("equipment", e.get("equipment"), "machine", where),
                                     "activity_id": codes["activities"].get(e.get("activity")),
                                     "operator": e.get("operator"), "meter_start": num(e.get("meter_start")),
                                     "meter_end": num(e.get("meter_end")), "hours": num(e.get("hours")),
                                     "idle_hours": num(e.get("idle_hours")),
                                     "breakdown_hours": num(e.get("breakdown_hours")),
                                     "rate": num(e.get("rate")), "amount": num(e.get("amount"))})
        for x in rec.get("delays") or []:
            ins(c, "dpr_delays", {"dpr_id": did, "activity_id": codes["activities"].get(x.get("activity")),
                                  "category": x.get("category"), "hours": num(x.get("hours")),
                                  "description": x.get("description")})
        remember("dpr", oid, did)
        added["dpr"] += 1

    for rec in p["records"].get("issues") or []:
        oid = rec.get("origin_id")
        if mapped("issues", oid):
            skipped["issues"] += 1
            continue
        where = "Issue %s of %s" % (rec.get("no") or oid, rec.get("date"))
        store = find("stores", rec.get("store"), "store", where)
        if not store:
            continue
        head = {k: rec.get(k) for k in ("date", "issued_to", "remarks") if rec.get(k) is not None}
        head.update({"project_id": pid, "store_id": store, "origin": site, "origin_id": oid, "created_by": u["id"],
                     "no": _renumber(c, "issues", rec.get("no"), site), "status": "draft"})
        iid = ins(c, "issues", head)
        ok = True
        for l in rec.get("lines") or []:
            mid = find("materials", l.get("material"), "material", where)
            if not mid:
                ok = False
                continue
            ins(c, "issue_lines", {"issue_id": iid, "material_id": mid, "qty": num(l.get("qty")),
                                   "target": l.get("target") or "boq",
                                   "boq_item_id": codes["boq_items"].get(l.get("boq")),
                                   "equipment_id": codes["equipment"].get(l.get("equipment")),
                                   "activity_id": codes["activities"].get(l.get("activity"))})
        remember("issues", oid, iid)
        added["issues"] += 1
        if not ok:
            problems.append("%s was loaded without some lines" % where)

    for rec in p["records"].get("logsheets") or []:
        oid = rec.get("origin_id")
        if mapped("logsheets", oid):
            skipped["logsheets"] += 1
            continue
        where = "Logsheet of %s" % rec.get("date")
        eq = find("equipment", rec.get("equipment"), "machine", where)
        if not eq:
            continue
        head = {k: rec.get(k) for k in ("date", "shift", "operator", "meter_start", "meter_end", "hours",
                                        "idle_hours", "breakdown_hours", "work", "trips", "standby_hours",
                                        "time_start", "time_stop", "km_start", "km_end", "km_run", "fuel_qty",
                                        "fuel_req_no", "down_reason", "cost_code", "sign_store", "sign_operator",
                                        "sign_incharge", "sign_hirer")
                if rec.get(k) is not None}
        head.update({"project_id": pid, "equipment_id": eq, "origin": site, "origin_id": oid, "status": "draft",
                     "created_by": u["id"], "activity_id": codes["activities"].get(rec.get("activity")),
                     "boq_item_id": codes["boq_items"].get(rec.get("boq"))})
        lid = ins(c, "logsheets", head)
        for mt in rec.get("meters") or []:
            ins(c, "log_meters", {"log_id": lid, "code": mt.get("code"), "r_start": mt.get("start") or 0,
                                  "r_stop": mt.get("stop") or 0, "total": mt.get("total") or 0})
        remember("logsheets", oid, lid)
        added["logsheets"] += 1

    upd(c, "site_packs", pack_id, {"counts": json.dumps({"added": added, "skipped": skipped})})
    note(c, u, "sync", "loaded a site pack from %s" % site,
         "%d DPR, %d issues, %d logsheets" % (added["dpr"], added["issues"], added["logsheets"]), pid, "#/admin/sync")
    audit(c, u, "import", "site_packs", pack_id, {"added": added, "skipped": skipped})
    return {"added": added, "skipped": skipped, "problems": problems[:40], "pack_id": pack_id,
            "site_code": site, "project_id": pid}


def _renumber(c, table, no, site):
    """Keep the site's own number but stamp where it came from, so two copies never collide."""
    if not no:
        return None
    tagged = "%s/%s" % (site, no)
    if q1(c, "SELECT id FROM %s WHERE no=?" % table, (tagged,)):
        tagged = "%s-%s" % (tagged, secrets.token_hex(2))
    return tagged


def _code_maps(c, pid):
    return {
        "materials": {r["code"]: r["id"] for r in q(c, "SELECT id, code FROM materials")},
        "trades": {r["code"]: r["id"] for r in q(c, "SELECT id, code FROM trades WHERE project_id=?", (pid,))},
        "equipment": {r["code"]: r["id"] for r in q(c, "SELECT id, code FROM equipment")},
        "activities": {r["code"]: r["id"] for r in q(c, "SELECT id, code FROM activities WHERE project_id=?", (pid,))},
        "boq_items": {r["code"]: r["id"] for r in q(c, "SELECT id, code FROM boq_items WHERE project_id=?", (pid,))},
        "stores": {r["code"]: r["id"] for r in q(c, "SELECT id, code FROM stores WHERE project_id=?", (pid,))},
    }


@api("team.packs", "project", "view")
def team_packs(c, u, a):
    rows = q(c, "SELECT * FROM site_packs ORDER BY id DESC LIMIT 100")
    for r in rows:
        try:
            r["counts"] = json.loads(r["counts"] or "{}")
        except ValueError:
            r["counts"] = {}
    return rows
