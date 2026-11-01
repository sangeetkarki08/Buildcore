"""Equipment management, reports, dashboard and administration."""
from datetime import date, datetime, timedelta

from core import (ApiError, EPS, ROLES, audit, backup_now, can, fsetting, get, hash_pw, ins, month_end, need,
                  next_no, now, num, post_voucher, q, q1, r2, r4, require, setting, today, upd, val)
from api_inventory import api, auto_reorder, load_doc, invoice_paid
from api_finance import budget_check

POSTED = "v.status IN ('posted','reversed')"
EQ_STATUS = ("working", "idle", "breakdown", "under_maintenance", "in_transit", "standby", "disposed")


# ───────────────────────── equipment: status & deployment ─────────────────────────
def set_status(c, u, eq_id, status, reason=""):
    if status not in EQ_STATUS:
        raise ApiError("Unknown equipment status.")
    eq = get(c, "equipment", eq_id, "Equipment")
    if eq["status"] == status:
        return
    ts = now()
    c.execute("UPDATE equipment_status_log SET to_ts=? WHERE equipment_id=? AND to_ts IS NULL", (ts, eq_id))
    ins(c, "equipment_status_log", {"equipment_id": eq_id, "status": status, "from_ts": ts, "reason": reason,
                                    "user_id": u["id"] if u else None})
    upd(c, "equipment", eq_id, {"status": status})


@api("eq.status", "equipment", "edit")
def eq_status(c, u, a):
    set_status(c, u, int(a["id"]), a.get("status"), a.get("reason") or "")
    return True


@api("eq.status_log", "equipment", "view")
def eq_status_log(c, u, a):
    return q(c, "SELECT * FROM equipment_status_log WHERE equipment_id=? ORDER BY id DESC", (a["id"],))


@api("eq.deploy", "equipment", "edit")
def eq_deploy(c, u, a):
    need(a, "equipment_id", "project_id", "date")
    eq = get(c, "equipment", int(a["equipment_id"]), "Equipment")
    last = q1(c, "SELECT * FROM deployments WHERE equipment_id=? AND demob_date IS NULL", (eq["id"],))
    if last:
        if last["project_id"] == int(a["project_id"]):
            raise ApiError("The equipment is already deployed on this project.")
        if a["date"] < last["mob_date"]:
            raise ApiError("Date is before the current deployment started.")
        upd(c, "deployments", last["id"], {"demob_date": a["date"]})
    ins(c, "deployments", {"equipment_id": eq["id"], "project_id": int(a["project_id"]), "mob_date": a["date"],
                           "meter": num(a.get("meter")) or eq["meter"], "remarks": a.get("remarks")})
    upd(c, "equipment", eq["id"], {"project_id": int(a["project_id"])})
    audit(c, u, "deploy", "equipment", eq["id"], a)
    return True


@api("eq.demobilise", "equipment", "edit")
def eq_demob(c, u, a):
    last = q1(c, "SELECT * FROM deployments WHERE equipment_id=? AND demob_date IS NULL", (a["equipment_id"],))
    if not last:
        raise ApiError("The equipment is not deployed.")
    upd(c, "deployments", last["id"], {"demob_date": a.get("date") or today()})
    upd(c, "equipment", int(a["equipment_id"]), {"project_id": None})
    return True


@api("eq.deployments", "equipment", "view")
def eq_deployments(c, u, a):
    return q(c, "SELECT * FROM deployments WHERE equipment_id=? ORDER BY mob_date DESC", (a["equipment_id"],))


# ───────────────────────── logsheets ─────────────────────────
def save_log(c, u, r):
    """One day of one machine. Used both by the day-by-day screen and by the monthly sheet."""
    need(r, "equipment_id", "project_id", "date")
    eq = get(c, "equipment", int(r["equipment_id"]), "Equipment")
    rid = r.get("id")
    if rid:
        old = get(c, "logsheets", int(rid), "Logsheet")
        if old["status"] != "draft":
            raise ApiError("Approved logsheets cannot be edited.")
    ms, me = num(r.get("meter_start")), num(r.get("meter_end"))
    shift = r.get("shift") or "day"
    if me or ms:
        if me < ms:
            raise ApiError("Closing meter must not be below opening meter.")
        prev = val(c, "SELECT MAX(meter_end) FROM logsheets WHERE equipment_id=? AND id<>? AND "
                      "(date<? OR (date=? AND shift<?))", (eq["id"], rid or 0, r["date"], r["date"], shift))
        if prev and ms + EPS < prev:
            raise ApiError("Opening meter %s is below the previous closing reading %s." % (ms, prev))
        nxt = val(c, "SELECT MIN(meter_start) FROM logsheets WHERE equipment_id=? AND id<>? AND "
                     "(date>? OR (date=? AND shift>?)) AND meter_start>0", (eq["id"], rid or 0, r["date"],
                                                                           r["date"], shift), None)
        if nxt is not None and me > nxt + EPS:
            raise ApiError("Closing meter %s is above a later opening reading %s." % (me, nxt))
    hours = r2(me - ms) if eq["meter_type"] == "hours" and (me or ms) else r2(num(r.get("hours")))
    sh = fsetting(c, "shift_hours") or 10
    idle, bd = r2(num(r.get("idle_hours"))), r2(num(r.get("breakdown_hours")))
    sby = r2(num(r.get("standby_hours")))
    if hours < 0 or hours + idle + bd + sby > 24:
        raise ApiError("Working, idle, standby and breakdown hours cannot exceed 24 in a shift.")
    dup = val(c, "SELECT COUNT(*) FROM logsheets WHERE equipment_id=? AND date=? AND shift=? AND id<>?",
              (eq["id"], r["date"], shift, rid or 0))
    if dup:
        raise ApiError("A logsheet for this machine, date and shift already exists.")
    ks, ke = num(r.get("km_start")), num(r.get("km_end"))
    if (eq["meter_type"] or "") == "km" and not (ks or ke):
        ks, ke = ms, me          # on an odometer machine the machine's own meter IS the kilometres
    if ks and ke and ke + EPS < ks:
        raise ApiError("Closing kilometres must not be below opening kilometres.")
    data = {"equipment_id": eq["id"], "project_id": int(r["project_id"]), "date": r["date"], "shift": shift,
            "operator": r.get("operator"), "meter_start": ms, "meter_end": me, "hours": hours,
            "idle_hours": idle, "breakdown_hours": bd, "standby_hours": sby,
            "boq_item_id": int(r["boq_item_id"]) if r.get("boq_item_id") else None, "work": r.get("work"),
            "trips": num(r.get("trips")),
            "book_id": int(r["book_id"]) if r.get("book_id") else None,
            "time_start": r.get("time_start"), "time_stop": r.get("time_stop"),
            "km_start": ks, "km_end": ke, "km_run": r2(ke - ks) if (ks and ke) else num(r.get("km_run")),
            "fuel_qty": num(r.get("fuel_qty")), "fuel_req_no": r.get("fuel_req_no"),
            "down_reason": r.get("down_reason"), "cost_code": r.get("cost_code"),
            "sign_store": r.get("sign_store"), "sign_operator": r.get("sign_operator"),
            "sign_incharge": r.get("sign_incharge"), "sign_hirer": r.get("sign_hirer")}
    if r.get("activity_id"):
        data["activity_id"] = int(r["activity_id"])
    if rid:
        upd(c, "logsheets", int(rid), data)
    else:
        data.update({"status": "draft", "created_by": u["id"]})
        rid = ins(c, "logsheets", data)
    if me > (eq["meter"] or 0):
        upd(c, "equipment", eq["id"], {"meter": me})
    return {"id": rid, "hours": hours, "warning": ("Hours exceed shift length of %s" % sh) if hours > sh else None}


@api("log.save", "equipment", "edit")
def log_save(c, u, a):
    return save_log(c, u, a.get("row") or {})


@api("log.list", "equipment", "view")
def log_list(c, u, a):
    cond, p = [], []
    for k in ("equipment_id", "project_id", "status"):
        if a.get(k):
            cond.append("%s=?" % k)
            p.append(a[k])
    if a.get("from"):
        cond.append("date>=?")
        p.append(a["from"])
    if a.get("to"):
        cond.append("date<=?")
        p.append(a["to"])
    return q(c, "SELECT * FROM logsheets%s ORDER BY date DESC, equipment_id LIMIT 1000" %
             (" WHERE " + " AND ".join(cond) if cond else ""), p)


@api("log.approve", "equipment", "approve")
def log_approve(c, u, a):
    for i in a.get("ids") or []:
        c.execute("UPDATE logsheets SET status='approved', approved_by=? WHERE id=? AND status='draft'", (u["id"], i))
    return True


@api("log.delete", "equipment", "edit")
def log_delete(c, u, a):
    l = get(c, "logsheets", a["id"], "Logsheet")
    if l["status"] != "draft":
        raise ApiError("Approved logsheets cannot be deleted.")
    c.execute("DELETE FROM log_meters WHERE log_id=?", (l["id"],))
    c.execute("DELETE FROM logsheets WHERE id=?", (l["id"],))
    return True


# ───────────────────────── maintenance & work orders ─────────────────────────
def plan_due(c, p):
    eq = get(c, "equipment", p["equipment_id"])
    out = {"plan_id": p["id"], "equipment_id": eq["id"], "title": p["title"], "interval_type": p["interval_type"],
           "interval": p["interval"], "meter": eq["meter"], "due": False, "state": "ok"}
    if p["interval_type"] == "days":
        base = date.fromisoformat(p["last_date"]) if p["last_date"] else None
        if not base:
            out.update(due=True, state="never done")
            return out
        due_d = base + timedelta(days=int(p["interval"]))
        left = (due_d - date.today()).days
        out.update(due_date=due_d.isoformat(), left=left, due=left <= 7,
                   state="overdue" if left < 0 else ("due soon" if left <= 7 else "ok"))
    else:
        due_m = (p["last_meter"] or 0) + p["interval"]
        left = due_m - (eq["meter"] or 0)
        out.update(due_meter=due_m, left=r2(left), due=left <= p["interval"] * 0.1,
                   state="overdue" if left < 0 else ("due soon" if left <= p["interval"] * 0.1 else "ok"))
    out["open_wo"] = val(c, "SELECT no FROM work_orders WHERE plan_id=? AND status IN ('open','in_progress')",
                         (p["id"],), None)
    return out


@api("maint.status", "equipment", "view")
def maint_status(c, u, a):
    plans = q(c, "SELECT * FROM maint_plans WHERE active=1" + (" AND equipment_id=?" if a.get("equipment_id") else ""),
              (a["equipment_id"],) if a.get("equipment_id") else ())
    rows = [plan_due(c, p) for p in plans]
    return sorted(rows, key=lambda r: (not r["due"], r.get("left") or 0))


@api("maint.create_wo", "equipment", "edit")
def maint_create_wo(c, u, a):
    p = get(c, "maint_plans", a["plan_id"], "Plan")
    if val(c, "SELECT COUNT(*) FROM work_orders WHERE plan_id=? AND status IN ('open','in_progress')", (p["id"],)):
        raise ApiError("An open work order already exists for this plan.")
    eq = get(c, "equipment", p["equipment_id"])
    no = next_no(c, "WO", today())
    wid = ins(c, "work_orders", {"no": no, "equipment_id": eq["id"], "project_id": eq["project_id"],
                                 "plan_id": p["id"], "type": "preventive", "status": "open", "reported_at": now(),
                                 "description": "%s\n%s" % (p["title"], p["checklist"] or ""),
                                 "created_by": u["id"]})
    return {"id": wid, "no": no}


@api("wo.save", "equipment", "edit")
def wo_save(c, u, a):
    r = a.get("row") or {}
    need(r, "equipment_id", "description")
    data = {"equipment_id": int(r["equipment_id"]), "project_id": int(r["project_id"]) if r.get("project_id") else None,
            "type": r.get("type") or "breakdown", "description": r["description"], "technician": r.get("technician")}
    if r.get("id"):
        wo = get(c, "work_orders", int(r["id"]))
        if wo["status"] in ("completed", "cancelled"):
            raise ApiError("Closed work orders cannot be edited.")
        upd(c, "work_orders", wo["id"], data)
        return {"id": wo["id"]}
    data.update({"no": next_no(c, "WO", today()), "status": "open", "reported_at": r.get("reported_at") or now(),
                 "created_by": u["id"]})
    wid = ins(c, "work_orders", data)
    if data["type"] == "breakdown":
        set_status(c, u, data["equipment_id"], "breakdown", "Work order " + data["no"])
    return {"id": wid, "no": data["no"]}


@api("wo.start", "equipment", "edit")
def wo_start(c, u, a):
    wo = get(c, "work_orders", a["id"], "Work order")
    if wo["status"] != "open":
        raise ApiError("Only open work orders can be started.")
    upd(c, "work_orders", wo["id"], {"status": "in_progress", "started_at": a.get("at") or now()})
    set_status(c, u, wo["equipment_id"], "under_maintenance", "Work order " + wo["no"])
    return True


def _dt(s):
    return datetime.fromisoformat(s[:19]) if len(s) > 10 else datetime.fromisoformat(s + "T00:00:00")


@api("wo.complete", "equipment", "edit")
def wo_complete(c, u, a):
    wo = get(c, "work_orders", a["id"], "Work order")
    if wo["status"] not in ("open", "in_progress"):
        raise ApiError("This work order is already closed.")
    done = a.get("at") or now()
    start = wo["reported_at"] if wo["type"] == "breakdown" else (wo["started_at"] or wo["reported_at"])
    hours = max(0, (_dt(done) - _dt(start)).total_seconds() / 3600)
    eq = get(c, "equipment", wo["equipment_id"])
    meter = num(a.get("meter")) or eq["meter"]
    upd(c, "work_orders", wo["id"], {"status": "completed", "completed_at": done, "downtime_hours": r2(hours),
                                     "action_taken": a.get("action_taken"), "meter": meter})
    if wo["plan_id"]:
        upd(c, "maint_plans", wo["plan_id"], {"last_date": done[:10], "last_meter": meter})
    set_status(c, u, wo["equipment_id"], "working", "Completed " + wo["no"])
    return True


@api("wo.cancel", "equipment", "approve")
def wo_cancel(c, u, a):
    wo = get(c, "work_orders", a["id"])
    if wo["status"] in ("completed", "cancelled"):
        raise ApiError("Already closed.")
    upd(c, "work_orders", wo["id"], {"status": "cancelled", "completed_at": now()})
    set_status(c, u, wo["equipment_id"], "working", "Cancelled " + wo["no"])
    return True


@api("wo.list", "equipment", "view")
def wo_list(c, u, a):
    cond, p = [], []
    for k in ("equipment_id", "project_id", "status"):
        if a.get(k):
            cond.append("%s=?" % k)
            p.append(a[k])
    rows = q(c, "SELECT * FROM work_orders%s ORDER BY id DESC LIMIT 500" %
             (" WHERE " + " AND ".join(cond) if cond else ""), p)
    for r in rows:
        r["spares_cost"] = r2(val(c, "SELECT SUM(l.amount) FROM issue_lines l JOIN issues i ON i.id=l.issue_id "
                                     "WHERE i.wo_id=? AND i.status='posted'", (r["id"],)))
    return rows


# ───────────────────────── hire, depreciation, internal billing ─────────────────────────
@api("hire.bill", "accounts", "edit")
def hire_bill(c, u, a):
    need(a, "agreement_id", "month")
    ag = get(c, "hire_agreements", int(a["agreement_id"]), "Hire agreement")
    m = a["month"]
    if q1(c, "SELECT id FROM hire_bills WHERE agreement_id=? AND month=?", (ag["id"], m)):
        raise ApiError("This month is already billed.")
    start, end = m + "-01", month_end(m)
    logs = q(c, "SELECT date, hours FROM logsheets WHERE equipment_id=? AND project_id=? AND date BETWEEN ? AND ?",
             (ag["equipment_id"], ag["project_id"], start, end))
    if ag["unit"] == "hour":
        units = sum(l["hours"] for l in logs)
    elif ag["unit"] == "day":
        units = len({l["date"] for l in logs if l["hours"] > 0})
    else:
        units = 1
    billed = max(units, ag["min_units"] or 0)
    first = not val(c, "SELECT COUNT(*) FROM hire_bills WHERE agreement_id=?", (ag["id"],))
    amount = r2(billed * ag["rate"])
    eq = get(c, "equipment", ag["equipment_id"])
    acc = val(c, "SELECT id FROM accounts WHERE role='hire_cost'")
    if not acc:
        raise ApiError("Set an account with role 'hire_cost'.")
    iid = ins(c, "invoices", {"kind": "purchase", "party_id": ag["vendor_id"], "project_id": ag["project_id"],
                              "date": end, "party_inv_no": a.get("party_inv_no"), "status": "draft",
                              "source": "hire", "remarks": "Hire of %s for %s" % (eq["name"], m),
                              "created_by": u["id"]})
    ins(c, "invoice_lines", {"invoice_id": iid, "description": "%s %s: %s %s (logged %s)" %
                             (eq["code"], m, r2(billed), ag["unit"], r2(units)), "qty": r2(billed),
                             "rate": ag["rate"], "vat_rate": ag["vat_rate"] or 0, "amount": amount,
                             "account_id": acc, "equipment_id": eq["id"]})
    if first and ag["mob_cost"]:
        ins(c, "invoice_lines", {"invoice_id": iid, "description": "Mobilisation %s" % eq["code"], "qty": 1,
                                 "rate": ag["mob_cost"], "vat_rate": ag["vat_rate"] or 0, "amount": ag["mob_cost"],
                                 "account_id": acc, "equipment_id": eq["id"]})
    ins(c, "hire_bills", {"agreement_id": ag["id"], "month": m, "units": r2(units), "billed_units": r2(billed),
                          "amount": amount, "invoice_id": iid})
    return {"invoice_id": iid, "units": r2(units), "billed": r2(billed)}


@api("hire.bills", "equipment", "view")
def hire_bills(c, u, a):
    return q(c, "SELECT b.*, i.status invoice_status, i.no invoice_no FROM hire_bills b LEFT JOIN invoices i "
                "ON i.id=b.invoice_id ORDER BY b.month DESC")


def dep_amount(c, eq, m):
    base = (eq["purchase_value"] or 0) - (eq["residual_value"] or 0)
    left = base - (eq["accumulated_dep"] or 0)
    if left <= 0.005 or not eq["purchase_value"]:
        return 0
    if eq["purchase_date"] and eq["purchase_date"][:7] > m:
        return 0
    meth = eq["dep_method"] or "sl"
    if meth == "wdv":
        amt = ((eq["purchase_value"] or 0) - (eq["accumulated_dep"] or 0)) * (eq["wdv_rate"] or 0) / 100 / 12
    elif meth == "hours":
        hrs = val(c, "SELECT SUM(hours) FROM logsheets WHERE equipment_id=? AND date BETWEEN ? AND ?",
                  (eq["id"], m + "-01", month_end(m)))
        amt = base / eq["est_total_hours"] * hrs if eq["est_total_hours"] else 0
    else:
        amt = base / eq["life_months"] if eq["life_months"] else 0
    return r2(min(amt, left))


@api("dep.preview", "accounts", "view")
def dep_preview(c, u, a):
    m = a["month"]
    rows = []
    for eq in q(c, "SELECT * FROM equipment WHERE ownership='owned' AND active=1 AND purchase_value>0"):
        done = q1(c, "SELECT amount FROM dep_runs WHERE equipment_id=? AND month=?", (eq["id"], m))
        rows.append({"equipment_id": eq["id"], "code": eq["code"], "name": eq["name"], "method": eq["dep_method"],
                     "book_value": r2(eq["purchase_value"] - (eq["accumulated_dep"] or 0)),
                     "amount": done["amount"] if done else dep_amount(c, eq, m), "posted": bool(done)})
    return rows


@api("dep.run", "accounts", "edit")
def dep_run(c, u, a):
    m = a.get("month") or ""
    if len(m) != 7:
        raise ApiError("Choose a month.")
    if m >= today()[:7]:
        raise ApiError("Depreciation can be run only for completed months.")
    total, n = 0, 0
    for eq in q(c, "SELECT * FROM equipment WHERE ownership='owned' AND active=1 AND purchase_value>0"):
        if q1(c, "SELECT id FROM dep_runs WHERE equipment_id=? AND month=?", (eq["id"], m)):
            continue
        amt = dep_amount(c, eq, m)
        if amt <= 0:
            continue
        vid = post_voucher(c, u, "journal", month_end(m), "Depreciation %s %s" % (eq["code"], m),
                           [{"role": "depreciation", "debit": amt, "equipment_id": eq["id"],
                             "project_id": eq["project_id"]},
                            {"role": "accum_dep", "credit": amt, "equipment_id": eq["id"]}],
                           project_id=eq["project_id"], source="depreciation", source_id=eq["id"])
        ins(c, "dep_runs", {"equipment_id": eq["id"], "month": m, "amount": amt, "voucher_id": vid})
        upd(c, "equipment", eq["id"], {"accumulated_dep": r2((eq["accumulated_dep"] or 0) + amt)})
        total += amt
        n += 1
    return {"count": n, "total": r2(total)}


@api("internal.preview", "equipment", "view")
def internal_preview(c, u, a):
    m = a["month"]
    rows = q(c, "SELECT l.equipment_id, l.project_id, SUM(l.hours) hours, e.code, e.name, e.internal_rate FROM "
                "logsheets l JOIN equipment e ON e.id=l.equipment_id WHERE e.ownership='owned' AND e.internal_rate>0 "
                "AND l.dpr_id IS NULL AND l.date BETWEEN ? AND ? GROUP BY l.equipment_id, l.project_id", (m + "-01", month_end(m)))
    for r in rows:
        r["amount"] = r2(r["hours"] * r["internal_rate"])
        r["posted"] = bool(q1(c, "SELECT id FROM internal_bills WHERE equipment_id=? AND project_id=? AND month=?",
                              (r["equipment_id"], r["project_id"], m)))
    return rows


@api("internal.run", "accounts", "edit")
def internal_run(c, u, a):
    m = a.get("month") or ""
    n, total = 0, 0
    for r in internal_preview(c, u, {"month": m}):
        if r["posted"] or r["amount"] <= 0:
            continue
        vid = post_voucher(c, u, "journal", month_end(m), "Internal hire %s %s (%s h)" % (r["code"], m, r["hours"]),
                           [{"role": "equipment_cost", "debit": r["amount"], "equipment_id": r["equipment_id"],
                             "project_id": r["project_id"]},
                            {"role": "equipment_recovery", "credit": r["amount"], "equipment_id": r["equipment_id"],
                             "project_id": r["project_id"]}],
                           project_id=r["project_id"], source="internal_billing", source_id=r["equipment_id"])
        ins(c, "internal_bills", {"equipment_id": r["equipment_id"], "project_id": r["project_id"], "month": m,
                                  "hours": r["hours"], "rate": r["internal_rate"], "amount": r["amount"],
                                  "voucher_id": vid})
        n += 1
        total += r["amount"]
    return {"count": n, "total": r2(total)}


# ───────────────────────── equipment KPIs ─────────────────────────
def eq_costs(c, eq_id, frm, to):
    return q(c, "SELECT a.role, a.name, SUM(l.debit-l.credit) amt FROM voucher_lines l JOIN vouchers v ON "
                "v.id=l.voucher_id JOIN accounts a ON a.id=l.account_id WHERE l.equipment_id=? AND a.type='expense' "
                "AND " + POSTED + " AND v.date BETWEEN ? AND ? GROUP BY a.id", (eq_id, frm, to))


@api("eq.kpi", "equipment", "view")
def eq_kpi(c, u, a):
    frm = a.get("from") or (date.today() - timedelta(days=30)).isoformat()
    to = a.get("to") or today()
    days = (date.fromisoformat(to) - date.fromisoformat(frm)).days + 1
    sh = fsetting(c, "shift_hours") or 10
    cond, p = "active=1 AND status<>'disposed'", []
    if a.get("project_id"):
        cond += " AND project_id=?"
        p.append(a["project_id"])
    out = []
    for eq in q(c, "SELECT * FROM equipment WHERE " + cond + " ORDER BY code", p):
        lg = q1(c, "SELECT SUM(hours) h, SUM(idle_hours) i, SUM(breakdown_hours) b, COUNT(DISTINCT date) d, "
                   "MAX(date) last FROM logsheets WHERE equipment_id=? AND date BETWEEN ? AND ?", (eq["id"], frm, to))
        wos = q(c, "SELECT downtime_hours FROM work_orders WHERE equipment_id=? AND type='breakdown' AND "
                   "status='completed' AND substr(completed_at,1,10) BETWEEN ? AND ?", (eq["id"], frm, to))
        fuel = val(c, "SELECT SUM(l.qty-l.returned_qty) FROM issue_lines l JOIN issues i ON i.id=l.issue_id JOIN "
                      "materials m ON m.id=l.material_id WHERE i.status='posted' AND l.equipment_id=? AND "
                      "(lower(m.category) LIKE '%fuel%') AND i.date BETWEEN ? AND ?", (eq["id"], frm, to))
        work = lg["h"] or 0
        bd = max(lg["b"] or 0, sum(w["downtime_hours"] for w in wos) if wos else 0)
        sched = days * sh
        avail = max(sched - bd, 0)
        cost = sum(x["amt"] for x in eq_costs(c, eq["id"], frm, to))
        last = lg["last"]
        idle_days = (date.fromisoformat(to) - date.fromisoformat(last)).days if last else None
        out.append({"id": eq["id"], "code": eq["code"], "name": eq["name"], "status": eq["status"],
                    "project_id": eq["project_id"], "working_hours": r2(work), "idle_hours": r2(lg["i"] or 0),
                    "breakdown_hours": r2(bd), "days_logged": lg["d"] or 0,
                    "availability_pct": round(100 * avail / sched, 1) if sched else None,
                    "utilisation_pct": round(100 * work / avail, 1) if avail else None,
                    "breakdowns": len(wos), "mttr": r2(sum(w["downtime_hours"] for w in wos) / len(wos)) if wos else None,
                    "mtbf": r2(work / len(wos)) if wos else None, "fuel": r2(fuel),
                    "fuel_per_hour": r2(fuel / work) if work else None, "fuel_norm": eq["fuel_norm"],
                    "fuel_flag": bool(work and eq["fuel_norm"] and fuel / work > eq["fuel_norm"] * 1.15),
                    "cost": r2(cost), "cost_per_hour": r2(cost / work) if work else None,
                    "internal_rate": eq["internal_rate"], "days_since_log": idle_days})
    return {"from": frm, "to": to, "rows": out}


@api("eq.passport", "equipment", "view")
def eq_passport(c, u, a):
    eq = get(c, "equipment", a["id"], "Equipment")
    return {"equipment": eq,
            "status_log": q(c, "SELECT * FROM equipment_status_log WHERE equipment_id=? ORDER BY id DESC LIMIT 30", (eq["id"],)),
            "deployments": q(c, "SELECT * FROM deployments WHERE equipment_id=? ORDER BY mob_date DESC", (eq["id"],)),
            "logs": q(c, "SELECT * FROM logsheets WHERE equipment_id=? ORDER BY date DESC LIMIT 30", (eq["id"],)),
            "books": q(c, "SELECT b.*, (SELECT COUNT(*) FROM logsheets l WHERE l.book_id=b.id) days, "
                          "(SELECT ROUND(SUM(l.hours),2) FROM logsheets l WHERE l.book_id=b.id) hours, "
                          "(SELECT ROUND(SUM(l.fuel_qty),2) FROM logsheets l WHERE l.book_id=b.id) fuel "
                          "FROM logbooks b WHERE b.equipment_id=? ORDER BY b.period DESC LIMIT 36", (eq["id"],)),
            "service": q(c, "SELECT s.*, b.period FROM log_service s JOIN logbooks b ON b.id=s.book_id "
                            "WHERE s.equipment_id=? ORDER BY s.date DESC LIMIT 60", (eq["id"],)),
            "work_orders": q(c, "SELECT * FROM work_orders WHERE equipment_id=? ORDER BY id DESC LIMIT 30", (eq["id"],)),
            "plans": maint_status(c, u, {"equipment_id": eq["id"]}),
            "costs": eq_costs(c, eq["id"], "0000-01-01", "9999-12-31"),
            "materials": q(c, "SELECT i.date, i.no, l.material_id, l.qty, l.amount FROM issue_lines l JOIN issues i ON "
                              "i.id=l.issue_id WHERE l.equipment_id=? AND i.status='posted' ORDER BY i.date DESC LIMIT 50",
                           (eq["id"],))}


# ───────────────────────── accounting reports ─────────────────────────
def signed_ob(acc):
    return acc["opening_balance"] or 0


@api("rep.tb", "accounts", "view")
def rep_tb(c, u, a):
    frm, to = a.get("from") or "0000-01-01", a.get("to") or today()
    pj = a.get("project_id")
    pc, pp = (" AND l.project_id=?", [pj]) if pj else ("", [])
    rows = []
    for acc in q(c, "SELECT * FROM accounts ORDER BY code"):
        op = val(c, "SELECT SUM(l.debit-l.credit) FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id WHERE "
                    "l.account_id=? AND " + POSTED + " AND v.date<?" + pc, [acc["id"], frm] + pp)
        if not pj:
            op += signed_ob(acc)
        mv = q1(c, "SELECT SUM(l.debit) d, SUM(l.credit) c FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id "
                   "WHERE l.account_id=? AND " + POSTED + " AND v.date BETWEEN ? AND ?" + pc,
                [acc["id"], frm, to] + pp)
        d, cr = mv["d"] or 0, mv["c"] or 0
        if abs(op) < 0.005 and abs(d) < 0.005 and abs(cr) < 0.005:
            continue
        rows.append({"id": acc["id"], "code": acc["code"], "name": acc["name"], "type": acc["type"],
                     "group_id": acc["group_id"], "opening": r2(op), "debit": r2(d), "credit": r2(cr),
                     "closing": r2(op + d - cr)})
    return rows


@api("rep.ledger", "accounts", "view")
def rep_ledger(c, u, a):
    need(a, "account_id")
    acc = get(c, "accounts", a["account_id"], "Account")
    frm, to = a.get("from") or "0000-01-01", a.get("to") or today()
    cond, p = "", []
    for k in ("project_id", "party_id", "equipment_id"):
        if a.get(k):
            cond += " AND l.%s=?" % k
            p.append(a[k])
    op = val(c, "SELECT SUM(l.debit-l.credit) FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id WHERE "
                "l.account_id=? AND " + POSTED + " AND v.date<?" + cond, [acc["id"], frm] + p)
    if not cond:
        op += signed_ob(acc)
    rows = q(c, "SELECT l.*, v.no, v.date, v.narration vnar, v.type, v.source, v.source_id, v.ref_no FROM "
                "voucher_lines l JOIN vouchers v ON v.id=l.voucher_id WHERE l.account_id=? AND " + POSTED +
             " AND v.date BETWEEN ? AND ?" + cond + " ORDER BY v.date, v.id, l.id", [acc["id"], frm, to] + p)
    bal = op
    for r in rows:
        bal += r["debit"] - r["credit"]
        r["balance"] = r2(bal)
    return {"account": acc, "opening": r2(op), "rows": rows, "closing": r2(bal)}


@api("rep.daybook", "accounts", "view")
def rep_daybook(c, u, a):
    frm, to = a.get("from") or today(), a.get("to") or today()
    vs = q(c, "SELECT * FROM vouchers v WHERE " + POSTED + " AND v.date BETWEEN ? AND ? ORDER BY date, id", (frm, to))
    for v in vs:
        v["lines"] = q(c, "SELECT l.debit, l.credit, l.narration, a.code, a.name FROM voucher_lines l JOIN accounts a "
                          "ON a.id=l.account_id WHERE l.voucher_id=? ORDER BY l.id", (v["id"],))
    return vs


def _type_totals(c, types, frm, to, pj):
    pc, pp = (" AND l.project_id=?", [pj]) if pj else ("", [])
    return q(c, "SELECT a.id, a.code, a.name, a.type, a.group_id, SUM(l.debit-l.credit) amt FROM voucher_lines l "
                "JOIN vouchers v ON v.id=l.voucher_id JOIN accounts a ON a.id=l.account_id WHERE a.type IN (%s) AND "
                % ",".join("?" * len(types)) + POSTED + " AND v.date BETWEEN ? AND ?" + pc +
             " GROUP BY a.id ORDER BY a.code", list(types) + [frm, to] + pp)


@api("rep.pl", "accounts", "view")
def rep_pl(c, u, a):
    frm, to = a.get("from") or "0000-01-01", a.get("to") or today()
    rows = _type_totals(c, ("income", "expense"), frm, to, a.get("project_id"))
    inc = [dict(r, amount=r2(-r["amt"])) for r in rows if r["type"] == "income" and abs(r["amt"]) > 0.004]
    exp = [dict(r, amount=r2(r["amt"])) for r in rows if r["type"] == "expense" and abs(r["amt"]) > 0.004]
    ti, te = r2(sum(r["amount"] for r in inc)), r2(sum(r["amount"] for r in exp))
    return {"income": inc, "expense": exp, "total_income": ti, "total_expense": te, "profit": r2(ti - te)}


@api("rep.bs", "accounts", "view")
def rep_bs(c, u, a):
    to = a.get("as_of") or today()
    sections = {"asset": [], "liability": [], "equity": []}
    for acc in q(c, "SELECT * FROM accounts WHERE type IN ('asset','liability','equity') ORDER BY code"):
        b = signed_ob(acc) + val(c, "SELECT SUM(l.debit-l.credit) FROM voucher_lines l JOIN vouchers v ON "
                                    "v.id=l.voucher_id WHERE l.account_id=? AND " + POSTED + " AND v.date<=?",
                                 (acc["id"], to))
        amt = b if acc["type"] == "asset" else -b
        if abs(amt) > 0.004:
            sections[acc["type"]].append({"id": acc["id"], "code": acc["code"], "name": acc["name"],
                                          "group_id": acc["group_id"], "amount": r2(amt)})
    pl = rep_pl(c, u, {"from": "0000-01-01", "to": to})
    ob_pl = sum(-signed_ob(x) if x["type"] == "income" else signed_ob(x)
                for x in q(c, "SELECT * FROM accounts WHERE type IN ('income','expense')"))
    profit = r2(pl["profit"] - ob_pl)
    ta = r2(sum(x["amount"] for x in sections["asset"]))
    tl = r2(sum(x["amount"] for x in sections["liability"]))
    te = r2(sum(x["amount"] for x in sections["equity"]) + profit)
    return {"assets": sections["asset"], "liabilities": sections["liability"], "equity": sections["equity"],
            "profit": profit, "total_assets": ta, "total_liabilities": tl, "total_equity": te,
            "difference": r2(ta - tl - te)}


PARTY_ROLES = ("ap_control", "ar_control", "supplier_advance", "subcon_advance", "client_advance",
               "retention_payable", "retention_receivable", "grni")


@api("rep.party", "accounts", "view")
def rep_party(c, u, a):
    need(a, "party_id")
    party = get(c, "parties", a["party_id"], "Party")
    frm, to = a.get("from") or "0000-01-01", a.get("to") or today()
    roles = ",".join("'%s'" % r for r in PARTY_ROLES)
    base = ("FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id JOIN accounts a ON a.id=l.account_id "
            "WHERE l.party_id=? AND a.role IN (%s) AND " % roles) + POSTED
    op = val(c, "SELECT SUM(l.debit-l.credit) " + base + " AND v.date<?", (party["id"], frm))
    rows = q(c, "SELECT l.debit, l.credit, l.narration, a.name account, a.role, v.no, v.date, v.narration vnar, "
                "v.ref_no " + base + " AND v.date BETWEEN ? AND ? ORDER BY v.date, v.id", (party["id"], frm, to))
    bal = op
    for r in rows:
        bal += r["debit"] - r["credit"]
        r["balance"] = r2(bal)
    by_role = q(c, "SELECT a.role, a.name, SUM(l.debit-l.credit) amt " + base + " AND v.date<=? GROUP BY a.id",
                (party["id"], to))
    return {"party": party, "opening": r2(op), "rows": rows, "closing": r2(bal), "by_account": by_role,
            "note": "Positive balance = party owes us; negative = we owe the party."}


@api("rep.party_summary", "accounts", "view")
def rep_party_summary(c, u, a):
    """Everyone we owe or who owes us, on one page. Click a line for that party's own statement."""
    frm, to = a.get("from") or "0000-01-01", a.get("to") or today()
    roles = ",".join("'%s'" % r for r in PARTY_ROLES)
    kind = a.get("kind") or ""
    rows = []
    parties = q(c, "SELECT * FROM parties%s ORDER BY name" % (" WHERE kind=?" if kind else ""),
                (kind,) if kind else ())
    for p in parties:
        base = ("FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id JOIN accounts x ON x.id=l.account_id "
                "WHERE l.party_id=? AND x.role IN (%s) AND " % roles) + POSTED
        op = val(c, "SELECT SUM(l.debit-l.credit) " + base + " AND v.date<?", (p["id"], frm))
        mv = q1(c, "SELECT SUM(l.debit) d, SUM(l.credit) cr " + base + " AND v.date BETWEEN ? AND ?",
                (p["id"], frm, to))
        d, cr = mv["d"] or 0, mv["cr"] or 0
        adv = val(c, "SELECT SUM(l.debit-l.credit) FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id "
                     "JOIN accounts x ON x.id=l.account_id WHERE l.party_id=? AND x.role IN "
                     "('supplier_advance','subcon_advance') AND v.date<=? AND " + POSTED, (p["id"], to))
        cadv = val(c, "SELECT SUM(l.credit-l.debit) FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id "
                      "JOIN accounts x ON x.id=l.account_id WHERE l.party_id=? AND x.role='client_advance' AND "
                      "v.date<=? AND " + POSTED, (p["id"], to))
        ret = val(c, "SELECT SUM(l.credit-l.debit) FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id "
                     "JOIN accounts x ON x.id=l.account_id WHERE l.party_id=? AND x.role IN "
                     "('retention_payable','retention_receivable') AND v.date<=? AND " + POSTED, (p["id"], to))
        closing = r2(op + d - cr)
        if abs(op) < 0.005 and abs(d) < 0.005 and abs(cr) < 0.005 and abs(adv) < 0.005:
            continue
        rows.append({"id": p["id"], "party_id": p["id"], "code": p["code"], "name": p["name"], "kind": p["kind"],
                     "phone": p["phone"], "opening": r2(op), "debit": r2(d), "credit": r2(cr), "closing": closing,
                     "advance": r2(adv), "client_advance": r2(cadv), "retention": r2(ret),
                     "owed_to_them": r2(-closing) if closing < 0 else 0,
                     "owed_by_them": r2(closing) if closing > 0 else 0})
    return rows


@api("rep.ageing", "accounts", "view")
def rep_ageing(c, u, a):
    kind = a.get("kind") or "purchase"
    asof = a.get("as_of") or today()
    cond, p = "", [kind, asof]
    if a.get("project_id"):
        cond = " AND project_id=?"
        p.append(a["project_id"])
    out = {}
    for inv in q(c, "SELECT * FROM invoices WHERE kind=? AND status='posted' AND date<=?" + cond, p):
        paid = val(c, "SELECT SUM(amount) FROM allocations WHERE invoice_id=? AND active=1 AND date<=?", (inv["id"], asof))
        bal = r2(inv["payable"] - paid)
        if bal <= 0.004:
            continue
        days = (date.fromisoformat(asof) - date.fromisoformat(inv["due_date"] or inv["date"])).days
        b = "current" if days <= 0 else "d30" if days <= 30 else "d60" if days <= 60 else "d90" if days <= 90 else "d90p"
        row = out.setdefault(inv["party_id"], {"party_id": inv["party_id"], "current": 0, "d30": 0, "d60": 0,
                                               "d90": 0, "d90p": 0, "total": 0, "invoices": []})
        row[b] = r2(row[b] + bal)
        row["total"] = r2(row["total"] + bal)
        row["invoices"].append({"id": inv["id"], "no": inv["no"], "date": inv["date"], "due_date": inv["due_date"],
                                "balance": bal, "days": days})
    return sorted(out.values(), key=lambda r: -r["total"])


@api("rep.vat", "accounts", "view")
def rep_vat(c, u, a):
    kind = a.get("kind") or "purchase"
    rows = q(c, "SELECT i.*, p.name party_name, p.pan FROM invoices i JOIN parties p ON p.id=i.party_id WHERE "
                "i.kind=? AND i.status='posted' AND i.date BETWEEN ? AND ? ORDER BY i.date, i.id",
             (kind, a.get("from") or "0000", a.get("to") or today()))
    for r in rows:
        r["taxable"] = r2(val(c, "SELECT SUM(amount) FROM invoice_lines WHERE invoice_id=? AND vat_rate>0", (r["id"],)))
        r["exempt"] = r2(r["subtotal"] - r["taxable"])
    return rows


@api("rep.tds", "accounts", "view")
def rep_tds(c, u, a):
    frm, to = a.get("from") or "0000", a.get("to") or today()
    paid = q(c, "SELECT pm.date, pm.no, pm.gross, pm.tds, p.name party_name, p.pan, t.section, t.rate, t.description "
                "FROM payments pm JOIN parties p ON p.id=pm.party_id LEFT JOIN tds_rates t ON t.id=pm.tds_rate_id "
                "WHERE pm.status='posted' AND pm.tds>0 AND pm.date BETWEEN ? AND ? ORDER BY pm.date", (frm, to))
    suffered = q(c, "SELECT i.date, i.no, i.subtotal gross, i.tds, p.name party_name, p.pan FROM invoices i JOIN "
                    "parties p ON p.id=i.party_id WHERE i.kind='sales' AND i.status='posted' AND i.tds>0 AND "
                    "i.date BETWEEN ? AND ? ORDER BY i.date", (frm, to))
    acc = val(c, "SELECT id FROM accounts WHERE role='tds_payable'")
    deposited = val(c, "SELECT SUM(l.debit) FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id WHERE "
                       "l.account_id=? AND " + POSTED + " AND v.date BETWEEN ? AND ?", (acc, frm, to))
    return {"deducted": paid, "suffered": suffered, "total_deducted": r2(sum(r["tds"] for r in paid)),
            "total_deposited": r2(deposited), "total_suffered": r2(sum(r["tds"] for r in suffered))}


@api("rep.budget", "accounts", "view")
def rep_budget(c, u, a):
    need(a, "project_id")
    rows = q(c, "SELECT b.*, a.code, a.name, a.role FROM budgets b JOIN accounts a ON a.id=b.account_id WHERE "
                "b.project_id=? ORDER BY a.code", (a["project_id"],))
    for r in rows:
        cond, p = "", [r["account_id"], a["project_id"]]
        if r["boq_item_id"]:
            cond = " AND l.boq_item_id=?"
            p.append(r["boq_item_id"])
        r["actual"] = r2(val(c, "SELECT SUM(l.debit-l.credit) FROM voucher_lines l JOIN vouchers v ON "
                                "v.id=l.voucher_id WHERE l.account_id=? AND l.project_id=? AND " + POSTED + cond, p))
        r["committed"] = budget_check(c, a["project_id"])["committed"] if r["role"] == "material_cost" and \
            not r["boq_item_id"] else 0
        r["available"] = r2(r["amount"] - r["actual"] - r["committed"])
        r["used_pct"] = round(100 * (r["actual"] + r["committed"]) / r["amount"], 1) if r["amount"] else None
    pl = rep_pl(c, u, {"project_id": a["project_id"]})
    proj = get(c, "projects", a["project_id"])
    return {"rows": rows, "project": proj, "revenue": pl["total_income"], "cost": pl["total_expense"],
            "margin": pl["profit"]}


@api("rep.boq_cost", "accounts", "view")
def rep_boq_cost(c, u, a):
    need(a, "project_id")
    rows = q(c, "SELECT * FROM boq_items WHERE project_id=? ORDER BY code", (a["project_id"],))
    for r in rows:
        r["amount"] = r2(r["qty"] * r["rate"])
        r["earned"] = r2((r["executed_qty"] or 0) * r["rate"])
        r["cost"] = r2(val(c, "SELECT SUM(l.debit-l.credit) FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id "
                              "JOIN accounts a ON a.id=l.account_id WHERE a.type='expense' AND l.boq_item_id=? AND "
                           + POSTED, (r["id"],)))
        r["progress_pct"] = round(100 * (r["executed_qty"] or 0) / r["qty"], 1) if r["qty"] else 0
        r["margin"] = r2(r["earned"] - r["cost"])
    return rows


def role_balance(c, role, project_id=None):
    cond, p = "", [role]
    if project_id:
        cond = " AND l.project_id=?"
        p.append(project_id)
    b = val(c, "SELECT SUM(l.debit-l.credit) FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id JOIN accounts a "
               "ON a.id=l.account_id WHERE a.role=? AND " + POSTED + cond, p)
    if not project_id:
        b += val(c, "SELECT SUM(opening_balance) FROM accounts WHERE role=?", (role,))
    return r2(b)


@api("rep.integrity", "accounts", "view")
def rep_integrity(c, u, a):
    checks = []

    def add(name, ok, detail):
        checks.append({"check": name, "ok": bool(ok), "detail": detail})
    bad = q(c, "SELECT v.no FROM vouchers v JOIN voucher_lines l ON l.voucher_id=v.id GROUP BY v.id "
               "HAVING ABS(SUM(l.debit)-SUM(l.credit))>0.01")
    add("All vouchers balance", not bad, ", ".join(x["no"] or "draft" for x in bad) or "No unbalanced vouchers")
    for p in q(c, "SELECT id, code FROM projects"):
        stock = r2(val(c, "SELECT SUM(value) FROM stock_balances WHERE project_id=?", (p["id"],)))
        books = r2(sum(role_balance(c, r, p["id"]) for r in ("inventory", "inventory_fuel", "inventory_spares")))
        add("Stock value = inventory accounts (%s)" % p["code"], abs(stock - books) < 1,
            "Stores %s, books %s" % (stock, books))
    grni = r2(-role_balance(c, "grni"))
    unbilled = r2(val(c, "SELECT SUM((l.accepted_qty-l.invoiced_qty)*l.rate) FROM grn_lines l JOIN grn g ON "
                         "g.id=l.grn_id WHERE g.status='posted'"))
    add("GRN clearing = received but not invoiced", abs(grni - unbilled) < 1, "Books %s, GRNs %s" % (grni, unbilled))
    ap = r2(-role_balance(c, "ap_control"))
    open_ap = r2(sum(i["payable"] - invoice_paid(c, i["id"]) for i in
                     q(c, "SELECT id, payable FROM invoices WHERE kind='purchase' AND status='posted'")))
    add("Creditors = open purchase invoices", abs(ap - open_ap) < 1, "Books %s, invoices %s" % (ap, open_ap))
    ar = r2(role_balance(c, "ar_control"))
    open_ar = r2(sum(i["payable"] - invoice_paid(c, i["id"]) for i in
                     q(c, "SELECT id, payable FROM invoices WHERE kind='sales' AND status='posted'")))
    add("Debtors = open sales invoices", abs(ar - open_ar) < 1, "Books %s, invoices %s" % (ar, open_ar))
    neg = q(c, "SELECT b.qty, m.code, s.name FROM stock_balances b JOIN materials m ON m.id=b.material_id JOIN stores s "
               "ON s.id=b.store_id WHERE b.qty<-0.0001")
    add("No negative stock", not neg, ", ".join("%s @ %s (%s)" % (x["code"], x["name"], r4(x["qty"])) for x in neg)
        or "None")
    transit = q(c, "SELECT no, date FROM transfers WHERE status='in_transit' AND date<?",
                ((date.today() - timedelta(days=7)).isoformat(),))
    add("No transfers in transit over 7 days", not transit, ", ".join(t["no"] for t in transit) or "None")
    from core import DEFAULT_ACCOUNTS
    missing = [r[4] for r in DEFAULT_ACCOUNTS if not val(c, "SELECT COUNT(*) FROM accounts WHERE role=? AND active=1",
                                                         (r[4],))]
    add("Every posting role has an account", not missing, ", ".join(missing) or "All set")
    bs = rep_bs(c, u, {})
    add("Balance sheet balances", abs(bs["difference"]) < 1, "Difference %s" % bs["difference"])
    return checks


# ───────────────────────── dashboard & approvals ─────────────────────────
@api("dash.approvals")
def dash_approvals(c, u, a):
    items = []

    def add(kind, module, label, rows, amount_key=None):
        for r in rows:
            items.append({"kind": kind, "label": label, "id": r["id"], "no": r.get("no"), "date": r.get("date"),
                          "project_id": r.get("project_id"), "amount": r.get(amount_key) if amount_key else None,
                          "can_approve": can(u, module, "approve")})
    add("mrq", "inventory", "Material requisition", q(c, "SELECT * FROM mrq WHERE status='submitted'"))
    add("pr", "procurement", "Purchase request", q(c, "SELECT * FROM pr WHERE status='submitted'"))
    add("cs", "procurement", "Comparative statement", q(c, "SELECT * FROM cs WHERE status='submitted'"))
    add("po", "procurement", "Purchase order", q(c, "SELECT * FROM po WHERE status='pending_approval'"), "total")
    add("voucher", "accounts", "Voucher", q(c, "SELECT * FROM vouchers WHERE status='draft' AND source='manual'"), "total")
    add("log", "equipment", "Logsheets", q(c, "SELECT MIN(id) id, COUNT(*) no, MAX(date) date, project_id FROM logsheets "
                                            "WHERE status='draft' GROUP BY project_id"))
    add("count", "inventory", "Stock count", q(c, "SELECT * FROM stock_counts WHERE status='draft'"))
    return items


@api("dash.summary")
def dash_summary(c, u, a):
    run_daily(c, u)
    pj = a.get("project_id")
    t = today()
    pc = " AND project_id=%d" % int(pj) if pj else ""
    out = {"approvals": len(dash_approvals(c, u, {})), "alerts": []}
    if can(u, "inventory", "view"):
        low = [r for r in __import__("api_inventory").stock_report(c, u, {"project_id": pj, "group": "material"})
               if r.get("flag")]
        out["low_stock"] = low[:15]
        out["stock_value"] = r2(val(c, "SELECT SUM(b.value) FROM stock_balances b WHERE 1=1" +
                                       (" AND b.project_id=%d" % int(pj) if pj else "")))
        out["in_transit"] = val(c, "SELECT COUNT(*) FROM transfers WHERE status='in_transit'")
        out["open_mrq"] = val(c, "SELECT COUNT(*) FROM mrq WHERE status IN ('approved','partially_issued')" + pc)
    if can(u, "procurement", "view"):
        from api_finance import po_pending
        pend = po_pending(c, u, {"project_id": pj})
        out["pending_deliveries"] = len(pend)
        out["overdue_deliveries"] = len([p for p in pend if p["overdue_days"] > 0])
        out["open_po_value"] = r2(sum(p["pending_value"] for p in pend))
    if can(u, "accounts", "view"):
        out["payables_due"] = r2(sum(r["total"] - r["current"] for r in rep_ageing(c, u, {"kind": "purchase",
                                                                                            "project_id": pj})))
        out["receivables_due"] = r2(sum(r["total"] - r["current"] for r in rep_ageing(c, u, {"kind": "sales",
                                                                                               "project_id": pj})))
        out["cash_bank"] = q(c, "SELECT id, code, name FROM accounts WHERE role IN ('cash','bank') AND active=1")
        for acc in out["cash_bank"]:
            acc["balance"] = r2(rep_ledger(c, u, {"account_id": acc["id"]})["closing"])
        m0 = t[:7] + "-01"
        pl = rep_pl(c, u, {"from": m0, "to": t, "project_id": pj})
        out["month_cost"], out["month_revenue"] = pl["total_expense"], pl["total_income"]
        out["cost_trend"] = []
        d0 = date.today().replace(day=1)
        for i in range(5, -1, -1):
            y, m = d0.year, d0.month - i
            while m <= 0:
                m += 12
                y -= 1
            mm = "%04d-%02d" % (y, m)
            p2 = rep_pl(c, u, {"from": mm + "-01", "to": month_end(mm), "project_id": pj})
            out["cost_trend"].append({"month": mm, "cost": p2["total_expense"], "revenue": p2["total_income"]})
    if can(u, "equipment", "view"):
        due = [x for x in maint_status(c, u, {}) if x["due"]]
        out["maintenance_due"] = due[:15]
        soon = (date.today() + timedelta(days=30)).isoformat()
        out["compliance"] = q(c, "SELECT id, code, name, insurance_expiry, registration_expiry FROM equipment WHERE "
                                 "active=1 AND ((insurance_expiry IS NOT NULL AND insurance_expiry<>'' AND "
                                 "insurance_expiry<=?) OR (registration_expiry IS NOT NULL AND registration_expiry<>'' "
                                 "AND registration_expiry<=?))", (soon, soon))
        out["breakdowns"] = q(c, "SELECT id, code, name FROM equipment WHERE status IN ('breakdown','under_maintenance')" + pc)
        wk = (date.today() - timedelta(days=7)).isoformat()
        out["idle"] = q(c, "SELECT id, code, name FROM equipment e WHERE active=1 AND status='working' AND project_id IS "
                           "NOT NULL" + pc + " AND NOT EXISTS (SELECT 1 FROM logsheets l WHERE l.equipment_id=e.id AND "
                           "l.date>=?)", (wk,))
    return out


def run_daily(c, u):
    if setting(c, "last_auto_run") == today():
        return
    c.execute("UPDATE settings SET value=? WHERE key='last_auto_run'", (today(),))
    try:
        auto_reorder(c, None)
    except ApiError:
        pass


# ───────────────────────── admin ─────────────────────────
@api("admin.users", "admin", "view")
def admin_users(c, u, a):
    return q(c, "SELECT id, username, name, role, active, location, phone, email FROM users ORDER BY username")


@api("admin.user_save", "admin", "edit")
def admin_user_save(c, u, a):
    r = a.get("row") or {}
    need(r, "username", "name", "role")
    if r["role"] not in ROLES:
        raise ApiError("Unknown role.")
    uname = r["username"].strip().lower()
    if q1(c, "SELECT id FROM users WHERE username=? AND id<>?", (uname, r.get("id") or 0)):
        raise ApiError("Username is taken.")
    data = {"username": uname, "name": r["name"], "role": r["role"], "active": int(num(r.get("active", 1))),
            "location": (r.get("location") or "").strip(), "phone": r.get("phone"), "email": r.get("email")}
    if r.get("id"):
        if int(r["id"]) == u["id"] and (data["role"] != "admin" or not data["active"]):
            raise ApiError("You cannot remove your own administrator access.")
        upd(c, "users", int(r["id"]), data)
        uid = int(r["id"])
    else:
        if len(r.get("password") or "") < 6:
            raise ApiError("Password must have at least 6 characters.")
        h, s = hash_pw(r["password"])
        data.update({"pw_hash": h, "salt": s})
        uid = ins(c, "users", data)
    if r.get("password") and r.get("id"):
        h, s = hash_pw(r["password"])
        upd(c, "users", uid, {"pw_hash": h, "salt": s})
        c.execute("DELETE FROM sessions WHERE user_id=?", (uid,))
    if not data["active"]:
        c.execute("DELETE FROM sessions WHERE user_id=?", (uid,))
    audit(c, u, "save", "users", uid, {k: v for k, v in data.items() if k not in ("pw_hash", "salt")})
    return {"id": uid}


@api("admin.settings", "admin", "edit")
def admin_settings(c, u, a):
    for k, v in (a.get("values") or {}).items():
        if k == "last_auto_run":
            continue
        c.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                  (k, str(v)))
    audit(c, u, "settings", "settings", None, a.get("values"))
    return True


@api("admin.audit", "admin", "view")
def admin_audit(c, u, a):
    cond, p = [], []
    if a.get("entity"):
        cond.append("entity=?")
        p.append(a["entity"])
    if a.get("user_id"):
        cond.append("user_id=?")
        p.append(a["user_id"])
    return q(c, "SELECT * FROM audit%s ORDER BY id DESC LIMIT %d" % (" WHERE " + " AND ".join(cond) if cond else "",
                                                                     int(a.get("limit") or 300)), p)


@api("admin.backup", "admin", "edit")
def admin_backup(c, u, a):
    import os
    c.commit()
    path = backup_now("manual")
    return {"file": os.path.basename(path)}


@api("admin.backups", "admin", "view")
def admin_backups(c, u, a):
    import os
    from core import BACKUP_DIR
    if not os.path.isdir(BACKUP_DIR):
        return []
    return [{"file": f, "size": os.path.getsize(os.path.join(BACKUP_DIR, f))}
            for f in sorted(os.listdir(BACKUP_DIR), reverse=True) if f.endswith(".db")]


@api("admin.reseed_accounts", "admin", "edit")
def admin_reseed(c, u, a):
    from core import DEFAULT_ACCOUNTS, DEFAULT_GROUPS
    added = 0
    for code, name, typ, parent in DEFAULT_GROUPS:
        if not q1(c, "SELECT id FROM account_groups WHERE code=?", (code,)):
            pid = val(c, "SELECT id FROM account_groups WHERE code=?", (parent,), None) if parent else None
            ins(c, "account_groups", {"code": code, "name": name, "type": typ, "parent_id": pid})
    for code, name, typ, grp, role in DEFAULT_ACCOUNTS:
        if not q1(c, "SELECT id FROM accounts WHERE role=?", (role,)) and not q1(c, "SELECT id FROM accounts WHERE code=?",
                                                                               (code,)):
            ins(c, "accounts", {"code": code, "name": name, "type": typ, "role": role, "opening_balance": 0,
                                "group_id": val(c, "SELECT id FROM account_groups WHERE code=?", (grp,)), "active": 1})
            added += 1
    return {"added": added}
