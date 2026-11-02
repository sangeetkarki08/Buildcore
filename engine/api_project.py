"""BuildCore 3 project-control layer.

PLAN (WBS, activities, BOQ, rate analysis) -> EXECUTE (DPR) -> MEASURE -> BILL (IPC) -> ACCOUNT -> ANALYSE -> CONTROL.
Source of truth: BOQ = contract qty/rate, schedule = planned work, approved DPR = actual work, store issues =
material use, logsheets = equipment hours, vouchers = money, IPC = certified revenue.
"""
import os
import uuid
from datetime import date, timedelta

from core import (ApiError, EPS, audit, can, fsetting, get, ins, need, next_no, now, num, post_voucher, q, q1, r2,
                  r4, require, reverse_voucher, setting, today, upd, val, DATA_DIR)
import api_inventory as inv
from api_inventory import api
from api_equipment_reports import log_save, maint_status, dash_approvals, POSTED
from api_finance import invoice_post, invoice_cancel, invoice_paid

SYSTEM = {"role": "admin"}  # internal automation runs with full rights, audited under the real user


def sysuser(u):
    return dict(SYSTEM, id=u["id"], name=u.get("name"))


# ───────────────────────── register new master tables ─────────────────────────
inv.MASTERS.update({
    "wbs": ("project", ["project_id", "code", "name", "parent_id", "weight", "sort"], ["project_id", "code", "name"],
            [("activities", "wbs_id"), ("wbs", "parent_id")]),
    "activities": ("project", ["project_id", "wbs_id", "code", "name", "boq_item_id", "location", "unit", "planned_qty",
                               "planned_start", "planned_finish", "baseline_start", "baseline_finish", "weight",
                               "responsible", "predecessors", "is_milestone", "critical", "std_labour_prod",
                               "std_equip_prod", "test_required", "delay_reason"],
                   ["project_id", "wbs_id", "name"], [("dpr_work", "activity_id")]),
    "trades": ("project", ["project_id", "code", "name", "rate_hour", "active"], ["name", "rate_hour"],
               [("dpr_labour", "trade_id")]),
    "rate_analysis": ("commercial", ["boq_item_id", "kind", "ref_id", "description", "qty_per_unit", "rate"],
                      ["boq_item_id", "kind", "qty_per_unit"], []),
    "equipment_rates": ("equipment", ["equipment_id", "effective_from", "ownership_hr", "fuel_hr", "operator_hr",
                                      "maintenance_hr", "insurance_hr", "overhead_pct", "remarks"],
                        ["equipment_id", "effective_from"], []),
})
inv.MASTERS["boq_items"] = ("commercial", inv.MASTERS["boq_items"][1] + ["wbs_id", "location", "revised_qty",
                                                                        "revised_rate"],
                            inv.MASTERS["boq_items"][2], inv.MASTERS["boq_items"][3] + [("dpr_work", "boq_item_id")])
inv.NUMERIC |= {"weight", "sort", "planned_qty", "is_milestone", "critical", "std_labour_prod", "std_equip_prod",
                "rate_hour", "qty_per_unit", "ownership_hr", "fuel_hr", "operator_hr", "maintenance_hr",
                "insurance_hr", "overhead_pct", "revised_qty", "revised_rate", "ref_id"}
inv.ID_FIELDS |= {"wbs_id", "boq_item_id", "activity_id"}
_orig_clean = inv.clean_value


def _clean(k, v):
    if k in ("revised_qty", "revised_rate") and (v == "" or v is None):
        return None  # empty means "same as contract"
    return _orig_clean(k, v)


inv.clean_value = _clean

# Registers with numbering and status (generic save for simple commercial / quality / task records)
REGISTERS = {
    "events": ("commercial", "EVT", ["project_id", "date", "type", "title", "description", "wbs_id", "activity_id",
                                     "dpr_id", "responsible_party", "clause", "notice_deadline", "delay_days",
                                     "cost_impact", "mitigation", "status"], ["project_id", "title"]),
    "variations": ("commercial", "VO", ["project_id", "boq_item_id", "new_code", "new_description", "new_unit", "date",
                                        "title", "reason", "instruction_ref", "var_qty", "new_rate",
                                        "time_impact_days", "event_id"], ["project_id", "title"]),
    "qa_tests": ("quality", "QT", ["project_id", "activity_id", "boq_item_id", "material_id", "dpr_id", "location",
                                   "test_type", "sample_ref", "sampled_date", "criteria", "remarks"],
                 ["project_id", "test_type"]),
    "ncrs": ("quality", "NCR", ["project_id", "date", "title", "description", "activity_id", "test_id",
                                "corrective_action", "due_date"], ["project_id", "title"]),
    "tasks": ("project", None, ["project_id", "title", "description", "due_date", "priority", "assigned_to"],
              ["title"]),
}
REG_NUM = {"delay_days", "cost_impact", "var_qty", "new_rate", "time_impact_days"}
REG_ID = {"project_id", "wbs_id", "activity_id", "dpr_id", "boq_item_id", "event_id", "material_id", "test_id",
          "assigned_to"}
LOCKED = {"variations": ("approved", "rejected"), "qa_tests": ("passed", "failed"), "ncrs": ("closed",)}


def rv(k, v):
    if v in ("", None):
        return None
    if k in REG_ID:
        return int(v)
    if k in REG_NUM:
        return num(v, k)
    return str(v).strip()


@api("reg.list")
def reg_list(c, u, a):
    t = a.get("table")
    if t not in REGISTERS:
        raise ApiError("Unknown register.")
    require(u, REGISTERS[t][0], "view")
    cond, p = [], []
    for k in ("project_id", "status", "activity_id", "dpr_id", "type"):
        if a.get(k):
            cond.append("%s=?" % k)
            p.append(a[k])
    if t == "tasks" and a.get("mine"):
        cond.append("(assigned_to=? OR assigned_to IS NULL)")
        p.append(u["id"])
    return q(c, "SELECT * FROM %s%s ORDER BY id DESC LIMIT 1000" % (t, " WHERE " + " AND ".join(cond) if cond else ""), p)


@api("reg.save")
def reg_save(c, u, a):
    t = a.get("table")
    if t not in REGISTERS:
        raise ApiError("Unknown register.")
    module, prefix, fields, req = REGISTERS[t]
    row = a.get("row") or {}
    if not (can(u, module, "edit") or (t in ("events", "tasks", "qa_tests") and can(u, "project", "edit"))):
        require(u, module, "edit")
    data = {k: rv(k, row.get(k)) for k in fields if k in row}
    rid = row.get("id")
    if rid:
        old = get(c, t, int(rid))
        if old.get("status") in LOCKED.get(t, ()):
            raise ApiError("This record is %s and can no longer be edited." % old["status"])
        upd(c, t, int(rid), data)
        rid = int(rid)
    else:
        for k in req:
            if data.get(k) in (None, ""):
                raise ApiError("%s is required." % k.replace("_", " ").capitalize())
        if "date" in fields and not data.get("date"):
            data["date"] = today()
        if prefix:
            data["no"] = next_no(c, prefix, data.get("date") or today())
        data["created_by"] = u["id"]
        if t == "tasks":
            data["ts"] = now()
        rid = ins(c, t, data)
        if t == "events" and (data.get("type") or "delay") in ("delay", "instruction", "notice", "claim"):
            auto_task(c, u, data.get("project_id"), "Contract review: " + data["title"], "events", rid,
                      due=data.get("notice_deadline"), priority="high",
                      description="Check notice requirement, clause, time and cost impact.")
    audit(c, u, "save", t, rid, data)
    return q1(c, "SELECT * FROM %s WHERE id=?" % t, (rid,))


@api("reg.delete")
def reg_delete(c, u, a):
    t = a.get("table")
    if t not in REGISTERS:
        raise ApiError("Unknown register.")
    require(u, REGISTERS[t][0], "approve")
    row = get(c, t, a["id"])
    if row.get("status") not in (None, "open", "identified", "pending", "draft"):
        raise ApiError("Only open records can be deleted.")
    c.execute("DELETE FROM %s WHERE id=?" % t, (row["id"],))
    audit(c, u, "delete", t, row["id"], row)
    return True


def auto_task(c, u, project_id, title, source_type, source_id, due=None, priority="normal", description=None):
    """Creates a task once per source record (never duplicates)."""
    if q1(c, "SELECT id FROM tasks WHERE source_type=? AND source_id=? AND title=?", (source_type, source_id, title)):
        return None
    return ins(c, "tasks", {"project_id": project_id, "title": title, "description": description,
                            "due_date": due or today(), "priority": priority, "status": "open",
                            "source_type": source_type, "source_id": source_id,
                            "created_by": u["id"] if u else None, "ts": now()})


@api("task.status", "project", "view")
def task_status(c, u, a):
    t = get(c, "tasks", a["id"], "Task")
    if not (can(u, "project", "edit") or t["assigned_to"] == u["id"]):
        raise ApiError("You cannot change this task.")
    st = a.get("status") or "done"
    upd(c, "tasks", t["id"], {"status": st, "done_at": now() if st == "done" else None})
    return True


# ───────────────────────── files & comments ─────────────────────────
FILES_DIR = os.path.join(DATA_DIR, "files")


def store_file(c, u, meta, body):
    if not body:
        raise ApiError("The file is empty.")
    os.makedirs(FILES_DIR, exist_ok=True)
    name = os.path.basename(meta.get("filename") or "file")
    ext = os.path.splitext(name)[1].lower()[:10]
    stored = uuid.uuid4().hex + ext
    with open(os.path.join(FILES_DIR, stored), "wb") as fh:
        fh.write(body)
    row = {"kind": meta.get("kind") or ("photo" if ext in (".jpg", ".jpeg", ".png", ".webp", ".gif") else "document"),
           "filename": name, "stored": stored, "mime": meta.get("mime"), "size": len(body), "user_id": u["id"],
           "ts": now(), "date": meta.get("date") or today()}
    for k in ("entity", "caption", "stage", "location"):
        if meta.get(k):
            row[k] = meta[k]
    for k in ("entity_id", "project_id", "wbs_id", "activity_id", "boq_item_id", "dpr_id"):
        if meta.get(k):
            row[k] = int(meta[k])
    fid = ins(c, "files", row)
    audit(c, u, "upload", "files", fid, {"filename": name, "entity": row.get("entity"),
                                         "entity_id": row.get("entity_id")})
    return fid


@api("files.list")
def files_list(c, u, a):
    cond, p = [], []
    for k in ("entity", "entity_id", "project_id", "kind", "wbs_id", "activity_id", "boq_item_id", "dpr_id"):
        if a.get(k):
            cond.append("%s=?" % k)
            p.append(a[k])
    if a.get("from"):
        cond.append("date>=?")
        p.append(a["from"])
    if a.get("to"):
        cond.append("date<=?")
        p.append(a["to"])
    return q(c, "SELECT * FROM files%s ORDER BY date DESC, id DESC LIMIT 500" %
             (" WHERE " + " AND ".join(cond) if cond else ""), p)


@api("files.update")
def files_update(c, u, a):
    f = get(c, "files", a["id"], "File")
    upd(c, "files", f["id"], {k: a.get(k) for k in ("caption", "stage", "location") if k in a})
    return True


@api("files.delete")
def files_delete(c, u, a):
    f = get(c, "files", a["id"], "File")
    if f["user_id"] != u["id"] and u["role"] != "admin":
        raise ApiError("Only the uploader or an administrator can delete a file.")
    c.execute("DELETE FROM files WHERE id=?", (f["id"],))
    try:
        os.remove(os.path.join(FILES_DIR, f["stored"]))
    except OSError:
        pass
    audit(c, u, "delete", "files", f["id"], f)
    return True


@api("comments.list")
def comments_list(c, u, a):
    return {"comments": q(c, "SELECT * FROM comments WHERE entity=? AND entity_id=? ORDER BY id",
                          (a["entity"], a["entity_id"])),
            "history": q(c, "SELECT ts, user_id, action, detail FROM audit WHERE entity=? AND entity_id=? "
                            "ORDER BY id DESC LIMIT 100", (a["entity"], a["entity_id"]))}


@api("comments.add")
def comments_add(c, u, a):
    if not (a.get("text") or "").strip():
        raise ApiError("Write a comment first.")
    ins(c, "comments", {"entity": a["entity"], "entity_id": int(a["entity_id"]), "user_id": u["id"], "ts": now(),
                        "text": a["text"].strip()})
    return True


# ───────────────────────── rates ─────────────────────────
def equipment_rate(c, eq, d):
    r = q1(c, "SELECT * FROM equipment_rates WHERE equipment_id=? AND effective_from<=? ORDER BY effective_from DESC "
              "LIMIT 1", (eq["id"], d))
    if r:
        base = sum(r[k] or 0 for k in ("ownership_hr", "fuel_hr", "operator_hr", "maintenance_hr", "insurance_hr"))
        return r2(base * (1 + (r["overhead_pct"] or 0) / 100)), "rate card from %s" % r["effective_from"]
    if eq["internal_rate"]:
        return eq["internal_rate"], "internal rate on register"
    return 0.0, "no rate set"


def unit_budget(c, boq_id):
    rows = q(c, "SELECT kind, qty_per_unit, rate FROM rate_analysis WHERE boq_item_id=?", (boq_id,))
    if not rows:
        return None, {}
    parts = {}
    for r in rows:
        if r["kind"] == "overhead_pct":
            continue
        parts[r["kind"]] = parts.get(r["kind"], 0) + (r["qty_per_unit"] or 0) * (r["rate"] or 0)
    direct = sum(parts.values())
    oh = sum((r["qty_per_unit"] or 0) for r in rows if r["kind"] == "overhead_pct")
    if oh:
        parts["overhead"] = parts.get("overhead", 0) + direct * oh / 100
    return r2(sum(parts.values())), {k: r2(v) for k, v in parts.items()}


# ───────────────────────── progress recomputation (idempotent) ─────────────────────────
def recompute_progress(c, project_id):
    """Executed quantities are always recalculated from approved DPRs, so re-approval never double counts."""
    for a in q(c, "SELECT id, planned_qty FROM activities WHERE project_id=?", (project_id,)):
        agg = q1(c, "SELECT SUM(w.actual_qty) q, MIN(d.date) s, MAX(d.date) f FROM dpr_work w JOIN dpr d ON d.id=w.dpr_id "
                    "WHERE d.status='approved' AND w.activity_id=? AND w.actual_qty>0", (a["id"],))
        qty = r4(agg["q"] or 0)
        done = a["planned_qty"] and qty + EPS >= a["planned_qty"]
        upd(c, "activities", a["id"], {"actual_qty": qty, "actual_start": agg["s"],
                                       "actual_finish": agg["f"] if done else None})
    for b in q(c, "SELECT id FROM boq_items WHERE project_id=?", (project_id,)):
        qty = val(c, "SELECT SUM(w.actual_qty) FROM dpr_work w JOIN dpr d ON d.id=w.dpr_id WHERE d.status='approved' "
                     "AND w.boq_item_id=?", (b["id"],))
        if qty or val(c, "SELECT COUNT(*) FROM dpr_work w JOIN dpr d ON d.id=w.dpr_id WHERE w.boq_item_id=?", (b["id"],)):
            upd(c, "boq_items", b["id"], {"executed_qty": r4(qty)})


# ───────────────────────── DPR ─────────────────────────
DPR_PARTS = {
    "work": ("dpr_work", ["activity_id", "boq_item_id", "location", "planned_qty", "actual_qty", "remarks"]),
    "labour": ("dpr_labour", ["activity_id", "trade_id", "party_id", "count", "hours", "ot_hours", "rate"]),
    "equipment": ("dpr_equipment", ["activity_id", "equipment_id", "operator", "meter_start", "meter_end", "hours",
                                    "idle_hours", "breakdown_hours"]),
    "delays": ("dpr_delays", ["activity_id", "category", "hours", "description", "create_event"]),
}
DPR_NUM = {"planned_qty", "actual_qty", "count", "hours", "ot_hours", "rate", "meter_start", "meter_end",
           "idle_hours", "breakdown_hours", "create_event"}
DPR_ID = {"activity_id", "boq_item_id", "trade_id", "party_id", "equipment_id"}


def dv(k, v):
    if v in ("", None):
        return None if (k in DPR_ID or k in ("rate", "meter_start", "meter_end")) else (0 if k in DPR_NUM else None)
    if k in DPR_ID:
        return int(v)
    if k in DPR_NUM:
        return num(v, k)
    return str(v).strip()


def dpr_materials(c, project_id, d):
    return q(c, "SELECT l.id, i.no, l.material_id, l.qty, l.returned_qty, l.rate, l.amount, l.target, l.boq_item_id, "
                "l.equipment_id, l.activity_id FROM issue_lines l JOIN issues i ON i.id=l.issue_id WHERE "
                "i.status='posted' AND i.project_id=? AND i.date=? ORDER BY i.id", (project_id, d))


@api("dpr.get", "project", "view")
def dpr_get(c, u, a):
    d = get(c, "dpr", a["id"], "DPR")
    for part, (t, _f) in DPR_PARTS.items():
        d[part] = q(c, "SELECT * FROM %s WHERE dpr_id=? ORDER BY id" % t, (d["id"],))
    d["materials"] = dpr_materials(c, d["project_id"], d["date"])
    d["receipts"] = q(c, "SELECT g.no, l.material_id, l.accepted_qty FROM grn_lines l JOIN grn g ON g.id=l.grn_id "
                         "WHERE g.status='posted' AND g.project_id=? AND g.date=?", (d["project_id"], d["date"]))
    d["photos"] = q(c, "SELECT * FROM files WHERE dpr_id=? ORDER BY id", (d["id"],))
    d["tests"] = q(c, "SELECT * FROM qa_tests WHERE dpr_id=?", (d["id"],))
    d["vouchers"] = q(c, "SELECT id, no, total, status FROM vouchers WHERE source='dpr' AND source_id=?", (d["id"],))
    return d


@api("dpr.list", "project", "view")
def dpr_list(c, u, a):
    cond, p = ["project_id=?"], [a["project_id"]]
    if a.get("status"):
        cond.append("status=?")
        p.append(a["status"])
    if a.get("from"):
        cond.append("date>=?")
        p.append(a["from"])
    if a.get("to"):
        cond.append("date<=?")
        p.append(a["to"])
    rows = q(c, "SELECT * FROM dpr WHERE " + " AND ".join(cond) + " ORDER BY date DESC, shift LIMIT 500", p)
    for r in rows:
        r["work_lines"] = val(c, "SELECT COUNT(*) FROM dpr_work WHERE dpr_id=?", (r["id"],))
        r["manhours"] = r2(val(c, "SELECT SUM(count*(hours+ot_hours)) FROM dpr_labour WHERE dpr_id=?", (r["id"],)))
        r["machine_hours"] = r2(val(c, "SELECT SUM(hours) FROM dpr_equipment WHERE dpr_id=?", (r["id"],)))
    return rows


@api("dpr.prefill", "project", "view")
def dpr_prefill(c, u, a):
    """Planned work for the date (from the schedule) plus labour and equipment from the previous DPR."""
    pid, d = a["project_id"], a.get("date") or today()
    work = []
    for act in q(c, "SELECT * FROM activities WHERE project_id=? AND planned_start<=? AND planned_finish>=? AND "
                    "(actual_finish IS NULL) ORDER BY code", (pid, d, d)):
        days = max(1, (date.fromisoformat(act["planned_finish"]) - date.fromisoformat(act["planned_start"])).days + 1)
        work.append({"activity_id": act["id"], "boq_item_id": act["boq_item_id"], "location": act["location"],
                     "planned_qty": r2((act["planned_qty"] or 0) / days), "actual_qty": ""})
    prev = q1(c, "SELECT id FROM dpr WHERE project_id=? AND date<? ORDER BY date DESC, id DESC LIMIT 1", (pid, d))
    labour, equipment = [], []
    if prev:
        labour = [{k: l[k] for k in ("activity_id", "trade_id", "party_id", "count", "hours")}
                  for l in q(c, "SELECT * FROM dpr_labour WHERE dpr_id=?", (prev["id"],))]
        for e in q(c, "SELECT * FROM dpr_equipment WHERE dpr_id=?", (prev["id"],)):
            eq = q1(c, "SELECT meter FROM equipment WHERE id=?", (e["equipment_id"],)) or {}
            equipment.append({"activity_id": e["activity_id"], "equipment_id": e["equipment_id"],
                              "operator": e["operator"], "meter_start": eq.get("meter")})
    if not work and prev:
        work = [{"activity_id": w["activity_id"], "boq_item_id": w["boq_item_id"], "location": w["location"],
                 "planned_qty": w["planned_qty"], "actual_qty": ""}
                for w in q(c, "SELECT * FROM dpr_work WHERE dpr_id=?", (prev["id"],))]
    return {"work": work, "labour": labour, "equipment": equipment, "materials": dpr_materials(c, pid, d),
            "previous_dpr": prev["id"] if prev else None}


@api("dpr.save", "project", "edit")
def dpr_save(c, u, a):
    h = a.get("header") or {}
    need(h, "project_id", "date")
    shift = h.get("shift") or "day"
    rid = h.get("id")
    if rid:
        d = get(c, "dpr", int(rid), "DPR")
        if d["status"] != "draft":
            raise ApiError("Only draft DPRs can be edited. This one is %s." % d["status"])
    dup = q1(c, "SELECT id, no FROM dpr WHERE project_id=? AND date=? AND shift=? AND id<>?",
             (int(h["project_id"]), h["date"], shift, int(rid or 0)))
    if dup:
        raise ApiError("A DPR for this project, date and shift already exists (%s)." % (dup["no"] or dup["id"]))
    if h["date"] > today():
        raise ApiError("A DPR cannot be dated in the future.")
    data = {"project_id": int(h["project_id"]), "date": h["date"], "shift": shift, "weather": h.get("weather"),
            "site_condition": h.get("site_condition"), "remarks": h.get("remarks")}
    if rid:
        upd(c, "dpr", int(rid), data)
        rid = int(rid)
    else:
        data.update({"status": "draft", "created_by": u["id"], "no": next_no(c, "DPR", h["date"])})
        rid = ins(c, "dpr", data)
    for part, (t, fields) in DPR_PARTS.items():
        c.execute("DELETE FROM %s WHERE dpr_id=?" % t, (rid,))
        for ln in a.get(part) or []:
            x = {k: dv(k, ln.get(k)) for k in fields}
            if part == "work":
                if not x["activity_id"] and not x["boq_item_id"]:
                    continue
                if x["activity_id"]:
                    act = get(c, "activities", x["activity_id"], "Activity")
                    if act["project_id"] != data["project_id"]:
                        raise ApiError("Activity %s belongs to another project." % act["name"])
                    x["boq_item_id"] = x["boq_item_id"] or act["boq_item_id"]
                    x["location"] = x["location"] or act["location"]
                if x["boq_item_id"]:
                    inv.check_boq(c, x["boq_item_id"], data["project_id"])
                if (x["actual_qty"] or 0) < 0:
                    raise ApiError("Quantities cannot be negative.")
            elif part == "labour":
                if not x["trade_id"] or not x["count"]:
                    continue
            elif part == "equipment":
                if not x["equipment_id"]:
                    continue
                if x["meter_start"] is not None and x["meter_end"] is not None:
                    if x["meter_end"] < x["meter_start"]:
                        raise ApiError("Closing meter must not be below opening meter.")
                    eq = get(c, "equipment", x["equipment_id"])
                    if eq["meter_type"] == "hours":
                        x["hours"] = r2(x["meter_end"] - x["meter_start"])
                if (x["hours"] or 0) + (x["idle_hours"] or 0) + (x["breakdown_hours"] or 0) > 24:
                    raise ApiError("Equipment hours in a shift cannot exceed 24.")
            elif part == "delays":
                if not x["category"]:
                    continue
            x["dpr_id"] = rid
            ins(c, t, x)
    audit(c, u, "save", "dpr", rid, {"header": data})
    return {"id": rid}


def dpr_step(c, u, rid, frm, module_action):
    d = get(c, "dpr", rid, "DPR")
    if d["status"] not in frm:
        raise ApiError("This DPR is %s." % d["status"])
    require(u, "project", module_action)
    return d


@api("dpr.submit", "project", "edit")
def dpr_submit(c, u, a):
    d = dpr_step(c, u, a["id"], ("draft",), "edit")
    if not val(c, "SELECT COUNT(*) FROM dpr_work WHERE dpr_id=?", (d["id"],)) and \
            not val(c, "SELECT COUNT(*) FROM dpr_delays WHERE dpr_id=?", (d["id"],)):
        raise ApiError("Add at least one work line or a delay/issue before submitting.")
    upd(c, "dpr", d["id"], {"status": "submitted", "submitted_by": u["id"]})
    audit(c, u, "submit", "dpr", d["id"])
    return True


@api("dpr.check", "project", "edit")
def dpr_check(c, u, a):
    d = dpr_step(c, u, a["id"], ("submitted",), "edit")
    upd(c, "dpr", d["id"], {"status": "checked", "checked_by": u["id"]})
    audit(c, u, "check", "dpr", d["id"])
    return True


@api("dpr.return", "project", "edit")
def dpr_return(c, u, a):
    d = dpr_step(c, u, a["id"], ("submitted", "checked"), "edit")
    upd(c, "dpr", d["id"], {"status": "draft", "remarks": ((d["remarks"] or "") + " | Returned: " +
                                                          (a.get("reason") or "")).strip(" |")})
    audit(c, u, "return", "dpr", d["id"], a.get("reason"))
    return True


@api("dpr.approve", "project", "approve")
def dpr_approve(c, u, a):
    d = dpr_step(c, u, a["id"], ("submitted", "checked"), "approve")
    post_dpr(c, u, d)
    upd(c, "dpr", d["id"], {"status": "approved", "approved_by": u["id"], "approved_at": now(),
                            "version": (d["version"] or 0) + 1})
    recompute_progress(c, d["project_id"])
    audit(c, u, "approve", "dpr", d["id"])
    return True


@api("dpr.reopen", "admin", "edit")
def dpr_reopen(c, u, a):
    d = get(c, "dpr", a["id"], "DPR")
    if d["status"] != "approved":
        raise ApiError("Only approved DPRs can be reopened.")
    if not (a.get("reason") or "").strip():
        raise ApiError("Give a reason for reopening.")
    unpost_dpr(c, u, d, a["reason"])
    upd(c, "dpr", d["id"], {"status": "draft"})
    recompute_progress(c, d["project_id"])
    audit(c, u, "reopen", "dpr", d["id"], a["reason"])
    return True


def post_dpr(c, u, d):
    pid = d["project_id"]
    vl = []
    acts = {}

    def dims(activity_id, boq_id=None):
        if activity_id and activity_id not in acts:
            acts[activity_id] = get(c, "activities", activity_id)
        act = acts.get(activity_id) or {}
        return {"activity_id": activity_id, "wbs_id": act.get("wbs_id"),
                "boq_item_id": boq_id or act.get("boq_item_id"), "project_id": pid}
    # labour
    for l in q(c, "SELECT * FROM dpr_labour WHERE dpr_id=?", (d["id"],)):
        tr = get(c, "trades", l["trade_id"], "Trade")
        rate = l["rate"] if l["rate"] else tr["rate_hour"]
        amount = r2(l["count"] * (l["hours"] * rate + (l["ot_hours"] or 0) * rate * 1.5))
        upd(c, "dpr_labour", l["id"], {"rate": rate, "amount": amount})
        if l["party_id"] or amount <= 0:
            continue  # subcontractor gangs are costed through their bills; zero-rate trades post nothing
        vl.append(dict(role="labour_cost", debit=amount, narration="%s x%s" % (tr["name"], l["count"]),
                       **dims(l["activity_id"])))
        vl.append({"role": "payroll_payable", "credit": amount, "project_id": pid})
    # equipment
    for e in q(c, "SELECT * FROM dpr_equipment WHERE dpr_id=?", (d["id"],)):
        eq = get(c, "equipment", e["equipment_id"], "Equipment")
        log = q1(c, "SELECT * FROM logsheets WHERE equipment_id=? AND date=? AND shift=?",
                 (eq["id"], d["date"], d["shift"]))
        created = 0
        if log:
            hours = log["hours"]  # equipment hours already logged in EMM: reuse, never duplicate
            if log["dpr_id"] is None:
                upd(c, "logsheets", log["id"], {"dpr_id": d["id"], "activity_id": e["activity_id"]})
        else:
            r = log_save(c, u, {"row": {"equipment_id": eq["id"], "project_id": pid, "date": d["date"],
                                        "shift": d["shift"], "operator": e["operator"],
                                        "meter_start": e["meter_start"] if e["meter_start"] is not None else "",
                                        "meter_end": e["meter_end"] if e["meter_end"] is not None else "",
                                        "hours": e["hours"], "idle_hours": e["idle_hours"],
                                        "breakdown_hours": e["breakdown_hours"],
                                        "work": "From %s" % d["no"]}})
            upd(c, "logsheets", r["id"], {"status": "approved", "approved_by": u["id"], "dpr_id": d["id"],
                                          "activity_id": e["activity_id"]})
            log = get(c, "logsheets", r["id"])
            hours, created = log["hours"], 1
        rate, _src = equipment_rate(c, eq, d["date"])
        amount = r2(hours * rate)
        upd(c, "dpr_equipment", e["id"], {"rate": rate, "amount": amount, "logsheet_id": log["id"],
                                          "created_log": created, "hours": hours})
        if eq["ownership"] == "owned" and amount > 0:
            vl.append(dict(role="equipment_cost", debit=amount, equipment_id=eq["id"],
                           narration="%s %s h" % (eq["code"], hours), **dims(e["activity_id"])))
            vl.append({"role": "equipment_recovery", "credit": amount, "equipment_id": eq["id"], "project_id": pid})
        if (e["breakdown_hours"] or 0) > 0:
            auto_task(c, u, pid, "Breakdown: %s %s" % (eq["code"], eq["name"]), "dpr_equipment", e["id"],
                      priority="high", description="Reported in %s with %s breakdown hours. Raise a work order."
                      % (d["no"], e["breakdown_hours"]))
    # delays -> events
    for dl in q(c, "SELECT * FROM dpr_delays WHERE dpr_id=?", (d["id"],)):
        if dl["create_event"] and not dl["event_id"]:
            act = dims(dl["activity_id"]) if dl["activity_id"] else {}
            ev = reg_save(c, sysuser(u), {"table": "events", "row": {
                "project_id": pid, "date": d["date"], "type": "delay",
                "title": "%s delay (%s)" % (dl["category"].replace("_", " ").capitalize(), d["no"]),
                "description": dl["description"], "activity_id": dl["activity_id"], "wbs_id": act.get("wbs_id"),
                "dpr_id": d["id"], "delay_days": r2((dl["hours"] or 0) / (fsetting(c, "shift_hours") or 10)),
                "status": "open"}})
            upd(c, "dpr_delays", dl["id"], {"event_id": ev["id"]})
    # QA requirements
    for w in q(c, "SELECT w.*, a.test_required, a.name FROM dpr_work w JOIN activities a ON a.id=w.activity_id "
                  "WHERE w.dpr_id=? AND w.actual_qty>0 AND a.test_required IS NOT NULL AND a.test_required<>''",
               (d["id"],)):
        if not q1(c, "SELECT id FROM qa_tests WHERE dpr_id=? AND activity_id=?", (d["id"], w["activity_id"])):
            reg_save(c, sysuser(u), {"table": "qa_tests", "row": {
                "project_id": pid, "activity_id": w["activity_id"], "boq_item_id": w["boq_item_id"],
                "dpr_id": d["id"], "location": w["location"], "test_type": w["test_required"],
                "sampled_date": d["date"], "remarks": "Required by %s for %s" % (d["no"], w["name"])}})
    if vl:
        post_voucher(c, u, "journal", d["date"], "Site resources %s" % d["no"], vl, project_id=pid,
                     source="dpr", source_id=d["id"])


def unpost_dpr(c, u, d, reason):
    for v in q(c, "SELECT id FROM vouchers WHERE source='dpr' AND source_id=? AND status='posted'", (d["id"],)):
        reverse_voucher(c, u, v["id"], today(), "DPR %s reopened: %s" % (d["no"], reason))
    for e in q(c, "SELECT * FROM dpr_equipment WHERE dpr_id=?", (d["id"],)):
        if e["created_log"] and e["logsheet_id"]:
            c.execute("DELETE FROM logsheets WHERE id=? AND dpr_id=?", (e["logsheet_id"], d["id"]))
        elif e["logsheet_id"]:
            upd(c, "logsheets", e["logsheet_id"], {"dpr_id": None})
        upd(c, "dpr_equipment", e["id"], {"logsheet_id": None, "created_log": 0})


# ───────────────────────── schedule metrics ─────────────────────────
def planned_fraction(a, asof):
    s, f = a.get("planned_start"), a.get("planned_finish")
    if not s or not f:
        return 0.0
    if asof < s:
        return 0.0
    if asof >= f:
        return 1.0
    tot = (date.fromisoformat(f) - date.fromisoformat(s)).days + 1
    return ((date.fromisoformat(asof) - date.fromisoformat(s)).days + 1) / tot


def activity_metrics(c, a, asof):
    pq = a["planned_qty"] or 0
    act_q = val(c, "SELECT SUM(w.actual_qty) FROM dpr_work w JOIN dpr d ON d.id=w.dpr_id WHERE d.status='approved' "
                   "AND w.activity_id=? AND d.date<=?", (a["id"], asof))
    pf = planned_fraction(a, asof)
    recent = q(c, "SELECT d.date, SUM(w.actual_qty) q FROM dpr_work w JOIN dpr d ON d.id=w.dpr_id WHERE "
                  "d.status='approved' AND w.activity_id=? AND d.date<=? GROUP BY d.date ORDER BY d.date DESC LIMIT 14",
               (a["id"], asof))
    avg_daily = sum(r["q"] for r in recent) / len(recent) if recent else 0
    lab = q1(c, "SELECT SUM(l.count*(l.hours+l.ot_hours)) mh FROM dpr_labour l JOIN dpr d ON d.id=l.dpr_id WHERE "
                "d.status='approved' AND l.activity_id=?", (a["id"],))
    eqh = val(c, "SELECT SUM(e.hours) FROM dpr_equipment e JOIN dpr d ON d.id=e.dpr_id WHERE d.status='approved' AND "
                 "e.activity_id=?", (a["id"],))
    ac = val(c, "SELECT SUM(l.debit-l.credit) FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id JOIN accounts x "
                "ON x.id=l.account_id WHERE x.type='expense' AND l.activity_id=? AND " + POSTED, (a["id"],))
    remaining = max(pq - act_q, 0)
    forecast = None
    if remaining <= EPS and pq:
        forecast = a.get("actual_finish") or asof
    elif avg_daily > EPS:
        forecast = (date.fromisoformat(asof) + timedelta(days=int(remaining / avg_daily + 0.999))).isoformat()
    delay = None
    if forecast and a.get("planned_finish"):
        delay = (date.fromisoformat(forecast) - date.fromisoformat(a["planned_finish"])).days
    elif not forecast and a.get("planned_finish") and asof > a["planned_finish"] and remaining > EPS:
        delay = (date.fromisoformat(asof) - date.fromisoformat(a["planned_finish"])).days
    mh = lab["mh"] or 0
    lprod = r4(act_q / mh) if mh else None
    eprod = r4(act_q / eqh) if eqh else None
    qa_pending = val(c, "SELECT COUNT(*) FROM qa_tests WHERE activity_id=? AND status='pending'", (a["id"],))
    qa_failed = val(c, "SELECT COUNT(*) FROM qa_tests WHERE activity_id=? AND status='failed'", (a["id"],))
    return {"actual_qty": r4(act_q), "planned_to_date": r4(pq * pf), "planned_pct": round(100 * pf, 1),
            "actual_pct": round(100 * act_q / pq, 1) if pq else 0, "variance_qty": r4(act_q - pq * pf),
            "avg_daily": r4(avg_daily), "forecast_finish": forecast, "delay_days": delay,
            "manhours": r2(mh), "labour_prod": lprod, "equip_hours": r2(eqh), "equip_prod": eprod,
            "labour_prod_var": round(100 * (lprod - a["std_labour_prod"]) / a["std_labour_prod"], 1)
            if lprod is not None and a.get("std_labour_prod") else None,
            "equip_prod_var": round(100 * (eprod - a["std_equip_prod"]) / a["std_equip_prod"], 1)
            if eprod is not None and a.get("std_equip_prod") else None,
            "actual_cost": r2(ac), "unit_cost": r2(ac / act_q) if act_q else None,
            "qa_hold": bool(act_q and (qa_pending or qa_failed)), "qa_pending": qa_pending, "qa_failed": qa_failed}


def activity_weights(c, acts):
    ws = {}
    for a in acts:
        w = a["weight"] or 0
        if not w and a["boq_item_id"]:
            b = q1(c, "SELECT qty, revised_qty, rate, revised_rate FROM boq_items WHERE id=?", (a["boq_item_id"],))
            if b:
                w = (b["revised_qty"] if b["revised_qty"] is not None else b["qty"]) * \
                    (b["revised_rate"] if b["revised_rate"] is not None else b["rate"])
        ws[a["id"]] = w
    if not any(ws.values()):
        ws = {k: 1 for k in ws}
    tot = sum(ws.values()) or 1
    return {k: v / tot for k, v in ws.items()}


@api("sched.tree", "project", "view")
def sched_tree(c, u, a):
    pid = a["project_id"]
    asof = a.get("as_of") or today()
    wbs = q(c, "SELECT * FROM wbs WHERE project_id=? ORDER BY sort, code", (pid,))
    acts = q(c, "SELECT * FROM activities WHERE project_id=? ORDER BY code, id", (pid,))
    w = activity_weights(c, acts)
    for x in acts:
        x.update(activity_metrics(c, x, asof))
        x["weight_share"] = round(100 * w.get(x["id"], 0), 2)
    node_by = {n["id"]: dict(n, planned=0.0, actual=0.0, share=0.0) for n in wbs}
    for x in acts:
        n = node_by.get(x["wbs_id"])
        while n:
            sh = w.get(x["id"], 0)
            n["share"] += sh
            n["planned"] += sh * x["planned_pct"]
            n["actual"] += sh * min(x["actual_pct"], 100)
            n = node_by.get(n["parent_id"])
    for n in node_by.values():
        n["planned_pct"] = round(n["planned"] / n["share"], 1) if n["share"] else 0
        n["actual_pct"] = round(n["actual"] / n["share"], 1) if n["share"] else 0
    planned = round(sum(w.get(x["id"], 0) * x["planned_pct"] for x in acts), 2)
    actual = round(sum(w.get(x["id"], 0) * min(x["actual_pct"], 100) for x in acts), 2)
    finishes = [x["forecast_finish"] for x in acts if x["forecast_finish"]]
    return {"wbs": list(node_by.values()), "activities": acts, "planned_pct": planned, "actual_pct": actual,
            "spi": round(actual / planned, 2) if planned else None,
            "forecast_finish": max(finishes) if finishes and len(finishes) == len([x for x in acts if x["planned_qty"]])
            else None, "as_of": asof}


@api("sched.scurve", "project", "view")
def sched_scurve(c, u, a):
    pid = a["project_id"]
    acts = q(c, "SELECT * FROM activities WHERE project_id=?", (pid,))
    if not acts:
        return []
    w = activity_weights(c, acts)
    starts = [x["planned_start"] for x in acts if x["planned_start"]]
    ends = [x["planned_finish"] for x in acts if x["planned_finish"]]
    if not starts or not ends:
        return []
    d0, d1 = date.fromisoformat(min(starts)), date.fromisoformat(max(max(ends), today()))
    step = max(7, (d1 - d0).days // 40)
    out = []
    d = d0
    while True:
        ds = d.isoformat()
        pl = sum(w[x["id"]] * planned_fraction(x, ds) for x in acts) * 100
        ac = None
        if ds <= today():
            ac = 0.0
            for x in acts:
                if x["planned_qty"]:
                    qd = val(c, "SELECT SUM(wk.actual_qty) FROM dpr_work wk JOIN dpr dd ON dd.id=wk.dpr_id WHERE "
                                "dd.status='approved' AND wk.activity_id=? AND dd.date<=?", (x["id"], ds))
                    ac += w[x["id"]] * min(qd / x["planned_qty"], 1) * 100
        out.append({"date": ds, "planned": round(pl, 1), "actual": round(ac, 1) if ac is not None else None})
        if d >= d1:
            break
        d = min(d + timedelta(days=step), d1)
    return out


# ───────────────────────── BOQ view & EVM ─────────────────────────
def boq_figures(c, b, asof):
    rq = b["revised_qty"] if b["revised_qty"] is not None else b["qty"]
    rate = b["revised_rate"] if b["revised_rate"] is not None else b["rate"]
    ub, parts = unit_budget(c, b["id"])
    measured = val(c, "SELECT SUM(l.qty) FROM measurement_lines l JOIN measurements m ON m.id=l.measurement_id WHERE "
                      "m.status='verified' AND l.boq_item_id=?", (b["id"],))
    billed = val(c, "SELECT SUM(l.qty) FROM ipc_lines l JOIN ipc i ON i.id=l.ipc_id WHERE i.status IN "
                    "('submitted','certified') AND l.boq_item_id=?", (b["id"],))
    certified = val(c, "SELECT SUM(l.qty) FROM ipc_lines l JOIN ipc i ON i.id=l.ipc_id WHERE i.status='certified' AND "
                       "l.boq_item_id=?", (b["id"],))
    var_qty = val(c, "SELECT SUM(var_qty) FROM variations WHERE boq_item_id=? AND status='approved'", (b["id"],))
    ac = val(c, "SELECT SUM(l.debit-l.credit) FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id JOIN accounts x "
                "ON x.id=l.account_id WHERE x.type='expense' AND l.boq_item_id=? AND v.date<=? AND " + POSTED,
             (b["id"], asof))
    ex = b["executed_qty"] or 0
    pv_qty = 0.0
    for a in q(c, "SELECT * FROM activities WHERE boq_item_id=?", (b["id"],)):
        pv_qty += (a["planned_qty"] or 0) * planned_fraction(a, asof)
    bac = r2(rq * ub) if ub is not None else None
    ev = r2(ex * ub) if ub is not None else None
    pv = r2(pv_qty * ub) if ub is not None else None
    auc = r2(ac / ex) if ex > EPS else None
    rem = max(rq - ex, 0)
    etc = r2(rem * (auc if auc is not None else (ub or 0)))
    eac = r2(ac + etc)
    # remaining work with neither a cost so far nor a budget (rate analysis) has no cost forecast: its value must
    # not be counted as profit, or an item with no budget shows a 100% margin
    basis = "actual" if auc is not None else ("budget" if ub and ub > EPS else "none")
    no_fc = r2(rem * rate) if basis == "none" and rem > EPS else 0.0
    return {"id": b["id"], "code": b["code"], "description": b["description"], "unit": b["unit"],
            "wbs_id": b.get("wbs_id"), "location": b.get("location"), "contract_qty": b["qty"],
            "contract_rate": b["rate"], "contract_amount": r2(b["qty"] * b["rate"]), "revised_qty": r4(rq),
            "revised_rate": rate, "revised_amount": r2(rq * rate), "variation_qty": r4(var_qty),
            "executed_qty": r4(ex), "balance_qty": r4(rq - ex), "measured_qty": r4(measured),
            "billed_qty": r4(billed), "certified_qty": r4(certified),
            "progress_pct": round(100 * ex / rq, 1) if rq else 0, "earned_revenue": r2(ex * rate),
            "unit_budget": ub, "budget_parts": parts, "bac": bac, "pv": pv, "ev": ev, "ac": r2(ac),
            "cv": r2(ev - ac) if ev is not None else None, "sv": r2(ev - pv) if ev is not None else None,
            "cpi": round(ev / ac, 2) if ev is not None and ac > EPS else None,
            "spi": round(ev / pv, 2) if ev is not None and pv else None, "actual_unit_cost": auc, "etc": etc,
            "eac": eac, "forecast_revenue": r2(rq * rate),
            "forecast_profit": r2(rq * rate - no_fc - eac) if not no_fc else None,
            "forecast_basis": basis, "no_forecast_revenue": no_fc,
            "unbilled_measured": r4(measured - billed)}


@api("boq.control", "commercial", "view")
def boq_control(c, u, a):
    asof = a.get("as_of") or today()
    return [boq_figures(c, b, asof) for b in q(c, "SELECT * FROM boq_items WHERE project_id=? ORDER BY code",
                                                (a["project_id"],))]


def project_evm(c, pid, asof):
    rows = [boq_figures(c, b, asof) for b in q(c, "SELECT * FROM boq_items WHERE project_id=?", (pid,))]
    exp = q1(c, "SELECT SUM(l.debit-l.credit) t, SUM(CASE WHEN l.boq_item_id IS NULL AND l.activity_id IS NULL "
                "THEN l.debit-l.credit ELSE 0 END) un FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id JOIN "
                "accounts x ON x.id=l.account_id WHERE x.type='expense' AND l.project_id=? AND v.date<=? AND " + POSTED,
             (pid, asof))
    # Plant charged internally to the work is a transfer, not a second cost: the fuel, depreciation
    # and repairs behind it are already in the expense accounts. Net the recovery off, or every
    # project that uses internal plant rates would show an inflated cost and a false loss.
    recovery = r2(val(c, "SELECT SUM(l.credit-l.debit) FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id "
                         "JOIN accounts x ON x.id=l.account_id WHERE x.role='equipment_recovery' AND "
                         "l.project_id=? AND v.date<=? AND " + POSTED, (pid, asof)))
    ac_total = r2((exp["t"] or 0) - recovery)
    unalloc = r2(max(0.0, (exp["un"] or 0) - recovery))
    act_only = r2(val(c, "SELECT SUM(l.debit-l.credit) FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id JOIN "
                         "accounts x ON x.id=l.account_id WHERE x.type='expense' AND l.project_id=? AND l.boq_item_id "
                         "IS NULL AND l.activity_id IS NOT NULL AND v.date<=? AND " + POSTED, (pid, asof)))
    fr = sum(r["forecast_revenue"] for r in rows)
    er = sum(r["earned_revenue"] for r in rows)
    progress = er / fr if fr else 0
    budgeted = [r for r in rows if r["bac"] is not None]
    bac = sum(r["bac"] for r in budgeted)
    oh_budget = val(c, "SELECT SUM(amount) FROM budgets WHERE project_id=? AND boq_item_id IS NULL", (pid,))
    ev = sum(r["ev"] for r in budgeted)
    pv = sum(r["pv"] for r in budgeted)
    ac_boq = sum(r["ac"] for r in rows)
    eac_items = sum(r["eac"] for r in rows)
    other = unalloc + act_only
    eac_other = r2(other / progress) if progress > 0.02 else r2(max(other, oh_budget))
    eac = r2(eac_items + eac_other)
    contract_rev = sum(r["contract_amount"] for r in rows)
    tender_cost = sum((r["contract_qty"] * r["unit_budget"]) for r in budgeted) + oh_budget
    tender_margin = round(100 * (contract_rev - tender_cost) / contract_rev, 1) if contract_rev and budgeted else None
    cur_margin = round(100 * (er - ac_total) / er, 1) if er else None
    no_fc = r2(sum(r["no_forecast_revenue"] for r in rows))
    fr_cov = r2(fr - no_fc)                 # revenue with a cost forecast behind it
    fc_margin = round(100 * (fr_cov - eac) / fr_cov, 1) if fr_cov > EPS else None
    return {"rows": rows, "contract_revenue": r2(contract_rev), "forecast_revenue": r2(fr), "earned_revenue": r2(er),
            "forecast_revenue_covered": fr_cov, "no_forecast_revenue": no_fc,
            "no_forecast_items": len([r for r in rows if r["no_forecast_revenue"]]),
            "progress_value_pct": round(100 * progress, 1), "bac": r2(bac + oh_budget), "pv": r2(pv), "ev": r2(ev),
            "ac": ac_total, "ac_boq": r2(ac_boq), "ac_unallocated": r2(other),
            "cpi": round(ev / ac_boq, 2) if ac_boq > EPS and budgeted else None,
            "spi": round(ev / pv, 2) if pv else None, "cv": r2(ev - ac_boq), "sv": r2(ev - pv),
            "eac": eac, "etc": r2(eac - ac_total), "forecast_profit": r2(fr_cov - eac),
            "tender_margin": tender_margin, "current_margin": cur_margin, "forecast_margin": fc_margin,
            "margin_fade": round(tender_margin - fc_margin, 1) if tender_margin is not None and fc_margin is not None
            else None, "items_without_budget": len(rows) - len(budgeted), "committed": r2(inv_committed(c, pid))}


def inv_committed(c, pid):
    return val(c, "SELECT SUM((pl.qty-MIN(pl.received_qty,pl.qty))*pl.rate) FROM po_lines pl JOIN po p ON p.id=pl.po_id "
                  "WHERE p.project_id=? AND p.status IN ('approved','partially_received')", (pid,))


@api("evm.project", "commercial", "view")
def evm_project(c, u, a):
    return project_evm(c, a["project_id"], a.get("as_of") or today())


# ───────────────────────── variations ─────────────────────────
@api("var.submit", "commercial", "edit")
def var_submit(c, u, a):
    v = get(c, "variations", a["id"], "Variation")
    if v["status"] != "identified":
        raise ApiError("Only new variations can be submitted.")
    if not v["boq_item_id"] and not (v["new_code"] and v["new_description"] and v["new_unit"] and v["new_rate"]):
        raise ApiError("Choose a BOQ item, or give code, description, unit and rate for a new item.")
    upd(c, "variations", v["id"], {"status": "submitted"})
    return True


@api("var.decide", "commercial", "approve")
def var_decide(c, u, a):
    v = get(c, "variations", a["id"], "Variation")
    if v["status"] != "submitted":
        raise ApiError("Only submitted variations can be decided.")
    if a.get("decision") == "rejected":
        upd(c, "variations", v["id"], {"status": "rejected", "approved_date": today()})
        return True
    if v["boq_item_id"]:
        b = get(c, "boq_items", v["boq_item_id"])
        rq = (b["revised_qty"] if b["revised_qty"] is not None else b["qty"]) + (v["var_qty"] or 0)
        if rq < (b["executed_qty"] or 0) - EPS:
            raise ApiError("Revised quantity would fall below executed quantity.")
        data = {"revised_qty": r4(rq)}
        if v["new_rate"]:
            data["revised_rate"] = v["new_rate"]
        upd(c, "boq_items", b["id"], data)
    else:
        bid = ins(c, "boq_items", {"project_id": v["project_id"], "code": v["new_code"],
                                   "description": v["new_description"], "unit": v["new_unit"], "qty": 0,
                                   "rate": v["new_rate"], "revised_qty": v["var_qty"], "revised_rate": v["new_rate"],
                                   "executed_qty": 0})
        upd(c, "variations", v["id"], {"boq_item_id": bid})
    upd(c, "variations", v["id"], {"status": "approved", "approved_date": today()})
    audit(c, u, "approve", "variations", v["id"])
    return True


# ───────────────────────── QA ─────────────────────────
@api("qa.result", "quality", "edit")
def qa_result(c, u, a):
    t = get(c, "qa_tests", a["id"], "Test")
    st = a.get("status")
    if st not in ("passed", "failed"):
        raise ApiError("Choose passed or failed.")
    if t["status"] != "pending":
        raise ApiError("A result is already recorded.")
    upd(c, "qa_tests", t["id"], {"status": st, "result_value": a.get("result_value"),
                                 "result_date": a.get("date") or today()})
    if st == "failed":
        n = reg_save(c, sysuser(u), {"table": "ncrs", "row": {
            "project_id": t["project_id"], "date": a.get("date") or today(),
            "title": "Failed %s %s" % (t["test_type"], t["no"]), "activity_id": t["activity_id"], "test_id": t["id"],
            "description": "Result: %s. Criteria: %s" % (a.get("result_value") or "", t["criteria"] or ""),
            "due_date": (date.today() + timedelta(days=7)).isoformat()}})
        upd(c, "qa_tests", t["id"], {"ncr_id": n["id"]})
        auto_task(c, u, t["project_id"], "Corrective action for %s" % n["no"], "ncrs", n["id"], priority="high",
                  due=n["due_date"])
    audit(c, u, "result", "qa_tests", t["id"], a)
    return True


@api("ncr.close", "quality", "approve")
def ncr_close(c, u, a):
    n = get(c, "ncrs", a["id"], "NCR")
    if not (a.get("corrective_action") or n["corrective_action"]):
        raise ApiError("Record the corrective action before closing.")
    upd(c, "ncrs", n["id"], {"status": "closed", "closed_date": today(),
                             "corrective_action": a.get("corrective_action") or n["corrective_action"]})
    return True


# ───────────────────────── measurement & IPC ─────────────────────────
@api("meas.prefill", "commercial", "view")
def meas_prefill(c, u, a):
    out = []
    for b in q(c, "SELECT * FROM boq_items WHERE project_id=? ORDER BY code", (a["project_id"],)):
        measured = val(c, "SELECT SUM(l.qty) FROM measurement_lines l JOIN measurements m ON m.id=l.measurement_id "
                          "WHERE m.status='verified' AND l.boq_item_id=?", (b["id"],))
        rest = r4((b["executed_qty"] or 0) - measured)
        if rest > EPS:
            out.append({"boq_item_id": b["id"], "qty": rest, "executed": b["executed_qty"], "measured": r4(measured)})
    return out


@api("meas.get", "commercial", "view")
def meas_get(c, u, a):
    m = get(c, "measurements", a["id"])
    m["lines"] = q(c, "SELECT * FROM measurement_lines WHERE measurement_id=?", (m["id"],))
    return m


@api("meas.list", "commercial", "view")
def meas_list(c, u, a):
    rows = q(c, "SELECT * FROM measurements WHERE project_id=? ORDER BY date DESC, id DESC", (a["project_id"],))
    for r in rows:
        r["value"] = r2(val(c, "SELECT SUM(l.qty*COALESCE(b.revised_rate,b.rate)) FROM measurement_lines l JOIN "
                               "boq_items b ON b.id=l.boq_item_id WHERE l.measurement_id=?", (r["id"],)))
    return rows


@api("meas.save", "commercial", "edit")
def meas_save(c, u, a):
    h = a.get("header") or {}
    need(h, "project_id", "date")
    if h.get("id"):
        m = get(c, "measurements", int(h["id"]))
        if m["status"] != "draft":
            raise ApiError("Verified measurements are locked.")
        upd(c, "measurements", m["id"], {"date": h["date"], "remarks": h.get("remarks")})
        mid = m["id"]
    else:
        mid = ins(c, "measurements", {"no": next_no(c, "MS", h["date"]), "project_id": int(h["project_id"]),
                                      "date": h["date"], "remarks": h.get("remarks"), "status": "draft",
                                      "created_by": u["id"]})
    c.execute("DELETE FROM measurement_lines WHERE measurement_id=?", (mid,))
    for l in a.get("lines") or []:
        if not l.get("boq_item_id") or num(l.get("qty")) == 0:
            continue
        inv.check_boq(c, int(l["boq_item_id"]), int(h["project_id"]))
        ins(c, "measurement_lines", {"measurement_id": mid, "boq_item_id": int(l["boq_item_id"]),
                                     "qty": num(l["qty"]), "location": l.get("location"), "remarks": l.get("remarks")})
    return {"id": mid}


@api("meas.verify", "commercial", "approve")
def meas_verify(c, u, a):
    m = meas_get(c, u, a)
    if m["status"] != "draft":
        raise ApiError("Already verified.")
    if not m["lines"]:
        raise ApiError("No lines to verify.")
    for l in m["lines"]:
        b = get(c, "boq_items", l["boq_item_id"])
        measured = val(c, "SELECT SUM(ml.qty) FROM measurement_lines ml JOIN measurements x ON x.id=ml.measurement_id "
                          "WHERE x.status='verified' AND ml.boq_item_id=?", (b["id"],))
        if measured + l["qty"] > (b["executed_qty"] or 0) + EPS and not a.get("override"):
            raise ApiError("%s: measured %s would exceed executed %s from approved DPRs. Tick override to accept."
                           % (b["code"], r4(measured + l["qty"]), b["executed_qty"]))
    upd(c, "measurements", m["id"], {"status": "verified", "verified_by": u["id"]})
    audit(c, u, "verify", "measurements", m["id"], {"override": bool(a.get("override"))})
    return True


@api("meas.delete", "commercial", "edit")
def meas_delete(c, u, a):
    m = get(c, "measurements", a["id"])
    if m["status"] != "draft":
        raise ApiError("Verified measurements cannot be deleted.")
    c.execute("DELETE FROM measurement_lines WHERE measurement_id=?", (m["id"],))
    c.execute("DELETE FROM measurements WHERE id=?", (m["id"],))
    return True


def ipc_prev(c, boq_id, exclude_ipc):
    return val(c, "SELECT SUM(l.qty) FROM ipc_lines l JOIN ipc i ON i.id=l.ipc_id WHERE i.status IN "
                  "('submitted','certified') AND l.boq_item_id=? AND i.id<>?", (boq_id, exclude_ipc or 0))


@api("ipc.prefill", "commercial", "view")
def ipc_prefill(c, u, a):
    out = []
    for b in q(c, "SELECT * FROM boq_items WHERE project_id=? ORDER BY code", (a["project_id"],)):
        measured = val(c, "SELECT SUM(l.qty) FROM measurement_lines l JOIN measurements m ON m.id=l.measurement_id "
                          "WHERE m.status='verified' AND l.boq_item_id=?", (b["id"],))
        prev = ipc_prev(c, b["id"], a.get("ipc_id"))
        cur = r4(measured - prev)
        if cur > EPS:
            out.append({"boq_item_id": b["id"], "prev_qty": r4(prev), "qty": cur,
                        "rate": b["revised_rate"] if b["revised_rate"] is not None else b["rate"]})
    return out


@api("ipc.get", "commercial", "view")
def ipc_get(c, u, a):
    i = get(c, "ipc", a["id"], "IPC")
    i["lines"] = q(c, "SELECT * FROM ipc_lines WHERE ipc_id=? ORDER BY id", (i["id"],))
    for l in i["lines"]:
        b = get(c, "boq_items", l["boq_item_id"])
        l.update({"code": b["code"], "description": b["description"], "unit": b["unit"],
                  "revised_qty": b["revised_qty"] if b["revised_qty"] is not None else b["qty"],
                  "cum_qty": r4((l["prev_qty"] or 0) + l["qty"]),
                  "cum_amount": r2(((l["prev_qty"] or 0) + l["qty"]) * l["rate"])})
    if i["invoice_id"]:
        inv_ = get(c, "invoices", i["invoice_id"])
        i["invoice_no"] = inv_["no"]
        i["paid"] = invoice_paid(c, inv_["id"])
        i["receivable"] = r2(inv_["payable"] - i["paid"])
    return i


@api("ipc.list", "commercial", "view")
def ipc_list(c, u, a):
    rows = q(c, "SELECT * FROM ipc WHERE project_id=? ORDER BY date DESC, id DESC", (a["project_id"],))
    for r in rows:
        r["paid"] = invoice_paid(c, r["invoice_id"]) if r["invoice_id"] else 0
    return rows


def ipc_totals(i, lines):
    gross = r2(sum(r2(l["qty"] * l["rate"]) for l in lines))
    ret = r2(gross * (i["retention_pct"] or 0) / 100)
    vat = r2(gross * (i["vat_rate"] or 0) / 100)
    tds = r2(gross * (i["tds_pct"] or 0) / 100)
    net = r2(gross + vat - ret - tds - (i["advance_recovery"] or 0))
    return gross, ret, vat, tds, net


@api("ipc.save", "commercial", "edit")
def ipc_save(c, u, a):
    h = a.get("header") or {}
    need(h, "project_id", "client_id", "date")
    hdr = {"project_id": int(h["project_id"]), "client_id": int(h["client_id"]), "date": h["date"],
           "period_to": h.get("period_to") or h["date"], "retention_pct": num(h.get("retention_pct")),
           "tds_pct": num(h.get("tds_pct")), "vat_rate": num(h.get("vat_rate")),
           "advance_recovery": num(h.get("advance_recovery")), "client_ref": h.get("client_ref"),
           "remarks": h.get("remarks")}
    if h.get("id"):
        i = get(c, "ipc", int(h["id"]))
        if i["status"] != "draft":
            raise ApiError("Only draft IPCs can be edited.")
        upd(c, "ipc", i["id"], hdr)
        iid = i["id"]
    else:
        hdr.update({"no": next_no(c, "IPC", h["date"]), "status": "draft", "created_by": u["id"]})
        iid = ins(c, "ipc", hdr)
    c.execute("DELETE FROM ipc_lines WHERE ipc_id=?", (iid,))
    lines = []
    for l in a.get("lines") or []:
        if not l.get("boq_item_id") or num(l.get("qty")) <= 0:
            continue
        b = inv.check_boq(c, int(l["boq_item_id"]), hdr["project_id"])
        rate = b["revised_rate"] if b["revised_rate"] is not None else b["rate"]
        x = {"ipc_id": iid, "boq_item_id": b["id"], "prev_qty": r4(ipc_prev(c, b["id"], iid)), "qty": num(l["qty"]),
             "rate": rate, "amount": r2(num(l["qty"]) * rate)}
        ins(c, "ipc_lines", x)
        lines.append(x)
    gross, ret, vat, tds, net = ipc_totals(hdr, lines)
    upd(c, "ipc", iid, {"gross": gross, "net": net})
    return {"id": iid}


def ipc_validate(c, i, lines, override):
    for l in lines:
        b = get(c, "boq_items", l["boq_item_id"])
        rq = b["revised_qty"] if b["revised_qty"] is not None else b["qty"]
        cum = ipc_prev(c, b["id"], i["id"]) + l["qty"]
        if cum > rq + EPS:
            raise ApiError("%s: cumulative %s exceeds approved quantity %s. An approved variation is needed."
                           % (b["code"], r4(cum), r4(rq)))
        measured = val(c, "SELECT SUM(ml.qty) FROM measurement_lines ml JOIN measurements m ON m.id=ml.measurement_id "
                          "WHERE m.status='verified' AND ml.boq_item_id=?", (b["id"],))
        if cum > measured + EPS and not override:
            raise ApiError("%s: cumulative %s exceeds verified measurement %s. Tick override to bill anyway."
                           % (b["code"], r4(cum), r4(measured)))


@api("ipc.submit", "commercial", "edit")
def ipc_submit(c, u, a):
    i = ipc_get(c, u, a)
    if i["status"] != "draft":
        raise ApiError("Only drafts can be submitted.")
    if not i["lines"]:
        raise ApiError("Add BOQ lines first.")
    ipc_validate(c, i, i["lines"], a.get("override"))
    upd(c, "ipc", i["id"], {"status": "submitted"})
    audit(c, u, "submit", "ipc", i["id"])
    return True


@api("ipc.return", "commercial", "approve")
def ipc_return(c, u, a):
    i = get(c, "ipc", a["id"])
    if i["status"] != "submitted":
        raise ApiError("Only submitted IPCs can be returned.")
    upd(c, "ipc", i["id"], {"status": "draft"})
    return True


@api("ipc.certify", "commercial", "approve")
def ipc_certify(c, u, a):
    """Consultant-certified quantities -> sales invoice -> receivable, VAT, TDS, retention, advance (accounts)."""
    i = ipc_get(c, u, a)
    if i["status"] != "submitted":
        raise ApiError("Only submitted IPCs can be certified.")
    cert = {int(k): num(v) for k, v in (a.get("certified") or {}).items()}
    lines = []
    for l in i["lines"]:
        qty = cert.get(l["id"], l["qty"])
        if qty < 0 or qty > l["qty"] + EPS:
            raise ApiError("%s: certified quantity must be between 0 and claimed %s." % (l["code"], l["qty"]))
        upd(c, "ipc_lines", l["id"], {"qty": qty, "amount": r2(qty * l["rate"])})
        if qty > EPS:
            lines.append(dict(l, qty=qty))
    if not lines:
        raise ApiError("Nothing was certified.")
    ipc_validate(c, i, lines, True)
    d = a.get("date") or today()
    hdr = dict(i, advance_recovery=num(a.get("advance_recovery", i["advance_recovery"])))
    gross, ret, vat, tds, net = ipc_totals(hdr, lines)
    acc = val(c, "SELECT id FROM accounts WHERE role='contract_revenue'")
    iid = ins(c, "invoices", {"kind": "sales", "party_id": i["client_id"], "project_id": i["project_id"], "date": d,
                              "party_inv_no": a.get("client_ref") or i["client_ref"] or i["no"], "tds": tds,
                              "retention": ret, "advance_recovery": hdr["advance_recovery"], "status": "draft",
                              "source": "ipc", "remarks": "Certified %s" % i["no"], "created_by": u["id"]})
    for l in lines:
        ins(c, "invoice_lines", {"invoice_id": iid, "description": "%s %s" % (l["code"], (l["description"] or "")[:60]),
                                 "qty": l["qty"], "rate": l["rate"], "vat_rate": i["vat_rate"] or 0,
                                 "amount": r2(l["qty"] * l["rate"]), "account_id": acc,
                                 "boq_item_id": l["boq_item_id"]})
    invoice_post(c, sysuser(u), {"id": iid})
    upd(c, "ipc", i["id"], {"status": "certified", "invoice_id": iid, "gross": gross, "net": net,
                            "certified_by": u["id"], "client_ref": a.get("client_ref") or i["client_ref"],
                            "advance_recovery": hdr["advance_recovery"]})
    audit(c, u, "certify", "ipc", i["id"], {"gross": gross, "net": net, "invoice_id": iid})
    return {"invoice_id": iid, "gross": gross, "net": net}


@api("ipc.uncertify", "accounts", "approve")
def ipc_uncertify(c, u, a):
    i = get(c, "ipc", a["id"])
    if i["status"] != "certified":
        raise ApiError("Only certified IPCs can be reversed.")
    invoice_cancel(c, sysuser(u), {"id": i["invoice_id"], "reason": a.get("reason") or "IPC reversed"})
    upd(c, "ipc", i["id"], {"status": "submitted", "invoice_id": None})
    audit(c, u, "uncertify", "ipc", i["id"], a.get("reason"))
    return True


@api("ipc.delete", "commercial", "edit")
def ipc_delete(c, u, a):
    i = get(c, "ipc", a["id"])
    if i["status"] != "draft":
        raise ApiError("Only draft IPCs can be deleted.")
    c.execute("DELETE FROM ipc_lines WHERE ipc_id=?", (i["id"],))
    c.execute("DELETE FROM ipc WHERE id=?", (i["id"],))
    return True


# ───────────────────────── material risk ─────────────────────────
def material_risks(c, pid):
    out = []
    for m in q(c, "SELECT m.* FROM materials m WHERE m.active=1 AND EXISTS (SELECT 1 FROM stock_ledger l WHERE "
                  "l.material_id=m.id AND l.project_id=?)", (pid,)):
        have = inv.project_available(c, pid, m["id"])
        since = (date.today() - timedelta(days=30)).isoformat()
        used = val(c, "SELECT SUM(l.qty-l.returned_qty) FROM issue_lines l JOIN issues i ON i.id=l.issue_id WHERE "
                      "i.status='posted' AND i.project_id=? AND l.material_id=? AND i.date>=?", (pid, m["id"], since))
        daily = used / 30
        pending_po = val(c, "SELECT SUM(pl.qty-pl.received_qty) FROM po_lines pl JOIN po p ON p.id=pl.po_id WHERE "
                            "p.project_id=? AND pl.material_id=? AND p.status IN ('approved','partially_received')",
                         (pid, m["id"]))
        lead = m["lead_days"] or 7
        days_left = have / daily if daily > EPS else None
        risk = daily > EPS and have < daily * lead
        last = q1(c, "SELECT l.rate FROM grn_lines l JOIN grn g ON g.id=l.grn_id WHERE g.status='posted' AND "
                     "l.material_id=? ORDER BY g.date DESC LIMIT 1", (m["id"],))
        out.append({"material_id": m["id"], "code": m["code"], "name": m["name"], "unit": m["unit"],
                    "available": r4(have), "avg_daily": r4(daily),
                    "days_left": round(days_left, 1) if days_left is not None else None, "lead_days": lead,
                    "pending_po": r4(pending_po), "last_rate": last["rate"] if last else None, "risk": bool(risk),
                    "why": ("Stock %s %s covers %.1f days; delivery takes %s days%s." %
                            (r4(have), m["unit"], days_left or 0, lead,
                             "" if not pending_po else ", %s on order" % r4(pending_po))) if risk else ""})
    return out


@api("stock.risk", "inventory", "view")
def stock_risk(c, u, a):
    return material_risks(c, a["project_id"])


# ───────────────────────── control room, action centre, portfolio ─────────────────────────
def health(c, pid, asof):
    sched = sched_tree(c, None, {"project_id": pid, "as_of": asof})
    ev = project_evm(c, pid, asof)
    proj = get(c, "projects", pid)
    dims = {}
    # schedule
    reasons, level = [], "ok"
    delayed = [x for x in sched["activities"] if (x["delay_days"] or 0) > 0]
    if sched["spi"] is not None and sched["spi"] < 0.95:
        level = "critical" if sched["spi"] < 0.85 else "attention"
        reasons.append("Progress %.1f%% against %.1f%% planned (SPI %.2f)." % (sched["actual_pct"],
                                                                               sched["planned_pct"], sched["spi"]))
    if delayed:
        level = "critical" if any(x["critical"] for x in delayed) or level == "critical" else "attention"
        reasons.append("%d activities forecast late, worst %s by %d days." % (
            len(delayed), max(delayed, key=lambda x: x["delay_days"])["name"], max(x["delay_days"] for x in delayed)))
    if sched["forecast_finish"] and proj["end_date"] and sched["forecast_finish"] > proj["end_date"]:
        level = "critical"
        reasons.append("Forecast finish %s is after contract completion %s." % (sched["forecast_finish"],
                                                                                proj["end_date"]))
    dims["schedule"] = {"level": level, "reasons": reasons or ["On programme."]}
    # cost
    reasons, level = [], "ok"
    if ev["cpi"] is not None and ev["cpi"] < 0.95:
        level = "critical" if ev["cpi"] < 0.85 else "attention"
        reasons.append("CPI %.2f: work done is costing more than budgeted." % ev["cpi"])
    over = [r for r in ev["rows"] if r["actual_unit_cost"] and r["unit_budget"]
            and r["actual_unit_cost"] > r["unit_budget"] * 1.05]
    if over:
        level = level if level == "critical" else "attention"
        reasons.append("%d BOQ items above budget unit cost (e.g. %s: %s vs %s)." % (
            len(over), over[0]["code"], over[0]["actual_unit_cost"], over[0]["unit_budget"]))
    if ev["margin_fade"] is not None and ev["margin_fade"] > 2:
        level = "critical" if ev["margin_fade"] > 5 else ("attention" if level == "ok" else level)
        reasons.append("Forecast margin %.1f%% vs tender %.1f%% (fade %.1f points)." % (
            ev["forecast_margin"], ev["tender_margin"], ev["margin_fade"]))
    if ev["items_without_budget"]:
        reasons.append("%d BOQ items have no rate analysis, so their cost cannot be judged."
                       % ev["items_without_budget"])
        level = "attention" if level == "ok" else level
    dims["cost"] = {"level": level, "reasons": reasons or ["Within budget."]}
    # quality
    failed = val(c, "SELECT COUNT(*) FROM qa_tests WHERE project_id=? AND status='failed'", (pid,))
    pending = val(c, "SELECT COUNT(*) FROM qa_tests WHERE project_id=? AND status='pending'", (pid,))
    ncr = val(c, "SELECT COUNT(*) FROM ncrs WHERE project_id=? AND status='open'", (pid,))
    holds = [x["name"] for x in sched["activities"] if x["qa_hold"]]
    reasons = []
    if ncr:
        reasons.append("%d open NCRs." % ncr)
    if holds:
        reasons.append("QA hold on %s (work done, tests pending or failed)." % ", ".join(holds[:3]))
    if pending:
        reasons.append("%d tests awaiting results." % pending)
    dims["quality"] = {"level": "critical" if ncr else ("attention" if holds or pending else "ok"),
                       "reasons": reasons or ["No open quality issues."], "failed": failed, "pending": pending,
                       "ncr": ncr}
    # resources
    risks = [m for m in material_risks(c, pid) if m["risk"]]
    down = q(c, "SELECT code, name FROM equipment WHERE project_id=? AND status IN ('breakdown','under_maintenance')",
             (pid,))
    reasons = ["MATERIAL SHORTAGE RISK: %s. %s" % (m["name"], m["why"]) for m in risks[:4]]
    if down:
        reasons.append("Machines down: %s." % ", ".join(d["code"] for d in down))
    dims["resources"] = {"level": "critical" if risks else ("attention" if down else "ok"),
                         "reasons": reasons or ["No shortages or breakdowns."]}
    # commercial
    soon = (date.today() + timedelta(days=7)).isoformat()
    notices = q(c, "SELECT no, title, notice_deadline FROM events WHERE project_id=? AND status IN ('open') AND "
                   "notice_deadline IS NOT NULL AND notice_deadline<>'' AND notice_deadline<=?", (pid, soon))
    unbilled = sum(r["unbilled_measured"] * r["revised_rate"] for r in ev["rows"] if r["unbilled_measured"] > EPS)
    vpending = val(c, "SELECT COUNT(*) FROM variations WHERE project_id=? AND status='submitted'", (pid,))
    reasons = ["Notice for %s due %s." % (n["title"], n["notice_deadline"]) for n in notices]
    if unbilled > 0:
        reasons.append("Measured work worth %s is not yet in an IPC (billing opportunity)." % r2(unbilled))
    if vpending:
        reasons.append("%d variations waiting for decision." % vpending)
    dims["commercial"] = {"level": "critical" if any(n["notice_deadline"] < today() for n in notices)
                          else ("attention" if reasons else "ok"), "reasons": reasons or ["Nothing pending."]}
    return dims, sched, ev


@api("control.room", "project", "view")
def control_room(c, u, a):
    pid = a["project_id"]
    asof = a.get("as_of") or today()
    dims, sched, ev = health(c, pid, asof)
    proj = get(c, "projects", pid)
    inv_rows = q(c, "SELECT id, payable FROM invoices WHERE project_id=? AND kind='sales' AND status='posted'", (pid,))
    paid = sum(invoice_paid(c, r["id"]) for r in inv_rows)
    billing = {
        "executed": ev["earned_revenue"],
        "measured": r2(sum(r["measured_qty"] * r["revised_rate"] for r in ev["rows"])),
        "billed": r2(sum(r["billed_qty"] * r["revised_rate"] for r in ev["rows"])),
        "certified": r2(sum(r["certified_qty"] * r["revised_rate"] for r in ev["rows"])),
        "received": r2(paid), "receivable": r2(sum(r["payable"] for r in inv_rows) - paid)}
    days_el = days_rem = None
    if proj["start_date"]:
        days_el = (date.fromisoformat(asof) - date.fromisoformat(proj["start_date"])).days
    if proj["end_date"]:
        days_rem = (date.fromisoformat(proj["end_date"]) - date.fromisoformat(asof)).days
    since = (date.fromisoformat(asof) - timedelta(days=6)).isoformat()
    resources = {
        "manpower_today": r2(val(c, "SELECT SUM(l.count) FROM dpr_labour l JOIN dpr d ON d.id=l.dpr_id WHERE "
                                    "d.project_id=? AND d.date=?", (pid, asof))),
        "manhours_week": r2(val(c, "SELECT SUM(l.count*(l.hours+l.ot_hours)) FROM dpr_labour l JOIN dpr d ON "
                                   "d.id=l.dpr_id WHERE d.project_id=? AND d.date BETWEEN ? AND ?",
                                (pid, since, asof))),
        "equipment_on_site": val(c, "SELECT COUNT(*) FROM equipment WHERE project_id=? AND active=1", (pid,)),
        "equipment_hours_week": r2(val(c, "SELECT SUM(hours) FROM logsheets WHERE project_id=? AND date BETWEEN ? AND ?",
                                       (pid, since, asof))),
        "shortages": [m for m in material_risks(c, pid) if m["risk"]]}
    commercial = {
        "variations": q1(c, "SELECT COUNT(*) n, SUM(CASE WHEN status='approved' THEN 1 ELSE 0 END) approved, "
                            "SUM(CASE WHEN status='submitted' THEN 1 ELSE 0 END) pending FROM variations "
                            "WHERE project_id=?", (pid,)),
        "events_open": val(c, "SELECT COUNT(*) FROM events WHERE project_id=? AND status NOT IN ('closed','rejected')",
                           (pid,)),
        "eot_days": r2(val(c, "SELECT SUM(delay_days) FROM events WHERE project_id=? AND status NOT IN ('rejected')",
                           (pid,))),
        "claim_value": r2(val(c, "SELECT SUM(cost_impact) FROM events WHERE project_id=? AND "
                                 "status NOT IN ('rejected')", (pid,)))}
    return {"project": proj, "as_of": asof, "health": dims,
            "progress": {"planned_pct": sched["planned_pct"], "actual_pct": sched["actual_pct"],
                         "variance": round(sched["actual_pct"] - sched["planned_pct"], 1), "spi": sched["spi"],
                         "forecast_finish": sched["forecast_finish"], "days_elapsed": days_el,
                         "days_remaining": days_rem, "value_pct": ev["progress_value_pct"]},
            "cost": {k: ev[k] for k in ("bac", "ac", "committed", "ev", "pv", "cpi", "cv", "eac", "etc",
                                        "forecast_profit", "tender_margin", "current_margin", "forecast_margin",
                                        "margin_fade", "contract_revenue", "forecast_revenue", "ac_unallocated")},
            "billing": billing, "resources": resources, "commercial": commercial,
            "critical": [x for x in sched["activities"] if x["critical"] or (x["delay_days"] or 0) > 0][:12],
            "milestones": [x for x in sched["activities"] if x["is_milestone"]][:10],
            "attention": action_items(c, u, pid)[:15]}


def action_items(c, u, pid=None):
    t = today()
    soon = (date.today() + timedelta(days=7)).isoformat()
    items = []
    pc = " AND project_id=%d" % int(pid) if pid else ""

    def add(cat, title, why, link, project_id=None, due=None):
        items.append({"category": cat, "title": title, "why": why, "link": link, "project_id": project_id, "due": due})
    for d in q(c, "SELECT * FROM dpr WHERE status IN ('submitted','checked')" + pc):
        add("approval", "DPR %s %s" % (d["no"], d["status"]), "Waiting to be %s." %
            ("checked" if d["status"] == "submitted" else "approved"), "#/p/dpr?id=%d" % d["id"], d["project_id"],
            d["date"])
    for i in q(c, "SELECT * FROM ipc WHERE status='submitted'" + pc):
        add("approval", "IPC %s awaiting certification" % i["no"], "Gross %s submitted." % i["gross"],
            "#/p/ipc?id=%d" % i["id"], i["project_id"], i["date"])
    for v in q(c, "SELECT * FROM variations WHERE status='submitted'" + pc):
        add("approval", "Variation %s" % v["no"], v["title"], "#/p/variations", v["project_id"])
    for m in q(c, "SELECT * FROM measurements WHERE status='draft'" + pc):
        add("approval", "Measurement %s to verify" % m["no"], "Draft measurement sheet.", "#/p/measure",
            m["project_id"])
    try:
        for x in dash_approvals(c, u, {}):
            if not pid or str(x.get("project_id")) == str(pid) or x.get("project_id") is None:
                add("approval", "%s %s" % (x["label"], x["no"] or ""), "Waiting for approval.", "#/approvals",
                    x.get("project_id"), x.get("date"))
    except ApiError:
        pass
    for tk in q(c, "SELECT * FROM tasks WHERE status='open'" + pc):
        cat = "overdue" if tk["due_date"] and tk["due_date"] < t else ("today" if tk["due_date"] == t else "upcoming")
        if tk["priority"] == "high" and cat != "upcoming":
            cat = "critical"
        add(cat, tk["title"], tk["description"] or "Task", "#/p/tasks", tk["project_id"], tk["due_date"])
    for p in q(c, "SELECT id, code FROM projects WHERE status='active'" + (" AND id=%d" % int(pid) if pid else "")):
        if not q1(c, "SELECT id FROM dpr WHERE project_id=? AND date=?", (p["id"], t)):
            add("today", "DPR not started for %s" % p["code"], "No daily report for today yet.", "#/p/dpr", p["id"], t)
        for m in material_risks(c, p["id"]):
            if m["risk"]:
                add("critical", "Material shortage risk: %s (%s)" % (m["name"], p["code"]), m["why"], "#/proc/pr",
                    p["id"])
        for x in q(c, "SELECT a.* FROM activities a WHERE a.project_id=? AND a.planned_finish<? AND "
                      "a.actual_finish IS NULL AND a.planned_qty>0", (p["id"], t)):
            add("critical" if x["critical"] else "overdue", "Activity late: %s" % x["name"],
                "Planned finish %s passed; %s of %s %s done." % (x["planned_finish"], r4(x["actual_qty"]),
                                                                x["planned_qty"], x["unit"] or ""),
                "#/p/schedule", p["id"], x["planned_finish"])
    for e in q(c, "SELECT * FROM events WHERE status='open' AND notice_deadline IS NOT NULL AND notice_deadline<>'' "
                  "AND notice_deadline<=?" + pc, (soon,)):
        add("critical" if e["notice_deadline"] <= t else "upcoming", "Notice deadline: %s" % e["title"],
            "Contract notice due %s%s." % (e["notice_deadline"], (" under clause " + e["clause"]) if e["clause"] else ""),
            "#/p/events", e["project_id"], e["notice_deadline"])
    for n in q(c, "SELECT * FROM ncrs WHERE status='open'" + pc):
        add("critical" if n["due_date"] and n["due_date"] < t else "info", "NCR %s open" % n["no"], n["title"],
            "#/p/quality", n["project_id"], n["due_date"])
    for eq in q(c, "SELECT * FROM equipment WHERE status IN ('breakdown','under_maintenance')" + pc):
        add("critical", "Equipment down: %s" % eq["code"], "Status is %s." % eq["status"].replace("_", " "),
            "#/eq/wo", eq["project_id"])
    for m in maint_status(c, u, {}):
        if m["state"] in ("overdue", "never done"):
            add("overdue", "Service overdue: %s" % m["title"], "Equipment %s." % m["equipment_id"], "#/eq/maint")
    for r in q(c, "SELECT i.*, p.name pname FROM invoices i JOIN parties p ON p.id=i.party_id WHERE i.status='posted' "
                  "AND i.due_date<?" + (" AND i.project_id=%d" % int(pid) if pid else ""), (t,)):
        bal = r2(r["payable"] - invoice_paid(c, r["id"]))
        if bal > 0.004:
            add("overdue", ("Receivable overdue: " if r["kind"] == "sales" else "Payment overdue: ") + r["pname"],
                "%s balance %s was due %s." % (r["no"], bal, r["due_date"]), "#/acc/ageing", r["project_id"],
                r["due_date"])
    order = {"critical": 0, "overdue": 1, "today": 2, "approval": 3, "upcoming": 4, "info": 5}
    items.sort(key=lambda x: (order[x["category"]], x["due"] or "9999"))
    return items


@api("action.centre")
def action_centre(c, u, a):
    return action_items(c, u, a.get("project_id"))


@api("action.generate_tasks", "project", "edit")
def action_generate(c, u, a):
    n = 0
    for it in action_items(c, u, a.get("project_id")):
        if it["category"] == "critical" and it["project_id"] and not it["link"].endswith("tasks"):
            if auto_task(c, u, it["project_id"], it["title"], "action", abs(hash(it["title"])) % 10 ** 9,
                         priority="high", description=it["why"]):
                n += 1
    return {"created": n}


@api("portfolio")
def portfolio(c, u, a):
    out = []
    for p in q(c, "SELECT * FROM projects ORDER BY status, code"):
        dims, sched, ev = health(c, p["id"], today())
        recv = sum(r["payable"] - invoice_paid(c, r["id"]) for r in
                   q(c, "SELECT id, payable FROM invoices WHERE project_id=? AND kind='sales' AND status='posted'",
                     (p["id"],)))
        out.append({"id": p["id"], "code": p["code"], "name": p["name"], "status": p["status"],
                    "contract_value": p["contract_value"], "planned_pct": sched["planned_pct"],
                    "actual_pct": sched["actual_pct"], "spi": sched["spi"], "cpi": ev["cpi"],
                    "earned": ev["earned_revenue"], "cost": ev["ac"], "eac": ev["eac"],
                    "forecast_profit": ev["forecast_profit"], "forecast_margin": ev["forecast_margin"],
                    "receivable": r2(recv),
                    "health": {k: v["level"] for k, v in dims.items()},
                    "risks": [r for v in dims.values() if v["level"] != "ok" for r in v["reasons"]][:4]})
    return out


@api("today.view", "project", "view")
def today_view(c, u, a):
    pid, t = a["project_id"], a.get("date") or today()
    d = q1(c, "SELECT * FROM dpr WHERE project_id=? AND date=? ORDER BY id LIMIT 1", (pid, t))
    planned = dpr_prefill(c, u, {"project_id": pid, "date": t})["work"]
    acts = {x["id"]: x for x in q(c, "SELECT id, name, unit, code FROM activities WHERE project_id=?", (pid,))}
    return {"date": t, "dpr": d,
            "planned": [dict(w, name=(acts.get(w["activity_id"]) or {}).get("name"),
                             unit=(acts.get(w["activity_id"]) or {}).get("unit")) for w in planned],
            "materials": dpr_materials(c, pid, t),
            "logs": q(c, "SELECT * FROM logsheets WHERE project_id=? AND date=?", (pid, t)),
            "photos": q(c, "SELECT * FROM files WHERE project_id=? AND date=? AND kind='photo'", (pid, t)),
            "tasks": q(c, "SELECT * FROM tasks WHERE status='open' AND (project_id=? OR project_id IS NULL) AND "
                          "(due_date IS NULL OR due_date<=?) ORDER BY due_date", (pid, t)),
            "events": q(c, "SELECT * FROM events WHERE project_id=? AND date=?", (pid, t)),
            "down": q(c, "SELECT id, code, name, status FROM equipment WHERE project_id=? AND status IN "
                         "('breakdown','under_maintenance')", (pid,))}


# ───────────────────────── universal search ─────────────────────────
# One box that reaches every module. Each entry says what to look in, what to call it,
# what to show underneath, and where clicking it goes. A person only sees the groups
# their role may view, and a search never shows a record they could not open anyway.
def S(group, module, table, label, where, link, sub="''", pid="project_id", dt="NULL", num=None, extra=""):
    return {"group": group, "module": module, "table": table, "label": label, "where": where, "link": link,
            "sub": sub, "pid": pid, "dt": dt, "num": num, "extra": extra}


SEARCH = [
    # master data
    S("Projects", "masters", "projects", "code||' '||name", ["code", "name", "client", "location"],
      "#/p/control?project={id}", "COALESCE(client,'')||' · '||COALESCE(status,'')", "id", "start_date",
      "contract_value"),
    S("Materials", "masters", "materials", "code||' '||name", ["code", "name", "local_name", "category", "spec"],
      "#/inv/card?material={id}", "COALESCE(category,'')||' · '||COALESCE(unit,'')", "NULL", "NULL",
      "standard_rate"),
    S("Vendors & clients", "masters", "parties", "code||' '||name", ["code", "name", "pan", "phone", "email",
                                                                     "address", "categories"],
      "#/acc/party?party={id}", "COALESCE(kind,'')||COALESCE(' · PAN '||pan,'')", "NULL"),
    S("Staff", "masters", "staff", "code||' '||name", ["code", "name", "designation", "phone"], "#/m/staff",
      "COALESCE(designation,'')"),
    S("BOQ items", "masters", "boq_items", "code||' '||description", ["code", "description", "location"],
      "#/p/boq", "COALESCE(unit,'')||' @ '||COALESCE(rate,0)", "project_id", "NULL", "rate"),
    S("Stores", "inventory", "stores", "code||' '||name", ["code", "name", "keeper"], "#/inv/stock",
      "COALESCE(type,'')||COALESCE(' · '||keeper,'')"),
    S("Ledger accounts", "accounts", "accounts", "code||' '||name", ["code", "name", "bank_name", "bank_acno"],
      "#/acc/ledger?account={id}", "COALESCE(type,'')||COALESCE(' · '||role,'')", "NULL"),
    S("Labour trades", "masters", "trades", "code||' '||name", ["code", "name"], "#/m/trades",
      "'per hour '||COALESCE(rate_hour,0)"),
    S("Daily check lists", "masters", "check_lists", "code||' '||name", ["code", "name", "category", "items"],
      "#/m/checklists", "COALESCE(category,'')", "NULL"),
    S("TDS sections", "accounts", "tds_rates", "section||' '||description", ["section", "description"],
      "#/acc/tds", "rate||'%'", "NULL"),
    # store
    S("Requisitions", "inventory", "mrq", "no", ["no", "requested_by", "remarks",
       "@EXISTS(SELECT 1 FROM mrq_lines l JOIN materials m ON m.id=l.material_id WHERE l.mrq_id=mrq.id AND (COALESCE(m.name,'') LIKE ? OR COALESCE(m.code,'') LIKE ?))"], "#/inv/mrq?id={id}",
      "COALESCE(requested_by,'')||' · '||COALESCE(status,'')", "project_id", "date"),
    S("Goods received", "inventory", "grn", "no", ["no", "challan_no", "vehicle_no", "remarks",
       "@EXISTS(SELECT 1 FROM grn_lines l JOIN materials m ON m.id=l.material_id WHERE l.grn_id=grn.id AND (COALESCE(m.name,'') LIKE ? OR COALESCE(m.code,'') LIKE ?))"],
      "#/inv/grn?id={id}", "COALESCE('challan '||challan_no,'')||' · '||COALESCE(status,'')", "project_id", "date"),
    S("Material issues", "inventory", "issues", "no", ["no", "issued_to", "remarks",
       "@EXISTS(SELECT 1 FROM issue_lines l JOIN materials m ON m.id=l.material_id WHERE l.issue_id=issues.id AND (COALESCE(m.name,'') LIKE ? OR COALESCE(m.code,'') LIKE ?))"], "#/inv/issue?id={id}",
      "COALESCE(issued_to,'')||' · '||COALESCE(status,'')", "project_id", "date"),
    S("Material returns", "inventory", "returns", "no", ["no", "returned_by", "remarks"], "#/inv/return?id={id}",
      "COALESCE(returned_by,'')||' · '||COALESCE(status,'')", "project_id", "date"),
    S("Transfers", "inventory", "transfers", "no", ["no", "vehicle_no", "remarks"], "#/inv/transfer?id={id}",
      "COALESCE(status,'')", "from_project", "date"),
    S("Stock counts", "inventory", "stock_counts", "no", ["no", "remarks"], "#/inv/count?id={id}",
      "COALESCE(status,'')", "project_id", "date"),
    # buying
    S("Purchase requests", "procurement", "pr", "no", ["no", "remarks", "source"], "#/proc/pr?id={id}",
      "COALESCE(priority,'')||' · '||COALESCE(status,'')", "project_id", "date"),
    S("Comparative statements", "procurement", "cs", "no", ["no", "reason", "remarks"], "#/proc/cs?id={id}",
      "COALESCE(status,'')", "project_id", "date"),
    S("Purchase orders", "procurement", "po", "no", ["no", "remarks", "terms", "payment_terms",
       "@EXISTS(SELECT 1 FROM po_lines l JOIN materials m ON m.id=l.material_id WHERE l.po_id=po.id AND (COALESCE(m.name,'') LIKE ? OR COALESCE(m.code,'') LIKE ?))"],
      "#/proc/po?id={id}", "COALESCE(status,'')", "project_id", "date", "total"),
    S("Bills & invoices", "procurement", "invoices", "COALESCE(no,'draft')||' '||COALESCE(party_inv_no,'')",
      ["no", "party_inv_no", "remarks",
       "@EXISTS(SELECT 1 FROM invoice_lines l WHERE l.invoice_id=invoices.id AND COALESCE(l.description,'') LIKE ?)"],
      "#/proc/invoices?id={id}",
      "COALESCE(kind,'')||' · '||COALESCE(status,'')", "project_id", "date", "total"),
    # money
    # a voucher is found by its own number or narration, and by anything written on its lines
    S("Vouchers", "accounts", "vouchers", "no||' '||type",
      ["no", "narration", "ref_no",
       "@EXISTS(SELECT 1 FROM voucher_lines l WHERE l.voucher_id=vouchers.id AND COALESCE(l.narration,'') LIKE ?)"],
      "#/acc/voucher?id={id}", "COALESCE(narration,'')", "project_id", "date", "total"),
    S("Payments & receipts", "accounts", "payments", "no", ["no", "cheque_no", "remarks", "mode"],
      "#/acc/payments?id={id}", "COALESCE(kind,'')||' · '||COALESCE(mode,'')", "project_id", "date", "net"),
    S("Budgets", "accounts", "budgets", "COALESCE(remarks,'budget line')", ["remarks"], "#/acc/budget",
      "''", "project_id", "NULL", "amount"),
    # machines
    S("Equipment", "equipment", "equipment", "code||' '||name",
      ["code", "name", "category", "make", "model", "serial", "reg_no", "operator", "owner_name", "notes"],
      "#/eq/passport?id={id}", "COALESCE(reg_no,'')||' · '||COALESCE(status,'')"),
    S("Monthly logsheets", "equipment", "logbooks", "no||' '||COALESCE(period_label,period)",
      ["no", "period", "period_label", "operator", "site", "location", "owner_name", "hirer_name", "remarks",
       "issues", "cost_code"],
      "#/eq/book?id={id}", "COALESCE(sheet_type,'')||' · '||COALESCE(status,'')", "project_id", "from_date"),
    S("Logsheet days", "equipment", "logsheets", "date||' '||COALESCE(work,'')",
      ["work", "operator", "down_reason", "cost_code", "fuel_req_no"], "#/eq/book?id={book_id}",
      "COALESCE(shift,'')||' · '||COALESCE(hours,0)||' h'", "project_id", "date"),
    S("Work orders", "equipment", "work_orders", "no||' '||COALESCE(description,'')",
      ["no", "description", "action_taken", "technician"], "#/eq/wo?id={id}",
      "COALESCE(type,'')||' · '||COALESCE(status,'')", "project_id", "reported_at"),
    S("Maintenance plans", "equipment", "maint_plans", "title", ["title", "checklist"], "#/eq/maint",
      "'every '||COALESCE(interval,0)||' '||COALESCE(interval_type,'')", "NULL"),
    S("Hire agreements", "equipment", "hire_agreements", "COALESCE(remarks,'hire agreement')", ["remarks", "unit"],
      "#/eq/hire", "'per '||COALESCE(unit,'')", "project_id", "start_date", "rate"),
    # site
    S("Daily progress reports", "project", "dpr", "no||' '||date", ["no", "remarks", "weather", "site_condition"],
      "#/p/dpr?id={id}", "COALESCE(shift,'')||' · '||COALESCE(status,'')", "project_id", "date"),
    S("Activities", "project", "activities", "COALESCE(code,'')||' '||name", ["code", "name", "location",
                                                                              "responsible"],
      "#/p/schedule", "COALESCE(unit,'')||COALESCE(' · '||responsible,'')", "project_id", "planned_start"),
    S("Work breakdown", "project", "wbs", "code||' '||name", ["code", "name"], "#/p/wbs", "''"),
    S("Tasks", "project", "tasks", "title", ["title", "description", "assigned_to"], "#/p/tasks",
      "COALESCE(assigned_to,'')||' · '||COALESCE(status,'')", "project_id", "due_date"),
    S("Events & claims", "project", "events", "no||' '||title", ["no", "title", "description", "clause",
                                                                 "responsible_party", "mitigation"],
      "#/p/events?id={id}", "COALESCE(type,'')||' · '||COALESCE(status,'')", "project_id", "date", "cost_impact"),
    S("Photos & documents", "project", "files", "filename||' '||COALESCE(caption,'')",
      ["filename", "caption", "location", "stage"], "#/p/docs", "COALESCE(kind,'')", "project_id", "date"),
    # commercial
    S("Measurements", "commercial", "measurements", "no", ["no", "remarks", "verified_by"], "#/p/measure?id={id}",
      "COALESCE(status,'')", "project_id", "date"),
    S("Payment certificates", "commercial", "ipc", "no", ["no", "client_ref", "remarks"], "#/p/ipc?id={id}",
      "COALESCE(status,'')", "project_id", "date", "net"),
    S("Variations", "commercial", "variations", "no||' '||title", ["no", "title", "reason", "instruction_ref",
                                                                   "new_description"],
      "#/p/variations?id={id}", "COALESCE(status,'')", "project_id", "date", "new_rate"),
    # quality
    S("Tests", "quality", "qa_tests", "no||' '||test_type", ["no", "test_type", "sample_ref", "location",
                                                             "criteria", "remarks", "result_value"],
      "#/p/quality?id={id}", "COALESCE(status,'')||COALESCE(' · '||result_value,'')", "project_id",
      "sampled_date"),
    S("Non-conformances", "quality", "ncrs", "no||' '||title", ["no", "title", "description", "corrective_action"],
      "#/p/quality", "COALESCE(status,'')", "project_id", "date"),
    # plant and assets
    S("Plants", "plant", "plants", "code||' '||name", ["code", "name", "location", "operator", "notes"],
      "#/pl/register", "COALESCE(kind,'')||COALESCE(' · '||location,'')"),
    S("Mix designs", "plant", "mix_designs", "code||' '||name", ["code", "name", "grade", "remarks"], "#/pl/mix",
      "COALESCE(grade,'')", "NULL"),
    S("Production runs", "plant", "plant_runs", "no", ["no", "remarks", "operator", "down_reason"],
      "#/pl/runs?id={id}", "COALESCE(status,'')||' · '||COALESCE(output_qty,0)", "project_id", "date",
      "total_cost"),
    S("Assets", "assets", "assets", "code||' '||name", ["code", "name", "category", "serial", "custodian",
                                                        "location", "invoice_no", "insurance_policy", "remarks"],
      "#/as/register?id={id}", "COALESCE(class,'')||COALESCE(' · '||custodian,'')", "project_id",
      "purchase_date", "book_value"),
    # people
    S("Users", "admin", "users", "username||' '||name", ["username", "name", "phone", "email", "location"],
      "#/admin/users", "COALESCE(role,'')||COALESCE(' · '||location,'')", "NULL"),
]
SEARCH_BY_GROUP = {e["group"]: e for e in SEARCH}


def _search_one(c, u, e, term, limit):
    if not can(u, e["module"], "view"):
        return []
    like = "%" + term + "%"
    # a column name, or "@" and a ready-made SQL test (to reach the lines inside a document)
    parts, args = [], []
    for col in e["where"]:
        if col.startswith("@"):
            parts.append(col[1:])
            args += [like] * col.count("?")
        else:
            parts.append("COALESCE(%s,'') LIKE ?" % col)
            args.append(like)
    where = " OR ".join(parts)
    # a number typed on its own also matches amounts, so "38400" finds the bill it is on
    if e["num"]:
        try:
            n = float(term.replace(",", ""))
            where += " OR ABS(%s - ?) < 0.5" % e["num"]
            args.append(n)
        except ValueError:
            pass
    cols = [r[1] for r in c.execute("PRAGMA table_info(%s)" % e["table"])]
    # a link may point at a parent record (a narration opens its voucher, a day opens its sheet)
    needed = [k for k in ("voucher_id", "book_id") if "{%s}" % k in e["link"] and k in cols]
    sql = ("SELECT id, (%s) label, (%s) sub, (%s) project_id, (%s) dt%s FROM %s WHERE (%s)"
           % (e["label"], e["sub"], e["pid"], e["dt"],
              "".join(", " + k for k in needed), e["table"], where))
    if "active" in cols:
        sql += " AND COALESCE(active,1)=1"
    sql += " ORDER BY dt DESC, id DESC LIMIT %d" % limit
    try:
        rows = q(c, sql, args)
    except Exception:
        return []
    out = []
    for r in rows:
        link = e["link"].replace("{id}", str(r["id"]))
        for key in ("voucher_id", "book_id"):
            if "{%s}" % key in link:
                v = r[key] if key in r.keys() else None
                if not v:
                    continue
                link = link.replace("{%s}" % key, str(v))
        if "{" in link:
            continue
        label = (r["label"] or "").strip() or ("#" + str(r["id"]))
        out.append({"group": e["group"], "module": e["module"], "label": label,
                    "sub": (r["sub"] or "").strip(" ·"), "date": r["dt"],
                    "project_id": r["project_id"], "id": r["id"], "link": link})
    return out


@api("search")
def search(c, u, a):
    """One box for the whole system. Pass a group to see everything inside it."""
    term = (a.get("q") or "").strip()
    if len(term) < 2:
        return {"q": term, "rows": [], "counts": {}, "groups": []} if a.get("full") else []
    want = a.get("group")
    per = int(a.get("limit") or (40 if a.get("full") else 6))
    pid = a.get("project_id")
    entries = [SEARCH_BY_GROUP[want]] if want in SEARCH_BY_GROUP else SEARCH
    rows, counts = [], {}
    for e in entries:
        hits = _search_one(c, u, e, term, per if len(entries) > 1 else per * 5)
        if pid:
            here = [x for x in hits if x["project_id"] in (None, int(pid))]
            hits = here or hits
        if hits:
            counts[e["group"]] = len(hits)
            rows.extend(hits)
    if not a.get("full"):
        return rows
    return {"q": term, "rows": rows, "counts": counts,
            "groups": [e["group"] for e in SEARCH if can(u, e["module"], "view")]}
